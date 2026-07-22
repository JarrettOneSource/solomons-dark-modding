constexpr std::uint64_t kReplicatedGoldPickupFeedbackHoldMs = 2000;

struct ReplicatedGoldPickupFeedbackEntry {
    SDModReplicatedGoldPickupFeedbackState state;
    std::uint64_t hold_until_ms = 0;
    bool applying = false;
};

std::unordered_map<std::uint64_t, ReplicatedGoldPickupFeedbackEntry>
    g_replicated_gold_pickup_feedback_by_drop_id;
SDModReplicatedGoldPickupFeedbackState g_last_replicated_gold_pickup_feedback;

void ClearReplicatedGoldPickupFeedbackStateLocked() {
    g_replicated_gold_pickup_feedback_by_drop_id.clear();
    g_last_replicated_gold_pickup_feedback = SDModReplicatedGoldPickupFeedbackState{};
}

void MarkReplicatedGoldPickupAwaitingAuthorityInternal(
    std::uint32_t run_nonce,
    std::uint64_t network_drop_id,
    uintptr_t actor_address,
    std::uint32_t request_sequence,
    std::uint64_t now_ms) {
    if (run_nonce == 0 || network_drop_id == 0 || actor_address == 0 || request_sequence == 0) {
        return;
    }

    std::lock_guard<std::mutex> lock(g_replicated_loot_presentation_mutex);
    auto& entry = g_replicated_gold_pickup_feedback_by_drop_id[network_drop_id];
    if (entry.state.applied) {
        return;
    }
    entry.state.valid = true;
    entry.state.network_drop_id = network_drop_id;
    entry.state.run_nonce = run_nonce;
    entry.state.actor_address = actor_address;
    entry.state.request_sequence = request_sequence;
    entry.hold_until_ms = now_ms + kReplicatedGoldPickupFeedbackHoldMs;
}

bool ShouldHoldReplicatedGoldPickupForFeedbackLocked(
    const ReplicatedLootPresentationBinding& binding,
    std::uint64_t now_ms) {
    const auto feedback_it =
        g_replicated_gold_pickup_feedback_by_drop_id.find(binding.network_drop_id);
    if (feedback_it == g_replicated_gold_pickup_feedback_by_drop_id.end()) {
        return false;
    }
    const auto& feedback = feedback_it->second;
    return feedback.state.valid &&
           !feedback.state.applied &&
           feedback.state.run_nonce == binding.run_nonce &&
           feedback.state.actor_address == binding.actor_address &&
           now_ms <= feedback.hold_until_ms;
}

bool TryBeginAcceptedReplicatedGoldPickupFeedbackForActorInternal(
    uintptr_t actor_address,
    SDModReplicatedGoldPickupFeedbackState* state) {
    if (state == nullptr || actor_address == 0) {
        return false;
    }
    *state = SDModReplicatedGoldPickupFeedbackState{};

    std::lock_guard<std::mutex> lock(g_replicated_loot_presentation_mutex);
    for (auto& pair : g_replicated_gold_pickup_feedback_by_drop_id) {
        auto& entry = pair.second;
        if (entry.state.valid &&
            entry.state.accepted &&
            !entry.state.applied &&
            !entry.applying &&
            entry.state.actor_address == actor_address) {
            entry.applying = true;
            *state = entry.state;
            return true;
        }
    }
    return false;
}

void AbortReplicatedGoldPickupFeedbackInternal(
    std::uint64_t network_drop_id,
    uintptr_t actor_address) {
    std::lock_guard<std::mutex> lock(g_replicated_loot_presentation_mutex);
    const auto feedback_it =
        g_replicated_gold_pickup_feedback_by_drop_id.find(network_drop_id);
    if (feedback_it != g_replicated_gold_pickup_feedback_by_drop_id.end() &&
        feedback_it->second.state.actor_address == actor_address &&
        !feedback_it->second.state.applied) {
        feedback_it->second.applying = false;
    }
}

void CompleteReplicatedGoldPickupFeedbackInternal(
    std::uint64_t network_drop_id,
    uintptr_t actor_address,
    std::uint64_t applied_ms) {
    std::lock_guard<std::mutex> lock(g_replicated_loot_presentation_mutex);
    const auto feedback_it =
        g_replicated_gold_pickup_feedback_by_drop_id.find(network_drop_id);
    if (feedback_it == g_replicated_gold_pickup_feedback_by_drop_id.end()) {
        return;
    }
    auto& entry = feedback_it->second;
    if (!entry.state.accepted ||
        entry.state.applied ||
        entry.state.actor_address != actor_address) {
        return;
    }
    entry.state.applied = true;
    entry.state.applied_ms = applied_ms;
    ++entry.state.apply_count;
    entry.applying = false;
    g_last_replicated_gold_pickup_feedback = entry.state;
}
