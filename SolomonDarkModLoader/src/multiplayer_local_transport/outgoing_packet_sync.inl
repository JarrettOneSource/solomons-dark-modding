SteamNetworkSendMode SteamSendModeForPacket(const void* packet, std::size_t packet_size) {
    if (packet == nullptr || packet_size < sizeof(PacketHeader)) {
        return SteamNetworkSendMode::ReliableNoNagle;
    }
    PacketHeader header{};
    std::memcpy(&header, packet, sizeof(header));
    const auto kind = static_cast<PacketKind>(header.kind);
    if (kind == PacketKind::Cast && packet_size == sizeof(CastPacket)) {
        CastPacket cast{};
        std::memcpy(&cast, packet, sizeof(cast));
        return cast.input_phase == static_cast<std::uint8_t>(CastInputPhase::Held)
            ? SteamNetworkSendMode::UnreliableNoDelay
            : SteamNetworkSendMode::ReliableNoNagle;
    }
    switch (kind) {
    case PacketKind::State:
    case PacketKind::WorldSnapshot:
    case PacketKind::LootSnapshot:
    case PacketKind::SpellEffectSnapshot:
    case PacketKind::AirChainSnapshot:
        return SteamNetworkSendMode::UnreliableNoDelay;
    default:
        return SteamNetworkSendMode::ReliableNoNagle;
    }
}
void SendBufferToEndpoint(
    const void* packet,
    std::size_t packet_size,
    const TransportPeerEndpoint& endpoint) {
    if (packet == nullptr || packet_size == 0 || packet_size > static_cast<std::size_t>((std::numeric_limits<int>::max)())) {
        return;
    }
    if (endpoint.backend == GameplayTransportBackend::Steam) {
        std::int32_t result_code = 0;
        if (SteamSendNetworkMessage(
                endpoint.steam_id,
                packet,
                packet_size,
                SteamSendModeForPacket(packet, packet_size),
                &result_code)) {
            g_local_transport.packets_sent += 1;
        }
        return;
    }
    const int sent = sendto(
        g_local_transport.socket_handle,
        reinterpret_cast<const char*>(packet),
        static_cast<int>(packet_size),
        0,
        reinterpret_cast<const sockaddr*>(&endpoint.udp_address),
        sizeof(endpoint.udp_address));
    if (sent == static_cast<int>(packet_size)) {
        g_local_transport.packets_sent += 1;
    }
}

template <typename Packet>
void SendPacketToEndpoint(const Packet& packet, const TransportPeerEndpoint& endpoint) {
    SendBufferToEndpoint(&packet, sizeof(packet), endpoint);
}

void PublishWorldSnapshotRuntimeInfo(const WorldSnapshotPacket& packet, std::uint64_t now_ms);
bool PublishLootSnapshotRuntimeInfo(const LootSnapshotPacket& packet, std::uint64_t now_ms);
int ApplyHostAcceptedFireballExplodeSplash(
    const EnemyDamageClaimPacket& packet,
    const ParticipantInfo* participant,
    std::uint64_t now_ms,
    const SDModSceneActorState& primary_target);
void CaptureHostLocalFireballExplodeBaseline(
    const ParticipantInfo& local,
    const CastPacket& packet,
    std::uint64_t now_ms);
void ReconcileHostLocalFireballExplodeSplash(std::uint64_t now_ms);

void SendLocalState(std::uint64_t now_ms) {
    if (now_ms - g_local_transport.last_send_ms < kLocalTransportSendIntervalMs) {
        return;
    }
    g_local_transport.last_send_ms = now_ms;

    const auto packet = BuildLocalStatePacket();
    if (packet.transform_valid == 0 &&
        !(g_local_transport.is_host && packet.run_nonce != 0 && packet.in_run == 0)) {
        return;
    }

    const auto endpoints = BuildKnownSendEndpoints();
    for (const auto& endpoint : endpoints) {
        SendPacketToEndpoint(packet, endpoint);
    }
}

void SendWorldSnapshot(std::uint64_t now_ms) {
    if (!g_local_transport.is_host ||
        now_ms - g_local_transport.last_world_snapshot_send_ms < kLocalTransportWorldSnapshotIntervalMs) {
        return;
    }
    g_local_transport.last_world_snapshot_send_ms = now_ms;

    ReconcileHostLocalFireballExplodeSplash(now_ms);

    WorldSnapshotPacket packet{};
    if (!BuildLocalWorldSnapshotPacket(&packet)) {
        return;
    }
    const auto scene_kind = static_cast<WorldSceneKind>(packet.scene_kind);
    if (packet.actor_count == 0 && scene_kind != WorldSceneKind::Run) {
        return;
    }

    PublishWorldSnapshotRuntimeInfo(packet, now_ms);

    const auto endpoints = BuildKnownSendEndpoints();
    for (const auto& endpoint : endpoints) {
        SendPacketToEndpoint(packet, endpoint);
    }
}

