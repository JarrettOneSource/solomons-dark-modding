void OnHostLobbyReady(std::uint64_t lobby_id, std::uint64_t now_ms) {
    if (g_session.lobby_id == lobby_id &&
        (g_session.phase == SteamSessionPhase::LobbyReady ||
         g_session.phase == SteamSessionPhase::Connected)) {
        return;
    }
    if (lobby_id == 0 || SteamGetLobbyOwner(lobby_id) != g_session.local_steam_id) {
        SetError("Created lobby does not report the local Steam user as owner.", true);
        return;
    }
    g_session.lobby_id = lobby_id;
    g_session.host_steam_id = g_session.local_steam_id;
    g_session.pending_api_call = 0;
    if (!SetHostLobbyMetadata()) {
        SetError("Could not publish required build metadata to the Steam lobby.", true);
        return;
    }
    SetLocalLobbyMemberMetadata();
    ReconcileLobbyMembers(now_ms);
    if (g_session.phase == SteamSessionPhase::Error) {
        return;
    }
    g_session.phase = SteamSessionPhase::LobbyReady;
    SteamSetRichPresence("status", "Hosting Solomon Dark multiplayer");
    const auto connect = "+connect_lobby " + std::to_string(lobby_id);
    SteamSetRichPresence("connect", connect.c_str());
    if (g_session.invite_steam_id != 0) {
        if (g_session.invite_steam_id == g_session.local_steam_id ||
            !SteamInviteUserToLobby(lobby_id, g_session.invite_steam_id)) {
            SetError("Steam rejected the requested lobby invite.", true);
            return;
        }
        g_session.invite_sent = true;
        Log("Steam multiplayer sent the requested lobby invite.");
    }
    RefreshOverlayAndInviteDialog();
    Log("Steam multiplayer lobby ready. lobby_id=" + std::to_string(lobby_id));
}

void OnClientLobbyEntered(std::uint64_t lobby_id, std::uint64_t now_ms) {
    g_session.lobby_id = lobby_id;
    g_session.pending_api_call = 0;
    std::string error;
    if (!ValidateJoinedLobby(&error)) {
        SetError(std::move(error), true);
        return;
    }
    SetLocalLobbyMemberMetadata();
    ReconcileLobbyMembers(now_ms);
    if (g_session.phase == SteamSessionPhase::Error ||
        g_session.lobby_id != lobby_id) {
        return;
    }
    g_session.client_lobby_recovery = false;
    g_session.recovery_lobby_id = 0;
    g_session.recovery_started_ms = 0;
    g_session.last_join_attempt_ms = 0;
    g_session.phase = SteamSessionPhase::Handshaking;
    g_session.last_hello_send_ms = 0;
    SteamSetRichPresence("status", "Joining Solomon Dark multiplayer");
    Log(
        "Steam multiplayer lobby entered. lobby_id=" + std::to_string(lobby_id) +
        " host_steam_id=" + std::to_string(g_session.host_steam_id));
}

