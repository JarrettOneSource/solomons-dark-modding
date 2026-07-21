bool IsRunLifecycleActive() {
    return g_state.run_active.load(std::memory_order_acquire);
}

bool EndRunLifecycleFromExternal(std::string_view reason) {
    if (!g_state.run_active.exchange(false, std::memory_order_acq_rel)) {
        return false;
    }

    CompleteRunLifecycleEnd(reason, true);
    return true;
}

int GetRunLifecycleCurrentWave() {
    return g_state.current_wave.load(std::memory_order_acquire);
}

std::uint64_t GetRunLifecycleElapsedMilliseconds() {
    const auto started_at = g_state.run_start_tick_ms.load(std::memory_order_acquire);
    if (started_at == 0) {
        return 0;
    }

    const auto now = static_cast<std::uint64_t>(GetTickCount64());
    return now >= started_at ? now - started_at : 0;
}

void GetRunLifecycleTrackedEnemies(std::vector<SDModTrackedEnemyState>* enemies) {
    if (enemies == nullptr) {
        return;
    }

    enemies->clear();
    if (!IsCombatArenaActiveForEnemyTracking()) {
        return;
    }

    SDModSceneState scene_state;
    const bool have_scene =
        TryGetSceneState(&scene_state) && scene_state.valid && scene_state.world_address != 0;
    auto& memory = ProcessMemory::Instance();

    std::lock_guard<std::mutex> lock(g_state.enemy_type_mutex);
    enemies->reserve(g_state.enemy_types_by_address.size());
    for (auto it = g_state.enemy_types_by_address.begin();
         it != g_state.enemy_types_by_address.end();) {
        const auto actor_address = it->first;
        if (have_scene) {
            uintptr_t owner_address = 0;
            if (!memory.TryReadField(actor_address, kActorOwnerOffset, &owner_address) ||
                owner_address != scene_state.world_address) {
                g_state.enemy_spawn_serials_by_address.erase(actor_address);
                it = g_state.enemy_types_by_address.erase(it);
                continue;
            }
        }

        enemies->push_back({actor_address, it->second});
        ++it;
    }
}

bool TryGetRunLifecycleEnemySpawnSerial(uintptr_t enemy_address, std::uint32_t* spawn_serial) {
    return LookupEnemySpawnSerial(enemy_address, spawn_serial);
}

