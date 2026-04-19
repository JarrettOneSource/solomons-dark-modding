bool WireGameplaySlotBotRuntimeHandles(
    uintptr_t actor_address,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (actor_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Gameplay slot runtime handle wiring is missing the actor address.";
        }
        return false;
    }

    uintptr_t equip_wrapper_address = 0;
    uintptr_t equip_inner_address = 0;
    std::string equip_error;
    if (!CreateStandaloneWizardEquipWrapper(
            &equip_wrapper_address,
            &equip_inner_address,
            &equip_error)) {
        if (error_message != nullptr) {
            *error_message = equip_error;
        }
        return false;
    }

    DWORD exception_code = 0;
    if (!AssignActorSmartPointerWrapperSafe(
            actor_address,
            kActorEquipHandleOffset,
            kActorEquipRuntimeStateOffset,
            equip_wrapper_address,
            &exception_code)) {
        ReleaseStandaloneWizardSmartPointerResource(
            actor_address,
            kActorEquipHandleOffset,
            kActorEquipRuntimeStateOffset,
            equip_wrapper_address,
            equip_inner_address,
            "equip");
        if (error_message != nullptr) {
            *error_message = "Assigning the equip handle failed with 0x" + HexString(exception_code) + ".";
        }
        return false;
    }

    return true;
}

bool SeedGameplaySlotBotRenderStateFromSourceActor(
    uintptr_t actor_address,
    uintptr_t world_address,
    const multiplayer::MultiplayerCharacterProfile& character_profile,
    float x,
    float y,
    float heading,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (actor_address == 0 || world_address == 0) {
        if (error_message != nullptr) {
            *error_message =
                "Gameplay-slot render seeding requires a live actor and world.";
        }
        return false;
    }

    ClearActorLiveDescriptorBlock(actor_address);

    auto& memory = ProcessMemory::Instance();
    const auto primary_visual_link_ctor_address =
        memory.ResolveGameAddressOrZero(kStandaloneWizardVisualLinkPrimaryCtor);
    const auto secondary_visual_link_ctor_address =
        memory.ResolveGameAddressOrZero(kStandaloneWizardVisualLinkSecondaryCtor);
    if (primary_visual_link_ctor_address == 0 ||
        secondary_visual_link_ctor_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the stock helper constructors.";
        }
        return false;
    }

    uintptr_t source_actor_address = 0;
    uintptr_t source_profile_address = 0;
    std::string stage_error;
    if (!CreateWizardCloneSourceActor(
            world_address,
            character_profile,
            x,
            y,
            heading,
            &source_actor_address,
            &source_profile_address,
            &stage_error)) {
        if (error_message != nullptr) {
            *error_message = std::move(stage_error);
        }
        return false;
    }

    auto cleanup_source = [&]() {
        std::string cleanup_error;
        if (source_actor_address != 0) {
            (void)DestroyWizardCloneSourceActor(source_actor_address, &cleanup_error);
        }
        if (source_profile_address != 0) {
            DestroySyntheticWizardSourceProfile(source_profile_address);
        }
        if (!cleanup_error.empty()) {
            Log("[bots] source actor cleanup detail: " + cleanup_error);
        }
    };

    constexpr bool kKeepSourceActorAliveDiagnostic = false;

    auto built_snapshot = CaptureActorRenderBuildSnapshot(source_actor_address);

    const auto& built_descriptor = built_snapshot.descriptor;
    if (!AttachBuiltDescriptorToEquipVisualLane(
            actor_address,
            kActorEquipRuntimeVisualLinkPrimaryOffset,
            primary_visual_link_ctor_address,
            built_descriptor,
            "primary",
            &stage_error) ||
        !AttachBuiltDescriptorToEquipVisualLane(
            actor_address,
            kActorEquipRuntimeVisualLinkSecondaryOffset,
            secondary_visual_link_ctor_address,
            built_descriptor,
            "secondary",
            &stage_error)) {
        cleanup_source();
        if (error_message != nullptr) {
            *error_message = stage_error;
        }
        return false;
    }

    if constexpr (kKeepSourceActorAliveDiagnostic) {
        if (source_actor_address != 0) {
            (void)memory.TryWriteField(source_actor_address, kActorPositionXOffset, 100000.0f);
            (void)memory.TryWriteField(source_actor_address, kActorPositionYOffset, 100000.0f);
            Log("[bots] source actor diagnostic park. actor=" + HexString(source_actor_address));
        }
    } else {
        cleanup_source();
    }
    NormalizeGameplaySlotBotSyntheticVisualState(actor_address);
    Log(
        "[bots] visual stage=slot_actor_helper_lanes_seeded bot={" +
        BuildActorVisualDebugSummary(actor_address) + "}");
    return true;
}

bool AttachGameplaySlotBotStaffItem(
    uintptr_t actor_address,
    std::string* error_message) {
    uintptr_t staff_item_address = 0;
    std::string stage_error;
    if (!CreateGameplaySlotStaffItemObject(&staff_item_address, &stage_error) ||
        !SetEquipVisualLaneObject(
            actor_address,
            kActorEquipRuntimeVisualLinkAttachmentOffset,
            staff_item_address,
            "attachment",
            &stage_error)) {
        if (staff_item_address != 0) {
            DWORD destroy_exception_code = 0;
            (void)CallScalarDeletingDestructorSafe(
                staff_item_address,
                1,
                &destroy_exception_code);
        }
        if (error_message != nullptr) {
            *error_message = stage_error;
        }
        return false;
    }

    Log(
        "[bots] visual stage=slot_actor_staff_attached bot={" +
        BuildActorVisualDebugSummary(actor_address) + "}");
    return true;
}

