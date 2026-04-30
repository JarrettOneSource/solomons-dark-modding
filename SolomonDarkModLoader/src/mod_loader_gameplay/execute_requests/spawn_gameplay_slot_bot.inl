bool TrySpawnGameplaySlotBotParticipantEntity(
    uintptr_t gameplay_address,
    const PendingParticipantEntitySyncRequest& request,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }

    uintptr_t local_actor_address = 0;
    if (!TryResolvePlayerActorForSlot(gameplay_address, 0, &local_actor_address) ||
        local_actor_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Local slot-0 player actor is not ready.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto world_address =
        memory.ReadFieldOr<uintptr_t>(local_actor_address, kActorOwnerOffset, 0);
    if (world_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Local slot-0 player world is not ready.";
        }
        return false;
    }

    float x = 0.0f;
    float y = 0.0f;
    float heading = 0.0f;
    if (!ResolveParticipantSpawnTransform(gameplay_address, request, &x, &y, &heading)) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve a bot transform.";
        }
        return false;
    }

    int target_slot = -1;
    (void)TryFindOpenGameplayBotSlot(gameplay_address, &target_slot);
    if (target_slot < 0) {
        if (error_message != nullptr) {
            *error_message = "All gameplay bot slots (1..3) are occupied.";
        }
        return false;
    }

    uintptr_t actor_address = 0;
    uintptr_t progression_address = 0;
    auto cleanup_spawn = [&](std::string_view failure_message) {
        std::string cleanup_error;
        (void)DestroyGameplaySlotBotResources(
            gameplay_address,
            target_slot,
            actor_address,
            world_address,
            0,
            &cleanup_error);
        actor_address = 0;
        progression_address = 0;
        if (error_message != nullptr) {
            *error_message = std::string(failure_message);
            if (!cleanup_error.empty()) {
                *error_message += " cleanup=" + cleanup_error;
            }
        }
        return false;
    };

    std::string stage_error;
    if (!CreateGameplaySlotBotActor(
            gameplay_address,
            world_address,
            target_slot,
            request.character_profile,
            x,
            y,
            heading,
            &actor_address,
            &progression_address,
            &stage_error)) {
        return cleanup_spawn(stage_error);
    }

    if (!FinalizeGameplaySlotBotRegistration(
            gameplay_address,
            world_address,
            target_slot,
            actor_address,
            nullptr,
            &stage_error)) {
        return cleanup_spawn(stage_error);
    }

    RememberParticipantEntity(
        request.bot_id,
        request.character_profile,
        request.scene_intent,
        actor_address,
        ParticipantEntityBinding::Kind::GameplaySlotWizard,
        target_slot,
        false);
    {
        std::lock_guard<std::recursive_mutex> binding_lock(g_participant_entities_mutex);
        if (auto* binding = FindParticipantEntity(request.bot_id); binding != nullptr) {
            binding->controller_state = multiplayer::BotControllerState::Idle;
            binding->movement_active = false;
            binding->has_target = false;
            binding->desired_heading_valid = false;
            binding->next_scene_materialize_retry_ms = 0;
            binding->materialized_scene_address = gameplay_address;
            binding->materialized_world_address = world_address;
            binding->materialized_region_index = -1;
            binding->gameplay_attach_applied = true;
            binding->gameplay_slot = target_slot;
            binding->raw_allocation = false;
            binding->standalone_progression_wrapper_address = 0;
            binding->standalone_progression_inner_address = 0;
            binding->standalone_equip_wrapper_address = 0;
            binding->standalone_equip_inner_address = 0;
            binding->synthetic_source_profile_address = 0;
            SeedStandaloneWizardAnimationDriveProfiles(binding, actor_address);

            SceneContextSnapshot scene_context;
            if (TryBuildSceneContextSnapshot(gameplay_address, &scene_context)) {
                binding->materialized_region_index = scene_context.current_region_index;
            }

            PublishParticipantGameplaySnapshot(*binding);
        }
    }

    Log(
        "[bots] created gameplay-slot wizard actor. bot_id=" + std::to_string(request.bot_id) +
        " actor=" + HexString(actor_address) +
        " world=" + HexString(world_address) +
        " gameplay_slot=" + std::to_string(target_slot) +
        " actor_slot=" + std::to_string(static_cast<int>(memory.ReadFieldOr<std::int8_t>(
            actor_address,
            kActorSlotOffset,
            -1))) +
        " resolved_anim_state=" + std::to_string(ResolveActorAnimationStateId(actor_address)) +
        " progression_handle=" +
        HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorProgressionHandleOffset, 0)) +
        " equip_handle=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorEquipHandleOffset, 0)));
    return true;
}
