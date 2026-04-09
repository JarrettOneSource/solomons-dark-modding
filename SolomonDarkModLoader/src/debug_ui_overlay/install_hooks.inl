bool InstallTextDrawHook(const DebugUiOverlayConfig& config, std::string* error_message) {
    const auto helper_address = ProcessMemory::Instance().ResolveGameAddressOrZero(config.text_draw_helper);
    if (helper_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the configured text draw helper address.";
        }
        return false;
    }

    if (!InstallX86Hook(
            reinterpret_cast<void*>(helper_address),
            reinterpret_cast<void*>(&HookTextDrawHelper),
            kTextDrawHookPatchSize,
            &g_debug_ui_overlay_state.text_draw_hook,
            error_message)) {
        return false;
    }

    return GetX86HookTrampoline<TextDrawHelperFn>(g_debug_ui_overlay_state.text_draw_hook) != nullptr;
}

bool InstallStringAssignHook(const DebugUiOverlayConfig& config, std::string* error_message) {
    const auto helper_address = ProcessMemory::Instance().ResolveGameAddressOrZero(config.string_assign_helper);
    if (helper_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the configured string assignment helper address.";
        }
        return false;
    }

    if (!InstallX86Hook(
            reinterpret_cast<void*>(helper_address),
            reinterpret_cast<void*>(&HookStringAssignHelper),
            kStringAssignHookPatchSize,
            &g_debug_ui_overlay_state.string_assign_hook,
            error_message)) {
        return false;
    }

    return GetX86HookTrampoline<StringAssignHelperFn>(g_debug_ui_overlay_state.string_assign_hook) != nullptr;
}

bool InstallDialogAddLineHook(const DebugUiOverlayConfig& config, std::string* error_message) {
    const auto helper_address = ProcessMemory::Instance().ResolveGameAddressOrZero(config.dialog_add_line_helper);
    if (helper_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the configured dialog add-line helper address.";
        }
        return false;
    }

    if (!InstallX86Hook(
            reinterpret_cast<void*>(helper_address),
            reinterpret_cast<void*>(&HookDialogAddLineHelper),
            kDialogAddLineHookPatchSize,
            &g_debug_ui_overlay_state.dialog_add_line_hook,
            error_message)) {
        return false;
    }

    return GetX86HookTrampoline<DialogAddLineHelperFn>(g_debug_ui_overlay_state.dialog_add_line_hook) != nullptr;
}

bool InstallDialogPrimaryButtonHook(const DebugUiOverlayConfig& config, std::string* error_message) {
    const auto helper_address = ProcessMemory::Instance().ResolveGameAddressOrZero(config.dialog_primary_button_helper);
    if (helper_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the configured dialog primary-button helper address.";
        }
        return false;
    }

    if (!InstallX86Hook(
            reinterpret_cast<void*>(helper_address),
            reinterpret_cast<void*>(&HookDialogPrimaryButtonHelper),
            kDialogButtonHookPatchSize,
            &g_debug_ui_overlay_state.dialog_primary_button_hook,
            error_message)) {
        return false;
    }

    return GetX86HookTrampoline<DialogButtonHelperFn>(g_debug_ui_overlay_state.dialog_primary_button_hook) != nullptr;
}

bool InstallDialogSecondaryButtonHook(const DebugUiOverlayConfig& config, std::string* error_message) {
    const auto helper_address = ProcessMemory::Instance().ResolveGameAddressOrZero(config.dialog_secondary_button_helper);
    if (helper_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the configured dialog secondary-button helper address.";
        }
        return false;
    }

    if (!InstallX86Hook(
            reinterpret_cast<void*>(helper_address),
            reinterpret_cast<void*>(&HookDialogSecondaryButtonHelper),
            kDialogButtonHookPatchSize,
            &g_debug_ui_overlay_state.dialog_secondary_button_hook,
            error_message)) {
        return false;
    }

    return GetX86HookTrampoline<DialogButtonHelperFn>(g_debug_ui_overlay_state.dialog_secondary_button_hook) != nullptr;
}

bool InstallDialogFinalizeHook(const DebugUiOverlayConfig& config, std::string* error_message) {
    const auto helper_address = ProcessMemory::Instance().ResolveGameAddressOrZero(config.dialog_finalize_helper);
    if (helper_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the configured dialog finalize helper address.";
        }
        return false;
    }

    if (!InstallX86Hook(
            reinterpret_cast<void*>(helper_address),
            reinterpret_cast<void*>(&HookDialogFinalizeHelper),
            kDialogFinalizeHookPatchSize,
            &g_debug_ui_overlay_state.dialog_finalize_hook,
            error_message)) {
        return false;
    }

    return GetX86HookTrampoline<DialogFinalizeHelperFn>(g_debug_ui_overlay_state.dialog_finalize_hook) != nullptr;
}

