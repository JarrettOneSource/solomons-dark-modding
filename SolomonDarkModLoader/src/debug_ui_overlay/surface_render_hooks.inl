void __fastcall HookSettingsRenderHelper(void* self, void* /*unused_edx*/) {
    {
        std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
        if (!g_debug_ui_overlay_state.first_settings_render_logged) {
            g_debug_ui_overlay_state.first_settings_render_logged = true;
            Log(
                "Debug UI overlay intercepted its first settings render call. object=" +
                HexString(reinterpret_cast<uintptr_t>(self)));
        }

        auto& tracked_settings = g_debug_ui_overlay_state.settings_render;
        ++tracked_settings.render_depth;
        tracked_settings.active_object_ptr = reinterpret_cast<uintptr_t>(self);
        tracked_settings.tracked_object_ptr = reinterpret_cast<uintptr_t>(self);
        tracked_settings.captured_at = GetTickCount64();
    }

    const auto original = GetX86HookTrampoline<SurfaceRenderHelperFn>(g_debug_ui_overlay_state.settings_render_hook);
    if (original != nullptr) {
        original(self);
    }

    std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
    auto& tracked_settings = g_debug_ui_overlay_state.settings_render;
    if (tracked_settings.render_depth > 0) {
        --tracked_settings.render_depth;
    }
    if (tracked_settings.render_depth == 0) {
        tracked_settings.active_object_ptr = 0;
    }
}

void __fastcall HookMyQuickPanelRenderHelper(void* self, void* /*unused_edx*/) {
    const auto* config = TryGetDebugUiOverlayConfig();
    auto is_quick_panel = false;
    if (config != nullptr && self != nullptr) {
        const auto resolved_vftable = ProcessMemory::Instance().ResolveGameAddressOrZero(config->myquick_panel_vftable);
        uintptr_t object_vftable = 0;
        is_quick_panel = resolved_vftable != 0 &&
                         TryReadPointerField(self, 0, &object_vftable) &&
                         object_vftable == resolved_vftable;
    }

    if (is_quick_panel) {
        std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
        if (!g_debug_ui_overlay_state.first_myquick_panel_render_logged) {
            g_debug_ui_overlay_state.first_myquick_panel_render_logged = true;
            Log(
                "Debug UI overlay intercepted its first MyQuickCPanel render call. object=" +
                HexString(reinterpret_cast<uintptr_t>(self)));
        }

        auto& tracked_panel = g_debug_ui_overlay_state.myquick_panel_render;
        ++tracked_panel.render_depth;
        tracked_panel.active_object_ptr = reinterpret_cast<uintptr_t>(self);
        tracked_panel.tracked_object_ptr = reinterpret_cast<uintptr_t>(self);
        tracked_panel.captured_at = GetTickCount64();
    }

    const auto original = GetX86HookTrampoline<SurfaceRenderHelperFn>(g_debug_ui_overlay_state.myquick_panel_render_hook);
    if (original != nullptr) {
        original(self);
    }

    if (!is_quick_panel) {
        return;
    }

    std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
    auto& tracked_panel = g_debug_ui_overlay_state.myquick_panel_render;
    if (tracked_panel.render_depth > 0) {
        --tracked_panel.render_depth;
    }
    if (tracked_panel.render_depth == 0) {
        tracked_panel.active_object_ptr = 0;
    }
}

int __fastcall HookMyQuickPanelModalLoop(void* self, void* /*unused_edx*/, void* arg2) {
    {
        std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
        if (!g_debug_ui_overlay_state.first_myquick_panel_modal_logged) {
            g_debug_ui_overlay_state.first_myquick_panel_modal_logged = true;
            Log(
                "Debug UI overlay intercepted its first MyQuickCPanel modal loop. object=" +
                HexString(reinterpret_cast<uintptr_t>(self)));
        }

        ++g_debug_ui_overlay_state.myquick_panel_modal.modal_depth;
        g_debug_ui_overlay_state.myquick_panel_modal.active_object_ptr = reinterpret_cast<uintptr_t>(self);
        g_debug_ui_overlay_state.myquick_panel_modal.captured_at = GetTickCount64();
        g_debug_ui_overlay_state.myquick_panel_render.tracked_object_ptr = reinterpret_cast<uintptr_t>(self);
        g_debug_ui_overlay_state.myquick_panel_render.captured_at =
            g_debug_ui_overlay_state.myquick_panel_modal.captured_at;
    }

    const auto original =
        GetX86HookTrampoline<MyQuickPanelModalLoopFn>(g_debug_ui_overlay_state.myquick_panel_modal_loop_hook);
    auto result = 0;
    if (original != nullptr) {
        result = original(self, arg2);
    }

    std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
    if (g_debug_ui_overlay_state.myquick_panel_modal.modal_depth > 0) {
        --g_debug_ui_overlay_state.myquick_panel_modal.modal_depth;
    }
    if (g_debug_ui_overlay_state.myquick_panel_modal.modal_depth == 0) {
        g_debug_ui_overlay_state.myquick_panel_modal.active_object_ptr = 0;
    }
    return result;
}

