bool QueueHubStartTestrun(std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!g_gameplay_keyboard_injection.initialized) {
        if (error_message != nullptr) {
            *error_message = "Gameplay action pump is not initialized.";
        }
        return false;
    }

    uintptr_t arena_address = 0;
    if (!TryResolveArena(&arena_address) || arena_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Arena state is not active.";
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

    SceneContextSnapshot scene_context;
    std::string readiness_error;
    if (!TryValidateRemoteParticipantSpawnReadiness(gameplay_address, &scene_context, &readiness_error)) {
        if (error_message != nullptr) {
            *error_message = readiness_error;
        }
        return false;
    }
    if (!IsSharedHubSceneContext(scene_context)) {
        if (error_message != nullptr) {
            *error_message = "Gameplay scene is not in the shared hub.";
        }
        return false;
    }

    std::uint32_t run_generation_seed = 0;
    if (multiplayer::IsLocalTransportHost()) {
        run_generation_seed = EnsureHostRunGenerationSeed("hub_start_testrun_queue");
    } else {
        run_generation_seed = ReadPendingRunGenerationSeed();
    }

    multiplayer::SetAllBotSceneIntentsToRun();

    g_gameplay_keyboard_injection.pending_hub_start_testrun_requests.exchange(1, std::memory_order_acq_rel);
    std::uint8_t testrun_mode_flag = 0;
    uintptr_t arena_vtable = 0;
    const bool have_testrun_mode_flag =
        ProcessMemory::Instance().TryReadField(gameplay_address, kGameplayTestrunModeFlagOffset, &testrun_mode_flag);
    const bool have_arena_vtable = ProcessMemory::Instance().TryReadValue(arena_address, &arena_vtable);
    Log(
        "Queued hub testrun request. arena=" + HexString(arena_address) +
        " arena_vtable=" + (have_arena_vtable ? HexString(arena_vtable) : std::string("unreadable")) +
        " gameplay=" + HexString(gameplay_address) +
        " switch_region=" + HexString(kGameplaySwitchRegion) +
        " target_region=" + std::to_string(kArenaRegionIndex) +
        " arena_enter_dispatch=" + HexString(kArenaStartRunDispatch) +
        " create=" + HexString(kArenaCreate) +
        " run_generation_seed=" +
        (run_generation_seed != 0 ? HexString(static_cast<uintptr_t>(run_generation_seed)) : std::string("none")) +
        " testrun_mode_flag=" +
        (have_testrun_mode_flag ? std::to_string(static_cast<unsigned>(testrun_mode_flag)) : std::string("unreadable")));
    return true;
}

bool SetPendingRunGenerationSeed(std::uint32_t seed, std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!g_gameplay_keyboard_injection.initialized) {
        if (error_message != nullptr) {
            *error_message = "Gameplay action pump is not initialized.";
        }
        return false;
    }
    (void)SetPendingRunGenerationSeedInternal(seed, "network_authority");
    return true;
}

