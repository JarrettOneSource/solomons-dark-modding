bool UpdateWizardBotPathMotion(ParticipantEntityBinding* binding, std::uint64_t now_ms, std::string* error_message) {
    if (binding == nullptr) {
        return false;
    }

    if (binding->controller_state != multiplayer::BotControllerState::Moving || !binding->has_target) {
        StopBotPathMotion(binding, false);
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
            StopBotPathMotion(binding, false);
            (void)multiplayer::StopBot(binding->bot_id);
            return false;
        }
    }

    if (!binding->path_active || binding->path_waypoints.empty()) {
        binding->movement_active = false;
        binding->last_movement_displacement = 0.0f;
        binding->direction_x = 0.0f;
        binding->direction_y = 0.0f;
        if (now_ms - binding->last_path_debug_log_ms >= 1000) {
            binding->last_path_debug_log_ms = now_ms;
            Log(
                "[bots] path inactive. bot_id=" + std::to_string(binding->bot_id) +
                " revision=" + std::to_string(binding->movement_intent_revision) +
                " path_active=" + std::to_string(binding->path_active ? 1 : 0) +
                " waypoint_count=" + std::to_string(binding->path_waypoints.size()));
        }
        return true;
    }

    auto& memory = ProcessMemory::Instance();
    const auto actor_x = memory.ReadFieldOr<float>(binding->actor_address, kActorPositionXOffset, 0.0f);
    const auto actor_y = memory.ReadFieldOr<float>(binding->actor_address, kActorPositionYOffset, 0.0f);
    const auto target_delta_x = binding->target_x - actor_x;
    const auto target_delta_y = binding->target_y - actor_y;
    const auto target_distance =
        std::sqrt(target_delta_x * target_delta_x + target_delta_y * target_delta_y);
    if (target_distance <= kWizardBotPathFinalArrivalThreshold) {
        StopBotPathMotion(binding, false);
        (void)multiplayer::StopBot(binding->bot_id);
        return true;
    }

    while (binding->path_waypoint_index < binding->path_waypoints.size()) {
        const auto& waypoint = binding->path_waypoints[binding->path_waypoint_index];
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
    }

    if (binding->path_waypoint_index >= binding->path_waypoints.size()) {
        const bool arrived_at_target = target_distance <= kWizardBotPathFinalArrivalThreshold;
        StopBotPathMotion(binding, false);
        if (!arrived_at_target) {
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
            return true;
        }

        (void)multiplayer::StopBot(binding->bot_id);
        if (now_ms - binding->last_path_debug_log_ms >= 1000) {
            binding->last_path_debug_log_ms = now_ms;
            Log(
                "[bots] path complete. bot_id=" + std::to_string(binding->bot_id) +
                " revision=" + std::to_string(binding->movement_intent_revision) +
                " actor=(" + std::to_string(actor_x) + ", " + std::to_string(actor_y) + ")" +
                " destination=(" + std::to_string(binding->target_x) + ", " + std::to_string(binding->target_y) + ")");
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
    return true;
}
