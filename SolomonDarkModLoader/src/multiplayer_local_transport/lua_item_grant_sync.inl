std::vector<QueuedAuthoritativeLuaItemGrant>
TakeQueuedAuthoritativeLuaItemGrants() {
    std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
    std::vector<QueuedAuthoritativeLuaItemGrant> grants;
    grants.swap(g_queued_authoritative_lua_item_grants);
    return grants;
}

void SendQueuedAuthoritativeLuaItemGrants() {
    if (!IsLocalTransportHost()) {
        return;
    }

    for (const auto& grant : TakeQueuedAuthoritativeLuaItemGrants()) {
        LuaItemGrantPacket packet{};
        packet.header = MakePacketHeader(
            PacketKind::LuaItemGrant,
            g_local_transport.next_sequence++);
        packet.authority_participant_id = g_local_transport.local_peer_id;
        packet.target_participant_id = grant.target_participant_id;
        packet.request_id = grant.request_id;
        packet.content_id = grant.content_id;
        if (grant.color_state_valid) {
            packet.flags |= LuaItemGrantFlagColorState;
            std::copy(
                grant.color_state.begin(),
                grant.color_state.end(),
                packet.color_state);
        }
        SendPacketToParticipantOrPeers(packet, grant.target_participant_id);
        Log(
            "lua_items: sent authoritative item grant. request_id=" +
            std::to_string(grant.request_id) +
            " target_participant_id=" +
            std::to_string(grant.target_participant_id) +
            " content_id=" + std::to_string(grant.content_id));
    }
}

