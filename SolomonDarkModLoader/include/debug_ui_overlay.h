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

bool InitializeDebugUiOverlay();
void ShutdownDebugUiOverlay();
bool IsDebugUiOverlayInitialized();
bool TryGetLatestDebugUiSurfaceSnapshot(DebugUiSurfaceSnapshot* snapshot);
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
