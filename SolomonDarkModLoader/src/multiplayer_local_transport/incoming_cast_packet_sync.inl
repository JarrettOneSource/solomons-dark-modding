// Inbound replicated cast lifecycle and native playback.

void ApplyRemoteCastPacket(
    const CastPacket& packet,
    const TransportPeerEndpoint& from,
    std::uint64_t now_ms) {
    const auto cast_kind = static_cast<CastKind>(packet.cast_kind);
    const auto input_phase = static_cast<CastInputPhase>(packet.input_phase);
    auto log_cast_drop = [&](const std::string& reason) {
        Log(
            "Multiplayer remote cast ignored. reason=" + reason +
            " participant_id=" + std::to_string(packet.participant_id) +
            " cast_sequence=" + std::to_string(packet.cast_sequence) +
            " packet_sequence=" + std::to_string(packet.header.sequence) +
            " phase=" + CastInputPhaseLabel(packet.input_phase) +
            " skill_id=" + std::to_string(packet.skill_id) +
            " run_nonce=" + std::to_string(packet.run_nonce));
    };

    if (packet.participant_id == 0 ||
        packet.participant_id == kLocalParticipantId ||
        packet.participant_id == g_local_transport.local_peer_id ||
        packet.cast_sequence == 0 ||
        packet.skill_id < 0 ||
        (cast_kind != CastKind::Primary && cast_kind != CastKind::Secondary) ||
        !IsCastInputPhaseValue(packet.input_phase) ||
        (cast_kind == CastKind::Primary && packet.secondary_slot != -1) ||
        (cast_kind == CastKind::Secondary &&
         (packet.secondary_slot < 0 ||
          packet.secondary_slot >=
              static_cast<std::int32_t>(kSecondaryLoadoutSlotCount) ||
          input_phase != CastInputPhase::Pressed)) ||
        !std::isfinite(packet.position_x) ||
        !std::isfinite(packet.position_y) ||
        !std::isfinite(packet.heading) ||
        !std::isfinite(packet.aim_target_x) ||
        !std::isfinite(packet.aim_target_y)) {
        log_cast_drop("invalid_packet");
        return;
    }

    UpsertPeerEndpoint(from, packet.participant_id, now_ms);
    RelayPacketToPeers(packet, from);

    const auto last_sequence_it =
        g_local_transport.last_cast_sequence_by_participant.find(packet.participant_id);
    if (last_sequence_it != g_local_transport.last_cast_sequence_by_participant.end() &&
        packet.cast_sequence != last_sequence_it->second &&
        !IsPacketSequenceNewer(packet.cast_sequence, last_sequence_it->second)) {
        log_cast_drop(
            "stale_cast_sequence last_cast_sequence=" +
            std::to_string(last_sequence_it->second));
        return;
    }
    auto& input_tracker = g_local_transport.remote_cast_inputs_by_participant[packet.participant_id];
    if (input_tracker.cast_sequence != packet.cast_sequence) {
        input_tracker = RemoteCastInputTracker{};
        input_tracker.cast_sequence = packet.cast_sequence;
        g_local_transport.last_cast_sequence_by_participant[packet.participant_id] =
            packet.cast_sequence;
    } else if (input_tracker.last_packet_sequence != 0 &&
               !IsPacketSequenceNewer(
                   packet.header.sequence,
                   input_tracker.last_packet_sequence)) {
        log_cast_drop(
            "stale_packet_sequence last_packet_sequence=" +
            std::to_string(input_tracker.last_packet_sequence));
        return;
    }
    input_tracker.last_packet_sequence = packet.header.sequence;
    input_tracker.last_packet_ms = now_ms;

    const auto runtime_state = SnapshotRuntimeState();
    const auto* participant = FindParticipant(runtime_state, packet.participant_id);
    if (participant == nullptr) {
        log_cast_drop("participant_missing");
        return;
    }
    if (!IsRemoteParticipant(*participant)) {
        log_cast_drop(
            "participant_not_remote kind=" +
            std::to_string(static_cast<int>(participant->kind)));
        return;
    }
    if (!IsNativeControlledParticipant(*participant)) {
        log_cast_drop(
            "participant_not_native_controlled controller=" +
            std::to_string(static_cast<int>(participant->controller_kind)));
        return;
    }
    if (!participant->runtime.valid) {
        log_cast_drop("participant_runtime_invalid");
        return;
    }
    if (!participant->runtime.in_run) {
        log_cast_drop("participant_not_in_run");
        return;
    }
    if (participant->runtime.scene_intent.kind != ParticipantSceneIntentKind::Run) {
        log_cast_drop(
            "participant_scene_not_run scene_intent=" +
            std::to_string(static_cast<int>(participant->runtime.scene_intent.kind)));
        return;
    }
    if (participant->runtime.run_nonce != 0 &&
        packet.run_nonce != 0 &&
        participant->runtime.run_nonce != packet.run_nonce) {
        log_cast_drop(
            "run_nonce_mismatch participant_run_nonce=" +
            std::to_string(participant->runtime.run_nonce));
        return;
    }
    if (cast_kind == CastKind::Secondary) {
        const auto secondary_slot = static_cast<std::size_t>(packet.secondary_slot);
        const auto* owned_entry =
            FindProgressionBookEntryById(
                participant->owned_progression,
                packet.skill_id);
        if (packet.queued_secondary_entry_indices[secondary_slot] != packet.skill_id ||
            owned_entry == nullptr ||
            owned_entry->active == 0) {
            log_cast_drop("secondary_skill_not_owned_by_packet_and_progression");
            return;
        }
    }

    SDModParticipantGameplayState gameplay_state;
    if (!TryGetParticipantGameplayState(packet.participant_id, &gameplay_state) ||
        !gameplay_state.entity_materialized ||
        gameplay_state.actor_address == 0) {
        log_cast_drop(
            "participant_not_materialized actor=" +
            HexString(gameplay_state.actor_address) +
            " entity_materialized=" +
            std::to_string(gameplay_state.entity_materialized ? 1 : 0));
        return;
    }

    UpdateRuntimeState([&](RuntimeState& state) {
        auto* live_participant = FindParticipant(state, packet.participant_id);
        if (live_participant == nullptr) {
            return;
        }
        live_participant->runtime.transform_valid = true;
        live_participant->runtime.position_x = packet.position_x;
        live_participant->runtime.position_y = packet.position_y;
        live_participant->runtime.heading = packet.heading;
        if (cast_kind == CastKind::Secondary) {
            const auto secondary_slot =
                static_cast<std::size_t>(packet.secondary_slot);
            // A native belt edit and its cast can occur between consecutive
            // 20 Hz state packets. The hook's live belt snapshot is therefore
            // the freshest authenticated state for this one slot.
            live_participant->character_profile.loadout
                .secondary_entry_indices[secondary_slot] = packet.skill_id;
            live_participant->runtime
                .queued_secondary_entry_indices[secondary_slot] = packet.skill_id;
        }

        ParticipantTransformSample sample;
        sample.valid = true;
        sample.received_ms = now_ms;
        sample.sequence = packet.header.sequence;
        sample.run_nonce = packet.run_nonce;
        sample.scene_intent = live_participant->runtime.scene_intent;
        sample.position_x = packet.position_x;
        sample.position_y = packet.position_y;
        sample.heading = packet.heading;
        AppendParticipantTransformSample(live_participant, sample);
    });

    if (cast_kind == CastKind::Secondary && packet.skill_id == 0x33) {
        std::string dampen_error;
        if (!QueueMultiplayerDampenEffect(
                packet.participant_id,
                packet.cast_sequence,
                packet.position_x,
                packet.position_y,
                &dampen_error)) {
            log_cast_drop("dampen_behavior_queue_failed error=" + dampen_error);
            return;
        }
    }

    BotCastRequest request;
    request.bot_id = packet.participant_id;
    request.kind = cast_kind == CastKind::Secondary
                       ? BotCastKind::Secondary
                       : BotCastKind::Primary;
    request.secondary_slot = packet.secondary_slot;
    request.skill_id = packet.skill_id;
    request.has_origin_transform = true;
    request.origin_position_x = packet.position_x;
    request.origin_position_y = packet.position_y;
    request.has_origin_heading = true;
    request.origin_heading = packet.heading;
    request.has_aim_target = true;
    request.aim_target_x = packet.aim_target_x;
    request.aim_target_y = packet.aim_target_y;
    request.has_aim_angle = true;
    request.aim_angle = packet.heading;

    SDModSceneActorState cast_target;
    const bool resolved_target_by_id =
        packet.target_network_actor_id != 0 &&
        TryFindLocalRunEnemyByNetworkIdInternal(packet.target_network_actor_id, &cast_target) &&
        IsSaneExplicitCastTarget(cast_target, packet.position_x, packet.position_y);
    uintptr_t resolved_target_actor_address = 0;
    if (resolved_target_by_id) {
        resolved_target_actor_address = cast_target.actor_address;
        request.target_actor_address = resolved_target_actor_address;
        request.aim_target_x = cast_target.x;
        request.aim_target_y = cast_target.y;
    }

    const auto phase = input_phase;
    const bool release_phase = phase == CastInputPhase::Released;
    request.cast_sequence = packet.cast_sequence;
    request.remote_input_controlled = true;
    if (cast_kind == CastKind::Secondary) {
        if (!input_tracker.start_queued) {
            if (QueueBotCast(request)) {
                input_tracker.start_queued = true;
                Log(
                    "Multiplayer remote secondary cast queued. participant_id=" +
                    std::to_string(packet.participant_id) +
                    " cast_sequence=" + std::to_string(packet.cast_sequence) +
                    " skill_id=" + std::to_string(packet.skill_id) +
                    " secondary_slot=" + std::to_string(packet.secondary_slot) +
                    " target_network_actor_id=" +
                    std::to_string(packet.target_network_actor_id) +
                    " target_actor=" + HexString(request.target_actor_address));
            } else {
                log_cast_drop("queue_secondary_bot_cast_failed");
            }
        }
        return;
    }

    BotCastInputState cast_input_state{};
    cast_input_state.bot_id = packet.participant_id;
    cast_input_state.active = !release_phase;
    cast_input_state.release_requested = release_phase;
    cast_input_state.cast_sequence = packet.cast_sequence;
    cast_input_state.last_update_ms = now_ms;
    cast_input_state.has_aim_target = true;
    cast_input_state.aim_target_x = request.aim_target_x;
    cast_input_state.aim_target_y = request.aim_target_y;
    cast_input_state.has_aim_angle = true;
    cast_input_state.aim_angle = packet.heading;
    cast_input_state.target_actor_address = resolved_target_actor_address;
    (void)UpdateBotCastInput(cast_input_state);

    if (release_phase) {
        input_tracker.release_seen = true;
        Log(
            "Multiplayer remote cast input release. participant_id=" +
            std::to_string(packet.participant_id) +
            " cast_sequence=" + std::to_string(packet.cast_sequence) +
            " skill_id=" + std::to_string(packet.skill_id));
        return;
    }

    if (!input_tracker.start_queued) {
        if (QueueBotCast(request)) {
            input_tracker.start_queued = true;
            Log(
                "Multiplayer remote cast queued. participant_id=" +
                std::to_string(packet.participant_id) +
                " cast_sequence=" + std::to_string(packet.cast_sequence) +
                " phase=" + CastInputPhaseLabel(packet.input_phase) +
                " skill_id=" + std::to_string(packet.skill_id) +
                " target_network_actor_id=" + std::to_string(packet.target_network_actor_id) +
                " target_actor=" + HexString(request.target_actor_address) +
                " target_source=" + std::string(
                    resolved_target_by_id
                        ? "network_id"
                        : (packet.target_network_actor_id != 0 ? "invalid_network_id" : "none")));
        } else {
            log_cast_drop("queue_bot_cast_failed");
        }
    }
}
