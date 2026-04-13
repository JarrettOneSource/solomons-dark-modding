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
    if (mouse_helper == 0 || helper == 0 || player_actor_tick == 0 ||
        player_actor_progression_handle == 0 ||
        player_actor_dtor == 0 ||
        player_actor_vtable28 == 0 ||
        gameplay_hud_render_dispatch == 0 ||
        actor_animation_advance == 0 ||
        puppet_manager_delete_puppet == 0 ||
        pointer_list_delete_batch == 0 ||
        actor_world_unregister == 0) {
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

    g_gameplay_keyboard_injection.initialized = true;
    g_gameplay_keyboard_injection.last_observed_mouse_left_down.store(false, std::memory_order_release);
    g_gameplay_keyboard_injection.mouse_left_edge_serial.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.mouse_left_edge_tick_ms.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.pending_mouse_left_edge_events.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.wizard_bot_sync_not_before_ms.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.gameplay_region_switch_not_before_ms.store(0, std::memory_order_release);
    {
        std::lock_guard<std::mutex> lock(g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
        g_gameplay_keyboard_injection.pending_gameplay_region_switch_requests.clear();
        g_gameplay_keyboard_injection.pending_wizard_bot_sync_requests.clear();
        g_gameplay_keyboard_injection.pending_wizard_bot_destroy_requests.clear();
    }
    g_bot_entities.clear();
    {
        std::lock_guard<std::mutex> lock(g_wizard_bot_snapshot_mutex);
        g_wizard_bot_gameplay_snapshots.clear();
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
        " world_unregister=" + HexString(actor_world_unregister));
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
    {
        std::lock_guard<std::mutex> lock(g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
        g_gameplay_keyboard_injection.pending_enemy_spawn_requests.clear();
        g_gameplay_keyboard_injection.pending_reward_spawn_requests.clear();
        g_gameplay_keyboard_injection.pending_gameplay_region_switch_requests.clear();
        g_gameplay_keyboard_injection.pending_wizard_bot_sync_requests.clear();
        g_gameplay_keyboard_injection.pending_wizard_bot_destroy_requests.clear();
    }
    g_bot_entities.clear();
    {
        std::lock_guard<std::mutex> lock(g_wizard_bot_snapshot_mutex);
        g_wizard_bot_gameplay_snapshots.clear();
        RefreshWizardBotCrashSummaryLocked();
    }
    g_gameplay_keyboard_injection.initialized = false;
    SetCrashContextSummary("wizard_bot_snapshots count=0 gameplay_injection_initialized=false");
}

bool IsGameplayKeyboardInjectionInitialized() {
    return g_gameplay_keyboard_injection.initialized;
}

std::uint64_t GetGameplayMouseLeftEdgeSerial() {
    return g_gameplay_keyboard_injection.mouse_left_edge_serial.load(std::memory_order_acquire);
}

std::uint64_t GetGameplayMouseLeftEdgeTickMs() {
    return g_gameplay_keyboard_injection.mouse_left_edge_tick_ms.load(std::memory_order_acquire);
}

bool QueueGameplayMouseLeftClick(std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!g_gameplay_keyboard_injection.initialized) {
        if (error_message != nullptr) {
            *error_message = "Gameplay input injection is not initialized.";
        }
        return false;
    }

    uintptr_t scene_address = 0;
    if (!TryResolveCurrentGameplayScene(&scene_address) || scene_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Gameplay scene is not active.";
        }
        return false;
    }

    g_gameplay_keyboard_injection.pending_mouse_left_frames.fetch_add(
        kInjectedGameplayMouseClickFrames,
        std::memory_order_acq_rel);
    g_gameplay_keyboard_injection.pending_mouse_left_edge_events.fetch_add(1, std::memory_order_acq_rel);
    Log("Queued gameplay mouse-left click. gameplay=" + HexString(scene_address));
    return true;
}

bool QueueGameplayScancodePress(std::uint32_t scancode, std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!g_gameplay_keyboard_injection.initialized) {
        if (error_message != nullptr) {
            *error_message = "Gameplay keyboard injection is not initialized.";
        }
        return false;
    }
    if (scancode > 0xFF) {
        if (error_message != nullptr) {
            *error_message = "Scancode must be in the range 0..255.";
        }
        return false;
    }

    g_gameplay_keyboard_injection.pending_scancodes[scancode].fetch_add(1, std::memory_order_acq_rel);
    return true;
}

