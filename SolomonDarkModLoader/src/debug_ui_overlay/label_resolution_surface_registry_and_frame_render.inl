// ---------------------------------------------------------------------------
// Surface registry: table-driven priority cascade replacing per-surface
// if-else branches.  Each entry defines a builder that returns overlay
// elements for a surface, plus metadata controlling first-frame logging
// and which tracked state to clear when the surface becomes dominant.
// ---------------------------------------------------------------------------

struct SurfaceRegistryEntry {
    const char* surface_id;
    const char* log_name;
    bool clear_main_menu_tracking;
    bool clear_settings_tracking;
    bool log_element_summary;
    bool first_frame_logged;
};

static SurfaceRegistryEntry s_surface_registry[] = {
    // Priority order: first match wins.
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

static constexpr std::size_t kSurfaceRegistrySize = sizeof(s_surface_registry) / sizeof(s_surface_registry[0]);

void ResetSurfaceRegistryFirstFrameFlags() {
    for (auto& entry : s_surface_registry) {
        entry.first_frame_logged = false;
    }
}

struct SurfaceRegistryInitializer {
    SurfaceRegistryInitializer() {
        g_reset_surface_registry_first_frame_flags = &ResetSurfaceRegistryFirstFrameFlags;
    }
};
static SurfaceRegistryInitializer s_surface_registry_initializer;

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
    auto raw_elements = TakeObservedFrameElements();
    auto exact_text_elements = TakeExactTextFrameElements();
    auto exact_control_elements = TakeExactControlFrameElements();
    auto elements = FilterElementsToDominantSurface(raw_elements);
    std::vector<OverlayRenderElement> render_elements;
    const auto gameplay_health_bars =
        BuildGameplayParticipantHealthBarRenderItems(
            exact_text_elements);
    const auto gameplay_dampen_presentations =
        BuildGameplayDampenPresentationRenderItems(
            device,
            exact_text_elements);
    std::string gameplay_level_up_wait_text;
    (void)multiplayer::TryBuildLevelUpWaitStatusText(
        &gameplay_level_up_wait_text);
    if (gameplay_level_up_wait_text.empty()) {
        LogGameplayLevelUpWaitStatusDraw(
            {},
            GameplayLevelUpWaitDrawResult::Hidden);
    }
    std::string gameplay_death_spectator_text;
    (void)multiplayer::TryBuildDeathSpectatorStatusText(
        &gameplay_death_spectator_text);
    if (gameplay_death_spectator_text.empty()) {
        LogGameplayDeathSpectatorStatusDraw(
            {},
            GameplayDeathSpectatorDrawResult::Hidden);
    }

    const auto quick_panel_render_elements =
        TryBuildQuickPanelOverlayRenderElements(exact_text_elements, exact_control_elements);

    struct { const char* id; std::vector<OverlayRenderElement> elems; } built[] = {
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
    for (std::size_t i = 0; i < kSurfaceRegistrySize; ++i) {
        if (!built[i].elems.empty()) {
            higher_priority_surface_name = s_surface_registry[i].surface_id;
            break;
        }
    }

    if (dialog_snapshot.has_value() && higher_priority_surface_name[0] != '\0' &&
        std::strcmp(higher_priority_surface_name, "main_menu") != 0) {
        ClearTrackedDialogBecauseHigherPrioritySurfaceBecameDominant(higher_priority_surface_name);
        dialog_snapshot.reset();
    }

    if (dialog_snapshot.has_value()) {
        render_elements = BuildDialogOverlayRenderElements(*dialog_snapshot);
        elements.clear();
        std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
        g_debug_ui_overlay_state.settings_render.tracked_object_ptr = 0;
        if (!g_debug_ui_overlay_state.first_tracked_dialog_frame_logged) {
            g_debug_ui_overlay_state.first_tracked_dialog_frame_logged = true;
            Log(
                "Debug UI overlay rendered its first tracked dialog frame. left=" +
                std::to_string(dialog_snapshot->left) + " top=" + std::to_string(dialog_snapshot->top) +
                " width=" + std::to_string(dialog_snapshot->right - dialog_snapshot->left) + " height=" +
                std::to_string(dialog_snapshot->bottom - dialog_snapshot->top) + " buttons=" +
                std::to_string(dialog_snapshot->buttons.size()));
        }
    } else {
        for (std::size_t i = 0; i < kSurfaceRegistrySize; ++i) {
            if (built[i].elems.empty()) {
                continue;
            }

            render_elements = std::move(built[i].elems);
            elements.clear();
            auto& entry = s_surface_registry[i];

            std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
            if (entry.clear_main_menu_tracking) {
                g_debug_ui_overlay_state.tracked_title_main_menu_object = 0;
            }
            if (entry.clear_settings_tracking) {
                g_debug_ui_overlay_state.settings_render.tracked_object_ptr = 0;
            }
            if (!entry.first_frame_logged) {
                entry.first_frame_logged = true;
                Log(
                    "Debug UI overlay rendered its first " + std::string(entry.log_name) +
                    " frame. elements=" + std::to_string(render_elements.size()));
                if (entry.log_element_summary) {
                    LogOverlayRenderElementsSummary(entry.log_name, render_elements);
                }
            }
            break;
        }

        if (render_elements.empty() && !elements.empty()) {
            render_elements = BuildOverlayRenderElements(elements, g_debug_ui_overlay_state.font_atlas);
        }
    }

    bool diagnostic_visuals_enabled = false;
    const auto observed_surface_id = render_elements.empty()
        ? std::string{}
        : GetOverlaySurfaceRootId(
              render_elements.front().surface_id);
    ObserveMultiplayerJoinFlowSurface(observed_surface_id);
    {
        std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
        StoreLatestSurfaceSnapshotUnlocked(&g_debug_ui_overlay_state, render_elements);
        diagnostic_visuals_enabled =
            g_debug_ui_overlay_state.diagnostic_visuals_enabled;
    }

    const auto join_flow_presentation =
        GetMultiplayerJoinFlowPresentation();
    if (join_flow_presentation.visible) {
        IDirect3DStateBlock9* state_block = nullptr;
        if (SUCCEEDED(
                device->CreateStateBlock(
                    D3DSBT_ALL,
                    &state_block)) &&
            state_block != nullptr) {
            state_block->Capture();
        }

        ConfigureOverlayRenderState(device);
        DrawMultiplayerJoinFlowPresentation(
            device,
            join_flow_presentation);

        if (state_block != nullptr) {
            state_block->Apply();
            state_block->Release();
        }
        return;
    }

    if (!diagnostic_visuals_enabled) {
        render_elements.clear();
    }

    if (render_elements.empty() && gameplay_health_bars.empty() &&
        gameplay_dampen_presentations.empty() &&
        gameplay_level_up_wait_text.empty() &&
        gameplay_death_spectator_text.empty()) {
        return;
    }

    IDirect3DStateBlock9* state_block = nullptr;
    if (SUCCEEDED(device->CreateStateBlock(D3DSBT_ALL, &state_block)) && state_block != nullptr) {
        state_block->Capture();
    }

    ConfigureOverlayRenderState(device);

    for (const auto& element : render_elements) {
        DrawObservedOverlayElement(device, g_debug_ui_overlay_state.font_atlas, element);
    }
    for (const auto& health_bar : gameplay_health_bars) {
        const auto draw_result =
            DrawGameplayParticipantHealthBar(device, health_bar);
        LogGameplayParticipantHealthBarDraw(health_bar, draw_result);
    }
    for (const auto& presentation : gameplay_dampen_presentations) {
        const bool drawn =
            DrawGameplayDampenPresentation(device, presentation);
        LogGameplayDampenPresentationDraw(presentation, drawn);
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
    if (!gameplay_death_spectator_text.empty()) {
        const auto draw_result = DrawGameplayDeathSpectatorStatus(
            device,
            g_debug_ui_overlay_state.font_atlas,
            gameplay_death_spectator_text);
        LogGameplayDeathSpectatorStatusDraw(
            gameplay_death_spectator_text,
            draw_result);
    }

    if (!g_debug_ui_overlay_state.first_frame_logged) {
        g_debug_ui_overlay_state.first_frame_logged = true;
        Log(
            "Debug UI overlay observed " + std::to_string(elements.size()) + " raw UI draw candidate(s) and rendered " +
            std::to_string(render_elements.size()) + " element overlay region(s) plus " +
            std::to_string(gameplay_health_bars.size()) +
            " gameplay participant health bar(s) and " +
            std::to_string(gameplay_dampen_presentations.size()) +
            " Dampen presentation(s) on the first rendered frame.");
    }

    if (state_block != nullptr) {
        state_block->Apply();
        state_block->Release();
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
