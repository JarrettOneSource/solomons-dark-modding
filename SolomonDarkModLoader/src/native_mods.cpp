#include "native_mods.h"

#include "binary_layout.h"
#include "debug_ui_overlay.h"
#include "logger.h"
#include "lua_engine.h"
#include "memory_access.h"
#include "multiplayer_foundation.h"
#include "runtime_flags.h"
#include "steam_bootstrap.h"

#include <Windows.h>

#include <algorithm>
#include <cctype>
#include <mutex>
#include <string>
#include <vector>

namespace sdmod {
namespace {

constexpr char kPluginInitializeExport[] = "SDModPlugin_Initialize";
constexpr char kPluginShutdownExport[] = "SDModPlugin_Shutdown";

struct LoadedNativeMod {
    std::string id;
    std::string name;
    std::string version;
    std::string api_version;
    std::string runtime_kind;
    std::string root_path;
    std::string manifest_path;
    std::string stage_root_path;
    std::string runtime_root_path;
    std::string sandbox_root_path;
    std::string data_root_path;
    std::string cache_root_path;
    std::string temp_root_path;
    std::string entry_script_path;
    std::string entry_dll_path;
    std::vector<std::string> required_capabilities;
    std::vector<std::string> optional_capabilities;
    std::vector<const char*> required_capability_ptrs;
    std::vector<const char*> optional_capability_ptrs;
    HMODULE module = nullptr;
    SDModPluginShutdownFn shutdown = nullptr;
};

std::mutex g_native_mods_mutex;
std::mutex g_runtime_tick_callbacks_mutex;
std::vector<LoadedNativeMod> g_loaded_native_mods;
std::vector<SDModRuntimeTickCallback> g_runtime_tick_callbacks;
RuntimeBootstrap g_runtime_bootstrap;

std::string ToLower(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char ch) {
        return static_cast<char>(std::tolower(ch));
    });
    return value;
}

void SDMOD_PLUGIN_CALL HostLog(const char* mod_id, const char* message) {
    const auto id = mod_id == nullptr || *mod_id == '\0' ? std::string("unknown") : std::string(mod_id);
    const auto text = message == nullptr ? std::string() : std::string(message);
    Log("[native][" + id + "] " + text);
}

bool HasDynamicCapability(std::string capability) {
    capability = ToLower(std::move(capability));
    if (capability == "log.write" || capability == "runtime.paths.read" || capability == "runtime.tick") {
        return true;
    }

    if (capability == "memory.resolve_game_address") {
        return IsBinaryLayoutLoaded();
    }

    if (capability == "debug.ui.overlay") {
        return IsDebugUiOverlayInitialized();
    }

    if (capability == "lua.engine") {
        return IsLuaEngineInitialized();
    }

    if (capability == "multiplayer.foundation") {
        return multiplayer::IsFoundationInitialized();
    }

    if (capability == "multiplayer.steam.bootstrap") {
        return GetSteamBootstrapSnapshot().initialized;
    }

    if (capability == "multiplayer.steam.transport") {
        return GetSteamBootstrapSnapshot().transport_interfaces_ready;
    }

    return false;
}

int SDMOD_PLUGIN_CALL HostHasCapability(const char* capability) {
    if (capability == nullptr || *capability == '\0') {
        return 0;
    }

    return HasDynamicCapability(capability) ? 1 : 0;
}

void* SDMOD_PLUGIN_CALL HostResolveGameAddress(uint64_t absolute_address) {
    return reinterpret_cast<void*>(ProcessMemory::Instance().ResolveGameAddressOrZero(
        static_cast<uintptr_t>(absolute_address)));
}

int SDMOD_PLUGIN_CALL HostRegisterRuntimeTickCallback(SDModRuntimeTickCallback callback) {
    if (callback == nullptr) {
        return 0;
    }

    std::scoped_lock lock(g_runtime_tick_callbacks_mutex);
    const auto existing = std::find(g_runtime_tick_callbacks.begin(), g_runtime_tick_callbacks.end(), callback);
    if (existing != g_runtime_tick_callbacks.end()) {
        return 1;
    }

    g_runtime_tick_callbacks.push_back(callback);
    return 1;
}