bool QueueGameplayKeyPress(std::string_view binding_name, std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }

    uintptr_t absolute_global = 0;
    if (!TryResolveInjectedBindingGlobal(binding_name, &absolute_global)) {
        if (error_message != nullptr) {
            *error_message =
                "Unknown gameplay key binding. Use menu, inventory, skills, or belt_slot_1..belt_slot_8.";
        }
        return false;
    }

    std::uint32_t raw_binding_code = 0;
    if (!TryReadInjectedBindingCode(absolute_global, &raw_binding_code)) {
        if (error_message != nullptr) {
            *error_message = "Failed to read the live gameplay key binding.";
        }
        return false;
    }

    if (raw_binding_code > 0xFF) {
        if (error_message != nullptr) {
            *error_message =
                "The live gameplay binding is mouse-backed. Use sd.input.click_normalized for mouse-bound actions.";
        }
        return false;
    }

    return QueueGameplayScancodePress(raw_binding_code, error_message);
}

bool QueueHubStartTestrun(std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!g_gameplay_keyboard_injection.initialized) {
        if (error_message != nullptr) {
            *error_message = "Gameplay action pump is not initialized.";
        }
        return false;
    }

    uintptr_t arena_address = 0;
    if (!TryResolveArena(&arena_address) || arena_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Arena state is not active.";
        }
        return false;
    }

    uintptr_t gameplay_address = 0;
    if (!TryResolveCurrentGameplayScene(&gameplay_address) || gameplay_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Gameplay scene is not active.";
        }
        return false;
    }

    g_gameplay_keyboard_injection.pending_hub_start_testrun_requests.exchange(1, std::memory_order_acq_rel);
    std::uint8_t testrun_mode_flag = 0;
    uintptr_t arena_vtable = 0;
    const bool have_testrun_mode_flag =
        ProcessMemory::Instance().TryReadField(gameplay_address, kGameplayTestrunModeFlagOffset, &testrun_mode_flag);
    const bool have_arena_vtable = ProcessMemory::Instance().TryReadValue(arena_address, &arena_vtable);
    Log(
        "Queued hub testrun request. arena=" + HexString(arena_address) +
        " arena_vtable=" + (have_arena_vtable ? HexString(arena_vtable) : std::string("unreadable")) +
        " gameplay=" + HexString(gameplay_address) +
        " switch_region=" + HexString(kGameplaySwitchRegion) +
        " target_region=" + std::to_string(kArenaRegionIndex) +
        " arena_enter_dispatch=" + HexString(kArenaStartRunDispatch) +
        " create=" + HexString(kArenaCreate) +
        " testrun_mode_flag=" +
        (have_testrun_mode_flag ? std::to_string(static_cast<unsigned>(testrun_mode_flag)) : std::string("unreadable")));
    return true;
}

bool QueueGameplaySwitchRegion(int region_index, std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!g_gameplay_keyboard_injection.initialized) {
        if (error_message != nullptr) {
            *error_message = "Gameplay action pump is not initialized.";
        }
        return false;
    }
    if (region_index < 0 || region_index > kArenaRegionIndex) {
        if (error_message != nullptr) {
            *error_message = "Region index is out of range.";
        }
        return false;
    }

    PendingGameplayRegionSwitchRequest request;
    request.region_index = region_index;
    request.next_attempt_ms = static_cast<std::uint64_t>(GetTickCount64());

    std::lock_guard<std::mutex> lock(g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
    if (g_gameplay_keyboard_injection.pending_gameplay_region_switch_requests.size() >= kQueuedGameplayWorldActionLimit) {
        if (error_message != nullptr) {
            *error_message = "The gameplay region switch queue is full.";
        }
        return false;
    }

    g_gameplay_keyboard_injection.pending_gameplay_region_switch_requests.push_back(request);
    Log("gameplay.switch_region: queued region=" + std::to_string(region_index));
    return true;
}

bool QueueGameplayStartWaves(std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!g_gameplay_keyboard_injection.initialized) {
        if (error_message != nullptr) {
            *error_message = "Gameplay action pump is not initialized.";
        }
        return false;
    }

    uintptr_t scene_address = 0;
    if (!TryResolveCurrentGameplayScene(&scene_address) || scene_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Gameplay scene is not active.";
        }
        return false;
    }

    uintptr_t arena_address = 0;
    if (!TryResolveArena(&arena_address) || arena_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Arena is not active.";
        }
        return false;
    }

    g_gameplay_keyboard_injection.pending_start_waves_requests.exchange(1, std::memory_order_acq_rel);
    g_gameplay_keyboard_injection.start_waves_retry_not_before_ms.store(0, std::memory_order_release);

    ArenaWaveStartState arena_state;
    const bool have_arena_state = TryReadArenaWaveStartState(arena_address, &arena_state);
    Log(
        "Queued gameplay start_waves request. scene=" + HexString(scene_address) +
        " arena=" + HexString(arena_address) +
        " start_waves=" + HexString(kArenaStartWaves) +
        " state=" + (have_arena_state ? DescribeArenaWaveStartState(arena_state) : std::string("unreadable")));
    return true;
}

