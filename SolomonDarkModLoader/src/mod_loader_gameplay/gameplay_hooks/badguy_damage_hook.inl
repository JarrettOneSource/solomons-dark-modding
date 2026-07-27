struct HagathaCurseBossesDamageLaneSnapshot {
    std::array<float, 2> lanes{};
    bool restore_failed = false;
};

bool HasHagathaPerkFlag(
    uintptr_t progression_address,
    std::uint8_t selector) {
    if (progression_address == 0 ||
        kProgressionHagathaPerkFlagBaseOffset == 0) {
        return false;
    }

    std::uint8_t enabled = 0;
    return ProcessMemory::Instance().TryReadField(
               progression_address,
               kProgressionHagathaPerkFlagBaseOffset + selector,
               &enabled) &&
           enabled != 0;
}

bool RestoreHagathaCurseBossesDamageLanes(
    const HagathaCurseBossesDamageLaneSnapshot& snapshot) {
    const auto primary_address =
        g_gameplay_keyboard_injection.damage_context_primary_address;
    if (primary_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    bool restored = true;
    for (std::size_t index = 0; index < snapshot.lanes.size(); ++index) {
        restored = memory.TryWriteValue(
                       primary_address + index * sizeof(float),
                       snapshot.lanes[index]) &&
                   restored;
    }
    return restored;
}

bool TryApplyHagathaCurseBossesDamageMultiplier(
    HagathaCurseBossesDamageLaneSnapshot* snapshot) {
    if (snapshot == nullptr) {
        return false;
    }
    *snapshot = HagathaCurseBossesDamageLaneSnapshot{};

    const auto primary_address =
        g_gameplay_keyboard_injection.damage_context_primary_address;
    if (primary_address == 0 ||
        g_gameplay_keyboard_injection.damage_context_secondary_address !=
            primary_address + sizeof(float)) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    bool captured = true;
    for (std::size_t index = 0; index < snapshot->lanes.size(); ++index) {
        captured = memory.TryReadValue(
                       primary_address + index * sizeof(float),
                       &snapshot->lanes[index]) &&
                   captured;
    }
    if (!captured ||
        !std::all_of(
            snapshot->lanes.begin(),
            snapshot->lanes.end(),
            [](float value) { return std::isfinite(value) && value >= 0.0f; }) ||
        std::none_of(
            snapshot->lanes.begin(),
            snapshot->lanes.end(),
            [](float value) { return value > 0.0f; })) {
        return false;
    }

    std::array<float, 2> multiplied{};
    for (std::size_t index = 0; index < multiplied.size(); ++index) {
        multiplied[index] =
            snapshot->lanes[index] * kHagathaCurseBossesDamageMultiplier;
        if (!std::isfinite(multiplied[index])) {
            return false;
        }
    }

    bool wrote_all = true;
    for (std::size_t index = 0; index < multiplied.size(); ++index) {
        wrote_all = memory.TryWriteValue(
                        primary_address + index * sizeof(float),
                        multiplied[index]) &&
                    wrote_all;
    }
    if (wrote_all) {
        return true;
    }

    snapshot->restore_failed =
        !RestoreHagathaCurseBossesDamageLanes(*snapshot);
    return false;
}

struct LocalReplicatedEnemyDamageCapture {
    bool valid = false;
    std::uint64_t network_actor_id = 0;
    float hp_before = 0.0f;
    float max_hp = 0.0f;
    float target_x = 0.0f;
    float target_y = 0.0f;
};

LocalReplicatedEnemyDamageCapture
CaptureLocalReplicatedEnemyDamageBeforeNativeCall(
    uintptr_t actor_address) {
    LocalReplicatedEnemyDamageCapture capture;
    if (!multiplayer::IsLocalTransportClient() ||
        actor_address == 0 ||
        g_gameplay_keyboard_injection.damage_context_source_address == 0) {
        return capture;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t context_source = 0;
    if (!memory.TryReadValue(
            g_gameplay_keyboard_injection.damage_context_source_address,
            &context_source)) {
        return capture;
    }
    const auto local_participant_id =
        multiplayer::GetLocalTransportParticipantId();
    if (local_participant_id == 0 ||
        ResolveDamageSourceParticipantId(context_source) !=
            local_participant_id) {
        return capture;
    }

    capture.network_actor_id =
        multiplayer::GetLocalRunEnemyNetworkActorId(actor_address);
    if (capture.network_actor_id == 0 ||
        !memory.TryReadField(
            actor_address,
            kEnemyCurrentHpOffset,
            &capture.hp_before) ||
        !memory.TryReadField(
            actor_address,
            kEnemyMaxHpOffset,
            &capture.max_hp) ||
        !memory.TryReadField(
            actor_address,
            kActorPositionXOffset,
            &capture.target_x) ||
        !memory.TryReadField(
            actor_address,
            kActorPositionYOffset,
            &capture.target_y) ||
        !std::isfinite(capture.hp_before) ||
        !std::isfinite(capture.max_hp) ||
        capture.max_hp <= 0.0f ||
        !std::isfinite(capture.target_x) ||
        !std::isfinite(capture.target_y)) {
        return LocalReplicatedEnemyDamageCapture{};
    }
    capture.valid = true;
    return capture;
}

void ObserveLocalReplicatedEnemyDamageAfterNativeCall(
    uintptr_t actor_address,
    const LocalReplicatedEnemyDamageCapture& capture) {
    if (!capture.valid || actor_address == 0) {
        return;
    }

    float hp_after = 0.0f;
    if (!ProcessMemory::Instance().TryReadField(
            actor_address,
            kEnemyCurrentHpOffset,
            &hp_after) ||
        !std::isfinite(hp_after)) {
        return;
    }
    const auto damage = capture.hp_before - hp_after;
    if (!std::isfinite(damage) || damage <= 0.0f) {
        return;
    }
    float target_x = capture.target_x;
    float target_y = capture.target_y;
    (void)ProcessMemory::Instance().TryReadField(
        actor_address,
        kActorPositionXOffset,
        &target_x);
    (void)ProcessMemory::Instance().TryReadField(
        actor_address,
        kActorPositionYOffset,
        &target_y);
    if (!std::isfinite(target_x) || !std::isfinite(target_y)) {
        target_x = capture.target_x;
        target_y = capture.target_y;
    }
    multiplayer::ObserveLocalPlayerReplicatedRunEnemyDamageEvent(
        capture.network_actor_id,
        damage,
        capture.max_hp,
        target_x,
        target_y,
        true);
}

bool IsAuthorizedHostSyntheticFireballDamage(
    uintptr_t source_actor_address,
    std::uint64_t* participant_id) {
    if (participant_id != nullptr) {
        *participant_id = 0;
    }
    if (!multiplayer::IsLocalTransportHost() ||
        source_actor_address == 0) {
        return false;
    }

    const auto synthetic_participant_id =
        FindHostSyntheticDamageSourceParticipant(source_actor_address);
    if (synthetic_participant_id == 0) {
        return false;
    }

    const auto runtime_state = multiplayer::SnapshotRuntimeState();
    const auto* participant =
        multiplayer::FindParticipant(
            runtime_state,
            synthetic_participant_id);
    if (participant == nullptr ||
        !multiplayer::IsRemoteParticipant(*participant) ||
        !multiplayer::IsLuaControlledParticipant(*participant) ||
        !participant->runtime.valid ||
        !participant->runtime.in_run) {
        return false;
    }

    if (participant_id != nullptr) {
        *participant_id = synthetic_participant_id;
    }
    return true;
}

std::uint8_t __fastcall HookBadguyDamage(
    void* self,
    void* /*unused_edx*/) {
    const auto original = GetX86HookTrampoline<BadguyDamageFn>(
        g_gameplay_keyboard_injection.badguy_damage_hook);
    if (original == nullptr) {
        return 0;
    }

    const auto actor_address = reinterpret_cast<uintptr_t>(self);
    auto& memory = ProcessMemory::Instance();
    uintptr_t context_source = 0;
    std::uint32_t source_native_type_id = 0;
    std::int8_t source_gameplay_slot = 0;
    const bool have_source =
        g_gameplay_keyboard_injection.damage_context_source_address != 0 &&
        memory.TryReadValue(
            g_gameplay_keyboard_injection.damage_context_source_address,
            &context_source) &&
        context_source != 0 &&
        memory.TryReadField(
            context_source,
            kGameObjectTypeIdOffset,
            &source_native_type_id) &&
        memory.TryReadField(
            context_source,
            kDamageSourceGameplaySlotOffset,
            &source_gameplay_slot);
    if (have_source &&
        source_native_type_id == kFireballDamageSourceNativeTypeId &&
        source_gameplay_slot != 0) {
        std::uint64_t synthetic_participant_id = 0;
        if (!IsAuthorizedHostSyntheticFireballDamage(
                context_source,
                &synthetic_participant_id)) {
            return 0;
        }
        Log(
            "[bots] host synthetic Fireball native damage authorized. "
            "participant_id=" +
            std::to_string(synthetic_participant_id) +
            " projectile_actor=" + HexString(context_source) +
            " target_actor=" + HexString(actor_address));
    }

    const auto local_damage_capture =
        CaptureLocalReplicatedEnemyDamageBeforeNativeCall(actor_address);
    const auto call_original = [&]() {
        const auto result = original(self);
        ObserveLocalReplicatedEnemyDamageAfterNativeCall(
            actor_address,
            local_damage_capture);
        return result;
    };
    std::uint32_t native_type_id = 0;
    if (actor_address == 0 ||
        !memory.TryReadField(
            actor_address,
            kGameObjectTypeIdOffset,
            &native_type_id) ||
        !IsHagathaCurseBossesNativeType(native_type_id) ||
        !memory.TryReadValue(
            g_gameplay_keyboard_injection.damage_context_source_address,
            &context_source)) {
        return call_original();
    }

    uintptr_t source_progression = 0;
    if (!TryResolveDamageSourceProgressionAddress(
            context_source,
            &source_progression) ||
        !HasHagathaPerkFlag(
            source_progression,
            kHagathaCurseBossesSelector)) {
        return call_original();
    }

    HagathaCurseBossesDamageLaneSnapshot snapshot;
    if (!TryApplyHagathaCurseBossesDamageMultiplier(&snapshot)) {
        if (snapshot.restore_failed) {
            Log(
                "[gameplay] Curse Bosses damage transaction rejected after "
                "restore failure. target=" + HexString(actor_address) +
                " source=" + HexString(context_source));
            ResetActiveDamageContext();
            return 0;
        }
        return call_original();
    }

    const auto result = call_original();
    if (!RestoreHagathaCurseBossesDamageLanes(snapshot)) {
        Log(
            "[gameplay] Curse Bosses damage transaction restore failed. "
            "target=" + HexString(actor_address) +
            " source=" + HexString(context_source) +
            " participant_id=" +
                std::to_string(
                    ResolveDamageSourceParticipantId(context_source)));
        ResetActiveDamageContext();
    }
    return result;
}
