bool SetHostLobbyMetadata() {
    const auto lobby_id = g_session.lobby_id;
    return SteamSetLobbyData(lobby_id, kLobbyProtocolKey, std::to_string(kProtocolVersion).c_str()) &&
           SteamSetLobbyData(lobby_id, kLobbyManifestKey, g_session.manifest_sha256_text.c_str()) &&
           SteamSetLobbyData(lobby_id, kLobbyHostKey, std::to_string(g_session.local_steam_id).c_str()) &&
           SteamSetLobbyData(lobby_id, kLobbyAppIdKey, std::to_string(g_session.app_id).c_str()) &&
           SteamSetLobbyData(
               lobby_id,
               kLobbyMaxParticipantsKey,
               std::to_string(g_session.max_participants).c_str()) &&
           SteamSetLobbyData(lobby_id, kLobbyStateKey, kLobbyStateOpen) &&
           SteamSetLobbyJoinable(lobby_id, true);
}

void SetLocalLobbyMemberMetadata() {
    if (g_session.lobby_id == 0) {
        return;
    }
    SteamSetLobbyMemberData(
        g_session.lobby_id,
        kMemberProtocolKey,
        std::to_string(kProtocolVersion).c_str());
    SteamSetLobbyMemberData(
        g_session.lobby_id,
        kMemberManifestKey,
        g_session.manifest_sha256_text.c_str());
}

bool ValidateJoinedLobby(std::string* error_message) {
    const auto owner = SteamGetLobbyOwner(g_session.lobby_id);
    std::uint64_t advertised_host = 0;
    std::uint64_t advertised_protocol = 0;
    std::uint64_t advertised_app_id = 0;
    std::uint64_t advertised_max = 0;
    if (owner == 0 ||
        !TryParseUnsigned64(SteamGetLobbyData(g_session.lobby_id, kLobbyHostKey), &advertised_host) ||
        owner != advertised_host) {
        *error_message = "Lobby owner metadata does not match the Steam lobby owner.";
        return false;
    }
    if (!TryParseUnsigned64(
            SteamGetLobbyData(g_session.lobby_id, kLobbyProtocolKey),
            &advertised_protocol) ||
        advertised_protocol != kProtocolVersion) {
        *error_message = "Lobby uses a different multiplayer protocol version.";
        return false;
    }
    if (SteamGetLobbyData(g_session.lobby_id, kLobbyManifestKey) !=
        g_session.manifest_sha256_text) {
        *error_message = "Lobby mod/game build fingerprint does not match.";
        return false;
    }
    if (!TryParseUnsigned64(
            SteamGetLobbyData(g_session.lobby_id, kLobbyAppIdKey),
            &advertised_app_id) ||
        advertised_app_id != g_session.app_id) {
        *error_message = "Lobby Steam AppID does not match this launch.";
        return false;
    }
    if (!TryParseUnsigned64(
            SteamGetLobbyData(g_session.lobby_id, kLobbyMaxParticipantsKey),
            &advertised_max) ||
        advertised_max < 2 ||
        advertised_max > kMaximumSupportedParticipants) {
        *error_message = "Lobby participant limit is unsupported.";
        return false;
    }
    if (SteamGetLobbyData(g_session.lobby_id, kLobbyStateKey) != kLobbyStateOpen) {
        *error_message = "Lobby is no longer accepting players.";
        return false;
    }
    g_session.host_steam_id = owner;
    g_session.max_participants = static_cast<std::uint32_t>(advertised_max);
    return true;
}

void ReconcileLobbyMembers(std::uint64_t now_ms) {
    if (g_session.lobby_id == 0) {
        return;
    }
    const auto members = SteamGetLobbyMembers(g_session.lobby_id);
    std::unordered_set<std::uint64_t> current(members.begin(), members.end());
    if (current.find(g_session.local_steam_id) == current.end()) {
        SetError("Local Steam user is no longer a lobby member.", false);
        return;
    }
    const auto owner = SteamGetLobbyOwner(g_session.lobby_id);
    if ((g_session.is_host && owner != g_session.local_steam_id) ||
        (!g_session.is_host && owner != g_session.host_steam_id)) {
        SetError("Steam lobby ownership changed; host migration is not supported.", true);
        return;
    }

    std::vector<std::uint64_t> removed;
    for (const auto& [steam_id, peer] : g_session.peers) {
        (void)peer;
        if (current.find(steam_id) == current.end()) {
            removed.push_back(steam_id);
        }
    }
    for (const auto steam_id : removed) {
        RemovePeer(steam_id);
    }

    for (const auto steam_id : current) {
        if (steam_id == g_session.local_steam_id ||
            (!g_session.is_host && steam_id != g_session.host_steam_id)) {
            continue;
        }
        auto& peer = g_session.peers[steam_id];
        peer.steam_id = steam_id;
        if (peer.display_name.empty()) {
            peer.display_name = SteamGetFriendPersonaName(steam_id);
        }
    }
    g_session.lobby_members = std::move(current);
    g_session.last_lobby_reconcile_ms = now_ms;
}