bool QueueWizardBotEntitySync(
    std::uint64_t bot_id,
    std::int32_t wizard_id,
    bool has_transform,
    bool has_heading,
    float position_x,
    float position_y,
    float heading,
    std::string* error_message) {
    PendingWizardBotSyncRequest request;
    request.bot_id = bot_id;
    request.wizard_id = wizard_id;
    request.has_transform = has_transform;
    request.has_heading = has_heading;
    request.x = position_x;
    request.y = position_y;
    request.heading = heading;

    uintptr_t gameplay_address = 0;
    if (!TryResolveCurrentGameplayScene(&gameplay_address) || gameplay_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Gameplay scene is not active.";
        }
        return false;
    }

    if (g_gameplay_keyboard_injection.initialized) {
        return QueueWizardBotSyncRequest(request, error_message);
    }

    return ExecuteWizardBotSyncNow(request, error_message);
}

bool QueueWizardBotDestroy(std::uint64_t bot_id, std::string* error_message) {
    uintptr_t gameplay_address = 0;
    if (!TryResolveCurrentGameplayScene(&gameplay_address) || gameplay_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Gameplay scene is not active.";
        }
        return false;
    }

    if (g_gameplay_keyboard_injection.initialized) {
        return QueueWizardBotDestroyRequest(bot_id, error_message);
    }

    DestroyWizardBotEntityNow(bot_id);
    return true;
}

bool TryGetWizardBotGameplayState(std::uint64_t bot_id, SDModBotGameplayState* state) {
    if (state == nullptr) {
        return false;
    }

    *state = SDModBotGameplayState{};
    std::lock_guard<std::mutex> lock(g_wizard_bot_snapshot_mutex);
    const auto it = std::find_if(
        g_wizard_bot_gameplay_snapshots.begin(),
        g_wizard_bot_gameplay_snapshots.end(),
        [&](const WizardBotGameplaySnapshot& snapshot) {
            return snapshot.bot_id == bot_id;
        });
    if (it == g_wizard_bot_gameplay_snapshots.end()) {
        return false;
    }

    state->available = true;
    state->entity_materialized = it->entity_materialized;
    state->moving = it->moving;
    state->bot_id = it->bot_id;
    state->wizard_id = it->wizard_id;
    state->actor_address = it->actor_address;
    state->world_address = it->world_address;
    state->animation_state_ptr = it->animation_state_ptr;
    state->render_frame_table = it->render_frame_table;
    state->hub_visual_attachment_ptr = it->hub_visual_attachment_ptr;
    state->hub_visual_source_profile_address = it->hub_visual_source_profile_address;
    state->hub_visual_descriptor_signature = it->hub_visual_descriptor_signature;
    state->hub_visual_proxy_address = it->hub_visual_proxy_address;
    state->progression_handle_address = it->progression_handle_address;
    state->equip_handle_address = it->equip_handle_address;
    state->progression_runtime_state_address = it->progression_runtime_state_address;
    state->equip_runtime_state_address = it->equip_runtime_state_address;
    state->gameplay_slot = it->gameplay_slot;
    state->actor_slot = it->actor_slot;
    state->slot_anim_state_index = it->slot_anim_state_index;
    state->resolved_animation_state_id = it->resolved_animation_state_id;
    state->hub_visual_source_kind = it->hub_visual_source_kind;
    state->render_drive_flags = it->render_drive_flags;
    state->anim_drive_state = it->anim_drive_state;
    state->render_variant_primary = it->render_variant_primary;
    state->render_variant_secondary = it->render_variant_secondary;
    state->render_weapon_type = it->render_weapon_type;
    state->render_selection_byte = it->render_selection_byte;
    state->render_variant_tertiary = it->render_variant_tertiary;
    state->x = it->x;
    state->y = it->y;
    state->heading = it->heading;
    state->hp = it->hp;
    state->max_hp = it->max_hp;
    state->mp = it->mp;
    state->max_mp = it->max_mp;
    state->walk_cycle_primary = it->walk_cycle_primary;
    state->walk_cycle_secondary = it->walk_cycle_secondary;
    state->render_drive_stride = it->render_drive_stride;
    state->render_advance_rate = it->render_advance_rate;
    state->render_advance_phase = it->render_advance_phase;
    state->render_drive_overlay_alpha = it->render_drive_overlay_alpha;
    state->render_drive_move_blend = it->render_drive_move_blend;
    state->gameplay_attach_applied = it->gameplay_attach_applied;
    state->primary_visual_lane = it->primary_visual_lane;
    state->secondary_visual_lane = it->secondary_visual_lane;
    state->attachment_visual_lane = it->attachment_visual_lane;
    return true;
}

