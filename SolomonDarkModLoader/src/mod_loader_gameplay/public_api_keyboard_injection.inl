bool InitializeGameplayKeyboardInjection(std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (g_gameplay_keyboard_injection.initialized) {
        return true;
    }

    if (!InitializeGameplaySeams(error_message)) {
        return false;
    }

    const auto mouse_helper = ProcessMemory::Instance().ResolveGameAddressOrZero(kGameplayMouseRefreshHelper);
    const auto helper = ProcessMemory::Instance().ResolveGameAddressOrZero(kGameplayKeyboardEdgeHelper);
    const auto player_actor_tick = ProcessMemory::Instance().ResolveGameAddressOrZero(kPlayerActorTick);
    const auto player_actor_progression_handle =
        ProcessMemory::Instance().ResolveGameAddressOrZero(kPlayerActorEnsureProgressionHandle);
    const auto player_actor_apply_mana_delta =
        ProcessMemory::Instance().ResolveGameAddressOrZero(kPlayerActorApplyManaDelta);
    const auto player_actor_dtor = ProcessMemory::Instance().ResolveGameAddressOrZero(kPlayerActorDtor);
    const auto player_actor_vtable28 = ProcessMemory::Instance().ResolveGameAddressOrZero(kPlayerActorVtable28);
    const auto player_actor_secondary_spell_cast =
        ProcessMemory::Instance().ResolveGameAddressOrZero(kPlayerActorSecondarySpellCast);
    const auto secondary_cursor_world_projection =
        ProcessMemory::Instance().ResolveGameAddressOrZero(
            kSecondaryCursorWorldProjection);
    const auto player_actor_magic_damage =
        ProcessMemory::Instance().ResolveGameAddressOrZero(kPlayerActorMagicDamage);
    const auto poisoned_modifier_tick =
        ProcessMemory::Instance().ResolveGameAddressOrZero(kPoisonedModifierTick);
    const auto webbed_modifier_tick =
        ProcessMemory::Instance().ResolveGameAddressOrZero(kWebbedModifierTick);
    const auto damage_context_reset =
        ProcessMemory::Instance().ResolveGameAddressOrZero(kDamageContextReset);
    const auto damage_context_target =
        ProcessMemory::Instance().ResolveGameAddressOrZero(kDamageContextTargetGlobal);
    const auto damage_context_source =
        ProcessMemory::Instance().ResolveGameAddressOrZero(kDamageContextSourceGlobal);
    const auto damage_context_flags =
        ProcessMemory::Instance().ResolveGameAddressOrZero(kDamageContextFlagsGlobal);
    const auto damage_context_primary =
        ProcessMemory::Instance().ResolveGameAddressOrZero(kDamageContextPrimaryGlobal);
    const auto damage_context_secondary =
        ProcessMemory::Instance().ResolveGameAddressOrZero(kDamageContextSecondaryGlobal);
    const auto player_actor_pure_primary_gate =
        ProcessMemory::Instance().ResolveGameAddressOrZero(kPlayerActorPurePrimaryGate);
    const auto player_control_brain_update =
        ProcessMemory::Instance().ResolveGameAddressOrZero(kPlayerControlBrainUpdate);
    const auto pure_primary_spell_start =
        ProcessMemory::Instance().ResolveGameAddressOrZero(kSpellCastPurePrimary);
    const auto pure_primary_attack_dispatch =
        ProcessMemory::Instance().ResolveGameAddressOrZero(kPurePrimaryAttackDispatch);
    const auto fire_ember_ctor =
        ProcessMemory::Instance().ResolveGameAddressOrZero(kFireEmberCtor);
    const auto pure_primary_post_builder =
        ProcessMemory::Instance().ResolveGameAddressOrZero(kPurePrimaryPostBuilder);
    const auto spell_cast_dispatcher =
        ProcessMemory::Instance().ResolveGameAddressOrZero(kSpellCastDispatcher);
    const auto spell_action_builder =
        ProcessMemory::Instance().ResolveGameAddressOrZero(kSpellActionBuilder);
    const auto spell_builder_reset =
        ProcessMemory::Instance().ResolveGameAddressOrZero(kSpellBuilderReset);
    const auto spell_builder_finalize =
        ProcessMemory::Instance().ResolveGameAddressOrZero(kSpellBuilderFinalize);
    const auto gameplay_hud_render_dispatch =
        ProcessMemory::Instance().ResolveGameAddressOrZero(kGameplayHudRenderDispatch);
    const auto gameplay_ui_glyph_draw =
        ProcessMemory::Instance().ResolveGameAddressOrZero(kGameplayUiGlyphDraw);
    const auto gameplay_ui_centered_glyph_draw =
        ProcessMemory::Instance().ResolveGameAddressOrZero(kGameplayUiCenteredGlyphDraw);
    const auto gameplay_ally_label_glyph_return =
        ProcessMemory::Instance().ResolveGameAddressOrZero(kGameplayAllyLabelGlyphReturn);
    const auto gameplay_ui_bundle_global =
        ProcessMemory::Instance().ResolveGameAddressOrZero(kGameplayUiBundleGlobal);
    const auto gameplay_string_assign =
        ProcessMemory::Instance().ResolveGameAddressOrZero(kGameplayStringAssign);
    const auto gameplay_exact_text_object_render =
        ProcessMemory::Instance().ResolveGameAddressOrZero(kGameplayExactTextObjectRender);
    const auto gameplay_exact_text_object_global =
        ProcessMemory::Instance().ResolveGameAddressOrZero(kGameplayExactTextObjectGlobal);
    const auto actor_animation_advance = ProcessMemory::Instance().ResolveGameAddressOrZero(kActorAnimationAdvance);
    const auto puppet_manager_delete_puppet =
        ProcessMemory::Instance().ResolveGameAddressOrZero(kPuppetManagerDeletePuppet);
    const auto pointer_list_delete_batch =
        ProcessMemory::Instance().ResolveGameAddressOrZero(kPointerListDeleteBatch);
    const auto actor_world_unregister = ProcessMemory::Instance().ResolveGameAddressOrZero(kActorWorldUnregister);
    const auto gameplay_switch_region =
        ProcessMemory::Instance().ResolveGameAddressOrZero(kGameplaySwitchRegion);
    const auto monster_pathfinding_refresh_target =
        ProcessMemory::Instance().ResolveGameAddressOrZero(kMonsterPathfindingRefreshTarget);
    const auto badguy_move_step =
        ProcessMemory::Instance().ResolveGameAddressOrZero(kBadguyMoveStep);
    const auto gold_pickup = ProcessMemory::Instance().ResolveGameAddressOrZero(kGoldPickupCaller);
    const auto orb_pickup = ProcessMemory::Instance().ResolveGameAddressOrZero(kOrbPickup);
    const auto item_drop_pickup = ProcessMemory::Instance().ResolveGameAddressOrZero(kItemDropPickupCaller);
    const auto powerup_pickup =
        ProcessMemory::Instance().ResolveGameAddressOrZero(kPowerupPickup);
    if (mouse_helper == 0 || helper == 0 || player_actor_tick == 0 ||
        player_actor_progression_handle == 0 ||
        player_actor_apply_mana_delta == 0 ||
        player_actor_dtor == 0 ||
        player_actor_vtable28 == 0 ||
        player_actor_secondary_spell_cast == 0 ||
        secondary_cursor_world_projection == 0 ||
        player_actor_magic_damage == 0 ||
        poisoned_modifier_tick == 0 ||
        webbed_modifier_tick == 0 ||
        damage_context_reset == 0 ||
        damage_context_target == 0 ||
        damage_context_source == 0 ||
        damage_context_flags == 0 ||
        damage_context_primary == 0 ||
        damage_context_secondary != damage_context_primary + sizeof(float) ||
        player_actor_pure_primary_gate == 0 ||
        player_control_brain_update == 0 ||
        pure_primary_spell_start == 0 ||
        pure_primary_attack_dispatch == 0 ||
        fire_ember_ctor == 0 ||
        spell_cast_dispatcher == 0 ||
        gameplay_hud_render_dispatch == 0 ||
        gameplay_ui_glyph_draw == 0 ||
        gameplay_ui_centered_glyph_draw == 0 ||
        gameplay_ally_label_glyph_return == 0 ||
        kGameplayUiAllyLabelGlyphOffset == 0 ||
        gameplay_ui_bundle_global == 0 ||
        gameplay_string_assign == 0 ||
        gameplay_exact_text_object_render == 0 ||
        gameplay_exact_text_object_global == 0 ||
        kGameplayExactTextObjectOffset == 0 ||
        actor_animation_advance == 0 ||
        puppet_manager_delete_puppet == 0 ||
        pointer_list_delete_batch == 0 ||
        actor_world_unregister == 0 ||
        gameplay_switch_region == 0 ||
        monster_pathfinding_refresh_target == 0 ||
        badguy_move_step == 0 ||
        gold_pickup == 0 ||
        orb_pickup == 0 ||
        item_drop_pickup == 0 ||
        powerup_pickup == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve gameplay input, lifecycle, tracked actor, or native HUD text helpers.";
        }
        return false;
    }

    std::string hook_error;
    if (!InstallX86Hook(
            reinterpret_cast<void*>(mouse_helper),
            reinterpret_cast<void*>(&HookGameplayMouseRefresh),
            kGameplayMouseRefreshHookPatchSize,
            &g_gameplay_keyboard_injection.mouse_refresh_hook,
            &hook_error)) {
        if (error_message != nullptr) {
            *error_message = "Failed to install gameplay mouse refresh hook: " + hook_error;
        }
        return false;
    }

    if (!InstallX86Hook(
            reinterpret_cast<void*>(helper),
            reinterpret_cast<void*>(&HookGameplayKeyboardEdge),
            kGameplayKeyboardEdgeHookPatchSize,
            &g_gameplay_keyboard_injection.edge_hook,
            &hook_error)) {
        RemoveX86Hook(&g_gameplay_keyboard_injection.mouse_refresh_hook);
        if (error_message != nullptr) {
            *error_message = "Failed to install gameplay keyboard edge hook: " + hook_error;
        }
        return false;
    }

    if (!InstallX86Hook(
            reinterpret_cast<void*>(player_actor_tick),
            reinterpret_cast<void*>(&HookPlayerActorTick),
            kPlayerActorTickHookPatchSize,
            &g_gameplay_keyboard_injection.player_actor_tick_hook,
            &hook_error)) {
        RemoveX86Hook(&g_gameplay_keyboard_injection.edge_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.mouse_refresh_hook);
        if (error_message != nullptr) {
            *error_message = "Failed to install player actor tick hook: " + hook_error;
        }
        return false;
    }

    if (!InstallX86Hook(
            reinterpret_cast<void*>(player_actor_progression_handle),
            reinterpret_cast<void*>(&HookPlayerActorEnsureProgressionHandle),
            kPlayerActorEnsureProgressionHandleHookPatchSize,
            &g_gameplay_keyboard_injection.player_actor_progression_handle_hook,
            &hook_error)) {
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_tick_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.edge_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.mouse_refresh_hook);
        if (error_message != nullptr) {
            *error_message = "Failed to install player actor +0x04 hook: " + hook_error;
        }
        return false;
    }

    if (kEnablePlayerActorDtorHook) {
        if (!InstallX86Hook(
                reinterpret_cast<void*>(player_actor_dtor),
                reinterpret_cast<void*>(&HookPlayerActorDtor),
                kPlayerActorDtorHookPatchSize,
                &g_gameplay_keyboard_injection.player_actor_dtor_hook,
                &hook_error)) {
            RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_progression_handle_hook);
            RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_tick_hook);
            RemoveX86Hook(&g_gameplay_keyboard_injection.edge_hook);
            RemoveX86Hook(&g_gameplay_keyboard_injection.mouse_refresh_hook);
            if (error_message != nullptr) {
                *error_message = "Failed to install player actor dtor hook: " + hook_error;
            }
            return false;
        }
    } else {
        g_gameplay_keyboard_injection.player_actor_dtor_hook = X86Hook{};
        Log("Gameplay input injection: player actor dtor hook disabled; run lifecycle hooks handle scene teardown.");
    }

    if (!InstallX86Hook(
            reinterpret_cast<void*>(player_actor_vtable28),
            reinterpret_cast<void*>(&HookPlayerActorVtable28),
            kPlayerActorVtable28HookPatchSize,
            &g_gameplay_keyboard_injection.player_actor_vtable28_hook,
            &hook_error)) {
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_dtor_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_progression_handle_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_tick_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.edge_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.mouse_refresh_hook);
        if (error_message != nullptr) {
            *error_message = "Failed to install player actor +0x28 hook: " + hook_error;
        }
        return false;
    }

    if (player_actor_pure_primary_gate != spell_cast_dispatcher) {
        if (!InstallSafeX86Hook(
                reinterpret_cast<void*>(player_actor_pure_primary_gate),
                reinterpret_cast<void*>(&HookPlayerActorPurePrimaryGate),
                kPlayerActorPurePrimaryGateHookMinimumPatchSize,
                &g_gameplay_keyboard_injection.player_actor_pure_primary_gate_hook,
                &hook_error)) {
            Log("Gameplay input injection: pure-primary gate hook unavailable. " + hook_error);
            g_gameplay_keyboard_injection.player_actor_pure_primary_gate_hook = X86Hook{};
        }
    } else {
        Log("Gameplay input injection: pure-primary gate hook disabled because it aliases spell_dispatcher.");
        g_gameplay_keyboard_injection.player_actor_pure_primary_gate_hook = X86Hook{};
    }

    if (!InstallSafeX86Hook(
            reinterpret_cast<void*>(player_control_brain_update),
            reinterpret_cast<void*>(&HookPlayerControlBrainUpdate),
            kPlayerControlBrainUpdateHookMinimumPatchSize,
            &g_gameplay_keyboard_injection.player_control_brain_update_hook,
            &hook_error)) {
        Log("Gameplay input injection: control-brain hook unavailable. " + hook_error);
        g_gameplay_keyboard_injection.player_control_brain_update_hook = X86Hook{};
    }

    if (!InstallSafeX86Hook(
            reinterpret_cast<void*>(pure_primary_spell_start),
            reinterpret_cast<void*>(&HookPurePrimarySpellStart),
            kPurePrimarySpellStartHookMinimumPatchSize,
            &g_gameplay_keyboard_injection.pure_primary_spell_start_hook,
            &hook_error)) {
        Log("Gameplay input injection: pure-primary spell hook unavailable. " + hook_error);
        g_gameplay_keyboard_injection.pure_primary_spell_start_hook = X86Hook{};
    }

    if (!InstallSafeX86Hook(
            reinterpret_cast<void*>(spell_cast_dispatcher),
            reinterpret_cast<void*>(&HookSpellCastDispatcher),
            kSpellCastDispatcherHookMinimumPatchSize,
            &g_gameplay_keyboard_injection.spell_cast_dispatcher_hook,
            &hook_error)) {
        Log("Gameplay input injection: spell dispatcher hook unavailable. " + hook_error);
        g_gameplay_keyboard_injection.spell_cast_dispatcher_hook = X86Hook{};
    }

    if (!InstallX86Hook(
            reinterpret_cast<void*>(gameplay_hud_render_dispatch),
            reinterpret_cast<void*>(&HookGameplayHudRenderDispatch),
            kGameplayHudRenderDispatchHookPatchSize,
            &g_gameplay_keyboard_injection.gameplay_hud_render_dispatch_hook,
            &hook_error)) {
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_control_brain_update_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.pure_primary_spell_start_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.spell_cast_dispatcher_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_pure_primary_gate_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_vtable28_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_dtor_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_progression_handle_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_tick_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.edge_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.mouse_refresh_hook);
        if (error_message != nullptr) {
            *error_message = "Failed to install gameplay HUD render dispatch hook: " + hook_error;
        }
        return false;
    }

    if (!InstallX86Hook(
            reinterpret_cast<void*>(actor_animation_advance),
            reinterpret_cast<void*>(&HookActorAnimationAdvance),
            kActorAnimationAdvanceHookPatchSize,
            &g_gameplay_keyboard_injection.actor_animation_advance_hook,
            &hook_error)) {
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_control_brain_update_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.pure_primary_spell_start_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.spell_cast_dispatcher_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_pure_primary_gate_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.gameplay_hud_render_dispatch_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_vtable28_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_dtor_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_progression_handle_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_tick_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.edge_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.mouse_refresh_hook);
        if (error_message != nullptr) {
            *error_message = "Failed to install actor animation advance hook: " + hook_error;
        }
        return false;
    }

    if (!InstallX86Hook(
            reinterpret_cast<void*>(puppet_manager_delete_puppet),
            reinterpret_cast<void*>(&HookPuppetManagerDeletePuppet),
            kPuppetManagerDeletePuppetHookPatchSize,
            &g_gameplay_keyboard_injection.puppet_manager_delete_puppet_hook,
            &hook_error)) {
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_control_brain_update_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.pure_primary_spell_start_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.spell_cast_dispatcher_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_pure_primary_gate_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.actor_animation_advance_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.gameplay_hud_render_dispatch_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_vtable28_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_dtor_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_progression_handle_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_tick_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.edge_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.mouse_refresh_hook);
        if (error_message != nullptr) {
            *error_message = "Failed to install puppet manager delete hook: " + hook_error;
        }
        return false;
    }

    if (!InstallX86Hook(
            reinterpret_cast<void*>(pointer_list_delete_batch),
            reinterpret_cast<void*>(&HookPointerListDeleteBatch),
            kPointerListDeleteBatchHookPatchSize,
            &g_gameplay_keyboard_injection.pointer_list_delete_batch_hook,
            &hook_error)) {
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_control_brain_update_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.pure_primary_spell_start_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.spell_cast_dispatcher_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_pure_primary_gate_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.puppet_manager_delete_puppet_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.actor_animation_advance_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.gameplay_hud_render_dispatch_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_vtable28_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_dtor_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_progression_handle_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_tick_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.edge_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.mouse_refresh_hook);
        if (error_message != nullptr) {
            *error_message = "Failed to install pointer-list delete-batch hook: " + hook_error;
        }
        return false;
    }

    if (!InstallX86Hook(
            reinterpret_cast<void*>(actor_world_unregister),
            reinterpret_cast<void*>(&HookActorWorldUnregister),
            kActorWorldUnregisterHookPatchSize,
            &g_gameplay_keyboard_injection.actor_world_unregister_hook,
            &hook_error)) {
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_control_brain_update_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.pure_primary_spell_start_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.spell_cast_dispatcher_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_pure_primary_gate_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.pointer_list_delete_batch_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.puppet_manager_delete_puppet_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.actor_animation_advance_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.gameplay_hud_render_dispatch_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_vtable28_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_dtor_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_progression_handle_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_tick_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.edge_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.mouse_refresh_hook);
        if (error_message != nullptr) {
            *error_message = "Failed to install actor world unregister hook: " + hook_error;
        }
        return false;
    }

    if (!InstallSafeX86Hook(
            reinterpret_cast<void*>(gameplay_switch_region),
            reinterpret_cast<void*>(&HookGameplaySwitchRegion),
            kGameplaySwitchRegionHookMinimumPatchSize,
            &g_gameplay_keyboard_injection.gameplay_switch_region_hook,
            &hook_error)) {
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_control_brain_update_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.pure_primary_spell_start_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.spell_cast_dispatcher_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_pure_primary_gate_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.actor_world_unregister_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.pointer_list_delete_batch_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.puppet_manager_delete_puppet_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.actor_animation_advance_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.gameplay_hud_render_dispatch_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_vtable28_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_dtor_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_progression_handle_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_tick_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.edge_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.mouse_refresh_hook);
        if (error_message != nullptr) {
            *error_message = "Failed to install gameplay switch-region hook: " + hook_error;
        }
        return false;
    }

    if (!InstallSafeX86Hook(
            reinterpret_cast<void*>(monster_pathfinding_refresh_target),
            reinterpret_cast<void*>(&HookMonsterPathfindingRefreshTarget),
            kMonsterPathfindingRefreshTargetHookMinimumPatchSize,
            &g_gameplay_keyboard_injection.monster_pathfinding_refresh_target_hook,
            &hook_error)) {
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_control_brain_update_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.pure_primary_spell_start_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.spell_cast_dispatcher_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_pure_primary_gate_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.gameplay_switch_region_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.actor_world_unregister_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.pointer_list_delete_batch_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.puppet_manager_delete_puppet_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.actor_animation_advance_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.gameplay_hud_render_dispatch_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_vtable28_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_dtor_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_progression_handle_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_tick_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.edge_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.mouse_refresh_hook);
        if (error_message != nullptr) {
            *error_message = "Failed to install hostile target refresh hook: " + hook_error;
        }
        return false;
    }

    g_pure_primary_post_builder_trampoline = nullptr;
    if (pure_primary_post_builder != 0) {
        if (!InstallSafeX86Hook(
                reinterpret_cast<void*>(pure_primary_post_builder),
                reinterpret_cast<void*>(&HookPurePrimaryPostBuilder),
                5,
                &g_gameplay_keyboard_injection.pure_primary_post_builder_hook,
                &hook_error)) {
            Log("Gameplay input injection: pure-primary post-builder hook unavailable. " + hook_error);
            g_gameplay_keyboard_injection.pure_primary_post_builder_hook = X86Hook{};
        } else {
            g_pure_primary_post_builder_trampoline =
                g_gameplay_keyboard_injection.pure_primary_post_builder_hook.trampoline;
        }
    } else {
        Log("Gameplay input injection: pure-primary post-builder hook unavailable; seam was unresolved.");
    }

    if (!InstallX86Hook(
            reinterpret_cast<void*>(player_actor_apply_mana_delta),
            reinterpret_cast<void*>(&HookPlayerActorApplyManaDelta),
            kPlayerActorApplyManaDeltaHookPatchSize,
            &g_gameplay_keyboard_injection.player_actor_apply_mana_delta_hook,
            &hook_error)) {
        RemoveX86Hook(&g_gameplay_keyboard_injection.pure_primary_post_builder_hook);
        g_pure_primary_post_builder_trampoline = nullptr;
        RemoveX86Hook(&g_gameplay_keyboard_injection.monster_pathfinding_refresh_target_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.gameplay_switch_region_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.actor_world_unregister_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.pointer_list_delete_batch_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.puppet_manager_delete_puppet_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.actor_animation_advance_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.gameplay_hud_render_dispatch_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.spell_builder_finalize_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.spell_builder_reset_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.spell_action_builder_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.spell_cast_dispatcher_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.pure_primary_spell_start_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_control_brain_update_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_pure_primary_gate_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_vtable28_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_dtor_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_progression_handle_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_tick_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.edge_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.mouse_refresh_hook);
        if (error_message != nullptr) {
            *error_message = "Failed to install player actor mana-delta hook: " + hook_error;
        }
        return false;
    }

    if (!InstallSafeX86Hook(
            reinterpret_cast<void*>(gold_pickup),
            reinterpret_cast<void*>(&HookGoldPickupTick),
            kGoldPickupHookMinimumPatchSize,
            &g_gameplay_keyboard_injection.gold_pickup_hook,
            &hook_error)) {
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_apply_mana_delta_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.pure_primary_post_builder_hook);
        g_pure_primary_post_builder_trampoline = nullptr;
        RemoveX86Hook(&g_gameplay_keyboard_injection.monster_pathfinding_refresh_target_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.gameplay_switch_region_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.actor_world_unregister_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.pointer_list_delete_batch_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.puppet_manager_delete_puppet_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.actor_animation_advance_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.gameplay_hud_render_dispatch_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.spell_builder_finalize_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.spell_builder_reset_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.spell_action_builder_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.spell_cast_dispatcher_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.pure_primary_spell_start_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_control_brain_update_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_pure_primary_gate_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_vtable28_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_dtor_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_progression_handle_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_tick_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.edge_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.mouse_refresh_hook);
        if (error_message != nullptr) {
            *error_message = "Failed to install gold pickup hook: " + hook_error;
        }
        return false;
    }

    if (!InstallSafeX86Hook(
            reinterpret_cast<void*>(orb_pickup),
            reinterpret_cast<void*>(&HookOrbPickupTick),
            kOrbPickupHookMinimumPatchSize,
            &g_gameplay_keyboard_injection.orb_pickup_hook,
            &hook_error)) {
        RemoveX86Hook(&g_gameplay_keyboard_injection.gold_pickup_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_apply_mana_delta_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.pure_primary_post_builder_hook);
        g_pure_primary_post_builder_trampoline = nullptr;
        RemoveX86Hook(&g_gameplay_keyboard_injection.monster_pathfinding_refresh_target_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.gameplay_switch_region_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.actor_world_unregister_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.pointer_list_delete_batch_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.puppet_manager_delete_puppet_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.actor_animation_advance_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.gameplay_hud_render_dispatch_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.spell_builder_finalize_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.spell_builder_reset_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.spell_action_builder_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.spell_cast_dispatcher_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.pure_primary_spell_start_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_control_brain_update_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_pure_primary_gate_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_vtable28_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_dtor_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_progression_handle_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_tick_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.edge_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.mouse_refresh_hook);
        if (error_message != nullptr) {
            *error_message = "Failed to install orb pickup hook: " + hook_error;
        }
        return false;
    }

    if (!InstallSafeX86Hook(
            reinterpret_cast<void*>(item_drop_pickup),
            reinterpret_cast<void*>(&HookItemDropPickupTick),
            kItemDropPickupHookMinimumPatchSize,
            &g_gameplay_keyboard_injection.item_drop_pickup_hook,
            &hook_error)) {
        RemoveX86Hook(&g_gameplay_keyboard_injection.orb_pickup_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.gold_pickup_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_apply_mana_delta_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.pure_primary_post_builder_hook);
        g_pure_primary_post_builder_trampoline = nullptr;
        RemoveX86Hook(&g_gameplay_keyboard_injection.monster_pathfinding_refresh_target_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.gameplay_switch_region_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.actor_world_unregister_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.pointer_list_delete_batch_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.puppet_manager_delete_puppet_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.actor_animation_advance_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.gameplay_hud_render_dispatch_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.spell_builder_finalize_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.spell_builder_reset_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.spell_action_builder_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.spell_cast_dispatcher_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.pure_primary_spell_start_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_control_brain_update_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_pure_primary_gate_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_vtable28_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_dtor_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_progression_handle_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_tick_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.edge_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.mouse_refresh_hook);
        if (error_message != nullptr) {
            *error_message = "Failed to install item drop pickup hook: " + hook_error;
        }
        return false;
    }

    if (!InstallSafeX86Hook(
            reinterpret_cast<void*>(pure_primary_attack_dispatch),
            reinterpret_cast<void*>(&HookPurePrimaryAttackDispatch),
            kPurePrimaryAttackDispatchHookMinimumPatchSize,
            &g_gameplay_keyboard_injection.pure_primary_attack_dispatch_hook,
            &hook_error)) {
        RemoveX86Hook(&g_gameplay_keyboard_injection.item_drop_pickup_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.orb_pickup_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.gold_pickup_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_apply_mana_delta_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.pure_primary_post_builder_hook);
        g_pure_primary_post_builder_trampoline = nullptr;
        RemoveX86Hook(&g_gameplay_keyboard_injection.monster_pathfinding_refresh_target_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.gameplay_switch_region_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.actor_world_unregister_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.pointer_list_delete_batch_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.puppet_manager_delete_puppet_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.actor_animation_advance_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.gameplay_hud_render_dispatch_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.spell_builder_finalize_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.spell_builder_reset_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.spell_action_builder_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.spell_cast_dispatcher_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.pure_primary_spell_start_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_control_brain_update_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_pure_primary_gate_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_vtable28_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_dtor_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_progression_handle_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_tick_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.edge_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.mouse_refresh_hook);
        if (error_message != nullptr) {
            *error_message =
                "Failed to install pure-primary attack dispatch hook: " + hook_error;
        }
        return false;
    }

    if (!InstallSafeX86Hook(
            reinterpret_cast<void*>(fire_ember_ctor),
            reinterpret_cast<void*>(&HookFireEmberCtor),
            kFireEmberCtorHookMinimumPatchSize,
            &g_gameplay_keyboard_injection.fire_ember_ctor_hook,
            &hook_error)) {
        RemoveX86Hook(&g_gameplay_keyboard_injection.pure_primary_attack_dispatch_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.item_drop_pickup_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.orb_pickup_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.gold_pickup_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_apply_mana_delta_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.pure_primary_post_builder_hook);
        g_pure_primary_post_builder_trampoline = nullptr;
        RemoveX86Hook(&g_gameplay_keyboard_injection.monster_pathfinding_refresh_target_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.gameplay_switch_region_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.actor_world_unregister_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.pointer_list_delete_batch_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.puppet_manager_delete_puppet_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.actor_animation_advance_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.gameplay_hud_render_dispatch_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.spell_builder_finalize_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.spell_builder_reset_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.spell_action_builder_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.spell_cast_dispatcher_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.pure_primary_spell_start_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_control_brain_update_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_pure_primary_gate_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_vtable28_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_dtor_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_progression_handle_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_tick_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.edge_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.mouse_refresh_hook);
        if (error_message != nullptr) {
            *error_message = "Failed to install Fire Ember constructor hook: " + hook_error;
        }
        return false;
    }

    std::string cast_gate_patch_error;
    if (!InstallNativeCastGatePatches(&cast_gate_patch_error)) {
        RemoveX86Hook(&g_gameplay_keyboard_injection.fire_ember_ctor_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.pure_primary_attack_dispatch_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.item_drop_pickup_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.orb_pickup_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.gold_pickup_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_apply_mana_delta_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.pure_primary_post_builder_hook);
        g_pure_primary_post_builder_trampoline = nullptr;
        RemoveX86Hook(&g_gameplay_keyboard_injection.monster_pathfinding_refresh_target_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.gameplay_switch_region_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.actor_world_unregister_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.pointer_list_delete_batch_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.puppet_manager_delete_puppet_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.actor_animation_advance_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.gameplay_hud_render_dispatch_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.spell_builder_finalize_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.spell_builder_reset_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.spell_action_builder_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.spell_cast_dispatcher_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.pure_primary_spell_start_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_control_brain_update_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_pure_primary_gate_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_vtable28_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_dtor_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_progression_handle_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_tick_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.edge_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.mouse_refresh_hook);
        if (error_message != nullptr) {
            *error_message = "Failed to install native cast gate patches: " + cast_gate_patch_error;
        }
        return false;
    }

    if (!InstallSafeX86Hook(
            reinterpret_cast<void*>(player_actor_secondary_spell_cast),
            reinterpret_cast<void*>(&HookPlayerActorSecondarySpellCast),
            kPlayerActorSecondarySpellCastHookMinimumPatchSize,
            &g_gameplay_keyboard_injection.player_actor_secondary_spell_cast_hook,
            &hook_error)) {
        ShutdownGameplayKeyboardInjection();
        if (error_message != nullptr) {
            *error_message =
                "Failed to install player secondary-spell dispatcher hook: " +
                hook_error;
        }
        return false;
    }

    if (!InstallSafeX86Hook(
            reinterpret_cast<void*>(secondary_cursor_world_projection),
            reinterpret_cast<void*>(&HookSecondaryCursorWorldProjection),
            kSecondaryCursorWorldProjectionHookMinimumPatchSize,
            &g_gameplay_keyboard_injection
                .secondary_cursor_world_projection_hook,
            &hook_error)) {
        ShutdownGameplayKeyboardInjection();
        if (error_message != nullptr) {
            *error_message =
                "Failed to install secondary cursor world-projection hook: " +
                hook_error;
        }
        return false;
    }

    if (!InstallX86Hook(
            reinterpret_cast<void*>(gameplay_ui_glyph_draw),
            reinterpret_cast<void*>(&HookGameplayUiGlyphDraw),
            kGameplayUiGlyphDrawHookPatchSize,
            &g_gameplay_keyboard_injection.gameplay_ui_glyph_draw_hook,
            &hook_error)) {
        ShutdownGameplayKeyboardInjection();
        if (error_message != nullptr) {
            *error_message = "Failed to install gameplay ally-label glyph hook: " + hook_error;
        }
        return false;
    }

    if (!InstallX86Hook(
            reinterpret_cast<void*>(gameplay_ui_centered_glyph_draw),
            reinterpret_cast<void*>(&HookGameplayUiAllyLabelGlyphDraw),
            kGameplayUiCenteredGlyphDrawHookPatchSize,
            &g_gameplay_keyboard_injection.gameplay_ui_ally_label_glyph_draw_hook,
            &hook_error)) {
        ShutdownGameplayKeyboardInjection();
        if (error_message != nullptr) {
            *error_message = "Failed to install gameplay ally-label centered glyph hook: " + hook_error;
        }
        return false;
    }

    if (!InstallSafeX86Hook(
            reinterpret_cast<void*>(powerup_pickup),
            reinterpret_cast<void*>(&HookPowerupPickupTick),
            kPowerupPickupHookMinimumPatchSize,
            &g_gameplay_keyboard_injection.powerup_pickup_hook,
            &hook_error)) {
        ShutdownGameplayKeyboardInjection();
        if (error_message != nullptr) {
            *error_message =
                "Failed to install powerup pickup hook: " + hook_error;
        }
        return false;
    }

    if (!InstallSafeX86Hook(
            reinterpret_cast<void*>(badguy_move_step),
            reinterpret_cast<void*>(&HookBadguyMoveStep),
            kBadguyMoveStepHookMinimumPatchSize,
            &g_gameplay_keyboard_injection.badguy_move_step_hook,
            &hook_error)) {
        ShutdownGameplayKeyboardInjection();
        if (error_message != nullptr) {
            *error_message =
                "Failed to install authoritative hostile movement hook: " +
                hook_error;
        }
        return false;
    }

    g_gameplay_keyboard_injection.damage_context_reset_address =
        damage_context_reset;
    g_gameplay_keyboard_injection.damage_context_target_address =
        damage_context_target;
    g_gameplay_keyboard_injection.damage_context_source_address =
        damage_context_source;
    g_gameplay_keyboard_injection.damage_context_flags_address =
        damage_context_flags;
    g_gameplay_keyboard_injection.damage_context_primary_address =
        damage_context_primary;
    g_gameplay_keyboard_injection.damage_context_secondary_address =
        damage_context_secondary;
    if (!InstallSafeX86Hook(
            reinterpret_cast<void*>(player_actor_magic_damage),
            reinterpret_cast<void*>(&HookPlayerActorMagicDamage),
            kPlayerActorMagicDamageHookMinimumPatchSize,
            &g_gameplay_keyboard_injection.player_actor_magic_damage_hook,
            &hook_error)) {
        ShutdownGameplayKeyboardInjection();
        if (error_message != nullptr) {
            *error_message =
                "Failed to install authoritative incoming-damage hook: " +
                hook_error;
        }
        return false;
    }

    if (!InstallSafeX86Hook(
            reinterpret_cast<void*>(poisoned_modifier_tick),
            reinterpret_cast<void*>(&HookPoisonedModifierTick),
            kPoisonedModifierTickHookMinimumPatchSize,
            &g_gameplay_keyboard_injection.poisoned_modifier_tick_hook,
            &hook_error)) {
        ShutdownGameplayKeyboardInjection();
        if (error_message != nullptr) {
            *error_message =
                "Failed to install owner poison authority hook: " +
                hook_error;
        }
        return false;
    }

    if (!InstallSafeX86Hook(
            reinterpret_cast<void*>(webbed_modifier_tick),
            reinterpret_cast<void*>(&HookWebbedModifierTick),
            kWebbedModifierTickHookMinimumPatchSize,
            &g_gameplay_keyboard_injection.webbed_modifier_tick_hook,
            &hook_error)) {
        ShutdownGameplayKeyboardInjection();
        if (error_message != nullptr) {
            *error_message =
                "Failed to install authoritative Webbed lifecycle hook: " +
                hook_error;
        }
        return false;
    }

    std::string boneyard_patch_error;
    if (!InstallBoneyardGeneratorPatch(&boneyard_patch_error)) {
        ShutdownGameplayKeyboardInjection();
        if (error_message != nullptr) {
            *error_message =
                "Failed to install Boneyard generator patch: " +
                boneyard_patch_error;
        }
        return false;
    }

    g_gameplay_keyboard_injection.initialized = true;
    g_gameplay_keyboard_injection.last_observed_mouse_left_down.store(false, std::memory_order_release);
    g_gameplay_keyboard_injection.mouse_left_edge_serial.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.mouse_left_edge_tick_ms.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.claimed_primary_cast_edge_serial.store(
        0,
        std::memory_order_release);
    g_gameplay_keyboard_injection.pending_mouse_left_edge_events.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.pending_mouse_left_frames.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.last_mouse_left_hold_player_tick_generation.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.last_observed_mouse_right_down.store(false, std::memory_order_release);
    g_gameplay_keyboard_injection.pending_mouse_right_frames.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.last_mouse_right_hold_player_tick_generation.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.input_state_address.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.pending_movement_x.store(0.0f, std::memory_order_release);
    g_gameplay_keyboard_injection.pending_movement_y.store(0.0f, std::memory_order_release);
    g_gameplay_keyboard_injection.pending_movement_frames.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.local_movement_intent_x.store(0.0f, std::memory_order_release);
    g_gameplay_keyboard_injection.local_movement_intent_y.store(0.0f, std::memory_order_release);
    g_gameplay_keyboard_injection.local_movement_intent_observed_ms.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.pending_injected_keyboard_control_frames.store(
        0,
        std::memory_order_release);
    g_gameplay_keyboard_injection.pending_manual_spawner_primary_cast_allowances.store(
        0,
        std::memory_order_release);
    g_gameplay_keyboard_injection.manual_spawner_primary_cast_control_grace_until_ms.store(
        0,
        std::memory_order_release);
    g_gameplay_keyboard_injection.manual_spawner_primary_target_actor.store(
        0,
        std::memory_order_release);
    g_gameplay_keyboard_injection.injected_mouse_left_active.store(false, std::memory_order_release);
    g_gameplay_keyboard_injection.injected_mouse_right_active.store(false, std::memory_order_release);
    g_gameplay_keyboard_injection.wizard_bot_sync_not_before_ms.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.gameplay_region_switch_not_before_ms.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.scene_churn_not_before_ms.store(0, std::memory_order_release);
    ResetLocalPlayerTickOwnershipState();
    {
        std::lock_guard<std::mutex> lock(g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
        g_gameplay_keyboard_injection.pending_client_local_loot_suppression_requests.clear();
        g_gameplay_keyboard_injection.pending_replicated_loot_snapshots.clear();
        g_gameplay_keyboard_injection.pending_host_loot_drop_deactivations.clear();
        g_gameplay_keyboard_injection.pending_host_loot_drop_deactivation_ids.clear();
        g_gameplay_keyboard_injection.completed_host_loot_drop_deactivations.clear();
        g_gameplay_keyboard_injection.host_loot_drop_deactivation_run_nonce = 0;
        g_gameplay_keyboard_injection.pending_gameplay_region_switch_requests.clear();
        g_gameplay_keyboard_injection.pending_participant_sync_requests.clear();
        g_gameplay_keyboard_injection.pending_multiplayer_dampen_effect_requests.clear();
        g_gameplay_keyboard_injection
            .pending_local_player_vitals_corrections.clear();
        g_gameplay_keyboard_injection.pending_native_poison_behavior_probes.clear();
        g_gameplay_keyboard_injection.pending_native_magic_hit_behavior_probes.clear();
        g_gameplay_keyboard_injection.next_native_magic_hit_behavior_probe_serial = 1;
        g_gameplay_keyboard_injection.native_magic_hit_behavior_probe_result = {};
        g_gameplay_keyboard_injection.pending_native_staff_effect_probes.clear();
        g_gameplay_keyboard_injection.next_native_staff_effect_probe_serial = 1;
        g_gameplay_keyboard_injection.native_staff_effect_probe_result = {};
        g_gameplay_keyboard_injection.pending_participant_destroy_requests.clear();
    }
    ClearAuthoritativeTurnUndeadTargetLocks();
    g_participant_entities.clear();
    {
        std::lock_guard<std::mutex> lock(g_wizard_bot_snapshot_mutex);
        g_participant_gameplay_snapshots.clear();
        RefreshWizardBotCrashSummaryLocked();
    }
    Log(
        "Gameplay input injection hooks installed. mouse_refresh=" + HexString(mouse_helper) +
        " keyboard_edge=" + HexString(helper) +
        " player_tick=" + HexString(player_actor_tick) +
        " player_vslot04=" + HexString(player_actor_progression_handle) +
        " mana_delta=" + HexString(player_actor_apply_mana_delta) +
        " player_dtor=" + HexString(player_actor_dtor) +
        " player_vslot28=" + HexString(player_actor_vtable28) +
        " secondary_spell_cast=" + HexString(player_actor_secondary_spell_cast) +
        " secondary_cursor_world_projection=" +
            HexString(secondary_cursor_world_projection) +
        " incoming_damage=" + HexString(player_actor_magic_damage) +
        " poisoned_modifier_tick=" + HexString(poisoned_modifier_tick) +
        " damage_context_reset=" + HexString(damage_context_reset) +
        " damage_context_primary=" + HexString(damage_context_primary) +
        " pure_primary_gate=" + HexString(player_actor_pure_primary_gate) +
        " control_brain_update=" + HexString(player_control_brain_update) +
        " pure_primary_start=" + HexString(pure_primary_spell_start) +
        " pure_primary_attack_dispatch=" + HexString(pure_primary_attack_dispatch) +
        " fire_ember_ctor=" + HexString(fire_ember_ctor) +
        " pure_primary_post_builder=" + HexString(pure_primary_post_builder) +
        " spell_dispatcher=" + HexString(spell_cast_dispatcher) +
        " spell_action_builder=" + HexString(spell_action_builder) +
        " spell_builder_reset=" + HexString(spell_builder_reset) +
        " spell_builder_finalize=" + HexString(spell_builder_finalize) +
        " hud_case_dispatch=" + HexString(gameplay_hud_render_dispatch) +
        " gameplay_ui_glyph_draw=" + HexString(gameplay_ui_glyph_draw) +
        " gameplay_ui_centered_glyph_draw=" + HexString(gameplay_ui_centered_glyph_draw) +
        " gameplay_ally_label_glyph_return=" + HexString(gameplay_ally_label_glyph_return) +
        " gameplay_ui_bundle_global=" + HexString(gameplay_ui_bundle_global) +
        " gameplay_ui_ally_label_glyph_offset=" +
            HexString(static_cast<uintptr_t>(kGameplayUiAllyLabelGlyphOffset)) +
        " gameplay_string_assign=" + HexString(gameplay_string_assign) +
        " gameplay_exact_text_object_render=" + HexString(gameplay_exact_text_object_render) +
        " gameplay_exact_text_object_global=" + HexString(gameplay_exact_text_object_global) +
        " gameplay_exact_text_object_offset=" + HexString(static_cast<uintptr_t>(kGameplayExactTextObjectOffset)) +
        " anim_advance=" + HexString(actor_animation_advance) +
        " puppet_manager_delete_puppet=" + HexString(puppet_manager_delete_puppet) +
        " pointer_list_delete_batch=" + HexString(pointer_list_delete_batch) +
        " world_unregister=" + HexString(actor_world_unregister) +
        " gameplay_switch_region=" + HexString(gameplay_switch_region) +
        " hostile_target_refresh=" + HexString(monster_pathfinding_refresh_target) +
        " hostile_move_step=" + HexString(badguy_move_step) +
        " gold_pickup=" + HexString(gold_pickup) +
        " orb_pickup=" + HexString(orb_pickup) +
        " item_drop_pickup=" + HexString(item_drop_pickup) +
        " powerup_pickup=" + HexString(powerup_pickup) +
        " webbed_modifier_tick=" + HexString(webbed_modifier_tick));
    return true;
}

