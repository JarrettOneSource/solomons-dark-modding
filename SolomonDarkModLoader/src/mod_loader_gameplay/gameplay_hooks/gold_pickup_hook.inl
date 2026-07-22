void __fastcall HookGoldPickupTick(void* self, void* /*unused_edx*/) {
    const auto original =
        GetX86HookTrampoline<GoldPickupTickFn>(g_gameplay_keyboard_injection.gold_pickup_hook);
    if (original == nullptr) {
        return;
    }

    const auto gold_address = reinterpret_cast<uintptr_t>(self);
    if (multiplayer::IsLocalTransportClient()) {
        if (IsReplicatedLootPresentationActorInternal(gold_address)) {
            SDModReplicatedGoldPickupFeedbackState feedback;
            if (TryBeginAcceptedReplicatedGoldPickupFeedbackForActorInternal(
                    gold_address,
                    &feedback)) {
                SDModPlayerState player_state;
                float original_x = 0.0f;
                float original_y = 0.0f;
                const std::uint32_t pickup_ready_lifetime = 1;
                auto& memory = ProcessMemory::Instance();
                const bool position_read =
                    memory.TryReadField(gold_address, kActorPositionXOffset, &original_x) &&
                    memory.TryReadField(gold_address, kActorPositionYOffset, &original_y);
                const bool prepared =
                    position_read &&
                    TryGetPlayerState(&player_state) &&
                    player_state.valid &&
                    std::isfinite(player_state.x) &&
                    std::isfinite(player_state.y) &&
                    memory.TryWriteField(gold_address, kActorPositionXOffset, player_state.x) &&
                    memory.TryWriteField(gold_address, kActorPositionYOffset, player_state.y) &&
                    memory.TryWriteField(
                        gold_address,
                        kReplicatedGoldLifetimeOffset,
                        pickup_ready_lifetime) &&
                    TryWriteResolvedGlobalInt(
                        kGoldGlobal,
                        feedback.resulting_gold - feedback.amount);
                if (!prepared) {
                    if (position_read) {
                        (void)memory.TryWriteField(
                            gold_address,
                            kActorPositionXOffset,
                            original_x);
                        (void)memory.TryWriteField(
                            gold_address,
                            kActorPositionYOffset,
                            original_y);
                    }
                    AbortReplicatedGoldPickupFeedbackInternal(
                        feedback.network_drop_id,
                        gold_address);
                    return;
                }

                original(self);
                std::uint8_t pending_remove = 0;
                const bool stock_feedback_applied =
                    memory.TryReadField(
                        gold_address,
                        kActorPendingRemoveOffset,
                        &pending_remove) &&
                    pending_remove != 0;
                const bool finalized =
                    TryWriteResolvedGlobalInt(kGoldGlobal, feedback.resulting_gold);
                if (stock_feedback_applied) {
                    CompleteReplicatedGoldPickupFeedbackInternal(
                        feedback.network_drop_id,
                        gold_address,
                        static_cast<std::uint64_t>(::GetTickCount64()));
                } else {
                    (void)memory.TryWriteField(
                        gold_address,
                        kActorPositionXOffset,
                        original_x);
                    (void)memory.TryWriteField(
                        gold_address,
                        kActorPositionYOffset,
                        original_y);
                    AbortReplicatedGoldPickupFeedbackInternal(
                        feedback.network_drop_id,
                        gold_address);
                }
                if (!finalized) {
                    Log(
                        "replicated_loot: stock gold feedback ran but final gold enforcement failed. "
                        "network_drop_id=" + std::to_string(feedback.network_drop_id) +
                        " resulting_gold=" + std::to_string(feedback.resulting_gold));
                }
                return;
            }
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