bool QueueGameplaySwitchRegion(int region_index, std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!g_gameplay_keyboard_injection.initialized) {
        if (error_message != nullptr) {
            *error_message = "Gameplay action pump is not initialized.";
        }
        return false;
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

    SceneContextSnapshot scene_context;
    if (TryBuildSceneContextSnapshot(gameplay_address, &scene_context) &&
        scene_context.current_region_index == kArenaRegionIndex &&
        region_index != kArenaRegionIndex) {
        if (error_message != nullptr) {
            *error_message =
                "Raw Gameplay_SwitchRegion cannot leave testrun safely. Use the stock UI Leave Game path instead.";
        }
        return false;
    }

    PendingGameplayRegionSwitchRequest request;
    request.region_index = region_index;
    request.next_attempt_ms = static_cast<std::uint64_t>(GetTickCount64());

    std::lock_guard<std::mutex> lock(g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
    if (g_gameplay_keyboard_injection.pending_gameplay_region_switch_requests.size() >= kQueuedGameplayWorldActionLimit) {
        if (error_message != nullptr) {
            *error_message = "The gameplay region switch queue is full.";
        }
        return false;
    }

    g_gameplay_keyboard_injection.pending_gameplay_region_switch_requests.push_back(request);
    Log("gameplay.switch_region: queued region=" + std::to_string(region_index));
    return true;
}

bool QueueMultiplayerDampenEffect(
    std::uint64_t owner_participant_id,
    std::uint32_t cast_sequence,
    float position_x,
    float position_y,
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
    if (owner_participant_id == 0 ||
        cast_sequence == 0 ||
        !std::isfinite(position_x) ||
        !std::isfinite(position_y)) {
        if (error_message != nullptr) {
            *error_message = "Dampen effect request is invalid.";
        }
        return false;
    }

    PendingMultiplayerDampenEffectRequest request{};
    request.owner_participant_id = owner_participant_id;
    request.cast_sequence = cast_sequence;
    request.position_x = position_x;
    request.position_y = position_y;

    std::lock_guard<std::mutex> lock(
        g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
    auto& pending =
        g_gameplay_keyboard_injection.pending_multiplayer_dampen_effect_requests;
    const auto duplicate = std::find_if(
        pending.begin(),
        pending.end(),
        [&](const PendingMultiplayerDampenEffectRequest& existing) {
            return existing.owner_participant_id == owner_participant_id &&
                   existing.cast_sequence == cast_sequence;
        });
    if (duplicate != pending.end()) {
        return true;
    }
    if (pending.size() >= kQueuedGameplayWorldActionLimit) {
        if (error_message != nullptr) {
            *error_message = "The multiplayer Dampen effect queue is full.";
        }
        return false;
    }
    pending.push_back(request);
    return true;
}

bool QueueLocalPlayerPoisonCorrection(
    std::int32_t duration_ticks,
    float damage_per_tick,
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
    if (duration_ticks <= 0 ||
        duration_ticks > multiplayer::kParticipantPoisonMaxDurationTicks ||
        !std::isfinite(damage_per_tick) ||
        damage_per_tick < 0.0f ||
        damage_per_tick > 10000.0f) {
        if (error_message != nullptr) {
            *error_message = "Local-player poison correction is invalid.";
        }
        return false;
    }

    PendingLocalPlayerPoisonCorrection request{};
    request.duration_ticks = duration_ticks;
    request.damage_per_tick = damage_per_tick;

    std::lock_guard<std::mutex> lock(
        g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
    auto& pending =
        g_gameplay_keyboard_injection.pending_local_player_poison_corrections;
    if (!pending.empty()) {
        auto& existing = pending.back();
        existing.duration_ticks =
            (std::max)(existing.duration_ticks, request.duration_ticks);
        existing.damage_per_tick =
            (std::max)(existing.damage_per_tick, request.damage_per_tick);
        return true;
    }
    if (pending.size() >= kQueuedGameplayWorldActionLimit) {
        if (error_message != nullptr) {
            *error_message = "The local-player poison correction queue is full.";
        }
        return false;
    }
    pending.push_back(request);
    return true;
}

bool QueueNativePoisonBehaviorProbe(
    std::uint64_t target_participant_id,
    std::int32_t duration_ticks,
    float damage_per_tick,
    std::int8_t source_slot,
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
    if (duration_ticks <= 0 ||
        duration_ticks > multiplayer::kParticipantPoisonMaxDurationTicks ||
        !std::isfinite(damage_per_tick) ||
        damage_per_tick < 0.0f ||
        damage_per_tick > 10000.0f ||
        source_slot < -1) {
        if (error_message != nullptr) {
            *error_message = "Native poison behavior probe is invalid.";
        }
        return false;
    }

    PendingNativePoisonBehaviorProbe request{};
    request.target_participant_id = target_participant_id;
    request.duration_ticks = duration_ticks;
    request.damage_per_tick = damage_per_tick;
    request.source_slot = source_slot;

    std::lock_guard<std::mutex> lock(
        g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
    auto& pending =
        g_gameplay_keyboard_injection.pending_native_poison_behavior_probes;
    if (pending.size() >= kQueuedGameplayWorldActionLimit) {
        if (error_message != nullptr) {
            *error_message = "The native poison behavior-probe queue is full.";
        }
        return false;
    }
    pending.push_back(request);
    return true;
}

bool QueueNativeMagicHitBehaviorProbe(
    float projectile_damage,
    float magic_damage,
    std::uint32_t attempts,
    std::uint64_t* request_serial,
    std::string* error_message) {
    if (request_serial != nullptr) {
        *request_serial = 0;
    }
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!g_gameplay_keyboard_injection.initialized) {
        if (error_message != nullptr) {
            *error_message = "Gameplay action pump is not initialized.";
        }
        return false;
    }
    if (!std::isfinite(projectile_damage) ||
        projectile_damage < 0.0f ||
        projectile_damage > 10000.0f ||
        !std::isfinite(magic_damage) ||
        magic_damage < 0.0f ||
        magic_damage > 10000.0f ||
        (projectile_damage <= 0.0f && magic_damage <= 0.0f) ||
        attempts == 0 ||
        attempts > 1000) {
        if (error_message != nullptr) {
            *error_message = "Native magic-hit behavior probe is invalid.";
        }
        return false;
    }

    std::lock_guard<std::mutex> lock(
        g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
    auto& pending = g_gameplay_keyboard_injection
                        .pending_native_magic_hit_behavior_probes;
    if (pending.size() >= kQueuedGameplayWorldActionLimit) {
        if (error_message != nullptr) {
            *error_message = "The native magic-hit behavior-probe queue is full.";
        }
        return false;
    }
    PendingNativeMagicHitBehaviorProbe request{};
    request.request_serial = g_gameplay_keyboard_injection
                                 .next_native_magic_hit_behavior_probe_serial++;
    if (g_gameplay_keyboard_injection
            .next_native_magic_hit_behavior_probe_serial == 0) {
        g_gameplay_keyboard_injection
            .next_native_magic_hit_behavior_probe_serial = 1;
    }
    request.projectile_damage = projectile_damage;
    request.magic_damage = magic_damage;
    request.attempts = attempts;
    pending.push_back(request);
    if (request_serial != nullptr) {
        *request_serial = request.request_serial;
    }
    return true;
}

bool GetNativeMagicHitBehaviorProbeResult(
    std::uint64_t request_serial,
    bool* completed,
    bool* success,
    float* hp_before,
    float* hp_after,
    std::string* error_message) {
    if (completed != nullptr) {
        *completed = false;
    }
    if (success != nullptr) {
        *success = false;
    }
    if (hp_before != nullptr) {
        *hp_before = 0.0f;
    }
    if (hp_after != nullptr) {
        *hp_after = 0.0f;
    }
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (request_serial == 0) {
        return false;
    }

    std::lock_guard<std::mutex> lock(
        g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
    const auto& result = g_gameplay_keyboard_injection
                             .native_magic_hit_behavior_probe_result;
    if (result.request_serial != request_serial) {
        return true;
    }
    if (completed != nullptr) {
        *completed = true;
    }
    if (success != nullptr) {
        *success = result.success;
    }
    if (hp_before != nullptr) {
        *hp_before = result.hp_before;
    }
    if (hp_after != nullptr) {
        *hp_after = result.hp_after;
    }
    if (error_message != nullptr) {
        *error_message = result.error;
    }
    return true;
}

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

bool QueueGameplayEnableCombatPrelude(std::string* error_message) {
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
    if (have_arena_state && arena_state.combat_wave_index > 0) {
        if (error_message != nullptr) {
            *error_message = "Arena waves are already active; refusing to switch to prelude-only combat state.";
        }
        return false;
    }

    g_gameplay_keyboard_injection.pending_enable_combat_prelude_requests.exchange(
        1,
        std::memory_order_acq_rel);

    Log(
        "Queued gameplay combat-prelude request. scene=" + HexString(scene_address) +
        " arena=" + HexString(arena_address) +
        " prelude_primary=" + HexString(kGameplayCombatPreludePrimaryMode) +
        " prelude_secondary=" + HexString(kGameplayCombatPreludeSecondaryMode) +
        " prelude_dispatch=" + HexString(kArenaCombatPreludeDispatch) +
        " state=" + (have_arena_state ? DescribeArenaWaveStartState(arena_state) : std::string("unreadable")));
    return true;
}
