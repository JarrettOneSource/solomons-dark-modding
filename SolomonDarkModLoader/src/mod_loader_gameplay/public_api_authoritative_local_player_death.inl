bool TryApplyAuthoritativeLocalPlayerDeath(std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!multiplayer::IsLocalTransportClient()) {
        if (error_message != nullptr) {
            *error_message =
                "Authoritative local death replay requires a connected client.";
        }
        return false;
    }
    if (multiplayer::SnapshotRuntimeState().death_spectator.active) {
        return true;
    }

    SDModPlayerState player;
    if (!TryGetPlayerState(&player) ||
        !player.valid ||
        player.actor_address == 0 ||
        !std::isfinite(player.hp) ||
        !std::isfinite(player.max_hp) ||
        !std::isfinite(player.mp) ||
        !std::isfinite(player.max_mp) ||
        player.max_hp <= 0.0f ||
        player.max_mp <= 0.0f) {
        if (error_message != nullptr) {
            *error_message =
                "A live local player is required for native death replay.";
        }
        return false;
    }

    const float presentation_life =
        (std::min)(player.max_hp, 1.0f);
    if (!TryWriteLocalPlayerOrbResource(
            0,
            presentation_life,
            player.max_hp,
            player.mp,
            player.max_mp) ||
        !TryGetPlayerState(&player) ||
        !player.valid ||
        player.hp <= 0.0f) {
        if (error_message != nullptr) {
            *error_message =
                "The local player could not be primed for native death.";
        }
        return false;
    }

    PendingNativeMagicHitBehaviorProbe request{};
    request.magic_damage =
        (std::max)(1000.0f, player.max_hp * 16.0f);
    request.attempts = 1;

    const auto previous_target =
        g_client_owner_authorized_damage_target;
    const bool previous_replay =
        g_authoritative_local_player_damage_replay_active;
    g_client_owner_authorized_damage_target =
        player.actor_address;
    g_authoritative_local_player_damage_replay_active = true;
    float hp_before = 0.0f;
    float hp_after = 0.0f;
    std::string replay_error;
    const bool replayed = ExecuteNativeMagicHitBehaviorProbe(
        request,
        &hp_before,
        &hp_after,
        &replay_error);
    g_authoritative_local_player_damage_replay_active =
        previous_replay;
    g_client_owner_authorized_damage_target =
        previous_target;

    constexpr float kLethalLifeEpsilon = 0.05f;
    const auto spectator =
        multiplayer::SnapshotRuntimeState().death_spectator;
    if (!replayed ||
        !std::isfinite(hp_after) ||
        hp_after > kLethalLifeEpsilon ||
        !spectator.active ||
        spectator.phase !=
            multiplayer::DeathSpectatorPhase::DeathPresentation) {
        if (error_message != nullptr) {
            *error_message =
                "Native authoritative death replay did not converge. hp=" +
                std::to_string(hp_before) + "->" +
                std::to_string(hp_after) +
                (replay_error.empty()
                     ? std::string{}
                     : " error=" + replay_error);
        }
        return false;
    }

    Log(
        "Applied authoritative local player death through the stock damage "
        "path. hp=" +
        std::to_string(hp_before) + "->" +
        std::to_string(hp_after));
    return true;
}
