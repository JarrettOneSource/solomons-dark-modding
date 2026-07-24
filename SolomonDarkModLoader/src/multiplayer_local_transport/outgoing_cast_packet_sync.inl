// Local cast packet construction, active-input tracking, and transmission.

std::vector<QueuedLocalCastEvent> TakeQueuedLocalCastEvents() {
    std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
    std::vector<QueuedLocalCastEvent> events;
    events.swap(g_queued_local_cast_events);
    return events;
}

bool IsCastInputPhaseValue(std::uint8_t phase) {
    return phase == static_cast<std::uint8_t>(CastInputPhase::Pressed) ||
           phase == static_cast<std::uint8_t>(CastInputPhase::Held) ||
           phase == static_cast<std::uint8_t>(CastInputPhase::Released);
}

const char* CastInputPhaseLabel(std::uint8_t phase) {
    switch (static_cast<CastInputPhase>(phase)) {
        case CastInputPhase::Pressed:
            return "pressed";
        case CastInputPhase::Held:
            return "held";
        case CastInputPhase::Released:
            return "released";
    }
    return "unknown";
}

std::uint64_t ResolveLocalCastTargetNetworkActorId(
    const QueuedLocalCastEvent& event,
    float position_x,
    float position_y,
    float direction_x,
    float direction_y) {
    const float aim_target_x =
        event.has_aim_target ? event.aim_target_x : position_x + direction_x * 512.0f;
    const float aim_target_y =
        event.has_aim_target ? event.aim_target_y : position_y + direction_y * 512.0f;
    if (event.target_network_actor_id != 0) {
        SDModSceneActorState target_actor;
        if (TryFindLocalRunEnemyByNetworkIdInternal(event.target_network_actor_id, &target_actor) &&
            IsSaneExplicitCastTarget(target_actor, position_x, position_y)) {
            return event.target_network_actor_id;
        }
        return 0;
    }

    if (event.target_actor_address != 0) {
        std::uint64_t target_network_actor_id = 0;
        if (TryResolveExplicitCastTargetNetworkActorId(
                event.target_actor_address,
                position_x,
                position_y,
                &target_network_actor_id)) {
            return target_network_actor_id;
        }
    }

    if (event.has_aim_target) {
        SDModSceneActorState target_actor;
        if (TryFindLocalRunEnemyForCastAim(
                position_x,
                position_y,
                direction_x,
                direction_y,
                aim_target_x,
                aim_target_y,
                &target_actor)) {
            return ResolveLocalRunEnemyNetworkActorId(target_actor);
        }
    }
    return 0;
}

