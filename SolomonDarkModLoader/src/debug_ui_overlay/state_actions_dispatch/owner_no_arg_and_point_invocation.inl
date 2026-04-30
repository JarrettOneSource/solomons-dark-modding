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
