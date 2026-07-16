// Focused debug seams for publishing deterministic host level-up cohorts.

void PublishHostLevelUpBarrierOffers(
    std::int32_t level,
    std::int32_t experience,
    uintptr_t source_progression_address) {
    if (!IsLocalTransportHost() ||
        g_local_transport.suppress_local_level_up_fanout ||
        level <= 0 || experience < 0) {
        return;
    }

    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);
    const std::uint32_t run_nonce =
        local != nullptr && local->runtime.valid ? local->runtime.run_nonce : 0;
    std::vector<std::uint64_t> participant_ids;
    if (g_local_transport.local_peer_id != 0) {
        participant_ids.push_back(g_local_transport.local_peer_id);
    }
    for (const auto& participant : runtime_state.participants) {
        if (IsRemoteParticipant(participant) &&
            IsNativeControlledParticipant(participant) &&
            participant.transport_connected) {
            participant_ids.push_back(participant.participant_id);
        }
    }
    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    if (!BeginOrExtendHostLevelUpBarrier(
            std::move(participant_ids),
            run_nonce,
            level,
            experience,
            source_progression_address,
            now_ms)) {
        return;
    }

    // The complete cohort is in the barrier before any picker offer is sent,
    // so every participant observes the same pause round.
    PublishHostLevelUpOffers(level, experience, source_progression_address);
    PublishLocalHostSelfLevelUpOffer(
        level,
        experience,
        source_progression_address);
}

bool DebugPublishHostNaturalLevelUpOffer(
    std::uint64_t target_participant_id,
    std::int32_t level,
    std::int32_t experience,
    std::string* error_message) {
    auto fail = [&](std::string message) {
        if (error_message != nullptr) {
            *error_message = std::move(message);
        }
        return false;
    };
    if (!IsLocalTransportHost()) {
        return fail("natural level-up offer requires the local transport host");
    }
    if (target_participant_id == 0 || level <= 0 || experience < 0) {
        return fail("natural level-up offer requires a target and valid progression");
    }
    if (HasUnresolvedIssuedLevelUpOfferForParticipant(target_participant_id)) {
        return fail("target participant already has an unresolved level-up offer");
    }

    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);
    const std::uint32_t run_nonce =
        local != nullptr && local->runtime.valid ? local->runtime.run_nonce : 0;
    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    if (!BeginOrExtendHostLevelUpBarrier(
            {target_participant_id},
            run_nonce,
            level,
            experience,
            0,
            now_ms)) {
        return fail("natural level-up barrier could not be started");
    }

    if (target_participant_id == g_local_transport.local_peer_id) {
        std::vector<BotSkillChoiceOption> options;
        std::string roll_error;
        bool synchronized = false;
        {
            ScopedLocalLevelUpFanoutSuppression suppress_fanout;
            synchronized = SyncLocalPlayerProgressionToSharedLevelUpAndRollChoices(
                level,
                experience,
                &options,
                &roll_error);
        }
        if (!synchronized) {
            return fail("natural host-self choice roll failed: " + roll_error);
        }
        return IssueLocalHostSelfLevelUpOffer(
            level,
            experience,
            std::move(options),
            false,
            error_message);
    }

    const auto* participant =
        FindParticipant(runtime_state, target_participant_id);
    if (participant == nullptr || !IsRemoteParticipant(*participant) ||
        !IsNativeControlledParticipant(*participant) ||
        !participant->transport_connected) {
        return fail("natural level-up offer target is not a connected native participant");
    }
    const auto result = TryPublishHostLevelUpOfferForParticipant(
        *participant,
        run_nonce,
        level,
        experience,
        0,
        true,
        now_ms);
    if (result == HostLevelUpOfferPublishResult::Failed) {
        return fail("natural level-up offer roll failed");
    }
    return true;
}

