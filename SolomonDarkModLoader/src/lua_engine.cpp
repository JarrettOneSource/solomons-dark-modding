#include "lua_engine.h"

#include "bot_runtime.h"
#include "logger.h"
#include "lua_engine_internal.h"
#include "mod_loader.h"
#include "multiplayer_foundation.h"

extern "C" {
#include "lauxlib.h"
#include "lua.h"
#include "lualib.h"
}

#include <algorithm>
#include <filesystem>
#include <memory>
#include <mutex>
#include <string>
#include <vector>

namespace sdmod {
namespace detail {
namespace {

void RemoveUnsafeGlobals(lua_State* state) {
    const char* globals_to_remove[] = {
        "debug",
        "dofile",
        "io",
        "loadfile",
        "os",
        "package",
        "require",
    };

    for (const auto* global_name : globals_to_remove) {
        lua_pushnil(state);
        lua_setglobal(state, global_name);
    }
}

int LuaPanic(lua_State* state) {
    const auto* message = lua_tostring(state, -1);
    Log(std::string("[lua] panic: ") + (message == nullptr ? "unknown" : message));
    return 0;
}

bool ExecuteEntryScript(LoadedLuaMod* mod, std::string* error_message) {
    if (mod == nullptr || mod->state == nullptr || error_message == nullptr) {
        return false;
    }

    const auto script_path = mod->descriptor.entry_script_path.string();
    if (luaL_loadfile(mod->state, script_path.c_str()) != LUA_OK) {
        *error_message = lua_tostring(mod->state, -1);
        lua_pop(mod->state, 1);
        return false;
    }

    if (lua_pcall(mod->state, 0, 0, 0) != LUA_OK) {
        *error_message = lua_tostring(mod->state, -1);
        lua_pop(mod->state, 1);
        return false;
    }

    return true;
}

}  // namespace

std::mutex& LuaEngineMutex() {
    static std::mutex mutex;
    return mutex;
}

bool& LuaEngineInitializedFlag() {
    static bool initialized = false;
    return initialized;
}

std::filesystem::path& LuaRuntimeDirectoryStorage() {
    static std::filesystem::path runtime_directory;
    return runtime_directory;
}

RuntimeBootstrap& LuaRuntimeBootstrapStorage() {
    static RuntimeBootstrap bootstrap;
    return bootstrap;
}

std::vector<std::unique_ptr<LoadedLuaMod>>& LoadedLuaModsStorage() {
    static std::vector<std::unique_ptr<LoadedLuaMod>> loaded_mods;
    return loaded_mods;
}

std::vector<std::string> BuildLuaCapabilitySet() {
    std::vector<std::string> capabilities = {
        "lua.engine",
        "events.runtime.tick",
        "runtime.mod.info",
        "ui.snapshot.read",
        "ui.element.query",
        "ui.action.query",
        "ui.action.activate",
    };

    if (multiplayer::IsFoundationInitialized()) {
        capabilities.emplace_back("multiplayer.foundation");
    }

    if (IsGameplayKeyboardInjectionInitialized()) {
        capabilities.emplace_back("input.keyboard.inject");
    }

    if (multiplayer::IsBotRuntimeInitialized()) {
        capabilities.emplace_back("bots.runtime");
        capabilities.emplace_back("bots.state.read");
        capabilities.emplace_back("bots.create");
        capabilities.emplace_back("bots.update");
        capabilities.emplace_back("bots.move");
        capabilities.emplace_back("bots.stop");
        capabilities.emplace_back("bots.destroy");
        capabilities.emplace_back("bots.cast");
    }

    return capabilities;
}

bool SupportsLuaModRequiredCapabilities(
    const RuntimeModDescriptor& mod,
    const std::vector<std::string>& capabilities,
    std::string* missing_capability) {
    if (missing_capability != nullptr) {
        missing_capability->clear();
    }

    for (const auto& required_capability : mod.required_capabilities) {
        const auto found = std::find(capabilities.begin(), capabilities.end(), required_capability);
        if (found == capabilities.end()) {
            if (missing_capability != nullptr) {
                *missing_capability = required_capability;
            }
            return false;
        }
    }

    return true;
}

bool CreateLuaStateForMod(LoadedLuaMod* mod, std::string* error_message) {
    if (mod == nullptr || error_message == nullptr) {
        return false;
    }

    mod->state = luaL_newstate();
    if (mod->state == nullptr) {
        *error_message = "luaL_newstate failed.";
        return false;
    }

    lua_atpanic(mod->state, &LuaPanic);
    luaL_openlibs(mod->state);
    RemoveUnsafeGlobals(mod->state);

    if (!RegisterLuaBindings(mod, error_message)) {
        return false;
    }

    if (!ExecuteEntryScript(mod, error_message)) {
        return false;
    }

    return true;
}

void CloseLuaStateForMod(LoadedLuaMod* mod) {
    if (mod == nullptr || mod->state == nullptr) {
        return;
    }

    lua_close(mod->state);
    mod->state = nullptr;
    mod->runtime_tick_registered = false;
    mod->run_started_registered = false;
    mod->run_ended_registered = false;
    mod->wave_started_registered = false;
    mod->wave_completed_registered = false;
    mod->enemy_death_registered = false;
    mod->enemy_spawned_registered = false;
    mod->spell_cast_registered = false;
    mod->gold_changed_registered = false;
    mod->drop_spawned_registered = false;
    mod->level_up_registered = false;
}

void LogLuaMessage(const LoadedLuaMod& mod, const std::string& message) {
    Log("[lua][" + mod.descriptor.id + "] " + message);
}

}  // namespace detail

bool InitializeLuaEngine(const RuntimeBootstrap& bootstrap, std::string* error_message) {
    std::scoped_lock lock(detail::LuaEngineMutex());
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (detail::LuaEngineInitializedFlag()) {
        return true;
    }

    auto& runtime_bootstrap = detail::LuaRuntimeBootstrapStorage();
    auto& runtime_directory = detail::LuaRuntimeDirectoryStorage();
    auto& loaded_mods = detail::LoadedLuaModsStorage();
    runtime_bootstrap = bootstrap;
    runtime_directory = bootstrap.runtime_root / "lua";
    std::filesystem::create_directories(runtime_directory);
    loaded_mods.clear();

    const auto capabilities = detail::BuildLuaCapabilitySet();
    for (const auto& mod : bootstrap.mods) {
        if (!mod.HasLuaEntry()) {
            continue;
        }

        if (mod.api_version != SDMOD_RUNTIME_API_VERSION) {
            Log(
                "[lua][" + mod.id + "] skipping mod due to apiVersion mismatch. host=" +
                std::string(SDMOD_RUNTIME_API_VERSION) + " mod=" + mod.api_version);
            continue;
        }

        std::string missing_capability;
        if (!detail::SupportsLuaModRequiredCapabilities(mod, capabilities, &missing_capability)) {
            Log(
                "[lua][" + mod.id + "] skipping mod due to unsupported required capability: " + missing_capability);
            continue;
        }

        auto loaded_mod = std::make_unique<detail::LoadedLuaMod>();
        loaded_mod->descriptor = mod;
        loaded_mod->capabilities = capabilities;

        std::string load_error;
        if (!detail::CreateLuaStateForMod(loaded_mod.get(), &load_error)) {
            detail::CloseLuaStateForMod(loaded_mod.get());
            Log("[lua][" + mod.id + "] failed to load entry script: " + load_error);
            continue;
        }

        detail::LogLuaMessage(*loaded_mod, "loaded entry script: " + mod.entry_script_path.string());
        loaded_mods.push_back(std::move(loaded_mod));
    }

    Log("Lua engine initialized.");
    Log("Lua runtime directory: " + runtime_directory.string());
    Log("Lua bootstrap manifest root: " + bootstrap.runtime_root.string());
    Log("Lua runtime mods loaded: " + std::to_string(loaded_mods.size()));
    detail::LuaEngineInitializedFlag() = true;
    return true;
}

void ShutdownLuaEngine() {
    std::scoped_lock lock(detail::LuaEngineMutex());
    if (!detail::LuaEngineInitializedFlag()) {
        return;
    }

    auto& loaded_mods = detail::LoadedLuaModsStorage();
    for (auto it = loaded_mods.rbegin(); it != loaded_mods.rend(); ++it) {
        detail::CloseLuaStateForMod(it->get());
    }
    loaded_mods.clear();
    detail::LuaRuntimeDirectoryStorage().clear();
    detail::LuaRuntimeBootstrapStorage() = RuntimeBootstrap{};
    detail::LuaEngineInitializedFlag() = false;
    Log("Lua engine shut down.");
}

bool IsLuaEngineInitialized() {
    std::scoped_lock lock(detail::LuaEngineMutex());
    return detail::LuaEngineInitializedFlag();
}

std::size_t GetLoadedLuaModCount() {
    std::scoped_lock lock(detail::LuaEngineMutex());
    return detail::LoadedLuaModsStorage().size();
}

bool HasLuaRuntimeTickHandlers() {
    std::scoped_lock lock(detail::LuaEngineMutex());
    return detail::LuaEngineInitializedFlag() && detail::HasAnyLuaRuntimeTickHandlers();
}

void DispatchLuaRuntimeTick(const SDModRuntimeTickContext& context) {
    std::scoped_lock lock(detail::LuaEngineMutex());
    if (!detail::LuaEngineInitializedFlag()) {
        return;
    }

    detail::DispatchRuntimeTickToLuaMods(context);
}

}  // namespace sdmod
