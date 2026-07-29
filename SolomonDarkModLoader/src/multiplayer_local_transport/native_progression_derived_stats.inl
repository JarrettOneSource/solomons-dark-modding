bool TryCaptureNativeParticipantDerivedStats(
    uintptr_t progression_address,
    SDModDerivedProgressionStatState* captured) {
    if (captured == nullptr) {
        return false;
    }
    *captured = SDModDerivedProgressionStatState{};
    if (progression_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto read_float = [&](std::size_t offset, float* value) {
        return offset != 0 &&
               memory.TryReadField(progression_address, offset, value) &&
               std::isfinite(*value) &&
               std::fabs(*value) <= 1000000.0f;
    };
    const bool complete =
        read_float(
            kProgressionCastSpeedMultiplierOffset,
            &captured->cast_speed_multiplier) &&
        read_float(
            kProgressionManaRecoveryMultiplierOffset,
            &captured->mana_recovery_multiplier) &&
        read_float(
            kProgressionResistMagicFractionOffset,
            &captured->resist_magic_fraction) &&
        read_float(
            kProgressionResistPoisonFractionOffset,
            &captured->resist_poison_fraction) &&
        read_float(
            kProgressionDeflectChanceOffset,
            &captured->deflect_chance) &&
        read_float(
            kProgressionStaffMeleeDamageAOffset,
            &captured->staff_melee_damage_a) &&
        read_float(
            kProgressionStaffMeleeDamageBOffset,
            &captured->staff_melee_damage_b) &&
        read_float(
            kProgressionPickupRangeOffset,
            &captured->pickup_range) &&
        read_float(
            kProgressionSecondaryRechargeMultiplierOffset,
            &captured->secondary_recharge_multiplier) &&
        read_float(
            kProgressionOffensiveDamageMultiplierOffset,
            &captured->offensive_damage_multiplier) &&
        read_float(
            kProgressionOffensiveManaMultiplierOffset,
            &captured->offensive_mana_multiplier) &&
        read_float(
            kProgressionMeleeDamageMultiplierOffset,
            &captured->melee_damage_multiplier) &&
        read_float(
            kProgressionPushStrengthOffset,
            &captured->push_strength) &&
        read_float(
            kProgressionMeditationRecoveryBonusOffset,
            &captured->meditation_recovery_bonus) &&
        kProgressionMeditationIdleTicksOffset != 0 &&
        memory.TryReadField(
            progression_address,
            kProgressionMeditationIdleTicksOffset,
            &captured->meditation_idle_ticks) &&
        captured->meditation_idle_ticks >= -1 &&
        captured->meditation_idle_ticks <= 1000000000;
    captured->valid = complete;
    return complete;
}

bool ApplyAuthoritativeParticipantDerivedStats(
    uintptr_t progression_address,
    const ParticipantDerivedStatState& desired,
    int* write_count) {
    if (write_count != nullptr) {
        *write_count = 0;
    }
    if (progression_address == 0 || !desired.valid) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    int writes = 0;
    const auto reconcile_float = [&](std::size_t offset, float value) {
        if (offset == 0 || !std::isfinite(value) ||
            std::fabs(value) > 1000000.0f) {
            return false;
        }
        float current = 0.0f;
        if (!memory.TryReadField(progression_address, offset, &current) ||
            !std::isfinite(current)) {
            return false;
        }
        if (std::fabs(current - value) <= 0.00001f) {
            return true;
        }
        float verified = 0.0f;
        if (!memory.TryWriteField(progression_address, offset, value) ||
            !memory.TryReadField(progression_address, offset, &verified) ||
            !std::isfinite(verified) ||
            std::fabs(verified - value) > 0.00001f) {
            return false;
        }
        ++writes;
        return true;
    };

    bool complete =
        reconcile_float(
            kProgressionCastSpeedMultiplierOffset,
            desired.cast_speed_multiplier) &&
        reconcile_float(
            kProgressionManaRecoveryMultiplierOffset,
            desired.mana_recovery_multiplier) &&
        reconcile_float(
            kProgressionResistMagicFractionOffset,
            desired.resist_magic_fraction) &&
        reconcile_float(
            kProgressionResistPoisonFractionOffset,
            desired.resist_poison_fraction) &&
        reconcile_float(kProgressionDeflectChanceOffset, desired.deflect_chance) &&
        reconcile_float(
            kProgressionStaffMeleeDamageAOffset,
            desired.staff_melee_damage_a) &&
        reconcile_float(
            kProgressionStaffMeleeDamageBOffset,
            desired.staff_melee_damage_b) &&
        reconcile_float(kProgressionPickupRangeOffset, desired.pickup_range) &&
        reconcile_float(
            kProgressionSecondaryRechargeMultiplierOffset,
            desired.secondary_recharge_multiplier) &&
        reconcile_float(
            kProgressionOffensiveDamageMultiplierOffset,
            desired.offensive_damage_multiplier) &&
        reconcile_float(
            kProgressionOffensiveManaMultiplierOffset,
            desired.offensive_mana_multiplier) &&
        reconcile_float(
            kProgressionMeleeDamageMultiplierOffset,
            desired.melee_damage_multiplier) &&
        reconcile_float(
            kProgressionPushStrengthOffset,
            desired.push_strength) &&
        reconcile_float(
            kProgressionMeditationRecoveryBonusOffset,
            desired.meditation_recovery_bonus);

    std::int32_t current_idle_ticks = 0;
    if (kProgressionMeditationIdleTicksOffset == 0 ||
        desired.meditation_idle_ticks < -1 ||
        desired.meditation_idle_ticks > 1000000000 ||
        !memory.TryReadField(
            progression_address,
            kProgressionMeditationIdleTicksOffset,
            &current_idle_ticks)) {
        complete = false;
    } else if (current_idle_ticks != desired.meditation_idle_ticks) {
        std::int32_t verified_idle_ticks = 0;
        if (!memory.TryWriteField(
                progression_address,
                kProgressionMeditationIdleTicksOffset,
                desired.meditation_idle_ticks) ||
            !memory.TryReadField(
                progression_address,
                kProgressionMeditationIdleTicksOffset,
                &verified_idle_ticks) ||
            verified_idle_ticks != desired.meditation_idle_ticks) {
            complete = false;
        } else {
            ++writes;
        }
    }

    if (write_count != nullptr) {
        *write_count = writes;
    }
    return complete;
}
