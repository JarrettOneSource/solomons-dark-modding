constexpr std::uint8_t kSuppressedPowerupApplyKind = 3;

const char* ReplicatedPowerupPickupNotificationText(std::int32_t powerup_kind) {
    switch (static_cast<multiplayer::PowerupRewardKind>(powerup_kind)) {
    case multiplayer::PowerupRewardKind::BonusSkillPoint:
        return "BONUS SKILL POINT";
    case multiplayer::PowerupRewardKind::RandomSkillRank:
        return "SKILL IMPROVED";
    case multiplayer::PowerupRewardKind::DamageX4:
        return "DAMAGE x4";
    }
    return nullptr;
}

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
            SDModReplicatedLootPickupFeedbackState feedback;
            if (TryBeginAcceptedReplicatedLootPickupFeedbackForActorInternal(
                    powerup_address,
                    multiplayer::LootDropKind::Powerup,
                    &feedback)) {
                auto& memory = ProcessMemory::Instance();
                SDModPlayerState player_state;
                float original_x = 0.0f;
                float original_y = 0.0f;
                std::uint8_t original_kind = 0;
                const bool actor_fields_read =
                    memory.TryReadField(
                        powerup_address,
                        kActorPositionXOffset,
                        &original_x) &&
                    memory.TryReadField(
                        powerup_address,
                        kActorPositionYOffset,
                        &original_y) &&
                    memory.TryReadField(
                        powerup_address,
                        kReplicatedPowerupKindOffset,
                        &original_kind);
                const bool prepared =
                    actor_fields_read &&
                    TryGetPlayerState(&player_state) &&
                    player_state.valid &&
                    std::isfinite(player_state.x) &&
                    std::isfinite(player_state.y) &&
                    memory.TryWriteField(
                        powerup_address,
                        kActorPositionXOffset,
                        player_state.x) &&
                    memory.TryWriteField(
                        powerup_address,
                        kActorPositionYOffset,
                        player_state.y) &&
                    memory.TryWriteField(
                        powerup_address,
                        kReplicatedPowerupKindOffset,
                        kSuppressedPowerupApplyKind);
                if (!prepared) {
                    if (actor_fields_read) {
                        (void)memory.TryWriteField(
                            powerup_address,
                            kActorPositionXOffset,
                            original_x);
                        (void)memory.TryWriteField(
                            powerup_address,
                            kActorPositionYOffset,
                            original_y);
                        (void)memory.TryWriteField(
                            powerup_address,
                            kReplicatedPowerupKindOffset,
                            original_kind);
                    }
                    AbortReplicatedLootPickupFeedbackInternal(
                        feedback.network_drop_id,
                        powerup_address);
                    return;
                }

                ++g_accepted_replicated_loot_feedback_depth;
                original(self);
                --g_accepted_replicated_loot_feedback_depth;

                std::uint8_t pending_remove = 0;
                const bool stock_feedback_applied =
                    memory.TryReadField(
                        powerup_address,
                        kActorPendingRemoveOffset,
                        &pending_remove) &&
                    pending_remove != 0;
                bool notification_applied = false;
                DWORD notification_exception_code = 0;
                if (stock_feedback_applied) {
                    const auto* notification_text =
                        ReplicatedPowerupPickupNotificationText(feedback.powerup_kind);
                    notification_applied = CallNativePickupNotificationSafe(
                        notification_text,
                        NativeRgbaColor{},
                        &notification_exception_code);
                    CompleteReplicatedLootPickupFeedbackInternal(
                        feedback.network_drop_id,
                        powerup_address,
                        true,
                        notification_applied,
                        static_cast<std::uint64_t>(::GetTickCount64()));
                } else {
                    (void)memory.TryWriteField(
                        powerup_address,
                        kActorPositionXOffset,
                        original_x);
                    (void)memory.TryWriteField(
                        powerup_address,
                        kActorPositionYOffset,
                        original_y);
                    (void)memory.TryWriteField(
                        powerup_address,
                        kReplicatedPowerupKindOffset,
                        original_kind);
                    AbortReplicatedLootPickupFeedbackInternal(
                        feedback.network_drop_id,
                        powerup_address);
                }
                if (stock_feedback_applied && !notification_applied) {
                    Log(
                        "replicated_loot: powerup actor feedback applied but native pickup "
                        "notification failed. network_drop_id=" +
                        std::to_string(feedback.network_drop_id) +
                        " seh=" + HexString(
                            static_cast<uintptr_t>(notification_exception_code)));
                }
                return;
            }
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
