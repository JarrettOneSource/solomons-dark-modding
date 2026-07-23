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

bool ClearHostileTargetsForDeadWizardActor(uintptr_t dead_actor_address) {
    if (dead_actor_address == 0 || !IsActorRuntimeDead(dead_actor_address)) {
        return false;
    }

    std::vector<SDModSceneActorState> actors;
    if (!TryListSceneActors(&actors)) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    int scanned_hostiles = 0;
    int cleared_hostiles = 0;
    for (const auto& actor : actors) {
        if (!actor.tracked_enemy ||
            actor.actor_address == 0 ||
            actor.dead ||
            actor.actor_address == dead_actor_address) {
            continue;
        }

        scanned_hostiles += 1;
        uintptr_t current_target_actor_address = 0;
        if (!memory.TryReadField(
                actor.actor_address,
                kActorCurrentTargetActorOffset,
                &current_target_actor_address) ||
            current_target_actor_address != dead_actor_address) {
            continue;
        }

        const bool target_write =
            memory.TryWriteField<uintptr_t>(
                actor.actor_address,
                kActorCurrentTargetActorOffset,
                0);
        const bool bucket_write =
            memory.TryWriteField<std::int32_t>(
                actor.actor_address,
                kHostileTargetBucketDeltaOffset,
                0);
        if (target_write || bucket_write) {
            cleared_hostiles += 1;
        }
    }

    if (cleared_hostiles > 0) {
        static std::uint64_t s_last_dead_wizard_target_clear_log_ms = 0;
        const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
        if (now_ms - s_last_dead_wizard_target_clear_log_ms >= 250) {
            s_last_dead_wizard_target_clear_log_ms = now_ms;
            Log(
                std::string("[hostile_ai] cleared dead wizard target refs") +
                ". dead_target=" + HexString(dead_actor_address) +
                " cleared=" + std::to_string(cleared_hostiles) +
                " scanned=" + std::to_string(scanned_hostiles));
        }
    }
    return cleared_hostiles > 0;
}

