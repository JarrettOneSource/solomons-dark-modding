// ---------------------------------------------------------------------------
// Semantic surface registry: table-driven priority cascade replacing
// per-surface if-else branches. Each entry describes observed stock UI used by
// sd.ui and launcher automation. Diagnostic rendering is registered separately
// and only after the explicit diagnostic gate below.
// ---------------------------------------------------------------------------

struct SemanticSurfaceRegistryEntry {
    const char* surface_id;
    const char* log_name;
    bool clear_main_menu_tracking;
    bool clear_settings_tracking;
    bool log_element_summary;
    bool first_frame_logged;
};

static SemanticSurfaceRegistryEntry s_semantic_surface_registry[] = {
    // Priority order: first match wins.
    {"control_scheme_picker", "ControlSchemePicker", true, true, true, false},
    {"controls",            "Controls",             true,  false, true,  false},
    {"settings",            "Settings",             true,  false, false, false},
    {"create",              "Create",               true,  true,  true,  false},
    {"dark_cloud_search",   "Dark Cloud search",    false, true,  true,  false},
    {"quick_panel",         "QuickPanel",           true,  false, true,  false},
    {"simple_menu",         "SimpleMenu",           false, true,  true,  false},
    {"dark_cloud_browser",  "Dark Cloud browser",   false, true,  true,  false},
    {"hall_of_fame",        "HallOfFame",           true,  true,  true,  false},
    {"spell_picker",        "SpellPicker",          true,  true,  true,  false},
    {"main_menu",           "MainMenu",             false, true,  true,  false},
};

static constexpr std::size_t kSemanticSurfaceRegistrySize =
    sizeof(s_semantic_surface_registry) /
    sizeof(s_semantic_surface_registry[0]);
static constexpr std::uint64_t kFreshTrackedDialogPriorityMs = 250;

void ResetSurfaceRegistryFirstFrameFlags() {
    for (auto& entry : s_semantic_surface_registry) {
        entry.first_frame_logged = false;
    }
}

struct SurfaceRegistryInitializer {
    SurfaceRegistryInitializer() {
        g_reset_surface_registry_first_frame_flags = &ResetSurfaceRegistryFirstFrameFlags;
    }
};
static SurfaceRegistryInitializer s_surface_registry_initializer;

struct DiagnosticSurfaceFrame {
    std::vector<OverlayRenderElement> render_elements;
    std::string level_up_wait_text;
    std::size_t registered_surface_count = 0;
};

DiagnosticSurfaceFrame RegisterDiagnosticSurfaceFrame(
    bool diagnostic_visuals_enabled,
    const std::vector<OverlayRenderElement>& semantic_surface_elements) {
    DiagnosticSurfaceFrame frame;
    if (diagnostic_visuals_enabled &&
        !semantic_surface_elements.empty()) {
        frame.render_elements = semantic_surface_elements;
        ++frame.registered_surface_count;
    }
    if (multiplayer::TryBuildLevelUpWaitStatusText(
            &frame.level_up_wait_text) &&
        !frame.level_up_wait_text.empty()) {
        ++frame.registered_surface_count;
    }
    return frame;
}

void LogDiagnosticSurfaceFrameState(
    bool enabled,
    std::size_t registered_surface_count,
    std::size_t rendered_surface_count) {
    bool changed = false;
    {
        std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
        changed =
            !g_debug_ui_overlay_state.diagnostic_surface_state_logged ||
            g_debug_ui_overlay_state.diagnostic_surface_state_enabled !=
                enabled ||
            g_debug_ui_overlay_state.diagnostic_surface_registered_count !=
                registered_surface_count ||
            g_debug_ui_overlay_state.diagnostic_surface_rendered_count !=
                rendered_surface_count;
        if (changed) {
            g_debug_ui_overlay_state.diagnostic_surface_state_logged = true;
            g_debug_ui_overlay_state.diagnostic_surface_state_enabled =
                enabled;
            g_debug_ui_overlay_state.diagnostic_surface_registered_count =
                registered_surface_count;
            g_debug_ui_overlay_state.diagnostic_surface_rendered_count =
                rendered_surface_count;
        }
    }
    if (!changed) {
        return;
    }

    Log(
        "Debug UI diagnostic surface set. enabled=" +
        std::to_string(enabled ? 1 : 0) +
        " registered=" + std::to_string(registered_surface_count) +
        " rendered=" + std::to_string(rendered_surface_count));
}

void DrawMultiplayerJoinFlowPresentation(
    IDirect3DDevice9* device,
    const MultiplayerJoinFlowPresentation& presentation) {
    D3DVIEWPORT9 viewport = {};
    if (device == nullptr ||
        FAILED(device->GetViewport(&viewport))) {
        return;
    }

    const auto left = static_cast<float>(viewport.X);
    const auto top = static_cast<float>(viewport.Y);
    const auto right = left + static_cast<float>(viewport.Width);
    const auto bottom = top + static_cast<float>(viewport.Height);
    DrawFilledRect(
        device,
        left,
        top,
        right,
        bottom,
        D3DCOLOR_ARGB(255, 0, 0, 0));

    if (presentation.message.empty()) {
        return;
    }

    const auto text_width = static_cast<float>(
        MeasureLabelWidth(
            g_debug_ui_overlay_state.font_atlas,
            presentation.message));
    const auto text_left =
        left + (static_cast<float>(viewport.Width) - text_width) * 0.5f;
    const auto text_top =
        top +
        (static_cast<float>(viewport.Height) -
         static_cast<float>(
             g_debug_ui_overlay_state.font_atlas.line_height)) *
            0.5f;
    DrawLabelText(
        device,
        g_debug_ui_overlay_state.font_atlas,
        text_left,
        text_top,
        presentation.message,
        kLabelTextColor);
}

