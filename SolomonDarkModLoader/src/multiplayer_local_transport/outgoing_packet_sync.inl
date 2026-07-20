SteamNetworkSendMode SteamSendModeForPacket(const CastPacket& packet) {
    return packet.input_phase == static_cast<std::uint8_t>(CastInputPhase::Held)
        ? SteamNetworkSendMode::UnreliableNoDelay
        : SteamNetworkSendMode::ReliableNoNagle;
}

template <typename Packet>
SteamNetworkSendMode SteamSendModeForPacket(const Packet& packet) {
    const auto kind = static_cast<PacketKind>(packet.header.kind);
    switch (kind) {
    case PacketKind::WorldSnapshot:
        // Ordinary generations are disposable visual updates. Never queue
        // them behind newer generations; periodic reliable generations own
        // structural convergence.
    case PacketKind::ParticipantFrame:
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
    const TransportPeerEndpoint& endpoint,
    SteamNetworkSendMode steam_send_mode) {
    if (packet == nullptr || packet_size == 0 || packet_size > static_cast<std::size_t>((std::numeric_limits<int>::max)())) {
        return;
    }
    if (endpoint.backend == GameplayTransportBackend::Steam) {
        std::int32_t result_code = 0;
        if (SteamSendNetworkMessage(
                endpoint.steam_id,
                packet,
                packet_size,
                steam_send_mode,
                &result_code)) {
            g_local_transport.packets_sent += 1;
        } else {
            g_local_transport.steam_send_failures += 1;
            if (steam_send_mode == SteamNetworkSendMode::ReliableNoNagle) {
                g_local_transport.steam_reliable_send_failures += 1;
            }
            g_local_transport.last_steam_send_failure_result = result_code;
            const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
            if (now_ms - g_local_transport.last_steam_send_failure_log_ms >= 1000) {
                g_local_transport.last_steam_send_failure_log_ms = now_ms;
                Log(
                    "Steam gameplay packet send rejected. result=" +
                    std::to_string(result_code) +
                    " bytes=" + std::to_string(packet_size) +
                    " reliable=" +
                    std::to_string(
                        steam_send_mode == SteamNetworkSendMode::ReliableNoNagle ? 1 : 0) +
                    " failures=" +
                    std::to_string(g_local_transport.steam_send_failures) +
                    " reliable_failures=" +
                    std::to_string(g_local_transport.steam_reliable_send_failures));
            }
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
    SendBufferToEndpoint(
        &packet,
        sizeof(packet),
        endpoint,
        SteamSendModeForPacket(packet));
}

template <typename Packet>
void SendPacketToEndpoint(
    const Packet& packet,
    const TransportPeerEndpoint& endpoint,
    SteamNetworkSendMode steam_send_mode) {
    SendBufferToEndpoint(
        &packet,
        sizeof(packet),
        endpoint,
        steam_send_mode);
}

void PublishWorldSnapshotRuntimeInfo(
    const CompleteWorldSnapshotPacketState& complete_snapshot,
    std::uint64_t now_ms);
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
    if (now_ms - g_local_transport.last_state_checkpoint_send_ms <
        kLocalTransportStateCheckpointIntervalMs) {
        return;
    }
    g_local_transport.last_state_checkpoint_send_ms = now_ms;

    const auto packet = BuildLocalStatePacket();
    if (packet.transform_valid == 0 &&
        !(g_local_transport.is_host && packet.run_nonce != 0 && packet.in_run == 0)) {
        return;
    }

    const auto endpoints = BuildKnownSendEndpoints();
    for (const auto& endpoint : endpoints) {
        SendPacketToEndpoint(
            packet,
            endpoint,
            SteamNetworkSendMode::ReliableNoNagle);
    }
}

void SendLocalParticipantFrame(std::uint64_t now_ms) {
    if (now_ms - g_local_transport.last_participant_frame_send_ms <
        kLocalTransportParticipantFrameIntervalMs) {
        return;
    }
    g_local_transport.last_participant_frame_send_ms = now_ms;

    const auto packet = BuildLocalParticipantFramePacket();
    if (packet.transform_valid == 0 &&
        !(g_local_transport.is_host && packet.run_nonce != 0 &&
          packet.in_run == 0)) {
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

    ReconcileHostLocalFireballExplodeSplash(now_ms);

    CompleteWorldSnapshotPacketState complete_snapshot;
    if (!BuildLocalWorldSnapshot(&complete_snapshot)) {
        return;
    }
    if (complete_snapshot.actors.empty() &&
        complete_snapshot.scene_kind != WorldSceneKind::Run) {
        return;
    }

    const auto fragment_count = (std::max<std::size_t>)(
        1,
        (complete_snapshot.actors.size() +
         kWorldSnapshotActorsPerFragment - 1u) /
            kWorldSnapshotActorsPerFragment);
    const auto generation_wire_size =
        fragment_count * sizeof(WorldSnapshotPacket);
    const auto send_interval_ms = BandwidthLimitedSnapshotIntervalMs(
        generation_wire_size,
        kLocalTransportWorldSnapshotIntervalMs,
        kLocalTransportWorldSnapshotBudgetBytesPerSecond);
    if (now_ms - g_local_transport.last_world_snapshot_send_ms <
        send_interval_ms) {
        return;
    }
    g_local_transport.last_world_snapshot_send_ms = now_ms;

    std::vector<WorldSnapshotPacket> packets;
    if (!BuildWorldSnapshotFragmentPackets(
            complete_snapshot,
            &g_local_transport.next_sequence,
            &packets)) {
        return;
    }

    PublishWorldSnapshotRuntimeInfo(complete_snapshot, now_ms);

    const bool reliable_checkpoint =
        now_ms -
                g_local_transport
                    .last_world_snapshot_reliable_checkpoint_ms >=
            BandwidthLimitedSnapshotIntervalMs(
                generation_wire_size,
                kLocalTransportWorldSnapshotReliableCheckpointIntervalMs,
                kLocalTransportWorldReliableCheckpointBudgetBytesPerSecond);
    if (reliable_checkpoint) {
        g_local_transport.last_world_snapshot_reliable_checkpoint_ms = now_ms;
    }
    const auto endpoints = BuildKnownSendEndpoints();
    for (const auto& endpoint : endpoints) {
        for (const auto& packet : packets) {
            if (reliable_checkpoint) {
                SendPacketToEndpoint(
                    packet,
                    endpoint,
                    SteamNetworkSendMode::ReliableNoNagle);
            } else {
                SendPacketToEndpoint(packet, endpoint);
            }
        }
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

    const auto wire_size = LootSnapshotPacketWireSize(packet.drop_count);
    const auto endpoints = BuildKnownSendEndpoints();
    for (const auto& endpoint : endpoints) {
        SendBufferToEndpoint(
            &packet,
            wire_size,
            endpoint,
            SteamSendModeForPacket(packet));
    }
}

std::vector<QueuedLocalLootPickupRequest> TakeQueuedLocalLootPickupRequests(
    std::uint64_t now_ms) {
    std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
    std::vector<QueuedLocalLootPickupRequest> requests;
    requests.swap(g_queued_local_loot_pickup_requests);
    for (const auto& request : requests) {
        g_in_flight_local_loot_pickup_requests_by_drop_id[
            request.network_drop_id] = {
                request.request_sequence,
                now_ms,
            };
    }
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

    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    auto requests = TakeQueuedLocalLootPickupRequests(now_ms);
    if (requests.empty()) {
        return;
    }

    for (const auto& request : requests) {
        const auto& last_result = runtime_state.last_loot_pickup_result;
        const bool automatic_request_already_terminal =
            request.automatic_proximity_request &&
            last_result.valid &&
            last_result.participant_id == g_local_transport.local_peer_id &&
            last_result.run_nonce == local->runtime.run_nonce &&
            last_result.network_drop_id == request.network_drop_id &&
            (last_result.result_code == LootPickupResultCode::Accepted ||
             last_result.result_code == LootPickupResultCode::AlreadyGone);
        if (automatic_request_already_terminal) {
            CompleteInFlightLocalLootPickupRequest(
                request.network_drop_id,
                request.request_sequence);
            Log(
                "Multiplayer automatic loot pickup retry suppressed after terminal result. "
                "network_drop_id=" +
                std::to_string(request.network_drop_id) +
                " request_sequence=" + std::to_string(request.request_sequence) +
                " result=" + LootPickupResultCodeLabel(last_result.result_code));
            continue;
        }

        const auto* drop =
            FindLootDropSnapshotByNetworkId(runtime_state.loot_snapshot, request.network_drop_id);
        const bool have_recent_pickup_result =
            runtime_state.last_loot_pickup_result.valid &&
            runtime_state.last_loot_pickup_result.network_drop_id == request.network_drop_id;
        if (drop == nullptr && !have_recent_pickup_result) {
            CompleteInFlightLocalLootPickupRequest(
                request.network_drop_id,
                request.request_sequence);
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
