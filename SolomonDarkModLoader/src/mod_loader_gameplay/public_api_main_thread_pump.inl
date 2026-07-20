void PumpGameplayMainThreadWork() {
    multiplayer::TickSessionAndTransportOnAppThread(
        static_cast<std::uint64_t>(GetTickCount64()));

    if (!g_gameplay_keyboard_injection.initialized) {
        return;
    }

    PumpQueuedGameplayActions();
}

void PumpGameplayPostStockTickWork() {
    if (!g_gameplay_keyboard_injection.initialized) {
        return;
    }

    PumpHostLootDropDeactivation();
}
