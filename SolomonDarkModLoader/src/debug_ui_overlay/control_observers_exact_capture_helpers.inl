void RecordExactControlElement(
    std::string surface_id,
    std::string surface_title,
    uintptr_t source_object_ptr,
    uintptr_t caller_address,
    float left,
    float top,
    float right,
    float bottom,
    std::string label) {
    if (!IsPlausibleSurfaceWidgetRect(left, top, right - left, bottom - top)) {
        return;
    }

    std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
    if (g_debug_ui_overlay_state.frame_exact_control_elements.size() >=
        g_debug_ui_overlay_state.config.max_tracked_elements_per_frame) {
        return;
    }

    const auto identity = source_object_ptr != 0
        ? source_object_ptr
        : BuildObservationIdentityKey(reinterpret_cast<void*>(caller_address), left, top, caller_address, false);

    for (auto& element : g_debug_ui_overlay_state.frame_exact_control_elements) {
        if (element.object_ptr == identity && element.surface_id == surface_id) {
            element.min_x = (std::min)(element.min_x, left);
            element.max_x = (std::max)(element.max_x, right);
            element.min_y = (std::min)(element.min_y, top);
            element.max_y = (std::max)(element.max_y, bottom);
            ++element.sample_count;
            if (element.label.empty() && !label.empty()) {
                element.label = std::move(label);
            }
            return;
        }
    }

    ObservedUiElement element;
    element.surface_id = std::move(surface_id);
    element.surface_title = std::move(surface_title);
    element.object_ptr = identity;
    element.caller_address = caller_address;
    element.min_x = left;
    element.max_x = right;
    element.min_y = top;
    element.max_y = bottom;
    element.sample_count = 1;
    element.label = std::move(label);
    g_debug_ui_overlay_state.frame_exact_control_elements.push_back(std::move(element));

    if (!g_debug_ui_overlay_state.first_exact_control_render_logged) {
        g_debug_ui_overlay_state.first_exact_control_render_logged = true;
        const auto& first_element = g_debug_ui_overlay_state.frame_exact_control_elements.back();
        Log(
            "Debug UI overlay captured its first exact control render. surface=" + first_element.surface_id +
            " label=" + SanitizeDebugLogLabel(first_element.label) + " caller=" +
            HexString(first_element.caller_address));
    }
}
