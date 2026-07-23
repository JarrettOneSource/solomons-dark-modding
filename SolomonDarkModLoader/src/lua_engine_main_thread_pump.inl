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

    for (const auto& request : drained) {
        if (!TryClaimLuaExecRequest(request)) {
            continue;
        }
        LuaExecResult result = ExecuteLuaCodeOnLockedState(shared_state, request->code);
        FinishLuaExecRequest(request, std::move(result));
    }
}

}  // namespace
}  // namespace detail

void PumpLuaExecQueueOnMainThread() {
    detail::ProcessLuaExecQueueOnMainThread();
}

void PumpLuaWorkOnMainThread(const SDModRuntimeTickContext& context) {
    detail::ProcessLuaExecQueueOnMainThread();

    std::scoped_lock lock(detail::LuaEngineMutex());
    if (!detail::LuaEngineInitializedFlag()) {
        return;
    }
    detail::DispatchPendingLuaRegisteredSpellCasts(context);
    detail::TickLuaRegisteredSpellEffects(context);
    detail::DispatchPendingLuaEventsToLuaMods();
    if (detail::HasAnyLuaRuntimeTickHandlers()) {
        detail::DispatchRuntimeTickToLuaMods(context);
    }
}

void PumpLuaWorkOnGameplayThread(const SDModRuntimeTickContext& context) {
    detail::ProcessLuaExecQueueOnMainThread();

    std::scoped_lock lock(detail::LuaEngineMutex());
    if (!detail::LuaEngineInitializedFlag()) {
        return;
    }
    detail::DispatchPendingLuaRegisteredSpellCasts(context);
    detail::TickLuaRegisteredSpellEffects(context);
    detail::DispatchPendingLuaEventsToLuaMods();
    if (detail::HasAnyLuaRuntimeTickHandlers()) {
        detail::DispatchRuntimeTickToLuaMods(context);
    }
}

}  // namespace sdmod
