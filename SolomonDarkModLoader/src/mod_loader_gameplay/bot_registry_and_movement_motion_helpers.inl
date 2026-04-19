float ReadResolvedGameFloatOr(uintptr_t absolute_address, float fallback) {
    auto& memory = ProcessMemory::Instance();
    const auto resolved_address = memory.ResolveGameAddressOrZero(absolute_address);
    if (resolved_address == 0) {
        return fallback;
    }

    return memory.ReadValueOr<float>(resolved_address, fallback);
}

float ReadResolvedGameDoubleAsFloatOr(uintptr_t absolute_address, float fallback) {
    auto& memory = ProcessMemory::Instance();
    const auto resolved_address = memory.ResolveGameAddressOrZero(absolute_address);
    if (resolved_address == 0) {
        return fallback;
    }

    return static_cast<float>(memory.ReadValueOr<double>(resolved_address, static_cast<double>(fallback)));
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

void StopWizardBotActorMotion(uintptr_t actor_address) {
    if (actor_address == 0) {
        return;
    }

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

void ApplyObservedBotAnimationState(ParticipantEntityBinding* binding, uintptr_t actor_address, bool moving) {
    if (binding == nullptr || actor_address == 0 || binding->kind != ParticipantEntityBinding::Kind::StandaloneWizard) {
        return;
    }

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
    const auto per_tick_speed_2d4 = memory.ReadFieldOr<float>(actor_address, kActorPerTickSpeedOffset, 0.0f);
    const auto dur_0x1BC = memory.ReadFieldOr<float>(actor_address, 0x1BC, 0.0f);
    const auto accel_0x1E0 = memory.ReadFieldOr<float>(actor_address, 0x1E0, 0.0f);
    const auto blend_0x268 = memory.ReadFieldOr<float>(actor_address, 0x268, 0.0f);
    auto player_per_tick_speed_2d4 = 0.0f;
    uintptr_t player_probe_scene_address = 0;
    uintptr_t player_probe_actor_address = 0;
    if (TryResolveCurrentGameplayScene(&player_probe_scene_address) &&
        player_probe_scene_address != 0 &&
        TryResolvePlayerActorForSlot(player_probe_scene_address, 0, &player_probe_actor_address) &&
        player_probe_actor_address != 0) {
        player_per_tick_speed_2d4 =
            memory.ReadFieldOr<float>(player_probe_actor_address, kActorPerTickSpeedOffset, 0.0f);
    }
    Log(
        "[bots] standalone_mv bot=" + std::to_string(binding->bot_id) +
        " before=(" + std::to_string(position_before_x) + "," + std::to_string(position_before_y) + ")" +
        " after=(" + std::to_string(position_after_x) + "," + std::to_string(position_after_y) + ")" +
        " d=" + std::to_string(d) +
        " dir=(" + std::to_string(direction_x) + "," + std::to_string(direction_y) + ")" +
        " 0x74=" + std::to_string(scale_0x74) +
        " 0x2D4=" + std::to_string(per_tick_speed_2d4) +
        " player_0x2D4=" + std::to_string(player_per_tick_speed_2d4) +
        " 0x1BC=" + std::to_string(dur_0x1BC) +
        " 0x1E0=" + std::to_string(accel_0x1E0) +
        " 0x268=" + std::to_string(blend_0x268) +
        " path=" + std::string(path_label != nullptr ? path_label : ""));
}

void LogLocalPlayerAnimationProbe() {
    uintptr_t gameplay_address = 0;
    uintptr_t actor_address = 0;
    if (!TryResolveCurrentGameplayScene(&gameplay_address) || gameplay_address == 0 ||
        !TryResolvePlayerActorForSlot(gameplay_address, 0, &actor_address) ||
        actor_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    const auto current_x = memory.ReadFieldOr<float>(actor_address, kActorPositionXOffset, 0.0f);
    const auto current_y = memory.ReadFieldOr<float>(actor_address, kActorPositionYOffset, 0.0f);

    bool moving_now = false;
    if (g_local_player_animation_probe_has_last_position) {
        const auto delta_x = current_x - g_local_player_animation_probe_last_x;
        const auto delta_y = current_y - g_local_player_animation_probe_last_y;
        moving_now = std::sqrt((delta_x * delta_x) + (delta_y * delta_y)) > 0.01f;
    }

    g_local_player_animation_probe_last_x = current_x;
    g_local_player_animation_probe_last_y = current_y;
    g_local_player_animation_probe_has_last_position = true;
    CaptureObservedPlayerAnimationDriveProfile(actor_address, moving_now);
}

