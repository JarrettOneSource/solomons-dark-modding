void __fastcall HookCreateArena(void* self, void* unused_edx) {
    const auto original = GetX86HookTrampoline<RunStartedFn>(g_state.hooks[kHookCreateArena]);
    if (original == nullptr) return;
    g_state.current_wave.store(0, std::memory_order_release);
    g_state.run_active.store(true, std::memory_order_release);
    g_state.last_wave_spawner.store(0, std::memory_order_release);
    g_state.last_consumed_spell_click_serial.store(0, std::memory_order_release);
    g_state.run_start_tick_ms.store(static_cast<std::uint64_t>(GetTickCount64()), std::memory_order_release);
    g_state.combat_prelude_only_suppression.store(false, std::memory_order_release);
    ClearRememberedEnemyTypes();
    original(self, unused_edx);
    DispatchLuaRunStarted();
}

void __fastcall HookStartGame(void* self, void* unused_edx) {
    const auto original = GetX86HookTrampoline<RunStartedFn>(g_state.hooks[kHookStartGame]);
    if (original == nullptr) return;
    g_state.current_wave.store(0, std::memory_order_release);
    g_state.run_active.store(true, std::memory_order_release);
    g_state.last_wave_spawner.store(0, std::memory_order_release);
    g_state.last_consumed_spell_click_serial.store(0, std::memory_order_release);
    g_state.run_start_tick_ms.store(static_cast<std::uint64_t>(GetTickCount64()), std::memory_order_release);
    g_state.combat_prelude_only_suppression.store(false, std::memory_order_release);
    ClearRememberedEnemyTypes();
    original(self, unused_edx);
    DispatchLuaRunStarted();
}

void __cdecl HookRunEnded() {
    const auto original = GetX86HookTrampoline<RunEndedFn>(g_state.hooks[kHookRunEnded]);
    if (original == nullptr) return;
    g_state.run_active.store(false, std::memory_order_release);
    original();
    CompleteRunLifecycleEnd("death", true);
}

void __fastcall HookWaveSpawnerTick(void* self, void* unused_edx) {
    const auto original = GetX86HookTrampoline<WaveSpawnerTickFn>(g_state.hooks[kHookWaveSpawnerTick]);
    if (original == nullptr) return;

    const auto self_address = reinterpret_cast<uintptr_t>(self);
    if (IsCombatPreludeOnlyActive()) {
        static std::uint64_t s_last_prelude_suppress_log_ms = 0;
        const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
        if (now_ms - s_last_prelude_suppress_log_ms >= 1000) {
            s_last_prelude_suppress_log_ms = now_ms;
            Log("WaveSpawner_Tick suppressed for combat-prelude-only state. self=" + HexString(self_address));
        }
        return;
    }

    const auto previous_self = g_state.last_wave_spawner.exchange(self_address, std::memory_order_acq_rel);
    if (self_address != 0 && previous_self != self_address) {
        uintptr_t self_vtable = 0;
        if (ProcessMemory::Instance().TryReadValue(self_address, &self_vtable)) {
            Log(
                "WaveSpawner_Tick invoked. self=" + HexString(self_address) +
                " vtable=" + HexString(self_vtable));
        } else {
            Log("WaveSpawner_Tick invoked. self=" + HexString(self_address) + " vtable=unreadable");
        }
    }

    original(self, unused_edx);

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
    Log(
        "enemy.spawned hook invoked. enemy=" + HexString(enemy_address) +
        " enemy_type=" + std::to_string(enemy_type) +
        " pos=(" + std::to_string(x) + "," + std::to_string(y) + ")" +
        " run_active=" + std::to_string(IsRunActive() ? 1 : 0) +
        " wave_start_tracking=" +
        std::to_string(g_state.wave_start_enemy_tracking.load(std::memory_order_acquire) ? 1 : 0));
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

    const auto result = original(self, unused_edx);
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
    original(self, unused_edx);
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
    if (!local_player_level_up) {
        if (have_pending_before) {
            RestoreNonLocalPendingLevelKind(progression_address, pending_before, level_after, xp_after);
        } else {
            Log(
                "level.up pending-level-kind global unavailable before native level-up; restore skipped. progression=" +
                HexString(progression_address) +
                " level=" + std::to_string(level_after) +
                " xp=" + std::to_string(xp_after));
        }
        return;
    }

    multiplayer::SyncBotsToSharedLevelUp(level_after, xp_after, progression_address);
    DispatchLuaLevelUp(level_after, xp_after);
}