void PublishSessionRuntime(std::uint64_t now_ms) {
    bool any_relayed = false;
    std::int32_t maximum_ping = 0;
    std::uint32_t authenticated_count = 0;
    for (const auto& [steam_id, peer] : g_session.peers) {
        (void)steam_id;
        if (!peer.authenticated) {
            continue;
        }
        authenticated_count += 1;
        any_relayed = any_relayed || peer.network_status.using_relay;
        maximum_ping = (std::max)(maximum_ping, peer.network_status.ping_ms);
    }

    std::ostringstream status;
    switch (g_session.phase) {
    case SteamSessionPhase::WaitingForInvite:
        status << "Steam multiplayer waiting for a lobby invite.";
        break;
    case SteamSessionPhase::CreatingLobby:
        status << "Creating friends-only Steam lobby.";
        break;
    case SteamSessionPhase::JoiningLobby:
        status << "Joining Steam lobby " << g_session.desired_lobby_id << '.';
        break;
    case SteamSessionPhase::Handshaking:
        status << "Steam lobby " << g_session.lobby_id
               << " joined; validating host build identity.";
        break;
    case SteamSessionPhase::LobbyReady:
        status << "Steam lobby " << g_session.lobby_id
               << " ready for invites; authenticated peers="
               << authenticated_count;
        break;
    case SteamSessionPhase::Connected:
        status << "Steam lobby " << g_session.lobby_id
               << " connected; authenticated peers=" << authenticated_count
               << " route=" << (any_relayed ? "SDR" : "direct-or-pending")
               << " ping_ms=" << maximum_ping;
        break;
    case SteamSessionPhase::Error:
        status << "Steam multiplayer error: " << g_session.error_text;
        break;
    case SteamSessionPhase::Disabled:
    default:
        status << "Steam multiplayer disabled.";
        break;
    }
    const auto status_text = status.str();

    UpdateRuntimeState([&](RuntimeState& state) {
        state.session_transport = SessionTransportKind::Steam;
        state.session_is_host = g_session.is_host;
        state.steam_app_id = g_session.app_id;
        state.steam_lobby_id = g_session.lobby_id;
        state.steam_host_id = g_session.host_steam_id;
        state.session_max_participants = g_session.max_participants;
        state.authenticated_peer_count = authenticated_count;
        state.steam_route_relayed = any_relayed;
        state.steam_route_ping_ms = maximum_ping;
        state.multiplayer_manifest_sha256 = g_session.manifest_sha256_text;
        state.transport_ready =
            g_session.phase == SteamSessionPhase::LobbyReady ||
            g_session.phase == SteamSessionPhase::Connected;
        switch (g_session.phase) {
        case SteamSessionPhase::WaitingForInvite:
            state.session_status = SessionStatus::WaitingForInvite;
            break;
        case SteamSessionPhase::CreatingLobby:
            state.session_status = SessionStatus::CreatingLobby;
            break;
        case SteamSessionPhase::JoiningLobby:
            state.session_status = SessionStatus::JoiningLobby;
            break;
        case SteamSessionPhase::Handshaking:
            state.session_status = SessionStatus::Handshaking;
            break;
        case SteamSessionPhase::LobbyReady:
        case SteamSessionPhase::Connected:
            state.session_status = SessionStatus::Ready;
            break;
        case SteamSessionPhase::Error:
            state.session_status = SessionStatus::Error;
            break;
        case SteamSessionPhase::Disabled:
        default:
            state.session_status = SessionStatus::Idle;
            break;
        }

        state.status_text = status_text;
        state.error_text = g_session.phase == SteamSessionPhase::Error
            ? g_session.error_text
            : std::string{};

        auto* local = UpsertLocalParticipant(state);
        if (local != nullptr) {
            local->steam_id = g_session.local_steam_id;
            local->transport_connected = state.transport_ready;
            local->transport_using_relay = any_relayed;
            local->last_packet_ms = now_ms;
        }
        for (const auto& [steam_id, peer] : g_session.peers) {
            auto* participant = FindParticipant(state, steam_id);
            if (participant == nullptr && peer.authenticated) {
                participant = UpsertRemoteParticipant(
                    state,
                    steam_id,
                    ParticipantControllerKind::Native);
            }
            if (participant == nullptr) {
                continue;
            }
            participant->steam_id = steam_id;
            participant->transport_connected = peer.authenticated;
            participant->transport_using_relay = peer.network_status.using_relay;
            if (!peer.display_name.empty() &&
                (participant->name.empty() || participant->name == "Remote Wizard")) {
                participant->name = peer.display_name;
            }
        }
    });

    std::ostringstream signature;
    signature << SteamSessionPhaseLabel(g_session.phase) << '|'
              << g_session.lobby_id << '|'
              << g_session.host_steam_id << '|'
              << authenticated_count << '|'
              << (g_session.overlay_enabled ? 1 : 0) << '|'
              << (g_session.invite_dialog_opened ? 1 : 0) << '|'
              << (any_relayed ? 1 : 0) << '|'
              << maximum_ping << '|'
              << g_session.error_text;
    const auto status_signature = signature.str();
    if (status_signature != g_session.last_status_signature ||
        g_session.last_status_write_ms == 0 ||
        now_ms >= g_session.last_status_write_ms +
            kSessionStatusWriteIntervalMs) {
        MultiplayerSessionStatusSnapshot snapshot;
        snapshot.launch_token = g_session.launch_token;
        snapshot.enabled = g_session.configured;
        snapshot.is_host = g_session.is_host;
        snapshot.phase = SteamSessionPhaseLabel(g_session.phase);
        snapshot.app_id = g_session.app_id;
        snapshot.lobby_id = g_session.lobby_id;
        snapshot.host_steam_id = g_session.host_steam_id;
        snapshot.max_participants = g_session.max_participants;
        snapshot.authenticated_peer_count = authenticated_count;
        snapshot.overlay_enabled = g_session.overlay_enabled;
        snapshot.invite_dialog_opened = g_session.invite_dialog_opened;
        snapshot.invite_sent = g_session.invite_sent;
        snapshot.route_relayed = any_relayed;
        snapshot.route_ping_ms = maximum_ping;
        snapshot.status_text = status_text;
        snapshot.error_text = g_session.error_text;
        WriteMultiplayerSessionStatus(
            GetStageRuntimeDirectory(),
            snapshot);
        g_session.last_status_signature = status_signature;
        g_session.last_status_write_ms = now_ms;
    }
}

