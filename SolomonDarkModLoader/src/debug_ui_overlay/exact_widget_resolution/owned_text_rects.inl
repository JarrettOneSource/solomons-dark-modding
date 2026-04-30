bool TryResolveDarkCloudBrowserModalLocalTextRect(
    const DebugUiOverlayConfig& config,
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

    float local_left = 0.0f;
    float local_top = 0.0f;
    float local_right = 0.0f;
    float local_bottom = 0.0f;
    if (!TryReadExactControlRect(
            config,
            reinterpret_cast<const void*>(source_object_ptr),
            &local_left,
            &local_top,
            &local_right,
            &local_bottom)) {
        return false;
    }

    if (!IsLocalSubsurfaceRect(local_left, local_top, local_right, local_bottom)) {
        return false;
    }

    uintptr_t browser_address = 0;
    const auto has_browser = TryGetCurrentDarkCloudBrowser(&browser_address) && browser_address != 0;

    uintptr_t rollout_address = 0;
    if (TryReadPointerField(
            reinterpret_cast<const void*>(source_object_ptr),
            config.dark_cloud_browser_modal_button_rollout_offset,
            &rollout_address) &&
        rollout_address != 0) {
        float rollout_left = 0.0f;
        float rollout_top = 0.0f;
        float rollout_right = 0.0f;
        float rollout_bottom = 0.0f;
        if (TryReadDarkCloudBrowserModalRolloutScreenRect(
                config,
                rollout_address,
                &rollout_left,
                &rollout_top,
                &rollout_right,
                &rollout_bottom)) {
            const auto rollout_width = rollout_right - rollout_left;
            const auto rollout_height = rollout_bottom - rollout_top;
            if (local_left >= -16.0f && local_top >= -16.0f &&
                local_right <= rollout_width + 32.0f && local_bottom <= rollout_height + 32.0f) {
                if (has_browser) {
                    RememberDarkCloudBrowserModalRootRect(
                        browser_address,
                        rollout_left,
                        rollout_top,
                        rollout_right,
                        rollout_bottom);
                }

                const auto control_screen_left = rollout_left + local_left;
                const auto control_screen_top = rollout_top + local_top;
                const auto control_screen_right = rollout_left + local_right;
                const auto control_screen_bottom = rollout_top + local_bottom;
                if (IsPlausibleSurfaceWidgetRect(
                        control_screen_left,
                        control_screen_top,
                        control_screen_right - control_screen_left,
                        control_screen_bottom - control_screen_top)) {
                    *left = control_screen_left + raw_left;
                    *top = control_screen_top + raw_top;
                    *right = control_screen_left + raw_right;
                    *bottom = control_screen_top + raw_bottom;
                    return IsPlausibleSurfaceWidgetRect(*left, *top, *right - *left, *bottom - *top);
                }
            }
        }
    }

    if (!has_browser) {
        return false;
    }

    float modal_left = 0.0f;
    float modal_top = 0.0f;
    float modal_right = 0.0f;
    float modal_bottom = 0.0f;
    if (!TryReadTrackedDarkCloudBrowserModalRootRect(
            browser_address,
            &modal_left,
            &modal_top,
            &modal_right,
            &modal_bottom)) {
        return false;
    }

    const auto modal_width = modal_right - modal_left;
    const auto modal_height = modal_bottom - modal_top;
    if (local_left < -16.0f || local_top < -16.0f ||
        local_right > modal_width + 32.0f || local_bottom > modal_height + 32.0f) {
        return false;
    }

    *left = modal_left + local_left;
    *top = modal_top + local_top;
    *right = modal_left + local_right;
    *bottom = modal_top + local_bottom;
    return IsPlausibleSurfaceWidgetRect(*left, *top, *right - *left, *bottom - *top);
}

bool TryResolveOwnedExactTextRect(
    std::string_view surface_id,
    uintptr_t caller_address,
    uintptr_t source_object_ptr,
    float* left,
    float* top,
    float* right,
    float* bottom) {
    const auto normalized_caller_address = NormalizeObservedCodeAddress(caller_address);
    if (surface_id == "settings") {
        uintptr_t settings_address = 0;
        if (!TryGetActiveSettingsRender(&settings_address) || settings_address == 0) {
            return false;
        }

        const auto* config = TryGetDebugUiOverlayConfig();
        if (config == nullptr) {
            return false;
        }

        return TryReadOwnedSettingsTextRect(
            *config,
            settings_address,
            normalized_caller_address,
            source_object_ptr,
            left,
            top,
            right,
            bottom);
    }

    if (surface_id == "quick_panel") {
        if (TryReadRecordedExactControlRect("quick_panel", source_object_ptr, left, top, right, bottom)) {
            return true;
        }

        const auto* config = TryGetDebugUiOverlayConfig();
        if (config == nullptr) {
            return false;
        }

        uintptr_t quick_panel_address = 0;
        if (!TryReadTrackedMyQuickPanel(&quick_panel_address) || quick_panel_address == 0 ||
            !IsQuickPanelOwnedObject(*config, quick_panel_address, source_object_ptr)) {
            return false;
        }

        return TryReadTranslatedQuickPanelWidgetRect(
            *config,
            quick_panel_address,
            source_object_ptr,
            left,
            top,
            right,
            bottom);
    }

    if (surface_id == "dark_cloud_browser") {
        if (TryReadRecordedExactControlRect("dark_cloud_browser", source_object_ptr, left, top, right, bottom)) {
            return true;
        }

        const auto* config = TryGetDebugUiOverlayConfig();
        if (config == nullptr) {
            return false;
        }

        uintptr_t browser_address = 0;
        if (TryGetCurrentDarkCloudBrowser(&browser_address) && browser_address != 0 &&
            TryReadTranslatedWidgetRectToRoot(
                *config,
                browser_address,
                source_object_ptr,
                left,
                top,
                right,
                bottom)) {
            return true;
        }

        if (TryResolveDarkCloudBrowserModalLocalTextRect(
                *config,
                source_object_ptr,
                *left,
                *top,
                *right,
                *bottom,
                left,
                top,
                right,
                bottom)) {
            return true;
        }

        return TryResolveDarkCloudBrowserModalHeaderTextRect(
            *config,
            caller_address,
            source_object_ptr,
            *left,
            *top,
            *right,
            *bottom,
            left,
            top,
            right,
            bottom);
    }

    return false;
}
