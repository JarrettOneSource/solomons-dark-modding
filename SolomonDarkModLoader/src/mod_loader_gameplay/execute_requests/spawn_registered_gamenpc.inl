bool TrySpawnRegisteredGameNpcParticipantEntity(
    uintptr_t gameplay_address,
    const PendingParticipantEntitySyncRequest& request,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }

    // Reserved for a real GameNpc (0x1397) rail. WizardCloneFromSourceActor
    // returns a player-family clone and must stay on the standalone wizard
    // path instead of being remembered as RegisteredGameNpc.

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

    uintptr_t actor_address = 0;
    uintptr_t source_actor_address = 0;
    uintptr_t source_profile_address = 0;
    auto cleanup_spawn = [&](std::string_view failure_message) {
        std::string cleanup_error;
        if (actor_address != 0) {
            (void)DestroyRegisteredGameNpcActor(
                actor_address,
                memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, world_address),
                &cleanup_error);
        }
        if (source_actor_address != 0) {
            std::string source_cleanup_error;
            (void)DestroyWizardCloneSourceActor(source_actor_address, &source_cleanup_error);
            if (cleanup_error.empty() && !source_cleanup_error.empty()) {
                cleanup_error = source_cleanup_error;
            }
        }
        if (source_profile_address != 0) {
            DestroySyntheticWizardSourceProfile(source_profile_address);
        }
        actor_address = 0;
        source_actor_address = 0;
        source_profile_address = 0;
        if (error_message != nullptr) {
            *error_message = std::string(failure_message);
            if (!cleanup_error.empty()) {
                *error_message += " cleanup=" + cleanup_error;
            }
        }
        return false;
    };

    std::string stage_error;
    if (!CreateWizardCloneSourceActor(
            world_address,
            request.character_profile,
            x,
            y,
            heading,
            &source_actor_address,
            &source_profile_address,
            &stage_error)) {
        return cleanup_spawn(stage_error);
    }

    const auto clone_from_source_address =
        memory.ResolveGameAddressOrZero(kWizardCloneFromSourceActor);
    if (clone_from_source_address == 0) {
        return cleanup_spawn("Unable to resolve WizardCloneFromSourceActor.");
    }

    DWORD clone_exception_code = 0;
    if (!CallWizardCloneFromSourceActorSafe(
            clone_from_source_address,
            source_actor_address,
            &actor_address,
            &clone_exception_code) ||
        actor_address == 0) {
        return cleanup_spawn(
            "WizardCloneFromSourceActor failed with 0x" +
            HexString(clone_exception_code) + ".");
    }

    {
        const auto selection_state_address =
            memory.ReadFieldOr<uintptr_t>(actor_address, kActorAnimationSelectionStateOffset, 0);
        if (selection_state_address != 0) {
            (void)memory.TryWriteField<std::uint8_t>(selection_state_address, 0x24, 1);
        }

        uintptr_t progression_address =
            memory.ReadFieldOr<uintptr_t>(actor_address, kActorProgressionRuntimeStateOffset, 0);
        if (progression_address == 0) {
            progression_address = ReadSmartPointerInnerObject(
                memory.ReadFieldOr<uintptr_t>(actor_address, kActorProgressionHandleOffset, 0));
        }
        if (progression_address != 0) {
            constexpr float kDefaultAllyHp = 25.0f;
            (void)memory.TryWriteField<float>(
                progression_address,
                kProgressionHpOffset,
                kDefaultAllyHp);
            (void)memory.TryWriteField<float>(
                progression_address,
                kProgressionMaxHpOffset,
                kDefaultAllyHp);
        }
    }

    if (!DestroyWizardCloneSourceActor(source_actor_address, &stage_error)) {
        return cleanup_spawn(stage_error);
    }
    source_actor_address = 0;
    DestroySyntheticWizardSourceProfile(source_profile_address);
    source_profile_address = 0;

    const auto rebind_actor_address =
        memory.ResolveGameAddressOrZero(kWorldCellGridRebindActor);
    if (rebind_actor_address == 0) {
        return cleanup_spawn("Unable to resolve WorldCellGrid_RebindActor.");
    }

    DWORD rebind_exception_code = 0;
    if (!CallWorldCellGridRebindActorSafe(
            rebind_actor_address,
            memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, world_address),
            actor_address,
            &rebind_exception_code)) {
        return cleanup_spawn(
            "WorldCellGrid_RebindActor failed with 0x" +
            HexString(rebind_exception_code) + ".");
    }

    RememberParticipantEntity(
        request.bot_id,
        request.character_profile,
        request.scene_intent,
        actor_address,
        ParticipantEntityBinding::Kind::RegisteredGameNpc,
        -1,
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
            binding->materialized_world_address =
                memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, world_address);
            binding->materialized_region_index = -1;
            binding->gameplay_attach_applied = false;
            binding->gameplay_slot = -1;
            binding->raw_allocation = false;
            binding->standalone_progression_wrapper_address = 0;
            binding->standalone_progression_inner_address = 0;
            binding->standalone_equip_wrapper_address = 0;
            binding->standalone_equip_inner_address = 0;
            binding->registered_gamenpc_goal_active = false;
            binding->registered_gamenpc_following_local_slot = false;
            binding->registered_gamenpc_goal_x = 0.0f;
            binding->registered_gamenpc_goal_y = 0.0f;
            binding->synthetic_source_profile_address = 0;

            SceneContextSnapshot scene_context;
            if (TryBuildSceneContextSnapshot(gameplay_address, &scene_context)) {
                binding->materialized_region_index = scene_context.current_region_index;
            }

            PublishParticipantGameplaySnapshot(*binding);
        }
    }

    const auto moved_x = memory.TryWriteField(actor_address, kActorPositionXOffset, x);
    const auto moved_y = memory.TryWriteField(actor_address, kActorPositionYOffset, y);
    ApplyWizardActorFacingState(actor_address, heading);
    if (!moved_x || !moved_y) {
        Log(
            "[bots] registered_gamenpc transform write incomplete. actor=" + HexString(actor_address) +
            " wrote_x=" + std::to_string(moved_x ? 1 : 0) +
            " wrote_y=" + std::to_string(moved_y ? 1 : 0));
    }

    Log(
        "[bots] created registered GameNpc actor. bot_id=" + std::to_string(request.bot_id) +
        " actor=" + HexString(actor_address) +
        " world=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, world_address)) +
        " object_type=0x" + HexString(memory.ReadFieldOr<std::uint32_t>(actor_address, kGameObjectTypeIdOffset, 0)) +
        " actor_slot=" + std::to_string(static_cast<int>(memory.ReadFieldOr<std::int8_t>(
            actor_address,
            kActorSlotOffset,
            -1))) +
        " resolved_anim_state=" + std::to_string(ResolveActorAnimationStateId(actor_address)) +
        " source_kind=" + std::to_string(memory.ReadFieldOr<std::int32_t>(
            actor_address,
            kActorHubVisualSourceKindOffset,
            0)) +
        " source_profile=" + HexString(memory.ReadFieldOr<uintptr_t>(
            actor_address,
            kActorHubVisualSourceProfileOffset,
            0)) +
        " attachment=" + HexString(memory.ReadFieldOr<uintptr_t>(
            actor_address,
            kActorHubVisualAttachmentPtrOffset,
            0)));
    return true;
}
