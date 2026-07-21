template <typename Packet>
void RelayParticipantPacketToPeers(
    const Packet& packet,
    const TransportPeerEndpoint& source) {
    if (!g_local_transport.is_host) {
        return;
    }

    std::vector<TransportPeerEndpoint> endpoints;
    for (const auto& peer : g_local_transport.peers) {
        if (SameEndpoint(peer.endpoint, source)) {
            continue;
        }
        const bool already_added = std::any_of(endpoints.begin(), endpoints.end(), [&](const TransportPeerEndpoint& existing) {
            return SameEndpoint(existing, peer.endpoint);
        });
        if (!already_added) {
            endpoints.push_back(peer.endpoint);
        }
    }

    auto relayed_packet = packet;
    relayed_packet.authority_participant_id = g_local_transport.local_peer_id;
    for (const auto& endpoint : endpoints) {
        SendPacketToEndpoint(relayed_packet, endpoint);
    }
}
void RelayPacketBufferToPeers(
    const void* packet,
    std::size_t packet_size,
    const TransportPeerEndpoint& source,
    SteamNetworkSendMode steam_send_mode) {
    if (!g_local_transport.is_host) {
        return;
    }

    std::vector<TransportPeerEndpoint> endpoints;
    for (const auto& peer : g_local_transport.peers) {
        if (SameEndpoint(peer.endpoint, source)) {
            continue;
        }
        const bool already_added = std::any_of(endpoints.begin(), endpoints.end(), [&](const TransportPeerEndpoint& existing) {
            return SameEndpoint(existing, peer.endpoint);
        });
        if (!already_added) {
            endpoints.push_back(peer.endpoint);
        }
    }

    for (const auto& endpoint : endpoints) {
        SendBufferToEndpoint(
            packet,
            packet_size,
            endpoint,
            steam_send_mode);
    }
}

template <typename Packet>
void RelayPacketToPeers(
    const Packet& packet,
    const TransportPeerEndpoint& source) {
    RelayPacketBufferToPeers(
        &packet,
        sizeof(packet),
        source,
        SteamSendModeForPacket(packet));
}

bool IsConfiguredRemoteAuthorityEndpoint(const TransportPeerEndpoint& from) {
    return g_local_transport.configured_remote_valid &&
           SameEndpoint(from, g_local_transport.configured_remote);
}

template <typename Packet>
bool IsAuthoritativeHostParticipantPacket(
    const Packet& packet,
    const TransportPeerEndpoint& from) {
    return IsLocalTransportClient() &&
           IsConfiguredRemoteAuthorityEndpoint(from) &&
           packet.authority_participant_id != 0 &&
           packet.participant_id == packet.authority_participant_id;
}

bool IsLocalSceneAlreadyRun(const SDModSceneState& scene_state) {
    return scene_state.kind == "arena" || scene_state.name == "testrun";
}

bool IsLocalSceneSharedHub(const SDModSceneState& scene_state) {
    return scene_state.kind == "hub" || scene_state.name == "hub";
}

bool DoesLocalSceneMatchParticipantIntent(const ParticipantSceneIntent& scene_intent) {
    SDModSceneState scene_state;
    if (!TryGetSceneState(&scene_state) || !scene_state.valid) {
        return false;
    }

    switch (scene_intent.kind) {
    case ParticipantSceneIntentKind::Run:
        return IsLocalSceneAlreadyRun(scene_state);
    case ParticipantSceneIntentKind::SharedHub:
        return IsLocalSceneSharedHub(scene_state);
    case ParticipantSceneIntentKind::PrivateRegion: {
        if (scene_state.kind == "transition" || scene_state.name == "transition") {
            return false;
        }
        const bool region_matches =
            scene_intent.region_index >= 0 &&
            scene_state.current_region_index >= 0 &&
            scene_intent.region_index == scene_state.current_region_index;
        const bool type_matches =
            scene_intent.region_type_id >= 0 &&
            scene_state.region_type_id >= 0 &&
            scene_intent.region_type_id == scene_state.region_type_id;
        return region_matches || type_matches;
    }
    }

    return false;
}

