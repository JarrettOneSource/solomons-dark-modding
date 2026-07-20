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
    binding->replicated_primary_visual_link_recipe_uid =
        transform_sample.primary_visual_link_recipe_uid;
    binding->replicated_secondary_visual_link_recipe_uid =
        transform_sample.secondary_visual_link_recipe_uid;
    binding->replicated_attachment_visual_link_type_id =
        transform_sample.attachment_visual_link_type_id;
    binding->replicated_attachment_visual_link_recipe_uid =
        transform_sample.attachment_visual_link_recipe_uid;
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
    binding->replicated_magic_shield_absorb_remaining = transform_sample.magic_shield_absorb_remaining;
    binding->replicated_magic_shield_absorb_capacity = transform_sample.magic_shield_absorb_capacity;
    binding->replicated_magic_shield_explosion_fraction = transform_sample.magic_shield_explosion_fraction;
    binding->replicated_magic_shield_hit_flash = transform_sample.magic_shield_hit_flash;
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

struct ReplicatedWearableEquipmentState {
    std::uint32_t type_id = 0;
    std::uint32_t recipe_uid = 0;
    std::array<std::uint8_t, multiplayer::kParticipantVisualLinkColorBlockBytes>
        color_block = {};
};

bool TryResolveRemoteParticipantEquipRuntime(
    uintptr_t actor_address,
    uintptr_t* equip_runtime_state_address) {
    if (equip_runtime_state_address != nullptr) {
        *equip_runtime_state_address = 0;
    }
    if (actor_address == 0 || equip_runtime_state_address == nullptr) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    if (memory.TryReadField(
            actor_address,
            kActorEquipRuntimeStateOffset,
            equip_runtime_state_address) &&
        *equip_runtime_state_address != 0) {
        return true;
    }

    uintptr_t equip_handle_address = 0;
    if (!memory.TryReadField(
            actor_address,
            kActorEquipHandleOffset,
            &equip_handle_address) ||
        equip_handle_address == 0) {
        return false;
    }
    *equip_runtime_state_address = ReadSmartPointerInnerObject(equip_handle_address);
    return *equip_runtime_state_address != 0;
}

