#pragma once

#include <cstdint>
#include <string>
#include <string_view>
#include <vector>

namespace sdmod {

// ---------------------------------------------------------------------------
// UI navigation middle layer — rich element model for programmatic menu
// navigation. Sits between raw memory access (debug_ui_overlay) and Lua.
//
// Modeled after the Solomon's Boneyard sb.ui.get_state() / sb.ui.perform()
// pattern: observation → scene/surface resolution → per-surface element
// builders → structured snapshot with hierarchical elements, typed
// properties, and semantic actions.
// ---------------------------------------------------------------------------

// --- Property system -------------------------------------------------------

enum class UiPropertyKind {
    String,
    Integer,
    Number,
    Boolean,
};

struct UiPropertySnapshot {
    std::string name;
    UiPropertyKind kind = UiPropertyKind::String;
    std::string string_value;
    int integer_value = 0;
    double number_value = 0.0;
    bool boolean_value = false;
};

// --- Actions ---------------------------------------------------------------

struct UiActionSnapshot {
    std::string id;
    std::string label;
    std::string element_id;
    bool enabled = false;
};

// --- Elements (recursive tree) ---------------------------------------------

struct UiElementSnapshot {
    std::string id;
    std::string kind;
    std::string label;
    std::string text;
    bool visible = true;
    bool interactive = false;
    bool enabled = false;
    bool selected = false;
    std::vector<UiPropertySnapshot> state;
    std::vector<UiActionSnapshot> actions;
    std::vector<UiElementSnapshot> children;
};

// --- Top-level snapshot ----------------------------------------------------

struct UiStateSnapshot {
    bool available = false;
    std::string scene;
    std::string surface;
    std::string surface_title;
    std::vector<UiPropertySnapshot> details;
    std::vector<UiActionSnapshot> actions;
    std::vector<UiElementSnapshot> elements;
};

// --- Structured action request ---------------------------------------------

struct UiActionRequest {
    std::string action_id;
    std::string element_id;
    std::string value;
};

// --- Public API ------------------------------------------------------------

/// Build a complete UI state snapshot from live game memory.
/// Returns a snapshot with available=false if the game UI cannot be read.
UiStateSnapshot BuildRuntimeUiStateSnapshot();

/// Execute a structured UI action request.
/// Returns true on success. On failure, populates status_message with reason.
bool ExecuteRuntimeUiAction(
    const UiActionRequest& request,
    std::string* status_message);

}  // namespace sdmod