bool TryGetPlayerState(SDModPlayerState* state) {
    if (state == nullptr) {
        return false;
    }

    *state = SDModPlayerState{};
    uintptr_t gameplay_address = 0;
    uintptr_t actor_address = 0;
    uintptr_t progression_address = 0;
    uintptr_t world_address = 0;
    const bool resolved_gameplay_address =
        TryResolveCurrentGameplayScene(&gameplay_address) && gameplay_address != 0;
    if (resolved_gameplay_address) {
        (void)TryResolveLocalPlayerWorldContext(
            gameplay_address,
            &actor_address,
            &progression_address,
            &world_address);
    }

    if (actor_address == 0 || progression_address == 0 || world_address == 0) {
        (void)TryReadResolvedGamePointerAbsolute(kLocalPlayerActorGlobal, &actor_address);
        if (actor_address == 0) {
            return false;
        }

        auto& memory = ProcessMemory::Instance();
        world_address = memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, 0);
        if (world_address == 0 || !TryResolveActorProgressionRuntime(actor_address, &progression_address)) {
            return false;
        }
    }

    auto& memory = ProcessMemory::Instance();
    state->valid = true;
    state->hp = memory.ReadFieldOr<float>(progression_address, kProgressionHpOffset, 0.0f);
    state->max_hp = memory.ReadFieldOr<float>(progression_address, kProgressionMaxHpOffset, 0.0f);
    state->mp = memory.ReadFieldOr<float>(progression_address, kProgressionMpOffset, 0.0f);
    state->max_mp = memory.ReadFieldOr<float>(progression_address, kProgressionMaxMpOffset, 0.0f);
    state->xp = ReadRoundedXpOrUnknown(progression_address);
    state->level = memory.ReadFieldOr<int>(progression_address, kProgressionLevelOffset, 0);
    state->x = memory.ReadFieldOr<float>(actor_address, kActorPositionXOffset, 0.0f);
    state->y = memory.ReadFieldOr<float>(actor_address, kActorPositionYOffset, 0.0f);
    state->gold = ReadResolvedGlobalIntOr(kGoldGlobal);
    state->actor_address = actor_address;
    state->render_subject_address = actor_address;
    state->world_address = world_address;
    state->progression_address = progression_address;
    state->animation_state_ptr = memory.ReadFieldOr<uintptr_t>(actor_address, kActorAnimationSelectionStateOffset, 0);
    state->render_frame_table = memory.ReadFieldOr<uintptr_t>(actor_address, kActorRenderFrameTableOffset, 0);
    state->hub_visual_attachment_ptr =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorHubVisualAttachmentPtrOffset, 0);
    state->hub_visual_source_profile_address =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorHubVisualSourceProfileOffset, 0);
    state->hub_visual_descriptor_signature = HashMemoryBlockFNV1a32(
        actor_address + kActorHubVisualDescriptorBlockOffset,
        kActorHubVisualDescriptorBlockSize);
    state->progression_handle_address =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorProgressionHandleOffset, 0);
    state->equip_handle_address =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorEquipHandleOffset, 0);
    state->equip_runtime_state_address =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorEquipRuntimeStateOffset, 0);
    state->actor_slot = static_cast<int>(memory.ReadFieldOr<std::int8_t>(actor_address, kActorSlotOffset, -1));
    state->resolved_animation_state_id = ResolveActorAnimationStateId(actor_address);
    state->hub_visual_source_kind =
        memory.ReadFieldOr<std::int32_t>(actor_address, kActorHubVisualSourceKindOffset, 0);
    state->render_drive_flags =
        memory.ReadFieldOr<std::uint32_t>(actor_address, kActorRenderDriveFlagsOffset, 0);
    state->anim_drive_state =
        memory.ReadFieldOr<std::uint8_t>(actor_address, kActorAnimationDriveStateByteOffset, 0);
    state->render_variant_primary =
        memory.ReadFieldOr<std::uint8_t>(actor_address, kActorRenderVariantPrimaryOffset, 0);
    state->render_variant_secondary =
        memory.ReadFieldOr<std::uint8_t>(actor_address, kActorRenderVariantSecondaryOffset, 0);
    state->render_weapon_type =
        memory.ReadFieldOr<std::uint8_t>(actor_address, kActorRenderWeaponTypeOffset, 0);
    state->render_selection_byte =
        memory.ReadFieldOr<std::uint8_t>(actor_address, kActorRenderSelectionByteOffset, 0);
    state->render_variant_tertiary =
        memory.ReadFieldOr<std::uint8_t>(actor_address, kActorRenderVariantTertiaryOffset, 0);
    state->walk_cycle_primary = memory.ReadFieldOr<float>(actor_address, kActorWalkCyclePrimaryOffset, 0.0f);
    state->walk_cycle_secondary = memory.ReadFieldOr<float>(actor_address, kActorWalkCycleSecondaryOffset, 0.0f);
    state->render_drive_stride =
        memory.ReadFieldOr<float>(actor_address, kActorRenderDriveStrideScaleOffset, 0.0f);
    state->render_advance_rate = memory.ReadFieldOr<float>(actor_address, kActorRenderAdvanceRateOffset, 0.0f);
    state->render_advance_phase = memory.ReadFieldOr<float>(actor_address, kActorRenderAdvancePhaseOffset, 0.0f);
    state->render_drive_overlay_alpha =
        memory.ReadFieldOr<float>(actor_address, kActorRenderDriveOverlayAlphaOffset, 0.0f);
    state->render_drive_move_blend =
        memory.ReadFieldOr<float>(actor_address, kActorRenderDriveMoveBlendOffset, 0.0f);
    if (resolved_gameplay_address) {
        state->primary_visual_lane =
            ReadEquipVisualLaneState(gameplay_address, kGameplayVisualSinkPrimaryOffset);
        state->secondary_visual_lane =
            ReadEquipVisualLaneState(gameplay_address, kGameplayVisualSinkSecondaryOffset);
        state->attachment_visual_lane =
            ReadEquipVisualLaneState(gameplay_address, kGameplayVisualSinkAttachmentOffset);
    }

    const auto render_subject_address = state->render_subject_address;
    state->render_subject_animation_state_ptr =
        memory.ReadFieldOr<uintptr_t>(render_subject_address, kActorAnimationSelectionStateOffset, 0);
    state->render_subject_frame_table =
        memory.ReadFieldOr<uintptr_t>(render_subject_address, kActorRenderFrameTableOffset, 0);
    state->render_subject_hub_visual_attachment_ptr =
        memory.ReadFieldOr<uintptr_t>(render_subject_address, kActorHubVisualAttachmentPtrOffset, 0);
    state->render_subject_hub_visual_source_profile_address =
        memory.ReadFieldOr<uintptr_t>(render_subject_address, kActorHubVisualSourceProfileOffset, 0);
    state->render_subject_hub_visual_descriptor_signature = HashMemoryBlockFNV1a32(
        render_subject_address + kActorHubVisualDescriptorBlockOffset,
        kActorHubVisualDescriptorBlockSize);
    state->render_subject_hub_visual_source_kind =
        memory.ReadFieldOr<std::int32_t>(render_subject_address, kActorHubVisualSourceKindOffset, 0);
    state->render_subject_drive_flags =
        memory.ReadFieldOr<std::uint32_t>(render_subject_address, kActorRenderDriveFlagsOffset, 0);
    state->render_subject_anim_drive_state =
        memory.ReadFieldOr<std::uint8_t>(render_subject_address, kActorAnimationDriveStateByteOffset, 0);
    state->render_subject_variant_primary =
        memory.ReadFieldOr<std::uint8_t>(render_subject_address, kActorRenderVariantPrimaryOffset, 0);
    state->render_subject_variant_secondary =
        memory.ReadFieldOr<std::uint8_t>(render_subject_address, kActorRenderVariantSecondaryOffset, 0);
    state->render_subject_weapon_type =
        memory.ReadFieldOr<std::uint8_t>(render_subject_address, kActorRenderWeaponTypeOffset, 0);
    state->render_subject_selection_byte =
        memory.ReadFieldOr<std::uint8_t>(render_subject_address, kActorRenderSelectionByteOffset, 0);
    state->render_subject_variant_tertiary =
        memory.ReadFieldOr<std::uint8_t>(render_subject_address, kActorRenderVariantTertiaryOffset, 0);
    state->gameplay_attach_applied = true;
    return true;
}

