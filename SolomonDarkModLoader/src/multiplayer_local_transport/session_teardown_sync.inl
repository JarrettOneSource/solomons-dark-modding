constexpr std::uint64_t kLocalTeardownSendIntervalMs = 50;
constexpr std::uint32_t kLocalTeardownSendCount = 3;

const LocalPeerEndpoint* FindLocalPeer(
    const TransportPeerEndpoint& endpoint,
    std::uint64_t participant_id) {
    const auto found = std::find_if(
        g_local_transport.peers.begin(),
        g_local_transport.peers.end(),
        [&](const LocalPeerEndpoint& peer) {
            return SameEndpoint(peer.endpoint, endpoint) &&
                peer.participant_id == participant_id;
        });
    return found == g_local_transport.peers.end()
        ? nullptr
        : &*found;
}

void SendLocalSessionGoodbye(SessionGoodbyeReason reason) {
    if (!g_local_transport.initialized ||
        g_local_transport.backend != GameplayTransportBackend::LocalUdp ||
        g_local_transport.local_peer_id == 0) {
        return;
    }

    SessionGoodbyePacket packet{};
    packet.header = MakePacketHeader(
        PacketKind::SessionGoodbye,
        g_local_transport.next_sequence++);
    packet.participant_id = g_local_transport.local_peer_id;
    packet.steam_id = g_local_transport.local_peer_id;
    packet.reason = static_cast<std::uint8_t>(reason);
    for (const auto& endpoint : BuildKnownSendEndpoints()) {
        SendPacketToEndpoint(packet, endpoint);
    }
}

void ApplyLocalSessionGoodbye(
    const SessionGoodbyePacket& packet,
    const TransportPeerEndpoint& from) {
    if (g_local_transport.backend != GameplayTransportBackend::LocalUdp ||
        packet.participant_id == 0 ||
        packet.participant_id != packet.steam_id ||
        FindLocalPeer(from, packet.participant_id) == nullptr) {
        return;
    }

    const auto reason =
        static_cast<SessionGoodbyeReason>(packet.reason);
    if (g_local_transport.is_host) {
        if (reason != SessionGoodbyeReason::Leaving) {
            return;
        }
        ResetRemoteParticipantSessionEpoch(
            packet.participant_id,
            false);
        g_local_transport.peers.erase(
            std::remove_if(
                g_local_transport.peers.begin(),
                g_local_transport.peers.end(),
                [&](const LocalPeerEndpoint& peer) {
                    return peer.participant_id == packet.participant_id;
                }),
            g_local_transport.peers.end());
        Log(
            "Multiplayer local UDP client left cleanly. participant_id=" +
            std::to_string(packet.participant_id));
        return;
    }

    if (!g_local_transport.configured_remote_valid ||
        !SameEndpoint(from, g_local_transport.configured_remote)) {
        return;
    }
    if (reason == SessionGoodbyeReason::LobbyClosed) {
        Log("Multiplayer local UDP received a clean host lobby close.");
        g_local_transport.clean_end_text =
            "The host closed the lobby.";
        PublishLocalSessionStatus(
            static_cast<std::uint64_t>(GetTickCount64()),
            true);
        NotifyRemoteHostSessionClosed();
    } else {
        Log("Multiplayer local UDP authority ended the session.");
        g_local_transport.clean_end_text =
            "The multiplayer host connection was lost.";
        PublishLocalSessionStatus(
            static_cast<std::uint64_t>(GetTickCount64()),
            true);
        NotifySessionAuthorityLost();
    }
}

void ServiceLocalTransportTeardown(std::uint64_t now_ms) {
    if (!g_local_transport.teardown_requested) {
        return;
    }
    if (g_local_transport.backend != GameplayTransportBackend::LocalUdp) {
        g_local_transport_teardown_complete.store(
            true,
            std::memory_order_release);
        return;
    }

    if (g_local_transport.teardown_started_ms == 0) {
        g_local_transport.teardown_started_ms = now_ms;
    }
    if (g_local_transport.teardown_notify_peers &&
        g_local_transport.teardown_send_count <
            kLocalTeardownSendCount &&
        (g_local_transport.last_teardown_send_ms == 0 ||
         now_ms >= g_local_transport.last_teardown_send_ms +
             kLocalTeardownSendIntervalMs)) {
        SendLocalSessionGoodbye(g_local_transport.teardown_reason);
        g_local_transport.last_teardown_send_ms = now_ms;
        g_local_transport.teardown_send_count += 1;
    }

    const bool sends_finished =
        !g_local_transport.teardown_notify_peers ||
        g_local_transport.teardown_send_count >=
            kLocalTeardownSendCount;
    if (!sends_finished ||
        now_ms < g_local_transport.teardown_started_ms +
            (kLocalTeardownSendIntervalMs *
             kLocalTeardownSendCount)) {
        return;
    }

    if (g_local_transport.socket_handle != INVALID_SOCKET) {
        closesocket(g_local_transport.socket_handle);
        g_local_transport.socket_handle = INVALID_SOCKET;
    }
    g_local_transport.initialized = false;
    g_local_transport_teardown_complete.store(
        true,
        std::memory_order_release);
    Log("Multiplayer local UDP teardown completed.");
}
