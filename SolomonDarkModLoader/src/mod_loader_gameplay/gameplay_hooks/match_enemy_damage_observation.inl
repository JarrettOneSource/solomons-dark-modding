struct EnemyDamageCapture {
    bool eligible = false;
    SDModEnemyDamageObservation observation;
};

EnemyDamageCapture CaptureEnemyDamageBeforeNativeCall(
    uintptr_t target_actor_address) {
    EnemyDamageCapture capture;
    auto& hook_state = g_gameplay_keyboard_injection;
    if (target_actor_address == 0 ||
        hook_state.damage_context_source_address == 0) {
        return capture;
    }

    auto& memory = ProcessMemory::Instance();
    auto& observation = capture.observation;
    if (!memory.TryReadValue(
            hook_state.damage_context_source_address,
            &observation.source_actor_address) ||
        observation.source_actor_address == 0) {
        return capture;
    }
    observation.source_participant_id =
        ResolveDamageSourceParticipantId(
            observation.source_actor_address);
    if (observation.source_participant_id == 0) {
        return capture;
    }

    observation.source_owner_actor_address =
        ResolveDamageSourceOwnerActorAddress(
            observation.source_actor_address);
    observation.target_actor_address = target_actor_address;
    observation.target_network_actor_id =
        multiplayer::GetLocalRunEnemyNetworkActorId(
            target_actor_address);
    std::int8_t source_gameplay_slot = -1;
    const bool captured =
        memory.TryReadField(
            observation.source_actor_address,
            kGameObjectTypeIdOffset,
            &observation.source_native_type_id) &&
        memory.TryReadField(
            target_actor_address,
            kGameObjectTypeIdOffset,
            &observation.target_native_type_id) &&
        memory.TryReadField(
            target_actor_address,
            kEnemyCurrentHpOffset,
            &observation.target_hp_before) &&
        memory.TryReadField(
            target_actor_address,
            kEnemyMaxHpOffset,
            &observation.target_max_hp);
    (void)memory.TryReadField(
        observation.source_actor_address,
        kDamageSourceGameplaySlotOffset,
        &source_gameplay_slot);
    observation.source_gameplay_slot =
        static_cast<std::int32_t>(source_gameplay_slot);
    if (observation.source_owner_actor_address != 0) {
        (void)memory.TryReadField(
            observation.source_owner_actor_address,
            kGameObjectTypeIdOffset,
            &observation.source_owner_native_type_id);
    }
    capture.eligible =
        captured &&
        std::isfinite(observation.target_hp_before) &&
        std::isfinite(observation.target_max_hp) &&
        observation.target_max_hp > 0.0f;
    return capture;
}

void ObserveEnemyDamageAfterNativeCall(
    const EnemyDamageCapture& capture) {
    if (!capture.eligible) {
        return;
    }

    auto observation = capture.observation;
    if (!ProcessMemory::Instance().TryReadField(
            observation.target_actor_address,
            kEnemyCurrentHpOffset,
            &observation.target_hp_after) ||
        !std::isfinite(observation.target_hp_after)) {
        return;
    }
    observation.hp_delta =
        observation.target_hp_before - observation.target_hp_after;
    if (!std::isfinite(observation.hp_delta) ||
        observation.hp_delta <= 0.0f) {
        return;
    }
    // Reward attribution consumes the same authoritative post-contact edge as
    // combat verification. Clamp overkill at zero HP so solo reward remains
    // identical to the former observed-health-ratio decrease.
    const auto applied_hp_damage =
        (std::min)(
            observation.hp_delta,
            (std::max)(observation.target_hp_before, 0.0f));
    if (applied_hp_damage > 0.0f &&
        observation.target_max_hp > 0.0f) {
        multiplayer::ObserveParticipantEnemyDamageRewardAttribution(
            observation.source_participant_id,
            static_cast<double>(applied_hp_damage) /
                static_cast<double>(observation.target_max_hp));
    }
    observation.monotonic_ms =
        static_cast<std::uint64_t>(GetTickCount64());

    std::lock_guard<std::mutex> lock(
        g_enemy_damage_observation_mutex);
    if (!g_enemy_damage_observation_armed ||
        g_enemy_damage_observations.size() >=
            kMaximumMatchDamageObservations) {
        return;
    }
    observation.sequence =
        g_next_enemy_damage_observation_sequence++;
    g_enemy_damage_observations.push_back(observation);
}
