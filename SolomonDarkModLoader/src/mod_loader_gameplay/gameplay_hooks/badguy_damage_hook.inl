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

#include "match_enemy_damage_observation.inl"

struct EarthBoulderDamageCapture {
    bool eligible = false;
    bool terms_valid = false;
    SDModEarthBoulderDamageObservation observation;
};

EarthBoulderDamageCapture CaptureEarthBoulderDamageBeforeNativeCall(
    uintptr_t target_actor_address) {
    EarthBoulderDamageCapture capture;
    {
        std::lock_guard<std::mutex> lock(
            g_earth_boulder_damage_observation_mutex);
        if (!g_earth_boulder_damage_observation_armed ||
            g_earth_boulder_damage_observations.size() >=
                kMaximumEarthBoulderDamageObservations) {
            return capture;
        }
    }

    auto& state = g_gameplay_keyboard_injection;
    if (target_actor_address == 0 ||
        state.damage_context_source_address == 0 ||
        state.damage_context_primary_address == 0 ||
        state.damage_context_secondary_address !=
            state.damage_context_primary_address + sizeof(float)) {
        return capture;
    }

    auto& memory = ProcessMemory::Instance();
    auto& observation = capture.observation;
    if (!memory.TryReadValue(
            state.damage_context_source_address,
            &observation.source_actor_address) ||
        observation.source_actor_address == 0 ||
        !memory.TryReadField(
            observation.source_actor_address,
            kGameObjectTypeIdOffset,
            &observation.source_native_type_id) ||
        observation.source_native_type_id !=
            kWaterPrimaryDamageSourceNativeTypeId) {
        return capture;
    }
    capture.eligible = true;
    observation.target_actor_address = target_actor_address;

    observation.owner_actor_address =
        ResolveDamageSourceOwnerActorAddress(
            observation.source_actor_address);
    observation.source_participant_id =
        ResolveDamageSourceParticipantId(
            observation.source_actor_address);
    const bool have_progression =
        observation.owner_actor_address != 0 &&
        TryResolveDamageSourceProgressionAddress(
            observation.source_actor_address,
            &observation.progression_address) &&
        observation.progression_address != 0;

    constexpr std::size_t kBoulderSkillIndex = 40;
    constexpr std::size_t kEarthSpellClass = 4;
    uintptr_t progression_table_address = 0;
    std::int32_t progression_table_count = 0;
    std::int8_t source_gameplay_slot = -1;
    bool terms_valid =
        have_progression &&
        memory.TryReadField(
            observation.source_actor_address,
            kDamageSourceGameplaySlotOffset,
            &source_gameplay_slot) &&
        memory.TryReadField(
            observation.progression_address,
            kProgressionLevelOffset,
            &observation.progression_level) &&
        memory.TryReadField(
            observation.progression_address,
            kStandaloneWizardProgressionTableBaseOffset,
            &progression_table_address) &&
        memory.TryReadField(
            observation.progression_address,
            kStandaloneWizardProgressionTableCountOffset,
            &progression_table_count) &&
        progression_table_address != 0 &&
        progression_table_count > static_cast<std::int32_t>(kBoulderSkillIndex) &&
        memory.TryReadField(
            progression_table_address +
                kBoulderSkillIndex *
                    kStandaloneWizardProgressionEntryStride,
            kStandaloneWizardProgressionEntryEffectiveRankOffset,
            &observation.effective_rank) &&
        memory.TryReadField(
            observation.progression_address,
            kProgressionSpellDamageBaseAdditiveOffset,
            &observation.progression_base_additive) &&
        memory.TryReadField(
            observation.progression_address,
            kProgressionSpellDamageGlobalFlatOffset,
            &observation.progression_global_flat) &&
        memory.TryReadField(
            observation.progression_address,
            kProgressionSpellFlatBaseOffset +
                kBoulderSkillIndex * sizeof(float),
            &observation.progression_spell_flat) &&
        memory.TryReadField(
            observation.progression_address,
            kProgressionSpellClassFlatBaseOffset +
                kEarthSpellClass * sizeof(float),
            &observation.progression_class_flat) &&
        memory.TryReadField(
            observation.progression_address,
            kProgressionSpellDamageGlobalMultiplierOffset,
            &observation.progression_global_multiplier) &&
        memory.TryReadField(
            observation.progression_address,
            kProgressionSpellMultiplierBaseOffset +
                kBoulderSkillIndex * sizeof(float),
            &observation.progression_spell_multiplier) &&
        memory.TryReadField(
            observation.progression_address,
            kProgressionSpellClassMultiplierBaseOffset +
                kEarthSpellClass * sizeof(float),
            &observation.progression_class_multiplier) &&
        memory.TryReadField(
            observation.progression_address,
            kProgressionOffensiveDamageMultiplierOffset,
            &observation.progression_siege_multiplier) &&
        memory.TryReadField(
            observation.owner_actor_address,
            kActorSpellConfig298Offset,
            &observation.actor_stat_damage) &&
        memory.TryReadField(
            observation.source_actor_address,
            kSpellObjectChargeOffset,
            &observation.charge) &&
        memory.TryReadField(
            observation.source_actor_address,
            kSpellObjectGrowthRateOffset,
            &observation.growth_rate) &&
        memory.TryReadField(
            observation.source_actor_address,
            kSpellObjectReleaseChargeOffset,
            &observation.release_charge) &&
        memory.TryReadField(
            observation.source_actor_address,
            kSpellObjectReleaseDamageOffset,
            &observation.release_damage_pool) &&
        memory.TryReadField(
            observation.source_actor_address,
            kSpellObjectReleaseBaseDamageOffset,
            &observation.release_base_damage) &&
        memory.TryReadField(
            observation.source_actor_address,
            kSpellObjectMaxChargeOffset,
            &observation.maximum_charge) &&
        memory.TryReadField(
            observation.source_actor_address,
            kSpellObjectToughnessOffset,
            &observation.toughness) &&
        memory.TryReadValue(
            state.damage_context_primary_address,
            &observation.damage_lane_primary) &&
        memory.TryReadValue(
            state.damage_context_secondary_address,
            &observation.damage_lane_secondary) &&
        memory.TryReadField(
            target_actor_address,
            kEnemyCurrentHpOffset,
            &observation.target_hp_before) &&
        memory.TryReadField(
            target_actor_address,
            kEnemyMaxHpOffset,
            &observation.target_max_hp);
    observation.source_gameplay_slot =
        static_cast<std::int32_t>(source_gameplay_slot);

    const std::array<float, 20> finite_terms = {
        observation.progression_base_additive,
        observation.progression_global_flat,
        observation.progression_spell_flat,
        observation.progression_class_flat,
        observation.progression_global_multiplier,
        observation.progression_spell_multiplier,
        observation.progression_class_multiplier,
        observation.progression_siege_multiplier,
        observation.actor_stat_damage,
        observation.charge,
        observation.growth_rate,
        observation.release_charge,
        observation.release_damage_pool,
        observation.release_base_damage,
        observation.maximum_charge,
        observation.toughness,
        observation.damage_lane_primary,
        observation.damage_lane_secondary,
        observation.target_hp_before,
        observation.target_max_hp,
    };
    terms_valid =
        terms_valid &&
        std::all_of(
            finite_terms.begin(),
            finite_terms.end(),
            [](float value) { return std::isfinite(value); });

    const double multiplier_product =
        static_cast<double>(observation.progression_global_multiplier) *
        static_cast<double>(observation.progression_spell_multiplier) *
        static_cast<double>(observation.progression_class_multiplier) *
        static_cast<double>(observation.progression_siege_multiplier);
    if (terms_valid &&
        std::isfinite(multiplier_product) &&
        multiplier_product != 0.0) {
        observation.configured_rank_damage = static_cast<float>(
            static_cast<double>(observation.actor_stat_damage) /
                multiplier_product -
            static_cast<double>(observation.progression_base_additive) -
            static_cast<double>(observation.progression_global_flat) -
            static_cast<double>(observation.progression_spell_flat) -
            static_cast<double>(observation.progression_class_flat));
        terms_valid =
            std::isfinite(observation.configured_rank_damage);
    } else {
        terms_valid = false;
    }

    capture.terms_valid = terms_valid;
    return capture;
}

