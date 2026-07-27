bool BuildSyntheticParticipantFramePacket(
    const RuntimeState& runtime_state,
    const ParticipantInfo& participant,
    std::uint64_t session_nonce,
    ParticipantFramePacket* packet) {
    if (packet == nullptr ||
        session_nonce == 0 ||
        !IsRemoteParticipant(participant) ||
        !IsLuaControlledParticipant(participant)) {
        return false;
    }

    *packet = ParticipantFramePacket{};
    packet->header = MakePacketHeader(
        PacketKind::ParticipantFrame,
        g_local_transport.next_sequence++);
    packet->participant_id = participant.participant_id;
    packet->participant_session_nonce = session_nonce;
    packet->authority_participant_id = g_local_transport.local_peer_id;
    PopulateParticipantFrameFields(
        participant,
        runtime_state,
        false,
        packet);
    packet->scene_kind = static_cast<std::uint8_t>(
        WorldSceneKindFromSceneIntent(
            participant.runtime.scene_intent));
    packet->region_index = participant.runtime.scene_intent.region_index;
    packet->region_type_id = participant.runtime.scene_intent.region_type_id;
    return true;
}

bool BuildSyntheticParticipantStatePacket(
    const RuntimeState& runtime_state,
    const ParticipantInfo& participant,
    std::uint64_t session_nonce,
    std::uint8_t state_flags,
    StatePacket* packet) {
    if (packet == nullptr ||
        session_nonce == 0 ||
        !IsRemoteParticipant(participant) ||
        !IsLuaControlledParticipant(participant) ||
        (state_flags & ~ParticipantStateFlagRetired) != 0) {
        return false;
    }

    *packet = StatePacket{};
    packet->header = MakePacketHeader(
        PacketKind::State,
        g_local_transport.next_sequence++);
    packet->participant_id = participant.participant_id;
    packet->participant_session_nonce = session_nonce;
    packet->authority_participant_id = g_local_transport.local_peer_id;
    packet->participant_state_flags = state_flags;
    PopulateParticipantFrameFields(
        participant,
        runtime_state,
        false,
        packet);
    PopulateParticipantStateFields(participant, packet);
    return true;
}

SyntheticParticipantTransportState*
EnsureSyntheticParticipantTransportState(
    std::uint64_t participant_id) {
    if ((g_local_transport.initialized &&
         !g_local_transport.is_host) ||
        participant_id == 0) {
        return nullptr;
    }

    auto [it, inserted] =
        g_local_transport.synthetic_participants.try_emplace(
            participant_id);
    if (inserted || it->second.session_nonce == 0) {
        it->second.session_nonce =
            GenerateTransportSessionNonce(participant_id);
        it->second.next_cast_sequence = 1;
        Log(
            "Multiplayer synthetic participant transport epoch registered. "
            "participant_id=" +
            std::to_string(participant_id) +
            " session_nonce=" +
            std::to_string(it->second.session_nonce) +
            " authority_participant_id=" +
            std::to_string(g_local_transport.local_peer_id));
    }
    return &it->second;
}

bool RegisterSyntheticParticipantTransportInternal(
    std::uint64_t participant_id,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (g_local_transport.initialized &&
        !g_local_transport.is_host) {
        if (error_message != nullptr) {
            *error_message =
                "Synthetic participants can only be registered by the transport host.";
        }
        return false;
    }

    const auto runtime_state = SnapshotRuntimeState();
    const auto* participant =
        FindParticipant(runtime_state, participant_id);
    if (participant == nullptr ||
        !IsRemoteParticipant(*participant) ||
        !IsLuaControlledParticipant(*participant)) {
        if (error_message != nullptr) {
            *error_message =
                "The participant is not an active host-owned Lua participant.";
        }
        return false;
    }

    g_local_transport.retired_synthetic_participants.erase(
        participant_id);
    auto* transport_state =
        EnsureSyntheticParticipantTransportState(participant_id);
    if (transport_state == nullptr) {
        if (error_message != nullptr) {
            *error_message =
                "The synthetic participant transport epoch could not be allocated.";
        }
        return false;
    }
    transport_state->last_state_send_ms = 0;
    transport_state->last_frame_send_ms = 0;
    return true;
}

