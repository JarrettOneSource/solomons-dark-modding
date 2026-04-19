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

    auto& memory = ProcessMemory::Instance();
    const auto render_probe_address = binding.actor_address;
    snapshot.world_address = memory.ReadFieldOr<uintptr_t>(binding.actor_address, kActorOwnerOffset, 0);
    snapshot.actor_slot = memory.ReadFieldOr<std::int8_t>(binding.actor_address, kActorSlotOffset, -1);
    snapshot.slot_anim_state_index = ResolveActorAnimationStateSlotIndex(binding.actor_address);
    snapshot.animation_state_ptr =
        memory.ReadFieldOr<uintptr_t>(render_probe_address, kActorAnimationSelectionStateOffset, 0);
    snapshot.render_frame_table =
        memory.ReadFieldOr<uintptr_t>(render_probe_address, kActorRenderFrameTableOffset, 0);
    snapshot.hub_visual_attachment_ptr =
        memory.ReadFieldOr<uintptr_t>(render_probe_address, kActorHubVisualAttachmentPtrOffset, 0);
    snapshot.hub_visual_source_profile_address =
        memory.ReadFieldOr<uintptr_t>(render_probe_address, kActorHubVisualSourceProfileOffset, 0);
    snapshot.hub_visual_descriptor_signature = HashMemoryBlockFNV1a32(
        render_probe_address + kActorHubVisualDescriptorBlockOffset,
        kActorHubVisualDescriptorBlockSize);
    if (!IsRegisteredGameNpcKind(binding.kind)) {
        snapshot.progression_handle_address =
            memory.ReadFieldOr<uintptr_t>(render_probe_address, kActorProgressionHandleOffset, 0);
        snapshot.equip_handle_address =
            memory.ReadFieldOr<uintptr_t>(render_probe_address, kActorEquipHandleOffset, 0);
        snapshot.progression_runtime_state_address =
            memory.ReadFieldOr<uintptr_t>(render_probe_address, kActorProgressionRuntimeStateOffset, 0);
        snapshot.equip_runtime_state_address =
            memory.ReadFieldOr<uintptr_t>(render_probe_address, kActorEquipRuntimeStateOffset, 0);
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
    }
    snapshot.resolved_animation_state_id = ResolveActorAnimationStateId(render_probe_address);
    snapshot.hub_visual_source_kind =
        memory.ReadFieldOr<std::int32_t>(render_probe_address, kActorHubVisualSourceKindOffset, 0);
    snapshot.render_drive_flags =
        memory.ReadFieldOr<std::uint32_t>(render_probe_address, kActorRenderDriveFlagsOffset, 0);
    snapshot.anim_drive_state =
        memory.ReadFieldOr<std::uint8_t>(render_probe_address, kActorAnimationDriveStateByteOffset, 0);
    snapshot.render_variant_primary =
        memory.ReadFieldOr<std::uint8_t>(render_probe_address, kActorRenderVariantPrimaryOffset, 0);
    snapshot.render_variant_secondary =
        memory.ReadFieldOr<std::uint8_t>(render_probe_address, kActorRenderVariantSecondaryOffset, 0);
    snapshot.render_weapon_type =
        memory.ReadFieldOr<std::uint8_t>(render_probe_address, kActorRenderWeaponTypeOffset, 0);
    snapshot.render_selection_byte =
        memory.ReadFieldOr<std::uint8_t>(render_probe_address, kActorRenderSelectionByteOffset, 0);
    snapshot.render_variant_tertiary =
        memory.ReadFieldOr<std::uint8_t>(render_probe_address, kActorRenderVariantTertiaryOffset, 0);
    snapshot.x = memory.ReadFieldOr<float>(binding.actor_address, kActorPositionXOffset, 0.0f);
    snapshot.y = memory.ReadFieldOr<float>(binding.actor_address, kActorPositionYOffset, 0.0f);
    snapshot.heading = memory.ReadFieldOr<float>(binding.actor_address, kActorHeadingOffset, 0.0f);
    snapshot.walk_cycle_primary =
        memory.ReadFieldOr<float>(render_probe_address, kActorWalkCyclePrimaryOffset, 0.0f);
    snapshot.walk_cycle_secondary =
        memory.ReadFieldOr<float>(render_probe_address, kActorWalkCycleSecondaryOffset, 0.0f);
    snapshot.render_drive_stride =
        memory.ReadFieldOr<float>(render_probe_address, kActorRenderDriveStrideScaleOffset, 0.0f);
    snapshot.render_advance_rate =
        memory.ReadFieldOr<float>(render_probe_address, kActorRenderAdvanceRateOffset, 0.0f);
    snapshot.render_advance_phase =
        memory.ReadFieldOr<float>(render_probe_address, kActorRenderAdvancePhaseOffset, 0.0f);
    snapshot.render_drive_overlay_alpha =
        memory.ReadFieldOr<float>(render_probe_address, kActorRenderDriveOverlayAlphaOffset, 0.0f);
    snapshot.render_drive_move_blend =
        memory.ReadFieldOr<float>(render_probe_address, kActorRenderDriveMoveBlendOffset, 0.0f);

    if (!IsRegisteredGameNpcKind(binding.kind)) {
        auto progression_address =
            memory.ReadFieldOr<uintptr_t>(binding.actor_address, kActorProgressionRuntimeStateOffset, 0);
        if (progression_address == 0 && snapshot.progression_handle_address != 0) {
            progression_address = ReadSmartPointerInnerObject(snapshot.progression_handle_address);
        }
        if (progression_address != 0) {
            snapshot.hp = memory.ReadFieldOr<float>(progression_address, kProgressionHpOffset, 0.0f);
            snapshot.max_hp = memory.ReadFieldOr<float>(progression_address, kProgressionMaxHpOffset, 0.0f);
            snapshot.mp = memory.ReadFieldOr<float>(progression_address, kProgressionMpOffset, 0.0f);
            snapshot.max_mp = memory.ReadFieldOr<float>(progression_address, kProgressionMaxMpOffset, 0.0f);
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

        if (!multiplayer::IsLuaControlledParticipant(*participant)) {
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
    if (!multiplayer::ReadBotSnapshot(binding.bot_id, &bot_snapshot) || !bot_snapshot.available) {
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
