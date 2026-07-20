constexpr float kClientAuthoritativeRunParkBase = 100000.0f;

bool PrepareMultiplayerRunStart(const char* source) {
    std::string run_generation_error;
    if (PrepareArenaRunGenerationSeed(source, &run_generation_error)) {
        return true;
    }
    Log(
        "Blocked multiplayer run start without a host-authoritative run seed. source=" +
        std::string(source != nullptr ? source : "unknown") +
        " error=" + run_generation_error);
    return false;
}

void __fastcall HookMainMenuControlAction(void* self, void* /*unused_edx*/, void* control) {
    const auto original = GetX86HookTrampoline<MainMenuControlActionFn>(
        g_state.hooks[kHookMainMenuControlAction]);
    if (original == nullptr) {
        return;
    }

    constexpr std::size_t kMainMenuModeOffset = 0x3FC;
    constexpr std::int32_t kMainMenuSavedRunMode = 1;
    constexpr std::size_t kMainMenuLastGameControlOffset = 0x78;
    constexpr std::size_t kMainMenuNewGameControlOffset = 0x12C;

    auto* dispatched_control = control;
    const auto owner_address = reinterpret_cast<uintptr_t>(self);
    std::int32_t menu_mode = 0;
    if ((multiplayer::IsLocalTransportClient() || multiplayer::IsLocalTransportHost()) &&
        owner_address != 0 &&
        reinterpret_cast<uintptr_t>(control) == owner_address + kMainMenuLastGameControlOffset &&
        ProcessMemory::Instance().TryReadField(
            owner_address,
            kMainMenuModeOffset,
            &menu_mode) &&
        menu_mode == kMainMenuSavedRunMode) {
        std::string save_reset_error;
        if (!TryPrepareMainMenuNewGameSaveReset(owner_address, &save_reset_error)) {
            Log(
                "Blocked connected multiplayer Last Game control activation because "
                "the native New Game save reset failed. error=" + save_reset_error);
            return;
        }
        dispatched_control = reinterpret_cast<void*>(owner_address + kMainMenuNewGameControlOffset);
        Log(
            "Redirected connected multiplayer Last Game control activation through "
            "the native New Game control path.");
    }

    original(self, dispatched_control);
}

void __fastcall HookCreateArena(void* self, void* unused_edx) {
    const auto original = GetX86HookTrampoline<RunStartedFn>(g_state.hooks[kHookCreateArena]);
    if (original == nullptr) return;
    if (!PrepareMultiplayerRunStart("arena_create")) {
        return;
    }
    g_state.current_wave.store(0, std::memory_order_release);
    g_state.run_active.store(true, std::memory_order_release);
    g_state.last_wave_spawner.store(0, std::memory_order_release);
    g_state.last_wave_spawner_vtable.store(0, std::memory_order_release);
    g_state.last_wave_spawner_tick_ms.store(0, std::memory_order_release);
    g_state.last_arena_enemy_wave_spawner.store(0, std::memory_order_release);
    g_state.last_arena_enemy_wave_spawner_vtable.store(0, std::memory_order_release);
    g_state.last_arena_enemy_wave_spawner_tick_ms.store(0, std::memory_order_release);
    g_state.last_consumed_spell_click_serial.store(0, std::memory_order_release);
    g_state.run_start_tick_ms.store(static_cast<std::uint64_t>(GetTickCount64()), std::memory_order_release);
    g_state.combat_prelude_only_suppression.store(false, std::memory_order_release);
    {
        std::lock_guard<std::mutex> lock(g_state.wave_spawner_log_mutex);
        g_state.logged_wave_spawners.clear();
    }
    ClearRememberedEnemyTracking();
    original(self, unused_edx);
    multiplayer::NotifyLocalRunStarted();
    DispatchLuaRunStarted();
}

void __fastcall HookStartGame(void* self, void* unused_edx) {
    const auto original = GetX86HookTrampoline<RunStartedFn>(g_state.hooks[kHookStartGame]);
    if (original == nullptr) return;
    if (!PrepareMultiplayerRunStart("start_game")) {
        return;
    }
    g_state.current_wave.store(0, std::memory_order_release);
    g_state.run_active.store(true, std::memory_order_release);
    g_state.last_wave_spawner.store(0, std::memory_order_release);
    g_state.last_wave_spawner_vtable.store(0, std::memory_order_release);
    g_state.last_wave_spawner_tick_ms.store(0, std::memory_order_release);
    g_state.last_arena_enemy_wave_spawner.store(0, std::memory_order_release);
    g_state.last_arena_enemy_wave_spawner_vtable.store(0, std::memory_order_release);
    g_state.last_arena_enemy_wave_spawner_tick_ms.store(0, std::memory_order_release);
    g_state.last_consumed_spell_click_serial.store(0, std::memory_order_release);
    g_state.run_start_tick_ms.store(static_cast<std::uint64_t>(GetTickCount64()), std::memory_order_release);
    g_state.combat_prelude_only_suppression.store(false, std::memory_order_release);
    {
        std::lock_guard<std::mutex> lock(g_state.wave_spawner_log_mutex);
        g_state.logged_wave_spawners.clear();
    }
    ClearRememberedEnemyTracking();
    original(self, unused_edx);
    multiplayer::NotifyLocalRunStarted();
    DispatchLuaRunStarted();
}

void __cdecl HookRunEnded() {
    const auto original = GetX86HookTrampoline<RunEndedFn>(g_state.hooks[kHookRunEnded]);
    if (original == nullptr) return;
    g_state.run_active.store(false, std::memory_order_release);
    original();
    CompleteRunLifecycleEnd("death", true, false);
}

