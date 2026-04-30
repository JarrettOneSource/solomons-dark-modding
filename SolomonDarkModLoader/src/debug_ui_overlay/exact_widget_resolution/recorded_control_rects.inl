bool TryReadRecordedExactControlRect(
    std::string_view surface_id,
    uintptr_t source_object_ptr,
    float* left,
    float* top,
    float* right,
    float* bottom) {
    if (source_object_ptr == 0 || left == nullptr || top == nullptr || right == nullptr || bottom == nullptr) {
        return false;
    }

    std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
    for (const auto& element : g_debug_ui_overlay_state.frame_exact_control_elements) {
        if (element.object_ptr != source_object_ptr || element.surface_id != surface_id) {
            continue;
        }

        *left = element.min_x;
        *top = element.min_y;
        *right = element.max_x;
        *bottom = element.max_y;
        return true;
    }

    return false;
}

bool TryReadDarkCloudBrowserModalRolloutScreenRect(
    const DebugUiOverlayConfig& config,
    uintptr_t rollout_address,
    float* left,
    float* top,
    float* right,
    float* bottom) {
    if (rollout_address == 0 || left == nullptr || top == nullptr || right == nullptr || bottom == nullptr) {
        return false;
    }

    float rollout_local_left = 0.0f;
    float rollout_local_top = 0.0f;
    float rollout_local_right = 0.0f;
    float rollout_local_bottom = 0.0f;
    if (!TryReadExactControlRect(
            config,
            reinterpret_cast<const void*>(rollout_address),
            &rollout_local_left,
            &rollout_local_top,
            &rollout_local_right,
            &rollout_local_bottom) ||
        !IsLocalSubsurfaceRect(
            rollout_local_left,
            rollout_local_top,
            rollout_local_right,
            rollout_local_bottom)) {
        return false;
    }

    uintptr_t parent_address = 0;
    if (!TryReadPointerField(
            reinterpret_cast<const void*>(rollout_address),
            config.ui_rollout_parent_offset,
            &parent_address) ||
        parent_address == 0 || parent_address == rollout_address) {
        return false;
    }

    float parent_left = 0.0f;
    float parent_top = 0.0f;
    float parent_right = 0.0f;
    float parent_bottom = 0.0f;
    auto resolved_parent_rect = false;
    uintptr_t browser_address = 0;
    if (TryGetCurrentDarkCloudBrowser(&browser_address) && browser_address != 0) {
        resolved_parent_rect = TryReadTranslatedWidgetRectToRoot(
            config,
            browser_address,
            parent_address,
            &parent_left,
            &parent_top,
            &parent_right,
            &parent_bottom);
    }

    if (!resolved_parent_rect) {
        resolved_parent_rect = TryReadExactControlRect(
            config,
            reinterpret_cast<const void*>(parent_address),
            &parent_left,
            &parent_top,
            &parent_right,
            &parent_bottom);
    }

    if (!resolved_parent_rect ||
        !IsPlausibleSurfaceWidgetRect(parent_left, parent_top, parent_right - parent_left, parent_bottom - parent_top)) {
        return false;
    }

    *left = parent_left + rollout_local_left;
    *top = parent_top + rollout_local_top;
    *right = parent_left + rollout_local_right;
    *bottom = parent_top + rollout_local_bottom;
    return IsPlausibleSurfaceWidgetRect(*left, *top, *right - *left, *bottom - *top);
}

