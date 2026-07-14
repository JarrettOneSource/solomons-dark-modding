bool TryApplyLivePrimarySelectionToProfile(
    const SDModGameplaySelectionDebugState& selection_state,
    MultiplayerCharacterProfile* profile) {
    if (profile == nullptr || !selection_state.valid) {
        return false;
    }

    const auto selected_primary_entry = selection_state.slot_selection_entries[0];
    int element_id = -1;
    switch (selected_primary_entry) {
    case 0x10:
        element_id = 0;
        break;
    case 0x20:
        element_id = 1;
        break;
    case 0x28:
        element_id = 2;
        break;
    case 0x18:
        element_id = 3;
        break;
    case 0x08:
        element_id = 4;
        break;
    default:
        break;
    }
    if (element_id < 0) {
        return false;
    }

    auto updated = *profile;
    updated.element_id = element_id;

    int resolved_primary_entry = -1;
    NativePrimarySpellSelection primary_selection;
    if (TryResolveNativePrimarySelectionFromPair(
            selected_primary_entry,
            selected_primary_entry,
            &primary_selection)) {
        resolved_primary_entry = selected_primary_entry;
    } else if (!TryResolveNativePrimaryEntryForElement(element_id, &resolved_primary_entry)) {
        return false;
    }

    updated.loadout.primary_entry_index = resolved_primary_entry;
    updated.loadout.primary_combo_entry_index = resolved_primary_entry;

    if (!IsValidCharacterProfile(updated)) {
        return false;
    }

    *profile = updated;
    return true;
}
bool TryApplyLiveBeltSkillLoadoutToProfile(MultiplayerCharacterProfile* profile) {
    if (profile == nullptr || kGameObjectGlobal == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto game_object_global_address =
        memory.ResolveGameAddressOrZero(kGameObjectGlobal);
    uintptr_t gameplay_address = 0;
    if (game_object_global_address == 0 ||
        !memory.TryReadValue(game_object_global_address, &gameplay_address) ||
        gameplay_address == 0) {
        return false;
    }

    auto secondary_entries = profile->loadout.secondary_entry_indices;
    for (std::size_t slot = 0; slot < secondary_entries.size(); ++slot) {
        const auto button_address =
            gameplay_address + kGameplayBeltButtonArrayOffset +
            slot * kGameplayBeltButtonStride;
        std::uint32_t button_type = 0;
        std::int32_t skill_entry_index = -1;
        if (!memory.TryReadField(button_address, kBeltButtonTypeOffset, &button_type) ||
            !memory.TryReadField(
                button_address,
                kBeltButtonSkillEntryIndexOffset,
                &skill_entry_index)) {
            return false;
        }
        secondary_entries[slot] =
            button_type == kBeltButtonSkillTypeId &&
                    skill_entry_index >= 0 &&
                    skill_entry_index <
                        static_cast<std::int32_t>(kParticipantProgressionBookSnapshotMaxEntries)
                ? skill_entry_index
                : -1;
    }

    profile->loadout.secondary_entry_indices = secondary_entries;
    return true;
}

std::vector<TransportPeerEndpoint> BuildKnownSendEndpoints() {
    std::vector<TransportPeerEndpoint> endpoints;
    if (g_local_transport.configured_remote_valid) {
        endpoints.push_back(g_local_transport.configured_remote);
    }
    for (const auto& peer : g_local_transport.peers) {
        const bool already_added = std::any_of(endpoints.begin(), endpoints.end(), [&](const TransportPeerEndpoint& existing) {
            return SameEndpoint(existing, peer.endpoint);
        });
        if (!already_added) {
            endpoints.push_back(peer.endpoint);
        }
    }
    return endpoints;
}

void AddUniqueLevelUpWaitParticipantId(
    std::vector<std::uint64_t>* participant_ids,
    std::uint64_t participant_id) {
    if (participant_ids == nullptr || participant_id == 0) {
        return;
    }
    if (std::find(
            participant_ids->begin(),
            participant_ids->end(),
            participant_id) == participant_ids->end()) {
        participant_ids->push_back(participant_id);
    }
}

bool HasUnresolvedIssuedLevelUpOfferForParticipant(std::uint64_t participant_id) {
    if (participant_id == 0) {
        return false;
    }
    for (const auto& [offer_id, offer] : g_local_transport.issued_level_up_offers_by_id) {
        (void)offer_id;
        if (!offer.resolved && offer.target_participant_id == participant_id) {
            return true;
        }
    }
    return false;
}

std::vector<std::uint64_t> CollectUnresolvedLevelUpOfferParticipantIds() {
    std::vector<std::uint64_t> participant_ids;
    if (!g_local_transport.initialized || !g_local_transport.is_host) {
        return participant_ids;
    }

    participant_ids.reserve(
        g_local_transport.issued_level_up_offers_by_id.size() +
        g_local_transport.pending_level_up_offer_targets_by_participant.size());
    for (const auto& [offer_id, offer] : g_local_transport.issued_level_up_offers_by_id) {
        (void)offer_id;
        if (offer.resolved || offer.target_participant_id == 0) {
            continue;
        }
        AddUniqueLevelUpWaitParticipantId(&participant_ids, offer.target_participant_id);
    }
    for (const auto& [participant_id, pending] : g_local_transport.pending_level_up_offer_targets_by_participant) {
        (void)participant_id;
        AddUniqueLevelUpWaitParticipantId(&participant_ids, pending.target_participant_id);
    }
    std::sort(participant_ids.begin(), participant_ids.end());
    return participant_ids;
}

bool HasPendingLocalLevelUpChoice(const RuntimeState& runtime_state) {
    const auto& offer = runtime_state.active_level_up_offer;
    return offer.valid &&
           !offer.selection_submitted &&
           offer.target_participant_id == g_local_transport.local_peer_id;
}

std::string ResolveParticipantNameForStatus(
    const RuntimeState& runtime_state,
    std::uint64_t participant_id) {
    if (participant_id == g_local_transport.local_peer_id) {
        const auto* local = FindLocalParticipant(runtime_state);
        if (local != nullptr && !local->name.empty()) {
            return local->name;
        }
        return "You";
    }

    const auto* participant = FindParticipant(runtime_state, participant_id);
    if (participant != nullptr && !participant->name.empty()) {
        return participant->name;
    }
    return "Player " + std::to_string(participant_id);
}

std::string BuildLevelUpWaitStatusTextFromIds(
    const RuntimeState& runtime_state,
    const std::vector<std::uint64_t>& participant_ids) {
    if (participant_ids.empty()) {
        return {};
    }

    std::string text = "Waiting for skill picks: ";
    for (std::size_t index = 0; index < participant_ids.size(); ++index) {
        if (index != 0) {
            text += ", ";
        }
        text += ResolveParticipantNameForStatus(runtime_state, participant_ids[index]);
    }
    return text;
}

void RefreshLocalParticipantFromGameState() {
    SDModPlayerState player_state;
    if (!TryGetPlayerState(&player_state) || !player_state.valid) {
        return;
    }

    SDModGameplaySelectionDebugState selection_state;
    const bool have_selection_state =
        TryGetGameplaySelectionDebugState(&selection_state) && selection_state.valid;
    const auto scene_intent = SceneIntentFromLocalScene();
    const auto configured_name = ReadLocalDisplayName();
    SDModWorldState world_state;
    const bool have_world_state = TryGetWorldState(&world_state) && world_state.valid;
    SDModInventoryState inventory_state;
    const bool have_inventory_state =
        TryGetPlayerInventoryState(&inventory_state) && inventory_state.valid;
    SDModProgressionBookState progression_book_state;
    const bool have_progression_book_state =
        TryGetPlayerProgressionBookState(&progression_book_state) && progression_book_state.valid;
    UpdateRuntimeState([&](RuntimeState& state) {
        auto* local = UpsertLocalParticipant(state);
        if (local == nullptr) {
            return;
        }

        local->ready = true;
        if (!configured_name.empty()) {
            local->name = configured_name;
        }
        local->character_profile.level = player_state.level;
        local->character_profile.experience = player_state.xp;
        if (have_selection_state) {
            const auto previous_element_id = local->character_profile.element_id;
            const auto previous_primary_entry = local->character_profile.loadout.primary_entry_index;
            const auto previous_combo_entry = local->character_profile.loadout.primary_combo_entry_index;
            if (TryApplyLivePrimarySelectionToProfile(selection_state, &local->character_profile)) {
                if (local->character_profile.element_id != previous_element_id ||
                    local->character_profile.loadout.primary_entry_index != previous_primary_entry ||
                    local->character_profile.loadout.primary_combo_entry_index != previous_combo_entry) {
                    Log(
                        "Multiplayer local primary selection refreshed. element_id=" +
                        std::to_string(local->character_profile.element_id) +
                        " primary_entry=" +
                        std::to_string(local->character_profile.loadout.primary_entry_index) +
                        " combo_entry=" +
                        std::to_string(local->character_profile.loadout.primary_combo_entry_index));
                }
            }
        }
        const auto previous_secondary_entries =
            local->character_profile.loadout.secondary_entry_indices;
        if (TryApplyLiveBeltSkillLoadoutToProfile(&local->character_profile) &&
            local->character_profile.loadout.secondary_entry_indices !=
                previous_secondary_entries) {
            std::ostringstream entries;
            for (std::size_t slot = 0;
                 slot < local->character_profile.loadout.secondary_entry_indices.size();
                 ++slot) {
                if (slot != 0) {
                    entries << ',';
                }
                entries << local->character_profile.loadout.secondary_entry_indices[slot];
            }
            Log(
                "Multiplayer local native belt loadout refreshed. entries=" +
                entries.str());
        }
        local->transport_connected = true;
        if (g_local_transport.backend == GameplayTransportBackend::LocalUdp) {
            local->transport_using_relay = false;
        }
        local->runtime.valid = true;
        local->runtime.transform_valid = true;
        local->runtime.in_run = scene_intent.kind == ParticipantSceneIntentKind::Run;
        local->runtime.scene_intent = scene_intent;
        if (local->runtime.life_max > 0.0f &&
            local->runtime.life_current > 0.0f &&
            player_state.max_hp > 0.0f &&
            player_state.hp <= 0.0f) {
            Log(
                "Multiplayer local participant vitals crossed to zero before state publish. participant_id=" +
                std::to_string(g_local_transport.local_peer_id) +
                " hp=" + std::to_string(player_state.hp) +
                "/" + std::to_string(player_state.max_hp) +
                " previous_hp=" + std::to_string(local->runtime.life_current) +
                "/" + std::to_string(local->runtime.life_max) +
                " level=" + std::to_string(player_state.level) +
                " xp=" + std::to_string(player_state.xp) +
                " progression=" + HexString(player_state.progression_address));
        }
        local->runtime.life_current = player_state.hp;
        local->runtime.life_max = player_state.max_hp;
        local->runtime.mana_current = player_state.mp;
        local->runtime.mana_max = player_state.max_mp;
        local->runtime.move_speed = player_state.move_speed;
        local->runtime.persistent_status_flags =
            player_state.persistent_status_flags;
        local->runtime.transient_status_flags =
            player_state.transient_status_flags;
        local->runtime.poison_remaining_ticks =
            player_state.poison_remaining_ticks;
        local->runtime.level = player_state.level;
        local->runtime.experience_current = player_state.xp;
        local->runtime.primary_entry_index = local->character_profile.loadout.primary_entry_index;
        local->runtime.primary_combo_entry_index = local->character_profile.loadout.primary_combo_entry_index;
        local->runtime.queued_secondary_entry_indices = local->character_profile.loadout.secondary_entry_indices;
        const auto previous_owned_gold = local->owned_progression.gold;
        const bool previous_owned_progression_initialized = local->owned_progression.initialized;
        local->owned_progression.initialized = true;
        local->owned_progression.gold = player_state.gold;
        if (previous_owned_progression_initialized && previous_owned_gold != player_state.gold) {
            local->owned_progression.gold_revision += 1;
        }
        if (scene_intent.kind != ParticipantSceneIntentKind::Run) {
            local->owned_progression.inventory_host_authoritative = false;
        }
        if (have_inventory_state && !local->owned_progression.inventory_host_authoritative) {
            RefreshOwnedInventoryFromSnapshot(inventory_state, &local->owned_progression);
        }
        if (have_progression_book_state) {
            RefreshOwnedProgressionBookFromSnapshot(progression_book_state, &local->owned_progression);
        }
        if (have_selection_state) {
            RefreshOwnedConcentrationSelections(
                selection_state.concentration_entry_a,
                selection_state.concentration_entry_b,
                &local->owned_progression);
        }
        RefreshOwnedDerivedStats(
            player_state.derived_stats,
            &local->owned_progression);
        RefreshOwnedAbilityLoadoutFromProfile(local->character_profile.loadout, &local->owned_progression);
        if (have_world_state) {
            local->runtime.wave = world_state.wave;
        }
        local->runtime.position_x = player_state.x;
        local->runtime.position_y = player_state.y;
        local->runtime.heading = player_state.heading;
        local->runtime.anim_drive_state = player_state.anim_drive_state;
        local->runtime.presentation_flags =
            ParticipantPresentationFlagAnimationDriveWord |
            ParticipantPresentationFlagRenderDriveFloats;
        // The staff attachment tail field at +0x84 is native-owned and can hold
        // process-local/pointer-like data in run scenes. Do not mirror it across
        // clients; remote cast playback and local materialization own staff glow.
        local->runtime.attachment_staff_visual_state = 0;
        if (kActorRenderVariantPrimaryOffset != 0 &&
            kActorRenderVariantSecondaryOffset != 0 &&
            kActorRenderWeaponTypeOffset != 0 &&
            kActorRenderSelectionByteOffset != 0 &&
            kActorRenderVariantTertiaryOffset != 0) {
            local->runtime.presentation_flags |= ParticipantPresentationFlagRenderSelectorBytes;
            local->runtime.render_variant_primary = player_state.render_variant_primary;
            local->runtime.render_variant_secondary = player_state.render_variant_secondary;
            local->runtime.render_weapon_type = player_state.render_weapon_type;
            local->runtime.render_selection_byte = player_state.render_selection_byte;
            local->runtime.render_variant_tertiary = player_state.render_variant_tertiary;
        } else {
            local->runtime.render_variant_primary = 0;
            local->runtime.render_variant_secondary = 0;
            local->runtime.render_weapon_type = 0;
            local->runtime.render_selection_byte = 0;
            local->runtime.render_variant_tertiary = 0;
        }
        std::uint32_t primary_visual_type = 0;
        std::uint32_t secondary_visual_type = 0;
        std::array<std::uint8_t, kParticipantVisualLinkColorBlockBytes> primary_visual_block = {};
        std::array<std::uint8_t, kParticipantVisualLinkColorBlockBytes> secondary_visual_block = {};
        if (TryReadVisualLinkColorBlock(
                player_state.primary_visual_lane,
                &primary_visual_type,
                &primary_visual_block) &&
            TryReadVisualLinkColorBlock(
                player_state.secondary_visual_lane,
                &secondary_visual_type,
                &secondary_visual_block)) {
            local->runtime.presentation_flags |= ParticipantPresentationFlagVisualLinkColorBlocks;
            local->runtime.primary_visual_link_type_id = primary_visual_type;
            local->runtime.secondary_visual_link_type_id = secondary_visual_type;
            local->runtime.primary_visual_link_color_block = primary_visual_block;
            local->runtime.secondary_visual_link_color_block = secondary_visual_block;
        } else {
            local->runtime.primary_visual_link_type_id = 0;
            local->runtime.secondary_visual_link_type_id = 0;
            local->runtime.primary_visual_link_color_block = {};
            local->runtime.secondary_visual_link_color_block = {};
        }
        local->runtime.anim_drive_state_word = player_state.anim_drive_state_word;
        local->runtime.walk_cycle_primary = player_state.walk_cycle_primary;
        local->runtime.walk_cycle_secondary = player_state.walk_cycle_secondary;
        local->runtime.render_drive_stride = player_state.render_drive_stride;
        local->runtime.render_advance_rate = player_state.render_advance_rate;
        local->runtime.render_advance_phase = player_state.render_advance_phase;
        const auto effect_state = NormalizeRenderDriveEffectState(
            player_state.render_drive_effect_timer,
            player_state.render_drive_effect_progress);
        local->runtime.render_drive_effect_timer = effect_state.timer;
        local->runtime.render_drive_effect_progress = effect_state.progress;
        local->runtime.render_drive_overlay_alpha = player_state.render_drive_overlay_alpha;
        local->runtime.render_drive_move_blend = player_state.render_drive_move_blend;
    });
}

StatePacket BuildLocalStatePacket() {
    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);

    StatePacket packet{};
    packet.header = MakePacketHeader(PacketKind::State, g_local_transport.next_sequence++);
    packet.participant_id = g_local_transport.local_peer_id;
    packet.authority_participant_id =
        g_local_transport.is_host ? g_local_transport.local_peer_id : 0;
    if (local == nullptr) {
        return packet;
    }

    CopyPacketDisplayName(local->name, &packet);
    packet.ready = local->ready ? 1 : 0;
    packet.in_run = local->runtime.in_run ? 1 : 0;
    packet.transform_valid = local->runtime.transform_valid ? 1 : 0;
    packet.controller_kind = static_cast<std::uint8_t>(ParticipantControllerKind::Native);
    packet.run_nonce = local->runtime.run_nonce;
    packet.participant_vitals_correction_ack_sequence =
        g_local_transport.last_applied_participant_vitals_correction_sequence;
    packet.element_id = local->character_profile.element_id;
    packet.discipline_id = static_cast<std::int32_t>(local->character_profile.discipline_id);
    for (std::size_t index = 0; index < local->character_profile.appearance.choice_ids.size(); ++index) {
        packet.appearance_choice_ids[index] = local->character_profile.appearance.choice_ids[index];
    }
    packet.level = local->runtime.level;
    packet.wave = local->runtime.wave;
    packet.life_current = local->runtime.life_current;
    packet.life_max = local->runtime.life_max;
    packet.mana_current = local->runtime.mana_current;
    packet.mana_max = local->runtime.mana_max;
    packet.move_speed = local->runtime.move_speed;
    packet.persistent_status_flags =
        local->runtime.persistent_status_flags;
    packet.transient_status_flags =
        local->runtime.transient_status_flags;
    packet.poison_remaining_ticks =
        local->runtime.poison_remaining_ticks;
    packet.experience_current = local->runtime.experience_current;
    packet.experience_next = local->runtime.experience_next;
    packet.owned_gold = local->owned_progression.gold;
    packet.gold_revision = local->owned_progression.gold_revision;
    packet.inventory_revision = local->owned_progression.inventory_revision;
    packet.spellbook_revision = local->owned_progression.spellbook_revision;
    packet.statbook_revision = local->owned_progression.statbook_revision;
    packet.loadout_revision = local->owned_progression.loadout_revision;
    packet.concentration_revision = local->owned_progression.concentration_revision;
    packet.concentration_selection_valid =
        local->owned_progression.concentration_selection_valid ? 1 : 0;
    packet.concentration_entry_a = local->owned_progression.concentration_entry_a;
    packet.concentration_entry_b = local->owned_progression.concentration_entry_b;
    BuildDerivedStatPacketState(
        local->owned_progression,
        &packet.derived_stat_revision,
        &packet.derived_stats);
    if (g_local_transport.is_host) {
        const auto waiting_participant_ids = CollectUnresolvedLevelUpOfferParticipantIds();
        packet.level_up_pause_active = waiting_participant_ids.empty() ? 0 : 1;
        const auto waiting_count =
            (std::min)(
                waiting_participant_ids.size(),
                static_cast<std::size_t>(kLevelUpWaitStatusMaxParticipants));
        packet.level_up_waiting_count = static_cast<std::uint8_t>(waiting_count);
        for (std::size_t index = 0; index < waiting_count; ++index) {
            packet.level_up_waiting_participant_ids[index] = waiting_participant_ids[index];
        }
    }
    const auto inventory_packet_count =
        (std::min)(
            local->owned_progression.inventory_items.size(),
            static_cast<std::size_t>(kParticipantInventorySnapshotMaxItems));
    packet.inventory_item_count = static_cast<std::uint16_t>(inventory_packet_count);
    packet.inventory_item_total_count = local->owned_progression.inventory_item_total_count;
    packet.inventory_snapshot_flags =
        local->owned_progression.inventory_truncated ||
            local->owned_progression.inventory_items.size() > kParticipantInventorySnapshotMaxItems
            ? ParticipantInventorySnapshotFlagTruncated
            : 0;
    for (std::size_t index = 0; index < inventory_packet_count; ++index) {
        const auto& item = local->owned_progression.inventory_items[index];
        packet.inventory_items[index].type_id = item.type_id;
        packet.inventory_items[index].slot = item.slot;
        packet.inventory_items[index].stack_count = item.stack_count;
    }
    const auto progression_book_packet_count =
        (std::min)(
            local->owned_progression.progression_book_entries.size(),
            static_cast<std::size_t>(kParticipantProgressionBookSnapshotMaxEntries));
    packet.progression_book_entry_count = static_cast<std::uint16_t>(progression_book_packet_count);
    packet.progression_book_entry_total_count =
        local->owned_progression.progression_book_entry_total_count;
    packet.progression_book_snapshot_flags =
        local->owned_progression.progression_book_truncated ||
            local->owned_progression.progression_book_entries.size() >
                kParticipantProgressionBookSnapshotMaxEntries
            ? ParticipantProgressionBookSnapshotFlagTruncated
            : 0;
    for (std::size_t index = 0; index < progression_book_packet_count; ++index) {
        const auto& entry = local->owned_progression.progression_book_entries[index];
        packet.progression_book_entries[index].entry_index = entry.entry_index;
        packet.progression_book_entries[index].internal_id = entry.internal_id;
        packet.progression_book_entries[index].active = entry.active;
        packet.progression_book_entries[index].visible = entry.visible;
        packet.progression_book_entries[index].category = entry.category;
        packet.progression_book_entries[index].statbook_max_level = entry.statbook_max_level;
    }
    packet.primary_entry_index = local->character_profile.loadout.primary_entry_index;
    packet.primary_combo_entry_index = local->character_profile.loadout.primary_combo_entry_index;
    for (std::size_t index = 0; index < local->character_profile.loadout.secondary_entry_indices.size(); ++index) {
        packet.queued_secondary_entry_indices[index] =
            local->character_profile.loadout.secondary_entry_indices[index];
    }
    packet.position_x = local->runtime.position_x;
    packet.position_y = local->runtime.position_y;
    packet.heading = local->runtime.heading;
    packet.anim_drive_state = local->runtime.anim_drive_state;
    packet.presentation_flags = local->runtime.presentation_flags;
    packet.attachment_staff_visual_state = local->runtime.attachment_staff_visual_state;
    packet.render_variant_primary = local->runtime.render_variant_primary;
    packet.render_variant_secondary = local->runtime.render_variant_secondary;
    packet.render_weapon_type = local->runtime.render_weapon_type;
    packet.render_selection_byte = local->runtime.render_selection_byte;
    packet.render_variant_tertiary = local->runtime.render_variant_tertiary;
    packet.primary_visual_link_type_id = local->runtime.primary_visual_link_type_id;
    packet.secondary_visual_link_type_id = local->runtime.secondary_visual_link_type_id;
    std::memcpy(
        packet.primary_visual_link_color_block,
        local->runtime.primary_visual_link_color_block.data(),
        local->runtime.primary_visual_link_color_block.size());
    std::memcpy(
        packet.secondary_visual_link_color_block,
        local->runtime.secondary_visual_link_color_block.data(),
        local->runtime.secondary_visual_link_color_block.size());
    packet.anim_drive_state_word = local->runtime.anim_drive_state_word;
    packet.walk_cycle_primary = local->runtime.walk_cycle_primary;
    packet.walk_cycle_secondary = local->runtime.walk_cycle_secondary;
    packet.render_drive_stride = local->runtime.render_drive_stride;
    packet.render_advance_rate = local->runtime.render_advance_rate;
    packet.render_advance_phase = local->runtime.render_advance_phase;
    packet.render_drive_effect_timer = local->runtime.render_drive_effect_timer;
    packet.render_drive_effect_progress = local->runtime.render_drive_effect_progress;
    packet.render_drive_overlay_alpha = local->runtime.render_drive_overlay_alpha;
    packet.render_drive_move_blend = local->runtime.render_drive_move_blend;
    return packet;
}

