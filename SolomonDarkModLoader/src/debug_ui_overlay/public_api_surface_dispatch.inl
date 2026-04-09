void ShutdownDebugUiOverlay() {
    RemoveD3d9FrameHook();
    RemoveX86Hook(&g_debug_ui_overlay_state.ui_rect_dispatch_hook);
    RemoveX86Hook(&g_debug_ui_overlay_state.ui_panel_render_hook);
    RemoveX86Hook(&g_debug_ui_overlay_state.ui_unlabeled_control_render_hook);
    RemoveX86Hook(&g_debug_ui_overlay_state.ui_labeled_control_alt_render_hook);
    RemoveX86Hook(&g_debug_ui_overlay_state.ui_labeled_control_render_hook);
    RemoveX86Hook(&g_debug_ui_overlay_state.simple_menu_modal_loop_hook);
    RemoveX86Hook(&g_debug_ui_overlay_state.myquick_panel_modal_loop_hook);
    RemoveX86Hook(&g_debug_ui_overlay_state.myquick_panel_render_hook);
    RemoveX86Hook(&g_debug_ui_overlay_state.settings_render_hook);
    RemoveX86Hook(&g_debug_ui_overlay_state.spell_picker_render_hook);
    RemoveX86Hook(&g_debug_ui_overlay_state.main_menu_render_hook);
    RemoveX86Hook(&g_debug_ui_overlay_state.hall_of_fame_render_hook);
    RemoveX86Hook(&g_debug_ui_overlay_state.dark_cloud_browser_render_hook);
    RemoveX86Hook(&g_debug_ui_overlay_state.text_quad_draw_hook);
    RemoveX86Hook(&g_debug_ui_overlay_state.glyph_draw_hook);
    RemoveX86Hook(&g_debug_ui_overlay_state.dark_cloud_browser_exact_text_render_hook);
    RemoveX86Hook(&g_debug_ui_overlay_state.exact_text_render_hook);
    RemoveX86Hook(&g_debug_ui_overlay_state.dialog_finalize_hook);
    RemoveX86Hook(&g_debug_ui_overlay_state.dialog_secondary_button_hook);
    RemoveX86Hook(&g_debug_ui_overlay_state.dialog_primary_button_hook);
    RemoveX86Hook(&g_debug_ui_overlay_state.dialog_add_line_hook);
    RemoveX86Hook(&g_debug_ui_overlay_state.string_assign_hook);
    RemoveX86Hook(&g_debug_ui_overlay_state.text_draw_hook);
    bool was_initialized = false;
    {
        std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
        was_initialized = g_debug_ui_overlay_state.initialized;
        ResetDebugUiOverlayStateUnlocked(&g_debug_ui_overlay_state);
    }

    if (was_initialized) {
        Log("Debug UI overlay shut down.");
    }
}

bool IsDebugUiOverlayInitialized() {
    std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
    return g_debug_ui_overlay_state.initialized;
}

bool TryGetLatestDebugUiSurfaceSnapshot(DebugUiSurfaceSnapshot* snapshot) {
    if (snapshot == nullptr) {
        return false;
    }

    std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
    if (!g_debug_ui_overlay_state.initialized ||
        !IsUsableDebugUiSurfaceSnapshot(g_debug_ui_overlay_state.latest_surface_snapshot)) {
        return false;
    }

    *snapshot = g_debug_ui_overlay_state.latest_surface_snapshot;
    return true;
}

bool TryFindDebugUiActionElement(
    std::string_view action_id,
    std::string_view surface_id,
    DebugUiSnapshotElement* element) {
    if (element == nullptr) {
        return false;
    }

    DebugUiSurfaceSnapshot snapshot;
    if (!TryGetLatestDebugUiSurfaceSnapshot(&snapshot)) {
        return false;
    }

    return FindBestSnapshotActionElement(snapshot, action_id, surface_id, element);
}

