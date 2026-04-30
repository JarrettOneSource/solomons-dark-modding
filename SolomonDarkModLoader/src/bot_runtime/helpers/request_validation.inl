bool IsValidCreateRequest(const BotCreateRequest& request) {
    return
        IsValidCharacterProfile(request.character_profile) &&
        (!request.has_scene_intent || IsValidParticipantSceneIntent(request.scene_intent));
}

bool IsValidUpdateRequest(const BotUpdateRequest& request) {
    return request.bot_id != 0 &&
        (!request.has_scene_intent || IsValidParticipantSceneIntent(request.scene_intent));
}

bool IsValidCastRequest(const BotCastRequest& request) {
    if (request.bot_id == 0) {
        return false;
    }

    if (request.kind == BotCastKind::Secondary &&
        (request.secondary_slot < 0 || request.secondary_slot >= static_cast<std::int32_t>(DefaultBotLoadout().secondary_entry_indices.size()))) {
        return false;
    }

    return true;
}

bool IsValidMoveRequest(const BotMoveToRequest& request) {
    if (request.bot_id == 0) {
        return false;
    }

    return std::isfinite(request.target_x) && std::isfinite(request.target_y);
}

ParticipantSceneIntent ResolveDefaultBotSceneIntentFromCurrentScene() {
    ParticipantSceneIntent scene_intent = DefaultParticipantSceneIntent();

    SDModSceneState scene_state;
    if (!TryGetSceneState(&scene_state) || !scene_state.valid) {
        return scene_intent;
    }

    if (scene_state.name == "testrun" || scene_state.kind == "arena") {
        scene_intent.kind = ParticipantSceneIntentKind::Run;
        scene_intent.region_index = scene_state.current_region_index;
        scene_intent.region_type_id = scene_state.region_type_id;
        return scene_intent;
    }

    if (scene_state.name == "hub" || scene_state.kind == "hub") {
        scene_intent.kind = ParticipantSceneIntentKind::SharedHub;
        scene_intent.region_index = scene_state.current_region_index;
        scene_intent.region_type_id = scene_state.region_type_id;
        return scene_intent;
    }

    scene_intent.kind = ParticipantSceneIntentKind::PrivateRegion;
    scene_intent.region_index = scene_state.current_region_index;
    scene_intent.region_type_id = scene_state.region_type_id;
    return scene_intent;
}
