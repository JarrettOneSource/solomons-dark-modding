bool QueueNativeEnemyDeathProbe(
    uintptr_t actor_address,
    uintptr_t expected_config_address,
    uintptr_t restore_config_address,
    std::uint64_t* request_serial,
    std::string* error_message) {
    if (request_serial != nullptr) {
        *request_serial = 0;
    }
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!g_gameplay_keyboard_injection.initialized) {
        if (error_message != nullptr) {
            *error_message = "Gameplay action pump is not initialized.";
        }
        return false;
    }
    uintptr_t current_config_address = 0;
    if (actor_address == 0 || expected_config_address == 0 ||
        kEnemyConfigOffset == 0 ||
        !ProcessMemory::Instance().TryReadField(
            actor_address,
            kEnemyConfigOffset,
            &current_config_address) ||
        current_config_address != expected_config_address) {
        if (error_message != nullptr) {
            *error_message = "Native enemy-death probe is invalid.";
        }
        return false;
    }

    std::lock_guard<std::mutex> lock(
        g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
    auto& pending =
        g_gameplay_keyboard_injection.pending_native_enemy_death_probes;
    if (pending.size() >= kQueuedGameplayWorldActionLimit) {
        if (error_message != nullptr) {
            *error_message = "The native enemy-death probe queue is full.";
        }
        return false;
    }

    PendingNativeEnemyDeathProbe request{};
    request.request_serial = g_gameplay_keyboard_injection
                                 .next_native_enemy_death_probe_serial++;
    if (g_gameplay_keyboard_injection.next_native_enemy_death_probe_serial ==
        0) {
        g_gameplay_keyboard_injection.next_native_enemy_death_probe_serial = 1;
    }
    request.actor_address = actor_address;
    request.expected_config_address = expected_config_address;
    request.restore_config_address = restore_config_address;
    pending.push_back(request);
    if (request_serial != nullptr) {
        *request_serial = request.request_serial;
    }
    return true;
}

bool GetNativeEnemyDeathProbeResult(
    std::uint64_t request_serial,
    bool* completed,
    bool* success,
    std::uint32_t* exception_code,
    bool* config_restored,
    std::string* error_message) {
    if (completed != nullptr) {
        *completed = false;
    }
    if (success != nullptr) {
        *success = false;
    }
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (config_restored != nullptr) {
        *config_restored = false;
    }
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (request_serial == 0) {
        return false;
    }

    std::lock_guard<std::mutex> lock(
        g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
    const auto& result =
        g_gameplay_keyboard_injection.native_enemy_death_probe_result;
    if (result.request_serial != request_serial) {
        return true;
    }
    if (completed != nullptr) {
        *completed = true;
    }
    if (success != nullptr) {
        *success = result.success;
    }
    if (exception_code != nullptr) {
        *exception_code = result.exception_code;
    }
    if (config_restored != nullptr) {
        *config_restored = result.config_restored;
    }
    if (error_message != nullptr) {
        *error_message = result.error;
    }
    return true;
}
