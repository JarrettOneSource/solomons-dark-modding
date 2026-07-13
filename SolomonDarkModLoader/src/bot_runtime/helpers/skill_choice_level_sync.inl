void UpdateBotLevelProfileState(
    std::uint64_t bot_id,
    int level,
    int experience,
    int next_experience) {
    UpdateRuntimeState([&](RuntimeState& state) {
        auto* participant = FindBot(state, bot_id);
        if (participant == nullptr) {
            return;
        }
        participant->character_profile.level = level;
        participant->character_profile.experience = experience;
        participant->runtime.level = level;
        participant->runtime.experience_current = experience;
        if (next_experience > 0) {
            participant->runtime.experience_next = next_experience;
        }
    });
}

bool SyncNativeBotProgressionLevel(
    uintptr_t progression_address,
    uintptr_t source_progression_address,
    int level,
    int experience,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (progression_address == 0 || level <= 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    if (!EnsureBotOwnedProgressionMode(progression_address)) {
        return false;
    }

    std::int32_t level_before = 0;
    float xp_before = 0.0f;
    if (!memory.TryReadField(progression_address, kProgressionLevelOffset, &level_before) ||
        !memory.TryReadField(progression_address, kProgressionXpOffset, &xp_before) ||
        !std::isfinite(xp_before)) {
        return false;
    }

    float target_xp = static_cast<float>(experience);
    if (source_progression_address != 0) {
        float source_xp = 0.0f;
        if (!memory.TryReadField(source_progression_address, kProgressionXpOffset, &source_xp) ||
            !std::isfinite(source_xp)) {
            return false;
        }
        if (source_xp >= 0.0f && source_xp > target_xp) {
            target_xp = source_xp;
        }
    }

    if (experience >= 0 && target_xp >= 0.0f) {
        (void)memory.TryWriteField<float>(progression_address, kProgressionXpOffset, target_xp);
    }

    if (level_before >= level) {
        Log(
            "[bots] native level_up sync skipped; progression already at target. progression=" +
            HexString(progression_address) +
            " level_before=" + std::to_string(level_before) +
            " target_level=" + std::to_string(level) +
            " xp_before=" + std::to_string(xp_before) +
            " target_xp=" + std::to_string(target_xp));
        return true;
    }

    constexpr int kMaxNativeLevelUpCalls = 256;
    int level_after = level_before;
    int calls = 0;
    while (level_after < level && calls < kMaxNativeLevelUpCalls) {
        const auto previous_level = level_after;
        if (!CallNativeLevelUpSafe(progression_address, exception_code)) {
            return false;
        }

        ++calls;
        if (!memory.TryReadField(progression_address, kProgressionLevelOffset, &level_after)) {
            return false;
        }
        if (level_after <= previous_level) {
            break;
        }
    }

    float xp_after = 0.0f;
    float previous_threshold = 0.0f;
    float next_threshold = 0.0f;
    if (!memory.TryReadField(progression_address, kProgressionXpOffset, &xp_after) ||
        !memory.TryReadField(progression_address, kProgressionPreviousXpThresholdOffset, &previous_threshold) ||
        !memory.TryReadField(progression_address, kProgressionNextXpThresholdOffset, &next_threshold) ||
        !std::isfinite(xp_after) ||
        !std::isfinite(previous_threshold) ||
        !std::isfinite(next_threshold)) {
        return false;
    }
    const bool synced = level_after >= level;
    Log(
        "[bots] native level_up sync. progression=" + HexString(progression_address) +
        " level_before=" + std::to_string(level_before) +
        " level_after=" + std::to_string(level_after) +
        " target_level=" + std::to_string(level) +
        " calls=" + std::to_string(calls) +
        " xp_before=" + std::to_string(xp_before) +
        " xp_after=" + std::to_string(xp_after) +
        " previous_threshold=" + std::to_string(previous_threshold) +
        " next_threshold=" + std::to_string(next_threshold) +
        " synced=" + std::to_string(synced ? 1 : 0));
    return synced;
}