void HandleSteamEvent(const SteamEvent& event, std::uint64_t now_ms) {
    switch (event.kind) {
    case SteamEventKind::SteamServersDisconnected: {
        if (!g_session.steam_servers_connected) {
            return;
        }
        g_session.steam_servers_connected = false;
        g_session.recovery_started_ms = 0;
        Log(
            "Steam multiplayer service connection lost. result=" +
            std::to_string(event.result_code));
        if (!g_session.is_host) {
            const auto lobby_id =
                g_session.lobby_id != 0
                    ? g_session.lobby_id
                    : (g_session.recovery_lobby_id != 0
                           ? g_session.recovery_lobby_id
                           : g_session.desired_lobby_id);
            if (lobby_id != 0) {
                BeginClientLobbyRecovery(
                    lobby_id,
                    now_ms,
                    "steam_service_disconnected");
            } else {
                RemoveAllPeers();
                g_session.phase = SteamSessionPhase::Reconnecting;
            }
        } else {
            RemoveAllPeers();
            g_session.phase = SteamSessionPhase::Reconnecting;
        }
        return;
    }
    case SteamEventKind::SteamServersConnected:
        g_session.steam_servers_connected = true;
        Log("Steam multiplayer service connection restored.");
        if (!g_session.is_host) {
            const auto lobby_id =
                g_session.recovery_lobby_id != 0
                    ? g_session.recovery_lobby_id
                    : g_session.desired_lobby_id;
            if (lobby_id != 0 && g_session.client_lobby_recovery) {
                g_session.recovery_started_ms = now_ms;
                g_session.last_join_attempt_ms = 0;
                (void)BeginJoinLobby(lobby_id, true);
            } else if (g_session.phase == SteamSessionPhase::Reconnecting) {
                g_session.phase = SteamSessionPhase::WaitingForInvite;
            }
            return;
        }
        if (g_session.phase != SteamSessionPhase::Reconnecting) {
            return;
        }
        if (g_session.lobby_id == 0) {
            g_session.pending_api_call = SteamCreateLobby(
                g_session.lobby_visibility,
                static_cast<std::int32_t>(g_session.max_participants));
            if (g_session.pending_api_call == 0) {
                SetError(
                    "Steam reconnected, but the host lobby could not be recreated.",
                    false);
                return;
            }
            g_session.phase = SteamSessionPhase::CreatingLobby;
            return;
        }
        ReconcileLobbyMembers(now_ms);
        if (g_session.phase == SteamSessionPhase::Error) {
            return;
        }
        if (!SetHostLobbyMetadata()) {
            SetError(
                "Steam reconnected, but the host lobby metadata could not be restored.",
                true);
            return;
        }
        g_session.last_keepalive_send_ms = 0;
        g_session.phase = SteamSessionPhase::LobbyReady;
        return;
    case SteamEventKind::LobbyCreated:
        if (!g_session.is_host ||
            (event.api_call != 0 && event.api_call != g_session.pending_api_call)) {
            return;
        }
        if (!event.success) {
            SetError(
                "CreateLobby failed with Steam result " +
                    std::to_string(event.result_code) + '.',
                false);
            return;
        }
        OnHostLobbyReady(event.lobby_id, now_ms);
        return;
    case SteamEventKind::LobbyEntered:
        if (!event.success) {
            if (!g_session.is_host &&
                g_session.phase == SteamSessionPhase::JoiningLobby &&
                (event.api_call == 0 || event.api_call == g_session.pending_api_call)) {
                if (g_session.client_lobby_recovery) {
                    g_session.pending_api_call = 0;
                    g_session.last_join_attempt_ms = now_ms;
                    g_session.phase = SteamSessionPhase::Reconnecting;
                    Log(
                        "Steam multiplayer client lobby rejoin failed with response " +
                        std::to_string(event.result_code) +
                        "; the recovery state machine will retry.");
                    return;
                }
                SetError(
                    "JoinLobby failed with response " +
                        std::to_string(event.result_code) + '.',
                    false);
            }
            return;
        }
        if (g_session.is_host) {
            if (g_session.phase == SteamSessionPhase::CreatingLobby ||
                event.lobby_id == g_session.lobby_id) {
                OnHostLobbyReady(event.lobby_id, now_ms);
            }
        } else if (g_session.phase == SteamSessionPhase::JoiningLobby &&
                   event.lobby_id == g_session.desired_lobby_id &&
                   (event.api_call == 0 || event.api_call == g_session.pending_api_call)) {
            OnClientLobbyEntered(event.lobby_id, now_ms);
        }
        return;
    case SteamEventKind::LobbyJoinRequested:
        if (!g_session.is_host && event.lobby_id != 0) {
            BeginJoinLobby(event.lobby_id);
        }
        return;
    case SteamEventKind::RichPresenceJoinRequested: {
        std::uint64_t lobby_id = 0;
        if (!g_session.is_host &&
            TryParseLobbyIdFromConnectString(event.connect_string, &lobby_id)) {
            BeginJoinLobby(lobby_id);
        }
        return;
    }
    case SteamEventKind::LobbyMemberChanged:
        if (event.lobby_id == g_session.lobby_id) {
            ReconcileLobbyMembers(now_ms);
        }
        return;
    case SteamEventKind::LobbyDataUpdated:
        if (!g_session.is_host && event.lobby_id == g_session.lobby_id) {
            std::string error;
            if (!ValidateJoinedLobby(&error)) {
                SetError(std::move(error), true);
            }
        }
        return;
    case SteamEventKind::NetworkSessionRequested:
        if (IsLobbyMember(event.user_id)) {
            SteamAcceptNetworkSession(event.user_id);
        } else if (event.user_id != 0) {
            SteamCloseNetworkSession(event.user_id);
        }
        return;
    case SteamEventKind::NetworkSessionFailed:
        if (event.user_id == 0 || !IsLobbyMember(event.user_id)) {
            return;
        }
        Log(
            "Steam multiplayer network session failed. steam_id=" +
            std::to_string(event.user_id) +
            " state=" + std::to_string(event.network_status.connection_state) +
            " end_reason=" + std::to_string(event.network_status.end_reason) +
            " debug=" + event.network_status.debug_text +
            " connection=" + event.network_status.connection_description);
        if (!g_session.is_host && event.user_id == g_session.host_steam_id) {
            RestartClientHostHandshake(
                event.user_id, "network_session_failed", true);
        } else {
            RemovePeer(event.user_id);
        }
        return;
    case SteamEventKind::LobbyInviteReceived:
        if (!g_session.is_host &&
            (g_session.phase == SteamSessionPhase::WaitingForInvite ||
             g_session.phase == SteamSessionPhase::Reconnecting ||
             (g_session.phase == SteamSessionPhase::Error &&
              g_session.lobby_id == 0)) &&
            event.lobby_id != 0) {
            BeginJoinLobby(event.lobby_id);
        }
        return;
    }
}

