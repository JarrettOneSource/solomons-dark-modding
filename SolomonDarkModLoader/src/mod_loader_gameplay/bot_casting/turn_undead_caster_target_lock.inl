constexpr std::int32_t kTurnUndeadSecondarySkillEntry = 0x4D;

struct AuthoritativeTurnUndeadPrecastEnemyState {
    uintptr_t enemy_actor_address = 0;
    std::int32_t duration_ticks = 0;
};

struct AuthoritativeTurnUndeadTargetLock {
    uintptr_t caster_actor_address = 0;
    std::uint64_t caster_participant_id = 0;
};

std::unordered_map<uintptr_t, AuthoritativeTurnUndeadTargetLock>
    g_authoritative_turn_undead_target_locks;

std::vector<AuthoritativeTurnUndeadPrecastEnemyState>
CaptureAuthoritativeTurnUndeadPrecastState(
    uintptr_t caster_actor_address,
    std::int32_t skill_entry_index) {
    std::vector<AuthoritativeTurnUndeadPrecastEnemyState> result;
    if (skill_entry_index != kTurnUndeadSecondarySkillEntry ||
        caster_actor_address == 0 ||
        !multiplayer::IsLocalTransportHost() ||
        kActorTurnUndeadDurationTicksOffset == 0) {
        return result;
    }

    std::vector<SDModSceneActorState> actors;
    if (!TryListSceneActors(&actors)) {
        return result;
    }

    auto& memory = ProcessMemory::Instance();
    result.reserve(actors.size());
    for (const auto& actor : actors) {
        if (!actor.valid ||
            !actor.tracked_enemy ||
            actor.actor_address == 0 ||
            actor.actor_address == caster_actor_address ||
            actor.dead ||
            !multiplayer::IsTurnUndeadEligibleRunEnemyType(
                actor.object_type_id)) {
            continue;
        }

        std::int32_t duration_ticks = 0;
        if (!memory.TryReadField(
                actor.actor_address,
                kActorTurnUndeadDurationTicksOffset,
                &duration_ticks) ||
            duration_ticks < -100000 ||
            duration_ticks > 100000) {
            continue;
        }
        result.push_back({actor.actor_address, duration_ticks});
    }
    return result;
}

bool WriteAuthoritativeTurnUndeadCasterTarget(
    uintptr_t enemy_actor_address,
    uintptr_t caster_actor_address) {
    if (enemy_actor_address == 0 ||
        caster_actor_address == 0 ||
        kActorCurrentTargetActorOffset == 0 ||
        kHostileTargetBucketDeltaOffset == 0 ||
        kActorWorldBucketStride == 0) {
        return false;
    }

    uintptr_t enemy_world_address = 0;
    std::int32_t enemy_actor_slot = -1;
    std::int32_t enemy_world_slot = -1;
    uintptr_t caster_world_address = 0;
    std::int32_t caster_actor_slot = -1;
    std::int32_t caster_world_slot = -1;
    if (!TryReadActorWorldTargetSlotState(
            enemy_actor_address,
            &enemy_world_address,
            &enemy_actor_slot,
            &enemy_world_slot) ||
        !TryReadActorWorldTargetSlotState(
            caster_actor_address,
            &caster_world_address,
            &caster_actor_slot,
            &caster_world_slot) ||
        enemy_world_address != caster_world_address) {
        return false;
    }
    (void)enemy_world_slot;

    const auto bucket_stride =
        static_cast<std::int64_t>(kActorWorldBucketStride);
    const auto target_bucket_delta =
        static_cast<std::int64_t>(caster_actor_slot) * bucket_stride +
        static_cast<std::int64_t>(caster_world_slot) -
        static_cast<std::int64_t>(enemy_actor_slot) * bucket_stride;
    if (target_bucket_delta < (std::numeric_limits<std::int32_t>::min)() ||
        target_bucket_delta > (std::numeric_limits<std::int32_t>::max)()) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t current_target_actor_address = 0;
    std::int32_t current_target_bucket_delta = 0;
    if (!memory.TryReadField(
            enemy_actor_address,
            kActorCurrentTargetActorOffset,
            &current_target_actor_address) ||
        !memory.TryReadField(
            enemy_actor_address,
            kHostileTargetBucketDeltaOffset,
            &current_target_bucket_delta)) {
        return false;
    }

    const auto desired_target_bucket_delta =
        static_cast<std::int32_t>(target_bucket_delta);
    const bool target_ready =
        current_target_actor_address == caster_actor_address ||
        memory.TryWriteField<uintptr_t>(
            enemy_actor_address,
            kActorCurrentTargetActorOffset,
            caster_actor_address);
    const bool bucket_ready =
        current_target_bucket_delta == desired_target_bucket_delta ||
        memory.TryWriteField<std::int32_t>(
            enemy_actor_address,
            kHostileTargetBucketDeltaOffset,
            desired_target_bucket_delta);
    return target_ready && bucket_ready;
}

