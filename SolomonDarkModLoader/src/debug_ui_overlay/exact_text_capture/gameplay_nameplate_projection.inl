struct D3dHomogeneousPoint {
    float x = 0.0f;
    float y = 0.0f;
    float z = 0.0f;
    float w = 1.0f;
};

D3dHomogeneousPoint TransformD3dRowVector(
    const D3dHomogeneousPoint& point,
    const D3DMATRIX& matrix) {
    return {
        point.x * matrix._11 + point.y * matrix._21 +
            point.z * matrix._31 + point.w * matrix._41,
        point.x * matrix._12 + point.y * matrix._22 +
            point.z * matrix._32 + point.w * matrix._42,
        point.x * matrix._13 + point.y * matrix._23 +
            point.z * matrix._33 + point.w * matrix._43,
        point.x * matrix._14 + point.y * matrix._24 +
            point.z * matrix._34 + point.w * matrix._44,
    };
}

bool TryProjectGameplayNameplateQuadBounds(
    void* draw_state,
    const float* destination_vertices,
    float base_x,
    float base_y,
    float* left,
    float* top,
    float* right,
    float* bottom) {
    if (draw_state == nullptr ||
        destination_vertices == nullptr ||
        left == nullptr ||
        top == nullptr ||
        right == nullptr ||
        bottom == nullptr) {
        return false;
    }

    auto* device = GetLastSeenD3d9Device();
    if (device == nullptr) {
        return false;
    }

    float depth = 0.0f;
    D3DVIEWPORT9 viewport{};
    D3DMATRIX world{};
    D3DMATRIX view{};
    D3DMATRIX projection{};
    if (!TryReadPlainField(
            draw_state,
            kTextQuadDrawStateDepthOffset,
            &depth) ||
        !std::isfinite(depth) ||
        FAILED(device->GetViewport(&viewport)) ||
        viewport.Width == 0 ||
        viewport.Height == 0 ||
        FAILED(device->GetTransform(D3DTS_WORLD, &world)) ||
        FAILED(device->GetTransform(D3DTS_VIEW, &view)) ||
        FAILED(device->GetTransform(D3DTS_PROJECTION, &projection))) {
        return false;
    }

    float projected_left = (std::numeric_limits<float>::max)();
    float projected_top = (std::numeric_limits<float>::max)();
    float projected_right = (std::numeric_limits<float>::lowest)();
    float projected_bottom = (std::numeric_limits<float>::lowest)();
    constexpr float kMinimumPositiveClipW = 0.0001f;
    for (int index = 0; index < 8; index += 2) {
        D3dHomogeneousPoint point{
            destination_vertices[index] + base_x,
            destination_vertices[index + 1] + base_y,
            depth,
            1.0f,
        };
        point = TransformD3dRowVector(point, world);
        point = TransformD3dRowVector(point, view);
        const auto clip = TransformD3dRowVector(point, projection);
        if (!std::isfinite(clip.x) ||
            !std::isfinite(clip.y) ||
            !std::isfinite(clip.w) ||
            clip.w <= kMinimumPositiveClipW) {
            return false;
        }

        const float normalized_x = clip.x / clip.w;
        const float normalized_y = clip.y / clip.w;
        const float screen_x =
            static_cast<float>(viewport.X) +
            (normalized_x + 1.0f) *
                static_cast<float>(viewport.Width) * 0.5f;
        const float screen_y =
            static_cast<float>(viewport.Y) +
            (1.0f - normalized_y) *
                static_cast<float>(viewport.Height) * 0.5f;
        if (!std::isfinite(screen_x) || !std::isfinite(screen_y)) {
            return false;
        }

        projected_left = (std::min)(projected_left, screen_x);
        projected_top = (std::min)(projected_top, screen_y);
        projected_right = (std::max)(projected_right, screen_x);
        projected_bottom = (std::max)(projected_bottom, screen_y);
    }

    if (projected_right - projected_left < 2.0f ||
        projected_bottom - projected_top < 2.0f) {
        return false;
    }

    *left = projected_left;
    *top = projected_top;
    *right = projected_right;
    *bottom = projected_bottom;
    return true;
}

