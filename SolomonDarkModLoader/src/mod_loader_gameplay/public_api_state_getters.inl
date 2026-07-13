bool TryGetParticipantGameplayState(
    std::uint64_t participant_id,
    SDModParticipantGameplayState* state) {
    if (state == nullptr) {
        return false;
    }

    *state = SDModParticipantGameplayState{};
    std::lock_guard<std::mutex> lock(g_wizard_bot_snapshot_mutex);
    const auto it = std::find_if(
        g_participant_gameplay_snapshots.begin(),
        g_participant_gameplay_snapshots.end(),
        [&](const ParticipantGameplaySnapshot& snapshot) {
            return snapshot.bot_id == participant_id;
        });
    if (it == g_participant_gameplay_snapshots.end()) {
        return false;
    }

    state->available = true;
    state->entity_materialized = it->entity_materialized;
    state->moving = it->moving;
    state->entity_kind = it->entity_kind;
    state->movement_intent_revision = it->movement_intent_revision;
    state->participant_id = it->bot_id;
    state->character_profile = it->character_profile;
    state->scene_intent = it->scene_intent;
    state->actor_address = it->actor_address;
    state->world_address = it->world_address;
    state->animation_state_ptr = it->animation_state_ptr;
    state->render_frame_table = it->render_frame_table;
    state->hub_visual_attachment_ptr = it->hub_visual_attachment_ptr;
    state->hub_visual_source_profile_address = it->hub_visual_source_profile_address;
    state->hub_visual_descriptor_signature = it->hub_visual_descriptor_signature;
    state->hub_visual_proxy_address = it->hub_visual_proxy_address;
    state->progression_handle_address = it->progression_handle_address;
    state->equip_handle_address = it->equip_handle_address;
    state->progression_runtime_state_address = it->progression_runtime_state_address;
    state->equip_runtime_state_address = it->equip_runtime_state_address;
    state->gameplay_slot = it->gameplay_slot;
    state->actor_slot = it->actor_slot;
    state->slot_anim_state_index = it->slot_anim_state_index;
    state->resolved_animation_state_id = it->resolved_animation_state_id;
    state->hub_visual_source_kind = it->hub_visual_source_kind;
    state->render_drive_flags = it->render_drive_flags;
    state->anim_drive_state = it->anim_drive_state;
    state->no_interrupt = it->no_interrupt;
    state->active_cast_group = it->active_cast_group;
    state->active_cast_slot = it->active_cast_slot;
    state->render_variant_primary = it->render_variant_primary;
    state->render_variant_secondary = it->render_variant_secondary;
    state->render_weapon_type = it->render_weapon_type;
    state->render_selection_byte = it->render_selection_byte;
    state->render_variant_tertiary = it->render_variant_tertiary;
    state->cast_active = it->cast_active;
    state->cast_startup_in_progress = it->cast_startup_in_progress;
    state->cast_saw_activity = it->cast_saw_activity;
    state->cast_skill_id = it->cast_skill_id;
    state->cast_ticks_waiting = it->cast_ticks_waiting;
    state->cast_target_actor_address = it->cast_target_actor_address;
    state->native_action_cooldown_ticks = it->native_action_cooldown_ticks;
    state->active_spell_object_readable = it->active_spell_object_readable;
    state->active_spell_object_address = it->active_spell_object_address;
    state->active_spell_object_type = it->active_spell_object_type;
    state->active_spell_object_x = it->active_spell_object_x;
    state->active_spell_object_y = it->active_spell_object_y;
    state->active_spell_object_radius = it->active_spell_object_radius;
    state->active_spell_object_charge = it->active_spell_object_charge;
    state->x = it->x;
    state->y = it->y;
    state->heading = it->heading;
    state->hp = it->hp;
    state->max_hp = it->max_hp;
    state->mp = it->mp;
    state->max_mp = it->max_mp;
    state->walk_cycle_primary = it->walk_cycle_primary;
    state->walk_cycle_secondary = it->walk_cycle_secondary;
    state->render_drive_stride = it->render_drive_stride;
    state->render_advance_rate = it->render_advance_rate;
    state->render_advance_phase = it->render_advance_phase;
    state->render_drive_effect_timer = it->render_drive_effect_timer;
    state->render_drive_effect_progress = it->render_drive_effect_progress;
    state->render_drive_overlay_alpha = it->render_drive_overlay_alpha;
    state->render_drive_move_blend = it->render_drive_move_blend;
    state->gameplay_attach_applied = it->gameplay_attach_applied;
    state->primary_visual_lane = it->primary_visual_lane;
    state->secondary_visual_lane = it->secondary_visual_lane;
    state->attachment_visual_lane = it->attachment_visual_lane;
    (void)TryReadWizardActorPersistentStatusFlags(
        state->actor_address,
        &state->native_persistent_status_flags);
    (void)TryReadWizardActorTransientStatusState(
        state->actor_address,
        &state->native_transient_status_flags,
        &state->native_poison_remaining_ticks);
    return true;
}

