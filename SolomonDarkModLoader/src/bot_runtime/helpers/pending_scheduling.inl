void SchedulePendingEntitySyncLocked(
    std::uint64_t bot_id,
    const MultiplayerCharacterProfile& character_profile,
    const ParticipantSceneIntent& scene_intent,
    bool has_transform,
    bool has_heading,
    float position_x,
    float position_y,
    float heading,
    std::uint64_t now_ms) {
    auto* pending_sync = FindPendingEntitySync(bot_id);
    if (pending_sync == nullptr) {
        g_pending_entity_syncs.push_back(PendingBotEntitySync{});
        pending_sync = &g_pending_entity_syncs.back();
        pending_sync->bot_id = bot_id;
    }

    pending_sync->generation = g_next_entity_sync_generation++;
    pending_sync->character_profile = character_profile;
    pending_sync->scene_intent = scene_intent;
    pending_sync->has_transform = has_transform;
    pending_sync->has_heading = has_heading;
    pending_sync->position_x = position_x;
    pending_sync->position_y = position_y;
    pending_sync->heading = heading;
    pending_sync->next_attempt_ms = now_ms;
}

void SchedulePendingMovementIntentLocked(
    std::uint64_t bot_id,
    BotControllerState state,
    bool has_target,
    float target_x,
    float target_y,
    bool desired_heading_valid,
    float desired_heading) {
    auto* pending_intent = FindPendingMovementIntent(bot_id);
    if (pending_intent == nullptr) {
        g_bot_movement_intents.push_back(PendingBotMovementIntent{});
        pending_intent = &g_bot_movement_intents.back();
        pending_intent->bot_id = bot_id;
    }

    pending_intent->revision = g_next_movement_intent_revision++;
    pending_intent->state = state;
    pending_intent->has_target = has_target;
    pending_intent->target_x = target_x;
    pending_intent->target_y = target_y;
    pending_intent->distance_to_target = 0.0f;
    pending_intent->direction_x = 0.0f;
    pending_intent->direction_y = 0.0f;
    pending_intent->desired_heading_valid = desired_heading_valid;
    pending_intent->desired_heading = desired_heading;
}

void SetPendingFaceHeadingLocked(std::uint64_t bot_id, bool valid, float heading, std::uint64_t expires_ms) {
    auto* pending_intent = FindPendingMovementIntent(bot_id);
    if (pending_intent == nullptr) {
        g_bot_movement_intents.push_back(PendingBotMovementIntent{});
        pending_intent = &g_bot_movement_intents.back();
        pending_intent->bot_id = bot_id;
        pending_intent->revision = g_next_movement_intent_revision++;
    }

    pending_intent->face_heading_valid = valid;
    pending_intent->face_heading = heading;
    pending_intent->face_heading_expires_ms = expires_ms;
}

void SetPendingFaceTargetLocked(std::uint64_t bot_id, uintptr_t target_actor_address) {
    auto* pending_intent = FindPendingMovementIntent(bot_id);
    if (pending_intent == nullptr) {
        g_bot_movement_intents.push_back(PendingBotMovementIntent{});
        pending_intent = &g_bot_movement_intents.back();
        pending_intent->bot_id = bot_id;
        pending_intent->revision = g_next_movement_intent_revision++;
    }

    pending_intent->face_target_actor_address = target_actor_address;
}

void ClearDeadBotControlsLocked(const ParticipantInfo& participant) {
    const auto bot_id = participant.participant_id;
    if (bot_id == 0) {
        return;
    }

    RemovePendingCast(bot_id);
    const auto* previous_intent = FindPendingMovementIntent(bot_id);
    const auto desired_heading_valid =
        participant.runtime.transform_valid ||
        (previous_intent != nullptr && previous_intent->desired_heading_valid);
    const auto desired_heading =
        participant.runtime.transform_valid
            ? NormalizeHeadingDegrees(participant.runtime.heading)
            : (previous_intent != nullptr ? previous_intent->desired_heading : 0.0f);
    SchedulePendingMovementIntentLocked(
        bot_id,
        BotControllerState::Idle,
        false,
        0.0f,
        0.0f,
        desired_heading_valid,
        desired_heading);
    SetPendingFaceHeadingLocked(bot_id, false, 0.0f, 0);
    SetPendingFaceTargetLocked(bot_id, 0);
}

void SchedulePendingDestroyLocked(std::uint64_t bot_id) {
    auto* pending_destroy = FindPendingDestroy(bot_id);
    if (pending_destroy == nullptr) {
        g_pending_destroys.push_back(PendingBotDestroy{});
        pending_destroy = &g_pending_destroys.back();
        pending_destroy->bot_id = bot_id;
    }

    pending_destroy->generation = g_next_destroy_generation++;
}
