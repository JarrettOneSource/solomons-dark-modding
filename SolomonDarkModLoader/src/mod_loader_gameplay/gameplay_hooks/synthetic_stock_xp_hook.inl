struct SyntheticStockXpCapture {
    bool eligible = false;
    std::uint64_t participant_id = 0;
    uintptr_t progression_address = 0;
    std::uint32_t enemy_type = 0;
    int wave = 0;
    float hp_before = 0.0f;
    std::uint8_t death_handled_before = 0;
    float base_reward = 0.0f;
    float gameplay_multiplier = 0.0f;
    int level_before = 0;
    float xp_before = 0.0f;
};

SyntheticStockXpCapture CaptureSyntheticStockXpBeforeDamage(
    uintptr_t enemy_actor_address,
    uintptr_t source_actor_address) {
    SyntheticStockXpCapture capture;
    if (!multiplayer::IsLuaModSimulationAuthority() ||
        enemy_actor_address == 0 ||
        source_actor_address == 0) {
        return capture;
    }

    capture.participant_id =
        ResolveDamageSourceParticipantId(source_actor_address);
    const auto runtime = multiplayer::SnapshotRuntimeState();
    const auto* participant = multiplayer::FindParticipant(
        runtime,
        capture.participant_id);
    if (participant == nullptr ||
        !multiplayer::IsLuaControlledParticipant(*participant) ||
        !participant->runtime.valid ||
        !participant->runtime.in_run ||
        !TryResolveDamageSourceProgressionAddress(
            source_actor_address,
            &capture.progression_address)) {
        return SyntheticStockXpCapture{};
    }

    uintptr_t gameplay_address = 0;
    auto& memory = ProcessMemory::Instance();
    if (!TryResolveCurrentGameplayScene(&gameplay_address) ||
        gameplay_address == 0 ||
        !memory.TryReadField(
            enemy_actor_address,
            kGameObjectTypeIdOffset,
            &capture.enemy_type) ||
        !memory.TryReadField(
            enemy_actor_address,
            kEnemyCurrentHpOffset,
            &capture.hp_before) ||
        !memory.TryReadField(
            enemy_actor_address,
            kEnemyDeathHandledOffset,
            &capture.death_handled_before) ||
        !memory.TryReadField(
            enemy_actor_address,
            kEnemyExperienceRewardOffset,
            &capture.base_reward) ||
        !memory.TryReadField(
            gameplay_address,
            kGameplayExperienceMultiplierOffset,
            &capture.gameplay_multiplier) ||
        !memory.TryReadField(
            capture.progression_address,
            kProgressionLevelOffset,
            &capture.level_before) ||
        !memory.TryReadField(
            capture.progression_address,
            kProgressionXpOffset,
            &capture.xp_before)) {
        return SyntheticStockXpCapture{};
    }

    capture.wave = GetRunLifecycleCurrentWave();

    capture.eligible =
        capture.death_handled_before == 0 &&
        std::isfinite(capture.hp_before) &&
        capture.hp_before > 0.0f &&
        std::isfinite(capture.base_reward) &&
        capture.base_reward > 0.0f &&
        std::isfinite(capture.gameplay_multiplier) &&
        capture.gameplay_multiplier > 0.0f &&
        capture.level_before > 0 &&
        std::isfinite(capture.xp_before) &&
        capture.xp_before >= 0.0f;
    return capture;
}

void RouteSyntheticStockXpAfterDamage(
    uintptr_t enemy_actor_address,
    std::uint8_t native_kill_result,
    const SyntheticStockXpCapture& capture) {
    // Badguy::Contact is the vtable +0x4C callback invoked by the stock
    // 0x0063E7D0 damage dispatcher. Its non-zero return is the dispatcher's
    // exact gate for the reward block at 0x0063E80E..0x0063E83F. The enemy
    // death-presenter flag is not set until after this callback returns, so it
    // cannot be used here as the lethal-transition predicate.
    if (!capture.eligible ||
        enemy_actor_address == 0 ||
        native_kill_result == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    float hp_after = capture.hp_before;
    int level_before_route = capture.level_before;
    float xp_before_route = capture.xp_before;
    if (!memory.TryReadField(
            enemy_actor_address,
            kEnemyCurrentHpOffset,
            &hp_after) ||
        !memory.TryReadField(
            capture.progression_address,
            kProgressionLevelOffset,
            &level_before_route) ||
        !memory.TryReadField(
            capture.progression_address,
            kProgressionXpOffset,
            &xp_before_route) ||
        !std::isfinite(hp_after) ||
        !std::isfinite(xp_before_route) ||
        hp_after > 0.0f) {
        return;
    }

    if (level_before_route != capture.level_before ||
        std::fabs(xp_before_route - capture.xp_before) > 0.0001f) {
        Log(
            "[bots] stock XP already reached synthetic progression; "
            "duplicate route suppressed. participant_id=" +
            std::to_string(capture.participant_id));
        return;
    }

    const auto amount =
        capture.base_reward * capture.gameplay_multiplier;
    const auto experience_gain_address =
        memory.ResolveGameAddressOrZero(kExperienceGain);
    if (experience_gain_address == 0 ||
        !std::isfinite(amount) ||
        amount <= 0.0f) {
        Log(
            "[bots] synthetic stock XP route unavailable. participant_id=" +
            std::to_string(capture.participant_id));
        return;
    }

    DWORD exception_code = 0;
    if (!CallNativeExperienceGainSafe(
            experience_gain_address,
            capture.progression_address,
            amount,
            true,
            &exception_code)) {
        Log(
            "[bots] synthetic stock XP native route failed. participant_id=" +
            std::to_string(capture.participant_id) +
            " exception=" + HexString(exception_code));
        return;
    }

    int level_after = level_before_route;
    float xp_after = xp_before_route;
    (void)memory.TryReadField(
        capture.progression_address,
        kProgressionLevelOffset,
        &level_after);
    (void)memory.TryReadField(
        capture.progression_address,
        kProgressionXpOffset,
        &xp_after);
    Log(
        "[bots] synthetic stock XP routed. participant_id=" +
        std::to_string(capture.participant_id) +
        " wave=" + std::to_string(capture.wave) +
        " enemy_type=" + std::to_string(capture.enemy_type) +
        " base_reward=" + std::to_string(capture.base_reward) +
        " gameplay_multiplier=" +
        std::to_string(capture.gameplay_multiplier) +
        " native_amount=" + std::to_string(amount) +
        " level_before=" + std::to_string(level_before_route) +
        " level_after=" + std::to_string(level_after) +
        " xp_before=" + std::to_string(xp_before_route) +
        " xp_after=" + std::to_string(xp_after) +
        " credited_xp=" +
        std::to_string(xp_after - xp_before_route));
}