void SendLootSnapshot(std::uint64_t now_ms) {
    if (!g_local_transport.is_host) {
        return;
    }

    LootSnapshotPacket packet{};
    if (!BuildLocalLootSnapshotPacket(&packet)) {
        return;
    }

    const auto send_interval_ms = LootSnapshotIntervalForPacket(packet);
    if (now_ms - g_local_transport.last_loot_snapshot_send_ms < send_interval_ms) {
        return;
    }
    g_local_transport.last_loot_snapshot_send_ms = now_ms;

    PublishLootSnapshotRuntimeInfo(packet, now_ms);

    const auto endpoints = BuildKnownSendEndpoints();
    for (const auto& endpoint : endpoints) {
        SendPacketToEndpoint(packet, endpoint);
    }
}

std::vector<QueuedLocalLootPickupRequest> TakeQueuedLocalLootPickupRequests() {
    std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
    std::vector<QueuedLocalLootPickupRequest> requests;
    requests.swap(g_queued_local_loot_pickup_requests);
    return requests;
}

const LootDropSnapshot* FindLootDropSnapshotByNetworkId(
    const LootSnapshotRuntimeInfo& snapshot,
    std::uint64_t network_drop_id) {
    for (const auto& drop : snapshot.drops) {
        if (drop.network_drop_id == network_drop_id) {
            return &drop;
        }
    }
    return nullptr;
}

void SendQueuedLootPickupRequests() {
    if (!IsLocalTransportClient()) {
        return;
    }

    auto requests = TakeQueuedLocalLootPickupRequests();
    if (requests.empty()) {
        return;
    }

    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);
    if (local == nullptr ||
        !local->runtime.valid ||
        !local->runtime.in_run ||
        local->runtime.scene_intent.kind != ParticipantSceneIntentKind::Run ||
        !runtime_state.loot_snapshot.valid ||
        runtime_state.loot_snapshot.scene_intent.kind != ParticipantSceneIntentKind::Run) {
        return;
    }
    if (runtime_state.loot_snapshot.run_nonce != 0 &&
        local->runtime.run_nonce != 0 &&
        runtime_state.loot_snapshot.run_nonce != local->runtime.run_nonce) {
        return;
    }

    const auto endpoints = BuildKnownSendEndpoints();
    if (endpoints.empty()) {
        return;
    }

    for (const auto& request : requests) {
        const auto* drop =
            FindLootDropSnapshotByNetworkId(runtime_state.loot_snapshot, request.network_drop_id);
        const bool have_recent_pickup_result =
            runtime_state.last_loot_pickup_result.valid &&
            runtime_state.last_loot_pickup_result.network_drop_id == request.network_drop_id;
        if (drop == nullptr && !have_recent_pickup_result) {
            Log(
                "Multiplayer loot pickup request skipped; replicated drop not found. network_drop_id=" +
                std::to_string(request.network_drop_id) +
                " request_sequence=" + std::to_string(request.request_sequence));
            continue;
        }

        LootPickupRequestPacket packet{};
        packet.header = MakePacketHeader(PacketKind::LootPickupRequest, g_local_transport.next_sequence++);
        packet.participant_id = g_local_transport.local_peer_id;
        packet.request_sequence = request.request_sequence;
        packet.run_nonce = local->runtime.run_nonce != 0
                               ? local->runtime.run_nonce
                               : runtime_state.loot_snapshot.run_nonce;
        packet.network_drop_id = request.network_drop_id;
        packet.requester_position_x =
            request.has_pickup_positions ? request.requester_position_x : local->runtime.position_x;
        packet.requester_position_y =
            request.has_pickup_positions ? request.requester_position_y : local->runtime.position_y;
        packet.drop_position_x =
            request.has_pickup_positions
                ? request.drop_position_x
                : (drop != nullptr ? drop->position_x : local->runtime.position_x);
        packet.drop_position_y =
            request.has_pickup_positions
                ? request.drop_position_y
                : (drop != nullptr ? drop->position_y : local->runtime.position_y);

        for (const auto& endpoint : endpoints) {
            SendPacketToEndpoint(packet, endpoint);
        }
        Log(
            "Multiplayer loot pickup request sent. participant_id=" +
            std::to_string(packet.participant_id) +
            " request_sequence=" + std::to_string(packet.request_sequence) +
            " network_drop_id=" + std::to_string(packet.network_drop_id) +
            " requester_pos=(" + std::to_string(packet.requester_position_x) + "," +
            std::to_string(packet.requester_position_y) + ")" +
            " drop_pos=(" + std::to_string(packet.drop_position_x) + "," +
            std::to_string(packet.drop_position_y) + ")" +
            " captured_positions=" + std::to_string(request.has_pickup_positions ? 1 : 0));
    }
}

