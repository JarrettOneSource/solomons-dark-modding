void SyncWizardBotMovementIntent(ParticipantEntityBinding* binding) {
    if (binding == nullptr || binding->bot_id == 0) {
        return;
    }

    multiplayer::BotMovementIntentSnapshot intent;
    if (!multiplayer::ReadBotMovementIntent(binding->bot_id, &intent) || !intent.available) {
        return;
    }

    binding->movement_intent_revision = intent.revision;
    binding->controller_state = intent.state;
    binding->movement_active = intent.moving;
    binding->has_target = intent.has_target;
    if (!intent.moving) {
        binding->last_movement_displacement = 0.0f;
        binding->direction_x = 0.0f;
        binding->direction_y = 0.0f;
    }
    if (intent.moving) {
        binding->direction_x = intent.direction_x;
        binding->direction_y = intent.direction_y;
    }
    binding->desired_heading_valid = intent.desired_heading_valid;
    binding->desired_heading = intent.desired_heading;
    binding->facing_target_actor_address = intent.face_target_actor_address;
    const bool target_face_applied = RefreshWizardBindingTargetFacing(binding);
    if (target_face_applied) {
        // Native target-facing wins over fallback headings because the target can move.
    } else if (intent.face_heading_valid) {
        binding->facing_heading_valid = true;
        binding->facing_heading_value = intent.face_heading;
    } else if (!binding->ongoing_cast.active) {
        binding->facing_heading_valid = false;
        binding->facing_heading_value = 0.0f;
    }
    binding->target_x = intent.target_x;
    binding->target_y = intent.target_y;
    binding->distance_to_target = intent.distance_to_target;
}

void TickParticipantSceneBindings(uintptr_t gameplay_address, std::uint64_t now_ms) {
    const auto scene_churn_until =
        g_gameplay_keyboard_injection.scene_churn_not_before_ms.load(std::memory_order_acquire);
    if (now_ms < scene_churn_until) {
        return;
    }

    SceneContextSnapshot scene_context;
    const bool have_scene_context = TryBuildSceneContextSnapshot(gameplay_address, &scene_context);
    std::vector<ParticipantRematerializationRequest> rematerialization_requests;
    std::vector<std::uint64_t> dematerialize_requests;
    std::vector<PendingParticipantEntitySyncRequest> materialize_requests;
    {
        std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
        for (auto& binding : g_participant_entities) {
            SyncWizardBotMovementIntent(&binding);
            multiplayer::BotSnapshot bot_snapshot;
            if (multiplayer::ReadBotSnapshot(binding.bot_id, &bot_snapshot) && bot_snapshot.available) {
                binding.character_profile = bot_snapshot.character_profile;
                binding.scene_intent = bot_snapshot.scene_intent;
            }
            const bool should_be_materialized =
                have_scene_context && ShouldBotBeMaterializedInScene(binding, scene_context);
            if (binding.actor_address == 0) {
                if (should_be_materialized && now_ms >= binding.next_scene_materialize_retry_ms) {
                    if (bot_snapshot.available) {
                        PendingParticipantEntitySyncRequest sync_request;
                        sync_request.bot_id = binding.bot_id;
                        sync_request.character_profile = bot_snapshot.character_profile;
                        sync_request.scene_intent = bot_snapshot.scene_intent;
                        sync_request.has_transform = bot_snapshot.transform_valid;
                        sync_request.has_heading = bot_snapshot.transform_valid;
                        sync_request.x = bot_snapshot.position_x;
                        sync_request.y = bot_snapshot.position_y;
                        sync_request.heading = bot_snapshot.heading;
                        materialize_requests.push_back(sync_request);
                        binding.next_scene_materialize_retry_ms = now_ms + kWizardBotSyncRetryDelayMs;
                    }
                }
                PublishParticipantGameplaySnapshot(binding);
                continue;
            }

            if (have_scene_context && HasBotMaterializedSceneChanged(binding, scene_context)) {
                if (should_be_materialized) {
                    ParticipantRematerializationRequest rematerialization_request;
                    if (TryBuildParticipantRematerializationRequest(gameplay_address, binding, &rematerialization_request)) {
                        rematerialization_requests.push_back(rematerialization_request);
                    }
                } else {
                    dematerialize_requests.push_back(binding.bot_id);
                }
                continue;
            }

        }
    }

    for (const auto bot_id : dematerialize_requests) {
        DematerializeParticipantEntityNow(bot_id, false, "scene mismatch");
    }

    for (const auto& rematerialization_request : rematerialization_requests) {
        QueueParticipantRematerialization(rematerialization_request);
    }

    for (const auto& sync_request : materialize_requests) {
        std::string error_message;
        if (!QueueParticipantEntitySync(
                sync_request.bot_id,
                sync_request.character_profile,
                sync_request.scene_intent,
                sync_request.has_transform,
                sync_request.has_heading,
                sync_request.x,
                sync_request.y,
                sync_request.heading,
                &error_message)) {
            Log(
                "[bots] queued scene materialize failed. bot_id=" + std::to_string(sync_request.bot_id) +
                " element_id=" + std::to_string(sync_request.character_profile.element_id) +
                " error=" + error_message);
        }
    }
}

