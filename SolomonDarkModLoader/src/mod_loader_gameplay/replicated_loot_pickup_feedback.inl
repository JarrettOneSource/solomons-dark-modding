constexpr std::uint64_t kReplicatedLootPickupFeedbackHoldMs = 2000;

struct ReplicatedLootPickupFeedbackEntry {
    SDModReplicatedLootPickupFeedbackState state;
    std::uint64_t hold_until_ms = 0;
    bool applying = false;
};

std::unordered_map<std::uint64_t, ReplicatedLootPickupFeedbackEntry>
    g_replicated_loot_pickup_feedback_by_drop_id;
std::unordered_map<int, SDModReplicatedLootPickupFeedbackState>
    g_last_replicated_loot_pickup_feedback_by_kind;
SDModReplicatedLootPickupFeedbackState g_last_replicated_loot_pickup_feedback;
thread_local std::uint32_t g_accepted_replicated_loot_feedback_depth = 0;

void ClearReplicatedLootPickupFeedbackStateLocked() {
    g_replicated_loot_pickup_feedback_by_drop_id.clear();
    g_last_replicated_loot_pickup_feedback_by_kind.clear();
    g_last_replicated_loot_pickup_feedback = {};
}

void PublishReplicatedLootPickupFeedbackLocked(
    const SDModReplicatedLootPickupFeedbackState& state) {
    g_last_replicated_loot_pickup_feedback = state;
    g_last_replicated_loot_pickup_feedback_by_kind[
        static_cast<int>(state.drop_kind)] = state;
}

void MarkReplicatedLootPickupAwaitingAuthorityInternal(
    std::uint32_t run_nonce,
    std::uint64_t network_drop_id,
    uintptr_t actor_address,
    std::uint32_t request_sequence,
    multiplayer::LootDropKind drop_kind,
    std::uint64_t now_ms) {
    if (run_nonce == 0 || network_drop_id == 0 || actor_address == 0 ||
        request_sequence == 0 ||
        (drop_kind != multiplayer::LootDropKind::Gold &&
         drop_kind != multiplayer::LootDropKind::Orb &&
         drop_kind != multiplayer::LootDropKind::Powerup)) {
        return;
    }

    std::lock_guard<std::mutex> lock(g_replicated_loot_presentation_mutex);
    auto& entry = g_replicated_loot_pickup_feedback_by_drop_id[network_drop_id];
    if (entry.state.applied) {
        return;
    }
    entry.state.valid = true;
    entry.state.drop_kind = drop_kind;
    entry.state.network_drop_id = network_drop_id;
    entry.state.run_nonce = run_nonce;
    entry.state.actor_address = actor_address;
    entry.state.request_sequence = request_sequence;
    entry.hold_until_ms = now_ms + kReplicatedLootPickupFeedbackHoldMs;
}

bool ShouldHoldReplicatedLootPickupForFeedbackLocked(
    const ReplicatedLootPresentationBinding& binding,
    std::uint64_t now_ms) {
    const auto feedback_it =
        g_replicated_loot_pickup_feedback_by_drop_id.find(binding.network_drop_id);
    if (feedback_it == g_replicated_loot_pickup_feedback_by_drop_id.end()) {
        return false;
    }
    const auto& feedback = feedback_it->second;
    return feedback.state.valid &&
           !feedback.state.applied &&
           feedback.state.run_nonce == binding.run_nonce &&
           feedback.state.drop_kind == binding.drop_kind &&
           feedback.state.actor_address == binding.actor_address &&
           now_ms <= feedback.hold_until_ms;
}

bool TryBeginAcceptedReplicatedLootPickupFeedbackForActorInternal(
    uintptr_t actor_address,
    multiplayer::LootDropKind expected_kind,
    SDModReplicatedLootPickupFeedbackState* state) {
    if (state == nullptr || actor_address == 0 ||
        expected_kind == multiplayer::LootDropKind::Unknown) {
        return false;
    }
    *state = {};

    std::lock_guard<std::mutex> lock(g_replicated_loot_presentation_mutex);
    for (auto& pair : g_replicated_loot_pickup_feedback_by_drop_id) {
        auto& entry = pair.second;
        if (entry.state.valid &&
            entry.state.accepted &&
            !entry.state.applied &&
            !entry.applying &&
            entry.state.drop_kind == expected_kind &&
            entry.state.actor_address == actor_address) {
            entry.applying = true;
            *state = entry.state;
            return true;
        }
    }
    return false;
}

