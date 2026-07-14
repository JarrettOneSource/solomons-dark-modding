thread_local bool g_allow_gameplay_action_pump_in_gameplay = false;

void PumpQueuedGameplayActions() {
    lua_exec_diag::g_last_pump_enter_ms.store(
        static_cast<std::uint64_t>(GetTickCount64()),
        std::memory_order_release);
    std::lock_guard<std::recursive_mutex> pump_lock(g_gameplay_action_pump_mutex);
    lua_exec_diag::g_last_pump_locked_ms.store(
        static_cast<std::uint64_t>(GetTickCount64()),
        std::memory_order_release);

    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    uintptr_t active_gameplay_address = 0;
    const bool gameplay_active =
        TryResolveCurrentGameplayScene(&active_gameplay_address) &&
        active_gameplay_address != 0;
    if (gameplay_active) {
        PinRunLifecycleFrozenManualEnemies();
    }

    // EndScene and HookPlayerActorTick both call this pump. Always drain
    // pipe-exec on the main thread. When gameplay is inactive, also emit
    // runtime.tick here so front-end automation and other menu-time Lua
    // mods can advance before a gameplay scene exists.
    if (!gameplay_active) {
        const SDModRuntimeTickContext lua_tick_context = {
            sizeof(SDModRuntimeTickContext),
            GetRuntimeTickServiceIntervalMs(),
            0,
            now_ms,
        };
        PumpLuaWorkOnMainThread(lua_tick_context);
    } else {
        PumpLuaExecQueueOnMainThread();
    }

    const auto wizard_bot_sync_not_before_ms =
        g_gameplay_keyboard_injection.wizard_bot_sync_not_before_ms.load(std::memory_order_acquire);

    auto pending =
        g_gameplay_keyboard_injection.pending_hub_start_testrun_requests.load(std::memory_order_acquire);
    if (!g_allow_gameplay_action_pump_in_gameplay) {
        while (pending > 0) {
            if (!g_gameplay_keyboard_injection.pending_hub_start_testrun_requests.compare_exchange_weak(
                    pending,
                    pending - 1,
                    std::memory_order_acq_rel,
                    std::memory_order_acquire)) {
                continue;
            }

            if (!TryDispatchHubStartTestrunOnGameThread()) {
                g_gameplay_keyboard_injection.pending_hub_start_testrun_requests.fetch_add(
                    1,
                    std::memory_order_acq_rel);
            }
            break;
        }
    }

    if (!g_allow_gameplay_action_pump_in_gameplay && gameplay_active) {
        const bool allow_level_up_picker_create =
            multiplayer::HasLocalLevelUpOfferAwaitingNativePresentation();
        multiplayer::ReconcileLocalLevelUpOfferPresentation(
            now_ms,
            allow_level_up_picker_create);
        return;
    }

    pending = g_gameplay_keyboard_injection.pending_start_waves_requests.load(std::memory_order_acquire);
    while (pending > 0) {
        if (!g_gameplay_keyboard_injection.pending_start_waves_requests.compare_exchange_weak(
                pending,
                pending - 1,
                std::memory_order_acq_rel,
                std::memory_order_acquire)) {
            continue;
        }

        if (!TryDispatchStartWavesOnGameThread()) {
            g_gameplay_keyboard_injection.pending_start_waves_requests.fetch_add(
                1,
                std::memory_order_acq_rel);
        }
        break;
    }

    pending = g_gameplay_keyboard_injection.pending_enable_combat_prelude_requests.load(std::memory_order_acquire);
    while (pending > 0) {
        if (!g_gameplay_keyboard_injection.pending_enable_combat_prelude_requests.compare_exchange_weak(
                pending,
                pending - 1,
                std::memory_order_acq_rel,
                std::memory_order_acquire)) {
            continue;
        }

        if (!TryEnableCombatPreludeOnGameThread()) {
            g_gameplay_keyboard_injection.pending_enable_combat_prelude_requests.fetch_add(
                1,
                std::memory_order_acq_rel);
        }
        break;
    }

    if (gameplay_active) {
        static std::uint64_t s_last_manual_spawn_pump_failure_log_ms = 0;
        constexpr std::size_t kManualSpawnPumpBurst = 4;
        for (std::size_t index = 0; index < kManualSpawnPumpBurst; ++index) {
            std::string manual_spawn_error;
            if (PumpRunLifecycleManualEnemySpawnRequest(&manual_spawn_error)) {
                continue;
            }
            if (!manual_spawn_error.empty()) {
                const auto failure_now_ms = static_cast<std::uint64_t>(GetTickCount64());
                if (failure_now_ms - s_last_manual_spawn_pump_failure_log_ms >= 1000) {
                    s_last_manual_spawn_pump_failure_log_ms = failure_now_ms;
                    Log("manual run enemy spawn: gameplay pump failed. error=" + manual_spawn_error);
                }
            }
            break;
        }
    }

    PendingRewardSpawnRequest reward_request;
    bool have_reward_request = false;
    std::vector<PendingClientLocalLootSuppressionRequest> client_local_loot_suppression_requests;
    std::vector<PendingMultiplayerDampenEffectRequest> multiplayer_dampen_effect_requests;
    PendingLocalPlayerPoisonCorrection local_player_poison_correction;
    bool have_local_player_poison_correction = false;
    std::vector<PendingNativePoisonBehaviorProbe> native_poison_behavior_probes;
    std::vector<PendingNativeMagicHitBehaviorProbe>
        native_magic_hit_behavior_probes;
    std::vector<PendingNativeStaffEffectProbe>
        native_staff_effect_probes;
    PendingParticipantEntitySyncRequest participant_sync_request;
    bool have_participant_sync_request = false;
    PendingGameplayRegionSwitchRequest region_switch_request;
    bool have_region_switch_request = false;
    multiplayer::LootSnapshotRuntimeInfo replicated_loot_snapshot;
    bool have_replicated_loot_snapshot = false;
    std::vector<std::uint64_t> destroy_requests;
    {
        std::lock_guard<std::mutex> lock(g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
        if (wizard_bot_sync_not_before_ms <= now_ms &&
            !g_gameplay_keyboard_injection.pending_participant_sync_requests.empty()) {
            const auto pending_sync_count =
                g_gameplay_keyboard_injection.pending_participant_sync_requests.size();
            for (std::size_t index = 0; index < pending_sync_count; ++index) {
                auto pending_request = g_gameplay_keyboard_injection.pending_participant_sync_requests.front();
                g_gameplay_keyboard_injection.pending_participant_sync_requests.pop_front();
                if (!have_participant_sync_request && pending_request.next_attempt_ms <= now_ms) {
                    participant_sync_request = pending_request;
                    have_participant_sync_request = true;
                    g_gameplay_keyboard_injection.wizard_bot_sync_not_before_ms.store(
                        now_ms + kWizardBotSyncDispatchSpacingMs,
                        std::memory_order_release);
                    continue;
                }

                g_gameplay_keyboard_injection.pending_participant_sync_requests.push_back(pending_request);
            }
        }
        const auto region_switch_not_before_ms =
            g_gameplay_keyboard_injection.gameplay_region_switch_not_before_ms.load(std::memory_order_acquire);
        if (region_switch_not_before_ms <= now_ms &&
            !g_gameplay_keyboard_injection.pending_gameplay_region_switch_requests.empty()) {
            const auto pending_region_switch_count =
                g_gameplay_keyboard_injection.pending_gameplay_region_switch_requests.size();
            for (std::size_t index = 0; index < pending_region_switch_count; ++index) {
                auto pending_request = g_gameplay_keyboard_injection.pending_gameplay_region_switch_requests.front();
                g_gameplay_keyboard_injection.pending_gameplay_region_switch_requests.pop_front();
                if (!have_region_switch_request && pending_request.next_attempt_ms <= now_ms) {
                    region_switch_request = pending_request;
                    have_region_switch_request = true;
                    g_gameplay_keyboard_injection.gameplay_region_switch_not_before_ms.store(
                        now_ms + kGameplayRegionSwitchDispatchSpacingMs,
                        std::memory_order_release);
                    continue;
                }

                g_gameplay_keyboard_injection.pending_gameplay_region_switch_requests.push_back(pending_request);
            }
        }
        while (!g_gameplay_keyboard_injection.pending_participant_destroy_requests.empty()) {
            destroy_requests.push_back(g_gameplay_keyboard_injection.pending_participant_destroy_requests.front());
            g_gameplay_keyboard_injection.pending_participant_destroy_requests.pop_front();
        }
        if (!g_gameplay_keyboard_injection.pending_reward_spawn_requests.empty()) {
            reward_request = std::move(g_gameplay_keyboard_injection.pending_reward_spawn_requests.front());
            g_gameplay_keyboard_injection.pending_reward_spawn_requests.pop_front();
            have_reward_request = true;
        }
        if (!g_gameplay_keyboard_injection.pending_client_local_loot_suppression_requests.empty()) {
            const auto pending_suppression_count =
                g_gameplay_keyboard_injection.pending_client_local_loot_suppression_requests.size();
            for (std::size_t index = 0; index < pending_suppression_count; ++index) {
                auto request = std::move(
                    g_gameplay_keyboard_injection.pending_client_local_loot_suppression_requests.front());
                g_gameplay_keyboard_injection.pending_client_local_loot_suppression_requests.pop_front();
                if (request.not_before_ms <= now_ms) {
                    client_local_loot_suppression_requests.push_back(std::move(request));
                    continue;
                }
                g_gameplay_keyboard_injection.pending_client_local_loot_suppression_requests.push_back(
                    std::move(request));
            }
        }
        if (!g_gameplay_keyboard_injection.pending_replicated_loot_snapshots.empty()) {
            replicated_loot_snapshot =
                std::move(g_gameplay_keyboard_injection.pending_replicated_loot_snapshots.back());
            g_gameplay_keyboard_injection.pending_replicated_loot_snapshots.clear();
            have_replicated_loot_snapshot = true;
        }
        while (!g_gameplay_keyboard_injection
                    .pending_multiplayer_dampen_effect_requests.empty()) {
            multiplayer_dampen_effect_requests.push_back(
                g_gameplay_keyboard_injection
                    .pending_multiplayer_dampen_effect_requests.front());
            g_gameplay_keyboard_injection
                .pending_multiplayer_dampen_effect_requests.pop_front();
        }
        if (!g_gameplay_keyboard_injection
                 .pending_local_player_poison_corrections.empty()) {
            local_player_poison_correction = g_gameplay_keyboard_injection
                                                 .pending_local_player_poison_corrections
                                                 .back();
            g_gameplay_keyboard_injection
                .pending_local_player_poison_corrections.clear();
            have_local_player_poison_correction = true;
        }
        while (!g_gameplay_keyboard_injection
                    .pending_native_poison_behavior_probes.empty()) {
            native_poison_behavior_probes.push_back(
                g_gameplay_keyboard_injection
                    .pending_native_poison_behavior_probes.front());
            g_gameplay_keyboard_injection
                .pending_native_poison_behavior_probes.pop_front();
        }
        while (!g_gameplay_keyboard_injection
                    .pending_native_magic_hit_behavior_probes.empty()) {
            native_magic_hit_behavior_probes.push_back(
                g_gameplay_keyboard_injection
                    .pending_native_magic_hit_behavior_probes.front());
            g_gameplay_keyboard_injection
                .pending_native_magic_hit_behavior_probes.pop_front();
        }
        while (!g_gameplay_keyboard_injection
                    .pending_native_staff_effect_probes.empty()) {
            native_staff_effect_probes.push_back(
                g_gameplay_keyboard_injection
                    .pending_native_staff_effect_probes.front());
            g_gameplay_keyboard_injection
                .pending_native_staff_effect_probes.pop_front();
        }
    }

    if (have_local_player_poison_correction) {
        SDModPlayerState player_state;
        std::string poison_error;
        bool applied = false;
        if (!TryGetPlayerState(&player_state) ||
            !player_state.valid ||
            player_state.actor_address == 0) {
            poison_error = "local player actor is unavailable";
        } else {
            std::uint8_t transient_flags = 0;
            std::int32_t current_duration_ticks = 0;
            uintptr_t poison_modifier = 0;
            const bool have_transient_state =
                TryReadWizardActorTransientStatusState(
                    player_state.actor_address,
                    &transient_flags,
                    &current_duration_ticks,
                    &poison_modifier);
            const bool poison_active =
                have_transient_state &&
                (transient_flags &
                 multiplayer::ParticipantTransientStatusFlagPoisoned) != 0 &&
                poison_modifier != 0;
            if (poison_active) {
                auto& memory = ProcessMemory::Instance();
                float current_damage_per_tick = 0.0f;
                if (!memory.TryReadField(
                        poison_modifier,
                        kNativePoisonDamagePerTickOffset,
                        &current_damage_per_tick) ||
                    !std::isfinite(current_damage_per_tick) ||
                    current_damage_per_tick < 0.0f) {
                    current_damage_per_tick = 0.0f;
                }
                const auto corrected_duration =
                    (std::max)(
                        current_duration_ticks,
                        local_player_poison_correction.duration_ticks);
                const auto corrected_damage =
                    (std::max)(
                        current_damage_per_tick,
                        local_player_poison_correction.damage_per_tick);
                applied =
                    memory.TryWriteField(
                        poison_modifier,
                        kNativeModifierDurationTicksOffset,
                        corrected_duration) &&
                    memory.TryWriteField(
                        poison_modifier,
                        kNativePoisonDamagePerTickOffset,
                        corrected_damage);
                if (!applied) {
                    poison_error = "failed to refresh native poison modifier";
                }
            } else {
                applied = InstallReplicatedPoisonModifier(
                    player_state.actor_address,
                    local_player_poison_correction.duration_ticks,
                    &poison_error,
                    local_player_poison_correction.damage_per_tick,
                    0);
            }
        }

        if (applied) {
            Log(
                "Multiplayer owner poison correction applied. duration_ticks=" +
                std::to_string(local_player_poison_correction.duration_ticks) +
                " damage_per_tick=" +
                std::to_string(local_player_poison_correction.damage_per_tick));
        } else {
            Log(
                "Multiplayer owner poison correction failed. duration_ticks=" +
                std::to_string(local_player_poison_correction.duration_ticks) +
                " damage_per_tick=" +
                std::to_string(local_player_poison_correction.damage_per_tick) +
                " error=" + poison_error);
        }
    }

    for (const auto& request : native_poison_behavior_probes) {
        uintptr_t actor_address = 0;
        if (request.target_participant_id == 0) {
            SDModPlayerState player_state;
            if (TryGetPlayerState(&player_state) && player_state.valid) {
                actor_address = player_state.actor_address;
            }
        } else {
            const auto* binding =
                FindParticipantEntity(request.target_participant_id);
            if (binding != nullptr) {
                actor_address = binding->actor_address;
            }
        }

        std::string poison_error;
        const bool applied =
            actor_address != 0 &&
            InstallReplicatedPoisonModifier(
                actor_address,
                request.duration_ticks,
                &poison_error,
                request.damage_per_tick,
                request.source_slot,
                false);
        Log(
            std::string("Native poison behavior probe ") +
            (applied ? "applied" : "failed") +
            ". target_participant_id=" +
            std::to_string(request.target_participant_id) +
            " actor=" + HexString(actor_address) +
            " duration_ticks=" +
            std::to_string(request.duration_ticks) +
            " damage_per_tick=" +
            std::to_string(request.damage_per_tick) +
            " source_slot=" +
            std::to_string(static_cast<int>(request.source_slot)) +
            (poison_error.empty() ? std::string{} : " error=" + poison_error));
    }

    for (const auto& request : native_magic_hit_behavior_probes) {
        std::string probe_error;
        float hp_before = 0.0f;
        float hp_after = 0.0f;
        const bool applied =
            ExecuteNativeMagicHitBehaviorProbe(
                request,
                &hp_before,
                &hp_after,
                &probe_error);
        {
            std::lock_guard<std::mutex> lock(
                g_gameplay_keyboard_injection
                    .pending_gameplay_world_actions_mutex);
            auto& result = g_gameplay_keyboard_injection
                               .native_magic_hit_behavior_probe_result;
            result.request_serial = request.request_serial;
            result.success = applied;
            result.hp_before = hp_before;
            result.hp_after = hp_after;
            result.error = probe_error;
        }
        Log(
            std::string("Native magic-hit behavior probe ") +
            (applied ? "applied" : "failed") +
            ". projectile_damage=" +
            std::to_string(request.projectile_damage) +
            " magic_damage=" + std::to_string(request.magic_damage) +
            " attempts=" + std::to_string(request.attempts) +
            " hp=" + std::to_string(hp_before) + "->" +
            std::to_string(hp_after) +
            (probe_error.empty() ? std::string{} : " error=" + probe_error));
    }

    for (const auto& request : native_staff_effect_probes) {
        std::string probe_error;
        float hp_before = 0.0f;
        float hp_after = 0.0f;
        const bool applied =
            ExecuteNativeStaffEffectProbe(
                request,
                &hp_before,
                &hp_after,
                &probe_error);
        {
            std::lock_guard<std::mutex> lock(
                g_gameplay_keyboard_injection
                    .pending_gameplay_world_actions_mutex);
            auto& result = g_gameplay_keyboard_injection
                               .native_staff_effect_probe_result;
            result.request_serial = request.request_serial;
            result.success = applied;
            result.hp_before = hp_before;
            result.hp_after = hp_after;
            result.error = probe_error;
        }
        Log(
            std::string("Native staff-effect probe ") +
            (applied ? "applied" : "failed") +
            ". source_actor=" + HexString(request.source_actor) +
            " target_actor=" + HexString(request.target_actor) +
            " variant=" + std::to_string(request.variant) +
            " hp=" + std::to_string(hp_before) + "->" +
            std::to_string(hp_after) +
            (probe_error.empty() ? std::string{} : " error=" + probe_error));
    }

    for (const auto bot_id : destroy_requests) {
        DestroyParticipantEntityNow(bot_id);
    }

    if (have_participant_sync_request &&
        std::find(destroy_requests.begin(), destroy_requests.end(), participant_sync_request.bot_id) != destroy_requests.end()) {
        have_participant_sync_request = false;
    }

    if (have_region_switch_request) {
        std::string error_message;
        if (!TryDispatchGameplaySwitchRegionOnGameThread(region_switch_request.region_index, &error_message)) {
            region_switch_request.next_attempt_ms = now_ms + kGameplayRegionSwitchRetryDelayMs;
            g_gameplay_keyboard_injection.gameplay_region_switch_not_before_ms.store(
                region_switch_request.next_attempt_ms,
                std::memory_order_release);
            {
                std::lock_guard<std::mutex> lock(g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
                g_gameplay_keyboard_injection.pending_gameplay_region_switch_requests.push_back(region_switch_request);
            }
            Log(
                "gameplay.switch_region: queued request deferred. region=" +
                std::to_string(region_switch_request.region_index) +
                " retry_in_ms=" + std::to_string(kGameplayRegionSwitchRetryDelayMs) +
                " error=" + error_message);
        }
    }

    if (have_participant_sync_request) {
        if constexpr (kEnableWizardBotHotPathDiagnostics) {
            Log(
                "[bots] pump sync bot_id=" + std::to_string(participant_sync_request.bot_id) +
                " element_id=" + std::to_string(participant_sync_request.character_profile.element_id) +
                " has_transform=" + std::to_string(participant_sync_request.has_transform ? 1 : 0) +
                " x=" + std::to_string(participant_sync_request.x) +
                " y=" + std::to_string(participant_sync_request.y) +
                " heading=" + std::to_string(participant_sync_request.heading));
        }
        std::string error_message;
        if (!ExecuteParticipantEntitySyncNow(participant_sync_request, &error_message)) {
            participant_sync_request.next_attempt_ms = now_ms + kWizardBotSyncRetryDelayMs;
            g_gameplay_keyboard_injection.wizard_bot_sync_not_before_ms.store(
                participant_sync_request.next_attempt_ms,
                std::memory_order_release);
            {
                std::lock_guard<std::mutex> lock(g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
                UpsertPendingParticipantSyncRequest(participant_sync_request);
            }
            Log(
                "[bots] queued sync deferred. bot_id=" + std::to_string(participant_sync_request.bot_id) +
                " element_id=" + std::to_string(participant_sync_request.character_profile.element_id) +
                " has_transform=" + std::to_string(participant_sync_request.has_transform ? 1 : 0) +
                " x=" + std::to_string(participant_sync_request.x) +
                " y=" + std::to_string(participant_sync_request.y) +
                " heading=" + std::to_string(participant_sync_request.heading) +
                " retry_in_ms=" + std::to_string(kWizardBotSyncRetryDelayMs) +
                " error=" + error_message);
        } else {
            g_gameplay_keyboard_injection.wizard_bot_sync_not_before_ms.store(
                now_ms + kWizardBotSyncDispatchSpacingMs,
                std::memory_order_release);
        }
    }

    if (have_reward_request) {
        std::string error_message;
        if (!ExecuteSpawnRewardNow(
                reward_request.kind,
                reward_request.amount,
                reward_request.x,
                reward_request.y,
                &error_message)) {
            Log(
                "spawn_reward: queued request failed. kind=" + reward_request.kind +
                " amount=" + std::to_string(reward_request.amount) +
                " x=" + std::to_string(reward_request.x) +
                " y=" + std::to_string(reward_request.y) +
                " error=" + error_message);
        }
    }

    if (have_replicated_loot_snapshot) {
        ReconcileReplicatedLootSnapshotNow(replicated_loot_snapshot, now_ms);
    }

    for (const auto& request : multiplayer_dampen_effect_requests) {
        std::string dampen_error;
        if (!ExecuteMultiplayerDampenEffectNow(request, &dampen_error)) {
            Log(
                "Multiplayer Dampen behavior request failed. owner_participant_id=" +
                std::to_string(request.owner_participant_id) +
                " cast_sequence=" + std::to_string(request.cast_sequence) +
                " error=" + dampen_error);
        }
    }

    for (const auto& request : client_local_loot_suppression_requests) {
        RemoveUnboundClientLootActors(request.reason.c_str());
    }

    multiplayer::ReconcileLocalLevelUpOfferPresentation(now_ms);
    RebuildNavGridSnapshotIfRequested_GameplayThread();
}
