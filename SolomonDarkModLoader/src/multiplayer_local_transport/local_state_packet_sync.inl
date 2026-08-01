#include "multiplayer_local_transport/local_profile_loadout_capture.inl"

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

    if (g_local_transport.host_level_up_barrier.active) {
        participant_ids.reserve(
            g_local_transport.host_level_up_barrier.participants.size());
        for (const auto& participant :
             g_local_transport.host_level_up_barrier.participants) {
            if (!participant.resolved && !participant.disconnected &&
                participant.participant_id != 0) {
                participant_ids.push_back(participant.participant_id);
            }
        }
        std::sort(participant_ids.begin(), participant_ids.end());
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

std::string BuildLevelUpWaitStatusTextFromIds(
    const std::vector<std::uint64_t>& participant_ids) {
    if (participant_ids.empty()) {
        return {};
    }
    return "Waiting on " + std::to_string(participant_ids.size()) +
           (participant_ids.size() == 1 ? " player" : " players");
}

LobbySessionState DetectLocalLobbySessionState(
    const SDModSceneState& scene_state,
    const SDModPlayerState& player_state,
    bool player_valid) {
    if (!player_valid ||
        player_state.actor_address == 0 ||
        !scene_state.valid ||
        scene_state.world_address == 0) {
        return LobbySessionState::NotInGame;
    }
    if (scene_state.kind == "hub" ||
        scene_state.name == "hub") {
        return LobbySessionState::InHub;
    }
    if (scene_state.kind == "arena" || scene_state.name == "testrun") {
        return IsRunLifecycleActive() &&
                g_run_game_over.accepted_epoch == 0
            ? LobbySessionState::InBoneyard
            : LobbySessionState::NotInGame;
    }
    return LobbySessionState::NotInGame;
}

void RefreshLocalParticipantFromGameState() {
    SDModSceneState scene_state;
    (void)TryGetSceneState(&scene_state);
    SDModPlayerState player_state;
    const bool have_player_state =
        TryGetPlayerState(&player_state) && player_state.valid;
    const auto lobby_session_state = DetectLocalLobbySessionState(
        scene_state,
        player_state,
        have_player_state);
    UpdateRuntimeState([&](RuntimeState& state) {
        state.lobby_session_state = lobby_session_state;
        if (lobby_session_state ==
            LobbySessionState::InHub) {
            state.run_end_pending_lobby_return = false;
        }
    });
    if (!have_player_state) {
        return;
    }

    SDModGameplaySelectionDebugState selection_state;
    const bool have_selection_state =
        TryGetGameplaySelectionDebugState(&selection_state) && selection_state.valid;
    auto scene_intent = SceneIntentFromLocalScene();
    if (scene_intent.kind ==
            ParticipantSceneIntentKind::Run &&
        !IsRunLifecycleActive()) {
        scene_intent = DefaultParticipantSceneIntent();
    }
    if (lobby_session_state == LobbySessionState::InHub) {
        g_local_run_exit_latched_nonce.store(0, std::memory_order_release);
        g_local_transport.client_host_run_exit_follow = ClientHostRunExitFollow{};
    }
    const auto configured_name = ReadLocalDisplayName();
    SDModWorldState world_state;
    const bool have_world_state = TryGetWorldState(&world_state) && world_state.valid;
    const auto wave_summary = SnapshotWaveSummary();
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
        local->runtime.damage_x4_remaining_ticks =
            player_state.damage_x4_remaining_ticks;
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
        if (have_inventory_state) {
            RefreshOwnedEquipmentFromSnapshot(inventory_state, &local->owned_progression);
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
        RefreshOwnedHagathaPerks(
            player_state.progression_address,
            &local->owned_progression);
        RefreshOwnedAbilityLoadoutFromProfile(local->character_profile.loadout, &local->owned_progression);
        if (have_world_state) {
            local->runtime.wave = world_state.wave;
        }
        if (local->runtime.in_run && wave_summary.valid) {
            local->runtime.wave = (std::max)(
                local->runtime.wave,
                wave_summary.wave);
        }
        local->runtime.position_x = player_state.x;
        local->runtime.position_y = player_state.y;
        local->runtime.heading = player_state.heading;
        local->runtime.movement_intent_x = player_state.movement_intent_x;
        local->runtime.movement_intent_y = player_state.movement_intent_y;
        local->runtime.anim_drive_state = player_state.anim_drive_state;
        local->runtime.presentation_flags =
            ParticipantPresentationFlagAnimationDriveWord |
            ParticipantPresentationFlagRenderDriveFloats;
        if (g_local_death_spectator.phase ==
            DeathSpectatorPhase::DeathPresentation) {
            local->runtime.presentation_flags |=
                ParticipantPresentationFlagDeathPresentation;
        } else {
            local->runtime.presentation_flags &=
                ~ParticipantPresentationFlagDeathPresentation;
        }
        local->runtime.death_presentation_tick =
            CurrentLocalDeathPresentationTick(
                static_cast<std::uint64_t>(::GetTickCount64()));
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
        std::uint32_t primary_visual_recipe_uid = 0;
        std::uint32_t secondary_visual_recipe_uid = 0;
        std::array<std::uint8_t, kParticipantVisualLinkColorBlockBytes> primary_visual_block = {};
        std::array<std::uint8_t, kParticipantVisualLinkColorBlockBytes> secondary_visual_block = {};
        if (TryReadVisualLinkColorBlock(
                player_state.primary_visual_lane,
                &primary_visual_type,
                &primary_visual_recipe_uid,
                &primary_visual_block) &&
            TryReadVisualLinkColorBlock(
                player_state.secondary_visual_lane,
                &secondary_visual_type,
                &secondary_visual_recipe_uid,
                &secondary_visual_block) &&
            player_state.attachment_visual_lane.holder_address != 0) {
            local->runtime.presentation_flags |=
                ParticipantPresentationFlagVisualLinkColorBlocks |
                ParticipantPresentationFlagEquipmentState;
            local->runtime.primary_visual_link_type_id = primary_visual_type;
            local->runtime.secondary_visual_link_type_id = secondary_visual_type;
            local->runtime.primary_visual_link_recipe_uid = primary_visual_recipe_uid;
            local->runtime.secondary_visual_link_recipe_uid = secondary_visual_recipe_uid;
            local->runtime.attachment_visual_link_type_id =
                player_state.attachment_visual_lane.current_object_type_id;
            local->runtime.attachment_visual_link_recipe_uid =
                player_state.attachment_visual_lane.current_object_recipe_uid;
            local->runtime.primary_visual_link_color_block = primary_visual_block;
            local->runtime.secondary_visual_link_color_block = secondary_visual_block;
        } else {
            local->runtime.primary_visual_link_type_id = 0;
            local->runtime.secondary_visual_link_type_id = 0;
            local->runtime.primary_visual_link_recipe_uid = 0;
            local->runtime.secondary_visual_link_recipe_uid = 0;
            local->runtime.attachment_visual_link_type_id = 0;
            local->runtime.attachment_visual_link_recipe_uid = 0;
            local->runtime.primary_visual_link_color_block = {};
            local->runtime.secondary_visual_link_color_block = {};
        }
        local->runtime.anim_drive_state_word = player_state.anim_drive_state_word;
        local->runtime.walk_cycle_primary = player_state.walk_cycle_primary;
        local->runtime.walk_cycle_secondary = player_state.walk_cycle_secondary;
        local->runtime.render_drive_stride = player_state.render_drive_stride;
        local->runtime.render_advance_rate = player_state.render_advance_rate;
        local->runtime.render_advance_phase = player_state.render_advance_phase;
        const auto shield_state = NormalizeMagicShieldState(
            player_state.magic_shield_absorb_remaining,
            player_state.magic_shield_absorb_capacity,
            player_state.magic_shield_explosion_fraction,
            player_state.magic_shield_hit_flash);
        local->runtime.magic_shield_absorb_remaining =
            shield_state.absorb_remaining;
        local->runtime.magic_shield_absorb_capacity =
            shield_state.absorb_capacity;
        local->runtime.magic_shield_explosion_fraction =
            shield_state.explosion_fraction;
        local->runtime.magic_shield_hit_flash = shield_state.hit_flash;
        local->runtime.render_drive_overlay_alpha = player_state.render_drive_overlay_alpha;
        local->runtime.render_drive_move_blend = player_state.render_drive_move_blend;
        if (state.run_end_pending_lobby_return &&
            state.last_terminated_run_nonce != 0) {
            ResetParticipantRuntimeForRunTermination(
                local);
            local->runtime.run_nonce =
                state.last_terminated_run_nonce;
        }
    });
}