bool InstallExactTextRenderHook(const DebugUiOverlayConfig& config, std::string* error_message) {
    const auto helper_address = ProcessMemory::Instance().ResolveGameAddressOrZero(config.exact_text_render_helper);
    if (helper_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the configured exact text render helper address.";
        }
        return false;
    }

    if (!InstallX86Hook(
            reinterpret_cast<void*>(helper_address),
            reinterpret_cast<void*>(&HookExactTextRender),
            kExactTextRenderHookPatchSize,
            &g_debug_ui_overlay_state.exact_text_render_hook,
            error_message)) {
        return false;
    }

    return GetX86HookTrampoline<ExactTextRenderFn>(g_debug_ui_overlay_state.exact_text_render_hook) != nullptr;
}

bool InstallDarkCloudBrowserExactTextRenderHook(const DebugUiOverlayConfig& config, std::string* error_message) {
    const auto helper_address =
        ProcessMemory::Instance().ResolveGameAddressOrZero(config.dark_cloud_browser_exact_text_render_helper);
    if (helper_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the configured Dark Cloud browser exact text render helper address.";
        }
        return false;
    }

    if (!InstallX86Hook(
            reinterpret_cast<void*>(helper_address),
            reinterpret_cast<void*>(&HookDarkCloudBrowserExactTextRender),
            kExactTextRenderHookPatchSize,
            &g_debug_ui_overlay_state.dark_cloud_browser_exact_text_render_hook,
            error_message)) {
        return false;
    }

    return GetX86HookTrampoline<ExactTextRenderFn>(g_debug_ui_overlay_state.dark_cloud_browser_exact_text_render_hook) !=
           nullptr;
}

bool InstallGlyphDrawHook(const DebugUiOverlayConfig& config, std::string* error_message) {
    const auto helper_address = ProcessMemory::Instance().ResolveGameAddressOrZero(config.glyph_draw_helper);
    if (helper_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the configured glyph draw helper address.";
        }
        return false;
    }

    if (!InstallX86Hook(
            reinterpret_cast<void*>(helper_address),
            reinterpret_cast<void*>(&HookGlyphDrawHelper),
            kGlyphDrawHookPatchSize,
            &g_debug_ui_overlay_state.glyph_draw_hook,
            error_message)) {
        return false;
    }

    return GetX86HookTrampoline<GlyphDrawHelperFn>(g_debug_ui_overlay_state.glyph_draw_hook) != nullptr;
}

bool InstallTextQuadDrawHook(const DebugUiOverlayConfig& config, std::string* error_message) {
    const auto helper_address = ProcessMemory::Instance().ResolveGameAddressOrZero(config.text_quad_draw_helper);
    if (helper_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the configured text quad draw helper address.";
        }
        return false;
    }

    if (!InstallX86Hook(
            reinterpret_cast<void*>(helper_address),
            reinterpret_cast<void*>(&HookTextQuadDrawHelper),
            kGlyphDrawHookPatchSize,
            &g_debug_ui_overlay_state.text_quad_draw_hook,
            error_message)) {
        return false;
    }

    return GetX86HookTrampoline<TextQuadDrawHelperFn>(g_debug_ui_overlay_state.text_quad_draw_hook) != nullptr;
}

bool InstallDarkCloudBrowserRenderHook(const DebugUiOverlayConfig& config, std::string* error_message) {
    const auto helper_address = ProcessMemory::Instance().ResolveGameAddressOrZero(config.dark_cloud_browser_render_helper);
    if (helper_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the configured Dark Cloud browser render helper address.";
        }
        return false;
    }

    if (!InstallX86Hook(
            reinterpret_cast<void*>(helper_address),
            reinterpret_cast<void*>(&HookDarkCloudBrowserRenderHelper),
            kSurfaceRenderHookPatchSize,
            &g_debug_ui_overlay_state.dark_cloud_browser_render_hook,
            error_message)) {
        return false;
    }

    return GetX86HookTrampoline<SurfaceRenderHelperFn>(g_debug_ui_overlay_state.dark_cloud_browser_render_hook) != nullptr;
}

bool InstallSettingsRenderHook(const DebugUiOverlayConfig& config, std::string* error_message) {
    const auto helper_address = ProcessMemory::Instance().ResolveGameAddressOrZero(config.settings_render_helper);
    if (helper_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the configured settings render helper address.";
        }
        return false;
    }

    if (!InstallX86Hook(
            reinterpret_cast<void*>(helper_address),
            reinterpret_cast<void*>(&HookSettingsRenderHelper),
            kSettingsRenderHookPatchSize,
            &g_debug_ui_overlay_state.settings_render_hook,
            error_message)) {
        return false;
    }

    return GetX86HookTrampoline<SurfaceRenderHelperFn>(g_debug_ui_overlay_state.settings_render_hook) != nullptr;
}

