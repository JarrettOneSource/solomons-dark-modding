void SyncBotsToSharedLevelUp(std::int32_t level, std::int32_t experience, uintptr_t source_progression_address) {
    if (level <= 0) {
        return;
    }

    const auto next_experience = ReadProgressionNextXpOrZero(source_progression_address);
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

bool ReadBotSkillChoices(std::uint64_t bot_id, BotSkillChoiceSnapshot* snapshot) {
    if (snapshot == nullptr) {
        return false;
    }

    *snapshot = BotSkillChoiceSnapshot{};
    snapshot->bot_id = bot_id;

    RuntimeState runtime = SnapshotRuntimeState();
    if (FindBot(runtime, bot_id) == nullptr) {
        return false;
    }

    std::scoped_lock lock(g_bot_runtime_mutex);
    const auto* pending_choice = FindPendingSkillChoiceConst(bot_id);
    if (pending_choice == nullptr) {
        return true;
    }

    snapshot->pending = true;
    snapshot->generation = pending_choice->generation;
    snapshot->level = pending_choice->level;
    snapshot->experience = pending_choice->experience;
    snapshot->options = pending_choice->options;
    return true;
}

bool ChooseBotSkill(const BotSkillChoiceRequest& request, std::string* error_message) {
    auto fail = [&](std::string message) {
        if (error_message != nullptr) {
            *error_message = std::move(message);
        }
        return false;
    };

    if (request.bot_id == 0) {
        return fail("bot skill choice requires a bot id");
    }

    PendingBotSkillChoice pending_choice{};
    BotSkillChoiceOption selected_option{};
    {
        std::scoped_lock lock(g_bot_runtime_mutex);
        const auto* existing = FindPendingSkillChoiceConst(request.bot_id);
        if (existing == nullptr) {
            return fail("bot has no pending skill choice");
        }
        if (request.generation != 0 && request.generation != existing->generation) {
            return fail("bot skill choice generation is stale");
        }

        pending_choice = *existing;
        if (request.option_index > 0) {
            const auto zero_based_index = static_cast<std::size_t>(request.option_index - 1);
            if (zero_based_index >= pending_choice.options.size()) {
                return fail("bot skill choice index is out of range");
            }
            selected_option = pending_choice.options[zero_based_index];
        } else if (request.option_id >= 0) {
            const auto it = std::find_if(
                pending_choice.options.begin(),
                pending_choice.options.end(),
                [&](const BotSkillChoiceOption& option) {
                    return option.option_id == request.option_id;
                });
            if (it == pending_choice.options.end()) {
                return fail("bot skill choice id was not in the rolled option list");
            }
            selected_option = *it;
        } else {
            return fail("bot skill choice requires option_index or option_id");
        }
    }

    SDModParticipantGameplayState gameplay_state;
    if (!TryGetParticipantGameplayState(request.bot_id, &gameplay_state) ||
        !gameplay_state.available ||
        gameplay_state.progression_runtime_state_address == 0) {
        return fail("bot skill choice requires a materialized bot progression");
    }

    DWORD apply_exception = 0;
    if (!ApplyNativeSkillChoiceToProgression(
            gameplay_state.progression_runtime_state_address,
            selected_option,
            &apply_exception)) {
        return fail(
            "native bot skill choice apply failed exception=0x" +
            HexString(apply_exception));
    }

    const auto level = ProcessMemory::Instance().ReadFieldOr<int>(
        gameplay_state.progression_runtime_state_address,
        kProgressionLevelOffset,
        pending_choice.level);
    const auto experience = ReadProgressionRoundedXpOrFallback(
        gameplay_state.progression_runtime_state_address,
        pending_choice.experience);
    const auto next_experience = ReadProgressionNextXpOrZero(gameplay_state.progression_runtime_state_address);
    UpdateBotLevelProfileState(request.bot_id, level, experience, next_experience);

    {
        std::scoped_lock lock(g_bot_runtime_mutex);
        const auto* existing = FindPendingSkillChoiceConst(request.bot_id);
        if (existing != nullptr && existing->generation == pending_choice.generation) {
            RemovePendingSkillChoice(request.bot_id);
        }
    }

    Log(
        "[bots] native skill choice applied. bot_id=" +
        std::to_string(request.bot_id) +
        " generation=" + std::to_string(pending_choice.generation) +
        " progression=" + HexString(gameplay_state.progression_runtime_state_address) +
        " option_id=" + std::to_string(selected_option.option_id) +
        " level=" + std::to_string(level) +
        " xp=" + std::to_string(experience));
    return true;
}
