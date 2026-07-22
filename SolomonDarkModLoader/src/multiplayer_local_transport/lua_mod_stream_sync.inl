std::uint32_t NextLuaModMessageId() {
    auto message_id = g_local_transport.next_lua_mod_message_id++;
    if (message_id == 0) {
        message_id = g_local_transport.next_lua_mod_message_id++;
    }
    return message_id;
}

void SendLuaModStreamMessageToEndpoint(
    LuaModStreamMessageKind kind,
    std::uint64_t stream_sequence,
    std::uint64_t state_revision,
    const std::vector<std::uint8_t>& payload,
    const TransportPeerEndpoint& endpoint) {
    if (payload.empty() ||
        payload.size() >
            kLuaModStreamFragmentPayloadBytes * kLuaModStreamMaxFragments) {
        return;
    }
    const auto fragment_count = static_cast<std::uint16_t>(
        (payload.size() + kLuaModStreamFragmentPayloadBytes - 1) /
        kLuaModStreamFragmentPayloadBytes);
    const auto message_id = NextLuaModMessageId();
    for (std::uint16_t fragment_index = 0;
         fragment_index < fragment_count;
         ++fragment_index) {
        const auto offset =
            static_cast<std::size_t>(fragment_index) *
            kLuaModStreamFragmentPayloadBytes;
        const auto payload_bytes = static_cast<std::uint16_t>((std::min)(
            payload.size() - offset,
            static_cast<std::size_t>(kLuaModStreamFragmentPayloadBytes)));
        LuaModStreamPacket packet{};
        packet.header = MakePacketHeader(
            PacketKind::LuaModStream,
            g_local_transport.next_sequence++);
        packet.authority_participant_id = g_local_transport.local_peer_id;
        packet.stream_sequence = stream_sequence;
        packet.state_revision = state_revision;
        packet.message_id = message_id;
        packet.total_payload_bytes =
            static_cast<std::uint32_t>(payload.size());
        packet.fragment_index = fragment_index;
        packet.fragment_count = fragment_count;
        packet.payload_bytes = payload_bytes;
        packet.message_kind = static_cast<std::uint8_t>(kind);
        std::memcpy(packet.payload, payload.data() + offset, payload_bytes);
        SendBufferToEndpoint(
            &packet,
            LuaModStreamPacketWireSize(payload_bytes),
            endpoint,
            SteamNetworkSendMode::ReliableNoNagle);
    }
}

bool BuildLuaModStateCheckpoint(
    std::vector<std::uint8_t>* payload,
    std::uint64_t* state_revision) {
    if (payload == nullptr || state_revision == nullptr) {
        return false;
    }
    const auto snapshot = SnapshotLuaModState(state_revision);
    std::string error_message;
    if (!EncodeLuaModStateSnapshot(snapshot, payload, &error_message)) {
        Log("Lua mod state checkpoint encode failed: " + error_message);
        return false;
    }
    return true;
}

void SendLuaModStateCheckpointToEndpoint(
    const std::vector<std::uint8_t>& payload,
    std::uint64_t state_revision,
    std::uint64_t stream_sequence,
    const TransportPeerEndpoint& endpoint) {
    SendLuaModStreamMessageToEndpoint(
        LuaModStreamMessageKind::StateCheckpoint,
        stream_sequence,
        state_revision,
        payload,
        endpoint);
}