void TickParticipantSceneBindingsIfActive() {
    if (!g_gameplay_keyboard_injection.initialized) {
        return;
    }

    static std::uint64_t s_last_scene_binding_tick_ms = 0;
    static std::uint64_t s_last_scene_binding_log_ms = 0;
    const auto now_ms = static_cast<std::uint64_t>(::GetTickCount64());
    if constexpr (kEnableWizardBotHotPathDiagnostics) {
        if (now_ms - s_last_scene_binding_log_ms >= 1000) {
            s_last_scene_binding_log_ms = now_ms;
            std::uint32_t bot_count = 0;
            std::uint32_t materialized_count = 0;
            {
                std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
                bot_count = static_cast<std::uint32_t>(g_participant_entities.size());
                for (const auto& binding : g_participant_entities) {
                    if (binding.actor_address != 0) {
                        ++materialized_count;
                    }
                }
            }
            Log(
                "[bots] scene_binding_tick heartbeat participants=" + std::to_string(bot_count) +
                " materialized=" + std::to_string(materialized_count));
        }
    }
    if (now_ms - s_last_scene_binding_tick_ms < kWizardBotSceneBindingTickIntervalMs) {
        return;
    }
    s_last_scene_binding_tick_ms = now_ms;

    uintptr_t gameplay_address = 0;
    if (!TryResolveCurrentGameplayScene(&gameplay_address) || gameplay_address == 0) {
        return;
    }

    std::lock_guard<std::recursive_mutex> pump_lock(g_gameplay_action_pump_mutex);
    TickParticipantSceneBindings(gameplay_address, now_ms);
    {
        std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
        for (auto& binding : g_participant_entities) {
            if (!IsRegisteredGameNpcKind(binding.kind) || binding.actor_address == 0) {
                continue;
            }

            LogRegisteredGameNpcMovementControllerAnomaly(binding, now_ms);
            SyncWizardBotMovementIntent(&binding);
            std::string path_error;
            if (!UpdateWizardBotPathMotion(&binding, now_ms, &path_error) &&
                !path_error.empty()) {
                Log(
                    "[bots] registered_gamenpc path update failed. bot_id=" +
                    std::to_string(binding.bot_id) +
                    " actor=" + HexString(binding.actor_address) +
                    " error=" + path_error);
            }
            std::string movement_error;
            if (!DriveRegisteredGameNpcMovement(gameplay_address, &binding, now_ms, &movement_error) &&
                !movement_error.empty()) {
                Log(
                    "[bots] registered_gamenpc movement failed. bot_id=" +
                    std::to_string(binding.bot_id) +
                    " actor=" + HexString(binding.actor_address) +
                    " error=" + movement_error);
            }
        }
    }
}
