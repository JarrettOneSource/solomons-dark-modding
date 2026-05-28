void FillParticipantActiveSpellObjectSnapshot(ParticipantGameplaySnapshot* snapshot) {
    if (snapshot == nullptr ||
        snapshot->world_address == 0 ||
        snapshot->active_cast_group == 0xFF ||
        snapshot->active_cast_slot == 0xFFFF) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    const auto lookup_address = memory.ResolveGameAddressOrZero(kActorWorldLookupObjectByHandle);
    uintptr_t object_address = 0;
    DWORD lookup_exception = 0;
    if (lookup_address == 0 ||
        !CallActorWorldLookupObjectByHandleSafe(
            lookup_address,
            snapshot->world_address,
            snapshot->active_cast_group,
            snapshot->active_cast_slot,
            &object_address,
            &lookup_exception) ||
        object_address == 0 ||
        !memory.IsReadableRange(object_address, 0x80)) {
        return;
    }

    float object_x = 0.0f;
    float object_y = 0.0f;
    float object_radius = 0.0f;
    float object_charge = 0.0f;
    if (!TryReadFiniteFloatField(object_address, kObjectPositionXOffset, &object_x) ||
        !TryReadFiniteFloatField(object_address, kObjectPositionYOffset, &object_y) ||
        !TryReadFiniteFloatField(object_address, kObjectCollisionRadiusOffset, &object_radius) ||
        !TryReadFiniteFloatField(object_address, kSpellObjectChargeOffset, &object_charge)) {
        return;
    }
    if (!std::isfinite(object_x) ||
        !std::isfinite(object_y) ||
        !std::isfinite(object_radius) ||
        object_radius < 0.0f ||
        object_radius > 128.0f ||
        !std::isfinite(object_charge) ||
        object_charge < 0.0f) {
        return;
    }

    snapshot->active_spell_object_readable = true;
    snapshot->active_spell_object_address = object_address;
    if (!memory.TryReadField(
            object_address,
            kGameObjectTypeIdOffset,
            &snapshot->active_spell_object_type)) {
        snapshot->active_spell_object_readable = false;
        snapshot->active_spell_object_address = 0;
        return;
    }
    snapshot->active_spell_object_x = object_x;
    snapshot->active_spell_object_y = object_y;
    snapshot->active_spell_object_radius = object_radius;
    snapshot->active_spell_object_charge = object_charge;
}

