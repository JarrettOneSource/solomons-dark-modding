#include "lua_ui_runtime.h"

#include "binary_layout.h"
#include "d3d9_end_scene_hook.h"
#include "logger.h"
#include "memory_access.h"
#include "multiplayer_local_transport.h"
#include "multiplayer_runtime_state.h"

#include <Windows.h>
#include <d3d9.h>

#include <algorithm>
#include <cstdint>
#include <mutex>
#include <string>
#include <utility>

namespace sdmod {
namespace {

struct NativeUiString {
    uintptr_t vtable = 0;
    char* text = nullptr;
    std::uint32_t unknown_08 = 0;
    std::int32_t* ref_count = nullptr;
    std::uint32_t length = 0;
    std::uint8_t flags_14 = 0;
    std::uint8_t flags_15 = 0;
    std::uint16_t padding_16 = 0;
    std::uint32_t unknown_18 = 0;
};
static_assert(sizeof(NativeUiString) == 0x1C, "Native UI string layout changed");

using UiPanelRenderFn = void(__cdecl*)(float x, float y, float width, float height, float scale);
using NativeStringAssignFn = void(__thiscall*)(void* self, char* text);
using ExactTextRenderFn = void(__thiscall*)(void* self, NativeUiString text, float x, float y);
using UiRenderContextColorFn =
    void(__thiscall*)(void* self, float red, float green, float blue, float alpha);

struct NativeUiRendererState {
    bool started = false;
    bool first_frame_logged = false;
    bool fault_logged = false;
    bool spectator_hud_state_logged = false;
    bool spectator_hud_active = false;
    multiplayer::DeathSpectatorPhase spectator_hud_phase =
        multiplayer::DeathSpectatorPhase::Inactive;
    bool spectator_hud_registered = false;
    bool spectator_hud_rendered = false;
    std::uint64_t spectator_hud_target_participant_id = 0;
    uintptr_t device_pointer_global = 0;
    uintptr_t font_bundle_global = 0;
    uintptr_t font_object_offset = 0;
    uintptr_t render_context_global = 0;
    uintptr_t render_context_draw_state_offset = 0;
    UiPanelRenderFn panel_render = nullptr;
    NativeStringAssignFn string_assign = nullptr;
    ExactTextRenderFn exact_text_render = nullptr;
    UiRenderContextColorFn render_context_color = nullptr;
    std::mutex mutex;
};

NativeUiRendererState g_native_ui_renderer;

struct SpectatorProductHudFrame {
    bool active = false;
    multiplayer::DeathSpectatorPhase phase =
        multiplayer::DeathSpectatorPhase::Inactive;
    std::uint64_t target_participant_id = 0;
    std::string text;
    bool registered = false;
};

SpectatorProductHudFrame BuildSpectatorProductHudFrame() {
    SpectatorProductHudFrame frame;
    const auto runtime =
        multiplayer::SnapshotRuntimeState().death_spectator;
    frame.active = runtime.active;
    frame.phase = runtime.phase;
    frame.target_participant_id = runtime.target_participant_id;
    frame.registered =
        multiplayer::TryBuildDeathSpectatorStatusText(
            runtime,
            &frame.text) &&
        !frame.text.empty();
    return frame;
}

void LogSpectatorProductHudFrame(
    const SpectatorProductHudFrame& frame,
    bool rendered) {
    bool changed = false;
    {
        std::scoped_lock lock(g_native_ui_renderer.mutex);
        changed =
            !g_native_ui_renderer.spectator_hud_state_logged ||
            g_native_ui_renderer.spectator_hud_active != frame.active ||
            g_native_ui_renderer.spectator_hud_phase != frame.phase ||
            g_native_ui_renderer.spectator_hud_registered !=
                frame.registered ||
            g_native_ui_renderer.spectator_hud_rendered != rendered ||
            g_native_ui_renderer.spectator_hud_target_participant_id !=
                frame.target_participant_id;
        if (changed) {
            g_native_ui_renderer.spectator_hud_state_logged = true;
            g_native_ui_renderer.spectator_hud_active = frame.active;
            g_native_ui_renderer.spectator_hud_phase = frame.phase;
            g_native_ui_renderer.spectator_hud_registered =
                frame.registered;
            g_native_ui_renderer.spectator_hud_rendered = rendered;
            g_native_ui_renderer.spectator_hud_target_participant_id =
                frame.target_participant_id;
        }
    }
    if (!changed) {
        return;
    }
    Log(
        "Product spectator HUD surface. active=" +
        std::to_string(frame.active ? 1 : 0) +
        " phase=" +
        multiplayer::DeathSpectatorPhaseLabel(frame.phase) +
        " registered=" +
        std::to_string(frame.registered ? 1 : 0) +
        " rendered=" + std::to_string(rendered ? 1 : 0) +
        " target_participant_id=" +
        std::to_string(frame.target_participant_id));
}

bool ReadRequiredLayoutValue(
    const char* key,
    uintptr_t* value,
    std::string* error_message) {
    if (value != nullptr) {
        *value = 0;
    }
    uintptr_t configured = 0;
    if (!TryGetBinaryLayoutNumericValue(
            "lua_ui_authoring", key, &configured) || configured == 0) {
        if (error_message != nullptr) {
            *error_message =
                "binary-layout.ini [lua_ui_authoring]." +
                std::string(key) + " is missing or zero.";
        }
        return false;
    }
    if (value != nullptr) {
        *value = configured;
    }
    return true;
}

LuaUiRect ComposeRect(const LuaUiRect& parent, const LuaUiRect& child) {
    return LuaUiRect{
        parent.x + child.x * parent.width,
        parent.y + child.y * parent.height,
        child.width * parent.width,
        child.height * parent.height,
    };
}

bool ResolveElementRect(
    const LuaUiSurfaceSnapshot& surface,
    const LuaUiElementSnapshot& element,
    LuaUiRect* rect,
    std::size_t depth = 0) {
    if (rect == nullptr || depth > kLuaUiMaximumPanelsPerSurface + 1) {
        return false;
    }
    LuaUiRect parent = surface.rect;
    if (element.parent_handle != surface.handle) {
        const auto found = std::find_if(
            surface.elements.begin(), surface.elements.end(),
            [&](const LuaUiElementSnapshot& candidate) {
                return candidate.handle == element.parent_handle;
            });
        if (found == surface.elements.end() ||
            !ResolveElementRect(surface, *found, &parent, depth + 1)) {
            return false;
        }
    }
    *rect = ComposeRect(parent, element.rect);
    return true;
}

int CaptureLuaUiRenderException(
    EXCEPTION_POINTERS* exception_pointers,
    DWORD* exception_code) {
    if (exception_code != nullptr && exception_pointers != nullptr &&
        exception_pointers->ExceptionRecord != nullptr) {
        *exception_code = exception_pointers->ExceptionRecord->ExceptionCode;
    }
    return EXCEPTION_EXECUTE_HANDLER;
}

bool DrawNativeText(
    NativeStringAssignFn string_assign,
    ExactTextRenderFn text_render,
    void* font,
    const std::string& text,
    float x,
    float y,
    DWORD* exception_code) {
    if (text.empty() || string_assign == nullptr ||
        text_render == nullptr || font == nullptr) {
        return text.empty();
    }
    NativeUiString native_text{};
    bool assigned = false;
    __try {
        string_assign(&native_text, const_cast<char*>(text.c_str()));
        assigned = true;
        text_render(font, native_text, x, y);
    } __except (CaptureLuaUiRenderException(
                    GetExceptionInformation(), exception_code)) {
        if (assigned) {
            __try {
                string_assign(&native_text, nullptr);
            } __except (EXCEPTION_EXECUTE_HANDLER) {
            }
        }
        return false;
    }
    __try {
        string_assign(&native_text, nullptr);
    } __except (CaptureLuaUiRenderException(
                    GetExceptionInformation(), exception_code)) {
        return false;
    }
    return true;
}

bool SetNativeTextColor(
    UiRenderContextColorFn color,
    void* context,
    float red,
    float green,
    float blue,
    DWORD* exception_code) {
    if (color == nullptr || context == nullptr) {
        return false;
    }
    __try {
        color(context, red, green, blue, 1.0f);
        return true;
    } __except (CaptureLuaUiRenderException(
                    GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool DrawNativePanel(
    UiPanelRenderFn render,
    const LuaUiRect& normalized,
    const D3DVIEWPORT9& viewport,
    DWORD* exception_code) {
    if (render == nullptr) {
        return false;
    }
    const float x = normalized.x * static_cast<float>(viewport.Width);
    const float y = normalized.y * static_cast<float>(viewport.Height);
    const float width = normalized.width * static_cast<float>(viewport.Width);
    const float height = normalized.height * static_cast<float>(viewport.Height);
    __try {
        render(x, y, width, height, 1.0f);
        return true;
    } __except (CaptureLuaUiRenderException(
                    GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool DrawSpectatorProductHud(
    UiPanelRenderFn panel_render,
    NativeStringAssignFn string_assign,
    ExactTextRenderFn text_render,
    UiRenderContextColorFn render_context_color,
    void* render_context,
    void* font,
    const D3DVIEWPORT9& viewport,
    const SpectatorProductHudFrame& frame,
    DWORD* exception_code) {
    if (!frame.registered || frame.text.empty()) {
        return false;
    }

    constexpr LuaUiRect kSurfaceRect{
        0.20f,
        0.055f,
        0.60f,
        0.075f,
    };
    const float left =
        kSurfaceRect.x * static_cast<float>(viewport.Width);
    const float top =
        kSurfaceRect.y * static_cast<float>(viewport.Height);

    const bool panel_drawn = DrawNativePanel(
        panel_render,
        kSurfaceRect,
        viewport,
        exception_code);
    const bool color_set = SetNativeTextColor(
        render_context_color,
        render_context,
        1.0f,
        0.9f,
        0.55f,
        exception_code);
    const bool text_drawn = DrawNativeText(
        string_assign,
        text_render,
        font,
        frame.text,
        left + 18.0f,
        top + 20.0f,
        exception_code);
    const bool color_restored = SetNativeTextColor(
        render_context_color,
        render_context,
        1.0f,
        1.0f,
        1.0f,
        exception_code);
    return panel_drawn && color_set && text_drawn && color_restored;
}

bool IsSwapChainBackBufferActive(IDirect3DDevice9* device) {
    if (device == nullptr) {
        return false;
    }
    IDirect3DSurface9* render_target = nullptr;
    IDirect3DSurface9* back_buffer = nullptr;
    const auto render_target_result =
        device->GetRenderTarget(0, &render_target);
    const auto back_buffer_result = device->GetBackBuffer(
        0,
        0,
        D3DBACKBUFFER_TYPE_MONO,
        &back_buffer);
    const bool active =
        SUCCEEDED(render_target_result) &&
        SUCCEEDED(back_buffer_result) &&
        render_target != nullptr &&
        render_target == back_buffer;
    if (back_buffer != nullptr) {
        back_buffer->Release();
    }
    if (render_target != nullptr) {
        render_target->Release();
    }
    return active;
}

bool ResolveFontObject(uintptr_t global_address, uintptr_t offset, void** font) {
    if (font != nullptr) {
        *font = nullptr;
    }
    uintptr_t bundle = 0;
    if (font == nullptr || global_address == 0 ||
        !ProcessMemory::Instance().TryReadValue(global_address, &bundle) ||
        bundle == 0) {
        return false;
    }
    *font = reinterpret_cast<void*>(bundle + offset);
    return true;
}

std::string ButtonText(const LuaUiElementSnapshot& element) {
    std::string text;
    text.reserve(element.text.size() + 4);
    text.append(element.selected ? "> " : "  ");
    text.append(element.enabled ? element.text : "[disabled] ");
    if (!element.enabled) {
        text.append(element.text);
    }
    return text;
}

}  // namespace

bool StartLuaUiRenderer(std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    std::scoped_lock lock(g_native_ui_renderer.mutex);
    if (g_native_ui_renderer.started) {
        return true;
    }

    uintptr_t device_global = 0;
    uintptr_t panel_render = 0;
    uintptr_t exact_text_render = 0;
    uintptr_t string_assign = 0;
    uintptr_t font_bundle_global = 0;
    uintptr_t font_object_offset = 0;
    uintptr_t render_context_global = 0;
    uintptr_t render_context_color = 0;
    uintptr_t render_context_draw_state_offset = 0;
    if (!ReadRequiredLayoutValue("device_pointer_global", &device_global, error_message) ||
        !ReadRequiredLayoutValue("panel_render", &panel_render, error_message) ||
        !ReadRequiredLayoutValue("exact_text_render", &exact_text_render, error_message) ||
        !ReadRequiredLayoutValue("string_assign", &string_assign, error_message) ||
        !ReadRequiredLayoutValue("font_bundle_global", &font_bundle_global, error_message) ||
        !ReadRequiredLayoutValue("font_object_offset", &font_object_offset, error_message) ||
        !ReadRequiredLayoutValue("render_context_global", &render_context_global, error_message) ||
        !ReadRequiredLayoutValue("render_context_color", &render_context_color, error_message) ||
        !ReadRequiredLayoutValue(
            "render_context_draw_state_offset",
            &render_context_draw_state_offset,
            error_message)) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto resolved_panel = memory.ResolveGameAddressOrZero(panel_render);
    const auto resolved_text = memory.ResolveGameAddressOrZero(exact_text_render);
    const auto resolved_assign = memory.ResolveGameAddressOrZero(string_assign);
    const auto resolved_device_global = memory.ResolveGameAddressOrZero(device_global);
    const auto resolved_font_global = memory.ResolveGameAddressOrZero(font_bundle_global);
    const auto resolved_context_global =
        memory.ResolveGameAddressOrZero(render_context_global);
    const auto resolved_context_color =
        memory.ResolveGameAddressOrZero(render_context_color);
    if (resolved_panel == 0 || resolved_text == 0 || resolved_assign == 0 ||
        resolved_device_global == 0 || resolved_font_global == 0 ||
        resolved_context_global == 0 || resolved_context_color == 0) {
        if (error_message != nullptr) {
            *error_message = "Lua UI native renderer seams could not be resolved for this executable.";
        }
        return false;
    }

    if (!InstallD3d9FrameHook(
            device_global, &RenderLuaUiFrame, error_message)) {
        return false;
    }
    g_native_ui_renderer.device_pointer_global = resolved_device_global;
    g_native_ui_renderer.font_bundle_global = resolved_font_global;
    g_native_ui_renderer.font_object_offset = font_object_offset;
    g_native_ui_renderer.render_context_global = resolved_context_global;
    g_native_ui_renderer.render_context_draw_state_offset =
        render_context_draw_state_offset;
    g_native_ui_renderer.panel_render =
        reinterpret_cast<UiPanelRenderFn>(resolved_panel);
    g_native_ui_renderer.exact_text_render =
        reinterpret_cast<ExactTextRenderFn>(resolved_text);
    g_native_ui_renderer.string_assign =
        reinterpret_cast<NativeStringAssignFn>(resolved_assign);
    g_native_ui_renderer.render_context_color =
        reinterpret_cast<UiRenderContextColorFn>(resolved_context_color);
    g_native_ui_renderer.first_frame_logged = false;
    g_native_ui_renderer.fault_logged = false;
    g_native_ui_renderer.spectator_hud_state_logged = false;
    g_native_ui_renderer.started = true;
    Log(
        "Native UI renderer registered game-native panel and exact-text "
        "callbacks.");
    return true;
}

bool IsLuaUiRendererStarted() {
    std::scoped_lock lock(g_native_ui_renderer.mutex);
    return g_native_ui_renderer.started;
}

void ShutdownLuaUiRuntime() {
    RemoveD3d9FrameCallback(&RenderLuaUiFrame);
    {
        std::scoped_lock lock(g_native_ui_renderer.mutex);
        g_native_ui_renderer.started = false;
        g_native_ui_renderer.first_frame_logged = false;
        g_native_ui_renderer.fault_logged = false;
        g_native_ui_renderer.spectator_hud_state_logged = false;
        g_native_ui_renderer.device_pointer_global = 0;
        g_native_ui_renderer.font_bundle_global = 0;
        g_native_ui_renderer.font_object_offset = 0;
        g_native_ui_renderer.render_context_global = 0;
        g_native_ui_renderer.render_context_draw_state_offset = 0;
        g_native_ui_renderer.panel_render = nullptr;
        g_native_ui_renderer.string_assign = nullptr;
        g_native_ui_renderer.exact_text_render = nullptr;
        g_native_ui_renderer.render_context_color = nullptr;
    }
    std::string ignored;
    InitializeLuaUiRuntime(&ignored);
}

void RenderLuaUiFrame(IDirect3DDevice9* device) {
    if (!IsSwapChainBackBufferActive(device)) {
        return;
    }
    D3DVIEWPORT9 viewport{};
    if (FAILED(device->GetViewport(&viewport)) ||
        viewport.Width == 0 || viewport.Height == 0) {
        return;
    }
    UpdateLuaUiViewport(viewport.Width, viewport.Height);
    const auto surfaces = SnapshotLuaUiSurfaces();
    const auto spectator_hud = BuildSpectatorProductHudFrame();
    if (surfaces.empty() && !spectator_hud.registered) {
        LogSpectatorProductHudFrame(spectator_hud, false);
        return;
    }

    UiPanelRenderFn panel_render = nullptr;
    NativeStringAssignFn string_assign = nullptr;
    ExactTextRenderFn exact_text_render = nullptr;
    uintptr_t font_bundle_global = 0;
    uintptr_t font_object_offset = 0;
    uintptr_t render_context_global = 0;
    uintptr_t render_context_draw_state_offset = 0;
    UiRenderContextColorFn render_context_color = nullptr;
    {
        std::scoped_lock lock(g_native_ui_renderer.mutex);
        if (!g_native_ui_renderer.started) {
            return;
        }
        panel_render = g_native_ui_renderer.panel_render;
        string_assign = g_native_ui_renderer.string_assign;
        exact_text_render = g_native_ui_renderer.exact_text_render;
        font_bundle_global = g_native_ui_renderer.font_bundle_global;
        font_object_offset = g_native_ui_renderer.font_object_offset;
        render_context_global = g_native_ui_renderer.render_context_global;
        render_context_draw_state_offset =
            g_native_ui_renderer.render_context_draw_state_offset;
        render_context_color = g_native_ui_renderer.render_context_color;
    }

    void* font = nullptr;
    if (!ResolveFontObject(font_bundle_global, font_object_offset, &font)) {
        LogSpectatorProductHudFrame(spectator_hud, false);
        return;
    }
    uintptr_t context_base = 0;
    if (!ProcessMemory::Instance().TryReadValue(
            render_context_global, &context_base) || context_base == 0) {
        LogSpectatorProductHudFrame(spectator_hud, false);
        return;
    }
    auto* render_context = reinterpret_cast<void*>(
        context_base + render_context_draw_state_offset);

    DWORD exception_code = 0;
    bool succeeded = true;
    for (const auto& surface : surfaces) {
        succeeded = DrawNativePanel(
            panel_render, surface.rect, viewport, &exception_code) && succeeded;
        const float surface_x = surface.rect.x * viewport.Width;
        const float surface_y = surface.rect.y * viewport.Height;
        succeeded = SetNativeTextColor(
            render_context_color, render_context, 1.0f, 0.9f, 0.55f,
            &exception_code) && succeeded;
        succeeded = DrawNativeText(
            string_assign,
            exact_text_render,
            font,
            surface.title,
            surface_x + 12.0f,
            surface_y + 10.0f,
            &exception_code) && succeeded;
        succeeded = SetNativeTextColor(
            render_context_color, render_context, 1.0f, 1.0f, 1.0f,
            &exception_code) && succeeded;

        for (const auto& element : surface.elements) {
            LuaUiRect rect;
            if (!ResolveElementRect(surface, element, &rect)) {
                succeeded = false;
                continue;
            }
            if (element.kind == LuaUiElementKind::Panel ||
                element.kind == LuaUiElementKind::Button) {
                succeeded = DrawNativePanel(
                    panel_render, rect, viewport, &exception_code) && succeeded;
            }
            if (element.kind == LuaUiElementKind::Label ||
                element.kind == LuaUiElementKind::Button) {
                const auto text = element.kind == LuaUiElementKind::Button
                    ? ButtonText(element)
                    : element.text;
                const float channel = element.enabled ? 1.0f : 0.55f;
                succeeded = SetNativeTextColor(
                    render_context_color,
                    render_context,
                    channel,
                    channel,
                    channel,
                    &exception_code) && succeeded;
                succeeded = DrawNativeText(
                    string_assign,
                    exact_text_render,
                    font,
                    text,
                    rect.x * viewport.Width + 8.0f,
                    rect.y * viewport.Height + 7.0f,
                    &exception_code) && succeeded;
                succeeded = SetNativeTextColor(
                    render_context_color, render_context, 1.0f, 1.0f, 1.0f,
                    &exception_code) && succeeded;
            }
        }
    }
    bool spectator_hud_rendered = false;
    if (spectator_hud.registered) {
        spectator_hud_rendered = DrawSpectatorProductHud(
            panel_render,
            string_assign,
            exact_text_render,
            render_context_color,
            render_context,
            font,
            viewport,
            spectator_hud,
            &exception_code);
        succeeded = spectator_hud_rendered && succeeded;
    }
    LogSpectatorProductHudFrame(
        spectator_hud,
        spectator_hud_rendered);

    std::scoped_lock lock(g_native_ui_renderer.mutex);
    if (!succeeded && !g_native_ui_renderer.fault_logged) {
        g_native_ui_renderer.fault_logged = true;
        g_native_ui_renderer.started = false;
        Log(
            "Native UI renderer disabled after a native draw failure. code=" +
            std::to_string(exception_code) + ".");
    } else if (!g_native_ui_renderer.first_frame_logged) {
        g_native_ui_renderer.first_frame_logged = true;
        Log("Native UI renderer completed its first product/authored UI frame.");
    }
}

}  // namespace sdmod
