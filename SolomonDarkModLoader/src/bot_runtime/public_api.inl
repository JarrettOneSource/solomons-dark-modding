bool InitializeBotRuntime() {
    std::scoped_lock lock(g_bot_runtime_mutex);
    if (g_bot_runtime_initialized) {
        return true;
    }

    g_next_bot_id = kFirstLuaBotParticipantId;
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
    UpdateRuntimeState([&](RuntimeState& state) {
        auto* participant = UpsertLuaBotParticipant(state, bot_id);
        if (participant == nullptr) {
            return;
        }

        participant->name = request.display_name.empty() ? DefaultBotName(bot_id) : request.display_name;
        participant->ready = request.ready;
        participant->transport_connected = true;
        participant->transport_using_relay = false;
        ApplyCharacterProfile(participant, request.character_profile);
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
                sync_has_transform,
                sync_has_heading,
                sync_position_x,
                sync_position_y,
                sync_heading,
                &sync_error_message)) {
            SchedulePendingEntitySyncLocked(
                bot_id,
                request.character_profile,
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
                return participant.participant_id == bot_id && IsLuaBotParticipant(participant);
            }),
            state.participants.end());
        removed = state.participants.size() != previous_size;
    });

    if (removed) {
        RemovePendingCast(bot_id);
        RemovePendingEntitySync(bot_id);
        RemovePendingMovementIntent(bot_id);
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
        if (IsLuaBotParticipant(participant)) {
            SchedulePendingDestroyLocked(participant.participant_id);
        }
    }
    UpdateRuntimeState([](RuntimeState& state) {
        state.participants.erase(
            std::remove_if(state.participants.begin(), state.participants.end(), [](const ParticipantInfo& participant) {
                return IsLuaBotParticipant(participant);
            }),
            state.participants.end());
    });
    g_pending_casts.clear();
    g_pending_entity_syncs.clear();
    g_bot_movement_intents.clear();
    g_next_cast_sequence = 1;
    g_next_entity_sync_generation = 1;
    g_next_movement_intent_revision = 1;
    g_next_destroy_generation = 1;
}

bool UpdateBot(const BotUpdateRequest& request) {
    std::scoped_lock lock(g_bot_runtime_mutex);
    if (!g_bot_runtime_initialized || !IsValidUpdateRequest(request)) {
        return false;
    }

    bool updated = false;
    MultiplayerCharacterProfile sync_character_profile = DefaultCharacterProfile();
    bool sync_has_transform = false;
    bool sync_has_heading = false;
    float sync_position_x = 0.0f;
    float sync_position_y = 0.0f;
    float sync_heading = 0.0f;
    UpdateRuntimeState([&](RuntimeState& state) {
        auto* participant = FindBot(state, request.bot_id);
        if (participant == nullptr) {
            return;
        }

        if (request.has_display_name) {
            participant->name = request.display_name.empty() ? DefaultBotName(request.bot_id) : request.display_name;
        }
        if (request.has_character_profile) {
            ApplyCharacterProfile(participant, request.character_profile);
        }
        if (request.has_ready) {
            participant->ready = request.ready;
        }
        if (request.has_transform) {
            ApplyTransform(
                participant,
                request.position_x,
                request.position_y,
                request.has_heading,
                request.heading);
        }
        sync_character_profile = participant->character_profile;
        sync_has_transform = participant->runtime.transform_valid;
        sync_has_heading = request.has_heading;
        sync_position_x = participant->runtime.position_x;
        sync_position_y = participant->runtime.position_y;
        sync_heading = participant->runtime.heading;
        updated = true;
    });

    if (updated && (request.has_character_profile || request.has_transform)) {
        std::string sync_error_message;
        if (!TryDispatchEntitySync(
                request.bot_id,
                sync_character_profile,
                sync_has_transform,
                sync_has_heading,
                sync_position_x,
                sync_position_y,
                sync_heading,
                &sync_error_message)) {
            SchedulePendingEntitySyncLocked(
                request.bot_id,
                sync_character_profile,
                sync_has_transform,
                sync_has_heading,
                sync_position_x,
                sync_position_y,
                sync_heading,
                GetTickCount64());
            Log(
                "[bots] gameplay sync request deferred during update. bot_id=" +
                std::to_string(request.bot_id) + " error=" + sync_error_message);
        }
    }

    if (updated && request.has_transform && request.has_heading) {
        if (auto* controller = FindPendingMovementIntent(request.bot_id);
            controller != nullptr && controller->state == BotControllerState::Idle) {
            controller->desired_heading_valid = true;
            controller->desired_heading = sync_heading;
        }
    }

    return updated;
}