void SDMOD_PLUGIN_CALL HostUnregisterRuntimeTickCallback(SDModRuntimeTickCallback callback) {
    if (callback == nullptr) {
        return;
    }

    std::scoped_lock lock(g_runtime_tick_callbacks_mutex);
    g_runtime_tick_callbacks.erase(
        std::remove(g_runtime_tick_callbacks.begin(), g_runtime_tick_callbacks.end(), callback),
        g_runtime_tick_callbacks.end());
}

const SDModHostApi kHostApi = {
    sizeof(SDModHostApi),
    SDMOD_PLUGIN_HOST_ABI_VERSION,
    SDMOD_RUNTIME_API_VERSION,
    &HostLog,
    &HostHasCapability,
    &HostResolveGameAddress,
    &HostRegisterRuntimeTickCallback,
    &HostUnregisterRuntimeTickCallback,
};

void PrimeCapabilityPointers(std::vector<std::string>& source, std::vector<const char*>* target) {
    if (target == nullptr) {
        return;
    }

    target->clear();
    target->reserve(source.size());
    for (const auto& value : source) {
        target->push_back(value.c_str());
    }
}

bool SupportsRequiredCapabilities(const RuntimeModDescriptor& mod) {
    for (const auto& capability : mod.required_capabilities) {
        if (!HasDynamicCapability(capability)) {
            return false;
        }
    }

    return true;
}

void LoadNativeMod(const RuntimeBootstrap& bootstrap, const RuntimeModDescriptor& mod) {
    if (!mod.HasNativeEntry()) {
        return;
    }

    if (mod.api_version != SDMOD_RUNTIME_API_VERSION) {
        Log(
            "[native][" + mod.id + "] skipping mod due to apiVersion mismatch. host=" +
            std::string(SDMOD_RUNTIME_API_VERSION) + " mod=" + mod.api_version);
        return;
    }

    if (!SupportsRequiredCapabilities(mod)) {
        Log("[native][" + mod.id + "] skipping mod due to unsupported required capabilities.");
        return;
    }

    const auto module_handle = LoadLibraryW(mod.entry_dll_path.c_str());
    if (module_handle == nullptr) {
        Log(
            "[native][" + mod.id + "] failed to load DLL: " + mod.entry_dll_path.string() +
            " error=" + std::to_string(GetLastError()));
        return;
    }

    const auto initialize = reinterpret_cast<SDModPluginInitializeFn>(
        GetProcAddress(module_handle, kPluginInitializeExport));
    const auto shutdown = reinterpret_cast<SDModPluginShutdownFn>(GetProcAddress(module_handle, kPluginShutdownExport));
    if (initialize == nullptr) {
        Log("[native][" + mod.id + "] missing export: SDModPlugin_Initialize");
        FreeLibrary(module_handle);
        return;
    }

    LoadedNativeMod loaded_mod;
    loaded_mod.id = mod.id;
    loaded_mod.name = mod.name;
    loaded_mod.version = mod.version;
    loaded_mod.api_version = mod.api_version;
    loaded_mod.runtime_kind = mod.runtime_kind;
    loaded_mod.root_path = mod.root_path.string();
    loaded_mod.manifest_path = mod.manifest_path.string();
    loaded_mod.stage_root_path = bootstrap.stage_root.string();
    loaded_mod.runtime_root_path = bootstrap.runtime_root.string();
    loaded_mod.sandbox_root_path = mod.sandbox_root_path.string();
    loaded_mod.data_root_path = mod.data_root_path.string();
    loaded_mod.cache_root_path = mod.cache_root_path.string();
    loaded_mod.temp_root_path = mod.temp_root_path.string();
    loaded_mod.entry_script_path = mod.entry_script_path.string();
    loaded_mod.entry_dll_path = mod.entry_dll_path.string();
    loaded_mod.required_capabilities = mod.required_capabilities;
    loaded_mod.optional_capabilities = mod.optional_capabilities;
    PrimeCapabilityPointers(loaded_mod.required_capabilities, &loaded_mod.required_capability_ptrs);
    PrimeCapabilityPointers(loaded_mod.optional_capabilities, &loaded_mod.optional_capability_ptrs);

    g_loaded_native_mods.push_back(std::move(loaded_mod));
    auto& live_mod = g_loaded_native_mods.back();

    const SDModPluginContext plugin_context = {
        sizeof(SDModPluginContext),
        live_mod.id.c_str(),
        live_mod.name.c_str(),
        live_mod.version.c_str(),
        live_mod.api_version.c_str(),
        live_mod.runtime_kind.c_str(),
        live_mod.root_path.c_str(),
        live_mod.manifest_path.c_str(),
        live_mod.stage_root_path.c_str(),
        live_mod.runtime_root_path.c_str(),
        live_mod.sandbox_root_path.c_str(),
        live_mod.data_root_path.c_str(),
        live_mod.cache_root_path.c_str(),
        live_mod.temp_root_path.c_str(),
        live_mod.entry_script_path.c_str(),
        live_mod.entry_dll_path.c_str(),
        live_mod.required_capability_ptrs.data(),
        static_cast<uint32_t>(live_mod.required_capability_ptrs.size()),
        live_mod.optional_capability_ptrs.data(),
        static_cast<uint32_t>(live_mod.optional_capability_ptrs.size()),
    };

    if (initialize(&kHostApi, &plugin_context) == 0) {
        Log("[native][" + mod.id + "] plugin initialization returned failure.");
        FreeLibrary(module_handle);
        g_loaded_native_mods.pop_back();
        return;
    }

    live_mod.module = module_handle;
    live_mod.shutdown = shutdown;
    Log("[native][" + mod.id + "] loaded DLL mod: " + mod.entry_dll_path.string());
}

}  // namespace

