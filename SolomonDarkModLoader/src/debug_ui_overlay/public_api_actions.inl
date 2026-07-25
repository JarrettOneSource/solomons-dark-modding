void DispatchPendingDebugUiActionOnAppTick() {
    DispatchPendingSemanticUiActionRequest();
}

bool TryContinuePostRunHallOfFame(std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }

    uintptr_t application_global = 0;
    uintptr_t hall_of_fame_offset = 0;
    uintptr_t hall_of_fame_vftable = 0;
    uintptr_t hall_of_fame_continue = 0;
    uintptr_t hall_of_fame_continue_stack_bytes = 0;
    if (!TryGetBinaryLayoutNumericValue(
            "game_over.native",
            "application_global",
            &application_global) ||
        !TryGetBinaryLayoutNumericValue(
            "game_over.native",
            "application_hall_of_fame_offset",
            &hall_of_fame_offset) ||
        !TryGetBinaryLayoutNumericValue(
            "game_over.native",
            "hall_of_fame_vftable",
            &hall_of_fame_vftable) ||
        !TryGetBinaryLayoutNumericValue(
            "game_over.native",
            "hall_of_fame_continue",
            &hall_of_fame_continue) ||
        !TryGetBinaryLayoutNumericValue(
            "game_over.native",
            "hall_of_fame_continue_stack_bytes",
            &hall_of_fame_continue_stack_bytes) ||
        application_global == 0 ||
        hall_of_fame_offset == 0 ||
        hall_of_fame_vftable == 0 ||
        hall_of_fame_continue == 0 ||
        hall_of_fame_continue_stack_bytes != sizeof(std::uint32_t)) {
        if (error_message != nullptr) {
            *error_message =
                "Post-run Hall of Fame layout is incomplete.";
        }
        return false;
    }

    uintptr_t application = 0;
    uintptr_t hall_of_fame = 0;
    if (!TryReadResolvedGamePointer(
            application_global,
            &application) ||
        application == 0 ||
        !TryReadPointerValueDirect(
            application + hall_of_fame_offset,
            &hall_of_fame) ||
        hall_of_fame == 0) {
        if (error_message != nullptr) {
            *error_message =
                "The stock Hall of Fame controller is not active.";
        }
        return false;
    }

    UiOwnerControlActionFn raw_action_method = nullptr;
    if (!TryResolveOwnerControlActionMethod(
            reinterpret_cast<const void*>(hall_of_fame),
            hall_of_fame_vftable,
            hall_of_fame_continue,
            &raw_action_method,
            error_message)) {
        return false;
    }

    UiOwnerControlActionException exception;
    const auto dispatched = TryCallUiOwnerIgnoredStackArgAction(
        reinterpret_cast<UiOwnerIgnoredStackArgActionFn>(raw_action_method),
        hall_of_fame,
        0,
        &exception);
    if (!dispatched && error_message != nullptr) {
        *error_message =
            "Hall of Fame continue raised an exception during dispatch: code=" +
            HexString(static_cast<uintptr_t>(exception.code)) +
            " fault=" + HexString(exception.address) +
            " owner=" + HexString(hall_of_fame) +
            " handler=" + HexString(reinterpret_cast<uintptr_t>(raw_action_method)) +
            " access_type=" + HexString(exception.access_type) +
            " access_address=" + HexString(exception.access_address);
    }

    return dispatched;
}

