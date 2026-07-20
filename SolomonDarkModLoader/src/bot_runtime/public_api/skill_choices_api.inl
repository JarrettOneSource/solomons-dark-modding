void SyncBotsToSharedLevelUp(std::int32_t level, std::int32_t experience, uintptr_t source_progression_address) {
    if (level <= 0) {
        return;
    }

    int next_experience = 0;
    if (source_progression_address != 0 &&
        !TryReadProgressionNextXp(source_progression_address, &next_experience)) {
        Log(
            "[bots] shared level-up native next-xp unavailable. source_progression=" +
            HexString(source_progression_address));
    }
    RuntimeState runtime = SnapshotRuntimeState();
    struct BotProgressionTarget {
        std::uint64_t bot_id = 0;
        uintptr_t progression_address = 0;
        std::int32_t element_id = 0;
        std::int32_t discipline_id = 0;
        std::int32_t primary_entry_index = -1;
    };
    std::vector<BotProgressionTarget> targets;

    UpdateRuntimeState([&](RuntimeState& state) {
        for (auto& participant : state.participants) {
            if (IsLocalHumanParticipant(participant)) {
                continue;
            }
            participant.character_profile.level = level;
            participant.character_profile.experience = experience;
            participant.runtime.level = level;
            participant.runtime.experience_current = experience;
            if (next_experience > 0) {
                participant.runtime.experience_next = next_experience;
            }
        }
    });

    for (const auto& participant : runtime.participants) {
        if (!IsLuaControlledParticipant(participant)) {
            continue;
        }

        SDModParticipantGameplayState gameplay_state;
        if (!TryGetParticipantGameplayState(participant.participant_id, &gameplay_state) ||
            !gameplay_state.available ||
            gameplay_state.progression_runtime_state_address == 0) {
            Log(
                "[bots] shared level-up profile sync pending materialization. bot_id=" +
                std::to_string(participant.participant_id) +
                " level=" + std::to_string(level) +
                " xp=" + std::to_string(experience));
            continue;
        }

        targets.push_back(BotProgressionTarget{
            participant.participant_id,
            gameplay_state.progression_runtime_state_address,
            participant.character_profile.element_id,
            static_cast<std::int32_t>(participant.character_profile.discipline_id),
            participant.character_profile.loadout.primary_entry_index});
    }

    for (const auto& target : targets) {
        DWORD sync_exception = 0;
        if (!SyncNativeBotProgressionLevel(
                target.progression_address,
                source_progression_address,
                level,
                experience,
                &sync_exception)) {
            Log(
                "[bots] shared level-up native progression sync failed. bot_id=" +
                std::to_string(target.bot_id) +
                " progression=" + HexString(target.progression_address) +
                " exception=0x" + HexString(sync_exception));
            continue;
        }

        std::vector<BotSkillChoiceOption> options;
        DWORD roll_exception = 0;
        int requested_choice_count = 0;
        if (!RollNativeSkillChoiceOptions(
                target.progression_address,
                &options,
                &roll_exception,
                &requested_choice_count)) {
            Log(
                "[bots] native skill choices roll failed. bot_id=" +
                std::to_string(target.bot_id) +
                " progression=" + HexString(target.progression_address) +
                " element_id=" + std::to_string(target.element_id) +
                " discipline_id=" + std::to_string(target.discipline_id) +
                " primary_entry_index=" + std::to_string(target.primary_entry_index) +
                " level=" + std::to_string(level) +
                " xp=" + std::to_string(experience) +
                " exception=0x" + HexString(roll_exception));
            continue;
        }

        std::scoped_lock lock(g_bot_runtime_mutex);
        auto* pending_choice = FindPendingSkillChoice(target.bot_id);
        if (pending_choice == nullptr) {
            g_pending_skill_choices.push_back(PendingBotSkillChoice{});
            pending_choice = &g_pending_skill_choices.back();
        }

        pending_choice->bot_id = target.bot_id;
        pending_choice->generation = g_next_skill_choice_generation++;
        pending_choice->level = level;
        pending_choice->experience = experience;
        pending_choice->options = options;

        Log(
            "[bots] native skill choices pending. bot_id=" +
            std::to_string(target.bot_id) +
            " generation=" + std::to_string(pending_choice->generation) +
            " progression=" + HexString(target.progression_address) +
            " element_id=" + std::to_string(target.element_id) +
            " discipline_id=" + std::to_string(target.discipline_id) +
            " primary_entry_index=" + std::to_string(target.primary_entry_index) +
            " level=" + std::to_string(level) +
            " xp=" + std::to_string(experience) +
            " requested_choice_count=" + std::to_string(requested_choice_count) +
            " option_count=" + std::to_string(options.size()) +
            " options=[" + FormatSkillChoiceOptionsForLog(options) + "]");
    }
}

