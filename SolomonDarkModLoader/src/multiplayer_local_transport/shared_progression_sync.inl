bool TryGetSharedProgressionForRun(
    std::uint32_t run_nonce,
    SharedProgressionTransportState* state) {
    if (state != nullptr) {
        *state = SharedProgressionTransportState{};
    }
    const auto& shared = g_local_transport.shared_progression;
    if (!shared.valid ||
        run_nonce == 0 ||
        shared.run_nonce != run_nonce) {
        return false;
    }
    if (state != nullptr) {
        *state = shared;
    }
    return true;
}

void ApplySharedProgressionToParticipantRuntime(
    std::uint32_t run_nonce,
    ParticipantRuntimeInfo* runtime) {
    if (runtime == nullptr) {
        return;
    }
    SharedProgressionTransportState shared;
    if (!TryGetSharedProgressionForRun(run_nonce, &shared)) {
        return;
    }
    runtime->level = shared.level;
    runtime->experience_current =
        static_cast<std::int32_t>(std::lround(shared.experience));
    runtime->experience_next = shared.experience_next;
}

void PublishAuthoritativeSharedProgressionInternal(
    std::uint64_t killer_participant_id,
    std::uint32_t run_nonce,
    std::int32_t level,
    float experience,
    std::int32_t experience_next) {
    if (killer_participant_id == 0 ||
        run_nonce == 0 ||
        level <= 0 ||
        !std::isfinite(experience) ||
        experience < 0.0f ||
        experience_next <= 0 ||
        IsLocalTransportClient()) {
        return;
    }

    SharedProgressionPacket packet{};
    packet.header = MakePacketHeader(
        PacketKind::SharedProgression,
        g_local_transport.next_sequence++);
    packet.authority_participant_id =
        g_local_transport.local_peer_id;
    packet.killer_participant_id = killer_participant_id;
    packet.run_nonce = run_nonce;
    packet.revision =
        g_local_transport.next_shared_progression_revision++;
    if (g_local_transport.next_shared_progression_revision == 0) {
        g_local_transport.next_shared_progression_revision = 1;
    }
    packet.level = level;
    packet.experience = experience;
    packet.experience_next = experience_next;

    auto& shared = g_local_transport.shared_progression;
    shared.valid = true;
    shared.authority_participant_id =
        packet.authority_participant_id;
    shared.killer_participant_id = killer_participant_id;
    shared.run_nonce = run_nonce;
    shared.revision = packet.revision;
    shared.packet_sequence = packet.header.sequence;
    shared.level = level;
    shared.experience = experience;
    shared.experience_next = experience_next;

    for (const auto& endpoint : BuildKnownSendEndpoints()) {
        SendPacketToEndpoint(
            packet,
            endpoint,
            SteamNetworkSendMode::ReliableNoNagle);
    }
    Log(
        "Multiplayer shared progression published. authority_participant_id=" +
        std::to_string(packet.authority_participant_id) +
        " killer_participant_id=" +
        std::to_string(killer_participant_id) +
        " run_nonce=" + std::to_string(run_nonce) +
        " revision=" + std::to_string(packet.revision) +
        " level=" + std::to_string(level) +
        " xp=" + std::to_string(experience) +
        " next_xp=" + std::to_string(experience_next));
}

void ApplySharedProgressionPacket(
    const SharedProgressionPacket& packet,
    const TransportPeerEndpoint& from,
    std::uint64_t now_ms) {
    if (!IsLocalTransportClient() ||
        !IsConfiguredRemoteAuthorityEndpoint(from) ||
        packet.authority_participant_id == 0 ||
        packet.authority_participant_id ==
            g_local_transport.local_peer_id ||
        packet.killer_participant_id == 0 ||
        packet.run_nonce == 0 ||
        packet.revision == 0 ||
        packet.level <= 0 ||
        !std::isfinite(packet.experience) ||
        packet.experience < 0.0f ||
        packet.experience_next <= 0) {
        return;
    }

    const auto runtime = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime);
    if (local == nullptr ||
        !local->runtime.valid ||
        !local->runtime.in_run ||
        local->runtime.run_nonce != packet.run_nonce) {
        return;
    }
    const auto& previous = g_local_transport.shared_progression;
    if (previous.valid &&
        previous.run_nonce == packet.run_nonce &&
        (!IsPacketSequenceNewer(
             packet.header.sequence,
             previous.packet_sequence) ||
         packet.revision <= previous.revision)) {
        return;
    }

    std::string sync_error;
    if (!SyncLocalPlayerProgressionToSharedSnapshot(
            packet.level,
            packet.experience,
            packet.experience_next,
            &sync_error)) {
        Log(
            "Multiplayer shared progression rejected; local native sync "
            "failed. run_nonce=" +
            std::to_string(packet.run_nonce) +
            " revision=" + std::to_string(packet.revision) +
            " error=" + sync_error);
        return;
    }

    auto& shared = g_local_transport.shared_progression;
    shared.valid = true;
    shared.authority_participant_id =
        packet.authority_participant_id;
    shared.killer_participant_id =
        packet.killer_participant_id;
    shared.run_nonce = packet.run_nonce;
    shared.revision = packet.revision;
    shared.packet_sequence = packet.header.sequence;
    shared.level = packet.level;
    shared.experience = packet.experience;
    shared.experience_next = packet.experience_next;

    const auto rounded_experience =
        static_cast<std::int32_t>(std::lround(packet.experience));
    UpdateRuntimeState([&](RuntimeState& state) {
        for (auto& participant : state.participants) {
            if (!participant.runtime.valid ||
                !participant.runtime.in_run ||
                participant.runtime.run_nonce != packet.run_nonce) {
                continue;
            }
            participant.character_profile.level = packet.level;
            participant.character_profile.experience =
                rounded_experience;
            participant.runtime.level = packet.level;
            participant.runtime.experience_current =
                rounded_experience;
            participant.runtime.experience_next =
                packet.experience_next;
        }
    });
    UpsertPeerEndpoint(
        from,
        packet.authority_participant_id,
        now_ms);
    Log(
        "Multiplayer shared progression applied. authority_participant_id=" +
        std::to_string(packet.authority_participant_id) +
        " killer_participant_id=" +
        std::to_string(packet.killer_participant_id) +
        " run_nonce=" + std::to_string(packet.run_nonce) +
        " revision=" + std::to_string(packet.revision) +
        " level=" + std::to_string(packet.level) +
        " xp=" + std::to_string(packet.experience) +
        " next_xp=" + std::to_string(packet.experience_next));
}

bool TryDispatchSharedProgressionPacket(
    PacketKind kind,
    const void* data,
    int received,
    const TransportPeerEndpoint& from,
    std::uint64_t now_ms) {
    if (kind != PacketKind::SharedProgression ||
        received != static_cast<int>(sizeof(SharedProgressionPacket))) {
        return false;
    }
    SharedProgressionPacket packet{};
    std::memcpy(&packet, data, sizeof(packet));
    if (IsValidHeader(packet.header, PacketKind::SharedProgression)) {
        g_local_transport.packets_received += 1;
        ApplySharedProgressionPacket(packet, from, now_ms);
    }
    return true;
}
