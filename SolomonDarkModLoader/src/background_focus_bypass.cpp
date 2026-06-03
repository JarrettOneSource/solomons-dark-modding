#include "logger.h"
#include "memory_access.h"
#include "mod_loader.h"
#include "gameplay_seams.h"
#include "mod_loader_internal.h"
#include "x86_hook.h"

#include <Windows.h>

#include <algorithm>
#include <cmath>
#include <fstream>
#include <string>

namespace sdmod {
namespace {

using GameWindowProcFn = LRESULT(__stdcall*)(HWND hwnd, UINT message, WPARAM wparam, LPARAM lparam);

constexpr size_t kGameWindowProcMinimumPatchSize = 5;
constexpr double kDefaultWindowAspectRatio = 16.0 / 9.0;
constexpr int kMinimumWindowClientWidth = 640;
constexpr int kMinimumWindowClientHeight = 360;

struct BackgroundFocusBypassState {
    X86Hook window_proc_hook = {};
    GameWindowProcFn original_window_proc = nullptr;
    bool initialized = false;
    bool aspect_initialized = false;
    bool input_scale_initialized = false;
    bool correcting_window_size = false;
    int target_client_width = 1600;
    int target_client_height = 900;
    double target_aspect_ratio = kDefaultWindowAspectRatio;
    float last_input_scale_x = 1.0f;
    float last_input_scale_y = 1.0f;
    DWORD last_input_scale_log_tick = 0;
} g_background_focus_bypass_state;

bool TryParseGraphicsResolutionLine(const std::string& line, int* width, int* height) {
    constexpr char kResolutionPrefix[] = "Graphics.Resolution=";
    if (line.rfind(kResolutionPrefix, 0) != 0) {
        return false;
    }

    const auto value = line.substr(sizeof(kResolutionPrefix) - 1);
    const auto comma = value.find(',');
    if (comma == std::string::npos) {
        return false;
    }

    try {
        const auto parsed_width = std::stoi(value.substr(0, comma));
        const auto parsed_height = std::stoi(value.substr(comma + 1));
        if (parsed_width <= 0 || parsed_height <= 0) {
            return false;
        }
        if (width != nullptr) {
            *width = parsed_width;
        }
        if (height != nullptr) {
            *height = parsed_height;
        }
        return true;
    } catch (...) {
        return false;
    }
}

bool TryReadConfiguredGraphicsResolution(int* width, int* height) {
    char current_directory[MAX_PATH] = {};
    if (GetCurrentDirectoryA(MAX_PATH, current_directory) == 0) {
        return false;
    }

    const std::string settings_path =
        std::string(current_directory) + "\\sandbox\\settings.txt";
    std::ifstream settings(settings_path);
    if (!settings.is_open()) {
        return false;
    }

    std::string line;
    while (std::getline(settings, line)) {
        if (TryParseGraphicsResolutionLine(line, width, height)) {
            return true;
        }
    }

    return false;
}

double ResolveTargetWindowAspectRatio() {
    if (g_background_focus_bypass_state.aspect_initialized) {
        return g_background_focus_bypass_state.target_aspect_ratio;
    }

    int width = 0;
    int height = 0;
    if (TryReadConfiguredGraphicsResolution(&width, &height)) {
        g_background_focus_bypass_state.target_client_width = width;
        g_background_focus_bypass_state.target_client_height = height;
        g_background_focus_bypass_state.target_aspect_ratio =
            static_cast<double>(width) / static_cast<double>(height);
        Log(
            "Window aspect guard using configured Graphics.Resolution=" +
            std::to_string(width) + "x" + std::to_string(height) +
            " aspect=" + std::to_string(g_background_focus_bypass_state.target_aspect_ratio) + ".");
    } else {
        g_background_focus_bypass_state.target_client_width = 1600;
        g_background_focus_bypass_state.target_client_height = 900;
        g_background_focus_bypass_state.target_aspect_ratio = kDefaultWindowAspectRatio;
        Log(
            "Window aspect guard could not read sandbox/settings.txt; using default 16:9 aspect.");
    }

    g_background_focus_bypass_state.aspect_initialized = true;
    return g_background_focus_bypass_state.target_aspect_ratio;
}

bool IsMouseInputMessage(UINT message) {
    return message >= WM_MOUSEFIRST && message <= WM_MOUSELAST;
}

BOOL CALLBACK FindCurrentProcessWindowProc(HWND hwnd, LPARAM lparam) {
    auto* const result = reinterpret_cast<HWND*>(lparam);
    if (result == nullptr || *result != nullptr) {
        return FALSE;
    }

    DWORD window_process_id = 0;
    GetWindowThreadProcessId(hwnd, &window_process_id);
    if (window_process_id != GetCurrentProcessId()) {
        return TRUE;
    }
    if (GetWindow(hwnd, GW_OWNER) != nullptr || !IsWindowVisible(hwnd)) {
        return TRUE;
    }

    *result = hwnd;
    return FALSE;
}

HWND FindCurrentProcessMainWindow() {
    HWND hwnd = nullptr;
    EnumWindows(&FindCurrentProcessWindowProc, reinterpret_cast<LPARAM>(&hwnd));
    return hwnd;
}

void UpdateWindowInputScale(HWND hwnd, const char* reason) {
    if (hwnd == nullptr) {
        return;
    }

    (void)ResolveTargetWindowAspectRatio();

    RECT client_rect{};
    if (!GetClientRect(hwnd, &client_rect)) {
        return;
    }

    const int client_width = client_rect.right - client_rect.left;
    const int client_height = client_rect.bottom - client_rect.top;
    const int target_width = g_background_focus_bypass_state.target_client_width;
    const int target_height = g_background_focus_bypass_state.target_client_height;
    if (client_width <= 0 || client_height <= 0 || target_width <= 0 || target_height <= 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    const auto scale_x_address = memory.ResolveGameAddressOrZero(kWindowInputScaleXGlobal);
    const auto scale_y_address = memory.ResolveGameAddressOrZero(kWindowInputScaleYGlobal);
    if (scale_x_address == 0 || scale_y_address == 0) {
        Log("Window input scale update failed because the scale globals are unresolved.");
        return;
    }

    const float scale_x = static_cast<float>(client_width) / static_cast<float>(target_width);
    const float scale_y = static_cast<float>(client_height) / static_cast<float>(target_height);
    auto& state = g_background_focus_bypass_state;
    const bool cached_scale_changed =
        !state.input_scale_initialized ||
        std::fabs(state.last_input_scale_x - scale_x) >= 0.0001f ||
        std::fabs(state.last_input_scale_y - scale_y) >= 0.0001f;
    float current_scale_x = 0.0f;
    float current_scale_y = 0.0f;
    const bool live_scale_matches =
        memory.TryReadValue<float>(scale_x_address, &current_scale_x) &&
        memory.TryReadValue<float>(scale_y_address, &current_scale_y) &&
        std::fabs(current_scale_x - scale_x) < 0.0001f &&
        std::fabs(current_scale_y - scale_y) < 0.0001f;

    if (!cached_scale_changed && live_scale_matches) {
        return;
    }

    if (!memory.TryWriteValue<float>(scale_x_address, scale_x) ||
        !memory.TryWriteValue<float>(scale_y_address, scale_y)) {
        Log(
            "Window input scale update failed. client=" +
            std::to_string(client_width) + "x" + std::to_string(client_height) +
            " target=" + std::to_string(target_width) + "x" + std::to_string(target_height) + ".");
        return;
    }

    state.input_scale_initialized = true;
    state.last_input_scale_x = scale_x;
    state.last_input_scale_y = scale_y;

    const std::string reason_text = reason == nullptr ? "unknown" : reason;
    const auto now_tick = GetTickCount();
    const bool mouse_restore = reason_text == "mouse" && !cached_scale_changed;
    if (!mouse_restore || now_tick - state.last_input_scale_log_tick >= 1000) {
        state.last_input_scale_log_tick = now_tick;
        Log(
            "Updated SolomonDark window input scale. reason=" + reason_text +
            " client=" + std::to_string(client_width) + "x" + std::to_string(client_height) +
            " target=" + std::to_string(target_width) + "x" + std::to_string(target_height) +
            " scale=(" + std::to_string(scale_x) + ", " + std::to_string(scale_y) + ").");
    }
}

bool TryGetWindowFrameSize(HWND hwnd, int* frame_width, int* frame_height) {
    if (hwnd == nullptr || frame_width == nullptr || frame_height == nullptr) {
        return false;
    }

    const auto style = static_cast<DWORD>(GetWindowLongPtrA(hwnd, GWL_STYLE));
    const auto ex_style = static_cast<DWORD>(GetWindowLongPtrA(hwnd, GWL_EXSTYLE));
    RECT frame_rect{0, 0, 0, 0};
    if (!AdjustWindowRectEx(&frame_rect, style, GetMenu(hwnd) != nullptr, ex_style)) {
        return false;
    }

    *frame_width = frame_rect.right - frame_rect.left;
    *frame_height = frame_rect.bottom - frame_rect.top;
    return *frame_width >= 0 && *frame_height >= 0;
}

bool IsLeftSizingEdge(WPARAM edge) {
    return edge == WMSZ_LEFT || edge == WMSZ_TOPLEFT || edge == WMSZ_BOTTOMLEFT;
}

bool IsTopSizingEdge(WPARAM edge) {
    return edge == WMSZ_TOP || edge == WMSZ_TOPLEFT || edge == WMSZ_TOPRIGHT;
}

bool IsHorizontalOnlySizingEdge(WPARAM edge) {
    return edge == WMSZ_LEFT || edge == WMSZ_RIGHT;
}

bool IsVerticalOnlySizingEdge(WPARAM edge) {
    return edge == WMSZ_TOP || edge == WMSZ_BOTTOM;
}

void ApplyOuterSizeToSizingRect(WPARAM edge, int outer_width, int outer_height, RECT* rect) {
    if (rect == nullptr) {
        return;
    }

    if (IsLeftSizingEdge(edge)) {
        rect->left = rect->right - outer_width;
    } else {
        rect->right = rect->left + outer_width;
    }

    if (IsTopSizingEdge(edge)) {
        rect->top = rect->bottom - outer_height;
    } else {
        rect->bottom = rect->top + outer_height;
    }
}

void ConstrainSizingRectToGameAspect(HWND hwnd, WPARAM edge, LPARAM lparam) {
    auto* const proposed_rect = reinterpret_cast<RECT*>(lparam);
    if (proposed_rect == nullptr) {
        return;
    }

    int frame_width = 0;
    int frame_height = 0;
    if (!TryGetWindowFrameSize(hwnd, &frame_width, &frame_height)) {
        return;
    }

    const int proposed_outer_width = proposed_rect->right - proposed_rect->left;
    const int proposed_outer_height = proposed_rect->bottom - proposed_rect->top;
    int client_width = (std::max)(kMinimumWindowClientWidth, proposed_outer_width - frame_width);
    int client_height = (std::max)(kMinimumWindowClientHeight, proposed_outer_height - frame_height);
    const auto target_aspect = ResolveTargetWindowAspectRatio();

    if (IsHorizontalOnlySizingEdge(edge)) {
        client_height = (std::max)(
            kMinimumWindowClientHeight,
            static_cast<int>(std::lround(static_cast<double>(client_width) / target_aspect)));
    } else if (IsVerticalOnlySizingEdge(edge)) {
        client_width = (std::max)(
            kMinimumWindowClientWidth,
            static_cast<int>(std::lround(static_cast<double>(client_height) * target_aspect)));
    } else {
        const auto proposed_aspect =
            static_cast<double>(client_width) / static_cast<double>(client_height);
        if (proposed_aspect > target_aspect) {
            client_width = (std::max)(
                kMinimumWindowClientWidth,
                static_cast<int>(std::lround(static_cast<double>(client_height) * target_aspect)));
        } else {
            client_height = (std::max)(
                kMinimumWindowClientHeight,
                static_cast<int>(std::lround(static_cast<double>(client_width) / target_aspect)));
        }
    }

    ApplyOuterSizeToSizingRect(
        edge,
        client_width + frame_width,
        client_height + frame_height,
        proposed_rect);
}

void CorrectRestoredWindowAspectIfNeeded(HWND hwnd) {
    if (hwnd == nullptr || g_background_focus_bypass_state.correcting_window_size ||
        IsIconic(hwnd) || IsZoomed(hwnd)) {
        return;
    }

    RECT client_rect{};
    RECT window_rect{};
    if (!GetClientRect(hwnd, &client_rect) || !GetWindowRect(hwnd, &window_rect)) {
        return;
    }

    const int client_width = client_rect.right - client_rect.left;
    const int client_height = client_rect.bottom - client_rect.top;
    if (client_width <= 0 || client_height <= 0) {
        return;
    }

    const auto target_aspect = ResolveTargetWindowAspectRatio();
    const auto current_aspect = static_cast<double>(client_width) / static_cast<double>(client_height);
    if (std::fabs(current_aspect - target_aspect) < 0.005) {
        return;
    }

    int frame_width = 0;
    int frame_height = 0;
    if (!TryGetWindowFrameSize(hwnd, &frame_width, &frame_height)) {
        return;
    }

    const int corrected_client_height = (std::max)(
        kMinimumWindowClientHeight,
        static_cast<int>(std::lround(static_cast<double>(client_width) / target_aspect)));
    const int corrected_outer_height = corrected_client_height + frame_height;
    const int current_outer_width = window_rect.right - window_rect.left;

    g_background_focus_bypass_state.correcting_window_size = true;
    SetWindowPos(
        hwnd,
        nullptr,
        0,
        0,
        current_outer_width,
        corrected_outer_height,
        SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOOWNERZORDER);
    g_background_focus_bypass_state.correcting_window_size = false;

    Log(
        "Corrected SolomonDark window aspect after resize. client=" +
        std::to_string(client_width) + "x" + std::to_string(client_height) +
        " corrected_client_height=" + std::to_string(corrected_client_height) + ".");
}

LRESULT __stdcall DetourGameWindowProc(HWND hwnd, UINT message, WPARAM wparam, LPARAM lparam) {
    auto* const original = g_background_focus_bypass_state.original_window_proc;
    if (original == nullptr) {
        return DefWindowProcA(hwnd, message, wparam, lparam);
    }

    if (message == WM_ACTIVATEAPP && wparam == FALSE) {
        Log("Suppressed WM_ACTIVATEAPP deactivation so Solomon Dark keeps running in the background.");
        wparam = TRUE;
    }

    if (message == WM_SIZING) {
        ConstrainSizingRectToGameAspect(hwnd, wparam, lparam);
    }

    if (IsMouseInputMessage(message)) {
        UpdateWindowInputScale(hwnd, "mouse");
    }

    const auto result = original(hwnd, message, wparam, lparam);

    if (message == WM_SIZE && wparam == SIZE_RESTORED) {
        CorrectRestoredWindowAspectIfNeeded(hwnd);
        UpdateWindowInputScale(hwnd, "resize");
    } else if (message == WM_WINDOWPOSCHANGED) {
        UpdateWindowInputScale(hwnd, "windowpos");
    }

    return result;
}

}  // namespace

bool InitializeBackgroundFocusBypass(std::string* error_message) {
    if (g_background_focus_bypass_state.initialized) {
        return true;
    }

    if (!InitializeGameplaySeams(error_message)) {
        return false;
    }

    const auto resolved_window_proc = ProcessMemory::Instance().ResolveGameAddressOrZero(kGameWindowProc);
    if (resolved_window_proc == 0) {
        if (error_message != nullptr) {
            *error_message = "Failed to resolve the game window procedure for the background focus bypass.";
        }
        return false;
    }

    std::string hook_error;
    if (!InstallSafeX86Hook(
            reinterpret_cast<void*>(resolved_window_proc),
            reinterpret_cast<void*>(&DetourGameWindowProc),
            kGameWindowProcMinimumPatchSize,
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
    UpdateWindowInputScale(FindCurrentProcessMainWindow(), "initialize");
    Log(
        "Installed background focus bypass hook at " + HexString(resolved_window_proc) +
        " patch=" + std::to_string(g_background_focus_bypass_state.window_proc_hook.patch_size) + ".");
    return true;
}

void ShutdownBackgroundFocusBypass() {
    if (!g_background_focus_bypass_state.initialized) {
        return;
    }

    RemoveX86Hook(&g_background_focus_bypass_state.window_proc_hook);
    g_background_focus_bypass_state.original_window_proc = nullptr;
    g_background_focus_bypass_state.initialized = false;
    g_background_focus_bypass_state.aspect_initialized = false;
    g_background_focus_bypass_state.input_scale_initialized = false;
}

}  // namespace sdmod
