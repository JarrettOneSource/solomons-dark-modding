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
