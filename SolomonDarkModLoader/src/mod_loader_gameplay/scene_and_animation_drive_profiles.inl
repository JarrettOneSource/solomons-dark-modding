bool CaptureActorAnimationDriveProfile(
    uintptr_t actor_address,
    ObservedActorAnimationDriveProfile* profile) {
    if (actor_address == 0 || profile == nullptr) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    if (!memory.TryRead(
            actor_address + kActorAnimationConfigBlockOffset,
            profile->config_bytes.data(),
            profile->config_bytes.size())) {
        return false;
    }

    profile->valid = true;
    profile->walk_cycle_primary =
        memory.ReadFieldOr<float>(actor_address, kActorWalkCyclePrimaryOffset, 0.0f);
    profile->walk_cycle_secondary =
        memory.ReadFieldOr<float>(actor_address, kActorWalkCycleSecondaryOffset, 0.0f);
    profile->render_drive_stride =
        memory.ReadFieldOr<float>(actor_address, kActorRenderDriveStrideScaleOffset, 0.0f);
    profile->render_advance_rate =
        memory.ReadFieldOr<float>(actor_address, kActorRenderAdvanceRateOffset, 0.0f);
    return true;
}

bool ApplyActorAnimationDriveProfile(
    uintptr_t actor_address,
    const ObservedActorAnimationDriveProfile& profile) {
    if (actor_address == 0 || !profile.valid) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    // The captured block starts at actor+0x158, but actor+0x160 is not a
    // locomotion flag. Non-zero values there drive cast/death branches, so
    // live movement must only replay the vector prefix before that byte.
    const auto config_prefix_size =
        kActorAnimationDriveStateByteOffset > kActorAnimationConfigBlockOffset
            ? (std::min)(
                  profile.config_bytes.size(),
                  kActorAnimationDriveStateByteOffset - kActorAnimationConfigBlockOffset)
            : std::size_t{0};
    if (config_prefix_size == 0) {
        return false;
    }

    const auto config_written = memory.TryWrite(
        actor_address + kActorAnimationConfigBlockOffset,
        profile.config_bytes.data(),
        config_prefix_size);
    if (!config_written) {
        return false;
    }

    (void)memory.TryWriteField(
        actor_address,
        kActorRenderAdvanceRateOffset,
        profile.render_advance_rate);
    return true;
}

void ClearLiveWizardActorAnimationDriveState(uintptr_t actor_address) {
    if (actor_address == 0) {
        return;
    }

    (void)ProcessMemory::Instance().TryWriteField<std::uint8_t>(
        actor_address,
        kActorAnimationDriveStateByteOffset,
        0);
}

void CaptureObservedPlayerAnimationDriveProfile(uintptr_t actor_address, bool moving_now) {
    ObservedActorAnimationDriveProfile profile;
    if (!CaptureActorAnimationDriveProfile(actor_address, &profile)) {
        return;
    }

    if (moving_now) {
        g_observed_moving_animation_profile = profile;
    } else {
        g_observed_idle_animation_profile = profile;
    }
}

const ObservedActorAnimationDriveProfile* SelectObservedAnimationDriveProfile(bool moving) {
    if (moving && g_observed_moving_animation_profile.valid) {
        return &g_observed_moving_animation_profile;
    }
    if (!moving && g_observed_idle_animation_profile.valid) {
        return &g_observed_idle_animation_profile;
    }
    if (g_observed_idle_animation_profile.valid) {
        return &g_observed_idle_animation_profile;
    }
    if (g_observed_moving_animation_profile.valid) {
        return &g_observed_moving_animation_profile;
    }
    return nullptr;
}

const ObservedActorAnimationDriveProfile* SelectStandaloneWizardAnimationDriveProfile(
    const ParticipantEntityBinding* binding,
    bool moving) {
    if (binding == nullptr) {
        return nullptr;
    }

    const auto* idle_profile = &binding->standalone_idle_animation_drive_profile;
    const auto* moving_profile = &binding->standalone_moving_animation_drive_profile;
    if (moving && moving_profile->valid) {
        return moving_profile;
    }
    if (!moving && idle_profile->valid) {
        return idle_profile;
    }
    if (idle_profile->valid) {
        return idle_profile;
    }
    if (moving_profile->valid) {
        return moving_profile;
    }
    return nullptr;
}