bool BeginJoinLobby(std::uint64_t lobby_id) {
    if (lobby_id == 0 || g_session.is_host) {
        return false;
    }
    if (g_session.lobby_id != 0) {
        SteamLeaveLobby(g_session.lobby_id);
    }
    RemoveAllPeers();
    g_session.lobby_members.clear();
    g_session.lobby_id = 0;
    g_session.host_steam_id = 0;
    g_session.desired_lobby_id = lobby_id;
    g_session.local_session_nonce = GenerateSessionNonce();
    g_session.pending_api_call = SteamJoinLobby(lobby_id);
    if (g_session.pending_api_call == 0) {
        SetError("Steam rejected the JoinLobby request before it was queued.", false);
        return false;
    }
    g_session.phase = SteamSessionPhase::JoiningLobby;
    g_session.error_text.clear();
    Log("Steam multiplayer joining lobby_id=" + std::to_string(lobby_id));
    return true;
}

void RefreshOverlayAndInviteDialog() {
    g_session.overlay_enabled = SteamIsOverlayEnabled();
    if (!g_session.is_host ||
        !g_session.open_invite_dialog ||
        g_session.lobby_id == 0 ||
        g_session.invite_dialog_opened) {
        return;
    }
    if (g_session.overlay_enabled) {
        SteamOpenLobbyInviteDialog(g_session.lobby_id);
        g_session.invite_dialog_opened = true;
        Log("Steam multiplayer opened the lobby invite dialog in the Steam overlay.");
        return;
    }
    if (!g_session.invite_fallback_logged) {
        g_session.invite_fallback_logged = true;
        Log(
            "Steam multiplayer lobby is inviteable, but the overlay is not active. "
            "Invite or join through the Steam Friends window, or share the lobby id.");
    }
}

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
    if (g_session.phase == SteamSessionPhase::Error) {
        return;
    }
    g_session.phase = SteamSessionPhase::Handshaking;
    g_session.last_hello_send_ms = 0;
    SteamSetRichPresence("status", "Joining Solomon Dark multiplayer");
    Log(
        "Steam multiplayer lobby entered. lobby_id=" + std::to_string(lobby_id) +
        " host_steam_id=" + std::to_string(g_session.host_steam_id));
}

void HandleSteamEvent(const SteamEvent& event, std::uint64_t now_ms) {
    switch (event.kind) {
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
        if (!g_session.is_host && event.user_id == g_session.host_steam_id) {
            RestartClientHostHandshake(event.user_id, "network_session_failed");
        } else {
            RemovePeer(event.user_id);
        }
        return;
    case SteamEventKind::LobbyInviteReceived:
        if (!g_session.is_host &&
            (g_session.phase == SteamSessionPhase::WaitingForInvite ||
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