bool SendHelloAck(
    std::uint64_t remote_steam_id,
    std::uint64_t session_nonce,
    SessionHelloResultCode result) {
    SessionHelloAckPacket packet{};
    packet.header = MakePacketHeader(PacketKind::SessionHelloAck, g_session.next_sequence++);
    packet.lobby_id = g_session.lobby_id;
    packet.authority_participant_id = g_session.local_steam_id;
    packet.target_participant_id = remote_steam_id;
    packet.target_steam_id = remote_steam_id;
    packet.session_nonce = session_nonce;
    packet.capabilities = kRequiredSessionCapabilities;
    packet.result_code = static_cast<std::uint8_t>(result);
    packet.authority_role = static_cast<std::uint8_t>(SessionPeerRole::Host);
    packet.max_participants = static_cast<std::uint8_t>(g_session.max_participants);
    std::memcpy(
        packet.manifest_sha256,
        g_session.manifest_sha256.data(),
        g_session.manifest_sha256.size());
    return SteamSendNetworkMessage(
        remote_steam_id,
        &packet,
        sizeof(packet),
        SteamNetworkSendMode::ReliableNoNagle);
}

void HandleSessionHello(
    const SteamNetworkMessage& message,
    const SessionHelloPacket& packet,
    bool protocol_matches,
    std::uint64_t now_ms) {
    if (!g_session.is_host ||
        (g_session.phase != SteamSessionPhase::LobbyReady &&
         g_session.phase != SteamSessionPhase::Connected)) {
        return;
    }
    SessionHelloResultCode result = SessionHelloResultCode::Accepted;
    if (!protocol_matches) {
        result = SessionHelloResultCode::ProtocolMismatch;
    } else if (!IsLobbyMember(message.sender_steam_id) ||
               packet.lobby_id != g_session.lobby_id) {
        result = SessionHelloResultCode::LobbyMismatch;
    } else if (packet.participant_id != message.sender_steam_id ||
               packet.steam_id != message.sender_steam_id ||
               packet.session_nonce == 0 ||
               packet.role != static_cast<std::uint8_t>(SessionPeerRole::Client)) {
        result = SessionHelloResultCode::IdentityMismatch;
    } else if (packet.host_steam_id != g_session.local_steam_id) {
        result = SessionHelloResultCode::HostMismatch;
    } else if (packet.app_id != g_session.app_id) {
        result = SessionHelloResultCode::LobbyMismatch;
    } else if ((packet.capabilities & kRequiredSessionCapabilities) !=
               kRequiredSessionCapabilities) {
        result = SessionHelloResultCode::CapabilityMismatch;
    } else if (std::memcmp(
                   packet.manifest_sha256,
                   g_session.manifest_sha256.data(),
                   g_session.manifest_sha256.size()) != 0) {
        result = SessionHelloResultCode::ManifestMismatch;
    } else {
        std::uint32_t authenticated_count = 1;
        for (const auto& [steam_id, peer] : g_session.peers) {
            if (steam_id != message.sender_steam_id && peer.authenticated) {
                authenticated_count += 1;
            }
        }
        if (authenticated_count >= g_session.max_participants) {
            result = SessionHelloResultCode::LobbyFull;
        }
    }

    auto& peer = g_session.peers[message.sender_steam_id];
    peer.steam_id = message.sender_steam_id;
    peer.session_nonce = packet.session_nonce;
    peer.last_packet_ms = now_ms;
    peer.display_name = PacketDisplayName(packet.display_name, sizeof(packet.display_name));
    if (result == SessionHelloResultCode::Accepted) {
        peer.authenticated = true;
        peer.rejected = false;
        SteamAcceptNetworkSession(message.sender_steam_id);
        RegisterSteamGameplayPeer(message.sender_steam_id, false);
        g_session.phase = SteamSessionPhase::Connected;
    } else {
        peer.authenticated = false;
        peer.rejected = true;
    }
    SendHelloAck(message.sender_steam_id, packet.session_nonce, result);
    Log(
        "Steam multiplayer hello result. steam_id=" +
        std::to_string(message.sender_steam_id) +
        " result=" + HelloResultLabel(result));
}
