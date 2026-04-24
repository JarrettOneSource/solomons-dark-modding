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

    if (!g_allow_gameplay_action_pump_in_gameplay && gameplay_active) {
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

    PendingRewardSpawnRequest reward_request;
    bool have_reward_request = false;
    PendingEnemySpawnRequest enemy_request;
    bool have_enemy_request = false;
    PendingParticipantEntitySyncRequest participant_sync_request;
    bool have_participant_sync_request = false;
    PendingGameplayRegionSwitchRequest region_switch_request;
    bool have_region_switch_request = false;
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
        if (!g_gameplay_keyboard_injection.pending_enemy_spawn_requests.empty()) {
            enemy_request = g_gameplay_keyboard_injection.pending_enemy_spawn_requests.front();
            g_gameplay_keyboard_injection.pending_enemy_spawn_requests.pop_front();
            have_enemy_request = true;
        }
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
        Log(
            "[bots] pump sync bot_id=" + std::to_string(participant_sync_request.bot_id) +
            " element_id=" + std::to_string(participant_sync_request.character_profile.element_id) +
            " has_transform=" + std::to_string(participant_sync_request.has_transform ? 1 : 0) +
            " x=" + std::to_string(participant_sync_request.x) +
            " y=" + std::to_string(participant_sync_request.y) +
            " heading=" + std::to_string(participant_sync_request.heading));
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

    if (have_enemy_request) {
        std::string error_message;
        if (!ExecuteSpawnEnemyNow(enemy_request.type_id, enemy_request.x, enemy_request.y, nullptr, &error_message)) {
            Log(
                "spawn_enemy: queued request failed. type_id=" + std::to_string(enemy_request.type_id) +
                " x=" + std::to_string(enemy_request.x) +
                " y=" + std::to_string(enemy_request.y) +
                " error=" + error_message);
        }
    }

    RebuildNavGridSnapshotIfRequested_GameplayThread();
}
