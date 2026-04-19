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
    (void)memory.TryWriteField(binding->actor_address, kActorHeadingOffset, binding->desired_heading);
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
        PublishParticipantGameplaySnapshot(*binding);
        return true;
    }

    if (!binding->movement_active || magnitude <= 0.0001f) {
        ApplyObservedBotAnimationState(binding, actor_address, false);
        StopWizardBotActorMotion(binding->actor_address);
        PublishParticipantGameplaySnapshot(*binding);
        return true;
    }

    float direction_x = binding->direction_x / magnitude;
    float direction_y = binding->direction_y / magnitude;

    const auto position_before_x = memory.ReadFieldOr<float>(actor_address, kActorPositionXOffset, 0.0f);
    const auto position_before_y = memory.ReadFieldOr<float>(actor_address, kActorPositionYOffset, 0.0f);
    const auto velocity_x = direction_x;
    const auto velocity_y = direction_y;
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
        const auto position_after_x = memory.ReadFieldOr<float>(actor_address, kActorPositionXOffset, 0.0f);
        const auto position_after_y = memory.ReadFieldOr<float>(actor_address, kActorPositionYOffset, 0.0f);
        const auto delta_x = position_after_x - position_before_x;
        const auto delta_y = position_after_y - position_before_y;
        const auto displacement_distance = std::sqrt((delta_x * delta_x) + (delta_y * delta_y));
        if (binding->desired_heading_valid) {
            (void)memory.TryWriteField(actor_address, kActorHeadingOffset, binding->desired_heading);
        }
        if (IsStandaloneWizardKind(binding->kind)) {
            AdvanceStandaloneWizardWalkCycleState(binding, displacement_distance);
            ApplyStandaloneWizardDynamicAnimationState(binding, actor_address);
        }
        if (displacement_distance <= 0.0001f) {
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
            direction_x,
            direction_y,
            velocity_x,
            velocity_y,
            position_before_x,
            position_before_y,
            position_after_x,
            position_after_y,
            move_result != 0 ? "player_move_step_ok" : "player_move_step_blocked");
        PublishParticipantGameplaySnapshot(*binding);
        return true;
    }

    if (exception_code != 0 && error_message != nullptr) {
        *error_message = "PlayerActor_MoveStep threw 0x" + HexString(exception_code) + ".";
    } else if (error_message != nullptr && movement_controller_address == 0) {
        *error_message = "PlayerActor_MoveStep requires a live movement controller.";
    }

    PublishParticipantGameplaySnapshot(*binding);
    return true;
}

void SyncWizardBotMovementIntent(ParticipantEntityBinding* binding) {
    if (binding == nullptr || binding->bot_id == 0) {
        return;
    }

    multiplayer::BotMovementIntentSnapshot intent;
    if (!multiplayer::ReadBotMovementIntent(binding->bot_id, &intent) || !intent.available) {
        return;
    }

    binding->movement_intent_revision = intent.revision;
    binding->controller_state = intent.state;
    binding->movement_active = intent.moving;
    binding->has_target = intent.has_target;
    if (!intent.moving) {
        binding->direction_x = 0.0f;
        binding->direction_y = 0.0f;
    }
    if (intent.moving) {
        binding->direction_x = intent.direction_x;
        binding->direction_y = intent.direction_y;
    }
    binding->desired_heading_valid = intent.desired_heading_valid;
    binding->desired_heading = intent.desired_heading;
    binding->target_x = intent.target_x;
    binding->target_y = intent.target_y;
    binding->distance_to_target = intent.distance_to_target;
}

