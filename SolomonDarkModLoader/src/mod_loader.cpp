#include "binary_layout.h"
#include "debug_ui_config.h"
#include "debug_ui_overlay.h"
#include "gameplay_seams.h"
#include "mod_loader.h"
#include "mod_loader_internal.h"

#include "bot_runtime.h"
#include "boneyard_picker.h"
#include "fresh_save_tutorial_bypass.h"
#include "headless_simulation.h"
#include "launch_audio_disable.h"
#include "loading_screen.h"
#include "logger.h"
#include "lua_camera_runtime.h"
#include "lua_developer_console.h"
#include "lua_draw_runtime.h"
#include "lua_ui_runtime.h"
#include "lua_engine.h"
#include "lua_exec_pipe.h"
#include "lua_item_runtime.h"
#include "lua_world_render_runtime.h"
#include "memory_access.h"
#include "multiplayer_foundation.h"
#include "multiplayer_join_flow.h"
#include "native_audio_observability.h"
#include "native_close_url_patch.h"
#include "native_d3d9_lifetime_guard.h"
#include "network_telemetry.h"
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

#if defined(NDEBUG)
#define SDMOD_BUILD_FLAVOR "Release"
#else
#define SDMOD_BUILD_FLAVOR "Debug"
#endif

extern "C" __declspec(dllexport) const char* __cdecl
SolomonDarkModLoaderBuildFlavor() noexcept {
    return "SDMOD_BUILD_FLAVOR=" SDMOD_BUILD_FLAVOR;
}

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

#include "mod_loader/startup_status_snapshot.inl"

void ShutdownPartialRuntime() {
    StopLuaExecPipeServer();
    ShutdownLuaDeveloperConsole();
    ShutdownLoadingScreen();
    ShutdownCpuLifecycleGuard();
    ShutdownBackgroundFocusBypass();
    ShutdownHeadlessSimulation();
    ShutdownLuaWorldRenderer();
    ShutdownLuaItemNativeHooks();
    ShutdownBoneyardPicker();
    ShutdownGameplayKeyboardInjection();
    ShutdownNativeAudioObservability();
    ShutdownRunLifecycleHooks();
    StopRuntimeTickService();
    RuntimeDebug_Shutdown();
    ShutdownMultiplayerJoinFlow();
    ShutdownFreshSaveTutorialBypass();
    ShutdownLaunchAudioDisable();
    ShutdownDebugUiOverlay();
    multiplayer::ShutdownBotRuntime();
    multiplayer::ShutdownFoundation();
    ShutdownSteamBootstrap();
    ShutdownMultiplayerSessionStatusWriter();
    ShutdownLuaEngine();
    ShutdownLuaCameraRuntime();
    ShutdownDebugUiOverlayConfig();
    ShutdownGameplaySeams();
    ShutdownNativeCloseUrlPatch();
    ShutdownBinaryLayout();
    ShutdownNetworkTelemetry();
}

void RunShutdownStep(const char* name, void (*step)()) noexcept {
    if (step == nullptr) {
        return;
    }

    try {
        step();
    } catch (const std::exception& ex) {
        Log(std::string("Shutdown step failed: ") + (name == nullptr ? "unknown" : name) + ": " + ex.what());
    } catch (...) {
        Log(std::string("Shutdown step failed: ") + (name == nullptr ? "unknown" : name) + ": unknown exception.");
    }
}

}  // namespace

#include "mod_loader/initialize.inl"

void Shutdown() {
    if (g_module_handle == nullptr) {
        return;
    }

    Log("SolomonDarkModLoader shutting down.");
    RunShutdownStep("lua exec pipe", &StopLuaExecPipeServer);
    RunShutdownStep("lua developer console", &ShutdownLuaDeveloperConsole);
    RunShutdownStep("loading screen", &ShutdownLoadingScreen);
    RunShutdownStep("CPU lifecycle guard", &ShutdownCpuLifecycleGuard);
    RunShutdownStep("background focus bypass", &ShutdownBackgroundFocusBypass);
    RunShutdownStep("headless simulation", &ShutdownHeadlessSimulation);
    RunShutdownStep("lua world renderer", &ShutdownLuaWorldRenderer);
    RunShutdownStep("lua item native hooks", &ShutdownLuaItemNativeHooks);
    RunShutdownStep("boneyard picker", &ShutdownBoneyardPicker);
    RunShutdownStep("gameplay keyboard injection", &ShutdownGameplayKeyboardInjection);
    RunShutdownStep(
        "native audio observability",
        &ShutdownNativeAudioObservability);
    RunShutdownStep("run lifecycle hooks", &ShutdownRunLifecycleHooks);
    RunShutdownStep("runtime tick service", &StopRuntimeTickService);
    RunShutdownStep("runtime debug", &RuntimeDebug_Shutdown);
    RunShutdownStep("multiplayer join flow", &ShutdownMultiplayerJoinFlow);
    RunShutdownStep(
        "fresh-save tutorial bypass",
        &ShutdownFreshSaveTutorialBypass);
    RunShutdownStep("launch audio disable", &ShutdownLaunchAudioDisable);
    RunShutdownStep("debug ui overlay", &ShutdownDebugUiOverlay);
    RunShutdownStep("bot runtime", &multiplayer::ShutdownBotRuntime);
    RunShutdownStep("multiplayer foundation", &multiplayer::ShutdownFoundation);
    RunShutdownStep("steam bootstrap", &ShutdownSteamBootstrap);
    RunShutdownStep(
        "multiplayer session status writer",
        &ShutdownMultiplayerSessionStatusWriter);
    RunShutdownStep("lua engine", &ShutdownLuaEngine);
    RunShutdownStep("lua camera runtime", &ShutdownLuaCameraRuntime);
    RunShutdownStep("debug ui overlay config", &ShutdownDebugUiOverlayConfig);
    RunShutdownStep("gameplay seams", &ShutdownGameplaySeams);
    RunShutdownStep(
        "native close URL patch",
        &ShutdownNativeCloseUrlPatch);
    RunShutdownStep("binary layout", &ShutdownBinaryLayout);
    RunShutdownStep("network telemetry", &ShutdownNetworkTelemetry);
    RunShutdownStep("logger flush", &FlushLogger);
    RunShutdownStep("crash handler", &ShutdownCrashHandler);
    RunShutdownStep("logger", &ShutdownLogger);
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