bool TryApplyGameplayNameplateViewportClamp(
    void* draw_state,
    const float* destination_vertices,
    std::array<float, 8>* adjusted_vertices) {
    if (draw_state == nullptr ||
        destination_vertices == nullptr ||
        adjusted_vertices == nullptr) {
        return false;
    }

    float base_x = 0.0f;
    float base_y = 0.0f;
    if (!TryReadUiRenderBase(&base_x, &base_y)) {
        return false;
    }

    std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
    if (g_debug_ui_overlay_state.active_exact_text_renders.empty()) {
        return false;
    }
    auto& capture = g_debug_ui_overlay_state.active_exact_text_renders.back();
    if (!capture.capture_enabled ||
        capture.surface_id != "gameplay_nameplate" ||
        !std::isfinite(capture.gameplay_world_width) ||
        capture.gameplay_world_width <= 0.0f) {
        return false;
    }

    if (!capture.gameplay_viewport_offset_resolved) {
        float glyph_left = (std::numeric_limits<float>::max)();
        float glyph_top = (std::numeric_limits<float>::max)();
        float glyph_right = (std::numeric_limits<float>::lowest)();
        float glyph_bottom = (std::numeric_limits<float>::lowest)();
        for (int index = 0; index < 8; index += 2) {
            glyph_left = (std::min)(glyph_left, destination_vertices[index]);
            glyph_top = (std::min)(glyph_top, destination_vertices[index + 1]);
            glyph_right = (std::max)(glyph_right, destination_vertices[index]);
            glyph_bottom = (std::max)(glyph_bottom, destination_vertices[index + 1]);
        }
        if (!std::isfinite(glyph_left) ||
            !std::isfinite(glyph_top) ||
            !std::isfinite(glyph_right) ||
            !std::isfinite(glyph_bottom) ||
            glyph_right <= glyph_left ||
            glyph_bottom <= glyph_top) {
            return false;
        }

        std::array<float, 8> full_name_quad{
            glyph_left,
            glyph_top,
            glyph_left + capture.gameplay_world_width,
            glyph_top,
            glyph_left,
            glyph_bottom,
            glyph_left + capture.gameplay_world_width,
            glyph_bottom,
        };
        float name_left = 0.0f;
        float name_top = 0.0f;
        float name_right = 0.0f;
        float name_bottom = 0.0f;
        if (!TryProjectGameplayNameplateQuadBounds(
                draw_state,
                full_name_quad.data(),
                base_x,
                base_y,
                &name_left,
                &name_top,
                &name_right,
                &name_bottom)) {
            return false;
        }

        auto* device = GetLastSeenD3d9Device();
        D3DVIEWPORT9 viewport{};
        if (device == nullptr ||
            FAILED(device->GetViewport(&viewport)) ||
            viewport.Width == 0 ||
            viewport.Height == 0) {
            return false;
        }
        const float viewport_left = static_cast<float>(viewport.X);
        const float viewport_top = static_cast<float>(viewport.Y);
        const float viewport_right =
            viewport_left + static_cast<float>(viewport.Width);
        const float viewport_bottom =
            viewport_top + static_cast<float>(viewport.Height);
        constexpr float kViewportMargin = 2.0f;
        constexpr float kMinimumHealthBarWidth = 64.0f;
        constexpr float kHealthBarVerticalExtent = 8.0f;

        const float name_center_x = (name_left + name_right) * 0.5f;
        const float combined_width = (std::max)(
            kMinimumHealthBarWidth,
            name_right - name_left);
        const float combined_left = name_center_x - combined_width * 0.5f;
        const float combined_right = name_center_x + combined_width * 0.5f;
        const float combined_top = name_top;
        const float combined_bottom = name_bottom + kHealthBarVerticalExtent;
        const bool intersects_viewport =
            combined_right > viewport_left &&
            combined_left < viewport_right &&
            combined_bottom > viewport_top &&
            combined_top < viewport_bottom;

        float screen_shift_x = 0.0f;
        float screen_shift_y = 0.0f;
        if (intersects_viewport) {
            const auto resolve_screen_shift = [=](
                float low,
                float high,
                float viewport_low,
                float viewport_high) {
                const float safe_low = viewport_low + kViewportMargin;
                const float safe_high = viewport_high - kViewportMargin;
                if (high - low > safe_high - safe_low) {
                    return ((safe_low + safe_high) - (low + high)) * 0.5f;
                }
                if (low < safe_low) {
                    return safe_low - low;
                }
                if (high > safe_high) {
                    return safe_high - high;
                }
                return 0.0f;
            };
            screen_shift_x = resolve_screen_shift(
                combined_left,
                combined_right,
                viewport_left,
                viewport_right);
            screen_shift_y = resolve_screen_shift(
                combined_top,
                combined_bottom,
                viewport_top,
                viewport_bottom);
        }

        if (std::fabs(screen_shift_x) > 0.001f ||
            std::fabs(screen_shift_y) > 0.001f) {
            std::array<float, 8> shifted_x = full_name_quad;
            std::array<float, 8> shifted_y = full_name_quad;
            for (int index = 0; index < 8; index += 2) {
                shifted_x[index] += 1.0f;
                shifted_y[index + 1] += 1.0f;
            }

            float shifted_x_left = 0.0f;
            float shifted_x_top = 0.0f;
            float shifted_x_right = 0.0f;
            float shifted_x_bottom = 0.0f;
            float shifted_y_left = 0.0f;
            float shifted_y_top = 0.0f;
            float shifted_y_right = 0.0f;
            float shifted_y_bottom = 0.0f;
            if (TryProjectGameplayNameplateQuadBounds(
                    draw_state,
                    shifted_x.data(),
                    base_x,
                    base_y,
                    &shifted_x_left,
                    &shifted_x_top,
                    &shifted_x_right,
                    &shifted_x_bottom) &&
                TryProjectGameplayNameplateQuadBounds(
                    draw_state,
                    shifted_y.data(),
                    base_x,
                    base_y,
                    &shifted_y_left,
                    &shifted_y_top,
                    &shifted_y_right,
                    &shifted_y_bottom)) {
                const float base_center_x =
                    (name_left + name_right) * 0.5f;
                const float base_center_y =
                    (name_top + name_bottom) * 0.5f;
                const float x_step_screen_x =
                    (shifted_x_left + shifted_x_right) * 0.5f - base_center_x;
                const float x_step_screen_y =
                    (shifted_x_top + shifted_x_bottom) * 0.5f - base_center_y;
                const float y_step_screen_x =
                    (shifted_y_left + shifted_y_right) * 0.5f - base_center_x;
                const float y_step_screen_y =
                    (shifted_y_top + shifted_y_bottom) * 0.5f - base_center_y;
                const float determinant =
                    x_step_screen_x * y_step_screen_y -
                    y_step_screen_x * x_step_screen_y;
                if (std::isfinite(determinant) &&
                    std::fabs(determinant) > 0.000001f) {
                    const float offset_x =
                        (screen_shift_x * y_step_screen_y -
                         y_step_screen_x * screen_shift_y) /
                        determinant;
                    const float offset_y =
                        (x_step_screen_x * screen_shift_y -
                         screen_shift_x * x_step_screen_y) /
                        determinant;
                    if (std::isfinite(offset_x) &&
                        std::isfinite(offset_y) &&
                        std::fabs(offset_x) <= 4096.0f &&
                        std::fabs(offset_y) <= 4096.0f) {
                        capture.gameplay_viewport_offset_x = offset_x;
                        capture.gameplay_viewport_offset_y = offset_y;
                    }
                }
            }
        }
        capture.gameplay_viewport_offset_resolved = true;
    }

    std::copy_n(
        destination_vertices,
        adjusted_vertices->size(),
        adjusted_vertices->begin());
    for (int index = 0; index < 8; index += 2) {
        (*adjusted_vertices)[index] += capture.gameplay_viewport_offset_x;
        (*adjusted_vertices)[index + 1] += capture.gameplay_viewport_offset_y;
    }
    return true;
}
