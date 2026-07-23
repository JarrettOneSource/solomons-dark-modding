bool QueueNativePoisonBehaviorProbe(
    std::uint64_t target_participant_id,
    std::int32_t duration_ticks,
    float damage_per_tick,
    std::int8_t source_slot,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!g_gameplay_keyboard_injection.initialized) {
        if (error_message != nullptr) {
            *error_message = "Gameplay action pump is not initialized.";
        }
        return false;
    }
    if (duration_ticks <= 0 ||
        duration_ticks > multiplayer::kParticipantPoisonMaxDurationTicks ||
        !std::isfinite(damage_per_tick) ||
        damage_per_tick < 0.0f ||
        damage_per_tick > 10000.0f ||
        source_slot < -1) {
        if (error_message != nullptr) {
            *error_message = "Native poison behavior probe is invalid.";
        }
        return false;
    }

    PendingNativePoisonBehaviorProbe request{};
    request.target_participant_id = target_participant_id;
    request.duration_ticks = duration_ticks;
    request.damage_per_tick = damage_per_tick;
    request.source_slot = source_slot;

    std::lock_guard<std::mutex> lock(
        g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
    auto& pending =
        g_gameplay_keyboard_injection.pending_native_poison_behavior_probes;
    if (pending.size() >= kQueuedGameplayWorldActionLimit) {
        if (error_message != nullptr) {
            *error_message = "The native poison behavior-probe queue is full.";
        }
        return false;
    }
    pending.push_back(request);
    return true;
}

bool QueueNativeMagicHitBehaviorProbe(
    float projectile_damage,
    float magic_damage,
    float poison_damage,
    std::uint32_t attempts,
    std::uint64_t target_participant_id,
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
    if (!std::isfinite(projectile_damage) ||
        projectile_damage < 0.0f ||
        projectile_damage > 10000.0f ||
        !std::isfinite(magic_damage) ||
        magic_damage < 0.0f ||
        magic_damage > 10000.0f ||
        !std::isfinite(poison_damage) ||
        poison_damage < 0.0f ||
        poison_damage > 10000.0f ||
        (projectile_damage <= 0.0f && magic_damage <= 0.0f &&
         poison_damage <= 0.0f) ||
        attempts == 0 ||
        attempts > 1000) {
        if (error_message != nullptr) {
            *error_message = "Native magic-hit behavior probe is invalid.";
        }
        return false;
    }

    std::lock_guard<std::mutex> lock(
        g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
    auto& pending = g_gameplay_keyboard_injection
                        .pending_native_magic_hit_behavior_probes;
    if (pending.size() >= kQueuedGameplayWorldActionLimit) {
        if (error_message != nullptr) {
            *error_message = "The native magic-hit behavior-probe queue is full.";
        }
        return false;
    }
    PendingNativeMagicHitBehaviorProbe request{};
    request.request_serial = g_gameplay_keyboard_injection
                                 .next_native_magic_hit_behavior_probe_serial++;
    if (g_gameplay_keyboard_injection
            .next_native_magic_hit_behavior_probe_serial == 0) {
        g_gameplay_keyboard_injection
            .next_native_magic_hit_behavior_probe_serial = 1;
    }
    request.projectile_damage = projectile_damage;
    request.magic_damage = magic_damage;
    request.poison_damage = poison_damage;
    request.attempts = attempts;
    request.target_participant_id = target_participant_id;
    pending.push_back(request);
    if (request_serial != nullptr) {
        *request_serial = request.request_serial;
    }
    return true;
}

bool GetNativeMagicHitBehaviorProbeResult(
    std::uint64_t request_serial,
    bool* completed,
    bool* success,
    float* hp_before,
    float* hp_after,
    std::string* error_message) {
    if (completed != nullptr) {
        *completed = false;
    }
    if (success != nullptr) {
        *success = false;
    }
    if (hp_before != nullptr) {
        *hp_before = 0.0f;
    }
    if (hp_after != nullptr) {
        *hp_after = 0.0f;
    }
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (request_serial == 0) {
        return false;
    }

    std::lock_guard<std::mutex> lock(
        g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
    const auto& result = g_gameplay_keyboard_injection
                             .native_magic_hit_behavior_probe_result;
    if (result.request_serial != request_serial) {
        return true;
    }
    if (completed != nullptr) {
        *completed = true;
    }
    if (success != nullptr) {
        *success = result.success;
    }
    if (hp_before != nullptr) {
        *hp_before = result.hp_before;
    }
    if (hp_after != nullptr) {
        *hp_after = result.hp_after;
    }
    if (error_message != nullptr) {
        *error_message = result.error;
    }
    return true;
}

bool QueueNativeStaffEffectProbe(
    uintptr_t source_actor,
    uintptr_t target_actor,
    std::uint32_t variant,
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
    if (source_actor == 0 ||
        target_actor == 0 ||
        kEnemyCurrentHpOffset == 0 ||
        variant > 4 ||
        !ProcessMemory::Instance().IsReadableRange(source_actor, sizeof(uintptr_t)) ||
        !ProcessMemory::Instance().IsReadableRange(
            target_actor + kEnemyCurrentHpOffset,
            sizeof(float))) {
        if (error_message != nullptr) {
            *error_message = "Native staff-effect probe is invalid.";
        }
        return false;
    }

    std::lock_guard<std::mutex> lock(
        g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
    auto& pending =
        g_gameplay_keyboard_injection.pending_native_staff_effect_probes;
    if (pending.size() >= kQueuedGameplayWorldActionLimit) {
        if (error_message != nullptr) {
            *error_message = "The native staff-effect probe queue is full.";
        }
        return false;
    }

    PendingNativeStaffEffectProbe request{};
    request.request_serial = g_gameplay_keyboard_injection
                                 .next_native_staff_effect_probe_serial++;
    if (g_gameplay_keyboard_injection
            .next_native_staff_effect_probe_serial == 0) {
        g_gameplay_keyboard_injection.next_native_staff_effect_probe_serial = 1;
    }
    request.source_actor = source_actor;
    request.target_actor = target_actor;
    request.variant = variant;
    pending.push_back(request);
    if (request_serial != nullptr) {
        *request_serial = request.request_serial;
    }
    return true;
}

bool GetNativeStaffEffectProbeResult(
    std::uint64_t request_serial,
    bool* completed,
    bool* success,
    float* hp_before,
    float* hp_after,
    std::string* error_message) {
    if (completed != nullptr) {
        *completed = false;
    }
    if (success != nullptr) {
        *success = false;
    }
    if (hp_before != nullptr) {
        *hp_before = 0.0f;
    }
    if (hp_after != nullptr) {
        *hp_after = 0.0f;
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
        g_gameplay_keyboard_injection.native_staff_effect_probe_result;
    if (result.request_serial != request_serial) {
        return true;
    }
    if (completed != nullptr) {
        *completed = true;
    }
    if (success != nullptr) {
        *success = result.success;
    }
    if (hp_before != nullptr) {
        *hp_before = result.hp_before;
    }
    if (hp_after != nullptr) {
        *hp_after = result.hp_after;
    }
    if (error_message != nullptr) {
        *error_message = result.error;
    }
    return true;
}