bool InstallMyQuickPanelRenderHook(const DebugUiOverlayConfig& config, std::string* error_message) {
    const auto helper_address = ProcessMemory::Instance().ResolveGameAddressOrZero(config.myquick_panel_render_helper);
    if (helper_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the configured MyQuickCPanel render helper address.";
        }
        return false;
    }

    if (!InstallX86Hook(
            reinterpret_cast<void*>(helper_address),
            reinterpret_cast<void*>(&HookMyQuickPanelRenderHelper),
            kSurfaceRenderHookPatchSize,
            &g_debug_ui_overlay_state.myquick_panel_render_hook,
            error_message)) {
        return false;
    }

    return GetX86HookTrampoline<SurfaceRenderHelperFn>(g_debug_ui_overlay_state.myquick_panel_render_hook) != nullptr;
}

bool InstallMyQuickPanelModalLoopHook(const DebugUiOverlayConfig& config, std::string* error_message) {
    const auto helper_address = ProcessMemory::Instance().ResolveGameAddressOrZero(config.myquick_panel_modal_loop_helper);
    if (helper_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the configured MyQuickCPanel modal loop helper address.";
        }
        return false;
    }

    if (!InstallX86Hook(
            reinterpret_cast<void*>(helper_address),
            reinterpret_cast<void*>(&HookMyQuickPanelModalLoop),
            kMyQuickPanelModalLoopHookPatchSize,
            &g_debug_ui_overlay_state.myquick_panel_modal_loop_hook,
            error_message)) {
        return false;
    }

    return GetX86HookTrampoline<MyQuickPanelModalLoopFn>(g_debug_ui_overlay_state.myquick_panel_modal_loop_hook) !=
           nullptr;
}

bool InstallSimpleMenuModalLoopHook(const DebugUiOverlayConfig& config, std::string* error_message) {
    const auto helper_address = ProcessMemory::Instance().ResolveGameAddressOrZero(config.simple_menu_modal_loop_helper);
    if (helper_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the configured SimpleMenu modal loop helper address.";
        }
        return false;
    }

    if (!InstallX86Hook(
            reinterpret_cast<void*>(helper_address),
            reinterpret_cast<void*>(&HookSimpleMenuModalLoop),
            kSimpleMenuModalLoopHookPatchSize,
            &g_debug_ui_overlay_state.simple_menu_modal_loop_hook,
            error_message)) {
        return false;
    }

    return GetX86HookTrampoline<SimpleMenuModalLoopFn>(g_debug_ui_overlay_state.simple_menu_modal_loop_hook) != nullptr;
}

bool InstallSpellPickerRenderHook(const DebugUiOverlayConfig& config, std::string* error_message) {
    if (config.spell_picker_render_helper == 0) {
        return false;
    }

    const auto helper_address = ProcessMemory::Instance().ResolveGameAddressOrZero(config.spell_picker_render_helper);
    if (helper_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the configured spell picker render helper address.";
        }
        return false;
    }

    if (!InstallX86Hook(
            reinterpret_cast<void*>(helper_address),
            reinterpret_cast<void*>(&HookSpellPickerRenderHelper),
            kSpellPickerRenderHookPatchSize,
            &g_debug_ui_overlay_state.spell_picker_render_hook,
            error_message)) {
        return false;
    }

    return GetX86HookTrampoline<SurfaceRenderHelperFn>(g_debug_ui_overlay_state.spell_picker_render_hook) != nullptr;
}

bool InstallMainMenuRenderHook(const DebugUiOverlayConfig& config, std::string* error_message) {
    if (config.main_menu_render_helper == 0) {
        return false;
    }

    const auto helper_address = ProcessMemory::Instance().ResolveGameAddressOrZero(config.main_menu_render_helper);
    if (helper_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the configured main menu render helper address.";
        }
        return false;
    }

    if (!InstallX86Hook(
            reinterpret_cast<void*>(helper_address),
            reinterpret_cast<void*>(&HookMainMenuRenderHelper),
            kMainMenuRenderHookPatchSize,
            &g_debug_ui_overlay_state.main_menu_render_hook,
            error_message)) {
        return false;
    }

    return GetX86HookTrampoline<SurfaceRenderHelperFn>(g_debug_ui_overlay_state.main_menu_render_hook) != nullptr;
}

