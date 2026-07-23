enum class LuaWaveSpawnConfigWriteResult {
    Applied,
    RestoredAfterFailure,
    RetiredAfterRestoreFailure,
};

enum class LuaWaveSpawnInstanceClaim {
    New,
    Existing,
};

constexpr std::int32_t kMaximumCapturedWaveSpawnCount = 4096;
constexpr std::int32_t kMaximumCapturedWaveDelayTicks = 1'000'000;

void LogLuaWaveSpawnFilterHookFailure(
    std::atomic<std::uint32_t>* log_count,
    const std::string& message) {
    if (log_count != nullptr &&
        log_count->fetch_add(1, std::memory_order_relaxed) <
            kMaximumLuaWaveSpawnFilterHookLogCount) {
        Log("[lua] " + message);
    }
}

bool TryCaptureLuaWaveSpawnFilterContext(
    uintptr_t spawner_address,
    LuaWaveSpawnFilterContext* context,
    uintptr_t* vtable_address) {
    if (spawner_address == 0 || context == nullptr || vtable_address == nullptr) {
        return false;
    }

    *context = LuaWaveSpawnFilterContext{};
    *vtable_address = 0;
    context->spawner_address = spawner_address;

    auto& memory = ProcessMemory::Instance();
    std::uint8_t randomize_delay = 0;
    std::uint8_t sequential_groups = 0;
    bool captured = memory.TryReadValue(spawner_address, vtable_address);
    captured = memory.TryReadField(
        spawner_address,
        kWaveSpawnerActionRecordOffset,
        &context->action_record_address) && captured;
    captured = memory.TryReadField(
        spawner_address,
        kWaveSpawnerRemainingBudgetOffset,
        &context->count) && captured;
    captured = memory.TryReadField(
        spawner_address,
        kWaveSpawnerSpawnDelayCountdownOffset,
        &context->spawn_delay_remaining) && captured;
    captured = memory.TryReadField(
        spawner_address,
        kWaveSpawnerSpawnDelayBaseOffset,
        &context->spawn_delay) && captured;
    captured = memory.TryReadField(
        spawner_address,
        kWaveSpawnerLongDelayCountdownOffset,
        &context->wave_delay) && captured;
    captured = memory.TryReadField(
        spawner_address,
        kWaveSpawnerRandomizeDelayOffset,
        &randomize_delay) && captured;
    captured = memory.TryReadField(
        spawner_address,
        kWaveSpawnerSequentialGroupsOffset,
        &sequential_groups) && captured;
    if (!captured || *vtable_address == 0 ||
        context->action_record_address == 0 || context->count < 0 ||
        context->count > kMaximumCapturedWaveSpawnCount ||
        context->spawn_delay_remaining < -1 ||
        context->spawn_delay_remaining > kMaximumCapturedWaveDelayTicks ||
        context->spawn_delay < 0 ||
        context->spawn_delay > kMaximumCapturedWaveDelayTicks ||
        context->wave_delay < 0 ||
        context->wave_delay > kMaximumCapturedWaveDelayTicks ||
        randomize_delay > 1 || sequential_groups > 1) {
        return false;
    }

    context->randomize_spawn_delay = randomize_delay != 0;
    context->sequential_groups = sequential_groups != 0;
    SDModGameplayCombatState combat_state;
    if (TryGetGameplayCombatState(&combat_state) && combat_state.valid) {
        context->wave_index = combat_state.combat_wave_index;
    }
    return true;
}

LuaWaveSpawnInstanceClaim ClaimLuaWaveSpawnFilterInstance(
    uintptr_t spawner_address,
    uintptr_t action_record_address,
    uintptr_t vtable_address) {
    std::lock_guard<std::mutex> lock(g_state.wave_spawn_filter_mutex);
    auto& instances = g_state.wave_spawn_filter_instances;
    const auto found = instances.find(spawner_address);
    if (found != instances.end() &&
        found->second.action_record_address == action_record_address &&
        found->second.vtable_address == vtable_address) {
        return LuaWaveSpawnInstanceClaim::Existing;
    }
    instances[spawner_address] = {
        action_record_address,
        vtable_address,
    };
    return LuaWaveSpawnInstanceClaim::New;
}

