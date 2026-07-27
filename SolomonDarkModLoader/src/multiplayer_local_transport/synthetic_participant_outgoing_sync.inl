void SendSyntheticParticipantState(std::uint64_t now_ms) {
    if (!g_local_transport.is_host) {
        return;
    }

    const auto runtime_state = SnapshotRuntimeState();
    const auto endpoints = BuildKnownSendEndpoints();
    for (auto it =
             g_local_transport.retired_synthetic_participants.begin();
         it !=
         g_local_transport.retired_synthetic_participants.end();) {
        auto& retirement = it->second;
        if (retirement.created_ms != 0 &&
            now_ms >= retirement.created_ms +
                kSyntheticParticipantRetirementHoldMs) {
            it =
                g_local_transport.retired_synthetic_participants.erase(
                    it);
            continue;
        }
        if (!endpoints.empty() &&
            (retirement.last_send_ms == 0 ||
             now_ms - retirement.last_send_ms >=
                 kSyntheticParticipantRetirementResendIntervalMs)) {
            for (const auto& endpoint : endpoints) {
                SendPacketToEndpoint(
                    retirement.packet,
                    endpoint,
                    SteamNetworkSendMode::ReliableNoNagle);
            }
            retirement.last_send_ms = now_ms;
        }
        ++it;
    }

    for (const auto& participant : runtime_state.participants) {
        if (!IsRemoteParticipant(participant) ||
            !IsLuaControlledParticipant(participant)) {
            continue;
        }

        auto* transport_state =
            EnsureSyntheticParticipantTransportState(
                participant.participant_id);
        if (transport_state == nullptr) {
            continue;
        }

        if (!endpoints.empty() &&
            (transport_state->last_state_send_ms == 0 ||
             now_ms - transport_state->last_state_send_ms >=
                 kLocalTransportStateCheckpointIntervalMs)) {
            StatePacket state_packet{};
            if (BuildSyntheticParticipantStatePacket(
                    runtime_state,
                    participant,
                    transport_state->session_nonce,
                    ParticipantStateFlagNone,
                    &state_packet)) {
                for (const auto& endpoint : endpoints) {
                    SendPacketToEndpoint(
                        state_packet,
                        endpoint,
                        SteamNetworkSendMode::ReliableNoNagle);
                }
                transport_state->last_state_send_ms = now_ms;
            }
        }

        if (!endpoints.empty() &&
            participant.runtime.transform_valid &&
            (transport_state->last_frame_send_ms == 0 ||
             now_ms - transport_state->last_frame_send_ms >=
                 kLocalTransportParticipantFrameIntervalMs)) {
            ParticipantFramePacket frame_packet{};
            if (BuildSyntheticParticipantFramePacket(
                    runtime_state,
                    participant,
                    transport_state->session_nonce,
                    &frame_packet)) {
                for (const auto& endpoint : endpoints) {
                    SendPacketToEndpoint(frame_packet, endpoint);
                }
                transport_state->last_frame_send_ms = now_ms;
            }
        }
    }
}
