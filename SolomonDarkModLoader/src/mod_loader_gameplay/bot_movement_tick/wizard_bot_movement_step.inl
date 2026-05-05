bool TryResolveWizardBotNativeMovementEnvelope(
    ParticipantEntityBinding* binding,
    uintptr_t actor_address,
    float* speed_cap,
    float* input_acceleration_divisor,
    float* velocity_damping,
    std::string* error_message) {
    if (binding == nullptr || actor_address == 0 ||
        speed_cap == nullptr ||
        input_acceleration_divisor == nullptr ||
        velocity_damping == nullptr) {
        if (error_message != nullptr) {
            *error_message = "Bot movement envelope requires a live actor.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto actor_movement_speed_multiplier =
        memory.ReadFieldOr<float>(actor_address, kActorMovementSpeedMultiplierOffset, 0.0f);
    const auto actor_move_speed_scale =
        memory.ReadFieldOr<float>(actor_address, kActorMoveSpeedScaleOffset, 0.0f);
    if (!std::isfinite(actor_movement_speed_multiplier) ||
        !std::isfinite(actor_move_speed_scale) ||
        actor_movement_speed_multiplier < 0.0f ||
        actor_move_speed_scale < 0.0f) {
        if (error_message != nullptr) {
            *error_message = "Bot actor has invalid native movement scalar fields.";
        }
        return false;
    }

    float progression_move_speed = 1.0f;
    if (IsStandaloneWizardKind(binding->kind) || IsGameplaySlotWizardKind(binding->kind)) {
        uintptr_t progression_address = 0;
        if (!TryResolveActorProgressionRuntime(actor_address, &progression_address) ||
            progression_address == 0 ||
            !memory.IsReadableRange(progression_address + kProgressionMoveSpeedOffset, sizeof(float))) {
            if (error_message != nullptr) {
                *error_message = "Bot movement requires the bot-owned progression runtime.";
            }
            return false;
        }
        progression_move_speed =
            memory.ReadFieldOr<float>(progression_address, kProgressionMoveSpeedOffset, 0.0f);
        if (!std::isfinite(progression_move_speed) || progression_move_speed < 0.0f) {
            if (error_message != nullptr) {
                *error_message = "Bot progression has invalid native move speed.";
            }
            return false;
        }
    }

    const auto speed_scalar =
        ReadResolvedGameDoubleAsFloatOr(kMovementSpeedScalarGlobal, 0.0f);
    const auto acceleration_divisor =
        ReadResolvedGameDoubleAsFloatOr(kMovementInputAccelerationDivisorGlobal, 0.0f);
    const auto damping =
        ReadResolvedGameDoubleAsFloatOr(kMovementVelocityDampingGlobal, 0.0f);
    if (!std::isfinite(speed_scalar) ||
        !std::isfinite(acceleration_divisor) ||
        !std::isfinite(damping) ||
        speed_scalar < 0.0f ||
        acceleration_divisor <= 0.0f ||
        damping < 0.0f) {
        if (error_message != nullptr) {
            *error_message = "Bot movement native scalar globals are unavailable.";
        }
        return false;
    }

    *speed_cap =
        actor_movement_speed_multiplier *
        actor_move_speed_scale *
        progression_move_speed *
        speed_scalar;
    if (!std::isfinite(*speed_cap) || *speed_cap < 0.0f) {
        if (error_message != nullptr) {
            *error_message = "Bot movement native speed cap is invalid.";
        }
        return false;
    }
    *input_acceleration_divisor = acceleration_divisor;
    *velocity_damping = damping;
    return true;
}

bool ApplyWizardBotMovementStep(ParticipantEntityBinding* binding, std::string* error_message) {
    if (binding == nullptr || binding->actor_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Bot actor is not materialized.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto actor_address = binding->actor_address;
    const auto live_world_address =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, binding->materialized_world_address);
    if (live_world_address != 0 && binding->materialized_world_address != live_world_address) {
        binding->materialized_world_address = live_world_address;
    }
    if (IsStandaloneWizardKind(binding->kind)) {
        (void)EnsureStandaloneWizardWorldOwner(
            actor_address,
            live_world_address,
            "movement_step",
            nullptr);
    }
    const auto magnitude = std::sqrt(
        binding->direction_x * binding->direction_x + binding->direction_y * binding->direction_y);

    const bool cast_active = binding->ongoing_cast.active;
    if (!binding->movement_active || magnitude <= 0.0001f) {
        binding->last_movement_displacement = 0.0f;
        binding->native_movement_accumulator_x = 0.0f;
        binding->native_movement_accumulator_y = 0.0f;
        if (cast_active) {
            // Continuous casts own the attack animation/control lane while they
            // are alive. Clear only stale locomotion inputs so the bot does not
            // slide; do not force the broader idle animation state over the
            // native cast pose.
            ClearWizardBotMovementVectorInputs(actor_address);
        } else {
            ApplyObservedBotAnimationState(binding, actor_address, false);
            StopWizardBotActorMotion(binding->actor_address);
        }
        (void)ApplyWizardBindingFacingState(binding, actor_address);
        PublishParticipantGameplaySnapshot(*binding);
        return true;
    }

    float direction_x = binding->direction_x / magnitude;
    float direction_y = binding->direction_y / magnitude;

    const auto position_before_x = memory.ReadFieldOr<float>(actor_address, kActorPositionXOffset, 0.0f);
    const auto position_before_y = memory.ReadFieldOr<float>(actor_address, kActorPositionYOffset, 0.0f);
    const auto owner_address =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, 0);
    const auto movement_controller_address =
        live_world_address != 0 ? (live_world_address + kActorOwnerMovementControllerOffset) : 0;
    const auto move_step_address =
        ProcessMemory::Instance().ResolveGameAddressOrZero(kPlayerActorMoveStep);
    auto* actor_animation_advance =
        GetX86HookTrampoline<ActorAnimationAdvanceFn>(g_gameplay_keyboard_injection.actor_animation_advance_hook);
    const auto advance_actor_animation = [&](uintptr_t address) {
        if (actor_animation_advance == nullptr || address == 0) {
            return;
        }

        __try {
            actor_animation_advance(reinterpret_cast<void*>(address));
        } __except (EXCEPTION_EXECUTE_HANDLER) {
        }
    };
    // Bot movement mirrors the stock player path in PlayerActorTick (FUN_00548B00)
    // around 0x005494C4, 0x0054B050, and 0x0054B58D:
    //
    //   vec_x += input_x / *0x007DE810
    //   vec_y += input_y / *0x007DE810
    //   speed cap = actor+0x120 * actor+0x74 * progression+0x90 * *0x00784740
    //   dx = actor+0x218 * vec_x
    //   dy = actor+0x218 * vec_y
    //   FUN_00525800(world + 0x378, actor, dx, dy, 0)
    //   vec *= *0x00784E20
    //
    // The bot's stock tick still needs +0x158/+0x15C cleared before it runs so
    // it cannot consume the prior frame twice. Keep the accumulator in the
    // binding, then publish the same vector to actor memory only for the
    // recovered native MoveStep call and animation replay.
    float native_speed_cap = 0.0f;
    float native_input_acceleration_divisor = 0.0f;
    float native_velocity_damping = 0.0f;
    if (!TryResolveWizardBotNativeMovementEnvelope(
            binding,
            actor_address,
            &native_speed_cap,
            &native_input_acceleration_divisor,
            &native_velocity_damping,
            error_message)) {
        binding->last_movement_displacement = 0.0f;
        PublishParticipantGameplaySnapshot(*binding);
        return false;
    }
    float move_step_scale = memory.ReadFieldOr<float>(actor_address, kActorMoveStepScaleOffset, 0.0f);
    if (!(move_step_scale > 0.0f)) {
        move_step_scale = 1.0f;
        (void)memory.TryWriteField(actor_address, kActorMoveStepScaleOffset, move_step_scale);
    }
    if (!std::isfinite(binding->native_movement_accumulator_x)) {
        binding->native_movement_accumulator_x = 0.0f;
    }
    if (!std::isfinite(binding->native_movement_accumulator_y)) {
        binding->native_movement_accumulator_y = 0.0f;
    }
    auto velocity_x =
        binding->native_movement_accumulator_x + (direction_x / native_input_acceleration_divisor);
    auto velocity_y =
        binding->native_movement_accumulator_y + (direction_y / native_input_acceleration_divisor);
    const auto velocity_magnitude = std::sqrt((velocity_x * velocity_x) + (velocity_y * velocity_y));
    if (native_speed_cap >= 0.0f &&
        std::isfinite(velocity_magnitude) &&
        velocity_magnitude > native_speed_cap &&
        velocity_magnitude > 0.0001f) {
        const auto velocity_scale = native_speed_cap / velocity_magnitude;
        velocity_x *= velocity_scale;
        velocity_y *= velocity_scale;
    }

    (void)memory.TryWriteField(actor_address, kActorAnimationConfigBlockOffset, velocity_x);
    (void)memory.TryWriteField(actor_address, kActorAnimationDriveParameterOffset, velocity_y);

    const auto move_step_x = velocity_x * move_step_scale;
    const auto move_step_y = velocity_y * move_step_scale;
    DWORD exception_code = 0;
    std::uint32_t move_result = 0;
    if ((binding->kind == ParticipantEntityBinding::Kind::PlaceholderEnemy ||
         IsStandaloneWizardKind(binding->kind) ||
         IsGameplaySlotWizardKind(binding->kind)) &&
        move_step_address != 0 &&
        movement_controller_address != 0 &&
        CallPlayerActorMoveStepSafe(
            move_step_address,
            movement_controller_address,
            actor_address,
            move_step_x,
            move_step_y,
            0,
            &exception_code,
            &move_result)) {
        const auto position_after_x = memory.ReadFieldOr<float>(actor_address, kActorPositionXOffset, 0.0f);
        const auto position_after_y = memory.ReadFieldOr<float>(actor_address, kActorPositionYOffset, 0.0f);
        const auto delta_x = position_after_x - position_before_x;
        const auto delta_y = position_after_y - position_before_y;
        const auto displacement_distance = std::sqrt((delta_x * delta_x) + (delta_y * delta_y));
        const auto applied_direction_x = direction_x;
        const auto applied_direction_y = direction_y;
        binding->native_movement_accumulator_x = velocity_x * native_velocity_damping;
        binding->native_movement_accumulator_y = velocity_y * native_velocity_damping;
        (void)memory.TryWriteField(
            actor_address,
            kActorAnimationConfigBlockOffset,
            binding->native_movement_accumulator_x);
        (void)memory.TryWriteField(
            actor_address,
            kActorAnimationDriveParameterOffset,
            binding->native_movement_accumulator_y);
        auto movement_log_result = move_result != 0 ? "player_move_step_ok" : "player_move_step_blocked";
        if (!ApplyWizardBindingFacingState(binding, actor_address) && binding->desired_heading_valid) {
            ApplyWizardActorFacingState(actor_address, binding->desired_heading);
        }
        binding->last_movement_displacement = displacement_distance;
        if (IsStandaloneWizardKind(binding->kind) && !cast_active) {
            AdvanceStandaloneWizardWalkCycleState(binding, displacement_distance);
            ApplyStandaloneWizardDynamicAnimationState(binding, actor_address);
        }
        if (displacement_distance <= 0.0001f) {
            if (cast_active) {
                ClearWizardBotMovementVectorInputs(actor_address);
            } else {
                StopWizardBotActorMotion(actor_address);
            }
            (void)ApplyWizardBindingFacingState(binding, actor_address);
            static std::uint64_t s_last_stuck_move_log_ms = 0;
            const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
            if (now_ms - s_last_stuck_move_log_ms >= 1000) {
                s_last_stuck_move_log_ms = now_ms;
                Log(
                    "[bots] zero-displacement move step. bot_id=" + std::to_string(binding->bot_id) +
                    " actor=" + HexString(actor_address) +
                    " before=(" + std::to_string(position_before_x) + ", " + std::to_string(position_before_y) + ")" +
                    " after=(" + std::to_string(position_after_x) + ", " + std::to_string(position_after_y) + ")" +
                    " dir=(" + std::to_string(direction_x) + ", " + std::to_string(direction_y) + ")" +
                    " desired_heading=" + std::to_string(binding->desired_heading) +
                    " move_result=" + std::to_string(move_result) +
                    " movement_controller=" + HexString(movement_controller_address) +
                    " move_step_scale=" + std::to_string(move_step_scale) +
                    " destination=(" + std::to_string(binding->target_x) + ", " + std::to_string(binding->target_y) + ")" +
                    " waypoint=(" + std::to_string(binding->current_waypoint_x) + ", " + std::to_string(binding->current_waypoint_y) + ")");
            }
        }
        LogWizardBotMovementFrame(
            binding,
            actor_address,
            owner_address,
            movement_controller_address,
            applied_direction_x,
            applied_direction_y,
            velocity_x,
            velocity_y,
            position_before_x,
            position_before_y,
            position_after_x,
            position_after_y,
            movement_log_result);
        PublishParticipantGameplaySnapshot(*binding);
        return true;
    }

    if (exception_code != 0 && error_message != nullptr) {
        *error_message = "PlayerActor_MoveStep threw 0x" + HexString(exception_code) + ".";
    } else if (error_message != nullptr && movement_controller_address == 0) {
        *error_message = "PlayerActor_MoveStep requires a live movement controller.";
    }

    binding->last_movement_displacement = 0.0f;
    binding->native_movement_accumulator_x = 0.0f;
    binding->native_movement_accumulator_y = 0.0f;
    ClearWizardBotMovementVectorInputs(actor_address);
    PublishParticipantGameplaySnapshot(*binding);
    return false;
}
