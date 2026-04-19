// ---------------------------------------------------------------------------
// UI navigation snapshot builder.
//
// Transforms the flat DebugUiSurfaceSnapshot into a rich UiStateSnapshot
// by enriching each overlay element with action definitions from
// binary-layout.ini and resolving the scene from the surface_id.
//
// The overlay snapshot is the single source of truth.
// ---------------------------------------------------------------------------

namespace {

std::string ResolveUiScene(const DebugUiSurfaceSnapshot& snapshot) {
    const auto& sid = snapshot.surface_id;
    if (sid == "main_menu" || sid == "dialog" || sid == "settings" ||
        sid == "create" ||
        sid == "controls" || sid == "dark_cloud_browser" ||
        sid == "dark_cloud_search" || sid == "simple_menu" ||
        sid == "myquick_panel") {
        return "title";
    }
    return sid.empty() ? "unknown" : "unknown";
}

UiElementSnapshot TransformOverlayElement(
    const DebugUiSnapshotElement& element,
    const std::string& surface_root_id) {
    UiElementSnapshot ui_element;

    // Resolve the action: use action_id from the overlay element if present,
    // otherwise look up the label against the configured actions for this surface.
    std::string resolved_action_id = element.action_id;
    const UiActionDefinition* action_def = nullptr;

    if (!resolved_action_id.empty()) {
        action_def = FindUiActionDefinition(resolved_action_id);
    } else if (!element.label.empty() && !surface_root_id.empty()) {
        action_def = FindConfiguredUiActionByLabel(surface_root_id, element.label);
        if (action_def != nullptr) {
            resolved_action_id = action_def->id;
        }
    }

    const bool has_action = !resolved_action_id.empty();

    ui_element.id = has_action ? resolved_action_id : (element.surface_id + "." + element.label);
    ui_element.label = element.label;
    ui_element.visible = true;
    ui_element.interactive = has_action;
    ui_element.enabled = has_action;

    if (has_action) {
        if (action_def != nullptr) {
            if (action_def->dispatch_kind == "owner_control" ||
                action_def->dispatch_kind == "control_child") {
                ui_element.kind = "button";
            } else if (action_def->dispatch_kind == "no_arg") {
                ui_element.kind = "control";
            } else {
                ui_element.kind = "button";
            }
        } else {
            ui_element.kind = "button";
        }

        UiActionSnapshot action;
        action.id = resolved_action_id;
        action.label = element.label;
        action.element_id = ui_element.id;
        action.enabled = true;
        ui_element.actions.push_back(std::move(action));
    } else if (element.show_label) {
        ui_element.kind = "label";
    } else {
        ui_element.kind = "text";
    }

    return ui_element;
}

std::vector<UiElementSnapshot> TransformOverlayElements(
    const DebugUiSurfaceSnapshot& snapshot) {
    std::vector<UiElementSnapshot> elements;
    elements.reserve(snapshot.elements.size());

    const auto surface_root_id = GetOverlaySurfaceRootId(snapshot.surface_id);

    for (const auto& overlay_element : snapshot.elements) {
        if (overlay_element.label.empty() && overlay_element.action_id.empty()) {
            continue;
        }
        elements.push_back(TransformOverlayElement(overlay_element, surface_root_id));
    }

    return elements;
}

std::vector<UiActionSnapshot> CollectSurfaceActions(
    const std::vector<UiElementSnapshot>& elements) {
    std::vector<UiActionSnapshot> actions;

    for (const auto& element : elements) {
        for (const auto& action : element.actions) {
            actions.push_back(action);
        }
    }

    return actions;
}

}  // namespace
