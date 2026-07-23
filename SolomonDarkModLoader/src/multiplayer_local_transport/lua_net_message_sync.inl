bool IsKnownLuaNetParticipant(std::uint64_t participant_id) {
    if (participant_id == 0) return false;
    if (participant_id == g_local_transport.local_peer_id) return true;
    if (std::any_of(
        g_local_transport.peers.begin(),
        g_local_transport.peers.end(),
        [&](const LocalPeerEndpoint& peer) {
            return peer.participant_id == participant_id;
        })) {
        return true;
    }
    const auto runtime = SnapshotRuntimeState();
    return std::any_of(
        runtime.participants.begin(),
        runtime.participants.end(),
        [&](const ParticipantInfo& participant) {
            return participant.participant_id == participant_id &&
                participant.transport_connected;
        });
}

std::vector<TransportPeerEndpoint> LuaNetDestinationEndpoints(
    std::uint64_t target_participant_id) {
    if (target_participant_id == 0) {
        return BuildKnownSendEndpoints();
    }
    std::vector<TransportPeerEndpoint> endpoints;
    for (const auto& peer : g_local_transport.peers) {
        if (peer.participant_id == target_participant_id) {
            endpoints.push_back(peer.endpoint);
            break;
        }
    }
    return endpoints;
}

bool QueueOutboundLuaNetMessage(
    QueuedLuaNetMessage message,
    std::string* error_message) {
    std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
    if (g_queued_lua_net_messages.size() >= kLuaNetMaximumQueuedMessages ||
        g_queued_lua_net_message_bytes + message.envelope.size() >
            kLuaNetMaximumQueuedBytes) {
        SetLuaNetError(error_message, "Lua net outbound queue is full");
        return false;
    }
    g_queued_lua_net_message_bytes += message.envelope.size();
    g_queued_lua_net_messages.push_back(std::move(message));
    return true;
}

std::vector<QueuedLuaNetMessage> TakeQueuedLuaNetMessages() {
    std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
    std::vector<QueuedLuaNetMessage> messages;
    messages.swap(g_queued_lua_net_messages);
    g_queued_lua_net_message_bytes = 0;
    return messages;
}

void RestoreQueuedLuaNetMessages(std::vector<QueuedLuaNetMessage> messages) {
    std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
    messages.insert(
        messages.end(),
        std::make_move_iterator(g_queued_lua_net_messages.begin()),
        std::make_move_iterator(g_queued_lua_net_messages.end()));
    std::size_t bytes = 0;
    std::size_t retained = 0;
    while (retained < messages.size() &&
           retained < kLuaNetMaximumQueuedMessages &&
           bytes + messages[retained].envelope.size() <=
               kLuaNetMaximumQueuedBytes) {
        bytes += messages[retained].envelope.size();
        ++retained;
    }
    messages.resize(retained);
    g_queued_lua_net_messages = std::move(messages);
    g_queued_lua_net_message_bytes = bytes;
}

bool QueueDecodedLuaNetDelivery(const QueuedLuaNetMessage& message) {
    std::string mod_id;
    std::string channel;
    std::string payload;
    std::string error_message;
    if (!DecodeLuaNetEnvelope(
            message.envelope,
            &mod_id,
            &channel,
            &payload,
            &error_message)) {
        return false;
    }
    return sdmod::QueueLuaNetMessageDelivery(LuaNetMessage{
        std::move(mod_id),
        std::move(channel),
        std::move(payload),
        message.source_participant_id,
        message.target_participant_id,
        message.message_sequence,
        message.target_participant_id == 0,
    });
}

