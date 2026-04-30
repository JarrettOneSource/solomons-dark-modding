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
