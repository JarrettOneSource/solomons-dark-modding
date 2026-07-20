bool RefreshParticipantNativeProgression(
    std::uint64_t participant_id,
    std::string* error_message) {
    auto fail = [&](std::string message) {
        if (error_message != nullptr) {
            *error_message = std::move(message);
        }
        return false;
    };

    if (participant_id == 0) {
        return fail("participant progression refresh requires a participant id");
    }

    SDModParticipantGameplayState gameplay_state;
    if (!TryGetParticipantGameplayState(participant_id, &gameplay_state) ||
        !gameplay_state.available ||
        gameplay_state.progression_runtime_state_address == 0) {
        return fail("participant progression refresh requires a materialized progression");
    }

    DWORD refresh_exception = 0;
    std::string concentration_error;
    if (!RunWithParticipantConcentrationContext(
            participant_id,
            [&]() {
                return CallNativeActorProgressionRefresh(
                    gameplay_state.progression_runtime_state_address,
                    &refresh_exception);
            },
            &concentration_error)) {
        return fail(
            concentration_error.empty()
                ? "participant native progression refresh failed exception=0x" +
                      HexString(refresh_exception)
                : "participant native progression refresh Concentrate isolation failed: " +
                      concentration_error);
    }
    return true;
}

bool ApplyLocalPlayerSkillChoiceOption(
    const BotSkillChoiceOption& option,
    std::string* error_message) {
    auto fail = [&](std::string message) {
        if (error_message != nullptr) {
            *error_message = std::move(message);
        }
        return false;
    };

    if (option.option_id < 0) {
        return fail("local skill choice apply requires a valid option id");
    }

    SDModPlayerState player_state;
    if (!TryGetPlayerState(&player_state) ||
        !player_state.valid ||
        player_state.progression_address == 0) {
        return fail("local skill choice apply requires a live player progression");
    }

    DWORD apply_exception = 0;
    if (!ApplyNativeSkillChoiceToProgression(
            player_state.progression_address,
            option,
            true,
            &apply_exception)) {
        return fail(
            "local native skill choice apply failed exception=0x" +
            HexString(apply_exception));
    }

    int level = 0;
    if (!ProcessMemory::Instance().TryReadField(
            player_state.progression_address,
            kProgressionLevelOffset,
            &level)) {
        return fail("local native skill choice level read failed");
    }
    int experience = 0;
    if (!TryReadProgressionRoundedXp(player_state.progression_address, &experience)) {
        return fail("local native skill choice xp read failed");
    }
    int next_experience = 0;
    if (!TryReadProgressionNextXp(player_state.progression_address, &next_experience)) {
        return fail("local native skill choice next-xp read failed");
    }
    UpdateParticipantLevelProfileState(kLocalParticipantId, level, experience, next_experience);
    return true;
}

#include "bot_skill_choice_api.inl"
