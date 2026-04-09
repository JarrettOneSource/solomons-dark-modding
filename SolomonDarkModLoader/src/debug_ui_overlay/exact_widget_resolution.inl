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
            kUiRolloutParentOffset,
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
            kDarkCloudBrowserModalHeaderGroupLeftOffset,
            &group_left) ||
        !TryReadPlainField(
            reinterpret_cast<const void*>(source_object_ptr),
            kDarkCloudBrowserModalHeaderGroupTopOffset,
            &group_top) ||
        !TryReadPlainField(
            reinterpret_cast<const void*>(source_object_ptr),
            kDarkCloudBrowserModalHeaderGroupWidthOffset,
            &group_width) ||
        !TryReadPlainField(
            reinterpret_cast<const void*>(source_object_ptr),
            kDarkCloudBrowserModalHeaderGroupHeightOffset,
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
            kDarkCloudBrowserModalButtonRolloutOffset,
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

bool PointInsideRect(float x, float y, float left, float top, float right, float bottom) {
    return x >= left && x <= right && y >= top && y <= bottom;
}

void CacheObservedObjectLabel(uintptr_t object_address, std::string label) {
    label = TrimAsciiWhitespace(label);
    if (object_address == 0 || label.empty()) {
        return;
    }

    std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
    g_debug_ui_overlay_state.object_label_cache[object_address] = std::move(label);
}

bool TryReadCachedObjectLabel(uintptr_t object_address, std::string* label) {
    if (object_address == 0 || label == nullptr) {
        return false;
    }

    std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
    const auto cache_it = g_debug_ui_overlay_state.object_label_cache.find(object_address);
    if (cache_it == g_debug_ui_overlay_state.object_label_cache.end() || cache_it->second.empty()) {
        return false;
    }

    *label = cache_it->second;
    return true;
}

std::string ResolveDarkCloudBrowserControlLabel(
    const DebugUiOverlayConfig& config,
    uintptr_t browser_address,
    uintptr_t control_address,
    std::string label) {
    label = TrimAsciiWhitespace(label);
    if (!label.empty()) {
        return label;
    }

    if (browser_address == 0 || control_address < browser_address) {
        return {};
    }

    const auto relative_offset = static_cast<std::size_t>(control_address - browser_address);
    if (relative_offset == config.dark_cloud_browser_primary_action_control_offset) {
        return "PLAY";
    }
    if (relative_offset == config.dark_cloud_browser_secondary_action_control_offset) {
        return "SEARCH";
    }
    if (relative_offset == config.dark_cloud_browser_aux_left_control_offset) {
        return "SORT";
    }
    if (relative_offset == config.dark_cloud_browser_aux_right_control_offset) {
        return "OPTIONS";
    }
    if (relative_offset == config.dark_cloud_browser_recent_tab_control_offset) {
        return "RECENT";
    }
    if (relative_offset == config.dark_cloud_browser_online_levels_tab_control_offset) {
        return "ONLINE LEVELS";
    }
    if (relative_offset == config.dark_cloud_browser_my_levels_tab_control_offset) {
        return "MY LEVELS";
    }
    if (relative_offset == config.dark_cloud_browser_footer_action_control_offset) {
        return "MENU";
    }

    return {};
}

std::string ResolveSettingsControlLabel(const DebugUiOverlayConfig& config, uintptr_t control_address) {
    if (control_address == 0) {
        return {};
    }

    std::uint8_t label_enabled = 0;
    (void)TryReadPlainField(
        reinterpret_cast<const void*>(control_address),
        config.settings_control_label_enabled_offset,
        &label_enabled);

    uintptr_t label_pointer = 0;
    if (!TryReadPointerField(
            reinterpret_cast<const void*>(control_address),
            config.settings_control_label_pointer_offset,
            &label_pointer) ||
        label_pointer == 0) {
        return {};
    }

    std::string label;
    if (!TryReadPrintableCString(label_pointer, &label, 1, 96)) {
        return {};
    }

    if (label.empty()) {
        return {};
    }

    return label;
}

bool IsSettingsRolloutControl(const DebugUiOverlayConfig& config, uintptr_t control_address) {
    if (control_address == 0 || config.settings_rollout_vftable == 0) {
        return false;
    }

    const auto resolved_rollout_vftable =
        ProcessMemory::Instance().ResolveGameAddressOrZero(config.settings_rollout_vftable);
    if (resolved_rollout_vftable == 0) {
        return false;
    }

    uintptr_t object_vftable = 0;
    return TryReadPointerValueDirect(control_address, &object_vftable) &&
           object_vftable == resolved_rollout_vftable;
}

bool TryResolveSettingsRolloutChildControlAddress(
    const DebugUiOverlayConfig& config,
    uintptr_t rollout_control_address,
    uintptr_t matched_control_address,
    uintptr_t* child_control_address,
    std::string* error_message) {
    if (child_control_address == nullptr) {
        return false;
    }

    *child_control_address = 0;
    if (rollout_control_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Settings rollout dispatch requires a live rollout control.";
        }
        return false;
    }

    if (!IsSettingsRolloutControl(config, rollout_control_address)) {
        if (error_message != nullptr) {
            *error_message = "Settings rollout dispatch requires a known rollout control class.";
        }
        return false;
    }

    std::uint32_t child_count = 0;
    uintptr_t child_list = 0;
    if (!TryReadUInt32ValueDirect(
            rollout_control_address + config.settings_control_child_count_offset,
            &child_count) ||
        !TryReadPointerValueDirect(
            rollout_control_address + config.settings_control_child_list_offset,
            &child_list) ||
        child_count == 0 ||
        child_list == 0) {
        if (error_message != nullptr) {
            *error_message = "Settings rollout dispatch could not resolve its child control list.";
        }
        return false;
    }

    std::vector<uintptr_t> child_controls;
    child_controls.reserve(child_count);
    std::size_t labeled_child_count = 0;
    for (std::uint32_t child_index = 0; child_index < child_count; ++child_index) {
        uintptr_t child_control = 0;
        if (!TryReadPointerValueDirect(
                child_list + child_index * sizeof(uintptr_t),
                &child_control) ||
            child_control == 0) {
            continue;
        }

        child_controls.push_back(child_control);
        if (!ResolveSettingsControlLabel(config, child_control).empty()) {
            ++labeled_child_count;
        }
    }

    if (child_controls.empty()) {
        if (error_message != nullptr) {
            *error_message = "Settings rollout dispatch did not expose any live child controls.";
        }
        return false;
    }

    uintptr_t selected_child_control = 0;
    if (matched_control_address != 0 && matched_control_address != rollout_control_address) {
        const auto selected_child_it =
            std::find(child_controls.begin(), child_controls.end(), matched_control_address);
        if (selected_child_it == child_controls.end()) {
            if (error_message != nullptr) {
                *error_message =
                    "Settings rollout dispatch resolved a child control that is not in the live rollout child list.";
            }
            return false;
        }

        selected_child_control = *selected_child_it;
    } else if (child_controls.size() == 1 || labeled_child_count == 0) {
        selected_child_control = child_controls.front();
    } else {
        if (error_message != nullptr) {
            *error_message =
                "Settings rollout root matched a labeled container without a unique actionable child.";
        }
        return false;
    }

    *child_control_address = selected_child_control;
    return true;
}