bool BuildLocalCastPacket(
    const RuntimeState& runtime_state,
    const ParticipantInfo& local,
    const QueuedLocalCastEvent& event,
    std::uint32_t cast_sequence,
    CastInputPhase phase,
    CastPacket* packet) {
    if (packet == nullptr ||
        cast_sequence == 0 ||
        event.skill_id < 0 ||
        (event.cast_kind != CastKind::Primary &&
         event.cast_kind != CastKind::Secondary) ||
        (event.cast_kind == CastKind::Secondary &&
         (event.secondary_slot < 0 ||
          event.secondary_slot >=
              static_cast<std::int32_t>(kSecondaryLoadoutSlotCount))) ||
        (event.cast_kind == CastKind::Primary && event.secondary_slot != -1) ||
        (event.cast_kind == CastKind::Secondary && phase != CastInputPhase::Pressed) ||
        !std::isfinite(event.position_x) ||
        !std::isfinite(event.position_y) ||
        !std::isfinite(event.direction_x) ||
        !std::isfinite(event.direction_y) ||
        (event.has_cursor_world_placement &&
         (event.cast_kind != CastKind::Secondary ||
          !std::isfinite(event.cursor_world_x) ||
          !std::isfinite(event.cursor_world_y)))) {
        return false;
    }
    const auto cast_direction_length_squared =
        event.direction_x * event.direction_x +
        event.direction_y * event.direction_y;
    if (!std::isfinite(cast_direction_length_squared) ||
        cast_direction_length_squared <= 0.0001f) {
        return false;
    }
    constexpr float kCastRadiansToDegrees =
        57.2957795130823208767981548141051703f;
    float cast_heading = static_cast<float>(
        std::atan2(event.direction_y, event.direction_x) *
            kCastRadiansToDegrees +
        90.0f);
    while (cast_heading < 0.0f) {
        cast_heading += 360.0f;
    }
    while (cast_heading >= 360.0f) {
        cast_heading -= 360.0f;
    }

    (void)runtime_state;
    CastPacket built{};
    built.header = MakePacketHeader(PacketKind::Cast, g_local_transport.next_sequence++);
    built.participant_id = g_local_transport.local_peer_id;
    built.cast_sequence = cast_sequence;
    built.cast_kind = static_cast<std::uint8_t>(event.cast_kind);
    built.secondary_slot = static_cast<std::int8_t>(event.secondary_slot);
    built.input_phase = static_cast<std::uint8_t>(phase);
    built.input_flags = event.has_cursor_world_placement
                            ? CastInputFlagCursorWorldPlacement
                            : 0;
    built.run_nonce = local.runtime.run_nonce;
    built.target_network_actor_id =
        ResolveLocalCastTargetNetworkActorId(
            event,
            event.position_x,
            event.position_y,
            event.direction_x,
            event.direction_y);
    built.skill_id = event.skill_id;
    built.element_id = local.character_profile.element_id;
    built.discipline_id = static_cast<std::int32_t>(local.character_profile.discipline_id);
    built.primary_entry_index = local.character_profile.loadout.primary_entry_index;
    built.primary_combo_entry_index = local.character_profile.loadout.primary_combo_entry_index;
    for (std::size_t index = 0;
         index < local.character_profile.loadout.secondary_entry_indices.size();
         ++index) {
        built.queued_secondary_entry_indices[index] =
            event.cast_kind == CastKind::Secondary &&
                    event.has_live_secondary_loadout
                ? event.live_secondary_entry_indices[index]
                : local.character_profile.loadout.secondary_entry_indices[index];
    }
    built.position_x = event.position_x;
    built.position_y = event.position_y;
    built.heading = cast_heading;
    built.direction_x = event.direction_x;
    built.direction_y = event.direction_y;
    built.aim_target_x =
        event.has_aim_target ? event.aim_target_x : event.position_x + event.direction_x * 512.0f;
    built.aim_target_y =
        event.has_aim_target ? event.aim_target_y : event.position_y + event.direction_y * 512.0f;
    built.cursor_world_x = event.has_cursor_world_placement
                               ? event.cursor_world_x
                               : 0.0f;
    built.cursor_world_y = event.has_cursor_world_placement
                               ? event.cursor_world_y
                               : 0.0f;

    *packet = built;
    return true;
}

