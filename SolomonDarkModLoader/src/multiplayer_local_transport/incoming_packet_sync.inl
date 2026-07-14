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

    const auto last_state_sequence_it =
        g_local_transport.last_state_packet_sequence_by_participant.find(
            packet.participant_id);
    if (last_state_sequence_it !=
            g_local_transport.last_state_packet_sequence_by_participant.end() &&
        !IsPacketSequenceNewer(
            packet.header.sequence,
            last_state_sequence_it->second)) {
        return;
    }
    g_local_transport.last_state_packet_sequence_by_participant[
        packet.participant_id] = packet.header.sequence;
    RelayStatePacketToPeers(packet, from);

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
                (packet.participant_vitals_correction_ack_sequence ==
                     correction.correction_sequence ||
                 IsPacketSequenceNewer(
                     packet.participant_vitals_correction_ack_sequence,
                     correction.correction_sequence));
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

    if (packet_from_configured_authority) {
        std::vector<std::uint64_t> waiting_participant_ids;
        const auto waiting_count =
            (std::min<std::size_t>)(
                packet.level_up_waiting_count,
                kLevelUpWaitStatusMaxParticipants);
        waiting_participant_ids.reserve(waiting_count);
        for (std::size_t index = 0; index < waiting_count; ++index) {
            const auto participant_id =
                packet.level_up_waiting_participant_ids[index];
            if (participant_id != 0) {
                waiting_participant_ids.push_back(participant_id);
            }
        }
        (void)ApplyAuthoritativeLevelUpWaitStatus(
            packet.authority_participant_id,
            packet.level_up_barrier_id,
            packet.level_up_barrier_revision,
            packet.level_up_deadline_remaining_ms,
            packet.level_up_pause_active != 0,
            (packet.level_up_barrier_flags &
             kLevelUpBarrierFlagTimedOut) != 0,
            std::move(waiting_participant_ids),
            now_ms);
    }

    UpdateRuntimeState([&](RuntimeState& state) {

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
    StageClientHostRunExitFollow(
        packet,
        packet_from_configured_authority,
        now_ms);

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
