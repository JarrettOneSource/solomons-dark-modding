bool TryFindLocalRunEnemyByNetworkId(
    std::uint64_t network_actor_id,
    SDModSceneActorState* actor_out) {
    return TryFindLocalRunEnemyByNetworkIdInternal(network_actor_id, actor_out);
}

std::uint64_t GetLocalRunEnemyNetworkActorId(uintptr_t actor_address) {
    return ResolveLocalRunEnemyNetworkActorId(actor_address);
}

void NotifyLocalWorldActorUnregistered(uintptr_t actor_address) {
    if (!g_local_transport.initialized ||
        !g_local_transport.is_host ||
        actor_address == 0) {
        return;
    }

    g_local_transport.hub_world_actor_ids_by_address.erase(actor_address);
    g_local_transport.run_host_local_world_actor_ids_by_address.erase(
        actor_address);
    ForgetRetainedRunEnemySnapshotForActor(actor_address);
    g_local_transport.run_loot_drop_ids_by_address.erase(actor_address);
}

void ResetLocalEnemyDamageClaimObservation(
    std::uint64_t network_actor_id) {
    ResetLocalEnemyDamageClaimObservationInternal(network_actor_id);
}

bool TakeLocalEnemyDamageClaimObservation(
    std::uint64_t network_actor_id,
    LocalEnemyDamageClaimObservation* observation) {
    if (network_actor_id == 0 || observation == nullptr) {
        return false;
    }
    std::lock_guard<std::mutex> lock(
        g_local_enemy_damage_claim_observation_mutex);
    const auto existing =
        g_local_enemy_damage_claim_observations.find(network_actor_id);
    if (existing == g_local_enemy_damage_claim_observations.end() ||
        !existing->second.valid) {
        *observation = LocalEnemyDamageClaimObservation{};
        g_local_enemy_damage_claim_observations.erase(network_actor_id);
        return false;
    }
    *observation = existing->second;
    g_local_enemy_damage_claim_observations.erase(existing);
    return true;
}

void PublishLocalAirChainFrame(
    uintptr_t caster_actor_address,
    const AirChainTargetCapture* targets,
    std::size_t target_count,
    std::size_t target_total_count) {
    QueueLocalAirChainFrameInternal(
        caster_actor_address,
        targets,
        target_count,
        target_total_count);
}

uintptr_t ResolveReplicatedAirChainTarget(
    uintptr_t caster_actor_address,
    std::uint64_t owner_participant_id,
    std::uint16_t target_ordinal,
    uintptr_t fallback_actor_address,
    float source_x,
    float source_y,
    AirChainSourceEndpoint* authoritative_source,
    AirChainTargetEndpoint* authoritative_target) {
    return ResolveReplicatedAirChainTargetInternal(
        caster_actor_address,
        owner_participant_id,
        target_ordinal,
        fallback_actor_address,
        source_x,
        source_y,
        authoritative_source,
        authoritative_target);
}

void RecordReplicatedAirChainSourceOverride(
    std::uint64_t owner_participant_id,
    std::uint16_t target_ordinal,
    bool applied) {
    RecordAirChainSourceOverrideInternal(
        owner_participant_id,
        target_ordinal,
        applied);
}

void RecordReplicatedAirChainTargetOverride(
    std::uint64_t owner_participant_id,
    std::uint16_t target_ordinal,
    bool applied) {
    RecordAirChainTargetOverrideInternal(
        owner_participant_id,
        target_ordinal,
        applied);
}

bool HasLocalPendingLethalEnemyDamageClaim(
    std::uint64_t network_actor_id,
    std::uint64_t now_ms) {
    return HasLocalPendingLethalEnemyDamageClaimInternal(network_actor_id, now_ms);
}

bool HasReplicatedRunEnemyDamageBaseline(std::uint64_t network_actor_id) {
    return IsLocalTransportClient() &&
           network_actor_id != 0 &&
           g_local_transport.last_synced_enemy_hp_by_network_id.find(network_actor_id) !=
               g_local_transport.last_synced_enemy_hp_by_network_id.end();
}

void MarkReplicatedRunEnemyDamageBaseline(
    std::uint64_t network_actor_id,
    float authoritative_hp) {
    if (!IsLocalTransportClient() ||
        network_actor_id == 0 ||
        !std::isfinite(authoritative_hp)) {
        return;
    }
    g_local_transport.last_synced_enemy_hp_by_network_id[network_actor_id] =
        (std::max)(0.0f, authoritative_hp);
}

