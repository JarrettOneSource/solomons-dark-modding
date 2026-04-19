bool StageWizardCloneSourceProfileOnActor(
    uintptr_t actor_address,
    uintptr_t source_profile_address,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (actor_address == 0 || source_profile_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Wizard clone source staging requires a live actor and source profile.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    if (!memory.TryWriteField<std::int32_t>(
            actor_address,
            kActorHubVisualSourceKindOffset,
            kStandaloneWizardVisualSourceKind) ||
        !memory.TryWriteField<uintptr_t>(
            actor_address,
            kActorHubVisualSourceProfileOffset,
            source_profile_address) ||
        !memory.TryWriteField<uintptr_t>(
            actor_address,
            kActorHubVisualSourceAuxPointerOffset,
            source_profile_address + kSourceProfileAuxPointerTargetOffset)) {
        if (error_message != nullptr) {
            *error_message = "Failed to stage the wizard source-profile fields on the temporary source actor.";
        }
        return false;
    }

    return true;
}

bool DestroyWizardCloneSourceActor(uintptr_t actor_address, std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (actor_address == 0) {
        return true;
    }

    auto& memory = ProcessMemory::Instance();
    const auto live_world_address =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, 0);
    bool unregistered_from_world = false;
    if (live_world_address != 0) {
        const auto unregister_address = memory.ResolveGameAddressOrZero(kActorWorldUnregister);
        if (unregister_address == 0) {
            if (error_message != nullptr) {
                *error_message = "Unable to resolve ActorWorld_Unregister for clone-source cleanup.";
            }
            return false;
        }

        DWORD exception_code = 0;
        if (!CallActorWorldUnregisterSafe(
                unregister_address,
                live_world_address,
                actor_address,
                1,
                &exception_code)) {
            if (error_message != nullptr) {
                *error_message =
                    "Clone-source ActorWorld_Unregister failed with 0x" +
                    HexString(exception_code) + ".";
            }
            return false;
        }

        unregistered_from_world = true;
    }

    // Factory-created source actors are world-owned once registered. On the
    // live build, following ActorWorld_Unregister with Object_Delete causes an
    // execute AV during temporary source cleanup after the attachment object
    // has been transferred. Treat unregister as the terminal owner transition
    // for registered source actors.
    if (unregistered_from_world) {
        return true;
    }

    const auto object_delete_address = memory.ResolveGameAddressOrZero(kObjectDelete);
    if (object_delete_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve Object_Delete for clone-source cleanup.";
        }
        return false;
    }

    DWORD exception_code = 0;
    if (!CallObjectDeleteSafe(object_delete_address, actor_address, &exception_code)) {
        if (error_message != nullptr) {
            *error_message =
                "Clone-source Object_Delete failed with 0x" + HexString(exception_code) + ".";
        }
        return false;
    }

    return true;
}

bool DestroyRegisteredGameNpcActor(
    uintptr_t actor_address,
    uintptr_t world_address,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (actor_address == 0) {
        return true;
    }

    auto& memory = ProcessMemory::Instance();
    const auto live_world_address =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, 0);
    if (live_world_address != 0) {
        world_address = live_world_address;
    }

    if (world_address != 0) {
        const auto unregister_address = memory.ResolveGameAddressOrZero(kActorWorldUnregister);
        if (unregister_address == 0) {
            if (error_message != nullptr) {
                *error_message =
                    "Unable to resolve ActorWorld_Unregister for registered GameNpc cleanup.";
            }
            return false;
        }

        DWORD exception_code = 0;
        if (!CallActorWorldUnregisterSafe(
                unregister_address,
                world_address,
                actor_address,
                1,
                &exception_code)) {
            if (error_message != nullptr) {
                *error_message =
                    "Registered GameNpc ActorWorld_Unregister failed with 0x" +
                    HexString(exception_code) + ".";
            }
            return false;
        }
    }

    const auto object_delete_address = memory.ResolveGameAddressOrZero(kObjectDelete);
    if (object_delete_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve Object_Delete for registered GameNpc cleanup.";
        }
        return false;
    }

    DWORD exception_code = 0;
    if (!CallObjectDeleteSafe(object_delete_address, actor_address, &exception_code)) {
        if (error_message != nullptr) {
            *error_message =
                "Registered GameNpc Object_Delete failed with 0x" +
                HexString(exception_code) + ".";
        }
        return false;
    }

    return true;
}