template <typename Packet>
void PopulateParticipantFrameFields(
    const ParticipantInfo& participant,
    const RuntimeState& runtime_state,
    bool include_local_authority_state,
    Packet* packet) {
    if (packet == nullptr) {
        return;
    }

    packet->ready = participant.ready ? 1 : 0;
    packet->in_run = participant.runtime.in_run ? 1 : 0;
    packet->transform_valid = participant.runtime.transform_valid ? 1 : 0;
    packet->controller_kind =
        static_cast<std::uint8_t>(participant.controller_kind);
    packet->loadout_pick_state =
        static_cast<std::uint8_t>(participant.loadout_pick_state);
    packet->loadout_pick_generation =
        participant.loadout_pick_generation;
    packet->run_nonce = participant.runtime.run_nonce;
    if (include_local_authority_state) {
        ResetLocalHitFeedbackAcknowledgementForRun(
            participant.runtime.run_nonce);
        PopulateRunGameOverPacketFields(packet);
        PopulateRunLoadingBarrierPacketFields(packet);
        PopulateSharedGameplayPausePacketFields(runtime_state, packet);
        PopulateLuaTimeControlPacketFields(packet);
        packet->participant_vitals_correction_ack_sequence =
            g_local_transport.last_applied_participant_vitals_correction_sequence;
        packet->participant_hit_feedback_ack_sequence =
            g_local_transport.local_hit_feedback_ack_sequence;
    }
    packet->level = participant.runtime.level;
    packet->wave = participant.runtime.wave;
    packet->life_current = participant.runtime.life_current;
    packet->life_max = participant.runtime.life_max;
    packet->mana_current = participant.runtime.mana_current;
    packet->mana_max = participant.runtime.mana_max;
    packet->move_speed = participant.runtime.move_speed;
    packet->persistent_status_flags = participant.runtime.persistent_status_flags;
    packet->transient_status_flags = participant.runtime.transient_status_flags;
    packet->poison_remaining_ticks = participant.runtime.poison_remaining_ticks;
    packet->damage_x4_remaining_ticks =
        participant.runtime.damage_x4_remaining_ticks;
    packet->experience_current = participant.runtime.experience_current;
    packet->experience_next = participant.runtime.experience_next;
    packet->position_x = participant.runtime.position_x;
    packet->position_y = participant.runtime.position_y;
    packet->heading = participant.runtime.heading;
    packet->movement_intent_x = participant.runtime.movement_intent_x;
    packet->movement_intent_y = participant.runtime.movement_intent_y;
    packet->anim_drive_state = participant.runtime.anim_drive_state;
    packet->presentation_flags = participant.runtime.presentation_flags;
    packet->death_presentation_tick =
        participant.runtime.death_presentation_tick;
    if (include_local_authority_state) {
        packet->death_presentation_tick =
            CurrentLocalDeathPresentationTick(
                static_cast<std::uint64_t>(::GetTickCount64()));
        if (g_local_death_spectator.phase ==
            DeathSpectatorPhase::DeathPresentation) {
            packet->presentation_flags |=
                ParticipantPresentationFlagDeathPresentation;
        } else {
            packet->presentation_flags &=
                ~ParticipantPresentationFlagDeathPresentation;
        }
    }
    packet->attachment_staff_visual_state =
        participant.runtime.attachment_staff_visual_state;
    packet->render_variant_primary = participant.runtime.render_variant_primary;
    packet->render_variant_secondary = participant.runtime.render_variant_secondary;
    packet->render_weapon_type = participant.runtime.render_weapon_type;
    packet->render_selection_byte = participant.runtime.render_selection_byte;
    packet->render_variant_tertiary = participant.runtime.render_variant_tertiary;
    packet->primary_visual_link_type_id =
        participant.runtime.primary_visual_link_type_id;
    packet->secondary_visual_link_type_id =
        participant.runtime.secondary_visual_link_type_id;
    packet->primary_visual_link_recipe_uid =
        participant.runtime.primary_visual_link_recipe_uid;
    packet->secondary_visual_link_recipe_uid =
        participant.runtime.secondary_visual_link_recipe_uid;
    packet->attachment_visual_link_type_id =
        participant.runtime.attachment_visual_link_type_id;
    packet->attachment_visual_link_recipe_uid =
        participant.runtime.attachment_visual_link_recipe_uid;
    std::memcpy(
        packet->primary_visual_link_color_block,
        participant.runtime.primary_visual_link_color_block.data(),
        participant.runtime.primary_visual_link_color_block.size());
    std::memcpy(
        packet->secondary_visual_link_color_block,
        participant.runtime.secondary_visual_link_color_block.data(),
        participant.runtime.secondary_visual_link_color_block.size());
    packet->anim_drive_state_word = participant.runtime.anim_drive_state_word;
    packet->walk_cycle_primary = participant.runtime.walk_cycle_primary;
    packet->walk_cycle_secondary = participant.runtime.walk_cycle_secondary;
    packet->render_drive_stride = participant.runtime.render_drive_stride;
    packet->render_advance_rate = participant.runtime.render_advance_rate;
    packet->render_advance_phase = participant.runtime.render_advance_phase;
    packet->magic_shield_absorb_remaining =
        participant.runtime.magic_shield_absorb_remaining;
    packet->magic_shield_absorb_capacity =
        participant.runtime.magic_shield_absorb_capacity;
    packet->magic_shield_explosion_fraction =
        participant.runtime.magic_shield_explosion_fraction;
    packet->magic_shield_hit_flash =
        participant.runtime.magic_shield_hit_flash;
    packet->render_drive_overlay_alpha =
        participant.runtime.render_drive_overlay_alpha;
    packet->render_drive_move_blend =
        participant.runtime.render_drive_move_blend;
}