int __fastcall HookSimpleMenuModalLoop(
    void* self,
    void* /*unused_edx*/,
    uintptr_t arg2,
    uintptr_t arg3,
    uintptr_t arg4,
    uintptr_t arg5,
    uintptr_t arg6,
    uintptr_t arg7,
    uintptr_t arg8) {
    {
        std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
        if (!g_debug_ui_overlay_state.first_simple_menu_modal_logged) {
            g_debug_ui_overlay_state.first_simple_menu_modal_logged = true;
            Log(
                "Debug UI overlay intercepted its first SimpleMenu modal loop. object=" +
                HexString(reinterpret_cast<uintptr_t>(self)));
        }

        auto& simple_menu = g_debug_ui_overlay_state.simple_menu;
        const auto simple_menu_address = reinterpret_cast<uintptr_t>(self);
        if (simple_menu.active_object_ptr != simple_menu_address) {
            simple_menu.raw_definition.clear();
            simple_menu.semantic_surface_id.clear();
            simple_menu.semantic_surface_title.clear();
            simple_menu.entries.clear();
            simple_menu.definition_captured_at = 0;
        }

        ++simple_menu.modal_depth;
        simple_menu.active_object_ptr = simple_menu_address;
        simple_menu.captured_at = GetTickCount64();
        RefreshTrackedSimpleMenuDefinitionUnlocked(&simple_menu, simple_menu.captured_at);
    }

    const auto original = GetX86HookTrampoline<SimpleMenuModalLoopFn>(g_debug_ui_overlay_state.simple_menu_modal_loop_hook);
    auto result = 0;
    if (original != nullptr) {
        result = original(self, arg2, arg3, arg4, arg5, arg6, arg7, arg8);
    }

    std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
    auto& simple_menu = g_debug_ui_overlay_state.simple_menu;
    if (simple_menu.modal_depth > 0) {
        --simple_menu.modal_depth;
    }
    if (simple_menu.modal_depth == 0) {
        simple_menu.active_object_ptr = 0;
        simple_menu.raw_definition.clear();
        simple_menu.semantic_surface_id.clear();
        simple_menu.semantic_surface_title.clear();
        simple_menu.entries.clear();
        simple_menu.definition_captured_at = 0;
    }
    return result;
}

void __fastcall HookMainMenuRenderHelper(void* self, void* /*unused_edx*/) {
    const auto* config = TryGetDebugUiOverlayConfig();
    auto is_main_menu = false;
    if (config != nullptr && self != nullptr && config->title_main_menu_vftable != 0) {
        const auto resolved_vftable = ProcessMemory::Instance().ResolveGameAddressOrZero(config->title_main_menu_vftable);
        uintptr_t object_vftable = 0;
        is_main_menu = resolved_vftable != 0 &&
                       TryReadPointerField(self, 0, &object_vftable) &&
                       object_vftable == resolved_vftable;
    }

    if (is_main_menu) {
        std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
        if (!g_debug_ui_overlay_state.first_main_menu_render_logged) {
            g_debug_ui_overlay_state.first_main_menu_render_logged = true;
            Log(
                "Debug UI overlay intercepted its first main menu render call. object=" +
                HexString(reinterpret_cast<uintptr_t>(self)));
        }

        g_debug_ui_overlay_state.tracked_title_main_menu_object = reinterpret_cast<uintptr_t>(self);
    }

    const auto original = GetX86HookTrampoline<SurfaceRenderHelperFn>(g_debug_ui_overlay_state.main_menu_render_hook);
    if (original != nullptr) {
        original(self);
    }
}

