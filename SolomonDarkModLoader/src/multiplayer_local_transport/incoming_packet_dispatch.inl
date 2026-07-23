// Authenticated packet authorization, dispatch, and receive-loop handling.

template <typename Packet, typename OwnerAccessor>
bool SteamPacketOwnerMatches(
    const void* data,
    std::size_t size,
    std::uint64_t sender_steam_id,
    OwnerAccessor owner_accessor) {
    if (size != sizeof(Packet)) {
        return false;
    }
    Packet packet{};
    std::memcpy(&packet, data, sizeof(packet));
    return owner_accessor(packet) == sender_steam_id;
}

bool SteamSpellEffectPacketOwnerMatches(
    const void* data,
    std::size_t size,
    std::uint64_t sender_steam_id) {
    if (data == nullptr ||
        size < kSpellEffectSnapshotPacketPrefixBytes ||
        size > sizeof(SpellEffectSnapshotPacket)) {
        return false;
    }
    SpellEffectSnapshotPacket packet{};
    std::memcpy(&packet, data, size);
    return IsValidHeader(
               packet.header,
               PacketKind::SpellEffectSnapshot) &&
           IsValidSpellEffectSnapshotPacketWireSize(
               size,
               packet.effect_count) &&
           packet.owner_participant_id == sender_steam_id;
}

bool SteamLuaRegisteredSpellEffectPacketOwnerMatches(
    const void* data,
    std::size_t size,
    std::uint64_t sender_steam_id) {
    if (data == nullptr ||
        size < kLuaRegisteredSpellEffectSnapshotPacketPrefixBytes ||
        size > sizeof(LuaRegisteredSpellEffectSnapshotPacket)) {
        return false;
    }
    LuaRegisteredSpellEffectSnapshotPacket packet{};
    std::memcpy(&packet, data, size);
    return IsValidHeader(
               packet.header,
               PacketKind::LuaRegisteredSpellEffectSnapshot) &&
        IsValidLuaRegisteredSpellEffectSnapshotPacketWireSize(
            size,
            packet.effect_count) &&
        packet.owner_participant_id == sender_steam_id;
}

bool SteamLuaNetPacketHopMatches(
    const void* data,
    std::size_t size,
    std::uint64_t sender_steam_id) {
    if (data == nullptr || size < kLuaNetMessagePacketPrefixBytes ||
        size > sizeof(LuaNetMessagePacket)) {
        return false;
    }
    LuaNetMessagePacket packet{};
    std::memcpy(&packet, data, size);
    return IsValidHeader(packet.header, PacketKind::LuaNetMessage) &&
        IsValidLuaNetMessagePacketWireSize(size, packet) &&
        packet.transport_participant_id == sender_steam_id;
}

