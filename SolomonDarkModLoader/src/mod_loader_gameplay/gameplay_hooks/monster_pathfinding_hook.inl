std::uint32_t __fastcall HookBadguyMoveStep(
    void* movement_context,
    void* /*unused_edx*/,
    void* actor,
    float move_x,
    float move_y) {
    const auto original = GetX86HookTrampoline<BadguyMoveStepFn>(
        g_gameplay_keyboard_injection.badguy_move_step_hook);
    if (original == nullptr) {
        return 0;
    }

    const auto actor_address = reinterpret_cast<uintptr_t>(actor);
    float frozen_x = 0.0f;
    float frozen_y = 0.0f;
    if (TryGetRunLifecycleManualEnemyFreezePosition(
            actor_address,
            &frozen_x,
            &frozen_y)) {
        (void)RestoreRunLifecycleFrozenManualEnemyPosition(actor_address);
        return 1;
    }
    if (IsBoundReplicatedRunEnemyActorForLocalClient(actor_address)) {
        return 1;
    }

    LuaEnemyAiCommandRuntime ai_command;
    if (TryGetLuaEnemyAiCommandForActor(actor_address, &ai_command) &&
        ai_command.state.move_goal_active) {
        float actor_x = 0.0f;
        float actor_y = 0.0f;
        if (TryReadFiniteFloatField(
                actor_address,
                kActorPositionXOffset,
                &actor_x) &&
            TryReadFiniteFloatField(
                actor_address,
                kActorPositionYOffset,
                &actor_y)) {
            const float goal_dx = ai_command.state.move_goal_x - actor_x;
            const float goal_dy = ai_command.state.move_goal_y - actor_y;
            const float goal_distance =
                std::sqrt(goal_dx * goal_dx + goal_dy * goal_dy);
            const float native_move_magnitude =
                std::sqrt(move_x * move_x + move_y * move_y);
            if (std::isfinite(goal_distance) &&
                goal_distance <=
                    ai_command.state.move_goal_stop_distance) {
                return original(movement_context, actor, 0.0f, 0.0f);
            }
            if (std::isfinite(goal_distance) && goal_distance > 0.0001f &&
                std::isfinite(native_move_magnitude) &&
                native_move_magnitude > 0.0001f) {
                move_x = goal_dx / goal_distance * native_move_magnitude;
                move_y = goal_dy / goal_distance * native_move_magnitude;
            }
        }
    }

    return original(movement_context, actor, move_x, move_y);
}