void SendLuaModStream(std::uint64_t now_ms) {
    if (!g_local_transport.is_host) {
        return;
    }

    std::vector<QueuedLuaModStreamMessage> queued_messages;
    {
        std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
        queued_messages.swap(g_queued_lua_mod_stream_messages);
    }
    const auto latest_stream_sequence =
        queued_messages.empty()
            ? g_local_transport.last_lua_mod_stream_sent_sequence
            : queued_messages.back().stream_sequence;

    std::vector<std::uint8_t> checkpoint_payload;
    std::uint64_t checkpoint_revision = 0;
    bool checkpoint_ready = false;
    std::vector<TransportPeerEndpoint> newly_checkpointed_endpoints;
    for (const auto& peer : g_local_transport.peers) {
        if (peer.participant_id == 0 ||
            g_local_transport.lua_mod_checkpointed_participants.find(
                peer.participant_id) !=
                g_local_transport.lua_mod_checkpointed_participants.end()) {
            continue;
        }
        if (!checkpoint_ready) {
            checkpoint_ready = BuildLuaModStateCheckpoint(
                &checkpoint_payload,
                &checkpoint_revision);
        }
        if (!checkpoint_ready) {
            break;
        }
        SendLuaModStateCheckpointToEndpoint(
            checkpoint_payload,
            checkpoint_revision,
            latest_stream_sequence,
            peer.endpoint);
        newly_checkpointed_endpoints.push_back(peer.endpoint);
        g_local_transport.lua_mod_checkpointed_participants.insert(
            peer.participant_id);
    }

    const auto endpoints = BuildKnownSendEndpoints();
    for (const auto& message : queued_messages) {
        for (const auto& endpoint : endpoints) {
            const bool checkpoint_covers_message = std::any_of(
                newly_checkpointed_endpoints.begin(),
                newly_checkpointed_endpoints.end(),
                [&](const TransportPeerEndpoint& checkpointed) {
                    return SameEndpoint(checkpointed, endpoint);
                });
            if (checkpoint_covers_message) {
                continue;
            }
            SendLuaModStreamMessageToEndpoint(
                message.kind,
                message.stream_sequence,
                message.state_revision,
                message.payload,
                endpoint);
        }
        g_local_transport.last_lua_mod_stream_sent_sequence =
            message.stream_sequence;
    }

    if (now_ms - g_local_transport.last_lua_mod_checkpoint_send_ms <
        kLuaModStateCheckpointIntervalMs) {
        return;
    }
    g_local_transport.last_lua_mod_checkpoint_send_ms = now_ms;
    if (!checkpoint_ready) {
        checkpoint_ready = BuildLuaModStateCheckpoint(
            &checkpoint_payload,
            &checkpoint_revision);
    }
    if (!checkpoint_ready) {
        return;
    }
    for (const auto& endpoint : endpoints) {
        SendLuaModStateCheckpointToEndpoint(
            checkpoint_payload,
            checkpoint_revision,
            g_local_transport.last_lua_mod_stream_sent_sequence,
            endpoint);
    }
}

bool IsAuthorizedLuaModStreamPacket(
    const LuaModStreamPacket& packet,
    const TransportPeerEndpoint& from) {
    if (!IsLocalTransportClient() ||
        !IsConfiguredRemoteAuthorityEndpoint(from)) {
        return false;
    }
    if (from.backend == GameplayTransportBackend::Steam) {
        return packet.authority_participant_id == from.steam_id;
    }
    const auto known_peer = std::find_if(
        g_local_transport.peers.begin(),
        g_local_transport.peers.end(),
        [&](const LocalPeerEndpoint& peer) {
            return SameEndpoint(peer.endpoint, from);
        });
    return known_peer == g_local_transport.peers.end() ||
           known_peer->participant_id == packet.authority_participant_id;
}

bool ApplyCompletedLuaModStreamMessage(
    const CompletedLuaModStreamMessage& message,
    std::string* error_message) {
    std::string mod_id;
    std::string secondary_name;
    LuaModValue value;
    if (!DecodeLuaModStreamPayload(
            message.kind,
            message.payload,
            &mod_id,
            &secondary_name,
            &value,
            error_message) ||
        !IsValidLuaModIdentifier(mod_id)) {
        return false;
    }

    switch (message.kind) {
    case LuaModStreamMessageKind::StateSet:
        return IsValidLuaModStateKey(secondary_name) &&
               ApplyReplicatedLuaModStateSet(
                   mod_id,
                   secondary_name,
                   std::move(value),
                   message.state_revision,
                   error_message);
    case LuaModStreamMessageKind::StateDelete:
        return IsValidLuaModStateKey(secondary_name) &&
               ApplyReplicatedLuaModStateDelete(
                   mod_id,
                   secondary_name,
                   message.state_revision,
                   error_message);
    case LuaModStreamMessageKind::StateClear:
        return ApplyReplicatedLuaModStateClear(
            mod_id,
            message.state_revision,
            error_message);
    case LuaModStreamMessageKind::Event:
        if (!IsValidLuaModIdentifier(secondary_name)) {
            return false;
        }
        DispatchLuaCustomEvent(
            mod_id,
            secondary_name,
            std::move(value),
            message.authority_participant_id,
            message.stream_sequence);
        return true;
    default:
        return false;
    }
}

