bool TryTeleportStuckWizardBot(
    ParticipantEntityBinding* binding,
    std::uint64_t now_ms,
    float actor_x,
    float actor_y,
    float target_distance) {
    if (binding == nullptr ||
        !multiplayer::IsLuaModSimulationAuthority() ||
        binding->controller_kind !=
            multiplayer::ParticipantControllerKind::LuaBrain) {
        return false;
    }

    const auto same_target = IsBotStuckTargetContinuous(
        binding->stuck_progress,
        binding->target_x,
        binding->target_y);
    if (!same_target) {
        binding->stuck_waypoint_anchor_valid = true;
        binding->stuck_waypoint_anchor_x = actor_x;
        binding->stuck_waypoint_anchor_y = actor_y;
        binding->stuck_waypoint_progress_pending = false;
    }
    const auto waypoint_progress =
        binding->stuck_waypoint_progress_pending;
    binding->stuck_waypoint_progress_pending = false;
    if (!ObserveBotStuckProgress(
            &binding->stuck_progress,
            now_ms,
            binding->target_x,
            binding->target_y,
            target_distance,
            waypoint_progress)) {
        return false;
    }

    const auto window_started_ms =
        binding->stuck_progress.samples.empty()
            ? now_ms
            : binding->stuck_progress.samples.front().observed_ms;
    float landing_x = 0.0f;
    float landing_y = 0.0f;
    std::string placement_error;
    if (!ResolveNativeBotSpawnPlacement(
            binding->bot_id,
            binding->scene_intent.kind,
            "stuck_teleport",
            binding->target_x,
            binding->target_y,
            &landing_x,
            &landing_y,
            &placement_error)) {
        ResetBotStuckProgress(&binding->stuck_progress);
        binding->stuck_waypoint_anchor_valid = false;
        Log(
            "[bots] stuck teleport skipped. bot_id=" +
            std::to_string(binding->bot_id) +
            " target=(" + std::to_string(binding->target_x) +
            ", " + std::to_string(binding->target_y) + ")" +
            " error=" + placement_error);
        return false;
    }

    DWORD rebind_exception_code = 0;
    if (!TeleportPlayerFamilyActorAndRebind(
            binding->actor_address,
            landing_x,
            landing_y,
            &rebind_exception_code)) {
        ResetBotStuckProgress(&binding->stuck_progress);
        binding->stuck_waypoint_anchor_valid = false;
        Log(
            "[bots] stuck teleport failed. bot_id=" +
            std::to_string(binding->bot_id) +
            " target=(" + std::to_string(binding->target_x) +
            ", " + std::to_string(binding->target_y) + ")" +
            " landing=(" + std::to_string(landing_x) +
            ", " + std::to_string(landing_y) + ")" +
            " exception=" + HexString(rebind_exception_code));
        return false;
    }

    const auto requested_target_x = binding->target_x;
    const auto requested_target_y = binding->target_y;
    const auto landing_delta_x = landing_x - requested_target_x;
    const auto landing_delta_y = landing_y - requested_target_y;
    const auto landing_search_distance = std::sqrt(
        landing_delta_x * landing_delta_x +
        landing_delta_y * landing_delta_y);
    StopBotPathMotion(binding, false);
    StopWizardBotActorMotion(binding->actor_address);
    (void)multiplayer::StopBot(binding->bot_id);
    binding->controller_state =
        multiplayer::BotControllerState::Idle;
    binding->has_target = false;
    binding->distance_to_target = 0.0f;
    RecordBotStuckTeleport(
        &binding->stuck_progress,
        now_ms);
    binding->stuck_waypoint_anchor_valid = false;
    binding->stuck_waypoint_progress_pending = false;
    PublishParticipantGameplaySnapshot(*binding);
    Log(
        "[bots] stuck teleport. bot_id=" +
        std::to_string(binding->bot_id) +
        " actor=" + HexString(binding->actor_address) +
        " origin=(" + std::to_string(actor_x) +
        ", " + std::to_string(actor_y) + ")" +
        " target=(" + std::to_string(requested_target_x) +
        ", " + std::to_string(requested_target_y) + ")" +
        " landing=(" + std::to_string(landing_x) +
        ", " + std::to_string(landing_y) + ")" +
        " window_ms=" +
        std::to_string(now_ms - window_started_ms) +
        " search_distance=" +
        std::to_string(landing_search_distance));
    return true;
}