template <typename Packet>
void MaybeQueueClientHostRunStart(
    const Packet& packet,
    const ParticipantSceneIntent& scene_intent,
    const TransportPeerEndpoint& from,
    std::uint64_t now_ms) {
    if (!IsLocalTransportClient() ||
        !IsAuthoritativeHostParticipantPacket(packet, from)) {
        return;
    }

    if (scene_intent.kind != ParticipantSceneIntentKind::Run ||
        packet.ready == 0 ||
        packet.run_nonce == 0) {
        std::lock_guard<std::mutex> lock(g_client_host_run_authorization_mutex);
        if (g_client_host_run_authorization.authority_participant_id == packet.participant_id) {
            g_client_host_run_authorization = ClientHostRunAuthorization{};
        }
        return;
    }

    bool authorization_changed = false;
    {
        std::lock_guard<std::mutex> lock(g_client_host_run_authorization_mutex);
        authorization_changed =
            !g_client_host_run_authorization.valid ||
            g_client_host_run_authorization.authority_participant_id != packet.participant_id ||
            g_client_host_run_authorization.run_nonce != packet.run_nonce;
        g_client_host_run_authorization.valid = true;
        g_client_host_run_authorization.authority_participant_id = packet.participant_id;
        g_client_host_run_authorization.run_nonce = packet.run_nonce;
        g_client_host_run_authorization.received_ms = now_ms;
    }
    if (authorization_changed) {
        Log(
            "Multiplayer cached authenticated host run intent. authority_participant_id=" +
            std::to_string(packet.participant_id) +
            " run_generation_seed=" + HexString(static_cast<uintptr_t>(packet.run_nonce)) +
            " sequence=" + std::to_string(packet.header.sequence));
    }

    SDModSceneState scene_state;
    if (!TryGetSceneState(&scene_state) || !scene_state.valid ||
        IsLocalSceneAlreadyRun(scene_state)) {
        return;
    }
    if (!IsLocalSceneSharedHub(scene_state)) {
        // A client resuming a save enters the stock transition scene before
        // Gameplay::switch_region(arena) runs. The game-thread hook consumes
        // the cached authorization above; repeatedly queueing a hub action or
        // logging here would race that transition and flood once per packet.
        return;
    }

    const auto last_request_ms = g_local_transport.last_client_host_run_request_ms;
    if (last_request_ms != 0 && now_ms < last_request_ms + kClientHostRunFollowRetryMs) {
        return;
    }

    std::string error_message;
    if (packet.run_nonce != 0 && !SetPendingRunGenerationSeed(packet.run_nonce, &error_message)) {
        Log(
            "Multiplayer transport failed to accept host run generation seed. authority_participant_id=" +
            std::to_string(packet.participant_id) +
            " seed=" + HexString(static_cast<uintptr_t>(packet.run_nonce)) +
            " error=" + error_message);
        return;
    }

    g_local_transport.last_client_host_run_request_ms = now_ms;
    if (!QueueHubStartTestrun(&error_message)) {
        Log(
            "Multiplayer transport failed to follow host run intent. authority_participant_id=" +
            std::to_string(packet.participant_id) +
            " error=" + error_message);
        return;
    }

    Log(
        "Multiplayer transport queued host-authoritative run entry. authority_participant_id=" +
        std::to_string(packet.participant_id) +
        " run_generation_seed=" + HexString(static_cast<uintptr_t>(packet.run_nonce)) +
        " sequence=" + std::to_string(packet.header.sequence));
}

struct NormalizedParticipantFrameState {
    bool transform_valid = false;
    float movement_intent_x = 0.0f;
    float movement_intent_y = 0.0f;
    float magic_shield_absorb_remaining = 0.0f;
    float magic_shield_absorb_capacity = 0.0f;
    float magic_shield_explosion_fraction = 0.0f;
    float magic_shield_hit_flash = 0.0f;
    float life_current = 0.0f;
    float life_max = 0.0f;
    std::uint8_t transient_status_flags = 0;
    std::int32_t poison_remaining_ticks = 0;
    std::int32_t damage_x4_remaining_ticks = 0;
};