void DrainCompletedLuaModStreamMessages() {
    for (;;) {
        const auto next_sequence =
            g_local_transport.last_lua_mod_stream_applied_sequence + 1;
        const auto next =
            g_local_transport.completed_lua_mod_stream_messages.find(
                next_sequence);
        if (next ==
            g_local_transport.completed_lua_mod_stream_messages.end()) {
            return;
        }
        auto message = std::move(next->second);
        g_local_transport.completed_lua_mod_stream_messages.erase(next);
        std::string error_message;
        if (!ApplyCompletedLuaModStreamMessage(message, &error_message)) {
            Log(
                "Lua mod stream message rejected. sequence=" +
                std::to_string(message.stream_sequence) +
                " error=" +
                (error_message.empty() ? "invalid payload" : error_message));
            return;
        }
        g_local_transport.last_lua_mod_stream_applied_sequence =
            message.stream_sequence;
    }
}

void ApplyCompletedLuaModStateCheckpoint(
    CompletedLuaModStreamMessage message) {
    if (message.stream_sequence <
        g_local_transport.last_lua_mod_stream_applied_sequence) {
        return;
    }
    LuaModStateSnapshot snapshot;
    std::string error_message;
    if (!DecodeLuaModStateSnapshot(
            message.payload.data(),
            message.payload.size(),
            &snapshot,
            &error_message) ||
        !ApplyReplicatedLuaModStateSnapshot(
            std::move(snapshot),
            message.state_revision,
            &error_message)) {
        Log(
            "Lua mod state checkpoint rejected: " +
            (error_message.empty() ? "invalid payload" : error_message));
        return;
    }
    g_local_transport.last_lua_mod_stream_applied_sequence =
        message.stream_sequence;
    auto completed =
        g_local_transport.completed_lua_mod_stream_messages.begin();
    while (completed !=
               g_local_transport.completed_lua_mod_stream_messages.end() &&
           completed->first <= message.stream_sequence) {
        completed =
            g_local_transport.completed_lua_mod_stream_messages.erase(completed);
    }
    DrainCompletedLuaModStreamMessages();
}

void PruneLuaModStreamAssemblies(std::uint64_t now_ms) {
    for (auto assembly =
             g_local_transport.pending_lua_mod_stream_assemblies.begin();
         assembly !=
         g_local_transport.pending_lua_mod_stream_assemblies.end();) {
        if (now_ms - assembly->second.last_update_ms >=
            kLuaModFragmentAssemblyExpiryMs) {
            assembly =
                g_local_transport.pending_lua_mod_stream_assemblies.erase(
                    assembly);
        } else {
            ++assembly;
        }
    }
}

