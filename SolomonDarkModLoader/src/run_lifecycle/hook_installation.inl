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
        resolved[i] =
            ProcessMemory::Instance().ResolveGameAddressOrZero(
                targets[i].address);
        if (resolved[i] == 0) {
            if (error_message != nullptr) {
                *error_message =
                    "Unable to resolve lifecycle hook target at " +
                    HexString(targets[i].address);
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
        reinterpret_cast<void*>(&HookDropSelector),
        reinterpret_cast<void*>(&HookSpellCast_3EB),
        reinterpret_cast<void*>(&HookSpellCast_018),
        reinterpret_cast<void*>(&HookAirLightningPrimaryTargetRefresh),
        reinterpret_cast<void*>(&HookAirLightningChainTarget),
        reinterpret_cast<void*>(&HookSpellCast_020),
        reinterpret_cast<void*>(&HookSpellCast_028),
        reinterpret_cast<void*>(&HookSpellCast_3EC),
        reinterpret_cast<void*>(&HookSpellCast_3ED),
        reinterpret_cast<void*>(&HookSpellCast_3EE),
        reinterpret_cast<void*>(&HookSpellCast_3EF),
        reinterpret_cast<void*>(&HookSpellCast_3F0),
        reinterpret_cast<void*>(&HookGoldChanged),
        reinterpret_cast<void*>(&HookExperienceGain),
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
        "drop.rolling",
        "spell.cast.0x3eb",
        "spell.cast.0x18",
        "spell.air.primary_target_refresh",
        "spell.air.chain_target",
        "spell.cast.0x20",
        "spell.cast.0x28",
        "spell.cast.0x3ec",
        "spell.cast.0x3ed",
        "spell.cast.0x3ee",
        "spell.cast.0x3ef",
        "spell.cast.0x3f0",
        "gold.changed",
        "experience.gain",
        "drop.spawned",
        "level.up",
    };

    HookSpec specs[kHookCount] = {};
    for (size_t i = 0; i < kHookCount; ++i) {
        specs[i] = {
            reinterpret_cast<void*>(resolved[i]),
            targets[i].patch_size,
            detours[i],
            names[i],
        };
    }

    if (!InstallHookSet(
            specs,
            kHookCount,
            g_state.hooks,
            error_message)) {
        return false;
    }

    g_state.current_wave.store(0, std::memory_order_release);
    g_state.run_active.store(false, std::memory_order_release);
    ResetRunLifecycleBookkeeping();
    g_state.initialized = true;

    std::string log_line = "Run lifecycle hooks installed.";
    for (size_t i = 0; i < kHookCount; ++i) {
        log_line +=
            " " + std::string(names[i]) + "=" + HexString(resolved[i]);
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
