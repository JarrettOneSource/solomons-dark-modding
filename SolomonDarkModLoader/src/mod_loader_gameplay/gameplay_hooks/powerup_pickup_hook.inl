void __fastcall HookPowerupPickupTick(void* self, void* /*unused_edx*/) {
    const auto original =
        GetX86HookTrampoline<PowerupPickupTickFn>(
            g_gameplay_keyboard_injection.powerup_pickup_hook);
    if (original == nullptr) {
        return;
    }

    const auto powerup_address = reinterpret_cast<uintptr_t>(self);
    if (!multiplayer::IsLocalTransportEnabled()) {
        original(self);
        return;
    }

    if (multiplayer::IsLocalTransportClient()) {
        if (IsReplicatedLootPresentationActorInternal(powerup_address)) {
            (void)TryQueueReplicatedLootPickupRequest(
                powerup_address,
                multiplayer::LootDropKind::Powerup,
                static_cast<std::uint64_t>(::GetTickCount64()),
                "client_powerup_pickup_tick");
        } else {
            QueueClientLocalLootSuppressionInternal(
                "client_powerup_pickup_tick",
                kClientLocalLootSuppressionSettleDelayMs);
        }
        return;
    }

    if (multiplayer::IsLocalTransportHost()) {
        multiplayer::LootPickupRequestCapture capture;
        SDModPlayerState player_state;
        float drop_x = 0.0f;
        float drop_y = 0.0f;
        if (TryGetPlayerState(&player_state) &&
            player_state.valid &&
            std::isfinite(player_state.x) &&
            std::isfinite(player_state.y) &&
            TryReadFiniteFloatField(
                powerup_address,
                kActorPositionXOffset,
                &drop_x) &&
            TryReadFiniteFloatField(
                powerup_address,
                kActorPositionYOffset,
                &drop_y)) {
            capture.valid = true;
            capture.requester_position_x = player_state.x;
            capture.requester_position_y = player_state.y;
            capture.drop_position_x = drop_x;
            capture.drop_position_y = drop_y;
        }
        (void)multiplayer::QueueLocalHostPowerupPickup(
            powerup_address,
            &capture);
        return;
    }

    original(self);
}
