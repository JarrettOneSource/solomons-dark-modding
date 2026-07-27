constexpr std::uint32_t kSyntheticPrimaryCastMaximumHoldMs = 5000;

bool RefreshSyntheticCastPacketPose(
    const ParticipantInfo& participant,
    CastPacket* packet) {
    if (packet == nullptr) {
        return false;
    }

    float position_x = participant.runtime.position_x;
    float position_y = participant.runtime.position_y;
    SDModParticipantGameplayState gameplay_state;
    if (TryGetParticipantGameplayState(
            participant.participant_id,
            &gameplay_state) &&
        gameplay_state.entity_materialized &&
        gameplay_state.actor_address != 0 &&
        std::isfinite(gameplay_state.x) &&
        std::isfinite(gameplay_state.y)) {
        position_x = gameplay_state.x;
        position_y = gameplay_state.y;
    }
    const auto delta_x = packet->aim_target_x - position_x;
    const auto delta_y = packet->aim_target_y - position_y;
    const auto distance_squared =
        delta_x * delta_x + delta_y * delta_y;
    if (!std::isfinite(position_x) ||
        !std::isfinite(position_y) ||
        !std::isfinite(distance_squared) ||
        distance_squared <= 0.0001f) {
        return false;
    }

    const auto distance = std::sqrt(distance_squared);
    packet->position_x = position_x;
    packet->position_y = position_y;
    packet->direction_x = delta_x / distance;
    packet->direction_y = delta_y / distance;
    constexpr float kRadiansToDegrees =
        57.2957795130823208767981548141051703f;
    packet->heading = static_cast<float>(
        std::atan2(packet->direction_y, packet->direction_x) *
            kRadiansToDegrees +
        90.0f);
    while (packet->heading < 0.0f) {
        packet->heading += 360.0f;
    }
    while (packet->heading >= 360.0f) {
        packet->heading -= 360.0f;
    }
    packet->run_nonce = participant.runtime.run_nonce;
    return true;
}

bool BuildSyntheticParticipantCastPacket(
    const ParticipantInfo& participant,
    SyntheticParticipantTransportState* transport_state,
    std::int32_t skill_slot,
    float target_x,
    float target_y,
    CastPacket* packet,
    std::string* error_message) {
    if (packet == nullptr ||
        transport_state == nullptr ||
        !std::isfinite(target_x) ||
        !std::isfinite(target_y) ||
        skill_slot < 0 ||
        skill_slot >
            static_cast<std::int32_t>(kSecondaryLoadoutSlotCount)) {
        if (error_message != nullptr) {
            *error_message =
                "The synthetic cast request is invalid.";
        }
        return false;
    }

    const bool primary = skill_slot == 0;
    const auto secondary_slot = skill_slot - 1;
    const auto skill_id =
        primary
            ? (participant.character_profile.loadout.primary_entry_index >= 0
                   ? participant.character_profile.loadout.primary_entry_index
                   : ResolveNativePrimaryEntryForElement(
                         participant.character_profile.element_id))
            : participant.character_profile.loadout.secondary_entry_indices[
                  static_cast<std::size_t>(secondary_slot)];
    if (skill_id < 0) {
        if (error_message != nullptr) {
            *error_message =
                primary
                    ? "The bot primary spell selection is unavailable."
                    : "The requested bot secondary slot is empty.";
        }
        return false;
    }

    auto cast_sequence = transport_state->next_cast_sequence++;
    if (cast_sequence == 0) {
        cast_sequence = transport_state->next_cast_sequence++;
    }

    CastPacket built{};
    built.header = MakePacketHeader(
        PacketKind::Cast,
        g_local_transport.next_sequence++);
    built.participant_id = participant.participant_id;
    built.cast_sequence = cast_sequence;
    built.cast_kind = static_cast<std::uint8_t>(
        primary ? CastKind::Primary : CastKind::Secondary);
    built.secondary_slot = static_cast<std::int8_t>(
        primary ? -1 : secondary_slot);
    built.input_phase = static_cast<std::uint8_t>(
        CastInputPhase::Pressed);
    built.input_flags =
        primary ? 0 : CastInputFlagCursorWorldPlacement;
    built.skill_id = skill_id;
    built.element_id = participant.character_profile.element_id;
    built.discipline_id = static_cast<std::int32_t>(
        participant.character_profile.discipline_id);
    built.primary_entry_index =
        participant.character_profile.loadout.primary_entry_index;
    built.primary_combo_entry_index =
        participant.character_profile.loadout.primary_combo_entry_index;
    for (std::size_t index = 0;
         index <
             participant.character_profile.loadout
                 .secondary_entry_indices.size();
         ++index) {
        built.queued_secondary_entry_indices[index] =
            participant.character_profile.loadout
                .secondary_entry_indices[index];
    }
    built.aim_target_x = target_x;
    built.aim_target_y = target_y;
    built.cursor_world_x = primary ? 0.0f : target_x;
    built.cursor_world_y = primary ? 0.0f : target_y;
    if (!RefreshSyntheticCastPacketPose(
            participant,
            &built)) {
        if (error_message != nullptr) {
            *error_message =
                "The bot does not have a usable materialized cast origin.";
        }
        return false;
    }

    QueuedLocalCastEvent target_event{};
    target_event.cast_kind =
        primary ? CastKind::Primary : CastKind::Secondary;
    target_event.secondary_slot =
        primary ? -1 : secondary_slot;
    target_event.skill_id = skill_id;
    target_event.position_x = built.position_x;
    target_event.position_y = built.position_y;
    target_event.direction_x = built.direction_x;
    target_event.direction_y = built.direction_y;
    target_event.has_aim_target = true;
    target_event.aim_target_x = target_x;
    target_event.aim_target_y = target_y;
    target_event.has_cursor_world_placement = !primary;
    target_event.cursor_world_x = built.cursor_world_x;
    target_event.cursor_world_y = built.cursor_world_y;
    built.target_network_actor_id =
        ResolveLocalCastTargetNetworkActorId(
            target_event,
            built.position_x,
            built.position_y,
            built.direction_x,
            built.direction_y);

    *packet = built;
    return true;
}