template <typename Packet>
void SendPacketToParticipantOrPeers(const Packet& packet, std::uint64_t participant_id) {
    bool sent_to_target = false;
    for (const auto& peer : g_local_transport.peers) {
        if (peer.participant_id != participant_id) {
            continue;
        }
        SendPacketToEndpoint(packet, peer.endpoint);
        sent_to_target = true;
    }
    if (sent_to_target) {
        return;
    }

    const auto endpoints = BuildKnownSendEndpoints();
    for (const auto& endpoint : endpoints) {
        SendPacketToEndpoint(packet, endpoint);
    }
}

std::vector<QueuedLocalLevelUpChoice> TakeQueuedLocalLevelUpChoices() {
    std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
    std::vector<QueuedLocalLevelUpChoice> choices;
    choices.swap(g_queued_local_level_up_choices);
    return choices;
}

bool TryResolveOfferedLevelUpOption(
    const std::vector<LevelUpChoiceOptionState>& options,
    std::int32_t option_index,
    std::int32_t option_id,
    LevelUpChoiceOptionState* resolved) {
    if (resolved != nullptr) {
        *resolved = LevelUpChoiceOptionState{};
    }
    if (option_index > 0) {
        const auto zero_based_index = static_cast<std::size_t>(option_index - 1);
        if (zero_based_index >= options.size()) {
            return false;
        }
        if (option_id >= 0 && options[zero_based_index].option_id != option_id) {
            return false;
        }
        if (resolved != nullptr) {
            *resolved = options[zero_based_index];
        }
        return true;
    }
    if (option_id >= 0) {
        const auto it = std::find_if(
            options.begin(),
            options.end(),
            [&](const LevelUpChoiceOptionState& option) {
                return option.option_id == option_id;
            });
        if (it == options.end()) {
            return false;
        }
        if (resolved != nullptr) {
            *resolved = *it;
        }
        return true;
    }
    return false;
}

LevelUpChoiceOptionState ToRuntimeLevelUpOption(const BotSkillChoiceOption& option) {
    LevelUpChoiceOptionState state;
    state.option_id = option.option_id;
    state.apply_count = option.apply_count;
    return state;
}

bool TryResolveIssuedLevelUpOption(
    const IssuedLevelUpOffer& offer,
    std::int32_t option_index,
    std::int32_t option_id,
    BotSkillChoiceOption* resolved) {
    if (resolved != nullptr) {
        *resolved = BotSkillChoiceOption{};
    }
    if (option_index > 0) {
        const auto zero_based_index = static_cast<std::size_t>(option_index - 1);
        if (zero_based_index >= offer.options.size()) {
            return false;
        }
        if (option_id >= 0 && offer.options[zero_based_index].option_id != option_id) {
            return false;
        }
        if (resolved != nullptr) {
            *resolved = offer.options[zero_based_index];
        }
        return true;
    }
    if (option_id >= 0) {
        const auto it = std::find_if(
            offer.options.begin(),
            offer.options.end(),
            [&](const BotSkillChoiceOption& option) {
                return option.option_id == option_id;
            });
        if (it == offer.options.end()) {
            return false;
        }
        if (resolved != nullptr) {
            *resolved = *it;
        }
        return true;
    }
    return false;
}

void SendQueuedLevelUpChoices() {
    if (!IsLocalTransportClient()) {
        return;
    }

    auto choices = TakeQueuedLocalLevelUpChoices();
    if (choices.empty()) {
        return;
    }

    const auto runtime_state = SnapshotRuntimeState();
    const auto& offer = runtime_state.active_level_up_offer;
    if (!offer.valid) {
        return;
    }

    const auto endpoints = BuildKnownSendEndpoints();
    if (endpoints.empty()) {
        return;
    }

    for (const auto& choice : choices) {
        if (choice.offer_id != offer.offer_id) {
            Log(
                "Multiplayer level-up choice skipped; offer id is stale. queued_offer_id=" +
                std::to_string(choice.offer_id) +
                " active_offer_id=" + std::to_string(offer.offer_id));
            continue;
        }

        LevelUpChoicePacket packet{};
        packet.header = MakePacketHeader(PacketKind::LevelUpChoice, g_local_transport.next_sequence++);
        packet.participant_id = g_local_transport.local_peer_id;
        packet.offer_id = choice.offer_id;
        packet.run_nonce = offer.run_nonce;
        packet.option_index = choice.option_index;
        packet.option_id = choice.option_id;
        for (const auto& endpoint : endpoints) {
            SendPacketToEndpoint(packet, endpoint);
        }
        Log(
            "Multiplayer level-up choice sent. participant_id=" +
            std::to_string(packet.participant_id) +
            " offer_id=" + std::to_string(packet.offer_id) +
            " option_index=" + std::to_string(packet.option_index) +
            " option_id=" + std::to_string(packet.option_id));
    }
}