bool TryResolveSettingsRolloutDispatchControlAddress(
    const DebugUiOverlayConfig& config,
    uintptr_t rollout_control_address,
    uintptr_t matched_control_address,
    uintptr_t* dispatch_control_address,
    std::string* error_message) {
    if (dispatch_control_address == nullptr) {
        return false;
    }

    *dispatch_control_address = 0;
    if (config.settings_control_dispatch_offset == 0) {
        if (error_message != nullptr) {
            *error_message = "Settings child control dispatch offset is not configured.";
        }
        return false;
    }

    uintptr_t selected_child_control = 0;
    if (!TryResolveSettingsRolloutChildControlAddress(
            config,
            rollout_control_address,
            matched_control_address,
            &selected_child_control,
            error_message)) {
        return false;
    }

    *dispatch_control_address = selected_child_control + config.settings_control_dispatch_offset;

    static int s_settings_rollout_dispatch_logs_remaining = 32;
    if (s_settings_rollout_dispatch_logs_remaining > 0) {
        --s_settings_rollout_dispatch_logs_remaining;
        Log(
            "Debug UI settings rollout dispatch resolved: owner=" + HexString(rollout_control_address) +
            " matched=" + HexString(matched_control_address) +
            " child=" + HexString(selected_child_control) +
            " dispatch=" + HexString(*dispatch_control_address));
    }

    return true;
}

