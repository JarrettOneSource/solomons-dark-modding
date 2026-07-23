void ProcessLuaExecQueueOnMainThread() {
    LuaExecPumpGeneration().fetch_add(1, std::memory_order_release);
    auto drained = DrainLuaExecQueue();
    if (drained.empty()) {
        return;
    }

    std::unique_lock<std::mutex> lock(LuaEngineMutex());
    lua_exec_diag::g_last_lua_locked_ms.store(
        static_cast<std::uint64_t>(GetTickCount64()),
        std::memory_order_release);
    if (!LuaEngineInitializedFlag()) {
        lock.unlock();
        ResolveDrainedAsError(drained, "Lua engine is not initialized.");
        return;
    }

    auto& mods = LoadedLuaModsStorage();
    lua_State* shared_state =
        (mods.empty() || mods.front() == nullptr) ? nullptr : mods.front()->state;

    std::vector<std::pair<std::shared_ptr<PendingLuaExecRequest>, LuaExecResult>>
        completed;
    completed.reserve(drained.size());
    for (const auto& request : drained) {
        if (!TryClaimLuaExecRequest(request)) {
            continue;
        }
        completed.emplace_back(
            request,
            ExecuteLuaCodeOnLockedState(shared_state, request->code));
    }

    lock.unlock();
    for (auto& [request, result] : completed) {
        FinishLuaExecRequest(request, std::move(result));
    }
}

bool HasConnectedRemoteNetworkParticipant() {
    const auto runtime = multiplayer::SnapshotFoundationState();
    return std::any_of(
        runtime.participants.begin(),
        runtime.participants.end(),
        [](const multiplayer::ParticipantInfo& participant) {
            return multiplayer::IsRemoteParticipant(participant) &&
                participant.controller_kind ==
                    multiplayer::ParticipantControllerKind::Native &&
                participant.transport_connected;
        });
}

}  // namespace
}  // namespace detail

void PumpLuaExecQueueOnMainThread() {
    detail::ProcessLuaExecQueueOnMainThread();
    const bool multiplayer_connected = detail::HasConnectedRemoteNetworkParticipant();
    std::scoped_lock lock(detail::LuaEngineMutex());
    if (detail::LuaEngineInitializedFlag()) {
        detail::PollLuaHotReloadsOnLockedThread(
            multiplayer_connected,
            static_cast<std::uint64_t>(GetTickCount64()));
    }
}

void PumpLuaWorkOnMainThread(const SDModRuntimeTickContext& context) {
    detail::ProcessLuaExecQueueOnMainThread();

    const bool multiplayer_connected = detail::HasConnectedRemoteNetworkParticipant();
    std::scoped_lock lock(detail::LuaEngineMutex());
    if (!detail::LuaEngineInitializedFlag()) {
        return;
    }
    detail::PollLuaHotReloadsOnLockedThread(
        multiplayer_connected,
        static_cast<std::uint64_t>(GetTickCount64()));
    detail::DispatchPendingLuaNetMessages();
    detail::DispatchPendingLuaUiActions();
    detail::DispatchPendingLuaRegisteredSpellCasts(context);
    detail::TickLuaRegisteredSpellEffects(context);
    detail::DispatchPendingLuaEventsToLuaMods();
    detail::DispatchLuaEnemyAiThink(context);
    detail::TickLuaAudioRuntime();
    if (detail::HasAnyLuaRuntimeTickHandlers()) {
        detail::DispatchRuntimeTickToLuaMods(context);
    }
}

void PumpLuaWorkOnGameplayThread(const SDModRuntimeTickContext& context) {
    detail::ProcessLuaExecQueueOnMainThread();

    const bool multiplayer_connected = detail::HasConnectedRemoteNetworkParticipant();
    std::scoped_lock lock(detail::LuaEngineMutex());
    if (!detail::LuaEngineInitializedFlag()) {
        return;
    }
    detail::PollLuaHotReloadsOnLockedThread(
        multiplayer_connected,
        static_cast<std::uint64_t>(GetTickCount64()));
    detail::DispatchPendingLuaNetMessages();
    detail::DispatchPendingLuaUiActions();
    detail::DispatchPendingLuaRegisteredSpellCasts(context);
    detail::TickLuaRegisteredSpellEffects(context);
    detail::DispatchPendingLuaEventsToLuaMods();
    detail::DispatchLuaEnemyAiThink(context);
    detail::TickLuaAudioRuntime();
    if (detail::HasAnyLuaRuntimeTickHandlers()) {
        detail::DispatchRuntimeTickToLuaMods(context);
    }
}

}  // namespace sdmod
