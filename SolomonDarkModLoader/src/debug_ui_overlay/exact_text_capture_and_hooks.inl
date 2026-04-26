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

bool IsExactTextSampleNearExpectedOrigin(
    const ExactTextRenderCapture& capture,
    float left,
    float top,
    float right,
    float bottom) {
    if (!capture.has_expected_origin) {
        return true;
    }

    constexpr float kMaxLeadingXSlack = 64.0f;
    constexpr float kMaxLeadingYSlack = 48.0f;
    constexpr float kMaxTrailingXSlack = 2048.0f;
    constexpr float kMaxTrailingYSlack = 256.0f;

    if (left < capture.expected_origin_x - kMaxLeadingXSlack ||
        top < capture.expected_origin_y - kMaxLeadingYSlack) {
        return false;
    }

    if (right > capture.expected_origin_x + kMaxTrailingXSlack ||
        bottom > capture.expected_origin_y + kMaxTrailingYSlack) {
        return false;
    }

    return true;
}

void ObserveActiveExactTextGlyph(float glyph_offset_x, float glyph_offset_y) {
    uintptr_t render_context_address = 0;
    if (!TryReadUiRenderContext(g_debug_ui_overlay_state.config, &render_context_address) || render_context_address == 0) {
        return;
    }

    float base_x = 0.0f;
    float base_y = 0.0f;
    const auto* render_context = reinterpret_cast<const void*>(render_context_address);
    if (!TryReadPlainField(
            render_context,
            g_debug_ui_overlay_state.config.ui_render_context_base_x_offset,
            &base_x) ||
        !TryReadPlainField(
            render_context,
            g_debug_ui_overlay_state.config.ui_render_context_base_y_offset,
            &base_y)) {
        return;
    }

    const auto glyph_x = base_x + glyph_offset_x;
    const auto glyph_y = base_y + glyph_offset_y;
    if (!IsPlausibleTitleCoordinate(glyph_x) || !IsPlausibleTitleCoordinate(glyph_y)) {
        return;
    }

    std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
    if (!g_debug_ui_overlay_state.first_glyph_draw_call_logged) {
        g_debug_ui_overlay_state.first_glyph_draw_call_logged = true;
        Log(
            "Debug UI overlay intercepted its first glyph draw call. x=" + std::to_string(glyph_x) +
            " y=" + std::to_string(glyph_y));
    }

    if (g_debug_ui_overlay_state.active_exact_text_renders.empty()) {
        return;
    }

    auto& capture = g_debug_ui_overlay_state.active_exact_text_renders.back();
    if (!capture.capture_enabled) {
        return;
    }

    if (!IsExactTextSampleNearExpectedOrigin(capture, glyph_x, glyph_y, glyph_x, glyph_y)) {
        return;
    }

    capture.min_x = (std::min)(capture.min_x, glyph_x);
    capture.min_y = (std::min)(capture.min_y, glyph_y);
    capture.max_x = (std::max)(capture.max_x, glyph_x);
    capture.max_y = (std::max)(capture.max_y, glyph_y);
    ++capture.glyph_count;
}

bool TryBuildGlyphQuadBounds(
    const float* candidate,
    float* left,
    float* top,
    float* right,
    float* bottom) {
    if (candidate == nullptr || left == nullptr || top == nullptr || right == nullptr || bottom == nullptr) {
        return false;
    }

    float min_x = (std::numeric_limits<float>::max)();
    float min_y = (std::numeric_limits<float>::max)();
    float max_x = (std::numeric_limits<float>::lowest)();
    float max_y = (std::numeric_limits<float>::lowest)();
    for (int index = 0; index < 8; index += 2) {
        const auto x = candidate[index];
        const auto y = candidate[index + 1];
        min_x = (std::min)(min_x, x);
        min_y = (std::min)(min_y, y);
        max_x = (std::max)(max_x, x);
        max_y = (std::max)(max_y, y);
    }

    if (!IsPlausibleTitleCoordinate(min_x) || !IsPlausibleTitleCoordinate(min_y) ||
        !IsPlausibleTitleCoordinate(max_x) || !IsPlausibleTitleCoordinate(max_y)) {
        return false;
    }

    if (max_x - min_x < 2.0f || max_y - min_y < 2.0f) {
        return false;
    }

    *left = min_x;
    *top = min_y;
    *right = max_x;
    *bottom = max_y;
    return true;
}