void UpdateParticipantLevelProfileState(
    std::uint64_t participant_id,
    int level,
    int experience,
    int next_experience) {
    UpdateRuntimeState([&](RuntimeState& state) {
        auto* participant = FindParticipant(state, participant_id);
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

bool SyncParticipantProgressionToSharedLevelUp(
    std::uint64_t participant_id,
    std::int32_t level,
    std::int32_t experience,
    uintptr_t source_progression_address,
    std::string* error_message) {
    auto fail = [&](std::string message) {
        if (error_message != nullptr) {
            *error_message = std::move(message);
        }
        return false;
    };

    if (participant_id == 0) {
        return fail("participant level sync requires a participant id");
    }
    if (level <= 0) {
        return fail("participant level sync requires a positive level");
    }
    if (experience < 0) {
        return fail("participant level sync requires non-negative experience");
    }

    SDModParticipantGameplayState gameplay_state;
    if (!TryGetParticipantGameplayState(participant_id, &gameplay_state) ||
        !gameplay_state.available ||
        gameplay_state.progression_runtime_state_address == 0) {
        return fail("participant level sync requires a materialized progression");
    }

    const auto live_vitals_before =
        CaptureLocalSharedLevelUpVitals(gameplay_state.progression_runtime_state_address);
    DWORD sync_exception = 0;
    std::string concentration_error;
    if (!RunWithParticipantConcentrationContext(
            participant_id,
            [&]() {
                return SyncNativeBotProgressionLevel(
                    gameplay_state.progression_runtime_state_address,
                    source_progression_address,
                    level,
                    experience,
                    &sync_exception);
            },
            &concentration_error)) {
        return fail(
            concentration_error.empty()
                ? "participant native level sync failed exception=0x" +
                      HexString(sync_exception)
                : "participant native level sync Concentrate isolation failed: " +
                      concentration_error);
    }
    if (!RestoreLocalSharedLevelUpVitals(
            gameplay_state.progression_runtime_state_address,
            live_vitals_before)) {
        return fail("participant native level sync live vitals restore failed");
    }

    int next_experience = 0;
    (void)TryReadProgressionNextXp(gameplay_state.progression_runtime_state_address, &next_experience);
    UpdateParticipantLevelProfileState(participant_id, level, experience, next_experience);
    Log(
        "[bots] participant native level synchronized. participant_id=" +
        std::to_string(participant_id) +
        " progression=" + HexString(gameplay_state.progression_runtime_state_address) +
        " level=" + std::to_string(level) +
        " xp=" + std::to_string(experience));
    return true;
}

bool SyncParticipantProgressionToSharedLevelUpAndRollChoices(
    std::uint64_t participant_id,
    std::int32_t level,
    std::int32_t experience,
    uintptr_t source_progression_address,
    std::vector<BotSkillChoiceOption>* options,
    std::string* error_message) {
    auto fail = [&](std::string message) {
        if (error_message != nullptr) {
            *error_message = std::move(message);
        }
        if (options != nullptr) {
            options->clear();
        }
        return false;
    };

    if (options == nullptr) {
        return fail("participant level-up roll requires an option sink");
    }
    options->clear();

    std::string sync_error;
    if (!SyncParticipantProgressionToSharedLevelUp(
            participant_id,
            level,
            experience,
            source_progression_address,
            &sync_error)) {
        return fail(std::move(sync_error));
    }

    SDModParticipantGameplayState gameplay_state;
    if (!TryGetParticipantGameplayState(participant_id, &gameplay_state) ||
        !gameplay_state.available ||
        gameplay_state.progression_runtime_state_address == 0) {
        return fail("participant level-up roll requires a materialized progression");
    }

    DWORD roll_exception = 0;
    int requested_choice_count = 0;
    if (!RollNativeSkillChoiceOptions(
            gameplay_state.progression_runtime_state_address,
            options,
            &roll_exception,
            &requested_choice_count)) {
        return fail(
            "participant native skill choices roll failed exception=0x" +
            HexString(roll_exception));
    }

    Log(
        "[bots] participant native skill choices rolled. participant_id=" +
        std::to_string(participant_id) +
        " progression=" + HexString(gameplay_state.progression_runtime_state_address) +
        " level=" + std::to_string(level) +
        " xp=" + std::to_string(experience) +
        " requested_choice_count=" + std::to_string(requested_choice_count) +
        " option_count=" + std::to_string(options->size()) +
        " options=[" + FormatSkillChoiceOptionsForLog(*options) + "]");
    return true;
}

bool SyncLocalPlayerProgressionToSharedLevelUp(
    std::int32_t level,
    std::int32_t experience,
    std::string* error_message) {
    auto fail = [&](std::string message) {
        if (error_message != nullptr) {
            *error_message = std::move(message);
        }
        return false;
    };

    if (level <= 0) {
        return fail("local level-up sync requires a positive level");
    }
    if (experience < 0) {
        return fail("local level-up sync requires non-negative experience");
    }

    SDModPlayerState player_state;
    if (!TryGetPlayerState(&player_state) ||
        !player_state.valid ||
        player_state.progression_address == 0) {
        return fail("local level-up sync requires a live player progression");
    }

    auto& memory = ProcessMemory::Instance();
    std::uint8_t previous_mode = kProgressionLocalPlayerModeValue;
    const bool have_previous_mode = memory.TryReadField<std::uint8_t>(
        player_state.progression_address,
        kProgressionNonLocalModeFlagOffset,
        &previous_mode);
    const auto live_vitals_before =
        CaptureLocalSharedLevelUpVitals(player_state.progression_address);
    DWORD sync_exception = 0;
    const bool synced = SyncNativeBotProgressionLevel(
            player_state.progression_address,
            0,
            level,
            experience,
            &sync_exception);
    (void)memory.TryWriteField<std::uint8_t>(
        player_state.progression_address,
        kProgressionNonLocalModeFlagOffset,
        have_previous_mode ? previous_mode : kProgressionLocalPlayerModeValue);
    LogLocalSharedLevelUpVitalsPreservedIfChanged(
        player_state.progression_address,
        live_vitals_before);
    if (!RestoreLocalSharedLevelUpVitals(
            player_state.progression_address,
            live_vitals_before)) {
        return fail("local native level sync live vitals restore failed");
    }
    if (!synced) {
        return fail(
            "local native level sync failed exception=0x" +
            HexString(sync_exception));
    }

    int next_experience = 0;
    (void)TryReadProgressionNextXp(player_state.progression_address, &next_experience);
    UpdateParticipantLevelProfileState(kLocalParticipantId, level, experience, next_experience);
    return true;
}

bool SyncLocalPlayerProgressionToSharedLevelUpAndRollChoices(
    std::int32_t level,
    std::int32_t experience,
    std::vector<BotSkillChoiceOption>* options,
    std::string* error_message) {
    auto fail = [&](std::string message) {
        if (error_message != nullptr) {
            *error_message = std::move(message);
        }
        if (options != nullptr) {
            options->clear();
        }
        return false;
    };

    if (options == nullptr) {
        return fail("local level-up roll requires an option sink");
    }
    options->clear();

    std::string sync_error;
    if (!SyncLocalPlayerProgressionToSharedLevelUp(level, experience, &sync_error)) {
        return fail(std::move(sync_error));
    }

    SDModPlayerState player_state;
    if (!TryGetPlayerState(&player_state) ||
        !player_state.valid ||
        player_state.progression_address == 0) {
        return fail("local level-up roll requires a live player progression");
    }

    DWORD roll_exception = 0;
    int requested_choice_count = 0;
    if (!RollNativeSkillChoiceOptions(
            player_state.progression_address,
            options,
            &roll_exception,
            &requested_choice_count)) {
        return fail(
            "local native skill choices roll failed exception=0x" +
            HexString(roll_exception));
    }
    Log(
        "[bots] local native skill choices rolled. progression=" +
        HexString(player_state.progression_address) +
        " level=" + std::to_string(level) +
        " xp=" + std::to_string(experience) +
        " requested_choice_count=" + std::to_string(requested_choice_count) +
        " option_count=" + std::to_string(options->size()) +
        " options=[" + FormatSkillChoiceOptionsForLog(*options) + "]");
    return true;
}

bool RollParticipantSkillChoiceOptions(
    std::uint64_t participant_id,
    std::vector<BotSkillChoiceOption>* options,
    std::string* error_message) {
    auto fail = [&](std::string message) {
        if (error_message != nullptr) {
            *error_message = std::move(message);
        }
        if (options != nullptr) {
            options->clear();
        }
        return false;
    };

    if (participant_id == 0) {
        return fail("participant skill choice roll requires a participant id");
    }
    if (options == nullptr) {
        return fail("participant skill choice roll requires an option sink");
    }
    options->clear();

    SDModParticipantGameplayState gameplay_state;
    if (!TryGetParticipantGameplayState(participant_id, &gameplay_state) ||
        !gameplay_state.available ||
        gameplay_state.progression_runtime_state_address == 0) {
        return fail("participant skill choice roll requires a materialized progression");
    }

    DWORD roll_exception = 0;
    int requested_choice_count = 0;
    if (!RollNativeSkillChoiceOptions(
            gameplay_state.progression_runtime_state_address,
            options,
            &roll_exception,
            &requested_choice_count)) {
        return fail(
            "participant native skill choices roll failed exception=0x" +
            HexString(roll_exception));
    }
    return true;
}

bool RollLocalPlayerSkillChoiceOptions(
    std::vector<BotSkillChoiceOption>* options,
    std::string* error_message) {
    auto fail = [&](std::string message) {
        if (error_message != nullptr) {
            *error_message = std::move(message);
        }
        if (options != nullptr) {
            options->clear();
        }
        return false;
    };

    if (options == nullptr) {
        return fail("local skill choice roll requires an option sink");
    }
    options->clear();

    SDModPlayerState player_state;
    if (!TryGetPlayerState(&player_state) ||
        !player_state.valid ||
        player_state.progression_address == 0) {
        return fail("local skill choice roll requires a live player progression");
    }

    DWORD roll_exception = 0;
    int requested_choice_count = 0;
    if (!RollNativeSkillChoiceOptions(
            player_state.progression_address,
            options,
            &roll_exception,
            &requested_choice_count)) {
        return fail(
            "local native skill choices roll failed exception=0x" +
            HexString(roll_exception));
    }
    return true;
}

bool ApplyParticipantSkillChoiceOption(
    std::uint64_t participant_id,
    const BotSkillChoiceOption& option,
    std::string* error_message) {
    auto fail = [&](std::string message) {
        if (error_message != nullptr) {
            *error_message = std::move(message);
        }
        return false;
    };

    if (participant_id == 0) {
        return fail("participant skill choice apply requires a participant id");
    }
    if (option.option_id < 0) {
        return fail("participant skill choice apply requires a valid option id");
    }

    SDModParticipantGameplayState gameplay_state;
    if (!TryGetParticipantGameplayState(participant_id, &gameplay_state) ||
        !gameplay_state.available ||
        gameplay_state.progression_runtime_state_address == 0) {
        return fail("participant skill choice apply requires a materialized progression");
    }

    DWORD apply_exception = 0;
    std::string concentration_error;
    if (!RunWithParticipantConcentrationContext(
            participant_id,
            [&]() {
                return ApplyNativeSkillChoiceToProgression(
                    gameplay_state.progression_runtime_state_address,
                    option,
                    false,
                    &apply_exception);
            },
            &concentration_error)) {
        return fail(
            concentration_error.empty()
                ? "participant native skill choice apply failed exception=0x" +
                      HexString(apply_exception)
                : "participant native skill choice Concentrate isolation failed: " +
                      concentration_error);
    }

    int level = 0;
    if (!ProcessMemory::Instance().TryReadField(
            gameplay_state.progression_runtime_state_address,
            kProgressionLevelOffset,
            &level)) {
        return fail("participant native skill choice level read failed");
    }
    int experience = 0;
    if (!TryReadProgressionRoundedXp(gameplay_state.progression_runtime_state_address, &experience)) {
        return fail("participant native skill choice xp read failed");
    }
    int next_experience = 0;
    if (!TryReadProgressionNextXp(gameplay_state.progression_runtime_state_address, &next_experience)) {
        return fail("participant native skill choice next-xp read failed");
    }
    UpdateParticipantLevelProfileState(participant_id, level, experience, next_experience);
    return true;
}

#include "skill_choice_application.inl"
