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
constexpr std::size_t kArenaEnemyMaxHpOffset = 0x170;
constexpr std::size_t kArenaEnemyCurrentHpOffset = 0x174;
constexpr std::size_t kArenaEnemyHealthReadSize = kArenaEnemyCurrentHpOffset + sizeof(float);

bool IsArenaEnemyActorHealthType(std::uint32_t object_type_id) {
    return object_type_id == 1001;
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
    if (!memory.IsReadableRange(actor_address, kArenaEnemyHealthReadSize)) {
        return false;
    }

    const auto object_type_id =
        memory.ReadFieldOr<std::uint32_t>(actor_address, kGameObjectTypeIdOffset, 0);
    if (!IsArenaEnemyActorHealthType(object_type_id)) {
        return false;
    }

    const auto hp =
        memory.ReadFieldOr<float>(actor_address, kArenaEnemyCurrentHpOffset, 0.0f);
    auto max_hp = memory.ReadFieldOr<float>(actor_address, kArenaEnemyMaxHpOffset, 0.0f);
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
    health->current_hp_offset = kArenaEnemyCurrentHpOffset;
    health->max_hp_offset = kArenaEnemyMaxHpOffset;
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
    float before = 0.0f;
    float after = 0.0f;
    float requested = 0.0f;
    float actual = 0.0f;
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

ManaSpendResult TrySpendProgressionMana(
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
    if (before <= 0.0f) {
        result.after = before;
        return result;
    }

    const float actual_amount =
        allow_partial && before < requested_amount ? before : requested_amount;
    if (before + 0.001f < requested_amount && !allow_partial) {
        result.after = before;
        return result;
    }
    const float after = before > actual_amount ? before - actual_amount : 0.0f;
    auto& memory = ProcessMemory::Instance();
    result.spent =
        memory.TryWriteField<float>(progression_address, kProgressionMpOffset, after);
    if (result.spent) {
        result.after = after;
        result.actual = actual_amount;
    } else {
        result.after = before;
    }
    return result;
}

constexpr std::array<float, 26> kEarthBoulderBaseDamageByLevel = {
    0.0f,   10.0f,  30.0f,  50.0f,  75.0f,  100.0f, 120.0f, 140.0f, 160.0f,
    180.0f, 200.0f, 220.0f, 240.0f, 260.0f, 280.0f, 300.0f, 320.0f, 340.0f,
    360.0f, 380.0f, 400.0f, 420.0f, 440.0f, 460.0f, 480.0f, 500.0f,
};

int ResolveEarthBoulderStatbookLevel(
    const ParticipantEntityBinding* binding,
    uintptr_t progression_runtime_address) {
    int level = binding != nullptr ? binding->character_profile.level : 1;
    auto& memory = ProcessMemory::Instance();
    if (progression_runtime_address != 0 &&
        kProgressionLevelOffset != 0 &&
        memory.IsReadableRange(progression_runtime_address + kProgressionLevelOffset, sizeof(int))) {
        level = memory.ReadFieldOr<int>(progression_runtime_address, kProgressionLevelOffset, level);
    }
    if (level < 1) {
        return 1;
    }
    const auto max_level = static_cast<int>(kEarthBoulderBaseDamageByLevel.size()) - 1;
    return level > max_level ? max_level : level;
}

float ResolveEarthBoulderBaseDamage(
    const ParticipantEntityBinding* binding,
    uintptr_t progression_runtime_address,
    int* resolved_level) {
    const auto level = ResolveEarthBoulderStatbookLevel(binding, progression_runtime_address);
    if (resolved_level != nullptr) {
        *resolved_level = level;
    }
    return kEarthBoulderBaseDamageByLevel[static_cast<std::size_t>(level)];
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