bool ApplySourceActorRenderSnapshotToTargetActor(
    uintptr_t target_actor_address,
    uintptr_t source_actor_address,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (target_actor_address == 0 || source_actor_address == 0) {
        if (error_message != nullptr) {
            *error_message =
                "Source-actor render snapshot application requires both the target actor and built source actor.";
        }
        return false;
    }

    constexpr std::size_t kActorSourceProfileUnknown74MirrorOffset = 0x194;
    constexpr std::size_t kActorSourceProfileUnknown56MirrorOffset = 0x1C0;

    auto& memory = ProcessMemory::Instance();
    std::array<std::uint8_t, kActorHubVisualDescriptorBlockSize> source_descriptor{};
    if (!memory.TryRead(
            source_actor_address + kActorHubVisualDescriptorBlockOffset,
            source_descriptor.data(),
            source_descriptor.size())) {
        if (error_message != nullptr) {
            *error_message = "Failed to read the built source actor descriptor block.";
        }
        return false;
    }

    const auto source_variant_primary =
        memory.ReadFieldOr<std::uint8_t>(source_actor_address, kActorRenderVariantPrimaryOffset, 0);
    const auto source_variant_secondary =
        memory.ReadFieldOr<std::uint8_t>(source_actor_address, kActorRenderVariantSecondaryOffset, 0);
    const auto source_variant_tertiary =
        memory.ReadFieldOr<std::uint8_t>(source_actor_address, kActorRenderVariantTertiaryOffset, 0);
    const auto source_unknown74_mirror =
        memory.ReadFieldOr<std::uint32_t>(source_actor_address, kActorSourceProfileUnknown74MirrorOffset, 0);
    const auto source_unknown56_mirror =
        memory.ReadFieldOr<std::uint16_t>(source_actor_address, kActorSourceProfileUnknown56MirrorOffset, 0);

    const auto equip_runtime_state_address =
        memory.ReadFieldOr<uintptr_t>(target_actor_address, kActorEquipRuntimeStateOffset, 0);
    uintptr_t attachment_lane_object_address = 0;
    if (equip_runtime_state_address != 0) {
        attachment_lane_object_address = ReadEquipVisualLaneState(
            equip_runtime_state_address,
            kActorEquipRuntimeVisualLinkAttachmentOffset).current_object_address;
    }
    const auto actor_attachment_address =
        memory.ReadFieldOr<uintptr_t>(target_actor_address, kActorHubVisualAttachmentPtrOffset, 0);

    if (!memory.TryWriteValue(
            target_actor_address + kActorSourceProfileUnknown74MirrorOffset,
            source_unknown74_mirror) ||
        !memory.TryWriteValue(
            target_actor_address + kActorSourceProfileUnknown56MirrorOffset,
            source_unknown56_mirror) ||
        !memory.TryWriteField(
            target_actor_address,
            kActorRenderVariantPrimaryOffset,
            source_variant_primary) ||
        !memory.TryWriteField(
            target_actor_address,
            kActorRenderVariantSecondaryOffset,
            source_variant_secondary) ||
        !memory.TryWriteField(
            target_actor_address,
            kActorRenderWeaponTypeOffset,
            static_cast<std::uint8_t>(0)) ||
        !memory.TryWriteField(
            target_actor_address,
            kActorRenderVariantTertiaryOffset,
            source_variant_tertiary) ||
        !memory.TryWriteField(
            target_actor_address,
            kActorRenderSelectionByteOffset,
            static_cast<std::uint8_t>(0)) ||
        !memory.TryWrite(
            target_actor_address + kActorHubVisualDescriptorBlockOffset,
            source_descriptor.data(),
            source_descriptor.size())) {
        if (error_message != nullptr) {
            *error_message = "Failed to mirror the built wizard render window onto the target actor.";
        }
        return false;
    }

    if (actor_attachment_address != 0 &&
        actor_attachment_address != attachment_lane_object_address) {
        Log(
            "[bots] source render snapshot: clearing target actor attachment staging pointer. actor=" +
            HexString(target_actor_address) +
            " actor_attachment=" + HexString(actor_attachment_address) +
            " attachment_lane=" + HexString(attachment_lane_object_address));
    }

    if (!memory.TryWriteField<uintptr_t>(
            target_actor_address,
            kActorHubVisualAttachmentPtrOffset,
            0)) {
        if (error_message != nullptr) {
            *error_message = "Failed to clear the target actor attachment pointer after render snapshot application.";
        }
        return false;
    }

    return true;
}

