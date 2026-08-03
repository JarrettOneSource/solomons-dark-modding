bool DispatchHostModTransferPacket(
    PacketKind kind,
    const TransportPacketBuffer& packet_buffer,
    int received,
    const TransportPeerEndpoint& from) {
    if (kind < PacketKind::ModTransferManifestRequest ||
        kind > PacketKind::ModTransferAbort) {
        return false;
    }

    std::uint64_t lobby_id = 0;
    if (!g_local_transport.is_host ||
        g_local_transport.backend != GameplayTransportBackend::LocalUdp ||
        !g_local_transport.configured_remote_valid ||
        !SameEndpoint(from, g_local_transport.configured_remote) ||
        received < 20) {
        return true;
    }
    std::memcpy(
        &lobby_id,
        packet_buffer.data() + sizeof(PacketHeader),
        sizeof(lobby_id));
    if (lobby_id != 0) {
        return true;
    }

    HostModTransferRoute route;
    route.backend = HostModTransferBackend::LocalUdp;
    route.ipv4_address = ntohl(from.udp_address.sin_addr.s_addr);
    route.port = ntohs(from.udp_address.sin_port);
    if (SubmitHostModTransferPacket(
            route,
            packet_buffer.data(),
            static_cast<std::size_t>(received))) {
        g_local_transport.packets_received += 1;
    }
    return true;
}
