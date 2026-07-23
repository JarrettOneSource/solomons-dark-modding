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
        float hp = 0.0f;
        if (!memory.TryReadField(actor_address, kEnemyCurrentHpOffset, &hp) ||
            !std::isfinite(hp) ||
            hp <= 0.05f) {
            stale_enemies.push_back(actor_address);
            continue;
        }
        ClearFrozenManualRunEnemyControlState(actor_address);
        (void)RestoreRunLifecycleFrozenManualEnemyPosition(actor_address);
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
    result.content_id = request.lua_config.content_id;
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

void RetireInvalidFeaturedEnemyAfterExactSpawn(
    const ManualRunEnemySpawnRequest& request) {
    uintptr_t spawned_actor_address = 0;
    {
        std::lock_guard<std::mutex> lock(g_manual_run_enemy_spawn_mutex);
        if (!g_last_manual_run_enemy_spawn_result.valid ||
            g_last_manual_run_enemy_spawn_result.request_id != request.request_id) {
            return;
        }
        spawned_actor_address = g_last_manual_run_enemy_spawn_result.actor_address;
    }
    if (spawned_actor_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t enemy_config_address = 0;
    if (!memory.TryReadField(
            spawned_actor_address,
            kEnemyConfigOffset,
            &enemy_config_address) ||
        enemy_config_address != 0) {
        return;
    }

    const auto gameplay_global_address =
        memory.ResolveGameAddressOrZero(kGameObjectGlobal);
    uintptr_t gameplay_address = 0;
    if (gameplay_global_address == 0 ||
        !memory.TryReadValue(gameplay_global_address, &gameplay_address) ||
        gameplay_address == 0) {
        return;
    }

    uintptr_t featured_enemy_actor = 0;
    if (!memory.TryReadField(
            gameplay_address,
            kGameplayFeaturedEnemyActorOffset,
            &featured_enemy_actor) ||
        featured_enemy_actor != spawned_actor_address) {
        return;
    }

    if (memory.TryWriteField<uintptr_t>(
            gameplay_address,
            kGameplayFeaturedEnemyActorOffset,
            0)) {
        Log(
            "exact enemy spawn: retired invalid featured-enemy reference. actor=" +
            HexString(spawned_actor_address) +
            " request_id=" + std::to_string(request.request_id));
    }
}

ManualRunEnemySpawnerDispatchResult DispatchExactRunEnemySpawn(
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
            "exact run enemy spawn is unavailable.");
        return ManualRunEnemySpawnerDispatchResult::Handled;
    }

    const auto previous_current_spawner =
        g_current_wave_spawner_tick_address;
    const bool previous_manual_tick = g_manual_run_enemy_spawner_tick_active;
    g_current_wave_spawner_tick_address = spawner_address;
    g_manual_run_enemy_spawner_tick_active = true;

    ManualRunEnemySpawnerDispatchException exception;
    const bool call_ok = CallSpawnExactEnemyGroupSafe(
        reinterpret_cast<SpawnExactEnemyGroupFn>(spawn_address),
        combat_state.arena_address,
        static_cast<std::uint32_t>(request.type_id),
        modifier_array_vtable,
        free_address,
        &exception);

    RetireInvalidFeaturedEnemyAfterExactSpawn(request);

    g_manual_run_enemy_spawner_tick_active = previous_manual_tick;
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
            "exact run enemy spawn raised 0x" +
                HexString(exception.code) + ".");
    } else if (still_active) {
        CompleteManualRunEnemySpawnFailure(
            request,
            "exact run enemy spawn created no enemy.");
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

ManualRunEnemySpawnerDispatchResult TryDispatchManualRunEnemySpawnFromSpawner(
    void* self) {
    if (self == nullptr) {
        return ManualRunEnemySpawnerDispatchResult::NoRequest;
    }

    ManualRunEnemySpawnRequest request;
    {
        std::lock_guard<std::mutex> lock(g_manual_run_enemy_spawn_mutex);
        const bool have_any_pending_request =
            g_have_pending_manual_run_enemy_spawn || !g_queued_run_enemy_spawns.empty();
        if (!have_any_pending_request || g_have_active_manual_run_enemy_spawn) {
            return ManualRunEnemySpawnerDispatchResult::NoRequest;
        }
        if (g_have_pending_manual_run_enemy_spawn) {
            request = g_pending_manual_run_enemy_spawn;
            g_pending_manual_run_enemy_spawn = ManualRunEnemySpawnRequest{};
            g_have_pending_manual_run_enemy_spawn = false;
        } else {
            request = g_queued_run_enemy_spawns.front();
            g_queued_run_enemy_spawns.pop_front();
        }
        g_active_manual_run_enemy_spawn = request;
        g_have_active_manual_run_enemy_spawn = true;
    }

    const auto spawner_address = reinterpret_cast<uintptr_t>(self);
    Log(
        "manual run enemy spawn: dispatching exact stock class. request_id=" +
        std::to_string(request.request_id) +
        " type_id=" + std::to_string(request.type_id) +
        " spawner=" + HexString(spawner_address) +
        " requested_pos=(" + std::to_string(request.x) + "," +
        std::to_string(request.y) + ")");
    return DispatchExactRunEnemySpawn(request, spawner_address);
}
