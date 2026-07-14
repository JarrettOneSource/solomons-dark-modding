struct NativeRemotePlaybackResult {
    bool applicable = false;
    bool moving = false;
    bool wrote_position = false;
    bool wrote_presentation = false;
    bool presentation_valid = false;
};

constexpr std::uint64_t kRemoteTransformInterpolationDelayMs = 120;

struct NativeRemoteVitalSyncResult {
    bool applicable = false;
    bool wrote_health = false;
    bool wrote_mana = false;
    bool dead = false;
};

bool IsNativeRemoteParticipantBinding(const ParticipantEntityBinding* binding) {
    return binding != nullptr &&
           binding->controller_kind == multiplayer::ParticipantControllerKind::Native;
}

float ShortestHeadingDeltaDegrees(float from_degrees, float to_degrees) {
    const float from = NormalizeWizardActorHeadingForWrite(from_degrees);
    const float to = NormalizeWizardActorHeadingForWrite(to_degrees);
    float delta = to - from;
    while (delta > 180.0f) {
        delta -= 360.0f;
    }
    while (delta < -180.0f) {
        delta += 360.0f;
    }
    return delta;
}

bool RefreshNativeRemoteParticipantTransformTarget(
    ParticipantEntityBinding* binding,
    std::uint64_t now_ms) {
    if (binding == nullptr || binding->bot_id == 0) {
        return false;
    }

    const auto runtime_state = multiplayer::SnapshotRuntimeState();
    const auto* participant = multiplayer::FindParticipant(runtime_state, binding->bot_id);
    if (participant == nullptr || !multiplayer::IsRemoteParticipant(*participant)) {
        binding->replicated_transform_valid = false;
        binding->replicated_presentation_valid = false;
        return false;
    }

    binding->controller_kind = participant->controller_kind;
    if (!multiplayer::IsNativeControlledParticipant(*participant) ||
        !participant->runtime.transform_valid) {
        binding->replicated_transform_valid = false;
        binding->replicated_presentation_valid = false;
        return false;
    }

    multiplayer::ParticipantTransformSample transform_sample;
    if (!multiplayer::TrySampleParticipantTransform(
            *participant,
            now_ms,
            kRemoteTransformInterpolationDelayMs,
            &transform_sample)) {
        binding->replicated_transform_valid = false;
        binding->replicated_presentation_valid = false;
        return false;
    }

    binding->replicated_transform_valid = true;
    binding->replicated_target_x = transform_sample.position_x;
    binding->replicated_target_y = transform_sample.position_y;
    binding->replicated_target_heading =
        NormalizeWizardActorHeadingForWrite(transform_sample.heading);
    binding->replicated_presentation_valid = transform_sample.presentation_flags != 0;
    binding->replicated_anim_drive_state = transform_sample.anim_drive_state;
    binding->replicated_presentation_flags = transform_sample.presentation_flags;
    binding->replicated_attachment_staff_visual_state =
        transform_sample.attachment_staff_visual_state;
    binding->replicated_render_variant_primary = transform_sample.render_variant_primary;
    binding->replicated_render_variant_secondary = transform_sample.render_variant_secondary;
    binding->replicated_render_weapon_type = transform_sample.render_weapon_type;
    binding->replicated_render_selection_byte = transform_sample.render_selection_byte;
    binding->replicated_render_variant_tertiary = transform_sample.render_variant_tertiary;
    binding->replicated_primary_visual_link_type_id =
        transform_sample.primary_visual_link_type_id;
    binding->replicated_secondary_visual_link_type_id =
        transform_sample.secondary_visual_link_type_id;
    binding->replicated_primary_visual_link_color_block =
        transform_sample.primary_visual_link_color_block;
    binding->replicated_secondary_visual_link_color_block =
        transform_sample.secondary_visual_link_color_block;
    binding->replicated_anim_drive_state_word = transform_sample.anim_drive_state_word;
    binding->replicated_walk_cycle_primary = transform_sample.walk_cycle_primary;
    binding->replicated_walk_cycle_secondary = transform_sample.walk_cycle_secondary;
    binding->replicated_render_drive_stride = transform_sample.render_drive_stride;
    binding->replicated_render_advance_rate = transform_sample.render_advance_rate;
    binding->replicated_render_advance_phase = transform_sample.render_advance_phase;
    binding->replicated_render_drive_effect_timer = transform_sample.render_drive_effect_timer;
    binding->replicated_render_drive_effect_progress = transform_sample.render_drive_effect_progress;
    binding->replicated_transform_packet_ms = transform_sample.received_ms;
    return true;
}

