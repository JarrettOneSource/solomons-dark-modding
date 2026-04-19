bool TryResolveUiActionControlAddress(
    std::string_view surface_root_id,
    uintptr_t owner_address,
    std::string_view action_id,
    uintptr_t fallback_control_address,
    uintptr_t* control_address,
    std::string* error_message) {
    if (control_address == nullptr) {
        return false;
    }

    *control_address = 0;

    if (owner_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve a live owner for action " + std::string(action_id) + ".";
        }
        return false;
    }

    const auto* action_definition = FindUiActionDefinition(action_id);
    if (action_definition == nullptr) {
        if (error_message != nullptr) {
            *error_message = "UI action '" + std::string(action_id) + "' is not defined in binary-layout.ini.";
        }
        return false;
    }

    const auto control_offset = GetDefinitionAddress(action_definition->addresses, "control_offset");
    if (control_offset != 0) {
        *control_address = owner_address + control_offset;
        return true;
    }

    if (fallback_control_address != 0) {
        *control_address = fallback_control_address;
        return true;
    }

    if (error_message != nullptr) {
        *error_message =
            "UI action '" + std::string(action_id) + "' on surface " + std::string(surface_root_id) +
            " does not have a configured live control pointer path.";
    }
    return false;
}

bool TryResolveUiActionControlChildDispatchAddress(
    uintptr_t owner_address,
    std::string_view action_id,
    uintptr_t* control_address,
    std::string* error_message) {
    if (control_address == nullptr) {
        return false;
    }

    *control_address = 0;
    if (owner_address == 0) {
        if (error_message != nullptr) {
            *error_message = "UI action '" + std::string(action_id) + "' requires a live rollout control owner.";
        }
        return false;
    }

    const auto* action_definition = FindUiActionDefinition(action_id);
    if (action_definition == nullptr) {
        if (error_message != nullptr) {
            *error_message = "UI action '" + std::string(action_id) + "' is not defined in binary-layout.ini.";
        }
        return false;
    }

    const auto count_offset = GetDefinitionAddress(action_definition->addresses, "control_child_count_offset");
    const auto list_offset = GetDefinitionAddress(action_definition->addresses, "control_child_list_offset");
    const auto child_index = GetDefinitionAddress(action_definition->addresses, "control_child_index");
    const auto dispatch_offset = GetDefinitionAddress(action_definition->addresses, "control_child_dispatch_offset");
    const auto use_raw_child = GetDefinitionAddress(action_definition->addresses, "control_child_use_raw") != 0;
    if (count_offset == 0 || list_offset == 0 || (!use_raw_child && dispatch_offset == 0)) {
        if (error_message != nullptr) {
            *error_message =
                "UI action '" + std::string(action_id) + "' is missing rollout child dispatch offsets.";
        }
        return false;
    }

    std::uint32_t child_count = 0;
    uintptr_t child_list = 0;
    if (!TryReadUInt32ValueDirect(owner_address + count_offset, &child_count) ||
        !TryReadPointerValueDirect(owner_address + list_offset, &child_list) ||
        child_count == 0 || child_list == 0) {
        if (error_message != nullptr) {
            *error_message =
                "UI action '" + std::string(action_id) + "' could not resolve rollout child list state.";
        }
        return false;
    }

    if (child_index >= child_count) {
        if (error_message != nullptr) {
            *error_message =
                "UI action '" + std::string(action_id) + "' requested rollout child index " +
                std::to_string(child_index) + " but only " + std::to_string(child_count) + " child entries exist.";
        }
        return false;
    }

    uintptr_t child_address = 0;
    if (!TryReadPointerValueDirect(
            child_list + child_index * sizeof(uintptr_t),
            &child_address) ||
        child_address == 0) {
        if (error_message != nullptr) {
            *error_message =
                "UI action '" + std::string(action_id) + "' could not resolve the selected rollout child entry.";
        }
        return false;
    }

    *control_address = use_raw_child ? child_address : (child_address + dispatch_offset);
    Log(
        "Debug UI control_child dispatch state: action=" + std::string(action_id) +
        " owner=" + HexString(owner_address) +
        " child_count=" + std::to_string(child_count) +
        " child_list=" + HexString(child_list) +
        " child_index=" + std::to_string(child_index) +
        " child=" + HexString(child_address) +
        " use_raw_child=" + std::to_string(use_raw_child ? 1 : 0) +
        " dispatch_control=" + HexString(*control_address));
    if (action_id == "settings.controls") {
        MaybeLogSettingsControlsLiveState(
            "control_child_dispatch_resolve",
            0,
            owner_address,
            child_address,
            "CUSTOMIZE KEYBOARD",
            0.0f,
            0.0f,
            0.0f,
            0.0f);
    }
    return true;
}

