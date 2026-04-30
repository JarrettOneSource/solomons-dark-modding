std::string SanitizeDebugLogLabel(std::string value) {
    for (auto& ch : value) {
        if (ch == '\r' || ch == '\n' || ch == '\t') {
            ch = ' ';
        }
    }
    return value;
}

void BeginExactTextRenderCapture(
    void* self,
    void* string_object,
    uintptr_t caller_address,
    uintptr_t widget_object,
    float origin_x,
    float origin_y,
    char* text) {
    ExactTextRenderCapture capture;
    capture.caller_address = caller_address;
    capture.label = ResolveExactTextRenderLabel(string_object, text);
    if (IsPlausibleTitleCoordinate(origin_x) && IsPlausibleTitleCoordinate(origin_y)) {
        capture.has_expected_origin = true;
        capture.expected_origin_x = origin_x;
        capture.expected_origin_y = origin_y;
        capture.min_x = origin_x;
        capture.max_x = origin_x;
        capture.min_y = origin_y;
        capture.max_y = origin_y;
    }

    const auto surface_match = TryResolveSurfaceForDrawCall(caller_address, g_debug_ui_overlay_state.config.stack_scan_slots);
    const auto recognized_title_line = IsRecognizedTitleMainMenuLine(capture.label);
    uintptr_t main_menu_address = 0;
    const auto stack_explicitly_rejected =
        surface_match.has_value() && surface_match->range != nullptr && surface_match->range->surface_id != "main_menu";
    if (!stack_explicitly_rejected && recognized_title_line &&
        TryReadActiveTitleMainMenu(g_debug_ui_overlay_state.config, nullptr, &main_menu_address)) {
        capture.capture_enabled = true;
        capture.surface_id = "main_menu";
        capture.surface_title = "Main Menu";
        if (surface_match.has_value() && surface_match->range != nullptr) {
            capture.surface_return_address = surface_match->return_address;
            capture.stack_slot = surface_match->stack_slot;
        }
        capture.source_object_ptr = main_menu_address;
    }

    if (!capture.capture_enabled) {
        uintptr_t settings_address = 0;
        uintptr_t owned_settings_object = 0;
        const auto normalized_caller_address = NormalizeObservedCodeAddress(caller_address);
        const auto* config = TryGetDebugUiOverlayConfig();
        if (config != nullptr &&
            TryGetActiveSettingsRender(&settings_address) &&
            settings_address != 0 &&
            !capture.label.empty() &&
            IsTrustedSettingsTextCaller(g_debug_ui_overlay_state.config, normalized_caller_address)) {
            const uintptr_t candidate_objects[] = {
                widget_object,
                reinterpret_cast<uintptr_t>(self),
                reinterpret_cast<uintptr_t>(string_object),
            };
            for (const auto candidate_object : candidate_objects) {
                if (candidate_object == 0) {
                    continue;
                }

                if (TryResolveSettingsOwnedObject(
                        *config,
                        settings_address,
                        candidate_object,
                        &owned_settings_object) &&
                    owned_settings_object != 0) {
                    break;
                }
            }

            capture.capture_enabled = true;
            capture.surface_id = "settings";
            capture.surface_title = "Game Settings";
            capture.source_object_ptr =
                owned_settings_object != 0
                    ? owned_settings_object
                    : (widget_object != 0 ? widget_object : settings_address);
            if (surface_match.has_value() && surface_match->range != nullptr) {
                capture.surface_return_address = surface_match->return_address;
                capture.stack_slot = surface_match->stack_slot;
            }
            static int s_settings_exact_text_owner_logs_remaining = 18;
            if (s_settings_exact_text_owner_logs_remaining > 0 &&
                (capture.label == "DONE" || capture.label == "Sound and Music" || capture.label == "Video Settings" ||
                 capture.label == "Dark Cloud Settings" || capture.label == "CONTROLS" ||
                 capture.label == "Performance" || capture.label == "LOGIN INFO" ||
                 capture.label == "CUSTOMIZE KEYBOARD" || capture.label == "TWEAK GAME")) {
                --s_settings_exact_text_owner_logs_remaining;
                Log(
                    "Debug UI settings exact text owner probe: label=" + SanitizeDebugLogLabel(capture.label) +
                    " caller=" + HexString(caller_address) + " self=" + HexString(reinterpret_cast<uintptr_t>(self)) +
                    " string=" + HexString(reinterpret_cast<uintptr_t>(string_object)) + " widget=" +
                    HexString(widget_object) + " owned=" + HexString(owned_settings_object) +
                    " settings=" + HexString(settings_address));
            }
        }
    }

    if (!capture.capture_enabled) {
        uintptr_t quick_panel_address = 0;
        const auto* config = TryGetDebugUiOverlayConfig();
        uintptr_t owned_object_address = 0;
        if (config != nullptr && TryReadTrackedMyQuickPanel(&quick_panel_address) && quick_panel_address != 0 &&
            !capture.label.empty() &&
            TryResolveQuickPanelOwnedObject(
                *config,
                quick_panel_address,
                widget_object,
                reinterpret_cast<uintptr_t>(self),
                &owned_object_address)) {
            capture.capture_enabled = true;
            capture.surface_id = "quick_panel";
            capture.surface_title = "Quick Panel";
            capture.source_object_ptr = owned_object_address;
            if (surface_match.has_value() && surface_match->range != nullptr) {
                capture.surface_return_address = surface_match->return_address;
                capture.stack_slot = surface_match->stack_slot;
            }

            static int s_quick_panel_exact_text_owner_logs_remaining = 24;
            if (s_quick_panel_exact_text_owner_logs_remaining > 0) {
                --s_quick_panel_exact_text_owner_logs_remaining;
                Log(
                    "Debug UI MyQuickCPanel exact text owner probe: label=" +
                    SanitizeDebugLogLabel(capture.label) + " caller=" + HexString(caller_address) +
                    " self=" + HexString(reinterpret_cast<uintptr_t>(self)) + " string=" +
                    HexString(reinterpret_cast<uintptr_t>(string_object)) + " widget=" +
                    HexString(widget_object) + " owned=" + HexString(owned_object_address) +
                    " panel=" + HexString(quick_panel_address));
            }
        }
    }

    if (!capture.capture_enabled) {
        uintptr_t simple_menu_address = 0;
        uintptr_t simple_menu_owned_object = 0;
        uintptr_t simple_menu_menu_text_object = 0;
        const auto* config = TryGetDebugUiOverlayConfig();
        if (config != nullptr &&
            TryGetActiveSimpleMenu(&simple_menu_address) &&
            simple_menu_address != 0 &&
            !capture.label.empty()) {
            const uintptr_t candidate_objects[] = {
                widget_object,
                reinterpret_cast<uintptr_t>(self),
                reinterpret_cast<uintptr_t>(string_object),
            };
            for (const auto candidate_object : candidate_objects) {
                if (candidate_object == 0) {
                    continue;
                }

                if (TryResolveSimpleMenuOwnedObject(
                        *config,
                        simple_menu_address,
                        candidate_object,
                        &simple_menu_owned_object) &&
                    simple_menu_owned_object != 0) {
                    break;
                }

                if (simple_menu_menu_text_object == 0 &&
                    IsWidgetOwnedByRoot(*config, simple_menu_address, candidate_object)) {
                    simple_menu_menu_text_object = candidate_object;
                }
            }
        }

        if (simple_menu_owned_object != 0 || simple_menu_menu_text_object != 0) {
            capture.capture_enabled = true;
            capture.surface_id = "simple_menu";
            capture.surface_title = "Simple Menu";
            capture.source_object_ptr =
                simple_menu_owned_object != 0 ? simple_menu_owned_object : simple_menu_menu_text_object;
            if (surface_match.has_value() && surface_match->range != nullptr) {
                capture.surface_return_address = surface_match->return_address;
                capture.stack_slot = surface_match->stack_slot;
            }

            static int s_simple_menu_exact_text_owner_logs_remaining = 24;
            if (s_simple_menu_exact_text_owner_logs_remaining > 0) {
                --s_simple_menu_exact_text_owner_logs_remaining;
                Log(
                    "Debug UI SimpleMenu exact text owner probe: label=" +
                    SanitizeDebugLogLabel(capture.label) + " caller=" + HexString(caller_address) +
                    " self=" + HexString(reinterpret_cast<uintptr_t>(self)) + " string=" +
                    HexString(reinterpret_cast<uintptr_t>(string_object)) + " widget=" +
                    HexString(widget_object) + " owned=" + HexString(simple_menu_owned_object) +
                    " menuText=" + HexString(simple_menu_menu_text_object) +
                    " menu=" + HexString(simple_menu_address));
            }
        }
    }

    // Simple render-based surface detection: surfaces that only need an active
    // render check and use the widget/string object as the source pointer.
    struct SimpleRenderSurface {
        const char* surface_id;
        const char* surface_title;
        bool (*try_get_active)(uintptr_t*);
    };
    static const SimpleRenderSurface kSimpleRenderSurfaces[] = {
        {"dark_cloud_browser", "Dark Cloud Browser", &TryGetActiveDarkCloudBrowserRender},
        {"hall_of_fame",       "Hall of Fame",       &TryGetActiveHallOfFameRender},
        {"spell_picker",       "Spell Picker",       &TryGetActiveSpellPickerRender},
    };
    for (const auto& surface : kSimpleRenderSurfaces) {
        if (capture.capture_enabled) {
            break;
        }
        uintptr_t surface_address = 0;
        const auto source_object =
            widget_object != 0 ? widget_object : reinterpret_cast<uintptr_t>(string_object);
        if (source_object != 0 &&
            surface.try_get_active(&surface_address) &&
            surface_address != 0 &&
            !capture.label.empty()) {
            capture.capture_enabled = true;
            capture.surface_id = surface.surface_id;
            capture.surface_title = surface.surface_title;
            capture.source_object_ptr = source_object;
            if (surface_match.has_value() && surface_match->range != nullptr) {
                capture.surface_return_address = surface_match->return_address;
                capture.stack_slot = surface_match->stack_slot;
            }
        }
    }

    if (!capture.capture_enabled) {
        const auto tracked_dialog_object = GetTrackedDialogObject();
        uintptr_t dialog_owned_object = 0;
        const auto* config = TryGetDebugUiOverlayConfig();
        if (config != nullptr && tracked_dialog_object != 0 && !capture.label.empty()) {
            const uintptr_t candidate_objects[] = {
                widget_object,
                reinterpret_cast<uintptr_t>(self),
                reinterpret_cast<uintptr_t>(string_object),
            };
            for (const auto candidate_object : candidate_objects) {
                if (candidate_object == 0) {
                    continue;
                }

                if (candidate_object == tracked_dialog_object ||
                    IsWidgetOwnedByRoot(*config, tracked_dialog_object, candidate_object)) {
                    dialog_owned_object = candidate_object;
                    break;
                }
            }
        }

        if (dialog_owned_object != 0) {
            capture.capture_enabled = true;
            capture.surface_id = "dialog";
            capture.surface_title = "Dialog";
            capture.source_object_ptr = dialog_owned_object;
            if (surface_match.has_value() && surface_match->range != nullptr) {
                capture.surface_return_address = surface_match->return_address;
                capture.stack_slot = surface_match->stack_slot;
            }
        }
    }

    std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
    if (!g_debug_ui_overlay_state.first_exact_text_render_call_logged) {
        g_debug_ui_overlay_state.first_exact_text_render_call_logged = true;
        Log(
            "Debug UI overlay intercepted its first exact text render call. caller=" + HexString(caller_address) +
            " label=" + capture.label);
    }
    g_debug_ui_overlay_state.active_exact_text_renders.push_back(std::move(capture));
}