void __fastcall HookSpellPickerRenderHelper(void* self, void* /*unused_edx*/) {
    const auto* config = TryGetDebugUiOverlayConfig();
    auto is_spell_picker = false;
    if (config != nullptr && self != nullptr && config->spell_picker_vftable != 0) {
        const auto resolved_vftable = ProcessMemory::Instance().ResolveGameAddressOrZero(config->spell_picker_vftable);
        uintptr_t object_vftable = 0;
        is_spell_picker = resolved_vftable != 0 &&
                          TryReadPointerField(self, 0, &object_vftable) &&
                          object_vftable == resolved_vftable;
    }

    if (is_spell_picker) {
        std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
        if (!g_debug_ui_overlay_state.first_spell_picker_render_logged) {
            g_debug_ui_overlay_state.first_spell_picker_render_logged = true;
            Log(
                "Debug UI overlay intercepted its first spell picker render call. object=" +
                HexString(reinterpret_cast<uintptr_t>(self)));
        }

        auto& tracked = g_debug_ui_overlay_state.spell_picker_render;
        ++tracked.render_depth;
        tracked.active_object_ptr = reinterpret_cast<uintptr_t>(self);
        tracked.tracked_object_ptr = reinterpret_cast<uintptr_t>(self);
        tracked.captured_at = GetTickCount64();
    }

    const auto original = GetX86HookTrampoline<SurfaceRenderHelperFn>(g_debug_ui_overlay_state.spell_picker_render_hook);
    if (original != nullptr) {
        original(self);
    }

    if (!is_spell_picker) {
        return;
    }

    std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
    auto& tracked = g_debug_ui_overlay_state.spell_picker_render;
    if (tracked.render_depth > 0) {
        --tracked.render_depth;
    }
    if (tracked.render_depth == 0) {
        tracked.active_object_ptr = 0;
    }
}

void __fastcall HookHallOfFameRenderHelper(void* self, void* /*unused_edx*/) {
    const auto* config = TryGetDebugUiOverlayConfig();
    auto is_hall_of_fame = false;
    if (config != nullptr && self != nullptr && config->hall_of_fame_vftable != 0) {
        const auto resolved_vftable = ProcessMemory::Instance().ResolveGameAddressOrZero(config->hall_of_fame_vftable);
        uintptr_t object_vftable = 0;
        is_hall_of_fame = resolved_vftable != 0 &&
                          TryReadPointerField(self, 0, &object_vftable) &&
                          object_vftable == resolved_vftable;
    }

    if (is_hall_of_fame) {
        std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
        if (!g_debug_ui_overlay_state.first_hall_of_fame_render_logged) {
            g_debug_ui_overlay_state.first_hall_of_fame_render_logged = true;
            Log(
                "Debug UI overlay intercepted its first Hall of Fame render call. object=" +
                HexString(reinterpret_cast<uintptr_t>(self)));
        }

        auto& tracked_hof = g_debug_ui_overlay_state.hall_of_fame_render;
        ++tracked_hof.render_depth;
        tracked_hof.active_object_ptr = reinterpret_cast<uintptr_t>(self);
        tracked_hof.tracked_object_ptr = reinterpret_cast<uintptr_t>(self);
        tracked_hof.captured_at = GetTickCount64();
    }

    const auto original = GetX86HookTrampoline<SurfaceRenderHelperFn>(g_debug_ui_overlay_state.hall_of_fame_render_hook);
    if (original != nullptr) {
        original(self);
    }

    if (!is_hall_of_fame) {
        return;
    }

    std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
    auto& tracked_hof = g_debug_ui_overlay_state.hall_of_fame_render;
    if (tracked_hof.render_depth > 0) {
        --tracked_hof.render_depth;
    }
    if (tracked_hof.render_depth == 0) {
        tracked_hof.active_object_ptr = 0;
    }
}

void __cdecl HookUiLabeledControlRender(
    void* self,
    void* arg2,
    char* text,
    uintptr_t arg4,
    int* arg5,
    uintptr_t arg6,
    uintptr_t arg7,
    uintptr_t arg8,
    float arg9) {
    const auto caller_address = reinterpret_cast<uintptr_t>(_ReturnAddress());
    static bool s_logged_labeled_control_hook = false;
    if (!s_logged_labeled_control_hook) {
        s_logged_labeled_control_hook = true;
        Log(
            "Debug UI overlay entered the labeled control render hook. caller=" + HexString(caller_address) +
            " control=" + HexString(reinterpret_cast<uintptr_t>(self)));
    }
    const auto resolved_label = ResolveExactTextRenderLabel(arg2, text);
    CacheObservedObjectLabel(reinterpret_cast<uintptr_t>(self), resolved_label);
    ObserveControlRenderForAllSurfaces(self, caller_address, resolved_label);

    const auto original =
        GetX86HookTrampoline<UiLabeledControlRenderFn>(g_debug_ui_overlay_state.ui_labeled_control_render_hook);
    if (original != nullptr) {
        original(self, arg2, text, arg4, arg5, arg6, arg7, arg8, arg9);
    }
}

