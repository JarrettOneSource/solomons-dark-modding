std::string NormalizeDebugUiQueryToken(std::string_view value) {
    std::string normalized;
    normalized.reserve(value.size());
    for (const auto character : value) {
        if (std::isalnum(static_cast<unsigned char>(character))) {
            normalized.push_back(static_cast<char>(std::toupper(static_cast<unsigned char>(character))));
        }
    }
    return normalized;
}

const DebugUiSnapshotElement* FindBestSnapshotLabelElement(
    const DebugUiSurfaceSnapshot& snapshot,
    std::string_view label,
    std::string_view surface_id) {
    const auto normalized_label = NormalizeDebugUiQueryToken(label);
    if (normalized_label.empty()) {
        return nullptr;
    }

    const auto normalized_surface_id = NormalizeDebugUiQueryToken(surface_id);
    if (!normalized_surface_id.empty() &&
        NormalizeDebugUiQueryToken(snapshot.surface_id) != normalized_surface_id) {
        return nullptr;
    }

    const DebugUiSnapshotElement* best_match = nullptr;
    double best_score = (std::numeric_limits<double>::lowest)();
    for (const auto& element : snapshot.elements) {
        if (NormalizeDebugUiQueryToken(element.label) != normalized_label) {
            continue;
        }

        if (!normalized_surface_id.empty() &&
            NormalizeDebugUiQueryToken(GetOverlaySurfaceRootId(element.surface_id)) != normalized_surface_id) {
            continue;
        }

        const auto width = static_cast<double>(element.right - element.left);
        const auto height = static_cast<double>(element.bottom - element.top);
        const auto area = (std::max)(0.0, width) * (std::max)(0.0, height);

        auto score = 0.0;
        if (!element.action_id.empty()) {
            score += 1000000.0;
        }
        if (element.show_label) {
            score += 100000.0;
        }
        if (element.surface_id == snapshot.surface_id) {
            score += 10000.0;
        } else if (GetOverlaySurfaceRootId(element.surface_id) == GetOverlaySurfaceRootId(snapshot.surface_id)) {
            score += 1000.0;
        }

        // For label lookups, prefer the most specific visible element over broad container boxes.
        score -= area;

        if (best_match == nullptr || score > best_score) {
            best_match = &element;
            best_score = score;
        }
    }

    return best_match;
}

bool FindBestSnapshotActionElement(
    const DebugUiSurfaceSnapshot& snapshot,
    std::string_view action_id,
    std::string_view surface_id,
    DebugUiSnapshotElement* out_element) {
    if (action_id.empty()) {
        return false;
    }

    const auto surface_root_id = GetOverlaySurfaceRootId(surface_id);
    if (!surface_root_id.empty() &&
        GetOverlaySurfaceRootId(snapshot.surface_id) != surface_root_id &&
        snapshot.surface_id != surface_id) {
        return false;
    }

    const auto snapshot_surface_root_id = GetOverlaySurfaceRootId(snapshot.surface_id);

    DebugUiSnapshotElement best_match;
    bool has_match = false;
    double best_score = -1.0;
    std::string first_dispatch_rejection;
    for (const auto& element : snapshot.elements) {
        // Build a candidate with action_id resolved.  When the overlay element
        // has no action_id (common for text-observed elements), resolve the
        // action from the element's label using configured action definitions.
        DebugUiSnapshotElement candidate = element;

        if (element.action_id == action_id) {
            // Direct match — action_id already set.
        } else if (element.action_id.empty() && !element.label.empty()) {
            const auto* resolved = FindConfiguredUiActionByLabel(snapshot_surface_root_id, element.label);
            if (resolved == nullptr || resolved->id != action_id) {
                continue;
            }
            candidate.action_id = resolved->id;
        } else {
            continue;
        }

        if (!surface_root_id.empty() &&
            GetOverlaySurfaceRootId(candidate.surface_id) != surface_root_id &&
            candidate.surface_id != surface_id) {
            continue;
        }

        std::string dispatch_rejection;
        if (!IsDebugUiSnapshotActionElementDispatchReady(candidate, &dispatch_rejection)) {
            if (first_dispatch_rejection.empty()) {
                first_dispatch_rejection = dispatch_rejection.empty()
                    ? "the action dispatch path is not ready."
                    : dispatch_rejection;
            }
            continue;
        }

        auto score = static_cast<double>(
            (candidate.right - candidate.left) * (candidate.bottom - candidate.top));
        if (candidate.show_label) {
            score += 1000000.0;
        }
        if (candidate.surface_id == snapshot.surface_id) {
            score += 10000.0;
        } else if (GetOverlaySurfaceRootId(candidate.surface_id) ==
                   GetOverlaySurfaceRootId(snapshot.surface_id)) {
            score += 1000.0;
        }

        if (!has_match || score > best_score) {
            best_match = candidate;
            has_match = true;
            best_score = score;
        }
    }

    if (!has_match && !first_dispatch_rejection.empty() && snapshot.generation != 0) {
        bool should_log_rejection = false;
        {
            std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
            if (g_debug_ui_overlay_state.last_logged_action_query_rejection_generation != snapshot.generation ||
                g_debug_ui_overlay_state.last_logged_action_query_rejection_action_id != action_id) {
                g_debug_ui_overlay_state.last_logged_action_query_rejection_generation = snapshot.generation;
                g_debug_ui_overlay_state.last_logged_action_query_rejection_action_id = std::string(action_id);
                should_log_rejection = true;
            }
        }

        if (should_log_rejection) {
            Log(
                "Debug UI overlay hid semantic action until dispatch-ready. action=" + std::string(action_id) +
                " surface=" + std::string(surface_id) +
                " generation=" + std::to_string(snapshot.generation) +
                " reason=" + first_dispatch_rejection);
        }
    }

    if (has_match && out_element != nullptr) {
        *out_element = best_match;
    }
    return has_match;
}