void ObserveActiveExactTextQuad(const float* arg2, const float* arg3) {
    float left = 0.0f;
    float top = 0.0f;
    float right = 0.0f;
    float bottom = 0.0f;

    float alternate_left = 0.0f;
    float alternate_top = 0.0f;
    float alternate_right = 0.0f;
    float alternate_bottom = 0.0f;

    const auto primary_valid = TryBuildGlyphQuadBounds(arg2, &left, &top, &right, &bottom);
    const auto alternate_valid =
        TryBuildGlyphQuadBounds(arg3, &alternate_left, &alternate_top, &alternate_right, &alternate_bottom);

    if (!primary_valid && !alternate_valid) {
        return;
    }

    if (alternate_valid) {
        const auto primary_area = primary_valid ? (right - left) * (bottom - top) : -1.0f;
        const auto alternate_area =
            (alternate_right - alternate_left) * (alternate_bottom - alternate_top);
        if (!primary_valid || alternate_area > primary_area) {
            left = alternate_left;
            top = alternate_top;
            right = alternate_right;
            bottom = alternate_bottom;
        }
    }

    std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
    if (!g_debug_ui_overlay_state.first_glyph_draw_call_logged) {
        g_debug_ui_overlay_state.first_glyph_draw_call_logged = true;
        Log(
            "Debug UI overlay intercepted its first glyph draw call. left=" + std::to_string(left) +
            " top=" + std::to_string(top) + " right=" + std::to_string(right) +
            " bottom=" + std::to_string(bottom));
    }

    if (g_debug_ui_overlay_state.active_exact_text_renders.empty()) {
        return;
    }

    auto& capture = g_debug_ui_overlay_state.active_exact_text_renders.back();
    if (!capture.capture_enabled) {
        return;
    }

    if (!IsExactTextSampleNearExpectedOrigin(capture, left, top, right, bottom)) {
        return;
    }

    capture.min_x = (std::min)(capture.min_x, left);
    capture.min_y = (std::min)(capture.min_y, top);
    capture.max_x = (std::max)(capture.max_x, right);
    capture.max_y = (std::max)(capture.max_y, bottom);
    ++capture.glyph_count;
}