bool RestoreLuaWaveSpawnFilterState(
    const LuaWaveSpawnFilterContext& context) {
    auto& memory = ProcessMemory::Instance();
    bool restored = memory.TryWriteField(
        context.spawner_address,
        kWaveSpawnerSpawnDelayCountdownOffset,
        context.spawn_delay_remaining);
    restored = memory.TryWriteField(
        context.spawner_address,
        kWaveSpawnerSpawnDelayBaseOffset,
        context.spawn_delay) && restored;
    restored = memory.TryWriteField(
        context.spawner_address,
        kWaveSpawnerLongDelayCountdownOffset,
        context.wave_delay) && restored;
    restored = memory.TryWriteField<std::uint8_t>(
        context.spawner_address,
        kWaveSpawnerRandomizeDelayOffset,
        context.randomize_spawn_delay ? 1 : 0) && restored;
    restored = memory.TryWriteField(
        context.spawner_address,
        kWaveSpawnerRemainingBudgetOffset,
        context.count) && restored;
    return restored;
}

LuaWaveSpawnConfigWriteResult WriteLuaWaveSpawnFilterState(
    const LuaWaveSpawnFilterContext& original,
    const LuaWaveSpawnFilterContext& filtered) {
    auto& memory = ProcessMemory::Instance();
    bool wrote_all = memory.TryWriteField(
        filtered.spawner_address,
        kWaveSpawnerSpawnDelayCountdownOffset,
        filtered.spawn_delay_remaining);
    wrote_all = memory.TryWriteField(
        filtered.spawner_address,
        kWaveSpawnerSpawnDelayBaseOffset,
        filtered.spawn_delay) && wrote_all;
    wrote_all = memory.TryWriteField(
        filtered.spawner_address,
        kWaveSpawnerLongDelayCountdownOffset,
        filtered.wave_delay) && wrote_all;
    wrote_all = memory.TryWriteField<std::uint8_t>(
        filtered.spawner_address,
        kWaveSpawnerRandomizeDelayOffset,
        filtered.randomize_spawn_delay ? 1 : 0) && wrote_all;
    wrote_all = memory.TryWriteField(
        filtered.spawner_address,
        kWaveSpawnerRemainingBudgetOffset,
        filtered.count) && wrote_all;
    if (wrote_all) {
        return LuaWaveSpawnConfigWriteResult::Applied;
    }
    if (RestoreLuaWaveSpawnFilterState(original)) {
        return LuaWaveSpawnConfigWriteResult::RestoredAfterFailure;
    }

    (void)memory.TryWriteField<std::int32_t>(
        original.spawner_address,
        kWaveSpawnerRemainingBudgetOffset,
        0);
    return LuaWaveSpawnConfigWriteResult::RetiredAfterRestoreFailure;
}

bool LuaWaveSpawnFilterContextChanged(
    const LuaWaveSpawnFilterContext& original,
    const LuaWaveSpawnFilterContext& filtered) {
    return original.count != filtered.count ||
        original.spawn_delay_remaining != filtered.spawn_delay_remaining ||
        original.spawn_delay != filtered.spawn_delay ||
        original.wave_delay != filtered.wave_delay ||
        original.randomize_spawn_delay != filtered.randomize_spawn_delay;
}

