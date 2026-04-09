#include "logger.h"
#include "memory_access.h"
#include "mod_loader.h"
#include "mod_loader_internal.h"
#include "x86_hook.h"

#include <Windows.h>

#include <string>

namespace sdmod {
namespace {

using GameWindowProcFn = LRESULT(__stdcall*)(HWND hwnd, UINT message, WPARAM wparam, LPARAM lparam);

constexpr uintptr_t kGameWindowProc = 0x00443440;
constexpr size_t kGameWindowProcPatchSize = 6;

struct BackgroundFocusBypassState {
    X86Hook window_proc_hook = {};
    GameWindowProcFn original_window_proc = nullptr;
    bool initialized = false;
} g_background_focus_bypass_state;

LRESULT __stdcall DetourGameWindowProc(HWND hwnd, UINT message, WPARAM wparam, LPARAM lparam) {
    auto* const original = g_background_focus_bypass_state.original_window_proc;
    if (original == nullptr) {
        return DefWindowProcA(hwnd, message, wparam, lparam);
    }

    if (message == WM_ACTIVATEAPP && wparam == FALSE) {
        Log("Suppressed WM_ACTIVATEAPP deactivation so Solomon Dark keeps running in the background.");
        wparam = TRUE;
    }

    return original(hwnd, message, wparam, lparam);
}

}  // namespace

bool InitializeBackgroundFocusBypass(std::string* error_message) {
    if (g_background_focus_bypass_state.initialized) {
        return true;
    }

    const auto resolved_window_proc = ProcessMemory::Instance().ResolveGameAddressOrZero(kGameWindowProc);
    if (resolved_window_proc == 0) {
        if (error_message != nullptr) {
            *error_message = "Failed to resolve the game window procedure for the background focus bypass.";
        }
        return false;
    }

    std::string hook_error;
    if (!InstallX86Hook(
            reinterpret_cast<void*>(resolved_window_proc),
            reinterpret_cast<void*>(&DetourGameWindowProc),
            kGameWindowProcPatchSize,
            &g_background_focus_bypass_state.window_proc_hook,
            &hook_error)) {
        if (error_message != nullptr) {
            *error_message = "Failed to install the background focus bypass hook: " + hook_error;
        }
        return false;
    }

    g_background_focus_bypass_state.original_window_proc =
        GetX86HookTrampoline<GameWindowProcFn>(g_background_focus_bypass_state.window_proc_hook);
    if (g_background_focus_bypass_state.original_window_proc == nullptr) {
        RemoveX86Hook(&g_background_focus_bypass_state.window_proc_hook);
        if (error_message != nullptr) {
            *error_message = "Background focus bypass hook installed without a valid trampoline.";
        }
        return false;
    }

    g_background_focus_bypass_state.initialized = true;
    Log("Installed background focus bypass hook at " + HexString(resolved_window_proc) + ".");
    return true;
}

void ShutdownBackgroundFocusBypass() {
    if (!g_background_focus_bypass_state.initialized) {
        return;
    }

    RemoveX86Hook(&g_background_focus_bypass_state.window_proc_hook);
    g_background_focus_bypass_state.original_window_proc = nullptr;
    g_background_focus_bypass_state.initialized = false;
}

}  // namespace sdmod