bool TryAccelerateRunLifecycleEnemyPoolForSnapshot(int enemy_type, std::uint32_t missing_enemy_count) {
    if (missing_enemy_count == 0 || !IsCombatArenaActiveForEnemyTracking()) {
        return false;
    }

    constexpr std::int32_t kMaxReasonableEnemyPoolCatchUpBudget = 128;

    const auto spawner_address = g_state.last_wave_spawner.load(std::memory_order_acquire);
    if (spawner_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    if (!memory.IsReadableRange(spawner_address, kWaveSpawnerLongDelayCountdownOffset + sizeof(std::int32_t))) {
        return false;
    }

    std::int32_t remaining_budget = 0;
    if (!memory.TryReadField(spawner_address, kWaveSpawnerRemainingBudgetOffset, &remaining_budget) ||
        remaining_budget <= 0 ||
        remaining_budget > kMaxReasonableEnemyPoolCatchUpBudget) {
        return false;
    }

    const auto requested = static_cast<std::int32_t>(
        (std::min<std::uint32_t>)(missing_enemy_count, static_cast<std::uint32_t>(remaining_budget)));
    const auto accelerated_budget = static_cast<std::int32_t>(
        (std::min<std::uint32_t>)(
            missing_enemy_count,
            static_cast<std::uint32_t>(kMaxReasonableEnemyPoolCatchUpBudget)));
    const bool wrote_budget =
        memory.TryWriteField(
            spawner_address,
            kWaveSpawnerRemainingBudgetOffset,
            (std::max)(remaining_budget, accelerated_budget));
    const bool wrote_spawn_delay =
        memory.TryWriteField(spawner_address, kWaveSpawnerSpawnDelayCountdownOffset, static_cast<std::int32_t>(0));
    const bool wrote_long_delay =
        memory.TryWriteField(spawner_address, kWaveSpawnerLongDelayCountdownOffset, static_cast<std::int32_t>(0));
    if (!wrote_budget || !wrote_spawn_delay || !wrote_long_delay) {
        return false;
    }

    static std::uint64_t s_last_pool_accelerate_log_ms = 0;
    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    if (now_ms - s_last_pool_accelerate_log_ms >= 1000) {
        s_last_pool_accelerate_log_ms = now_ms;
        Log(
            "run.lifecycle enemy pool catch-up. spawner=" + HexString(spawner_address) +
            " enemy_type=" + std::to_string(enemy_type) +
            " missing=" + std::to_string(missing_enemy_count) +
            " requested=" + std::to_string(requested) +
            " remaining_budget=" + std::to_string(remaining_budget) +
            " accelerated_budget=" + std::to_string(accelerated_budget));
    }
    return true;
}

uintptr_t GetRunLifecycleLastWaveSpawnerAddress() {
    return g_state.last_wave_spawner.load(std::memory_order_acquire);
}

bool IsRememberedWaveSpawnerVtableValid(uintptr_t spawner_address, uintptr_t remembered_vtable) {
    if (spawner_address == 0 || remembered_vtable == 0) {
        return false;
    }

    uintptr_t current_vtable = 0;
    return ProcessMemory::Instance().TryReadValue(spawner_address, &current_vtable) &&
        current_vtable == remembered_vtable;
}

bool TryGetPreferredManualRunEnemySpawner(uintptr_t* spawner_address, uintptr_t* remembered_vtable) {
    if (spawner_address == nullptr || remembered_vtable == nullptr) {
        return false;
    }

    *spawner_address = 0;
    *remembered_vtable = 0;

    const auto arena_spawner =
        g_state.last_arena_enemy_wave_spawner.load(std::memory_order_acquire);
    const auto arena_vtable =
        g_state.last_arena_enemy_wave_spawner_vtable.load(std::memory_order_acquire);
    if (IsRememberedWaveSpawnerVtableValid(arena_spawner, arena_vtable)) {
        *spawner_address = arena_spawner;
        *remembered_vtable = arena_vtable;
        return true;
    }

    const auto generic_spawner = g_state.last_wave_spawner.load(std::memory_order_acquire);
    const auto generic_vtable = g_state.last_wave_spawner_vtable.load(std::memory_order_acquire);
    const auto last_tick_ms = g_state.last_wave_spawner_tick_ms.load(std::memory_order_acquire);
    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    if (last_tick_ms == 0 || now_ms - last_tick_ms > kManualRunEnemySpawnerFreshnessWindowMs) {
        return false;
    }
    if (!IsRememberedWaveSpawnerVtableValid(generic_spawner, generic_vtable)) {
        return false;
    }

    *spawner_address = generic_spawner;
    *remembered_vtable = generic_vtable;
    return true;
}

bool IsRunLifecycleManualEnemySpawnerReady() {
    if (!g_state.manual_enemy_spawner_test_mode.load(std::memory_order_acquire)) {
        return false;
    }

    uintptr_t spawner_address = 0;
    uintptr_t remembered_vtable = 0;
    return TryGetPreferredManualRunEnemySpawner(&spawner_address, &remembered_vtable);
}

bool QueueRunLifecycleEnemySpawnRequestInternal(
    std::uint64_t network_actor_id,
    int type_id,
    float x,
    float y,
    bool allow_active_waves,
    bool freeze_on_spawn,
    std::string* error_message,
    std::uint64_t* request_id) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (request_id != nullptr) {
        *request_id = 0;
    }
    if (type_id <= 0) {
        if (error_message != nullptr) {
            *error_message = "manual run enemy spawn: invalid type_id.";
        }
        return false;
    }
    if (!std::isfinite(x) || !std::isfinite(y)) {
        if (error_message != nullptr) {
            *error_message = "manual run enemy spawn: position must be finite.";
        }
        return false;
    }
    if (!IsCombatArenaActiveForEnemyTracking()) {
        if (error_message != nullptr) {
            *error_message = "manual run enemy spawn: combat arena is not active.";
        }
        return false;
    }

    SDModGameplayCombatState combat_state;
    if (!TryGetGameplayCombatState(&combat_state) || !combat_state.valid) {
        if (error_message != nullptr) {
            *error_message = "manual run enemy spawn: combat state is unavailable.";
        }
        return false;
    }
    if (combat_state.combat_wave_index > 0 && !allow_active_waves) {
        if (error_message != nullptr) {
            *error_message = "manual run enemy spawn: refusing while native waves are active.";
        }
        return false;
    }

    ManualRunEnemySpawnRequest request;
    request.request_id = g_next_manual_run_enemy_spawn_request_id++;
    request.network_actor_id = network_actor_id;
    request.type_id = type_id;
    request.x = x;
    request.y = y;
    request.allow_active_waves = allow_active_waves;
    request.freeze_on_spawn = freeze_on_spawn;

    std::lock_guard<std::mutex> lock(g_manual_run_enemy_spawn_mutex);
    if (!freeze_on_spawn && allow_active_waves) {
        if (g_have_pending_manual_run_enemy_spawn &&
            g_pending_manual_run_enemy_spawn.network_actor_id != 0 &&
            g_pending_manual_run_enemy_spawn.network_actor_id == network_actor_id) {
            if (request_id != nullptr) {
                *request_id = g_pending_manual_run_enemy_spawn.request_id;
            }
            return true;
        }
        if (g_have_active_manual_run_enemy_spawn &&
            g_active_manual_run_enemy_spawn.network_actor_id != 0 &&
            g_active_manual_run_enemy_spawn.network_actor_id == network_actor_id) {
            if (request_id != nullptr) {
                *request_id = g_active_manual_run_enemy_spawn.request_id;
            }
            return true;
        }
        const auto already_queued = std::find_if(
            g_queued_replicated_run_enemy_spawns.begin(),
            g_queued_replicated_run_enemy_spawns.end(),
            [&](const ManualRunEnemySpawnRequest& queued) {
                return queued.network_actor_id != 0 &&
                       queued.network_actor_id == network_actor_id;
            });
        if (already_queued != g_queued_replicated_run_enemy_spawns.end()) {
            if (request_id != nullptr) {
                *request_id = already_queued->request_id;
            }
            return true;
        }
        if (g_queued_replicated_run_enemy_spawns.size() >= kQueuedReplicatedRunEnemySpawnLimit) {
            if (error_message != nullptr) {
                *error_message = "manual run enemy spawn: replicated catch-up queue is full.";
            }
            return false;
        }
        g_queued_replicated_run_enemy_spawns.push_back(request);
    } else {
        if (g_have_pending_manual_run_enemy_spawn ||
            g_have_active_manual_run_enemy_spawn ||
            !g_queued_replicated_run_enemy_spawns.empty()) {
            if (error_message != nullptr) {
                *error_message = "manual run enemy spawn: a previous request is still pending.";
            }
            return false;
        }
        g_pending_manual_run_enemy_spawn = request;
        g_have_pending_manual_run_enemy_spawn = true;
    }

    if (request_id != nullptr) {
        *request_id = request.request_id;
    }

    Log(
        "manual run enemy spawn: queued stock-spawner request. request_id=" +
        std::to_string(request.request_id) +
        " network_actor_id=" + std::to_string(request.network_actor_id) +
        " type_id=" + std::to_string(type_id) +
        " requested_pos=(" + std::to_string(x) + "," + std::to_string(y) + ")" +
        " allow_active_waves=" + std::to_string(request.allow_active_waves ? 1 : 0) +
        " freeze_on_spawn=" + std::to_string(request.freeze_on_spawn ? 1 : 0));
    return true;
}

