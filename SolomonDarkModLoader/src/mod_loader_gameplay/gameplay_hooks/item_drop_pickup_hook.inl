constexpr float kRemoteItemDropPickupSuppressionDistance = 320.0f;

bool IsWithinItemDropPickupSuppressionRange(
    float actor_x,
    float actor_y,
    float drop_x,
    float drop_y,
    float drop_radius) {
    const float pickup_distance =
        kRemoteItemDropPickupSuppressionDistance + (std::max)(drop_radius, 0.0f);
    const float dx = actor_x - drop_x;
    const float dy = actor_y - drop_y;
    return dx * dx + dy * dy <= pickup_distance * pickup_distance;
}

bool ShouldSuppressRemoteParticipantItemDropPickup(uintptr_t drop_address) {
    if (drop_address == 0 ||
        kItemDropHeldItemOffset == 0 ||
        !multiplayer::IsLocalTransportHost()) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    std::uint32_t held_item_address = 0;
    if (!memory.TryReadField(drop_address, kItemDropHeldItemOffset, &held_item_address) ||
        held_item_address == 0) {
        return false;
    }

    const auto runtime_state = multiplayer::SnapshotRuntimeState();
    const auto* local = multiplayer::FindLocalParticipant(runtime_state);
    if (local == nullptr ||
        !local->runtime.valid ||
        !local->runtime.in_run ||
        local->runtime.scene_intent.kind != multiplayer::ParticipantSceneIntentKind::Run) {
        return false;
    }

    float drop_x = 0.0f;
    float drop_y = 0.0f;
    float drop_radius = 0.0f;
    if (!TryReadActorPositionAndRadius(drop_address, &drop_x, &drop_y, &drop_radius)) {
        return false;
    }

    SDModPlayerState player_state;
    if (TryGetPlayerState(&player_state) &&
        player_state.valid &&
        IsWithinItemDropPickupSuppressionRange(
            player_state.x,
            player_state.y,
            drop_x,
            drop_y,
            drop_radius)) {
        return false;
    }

    std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
    for (const auto& binding : g_participant_entities) {
        if (binding.actor_address == 0 ||
            !IsGameplaySlotWizardKind(binding.kind) ||
            !IsNativeRemoteParticipantBinding(&binding)) {
            continue;
        }

        const auto* participant = multiplayer::FindParticipant(runtime_state, binding.bot_id);
        if (participant == nullptr ||
            !multiplayer::IsRemoteParticipant(*participant) ||
            !multiplayer::IsNativeControlledParticipant(*participant) ||
            !participant->runtime.valid ||
            !participant->runtime.in_run ||
            participant->runtime.scene_intent.kind != multiplayer::ParticipantSceneIntentKind::Run) {
            continue;
        }
        if (local->runtime.run_nonce != 0 &&
            participant->runtime.run_nonce != 0 &&
            local->runtime.run_nonce != participant->runtime.run_nonce) {
            continue;
        }

        float actor_x = 0.0f;
        float actor_y = 0.0f;
        float actor_radius = 0.0f;
        if (!TryReadActorPositionAndRadius(binding.actor_address, &actor_x, &actor_y, &actor_radius)) {
            continue;
        }
        if (IsWithinItemDropPickupSuppressionRange(actor_x, actor_y, drop_x, drop_y, drop_radius)) {
            return true;
        }
    }

    return false;
}

void __fastcall HookItemDropPickupTick(void* self, void* /*unused_edx*/) {
    const auto original =
        GetX86HookTrampoline<ItemDropPickupTickFn>(g_gameplay_keyboard_injection.item_drop_pickup_hook);
    if (original == nullptr) {
        return;
    }

    const auto drop_address = reinterpret_cast<uintptr_t>(self);
    if (ShouldSuppressRemoteParticipantItemDropPickup(drop_address)) {
        return;
    }

    original(self);
}
