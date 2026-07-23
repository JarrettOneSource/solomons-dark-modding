bool BeginLocalDeathSpectatorPresentation() {
    if (!g_local_transport.initialized) {
        return false;
    }
    if (g_local_death_spectator.phase !=
        DeathSpectatorPhase::Inactive) {
        return true;
    }

    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);
    SDModPlayerState player;
    if (local == nullptr ||
        !local->runtime.valid ||
        !local->runtime.in_run ||
        local->runtime.run_nonce == 0 ||
        !TryGetPlayerState(&player) ||
        !player.valid ||
        player.actor_address == 0 ||
        !std::isfinite(player.hp) ||
        !std::isfinite(player.max_hp) ||
        player.max_hp <= 0.0f ||
        player.hp > 0.0f) {
        return false;
    }

    g_local_death_spectator.phase =
        DeathSpectatorPhase::DeathPresentation;
    g_local_death_spectator.death_started_ms =
        static_cast<std::uint64_t>(GetTickCount64());
    g_local_death_spectator.observed_mouse_left_edge_serial =
        GetGameplayMouseLeftEdgeSerial();
    g_local_death_spectator.observed_mouse_right_edge_serial =
        GetGameplayMouseRightEdgeSerial();
    g_local_death_spectator.click_armed =
        !IsGameplayMouseLeftDown() &&
        !IsGameplayMouseRightDown();
    if (!g_local_death_spectator.click_armed) {
        g_local_death_spectator.click_consumed_ms =
            g_local_death_spectator.death_started_ms;
    }
    std::string cast_clear_error;
    if (!ClearLocalPlayerGameplayCastState(&cast_clear_error)) {
        Log(
            "Multiplayer death spectator could not fully clear the local cast "
            "state. error=" +
            cast_clear_error);
    }
    PublishLocalDeathSpectatorRuntime(
        g_local_death_spectator.death_started_ms);
    Log(
        "Multiplayer death presentation started. participant_id=" +
        std::to_string(g_local_transport.local_peer_id) +
        " duration_ms=" +
        std::to_string(kDeathPresentationDurationMs));
    return true;
}

bool TryBuildDeathSpectatorStatusText(std::string* status_text) {
    if (status_text == nullptr) {
        return false;
    }
    status_text->clear();
    const auto runtime = SnapshotRuntimeState().death_spectator;
    if (!runtime.active ||
        runtime.phase != DeathSpectatorPhase::Spectating) {
        return false;
    }
    if (runtime.target_participant_id == 0 ||
        runtime.target_name.empty()) {
        *status_text = "Spectating - waiting for an alive player";
    } else {
        *status_text =
            "Spectating " + runtime.target_name +
            "  |  Left / Right click: next player";
    }
    return true;
}