template <typename Packet>
NormalizedParticipantFrameState NormalizeParticipantFramePacket(
    const Packet& packet) {
    NormalizedParticipantFrameState normalized;
    normalized.transform_valid = packet.transform_valid != 0 &&
        std::isfinite(packet.position_x) &&
        std::isfinite(packet.position_y) &&
        std::isfinite(packet.heading);
    if (std::isfinite(packet.movement_intent_x) &&
        std::isfinite(packet.movement_intent_y)) {
        const auto movement_magnitude_squared =
            packet.movement_intent_x * packet.movement_intent_x +
            packet.movement_intent_y * packet.movement_intent_y;
        if (std::isfinite(movement_magnitude_squared) &&
            movement_magnitude_squared > 0.000001f) {
            const auto movement_scale = movement_magnitude_squared > 1.0f
                ? 1.0f / std::sqrt(movement_magnitude_squared)
                : 1.0f;
            normalized.movement_intent_x =
                packet.movement_intent_x * movement_scale;
            normalized.movement_intent_y =
                packet.movement_intent_y * movement_scale;
        }
    }
    const auto shield_state = NormalizeMagicShieldState(
        packet.magic_shield_absorb_remaining,
        packet.magic_shield_absorb_capacity,
        packet.magic_shield_explosion_fraction,
        packet.magic_shield_hit_flash);
    normalized.magic_shield_absorb_remaining =
        shield_state.absorb_remaining;
    normalized.magic_shield_absorb_capacity =
        shield_state.absorb_capacity;
    normalized.magic_shield_explosion_fraction =
        shield_state.explosion_fraction;
    normalized.magic_shield_hit_flash = shield_state.hit_flash;
    normalized.transient_status_flags = static_cast<std::uint8_t>(
        packet.transient_status_flags &
        (kParticipantTransientStatusValueMask |
         ParticipantTransientStatusFlagSnapshotValid));
    const bool poison_snapshot_active =
        (normalized.transient_status_flags &
         (ParticipantTransientStatusFlagSnapshotValid |
          ParticipantTransientStatusFlagPoisoned)) ==
        (ParticipantTransientStatusFlagSnapshotValid |
         ParticipantTransientStatusFlagPoisoned);
    normalized.poison_remaining_ticks = poison_snapshot_active
        ? (std::clamp)(
              packet.poison_remaining_ticks,
              std::int32_t{1},
              kParticipantPoisonMaxDurationTicks)
        : 0;
    const bool damage_x4_snapshot_active =
        (normalized.transient_status_flags &
         (ParticipantTransientStatusFlagSnapshotValid |
          ParticipantTransientStatusFlagDamageX4)) ==
        (ParticipantTransientStatusFlagSnapshotValid |
         ParticipantTransientStatusFlagDamageX4);
    normalized.damage_x4_remaining_ticks = damage_x4_snapshot_active
        ? (std::clamp)(
              packet.damage_x4_remaining_ticks,
              std::int32_t{1},
              kParticipantDamageX4MaxDurationTicks)
        : 0;
    normalized.life_current = packet.life_current;
    normalized.life_max = packet.life_max;

    if (!g_local_transport.is_host) {
        return normalized;
    }

    const auto pending_it =
        g_local_transport.pending_participant_vitals_corrections_by_participant.find(
            packet.participant_id);
    if (pending_it ==
        g_local_transport.pending_participant_vitals_corrections_by_participant.end()) {
        return normalized;
    }

    const auto& correction = pending_it->second.packet;
    const bool life_acknowledged =
        packet.participant_vitals_correction_ack_sequence != 0 &&
        (packet.participant_vitals_correction_ack_sequence ==
             correction.correction_sequence ||
         IsPacketSequenceNewer(
             packet.participant_vitals_correction_ack_sequence,
             correction.correction_sequence));
    const bool correction_poisoned =
        (correction.transient_status_flags &
         ParticipantTransientStatusFlagPoisoned) != 0;
    const bool correction_webbed =
        (correction.transient_status_flags &
         ParticipantTransientStatusFlagWebbed) != 0;
    const bool correction_magic_shield =
        (correction.correction_flags &
         ParticipantVitalsCorrectionFlagMagicShieldState) != 0;
    if (life_acknowledged) {
        g_local_transport.pending_participant_vitals_corrections_by_participant.erase(
            pending_it);
        return normalized;
    }
    if (!life_acknowledged && std::isfinite(correction.life_current)) {
        normalized.life_current =
            (std::min)(normalized.life_current, correction.life_current);
    }
    if (!life_acknowledged && std::isfinite(correction.life_max) &&
        correction.life_max > 0.0f) {
        normalized.life_max = correction.life_max;
    }
    if (correction_poisoned) {
        normalized.transient_status_flags |=
            ParticipantTransientStatusFlagSnapshotValid |
            ParticipantTransientStatusFlagPoisoned;
        normalized.poison_remaining_ticks =
            (std::max)(
                normalized.poison_remaining_ticks,
                correction.poison_remaining_ticks);
    }
    if (correction_webbed) {
        normalized.transient_status_flags |=
            ParticipantTransientStatusFlagSnapshotValid |
            ParticipantTransientStatusFlagWebbed;
    }
    if (correction_magic_shield) {
        normalized.magic_shield_absorb_remaining =
            correction.magic_shield_absorb_remaining;
        normalized.magic_shield_absorb_capacity =
            correction.magic_shield_absorb_capacity;
        normalized.magic_shield_explosion_fraction =
            correction.magic_shield_explosion_fraction;
        normalized.magic_shield_hit_flash =
            correction.magic_shield_hit_flash;
    }
    return normalized;
}

