bool TryFindLocalRunEnemyByNetworkId(
    std::uint64_t network_actor_id,
    SDModSceneActorState* actor_out) {
    return TryFindLocalRunEnemyByNetworkIdInternal(network_actor_id, actor_out);
}

std::uint64_t GetLocalRunEnemyNetworkActorId(uintptr_t actor_address) {
    return ResolveLocalRunEnemyNetworkActorId(actor_address);
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

bool InitializeLocalTransport() {
    if (!ConfigureLocalTransport()) {
        return true;
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
            " participant_id=" + std::to_string(g_local_transport.local_peer_id));
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
    Log(message.str());
    return true;
}

void ShutdownLocalTransport() {
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
    {
        std::lock_guard<std::mutex> lock(g_client_host_run_authorization_mutex);
        g_client_host_run_authorization = ClientHostRunAuthorization{};
    }
    {
        std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
        g_queued_local_cast_events.clear();
        g_queued_local_enemy_damage_claims.clear();
        g_queued_host_participant_vitals_corrections.clear();
        g_queued_local_loot_pickup_requests.clear();
        g_queued_local_level_up_choices.clear();
        g_queued_local_air_chain_frame = QueuedLocalAirChainFrame{};
        g_have_queued_local_air_chain_frame = false;
        g_next_local_loot_pickup_request_sequence = 1;
    }
    ResetAirChainRuntimeState();
}

void TickLocalTransport(std::uint64_t now_ms) {
    if (!g_local_transport.initialized) {
        return;
    }

    RefreshLocalParticipantFromGameState();
    ReceivePackets(now_ms);
    ReconcileRemoteParticipantNativeProgression(now_ms);
    ProcessPendingHostLevelUpOffers(now_ms);
    SendLocalState(now_ms);
    SendActiveLocalCastInput(now_ms);
    SendQueuedCastEvents(now_ms);
    SendAirChainSnapshots(now_ms);
    SendSpellEffectSnapshot(now_ms);
    SendLocalEnemyDamageClaims();
    SendQueuedHostParticipantVitalsCorrections(now_ms);
    SendQueuedLootPickupRequests();
    SendQueuedLevelUpChoices();
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
    TransportPeerEndpoint endpoint;
    endpoint.backend = GameplayTransportBackend::Steam;
    endpoint.steam_id = steam_id;
    UpsertPeerEndpoint(endpoint, steam_id, GetTickCount64());
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
    std::uint64_t now_ms) {
    if (!IsSteamGameplayTransportEnabled() ||
        sender_steam_id == 0 ||
        data == nullptr ||
        size < sizeof(PacketHeader) ||
        size > sizeof(WorldSnapshotPacket)) {
        return false;
    }
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

void QueueHostParticipantVitalsCorrection(
    std::uint64_t target_participant_id,
    float life_current,
    float life_max,
    std::uint8_t transient_status_flags,
    std::int32_t poison_remaining_ticks,
    float poison_damage_per_tick) {
    QueueHostParticipantVitalsCorrectionInternal(
        target_participant_id,
        life_current,
        life_max,
        transient_status_flags,
        poison_remaining_ticks,
        poison_damage_per_tick);
}

bool ShouldPauseGameplayForLevelUpSelection() {
    if (!g_local_transport.initialized) {
        return false;
    }

    const auto runtime_state = SnapshotRuntimeState();
    if (HasPendingLocalLevelUpChoice(runtime_state)) {
        return true;
    }

    if (g_local_transport.is_host) {
        return !CollectUnresolvedLevelUpOfferParticipantIds().empty();
    }

    const auto& wait_status = runtime_state.level_up_wait_status;
    return wait_status.valid &&
           wait_status.pause_active &&
           !wait_status.waiting_participant_ids.empty();
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

    *text = BuildLevelUpWaitStatusTextFromIds(runtime_state, waiting_participant_ids);
    return !text->empty();
}

std::uint64_t QueueLocalCastEventInternal(
    CastKind cast_kind,
    std::int32_t secondary_slot,
    std::int32_t skill_id,
    float position_x,
    float position_y,
    float direction_x,
    float direction_y,
    std::uint64_t target_network_actor_id,
    uintptr_t target_actor_address,
    std::uint32_t hold_frames,
    bool has_aim_target,
    float aim_target_x,
    float aim_target_y,
    const std::int32_t* live_secondary_entry_indices,
    std::size_t live_secondary_entry_count) {
    if (skill_id < 0 ||
        (cast_kind != CastKind::Primary && cast_kind != CastKind::Secondary) ||
        (cast_kind == CastKind::Primary && secondary_slot != -1) ||
        (cast_kind == CastKind::Secondary &&
         (secondary_slot < 0 ||
          secondary_slot >=
              static_cast<std::int32_t>(kSecondaryLoadoutSlotCount))) ||
        !std::isfinite(position_x) ||
        !std::isfinite(position_y) ||
        !std::isfinite(direction_x) ||
        !std::isfinite(direction_y)) {
        return 0;
    }
    if (has_aim_target &&
        !IsUsableLocalCastAimTarget(position_x, position_y, aim_target_x, aim_target_y)) {
        has_aim_target = false;
        aim_target_x = 0.0f;
        aim_target_y = 0.0f;
    }

    std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
    constexpr std::size_t kMaxQueuedLocalCastEvents = 16;
    if (g_queued_local_cast_events.size() >= kMaxQueuedLocalCastEvents) {
        g_queued_local_cast_events.erase(g_queued_local_cast_events.begin());
    }
    QueuedLocalCastEvent event;
    event.native_queue_id = g_next_local_cast_event_id++;
    if (g_next_local_cast_event_id == 0) {
        g_next_local_cast_event_id = 1;
    }
    event.cast_kind = cast_kind;
    event.secondary_slot = secondary_slot;
    event.skill_id = skill_id;
    if (cast_kind == CastKind::Secondary &&
        live_secondary_entry_indices != nullptr &&
        live_secondary_entry_count == event.live_secondary_entry_indices.size()) {
        std::copy_n(
            live_secondary_entry_indices,
            live_secondary_entry_count,
            event.live_secondary_entry_indices.begin());
        event.has_live_secondary_loadout =
            event.live_secondary_entry_indices[
                static_cast<std::size_t>(secondary_slot)] == skill_id;
    }
    event.target_network_actor_id = target_network_actor_id;
    event.target_actor_address = target_actor_address;
    if (hold_frames > 0) {
        constexpr std::uint64_t kApproximateFrameMs = 16;
        event.minimum_hold_until_ms =
            static_cast<std::uint64_t>(GetTickCount64()) +
            static_cast<std::uint64_t>(hold_frames) * kApproximateFrameMs;
    }
    event.position_x = position_x;
    event.position_y = position_y;
    event.direction_x = direction_x;
    event.direction_y = direction_y;
    event.has_aim_target = has_aim_target;
    event.aim_target_x = aim_target_x;
    event.aim_target_y = aim_target_y;
    g_queued_local_cast_events.push_back(event);
    return event.native_queue_id;
}

std::uint64_t QueueLocalSpellCastEvent(
    std::int32_t skill_id,
    float position_x,
    float position_y,
    float direction_x,
    float direction_y,
    std::uint64_t target_network_actor_id,
    uintptr_t target_actor_address,
    std::uint32_t hold_frames,
    bool has_aim_target,
    float aim_target_x,
    float aim_target_y) {
    return QueueLocalCastEventInternal(
        CastKind::Primary,
        -1,
        skill_id,
        position_x,
        position_y,
        direction_x,
        direction_y,
        target_network_actor_id,
        target_actor_address,
        hold_frames,
        has_aim_target,
        aim_target_x,
        aim_target_y,
        nullptr,
        0);
}

std::uint64_t QueueLocalSecondarySpellCastEvent(
    std::int32_t skill_id,
    std::int32_t secondary_slot,
    float position_x,
    float position_y,
    float direction_x,
    float direction_y,
    std::uint64_t target_network_actor_id,
    uintptr_t target_actor_address,
    bool has_aim_target,
    float aim_target_x,
    float aim_target_y,
    const std::int32_t* live_secondary_entry_indices,
    std::size_t live_secondary_entry_count) {
    return QueueLocalCastEventInternal(
        CastKind::Secondary,
        secondary_slot,
        skill_id,
        position_x,
        position_y,
        direction_x,
        direction_y,
        target_network_actor_id,
        target_actor_address,
        0,
        has_aim_target,
        aim_target_x,
        aim_target_y,
        live_secondary_entry_indices,
        live_secondary_entry_count);
}

void QueueLocalEnemyDamageClaim(
    std::uint64_t network_actor_id,
    std::int32_t skill_id,
    float authoritative_hp,
    float local_hp,
    float max_hp,
    float target_position_x,
    float target_position_y,
    bool target_position_optional) {
    if (network_actor_id == 0 ||
        !std::isfinite(authoritative_hp) ||
        !std::isfinite(local_hp) ||
        !std::isfinite(max_hp) ||
        max_hp <= 0.0f ||
        !std::isfinite(target_position_x) ||
        !std::isfinite(target_position_y) ||
        local_hp + kEnemyDamageClaimHpEpsilon >= authoritative_hp) {
        return;
    }

    std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
    constexpr std::size_t kMaxQueuedLocalEnemyDamageClaims = 32;
    if (g_queued_local_enemy_damage_claims.size() >= kMaxQueuedLocalEnemyDamageClaims) {
        g_queued_local_enemy_damage_claims.erase(g_queued_local_enemy_damage_claims.begin());
    }
    QueuedLocalEnemyDamageClaim claim;
    claim.network_actor_id = network_actor_id;
    claim.skill_id = skill_id;
    claim.authoritative_hp = authoritative_hp;
    claim.local_hp = local_hp;
    claim.max_hp = max_hp;
    claim.target_position_x = target_position_x;
    claim.target_position_y = target_position_y;
    claim.target_position_optional = target_position_optional;
    claim.baseline_prevalidated =
        !IsLocalTransportClient() ||
        HasReplicatedRunEnemyDamageBaseline(network_actor_id);
    g_queued_local_enemy_damage_claims.push_back(claim);
    if (local_hp <= kEnemyDamageClaimHpEpsilon && IsLocalTransportClient()) {
        g_local_transport.pending_lethal_enemy_damage_claim_until_ms[network_actor_id] =
            static_cast<std::uint64_t>(GetTickCount64()) +
            kEnemyDamageLethalClaimPendingSuppressMs;
    }
}

void NotifyLocalRunEnemyDeath(uintptr_t actor_address) {
    if (!g_local_transport.initialized ||
        !g_local_transport.is_host ||
        actor_address == 0) {
        return;
    }

    SDModSceneActorState actor;
    if (!TryGetRunEnemyActorForDeathSnapshotByAddress(actor_address, &actor)) {
        return;
    }

    const auto network_actor_id = ResolveLocalRunEnemyNetworkActorId(actor);
    if (network_actor_id == 0) {
        return;
    }

    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    RecordRecentRunEnemyDeathSnapshot(network_actor_id, actor, now_ms);
    Log(
        "world_snapshot: recorded host run enemy death snapshot from native hook. actor=" +
        HexString(actor.actor_address) +
        " network_actor_id=" + std::to_string(network_actor_id) +
        " type=" + HexString(static_cast<uintptr_t>(actor.object_type_id)) +
        " enemy_type=" + std::to_string(actor.enemy_type) +
        " hp=" + std::to_string(actor.hp) +
        " max_hp=" + std::to_string(actor.max_hp));
}

bool QueueLocalLootPickupRequest(
    std::uint64_t network_drop_id,
    std::uint32_t* request_sequence,
    std::string* error_message,
    const LootPickupRequestCapture* capture) {
    if (request_sequence != nullptr) {
        *request_sequence = 0;
    }
    auto fail = [&](const char* message) {
        if (error_message != nullptr) {
            *error_message = message;
        }
        return false;
    };

    if (!IsLocalTransportEnabled()) {
        return fail("local transport is not enabled");
    }
    if (!IsLocalTransportClient()) {
        return fail("loot pickup requests are currently client-to-host only");
    }
    if (network_drop_id == 0) {
        return fail("network_drop_id must be non-zero");
    }

    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);
    if (local == nullptr ||
        !local->runtime.valid ||
        !local->runtime.in_run ||
        local->runtime.scene_intent.kind != ParticipantSceneIntentKind::Run) {
        return fail("local participant is not in a run");
    }
    const LootDropSnapshot* queued_drop =
        runtime_state.loot_snapshot.valid &&
                runtime_state.loot_snapshot.scene_intent.kind == ParticipantSceneIntentKind::Run
            ? FindLootDropSnapshotByNetworkId(runtime_state.loot_snapshot, network_drop_id)
            : nullptr;
    const bool present_in_loot_snapshot = queued_drop != nullptr;
    const bool matches_recent_pickup_result =
        runtime_state.last_loot_pickup_result.valid &&
        runtime_state.last_loot_pickup_result.network_drop_id == network_drop_id;
    if (!present_in_loot_snapshot && !matches_recent_pickup_result) {
        return fail("network_drop_id is not present in the replicated loot snapshot");
    }

    std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
    constexpr std::size_t kMaxQueuedLocalLootPickupRequests = 32;
    if (g_queued_local_loot_pickup_requests.size() >= kMaxQueuedLocalLootPickupRequests) {
        g_queued_local_loot_pickup_requests.erase(g_queued_local_loot_pickup_requests.begin());
    }

    QueuedLocalLootPickupRequest request;
    request.network_drop_id = network_drop_id;
    request.request_sequence = g_next_local_loot_pickup_request_sequence++;
    if (g_next_local_loot_pickup_request_sequence == 0) {
        g_next_local_loot_pickup_request_sequence = 1;
    }
    LootPickupRequestCapture resolved_capture{};
    if (capture != nullptr && capture->valid) {
        resolved_capture = *capture;
    } else if (present_in_loot_snapshot) {
        SDModPlayerState player_state;
        if (TryGetPlayerState(&player_state) && player_state.valid) {
            resolved_capture.valid = true;
            resolved_capture.requester_position_x = player_state.x;
            resolved_capture.requester_position_y = player_state.y;
            resolved_capture.drop_position_x = queued_drop->position_x;
            resolved_capture.drop_position_y = queued_drop->position_y;
        }
    }
    if (resolved_capture.valid &&
        std::isfinite(resolved_capture.requester_position_x) &&
        std::isfinite(resolved_capture.requester_position_y) &&
        std::isfinite(resolved_capture.drop_position_x) &&
        std::isfinite(resolved_capture.drop_position_y)) {
        request.has_pickup_positions = true;
        request.requester_position_x = resolved_capture.requester_position_x;
        request.requester_position_y = resolved_capture.requester_position_y;
        request.drop_position_x = resolved_capture.drop_position_x;
        request.drop_position_y = resolved_capture.drop_position_y;
    }
    if (request_sequence != nullptr) {
        *request_sequence = request.request_sequence;
    }
    g_queued_local_loot_pickup_requests.push_back(request);
    return true;
}
