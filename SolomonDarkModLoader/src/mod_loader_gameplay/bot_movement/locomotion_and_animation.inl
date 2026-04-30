bool RefreshAndApplyWizardBindingFacingState(ParticipantEntityBinding* binding, uintptr_t actor_address) {
    if (binding == nullptr || actor_address == 0) {
        return false;
    }

    if (binding->ongoing_cast.active &&
        OngoingCastShouldRefreshNativeTargetState(binding->ongoing_cast)) {
        (void)RefreshOngoingCastAimFromFacingTarget(binding, &binding->ongoing_cast);
    }
    (void)RefreshWizardBindingTargetFacing(binding);
    return ApplyWizardBindingFacingState(binding, actor_address);
}

void QuiesceDeadWizardBinding(ParticipantEntityBinding* binding) {
    if (binding == nullptr) {
        return;
    }

    binding->controller_state = multiplayer::BotControllerState::Idle;
    binding->movement_active = false;
    binding->last_movement_displacement = 0.0f;
    binding->has_target = false;
    binding->direction_x = 0.0f;
    binding->direction_y = 0.0f;
    binding->desired_heading_valid = false;
    binding->desired_heading = 0.0f;
    binding->target_x = 0.0f;
    binding->target_y = 0.0f;
    binding->distance_to_target = 0.0f;
    binding->path_active = false;
    binding->path_failed = false;
    binding->path_waypoint_index = 0;
    binding->current_waypoint_x = 0.0f;
    binding->current_waypoint_y = 0.0f;
    binding->path_waypoints.clear();
    binding->facing_heading_valid = false;
    binding->facing_target_actor_address = 0;
    binding->stock_tick_facing_origin_valid = false;
    binding->stock_tick_facing_origin_x = 0.0f;
    binding->stock_tick_facing_origin_y = 0.0f;
}

void AdvanceStandaloneWizardWalkCycleState(
    ParticipantEntityBinding* binding,
    float displacement_distance) {
    if (binding == nullptr || !std::isfinite(displacement_distance) || displacement_distance <= 0.0001f) {
        return;
    }

    const auto primary_divisor =
        (std::max)(0.0001f, ReadResolvedGameDoubleAsFloatOr(kActorWalkCyclePrimaryDivisorGlobal, 1.0f));
    const auto secondary_divisor =
        (std::max)(0.0001f, ReadResolvedGameDoubleAsFloatOr(kActorWalkCycleSecondaryDivisorGlobal, 1.0f));
    const auto primary_wrap_threshold =
        (std::max)(0.0001f, ReadResolvedGameFloatOr(kActorWalkCyclePrimaryWrapThresholdGlobal, 1.0f));
    const auto secondary_wrap_threshold =
        (std::max)(0.0001f, ReadResolvedGameFloatOr(kActorWalkCycleSecondaryWrapThresholdGlobal, 1.0f));
    const auto secondary_wrap_step =
        (std::max)(0.0001f, ReadResolvedGameDoubleAsFloatOr(kActorWalkCycleSecondaryWrapStepGlobal, secondary_wrap_threshold));
    const auto stride_step = ReadResolvedGameDoubleAsFloatOr(kActorWalkCycleStrideStepGlobal, 1.0f);

    auto primary = binding->dynamic_walk_cycle_primary;
    auto secondary = binding->dynamic_walk_cycle_secondary;

    primary += displacement_distance / primary_divisor;
    if (std::isfinite(primary) && primary_wrap_threshold > 0.0001f) {
        primary = std::fmod(primary, primary_wrap_threshold);
        if (primary < 0.0f) {
            primary += primary_wrap_threshold;
        }
    }

    secondary += displacement_distance / secondary_divisor;
    if (std::isfinite(secondary) && secondary_wrap_threshold > 0.0001f) {
        while (secondary >= secondary_wrap_threshold) {
            secondary -= secondary_wrap_step;
        }
        while (secondary < 0.0f) {
            secondary += secondary_wrap_step;
        }
    }

    binding->dynamic_walk_cycle_primary = primary;
    binding->dynamic_walk_cycle_secondary = secondary;
    binding->dynamic_render_drive_stride = stride_step;
    binding->dynamic_render_advance_rate = displacement_distance;
    binding->dynamic_render_drive_move_blend = 1.0f;
    binding->dynamic_render_advance_phase = primary;
}

void ClearWizardBotLocomotionInputs(uintptr_t actor_address) {
    if (!IsParticipantActorMemoryFreshWritable(actor_address)) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    (void)memory.TryWriteField(actor_address, kActorAnimationConfigBlockOffset, 0.0f);
    (void)memory.TryWriteField(actor_address, kActorAnimationDriveParameterOffset, 0.0f);
    (void)memory.TryWriteField(actor_address, kActorWalkCyclePrimaryOffset, 0.0f);
    (void)memory.TryWriteField(actor_address, kActorWalkCycleSecondaryOffset, 0.0f);
    (void)memory.TryWriteField(actor_address, kActorRenderDriveStrideScaleOffset, 0.0f);
    (void)memory.TryWriteField(actor_address, kActorRenderAdvanceRateOffset, 0.0f);
    (void)memory.TryWriteField(actor_address, kActorRenderAdvancePhaseOffset, 0.0f);
    (void)memory.TryWriteField(actor_address, kActorRenderDriveMoveBlendOffset, 0.0f);
}