template <typename Packet>
void ApplyParticipantFrameToRuntime(
    const Packet& packet,
    const ParticipantSceneIntent& scene_intent,
    const NormalizedParticipantFrameState& normalized,
    std::uint64_t now_ms,
    ParticipantInfo* participant) {
    if (participant == nullptr) {
        return;
    }

    participant->ready = packet.ready != 0;
    participant->transport_connected = true;
    if (g_local_transport.backend == GameplayTransportBackend::LocalUdp) {
        participant->transport_using_relay = false;
    }
    participant->last_packet_ms = now_ms;
    participant->runtime.valid = true;
    participant->runtime.in_run = packet.in_run != 0;
    participant->runtime.run_nonce = packet.run_nonce;
    participant->runtime.scene_intent = scene_intent;
    participant->runtime.level = packet.level;
    participant->runtime.wave = packet.wave;
    if (participant->runtime.life_max > 0.0f &&
        participant->runtime.life_current > 0.0f &&
        packet.life_max > 0.0f &&
        normalized.life_current <= 0.0f) {
        Log(
            "Multiplayer remote participant vitals crossed to zero. participant_id=" +
            std::to_string(packet.participant_id) +
            " hp=" + std::to_string(normalized.life_current) +
            "/" + std::to_string(normalized.life_max) +
            " previous_hp=" +
            std::to_string(participant->runtime.life_current) +
            "/" + std::to_string(participant->runtime.life_max) +
            " level=" + std::to_string(packet.level) +
            " xp=" + std::to_string(packet.experience_current) +
            " packet_sequence=" +
            std::to_string(packet.header.sequence));
    }
    participant->runtime.life_current = normalized.life_current;
    participant->runtime.life_max = normalized.life_max;
    participant->runtime.mana_current = packet.mana_current;
    participant->runtime.mana_max = packet.mana_max;
    participant->runtime.move_speed = packet.move_speed;
    participant->runtime.persistent_status_flags =
        packet.persistent_status_flags;
    participant->runtime.transient_status_flags =
        normalized.transient_status_flags;
    participant->runtime.poison_remaining_ticks =
        normalized.poison_remaining_ticks;
    participant->runtime.damage_x4_remaining_ticks =
        normalized.damage_x4_remaining_ticks;
    participant->runtime.movement_intent_x = normalized.movement_intent_x;
    participant->runtime.movement_intent_y = normalized.movement_intent_y;
    participant->runtime.experience_current = packet.experience_current;
    participant->runtime.experience_next = packet.experience_next;
    participant->runtime.anim_drive_state = packet.anim_drive_state;
    participant->runtime.presentation_flags =
        packet.presentation_flags &
        ~ParticipantPresentationFlagStaffVisualState;
    participant->runtime.attachment_staff_visual_state = 0;
    participant->runtime.render_variant_primary =
        packet.render_variant_primary;
    participant->runtime.render_variant_secondary =
        packet.render_variant_secondary;
    participant->runtime.render_weapon_type = packet.render_weapon_type;
    participant->runtime.render_selection_byte = packet.render_selection_byte;
    participant->runtime.render_variant_tertiary =
        packet.render_variant_tertiary;
    participant->runtime.primary_visual_link_type_id =
        packet.primary_visual_link_type_id;
    participant->runtime.secondary_visual_link_type_id =
        packet.secondary_visual_link_type_id;
    participant->runtime.primary_visual_link_recipe_uid =
        packet.primary_visual_link_recipe_uid;
    participant->runtime.secondary_visual_link_recipe_uid =
        packet.secondary_visual_link_recipe_uid;
    participant->runtime.attachment_visual_link_type_id =
        packet.attachment_visual_link_type_id;
    participant->runtime.attachment_visual_link_recipe_uid =
        packet.attachment_visual_link_recipe_uid;
    std::memcpy(
        participant->runtime.primary_visual_link_color_block.data(),
        packet.primary_visual_link_color_block,
        participant->runtime.primary_visual_link_color_block.size());
    std::memcpy(
        participant->runtime.secondary_visual_link_color_block.data(),
        packet.secondary_visual_link_color_block,
        participant->runtime.secondary_visual_link_color_block.size());
    participant->runtime.anim_drive_state_word =
        packet.anim_drive_state_word;
    participant->runtime.walk_cycle_primary = packet.walk_cycle_primary;
    participant->runtime.walk_cycle_secondary = packet.walk_cycle_secondary;
    participant->runtime.render_drive_stride = packet.render_drive_stride;
    participant->runtime.render_advance_rate = packet.render_advance_rate;
    participant->runtime.render_advance_phase = packet.render_advance_phase;
    participant->runtime.magic_shield_absorb_remaining =
        normalized.magic_shield_absorb_remaining;
    participant->runtime.magic_shield_absorb_capacity =
        normalized.magic_shield_absorb_capacity;
    participant->runtime.magic_shield_explosion_fraction =
        normalized.magic_shield_explosion_fraction;
    participant->runtime.magic_shield_hit_flash =
        normalized.magic_shield_hit_flash;
    participant->runtime.render_drive_overlay_alpha =
        packet.render_drive_overlay_alpha;
    participant->runtime.render_drive_move_blend =
        packet.render_drive_move_blend;

    if (!normalized.transform_valid) {
        if (packet.in_run == 0) {
            participant->runtime.transform_valid = false;
        }
        return;
    }

    participant->runtime.transform_valid = true;
    participant->runtime.position_x = packet.position_x;
    participant->runtime.position_y = packet.position_y;
    participant->runtime.heading = packet.heading;

    ParticipantTransformSample sample;
    sample.valid = true;
    sample.received_ms = now_ms;
    sample.sequence = packet.header.sequence;
    sample.run_nonce = packet.run_nonce;
    sample.scene_intent = scene_intent;
    sample.position_x = packet.position_x;
    sample.position_y = packet.position_y;
    sample.heading = packet.heading;
    sample.anim_drive_state = packet.anim_drive_state;
    sample.presentation_flags =
        packet.presentation_flags &
        ~ParticipantPresentationFlagStaffVisualState;
    sample.attachment_staff_visual_state = 0;
    sample.render_variant_primary = packet.render_variant_primary;
    sample.render_variant_secondary = packet.render_variant_secondary;
    sample.render_weapon_type = packet.render_weapon_type;
    sample.render_selection_byte = packet.render_selection_byte;
    sample.render_variant_tertiary = packet.render_variant_tertiary;
    sample.primary_visual_link_type_id = packet.primary_visual_link_type_id;
    sample.secondary_visual_link_type_id =
        packet.secondary_visual_link_type_id;
    sample.primary_visual_link_recipe_uid =
        packet.primary_visual_link_recipe_uid;
    sample.secondary_visual_link_recipe_uid =
        packet.secondary_visual_link_recipe_uid;
    sample.attachment_visual_link_type_id =
        packet.attachment_visual_link_type_id;
    sample.attachment_visual_link_recipe_uid =
        packet.attachment_visual_link_recipe_uid;
    std::memcpy(
        sample.primary_visual_link_color_block.data(),
        packet.primary_visual_link_color_block,
        sample.primary_visual_link_color_block.size());
    std::memcpy(
        sample.secondary_visual_link_color_block.data(),
        packet.secondary_visual_link_color_block,
        sample.secondary_visual_link_color_block.size());
    sample.anim_drive_state_word = packet.anim_drive_state_word;
    sample.walk_cycle_primary = packet.walk_cycle_primary;
    sample.walk_cycle_secondary = packet.walk_cycle_secondary;
    sample.render_drive_stride = packet.render_drive_stride;
    sample.render_advance_rate = packet.render_advance_rate;
    sample.render_advance_phase = packet.render_advance_phase;
    sample.magic_shield_absorb_remaining = normalized.magic_shield_absorb_remaining;
    sample.magic_shield_absorb_capacity = normalized.magic_shield_absorb_capacity;
    sample.magic_shield_explosion_fraction =
        normalized.magic_shield_explosion_fraction;
    sample.magic_shield_hit_flash =
        normalized.magic_shield_hit_flash;
    sample.render_drive_overlay_alpha = packet.render_drive_overlay_alpha;
    sample.render_drive_move_blend = packet.render_drive_move_blend;
    AppendParticipantTransformSample(participant, sample);
}

#include "incoming_participant_state_sync.inl"
