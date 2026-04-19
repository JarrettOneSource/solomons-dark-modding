void* CallSpawnEnemyInternal(SpawnEnemyCallContext* context, DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (context == nullptr ||
        context->arena_address == 0 ||
        context->config_ctor == nullptr ||
        context->config_dtor == nullptr ||
        context->build_config == nullptr ||
        context->spawn_enemy == nullptr ||
        context->modifiers == nullptr ||
        context->config_wrapper == nullptr ||
        context->config_buffer == nullptr) {
        return nullptr;
    }

    __try {
        context->config_ctor(context->config_wrapper);
        context->build_config(
            reinterpret_cast<void*>(context->arena_address),
            context->type_id,
            kSpawnEnemyVariantDefault,
            context->config_buffer,
            context->modifiers);
        context->enemy = context->spawn_enemy(
            reinterpret_cast<void*>(context->arena_address),
            nullptr,
            context->config_buffer,
            kSpawnEnemyModeDefault,
            kSpawnEnemyParam5Default,
            kSpawnEnemyParam6Default,
            kSpawnEnemyAllowOverrideDefault);
        context->config_dtor(context->config_wrapper);
        return context->enemy;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return nullptr;
    }
}

bool QueueEnemySpawnRequest(const PendingEnemySpawnRequest& request, std::string* error_message) {
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
    if (g_gameplay_keyboard_injection.pending_enemy_spawn_requests.size() >= kQueuedGameplayWorldActionLimit) {
        if (error_message != nullptr) {
            *error_message = "The enemy spawn queue is full.";
        }
        return false;
    }

    g_gameplay_keyboard_injection.pending_enemy_spawn_requests.push_back(request);
    return true;
}

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

