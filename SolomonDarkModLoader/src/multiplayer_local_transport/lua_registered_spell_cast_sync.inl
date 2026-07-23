std::vector<QueuedLuaRegisteredSpellCast>
TakeQueuedLuaRegisteredSpellCasts() {
    std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
    std::vector<QueuedLuaRegisteredSpellCast> casts;
    casts.swap(g_queued_lua_registered_spell_casts);
    return casts;
}

void SendQueuedLuaRegisteredSpellCasts() {
    if (!IsLocalTransportHost()) {
        return;
    }
    for (const auto& queued : TakeQueuedLuaRegisteredSpellCasts()) {
        const auto& request = queued.request;
        LuaRegisteredSpellCastPacket packet{};
        packet.header = MakePacketHeader(
            PacketKind::LuaRegisteredSpellCast,
            g_local_transport.next_sequence++);
        packet.authority_participant_id = request.authority_participant_id;
        packet.owner_participant_id = request.owner_participant_id;
        packet.request_id = request.request_id;
        packet.content_id = request.content_id;
        packet.target_network_actor_id = request.target_network_actor_id;
        packet.origin_x = request.origin_x;
        packet.origin_y = request.origin_y;
        packet.aim_x = request.aim_x;
        packet.aim_y = request.aim_y;
        SendPacketToParticipantOrPeers(packet, request.owner_participant_id);
        Log(
            "lua_spells: sent owner-routed cast. request_id=" +
            std::to_string(request.request_id) +
            " owner_participant_id=" +
            std::to_string(request.owner_participant_id) +
            " content_id=" + std::to_string(request.content_id));
    }
}

