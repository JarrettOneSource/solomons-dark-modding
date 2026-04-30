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
