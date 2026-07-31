struct LocalSharedLevelUpVitalsSnapshot {
    bool health_valid = false;
    bool mana_valid = false;
    float hp = 0.0f;
    float max_hp = 0.0f;
    float mp = 0.0f;
    float max_mp = 0.0f;
};

LocalSharedLevelUpVitalsSnapshot CaptureLocalSharedLevelUpVitals(uintptr_t progression_address) {
    LocalSharedLevelUpVitalsSnapshot snapshot;
    if (progression_address == 0) {
        return snapshot;
    }

    auto& memory = ProcessMemory::Instance();
    float hp = 0.0f;
    float max_hp = 0.0f;
    if (memory.TryReadField(progression_address, kProgressionHpOffset, &hp) &&
        memory.TryReadField(progression_address, kProgressionMaxHpOffset, &max_hp) &&
        std::isfinite(hp) &&
        std::isfinite(max_hp) &&
        max_hp > 0.0f) {
        snapshot.health_valid = true;
        snapshot.hp = hp;
        snapshot.max_hp = max_hp;
    }

    float mp = 0.0f;
    float max_mp = 0.0f;
    if (memory.TryReadField(progression_address, kProgressionMpOffset, &mp) &&
        memory.TryReadField(progression_address, kProgressionMaxMpOffset, &max_mp) &&
        std::isfinite(mp) &&
        std::isfinite(max_mp) &&
        max_mp > 0.0f) {
        snapshot.mana_valid = true;
        snapshot.mp = mp;
        snapshot.max_mp = max_mp;
    }

    return snapshot;
}

bool RestoreLocalSharedLevelUpVitals(
    uintptr_t progression_address,
    const LocalSharedLevelUpVitalsSnapshot& snapshot) {
    if (progression_address == 0 ||
        (!snapshot.health_valid && !snapshot.mana_valid)) {
        return true;
    }

    auto& memory = ProcessMemory::Instance();
    bool wrote = true;
    if (snapshot.health_valid) {
        wrote = memory.TryWriteField<float>(
            progression_address,
            kProgressionMaxHpOffset,
            snapshot.max_hp) && wrote;
        wrote = memory.TryWriteField<float>(
            progression_address,
            kProgressionHpOffset,
            snapshot.hp) && wrote;
    }
    if (snapshot.mana_valid) {
        wrote = memory.TryWriteField<float>(
            progression_address,
            kProgressionMaxMpOffset,
            snapshot.max_mp) && wrote;
        wrote = memory.TryWriteField<float>(
            progression_address,
            kProgressionMpOffset,
            snapshot.mp) && wrote;
    }
    return wrote;
}

void LogLocalSharedLevelUpVitalsPreservedIfChanged(
    uintptr_t progression_address,
    const LocalSharedLevelUpVitalsSnapshot& before) {
    if (progression_address == 0 ||
        (!before.health_valid && !before.mana_valid)) {
        return;
    }

    const auto native_after = CaptureLocalSharedLevelUpVitals(progression_address);
    constexpr float kVitalsLogEpsilon = 0.001f;
    const bool health_changed =
        before.health_valid &&
        native_after.health_valid &&
        (std::fabs(before.hp - native_after.hp) > kVitalsLogEpsilon ||
         std::fabs(before.max_hp - native_after.max_hp) > kVitalsLogEpsilon);
    const bool mana_changed =
        before.mana_valid &&
        native_after.mana_valid &&
        (std::fabs(before.mp - native_after.mp) > kVitalsLogEpsilon ||
         std::fabs(before.max_mp - native_after.max_mp) > kVitalsLogEpsilon);
    if (!health_changed && !mana_changed) {
        return;
    }

    Log(
        "[bots] local shared level-up sync preserving live vitals. progression=" +
        HexString(progression_address) +
        " hp_before=" + std::to_string(before.hp) + "/" + std::to_string(before.max_hp) +
        " hp_native=" + std::to_string(native_after.hp) + "/" + std::to_string(native_after.max_hp) +
        " mp_before=" + std::to_string(before.mp) + "/" + std::to_string(before.max_mp) +
        " mp_native=" + std::to_string(native_after.mp) + "/" + std::to_string(native_after.max_mp));
}