void SeedStandaloneWizardAnimationDriveProfiles(ParticipantEntityBinding* binding, uintptr_t actor_address) {
    if (binding == nullptr) {
        return;
    }

    binding->standalone_idle_animation_drive_profile = ObservedActorAnimationDriveProfile{};
    binding->standalone_moving_animation_drive_profile = ObservedActorAnimationDriveProfile{};

    ObservedActorAnimationDriveProfile actor_profile;
    if (CaptureActorAnimationDriveProfile(actor_address, &actor_profile)) {
        binding->standalone_idle_animation_drive_profile = actor_profile;
    } else if (g_observed_idle_animation_profile.valid) {
        binding->standalone_idle_animation_drive_profile = g_observed_idle_animation_profile;
    }

    if (g_observed_moving_animation_profile.valid) {
        binding->standalone_moving_animation_drive_profile = g_observed_moving_animation_profile;
    } else if (binding->standalone_idle_animation_drive_profile.valid) {
        binding->standalone_moving_animation_drive_profile =
            binding->standalone_idle_animation_drive_profile;
    } else if (g_observed_idle_animation_profile.valid) {
        binding->standalone_moving_animation_drive_profile = g_observed_idle_animation_profile;
    }

    if (!binding->standalone_idle_animation_drive_profile.valid &&
        binding->standalone_moving_animation_drive_profile.valid) {
        binding->standalone_idle_animation_drive_profile =
            binding->standalone_moving_animation_drive_profile;
    }
}

void ApplyStandaloneWizardAnimationDriveProfile(
    const ParticipantEntityBinding* binding,
    uintptr_t actor_address,
    bool moving) {
    if (actor_address == 0) {
        return;
    }

    if (const auto* profile = SelectStandaloneWizardAnimationDriveProfile(binding, moving);
        profile != nullptr) {
        (void)ApplyActorAnimationDriveProfile(actor_address, *profile);
    }
}

void ApplyStandaloneWizardDynamicAnimationState(
    const ParticipantEntityBinding* binding,
    uintptr_t actor_address) {
    if (binding == nullptr || actor_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    (void)memory.TryWriteField(actor_address, kActorWalkCyclePrimaryOffset, binding->dynamic_walk_cycle_primary);
    (void)memory.TryWriteField(actor_address, kActorWalkCycleSecondaryOffset, binding->dynamic_walk_cycle_secondary);
}

void SeedBotAnimationDriveProfile(uintptr_t source_actor_address, uintptr_t destination_actor_address) {
    if (source_actor_address == 0 || destination_actor_address == 0) {
        return;
    }

    ObservedActorAnimationDriveProfile profile;
    if (!CaptureActorAnimationDriveProfile(source_actor_address, &profile)) {
        return;
    }

    (void)ApplyActorAnimationDriveProfile(destination_actor_address, profile);
}

void ApplyActorAnimationDriveState(uintptr_t actor_address, bool moving) {
    if (actor_address == 0) {
        return;
    }

    if (const auto* observed_profile = SelectObservedAnimationDriveProfile(moving);
        observed_profile != nullptr) {
        (void)ApplyActorAnimationDriveProfile(actor_address, *observed_profile);
    }

    auto& memory = ProcessMemory::Instance();
    ClearLiveWizardActorAnimationDriveState(actor_address);

    if (!moving) {
        (void)memory.TryWriteField(actor_address, kActorAnimationMoveDurationTicksOffset, 0);
        return;
    }

    auto move_duration =
        memory.ReadFieldOr<std::int32_t>(actor_address, kActorAnimationMoveDurationTicksOffset, 0);
    if (move_duration < 1) {
        move_duration = 1;
    } else if (move_duration < (std::numeric_limits<std::int32_t>::max)()) {
        ++move_duration;
    }
    (void)memory.TryWriteField(actor_address, kActorAnimationMoveDurationTicksOffset, move_duration);
}

float NormalizeWizardActorHeadingForWrite(float heading_degrees) {
    if (!std::isfinite(heading_degrees)) {
        return 0.0f;
    }

    heading_degrees = std::fmod(heading_degrees, 360.0f);
    if (heading_degrees < 0.0f) {
        heading_degrees += 360.0f;
    }
    return heading_degrees;
}

void ApplyWizardActorFacingState(uintptr_t actor_address, float heading_degrees) {
    if (actor_address == 0) {
        return;
    }

    const auto heading = NormalizeWizardActorHeadingForWrite(heading_degrees);
    auto& memory = ProcessMemory::Instance();
    (void)memory.TryWriteField(actor_address, kActorHeadingOffset, heading);

    const auto control_brain_address =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorAnimationSelectionStateOffset, 0);
    if (control_brain_address == 0) {
        return;
    }

    (void)memory.TryWriteValue<float>(
        control_brain_address + kActorControlBrainHeadingAccumulatorOffset,
        heading);
    (void)memory.TryWriteValue<float>(
        control_brain_address + kActorControlBrainDesiredFacingOffset,
        heading);
    (void)memory.TryWriteValue<float>(
        control_brain_address + kActorControlBrainDesiredFacingSmoothedOffset,
        heading);
}