bool QueueAuthoritativeLuaItemGrantInternal(
    std::uint64_t content_id,
    std::uint64_t requested_target_participant_id,
    const std::array<std::uint8_t, kParticipantVisualLinkColorBlockBytes>&
        color_state,
    bool color_state_valid,
    std::uint64_t* request_id,
    std::uint64_t* target_participant_id,
    bool* local_target,
    std::string* error_message) {
    if (request_id != nullptr) {
        *request_id = 0;
    }
    if (target_participant_id != nullptr) {
        *target_participant_id = 0;
    }
    if (local_target != nullptr) {
        *local_target = false;
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

    if (content_id == 0) {
        return fail("Lua item grant content id must be nonzero.");
    }
    if (!IsLuaModSimulationAuthority()) {
        return fail("Only the simulation authority may grant Lua items.");
    }
    if (!color_state_valid &&
        std::any_of(
            color_state.begin(),
            color_state.end(),
            [](std::uint8_t value) { return value != 0; })) {
        return fail("Lua item grant color bytes require the color-state flag.");
    }

    const auto local_wire_participant_id =
        g_local_transport.initialized
            ? g_local_transport.local_peer_id
            : kLocalParticipantId;
    const bool targets_local_participant =
        requested_target_participant_id == 0 ||
        requested_target_participant_id == kLocalParticipantId ||
        requested_target_participant_id == local_wire_participant_id;
    if (!targets_local_participant &&
        (!IsLocalTransportHost() ||
         std::none_of(
             g_local_transport.peers.begin(),
             g_local_transport.peers.end(),
             [&](const LocalPeerEndpoint& peer) {
                 return peer.participant_id ==
                     requested_target_participant_id;
             }))) {
        return fail(
            "Lua item grant target is not a connected remote participant.");
    }

    std::uint64_t assigned_request_id = 0;
    {
        std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
        if (!targets_local_participant &&
            g_queued_authoritative_lua_item_grants.size() >=
                kLuaItemGrantMaximumQueuedRequests) {
            return fail("Lua item grant transport queue is full.");
        }
        if (g_next_lua_item_grant_request_id == 0) {
            g_next_lua_item_grant_request_id = 1;
        }
        assigned_request_id = g_next_lua_item_grant_request_id++;
        if (!targets_local_participant) {
            QueuedAuthoritativeLuaItemGrant grant;
            grant.request_id = assigned_request_id;
            grant.target_participant_id = requested_target_participant_id;
            grant.content_id = content_id;
            grant.color_state_valid = color_state_valid;
            grant.color_state = color_state;
            g_queued_authoritative_lua_item_grants.push_back(
                std::move(grant));
        }
    }

    if (targets_local_participant) {
        std::string queue_error;
        if (!sdmod::QueueLuaItemGrantToLocalInventory(
                local_wire_participant_id,
                assigned_request_id,
                content_id,
                color_state,
                color_state_valid,
                &queue_error)) {
            if (error_message != nullptr) {
                *error_message = queue_error;
            }
            return false;
        }
    }

    if (request_id != nullptr) {
        *request_id = assigned_request_id;
    }
    if (target_participant_id != nullptr) {
        *target_participant_id = targets_local_participant
            ? kLocalParticipantId
            : requested_target_participant_id;
    }
    if (local_target != nullptr) {
        *local_target = targets_local_participant;
    }
    return true;
}

void ApplyLuaItemGrantPacket(
    const LuaItemGrantPacket& packet,
    const TransportPeerEndpoint& from,
    std::uint64_t now_ms) {
    if (!IsLocalTransportClient() ||
        !IsConfiguredRemoteAuthorityEndpoint(from) ||
        packet.authority_participant_id == 0 ||
        packet.target_participant_id != g_local_transport.local_peer_id ||
        packet.request_id == 0 ||
        packet.content_id == 0 ||
        (packet.flags & ~kLuaItemGrantKnownFlags) != 0 ||
        std::any_of(
            std::begin(packet.reserved),
            std::end(packet.reserved),
            [](std::uint8_t value) { return value != 0; }) ||
        (from.backend == GameplayTransportBackend::Steam &&
         packet.authority_participant_id != from.steam_id)) {
        return;
    }

    const bool color_state_valid =
        (packet.flags & LuaItemGrantFlagColorState) != 0;
    if (!color_state_valid &&
        std::any_of(
            std::begin(packet.color_state),
            std::end(packet.color_state),
            [](std::uint8_t value) { return value != 0; })) {
        return;
    }
    if (g_local_transport.received_lua_item_grant_request_ids.find(
            packet.request_id) !=
        g_local_transport.received_lua_item_grant_request_ids.end()) {
        return;
    }

    std::array<std::uint8_t, kParticipantVisualLinkColorBlockBytes>
        color_state = {};
    if (color_state_valid) {
        std::copy(
            std::begin(packet.color_state),
            std::end(packet.color_state),
            color_state.begin());
    }
    std::string queue_error;
    if (!sdmod::QueueLuaItemGrantToLocalInventory(
            packet.authority_participant_id,
            packet.request_id,
            packet.content_id,
            color_state,
            color_state_valid,
            &queue_error)) {
        Log(
            "lua_items: rejected received item grant. request_id=" +
            std::to_string(packet.request_id) +
            " content_id=" + std::to_string(packet.content_id) +
            " error=" + queue_error);
        return;
    }

    UpsertPeerEndpoint(from, packet.authority_participant_id, now_ms);
    g_local_transport.received_lua_item_grant_request_ids.insert(
        packet.request_id);
    g_local_transport.received_lua_item_grant_request_order.push_back(
        packet.request_id);
    while (g_local_transport.received_lua_item_grant_request_order.size() >
           kLuaItemGrantMaximumRememberedRequests) {
        const auto expired_request_id =
            g_local_transport.received_lua_item_grant_request_order.front();
        g_local_transport.received_lua_item_grant_request_order.pop_front();
        g_local_transport.received_lua_item_grant_request_ids.erase(
            expired_request_id);
    }
    Log(
        "lua_items: accepted authoritative item grant. authority_participant_id=" +
        std::to_string(packet.authority_participant_id) +
        " request_id=" + std::to_string(packet.request_id) +
        " content_id=" + std::to_string(packet.content_id));
}