void EndExactTextRenderCapture() {
    ExactTextRenderCapture capture;
    {
        std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
        if (g_debug_ui_overlay_state.active_exact_text_renders.empty()) {
            return;
        }

        capture = std::move(g_debug_ui_overlay_state.active_exact_text_renders.back());
        g_debug_ui_overlay_state.active_exact_text_renders.pop_back();
    }

    if (!capture.capture_enabled || capture.glyph_count == 0) {
        return;
    }

    float resolved_left = capture.min_x;
    float resolved_top = capture.min_y;
    float resolved_right = capture.max_x;
    float resolved_bottom = capture.max_y;
    const auto used_owned_rect = TryResolveOwnedExactTextRect(
        capture.surface_id,
        capture.caller_address,
        capture.source_object_ptr,
        &resolved_left,
        &resolved_top,
        &resolved_right,
        &resolved_bottom);

    ObservedUiElement element;
    element.surface_id = std::move(capture.surface_id);
    element.surface_title = std::move(capture.surface_title);
    element.object_ptr = capture.source_object_ptr;
    element.caller_address = capture.caller_address;
    element.surface_return_address = capture.surface_return_address;
    element.stack_slot = capture.stack_slot;
    element.min_x = resolved_left;
    element.max_x = resolved_right;
    element.min_y = resolved_top;
    element.max_y = resolved_bottom;
    element.sample_count = capture.glyph_count;
    element.label = std::move(capture.label);
    auto logged_element = element;
    {
        std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
        g_debug_ui_overlay_state.frame_exact_text_elements.push_back(std::move(element));
    }

    static int s_dialog_exact_capture_logs_remaining = 16;
    if (s_dialog_exact_capture_logs_remaining > 0 && logged_element.surface_id == "dialog") {
        const auto& logged = logged_element;
        --s_dialog_exact_capture_logs_remaining;
        Log(
            "Debug UI dialog exact capture: label=" + SanitizeDebugLogLabel(logged.label) +
            " glyphs=" + std::to_string(logged.sample_count) + " min=(" + std::to_string(logged.min_x) + "," +
            std::to_string(logged.min_y) + ") max=(" + std::to_string(logged.max_x) + "," +
            std::to_string(logged.max_y) + ") object=" + HexString(logged.object_ptr));
    }

    static int s_dark_cloud_browser_exact_capture_logs_remaining = 24;
    if (s_dark_cloud_browser_exact_capture_logs_remaining > 0 && logged_element.surface_id == "dark_cloud_browser") {
        const auto& logged = logged_element;
        --s_dark_cloud_browser_exact_capture_logs_remaining;
        Log(
            "Debug UI Dark Cloud browser exact capture: label=" + SanitizeDebugLogLabel(logged.label) +
            " glyphs=" + std::to_string(logged.sample_count) + " min=(" + std::to_string(logged.min_x) + "," +
            std::to_string(logged.min_y) + ") max=(" + std::to_string(logged.max_x) + "," +
            std::to_string(logged.max_y) + ") object=" + HexString(logged.object_ptr) +
            " caller=" + HexString(logged.caller_address));
    }

    static int s_dark_cloud_search_exact_capture_logs_remaining = 24;
    if (s_dark_cloud_search_exact_capture_logs_remaining > 0 && logged_element.surface_id == "dark_cloud_search") {
        const auto& logged = logged_element;
        --s_dark_cloud_search_exact_capture_logs_remaining;
        Log(
            "Debug UI Dark Cloud search exact capture: label=" + SanitizeDebugLogLabel(logged.label) +
            " glyphs=" + std::to_string(logged.sample_count) + " min=(" + std::to_string(logged.min_x) + "," +
            std::to_string(logged.min_y) + ") max=(" + std::to_string(logged.max_x) + "," +
            std::to_string(logged.max_y) + ") object=" + HexString(logged.object_ptr) +
            " caller=" + HexString(logged.caller_address) + " ownedRect=" + (used_owned_rect ? "1" : "0"));
    }

    static int s_settings_exact_capture_logs_remaining = 24;
    if (s_settings_exact_capture_logs_remaining > 0 && logged_element.surface_id == "settings") {
        const auto& logged = logged_element;
        --s_settings_exact_capture_logs_remaining;
        Log(
            "Debug UI settings exact text capture: label=" + SanitizeDebugLogLabel(logged.label) +
            " glyphs=" + std::to_string(logged.sample_count) + " min=(" + std::to_string(logged.min_x) + "," +
            std::to_string(logged.min_y) + ") max=(" + std::to_string(logged.max_x) + "," +
            std::to_string(logged.max_y) + ") object=" + HexString(logged.object_ptr) +
            " caller=" + HexString(logged.caller_address) + " ownedRect=" + (used_owned_rect ? "1" : "0"));
    }

    static int s_quick_panel_exact_capture_logs_remaining = 24;
    if (s_quick_panel_exact_capture_logs_remaining > 0 && logged_element.surface_id == "quick_panel") {
        const auto& logged = logged_element;
        --s_quick_panel_exact_capture_logs_remaining;
        Log(
            "Debug UI MyQuickCPanel exact text capture: label=" + SanitizeDebugLogLabel(logged.label) +
            " glyphs=" + std::to_string(logged.sample_count) + " min=(" + std::to_string(logged.min_x) + "," +
            std::to_string(logged.min_y) + ") max=(" + std::to_string(logged.max_x) + "," +
            std::to_string(logged.max_y) + ") object=" + HexString(logged.object_ptr) +
            " caller=" + HexString(logged.caller_address) + " ownedRect=" + (used_owned_rect ? "1" : "0"));
    }

    static int s_simple_menu_exact_capture_logs_remaining = 24;
    if (s_simple_menu_exact_capture_logs_remaining > 0 && logged_element.surface_id == "simple_menu") {
        const auto& logged = logged_element;
        --s_simple_menu_exact_capture_logs_remaining;
        Log(
            "Debug UI SimpleMenu exact text capture: label=" + SanitizeDebugLogLabel(logged.label) +
            " glyphs=" + std::to_string(logged.sample_count) + " min=(" + std::to_string(logged.min_x) + "," +
            std::to_string(logged.min_y) + ") max=(" + std::to_string(logged.max_x) + "," +
            std::to_string(logged.max_y) + ") object=" + HexString(logged.object_ptr) +
            " caller=" + HexString(logged.caller_address));
    }

    if (IsDarkCloudSortProbeLabel(logged_element.label)) {
        const auto& logged = logged_element;
        Log(
            "Debug UI Dark Cloud sort probe capture: surface=" + logged.surface_id +
            " label=" + SanitizeDebugLogLabel(logged.label) + " glyphs=" + std::to_string(logged.sample_count) +
            " min=(" + std::to_string(logged.min_x) + "," + std::to_string(logged.min_y) + ") max=(" +
            std::to_string(logged.max_x) + "," + std::to_string(logged.max_y) + ") object=" +
            HexString(logged.object_ptr) + " caller=" + HexString(logged.caller_address) +
            " ownedRect=" + (used_owned_rect ? "1" : "0"));
    }
}