bool MoveBotTo(const BotMoveToRequest& request) {
    std::scoped_lock lock(g_bot_runtime_mutex);
    if (!g_bot_runtime_initialized || !IsValidMoveRequest(request)) {
        return false;
    }

    const RuntimeState runtime = SnapshotRuntimeState();
    const auto* participant = FindBot(runtime, request.bot_id);
    if (participant == nullptr) {
        return false;
    }

    const auto* previous_intent = FindPendingMovementIntent(request.bot_id);
    const bool have_transform = participant->runtime.transform_valid;
    const float current_x = participant->runtime.position_x;
    const float current_y = participant->runtime.position_y;
    const float current_heading =
        have_transform ? participant->runtime.heading
                       : (previous_intent != nullptr && previous_intent->desired_heading_valid
                              ? previous_intent->desired_heading
                              : 0.0f);
    SchedulePendingMovementIntentLocked(
        request.bot_id,
        BotControllerState::Moving,
        true,
        request.target_x,
        request.target_y,
        previous_intent != nullptr && previous_intent->desired_heading_valid,
        previous_intent != nullptr ? previous_intent->desired_heading : 0.0f);
    if (auto* current_intent = FindPendingMovementIntent(request.bot_id); current_intent != nullptr) {
        DeriveControllerMotionFromTransform(current_intent, have_transform, current_x, current_y, current_heading);
    }
    return true;
}

bool StopBot(std::uint64_t bot_id) {
    std::scoped_lock lock(g_bot_runtime_mutex);
    if (!g_bot_runtime_initialized || bot_id == 0) {
        return false;
    }

    bool bot_exists = false;
    UpdateRuntimeState([&](RuntimeState& state) {
        bot_exists = FindBot(state, bot_id) != nullptr;
    });
    if (!bot_exists) {
        return false;
    }

    const auto* previous_intent = FindPendingMovementIntent(bot_id);
    const auto desired_heading_valid = previous_intent != nullptr && previous_intent->desired_heading_valid;
    const auto desired_heading = previous_intent != nullptr ? previous_intent->desired_heading : 0.0f;
    SchedulePendingMovementIntentLocked(
        bot_id,
        BotControllerState::Idle,
        false,
        0.0f,
        0.0f,
        desired_heading_valid,
        desired_heading);
    if (previous_intent == nullptr || previous_intent->state != BotControllerState::Idle || previous_intent->has_target) {
        Log("[bots] queued stop id=" + std::to_string(bot_id) + " state=idle");
    }

    return true;
}

bool FaceBot(std::uint64_t bot_id, float heading) {
    std::scoped_lock lock(g_bot_runtime_mutex);
    if (!g_bot_runtime_initialized || bot_id == 0 || !std::isfinite(heading)) {
        return false;
    }

    bool bot_exists = false;
    UpdateRuntimeState([&](RuntimeState& state) {
        bot_exists = FindBot(state, bot_id) != nullptr;
    });
    if (!bot_exists) {
        return false;
    }

    const auto* previous_intent = FindPendingMovementIntent(bot_id);
    const bool changed =
        previous_intent == nullptr ||
        previous_intent->state != BotControllerState::Idle ||
        !previous_intent->desired_heading_valid ||
        std::fabs(previous_intent->desired_heading - heading) > 0.01f;
    SchedulePendingMovementIntentLocked(
        bot_id,
        BotControllerState::Idle,
        false,
        0.0f,
        0.0f,
        true,
        heading);
    if (changed) {
        Log(
            "[bots] queued face id=" + std::to_string(bot_id) +
            " heading=" + std::to_string(heading));
    }

    return true;
}

bool ReadBotMovementIntent(std::uint64_t bot_id, BotMovementIntentSnapshot* snapshot) {
    if (snapshot == nullptr) {
        return false;
    }

    *snapshot = BotMovementIntentSnapshot{};

    std::scoped_lock lock(g_bot_runtime_mutex);
    if (!g_bot_runtime_initialized || bot_id == 0) {
        return false;
    }

    RuntimeState runtime = SnapshotRuntimeState();
    if (FindBot(runtime, bot_id) == nullptr) {
        return false;
    }

    snapshot->available = true;
    if (const auto* pending_intent = FindPendingMovementIntent(bot_id); pending_intent != nullptr) {
        snapshot->state = pending_intent->state;
        snapshot->moving = pending_intent->state == BotControllerState::Moving;
        snapshot->has_target = pending_intent->has_target;
        snapshot->direction_x = pending_intent->direction_x;
        snapshot->direction_y = pending_intent->direction_y;
        snapshot->desired_heading_valid = pending_intent->desired_heading_valid;
        snapshot->desired_heading = pending_intent->desired_heading;
        snapshot->target_x = pending_intent->target_x;
        snapshot->target_y = pending_intent->target_y;
        snapshot->distance_to_target = pending_intent->distance_to_target;
    }

    return true;
}

