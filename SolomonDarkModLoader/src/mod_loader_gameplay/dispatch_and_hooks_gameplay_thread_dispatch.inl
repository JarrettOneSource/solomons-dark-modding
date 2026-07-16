struct DispatchException {
    DWORD code = 0;
};

int CaptureDispatchException(EXCEPTION_POINTERS* exception_pointers, DispatchException* exception) {
    if (exception == nullptr || exception_pointers == nullptr || exception_pointers->ExceptionRecord == nullptr) {
        return EXCEPTION_EXECUTE_HANDLER;
    }

    exception->code = exception_pointers->ExceptionRecord->ExceptionCode;
    return EXCEPTION_EXECUTE_HANDLER;
}

bool CallGameplaySwitchRegionSafe(
    uintptr_t switch_region_address,
    uintptr_t gameplay_address,
    int region_index,
    DispatchException* exception) {
    auto* switch_region = reinterpret_cast<GameplaySwitchRegionFn>(switch_region_address);
    if (exception != nullptr) {
        *exception = DispatchException{};
    }

    __try {
        switch_region(reinterpret_cast<void*>(gameplay_address), region_index);
        return true;
    } __except (CaptureDispatchException(GetExceptionInformation(), exception)) {
        return false;
    }
}

struct ScopedHubRunSwitchAuthorization {
    ScopedHubRunSwitchAuthorization() {
        ++g_multiplayer_client_authorized_hub_run_switch_depth;
    }

    ~ScopedHubRunSwitchAuthorization() {
        --g_multiplayer_client_authorized_hub_run_switch_depth;
    }
};