bool TryRefreshActiveLocalCastEvent(QueuedLocalCastEvent* event) {
    if (event == nullptr || !g_local_transport.active_local_cast_input.active) {
        return false;
    }

    const auto& active = g_local_transport.active_local_cast_input;
    *event = QueuedLocalCastEvent{};
    event->cast_kind = CastKind::Primary;
    event->secondary_slot = -1;
    event->skill_id = active.skill_id;
    event->target_network_actor_id = active.target_network_actor_id;
    event->target_actor_address = active.target_actor_address;
    event->minimum_hold_until_ms = active.minimum_hold_until_ms;
    event->position_x = active.last_position_x;
    event->position_y = active.last_position_y;
    event->direction_x = active.last_direction_x;
    event->direction_y = active.last_direction_y;
    event->has_aim_target = active.has_aim_target;
    event->aim_target_x = active.last_aim_target_x;
    event->aim_target_y = active.last_aim_target_y;

    SDModPlayerState player_state;
    if (!TryGetPlayerState(&player_state) || !player_state.valid) {
        return true;
    }

    constexpr float kDegreesToRadians = 0.01745329251994329576923690768489f;
    float normalized_heading = player_state.heading;
    while (normalized_heading < 0.0f) {
        normalized_heading += 360.0f;
    }
    while (normalized_heading >= 360.0f) {
        normalized_heading -= 360.0f;
    }
    auto radians = (normalized_heading - 90.0f) * kDegreesToRadians;
    auto direction_x = static_cast<float>(std::cos(radians));
    auto direction_y = static_cast<float>(std::sin(radians));
    if (!std::isfinite(player_state.x) ||
        !std::isfinite(player_state.y) ||
        !std::isfinite(direction_x) ||
        !std::isfinite(direction_y)) {
        return true;
    }

    event->position_x = player_state.x;
    event->position_y = player_state.y;

    float aim_target_x = 0.0f;
    float aim_target_y = 0.0f;
    if (player_state.actor_address != 0 &&
        ProcessMemory::Instance().TryReadField(player_state.actor_address, kActorAimTargetXOffset, &aim_target_x) &&
        ProcessMemory::Instance().TryReadField(player_state.actor_address, kActorAimTargetYOffset, &aim_target_y) &&
        IsUsableLocalCastAimTarget(player_state.x, player_state.y, aim_target_x, aim_target_y)) {
        const auto aim_dx = aim_target_x - player_state.x;
        const auto aim_dy = aim_target_y - player_state.y;
        const auto aim_length = std::sqrt((aim_dx * aim_dx) + (aim_dy * aim_dy));
        if (std::isfinite(aim_length) && aim_length > 0.0001f) {
            direction_x = aim_dx / aim_length;
            direction_y = aim_dy / aim_length;
            event->has_aim_target = true;
            event->aim_target_x = aim_target_x;
            event->aim_target_y = aim_target_y;
        }
    }

    event->direction_x = direction_x;
    event->direction_y = direction_y;

    uintptr_t target_actor_address = 0;
    if (player_state.actor_address != 0 &&
        ProcessMemory::Instance().TryReadField(
            player_state.actor_address,
            kActorCurrentTargetActorOffset,
            &target_actor_address) &&
        target_actor_address != 0) {
        std::uint64_t target_network_actor_id = 0;
        if (TryResolveExplicitCastTargetNetworkActorId(
                target_actor_address,
                event->position_x,
                event->position_y,
                &target_network_actor_id)) {
            event->target_actor_address = target_actor_address;
            event->target_network_actor_id = target_network_actor_id;
        } else {
            event->target_actor_address = 0;
            event->target_network_actor_id = 0;
        }
    }
    return true;
}

void RememberActiveLocalCastInput(
    const QueuedLocalCastEvent& event,
    const CastPacket& packet,
    std::uint64_t now_ms) {
    auto& active = g_local_transport.active_local_cast_input;
    active.active = true;
    active.cast_sequence = packet.cast_sequence;
    active.skill_id = event.skill_id;
    active.run_nonce = packet.run_nonce;
    active.target_network_actor_id = packet.target_network_actor_id;
    active.target_actor_address = event.target_actor_address;
    active.minimum_hold_until_ms = event.minimum_hold_until_ms;
    active.last_position_x = event.position_x;
    active.last_position_y = event.position_y;
    active.last_direction_x = event.direction_x;
    active.last_direction_y = event.direction_y;
    active.has_aim_target = event.has_aim_target;
    active.last_aim_target_x = event.aim_target_x;
    active.last_aim_target_y = event.aim_target_y;
    active.last_sent_ms = now_ms;
}

void RememberRecentLocalCast(
    const CastPacket& packet,
    std::uint64_t now_ms) {
    g_local_transport.recent_local_cast_sequence = packet.cast_sequence;
    g_local_transport.recent_local_cast_skill_id = packet.skill_id;
    g_local_transport.recent_local_cast_ms = now_ms;
    g_local_transport.recent_local_cast_target_network_actor_id =
        packet.target_network_actor_id;
}

