std::optional<std::string_view> TryGetDarkCloudBrowserActionId(PendingDarkCloudBrowserAction action) {
    switch (action) {
        case PendingDarkCloudBrowserAction::Search:
            return "dark_cloud_browser.search";
        case PendingDarkCloudBrowserAction::Sort:
            return "dark_cloud_browser.sort";
        case PendingDarkCloudBrowserAction::Options:
            return "dark_cloud_browser.options";
        case PendingDarkCloudBrowserAction::Recent:
            return "dark_cloud_browser.recent";
        case PendingDarkCloudBrowserAction::OnlineLevels:
            return "dark_cloud_browser.online_levels";
        case PendingDarkCloudBrowserAction::MyLevels:
            return "dark_cloud_browser.my_levels";
        case PendingDarkCloudBrowserAction::None:
        default:
            return std::nullopt;
    }
}

std::optional<PendingDarkCloudBrowserAction> PollDarkCloudBrowserActionHotkey() {
    struct HotkeyBinding {
        int virtual_key = 0;
        PendingDarkCloudBrowserAction action = PendingDarkCloudBrowserAction::None;
    };

    constexpr HotkeyBinding kBindings[] = {
        {VK_F6, PendingDarkCloudBrowserAction::Search},
        {VK_F7, PendingDarkCloudBrowserAction::Sort},
        {VK_F8, PendingDarkCloudBrowserAction::Options},
        {VK_F9, PendingDarkCloudBrowserAction::Recent},
        {VK_F10, PendingDarkCloudBrowserAction::OnlineLevels},
        {VK_F11, PendingDarkCloudBrowserAction::MyLevels},
    };

    for (const auto& binding : kBindings) {
        if ((GetAsyncKeyState(binding.virtual_key) & 1) != 0) {
            return binding.action;
        }
    }

    return std::nullopt;
}

void StoreCompletedSemanticUiActionDispatchUnlocked(
    DebugUiOverlayState* state,
    std::string_view status,
    std::string_view error_message) {
    if (state == nullptr || !state->active_semantic_ui_action_dispatch.active) {
        return;
    }

    auto& result = state->last_semantic_ui_action_dispatch;
    result.valid = true;
    result.request_id = state->active_semantic_ui_action_dispatch.request_id;
    result.queued_at = state->active_semantic_ui_action_dispatch.queued_at;
    result.started_at = state->active_semantic_ui_action_dispatch.started_at;
    result.completed_at = GetTickCount64();
    result.snapshot_generation = state->active_semantic_ui_action_dispatch.snapshot_generation;
    result.owner_address = state->active_semantic_ui_action_dispatch.owner_address;
    result.control_address = state->active_semantic_ui_action_dispatch.control_address;
    result.action_id = state->active_semantic_ui_action_dispatch.action_id;
    result.target_label = state->active_semantic_ui_action_dispatch.target_label;
    result.surface_id = state->active_semantic_ui_action_dispatch.surface_id;
    result.dispatch_kind = state->active_semantic_ui_action_dispatch.dispatch_kind;
    result.status = std::string(status);
    result.error_message = std::string(error_message);
    state->active_semantic_ui_action_dispatch = ActiveSemanticUiActionDispatch{};
}

void StoreActiveSemanticUiActionDispatchResolution(
    uintptr_t owner_address,
    uintptr_t control_address,
    std::string_view dispatch_kind) {
    std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
    if (!g_debug_ui_overlay_state.active_semantic_ui_action_dispatch.active) {
        return;
    }

    g_debug_ui_overlay_state.active_semantic_ui_action_dispatch.owner_address = owner_address;
    g_debug_ui_overlay_state.active_semantic_ui_action_dispatch.control_address = control_address;
    g_debug_ui_overlay_state.active_semantic_ui_action_dispatch.dispatch_kind = std::string(dispatch_kind);
}

bool TryCompleteActiveSemanticUiActionOnSurfaceTransitionUnlocked(
    DebugUiOverlayState* state,
    const DebugUiSurfaceSnapshot& snapshot) {
    if (state == nullptr || !state->active_semantic_ui_action_dispatch.active || snapshot.elements.empty()) {
        return false;
    }

    const auto active_surface_root_id = GetOverlaySurfaceRootId(state->active_semantic_ui_action_dispatch.surface_id);
    if (active_surface_root_id.empty() || snapshot.surface_id.empty() || active_surface_root_id == snapshot.surface_id) {
        return false;
    }

    if (state->active_semantic_ui_action_dispatch.started_at != 0 &&
        snapshot.captured_at_milliseconds < state->active_semantic_ui_action_dispatch.started_at) {
        return false;
    }

    StoreCompletedSemanticUiActionDispatchUnlocked(state, "dispatched", "");
    return true;
}