void ClearReplicatedRunEnemyDamageBaseline(std::uint64_t network_actor_id) {
    if (network_actor_id == 0) {
        return;
    }
    g_local_transport.last_synced_enemy_hp_by_network_id.erase(network_actor_id);
    g_local_transport.last_enemy_claimed_hp_by_network_id.erase(network_actor_id);
    g_local_transport.observed_enemy_damage_by_network_id.erase(network_actor_id);
    g_local_transport.pending_lethal_enemy_damage_claim_until_ms.erase(network_actor_id);
    g_local_transport.rejected_enemy_damage_retry_suppressed_until_ms.erase(network_actor_id);
}

void ObserveReplicatedRunEnemyDamage(
    std::uint64_t network_actor_id,
    float authoritative_hp,
    float local_hp,
    float max_hp,
    float target_position_x,
    float target_position_y,
    bool target_position_optional) {
    ObserveReplicatedRunEnemyDamageInternal(
        network_actor_id,
        authoritative_hp,
        local_hp,
        max_hp,
        target_position_x,
        target_position_y,
        target_position_optional);
}

bool TrySetRunEnemyHealth(uintptr_t actor_address, float hp, float max_hp) {
    return TryWriteRunEnemyHealth(actor_address, hp, max_hp);
}

void ApplyQueuedSteamGameplayEvents(std::uint64_t now_ms);

bool InitializeLocalTransport() {
    if (!ConfigureLocalTransport()) {
        return true;
    }
    ResetSteamGameplayQueues();

    std::random_device random;
    g_local_transport.local_session_nonce =
        (static_cast<std::uint64_t>(random()) << 32) ^
        static_cast<std::uint64_t>(random()) ^
        GetTickCount64() ^
        (static_cast<std::uint64_t>(GetCurrentProcessId()) << 16);
    if (g_local_transport.local_session_nonce == 0) {
        g_local_transport.local_session_nonce = 1;
    }

    if (g_local_transport.backend == GameplayTransportBackend::Steam) {
        if (g_local_transport.local_peer_id == 0) {
            Log("Multiplayer Steam transport requested without an initialized Steam identity.");
            g_local_transport = LocalTransportState{};
            return false;
        }
        g_local_transport.initialized = true;
        Log(
            "Multiplayer Steam gameplay transport initialized. role=" +
            std::string(g_local_transport.is_host ? "host" : "client") +
            " participant_id=" + std::to_string(g_local_transport.local_peer_id) +
            " session_nonce=" +
            std::to_string(g_local_transport.local_session_nonce));
        return true;
    }

    WSADATA data{};
    if (WSAStartup(MAKEWORD(2, 2), &data) != 0) {
        Log("Multiplayer local UDP: WSAStartup failed.");
        g_local_transport = LocalTransportState{};
        return false;
    }
    g_local_transport.winsock_initialized = true;

    g_local_transport.socket_handle = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (g_local_transport.socket_handle == INVALID_SOCKET) {
        Log("Multiplayer local UDP: socket creation failed.");
        ShutdownLocalTransport();
        return false;
    }

    u_long nonblocking = 1;
    if (ioctlsocket(g_local_transport.socket_handle, FIONBIO, &nonblocking) != 0) {
        Log("Multiplayer local UDP: failed to set non-blocking mode.");
        ShutdownLocalTransport();
        return false;
    }

    sockaddr_in bind_address{};
    bind_address.sin_family = AF_INET;
    bind_address.sin_addr.s_addr = htonl(INADDR_ANY);
    bind_address.sin_port = htons(g_local_transport.local_port);
    if (bind(
            g_local_transport.socket_handle,
            reinterpret_cast<const sockaddr*>(&bind_address),
            sizeof(bind_address)) != 0) {
        Log("Multiplayer local UDP: bind failed on port " + std::to_string(g_local_transport.local_port) + ".");
        ShutdownLocalTransport();
        return false;
    }

    g_local_transport.initialized = true;
    std::ostringstream message;
    message << "Multiplayer local UDP transport initialized. role="
            << (g_local_transport.is_host ? "host" : "client")
            << " local_port=" << g_local_transport.local_port
            << " remote=" << g_local_transport.remote_host << ":" << g_local_transport.remote_port
            << " participant_id=" << g_local_transport.local_peer_id;
    message << " session_nonce=" << g_local_transport.local_session_nonce;
    Log(message.str());
    return true;
}

