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
    state->render_variant_primary = it->render_variant_primary;
    state->render_variant_secondary = it->render_variant_secondary;
    state->render_weapon_type = it->render_weapon_type;
    state->render_selection_byte = it->render_selection_byte;
    state->render_variant_tertiary = it->render_variant_tertiary;
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
    state->render_drive_overlay_alpha = it->render_drive_overlay_alpha;
    state->render_drive_move_blend = it->render_drive_move_blend;
    state->gameplay_attach_applied = it->gameplay_attach_applied;
    state->primary_visual_lane = it->primary_visual_lane;
    state->secondary_visual_lane = it->secondary_visual_lane;
    state->attachment_visual_lane = it->attachment_visual_lane;
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
    if (resolved_gameplay_address) {
        (void)TryResolveLocalPlayerWorldContext(
            gameplay_address,
            &actor_address,
            &progression_address,
            &world_address);
    }

    if (actor_address == 0 || progression_address == 0 || world_address == 0) {
        (void)TryReadResolvedGamePointerAbsolute(kLocalPlayerActorGlobal, &actor_address);
        if (actor_address == 0) {
            return false;
        }

        auto& memory = ProcessMemory::Instance();
        world_address = memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, 0);
        if (world_address == 0 || !TryResolveActorProgressionRuntime(actor_address, &progression_address)) {
            return false;
        }
    }

    auto& memory = ProcessMemory::Instance();
    state->valid = true;
    state->hp = memory.ReadFieldOr<float>(progression_address, kProgressionHpOffset, 0.0f);
    state->max_hp = memory.ReadFieldOr<float>(progression_address, kProgressionMaxHpOffset, 0.0f);
    state->mp = memory.ReadFieldOr<float>(progression_address, kProgressionMpOffset, 0.0f);
    state->max_mp = memory.ReadFieldOr<float>(progression_address, kProgressionMaxMpOffset, 0.0f);
    state->xp = ReadRoundedXpOrUnknown(progression_address);
    state->level = memory.ReadFieldOr<int>(progression_address, kProgressionLevelOffset, 0);
    state->x = memory.ReadFieldOr<float>(actor_address, kActorPositionXOffset, 0.0f);
    state->y = memory.ReadFieldOr<float>(actor_address, kActorPositionYOffset, 0.0f);
    state->gold = ReadResolvedGlobalIntOr(kGoldGlobal);
    state->actor_address = actor_address;
    state->render_subject_address = actor_address;
    state->world_address = world_address;
    state->progression_address = progression_address;
    state->animation_state_ptr = memory.ReadFieldOr<uintptr_t>(actor_address, kActorAnimationSelectionStateOffset, 0);
    state->render_frame_table = memory.ReadFieldOr<uintptr_t>(actor_address, kActorRenderFrameTableOffset, 0);
    state->hub_visual_attachment_ptr =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorHubVisualAttachmentPtrOffset, 0);
    state->hub_visual_source_profile_address =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorHubVisualSourceProfileOffset, 0);
    state->hub_visual_descriptor_signature = HashMemoryBlockFNV1a32(
        actor_address + kActorHubVisualDescriptorBlockOffset,
        kActorHubVisualDescriptorBlockSize);
    state->progression_handle_address =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorProgressionHandleOffset, 0);
    state->equip_handle_address =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorEquipHandleOffset, 0);
    state->equip_runtime_state_address =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorEquipRuntimeStateOffset, 0);
    state->actor_slot = static_cast<int>(memory.ReadFieldOr<std::int8_t>(actor_address, kActorSlotOffset, -1));
    state->resolved_animation_state_id = ResolveActorAnimationStateId(actor_address);
    state->hub_visual_source_kind =
        memory.ReadFieldOr<std::int32_t>(actor_address, kActorHubVisualSourceKindOffset, 0);
    state->render_drive_flags =
        memory.ReadFieldOr<std::uint32_t>(actor_address, kActorRenderDriveFlagsOffset, 0);
    state->anim_drive_state =
        memory.ReadFieldOr<std::uint8_t>(actor_address, kActorAnimationDriveStateByteOffset, 0);
    state->render_variant_primary =
        memory.ReadFieldOr<std::uint8_t>(actor_address, kActorRenderVariantPrimaryOffset, 0);
    state->render_variant_secondary =
        memory.ReadFieldOr<std::uint8_t>(actor_address, kActorRenderVariantSecondaryOffset, 0);
    state->render_weapon_type =
        memory.ReadFieldOr<std::uint8_t>(actor_address, kActorRenderWeaponTypeOffset, 0);
    state->render_selection_byte =
        memory.ReadFieldOr<std::uint8_t>(actor_address, kActorRenderSelectionByteOffset, 0);
    state->render_variant_tertiary =
        memory.ReadFieldOr<std::uint8_t>(actor_address, kActorRenderVariantTertiaryOffset, 0);
    state->walk_cycle_primary = memory.ReadFieldOr<float>(actor_address, kActorWalkCyclePrimaryOffset, 0.0f);
    state->walk_cycle_secondary = memory.ReadFieldOr<float>(actor_address, kActorWalkCycleSecondaryOffset, 0.0f);
    state->render_drive_stride =
        memory.ReadFieldOr<float>(actor_address, kActorRenderDriveStrideScaleOffset, 0.0f);
    state->render_advance_rate = memory.ReadFieldOr<float>(actor_address, kActorRenderAdvanceRateOffset, 0.0f);
    state->render_advance_phase = memory.ReadFieldOr<float>(actor_address, kActorRenderAdvancePhaseOffset, 0.0f);
    state->render_drive_overlay_alpha =
        memory.ReadFieldOr<float>(actor_address, kActorRenderDriveOverlayAlphaOffset, 0.0f);
    state->render_drive_move_blend =
        memory.ReadFieldOr<float>(actor_address, kActorRenderDriveMoveBlendOffset, 0.0f);
    if (resolved_gameplay_address) {
        state->primary_visual_lane =
            ReadEquipVisualLaneState(gameplay_address, kGameplayVisualSinkPrimaryOffset);
        state->secondary_visual_lane =
            ReadEquipVisualLaneState(gameplay_address, kGameplayVisualSinkSecondaryOffset);
        state->attachment_visual_lane =
            ReadEquipVisualLaneState(gameplay_address, kGameplayVisualSinkAttachmentOffset);
    }

    const auto render_subject_address = state->render_subject_address;
    state->render_subject_animation_state_ptr =
        memory.ReadFieldOr<uintptr_t>(render_subject_address, kActorAnimationSelectionStateOffset, 0);
    state->render_subject_frame_table =
        memory.ReadFieldOr<uintptr_t>(render_subject_address, kActorRenderFrameTableOffset, 0);
    state->render_subject_hub_visual_attachment_ptr =
        memory.ReadFieldOr<uintptr_t>(render_subject_address, kActorHubVisualAttachmentPtrOffset, 0);
    state->render_subject_hub_visual_source_profile_address =
        memory.ReadFieldOr<uintptr_t>(render_subject_address, kActorHubVisualSourceProfileOffset, 0);
    state->render_subject_hub_visual_descriptor_signature = HashMemoryBlockFNV1a32(
        render_subject_address + kActorHubVisualDescriptorBlockOffset,
        kActorHubVisualDescriptorBlockSize);
    state->render_subject_hub_visual_source_kind =
        memory.ReadFieldOr<std::int32_t>(render_subject_address, kActorHubVisualSourceKindOffset, 0);
    state->render_subject_drive_flags =
        memory.ReadFieldOr<std::uint32_t>(render_subject_address, kActorRenderDriveFlagsOffset, 0);
    state->render_subject_anim_drive_state =
        memory.ReadFieldOr<std::uint8_t>(render_subject_address, kActorAnimationDriveStateByteOffset, 0);
    state->render_subject_variant_primary =
        memory.ReadFieldOr<std::uint8_t>(render_subject_address, kActorRenderVariantPrimaryOffset, 0);
    state->render_subject_variant_secondary =
        memory.ReadFieldOr<std::uint8_t>(render_subject_address, kActorRenderVariantSecondaryOffset, 0);
    state->render_subject_weapon_type =
        memory.ReadFieldOr<std::uint8_t>(render_subject_address, kActorRenderWeaponTypeOffset, 0);
    state->render_subject_selection_byte =
        memory.ReadFieldOr<std::uint8_t>(render_subject_address, kActorRenderSelectionByteOffset, 0);
    state->render_subject_variant_tertiary =
        memory.ReadFieldOr<std::uint8_t>(render_subject_address, kActorRenderVariantTertiaryOffset, 0);
    state->gameplay_attach_applied = true;
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

    state->valid = true;
    state->wave = GetRunLifecycleCurrentWave();
    if (state->wave <= 0) {
        state->wave = ProcessMemory::Instance().ReadFieldOr<int>(arena_address, kArenaCombatWaveIndexOffset, 0);
    }
    state->enemy_count = ReadResolvedGlobalIntOr(kEnemyCountGlobal);
    state->time_elapsed_ms = GetRunLifecycleElapsedMilliseconds();
    return true;
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
    state->valid = true;
    state->kind = DescribeSceneKind(scene_context);
    state->name = DescribeSceneName(scene_context);
    state->gameplay_scene_address = gameplay_scene_address;
    state->world_address = scene_context.world_address;
    state->arena_address = scene_context.arena_address;
    state->region_state_address = scene_context.region_state_address;
    state->current_region_index = scene_context.current_region_index;
    state->region_type_id = scene_context.region_type_id;
    state->pending_level_kind = ReadResolvedGlobalIntOr(kPendingLevelKindGlobal);
    state->transition_target_a = ReadResolvedGlobalIntOr(kTransitionTargetAGlobal);
    state->transition_target_b = ReadResolvedGlobalIntOr(kTransitionTargetBGlobal);
    return true;
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
        const auto actor_address = memory.ReadValueOr<uintptr_t>(
            scene_context.world_address + kActorWorldBucketTableOffset + bucket_index * sizeof(uintptr_t),
            0);
        if (actor_address == 0 || !seen.insert(actor_address).second) {
            continue;
        }
        if (!memory.IsReadableRange(actor_address, 0x80)) {
            continue;
        }

        SDModSceneActorState actor_state{};
        actor_state.actor_address = actor_address;
        actor_state.vtable_address = memory.ReadFieldOr<uintptr_t>(actor_address, 0x00, 0);
        if (actor_state.vtable_address == 0 || !memory.IsReadableRange(actor_state.vtable_address, sizeof(uintptr_t))) {
            continue;
        }

        actor_state.first_method_address =
            memory.ReadValueOr<uintptr_t>(actor_state.vtable_address, 0);
        if (actor_state.first_method_address == 0 ||
            !memory.IsExecutableRange(actor_state.first_method_address, 1)) {
            continue;
        }

        actor_state.owner_address = memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, 0);
        if (actor_state.owner_address != scene_context.world_address) {
            continue;
        }

        actor_state.valid = true;
        actor_state.object_type_id =
            memory.ReadFieldOr<std::uint32_t>(actor_address, kGameObjectTypeIdOffset, 0);
        actor_state.object_header_word =
            memory.ReadFieldOr<std::uint32_t>(actor_address, kObjectHeaderWordOffset, 0);
        actor_state.actor_slot =
            static_cast<int>(memory.ReadFieldOr<std::int8_t>(actor_address, kActorSlotOffset, -1));
        actor_state.world_slot =
            static_cast<int>(memory.ReadFieldOr<std::int16_t>(actor_address, kActorWorldSlotOffset, -1));
        actor_state.x = memory.ReadFieldOr<float>(actor_address, kActorPositionXOffset, 0.0f);
        actor_state.y = memory.ReadFieldOr<float>(actor_address, kActorPositionYOffset, 0.0f);
        actor_state.anim_drive_state =
            memory.ReadFieldOr<std::uint8_t>(actor_address, kActorAnimationDriveStateByteOffset, 0);
        actor_state.progression_handle_address =
            memory.ReadFieldOr<uintptr_t>(actor_address, kActorProgressionHandleOffset, 0);
        actor_state.equip_handle_address =
            memory.ReadFieldOr<uintptr_t>(actor_address, kActorEquipHandleOffset, 0);
        actor_state.animation_state_ptr =
            memory.ReadFieldOr<uintptr_t>(actor_address, kActorAnimationSelectionStateOffset, 0);
        actors->push_back(actor_state);
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
