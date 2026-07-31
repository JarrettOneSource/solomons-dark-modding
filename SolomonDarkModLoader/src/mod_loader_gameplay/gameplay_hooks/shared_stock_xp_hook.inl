struct SharedStockXpCapture {
    bool eligible = false;
    multiplayer::SharedKillExperienceCredit credit;
    float hp_before = 0.0f;
    std::uint8_t death_handled_before = 0;
};

SharedStockXpCapture CaptureSharedStockXpBeforeDamage(
    uintptr_t enemy_actor_address,
    uintptr_t source_actor_address) {
    SharedStockXpCapture capture;
    if (!multiplayer::IsLuaModSimulationAuthority() ||
        enemy_actor_address == 0 ||
        source_actor_address == 0) {
        return capture;
    }

    capture.credit.participant_id =
        ResolveDamageSourceParticipantId(source_actor_address);
    const auto local_transport_participant_id =
        multiplayer::GetLocalTransportParticipantId();
    if (local_transport_participant_id != 0 &&
        capture.credit.participant_id ==
            local_transport_participant_id) {
        capture.credit.participant_id =
            multiplayer::kLocalParticipantId;
    }
    const auto runtime = multiplayer::SnapshotRuntimeState();
    const auto* participant = multiplayer::FindParticipant(
        runtime,
        capture.credit.participant_id);
    if (participant == nullptr ||
        !participant->runtime.valid ||
        !participant->runtime.in_run ||
        participant->runtime.run_nonce == 0) {
        return SharedStockXpCapture{};
    }
    capture.credit.run_nonce = participant->runtime.run_nonce;
    (void)TryResolveDamageSourceProgressionAddress(
        source_actor_address,
        &capture.credit.source_progression_address);

    uintptr_t gameplay_address = 0;
    auto& memory = ProcessMemory::Instance();
    if (!TryResolveCurrentGameplayScene(&gameplay_address) ||
        gameplay_address == 0 ||
        !memory.TryReadField(
            enemy_actor_address,
            kGameObjectTypeIdOffset,
            &capture.credit.enemy_type) ||
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
            &capture.credit.base_reward) ||
        !memory.TryReadField(
            gameplay_address,
            kGameplayExperienceMultiplierOffset,
            &capture.credit.gameplay_multiplier)) {
        return SharedStockXpCapture{};
    }
    if (capture.credit.source_progression_address != 0) {
        if (!memory.TryReadField(
                capture.credit.source_progression_address,
                kProgressionXpOffset,
                &capture.credit.source_experience_before) ||
            !std::isfinite(capture.credit.source_experience_before) ||
            capture.credit.source_experience_before < 0.0f) {
            capture.credit.source_progression_address = 0;
            capture.credit.source_experience_before = 0.0f;
        }
    }

    capture.credit.wave = GetRunLifecycleCurrentWave();
    capture.eligible =
        capture.death_handled_before == 0 &&
        std::isfinite(capture.hp_before) &&
        capture.hp_before > 0.0f &&
        std::isfinite(capture.credit.base_reward) &&
        capture.credit.base_reward > 0.0f &&
        std::isfinite(capture.credit.gameplay_multiplier) &&
        capture.credit.gameplay_multiplier > 0.0f;
    return capture;
}

void ArmSharedStockXpAfterDamage(
    uintptr_t enemy_actor_address,
    std::uint8_t native_kill_result,
    const SharedStockXpCapture& capture) {
    // Badguy::Contact is the vtable +0x4C callback invoked by the stock
    // 0x0063E7D0 dispatcher. Its non-zero return is the exact gate for the
    // reward block at 0x0063E80E..0x0063E83F. Arm attribution here; the
    // outer damage-dispatch wrapper consumes it after the contact and stock
    // reward block return.
    if (enemy_actor_address == 0 || native_kill_result == 0) {
        return;
    }

    float hp_after = capture.hp_before;
    if (!ProcessMemory::Instance().TryReadField(
            enemy_actor_address,
            kEnemyCurrentHpOffset,
            &hp_after) ||
        !std::isfinite(hp_after) ||
        hp_after > 0.0f) {
        return;
    }

    if (!capture.eligible) {
        Log(
            "[progression] shared XP lethal capture ineligible. "
            "participant_id=" +
            std::to_string(capture.credit.participant_id) +
            " run_nonce=" + std::to_string(capture.credit.run_nonce) +
            " hp_before=" + std::to_string(capture.hp_before) +
            " hp_after=" + std::to_string(hp_after) +
            " death_handled_before=" +
            std::to_string(capture.death_handled_before) +
            " base_reward=" +
            std::to_string(capture.credit.base_reward) +
            " gameplay_multiplier=" +
            std::to_string(capture.credit.gameplay_multiplier));
        return;
    }

    const auto expected_native_amount =
        capture.credit.base_reward *
        capture.credit.gameplay_multiplier;
    if (!std::isfinite(expected_native_amount) ||
        expected_native_amount <= 0.0f) {
        return;
    }
    multiplayer::ArmSharedKillExperienceCredit(
        capture.credit,
        expected_native_amount);
}
