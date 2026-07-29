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

bool QueueGameplayEnableCombatPrelude(
    bool recover_untracked_wave,
    std::string* error_message) {
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

    ArenaWaveStartState arena_state;
    const bool have_arena_state = TryReadArenaWaveStartState(arena_address, &arena_state);
    int enemy_count = 0;
    const bool untracked_wave_recovery_allowed =
        recover_untracked_wave &&
        GetRunLifecycleCurrentWave() == 0 &&
        TryReadResolvedGlobalInt(kEnemyCountGlobal, &enemy_count) &&
        enemy_count == 0;
    if (have_arena_state &&
        arena_state.combat_wave_index > 0 &&
        !untracked_wave_recovery_allowed) {
        if (error_message != nullptr) {
            *error_message =
                recover_untracked_wave
                ? "Arena wave recovery requires zero tracked waves and zero enemies."
                : "Arena waves are already active; refusing to switch to prelude-only combat state.";
        }
        return false;
    }

    g_gameplay_keyboard_injection
        .pending_enable_combat_prelude_recover_untracked_wave.store(
            untracked_wave_recovery_allowed,
            std::memory_order_release);
    g_gameplay_keyboard_injection.pending_enable_combat_prelude_requests.exchange(
        1,
        std::memory_order_acq_rel);

    Log(
        "Queued gameplay combat-prelude request. scene=" + HexString(scene_address) +
        " arena=" + HexString(arena_address) +
        " prelude_primary=" + HexString(kGameplayCombatPreludePrimaryMode) +
        " prelude_secondary=" + HexString(kGameplayCombatPreludeSecondaryMode) +
        " prelude_dispatch=" + HexString(kArenaCombatPreludeDispatch) +
        " recover_untracked_wave=" +
        std::to_string(
            static_cast<unsigned>(
                untracked_wave_recovery_allowed)) +
        " state=" + (have_arena_state ? DescribeArenaWaveStartState(arena_state) : std::string("unreadable")));
    return true;
}
