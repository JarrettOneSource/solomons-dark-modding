// Included by lua_world_renderer.cpp inside namespace sdmod.
// Public screen-space primitives that draw through the stock native
// renderer: the world-indicator health bar and the tinted screen quad.

bool DrawNativeWorldIndicatorHealthBar(
    float center_x,
    float top,
    float width,
    float health_ratio) {
    if (!std::isfinite(center_x) || !std::isfinite(top) ||
        !std::isfinite(width) || width < 4.0f ||
        !std::isfinite(health_ratio)) {
        return false;
    }
    std::scoped_lock lock(g_world_renderer.mutex);
    if (!g_world_renderer.initialized ||
        g_world_renderer.native_renderer_set_color == nullptr ||
        g_world_renderer.native_untextured_quad == nullptr) {
        return false;
    }
    void* renderer = TryGetNativeRenderer();
    if (renderer == nullptr) {
        return false;
    }

    constexpr float kHeight = 7.0f;
    constexpr float kInset = 1.0f;
    constexpr NativeWorldIndicatorColor kBorder{12, 6, 6, 235};
    constexpr NativeWorldIndicatorColor kEmpty{54, 13, 13, 220};
    constexpr NativeWorldIndicatorColor kHealth{190, 31, 24, 240};
    constexpr NativeWorldIndicatorColor kHighlight{255, 105, 78, 210};
    const float left = center_x - width * 0.5f;
    const float inner_width = width - kInset * 2.0f;
    const float fill_width = inner_width *
        std::clamp(health_ratio, 0.0f, 1.0f);
    const auto previous_color = ReadNativeRendererBaseColor(renderer);
    DrawNativeIndicatorQuadUnlocked(
        renderer, left, top, width, kHeight, kBorder);
    DrawNativeIndicatorQuadUnlocked(
        renderer,
        left + kInset,
        top + kInset,
        inner_width,
        kHeight - kInset * 2.0f,
        kEmpty);
    if (fill_width > 0.0f) {
        DrawNativeIndicatorQuadUnlocked(
            renderer,
            left + kInset,
            top + kInset,
            fill_width,
            kHeight - kInset * 2.0f,
            kHealth);
        DrawNativeIndicatorQuadUnlocked(
            renderer,
            left + kInset,
            top + kInset,
            fill_width,
            1.0f,
            kHighlight);
    }
    RestoreNativeRendererColor(renderer, previous_color);
    return true;
}

bool DrawNativeScreenQuad(
    float left,
    float top,
    float width,
    float height,
    const NativeWorldIndicatorColor& color) {
    if (!std::isfinite(left) || !std::isfinite(top) ||
        !std::isfinite(width) || !std::isfinite(height) ||
        width <= 0.0f || height <= 0.0f) {
        return false;
    }
    std::scoped_lock lock(g_world_renderer.mutex);
    if (!g_world_renderer.initialized ||
        g_world_renderer.native_renderer_set_color == nullptr ||
        g_world_renderer.native_untextured_quad == nullptr) {
        return false;
    }
    void* renderer = TryGetNativeRenderer();
    if (renderer == nullptr) {
        return false;
    }
    const auto previous_color = ReadNativeRendererBaseColor(renderer);
    DrawNativeIndicatorQuadUnlocked(renderer, left, top, width, height, color);
    RestoreNativeRendererColor(renderer, previous_color);
    return true;
}
