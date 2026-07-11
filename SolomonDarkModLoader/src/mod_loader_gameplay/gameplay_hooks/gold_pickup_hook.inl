void __fastcall HookGoldPickupTick(void* self, void* /*unused_edx*/) {
    const auto original =
        GetX86HookTrampoline<GoldPickupTickFn>(g_gameplay_keyboard_injection.gold_pickup_hook);
    if (original == nullptr) {
        return;
    }

    const auto gold_address = reinterpret_cast<uintptr_t>(self);
    if (multiplayer::IsLocalTransportClient()) {
        if (IsReplicatedLootPresentationActorInternal(gold_address)) {
            (void)TryQueueReplicatedLootPickupRequest(
                gold_address,
                multiplayer::LootDropKind::Gold,
                static_cast<std::uint64_t>(::GetTickCount64()),
                "client_gold_pickup_tick");
        } else {
            QueueClientLocalLootSuppressionInternal(
                "client_gold_pickup_tick",
                kClientLocalLootSuppressionSettleDelayMs);
        }
        return;
    }
    if (IsReplicatedLootPresentationActorInternal(gold_address)) {
        return;
    }

    original(self);
}
