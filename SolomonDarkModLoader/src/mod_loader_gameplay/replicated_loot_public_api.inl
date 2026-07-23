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
    if (amount <= 0 || resulting_gold < amount) {
        if (error_message != nullptr) {
            *error_message = "Accepted gold feedback payload is invalid.";
        }
        return false;
    }

    SDModReplicatedLootPickupFeedbackState state;
    state.drop_kind = multiplayer::LootDropKind::Gold;
    state.network_drop_id = network_drop_id;
    state.run_nonce = run_nonce;
    state.request_sequence = request_sequence;
    state.amount = amount;
    state.resulting_gold = resulting_gold;
    return QueueAcceptedReplicatedLootPickupFeedbackInternal(
        state,
        accepted_ms,
        error_message);
}

bool QueueAcceptedReplicatedOrbPickupFeedbackInternal(
    std::uint32_t run_nonce,
    std::uint64_t network_drop_id,
    std::uint32_t request_sequence,
    std::int32_t resource_kind,
    float resource_delta,
    float resulting_life_current,
    float resulting_life_max,
    float resulting_mana_current,
    float resulting_mana_max,
    std::uint64_t accepted_ms,
    std::string* error_message) {
    if ((resource_kind != 0 && resource_kind != 1) ||
        !std::isfinite(resource_delta) || resource_delta <= 0.0f ||
        !std::isfinite(resulting_life_current) ||
        !std::isfinite(resulting_life_max) || resulting_life_max <= 0.0f ||
        !std::isfinite(resulting_mana_current) ||
        !std::isfinite(resulting_mana_max) || resulting_mana_max <= 0.0f) {
        if (error_message != nullptr) {
            *error_message = "Accepted orb feedback payload is invalid.";
        }
        return false;
    }

    SDModReplicatedLootPickupFeedbackState state;
    state.drop_kind = multiplayer::LootDropKind::Orb;
    state.network_drop_id = network_drop_id;
    state.run_nonce = run_nonce;
    state.request_sequence = request_sequence;
    state.resource_kind = resource_kind;
    state.resource_delta = resource_delta;
    state.resulting_life_current = resulting_life_current;
    state.resulting_life_max = resulting_life_max;
    state.resulting_mana_current = resulting_mana_current;
    state.resulting_mana_max = resulting_mana_max;
    return QueueAcceptedReplicatedLootPickupFeedbackInternal(
        state,
        accepted_ms,
        error_message);
}

bool QueueAcceptedReplicatedPowerupPickupFeedbackInternal(
    std::uint32_t run_nonce,
    std::uint64_t network_drop_id,
    std::uint32_t request_sequence,
    std::int32_t powerup_kind,
    std::int32_t powerup_skill_entry_index,
    std::uint16_t powerup_skill_resulting_active,
    std::int32_t damage_x4_remaining_ticks,
    std::uint64_t accepted_ms,
    std::string* error_message) {
    if (powerup_kind < static_cast<std::int32_t>(
            multiplayer::PowerupRewardKind::BonusSkillPoint) ||
        powerup_kind > static_cast<std::int32_t>(
            multiplayer::PowerupRewardKind::DamageX4)) {
        if (error_message != nullptr) {
            *error_message = "Accepted powerup feedback payload is invalid.";
        }
        return false;
    }

    SDModReplicatedLootPickupFeedbackState state;
    state.drop_kind = multiplayer::LootDropKind::Powerup;
    state.network_drop_id = network_drop_id;
    state.run_nonce = run_nonce;
    state.request_sequence = request_sequence;
    state.powerup_kind = powerup_kind;
    state.powerup_skill_entry_index = powerup_skill_entry_index;
    state.powerup_skill_resulting_active = powerup_skill_resulting_active;
    state.damage_x4_remaining_ticks = damage_x4_remaining_ticks;
    return QueueAcceptedReplicatedLootPickupFeedbackInternal(
        state,
        accepted_ms,
        error_message);
}

void CancelReplicatedGoldPickupFeedbackInternal(std::uint64_t network_drop_id) {
    CancelReplicatedLootPickupFeedbackInternal(network_drop_id);
}

bool TryGetLastReplicatedGoldPickupFeedbackStateInternal(
    SDModReplicatedGoldPickupFeedbackState* state) {
    if (state == nullptr) {
        return false;
    }
    SDModReplicatedLootPickupFeedbackState feedback;
    if (!TryGetLastReplicatedLootPickupFeedbackStateForKindInternal(
            multiplayer::LootDropKind::Gold,
            &feedback)) {
        *state = {};
        return false;
    }
    *state = ToReplicatedGoldPickupFeedbackState(feedback);
    return true;
}