void SendLuaNetMessageToEndpoint(
    const QueuedLuaNetMessage& message,
    const TransportPeerEndpoint& endpoint) {
    const auto fragment_count = static_cast<std::uint16_t>(
        (message.envelope.size() + kLuaNetFragmentPayloadBytes - 1) /
        kLuaNetFragmentPayloadBytes);
    for (std::uint16_t fragment_index = 0;
         fragment_index < fragment_count;
         ++fragment_index) {
        const auto offset = static_cast<std::size_t>(fragment_index) *
            kLuaNetFragmentPayloadBytes;
        const auto payload_bytes = static_cast<std::uint16_t>((std::min)(
            message.envelope.size() - offset,
            static_cast<std::size_t>(kLuaNetFragmentPayloadBytes)));
        LuaNetMessagePacket packet{};
        packet.header = MakePacketHeader(
            PacketKind::LuaNetMessage,
            g_local_transport.next_sequence++);
        packet.transport_participant_id = g_local_transport.local_peer_id;
        packet.source_participant_id = message.source_participant_id;
        packet.source_session_nonce = message.source_session_nonce;
        packet.target_participant_id = message.target_participant_id;
        packet.message_sequence = message.message_sequence;
        packet.total_payload_bytes =
            static_cast<std::uint32_t>(message.envelope.size());
        packet.fragment_index = fragment_index;
        packet.fragment_count = fragment_count;
        packet.payload_bytes = payload_bytes;
        std::memcpy(
            packet.payload,
            message.envelope.data() + offset,
            payload_bytes);
        SendBufferToEndpoint(
            &packet,
            LuaNetMessagePacketWireSize(payload_bytes),
            endpoint,
            SteamNetworkSendMode::ReliableNoNagle);
    }
}

void SendQueuedLuaNetMessages() {
    if (!g_local_transport.initialized) return;
    auto messages = TakeQueuedLuaNetMessages();
    if (messages.empty()) return;
    if (!g_local_transport.is_host && BuildKnownSendEndpoints().empty()) {
        RestoreQueuedLuaNetMessages(std::move(messages));
        return;
    }
    for (auto& message : messages) {
        if (g_local_transport.is_host && !message.local_delivery_complete &&
            (message.target_participant_id == 0 ||
             message.target_participant_id == g_local_transport.local_peer_id)) {
            if (!QueueDecodedLuaNetDelivery(message)) {
                Log("Lua net local delivery queue rejected an outbound message.");
            }
            message.local_delivery_complete = true;
        }
        const auto endpoints = g_local_transport.is_host
            ? LuaNetDestinationEndpoints(message.target_participant_id)
            : BuildKnownSendEndpoints();
        for (const auto& endpoint : endpoints) {
            SendLuaNetMessageToEndpoint(message, endpoint);
        }
    }
}

bool IsAuthorizedLuaNetMessagePacket(
    const LuaNetMessagePacket& packet,
    const TransportPeerEndpoint& from) {
    if (g_local_transport.is_host) {
        const auto peer = std::find_if(
            g_local_transport.peers.begin(),
            g_local_transport.peers.end(),
            [&](const LocalPeerEndpoint& candidate) {
                return SameEndpoint(candidate.endpoint, from) &&
                    candidate.participant_id == packet.transport_participant_id;
            });
        const auto nonce = g_local_transport.session_nonce_by_participant.find(
            packet.source_participant_id);
        return peer != g_local_transport.peers.end() &&
            packet.transport_participant_id == packet.source_participant_id &&
            nonce != g_local_transport.session_nonce_by_participant.end() &&
            nonce->second == packet.source_session_nonce;
    }
    if (!IsConfiguredRemoteAuthorityEndpoint(from)) return false;
    if (from.backend == GameplayTransportBackend::Steam) {
        return packet.transport_participant_id == from.steam_id;
    }
    const auto peer = std::find_if(
        g_local_transport.peers.begin(),
        g_local_transport.peers.end(),
        [&](const LocalPeerEndpoint& candidate) {
            return SameEndpoint(candidate.endpoint, from);
        });
    return peer == g_local_transport.peers.end() ||
        peer->participant_id == packet.transport_participant_id;
}

std::size_t PendingLuaNetAssemblyBytes() {
    std::size_t bytes = 0;
    for (const auto& entry :
         g_local_transport.pending_lua_net_message_assemblies) {
        bytes += entry.second.payload.size();
    }
    return bytes;
}