void LogLocalPlayerSceneSwitchState(
    std::string_view stage,
    uintptr_t gameplay_address) {
    if (gameplay_address == 0) {
        Log("[bots] scene_switch_local stage=" + std::string(stage) + " gameplay=0x0");
        return;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t local_actor_address = 0;
    const bool have_local_actor =
        TryResolvePlayerActorForSlot(gameplay_address, 0, &local_actor_address) &&
        local_actor_address != 0;
    const auto slot_actor_entry = gameplay_address + kGameplayPlayerActorOffset;
    const auto slot_progression_entry = gameplay_address + kGameplayPlayerProgressionHandleOffset;

    uintptr_t actor_vtable = 0;
    uintptr_t actor_vtable_48 = 0;
    uintptr_t local_progression_wrapper = 0;
    uintptr_t local_progression_inner = 0;
    uintptr_t local_equip_wrapper = 0;
    uintptr_t local_equip_inner = 0;
    uintptr_t slot_actor = 0;
    uintptr_t slot_progression_wrapper = 0;
    uintptr_t slot_progression_inner = 0;

    (void)memory.TryReadValue(slot_actor_entry, &slot_actor);
    (void)memory.TryReadValue(slot_progression_entry, &slot_progression_wrapper);
    slot_progression_inner = ReadSmartPointerInnerObject(slot_progression_wrapper);

    if (have_local_actor) {
        (void)memory.TryReadValue(local_actor_address, &actor_vtable);
        if (actor_vtable != 0) {
            (void)memory.TryReadValue(
                actor_vtable + kActorWorldUnregisterNotifyVfuncOffset,
                &actor_vtable_48);
        }
        (void)memory.TryReadField(
            local_actor_address,
            kActorProgressionHandleOffset,
            &local_progression_wrapper);
        local_progression_inner = ReadSmartPointerInnerObject(local_progression_wrapper);
        (void)memory.TryReadField(
            local_actor_address,
            kActorEquipHandleOffset,
            &local_equip_wrapper);
        local_equip_inner = ReadSmartPointerInnerObject(local_equip_wrapper);
    }

    Log(
        "[bots] scene_switch_local stage=" + std::string(stage) +
        " gameplay=" + HexString(gameplay_address) +
        " local_actor=" + (have_local_actor ? HexString(local_actor_address) : std::string("unresolved")) +
        " actor_vt=" + HexString(actor_vtable) +
        " actor_vt48=" + HexString(actor_vtable_48) +
        " slot_actor_entry=" + HexString(slot_actor_entry) +
        " slot_actor=" + HexString(slot_actor) +
        " slot_prog_entry=" + HexString(slot_progression_entry) +
        " slot_prog_wrapper=" + HexString(slot_progression_wrapper) +
        " slot_prog_inner=" + HexString(slot_progression_inner) +
        " local_prog_wrapper=" + HexString(local_progression_wrapper) +
        " local_prog_inner=" + HexString(local_progression_inner) +
        " local_equip_wrapper=" + HexString(local_equip_wrapper) +
        " local_equip_inner=" + HexString(local_equip_inner) +
        " local_progression_runtime=" +
            (have_local_actor
                 ? ReadPointerFieldText(local_actor_address, kActorProgressionRuntimeStateOffset)
                 : std::string("unresolved")) +
        " local_equip_runtime=" +
            (have_local_actor
                 ? ReadPointerFieldText(local_actor_address, kActorEquipRuntimeStateOffset)
                 : std::string("unresolved")) +
        " local_selection=" +
            (have_local_actor
                 ? ReadPointerFieldText(local_actor_address, kActorAnimationSelectionStateOffset)
                 : std::string("unresolved")));
}

bool PrepareGameplaySceneSwitchOnGameThread(
    uintptr_t gameplay_address,
    int region_index,
    const char* source) {
    const bool seeded = ApplyPendingRunGenerationSeedForSceneSwitch(region_index, source);
    LogLocalPlayerSceneSwitchState("before_cleanup", gameplay_address);
    const auto scene_churn_until =
        static_cast<std::uint64_t>(::GetTickCount64()) + kGameplaySceneChurnDelayMs;
    g_gameplay_keyboard_injection.scene_churn_not_before_ms.store(
        scene_churn_until,
        std::memory_order_release);
    g_gameplay_keyboard_injection.wizard_bot_sync_not_before_ms.store(
        scene_churn_until,
        std::memory_order_release);
    {
        std::lock_guard<std::mutex> lock(g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
        g_gameplay_keyboard_injection.pending_participant_sync_requests.clear();
        g_gameplay_keyboard_injection.pending_local_inventory_equip_requests.clear();
    }
    RemoveReplicatedCreatedSharedHubActorsForSceneSwitch(source);
    ClearReplicatedLootPresentationBindingsForSceneSwitch(source);
    LogLocalPlayerSceneSwitchState("before_wizard_dematerialize", gameplay_address);
    DematerializeAllMaterializedWizardBotsForSceneSwitch(source);
    LogLocalPlayerSceneSwitchState("after_wizard_dematerialize", gameplay_address);
    Log(
        "[bots] prepared gameplay scene switch. gameplay=" + HexString(gameplay_address) +
        " target_region=" + std::to_string(region_index) +
        " source=" + std::string(source != nullptr ? source : "unknown") +
        " seeded=" + std::to_string(seeded ? 1 : 0));
    return seeded;
}

bool TryDispatchGameplaySwitchRegionOnGameThread(int region_index, std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }

    if (region_index < 0 || region_index > kArenaRegionIndex) {
        if (error_message != nullptr) {
            *error_message = "Region index is out of range.";
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

    const auto switch_region_address = ProcessMemory::Instance().ResolveGameAddressOrZero(kGameplaySwitchRegion);
    if (switch_region_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve Gameplay_SwitchRegion.";
        }
        return false;
    }

    SceneContextSnapshot before;
    (void)TryBuildSceneContextSnapshot(gameplay_address, &before);
    if (before.current_region_index == region_index && before.world_address != 0) {
        Log(
            "gameplay.switch_region: already in target region. region=" + std::to_string(region_index) +
            " scene=" + DescribeSceneName(before));
        return true;
    }

    DispatchException exception;
    if (!CallGameplaySwitchRegionSafe(switch_region_address, gameplay_address, region_index, &exception)) {
        if (error_message != nullptr) {
            *error_message = "Gameplay_SwitchRegion raised 0x" + HexString(exception.code) + ".";
        }
        Log(
            "gameplay.switch_region: dispatch failed. gameplay=" + HexString(gameplay_address) +
            " switch_region=" + HexString(switch_region_address) +
            " from=" + DescribeSceneName(before) +
            " target_region=" + std::to_string(region_index) +
            " exception_code=" + HexString(exception.code));
        return false;
    }

    SceneContextSnapshot after;
    (void)TryBuildSceneContextSnapshot(gameplay_address, &after);
    Log(
        "gameplay.switch_region: dispatched. gameplay=" + HexString(gameplay_address) +
        " switch_region=" + HexString(switch_region_address) +
        " from=" + DescribeSceneName(before) +
        " to=" + DescribeSceneName(after) +
        " target_region=" + std::to_string(region_index));
    return true;
}

bool CallArenaStartWavesSafe(uintptr_t start_waves_address, uintptr_t arena_address, DispatchException* exception) {
    auto* start_waves = reinterpret_cast<ArenaStartWavesFn>(start_waves_address);
    if (exception != nullptr) {
        *exception = DispatchException{};
    }

    __try {
        start_waves(reinterpret_cast<void*>(arena_address));
        return true;
    } __except (CaptureDispatchException(GetExceptionInformation(), exception)) {
        return false;
    }
}

bool CallGameplayCombatPreludeModeSafe(
    uintptr_t function_address,
    uintptr_t gameplay_runtime_address,
    std::uint32_t arg0,
    std::uint32_t arg1,
    DispatchException* exception) {
    auto* fn = reinterpret_cast<GameplayCombatPreludeModeFn>(function_address);
    if (exception != nullptr) {
        *exception = DispatchException{};
    }

    __try {
        fn(reinterpret_cast<void*>(gameplay_runtime_address), arg0, arg1);
        return true;
    } __except (CaptureDispatchException(GetExceptionInformation(), exception)) {
        return false;
    }
}

bool CallArenaCombatPreludeDispatchSafe(
    uintptr_t function_address,
    uintptr_t prelude_list_address,
    int mode,
    DispatchException* exception) {
    auto* fn = reinterpret_cast<ArenaCombatPreludeDispatchFn>(function_address);
    if (exception != nullptr) {
        *exception = DispatchException{};
    }

    __try {
        fn(reinterpret_cast<void*>(prelude_list_address), mode);
        return true;
    } __except (CaptureDispatchException(GetExceptionInformation(), exception)) {
        return false;
    }
}

bool TryReadArenaWaveStartState(uintptr_t arena_address, ArenaWaveStartState* state) {
    if (state == nullptr || arena_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t vtable = 0;
    if (!memory.TryReadValue(arena_address, &vtable) || vtable == 0) {
        return false;
    }

    ArenaWaveStartState snapshot;
    memory.TryReadField(arena_address, kArenaCombatSectionIndexOffset, &snapshot.combat_section_index);
    memory.TryReadField(arena_address, kArenaCombatWaveIndexOffset, &snapshot.combat_wave_index);
    memory.TryReadField(arena_address, kArenaCombatWaitTicksOffset, &snapshot.combat_wait_ticks);
    memory.TryReadField(arena_address, kArenaCombatAdvanceModeOffset, &snapshot.combat_advance_mode);
    memory.TryReadField(arena_address, kArenaCombatAdvanceThresholdOffset, &snapshot.combat_advance_threshold);
    memory.TryReadField(arena_address, kArenaCombatWaveCounterOffset, &snapshot.combat_wave_counter);
    memory.TryReadField(arena_address, kArenaCombatStartedMusicOffset, &snapshot.combat_started_music);
    memory.TryReadField(arena_address, kArenaCombatTransitionRequestedOffset, &snapshot.combat_transition_requested);
    memory.TryReadField(arena_address, kArenaCombatActiveFlagOffset, &snapshot.combat_active);

    *state = snapshot;
    return true;
}

bool TryResolveGameplayRuntimeState(uintptr_t* gameplay_runtime_address) {
    if (gameplay_runtime_address == nullptr) {
        return false;
    }

    *gameplay_runtime_address = 0;
    auto& memory = ProcessMemory::Instance();
    const auto gameplay_runtime_global_address = memory.ResolveGameAddressOrZero(kGameplayRuntimeGlobal);
    if (gameplay_runtime_global_address == 0) {
        return false;
    }

    uintptr_t gameplay_runtime = 0;
    if (!memory.TryReadValue(gameplay_runtime_global_address, &gameplay_runtime)) {
        return false;
    }
    if (gameplay_runtime == 0 || !memory.IsReadableRange(gameplay_runtime, 0x230)) {
        return false;
    }

    *gameplay_runtime_address = gameplay_runtime;
    return true;
}

std::string DescribeArenaWaveStartState(const ArenaWaveStartState& candidate) {
    return
        "section=" + std::to_string(candidate.combat_section_index) +
        " wave=" + std::to_string(candidate.combat_wave_index) +
        " wait_ticks=" + std::to_string(candidate.combat_wait_ticks) +
        " advance_mode=" + std::to_string(candidate.combat_advance_mode) +
        " advance_threshold=" + std::to_string(candidate.combat_advance_threshold) +
        " wave_counter=" + std::to_string(candidate.combat_wave_counter) +
        " music_started=" + std::to_string(static_cast<unsigned>(candidate.combat_started_music)) +
        " transition_requested=" + std::to_string(static_cast<unsigned>(candidate.combat_transition_requested)) +
        " combat_active=" + std::to_string(static_cast<unsigned>(candidate.combat_active));
}

bool TryEnableCombatPreludeOnGameThread() {
    auto& memory = ProcessMemory::Instance();

    uintptr_t arena_address = 0;
    if (!TryResolveArena(&arena_address) || arena_address == 0) {
        Log("combat_prelude: arena is not active.");
        return false;
    }

    uintptr_t gameplay_runtime_address = 0;
    if (!TryResolveGameplayRuntimeState(&gameplay_runtime_address) || gameplay_runtime_address == 0) {
        Log("combat_prelude: gameplay runtime root is not active.");
        return false;
    }

    ArenaWaveStartState before;
    const bool have_before = TryReadArenaWaveStartState(arena_address, &before);
    int enemy_count = 0;
    if (!TryReadResolvedGlobalInt(kEnemyCountGlobal, &enemy_count)) {
        Log("combat_prelude: native enemy-count global unavailable.");
        return false;
    }
    if (have_before && before.combat_wave_index > 0) {
        Log(
            "combat_prelude: refusing because waves are already active. arena=" + HexString(arena_address) +
            " state=" + DescribeArenaWaveStartState(before));
        return true;
    }
    if (enemy_count > 0) {
        Log(
            "combat_prelude: continuing with existing enemies present. arena=" + HexString(arena_address) +
            " enemy_count=" + std::to_string(enemy_count));
    }

    const auto primary_mode_address = memory.ResolveGameAddressOrZero(kGameplayCombatPreludePrimaryMode);
    const auto secondary_mode_address = memory.ResolveGameAddressOrZero(kGameplayCombatPreludeSecondaryMode);
    const auto prelude_dispatch_address = memory.ResolveGameAddressOrZero(kArenaCombatPreludeDispatch);
    if (primary_mode_address == 0 || secondary_mode_address == 0 || prelude_dispatch_address == 0) {
        Log(
            "combat_prelude: missing stock helper(s). primary=" + HexString(primary_mode_address) +
            " secondary=" + HexString(secondary_mode_address) +
            " dispatch=" + HexString(prelude_dispatch_address));
        return false;
    }

    DispatchException exception;
    if (!CallGameplayCombatPreludeModeSafe(
            primary_mode_address,
            gameplay_runtime_address,
            0,
            0,
            &exception)) {
        Log(
            "combat_prelude: primary mode helper failed. runtime=" + HexString(gameplay_runtime_address) +
            " fn=" + HexString(primary_mode_address) +
            " exception=" + HexString(exception.code));
        return false;
    }

    if (!CallGameplayCombatPreludeModeSafe(
            secondary_mode_address,
            gameplay_runtime_address,
            0,
            0,
            &exception)) {
        Log(
            "combat_prelude: secondary mode helper failed. runtime=" + HexString(gameplay_runtime_address) +
            " fn=" + HexString(secondary_mode_address) +
            " exception=" + HexString(exception.code));
        return false;
    }

    if (!memory.TryWriteField(arena_address, kArenaCombatTransitionRequestedOffset, static_cast<std::uint8_t>(1))) {
        Log("combat_prelude: failed to write arena transition_requested.");
        return false;
    }

    const auto prelude_list_address = arena_address + kArenaCombatPreludeListOffset;
    if (!CallArenaCombatPreludeDispatchSafe(
            prelude_dispatch_address,
            prelude_list_address,
            0x0f,
            &exception)) {
        Log(
            "combat_prelude: prelude dispatch helper failed. list=" + HexString(prelude_list_address) +
            " fn=" + HexString(prelude_dispatch_address) +
            " exception=" + HexString(exception.code));
        return false;
    }

    (void)memory.TryWriteField(arena_address, kArenaCombatStartedMusicOffset, static_cast<std::uint8_t>(1));
    (void)memory.TryWriteField(arena_address, kArenaCombatActiveFlagOffset, static_cast<std::uint8_t>(1));

    ArenaWaveStartState after;
    const bool have_after = TryReadArenaWaveStartState(arena_address, &after);
    int enemy_count_after = 0;
    const bool have_enemy_count_after = TryReadResolvedGlobalInt(kEnemyCountGlobal, &enemy_count_after);
    Log(
        "combat_prelude: dispatched. arena=" + HexString(arena_address) +
        " runtime=" + HexString(gameplay_runtime_address) +
        " before=" + (have_before ? DescribeArenaWaveStartState(before) : std::string("unreadable")) +
        " after=" + (have_after ? DescribeArenaWaveStartState(after) : std::string("unreadable")) +
        " enemy_count=" + (have_enemy_count_after ? std::to_string(enemy_count_after) : std::string("unreadable")));
    SetRunLifecycleCombatPreludeOnlySuppression(true);
    return true;
}

bool TryStartWavesOnGameThread() {
    auto& memory = ProcessMemory::Instance();
    uintptr_t arena_address = 0;
    if (!TryResolveArena(&arena_address) || arena_address == 0) {
        Log("start_waves: arena is not active. arena=" + HexString(arena_address));
        return false;
    }

    const auto start_waves_address = memory.ResolveGameAddressOrZero(kArenaStartWaves);
    if (start_waves_address == 0) {
        Log(
            "start_waves: missing arena combat entrypoint. arena=" + HexString(arena_address) +
            " start_waves=" + HexString(start_waves_address));
        return false;
    }

    ArenaWaveStartState before;
    const bool have_before = TryReadArenaWaveStartState(arena_address, &before);
    if (have_before && before.combat_started_music != 0 && before.combat_wave_index > 0) {
        Log(
            "start_waves: arena combat is already active. arena=" + HexString(arena_address) +
            " start_waves=" + HexString(start_waves_address) +
            " state=" + DescribeArenaWaveStartState(before));
        SetRunLifecycleCombatPreludeOnlySuppression(false);
        return true;
    }

    SetRunLifecycleCombatPreludeOnlySuppression(false);
    SetRunLifecycleWaveStartEnemyTracking(true);
    DispatchException start_waves_exception;
    const bool started_waves =
        CallArenaStartWavesSafe(start_waves_address, arena_address, &start_waves_exception);
    SetRunLifecycleWaveStartEnemyTracking(false);
    if (!started_waves) {
        Log(
            "start_waves: arena combat entrypoint raised an exception. arena=" + HexString(arena_address) +
            " start_waves=" + HexString(start_waves_address) +
            " before=" + (have_before ? DescribeArenaWaveStartState(before) : std::string("unreadable")) +
            " exception_code=" + HexString(start_waves_exception.code));
        return false;
    }

    ArenaWaveStartState after;
    const bool have_after = TryReadArenaWaveStartState(arena_address, &after);
    Log(
        "start_waves: arena combat entrypoint dispatched. arena=" + HexString(arena_address) +
        " start_waves=" + HexString(start_waves_address) +
        " before=" + (have_before ? DescribeArenaWaveStartState(before) : std::string("unreadable")) +
        " after=" + (have_after ? DescribeArenaWaveStartState(after) : std::string("unreadable")));
    return true;
}

bool TryDispatchHubStartTestrunOnGameThread() {
    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    const auto cooldown_until =
        g_gameplay_keyboard_injection.hub_start_testrun_cooldown_until_ms.load(std::memory_order_acquire);
    if (now_ms < cooldown_until) {
        return false;
    }

    uintptr_t arena_address = 0;
    if (!TryResolveArena(&arena_address) || arena_address == 0) {
        return false;
    }

    uintptr_t gameplay_address = 0;
    if (!TryResolveCurrentGameplayScene(&gameplay_address) || gameplay_address == 0) {
        return false;
    }

    const auto switch_region_address = ProcessMemory::Instance().ResolveGameAddressOrZero(kGameplaySwitchRegion);
    if (switch_region_address == 0) {
        return false;
    }
    const auto arena_dispatch_address = ProcessMemory::Instance().ResolveGameAddressOrZero(kArenaStartRunDispatch);

    auto& memory = ProcessMemory::Instance();
    std::uint8_t testrun_mode_flag = 0;
    const bool have_testrun_mode_flag =
        memory.TryReadField(gameplay_address, kGameplayTestrunModeFlagOffset, &testrun_mode_flag);
    uintptr_t arena_vtable = 0;
    const bool have_arena_vtable = memory.TryReadValue(arena_address, &arena_vtable);

    DispatchException start_exception;
    bool switched = false;
    {
        ScopedHubRunSwitchAuthorization authorize_switch;
        switched = CallGameplaySwitchRegionSafe(
            switch_region_address,
            gameplay_address,
            kArenaRegionIndex,
            &start_exception);
    }
    if (!switched) {
        g_gameplay_keyboard_injection.hub_start_testrun_cooldown_until_ms.store(
            now_ms + kHubStartTestrunDispatchCooldownMs,
            std::memory_order_release);
        Log(
            "Hub testrun region switch raised an exception. switch_region=" +
            HexString(switch_region_address) +
            " arena=" + HexString(arena_address) +
            " arena_vtable=" + (have_arena_vtable ? HexString(arena_vtable) : std::string("unreadable")) +
            " gameplay=" + HexString(gameplay_address) +
            " target_region=" + std::to_string(kArenaRegionIndex) +
            " arena_enter_dispatch=" +
            (arena_dispatch_address != 0 ? HexString(arena_dispatch_address) : std::string("unresolved")) +
            " testrun_mode_flag=" +
            (have_testrun_mode_flag ? std::to_string(static_cast<unsigned>(testrun_mode_flag)) : std::string("unreadable")) +
            " exception_code=" + HexString(start_exception.code));
        return false;
    }

    g_gameplay_keyboard_injection.hub_start_testrun_cooldown_until_ms.store(
        now_ms + kHubStartTestrunDispatchCooldownMs,
        std::memory_order_release);
    Log(
        "Hub testrun region switch completed. switch_region=" + HexString(switch_region_address) +
        " arena=" + HexString(arena_address) +
        " arena_vtable=" + (have_arena_vtable ? HexString(arena_vtable) : std::string("unreadable")) +
        " gameplay=" + HexString(gameplay_address) +
        " target_region=" + std::to_string(kArenaRegionIndex) +
        " arena_enter_dispatch=" +
        (arena_dispatch_address != 0 ? HexString(arena_dispatch_address) : std::string("unresolved")) +
        " testrun_mode_flag=" +
        (have_testrun_mode_flag ? std::to_string(static_cast<unsigned>(testrun_mode_flag)) : std::string("unreadable")));
    return true;
}

bool TryDispatchStartWavesOnGameThread() {
    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    const auto retry_not_before =
        g_gameplay_keyboard_injection.start_waves_retry_not_before_ms.load(std::memory_order_acquire);
    if (now_ms < retry_not_before) {
        return false;
    }

    if (!TryStartWavesOnGameThread()) {
        g_gameplay_keyboard_injection.start_waves_retry_not_before_ms.store(
            now_ms + kWaveStartRetryDelayMs,
            std::memory_order_release);
        return false;
    }

    g_gameplay_keyboard_injection.start_waves_retry_not_before_ms.store(0, std::memory_order_release);
    return true;
}
