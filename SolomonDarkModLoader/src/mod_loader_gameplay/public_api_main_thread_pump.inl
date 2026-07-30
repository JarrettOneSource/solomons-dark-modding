void PumpGameplayMainThreadWork() {
    multiplayer::TickGameplayTransportOnAppThread(
        static_cast<std::uint64_t>(GetTickCount64()));

    if (!g_gameplay_keyboard_injection.initialized) {
        return;
    }

    PumpQueuedGameplayActions();
}

void PumpParticipantDestroyRequestsPostStockTick() {
    std::vector<std::uint64_t> destroy_requests;
    {
        std::lock_guard<std::mutex> lock(
            g_gameplay_keyboard_injection
                .pending_gameplay_world_actions_mutex);
        while (!g_gameplay_keyboard_injection
                    .pending_participant_destroy_requests.empty()) {
            destroy_requests.push_back(
                g_gameplay_keyboard_injection
                    .pending_participant_destroy_requests.front());
            g_gameplay_keyboard_injection
                .pending_participant_destroy_requests.pop_front();
        }
    }
    for (const auto participant_id : destroy_requests) {
        DestroyParticipantEntityNow(participant_id);
    }
}

void PumpGameplayPostStockTickWork() {
    if (!g_gameplay_keyboard_injection.initialized) {
        return;
    }

    PumpParticipantDestroyRequestsPostStockTick();
    TickDormantSharedHubOnGameThread();
    PumpHostLootDropDeactivation();
}
