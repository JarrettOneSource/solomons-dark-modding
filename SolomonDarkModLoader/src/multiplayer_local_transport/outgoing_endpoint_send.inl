SteamNetworkSendMode SteamSendModeForPacket(const CastPacket& packet) {
    return packet.input_phase == static_cast<std::uint8_t>(CastInputPhase::Held)
        ? SteamNetworkSendMode::UnreliableNoDelay
        : SteamNetworkSendMode::ReliableNoNagle;
}

template <typename Packet>
SteamNetworkSendMode SteamSendModeForPacket(const Packet& packet) {
    const auto kind = static_cast<PacketKind>(packet.header.kind);
    switch (kind) {
    case PacketKind::WorldSnapshot:
        // Ordinary generations are disposable visual updates. Never queue
        // them behind newer generations; periodic reliable generations own
        // structural convergence.
    case PacketKind::WorldMotionSnapshot:
    case PacketKind::ParticipantFrame:
    case PacketKind::WaveSummary:
    case PacketKind::LootSnapshot:
    case PacketKind::SpellEffectSnapshot:
    case PacketKind::AirChainSnapshot:
    case PacketKind::LuaRegisteredSpellEffectSnapshot:
        return SteamNetworkSendMode::UnreliableNoDelay;
    default:
        return SteamNetworkSendMode::ReliableNoNagle;
    }
}

void SendBufferToEndpoint(
    const void* packet,
    std::size_t packet_size,
    const TransportPeerEndpoint& endpoint,
    SteamNetworkSendMode steam_send_mode) {
    if (packet == nullptr || packet_size == 0 || packet_size > static_cast<std::size_t>((std::numeric_limits<int>::max)())) {
        return;
    }
    const bool telemetry_enabled =
        IsNetworkTelemetryEnabled();
    PacketHeader header{};
    if (telemetry_enabled &&
        packet_size >= sizeof(header)) {
        std::memcpy(&header, packet, sizeof(header));
    }
    const auto started_us = telemetry_enabled
        ? NetworkTelemetryNowMicroseconds()
        : 0;
    if (endpoint.backend == GameplayTransportBackend::Steam) {
        const bool queued = QueueSteamGameplayPacketSend(
            endpoint.steam_id,
            packet,
            packet_size,
            steam_send_mode);
        RecordNetworkPacketSend(
            "steam",
            header.kind,
            header.sequence,
            packet_size,
            packet_size,
            1,
            packet_size,
            endpoint.steam_id,
            0,
            queued ? 1 : 0,
            0,
            telemetry_enabled
                ? NetworkTelemetryNowMicroseconds() -
                    started_us
                : 0);
        if (queued) {
            return;
        }
        const auto queue_stats = SnapshotSteamGameplayQueueStats();
        g_local_transport.steam_send_failures = queue_stats.send_failures;
        g_local_transport.steam_reliable_send_failures =
            queue_stats.reliable_send_failures;
        g_local_transport.last_steam_send_failure_result =
            queue_stats.last_send_failure_result;
        return;
    }
    int result = SOCKET_ERROR;
    int error_code = 0;
    std::size_t wire_bytes = 0;
    std::size_t datagram_count = 0;
    std::size_t largest_datagram_bytes = 0;
    if (packet_size <= kLocalUdpMaximumDatagramBytes) {
        const int sent = sendto(
            g_local_transport.socket_handle,
            reinterpret_cast<const char*>(packet),
            static_cast<int>(packet_size),
            0,
            reinterpret_cast<const sockaddr*>(
                &endpoint.udp_address),
            sizeof(endpoint.udp_address));
        error_code =
            sent == SOCKET_ERROR ? WSAGetLastError() : 0;
        result = sent;
        wire_bytes = packet_size;
        datagram_count = 1;
        largest_datagram_bytes = packet_size;
    } else {
        std::vector<std::vector<std::uint8_t>> datagrams;
        if (!BuildLocalUdpFragmentDatagrams(
                packet,
                packet_size,
                &datagrams)) {
            error_code = WSAEMSGSIZE;
        } else {
            bool sent_all = true;
            for (const auto& datagram : datagrams) {
                wire_bytes += datagram.size();
                ++datagram_count;
                largest_datagram_bytes =
                    (std::max)(
                        largest_datagram_bytes,
                        datagram.size());
                const int sent = sendto(
                    g_local_transport.socket_handle,
                    reinterpret_cast<const char*>(
                        datagram.data()),
                    static_cast<int>(datagram.size()),
                    0,
                    reinterpret_cast<const sockaddr*>(
                        &endpoint.udp_address),
                    sizeof(endpoint.udp_address));
                if (sent !=
                    static_cast<int>(datagram.size())) {
                    sent_all = false;
                    error_code = sent == SOCKET_ERROR
                        ? WSAGetLastError()
                        : WSAEMSGSIZE;
                    break;
                }
            }
            if (sent_all) {
                result = static_cast<int>(packet_size);
            }
        }
    }
    RecordNetworkPacketSend(
        "local_udp",
        header.kind,
        header.sequence,
        packet_size,
        wire_bytes,
        datagram_count,
        largest_datagram_bytes,
        ntohl(endpoint.udp_address.sin_addr.s_addr),
        ntohs(endpoint.udp_address.sin_port),
        result,
        error_code,
        telemetry_enabled
            ? NetworkTelemetryNowMicroseconds() -
                started_us
            : 0);
    if (result == static_cast<int>(packet_size)) {
        g_local_transport.packets_sent += 1;
    }
}

template <typename Packet>
void SendPacketToEndpoint(const Packet& packet, const TransportPeerEndpoint& endpoint) {
    SendBufferToEndpoint(
        &packet,
        sizeof(packet),
        endpoint,
        SteamSendModeForPacket(packet));
}

template <typename Packet>
void SendPacketToEndpoint(
    const Packet& packet,
    const TransportPeerEndpoint& endpoint,
    SteamNetworkSendMode steam_send_mode) {
    SendBufferToEndpoint(
        &packet,
        sizeof(packet),
        endpoint,
        steam_send_mode);
}

void DrainLocalHostModTransferResponses() {
    auto responses = TakeHostModTransferResponses(
        HostModTransferBackend::LocalUdp,
        8,
        8);
    for (const auto& response : responses) {
        TransportPeerEndpoint endpoint;
        endpoint.backend = GameplayTransportBackend::LocalUdp;
        endpoint.udp_address.sin_family = AF_INET;
        endpoint.udp_address.sin_addr.s_addr =
            htonl(response.route.ipv4_address);
        endpoint.udp_address.sin_port = htons(response.route.port);
        SendBufferToEndpoint(
            response.bytes.data(),
            response.bytes.size(),
            endpoint,
            SteamNetworkSendMode::ReliableNoNagle);
    }
}
