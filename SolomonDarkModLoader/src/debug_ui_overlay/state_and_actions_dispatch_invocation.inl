bool TryReadPointerValueDirect(uintptr_t address, uintptr_t* value) {
    if (address == 0 || value == nullptr) {
        return false;
    }

    __try {
        *value = *reinterpret_cast<const uintptr_t*>(address);
        return true;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return false;
    }
}

bool TryReadPointerFieldDirect(const void* object, size_t offset, uintptr_t* value) {
    if (object == nullptr || value == nullptr) {
        return false;
    }

    const auto field_address = reinterpret_cast<uintptr_t>(object) + offset;
    return TryReadPointerValueDirect(field_address, value);
}

struct UiOwnerContextGlobalBinding {
    uintptr_t resolved_address = 0;
    uintptr_t previous_value = 0;
    uintptr_t bound_value = 0;
    bool changed = false;
};

bool TryResolveUiOwnerContextBindingValue(
    const UiActionDispatchExpectation& expectation,
    uintptr_t owner_address,
    uintptr_t* binding_value,
    std::string* error_message) {
    if (binding_value == nullptr) {
        return false;
    }

    *binding_value = owner_address;
    if (owner_address == 0) {
        if (error_message != nullptr) {
            *error_message = "UI owner context binding requires a live owner object.";
        }
        return false;
    }

    const uintptr_t context_source_globals[] = {
        expectation.owner_context_source_global_address,
        expectation.owner_context_source_alt_global_address_1,
        expectation.owner_context_source_alt_global_address_2,
    };

    auto has_explicit_source = false;
    for (const auto source_global_address : context_source_globals) {
        if (source_global_address == 0) {
            continue;
        }

        has_explicit_source = true;
        uintptr_t source_value = 0;
        if (TryReadResolvedGamePointer(source_global_address, &source_value) && source_value != 0) {
            *binding_value = source_value;
            return true;
        }
    }

    if (has_explicit_source) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve a non-zero UI owner context source pointer.";
        }
        return false;
    }

    return true;
}

bool TryValidateUiActionOwnerReadiness(
    const UiActionDispatchExpectation& expectation,
    uintptr_t owner_address,
    std::string_view action_name,
    std::string* error_message) {
    if (owner_address == 0) {
        return true;
    }

    if (expectation.owner_optional_enabled_byte_pointer_offset != 0) {
        uintptr_t enabled_byte_pointer = 0;
        if (!TryReadPointerValueDirect(
                owner_address + expectation.owner_optional_enabled_byte_pointer_offset,
                &enabled_byte_pointer)) {
            if (error_message != nullptr) {
                *error_message =
                    "UI action '" + std::string(action_name) + "' owner readiness probe could not read " +
                    HexString(owner_address + expectation.owner_optional_enabled_byte_pointer_offset) +
                    " from owner=" + HexString(owner_address) + ".";
            }
            return false;
        }

        if (enabled_byte_pointer != 0) {
            std::uint8_t enabled_byte = 0;
            if (!TryReadByteValueDirect(enabled_byte_pointer, &enabled_byte)) {
                if (error_message != nullptr) {
                    *error_message =
                        "UI action '" + std::string(action_name) + "' owner is not ready yet: field +" +
                        HexString(expectation.owner_optional_enabled_byte_pointer_offset) + " = " +
                        HexString(enabled_byte_pointer) + " owner=" + HexString(owner_address) + ".";
                }
                return false;
            }

            if (enabled_byte == 0) {
                if (error_message != nullptr) {
                    *error_message =
                        "UI action '" + std::string(action_name) + "' owner is not ready yet: field +" +
                        HexString(expectation.owner_optional_enabled_byte_pointer_offset) + " = " +
                        HexString(enabled_byte_pointer) + " byte=0 owner=" + HexString(owner_address) + ".";
                }
                return false;
            }
        }
    }

    if (expectation.owner_ready_pointer_offset == 0) {
        return true;
    }

    uintptr_t owner_ready_value = 0;
    if (!TryReadPointerValueDirect(owner_address + expectation.owner_ready_pointer_offset, &owner_ready_value)) {
        if (error_message != nullptr) {
            *error_message =
                "UI action '" + std::string(action_name) + "' owner readiness probe could not read " +
                HexString(owner_address + expectation.owner_ready_pointer_offset) +
                " from owner=" + HexString(owner_address) + ".";
        }
        return false;
    }

    if (owner_ready_value < 0x10000) {
        if (error_message != nullptr) {
            *error_message =
                "UI action '" + std::string(action_name) + "' owner is not ready yet: field +" +
                HexString(expectation.owner_ready_pointer_offset) + " = " + HexString(owner_ready_value) +
                " owner=" + HexString(owner_address) + ".";
        }
        return false;
    }

    if (owner_ready_value >= 0x80000000u) {
        if (error_message != nullptr) {
            *error_message =
                "UI action '" + std::string(action_name) + "' owner is not ready yet: field +" +
                HexString(expectation.owner_ready_pointer_offset) + " = " + HexString(owner_ready_value) +
                " owner=" + HexString(owner_address) + ".";
        }
        return false;
    }

    std::uint32_t owner_ready_probe = 0;
    if (!TryReadUInt32ValueDirect(owner_ready_value + sizeof(std::uint32_t), &owner_ready_probe)) {
        if (error_message != nullptr) {
            *error_message =
                "UI action '" + std::string(action_name) + "' owner readiness probe could not read pointee " +
                HexString(owner_ready_value + sizeof(std::uint32_t)) +
                " from owner=" + HexString(owner_address) +
                " field=" + HexString(owner_ready_value) + ".";
        }
        return false;
    }

    return true;
}

