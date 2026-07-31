bool ReadParticipantInventoryDetails(
    std::uint64_t participant_id,
    BotInventoryDetails* details) {
    if (details == nullptr) {
        return false;
    }
    *details = {};
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
    const auto revisions =
        ResolveBotInventoryRevisionTuple(*participant);

    {
        std::scoped_lock lock(g_bot_runtime_mutex);
        if (!g_bot_runtime_initialized) {
            return false;
        }
        const auto* cached =
            FindCachedParticipantInventoryDetails(
                participant_id);
        if (cached != nullptr &&
            BotInventoryRevisionTuplesEqual(
                cached->revisions,
                revisions)) {
            *details = cached->details;
        }
    }

    if (!details->available) {
        BuildStaticParticipantInventoryDetails(
            *participant,
            details);
        CachedParticipantInventoryDetails cache_entry;
        cache_entry.participant_id = participant_id;
        cache_entry.revisions = revisions;
        cache_entry.details = *details;
        {
            std::scoped_lock lock(g_bot_runtime_mutex);
            auto* cached =
                FindCachedParticipantInventoryDetails(
                    participant_id);
            if (cached == nullptr) {
                g_inventory_details_cache.push_back(
                    std::move(cache_entry));
            } else {
                *cached = std::move(cache_entry);
            }
        }
    }

    OverlayLiveParticipantConsumableState(details);
    return true;
}
