void DispatchPendingMultiplayerGameOverOnAppTick() {
    const auto original =
        GetX86HookTrampoline<RunEndedFn>(
            g_state.hooks[kHookRunEnded]);
    if (original == nullptr ||
        !multiplayer::ConsumePendingNativeGameOverDispatch()) {
        return;
    }

    g_state.run_active.store(false, std::memory_order_release);
    original();
    CompleteRunLifecycleEnd(
        "all_players_dead",
        true,
        false);
    multiplayer::NotifyNativeGameOverDispatched();
}
