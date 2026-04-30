bool TryActivateResolvedUiAction(
    std::string_view surface_root_id,
    uintptr_t owner_address,
    uintptr_t control_address,
    std::string_view action_id,
    std::string* error_message) {
    if (action_id.empty()) {
        if (error_message != nullptr) {
            *error_message = "UI activation requires a non-empty action id.";
        }
        return false;
    }

    uintptr_t resolved_owner_address = 0;
    if (!TryResolvePreferredUiActionOwnerAddress(
            surface_root_id,
            owner_address,
            control_address,
            action_id,
            &resolved_owner_address,
            error_message) ||
        resolved_owner_address == 0) {
        return false;
    }

    UiActionDispatchExpectation expectation;
    if (!TryResolveUiActionDispatchExpectation(
            surface_root_id,
            action_id,
            &expectation)) {
        if (error_message != nullptr) {
            *error_message = "UI activation is not configured for surface " + std::string(surface_root_id) +
                             " action " + std::string(action_id) + ".";
        }
        return false;
    }

    if (action_id == "pause_menu.leave_game") {
        DispatchLuaRunEnded("leave_game");
    }

    if (surface_root_id == "main_menu" && action_id == "main_menu.new_game") {
        if (!TryPrepareMainMenuNewGameCompatibility(resolved_owner_address, error_message)) {
            return false;
        }
    }

    if (expectation.dispatch_kind == "owner_noarg") {
        if (!TryValidateUiActionOwnerReadiness(
                expectation,
                resolved_owner_address,
                action_id,
                error_message)) {
            return false;
        }

        uintptr_t owner_context_binding_value = 0;
        if (!TryResolveUiOwnerContextBindingValue(
                expectation,
                resolved_owner_address,
                &owner_context_binding_value,
                error_message)) {
            return false;
        }

        Log(
            "Debug UI overlay resolved semantic action dispatch. action=" + std::string(action_id) +
            " surface=" + std::string(surface_root_id) +
            " dispatch_kind=owner_noarg owner=" + HexString(resolved_owner_address) +
            " handler=" + HexString(expectation.expected_handler_address));
        StoreActiveSemanticUiActionDispatchResolution(resolved_owner_address, 0, "owner_noarg");
        return TryInvokeOwnerNoArgAction(
            resolved_owner_address,
            expectation.expected_vftable_address,
            expectation.expected_handler_address,
            expectation.owner_context_global_address,
            owner_context_binding_value,
            expectation.owner_name,
            action_id,
            error_message);
    }

    if (expectation.dispatch_kind == "owner_point_click") {
        if (!TryValidateUiActionOwnerReadiness(
                expectation,
                resolved_owner_address,
                action_id,
                error_message)) {
            return false;
        }

        const auto* action_definition = FindUiActionDefinition(action_id);
        if (action_definition == nullptr) {
            if (error_message != nullptr) {
                *error_message = "owner_point_click action '" + std::string(action_id) + "' has no action definition.";
            }
            return false;
        }

        const auto point_list_offset = GetDefinitionAddress(action_definition->addresses, "point_list_offset");
        const auto point_index = GetDefinitionAddress(action_definition->addresses, "point_index");
        const auto configured_point_stride = GetDefinitionAddress(action_definition->addresses, "point_stride");
        const auto point_x_offset = GetDefinitionAddress(action_definition->addresses, "point_x_offset");
        const auto configured_point_y_offset = GetDefinitionAddress(action_definition->addresses, "point_y_offset");
        const auto point_stride = configured_point_stride != 0 ? configured_point_stride : sizeof(std::int32_t) * 2;
        const auto point_y_offset =
            configured_point_y_offset != 0 ? configured_point_y_offset : sizeof(std::int32_t);
        if (point_list_offset == 0) {
            if (error_message != nullptr) {
                *error_message = "owner_point_click action '" + std::string(action_id) +
                                 "' is missing point_list_offset.";
            }
            return false;
        }
        if (expectation.expected_handler_address == 0) {
            if (error_message != nullptr) {
                *error_message = "owner_point_click action '" + std::string(action_id) +
                                 "' is missing a handler address.";
            }
            return false;
        }

        const auto point_address = resolved_owner_address + point_list_offset + point_index * point_stride;
        float point_x_float = 0.0f;
        float point_y_float = 0.0f;
        if (!ProcessMemory::Instance().TryReadValue(point_address + point_x_offset, &point_x_float) ||
            !ProcessMemory::Instance().TryReadValue(point_address + point_y_offset, &point_y_float)) {
            if (error_message != nullptr) {
                *error_message = "owner_point_click action '" + std::string(action_id) +
                                 "' could not read click coordinates from point " + HexString(point_address) +
                                 " owner=" + HexString(resolved_owner_address) + ".";
            }
            return false;
        }
        const auto point_x = static_cast<std::int32_t>(point_x_float);
        const auto point_y = static_cast<std::int32_t>(point_y_float);

        uintptr_t owner_context_binding_value = 0;
        if (!TryResolveUiOwnerContextBindingValue(
                expectation,
                resolved_owner_address,
                &owner_context_binding_value,
                error_message)) {
            return false;
        }

        Log(
            "Debug UI overlay resolved semantic action dispatch. action=" + std::string(action_id) +
            " surface=" + std::string(surface_root_id) +
            " dispatch_kind=owner_point_click owner=" + HexString(resolved_owner_address) +
            " handler=" + HexString(expectation.expected_handler_address) +
            " point=" + HexString(point_address) +
            " point_index=" + std::to_string(static_cast<unsigned long long>(point_index)) +
            " x=" + std::to_string(point_x) + " (" + std::to_string(point_x_float) + "f)" +
            " y=" + std::to_string(point_y) + " (" + std::to_string(point_y_float) + "f)");
        StoreActiveSemanticUiActionDispatchResolution(resolved_owner_address, point_address, "owner_point_click");
        return TryInvokeOwnerPointClickAction(
            resolved_owner_address,
            expectation.expected_vftable_address,
            expectation.expected_handler_address,
            expectation.owner_context_global_address,
            owner_context_binding_value,
            point_x,
            point_y,
            expectation.owner_name,
            action_id,
            error_message);
    }

    if (expectation.dispatch_kind == "control_child" ||
        expectation.dispatch_kind == "control_child_callback_owner") {
        uintptr_t resolved_child_control_address = 0;
        if (!TryResolveUiActionChildDispatchControlAddress(
                surface_root_id,
                resolved_owner_address,
                control_address,
                action_id,
                &resolved_child_control_address,
                error_message)) {
            return false;
        }

        uintptr_t dispatch_owner_address = resolved_owner_address;
        if (expectation.dispatch_kind == "control_child_callback_owner") {
            if (!TryReadUiActionCallbackOwnerAddress(
                    resolved_owner_address,
                    action_id,
                    &dispatch_owner_address,
                    error_message)) {
                return false;
            }
        }

        if (!TryValidateUiActionOwnerReadiness(
                expectation,
                dispatch_owner_address,
                action_id,
                error_message)) {
            return false;
        }

        uintptr_t owner_context_source_address = dispatch_owner_address;
        if (expectation.owner_context_use_callback_owner) {
            if (!TryReadUiActionCallbackOwnerAddress(
                    resolved_owner_address,
                    action_id,
                    &owner_context_source_address,
                    error_message)) {
                return false;
            }
        }

        uintptr_t owner_context_binding_value = 0;
        if (!TryResolveUiOwnerContextBindingValue(
                expectation,
                owner_context_source_address,
                &owner_context_binding_value,
                error_message)) {
            return false;
        }

        Log(
            "Debug UI overlay resolved semantic action dispatch. action=" + std::string(action_id) +
            " surface=" + std::string(surface_root_id) +
            " dispatch_kind=" + expectation.dispatch_kind +
            " owner=" + HexString(dispatch_owner_address) +
            " owner_control=" + HexString(resolved_owner_address) +
            " control=" + HexString(resolved_child_control_address) +
            " handler=" + HexString(expectation.expected_handler_address));
        StoreActiveSemanticUiActionDispatchResolution(
            dispatch_owner_address,
            resolved_child_control_address,
            expectation.dispatch_kind);
        if (action_id == "settings.controls") {
            MaybeLogSettingsControlsLiveState(
                "semantic_dispatch_ready",
                owner_address,
                resolved_owner_address,
                resolved_child_control_address,
                "CUSTOMIZE KEYBOARD",
                0.0f,
                0.0f,
                0.0f,
                0.0f);
        }
        return TryInvokeOwnerControlActionByControlAddress(
            dispatch_owner_address,
            expectation.expected_vftable_address,
            expectation.expected_handler_address,
            expectation.owner_context_global_address,
            owner_context_binding_value,
            resolved_child_control_address,
            expectation.owner_name,
            action_id,
            error_message);
    }

    if (expectation.dispatch_kind == "control_noarg") {
        Log(
            "Debug UI overlay resolved semantic action dispatch. action=" + std::string(action_id) +
            " surface=" + std::string(surface_root_id) +
            " dispatch_kind=control_noarg control=" + HexString(resolved_owner_address) +
            " handler=" + HexString(expectation.expected_handler_address));
        StoreActiveSemanticUiActionDispatchResolution(0, resolved_owner_address, "control_noarg");
        return TryInvokeControlNoArgAction(
            resolved_owner_address,
            expectation.expected_vftable_address,
            expectation.expected_handler_address,
            action_id,
            error_message);
    }

    if (expectation.dispatch_kind == "direct_write") {
        const auto* action_definition = FindUiActionDefinition(action_id);
        if (action_definition == nullptr) {
            if (error_message != nullptr) {
                *error_message = "direct_write action '" + std::string(action_id) + "' has no action definition.";
            }
            return false;
        }

        const auto write_global = GetDefinitionAddress(action_definition->addresses, "write_global");
        const auto write_value = GetDefinitionAddress(action_definition->addresses, "write_value");
        const auto write_owner_offset = GetDefinitionAddress(action_definition->addresses, "write_owner_offset");
        const auto confirm_byte_offset = GetDefinitionAddress(action_definition->addresses, "write_confirm_byte_offset");

        if (write_global == 0 && write_owner_offset == 0) {
            if (error_message != nullptr) {
                *error_message = "direct_write action '" + std::string(action_id) +
                    "' is missing both write_global and write_owner_offset.";
            }
            return false;
        }

        if (write_global != 0) {
            if (!ProcessMemory::Instance().TryWriteValue(write_global, static_cast<std::uint32_t>(write_value))) {
                if (error_message != nullptr) {
                    *error_message = "direct_write action '" + std::string(action_id) +
                        "' failed to write value " + HexString(write_value) + " to global " + HexString(write_global);
                }
                return false;
            }
        }

        if (write_owner_offset != 0 && resolved_owner_address != 0) {
            if (!ProcessMemory::Instance().TryWriteValue(
                    resolved_owner_address + write_owner_offset,
                    static_cast<std::uint32_t>(write_value))) {
                if (error_message != nullptr) {
                    *error_message = "direct_write action '" + std::string(action_id) +
                        "' failed to write value " + HexString(write_value) +
                        " to owner+" + HexString(write_owner_offset);
                }
                return false;
            }
        }

        if (confirm_byte_offset != 0 && resolved_owner_address != 0) {
            ProcessMemory::Instance().TryWriteValue(
                resolved_owner_address + confirm_byte_offset,
                static_cast<std::uint8_t>(1));
        }

        Log(
            "Debug UI overlay dispatched direct_write action. action=" + std::string(action_id) +
            " surface=" + std::string(surface_root_id) +
            " global=" + HexString(write_global) +
            " owner_offset=" + HexString(write_owner_offset) +
            " value=" + HexString(write_value) +
            " confirm_byte=" + HexString(confirm_byte_offset) +
            " owner=" + HexString(resolved_owner_address));
        StoreActiveSemanticUiActionDispatchResolution(resolved_owner_address, 0, "direct_write");
        return true;
    }

    uintptr_t resolved_control_address = 0;
    if (!TryResolveUiActionControlAddress(
            surface_root_id,
            resolved_owner_address,
            action_id,
            control_address,
            &resolved_control_address,
            error_message)) {
        return false;
    }

    Log(
        "Debug UI overlay resolved semantic action dispatch. action=" + std::string(action_id) +
        " surface=" + std::string(surface_root_id) +
        " dispatch_kind=" + expectation.dispatch_kind +
        " owner=" + HexString(resolved_owner_address) +
        " control=" + HexString(resolved_control_address) +
        " handler=" + HexString(expectation.expected_handler_address));
    StoreActiveSemanticUiActionDispatchResolution(
        resolved_owner_address,
        resolved_control_address,
        expectation.dispatch_kind);
    if (!TryValidateUiActionOwnerReadiness(
            expectation,
            resolved_owner_address,
            action_id,
            error_message)) {
        return false;
    }
    uintptr_t owner_context_binding_value = 0;
    if (!TryResolveUiOwnerContextBindingValue(
            expectation,
            resolved_owner_address,
            &owner_context_binding_value,
            error_message)) {
        return false;
    }
    return TryInvokeOwnerControlActionByControlAddress(
        resolved_owner_address,
        expectation.expected_vftable_address,
        expectation.expected_handler_address,
        expectation.owner_context_global_address,
        owner_context_binding_value,
        resolved_control_address,
        expectation.owner_name,
        action_id,
        error_message);
}
