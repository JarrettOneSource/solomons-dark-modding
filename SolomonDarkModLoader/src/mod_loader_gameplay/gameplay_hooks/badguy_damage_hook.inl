struct HagathaCurseBossesDamageLaneSnapshot {
    std::array<float, 2> lanes{};
    bool restore_failed = false;
};

bool HasHagathaPerkFlag(
    uintptr_t progression_address,
    std::uint8_t selector) {
    if (progression_address == 0 ||
        kProgressionHagathaPerkFlagBaseOffset == 0) {
        return false;
    }

    std::uint8_t enabled = 0;
    return ProcessMemory::Instance().TryReadField(
               progression_address,
               kProgressionHagathaPerkFlagBaseOffset + selector,
               &enabled) &&
           enabled != 0;
}

bool RestoreHagathaCurseBossesDamageLanes(
    const HagathaCurseBossesDamageLaneSnapshot& snapshot) {
    const auto primary_address =
        g_gameplay_keyboard_injection.damage_context_primary_address;
    if (primary_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    bool restored = true;
    for (std::size_t index = 0; index < snapshot.lanes.size(); ++index) {
        restored = memory.TryWriteValue(
                       primary_address + index * sizeof(float),
                       snapshot.lanes[index]) &&
                   restored;
    }
    return restored;
}

bool TryApplyHagathaCurseBossesDamageMultiplier(
    HagathaCurseBossesDamageLaneSnapshot* snapshot) {
    if (snapshot == nullptr) {
        return false;
    }
    *snapshot = HagathaCurseBossesDamageLaneSnapshot{};

    const auto primary_address =
        g_gameplay_keyboard_injection.damage_context_primary_address;
    if (primary_address == 0 ||
        g_gameplay_keyboard_injection.damage_context_secondary_address !=
            primary_address + sizeof(float)) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    bool captured = true;
    for (std::size_t index = 0; index < snapshot->lanes.size(); ++index) {
        captured = memory.TryReadValue(
                       primary_address + index * sizeof(float),
                       &snapshot->lanes[index]) &&
                   captured;
    }
    if (!captured ||
        !std::all_of(
            snapshot->lanes.begin(),
            snapshot->lanes.end(),
            [](float value) { return std::isfinite(value) && value >= 0.0f; }) ||
        std::none_of(
            snapshot->lanes.begin(),
            snapshot->lanes.end(),
            [](float value) { return value > 0.0f; })) {
        return false;
    }

    std::array<float, 2> multiplied{};
    for (std::size_t index = 0; index < multiplied.size(); ++index) {
        multiplied[index] =
            snapshot->lanes[index] * kHagathaCurseBossesDamageMultiplier;
        if (!std::isfinite(multiplied[index])) {
            return false;
        }
    }

    bool wrote_all = true;
    for (std::size_t index = 0; index < multiplied.size(); ++index) {
        wrote_all = memory.TryWriteValue(
                        primary_address + index * sizeof(float),
                        multiplied[index]) &&
                    wrote_all;
    }
    if (wrote_all) {
        return true;
    }

    snapshot->restore_failed =
        !RestoreHagathaCurseBossesDamageLanes(*snapshot);
    return false;
}

std::uint8_t __fastcall HookBadguyDamage(
    void* self,
    void* /*unused_edx*/) {
    const auto original = GetX86HookTrampoline<BadguyDamageFn>(
        g_gameplay_keyboard_injection.badguy_damage_hook);
    if (original == nullptr) {
        return 0;
    }

    const auto actor_address = reinterpret_cast<uintptr_t>(self);
    auto& memory = ProcessMemory::Instance();
    std::uint32_t native_type_id = 0;
    uintptr_t context_source = 0;
    if (actor_address == 0 ||
        !memory.TryReadField(
            actor_address,
            kGameObjectTypeIdOffset,
            &native_type_id) ||
        !IsHagathaCurseBossesNativeType(native_type_id) ||
        !memory.TryReadValue(
            g_gameplay_keyboard_injection.damage_context_source_address,
            &context_source)) {
        return original(self);
    }

    uintptr_t source_progression = 0;
    if (!TryResolveDamageSourceProgressionAddress(
            context_source,
            &source_progression) ||
        !HasHagathaPerkFlag(
            source_progression,
            kHagathaCurseBossesSelector)) {
        return original(self);
    }

    HagathaCurseBossesDamageLaneSnapshot snapshot;
    if (!TryApplyHagathaCurseBossesDamageMultiplier(&snapshot)) {
        if (snapshot.restore_failed) {
            Log(
                "[gameplay] Curse Bosses damage transaction rejected after "
                "restore failure. target=" + HexString(actor_address) +
                " source=" + HexString(context_source));
            ResetActiveDamageContext();
            return 0;
        }
        return original(self);
    }

    const auto result = original(self);
    if (!RestoreHagathaCurseBossesDamageLanes(snapshot)) {
        Log(
            "[gameplay] Curse Bosses damage transaction restore failed. "
            "target=" + HexString(actor_address) +
            " source=" + HexString(context_source) +
            " participant_id=" +
                std::to_string(
                    ResolveDamageSourceParticipantId(context_source)));
        ResetActiveDamageContext();
    }
    return result;
}