bool QueueRunLifecycleManualEnemySpawn(
    int type_id,
    float x,
    float y,
    bool freeze_on_spawn,
    std::string* error_message,
    std::uint64_t* request_id) {
    if (!IsRunLifecycleManualEnemySpawnerReady()) {
        if (error_message != nullptr) {
            *error_message =
                "manual run enemy spawn: stock wave spawner is not ready.";
        }
        if (request_id != nullptr) {
            *request_id = 0;
        }
        return false;
    }
    return QueueRunLifecycleEnemySpawnRequestInternal(
        0,
        type_id,
        x,
        y,
        g_state.manual_enemy_spawner_test_mode.load(std::memory_order_acquire),
        freeze_on_spawn,
        error_message,
        request_id);
}

bool QueueRunLifecycleReplicatedEnemyCatchupSpawn(
    std::uint64_t network_actor_id,
    int type_id,
    float x,
    float y,
    std::string* error_message,
    std::uint64_t* request_id) {
    return QueueRunLifecycleEnemySpawnRequestInternal(
        network_actor_id,
        type_id,
        x,
        y,
        true,
        false,
        error_message,
        request_id);
}

void CancelQueuedRunLifecycleReplicatedEnemyCatchupSpawn(std::uint64_t network_actor_id) {
    if (network_actor_id == 0) {
        return;
    }

    std::lock_guard<std::mutex> lock(g_manual_run_enemy_spawn_mutex);
    if (g_have_pending_manual_run_enemy_spawn &&
        g_pending_manual_run_enemy_spawn.network_actor_id == network_actor_id &&
        g_pending_manual_run_enemy_spawn.allow_active_waves &&
        !g_pending_manual_run_enemy_spawn.freeze_on_spawn) {
        g_pending_manual_run_enemy_spawn = ManualRunEnemySpawnRequest{};
        g_have_pending_manual_run_enemy_spawn = false;
    }
    for (auto it = g_queued_replicated_run_enemy_spawns.begin();
         it != g_queued_replicated_run_enemy_spawns.end();) {
        if (it->network_actor_id == network_actor_id) {
            it = g_queued_replicated_run_enemy_spawns.erase(it);
            continue;
        }
        ++it;
    }
}