void __cdecl HookUiLabeledControlAltRender(
    void* self,
    void* arg2,
    char* text,
    uintptr_t arg4,
    int* arg5,
    uintptr_t arg6,
    uintptr_t arg7,
    uintptr_t arg8,
    float arg9) {
    const auto caller_address = reinterpret_cast<uintptr_t>(_ReturnAddress());
    static bool s_logged_alt_labeled_control_hook = false;
    if (!s_logged_alt_labeled_control_hook) {
        s_logged_alt_labeled_control_hook = true;
        Log(
            "Debug UI overlay entered the alternate labeled control render hook. caller=" +
            HexString(caller_address) + " control=" + HexString(reinterpret_cast<uintptr_t>(self)));
    }
    const auto resolved_label = ResolveExactTextRenderLabel(arg2, text);
    CacheObservedObjectLabel(reinterpret_cast<uintptr_t>(self), resolved_label);
    ObserveControlRenderForAllSurfaces(self, caller_address, resolved_label);

    const auto original =
        GetX86HookTrampoline<UiLabeledControlRenderFn>(g_debug_ui_overlay_state.ui_labeled_control_alt_render_hook);
    if (original != nullptr) {
        original(self, arg2, text, arg4, arg5, arg6, arg7, arg8, arg9);
    }
}

void __cdecl HookUiUnlabeledControlRender(void* self, int arg2, int arg3) {
    const auto caller_address = reinterpret_cast<uintptr_t>(_ReturnAddress());
    static bool s_logged_unlabeled_control_hook = false;
    if (!s_logged_unlabeled_control_hook) {
        s_logged_unlabeled_control_hook = true;
        Log(
            "Debug UI overlay entered the unlabeled control render hook. caller=" +
            HexString(caller_address) + " control=" + HexString(reinterpret_cast<uintptr_t>(self)));
    }
    ObserveControlRenderForAllSurfaces(self, caller_address, {});

    const auto original =
        GetX86HookTrampoline<UiUnlabeledControlRenderFn>(g_debug_ui_overlay_state.ui_unlabeled_control_render_hook);
    if (original != nullptr) {
        original(self, arg2, arg3);
    }
}

void __cdecl HookUiPanelRender(float arg1, float arg2, float arg3, float arg4, float arg5) {
    const auto caller_address = reinterpret_cast<uintptr_t>(_ReturnAddress());
    static bool s_logged_panel_hook = false;
    if (!s_logged_panel_hook) {
        s_logged_panel_hook = true;
        Log(
            "Debug UI overlay entered the panel render hook. caller=" + HexString(caller_address) +
            " left=" + std::to_string(arg1) + " top=" + std::to_string(arg2) + " right=" +
            std::to_string(arg3) + " bottom=" + std::to_string(arg4));
    }
    static int s_settings_panel_logs_remaining = 32;
    uintptr_t settings_address = 0;
    if (s_settings_panel_logs_remaining > 0 && TryGetActiveSettingsRender(&settings_address) && settings_address != 0) {
        --s_settings_panel_logs_remaining;
        Log(
            "Debug UI settings panel render: caller=" + HexString(caller_address) + " left=" +
            std::to_string(arg1) + " top=" + std::to_string(arg2) + " right=" + std::to_string(arg3) +
            " bottom=" + std::to_string(arg4) + " settings=" + HexString(settings_address));
    }
    ObserveDarkCloudBrowserPanelRender(caller_address, arg1, arg2, arg3, arg4);
    ObserveSettingsPanelRender(caller_address, arg1, arg2, arg3, arg4);

    const auto original = GetX86HookTrampoline<UiPanelRenderFn>(g_debug_ui_overlay_state.ui_panel_render_hook);
    if (original != nullptr) {
        original(arg1, arg2, arg3, arg4, arg5);
    }
}

void __fastcall HookUiRectDispatch(void* self, void* /*unused_edx*/, float arg2, float arg3, float arg4, float arg5) {
    const auto caller_address = reinterpret_cast<uintptr_t>(_ReturnAddress());
    ObserveDarkCloudBrowserRectDispatch(self, caller_address, arg2, arg3, arg4, arg5);
    ObserveSettingsRectDispatch(self, caller_address, arg2, arg3, arg4, arg5);
    ObserveSimpleMenuRectDispatch(self, caller_address, arg2, arg3, arg4, arg5);
    ObserveQuickPanelRectDispatch(self, caller_address, arg2, arg3, arg4, arg5);

    const auto original = GetX86HookTrampoline<UiRectDispatchFn>(g_debug_ui_overlay_state.ui_rect_dispatch_hook);
    if (original != nullptr) {
        original(self, arg2, arg3, arg4, arg5);
    }
}