void __fastcall HookMonsterPathfindingRefreshTarget(void* self, void* /*unused_edx*/) {
    const auto original = GetX86HookTrampoline<MonsterPathfindingRefreshTargetFn>(
        g_gameplay_keyboard_injection.monster_pathfinding_refresh_target_hook);
    if (original == nullptr) {
        return;
    }

    const auto hostile_actor_address = reinterpret_cast<uintptr_t>(self);
    float frozen_x = 0.0f;
    float frozen_y = 0.0f;
    if (TryGetRunLifecycleManualEnemyFreezePosition(hostile_actor_address, &frozen_x, &frozen_y)) {
        if (IsActorRuntimeDead(hostile_actor_address)) {
            ClearRunLifecycleManualEnemyFreeze(hostile_actor_address);
            return;
        }
        (void)RestoreRunLifecycleFrozenManualEnemyPosition(
            hostile_actor_address);
        auto& memory = ProcessMemory::Instance();
        (void)memory.TryWriteField<uintptr_t>(
            hostile_actor_address,
            kActorCurrentTargetActorOffset,
            0);
        (void)memory.TryWriteField<std::int32_t>(
            hostile_actor_address,
            kHostileTargetBucketDeltaOffset,
            0);
        return;
    }

    if (ApplyAuthoritativeTurnUndeadCasterTargetLock(hostile_actor_address)) {
        return;
    }

    if (multiplayer::IsLocalTransportClient()) {
        (void)ApplyLatestReplicatedRunEnemyTargetForLocalActor(hostile_actor_address, true);
        return;
    }

    original(self, nullptr);

    if (ApplyLuaEnemyAiTargetOverride(hostile_actor_address)) {
        return;
    }

    // The hostile-target widening path is only validated on stock wave-spawned
    // enemies. Pre-wave/manual spawn surfaces have repeatedly shown instability
    // when hostile AI is redirected onto gameplay-slot bots before the combat
    // system is fully active, so keep the widening dormant until a run has
    // actually entered wave combat.
    if (!IsRunLifecycleActive() || GetRunLifecycleCurrentWave() <= 0) {
        return;
    }

    if (hostile_actor_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t gameplay_address = 0;
    if (!TryResolveCurrentGameplayScene(&gameplay_address) || gameplay_address == 0) {
        return;
    }

    uintptr_t hostile_world_address = 0;
    if (!memory.TryReadField(hostile_actor_address, kActorOwnerOffset, &hostile_world_address)) {
        return;
    }
    if (hostile_world_address == 0) {
        return;
    }

    std::int8_t hostile_actor_slot_byte = -1;
    if (!memory.TryReadField(hostile_actor_address, kActorSlotOffset, &hostile_actor_slot_byte)) {
        return;
    }
    const auto hostile_actor_slot = static_cast<std::int32_t>(hostile_actor_slot_byte);
    if (hostile_actor_slot < 0) {
        return;
    }

    const auto compute_distance_to = [&](uintptr_t candidate_actor_address, float* distance) -> bool {
        if (distance == nullptr || candidate_actor_address == 0 || candidate_actor_address == hostile_actor_address) {
            return false;
        }
        uintptr_t candidate_world_address = 0;
        if (!memory.TryReadField(candidate_actor_address, kActorOwnerOffset, &candidate_world_address) ||
            candidate_world_address != hostile_world_address) {
            return false;
        }
        if (IsActorRuntimeDead(candidate_actor_address)) {
            return false;
        }
        std::uint8_t candidate_anim_drive_state = 0;
        if (!memory.TryReadField(
                candidate_actor_address,
                kActorAnimationDriveStateByteOffset,
                &candidate_anim_drive_state) ||
            candidate_anim_drive_state != 0) {
            return false;
        }

        float hostile_x = 0.0f;
        float hostile_y = 0.0f;
        float candidate_x = 0.0f;
        float candidate_y = 0.0f;
        if (!TryReadFiniteFloatField(hostile_actor_address, kActorPositionXOffset, &hostile_x) ||
            !TryReadFiniteFloatField(hostile_actor_address, kActorPositionYOffset, &hostile_y) ||
            !TryReadFiniteFloatField(candidate_actor_address, kActorPositionXOffset, &candidate_x) ||
            !TryReadFiniteFloatField(candidate_actor_address, kActorPositionYOffset, &candidate_y)) {
            return false;
        }
        const auto delta_x = hostile_x - candidate_x;
        const auto delta_y = hostile_y - candidate_y;
        *distance = std::sqrt((delta_x * delta_x) + (delta_y * delta_y));
        return true;
    };

    auto best_distance = (std::numeric_limits<float>::max)();
    uintptr_t best_actor_address = 0;
    uintptr_t current_target_actor_address = 0;
    if (!memory.TryReadField(
            hostile_actor_address,
            kActorCurrentTargetActorOffset,
            &current_target_actor_address)) {
        return;
    }
    bool current_target_is_dead_bot = false;
    if (!compute_distance_to(current_target_actor_address, &best_distance) &&
        current_target_actor_address != 0 &&
        IsActorRuntimeDead(current_target_actor_address)) {
        std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
        const auto* current_binding = FindParticipantEntityForActor(current_target_actor_address);
        current_target_is_dead_bot =
            current_binding != nullptr && IsWizardParticipantKind(current_binding->kind);
    }

    std::vector<uintptr_t> candidate_actor_addresses;
    {
        std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
        candidate_actor_addresses.reserve(g_participant_entities.size());
        for (const auto& binding : g_participant_entities) {
            if (!IsWizardParticipantKind(binding.kind) || binding.actor_address == 0) {
                continue;
            }
            if (binding.materialized_scene_address != 0 &&
                binding.materialized_scene_address != gameplay_address) {
                continue;
            }
            candidate_actor_addresses.push_back(binding.actor_address);
        }
    }

    for (const auto candidate_actor_address : candidate_actor_addresses) {
        if (candidate_actor_address == 0) {
            continue;
        }

        auto candidate_distance = 0.0f;
        if (!compute_distance_to(candidate_actor_address, &candidate_distance)) {
            continue;
        }

        if (candidate_distance < best_distance) {
            best_distance = candidate_distance;
            best_actor_address = candidate_actor_address;
        }
    }

    if (best_actor_address == 0) {
        if (current_target_is_dead_bot) {
            (void)memory.TryWriteField<uintptr_t>(
                hostile_actor_address,
                kActorCurrentTargetActorOffset,
                0);
            (void)memory.TryWriteField<std::int32_t>(
                hostile_actor_address,
                kHostileTargetBucketDeltaOffset,
                0);
            static std::uint64_t s_last_dead_target_clear_log_ms = 0;
            const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
            if (now_ms - s_last_dead_target_clear_log_ms >= 250) {
                s_last_dead_target_clear_log_ms = now_ms;
                Log(
                    std::string("[hostile_ai] cleared dead bot target") +
                    ". hostile=" + HexString(hostile_actor_address) +
                    " dead_target=" + HexString(current_target_actor_address));
            }
        }
        return;
    }

    std::int16_t best_world_slot_word = -1;
    if (!memory.TryReadField(best_actor_address, kActorWorldSlotOffset, &best_world_slot_word)) {
        return;
    }
    const auto best_world_slot = static_cast<std::int32_t>(best_world_slot_word);
    if (best_world_slot < 0) {
        return;
    }

    std::int16_t current_target_world_slot_word = -1;
    const bool have_current_target_world_slot =
        current_target_actor_address != 0 &&
        memory.TryReadField(
            current_target_actor_address,
            kActorWorldSlotOffset,
            &current_target_world_slot_word);
    std::int8_t current_target_slot_byte = -1;
    const bool have_current_target_slot =
        current_target_actor_address != 0 &&
        memory.TryReadField(
            current_target_actor_address,
            kActorSlotOffset,
            &current_target_slot_byte);
    std::int8_t best_actor_slot_byte = -1;
    if (!memory.TryReadField(best_actor_address, kActorSlotOffset, &best_actor_slot_byte)) {
        return;
    }
    const auto best_actor_slot = static_cast<std::int32_t>(best_actor_slot_byte);
    if (best_actor_slot < 0) {
        return;
    }

    const auto best_bucket_delta =
        best_actor_slot * kActorWorldBucketStride + best_world_slot -
        hostile_actor_slot * kActorWorldBucketStride;

    (void)memory.TryWriteField(hostile_actor_address, kActorCurrentTargetActorOffset, best_actor_address);
    (void)memory.TryWriteField(hostile_actor_address, kHostileTargetBucketDeltaOffset, best_bucket_delta);

    if (best_actor_address != current_target_actor_address) {
        static std::uint64_t s_last_selector_promotion_log_ms = 0;
        const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
        if (now_ms - s_last_selector_promotion_log_ms >= 250) {
            s_last_selector_promotion_log_ms = now_ms;
            Log(
                std::string("[hostile_ai] selector promoted wizard participant") +
                ". hostile=" + HexString(hostile_actor_address) +
                " stock_target=" + HexString(current_target_actor_address) +
                " stock_slot=" + (have_current_target_slot
                    ? std::to_string(static_cast<std::int32_t>(current_target_slot_byte))
                    : UnreadableMemoryFieldText()) +
                " stock_world_slot=" + (have_current_target_world_slot
                    ? std::to_string(static_cast<std::int32_t>(current_target_world_slot_word))
                    : UnreadableMemoryFieldText()) +
                " promoted_target=" + HexString(best_actor_address) +
                " promoted_slot=" + std::to_string(best_actor_slot) +
                " promoted_world_slot=" + std::to_string(best_world_slot) +
                " promoted_bucket_delta=" + std::to_string(best_bucket_delta));
        }
    }
}
