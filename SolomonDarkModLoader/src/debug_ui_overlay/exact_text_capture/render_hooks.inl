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
    std::array<float, 8> adjusted_vertices{};
    const float* draw_vertices = arg2;
    if (TryApplyGameplayNameplateViewportClamp(
            self,
            arg2,
            &adjusted_vertices)) {
        draw_vertices = adjusted_vertices.data();
    }
    ObserveActiveExactTextQuad(self, draw_vertices, arg3);

    const auto original = GetX86HookTrampoline<TextQuadDrawHelperFn>(g_debug_ui_overlay_state.text_quad_draw_hook);
    if (original != nullptr) {
        original(self, draw_vertices, arg3);
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

    DrawNativeDarkCloudBrowserMultiplayerTab(browser_address, caller_address);

    std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
    auto& tracked_browser = g_debug_ui_overlay_state.dark_cloud_browser_render;
    if (tracked_browser.render_depth > 0) {
        --tracked_browser.render_depth;
    }
    if (tracked_browser.render_depth == 0) {
        tracked_browser.active_object_ptr = 0;
    }
}
