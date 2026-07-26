bool SpawnNativeRemoteParticipantDeathDrop(
    uintptr_t actor_address,
    uintptr_t item_address,
    std::uint32_t item_type_id,
    uintptr_t* bouncer_address,
    std::string* error_message) {
    if (bouncer_address != nullptr) {
        *bouncer_address = 0;
    }
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (actor_address == 0 ||
        item_address == 0 ||
        bouncer_address == nullptr ||
        (item_type_id != kStandaloneWizardStaffItemTypeId &&
         item_type_id != kStandaloneWizardWandItemTypeId)) {
        if (error_message != nullptr) {
            *error_message = "Remote death drop source is invalid.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto allocate_address =
        memory.ResolveGameAddressOrZero(kObjectAllocate);
    const auto free_address =
        memory.ResolveGameAddressOrZero(kGameFree);
    const auto ctor_address =
        memory.ResolveGameAddressOrZero(kAnimationBouncerCtor);
    const auto vtable_address =
        memory.ResolveGameAddressOrZero(
            item_type_id == kStandaloneWizardStaffItemTypeId
                ? kStaffAnimationBouncerVtable
                : kWandAnimationBouncerVtable);
    const auto resolver_address =
        memory.ResolveGameAddressOrZero(
            item_type_id == kStandaloneWizardStaffItemTypeId
                ? kStaffAnimationBouncerResolveVisual
                : kWandAnimationBouncerResolveVisual);
    const auto random_address =
        memory.ResolveGameAddressOrZero(kNativeRngFloat);
    uintptr_t rng_state_address = 0;
    if (allocate_address == 0 ||
        free_address == 0 ||
        ctor_address == 0 ||
        vtable_address == 0 ||
        resolver_address == 0 ||
        random_address == 0 ||
        !TryResolveNativeGlobalRngState(
            nullptr,
            &rng_state_address)) {
        if (error_message != nullptr) {
            *error_message =
                "Remote death drop native seams are unavailable.";
        }
        return false;
    }

    float actor_x = 0.0f;
    float actor_y = 0.0f;
    float actor_heading = 0.0f;
    uintptr_t world_address = 0;
    if (!TryReadFiniteFloatField(
            actor_address,
            kActorPositionXOffset,
            &actor_x) ||
        !TryReadFiniteFloatField(
            actor_address,
            kActorPositionYOffset,
            &actor_y) ||
        !TryReadFiniteFloatField(
            actor_address,
            kActorHeadingOffset,
            &actor_heading) ||
        !memory.TryReadField(
            actor_address,
            kActorOwnerOffset,
            &world_address) ||
        world_address == 0) {
        if (error_message != nullptr) {
            *error_message =
                "Remote death drop could not resolve actor placement.";
        }
        return false;
    }

    DWORD exception_code = 0;
    uintptr_t allocation = 0;
    if (!CallGameObjectAllocateSafe(
            allocate_address,
            kAnimationBouncerSize,
            &allocation,
            &exception_code) ||
        allocation == 0) {
        if (error_message != nullptr) {
            *error_message =
                "Remote death drop allocation failed with 0x" +
                HexString(exception_code) + ".";
        }
        return false;
    }

    uintptr_t bouncer = 0;
    if (!CallRawObjectCtorSafe(
            ctor_address,
            reinterpret_cast<void*>(allocation),
            &bouncer,
            &exception_code) ||
        bouncer == 0) {
        DWORD free_exception_code = 0;
        (void)CallGameFreeSafe(
            free_address,
            allocation,
            &free_exception_code);
        if (error_message != nullptr) {
            *error_message =
                "Remote death drop construction failed with 0x" +
                HexString(exception_code) + ".";
        }
        return false;
    }

    const auto destroy_bouncer = [&] {
        DWORD destroy_exception_code = 0;
        (void)CallScalarDeletingDestructorSafe(
            bouncer,
            1,
            &destroy_exception_code);
    };
    if (!memory.TryWriteValue<uintptr_t>(
            bouncer,
            vtable_address) ||
        !CallAnimationBouncerVisualResolverSafe(
            resolver_address,
            bouncer,
            item_address,
            &exception_code)) {
        destroy_bouncer();
        if (error_message != nullptr) {
            *error_message =
                "Remote death drop visual initialization failed with 0x" +
                HexString(exception_code) + ".";
        }
        return false;
    }

    constexpr float kDegreesToRadians =
        3.14159265358979323846f / 180.0f;
    const auto heading_radians =
        actor_heading * kDegreesToRadians;
    const float velocity_x =
        std::cos(heading_radians) *
        kAnimationBouncerHorizontalVelocityScale;
    const float velocity_y =
        -std::sin(heading_radians);
    float random_launch_offset = 0.0f;
    if (!CallNativeRngFloatSafe(
            random_address,
            rng_state_address,
            kAnimationBouncerLaunchOffsetRange,
            &random_launch_offset,
            &exception_code)) {
        destroy_bouncer();
        if (error_message != nullptr) {
            *error_message =
                "Remote death drop launch sampling failed with 0x" +
                HexString(exception_code) + ".";
        }
        return false;
    }

    const float launch_offset =
        kAnimationBouncerLaunchOffsetMinimum +
        random_launch_offset;
    const float bouncer_x =
        actor_x +
        velocity_x *
            (launch_offset +
             kAnimationBouncerForwardOffset);
    const float bouncer_y =
        actor_y + velocity_y * launch_offset;
    const bool seeded =
        memory.TryWriteField(
            bouncer,
            kAnimationBouncerPositionXOffset,
            bouncer_x) &&
        memory.TryWriteField(
            bouncer,
            kAnimationBouncerPositionYOffset,
            bouncer_y) &&
        memory.TryWriteField(
            bouncer,
            kAnimationBouncerVelocityXOffset,
            velocity_x) &&
        memory.TryWriteField(
            bouncer,
            kAnimationBouncerVelocityYOffset,
            velocity_y) &&
        memory.TryWriteField(
            bouncer,
            kAnimationBouncerLifetimeOffset,
            kAnimationBouncerLifetime) &&
        memory.TryWriteField<std::uint8_t>(
            bouncer,
            kAnimationBouncerActiveOffset,
            1);
    if (!seeded ||
        !CallWorldAnimationLaneInsertSafe(
            world_address,
            bouncer,
            &exception_code)) {
        destroy_bouncer();
        if (error_message != nullptr) {
            *error_message =
                "Remote death drop placement failed with 0x" +
                HexString(exception_code) + ".";
        }
        return false;
    }

    if (item_type_id == kStandaloneWizardStaffItemTypeId) {
        DWORD post_insert_exception_code = 0;
        if (!CallAnimationBouncerPostInsertSafe(
                bouncer,
                &post_insert_exception_code)) {
            Log(
                "[bots] remote staff death drop post-insert callback failed. "
                "bouncer=" +
                HexString(bouncer) +
                " seh=0x" +
                HexString(post_insert_exception_code));
        }
    }
    *bouncer_address = bouncer;
    return true;
}
bool TrySpawnNativeRemoteParticipantDeathDrop(
    ParticipantEntityBinding* binding,
    uintptr_t actor_address) {
    if (!IsNativeRemoteParticipantBinding(binding) ||
        actor_address == 0) {
        return false;
    }
    if (binding->native_remote_death_drop_spawned) {
        return true;
    }

    uintptr_t equip_runtime_state_address = 0;
    SDModEquipVisualLaneState attachment;
    if (TryResolveRemoteParticipantEquipRuntime(
            actor_address,
            &equip_runtime_state_address)) {
        attachment = ReadEquipVisualLaneState(
            equip_runtime_state_address,
            kActorEquipRuntimeVisualLinkAttachmentOffset);
    }

    uintptr_t source_item = 0;
    std::uint32_t source_type = 0;
    bool temporary_source_item = false;
    if (attachment.current_object_address != 0 &&
        (attachment.current_object_type_id ==
             kStandaloneWizardStaffItemTypeId ||
         attachment.current_object_type_id ==
             kStandaloneWizardWandItemTypeId)) {
        source_item = attachment.current_object_address;
        source_type = attachment.current_object_type_id;
    } else {
        if ((binding->replicated_presentation_flags &
             multiplayer::ParticipantPresentationFlagEquipmentState) == 0) {
            return false;
        }
        source_type =
            binding->replicated_attachment_visual_link_type_id;
        if (source_type == 0) {
            binding->native_remote_death_drop_spawned = true;
            return true;
        }

        std::string source_error;
        const auto source_recipe_uid =
            binding->replicated_attachment_visual_link_recipe_uid;
        if (source_recipe_uid != 0) {
            const std::array<
                std::uint8_t,
                multiplayer::kParticipantVisualLinkColorBlockBytes>
                empty_color = {};
            if (!CloneNativeItemFromRecipe(
                    source_recipe_uid,
                    source_type,
                    empty_color,
                    false,
                    &source_item,
                    &source_error)) {
                return false;
            }
        } else if (
            source_type == kStandaloneWizardStaffItemTypeId) {
            if (!CreateGameplaySlotStaffItemObject(
                    &source_item,
                    &source_error)) {
                return false;
            }
        } else {
            return false;
        }
        temporary_source_item = true;
    }

    uintptr_t bouncer_address = 0;
    std::string drop_error;
    const bool spawned =
        SpawnNativeRemoteParticipantDeathDrop(
            actor_address,
            source_item,
            source_type,
            &bouncer_address,
            &drop_error);
    if (temporary_source_item) {
        DestroyUnownedNativeItem(
            source_item,
            "remote_death_drop_source");
    }
    if (!spawned) {
        return false;
    }

    binding->native_remote_death_drop_spawned = true;
    Log(
        "[bots] native remote death drop spawned. participant_id=" +
        std::to_string(binding->bot_id) +
        " actor=" + HexString(actor_address) +
        " bouncer=" + HexString(bouncer_address) +
        " item_type=" + std::to_string(source_type));
    return true;
}
