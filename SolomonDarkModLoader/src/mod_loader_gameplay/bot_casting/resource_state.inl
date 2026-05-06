bool TryReadResolvedGameFloat(uintptr_t absolute_address, float* value) {
    if (value == nullptr) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto resolved_address = memory.ResolveGameAddressOrZero(absolute_address);
    if (resolved_address == 0) {
        return false;
    }

    return memory.TryReadValue(resolved_address, value);
}

bool TryReadResolvedGameDoubleAsFloat(uintptr_t absolute_address, float* value) {
    if (value == nullptr) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto resolved_address = memory.ResolveGameAddressOrZero(absolute_address);
    if (resolved_address == 0) {
        return false;
    }

    double native_value = 0.0;
    if (!memory.TryReadValue(resolved_address, &native_value)) {
        return false;
    }

    *value = static_cast<float>(native_value);
    return true;
}

constexpr std::int32_t kSuppressedSelectionRetargetTicks = 60;

bool IsArenaEnemyActorHealthType(std::uint32_t object_type_id) {
    return IsArenaCombatActorTypeInternal(object_type_id);
}

struct ActorHealthRuntime {
    uintptr_t base_address = 0;
    std::size_t current_hp_offset = 0;
    std::size_t max_hp_offset = 0;
    uintptr_t progression_address = 0;
    const char* kind = "unknown";
    float hp = 0.0f;
    float max_hp = 0.0f;
};

bool TryReadArenaEnemyActorHealth(uintptr_t actor_address, ActorHealthRuntime* health) {
    if (actor_address == 0 || health == nullptr) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    if (!memory.IsReadableRange(actor_address + kEnemyCurrentHpOffset, sizeof(float)) ||
        !memory.IsReadableRange(actor_address + kEnemyMaxHpOffset, sizeof(float))) {
        return false;
    }

    std::uint32_t object_type_id = 0;
    if (!memory.TryReadField(actor_address, kGameObjectTypeIdOffset, &object_type_id)) {
        return false;
    }
    if (!IsArenaEnemyActorHealthType(object_type_id)) {
        return false;
    }

    float hp = 0.0f;
    float max_hp = 0.0f;
    if (!memory.TryReadField(actor_address, kEnemyCurrentHpOffset, &hp) ||
        !memory.TryReadField(actor_address, kEnemyMaxHpOffset, &max_hp)) {
        return false;
    }
    if (!std::isfinite(hp) || !std::isfinite(max_hp)) {
        return false;
    }
    if (max_hp <= 0.0f) {
        return false;
    }

    health->base_address = actor_address;
    health->current_hp_offset = kEnemyCurrentHpOffset;
    health->max_hp_offset = kEnemyMaxHpOffset;
    health->progression_address = 0;
    health->kind = "arena_enemy";
    health->hp = hp;
    health->max_hp = max_hp;
    return true;
}

