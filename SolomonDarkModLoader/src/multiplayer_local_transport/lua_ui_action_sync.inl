constexpr std::size_t kMaximumQueuedLuaUiActionRequests = 64;

bool CopyLuaUiPacketString(
    std::string_view value,
    char* destination,
    std::size_t capacity) {
    if (destination == nullptr || capacity < 2 || value.empty() ||
        value.size() >= capacity) {
        return false;
    }
    std::memset(destination, 0, capacity);
    std::memcpy(destination, value.data(), value.size());
    return true;
}

bool ReadLuaUiPacketString(
    const char* source,
    std::size_t capacity,
    std::string* value) {
    if (source == nullptr || value == nullptr || capacity < 2) {
        return false;
    }
    const auto* terminator = static_cast<const char*>(
        std::memchr(source, '\0', capacity));
    if (terminator == nullptr || terminator == source) {
        return false;
    }
    value->assign(source, static_cast<std::size_t>(terminator - source));
    return true;
}

bool QueueLuaUiSimulationActionInternal(
    std::string_view mod_id,
    std::string_view surface_id,
    std::string_view action_id,
    std::uint64_t* request_id,
    std::string* error_message) {
    if (request_id != nullptr) *request_id = 0;
    if (error_message != nullptr) error_message->clear();
    auto fail = [&](const char* message) {
        if (error_message != nullptr) *error_message = message;
        return false;
    };
    if (!IsLocalTransportClient()) {
        return fail("Lua UI simulation action routing requires a multiplayer client");
    }
    if (g_local_transport.local_peer_id == 0 ||
        g_local_transport.local_session_nonce == 0) {
        return fail("Lua UI simulation action routing has no participant session identity");
    }
    if (mod_id.empty() || mod_id.size() >= kLuaUiModIdPacketBytes ||
        surface_id.empty() || surface_id.size() >= kLuaUiIdentifierPacketBytes ||
        action_id.empty() || action_id.size() >= kLuaUiIdentifierPacketBytes) {
        return fail("Lua UI simulation action identity exceeds the protocol bounds");
    }

    std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
    if (g_queued_lua_ui_action_requests.size() >=
        kMaximumQueuedLuaUiActionRequests) {
        return fail("Lua UI simulation action route queue is full");
    }
    QueuedLuaUiActionRequest request;
    request.request_id = g_next_lua_ui_action_request_id++;
    request.mod_id.assign(mod_id.data(), mod_id.size());
    request.surface_id.assign(surface_id.data(), surface_id.size());
    request.action_id.assign(action_id.data(), action_id.size());
    g_queued_lua_ui_action_requests.push_back(request);
    if (request_id != nullptr) *request_id = request.request_id;
    return true;
}

std::vector<QueuedLuaUiActionRequest> TakeQueuedLuaUiActionRequests() {
    std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
    std::vector<QueuedLuaUiActionRequest> requests;
    requests.swap(g_queued_lua_ui_action_requests);
    return requests;
}

void RestoreQueuedLuaUiActionRequests(
    std::vector<QueuedLuaUiActionRequest> requests) {
    std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
    requests.insert(
        requests.end(),
        std::make_move_iterator(g_queued_lua_ui_action_requests.begin()),
        std::make_move_iterator(g_queued_lua_ui_action_requests.end()));
    g_queued_lua_ui_action_requests = std::move(requests);
    if (g_queued_lua_ui_action_requests.size() >
        kMaximumQueuedLuaUiActionRequests) {
        g_queued_lua_ui_action_requests.resize(
            kMaximumQueuedLuaUiActionRequests);
    }
}

void SendQueuedLuaUiActionRequests() {
    if (!IsLocalTransportClient()) return;
    auto requests = TakeQueuedLuaUiActionRequests();
    if (requests.empty()) return;
    const auto endpoints = BuildKnownSendEndpoints();
    if (endpoints.empty()) {
        RestoreQueuedLuaUiActionRequests(std::move(requests));
        return;
    }

    for (const auto& request : requests) {
        LuaUiActionRequestPacket packet{};
        packet.header = MakePacketHeader(
            PacketKind::LuaUiActionRequest,
            g_local_transport.next_sequence++);
        packet.participant_id = g_local_transport.local_peer_id;
        packet.participant_session_nonce =
            g_local_transport.local_session_nonce;
        packet.request_id = request.request_id;
        if (!CopyLuaUiPacketString(
                request.mod_id, packet.mod_id, sizeof(packet.mod_id)) ||
            !CopyLuaUiPacketString(
                request.surface_id, packet.surface_id, sizeof(packet.surface_id)) ||
            !CopyLuaUiPacketString(
                request.action_id, packet.action_id, sizeof(packet.action_id))) {
            continue;
        }
        for (const auto& endpoint : endpoints) {
            SendPacketToEndpoint(packet, endpoint);
        }
        Log(
            "Multiplayer Lua UI simulation action sent. participant_id=" +
            std::to_string(packet.participant_id) +
            " request_id=" + std::to_string(packet.request_id) +
            " mod=" + request.mod_id + " action=" +
            request.surface_id + "." + request.action_id);
    }
}

void ApplyLuaUiActionRequestPacket(
    const LuaUiActionRequestPacket& packet,
    const TransportPeerEndpoint& from,
    std::uint64_t) {
    if (!IsLocalTransportHost() || packet.participant_id == 0 ||
        packet.participant_id == g_local_transport.local_peer_id ||
        packet.participant_session_nonce == 0 || packet.request_id == 0) {
        return;
    }
    const auto peer = std::find_if(
        g_local_transport.peers.begin(), g_local_transport.peers.end(),
        [&](const LocalPeerEndpoint& candidate) {
            return candidate.participant_id == packet.participant_id &&
                SameEndpoint(candidate.endpoint, from);
        });
    const auto nonce =
        g_local_transport.session_nonce_by_participant.find(packet.participant_id);
    if (peer == g_local_transport.peers.end() ||
        nonce == g_local_transport.session_nonce_by_participant.end() ||
        nonce->second != packet.participant_session_nonce) {
        return;
    }
    auto& last_request =
        g_local_transport.last_lua_ui_action_request_by_participant[
            packet.participant_id];
    if (packet.request_id <= last_request) {
        return;
    }

    std::string mod_id;
    std::string surface_id;
    std::string action_id;
    if (!ReadLuaUiPacketString(
            packet.mod_id, sizeof(packet.mod_id), &mod_id) ||
        !ReadLuaUiPacketString(
            packet.surface_id, sizeof(packet.surface_id), &surface_id) ||
        !ReadLuaUiPacketString(
            packet.action_id, sizeof(packet.action_id), &action_id)) {
        return;
    }
    std::string error;
    if (!sdmod::QueueRemoteLuaUiSimulationAction(
            mod_id,
            surface_id,
            action_id,
            packet.participant_id,
            packet.request_id,
            &error)) {
        Log(
            "Multiplayer Lua UI simulation action rejected. participant_id=" +
            std::to_string(packet.participant_id) + " error=" + error);
        return;
    }
    last_request = packet.request_id;
}