bool PrepareLuaWaveSpawnFilter(
    uintptr_t spawner_address,
    uintptr_t* action_record_address,
    uintptr_t* vtable_address) {
    if (action_record_address == nullptr || vtable_address == nullptr ||
        !HasLuaWaveSpawnFilterHandlers() ||
        multiplayer::IsLocalTransportClient() ||
        !g_state.run_active.load(std::memory_order_acquire)) {
        return false;
    }

    LuaWaveSpawnFilterContext context;
    if (!TryCaptureLuaWaveSpawnFilterContext(
            spawner_address,
            &context,
            vtable_address)) {
        LogLuaWaveSpawnFilterHookFailure(
            &g_lua_wave_spawn_filter_capture_log_count,
            "wave.spawning skipped because the stock spawner state could not "
            "be captured. spawner=" + HexString(spawner_address));
        return false;
    }
    *action_record_address = context.action_record_address;

    const auto claim = ClaimLuaWaveSpawnFilterInstance(
        spawner_address,
        context.action_record_address,
        *vtable_address);
    if (claim == LuaWaveSpawnInstanceClaim::Existing || context.count == 0) {
        return true;
    }

    const auto original_context = context;
    if (!ApplyLuaWaveSpawnFilters(&context)) {
        context.count = 0;
    }
    if (!LuaWaveSpawnFilterContextChanged(original_context, context)) {
        return true;
    }

    const auto write_result = WriteLuaWaveSpawnFilterState(
        original_context,
        context);
    if (write_result != LuaWaveSpawnConfigWriteResult::Applied) {
        LogLuaWaveSpawnFilterHookFailure(
            &g_lua_wave_spawn_filter_write_log_count,
            "wave.spawning rewrite failed. spawner=" +
                HexString(spawner_address) + " record=" +
                HexString(context.action_record_address) + " restored=" +
                (write_result ==
                         LuaWaveSpawnConfigWriteResult::RestoredAfterFailure
                     ? "1"
                     : "0"));
    }
    return true;
}

void FinishLuaWaveSpawnFilterTick(
    uintptr_t spawner_address,
    uintptr_t expected_action_record_address,
    uintptr_t expected_vtable_address) {
    auto& memory = ProcessMemory::Instance();
    uintptr_t current_vtable_address = 0;
    uintptr_t current_action_record_address = 0;
    std::int32_t remaining_count = 0;
    const bool still_active = memory.TryReadValue(
        spawner_address,
        &current_vtable_address) &&
        memory.TryReadField(
            spawner_address,
            kWaveSpawnerActionRecordOffset,
            &current_action_record_address) &&
        memory.TryReadField(
            spawner_address,
            kWaveSpawnerRemainingBudgetOffset,
            &remaining_count) &&
        current_vtable_address == expected_vtable_address &&
        current_action_record_address == expected_action_record_address &&
        remaining_count > 0;
    if (still_active) {
        return;
    }

    std::lock_guard<std::mutex> lock(g_state.wave_spawn_filter_mutex);
    const auto found =
        g_state.wave_spawn_filter_instances.find(spawner_address);
    if (found != g_state.wave_spawn_filter_instances.end() &&
        found->second.action_record_address == expected_action_record_address &&
        found->second.vtable_address == expected_vtable_address) {
        g_state.wave_spawn_filter_instances.erase(found);
    }
}