void AbortReplicatedLootPickupFeedbackInternal(
    std::uint64_t network_drop_id,
    uintptr_t actor_address) {
    std::lock_guard<std::mutex> lock(g_replicated_loot_presentation_mutex);
    const auto feedback_it =
        g_replicated_loot_pickup_feedback_by_drop_id.find(network_drop_id);
    if (feedback_it != g_replicated_loot_pickup_feedback_by_drop_id.end() &&
        feedback_it->second.state.actor_address == actor_address &&
        !feedback_it->second.state.applied) {
        feedback_it->second.applying = false;
    }
}

void CompleteReplicatedLootPickupFeedbackInternal(
    std::uint64_t network_drop_id,
    uintptr_t actor_address,
    bool stock_feedback_applied,
    bool notification_applied,
    std::uint64_t applied_ms) {
    std::lock_guard<std::mutex> lock(g_replicated_loot_presentation_mutex);
    const auto feedback_it =
        g_replicated_loot_pickup_feedback_by_drop_id.find(network_drop_id);
    if (feedback_it == g_replicated_loot_pickup_feedback_by_drop_id.end()) {
        return;
    }
    auto& entry = feedback_it->second;
    if (!entry.state.accepted || entry.state.applied ||
        entry.state.actor_address != actor_address) {
        return;
    }
    entry.state.applied = true;
    entry.state.stock_feedback_applied = stock_feedback_applied;
    entry.state.notification_applied = notification_applied;
    entry.state.applied_ms = applied_ms;
    ++entry.state.apply_count;
    entry.applying = false;
    PublishReplicatedLootPickupFeedbackLocked(entry.state);
}

bool QueueAcceptedReplicatedLootPickupFeedbackInternal(
    SDModReplicatedLootPickupFeedbackState state,
    std::uint64_t accepted_ms,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!multiplayer::IsLocalTransportClient() ||
        state.run_nonce == 0 || state.network_drop_id == 0 ||
        state.request_sequence == 0 ||
        (state.drop_kind != multiplayer::LootDropKind::Gold &&
         state.drop_kind != multiplayer::LootDropKind::Orb &&
         state.drop_kind != multiplayer::LootDropKind::Powerup)) {
        if (error_message != nullptr) {
            *error_message = "Accepted pickup feedback payload is invalid.";
        }
        return false;
    }

    std::lock_guard<std::mutex> lock(g_replicated_loot_presentation_mutex);
    auto feedback_it =
        g_replicated_loot_pickup_feedback_by_drop_id.find(state.network_drop_id);
    if (feedback_it != g_replicated_loot_pickup_feedback_by_drop_id.end() &&
        feedback_it->second.state.run_nonce == state.run_nonce &&
        feedback_it->second.state.drop_kind == state.drop_kind &&
        feedback_it->second.state.applied) {
        return true;
    }

    uintptr_t actor_address = 0;
    if (feedback_it != g_replicated_loot_pickup_feedback_by_drop_id.end() &&
        feedback_it->second.state.run_nonce == state.run_nonce &&
        feedback_it->second.state.drop_kind == state.drop_kind) {
        actor_address = feedback_it->second.state.actor_address;
    }
    const auto* binding = FindReplicatedLootPresentationBindingLocked(state.network_drop_id);
    if (binding != nullptr && binding->run_nonce == state.run_nonce &&
        binding->drop_kind == state.drop_kind) {
        actor_address = binding->actor_address;
        state.presentation_value = binding->value;
    }
    if (actor_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Accepted pickup feedback has no live presentation actor.";
        }
        return false;
    }

    state.valid = true;
    state.accepted = true;
    state.applied = false;
    state.actor_address = actor_address;
    state.accepted_ms = accepted_ms;
    auto& entry = g_replicated_loot_pickup_feedback_by_drop_id[state.network_drop_id];
    entry = {};
    entry.state = state;
    entry.hold_until_ms = accepted_ms + kReplicatedLootPickupFeedbackHoldMs;
    PublishReplicatedLootPickupFeedbackLocked(entry.state);
    return true;
}

void CancelReplicatedLootPickupFeedbackInternal(std::uint64_t network_drop_id) {
    if (network_drop_id == 0) {
        return;
    }
    std::lock_guard<std::mutex> lock(g_replicated_loot_presentation_mutex);
    const auto feedback_it =
        g_replicated_loot_pickup_feedback_by_drop_id.find(network_drop_id);
    if (feedback_it != g_replicated_loot_pickup_feedback_by_drop_id.end() &&
        !feedback_it->second.state.applied) {
        g_replicated_loot_pickup_feedback_by_drop_id.erase(feedback_it);
    }
}

