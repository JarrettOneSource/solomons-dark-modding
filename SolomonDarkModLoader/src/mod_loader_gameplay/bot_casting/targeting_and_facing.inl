bool TryComputeActorAimTowardTarget(
    uintptr_t actor_address,
    uintptr_t target_actor_address,
    float* heading_degrees,
    float* target_x_out,
    float* target_y_out);

bool TryComputeActorAimTowardTargetFromOrigin(
    uintptr_t actor_address,
    uintptr_t target_actor_address,
    bool origin_valid,
    float origin_x,
    float origin_y,
    float* heading_degrees,
    float* target_x_out,
    float* target_y_out);

bool SkillRequiresHeldCastInputDuringNativeTick(std::int32_t skill_id);

bool SkillRequiresBoundedHeldCastInputDuringNativeTick(std::int32_t skill_id);

bool SkillRequiresSyntheticCastInputDuringNativeTick(std::int32_t skill_id);

bool SkillTracksLiveTargetDuringNativeTick(std::int32_t skill_id);

std::int32_t ResolveOngoingNativeTickSkillId(
    const ParticipantEntityBinding::OngoingCastState& ongoing);

bool OngoingCastShouldRefreshNativeTargetState(
    const ParticipantEntityBinding::OngoingCastState& ongoing);

bool OngoingCastShouldUseLiveFacingTarget(
    const ParticipantEntityBinding::OngoingCastState& ongoing);

uintptr_t ResolveOngoingCastNativeTargetActor(
    const ParticipantEntityBinding* binding,
    const ParticipantEntityBinding::OngoingCastState& ongoing);

bool SkillRequiresNativeActorTargetHandle(std::int32_t skill_id) {
    // Air primary (lightning) is not projectile/collision based. The native
    // handler resolves the victim through actor+0x164/0x166 and only runs the
    // damage branch when that handle points at a live world actor.
    switch (skill_id) {
    case 0x18:
    case 0x3F5:
        return true;
    default:
        return false;
    }
}

bool OngoingCastNeedsNativeTargetHandle(
    const ParticipantEntityBinding::OngoingCastState& ongoing) {
    return SkillRequiresNativeActorTargetHandle(ongoing.skill_id) ||
           SkillRequiresNativeActorTargetHandle(ongoing.dispatcher_skill_id);
}

bool TryResolveSameWorldTargetHandle(
    uintptr_t actor_address,
    uintptr_t target_actor_address,
    std::uint8_t* group_out,
    std::uint16_t* slot_out) {
    if (group_out != nullptr) {
        *group_out = kTargetHandleGroupSentinel;
    }
    if (slot_out != nullptr) {
        *slot_out = kTargetHandleSlotSentinel;
    }
    if (actor_address == 0 || target_actor_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto actor_owner =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, 0);
    const auto target_owner =
        memory.ReadFieldOr<uintptr_t>(target_actor_address, kActorOwnerOffset, 0);
    if (actor_owner == 0 || actor_owner != target_owner) {
        return false;
    }

    const auto target_group =
        memory.ReadFieldOr<std::uint8_t>(
            target_actor_address,
            kActorSlotOffset,
            kTargetHandleGroupSentinel);
    const auto target_slot =
        memory.ReadFieldOr<std::uint16_t>(
            target_actor_address,
            kActorWorldSlotOffset,
            kTargetHandleSlotSentinel);
    if (target_group == kTargetHandleGroupSentinel ||
        target_slot == kTargetHandleSlotSentinel) {
        return false;
    }

    if (group_out != nullptr) {
        *group_out = target_group;
    }
    if (slot_out != nullptr) {
        *slot_out = target_slot;
    }
    return true;
}

bool TryComputeActorHeadingTowardTarget(
    uintptr_t actor_address,
    uintptr_t target_actor_address,
    float* heading_degrees) {
    float ignored_target_x = 0.0f;
    float ignored_target_y = 0.0f;
    return TryComputeActorAimTowardTarget(
        actor_address,
        target_actor_address,
        heading_degrees,
        &ignored_target_x,
        &ignored_target_y);
}