void ObserveEarthBoulderDamageAfterNativeCall(
    const EarthBoulderDamageCapture& capture) {
    if (!capture.eligible) {
        return;
    }

    auto observation = capture.observation;
    const bool have_hp_after =
        ProcessMemory::Instance().TryReadField(
            observation.target_actor_address,
            kEnemyCurrentHpOffset,
            &observation.target_hp_after) &&
        std::isfinite(observation.target_hp_after);
    if (have_hp_after) {
        observation.hp_delta =
            observation.target_hp_before - observation.target_hp_after;
    }
    observation.valid =
        capture.terms_valid &&
        have_hp_after &&
        std::isfinite(observation.hp_delta) &&
        observation.hp_delta >= 0.0f;

    {
        std::lock_guard<std::mutex> lock(
            g_earth_boulder_damage_observation_mutex);
        if (!g_earth_boulder_damage_observation_armed ||
            g_earth_boulder_damage_observations.size() >=
                kMaximumEarthBoulderDamageObservations) {
            return;
        }
        observation.sequence =
            g_next_earth_boulder_damage_observation_sequence++;
        g_earth_boulder_damage_observations.push_back(observation);
    }

    const auto trace_float = [](float value) {
        return std::to_string(value) +
            "(bits=" + HexString(FloatToBits(value)) + ")";
    };
    Log(
        "[earth-damage-trace] sequence=" +
        std::to_string(observation.sequence) +
        " valid=" + std::to_string(observation.valid ? 1 : 0) +
        " participant_id=" +
        std::to_string(observation.source_participant_id) +
        " source=" + HexString(observation.source_actor_address) +
        " owner=" + HexString(observation.owner_actor_address) +
        " progression=" + HexString(observation.progression_address) +
        " target=" + HexString(observation.target_actor_address) +
        " native_type=" + HexString(observation.source_native_type_id) +
        " slot=" + std::to_string(observation.source_gameplay_slot) +
        " level=" + std::to_string(observation.progression_level) +
        " rank=" + std::to_string(observation.effective_rank) +
        " base_add=" + trace_float(observation.progression_base_additive) +
        " rank_damage=" + trace_float(observation.configured_rank_damage) +
        " global_flat=" + trace_float(observation.progression_global_flat) +
        " spell_flat=" + trace_float(observation.progression_spell_flat) +
        " class_flat=" + trace_float(observation.progression_class_flat) +
        " global_mul=" +
        trace_float(observation.progression_global_multiplier) +
        " spell_mul=" +
        trace_float(observation.progression_spell_multiplier) +
        " class_mul=" +
        trace_float(observation.progression_class_multiplier) +
        " siege_mul=" +
        trace_float(observation.progression_siege_multiplier) +
        " actor_damage=" + trace_float(observation.actor_stat_damage) +
        " charge=" + trace_float(observation.charge) +
        " growth_rate=" + trace_float(observation.growth_rate) +
        " release_charge=" + trace_float(observation.release_charge) +
        " release_pool=" + trace_float(observation.release_damage_pool) +
        " release_base=" + trace_float(observation.release_base_damage) +
        " maximum_charge=" + trace_float(observation.maximum_charge) +
        " toughness=" + trace_float(observation.toughness) +
        " lane_primary=" + trace_float(observation.damage_lane_primary) +
        " lane_secondary=" +
        trace_float(observation.damage_lane_secondary) +
        " hp_before=" + trace_float(observation.target_hp_before) +
        " hp_after=" + trace_float(observation.target_hp_after) +
        " hp_delta=" + trace_float(observation.hp_delta));
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

#include "packet_enemy_damage_suppression.inl"

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
        ShouldSuppressPacketDrivenRemoteReplicatedEnemyDamage(
            actor_address,
            context_source)) {
        const auto earth_boulder_damage_capture =
            CaptureEarthBoulderDamageBeforeNativeCall(actor_address);
        ObserveEarthBoulderDamageAfterNativeCall(
            earth_boulder_damage_capture);
        return 0;
    }
    if (have_source &&
        source_native_type_id == kFireballDamageSourceNativeTypeId &&
        source_gameplay_slot != 0) {
        std::uint64_t synthetic_participant_id = 0;
        if (!IsAuthorizedHostSyntheticFireballDamage(
                context_source,
                &synthetic_participant_id)) {
            return 0;
        }
        const auto target_network_actor_id = multiplayer::GetLocalRunEnemyNetworkActorId(actor_address);
        Log("[bots] host synthetic Fireball native damage authorized. monotonic_ms=" +
            std::to_string(GetTickCount64()) + " participant_id=" +
            std::to_string(synthetic_participant_id) +
            " projectile_actor=" + HexString(context_source) +
            " target_actor=" + HexString(actor_address) + " target_network_actor_id=" +
            std::to_string(target_network_actor_id));
    }

    const auto local_damage_capture =
        CaptureLocalReplicatedEnemyDamageBeforeNativeCall(actor_address);
    const auto call_original = [&]() {
        const auto enemy_damage_capture =
            CaptureEnemyDamageBeforeNativeCall(actor_address);
        const auto earth_boulder_damage_capture =
            CaptureEarthBoulderDamageBeforeNativeCall(actor_address);
        const auto result = original(self);
        ObserveEarthBoulderDamageAfterNativeCall(
            earth_boulder_damage_capture);
        ObserveEnemyDamageAfterNativeCall(enemy_damage_capture);
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