void SendCastPacketToEndpoints(
    const CastPacket& packet,
    const std::vector<TransportPeerEndpoint>& endpoints) {
    for (const auto& endpoint : endpoints) {
        if (static_cast<CastInputPhase>(packet.input_phase) ==
            CastInputPhase::Held) {
            SendPacketToEndpoint(
                packet,
                endpoint,
                SteamNetworkSendMode::UnreliableNoDelay);
            continue;
        }
        // Input edges must bypass reliable-channel retransmission ordering, but
        // the reliable copy still owns eventual convergence after packet loss.
        SendPacketToEndpoint(
            packet,
            endpoint,
            SteamNetworkSendMode::UnreliableNoDelay);
        SendPacketToEndpoint(
            packet,
            endpoint,
            SteamNetworkSendMode::ReliableNoNagle);
    }
    Log(
        "Multiplayer local cast sent. participant_id=" +
        std::to_string(packet.participant_id) +
        " cast_sequence=" + std::to_string(packet.cast_sequence) +
        " kind=" +
        std::string(
            static_cast<CastKind>(packet.cast_kind) == CastKind::Secondary
                ? "secondary"
                : "primary") +
        " secondary_slot=" + std::to_string(packet.secondary_slot) +
        " phase=" + CastInputPhaseLabel(packet.input_phase) +
        " skill_id=" + std::to_string(packet.skill_id) +
        " origin=(" + std::to_string(packet.position_x) + "," +
            std::to_string(packet.position_y) + ")" +
        " heading=" + std::to_string(packet.heading) +
        " cursor_world_placement=" +
            std::to_string(
                (packet.input_flags & CastInputFlagCursorWorldPlacement) != 0
                    ? 1
                    : 0) +
        " cursor_world=(" + std::to_string(packet.cursor_world_x) + "," +
            std::to_string(packet.cursor_world_y) + ")" +
        " target_network_actor_id=" + std::to_string(packet.target_network_actor_id));
}

bool SendLocalEnemyDamageClaim(
    const RuntimeState& runtime_state,
    const ParticipantInfo& local,
    std::uint64_t network_actor_id,
    std::int32_t skill_id,
    float authoritative_hp,
    float local_hp,
    float max_hp,
    float target_position_x,
    float target_position_y,
    bool target_position_optional = false,
    bool baseline_prevalidated = false,
    bool force_resend = false);

void ReleaseActiveLocalCastInputForReplacement(
    const RuntimeState& runtime_state,
    const ParticipantInfo& local,
    const std::vector<TransportPeerEndpoint>& endpoints,
    std::uint64_t now_ms,
    std::uint64_t replacement_native_queue_id) {
    if (!g_local_transport.active_local_cast_input.active) {
        return;
    }

    const auto replaced_cast = g_local_transport.active_local_cast_input;
    const auto replaced_cast_sequence = replaced_cast.cast_sequence;
    QueuedLocalCastEvent release_event{};
    const bool refreshed = TryRefreshActiveLocalCastEvent(&release_event);
    if (refreshed) {
        CastPacket release_packet{};
        if (BuildLocalCastPacket(
                runtime_state,
                local,
                release_event,
                replaced_cast_sequence,
                CastInputPhase::Released,
                &release_packet)) {
            SendCastPacketToEndpoints(release_packet, endpoints);
        }
    }

    if (replaced_cast.skill_id == kAirPrimarySkillId) {
        QueueAirChainTerminal(
            replaced_cast.cast_sequence,
            replaced_cast.run_nonce,
            now_ms);
    }
    g_local_transport.active_local_cast_input = ActiveLocalCastInput{};
    Log(
        "Multiplayer local active cast replaced by native cast. released_cast_sequence=" +
        std::to_string(replaced_cast_sequence) +
        " replacement_native_queue_id=" +
        std::to_string(replacement_native_queue_id) +
        " replacement_tick_ms=" +
        std::to_string(now_ms));
}