bool TryComputeActorAimTowardTarget(
    uintptr_t actor_address,
    uintptr_t target_actor_address,
    float* heading_degrees,
    float* target_x_out,
    float* target_y_out) {
    return TryComputeActorAimTowardTargetFromOrigin(
        actor_address,
        target_actor_address,
        false,
        0.0f,
        0.0f,
        heading_degrees,
        target_x_out,
        target_y_out);
}

bool TryComputeActorAimTowardTargetFromOrigin(
    uintptr_t actor_address,
    uintptr_t target_actor_address,
    bool origin_valid,
    float origin_x,
    float origin_y,
    float* heading_degrees,
    float* target_x_out,
    float* target_y_out) {
    if (actor_address == 0 || target_actor_address == 0 || heading_degrees == nullptr) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    constexpr std::size_t kActorFacingReadSize = 0x80;
    if (!memory.IsReadableRange(actor_address, kActorFacingReadSize) ||
        !memory.IsReadableRange(target_actor_address, kActorFacingReadSize) ||
        IsActorRuntimeDead(target_actor_address)) {
        return false;
    }

    const auto actor_owner = memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, 0);
    const auto target_owner = memory.ReadFieldOr<uintptr_t>(target_actor_address, kActorOwnerOffset, 0);
    if (actor_owner == 0 || target_owner == 0 || actor_owner != target_owner) {
        return false;
    }

    const auto actor_x =
        origin_valid && std::isfinite(origin_x)
            ? origin_x
            : memory.ReadFieldOr<float>(actor_address, kActorPositionXOffset, 0.0f);
    const auto actor_y =
        origin_valid && std::isfinite(origin_y)
            ? origin_y
            : memory.ReadFieldOr<float>(actor_address, kActorPositionYOffset, 0.0f);
    const auto target_x = memory.ReadFieldOr<float>(target_actor_address, kActorPositionXOffset, 0.0f);
    const auto target_y = memory.ReadFieldOr<float>(target_actor_address, kActorPositionYOffset, 0.0f);
    const auto dx = target_x - actor_x;
    const auto dy = target_y - actor_y;
    if (!std::isfinite(dx) || !std::isfinite(dy) || ((dx * dx) + (dy * dy)) <= 0.0001f) {
        return false;
    }

    *heading_degrees = NormalizeWizardActorHeadingForWrite(
        static_cast<float>(std::atan2(dy, dx) * kWizardHeadingRadiansToDegrees + 90.0f));
    if (target_x_out != nullptr) {
        *target_x_out = target_x;
    }
    if (target_y_out != nullptr) {
        *target_y_out = target_y;
    }
    return true;
}

bool TryGetBindingMovementInputVector(
    const ParticipantEntityBinding& binding,
    float* direction_x_out,
    float* direction_y_out) {
    if (direction_x_out == nullptr || direction_y_out == nullptr || !binding.movement_active) {
        return false;
    }

    const auto direction_x = binding.direction_x;
    const auto direction_y = binding.direction_y;
    const auto magnitude_squared = (direction_x * direction_x) + (direction_y * direction_y);
    if (!std::isfinite(magnitude_squared) || magnitude_squared <= 0.0001f) {
        return false;
    }

    const auto inverse_magnitude = 1.0f / std::sqrt(magnitude_squared);
    *direction_x_out = direction_x * inverse_magnitude;
    *direction_y_out = direction_y * inverse_magnitude;
    return std::isfinite(*direction_x_out) && std::isfinite(*direction_y_out);
}

