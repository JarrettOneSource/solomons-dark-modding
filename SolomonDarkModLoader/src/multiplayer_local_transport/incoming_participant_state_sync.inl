bool IsSaneParticipantInventorySnapshot(const StatePacket& packet) {
    if (packet.inventory_item_count > kParticipantInventorySnapshotMaxItems ||
        packet.inventory_item_total_count < packet.inventory_item_count) {
        return false;
    }

    for (std::size_t index = 0; index < packet.inventory_item_count; ++index) {
        const auto& item = packet.inventory_items[index];
        if (item.type_id == 0 ||
            item.container_depth > kSDModInventorySnapshotMaxDepth) {
            return false;
        }
        if (item.container_depth == 0) {
            if (item.parent_item_index != -1) {
                return false;
            }
            continue;
        }
        if (item.parent_item_index < 0 ||
            static_cast<std::size_t>(item.parent_item_index) >= index) {
            return false;
        }
        const auto& parent = packet.inventory_items[item.parent_item_index];
        if (parent.type_id != 0x1B60 ||
            item.container_depth !=
                static_cast<std::uint16_t>(parent.container_depth + 1)) {
            return false;
        }
    }
    return true;
}

void ApplyRemoteStatePacket(
    const StatePacket& packet,
    const TransportPeerEndpoint& from,
    std::uint64_t now_ms) {
    if (packet.participant_id == 0 ||
        packet.participant_session_nonce == 0 ||
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

    auto session_it =
        g_local_transport.session_nonce_by_participant.find(packet.participant_id);
    if (session_it == g_local_transport.session_nonce_by_participant.end()) {
        g_local_transport.session_nonce_by_participant.emplace(
            packet.participant_id,
            packet.participant_session_nonce);
    } else if (session_it->second != packet.participant_session_nonce) {
        const auto retired_it =
            g_local_transport.retired_session_nonces_by_participant.find(
                packet.participant_id);
        if (retired_it !=
                g_local_transport.retired_session_nonces_by_participant.end() &&
            retired_it->second.find(packet.participant_session_nonce) !=
                retired_it->second.end()) {
            return;
        }
        const auto previous_nonce = session_it->second;
        ResetRemoteParticipantSessionEpoch(
            packet.participant_id,
            false,
            true);
        g_local_transport.retired_session_nonces_by_participant[
            packet.participant_id].insert(previous_nonce);
        g_local_transport.session_nonce_by_participant[packet.participant_id] =
            packet.participant_session_nonce;
        Log(
            "Multiplayer participant gameplay session changed; accepted new stream epochs. "
            "participant_id=" + std::to_string(packet.participant_id) +
            " previous_nonce=" + std::to_string(previous_nonce) +
            " session_nonce=" +
            std::to_string(packet.participant_session_nonce));
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
    RelayParticipantPacketToPeers(packet, from);

    const auto scene_intent = SceneIntentFromPacket(packet);
    const auto display_name = PacketDisplayName(packet);
    const auto normalized = NormalizeParticipantFramePacket(packet);
    const bool packet_from_configured_authority =
        IsAuthoritativeHostParticipantPacket(packet, from);
    const bool inventory_packet_is_sane =
        IsSaneParticipantInventorySnapshot(packet);

    if (IsLocalTransportHost()) {
        ApplyHostMenuPauseRequest(
            packet.participant_id,
            packet.run_nonce,
            packet.local_menu_pause_request_epoch,
            packet.local_menu_pause_requested != 0,
            now_ms);
    } else if (packet_from_configured_authority) {
        ApplyAuthoritativeSharedGameplayPause(
            packet.authority_participant_id,
            packet.run_nonce,
            packet.shared_gameplay_pause_origin_participant_id,
            packet.shared_gameplay_pause_deadline_remaining_ms,
            packet.shared_gameplay_pause_active != 0,
            packet.shared_gameplay_pause_timed_out != 0,
            now_ms);
        ApplyAuthoritativeLuaTimeControlSnapshot(
            packet.authority_participant_id,
            packet.run_nonce,
            packet.lua_time_scale_units,
            packet.lua_time_revision);
    }

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
    ApplyAuthoritativeWaveRespawn(
        packet,
        packet_from_configured_authority,
        now_ms);

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
        participant->character_profile = profile;
        ApplyParticipantFrameToRuntime(
            packet,
            scene_intent,
            normalized,
            now_ms,
            participant);
        const bool should_apply_gold =
            !participant->owned_progression.initialized ||
            packet.gold_revision >= participant->owned_progression.gold_revision;
        participant->owned_progression.initialized = true;
        if (should_apply_gold) {
            participant->owned_progression.gold = packet.owned_gold;
            participant->owned_progression.gold_revision = packet.gold_revision;
        }
        const bool should_apply_inventory =
            inventory_packet_is_sane &&
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
                item.recipe_uid = packet_item.recipe_uid;
                item.slot = packet_item.slot;
                item.stack_count = packet_item.stack_count;
                item.parent_item_index = packet_item.parent_item_index;
                item.container_depth = packet_item.container_depth;
                participant->owned_progression.inventory_items.push_back(item);
            }
        }
        const auto equipped_type_is = [](
            const ParticipantEquippedItemPacketState& item,
            std::initializer_list<std::uint32_t> allowed_types) {
            return item.type_id == 0 ||
                   std::find(
                       allowed_types.begin(),
                       allowed_types.end(),
                       item.type_id) != allowed_types.end();
        };
        bool equipment_packet_is_sane = packet.equipment_valid != 0 &&
            equipped_type_is(packet.equipped_hat, {0x1B5D}) &&
            equipped_type_is(packet.equipped_robe, {0x1B5E}) &&
            equipped_type_is(packet.equipped_weapon, {0x1B5C, 0x1B63}) &&
            equipped_type_is(packet.equipped_amulet, {0x1B5B});
        for (const auto& ring : packet.equipped_rings) {
            equipment_packet_is_sane =
                equipment_packet_is_sane && equipped_type_is(ring, {0x1B5A});
        }
        const bool should_apply_equipment =
            equipment_packet_is_sane &&
            (!participant->owned_progression.equipment.valid ||
             packet.equipment_revision >=
                 participant->owned_progression.equipment_revision);
        if (should_apply_equipment) {
            const auto copy_equipped_item = [](
                const ParticipantEquippedItemPacketState& source,
                ParticipantEquippedItemState* destination) {
                destination->type_id = source.type_id;
                destination->recipe_uid = source.recipe_uid;
            };
            auto& equipment = participant->owned_progression.equipment;
            equipment = ParticipantEquipmentState{};
            equipment.valid = true;
            copy_equipped_item(packet.equipped_hat, &equipment.hat);
            copy_equipped_item(packet.equipped_robe, &equipment.robe);
            copy_equipped_item(packet.equipped_weapon, &equipment.weapon);
            for (std::size_t index = 0; index < equipment.rings.size(); ++index) {
                copy_equipped_item(packet.equipped_rings[index], &equipment.rings[index]);
            }
            copy_equipped_item(packet.equipped_amulet, &equipment.amulet);
            participant->owned_progression.equipment_revision =
                packet.equipment_revision;
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
        ApplyHagathaPerkPacketState(
            packet.hagatha_perk_revision,
            packet.hagatha_perks,
            g_local_transport.is_host && participant->runtime.in_run,
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
    if (normalized.transform_valid &&
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

void ApplyRemoteParticipantFramePacket(
    const ParticipantFramePacket& packet,
    const TransportPeerEndpoint& from,
    std::uint64_t now_ms) {
    if (packet.participant_id == 0 ||
        packet.participant_session_nonce == 0 ||
        packet.participant_id == kLocalParticipantId ||
        packet.participant_id == g_local_transport.local_peer_id) {
        return;
    }

    const auto session_it =
        g_local_transport.session_nonce_by_participant.find(
            packet.participant_id);
    if (session_it ==
            g_local_transport.session_nonce_by_participant.end() ||
        session_it->second != packet.participant_session_nonce) {
        return;
    }

    const auto last_sequence_it =
        g_local_transport.last_participant_frame_sequence_by_participant.find(
            packet.participant_id);
    if (last_sequence_it !=
            g_local_transport.last_participant_frame_sequence_by_participant.end() &&
        !IsPacketSequenceNewer(
            packet.header.sequence,
            last_sequence_it->second)) {
        return;
    }
    g_local_transport.last_participant_frame_sequence_by_participant[
        packet.participant_id] = packet.header.sequence;
    UpsertPeerEndpoint(from, packet.participant_id, now_ms);
    RelayParticipantPacketToPeers(packet, from);

    const auto scene_intent = SceneIntentFromPacket(packet);
    const auto normalized = NormalizeParticipantFramePacket(packet);
    const bool packet_from_configured_authority =
        IsAuthoritativeHostParticipantPacket(packet, from);
    if (IsLocalTransportHost()) {
        ApplyHostMenuPauseRequest(
            packet.participant_id,
            packet.run_nonce,
            packet.local_menu_pause_request_epoch,
            packet.local_menu_pause_requested != 0,
            now_ms);
    } else if (packet_from_configured_authority) {
        ApplyAuthoritativeSharedGameplayPause(
            packet.authority_participant_id,
            packet.run_nonce,
            packet.shared_gameplay_pause_origin_participant_id,
            packet.shared_gameplay_pause_deadline_remaining_ms,
            packet.shared_gameplay_pause_active != 0,
            packet.shared_gameplay_pause_timed_out != 0,
            now_ms);
        ApplyAuthoritativeLuaTimeControlSnapshot(
            packet.authority_participant_id,
            packet.run_nonce,
            packet.lua_time_scale_units,
            packet.lua_time_revision);
    }
    ApplyAuthoritativeWaveRespawn(
        packet,
        packet_from_configured_authority,
        now_ms);
    MultiplayerCharacterProfile profile;
    bool participant_found = false;
    UpdateRuntimeState([&](RuntimeState& state) {
        auto* participant = FindParticipant(state, packet.participant_id);
        if (participant == nullptr || !IsRemoteParticipant(*participant)) {
            return;
        }
        ApplyParticipantFrameToRuntime(
            packet,
            scene_intent,
            normalized,
            now_ms,
            participant);
        profile = participant->character_profile;
        participant_found = true;
    });
    if (!participant_found) {
        return;
    }

    ApplyAuthorityWaveSummaryFromPacket(
        packet,
        packet_from_configured_authority);

    MaybeQueueClientHostRunStart(packet, scene_intent, from, now_ms);
    MaybeQueueClientHostRegionFollow(packet, scene_intent, from, now_ms);
    StageClientHostRunExitFollow(
        packet,
        packet_from_configured_authority,
        now_ms);

    SDModParticipantGameplayState gameplay_state;
    const bool participant_materialized =
        TryGetParticipantGameplayState(
            packet.participant_id,
            &gameplay_state) &&
        gameplay_state.entity_materialized &&
        gameplay_state.actor_address != 0;
    if (normalized.transform_valid &&
        !participant_materialized &&
        DoesLocalSceneMatchParticipantIntent(scene_intent) &&
        IsValidCharacterProfile(profile)) {
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
