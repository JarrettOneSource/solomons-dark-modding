constexpr std::size_t kGameNpcMoveFlagOffset = 0x198;
constexpr std::size_t kGameNpcDesiredYawOffset = 0x188;
constexpr std::size_t kGameNpcTrackedSlotOffset = 0x1C2;
constexpr std::size_t kGameNpcTrackedSlotCallbackOffset = 0x1C3;
constexpr std::uint8_t kGameNpcMoveModeDefault = 1;
constexpr float kRegisteredGameNpcGoalRetargetThreshold = 24.0f;
constexpr float kRegisteredGameNpcDirectStopDistance = 2.0f;
// Stock GameNpc movement scales the raw goal delta directly, and it resets its
// internal waypoint cadence when distance^2 drops below 64 (about 8 world
// units). Feed it modest micro-goals that stay comfortably above that floor so
// the native mover can accelerate and step, but still keep the target local.
constexpr float kRegisteredGameNpcIssuedGoalStepDistance = 9.0f;
constexpr float kRegisteredGameNpcIssuedGoalArrivalThreshold = 4.0f;
constexpr float kRegisteredGameNpcIssuedGoalRetargetDeltaThreshold = 1.0f;

void LogRegisteredGameNpcMovementControllerAnomaly(
    const ParticipantEntityBinding& binding,
    std::uint64_t now_ms) {
    if (binding.actor_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    const auto world_address =
        memory.ReadFieldOr<uintptr_t>(binding.actor_address, kActorOwnerOffset, 0);
    if (world_address == 0) {
        return;
    }

    const auto movement_context_address = world_address + kActorOwnerMovementControllerOffset;
    const auto primary_count = memory.ReadFieldOr<std::int32_t>(movement_context_address, 0x40, 0);
    const auto primary_list = memory.ReadFieldOr<uintptr_t>(movement_context_address, 0x4C, 0);
    const auto secondary_count = memory.ReadFieldOr<std::int32_t>(movement_context_address, 0x70, 0);
    const auto secondary_list = memory.ReadFieldOr<uintptr_t>(movement_context_address, 0x7C, 0);

    bool anomaly = false;
    std::ostringstream out;
    out << "[bots] registered_gamenpc movement list anomaly. bot_id=" << binding.bot_id
        << " actor=" << HexString(binding.actor_address)
        << " world=" << HexString(world_address)
        << " ctx=" << HexString(movement_context_address);

    const auto append_list = [&](const char* label, std::int32_t count, uintptr_t list_address) {
        out << " " << label << "_count=" << count
            << " " << label << "_list=" << HexString(list_address);
        if (count > 0 && list_address == 0) {
            anomaly = true;
            out << " " << label << "_list_null_with_positive_count=1";
            return;
        }

        int sample_count = count;
        if (sample_count < 0) {
            sample_count = 0;
        } else if (sample_count > 4) {
            sample_count = 4;
        }
        for (int index = 0; index < sample_count; ++index) {
            const auto entry_address =
                memory.ReadFieldOr<uintptr_t>(list_address, static_cast<std::size_t>(index) * sizeof(uintptr_t), 0);
            out << " " << label << index << "=" << HexString(entry_address);
            if (entry_address == 0) {
                anomaly = true;
            }
        }
    };

    append_list("primary", primary_count, primary_list);
    append_list("secondary", secondary_count, secondary_list);

    if (!anomaly) {
        return;
    }

    static std::uint64_t s_last_registered_gamenpc_movement_anomaly_log_ms = 0;
    if (now_ms - s_last_registered_gamenpc_movement_anomaly_log_ms < 250) {
        return;
    }
    s_last_registered_gamenpc_movement_anomaly_log_ms = now_ms;
    Log(out.str());
}

void StopRegisteredGameNpcMotion(ParticipantEntityBinding* binding) {
    if (binding == nullptr || binding->actor_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    (void)memory.TryWriteField<std::uint8_t>(
        binding->actor_address,
        kGameNpcMoveFlagOffset,
        0);
    (void)memory.TryWriteField<std::uint8_t>(
        binding->actor_address,
        kGameNpcTrackedSlotOffset,
        0xFF);
    (void)memory.TryWriteField<std::uint8_t>(
        binding->actor_address,
        kGameNpcTrackedSlotCallbackOffset,
        0);
    binding->registered_gamenpc_goal_active = false;
    binding->registered_gamenpc_following_local_slot = false;
    binding->registered_gamenpc_goal_x = 0.0f;
    binding->registered_gamenpc_goal_y = 0.0f;
}

void ApplyRegisteredGameNpcIdleFacing(ParticipantEntityBinding* binding) {
    if (binding == nullptr || binding->actor_address == 0 || !binding->desired_heading_valid) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    ApplyWizardActorFacingState(binding->actor_address, binding->desired_heading);
    (void)memory.TryWriteField(binding->actor_address, kGameNpcDesiredYawOffset, binding->desired_heading);
}

struct RegisteredGameNpcMotionLogState {
    std::uint64_t last_log_ms = 0;
    float last_x = 0.0f;
    float last_y = 0.0f;
    bool have_last = false;
};

bool DriveRegisteredGameNpcMovement(
    uintptr_t gameplay_address,
    ParticipantEntityBinding* binding,
    std::uint64_t now_ms,
    std::string* error_message) {
    (void)gameplay_address;
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (binding == nullptr || binding->actor_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto actor_address = binding->actor_address;
    const auto set_move_goal_address = memory.ResolveGameAddressOrZero(kGameNpcSetMoveGoal);
    const auto current_x = memory.ReadFieldOr<float>(actor_address, kActorPositionXOffset, 0.0f);
    const auto current_y = memory.ReadFieldOr<float>(actor_address, kActorPositionYOffset, 0.0f);

    if (!binding->movement_active || !binding->has_target) {
        StopRegisteredGameNpcMotion(binding);
        PublishParticipantGameplaySnapshot(*binding);
        return true;
    }

    if (set_move_goal_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve GameNpc_SetMoveGoal.";
        }
        return false;
    }

    const auto goal_x =
        binding->current_waypoint_x != 0.0f || binding->current_waypoint_y != 0.0f
            ? binding->current_waypoint_x
            : binding->target_x;
    const auto goal_y =
        binding->current_waypoint_x != 0.0f || binding->current_waypoint_y != 0.0f
            ? binding->current_waypoint_y
            : binding->target_y;
    const auto target_delta_x = goal_x - current_x;
    const auto target_delta_y = goal_y - current_y;
    const auto target_distance =
        std::sqrt(target_delta_x * target_delta_x + target_delta_y * target_delta_y);
    if (!std::isfinite(target_distance)) {
        StopRegisteredGameNpcMotion(binding);
        PublishParticipantGameplaySnapshot(*binding);
        return true;
    }

    if (target_distance <= kRegisteredGameNpcDirectStopDistance) {
        ApplyRegisteredGameNpcIdleFacing(binding);
        StopRegisteredGameNpcMotion(binding);
        PublishParticipantGameplaySnapshot(*binding);
        return true;
    }

    binding->desired_heading_valid = true;
    binding->desired_heading = NormalizeGameplayHeadingDegrees(
        static_cast<float>(std::atan2(target_delta_y, target_delta_x) * (180.0 / 3.14159265358979323846) + 90.0));

    auto issued_goal_x = goal_x;
    auto issued_goal_y = goal_y;
    if (target_distance > kRegisteredGameNpcIssuedGoalStepDistance) {
        const auto step_scale = kRegisteredGameNpcIssuedGoalStepDistance / target_distance;
        issued_goal_x = current_x + target_delta_x * step_scale;
        issued_goal_y = current_y + target_delta_y * step_scale;
    }

    const auto goal_delta_x = issued_goal_x - binding->registered_gamenpc_goal_x;
    const auto goal_delta_y = issued_goal_y - binding->registered_gamenpc_goal_y;
    const auto goal_delta_distance =
        std::sqrt(goal_delta_x * goal_delta_x + goal_delta_y * goal_delta_y);
    const auto distance_to_issued_goal_x = binding->registered_gamenpc_goal_x - current_x;
    const auto distance_to_issued_goal_y = binding->registered_gamenpc_goal_y - current_y;
    const auto distance_to_issued_goal =
        std::sqrt(
            distance_to_issued_goal_x * distance_to_issued_goal_x +
            distance_to_issued_goal_y * distance_to_issued_goal_y);
    const bool need_retarget =
        !binding->registered_gamenpc_goal_active ||
        binding->registered_gamenpc_following_local_slot ||
        !std::isfinite(distance_to_issued_goal) ||
        distance_to_issued_goal <= kRegisteredGameNpcIssuedGoalArrivalThreshold ||
        !std::isfinite(goal_delta_distance) ||
        goal_delta_distance >= kRegisteredGameNpcIssuedGoalRetargetDeltaThreshold;

    if (need_retarget) {
        DWORD exception_code = 0;
        SehExceptionDetails exception_details = {};
        if (!CallGameNpcSetMoveGoalSafe(
                set_move_goal_address,
                actor_address,
                kGameNpcMoveModeDefault,
                0,
                issued_goal_x,
                issued_goal_y,
                0.0f,
                &exception_code,
                &exception_details)) {
            if (error_message != nullptr) {
                *error_message =
                    "GameNpc_SetMoveGoal failed. code=0x" + HexString(exception_code);
                const auto detail_summary = FormatSehExceptionDetails(exception_details);
                if (!detail_summary.empty()) {
                    *error_message += " " + detail_summary;
                }
            }
            return false;
        }

        binding->registered_gamenpc_goal_active = true;
        binding->registered_gamenpc_following_local_slot = false;
        binding->registered_gamenpc_goal_x = issued_goal_x;
        binding->registered_gamenpc_goal_y = issued_goal_y;
    }

    {
        static std::unordered_map<std::uint64_t, RegisteredGameNpcMotionLogState> s_log_state;
        auto& state = s_log_state[binding->bot_id];
        const auto dx = state.have_last ? (current_x - state.last_x) : 0.0f;
        const auto dy = state.have_last ? (current_y - state.last_y) : 0.0f;
        const auto d = std::sqrt(dx * dx + dy * dy);
        const auto scale_0x74 = memory.ReadFieldOr<float>(actor_address, 0x74, 0.0f);
        const auto scale_0x1BC = memory.ReadFieldOr<float>(actor_address, 0x1BC, 0.0f);
        const auto accel_0x1E0 = memory.ReadFieldOr<float>(actor_address, 0x1E0, 0.0f);
        const auto target_0x168 =
            memory.ReadFieldOr<std::uint32_t>(actor_address, 0x168, 0);
        const auto blend_0x268 = memory.ReadFieldOr<float>(actor_address, 0x268, 0.0f);
        Log(
            "[bots] regnpc_mv bot=" + std::to_string(binding->bot_id) +
            " pos=(" + std::to_string(current_x) + "," + std::to_string(current_y) + ")" +
            " d=" + std::to_string(d) +
            " dist_wp=" + std::to_string(target_distance) +
            " retarget=" + std::to_string(need_retarget ? 1 : 0) +
            " goal_delta=" + std::to_string(goal_delta_distance) +
            " 0x74=" + std::to_string(scale_0x74) +
            " 0x1BC=" + std::to_string(scale_0x1BC) +
            " 0x1E0=" + std::to_string(accel_0x1E0) +
            " 0x168=0x" + HexString(target_0x168) +
            " 0x268=" + std::to_string(blend_0x268));
        state.last_log_ms = now_ms;
        state.last_x = current_x;
        state.last_y = current_y;
        state.have_last = true;
    }

    PublishParticipantGameplaySnapshot(*binding);
    return true;
}