bool IsAuthorizedSteamGameplayPacket(
    std::uint64_t sender_steam_id,
    const void* data,
    std::size_t size) {
    if (data == nullptr || size < sizeof(PacketHeader)) {
        return false;
    }

    if (!g_local_transport.is_host) {
        return g_local_transport.configured_remote_valid &&
               g_local_transport.configured_remote.backend ==
                   GameplayTransportBackend::Steam &&
               g_local_transport.configured_remote.steam_id == sender_steam_id;
    }

    PacketHeader header{};
    std::memcpy(&header, data, sizeof(header));
    switch (static_cast<PacketKind>(header.kind)) {
    case PacketKind::State:
        return SteamPacketOwnerMatches<StatePacket>(
            data,
            size,
            sender_steam_id,
            [](const StatePacket& packet) {
                return packet.authority_participant_id == 0
                    ? packet.participant_id
                    : std::uint64_t{0};
            });
    case PacketKind::ParticipantFrame:
        return SteamPacketOwnerMatches<ParticipantFramePacket>(
            data,
            size,
            sender_steam_id,
            [](const ParticipantFramePacket& packet) {
                return packet.authority_participant_id == 0
                    ? packet.participant_id
                    : std::uint64_t{0};
            });
    case PacketKind::Cast:
        return SteamPacketOwnerMatches<CastPacket>(
            data,
            size,
            sender_steam_id,
            [](const CastPacket& packet) { return packet.participant_id; });
    case PacketKind::SpellEffectSnapshot:
        return SteamSpellEffectPacketOwnerMatches(
            data,
            size,
            sender_steam_id);
    case PacketKind::LuaRegisteredSpellEffectSnapshot:
        return SteamLuaRegisteredSpellEffectPacketOwnerMatches(
            data,
            size,
            sender_steam_id);
    case PacketKind::AirChainSnapshot:
        return SteamPacketOwnerMatches<AirChainSnapshotPacket>(
            data,
            size,
            sender_steam_id,
            [](const AirChainSnapshotPacket& packet) {
                return packet.owner_participant_id;
            });
    case PacketKind::EnemyDamageClaim:
        return SteamPacketOwnerMatches<EnemyDamageClaimPacket>(
            data,
            size,
            sender_steam_id,
            [](const EnemyDamageClaimPacket& packet) {
                return packet.participant_id;
            });
    case PacketKind::LootPickupRequest:
        return SteamPacketOwnerMatches<LootPickupRequestPacket>(
            data,
            size,
            sender_steam_id,
            [](const LootPickupRequestPacket& packet) {
                return packet.participant_id;
            });
    case PacketKind::LevelUpChoice:
        return SteamPacketOwnerMatches<LevelUpChoicePacket>(
            data,
            size,
            sender_steam_id,
            [](const LevelUpChoicePacket& packet) {
                return packet.participant_id;
            });
    case PacketKind::LuaUiActionRequest:
        return SteamPacketOwnerMatches<LuaUiActionRequestPacket>(
            data,
            size,
            sender_steam_id,
            [](const LuaUiActionRequestPacket& packet) {
                return packet.participant_id;
            });
    case PacketKind::LuaNetMessage:
        return SteamLuaNetPacketHopMatches(
            data,
            size,
            sender_steam_id);
    default:
        return false;
    }
}

