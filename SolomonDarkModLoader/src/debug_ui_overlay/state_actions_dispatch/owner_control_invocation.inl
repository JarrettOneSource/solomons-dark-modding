bool TryInvokeOwnerControlActionByControlAddress(
    uintptr_t owner_address,
    uintptr_t expected_vftable_address,
    uintptr_t expected_handler_address,
    uintptr_t owner_context_global_address,
    uintptr_t owner_context_binding_value,
    uintptr_t control_address,
    std::string_view owner_name,
    std::string_view action_name,
    std::string* error_message) {
    if (owner_address == 0) {
        if (error_message != nullptr) {
            *error_message = std::string(owner_name) + " activation requires a live owner object.";
        }
        return false;
    }

    if (control_address == 0) {
        if (error_message != nullptr) {
            *error_message = std::string(owner_name) + " activation is missing a live control pointer for action " +
                             std::string(action_name) + ".";
        }
        return false;
    }

    UiOwnerControlActionFn action_method = nullptr;
    if (!TryResolveOwnerControlActionMethod(
            reinterpret_cast<const void*>(owner_address),
            expected_vftable_address,
            expected_handler_address,
            &action_method,
            error_message)) {
        return false;
    }

    const auto* config = TryGetDebugUiOverlayConfig();
    if (action_name == "settings.controls" &&
        config != nullptr &&
        IsSettingsRolloutControl(*config, owner_address)) {
        uintptr_t guard_pointer = 0;
        if (TryReadPointerValueDirect(
                owner_address + config->settings_controls_guard_pointer_offset,
                &guard_pointer)) {
            const auto expected_guard_pointer =
                owner_address + config->settings_controls_expected_guard_offset;

            bool guard_pointer_is_readable = false;
            if (guard_pointer != 0) {
                std::uint8_t guard_value = 0;
                guard_pointer_is_readable = TryReadByteValueDirect(guard_pointer, &guard_value);
            }

            if (guard_pointer == 0 || !guard_pointer_is_readable) {
                std::uint8_t expected_guard_value = 0;
                uintptr_t repaired_guard_pointer = 0;
                if (TryReadByteValueDirect(expected_guard_pointer, &expected_guard_value)) {
                    repaired_guard_pointer = expected_guard_pointer;
                }

                if (ProcessMemory::Instance().TryWriteValue(
                        owner_address + config->settings_controls_guard_pointer_offset,
                        repaired_guard_pointer)) {
                    static int s_settings_controls_guard_repair_logs_remaining = 8;
                    if (s_settings_controls_guard_repair_logs_remaining > 0) {
                        --s_settings_controls_guard_repair_logs_remaining;
                        Log(
                            "Debug UI repaired settings.controls guard pointer before dispatch. owner=" +
                            HexString(owner_address) +
                            " old_guard=" + HexString(guard_pointer) +
                            " expected_guard=" + HexString(expected_guard_pointer) +
                            " new_guard=" + HexString(repaired_guard_pointer));
                    }
                }
            }
        }
    }

    UiOwnerContextGlobalBinding owner_context_binding;
    if (!TryBindUiOwnerContextGlobal(
            owner_context_global_address,
            owner_context_binding_value,
            &owner_context_binding,
            error_message)) {
        return false;
    }

    if (action_name == "settings.controls") {
        uintptr_t current_owner_context_value = 0;
        if (owner_context_binding.resolved_address != 0) {
            (void)TryReadPointerValueDirect(owner_context_binding.resolved_address, &current_owner_context_value);
        }
        Log(
            "Debug UI settings.controls owner context binding: owner=" + HexString(owner_address) +
            " control=" + HexString(control_address) +
            " owner_context_global=" + HexString(owner_context_binding.resolved_address) +
            " owner_context_prev=" + HexString(owner_context_binding.previous_value) +
            " owner_context_bound=" + HexString(owner_context_binding.bound_value) +
            " owner_context_current=" + HexString(current_owner_context_value));
    }

    auto dispatched = false;
    auto restore_owner_context = owner_context_binding.changed && owner_context_binding.previous_value != 0;
    UiOwnerControlActionException exception;
    dispatched = TryCallUiOwnerControlAction(action_method, owner_address, control_address, &exception);
    if (!dispatched) {
        uintptr_t owner_vftable = 0;
        (void)TryReadPointerValueDirect(owner_address, &owner_vftable);

        uintptr_t current_owner_context_value = 0;
        if (owner_context_binding.resolved_address != 0) {
            (void)TryReadPointerValueDirect(owner_context_binding.resolved_address, &current_owner_context_value);
        }

        if (error_message != nullptr) {
            *error_message =
                "UI action '" + std::string(action_name) + "' raised an exception during dispatch: code=" +
                HexString(static_cast<uintptr_t>(exception.code)) +
                " fault=" + HexString(exception.address) +
                " owner=" + HexString(owner_address) +
                " owner_vftable=" + HexString(owner_vftable) +
                " control=" + HexString(control_address) +
                " handler=" + HexString(reinterpret_cast<uintptr_t>(action_method)) +
                " owner_context_global=" + HexString(owner_context_binding.resolved_address) +
                " owner_context_prev=" + HexString(owner_context_binding.previous_value) +
                " owner_context_bound=" + HexString(owner_context_binding.bound_value) +
                " owner_context_current=" + HexString(current_owner_context_value) +
                " access_type=" + HexString(exception.access_type) +
                " access_address=" + HexString(exception.access_address);
        }
        restore_owner_context = owner_context_binding.changed;
    }

    if (restore_owner_context) {
        RestoreUiOwnerContextGlobal(owner_context_binding);
    }

    return dispatched;
}
