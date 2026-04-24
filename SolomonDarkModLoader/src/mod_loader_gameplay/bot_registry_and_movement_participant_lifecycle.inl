void RememberParticipantEntity(
    std::uint64_t participant_id,
    const multiplayer::MultiplayerCharacterProfile& character_profile,
    const multiplayer::ParticipantSceneIntent& scene_intent,
    uintptr_t actor_address,
    ParticipantEntityBinding::Kind kind,
    int gameplay_slot = -1,
    bool raw_allocation = false) {
    std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
    auto* binding = EnsureParticipantEntity(participant_id);
    if (binding == nullptr) {
        return;
    }

    if (binding->actor_address != 0 && binding->actor_address != actor_address) {
        binding->materialized_scene_address = 0;
        binding->materialized_world_address = 0;
        binding->materialized_region_index = -1;
        binding->gameplay_attach_applied = false;
        binding->standalone_idle_animation_drive_profile = ObservedActorAnimationDriveProfile{};
        binding->standalone_moving_animation_drive_profile = ObservedActorAnimationDriveProfile{};
        binding->standalone_progression_wrapper_address = 0;
        binding->standalone_progression_inner_address = 0;
        binding->standalone_equip_wrapper_address = 0;
        binding->standalone_equip_inner_address = 0;
        binding->registered_gamenpc_goal_active = false;
        binding->registered_gamenpc_following_local_slot = false;
        binding->registered_gamenpc_goal_x = 0.0f;
        binding->registered_gamenpc_goal_y = 0.0f;
        binding->synthetic_source_profile_address = 0;
        binding->dynamic_walk_cycle_primary = 0.0f;
        binding->dynamic_walk_cycle_secondary = 0.0f;
        binding->dynamic_render_drive_stride = 0.0f;
        binding->dynamic_render_advance_rate = 0.0f;
        binding->dynamic_render_advance_phase = 0.0f;
        binding->dynamic_render_drive_move_blend = 0.0f;
        binding->facing_heading_valid = false;
        binding->facing_heading_value = 0.0f;
        binding->facing_target_actor_address = 0;
        binding->stock_tick_facing_origin_valid = false;
        binding->stock_tick_facing_origin_x = 0.0f;
        binding->stock_tick_facing_origin_y = 0.0f;
        binding->death_transition_stock_tick_seen = false;
    }

    binding->character_profile = character_profile;
    binding->scene_intent = scene_intent;
    binding->actor_address = actor_address;
    binding->gameplay_slot = gameplay_slot;
    binding->kind = kind;
    binding->raw_allocation = raw_allocation;
    if (actor_address == 0) {
        binding->gameplay_attach_applied = false;
        binding->standalone_idle_animation_drive_profile = ObservedActorAnimationDriveProfile{};
        binding->standalone_moving_animation_drive_profile = ObservedActorAnimationDriveProfile{};
        binding->standalone_progression_wrapper_address = 0;
        binding->standalone_progression_inner_address = 0;
        binding->standalone_equip_wrapper_address = 0;
        binding->standalone_equip_inner_address = 0;
        binding->registered_gamenpc_goal_active = false;
        binding->registered_gamenpc_following_local_slot = false;
        binding->registered_gamenpc_goal_x = 0.0f;
        binding->registered_gamenpc_goal_y = 0.0f;
        binding->synthetic_source_profile_address = 0;
        binding->raw_allocation = false;
        binding->dynamic_walk_cycle_primary = 0.0f;
        binding->dynamic_walk_cycle_secondary = 0.0f;
        binding->dynamic_render_drive_stride = 0.0f;
        binding->dynamic_render_advance_rate = 0.0f;
        binding->dynamic_render_advance_phase = 0.0f;
        binding->dynamic_render_drive_move_blend = 0.0f;
        binding->facing_heading_valid = false;
        binding->facing_heading_value = 0.0f;
        binding->facing_target_actor_address = 0;
        binding->stock_tick_facing_origin_valid = false;
        binding->stock_tick_facing_origin_x = 0.0f;
        binding->stock_tick_facing_origin_y = 0.0f;
        binding->death_transition_stock_tick_seen = false;
    }
}

