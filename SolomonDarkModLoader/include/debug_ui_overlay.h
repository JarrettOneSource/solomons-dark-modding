#pragma once

#include <cstdint>
#include <string>
#include <string_view>
#include <vector>

namespace sdmod {

struct DebugUiSnapshotElement {
    std::string surface_id;
    std::string surface_title;
    std::string label;
    std::string action_id;
    std::uintptr_t source_object_ptr = 0;
    std::uintptr_t surface_object_ptr = 0;
    bool show_label = true;
    float left = 0.0f;
    float top = 0.0f;
    float right = 0.0f;
    float bottom = 0.0f;
};

struct DebugUiSurfaceSnapshot {
    std::uint64_t generation = 0;
    std::uint64_t captured_at_milliseconds = 0;
    std::string surface_id;
    std::string surface_title;
    std::vector<DebugUiSnapshotElement> elements;
};

// Opt-in native menu-layout capture. Unlike DebugUiSurfaceSnapshot, this
// additive diagnostic view includes observed text/font provenance and native
// atlas draws. Coordinates are the clipped, live D3D9 output coordinates;
// unclipped coordinates preserve the submitted quad for scroll/scissor cases.
struct DebugUiLayoutElement {
    std::string id;
    std::string kind;
    std::string text;
    std::string action_id;
    std::string art_id;
    std::string font_id;
    std::string text_style;
    std::uintptr_t source_object_ptr = 0;
    bool visible = true;
    bool interactive = false;
    std::uint32_t draw_order = 0;
    float left = 0.0f;
    float top = 0.0f;
    float right = 0.0f;
    float bottom = 0.0f;
    float unclipped_left = 0.0f;
    float unclipped_top = 0.0f;
    float unclipped_right = 0.0f;
    float unclipped_bottom = 0.0f;
};

struct DebugUiLayoutSnapshot {
    std::uint64_t generation = 0;
    std::uint64_t captured_at_milliseconds = 0;
    std::string screen_id;
    std::string screen_title;
    std::string capture_method;
    std::vector<DebugUiLayoutElement> elements;
};

struct DebugUiActionDispatchSnapshot {
    std::uint64_t request_id = 0;
    std::uint64_t queued_at_milliseconds = 0;
    std::uint64_t started_at_milliseconds = 0;
    std::uint64_t completed_at_milliseconds = 0;
    std::uint64_t snapshot_generation = 0;
    std::uintptr_t owner_address = 0;
    std::uintptr_t control_address = 0;
    std::string action_id;
    std::string target_label;
    std::string surface_id;
    std::string dispatch_kind;
    std::string status;
    std::string error_message;
};

bool InitializeDebugUiOverlay(bool diagnostic_visuals_enabled);
void ShutdownDebugUiOverlay();
bool IsDebugUiOverlayInitialized();
void ObserveDebugUiExactTextGlyph(float x, float y);
void ObserveDebugUiMenuSpritePositionDraw(void* sprite, float x, float y);
void DispatchPendingDebugUiActionOnAppTick();
bool TryPrepareMainMenuNewGameSaveReset(
    std::uintptr_t main_menu_address,
    std::string* error_message);
bool TryContinuePostRunHallOfFame(std::string* error_message);
bool TryGetLatestDebugUiSurfaceSnapshot(DebugUiSurfaceSnapshot* snapshot);
bool TryGetLatestDebugUiLayoutSnapshot(DebugUiLayoutSnapshot* snapshot);
bool TryGetDebugUiLayoutSnapshot(
    std::string_view screen_id,
    DebugUiLayoutSnapshot* snapshot);
bool TryFindDebugUiActionElement(std::string_view action_id, std::string_view surface_id, DebugUiSnapshotElement* element);
bool TryGetDebugUiActionDispatchSnapshot(std::uint64_t request_id, DebugUiActionDispatchSnapshot* snapshot);
bool TryActivateDebugUiAction(
    std::string_view action_id,
    std::string_view surface_id,
    std::uint64_t* request_id,
    std::string* error_message);
bool TryActivateDebugUiAction(std::string_view action_id, std::string_view surface_id, std::string* error_message);
bool TryActivateDebugUiElement(
    std::string_view label,
    std::string_view surface_id,
    std::uint64_t* request_id,
    std::string* error_message);
bool TryActivateDebugUiElement(std::string_view label, std::string_view surface_id, std::string* error_message);
bool TryActivateDebugUiSnapshotElement(const DebugUiSnapshotElement& element, std::string* error_message);

}  // namespace sdmod
