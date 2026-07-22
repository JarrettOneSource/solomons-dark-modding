void SendClientHello(std::uint64_t now_ms) {
    if (g_session.is_host ||
        g_session.phase != SteamSessionPhase::Handshaking ||
        g_session.host_steam_id == 0 ||
        (g_session.last_hello_send_ms != 0 &&
         now_ms < g_session.last_hello_send_ms + kHelloRetryIntervalMs)) {
        return;
    }
    SessionHelloPacket packet{};
    packet.header = MakePacketHeader(PacketKind::SessionHello, g_session.next_sequence++);
    packet.lobby_id = g_session.lobby_id;
    packet.participant_id = g_session.local_steam_id;
    packet.steam_id = g_session.local_steam_id;
    packet.host_steam_id = g_session.host_steam_id;
    packet.session_nonce = g_session.local_session_nonce;
    packet.app_id = g_session.app_id;
    packet.capabilities = kRequiredSessionCapabilities;
    packet.role = static_cast<std::uint8_t>(SessionPeerRole::Client);
    CopyDisplayName(
        GetSteamBootstrapSnapshot().persona_name,
        packet.display_name,
        sizeof(packet.display_name));
    std::memcpy(
        packet.manifest_sha256,
        g_session.manifest_sha256.data(),
        g_session.manifest_sha256.size());
    SteamSendNetworkMessage(
        g_session.host_steam_id,
        &packet,
        sizeof(packet),
        SteamNetworkSendMode::ReliableNoNagle);
    g_session.last_hello_send_ms = now_ms;
}

void HandleSessionHelloAck(
    const SteamNetworkMessage& message,
    const SessionHelloAckPacket& packet,
    std::uint64_t now_ms) {
    if (g_session.is_host ||
        g_session.phase != SteamSessionPhase::Handshaking ||
        message.sender_steam_id != g_session.host_steam_id ||
        packet.lobby_id != g_session.lobby_id ||
        packet.authority_participant_id != g_session.host_steam_id ||
        packet.target_participant_id != g_session.local_steam_id ||
        packet.target_steam_id != g_session.local_steam_id ||
        packet.session_nonce != g_session.local_session_nonce ||
        packet.authority_role != static_cast<std::uint8_t>(SessionPeerRole::Host)) {
        return;
    }
    const auto result = static_cast<SessionHelloResultCode>(packet.result_code);
    if (result != SessionHelloResultCode::Accepted) {
        SetError(
            std::string("Host rejected session handshake: ") +
                HelloResultLabel(result) + '.',
            true);
        return;
    }
    if ((packet.capabilities & kRequiredSessionCapabilities) !=
            kRequiredSessionCapabilities ||
        std::memcmp(
            packet.manifest_sha256,
            g_session.manifest_sha256.data(),
            g_session.manifest_sha256.size()) != 0 ||
        packet.max_participants != g_session.max_participants) {
        SetError("Host acknowledgement changed session identity data.", true);
        return;
    }

    auto& peer = g_session.peers[message.sender_steam_id];
    peer.steam_id = message.sender_steam_id;
    peer.session_nonce = packet.session_nonce;
    peer.last_packet_ms = now_ms;
    peer.authenticated = true;
    peer.rejected = false;
    if (peer.display_name.empty()) {
        peer.display_name = SteamGetFriendPersonaName(message.sender_steam_id);
    }
    RegisterSteamGameplayPeer(message.sender_steam_id, true);
    g_session.phase = SteamSessionPhase::Connected;
    SteamSetRichPresence("status", "Playing Solomon Dark multiplayer");
    Log(
        "Steam multiplayer host handshake accepted. host_steam_id=" +
        std::to_string(message.sender_steam_id));
}

void HandleSessionGoodbye(
    const SteamNetworkMessage& message,
    const SessionGoodbyePacket& packet) {
    if (packet.lobby_id != g_session.lobby_id ||
        packet.steam_id != message.sender_steam_id ||
        packet.participant_id != message.sender_steam_id) {
        return;
    }
    RemovePeer(message.sender_steam_id);
    if (!g_session.is_host && message.sender_steam_id == g_session.host_steam_id) {
        SetError("The Steam lobby host ended the multiplayer session.", true);
    }
}