bool TryResolveSettingsDispatchControlAddress(
    const DebugUiOverlayConfig& config,
    uintptr_t owner_control_address,
    uintptr_t matched_control_address,
    std::string_view action_id,
    uintptr_t* dispatch_control_address,
    std::string* error_message) {
    if (dispatch_control_address == nullptr) {
        return false;
    }

    *dispatch_control_address = 0;
    if (owner_control_address == 0 || matched_control_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Settings activation requires a live owner control and a matched control object.";
        }
        return false;
    }

    if (IsSettingsRolloutControl(config, owner_control_address)) {
        const auto* action_definition =
            !action_id.empty() ? FindUiActionDefinition(action_id) : nullptr;
        const auto use_raw_child_control =
            action_definition != nullptr &&
            GetDefinitionAddress(action_definition->addresses, "raw_child_control") != 0;
        if (use_raw_child_control &&
            TryResolveSettingsRolloutChildControlAddress(
                config,
                owner_control_address,
                matched_control_address,
                dispatch_control_address,
                error_message)) {
            Log(
                "Debug UI settings rollout raw child dispatch resolved: action=" +
                std::string(action_id) +
                " owner=" + HexString(owner_control_address) +
                " matched=" + HexString(matched_control_address) +
                " child=" + HexString(*dispatch_control_address));
            return true;
        }

        if (!action_id.empty()) {
            if (TryResolveUiActionControlChildDispatchAddress(
                    owner_control_address,
                    action_id,
                    dispatch_control_address,
                    error_message)) {
                Log(
                    "Debug UI settings rollout dispatch resolved via action definition: action=" +
                    std::string(action_id) +
                    " owner=" + HexString(owner_control_address) +
                    " matched=" + HexString(matched_control_address) +
                    " dispatch=" + HexString(*dispatch_control_address));
                return true;
            }
        }

        return TryResolveSettingsRolloutDispatchControlAddress(
            config,
            owner_control_address,
            matched_control_address,
            dispatch_control_address,
            error_message);
    }

    if (matched_control_address == owner_control_address) {
        if (error_message != nullptr) {
            *error_message =
                "Settings element resolved to a root control without a known semantic child dispatch token.";
        }
        return false;
    }

    if (config.settings_control_dispatch_offset == 0) {
        if (error_message != nullptr) {
            *error_message = "Settings child control dispatch offset is not configured.";
        }
        return false;
    }

    *dispatch_control_address = matched_control_address + config.settings_control_dispatch_offset;
    return true;
}

bool TryReadExactControlRect(
    const DebugUiOverlayConfig& config,
    const void* control_object,
    float* left,
    float* top,
    float* right,
    float* bottom) {
    return TryReadEmbeddedWidgetRect(
        control_object,
        0,
        config.dark_cloud_browser_control_left_offset,
        config.dark_cloud_browser_control_top_offset,
        config.dark_cloud_browser_control_width_offset,
        config.dark_cloud_browser_control_height_offset,
        left,
        top,
        right,
        bottom);
}