bool InitializeNativeMods(const RuntimeBootstrap& bootstrap, std::string* error_message) {
    ShutdownNativeMods();
    if (error_message != nullptr) {
        error_message->clear();
    }

    std::scoped_lock lock(g_native_mods_mutex);
    g_runtime_bootstrap = bootstrap;
    g_loaded_native_mods.reserve(bootstrap.mods.size());

    for (const auto& mod : bootstrap.mods) {
        LoadNativeMod(bootstrap, mod);
    }

    Log(
        "Native mod host initialized. loaded_mods=" + std::to_string(g_loaded_native_mods.size()) +
        " discovered_mods=" + std::to_string(bootstrap.mods.size()));
    return true;
}

void ShutdownNativeMods() {
    std::scoped_lock native_lock(g_native_mods_mutex);
    {
        std::scoped_lock callback_lock(g_runtime_tick_callbacks_mutex);
        g_runtime_tick_callbacks.clear();
    }

    for (auto it = g_loaded_native_mods.rbegin(); it != g_loaded_native_mods.rend(); ++it) {
        if (it->shutdown != nullptr) {
            it->shutdown();
        }

        if (it->module != nullptr) {
            FreeLibrary(it->module);
        }
    }

    g_loaded_native_mods.clear();
    g_runtime_bootstrap = RuntimeBootstrap{};
}

std::size_t GetLoadedNativeModCount() {
    std::scoped_lock lock(g_native_mods_mutex);
    return g_loaded_native_mods.size();
}

bool HasLoadedNativeMods() {
    return GetLoadedNativeModCount() != 0;
}

void DispatchNativeModRuntimeTick(const SDModRuntimeTickContext& context) {
    std::vector<SDModRuntimeTickCallback> callbacks;
    {
        std::scoped_lock lock(g_runtime_tick_callbacks_mutex);
        callbacks = g_runtime_tick_callbacks;
    }

    for (const auto callback : callbacks) {
        if (callback != nullptr) {
            callback(&context);
        }
    }
}

}  // namespace sdmod