bool CompletePendingDirectManualRunEnemySpawnFailure(
    std::string_view error_message) {
    ManualRunEnemySpawnRequest request;
    {
        std::lock_guard<std::mutex> lock(g_manual_run_enemy_spawn_mutex);
        if (!g_have_pending_manual_run_enemy_spawn ||
            g_pending_manual_run_enemy_spawn.network_actor_id != 0) {
            return false;
        }
        request = g_pending_manual_run_enemy_spawn;
        g_pending_manual_run_enemy_spawn = ManualRunEnemySpawnRequest{};
        g_have_pending_manual_run_enemy_spawn = false;
    }
    CompleteManualRunEnemySpawnFailure(request, error_message);
    return true;
}

bool PumpRunLifecycleManualEnemySpawnRequest(std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }

    {
        std::lock_guard<std::mutex> lock(g_manual_run_enemy_spawn_mutex);
        const bool have_any_pending_request =
            g_have_pending_manual_run_enemy_spawn || !g_queued_replicated_run_enemy_spawns.empty();
        if (!have_any_pending_request || g_have_active_manual_run_enemy_spawn) {
            return false;
        }
    }

    uintptr_t spawner_address = 0;
    uintptr_t remembered_vtable = 0;
    if (!TryGetPreferredManualRunEnemySpawner(&spawner_address, &remembered_vtable)) {
        constexpr std::string_view kSpawnerUnavailable =
            "manual run enemy spawn: stock wave spawner became unavailable.";
        if (CompletePendingDirectManualRunEnemySpawnFailure(kSpawnerUnavailable)) {
            return true;
        }
        if (error_message != nullptr) {
            *error_message = std::string(kSpawnerUnavailable);
        }
        return false;
    }

    const auto dispatch_result = TryDispatchManualRunEnemySpawnFromSpawner(
        reinterpret_cast<void*>(spawner_address));
    if (dispatch_result == ManualRunEnemySpawnerDispatchResult::Handled) {
        Log(
            "manual run enemy spawn: dispatched from remembered stock spawner. spawner=" +
            HexString(spawner_address));
        return true;
    }
    if (error_message != nullptr) {
        *error_message = "manual run enemy spawn: remembered stock wave spawner did not accept the request.";
    }
    return false;
}