void TickBotRuntime(std::uint64_t monotonic_ms) {
    std::vector<PendingBotEntitySync> ready_syncs;
    std::vector<PendingBotMovementIntent> controller_intents;
    std::vector<PendingBotDestroy> destroy_requests;
    {
        std::scoped_lock lock(g_bot_runtime_mutex);
        if (!g_bot_runtime_initialized) {
            return;
        }

        controller_intents = g_bot_movement_intents;
        destroy_requests = g_pending_destroys;

        for (auto& pending_sync : g_pending_entity_syncs) {
            if (pending_sync.next_attempt_ms > monotonic_ms) {
                continue;
            }

            if (FindPendingDestroy(pending_sync.bot_id) != nullptr) {
                continue;
            }

            pending_sync.next_attempt_ms = monotonic_ms + 250;
            ready_syncs.push_back(pending_sync);
        }
    }

    RuntimeState runtime = SnapshotRuntimeState();

    for (const auto& pending_destroy : destroy_requests) {
        std::string error_message;
        if (!TryDispatchDestroy(pending_destroy.bot_id, &error_message)) {
            continue;
        }

        std::scoped_lock lock(g_bot_runtime_mutex);
        auto* current_pending_destroy = FindPendingDestroy(pending_destroy.bot_id);
        if (current_pending_destroy != nullptr && current_pending_destroy->generation == pending_destroy.generation) {
            RemovePendingDestroy(pending_destroy.bot_id);
        }
    }

    for (const auto& pending_sync : ready_syncs) {
        if (FindBot(runtime, pending_sync.bot_id) == nullptr) {
            std::scoped_lock lock(g_bot_runtime_mutex);
            auto* current_pending_sync = FindPendingEntitySync(pending_sync.bot_id);
            if (current_pending_sync != nullptr && current_pending_sync->generation == pending_sync.generation) {
                RemovePendingEntitySync(pending_sync.bot_id);
            }
            continue;
        }

        std::string sync_error_message;
        if (!TryDispatchEntitySync(
                pending_sync.bot_id,
                pending_sync.character_profile,
                pending_sync.has_transform,
                pending_sync.has_heading,
                pending_sync.position_x,
                pending_sync.position_y,
                pending_sync.heading,
                &sync_error_message)) {
            continue;
        }

        std::scoped_lock lock(g_bot_runtime_mutex);
        auto* current_pending_sync = FindPendingEntitySync(pending_sync.bot_id);
        if (current_pending_sync != nullptr && current_pending_sync->generation == pending_sync.generation) {
            RemovePendingEntitySync(pending_sync.bot_id);
            Log(
                "[bots] gameplay sync request acknowledged. bot_id=" + std::to_string(pending_sync.bot_id) +
                " generation=" + std::to_string(pending_sync.generation));
        }
    }

    for (const auto& pending_intent : controller_intents) {
        auto updated_intent = pending_intent;
        const auto* participant = FindBot(runtime, pending_intent.bot_id);
        bool have_transform = false;
        float current_x = 0.0f;
        float current_y = 0.0f;
        float current_heading =
            pending_intent.desired_heading_valid ? pending_intent.desired_heading : 0.0f;
        if (participant != nullptr && participant->runtime.transform_valid) {
            have_transform = true;
            current_x = participant->runtime.position_x;
            current_y = participant->runtime.position_y;
            current_heading = participant->runtime.heading;
        }

        SDModBotGameplayState gameplay_state;
        if (TryGetWizardBotGameplayState(pending_intent.bot_id, &gameplay_state) &&
            gameplay_state.available &&
            gameplay_state.entity_materialized) {
            have_transform = true;
            current_x = gameplay_state.x;
            current_y = gameplay_state.y;
            current_heading = gameplay_state.heading;
            UpdateRuntimeState([&](RuntimeState& state) {
                auto* live_participant = FindBot(state, pending_intent.bot_id);
                if (live_participant == nullptr) {
                    return;
                }

                live_participant->runtime.valid = true;
                live_participant->runtime.in_run = true;
                live_participant->runtime.transform_valid = true;
                live_participant->runtime.position_x = gameplay_state.x;
                live_participant->runtime.position_y = gameplay_state.y;
                live_participant->runtime.heading = gameplay_state.heading;
                live_participant->runtime.life_current = static_cast<std::int32_t>(gameplay_state.hp);
                live_participant->runtime.life_max = static_cast<std::int32_t>(gameplay_state.max_hp);
                live_participant->runtime.mana_current = static_cast<std::int32_t>(gameplay_state.mp);
                live_participant->runtime.mana_max = static_cast<std::int32_t>(gameplay_state.max_mp);
            });
        }

        DeriveControllerMotionFromTransform(&updated_intent, have_transform, current_x, current_y, current_heading);

        std::scoped_lock lock(g_bot_runtime_mutex);
        auto* current_pending_intent = FindPendingMovementIntent(pending_intent.bot_id);
        if (current_pending_intent != nullptr && current_pending_intent->revision == pending_intent.revision) {
            current_pending_intent->state = updated_intent.state;
            current_pending_intent->has_target = updated_intent.has_target;
            current_pending_intent->target_x = updated_intent.target_x;
            current_pending_intent->target_y = updated_intent.target_y;
            current_pending_intent->distance_to_target = updated_intent.distance_to_target;
            current_pending_intent->direction_x = updated_intent.direction_x;
            current_pending_intent->direction_y = updated_intent.direction_y;
            current_pending_intent->desired_heading_valid = updated_intent.desired_heading_valid;
            current_pending_intent->desired_heading = updated_intent.desired_heading;
        }
    }
}

