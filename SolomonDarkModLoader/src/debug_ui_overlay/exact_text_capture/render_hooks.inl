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

    {
        static int s_ally_text_render_probe_remaining = 128;
        if (s_ally_text_render_probe_remaining > 0 && arg10 < -70.0f && arg10 > -120.0f &&
            arg9 > -200.0f && arg9 < 200.0f) {
            --s_ally_text_render_probe_remaining;
            const auto resolved_label = ResolveExactTextRenderLabel(arg2, text);
            Log(
                "ALLYTEXTPROBE exact caller=" + HexString(caller_address) +
                " x=" + std::to_string(arg9) + " y=" + std::to_string(arg10) +
                " text=" + SanitizeDebugLogLabel(resolved_label) +
                " self=" + HexString(reinterpret_cast<uintptr_t>(self)) +
                " arg2=" + HexString(reinterpret_cast<uintptr_t>(arg2)) +
                " widget=" + HexString(widget_pointer));
        }
    }

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

    {
        static int s_ally_text_render_probe_remaining = 128;
        if (s_ally_text_render_probe_remaining > 0 && arg10 < -70.0f && arg10 > -120.0f &&
            arg9 > -200.0f && arg9 < 200.0f) {
            --s_ally_text_render_probe_remaining;
            Log(
                "ALLYTEXTPROBE dcbrowser caller=" + HexString(caller_address) +
                " x=" + std::to_string(arg9) + " y=" + std::to_string(arg10) +
                " text=" + SanitizeDebugLogLabel(resolved_label) +
                " self=" + HexString(reinterpret_cast<uintptr_t>(self)) +
                " arg2=" + HexString(reinterpret_cast<uintptr_t>(arg2)));
        }
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
    const auto caller_address = reinterpret_cast<uintptr_t>(_ReturnAddress());

    {
        static int s_ally_probe_logs_remaining = 256;
        if (s_ally_probe_logs_remaining > 0) {
            uintptr_t render_context_address = 0;
            float base_x = 0.0f;
            float base_y = 0.0f;
            if (TryReadUiRenderContext(g_debug_ui_overlay_state.config, &render_context_address) &&
                render_context_address != 0 &&
                TryReadPlainField(
                    reinterpret_cast<const void*>(render_context_address),
                    g_debug_ui_overlay_state.config.ui_render_context_base_x_offset,
                    &base_x) &&
                TryReadPlainField(
                    reinterpret_cast<const void*>(render_context_address),
                    g_debug_ui_overlay_state.config.ui_render_context_base_y_offset,
                    &base_y)) {
                const float glyph_x = base_x + arg2;
                const float glyph_y = base_y + arg3;
                if (glyph_y < -85.0f) {
                    --s_ally_probe_logs_remaining;
                    Log(
                        "ALLYPROBE glyph caller=" + HexString(caller_address) +
                        " x=" + std::to_string(glyph_x) + " y=" + std::to_string(glyph_y) +
                        " self=" + HexString(reinterpret_cast<uintptr_t>(self)));
                }
            }
        }
    }

    ObserveActiveExactTextGlyph(arg2, arg3);

    const auto original = GetX86HookTrampoline<GlyphDrawHelperFn>(g_debug_ui_overlay_state.glyph_draw_hook);
    if (original != nullptr) {
        original(self, arg2, arg3);
    }
}

void __fastcall HookTextQuadDrawHelper(void* self, void* /*unused_edx*/, const float* arg2, const float* arg3) {
    const auto caller_address = reinterpret_cast<uintptr_t>(_ReturnAddress());

    {
        static int s_ally_probe_logs_remaining = 256;
        if (s_ally_probe_logs_remaining > 0) {
            float left = 0.0f;
            float top = 0.0f;
            float right = 0.0f;
            float bottom = 0.0f;
            float alt_left = 0.0f;
            float alt_top = 0.0f;
            float alt_right = 0.0f;
            float alt_bottom = 0.0f;
            const bool primary_valid = TryBuildGlyphQuadBounds(arg2, &left, &top, &right, &bottom);
            const bool alternate_valid = TryBuildGlyphQuadBounds(arg3, &alt_left, &alt_top, &alt_right, &alt_bottom);
            if (primary_valid || alternate_valid) {
                if (alternate_valid) {
                    const float primary_area = primary_valid ? ((right - left) * (bottom - top)) : 0.0f;
                    const float alternate_area = (alt_right - alt_left) * (alt_bottom - alt_top);
                    if (!primary_valid || alternate_area > primary_area) {
                        left = alt_left;
                        top = alt_top;
                        right = alt_right;
                        bottom = alt_bottom;
                    }
                }
                const float width = right - left;
                const float height = bottom - top;
                if (top < -85.0f && width < 40.0f && height < 40.0f) {
                    --s_ally_probe_logs_remaining;
                    Log(
                        "ALLYPROBE quad caller=" + HexString(caller_address) +
                        " l=" + std::to_string(left) + " t=" + std::to_string(top) +
                        " r=" + std::to_string(right) + " b=" + std::to_string(bottom) +
                        " self=" + HexString(reinterpret_cast<uintptr_t>(self)));
                }
            }
        }
    }

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