void PruneLuaNetAssemblies(std::uint64_t now_ms) {
    for (auto it = g_local_transport.pending_lua_net_message_assemblies.begin();
         it != g_local_transport.pending_lua_net_message_assemblies.end();) {
        if (now_ms - it->second.last_update_ms >=
            kLuaModFragmentAssemblyExpiryMs) {
            it = g_local_transport.pending_lua_net_message_assemblies.erase(it);
        } else {
            ++it;
        }
    }
}

bool RememberLuaNetSequence(
    std::uint64_t source_participant_id,
    std::uint64_t source_session_nonce,
    std::uint64_t message_sequence) {
    auto& remembered_nonce =
        g_local_transport.received_lua_net_session_nonce_by_participant[
            source_participant_id];
    if (remembered_nonce != source_session_nonce) {
        g_local_transport.received_lua_net_sequences_by_participant.erase(
            source_participant_id);
        g_local_transport.received_lua_net_sequence_order_by_participant.erase(
            source_participant_id);
        remembered_nonce = source_session_nonce;
    }
    auto& remembered =
        g_local_transport.received_lua_net_sequences_by_participant[
            source_participant_id];
    if (!remembered.insert(message_sequence).second) return false;
    auto& order =
        g_local_transport.received_lua_net_sequence_order_by_participant[
            source_participant_id];
    order.push_back(message_sequence);
    while (order.size() > kLuaNetMaxRememberedSequencesPerParticipant) {
        remembered.erase(order.front());
        order.pop_front();
    }
    return true;
}

void ApplyCompletedLuaNetMessage(QueuedLuaNetMessage message) {
    std::string mod_id;
    std::string channel;
    std::string payload;
    std::string error_message;
    if (!DecodeLuaNetEnvelope(
            message.envelope,
            &mod_id,
            &channel,
            &payload,
            &error_message)) {
        return;
    }
    if (g_local_transport.is_host &&
        message.target_participant_id != 0 &&
        !IsKnownLuaNetParticipant(message.target_participant_id)) {
        return;
    }
    if (!g_local_transport.is_host &&
        message.target_participant_id != 0 &&
        message.target_participant_id != g_local_transport.local_peer_id) {
        return;
    }
    if (!RememberLuaNetSequence(
            message.source_participant_id,
            message.source_session_nonce,
            message.message_sequence)) {
        return;
    }

    if (!g_local_transport.is_host) {
        QueueLuaNetMessageDelivery(LuaNetMessage{
            std::move(mod_id),
            std::move(channel),
            std::move(payload),
            message.source_participant_id,
            message.target_participant_id,
            message.message_sequence,
            message.target_participant_id == 0,
        });
        return;
    }

    if (message.target_participant_id ==
        g_local_transport.local_peer_id) {
        QueueLuaNetMessageDelivery(LuaNetMessage{
            mod_id,
            channel,
            payload,
            message.source_participant_id,
            message.target_participant_id,
            message.message_sequence,
            message.target_participant_id == 0,
        });
        return;
    }
    const auto source_participant_id = message.source_participant_id;
    const auto target_participant_id = message.target_participant_id;
    const auto message_sequence = message.message_sequence;
    message.local_delivery_complete = true;
    if (!QueueOutboundLuaNetMessage(std::move(message), &error_message)) {
        Log("Lua net relay queue rejected a completed participant message.");
        return;
    }
    if (target_participant_id == 0) {
        QueueLuaNetMessageDelivery(LuaNetMessage{
            std::move(mod_id),
            std::move(channel),
            std::move(payload),
            source_participant_id,
            target_participant_id,
            message_sequence,
            true,
        });
    }
}