void RegisterAuthoritativeTurnUndeadCasterTargets(
    uintptr_t caster_actor_address,
    std::uint64_t caster_participant_id,
    const std::vector<AuthoritativeTurnUndeadPrecastEnemyState>& precast_state,
    bool native_success) {
    if (!native_success ||
        !multiplayer::IsLocalTransportHost() ||
        caster_actor_address == 0 ||
        caster_participant_id == 0 ||
        precast_state.empty() ||
        kActorTurnUndeadDurationTicksOffset == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    std::size_t affected_count = 0;
    std::size_t applied_count = 0;
    for (const auto& previous : precast_state) {
        std::int32_t current_duration_ticks = 0;
        if (previous.enemy_actor_address == 0 ||
            !memory.TryReadField(
                previous.enemy_actor_address,
                kActorTurnUndeadDurationTicksOffset,
                &current_duration_ticks) ||
            current_duration_ticks <= 0 ||
            current_duration_ticks > 100000 ||
            current_duration_ticks <= previous.duration_ticks) {
            continue;
        }

        affected_count += 1;
        g_authoritative_turn_undead_target_locks[previous.enemy_actor_address] = {
            caster_actor_address,
            caster_participant_id,
        };
        if (WriteAuthoritativeTurnUndeadCasterTarget(
                previous.enemy_actor_address,
                caster_actor_address)) {
            applied_count += 1;
        }
    }

    if (affected_count > 0) {
        Log(
            "Multiplayer authoritative Turn Undead caster targets registered. caster=" +
            HexString(caster_actor_address) +
            " affected=" + std::to_string(affected_count) +
            " applied=" + std::to_string(applied_count));
    }
}

bool ApplyAuthoritativeTurnUndeadCasterTargetLock(
    uintptr_t enemy_actor_address) {
    if (!multiplayer::IsLocalTransportHost() || enemy_actor_address == 0) {
        return false;
    }

    const auto lock_it =
        g_authoritative_turn_undead_target_locks.find(enemy_actor_address);
    if (lock_it == g_authoritative_turn_undead_target_locks.end()) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    std::int32_t duration_ticks = 0;
    if (kActorTurnUndeadDurationTicksOffset == 0 ||
        !memory.TryReadField(
            enemy_actor_address,
            kActorTurnUndeadDurationTicksOffset,
            &duration_ticks) ||
        duration_ticks <= 0 ||
        duration_ticks > 100000 ||
        IsActorRuntimeDead(enemy_actor_address) ||
        IsActorRuntimeDead(lock_it->second.caster_actor_address)) {
        g_authoritative_turn_undead_target_locks.erase(lock_it);
        return false;
    }

    (void)WriteAuthoritativeTurnUndeadCasterTarget(
        enemy_actor_address,
        lock_it->second.caster_actor_address);
    return true;
}

void ForgetAuthoritativeTurnUndeadTargetLocksForActor(
    uintptr_t actor_address) {
    if (actor_address == 0) {
        return;
    }

    for (auto lock_it = g_authoritative_turn_undead_target_locks.begin();
         lock_it != g_authoritative_turn_undead_target_locks.end();) {
        if (lock_it->first == actor_address ||
            lock_it->second.caster_actor_address == actor_address) {
            lock_it = g_authoritative_turn_undead_target_locks.erase(lock_it);
        } else {
            ++lock_it;
        }
    }
}

void ClearAuthoritativeTurnUndeadTargetLocks() {
    g_authoritative_turn_undead_target_locks.clear();
}
