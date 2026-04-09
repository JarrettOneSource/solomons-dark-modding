bool InitializeDebugUiOverlay() {
    std::scoped_lock lock(g_debug_ui_overlay_state.mutex);

    if (g_debug_ui_overlay_state.initialized) {
        return true;
    }

    const auto* config = TryGetDebugUiOverlayConfig();
    const auto* binary_layout = TryGetBinaryLayout();
    if (config == nullptr || binary_layout == nullptr || !config->enabled) {
        return false;
    }

    ResetDebugUiOverlayStateUnlocked(&g_debug_ui_overlay_state);
    g_debug_ui_overlay_state.config = *config;
    g_debug_ui_overlay_state.surface_ranges = BuildSurfaceRanges(*binary_layout, config->surface_range_slop);
    g_debug_ui_overlay_state.frame_elements.reserve(config->max_tracked_elements_per_frame);
    g_debug_ui_overlay_state.frame_exact_text_elements.reserve(config->max_tracked_elements_per_frame);
    g_debug_ui_overlay_state.frame_exact_control_elements.reserve(config->max_tracked_elements_per_frame);
    g_debug_ui_overlay_state.active_exact_text_renders.reserve(16);
    g_debug_ui_overlay_state.object_label_cache.reserve(config->max_tracked_elements_per_frame);
    Log("Debug UI overlay: prepared " + std::to_string(g_debug_ui_overlay_state.surface_ranges.size()) + " observation range(s).");

    std::string hook_error;
    Log("Debug UI overlay: installing text draw hook.");
    if (!InstallTextDrawHook(g_debug_ui_overlay_state.config, &hook_error)) {
        Log("Debug UI overlay text draw hook failed. " + hook_error);
        ResetDebugUiOverlayStateUnlocked(&g_debug_ui_overlay_state);
        return false;
    }
    Log("Debug UI overlay: text draw hook installed.");

    Log("Debug UI overlay: installing string assignment hook.");
    if (!InstallStringAssignHook(g_debug_ui_overlay_state.config, &hook_error)) {
        Log("Debug UI overlay string assignment hook failed. " + hook_error);
        RemoveX86Hook(&g_debug_ui_overlay_state.text_draw_hook);
        ResetDebugUiOverlayStateUnlocked(&g_debug_ui_overlay_state);
        return false;
    }
    Log("Debug UI overlay: string assignment hook installed.");

    Log("Debug UI overlay: installing dialog add-line hook.");
    if (!InstallDialogAddLineHook(g_debug_ui_overlay_state.config, &hook_error)) {
        Log("Debug UI overlay dialog add-line hook failed. " + hook_error);
        RemoveX86Hook(&g_debug_ui_overlay_state.string_assign_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.text_draw_hook);
        ResetDebugUiOverlayStateUnlocked(&g_debug_ui_overlay_state);
        return false;
    }
    Log("Debug UI overlay: dialog add-line hook installed.");

    Log("Debug UI overlay: installing dialog primary-button hook.");
    if (!InstallDialogPrimaryButtonHook(g_debug_ui_overlay_state.config, &hook_error)) {
        Log("Debug UI overlay dialog primary-button hook failed. " + hook_error);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_add_line_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.string_assign_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.text_draw_hook);
        ResetDebugUiOverlayStateUnlocked(&g_debug_ui_overlay_state);
        return false;
    }
    Log("Debug UI overlay: dialog primary-button hook installed.");

    Log("Debug UI overlay: installing dialog secondary-button hook.");
    if (!InstallDialogSecondaryButtonHook(g_debug_ui_overlay_state.config, &hook_error)) {
        Log("Debug UI overlay dialog secondary-button hook failed. " + hook_error);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_primary_button_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_add_line_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.string_assign_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.text_draw_hook);
        ResetDebugUiOverlayStateUnlocked(&g_debug_ui_overlay_state);
        return false;
    }
    Log("Debug UI overlay: dialog secondary-button hook installed.");

    Log("Debug UI overlay: installing dialog finalize hook.");
    if (!InstallDialogFinalizeHook(g_debug_ui_overlay_state.config, &hook_error)) {
        Log("Debug UI overlay dialog finalize hook failed. " + hook_error);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_secondary_button_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_primary_button_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_add_line_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.string_assign_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.text_draw_hook);
        ResetDebugUiOverlayStateUnlocked(&g_debug_ui_overlay_state);
        return false;
    }
    Log("Debug UI overlay: dialog finalize hook installed.");

    Log("Debug UI overlay: installing exact text render hook.");
    if (!InstallExactTextRenderHook(g_debug_ui_overlay_state.config, &hook_error)) {
        Log("Debug UI overlay exact text render hook failed. " + hook_error);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_finalize_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_secondary_button_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_primary_button_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_add_line_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.string_assign_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.text_draw_hook);
        ResetDebugUiOverlayStateUnlocked(&g_debug_ui_overlay_state);
        return false;
    }
    Log("Debug UI overlay: exact text render hook installed.");

    Log("Debug UI overlay: installing Dark Cloud browser exact text render hook.");
    if (!InstallDarkCloudBrowserExactTextRenderHook(g_debug_ui_overlay_state.config, &hook_error)) {
        Log("Debug UI overlay Dark Cloud browser exact text render hook failed. " + hook_error);
        RemoveX86Hook(&g_debug_ui_overlay_state.exact_text_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_finalize_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_secondary_button_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_primary_button_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_add_line_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.string_assign_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.text_draw_hook);
        ResetDebugUiOverlayStateUnlocked(&g_debug_ui_overlay_state);
        return false;
    }
    Log("Debug UI overlay: Dark Cloud browser exact text render hook installed.");

    Log("Debug UI overlay: installing glyph draw hook.");
    if (!InstallGlyphDrawHook(g_debug_ui_overlay_state.config, &hook_error)) {
        Log("Debug UI overlay glyph draw hook failed. " + hook_error);
        RemoveX86Hook(&g_debug_ui_overlay_state.dark_cloud_browser_exact_text_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.exact_text_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_finalize_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_secondary_button_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_primary_button_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_add_line_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.string_assign_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.text_draw_hook);
        ResetDebugUiOverlayStateUnlocked(&g_debug_ui_overlay_state);
        return false;
    }
    Log("Debug UI overlay: glyph draw hook installed.");

    Log("Debug UI overlay: installing text quad draw hook.");
    if (!InstallTextQuadDrawHook(g_debug_ui_overlay_state.config, &hook_error)) {
        Log("Debug UI overlay text quad draw hook failed. " + hook_error);
        RemoveX86Hook(&g_debug_ui_overlay_state.glyph_draw_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dark_cloud_browser_exact_text_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.exact_text_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_finalize_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_secondary_button_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_primary_button_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_add_line_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.string_assign_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.text_draw_hook);
        ResetDebugUiOverlayStateUnlocked(&g_debug_ui_overlay_state);
        return false;
    }
    Log("Debug UI overlay: text quad draw hook installed.");

    Log("Debug UI overlay: installing Dark Cloud browser render hook.");
    if (!InstallDarkCloudBrowserRenderHook(g_debug_ui_overlay_state.config, &hook_error)) {
        Log("Debug UI overlay Dark Cloud browser render hook failed. " + hook_error);
        RemoveX86Hook(&g_debug_ui_overlay_state.text_quad_draw_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.glyph_draw_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dark_cloud_browser_exact_text_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.exact_text_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_finalize_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_secondary_button_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_primary_button_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_add_line_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.string_assign_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.text_draw_hook);
        ResetDebugUiOverlayStateUnlocked(&g_debug_ui_overlay_state);
        return false;
    }
    Log("Debug UI overlay: Dark Cloud browser render hook installed.");

    if (g_debug_ui_overlay_state.config.spell_picker_render_helper != 0) {
        Log("Debug UI overlay: installing spell picker render hook.");
        if (InstallSpellPickerRenderHook(g_debug_ui_overlay_state.config, &hook_error)) {
            Log("Debug UI overlay: spell picker render hook installed.");
        } else {
            Log("Debug UI overlay: spell picker render hook failed (non-fatal). " + hook_error);
        }
    }

    if (g_debug_ui_overlay_state.config.main_menu_render_helper != 0) {
        Log("Debug UI overlay: installing main menu render hook.");
        if (InstallMainMenuRenderHook(g_debug_ui_overlay_state.config, &hook_error)) {
            Log("Debug UI overlay: main menu render hook installed.");
        } else {
            Log("Debug UI overlay: main menu render hook failed (non-fatal). " + hook_error);
        }
    }

    if (g_debug_ui_overlay_state.config.hall_of_fame_render_helper != 0) {
        Log("Debug UI overlay: installing Hall of Fame render hook.");
        if (InstallHallOfFameRenderHook(g_debug_ui_overlay_state.config, &hook_error)) {
            Log("Debug UI overlay: Hall of Fame render hook installed.");
        } else {
            Log("Debug UI overlay: Hall of Fame render hook failed (non-fatal). " + hook_error);
        }
    }

    Log("Debug UI overlay: installing settings render hook.");
    if (!InstallSettingsRenderHook(g_debug_ui_overlay_state.config, &hook_error)) {
        Log("Debug UI overlay settings render hook failed. " + hook_error);
        RemoveX86Hook(&g_debug_ui_overlay_state.spell_picker_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.main_menu_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.hall_of_fame_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dark_cloud_browser_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.text_quad_draw_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.glyph_draw_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dark_cloud_browser_exact_text_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.exact_text_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_finalize_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_secondary_button_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_primary_button_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_add_line_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.string_assign_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.text_draw_hook);
        ResetDebugUiOverlayStateUnlocked(&g_debug_ui_overlay_state);
        return false;
    }
    Log("Debug UI overlay: settings render hook installed.");

    Log("Debug UI overlay: installing MyQuickCPanel render hook.");
    if (!InstallMyQuickPanelRenderHook(g_debug_ui_overlay_state.config, &hook_error)) {
        Log("Debug UI overlay MyQuickCPanel render hook failed. " + hook_error);
        RemoveX86Hook(&g_debug_ui_overlay_state.settings_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.spell_picker_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.main_menu_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.hall_of_fame_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dark_cloud_browser_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.text_quad_draw_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.glyph_draw_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dark_cloud_browser_exact_text_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.exact_text_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_finalize_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_secondary_button_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_primary_button_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_add_line_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.string_assign_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.text_draw_hook);
        ResetDebugUiOverlayStateUnlocked(&g_debug_ui_overlay_state);
        return false;
    }
    Log("Debug UI overlay: MyQuickCPanel render hook installed.");

    Log("Debug UI overlay: installing MyQuickCPanel modal loop hook.");
    if (!InstallMyQuickPanelModalLoopHook(g_debug_ui_overlay_state.config, &hook_error)) {
        Log("Debug UI overlay MyQuickCPanel modal loop hook failed. " + hook_error);
        RemoveX86Hook(&g_debug_ui_overlay_state.myquick_panel_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.settings_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.spell_picker_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.main_menu_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.hall_of_fame_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dark_cloud_browser_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.text_quad_draw_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.glyph_draw_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dark_cloud_browser_exact_text_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.exact_text_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_finalize_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_secondary_button_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_primary_button_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_add_line_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.string_assign_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.text_draw_hook);
        ResetDebugUiOverlayStateUnlocked(&g_debug_ui_overlay_state);
        return false;
    }
    Log("Debug UI overlay: MyQuickCPanel modal loop hook installed.");

    Log("Debug UI overlay: installing SimpleMenu modal loop hook.");
    if (!InstallSimpleMenuModalLoopHook(g_debug_ui_overlay_state.config, &hook_error)) {
        Log("Debug UI overlay SimpleMenu modal loop hook failed. " + hook_error);
        RemoveX86Hook(&g_debug_ui_overlay_state.myquick_panel_modal_loop_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.myquick_panel_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.settings_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.spell_picker_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.main_menu_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.hall_of_fame_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dark_cloud_browser_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.text_quad_draw_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.glyph_draw_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dark_cloud_browser_exact_text_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.exact_text_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_finalize_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_secondary_button_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_primary_button_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_add_line_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.string_assign_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.text_draw_hook);
        ResetDebugUiOverlayStateUnlocked(&g_debug_ui_overlay_state);
        return false;
    }
    Log("Debug UI overlay: SimpleMenu modal loop hook installed.");

    Log("Debug UI overlay: installing labeled control render hook.");
    if (!InstallUiLabeledControlRenderHook(g_debug_ui_overlay_state.config, &hook_error)) {
        Log("Debug UI overlay labeled control render hook failed. " + hook_error);
        RemoveX86Hook(&g_debug_ui_overlay_state.simple_menu_modal_loop_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.myquick_panel_modal_loop_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.myquick_panel_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.settings_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.spell_picker_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.main_menu_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.hall_of_fame_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dark_cloud_browser_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.text_quad_draw_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.glyph_draw_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dark_cloud_browser_exact_text_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.exact_text_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_finalize_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_secondary_button_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_primary_button_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_add_line_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.string_assign_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.text_draw_hook);
        ResetDebugUiOverlayStateUnlocked(&g_debug_ui_overlay_state);
        return false;
    }
    Log("Debug UI overlay: labeled control render hook installed.");

    Log("Debug UI overlay: installing alternate labeled control render hook.");
    if (!InstallUiLabeledControlAltRenderHook(g_debug_ui_overlay_state.config, &hook_error)) {
        Log("Debug UI overlay alternate labeled control render hook failed. " + hook_error);
        RemoveX86Hook(&g_debug_ui_overlay_state.ui_labeled_control_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.simple_menu_modal_loop_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.myquick_panel_modal_loop_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.myquick_panel_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.settings_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.spell_picker_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.main_menu_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.hall_of_fame_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dark_cloud_browser_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.text_quad_draw_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.glyph_draw_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dark_cloud_browser_exact_text_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.exact_text_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_finalize_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_secondary_button_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_primary_button_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_add_line_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.string_assign_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.text_draw_hook);
        ResetDebugUiOverlayStateUnlocked(&g_debug_ui_overlay_state);
        return false;
    }
    Log("Debug UI overlay: alternate labeled control render hook installed.");

    Log("Debug UI overlay: installing unlabeled control render hook.");
    if (!InstallUiUnlabeledControlRenderHook(g_debug_ui_overlay_state.config, &hook_error)) {
        Log("Debug UI overlay unlabeled control render hook failed. " + hook_error);
        RemoveX86Hook(&g_debug_ui_overlay_state.ui_labeled_control_alt_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.ui_labeled_control_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.simple_menu_modal_loop_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.myquick_panel_modal_loop_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.myquick_panel_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.settings_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.spell_picker_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.main_menu_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.hall_of_fame_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dark_cloud_browser_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.text_quad_draw_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.glyph_draw_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dark_cloud_browser_exact_text_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.exact_text_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_finalize_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_secondary_button_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_primary_button_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_add_line_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.string_assign_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.text_draw_hook);
        ResetDebugUiOverlayStateUnlocked(&g_debug_ui_overlay_state);
        return false;
    }
    Log("Debug UI overlay: unlabeled control render hook installed.");

    Log("Debug UI overlay: installing panel render hook.");
    if (!InstallUiPanelRenderHook(g_debug_ui_overlay_state.config, &hook_error)) {
        Log("Debug UI overlay panel render hook failed. " + hook_error);
        RemoveX86Hook(&g_debug_ui_overlay_state.ui_unlabeled_control_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.ui_labeled_control_alt_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.ui_labeled_control_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.simple_menu_modal_loop_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.myquick_panel_modal_loop_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.myquick_panel_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.settings_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.spell_picker_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.main_menu_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.hall_of_fame_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dark_cloud_browser_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.text_quad_draw_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.glyph_draw_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dark_cloud_browser_exact_text_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.exact_text_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_finalize_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_secondary_button_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_primary_button_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_add_line_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.string_assign_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.text_draw_hook);
        ResetDebugUiOverlayStateUnlocked(&g_debug_ui_overlay_state);
        return false;
    }
    Log("Debug UI overlay: panel render hook installed.");

    Log("Debug UI overlay: installing UI rect dispatch hook.");
    if (!InstallUiRectDispatchHook(g_debug_ui_overlay_state.config, &hook_error)) {
        Log("Debug UI overlay UI rect dispatch hook failed. " + hook_error);
        RemoveX86Hook(&g_debug_ui_overlay_state.ui_panel_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.ui_unlabeled_control_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.ui_labeled_control_alt_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.ui_labeled_control_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.simple_menu_modal_loop_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.myquick_panel_modal_loop_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.myquick_panel_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.settings_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.spell_picker_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.main_menu_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.hall_of_fame_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dark_cloud_browser_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.text_quad_draw_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.glyph_draw_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dark_cloud_browser_exact_text_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.exact_text_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_finalize_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_secondary_button_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_primary_button_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_add_line_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.string_assign_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.text_draw_hook);
        ResetDebugUiOverlayStateUnlocked(&g_debug_ui_overlay_state);
        return false;
    }
    Log("Debug UI overlay: UI rect dispatch hook installed.");

    Log("Debug UI overlay: installing D3D9 frame hook.");
    if (!InstallD3d9FrameHook(g_debug_ui_overlay_state.config.device_pointer_global, &OnD3d9Frame, &hook_error)) {
        Log("Debug UI overlay D3D9 frame hook failed. " + hook_error);
        RemoveX86Hook(&g_debug_ui_overlay_state.ui_rect_dispatch_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.ui_panel_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.ui_unlabeled_control_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.ui_labeled_control_alt_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.ui_labeled_control_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.simple_menu_modal_loop_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.myquick_panel_modal_loop_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.myquick_panel_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.settings_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.spell_picker_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.main_menu_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.hall_of_fame_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dark_cloud_browser_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.text_quad_draw_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.glyph_draw_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dark_cloud_browser_exact_text_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.exact_text_render_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_finalize_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_secondary_button_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_primary_button_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.dialog_add_line_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.string_assign_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.text_draw_hook);
        ResetDebugUiOverlayStateUnlocked(&g_debug_ui_overlay_state);
        return false;
    }
    Log("Debug UI overlay: D3D9 frame hook installed.");

    g_debug_ui_overlay_state.initialized = true;
    Log("Debug UI overlay initialized.");
    Log("Debug UI text draw helper: " + HexString(config->text_draw_helper));
    Log("Debug UI string assignment helper: " + HexString(config->string_assign_helper));
    Log("Debug UI dialog add-line helper: " + HexString(config->dialog_add_line_helper));
    Log("Debug UI dialog primary-button helper: " + HexString(config->dialog_primary_button_helper));
    Log("Debug UI dialog secondary-button helper: " + HexString(config->dialog_secondary_button_helper));
    Log("Debug UI dialog finalize helper: " + HexString(config->dialog_finalize_helper));
    Log("Debug UI exact text render helper: " + HexString(config->exact_text_render_helper));
    Log(
        "Debug UI Dark Cloud browser exact text render helper: " +
        HexString(config->dark_cloud_browser_exact_text_render_helper));
    Log("Debug UI glyph draw helper: " + HexString(config->glyph_draw_helper));
    Log("Debug UI text quad draw helper: " + HexString(config->text_quad_draw_helper));
    Log("Debug UI Dark Cloud browser render helper: " + HexString(config->dark_cloud_browser_render_helper));
    Log("Debug UI Dark Cloud browser vftable: " + HexString(config->dark_cloud_browser_vftable));
    Log("Debug UI settings render helper: " + HexString(config->settings_render_helper));
    Log("Debug UI MyQuickCPanel render helper: " + HexString(config->myquick_panel_render_helper));
    Log("Debug UI MyQuickCPanel modal loop helper: " + HexString(config->myquick_panel_modal_loop_helper));
    Log("Debug UI rect dispatch helper: " + HexString(config->ui_rect_dispatch_helper));
    Log("Debug UI SimpleMenu modal loop helper: " + HexString(config->simple_menu_modal_loop_helper));
    Log("Debug UI labeled control render helper: " + HexString(config->ui_labeled_control_render_helper));
    Log(
        "Debug UI alternate labeled control render helper: " +
        HexString(config->ui_labeled_control_alt_render_helper));
    Log("Debug UI unlabeled control render helper: " + HexString(config->ui_unlabeled_control_render_helper));
    Log("Debug UI panel render helper: " + HexString(config->ui_panel_render_helper));
    Log("Debug UI device pointer global: " + HexString(config->device_pointer_global));
    Log("Debug UI render context global: " + HexString(config->ui_render_context_global));
    Log("Debug UI MainMenu vftable: " + HexString(config->title_main_menu_vftable));
    Log("Debug UI MyQuickCPanel vftable: " + HexString(config->myquick_panel_vftable));
    Log(
        "Debug UI MainMenu button layout: array=" + HexString(config->title_main_menu_button_array_offset) +
        " stride=" + HexString(config->title_main_menu_button_stride) +
        " count=" + std::to_string(config->title_main_menu_button_count) +
        " left=" + HexString(config->title_main_menu_button_left_offset) +
        " top=" + HexString(config->title_main_menu_button_top_offset) +
        " width=" + HexString(config->title_main_menu_button_width_offset) +
        " height=" + HexString(config->title_main_menu_button_height_offset) +
        " mode=" + HexString(config->title_main_menu_mode_offset));
    Log(
        "Debug UI MyQuickCPanel layout: left=" + HexString(config->myquick_panel_left_offset) +
        " top=" + HexString(config->myquick_panel_top_offset) + " width=" +
        HexString(config->myquick_panel_width_offset) + " height=" +
        HexString(config->myquick_panel_height_offset) + " owner=" +
        HexString(config->myquick_panel_builder_owner_offset) + " builder=" +
        HexString(config->myquick_panel_builder_offset) + " root=" +
        HexString(config->myquick_panel_builder_root_control_offset) + " begin=" +
        HexString(config->myquick_panel_builder_widget_entries_begin_offset) + " end=" +
        HexString(config->myquick_panel_builder_widget_entries_end_offset) + " stride=" +
        HexString(config->myquick_panel_builder_widget_entry_stride) + " primary=" +
        HexString(config->myquick_panel_builder_widget_entry_primary_offset) + " secondary=" +
        HexString(config->myquick_panel_builder_widget_entry_secondary_offset) + " parent=" +
        HexString(config->myquick_panel_widget_parent_offset));
    Log("Debug UI widget parent offset: " + HexString(config->ui_widget_parent_offset));
    Log(
        "Debug UI Dark Cloud browser control layout: left=" +
        HexString(config->dark_cloud_browser_control_left_offset) + " top=" +
        HexString(config->dark_cloud_browser_control_top_offset) + " width=" +
        HexString(config->dark_cloud_browser_control_width_offset) + " height=" +
        HexString(config->dark_cloud_browser_control_height_offset) + " textOwner=" +
        HexString(config->dark_cloud_browser_text_owner_offset) + " headerCaller=" +
        HexString(config->dark_cloud_browser_modal_header_text_caller) + " primary=" +
        HexString(config->dark_cloud_browser_primary_action_control_offset) + " secondary=" +
        HexString(config->dark_cloud_browser_secondary_action_control_offset) + " auxLeft=" +
        HexString(config->dark_cloud_browser_aux_left_control_offset) + " auxRight=" +
        HexString(config->dark_cloud_browser_aux_right_control_offset) + " recent=" +
        HexString(config->dark_cloud_browser_recent_tab_control_offset) + " online=" +
        HexString(config->dark_cloud_browser_online_levels_tab_control_offset) + " myLevels=" +
        HexString(config->dark_cloud_browser_my_levels_tab_control_offset) + " footer=" +
        HexString(config->dark_cloud_browser_footer_action_control_offset));
    Log(
        "Debug UI SimpleMenu layout: vftable=" + HexString(config->simple_menu_vftable) +
        " left=" + HexString(config->simple_menu_left_offset) + " top=" +
        HexString(config->simple_menu_top_offset) + " width=" +
        HexString(config->simple_menu_width_offset) + " height=" +
        HexString(config->simple_menu_height_offset) + " controlList=" +
        HexString(config->simple_menu_control_list_offset) + " controlCount=" +
        HexString(config->simple_menu_control_list_count_offset) + " controlEntries=" +
        HexString(config->simple_menu_control_list_entries_offset) + " controlLeft=" +
        HexString(config->simple_menu_control_left_offset) + " controlTop=" +
        HexString(config->simple_menu_control_top_offset) + " controlWidth=" +
        HexString(config->simple_menu_control_width_offset) + " controlHeight=" +
        HexString(config->simple_menu_control_height_offset));
    Log("Debug UI MsgBox vftable: " + HexString(config->msgbox_vftable));
    Log(
        "Debug UI MsgBox layout offsets: panelLeft=" + HexString(config->msgbox_panel_left_offset) +
        " panelTop=" + HexString(config->msgbox_panel_top_offset) +
        " panelWidth=" + HexString(config->msgbox_panel_width_offset) +
        " panelHeight=" + HexString(config->msgbox_panel_height_offset) +
        " primaryLeft=" + HexString(config->msgbox_primary_button_left_offset) +
        " primaryTop=" + HexString(config->msgbox_primary_button_top_offset) +
        " primaryWidth=" + HexString(config->msgbox_primary_button_width_offset) +
        " primaryHeight=" + HexString(config->msgbox_primary_button_height_offset) +
        " secondaryLeft=" + HexString(config->msgbox_secondary_button_left_offset) +
        " secondaryTop=" + HexString(config->msgbox_secondary_button_top_offset) +
        " secondaryHalfWidth=" + HexString(config->msgbox_secondary_button_half_width_offset) +
        " secondaryHalfHeight=" + HexString(config->msgbox_secondary_button_half_height_offset) +
        " primaryLabel=" +
        HexString(config->msgbox_primary_label_offset) + " secondaryLabel=" +
        HexString(config->msgbox_secondary_label_offset) + " lineList=" +
        HexString(config->msgbox_line_list_offset) + " lineCount=" +
        HexString(config->msgbox_line_list_count_offset) + " lineEntries=" +
        HexString(config->msgbox_line_list_entries_offset) + " lineWrapperObject=" +
        HexString(config->msgbox_line_wrapper_object_offset) + " lineHeight=" +
        HexString(config->msgbox_line_height_offset) + " contentLeftGlobal=" +
        HexString(config->msgbox_content_left_padding_global) + " contentTopGlobal=" +
        HexString(config->msgbox_content_top_padding_global));
    Log("Debug UI surface range slop: " + std::to_string(config->surface_range_slop) + " byte(s)");
    Log("Debug UI stack scan slots: " + std::to_string(config->stack_scan_slots));
    Log("Debug UI max tracked elements per frame: " + std::to_string(config->max_tracked_elements_per_frame));
    return true;
}