bool UpdateWizardBotPathMotion(ParticipantEntityBinding* binding, std::uint64_t now_ms, std::string* error_message) {
    if (binding == nullptr) {
        return false;
    }

    if (binding->controller_state != multiplayer::BotControllerState::Moving || !binding->has_target) {
        StopBotPathMotion(binding, false);
        ResetBotStuckProgress(&binding->stuck_progress);
        binding->stuck_waypoint_anchor_valid = false;
        binding->stuck_waypoint_progress_pending = false;
        return true;
    }

    float actor_x = 0.0f;
    float actor_y = 0.0f;
    if (!TryReadFiniteFloatField(binding->actor_address, kActorPositionXOffset, &actor_x) ||
        !TryReadFiniteFloatField(binding->actor_address, kActorPositionYOffset, &actor_y)) {
        StopBotPathMotion(binding, false);
        if (error_message != nullptr) {
            *error_message = "Bot actor position is unreadable during path motion.";
        }
        return false;
    }
    const auto target_delta_x = binding->target_x - actor_x;
    const auto target_delta_y = binding->target_y - actor_y;
    const auto target_distance =
        std::sqrt(target_delta_x * target_delta_x + target_delta_y * target_delta_y);
    if (target_distance <= kWizardBotPathFinalArrivalThreshold) {
        StopBotPathMotion(binding, false);
        (void)multiplayer::StopBot(binding->bot_id);
        ResetBotStuckProgress(&binding->stuck_progress);
        binding->stuck_waypoint_anchor_valid = false;
        binding->stuck_waypoint_progress_pending = false;
        return true;
    }
    if (TryTeleportStuckWizardBot(
            binding,
            now_ms,
            actor_x,
            actor_y,
            target_distance)) {
        return true;
    }

    const auto revision_changed = binding->active_path_revision != binding->movement_intent_revision;
    if (binding->path_failed && !revision_changed && now_ms < binding->next_path_retry_not_before_ms) {
        binding->movement_active = false;
        binding->last_movement_displacement = 0.0f;
        binding->direction_x = 0.0f;
        binding->direction_y = 0.0f;
        return true;
    }

    const auto rebuild_due =
        revision_changed ||
        (!binding->path_failed && (!binding->path_active || binding->path_waypoints.empty())) ||
        (binding->path_failed && now_ms >= binding->next_path_retry_not_before_ms);
    if (rebuild_due) {
        if (!TryBuildBotPath(binding, now_ms, error_message)) {
            binding->path_failed = true;
            binding->path_active = false;
            binding->active_path_revision = binding->movement_intent_revision;
            binding->next_path_retry_not_before_ms = now_ms + kWizardBotPathRetryDelayMs;
            binding->movement_active = false;
            binding->last_movement_displacement = 0.0f;
            binding->direction_x = 0.0f;
            binding->direction_y = 0.0f;
            binding->path_waypoints.clear();
            binding->path_waypoint_index = 0;
            return false;
        }
    }

    if (!binding->path_active || binding->path_waypoints.empty()) {
        binding->movement_active = false;
        binding->last_movement_displacement = 0.0f;
        binding->direction_x = 0.0f;
        binding->direction_y = 0.0f;
        if constexpr (kEnableWizardBotHotPathDiagnostics) {
            if (now_ms - binding->last_path_debug_log_ms >= 1000) {
                binding->last_path_debug_log_ms = now_ms;
                Log(
                    "[bots] path inactive. bot_id=" + std::to_string(binding->bot_id) +
                    " revision=" + std::to_string(binding->movement_intent_revision) +
                    " path_active=" + std::to_string(binding->path_active ? 1 : 0) +
                    " waypoint_count=" + std::to_string(binding->path_waypoints.size()));
            }
        }
        return true;
    }

    float actor_radius = 0.0f;
    (void)TryReadFiniteFloatField(binding->actor_address, kActorCollisionRadiusOffset, &actor_radius);
    const auto target_blocked_by_participant =
        actor_radius > 0.0f &&
        IsGameplayPathBlockedByWizardParticipant(
            binding,
            binding->target_x,
            binding->target_y,
            actor_radius,
            nullptr);

    while (binding->path_waypoint_index < binding->path_waypoints.size()) {
        const auto& waypoint = binding->path_waypoints[binding->path_waypoint_index];
        if (actor_radius > 0.0f &&
            IsGameplayPathBlockedByWizardParticipant(binding, waypoint.x, waypoint.y, actor_radius, nullptr)) {
            StopBotPathMotion(binding, false);
            return true;
        }
        const auto delta_x = waypoint.x - actor_x;
        const auto delta_y = waypoint.y - actor_y;
        const auto distance = std::sqrt(delta_x * delta_x + delta_y * delta_y);
        const auto final_waypoint =
            binding->path_waypoint_index + 1 >= binding->path_waypoints.size();
        const auto arrival_threshold =
            final_waypoint ? kWizardBotPathFinalArrivalThreshold : kWizardBotPathWaypointArrivalThreshold;
        if (distance > arrival_threshold) {
            break;
        }
        ++binding->path_waypoint_index;
        if (!final_waypoint &&
            binding->stuck_waypoint_anchor_valid) {
            const auto anchor_delta_x =
                actor_x - binding->stuck_waypoint_anchor_x;
            const auto anchor_delta_y =
                actor_y - binding->stuck_waypoint_anchor_y;
            if (anchor_delta_x * anchor_delta_x +
                    anchor_delta_y * anchor_delta_y >=
                kBotStuckMeaningfulDistanceProgress *
                    kBotStuckMeaningfulDistanceProgress) {
                binding->stuck_waypoint_progress_pending = true;
                binding->stuck_waypoint_anchor_x = actor_x;
                binding->stuck_waypoint_anchor_y = actor_y;
            }
        }
    }

    if (binding->path_waypoint_index >= binding->path_waypoints.size()) {
        const bool arrived_at_target =
            target_distance <= kWizardBotPathFinalArrivalThreshold ||
            target_blocked_by_participant;
        StopBotPathMotion(binding, false);
        if (!arrived_at_target) {
            DiscardBotStuckWaypointProgress(
                &binding->stuck_progress);
            binding->stuck_waypoint_anchor_valid = true;
            binding->stuck_waypoint_anchor_x = actor_x;
            binding->stuck_waypoint_anchor_y = actor_y;
            binding->stuck_waypoint_progress_pending = false;
            if constexpr (kEnableWizardBotHotPathDiagnostics) {
                if (now_ms - binding->last_path_debug_log_ms >= 1000) {
                    binding->last_path_debug_log_ms = now_ms;
                    Log(
                        "[bots] path segment exhausted. bot_id=" + std::to_string(binding->bot_id) +
                        " revision=" + std::to_string(binding->movement_intent_revision) +
                        " actor=(" + std::to_string(actor_x) + ", " + std::to_string(actor_y) + ")" +
                        " destination=(" + std::to_string(binding->target_x) + ", " + std::to_string(binding->target_y) + ")" +
                        " remaining_distance=" + std::to_string(target_distance) +
                        " action=rebuild");
                }
            }
            return true;
        }

        (void)multiplayer::StopBot(binding->bot_id);
        ResetBotStuckProgress(&binding->stuck_progress);
        binding->stuck_waypoint_anchor_valid = false;
        binding->stuck_waypoint_progress_pending = false;
        if constexpr (kEnableWizardBotHotPathDiagnostics) {
            if (now_ms - binding->last_path_debug_log_ms >= 1000) {
                binding->last_path_debug_log_ms = now_ms;
                Log(
                    "[bots] path complete. bot_id=" + std::to_string(binding->bot_id) +
                    " revision=" + std::to_string(binding->movement_intent_revision) +
                    " actor=(" + std::to_string(actor_x) + ", " + std::to_string(actor_y) + ")" +
                    " destination=(" + std::to_string(binding->target_x) + ", " + std::to_string(binding->target_y) + ")");
            }
        }
        return true;
    }

    const auto& waypoint = binding->path_waypoints[binding->path_waypoint_index];
    const auto delta_x = waypoint.x - actor_x;
    const auto delta_y = waypoint.y - actor_y;
    const auto distance = std::sqrt(delta_x * delta_x + delta_y * delta_y);
    if (distance <= 0.0001f) {
        binding->movement_active = false;
        binding->last_movement_displacement = 0.0f;
        binding->direction_x = 0.0f;
        binding->direction_y = 0.0f;
        return true;
    }

    binding->movement_active = true;
    binding->direction_x = delta_x / distance;
    binding->direction_y = delta_y / distance;
    binding->desired_heading_valid = true;
    binding->desired_heading = NormalizeGameplayHeadingDegrees(
        static_cast<float>(std::atan2(binding->direction_y, binding->direction_x) * (180.0 / 3.14159265358979323846) + 90.0));
    binding->current_waypoint_x = waypoint.x;
    binding->current_waypoint_y = waypoint.y;
    if constexpr (kEnableWizardBotHotPathDiagnostics) {
        if (now_ms - binding->last_path_debug_log_ms >= 1000) {
            binding->last_path_debug_log_ms = now_ms;
            Log(
                "[bots] path follow tick. bot_id=" + std::to_string(binding->bot_id) +
                " revision=" + std::to_string(binding->movement_intent_revision) +
                " actor=(" + std::to_string(actor_x) + ", " + std::to_string(actor_y) + ")" +
                " waypoint_index=" + std::to_string(binding->path_waypoint_index) +
                "/" + std::to_string(binding->path_waypoints.size()) +
                " waypoint=(" + std::to_string(binding->current_waypoint_x) + ", " + std::to_string(binding->current_waypoint_y) + ")" +
                " dir=(" + std::to_string(binding->direction_x) + ", " + std::to_string(binding->direction_y) + ")" +
                " distance=" + std::to_string(distance));
        }
    }
    return true;
}
