constexpr std::uint64_t kLocalSessionStatusIntervalMs = 500;

std::string LocalSessionGamePhase(const RuntimeState& runtime) {
    switch (runtime.lobby_session_state) {
    case LobbySessionState::InHub:
        return "hub";
    case LobbySessionState::InBoneyard:
        return !runtime.run_loading_barrier.active ||
                !runtime.run_loading_barrier.released
            ? "loading"
            : "session";
    case LobbySessionState::NotInGame:
    default:
        return runtime.run_end_pending_lobby_return ||
                runtime.game_over.accepted_epoch != 0
            ? "results"
            : "loading";
    }
}

void PublishLocalSessionStatus(
    std::uint64_t now_ms,
    bool force = false) {
    if (!g_local_transport.initialized ||
        g_local_transport.backend !=
            GameplayTransportBackend::LocalUdp ||
        g_local_transport.launch_token.empty()) {
        return;
    }

    const auto runtime = SnapshotRuntimeState();
    const auto authority_id = g_local_transport.is_host
        ? g_local_transport.local_peer_id
        : g_local_transport_authority_participant_id.load(
            std::memory_order_acquire);
    const auto host_id = authority_id != 0
        ? authority_id
        : !g_local_transport.peers.empty()
            ? g_local_transport.peers.front().participant_id
            : std::uint64_t{0};
    const auto lobby_id = g_local_transport.is_host
        ? g_local_transport.local_port
        : g_local_transport.remote_port;

    std::vector<MultiplayerSessionMemberSnapshot> members;
    members.reserve(
        g_local_transport.peers.size() +
        CountBotParticipantSeats(runtime) +
        1);
    MultiplayerSessionMemberSnapshot local;
    local.steam_id = g_local_transport.local_peer_id;
    local.participant_id = g_local_transport.local_peer_id;
    local.name = ReadLocalDisplayName();
    if (local.name.empty()) {
        if (const auto* participant =
                FindLocalParticipant(runtime);
            participant != nullptr) {
            local.name = participant->name;
        }
    }
    if (local.name.empty()) {
        local.name = g_local_transport.is_host
            ? "Local Host"
            : "Local Client";
    }
    const auto local_display_name = local.name;
    local.gameplay_slot = 0;
    local.is_host =
        g_local_transport.is_host ||
        local.participant_id == host_id;
    local.is_local = true;
    members.push_back(std::move(local));

    for (const auto& peer : g_local_transport.peers) {
        MultiplayerSessionMemberSnapshot member;
        member.steam_id = peer.participant_id;
        member.participant_id = peer.participant_id;
        if (const auto* participant =
                FindParticipant(runtime, peer.participant_id);
            participant != nullptr) {
            member.name = participant->name;
        }
        if (member.name.empty()) {
            member.name =
                "Remote Wizard " +
                std::to_string(peer.participant_id);
        }
        member.gameplay_slot = -1;
        member.is_host = peer.participant_id == host_id;
        members.push_back(std::move(member));
    }
    for (const auto& participant : runtime.participants) {
        if (!IsLuaControlledParticipant(participant)) {
            continue;
        }

        MultiplayerSessionMemberSnapshot member;
        member.participant_id = participant.participant_id;
        member.name = participant.name;
        member.gameplay_slot = -1;
        member.is_synthetic = true;
        member.is_bot = true;
        BotSnapshot bot_snapshot;
        if (ReadParticipantSnapshot(
                participant.participant_id,
                &bot_snapshot)) {
            member.gameplay_slot = bot_snapshot.gameplay_slot;
        }
        members.push_back(std::move(member));
    }
    std::sort(
        members.begin(),
        members.end(),
        [](const auto& left, const auto& right) {
            if (left.is_host != right.is_host) {
                return left.is_host;
            }
            if (left.is_local != right.is_local) {
                return left.is_local;
            }
            if (left.is_bot != right.is_bot) {
                return !left.is_bot;
            }
            return left.participant_id < right.participant_id;
        });

    const auto phase = g_local_transport.is_host
        ? g_local_transport.peers.empty()
            ? "LobbyReady"
            : "Connected"
        : g_local_transport.peers.empty()
            ? "Handshaking"
            : "Connected";
    const auto status_text =
        !g_local_transport.clean_end_text.empty()
        ? g_local_transport.clean_end_text
        : "Local loopback multiplayer is connected.";
    std::ostringstream signature;
    signature << phase << '|'
              << lobby_id << '|'
              << host_id << '|'
              << LobbySessionStateLabel(
                     runtime.lobby_session_state)
              << '|' << status_text;
    for (const auto& member : members) {
        signature << '|' << member.participant_id
                  << ':' << member.name
                  << ':' << (member.is_host ? 'h' : '-')
                  << ':' << (member.is_local ? 'l' : '-')
                  << ':' << (member.is_bot ? 'b' : '-')
                  << ':' << member.gameplay_slot;
    }
    const auto current_signature = signature.str();
    if (!force &&
        current_signature ==
            g_local_transport.last_session_status_signature &&
        g_local_transport.last_session_status_write_ms != 0 &&
        now_ms <
            g_local_transport.last_session_status_write_ms +
                kLocalSessionStatusIntervalMs) {
        return;
    }

    MultiplayerSessionStatusSnapshot snapshot;
    snapshot.launch_token = g_local_transport.launch_token;
    snapshot.enabled = true;
    snapshot.is_host = g_local_transport.is_host;
    snapshot.phase = phase;
    snapshot.game_phase = LocalSessionGamePhase(runtime);
    snapshot.session_state =
        LobbySessionStateLabel(runtime.lobby_session_state);
    snapshot.app_id = GetSteamBootstrapSnapshot().app_id;
    snapshot.lobby_id = lobby_id;
    snapshot.host_steam_id = host_id;
    snapshot.local_steam_id =
        g_local_transport.local_peer_id;
    snapshot.persona_name = local_display_name;
    snapshot.privacy = g_local_transport.privacy;
    snapshot.protocol_version = kProtocolVersion;
    snapshot.manifest_sha256 =
        g_local_transport.manifest_sha256;
    snapshot.max_participants =
        g_local_transport.max_participants;
    snapshot.authenticated_peer_count =
        static_cast<std::uint32_t>(
            g_local_transport.peers.size());
    snapshot.members = std::move(members);
    snapshot.status_text = status_text;
    WriteMultiplayerSessionStatus(
        GetStageRuntimeDirectory(),
        snapshot);
    g_local_transport.last_session_status_signature =
        current_signature;
    g_local_transport.last_session_status_write_ms = now_ms;
}
