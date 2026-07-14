bool QueueReplicatedLootSnapshot(
    const multiplayer::LootSnapshotRuntimeInfo& snapshot,
    std::string* error_message) {
    return QueueReplicatedLootSnapshotInternal(snapshot, error_message);
}

bool QueueNativePotionInventoryCredit(
    std::uint64_t authority_participant_id,
    std::uint32_t run_nonce,
    std::uint64_t network_drop_id,
    std::uint32_t item_type_id,
    std::int32_t item_slot,
    std::int32_t stack_count,
    std::uint32_t inventory_revision,
    std::string* error_message) {
    return QueueNativePotionInventoryCreditInternal(
        authority_participant_id,
        run_nonce,
        network_drop_id,
        item_type_id,
        item_slot,
        stack_count,
        inventory_revision,
        error_message);
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
