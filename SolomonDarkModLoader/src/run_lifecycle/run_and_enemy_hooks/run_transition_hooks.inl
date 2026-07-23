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
    ResetWaveIntelligenceRun();
    g_state.current_wave.store(0, std::memory_order_release);
    g_state.run_active.store(true, std::memory_order_release);
    g_state.last_wave_spawner.store(0, std::memory_order_release);
    g_state.last_wave_spawner_vtable.store(0, std::memory_order_release);
    g_state.last_wave_spawner_tick_ms.store(0, std::memory_order_release);
    g_state.last_arena_enemy_wave_spawner.store(0, std::memory_order_release);
    g_state.last_arena_enemy_wave_spawner_vtable.store(0, std::memory_order_release);
    g_state.last_arena_enemy_wave_spawner_tick_ms.store(0, std::memory_order_release);
    g_state.last_dispatched_lua_spell_click_serial.store(0, std::memory_order_release);
    g_state.run_start_tick_ms.store(static_cast<std::uint64_t>(GetTickCount64()), std::memory_order_release);
    g_state.combat_prelude_only_suppression.store(false, std::memory_order_release);
    {
        std::lock_guard<std::mutex> lock(g_state.wave_spawner_log_mutex);
        g_state.logged_wave_spawners.clear();
    }
    ClearLuaWaveSpawnFilterInstances();
    ClearRememberedEnemyTracking();
    if (!ReinitializeAppliedRunGenerationSeedForArenaCreate("arena_create_pre_stock")) {
        g_state.run_active.store(false, std::memory_order_release);
        Log("Blocked multiplayer Arena_Create because the host Boneyard seed could not be reinitialized.");
        return;
    }
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
    ResetWaveIntelligenceRun();
    g_state.current_wave.store(0, std::memory_order_release);
    g_state.run_active.store(true, std::memory_order_release);
    g_state.last_wave_spawner.store(0, std::memory_order_release);
    g_state.last_wave_spawner_vtable.store(0, std::memory_order_release);
    g_state.last_wave_spawner_tick_ms.store(0, std::memory_order_release);
    g_state.last_arena_enemy_wave_spawner.store(0, std::memory_order_release);
    g_state.last_arena_enemy_wave_spawner_vtable.store(0, std::memory_order_release);
    g_state.last_arena_enemy_wave_spawner_tick_ms.store(0, std::memory_order_release);
    g_state.last_dispatched_lua_spell_click_serial.store(0, std::memory_order_release);
    g_state.run_start_tick_ms.store(static_cast<std::uint64_t>(GetTickCount64()), std::memory_order_release);
    g_state.combat_prelude_only_suppression.store(false, std::memory_order_release);
    {
        std::lock_guard<std::mutex> lock(g_state.wave_spawner_log_mutex);
        g_state.logged_wave_spawners.clear();
    }
    ClearLuaWaveSpawnFilterInstances();
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
