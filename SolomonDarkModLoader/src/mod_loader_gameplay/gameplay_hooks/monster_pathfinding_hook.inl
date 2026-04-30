void __fastcall HookMonsterPathfindingRefreshTarget(void* self, void* /*unused_edx*/) {
    const auto original = GetX86HookTrampoline<MonsterPathfindingRefreshTargetFn>(
        g_gameplay_keyboard_injection.monster_pathfinding_refresh_target_hook);
    if (original == nullptr) {
        return;
    }

    original(self, nullptr);

    // The hostile-target widening path is only validated on stock wave-spawned
    // enemies. Pre-wave/manual spawn surfaces have repeatedly shown instability
    // when hostile AI is redirected onto gameplay-slot bots before the combat
    // system is fully active, so keep the widening dormant until a run has
    // actually entered wave combat.
    if (!IsRunLifecycleActive() || GetRunLifecycleCurrentWave() <= 0) {
        return;
    }

    const auto hostile_actor_address = reinterpret_cast<uintptr_t>(self);
    if (hostile_actor_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t gameplay_address = 0;
    if (!TryResolveCurrentGameplayScene(&gameplay_address) || gameplay_address == 0) {
        return;
    }

    const auto hostile_world_address =
        memory.ReadFieldOr<uintptr_t>(hostile_actor_address, kActorOwnerOffset, 0);
    if (hostile_world_address == 0) {
        return;
    }

    const auto hostile_actor_slot =
        static_cast<std::int32_t>(memory.ReadFieldOr<std::int8_t>(
            hostile_actor_address,
            kActorSlotOffset,
            static_cast<std::int8_t>(-1)));
    if (hostile_actor_slot < 0) {
        return;
    }

    const auto compute_distance_to = [&](uintptr_t candidate_actor_address, float* distance) -> bool {
        if (distance == nullptr || candidate_actor_address == 0 || candidate_actor_address == hostile_actor_address) {
            return false;
        }
        if (memory.ReadFieldOr<uintptr_t>(candidate_actor_address, kActorOwnerOffset, 0) != hostile_world_address) {
            return false;
        }
        if (IsActorRuntimeDead(candidate_actor_address)) {
            return false;
        }
        if (memory.ReadFieldOr<std::uint8_t>(candidate_actor_address, kActorAnimationDriveStateByteOffset, 0) != 0) {
            return false;
        }

        const auto delta_x =
            memory.ReadFieldOr<float>(hostile_actor_address, kActorPositionXOffset, 0.0f) -
            memory.ReadFieldOr<float>(candidate_actor_address, kActorPositionXOffset, 0.0f);
        const auto delta_y =
            memory.ReadFieldOr<float>(hostile_actor_address, kActorPositionYOffset, 0.0f) -
            memory.ReadFieldOr<float>(candidate_actor_address, kActorPositionYOffset, 0.0f);
        *distance = std::sqrt((delta_x * delta_x) + (delta_y * delta_y));
        return true;
    };

    auto best_distance = (std::numeric_limits<float>::max)();
    uintptr_t best_actor_address = 0;
    const auto current_target_actor_address =
        memory.ReadFieldOr<uintptr_t>(hostile_actor_address, kHostileCurrentTargetActorOffset, 0);
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
                kHostileCurrentTargetActorOffset,
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

    const auto best_world_slot =
        static_cast<std::int32_t>(memory.ReadFieldOr<std::int16_t>(
            best_actor_address,
            kActorWorldSlotOffset,
            static_cast<std::int16_t>(-1)));
    if (best_world_slot < 0) {
        return;
    }

    const auto current_target_world_slot =
        current_target_actor_address != 0
            ? static_cast<std::int32_t>(memory.ReadFieldOr<std::int16_t>(
                  current_target_actor_address,
                  kActorWorldSlotOffset,
                  static_cast<std::int16_t>(-1)))
            : -1;
    const auto current_target_slot =
        current_target_actor_address != 0
            ? static_cast<std::int32_t>(memory.ReadFieldOr<std::int8_t>(
                  current_target_actor_address,
                  kActorSlotOffset,
                  static_cast<std::int8_t>(-1)))
            : -1;
    const auto best_actor_slot =
        static_cast<std::int32_t>(memory.ReadFieldOr<std::int8_t>(
            best_actor_address,
            kActorSlotOffset,
            static_cast<std::int8_t>(-1)));
    if (best_actor_slot < 0) {
        return;
    }

    const auto best_bucket_delta =
        best_actor_slot * kActorWorldBucketStride + best_world_slot -
        hostile_actor_slot * kActorWorldBucketStride;

    (void)memory.TryWriteField(hostile_actor_address, kHostileCurrentTargetActorOffset, best_actor_address);
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
                " stock_slot=" + std::to_string(current_target_slot) +
                " stock_world_slot=" + std::to_string(current_target_world_slot) +
                " promoted_target=" + HexString(best_actor_address) +
                " promoted_slot=" + std::to_string(best_actor_slot) +
                " promoted_world_slot=" + std::to_string(best_world_slot) +
                " promoted_bucket_delta=" + std::to_string(best_bucket_delta));
        }
    }
}