uintptr_t CaptureCallerWidgetPointer() {
#if defined(_MSC_VER) && defined(_M_IX86)
    uintptr_t widget_pointer = 0;
    __asm {
        mov widget_pointer, esi
    }
    return widget_pointer;
#else
    return 0;
#endif
}

bool IsGameplayHudParticipantFallbackLabel(std::string_view label) {
    return label == "ALLY";
}

void __fastcall HookExactTextRender(
    void* self,
    void* /*unused_edx*/,
    void* arg2,
    char* text,
    uintptr_t arg4,
    int* arg5,
    void* arg6,
    uintptr_t arg7,
    uintptr_t arg8,
    float arg9,
    float arg10) {
    const auto caller_address = reinterpret_cast<uintptr_t>(_ReturnAddress());
    const auto widget_pointer = CaptureCallerWidgetPointer();
    BeginExactTextRenderCapture(self, arg2, caller_address, widget_pointer, arg9, arg10, text);

    const auto original = GetX86HookTrampoline<ExactTextRenderFn>(g_debug_ui_overlay_state.exact_text_render_hook);
    if (original != nullptr) {
        original(self, arg2, text, arg4, arg5, arg6, arg7, arg8, arg9, arg10);
    }

    EndExactTextRenderCapture();
}

void __fastcall HookDarkCloudBrowserExactTextRender(
    void* self,
    void* /*unused_edx*/,
    void* arg2,
    char* text,
    uintptr_t arg4,
    int* arg5,
    void* arg6,
    uintptr_t arg7,
    uintptr_t arg8,
    float arg9,
    float arg10) {
    const auto caller_address = reinterpret_cast<uintptr_t>(_ReturnAddress());
    const auto resolved_label = ResolveExactTextRenderLabel(arg2, text);
    static bool s_first_dark_cloud_browser_exact_text_render_logged = false;
    if (!s_first_dark_cloud_browser_exact_text_render_logged) {
        s_first_dark_cloud_browser_exact_text_render_logged = true;
        Log(
            "Debug UI overlay intercepted its first Dark Cloud browser exact text render call. caller=" +
            HexString(caller_address) + " label=" + SanitizeDebugLogLabel(resolved_label));
    }

    const auto widget_pointer = CaptureCallerWidgetPointer();
    BeginExactTextRenderCapture(self, arg2, caller_address, widget_pointer, arg9, arg10, text);

    const auto original =
        GetX86HookTrampoline<ExactTextRenderFn>(g_debug_ui_overlay_state.dark_cloud_browser_exact_text_render_hook);
    if (original != nullptr) {
        original(self, arg2, text, arg4, arg5, arg6, arg7, arg8, arg9, arg10);
    }

    EndExactTextRenderCapture();
}