bool TryGetWorldState(SDModWorldState* state) {
    if (state == nullptr) {
        return false;
    }

    *state = SDModWorldState{};
    uintptr_t arena_address = 0;
    if (!TryResolveArena(&arena_address) || arena_address == 0) {
        return false;
    }

    state->valid = true;
    state->wave = GetRunLifecycleCurrentWave();
    if (state->wave <= 0) {
        state->wave = ProcessMemory::Instance().ReadFieldOr<int>(arena_address, kArenaCombatWaveIndexOffset, 0);
    }
    state->enemy_count = ReadResolvedGlobalIntOr(kEnemyCountGlobal);
    state->time_elapsed_ms = GetRunLifecycleElapsedMilliseconds();
    return true;
}

bool TryGetSceneState(SDModSceneState* state) {
    if (state == nullptr) {
        return false;
    }

    *state = SDModSceneState{};

    uintptr_t gameplay_scene_address = 0;
    if (!TryResolveCurrentGameplayScene(&gameplay_scene_address) || gameplay_scene_address == 0) {
        return false;
    }

    SceneContextSnapshot scene_context;
    (void)TryBuildSceneContextSnapshot(gameplay_scene_address, &scene_context);
    state->valid = true;
    state->kind = DescribeSceneKind(scene_context);
    state->name = DescribeSceneName(scene_context);
    state->gameplay_scene_address = gameplay_scene_address;
    state->world_address = scene_context.world_address;
    state->arena_address = scene_context.arena_address;
    state->region_state_address = scene_context.region_state_address;
    state->current_region_index = scene_context.current_region_index;
    state->region_type_id = scene_context.region_type_id;
    state->pending_level_kind = ReadResolvedGlobalIntOr(kPendingLevelKindGlobal);
    state->transition_target_a = ReadResolvedGlobalIntOr(kTransitionTargetAGlobal);
    state->transition_target_b = ReadResolvedGlobalIntOr(kTransitionTargetBGlobal);
    return true;
}

