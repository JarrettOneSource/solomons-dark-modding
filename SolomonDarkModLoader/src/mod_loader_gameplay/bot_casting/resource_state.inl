float ReadResolvedGameFloatOr(uintptr_t absolute_address, float fallback) {
    auto& memory = ProcessMemory::Instance();
    const auto resolved_address = memory.ResolveGameAddressOrZero(absolute_address);
    if (resolved_address == 0) {
        return fallback;
    }

    return memory.ReadValueOr<float>(resolved_address, fallback);
}

float ReadResolvedGameDoubleAsFloatOr(uintptr_t absolute_address, float fallback) {
    auto& memory = ProcessMemory::Instance();
    const auto resolved_address = memory.ResolveGameAddressOrZero(absolute_address);
    if (resolved_address == 0) {
        return fallback;
    }

    return static_cast<float>(memory.ReadValueOr<double>(resolved_address, static_cast<double>(fallback)));
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

    const auto object_type_id =
        memory.ReadFieldOr<std::uint32_t>(actor_address, kGameObjectTypeIdOffset, 0);
    if (!IsArenaEnemyActorHealthType(object_type_id)) {
        return false;
    }

    const auto hp =
        memory.ReadFieldOr<float>(actor_address, kEnemyCurrentHpOffset, 0.0f);
    auto max_hp = memory.ReadFieldOr<float>(actor_address, kEnemyMaxHpOffset, 0.0f);
    if (!std::isfinite(hp) || !std::isfinite(max_hp)) {
        return false;
    }
    if (max_hp <= 0.0f && hp > 0.0f) {
        max_hp = hp;
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

    const auto hp = memory.ReadFieldOr<float>(progression_address, kProgressionHpOffset, 0.0f);
    const auto max_hp =
        memory.ReadFieldOr<float>(progression_address, kProgressionMaxHpOffset, 0.0f);
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

struct ManaSpendResult {
    bool readable = false;
    bool spent = false;
    bool native_call_attempted = false;
    bool native_call_succeeded = false;
    float before = 0.0f;
    float after = 0.0f;
    float requested = 0.0f;
    float actual = 0.0f;
    std::uint32_t native_result = 0;
    DWORD native_exception_code = 0;
};

struct NativeBotManaDeltaShim {
    bool active = false;
    uintptr_t gameplay_address = 0;
    std::size_t local_actor_slot_offset = 0;
    uintptr_t saved_local_actor = 0;
    bool local_actor_slot_restore_needed = false;
};

bool TryReadProgressionMana(uintptr_t progression_address, float* mp, float* max_mp) {
    if (progression_address == 0 || mp == nullptr || max_mp == nullptr) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    if (!memory.IsReadableRange(progression_address + kProgressionMpOffset, sizeof(float)) ||
        !memory.IsReadableRange(progression_address + kProgressionMaxMpOffset, sizeof(float))) {
        return false;
    }
    const auto current = memory.ReadFieldOr<float>(progression_address, kProgressionMpOffset, 0.0f);
    const auto maximum =
        memory.ReadFieldOr<float>(progression_address, kProgressionMaxMpOffset, 0.0f);
    if (!std::isfinite(current) || !std::isfinite(maximum) || maximum <= 0.0f) {
        return false;
    }
    *mp = current;
    *max_mp = maximum;
    return true;
}

bool EnterNativeBotManaDeltaShim(
    const ParticipantEntityBinding* binding,
    NativeBotManaDeltaShim* state) {
    if (state == nullptr) {
        return false;
    }

    *state = NativeBotManaDeltaShim{};
    if (binding == nullptr || binding->actor_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t gameplay_address = 0;
    if (!TryResolveCurrentGameplayScene(&gameplay_address) || gameplay_address == 0) {
        *state = NativeBotManaDeltaShim{};
        return false;
    }

    // Native 0x0052B150 gates the mana-delta body on the local player actor
    // pointer at gameplay+0x1358 before mutating this actor's progression.
    const auto local_actor_slot_offset = kGameplayPlayerActorOffset;
    const auto saved_local_actor =
        memory.ReadFieldOr<uintptr_t>(gameplay_address, local_actor_slot_offset, 0);
    if (saved_local_actor != binding->actor_address &&
        !memory.TryWriteField<uintptr_t>(
            gameplay_address,
            local_actor_slot_offset,
            binding->actor_address)) {
        *state = NativeBotManaDeltaShim{};
        return false;
    }

    state->active = true;
    state->gameplay_address = gameplay_address;
    state->local_actor_slot_offset = local_actor_slot_offset;
    state->saved_local_actor = saved_local_actor;
    state->local_actor_slot_restore_needed = saved_local_actor != binding->actor_address;
    return true;
}

void LeaveNativeBotManaDeltaShim(const NativeBotManaDeltaShim& state) {
    if (!state.active) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    if (state.local_actor_slot_restore_needed &&
        state.gameplay_address != 0 &&
        state.local_actor_slot_offset != 0) {
        (void)memory.TryWriteField<uintptr_t>(
            state.gameplay_address,
            state.local_actor_slot_offset,
            state.saved_local_actor);
    }
}

ManaSpendResult TryApplyNativeBotManaDelta(
    const ParticipantEntityBinding* binding,
    uintptr_t progression_address,
    float actual_amount) {
    ManaSpendResult result{};
    result.requested = actual_amount;
    if (binding == nullptr || binding->actor_address == 0 ||
        !std::isfinite(actual_amount) || actual_amount < 0.0f) {
        return result;
    }

    float before = 0.0f;
    float max_mp = 0.0f;
    if (!TryReadProgressionMana(progression_address, &before, &max_mp)) {
        return result;
    }

    result.readable = true;
    result.before = before;
    result.after = before;
    if (actual_amount <= 0.0f) {
        result.spent = true;
        return result;
    }

    auto& memory = ProcessMemory::Instance();
    const auto actor_progression_handle =
        memory.ReadFieldOr<uintptr_t>(binding->actor_address, kActorProgressionHandleOffset, 0);
    const auto actor_progression_runtime =
        actor_progression_handle != 0 ? ReadSmartPointerInnerObject(actor_progression_handle) : 0;
    if (actor_progression_runtime != progression_address) {
        Log(
            "[bots] native mana delta skipped; actor progression mismatch. actor=" +
            HexString(binding->actor_address) +
            " actor_progression=" + HexString(actor_progression_runtime) +
            " requested_progression=" + HexString(progression_address));
        return result;
    }

    const auto apply_mana_delta_address =
        memory.ResolveGameAddressOrZero(kPlayerActorApplyManaDelta);
    if (apply_mana_delta_address == 0) {
        return result;
    }

    NativeBotManaDeltaShim shim;
    if (!EnterNativeBotManaDeltaShim(binding, &shim)) {
        return result;
    }

    result.native_call_attempted = true;
    result.native_call_succeeded =
        CallPlayerActorApplyManaDeltaSafe(
            apply_mana_delta_address,
            binding->actor_address,
            -actual_amount,
            1,
            &result.native_result,
            &result.native_exception_code);
    LeaveNativeBotManaDeltaShim(shim);

    if (!result.native_call_succeeded) {
        return result;
    }

    float after = before;
    float after_max_mp = 0.0f;
    if (!TryReadProgressionMana(progression_address, &after, &after_max_mp)) {
        return result;
    }

    result.after = after;
    const auto spent_amount = before - after;
    if (spent_amount <= 0.0f) {
        return result;
    }

    const auto expected_after = before > actual_amount ? before - actual_amount : 0.0f;
    constexpr float kManaSpendEpsilon = 0.01f;
    result.actual = spent_amount;
    result.spent =
        std::fabs(after - expected_after) <= kManaSpendEpsilon ||
        spent_amount + kManaSpendEpsilon >= actual_amount;
    return result;
}

ManaSpendResult TrySpendBotMana(
    const ParticipantEntityBinding* binding,
    uintptr_t progression_address,
    float requested_amount,
    bool allow_partial) {
    ManaSpendResult result{};
    result.requested = requested_amount;
    if (!std::isfinite(requested_amount) || requested_amount <= 0.0f) {
        result.spent = true;
        return result;
    }

    float before = 0.0f;
    float max_mp = 0.0f;
    if (!TryReadProgressionMana(progression_address, &before, &max_mp)) {
        return result;
    }
    result.readable = true;
    result.before = before;
    result.after = before;
    if (before <= 0.0f) {
        return result;
    }

    if (before + 0.001f < requested_amount && !allow_partial) {
        return result;
    }

    const float actual_amount =
        (allow_partial || before < requested_amount)
            ? (before < requested_amount ? before : requested_amount)
            : requested_amount;
    auto result_from_native =
        TryApplyNativeBotManaDelta(binding, progression_address, actual_amount);
    result_from_native.requested = requested_amount;
    return result_from_native;
}

int ReadEarthBoulderProgressionLevel(
    const ParticipantEntityBinding* binding,
    uintptr_t progression_runtime_address) {
    int level = binding != nullptr ? binding->character_profile.level : 1;
    auto& memory = ProcessMemory::Instance();
    if (progression_runtime_address != 0 &&
        kProgressionLevelOffset != 0 &&
        memory.IsReadableRange(progression_runtime_address + kProgressionLevelOffset, sizeof(int))) {
        level = memory.ReadFieldOr<int>(progression_runtime_address, kProgressionLevelOffset, level);
    }
    return level;
}

float ResolveEarthBoulderBaseDamage(
    const ParticipantEntityBinding* binding,
    uintptr_t progression_runtime_address,
    int* resolved_level) {
    const auto progression_level =
        ReadEarthBoulderProgressionLevel(binding, progression_runtime_address);
    NativePrimarySpellSelection selection{};
    if (!TryResolveNativePrimarySelectionFromSkillId(0x3F6, &selection)) {
        Log("[bots] failed to resolve native Earth boulder selection.");
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
    const auto scale =
        ReadResolvedGameDoubleAsFloatOr(kEarthBoulderDamageOutputScaleGlobal, 0.0f);
    if (!std::isfinite(scale) || scale <= 0.0f) {
        return 0.0f;
    }
    return scale;
}

float ResolveEarthBoulderReleaseDamageScale() {
    const auto scale =
        ReadResolvedGameDoubleAsFloatOr(kEarthBoulderReleaseDamageScaleGlobal, 0.0f);
    if (!std::isfinite(scale) || scale <= 0.0f) {
        return 0.0f;
    }
    return scale;
}

float ResolveEarthBoulderReleaseDamageFloor() {
    const auto floor =
        ReadResolvedGameDoubleAsFloatOr(kEarthBoulderReleaseDamageFloorGlobal, 0.0f);
    if (!std::isfinite(floor) || floor < 0.0f) {
        return 0.0f;
    }
    return floor;
}

float ResolveEarthBoulderReleaseDamageCapScale() {
    const auto scale =
        ReadResolvedGameDoubleAsFloatOr(kEarthBoulderReleaseDamageCapScaleGlobal, 0.0f);
    if (!std::isfinite(scale) || scale <= 0.0f) {
        return 0.0f;
    }
    return scale;
}

float ResolveEarthBoulderReleaseGrowthStopMinCharge() {
    const auto charge =
        ReadResolvedGameFloatOr(kEarthBoulderReleaseGrowthStopMinChargeGlobal, 0.0f);
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
    const auto object_type_id =
        memory.ReadFieldOr<std::uint32_t>(actor_address, kGameObjectTypeIdOffset, 0);
    if (IsArenaEnemyActorHealthType(object_type_id) &&
        TryReadArenaEnemyActorHealth(actor_address, &health)) {
        return health.max_hp > 0.0f && health.hp <= 0.0f;
    }

    if (TryReadActorProgressionHealth(actor_address, &health)) {
        return health.max_hp > 0.0f && health.hp <= 0.0f;
    }

    if (memory.ReadFieldOr<std::uint8_t>(actor_address, kEnemyDeathHandledOffset, 0) != 0) {
        return true;
    }
    return false;
}
