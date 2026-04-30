bool MoveBotTo(const BotMoveToRequest& request) {
    std::scoped_lock lock(g_bot_runtime_mutex);
    if (!g_bot_runtime_initialized || !IsValidMoveRequest(request)) {
        return false;
    }

    const RuntimeState runtime = SnapshotRuntimeState();
    const auto* participant = FindBot(runtime, request.bot_id);
    if (participant == nullptr) {
        return false;
    }
    if (IsParticipantRuntimeDead(*participant)) {
        ClearDeadBotControlsLocked(*participant);
        return false;
    }

    const auto* previous_intent = FindPendingMovementIntent(request.bot_id);
    const bool have_transform = participant->runtime.transform_valid;
    const float current_x = participant->runtime.position_x;
    const float current_y = participant->runtime.position_y;
    const float current_heading =
        have_transform ? participant->runtime.heading
                       : (previous_intent != nullptr && previous_intent->desired_heading_valid
                              ? previous_intent->desired_heading
                              : 0.0f);
    SchedulePendingMovementIntentLocked(
        request.bot_id,
        BotControllerState::Moving,
        true,
        request.target_x,
        request.target_y,
        previous_intent != nullptr && previous_intent->desired_heading_valid,
        previous_intent != nullptr ? previous_intent->desired_heading : 0.0f);
    if (auto* current_intent = FindPendingMovementIntent(request.bot_id); current_intent != nullptr) {
        DeriveControllerMotionFromTransform(current_intent, have_transform, current_x, current_y, current_heading);
    }
    return true;
}

bool StopBot(std::uint64_t bot_id) {
    std::scoped_lock lock(g_bot_runtime_mutex);
    if (!g_bot_runtime_initialized || bot_id == 0) {
        return false;
    }

    const RuntimeState runtime = SnapshotRuntimeState();
    const auto* participant = FindBot(runtime, bot_id);
    if (participant == nullptr) {
        return false;
    }
    if (IsParticipantRuntimeDead(*participant)) {
        ClearDeadBotControlsLocked(*participant);
        return true;
    }

    const auto* previous_intent = FindPendingMovementIntent(bot_id);
    const auto desired_heading_valid = previous_intent != nullptr && previous_intent->desired_heading_valid;
    const auto desired_heading = previous_intent != nullptr ? previous_intent->desired_heading : 0.0f;
    SchedulePendingMovementIntentLocked(
        bot_id,
        BotControllerState::Idle,
        false,
        0.0f,
        0.0f,
        desired_heading_valid,
        desired_heading);
    if (previous_intent == nullptr || previous_intent->state != BotControllerState::Idle || previous_intent->has_target) {
        Log("[bots] queued stop id=" + std::to_string(bot_id) + " state=idle");
    }

    return true;
}

bool FaceBot(std::uint64_t bot_id, float heading) {
    std::scoped_lock lock(g_bot_runtime_mutex);
    if (!g_bot_runtime_initialized || bot_id == 0 || !std::isfinite(heading)) {
        return false;
    }
    heading = NormalizeHeadingDegrees(heading);

    const RuntimeState runtime = SnapshotRuntimeState();
    const auto* participant = FindBot(runtime, bot_id);
    if (participant == nullptr) {
        return false;
    }
    if (IsParticipantRuntimeDead(*participant)) {
        ClearDeadBotControlsLocked(*participant);
        return false;
    }

    const auto* previous_intent = FindPendingMovementIntent(bot_id);
    const bool preserve_active_intent =
        previous_intent != nullptr &&
        (previous_intent->state == BotControllerState::Moving ||
         previous_intent->state == BotControllerState::Attacking ||
         previous_intent->has_target);
    const bool changed =
        previous_intent == nullptr ||
        !previous_intent->face_heading_valid ||
        std::fabs(previous_intent->face_heading - heading) > 0.01f;

    if (!preserve_active_intent) {
        SchedulePendingMovementIntentLocked(
            bot_id,
            BotControllerState::Idle,
            false,
            0.0f,
            0.0f,
            true,
            heading);
    }
    SetPendingFaceHeadingLocked(bot_id, true, heading, 0);
    SetPendingFaceTargetLocked(bot_id, 0);
    if (changed) {
        Log(
            "[bots] queued face id=" + std::to_string(bot_id) +
            " heading=" + std::to_string(heading));
    }

    return true;
}