bool BuildLocalWorldSnapshotPacket(WorldSnapshotPacket* packet) {
    if (packet == nullptr || !g_local_transport.is_host) {
        return false;
    }

    SDModSceneState scene_state;
    if (!TryGetSceneState(&scene_state) || !scene_state.valid) {
        return false;
    }

    std::vector<SDModSceneActorState> actors;
    if (!TryListSceneActors(&actors)) {
        return false;
    }

    const auto scene_intent = SceneIntentFromLocalScene();
    if (scene_intent.kind != ParticipantSceneIntentKind::SharedHub &&
        scene_intent.kind != ParticipantSceneIntentKind::Run) {
        return false;
    }

    RefreshWorldSceneTracking(scene_state);
    PruneHubWorldActorNetworkIds(actors, scene_intent.kind);
    PruneRunHostLocalWorldActorNetworkIds(actors, scene_intent.kind);

    WorldSnapshotPacket built{};
    built.header = MakePacketHeader(PacketKind::WorldSnapshot, g_local_transport.next_sequence++);
    built.authority_participant_id = g_local_transport.local_peer_id;
    built.scene_epoch = g_local_transport.world_scene_epoch;
    built.scene_kind = static_cast<std::uint8_t>(WorldSceneKindFromSceneIntent(scene_intent));

    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);
    if (local != nullptr) {
        built.run_nonce = local->runtime.run_nonce;
    }

    const bool run_scene = scene_intent.kind == ParticipantSceneIntentKind::Run;
    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    if (run_scene) {
        PruneRecentRunEnemyDeathSnapshots(now_ms);
    }
    std::uint32_t valid_recent_death_count = 0;
    if (run_scene) {
        for (const auto& [network_actor_id, death_snapshot] :
             g_local_transport.recent_run_enemy_deaths_by_network_id) {
            if (network_actor_id != 0 &&
                death_snapshot.native_type_id != 0 &&
                std::isfinite(death_snapshot.max_hp) &&
                death_snapshot.max_hp > 0.0f) {
                valid_recent_death_count += 1;
            }
        }
    }
    constexpr std::uint32_t kWorldSnapshotRecentDeathReservedSlots = 16;
    const std::uint32_t reserved_recent_death_slots =
        run_scene
            ? (std::min<std::uint32_t>)(
                  valid_recent_death_count,
                  (std::min<std::uint32_t>)(kWorldSnapshotRecentDeathReservedSlots, kWorldSnapshotMaxActors))
            : 0;
    const std::uint32_t live_actor_snapshot_budget =
        kWorldSnapshotMaxActors > reserved_recent_death_slots
            ? kWorldSnapshotMaxActors - reserved_recent_death_slots
            : 0;
    std::unordered_set<std::uint64_t> included_actor_ids;
    std::uint32_t total_actor_count = 0;
    for (const auto& actor : actors) {
        if (!ShouldReplicateWorldActor(actor, scene_intent.kind)) {
            continue;
        }
        if (run_scene &&
            actor.tracked_enemy &&
            actor.dead &&
            HasRecentRunEnemyDeathSnapshotForActor(actor.actor_address)) {
            continue;
        }
        std::uint64_t network_actor_id = 0;
        if (run_scene) {
            std::uint32_t spawn_serial = 0;
            if (TryGetRunLifecycleEnemySpawnSerial(actor.actor_address, &spawn_serial)) {
                g_local_transport.run_host_local_world_actor_ids_by_address.erase(actor.actor_address);
                network_actor_id = BuildRunWorldActorNetworkId(spawn_serial);
            } else {
                network_actor_id = AllocateRunHostLocalWorldActorNetworkId(actor);
            }
        } else {
            network_actor_id = AllocateHubWorldActorNetworkId(actor);
        }
        if (network_actor_id == 0) {
            continue;
        }
        included_actor_ids.insert(network_actor_id);
        total_actor_count += 1;
        if (built.actor_count >= live_actor_snapshot_budget) {
            continue;
        }

        auto& snapshot = built.actors[built.actor_count];
        snapshot.network_actor_id = network_actor_id;
        snapshot.native_type_id = actor.object_type_id;
        snapshot.enemy_type = actor.enemy_type;
        snapshot.actor_slot = actor.actor_slot;
        snapshot.world_slot = actor.world_slot;
        snapshot.target_actor_slot = -1;
        snapshot.target_world_slot = -1;
        if (run_scene && actor.tracked_enemy) {
            snapshot.flags |= WorldActorSnapshotFlagTargetAuthoritative;
            snapshot.target_participant_id = ResolveRunEnemyTargetParticipantId(actor.actor_address);
            (void)PopulateRunEnemyNativeTargetSnapshot(actor.actor_address, &snapshot);
        }
        snapshot.anim_drive_state = actor.anim_drive_state;
        snapshot.position_x = actor.x;
        snapshot.position_y = actor.y;
        snapshot.radius = actor.radius;
        snapshot.heading = ReadActorHeadingOrZero(actor.actor_address);
        snapshot.hp = std::isfinite(actor.hp) ? actor.hp : 0.0f;
        snapshot.max_hp = std::isfinite(actor.max_hp) ? actor.max_hp : 0.0f;
        PopulateWorldActorPresentationSnapshot(
            actor.actor_address,
            actor.object_type_id,
            scene_intent.kind,
            actor.tracked_enemy,
            &snapshot);
        if (actor.dead) {
            snapshot.flags |= WorldActorSnapshotFlagDead;
        }
        if (actor.tracked_enemy) {
            snapshot.flags |= WorldActorSnapshotFlagTrackedEnemy;
        }
        if (run_scene && IsRunStaticLayoutActor(actor)) {
            snapshot.flags |= WorldActorSnapshotFlagRunStatic;
        }
        if (run_scene &&
            IsReplicatedRunPlayerCreatedActorType(actor.object_type_id)) {
            snapshot.flags |= WorldActorSnapshotFlagPlayerCreated;
        }
        if (run_scene) {
            snapshot.flags |= WorldActorSnapshotFlagLifecycleOwned;
        }
        built.actor_count += 1;
    }
    if (run_scene) {
        for (const auto& [network_actor_id, death_snapshot] :
             g_local_transport.recent_run_enemy_deaths_by_network_id) {
            if (network_actor_id == 0 ||
                included_actor_ids.find(network_actor_id) != included_actor_ids.end() ||
                death_snapshot.native_type_id == 0 ||
                !std::isfinite(death_snapshot.max_hp) ||
                death_snapshot.max_hp <= 0.0f) {
                continue;
            }
            total_actor_count += 1;
            if (built.actor_count >= kWorldSnapshotMaxActors) {
                continue;
            }

            auto& snapshot = built.actors[built.actor_count];
            snapshot.network_actor_id = network_actor_id;
            snapshot.native_type_id = death_snapshot.native_type_id;
            snapshot.enemy_type = death_snapshot.enemy_type;
            snapshot.actor_slot = -1;
            snapshot.world_slot = -1;
            snapshot.target_actor_slot = -1;
            snapshot.target_world_slot = -1;
            snapshot.flags =
                WorldActorSnapshotFlagDead |
                WorldActorSnapshotFlagTrackedEnemy |
                WorldActorSnapshotFlagLifecycleOwned;
            snapshot.position_x = death_snapshot.position_x;
            snapshot.position_y = death_snapshot.position_y;
            snapshot.radius = death_snapshot.radius;
            snapshot.heading = death_snapshot.heading;
            snapshot.hp = 0.0f;
            snapshot.max_hp = death_snapshot.max_hp;
            built.actor_count += 1;
        }
    }
    built.actor_total_count = static_cast<std::uint8_t>((std::min<std::uint32_t>)(total_actor_count, 0xFFu));
    if (total_actor_count > built.actor_count) {
        built.snapshot_flags |= WorldSnapshotFlagTruncated;
    }

    *packet = built;
    return true;
}

