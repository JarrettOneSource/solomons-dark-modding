template <typename Packet>
void PopulateLuaTimeControlPacketFieldsImpl(Packet* packet) {
    if (packet == nullptr || !g_local_transport.is_host) return;
    const auto time = SnapshotLuaTimeControl();
    packet->lua_time_scale_units = time.scale_units;
    packet->lua_time_revision = time.revision;
}

void PopulateLuaTimeControlPacketFields(StatePacket* packet) {
    PopulateLuaTimeControlPacketFieldsImpl(packet);
}

void PopulateLuaTimeControlPacketFields(ParticipantFramePacket* packet) {
    PopulateLuaTimeControlPacketFieldsImpl(packet);
}

bool IsCurrentLuaTimeRun(std::uint32_t run_nonce) {
    const auto runtime = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime);
    return local != nullptr && local->runtime.in_run && run_nonce != 0 &&
        local->runtime.run_nonce == run_nonce;
}

void ApplyAuthoritativeLuaTimeControlSnapshot(
    std::uint64_t authority_participant_id,
    std::uint32_t run_nonce,
    std::uint32_t scale_units,
    std::uint32_t revision) {
    if (!IsLocalTransportClient() ||
        !IsCurrentLuaTimeRun(run_nonce)) {
        return;
    }
    (void)ApplyReplicatedLuaTimeControl(
        authority_participant_id,
        run_nonce,
        scale_units,
        revision,
        0,
        0);
}

bool IsAuthorizedLuaTimeControlPacket(
    const LuaTimeControlPacket& packet,
    const TransportPeerEndpoint& from) {
    if (!IsLocalTransportClient() ||
        !IsConfiguredRemoteAuthorityEndpoint(from)) {
        return false;
    }
    const auto peer = std::find_if(
        g_local_transport.peers.begin(),
        g_local_transport.peers.end(),
        [&](const LocalPeerEndpoint& candidate) {
            return SameEndpoint(candidate.endpoint, from) &&
                candidate.participant_id ==
                    packet.authority_participant_id;
        });
    const auto nonce = g_local_transport.session_nonce_by_participant.find(
        packet.authority_participant_id);
    return peer != g_local_transport.peers.end() &&
        nonce != g_local_transport.session_nonce_by_participant.end() &&
        nonce->second == packet.authority_session_nonce;
}

void ApplyLuaTimeControlPacket(
    const LuaTimeControlPacket& packet,
    const TransportPeerEndpoint& from) {
    if (!IsAuthorizedLuaTimeControlPacket(packet, from) ||
        !IsCurrentLuaTimeRun(packet.run_nonce)) {
        return;
    }
    const auto step_frames =
        (packet.flags & LuaTimeControlPacketFlagStepFrames) != 0
            ? packet.step_frames
            : 0u;
    (void)ApplyReplicatedLuaTimeControl(
        packet.authority_participant_id,
        packet.run_nonce,
        packet.scale_units,
        packet.revision,
        packet.step_sequence,
        step_frames);
}

void SendLuaTimeControlUpdate() {
    if (!g_local_transport.initialized || !g_local_transport.is_host) return;
    const auto time = SnapshotLuaTimeControl();
    if (time.revision == g_last_lua_time_control_revision_sent) return;

    const auto runtime = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime);
    if (local == nullptr || !local->runtime.in_run ||
        local->runtime.run_nonce == 0 ||
        g_local_transport.local_peer_id == 0 ||
        g_local_transport.local_session_nonce == 0) {
        g_last_lua_time_control_revision_sent = time.revision;
        MarkLuaTimeControlUpdateSent(time.revision);
        return;
    }

    LuaTimeControlPacket packet{};
    packet.header = MakePacketHeader(
        PacketKind::LuaTimeControl,
        g_local_transport.next_sequence++);
    packet.authority_participant_id = g_local_transport.local_peer_id;
    packet.authority_session_nonce = g_local_transport.local_session_nonce;
    packet.run_nonce = local->runtime.run_nonce;
    packet.revision = time.revision;
    packet.scale_units = time.scale_units;
    packet.step_sequence = time.step_sequence;
    packet.step_frames = time.unsent_step_frames;
    if (packet.step_frames != 0) {
        packet.flags |= LuaTimeControlPacketFlagStepFrames;
    }
    for (const auto& endpoint : BuildKnownSendEndpoints()) {
        SendPacketToEndpoint(
            packet,
            endpoint,
            SteamNetworkSendMode::ReliableNoNagle);
    }
    g_last_lua_time_control_revision_sent = time.revision;
    MarkLuaTimeControlUpdateSent(time.revision);
}