void RenderOverlayFrame(IDirect3DDevice9* device) {
    bool diagnostic_visuals_enabled = false;
    {
        std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
        diagnostic_visuals_enabled =
            g_debug_ui_overlay_state.diagnostic_visuals_enabled;
    }

    auto raw_elements = TakeObservedFrameElements();
    auto exact_text_elements = TakeExactTextFrameElements();
    auto exact_control_elements = TakeExactControlFrameElements();
    auto menu_art_elements = TakeCapturedMenuArtFrame();
    auto elements = FilterElementsToDominantSurface(raw_elements);
    std::vector<OverlayRenderElement> semantic_surface_elements;
    const auto quick_panel_render_elements =
        TryBuildQuickPanelOverlayRenderElements(exact_text_elements, exact_control_elements);

    struct { const char* id; std::vector<OverlayRenderElement> elems; } built[] = {
        {"control_scheme_picker", TryBuildControlSchemePickerOverlayRenderElements()},
        {"controls",           TryBuildControlsOverlayRenderElements(exact_text_elements, exact_control_elements)},
        {"settings",           TryBuildSettingsOverlayRenderElements(exact_text_elements, exact_control_elements)},
        {"create",             TryBuildCreateOverlayRenderElements()},
        {"dark_cloud_search",  TryBuildDarkCloudSearchOverlayRenderElements(quick_panel_render_elements)},
        {"quick_panel",        std::vector<OverlayRenderElement>(quick_panel_render_elements)},
        {"simple_menu",        TryBuildSimpleMenuOverlayRenderElements(exact_text_elements, exact_control_elements)},
        {"dark_cloud_browser", TryBuildDarkCloudBrowserOverlayRenderElements(exact_text_elements, exact_control_elements, elements)},
        {"hall_of_fame",       TryBuildHallOfFameOverlayRenderElements(exact_text_elements)},
        {"spell_picker",       TryBuildSpellPickerOverlayRenderElements(exact_text_elements)},
        {"main_menu",          TryBuildTitleMainMenuOverlayRenderElements(g_debug_ui_overlay_state.font_atlas, exact_text_elements, exact_control_elements, elements)},
    };

    auto dialog_snapshot = TryBuildTrackedDialogOverlaySnapshot(device, elements, exact_text_elements);

    const char* higher_priority_surface_name = "";
    for (std::size_t i = 0; i < kSemanticSurfaceRegistrySize; ++i) {
        if (!built[i].elems.empty()) {
            higher_priority_surface_name =
                s_semantic_surface_registry[i].surface_id;
            break;
        }
    }

    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    const bool dialog_was_just_captured =
        dialog_snapshot.has_value() &&
        now_ms >= dialog_snapshot->captured_at &&
        now_ms - dialog_snapshot->captured_at <=
            kFreshTrackedDialogPriorityMs;
    if (dialog_snapshot.has_value() &&
        !dialog_was_just_captured &&
        higher_priority_surface_name[0] != '\0' &&
        std::strcmp(higher_priority_surface_name, "main_menu") != 0) {
        ClearTrackedDialogBecauseHigherPrioritySurfaceBecameDominant(higher_priority_surface_name);
        dialog_snapshot.reset();
    }

    if (dialog_snapshot.has_value()) {
        semantic_surface_elements =
            BuildDialogOverlayRenderElements(*dialog_snapshot);
        elements.clear();
        std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
        g_debug_ui_overlay_state.settings_render.tracked_object_ptr = 0;
        if (diagnostic_visuals_enabled &&
            !g_debug_ui_overlay_state.first_tracked_dialog_frame_logged) {
            g_debug_ui_overlay_state.first_tracked_dialog_frame_logged = true;
            Log(
                "Debug UI overlay rendered its first tracked dialog frame. left=" +
                std::to_string(dialog_snapshot->left) + " top=" + std::to_string(dialog_snapshot->top) +
                " width=" + std::to_string(dialog_snapshot->right - dialog_snapshot->left) + " height=" +
                std::to_string(dialog_snapshot->bottom - dialog_snapshot->top) + " buttons=" +
                std::to_string(dialog_snapshot->buttons.size()));
        }
    } else {
        for (std::size_t i = 0;
             i < kSemanticSurfaceRegistrySize;
             ++i) {
            if (built[i].elems.empty()) {
                continue;
            }

            semantic_surface_elements = std::move(built[i].elems);
            elements.clear();
            auto& entry = s_semantic_surface_registry[i];

            std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
            if (entry.clear_main_menu_tracking) {
                g_debug_ui_overlay_state.tracked_title_main_menu_object = 0;
            }
            if (entry.clear_settings_tracking) {
                g_debug_ui_overlay_state.settings_render.tracked_object_ptr = 0;
            }
            if (diagnostic_visuals_enabled &&
                !entry.first_frame_logged) {
                entry.first_frame_logged = true;
                Log(
                    "Debug UI overlay rendered its first " + std::string(entry.log_name) +
                    " frame. elements=" +
                    std::to_string(semantic_surface_elements.size()));
                if (entry.log_element_summary) {
                    LogOverlayRenderElementsSummary(
                        entry.log_name,
                        semantic_surface_elements);
                }
            }
            break;
        }

        if (semantic_surface_elements.empty() && !elements.empty()) {
            semantic_surface_elements = BuildOverlayRenderElements(
                elements,
                g_debug_ui_overlay_state.font_atlas);
        }
    }

    const auto observed_surface_id = semantic_surface_elements.empty()
        ? std::string{}
        : GetOverlaySurfaceRootId(
              semantic_surface_elements.front().surface_id);
    ObserveMultiplayerJoinFlowSurface(observed_surface_id);
    {
        std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
        StoreLatestSurfaceSnapshotUnlocked(
            &g_debug_ui_overlay_state,
            semantic_surface_elements);
        StoreLatestMenuLayoutSnapshotUnlocked(
            &g_debug_ui_overlay_state,
            semantic_surface_elements,
            exact_text_elements,
            menu_art_elements);
    }
    const auto diagnostic_surface_frame =
        RegisterDiagnosticSurfaceFrame(
            diagnostic_visuals_enabled,
            semantic_surface_elements);
    const auto& gameplay_level_up_wait_text =
        diagnostic_surface_frame.level_up_wait_text;

    const auto join_flow_presentation =
        GetMultiplayerJoinFlowPresentation();
    if (join_flow_presentation.visible) {
        LogDiagnosticSurfaceFrameState(
            diagnostic_visuals_enabled,
            diagnostic_surface_frame.registered_surface_count,
            0);
        ConfigureOverlayRenderState(device);
        DrawMultiplayerJoinFlowPresentation(
            device,
            join_flow_presentation);
        return;
    }

    LogDiagnosticSurfaceFrameState(
        diagnostic_visuals_enabled,
        diagnostic_surface_frame.registered_surface_count,
        diagnostic_surface_frame.registered_surface_count);
    if (gameplay_level_up_wait_text.empty()) {
        LogGameplayLevelUpWaitStatusDraw(
            {},
            GameplayLevelUpWaitDrawResult::Hidden);
    }
    if (diagnostic_surface_frame.render_elements.empty() &&
        gameplay_level_up_wait_text.empty()) {
        return;
    }

    ConfigureOverlayRenderState(device);

    for (const auto& element :
         diagnostic_surface_frame.render_elements) {
        DrawObservedOverlayElement(device, g_debug_ui_overlay_state.font_atlas, element);
    }
    if (!gameplay_level_up_wait_text.empty()) {
        const auto draw_result = DrawGameplayLevelUpWaitStatus(
            device,
            g_debug_ui_overlay_state.font_atlas,
            gameplay_level_up_wait_text);
        LogGameplayLevelUpWaitStatusDraw(
            gameplay_level_up_wait_text,
            draw_result);
    }
    if (!g_debug_ui_overlay_state.first_frame_logged) {
        g_debug_ui_overlay_state.first_frame_logged = true;
        Log(
            "Debug UI overlay observed " + std::to_string(elements.size()) + " raw UI draw candidate(s) and rendered " +
            std::to_string(
                diagnostic_surface_frame.render_elements.size()) +
            " diagnostic element overlay region(s) on the first rendered frame.");
    }

}

