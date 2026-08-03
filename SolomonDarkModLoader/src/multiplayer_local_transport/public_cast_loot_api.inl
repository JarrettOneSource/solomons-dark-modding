void NotifyLocalWorldActorUnregistered(uintptr_t actor_address) {
    if (!IsLuaModSimulationAuthority() ||
        actor_address == 0) {
        return;
    }

    (void)BuildNativeMinionTerminalTombstone(
        actor_address,
        NativeMinionTerminalReasonNativeDeath,
        static_cast<std::uint64_t>(GetTickCount64()));
    g_local_transport.hub_world_actor_ids_by_address.erase(actor_address);
    g_local_transport.run_host_local_world_actor_ids_by_address.erase(
        actor_address);
    ForgetRetainedRunEnemySnapshotForActor(actor_address);
    ForgetNativeMinionSnapshotForActor(actor_address);
    g_local_transport.run_loot_drop_ids_by_address.erase(actor_address);
}

void NotifyLocalNativeMinionTerminal(
    uintptr_t actor_address,
    NativeMinionTerminalReason reason) {
    if (!g_local_transport.initialized ||
        !g_local_transport.is_host ||
        actor_address == 0) {
        return;
    }
    (void)BuildNativeMinionTerminalTombstone(
        actor_address,
        reason,
        static_cast<std::uint64_t>(GetTickCount64()));
}

void ApplyQueuedSteamGameplayEvents(std::uint64_t now_ms);