template <typename Packet>
void ApplyLocalRunExitLatch(Packet* packet) {
    if (packet == nullptr || !g_local_transport.is_host) {
        return;
    }
    const auto run_exit_nonce =
        g_local_run_exit_latched_nonce.load(std::memory_order_acquire);
    if (run_exit_nonce == 0) {
        return;
    }
    packet->in_run = 0;
    packet->transform_valid = 0;
    packet->run_nonce = run_exit_nonce;
}

ParticipantFramePacket BuildLocalParticipantFramePacket() {
    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);

    ParticipantFramePacket packet{};
    packet.header = MakePacketHeader(
        PacketKind::ParticipantFrame,
        g_local_transport.next_sequence++);
    packet.participant_id = g_local_transport.local_peer_id;
    packet.participant_session_nonce = g_local_transport.local_session_nonce;
    packet.authority_participant_id =
        g_local_transport.is_host ? g_local_transport.local_peer_id : 0;
    if (local == nullptr) {
        return packet;
    }

    PopulateParticipantFrameFields(*local, runtime_state, true, &packet);
    packet.scene_kind = static_cast<std::uint8_t>(
        WorldSceneKindFromSceneIntent(local->runtime.scene_intent));
    packet.region_index = local->runtime.scene_intent.region_index;
    packet.region_type_id = local->runtime.scene_intent.region_type_id;
    PopulateAuthorityWaveRespawn(&packet);
    ApplyLocalRunExitLatch(&packet);
    return packet;
}

