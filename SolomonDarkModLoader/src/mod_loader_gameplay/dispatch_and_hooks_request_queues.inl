bool QueueRewardSpawnRequest(const PendingRewardSpawnRequest& request, std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!g_gameplay_keyboard_injection.initialized) {
        if (error_message != nullptr) {
            *error_message = "Gameplay action pump is not initialized.";
        }
        return false;
    }

    std::lock_guard<std::mutex> lock(g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
    if (g_gameplay_keyboard_injection.pending_reward_spawn_requests.size() >= kQueuedGameplayWorldActionLimit) {
        if (error_message != nullptr) {
            *error_message = "The reward spawn queue is full.";
        }
        return false;
    }

    g_gameplay_keyboard_injection.pending_reward_spawn_requests.push_back(request);
    return true;
}

bool QueueParticipantSyncRequest(const PendingParticipantEntitySyncRequest& request, std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!g_gameplay_keyboard_injection.initialized) {
        if (error_message != nullptr) {
            *error_message = "Gameplay action pump is not initialized.";
        }
        return false;
    }

    auto immediate_request = request;
    immediate_request.next_attempt_ms = static_cast<std::uint64_t>(GetTickCount64());

    std::lock_guard<std::mutex> lock(g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
    if (FindPendingParticipantSyncRequest(immediate_request.bot_id) != nullptr) {
        UpsertPendingParticipantSyncRequest(immediate_request);
        Log(
            "[bots] queued sync update bot_id=" + std::to_string(immediate_request.bot_id) +
            " element_id=" + std::to_string(immediate_request.character_profile.element_id) +
            " has_transform=" + std::to_string(immediate_request.has_transform ? 1 : 0) +
            " x=" + std::to_string(immediate_request.x) +
            " y=" + std::to_string(immediate_request.y) +
            " heading=" + std::to_string(immediate_request.heading));
        return true;
    }

    if (g_gameplay_keyboard_injection.pending_participant_sync_requests.size() >= kQueuedGameplayWorldActionLimit) {
        if (error_message != nullptr) {
            *error_message = "The wizard bot sync queue is full.";
        }
        return false;
    }

    g_gameplay_keyboard_injection.pending_participant_sync_requests.push_back(immediate_request);
    Log(
        "[bots] queued sync bot_id=" + std::to_string(immediate_request.bot_id) +
        " element_id=" + std::to_string(immediate_request.character_profile.element_id) +
        " has_transform=" + std::to_string(immediate_request.has_transform ? 1 : 0) +
        " x=" + std::to_string(immediate_request.x) +
        " y=" + std::to_string(immediate_request.y) +
        " heading=" + std::to_string(immediate_request.heading));
    return true;
}

bool QueueParticipantDestroyRequest(std::uint64_t bot_id, std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!g_gameplay_keyboard_injection.initialized) {
        if (error_message != nullptr) {
            *error_message = "Gameplay action pump is not initialized.";
        }
        return false;
    }

    std::lock_guard<std::mutex> lock(g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
    RemovePendingParticipantSyncRequest(bot_id);
    UpsertPendingParticipantDestroyRequest(bot_id);
    return true;
}