bool ApplyWizardBindingFacingState(const ParticipantEntityBinding* binding, uintptr_t actor_address) {
    if (binding == nullptr || actor_address == 0 || !binding->facing_heading_valid) {
        return false;
    }

    ApplyWizardActorFacingState(actor_address, binding->facing_heading_value);
    return true;
}

void ResetStandaloneWizardControlBrain(uintptr_t actor_address) {
    if (actor_address == 0) {
        return;
    }

    constexpr int kSuppressedSelectionRetargetTicks = 60;
    auto& memory = ProcessMemory::Instance();
    const auto control_brain_address =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorAnimationSelectionStateOffset, 0);
    if (control_brain_address == 0) {
        return;
    }

    (void)memory.TryWriteValue<std::int8_t>(control_brain_address + kActorControlBrainTargetSlotOffset, -1);
    (void)memory.TryWriteValue<std::uint16_t>(
        control_brain_address + kActorControlBrainTargetHandleOffset,
        static_cast<std::uint16_t>(0xFFFF));
    (void)memory.TryWriteValue<int>(
        control_brain_address + kActorControlBrainRetargetTicksOffset,
        kSuppressedSelectionRetargetTicks);
    (void)memory.TryWriteValue<int>(control_brain_address + kActorControlBrainActionCooldownTicksOffset, 0);
    (void)memory.TryWriteValue<int>(control_brain_address + kActorControlBrainActionBurstTicksOffset, 0);
    (void)memory.TryWriteValue<int>(control_brain_address + kActorControlBrainHeadingLockTicksOffset, 0);
    (void)memory.TryWriteValue<float>(control_brain_address + kActorControlBrainHeadingAccumulatorOffset, 0.0f);
    (void)memory.TryWriteValue<float>(control_brain_address + kActorControlBrainPursuitRangeOffset, 0.0f);
    (void)memory.TryWriteValue<std::uint8_t>(control_brain_address + kActorControlBrainFollowLeaderOffset, 0);
    (void)memory.TryWriteValue<float>(control_brain_address + kActorControlBrainDesiredFacingOffset, 0.0f);
    (void)memory.TryWriteValue<float>(
        control_brain_address + kActorControlBrainDesiredFacingSmoothedOffset,
        0.0f);
    (void)memory.TryWriteValue<float>(control_brain_address + kActorControlBrainMoveInputXOffset, 0.0f);
    (void)memory.TryWriteValue<float>(control_brain_address + kActorControlBrainMoveInputYOffset, 0.0f);
}

void ApplyStandaloneWizardPuppetDriveState(
    const ParticipantEntityBinding* binding,
    uintptr_t actor_address,
    bool moving) {
    if (actor_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    const auto control_brain_address =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorAnimationSelectionStateOffset, 0);
    if (!moving) {
        (void)memory.TryWriteField(actor_address, kActorAnimationMoveDurationTicksOffset, 0);
    } else {
        auto move_duration =
            memory.ReadFieldOr<std::int32_t>(actor_address, kActorAnimationMoveDurationTicksOffset, 0);
        if (move_duration < 1) {
            move_duration = 1;
        } else if (move_duration < (std::numeric_limits<std::int32_t>::max)()) {
            ++move_duration;
        }
        (void)memory.TryWriteField(actor_address, kActorAnimationMoveDurationTicksOffset, move_duration);
    }

    ResetStandaloneWizardControlBrain(actor_address);
    if (control_brain_address == 0 || binding == nullptr || !moving) {
        return;
    }

    float move_input_x = binding->direction_x;
    float move_input_y = binding->direction_y;
    const auto magnitude = std::sqrt((move_input_x * move_input_x) + (move_input_y * move_input_y));
    if (magnitude > 0.0001f) {
        move_input_x /= magnitude;
        move_input_y /= magnitude;
    } else {
        move_input_x = 0.0f;
        move_input_y = 0.0f;
    }

    const auto desired_heading =
        binding->facing_heading_valid
            ? binding->facing_heading_value
            : (binding->desired_heading_valid
                   ? binding->desired_heading
                   : memory.ReadFieldOr<float>(actor_address, kActorHeadingOffset, 0.0f));
    (void)memory.TryWriteValue<float>(control_brain_address + kActorControlBrainHeadingAccumulatorOffset, desired_heading);
    (void)memory.TryWriteValue<float>(control_brain_address + kActorControlBrainDesiredFacingOffset, desired_heading);
    (void)memory.TryWriteValue<float>(
        control_brain_address + kActorControlBrainDesiredFacingSmoothedOffset,
        desired_heading);
    (void)memory.TryWriteValue<float>(control_brain_address + kActorControlBrainMoveInputXOffset, move_input_x);
    (void)memory.TryWriteValue<float>(control_brain_address + kActorControlBrainMoveInputYOffset, move_input_y);
}
