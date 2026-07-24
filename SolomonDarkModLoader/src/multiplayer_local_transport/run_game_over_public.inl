bool ConsumePendingNativeGameOverDispatch() {
    if (!g_run_game_over.pending_dispatch ||
        g_run_game_over.accepted_epoch == 0 ||
        g_run_game_over.run_nonce == 0 ||
        g_run_game_over.dispatch_count != 0) {
        return false;
    }
    g_run_game_over.pending_dispatch = false;
    PublishRunGameOverRuntime();
    return true;
}

void NotifyNativeGameOverDispatched() {
    if (g_run_game_over.accepted_epoch == 0 ||
        g_run_game_over.dispatch_count != 0) {
        return;
    }
    g_run_game_over.dispatch_count = 1;
    PublishRunGameOverRuntime();
    Log(
        "Multiplayer native Game Over dispatched. run_nonce=" +
        std::to_string(g_run_game_over.run_nonce) +
        " command_epoch=" +
        std::to_string(g_run_game_over.accepted_epoch));
}
