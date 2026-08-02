// Included by lua_world_renderer.cpp inside its anonymous namespace.

std::array<float, 4> ReadNativeRendererBaseColor(void* renderer) {
    return {
        ReadNativeField<float>(renderer, kNativeRendererBaseRedOffset),
        ReadNativeField<float>(renderer, kNativeRendererBaseGreenOffset),
        ReadNativeField<float>(renderer, kNativeRendererBaseBlueOffset),
        ReadNativeField<float>(renderer, kNativeRendererBaseAlphaOffset),
    };
}

void SetNativeRendererColor(
    void* renderer,
    const NativeWorldIndicatorColor& color) {
    g_world_renderer.native_renderer_set_color(
        renderer,
        static_cast<float>(color.red) / 255.0f,
        static_cast<float>(color.green) / 255.0f,
        static_cast<float>(color.blue) / 255.0f,
        static_cast<float>(color.alpha) / 255.0f);
}

void RestoreNativeRendererColor(
    void* renderer,
    const std::array<float, 4>& color) {
    g_world_renderer.native_renderer_set_color(
        renderer,
        color[0],
        color[1],
        color[2],
        color[3]);
}

void DrawNativeIndicatorQuadUnlocked(
    void* renderer,
    float left,
    float top,
    float width,
    float height,
    const NativeWorldIndicatorColor& color) {
    SetNativeRendererColor(renderer, color);
    g_world_renderer.native_untextured_quad(
        renderer,
        left,
        top,
        width,
        height);
}

void RenderLuaWorldMarkersInNativePass() {
    std::scoped_lock lock(g_world_renderer.mutex);
    if (!g_world_renderer.initialized ||
        g_world_renderer.native_renderer_set_color == nullptr ||
        g_world_renderer.native_untextured_quad == nullptr) {
        return;
    }
    void* renderer = TryGetNativeRenderer();
    if (renderer == nullptr) {
        return;
    }
    RefreshLuaWorldRenderFrameSnapshots(
        &g_world_renderer.frame_snapshots);
    const auto previous_color = ReadNativeRendererBaseColor(renderer);
    for (const auto& frame : g_world_renderer.frame_snapshots) {
        for (const auto& marker : frame.markers) {
            float x = 0.0f;
            float y = 0.0f;
            if (!TryProjectNativeWorldIndicatorPoint(
                    marker.x,
                    marker.y,
                    &x,
                    &y)) {
                continue;
            }
            const NativeWorldIndicatorColor color{
                marker.red,
                marker.green,
                marker.blue,
                marker.alpha,
            };
            DrawNativeIndicatorQuadUnlocked(
                renderer, x - 10.0f, y - 1.0f, 20.0f, 2.0f, color);
            DrawNativeIndicatorQuadUnlocked(
                renderer, x - 1.0f, y - 10.0f, 2.0f, 20.0f, color);

            SetNativeRendererColor(renderer, color);
            const auto text_width =
                static_cast<float>(marker.label.size()) * 8.0f;
            const std::string exact_text = "_s(0.5)" + marker.label;
            (void)DrawNativeWorldIndicatorExactText(
                exact_text,
                x - text_width * 0.5f,
                y - 30.0f);
            if (!g_world_renderer.logged_native_marker_draw) {
                g_world_renderer.logged_native_marker_draw = true;
                Log(
                    "lua_world_render: native post-scene marker drawn. mod=" +
                    frame.mod_id);
            }
        }
    }
    RestoreNativeRendererColor(renderer, previous_color);
}

void __fastcall HookNativeArenaRender(
    void* self,
    void* /*unused_edx*/) {
    const auto original =
        GetX86HookTrampoline<NativeArenaRenderFn>(
            g_world_renderer.arena_render_hook);
    if (original == nullptr) {
        return;
    }
    original(self);
    RenderGameplayWorldIndicatorsInNativePass();
    RenderLuaWorldMarkersInNativePass();
}