bool TryListRecentNativeSpellEffectActors(
    std::vector<SDModNativeSpellEffectActorState>* actors) {
    if (actors == nullptr) {
        return false;
    }
    actors->clear();

    constexpr std::uint64_t kRecentNativeSpellEffectHoldMs = 3000;
    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    std::vector<SDModNativeSpellEffectActorState> recent;
    {
        std::lock_guard<std::mutex> lock(g_native_spell_effect_actor_mutex);
        g_recent_native_spell_effect_actors.erase(
            std::remove_if(
                g_recent_native_spell_effect_actors.begin(),
                g_recent_native_spell_effect_actors.end(),
                [&](const SDModNativeSpellEffectActorState& actor) {
                    return actor.actor_address == 0 ||
                           now_ms < actor.created_ms ||
                           now_ms - actor.created_ms >
                               kRecentNativeSpellEffectHoldMs;
                }),
            g_recent_native_spell_effect_actors.end());
        recent = g_recent_native_spell_effect_actors;
    }

    auto& memory = ProcessMemory::Instance();
    actors->reserve(recent.size());
    for (auto actor : recent) {
        std::uint32_t live_type_id = 0;
        std::int8_t actor_slot = -1;
        if (!memory.TryReadField(
                actor.actor_address,
                kRegionObjectTypeIdOffset,
                &live_type_id) ||
            live_type_id != actor.native_type_id ||
            !memory.TryReadField(
                actor.actor_address,
                kActorSlotOffset,
                &actor_slot) ||
            !TryReadFiniteFloatField(
                actor.actor_address,
                kActorPositionXOffset,
                &actor.x) ||
            !TryReadFiniteFloatField(
                actor.actor_address,
                kActorPositionYOffset,
                &actor.y) ||
            !TryReadFiniteFloatField(
                actor.actor_address,
                kActorCollisionRadiusOffset,
                &actor.radius) ||
            actor.radius < 0.0f) {
            continue;
        }
        actor.valid = true;
        actor.actor_slot = static_cast<int>(actor_slot);
        actors->push_back(actor);
    }
    return true;
}

bool TryRefreshParticipantGameplayState(
    std::uint64_t participant_id,
    SDModParticipantGameplayState* state) {
    auto* binding = FindParticipantEntity(participant_id);
    if (binding == nullptr || binding->actor_address == 0) {
        return TryGetParticipantGameplayState(participant_id, state);
    }

    PublishParticipantGameplaySnapshot(*binding);
    return TryGetParticipantGameplayState(participant_id, state);
}

bool TryGetGameplayHudParticipantDisplayNameForActor(
    uintptr_t active_actor_address,
    std::string* display_name,
    std::uint64_t* participant_id) {
    if (display_name != nullptr) {
        display_name->clear();
    }
    if (participant_id != nullptr) {
        *participant_id = 0;
    }
    if (active_actor_address == 0) {
        return false;
    }

    std::uint64_t resolved_participant_id = 0;
    {
        std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
        const auto* binding = FindParticipantEntityForActor(active_actor_address);
        if (binding == nullptr || !IsWizardParticipantKind(binding->kind)) {
            return false;
        }

        resolved_participant_id = binding->bot_id;
    }

    const auto runtime = multiplayer::SnapshotRuntimeState();
    const auto* participant = multiplayer::FindParticipant(runtime, resolved_participant_id);
    if (participant == nullptr ||
        !multiplayer::IsRemoteParticipant(*participant) ||
        participant->name.empty()) {
        return false;
    }

    if (display_name != nullptr) {
        *display_name = participant->name;
    }
    if (participant_id != nullptr) {
        *participant_id = resolved_participant_id;
    }
    return true;
}

