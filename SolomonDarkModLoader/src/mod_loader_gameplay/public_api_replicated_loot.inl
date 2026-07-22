bool QueueReplicatedLootSnapshot(
    const multiplayer::LootSnapshotRuntimeInfo& snapshot,
    std::string* error_message) {
    return QueueReplicatedLootSnapshotInternal(snapshot, error_message);
}

bool QueueHostLootDropDeactivation(
    std::uint32_t run_nonce,
    std::uint64_t network_drop_id,
    uintptr_t actor_address,
    multiplayer::LootDropKind drop_kind,
    std::string* error_message) {
    return QueueHostLootDropDeactivationInternal(
        run_nonce,
        network_drop_id,
        actor_address,
        drop_kind,
        error_message);
}

bool TryTakeHostLootDropDeactivationResult(
    SDModHostLootDropDeactivationResult* result) {
    return TryTakeHostLootDropDeactivationResultInternal(result);
}

void ClearHostLootDropDeactivationState() {
    ClearHostLootDropDeactivationStateInternal();
}

bool QueueNativeInventoryCredit(
    std::uint64_t authority_participant_id,
    std::uint32_t run_nonce,
    std::uint64_t network_drop_id,
    std::uint32_t item_type_id,
    std::uint32_t item_recipe_uid,
    const std::array<std::uint8_t, multiplayer::kParticipantVisualLinkColorBlockBytes>&
        item_color_state,
    bool item_color_state_valid,
    std::int32_t item_slot,
    std::int32_t stack_count,
    std::uint32_t inventory_revision,
    std::string* error_message) {
    return QueueNativeInventoryCreditInternal(
        authority_participant_id,
        run_nonce,
        network_drop_id,
        item_type_id,
        item_recipe_uid,
        item_color_state,
        item_color_state_valid,
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

bool QueueAcceptedReplicatedGoldPickupFeedback(
    std::uint32_t run_nonce,
    std::uint64_t network_drop_id,
    std::uint32_t request_sequence,
    std::int32_t amount,
    std::int32_t resulting_gold,
    std::uint64_t accepted_ms,
    std::string* error_message) {
    return QueueAcceptedReplicatedGoldPickupFeedbackInternal(
        run_nonce,
        network_drop_id,
        request_sequence,
        amount,
        resulting_gold,
        accepted_ms,
        error_message);
}

void CancelReplicatedGoldPickupFeedback(std::uint64_t network_drop_id) {
    CancelReplicatedGoldPickupFeedbackInternal(network_drop_id);
}

bool TryGetLastReplicatedGoldPickupFeedbackState(
    SDModReplicatedGoldPickupFeedbackState* state) {
    return TryGetLastReplicatedGoldPickupFeedbackStateInternal(state);
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
bool IsApplyingAcceptedReplicatedGoldPickupFeedback() {
    return g_accepted_replicated_gold_feedback_depth != 0;
}
