void __fastcall HookGoldPickupTick(void* self, void* /*unused_edx*/) {
    const auto original =
        GetX86HookTrampoline<GoldPickupTickFn>(g_gameplay_keyboard_injection.gold_pickup_hook);
    if (original == nullptr) {
        return;
    }

    const auto gold_address = reinterpret_cast<uintptr_t>(self);
    if (multiplayer::IsLocalTransportClient()) {
        (void)RemoveUnboundClientLootActorNow(
            gold_address,
            multiplayer::LootDropKind::Gold,
            "client_gold_pickup_tick");
        return;
    }
    if (IsReplicatedLootPresentationActorInternal(gold_address)) {
        return;
    }

    original(self);
}
