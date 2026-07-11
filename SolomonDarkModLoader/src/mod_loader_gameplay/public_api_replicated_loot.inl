bool QueueReplicatedLootSnapshot(
    const multiplayer::LootSnapshotRuntimeInfo& snapshot,
    std::string* error_message) {
    return QueueReplicatedLootSnapshotInternal(snapshot, error_message);
}

bool IsReplicatedLootPresentationActor(uintptr_t actor_address) {
    return IsReplicatedLootPresentationActorInternal(actor_address);
}

bool TryGetReplicatedLootPresentationState(
    std::uint64_t network_drop_id,
    SDModReplicatedLootPresentationState* state) {
    return TryGetReplicatedLootPresentationStateInternal(network_drop_id, state);
}

void GetReplicatedLootPresentationStates(std::vector<SDModReplicatedLootPresentationState>* states) {
    GetReplicatedLootPresentationStatesInternal(states);
}

void SuppressClientLocalLootActors(const char* reason) {
    QueueClientLocalLootSuppressionInternal(reason, kClientLocalLootSuppressionSettleDelayMs);
}

bool HasReplicatedRunEnemyDeathPresentation(std::uint64_t network_actor_id) {
    return HasReplicatedRunEnemyDeathPresentationStarted(network_actor_id);
}

void MarkReplicatedRunEnemyDeathPresented(std::uint64_t network_actor_id) {
    MarkReplicatedRunEnemyDeathPresentationStarted(
        network_actor_id,
        static_cast<std::uint64_t>(GetTickCount64()));
}

void ClearReplicatedRunEnemyDeathPresentation(std::uint64_t network_actor_id) {
    ClearReplicatedRunEnemyDeathPresentationState(network_actor_id);
}