bool QueueBotCast(const BotCastRequest& request) {
    std::scoped_lock lock(g_bot_runtime_mutex);
    if (!g_bot_runtime_initialized || !IsValidCastRequest(request)) {
        return false;
    }

    bool queued = false;
    const auto now_ms = GetTickCount64();
    UpdateRuntimeState([&](RuntimeState& state) {
        const auto* participant = FindBot(state, request.bot_id);
        if (participant == nullptr) {
            return;
        }

        auto* pending_cast = FindPendingCast(request.bot_id);
        if (pending_cast == nullptr) {
            g_pending_casts.push_back(PendingBotCast{
                request.bot_id,
                request.kind,
                request.secondary_slot,
                g_next_cast_sequence++,
                now_ms,
            });
        } else {
            pending_cast->kind = request.kind;
            pending_cast->secondary_slot = request.secondary_slot;
            pending_cast->queued_cast_count = g_next_cast_sequence++;
            pending_cast->queued_at_ms = now_ms;
        }
        queued = true;
    });

    if (queued) {
        Log("[bots] queued cast for bot id=" + std::to_string(request.bot_id));
    }

    return queued;
}

std::uint32_t GetBotCount() {
    RuntimeState snapshot = SnapshotRuntimeState();
    return static_cast<std::uint32_t>(std::count_if(
        snapshot.participants.begin(),
        snapshot.participants.end(),
        [](const ParticipantInfo& participant) { return IsLuaBotParticipant(participant); }));
}

bool ReadBotSnapshot(std::uint64_t bot_id, BotSnapshot* snapshot) {
    if (snapshot == nullptr) {
        return false;
    }

    *snapshot = BotSnapshot{};
    RuntimeState runtime = SnapshotRuntimeState();
    const auto* participant = FindBot(runtime, bot_id);
    if (participant == nullptr) {
        return false;
    }

    std::scoped_lock lock(g_bot_runtime_mutex);
    FillBotSnapshot(*participant, snapshot);
    ApplyGameplayStateToSnapshot(bot_id, snapshot);
    ApplyControllerStateToSnapshot(bot_id, snapshot);
    return true;
}

bool ReadBotSnapshotByIndex(std::uint32_t index, BotSnapshot* snapshot) {
    if (snapshot == nullptr) {
        return false;
    }

    *snapshot = BotSnapshot{};
    RuntimeState runtime = SnapshotRuntimeState();
    std::uint32_t current_index = 0;
    for (const auto& participant : runtime.participants) {
        if (!IsLuaBotParticipant(participant)) {
            continue;
        }

        if (current_index == index) {
            std::scoped_lock lock(g_bot_runtime_mutex);
            FillBotSnapshot(participant, snapshot);
            ApplyGameplayStateToSnapshot(participant.participant_id, snapshot);
            ApplyControllerStateToSnapshot(participant.participant_id, snapshot);
            return true;
        }

        current_index += 1;
    }

    return false;
}

std::size_t GetPendingBotCastCount() {
    std::scoped_lock lock(g_bot_runtime_mutex);
    return g_pending_casts.size();
}

const char* BotControllerStateLabel(BotControllerState state) {
    return BotControllerStateLabelInternal(state);
}