bool TryReadActorProgressionHealth(uintptr_t actor_address, ActorHealthRuntime* health) {
    if (actor_address == 0 || health == nullptr) {
        return false;
    }

    uintptr_t progression_address = 0;
    if (!TryResolveActorProgressionRuntime(actor_address, &progression_address) ||
        progression_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    if (!memory.IsReadableRange(progression_address + kProgressionHpOffset, sizeof(float)) ||
        !memory.IsReadableRange(progression_address + kProgressionMaxHpOffset, sizeof(float))) {
        return false;
    }

    float hp = 0.0f;
    float max_hp = 0.0f;
    if (!memory.TryReadField(progression_address, kProgressionHpOffset, &hp) ||
        !memory.TryReadField(progression_address, kProgressionMaxHpOffset, &max_hp)) {
        return false;
    }
    if (!std::isfinite(hp) || !std::isfinite(max_hp) || max_hp <= 0.0f) {
        return false;
    }

    health->base_address = progression_address;
    health->current_hp_offset = kProgressionHpOffset;
    health->max_hp_offset = kProgressionMaxHpOffset;
    health->progression_address = progression_address;
    health->kind = "progression";
    health->hp = hp;
    health->max_hp = max_hp;
    return true;
}

bool TryReadActorHealthRuntime(uintptr_t actor_address, ActorHealthRuntime* health) {
    if (actor_address == 0 || health == nullptr) {
        return false;
    }
    if (TryReadArenaEnemyActorHealth(actor_address, health)) {
        return true;
    }
    return TryReadActorProgressionHealth(actor_address, health);
}

bool TryReadProgressionMana(uintptr_t progression_address, float* mp, float* max_mp) {
    if (progression_address == 0 || mp == nullptr || max_mp == nullptr) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    if (!memory.IsReadableRange(progression_address + kProgressionMpOffset, sizeof(float)) ||
        !memory.IsReadableRange(progression_address + kProgressionMaxMpOffset, sizeof(float))) {
        return false;
    }
    float current = 0.0f;
    float maximum = 0.0f;
    if (!memory.TryReadField(progression_address, kProgressionMpOffset, &current) ||
        !memory.TryReadField(progression_address, kProgressionMaxMpOffset, &maximum)) {
        return false;
    }
    if (!std::isfinite(current) || !std::isfinite(maximum) || maximum <= 0.0f) {
        return false;
    }
    *mp = current;
    *max_mp = maximum;
    return true;
}

struct NativeManaRateConfigValidation {
    bool required = false;
    bool invalidated = false;
    bool readable = false;
    bool plausible = true;
    float native_rate = 0.0f;
    float expected_rate = 0.0f;
    float max_allowed_rate = 0.0f;
    const char* reason = "not_required";
};

bool NativeManaRateConfigRequiredForOngoingCast(
    const ParticipantEntityBinding::OngoingCastState& ongoing) {
    return ongoing.active &&
           ongoing.uses_dispatcher_skill_id &&
           ongoing.mana_charge_kind == multiplayer::BotManaChargeKind::PerSecond &&
           std::isfinite(ongoing.mana_cost) &&
           ongoing.mana_cost > 0.0f;
}

bool ClearNativeManaRateConfigForOngoingCast(
    uintptr_t actor_address,
    const ParticipantEntityBinding::OngoingCastState& ongoing) {
    if (actor_address == 0 || !NativeManaRateConfigRequiredForOngoingCast(ongoing)) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    if (kActorSpellConfig2d0Offset == 0 ||
        !memory.IsReadableRange(actor_address + kActorSpellConfig2d0Offset, sizeof(float))) {
        return false;
    }
    return memory.TryWriteField<float>(actor_address, kActorSpellConfig2d0Offset, 0.0f);
}

NativeManaRateConfigValidation ValidateNativeManaRateConfigForOngoingCast(
    uintptr_t actor_address,
    const ParticipantEntityBinding::OngoingCastState& ongoing) {
    NativeManaRateConfigValidation validation{};
    validation.required = NativeManaRateConfigRequiredForOngoingCast(ongoing);
    validation.invalidated = ongoing.native_mana_rate_config_invalidated;
    validation.expected_rate = ongoing.mana_cost;
    if (!validation.required) {
        return validation;
    }

    validation.plausible = false;
    const auto rate_ceiling = std::fabs(validation.expected_rate) * 4.0f;
    validation.max_allowed_rate = rate_ceiling > 0.01f ? rate_ceiling : 0.01f;
    if (!validation.invalidated) {
        validation.reason = "not_invalidated";
        return validation;
    }
    if (actor_address == 0 || kActorSpellConfig2d0Offset == 0) {
        validation.reason = "address_unavailable";
        return validation;
    }

    auto& memory = ProcessMemory::Instance();
    if (!memory.IsReadableRange(actor_address + kActorSpellConfig2d0Offset, sizeof(float))) {
        validation.reason = "unreadable";
        return validation;
    }

    if (!memory.TryReadField(actor_address, kActorSpellConfig2d0Offset, &validation.native_rate)) {
        validation.reason = "unreadable";
        return validation;
    }
    validation.readable = true;
    if (!std::isfinite(validation.native_rate) || validation.native_rate <= 0.0f) {
        validation.reason = "pending";
        return validation;
    }

    if (validation.native_rate > validation.max_allowed_rate) {
        validation.reason = "mismatch";
        return validation;
    }

    validation.plausible = true;
    validation.reason = "ready";
    return validation;
}

bool TryReadEarthBoulderProgressionLevel(
    uintptr_t progression_runtime_address,
    int* level) {
    if (level == nullptr) {
        return false;
    }
    *level = 0;
    if (progression_runtime_address == 0 || kProgressionLevelOffset == 0) {
        return false;
    }
    auto& memory = ProcessMemory::Instance();
    if (!memory.IsReadableRange(progression_runtime_address + kProgressionLevelOffset, sizeof(int)) ||
        !memory.TryReadField(progression_runtime_address, kProgressionLevelOffset, level)) {
        *level = 0;
        return false;
    }
    if (*level <= 0) {
        *level = 0;
        return false;
    }
    return true;
}

float ResolveEarthBoulderBaseDamage(
    const ParticipantEntityBinding* binding,
    uintptr_t progression_runtime_address,
    int* resolved_level) {
    (void)binding;
    int progression_level = 0;
    if (!TryReadEarthBoulderProgressionLevel(progression_runtime_address, &progression_level)) {
        Log(
            "[bots] failed to resolve native Earth boulder progression level. progression=" +
            HexString(progression_runtime_address));
        if (resolved_level != nullptr) {
            *resolved_level = 0;
        }
        return 0.0f;
    }
    NativePrimarySpellSelection selection{};
    const auto earth_primary_entry = ResolveNativePrimaryEntryForElement(2);
    std::string selection_error;
    if (!TryResolveNativePrimarySelectionFromLiveProgression(
            progression_runtime_address,
            earth_primary_entry,
            earth_primary_entry,
            &selection,
            &selection_error)) {
        Log("[bots] failed to resolve native Earth boulder selection. error=" + selection_error);
        if (resolved_level != nullptr) {
            *resolved_level = progression_level;
        }
        return 0.0f;
    }

    NativePrimarySpellStats stats{};
    std::string error_message;
    if (!TryResolveNativePrimarySpellStats(
            progression_runtime_address,
            selection,
            &stats,
            &error_message)) {
        Log(
            "[bots] failed to resolve native Earth boulder damage. progression=" +
            HexString(progression_runtime_address) +
            " progression_level=" + std::to_string(progression_level) +
            " error=" + error_message);
        if (resolved_level != nullptr) {
            *resolved_level = progression_level;
        }
        return 0.0f;
    }

    if (resolved_level != nullptr) {
        *resolved_level = stats.progression_level;
    }
    return stats.damage;
}

float ResolveEarthBoulderDamageOutputScale() {
    float scale = 0.0f;
    if (!TryReadResolvedGameDoubleAsFloat(kEarthBoulderDamageOutputScaleGlobal, &scale)) {
        return 0.0f;
    }
    if (!std::isfinite(scale) || scale <= 0.0f) {
        return 0.0f;
    }
    return scale;
}

float ResolveEarthBoulderReleaseDamageScale() {
    float scale = 0.0f;
    if (!TryReadResolvedGameDoubleAsFloat(kEarthBoulderReleaseDamageScaleGlobal, &scale)) {
        return 0.0f;
    }
    if (!std::isfinite(scale) || scale <= 0.0f) {
        return 0.0f;
    }
    return scale;
}

float ResolveEarthBoulderReleaseDamageFloor() {
    float floor = 0.0f;
    if (!TryReadResolvedGameDoubleAsFloat(kEarthBoulderReleaseDamageFloorGlobal, &floor)) {
        return 0.0f;
    }
    if (!std::isfinite(floor) || floor < 0.0f) {
        return 0.0f;
    }
    return floor;
}

float ResolveEarthBoulderReleaseDamageCapScale() {
    float scale = 0.0f;
    if (!TryReadResolvedGameDoubleAsFloat(kEarthBoulderReleaseDamageCapScaleGlobal, &scale)) {
        return 0.0f;
    }
    if (!std::isfinite(scale) || scale <= 0.0f) {
        return 0.0f;
    }
    return scale;
}

float ResolveEarthBoulderReleaseGrowthStopMinCharge() {
    float charge = 0.0f;
    if (!TryReadResolvedGameFloat(kEarthBoulderReleaseGrowthStopMinChargeGlobal, &charge)) {
        return 0.0f;
    }
    if (!std::isfinite(charge) || charge < 0.0f) {
        return 0.0f;
    }
    return charge;
}

bool IsActorRuntimeDead(uintptr_t actor_address) {
    if (actor_address == 0) {
        return false;
    }

    ActorHealthRuntime health;
    auto& memory = ProcessMemory::Instance();
    std::uint32_t object_type_id = 0;
    if (!memory.TryReadField(actor_address, kGameObjectTypeIdOffset, &object_type_id)) {
        return false;
    }
    if (IsArenaEnemyActorHealthType(object_type_id) &&
        TryReadArenaEnemyActorHealth(actor_address, &health)) {
        return health.max_hp > 0.0f && health.hp <= 0.0f;
    }

    if (TryReadActorProgressionHealth(actor_address, &health)) {
        return health.max_hp > 0.0f && health.hp <= 0.0f;
    }

    std::uint8_t death_handled = 0;
    if (memory.TryReadField(actor_address, kEnemyDeathHandledOffset, &death_handled) &&
        death_handled != 0) {
        return true;
    }
    return false;
}