void StopWizardBotActorMotion(uintptr_t actor_address) {
    if (actor_address == 0) {
        return;
    }

    // Standalone clone-rail bots seed the stock walk accumulators at +0x158/+0x15C
    // so our loader-owned MoveStep can mirror player movement. Once loader
    // movement stops, those accumulators must be cleared immediately; otherwise
    // the stock PlayerActorTick keeps consuming the stale vector and slides the
    // clone even while our controller is idle.
    ClearWizardBotLocomotionInputs(actor_address);

    std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
    if (auto* binding = FindParticipantEntityForActor(actor_address);
        binding != nullptr && binding->kind == ParticipantEntityBinding::Kind::StandaloneWizard) {
        ApplyObservedBotAnimationState(binding, actor_address, false);
        binding->dynamic_walk_cycle_primary = 0.0f;
        binding->dynamic_walk_cycle_secondary = 0.0f;
        binding->dynamic_render_drive_stride = 0.0f;
        binding->dynamic_render_advance_rate = 0.0f;
        binding->dynamic_render_advance_phase = 0.0f;
        binding->dynamic_render_drive_move_blend = 0.0f;
        ApplyStandaloneWizardDynamicAnimationState(binding, actor_address);
        return;
    }

    ApplyActorAnimationDriveState(actor_address, false);
}

void StopDeadWizardBotActorMotion(uintptr_t actor_address) {
    if (actor_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    // Dead bots are deliberately moved onto the player-family alternate/corpse
    // drive branch. That branch can look wrong for living idle bots, but it is
    // the stable "body on the ground" pose we want after HP reaches zero.
    // Keep the rest of the drive inputs zero so the actor remains inert.
    ClearWizardBotLocomotionInputs(actor_address);
    (void)memory.TryWriteField(
        actor_address,
        kActorAnimationDriveStateByteOffset,
        kDeadWizardBotCorpseDriveState);
    (void)memory.TryWriteField(actor_address, kActorAnimationMoveDurationTicksOffset, 0);
    (void)memory.TryWriteField(actor_address, kActorMoveStepScaleOffset, 0.0f);
    ResetStandaloneWizardControlBrain(actor_address);

    std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
    if (auto* binding = FindParticipantEntityForActor(actor_address);
        binding != nullptr && binding->kind == ParticipantEntityBinding::Kind::StandaloneWizard) {
        binding->dynamic_walk_cycle_primary = 0.0f;
        binding->dynamic_walk_cycle_secondary = 0.0f;
        binding->dynamic_render_drive_stride = 0.0f;
        binding->dynamic_render_advance_rate = 0.0f;
        binding->dynamic_render_advance_phase = 0.0f;
        binding->dynamic_render_drive_move_blend = 0.0f;
        ApplyStandaloneWizardDynamicAnimationState(binding, actor_address);
    }
}

void ApplyObservedBotAnimationState(ParticipantEntityBinding* binding, uintptr_t actor_address, bool moving) {
    if (binding == nullptr || actor_address == 0 || binding->kind != ParticipantEntityBinding::Kind::StandaloneWizard) {
        return;
    }

    ClearLiveWizardActorAnimationDriveState(actor_address);
    ApplyStandaloneWizardAnimationDriveProfile(binding, actor_address, moving);
    ApplyStandaloneWizardPuppetDriveState(binding, actor_address, moving);
    ApplyStandaloneWizardDynamicAnimationState(binding, actor_address);

    const auto desired_state_id = ResolveProfileSelectionState(binding->character_profile);
    if (TryWriteActorAnimationStateIdDirect(actor_address, desired_state_id)) {
        binding->last_applied_animation_state_id = desired_state_id;
        return;
    }

    binding->last_applied_animation_state_id = ResolveActorAnimationStateId(actor_address);
}

void LogWizardBotMovementFrame(
    ParticipantEntityBinding* binding,
    uintptr_t actor_address,
    uintptr_t owner_address,
    uintptr_t movement_controller_address,
    float direction_x,
    float direction_y,
    float velocity_x,
    float velocity_y,
    float position_before_x,
    float position_before_y,
    float position_after_x,
    float position_after_y,
    const char* path_label) {
    (void)owner_address;
    (void)movement_controller_address;
    (void)velocity_x;
    (void)velocity_y;
    if constexpr (!kEnableWizardBotHotPathDiagnostics) {
        return;
    }
    if (binding == nullptr || actor_address == 0) {
        return;
    }
    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    (void)now_ms;
    auto& memory = ProcessMemory::Instance();
    const auto delta_x = position_after_x - position_before_x;
    const auto delta_y = position_after_y - position_before_y;
    const auto d = std::sqrt(delta_x * delta_x + delta_y * delta_y);
    const auto scale_0x74 = memory.ReadFieldOr<float>(actor_address, kActorMoveSpeedScaleOffset, 0.0f);
    const auto move_step_scale_0x218 =
        memory.ReadFieldOr<float>(actor_address, kActorMoveStepScaleOffset, 0.0f);
    const auto dir_x_0x158 =
        memory.ReadFieldOr<float>(actor_address, kActorAnimationConfigBlockOffset, 0.0f);
    const auto dir_y_0x15C =
        memory.ReadFieldOr<float>(actor_address, kActorAnimationDriveParameterOffset, 0.0f);
    Log(
        "[bots] standalone_mv bot=" + std::to_string(binding->bot_id) +
        " before=(" + std::to_string(position_before_x) + "," + std::to_string(position_before_y) + ")" +
        " after=(" + std::to_string(position_after_x) + "," + std::to_string(position_after_y) + ")" +
        " d=" + std::to_string(d) +
        " dir=(" + std::to_string(direction_x) + "," + std::to_string(direction_y) + ")" +
        " 0x74=" + std::to_string(scale_0x74) +
        " 0x218=" + std::to_string(move_step_scale_0x218) +
        " 0x158=" + std::to_string(dir_x_0x158) +
        " 0x15C=" + std::to_string(dir_y_0x15C) +
        " path=" + std::string(path_label != nullptr ? path_label : ""));
}