bool OngoingCastNeedsNativeTargetActor(
    const ParticipantEntityBinding::OngoingCastState& ongoing) {
    if (ongoing.lane == ParticipantEntityBinding::OngoingCastState::Lane::PurePrimary) {
        return true;
    }

    // Only live-target channel handlers consume actor+0x298 during the native
    // tick. Earth's boulder is a world spell object; publishing a target actor
    // there changes the native projectile collision/damage path even though
    // aim and selection state still need to be refreshed while charging.
    return ongoing.uses_dispatcher_skill_id &&
           ongoing.requires_local_slot_native_tick &&
           SkillTracksLiveTargetDuringNativeTick(ResolveOngoingNativeTickSkillId(ongoing));
}

bool OngoingCastShouldPreserveAimAfterTargetLoss(
    const ParticipantEntityBinding::OngoingCastState& ongoing) {
    return ongoing.active &&
           OngoingCastNeedsNativeTargetActor(ongoing) &&
           ongoing.requires_local_slot_native_tick &&
           ongoing.have_aim_target;
}

bool WriteOngoingCastNativeTargetActor(
    uintptr_t actor_address,
    ParticipantEntityBinding::OngoingCastState* ongoing,
    uintptr_t target_actor_address) {
    if (actor_address == 0 || ongoing == nullptr || !OngoingCastNeedsNativeTargetActor(*ongoing)) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    if (!ongoing->current_target_actor_override_active) {
        ongoing->current_target_actor_before =
            memory.ReadFieldOr<uintptr_t>(actor_address, kActorCurrentTargetActorOffset, 0);
        ongoing->current_target_actor_override_active = true;
    }
    const bool target_pointer_written = memory.TryWriteField<uintptr_t>(
        actor_address,
        kActorCurrentTargetActorOffset,
        target_actor_address);

    if (OngoingCastNeedsNativeTargetHandle(*ongoing)) {
        std::uint8_t target_group = kTargetHandleGroupSentinel;
        std::uint16_t target_slot = kTargetHandleSlotSentinel;
        if (TryResolveSameWorldTargetHandle(
                actor_address,
                target_actor_address,
                &target_group,
                &target_slot)) {
            if (!ongoing->native_target_handle_override_active) {
                ongoing->native_target_group_before =
                    memory.ReadFieldOr<std::uint8_t>(
                        actor_address,
                        kActorSpellTargetGroupByteOffset,
                        kTargetHandleGroupSentinel);
                ongoing->native_target_slot_before =
                    memory.ReadFieldOr<std::uint16_t>(
                        actor_address,
                        kActorSpellTargetSlotShortOffset,
                        kTargetHandleSlotSentinel);
                ongoing->native_target_handle_override_active = true;
            }
            (void)memory.TryWriteField<std::uint8_t>(
                actor_address,
                kActorSpellTargetGroupByteOffset,
                target_group);
            (void)memory.TryWriteField<std::uint16_t>(
                actor_address,
                kActorSpellTargetSlotShortOffset,
                target_slot);
        } else if (ongoing->native_target_handle_override_active) {
            (void)memory.TryWriteField<std::uint8_t>(
                actor_address,
                kActorSpellTargetGroupByteOffset,
                kTargetHandleGroupSentinel);
            (void)memory.TryWriteField<std::uint16_t>(
                actor_address,
                kActorSpellTargetSlotShortOffset,
                kTargetHandleSlotSentinel);
        }
    }

    return target_pointer_written;
}

void ClearOngoingCastNativeTargetActor(
    uintptr_t actor_address,
    ParticipantEntityBinding::OngoingCastState* ongoing) {
    if (actor_address == 0 || ongoing == nullptr ||
        (!ongoing->current_target_actor_override_active &&
         !ongoing->native_target_handle_override_active)) {
        return;
    }
    if (ongoing->current_target_actor_override_active) {
        (void)ProcessMemory::Instance().TryWriteField<uintptr_t>(
            actor_address,
            kActorCurrentTargetActorOffset,
            0);
    }
    if (OngoingCastNeedsNativeTargetHandle(*ongoing) &&
        ongoing->native_target_handle_override_active) {
        (void)ProcessMemory::Instance().TryWriteField<std::uint8_t>(
            actor_address,
            kActorSpellTargetGroupByteOffset,
            kTargetHandleGroupSentinel);
        (void)ProcessMemory::Instance().TryWriteField<std::uint16_t>(
            actor_address,
            kActorSpellTargetSlotShortOffset,
            kTargetHandleSlotSentinel);
    }
}

