bool IsLocalRunSceneForHostExitFollow() {
    SDModSceneState scene_state;
    return TryGetSceneState(&scene_state) &&
           scene_state.valid &&
           (scene_state.kind == "arena" || scene_state.name == "testrun");
}

void ResetClientHostRunExitFollow(std::string_view reason) {
    const auto previous = g_local_transport.client_host_run_exit_follow;
    g_local_transport.client_host_run_exit_follow = ClientHostRunExitFollow{};
    if (!previous.active) {
        return;
    }
    Log(
        "Multiplayer client host-run exit follow cleared. run_nonce=" +
        std::to_string(previous.run_nonce) +
        " reason=" + std::string(reason));
}

void StageClientHostRunExitFollow(
    const StatePacket& packet,
    bool packet_from_configured_authority,
    std::uint64_t now_ms) {
    if (!IsLocalTransportClient() ||
        !packet_from_configured_authority ||
        packet.in_run != 0 ||
        packet.run_nonce == 0) {
        return;
    }

    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);
    if (local == nullptr ||
        !local->runtime.valid ||
        !local->runtime.in_run ||
        (local->runtime.run_nonce != 0 &&
         local->runtime.run_nonce != packet.run_nonce) ||
        !IsLocalRunSceneForHostExitFollow()) {
        return;
    }

    auto& follow = g_local_transport.client_host_run_exit_follow;
    if (follow.active && follow.run_nonce == packet.run_nonce) {
        follow.received_ms = now_ms;
        return;
    }

    follow = ClientHostRunExitFollow{};
    follow.active = true;
    follow.run_nonce = packet.run_nonce;
    follow.received_ms = now_ms;
    Log(
        "Multiplayer client accepted authenticated host run exit. authority_participant_id=" +
        std::to_string(packet.authority_participant_id) +
        " run_nonce=" + std::to_string(packet.run_nonce) +
        " packet_sequence=" + std::to_string(packet.header.sequence));
}

void ServiceClientHostRunExitFollow(std::uint64_t now_ms) {
    if (!IsLocalTransportClient()) {
        return;
    }

    auto& follow = g_local_transport.client_host_run_exit_follow;
    if (!follow.active) {
        return;
    }
    if (follow.received_ms == 0 ||
        now_ms > follow.received_ms + kClientHostRunExitFollowExpiryMs) {
        ResetClientHostRunExitFollow("expired");
        return;
    }

    if (!IsLocalRunSceneForHostExitFollow()) {
        ResetClientHostRunExitFollow("local scene left run");
        return;
    }

    if (follow.action_request_id != 0) {
        DebugUiActionDispatchSnapshot dispatch;
        if (!TryGetDebugUiActionDispatchSnapshot(
                follow.action_request_id,
                &dispatch)) {
            return;
        }
        if (dispatch.status == "failed") {
            Log(
                "Multiplayer client host-run exit action failed. run_nonce=" +
                std::to_string(follow.run_nonce) +
                " error=" + dispatch.error_message);
            follow.action_request_id = 0;
            follow.last_action_attempt_ms = now_ms;
            return;
        }
        return;
    }

    DebugUiSnapshotElement leave_game;
    if (TryFindDebugUiActionElement(
            "pause_menu.leave_game",
            "simple_menu",
            &leave_game)) {
        if (follow.last_action_attempt_ms != 0 &&
            now_ms < follow.last_action_attempt_ms +
                         kClientHostRunExitActionRetryMs) {
            return;
        }
        follow.last_action_attempt_ms = now_ms;
        std::string action_error;
        std::uint64_t request_id = 0;
        if (!TryActivateDebugUiAction(
                "pause_menu.leave_game",
                "simple_menu",
                &request_id,
                &action_error)) {
            Log(
                "Multiplayer client could not queue host-run exit action. run_nonce=" +
                std::to_string(follow.run_nonce) +
                " error=" + action_error);
            return;
        }
        follow.action_request_id = request_id;
        Log(
            "Multiplayer client queued stock Leave Game for authenticated host run exit. run_nonce=" +
            std::to_string(follow.run_nonce) +
            " action_request_id=" + std::to_string(request_id));
        return;
    }

    DebugUiSurfaceSnapshot snapshot;
    const bool pause_menu_visible =
        TryGetLatestDebugUiSurfaceSnapshot(&snapshot) &&
        snapshot.surface_id == "simple_menu";
    if (pause_menu_visible ||
        follow.menu_request_count >= kClientHostRunExitMenuMaxAttempts ||
        (follow.last_menu_request_ms != 0 &&
         now_ms < follow.last_menu_request_ms +
                      kClientHostRunExitMenuRetryMs)) {
        return;
    }

    std::string menu_error;
    if (!QueueGameplayKeyPress("menu", &menu_error)) {
        Log(
            "Multiplayer client could not open the pause menu for host run exit. run_nonce=" +
            std::to_string(follow.run_nonce) +
            " error=" + menu_error);
        return;
    }
    follow.last_menu_request_ms = now_ms;
    follow.menu_request_count += 1;
    Log(
        "Multiplayer client queued pause menu for authenticated host run exit. run_nonce=" +
        std::to_string(follow.run_nonce) +
        " attempt=" + std::to_string(follow.menu_request_count));
}