bool TryGetRunLifecycleManualEnemySpawnResult(
    SDModManualRunEnemySpawnResult* result,
    std::uint64_t request_id) {
    if (result == nullptr) {
        return false;
    }

    std::lock_guard<std::mutex> lock(g_manual_run_enemy_spawn_mutex);
    if (!g_last_manual_run_enemy_spawn_result.valid ||
        (request_id != 0 && g_last_manual_run_enemy_spawn_result.request_id != request_id)) {
        *result = SDModManualRunEnemySpawnResult{};
        return false;
    }

    *result = g_last_manual_run_enemy_spawn_result;
    return true;
}

bool TryGetRunLifecycleManualEnemyFreezePosition(uintptr_t actor_address, float* x, float* y) {
    if (actor_address == 0 || x == nullptr || y == nullptr) {
        return false;
    }

    std::lock_guard<std::mutex> lock(g_manual_run_enemy_spawn_mutex);
    const auto found = g_frozen_manual_run_enemies.find(actor_address);
    if (found == g_frozen_manual_run_enemies.end()) {
        return false;
    }
    *x = found->second.x;
    *y = found->second.y;
    return true;
}

bool RestoreRunLifecycleFrozenManualEnemyPosition(uintptr_t actor_address) {
    float frozen_x = 0.0f;
    float frozen_y = 0.0f;
    if (!TryGetRunLifecycleManualEnemyFreezePosition(
            actor_address,
            &frozen_x,
            &frozen_y)) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    float current_x = 0.0f;
    float current_y = 0.0f;
    const bool position_is_current =
        memory.TryReadField(
            actor_address,
            kActorPositionXOffset,
            &current_x) &&
        memory.TryReadField(
            actor_address,
            kActorPositionYOffset,
            &current_y) &&
        std::abs(current_x - frozen_x) <= 0.001f &&
        std::abs(current_y - frozen_y) <= 0.001f;
    if (position_is_current) {
        return true;
    }

    if (!memory.TryWriteField(
            actor_address,
            kActorPositionXOffset,
            frozen_x) ||
        !memory.TryWriteField(
            actor_address,
            kActorPositionYOffset,
            frozen_y)) {
        return false;
    }

    std::string rebind_error;
    if (!RebindSceneActorCell(actor_address, &rebind_error)) {
        Log(
            "Frozen manual enemy spatial rebind failed. actor=" +
            HexString(actor_address) + " error=" + rebind_error);
        return false;
    }
    return true;
}

void PinRunLifecycleFrozenManualEnemies() {
    PinFrozenManualRunEnemies();
}

void ClearRunLifecycleManualEnemyFreeze(uintptr_t actor_address) {
    std::lock_guard<std::mutex> lock(g_manual_run_enemy_spawn_mutex);
    if (actor_address == 0) {
        g_frozen_manual_run_enemies.clear();
        return;
    }
    g_frozen_manual_run_enemies.erase(actor_address);
}

void SetRunLifecycleCombatPreludeOnlySuppression(bool enabled) {
    g_state.combat_prelude_only_suppression.store(enabled, std::memory_order_release);
}

void SetRunLifecycleWaveStartEnemyTracking(bool enabled) {
    g_state.wave_start_enemy_tracking.store(enabled, std::memory_order_release);
}

static void CancelRememberedWaveSpawnerProductionForManualTestMode() {
    uintptr_t spawner_address = 0;
    uintptr_t remembered_vtable = 0;
    if (!TryGetPreferredManualRunEnemySpawner(
            &spawner_address,
            &remembered_vtable)) {
        return;
    }

    (void)ProcessMemory::Instance().TryWriteField<std::int32_t>(
        spawner_address,
        kWaveSpawnerRemainingBudgetOffset,
        0);
}

void SetRunLifecycleManualEnemySpawnerTestMode(bool enabled) {
    const bool previous = g_state.manual_enemy_spawner_test_mode.exchange(
        enabled,
        std::memory_order_acq_rel);
    if (enabled) {
        PinManualRunEnemySpawnerTestModeArenaState();
        CancelRememberedWaveSpawnerProductionForManualTestMode();
    }
    if (previous == enabled) {
        return;
    }
    Log(
        "manual run enemy spawn: stock-spawner test mode " +
        std::string(enabled ? "enabled" : "disabled") + ".");
}