bool ShouldSuppressClientAuthoritativeRunWaveSpawner(std::uint64_t now_ms) {
    if (!multiplayer::IsLocalTransportClient()) {
        return false;
    }

    const auto runtime_state = multiplayer::SnapshotRuntimeState();
    const auto& snapshot = runtime_state.world_snapshot;
    if (!snapshot.valid ||
        snapshot.scene_intent.kind != multiplayer::ParticipantSceneIntentKind::Run ||
        snapshot.actors.empty() ||
        snapshot.authority_participant_id == 0 ||
        now_ms < snapshot.received_ms ||
        now_ms - snapshot.received_ms > 1000) {
        return true;
    }

    std::uint32_t authoritative_live_enemies = 0;
    for (const auto& actor : snapshot.actors) {
        if (actor.tracked_enemy &&
            !actor.dead &&
            std::isfinite(actor.hp) &&
            std::isfinite(actor.max_hp) &&
            actor.max_hp > 0.0f &&
            actor.hp > 0.05f) {
            authoritative_live_enemies += 1;
        }
    }

    std::vector<SDModSceneActorState> actors;
    if (!TryListSceneActors(&actors)) {
        return false;
    }

    std::uint32_t local_live_enemies = 0;
    for (const auto& actor : actors) {
        if (actor.valid &&
            actor.actor_address != 0 &&
            actor.tracked_enemy &&
            !actor.dead &&
            actor.x < kClientAuthoritativeRunParkBase * 0.5f &&
            actor.y < kClientAuthoritativeRunParkBase * 0.5f &&
            std::isfinite(actor.hp) &&
            std::isfinite(actor.max_hp) &&
            actor.max_hp > 0.0f &&
            actor.hp > 0.05f) {
            local_live_enemies += 1;
        }
    }

    (void)authoritative_live_enemies;
    (void)local_live_enemies;
    return true;
}

