bool IsLuaConsumableUseContentRegistered(std::uint64_t content_id) {
    return content_id != 0 &&
        FindLuaConsumableDefinition(content_id).has_value();
}

bool LuaConsumableUseRunMatches(
    std::uint64_t participant_id,
    std::uint32_t run_nonce) {
    if (run_nonce == 0) {
        return true;
    }
    const auto runtime = SnapshotRuntimeState();
    const auto* participant =
        FindParticipant(runtime, participant_id);
    return participant == nullptr ||
        participant->runtime.run_nonce == 0 ||
        participant->runtime.run_nonce == run_nonce;
}

bool RememberLuaConsumableUse(
    std::uint64_t participant_id,
    std::uint64_t session_nonce,
    std::uint64_t use_id) {
    auto& remembered_nonce =
        g_local_transport
            .lua_consumable_session_nonce_by_participant[
                participant_id];
    if (remembered_nonce != session_nonce) {
        remembered_nonce = session_nonce;
        g_local_transport
            .last_lua_consumable_use_by_participant[
                participant_id] = 0;
    }
    auto& last_use =
        g_local_transport.last_lua_consumable_use_by_participant[
            participant_id];
    if (use_id <= last_use) {
        return false;
    }
    last_use = use_id;
    return true;
}

bool QueueLocalLuaConsumableUseInternal(
    std::uint64_t content_id,
    std::uint64_t* use_id,
    std::string* error_message) {
    if (use_id != nullptr) {
        *use_id = 0;
    }
    if (error_message != nullptr) {
        error_message->clear();
    }
    const auto fail = [&](const char* message) {
        if (error_message != nullptr) {
            *error_message = message;
        }
        return false;
    };
    if (!IsLuaConsumableUseContentRegistered(content_id)) {
        return fail(
            "Lua consumable use requires a registered content identity.");
    }

    QueuedLuaConsumableUse use;
    use.participant_id = g_local_transport.initialized
        ? g_local_transport.local_peer_id
        : kLocalParticipantId;
    use.participant_session_nonce =
        g_local_transport.local_session_nonce;
    const auto runtime = SnapshotRuntimeState();
    if (const auto* local = FindLocalParticipant(runtime);
        local != nullptr) {
        use.run_nonce = local->runtime.run_nonce;
    }
    {
        std::lock_guard<std::mutex> lock(
            g_local_transport_event_mutex);
        if (g_next_lua_consumable_use_id == 0 ||
            g_next_lua_consumable_use_id >
                static_cast<std::uint64_t>(INT64_MAX)) {
            g_next_lua_consumable_use_id = 1;
        }
        use.use_id = g_next_lua_consumable_use_id++;
        use.content_id = content_id;
        if (g_local_transport.initialized) {
            if (use.participant_id == 0 ||
                use.participant_session_nonce == 0) {
                return fail(
                    "Lua consumable use has no multiplayer session identity.");
            }
            if (g_queued_lua_consumable_uses.size() >=
                kLuaConsumableUseMaximumQueuedRequests) {
                return fail("Lua consumable use transport queue is full.");
            }
            g_queued_lua_consumable_uses.push_back(use);
        }
    }

    DispatchLuaConsumableUse(
        content_id,
        use.participant_id,
        use.use_id,
        true);
    if (use_id != nullptr) {
        *use_id = use.use_id;
    }
    return true;
}

std::vector<QueuedLuaConsumableUse>
TakeQueuedLuaConsumableUses() {
    std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
    std::vector<QueuedLuaConsumableUse> uses;
    uses.swap(g_queued_lua_consumable_uses);
    return uses;
}

void SendQueuedLuaConsumableUses() {
    const auto endpoints = BuildKnownSendEndpoints();
    auto uses = TakeQueuedLuaConsumableUses();
    if (endpoints.empty()) {
        std::lock_guard<std::mutex> lock(
            g_local_transport_event_mutex);
        uses.insert(
            uses.end(),
            std::make_move_iterator(
                g_queued_lua_consumable_uses.begin()),
            std::make_move_iterator(
                g_queued_lua_consumable_uses.end()));
        g_queued_lua_consumable_uses = std::move(uses);
        if (g_queued_lua_consumable_uses.size() >
            kLuaConsumableUseMaximumQueuedRequests) {
            g_queued_lua_consumable_uses.resize(
                kLuaConsumableUseMaximumQueuedRequests);
        }
        return;
    }

    for (const auto& use : uses) {
        LuaConsumableUsePacket packet{};
        packet.header = MakePacketHeader(
            PacketKind::LuaConsumableUse,
            g_local_transport.next_sequence++);
        packet.participant_id = use.participant_id;
        packet.participant_session_nonce =
            use.participant_session_nonce;
        packet.use_id = use.use_id;
        packet.content_id = use.content_id;
        packet.run_nonce = use.run_nonce;
        for (const auto& endpoint : endpoints) {
            SendPacketToEndpoint(packet, endpoint);
        }
        Log(
            "lua_items: sent consumable use. participant_id=" +
            std::to_string(packet.participant_id) +
            " use_id=" + std::to_string(packet.use_id) +
            " content_id=" + std::to_string(packet.content_id));
    }
}

void ApplyLuaConsumableUsePacket(
    const LuaConsumableUsePacket& packet,
    const TransportPeerEndpoint& from,
    std::uint64_t now_ms) {
    if (packet.participant_id == 0 ||
        packet.participant_id == g_local_transport.local_peer_id ||
        packet.participant_session_nonce == 0 ||
        packet.use_id == 0 ||
        !IsLuaConsumableUseContentRegistered(packet.content_id) ||
        packet.flags != 0 ||
        std::any_of(
            std::begin(packet.reserved),
            std::end(packet.reserved),
            [](std::uint8_t value) { return value != 0; }) ||
        !LuaConsumableUseRunMatches(
            packet.participant_id,
            packet.run_nonce)) {
        return;
    }

    if (IsLocalTransportHost()) {
        const auto peer = std::find_if(
            g_local_transport.peers.begin(),
            g_local_transport.peers.end(),
            [&](const LocalPeerEndpoint& candidate) {
                return candidate.participant_id ==
                        packet.participant_id &&
                    SameEndpoint(candidate.endpoint, from);
            });
        const auto nonce =
            g_local_transport.session_nonce_by_participant.find(
                packet.participant_id);
        if (peer == g_local_transport.peers.end() ||
            nonce ==
                g_local_transport.session_nonce_by_participant.end() ||
            nonce->second != packet.participant_session_nonce) {
            return;
        }
    } else if (!IsConfiguredRemoteAuthorityEndpoint(from)) {
        return;
    }

    if (!RememberLuaConsumableUse(
            packet.participant_id,
            packet.participant_session_nonce,
            packet.use_id)) {
        return;
    }
    if (IsLocalTransportHost()) {
        UpsertPeerEndpoint(from, packet.participant_id, now_ms);
    }
    DispatchLuaConsumableUse(
        packet.content_id,
        packet.participant_id,
        packet.use_id,
        false);
    if (IsLocalTransportHost()) {
        RelayPacketToPeers(packet, from);
    }
    Log(
        "lua_items: accepted consumable use. participant_id=" +
        std::to_string(packet.participant_id) +
        " use_id=" + std::to_string(packet.use_id) +
        " content_id=" + std::to_string(packet.content_id));
}
