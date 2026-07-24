constexpr std::int32_t kMaximumReplicatedWaveCount = 4096;
static_assert(
    kWaveSummaryMaxCompositionRows == kWaveCompositionMaxRows,
    "wave summary packet and semantic row limits must match");

bool BuildAuthorityWaveSummaryPacket(WaveSummaryPacket* packet) {
    if (packet == nullptr || !g_local_transport.is_host) {
        return false;
    }

    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);
    if (local == nullptr) {
        return false;
    }

    const auto summary = SnapshotWaveSummary();
    if (!summary.valid) {
        return false;
    }

    WaveSummaryPacket built{};
    built.authority_participant_id =
        g_local_transport.local_peer_id;
    built.authority_session_nonce =
        g_local_transport.local_session_nonce;
    built.run_nonce = local->runtime.run_nonce;
    built.valid = 1;
    built.phase = static_cast<std::uint8_t>(summary.phase);
    built.wave = summary.wave;
    built.remaining_to_spawn = summary.remaining_to_spawn;
    built.spawned = summary.spawned;
    built.alive = summary.alive;
    built.killed = summary.killed;
    const auto row_count = (std::min<std::size_t>)(
        summary.composition.size(),
        kWaveSummaryMaxCompositionRows);
    built.row_count = static_cast<std::uint16_t>(row_count);
    for (std::size_t index = 0; index < row_count; ++index) {
        const auto& source = summary.composition[index];
        auto& destination = built.rows[index];
        destination.enemy_type = source.enemy_type;
        destination.planned = static_cast<std::uint16_t>(source.planned);
        destination.spawned = static_cast<std::uint16_t>(source.spawned);
        destination.alive = static_cast<std::uint16_t>(source.alive);
        destination.killed = static_cast<std::uint16_t>(source.killed);
    }
    *packet = built;
    return true;
}

bool WaveSummaryPayloadMatches(
    const WaveSummaryPacket& left,
    const WaveSummaryPacket& right) {
    return std::memcmp(
               reinterpret_cast<const char*>(&left) +
                   sizeof(PacketHeader),
               reinterpret_cast<const char*>(&right) +
                   sizeof(PacketHeader),
               sizeof(WaveSummaryPacket) -
                   sizeof(PacketHeader)) == 0;
}

void SendLocalWaveSummary(std::uint64_t now_ms) {
    WaveSummaryPacket packet{};
    if (!BuildAuthorityWaveSummaryPacket(&packet)) {
        return;
    }

    const bool changed =
        !g_local_transport.have_last_sent_wave_summary ||
        !WaveSummaryPayloadMatches(
            packet,
            g_local_transport.last_sent_wave_summary);
    const bool checkpoint_due =
        g_local_transport.last_wave_summary_send_ms == 0 ||
        now_ms < g_local_transport.last_wave_summary_send_ms ||
        now_ms - g_local_transport.last_wave_summary_send_ms >=
            kLocalTransportWaveSummaryCheckpointIntervalMs;
    if (!changed && !checkpoint_due) {
        return;
    }

    packet.header = MakePacketHeader(
        PacketKind::WaveSummary,
        g_local_transport.next_sequence++);
    const auto endpoints = BuildKnownSendEndpoints();
    for (const auto& endpoint : endpoints) {
        SendPacketToEndpoint(packet, endpoint);
    }
    g_local_transport.last_wave_summary_send_ms = now_ms;
    g_local_transport.last_sent_wave_summary = packet;
    g_local_transport.have_last_sent_wave_summary = true;
}