ParticipantGameplaySnapshot BuildParticipantGameplaySnapshot(const ParticipantEntityBinding& binding) {
    ParticipantGameplaySnapshot snapshot;
    snapshot.bot_id = binding.bot_id;
    snapshot.entity_materialized = binding.actor_address != 0;
    snapshot.moving = binding.movement_active;
    snapshot.entity_kind = static_cast<int>(binding.kind);
    snapshot.movement_intent_revision = binding.movement_intent_revision;
    snapshot.character_profile = binding.character_profile;
    snapshot.scene_intent = binding.scene_intent;
    snapshot.actor_address = binding.actor_address;
    snapshot.hub_visual_proxy_address = 0;
    snapshot.gameplay_slot = binding.gameplay_slot;
    snapshot.gameplay_attach_applied = binding.gameplay_attach_applied;

    if (binding.actor_address == 0) {
        return snapshot;
    }
    if (!IsParticipantActorMemoryFreshReadable(binding.actor_address)) {
        snapshot.entity_materialized = false;
        snapshot.actor_address = 0;
        return snapshot;
    }

    auto& memory = ProcessMemory::Instance();
    const auto render_probe_address = binding.actor_address;
    if (!memory.TryReadField(binding.actor_address, kActorOwnerOffset, &snapshot.world_address) ||
        !memory.TryReadField(binding.actor_address, kActorSlotOffset, &snapshot.actor_slot)) {
        snapshot.entity_materialized = false;
        snapshot.actor_address = 0;
        return snapshot;
    }
    snapshot.slot_anim_state_index = ResolveActorAnimationStateSlotIndex(binding.actor_address);
    (void)memory.TryReadField(
        render_probe_address,
        kActorAnimationSelectionStateOffset,
        &snapshot.animation_state_ptr);
    (void)memory.TryReadField(
        render_probe_address,
        kActorRenderFrameTableOffset,
        &snapshot.render_frame_table);
    (void)memory.TryReadField(
        render_probe_address,
        kActorHubVisualAttachmentPtrOffset,
        &snapshot.hub_visual_attachment_ptr);
    (void)memory.TryReadField(
        render_probe_address,
        kActorHubVisualSourceProfileOffset,
        &snapshot.hub_visual_source_profile_address);
    snapshot.hub_visual_descriptor_signature = HashMemoryBlockFNV1a32(
        render_probe_address + kActorHubVisualDescriptorBlockOffset,
        kActorHubVisualDescriptorBlockSize);
    if (!memory.TryReadField(render_probe_address, kActorProgressionHandleOffset, &snapshot.progression_handle_address) ||
        !memory.TryReadField(render_probe_address, kActorEquipHandleOffset, &snapshot.equip_handle_address) ||
        !memory.TryReadField(render_probe_address, kActorProgressionRuntimeStateOffset, &snapshot.progression_runtime_state_address) ||
        !memory.TryReadField(render_probe_address, kActorEquipRuntimeStateOffset, &snapshot.equip_runtime_state_address)) {
        snapshot.entity_materialized = false;
        snapshot.actor_address = 0;
        return snapshot;
    }
    if (snapshot.progression_runtime_state_address == 0 && snapshot.progression_handle_address != 0) {
        snapshot.progression_runtime_state_address =
            ReadSmartPointerInnerObject(snapshot.progression_handle_address);
    }
    if (snapshot.equip_runtime_state_address == 0 && snapshot.equip_handle_address != 0) {
        snapshot.equip_runtime_state_address =
            ReadSmartPointerInnerObject(snapshot.equip_handle_address);
    }
    snapshot.primary_visual_lane = ReadEquipVisualLaneState(
        snapshot.equip_runtime_state_address,
        kActorEquipRuntimeVisualLinkPrimaryOffset);
    snapshot.secondary_visual_lane = ReadEquipVisualLaneState(
        snapshot.equip_runtime_state_address,
        kActorEquipRuntimeVisualLinkSecondaryOffset);
    snapshot.attachment_visual_lane = ReadEquipVisualLaneState(
        snapshot.equip_runtime_state_address,
        kActorEquipRuntimeVisualLinkAttachmentOffset);
    snapshot.resolved_animation_state_id = ResolveActorAnimationStateId(render_probe_address);
    (void)memory.TryReadField(render_probe_address, kActorHubVisualSourceKindOffset, &snapshot.hub_visual_source_kind);
    (void)memory.TryReadField(render_probe_address, kActorRenderDriveFlagsOffset, &snapshot.render_drive_flags);
    (void)memory.TryReadField(render_probe_address, kActorAnimationDriveStateByteOffset, &snapshot.anim_drive_state);
    (void)memory.TryReadField(render_probe_address, kActorNoInterruptFlagOffset, &snapshot.no_interrupt);
    if (!memory.TryReadField(render_probe_address, kActorActiveCastGroupByteOffset, &snapshot.active_cast_group) ||
        !memory.TryReadField(render_probe_address, kActorActiveCastSlotShortOffset, &snapshot.active_cast_slot)) {
        snapshot.active_cast_group = 0xFF;
        snapshot.active_cast_slot = 0xFFFF;
    }
    (void)memory.TryReadField(render_probe_address, kActorRenderVariantPrimaryOffset, &snapshot.render_variant_primary);
    (void)memory.TryReadField(render_probe_address, kActorRenderVariantSecondaryOffset, &snapshot.render_variant_secondary);
    (void)memory.TryReadField(render_probe_address, kActorRenderWeaponTypeOffset, &snapshot.render_weapon_type);
    (void)memory.TryReadField(render_probe_address, kActorRenderSelectionByteOffset, &snapshot.render_selection_byte);
    (void)memory.TryReadField(render_probe_address, kActorRenderVariantTertiaryOffset, &snapshot.render_variant_tertiary);
    snapshot.cast_active = binding.ongoing_cast.active;
    snapshot.cast_startup_in_progress = binding.ongoing_cast.startup_in_progress;
    snapshot.cast_saw_activity = binding.ongoing_cast.saw_activity;
    snapshot.cast_skill_id = binding.ongoing_cast.skill_id;
    snapshot.cast_ticks_waiting = binding.ongoing_cast.ticks_waiting;
    snapshot.cast_target_actor_address = binding.ongoing_cast.target_actor_address;
    uintptr_t control_brain_address = 0;
    if (memory.TryReadField(
            binding.actor_address,
            kActorAnimationSelectionStateOffset,
            &control_brain_address) &&
        control_brain_address != 0) {
        (void)memory.TryReadValue<int>(
            control_brain_address + kActorControlBrainActionCooldownTicksOffset,
            &snapshot.native_action_cooldown_ticks);
    }
    FillParticipantActiveSpellObjectSnapshot(&snapshot);
    if (!TryReadFiniteFloatField(binding.actor_address, kActorPositionXOffset, &snapshot.x) ||
        !TryReadFiniteFloatField(binding.actor_address, kActorPositionYOffset, &snapshot.y) ||
        !TryReadFiniteFloatField(binding.actor_address, kActorHeadingOffset, &snapshot.heading)) {
        snapshot.entity_materialized = false;
        snapshot.actor_address = 0;
        return snapshot;
    }
    (void)TryReadFiniteFloatField(render_probe_address, kActorWalkCyclePrimaryOffset, &snapshot.walk_cycle_primary);
    (void)TryReadFiniteFloatField(render_probe_address, kActorWalkCycleSecondaryOffset, &snapshot.walk_cycle_secondary);
    (void)TryReadFiniteFloatField(render_probe_address, kActorRenderDriveStrideScaleOffset, &snapshot.render_drive_stride);
    (void)TryReadFiniteFloatField(render_probe_address, kActorRenderAdvanceRateOffset, &snapshot.render_advance_rate);
    (void)TryReadFiniteFloatField(render_probe_address, kActorRenderAdvancePhaseOffset, &snapshot.render_advance_phase);
    (void)TryReadFiniteFloatField(render_probe_address, kActorRenderDriveOverlayAlphaOffset, &snapshot.render_drive_overlay_alpha);
    (void)TryReadFiniteFloatField(render_probe_address, kActorRenderDriveMoveBlendOffset, &snapshot.render_drive_move_blend);

    uintptr_t progression_address = 0;
    if (!memory.TryReadField(binding.actor_address, kActorProgressionRuntimeStateOffset, &progression_address)) {
        snapshot.entity_materialized = false;
        snapshot.actor_address = 0;
        return snapshot;
    }
    if (progression_address == 0 && snapshot.progression_handle_address != 0) {
        progression_address = ReadSmartPointerInnerObject(snapshot.progression_handle_address);
    }
    if (progression_address != 0) {
        if (!TryReadFiniteFloatField(progression_address, kProgressionHpOffset, &snapshot.hp) ||
            !TryReadFiniteFloatField(progression_address, kProgressionMaxHpOffset, &snapshot.max_hp) ||
            !TryReadFiniteFloatField(progression_address, kProgressionMpOffset, &snapshot.mp) ||
            !TryReadFiniteFloatField(progression_address, kProgressionMaxMpOffset, &snapshot.max_mp)) {
            snapshot.entity_materialized = false;
            snapshot.actor_address = 0;
            return snapshot;
        }
    }

    return snapshot;
}