void PopulateParticipantStateFields(
    const ParticipantInfo& participant,
    StatePacket* packet) {
    if (packet == nullptr) {
        return;
    }

    CopyPacketDisplayName(participant.name, packet);
    packet->element_id = participant.character_profile.element_id;
    packet->discipline_id =
        static_cast<std::int32_t>(
            participant.character_profile.discipline_id);
    for (std::size_t index = 0;
         index < participant.character_profile.appearance.choice_ids.size();
         ++index) {
        packet->appearance_choice_ids[index] =
            participant.character_profile.appearance.choice_ids[index];
    }
    packet->owned_gold = participant.owned_progression.gold;
    packet->gold_revision = participant.owned_progression.gold_revision;
    packet->inventory_revision =
        participant.owned_progression.inventory_revision;
    packet->equipment_revision =
        participant.owned_progression.equipment_revision;
    packet->equipment_valid =
        participant.owned_progression.equipment.valid ? 1 : 0;
    const auto copy_equipped_item = [](
        const ParticipantEquippedItemState& source,
        ParticipantEquippedItemPacketState* destination) {
        destination->type_id = source.type_id;
        destination->recipe_uid = source.recipe_uid;
    };
    copy_equipped_item(
        participant.owned_progression.equipment.hat,
        &packet->equipped_hat);
    copy_equipped_item(
        participant.owned_progression.equipment.robe,
        &packet->equipped_robe);
    copy_equipped_item(
        participant.owned_progression.equipment.weapon,
        &packet->equipped_weapon);
    for (std::size_t index = 0;
         index < participant.owned_progression.equipment.rings.size();
         ++index) {
        copy_equipped_item(
            participant.owned_progression.equipment.rings[index],
            &packet->equipped_rings[index]);
    }
    copy_equipped_item(
        participant.owned_progression.equipment.amulet,
        &packet->equipped_amulet);
    packet->spellbook_revision =
        participant.owned_progression.spellbook_revision;
    packet->statbook_revision =
        participant.owned_progression.statbook_revision;
    packet->loadout_revision =
        participant.owned_progression.loadout_revision;
    packet->concentration_revision =
        participant.owned_progression.concentration_revision;
    packet->concentration_selection_valid =
        participant.owned_progression.concentration_selection_valid ? 1 : 0;
    packet->concentration_entry_a =
        participant.owned_progression.concentration_entry_a;
    packet->concentration_entry_b =
        participant.owned_progression.concentration_entry_b;
    BuildDerivedStatPacketState(
        participant.owned_progression,
        &packet->derived_stat_revision,
        &packet->derived_stats);
    BuildHagathaPerkPacketState(
        participant.owned_progression,
        &packet->hagatha_perk_revision,
        &packet->hagatha_perks);
    packet->primary_entry_index =
        participant.character_profile.loadout.primary_entry_index;
    packet->primary_combo_entry_index =
        participant.character_profile.loadout.primary_combo_entry_index;
    for (std::size_t index = 0;
         index <
             participant.character_profile.loadout.secondary_entry_indices.size();
         ++index) {
        packet->queued_secondary_entry_indices[index] =
            participant.character_profile.loadout.secondary_entry_indices[index];
    }
}

StatePacket BuildLocalStatePacket() {
    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);

    StatePacket packet{};
    packet.header = MakePacketHeader(PacketKind::State, g_local_transport.next_sequence++);
    packet.participant_id = g_local_transport.local_peer_id;
    packet.participant_session_nonce = g_local_transport.local_session_nonce;
    packet.authority_participant_id =
        g_local_transport.is_host ? g_local_transport.local_peer_id : 0;
    if (local == nullptr) {
        return packet;
    }

    PopulateParticipantFrameFields(*local, runtime_state, true, &packet);
    PopulateParticipantStateFields(*local, &packet);
    PopulateAuthorityWaveRespawn(&packet);
    ApplyLocalRunExitLatch(&packet);
    return packet;
}

#include "multiplayer_local_transport/synthetic_participant_state_sync.inl"
