bool UpdateBot(const BotUpdateRequest& request) {
    std::scoped_lock lock(g_bot_runtime_mutex);
    if (!g_bot_runtime_initialized || !IsValidUpdateRequest(request)) {
        return false;
    }

    if (request.has_transform && !request.has_scene_intent) {
        SDModParticipantGameplayState gameplay_state;
        if (TryGetParticipantGameplayState(request.bot_id, &gameplay_state) &&
            gameplay_state.available &&
            gameplay_state.entity_materialized &&
            gameplay_state.entity_kind == kSDModParticipantGameplayKindRegisteredGameNpc) {
            Log(
                "[bots] rejecting transform-only update for materialized registered_gamenpc. bot_id=" +
                std::to_string(request.bot_id) +
                " actor=" + HexString(gameplay_state.actor_address));
            return false;
        }
    }

    bool updated = false;
    MultiplayerCharacterProfile sync_character_profile = DefaultCharacterProfile();
    ParticipantSceneIntent sync_scene_intent = DefaultParticipantSceneIntent();
    bool sync_has_transform = false;
    bool sync_has_heading = false;
    float sync_position_x = 0.0f;
    float sync_position_y = 0.0f;
    float sync_heading = 0.0f;
    UpdateRuntimeState([&](RuntimeState& state) {
        auto* participant = FindBot(state, request.bot_id);
        if (participant == nullptr) {
            return;
        }

        if (request.has_display_name) {
            participant->name = request.display_name.empty() ? DefaultBotName(request.bot_id) : request.display_name;
        }
        if (request.has_character_profile) {
            ApplyCharacterProfile(participant, request.character_profile);
        }
        if (request.has_scene_intent) {
            ApplySceneIntent(participant, request.scene_intent);
        }
        if (request.has_ready) {
            participant->ready = request.ready;
        }
        if (request.has_transform) {
            ApplyTransform(
                participant,
                request.position_x,
                request.position_y,
                request.has_heading,
                request.heading);
        }
        sync_character_profile = participant->character_profile;
        sync_scene_intent = participant->runtime.scene_intent;
        sync_has_transform = participant->runtime.transform_valid;
        sync_has_heading = request.has_heading;
        sync_position_x = participant->runtime.position_x;
        sync_position_y = participant->runtime.position_y;
        sync_heading = participant->runtime.heading;
        updated = true;
    });

    if (updated && (request.has_character_profile || request.has_scene_intent || request.has_transform)) {
        std::string sync_error_message;
        if (!TryDispatchEntitySync(
                request.bot_id,
                sync_character_profile,
                sync_scene_intent,
                sync_has_transform,
                sync_has_heading,
                sync_position_x,
                sync_position_y,
                sync_heading,
                &sync_error_message)) {
            SchedulePendingEntitySyncLocked(
                request.bot_id,
                sync_character_profile,
                sync_scene_intent,
                sync_has_transform,
                sync_has_heading,
                sync_position_x,
                sync_position_y,
                sync_heading,
                GetTickCount64());
            Log(
                "[bots] gameplay sync request deferred during update. bot_id=" +
                std::to_string(request.bot_id) + " error=" + sync_error_message);
        }
    }

    if (updated && request.has_transform && request.has_heading) {
        if (auto* controller = FindPendingMovementIntent(request.bot_id);
            controller != nullptr && controller->state == BotControllerState::Idle) {
            controller->desired_heading_valid = true;
            controller->desired_heading = sync_heading;
        }
    }

    return updated;
}
