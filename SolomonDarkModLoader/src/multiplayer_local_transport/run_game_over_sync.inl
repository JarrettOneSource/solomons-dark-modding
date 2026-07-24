struct RunGameOverCommandState {
    std::uint32_t next_command_epoch = 1;
    std::uint32_t command_epoch = 0;
    std::uint32_t accepted_epoch = 0;
    std::uint32_t run_nonce = 0;
    std::uint64_t authority_participant_id = 0;
    bool pending_dispatch = false;
    std::uint32_t dispatch_count = 0;
    std::unordered_set<std::uint64_t>
        expected_participant_ids;
    std::unordered_set<std::uint64_t>
        acknowledged_participant_ids;
};

RunGameOverCommandState g_run_game_over;

void PublishRunGameOverRuntime() {
    RunGameOverRuntimeInfo current;
    current.command_epoch = g_run_game_over.command_epoch;
    current.accepted_epoch = g_run_game_over.accepted_epoch;
    current.run_nonce = g_run_game_over.run_nonce;
    current.authority_participant_id =
        g_run_game_over.authority_participant_id;
    current.pending_dispatch = g_run_game_over.pending_dispatch;
    current.dispatch_count = g_run_game_over.dispatch_count;
    UpdateRuntimeState([&](RuntimeState& state) {
        state.game_over = current;
    });
}

void ResetRunGameOverState(std::string_view reason) {
    const bool was_active =
        g_run_game_over.command_epoch != 0 ||
        g_run_game_over.accepted_epoch != 0 ||
        g_run_game_over.pending_dispatch ||
        g_run_game_over.dispatch_count != 0;
    g_run_game_over = RunGameOverCommandState{};
    PublishRunGameOverRuntime();
    if (was_active) {
        Log(
            "Multiplayer Game Over command retired. reason=" +
            std::string(reason));
    }
}

bool IsRunGameOverAccepted(std::uint32_t run_nonce) {
    return run_nonce != 0 &&
           g_run_game_over.accepted_epoch != 0 &&
           g_run_game_over.run_nonce == run_nonce;
}

bool HostRunGameOverAcknowledgedByAllParticipants() {
    if (!g_local_transport.is_host ||
        g_run_game_over.expected_participant_ids.empty()) {
        return false;
    }
    for (const auto participant_id :
         g_run_game_over.expected_participant_ids) {
        if (g_run_game_over.acknowledged_participant_ids.find(
                participant_id) ==
            g_run_game_over.acknowledged_participant_ids.end()) {
            return false;
        }
    }
    return true;
}

bool IsConnectedRunGameOverMember(
    const ParticipantInfo& participant,
    std::uint32_t run_nonce) {
    return participant.participant_id != 0 &&
           participant.ready &&
           (participant.kind == ParticipantKind::LocalHuman ||
            participant.transport_connected) &&
           participant.runtime.valid &&
           participant.runtime.in_run &&
           participant.runtime.run_nonce == run_nonce;
}

bool IsParticipantTerminallyDead(
    const ParticipantInfo& participant) {
    return std::isfinite(participant.runtime.life_current) &&
           std::isfinite(participant.runtime.life_max) &&
           participant.runtime.life_max > 0.0f &&
           participant.runtime.life_current <= 0.0f &&
           participant.runtime.anim_drive_state != 0;
}

bool AcceptRunGameOverCommand(
    std::uint32_t command_epoch,
    std::uint32_t run_nonce,
    std::uint64_t authority_participant_id,
    std::string_view source) {
    if (!g_local_transport.initialized ||
        command_epoch == 0 ||
        run_nonce == 0 ||
        authority_participant_id == 0) {
        return false;
    }

    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);
    if (local == nullptr ||
        !local->runtime.valid ||
        !local->runtime.in_run ||
        local->runtime.run_nonce != run_nonce) {
        return false;
    }
    if (g_local_transport.is_host &&
        authority_participant_id != g_local_transport.local_peer_id) {
        return false;
    }
    if (g_run_game_over.accepted_epoch != 0) {
        return g_run_game_over.accepted_epoch == command_epoch &&
               g_run_game_over.run_nonce == run_nonce &&
               g_run_game_over.authority_participant_id ==
                   authority_participant_id;
    }

    g_run_game_over.command_epoch = command_epoch;
    g_run_game_over.accepted_epoch = command_epoch;
    g_run_game_over.run_nonce = run_nonce;
    g_run_game_over.authority_participant_id =
        authority_participant_id;
    g_run_game_over.pending_dispatch = true;
    g_run_game_over.dispatch_count = 0;
    if (g_local_transport.is_host) {
        g_run_game_over.acknowledged_participant_ids.insert(
            g_local_transport.local_peer_id);
    }
    g_local_transport.client_host_run_exit_follow =
        ClientHostRunExitFollow{};
    ResetLocalDeathSpectatorState("all_players_dead");
    ResetWaveRespawnState();
    PublishRunGameOverRuntime();
    Log(
        "Multiplayer native Game Over command accepted. source=" +
        std::string(source) +
        " authority_participant_id=" +
        std::to_string(authority_participant_id) +
        " run_nonce=" + std::to_string(run_nonce) +
        " command_epoch=" + std::to_string(command_epoch));
    return true;
}