bool FaceBotTarget(std::uint64_t bot_id, uintptr_t target_actor_address, bool fallback_heading_valid, float fallback_heading) {
    std::scoped_lock lock(g_bot_runtime_mutex);
    if (!g_bot_runtime_initialized || bot_id == 0) {
        return false;
    }
    if (fallback_heading_valid && !std::isfinite(fallback_heading)) {
        return false;
    }
    if (fallback_heading_valid) {
        fallback_heading = NormalizeHeadingDegrees(fallback_heading);
    }

    const RuntimeState runtime = SnapshotRuntimeState();
    const auto* participant = FindBot(runtime, bot_id);
    if (participant == nullptr) {
        return false;
    }
    if (IsParticipantRuntimeDead(*participant)) {
        ClearDeadBotControlsLocked(*participant);
        return false;
    }

    const auto* previous_intent = FindPendingMovementIntent(bot_id);
    const bool changed =
        previous_intent == nullptr ||
        previous_intent->face_target_actor_address != target_actor_address ||
        previous_intent->face_heading_valid != fallback_heading_valid ||
        (fallback_heading_valid &&
         (!previous_intent->face_heading_valid ||
          std::fabs(previous_intent->face_heading - fallback_heading) > 0.01f));

    if (fallback_heading_valid) {
        SetPendingFaceHeadingLocked(bot_id, true, fallback_heading, 0);
    } else if (target_actor_address == 0) {
        SetPendingFaceHeadingLocked(bot_id, false, 0.0f, 0);
    }
    SetPendingFaceTargetLocked(bot_id, target_actor_address);

    if (changed) {
        Log(
            "[bots] queued face_target id=" + std::to_string(bot_id) +
            " target=" + std::to_string(static_cast<std::uintptr_t>(target_actor_address)) +
            " fallback_valid=" + std::to_string(fallback_heading_valid ? 1 : 0));
    }

    return true;
}

bool ReadBotMovementIntent(std::uint64_t bot_id, BotMovementIntentSnapshot* snapshot) {
    if (snapshot == nullptr) {
        return false;
    }

    *snapshot = BotMovementIntentSnapshot{};

    std::scoped_lock lock(g_bot_runtime_mutex);
    if (!g_bot_runtime_initialized || bot_id == 0) {
        return false;
    }

    RuntimeState runtime = SnapshotRuntimeState();
    const auto* participant = FindBot(runtime, bot_id);
    if (participant == nullptr) {
        return false;
    }
    if (IsParticipantRuntimeDead(*participant)) {
        snapshot->available = true;
        return true;
    }

    snapshot->available = true;
    if (auto* pending_intent = FindPendingMovementIntent(bot_id); pending_intent != nullptr) {
        if (pending_intent->face_heading_valid &&
            pending_intent->face_heading_expires_ms != 0 &&
            GetTickCount64() > pending_intent->face_heading_expires_ms) {
            pending_intent->face_heading_valid = false;
            pending_intent->face_heading_expires_ms = 0;
        }
        snapshot->revision = pending_intent->revision;
        snapshot->state = pending_intent->state;
        snapshot->moving = pending_intent->state == BotControllerState::Moving;
        snapshot->has_target = pending_intent->has_target;
        snapshot->direction_x = pending_intent->direction_x;
        snapshot->direction_y = pending_intent->direction_y;
        snapshot->desired_heading_valid = pending_intent->desired_heading_valid;
        snapshot->desired_heading = pending_intent->desired_heading;
        snapshot->face_heading_valid = pending_intent->face_heading_valid;
        snapshot->face_heading = pending_intent->face_heading;
        snapshot->face_target_actor_address = pending_intent->face_target_actor_address;
        snapshot->target_x = pending_intent->target_x;
        snapshot->target_y = pending_intent->target_y;
        snapshot->distance_to_target = pending_intent->distance_to_target;
    }

    return true;
}
