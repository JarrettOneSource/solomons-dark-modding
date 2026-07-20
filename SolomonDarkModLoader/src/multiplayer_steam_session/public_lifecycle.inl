bool InitializeSteamSession() {
    const auto transport = ToLowerAscii(TrimAscii(ReadEnvironmentVariable(kTransportEnvironmentVariable)));
    ResetMultiplayerSessionStatus(GetStageRuntimeDirectory());
    g_session = SteamSessionState{};
    g_session.launch_token =
        TrimAscii(ReadEnvironmentVariable(kLaunchTokenEnvironmentVariable));
    if (transport != "steam") {
        return true;
    }

    const auto mode = ToLowerAscii(TrimAscii(ReadEnvironmentVariable(kSessionModeEnvironmentVariable)));
    const auto role = ToLowerAscii(TrimAscii(ReadEnvironmentVariable(kRoleEnvironmentVariable)));
    g_session.configured = true;
    g_session.is_host = mode == "host" ||
        (mode.empty() && (role.empty() || role == "host" || role == "server"));
    g_session.max_participants = ReadMaxParticipants();
    g_session.lobby_visibility = ReadLobbyVisibility();
    g_session.privacy = LobbyPrivacyToken(g_session.lobby_visibility);
    g_session.open_invite_dialog = ReadBooleanEnvironmentVariable(
        kOpenInviteEnvironmentVariable,
        true);
    TryParseUnsigned64(
        TrimAscii(ReadEnvironmentVariable(kInviteSteamIdEnvironmentVariable)),
        &g_session.invite_steam_id);

    const auto steam = GetSteamBootstrapSnapshot();
    g_session.app_id = steam.app_id;
    g_session.local_steam_id = steam.local_steam_id;
    if (!steam.transport_interfaces_ready || steam.local_steam_id == 0) {
        SetError("Steam transport was requested but SteamAPI is not ready.", false);
        PublishSessionRuntime(GetTickCount64());
        return false;
    }
    g_session.manifest_sha256_text = ToLowerAscii(TrimAscii(
        ReadEnvironmentVariable(kManifestEnvironmentVariable)));
    if (!ParseSha256(
            g_session.manifest_sha256_text,
            &g_session.manifest_sha256)) {
        SetError("Missing or invalid multiplayer build fingerprint.", false);
        PublishSessionRuntime(GetTickCount64());
        return false;
    }

    g_session.initialized = true;
    g_session.overlay_enabled = SteamIsOverlayEnabled();
    g_session.local_session_nonce = GenerateSessionNonce();

    if (g_session.is_host) {
        g_session.pending_api_call = SteamCreateLobby(
            g_session.lobby_visibility,
            static_cast<std::int32_t>(g_session.max_participants));
        if (g_session.pending_api_call == 0) {
            SetError("Steam rejected the CreateLobby request before it was queued.", false);
            PublishSessionRuntime(GetTickCount64());
            return false;
        }
        g_session.phase = SteamSessionPhase::CreatingLobby;
    } else {
        std::uint64_t configured_lobby_id = 0;
        TryParseUnsigned64(
            TrimAscii(ReadEnvironmentVariable(kLobbyIdEnvironmentVariable)),
            &configured_lobby_id);
        if (configured_lobby_id == 0) {
            configured_lobby_id = ParseCommandLineLobbyId();
        }
        if (configured_lobby_id != 0) {
            BeginJoinLobby(configured_lobby_id);
        } else {
            g_session.phase = SteamSessionPhase::WaitingForInvite;
        }
    }
    PublishSessionRuntime(GetTickCount64());
    return g_session.phase != SteamSessionPhase::Error;
}

void ShutdownSteamSession() {
    if (!g_session.initialized) {
        g_session = SteamSessionState{};
        return;
    }
    SendGoodbyeToAuthenticatedPeers(
        g_session.is_host
            ? SessionGoodbyeReason::LobbyClosed
            : SessionGoodbyeReason::Leaving);
    if (g_session.is_host && g_session.lobby_id != 0) {
        SteamSetLobbyJoinable(g_session.lobby_id, false);
        SteamSetLobbyData(g_session.lobby_id, kLobbyStateKey, kLobbyStateClosed);
    }
    if (g_session.lobby_id != 0) {
        SteamLeaveLobby(g_session.lobby_id);
    }
    for (const auto& [steam_id, peer] : g_session.peers) {
        (void)peer;
        SteamCloseNetworkSession(steam_id);
        UnregisterSteamGameplayPeer(steam_id);
    }
    SteamSetRichPresence("connect", nullptr);
    SteamSetRichPresence("status", nullptr);
    g_session = SteamSessionState{};
}

void TickSteamSession(std::uint64_t now_ms) {
    if (!g_session.initialized || g_session.phase == SteamSessionPhase::Disabled) {
        return;
    }
    for (const auto& event : DrainSteamEvents()) {
        HandleSteamEvent(event, now_ms);
    }
    ServiceClientLobbyRecovery(now_ms);
    if (g_session.phase == SteamSessionPhase::Error) {
        PublishSessionRuntime(now_ms);
        return;
    }
    if (!g_session.steam_servers_connected ||
        g_session.phase == SteamSessionPhase::Reconnecting) {
        PublishSessionRuntime(now_ms);
        return;
    }
    if (g_session.lobby_id != 0 &&
        (g_session.last_lobby_reconcile_ms == 0 ||
         now_ms >= g_session.last_lobby_reconcile_ms + kLobbyReconcileIntervalMs)) {
        ReconcileLobbyMembers(now_ms);
    }
    if (g_session.phase == SteamSessionPhase::Error) {
        PublishSessionRuntime(now_ms);
        return;
    }
    RefreshOverlayAndInviteDialog();
    SendClientHello(now_ms);
    SendSessionKeepalives(now_ms);
    PumpNetworkMessages(now_ms);
    ExpireInactivePeers(now_ms);
    RefreshRouteStatus(now_ms);
    PublishSessionRuntime(now_ms);
}

bool IsSteamSessionEnabled() {
    return g_session.initialized;
}
