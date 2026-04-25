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

    if (request.has_transform && !request.has_scene_intent) {
        SDModParticipantGameplayState gameplay_state;
        if (TryGetParticipantGameplayState(request.bot_id, &gameplay_state) &&
            gameplay_state.available &&
            gameplay_state.entity_materialized &&
            gameplay_state.entity_kind == kSDModParticipantGameplayKindRegisteredGameNpc) {
            Log(
                "[bots] rejecting transform-only update for materialized registered_gamenpc. bot_id=" +
                std::to_string(request.bot_id) +
                " actor=" + HexString(gameplay_state.actor_address));
            return false;
        }
    }

    bool updated = false;
    MultiplayerCharacterProfile sync_character_profile = DefaultCharacterProfile();
    ParticipantSceneIntent sync_scene_intent = DefaultParticipantSceneIntent();
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
        if (request.has_scene_intent) {
            ApplySceneIntent(participant, request.scene_intent);
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
        sync_scene_intent = participant->runtime.scene_intent;
        sync_has_transform = participant->runtime.transform_valid;
        sync_has_heading = request.has_heading;
        sync_position_x = participant->runtime.position_x;
        sync_position_y = participant->runtime.position_y;
        sync_heading = participant->runtime.heading;
        updated = true;
    });

    if (updated && (request.has_character_profile || request.has_scene_intent || request.has_transform)) {
        std::string sync_error_message;
        if (!TryDispatchEntitySync(
                request.bot_id,
                sync_character_profile,
                sync_scene_intent,
                sync_has_transform,
                sync_has_heading,
                sync_position_x,
                sync_position_y,
                sync_heading,
                &sync_error_message)) {
            SchedulePendingEntitySyncLocked(
                request.bot_id,
                sync_character_profile,
                sync_scene_intent,
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
    if (IsParticipantRuntimeDead(*participant)) {
        ClearDeadBotControlsLocked(*participant);
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

    const RuntimeState runtime = SnapshotRuntimeState();
    const auto* participant = FindBot(runtime, bot_id);
    if (participant == nullptr) {
        return false;
    }
    if (IsParticipantRuntimeDead(*participant)) {
        ClearDeadBotControlsLocked(*participant);
        return true;
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
    heading = NormalizeHeadingDegrees(heading);

    const RuntimeState runtime = SnapshotRuntimeState();
    const auto* participant = FindBot(runtime, bot_id);
    if (participant == nullptr) {
        return false;
    }
    if (IsParticipantRuntimeDead(*participant)) {
        ClearDeadBotControlsLocked(*participant);
        return false;
    }

    const auto* previous_intent = FindPendingMovementIntent(bot_id);
    const bool preserve_active_intent =
        previous_intent != nullptr &&
        (previous_intent->state == BotControllerState::Moving ||
         previous_intent->state == BotControllerState::Attacking ||
         previous_intent->has_target);
    const bool changed =
        previous_intent == nullptr ||
        !previous_intent->face_heading_valid ||
        std::fabs(previous_intent->face_heading - heading) > 0.01f;

    if (!preserve_active_intent) {
        SchedulePendingMovementIntentLocked(
            bot_id,
            BotControllerState::Idle,
            false,
            0.0f,
            0.0f,
            true,
            heading);
    }
    SetPendingFaceHeadingLocked(bot_id, true, heading, 0);
    SetPendingFaceTargetLocked(bot_id, 0);
    if (changed) {
        Log(
            "[bots] queued face id=" + std::to_string(bot_id) +
            " heading=" + std::to_string(heading));
    }

    return true;
}

bool FaceBotTarget(std::uint64_t bot_id, uintptr_t target_actor_address, bool fallback_heading_valid, float fallback_heading) {
    std::scoped_lock lock(g_bot_runtime_mutex);
    if (!g_bot_runtime_initialized || bot_id == 0) {
        return false;
    }
    if (fallback_heading_valid && !std::isfinite(fallback_heading)) {
        return false;
    }
    if (fallback_heading_valid) {
        fallback_heading = NormalizeHeadingDegrees(fallback_heading);
    }

    const RuntimeState runtime = SnapshotRuntimeState();
    const auto* participant = FindBot(runtime, bot_id);
    if (participant == nullptr) {
        return false;
    }
    if (IsParticipantRuntimeDead(*participant)) {
        ClearDeadBotControlsLocked(*participant);
        return false;
    }

    const auto* previous_intent = FindPendingMovementIntent(bot_id);
    const bool changed =
        previous_intent == nullptr ||
        previous_intent->face_target_actor_address != target_actor_address ||
        previous_intent->face_heading_valid != fallback_heading_valid ||
        (fallback_heading_valid &&
         (!previous_intent->face_heading_valid ||
          std::fabs(previous_intent->face_heading - fallback_heading) > 0.01f));

    if (fallback_heading_valid) {
        SetPendingFaceHeadingLocked(bot_id, true, fallback_heading, 0);
    } else if (target_actor_address == 0) {
        SetPendingFaceHeadingLocked(bot_id, false, 0.0f, 0);
    }
    SetPendingFaceTargetLocked(bot_id, target_actor_address);

    if (changed) {
        Log(
            "[bots] queued face_target id=" + std::to_string(bot_id) +
            " target=" + std::to_string(static_cast<std::uintptr_t>(target_actor_address)) +
            " fallback_valid=" + std::to_string(fallback_heading_valid ? 1 : 0));
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
    const auto* participant = FindBot(runtime, bot_id);
    if (participant == nullptr) {
        return false;
    }
    if (IsParticipantRuntimeDead(*participant)) {
        snapshot->available = true;
        return true;
    }

    snapshot->available = true;
    if (auto* pending_intent = FindPendingMovementIntent(bot_id); pending_intent != nullptr) {
        if (pending_intent->face_heading_valid &&
            pending_intent->face_heading_expires_ms != 0 &&
            GetTickCount64() > pending_intent->face_heading_expires_ms) {
            pending_intent->face_heading_valid = false;
            pending_intent->face_heading_expires_ms = 0;
        }
        snapshot->revision = pending_intent->revision;
        snapshot->state = pending_intent->state;
        snapshot->moving = pending_intent->state == BotControllerState::Moving;
        snapshot->has_target = pending_intent->has_target;
        snapshot->direction_x = pending_intent->direction_x;
        snapshot->direction_y = pending_intent->direction_y;
        snapshot->desired_heading_valid = pending_intent->desired_heading_valid;
        snapshot->desired_heading = pending_intent->desired_heading;
        snapshot->face_heading_valid = pending_intent->face_heading_valid;
        snapshot->face_heading = pending_intent->face_heading;
        snapshot->face_target_actor_address = pending_intent->face_target_actor_address;
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
                pending_sync.scene_intent,
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
        const bool participant_dead = participant != nullptr && IsParticipantRuntimeDead(*participant);
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

        SDModParticipantGameplayState gameplay_state;
        bool registered_gamenpc_native_movement = false;
        if (TryGetParticipantGameplayState(pending_intent.bot_id, &gameplay_state) &&
            gameplay_state.available &&
            gameplay_state.entity_materialized) {
            have_transform = true;
            current_x = gameplay_state.x;
            current_y = gameplay_state.y;
            current_heading = gameplay_state.heading;
            registered_gamenpc_native_movement =
                gameplay_state.entity_kind == kSDModParticipantGameplayKindRegisteredGameNpc;
        }

        if (participant_dead) {
            updated_intent.state = BotControllerState::Idle;
            updated_intent.has_target = false;
            updated_intent.target_x = current_x;
            updated_intent.target_y = current_y;
            updated_intent.distance_to_target = 0.0f;
            updated_intent.direction_x = 0.0f;
            updated_intent.direction_y = 0.0f;
            updated_intent.desired_heading_valid = have_transform || pending_intent.desired_heading_valid;
            updated_intent.desired_heading =
                have_transform ? current_heading : pending_intent.desired_heading;
        } else if (registered_gamenpc_native_movement &&
            updated_intent.state == BotControllerState::Moving &&
            gameplay_state.movement_intent_revision == pending_intent.revision &&
            !gameplay_state.moving) {
            // Registered GameNpc movement is consumed on the gameplay scene-binding
            // tick, not immediately at the runtime API boundary. Only treat
            // moving=false as native completion after gameplay has observed the
            // same movement intent revision; otherwise a freshly queued move_to()
            // is collapsed back to idle before gameplay can build the path.
            updated_intent.state = BotControllerState::Idle;
            updated_intent.has_target = false;
            updated_intent.target_x = current_x;
            updated_intent.target_y = current_y;
            updated_intent.distance_to_target = 0.0f;
            updated_intent.direction_x = 0.0f;
            updated_intent.direction_y = 0.0f;
            updated_intent.desired_heading_valid = true;
            updated_intent.desired_heading = current_heading;
        } else {
            DeriveControllerMotionFromTransform(&updated_intent, have_transform, current_x, current_y, current_heading);
        }

        std::scoped_lock lock(g_bot_runtime_mutex);
        if (participant_dead) {
            RemovePendingCast(pending_intent.bot_id);
        }
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

    const RuntimeState runtime = SnapshotRuntimeState();
    const auto* participant = FindBot(runtime, request.bot_id);
    if (participant == nullptr) {
        return false;
    }
    if (IsParticipantRuntimeDead(*participant)) {
        ClearDeadBotControlsLocked(*participant);
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
    bool desired_heading_valid =
        previous_intent != nullptr && previous_intent->desired_heading_valid;
    float desired_heading =
        desired_heading_valid ? previous_intent->desired_heading : current_heading;

    if (request.has_aim_target && have_transform) {
        const auto delta_x = request.aim_target_x - current_x;
        const auto delta_y = request.aim_target_y - current_y;
        if ((delta_x * delta_x) + (delta_y * delta_y) > 0.0001f) {
            desired_heading_valid = true;
            desired_heading = NormalizeHeadingDegrees(
                static_cast<float>(
                    std::atan2(delta_y, delta_x) * (180.0 / 3.14159265358979323846) + 90.0));
        }
    } else if (request.has_aim_angle && std::isfinite(request.aim_angle)) {
        desired_heading_valid = true;
        desired_heading = NormalizeHeadingDegrees(request.aim_angle);
    } else if (have_transform) {
        desired_heading_valid = true;
        desired_heading = NormalizeHeadingDegrees(current_heading);
    }

    bool queued = false;
    const auto now_ms = GetTickCount64();
    UpdateRuntimeState([&](RuntimeState& state) {
        if (FindBot(state, request.bot_id) == nullptr) {
            return;
        }

        auto* pending_cast = FindPendingCast(request.bot_id);
        if (pending_cast == nullptr) {
            g_pending_casts.push_back(PendingBotCast{});
            pending_cast = &g_pending_casts.back();
            pending_cast->bot_id = request.bot_id;
        }
        pending_cast->kind = request.kind;
        pending_cast->secondary_slot = request.secondary_slot;
        pending_cast->skill_id = request.skill_id;
        pending_cast->target_actor_address = request.target_actor_address;
        pending_cast->has_aim_target = request.has_aim_target;
        pending_cast->aim_target_x = request.aim_target_x;
        pending_cast->aim_target_y = request.aim_target_y;
        pending_cast->has_aim_angle = request.has_aim_angle;
        pending_cast->aim_angle = request.aim_angle;
        pending_cast->queued_cast_count = g_next_cast_sequence++;
        pending_cast->queued_at_ms = now_ms;
        SetPendingFaceTargetLocked(request.bot_id, request.target_actor_address);
        if (desired_heading_valid) {
            SetPendingFaceHeadingLocked(request.bot_id, true, desired_heading, 0);
        }
        queued = true;
    });

    if (queued) {
        Log(
            "[bots] queued cast for bot id=" + std::to_string(request.bot_id) +
            " facing_preserved=" + std::to_string(desired_heading_valid ? 1 : 0));
    }

    return queued;
}

bool FinishBotAttack(
    std::uint64_t bot_id,
    bool desired_heading_valid,
    float desired_heading,
    bool clear_face_target) {
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
    if (!desired_heading_valid &&
        previous_intent != nullptr &&
        previous_intent->desired_heading_valid) {
        desired_heading_valid = true;
        desired_heading = previous_intent->desired_heading;
    }
    if (desired_heading_valid) {
        desired_heading = NormalizeHeadingDegrees(desired_heading);
    }
    if (clear_face_target) {
        SetPendingFaceTargetLocked(bot_id, 0);
    }

    if (previous_intent != nullptr &&
        previous_intent->state == BotControllerState::Moving &&
        previous_intent->has_target) {
        if (desired_heading_valid) {
            SetPendingFaceHeadingLocked(bot_id, true, desired_heading, 0);
        }
        Log(
            "[bots] settled attack controller id=" + std::to_string(bot_id) +
            " movement_preserved=1 heading_valid=" + std::to_string(desired_heading_valid ? 1 : 0) +
            (desired_heading_valid ? " heading=" + std::to_string(desired_heading) : std::string("")));
        return true;
    }

    const bool changed =
        previous_intent == nullptr ||
        previous_intent->state != BotControllerState::Idle ||
        previous_intent->has_target ||
        previous_intent->desired_heading_valid != desired_heading_valid ||
        (desired_heading_valid &&
         (!previous_intent->desired_heading_valid ||
          std::fabs(previous_intent->desired_heading - desired_heading) > 0.01f));
    SchedulePendingMovementIntentLocked(
        bot_id,
        BotControllerState::Idle,
        false,
        0.0f,
        0.0f,
        desired_heading_valid,
        desired_heading);
    if (changed) {
        Log(
            "[bots] settled attack controller id=" + std::to_string(bot_id) +
            " state=idle heading_valid=" + std::to_string(desired_heading_valid ? 1 : 0) +
            (desired_heading_valid ? " heading=" + std::to_string(desired_heading) : std::string("")));
    }
    return true;
}

bool ConsumePendingBotCast(std::uint64_t bot_id, BotCastRequest* request) {
    if (request == nullptr || bot_id == 0) {
        return false;
    }

    std::scoped_lock lock(g_bot_runtime_mutex);
    if (!g_bot_runtime_initialized) {
        return false;
    }

    auto* pending_cast = FindPendingCast(bot_id);
    if (pending_cast == nullptr) {
        return false;
    }

    *request = BotCastRequest{};
    request->bot_id = pending_cast->bot_id;
    request->kind = pending_cast->kind;
    request->secondary_slot = pending_cast->secondary_slot;
    request->skill_id = pending_cast->skill_id;
    request->target_actor_address = pending_cast->target_actor_address;
    request->has_aim_target = pending_cast->has_aim_target;
    request->aim_target_x = pending_cast->aim_target_x;
    request->aim_target_y = pending_cast->aim_target_y;
    request->has_aim_angle = pending_cast->has_aim_angle;
    request->aim_angle = pending_cast->aim_angle;
    RemovePendingCast(bot_id);
    return true;
}

std::uint32_t GetBotCount() {
    RuntimeState snapshot = SnapshotRuntimeState();
    return static_cast<std::uint32_t>(std::count_if(
        snapshot.participants.begin(),
        snapshot.participants.end(),
        [](const ParticipantInfo& participant) { return IsLuaControlledParticipant(participant); }));
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
    DeriveBotCastReadiness(snapshot);
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
        if (!IsLuaControlledParticipant(participant)) {
            continue;
        }

        if (current_index == index) {
            std::scoped_lock lock(g_bot_runtime_mutex);
            FillBotSnapshot(participant, snapshot);
            ApplyGameplayStateToSnapshot(participant.participant_id, snapshot);
            ApplyControllerStateToSnapshot(participant.participant_id, snapshot);
            DeriveBotCastReadiness(snapshot);
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

void SetAllBotSceneIntentsToRun() {
    std::scoped_lock lock(g_bot_runtime_mutex);
    if (!g_bot_runtime_initialized) {
        return;
    }

    UpdateRuntimeState([](RuntimeState& state) {
        for (auto& participant : state.participants) {
            if (!IsLuaControlledParticipant(participant)) {
                continue;
            }

            ApplySceneIntent(
                &participant,
                ParticipantSceneIntent{
                    ParticipantSceneIntentKind::Run,
                    -1,
                    -1,
                });
        }
    });
}

void SetAllBotSceneIntentsToSharedHub() {
    std::scoped_lock lock(g_bot_runtime_mutex);
    if (!g_bot_runtime_initialized) {
        return;
    }

    UpdateRuntimeState([](RuntimeState& state) {
        for (auto& participant : state.participants) {
            if (!IsLuaControlledParticipant(participant)) {
                continue;
            }

            ApplySceneIntent(
                &participant,
                ParticipantSceneIntent{
                    ParticipantSceneIntentKind::SharedHub,
                    0,
                    0,
                });
        }
    });
}

const char* BotControllerStateLabel(BotControllerState state) {
    return BotControllerStateLabelInternal(state);
}
