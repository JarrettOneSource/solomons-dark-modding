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