bool TryResolveSettingsSnapshotElementDispatch(
    const DebugUiSnapshotElement& element,
    uintptr_t* owner_address,
    uintptr_t* control_address,
    std::string* error_message) {
    if (owner_address == nullptr || control_address == nullptr) {
        return false;
    }

    *owner_address = 0;
    *control_address = 0;

    const auto* config = TryGetDebugUiOverlayConfig();
    if (config == nullptr) {
        if (error_message != nullptr) {
            *error_message = "The debug UI overlay config is unavailable for settings element activation.";
        }
        return false;
    }

    uintptr_t settings_address = 0;
    if (!TryResolveLiveUiSurfaceOwner("settings", element.surface_object_ptr, &settings_address) || settings_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the active settings surface owner.";
        }
        return false;
    }

    std::vector<uintptr_t> root_controls;
    if (!TryReadSettingsControlPointers(*config, settings_address, &root_controls) || root_controls.empty()) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the live settings control tree.";
        }
        return false;
    }

    const auto normalized_element_label = NormalizeSemanticUiToken(element.label);

    const auto matches_element_label = [&](uintptr_t candidate_control) {
        if (candidate_control == 0 || normalized_element_label.empty()) {
            return false;
        }

        std::string candidate_label = ResolveSettingsControlLabel(*config, candidate_control);
        if (candidate_label.empty()) {
            (void)TryReadCachedObjectLabel(candidate_control, &candidate_label);
        }

        return !candidate_label.empty() &&
               NormalizeSemanticUiToken(candidate_label) == normalized_element_label;
    };

    for (const auto root_control : root_controls) {
        if (root_control == 0) {
            continue;
        }

        std::vector<uintptr_t> child_controls;
        (void)TryReadSettingsControlChildPointers(*config, root_control, &child_controls);

        if (matches_element_label(root_control) &&
            IsSettingsRolloutControl(*config, root_control) &&
            (element.source_object_ptr == 0 ||
             element.source_object_ptr == root_control ||
             IsWidgetOwnedByRoot(*config, root_control, element.source_object_ptr))) {
            *owner_address = root_control;
            Log(
                "Debug UI overlay resolved settings rollout element from its labeled root control. label=" +
                SanitizeDebugLogLabel(element.label) +
                " source=" + HexString(element.source_object_ptr) +
                " owner=" + HexString(*owner_address));
            return TryResolveSettingsDispatchControlAddress(
                *config,
                *owner_address,
                root_control,
                element.action_id,
                control_address,
                error_message);
        }

        for (const auto child_control : child_controls) {
            if (child_control == 0) {
                continue;
            }

            if (element.source_object_ptr == child_control ||
                IsWidgetOwnedByRoot(*config, child_control, element.source_object_ptr)) {
                *owner_address = root_control;
                return TryResolveSettingsDispatchControlAddress(
                    *config,
                    *owner_address,
                    child_control,
                    element.action_id,
                    control_address,
                    error_message);
            }

            if (matches_element_label(child_control)) {
                *owner_address = root_control;
                return TryResolveSettingsDispatchControlAddress(
                    *config,
                    *owner_address,
                    child_control,
                    element.action_id,
                    control_address,
                    error_message);
            }
        }

        if (element.source_object_ptr == root_control ||
            IsWidgetOwnedByRoot(*config, root_control, element.source_object_ptr)) {
            if (IsSettingsRolloutControl(*config, root_control)) {
                *owner_address = root_control;
                return TryResolveSettingsDispatchControlAddress(
                    *config,
                    *owner_address,
                    root_control,
                    element.action_id,
                    control_address,
                    error_message);
            }

            if (child_controls.size() == 1 && child_controls.front() != 0) {
                *owner_address = root_control;
                return TryResolveSettingsDispatchControlAddress(
                    *config,
                    *owner_address,
                    child_controls.front(),
                    element.action_id,
                    control_address,
                    error_message);
            }

            if (matches_element_label(root_control) &&
                CountSettingsChildControlsWithResolvedLabels(*config, child_controls) == 0 &&
                !child_controls.empty() &&
                child_controls.front() != 0) {
                *owner_address = root_control;
                if (!TryResolveSettingsDispatchControlAddress(
                        *config,
                        *owner_address,
                        child_controls.front(),
                        element.action_id,
                        control_address,
                        error_message)) {
                    return false;
                }
                Log(
                    "Debug UI overlay resolved settings element through the first unlabeled child of its labeled root control. label=" +
                    SanitizeDebugLogLabel(element.label) +
                    " source=" + HexString(element.source_object_ptr) +
                    " owner=" + HexString(*owner_address) +
                    " control=" + HexString(*control_address));
                return true;
            }

            if (error_message != nullptr) {
                *error_message =
                    "Settings element '" + element.label +
                    "' resolved to a container control instead of a uniquely actionable child.";
            }
            return false;
        }
    }

    uintptr_t label_matched_owner_address = 0;
    uintptr_t label_matched_child_control_address = 0;
    std::size_t label_match_count = 0;
    bool label_match_was_container_only = false;
    if (TryResolveSettingsActionableLabelControl(
            *config,
            settings_address,
            element.source_object_ptr,
            element.label,
            &label_matched_owner_address,
            &label_matched_child_control_address,
            &label_match_count,
            &label_match_was_container_only) &&
        label_matched_owner_address != 0 &&
        label_matched_child_control_address != 0) {
        *owner_address = label_matched_owner_address;
        if (!TryResolveSettingsDispatchControlAddress(
                *config,
                *owner_address,
                label_matched_child_control_address,
                element.action_id,
                control_address,
                error_message)) {
            return false;
        }
        Log(
            "Debug UI overlay resolved settings element by live label fallback. label=" +
            SanitizeDebugLogLabel(element.label) +
            " source=" + HexString(element.source_object_ptr) +
            " settings=" + HexString(settings_address) +
            " owner=" + HexString(*owner_address) +
            " control=" + HexString(*control_address));
        return true;
    }

    if (label_match_count > 1) {
        if (error_message != nullptr) {
            *error_message =
                "Settings element '" + element.label +
                "' matched multiple live settings controls by label.";
        }
        return false;
    }

    if (label_match_was_container_only) {
        if (error_message != nullptr) {
            *error_message =
                "Settings element '" + element.label +
                "' matched a non-actionable settings container without a unique child.";
        }
        return false;
    }

    // Fallback: use the control_offset from binary-layout.ini to resolve the control
    // directly from the settings object address. This handles settings actions (LOGIN INFO,
    // TWEAK GAME, etc.) whose text source objects are not in the settings child control tree.
    if (!element.action_id.empty()) {
        const auto* action_definition = FindUiActionDefinition(element.action_id);
        if (action_definition != nullptr) {
            const auto control_offset = GetDefinitionAddress(action_definition->addresses, "control_offset");
            if (control_offset != 0 && settings_address != 0) {
                const auto fallback_control = settings_address + control_offset;
                uintptr_t vftable_check = 0;
                if (TryReadPointerValueDirect(fallback_control, &vftable_check) && vftable_check != 0) {
                    *owner_address = settings_address;
                    *control_address = fallback_control;
                    Log(
                        "Debug UI overlay resolved settings element via control_offset fallback. label=" +
                        SanitizeDebugLogLabel(element.label) +
                        " action=" + std::string(element.action_id) +
                        " settings=" + HexString(settings_address) +
                        " control_offset=" + HexString(control_offset) +
                        " control=" + HexString(fallback_control));
                    return true;
                }
            }
        }
    }

    if (error_message != nullptr) {
        *error_message =
            "Settings element '" + element.label + "' did not resolve to a live actionable control. source=" +
            HexString(element.source_object_ptr);
    }
    return false;
}