void ResetParticipantEntityMaterializationState(ParticipantEntityBinding* binding) {
    if (binding == nullptr) {
        return;
    }

    binding->actor_address = 0;
    binding->next_scene_materialize_retry_ms = 0;
    binding->materialized_scene_address = 0;
    binding->materialized_world_address = 0;
    binding->materialized_region_index = -1;
    binding->last_applied_animation_state_id = kUnknownAnimationStateId - 1;
    binding->standalone_idle_animation_drive_profile = ObservedActorAnimationDriveProfile{};
    binding->standalone_moving_animation_drive_profile = ObservedActorAnimationDriveProfile{};
    binding->standalone_progression_wrapper_address = 0;
    binding->standalone_progression_inner_address = 0;
    binding->standalone_equip_wrapper_address = 0;
    binding->standalone_equip_inner_address = 0;
    binding->registered_gamenpc_goal_active = false;
    binding->registered_gamenpc_following_local_slot = false;
    binding->registered_gamenpc_goal_x = 0.0f;
    binding->registered_gamenpc_goal_y = 0.0f;
    binding->gameplay_attach_applied = false;
    binding->raw_allocation = false;
    binding->synthetic_source_profile_address = 0;
    binding->dynamic_walk_cycle_primary = 0.0f;
    binding->dynamic_walk_cycle_secondary = 0.0f;
    binding->dynamic_render_drive_stride = 0.0f;
    binding->dynamic_render_advance_rate = 0.0f;
    binding->dynamic_render_advance_phase = 0.0f;
    binding->dynamic_render_drive_move_blend = 0.0f;
    binding->facing_heading_valid = false;
    binding->facing_heading_value = 0.0f;
    binding->facing_target_actor_address = 0;
    binding->stock_tick_facing_origin_valid = false;
    binding->stock_tick_facing_origin_x = 0.0f;
    binding->stock_tick_facing_origin_y = 0.0f;
    binding->death_transition_stock_tick_seen = false;
}