void SyncInRunParticipantsToSharedProgression(
    std::uint32_t run_nonce,
    std::int32_t level,
    float experience,
    std::int32_t next_experience,
    uintptr_t source_progression_address) {
    if (run_nonce == 0 ||
        level <= 0 ||
        !std::isfinite(experience) ||
        experience < 0.0f ||
        next_experience <= 0) {
        return;
    }

    const auto runtime = SnapshotRuntimeState();
    SDModPlayerState local_player;
    if (TryGetPlayerState(&local_player) &&
        local_player.valid &&
        local_player.progression_address != 0 &&
        local_player.progression_address != source_progression_address) {
        std::string local_sync_error;
        if (!SyncLocalPlayerProgressionToSharedSnapshot(
                level,
                experience,
                next_experience,
                &local_sync_error)) {
            Log(
                "[progression] shared XP local native sync failed. "
                "run_nonce=" + std::to_string(run_nonce) +
                " level=" + std::to_string(level) +
                " xp=" + std::to_string(experience) +
                " next_xp=" + std::to_string(next_experience) +
                " error=" + local_sync_error);
        }
    }
    UpdateInRunParticipantSharedProgressionState(
        run_nonce,
        level,
        experience,
        next_experience);
    for (const auto& participant : runtime.participants) {
        if (IsLocalHumanParticipant(participant) ||
            !participant.runtime.valid ||
            !participant.runtime.in_run ||
            participant.runtime.run_nonce != run_nonce) {
            continue;
        }

        SDModParticipantGameplayState gameplay_state;
        if (!TryGetParticipantGameplayState(
                participant.participant_id,
                &gameplay_state) ||
            !gameplay_state.available ||
            gameplay_state.progression_runtime_state_address == 0) {
            Log(
                "[progression] shared XP native sync pending materialization. "
                "participant_id=" +
                std::to_string(participant.participant_id) +
                " run_nonce=" + std::to_string(run_nonce));
            continue;
        }

        const auto live_vitals_before =
            CaptureLocalSharedLevelUpVitals(
                gameplay_state.progression_runtime_state_address);
        DWORD sync_exception = 0;
        std::string concentration_error;
        const bool synced = RunWithParticipantConcentrationContext(
            participant.participant_id,
            [&]() {
                return SyncNativeProgressionToSharedSnapshot(
                    gameplay_state.progression_runtime_state_address,
                    source_progression_address,
                    level,
                    experience,
                    next_experience,
                    &sync_exception);
            },
            &concentration_error);
        const bool vitals_restored =
            RestoreLocalSharedLevelUpVitals(
                gameplay_state.progression_runtime_state_address,
                live_vitals_before);
        if (!synced || !vitals_restored) {
            Log(
                "[progression] shared XP native sync failed. participant_id=" +
                std::to_string(participant.participant_id) +
                " run_nonce=" + std::to_string(run_nonce) +
                " level=" + std::to_string(level) +
                " xp=" + std::to_string(experience) +
                " next_xp=" + std::to_string(next_experience) +
                (concentration_error.empty()
                     ? " exception=0x" + HexString(sync_exception)
                     : " error=" + concentration_error) +
                " vitals_restored=" +
                std::to_string(vitals_restored ? 1 : 0));
        }
    }
}

bool SyncLocalPlayerProgressionToSharedSnapshot(
    std::int32_t level,
    float experience,
    std::int32_t next_experience,
    std::string* error_message) {
    auto fail = [&](std::string message) {
        if (error_message != nullptr) {
            *error_message = std::move(message);
        }
        return false;
    };
    if (level <= 0 ||
        !std::isfinite(experience) ||
        experience < 0.0f ||
        next_experience <= 0) {
        return fail("local shared progression snapshot is invalid");
    }

    SDModPlayerState player_state;
    if (!TryGetPlayerState(&player_state) ||
        !player_state.valid ||
        player_state.progression_address == 0) {
        return fail(
            "local shared progression sync requires a live player progression");
    }

    auto& memory = ProcessMemory::Instance();
    std::uint8_t previous_mode = kProgressionLocalPlayerModeValue;
    const bool have_previous_mode =
        memory.TryReadField<std::uint8_t>(
            player_state.progression_address,
            kProgressionNonLocalModeFlagOffset,
            &previous_mode);
    const auto live_vitals_before =
        CaptureLocalSharedLevelUpVitals(
            player_state.progression_address);
    DWORD sync_exception = 0;
    const bool synced = SyncNativeProgressionToSharedSnapshot(
        player_state.progression_address,
        0,
        level,
        experience,
        next_experience,
        &sync_exception);
    (void)memory.TryWriteField<std::uint8_t>(
        player_state.progression_address,
        kProgressionNonLocalModeFlagOffset,
        have_previous_mode
            ? previous_mode
            : kProgressionLocalPlayerModeValue);
    LogLocalSharedLevelUpVitalsPreservedIfChanged(
        player_state.progression_address,
        live_vitals_before);
    if (!RestoreLocalSharedLevelUpVitals(
            player_state.progression_address,
            live_vitals_before)) {
        return fail(
            "local shared progression sync live vitals restore failed");
    }
    if (!synced) {
        return fail(
            "local shared progression native sync failed exception=0x" +
            HexString(sync_exception));
    }

    UpdateParticipantLevelProfileState(
        kLocalParticipantId,
        level,
        static_cast<std::int32_t>(std::lround(experience)),
        next_experience);
    return true;
}
