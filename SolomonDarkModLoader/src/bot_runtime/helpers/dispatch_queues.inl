bool TryDispatchEntitySync(
    std::uint64_t bot_id,
    const MultiplayerCharacterProfile& character_profile,
    const ParticipantSceneIntent& scene_intent,
    bool has_transform,
    bool has_heading,
    float position_x,
    float position_y,
    float heading,
    std::string* error_message) {
    return QueueParticipantEntitySync(
        bot_id,
        character_profile,
        scene_intent,
        has_transform,
        has_heading,
        position_x,
        position_y,
        heading,
        error_message);
}

bool TryDispatchDestroy(std::uint64_t bot_id, std::string* error_message) {
    return QueueParticipantDestroy(bot_id, error_message);
}