void RestoreOngoingCastNativeTargetActor(
    uintptr_t actor_address,
    const ParticipantEntityBinding::OngoingCastState& ongoing) {
    if (actor_address == 0 ||
        (!ongoing.current_target_actor_override_active &&
         !ongoing.native_target_handle_override_active)) {
        return;
    }
    if (ongoing.current_target_actor_override_active) {
        (void)ProcessMemory::Instance().TryWriteField<uintptr_t>(
            actor_address,
            kActorCurrentTargetActorOffset,
            ongoing.current_target_actor_before);
    }
    if (ongoing.native_target_handle_override_active) {
        (void)ProcessMemory::Instance().TryWriteField<std::uint8_t>(
            actor_address,
            kActorSpellTargetGroupByteOffset,
            ongoing.native_target_group_before);
        (void)ProcessMemory::Instance().TryWriteField<std::uint16_t>(
            actor_address,
            kActorSpellTargetSlotShortOffset,
            ongoing.native_target_slot_before);
    }
}

bool RefreshWizardBindingTargetFacing(ParticipantEntityBinding* binding) {
    if (binding == nullptr || binding->actor_address == 0 || binding->facing_target_actor_address == 0) {
        return false;
    }

    float heading = 0.0f;
    float target_x = 0.0f;
    float target_y = 0.0f;
    if (!TryComputeActorAimTowardTargetFromOrigin(
            binding->actor_address,
            binding->facing_target_actor_address,
            binding->stock_tick_facing_origin_valid,
            binding->stock_tick_facing_origin_x,
            binding->stock_tick_facing_origin_y,
            &heading,
            &target_x,
            &target_y)) {
        binding->facing_target_actor_address = 0;
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    (void)memory.TryWriteField(binding->actor_address, kActorAimTargetXOffset, target_x);
    (void)memory.TryWriteField(binding->actor_address, kActorAimTargetYOffset, target_y);
    (void)memory.TryWriteField<std::uint32_t>(binding->actor_address, kActorAimTargetAux0Offset, 0);
    (void)memory.TryWriteField<std::uint32_t>(binding->actor_address, kActorAimTargetAux1Offset, 0);
    binding->facing_heading_value = heading;
    binding->facing_heading_valid = true;
    return true;
}

bool RefreshOngoingCastAimFromFacingTarget(
    ParticipantEntityBinding* binding,
    ParticipantEntityBinding::OngoingCastState* ongoing) {
    if (binding == nullptr || ongoing == nullptr) {
        return false;
    }

    auto target_actor_address = ResolveOngoingCastNativeTargetActor(binding, *ongoing);
    if (target_actor_address == 0) {
        ongoing->selection_target_seed_active = false;
        if (!OngoingCastShouldPreserveAimAfterTargetLoss(*ongoing)) {
            ongoing->have_aim_heading = false;
            ongoing->have_aim_target = false;
        }
        ClearOngoingCastNativeTargetActor(binding->actor_address, ongoing);
        return false;
    }

    float heading = 0.0f;
    float target_x = 0.0f;
    float target_y = 0.0f;
    if (!TryComputeActorAimTowardTargetFromOrigin(
            binding->actor_address,
            target_actor_address,
            binding->stock_tick_facing_origin_valid,
            binding->stock_tick_facing_origin_x,
            binding->stock_tick_facing_origin_y,
            &heading,
            &target_x,
            &target_y)) {
        if (binding->facing_target_actor_address == target_actor_address) {
            binding->facing_target_actor_address = 0;
        }
        if (ongoing->target_actor_address == target_actor_address) {
            ongoing->target_actor_address = 0;
        }
        ongoing->selection_target_seed_active = false;
        if (!OngoingCastShouldPreserveAimAfterTargetLoss(*ongoing)) {
            ongoing->have_aim_heading = false;
            ongoing->have_aim_target = false;
        }
        ClearOngoingCastNativeTargetActor(binding->actor_address, ongoing);
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    ongoing->targetless_ticks_waiting = 0;
    binding->facing_target_actor_address = target_actor_address;
    ongoing->target_actor_address = target_actor_address;
    const auto target_group =
        memory.ReadFieldOr<std::uint8_t>(
            target_actor_address,
            kActorSlotOffset,
            kTargetHandleGroupSentinel);
    const auto target_slot =
        memory.ReadFieldOr<std::uint16_t>(
            target_actor_address,
            kActorWorldSlotOffset,
            kTargetHandleSlotSentinel);
    if (target_group != kTargetHandleGroupSentinel &&
        target_slot != kTargetHandleSlotSentinel) {
        ongoing->selection_target_seed_active = true;
        ongoing->selection_target_group_seed = target_group;
        ongoing->selection_target_slot_seed = target_slot;
        ongoing->selection_target_hold_ticks = 60;
        if (ongoing->selection_state_pointer != 0) {
            (void)memory.TryWriteField<std::uint8_t>(
                ongoing->selection_state_pointer,
                0x04,
                target_group);
            (void)memory.TryWriteField<std::uint16_t>(
                ongoing->selection_state_pointer,
                0x06,
                target_slot);
            (void)memory.TryWriteField<std::int32_t>(
                ongoing->selection_state_pointer,
                0x08,
                ongoing->selection_target_hold_ticks);
            (void)memory.TryWriteField<std::int32_t>(ongoing->selection_state_pointer, 0x0C, 0);
            (void)memory.TryWriteField<std::int32_t>(ongoing->selection_state_pointer, 0x10, 0);
            (void)memory.TryWriteField<std::int32_t>(ongoing->selection_state_pointer, 0x14, 0);
        }
    } else {
        ongoing->selection_target_seed_active = false;
    }

    binding->facing_heading_value = heading;
    binding->facing_heading_valid = true;
    ongoing->aim_heading = heading;
    ongoing->have_aim_heading = true;
    ongoing->aim_target_x = target_x;
    ongoing->aim_target_y = target_y;
    ongoing->have_aim_target = true;
    ApplyWizardActorFacingState(binding->actor_address, heading);
    (void)WriteOngoingCastNativeTargetActor(
        binding->actor_address,
        ongoing,
        target_actor_address);

    if (ongoing->selection_state_pointer != 0 && ongoing->startup_in_progress) {
        float startup_input_x = 0.0f;
        float startup_input_y = 0.0f;
        auto have_startup_input =
            TryGetBindingMovementInputVector(*binding, &startup_input_x, &startup_input_y);
        if (!have_startup_input) {
            const auto actor_x = memory.ReadFieldOr<float>(
                binding->actor_address,
                kActorPositionXOffset,
                0.0f);
            const auto actor_y = memory.ReadFieldOr<float>(
                binding->actor_address,
                kActorPositionYOffset,
                0.0f);
            const auto dx = target_x - actor_x;
            const auto dy = target_y - actor_y;
            const auto distance = std::sqrt((dx * dx) + (dy * dy));
            if (std::isfinite(distance) && distance > 0.0001f) {
                startup_input_x = dx / distance;
                startup_input_y = dy / distance;
                have_startup_input = true;
            }
        }
        if (have_startup_input) {
            // Stock pure-primary startup needs a non-zero movement/control vector.
            // Prefer the follow lane so attacking does not steer the bot away from
            // the player; only fall back to attack-facing when the bot is idle.
            (void)memory.TryWriteValue<float>(
                ongoing->selection_state_pointer + kActorControlBrainMoveInputXOffset,
                startup_input_x);
            (void)memory.TryWriteValue<float>(
                ongoing->selection_state_pointer + kActorControlBrainMoveInputYOffset,
                startup_input_y);
        }
    }
    return true;
}