bool TryApplyNativeRemoteParticipantWearableColor(
    const SDModEquipVisualLaneState& lane,
    const ReplicatedWearableEquipmentState& desired,
    bool* changed) {
    if (changed != nullptr) {
        *changed = false;
    }
    if (lane.current_object_address == 0 ||
        lane.current_object_type_id != desired.type_id ||
        desired.type_id == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    std::array<std::uint8_t, multiplayer::kParticipantVisualLinkColorBlockBytes> current = {};
    if (!memory.TryRead(
            lane.current_object_address + kStandaloneWizardVisualLinkColorBlockOffset,
            current.data(),
            current.size())) {
        return false;
    }
    if (current == desired.color_block) {
        return true;
    }
    if (!memory.TryWrite(
            lane.current_object_address + kStandaloneWizardVisualLinkColorBlockOffset,
            desired.color_block.data(),
            desired.color_block.size())) {
        return false;
    }
    if (changed != nullptr) {
        *changed = true;
    }
    return true;
}

bool ReconcileNativeRemoteParticipantEquipmentLane(
    uintptr_t actor_address,
    std::size_t lane_offset,
    std::uint32_t desired_type_id,
    std::uint32_t desired_recipe_uid,
    const ReplicatedWearableEquipmentState* wearable,
    std::string_view label,
    bool* changed,
    std::string* error_message) {
    if (changed != nullptr) {
        *changed = false;
    }
    uintptr_t equip_runtime_state_address = 0;
    if (!TryResolveRemoteParticipantEquipRuntime(
            actor_address,
            &equip_runtime_state_address)) {
        if (error_message != nullptr) {
            *error_message = "Remote equipment runtime is unavailable.";
        }
        return false;
    }

    const auto current = ReadEquipVisualLaneState(
        equip_runtime_state_address,
        lane_offset);
    if (desired_type_id == 0) {
        if (current.current_object_address == 0) {
            return true;
        }
        std::string detach_error;
        if (!SetEquipVisualLaneObject(
                actor_address,
                lane_offset,
                0,
                label,
                &detach_error)) {
            if (error_message != nullptr) {
                *error_message = detach_error;
            }
            return false;
        }
        DestroyUnownedNativeItem(current.current_object_address, "remote_equipment_detach");
        if (changed != nullptr) {
            *changed = true;
        }
        return true;
    }

    if (current.current_object_type_id == desired_type_id &&
        current.current_object_recipe_uid == desired_recipe_uid) {
        if (wearable == nullptr) {
            return true;
        }
        return TryApplyNativeRemoteParticipantWearableColor(
            current,
            *wearable,
            changed);
    }

    uintptr_t replacement = 0;
    std::string replacement_error;
    if (desired_recipe_uid != 0) {
        const std::array<std::uint8_t, multiplayer::kParticipantVisualLinkColorBlockBytes>
            empty_color = {};
        if (!CloneNativeItemFromRecipe(
                desired_recipe_uid,
                desired_type_id,
                wearable != nullptr ? wearable->color_block : empty_color,
                wearable != nullptr,
                &replacement,
                &replacement_error)) {
            if (error_message != nullptr) {
                *error_message = replacement_error;
            }
            return false;
        }
    } else if (desired_type_id == kStandaloneWizardHatVisualTypeId ||
               desired_type_id == kStandaloneWizardRobeVisualTypeId) {
        if (wearable == nullptr) {
            if (error_message != nullptr) {
                *error_message = "Default wearable equipment lacks its color payload.";
            }
            return false;
        }
        const auto ctor = ProcessMemory::Instance().ResolveGameAddressOrZero(
            desired_type_id == kStandaloneWizardHatVisualTypeId
                ? kStandaloneWizardVisualLinkSecondaryCtor
                : kStandaloneWizardVisualLinkPrimaryCtor);
        if (!CreateStandaloneWizardVisualLinkObject(
                ctor,
                wearable->color_block,
                &replacement,
                &replacement_error)) {
            if (error_message != nullptr) {
                *error_message = replacement_error;
            }
            return false;
        }
    } else if (desired_type_id == kStandaloneWizardStaffItemTypeId) {
        if (!CreateGameplaySlotStaffItemObject(
                &replacement,
                &replacement_error)) {
            if (error_message != nullptr) {
                *error_message = replacement_error;
            }
            return false;
        }
    } else {
        if (error_message != nullptr) {
            *error_message = "Equipment identity has no exact stock recipe.";
        }
        return false;
    }

    std::string attach_error;
    if (!SetEquipVisualLaneObject(
            actor_address,
            lane_offset,
            replacement,
            label,
            &attach_error)) {
        DestroyUnownedNativeItem(replacement, "remote_equipment_attach_failed");
        if (error_message != nullptr) {
            *error_message = attach_error;
        }
        return false;
    }
    DestroyUnownedNativeItem(current.current_object_address, "remote_equipment_replaced");
    if (changed != nullptr) {
        *changed = true;
    }
    return true;
}

bool ApplyNativeRemoteParticipantEquipmentState(
    ParticipantEntityBinding* binding,
    uintptr_t actor_address) {
    if (!IsNativeRemoteParticipantBinding(binding) ||
        actor_address == 0 ||
        (binding->replicated_presentation_flags &
         multiplayer::ParticipantPresentationFlagEquipmentState) == 0) {
        return false;
    }

    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    if (now_ms < binding->equipment_reconcile_not_before_ms) {
        return false;
    }

    ReplicatedWearableEquipmentState hat;
    ReplicatedWearableEquipmentState robe;
    bool wearable_types_valid = true;
    const auto assign_wearable = [&](std::uint32_t type_id,
                                     std::uint32_t recipe_uid,
                                     const auto& color_block) {
        ReplicatedWearableEquipmentState* target = nullptr;
        if (type_id == kStandaloneWizardHatVisualTypeId) {
            target = &hat;
        } else if (type_id == kStandaloneWizardRobeVisualTypeId) {
            target = &robe;
        } else if (type_id != 0) {
            wearable_types_valid = false;
            return;
        }
        if (target == nullptr) {
            return;
        }
        if (target->type_id != 0) {
            wearable_types_valid = false;
            return;
        }
        target->type_id = type_id;
        target->recipe_uid = recipe_uid;
        target->color_block = color_block;
    };
    // Slot-0 gameplay and gameplay-slot actor runtimes use opposite primary /
    // secondary labels. Canonicalize non-empty records by native item type;
    // whichever wearable is absent remains the authoritative empty lane.
    assign_wearable(
        binding->replicated_primary_visual_link_type_id,
        binding->replicated_primary_visual_link_recipe_uid,
        binding->replicated_primary_visual_link_color_block);
    assign_wearable(
        binding->replicated_secondary_visual_link_type_id,
        binding->replicated_secondary_visual_link_recipe_uid,
        binding->replicated_secondary_visual_link_color_block);

    bool complete = wearable_types_valid;
    bool changed = false;
    const auto reconcile = [&](std::size_t lane_offset,
                               std::uint32_t type_id,
                               std::uint32_t recipe_uid,
                               const ReplicatedWearableEquipmentState* wearable,
                               std::string_view label) {
        bool lane_changed = false;
        std::string lane_error;
        if (!ReconcileNativeRemoteParticipantEquipmentLane(
                actor_address,
                lane_offset,
                type_id,
                recipe_uid,
                wearable,
                label,
                &lane_changed,
                &lane_error)) {
            complete = false;
            return;
        }
        changed = changed || lane_changed;
    };
    reconcile(
        kActorEquipRuntimeVisualLinkSecondaryOffset,
        hat.type_id,
        hat.recipe_uid,
        &hat,
        "hat");
    reconcile(
        kActorEquipRuntimeVisualLinkPrimaryOffset,
        robe.type_id,
        robe.recipe_uid,
        &robe,
        "robe");

    const auto attachment_type = binding->replicated_attachment_visual_link_type_id;
    const bool attachment_type_valid =
        attachment_type == 0 ||
        attachment_type == kStandaloneWizardStaffItemTypeId ||
        attachment_type == kStandaloneWizardWandItemTypeId;
    if (!attachment_type_valid) {
        complete = false;
    } else {
        reconcile(
            kActorEquipRuntimeVisualLinkAttachmentOffset,
            attachment_type,
            binding->replicated_attachment_visual_link_recipe_uid,
            nullptr,
            "attachment");
    }

    if (changed) {
        std::string refresh_error;
        if (!multiplayer::RefreshParticipantNativeProgression(
                binding->bot_id,
                &refresh_error)) {
            complete = false;
        }
    }
    binding->equipment_reconcile_not_before_ms =
        complete ? 0 : now_ms + 250;
    return changed;
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
    ParticipantEntityBinding* binding,
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
    wrote = ApplyNativeRemoteParticipantEquipmentState(binding, actor_address) || wrote;

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
    if (std::isfinite(binding->replicated_magic_shield_absorb_remaining)) {
        wrote = memory.TryWriteField(
            actor_address,
            kActorMagicShieldAbsorbRemainingOffset,
            binding->replicated_magic_shield_absorb_remaining) || wrote;
    }
    if (std::isfinite(binding->replicated_magic_shield_absorb_capacity)) {
        wrote = memory.TryWriteField(
            actor_address,
            kActorMagicShieldAbsorbCapacityOffset,
            binding->replicated_magic_shield_absorb_capacity) || wrote;
    }
    if (std::isfinite(binding->replicated_magic_shield_explosion_fraction)) {
        wrote = memory.TryWriteField(
            actor_address,
            kActorMagicShieldExplosionFractionOffset,
            binding->replicated_magic_shield_explosion_fraction) || wrote;
    }
    if (std::isfinite(binding->replicated_magic_shield_hit_flash)) {
        wrote = memory.TryWriteField(
            actor_address,
            kActorMagicShieldHitFlashOffset,
            binding->replicated_magic_shield_hit_flash) || wrote;
    }
    // The transport keeps +0x248/+0x268 as diagnostics, but remote gameplay-slot
    // actors must leave those native-owned overlay/cache fields alone. Magic
    // Shield owns the separate +0x1C4..+0x1D0 state block above.
    return wrote;
}

#include "native_remote_vitals_and_playback.inl"