bool CreateWizardCloneSourceActor(
    uintptr_t world_address,
    const multiplayer::MultiplayerCharacterProfile& character_profile,
    float x,
    float y,
    float heading,
    uintptr_t* source_actor_address,
    uintptr_t* source_profile_address,
    std::string* error_message) {
    if (source_actor_address != nullptr) {
        *source_actor_address = 0;
    }
    if (source_profile_address != nullptr) {
        *source_profile_address = 0;
    }
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (world_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Wizard clone source creation requires a live world address.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto factory_address = memory.ResolveGameAddressOrZero(kGameObjectFactory);
    const auto factory_context_address =
        memory.ResolveGameAddressOrZero(kGameObjectFactoryContextGlobal);
    const auto build_descriptor_address =
        memory.ResolveGameAddressOrZero(kActorBuildRenderDescriptorFromSource);
    if (factory_address == 0 ||
        factory_context_address == 0 ||
        build_descriptor_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the stock wizard clone source entrypoints.";
        }
        return false;
    }

    LogWizardCloneSourceCreationStage(
        "entrypoints_resolved",
        world_address,
        0,
        0);

    uintptr_t staged_source_profile_address = CreateSyntheticWizardSourceProfile(character_profile);
    if (staged_source_profile_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Wizard clone source-profile allocation failed.";
        }
        return false;
    }
    LogWizardCloneSourceCreationStage(
        "source_profile_created",
        world_address,
        0,
        staged_source_profile_address);

    uintptr_t staged_source_actor_address = 0;
    auto cleanup_failed_source = [&](std::string_view failure_message) {
        std::string cleanup_error;
        if (staged_source_actor_address != 0) {
            (void)DestroyWizardCloneSourceActor(staged_source_actor_address, &cleanup_error);
        }
        DestroySyntheticWizardSourceProfile(staged_source_profile_address);
        staged_source_profile_address = 0;
        if (error_message != nullptr) {
            *error_message = std::string(failure_message);
            if (!cleanup_error.empty()) {
                *error_message += " cleanup=" + cleanup_error;
            }
        }
        return false;
    };

    DWORD exception_code = 0;
    LogWizardCloneSourceCreationStage(
        "factory_call_before",
        world_address,
        0,
        staged_source_profile_address);
    if (!CallGameObjectFactorySafe(
            factory_address,
            factory_context_address,
            kWizardSourceActorFactoryTypeId,
            &staged_source_actor_address,
            &exception_code) ||
        staged_source_actor_address == 0) {
        return cleanup_failed_source(
            "Wizard clone source actor factory failed with 0x" + HexString(exception_code) + ".");
    }
    LogWizardCloneSourceCreationStage(
        "factory_call_after",
        world_address,
        staged_source_actor_address,
        staged_source_profile_address);

    (void)memory.TryWriteField(staged_source_actor_address, kActorPositionXOffset, x);
    (void)memory.TryWriteField(staged_source_actor_address, kActorPositionYOffset, y);
    (void)memory.TryWriteField(staged_source_actor_address, kActorHeadingOffset, heading);
    LogWizardCloneSourceCreationStage(
        "transform_seeded",
        world_address,
        staged_source_actor_address,
        staged_source_profile_address);
    ApplyActorAnimationDriveState(staged_source_actor_address, false);
    LogWizardCloneSourceCreationStage(
        "animation_drive_seeded",
        world_address,
        staged_source_actor_address,
        staged_source_profile_address);

    std::string staging_error;
    if (!StageWizardCloneSourceProfileOnActor(
            staged_source_actor_address,
            staged_source_profile_address,
            &staging_error)) {
        return cleanup_failed_source(staging_error);
    }
    LogWizardCloneSourceCreationStage(
        "source_profile_staged",
        world_address,
        staged_source_actor_address,
        staged_source_profile_address);

    const auto actor_world_register_address =
        memory.ResolveGameAddressOrZero(kActorWorldRegister);
    if (actor_world_register_address == 0) {
        return cleanup_failed_source("Wizard clone source register entrypoint is unavailable.");
    }

    exception_code = 0;
    if (!CallActorWorldRegisterSafe(
            actor_world_register_address,
            world_address,
            0,
            staged_source_actor_address,
            -1,
            0,
            &exception_code)) {
        return cleanup_failed_source(
            "Wizard clone source world register failed with 0x" + HexString(exception_code) + ".");
    }
    LogWizardCloneSourceCreationStage(
        "source_world_registered",
        world_address,
        staged_source_actor_address,
        staged_source_profile_address);

    exception_code = 0;
    LogWizardCloneSourceCreationStage(
        "descriptor_build_before",
        world_address,
        staged_source_actor_address,
        staged_source_profile_address);
    if (!CallActorBuildRenderDescriptorFromSourceSafe(
            build_descriptor_address,
            staged_source_actor_address,
            &exception_code)) {
        return cleanup_failed_source(
            "Wizard clone source descriptor build failed with 0x" + HexString(exception_code) + ".");
    }
    LogWizardCloneSourceCreationStage(
        "descriptor_build_after",
        world_address,
        staged_source_actor_address,
        staged_source_profile_address);

    LogBotVisualDebugStage("clone_source_ready", 0, 0, staged_source_actor_address);
    if (source_actor_address != nullptr) {
        *source_actor_address = staged_source_actor_address;
    }
    if (source_profile_address != nullptr) {
        *source_profile_address = staged_source_profile_address;
    }
    return true;
}