bool BuildLocalLootSnapshotPacket(LootSnapshotPacket* packet) {
    if (packet == nullptr || !g_local_transport.is_host) {
        return false;
    }

    SDModSceneState scene_state;
    if (!TryGetSceneState(&scene_state) || !scene_state.valid) {
        return false;
    }

    std::vector<SDModSceneActorState> actors;
    if (!TryListSceneActors(&actors)) {
        return false;
    }

    const auto scene_intent = SceneIntentFromLocalScene();
    if (scene_intent.kind != ParticipantSceneIntentKind::Run) {
        PruneRunLootDropNetworkIds(actors, scene_intent.kind);
        return false;
    }

    RefreshWorldSceneTracking(scene_state);
    PruneRunLootDropNetworkIds(actors, scene_intent.kind);

    LootSnapshotPacket built{};
    built.header = MakePacketHeader(PacketKind::LootSnapshot, g_local_transport.next_sequence++);
    built.authority_participant_id = g_local_transport.local_peer_id;
    built.scene_epoch = g_local_transport.world_scene_epoch;
    built.scene_kind = static_cast<std::uint8_t>(WorldSceneKindFromSceneIntent(scene_intent));

    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);
    if (local != nullptr) {
        built.run_nonce = local->runtime.run_nonce;
    }

    std::uint32_t total_drop_count = 0;
    for (const auto& actor : actors) {
        if (!ShouldReplicateLootDropActor(actor, scene_intent.kind)) {
            continue;
        }

        const auto network_drop_id = AllocateRunLootDropNetworkId(actor);
        if (network_drop_id == 0) {
            continue;
        }
        if (g_local_transport.accepted_loot_pickup_drop_ids.find(network_drop_id) !=
            g_local_transport.accepted_loot_pickup_drop_ids.end()) {
            continue;
        }

        LootDropSnapshotPacketState snapshot{};
        if (!TryPopulateLootDropSnapshot(actor, network_drop_id, &snapshot)) {
            continue;
        }
        if ((snapshot.flags & LootDropSnapshotFlagActive) == 0) {
            continue;
        }

        total_drop_count += 1;
        if (built.drop_count >= kLootSnapshotMaxDrops) {
            continue;
        }

        built.drops[built.drop_count] = snapshot;
        built.drop_count += 1;
    }

    built.drop_total_count = static_cast<std::uint8_t>((std::min<std::uint32_t>)(total_drop_count, 0xFFu));
    if (total_drop_count > built.drop_count) {
        built.snapshot_flags |= LootSnapshotFlagTruncated;
    }

    *packet = built;
    return true;
}