void HandleSessionKeepalive(
    const SteamNetworkMessage& message,
    const SessionKeepalivePacket& packet,
    std::uint64_t now_ms) {
    const auto peer_it = g_session.peers.find(message.sender_steam_id);
    if (peer_it == g_session.peers.end() ||
        packet.lobby_id != g_session.lobby_id ||
        packet.participant_id != message.sender_steam_id ||
        packet.steam_id != message.sender_steam_id ||
        packet.target_steam_id != g_session.local_steam_id ||
        packet.session_nonce != peer_it->second.session_nonce) {
        return;
    }
    auto& peer = peer_it->second;
    if (!peer.authenticated) {
        if (!g_session.is_host ||
            !IsLobbyMember(message.sender_steam_id) ||
            peer.rejected ||
            peer.session_nonce == 0 ||
            (g_session.phase != SteamSessionPhase::LobbyReady &&
             g_session.phase != SteamSessionPhase::Connected)) {
            return;
        }
        SteamAcceptNetworkSession(message.sender_steam_id);
        peer.authenticated = true;
        RegisterSteamGameplayPeer(message.sender_steam_id, false);
        g_session.phase = SteamSessionPhase::Connected;
        Log(
            "Steam multiplayer peer restored by validated keepalive. steam_id=" +
            std::to_string(message.sender_steam_id));
    }
    peer.last_packet_ms = now_ms;
}

void PumpNetworkMessages(std::uint64_t now_ms) {
    std::unordered_set<std::uint64_t> handled_session_hello_senders;
    for (auto& message : SteamReceiveNetworkMessages(0, kReceiveBatchSize)) {
        if (!IsLobbyMember(message.sender_steam_id) ||
            message.payload.size() < sizeof(PacketHeader)) {
            SteamCloseNetworkSession(message.sender_steam_id);
            continue;
        }
        PacketHeader header{};
        std::memcpy(&header, message.payload.data(), sizeof(header));
        if (!HasProtocolMagic(header)) {
            continue;
        }
        const auto kind = static_cast<PacketKind>(header.kind);
        if (kind == PacketKind::SessionHello) {
            SessionHelloPacket packet{};
            if (CopyNetworkPacket(message, &packet) &&
                handled_session_hello_senders.insert(message.sender_steam_id).second) {
                HandleSessionHello(
                    message,
                    packet,
                    header.version == kProtocolVersion,
                    now_ms);
            }
            continue;
        }
        if (!IsValidPacketHeader(header)) {
            continue;
        }
        if (kind == PacketKind::SessionHelloAck) {
            SessionHelloAckPacket packet{};
            if (CopyNetworkPacket(message, &packet)) {
                HandleSessionHelloAck(message, packet, now_ms);
            }
            continue;
        }
        if (kind == PacketKind::SessionGoodbye) {
            SessionGoodbyePacket packet{};
            if (CopyNetworkPacket(message, &packet)) {
                HandleSessionGoodbye(message, packet);
            }
            continue;
        }
        if (kind == PacketKind::SessionKeepalive) {
            SessionKeepalivePacket packet{};
            if (CopyNetworkPacket(message, &packet)) {
                HandleSessionKeepalive(message, packet, now_ms);
            }
            continue;
        }

        const auto peer_it = g_session.peers.find(message.sender_steam_id);
        if (peer_it == g_session.peers.end() || !peer_it->second.authenticated) {
            continue;
        }
        peer_it->second.last_packet_ms = now_ms;
        SubmitSteamGameplayPacket(
            message.sender_steam_id,
            message.payload.data(),
            message.payload.size(),
            now_ms,
            message.reliable);
    }
}

