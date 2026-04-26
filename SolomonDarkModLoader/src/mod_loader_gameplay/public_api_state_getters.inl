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
    // 1001 is the stock wave-spawned enemy actor type observed in arena runs.
    // Solomon/NPC helper actors can look hostile while waves start, but they
    // are not the wave combat targets the autonomous bot should attack.
    return object_type_id == 1001;
}

bool IsArenaCombatActiveForSceneActorFallback() {
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
    state.vtable_address = memory.ReadFieldOr<uintptr_t>(actor_address, 0x00, 0);
    if (state.vtable_address == 0 || !memory.IsReadableRange(state.vtable_address, sizeof(uintptr_t))) {
        return false;
    }

    state.first_method_address = memory.ReadValueOr<uintptr_t>(state.vtable_address, 0);
    if (state.first_method_address == 0 || !memory.IsExecutableRange(state.first_method_address, 1)) {
        return false;
    }

    state.owner_address = memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, 0);
    if (require_scene_owner && state.owner_address != scene_context.world_address) {
        return false;
    }

    state.valid = true;
    state.object_type_id = memory.ReadFieldOr<std::uint32_t>(actor_address, kGameObjectTypeIdOffset, 0);
    const bool scene_combat_enemy_candidate =
        !tracked_enemy &&
        IsArenaCombatActorType(state.object_type_id) &&
        IsArenaCombatActiveForSceneActorFallback();
    state.object_header_word = memory.ReadFieldOr<std::uint32_t>(actor_address, kObjectHeaderWordOffset, 0);
    state.actor_slot = static_cast<int>(memory.ReadFieldOr<std::int8_t>(actor_address, kActorSlotOffset, -1));
    state.world_slot = static_cast<int>(memory.ReadFieldOr<std::int16_t>(actor_address, kActorWorldSlotOffset, -1));
    state.x = memory.ReadFieldOr<float>(actor_address, kActorPositionXOffset, 0.0f);
    state.y = memory.ReadFieldOr<float>(actor_address, kActorPositionYOffset, 0.0f);
    state.anim_drive_state =
        memory.ReadFieldOr<std::uint8_t>(actor_address, kActorAnimationDriveStateByteOffset, 0);
    state.progression_handle_address = memory.ReadFieldOr<uintptr_t>(actor_address, kActorProgressionHandleOffset, 0);
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
        state.hp = memory.ReadFieldOr<float>(state.progression_runtime_address, kProgressionHpOffset, 0.0f);
        state.max_hp = memory.ReadFieldOr<float>(state.progression_runtime_address, kProgressionMaxHpOffset, 0.0f);
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
            const bool death_handled = memory.ReadFieldOr<std::uint8_t>(actor_address, kEnemyDeathHandledOffset, 0) != 0;
            state.dead = state.dead || death_handled;
        }
        if (!state.dead && state.max_hp <= 0.0f) {
            state.hp = 1.0f;
            state.max_hp = 1.0f;
        }
    }

    state.equip_handle_address = memory.ReadFieldOr<uintptr_t>(actor_address, kActorEquipHandleOffset, 0);
    state.animation_state_ptr = memory.ReadFieldOr<uintptr_t>(actor_address, kActorAnimationSelectionStateOffset, 0);
    *actor_state = state;
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

        SDModSceneActorState actor_state{};
        if (TryBuildSceneActorState(actor_address, scene_context, true, false, -1, &actor_state)) {
            actors->push_back(actor_state);
        }
    }

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