bool TryGetPlayerState(SDModPlayerState* state) {
    if (state == nullptr) {
        return false;
    }

    *state = SDModPlayerState{};
    uintptr_t gameplay_address = 0;
    uintptr_t actor_address = 0;
    uintptr_t progression_address = 0;
    uintptr_t world_address = 0;
    const bool resolved_gameplay_address =
        TryResolveCurrentGameplayScene(&gameplay_address) && gameplay_address != 0;
    if (!resolved_gameplay_address ||
        !TryResolveLocalPlayerWorldContext(
            gameplay_address,
            &actor_address,
            &progression_address,
            &world_address) ||
        actor_address == 0 ||
        progression_address == 0 ||
        world_address == 0) {
        return false;
    }

    int gold = 0;
    if (!TryReadResolvedGlobalInt(kGoldGlobal, &gold)) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    float hp = 0.0f;
    float max_hp = 0.0f;
    float mp = 0.0f;
    float max_mp = 0.0f;
    float move_speed = 0.0f;
    int xp = 0;
    int level = 0;
    float x = 0.0f;
    float y = 0.0f;
    float heading = 0.0f;
    if (!TryReadFiniteFloatField(progression_address, kProgressionHpOffset, &hp) ||
        !TryReadFiniteFloatField(progression_address, kProgressionMaxHpOffset, &max_hp) ||
        !TryReadFiniteFloatField(progression_address, kProgressionMpOffset, &mp) ||
        !TryReadFiniteFloatField(progression_address, kProgressionMaxMpOffset, &max_mp) ||
        !TryReadFiniteFloatField(progression_address, kProgressionMoveSpeedOffset, &move_speed) ||
        !TryReadPlayerRoundedXp(progression_address, &xp) ||
        !memory.TryReadField(progression_address, kProgressionLevelOffset, &level) ||
        !TryReadFiniteFloatField(actor_address, kActorPositionXOffset, &x) ||
        !TryReadFiniteFloatField(actor_address, kActorPositionYOffset, &y) ||
        !TryReadFiniteFloatField(actor_address, kActorHeadingOffset, &heading)) {
        return false;
    }

    state->valid = true;
    state->hp = hp;
    state->max_hp = max_hp;
    state->mp = mp;
    state->max_mp = max_mp;
    state->move_speed = move_speed;
    auto& derived = state->derived_stats;
    derived.valid =
        kProgressionCastSpeedMultiplierOffset != 0 &&
        kProgressionManaRecoveryMultiplierOffset != 0 &&
        kProgressionResistMagicFractionOffset != 0 &&
        kProgressionResistPoisonFractionOffset != 0 &&
        kProgressionDeflectChanceOffset != 0 &&
        kProgressionStaffMeleeDamageAOffset != 0 &&
        kProgressionStaffMeleeDamageBOffset != 0 &&
        kProgressionPickupRangeOffset != 0 &&
        kProgressionSecondaryRechargeMultiplierOffset != 0 &&
        kProgressionOffensiveDamageMultiplierOffset != 0 &&
        kProgressionOffensiveManaMultiplierOffset != 0 &&
        kProgressionMeditationRecoveryBonusOffset != 0 &&
        kProgressionMeditationIdleTicksOffset != 0 &&
        TryReadFiniteFloatField(
            progression_address,
            kProgressionCastSpeedMultiplierOffset,
            &derived.cast_speed_multiplier) &&
        TryReadFiniteFloatField(
            progression_address,
            kProgressionManaRecoveryMultiplierOffset,
            &derived.mana_recovery_multiplier) &&
        TryReadFiniteFloatField(
            progression_address,
            kProgressionResistMagicFractionOffset,
            &derived.resist_magic_fraction) &&
        TryReadFiniteFloatField(
            progression_address,
            kProgressionResistPoisonFractionOffset,
            &derived.resist_poison_fraction) &&
        TryReadFiniteFloatField(
            progression_address,
            kProgressionDeflectChanceOffset,
            &derived.deflect_chance) &&
        TryReadFiniteFloatField(
            progression_address,
            kProgressionStaffMeleeDamageAOffset,
            &derived.staff_melee_damage_a) &&
        TryReadFiniteFloatField(
            progression_address,
            kProgressionStaffMeleeDamageBOffset,
            &derived.staff_melee_damage_b) &&
        TryReadFiniteFloatField(
            progression_address,
            kProgressionPickupRangeOffset,
            &derived.pickup_range) &&
        TryReadFiniteFloatField(
            progression_address,
            kProgressionSecondaryRechargeMultiplierOffset,
            &derived.secondary_recharge_multiplier) &&
        TryReadFiniteFloatField(
            progression_address,
            kProgressionOffensiveDamageMultiplierOffset,
            &derived.offensive_damage_multiplier) &&
        TryReadFiniteFloatField(
            progression_address,
            kProgressionOffensiveManaMultiplierOffset,
            &derived.offensive_mana_multiplier) &&
        TryReadFiniteFloatField(
            progression_address,
            kProgressionMeditationRecoveryBonusOffset,
            &derived.meditation_recovery_bonus) &&
        memory.TryReadField(
            progression_address,
            kProgressionMeditationIdleTicksOffset,
            &derived.meditation_idle_ticks);
    state->xp = xp;
    state->level = level;
    state->x = x;
    state->y = y;
    state->heading = heading;
    state->gold = gold;
    state->actor_address = actor_address;
    (void)TryReadWizardActorPersistentStatusFlags(
        actor_address,
        &state->persistent_status_flags);
    (void)TryReadWizardActorTransientStatusState(
        actor_address,
        &state->transient_status_flags,
        &state->poison_remaining_ticks);
    state->render_subject_address = actor_address;
    state->world_address = world_address;
    state->progression_address = progression_address;
    (void)memory.TryReadField(actor_address, kActorAnimationSelectionStateOffset, &state->animation_state_ptr);
    (void)memory.TryReadField(actor_address, kActorRenderFrameTableOffset, &state->render_frame_table);
    (void)memory.TryReadField(actor_address, kActorHubVisualAttachmentPtrOffset, &state->hub_visual_attachment_ptr);
    (void)memory.TryReadField(
        actor_address,
        kActorHubVisualSourceProfileOffset,
        &state->hub_visual_source_profile_address);
    state->hub_visual_descriptor_signature = HashMemoryBlockFNV1a32(
        actor_address + kActorHubVisualDescriptorBlockOffset,
        kActorHubVisualDescriptorBlockSize);
    (void)memory.TryReadField(actor_address, kActorProgressionHandleOffset, &state->progression_handle_address);
    (void)memory.TryReadField(actor_address, kActorEquipHandleOffset, &state->equip_handle_address);
    (void)memory.TryReadField(actor_address, kActorEquipRuntimeStateOffset, &state->equip_runtime_state_address);
    std::int8_t actor_slot = -1;
    if (memory.TryReadField(actor_address, kActorSlotOffset, &actor_slot)) {
        state->actor_slot = static_cast<int>(actor_slot);
    }
    state->resolved_animation_state_id = ResolveActorAnimationStateId(actor_address);
    (void)memory.TryReadField(actor_address, kActorHubVisualSourceKindOffset, &state->hub_visual_source_kind);
    (void)memory.TryReadField(actor_address, kActorRenderDriveFlagsOffset, &state->render_drive_flags);
    (void)memory.TryReadField(actor_address, kActorAnimationDriveStateByteOffset, &state->anim_drive_state);
    (void)memory.TryReadField(actor_address, kActorAnimationDriveStateByteOffset, &state->anim_drive_state_word);
    (void)memory.TryReadField(actor_address, kActorRenderVariantPrimaryOffset, &state->render_variant_primary);
    (void)memory.TryReadField(actor_address, kActorRenderVariantSecondaryOffset, &state->render_variant_secondary);
    (void)memory.TryReadField(actor_address, kActorRenderWeaponTypeOffset, &state->render_weapon_type);
    (void)memory.TryReadField(actor_address, kActorRenderSelectionByteOffset, &state->render_selection_byte);
    (void)memory.TryReadField(actor_address, kActorRenderVariantTertiaryOffset, &state->render_variant_tertiary);
    (void)TryReadFiniteFloatField(actor_address, kActorWalkCyclePrimaryOffset, &state->walk_cycle_primary);
    (void)TryReadFiniteFloatField(actor_address, kActorWalkCycleSecondaryOffset, &state->walk_cycle_secondary);
    (void)TryReadFiniteFloatField(actor_address, kActorRenderDriveStrideScaleOffset, &state->render_drive_stride);
    (void)TryReadFiniteFloatField(actor_address, kActorRenderAdvanceRateOffset, &state->render_advance_rate);
    (void)TryReadFiniteFloatField(actor_address, kActorRenderAdvancePhaseOffset, &state->render_advance_phase);
    (void)TryReadFiniteFloatField(actor_address, kActorRenderDriveEffectTimerOffset, &state->render_drive_effect_timer);
    (void)TryReadFiniteFloatField(actor_address, kActorRenderDriveEffectProgressOffset, &state->render_drive_effect_progress);
    (void)TryReadFiniteFloatField(actor_address, kActorRenderDriveOverlayAlphaOffset, &state->render_drive_overlay_alpha);
    (void)TryReadFiniteFloatField(actor_address, kActorRenderDriveMoveBlendOffset, &state->render_drive_move_blend);
    if (resolved_gameplay_address) {
        state->primary_visual_lane =
            ReadEquipVisualLaneState(gameplay_address, kGameplayVisualSinkPrimaryOffset);
        state->secondary_visual_lane =
            ReadEquipVisualLaneState(gameplay_address, kGameplayVisualSinkSecondaryOffset);
        state->attachment_visual_lane =
            ReadEquipVisualLaneState(gameplay_address, kGameplayVisualSinkAttachmentOffset);
    }

    const auto render_subject_address = state->render_subject_address;
    (void)memory.TryReadField(
        render_subject_address,
        kActorAnimationSelectionStateOffset,
        &state->render_subject_animation_state_ptr);
    (void)memory.TryReadField(render_subject_address, kActorRenderFrameTableOffset, &state->render_subject_frame_table);
    (void)memory.TryReadField(
        render_subject_address,
        kActorHubVisualAttachmentPtrOffset,
        &state->render_subject_hub_visual_attachment_ptr);
    (void)memory.TryReadField(
        render_subject_address,
        kActorHubVisualSourceProfileOffset,
        &state->render_subject_hub_visual_source_profile_address);
    state->render_subject_hub_visual_descriptor_signature = HashMemoryBlockFNV1a32(
        render_subject_address + kActorHubVisualDescriptorBlockOffset,
        kActorHubVisualDescriptorBlockSize);
    (void)memory.TryReadField(
        render_subject_address,
        kActorHubVisualSourceKindOffset,
        &state->render_subject_hub_visual_source_kind);
    (void)memory.TryReadField(render_subject_address, kActorRenderDriveFlagsOffset, &state->render_subject_drive_flags);
    (void)memory.TryReadField(render_subject_address, kActorAnimationDriveStateByteOffset, &state->render_subject_anim_drive_state);
    (void)memory.TryReadField(render_subject_address, kActorRenderVariantPrimaryOffset, &state->render_subject_variant_primary);
    (void)memory.TryReadField(render_subject_address, kActorRenderVariantSecondaryOffset, &state->render_subject_variant_secondary);
    (void)memory.TryReadField(render_subject_address, kActorRenderWeaponTypeOffset, &state->render_subject_weapon_type);
    (void)memory.TryReadField(render_subject_address, kActorRenderSelectionByteOffset, &state->render_subject_selection_byte);
    (void)memory.TryReadField(render_subject_address, kActorRenderVariantTertiaryOffset, &state->render_subject_variant_tertiary);
    state->gameplay_attach_applied = true;
    return true;
}