bool DebugPublishHostLevelUpOffer(
    std::uint64_t target_participant_id,
    std::int32_t level,
    std::int32_t experience,
    std::int32_t option_id,
    std::int32_t apply_count,
    std::string* error_message) {
    auto fail = [&](std::string message) {
        if (error_message != nullptr) {
            *error_message = std::move(message);
        }
        return false;
    };

    if (!IsLocalTransportHost()) {
        return fail("deterministic level-up offer requires the local transport host");
    }
    if (target_participant_id == 0) {
        return fail("deterministic level-up offer requires a target participant id");
    }
    if (level <= 0 || experience < 0) {
        return fail("deterministic level-up offer requires valid progression values");
    }
    if (option_id < 0 || apply_count <= 0 || apply_count > 2) {
        return fail("deterministic level-up offer requires a valid option and apply_count 1..2");
    }
    if (HasUnresolvedIssuedLevelUpOfferForParticipant(target_participant_id)) {
        return fail("target participant already has an unresolved level-up offer");
    }

    const auto runtime_state = SnapshotRuntimeState();
    const bool target_self = target_participant_id == g_local_transport.local_peer_id;
    const auto* participant = target_self
        ? FindLocalParticipant(runtime_state)
        : FindParticipant(runtime_state, target_participant_id);
    if (participant == nullptr) {
        return fail("deterministic level-up offer target participant is unavailable");
    }
    if (!participant->transport_connected) {
        return fail("deterministic level-up offer target transport is disconnected");
    }
    if (!participant->owned_progression.initialized) {
        return fail("deterministic level-up offer target progression is uninitialized");
    }
    if (participant->owned_progression.progression_book_truncated) {
        return fail("deterministic level-up offer target progression book is truncated");
    }
    if (!target_self &&
        (!IsRemoteParticipant(*participant) ||
         !IsNativeControlledParticipant(*participant))) {
        return fail("deterministic level-up offer target is not a native remote participant");
    }

    const auto* entry = FindProgressionBookEntryById(
        participant->owned_progression,
        option_id);
    if (entry == nullptr) {
        return fail("deterministic level-up offer option is outside the native progression book");
    }
    if (entry->statbook_max_level > 0 &&
        static_cast<std::int32_t>(entry->active) + apply_count >
            entry->statbook_max_level) {
        return fail("deterministic level-up offer option would exceed its native max level");
    }

    std::string sync_error;
    if (target_self) {
        bool synchronized = false;
        {
            ScopedLocalLevelUpFanoutSuppression suppress_fanout;
            synchronized = SyncLocalPlayerProgressionToSharedLevelUp(
                level,
                experience,
                &sync_error);
        }
        if (!synchronized) {
            return fail("deterministic host-self progression sync failed: " + sync_error);
        }
    } else {
        bool synchronized = false;
        {
            ScopedLocalLevelUpFanoutSuppression suppress_fanout;
            synchronized = SyncParticipantProgressionToSharedLevelUp(
                target_participant_id,
                level,
                experience,
                0,
                &sync_error);
        }
        if (!synchronized) {
            return fail("deterministic remote progression sync failed: " + sync_error);
        }
    }

    BotSkillChoiceOption option;
    option.option_id = option_id;
    option.apply_count = apply_count;
    std::vector<BotSkillChoiceOption> options = {option};
    if (target_self) {
        return IssueLocalHostSelfLevelUpOffer(
            level,
            experience,
            std::move(options),
            true,
            error_message);
    }

    const auto* local = FindLocalParticipant(runtime_state);
    const std::uint32_t run_nonce =
        local != nullptr && local->runtime.valid ? local->runtime.run_nonce : 0;
    if (!IssueHostLevelUpOfferForParticipant(
        target_participant_id,
        run_nonce,
        level,
        experience,
        std::move(options),
        true)) {
        return fail("deterministic remote level-up offer could not be issued");
    }
    Log(
        "Multiplayer deterministic level-up offer issued. target_participant_id=" +
        std::to_string(target_participant_id) +
        " level=" + std::to_string(level) +
        " xp=" + std::to_string(experience) +
        " option_id=" + std::to_string(option_id) +
        " apply_count=" + std::to_string(apply_count));
    return true;
}
