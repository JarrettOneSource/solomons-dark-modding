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
    const auto player_actor_dtor = ProcessMemory::Instance().ResolveGameAddressOrZero(kPlayerActorDtor);
    const auto player_actor_vtable28 = ProcessMemory::Instance().ResolveGameAddressOrZero(kPlayerActorVtable28);
    const auto gameplay_hud_render_dispatch =
        ProcessMemory::Instance().ResolveGameAddressOrZero(kGameplayHudRenderDispatch);
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
    if (mouse_helper == 0 || helper == 0 || player_actor_tick == 0 ||
        player_actor_progression_handle == 0 ||
        player_actor_dtor == 0 ||
        player_actor_vtable28 == 0 ||
        gameplay_hud_render_dispatch == 0 ||
        actor_animation_advance == 0 ||
        puppet_manager_delete_puppet == 0 ||
        pointer_list_delete_batch == 0 ||
        actor_world_unregister == 0 ||
        gameplay_switch_region == 0 ||
        monster_pathfinding_refresh_target == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve gameplay input, lifecycle, or tracked actor helpers.";
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

    if (!InstallX86Hook(
            reinterpret_cast<void*>(gameplay_hud_render_dispatch),
            reinterpret_cast<void*>(&HookGameplayHudRenderDispatch),
            kGameplayHudRenderDispatchHookPatchSize,
            &g_gameplay_keyboard_injection.gameplay_hud_render_dispatch_hook,
            &hook_error)) {
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

    g_gameplay_keyboard_injection.initialized = true;
    g_gameplay_keyboard_injection.last_observed_mouse_left_down.store(false, std::memory_order_release);
    g_gameplay_keyboard_injection.mouse_left_edge_serial.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.mouse_left_edge_tick_ms.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.pending_mouse_left_edge_events.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.wizard_bot_sync_not_before_ms.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.gameplay_region_switch_not_before_ms.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.scene_churn_not_before_ms.store(0, std::memory_order_release);
    {
        std::lock_guard<std::mutex> lock(g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
        g_gameplay_keyboard_injection.pending_gameplay_region_switch_requests.clear();
        g_gameplay_keyboard_injection.pending_participant_sync_requests.clear();
        g_gameplay_keyboard_injection.pending_participant_destroy_requests.clear();
    }
    g_participant_entities.clear();
    {
        std::lock_guard<std::mutex> lock(g_wizard_bot_snapshot_mutex);
        g_participant_gameplay_snapshots.clear();
        RefreshWizardBotCrashSummaryLocked();
    }
    SetD3d9FrameActionPump(&PumpQueuedGameplayActions);
    Log(
        "Gameplay input injection hooks installed. mouse_refresh=" + HexString(mouse_helper) +
        " keyboard_edge=" + HexString(helper) +
        " player_tick=" + HexString(player_actor_tick) +
        " player_vslot04=" + HexString(player_actor_progression_handle) +
        " player_dtor=" + HexString(player_actor_dtor) +
        " player_vslot28=" + HexString(player_actor_vtable28) +
        " hud_case_dispatch=" + HexString(gameplay_hud_render_dispatch) +
        " anim_advance=" + HexString(actor_animation_advance) +
        " puppet_manager_delete_puppet=" + HexString(puppet_manager_delete_puppet) +
        " pointer_list_delete_batch=" + HexString(pointer_list_delete_batch) +
        " world_unregister=" + HexString(actor_world_unregister) +
        " gameplay_switch_region=" + HexString(gameplay_switch_region) +
        " hostile_target_refresh=" + HexString(monster_pathfinding_refresh_target));
    return true;
}

void ShutdownGameplayKeyboardInjection() {
    SetD3d9FrameActionPump(nullptr);
    RemoveX86Hook(&g_gameplay_keyboard_injection.mouse_refresh_hook);
    RemoveX86Hook(&g_gameplay_keyboard_injection.edge_hook);
    RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_tick_hook);
    RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_progression_handle_hook);
    RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_dtor_hook);
    RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_vtable28_hook);
    RemoveX86Hook(&g_gameplay_keyboard_injection.gameplay_hud_render_dispatch_hook);
    RemoveX86Hook(&g_gameplay_keyboard_injection.actor_animation_advance_hook);
    RemoveX86Hook(&g_gameplay_keyboard_injection.puppet_manager_delete_puppet_hook);
    RemoveX86Hook(&g_gameplay_keyboard_injection.pointer_list_delete_batch_hook);
    RemoveX86Hook(&g_gameplay_keyboard_injection.actor_world_unregister_hook);
    RemoveX86Hook(&g_gameplay_keyboard_injection.gameplay_switch_region_hook);
    RemoveX86Hook(&g_gameplay_keyboard_injection.monster_pathfinding_refresh_target_hook);
    for (auto& pending : g_gameplay_keyboard_injection.pending_scancodes) {
        pending.store(0, std::memory_order_release);
    }
    g_gameplay_keyboard_injection.last_observed_mouse_left_down.store(false, std::memory_order_release);
    g_gameplay_keyboard_injection.mouse_left_edge_serial.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.mouse_left_edge_tick_ms.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.pending_mouse_left_edge_events.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.pending_mouse_left_frames.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.pending_hub_start_testrun_requests.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.pending_start_waves_requests.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.hub_start_testrun_cooldown_until_ms.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.start_waves_retry_not_before_ms.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.wizard_bot_sync_not_before_ms.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.gameplay_region_switch_not_before_ms.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.scene_churn_not_before_ms.store(0, std::memory_order_release);
    {
        std::lock_guard<std::mutex> lock(g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
        g_gameplay_keyboard_injection.pending_enemy_spawn_requests.clear();
        g_gameplay_keyboard_injection.pending_reward_spawn_requests.clear();
        g_gameplay_keyboard_injection.pending_gameplay_region_switch_requests.clear();
        g_gameplay_keyboard_injection.pending_participant_sync_requests.clear();
        g_gameplay_keyboard_injection.pending_participant_destroy_requests.clear();
    }
    g_participant_entities.clear();
    {
        std::lock_guard<std::mutex> lock(g_wizard_bot_snapshot_mutex);
        g_participant_gameplay_snapshots.clear();
        RefreshWizardBotCrashSummaryLocked();
    }
    g_gameplay_keyboard_injection.initialized = false;
    SetCrashContextSummary("participant_snapshots count=0 gameplay_injection_initialized=false");
}

