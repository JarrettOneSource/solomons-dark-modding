bool PublishNaturalParticipantLevelUp(
    std::uint64_t participant_id,
    uintptr_t progression_address,
    std::int32_t level,
    std::int32_t experience,
    std::string* error_message) {
    auto fail = [&](std::string message) {
        if (error_message != nullptr) {
            *error_message = std::move(message);
        }
        return false;
    };
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (participant_id == 0 || progression_address == 0) {
        return fail("natural participant level-up requires a participant progression");
    }
    if (level <= 0 || experience < 0) {
        return fail("natural participant level-up has invalid progression values");
    }

    const auto runtime = SnapshotRuntimeState();
    const auto* participant = FindParticipant(runtime, participant_id);
    if (participant == nullptr || !IsLuaControlledParticipant(*participant)) {
        return fail("natural participant level-up requires a Lua-controlled participant");
    }

    SDModParticipantGameplayState gameplay_state;
    if (!TryGetParticipantGameplayState(participant_id, &gameplay_state) ||
        !gameplay_state.available ||
        gameplay_state.progression_runtime_state_address != progression_address) {
        return fail("natural participant level-up progression ownership changed");
    }

    int next_experience = 0;
    if (!TryReadProgressionNextXp(progression_address, &next_experience)) {
        return fail("natural participant level-up next-xp read failed");
    }
    UpdateParticipantLevelProfileState(
        participant_id,
        level,
        experience,
        next_experience);

    {
        std::scoped_lock lock(g_bot_runtime_mutex);
        const auto* existing = FindPendingSkillChoice(participant_id);
        if (existing != nullptr && !existing->options.empty()) {
            return fail("natural participant level-up arrived while a choice is pending");
        }
    }

    std::vector<BotSkillChoiceOption> options;
    DWORD roll_exception = 0;
    int requested_choice_count = 0;
    std::string concentration_error;
    if (!RunWithParticipantConcentrationContext(
            participant_id,
            [&]() {
                return RollNativeSkillChoiceOptions(
                    progression_address,
                    &options,
                    &roll_exception,
                    &requested_choice_count);
            },
            &concentration_error)) {
        return fail(
            concentration_error.empty()
                ? "natural participant skill choices roll failed exception=0x" +
                      HexString(roll_exception)
                : "natural participant skill choices Concentrate isolation failed: " +
                      concentration_error);
    }
    if (options.empty()) {
        return fail("natural participant skill choices roll returned no options");
    }

    const bool weld_option_present =
        std::any_of(
            options.begin(),
            options.end(),
            [&](const BotSkillChoiceOption& option) {
                return option.option_id == NativeSpecialChoiceActivationId();
            });
    std::int32_t pending_weld_build_id = -1;
    const bool pending_weld_build_id_resolved =
        weld_option_present &&
        TryReadNativePendingWeldBuildId(
            progression_address,
            &pending_weld_build_id);

    std::uint64_t generation = 0;
    {
        std::scoped_lock lock(g_bot_runtime_mutex);
        auto* pending_choice = FindPendingSkillChoice(participant_id);
        if (pending_choice == nullptr) {
            g_pending_skill_choices.push_back(PendingBotSkillChoice{});
            pending_choice = &g_pending_skill_choices.back();
        }
        pending_choice->bot_id = participant_id;
        pending_choice->generation = g_next_skill_choice_generation++;
        pending_choice->level = level;
        pending_choice->experience = experience;
        pending_choice->options = options;
        pending_choice->pending_weld_build_id = pending_weld_build_id;
        pending_choice->pending_weld_build_id_resolved =
            pending_weld_build_id_resolved;
        generation = pending_choice->generation;
        InvalidateParticipantLoadoutDetailsLocked(participant_id);
    }

    Log(
        "[bots] natural synthetic level-up choices pending. participant_id=" +
        std::to_string(participant_id) +
        " generation=" + std::to_string(generation) +
        " level=" + std::to_string(level) +
        " xp=" + std::to_string(experience) +
        " next_xp=" + std::to_string(next_experience) +
        " requested_choice_count=" + std::to_string(requested_choice_count) +
        " option_count=" + std::to_string(options.size()) +
        " options=[" + FormatSkillChoiceOptionsForLog(options) + "]");
    return true;
}
