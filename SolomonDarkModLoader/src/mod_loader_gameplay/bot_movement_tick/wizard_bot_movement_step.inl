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

    if (IsRegisteredGameNpcKind(binding->kind)) {
        binding->last_movement_displacement = 0.0f;
        PublishParticipantGameplaySnapshot(*binding);
        return true;
    }

    const bool cast_active = binding->ongoing_cast.active;
    if (!binding->movement_active || magnitude <= 0.0001f) {
        binding->last_movement_displacement = 0.0f;
        if (cast_active) {
            // Continuous casts own the attack animation/control lane while they
            // are alive. Clear only stale locomotion inputs so the bot does not
            // slide; do not force the broader idle animation state over the
            // native cast pose.
            ClearWizardBotLocomotionInputs(actor_address);
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
    // around 0x0054B050 / 0x0054B58D:
    //
    //   move_step_scale = *(float*)(actor + 0x218)   ; set to 1.0f at construction
    //                                                ; by Player_Ctor @ 0x0052A588
    //   dir_x           = *(float*)(actor + 0x158)   ; direction accumulator the
    //   dir_y           = *(float*)(actor + 0x15C)   ; tick folds control input into
    //   dx              = move_step_scale * dir_x
    //   dy              = move_step_scale * dir_y
    //   FUN_00525800(world + 0x378, actor, dx, dy, 0)
    //
    // For bots the native tick never folds control input into +0x158/+0x15C
    // (no input source), so we seed those accumulators with our own normalized
    // target direction. If +0x218 is zero (e.g. the clone didn't run Player_Ctor),
    // initialize it to 1.0f — matching what the native constructor writes.
    float move_step_scale = memory.ReadFieldOr<float>(actor_address, kActorMoveStepScaleOffset, 0.0f);
    if (!(move_step_scale > 0.0f)) {
        move_step_scale = 1.0f;
        (void)memory.TryWriteField(actor_address, kActorMoveStepScaleOffset, move_step_scale);
    }
    (void)memory.TryWriteField(actor_address, kActorAnimationConfigBlockOffset, direction_x);
    (void)memory.TryWriteField(actor_address, kActorAnimationDriveParameterOffset, direction_y);

    const auto move_step_x = direction_x * move_step_scale;
    const auto move_step_y = direction_y * move_step_scale;
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
        auto position_after_x = memory.ReadFieldOr<float>(actor_address, kActorPositionXOffset, 0.0f);
        auto position_after_y = memory.ReadFieldOr<float>(actor_address, kActorPositionYOffset, 0.0f);
        auto delta_x = position_after_x - position_before_x;
        auto delta_y = position_after_y - position_before_y;
        auto displacement_distance = std::sqrt((delta_x * delta_x) + (delta_y * delta_y));
        auto applied_direction_x = direction_x;
        auto applied_direction_y = direction_y;
        auto movement_log_result = move_result != 0 ? "player_move_step_ok" : "player_move_step_blocked";
        if ((move_result == 0 || displacement_distance <= 0.0001f) && !cast_active) {
            const auto recovery_start_x = position_after_x;
            const auto recovery_start_y = position_after_y;
            const auto final_target_x = binding->target_x - recovery_start_x;
            const auto final_target_y = binding->target_y - recovery_start_y;
            const auto final_target_distance =
                std::sqrt((final_target_x * final_target_x) + (final_target_y * final_target_y));
            if (final_target_distance > 0.0001f) {
                const auto target_direction_x = final_target_x / final_target_distance;
                const auto target_direction_y = final_target_y / final_target_distance;
                constexpr float kSqrtHalf = 0.70710678118f;
                constexpr std::array<std::pair<float, float>, 7> kRecoveryRotations = {{
                    {1.0f, 0.0f},
                    {kSqrtHalf, kSqrtHalf},
                    {kSqrtHalf, -kSqrtHalf},
                    {0.0f, 1.0f},
                    {0.0f, -1.0f},
                    {-kSqrtHalf, kSqrtHalf},
                    {-kSqrtHalf, -kSqrtHalf},
                }};
                for (const auto& rotation : kRecoveryRotations) {
                    const auto recovery_direction_x =
                        target_direction_x * rotation.first - target_direction_y * rotation.second;
                    const auto recovery_direction_y =
                        target_direction_x * rotation.second + target_direction_y * rotation.first;
                    const auto recovery_magnitude =
                        std::sqrt((recovery_direction_x * recovery_direction_x) + (recovery_direction_y * recovery_direction_y));
                    if (recovery_magnitude <= 0.0001f) {
                        continue;
                    }

                    const auto normalized_recovery_direction_x = recovery_direction_x / recovery_magnitude;
                    const auto normalized_recovery_direction_y = recovery_direction_y / recovery_magnitude;
                    DWORD recovery_exception_code = 0;
                    std::uint32_t recovery_move_result = 0;
                    if (!CallPlayerActorMoveStepSafe(
                            move_step_address,
                            movement_controller_address,
                            actor_address,
                            normalized_recovery_direction_x * move_step_scale,
                            normalized_recovery_direction_y * move_step_scale,
                            0,
                            &recovery_exception_code,
                            &recovery_move_result)) {
                        continue;
                    }

                    const auto recovery_after_x = memory.ReadFieldOr<float>(actor_address, kActorPositionXOffset, 0.0f);
                    const auto recovery_after_y = memory.ReadFieldOr<float>(actor_address, kActorPositionYOffset, 0.0f);
                    const auto recovery_delta_x = recovery_after_x - recovery_start_x;
                    const auto recovery_delta_y = recovery_after_y - recovery_start_y;
                    const auto recovery_displacement =
                        std::sqrt((recovery_delta_x * recovery_delta_x) + (recovery_delta_y * recovery_delta_y));
                    if (recovery_displacement <= 0.0001f) {
                        continue;
                    }

                    position_after_x = recovery_after_x;
                    position_after_y = recovery_after_y;
                    delta_x = position_after_x - position_before_x;
                    delta_y = position_after_y - position_before_y;
                    displacement_distance = std::sqrt((delta_x * delta_x) + (delta_y * delta_y));
                    move_result = recovery_move_result;
                    applied_direction_x = normalized_recovery_direction_x;
                    applied_direction_y = normalized_recovery_direction_y;
                    direction_x = normalized_recovery_direction_x;
                    direction_y = normalized_recovery_direction_y;
                    binding->desired_heading = NormalizeGameplayHeadingDegrees(
                        static_cast<float>(std::atan2(direction_y, direction_x) * (180.0 / 3.14159265358979323846) + 90.0));
                    movement_log_result = "player_move_step_detour";
                    break;
                }
            }
        }
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
                ClearWizardBotLocomotionInputs(actor_address);
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
            applied_direction_x,
            applied_direction_y,
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
    PublishParticipantGameplaySnapshot(*binding);
    return true;
}