void ApplyLuaNetMessagePacket(
    const LuaNetMessagePacket& packet,
    const TransportPeerEndpoint& from,
    std::uint64_t now_ms) {
    if (!IsAuthorizedLuaNetMessagePacket(packet, from)) return;
    PruneLuaNetAssemblies(now_ms);
    const auto key = std::make_pair(
        packet.source_participant_id,
        packet.message_sequence);
    auto assembly =
        g_local_transport.pending_lua_net_message_assemblies.find(key);
    if (assembly ==
        g_local_transport.pending_lua_net_message_assemblies.end()) {
        if (g_local_transport.pending_lua_net_message_assemblies.size() >=
                kLuaNetMaxPendingAssemblies ||
            PendingLuaNetAssemblyBytes() + packet.total_payload_bytes >
                kLuaNetMaxPendingAssemblyBytes) {
            return;
        }
        PendingLuaNetMessageAssembly pending;
        pending.transport_participant_id = packet.transport_participant_id;
        pending.source_participant_id = packet.source_participant_id;
        pending.source_session_nonce = packet.source_session_nonce;
        pending.target_participant_id = packet.target_participant_id;
        pending.message_sequence = packet.message_sequence;
        pending.total_payload_bytes = packet.total_payload_bytes;
        pending.fragment_count = packet.fragment_count;
        pending.last_update_ms = now_ms;
        pending.payload.resize(packet.total_payload_bytes);
        pending.received_fragments.resize(packet.fragment_count);
        assembly = g_local_transport.pending_lua_net_message_assemblies.emplace(
            key,
            std::move(pending)).first;
    }

    auto& pending = assembly->second;
    if (pending.transport_participant_id != packet.transport_participant_id ||
        pending.source_participant_id != packet.source_participant_id ||
        pending.source_session_nonce != packet.source_session_nonce ||
        pending.target_participant_id != packet.target_participant_id ||
        pending.message_sequence != packet.message_sequence ||
        pending.total_payload_bytes != packet.total_payload_bytes ||
        pending.fragment_count != packet.fragment_count) {
        g_local_transport.pending_lua_net_message_assemblies.erase(assembly);
        return;
    }
    pending.last_update_ms = now_ms;
    if (pending.received_fragments[packet.fragment_index] == 0) {
        const auto offset = static_cast<std::size_t>(packet.fragment_index) *
            kLuaNetFragmentPayloadBytes;
        std::memcpy(
            pending.payload.data() + offset,
            packet.payload,
            packet.payload_bytes);
        pending.received_fragments[packet.fragment_index] = 1;
        ++pending.received_fragment_count;
    }
    if (pending.received_fragment_count != pending.fragment_count) return;

    QueuedLuaNetMessage completed;
    completed.source_participant_id = pending.source_participant_id;
    completed.source_session_nonce = pending.source_session_nonce;
    completed.target_participant_id = pending.target_participant_id;
    completed.message_sequence = pending.message_sequence;
    completed.envelope = std::move(pending.payload);
    g_local_transport.pending_lua_net_message_assemblies.erase(assembly);
    ApplyCompletedLuaNetMessage(std::move(completed));
}

