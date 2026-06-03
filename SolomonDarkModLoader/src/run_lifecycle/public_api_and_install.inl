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

bool TryAccelerateRunLifecycleEnemyPoolForSnapshot(std::uint32_t missing_enemy_count) {
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
    const bool wrote_spawn_delay =
        memory.TryWriteField(spawner_address, kWaveSpawnerSpawnDelayCountdownOffset, static_cast<std::int32_t>(0));
    const bool wrote_long_delay =
        memory.TryWriteField(spawner_address, kWaveSpawnerLongDelayCountdownOffset, static_cast<std::int32_t>(0));
    if (!wrote_spawn_delay || !wrote_long_delay) {
        return false;
    }

    static std::uint64_t s_last_pool_accelerate_log_ms = 0;
    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    if (now_ms - s_last_pool_accelerate_log_ms >= 1000) {
        s_last_pool_accelerate_log_ms = now_ms;
        Log(
            "run.lifecycle enemy pool catch-up. spawner=" + HexString(spawner_address) +
            " missing=" + std::to_string(missing_enemy_count) +
            " requested=" + std::to_string(requested) +
            " remaining_budget=" + std::to_string(remaining_budget));
    }
    return true;
}

void SetRunLifecycleCombatPreludeOnlySuppression(bool enabled) {
    g_state.combat_prelude_only_suppression.store(enabled, std::memory_order_release);
}

void SetRunLifecycleWaveStartEnemyTracking(bool enabled) {
    g_state.wave_start_enemy_tracking.store(enabled, std::memory_order_release);
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
        reinterpret_cast<void*>(&HookStartGame),
        reinterpret_cast<void*>(&HookRunEnded),
        reinterpret_cast<void*>(&HookWaveSpawnerTick),
        reinterpret_cast<void*>(&HookEnemySpawned),
        reinterpret_cast<void*>(&HookEnemyDeath),
        reinterpret_cast<void*>(&HookSpellCast_3EB),
        reinterpret_cast<void*>(&HookSpellCast_018),
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
        "start_game",
        "run.ended",
        "wave.spawner_tick",
        "enemy.spawned",
        "enemy.death",
        "spell.cast.0x3eb",
        "spell.cast.0x18",
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