void __fastcall HookTextDrawHelper(
    void* render_context,
    void* /*unused_edx*/,
    float x,
    float y,
    std::uint32_t arg3,
    std::uint32_t arg4) {
    const auto caller_address = reinterpret_cast<uintptr_t>(_ReturnAddress());
    const auto widget_pointer = CaptureCallerWidgetPointer();
    {
        std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
        if (!g_debug_ui_overlay_state.first_text_draw_call_logged) {
            g_debug_ui_overlay_state.first_text_draw_call_logged = true;
            Log(
                "Debug UI overlay intercepted its first configured text draw helper call. caller=" +
                HexString(caller_address));
        }
    }

    const auto surface_match = TryResolveSurfaceForDrawCall(caller_address, g_debug_ui_overlay_state.config.stack_scan_slots);
    const auto identity_pointer =
        widget_pointer != 0 ? reinterpret_cast<void*>(widget_pointer) : nullptr;
    const auto label_source_pointer =
        widget_pointer != 0 ? reinterpret_cast<void*>(widget_pointer) : render_context;
    if (surface_match.has_value()) {
        if (surface_match->range != nullptr && surface_match->range->surface_id == "main_menu") {
            std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
            if (g_debug_ui_overlay_state.tracked_title_main_menu_object == 0) {
                const auto resolved_main_menu_vftable =
                    ProcessMemory::Instance().ResolveGameAddressOrZero(g_debug_ui_overlay_state.config.title_main_menu_vftable);
                if (resolved_main_menu_vftable != 0) {
#if defined(_MSC_VER) && defined(_M_IX86)
                    const auto* stack_cursor = reinterpret_cast<const uintptr_t*>(_AddressOfReturnAddress());
                    constexpr std::size_t kMainMenuStackScanSlots = 32;
                    for (std::size_t slot = 0; slot < kMainMenuStackScanSlots && stack_cursor != nullptr; ++slot) {
                        const auto candidate = stack_cursor[slot];
                        if (candidate < 0x10000 || candidate > 0x7FFFFFFF) {
                            continue;
                        }
                        uintptr_t candidate_vftable = 0;
                        if (TryReadPointerField(reinterpret_cast<const void*>(candidate), 0, &candidate_vftable) &&
                            candidate_vftable == resolved_main_menu_vftable) {
                            g_debug_ui_overlay_state.tracked_title_main_menu_object = candidate;
                            static bool s_logged = false;
                            if (!s_logged) {
                                s_logged = true;
                                Log(
                                    "Debug UI overlay tracked MainMenu object via stack scan: " + HexString(candidate) +
                                    " slot=" + std::to_string(slot));
                            }
                            break;
                        }
                    }
#endif
                }
            }
        }

        (void)ObserveUiDrawCall(*surface_match, identity_pointer, label_source_pointer, x, y, caller_address);
    }

    const auto original = GetX86HookTrampoline<TextDrawHelperFn>(g_debug_ui_overlay_state.text_draw_hook);
    if (original != nullptr) {
        const auto normalized_caller_address = NormalizeObservedCodeAddress(caller_address);
        constexpr uintptr_t kGameplayHudAllyBarTextDrawReturnAddress = 0x0060CBCE;
        if (normalized_caller_address == kGameplayHudAllyBarTextDrawReturnAddress) {
            const auto label = ResolveExactTextRenderLabel(render_context, nullptr);
            std::string replacement_label;
            uintptr_t actor_address = 0;
            const auto string_assign =
                GetX86HookTrampoline<StringAssignHelperFn>(g_debug_ui_overlay_state.string_assign_hook);
            if (IsGameplayHudParticipantFallbackLabel(label) &&
                TryGetActiveGameplayHudParticipantDisplayName(&replacement_label, &actor_address) &&
                !replacement_label.empty() &&
                string_assign != nullptr) {
                string_assign(render_context, const_cast<char*>(replacement_label.c_str()));
                original(render_context, x, y, arg3, arg4);
                string_assign(render_context, const_cast<char*>(label.c_str()));

                static int s_native_ally_label_override_logs_remaining = 8;
                if (s_native_ally_label_override_logs_remaining > 0) {
                    --s_native_ally_label_override_logs_remaining;
                    Log(
                        "[bots] native gameplay HUD ally label override. actor=" +
                        HexString(actor_address) +
                        " old=" + SanitizeDebugLogLabel(label) +
                        " new=" + SanitizeDebugLogLabel(replacement_label) +
                        " caller=" + HexString(normalized_caller_address));
                }
                return;
            }

            static int s_native_ally_label_skip_logs_remaining = 4;
            if (s_native_ally_label_skip_logs_remaining > 0 && !label.empty()) {
                --s_native_ally_label_skip_logs_remaining;
                Log(
                    "[bots] native gameplay HUD ally label draw left unchanged. label=" +
                    SanitizeDebugLogLabel(label) +
                    " caller=" + HexString(normalized_caller_address));
            }
        }
        original(render_context, x, y, arg3, arg4);
    }
}

