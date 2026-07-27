bool TryResolveBotSpawnPlacement(
    std::uint64_t bot_id,
    multiplayer::ParticipantSceneIntentKind scene_kind,
    std::string_view phase,
    float anchor_x,
    float anchor_y,
    float* resolved_x,
    float* resolved_y,
    std::string* error_message) {
    return ResolveNativeBotSpawnPlacement(
        bot_id,
        scene_kind,
        phase,
        anchor_x,
        anchor_y,
        resolved_x,
        resolved_y,
        error_message);
}