bool RetireSyntheticParticipantTransportInternal(
    std::uint64_t participant_id,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (g_local_transport.initialized &&
        !g_local_transport.is_host) {
        if (error_message != nullptr) {
            *error_message =
                "Synthetic participants can only be retired by the transport host.";
        }
        return false;
    }

    const auto transport_it =
        g_local_transport.synthetic_participants.find(
            participant_id);
    if (transport_it ==
        g_local_transport.synthetic_participants.end()) {
        return true;
    }
    if (!g_local_transport.initialized) {
        g_local_transport.synthetic_participants.erase(
            transport_it);
        g_local_transport.remote_cast_inputs_by_participant.erase(
            participant_id);
        g_local_transport.last_cast_sequence_by_participant.erase(
            participant_id);
        return true;
    }
    const auto runtime_state = SnapshotRuntimeState();
    const auto* participant =
        FindParticipant(runtime_state, participant_id);
    if (participant == nullptr ||
        !IsRemoteParticipant(*participant) ||
        !IsLuaControlledParticipant(*participant)) {
        if (error_message != nullptr) {
            *error_message =
                "The synthetic participant disappeared before retirement could be serialized.";
        }
        return false;
    }

    StatePacket packet{};
    if (!BuildSyntheticParticipantStatePacket(
            runtime_state,
            *participant,
            transport_it->second.session_nonce,
            ParticipantStateFlagRetired,
            &packet)) {
        if (error_message != nullptr) {
            *error_message =
                "The synthetic participant retirement packet could not be built.";
        }
        return false;
    }

    SyntheticParticipantRetirementState retirement;
    retirement.packet = packet;
    retirement.created_ms =
        static_cast<std::uint64_t>(GetTickCount64());
    g_local_transport.retired_synthetic_participants[
        participant_id] = retirement;
    g_local_transport.synthetic_participants.erase(transport_it);
    Log(
        "Multiplayer synthetic participant transport epoch retired. "
        "participant_id=" +
        std::to_string(participant_id) +
        " session_nonce=" +
        std::to_string(packet.participant_session_nonce));
    return true;
}

struct SyntheticParticipantSceneSyncRequest {
    std::uint64_t participant_id = 0;
    MultiplayerCharacterProfile profile;
    ParticipantSceneIntent scene_intent;
    bool transform_valid = false;
    float position_x = 0.0f;
    float position_y = 0.0f;
    float heading = 0.0f;
};

void RefreshHostSyntheticParticipantSceneIntent() {
    if (!g_local_transport.is_host) {
        return;
    }

    const auto snapshot = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(snapshot);
    if (local == nullptr || !local->runtime.valid) {
        return;
    }

    auto host_scene_intent = local->runtime.scene_intent;
    if (host_scene_intent.kind == ParticipantSceneIntentKind::PrivateRegion) {
        host_scene_intent = DefaultParticipantSceneIntent();
    }
    std::vector<SyntheticParticipantSceneSyncRequest> sync_requests;
    UpdateRuntimeState([&](RuntimeState& state) {
        for (auto& participant : state.participants) {
            if (!IsRemoteParticipant(participant) ||
                !IsLuaControlledParticipant(participant)) {
                continue;
            }

            const bool scene_changed =
                participant.runtime.scene_intent.kind !=
                    host_scene_intent.kind ||
                participant.runtime.scene_intent.region_index !=
                    host_scene_intent.region_index ||
                participant.runtime.scene_intent.region_type_id !=
                    host_scene_intent.region_type_id;
            participant.runtime.scene_intent = host_scene_intent;
            participant.runtime.in_run =
                host_scene_intent.kind ==
                ParticipantSceneIntentKind::Run;
            participant.runtime.run_nonce =
                participant.runtime.in_run
                    ? local->runtime.run_nonce
                    : 0;
            participant.runtime.wave = local->runtime.wave;
            if (!scene_changed) {
                continue;
            }

            SyntheticParticipantSceneSyncRequest request;
            request.participant_id = participant.participant_id;
            request.profile = participant.character_profile;
            request.scene_intent = participant.runtime.scene_intent;
            request.transform_valid =
                participant.runtime.transform_valid;
            request.position_x = participant.runtime.position_x;
            request.position_y = participant.runtime.position_y;
            request.heading = participant.runtime.heading;
            sync_requests.push_back(std::move(request));
        }
    });

    for (const auto& request : sync_requests) {
        std::string error_message;
        if (!QueueParticipantEntitySync(
                request.participant_id,
                request.profile,
                request.scene_intent,
                request.transform_valid,
                request.transform_valid,
                request.position_x,
                request.position_y,
                request.heading,
                &error_message)) {
            Log(
                "Multiplayer synthetic participant scene sync could not be queued. "
                "participant_id=" +
                std::to_string(request.participant_id) +
                " scene=" +
                std::to_string(
                    static_cast<int>(request.scene_intent.kind)) +
                " error=" + error_message);
        }
    }
}