void MarkParticipantEntityWorldUnregistered(uintptr_t actor_address) {
    if (actor_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
    auto* binding = FindParticipantEntityForActor(actor_address);
    if (binding == nullptr || !IsWizardParticipantKind(binding->kind)) {
        return;
    }

    const auto bot_id = binding->bot_id;
    const auto gameplay_slot = binding->gameplay_slot;
    const auto gameplay_address = binding->materialized_scene_address;
    if (IsGameplaySlotWizardKind(binding->kind) &&
        gameplay_address != 0 &&
        gameplay_slot >= 0 &&
        gameplay_slot < static_cast<int>(kGameplayPlayerSlotCount)) {
        const auto actor_slot_offset =
            kGameplayPlayerActorOffset + static_cast<std::size_t>(gameplay_slot) * kGameplayPlayerSlotStride;
        const auto progression_slot_offset =
            kGameplayPlayerProgressionHandleOffset + static_cast<std::size_t>(gameplay_slot) * kGameplayPlayerSlotStride;
        const auto published_actor =
            memory.ReadFieldOr<uintptr_t>(gameplay_address, actor_slot_offset, 0);
        if (published_actor == actor_address) {
            (void)memory.TryWriteField<uintptr_t>(gameplay_address, actor_slot_offset, 0);
            (void)memory.TryWriteField<uintptr_t>(gameplay_address, progression_slot_offset, 0);
            Log(
                "[bots] world_unregister cleared stale gameplay slot publish. bot_id=" +
                std::to_string(bot_id) +
                " slot=" + std::to_string(gameplay_slot) +
                " actor=" + HexString(actor_address) +
                " gameplay=" + HexString(gameplay_address));
        }
    }
    ResetParticipantEntityMaterializationState(binding);
    PublishParticipantGameplaySnapshot(*binding);
    Log(
        "[bots] world_unregister reset tracked bot binding. bot_id=" + std::to_string(bot_id) +
        " slot=" + std::to_string(gameplay_slot) +
        " actor=" + HexString(actor_address));
}

void ForgetParticipantEntity(std::uint64_t bot_id) {
    std::lock_guard<std::recursive_mutex> entity_lock(g_participant_entities_mutex);
    g_participant_entities.erase(
        std::remove_if(
            g_participant_entities.begin(),
            g_participant_entities.end(),
            [&](const ParticipantEntityBinding& binding) {
                return binding.bot_id == bot_id;
            }),
        g_participant_entities.end());

    std::lock_guard<std::mutex> snapshot_lock(g_wizard_bot_snapshot_mutex);
    g_participant_gameplay_snapshots.erase(
        std::remove_if(
            g_participant_gameplay_snapshots.begin(),
            g_participant_gameplay_snapshots.end(),
            [&](const ParticipantGameplaySnapshot& snapshot) {
                return snapshot.bot_id == bot_id;
            }),
        g_participant_gameplay_snapshots.end());
    RefreshWizardBotCrashSummaryLocked();
}

void DematerializeParticipantEntityNow(std::uint64_t bot_id, bool forget_binding, std::string_view reason) {
    auto& memory = ProcessMemory::Instance();
    std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
    auto* binding = FindParticipantEntity(bot_id);
    if (binding == nullptr) {
        if (forget_binding) {
            ForgetParticipantEntity(bot_id);
        }
        return;
    }

    if (binding->actor_address != 0) {
        if (IsRegisteredGameNpcKind(binding->kind)) {
            StopRegisteredGameNpcMotion(binding);
        } else {
            StopWizardBotActorMotion(binding->actor_address);
        }

        std::string destroy_error;
        bool destroyed = false;
        if (IsGameplaySlotWizardKind(binding->kind) &&
            binding->gameplay_slot >= kFirstWizardBotSlot) {
            auto gameplay_address = binding->materialized_scene_address;
            if (gameplay_address == 0) {
                (void)TryResolveCurrentGameplayScene(&gameplay_address);
            }

            if (gameplay_address != 0) {
                destroyed = DestroyGameplaySlotBotResources(
                    gameplay_address,
                    binding->gameplay_slot,
                    binding->actor_address,
                    binding->materialized_world_address,
                    binding->synthetic_source_profile_address,
                    &destroy_error);
            } else {
                destroy_error = "Gameplay slot cleanup could not resolve a gameplay scene.";
            }
        } else if (IsRegisteredGameNpcKind(binding->kind)) {
            destroyed = DestroyRegisteredGameNpcActor(
                binding->actor_address,
                binding->materialized_world_address,
                &destroy_error);
        } else {
            if (IsStandaloneWizardKind(binding->kind) &&
                (binding->standalone_progression_wrapper_address != 0 ||
                 binding->standalone_progression_inner_address != 0 ||
                 binding->standalone_equip_wrapper_address != 0 ||
                 binding->standalone_equip_inner_address != 0)) {
                ReleaseStandaloneWizardVisualResources(
                    binding->actor_address,
                    binding->standalone_progression_wrapper_address,
                    binding->standalone_progression_inner_address,
                    binding->standalone_equip_wrapper_address,
                    binding->standalone_equip_inner_address);
                binding->standalone_progression_wrapper_address = 0;
                binding->standalone_progression_inner_address = 0;
                binding->standalone_equip_wrapper_address = 0;
                binding->standalone_equip_inner_address = 0;
            }
            destroyed = DestroyLoaderOwnedWizardActor(
                binding->actor_address,
                binding->materialized_world_address,
                binding->raw_allocation,
                &destroy_error);
        }
        if (destroyed) {
            DestroySyntheticWizardSourceProfile(binding->synthetic_source_profile_address);
            binding->synthetic_source_profile_address = 0;
        }
        if (!destroyed) {
            (void)memory.TryWriteField(binding->actor_address, kActorPositionXOffset, 100000.0f);
            (void)memory.TryWriteField(binding->actor_address, kActorPositionYOffset, 100000.0f);
            (void)memory.TryWriteField(binding->actor_address, kActorHeadingOffset, 0.0f);
        }
        Log(
            "[bots] dematerialized bot entity. bot_id=" + std::to_string(bot_id) +
            " slot=" + std::to_string(binding->gameplay_slot) +
            " kind=" + std::to_string(static_cast<int>(binding->kind)) +
            " actor=" + HexString(binding->actor_address) +
            " reason=" + std::string(reason) +
            (destroy_error.empty() ? std::string() : " detail=" + destroy_error));
    }

    ResetParticipantEntityMaterializationState(binding);
    PublishParticipantGameplaySnapshot(*binding);
    if (forget_binding) {
        ForgetParticipantEntity(bot_id);
    }
}

void DematerializeAllMaterializedWizardBotsForSceneSwitch(std::string_view reason) {
    std::vector<std::uint64_t> bot_ids;
    {
        std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
        for (const auto& binding : g_participant_entities) {
            if (!IsWizardParticipantKind(binding.kind) ||
                binding.actor_address == 0) {
                continue;
            }
            bot_ids.push_back(binding.bot_id);
        }
    }

    for (const auto bot_id : bot_ids) {
        DematerializeParticipantEntityNow(bot_id, false, reason);
    }
}
