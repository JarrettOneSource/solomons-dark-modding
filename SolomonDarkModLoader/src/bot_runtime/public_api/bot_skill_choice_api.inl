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
            false,
            &apply_exception)) {
        return fail(
            "native bot skill choice apply failed exception=0x" +
            HexString(apply_exception));
    }

    int level = 0;
    if (!ProcessMemory::Instance().TryReadField(
            gameplay_state.progression_runtime_state_address,
            kProgressionLevelOffset,
            &level)) {
        return fail("native bot skill choice level read failed");
    }
    int experience = 0;
    if (!TryReadProgressionRoundedXp(gameplay_state.progression_runtime_state_address, &experience)) {
        return fail("native bot skill choice xp read failed");
    }
    int next_experience = 0;
    if (!TryReadProgressionNextXp(gameplay_state.progression_runtime_state_address, &next_experience)) {
        return fail("native bot skill choice next-xp read failed");
    }
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