void SendQueuedCastEvents(std::uint64_t now_ms) {
    auto events = TakeQueuedLocalCastEvents();
    if (events.empty()) {
        return;
    }

    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);
    if (local == nullptr ||
        !local->runtime.valid ||
        !local->runtime.in_run ||
        local->runtime.scene_intent.kind != ParticipantSceneIntentKind::Run) {
        return;
    }

    const auto endpoints = BuildKnownSendEndpoints();
    if (endpoints.empty()) {
        return;
    }

    for (const auto& event : events) {
        if (g_local_transport.active_local_cast_input.active) {
            ReleaseActiveLocalCastInputForReplacement(
                runtime_state,
                *local,
                endpoints,
                now_ms,
                event.native_queue_id);
        }

        const auto cast_sequence = g_local_transport.next_cast_sequence++;
        CastPacket packet{};
        if (!BuildLocalCastPacket(
                runtime_state,
                *local,
                event,
                cast_sequence,
                CastInputPhase::Pressed,
                &packet)) {
            continue;
        }
        RememberRecentLocalCast(packet, now_ms);
        if (event.cast_kind == CastKind::Primary) {
            CaptureHostLocalFireballExplodeBaseline(*local, packet, now_ms);
        }

        SendCastPacketToEndpoints(packet, endpoints);
        if (event.cast_kind == CastKind::Secondary &&
            event.skill_id == 0x33) {
            std::string dampen_error;
            if (!QueueMultiplayerDampenEffect(
                    packet.participant_id,
                    packet.cast_sequence,
                    packet.position_x,
                    packet.position_y,
                    &dampen_error)) {
                Log(
                    "Multiplayer local Dampen behavior queue failed. cast_sequence=" +
                    std::to_string(packet.cast_sequence) +
                    " error=" + dampen_error);
            }
        }
        if (event.native_queue_id != 0) {
            Log(
                "Multiplayer local native cast sent. native_queue_id=" +
                std::to_string(event.native_queue_id) +
                " cast_sequence=" + std::to_string(cast_sequence) +
                " participant_id=" + std::to_string(packet.participant_id));
        }
        if (event.cast_kind == CastKind::Primary) {
            RememberActiveLocalCastInput(event, packet, now_ms);
        }
    }
}

void SendActiveLocalCastInput(std::uint64_t now_ms) {
    if (!g_local_transport.active_local_cast_input.active) {
        return;
    }

    const bool still_held =
        IsGameplayMouseLeftDown() ||
        now_ms < g_local_transport.active_local_cast_input.minimum_hold_until_ms;
    if (still_held &&
        now_ms - g_local_transport.active_local_cast_input.last_sent_ms <
            kLocalCastInputUpdateIntervalMs) {
        return;
    }

    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);
    if (local == nullptr ||
        !local->runtime.valid ||
        !local->runtime.in_run ||
        local->runtime.scene_intent.kind != ParticipantSceneIntentKind::Run) {
        const auto abandoned_cast = g_local_transport.active_local_cast_input;
        if (abandoned_cast.skill_id == kAirPrimarySkillId) {
            QueueAirChainTerminal(
                abandoned_cast.cast_sequence,
                abandoned_cast.run_nonce,
                now_ms);
        }
        g_local_transport.active_local_cast_input = ActiveLocalCastInput{};
        return;
    }

    const auto endpoints = BuildKnownSendEndpoints();
    if (endpoints.empty()) {
        return;
    }

    QueuedLocalCastEvent event{};
    if (!TryRefreshActiveLocalCastEvent(&event)) {
        const auto abandoned_cast = g_local_transport.active_local_cast_input;
        if (abandoned_cast.skill_id == kAirPrimarySkillId) {
            QueueAirChainTerminal(
                abandoned_cast.cast_sequence,
                abandoned_cast.run_nonce,
                now_ms);
        }
        g_local_transport.active_local_cast_input = ActiveLocalCastInput{};
        return;
    }

    CastPacket packet{};
    if (!BuildLocalCastPacket(
            runtime_state,
            *local,
            event,
            g_local_transport.active_local_cast_input.cast_sequence,
            still_held ? CastInputPhase::Held : CastInputPhase::Released,
            &packet)) {
        return;
    }

    RememberRecentLocalCast(packet, now_ms);
    SendCastPacketToEndpoints(packet, endpoints);
    if (still_held) {
        RememberActiveLocalCastInput(event, packet, now_ms);
    } else {
        const auto released_cast = g_local_transport.active_local_cast_input;
        if (released_cast.skill_id == kAirPrimarySkillId) {
            QueueAirChainTerminal(
                released_cast.cast_sequence,
                released_cast.run_nonce,
                now_ms);
        }
        g_local_transport.active_local_cast_input = ActiveLocalCastInput{};
    }
}
