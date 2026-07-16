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