bool QueueOwnerRoutedLuaRegisteredSpellCastInternal(
    std::uint64_t content_id,
    std::uint64_t requested_owner_participant_id,
    std::uint64_t target_network_actor_id,
    float origin_x,
    float origin_y,
    float aim_x,
    float aim_y,
    std::uint64_t* request_id,
    std::uint64_t* owner_participant_id,
    bool* local_owner,
    std::string* error_message) {
    if (request_id != nullptr) {
        *request_id = 0;
    }
    if (owner_participant_id != nullptr) {
        *owner_participant_id = 0;
    }
    if (local_owner != nullptr) {
        *local_owner = false;
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
    if (content_id == 0 ||
        content_id > static_cast<std::uint64_t>(INT64_MAX)) {
        return fail("Lua registered spell content id must be a positive integer.");
    }
    for (const auto coordinate : {origin_x, origin_y, aim_x, aim_y}) {
        if (!std::isfinite(coordinate) ||
            std::fabs(coordinate) > 10'000'000.0f) {
            return fail("Lua registered spell cast coordinates are invalid.");
        }
    }
    const auto direction_x = aim_x - origin_x;
    const auto direction_y = aim_y - origin_y;
    if (direction_x * direction_x + direction_y * direction_y < 0.000001f) {
        return fail("Lua registered spell cast origin and aim must differ.");
    }

    const auto local_wire_participant_id = g_local_transport.initialized
        ? g_local_transport.local_peer_id
        : kLocalParticipantId;
    std::uint64_t selected_owner_participant_id =
        requested_owner_participant_id;
    bool targets_local_owner =
        requested_owner_participant_id == 0 ||
        requested_owner_participant_id == kLocalParticipantId ||
        requested_owner_participant_id == local_wire_participant_id;
    if (targets_local_owner) {
        selected_owner_participant_id = local_wire_participant_id;
    } else {
        const auto runtime_state = SnapshotRuntimeState();
        const auto* participant = FindParticipant(
            runtime_state,
            requested_owner_participant_id);
        targets_local_owner = participant != nullptr &&
            participant->is_owner && !IsRemoteParticipant(*participant);
    }
    if (!targets_local_owner &&
        (!IsLocalTransportHost() ||
         std::none_of(
             g_local_transport.peers.begin(),
             g_local_transport.peers.end(),
             [&](const LocalPeerEndpoint& peer) {
                 return peer.participant_id == requested_owner_participant_id;
             }))) {
        return fail(
            "Lua registered spell owner is not a connected remote participant.");
    }

    LuaRegisteredSpellCastRequest request;
    request.authority_participant_id = local_wire_participant_id;
    request.owner_participant_id = selected_owner_participant_id;
    request.content_id = content_id;
    request.target_network_actor_id = target_network_actor_id;
    request.origin_x = origin_x;
    request.origin_y = origin_y;
    request.aim_x = aim_x;
    request.aim_y = aim_y;
    {
        std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
        if (!targets_local_owner &&
            g_queued_lua_registered_spell_casts.size() >=
                kLuaRegisteredSpellMaximumQueuedCasts) {
            return fail("Lua registered spell cast transport queue is full.");
        }
        if (g_next_lua_registered_spell_cast_request_id == 0 ||
            g_next_lua_registered_spell_cast_request_id >
                static_cast<std::uint64_t>(INT64_MAX)) {
            g_next_lua_registered_spell_cast_request_id = 1;
        }
        request.request_id =
            g_next_lua_registered_spell_cast_request_id++;
        if (!targets_local_owner) {
            g_queued_lua_registered_spell_casts.push_back({request});
        }
    }

    if (targets_local_owner &&
        !sdmod::QueueLuaRegisteredSpellCastRequest(request, error_message)) {
        return false;
    }
    if (request_id != nullptr) {
        *request_id = request.request_id;
    }
    if (owner_participant_id != nullptr) {
        *owner_participant_id = selected_owner_participant_id;
    }
    if (local_owner != nullptr) {
        *local_owner = targets_local_owner;
    }
    return true;
}

void ApplyLuaRegisteredSpellCastPacket(
    const LuaRegisteredSpellCastPacket& packet,
    const TransportPeerEndpoint& from,
    std::uint64_t now_ms) {
    if (!IsLocalTransportClient() ||
        !IsConfiguredRemoteAuthorityEndpoint(from) ||
        packet.authority_participant_id == 0 ||
        packet.owner_participant_id != g_local_transport.local_peer_id ||
        packet.request_id == 0 || packet.content_id == 0 ||
        packet.flags != 0 ||
        std::any_of(
            std::begin(packet.reserved),
            std::end(packet.reserved),
            [](std::uint8_t value) { return value != 0; }) ||
        (from.backend == GameplayTransportBackend::Steam &&
         packet.authority_participant_id != from.steam_id)) {
        return;
    }
    if (g_local_transport.received_lua_registered_spell_cast_request_ids.find(
            packet.request_id) !=
        g_local_transport.received_lua_registered_spell_cast_request_ids.end()) {
        return;
    }

    LuaRegisteredSpellCastRequest request;
    request.authority_participant_id = packet.authority_participant_id;
    request.owner_participant_id = packet.owner_participant_id;
    request.request_id = packet.request_id;
    request.content_id = packet.content_id;
    request.target_network_actor_id = packet.target_network_actor_id;
    request.origin_x = packet.origin_x;
    request.origin_y = packet.origin_y;
    request.aim_x = packet.aim_x;
    request.aim_y = packet.aim_y;
    std::string queue_error;
    if (!sdmod::QueueLuaRegisteredSpellCastRequest(request, &queue_error)) {
        Log(
            "lua_spells: rejected received owner-routed cast. request_id=" +
            std::to_string(packet.request_id) + " error=" + queue_error);
        return;
    }

    UpsertPeerEndpoint(from, packet.authority_participant_id, now_ms);
    g_local_transport.received_lua_registered_spell_cast_request_ids.insert(
        packet.request_id);
    g_local_transport.received_lua_registered_spell_cast_request_order.push_back(
        packet.request_id);
    while (g_local_transport
               .received_lua_registered_spell_cast_request_order.size() >
           kLuaRegisteredSpellMaximumRememberedCasts) {
        const auto expired = g_local_transport
            .received_lua_registered_spell_cast_request_order.front();
        g_local_transport.received_lua_registered_spell_cast_request_order
            .pop_front();
        g_local_transport.received_lua_registered_spell_cast_request_ids.erase(
            expired);
    }
    Log(
        "lua_spells: accepted owner-routed cast. request_id=" +
        std::to_string(packet.request_id) +
        " content_id=" + std::to_string(packet.content_id));
}