bool IsRunLifecycleManualEnemySpawnerTestModeEnabled() {
    return g_state.manual_enemy_spawner_test_mode.load(std::memory_order_acquire);
}

bool InitializeRunLifecycleHooks(std::string* error_message) {
    if (error_message != nullptr) error_message->clear();
    if (g_state.initialized) return true;

    if (!InitializeGameplaySeams(error_message)) {
        return false;
    }

    HookTarget targets[kHookCount] = {};
    BuildHookTargets(targets);

    uintptr_t resolved[kHookCount] = {};
    for (size_t i = 0; i < kHookCount; ++i) {
        resolved[i] = ProcessMemory::Instance().ResolveGameAddressOrZero(targets[i].address);
        if (resolved[i] == 0) {
            if (error_message != nullptr) {
                *error_message = "Unable to resolve lifecycle hook target at " + HexString(targets[i].address);
            }
            return false;
        }
    }

    void* detours[] = {
        reinterpret_cast<void*>(&HookCreateArena),
        reinterpret_cast<void*>(&HookMainMenuControlAction),
        reinterpret_cast<void*>(&HookStartGame),
        reinterpret_cast<void*>(&HookRunEnded),
        reinterpret_cast<void*>(&HookActorWorldTick),
        reinterpret_cast<void*>(&HookWaveSpawnerTick),
        reinterpret_cast<void*>(&HookEnemySpawned),
        reinterpret_cast<void*>(&HookEnemyDeath),
        reinterpret_cast<void*>(&HookSpellCast_3EB),
        reinterpret_cast<void*>(&HookSpellCast_018),
        reinterpret_cast<void*>(&HookAirLightningChainTarget),
        reinterpret_cast<void*>(&HookSpellCast_020),
        reinterpret_cast<void*>(&HookSpellCast_028),
        reinterpret_cast<void*>(&HookSpellCast_3EC),
        reinterpret_cast<void*>(&HookSpellCast_3ED),
        reinterpret_cast<void*>(&HookSpellCast_3EE),
        reinterpret_cast<void*>(&HookSpellCast_3EF),
        reinterpret_cast<void*>(&HookSpellCast_3F0),
        reinterpret_cast<void*>(&HookGoldChanged),
        reinterpret_cast<void*>(&HookDropSpawned),
        reinterpret_cast<void*>(&HookLevelUp),
    };
    const char* names[] = {
        "create_arena",
        "main_menu.control_action",
        "start_game",
        "run.ended",
        "actor_world.tick",
        "wave.spawner_tick",
        "enemy.spawned",
        "enemy.death",
        "spell.cast.0x3eb",
        "spell.cast.0x18",
        "spell.air.chain_target",
        "spell.cast.0x20",
        "spell.cast.0x28",
        "spell.cast.0x3ec",
        "spell.cast.0x3ed",
        "spell.cast.0x3ee",
        "spell.cast.0x3ef",
        "spell.cast.0x3f0",
        "gold.changed",
        "drop.spawned",
        "level.up",
    };

    HookSpec specs[kHookCount] = {};
    for (size_t i = 0; i < kHookCount; ++i) {
        specs[i] = {reinterpret_cast<void*>(resolved[i]), targets[i].patch_size, detours[i], names[i]};
    }

    if (!InstallHookSet(specs, kHookCount, g_state.hooks, error_message)) {
        return false;
    }

    g_state.current_wave.store(0, std::memory_order_release);
    g_state.run_active.store(false, std::memory_order_release);
    ResetRunLifecycleBookkeeping();
    g_state.initialized = true;

    std::string log_line = "Run lifecycle hooks installed.";
    for (size_t i = 0; i < kHookCount; ++i) {
        log_line += " " + std::string(names[i]) + "=" + HexString(resolved[i]);
    }
    Log(log_line);
    return true;
}

void ShutdownRunLifecycleHooks() {
    RemoveHookSet(g_state.hooks, kHookCount);
    g_state.current_wave.store(0, std::memory_order_release);
    g_state.run_active.store(false, std::memory_order_release);
    ResetRunLifecycleBookkeeping();
    g_state.initialized = false;
}