void ShutdownLocalTransport() {
    ShutdownLocalLevelUpOptionRollHook();
    sdmod::ClearHostLootDropDeactivationState();
    if (g_local_transport.socket_handle != INVALID_SOCKET) {
        closesocket(g_local_transport.socket_handle);
    }
    if (g_local_transport.winsock_initialized) {
        WSACleanup();
    }
    g_local_transport = LocalTransportState{};
    g_remote_native_progression_reconcile_suppressed_for_test.store(
        0,
        std::memory_order_release);
    g_local_run_exit_latched_nonce.store(0, std::memory_order_release);
    {
        std::lock_guard<std::mutex> lock(g_client_host_run_authorization_mutex);
        g_client_host_run_authorization = ClientHostRunAuthorization{};
    }
    {
        std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
        g_queued_local_cast_events.clear();
        g_queued_local_enemy_damage_claims.clear();
        g_queued_host_participant_vitals_corrections.clear();
        ClearLocalLootPickupRequestStateLocked();
        g_queued_local_host_powerup_pickups.clear();
        g_queued_local_level_up_choices.clear();
        g_queued_lua_mod_stream_messages.clear();
        g_next_lua_mod_stream_sequence = 1;
        g_queued_authoritative_lua_item_grants.clear();
        g_next_lua_item_grant_request_id = 1;
        g_queued_lua_registered_spell_casts.clear();
        g_next_lua_registered_spell_cast_request_id = 1;
        g_queued_local_air_chain_frame = QueuedLocalAirChainFrame{};
        g_have_queued_local_air_chain_frame = false;
        g_next_local_loot_pickup_request_sequence = 1;
    }
    ResetAirChainRuntimeState();
    ResetSteamGameplayQueues();
    UpdateRuntimeState([](RuntimeState& state) {
        state.shared_gameplay_pause = SharedGameplayPauseRuntimeInfo{};
    });
}

void TickLocalTransport(std::uint64_t now_ms) {
    if (!g_local_transport.initialized) {
        return;
    }

    ApplyQueuedSteamGameplayEvents(now_ms);
    RefreshLocalParticipantFromGameState();
    RefreshLocalMenuPauseRequest(now_ms);
    ReceivePackets(now_ms);
    RefreshHostSharedGameplayPause(now_ms);
    ProcessCompletedHostLootPickups();
    ProcessQueuedLocalHostPowerupPickups(now_ms);
    ServiceClientHostRunExitFollow(now_ms);
    ReconcileRemoteParticipantNativeProgression(now_ms);
    ProcessPendingHostPowerupPreparations(now_ms);
    ProcessPendingHostLevelUpOffers(now_ms);
    ProcessHostLevelUpBarrier(now_ms);
    BroadcastHostLevelUpBarrierState(now_ms, false);
    SendLocalState(now_ms);
    SendLocalParticipantFrame(now_ms);
    SendActiveLocalCastInput(now_ms);
    SendQueuedCastEvents(now_ms);
    SendAirChainSnapshots(now_ms);
    SendSpellEffectSnapshot(now_ms);
    SendLocalEnemyDamageClaims();
    SendQueuedHostParticipantVitalsCorrections(now_ms);
    SendQueuedAuthoritativeLuaItemGrants();
    SendQueuedLuaRegisteredSpellCasts();
    SendQueuedLootPickupRequests();
    SendQueuedLevelUpChoices();
    SendLuaModStream(now_ms);
    SendWorldSnapshot(now_ms);
    SendLootSnapshot(now_ms);
    PublishLocalTransportRuntimeState();
}

bool IsLocalTransportEnabled() {
    return g_local_transport.initialized;
}

bool IsLocalTransportHost() {
    return g_local_transport.initialized && g_local_transport.is_host;
}

bool IsLocalTransportClient() {
    return g_local_transport.initialized && !g_local_transport.is_host;
}

bool TryAuthorizeLocalClientRunSwitch(std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!IsLocalTransportClient()) {
        if (error_message != nullptr) {
            *error_message = "The local participant is not a multiplayer client.";
        }
        return false;
    }

    ClientHostRunAuthorization authorization;
    {
        std::lock_guard<std::mutex> lock(g_client_host_run_authorization_mutex);
        authorization = g_client_host_run_authorization;
    }

    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    if (!authorization.valid ||
        authorization.authority_participant_id == 0 ||
        authorization.run_nonce == 0 ||
        authorization.received_ms == 0 ||
        now_ms > authorization.received_ms + kClientHostRunAuthorizationFreshnessMs) {
        if (error_message != nullptr) {
            *error_message = "No fresh authenticated host run intent is available.";
        }
        return false;
    }

    if (!SetPendingRunGenerationSeed(authorization.run_nonce, error_message)) {
        return false;
    }
    return true;
}