bool TryReadDarkCloudBrowserModalHeaderOwnerLocalRect(
    const DebugUiOverlayConfig& config,
    uintptr_t source_object_ptr,
    float* left,
    float* top,
    float* right,
    float* bottom) {
    if (source_object_ptr == 0 || left == nullptr || top == nullptr || right == nullptr || bottom == nullptr) {
        return false;
    }

    if (TryReadExactControlRect(
            config,
            reinterpret_cast<const void*>(source_object_ptr),
            left,
            top,
            right,
            bottom) &&
        IsLocalSubsurfaceRect(*left, *top, *right, *bottom)) {
        return true;
    }

    float group_left = 0.0f;
    float group_top = 0.0f;
    float group_width = 0.0f;
    float group_height = 0.0f;
    if (!TryReadPlainField(
            reinterpret_cast<const void*>(source_object_ptr),
            config.dark_cloud_browser_modal_header_group_left_offset,
            &group_left) ||
        !TryReadPlainField(
            reinterpret_cast<const void*>(source_object_ptr),
            config.dark_cloud_browser_modal_header_group_top_offset,
            &group_top) ||
        !TryReadPlainField(
            reinterpret_cast<const void*>(source_object_ptr),
            config.dark_cloud_browser_modal_header_group_width_offset,
            &group_width) ||
        !TryReadPlainField(
            reinterpret_cast<const void*>(source_object_ptr),
            config.dark_cloud_browser_modal_header_group_height_offset,
            &group_height)) {
        return false;
    }

    const auto group_right = group_left + group_width;
    const auto group_bottom = group_top + group_height;
    if (!IsLocalSubsurfaceRect(group_left, group_top, group_right, group_bottom)) {
        return false;
    }

    *left = group_left;
    *top = group_top;
    *right = group_right;
    *bottom = group_bottom;
    return true;
}

bool TryResolveDarkCloudBrowserModalHeaderTextRect(
    const DebugUiOverlayConfig& config,
    uintptr_t caller_address,
    uintptr_t source_object_ptr,
    float raw_left,
    float raw_top,
    float raw_right,
    float raw_bottom,
    float* left,
    float* top,
    float* right,
    float* bottom) {
    if (source_object_ptr == 0 || left == nullptr || top == nullptr || right == nullptr || bottom == nullptr) {
        return false;
    }

    const auto normalized_caller_address = NormalizeObservedCodeAddress(caller_address);
    if (normalized_caller_address != config.dark_cloud_browser_modal_header_text_caller) {
        return false;
    }

    uintptr_t active_browser_address = 0;
    const auto has_active_browser = TryGetCurrentDarkCloudBrowser(&active_browser_address) && active_browser_address != 0;

    uintptr_t rollout_address = 0;
    if (!TryReadDarkCloudBrowserTextOwnerAddress(config, source_object_ptr, &rollout_address) || rollout_address == 0) {
        return false;
    }

    float rollout_screen_left = 0.0f;
    float rollout_screen_top = 0.0f;
    float rollout_screen_right = 0.0f;
    float rollout_screen_bottom = 0.0f;
    if (!TryReadDarkCloudBrowserModalRolloutScreenRect(
            config,
            rollout_address,
            &rollout_screen_left,
            &rollout_screen_top,
            &rollout_screen_right,
            &rollout_screen_bottom)) {
        return false;
    }

    float owner_local_left = 0.0f;
    float owner_local_top = 0.0f;
    float owner_local_right = 0.0f;
    float owner_local_bottom = 0.0f;
    if (!TryReadDarkCloudBrowserModalHeaderOwnerLocalRect(
            config,
            source_object_ptr,
            &owner_local_left,
            &owner_local_top,
            &owner_local_right,
            &owner_local_bottom)) {
        return false;
    }

    if (has_active_browser) {
        RememberDarkCloudBrowserModalRootRect(
            active_browser_address,
            rollout_screen_left,
            rollout_screen_top,
            rollout_screen_right,
            rollout_screen_bottom);
    }

    const auto owner_screen_left = rollout_screen_left + owner_local_left;
    const auto owner_screen_top = rollout_screen_top + owner_local_top;
    const auto owner_screen_right = rollout_screen_left + owner_local_right;
    const auto owner_screen_bottom = rollout_screen_top + owner_local_bottom;
    if (!IsPlausibleSurfaceWidgetRect(
            owner_screen_left,
            owner_screen_top,
            owner_screen_right - owner_screen_left,
            owner_screen_bottom - owner_screen_top)) {
        return false;
    }

    *left = owner_screen_left + raw_left;
    *top = owner_screen_top + raw_top;
    *right = owner_screen_left + raw_right;
    *bottom = owner_screen_top + raw_bottom;
    return IsPlausibleSurfaceWidgetRect(*left, *top, *right - *left, *bottom - *top);
}
