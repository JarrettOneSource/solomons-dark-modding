bool SetHostLobbyMetadata() {
    const auto lobby_id = g_session.lobby_id;
    return SteamSetLobbyData(lobby_id, kLobbyProtocolKey, std::to_string(kProtocolVersion).c_str()) &&
           SteamSetLobbyData(lobby_id, kLobbyManifestKey, g_session.manifest_sha256_text.c_str()) &&
           SteamSetLobbyData(lobby_id, kLobbyHostKey, std::to_string(g_session.local_steam_id).c_str()) &&
           SteamSetLobbyData(lobby_id, kLobbyAppIdKey, std::to_string(g_session.app_id).c_str()) &&
           SteamSetLobbyData(lobby_id, kLobbyPrivacyKey, g_session.privacy.c_str()) &&
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

bool BeginJoinLobby(std::uint64_t lobby_id, bool recovery = false);
void BeginClientLobbyRecovery(
    std::uint64_t lobby_id,
    std::uint64_t now_ms,
    const char* reason);

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
    const auto advertised_privacy =
        SteamGetLobbyData(g_session.lobby_id, kLobbyPrivacyKey);
    if (advertised_privacy == "public") {
        g_session.lobby_visibility = SteamLobbyVisibility::Public;
        g_session.privacy = "public";
    } else if (advertised_privacy == "friendsOnly") {
        g_session.lobby_visibility = SteamLobbyVisibility::FriendsOnly;
        g_session.privacy = "friendsOnly";
    } else {
        *error_message = "Lobby privacy metadata is invalid.";
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
        if (!g_session.is_host) {
            const auto lobby_id = g_session.lobby_id;
            BeginClientLobbyRecovery(
                lobby_id,
                now_ms,
                "local_lobby_membership_missing");
            return;
        }
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

    const auto steam_snapshot = GetSteamBootstrapSnapshot();
    std::string game_phase = "loading";
    ParticipantRuntimeInfo local_runtime;
    if (TryGetLocalParticipantRuntimeInfo(&local_runtime)) {
        switch (local_runtime.scene_intent.kind) {
        case ParticipantSceneIntentKind::SharedHub:
            game_phase = "hub";
            break;
        case ParticipantSceneIntentKind::Run:
            game_phase = "session";
            break;
        case ParticipantSceneIntentKind::PrivateRegion:
            game_phase = "loading";
            break;
        }
    }

    if (g_session.is_host &&
        (g_session.last_friend_list_refresh_ms == 0 ||
         now_ms >= g_session.last_friend_list_refresh_ms +
             kFriendListRefreshIntervalMs)) {
        g_session.immediate_friend_ids = SteamGetImmediateFriends();
        g_session.immediate_friend_ids.erase(
            std::remove_if(
                g_session.immediate_friend_ids.begin(),
                g_session.immediate_friend_ids.end(),
                [](std::uint64_t steam_id) {
                    return steam_id == 0 || steam_id == g_session.local_steam_id;
                }),
            g_session.immediate_friend_ids.end());
        std::sort(
            g_session.immediate_friend_ids.begin(),
            g_session.immediate_friend_ids.end());
        g_session.immediate_friend_ids.erase(
            std::unique(
                g_session.immediate_friend_ids.begin(),
                g_session.immediate_friend_ids.end()),
            g_session.immediate_friend_ids.end());
        g_session.last_friend_list_refresh_ms = now_ms;
    }
    const auto& friend_steam_ids = g_session.immediate_friend_ids;

    std::vector<MultiplayerSessionMemberSnapshot> members;
    if (g_session.lobby_id != 0 && !g_session.lobby_members.empty()) {
        members.reserve(g_session.lobby_members.size());
        for (const auto member_steam_id : g_session.lobby_members) {
            MultiplayerSessionMemberSnapshot member;
            member.steam_id = member_steam_id;
            member.is_host = member_steam_id == g_session.host_steam_id;
            member.is_local = member_steam_id == g_session.local_steam_id;
            if (member.is_local) {
                member.name = steam_snapshot.persona_name;
            } else if (const auto peer = g_session.peers.find(member_steam_id);
                       peer != g_session.peers.end() &&
                       !peer->second.display_name.empty()) {
                member.name = peer->second.display_name;
            } else {
                member.name = SteamGetFriendPersonaName(member_steam_id);
            }
            members.push_back(std::move(member));
        }
        std::sort(
            members.begin(),
            members.end(),
            [](const MultiplayerSessionMemberSnapshot& left,
               const MultiplayerSessionMemberSnapshot& right) {
                if (left.is_host != right.is_host) {
                    return left.is_host;
                }
                if (left.is_local != right.is_local) {
                    return left.is_local;
                }
                return left.steam_id < right.steam_id;
            });
    }

    std::ostringstream status;
    switch (g_session.phase) {
    case SteamSessionPhase::WaitingForInvite:
        status << "Steam join mode ready; accept an invite or enter a lobby ID.";
        break;
    case SteamSessionPhase::CreatingLobby:
        status << "Creating "
               << (g_session.lobby_visibility == SteamLobbyVisibility::Public
                       ? "public"
                       : "friends-only")
               << " Steam lobby.";
        break;
    case SteamSessionPhase::JoiningLobby:
        status << "Joining Steam lobby " << g_session.desired_lobby_id << '.';
        break;
    case SteamSessionPhase::Reconnecting:
        status << "Steam multiplayer reconnecting after Steam service interruption.";
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
        case SteamSessionPhase::Reconnecting:
            state.session_status = SessionStatus::Handshaking;
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
              << g_session.local_steam_id << '|'
              << g_session.privacy << '|'
              << game_phase << '|'
              << authenticated_count << '|'
              << (g_session.overlay_enabled ? 1 : 0) << '|'
              << (g_session.invite_dialog_opened ? 1 : 0) << '|'
              << (any_relayed ? 1 : 0) << '|'
              << maximum_ping << '|'
              << g_session.error_text;
    for (const auto friend_steam_id : friend_steam_ids) {
        signature << "|f:" << friend_steam_id;
    }
    for (const auto& member : members) {
        signature << '|' << member.steam_id << ':'
                  << (member.is_host ? 'h' : '-') << ':' << member.name;
    }
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
        snapshot.game_phase = game_phase;
        snapshot.app_id = g_session.app_id;
        snapshot.lobby_id = g_session.lobby_id;
        snapshot.host_steam_id = g_session.host_steam_id;
        snapshot.local_steam_id = g_session.local_steam_id;
        snapshot.persona_name = steam_snapshot.persona_name;
        snapshot.privacy = g_session.privacy;
        snapshot.protocol_version = kProtocolVersion;
        snapshot.manifest_sha256 = g_session.manifest_sha256_text;
        snapshot.friend_steam_ids = friend_steam_ids;
        snapshot.max_participants = g_session.max_participants;
        snapshot.authenticated_peer_count = authenticated_count;
        snapshot.overlay_enabled = g_session.overlay_enabled;
        snapshot.invite_dialog_opened = g_session.invite_dialog_opened;
        snapshot.invite_sent = g_session.invite_sent;
        snapshot.route_relayed = any_relayed;
        snapshot.route_ping_ms = maximum_ping;
        snapshot.members = members;
        snapshot.status_text = status_text;
        snapshot.error_text = g_session.error_text;
        WriteMultiplayerSessionStatus(
            GetStageRuntimeDirectory(),
            snapshot);
        g_session.last_status_signature = status_signature;
        g_session.last_status_write_ms = now_ms;
    }
}

bool BeginJoinLobby(std::uint64_t lobby_id, bool recovery) {
    if (lobby_id == 0 || g_session.is_host) {
        return false;
    }
    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    if (recovery) {
        if (!g_session.client_lobby_recovery) {
            g_session.recovery_started_ms =
                g_session.steam_servers_connected ? now_ms : 0;
        }
        g_session.client_lobby_recovery = true;
        g_session.recovery_lobby_id = lobby_id;
    } else {
        g_session.client_lobby_recovery = false;
        g_session.recovery_lobby_id = 0;
        g_session.recovery_started_ms = 0;
    }
    g_session.last_join_attempt_ms = now_ms;
    if (!g_session.steam_servers_connected) {
        RemoveAllPeers();
        g_session.lobby_members.clear();
        g_session.lobby_id = 0;
        g_session.host_steam_id = 0;
        g_session.desired_lobby_id = lobby_id;
        g_session.pending_api_call = 0;
        g_session.phase = SteamSessionPhase::Reconnecting;
        g_session.error_text.clear();
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
        if (recovery) {
            g_session.phase = SteamSessionPhase::Reconnecting;
            g_session.error_text.clear();
            Log(
                "Steam multiplayer client lobby rejoin was not queued; "
                "the recovery state machine will retry.");
            return false;
        }
        SetError("Steam rejected the JoinLobby request before it was queued.", false);
        return false;
    }
    g_session.phase = SteamSessionPhase::JoiningLobby;
    g_session.error_text.clear();
    Log(
        std::string(
            recovery
                ? "Steam multiplayer rejoining lobby_id="
                : "Steam multiplayer joining lobby_id=") +
        std::to_string(lobby_id));
    return true;
}

void BeginClientLobbyRecovery(
    std::uint64_t lobby_id,
    std::uint64_t now_ms,
    const char* reason) {
    if (g_session.is_host || lobby_id == 0) {
        return;
    }
    if (!g_session.client_lobby_recovery) {
        g_session.recovery_started_ms =
            g_session.steam_servers_connected ? now_ms : 0;
    }
    g_session.client_lobby_recovery = true;
    g_session.recovery_lobby_id = lobby_id;
    Log(
        "Steam multiplayer client starting lobby recovery. reason=" +
        std::string(reason != nullptr ? reason : "unknown"));
    (void)BeginJoinLobby(lobby_id, true);
}

void ServiceClientLobbyRecovery(std::uint64_t now_ms) {
    if (g_session.is_host ||
        !g_session.client_lobby_recovery ||
        g_session.recovery_lobby_id == 0) {
        return;
    }
    if (!g_session.steam_servers_connected) {
        return;
    }
    if (g_session.recovery_started_ms != 0 &&
        now_ms >= g_session.recovery_started_ms &&
        now_ms - g_session.recovery_started_ms >=
            kClientLobbyRecoveryTimeoutMs) {
        SetError(
            "Steam reconnected, but the authenticated host lobby could not be rejoined.",
            false);
        return;
    }
    if (g_session.last_join_attempt_ms != 0 &&
         now_ms < g_session.last_join_attempt_ms +
             kClientLobbyRecoveryRetryMs) {
        return;
    }
    (void)BeginJoinLobby(g_session.recovery_lobby_id, true);
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

#include "lobby_event_handlers.inl"