std::uint64_t GetLocalTransportParticipantId() {
    return g_local_transport.initialized ? g_local_transport.local_peer_id : 0;
}

bool IsSteamGameplayTransportEnabled() {
    return g_local_transport.initialized &&
           g_local_transport.backend == GameplayTransportBackend::Steam;
}

bool RegisterSteamGameplayPeer(
    std::uint64_t steam_id,
    bool authoritative_host) {
    if (!IsSteamGameplayTransportEnabled() ||
        steam_id == 0 ||
        steam_id == g_local_transport.local_peer_id ||
        (g_local_transport.is_host && authoritative_host)) {
        return false;
    }
    return QueueSteamGameplayPeerConnected(
        steam_id,
        authoritative_host);
}

bool ApplySteamGameplayPeerConnected(
    std::uint64_t steam_id,
    bool authoritative_host) {
    TransportPeerEndpoint endpoint;
    endpoint.backend = GameplayTransportBackend::Steam;
    endpoint.steam_id = steam_id;
    const bool peer_known = std::any_of(
        g_local_transport.peers.begin(),
        g_local_transport.peers.end(),
        [&](const LocalPeerEndpoint& peer) {
            return SameEndpoint(peer.endpoint, endpoint);
        });
    UpsertPeerEndpoint(endpoint, steam_id, GetTickCount64());
    if (!peer_known) {
        g_local_transport.last_state_checkpoint_send_ms = 0;
    }
    if (!g_local_transport.is_host && authoritative_host) {
        g_local_transport.configured_remote = endpoint;
        g_local_transport.configured_remote_valid = true;
    }
    return true;
}

void UnregisterSteamGameplayPeer(std::uint64_t steam_id) {
    if (!IsSteamGameplayTransportEnabled() ||
        steam_id == 0 ||
        steam_id == g_local_transport.local_peer_id) {
        return;
    }
    QueueSteamGameplayPeerDisconnected(steam_id);
}

void ApplySteamGameplayPeerDisconnected(std::uint64_t steam_id) {
    const bool configured_authority_disconnected =
        g_local_transport.configured_remote_valid &&
        g_local_transport.configured_remote.backend ==
            GameplayTransportBackend::Steam &&
        g_local_transport.configured_remote.steam_id == steam_id;
    g_local_transport.peers.erase(
        std::remove_if(
            g_local_transport.peers.begin(),
            g_local_transport.peers.end(),
            [&](const LocalPeerEndpoint& peer) {
                return peer.endpoint.backend == GameplayTransportBackend::Steam &&
                       peer.endpoint.steam_id == steam_id;
            }),
        g_local_transport.peers.end());
    ResetRemoteParticipantSessionEpoch(
        steam_id,
        configured_authority_disconnected);
    if (configured_authority_disconnected) {
        g_local_transport.configured_remote = TransportPeerEndpoint{};
        g_local_transport.configured_remote_valid = false;
        std::lock_guard<std::mutex> lock(g_client_host_run_authorization_mutex);
        g_client_host_run_authorization = ClientHostRunAuthorization{};
    }
}

bool SubmitSteamGameplayPacket(
    std::uint64_t sender_steam_id,
    const void* data,
    std::size_t size,
    std::uint64_t now_ms,
    bool reliable) {
    if (!IsSteamGameplayTransportEnabled() ||
        sender_steam_id == 0 ||
        data == nullptr ||
        size < sizeof(PacketHeader) ||
        size > sizeof(TransportPacketBuffer)) {
        return false;
    }
    return QueueSteamGameplayPacketReceived(
        sender_steam_id,
        data,
        size,
        now_ms,
        reliable);
}

