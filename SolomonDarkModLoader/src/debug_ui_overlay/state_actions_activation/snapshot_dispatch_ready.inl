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