void RefreshHostRunGameOverCommand() {
    if (!g_local_transport.initialized ||
        !g_local_transport.is_host ||
        g_run_game_over.accepted_epoch != 0) {
        return;
    }

    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);
    if (local == nullptr ||
        !local->runtime.valid ||
        !local->runtime.in_run ||
        local->runtime.run_nonce == 0) {
        return;
    }

    std::vector<std::uint64_t> member_ids;
    for (const auto& participant : runtime_state.participants) {
        if (!IsConnectedRunGameOverMember(
                participant,
                local->runtime.run_nonce)) {
            continue;
        }
        member_ids.push_back(
            participant.kind == ParticipantKind::LocalHuman
                ? g_local_transport.local_peer_id
                : participant.participant_id);
        if (!IsParticipantTerminallyDead(participant)) {
            return;
        }
    }
    if (member_ids.size() < 2) {
        return;
    }

    auto command_epoch = g_run_game_over.next_command_epoch++;
    if (command_epoch == 0) {
        command_epoch = g_run_game_over.next_command_epoch++;
    }
    g_run_game_over.expected_participant_ids.insert(
        member_ids.begin(),
        member_ids.end());
    if (!AcceptRunGameOverCommand(
        command_epoch,
        local->runtime.run_nonce,
        g_local_transport.local_peer_id,
        "host_all_players_dead")) {
        g_run_game_over.expected_participant_ids.clear();
    }
}

template <typename Packet>
void RecordRunGameOverAcknowledgement(const Packet& packet) {
    if (!g_local_transport.is_host ||
        g_run_game_over.accepted_epoch == 0 ||
        packet.game_over_ack_epoch !=
            g_run_game_over.accepted_epoch ||
        packet.game_over_run_nonce !=
            g_run_game_over.run_nonce ||
        packet.run_nonce != g_run_game_over.run_nonce ||
        g_run_game_over.expected_participant_ids.find(
            packet.participant_id) ==
            g_run_game_over.expected_participant_ids.end()) {
        return;
    }

    const bool inserted =
        g_run_game_over.acknowledged_participant_ids.insert(
            packet.participant_id).second;
    if (inserted &&
        HostRunGameOverAcknowledgedByAllParticipants()) {
        Log(
            "Multiplayer native Game Over acknowledged by every "
            "terminal run participant. run_nonce=" +
            std::to_string(g_run_game_over.run_nonce) +
            " command_epoch=" +
            std::to_string(g_run_game_over.command_epoch));
    }
}

template <typename Packet>
void PopulateRunGameOverPacketFields(Packet* packet) {
    if (packet == nullptr ||
        g_run_game_over.accepted_epoch == 0 ||
        g_run_game_over.run_nonce == 0) {
        return;
    }
    packet->run_nonce = g_run_game_over.run_nonce;
    packet->game_over_command_epoch =
        g_local_transport.is_host &&
                !HostRunGameOverAcknowledgedByAllParticipants()
            ? g_run_game_over.command_epoch
            : 0;
    packet->game_over_ack_epoch =
        g_run_game_over.accepted_epoch;
    packet->game_over_run_nonce =
        g_run_game_over.run_nonce;
}

template <typename Packet>
bool HasRunGameOverPacketWork(const Packet& packet) {
    return packet.game_over_run_nonce != 0 &&
           (packet.game_over_command_epoch != 0 ||
            packet.game_over_ack_epoch != 0);
}

template <typename Packet>
void ApplyAuthoritativeRunGameOver(
    const Packet& packet,
    bool packet_from_configured_authority) {
    if (!g_local_transport.initialized ||
        g_local_transport.is_host ||
        !packet_from_configured_authority) {
        return;
    }
    if (packet.game_over_command_epoch == 0 ||
        packet.game_over_run_nonce == 0 ||
        packet.game_over_run_nonce != packet.run_nonce) {
        return;
    }
    (void)AcceptRunGameOverCommand(
        packet.game_over_command_epoch,
        packet.game_over_run_nonce,
        packet.authority_participant_id,
        "authority_packet");
}