std::uint64_t LootSnapshotIntervalForPacket(const LootSnapshotPacket& packet) {
    for (std::size_t index = 0; index < packet.drop_count; ++index) {
        const auto& drop = packet.drops[index];
        const auto drop_kind = LootDropKindFromPacketValue(drop.drop_kind);
        const bool active = (drop.flags & LootDropSnapshotFlagActive) != 0;
        if (!active) {
            continue;
        }
        if (drop_kind == LootDropKind::Gold || drop_kind == LootDropKind::Orb) {
            return kLocalTransportAnimatedLootSnapshotIntervalMs;
        }
    }
    return kLocalTransportLootSnapshotIntervalMs;
}

float ClampEnemyHp(float hp, float max_hp) {
    if (!std::isfinite(hp)) {
        return 0.0f;
    }
    if (hp < 0.0f) {
        return 0.0f;
    }
    if (std::isfinite(max_hp) && max_hp > 0.0f && hp > max_hp) {
        return max_hp;
    }
    return hp;
}

float DistanceSquared(float ax, float ay, float bx, float by) {
    const float dx = ax - bx;
    const float dy = ay - by;
    return dx * dx + dy * dy;
}

bool TryWriteRunEnemyHealth(uintptr_t actor_address, float hp, float max_hp) {
    if (actor_address == 0 ||
        kEnemyCurrentHpOffset == 0 ||
        kEnemyMaxHpOffset == 0 ||
        !std::isfinite(max_hp) ||
        max_hp <= 0.0f) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const float clamped_hp = ClampEnemyHp(hp, max_hp);
    // Run enemies own health directly on their arena-actor object.  Do not
    // probe the wizard-only actor+0x200 progression seam here: on stock enemy
    // classes that field has unrelated meaning, and a readable pointer is not
    // proof that it names a progression object.  Writing HP through that
    // pointer corrupted native callbacks/heap metadata with values such as
    // 0x42200000 (40.0f) during clustered spell tests.
    return
        memory.TryWriteField(actor_address, kEnemyMaxHpOffset, max_hp) &&
        memory.TryWriteField(actor_address, kEnemyCurrentHpOffset, clamped_hp);
}