bool TryGetLastReplicatedLootPickupFeedbackStateInternal(
    SDModReplicatedLootPickupFeedbackState* state) {
    if (state == nullptr) {
        return false;
    }
    *state = {};
    std::lock_guard<std::mutex> lock(g_replicated_loot_presentation_mutex);
    if (!g_last_replicated_loot_pickup_feedback.valid) {
        return false;
    }
    *state = g_last_replicated_loot_pickup_feedback;
    return true;
}

bool TryGetLastReplicatedLootPickupFeedbackStateForKindInternal(
    multiplayer::LootDropKind drop_kind,
    SDModReplicatedLootPickupFeedbackState* state) {
    if (state == nullptr) {
        return false;
    }
    *state = {};
    std::lock_guard<std::mutex> lock(g_replicated_loot_presentation_mutex);
    const auto it = g_last_replicated_loot_pickup_feedback_by_kind.find(
        static_cast<int>(drop_kind));
    if (it == g_last_replicated_loot_pickup_feedback_by_kind.end()) {
        return false;
    }
    *state = it->second;
    return true;
}

void PublishCompletedReplicatedInventoryPickupFeedbackInternal(
    multiplayer::LootDropKind drop_kind,
    std::uint32_t run_nonce,
    std::uint64_t network_drop_id,
    uintptr_t actor_address,
    std::uint32_t item_type_id,
    std::uint32_t item_recipe_uid,
    std::int32_t item_slot,
    std::int32_t stack_count,
    bool stock_feedback_applied,
    std::uint64_t accepted_ms,
    std::uint64_t applied_ms) {
    if ((drop_kind != multiplayer::LootDropKind::Item &&
         drop_kind != multiplayer::LootDropKind::Potion) ||
        run_nonce == 0 || network_drop_id == 0 || actor_address == 0 ||
        item_type_id == 0 || stack_count <= 0) {
        return;
    }

    SDModReplicatedLootPickupFeedbackState state;
    state.valid = true;
    state.accepted = true;
    state.applied = true;
    state.drop_kind = drop_kind;
    state.network_drop_id = network_drop_id;
    state.run_nonce = run_nonce;
    state.actor_address = actor_address;
    state.item_type_id = item_type_id;
    state.item_recipe_uid = item_recipe_uid;
    state.item_slot = item_slot;
    state.stack_count = stack_count;
    state.stock_feedback_applied = stock_feedback_applied;
    state.notification_applied = stock_feedback_applied;
    state.apply_count = 1;
    state.accepted_ms = accepted_ms;
    state.applied_ms = applied_ms;

    std::lock_guard<std::mutex> lock(g_replicated_loot_presentation_mutex);
    PublishReplicatedLootPickupFeedbackLocked(state);
}

bool CallNativePickupNotificationSafe(
    const char* text,
    NativeRgbaColor color,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (text == nullptr || text[0] == '\0') {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto string_assign_address =
        memory.ResolveGameAddressOrZero(kGameplayStringAssign);
    const auto notification_address =
        memory.ResolveGameAddressOrZero(kPickupNotification);
    const auto notification_queue_address =
        memory.ResolveGameAddressOrZero(kPickupNotificationQueueGlobal);
    auto* string_assign =
        reinterpret_cast<NativeStringAssignFn>(string_assign_address);
    auto* notify =
        reinterpret_cast<NativePickupNotificationFn>(notification_address);
    if (string_assign == nullptr || notify == nullptr ||
        notification_queue_address == 0) {
        return false;
    }

    NativeGameString native_text{};
    bool assigned = false;
    __try {
        string_assign(&native_text, const_cast<char*>(text));
        assigned = true;
        // PickupNotificationQueue::Push consumes the owned String argument;
        // the retail callers construct it directly in the outgoing stack slot.
        notify(
            reinterpret_cast<void*>(notification_queue_address),
            native_text,
            color);
        native_text = {};
        assigned = false;
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        if (assigned) {
            DWORD cleanup_exception_code = 0;
            __try {
                string_assign(&native_text, nullptr);
            } __except (CaptureSehCode(
                GetExceptionInformation(),
                &cleanup_exception_code)) {
                if (exception_code != nullptr && *exception_code == 0) {
                    *exception_code = cleanup_exception_code;
                }
            }
        }
        return false;
    }
}
