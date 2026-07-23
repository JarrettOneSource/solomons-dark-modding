#pragma once

#include <Windows.h>

#include <cstddef>
#include <cstdint>
#include <string>
#include <string_view>
#include <vector>

struct IDirect3DDevice9;

namespace sdmod {

inline constexpr std::size_t kLuaUiMaximumSurfacesPerMod = 8;
inline constexpr std::size_t kLuaUiMaximumSurfaces = 64;
inline constexpr std::size_t kLuaUiMaximumPanelsPerSurface = 16;
inline constexpr std::size_t kLuaUiMaximumLabelsPerSurface = 64;
inline constexpr std::size_t kLuaUiMaximumButtonsPerSurface = 32;
inline constexpr std::size_t kLuaUiMaximumTextBytesPerSurface = 8 * 1024;
inline constexpr std::size_t kLuaUiMaximumIdentifierBytes = 64;
inline constexpr std::size_t kLuaUiMaximumTitleBytes = 256;
inline constexpr std::size_t kLuaUiMaximumTextBytes = 1024;

enum class LuaUiElementKind : std::uint8_t {
    Panel,
    Label,
    Button,
};

enum class LuaUiActionClass : std::uint8_t {
    Presentation,
    Simulation,
};

struct LuaUiRect {
    float x = 0.0f;
    float y = 0.0f;
    float width = 0.0f;
    float height = 0.0f;
};

struct LuaUiSurfaceDefinition {
    std::string id;
    std::string title;
    LuaUiRect rect{0.2f, 0.15f, 0.6f, 0.7f};
    bool modal = true;
    bool close_on_escape = true;
};

struct LuaUiElementDefinition {
    LuaUiElementKind kind = LuaUiElementKind::Panel;
    std::string id;
    std::string text;
    LuaUiRect rect;
    LuaUiActionClass action_class = LuaUiActionClass::Presentation;
    bool enabled = true;
    bool close_on_activate = false;
};

struct LuaUiElementSnapshot {
    std::uint64_t handle = 0;
    std::uint64_t parent_handle = 0;
    LuaUiElementKind kind = LuaUiElementKind::Panel;
    std::string id;
    std::string text;
    LuaUiRect rect;
    LuaUiActionClass action_class = LuaUiActionClass::Presentation;
    bool enabled = true;
    bool selected = false;
};

struct LuaUiSurfaceSnapshot {
    std::uint64_t handle = 0;
    std::string mod_id;
    std::string id;
    std::string title;
    LuaUiRect rect;
    bool modal = true;
    bool close_on_escape = true;
    bool visible = false;
    std::uint64_t focused_button_handle = 0;
    std::vector<LuaUiElementSnapshot> elements;
};

struct LuaUiPendingAction {
    std::string mod_id;
    std::string surface_id;
    std::string action_id;
    LuaUiActionClass action_class = LuaUiActionClass::Presentation;
    std::uint64_t participant_id = 0;
    std::uint64_t request_id = 0;
    bool routed = false;
};

bool InitializeLuaUiRuntime(std::string* error_message);
void ShutdownLuaUiRuntime();
bool StartLuaUiRenderer(std::string* error_message);
bool IsLuaUiRendererStarted();

bool CreateLuaUiSurface(
    std::string_view mod_id,
    LuaUiSurfaceDefinition definition,
    std::uint64_t* handle,
    std::string* error_message);
bool CreateLuaUiElement(
    std::string_view mod_id,
    std::uint64_t parent_handle,
    LuaUiElementDefinition definition,
    std::uint64_t* handle,
    std::uint64_t* surface_handle,
    std::string* error_message);
bool SetLuaUiSurfaceVisible(
    std::string_view mod_id,
    std::uint64_t surface_handle,
    bool visible,
    std::string* error_message);
bool DestroyLuaUiSurface(
    std::string_view mod_id,
    std::uint64_t surface_handle,
    std::string* error_message);
bool SetLuaUiElementText(
    std::string_view mod_id,
    std::uint64_t element_handle,
    std::string text,
    std::string* error_message);
bool SetLuaUiButtonEnabled(
    std::string_view mod_id,
    std::uint64_t button_handle,
    bool enabled,
    std::string* error_message);
bool FocusLuaUiButton(
    std::string_view mod_id,
    std::uint64_t button_handle,
    std::string* error_message);
bool TryQueueLuaUiAction(
    std::string_view mod_id,
    std::string_view surface_id,
    std::string_view action_id,
    std::uint64_t* request_id,
    std::string* error_message);
bool QueueRemoteLuaUiSimulationAction(
    std::string_view mod_id,
    std::string_view surface_id,
    std::string_view action_id,
    std::uint64_t participant_id,
    std::uint64_t request_id,
    std::string* error_message);

std::vector<LuaUiSurfaceSnapshot> SnapshotLuaUiSurfaces();
bool TryGetLuaUiSurfaceSnapshot(
    std::string_view mod_id,
    std::uint64_t surface_handle,
    LuaUiSurfaceSnapshot* snapshot);
std::vector<LuaUiPendingAction> TakePendingLuaUiActions();
bool HasLuaUiRegistrations();
bool HasLuaUiRegistrationsForMod(std::string_view mod_id);
void ClearLuaUiForMod(std::string_view mod_id);

bool HandleLuaAuthoredUiWindowMessage(
    HWND hwnd,
    UINT message,
    WPARAM wparam,
    LPARAM lparam);
void UpdateLuaUiViewport(std::uint32_t width, std::uint32_t height);
void RenderLuaUiFrame(IDirect3DDevice9* device);

}  // namespace sdmod
