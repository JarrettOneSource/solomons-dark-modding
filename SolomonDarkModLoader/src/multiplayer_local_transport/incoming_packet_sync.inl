void RelayStatePacketToPeers(
    const StatePacket& packet,
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
template <typename Packet>
void RelayPacketToPeers(const Packet& packet, const TransportPeerEndpoint& source) {
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
        SendPacketToEndpoint(packet, endpoint);
    }
}

bool IsConfiguredRemoteAuthorityEndpoint(const TransportPeerEndpoint& from) {
    return g_local_transport.configured_remote_valid &&
           SameEndpoint(from, g_local_transport.configured_remote);
}

bool IsAuthoritativeHostStatePacket(
    const StatePacket& packet,
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

void MaybeQueueClientHostRunStart(
    const StatePacket& packet,
    const ParticipantSceneIntent& scene_intent,
    const TransportPeerEndpoint& from,
    std::uint64_t now_ms) {
    if (!IsLocalTransportClient() ||
        !IsAuthoritativeHostStatePacket(packet, from)) {
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

void ApplyRemoteStatePacket(
    const StatePacket& packet,
    const TransportPeerEndpoint& from,
    std::uint64_t now_ms) {
    if (packet.participant_id == 0 ||
        packet.participant_id == kLocalParticipantId ||
        packet.participant_id == g_local_transport.local_peer_id) {
        return;
    }

    UpsertPeerEndpoint(from, packet.participant_id, now_ms);
    RelayStatePacketToPeers(packet, from);

    MultiplayerCharacterProfile profile;
    profile.element_id = packet.element_id;
    profile.discipline_id = static_cast<CharacterDisciplineId>(packet.discipline_id);
    for (std::size_t index = 0; index < profile.appearance.choice_ids.size(); ++index) {
        profile.appearance.choice_ids[index] = packet.appearance_choice_ids[index];
    }
    profile.loadout.primary_entry_index = packet.primary_entry_index;
    profile.loadout.primary_combo_entry_index = packet.primary_combo_entry_index;
    for (std::size_t index = 0; index < profile.loadout.secondary_entry_indices.size(); ++index) {
        profile.loadout.secondary_entry_indices[index] = packet.queued_secondary_entry_indices[index];
    }
    profile.level = packet.level;
    profile.experience = packet.experience_current;
    if (!IsValidCharacterProfile(profile)) {
        return;
    }

    const auto scene_intent = SceneIntentFromPacket(packet);
    const auto display_name = PacketDisplayName(packet);
    const bool transform_valid = packet.transform_valid != 0 &&
        std::isfinite(packet.position_x) &&
        std::isfinite(packet.position_y) &&
        std::isfinite(packet.heading);
    const auto effect_state = NormalizeRenderDriveEffectState(
        packet.render_drive_effect_timer,
        packet.render_drive_effect_progress);
    const auto transient_status_flags = static_cast<std::uint8_t>(
        packet.transient_status_flags &
        (kParticipantTransientStatusValueMask |
         ParticipantTransientStatusFlagSnapshotValid));
    const bool poison_snapshot_active =
        (transient_status_flags &
         (ParticipantTransientStatusFlagSnapshotValid |
          ParticipantTransientStatusFlagPoisoned)) ==
        (ParticipantTransientStatusFlagSnapshotValid |
         ParticipantTransientStatusFlagPoisoned);
    const auto poison_remaining_ticks = poison_snapshot_active
        ? (std::clamp)(
              packet.poison_remaining_ticks,
              std::int32_t{1},
              kParticipantPoisonMaxDurationTicks)
        : 0;
    float effective_life_current = packet.life_current;
    float effective_life_max = packet.life_max;
    std::uint8_t effective_transient_status_flags = transient_status_flags;
    std::int32_t effective_poison_remaining_ticks = poison_remaining_ticks;
    if (g_local_transport.is_host) {
        const auto pending_it =
            g_local_transport.pending_participant_vitals_corrections_by_participant.find(
                packet.participant_id);
        if (pending_it !=
            g_local_transport.pending_participant_vitals_corrections_by_participant.end()) {
            const auto& correction = pending_it->second.packet;
            const bool life_acknowledged =
                packet.participant_vitals_correction_ack_sequence != 0 &&
                static_cast<std::int32_t>(
                    packet.participant_vitals_correction_ack_sequence -
                    correction.correction_sequence) >= 0;
            const bool correction_poisoned =
                (correction.transient_status_flags &
                 ParticipantTransientStatusFlagPoisoned) != 0;
            const bool poison_acknowledged =
                !correction_poisoned ||
                ((transient_status_flags &
                  ParticipantTransientStatusFlagPoisoned) != 0 &&
                 poison_remaining_ticks > 0);
            if (life_acknowledged && poison_acknowledged) {
                g_local_transport.pending_participant_vitals_corrections_by_participant.erase(
                    pending_it);
            } else {
                if (!life_acknowledged &&
                    std::isfinite(correction.life_current)) {
                    effective_life_current =
                        (std::min)(effective_life_current, correction.life_current);
                }
                if (!life_acknowledged &&
                    std::isfinite(correction.life_max) &&
                    correction.life_max > 0.0f) {
                    effective_life_max = correction.life_max;
                }
                if (!poison_acknowledged && correction_poisoned) {
                    effective_transient_status_flags =
                        ParticipantTransientStatusFlagSnapshotValid |
                        ParticipantTransientStatusFlagPoisoned;
                    effective_poison_remaining_ticks =
                        (std::max)(
                            effective_poison_remaining_ticks,
                            correction.poison_remaining_ticks);
                }
            }
        }
    }
    const bool packet_from_configured_authority =
        IsAuthoritativeHostStatePacket(packet, from);

    UpdateRuntimeState([&](RuntimeState& state) {
        if (packet_from_configured_authority) {
            LevelUpWaitStatusRuntimeInfo wait_status;
            wait_status.valid = true;
            wait_status.pause_active = packet.level_up_pause_active != 0;
            wait_status.authority_participant_id = packet.authority_participant_id;
            wait_status.received_ms = now_ms;
            const auto waiting_count =
                (std::min<std::size_t>)(
                    packet.level_up_waiting_count,
                    kLevelUpWaitStatusMaxParticipants);
            wait_status.waiting_participant_ids.reserve(waiting_count);
            for (std::size_t index = 0; index < waiting_count; ++index) {
                const auto participant_id = packet.level_up_waiting_participant_ids[index];
                if (participant_id != 0) {
                    wait_status.waiting_participant_ids.push_back(participant_id);
                }
            }
            state.level_up_wait_status = std::move(wait_status);
        }

        auto* participant = UpsertRemoteParticipant(
            state,
            packet.participant_id,
            ParticipantControllerKind::Native);
        if (participant == nullptr) {
            return;
        }

        if (!display_name.empty()) {
            participant->name = display_name;
        } else if (participant->name.empty() || participant->name == "Remote Wizard") {
            participant->name = "Remote Wizard " + std::to_string(packet.participant_id);
        }
        participant->ready = packet.ready != 0;
        participant->transport_connected = true;
        if (g_local_transport.backend == GameplayTransportBackend::LocalUdp) {
            participant->transport_using_relay = false;
        }
        participant->last_packet_ms = now_ms;
        participant->character_profile = profile;
        participant->runtime.valid = true;
        participant->runtime.in_run = packet.in_run != 0;
        participant->runtime.run_nonce = packet.run_nonce;
        participant->runtime.scene_intent = scene_intent;
        participant->runtime.level = packet.level;
        participant->runtime.wave = packet.wave;
        if (participant->runtime.life_max > 0.0f &&
            participant->runtime.life_current > 0.0f &&
            packet.life_max > 0.0f &&
            effective_life_current <= 0.0f) {
            Log(
                "Multiplayer remote participant vitals crossed to zero from state packet. participant_id=" +
                std::to_string(packet.participant_id) +
                " hp=" + std::to_string(effective_life_current) +
                "/" + std::to_string(effective_life_max) +
                " previous_hp=" + std::to_string(participant->runtime.life_current) +
                "/" + std::to_string(participant->runtime.life_max) +
                " level=" + std::to_string(packet.level) +
                " xp=" + std::to_string(packet.experience_current) +
                " packet_sequence=" + std::to_string(packet.header.sequence));
        }
        participant->runtime.life_current = effective_life_current;
        participant->runtime.life_max = effective_life_max;
        participant->runtime.mana_current = packet.mana_current;
        participant->runtime.mana_max = packet.mana_max;
        participant->runtime.move_speed = packet.move_speed;
        participant->runtime.persistent_status_flags =
            packet.persistent_status_flags;
        participant->runtime.transient_status_flags =
            effective_transient_status_flags;
        participant->runtime.poison_remaining_ticks =
            effective_poison_remaining_ticks;
        participant->runtime.experience_current = packet.experience_current;
        participant->runtime.experience_next = packet.experience_next;
        const bool should_apply_gold =
            !participant->owned_progression.initialized ||
            packet.gold_revision >= participant->owned_progression.gold_revision;
        participant->owned_progression.initialized = true;
        if (should_apply_gold) {
            participant->owned_progression.gold = packet.owned_gold;
            participant->owned_progression.gold_revision = packet.gold_revision;
        }
        const bool should_apply_inventory =
            packet.inventory_revision >= participant->owned_progression.inventory_revision;
        if (should_apply_inventory) {
            participant->owned_progression.inventory_revision = packet.inventory_revision;
            participant->owned_progression.inventory_item_total_count = packet.inventory_item_total_count;
            participant->owned_progression.inventory_truncated =
                (packet.inventory_snapshot_flags & ParticipantInventorySnapshotFlagTruncated) != 0;
            participant->owned_progression.inventory_items.clear();
            const auto packet_inventory_count =
                (std::min)(
                    static_cast<std::size_t>(packet.inventory_item_count),
                    static_cast<std::size_t>(kParticipantInventorySnapshotMaxItems));
            participant->owned_progression.inventory_items.reserve(packet_inventory_count);
            for (std::size_t index = 0; index < packet_inventory_count; ++index) {
                const auto& packet_item = packet.inventory_items[index];
                if (packet_item.type_id == 0) {
                    continue;
                }
                ParticipantInventoryItemState item;
                item.type_id = packet_item.type_id;
                item.slot = packet_item.slot;
                item.stack_count = packet_item.stack_count;
                participant->owned_progression.inventory_items.push_back(item);
            }
        }
        const bool should_apply_progression_book =
            packet.statbook_revision >= participant->owned_progression.statbook_revision ||
            packet.spellbook_revision >= participant->owned_progression.spellbook_revision;
        if (should_apply_progression_book) {
            participant->owned_progression.spellbook_revision = packet.spellbook_revision;
            participant->owned_progression.statbook_revision = packet.statbook_revision;
            participant->owned_progression.progression_book_entry_total_count =
                packet.progression_book_entry_total_count;
            participant->owned_progression.progression_book_truncated =
                (packet.progression_book_snapshot_flags & ParticipantProgressionBookSnapshotFlagTruncated) != 0;
            participant->owned_progression.progression_book_entries.clear();
            const auto packet_progression_book_count =
                (std::min)(
                    static_cast<std::size_t>(packet.progression_book_entry_count),
                    static_cast<std::size_t>(kParticipantProgressionBookSnapshotMaxEntries));
            participant->owned_progression.progression_book_entries.reserve(packet_progression_book_count);
            for (std::size_t index = 0; index < packet_progression_book_count; ++index) {
                const auto& packet_entry = packet.progression_book_entries[index];
                if (packet_entry.entry_index < 0) {
                    continue;
                }
                ParticipantProgressionBookEntryState entry;
                entry.entry_index = packet_entry.entry_index;
                entry.internal_id = packet_entry.internal_id;
                entry.active = packet_entry.active;
                entry.visible = packet_entry.visible;
                entry.category = packet_entry.category;
                entry.statbook_max_level = packet_entry.statbook_max_level;
                participant->owned_progression.progression_book_entries.push_back(entry);
            }
        }
        participant->owned_progression.spellbook_revision =
            (std::max)(participant->owned_progression.spellbook_revision, packet.spellbook_revision);
        const bool should_apply_concentration =
            packet.concentration_selection_valid != 0 &&
            (!participant->owned_progression.concentration_selection_valid ||
             packet.concentration_revision >
                 participant->owned_progression.concentration_revision);
        if (should_apply_concentration) {
            participant->owned_progression.concentration_selection_valid = true;
            participant->owned_progression.concentration_revision =
                packet.concentration_revision;
            participant->owned_progression.concentration_entry_a =
                packet.concentration_entry_a;
            participant->owned_progression.concentration_entry_b =
                packet.concentration_entry_b;
        }
        ApplyDerivedStatPacketState(
            packet.derived_stat_revision,
            packet.derived_stats,
            &participant->owned_progression);
        const bool should_apply_loadout =
            packet.loadout_revision >= participant->owned_progression.loadout_revision;
        if (should_apply_loadout) {
            participant->owned_progression.loadout_revision = packet.loadout_revision;
            participant->owned_progression.ability_loadout_valid = true;
            participant->owned_progression.ability_loadout = profile.loadout;
        }
        participant->runtime.primary_entry_index = packet.primary_entry_index;
        participant->runtime.primary_combo_entry_index = packet.primary_combo_entry_index;
        for (std::size_t index = 0; index < participant->runtime.queued_secondary_entry_indices.size(); ++index) {
            participant->runtime.queued_secondary_entry_indices[index] =
                packet.queued_secondary_entry_indices[index];
        }
        participant->runtime.anim_drive_state = packet.anim_drive_state;
        participant->runtime.presentation_flags =
            packet.presentation_flags & ~ParticipantPresentationFlagStaffVisualState;
        participant->runtime.attachment_staff_visual_state = 0;
        participant->runtime.render_variant_primary = packet.render_variant_primary;
        participant->runtime.render_variant_secondary = packet.render_variant_secondary;
        participant->runtime.render_weapon_type = packet.render_weapon_type;
        participant->runtime.render_selection_byte = packet.render_selection_byte;
        participant->runtime.render_variant_tertiary = packet.render_variant_tertiary;
        participant->runtime.primary_visual_link_type_id = packet.primary_visual_link_type_id;
        participant->runtime.secondary_visual_link_type_id = packet.secondary_visual_link_type_id;
        std::memcpy(
            participant->runtime.primary_visual_link_color_block.data(),
            packet.primary_visual_link_color_block,
            participant->runtime.primary_visual_link_color_block.size());
        std::memcpy(
            participant->runtime.secondary_visual_link_color_block.data(),
            packet.secondary_visual_link_color_block,
            participant->runtime.secondary_visual_link_color_block.size());
        participant->runtime.anim_drive_state_word = packet.anim_drive_state_word;
        participant->runtime.walk_cycle_primary = packet.walk_cycle_primary;
        participant->runtime.walk_cycle_secondary = packet.walk_cycle_secondary;
        participant->runtime.render_drive_stride = packet.render_drive_stride;
        participant->runtime.render_advance_rate = packet.render_advance_rate;
        participant->runtime.render_advance_phase = packet.render_advance_phase;
        participant->runtime.render_drive_effect_timer = effect_state.timer;
        participant->runtime.render_drive_effect_progress = effect_state.progress;
        participant->runtime.render_drive_overlay_alpha = packet.render_drive_overlay_alpha;
        participant->runtime.render_drive_move_blend = packet.render_drive_move_blend;
        if (transform_valid) {
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
                packet.presentation_flags & ~ParticipantPresentationFlagStaffVisualState;
            sample.attachment_staff_visual_state = 0;
            sample.render_variant_primary = packet.render_variant_primary;
            sample.render_variant_secondary = packet.render_variant_secondary;
            sample.render_weapon_type = packet.render_weapon_type;
            sample.render_selection_byte = packet.render_selection_byte;
            sample.render_variant_tertiary = packet.render_variant_tertiary;
            sample.primary_visual_link_type_id = packet.primary_visual_link_type_id;
            sample.secondary_visual_link_type_id = packet.secondary_visual_link_type_id;
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
            sample.render_drive_effect_timer = effect_state.timer;
            sample.render_drive_effect_progress = effect_state.progress;
            sample.render_drive_overlay_alpha = packet.render_drive_overlay_alpha;
            sample.render_drive_move_blend = packet.render_drive_move_blend;
            AppendParticipantTransformSample(participant, sample);
        }
    });

    MaybeQueueClientHostRunStart(packet, scene_intent, from, now_ms);

    SDModParticipantGameplayState gameplay_state;
    const bool participant_materialized =
        TryGetParticipantGameplayState(packet.participant_id, &gameplay_state) &&
        gameplay_state.entity_materialized &&
        gameplay_state.actor_address != 0;
    if (transform_valid &&
        !participant_materialized &&
        DoesLocalSceneMatchParticipantIntent(scene_intent)) {
        std::string sync_error;
        (void)QueueParticipantEntitySync(
            packet.participant_id,
            profile,
            scene_intent,
            true,
            true,
            packet.position_x,
            packet.position_y,
            packet.heading,
            &sync_error);
    }
}

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
        static_cast<std::int32_t>(packet.cast_sequence - last_sequence_it->second) < 0) {
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
               static_cast<std::int32_t>(packet.header.sequence - input_tracker.last_packet_sequence) <= 0) {
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

    // Lightning can kill its initial target inside the stock pressed-frame
    // dispatcher before the post-dispatch cast hook publishes the packet. The
    // receiver may therefore see one or more packets whose exact network target
    // is already dead or not materialized yet, followed by a held packet for a
    // live target. Starting remote playback before that target resolves leaves
    // Lightning's native target validation false for the whole action, so an
    // upgraded cast never enters Chaining's extra-target loop on observers.
    // Other elements retain their targetless directional/projectile behavior.
    const bool air_primary_packet =
        packet.element_id == 3 &&
        (packet.primary_entry_index == 0x18 || packet.skill_id == 0x18);
    if (!input_tracker.start_queued && air_primary_packet && !resolved_target_by_id) {
        input_tracker.deferred_start_packet_count += 1;
        if (input_tracker.deferred_start_packet_count <= 3 ||
            input_tracker.deferred_start_packet_count % 10 == 0) {
            Log(
                "Multiplayer remote Air cast start deferred until exact target resolves. participant_id=" +
                std::to_string(packet.participant_id) +
                " cast_sequence=" + std::to_string(packet.cast_sequence) +
                " phase=" + CastInputPhaseLabel(packet.input_phase) +
                " target_network_actor_id=" + std::to_string(packet.target_network_actor_id) +
                " deferred_packets=" + std::to_string(input_tracker.deferred_start_packet_count));
        }
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

WorldSnapshotRuntimeInfo BuildWorldSnapshotRuntimeInfo(
    const WorldSnapshotPacket& packet,
    std::uint64_t now_ms) {
    const auto actor_count = static_cast<std::uint8_t>(
        (std::min<std::uint32_t>)(packet.actor_count, kWorldSnapshotMaxActors));
    const auto scene_kind = static_cast<WorldSceneKind>(packet.scene_kind);
    WorldSnapshotRuntimeInfo snapshot;
    snapshot.valid = true;
    snapshot.authority_participant_id = packet.authority_participant_id;
    snapshot.received_ms = now_ms;
    snapshot.sequence = packet.header.sequence;
    snapshot.scene_epoch = packet.scene_epoch;
    snapshot.run_nonce = packet.run_nonce;
    snapshot.actor_total_count = packet.actor_total_count;
    snapshot.truncated = (packet.snapshot_flags & WorldSnapshotFlagTruncated) != 0;
    snapshot.scene_intent = SceneIntentFromWorldSceneKind(scene_kind);
    snapshot.actors.reserve(actor_count);

    for (std::uint8_t index = 0; index < actor_count; ++index) {
        const auto& packet_actor = packet.actors[index];
        if (packet_actor.network_actor_id == 0 ||
            packet_actor.native_type_id == 0 ||
            !std::isfinite(packet_actor.position_x) ||
            !std::isfinite(packet_actor.position_y) ||
            !std::isfinite(packet_actor.radius) ||
            packet_actor.radius < 0.0f) {
            continue;
        }

        WorldActorSnapshot actor;
        actor.network_actor_id = packet_actor.network_actor_id;
        actor.native_type_id = packet_actor.native_type_id;
        actor.enemy_type = packet_actor.enemy_type;
        actor.actor_slot = packet_actor.actor_slot;
        actor.world_slot = packet_actor.world_slot;
        actor.target_participant_id = packet_actor.target_participant_id;
        actor.target_native_type_id = packet_actor.target_native_type_id;
        actor.target_actor_slot = packet_actor.target_actor_slot;
        actor.target_world_slot = packet_actor.target_world_slot;
        actor.target_bucket_delta = packet_actor.target_bucket_delta;
        actor.dead = (packet_actor.flags & WorldActorSnapshotFlagDead) != 0;
        actor.tracked_enemy = (packet_actor.flags & WorldActorSnapshotFlagTrackedEnemy) != 0;
        actor.lifecycle_owned = (packet_actor.flags & WorldActorSnapshotFlagLifecycleOwned) != 0;
        actor.run_static = (packet_actor.flags & WorldActorSnapshotFlagRunStatic) != 0;
        actor.player_created =
            (packet_actor.flags & WorldActorSnapshotFlagPlayerCreated) != 0;
        actor.target_authoritative =
            (packet_actor.flags & WorldActorSnapshotFlagTargetAuthoritative) != 0;
        actor.anim_drive_state = packet_actor.anim_drive_state;
        actor.presentation_flags = packet_actor.presentation_flags;
        actor.position_x = packet_actor.position_x;
        actor.position_y = packet_actor.position_y;
        actor.radius = packet_actor.radius;
        actor.heading = std::isfinite(packet_actor.heading) ? packet_actor.heading : 0.0f;
        actor.hp = std::isfinite(packet_actor.hp) ? packet_actor.hp : 0.0f;
        actor.max_hp = std::isfinite(packet_actor.max_hp) ? packet_actor.max_hp : 0.0f;
        actor.anim_drive_state_word = packet_actor.anim_drive_state_word;
        actor.walk_cycle_primary =
            std::isfinite(packet_actor.walk_cycle_primary) ? packet_actor.walk_cycle_primary : 0.0f;
        actor.walk_cycle_secondary =
            std::isfinite(packet_actor.walk_cycle_secondary) ? packet_actor.walk_cycle_secondary : 0.0f;
        actor.render_variant_primary = packet_actor.render_variant_primary;
        actor.render_variant_secondary = packet_actor.render_variant_secondary;
        actor.render_weapon_type = packet_actor.render_weapon_type;
        actor.render_selection_byte = packet_actor.render_selection_byte;
        actor.render_variant_tertiary = packet_actor.render_variant_tertiary;
        std::memcpy(
            actor.student_visual_state.data(),
            packet_actor.student_visual_state,
            actor.student_visual_state.size());
        snapshot.actors.push_back(actor);
    }

    return snapshot;
}

void PublishWorldSnapshotRuntimeInfo(const WorldSnapshotPacket& packet, std::uint64_t now_ms) {
    UpdateRuntimeState([&](RuntimeState& state) {
        AppendWorldSnapshot(&state, BuildWorldSnapshotRuntimeInfo(packet, now_ms));
    });
}

void ApplyWorldSnapshotPacket(
    const WorldSnapshotPacket& packet,
    const TransportPeerEndpoint& from,
    std::uint64_t now_ms) {
    if (g_local_transport.is_host ||
        packet.authority_participant_id == 0 ||
        packet.authority_participant_id == g_local_transport.local_peer_id) {
        return;
    }

    UpsertPeerEndpoint(from, packet.authority_participant_id, now_ms);
    PublishWorldSnapshotRuntimeInfo(packet, now_ms);
}

LootSnapshotRuntimeInfo BuildLootSnapshotRuntimeInfo(
    const LootSnapshotPacket& packet,
    std::uint64_t now_ms) {
    const auto drop_count = static_cast<std::uint8_t>(
        (std::min<std::uint32_t>)(packet.drop_count, kLootSnapshotMaxDrops));
    const auto scene_kind = static_cast<WorldSceneKind>(packet.scene_kind);

    LootSnapshotRuntimeInfo snapshot;
    snapshot.valid = true;
    snapshot.authority_participant_id = packet.authority_participant_id;
    snapshot.received_ms = now_ms;
    snapshot.sequence = packet.header.sequence;
    snapshot.scene_epoch = packet.scene_epoch;
    snapshot.run_nonce = packet.run_nonce;
    snapshot.drop_total_count = packet.drop_total_count;
    snapshot.truncated = (packet.snapshot_flags & LootSnapshotFlagTruncated) != 0;
    snapshot.scene_intent = SceneIntentFromWorldSceneKind(scene_kind);
    snapshot.drops.reserve(drop_count);

    for (std::uint8_t index = 0; index < drop_count; ++index) {
        const auto& packet_drop = packet.drops[index];
        const auto drop_kind = LootDropKindFromPacketValue(packet_drop.drop_kind);
        if (packet_drop.network_drop_id == 0 ||
            packet_drop.native_type_id == 0 ||
            !std::isfinite(packet_drop.position_x) ||
            !std::isfinite(packet_drop.position_y) ||
            !std::isfinite(packet_drop.radius) ||
            packet_drop.radius < 0.0f ||
            (drop_kind == LootDropKind::Orb && !std::isfinite(packet_drop.value)) ||
            ((drop_kind == LootDropKind::Item || drop_kind == LootDropKind::Potion) &&
                packet_drop.item_type_id == 0)) {
            continue;
        }

        LootDropSnapshot drop;
        drop.network_drop_id = packet_drop.network_drop_id;
        drop.native_type_id = packet_drop.native_type_id;
        drop.drop_kind = drop_kind;
        drop.active = (packet_drop.flags & LootDropSnapshotFlagActive) != 0;
        drop.presentation_state = packet_drop.presentation_state;
        drop.amount = packet_drop.amount;
        drop.amount_tier = packet_drop.amount_tier;
        drop.value = packet_drop.value;
        drop.motion = packet_drop.motion;
        drop.progress = packet_drop.progress;
        drop.item_type_id = packet_drop.item_type_id;
        drop.item_slot = packet_drop.item_slot;
        drop.stack_count = packet_drop.stack_count;
        drop.actor_slot = packet_drop.actor_slot;
        drop.world_slot = packet_drop.world_slot;
        drop.lifetime = packet_drop.lifetime;
        drop.position_x = packet_drop.position_x;
        drop.position_y = packet_drop.position_y;
        drop.radius = packet_drop.radius;
        snapshot.drops.push_back(drop);
    }

    return snapshot;
}

void PublishLootSnapshotRuntimeInfo(const LootSnapshotPacket& packet, std::uint64_t now_ms) {
    UpdateRuntimeState([&](RuntimeState& state) {
        state.loot_snapshot = BuildLootSnapshotRuntimeInfo(packet, now_ms);
    });
}

void ApplyLootSnapshotPacket(
    const LootSnapshotPacket& packet,
    const TransportPeerEndpoint& from,
    std::uint64_t now_ms) {
    if (g_local_transport.is_host ||
        packet.authority_participant_id == 0 ||
        packet.authority_participant_id == g_local_transport.local_peer_id) {
        return;
    }

    UpsertPeerEndpoint(from, packet.authority_participant_id, now_ms);
    PublishLootSnapshotRuntimeInfo(packet, now_ms);

    std::string queue_error;
    (void)sdmod::QueueReplicatedLootSnapshot(SnapshotRuntimeState().loot_snapshot, &queue_error);
}

#include "multiplayer_local_transport/enemy_damage_authority.inl"

#include "multiplayer_local_transport/loot_pickup_authority.inl"

#include "multiplayer_local_transport/level_up_packet_sync.inl"

#include "multiplayer_local_transport/spell_effect_sync.inl"
#include "multiplayer_local_transport/air_chain_sync.inl"
#include "multiplayer_local_transport/participant_vitals_authority.inl"

using TransportPacketBuffer = std::array<char, sizeof(WorldSnapshotPacket)>;

template <typename Packet, typename OwnerAccessor>
bool SteamPacketOwnerMatches(
    const void* data,
    std::size_t size,
    std::uint64_t sender_steam_id,
    OwnerAccessor owner_accessor) {
    if (size != sizeof(Packet)) {
        return false;
    }
    Packet packet{};
    std::memcpy(&packet, data, sizeof(packet));
    return owner_accessor(packet) == sender_steam_id;
}

bool IsAuthorizedSteamGameplayPacket(
    std::uint64_t sender_steam_id,
    const void* data,
    std::size_t size) {
    if (data == nullptr || size < sizeof(PacketHeader)) {
        return false;
    }

    if (!g_local_transport.is_host) {
        return g_local_transport.configured_remote_valid &&
               g_local_transport.configured_remote.backend ==
                   GameplayTransportBackend::Steam &&
               g_local_transport.configured_remote.steam_id == sender_steam_id;
    }

    PacketHeader header{};
    std::memcpy(&header, data, sizeof(header));
    switch (static_cast<PacketKind>(header.kind)) {
    case PacketKind::State:
        return SteamPacketOwnerMatches<StatePacket>(
            data,
            size,
            sender_steam_id,
            [](const StatePacket& packet) {
                return packet.authority_participant_id == 0
                    ? packet.participant_id
                    : std::uint64_t{0};
            });
    case PacketKind::Cast:
        return SteamPacketOwnerMatches<CastPacket>(
            data,
            size,
            sender_steam_id,
            [](const CastPacket& packet) { return packet.participant_id; });
    case PacketKind::SpellEffectSnapshot:
        return SteamPacketOwnerMatches<SpellEffectSnapshotPacket>(
            data,
            size,
            sender_steam_id,
            [](const SpellEffectSnapshotPacket& packet) {
                return packet.owner_participant_id;
            });
    case PacketKind::AirChainSnapshot:
        return SteamPacketOwnerMatches<AirChainSnapshotPacket>(
            data,
            size,
            sender_steam_id,
            [](const AirChainSnapshotPacket& packet) {
                return packet.owner_participant_id;
            });
    case PacketKind::EnemyDamageClaim:
        return SteamPacketOwnerMatches<EnemyDamageClaimPacket>(
            data,
            size,
            sender_steam_id,
            [](const EnemyDamageClaimPacket& packet) {
                return packet.participant_id;
            });
    case PacketKind::LootPickupRequest:
        return SteamPacketOwnerMatches<LootPickupRequestPacket>(
            data,
            size,
            sender_steam_id,
            [](const LootPickupRequestPacket& packet) {
                return packet.participant_id;
            });
    case PacketKind::LevelUpChoice:
        return SteamPacketOwnerMatches<LevelUpChoicePacket>(
            data,
            size,
            sender_steam_id,
            [](const LevelUpChoicePacket& packet) {
                return packet.participant_id;
            });
    default:
        return false;
    }
}

void DispatchReceivedPacket(
    const TransportPacketBuffer& packet_buffer,
    int received,
    const TransportPeerEndpoint& from,
    std::uint64_t now_ms) {
    do {
        if (received < static_cast<int>(sizeof(PacketHeader))) {
            continue;
        }

        PacketHeader header{};
        std::memcpy(&header, packet_buffer.data(), sizeof(header));
        if (!IsValidPacketHeader(header)) {
            continue;
        }

        const auto kind = static_cast<PacketKind>(header.kind);
        if (kind == PacketKind::State && received == static_cast<int>(sizeof(StatePacket))) {
            StatePacket packet{};
            std::memcpy(&packet, packet_buffer.data(), sizeof(packet));
            if (!IsValidHeader(packet.header, PacketKind::State)) {
                continue;
            }
            g_local_transport.packets_received += 1;
            ApplyRemoteStatePacket(packet, from, now_ms);
            continue;
        }

        if (kind == PacketKind::Cast && received == static_cast<int>(sizeof(CastPacket))) {
            CastPacket packet{};
            std::memcpy(&packet, packet_buffer.data(), sizeof(packet));
            if (!IsValidHeader(packet.header, PacketKind::Cast)) {
                continue;
            }
            g_local_transport.packets_received += 1;
            ApplyRemoteCastPacket(packet, from, now_ms);
            continue;
        }

        if (kind == PacketKind::SpellEffectSnapshot &&
            received == static_cast<int>(sizeof(SpellEffectSnapshotPacket))) {
            SpellEffectSnapshotPacket packet{};
            std::memcpy(&packet, packet_buffer.data(), sizeof(packet));
            if (!IsValidHeader(packet.header, PacketKind::SpellEffectSnapshot)) {
                continue;
            }
            g_local_transport.packets_received += 1;
            ApplySpellEffectSnapshotPacket(packet, from, now_ms);
            continue;
        }

        if (kind == PacketKind::AirChainSnapshot &&
            received == static_cast<int>(sizeof(AirChainSnapshotPacket))) {
            AirChainSnapshotPacket packet{};
            std::memcpy(&packet, packet_buffer.data(), sizeof(packet));
            if (!IsValidHeader(packet.header, PacketKind::AirChainSnapshot)) {
                continue;
            }
            g_local_transport.packets_received += 1;
            ApplyAirChainSnapshotPacket(packet, from, now_ms);
            continue;
        }

        if (kind == PacketKind::ParticipantVitalsCorrection &&
            received == static_cast<int>(sizeof(ParticipantVitalsCorrectionPacket))) {
            ParticipantVitalsCorrectionPacket packet{};
            std::memcpy(&packet, packet_buffer.data(), sizeof(packet));
            if (!IsValidHeader(
                    packet.header,
                    PacketKind::ParticipantVitalsCorrection)) {
                continue;
            }
            g_local_transport.packets_received += 1;
            ApplyParticipantVitalsCorrectionPacket(packet, from, now_ms);
            continue;
        }

        if (kind == PacketKind::WorldSnapshot && received == static_cast<int>(sizeof(WorldSnapshotPacket))) {
            WorldSnapshotPacket packet{};
            std::memcpy(&packet, packet_buffer.data(), sizeof(packet));
            if (!IsValidHeader(packet.header, PacketKind::WorldSnapshot)) {
                continue;
            }
            g_local_transport.packets_received += 1;
            ApplyWorldSnapshotPacket(packet, from, now_ms);
            continue;
        }

        if (kind == PacketKind::LootSnapshot && received == static_cast<int>(sizeof(LootSnapshotPacket))) {
            LootSnapshotPacket packet{};
            std::memcpy(&packet, packet_buffer.data(), sizeof(packet));
            if (!IsValidHeader(packet.header, PacketKind::LootSnapshot)) {
                continue;
            }
            g_local_transport.packets_received += 1;
            ApplyLootSnapshotPacket(packet, from, now_ms);
            continue;
        }

        if (kind == PacketKind::EnemyDamageClaim && received == static_cast<int>(sizeof(EnemyDamageClaimPacket))) {
            EnemyDamageClaimPacket packet{};
            std::memcpy(&packet, packet_buffer.data(), sizeof(packet));
            if (!IsValidHeader(packet.header, PacketKind::EnemyDamageClaim)) {
                continue;
            }
            g_local_transport.packets_received += 1;
            ApplyEnemyDamageClaimPacket(packet, from, now_ms);
            continue;
        }

        if (kind == PacketKind::EnemyDamageResult && received == static_cast<int>(sizeof(EnemyDamageResultPacket))) {
            EnemyDamageResultPacket packet{};
            std::memcpy(&packet, packet_buffer.data(), sizeof(packet));
            if (!IsValidHeader(packet.header, PacketKind::EnemyDamageResult)) {
                continue;
            }
            g_local_transport.packets_received += 1;
            ApplyEnemyDamageCorrection(packet);
            continue;
        }

        if (kind == PacketKind::LootPickupRequest && received == static_cast<int>(sizeof(LootPickupRequestPacket))) {
            LootPickupRequestPacket packet{};
            std::memcpy(&packet, packet_buffer.data(), sizeof(packet));
            if (!IsValidHeader(packet.header, PacketKind::LootPickupRequest)) {
                continue;
            }
            g_local_transport.packets_received += 1;
            ApplyLootPickupRequestPacket(packet, from, now_ms);
            continue;
        }

        if (kind == PacketKind::LootPickupResult && received == static_cast<int>(sizeof(LootPickupResultPacket))) {
            LootPickupResultPacket packet{};
            std::memcpy(&packet, packet_buffer.data(), sizeof(packet));
            if (!IsValidHeader(packet.header, PacketKind::LootPickupResult)) {
                continue;
            }
            g_local_transport.packets_received += 1;
            ApplyLootPickupResultPacket(packet, from, now_ms);
            continue;
        }

        if (kind == PacketKind::LevelUpOffer && received == static_cast<int>(sizeof(LevelUpOfferPacket))) {
            LevelUpOfferPacket packet{};
            std::memcpy(&packet, packet_buffer.data(), sizeof(packet));
            if (!IsValidHeader(packet.header, PacketKind::LevelUpOffer)) {
                continue;
            }
            g_local_transport.packets_received += 1;
            ApplyLevelUpOfferPacket(packet, from, now_ms);
            continue;
        }

        if (kind == PacketKind::LevelUpChoice && received == static_cast<int>(sizeof(LevelUpChoicePacket))) {
            LevelUpChoicePacket packet{};
            std::memcpy(&packet, packet_buffer.data(), sizeof(packet));
            if (!IsValidHeader(packet.header, PacketKind::LevelUpChoice)) {
                continue;
            }
            g_local_transport.packets_received += 1;
            ApplyLevelUpChoicePacket(packet, from, now_ms);
            continue;
        }

        if (kind == PacketKind::LevelUpChoiceResult &&
            received == static_cast<int>(sizeof(LevelUpChoiceResultPacket))) {
            LevelUpChoiceResultPacket packet{};
            std::memcpy(&packet, packet_buffer.data(), sizeof(packet));
            if (!IsValidHeader(packet.header, PacketKind::LevelUpChoiceResult)) {
                continue;
            }
            g_local_transport.packets_received += 1;
            ApplyLevelUpChoiceResultPacket(packet, from, now_ms);
        }
    } while (false);
}

void ReceivePackets(std::uint64_t now_ms) {
    if (g_local_transport.backend != GameplayTransportBackend::LocalUdp) {
        return;
    }
    for (int packet_index = 0; packet_index < kMaxPacketsPerTick; ++packet_index) {
        TransportPacketBuffer packet_buffer{};
        sockaddr_in udp_from{};
        int from_length = sizeof(udp_from);
        const int received = recvfrom(
            g_local_transport.socket_handle,
            packet_buffer.data(),
            static_cast<int>(packet_buffer.size()),
            0,
            reinterpret_cast<sockaddr*>(&udp_from),
            &from_length);
        if (received == SOCKET_ERROR) {
            return;
        }
        TransportPeerEndpoint from;
        from.backend = GameplayTransportBackend::LocalUdp;
        from.udp_address = udp_from;
        DispatchReceivedPacket(packet_buffer, received, from, now_ms);
    }
}