bool InstallHallOfFameRenderHook(const DebugUiOverlayConfig& config, std::string* error_message) {
    if (config.hall_of_fame_render_helper == 0) {
        return false;
    }

    const auto helper_address = ProcessMemory::Instance().ResolveGameAddressOrZero(config.hall_of_fame_render_helper);
    if (helper_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the configured Hall of Fame render helper address.";
        }
        return false;
    }

    if (!InstallX86Hook(
            reinterpret_cast<void*>(helper_address),
            reinterpret_cast<void*>(&HookHallOfFameRenderHelper),
            kHallOfFameRenderHookPatchSize,
            &g_debug_ui_overlay_state.hall_of_fame_render_hook,
            error_message)) {
        return false;
    }

    return GetX86HookTrampoline<SurfaceRenderHelperFn>(g_debug_ui_overlay_state.hall_of_fame_render_hook) != nullptr;
}

bool InstallUiLabeledControlRenderHook(const DebugUiOverlayConfig& config, std::string* error_message) {
    const auto helper_address = ProcessMemory::Instance().ResolveGameAddressOrZero(config.ui_labeled_control_render_helper);
    if (helper_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the configured labeled control render helper address.";
        }
        return false;
    }

    if (!InstallX86Hook(
            reinterpret_cast<void*>(helper_address),
            reinterpret_cast<void*>(&HookUiLabeledControlRender),
            kUiLabeledControlRenderHookPatchSize,
            &g_debug_ui_overlay_state.ui_labeled_control_render_hook,
            error_message)) {
        return false;
    }

    return GetX86HookTrampoline<UiLabeledControlRenderFn>(g_debug_ui_overlay_state.ui_labeled_control_render_hook) !=
           nullptr;
}

bool InstallUiLabeledControlAltRenderHook(const DebugUiOverlayConfig& config, std::string* error_message) {
    const auto helper_address =
        ProcessMemory::Instance().ResolveGameAddressOrZero(config.ui_labeled_control_alt_render_helper);
    if (helper_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the configured alternate labeled control render helper address.";
        }
        return false;
    }

    if (!InstallX86Hook(
            reinterpret_cast<void*>(helper_address),
            reinterpret_cast<void*>(&HookUiLabeledControlAltRender),
            kUiLabeledControlRenderHookPatchSize,
            &g_debug_ui_overlay_state.ui_labeled_control_alt_render_hook,
            error_message)) {
        return false;
    }

    return GetX86HookTrampoline<UiLabeledControlRenderFn>(g_debug_ui_overlay_state.ui_labeled_control_alt_render_hook) !=
           nullptr;
}

bool InstallUiUnlabeledControlRenderHook(const DebugUiOverlayConfig& config, std::string* error_message) {
    const auto helper_address =
        ProcessMemory::Instance().ResolveGameAddressOrZero(config.ui_unlabeled_control_render_helper);
    if (helper_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the configured unlabeled control render helper address.";
        }
        return false;
    }

    if (!InstallX86Hook(
            reinterpret_cast<void*>(helper_address),
            reinterpret_cast<void*>(&HookUiUnlabeledControlRender),
            kUiUnlabeledControlRenderHookPatchSize,
            &g_debug_ui_overlay_state.ui_unlabeled_control_render_hook,
            error_message)) {
        return false;
    }

    return GetX86HookTrampoline<UiUnlabeledControlRenderFn>(g_debug_ui_overlay_state.ui_unlabeled_control_render_hook) !=
           nullptr;
}

bool InstallUiPanelRenderHook(const DebugUiOverlayConfig& config, std::string* error_message) {
    const auto helper_address = ProcessMemory::Instance().ResolveGameAddressOrZero(config.ui_panel_render_helper);
    if (helper_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the configured panel render helper address.";
        }
        return false;
    }

    if (!InstallX86Hook(
            reinterpret_cast<void*>(helper_address),
            reinterpret_cast<void*>(&HookUiPanelRender),
            kUiPanelRenderHookPatchSize,
            &g_debug_ui_overlay_state.ui_panel_render_hook,
            error_message)) {
        return false;
    }

    return GetX86HookTrampoline<UiPanelRenderFn>(g_debug_ui_overlay_state.ui_panel_render_hook) != nullptr;
}

bool InstallUiRectDispatchHook(const DebugUiOverlayConfig& config, std::string* error_message) {
    const auto helper_address = ProcessMemory::Instance().ResolveGameAddressOrZero(config.ui_rect_dispatch_helper);
    if (helper_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the configured UI rect dispatch helper address.";
        }
        return false;
    }

    if (!InstallX86Hook(
            reinterpret_cast<void*>(helper_address),
            reinterpret_cast<void*>(&HookUiRectDispatch),
            kUiRectDispatchHookPatchSize,
            &g_debug_ui_overlay_state.ui_rect_dispatch_hook,
            error_message)) {
        return false;
    }

    return GetX86HookTrampoline<UiRectDispatchFn>(g_debug_ui_overlay_state.ui_rect_dispatch_hook) != nullptr;
}
