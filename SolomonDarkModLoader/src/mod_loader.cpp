#include "binary_layout.h"
#include "debug_ui_config.h"
#include "debug_ui_overlay.h"
#include "gameplay_seams.h"
#include "mod_loader.h"
#include "mod_loader_internal.h"

#include "bot_runtime.h"
#include "logger.h"
#include "lua_engine.h"
#include "lua_exec_pipe.h"
#include "memory_access.h"
#include "multiplayer_foundation.h"
#include "native_mods.h"
#include "runtime_bootstrap.h"
#include "runtime_debug.h"
#include "runtime_flags.h"
#include "runtime_tick_service.h"
#include "startup_status.h"
#include "steam_bootstrap.h"
#include "target_game.h"

#include <Windows.h>

#include <exception>
#include <filesystem>
#include <iomanip>
#include <sstream>
#include <string>

namespace sdmod {
namespace {

HMODULE g_module_handle = nullptr;
std::filesystem::path g_project_root;
constexpr wchar_t kLaunchTokenEnvironmentVariable[] = L"SDMOD_LAUNCH_TOKEN";

std::wstring GetModulePathString(HMODULE module_handle) {
    std::wstring path(MAX_PATH, L'\0');
    DWORD written = 0;

    for (;;) {
        written = GetModuleFileNameW(module_handle, path.data(), static_cast<DWORD>(path.size()));
        if (written == 0) {
            return {};
        }
        if (written < path.size() - 1) {
            path.resize(written);
            return path;
        }
        path.resize(path.size() * 2);
    }
}

std::filesystem::path FindProjectRoot(const std::filesystem::path& start_path) {
    auto current = start_path;
    while (!current.empty()) {
        if (std::filesystem::exists(current / "SolomonDarkModding.sln")) {
            return current;
        }

        if (!current.has_parent_path()) {
            break;
        }

        const auto parent = current.parent_path();
        if (parent == current) {
            break;
        }

        current = parent;
    }

    return start_path;
}

std::string GetEnvironmentString(const wchar_t* variable_name) {
    if (variable_name == nullptr || *variable_name == L'\0') {
        return {};
    }

    std::wstring value(64, L'\0');
    for (;;) {
        const auto written = GetEnvironmentVariableW(
            variable_name,
            value.data(),
            static_cast<DWORD>(value.size()));
        if (written == 0) {
            return {};
        }

        if (written < value.size()) {
            value.resize(written);
            const auto utf8_size = WideCharToMultiByte(
                CP_UTF8,
                0,
                value.c_str(),
                static_cast<int>(value.size()),
                nullptr,
                0,
                nullptr,
                nullptr);
            if (utf8_size <= 0) {
                return {};
            }

            std::string utf8_value(static_cast<std::size_t>(utf8_size), '\0');
            WideCharToMultiByte(
                CP_UTF8,
                0,
                value.c_str(),
                static_cast<int>(value.size()),
                utf8_value.data(),
                utf8_size,
                nullptr,
                nullptr);
            return utf8_value;
        }

        value.resize(written + 1);
    }
}

void RefreshStartupStatusSnapshot(StartupStatusSnapshot* snapshot) {
    if (snapshot == nullptr) {
        return;
    }

    snapshot->log_path = GetLoggerPath();
    snapshot->steam_transport_ready = GetSteamBootstrapSnapshot().transport_interfaces_ready;
    snapshot->multiplayer_foundation_ready = multiplayer::IsFoundationInitialized();
    snapshot->lua_engine_initialized = IsLuaEngineInitialized();
    snapshot->lua_loaded_mod_count = static_cast<int>(GetLoadedLuaModCount());
    snapshot->bot_runtime_initialized = multiplayer::IsBotRuntimeInitialized();
    snapshot->native_mod_count = static_cast<int>(GetLoadedNativeModCount());
    snapshot->runtime_tick_service_running = IsRuntimeTickServiceRunning();
}

void ShutdownPartialRuntime() {
    StopLuaExecPipeServer();
    ShutdownBackgroundFocusBypass();
    ShutdownGameplayKeyboardInjection();
    ShutdownRunLifecycleHooks();
    StopRuntimeTickService();
    RuntimeDebug_Shutdown();
    ShutdownDebugUiOverlay();
    ShutdownNativeMods();
    multiplayer::ShutdownBotRuntime();
    multiplayer::ShutdownFoundation();
    ShutdownSteamBootstrap();
    ShutdownLuaEngine();
    ShutdownDebugUiOverlayConfig();
    ShutdownGameplaySeams();
    ShutdownBinaryLayout();
}

}  // namespace

void Initialize(HMODULE module_handle) {
    g_module_handle = module_handle;
    g_project_root = FindProjectRoot(GetModuleDirectory(module_handle));

    const auto stage_runtime_directory = GetStageRuntimeDirectory();
    std::filesystem::create_directories(stage_runtime_directory / "logs");
    InitializeLogger(stage_runtime_directory / "logs" / "solomondarkmodloader.log");
    InstallCrashHandler(stage_runtime_directory / "logs" / "solomondarkmodloader.crash.log");
    ResetStartupStatus(stage_runtime_directory);

    StartupStatusSnapshot startup_status;
    startup_status.launch_token = GetEnvironmentString(kLaunchTokenEnvironmentVariable);
    startup_status.code = "pending";
    startup_status.message = "SolomonDarkModLoader startup is in progress.";
    startup_status.log_path = GetLoggerPath();
    startup_status.runtime_flags_path = GetRuntimeFlagsPath(stage_runtime_directory);
    startup_status.runtime_bootstrap_path = GetRuntimeBootstrapPath(stage_runtime_directory);
    startup_status.binary_layout_path = GetBinaryLayoutPath(stage_runtime_directory);
    WriteStartupStatus(stage_runtime_directory, startup_status);

    const auto write_failed_status = [&](const char* code, const std::string& message) {
        startup_status.completed = true;
        startup_status.success = false;
        startup_status.code = code == nullptr ? "startup-failed" : code;
        startup_status.message = message;
        RefreshStartupStatusSnapshot(&startup_status);
        WriteStartupStatus(stage_runtime_directory, startup_status);
    };

    const auto write_success_status = [&](const std::string& message) {
        startup_status.completed = true;
        startup_status.success = true;
        startup_status.code = "startup-complete";
        startup_status.message = message;
        RefreshStartupStatusSnapshot(&startup_status);
        WriteStartupStatus(stage_runtime_directory, startup_status);
    };

    try {
        Log("SolomonDarkModLoader attached.");
        Log("Module directory: " + GetModuleDirectory(module_handle).string());
        Log("Host process directory: " + GetHostProcessDirectory().string());
        Log("Stage runtime directory: " + stage_runtime_directory.string());
        Log("Project root: " + g_project_root.string());

        RuntimeFeatureFlags runtime_flags;
        std::string runtime_flags_error;
        if (!LoadRuntimeFeatureFlags(stage_runtime_directory, &runtime_flags, &runtime_flags_error)) {
            Log(runtime_flags_error);
            write_failed_status("runtime-flags-load-failed", runtime_flags_error);
            return;
        }

        SetActiveRuntimeFeatureFlags(runtime_flags);
        startup_status.runtime_flags_path = GetRuntimeFlagsPath(stage_runtime_directory);
        Log("Runtime feature flags: " + DescribeRuntimeFeatureFlags(runtime_flags));

        RuntimeBootstrap runtime_bootstrap;
        std::string runtime_bootstrap_error;
        if (!LoadRuntimeBootstrap(stage_runtime_directory, &runtime_bootstrap, &runtime_bootstrap_error)) {
            Log(runtime_bootstrap_error);
            write_failed_status("runtime-bootstrap-load-failed", runtime_bootstrap_error);
            return;
        }

        startup_status.runtime_bootstrap_path = GetRuntimeBootstrapPath(stage_runtime_directory);
        Log("Runtime bootstrap: " + DescribeRuntimeBootstrap(runtime_bootstrap));
        if (runtime_bootstrap.api_version != SDMOD_RUNTIME_API_VERSION) {
            const auto message =
                "Runtime bootstrap apiVersion mismatch. loader=" + std::string(SDMOD_RUNTIME_API_VERSION) +
                " bootstrap=" + runtime_bootstrap.api_version;
            Log(message);
            write_failed_status("runtime-api-version-mismatch", message);
            return;
        }

        if (InitializeBinaryLayout(stage_runtime_directory)) {
            startup_status.binary_layout_loaded = true;
            startup_status.binary_layout_path = GetBinaryLayoutPath(stage_runtime_directory);
            if (const auto* binary_layout = TryGetBinaryLayout(); binary_layout != nullptr) {
                Log("Binary layout loaded.");
                Log("Binary layout path: " + binary_layout->source_path.string());
                Log("Configured binary: " + binary_layout->binary_name + " " + binary_layout->binary_version);
                Log("Configured image base: " + HexString(binary_layout->image_base));
                Log("Configured UI surfaces: " + std::to_string(binary_layout->ui_surfaces.size()));
                Log("Configured UI actions: " + std::to_string(binary_layout->ui_actions.size()));
            }
        } else {
            startup_status.binary_layout_loaded = false;
            Log("Binary layout failed to load. " + GetBinaryLayoutLoadError());
            Log("Config-driven address resolution and UI seam discovery are unavailable.");
        }

        {
            std::string keyboard_injection_error;
            if (!InitializeGameplayKeyboardInjection(&keyboard_injection_error)) {
                Log("Gameplay keyboard injection unavailable. " + keyboard_injection_error);
            }
        }

        if (InitializeDebugUiOverlayConfig(stage_runtime_directory)) {
            if (const auto* debug_ui_config = TryGetDebugUiOverlayConfig(); debug_ui_config != nullptr) {
                Log("Debug UI config loaded.");
                Log("Debug UI config path: " + debug_ui_config->source_path.string());
                Log("Debug UI overlay enabled: " + std::string(debug_ui_config->enabled ? "true" : "false"));
            }
        } else {
            Log("Debug UI config failed to load. " + GetDebugUiOverlayConfigLoadError());
        }

        auto& memory = ProcessMemory::Instance();
        Log("Host module base: " + HexString(memory.ModuleBase()));

        {
            std::string background_focus_bypass_error;
            if (!InitializeBackgroundFocusBypass(&background_focus_bypass_error)) {
                const auto message = background_focus_bypass_error.empty()
                    ? std::string("Background focus bypass failed to initialize.")
                    : background_focus_bypass_error;
                Log(message);
                ShutdownPartialRuntime();
                write_failed_status("background-focus-bypass-failed", message);
                return;
            }
        }

        if (runtime_flags.multiplayer.steam_bootstrap) {
            InitializeSteamBootstrap();
        } else {
            Log("Steam bootstrap disabled by runtime flags.");
        }

        if (runtime_flags.multiplayer.foundation) {
            multiplayer::InitializeFoundation();
        } else {
            Log("Multiplayer foundation disabled by runtime flags.");
        }

        if (multiplayer::IsFoundationInitialized()) {
            multiplayer::InitializeBotRuntime();
        } else {
            Log("Bot runtime not initialized because the multiplayer foundation is unavailable.");
        }

        startup_status.lua_engine_enabled = runtime_flags.loader.lua_engine;
        if (runtime_flags.loader.lua_engine) {
            std::string lua_engine_error;
            if (!InitializeLuaEngine(runtime_bootstrap, &lua_engine_error)) {
                const auto message = lua_engine_error.empty()
                    ? std::string("Lua engine failed to initialize.")
                    : lua_engine_error;
                Log(message);
                ShutdownPartialRuntime();
                write_failed_status("lua-engine-failed", message);
                return;
            }

            std::string run_lifecycle_hook_error;
            if (!InitializeRunLifecycleHooks(&run_lifecycle_hook_error)) {
                const auto message = run_lifecycle_hook_error.empty()
                    ? std::string("Run lifecycle hooks failed to initialize.")
                    : run_lifecycle_hook_error;
                Log(message);
                ShutdownPartialRuntime();
                write_failed_status("run-lifecycle-hooks-failed", message);
                return;
            }

            if (!StartLuaExecPipeServer()) {
                const std::string message = "Lua exec pipe server failed to start.";
                Log(message);
                ShutdownPartialRuntime();
                write_failed_status("lua-exec-pipe-failed", message);
                return;
            }
        } else {
            Log("Lua engine disabled by runtime flags.");
        }

        startup_status.native_mods_enabled = runtime_flags.loader.native_mods;
        if (runtime_flags.loader.native_mods) {
            std::string native_mods_error;
            if (!InitializeNativeMods(runtime_bootstrap, &native_mods_error)) {
                const auto message = native_mods_error.empty()
                    ? std::string("Native mod host failed to initialize.")
                    : native_mods_error;
                Log(message);
                ShutdownPartialRuntime();
                write_failed_status("native-mod-host-failed", message);
                return;
            }
        } else {
            Log("Native mod host disabled by runtime flags.");
        }

        startup_status.runtime_tick_service_enabled = runtime_flags.loader.runtime_tick_service;
        if (runtime_flags.loader.runtime_tick_service && (HasLoadedNativeMods() || HasLuaRuntimeTickHandlers())) {
            if (!StartRuntimeTickService()) {
                const std::string message = "Runtime tick service failed to start.";
                Log(message);
                ShutdownPartialRuntime();
                write_failed_status("runtime-tick-service-failed", message);
                return;
            }
        } else if (!runtime_flags.loader.runtime_tick_service) {
            Log("Runtime tick service disabled by runtime flags.");
        } else {
            Log("Runtime tick service not started because no runtime tick handlers were loaded.");
        }

        if (runtime_flags.loader.debug_ui) {
            if (!InitializeDebugUiOverlay() && IsDebugUiOverlayConfigLoaded()) {
                if (const auto* debug_ui_config = TryGetDebugUiOverlayConfig();
                    debug_ui_config != nullptr && debug_ui_config->enabled) {
                    Log("Debug UI overlay requested but failed to initialize.");
                }
            }
        } else {
            Log("Debug UI overlay disabled by runtime flags.");
        }

        RefreshStartupStatusSnapshot(&startup_status);
        std::ostringstream startup_summary;
        startup_summary << "SolomonDarkModLoader startup complete."
                        << " binary_layout=" << (startup_status.binary_layout_loaded ? 1 : 0)
                        << " steam_transport=" << (startup_status.steam_transport_ready ? 1 : 0)
                        << " multiplayer_foundation=" << (startup_status.multiplayer_foundation_ready ? 1 : 0)
                        << " bot_runtime=" << (startup_status.bot_runtime_initialized ? 1 : 0)
                        << " lua_engine=" << (startup_status.lua_engine_initialized ? 1 : 0)
                        << " lua_mods=" << startup_status.lua_loaded_mod_count
                        << " native_mods=" << startup_status.native_mod_count
                        << " runtime_tick_service=" << (startup_status.runtime_tick_service_running ? 1 : 0);
        Log(startup_summary.str());
        write_success_status(startup_summary.str());
    } catch (const std::exception& ex) {
        const auto message = std::string("Unhandled exception during loader startup: ") + ex.what();
        Log(message);
        ShutdownPartialRuntime();
        write_failed_status("startup-exception", message);
    } catch (...) {
        const std::string message = "Unhandled non-standard exception during loader startup.";
        Log(message);
        ShutdownPartialRuntime();
        write_failed_status("startup-exception", message);
    }
}

void Shutdown() {
    if (g_module_handle == nullptr) {
        return;
    }

    Log("SolomonDarkModLoader shutting down.");
    StopLuaExecPipeServer();
    ShutdownBackgroundFocusBypass();
    ShutdownGameplayKeyboardInjection();
    ShutdownRunLifecycleHooks();
    StopRuntimeTickService();
    RuntimeDebug_Shutdown();
    ShutdownDebugUiOverlay();
    ShutdownNativeMods();
    multiplayer::ShutdownBotRuntime();
    multiplayer::ShutdownFoundation();
    ShutdownSteamBootstrap();
    ShutdownLuaEngine();
    ShutdownDebugUiOverlayConfig();
    ShutdownGameplaySeams();
    ShutdownBinaryLayout();
    FlushLogger();
    ShutdownCrashHandler();
    ShutdownLogger();
    g_module_handle = nullptr;
    g_project_root.clear();
}

std::filesystem::path GetModulePath(HMODULE module_handle) {
    return std::filesystem::path(GetModulePathString(module_handle));
}

std::filesystem::path GetModuleDirectory(HMODULE module_handle) {
    return GetModulePath(module_handle).parent_path();
}

std::filesystem::path GetHostProcessPath() {
    return std::filesystem::path(GetModulePathString(nullptr));
}

std::filesystem::path GetHostProcessDirectory() {
    return GetHostProcessPath().parent_path();
}

std::filesystem::path GetStageRuntimeDirectory() {
    return GetHostProcessDirectory() / target_game::kRuntimeDirectoryName;
}

std::filesystem::path GetProjectRoot(HMODULE module_handle) {
    if (!g_project_root.empty()) {
        return g_project_root;
    }

    return FindProjectRoot(GetModuleDirectory(module_handle));
}

std::string HexString(uintptr_t value) {
    std::ostringstream out;
    out << "0x" << std::hex << std::uppercase << value;
    return out.str();
}

}  // namespace sdmod