bool QueueLuaNetMessageInternal(
    std::string_view mod_id,
    std::string_view channel,
    std::string_view payload,
    std::uint64_t target_participant_id,
    bool broadcast,
    std::uint64_t* message_sequence,
    std::string* error_message) {
    if (message_sequence != nullptr) *message_sequence = 0;
    if (error_message != nullptr) error_message->clear();
    if (broadcast != (target_participant_id == 0)) {
        SetLuaNetError(error_message, "Lua net target and broadcast mode disagree");
        return false;
    }
    std::vector<std::uint8_t> envelope;
    if (!EncodeLuaNetEnvelope(
            mod_id,
            channel,
            payload,
            &envelope,
            error_message)) {
        return false;
    }

    if (!g_local_transport.initialized) {
        if (!broadcast) {
            SetLuaNetError(
                error_message,
                "Lua net unicast requires an active multiplayer transport");
            return false;
        }
        std::uint64_t sequence = 0;
        {
            std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
            if (g_next_lua_net_message_sequence == 0 ||
                g_next_lua_net_message_sequence >
                    kLuaNetMaximumMessageSequence) {
                SetLuaNetError(error_message, "Lua net sequence space is exhausted");
                return false;
            }
            sequence = g_next_lua_net_message_sequence++;
        }
        if (!QueueLuaNetMessageDelivery(LuaNetMessage{
                std::string(mod_id),
                std::string(channel),
                std::string(payload),
                0,
                0,
                sequence,
                true,
            })) {
            SetLuaNetError(error_message, "Lua net local delivery queue is full");
            return false;
        }
        if (message_sequence != nullptr) *message_sequence = sequence;
        return true;
    }

    if (g_local_transport.local_peer_id == 0 ||
        g_local_transport.local_session_nonce == 0) {
        SetLuaNetError(error_message, "Lua net local participant session is unavailable");
        return false;
    }
    if (!broadcast && !IsKnownLuaNetParticipant(target_participant_id)) {
        SetLuaNetError(error_message, "Lua net target participant is not connected");
        return false;
    }

    std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
    if (g_next_lua_net_message_sequence == 0 ||
        g_next_lua_net_message_sequence > kLuaNetMaximumMessageSequence) {
        SetLuaNetError(error_message, "Lua net sequence space is exhausted");
        return false;
    }
    if (g_queued_lua_net_messages.size() >= kLuaNetMaximumQueuedMessages ||
        g_queued_lua_net_message_bytes + envelope.size() >
            kLuaNetMaximumQueuedBytes) {
        SetLuaNetError(error_message, "Lua net outbound queue is full");
        return false;
    }
    QueuedLuaNetMessage message;
    message.source_participant_id = g_local_transport.local_peer_id;
    message.source_session_nonce = g_local_transport.local_session_nonce;
    message.target_participant_id = target_participant_id;
    message.message_sequence = g_next_lua_net_message_sequence++;
    message.envelope = std::move(envelope);
    g_queued_lua_net_message_bytes += message.envelope.size();
    if (message_sequence != nullptr) {
        *message_sequence = message.message_sequence;
    }
    g_queued_lua_net_messages.push_back(std::move(message));
    return true;
}

void ClearLuaNetParticipantTransportState(
    std::uint64_t participant_id,
    bool authority_disconnected) {
    if (authority_disconnected) {
        g_local_transport.pending_lua_net_message_assemblies.clear();
        g_local_transport.received_lua_net_sequences_by_participant.clear();
        g_local_transport.received_lua_net_sequence_order_by_participant.clear();
        g_local_transport.received_lua_net_session_nonce_by_participant.clear();
    } else {
        for (auto it =
                 g_local_transport.pending_lua_net_message_assemblies.begin();
             it !=
                 g_local_transport.pending_lua_net_message_assemblies.end();) {
            const auto& pending = it->second;
            if (pending.source_participant_id == participant_id ||
                pending.transport_participant_id == participant_id ||
                pending.target_participant_id == participant_id) {
                it = g_local_transport.pending_lua_net_message_assemblies.erase(it);
            } else {
                ++it;
            }
        }
        g_local_transport.received_lua_net_sequences_by_participant.erase(
            participant_id);
        g_local_transport.received_lua_net_sequence_order_by_participant.erase(
            participant_id);
        g_local_transport.received_lua_net_session_nonce_by_participant.erase(
            participant_id);
    }
    std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
    if (authority_disconnected) {
        g_queued_lua_net_messages.clear();
        g_queued_lua_net_message_bytes = 0;
        g_next_lua_net_message_sequence = 1;
        return;
    }
    g_queued_lua_net_messages.erase(
        std::remove_if(
            g_queued_lua_net_messages.begin(),
            g_queued_lua_net_messages.end(),
            [&](const QueuedLuaNetMessage& message) {
                return message.source_participant_id == participant_id ||
                    message.target_participant_id == participant_id;
            }),
        g_queued_lua_net_messages.end());
    g_queued_lua_net_message_bytes = 0;
    for (const auto& message : g_queued_lua_net_messages) {
        g_queued_lua_net_message_bytes += message.envelope.size();
    }
}
