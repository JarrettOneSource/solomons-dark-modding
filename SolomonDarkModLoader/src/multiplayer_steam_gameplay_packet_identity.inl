SteamGameplayOutboundQueuePolicy::PacketIdentity
SteamGameplayOutboundQueuePolicy::DescribePacket(
    const void* data,
    std::size_t size,
    SteamNetworkSendMode mode) {
    PacketIdentity identity;
    PacketHeader header{};
    if (!ReadPacketValue(data, size, 0, &header) ||
        !IsValidPacketHeader(header)) {
        return identity;
    }
    identity.kind = header.kind;
    identity.packet_sequence = header.sequence;
    const auto kind = static_cast<PacketKind>(header.kind);
    const bool reliable = IsReliable(mode);

    switch (kind) {
    case PacketKind::State:
        identity.retention = Retention::LatestStream;
        if (!ReadPacketValue(
                data,
                size,
                offsetof(StatePacket, participant_id),
                &identity.stream_id)) {
            return PacketIdentity{};
        }
        return identity;
    case PacketKind::ParticipantFrame:
        identity.retention = Retention::LatestStream;
        if (!ReadPacketValue(
                data,
                size,
                offsetof(
                    ParticipantFramePacket,
                    participant_id),
                &identity.stream_id)) {
            return PacketIdentity{};
        }
        return identity;
    case PacketKind::ParticipantInventorySnapshot:
        identity.retention = Retention::LatestStream;
        if (!ReadPacketValue(
                data,
                size,
                offsetof(
                    ParticipantInventorySnapshotPacket,
                    participant_id),
                &identity.stream_id)) {
            return PacketIdentity{};
        }
        return identity;
    case PacketKind::ParticipantProgressionBookSnapshot:
        identity.retention = Retention::LatestStream;
        if (!ReadPacketValue(
                data,
                size,
                offsetof(
                    ParticipantProgressionBookSnapshotPacket,
                    participant_id),
                &identity.stream_id)) {
            return PacketIdentity{};
        }
        return identity;
    case PacketKind::LevelUpBarrier:
        identity.retention = Retention::LatestStream;
        if (!ReadPacketValue(
                data,
                size,
                offsetof(
                    LevelUpBarrierPacket,
                    authority_participant_id),
                &identity.stream_id)) {
            return PacketIdentity{};
        }
        return identity;
    case PacketKind::WaveSummary:
        identity.retention = Retention::LatestStream;
        if (!ReadPacketValue(
                data,
                size,
                offsetof(
                    WaveSummaryPacket,
                    authority_participant_id),
                &identity.stream_id)) {
            return PacketIdentity{};
        }
        return identity;
    case PacketKind::LootSnapshot:
        identity.retention = Retention::LatestStream;
        if (!ReadPacketValue(
                data,
                size,
                offsetof(
                    LootSnapshotPacket,
                    authority_participant_id),
                &identity.stream_id)) {
            return PacketIdentity{};
        }
        return identity;
    case PacketKind::SpellEffectSnapshot:
        identity.retention = Retention::LatestStream;
        if (!ReadPacketValue(
                data,
                size,
                offsetof(
                    SpellEffectSnapshotPacket,
                    owner_participant_id),
                &identity.stream_id)) {
            return PacketIdentity{};
        }
        return identity;
    case PacketKind::Cast: {
        if (reliable) {
            return identity;
        }
        std::uint8_t cast_kind = 0;
        std::int8_t secondary_slot = 0;
        identity.retention = Retention::LatestStream;
        if (!ReadPacketValue(
                data,
                size,
                offsetof(CastPacket, participant_id),
                &identity.stream_id) ||
            !ReadPacketValue(
                data,
                size,
                offsetof(CastPacket, cast_kind),
                &cast_kind) ||
            !ReadPacketValue(
                data,
                size,
                offsetof(CastPacket, secondary_slot),
                &secondary_slot)) {
            return PacketIdentity{};
        }
        identity.logical_a = PackedPair(
            cast_kind,
            static_cast<std::uint8_t>(secondary_slot));
        return identity;
    }
    case PacketKind::AirChainSnapshot: {
        std::uint32_t run_nonce = 0;
        std::uint32_t cast_sequence = 0;
        identity.retention = Retention::LatestStream;
        if (!ReadPacketValue(
                data,
                size,
                offsetof(
                    AirChainSnapshotPacket,
                    owner_participant_id),
                &identity.stream_id) ||
            !ReadPacketValue(
                data,
                size,
                offsetof(AirChainSnapshotPacket, run_nonce),
                &run_nonce) ||
            !ReadPacketValue(
                data,
                size,
                offsetof(
                    AirChainSnapshotPacket,
                    cast_sequence),
                &cast_sequence)) {
            return PacketIdentity{};
        }
        identity.logical_a =
            PackedPair(run_nonce, cast_sequence);
        return identity;
    }
    case PacketKind::LuaTimeControl: {
        std::uint32_t flags = 0;
        if (!ReadPacketValue(
                data,
                size,
                offsetof(LuaTimeControlPacket, flags),
                &flags)) {
            return PacketIdentity{};
        }
        if ((flags &
             LuaTimeControlPacketFlagStepFrames) != 0) {
            return identity;
        }
        identity.retention = Retention::LatestStream;
        if (!ReadPacketValue(
                data,
                size,
                offsetof(
                    LuaTimeControlPacket,
                    authority_participant_id),
                &identity.stream_id)) {
            return PacketIdentity{};
        }
        return identity;
    }
    case PacketKind::WorldSnapshot: {
        identity.retention = Retention::LatestGeneration;
        std::uint32_t scene_epoch = 0;
        std::uint32_t run_nonce = 0;
        std::uint32_t snapshot_id = 0;
        std::uint16_t fragment_index = 0;
        std::uint16_t fragment_count = 0;
        if (!ReadPacketValue(
                data,
                size,
                offsetof(
                    WorldSnapshotPacket,
                    authority_participant_id),
                &identity.stream_id) ||
            !ReadPacketValue(
                data,
                size,
                offsetof(WorldSnapshotPacket, scene_epoch),
                &scene_epoch) ||
            !ReadPacketValue(
                data,
                size,
                offsetof(WorldSnapshotPacket, run_nonce),
                &run_nonce) ||
            !ReadPacketValue(
                data,
                size,
                offsetof(WorldSnapshotPacket, snapshot_id),
                &snapshot_id) ||
            !ReadPacketValue(
                data,
                size,
                offsetof(
                    WorldSnapshotPacket,
                    fragment_index),
                &fragment_index) ||
            !ReadPacketValue(
                data,
                size,
                offsetof(
                    WorldSnapshotPacket,
                    fragment_count),
                &fragment_count) ||
            snapshot_id == 0 ||
            fragment_count == 0 ||
            fragment_index >= fragment_count) {
            return PacketIdentity{};
        }
        identity.logical_a = PackedPair(scene_epoch, run_nonce);
        identity.logical_b = snapshot_id;
        identity.fragment_index = fragment_index;
        identity.fragment_count = fragment_count;
        return identity;
    }
    case PacketKind::WorldMotionSnapshot: {
        identity.retention = Retention::LatestGeneration;
        std::uint32_t scene_epoch = 0;
        std::uint32_t run_nonce = 0;
        std::uint32_t snapshot_id = 0;
        std::uint16_t fragment_index = 0;
        std::uint16_t fragment_count = 0;
        if (!ReadPacketValue(
                data,
                size,
                offsetof(
                    WorldMotionSnapshotPacket,
                    authority_participant_id),
                &identity.stream_id) ||
            !ReadPacketValue(
                data,
                size,
                offsetof(
                    WorldMotionSnapshotPacket,
                    scene_epoch),
                &scene_epoch) ||
            !ReadPacketValue(
                data,
                size,
                offsetof(
                    WorldMotionSnapshotPacket,
                    run_nonce),
                &run_nonce) ||
            !ReadPacketValue(
                data,
                size,
                offsetof(
                    WorldMotionSnapshotPacket,
                    snapshot_id),
                &snapshot_id) ||
            !ReadPacketValue(
                data,
                size,
                offsetof(
                    WorldMotionSnapshotPacket,
                    fragment_index),
                &fragment_index) ||
            !ReadPacketValue(
                data,
                size,
                offsetof(
                    WorldMotionSnapshotPacket,
                    fragment_count),
                &fragment_count) ||
            snapshot_id == 0 ||
            fragment_count == 0 ||
            fragment_index >= fragment_count) {
            return PacketIdentity{};
        }
        identity.logical_a = PackedPair(scene_epoch, run_nonce);
        identity.logical_b = snapshot_id;
        identity.fragment_index = fragment_index;
        identity.fragment_count = fragment_count;
        return identity;
    }
    case PacketKind::LuaRegisteredSpellEffectSnapshot: {
        identity.retention = Retention::LatestGeneration;
        std::uint32_t generation = 0;
        std::uint32_t run_nonce = 0;
        std::uint32_t scene_epoch = 0;
        std::uint16_t fragment_index = 0;
        std::uint16_t fragment_count = 0;
        if (!ReadPacketValue(
                data,
                size,
                offsetof(
                    LuaRegisteredSpellEffectSnapshotPacket,
                    owner_participant_id),
                &identity.stream_id) ||
            !ReadPacketValue(
                data,
                size,
                offsetof(
                    LuaRegisteredSpellEffectSnapshotPacket,
                    generation),
                &generation) ||
            !ReadPacketValue(
                data,
                size,
                offsetof(
                    LuaRegisteredSpellEffectSnapshotPacket,
                    run_nonce),
                &run_nonce) ||
            !ReadPacketValue(
                data,
                size,
                offsetof(
                    LuaRegisteredSpellEffectSnapshotPacket,
                    scene_epoch),
                &scene_epoch) ||
            !ReadPacketValue(
                data,
                size,
                offsetof(
                    LuaRegisteredSpellEffectSnapshotPacket,
                    fragment_index),
                &fragment_index) ||
            !ReadPacketValue(
                data,
                size,
                offsetof(
                    LuaRegisteredSpellEffectSnapshotPacket,
                    fragment_count),
                &fragment_count) ||
            generation == 0 ||
            fragment_count == 0 ||
            fragment_index >= fragment_count) {
            return PacketIdentity{};
        }
        identity.logical_a = PackedPair(scene_epoch, run_nonce);
        identity.logical_b = generation;
        identity.fragment_index = fragment_index;
        identity.fragment_count = fragment_count;
        return identity;
    }
    case PacketKind::ParticipantVitalsCorrection: {
        identity.retention = Retention::DistinctLogicalEvent;
        std::uint32_t correction_sequence = 0;
        std::uint32_t run_nonce = 0;
        if (!ReadPacketValue(
                data,
                size,
                offsetof(
                    ParticipantVitalsCorrectionPacket,
                    target_participant_id),
                &identity.stream_id) ||
            !ReadPacketValue(
                data,
                size,
                offsetof(
                    ParticipantVitalsCorrectionPacket,
                    correction_sequence),
                &correction_sequence) ||
            !ReadPacketValue(
                data,
                size,
                offsetof(
                    ParticipantVitalsCorrectionPacket,
                    run_nonce),
                &run_nonce) ||
            correction_sequence == 0) {
            return PacketIdentity{};
        }
        identity.logical_a = run_nonce;
        identity.logical_b = correction_sequence;
        return identity;
    }
    case PacketKind::ParticipantHitFeedback: {
        identity.retention = Retention::DistinctLogicalEvent;
        std::uint32_t event_sequence = 0;
        std::uint32_t run_nonce = 0;
        if (!ReadPacketValue(
                data,
                size,
                offsetof(
                    ParticipantHitFeedbackPacket,
                    target_participant_id),
                &identity.stream_id) ||
            !ReadPacketValue(
                data,
                size,
                offsetof(
                    ParticipantHitFeedbackPacket,
                    event_sequence),
                &event_sequence) ||
            !ReadPacketValue(
                data,
                size,
                offsetof(
                    ParticipantHitFeedbackPacket,
                    run_nonce),
                &run_nonce) ||
            event_sequence == 0) {
            return PacketIdentity{};
        }
        identity.logical_a = run_nonce;
        identity.logical_b = event_sequence;
        return identity;
    }
    default:
        return identity;
    }
}