bool TryGetDebugUiActionDispatchSnapshot(std::uint64_t request_id, DebugUiActionDispatchSnapshot* snapshot) {
    if (snapshot == nullptr) {
        return false;
    }

    *snapshot = DebugUiActionDispatchSnapshot{};

    std::scoped_lock lock(g_debug_ui_overlay_state.mutex);

    const auto fill_from_pending = [&](const PendingSemanticUiActionRequest& pending) {
        snapshot->request_id = pending.request_id;
        snapshot->queued_at_milliseconds = pending.queued_at;
        snapshot->snapshot_generation = pending.snapshot_generation;
        snapshot->action_id = pending.action_id;
        snapshot->target_label = pending.target_label;
        snapshot->surface_id = pending.surface_id;
        snapshot->status = "queued";
    };

    const auto fill_from_active = [&](const ActiveSemanticUiActionDispatch& active) {
        snapshot->request_id = active.request_id;
        snapshot->queued_at_milliseconds = active.queued_at;
        snapshot->started_at_milliseconds = active.started_at;
        snapshot->snapshot_generation = active.snapshot_generation;
        snapshot->owner_address = active.owner_address;
        snapshot->control_address = active.control_address;
        snapshot->action_id = active.action_id;
        snapshot->target_label = active.target_label;
        snapshot->surface_id = active.surface_id;
        snapshot->dispatch_kind = active.dispatch_kind;
        snapshot->status = active.status.empty() ? "dispatching" : active.status;
    };

    const auto fill_from_completed = [&](const CompletedSemanticUiActionDispatch& completed) {
        snapshot->request_id = completed.request_id;
        snapshot->queued_at_milliseconds = completed.queued_at;
        snapshot->started_at_milliseconds = completed.started_at;
        snapshot->completed_at_milliseconds = completed.completed_at;
        snapshot->snapshot_generation = completed.snapshot_generation;
        snapshot->owner_address = completed.owner_address;
        snapshot->control_address = completed.control_address;
        snapshot->action_id = completed.action_id;
        snapshot->target_label = completed.target_label;
        snapshot->surface_id = completed.surface_id;
        snapshot->dispatch_kind = completed.dispatch_kind;
        snapshot->status = completed.status;
        snapshot->error_message = completed.error_message;
    };

    if (request_id != 0) {
        if (g_debug_ui_overlay_state.pending_semantic_ui_action.active &&
            g_debug_ui_overlay_state.pending_semantic_ui_action.request_id == request_id) {
            fill_from_pending(g_debug_ui_overlay_state.pending_semantic_ui_action);
            return true;
        }

        if (g_debug_ui_overlay_state.active_semantic_ui_action_dispatch.active &&
            g_debug_ui_overlay_state.active_semantic_ui_action_dispatch.request_id == request_id) {
            fill_from_active(g_debug_ui_overlay_state.active_semantic_ui_action_dispatch);
            return true;
        }

        if (g_debug_ui_overlay_state.last_semantic_ui_action_dispatch.valid &&
            g_debug_ui_overlay_state.last_semantic_ui_action_dispatch.request_id == request_id) {
            fill_from_completed(g_debug_ui_overlay_state.last_semantic_ui_action_dispatch);
            return true;
        }

        return false;
    }

    if (g_debug_ui_overlay_state.pending_semantic_ui_action.active) {
        fill_from_pending(g_debug_ui_overlay_state.pending_semantic_ui_action);
        return true;
    }

    if (g_debug_ui_overlay_state.active_semantic_ui_action_dispatch.active) {
        fill_from_active(g_debug_ui_overlay_state.active_semantic_ui_action_dispatch);
        return true;
    }

    if (g_debug_ui_overlay_state.last_semantic_ui_action_dispatch.valid) {
        fill_from_completed(g_debug_ui_overlay_state.last_semantic_ui_action_dispatch);
        return true;
    }

    return false;
}

bool TryActivateDebugUiAction(
    std::string_view action_id,
    std::string_view surface_id,
    std::uint64_t* request_id,
    std::string* error_message) {
    return TryQueueSemanticUiActionRequest(action_id, surface_id, request_id, error_message);
}

bool TryActivateDebugUiAction(std::string_view action_id, std::string_view surface_id, std::string* error_message) {
    return TryActivateDebugUiAction(action_id, surface_id, nullptr, error_message);
}

bool TryActivateDebugUiElement(
    std::string_view label,
    std::string_view surface_id,
    std::uint64_t* request_id,
    std::string* error_message) {
    return TryQueueSemanticUiElementRequest(label, surface_id, request_id, error_message);
}

bool TryActivateDebugUiElement(std::string_view label, std::string_view surface_id, std::string* error_message) {
    return TryActivateDebugUiElement(label, surface_id, nullptr, error_message);
}

bool TryActivateDebugUiSnapshotElement(const DebugUiSnapshotElement& element, std::string* error_message) {
    const auto surface_root_id = GetOverlaySurfaceRootId(element.surface_id);
    if (element.action_id.empty()) {
        if (surface_root_id == "settings") {
            uintptr_t owner_address = 0;
            uintptr_t control_address = 0;
            if (!TryResolveSettingsSnapshotElementDispatch(
                    element,
                    &owner_address,
                    &control_address,
                    error_message)) {
                return false;
            }

            Log(
                "Debug UI overlay resolved semantic element dispatch. label=" + element.label +
                " surface=" + std::string(surface_root_id) + " owner=" + HexString(owner_address) +
                " control=" + HexString(control_address) +
                " handler=0x0");
            StoreActiveSemanticUiActionDispatchResolution(owner_address, control_address, "settings_control");
            return TryInvokeOwnerControlActionByControlAddress(
                owner_address,
                0,
                0,
                0,
                owner_address,
                control_address,
                "Settings Control",
                element.label,
                error_message);
        }

        if (error_message != nullptr) {
            *error_message =
                "UI element '" + element.label + "' on surface " + std::string(surface_root_id) + " is not actionable.";
        }
        return false;
    }

    uintptr_t owner_address = 0;
    if (!TryResolveLiveUiSurfaceOwner(surface_root_id, element.surface_object_ptr, &owner_address) || owner_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the active " + std::string(surface_root_id) + " surface owner.";
        }
        return false;
    }

    if (element.source_object_ptr == 0) {
        const auto* action_definition = FindUiActionDefinition(element.action_id);
        if (action_definition != nullptr &&
            (action_definition->dispatch_kind == "direct_write" ||
             action_definition->dispatch_kind == "owner_point_click")) {
            return TryActivateResolvedUiAction(
                surface_root_id,
                owner_address,
                0,
                element.action_id,
                error_message);
        }
        if (error_message != nullptr) {
            *error_message = "UI action '" + element.action_id + "' on surface " + std::string(surface_root_id) +
                             " does not have a live control pointer.";
        }
        return false;
    }

    return TryActivateResolvedUiAction(
        surface_root_id,
        owner_address,
        element.source_object_ptr,
        element.action_id,
        error_message);
}
