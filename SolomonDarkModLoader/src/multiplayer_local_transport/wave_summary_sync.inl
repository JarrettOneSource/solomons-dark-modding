constexpr std::int32_t kMaximumReplicatedWaveCount = 4096;
static_assert(
    kWaveSummaryMaxCompositionRows == kWaveCompositionMaxRows,
    "wave summary packet and semantic row limits must match");

void PopulateAuthorityWaveSummary(ParticipantFramePacket* packet) {
    if (packet == nullptr || !g_local_transport.is_host) {
        return;
    }
    const auto summary = SnapshotWaveSummary();
    if (!summary.valid) {
        return;
    }
    packet->wave_summary_valid = 1;
    packet->wave_summary_phase = static_cast<std::uint8_t>(summary.phase);
    packet->wave_summary_wave = summary.wave;
    packet->wave_summary_remaining_to_spawn = summary.remaining_to_spawn;
    packet->wave_summary_spawned = summary.spawned;
    packet->wave_summary_alive = summary.alive;
    packet->wave_summary_killed = summary.killed;
    const auto row_count = (std::min<std::size_t>)(
        summary.composition.size(),
        kWaveSummaryMaxCompositionRows);
    packet->wave_summary_row_count = static_cast<std::uint16_t>(row_count);
    for (std::size_t index = 0; index < row_count; ++index) {
        const auto& source = summary.composition[index];
        auto& destination = packet->wave_summary_rows[index];
        destination.enemy_type = source.enemy_type;
        destination.planned = static_cast<std::uint16_t>(source.planned);
        destination.spawned = static_cast<std::uint16_t>(source.spawned);
        destination.alive = static_cast<std::uint16_t>(source.alive);
        destination.killed = static_cast<std::uint16_t>(source.killed);
    }
}

void ApplyAuthorityWaveSummaryFromPacket(
    const ParticipantFramePacket& packet,
    bool packet_from_configured_authority) {
    if (!packet_from_configured_authority ||
        packet.wave_summary_valid != 1 ||
        packet.wave_summary_phase >
            static_cast<std::uint8_t>(WavePhase::Completed) ||
        packet.wave_summary_row_count > kWaveSummaryMaxCompositionRows ||
        packet.wave_summary_wave < 0 ||
        packet.wave_summary_wave > kMaximumReplicatedWaveCount ||
        packet.wave_summary_remaining_to_spawn < 0 ||
        packet.wave_summary_remaining_to_spawn > kMaximumReplicatedWaveCount ||
        packet.wave_summary_spawned < 0 ||
        packet.wave_summary_spawned > kMaximumReplicatedWaveCount ||
        packet.wave_summary_alive < 0 ||
        packet.wave_summary_alive > kMaximumReplicatedWaveCount ||
        packet.wave_summary_killed < 0 ||
        packet.wave_summary_killed > kMaximumReplicatedWaveCount) {
        return;
    }

    WaveSummary summary;
    summary.valid = true;
    summary.wave = packet.wave_summary_wave;
    summary.phase = static_cast<WavePhase>(packet.wave_summary_phase);
    summary.remaining_to_spawn = packet.wave_summary_remaining_to_spawn;
    summary.spawned = packet.wave_summary_spawned;
    summary.alive = packet.wave_summary_alive;
    summary.killed = packet.wave_summary_killed;
    summary.composition.reserve(packet.wave_summary_row_count);
    std::int32_t rows_spawned = 0;
    std::int32_t rows_alive = 0;
    std::int32_t rows_killed = 0;
    std::int32_t previous_enemy_type = -1;
    for (std::size_t index = 0;
         index < packet.wave_summary_row_count;
         ++index) {
        const auto& source = packet.wave_summary_rows[index];
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

    const auto wave_update = ApplyReplicatedWaveSummary(summary);
    if (wave_update.started_wave != 0) {
        DispatchLuaWaveStarted(wave_update.summary);
    }
    if (wave_update.completed_wave != 0) {
        DispatchLuaWaveCompleted(wave_update.completed_wave);
    }
}
