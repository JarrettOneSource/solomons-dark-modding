bool InitializeBotRuntime() {
    std::scoped_lock lock(g_bot_runtime_mutex);
    if (g_bot_runtime_initialized) {
        return true;
    }

    g_next_bot_id = kFirstLuaControlledParticipantId;
    ResetPendingState();
    g_bot_runtime_initialized = true;
    Log("Bot runtime initialized.");
    return true;
}

void ShutdownBotRuntime() {
    std::scoped_lock lock(g_bot_runtime_mutex);
    if (!g_bot_runtime_initialized) {
        return;
    }

    DestroyAllBotsLocked();
    g_bot_runtime_initialized = false;
    Log("Bot runtime shut down.");
}

bool IsBotRuntimeInitialized() {
    std::scoped_lock lock(g_bot_runtime_mutex);
    return g_bot_runtime_initialized;
}

bool CreateBot(const BotCreateRequest& request, std::uint64_t* out_bot_id) {
    if (out_bot_id != nullptr) {
        *out_bot_id = 0;
    }

    std::scoped_lock lock(g_bot_runtime_mutex);
    if (!g_bot_runtime_initialized || !IsValidCreateRequest(request)) {
        return false;
    }

    const auto bot_id = g_next_bot_id++;
    const bool sync_has_transform = request.has_transform;
    const bool sync_has_heading = request.has_heading;
    const float sync_position_x = request.position_x;
    const float sync_position_y = request.position_y;
    const float sync_heading = request.heading;
    const auto sync_scene_intent =
        request.has_scene_intent ? request.scene_intent : ResolveDefaultBotSceneIntentFromCurrentScene();
    UpdateRuntimeState([&](RuntimeState& state) {
        auto* participant = UpsertRemoteParticipant(
            state,
            bot_id,
            ParticipantControllerKind::LuaBrain);
        if (participant == nullptr) {
            return;
        }

        participant->name = request.display_name.empty() ? DefaultBotName(bot_id) : request.display_name;
        participant->ready = request.ready;
        participant->transport_connected = true;
        participant->transport_using_relay = false;
        ApplyCharacterProfile(participant, request.character_profile);
        ApplySceneIntent(participant, sync_scene_intent);
        if (request.has_transform) {
            ApplyTransform(
                participant,
                request.position_x,
                request.position_y,
                request.has_heading,
                request.heading);
        }
    });

    if (out_bot_id != nullptr) {
        *out_bot_id = bot_id;
    }

    SchedulePendingMovementIntentLocked(
        bot_id,
        BotControllerState::Idle,
        false,
        0.0f,
        0.0f,
        request.has_heading,
        sync_heading);

    std::string sync_error_message;
        if (!TryDispatchEntitySync(
                bot_id,
                request.character_profile,
                sync_scene_intent,
                sync_has_transform,
                sync_has_heading,
                sync_position_x,
                sync_position_y,
                sync_heading,
                &sync_error_message)) {
            SchedulePendingEntitySyncLocked(
                bot_id,
                request.character_profile,
                sync_scene_intent,
                sync_has_transform,
                sync_has_heading,
                sync_position_x,
                sync_position_y,
                sync_heading,
                GetTickCount64());
        Log(
            "[bots] gameplay sync request deferred during create. bot_id=" + std::to_string(bot_id) +
            " error=" + sync_error_message);
    }

    Log("[bots] created lua bot id=" + std::to_string(bot_id));
    return true;
}

bool DestroyBot(std::uint64_t bot_id) {
    std::scoped_lock lock(g_bot_runtime_mutex);
    if (!g_bot_runtime_initialized || bot_id == 0) {
        return false;
    }

    bool removed = false;
    UpdateRuntimeState([&](RuntimeState& state) {
        const auto previous_size = state.participants.size();
        state.participants.erase(
            std::remove_if(state.participants.begin(), state.participants.end(), [&](const ParticipantInfo& participant) {
                return participant.participant_id == bot_id && IsLuaControlledParticipant(participant);
            }),
            state.participants.end());
        removed = state.participants.size() != previous_size;
    });

    if (removed) {
        RemovePendingCast(bot_id);
        RemovePendingEntitySync(bot_id);
        RemovePendingMovementIntent(bot_id);
        RemovePendingSkillChoice(bot_id);
        std::string destroy_error_message;
        if (!TryDispatchDestroy(bot_id, &destroy_error_message)) {
            SchedulePendingDestroyLocked(bot_id);
        }
        Log("[bots] destroyed lua bot id=" + std::to_string(bot_id));
    }

    return removed;
}

void DestroyAllBots() {
    std::scoped_lock lock(g_bot_runtime_mutex);
    if (!g_bot_runtime_initialized) {
        ResetPendingState();
        return;
    }

    RuntimeState runtime = SnapshotRuntimeState();
    for (const auto& participant : runtime.participants) {
        if (IsLuaControlledParticipant(participant)) {
            SchedulePendingDestroyLocked(participant.participant_id);
        }
    }
    UpdateRuntimeState([](RuntimeState& state) {
        state.participants.erase(
            std::remove_if(state.participants.begin(), state.participants.end(), [](const ParticipantInfo& participant) {
                return IsLuaControlledParticipant(participant);
            }),
            state.participants.end());
    });
    g_pending_casts.clear();
    g_pending_entity_syncs.clear();
    g_bot_movement_intents.clear();
    g_pending_skill_choices.clear();
    g_next_cast_sequence = 1;
    g_next_entity_sync_generation = 1;
    g_next_movement_intent_revision = 1;
    g_next_destroy_generation = 1;
    g_next_skill_choice_generation = 1;
}