void ApplyLuaModStreamPacket(
    const LuaModStreamPacket& packet,
    const TransportPeerEndpoint& from,
    std::uint64_t now_ms) {
    if (!IsAuthorizedLuaModStreamPacket(packet, from)) {
        return;
    }
    PruneLuaModStreamAssemblies(now_ms);
    auto assembly =
        g_local_transport.pending_lua_mod_stream_assemblies.find(
            packet.message_id);
    if (assembly ==
        g_local_transport.pending_lua_mod_stream_assemblies.end()) {
        if (g_local_transport.pending_lua_mod_stream_assemblies.size() >=
            kLuaModMaxPendingAssemblies) {
            return;
        }
        PendingLuaModStreamAssembly pending;
        pending.kind =
            static_cast<LuaModStreamMessageKind>(packet.message_kind);
        pending.authority_participant_id =
            packet.authority_participant_id;
        pending.stream_sequence = packet.stream_sequence;
        pending.state_revision = packet.state_revision;
        pending.total_payload_bytes = packet.total_payload_bytes;
        pending.fragment_count = packet.fragment_count;
        pending.last_update_ms = now_ms;
        pending.payload.resize(packet.total_payload_bytes);
        pending.received_fragments.resize(packet.fragment_count);
        assembly =
            g_local_transport.pending_lua_mod_stream_assemblies.emplace(
                packet.message_id,
                std::move(pending)).first;
    }

    auto& pending = assembly->second;
    if (pending.kind !=
            static_cast<LuaModStreamMessageKind>(packet.message_kind) ||
        pending.authority_participant_id !=
            packet.authority_participant_id ||
        pending.stream_sequence != packet.stream_sequence ||
        pending.state_revision != packet.state_revision ||
        pending.total_payload_bytes != packet.total_payload_bytes ||
        pending.fragment_count != packet.fragment_count) {
        g_local_transport.pending_lua_mod_stream_assemblies.erase(assembly);
        return;
    }
    pending.last_update_ms = now_ms;
    if (pending.received_fragments[packet.fragment_index] == 0) {
        const auto offset =
            static_cast<std::size_t>(packet.fragment_index) *
            kLuaModStreamFragmentPayloadBytes;
        std::memcpy(
            pending.payload.data() + offset,
            packet.payload,
            packet.payload_bytes);
        pending.received_fragments[packet.fragment_index] = 1;
        ++pending.received_fragment_count;
    }
    if (pending.received_fragment_count != pending.fragment_count) {
        return;
    }

    CompletedLuaModStreamMessage completed;
    completed.kind = pending.kind;
    completed.authority_participant_id = pending.authority_participant_id;
    completed.stream_sequence = pending.stream_sequence;
    completed.state_revision = pending.state_revision;
    completed.payload = std::move(pending.payload);
    g_local_transport.pending_lua_mod_stream_assemblies.erase(assembly);

    if (completed.kind == LuaModStreamMessageKind::StateCheckpoint) {
        ApplyCompletedLuaModStateCheckpoint(std::move(completed));
        return;
    }
    if (completed.stream_sequence <=
            g_local_transport.last_lua_mod_stream_applied_sequence ||
        g_local_transport.completed_lua_mod_stream_messages.size() >=
            kLuaModMaxCompletedMessages) {
        return;
    }
    g_local_transport.completed_lua_mod_stream_messages.emplace(
        completed.stream_sequence,
        std::move(completed));
    DrainCompletedLuaModStreamMessages();
}

bool QueueAuthoritativeLuaModStreamMessage(
    LuaModStreamMessageKind kind,
    std::uint64_t state_revision,
    std::vector<std::uint8_t> payload,
    std::uint64_t* stream_sequence,
    std::string* error_message) {
    if (stream_sequence != nullptr) {
        *stream_sequence = 0;
    }
    if (!g_local_transport.initialized) {
        return true;
    }
    if (!g_local_transport.is_host) {
        SetLuaModStreamError(
            error_message,
            "Lua mod stream publishing requires simulation authority");
        return false;
    }
    if (payload.empty() ||
        payload.size() >
            kLuaModStreamFragmentPayloadBytes * kLuaModStreamMaxFragments) {
        SetLuaModStreamError(
            error_message,
            "Lua mod stream message exceeds the wire payload limit");
        return false;
    }
    std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
    if (g_next_lua_mod_stream_sequence == 0) {
        SetLuaModStreamError(
            error_message,
            "Lua mod stream sequence space is exhausted");
        return false;
    }
    QueuedLuaModStreamMessage message;
    message.kind = kind;
    message.stream_sequence = g_next_lua_mod_stream_sequence++;
    message.state_revision = state_revision;
    message.payload = std::move(payload);
    if (stream_sequence != nullptr) {
        *stream_sequence = message.stream_sequence;
    }
    g_queued_lua_mod_stream_messages.push_back(std::move(message));
    return true;
}