void ApplyAuthorityWaveSummaryPacket(
    const WaveSummaryPacket& packet,
    const TransportPeerEndpoint& from,
    std::uint64_t now_ms) {
    if (!IsLocalTransportClient() ||
        !IsConfiguredRemoteAuthorityEndpoint(from) ||
        packet.authority_participant_id == 0 ||
        packet.authority_session_nonce == 0 ||
        packet.valid != 1 ||
        packet.phase >
            static_cast<std::uint8_t>(WavePhase::Completed) ||
        packet.row_count > kWaveSummaryMaxCompositionRows ||
        packet.wave < 0 ||
        packet.wave > kMaximumReplicatedWaveCount ||
        packet.remaining_to_spawn < 0 ||
        packet.remaining_to_spawn > kMaximumReplicatedWaveCount ||
        packet.spawned < 0 ||
        packet.spawned > kMaximumReplicatedWaveCount ||
        packet.alive < 0 ||
        packet.alive > kMaximumReplicatedWaveCount ||
        packet.killed < 0 ||
        packet.killed > kMaximumReplicatedWaveCount) {
        return;
    }

    const auto session =
        g_local_transport.session_nonce_by_participant.find(
            packet.authority_participant_id);
    if (session ==
            g_local_transport.session_nonce_by_participant.end() ||
        session->second != packet.authority_session_nonce) {
        return;
    }
    const auto previous_sequence =
        g_local_transport
            .last_wave_summary_sequence_by_authority.find(
                packet.authority_participant_id);
    if (previous_sequence !=
            g_local_transport
                .last_wave_summary_sequence_by_authority.end() &&
        !IsPacketSequenceNewer(
            packet.header.sequence,
            previous_sequence->second)) {
        return;
    }
    g_local_transport.last_wave_summary_sequence_by_authority[
        packet.authority_participant_id] =
        packet.header.sequence;

    WaveSummary summary;
    summary.valid = true;
    summary.wave = packet.wave;
    summary.phase = static_cast<WavePhase>(packet.phase);
    summary.remaining_to_spawn = packet.remaining_to_spawn;
    summary.spawned = packet.spawned;
    summary.alive = packet.alive;
    summary.killed = packet.killed;
    summary.composition.reserve(packet.row_count);
    std::int32_t rows_spawned = 0;
    std::int32_t rows_alive = 0;
    std::int32_t rows_killed = 0;
    std::int32_t previous_enemy_type = -1;
    for (std::size_t index = 0;
         index < packet.row_count;
         ++index) {
        const auto& source = packet.rows[index];
        if (source.enemy_type < 0 ||
            source.enemy_type <= previous_enemy_type ||
            source.alive > source.spawned ||
            source.killed > source.spawned ||
            static_cast<std::uint32_t>(source.alive) + source.killed !=
                source.spawned) {
            return;
        }
        previous_enemy_type = source.enemy_type;
        WaveCompositionRow row;
        row.enemy_type = source.enemy_type;
        row.planned = source.planned;
        row.spawned = source.spawned;
        row.alive = source.alive;
        row.killed = source.killed;
        rows_spawned += row.spawned;
        rows_alive += row.alive;
        rows_killed += row.killed;
        summary.composition.push_back(row);
    }
    const bool idle_consistent = summary.wave == 0
        ? summary.phase == WavePhase::Idle &&
            summary.remaining_to_spawn == 0 &&
            summary.spawned == 0 &&
            summary.alive == 0 &&
            summary.killed == 0 &&
            summary.composition.empty()
        : summary.phase != WavePhase::Idle;
    const bool phase_consistent =
        (summary.phase == WavePhase::Idle) ||
        (summary.phase == WavePhase::Spawning &&
         summary.remaining_to_spawn > 0) ||
        (summary.phase == WavePhase::Clearing &&
         summary.remaining_to_spawn == 0 && summary.alive > 0) ||
        (summary.phase == WavePhase::Completed &&
         summary.remaining_to_spawn == 0 && summary.alive == 0);
    if (!idle_consistent || !phase_consistent ||
        rows_spawned != summary.spawned ||
        rows_alive != summary.alive ||
        rows_killed != summary.killed) {
        return;
    }

    UpsertPeerEndpoint(
        from,
        packet.authority_participant_id,
        now_ms);
    const auto wave_update = ApplyReplicatedWaveSummary(summary);
    if (wave_update.started_wave != 0) {
        DispatchLuaWaveStarted(wave_update.summary);
    }
    if (wave_update.completed_wave != 0) {
        DispatchLuaWaveCompleted(wave_update.completed_wave);
    }
}