void OnD3d9Frame(IDirect3DDevice9* device) {
    if (device == nullptr) {
        return;
    }

    {
        std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
        if (!g_debug_ui_overlay_state.first_d3d_frame_logged) {
            g_debug_ui_overlay_state.first_d3d_frame_logged = true;
            Log("Debug UI overlay received its first D3D9 frame callback.");
        }
    }

    if (g_debug_ui_overlay_state.font_device != device) {
        ReleaseFontAtlas(&g_debug_ui_overlay_state.font_atlas);
        g_debug_ui_overlay_state.font_device = device;
    }
    std::string font_error;
    if (!InitializeFontAtlas(device, &g_debug_ui_overlay_state.font_atlas, &font_error)) {
        std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
        if (!g_debug_ui_overlay_state.first_font_atlas_failure_logged) {
            g_debug_ui_overlay_state.first_font_atlas_failure_logged = true;
            Log("Debug UI overlay failed to prewarm its font atlas on the frame hook. " + font_error);
        }
        return;
    }

    {
        std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
        if (!g_debug_ui_overlay_state.first_font_atlas_ready_logged) {
            g_debug_ui_overlay_state.first_font_atlas_ready_logged = true;
            Log("Debug UI overlay prewarmed its font atlas on the frame hook.");
        }
    }

    RenderOverlayFrame(device);
}
