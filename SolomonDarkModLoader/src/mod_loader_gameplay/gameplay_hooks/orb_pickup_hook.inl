constexpr float kRemoteOrbPickupSuppressionDistance = 320.0f;

bool TryReadActorPositionAndRadius(uintptr_t actor_address, float* x, float* y, float* radius) {
    if (x == nullptr || y == nullptr || radius == nullptr) {
        return false;
    }

    *x = 0.0f;
    *y = 0.0f;
    *radius = 0.0f;
    if (kActorPositionXOffset == 0 ||
        kActorPositionYOffset == 0 ||
        !TryReadFiniteFloatField(actor_address, kActorPositionXOffset, x) ||
        !TryReadFiniteFloatField(actor_address, kActorPositionYOffset, y)) {
        return false;
    }

    float read_radius = 0.0f;
    if (kActorCollisionRadiusOffset != 0 &&
        TryReadFiniteFloatField(actor_address, kActorCollisionRadiusOffset, &read_radius) &&
        read_radius > 0.0f) {
        *radius = read_radius;
    }
    return true;
}

bool IsWithinOrbPickupSuppressionRange(
    float actor_x,
    float actor_y,
    float orb_x,
    float orb_y,
    float orb_radius) {
    const float pickup_distance =
        kRemoteOrbPickupSuppressionDistance + (std::max)(orb_radius, 0.0f);
    const float dx = actor_x - orb_x;
    const float dy = actor_y - orb_y;
    return dx * dx + dy * dy <= pickup_distance * pickup_distance;
}

bool ShouldSuppressRemoteParticipantOrbPickup(uintptr_t orb_address) {
    if (orb_address == 0 || !multiplayer::IsLocalTransportHost()) {
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

    float orb_x = 0.0f;
    float orb_y = 0.0f;
    float orb_radius = 0.0f;
    if (!TryReadActorPositionAndRadius(orb_address, &orb_x, &orb_y, &orb_radius)) {
        return false;
    }

    SDModPlayerState player_state;
    if (TryGetPlayerState(&player_state) &&
        player_state.valid &&
        IsWithinOrbPickupSuppressionRange(player_state.x, player_state.y, orb_x, orb_y, orb_radius)) {
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
        if (IsWithinOrbPickupSuppressionRange(actor_x, actor_y, orb_x, orb_y, orb_radius)) {
            return true;
        }
    }

    return false;
}

void __fastcall HookOrbPickupTick(void* self, void* /*unused_edx*/) {
    const auto original =
        GetX86HookTrampoline<OrbPickupTickFn>(g_gameplay_keyboard_injection.orb_pickup_hook);
    if (original == nullptr) {
        return;
    }

    const auto orb_address = reinterpret_cast<uintptr_t>(self);
    if (ShouldSuppressRemoteParticipantOrbPickup(orb_address)) {
        return;
    }

    original(self);
}