void DispatchReceivedPacket(
    const TransportPacketBuffer& packet_buffer,
    int received,
    const TransportPeerEndpoint& from,
    std::uint64_t now_ms) {
    do {
        if (received < static_cast<int>(sizeof(PacketHeader))) {
            continue;
        }

        PacketHeader header{};
        std::memcpy(&header, packet_buffer.data(), sizeof(header));
        if (!IsValidPacketHeader(header)) {
            continue;
        }

        const auto kind = static_cast<PacketKind>(header.kind);
        if (kind == PacketKind::LuaRegisteredSpellEffectSnapshot &&
            received >= static_cast<int>(
                kLuaRegisteredSpellEffectSnapshotPacketPrefixBytes) &&
            received <= static_cast<int>(
                sizeof(LuaRegisteredSpellEffectSnapshotPacket))) {
            LuaRegisteredSpellEffectSnapshotPacket packet{};
            std::memcpy(
                &packet,
                packet_buffer.data(),
                static_cast<std::size_t>(received));
            if (!IsValidHeader(
                    packet.header,
                    PacketKind::LuaRegisteredSpellEffectSnapshot) ||
                !IsValidLuaRegisteredSpellEffectSnapshotPacketWireSize(
                    static_cast<std::size_t>(received),
                    packet.effect_count)) {
                continue;
            }
            g_local_transport.packets_received += 1;
            ApplyLuaRegisteredSpellEffectSnapshotPacket(
                packet,
                from,
                now_ms);
            continue;
        }
        if (kind == PacketKind::LuaRegisteredSpellCast &&
            received ==
                static_cast<int>(sizeof(LuaRegisteredSpellCastPacket))) {
            LuaRegisteredSpellCastPacket packet{};
            std::memcpy(&packet, packet_buffer.data(), sizeof(packet));
            if (!IsValidHeader(
                    packet.header,
                    PacketKind::LuaRegisteredSpellCast)) {
                continue;
            }
            g_local_transport.packets_received += 1;
            ApplyLuaRegisteredSpellCastPacket(packet, from, now_ms);
            continue;
        }
        if (kind == PacketKind::LuaItemGrant &&
            received == static_cast<int>(sizeof(LuaItemGrantPacket))) {
            LuaItemGrantPacket packet{};
            std::memcpy(&packet, packet_buffer.data(), sizeof(packet));
            if (!IsValidHeader(packet.header, PacketKind::LuaItemGrant)) {
                continue;
            }
            g_local_transport.packets_received += 1;
            ApplyLuaItemGrantPacket(packet, from, now_ms);
            continue;
        }

        if (kind == PacketKind::LuaModStream &&
            received >= static_cast<int>(kLuaModStreamPacketPrefixBytes) &&
            received <= static_cast<int>(sizeof(LuaModStreamPacket))) {
            LuaModStreamPacket packet{};
            std::memcpy(
                &packet,
                packet_buffer.data(),
                static_cast<std::size_t>(received));
            if (!IsValidHeader(
                    packet.header,
                    PacketKind::LuaModStream) ||
                !IsValidLuaModStreamPacketWireSize(
                    static_cast<std::size_t>(received),
                    packet)) {
                continue;
            }
            g_local_transport.packets_received += 1;
            ApplyLuaModStreamPacket(packet, from, now_ms);
            continue;
        }

        if (kind == PacketKind::LuaNetMessage &&
            received >= static_cast<int>(kLuaNetMessagePacketPrefixBytes) &&
            received <= static_cast<int>(sizeof(LuaNetMessagePacket))) {
            LuaNetMessagePacket packet{};
            std::memcpy(
                &packet,
                packet_buffer.data(),
                static_cast<std::size_t>(received));
            if (!IsValidHeader(packet.header, PacketKind::LuaNetMessage) ||
                !IsValidLuaNetMessagePacketWireSize(
                    static_cast<std::size_t>(received),
                    packet)) {
                continue;
            }
            g_local_transport.packets_received += 1;
            ApplyLuaNetMessagePacket(packet, from, now_ms);
            continue;
        }

        if (kind == PacketKind::State && received == static_cast<int>(sizeof(StatePacket))) {
            StatePacket packet{};
            std::memcpy(&packet, packet_buffer.data(), sizeof(packet));
            if (!IsValidHeader(packet.header, PacketKind::State)) {
                continue;
            }
            g_local_transport.packets_received += 1;
            ApplyRemoteStatePacket(packet, from, now_ms);
            continue;
        }

        if (kind == PacketKind::ParticipantFrame &&
            received == static_cast<int>(sizeof(ParticipantFramePacket))) {
            ParticipantFramePacket packet{};
            std::memcpy(&packet, packet_buffer.data(), sizeof(packet));
            if (!IsValidHeader(
                    packet.header,
                    PacketKind::ParticipantFrame)) {
                continue;
            }
            g_local_transport.packets_received += 1;
            ApplyRemoteParticipantFramePacket(packet, from, now_ms);
            continue;
        }

        if (kind == PacketKind::Cast && received == static_cast<int>(sizeof(CastPacket))) {
            CastPacket packet{};
            std::memcpy(&packet, packet_buffer.data(), sizeof(packet));
            if (!IsValidHeader(packet.header, PacketKind::Cast)) {
                continue;
            }
            g_local_transport.packets_received += 1;
            ApplyRemoteCastPacket(packet, from, now_ms);
            continue;
        }

        if (kind == PacketKind::SpellEffectSnapshot &&
            received >= static_cast<int>(
                kSpellEffectSnapshotPacketPrefixBytes) &&
            received <= static_cast<int>(sizeof(SpellEffectSnapshotPacket))) {
            SpellEffectSnapshotPacket packet{};
            std::memcpy(
                &packet,
                packet_buffer.data(),
                static_cast<std::size_t>(received));
            if (!IsValidHeader(
                    packet.header,
                    PacketKind::SpellEffectSnapshot) ||
                !IsValidSpellEffectSnapshotPacketWireSize(
                    static_cast<std::size_t>(received),
                    packet.effect_count)) {
                continue;
            }
            g_local_transport.packets_received += 1;
            ApplySpellEffectSnapshotPacket(packet, from, now_ms);
            continue;
        }

        if (kind == PacketKind::AirChainSnapshot &&
            received == static_cast<int>(sizeof(AirChainSnapshotPacket))) {
            AirChainSnapshotPacket packet{};
            std::memcpy(&packet, packet_buffer.data(), sizeof(packet));
            if (!IsValidHeader(packet.header, PacketKind::AirChainSnapshot)) {
                continue;
            }
            g_local_transport.packets_received += 1;
            ApplyAirChainSnapshotPacket(packet, from, now_ms);
            continue;
        }

        if (kind == PacketKind::ParticipantVitalsCorrection &&
            received == static_cast<int>(sizeof(ParticipantVitalsCorrectionPacket))) {
            ParticipantVitalsCorrectionPacket packet{};
            std::memcpy(&packet, packet_buffer.data(), sizeof(packet));
            if (!IsValidHeader(
                    packet.header,
                    PacketKind::ParticipantVitalsCorrection)) {
                continue;
            }
            g_local_transport.packets_received += 1;
            ApplyParticipantVitalsCorrectionPacket(packet, from, now_ms);
            continue;
        }

        if (kind == PacketKind::WorldSnapshot && received == static_cast<int>(sizeof(WorldSnapshotPacket))) {
            WorldSnapshotPacket packet{};
            std::memcpy(&packet, packet_buffer.data(), sizeof(packet));
            if (!IsValidHeader(packet.header, PacketKind::WorldSnapshot)) {
                continue;
            }
            g_local_transport.packets_received += 1;
            ApplyWorldSnapshotPacket(packet, from, now_ms);
            continue;
        }

        if (kind == PacketKind::LootSnapshot &&
            received >= static_cast<int>(kLootSnapshotPacketPrefixBytes) &&
            received <= static_cast<int>(sizeof(LootSnapshotPacket))) {
            LootSnapshotPacket packet{};
            std::memcpy(
                &packet,
                packet_buffer.data(),
                static_cast<std::size_t>(received));
            if (!IsValidHeader(packet.header, PacketKind::LootSnapshot) ||
                !IsValidLootSnapshotPacketWireSize(
                    static_cast<std::size_t>(received),
                    packet.drop_count)) {
                continue;
            }
            g_local_transport.packets_received += 1;
            ApplyLootSnapshotPacket(packet, from, now_ms);
            continue;
        }

        if (kind == PacketKind::EnemyDamageClaim && received == static_cast<int>(sizeof(EnemyDamageClaimPacket))) {
            EnemyDamageClaimPacket packet{};
            std::memcpy(&packet, packet_buffer.data(), sizeof(packet));
            if (!IsValidHeader(packet.header, PacketKind::EnemyDamageClaim)) {
                continue;
            }
            g_local_transport.packets_received += 1;
            ApplyEnemyDamageClaimPacket(packet, from, now_ms);
            continue;
        }

        if (kind == PacketKind::EnemyDamageResult && received == static_cast<int>(sizeof(EnemyDamageResultPacket))) {
            EnemyDamageResultPacket packet{};
            std::memcpy(&packet, packet_buffer.data(), sizeof(packet));
            if (!IsValidHeader(packet.header, PacketKind::EnemyDamageResult)) {
                continue;
            }
            g_local_transport.packets_received += 1;
            ApplyEnemyDamageCorrection(packet);
            continue;
        }

        if (kind == PacketKind::LootPickupRequest && received == static_cast<int>(sizeof(LootPickupRequestPacket))) {
            LootPickupRequestPacket packet{};
            std::memcpy(&packet, packet_buffer.data(), sizeof(packet));
            if (!IsValidHeader(packet.header, PacketKind::LootPickupRequest)) {
                continue;
            }
            g_local_transport.packets_received += 1;
            ApplyLootPickupRequestPacket(packet, from, now_ms);
            continue;
        }

        if (kind == PacketKind::LootPickupResult && received == static_cast<int>(sizeof(LootPickupResultPacket))) {
            LootPickupResultPacket packet{};
            std::memcpy(&packet, packet_buffer.data(), sizeof(packet));
            if (!IsValidHeader(packet.header, PacketKind::LootPickupResult)) {
                continue;
            }
            g_local_transport.packets_received += 1;
            ApplyLootPickupResultPacket(packet, from, now_ms);
            continue;
        }

        if (kind == PacketKind::LevelUpOffer && received == static_cast<int>(sizeof(LevelUpOfferPacket))) {
            LevelUpOfferPacket packet{};
            std::memcpy(&packet, packet_buffer.data(), sizeof(packet));
            if (!IsValidHeader(packet.header, PacketKind::LevelUpOffer)) {
                continue;
            }
            g_local_transport.packets_received += 1;
            ApplyLevelUpOfferPacket(packet, from, now_ms);
            continue;
        }

        if (kind == PacketKind::LevelUpChoice && received == static_cast<int>(sizeof(LevelUpChoicePacket))) {
            LevelUpChoicePacket packet{};
            std::memcpy(&packet, packet_buffer.data(), sizeof(packet));
            if (!IsValidHeader(packet.header, PacketKind::LevelUpChoice)) {
                continue;
            }
            g_local_transport.packets_received += 1;
            ApplyLevelUpChoicePacket(packet, from, now_ms);
            continue;
        }

        if (kind == PacketKind::LevelUpChoiceResult &&
            received == static_cast<int>(sizeof(LevelUpChoiceResultPacket))) {
            LevelUpChoiceResultPacket packet{};
            std::memcpy(&packet, packet_buffer.data(), sizeof(packet));
            if (!IsValidHeader(packet.header, PacketKind::LevelUpChoiceResult)) {
                continue;
            }
            g_local_transport.packets_received += 1;
            ApplyLevelUpChoiceResultPacket(packet, from, now_ms);
            continue;
        }

        if (kind == PacketKind::LuaUiActionRequest &&
            received == static_cast<int>(sizeof(LuaUiActionRequestPacket))) {
            LuaUiActionRequestPacket packet{};
            std::memcpy(&packet, packet_buffer.data(), sizeof(packet));
            if (!IsValidHeader(packet.header, PacketKind::LuaUiActionRequest)) {
                continue;
            }
            g_local_transport.packets_received += 1;
            ApplyLuaUiActionRequestPacket(packet, from, now_ms);
            continue;
        }

        if (kind == PacketKind::LevelUpBarrier &&
            received == static_cast<int>(sizeof(LevelUpBarrierPacket))) {
            LevelUpBarrierPacket packet{};
            std::memcpy(&packet, packet_buffer.data(), sizeof(packet));
            if (!IsValidHeader(packet.header, PacketKind::LevelUpBarrier)) {
                continue;
            }
            g_local_transport.packets_received += 1;
            ApplyLevelUpBarrierPacket(packet, from, now_ms);
        }
    } while (false);
}

void ReceivePackets(std::uint64_t now_ms) {
    if (g_local_transport.backend != GameplayTransportBackend::LocalUdp) {
        return;
    }
    for (int packet_index = 0; packet_index < kMaxPacketsPerTick; ++packet_index) {
        TransportPacketBuffer packet_buffer{};
        sockaddr_in udp_from{};
        int from_length = sizeof(udp_from);
        const int received = recvfrom(
            g_local_transport.socket_handle,
            packet_buffer.data(),
            static_cast<int>(packet_buffer.size()),
            0,
            reinterpret_cast<sockaddr*>(&udp_from),
            &from_length);
        if (received == SOCKET_ERROR) {
            return;
        }
        TransportPeerEndpoint from;
        from.backend = GameplayTransportBackend::LocalUdp;
        from.udp_address = udp_from;
        DispatchReceivedPacket(packet_buffer, received, from, now_ms);
    }
}