bool ApplySteamGameplayPacketReceived(
    std::uint64_t sender_steam_id,
    const void* data,
    std::size_t size,
    std::uint64_t now_ms) {
    const auto peer_it = std::find_if(
        g_local_transport.peers.begin(),
        g_local_transport.peers.end(),
        [&](const LocalPeerEndpoint& peer) {
            return peer.endpoint.backend == GameplayTransportBackend::Steam &&
                   peer.endpoint.steam_id == sender_steam_id;
        });
    if (peer_it == g_local_transport.peers.end()) {
        return false;
    }
    if (!IsAuthorizedSteamGameplayPacket(
            sender_steam_id,
            data,
            size)) {
        Log(
            "Multiplayer Steam gameplay packet rejected for sender ownership. steam_id=" +
            std::to_string(sender_steam_id));
        return false;
    }

    TransportPacketBuffer packet_buffer{};
    std::memcpy(packet_buffer.data(), data, size);
    DispatchReceivedPacket(
        packet_buffer,
        static_cast<int>(size),
        peer_it->endpoint,
        now_ms);
    return true;
}

void ApplyQueuedSteamGameplayEvents(std::uint64_t now_ms) {
    for (auto& event : DrainSteamGameplayInboundEvents()) {
        switch (event.kind) {
        case SteamGameplayInboundEventKind::PeerConnected:
            ApplySteamGameplayPeerConnected(
                event.steam_id,
                event.authoritative_host);
            break;
        case SteamGameplayInboundEventKind::PeerDisconnected:
            ApplySteamGameplayPeerDisconnected(event.steam_id);
            break;
        case SteamGameplayInboundEventKind::PacketReceived:
            ApplySteamGameplayPacketReceived(
                event.steam_id,
                event.payload.data(),
                event.payload.size(),
                event.received_ms != 0 ? event.received_ms : now_ms);
            break;
        }
    }
}

void QueueHostParticipantVitalsCorrection(
    std::uint64_t target_participant_id,
    float life_current,
    float life_max,
    std::uint8_t transient_status_flags,
    std::int32_t poison_remaining_ticks,
    float poison_damage_per_tick,
    std::int32_t webbed_remaining_ticks,
    float webbed_strength,
    std::uint8_t correction_flags,
    float magic_shield_absorb_remaining,
    float magic_shield_absorb_capacity,
    float magic_shield_explosion_fraction,
    float magic_shield_hit_flash) {
    QueueHostParticipantVitalsCorrectionInternal(
        target_participant_id,
        life_current,
        life_max,
        transient_status_flags,
        poison_remaining_ticks,
        poison_damage_per_tick,
        webbed_remaining_ticks,
        webbed_strength,
        correction_flags,
        magic_shield_absorb_remaining,
        magic_shield_absorb_capacity,
        magic_shield_explosion_fraction,
        magic_shield_hit_flash);
}

bool HasAuthoritativeHagathaRuntimeStateChanged(
    std::uint64_t target_participant_id) {
    return HasAuthoritativeHagathaRuntimeStateChangedInternal(
        target_participant_id);
}

bool ShouldPauseMultiplayerGameplay() {
    if (!g_local_transport.initialized) {
        return false;
    }

    const auto runtime_state = SnapshotRuntimeState();
    if (HasPendingLocalLevelUpChoice(runtime_state)) {
        return true;
    }

    if (g_local_transport.is_host) {
        if (!CollectUnresolvedLevelUpOfferParticipantIds().empty()) {
            return true;
        }
    } else {
        const auto& wait_status = runtime_state.level_up_wait_status;
        if (wait_status.valid && wait_status.pause_active) {
            return true;
        }
    }

    return ShouldPauseForSharedGameplayMenu();
}

bool HasLocalLevelUpOfferAwaitingNativePresentation() {
    if (!IsLocalTransportClient() && !IsLocalTransportHost()) {
        return false;
    }

    return HasPendingLocalLevelUpChoice(SnapshotRuntimeState());
}

bool TryBuildLevelUpWaitStatusText(std::string* text) {
    if (text != nullptr) {
        text->clear();
    }
    if (text == nullptr || !g_local_transport.initialized) {
        return false;
    }

    const auto runtime_state = SnapshotRuntimeState();
    if (HasPendingLocalLevelUpChoice(runtime_state)) {
        *text = "Choose your skill upgrade";
        return true;
    }

    std::vector<std::uint64_t> waiting_participant_ids;
    if (g_local_transport.is_host) {
        waiting_participant_ids = CollectUnresolvedLevelUpOfferParticipantIds();
    } else if (runtime_state.level_up_wait_status.valid &&
               runtime_state.level_up_wait_status.pause_active) {
        waiting_participant_ids = runtime_state.level_up_wait_status.waiting_participant_ids;
    }

    if (waiting_participant_ids.empty()) {
        return false;
    }

    *text = BuildLevelUpWaitStatusTextFromIds(waiting_participant_ids);
    return !text->empty();
}