bool TryGetPlayerInventoryState(SDModInventoryState* state) {
    if (state == nullptr) {
        return false;
    }

    *state = SDModInventoryState{};
    uintptr_t gameplay_address = 0;
    if (!TryResolveCurrentGameplayScene(&gameplay_address) || gameplay_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const uintptr_t item_list_root = gameplay_address + kGameplayItemListRootOffset;
    int item_count = 0;
    uintptr_t item_array_address = 0;
    if (!memory.IsReadableRange(item_list_root, kGameplayItemListItemsOffset + sizeof(uintptr_t)) ||
        !memory.TryReadField(item_list_root, kGameplayItemListCountOffset, &item_count) ||
        !memory.TryReadField(item_list_root, kGameplayItemListItemsOffset, &item_array_address) ||
        item_count < 0 ||
        item_count > 4096) {
        return false;
    }

    state->valid = true;
    state->gameplay_scene_address = gameplay_address;
    state->item_list_root_address = item_list_root;
    state->item_array_address = item_array_address;
    state->item_count = item_count;
    state->primary_visual_lane =
        ReadEquipVisualLaneState(gameplay_address, kGameplayVisualSinkPrimaryOffset);
    state->secondary_visual_lane =
        ReadEquipVisualLaneState(gameplay_address, kGameplayVisualSinkSecondaryOffset);
    state->attachment_visual_lane =
        ReadEquipVisualLaneState(gameplay_address, kGameplayVisualSinkAttachmentOffset);

    if (item_count == 0) {
        return true;
    }
    if (item_array_address == 0) {
        return false;
    }

    const int enumerate_count =
        item_count > static_cast<int>(kSDModInventorySnapshotMaxItems)
            ? static_cast<int>(kSDModInventorySnapshotMaxItems)
            : item_count;
    state->truncated = item_count > enumerate_count;
    if (!memory.IsReadableRange(
            item_array_address,
            static_cast<std::size_t>(enumerate_count) * sizeof(std::uint32_t))) {
        return false;
    }

    state->items.reserve(static_cast<std::size_t>(enumerate_count));
    constexpr std::uint32_t kPotionItemTypeId = 0x1B59;
    for (int index = 0; index < enumerate_count; ++index) {
        std::uint32_t raw_item_address = 0;
        if (!memory.TryReadValue(
                item_array_address + static_cast<std::size_t>(index) * sizeof(std::uint32_t),
                &raw_item_address) ||
            raw_item_address == 0) {
            continue;
        }

        const uintptr_t item_address = static_cast<uintptr_t>(raw_item_address);
        if (!memory.IsReadableRange(item_address, kItemSlotOffset + sizeof(int))) {
            continue;
        }

        SDModInventoryItemState item{};
        item.item_address = item_address;
        if (!memory.TryReadField(item_address, kGameObjectTypeIdOffset, &item.type_id)) {
            continue;
        }
        item.valid = true;
        (void)memory.TryReadField(item_address, kItemSlotOffset, &item.slot);
        if (item.type_id == kPotionItemTypeId &&
            memory.IsReadableRange(item_address + kPotionStackCountOffset, sizeof(int))) {
            (void)memory.TryReadField(item_address, kPotionStackCountOffset, &item.stack_count);
        }
        state->items.push_back(item);
    }
    state->enumerated_item_count = static_cast<int>(state->items.size());
    return true;
}

bool TryGetPlayerProgressionBookState(SDModProgressionBookState* state) {
    if (state == nullptr) {
        return false;
    }

    *state = SDModProgressionBookState{};

    SDModPlayerState player_state;
    if (!TryGetPlayerState(&player_state) ||
        !player_state.valid ||
        player_state.progression_address == 0 ||
        kStandaloneWizardProgressionTableBaseOffset == 0 ||
        kStandaloneWizardProgressionTableCountOffset == 0 ||
        kStandaloneWizardProgressionEntryStride == 0 ||
        kStandaloneWizardProgressionEntryInternalIdOffset == 0 ||
        kStandaloneWizardProgressionActiveFlagOffset == 0 ||
        kStandaloneWizardProgressionVisibleFlagOffset == 0 ||
        kStandaloneWizardProgressionEntryCategoryOffset == 0 ||
        kStandaloneWizardProgressionEntryStatbookOffset == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t entry_table_address = 0;
    int entry_count = 0;
    if (!memory.IsReadableRange(
            player_state.progression_address + kStandaloneWizardProgressionTableBaseOffset,
            sizeof(uintptr_t)) ||
        !memory.IsReadableRange(
            player_state.progression_address + kStandaloneWizardProgressionTableCountOffset,
            sizeof(int)) ||
        !memory.TryReadField(
            player_state.progression_address,
            kStandaloneWizardProgressionTableBaseOffset,
            &entry_table_address) ||
        !memory.TryReadField(
            player_state.progression_address,
            kStandaloneWizardProgressionTableCountOffset,
            &entry_count) ||
        entry_table_address == 0 ||
        entry_count < 0 ||
        entry_count > 4096) {
        return false;
    }

    state->valid = true;
    state->progression_address = player_state.progression_address;
    state->entry_table_address = entry_table_address;
    state->entry_count = entry_count;

    const int enumerate_count =
        entry_count > static_cast<int>(kSDModProgressionBookSnapshotMaxEntries)
            ? static_cast<int>(kSDModProgressionBookSnapshotMaxEntries)
            : entry_count;
    state->truncated = entry_count > enumerate_count;
    state->entries.reserve(static_cast<std::size_t>(enumerate_count));

    const auto minimum_entry_size = (std::max)(
        (std::max)(
            kStandaloneWizardProgressionEntryInternalIdOffset + sizeof(int),
            kStandaloneWizardProgressionActiveFlagOffset + sizeof(std::uint16_t)),
        (std::max)(
            kStandaloneWizardProgressionVisibleFlagOffset + sizeof(std::uint16_t),
            (std::max)(
                kStandaloneWizardProgressionEntryCategoryOffset + sizeof(std::uint16_t),
                kStandaloneWizardProgressionEntryStatbookOffset + sizeof(uintptr_t))));
    if (kStandaloneWizardProgressionEntryStride < minimum_entry_size) {
        return false;
    }

    for (int index = 0; index < enumerate_count; ++index) {
        const uintptr_t entry_address =
            entry_table_address + static_cast<std::size_t>(index) * kStandaloneWizardProgressionEntryStride;
        if (!memory.IsReadableRange(entry_address, minimum_entry_size)) {
            continue;
        }

        SDModProgressionBookEntryState entry{};
        entry.valid = true;
        entry.entry_address = entry_address;
        entry.entry_index = index;
        if (!memory.TryReadField(
                entry_address,
                kStandaloneWizardProgressionEntryInternalIdOffset,
                &entry.internal_id) ||
            !memory.TryReadField(
                entry_address,
                kStandaloneWizardProgressionActiveFlagOffset,
                &entry.active) ||
            !memory.TryReadField(
                entry_address,
                kStandaloneWizardProgressionVisibleFlagOffset,
                &entry.visible) ||
            !memory.TryReadField(
                entry_address,
                kStandaloneWizardProgressionEntryCategoryOffset,
                &entry.category) ||
            !memory.TryReadField(
                entry_address,
                kStandaloneWizardProgressionEntryStatbookOffset,
                &entry.statbook_address)) {
            continue;
        }

        if (entry.statbook_address != 0 &&
            kStatbookMaxLevelOffset != 0 &&
            memory.IsReadableRange(entry.statbook_address + kStatbookMaxLevelOffset, sizeof(int))) {
            (void)memory.TryReadField(entry.statbook_address, kStatbookMaxLevelOffset, &entry.statbook_max_level);
        }
        // The stock table ends with three structural records after the real
        // wizard-skill rows. Their category bytes are scratch/uninitialized
        // data and differ between processes; the final record also points at a
        // non-StatBook object whose +max-level bytes decode as float 1.0. Keep
        // the rows for exact table cardinality, but normalize their meaningless
        // metadata before it enters multiplayer snapshots or revision checks.
        const bool structural_tail_record =
            index >= entry_count - 3 &&
            (entry.internal_id == 0xFFFF ||
             entry.statbook_max_level < 0 ||
             entry.statbook_max_level > 256);
        if (structural_tail_record) {
            entry.category = 0;
            entry.statbook_max_level = 0;
        }
        state->entries.push_back(entry);
    }

    state->enumerated_entry_count = static_cast<int>(state->entries.size());
    return true;
}

bool TryGetWorldState(SDModWorldState* state) {
    if (state == nullptr) {
        return false;
    }

    *state = SDModWorldState{};
    uintptr_t arena_address = 0;
    if (!TryResolveArena(&arena_address) || arena_address == 0) {
        return false;
    }

    int enemy_count = 0;
    if (!TryReadResolvedGlobalInt(kEnemyCountGlobal, &enemy_count)) {
        return false;
    }

    state->valid = true;
    state->wave = GetRunLifecycleCurrentWave();
    if (state->wave <= 0) {
        if (!ProcessMemory::Instance().TryReadField(
                arena_address,
                kArenaCombatWaveIndexOffset,
                &state->wave)) {
            return false;
        }
    }
    state->enemy_count = enemy_count;
    state->time_elapsed_ms = GetRunLifecycleElapsedMilliseconds();
    return true;
}

bool TryGetGameplayCombatState(SDModGameplayCombatState* state) {
    if (state == nullptr) {
        return false;
    }

    *state = SDModGameplayCombatState{};

    uintptr_t arena_address = 0;
    if (!TryResolveArena(&arena_address) || arena_address == 0) {
        return false;
    }

    ArenaWaveStartState snapshot;
    if (!TryReadArenaWaveStartState(arena_address, &snapshot)) {
        return false;
    }

    state->valid = true;
    state->arena_address = arena_address;
    state->combat_section_index = snapshot.combat_section_index;
    state->combat_wave_index = snapshot.combat_wave_index;
    state->combat_wait_ticks = snapshot.combat_wait_ticks;
    state->combat_advance_mode = snapshot.combat_advance_mode;
    state->combat_advance_threshold = snapshot.combat_advance_threshold;
    state->combat_wave_counter = snapshot.combat_wave_counter;
    state->combat_started_music = snapshot.combat_started_music;
    state->combat_transition_requested = snapshot.combat_transition_requested;
    state->combat_active = snapshot.combat_active;
    return true;
}

bool IsArenaCombatActorType(std::uint32_t object_type_id) {
    return IsArenaCombatActorTypeInternal(object_type_id);
}

bool IsArenaCombatActiveForUntrackedSceneActor() {
    SDModGameplayCombatState combat_state;
    if (!TryGetGameplayCombatState(&combat_state) || !combat_state.valid) {
        return false;
    }

    return combat_state.combat_active != 0 || combat_state.combat_wave_index > 0;
}

bool TryGetSceneState(SDModSceneState* state) {
    if (state == nullptr) {
        return false;
    }

    *state = SDModSceneState{};

    uintptr_t gameplay_scene_address = 0;
    if (!TryResolveCurrentGameplayScene(&gameplay_scene_address) || gameplay_scene_address == 0) {
        return false;
    }

    SceneContextSnapshot scene_context;
    (void)TryBuildSceneContextSnapshot(gameplay_scene_address, &scene_context);
    int pending_level_kind = 0;
    int transition_target_a = 0;
    int transition_target_b = 0;
    if (!TryReadResolvedGlobalInt(kPendingLevelKindGlobal, &pending_level_kind) ||
        !TryReadResolvedGlobalInt(kTransitionTargetAGlobal, &transition_target_a) ||
        !TryReadResolvedGlobalInt(kTransitionTargetBGlobal, &transition_target_b)) {
        return false;
    }

    state->valid = true;
    state->kind = DescribeSceneKind(scene_context);
    state->name = DescribeSceneName(scene_context);
    state->gameplay_scene_address = gameplay_scene_address;
    state->world_address = scene_context.world_address;
    state->arena_address = scene_context.arena_address;
    state->region_state_address = scene_context.region_state_address;
    state->current_region_index = scene_context.current_region_index;
    state->region_type_id = scene_context.region_type_id;
    state->pending_level_kind = pending_level_kind;
    state->transition_target_a = transition_target_a;
    state->transition_target_b = transition_target_b;
    return true;
}

bool TryBuildSceneActorState(
    uintptr_t actor_address,
    const SceneContextSnapshot& scene_context,
    bool require_scene_owner,
    bool tracked_enemy,
    int enemy_type,
    SDModSceneActorState* actor_state) {
    if (actor_state == nullptr || actor_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    if (!memory.IsReadableRange(actor_address, 0x80)) {
        return false;
    }

    SDModSceneActorState state{};
    state.actor_address = actor_address;
    state.tracked_enemy = tracked_enemy;
    state.enemy_type = enemy_type;
    const bool hook_tracked_enemy = tracked_enemy;
    if (!memory.TryReadField(actor_address, kObjectVtableOffset, &state.vtable_address)) {
        return false;
    }
    if (state.vtable_address == 0 || !memory.IsReadableRange(state.vtable_address, sizeof(uintptr_t))) {
        return false;
    }

    if (!memory.TryReadValue(state.vtable_address, &state.first_method_address)) {
        return false;
    }
    if (state.first_method_address == 0 || !memory.IsExecutableRange(state.first_method_address, 1)) {
        return false;
    }

    if (!memory.TryReadField(actor_address, kActorOwnerOffset, &state.owner_address)) {
        return false;
    }
    if (require_scene_owner && state.owner_address != scene_context.world_address) {
        return false;
    }

    state.valid = true;
    if (!memory.TryReadField(actor_address, kGameObjectTypeIdOffset, &state.object_type_id)) {
        return false;
    }
    if (tracked_enemy && !IsArenaCombatActorType(state.object_type_id)) {
        return false;
    }
    const bool scene_combat_enemy_candidate =
        !tracked_enemy &&
        IsArenaCombatActorType(state.object_type_id) &&
        IsArenaCombatActiveForUntrackedSceneActor();
    std::int8_t actor_slot = -1;
    std::int16_t world_slot = -1;
    if (!memory.TryReadField(actor_address, kObjectHeaderWordOffset, &state.object_header_word) ||
        !memory.TryReadField(actor_address, kActorSlotOffset, &actor_slot) ||
        !memory.TryReadField(actor_address, kActorWorldSlotOffset, &world_slot) ||
        !TryReadFiniteFloatField(actor_address, kActorPositionXOffset, &state.x) ||
        !TryReadFiniteFloatField(actor_address, kActorPositionYOffset, &state.y) ||
        !TryReadFiniteFloatField(actor_address, kActorCollisionRadiusOffset, &state.radius)) {
        return false;
    }
    state.actor_slot = static_cast<int>(actor_slot);
    state.world_slot = static_cast<int>(world_slot);
    if (state.radius < 0.0f || state.radius > 256.0f) {
        return false;
    }
    (void)memory.TryReadField(actor_address, kActorAnimationDriveStateByteOffset, &state.anim_drive_state);
    (void)memory.TryReadField(actor_address, kActorProgressionHandleOffset, &state.progression_handle_address);
    ActorHealthRuntime actor_health;
    if (IsArenaEnemyActorHealthType(state.object_type_id) &&
        TryReadArenaEnemyActorHealth(actor_address, &actor_health)) {
        state.progression_runtime_address = 0;
        state.hp = actor_health.hp;
        state.max_hp = actor_health.max_hp;
        state.dead = state.hp <= 0.0f && state.max_hp > 0.0f;
    } else if (TryResolveActorProgressionRuntime(actor_address, &state.progression_runtime_address) &&
        state.progression_runtime_address != 0 &&
        memory.IsReadableRange(state.progression_runtime_address + kProgressionHpOffset, sizeof(float)) &&
        memory.IsReadableRange(state.progression_runtime_address + kProgressionMaxHpOffset, sizeof(float))) {
        if (!TryReadFiniteFloatField(state.progression_runtime_address, kProgressionHpOffset, &state.hp) ||
            !TryReadFiniteFloatField(state.progression_runtime_address, kProgressionMaxHpOffset, &state.max_hp)) {
            return false;
        }
        state.dead = state.hp <= 0.0f && state.max_hp > 0.0f;
    } else {
        state.progression_runtime_address = 0;
        if (TryReadArenaEnemyActorHealth(actor_address, &actor_health)) {
            state.hp = actor_health.hp;
            state.max_hp = actor_health.max_hp;
            state.dead = state.hp <= 0.0f && state.max_hp > 0.0f;
        }
    }

    const bool scene_combat_enemy = scene_combat_enemy_candidate;
    if (scene_combat_enemy) {
        tracked_enemy = true;
        state.tracked_enemy = true;
        state.enemy_type = state.object_type_id;
    }

    if (tracked_enemy) {
        if (hook_tracked_enemy || scene_combat_enemy) {
            std::uint8_t death_handled_byte = 0;
            const bool death_handled =
                memory.TryReadField(actor_address, kEnemyDeathHandledOffset, &death_handled_byte) &&
                death_handled_byte != 0;
            state.dead = state.dead || death_handled;
        }
        if (!std::isfinite(state.hp) ||
            !std::isfinite(state.max_hp) ||
            state.max_hp <= 0.0f) {
            return false;
        }
    }

    (void)memory.TryReadField(actor_address, kActorEquipHandleOffset, &state.equip_handle_address);
    (void)memory.TryReadField(actor_address, kActorAnimationSelectionStateOffset, &state.animation_state_ptr);
    *actor_state = state;
    return true;
}

void AppendTransientRewardActors(
    const SceneContextSnapshot& scene_context,
    std::unordered_set<uintptr_t>* seen,
    std::vector<SDModSceneActorState>* actors) {
    if (seen == nullptr ||
        actors == nullptr ||
        scene_context.world_address == 0 ||
        kActorWorldTransientActorListOffset == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    const uintptr_t transient_actor_list =
        scene_context.world_address + kActorWorldTransientActorListOffset;
    int count = 0;
    uintptr_t items_address = 0;
    if (!memory.TryReadField(transient_actor_list, kPointerListCountOffset, &count) ||
        !memory.TryReadField(transient_actor_list, kPointerListItemsOffset, &items_address)) {
        return;
    }
    if (count <= 0 || count > 1024 || items_address == 0 ||
        !memory.IsReadableRange(items_address, static_cast<std::size_t>(count) * sizeof(std::uint32_t))) {
        return;
    }

    for (int index = 0; index < count; ++index) {
        uintptr_t actor_address = 0;
        if (!memory.TryReadValue(
                items_address + static_cast<std::size_t>(index) * sizeof(std::uint32_t),
                &actor_address) ||
            actor_address == 0 ||
            !seen->insert(actor_address).second) {
            continue;
        }

        SDModSceneActorState actor_state{};
        if (!TryBuildSceneActorState(actor_address, scene_context, true, false, -1, &actor_state)) {
            continue;
        }
        if (actor_state.object_type_id == 0x07DB) {
            actors->push_back(actor_state);
        }
    }
}

bool TryListSceneActors(std::vector<SDModSceneActorState>* actors) {
    if (actors == nullptr) {
        return false;
    }

    actors->clear();

    uintptr_t gameplay_scene_address = 0;
    if (!TryResolveCurrentGameplayScene(&gameplay_scene_address) || gameplay_scene_address == 0) {
        return false;
    }

    SceneContextSnapshot scene_context;
    if (!TryBuildSceneContextSnapshot(gameplay_scene_address, &scene_context) ||
        scene_context.world_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    std::unordered_set<uintptr_t> seen;
    actors->reserve(128);
    for (std::size_t bucket_index = 0; bucket_index < kSceneActorBucketScanCount; ++bucket_index) {
        uintptr_t actor_address = 0;
        if (!memory.TryReadValue(
                scene_context.world_address + kActorWorldBucketTableOffset + bucket_index * sizeof(uintptr_t),
                &actor_address)) {
            continue;
        }
        if (actor_address == 0 || !seen.insert(actor_address).second) {
            continue;
        }

        SDModSceneActorState actor_state{};
        if (TryBuildSceneActorState(actor_address, scene_context, true, false, -1, &actor_state)) {
            actors->push_back(actor_state);
        }
    }

    AppendTransientRewardActors(scene_context, &seen, actors);

    std::vector<SDModTrackedEnemyState> tracked_enemies;
    GetRunLifecycleTrackedEnemies(&tracked_enemies);
    for (const auto& tracked_enemy : tracked_enemies) {
        if (tracked_enemy.actor_address == 0 || !seen.insert(tracked_enemy.actor_address).second) {
            continue;
        }

        SDModSceneActorState actor_state{};
        if (TryBuildSceneActorState(
                tracked_enemy.actor_address,
                scene_context,
                false,
                true,
                tracked_enemy.enemy_type,
                &actor_state)) {
            actors->push_back(actor_state);
        }
    }

    std::sort(
        actors->begin(),
        actors->end(),
        [](const SDModSceneActorState& a, const SDModSceneActorState& b) {
            if (a.actor_slot != b.actor_slot) {
                return a.actor_slot < b.actor_slot;
            }
            if (a.world_slot != b.world_slot) {
                return a.world_slot < b.world_slot;
            }
            return a.actor_address < b.actor_address;
        });
    return true;
}
