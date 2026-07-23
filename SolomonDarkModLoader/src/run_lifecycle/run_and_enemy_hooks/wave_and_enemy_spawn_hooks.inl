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

    const auto config_address = static_cast<uintptr_t>(
        static_cast<std::uint32_t>(enemy_config));
    LuaEnemySpawnFilterContext original_filter_context;
    bool restore_filter_context = false;
    if (HasLuaEnemySpawnFilterHandlers() &&
        !multiplayer::IsLocalTransportClient() &&
        !g_manual_run_enemy_spawner_tick_active) {
        LuaEnemySpawnFilterContext filtered_context;
        if (!TryCaptureLuaEnemySpawnFilterContext(
                reinterpret_cast<uintptr_t>(self),
                config_address,
                &filtered_context)) {
            LogLuaEnemySpawnFilterHookFailure(
                &g_lua_enemy_spawn_filter_capture_log_count,
                "enemy.spawning skipped because the stock config could not "
                "be captured. config=" + HexString(config_address));
        } else {
            original_filter_context = filtered_context;
            if (!ApplyLuaEnemySpawnFilters(&filtered_context)) {
                return CanceledEnemySpawnResult();
            }
            if (LuaEnemySpawnFilterContextChanged(
                    original_filter_context,
                    filtered_context)) {
                const auto write_result = WriteLuaEnemySpawnFilterConfig(
                    original_filter_context,
                    filtered_context);
                restore_filter_context =
                    write_result == LuaEnemySpawnConfigWriteResult::Applied;
                if (write_result != LuaEnemySpawnConfigWriteResult::Applied) {
                    LogLuaEnemySpawnFilterHookFailure(
                        &g_lua_enemy_spawn_filter_write_log_count,
                        "enemy.spawning rewrite failed. config=" +
                            HexString(config_address) + " restored=" +
                            (write_result ==
                                     LuaEnemySpawnConfigWriteResult::RestoredAfterFailure
                                 ? "1"
                                 : "0"));
                    if (write_result ==
                        LuaEnemySpawnConfigWriteResult::RestoreFailed) {
                        return CanceledEnemySpawnResult();
                    }
                }
            }
        }
    }

    auto* enemy = original(
        self,
        unused_edx,
        param_2,
        enemy_config,
        param_4,
        param_5,
        param_6,
        param_7);
    if (restore_filter_context &&
        !RestoreLuaEnemySpawnFilterConfig(original_filter_context)) {
        LogLuaEnemySpawnFilterHookFailure(
            &g_lua_enemy_spawn_filter_write_log_count,
            "enemy.spawning stock config restore failed after construction. "
            "config=" + HexString(config_address));
    }
    if (enemy == nullptr || !IsCombatArenaActiveForEnemyTracking()) {
        return enemy;
    }

    const auto enemy_address = reinterpret_cast<uintptr_t>(enemy);
    const auto spawn_serial = RememberEnemySpawnSerial(enemy_address);
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
    std::uint32_t actor_object_type = 0;
    const bool have_actor_object_type =
        TryReadActorObjectTypeForRunLifecycle(enemy_address, &actor_object_type);
    const bool arena_combat_actor_type =
        have_actor_object_type &&
        IsArenaCombatActorType(actor_object_type);
    if (arena_combat_actor_type) {
        RememberArenaEnemyWaveSpawner(g_current_wave_spawner_tick_address);
        if (g_current_wave_number > 0) {
            ObserveAuthorityWaveEnemySpawn(
                enemy_address,
                enemy_type,
                g_current_wave_number);
        }
    }
    Log(
        "enemy.spawned hook invoked. enemy=" + HexString(enemy_address) +
        " spawn_serial=" + std::to_string(spawn_serial) +
        " enemy_type=" + std::to_string(enemy_type) +
        " actor_object_type=" + std::to_string(actor_object_type) +
        " pos=(" + std::to_string(x) + "," + std::to_string(y) + ")" +
        " run_active=" + std::to_string(IsRunActive() ? 1 : 0) +
        " wave_start_tracking=" +
        std::to_string(g_state.wave_start_enemy_tracking.load(std::memory_order_acquire) ? 1 : 0));

    if (g_manual_run_enemy_spawner_tick_active && !arena_combat_actor_type) {
        Log(
            "manual run enemy spawn: ignored non-arena stock spawn during controlled exact spawn. actor=" +
            HexString(enemy_address) +
            " spawn_serial=" + std::to_string(spawn_serial) +
            " enemy_type=" + std::to_string(enemy_type) +
            " actor_object_type=" + std::to_string(actor_object_type));
    } else if (g_manual_run_enemy_spawner_tick_active) {
        ManualRunEnemySpawnRequest request;
        bool complete_manual_request = false;
        {
            std::lock_guard<std::mutex> lock(g_manual_run_enemy_spawn_mutex);
            if (g_have_active_manual_run_enemy_spawn) {
                request = g_active_manual_run_enemy_spawn;
                g_have_active_manual_run_enemy_spawn = false;
                g_active_manual_run_enemy_spawn = ManualRunEnemySpawnRequest{};
                if (request.freeze_on_spawn) {
                    g_frozen_manual_run_enemies[enemy_address] = FrozenManualRunEnemy{request.x, request.y};
                }
                complete_manual_request = true;
            }
        }

        if (complete_manual_request) {
            auto& memory = ProcessMemory::Instance();
            const float native_x = x;
            const float native_y = y;
            const bool wrote_x = memory.TryWriteField(enemy_address, kActorPositionXOffset, request.x);
            const bool wrote_y = memory.TryWriteField(enemy_address, kActorPositionYOffset, request.y);
            float final_x = x;
            float final_y = y;
            (void)memory.TryReadField(enemy_address, kActorPositionXOffset, &final_x);
            (void)memory.TryReadField(enemy_address, kActorPositionYOffset, &final_y);
            std::string rebind_error_message;
            const bool rebind_ok = RebindSceneActorCell(enemy_address, &rebind_error_message);

            SDModManualRunEnemySpawnResult result;
            result.valid = true;
            const bool exact_native_type =
                have_actor_object_type &&
                actor_object_type == static_cast<std::uint32_t>(request.type_id);
            result.ok = wrote_x && wrote_y && rebind_ok && exact_native_type;
            result.request_id = request.request_id;
            result.type_id = enemy_type >= 0 ? enemy_type : request.type_id;
            result.actor_address = enemy_address;
            result.requested_x = request.x;
            result.requested_y = request.y;
            result.x = final_x;
            result.y = final_y;
            result.wrote_x = wrote_x && std::fabs(final_x - request.x) <= 0.01f;
            result.wrote_y = wrote_y && std::fabs(final_y - request.y) <= 0.01f;
            result.rebind_ok = rebind_ok;
            result.completed_tick_ms = static_cast<std::uint64_t>(GetTickCount64());
            if (!wrote_x || !wrote_y) {
                result.error_message = "exact stock enemy was created but position write failed.";
            } else if (!rebind_ok) {
                result.error_message =
                    "exact stock enemy was relocated but cell rebind failed: " +
                    rebind_error_message;
            } else if (!exact_native_type) {
                result.error_message =
                    "actual native type did not match authority.";
            }
            x = final_x;
            y = final_y;

            {
                std::lock_guard<std::mutex> lock(g_manual_run_enemy_spawn_mutex);
                g_last_manual_run_enemy_spawn_result = result;
            }

            Log(
                "manual run enemy spawn: completed through exact stock path. request_id=" +
                std::to_string(result.request_id) +
                " requested_type_id=" + std::to_string(request.type_id) +
                " actual_type_id=" + std::to_string(result.type_id) +
                " actor=" + HexString(enemy_address) +
                " spawn_serial=" + std::to_string(spawn_serial) +
                " native_pos=(" + std::to_string(native_x) + "," + std::to_string(native_y) + ")" +
                " final_pos=(" + std::to_string(final_x) + "," + std::to_string(final_y) + ")" +
                " wrote_x=" + std::to_string(result.wrote_x ? 1 : 0) +
                " wrote_y=" + std::to_string(result.wrote_y ? 1 : 0) +
                " rebind_ok=" + std::to_string(result.rebind_ok ? 1 : 0) +
                (rebind_error_message.empty()
                    ? std::string()
                    : " rebind_error=\"" + rebind_error_message + "\""));
        } else {
            Log(
                "manual run enemy spawn: extra native spawn observed during controlled exact spawn. actor=" +
                HexString(enemy_address) +
                " spawn_serial=" + std::to_string(spawn_serial) +
                " enemy_type=" + std::to_string(enemy_type));
        }
    }

    DispatchLuaEnemySpawned(enemy_type, x, y);
    return enemy;
}
