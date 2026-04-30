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