void __fastcall HookStringAssignHelper(void* string_object, void* /*unused_edx*/, char* text) {
    if (text != nullptr) {
        PushRecentAssignedString(text);
    }

    const auto original = GetX86HookTrampoline<StringAssignHelperFn>(g_debug_ui_overlay_state.string_assign_hook);
    if (original != nullptr) {
        original(string_object, text);
    }
}

void __fastcall HookDialogAddLineHelper(
    void* dialog_object,
    void* /*unused_edx*/,
    uintptr_t arg2,
    uintptr_t arg3,
    uintptr_t arg4,
    uintptr_t arg5,
    uintptr_t arg6,
    std::uint32_t arg7,
    std::uint32_t arg8,
    std::uint32_t arg9,
    std::uint32_t arg10,
    std::uint32_t arg11,
    uintptr_t arg12,
    float arg13,
    uintptr_t arg14) {
    const auto original = GetX86HookTrampoline<DialogAddLineHelperFn>(g_debug_ui_overlay_state.dialog_add_line_hook);
    if (original != nullptr) {
        original(dialog_object, arg2, arg3, arg4, arg5, arg6, arg7, arg8, arg9, arg10, arg11, arg12, arg13, arg14);
    }

    const auto caller_address = reinterpret_cast<uintptr_t>(_ReturnAddress());
    TrackDialogLine(dialog_object, caller_address);
}

void __fastcall HookDialogPrimaryButtonHelper(
    void* dialog_object,
    void* /*unused_edx*/,
    uintptr_t arg2,
    uintptr_t arg3,
    uintptr_t arg4,
    uintptr_t arg5,
    uintptr_t arg6,
    uintptr_t arg7,
    uintptr_t arg8) {
    const auto original =
        GetX86HookTrampoline<DialogButtonHelperFn>(g_debug_ui_overlay_state.dialog_primary_button_hook);
    if (original != nullptr) {
        original(dialog_object, arg2, arg3, arg4, arg5, arg6, arg7, arg8);
    }

    const auto caller_address = reinterpret_cast<uintptr_t>(_ReturnAddress());
    TrackDialogButton(dialog_object, true, caller_address);
}

void __fastcall HookDialogSecondaryButtonHelper(
    void* dialog_object,
    void* /*unused_edx*/,
    uintptr_t arg2,
    uintptr_t arg3,
    uintptr_t arg4,
    uintptr_t arg5,
    uintptr_t arg6,
    uintptr_t arg7,
    uintptr_t arg8) {
    const auto original =
        GetX86HookTrampoline<DialogButtonHelperFn>(g_debug_ui_overlay_state.dialog_secondary_button_hook);
    if (original != nullptr) {
        original(dialog_object, arg2, arg3, arg4, arg5, arg6, arg7, arg8);
    }

    const auto caller_address = reinterpret_cast<uintptr_t>(_ReturnAddress());
    TrackDialogButton(dialog_object, false, caller_address);
}

void __fastcall HookDialogFinalizeHelper(
    void* dialog_object,
    void* /*unused_edx*/,
    std::uint32_t arg2,
    std::uint32_t arg3,
    std::uint32_t arg4,
    float arg5) {
    const auto original = GetX86HookTrampoline<DialogFinalizeHelperFn>(g_debug_ui_overlay_state.dialog_finalize_hook);
    if (original != nullptr) {
        original(dialog_object, arg2, arg3, arg4, arg5);
    }

    const auto caller_address = reinterpret_cast<uintptr_t>(_ReturnAddress());
    ObserveDialogFinalize(dialog_object, caller_address);
}