void __fastcall HookGlyphDrawHelper(void* self, void* /*unused_edx*/, float arg2, float arg3) {
    ObserveActiveExactTextGlyph(arg2, arg3);

    const auto original = GetX86HookTrampoline<GlyphDrawHelperFn>(g_debug_ui_overlay_state.glyph_draw_hook);
    if (original != nullptr) {
        original(self, arg2, arg3);
    }
}

void __fastcall HookTextQuadDrawHelper(void* self, void* /*unused_edx*/, const float* arg2, const float* arg3) {
    ObserveActiveExactTextQuad(arg2, arg3);

    const auto original = GetX86HookTrampoline<TextQuadDrawHelperFn>(g_debug_ui_overlay_state.text_quad_draw_hook);
    if (original != nullptr) {
        original(self, arg2, arg3);
    }
}

void __fastcall HookDarkCloudBrowserRenderHelper(void* self, void* /*unused_edx*/) {
    const auto caller_address = reinterpret_cast<uintptr_t>(_ReturnAddress());
    const auto browser_address = reinterpret_cast<uintptr_t>(self);
    const auto requested_action = PollDarkCloudBrowserActionHotkey();
    {
        std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
        if (!g_debug_ui_overlay_state.first_dark_cloud_browser_render_logged) {
            g_debug_ui_overlay_state.first_dark_cloud_browser_render_logged = true;
            Log(
                "Debug UI overlay intercepted its first Dark Cloud browser render call. object=" +
                HexString(browser_address));
        }

        auto& tracked_browser = g_debug_ui_overlay_state.dark_cloud_browser_render;
        ++tracked_browser.render_depth;
        tracked_browser.active_object_ptr = browser_address;
        tracked_browser.tracked_object_ptr = browser_address;
        tracked_browser.captured_at = GetTickCount64();
    }

    if (requested_action.has_value()) {
        const auto requested_action_id = TryGetDarkCloudBrowserActionId(*requested_action);
        if (requested_action_id.has_value()) {
            std::string queue_error;
            if (TryQueueSemanticUiActionRequest(*requested_action_id, "dark_cloud_browser", nullptr, &queue_error)) {
                Log(
                    "Debug UI overlay queued Dark Cloud browser semantic action via hotkey. action=" +
                    std::string(*requested_action_id) + " browser=" + HexString(browser_address));
            } else {
                Log(
                    "Debug UI overlay failed to queue Dark Cloud browser semantic action via hotkey. action=" +
                    std::string(*requested_action_id) + " browser=" + HexString(browser_address) +
                    " reason=" + queue_error);
            }
        }
    }

    if (const auto* config = TryGetDebugUiOverlayConfig(); config != nullptr && browser_address != 0) {
        ObserveDarkCloudBrowserControlsFromLayout(*config, browser_address, caller_address);
    }

    const auto original = GetX86HookTrampoline<SurfaceRenderHelperFn>(g_debug_ui_overlay_state.dark_cloud_browser_render_hook);
    if (original != nullptr) {
        original(self);
    }

    std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
    auto& tracked_browser = g_debug_ui_overlay_state.dark_cloud_browser_render;
    if (tracked_browser.render_depth > 0) {
        --tracked_browser.render_depth;
    }
    if (tracked_browser.render_depth == 0) {
        tracked_browser.active_object_ptr = 0;
    }
}
