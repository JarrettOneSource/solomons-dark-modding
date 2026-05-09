bool TrySpawnStandaloneRemoteWizardParticipantEntity(
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
    uintptr_t world_address = 0;
    if (!memory.TryReadField(local_actor_address, kActorOwnerOffset, &world_address)) {
        if (error_message != nullptr) {
            *error_message = "Local slot-0 player world is unreadable.";
        }
        return false;
    }
    if (world_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Local slot-0 player world is not ready.";
        }
        return false;
    }

    float x = 0.0f;
    float y = 0.0f;
    float heading = 0.0f;
    if (!ResolveParticipantSpawnTransform(gameplay_address, request, true, &x, &y, &heading)) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve a bot transform.";
        }
        return false;
    }

    uintptr_t actor_address = 0;
    uintptr_t source_actor_address = 0;
    auto cleanup_spawn = [&](std::string_view failure_message) {
        std::string cleanup_error;
        if (actor_address != 0) {
            uintptr_t cleanup_world_address = 0;
            if (!memory.TryReadField(actor_address, kActorOwnerOffset, &cleanup_world_address)) {
                cleanup_error = "actor owner unreadable during cleanup";
            }
            (void)DestroyLoaderOwnedWizardActor(
                actor_address,
                cleanup_world_address,
                false,
                &cleanup_error);
        }
        if (source_actor_address != 0) {
            std::string source_cleanup_error;
            (void)DestroyWizardCloneSourceActor(source_actor_address, &source_cleanup_error);
            if (cleanup_error.empty() && !source_cleanup_error.empty()) {
                cleanup_error = source_cleanup_error;
            }
        }
        actor_address = 0;
        source_actor_address = 0;
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
            local_actor_address,
            request.character_profile,
            x,
            y,
            heading,
            &source_actor_address,
            &stage_error)) {
        return cleanup_spawn(stage_error);
    }
    LogBotVisualDebugStage(
        "spawn_after_source_create",
        local_actor_address,
        0,
        source_actor_address);
    const auto source_render_snapshot = CaptureActorRenderBuildSnapshot(source_actor_address);

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

    if (!SeedWizardBotNativeCollisionStateFromSourceActor(
            actor_address,
            local_actor_address,
            &stage_error)) {
        return cleanup_spawn(stage_error);
    }

    if (!ApplySourceActorRenderSelectorsToTargetActor(
            actor_address,
            source_render_snapshot,
            &stage_error)) {
        return cleanup_spawn(stage_error);
    }

    uintptr_t progression_address = 0;
    if (!TryResolveActorProgressionRuntime(actor_address, &progression_address) ||
        progression_address == 0 ||
        !EnsureBotOwnedProgressionMode(progression_address, "standalone_clone_spawn")) {
        return cleanup_spawn(
            "Standalone clone progression could not be marked as bot-owned non-local mode. progression=" +
            HexString(progression_address));
    }

    {
        uintptr_t selection_state_address = 0;
        if (!memory.TryReadField(actor_address, kActorAnimationSelectionStateOffset, &selection_state_address)) {
            return cleanup_spawn("Standalone clone selection state pointer is unreadable.");
        }
        if (selection_state_address != 0) {
            (void)memory.TryWriteField<std::uint8_t>(
                selection_state_address,
                kActorControlBrainFollowLeaderOffset,
                1);
        }
    }

    if (!DestroyWizardCloneSourceActor(source_actor_address, &stage_error)) {
        return cleanup_spawn(stage_error);
    }
    source_actor_address = 0;

    if (!AttachGameplaySlotBotStaffItem(actor_address, &stage_error)) {
        return cleanup_spawn(stage_error);
    }

    const auto rebind_actor_address =
        memory.ResolveGameAddressOrZero(kWorldCellGridRebindActor);
    if (rebind_actor_address == 0) {
        return cleanup_spawn("Unable to resolve WorldCellGrid_RebindActor.");
    }

    DWORD rebind_exception_code = 0;
    uintptr_t rebind_world_address = 0;
    if (!memory.TryReadField(actor_address, kActorOwnerOffset, &rebind_world_address)) {
        return cleanup_spawn("Standalone clone world owner is unreadable before rebind.");
    }
    if (!CallWorldCellGridRebindActorSafe(
            rebind_actor_address,
            rebind_world_address,
            actor_address,
            &rebind_exception_code)) {
        return cleanup_spawn(
            "WorldCellGrid_RebindActor failed for standalone wizard with 0x" +
            HexString(rebind_exception_code) + ".");
    }

    LogLocalPlayerAnimationProbe();
    RememberParticipantEntity(
        request.bot_id,
        request.character_profile,
        request.scene_intent,
        actor_address,
        ParticipantEntityBinding::Kind::StandaloneWizard,
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
            if (!memory.TryReadField(
                    actor_address,
                    kActorOwnerOffset,
                    &binding->materialized_world_address)) {
                binding->materialized_world_address = 0;
            }
            binding->materialized_region_index = -1;
            binding->gameplay_attach_applied = true;
            binding->gameplay_slot = -1;
            binding->raw_allocation = false;
            (void)memory.TryReadField(
                actor_address,
                kActorProgressionHandleOffset,
                &binding->standalone_progression_wrapper_address);
            binding->standalone_progression_inner_address =
                ReadSmartPointerInnerObject(binding->standalone_progression_wrapper_address);
            (void)memory.TryReadField(
                actor_address,
                kActorEquipHandleOffset,
                &binding->standalone_equip_wrapper_address);
            binding->standalone_equip_inner_address =
                ReadSmartPointerInnerObject(binding->standalone_equip_wrapper_address);
            SeedStandaloneWizardAnimationDriveProfiles(binding, actor_address);

            SceneContextSnapshot scene_context;
            if (TryBuildSceneContextSnapshot(gameplay_address, &scene_context)) {
                binding->materialized_region_index = scene_context.current_region_index;
            }

            PublishParticipantGameplaySnapshot(*binding);
        }
    }
    LogBotVisualDebugStage(
        "spawn_after_binding_publish",
        local_actor_address,
        actor_address,
        0);

    const auto moved_x = memory.TryWriteField(actor_address, kActorPositionXOffset, x);
    const auto moved_y = memory.TryWriteField(actor_address, kActorPositionYOffset, y);
    ApplyWizardActorFacingState(actor_address, heading);
    if (!moved_x || !moved_y) {
        Log(
            "[bots] standalone clone transform write incomplete. actor=" +
            HexString(actor_address) +
            " wrote_x=" + std::to_string(moved_x ? 1 : 0) +
            " wrote_y=" + std::to_string(moved_y ? 1 : 0));
    }
    if (moved_x && moved_y) {
        DWORD transform_rebind_exception_code = 0;
        if (!TryRebindActorToOwnerWorld(actor_address, &transform_rebind_exception_code)) {
            Log(
                "[bots] standalone clone final transform rebind failed. actor=" +
                HexString(actor_address) +
                " exception=" + HexString(transform_rebind_exception_code));
        }
    }

    uintptr_t final_world_address = 0;
    std::int8_t actor_slot = -1;
    uintptr_t progression_handle = 0;
    uintptr_t equip_handle = 0;
    uintptr_t attachment = 0;
    const auto final_world_text =
        memory.TryReadField(actor_address, kActorOwnerOffset, &final_world_address)
            ? HexString(final_world_address)
            : std::string("unreadable");
    const auto actor_slot_text =
        memory.TryReadField(actor_address, kActorSlotOffset, &actor_slot)
            ? std::to_string(static_cast<int>(actor_slot))
            : std::string("unreadable");
    const auto progression_handle_text =
        memory.TryReadField(actor_address, kActorProgressionHandleOffset, &progression_handle)
            ? HexString(progression_handle)
            : std::string("unreadable");
    const auto equip_handle_text =
        memory.TryReadField(actor_address, kActorEquipHandleOffset, &equip_handle)
            ? HexString(equip_handle)
            : std::string("unreadable");
    const auto attachment_text =
        memory.TryReadField(actor_address, kActorHubVisualAttachmentPtrOffset, &attachment)
            ? HexString(attachment)
            : std::string("unreadable");
    Log(
        "[bots] created standalone clone wizard actor. bot_id=" + std::to_string(request.bot_id) +
        " actor=" + HexString(actor_address) +
        " world=" + final_world_text +
        " gameplay_slot=-1" +
        " actor_slot=" + actor_slot_text +
        " slot_anim_state=" + std::to_string(ResolveActorAnimationStateSlotIndex(actor_address)) +
        " resolved_anim_state=" + std::to_string(ResolveActorAnimationStateId(actor_address)) +
        " progression_handle=" + progression_handle_text +
        " equip_handle=" + equip_handle_text +
        " attachment=" + attachment_text);
    return true;
}
