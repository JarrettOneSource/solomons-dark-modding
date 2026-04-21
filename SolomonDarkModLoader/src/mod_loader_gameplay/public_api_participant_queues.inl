bool QueueParticipantEntitySync(
    std::uint64_t participant_id,
    const multiplayer::MultiplayerCharacterProfile& character_profile,
    const multiplayer::ParticipantSceneIntent& scene_intent,
    bool has_transform,
    bool has_heading,
    float position_x,
    float position_y,
    float heading,
    std::string* error_message) {
    PendingParticipantEntitySyncRequest request;
    request.bot_id = participant_id;
    request.character_profile = character_profile;
    request.scene_intent = scene_intent;
    request.has_transform = has_transform;
    request.has_heading = has_heading;
    request.x = position_x;
    request.y = position_y;
    request.heading = heading;

    uintptr_t gameplay_address = 0;
    if (!TryResolveCurrentGameplayScene(&gameplay_address) || gameplay_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Gameplay scene is not active.";
        }
        return false;
    }

    if (!g_gameplay_keyboard_injection.initialized) {
        if (error_message != nullptr) {
            *error_message = "participant sync: gameplay action pump is not initialized.";
        }
        return false;
    }

    return QueueParticipantSyncRequest(request, error_message);
}

bool QueueParticipantDestroy(std::uint64_t participant_id, std::string* error_message) {
    uintptr_t gameplay_address = 0;
    if (!TryResolveCurrentGameplayScene(&gameplay_address) || gameplay_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Gameplay scene is not active.";
        }
        return false;
    }

    if (!g_gameplay_keyboard_injection.initialized) {
        if (error_message != nullptr) {
            *error_message = "participant destroy: gameplay action pump is not initialized.";
        }
        return false;
    }

    return QueueParticipantDestroyRequest(participant_id, error_message);
}