void SendSessionKeepalives(std::uint64_t now_ms) {
    if (g_session.phase != SteamSessionPhase::Connected ||
        (g_session.last_keepalive_send_ms != 0 &&
         now_ms < g_session.last_keepalive_send_ms + kKeepaliveIntervalMs)) {
        return;
    }

    bool sent = false;
    for (const auto& [steam_id, peer] : g_session.peers) {
        if (!peer.authenticated || peer.session_nonce == 0) {
            continue;
        }
        SessionKeepalivePacket packet{};
        packet.header = MakePacketHeader(
            PacketKind::SessionKeepalive,
            g_session.next_sequence++);
        packet.lobby_id = g_session.lobby_id;
        packet.participant_id = g_session.local_steam_id;
        packet.steam_id = g_session.local_steam_id;
        packet.target_steam_id = steam_id;
        packet.session_nonce = peer.session_nonce;
        std::int32_t result_code = 0;
        const bool send_succeeded = SteamSendNetworkMessage(
            steam_id,
            &packet,
            sizeof(packet),
            SteamNetworkSendMode::UnreliableNoNagle,
            &result_code);
        g_session.last_keepalive_send_result = result_code;
        if (send_succeeded) {
            g_session.last_keepalive_send_success_ms = now_ms;
        }
        sent = true;
    }
    if (sent) {
        g_session.last_keepalive_send_ms = now_ms;
    }
}

void ExpireInactivePeers(std::uint64_t now_ms) {
    std::vector<std::uint64_t> expired;
    for (const auto& [steam_id, peer] : g_session.peers) {
        if (peer.authenticated &&
            peer.last_packet_ms != 0 &&
            now_ms >= peer.last_packet_ms &&
            now_ms - peer.last_packet_ms >= kAuthenticatedPeerTimeoutMs) {
            expired.push_back(steam_id);
        }
    }

    for (const auto steam_id : expired) {
        const auto peer_it = g_session.peers.find(steam_id);
        if (peer_it == g_session.peers.end()) {
            continue;
        }
        Log(
            "Steam multiplayer peer timed out. steam_id=" +
            std::to_string(steam_id) +
            " last_packet_age_ms=" +
            std::to_string(now_ms - peer_it->second.last_packet_ms) +
            " last_keepalive_success_age_ms=" +
            std::to_string(
                g_session.last_keepalive_send_success_ms == 0
                    ? 0
                    : now_ms - g_session.last_keepalive_send_success_ms) +
            " last_keepalive_result=" +
            std::to_string(g_session.last_keepalive_send_result));
        if (!g_session.is_host && steam_id == g_session.host_steam_id) {
            RestartClientHostHandshake(
                steam_id, "authenticated_peer_timeout", false);
            continue;
        }
        SuspendPeerForReauthentication(steam_id);
    }

    if (g_session.is_host && g_session.phase == SteamSessionPhase::Connected) {
        const bool has_authenticated_peer = std::any_of(
            g_session.peers.begin(),
            g_session.peers.end(),
            [](const auto& entry) { return entry.second.authenticated; });
        if (!has_authenticated_peer) {
            g_session.phase = SteamSessionPhase::LobbyReady;
        }
    }
}

void RefreshRouteStatus(std::uint64_t now_ms) {
    if (g_session.last_route_status_ms != 0 &&
        now_ms < g_session.last_route_status_ms + kRouteStatusIntervalMs) {
        return;
    }
    for (auto& [steam_id, peer] : g_session.peers) {
        if (!peer.authenticated) {
            continue;
        }
        peer.network_status = SteamGetNetworkSessionStatus(steam_id);
    }
    g_session.last_route_status_ms = now_ms;
}

void SendGoodbyeToAuthenticatedPeers(SessionGoodbyeReason reason) {
    if (g_session.lobby_id == 0) {
        return;
    }
    SessionGoodbyePacket packet{};
    packet.header = MakePacketHeader(PacketKind::SessionGoodbye, g_session.next_sequence++);
    packet.lobby_id = g_session.lobby_id;
    packet.participant_id = g_session.local_steam_id;
    packet.steam_id = g_session.local_steam_id;
    packet.reason = static_cast<std::uint8_t>(reason);
    for (const auto& [steam_id, peer] : g_session.peers) {
        if (!peer.authenticated) {
            continue;
        }
        SteamSendNetworkMessage(
            steam_id,
            &packet,
            sizeof(packet),
            SteamNetworkSendMode::ReliableNoNagle);
    }
}