namespace {

constexpr std::size_t kTitleMainMenuHasPreviousSaveOffset = 0x474;

std::filesystem::path GetStagedSurvivalSaveDirectoryPath() {
    return GetHostProcessDirectory() / "savegames" / "solomondark" / "savegames" / "_survival";
}

bool TryDeleteStagedSurvivalSaveDirectory(std::string* error_message) {
    std::error_code exists_error;
    const auto save_directory = GetStagedSurvivalSaveDirectoryPath();
    if (!std::filesystem::exists(save_directory, exists_error)) {
        return true;
    }

    std::error_code remove_error;
    std::filesystem::remove_all(save_directory, remove_error);
    if (!remove_error) {
        Log("Debug UI compatibility: deleted staged survival save directory at " + save_directory.string());
        return true;
    }

    if (error_message != nullptr) {
        *error_message =
            "Unable to delete the staged survival save directory at " + save_directory.string() +
            ": " + remove_error.message();
    }
    return false;
}

bool TryPrepareMainMenuNewGameCompatibility(uintptr_t main_menu_address, std::string* error_message) {
    if (main_menu_address == 0) {
        return true;
    }

    std::uint8_t has_previous_save = 0;
    if (!TryReadByteValueDirect(main_menu_address + kTitleMainMenuHasPreviousSaveOffset, &has_previous_save)) {
        if (error_message != nullptr) {
            *error_message =
                "Unable to read the Main Menu previous-save flag at " +
                HexString(main_menu_address + kTitleMainMenuHasPreviousSaveOffset) + ".";
        }
        return false;
    }

    if (has_previous_save == 0) {
        return true;
    }

    if (!TryDeleteStagedSurvivalSaveDirectory(error_message)) {
        return false;
    }

    constexpr std::uint8_t kNoPreviousSave = 0;
    if (!ProcessMemory::Instance().TryWriteValue(
            main_menu_address + kTitleMainMenuHasPreviousSaveOffset,
            kNoPreviousSave)) {
        if (error_message != nullptr) {
            *error_message =
                "Unable to clear the Main Menu previous-save flag at " +
                HexString(main_menu_address + kTitleMainMenuHasPreviousSaveOffset) + ".";
        }
        return false;
    }

    Log(
        "Debug UI compatibility: bypassed existing-save confirm for NEW GAME. menu=" +
        HexString(main_menu_address) + " cleared +" +
        HexString(kTitleMainMenuHasPreviousSaveOffset) + ".");
    return true;
}

}  // namespace

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

bool IsDebugUiSnapshotActionElementDispatchReady(
    const DebugUiSnapshotElement& element,
    std::string* error_message) {
    if (element.action_id.empty()) {
        if (error_message != nullptr) {
            *error_message = "snapshot element does not carry an action id.";
        }
        return false;
    }

    const auto surface_root_id = GetOverlaySurfaceRootId(element.surface_id);
    uintptr_t resolved_owner_address = 0;
    if (!TryResolvePreferredUiActionOwnerAddress(
            surface_root_id,
            element.surface_object_ptr,
            element.source_object_ptr,
            element.action_id,
            &resolved_owner_address,
            error_message) ||
        resolved_owner_address == 0) {
        return false;
    }

    UiActionDispatchExpectation expectation;
    if (!TryResolveUiActionDispatchExpectation(
            surface_root_id,
            element.action_id,
            &expectation)) {
        if (error_message != nullptr) {
            *error_message =
                "UI action '" + element.action_id + "' does not have a configured semantic dispatch path.";
        }
        return false;
    }

    if (expectation.dispatch_kind == "owner_noarg") {
        return TryValidateUiActionOwnerReadiness(
            expectation,
            resolved_owner_address,
            element.action_id,
            error_message);
    }

    if (expectation.dispatch_kind == "owner_point_click") {
        return TryValidateUiActionOwnerReadiness(
            expectation,
            resolved_owner_address,
            element.action_id,
            error_message);
    }

    if (expectation.dispatch_kind == "control_child" ||
        expectation.dispatch_kind == "control_child_callback_owner") {
        uintptr_t resolved_child_control_address = 0;
        if (!TryResolveUiActionChildDispatchControlAddress(
                surface_root_id,
                resolved_owner_address,
                element.source_object_ptr,
                element.action_id,
                &resolved_child_control_address,
                error_message) ||
            resolved_child_control_address == 0) {
            return false;
        }

        uintptr_t dispatch_owner_address = resolved_owner_address;
        if (expectation.dispatch_kind == "control_child_callback_owner" &&
            !TryReadUiActionCallbackOwnerAddress(
                resolved_owner_address,
                element.action_id,
                &dispatch_owner_address,
                error_message)) {
            return false;
        }

        return TryValidateUiActionOwnerReadiness(
            expectation,
            dispatch_owner_address,
            element.action_id,
            error_message);
    }

    if (expectation.dispatch_kind == "control_noarg") {
        return true;
    }

    uintptr_t resolved_control_address = 0;
    if (!TryResolveUiActionControlAddress(
            surface_root_id,
            resolved_owner_address,
            element.action_id,
            element.source_object_ptr,
            &resolved_control_address,
            error_message) ||
        resolved_control_address == 0) {
        return false;
    }

    return TryValidateUiActionOwnerReadiness(
        expectation,
        resolved_owner_address,
        element.action_id,
        error_message);
}