bool TryGetGameplaySelectionDebugState(SDModGameplaySelectionDebugState* state) {
    if (state == nullptr) {
        return false;
    }

    *state = SDModGameplaySelectionDebugState{};
    uintptr_t table_address = 0;
    int entry_count = 0;
    if (!TryResolveGameplayIndexState(&table_address, &entry_count) || table_address == 0 || entry_count <= 0) {
        return false;
    }

    state->valid = true;
    state->table_address = table_address;
    state->entry_count = entry_count;
    for (int slot_index = 0; slot_index < static_cast<int>(kGameplayPlayerSlotCount); ++slot_index) {
        const auto table_index = static_cast<int>(kGameplayIndexStateActorSelectionBaseIndex) + slot_index;
        int value = 0;
        if (table_index >= 0 && table_index < entry_count) {
            (void)TryReadGameplayIndexStateValue(table_index, &value);
        }
        state->slot_selection_entries[slot_index] = static_cast<std::int32_t>(value);
    }

    state->player_selection_state_0 =
        static_cast<std::int32_t>(ReadResolvedGlobalIntOr(kPlayerSelectionState0Global, 0));
    state->player_selection_state_1 =
        static_cast<std::int32_t>(ReadResolvedGlobalIntOr(kPlayerSelectionState1Global, 0));
    return true;
}

bool SpawnEnemyByType(int type_id, float x, float y, std::string* error_message) {
    if (g_gameplay_keyboard_injection.initialized) {
        PendingEnemySpawnRequest request;
        request.type_id = type_id;
        request.x = x;
        request.y = y;
        return QueueEnemySpawnRequest(request, error_message);
    }

    return ExecuteSpawnEnemyNow(type_id, x, y, nullptr, error_message);
}

bool SpawnReward(std::string_view kind, int amount, float x, float y, std::string* error_message) {
    if (g_gameplay_keyboard_injection.initialized) {
        PendingRewardSpawnRequest request;
        request.kind = std::string(kind);
        request.amount = amount;
        request.x = x;
        request.y = y;
        return QueueRewardSpawnRequest(request, error_message);
    }

    return ExecuteSpawnRewardNow(kind, amount, x, y, error_message);
}