void ShutdownLocalTransport() {
    const bool pending_teardown =
        g_local_teardown_requested.exchange(
            false,
            std::memory_order_acq_rel);
    if (g_local_transport.initialized &&
        g_local_transport.backend == GameplayTransportBackend::LocalUdp) {
        const bool teardown_requested =
            pending_teardown ||
            g_local_transport.teardown_requested;
        const bool notify_peers = pending_teardown
            ? g_local_teardown_notify_peers.load(
                std::memory_order_acquire)
            : !g_local_transport.teardown_requested ||
                g_local_transport.teardown_notify_peers;
        if (notify_peers) {
            SendLocalSessionGoodbye(
                pending_teardown
                    ? static_cast<SessionGoodbyeReason>(
                        g_local_teardown_reason.load(
                            std::memory_order_acquire))
                    : teardown_requested
                        ? g_local_transport.teardown_reason
                        : g_local_transport.is_host
                            ? SessionGoodbyeReason::LobbyClosed
                            : SessionGoodbyeReason::Leaving);
        }
    }
    ShutdownLocalDeathProgressionTickHook();
    ShutdownLocalLevelUpOptionRollHook();
    ShutdownDeadLevelUpScreenTickHook();
    ResetRunGameOverState("transport_shutdown");
    ResetRunLoadingBarrierState("transport_shutdown");
    ResetLocalDeathSpectatorState("transport_shutdown");
    ResetWaveRespawnState();
    sdmod::ClearHostLootDropDeactivationState();
    StopLocalUdpIngressWorker();
    if (g_local_transport.socket_handle != INVALID_SOCKET) {
        closesocket(g_local_transport.socket_handle);
    }
    if (g_local_transport.winsock_initialized) {
        WSACleanup();
    }
    g_local_transport = LocalTransportState{};
    g_local_transport_enabled.store(false, std::memory_order_release);
    g_local_transport_is_udp.store(false, std::memory_order_release);
    g_local_transport_host.store(false, std::memory_order_release);
    g_local_transport_teardown_complete.store(
        true,
        std::memory_order_release);
    g_local_transport_authority_participant_id.store(
        0,
        std::memory_order_release);
    g_last_lua_time_control_revision_sent = 0;
    ResetReplicatedLuaTimeControl();
    g_remote_native_progression_reconcile_suppressed_for_test.store(
        0,
        std::memory_order_release);
    g_local_run_exit_latched_nonce.store(0, std::memory_order_release);
    g_local_terminated_run_nonce.store(
        0,
        std::memory_order_release);
    {
        std::lock_guard<std::mutex> lock(g_client_host_run_authorization_mutex);
        g_client_host_run_authorization = ClientHostRunAuthorization{};
    }
    {
        std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
        g_queued_local_cast_events.clear();
        g_queued_local_enemy_damage_claims.clear();
        g_queued_host_participant_vitals_corrections.clear();
        g_queued_host_participant_hit_feedback.clear();
        ClearLocalLootPickupRequestStateLocked();
        g_queued_local_host_powerup_pickups.clear();
        g_queued_local_level_up_choices.clear();
        g_queued_lua_mod_stream_messages.clear();
        g_next_lua_mod_stream_sequence = 1;
        g_queued_authoritative_lua_item_grants.clear();
        g_next_lua_item_grant_request_id = 1;
        g_queued_lua_consumable_uses.clear();
        g_next_lua_consumable_use_id = 1;
        g_queued_lua_registered_spell_casts.clear();
        g_next_lua_registered_spell_cast_request_id = 1;
        g_queued_lua_ui_action_requests.clear();
        g_next_lua_ui_action_request_id = 1;
        g_queued_lua_net_messages.clear();
        g_next_lua_net_message_sequence = 1;
        g_queued_lua_net_message_bytes = 0;
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
    RefreshLocalParticipantFromGameState();
    if (!g_local_transport.initialized) {
        ServiceSyntheticParticipantCastInputs(now_ms);
        return;
    }

    const bool telemetry_enabled = IsNetworkTelemetryEnabled();
    auto stage_started_us = telemetry_enabled
        ? NetworkTelemetryNowMicroseconds()
        : 0;
    const auto finish_stage =
        [telemetry_enabled, &stage_started_us](const char* stage) {
            if (!telemetry_enabled) {
                return;
            }
            const auto finished_us =
                NetworkTelemetryNowMicroseconds();
            RecordNetworkTransportStage(
                stage,
                finished_us - stage_started_us);
            stage_started_us = finished_us;
        };

    if (telemetry_enabled) {
        SetNetworkTransportQueueDepth(
            true,
            SnapshotQueuedTransportEventCountForTelemetry());
    }
    ApplyQueuedSteamGameplayEvents(now_ms);
    finish_stage("steam_events");
    finish_stage("local_participant_refresh");
    RefreshHostSyntheticParticipantSceneIntent();
    RefreshHostWaveRespawnCommand(now_ms);
    RetryHostWaveRespawnCommand(now_ms);
    RefreshLocalMenuPauseRequest(now_ms);
    finish_stage("host_scene_control");
    ReceivePackets(now_ms);
    finish_stage("receive_apply");
    DrainLocalHostModTransferResponses();
    finish_stage("mod_transfer_send");
    if (g_local_teardown_requested.exchange(
            false,
            std::memory_order_acq_rel)) {
        g_local_transport.teardown_reason =
            static_cast<SessionGoodbyeReason>(
                g_local_teardown_reason.load(
                    std::memory_order_acquire));
        g_local_transport.teardown_notify_peers =
            g_local_teardown_notify_peers.load(
                std::memory_order_acquire);
        g_local_transport.teardown_requested = true;
    }
    finish_stage("teardown_request");
    if (g_local_transport.teardown_requested) {
        ServiceLocalTransportTeardown(now_ms);
        if (telemetry_enabled) {
            SetNetworkTransportQueueDepth(
                false,
                SnapshotQueuedTransportEventCountForTelemetry());
        }
        finish_stage("teardown_service");
        return;
    }
    PruneStaleLocalUdpPeers(now_ms);
    ServiceRunLoadingBarrier(now_ms);
    TickLocalDeathSpectator(now_ms);
    RefreshHostRunGameOverCommand();
    RefreshHostSharedGameplayPause(now_ms);
    ProcessCompletedHostLootPickups();
    ProcessQueuedLocalHostPowerupPickups(now_ms);
    ServiceClientHostRunExitFollow(now_ms);
    finish_stage("run_lifecycle");
    ReconcileRemoteParticipantNativeProgression(now_ms);
    ProcessPendingHostPowerupPreparations(now_ms);
    finish_stage("native_reconciliation");
    ProcessPendingHostLevelUpOffers(now_ms);
    ProcessHostLevelUpBarrier(now_ms);
    BroadcastHostLevelUpBarrierState(now_ms, false);
    SendLuaTimeControlUpdate();
    finish_stage("level_up");
    SendLocalState(now_ms);
    SendLocalParticipantFrame(now_ms);
    SendSyntheticParticipantState(now_ms);
    ServiceSyntheticParticipantCastInputs(now_ms);
    SendLocalWaveSummary(now_ms);
    finish_stage("outbound_state");
    SendActiveLocalCastInput(now_ms);
    SendQueuedCastEvents(now_ms);
    SendAirChainSnapshots(now_ms);
    SendSpellEffectSnapshot(now_ms);
    SendLocalEnemyDamageClaims();
    finish_stage("outbound_casts");
    SendQueuedHostParticipantVitalsCorrections(now_ms);
    SendQueuedHostParticipantHitFeedback(now_ms);
    finish_stage("outbound_corrections");
    SendQueuedAuthoritativeLuaItemGrants();
    SendQueuedLuaConsumableUses();
    SendQueuedLuaRegisteredSpellCasts();
    SendLuaRegisteredSpellEffectSnapshots(now_ms);
    SendQueuedLuaUiActionRequests();
    SendQueuedLuaNetMessages();
    SendQueuedLootPickupRequests();
    SendQueuedLevelUpChoices();
    SendLuaModStream(now_ms);
    finish_stage("outbound_lua");
    SendWorldSnapshot(now_ms);
    SendLootSnapshot(now_ms);
    finish_stage("outbound_snapshots");
    PublishLocalTransportRuntimeState();
    if (telemetry_enabled) {
        SetNetworkTransportQueueDepth(
            false,
            SnapshotQueuedTransportEventCountForTelemetry());
    }
    finish_stage("publish");
}

void FlushActiveLocalCastRelease(std::uint64_t now_ms) {
    const auto& active = g_local_transport.active_local_cast_input;
    if (!g_local_transport.initialized ||
        !active.active ||
        IsGameplayMouseLeftDown() ||
        now_ms < active.minimum_hold_until_ms) {
        return;
    }
    SendActiveLocalCastInput(now_ms);
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

std::uint64_t GetLocalTransportAuthorityParticipantId() {
    return g_local_transport_authority_participant_id.load(
        std::memory_order_acquire);
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
    const bool queued = QueueSteamGameplayPeerConnected(
        steam_id,
        authoritative_host);
    if (queued) {
        SetSteamGameplayPeerSendEnabled(steam_id, true);
    }
    return queued;
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
        for (auto& [participant_id, synthetic] :
             g_local_transport.synthetic_participants) {
            (void)participant_id;
            synthetic.last_state_send_ms = 0;
            synthetic.last_frame_send_ms = 0;
        }
    }
    if (!g_local_transport.is_host && authoritative_host) {
        g_local_transport.configured_remote = endpoint;
        g_local_transport.configured_remote_valid = true;
        g_local_transport_authority_participant_id.store(
            steam_id,
            std::memory_order_release);
    }
    return true;
}

void UnregisterSteamGameplayPeer(std::uint64_t steam_id) {
    if (!IsSteamGameplayTransportEnabled() ||
        steam_id == 0 ||
        steam_id == g_local_transport.local_peer_id) {
        return;
    }
    SetSteamGameplayPeerSendEnabled(steam_id, false);
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
        g_local_transport_authority_participant_id.store(
            0,
            std::memory_order_release);
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

bool ShouldPauseMultiplayerGameplayWithoutLuaTime() {
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

bool BeginGameplaySimulationFrame() {
    return BeginLuaTimeSimulationFrame(
        ShouldPauseMultiplayerGameplayWithoutLuaTime());
}

void EndGameplaySimulationFrame() {
    EndLuaTimeSimulationFrame();
}

bool ShouldPauseMultiplayerGameplay() {
    return ShouldPauseMultiplayerGameplayWithoutLuaTime() ||
        ShouldHoldLuaTimeSimulationFrame();
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
    std::vector<std::uint64_t> waiting_participant_ids;
    if (g_local_transport.is_host) {
        waiting_participant_ids = CollectUnresolvedLevelUpOfferParticipantIds();
    } else if (runtime_state.level_up_wait_status.valid &&
               runtime_state.level_up_wait_status.pause_active) {
        waiting_participant_ids = runtime_state.level_up_wait_status.waiting_participant_ids;
    }

    waiting_participant_ids.erase(
        std::remove(
            waiting_participant_ids.begin(),
            waiting_participant_ids.end(),
            g_local_transport.local_peer_id),
        waiting_participant_ids.end());
    if (waiting_participant_ids.empty()) {
        return false;
    }

    *text = BuildLevelUpWaitStatusTextFromIds(waiting_participant_ids);
    return !text->empty();
}