void ShutdownGameplayKeyboardInjection() {
    ClearReplicatedSpellEffectBindings();
    RemoveX86Hook(&g_gameplay_keyboard_injection.mouse_refresh_hook);
    RemoveX86Hook(&g_gameplay_keyboard_injection.edge_hook);
    RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_tick_hook);
    RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_progression_handle_hook);
    RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_apply_mana_delta_hook);
    RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_dtor_hook);
    RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_vtable28_hook);
    RemoveX86Hook(
        &g_gameplay_keyboard_injection.secondary_cursor_world_projection_hook);
    RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_secondary_spell_cast_hook);
    RemoveX86Hook(&g_gameplay_keyboard_injection.webbed_modifier_tick_hook);
    RemoveX86Hook(&g_gameplay_keyboard_injection.poisoned_modifier_tick_hook);
    RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_magic_damage_hook);
    RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_pure_primary_gate_hook);
    RemoveX86Hook(&g_gameplay_keyboard_injection.player_control_brain_update_hook);
    RemoveX86Hook(&g_gameplay_keyboard_injection.pure_primary_spell_start_hook);
    RemoveX86Hook(&g_gameplay_keyboard_injection.pure_primary_attack_dispatch_hook);
    RemoveX86Hook(&g_gameplay_keyboard_injection.fire_ember_ctor_hook);
    RemoveX86Hook(&g_gameplay_keyboard_injection.pure_primary_post_builder_hook);
    g_pure_primary_post_builder_trampoline = nullptr;
    RemoveX86Hook(&g_gameplay_keyboard_injection.spell_cast_dispatcher_hook);
    RemoveX86Hook(&g_gameplay_keyboard_injection.spell_action_builder_hook);
    RemoveX86Hook(&g_gameplay_keyboard_injection.spell_builder_reset_hook);
    RemoveX86Hook(&g_gameplay_keyboard_injection.spell_builder_finalize_hook);
    RemoveX86Hook(&g_gameplay_keyboard_injection.gameplay_ui_ally_label_glyph_draw_hook);
    RemoveX86Hook(&g_gameplay_keyboard_injection.gameplay_ui_glyph_draw_hook);
    RemoveX86Hook(&g_gameplay_keyboard_injection.gameplay_hud_render_dispatch_hook);
    RemoveX86Hook(&g_gameplay_keyboard_injection.actor_animation_advance_hook);
    RemoveX86Hook(&g_gameplay_keyboard_injection.puppet_manager_delete_puppet_hook);
    RemoveX86Hook(&g_gameplay_keyboard_injection.pointer_list_delete_batch_hook);
    RemoveX86Hook(&g_gameplay_keyboard_injection.actor_world_unregister_hook);
    RemoveX86Hook(&g_gameplay_keyboard_injection.gameplay_switch_region_hook);
    RemoveX86Hook(&g_gameplay_keyboard_injection.monster_pathfinding_refresh_target_hook);
    RemoveX86Hook(&g_gameplay_keyboard_injection.badguy_move_step_hook);
    RemoveX86Hook(&g_gameplay_keyboard_injection.gold_pickup_hook);
    RemoveX86Hook(&g_gameplay_keyboard_injection.orb_pickup_hook);
    RemoveX86Hook(&g_gameplay_keyboard_injection.item_drop_pickup_hook);
    RemoveX86Hook(&g_gameplay_keyboard_injection.powerup_pickup_hook);
    g_gameplay_keyboard_injection.damage_context_reset_address = 0;
    g_gameplay_keyboard_injection.damage_context_target_address = 0;
    g_gameplay_keyboard_injection.damage_context_source_address = 0;
    g_gameplay_keyboard_injection.damage_context_flags_address = 0;
    g_gameplay_keyboard_injection.damage_context_primary_address = 0;
    g_gameplay_keyboard_injection.damage_context_secondary_address = 0;
    RestoreNativeCastGatePatches();
    RestoreBoneyardGeneratorPatch();
    {
        std::lock_guard<std::mutex> lock(g_native_spell_effect_actor_mutex);
        g_recent_native_spell_effect_actors.clear();
    }
    for (auto& pending : g_gameplay_keyboard_injection.pending_scancodes) {
        pending.store(0, std::memory_order_release);
    }
    g_gameplay_keyboard_injection.last_observed_mouse_left_down.store(false, std::memory_order_release);
    g_gameplay_keyboard_injection.mouse_left_edge_serial.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.mouse_left_edge_tick_ms.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.claimed_primary_cast_edge_serial.store(
        0,
        std::memory_order_release);
    g_gameplay_keyboard_injection.pending_mouse_left_edge_events.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.pending_mouse_left_frames.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.last_mouse_left_hold_player_tick_generation.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.last_observed_mouse_right_down.store(false, std::memory_order_release);
    g_gameplay_keyboard_injection.pending_mouse_right_frames.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.last_mouse_right_hold_player_tick_generation.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.input_state_address.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.pending_movement_x.store(0.0f, std::memory_order_release);
    g_gameplay_keyboard_injection.pending_movement_y.store(0.0f, std::memory_order_release);
    g_gameplay_keyboard_injection.pending_movement_frames.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.local_movement_intent_x.store(0.0f, std::memory_order_release);
    g_gameplay_keyboard_injection.local_movement_intent_y.store(0.0f, std::memory_order_release);
    g_gameplay_keyboard_injection.local_movement_intent_observed_ms.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.pending_injected_keyboard_control_frames.store(
        0,
        std::memory_order_release);
    g_gameplay_keyboard_injection.pending_manual_spawner_primary_cast_allowances.store(
        0,
        std::memory_order_release);
    g_gameplay_keyboard_injection.manual_spawner_primary_cast_control_grace_until_ms.store(
        0,
        std::memory_order_release);
    g_gameplay_keyboard_injection.manual_spawner_primary_target_actor.store(
        0,
        std::memory_order_release);
    g_gameplay_keyboard_injection.injected_mouse_left_active.store(false, std::memory_order_release);
    g_gameplay_keyboard_injection.injected_mouse_right_active.store(false, std::memory_order_release);
    g_gameplay_keyboard_injection.pending_hub_start_testrun_requests.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.pending_hub_service_request.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.pending_start_waves_requests.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.pending_enable_combat_prelude_requests.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.pending_run_generation_seed.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.pending_run_generation_seed_valid.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.hub_start_testrun_cooldown_until_ms.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.start_waves_retry_not_before_ms.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.wizard_bot_sync_not_before_ms.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.gameplay_region_switch_not_before_ms.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.scene_churn_not_before_ms.store(0, std::memory_order_release);
    ResetLocalPlayerTickOwnershipState();
    {
        std::lock_guard<std::mutex> lock(g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
        g_gameplay_keyboard_injection.pending_reward_spawn_requests.clear();
        g_gameplay_keyboard_injection.pending_local_inventory_equip_requests.clear();
        g_gameplay_keyboard_injection.pending_client_local_loot_suppression_requests.clear();
        g_gameplay_keyboard_injection.pending_replicated_loot_snapshots.clear();
        g_gameplay_keyboard_injection.pending_host_loot_drop_deactivations.clear();
        g_gameplay_keyboard_injection.pending_host_loot_drop_deactivation_ids.clear();
        g_gameplay_keyboard_injection.completed_host_loot_drop_deactivations.clear();
        g_gameplay_keyboard_injection.host_loot_drop_deactivation_run_nonce = 0;
        g_gameplay_keyboard_injection.pending_gameplay_region_switch_requests.clear();
        g_gameplay_keyboard_injection.pending_participant_sync_requests.clear();
        g_gameplay_keyboard_injection.pending_multiplayer_dampen_effect_requests.clear();
        g_gameplay_keyboard_injection
            .pending_local_player_vitals_corrections.clear();
        g_gameplay_keyboard_injection.pending_native_poison_behavior_probes.clear();
        g_gameplay_keyboard_injection.pending_native_magic_hit_behavior_probes.clear();
        g_gameplay_keyboard_injection.next_native_magic_hit_behavior_probe_serial = 1;
        g_gameplay_keyboard_injection.native_magic_hit_behavior_probe_result = {};
        g_gameplay_keyboard_injection.pending_native_staff_effect_probes.clear();
        g_gameplay_keyboard_injection.next_native_staff_effect_probe_serial = 1;
        g_gameplay_keyboard_injection.native_staff_effect_probe_result = {};
        g_gameplay_keyboard_injection.pending_participant_destroy_requests.clear();
    }
    ClearReplicatedLootPresentationBindingsForSceneSwitch("gameplay injection shutdown");
    ClearAuthoritativeTurnUndeadTargetLocks();
    g_participant_entities.clear();
    {
        std::lock_guard<std::mutex> lock(g_wizard_bot_snapshot_mutex);
        g_participant_gameplay_snapshots.clear();
        RefreshWizardBotCrashSummaryLocked();
    }
    g_gameplay_keyboard_injection.initialized = false;
    FlushNavGridSnapshotOnSceneUnload();
    SetCrashContextSummary("participant_snapshots count=0 gameplay_injection_initialized=false");
}
