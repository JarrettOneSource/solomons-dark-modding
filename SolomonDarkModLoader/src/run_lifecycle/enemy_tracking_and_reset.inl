int ReadRoundedXpOrUnknown(uintptr_t address) {
    if (address == 0) {
        return -1;
    }

    const auto xp = ProcessMemory::Instance().ReadFieldOr<float>(address, kProgressionXpOffset, -1.0f);
    if (xp < 0.0f) {
        return -1;
    }

    return static_cast<int>(std::lround(xp));
}

int ReadEnemyType(uintptr_t enemy_address, uintptr_t fallback_config_address = 0) {
    auto& memory = ProcessMemory::Instance();
    const auto config_address = memory.ReadFieldOr<uintptr_t>(enemy_address, kEnemyConfigOffset, fallback_config_address);
    return memory.ReadFieldOr<int>(config_address, kEnemyTypeOffset, -1);
}

void RememberEnemyType(uintptr_t enemy_address, int enemy_type) {
    if (enemy_address == 0) {
        return;
    }

    std::lock_guard<std::mutex> lock(g_state.enemy_type_mutex);
    g_state.enemy_types_by_address[enemy_address] = enemy_type;
}

int LookupRememberedEnemyType(uintptr_t enemy_address) {
    if (enemy_address == 0) {
        return -1;
    }

    std::lock_guard<std::mutex> lock(g_state.enemy_type_mutex);
    const auto it = g_state.enemy_types_by_address.find(enemy_address);
    return it != g_state.enemy_types_by_address.end() ? it->second : -1;
}

void ForgetEnemyType(uintptr_t enemy_address) {
    if (enemy_address == 0) {
        return;
    }

    std::lock_guard<std::mutex> lock(g_state.enemy_type_mutex);
    g_state.enemy_types_by_address.erase(enemy_address);
}

void ClearRememberedEnemyTypes() {
    std::lock_guard<std::mutex> lock(g_state.enemy_type_mutex);
    g_state.enemy_types_by_address.clear();
}

void ResetRunLifecycleBookkeeping() {
    g_state.current_wave.store(0, std::memory_order_release);
    g_state.last_wave_spawner.store(0, std::memory_order_release);
    g_state.last_consumed_spell_click_serial.store(0, std::memory_order_release);
    g_state.run_start_tick_ms.store(0, std::memory_order_release);
    g_state.combat_prelude_only_suppression.store(false, std::memory_order_release);
    g_state.wave_start_enemy_tracking.store(false, std::memory_order_release);
    ClearRememberedEnemyTypes();
}

void CompleteRunLifecycleEnd(std::string_view reason, bool dispatch_lua) {
    ResetRunLifecycleBookkeeping();
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