void SyncParticipantRuntimeFromGameplaySnapshot(const ParticipantGameplaySnapshot& snapshot) {
    multiplayer::UpdateRuntimeState([&](multiplayer::RuntimeState& state) {
        auto* participant = multiplayer::FindParticipant(state, snapshot.bot_id);
        if (participant == nullptr || !multiplayer::IsRemoteParticipant(*participant)) {
            return;
        }

        participant->runtime.valid = participant->runtime.valid || snapshot.entity_materialized;
        participant->runtime.in_run =
            participant->runtime.scene_intent.kind == multiplayer::ParticipantSceneIntentKind::Run;

        if (!snapshot.entity_materialized) {
            return;
        }

        participant->runtime.life_current = static_cast<std::int32_t>(snapshot.hp);
        participant->runtime.life_max = static_cast<std::int32_t>(snapshot.max_hp);
        participant->runtime.mana_current = static_cast<std::int32_t>(snapshot.mp);
        participant->runtime.mana_max = static_cast<std::int32_t>(snapshot.max_mp);

        if (multiplayer::IsNativeControlledParticipant(*participant)) {
            return;
        }

        participant->runtime.transform_valid = true;
        participant->runtime.position_x = snapshot.x;
        participant->runtime.position_y = snapshot.y;
        participant->runtime.heading = snapshot.heading;
    });
}

