constexpr std::uint64_t kReplicatedLootPickupRequestRetryMs = 250;

std::unordered_map<std::uint64_t, std::uint64_t> g_replicated_loot_pickup_request_not_before_ms;

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

bool IsWithinStockLootBehaviorRange(
    float actor_x,
    float actor_y,
    float drop_x,
    float drop_y,
    multiplayer::LootDropKind drop_kind,
    float pickup_range) {
    const float behavior_distance =
        multiplayer::StockLootBehaviorDistance(drop_kind, pickup_range);
    if (!std::isfinite(behavior_distance) || behavior_distance <= 0.0f) {
        return false;
    }
    const float dx = actor_x - drop_x;
    const float dy = actor_y - drop_y;
    return dx * dx + dy * dy <= behavior_distance * behavior_distance;
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
        player_state.derived_stats.valid &&
        IsWithinStockLootBehaviorRange(
            player_state.x,
            player_state.y,
            orb_x,
            orb_y,
            multiplayer::LootDropKind::Orb,
            player_state.derived_stats.pickup_range)) {
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
        const auto& derived = participant->owned_progression.derived_stats;
        if (derived.valid &&
            IsWithinStockLootBehaviorRange(
                actor_x,
                actor_y,
                orb_x,
                orb_y,
                multiplayer::LootDropKind::Orb,
                derived.pickup_range)) {
            return true;
        }
    }

    return false;
}

bool TryQueueReplicatedLootPickupRequest(
    uintptr_t actor_address,
    multiplayer::LootDropKind drop_kind,
    std::uint64_t now_ms,
    const char* source_label) {
    if (actor_address == 0 ||
        drop_kind == multiplayer::LootDropKind::Unknown ||
        !multiplayer::IsLocalTransportClient()) {
        return false;
    }

    SDModReplicatedLootPresentationState presentation;
    bool found = false;
    std::vector<SDModReplicatedLootPresentationState> presentations;
    GetReplicatedLootPresentationStatesInternal(&presentations);
    for (const auto& candidate : presentations) {
        if (candidate.valid &&
            candidate.actor_address == actor_address &&
            candidate.network_drop_id != 0 &&
            candidate.active &&
            candidate.drop_kind == drop_kind) {
            presentation = candidate;
            found = true;
            break;
        }
    }
    if (!found) {
        return false;
    }

    const auto runtime_state = multiplayer::SnapshotRuntimeState();
    const auto* local = multiplayer::FindLocalParticipant(runtime_state);
    const auto local_transport_participant_id =
        multiplayer::GetLocalTransportParticipantId();
    const auto& last_result = runtime_state.last_loot_pickup_result;
    if (local != nullptr &&
        local_transport_participant_id != 0 &&
        last_result.valid &&
        last_result.participant_id == local_transport_participant_id &&
        last_result.run_nonce == local->runtime.run_nonce &&
        last_result.network_drop_id == presentation.network_drop_id &&
        (last_result.result_code == multiplayer::LootPickupResultCode::Accepted ||
         last_result.result_code == multiplayer::LootPickupResultCode::AlreadyGone)) {
        g_replicated_loot_pickup_request_not_before_ms.erase(presentation.network_drop_id);
        return true;
    }

    float drop_x = 0.0f;
    float drop_y = 0.0f;
    float drop_radius = 0.0f;
    if (!TryReadActorPositionAndRadius(actor_address, &drop_x, &drop_y, &drop_radius)) {
        return false;
    }
    const float authoritative_drop_x = presentation.x;
    const float authoritative_drop_y = presentation.y;
    if (!std::isfinite(authoritative_drop_x) || !std::isfinite(authoritative_drop_y)) {
        return false;
    }

    SDModPlayerState player_state;
    if (!TryGetPlayerState(&player_state) ||
        !player_state.valid ||
        !player_state.derived_stats.valid ||
        !IsWithinStockLootBehaviorRange(
            player_state.x,
            player_state.y,
            authoritative_drop_x,
            authoritative_drop_y,
            drop_kind,
            player_state.derived_stats.pickup_range)) {
        return false;
    }

    const auto retry_it =
        g_replicated_loot_pickup_request_not_before_ms.find(presentation.network_drop_id);
    if (retry_it != g_replicated_loot_pickup_request_not_before_ms.end() &&
        now_ms < retry_it->second) {
        return true;
    }

    std::uint32_t request_sequence = 0;
    std::string error_message;
    multiplayer::LootPickupRequestCapture pickup_capture;
    pickup_capture.valid = true;
    pickup_capture.requester_position_x = player_state.x;
    pickup_capture.requester_position_y = player_state.y;
    pickup_capture.drop_position_x = authoritative_drop_x;
    pickup_capture.drop_position_y = authoritative_drop_y;
    if (multiplayer::QueueLocalLootPickupRequest(
            presentation.network_drop_id,
            &request_sequence,
            &error_message,
            &pickup_capture)) {
        g_replicated_loot_pickup_request_not_before_ms[presentation.network_drop_id] =
            now_ms + kReplicatedLootPickupRequestRetryMs;
        Log(
            "replicated_loot: queued pickup request from presentation actor. kind=" +
            std::string(multiplayer::LootDropKindLabel(drop_kind)) +
            " source=" + std::string(source_label != nullptr ? source_label : "unknown") +
            " network_drop_id=" +
            std::to_string(presentation.network_drop_id) +
            " actor=" + HexString(actor_address) +
            " request_sequence=" + std::to_string(request_sequence));
        return true;
    }

    g_replicated_loot_pickup_request_not_before_ms[presentation.network_drop_id] =
        now_ms + kReplicatedLootPickupRequestRetryMs;
    Log(
        "replicated_loot: failed to queue pickup request from presentation actor. kind=" +
        std::string(multiplayer::LootDropKindLabel(drop_kind)) +
        " source=" + std::string(source_label != nullptr ? source_label : "unknown") +
        " network_drop_id=" +
        std::to_string(presentation.network_drop_id) +
        " actor=" + HexString(actor_address) +
        " error=" + error_message);
    return false;
}

void __fastcall HookOrbPickupTick(void* self, void* /*unused_edx*/) {
    const auto original =
        GetX86HookTrampoline<OrbPickupTickFn>(g_gameplay_keyboard_injection.orb_pickup_hook);
    if (original == nullptr) {
        return;
    }

    const auto orb_address = reinterpret_cast<uintptr_t>(self);
    if (multiplayer::IsLocalTransportClient()) {
        if (IsReplicatedLootPresentationActorInternal(orb_address)) {
            (void)TryQueueReplicatedLootPickupRequest(
                orb_address,
                multiplayer::LootDropKind::Orb,
                static_cast<std::uint64_t>(::GetTickCount64()),
                "client_orb_pickup_tick");
        } else {
            QueueClientLocalLootSuppressionInternal(
                "client_orb_pickup_tick",
                kClientLocalLootSuppressionSettleDelayMs);
        }
        return;
    }
    if (IsReplicatedLootPresentationActorInternal(orb_address)) {
        return;
    }
    if (ShouldSuppressRemoteParticipantOrbPickup(orb_address)) {
        return;
    }

    original(self);
}
