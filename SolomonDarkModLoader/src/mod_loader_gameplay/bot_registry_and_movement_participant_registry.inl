ParticipantEntityBinding* FindParticipantEntity(std::uint64_t participant_id) {
    const auto it = std::find_if(
        g_participant_entities.begin(),
        g_participant_entities.end(),
        [&](const ParticipantEntityBinding& binding) {
            return binding.bot_id == participant_id;
        });
    return it == g_participant_entities.end() ? nullptr : &(*it);
}

ParticipantEntityBinding* FindParticipantEntityForActor(uintptr_t actor_address) {
    if (actor_address == 0) {
        return nullptr;
    }

    const auto it = std::find_if(
        g_participant_entities.begin(),
        g_participant_entities.end(),
        [&](const ParticipantEntityBinding& binding) {
            return binding.actor_address == actor_address;
        });
    return it == g_participant_entities.end() ? nullptr : &(*it);
}

ParticipantEntityBinding* EnsureParticipantEntity(std::uint64_t participant_id) {
    auto* binding = FindParticipantEntity(participant_id);
    if (binding != nullptr) {
        return binding;
    }

    g_participant_entities.push_back(ParticipantEntityBinding{});
    g_participant_entities.back().bot_id = participant_id;
    return &g_participant_entities.back();
}

ParticipantEntityBinding* FindParticipantEntityForGameplaySlot(int gameplay_slot) {
    const auto it = std::find_if(
        g_participant_entities.begin(),
        g_participant_entities.end(),
        [&](const ParticipantEntityBinding& binding) {
            return binding.gameplay_slot == gameplay_slot;
        });
    return it == g_participant_entities.end() ? nullptr : &(*it);
}

PendingParticipantEntitySyncRequest* FindPendingParticipantSyncRequest(std::uint64_t participant_id) {
    const auto it = std::find_if(
        g_gameplay_keyboard_injection.pending_participant_sync_requests.begin(),
        g_gameplay_keyboard_injection.pending_participant_sync_requests.end(),
        [&](const PendingParticipantEntitySyncRequest& request) {
            return request.bot_id == participant_id;
        });
    return it == g_gameplay_keyboard_injection.pending_participant_sync_requests.end() ? nullptr : &(*it);
}

void UpsertPendingParticipantSyncRequest(const PendingParticipantEntitySyncRequest& request) {
    auto* pending_request = FindPendingParticipantSyncRequest(request.bot_id);
    if (pending_request == nullptr) {
        g_gameplay_keyboard_injection.pending_participant_sync_requests.push_back(request);
        return;
    }

    *pending_request = request;
}

void RemovePendingParticipantSyncRequest(std::uint64_t participant_id) {
    g_gameplay_keyboard_injection.pending_participant_sync_requests.erase(
        std::remove_if(
            g_gameplay_keyboard_injection.pending_participant_sync_requests.begin(),
            g_gameplay_keyboard_injection.pending_participant_sync_requests.end(),
            [&](const PendingParticipantEntitySyncRequest& request) {
                return request.bot_id == participant_id;
            }),
        g_gameplay_keyboard_injection.pending_participant_sync_requests.end());
}

void RemovePendingParticipantDestroyRequest(std::uint64_t participant_id) {
    g_gameplay_keyboard_injection.pending_participant_destroy_requests.erase(
        std::remove(
            g_gameplay_keyboard_injection.pending_participant_destroy_requests.begin(),
            g_gameplay_keyboard_injection.pending_participant_destroy_requests.end(),
            participant_id),
        g_gameplay_keyboard_injection.pending_participant_destroy_requests.end());
}

void UpsertPendingParticipantDestroyRequest(std::uint64_t participant_id) {
    if (participant_id == 0) {
        return;
    }

    const auto it = std::find(
        g_gameplay_keyboard_injection.pending_participant_destroy_requests.begin(),
        g_gameplay_keyboard_injection.pending_participant_destroy_requests.end(),
        participant_id);
    if (it == g_gameplay_keyboard_injection.pending_participant_destroy_requests.end()) {
        g_gameplay_keyboard_injection.pending_participant_destroy_requests.push_back(participant_id);
    }
}

