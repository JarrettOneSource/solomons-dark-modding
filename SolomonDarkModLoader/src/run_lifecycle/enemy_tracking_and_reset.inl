bool TryReadEnemyTypeFromConfig(uintptr_t config_address, int* enemy_type) {
    if (enemy_type == nullptr) {
        return false;
    }

    *enemy_type = -1;
    if (config_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    return memory.TryReadField(config_address, kEnemyTypeOffset, enemy_type) && *enemy_type >= 0;
}

bool TryReadEnemyTypeFromActor(uintptr_t enemy_address, int* enemy_type) {
    if (enemy_type == nullptr) {
        return false;
    }

    *enemy_type = -1;
    if (enemy_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t config_address = 0;
    return memory.TryReadField(enemy_address, kEnemyConfigOffset, &config_address) &&
           TryReadEnemyTypeFromConfig(config_address, enemy_type);
}

bool TryReadRunLifecycleRoundedXp(uintptr_t progression_address, int* experience) {
    if (experience == nullptr) {
        return false;
    }

    *experience = 0;
    if (progression_address == 0) {
        return false;
    }

    float xp = 0.0f;
    if (!ProcessMemory::Instance().TryReadField(progression_address, kProgressionXpOffset, &xp) ||
        !std::isfinite(xp) ||
        xp < 0.0f) {
        return false;
    }

    *experience = static_cast<int>(std::lround(xp));
    return true;
}

void RememberEnemyType(uintptr_t enemy_address, int enemy_type) {
    if (enemy_address == 0) {
        return;
    }

    std::lock_guard<std::mutex> lock(g_state.enemy_type_mutex);
    g_state.enemy_types_by_address[enemy_address] = enemy_type;
}

std::uint32_t RememberEnemySpawnSerial(uintptr_t enemy_address) {
    if (enemy_address == 0) {
        return 0;
    }

    std::lock_guard<std::mutex> lock(g_state.enemy_type_mutex);
    auto spawn_serial = g_state.next_enemy_spawn_serial++;
    if (spawn_serial == 0) {
        spawn_serial = g_state.next_enemy_spawn_serial++;
    }
    g_state.enemy_spawn_serials_by_address[enemy_address] = spawn_serial;
    return spawn_serial;
}

int LookupRememberedEnemyType(uintptr_t enemy_address) {
    if (enemy_address == 0) {
        return -1;
    }

    std::lock_guard<std::mutex> lock(g_state.enemy_type_mutex);
    const auto it = g_state.enemy_types_by_address.find(enemy_address);
    return it != g_state.enemy_types_by_address.end() ? it->second : -1;
}

bool LookupEnemySpawnSerial(uintptr_t enemy_address, std::uint32_t* spawn_serial) {
    if (spawn_serial == nullptr) {
        return false;
    }

    *spawn_serial = 0;
    if (enemy_address == 0) {
        return false;
    }

    std::lock_guard<std::mutex> lock(g_state.enemy_type_mutex);
    const auto it = g_state.enemy_spawn_serials_by_address.find(enemy_address);
    if (it == g_state.enemy_spawn_serials_by_address.end() || it->second == 0) {
        return false;
    }
    *spawn_serial = it->second;
    return true;
}

void ForgetEnemyType(uintptr_t enemy_address) {
    if (enemy_address == 0) {
        return;
    }

    std::lock_guard<std::mutex> lock(g_state.enemy_type_mutex);
    g_state.enemy_types_by_address.erase(enemy_address);
    g_state.enemy_spawn_serials_by_address.erase(enemy_address);
}

void ClearRememberedEnemyTracking() {
    std::lock_guard<std::mutex> lock(g_state.enemy_type_mutex);
    g_state.enemy_types_by_address.clear();
    g_state.enemy_spawn_serials_by_address.clear();
    g_state.next_enemy_spawn_serial = 1;
}

void ResetRunLifecycleBookkeeping(bool clear_enemy_tracking = true) {
    g_state.current_wave.store(0, std::memory_order_release);
    g_state.last_wave_spawner.store(0, std::memory_order_release);
    g_state.last_consumed_spell_click_serial.store(0, std::memory_order_release);
    g_state.run_start_tick_ms.store(0, std::memory_order_release);
    g_state.combat_prelude_only_suppression.store(false, std::memory_order_release);
    g_state.wave_start_enemy_tracking.store(false, std::memory_order_release);
    if (clear_enemy_tracking) {
        ClearRememberedEnemyTracking();
    }
}

void CompleteRunLifecycleEnd(
    std::string_view reason,
    bool dispatch_lua,
    bool clear_enemy_tracking = true) {
    ResetRunLifecycleBookkeeping(clear_enemy_tracking);
    multiplayer::SetAllBotSceneIntentsToSharedHub();
    if (dispatch_lua) {
        std::string reason_string;
        if (reason.empty()) {
            reason_string = "unknown";
        } else {
            reason_string.assign(reason.data(), reason.size());
        }
        DispatchLuaRunEnded(reason_string.c_str());
    }
}