void ClearFrozenManualRunEnemyControlState(uintptr_t actor_address) {
    if (actor_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    (void)memory.TryWriteField<uintptr_t>(
        actor_address,
        kActorCurrentTargetActorOffset,
        0);
    (void)memory.TryWriteField<std::int32_t>(
        actor_address,
        kActorCurrentTargetBucketDeltaOffset,
        0);

    uintptr_t control_brain_address = 0;
    if (!memory.TryReadField(
            actor_address,
            kActorAnimationSelectionStateOffset,
            &control_brain_address) ||
        control_brain_address == 0) {
        return;
    }

    constexpr std::int32_t kFrozenManualEnemyRetargetSuppressionTicks = 60;
    (void)memory.TryWriteValue<std::uint8_t>(
        control_brain_address + kActorControlBrainTargetSlotOffset,
        0xFF);
    (void)memory.TryWriteValue<std::uint16_t>(
        control_brain_address + kActorControlBrainTargetHandleOffset,
        0xFFFF);
    (void)memory.TryWriteValue<std::int32_t>(
        control_brain_address + kActorControlBrainRetargetTicksOffset,
        kFrozenManualEnemyRetargetSuppressionTicks);
    (void)memory.TryWriteValue<std::int32_t>(
        control_brain_address + kActorControlBrainTargetCooldownTicksOffset,
        0);
    (void)memory.TryWriteValue<std::int32_t>(
        control_brain_address + kActorControlBrainActionCooldownTicksOffset,
        0);
    (void)memory.TryWriteValue<std::int32_t>(
        control_brain_address + kActorControlBrainActionBurstTicksOffset,
        0);
    (void)memory.TryWriteValue<std::int32_t>(
        control_brain_address + kActorControlBrainHeadingLockTicksOffset,
        0);
    (void)memory.TryWriteValue<std::uint8_t>(
        control_brain_address + kActorControlBrainFollowLeaderOffset,
        0);
    (void)memory.TryWriteValue<float>(
        control_brain_address + kActorControlBrainMoveInputXOffset,
        0.0f);
    (void)memory.TryWriteValue<float>(
        control_brain_address + kActorControlBrainMoveInputYOffset,
        0.0f);
}

void PinFrozenManualRunEnemies() {
    std::vector<std::pair<uintptr_t, FrozenManualRunEnemy>> frozen_enemies;
    {
        std::lock_guard<std::mutex> lock(g_manual_run_enemy_spawn_mutex);
        frozen_enemies.reserve(g_frozen_manual_run_enemies.size());
        for (const auto& entry : g_frozen_manual_run_enemies) {
            frozen_enemies.push_back(entry);
        }
    }

    if (frozen_enemies.empty()) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    std::vector<uintptr_t> stale_enemies;
    for (const auto& entry : frozen_enemies) {
        const auto actor_address = entry.first;
        const auto& freeze = entry.second;
        float hp = 0.0f;
        if (!memory.TryReadField(actor_address, kEnemyCurrentHpOffset, &hp) ||
            !std::isfinite(hp) ||
            hp <= 0.05f) {
            stale_enemies.push_back(actor_address);
            continue;
        }
        ClearFrozenManualRunEnemyControlState(actor_address);
        (void)memory.TryWriteField(actor_address, kActorPositionXOffset, freeze.x);
        (void)memory.TryWriteField(actor_address, kActorPositionYOffset, freeze.y);
    }

    if (stale_enemies.empty()) {
        return;
    }

    std::lock_guard<std::mutex> lock(g_manual_run_enemy_spawn_mutex);
    for (const auto actor_address : stale_enemies) {
        g_frozen_manual_run_enemies.erase(actor_address);
    }
}

void PinManualRunEnemySpawnerTestModeArenaState() {
    SDModGameplayCombatState combat_state;
    if (!TryGetGameplayCombatState(&combat_state) || !combat_state.valid || combat_state.arena_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    (void)memory.TryWriteField<std::int32_t>(
        combat_state.arena_address,
        kArenaCombatWaveIndexOffset,
        0);
    (void)memory.TryWriteField<std::int32_t>(
        combat_state.arena_address,
        kArenaCombatWaveCounterOffset,
        999999999);
    (void)memory.TryWriteField<std::uint8_t>(
        combat_state.arena_address,
        kArenaCombatTransitionRequestedOffset,
        static_cast<std::uint8_t>(1));
    (void)memory.TryWriteField<std::uint8_t>(
        combat_state.arena_address,
        kArenaCombatStartedMusicOffset,
        static_cast<std::uint8_t>(1));
    (void)memory.TryWriteField<std::uint8_t>(
        combat_state.arena_address,
        kArenaCombatActiveFlagOffset,
        static_cast<std::uint8_t>(1));
    g_state.current_wave.store(0, std::memory_order_release);
}

void CompleteManualRunEnemySpawnFailure(
    const ManualRunEnemySpawnRequest& request,
    std::string_view error_message) {
    SDModManualRunEnemySpawnResult result;
    result.valid = true;
    result.ok = false;
    result.request_id = request.request_id;
    result.type_id = request.type_id;
    result.requested_x = request.x;
    result.requested_y = request.y;
    result.completed_tick_ms = static_cast<std::uint64_t>(GetTickCount64());
    result.error_message = std::string(error_message);

    std::lock_guard<std::mutex> lock(g_manual_run_enemy_spawn_mutex);
    g_last_manual_run_enemy_spawn_result = std::move(result);
    if (g_have_active_manual_run_enemy_spawn &&
        g_active_manual_run_enemy_spawn.request_id == request.request_id) {
        g_have_active_manual_run_enemy_spawn = false;
        g_active_manual_run_enemy_spawn = ManualRunEnemySpawnRequest{};
    }
}

struct ManualRunEnemySpawnerDispatchException {
    DWORD code = 0;
};

struct EmptyEnemyModifierArray {
    uintptr_t vtable = 0;
    uintptr_t entries = 0;
    std::int32_t count = 0;
    std::int32_t capacity = 0;
};

enum class ManualRunEnemySpawnerDispatchResult {
    NoRequest = 0,
    Handled,
};

int CaptureManualRunEnemySpawnerDispatchException(
    EXCEPTION_POINTERS* exception_pointers,
    ManualRunEnemySpawnerDispatchException* exception) {
    if (exception == nullptr || exception_pointers == nullptr || exception_pointers->ExceptionRecord == nullptr) {
        return EXCEPTION_EXECUTE_HANDLER;
    }

    exception->code = exception_pointers->ExceptionRecord->ExceptionCode;
    return EXCEPTION_EXECUTE_HANDLER;
}

bool CallSpawnExactEnemyGroupSafe(
    SpawnExactEnemyGroupFn spawn,
    uintptr_t arena_address,
    std::uint32_t native_type_id,
    uintptr_t modifier_array_vtable,
    uintptr_t free_address,
    ManualRunEnemySpawnerDispatchException* exception) {
    if (exception != nullptr) {
        *exception = ManualRunEnemySpawnerDispatchException{};
    }
    if (spawn == nullptr || arena_address == 0 ||
        modifier_array_vtable == 0 || free_address == 0 ||
        !IsArenaCombatActorType(native_type_id)) {
        return false;
    }

    EmptyEnemyModifierArray no_modifiers;
    no_modifiers.vtable = modifier_array_vtable;
    bool call_ok = false;
    __try {
        spawn(
            reinterpret_cast<void*>(arena_address),
            1,
            native_type_id,
            0,
            &no_modifiers,
            0,
            0,
            0);
        call_ok = true;
    } __except (CaptureManualRunEnemySpawnerDispatchException(
        GetExceptionInformation(), exception)) {
        call_ok = false;
    }

    if (no_modifiers.entries != 0) {
        auto* free_fn = reinterpret_cast<GameFreeFn>(free_address);
        __try {
            free_fn(reinterpret_cast<void*>(no_modifiers.entries));
        } __except (CaptureManualRunEnemySpawnerDispatchException(
            GetExceptionInformation(), exception)) {
            call_ok = false;
        }
    }
    return call_ok;
}

ManualRunEnemySpawnerDispatchResult DispatchReplicatedExactRunEnemySpawn(
    const ManualRunEnemySpawnRequest& request,
    uintptr_t spawner_address) {
    auto& memory = ProcessMemory::Instance();
    const auto spawn_address =
        memory.ResolveGameAddressOrZero(kSpawnExactEnemyGroup);
    const auto modifier_array_vtable =
        memory.ResolveGameAddressOrZero(kNativeIntArrayVtable);
    const auto free_address = memory.ResolveGameAddressOrZero(kGameFree);
    SDModGameplayCombatState combat_state;
    if (spawn_address == 0 ||
        modifier_array_vtable == 0 ||
        free_address == 0 ||
        !TryGetGameplayCombatState(&combat_state) ||
        !combat_state.valid ||
        combat_state.arena_address == 0 ||
        !IsArenaCombatActorType(static_cast<std::uint32_t>(request.type_id))) {
        CompleteManualRunEnemySpawnFailure(
            request,
            "exact replicated run enemy spawn is unavailable.");
        return ManualRunEnemySpawnerDispatchResult::Handled;
    }

    const auto previous_current_spawner =
        g_current_wave_spawner_tick_address;
    const auto previous_manual_spawner =
        g_manual_run_enemy_spawner_tick_address;
    const bool previous_manual_tick = g_manual_run_enemy_spawner_tick_active;
    g_current_wave_spawner_tick_address = spawner_address;
    g_manual_run_enemy_spawner_tick_address = 0;
    g_manual_run_enemy_spawner_tick_active = true;

    ManualRunEnemySpawnerDispatchException exception;
    const bool call_ok = CallSpawnExactEnemyGroupSafe(
        reinterpret_cast<SpawnExactEnemyGroupFn>(spawn_address),
        combat_state.arena_address,
        static_cast<std::uint32_t>(request.type_id),
        modifier_array_vtable,
        free_address,
        &exception);

    g_manual_run_enemy_spawner_tick_active = previous_manual_tick;
    g_manual_run_enemy_spawner_tick_address = previous_manual_spawner;
    g_current_wave_spawner_tick_address = previous_current_spawner;

    bool still_active = false;
    {
        std::lock_guard<std::mutex> lock(g_manual_run_enemy_spawn_mutex);
        still_active =
            g_have_active_manual_run_enemy_spawn &&
            g_active_manual_run_enemy_spawn.request_id == request.request_id;
    }
    if (!call_ok) {
        CompleteManualRunEnemySpawnFailure(
            request,
            "exact replicated run enemy spawn raised 0x" +
                HexString(exception.code) + ".");
    } else if (still_active) {
        CompleteManualRunEnemySpawnFailure(
            request,
            "exact replicated run enemy spawn created no enemy.");
    }
    return ManualRunEnemySpawnerDispatchResult::Handled;
}

void RememberArenaEnemyWaveSpawner(uintptr_t spawner_address) {
    if (spawner_address == 0) {
        return;
    }

    uintptr_t spawner_vtable = 0;
    if (!ProcessMemory::Instance().TryReadValue(spawner_address, &spawner_vtable) ||
        spawner_vtable == 0) {
        return;
    }

    g_state.last_arena_enemy_wave_spawner.store(spawner_address, std::memory_order_release);
    g_state.last_arena_enemy_wave_spawner_vtable.store(spawner_vtable, std::memory_order_release);
    g_state.last_arena_enemy_wave_spawner_tick_ms.store(
        static_cast<std::uint64_t>(GetTickCount64()),
        std::memory_order_release);
}

bool CallManualRunEnemySpawnerTickSafe(
    WaveSpawnerTickFn original,
    void* self,
    void* unused_edx,
    ManualRunEnemySpawnerDispatchException* exception) {
    if (exception != nullptr) {
        *exception = ManualRunEnemySpawnerDispatchException{};
    }
    __try {
        original(self, unused_edx);
        return true;
    } __except (CaptureManualRunEnemySpawnerDispatchException(GetExceptionInformation(), exception)) {
        return false;
    }
}

ManualRunEnemySpawnerDispatchResult TryDispatchManualRunEnemySpawnFromSpawner(
    void* self,
    void* unused_edx,
    WaveSpawnerTickFn original) {
    if (self == nullptr || original == nullptr) {
        return ManualRunEnemySpawnerDispatchResult::NoRequest;
    }

    ManualRunEnemySpawnRequest request;
    {
        std::lock_guard<std::mutex> lock(g_manual_run_enemy_spawn_mutex);
        const bool have_any_pending_request =
            g_have_pending_manual_run_enemy_spawn || !g_queued_replicated_run_enemy_spawns.empty();
        if (!have_any_pending_request || g_have_active_manual_run_enemy_spawn) {
            return ManualRunEnemySpawnerDispatchResult::NoRequest;
        }
        if (g_have_pending_manual_run_enemy_spawn) {
            request = g_pending_manual_run_enemy_spawn;
            g_pending_manual_run_enemy_spawn = ManualRunEnemySpawnRequest{};
            g_have_pending_manual_run_enemy_spawn = false;
        } else {
            request = g_queued_replicated_run_enemy_spawns.front();
            g_queued_replicated_run_enemy_spawns.pop_front();
        }
        g_active_manual_run_enemy_spawn = request;
        g_have_active_manual_run_enemy_spawn = true;
    }

    const auto spawner_address = reinterpret_cast<uintptr_t>(self);
    const bool is_replicated_catchup_request =
        request.network_actor_id != 0 &&
        request.allow_active_waves &&
        !request.freeze_on_spawn;
    if (is_replicated_catchup_request) {
        return DispatchReplicatedExactRunEnemySpawn(
            request,
            spawner_address);
    }

    auto& memory = ProcessMemory::Instance();
    if (!memory.IsReadableRange(spawner_address, kWaveSpawnerLongDelayCountdownOffset + sizeof(std::int32_t))) {
        CompleteManualRunEnemySpawnFailure(request, "stock wave spawner is not readable.");
        return ManualRunEnemySpawnerDispatchResult::Handled;
    }

    std::int32_t previous_budget = 0;
    std::int32_t previous_spawn_delay = 0;
    std::int32_t previous_long_delay = 0;
    (void)memory.TryReadField(spawner_address, kWaveSpawnerRemainingBudgetOffset, &previous_budget);
    (void)memory.TryReadField(spawner_address, kWaveSpawnerSpawnDelayCountdownOffset, &previous_spawn_delay);
    (void)memory.TryReadField(spawner_address, kWaveSpawnerLongDelayCountdownOffset, &previous_long_delay);

    const bool wrote_budget =
        memory.TryWriteField(spawner_address, kWaveSpawnerRemainingBudgetOffset, kManualRunEnemySpawnerBudget);
    const bool wrote_spawn_delay =
        memory.TryWriteField(spawner_address, kWaveSpawnerSpawnDelayCountdownOffset, static_cast<std::int32_t>(0));
    const bool wrote_long_delay =
        memory.TryWriteField(spawner_address, kWaveSpawnerLongDelayCountdownOffset, kManualRunEnemySpawnerLongDelay);
    if (!wrote_budget || !wrote_spawn_delay || !wrote_long_delay) {
        CompleteManualRunEnemySpawnFailure(request, "failed to arm stock wave spawner for one manual enemy.");
        return ManualRunEnemySpawnerDispatchResult::Handled;
    }

    Log(
        "manual run enemy spawn: arming stock spawner. request_id=" +
        std::to_string(request.request_id) +
        " type_id=" + std::to_string(request.type_id) +
        " spawner=" + HexString(spawner_address) +
        " requested_pos=(" + std::to_string(request.x) + "," + std::to_string(request.y) + ")" +
        " previous_budget=" + std::to_string(previous_budget) +
        " previous_spawn_delay=" + std::to_string(previous_spawn_delay) +
        " previous_long_delay=" + std::to_string(previous_long_delay));

    const auto previous_tracking = g_state.wave_start_enemy_tracking.exchange(true, std::memory_order_acq_rel);
    g_manual_run_enemy_spawner_tick_active = true;
    g_manual_run_enemy_spawner_tick_address = spawner_address;
    const auto previous_current_wave_spawner_tick_address = g_current_wave_spawner_tick_address;
    g_current_wave_spawner_tick_address = spawner_address;

    ManualRunEnemySpawnerDispatchException exception;
    const bool tick_ok = CallManualRunEnemySpawnerTickSafe(original, self, unused_edx, &exception);

    g_current_wave_spawner_tick_address = previous_current_wave_spawner_tick_address;
    g_manual_run_enemy_spawner_tick_address = 0;
    g_manual_run_enemy_spawner_tick_active = false;
    g_state.wave_start_enemy_tracking.store(previous_tracking, std::memory_order_release);

    bool still_active = false;
    {
        std::lock_guard<std::mutex> lock(g_manual_run_enemy_spawn_mutex);
        still_active =
            g_have_active_manual_run_enemy_spawn &&
            g_active_manual_run_enemy_spawn.request_id == request.request_id;
    }

    if (!tick_ok) {
        CompleteManualRunEnemySpawnFailure(
            request,
            "stock wave spawner tick raised 0x" + HexString(exception.code) + ".");
        return ManualRunEnemySpawnerDispatchResult::Handled;
    }

    if (still_active) {
        CompleteManualRunEnemySpawnFailure(
            request,
            "stock wave spawner tick completed without creating an enemy.");
        return ManualRunEnemySpawnerDispatchResult::Handled;
    }
    return ManualRunEnemySpawnerDispatchResult::Handled;
}

void __fastcall HookActorWorldTick(void* self, void* unused_edx) {
    const auto original = GetX86HookTrampoline<ActorWorldTickFn>(
        g_state.hooks[kHookActorWorldTick]);
    if (original == nullptr) {
        return;
    }

    if (!multiplayer::ShouldPauseGameplayForLevelUpSelection()) {
        original(self, unused_edx);
        return;
    }

    auto& memory = ProcessMemory::Instance();
    const auto world_address = reinterpret_cast<uintptr_t>(self);
    const auto resolved_player_actor_tick =
        memory.ResolveGameAddressOrZero(kPlayerActorTick);
    std::int32_t actor_count = 0;
    uintptr_t actor_array_address = 0;
    constexpr std::int32_t kMaxReasonableActorWorldCount = 65'536;
    if (world_address == 0 ||
        resolved_player_actor_tick == 0 ||
        !memory.TryReadField(
            world_address,
            kActorWorldActorCountOffset,
            &actor_count) ||
        !memory.TryReadField(
            world_address,
            kActorWorldActorArrayOffset,
            &actor_array_address) ||
        actor_count < 0 ||
        actor_count > kMaxReasonableActorWorldCount ||
        (actor_count != 0 && actor_array_address == 0)) {
        static std::uint64_t s_last_invalid_actor_world_pause_log_ms = 0;
        const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
        if (now_ms - s_last_invalid_actor_world_pause_log_ms >= 1000) {
            s_last_invalid_actor_world_pause_log_ms = now_ms;
            Log(
                "ActorWorld_Tick held for multiplayer level-up wait, but the "
                "player-only actor list could not be read. world=" +
                HexString(world_address) +
                " count=" + std::to_string(actor_count) +
                " actors=" + HexString(actor_array_address));
        }
        return;
    }

    std::int32_t player_actor_tick_count = 0;
    std::int32_t held_non_player_actor_count = 0;
    for (std::int32_t index = 0; index < actor_count; ++index) {
        uintptr_t actor_address = 0;
        if (!memory.TryReadValue(
                actor_array_address +
                    static_cast<uintptr_t>(index) * sizeof(uintptr_t),
                &actor_address) ||
            actor_address == 0) {
            continue;
        }

        std::uint8_t pending_remove = 0;
        uintptr_t actor_vtable = 0;
        uintptr_t actor_tick_address = 0;
        if (!memory.TryReadField(
                actor_address,
                kActorPendingRemoveOffset,
                &pending_remove) ||
            pending_remove != 0 ||
            !memory.TryReadValue(actor_address, &actor_vtable) ||
            actor_vtable == 0 ||
            !memory.TryReadField(
                actor_vtable,
                kActorVtableTickOffset,
                &actor_tick_address)) {
            continue;
        }
        if (actor_tick_address != resolved_player_actor_tick) {
            held_non_player_actor_count += 1;
            continue;
        }

        if (!memory.TryWriteField(
                world_address,
                kActorWorldCurrentActorOffset,
                actor_address)) {
            break;
        }

        auto* actor = reinterpret_cast<void*>(actor_address);
        std::uint8_t pending_initialize = 0;
        if (memory.TryReadField(
                actor_address,
                kActorPendingInitializeOffset,
                &pending_initialize) &&
            pending_initialize != 0) {
            uintptr_t actor_initialize_address = 0;
            if (!memory.TryReadField(
                    actor_vtable,
                    kActorVtableInitializeOffset,
                    &actor_initialize_address) ||
                actor_initialize_address == 0 ||
                !memory.TryWriteField<std::uint8_t>(
                    actor_address,
                    kActorPendingInitializeOffset,
                    0)) {
                continue;
            }
            const auto actor_initialize =
                reinterpret_cast<ActorWorldEntryFn>(actor_initialize_address);
            actor_initialize(actor);
        }

        const auto actor_tick =
            reinterpret_cast<ActorWorldEntryFn>(actor_tick_address);
        actor_tick(actor);
        player_actor_tick_count += 1;
    }

    (void)memory.TryWriteField<uintptr_t>(
        world_address,
        kActorWorldCurrentActorOffset,
        0);
    static std::uint64_t s_last_actor_world_pause_log_ms = 0;
    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    if (now_ms - s_last_actor_world_pause_log_ms >= 1000) {
        s_last_actor_world_pause_log_ms = now_ms;
        Log(
            "ActorWorld_Tick held for multiplayer level-up wait. player_ticks=" +
            std::to_string(player_actor_tick_count) +
            " non_player_actors_held=" +
            std::to_string(held_non_player_actor_count));
    }
}

void __fastcall HookWaveSpawnerTick(void* self, void* unused_edx) {
    const auto original = GetX86HookTrampoline<WaveSpawnerTickFn>(g_state.hooks[kHookWaveSpawnerTick]);
    if (original == nullptr) return;

    const auto self_address = reinterpret_cast<uintptr_t>(self);
    g_state.last_wave_spawner.store(self_address, std::memory_order_release);
    uintptr_t self_vtable = 0;
    const bool have_self_vtable =
        self_address != 0 && ProcessMemory::Instance().TryReadValue(self_address, &self_vtable);
    if (have_self_vtable) {
        g_state.last_wave_spawner_vtable.store(self_vtable, std::memory_order_release);
        g_state.last_wave_spawner_tick_ms.store(
            static_cast<std::uint64_t>(GetTickCount64()),
            std::memory_order_release);
    }
    bool should_log_spawner = false;
    if (self_address != 0) {
        std::lock_guard<std::mutex> lock(g_state.wave_spawner_log_mutex);
        should_log_spawner = g_state.logged_wave_spawners.insert(self_address).second;
    }
    if (should_log_spawner) {
        if (have_self_vtable) {
            Log(
                "WaveSpawner_Tick invoked. self=" + HexString(self_address) +
                " vtable=" + HexString(self_vtable));
        } else {
            Log("WaveSpawner_Tick invoked. self=" + HexString(self_address) + " vtable=unreadable");
        }
    }

    PinFrozenManualRunEnemies();

    auto try_drain_manual_spawns = [&]() {
        bool dispatched_any = false;
        for (std::size_t index = 0; index < kReplicatedCatchupSpawnBurstPerSpawnerTick; ++index) {
            const auto dispatch_result =
                TryDispatchManualRunEnemySpawnFromSpawner(self, unused_edx, original);
            if (dispatch_result == ManualRunEnemySpawnerDispatchResult::Handled) {
                dispatched_any = true;
                continue;
            }
            if (dispatch_result == ManualRunEnemySpawnerDispatchResult::NoRequest) {
                break;
            }
        }
        return dispatched_any;
    };

    if (g_state.manual_enemy_spawner_test_mode.load(std::memory_order_acquire)) {
        if (try_drain_manual_spawns()) {
            PinManualRunEnemySpawnerTestModeArenaState();
            return;
        }
        PinManualRunEnemySpawnerTestModeArenaState();
        static std::uint64_t s_last_manual_test_suppress_log_ms = 0;
        const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
        if (now_ms - s_last_manual_test_suppress_log_ms >= 1000) {
            s_last_manual_test_suppress_log_ms = now_ms;
            Log("WaveSpawner_Tick suppressed for manual enemy spawner test mode. self=" + HexString(self_address));
        }
        return;
    }

    if (IsCombatPreludeOnlyActive()) {
        if (try_drain_manual_spawns()) {
            return;
        }
        static std::uint64_t s_last_prelude_suppress_log_ms = 0;
        const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
        if (now_ms - s_last_prelude_suppress_log_ms >= 1000) {
            s_last_prelude_suppress_log_ms = now_ms;
            Log("WaveSpawner_Tick suppressed for combat-prelude-only state. self=" + HexString(self_address));
        }
        return;
    }

    if (multiplayer::ShouldPauseGameplayForLevelUpSelection()) {
        static std::uint64_t s_last_level_up_pause_suppress_log_ms = 0;
        const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
        if (now_ms - s_last_level_up_pause_suppress_log_ms >= 1000) {
            s_last_level_up_pause_suppress_log_ms = now_ms;
            Log("WaveSpawner_Tick suppressed for multiplayer level-up wait. self=" + HexString(self_address));
        }
        return;
    }

    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    if (ShouldSuppressClientAuthoritativeRunWaveSpawner(now_ms)) {
        if (try_drain_manual_spawns()) {
            return;
        }
        static std::uint64_t s_last_authority_suppress_log_ms = 0;
        if (now_ms - s_last_authority_suppress_log_ms >= 1000) {
            s_last_authority_suppress_log_ms = now_ms;
            Log("WaveSpawner_Tick suppressed for host-authoritative client run. self=" + HexString(self_address));
        }
        return;
    }

    const auto previous_current_wave_spawner_tick_address = g_current_wave_spawner_tick_address;
    g_current_wave_spawner_tick_address = self_address;
    original(self, unused_edx);
    g_current_wave_spawner_tick_address = previous_current_wave_spawner_tick_address;

    // Only dispatch wave events while a run is active.
    // The game calls WaveSpawner_Tick once more after Game_OnGameOver,
    // so we must check run_active to avoid a spurious wave.started.
    if (!g_state.run_active.load(std::memory_order_acquire)) return;

    const auto wave_before = g_state.current_wave.load(std::memory_order_acquire);
    if (wave_before == 0) {
        g_state.current_wave.store(1, std::memory_order_release);
        DispatchLuaWaveStarted(1);
    }
}

void* __fastcall HookEnemySpawned(
    void* self,
    void* unused_edx,
    void* param_2,
    int enemy_config,
    void* param_4,
    int param_5,
    int param_6,
    char param_7) {
    const auto original = GetX86HookTrampoline<EnemySpawnedFn>(g_state.hooks[kHookEnemySpawned]);
    if (original == nullptr) {
        return nullptr;
    }

    auto* enemy = original(self, unused_edx, param_2, enemy_config, param_4, param_5, param_6, param_7);
    if (enemy == nullptr || !IsCombatArenaActiveForEnemyTracking()) {
        return enemy;
    }

    const auto enemy_address = reinterpret_cast<uintptr_t>(enemy);
    const auto spawn_serial = RememberEnemySpawnSerial(enemy_address);
    int enemy_type = -1;
    if (!TryReadEnemyTypeFromActor(enemy_address, &enemy_type) &&
        !TryReadEnemyTypeFromConfig(static_cast<uintptr_t>(enemy_config), &enemy_type)) {
        Log("enemy.spawned native type unavailable. enemy=" + HexString(enemy_address));
        return enemy;
    }
    float x = 0.0f;
    float y = 0.0f;
    if (!TryReadActorPosition(enemy_address, &x, &y)) {
        Log("enemy.spawned native position unavailable. enemy=" + HexString(enemy_address));
        return enemy;
    }
    RememberEnemyType(enemy_address, enemy_type);
    std::uint32_t actor_object_type = 0;
    const bool have_actor_object_type =
        TryReadActorObjectTypeForRunLifecycle(enemy_address, &actor_object_type);
    const bool arena_combat_actor_type =
        have_actor_object_type &&
        IsArenaCombatActorType(actor_object_type);
    if (arena_combat_actor_type) {
        RememberArenaEnemyWaveSpawner(g_current_wave_spawner_tick_address);
    }
    Log(
        "enemy.spawned hook invoked. enemy=" + HexString(enemy_address) +
        " spawn_serial=" + std::to_string(spawn_serial) +
        " enemy_type=" + std::to_string(enemy_type) +
        " actor_object_type=" + std::to_string(actor_object_type) +
        " pos=(" + std::to_string(x) + "," + std::to_string(y) + ")" +
        " run_active=" + std::to_string(IsRunActive() ? 1 : 0) +
        " wave_start_tracking=" +
        std::to_string(g_state.wave_start_enemy_tracking.load(std::memory_order_acquire) ? 1 : 0));

    if (g_manual_run_enemy_spawner_tick_active && !arena_combat_actor_type) {
        Log(
            "manual run enemy spawn: ignored non-arena stock spawn during controlled tick. actor=" +
            HexString(enemy_address) +
            " spawn_serial=" + std::to_string(spawn_serial) +
            " enemy_type=" + std::to_string(enemy_type) +
            " actor_object_type=" + std::to_string(actor_object_type) +
            " spawner=" + HexString(g_manual_run_enemy_spawner_tick_address));
    } else if (g_manual_run_enemy_spawner_tick_active) {
        ManualRunEnemySpawnRequest request;
        bool complete_manual_request = false;
        {
            std::lock_guard<std::mutex> lock(g_manual_run_enemy_spawn_mutex);
            if (g_have_active_manual_run_enemy_spawn) {
                request = g_active_manual_run_enemy_spawn;
                g_have_active_manual_run_enemy_spawn = false;
                g_active_manual_run_enemy_spawn = ManualRunEnemySpawnRequest{};
                if (request.freeze_on_spawn) {
                    g_frozen_manual_run_enemies[enemy_address] = FrozenManualRunEnemy{request.x, request.y};
                }
                complete_manual_request = true;
            }
        }

        if (complete_manual_request) {
            auto& memory = ProcessMemory::Instance();
            const float native_x = x;
            const float native_y = y;
            const bool wrote_x = memory.TryWriteField(enemy_address, kActorPositionXOffset, request.x);
            const bool wrote_y = memory.TryWriteField(enemy_address, kActorPositionYOffset, request.y);
            float final_x = x;
            float final_y = y;
            (void)memory.TryReadField(enemy_address, kActorPositionXOffset, &final_x);
            (void)memory.TryReadField(enemy_address, kActorPositionYOffset, &final_y);
            std::string rebind_error_message;
            const bool rebind_ok = RebindSceneActorCell(enemy_address, &rebind_error_message);

            SDModManualRunEnemySpawnResult result;
            result.valid = true;
            const bool exact_native_type =
                request.network_actor_id == 0 ||
                (have_actor_object_type &&
                 actor_object_type == static_cast<std::uint32_t>(request.type_id));
            result.ok = wrote_x && wrote_y && rebind_ok && exact_native_type;
            result.request_id = request.request_id;
            result.type_id = enemy_type >= 0 ? enemy_type : request.type_id;
            result.actor_address = enemy_address;
            result.requested_x = request.x;
            result.requested_y = request.y;
            result.x = final_x;
            result.y = final_y;
            result.wrote_x = wrote_x && std::fabs(final_x - request.x) <= 0.01f;
            result.wrote_y = wrote_y && std::fabs(final_y - request.y) <= 0.01f;
            result.rebind_ok = rebind_ok;
            result.completed_tick_ms = static_cast<std::uint64_t>(GetTickCount64());
            if (!wrote_x || !wrote_y) {
                result.error_message = "stock-spawned manual enemy was created but position write failed.";
            } else if (!rebind_ok) {
                result.error_message =
                    "stock-spawned manual enemy was relocated but cell rebind failed: " +
                    rebind_error_message;
            } else if (!exact_native_type) {
                result.error_message =
                    "actual native type did not match authority.";
            }
            x = final_x;
            y = final_y;

            {
                std::lock_guard<std::mutex> lock(g_manual_run_enemy_spawn_mutex);
                g_last_manual_run_enemy_spawn_result = result;
            }

            if (g_manual_run_enemy_spawner_tick_address != 0) {
                (void)memory.TryWriteField(
                    g_manual_run_enemy_spawner_tick_address,
                    kWaveSpawnerRemainingBudgetOffset,
                    kManualRunEnemySpawnerBudget);
                (void)memory.TryWriteField(
                    g_manual_run_enemy_spawner_tick_address,
                    kWaveSpawnerLongDelayCountdownOffset,
                    kManualRunEnemySpawnerLongDelay);
            }

            Log(
                "manual run enemy spawn: completed through stock enemy path. request_id=" +
                std::to_string(result.request_id) +
                " requested_type_id=" + std::to_string(request.type_id) +
                " actual_type_id=" + std::to_string(result.type_id) +
                " actor=" + HexString(enemy_address) +
                " spawn_serial=" + std::to_string(spawn_serial) +
                " native_pos=(" + std::to_string(native_x) + "," + std::to_string(native_y) + ")" +
                " final_pos=(" + std::to_string(final_x) + "," + std::to_string(final_y) + ")" +
                " wrote_x=" + std::to_string(result.wrote_x ? 1 : 0) +
                " wrote_y=" + std::to_string(result.wrote_y ? 1 : 0) +
                " rebind_ok=" + std::to_string(result.rebind_ok ? 1 : 0) +
                (rebind_error_message.empty()
                    ? std::string()
                    : " rebind_error=\"" + rebind_error_message + "\""));
        } else {
            Log(
                "manual run enemy spawn: extra native spawn observed during controlled spawner tick. actor=" +
                HexString(enemy_address) +
                " spawn_serial=" + std::to_string(spawn_serial) +
                " enemy_type=" + std::to_string(enemy_type));
        }
    }

    DispatchLuaEnemySpawned(enemy_type, x, y);
    return enemy;
}

int __fastcall HookEnemyDeath(void* self, void* unused_edx) {
    const auto original = GetX86HookTrampoline<EnemyDeathFn>(g_state.hooks[kHookEnemyDeath]);
    if (original == nullptr) {
        return 0;
    }

    const auto self_address = reinterpret_cast<uintptr_t>(self);
    auto& memory = ProcessMemory::Instance();
    std::uint8_t already_handled_byte = 0;
    const bool have_already_handled =
        memory.TryReadField(self_address, kEnemyDeathHandledOffset, &already_handled_byte);
    int enemy_type = LookupRememberedEnemyType(self_address);
    const bool have_enemy_type = enemy_type >= 0 || TryReadEnemyTypeFromActor(self_address, &enemy_type);
    float x = 0.0f;
    float y = 0.0f;
    const bool have_position = TryReadActorPosition(self_address, &x, &y);
    const bool already_handled_before_death =
        have_already_handled && already_handled_byte != 0;
    if (have_already_handled &&
        !already_handled_before_death &&
        IsCombatArenaActiveForEnemyTracking()) {
        multiplayer::NotifyLocalRunEnemyDeath(self_address);
    }

    const auto result = original(self, unused_edx);
    {
        std::lock_guard<std::mutex> lock(g_manual_run_enemy_spawn_mutex);
        g_frozen_manual_run_enemies.erase(self_address);
    }
    if (!have_enemy_type) {
        Log("enemy.death native type unavailable. enemy=" + HexString(self_address));
        ForgetEnemyType(self_address);
        return result;
    }
    if (!have_position) {
        Log("enemy.death native position unavailable. enemy=" + HexString(self_address));
        ForgetEnemyType(self_address);
        return result;
    }
    if (!have_already_handled) {
        Log("enemy.death native handled flag unavailable. enemy=" + HexString(self_address));
        ForgetEnemyType(self_address);
        return result;
    }
    const bool already_handled = already_handled_byte != 0;
    Log(
        "enemy.death hook invoked. enemy=" + HexString(self_address) +
        " enemy_type=" + std::to_string(enemy_type) +
        " pos=(" + std::to_string(x) + "," + std::to_string(y) + ")" +
        " already_handled=" + std::to_string(already_handled ? 1 : 0) +
        " run_active=" + std::to_string(IsRunActive() ? 1 : 0) +
        " result=" + std::to_string(result));
    ForgetEnemyType(self_address);
    if (!already_handled && IsCombatArenaActiveForEnemyTracking()) {
        DispatchLuaEnemyDeath(enemy_type, x, y, kUnknownKillMethod);
    }

    return result;
}

int __stdcall HookGoldChanged(int delta, char allow_negative) {
    const auto original = GetX86HookTrampoline<GoldChangedFn>(g_state.hooks[kHookGoldChanged]);
    if (original == nullptr) {
        return 0;
    }

    const auto return_address = reinterpret_cast<uintptr_t>(_ReturnAddress());
    const auto* source = ClassifyGoldChangeSource(return_address, delta);
    const auto result = original(delta, allow_negative);
    if (result != 0) {
        int gold = 0;
        if (TryReadResolvedGlobalInt(kGoldGlobal, &gold)) {
            DispatchLuaGoldChanged(gold, delta, source);
        } else {
            Log(
                "gold.changed native gold global unavailable. delta=" + std::to_string(delta) +
                " source=" + std::string(source));
        }
    }
    return result;
}

void __fastcall HookDropSpawned(
    void* self,
    void* unused_edx,
    std::uint32_t x_bits,
    std::uint32_t y_bits,
    int amount,
    int lifetime) {
    const auto original = GetX86HookTrampoline<DropSpawnedFn>(g_state.hooks[kHookDropSpawned]);
    if (original == nullptr) {
        return;
    }

    original(self, unused_edx, x_bits, y_bits, amount, lifetime);
    if (!IsRunActive()) {
        return;
    }

    DispatchLuaDropSpawned(kDropKindGold, BitsToFloat(x_bits), BitsToFloat(y_bits));
}

void __fastcall HookLevelUp(void* self, void* unused_edx) {
    const auto original = GetX86HookTrampoline<LevelUpFn>(g_state.hooks[kHookLevelUp]);
    if (original == nullptr) {
        return;
    }

    const auto progression_address = reinterpret_cast<uintptr_t>(self);
    auto& memory = ProcessMemory::Instance();
    int level_before = 0;
    const bool have_level_before =
        memory.TryReadField(progression_address, kProgressionLevelOffset, &level_before);
    int pending_before = 0;
    const bool have_pending_before = TryReadPendingLevelKind(&pending_before);
    const auto local_player_level_up = IsLocalPlayerProgressionForRunLifecycle(progression_address);
    const bool suppress_client_local_level_up =
        local_player_level_up && multiplayer::IsLocalTransportClient();
    // Both host and client suppress the native modal skill picker for their own
    // local-player level-up. The native picker monopolizes the gameplay thread
    // until a human dismisses it, which deadlocks the loader-driven mirror/peer
    // transform sync (the kill-loop convergence freeze). Writing non-local mode
    // around the native routine preserves the level increment but routes
    // selection through the loader's controlled, non-modal offer path for both
    // roles: the client resolves through the host authority, while the host
    // resolves its own offer locally via PublishLocalHostSelfLevelUpOffer.
    const bool suppress_local_native_picker =
        local_player_level_up &&
        (multiplayer::IsLocalTransportClient() || multiplayer::IsLocalTransportHost());
    std::uint8_t previous_progression_mode = kProgressionLocalPlayerModeValue;
    const bool have_previous_progression_mode =
        suppress_local_native_picker &&
        memory.TryReadField<std::uint8_t>(
            progression_address,
            kProgressionNonLocalModeFlagOffset,
            &previous_progression_mode);
    const bool wrote_local_level_up_gate =
        suppress_local_native_picker &&
        memory.TryWriteField<std::uint8_t>(
            progression_address,
            kProgressionNonLocalModeFlagOffset,
            kProgressionNonLocalModeValue);
    if (suppress_local_native_picker && !wrote_local_level_up_gate) {
        Log(
            "level.up local gate failed to set non-local mode before native level-up. progression=" +
            HexString(progression_address));
    }

    original(self, unused_edx);
    if (wrote_local_level_up_gate) {
        const auto restore_mode =
            have_previous_progression_mode ? previous_progression_mode : kProgressionLocalPlayerModeValue;
        if (!memory.TryWriteField<std::uint8_t>(
                progression_address,
                kProgressionNonLocalModeFlagOffset,
                restore_mode)) {
            Log(
                "level.up local gate failed to restore progression mode after native level-up. progression=" +
                HexString(progression_address) +
                " restore_mode=" + std::to_string(restore_mode));
        }
    }
    if (!IsRunActive()) {
        return;
    }

    if (!have_level_before) {
        Log(
            "level.up native level-before unavailable. progression=" +
            HexString(progression_address));
        return;
    }

    int level_after = 0;
    if (!memory.TryReadField(progression_address, kProgressionLevelOffset, &level_after)) {
        Log(
            "level.up native level-after unavailable. progression=" +
            HexString(progression_address) +
            " level_before=" + std::to_string(level_before));
        return;
    }
    if (level_after <= level_before) {
        return;
    }

    int xp_after = 0;
    if (!TryReadRunLifecycleRoundedXp(progression_address, &xp_after)) {
        Log(
            "level.up native xp unavailable. progression=" +
            HexString(progression_address) +
            " level_before=" + std::to_string(level_before) +
            " level_after=" + std::to_string(level_after));
        return;
    }
    if (!local_player_level_up || suppress_client_local_level_up) {
        if (have_pending_before) {
            RestoreNonLocalPendingLevelKind(progression_address, pending_before, level_after, xp_after);
        } else {
            Log(
                "level.up pending-level-kind global unavailable before native level-up; restore skipped. progression=" +
                HexString(progression_address) +
                " level=" + std::to_string(level_after) +
                " xp=" + std::to_string(xp_after));
        }
        if (suppress_client_local_level_up) {
            Log(
                "level.up client local picker/event gated. progression=" +
                HexString(progression_address) +
                " level=" + std::to_string(level_after) +
                " xp=" + std::to_string(xp_after));
        }
        return;
    }

    const bool suppress_level_up_side_effects =
        multiplayer::ShouldSuppressLocalLevelUpFanout();
    if (!suppress_level_up_side_effects) {
        multiplayer::SyncBotsToSharedLevelUp(level_after, xp_after, progression_address);
        multiplayer::PublishHostLevelUpBarrierOffers(
            level_after,
            xp_after,
            progression_address);
        DispatchLuaLevelUp(level_after, xp_after);
    }
}
