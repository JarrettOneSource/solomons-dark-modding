bool ReadParticipantLoadoutDetails(
    std::uint64_t participant_id,
    BotLoadoutDetails* details) {
    if (details == nullptr) {
        return false;
    }
    *details = BotLoadoutDetails{};
    details->participant_id = participant_id;
    if (participant_id == 0) {
        return false;
    }

    const auto runtime = SnapshotRuntimeState();
    const auto* participant =
        FindParticipant(runtime, participant_id);
    if (participant == nullptr) {
        return false;
    }

    SDModParticipantGameplayState gameplay_state;
    const bool gameplay_state_available =
        TryGetParticipantGameplayState(
            participant_id,
            &gameplay_state) &&
        gameplay_state.available;
    const auto progression_runtime_address =
        gameplay_state_available
            ? gameplay_state.progression_runtime_state_address
            : 0;
    const auto actor_address =
        gameplay_state_available
            ? gameplay_state.actor_address
            : 0;
    const auto revisions =
        ResolveBotLoadoutRevisionTuple(*participant);

    std::int32_t active_weld_build_id = -1;
    {
        std::scoped_lock lock(g_bot_runtime_mutex);
        if (!g_bot_runtime_initialized) {
            return false;
        }
        const auto* active =
            FindActiveBotWeldBuild(participant_id);
        if (active != nullptr) {
            active_weld_build_id = active->build_id;
        }

        const auto* cached =
            FindCachedParticipantLoadoutDetails(participant_id);
        if (cached != nullptr &&
            BotLoadoutRevisionTuplesEqual(
                cached->revisions,
                revisions) &&
            cached->progression_runtime_address ==
                progression_runtime_address &&
            cached->actor_address == actor_address &&
            cached->active_weld_build_id ==
                active_weld_build_id) {
            *details = cached->details;
        }
    }

    if (!details->available) {
        ResolveStaticParticipantLoadoutDetails(
            *participant,
            progression_runtime_address,
            actor_address,
            active_weld_build_id,
            details);

        CachedParticipantLoadoutDetails cache_entry;
        cache_entry.participant_id = participant_id;
        cache_entry.revisions = revisions;
        cache_entry.progression_runtime_address =
            progression_runtime_address;
        cache_entry.actor_address = actor_address;
        cache_entry.active_weld_build_id =
            active_weld_build_id;
        cache_entry.details = *details;
        {
            std::scoped_lock lock(g_bot_runtime_mutex);
            auto* cached =
                FindCachedParticipantLoadoutDetails(
                    participant_id);
            if (cached == nullptr) {
                g_loadout_details_cache.push_back(
                    std::move(cache_entry));
            } else {
                *cached = std::move(cache_entry);
            }
        }
    }

    OverlayLiveSecondaryCooldowns(
        progression_runtime_address,
        details);

    details->pending_weld_build_id = 0;
    details->pending_weld_build_id_resolved = false;
    {
        std::scoped_lock lock(g_bot_runtime_mutex);
        const auto* pending =
            FindPendingSkillChoiceConst(participant_id);
        if (pending != nullptr &&
            pending->pending_weld_build_id_resolved &&
            IsNativeWeldBuildId(
                pending->pending_weld_build_id)) {
            details->pending_weld_build_id =
                pending->pending_weld_build_id;
            details->pending_weld_build_id_resolved = true;
        }
    }
    return true;
}
