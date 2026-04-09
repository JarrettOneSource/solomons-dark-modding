// ---------------------------------------------------------------------------
// UI navigation public API implementations.
//
// These functions are in namespace sdmod (outside the anonymous namespace)
// and implement the declarations from ui_navigation.h.
//
// The overlay snapshot is the single source of truth.  BuildRuntimeUiStateSnapshot
// transforms it into a UiStateSnapshot by enriching elements with action
// definitions from binary-layout.ini.  No separate memory reads.
// ---------------------------------------------------------------------------

UiStateSnapshot BuildRuntimeUiStateSnapshot() {
    UiStateSnapshot state;

    if (!g_debug_ui_overlay_state.initialized) {
        return state;
    }

    DebugUiSurfaceSnapshot snapshot;
    if (!TryGetLatestDebugUiSurfaceSnapshot(&snapshot)) {
        return state;
    }

    state.available = true;
    state.scene = ResolveUiScene(snapshot);
    state.surface = snapshot.surface_id;
    state.surface_title = snapshot.surface_title;
    state.elements = TransformOverlayElements(snapshot);
    state.actions = CollectSurfaceActions(state.elements);

    return state;
}

bool ExecuteRuntimeUiAction(
    const UiActionRequest& request,
    std::string* status_message) {
    if (request.action_id.empty()) {
        if (status_message != nullptr) {
            *status_message = "action_id is required";
        }
        return false;
    }

    if (!g_debug_ui_overlay_state.initialized) {
        if (status_message != nullptr) {
            *status_message = "overlay not initialized";
        }
        return false;
    }

    std::string error;
    if (TryActivateDebugUiAction(request.action_id, "", &error)) {
        if (status_message != nullptr) {
            *status_message = "dispatched";
        }
        return true;
    }

    if (!request.element_id.empty()) {
        std::string element_error;
        if (TryActivateDebugUiElement(request.element_id, "", &element_error)) {
            if (status_message != nullptr) {
                *status_message = "dispatched via element label";
            }
            return true;
        }
    }

    if (status_message != nullptr) {
        *status_message = error.empty() ? "action not found" : error;
    }
    return false;
}