bool CreateGameplaySlotBotActor(
    uintptr_t gameplay_address,
    uintptr_t world_address,
    int slot_index,
    const multiplayer::MultiplayerCharacterProfile& character_profile,
    float x,
    float y,
    float heading,
    uintptr_t* actor_address,
    uintptr_t* progression_address,
    std::string* error_message) {
    if (actor_address != nullptr) {
        *actor_address = 0;
    }
    if (progression_address != nullptr) {
        *progression_address = 0;
    }
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (gameplay_address == 0 || world_address == 0 || slot_index < 0) {
        if (error_message != nullptr) {
            *error_message =
                "Gameplay-slot bot creation requires a live gameplay scene, world, and slot index.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    (void)world_address;
    uintptr_t slot_actor_address = 0;
    uintptr_t slot_progression_address = 0;
    const bool have_existing_slot_actor =
        TryResolvePlayerActorForSlot(gameplay_address, slot_index, &slot_actor_address) &&
        slot_actor_address != 0;
    const bool have_existing_slot_progression =
        TryResolvePlayerProgressionForSlot(gameplay_address, slot_index, &slot_progression_address) &&
        slot_progression_address != 0;

    if (!have_existing_slot_actor || !have_existing_slot_progression) {
        const auto create_slot_address = memory.ResolveGameAddressOrZero(kGameplayCreatePlayerSlot);
        if (create_slot_address == 0) {
            if (error_message != nullptr) {
                *error_message = "Unable to resolve Gameplay_CreatePlayerSlot.";
            }
            return false;
        }

        DWORD exception_code = 0;
        if (!CallGameplayCreatePlayerSlotSafe(
                create_slot_address,
                gameplay_address,
                slot_index,
                &exception_code)) {
            if (error_message != nullptr) {
                *error_message =
                    "Gameplay_CreatePlayerSlot failed with 0x" + HexString(exception_code) + ".";
            }
            return false;
        }

        if (!TryResolvePlayerActorForSlot(gameplay_address, slot_index, &slot_actor_address) ||
            slot_actor_address == 0) {
            if (error_message != nullptr) {
                *error_message =
                    "Gameplay_CreatePlayerSlot did not publish a slot actor.";
            }
            return false;
        }
        if (!TryResolvePlayerProgressionForSlot(gameplay_address, slot_index, &slot_progression_address) ||
            slot_progression_address == 0) {
            if (error_message != nullptr) {
                *error_message =
                    "Gameplay_CreatePlayerSlot did not publish a slot progression object.";
            }
            return false;
        }
    }

    PrimeGameplaySlotBotActor(
        gameplay_address,
        slot_index,
        slot_actor_address,
        slot_progression_address,
        x,
        y,
        heading);

    std::string stage_error;

    // Keep gameplay-slot actors on the stock slot contract. Only clear stale
    // synthetic source markers from older experiments; preserve whatever stock
    // runtime/equip state the slot factory already established.
    (void)memory.TryWriteField<std::uint32_t>(slot_actor_address, kActorHubVisualSourceKindOffset, 0);
    (void)memory.TryWriteField<uintptr_t>(slot_actor_address, kActorHubVisualSourceProfileOffset, 0);
    (void)memory.TryWriteField<uintptr_t>(slot_actor_address, kActorHubVisualSourceAuxPointerOffset, 0);
    (void)memory.TryWriteField<uintptr_t>(slot_actor_address, kActorHubVisualAttachmentPtrOffset, 0);

    LogBotVisualDebugStage(
        "slot_actor_pre_register",
        memory.ReadFieldOr<uintptr_t>(gameplay_address, kGameplayPlayerActorOffset, 0),
        slot_actor_address,
        0);

    if (actor_address != nullptr) {
        *actor_address = slot_actor_address;
    }
    if (progression_address != nullptr) {
        *progression_address = slot_progression_address;
    }
    return true;
}

bool FinalizeGameplaySlotBotRegistration(
    uintptr_t gameplay_address,
    uintptr_t world_address,
    int slot_index,
    uintptr_t actor_address,
    ParticipantEntityBinding* binding,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (gameplay_address == 0 || actor_address == 0 || slot_index < 0) {
        if (error_message != nullptr) {
            *error_message =
                "Gameplay-slot publish requires a live gameplay scene, slot index, and actor.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto actor_slot_offset =
        kGameplayPlayerActorOffset + static_cast<std::size_t>(slot_index) * kGameplayPlayerSlotStride;
    const auto progression_slot_offset =
        kGameplayPlayerProgressionHandleOffset + static_cast<std::size_t>(slot_index) * kGameplayPlayerSlotStride;
    const auto published_actor_address =
        memory.ReadFieldOr<uintptr_t>(gameplay_address, actor_slot_offset, 0);
    const auto published_progression_wrapper =
        memory.ReadFieldOr<uintptr_t>(gameplay_address, progression_slot_offset, 0);
    if (published_actor_address != actor_address || published_progression_wrapper == 0) {
        if (error_message != nullptr) {
            *error_message =
                "Gameplay-slot registration requires the stock slot tables to contain the created actor. actor=" +
                HexString(published_actor_address) +
                " progression=" + HexString(published_progression_wrapper);
        }
        return false;
    }

    if (binding != nullptr) {
        binding->gameplay_attach_applied = false;
    }
    LogBotVisualDebugStage(
        "finalize_slot_table_only",
        0,
        actor_address,
        0);
    return true;
}