bool WriteLuaEnemyAiNativeTarget(
    uintptr_t hostile_actor_address,
    uintptr_t target_actor_address) {
    if (hostile_actor_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    if (target_actor_address == 0) {
        const bool target_write = memory.TryWriteField<uintptr_t>(
            hostile_actor_address,
            kActorCurrentTargetActorOffset,
            0);
        const bool bucket_write = memory.TryWriteField<std::int32_t>(
            hostile_actor_address,
            kHostileTargetBucketDeltaOffset,
            0);
        return target_write && bucket_write;
    }

    if (target_actor_address == hostile_actor_address ||
        IsActorRuntimeDead(target_actor_address)) {
        return WriteLuaEnemyAiNativeTarget(hostile_actor_address, 0);
    }

    uintptr_t hostile_world_address = 0;
    std::int32_t hostile_actor_slot = -1;
    std::int32_t hostile_world_slot = -1;
    uintptr_t target_world_address = 0;
    std::int32_t target_actor_slot = -1;
    std::int32_t target_world_slot = -1;
    if (!TryReadActorWorldTargetSlotState(
            hostile_actor_address,
            &hostile_world_address,
            &hostile_actor_slot,
            &hostile_world_slot) ||
        !TryReadActorWorldTargetSlotState(
            target_actor_address,
            &target_world_address,
            &target_actor_slot,
            &target_world_slot) ||
        hostile_world_address == 0 ||
        hostile_world_address != target_world_address ||
        hostile_actor_slot < 0 || target_actor_slot < 0 ||
        target_world_slot < 0) {
        return WriteLuaEnemyAiNativeTarget(hostile_actor_address, 0);
    }
    (void)hostile_world_slot;

    const auto bucket_delta =
        target_actor_slot * kActorWorldBucketStride + target_world_slot -
        hostile_actor_slot * kActorWorldBucketStride;
    const bool target_write = memory.TryWriteField(
        hostile_actor_address,
        kActorCurrentTargetActorOffset,
        target_actor_address);
    const bool bucket_write = memory.TryWriteField(
        hostile_actor_address,
        kHostileTargetBucketDeltaOffset,
        bucket_delta);
    return target_write && bucket_write;
}

bool ApplyLuaEnemyAiTargetOverride(uintptr_t hostile_actor_address) {
    LuaEnemyAiCommandRuntime command;
    if (!TryGetLuaEnemyAiCommandForActor(
            hostile_actor_address,
            &command) ||
        command.state.target_mode == SDModLuaEnemyAiTargetMode::Stock) {
        return false;
    }

    uintptr_t target_actor_address = 0;
    switch (command.state.target_mode) {
    case SDModLuaEnemyAiTargetMode::Stock:
        return false;
    case SDModLuaEnemyAiTargetMode::Clear:
        break;
    case SDModLuaEnemyAiTargetMode::LocalPlayer: {
        SDModPlayerState player_state;
        if (TryGetPlayerState(&player_state) && player_state.valid) {
            target_actor_address = player_state.actor_address;
        }
        break;
    }
    case SDModLuaEnemyAiTargetMode::Participant:
        target_actor_address = ResolveReplicatedRunEnemyTargetActor(
            command.state.target_participant_id);
        break;
    }

    (void)WriteLuaEnemyAiNativeTarget(
        hostile_actor_address,
        target_actor_address);
    return true;
}

bool ApplyHigherPriorityHostileTargetPolicy(
    uintptr_t hostile_actor_address) {
    if (hostile_actor_address == 0) {
        return true;
    }

    float frozen_x = 0.0f;
    float frozen_y = 0.0f;
    if (TryGetRunLifecycleManualEnemyFreezePosition(
            hostile_actor_address,
            &frozen_x,
            &frozen_y)) {
        if (IsActorRuntimeDead(hostile_actor_address)) {
            ClearRunLifecycleManualEnemyFreeze(hostile_actor_address);
        } else {
            (void)RestoreRunLifecycleFrozenManualEnemyPosition(
                hostile_actor_address);
        }
        (void)WriteLuaEnemyAiNativeTarget(hostile_actor_address, 0);
        return true;
    }

    if (ApplyAuthoritativeTurnUndeadCasterTargetLock(hostile_actor_address)) {
        return true;
    }
    if (multiplayer::IsLocalTransportClient()) {
        (void)ApplyLatestReplicatedRunEnemyTargetForLocalActor(
            hostile_actor_address,
            true);
        return true;
    }
    return ApplyLuaEnemyAiTargetOverride(hostile_actor_address);
}

bool ReacquireHostileTargetAfterInvalidation(
    uintptr_t hostile_actor_address,
    uintptr_t invalidated_target_actor_address,
    std::string_view reason) {
    if (hostile_actor_address == 0 ||
        IsActorRuntimeDead(hostile_actor_address)) {
        return false;
    }
    if (ApplyHigherPriorityHostileTargetPolicy(hostile_actor_address)) {
        return true;
    }
    return ApplyNearestValidHostileTarget(
        hostile_actor_address,
        invalidated_target_actor_address,
        reason);
}

bool ClearHostileTargetsForDeadWizardActor(uintptr_t dead_actor_address) {
    if (dead_actor_address == 0 ||
        (!IsActorRuntimeDead(dead_actor_address) &&
         !IsDeadWizardParticipantActor(dead_actor_address))) {
        return false;
    }

    std::vector<uintptr_t> hostile_actor_addresses;
    if (!CaptureLiveHostilesTargetingActor(
            dead_actor_address,
            &hostile_actor_addresses)) {
        return false;
    }

    int reacquired_hostiles = 0;
    for (const auto hostile_actor_address : hostile_actor_addresses) {
        if (ReacquireHostileTargetAfterInvalidation(
                hostile_actor_address,
                dead_actor_address,
                "target_death")) {
            reacquired_hostiles += 1;
        }
    }

    if (reacquired_hostiles > 0) {
        Log(
            std::string("[hostile_ai] target death forced reacquisition") +
            ". dead_target=" + HexString(dead_actor_address) +
            " reacquired=" + std::to_string(reacquired_hostiles) +
            " affected=" +
                std::to_string(hostile_actor_addresses.size()));
    }
    return reacquired_hostiles > 0;
}

void __fastcall HookMonsterPathfindingSelectNearestTarget(
    void* self,
    void* /*unused_edx*/) {
    const auto original =
        GetX86HookTrampoline<MonsterPathfindingSelectNearestTargetFn>(
            g_gameplay_keyboard_injection
                .monster_pathfinding_select_nearest_target_hook);
    if (original == nullptr) {
        return;
    }

    const auto hostile_actor_address = reinterpret_cast<uintptr_t>(self);
    if (ApplyHigherPriorityHostileTargetPolicy(
            hostile_actor_address)) {
        return;
    }

    original(self, nullptr);
    (void)ApplyNearestValidHostileTarget(
        hostile_actor_address,
        0,
        "native_selector");
}

void __fastcall HookMonsterPathfindingRefreshTarget(
    void* self,
    void* /*unused_edx*/) {
    const auto original =
        GetX86HookTrampoline<MonsterPathfindingRefreshTargetFn>(
            g_gameplay_keyboard_injection
                .monster_pathfinding_refresh_target_hook);
    if (original == nullptr) {
        return;
    }

    const auto hostile_actor_address = reinterpret_cast<uintptr_t>(self);
    if (ApplyHigherPriorityHostileTargetPolicy(
            hostile_actor_address)) {
        return;
    }
    original(self, nullptr);
    (void)ApplyNearestValidHostileTarget(
        hostile_actor_address,
        0,
        "native_refresh");
}

std::uint32_t __fastcall HookBadguyCommonChaseTick(
    void* self,
    void* /*unused_edx*/) {
    const auto original =
        GetX86HookTrampoline<BadguyCommonChaseTickFn>(
            g_gameplay_keyboard_injection
                .badguy_common_chase_tick_hook);
    if (original == nullptr) {
        return 0;
    }

    const auto result = original(self, nullptr);
    const auto hostile_actor_address =
        reinterpret_cast<uintptr_t>(self);
    MaintainInvalidatedHostileTargetAfterNativeTick(hostile_actor_address);
    MaintainMissingOrInvalidHostileTargetAfterNativeTick(
        hostile_actor_address);
    return result;
}