void PublishParticipantGameplaySnapshot(const ParticipantEntityBinding& binding) {
    const auto snapshot = BuildParticipantGameplaySnapshot(binding);
    std::lock_guard<std::mutex> lock(g_wizard_bot_snapshot_mutex);
    const auto it = std::find_if(
        g_participant_gameplay_snapshots.begin(),
        g_participant_gameplay_snapshots.end(),
        [&](const ParticipantGameplaySnapshot& existing) {
            return existing.bot_id == binding.bot_id;
        });
    if (it == g_participant_gameplay_snapshots.end()) {
        g_participant_gameplay_snapshots.push_back(snapshot);
    } else {
        *it = snapshot;
    }

    const auto now_ms = static_cast<std::uint64_t>(::GetTickCount64());
    if (now_ms - g_last_wizard_bot_crash_summary_refresh_ms >= 1000) {
        g_last_wizard_bot_crash_summary_refresh_ms = now_ms;
        RefreshWizardBotCrashSummaryLocked();
    }

    SyncParticipantRuntimeFromGameplaySnapshot(snapshot);
}

bool TryBuildParticipantRematerializationRequest(
    uintptr_t gameplay_address,
    const ParticipantEntityBinding& binding,
    ParticipantRematerializationRequest* request) {
    if (request == nullptr || binding.actor_address == 0) {
        return false;
    }

    *request = ParticipantRematerializationRequest{};
    if (binding.materialized_scene_address == 0 && binding.materialized_world_address == 0) {
        return false;
    }

    SceneContextSnapshot scene_context;
    if (!TryBuildSceneContextSnapshot(gameplay_address, &scene_context)) {
        return false;
    }

    if (!HasBotMaterializedSceneChanged(binding, scene_context)) {
        return false;
    }

    multiplayer::BotSnapshot bot_snapshot;
    if (!multiplayer::ReadParticipantSnapshot(binding.bot_id, &bot_snapshot) || !bot_snapshot.available) {
        return false;
    }

    request->bot_id = binding.bot_id;
    request->character_profile = bot_snapshot.character_profile;
    request->scene_intent = bot_snapshot.scene_intent;
    request->has_transform = bot_snapshot.transform_valid;
    request->x = bot_snapshot.position_x;
    request->y = bot_snapshot.position_y;
    request->heading = bot_snapshot.heading;
    request->previous_scene_address = binding.materialized_scene_address;
    request->previous_world_address = binding.materialized_world_address;
    request->previous_region_index = binding.materialized_region_index;
    request->next_scene_address = scene_context.gameplay_scene_address;
    request->next_world_address = scene_context.world_address;
    request->next_region_index = scene_context.current_region_index;
    return true;
}

void QueueParticipantRematerialization(const ParticipantRematerializationRequest& request) {
    Log(
        "[bots] rematerializing entity. bot_id=" + std::to_string(request.bot_id) +
        " old_scene=" + HexString(request.previous_scene_address) +
        " new_scene=" + HexString(request.next_scene_address) +
        " old_world=" + HexString(request.previous_world_address) +
        " new_world=" + HexString(request.next_world_address) +
        " old_region=" + std::to_string(request.previous_region_index) +
        " new_region=" + std::to_string(request.next_region_index));

    DematerializeParticipantEntityNow(request.bot_id, false, "scene transition");
    {
        std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
        if (auto* binding = FindParticipantEntity(request.bot_id); binding != nullptr) {
            binding->character_profile = request.character_profile;
            binding->scene_intent = request.scene_intent;
            binding->next_scene_materialize_retry_ms =
                static_cast<std::uint64_t>(::GetTickCount64()) + kWizardBotSyncRetryDelayMs;
        }
    }
}