void __fastcall HookWaveSpawnerTick(void* self, void* unused_edx) {
    const auto original = GetX86HookTrampoline<WaveSpawnerTickFn>(
        g_state.hooks[kHookWaveSpawnerTick]);
    if (original == nullptr) {
        return;
    }

    const auto self_address = reinterpret_cast<uintptr_t>(self);
    g_state.last_wave_spawner.store(self_address, std::memory_order_release);
    uintptr_t self_vtable = 0;
    const bool have_self_vtable = self_address != 0 &&
        ProcessMemory::Instance().TryReadValue(self_address, &self_vtable);
    if (have_self_vtable) {
        g_state.last_wave_spawner_vtable.store(
            self_vtable,
            std::memory_order_release);
        g_state.last_wave_spawner_tick_ms.store(
            static_cast<std::uint64_t>(GetTickCount64()),
            std::memory_order_release);
    }
    bool should_log_spawner = false;
    if (self_address != 0) {
        std::lock_guard<std::mutex> lock(g_state.wave_spawner_log_mutex);
        should_log_spawner =
            g_state.logged_wave_spawners.insert(self_address).second;
    }
    if (should_log_spawner) {
        Log(
            "WaveSpawner_Tick invoked. self=" + HexString(self_address) +
            (have_self_vtable
                 ? " vtable=" + HexString(self_vtable)
                 : " vtable=unreadable"));
    }

    PinFrozenManualRunEnemies();

    auto try_drain_manual_spawns = [&]() {
        bool dispatched_any = false;
        for (std::size_t index = 0;
             index < kReplicatedCatchupSpawnBurstPerSpawnerTick;
             ++index) {
            const auto dispatch_result =
                TryDispatchManualRunEnemySpawnFromSpawner(self);
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
            Log(
                "WaveSpawner_Tick suppressed for manual enemy spawner test "
                "mode. self=" + HexString(self_address));
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
            Log(
                "WaveSpawner_Tick suppressed for combat-prelude-only state. "
                "self=" + HexString(self_address));
        }
        return;
    }

    if (multiplayer::ShouldPauseMultiplayerGameplay()) {
        static std::uint64_t s_last_shared_simulation_hold_log_ms = 0;
        const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
        if (now_ms - s_last_shared_simulation_hold_log_ms >= 1000) {
            s_last_shared_simulation_hold_log_ms = now_ms;
            Log(
                "WaveSpawner_Tick suppressed for shared simulation control. self=" +
                HexString(self_address));
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
            Log(
                "WaveSpawner_Tick suppressed for host-authoritative client "
                "run. self=" + HexString(self_address));
        }
        return;
    }

    uintptr_t filtered_action_record_address = 0;
    uintptr_t filtered_vtable_address = 0;
    const bool tracked_filter_instance = PrepareLuaWaveSpawnFilter(
        self_address,
        &filtered_action_record_address,
        &filtered_vtable_address);

    LuaWaveSpawnFilterContext wave_context_before;
    uintptr_t wave_context_vtable = 0;
    const bool track_wave_summary =
        g_state.run_active.load(std::memory_order_acquire) &&
        TryCaptureLuaWaveSpawnFilterContext(
            self_address,
            &wave_context_before,
            &wave_context_vtable);
    WaveSummaryUpdate wave_started;
    if (track_wave_summary) {
        wave_started = ObserveAuthorityWaveSpawner(
            self_address,
            wave_context_before.action_record_address,
            wave_context_before.count,
            wave_context_before.wave_index);
        if (wave_started.summary.valid) {
            const auto current_wave =
                g_state.current_wave.load(std::memory_order_acquire);
            g_state.current_wave.store(
                (std::max)(current_wave, wave_started.summary.wave),
                std::memory_order_release);
        }
        if (wave_started.started_wave != 0) {
            DispatchLuaWaveStarted(wave_started.summary);
        }
        if (wave_started.completed_wave != 0) {
            DispatchLuaWaveCompleted(wave_started.completed_wave);
        }
    }

    const auto previous_current_wave_spawner_tick_address =
        g_current_wave_spawner_tick_address;
    const auto previous_current_wave_number = g_current_wave_number;
    g_current_wave_spawner_tick_address = self_address;
    g_current_wave_number = track_wave_summary
        ? wave_started.summary.wave
        : 0;
    original(self, unused_edx);
    g_current_wave_spawner_tick_address =
        previous_current_wave_spawner_tick_address;
    g_current_wave_number = previous_current_wave_number;

    if (track_wave_summary &&
        g_state.run_active.load(std::memory_order_acquire)) {
        LuaWaveSpawnFilterContext wave_context_after;
        uintptr_t wave_context_after_vtable = 0;
        const bool captured_after = TryCaptureLuaWaveSpawnFilterContext(
            self_address,
            &wave_context_after,
            &wave_context_after_vtable);
        const auto remaining_after =
            captured_after &&
                wave_context_after.action_record_address ==
                    wave_context_before.action_record_address
            ? wave_context_after.count
            : 0;
        const auto wave_update = ObserveAuthorityWaveSpawner(
            self_address,
            wave_context_before.action_record_address,
            remaining_after,
            wave_context_before.wave_index);
        if (wave_update.completed_wave != 0) {
            DispatchLuaWaveCompleted(wave_update.completed_wave);
        }
    }

    if (tracked_filter_instance) {
        FinishLuaWaveSpawnFilterTick(
            self_address,
            filtered_action_record_address,
            filtered_vtable_address);
    }

}