bool ApplyNativeRemoteParticipantStaffVisualState(
    const ParticipantEntityBinding* binding,
    uintptr_t actor_address) {
    if (!IsNativeRemoteParticipantBinding(binding) ||
        actor_address == 0 ||
        (binding->replicated_presentation_flags &
         multiplayer::ParticipantPresentationFlagStaffVisualState) == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t equip_runtime_state_address = 0;
    (void)memory.TryReadField(
        actor_address,
        kActorEquipRuntimeStateOffset,
        &equip_runtime_state_address);
    if (equip_runtime_state_address == 0) {
        uintptr_t equip_handle_address = 0;
        if (memory.TryReadField(
                actor_address,
                kActorEquipHandleOffset,
                &equip_handle_address) &&
            equip_handle_address != 0) {
            equip_runtime_state_address = ReadSmartPointerInnerObject(equip_handle_address);
        }
    }
    if (equip_runtime_state_address == 0) {
        return false;
    }

    const auto lane = ReadEquipVisualLaneState(
        equip_runtime_state_address,
        kActorEquipRuntimeVisualLinkAttachmentOffset);
    if (lane.current_object_address == 0 ||
        lane.current_object_type_id != kStandaloneWizardStaffItemTypeId) {
        return false;
    }

    std::uint32_t current_state = 0;
    if (memory.TryReadField(
            lane.current_object_address,
            kStandaloneWizardAttachmentStaffVisualStateOffset,
            &current_state) &&
        current_state == binding->replicated_attachment_staff_visual_state) {
        return false;
    }

    return memory.TryWriteField<std::uint32_t>(
        lane.current_object_address,
        kStandaloneWizardAttachmentStaffVisualStateOffset,
        binding->replicated_attachment_staff_visual_state);
}

bool TryApplyNativeRemoteParticipantVisualLinkColorBlockToLane(
    const SDModEquipVisualLaneState& lane,
    std::uint32_t replicated_type_id,
    const std::array<std::uint8_t, multiplayer::kParticipantVisualLinkColorBlockBytes>&
        replicated_color_block) {
    if (lane.current_object_address == 0 ||
        lane.current_object_type_id == 0 ||
        replicated_type_id == 0 ||
        lane.current_object_type_id != replicated_type_id) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    std::array<std::uint8_t, multiplayer::kParticipantVisualLinkColorBlockBytes> current = {};
    if (memory.TryRead(
            lane.current_object_address + kStandaloneWizardVisualLinkColorBlockOffset,
            current.data(),
            current.size()) &&
        std::memcmp(current.data(), replicated_color_block.data(), current.size()) == 0) {
        return false;
    }

    return memory.TryWrite(
        lane.current_object_address + kStandaloneWizardVisualLinkColorBlockOffset,
        replicated_color_block.data(),
        replicated_color_block.size());
}

bool ApplyNativeRemoteParticipantVisualLinkColorBlocks(
    const ParticipantEntityBinding* binding,
    uintptr_t actor_address) {
    if (!IsNativeRemoteParticipantBinding(binding) ||
        actor_address == 0 ||
        (binding->replicated_presentation_flags &
         multiplayer::ParticipantPresentationFlagVisualLinkColorBlocks) == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t equip_runtime_state_address = 0;
    (void)memory.TryReadField(
        actor_address,
        kActorEquipRuntimeStateOffset,
        &equip_runtime_state_address);
    if (equip_runtime_state_address == 0) {
        uintptr_t equip_handle_address = 0;
        if (memory.TryReadField(
                actor_address,
                kActorEquipHandleOffset,
                &equip_handle_address) &&
            equip_handle_address != 0) {
            equip_runtime_state_address = ReadSmartPointerInnerObject(equip_handle_address);
        }
    }
    if (equip_runtime_state_address == 0) {
        return false;
    }

    const auto primary_lane = ReadEquipVisualLaneState(
        equip_runtime_state_address,
        kActorEquipRuntimeVisualLinkPrimaryOffset);
    const auto secondary_lane = ReadEquipVisualLaneState(
        equip_runtime_state_address,
        kActorEquipRuntimeVisualLinkSecondaryOffset);

    bool wrote = false;
    wrote = TryApplyNativeRemoteParticipantVisualLinkColorBlockToLane(
        primary_lane,
        binding->replicated_primary_visual_link_type_id,
        binding->replicated_primary_visual_link_color_block) || wrote;
    wrote = TryApplyNativeRemoteParticipantVisualLinkColorBlockToLane(
        secondary_lane,
        binding->replicated_primary_visual_link_type_id,
        binding->replicated_primary_visual_link_color_block) || wrote;
    wrote = TryApplyNativeRemoteParticipantVisualLinkColorBlockToLane(
        primary_lane,
        binding->replicated_secondary_visual_link_type_id,
        binding->replicated_secondary_visual_link_color_block) || wrote;
    wrote = TryApplyNativeRemoteParticipantVisualLinkColorBlockToLane(
        secondary_lane,
        binding->replicated_secondary_visual_link_type_id,
        binding->replicated_secondary_visual_link_color_block) || wrote;
    return wrote;
}

bool ApplyNativeRemoteParticipantProfileRenderSelectors(
    const ParticipantEntityBinding* binding,
    uintptr_t actor_address) {
    if (!IsNativeRemoteParticipantBinding(binding) || actor_address == 0) {
        return false;
    }

    ActorRenderBuildSnapshot expected;
    expected.variant_primary = 1;
    expected.variant_secondary = 1;
    expected.weapon_type = 0;
    expected.render_selection = static_cast<std::uint8_t>(
        ResolveStandaloneWizardRenderSelectionIndex(
            binding->character_profile.element_id));
    expected.variant_tertiary = 0;

    const auto current = CaptureActorRenderBuildSnapshot(actor_address);
    if (current.variant_primary == expected.variant_primary &&
        current.variant_secondary == expected.variant_secondary &&
        current.weapon_type == expected.weapon_type &&
        current.render_selection == expected.render_selection &&
        current.variant_tertiary == expected.variant_tertiary) {
        return false;
    }

    // The remote actor's stock cast path can mutate these bytes after
    // materialization. Reassert the local profile-built selector; the sender's
    // slot-0 selector is deliberately not authoritative for a gameplay-slot
    // clone (Fire is 0 on the sender but 1 on the clone).
    return ApplySourceActorRenderSelectorsToTargetActor(
        actor_address,
        expected,
        nullptr);
}

bool ApplyNativeRemoteParticipantPresentationState(
    const ParticipantEntityBinding* binding,
    uintptr_t actor_address) {
    if (!IsNativeRemoteParticipantBinding(binding) ||
        actor_address == 0 ||
        !binding->replicated_presentation_valid) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    bool wrote = false;
    if ((binding->replicated_presentation_flags &
         multiplayer::ParticipantPresentationFlagAnimationDriveWord) != 0 &&
        kActorAnimationDriveStateByteOffset != 0) {
        wrote = memory.TryWriteField(
            actor_address,
            kActorAnimationDriveStateByteOffset,
            binding->replicated_anim_drive_state_word) || wrote;
    } else if (kActorAnimationDriveStateByteOffset != 0) {
        wrote = memory.TryWriteField(
            actor_address,
            kActorAnimationDriveStateByteOffset,
            binding->replicated_anim_drive_state) || wrote;
    }

    wrote = ApplyNativeRemoteParticipantStaffVisualState(binding, actor_address) || wrote;
    // Render selector bytes are materialization-local. The sender reports
    // bytes from its stock slot-0 actor, while this process owns a synthetic
    // clone/gameplay-slot actor whose selector is built from the participant
    // profile. Keep the packet values as diagnostics and reassert the local profile selector
    // if stock remote-cast playback mutates it.
    wrote = ApplyNativeRemoteParticipantProfileRenderSelectors(
        binding,
        actor_address) || wrote;
    wrote = ApplyNativeRemoteParticipantVisualLinkColorBlocks(binding, actor_address) || wrote;

    if ((binding->replicated_presentation_flags &
         multiplayer::ParticipantPresentationFlagRenderDriveFloats) == 0) {
        return wrote;
    }

    if (std::isfinite(binding->replicated_walk_cycle_primary)) {
        wrote = memory.TryWriteField(
            actor_address,
            kActorWalkCyclePrimaryOffset,
            binding->replicated_walk_cycle_primary) || wrote;
    }
    if (std::isfinite(binding->replicated_walk_cycle_secondary)) {
        wrote = memory.TryWriteField(
            actor_address,
            kActorWalkCycleSecondaryOffset,
            binding->replicated_walk_cycle_secondary) || wrote;
    }
    if (std::isfinite(binding->replicated_render_drive_stride)) {
        wrote = memory.TryWriteField(
            actor_address,
            kActorRenderDriveStrideScaleOffset,
            binding->replicated_render_drive_stride) || wrote;
    }
    if (std::isfinite(binding->replicated_render_advance_rate)) {
        wrote = memory.TryWriteField(
            actor_address,
            kActorRenderAdvanceRateOffset,
            binding->replicated_render_advance_rate) || wrote;
    }
    if (std::isfinite(binding->replicated_render_advance_phase)) {
        wrote = memory.TryWriteField(
            actor_address,
            kActorRenderAdvancePhaseOffset,
            binding->replicated_render_advance_phase) || wrote;
    }
    if (std::isfinite(binding->replicated_render_drive_effect_timer)) {
        wrote = memory.TryWriteField(
            actor_address,
            kActorRenderDriveEffectTimerOffset,
            binding->replicated_render_drive_effect_timer) || wrote;
    }
    if (std::isfinite(binding->replicated_render_drive_effect_progress)) {
        wrote = memory.TryWriteField(
            actor_address,
            kActorRenderDriveEffectProgressOffset,
            binding->replicated_render_drive_effect_progress) || wrote;
    }
    // The transport keeps +0x248/+0x268 as diagnostics, but remote gameplay-slot
    // actors must leave those native-owned overlay/cache fields alone. Damage
    // flash owns the separate +0x1C4/+0x1D0 effect timer/progress lane above.
    return wrote;
}

bool NativeRemoteParticipantPlaybackTargetIsMoving(
    const ParticipantEntityBinding* binding,
    uintptr_t actor_address) {
    if (!IsNativeRemoteParticipantBinding(binding) ||
        actor_address == 0 ||
        !binding->replicated_transform_valid) {
        return false;
    }

    float x = 0.0f;
    float y = 0.0f;
    float heading = 0.0f;
    if (!TryReadFiniteFloatField(actor_address, kActorPositionXOffset, &x) ||
        !TryReadFiniteFloatField(actor_address, kActorPositionYOffset, &y) ||
        !TryReadFiniteFloatField(actor_address, kActorHeadingOffset, &heading)) {
        return false;
    }

    const float dx = binding->replicated_target_x - x;
    const float dy = binding->replicated_target_y - y;
    const float heading_delta =
        ShortestHeadingDeltaDegrees(heading, binding->replicated_target_heading);
    return dx * dx + dy * dy > 2.25f || std::fabs(heading_delta) > 2.0f;
}

NativeRemoteVitalSyncResult ApplyNativeRemoteParticipantVitalState(
    ParticipantEntityBinding* binding,
    uintptr_t actor_address) {
    NativeRemoteVitalSyncResult result;
    if (!IsNativeRemoteParticipantBinding(binding) ||
        actor_address == 0 ||
        binding->bot_id == 0) {
        return result;
    }

    const auto runtime_state = multiplayer::SnapshotRuntimeState();
    const auto* participant = multiplayer::FindParticipant(runtime_state, binding->bot_id);
    if (participant == nullptr ||
        !multiplayer::IsRemoteParticipant(*participant) ||
        !multiplayer::IsNativeControlledParticipant(*participant) ||
        !participant->runtime.valid) {
        return result;
    }
    result.applicable = true;

    uintptr_t progression_address = 0;
    if (!TryResolveActorProgressionRuntime(actor_address, &progression_address) ||
        progression_address == 0) {
        return result;
    }

    auto& memory = ProcessMemory::Instance();
    const auto clamp_to_max = [](float value, float maximum) {
        if (!std::isfinite(value)) {
            return 0.0f;
        }
        if (value < 0.0f) {
            return 0.0f;
        }
        if (std::isfinite(maximum) && maximum > 0.0f && value > maximum) {
            return maximum;
        }
        return value;
    };

    float native_hp = 0.0f;
    float native_max_hp = 0.0f;
    const bool native_health_readable =
        TryReadFiniteFloatField(
            progression_address,
            kProgressionHpOffset,
            &native_hp) &&
        TryReadFiniteFloatField(
            progression_address,
            kProgressionMaxHpOffset,
            &native_max_hp);
    std::uint8_t native_transient_flags = 0;
    std::int32_t native_poison_remaining_ticks = 0;
    uintptr_t native_poison_modifier = 0;
    const bool native_transient_readable =
        TryReadWizardActorTransientStatusState(
            actor_address,
            &native_transient_flags,
            &native_poison_remaining_ticks,
            &native_poison_modifier);
    float native_poison_damage_per_tick = 0.0f;
    const bool native_poison_damage_readable =
        native_poison_modifier != 0 &&
        memory.TryReadField(
            native_poison_modifier,
            kNativePoisonDamagePerTickOffset,
            &native_poison_damage_per_tick) &&
        std::isfinite(native_poison_damage_per_tick) &&
        native_poison_damage_per_tick >= 0.0f &&
        native_poison_damage_per_tick <= 10000.0f;
    std::int8_t native_poison_source_slot = 1;
    const bool native_poison_source_readable =
        native_poison_modifier != 0 &&
        memory.TryReadField(
            native_poison_modifier,
            kNativePoisonSourceSlotOffset,
            &native_poison_source_slot);
    const float expected_hp =
        clamp_to_max(
            participant->runtime.life_current,
            participant->runtime.life_max);
    const bool native_max_matches_last_write =
        native_health_readable &&
        binding->native_remote_vital_baseline_valid &&
        std::isfinite(binding->native_remote_last_written_max_hp) &&
        binding->native_remote_last_written_max_hp > 0.0f &&
        std::fabs(
            native_max_hp - binding->native_remote_last_written_max_hp) <=
            (std::max)(
                1.0f,
                binding->native_remote_last_written_max_hp * 0.1f);
    const bool replicated_life_increased_since_last_write =
        binding->native_remote_vital_baseline_valid &&
        expected_hp > binding->native_remote_last_written_hp + 0.0001f;
    const float damage_reference_hp =
        (std::min)(expected_hp, binding->native_remote_last_written_hp);
    const bool native_damage_observed =
        native_max_matches_last_write &&
        !replicated_life_increased_since_last_write &&
        native_hp >= 0.0f &&
        native_hp + 0.05f < damage_reference_hp;
    const bool native_poison_observed =
        native_transient_readable &&
        (native_transient_flags &
         multiplayer::ParticipantTransientStatusFlagPoisoned) != 0 &&
        (participant->runtime.transient_status_flags &
         multiplayer::ParticipantTransientStatusFlagPoisoned) == 0 &&
        native_poison_damage_readable &&
        native_poison_source_readable &&
        (native_poison_source_slot != 1 ||
         native_poison_damage_per_tick > 0.000001f);
    if (native_damage_observed || native_poison_observed) {
        multiplayer::QueueHostParticipantVitalsCorrection(
            binding->bot_id,
            native_damage_observed ? native_hp : expected_hp,
            native_max_matches_last_write
                ? native_max_hp
                : participant->runtime.life_max,
            native_poison_observed ? native_transient_flags : 0,
            native_poison_observed ? native_poison_remaining_ticks : 0,
            native_poison_observed && native_poison_damage_readable
                ? native_poison_damage_per_tick
                : 0.0f);
    }

    if (std::isfinite(participant->runtime.life_max) &&
        participant->runtime.life_max > 0.0f &&
        std::isfinite(participant->runtime.life_current) &&
        memory.IsReadableRange(progression_address + kProgressionHpOffset, sizeof(float)) &&
        memory.IsReadableRange(progression_address + kProgressionMaxHpOffset, sizeof(float))) {
        const float max_hp = participant->runtime.life_max;
        const float hp = clamp_to_max(participant->runtime.life_current, max_hp);
        result.wrote_health =
            memory.TryWriteField(progression_address, kProgressionMaxHpOffset, max_hp) &&
            memory.TryWriteField(progression_address, kProgressionHpOffset, hp);
        if (result.wrote_health) {
            binding->native_remote_vital_baseline_valid = true;
            binding->native_remote_last_written_hp = hp;
            binding->native_remote_last_written_max_hp = max_hp;
        } else {
            binding->native_remote_vital_baseline_valid = false;
        }
        result.dead = result.wrote_health && hp <= 0.0f;
    }

    if (std::isfinite(participant->runtime.mana_max) &&
        participant->runtime.mana_max > 0.0f &&
        std::isfinite(participant->runtime.mana_current) &&
        memory.IsReadableRange(progression_address + kProgressionMpOffset, sizeof(float)) &&
        memory.IsReadableRange(progression_address + kProgressionMaxMpOffset, sizeof(float))) {
        const float max_mp = participant->runtime.mana_max;
        const float mp = clamp_to_max(participant->runtime.mana_current, max_mp);
        result.wrote_mana =
            memory.TryWriteField(progression_address, kProgressionMaxMpOffset, max_mp) &&
            memory.TryWriteField(progression_address, kProgressionMpOffset, mp);
    }

    return result;
}

NativeRemotePlaybackResult ApplyNativeRemoteParticipantPlayback(
    ParticipantEntityBinding* binding,
    uintptr_t actor_address,
    std::uint64_t now_ms) {
    NativeRemotePlaybackResult result;
    if (!IsNativeRemoteParticipantBinding(binding) ||
        actor_address == 0 ||
        !binding->replicated_transform_valid) {
        return result;
    }
    result.applicable = true;

    float x = 0.0f;
    float y = 0.0f;
    float heading = 0.0f;
    if (!TryReadFiniteFloatField(actor_address, kActorPositionXOffset, &x) ||
        !TryReadFiniteFloatField(actor_address, kActorPositionYOffset, &y) ||
        !TryReadFiniteFloatField(actor_address, kActorHeadingOffset, &heading)) {
        return result;
    }

    const float dx = binding->replicated_target_x - x;
    const float dy = binding->replicated_target_y - y;
    const float distance_sq = dx * dx + dy * dy;
    const float distance = std::sqrt(distance_sq);
    const float heading_delta =
        ShortestHeadingDeltaDegrees(heading, binding->replicated_target_heading);
    result.moving = distance > 1.5f || std::fabs(heading_delta) > 2.0f;

    constexpr float kRemoteSnapDistance = 360.0f;
    constexpr float kRemoteSettleDistance = 0.05f;

    const bool large_discontinuity = distance > kRemoteSnapDistance;
    const float position_write_distance = large_discontinuity ? 0.0f : kRemoteSettleDistance;
    const float next_x = binding->replicated_target_x;
    const float next_y = binding->replicated_target_y;
    const float next_heading = binding->replicated_target_heading;

    auto& memory = ProcessMemory::Instance();
    if (distance > position_write_distance) {
        result.wrote_position =
            memory.TryWriteField(actor_address, kActorPositionXOffset, next_x) &&
            memory.TryWriteField(actor_address, kActorPositionYOffset, next_y);
        if (result.wrote_position) {
            const auto rebind_actor_address = memory.ResolveGameAddressOrZero(kWorldCellGridRebindActor);
            uintptr_t world_address = 0;
            if (rebind_actor_address != 0 &&
                memory.TryReadField(actor_address, kActorOwnerOffset, &world_address) &&
                world_address != 0) {
                DWORD rebind_exception_code = 0;
                (void)CallWorldCellGridRebindActorSafe(
                    rebind_actor_address,
                    world_address,
                    actor_address,
                    &rebind_exception_code);
            }
        }
    }
    ApplyWizardActorFacingState(actor_address, next_heading);
    result.presentation_valid = binding->replicated_presentation_valid;
    result.wrote_presentation =
        ApplyNativeRemoteParticipantPresentationState(binding, actor_address);
    binding->replicated_transform_playback_ms = now_ms;
    PublishParticipantGameplaySnapshot(*binding);
    return result;
}