std::uint64_t QueueSemanticUiActionRequestUnlocked(
    std::string_view action_id,
    std::string_view target_label,
    std::string_view surface_id) {
    auto& request = g_debug_ui_overlay_state.pending_semantic_ui_action;
    request.active = true;
    request.request_id = ++g_debug_ui_overlay_state.next_semantic_ui_action_request_id;
    request.queued_at = GetTickCount64();
    request.action_id = std::string(action_id);
    request.target_label = std::string(target_label);
    request.surface_id = std::string(surface_id);
    return request.request_id;
}

bool TryDispatchSemanticUiActionRequestImmediately(
    std::string_view action_id,
    std::string_view surface_id,
    uintptr_t owner_address,
    std::uint64_t* request_id,
    std::string* error_message) {
    if (owner_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Immediate semantic UI dispatch requires a live owner object.";
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

    const auto queued_at = GetTickCount64();
    std::uint64_t queued_request_id = 0;
    {
        std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
        if (g_debug_ui_overlay_state.pending_semantic_ui_action.active) {
            if (error_message != nullptr) {
                *error_message =
                    "UI action request " +
                    std::to_string(g_debug_ui_overlay_state.pending_semantic_ui_action.request_id) +
                    " is already queued for action " + g_debug_ui_overlay_state.pending_semantic_ui_action.action_id +
                    " on surface " + g_debug_ui_overlay_state.pending_semantic_ui_action.surface_id + ".";
            }
            return false;
        }

        if (g_debug_ui_overlay_state.active_semantic_ui_action_dispatch.active) {
            if (error_message != nullptr) {
                *error_message =
                    "UI action request " +
                    std::to_string(g_debug_ui_overlay_state.active_semantic_ui_action_dispatch.request_id) +
                    " is still dispatching action " +
                    g_debug_ui_overlay_state.active_semantic_ui_action_dispatch.action_id + " on surface " +
                    g_debug_ui_overlay_state.active_semantic_ui_action_dispatch.surface_id + ".";
            }
            return false;
        }

        queued_request_id = ++g_debug_ui_overlay_state.next_semantic_ui_action_request_id;
        auto& active = g_debug_ui_overlay_state.active_semantic_ui_action_dispatch;
        active.active = true;
        active.request_id = queued_request_id;
        active.queued_at = queued_at;
        active.started_at = queued_at;
        active.snapshot_generation = 0;
        active.action_id = std::string(action_id);
        active.target_label.clear();
        active.surface_id = std::string(surface_id);
        active.status = "dispatching";
    }

    DebugUiSnapshotElement snapshot_element;
    snapshot_element.action_id = std::string(action_id);
    snapshot_element.label = action_definition->label;
    snapshot_element.surface_id = std::string(surface_id);
    snapshot_element.surface_object_ptr = owner_address;

    std::string dispatch_error;
    const auto dispatched = ::sdmod::TryActivateDebugUiSnapshotElement(snapshot_element, &dispatch_error);
    {
        std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
        StoreCompletedSemanticUiActionDispatchUnlocked(
            &g_debug_ui_overlay_state,
            dispatched ? "dispatched" : "failed",
            dispatch_error);
    }

    if (request_id != nullptr) {
        *request_id = queued_request_id;
    }

    if (dispatched) {
        Log(
            "Debug UI overlay dispatched semantic UI action immediately. request=" +
            std::to_string(queued_request_id) + " target=" + std::string(action_id) +
            " surface=" + std::string(surface_id) +
            " owner=" + HexString(owner_address));
        return true;
    }

    if (error_message != nullptr) {
        *error_message = dispatch_error;
    }
    Log(
        "Debug UI overlay failed immediate semantic UI dispatch. request=" +
        std::to_string(queued_request_id) + " target=" + std::string(action_id) +
        " surface=" + std::string(surface_id) +
        " owner=" + HexString(owner_address) +
        " reason=" + dispatch_error);
    return false;
}

bool TryQueueSemanticUiActionRequest(
    std::string_view action_id,
    std::string_view surface_id,
    std::uint64_t* request_id,
    std::string* error_message) {
    if (action_id.empty()) {
        if (error_message != nullptr) {
            *error_message = "UI action activation requires a non-empty action id.";
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

    const auto effective_surface_id = surface_id.empty() ? action_definition->surface_id : std::string(surface_id);
    const auto surface_root_id = GetOverlaySurfaceRootId(effective_surface_id);

    UiActionDispatchExpectation expectation;
    if (!TryResolveUiActionDispatchExpectation(surface_root_id, action_id, &expectation)) {
        if (error_message != nullptr) {
            *error_message = "UI action '" + std::string(action_id) +
                             "' does not have a configured semantic dispatch path.";
        }
        return false;
    }

    if (expectation.dispatch_kind == "direct_write") {
        uintptr_t owner_address = 0;
        if (TryResolveLiveUiSurfaceOwner(surface_root_id, 0, &owner_address) && owner_address != 0) {
            return TryDispatchSemanticUiActionRequestImmediately(
                action_id,
                effective_surface_id,
                owner_address,
                request_id,
                error_message);
        }
    }

    std::uint64_t queued_request_id = 0;
    {
        std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
        if (g_debug_ui_overlay_state.pending_semantic_ui_action.active) {
            if (error_message != nullptr) {
                *error_message =
                    "UI action request " +
                    std::to_string(g_debug_ui_overlay_state.pending_semantic_ui_action.request_id) +
                    " is already queued for action " + g_debug_ui_overlay_state.pending_semantic_ui_action.action_id +
                    " on surface " + g_debug_ui_overlay_state.pending_semantic_ui_action.surface_id + ".";
            }
            return false;
        }

        if (g_debug_ui_overlay_state.active_semantic_ui_action_dispatch.active) {
            if (error_message != nullptr) {
                *error_message =
                    "UI action request " +
                    std::to_string(g_debug_ui_overlay_state.active_semantic_ui_action_dispatch.request_id) +
                    " is still dispatching action " +
                    g_debug_ui_overlay_state.active_semantic_ui_action_dispatch.action_id + " on surface " +
                    g_debug_ui_overlay_state.active_semantic_ui_action_dispatch.surface_id + ".";
            }
            return false;
        }

        queued_request_id = QueueSemanticUiActionRequestUnlocked(action_id, "", effective_surface_id);
    }

    if (request_id != nullptr) {
        *request_id = queued_request_id;
    }
    Log(
        "Debug UI overlay queued semantic UI action. request=" + std::to_string(queued_request_id) +
        " action=" + std::string(action_id) + " surface=" + effective_surface_id);
    return true;
}

bool TryQueueSemanticUiElementRequest(
    std::string_view label,
    std::string_view surface_id,
    std::uint64_t* request_id,
    std::string* error_message) {
    if (label.empty()) {
        if (error_message != nullptr) {
            *error_message = "UI element activation requires a non-empty label.";
        }
        return false;
    }

    const auto effective_surface_id = std::string(surface_id);
    std::uint64_t queued_request_id = 0;
    {
        std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
        if (g_debug_ui_overlay_state.pending_semantic_ui_action.active) {
            if (error_message != nullptr) {
                *error_message =
                    "UI action request " +
                    std::to_string(g_debug_ui_overlay_state.pending_semantic_ui_action.request_id) +
                    " is already queued for action " + g_debug_ui_overlay_state.pending_semantic_ui_action.action_id +
                    " on surface " + g_debug_ui_overlay_state.pending_semantic_ui_action.surface_id + ".";
            }
            return false;
        }

        if (g_debug_ui_overlay_state.active_semantic_ui_action_dispatch.active) {
            if (error_message != nullptr) {
                *error_message =
                    "UI action request " +
                    std::to_string(g_debug_ui_overlay_state.active_semantic_ui_action_dispatch.request_id) +
                    " is still dispatching action " +
                    g_debug_ui_overlay_state.active_semantic_ui_action_dispatch.action_id + " on surface " +
                    g_debug_ui_overlay_state.active_semantic_ui_action_dispatch.surface_id + ".";
            }
            return false;
        }

        queued_request_id = QueueSemanticUiActionRequestUnlocked("", label, effective_surface_id);
    }

    if (request_id != nullptr) {
        *request_id = queued_request_id;
    }

    Log(
        "Debug UI overlay queued semantic UI element activation. request=" + std::to_string(queued_request_id) +
        " label=" + std::string(label) + " surface=" + effective_surface_id);
    return true;
}

void DispatchPendingSemanticUiActionRequest() {
    PendingSemanticUiActionRequest request;
    DebugUiSurfaceSnapshot snapshot;
    {
        std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
        const auto pending_skips_snapshot_match = [&]() {
            if (!g_debug_ui_overlay_state.pending_semantic_ui_action.active) return false;
            const auto* def = FindUiActionDefinition(g_debug_ui_overlay_state.pending_semantic_ui_action.action_id);
            return def != nullptr &&
                   (def->dispatch_kind == "direct_write" || def->dispatch_kind == "owner_point_click");
        }();
        if (g_debug_ui_overlay_state.active_semantic_ui_action_dispatch.active ||
            !g_debug_ui_overlay_state.pending_semantic_ui_action.active ||
            (!pending_skips_snapshot_match &&
             !IsUsableDebugUiSurfaceSnapshot(g_debug_ui_overlay_state.latest_surface_snapshot))) {
            return;
        }

        request = g_debug_ui_overlay_state.pending_semantic_ui_action;
        snapshot = g_debug_ui_overlay_state.latest_surface_snapshot;
        g_debug_ui_overlay_state.pending_semantic_ui_action = PendingSemanticUiActionRequest{};
        g_debug_ui_overlay_state.active_semantic_ui_action_dispatch.active = true;
        g_debug_ui_overlay_state.active_semantic_ui_action_dispatch.request_id = request.request_id;
        g_debug_ui_overlay_state.active_semantic_ui_action_dispatch.queued_at = request.queued_at;
        g_debug_ui_overlay_state.active_semantic_ui_action_dispatch.started_at = GetTickCount64();
        g_debug_ui_overlay_state.active_semantic_ui_action_dispatch.snapshot_generation = snapshot.generation;
        g_debug_ui_overlay_state.active_semantic_ui_action_dispatch.action_id = request.action_id;
        g_debug_ui_overlay_state.active_semantic_ui_action_dispatch.target_label = request.target_label;
        g_debug_ui_overlay_state.active_semantic_ui_action_dispatch.surface_id = request.surface_id;
        g_debug_ui_overlay_state.active_semantic_ui_action_dispatch.status = "dispatching";
    }

    const auto surface_root_id = GetOverlaySurfaceRootId(request.surface_id);
    const auto dispatch_identity = !request.action_id.empty() ? request.action_id : request.target_label;
    if (!ShouldDispatchUiActionViaOverlayFrame(surface_root_id, request.action_id)) {
        const auto dispatch_timing = std::string(ResolveUiActionDispatchTiming(surface_root_id, request.action_id));
        const auto error_message =
            "UI action '" + dispatch_identity + "' uses unsupported dispatch timing '" + dispatch_timing + "'.";
        {
            std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
            StoreCompletedSemanticUiActionDispatchUnlocked(&g_debug_ui_overlay_state, "failed", error_message);
        }
        Log(
            "Debug UI overlay failed to dispatch semantic UI action on the render thread. request=" +
            std::to_string(request.request_id) + " target=" + dispatch_identity + " surface=" + request.surface_id +
            " reason=" + error_message);
        return;
    }

    DebugUiSnapshotElement resolved_snapshot_element;
    const DebugUiSnapshotElement* snapshot_element = nullptr;
    if (!request.action_id.empty()) {
        if (FindBestSnapshotActionElement(snapshot, request.action_id, request.surface_id, &resolved_snapshot_element)) {
            snapshot_element = &resolved_snapshot_element;
        }
    } else {
        snapshot_element = FindBestSnapshotLabelElement(snapshot, request.target_label, request.surface_id);
    }
    if (snapshot_element == nullptr && !request.action_id.empty()) {
        const auto* action_definition = FindUiActionDefinition(request.action_id);
        if (action_definition != nullptr &&
            (action_definition->dispatch_kind == "direct_write" ||
             action_definition->dispatch_kind == "owner_point_click")) {
            resolved_snapshot_element = DebugUiSnapshotElement{};
            resolved_snapshot_element.action_id = request.action_id;
            resolved_snapshot_element.surface_id = request.surface_id;
            resolved_snapshot_element.label = action_definition->label;
            snapshot_element = &resolved_snapshot_element;
        }
    }

    if (snapshot_element == nullptr) {
        const auto error_message =
            "No live snapshot element matched target '" + dispatch_identity + "' on surface '" + request.surface_id +
            "' at dispatch time.";
        {
            std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
            StoreCompletedSemanticUiActionDispatchUnlocked(&g_debug_ui_overlay_state, "failed", error_message);
        }
        Log(
            "Debug UI overlay failed to dispatch semantic UI action on the render thread. request=" +
            std::to_string(request.request_id) + " target=" + dispatch_identity + " surface=" + request.surface_id +
            " reason=" + error_message);
        return;
    }

    std::string dispatch_error;
    const auto dispatched = ::sdmod::TryActivateDebugUiSnapshotElement(*snapshot_element, &dispatch_error);

    {
        std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
        StoreCompletedSemanticUiActionDispatchUnlocked(
            &g_debug_ui_overlay_state,
            dispatched ? "dispatched" : "failed",
            dispatch_error);
    }

    if (dispatched) {
        Log(
            "Debug UI overlay dispatched semantic UI action on the render thread. request=" +
            std::to_string(request.request_id) + " target=" + dispatch_identity +
            " surface=" + request.surface_id);
        return;
    }

    Log(
        "Debug UI overlay failed to dispatch semantic UI action on the render thread. request=" +
        std::to_string(request.request_id) + " target=" + dispatch_identity +
        " surface=" + request.surface_id + " reason=" + dispatch_error);
}

void ResetDebugUiOverlayStateUnlocked(DebugUiOverlayState* state) {
    if (state == nullptr) {
        return;
    }

    ReleaseFontAtlas(&state->font_atlas);
    state->initialized = false;
    state->first_frame_logged = false;
    state->first_d3d_frame_logged = false;
    state->first_font_atlas_ready_logged = false;
    state->first_font_atlas_failure_logged = false;
    state->first_candidate_logged = false;
    state->first_text_draw_call_logged = false;
    state->first_exact_text_render_call_logged = false;
    state->first_glyph_draw_call_logged = false;
    state->first_string_assign_call_logged = false;
    state->first_dialog_add_line_logged = false;
    state->first_dialog_button_logged = false;
    state->first_dialog_finalize_logged = false;
    state->first_tracked_dialog_frame_logged = false;
    state->first_dark_cloud_browser_render_logged = false;
    state->first_settings_render_logged = false;
    state->first_myquick_panel_render_logged = false;
    state->first_myquick_panel_modal_logged = false;
    state->first_exact_control_render_logged = false;
    state->first_simple_menu_modal_logged = false;
    state->first_main_menu_render_logged = false;
    state->first_hall_of_fame_render_logged = false;
    state->first_spell_picker_render_logged = false;
    // Surface registry first-frame flags are reset by RenderOverlayFrame's
    // registry definition.  The flags live in a static array in
    // label_resolution_and_frame_render.inl which is included after this file,
    // so the reset is called from the overlay shutdown/init path via a
    // forward-declared helper.  We call through a function pointer that is
    // set once the registry translation unit has been parsed.
    if (g_reset_surface_registry_first_frame_flags != nullptr) {
        g_reset_surface_registry_first_frame_flags();
    }
    state->first_viewport_calibrated_dialog_logged = false;
    state->first_cached_dialog_geometry_logged = false;
    state->first_stack_match_logged = false;
    state->previous_left_button_down = false;
    state->config = DebugUiOverlayConfig{};
    state->text_draw_hook = X86Hook{};
    state->string_assign_hook = X86Hook{};
    state->dialog_add_line_hook = X86Hook{};
    state->dialog_primary_button_hook = X86Hook{};
    state->dialog_secondary_button_hook = X86Hook{};
    state->dialog_finalize_hook = X86Hook{};
    state->exact_text_render_hook = X86Hook{};
    state->glyph_draw_hook = X86Hook{};
    state->text_quad_draw_hook = X86Hook{};
    state->dark_cloud_browser_exact_text_render_hook = X86Hook{};
    state->dark_cloud_browser_render_hook = X86Hook{};
    state->settings_render_hook = X86Hook{};
    state->myquick_panel_render_hook = X86Hook{};
    state->myquick_panel_modal_loop_hook = X86Hook{};
    state->simple_menu_modal_loop_hook = X86Hook{};
    state->main_menu_render_hook = X86Hook{};
    state->hall_of_fame_render_hook = X86Hook{};
    state->spell_picker_render_hook = X86Hook{};
    state->ui_labeled_control_render_hook = X86Hook{};
    state->ui_labeled_control_alt_render_hook = X86Hook{};
    state->ui_unlabeled_control_render_hook = X86Hook{};
    state->ui_panel_render_hook = X86Hook{};
    state->ui_rect_dispatch_hook = X86Hook{};
    state->surface_ranges.clear();
    state->frame_elements.clear();
    state->frame_exact_text_elements.clear();
    state->frame_exact_control_elements.clear();
    state->active_exact_text_renders.clear();
    state->recent_assigned_strings.clear();
    state->recent_assigned_strings_updated_at = 0;
    state->tracked_title_main_menu_object = 0;
    state->last_create_owner_object = 0;
    state->dark_cloud_browser_render = TrackedSurfaceRenderState{};
    state->settings_render = TrackedSurfaceRenderState{};
    state->myquick_panel_render = TrackedSurfaceRenderState{};
    state->hall_of_fame_render = TrackedSurfaceRenderState{};
    state->spell_picker_render = TrackedSurfaceRenderState{};
    state->myquick_panel_modal = TrackedSimpleMenuState{};
    state->simple_menu = TrackedSimpleMenuState{};
    state->dark_cloud_browser_panel = TrackedWidgetRectState{};
    state->dark_cloud_browser_modal_root = TrackedWidgetRectState{};
    state->tracked_dialog = TrackedDialogState{};
    state->pending_semantic_ui_action = PendingSemanticUiActionRequest{};
    state->active_semantic_ui_action_dispatch = ActiveSemanticUiActionDispatch{};
    state->last_semantic_ui_action_dispatch = CompletedSemanticUiActionDispatch{};
    state->object_label_cache.clear();
    state->latest_surface_snapshot_generation = 0;
    state->last_logged_overlay_draw_generation = 0;
    state->last_logged_overlay_clear_generation = 0;
    state->last_logged_action_query_rejection_generation = 0;
    state->last_logged_action_query_rejection_action_id.clear();
    state->next_semantic_ui_action_request_id = 0;
    state->latest_surface_snapshot = DebugUiSurfaceSnapshot{};
}

bool IsPrintableUiCharacter(unsigned char value) {
    return value >= 32 && value <= 126;
}

bool IsPlausibleUiLabel(std::string_view label) {
    if (label.empty() || label.size() > 96) {
        return false;
    }

    std::size_t printable_count = 0;
    for (unsigned char ch : label) {
        if (IsPrintableUiCharacter(ch)) {
            ++printable_count;
            continue;
        }

        if (ch == '\t' || ch == '\r' || ch == '\n') {
            return false;
        }
    }

    return printable_count == label.size();
}
