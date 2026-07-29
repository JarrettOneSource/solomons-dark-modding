bool ResetLocalPlayerManaDeltaObservation() {
    SDModPlayerState player;
    if (!TryGetPlayerState(&player) || player.actor_address == 0) {
        return false;
    }
    std::lock_guard<std::mutex> lock(g_local_mana_delta_observation_mutex);
    g_local_mana_delta_observation = SDModLocalManaDeltaObservation{};
    g_local_mana_delta_observation.armed = true;
    g_local_mana_delta_observation.actor_address = player.actor_address;
    return true;
}

bool RestoreLocalPlayerMana(
    float* resulting_mana,
    std::string* error_message) {
    if (resulting_mana != nullptr) {
        *resulting_mana = 0.0f;
    }
    if (error_message != nullptr) {
        error_message->clear();
    }
    const auto fail = [&](const char* message) {
        if (error_message != nullptr) {
            *error_message = message;
        }
        return false;
    };

    SDModPlayerState player;
    if (!TryGetPlayerState(&player) || !player.valid ||
        player.actor_address == 0) {
        return fail("The local player is unavailable.");
    }

    uintptr_t progression_address = 0;
    float current_mana = 0.0f;
    float maximum_mana = 0.0f;
    if (!TryResolveActorProgressionRuntime(
            player.actor_address,
            &progression_address) ||
        progression_address == 0 ||
        !TryReadProgressionMana(
            progression_address,
            &current_mana,
            &maximum_mana) ||
        !std::isfinite(current_mana) ||
        !std::isfinite(maximum_mana) ||
        maximum_mana <= 0.0f) {
        return fail("The local player's native mana pool is unavailable.");
    }

    constexpr float kManaRestoreEpsilon = 0.001f;
    if (current_mana + kManaRestoreEpsilon < maximum_mana) {
        const auto original =
            GetX86HookTrampoline<PlayerActorApplyManaDeltaFn>(
                g_gameplay_keyboard_injection
                    .player_actor_apply_mana_delta_hook);
        if (original == nullptr) {
            return fail("The native mana writer is unavailable.");
        }
        (void)original(
            reinterpret_cast<void*>(player.actor_address),
            maximum_mana - current_mana,
            0);
        if (!TryReadProgressionMana(
                progression_address,
                &current_mana,
                &maximum_mana) ||
            !std::isfinite(current_mana) ||
            !std::isfinite(maximum_mana) ||
            current_mana + kManaRestoreEpsilon < maximum_mana) {
            return fail("The native mana writer did not restore the local pool.");
        }
    }

    if (resulting_mana != nullptr) {
        *resulting_mana = current_mana;
    }
    return true;
}

bool TakeLocalPlayerManaDeltaObservation(
    SDModLocalManaDeltaObservation* observation) {
    if (observation == nullptr) {
        return false;
    }
    std::lock_guard<std::mutex> lock(g_local_mana_delta_observation_mutex);
    *observation = g_local_mana_delta_observation;
    g_local_mana_delta_observation = SDModLocalManaDeltaObservation{};
    return observation->valid;
}

void ResetEarthBoulderDamageObservations() {
    std::lock_guard<std::mutex> lock(
        g_earth_boulder_damage_observation_mutex);
    g_earth_boulder_damage_observation_armed = true;
    g_next_earth_boulder_damage_observation_sequence = 1;
    g_earth_boulder_damage_observations.clear();
}

bool TakeEarthBoulderDamageObservations(
    std::vector<SDModEarthBoulderDamageObservation>* observations) {
    if (observations == nullptr) {
        return false;
    }
    std::lock_guard<std::mutex> lock(
        g_earth_boulder_damage_observation_mutex);
    *observations = std::move(g_earth_boulder_damage_observations);
    g_earth_boulder_damage_observations.clear();
    g_earth_boulder_damage_observation_armed = false;
    return !observations->empty();
}

void ResetEnemyDamageObservations() {
    std::lock_guard<std::mutex> lock(
        g_enemy_damage_observation_mutex);
    g_enemy_damage_observation_armed = true;
    g_next_enemy_damage_observation_sequence = 1;
    g_enemy_damage_observations.clear();
}

bool TakeEnemyDamageObservations(
    std::vector<SDModEnemyDamageObservation>* observations) {
    if (observations == nullptr) {
        return false;
    }
    std::lock_guard<std::mutex> lock(
        g_enemy_damage_observation_mutex);
    *observations = std::move(g_enemy_damage_observations);
    g_enemy_damage_observations.clear();
    return !observations->empty();
}

void ResetPlayerDamageObservations() {
    std::lock_guard<std::mutex> lock(
        g_player_damage_observation_mutex);
    g_player_damage_observation_armed = true;
    g_next_player_damage_observation_sequence = 1;
    g_player_damage_observations.clear();
}

bool TakePlayerDamageObservations(
    std::vector<SDModPlayerDamageObservation>* observations) {
    if (observations == nullptr) {
        return false;
    }
    std::lock_guard<std::mutex> lock(
        g_player_damage_observation_mutex);
    *observations = std::move(g_player_damage_observations);
    g_player_damage_observations.clear();
    return !observations->empty();
}
