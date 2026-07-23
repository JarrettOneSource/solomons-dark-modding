SDModReplicatedGoldPickupFeedbackState ToReplicatedGoldPickupFeedbackState(
    const SDModReplicatedLootPickupFeedbackState& state) {
    SDModReplicatedGoldPickupFeedbackState gold;
    gold.valid = state.valid && state.drop_kind == multiplayer::LootDropKind::Gold;
    gold.accepted = state.accepted;
    gold.applied = state.applied;
    gold.network_drop_id = state.network_drop_id;
    gold.run_nonce = state.run_nonce;
    gold.actor_address = state.actor_address;
    gold.request_sequence = state.request_sequence;
    gold.amount = state.amount;
    gold.resulting_gold = state.resulting_gold;
    gold.apply_count = state.apply_count;
    gold.accepted_ms = state.accepted_ms;
    gold.applied_ms = state.applied_ms;
    return gold;
}

void ClearReplicatedGoldPickupFeedbackStateLocked() {
    ClearReplicatedLootPickupFeedbackStateLocked();
}

void MarkReplicatedGoldPickupAwaitingAuthorityInternal(
    std::uint32_t run_nonce,
    std::uint64_t network_drop_id,
    uintptr_t actor_address,
    std::uint32_t request_sequence,
    std::uint64_t now_ms) {
    MarkReplicatedLootPickupAwaitingAuthorityInternal(
        run_nonce,
        network_drop_id,
        actor_address,
        request_sequence,
        multiplayer::LootDropKind::Gold,
        now_ms);
}

bool ShouldHoldReplicatedGoldPickupForFeedbackLocked(
    const ReplicatedLootPresentationBinding& binding,
    std::uint64_t now_ms) {
    return binding.drop_kind == multiplayer::LootDropKind::Gold &&
           ShouldHoldReplicatedLootPickupForFeedbackLocked(binding, now_ms);
}

bool TryBeginAcceptedReplicatedGoldPickupFeedbackForActorInternal(
    uintptr_t actor_address,
    SDModReplicatedGoldPickupFeedbackState* state) {
    if (state == nullptr) {
        return false;
    }
    SDModReplicatedLootPickupFeedbackState feedback;
    if (!TryBeginAcceptedReplicatedLootPickupFeedbackForActorInternal(
            actor_address,
            multiplayer::LootDropKind::Gold,
            &feedback)) {
        *state = {};
        return false;
    }
    *state = ToReplicatedGoldPickupFeedbackState(feedback);
    return true;
}

void AbortReplicatedGoldPickupFeedbackInternal(
    std::uint64_t network_drop_id,
    uintptr_t actor_address) {
    AbortReplicatedLootPickupFeedbackInternal(network_drop_id, actor_address);
}

void CompleteReplicatedGoldPickupFeedbackInternal(
    std::uint64_t network_drop_id,
    uintptr_t actor_address,
    std::uint64_t applied_ms) {
    CompleteReplicatedLootPickupFeedbackInternal(
        network_drop_id,
        actor_address,
        true,
        true,
        applied_ms);
}
