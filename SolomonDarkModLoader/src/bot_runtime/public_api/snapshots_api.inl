std::uint32_t GetBotCount() {
    RuntimeState snapshot = SnapshotRuntimeState();
    return static_cast<std::uint32_t>(std::count_if(
        snapshot.participants.begin(),
        snapshot.participants.end(),
        [](const ParticipantInfo& participant) { return IsLuaControlledParticipant(participant); }));
}

bool ReadBotSnapshot(std::uint64_t bot_id, BotSnapshot* snapshot) {
    if (snapshot == nullptr) {
        return false;
    }

    *snapshot = BotSnapshot{};
    RuntimeState runtime = SnapshotRuntimeState();
    const auto* participant = FindBot(runtime, bot_id);
    if (participant == nullptr) {
        return false;
    }

    std::scoped_lock lock(g_bot_runtime_mutex);
    FillBotSnapshot(*participant, snapshot);
    ApplyGameplayStateToSnapshot(bot_id, snapshot);
    ApplyControllerStateToSnapshot(bot_id, snapshot);
    DeriveBotCastReadiness(snapshot);
    return true;
}

bool ReadBotSnapshotByIndex(std::uint32_t index, BotSnapshot* snapshot) {
    if (snapshot == nullptr) {
        return false;
    }

    *snapshot = BotSnapshot{};
    RuntimeState runtime = SnapshotRuntimeState();
    std::uint32_t current_index = 0;
    for (const auto& participant : runtime.participants) {
        if (!IsLuaControlledParticipant(participant)) {
            continue;
        }

        if (current_index == index) {
            std::scoped_lock lock(g_bot_runtime_mutex);
            FillBotSnapshot(participant, snapshot);
            ApplyGameplayStateToSnapshot(participant.participant_id, snapshot);
            ApplyControllerStateToSnapshot(participant.participant_id, snapshot);
            DeriveBotCastReadiness(snapshot);
            return true;
        }

        current_index += 1;
    }

    return false;
}

std::size_t GetPendingBotCastCount() {
    std::scoped_lock lock(g_bot_runtime_mutex);
    return g_pending_casts.size();
}