bool InjectSyntheticParticipantCastPacket(
    CastPacket packet,
    CastInputPhase phase,
    std::uint64_t now_ms) {
    const auto runtime_state = SnapshotRuntimeState();
    const auto* participant =
        FindParticipant(
            runtime_state,
            packet.participant_id);
    if (participant == nullptr ||
        !IsLuaControlledParticipant(*participant) ||
        !RefreshSyntheticCastPacketPose(
            *participant,
            &packet)) {
        return false;
    }
    packet.header = MakePacketHeader(
        PacketKind::Cast,
        g_local_transport.next_sequence++);
    packet.input_phase =
        static_cast<std::uint8_t>(phase);

    const bool accepted =
        ApplyParticipantCastPacket(
            packet,
            TransportPeerEndpoint{},
            now_ms,
            true);
    if (accepted) {
        Log(
            "Multiplayer synthetic cast injected. participant_id=" +
            std::to_string(packet.participant_id) +
            " cast_sequence=" +
            std::to_string(packet.cast_sequence) +
            " phase=" +
            CastInputPhaseLabel(packet.input_phase) +
            " skill_id=" +
            std::to_string(packet.skill_id));
    }
    return accepted;
}

bool QueueSyntheticParticipantCastInternal(
    std::uint64_t participant_id,
    std::int32_t skill_slot,
    float target_x,
    float target_y,
    std::uint32_t hold_ms,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if ((g_local_transport.initialized &&
         !g_local_transport.is_host) ||
        participant_id == 0) {
        if (error_message != nullptr) {
            *error_message =
                "Only the multiplayer host can control a synthetic participant.";
        }
        return false;
    }
    if (hold_ms >
        kSyntheticPrimaryCastMaximumHoldMs) {
        if (error_message != nullptr) {
            *error_message =
                "Bot cast hold_ms must be between 0 and 5000.";
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
                "The bot handle no longer names an active synthetic participant.";
        }
        return false;
    }
    if (!participant->runtime.valid ||
        !participant->runtime.in_run ||
        participant->runtime.scene_intent.kind !=
            ParticipantSceneIntentKind::Run ||
        IsParticipantGameplayInertForDeath(*participant)) {
        if (error_message != nullptr) {
            *error_message =
                "The bot is not alive and materialized in the active run.";
        }
        return false;
    }

    auto* transport_state =
        EnsureSyntheticParticipantTransportState(
            participant_id);
    if (transport_state == nullptr) {
        if (error_message != nullptr) {
            *error_message =
                "The bot transport epoch is unavailable.";
        }
        return false;
    }

    const auto now_ms =
        static_cast<std::uint64_t>(GetTickCount64());
    if (transport_state->primary_cast_active) {
        const auto previous =
            transport_state->active_primary_cast;
        transport_state->primary_cast_active = false;
        if (!InjectSyntheticParticipantCastPacket(
                previous,
                CastInputPhase::Released,
                now_ms)) {
            if (error_message != nullptr) {
                *error_message =
                    "The previous bot primary cast could not be released.";
            }
            return false;
        }
    }

    CastPacket packet{};
    if (!BuildSyntheticParticipantCastPacket(
            *participant,
            transport_state,
            skill_slot,
            target_x,
            target_y,
            &packet,
            error_message)) {
        return false;
    }
    if (!InjectSyntheticParticipantCastPacket(
            packet,
            CastInputPhase::Pressed,
            now_ms)) {
        if (error_message != nullptr &&
            error_message->empty()) {
            *error_message =
                "The bot cast was rejected by replicated cast ingress.";
        }
        return false;
    }

    if (skill_slot == 0) {
        transport_state->primary_cast_active = true;
        transport_state->active_primary_cast = packet;
        transport_state->next_primary_held_send_ms =
            now_ms + kLocalCastInputUpdateIntervalMs;
        transport_state->primary_release_ms =
            now_ms + hold_ms;
    }
    return true;
}

void ServiceSyntheticParticipantCastInputs(
    std::uint64_t now_ms) {
    if (g_local_transport.initialized &&
        !g_local_transport.is_host) {
        return;
    }

    for (auto& entry :
         g_local_transport.synthetic_participants) {
        auto& state = entry.second;
        if (!state.primary_cast_active) {
            continue;
        }

        if (now_ms >= state.primary_release_ms) {
            const auto packet =
                state.active_primary_cast;
            state.primary_cast_active = false;
            (void)InjectSyntheticParticipantCastPacket(
                packet,
                CastInputPhase::Released,
                now_ms);
            continue;
        }
        if (now_ms <
            state.next_primary_held_send_ms) {
            continue;
        }

        if (InjectSyntheticParticipantCastPacket(
                state.active_primary_cast,
                CastInputPhase::Held,
                now_ms)) {
            state.next_primary_held_send_ms =
                now_ms +
                kLocalCastInputUpdateIntervalMs;
        } else {
            state.primary_cast_active = false;
        }
    }
}