bool TryBindUiOwnerContextGlobal(
    uintptr_t absolute_global_address,
    uintptr_t binding_value,
    UiOwnerContextGlobalBinding* binding,
    std::string* error_message) {
    if (binding == nullptr) {
        return absolute_global_address == 0;
    }

    *binding = UiOwnerContextGlobalBinding{};
    if (absolute_global_address == 0 || binding_value == 0) {
        return true;
    }

    const auto resolved_address = ProcessMemory::Instance().ResolveGameAddressOrZero(absolute_global_address);
    if (resolved_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the configured UI owner context global.";
        }
        return false;
    }

    uintptr_t previous_value = 0;
    if (!TryReadPointerValueDirect(resolved_address, &previous_value)) {
        if (error_message != nullptr) {
            *error_message = "Unable to read the configured UI owner context global.";
        }
        return false;
    }

    binding->resolved_address = resolved_address;
    binding->previous_value = previous_value;
    binding->bound_value = binding_value;
    if (previous_value == binding_value) {
        return true;
    }

    if (!ProcessMemory::Instance().TryWriteValue(resolved_address, binding_value)) {
        if (error_message != nullptr) {
            *error_message = "Unable to bind the configured UI owner context global.";
        }
        return false;
    }

    binding->changed = true;
    return true;
}

void RestoreUiOwnerContextGlobal(const UiOwnerContextGlobalBinding& binding) {
    if (!binding.changed || binding.resolved_address == 0) {
        return;
    }

    (void)ProcessMemory::Instance().TryWriteValue(binding.resolved_address, binding.previous_value);
}

struct UiOwnerControlActionException {
    DWORD code = 0;
    uintptr_t address = 0;
    uintptr_t access_type = 0;
    uintptr_t access_address = 0;
};

