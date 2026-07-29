PlayerDamageCapture CapturePlayerDamageBeforeNativeCall(
    uintptr_t target_actor_address) {
    PlayerDamageCapture capture;
    {
        std::lock_guard<std::mutex> lock(
            g_player_damage_observation_mutex);
        if (!g_player_damage_observation_armed ||
            g_player_damage_observations.size() >=
                kMaximumMatchDamageObservations) {
            return capture;
        }
    }
    if (target_actor_address == 0) {
        return capture;
    }

    auto& observation = capture.observation;
    observation.target_actor_address = target_actor_address;
    observation.target_participant_id =
        ResolveDamageSourceParticipantId(target_actor_address);
    if (observation.target_participant_id == 0) {
        return capture;
    }

    SDModPlayerState local_player;
    if (TryGetPlayerState(&local_player) &&
        local_player.valid &&
        local_player.actor_address == target_actor_address) {
        observation.target_gameplay_slot = 0;
    } else {
        std::lock_guard<std::recursive_mutex> lock(
            g_participant_entities_mutex);
        const auto* binding =
            FindParticipantEntityForActor(target_actor_address);
        if (binding != nullptr) {
            observation.target_gameplay_slot =
                binding->gameplay_slot;
        }
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t progression_address = 0;
    const bool captured =
        memory.TryReadField(
            target_actor_address,
            kGameObjectTypeIdOffset,
            &observation.target_native_type_id) &&
        TryResolveActorProgressionRuntime(
            target_actor_address,
            &progression_address) &&
        progression_address != 0 &&
        memory.TryReadField(
            progression_address,
            kProgressionHpOffset,
            &observation.target_hp_before) &&
        memory.TryReadField(
            progression_address,
            kProgressionMaxHpOffset,
            &observation.target_max_hp);
    if (g_gameplay_keyboard_injection
            .damage_context_source_address != 0) {
        (void)memory.TryReadValue(
            g_gameplay_keyboard_injection
                .damage_context_source_address,
            &observation.source_actor_address);
    }
    if (observation.source_actor_address != 0) {
        (void)memory.TryReadField(
            observation.source_actor_address,
            kGameObjectTypeIdOffset,
            &observation.source_native_type_id);
    }
    capture.eligible =
        captured &&
        std::isfinite(observation.target_hp_before) &&
        std::isfinite(observation.target_max_hp) &&
        observation.target_max_hp > 0.0f;
    return capture;
}

void ObservePlayerDamageAfterNativeCall(
    const PlayerDamageCapture& capture) {
    if (!capture.eligible) {
        return;
    }

    auto observation = capture.observation;
    uintptr_t progression_address = 0;
    if (!TryResolveActorProgressionRuntime(
            observation.target_actor_address,
            &progression_address) ||
        progression_address == 0 ||
        !ProcessMemory::Instance().TryReadField(
            progression_address,
            kProgressionHpOffset,
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
    observation.monotonic_ms =
        static_cast<std::uint64_t>(GetTickCount64());

    std::lock_guard<std::mutex> lock(
        g_player_damage_observation_mutex);
    if (!g_player_damage_observation_armed ||
        g_player_damage_observations.size() >=
            kMaximumMatchDamageObservations) {
        return;
    }
    observation.sequence =
        g_next_player_damage_observation_sequence++;
    g_player_damage_observations.push_back(observation);
}
