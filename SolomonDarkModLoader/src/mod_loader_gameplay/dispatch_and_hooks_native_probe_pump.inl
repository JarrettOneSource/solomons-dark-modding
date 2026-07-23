void ExecuteQueuedNativeDiagnosticProbes(
    const std::vector<PendingNativeMagicHitBehaviorProbe>&
        native_magic_hit_behavior_probes,
    const std::vector<PendingNativeEnemyDeathProbe>& native_enemy_death_probes,
    const std::vector<PendingNativeExperienceGainProbe>&
        native_experience_gain_probes,
    const std::vector<PendingNativeStaffEffectProbe>& native_staff_effect_probes) {
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
            " target_participant_id=" +
            std::to_string(request.target_participant_id) +
            " hp=" + std::to_string(hp_before) + "->" +
            std::to_string(hp_after) +
            (probe_error.empty() ? std::string{} : " error=" + probe_error));
    }

    for (const auto& request : native_enemy_death_probes) {
        std::uint32_t exception_code = 0;
        bool config_restored = false;
        std::string probe_error;
        const bool success = ExecuteNativeEnemyDeathProbe(
            request,
            &exception_code,
            &config_restored,
            &probe_error);
        {
            std::lock_guard<std::mutex> lock(
                g_gameplay_keyboard_injection
                    .pending_gameplay_world_actions_mutex);
            auto& result = g_gameplay_keyboard_injection
                               .native_enemy_death_probe_result;
            result.request_serial = request.request_serial;
            result.success = success;
            result.exception_code = exception_code;
            result.config_restored = config_restored;
            result.error = probe_error;
        }
        Log(
            std::string("Native enemy-death probe ") +
            (success ? "applied" : "failed") +
            ". actor=" + HexString(request.actor_address) +
            " config=" + HexString(request.expected_config_address) +
            " restored=" + std::to_string(config_restored ? 1 : 0) +
            " seh=" + HexString(static_cast<uintptr_t>(exception_code)) +
            (probe_error.empty() ? std::string{} : " error=" + probe_error));
    }

    for (const auto& request : native_experience_gain_probes) {
        float xp_before = 0.0f;
        float xp_after = 0.0f;
        std::uint32_t exception_code = 0;
        std::string probe_error;
        const bool success = ExecuteNativeExperienceGainProbe(
            request,
            &xp_before,
            &xp_after,
            &exception_code,
            &probe_error);
        {
            std::lock_guard<std::mutex> lock(
                g_gameplay_keyboard_injection
                    .pending_gameplay_world_actions_mutex);
            auto& result = g_gameplay_keyboard_injection
                               .native_experience_gain_probe_result;
            result.request_serial = request.request_serial;
            result.success = success;
            result.xp_before = xp_before;
            result.xp_after = xp_after;
            result.exception_code = exception_code;
            result.error = probe_error;
        }
        Log(
            std::string("Native XP gain probe ") +
            (success ? "applied" : "failed") +
            ". amount=" + std::to_string(request.amount) +
            " native_scaling=" +
            std::to_string(request.apply_native_scaling ? 1 : 0) +
            " xp=" + std::to_string(xp_before) + "->" +
            std::to_string(xp_after) +
            " seh=" + HexString(static_cast<uintptr_t>(exception_code)) +
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
}