int CaptureUiOwnerControlActionException(
    EXCEPTION_POINTERS* exception_pointers,
    UiOwnerControlActionException* exception) {
    if (exception == nullptr || exception_pointers == nullptr || exception_pointers->ExceptionRecord == nullptr) {
        return EXCEPTION_EXECUTE_HANDLER;
    }

    const auto* record = exception_pointers->ExceptionRecord;
    exception->code = record->ExceptionCode;
    exception->address = reinterpret_cast<uintptr_t>(record->ExceptionAddress);
    if (record->NumberParameters >= 1) {
        exception->access_type = static_cast<uintptr_t>(record->ExceptionInformation[0]);
    }
    if (record->NumberParameters >= 2) {
        exception->access_address = static_cast<uintptr_t>(record->ExceptionInformation[1]);
    }

    return EXCEPTION_EXECUTE_HANDLER;
}

bool TryCallUiOwnerControlAction(
    UiOwnerControlActionFn action_method,
    uintptr_t owner_address,
    uintptr_t control_address,
    UiOwnerControlActionException* exception) {
    if (action_method == nullptr || owner_address == 0 || control_address == 0) {
        return false;
    }

    if (exception != nullptr) {
        *exception = UiOwnerControlActionException{};
    }

    __try {
        action_method(reinterpret_cast<void*>(owner_address), reinterpret_cast<void*>(control_address));
        return true;
    } __except (CaptureUiOwnerControlActionException(GetExceptionInformation(), exception)) {
        return false;
    }
}

bool TryCallUiOwnerNoArgAction(
    UiOwnerNoArgActionFn action_method,
    uintptr_t owner_address,
    UiOwnerControlActionException* exception) {
    if (action_method == nullptr || owner_address == 0) {
        return false;
    }

    if (exception != nullptr) {
        *exception = UiOwnerControlActionException{};
    }

    __try {
        action_method(reinterpret_cast<void*>(owner_address));
        return true;
    } __except (CaptureUiOwnerControlActionException(GetExceptionInformation(), exception)) {
        return false;
    }
}

bool TryCallUiOwnerPointClickAction(
    UiOwnerPointClickActionFn action_method,
    uintptr_t owner_address,
    std::int32_t x,
    std::int32_t y,
    UiOwnerControlActionException* exception) {
    if (action_method == nullptr || owner_address == 0) {
        return false;
    }

    if (exception != nullptr) {
        *exception = UiOwnerControlActionException{};
    }

    __try {
        action_method(reinterpret_cast<void*>(owner_address), x, y);
        return true;
    } __except (CaptureUiOwnerControlActionException(GetExceptionInformation(), exception)) {
        return false;
    }
}

bool TryResolveOwnerControlActionMethod(
    const void* object,
    uintptr_t expected_vftable_address,
    uintptr_t expected_handler_address,
    UiOwnerControlActionFn* action_method,
    std::string* error_message) {
    if (object == nullptr || action_method == nullptr) {
        if (error_message != nullptr) {
            *error_message = "Control activation requires a live owner object and a destination method.";
        }
        return false;
    }

    uintptr_t object_vftable = 0;
    if (!TryReadPointerFieldDirect(object, 0, &object_vftable) || object_vftable == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the owner object vftable for UI control activation.";
        }
        return false;
    }

    if (expected_vftable_address != 0) {
        const auto resolved_vftable = ProcessMemory::Instance().ResolveGameAddressOrZero(expected_vftable_address);
        if (resolved_vftable == 0 || object_vftable != resolved_vftable) {
            if (error_message != nullptr) {
                *error_message = "Owner object no longer matches the expected UI class vftable.";
            }
            return false;
        }
    }

    if (expected_handler_address != 0) {
        const auto resolved_handler = ProcessMemory::Instance().ResolveGameAddressOrZero(expected_handler_address);
        if (resolved_handler == 0) {
            if (error_message != nullptr) {
                *error_message = "Unable to resolve the configured UI control action handler.";
            }
            return false;
        }

        *action_method = reinterpret_cast<UiOwnerControlActionFn>(resolved_handler);
        return true;
    }

    uintptr_t method_address = 0;
    if (!TryReadPointerValueDirect(
            object_vftable + kUiOwnerControlActionVtableSlotIndex * sizeof(uintptr_t),
            &method_address) ||
        method_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the UI control action dispatch method from the owner vftable.";
        }
        return false;
    }

    *action_method = reinterpret_cast<UiOwnerControlActionFn>(method_address);
    return true;
}

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

