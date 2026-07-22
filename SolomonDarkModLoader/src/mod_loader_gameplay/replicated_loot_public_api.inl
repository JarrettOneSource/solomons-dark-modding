SDModReplicatedLootPresentationState ToPublicReplicatedLootPresentationState(
    const ReplicatedLootPresentationBinding& binding) {
    SDModReplicatedLootPresentationState state;
    state.valid = binding.network_drop_id != 0 && binding.actor_address != 0;
    state.network_drop_id = binding.network_drop_id;
    state.authority_participant_id = binding.authority_participant_id;
    state.scene_epoch = binding.scene_epoch;
    state.run_nonce = binding.run_nonce;
    state.native_type_id = binding.native_type_id;
    state.drop_kind = binding.drop_kind;
    state.actor_address = binding.actor_address;
    state.active = binding.active;
    state.amount = binding.amount;
    state.amount_tier = binding.amount_tier;
    state.value = binding.value;
    state.motion = binding.motion;
    state.progress = binding.progress;
    state.auxiliary = binding.auxiliary;
    state.lifetime = binding.lifetime;
    state.x = binding.x;
    state.y = binding.y;
    state.radius = binding.radius;
    state.last_seen_ms = binding.last_seen_ms;
    return state;
}

bool QueueReplicatedLootSnapshotInternal(
    const multiplayer::LootSnapshotRuntimeInfo& snapshot,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!g_gameplay_keyboard_injection.initialized) {
        if (error_message != nullptr) {
            *error_message = "Gameplay action pump is not initialized.";
        }
        return false;
    }
    if (!multiplayer::IsLocalTransportClient()) {
        if (error_message != nullptr) {
            *error_message = "Replicated loot materialization is client-only.";
        }
        return false;
    }

    std::lock_guard<std::mutex> lock(
        g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
    g_gameplay_keyboard_injection.pending_replicated_loot_snapshots.clear();
    g_gameplay_keyboard_injection.pending_replicated_loot_snapshots.push_back(snapshot);
    return true;
}

bool IsReplicatedLootPresentationActorInternal(uintptr_t actor_address) {
    if (actor_address == 0) {
        return false;
    }
    std::lock_guard<std::mutex> lock(g_replicated_loot_presentation_mutex);
    return std::find_if(
               g_replicated_loot_presentations.begin(),
               g_replicated_loot_presentations.end(),
               [&](const ReplicatedLootPresentationBinding& binding) {
                   return binding.actor_address == actor_address;
               }) != g_replicated_loot_presentations.end();
}

bool TryGetReplicatedLootPresentationStateInternal(
    std::uint64_t network_drop_id,
    SDModReplicatedLootPresentationState* state) {
    if (state == nullptr) {
        return false;
    }
    *state = SDModReplicatedLootPresentationState{};
    std::lock_guard<std::mutex> lock(g_replicated_loot_presentation_mutex);
    const auto* binding = FindReplicatedLootPresentationBindingLocked(network_drop_id);
    if (binding == nullptr) {
        return false;
    }
    *state = ToPublicReplicatedLootPresentationState(*binding);
    return true;
}

void GetReplicatedLootPresentationStatesInternal(
    std::vector<SDModReplicatedLootPresentationState>* states) {
    if (states == nullptr) {
        return;
    }
    states->clear();
    std::lock_guard<std::mutex> lock(g_replicated_loot_presentation_mutex);
    states->reserve(g_replicated_loot_presentations.size());
    for (const auto& binding : g_replicated_loot_presentations) {
        states->push_back(ToPublicReplicatedLootPresentationState(binding));
    }
}

bool QueueAcceptedReplicatedGoldPickupFeedbackInternal(
    std::uint32_t run_nonce,
    std::uint64_t network_drop_id,
    std::uint32_t request_sequence,
    std::int32_t amount,
    std::int32_t resulting_gold,
    std::uint64_t accepted_ms,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!multiplayer::IsLocalTransportClient() ||
        run_nonce == 0 ||
        network_drop_id == 0 ||
        request_sequence == 0 ||
        amount <= 0 ||
        resulting_gold < amount) {
        if (error_message != nullptr) {
            *error_message = "Accepted gold feedback payload is invalid.";
        }
        return false;
    }

    std::lock_guard<std::mutex> lock(g_replicated_loot_presentation_mutex);
    auto feedback_it =
        g_replicated_gold_pickup_feedback_by_drop_id.find(network_drop_id);
    if (feedback_it != g_replicated_gold_pickup_feedback_by_drop_id.end() &&
        feedback_it->second.state.run_nonce == run_nonce &&
        feedback_it->second.state.applied) {
        return true;
    }

    uintptr_t actor_address = 0;
    if (feedback_it != g_replicated_gold_pickup_feedback_by_drop_id.end() &&
        feedback_it->second.state.run_nonce == run_nonce) {
        actor_address = feedback_it->second.state.actor_address;
    }
    if (actor_address == 0) {
        const auto* binding = FindReplicatedLootPresentationBindingLocked(network_drop_id);
        if (binding != nullptr && binding->run_nonce == run_nonce) {
            actor_address = binding->actor_address;
        }
    }
    if (actor_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Accepted gold feedback has no live presentation actor.";
        }
        return false;
    }

    auto& entry = g_replicated_gold_pickup_feedback_by_drop_id[network_drop_id];
    entry = ReplicatedGoldPickupFeedbackEntry{};
    entry.state.valid = true;
    entry.state.accepted = true;
    entry.state.network_drop_id = network_drop_id;
    entry.state.run_nonce = run_nonce;
    entry.state.actor_address = actor_address;
    entry.state.request_sequence = request_sequence;
    entry.state.amount = amount;
    entry.state.resulting_gold = resulting_gold;
    entry.state.accepted_ms = accepted_ms;
    entry.hold_until_ms = accepted_ms + kReplicatedGoldPickupFeedbackHoldMs;
    g_last_replicated_gold_pickup_feedback = entry.state;
    return true;
}

void CancelReplicatedGoldPickupFeedbackInternal(std::uint64_t network_drop_id) {
    if (network_drop_id == 0) {
        return;
    }
    std::lock_guard<std::mutex> lock(g_replicated_loot_presentation_mutex);
    const auto feedback_it =
        g_replicated_gold_pickup_feedback_by_drop_id.find(network_drop_id);
    if (feedback_it != g_replicated_gold_pickup_feedback_by_drop_id.end() &&
        !feedback_it->second.state.applied) {
        g_replicated_gold_pickup_feedback_by_drop_id.erase(feedback_it);
    }
}

bool TryGetLastReplicatedGoldPickupFeedbackStateInternal(
    SDModReplicatedGoldPickupFeedbackState* state) {
    if (state == nullptr) {
        return false;
    }
    *state = SDModReplicatedGoldPickupFeedbackState{};
    std::lock_guard<std::mutex> lock(g_replicated_loot_presentation_mutex);
    if (!g_last_replicated_gold_pickup_feedback.valid) {
        return false;
    }
    *state = g_last_replicated_gold_pickup_feedback;
    return true;
}