void TickParticipantSceneBindings(uintptr_t gameplay_address, std::uint64_t now_ms) {
    const auto scene_churn_until =
        g_gameplay_keyboard_injection.scene_churn_not_before_ms.load(std::memory_order_acquire);
    if (now_ms < scene_churn_until) {
        return;
    }

    SceneContextSnapshot scene_context;
    const bool have_scene_context = TryBuildSceneContextSnapshot(gameplay_address, &scene_context);
    std::vector<ParticipantRematerializationRequest> rematerialization_requests;
    std::vector<std::uint64_t> dematerialize_requests;
    std::vector<PendingParticipantEntitySyncRequest> materialize_requests;
    {
        std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
        for (auto& binding : g_participant_entities) {
            SyncWizardBotMovementIntent(&binding);
            multiplayer::BotSnapshot bot_snapshot;
            if (multiplayer::ReadBotSnapshot(binding.bot_id, &bot_snapshot) && bot_snapshot.available) {
                binding.character_profile = bot_snapshot.character_profile;
                binding.scene_intent = bot_snapshot.scene_intent;
            }
            const bool should_be_materialized =
                have_scene_context && ShouldBotBeMaterializedInScene(binding, scene_context);
            if (binding.actor_address == 0) {
                if (should_be_materialized && now_ms >= binding.next_scene_materialize_retry_ms) {
                    if (bot_snapshot.available) {
                        PendingParticipantEntitySyncRequest sync_request;
                        sync_request.bot_id = binding.bot_id;
                        sync_request.character_profile = bot_snapshot.character_profile;
                        sync_request.scene_intent = bot_snapshot.scene_intent;
                        sync_request.has_transform = bot_snapshot.transform_valid;
                        sync_request.has_heading = bot_snapshot.transform_valid;
                        sync_request.x = bot_snapshot.position_x;
                        sync_request.y = bot_snapshot.position_y;
                        sync_request.heading = bot_snapshot.heading;
                        materialize_requests.push_back(sync_request);
                        binding.next_scene_materialize_retry_ms = now_ms + kWizardBotSyncRetryDelayMs;
                    }
                }
                PublishParticipantGameplaySnapshot(binding);
                continue;
            }

            if (have_scene_context && HasBotMaterializedSceneChanged(binding, scene_context)) {
                if (should_be_materialized) {
                    ParticipantRematerializationRequest rematerialization_request;
                    if (TryBuildParticipantRematerializationRequest(gameplay_address, binding, &rematerialization_request)) {
                        rematerialization_requests.push_back(rematerialization_request);
                    }
                } else {
                    dematerialize_requests.push_back(binding.bot_id);
                }
                continue;
            }

        }
    }

    for (const auto bot_id : dematerialize_requests) {
        DematerializeParticipantEntityNow(bot_id, false, "scene mismatch");
    }

    for (const auto& rematerialization_request : rematerialization_requests) {
        QueueParticipantRematerialization(rematerialization_request);
    }

    for (const auto& sync_request : materialize_requests) {
        std::string error_message;
        if (!QueueParticipantEntitySync(
                sync_request.bot_id,
                sync_request.character_profile,
                sync_request.scene_intent,
                sync_request.has_transform,
                sync_request.has_heading,
                sync_request.x,
                sync_request.y,
                sync_request.heading,
                &error_message)) {
            Log(
                "[bots] queued scene materialize failed. bot_id=" + std::to_string(sync_request.bot_id) +
                " element_id=" + std::to_string(sync_request.character_profile.element_id) +
                " error=" + error_message);
        }
    }
}

void TickParticipantSceneBindingsIfActive() {
    if (!g_gameplay_keyboard_injection.initialized) {
        return;
    }

    static std::uint64_t s_last_scene_binding_tick_ms = 0;
    static std::uint64_t s_last_scene_binding_log_ms = 0;
    const auto now_ms = static_cast<std::uint64_t>(::GetTickCount64());
    if (now_ms - s_last_scene_binding_log_ms >= 1000) {
        s_last_scene_binding_log_ms = now_ms;
        std::uint32_t bot_count = 0;
        std::uint32_t materialized_count = 0;
        {
            std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
            bot_count = static_cast<std::uint32_t>(g_participant_entities.size());
            for (const auto& binding : g_participant_entities) {
                if (binding.actor_address != 0) {
                    ++materialized_count;
                }
            }
        }
        Log(
            "[bots] scene_binding_tick heartbeat participants=" + std::to_string(bot_count) +
            " materialized=" + std::to_string(materialized_count));
    }
    if (now_ms - s_last_scene_binding_tick_ms < kWizardBotSceneBindingTickIntervalMs) {
        return;
    }
    s_last_scene_binding_tick_ms = now_ms;

    uintptr_t gameplay_address = 0;
    if (!TryResolveCurrentGameplayScene(&gameplay_address) || gameplay_address == 0) {
        return;
    }

    std::lock_guard<std::recursive_mutex> pump_lock(g_gameplay_action_pump_mutex);
    TickParticipantSceneBindings(gameplay_address, now_ms);
    {
        std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
        for (auto& binding : g_participant_entities) {
            if (!IsRegisteredGameNpcKind(binding.kind) || binding.actor_address == 0) {
                continue;
            }

            LogRegisteredGameNpcMovementControllerAnomaly(binding, now_ms);
            SyncWizardBotMovementIntent(&binding);
            std::string path_error;
            if (!UpdateWizardBotPathMotion(&binding, now_ms, &path_error) &&
                !path_error.empty()) {
                Log(
                    "[bots] registered_gamenpc path update failed. bot_id=" +
                    std::to_string(binding.bot_id) +
                    " actor=" + HexString(binding.actor_address) +
                    " error=" + path_error);
            }
            std::string movement_error;
            if (!DriveRegisteredGameNpcMovement(gameplay_address, &binding, now_ms, &movement_error) &&
                !movement_error.empty()) {
                Log(
                    "[bots] registered_gamenpc movement failed. bot_id=" +
                    std::to_string(binding.bot_id) +
                    " actor=" + HexString(binding.actor_address) +
                    " error=" + movement_error);
            }
        }
    }
}