bool TryInvokeOwnerNoArgAction(
    uintptr_t owner_address,
    uintptr_t expected_vftable_address,
    uintptr_t expected_handler_address,
    uintptr_t owner_context_global_address,
    uintptr_t owner_context_binding_value,
    std::string_view owner_name,
    std::string_view action_name,
    std::string* error_message) {
    if (owner_address == 0) {
        if (error_message != nullptr) {
            *error_message = std::string(owner_name) + " activation requires a live owner object.";
        }
        return false;
    }

    UiOwnerControlActionFn raw_action_method = nullptr;
    if (!TryResolveOwnerControlActionMethod(
            reinterpret_cast<const void*>(owner_address),
            expected_vftable_address,
            expected_handler_address,
            &raw_action_method,
            error_message)) {
        return false;
    }

    UiOwnerContextGlobalBinding owner_context_binding;
    if (!TryBindUiOwnerContextGlobal(
            owner_context_global_address,
            owner_context_binding_value,
            &owner_context_binding,
            error_message)) {
        return false;
    }

    auto restore_owner_context = owner_context_binding.changed && owner_context_binding.previous_value != 0;
    UiOwnerControlActionException exception;
    const auto dispatched = TryCallUiOwnerNoArgAction(
        reinterpret_cast<UiOwnerNoArgActionFn>(raw_action_method),
        owner_address,
        &exception);
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
                " handler=" + HexString(reinterpret_cast<uintptr_t>(raw_action_method)) +
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

bool TryInvokeOwnerPointClickAction(
    uintptr_t owner_address,
    uintptr_t expected_vftable_address,
    uintptr_t expected_handler_address,
    uintptr_t owner_context_global_address,
    uintptr_t owner_context_binding_value,
    std::int32_t x,
    std::int32_t y,
    std::string_view owner_name,
    std::string_view action_name,
    std::string* error_message) {
    if (owner_address == 0) {
        if (error_message != nullptr) {
            *error_message = std::string(owner_name) + " activation requires a live owner object.";
        }
        return false;
    }

    UiOwnerControlActionFn raw_action_method = nullptr;
    if (!TryResolveOwnerControlActionMethod(
            reinterpret_cast<const void*>(owner_address),
            expected_vftable_address,
            expected_handler_address,
            &raw_action_method,
            error_message)) {
        return false;
    }

    UiOwnerContextGlobalBinding owner_context_binding;
    if (!TryBindUiOwnerContextGlobal(
            owner_context_global_address,
            owner_context_binding_value,
            &owner_context_binding,
            error_message)) {
        return false;
    }

    auto restore_owner_context = owner_context_binding.changed && owner_context_binding.previous_value != 0;
    UiOwnerControlActionException exception;
    const auto dispatched = TryCallUiOwnerPointClickAction(
        reinterpret_cast<UiOwnerPointClickActionFn>(raw_action_method),
        owner_address,
        x,
        y,
        &exception);
    if (!dispatched) {
        uintptr_t owner_vftable = 0;
        (void)TryReadPointerValueDirect(owner_address, &owner_vftable);

        uintptr_t current_owner_context_value = 0;
        if (owner_context_binding.resolved_address != 0) {
            (void)TryReadPointerValueDirect(owner_context_binding.resolved_address, &current_owner_context_value);
        }

        if (error_message != nullptr) {
            *error_message =
                "UI action '" + std::string(action_name) + "' raised an exception during point-click dispatch: code=" +
                HexString(static_cast<uintptr_t>(exception.code)) +
                " fault=" + HexString(exception.address) +
                " owner=" + HexString(owner_address) +
                " owner_vftable=" + HexString(owner_vftable) +
                " handler=" + HexString(reinterpret_cast<uintptr_t>(raw_action_method)) +
                " x=" + std::to_string(x) +
                " y=" + std::to_string(y) +
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

bool TryInvokeControlNoArgAction(
    uintptr_t control_address,
    uintptr_t expected_vftable_address,
    uintptr_t expected_handler_address,
    std::string_view action_name,
    std::string* error_message) {
    if (control_address == 0) {
        if (error_message != nullptr) {
            *error_message =
                "UI action '" + std::string(action_name) + "' requires a live control object.";
        }
        return false;
    }

    UiOwnerControlActionFn raw_action_method = nullptr;
    if (!TryResolveOwnerControlActionMethod(
            reinterpret_cast<const void*>(control_address),
            expected_vftable_address,
            expected_handler_address,
            &raw_action_method,
            error_message)) {
        return false;
    }

    uintptr_t control_vftable = 0;
    uintptr_t control_owner = 0;
    uintptr_t control_context = 0;
    uintptr_t control_callback = 0;
    uintptr_t app_address = 0;
    uintptr_t current_overlay_address = 0;
    uintptr_t current_overlay_vftable = 0;
    const auto* config = TryGetDebugUiOverlayConfig();
    const auto app_global_address = GetBinaryLayoutNumericValueOrZero("debug_ui.globals", "app");
    const auto current_overlay_offset =
        GetBinaryLayoutNumericValueOrZero("debug_ui.globals", "app_current_overlay_offset");
    (void)TryReadPointerValueDirect(control_address, &control_vftable);
    if (config != nullptr) {
        (void)TryReadPointerValueDirect(control_address + config->control_noarg_owner_offset, &control_owner);
        (void)TryReadPointerValueDirect(control_address + config->control_noarg_context_offset, &control_context);
        (void)TryReadPointerValueDirect(control_address + config->control_noarg_callback_offset, &control_callback);
    }
    if (app_global_address != 0 &&
        current_overlay_offset != 0 &&
        TryReadResolvedGamePointer(app_global_address, &app_address) &&
        app_address != 0) {
        (void)TryReadPointerValueDirect(app_address + current_overlay_offset, &current_overlay_address);
        if (current_overlay_address != 0) {
            (void)TryReadPointerValueDirect(current_overlay_address, &current_overlay_vftable);
        }
    }
    Log(
        "Debug UI control_noarg dispatch state: action=" + std::string(action_name) +
        " control=" + HexString(control_address) +
        " control_vftable=" + HexString(control_vftable) +
        " control_owner=" + HexString(control_owner) +
        " control_context=" + HexString(control_context) +
        " control_callback_field=" + HexString(control_callback) +
        " app=" + HexString(app_address) +
        " current_overlay=" + HexString(current_overlay_address) +
        " current_overlay_vftable=" + HexString(current_overlay_vftable) +
        " handler=" + HexString(reinterpret_cast<uintptr_t>(raw_action_method)));

    UiOwnerControlActionException exception;
    const auto dispatched = TryCallUiOwnerNoArgAction(
        reinterpret_cast<UiOwnerNoArgActionFn>(raw_action_method),
        control_address,
        &exception);
    if (!dispatched && error_message != nullptr) {
        *error_message =
            "UI action '" + std::string(action_name) + "' raised an exception during control dispatch: code=" +
            HexString(static_cast<uintptr_t>(exception.code)) +
            " fault=" + HexString(exception.address) +
            " control=" + HexString(control_address) +
            " control_vftable=" + HexString(control_vftable) +
            " handler=" + HexString(reinterpret_cast<uintptr_t>(raw_action_method)) +
            " access_type=" + HexString(exception.access_type) +
            " access_address=" + HexString(exception.access_address);
    }

    return dispatched;
}
