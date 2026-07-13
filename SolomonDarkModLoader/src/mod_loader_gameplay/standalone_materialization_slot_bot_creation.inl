bool WireGameplaySlotBotRuntimeHandles(
    uintptr_t actor_address,
    std::string* error_message) {
    return EnsureWizardActorEquipRuntimeHandles(
        actor_address,
        "gameplay_slot_bot",
        error_message);
}

bool SeedWizardBotNativeCollisionStateFromSourceActor(
    uintptr_t actor_address,
    uintptr_t native_visual_actor_address,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (actor_address == 0 || native_visual_actor_address == 0) {
        if (error_message != nullptr) {
            *error_message =
                "Gameplay-slot collision seeding requires a live bot actor and native visual source.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    float source_radius = 0.0f;
    float source_move_step_scale = 0.0f;
    std::uint32_t source_primary_mask = 0;
    std::uint32_t source_secondary_mask = 0;
    if (!TryReadFiniteFloatField(
            native_visual_actor_address,
            kActorCollisionRadiusOffset,
            &source_radius) ||
        !TryReadFiniteFloatField(
            native_visual_actor_address,
            kActorMoveStepScaleOffset,
            &source_move_step_scale) ||
        !memory.TryReadField(
            native_visual_actor_address,
            kActorPrimaryFlagMaskOffset,
            &source_primary_mask) ||
        !memory.TryReadField(
            native_visual_actor_address,
            kActorSecondaryFlagMaskOffset,
            &source_secondary_mask)) {
        if (error_message != nullptr) {
            *error_message = "Native visual source collision fields are unreadable.";
        }
        return false;
    }
    if (!(source_radius > 0.0f) ||
        !(source_move_step_scale > 0.0f) ||
        source_primary_mask == 0) {
        if (error_message != nullptr) {
            *error_message = "Native visual source collision fields are invalid.";
        }
        return false;
    }

    if (!memory.TryWriteField(
            actor_address,
            kActorCollisionRadiusOffset,
            source_radius) ||
        !memory.TryWriteField(
            actor_address,
            kActorMoveStepScaleOffset,
            source_move_step_scale) ||
        !memory.TryWriteField(
            actor_address,
            kActorPrimaryFlagMaskOffset,
            source_primary_mask) ||
        !memory.TryWriteField(
            actor_address,
            kActorSecondaryFlagMaskOffset,
            source_secondary_mask)) {
        if (error_message != nullptr) {
            *error_message = "Failed to seed wizard bot native collision fields.";
        }
        return false;
    }

    Log(
        "[bots] wizard bot native collision seeded. actor=" + HexString(actor_address) +
        " source=" + HexString(native_visual_actor_address) +
        " radius=" + std::to_string(source_radius) +
        " move_step=" + std::to_string(source_move_step_scale) +
        " mask=" + HexString(source_primary_mask) +
        " mask2=" + HexString(source_secondary_mask));
    return true;
}

bool SeedGameplaySlotBotRenderStateFromSourceActor(
    uintptr_t actor_address,
    uintptr_t world_address,
    uintptr_t native_visual_actor_address,
    std::uint64_t participant_id,
    const multiplayer::MultiplayerCharacterProfile& character_profile,
    float x,
    float y,
    float heading,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (actor_address == 0 || world_address == 0 ||
        native_visual_actor_address == 0 || participant_id == 0) {
        if (error_message != nullptr) {
            *error_message =
                "Gameplay-slot render seeding requires a live actor, world, and native visual source.";
        }
        return false;
    }
    (void)x;
    (void)y;
    (void)heading;

    auto& memory = ProcessMemory::Instance();
    // 0x00461F70 constructs the robe (0x1B5E) and the actor-owned equip
    // runtime's +0x1C lane accepts it. 0x00461ED0 constructs the hat (0x1B5D)
    // and +0x18 accepts it. The local-player inventory audit exposes
    // scene-owned sinks under older primary/secondary labels in the opposite
    // order, so name these constructors for their concrete objects here.
    const auto robe_visual_link_ctor_address =
        memory.ResolveGameAddressOrZero(kStandaloneWizardVisualLinkPrimaryCtor);
    const auto hat_visual_link_ctor_address =
        memory.ResolveGameAddressOrZero(kStandaloneWizardVisualLinkSecondaryCtor);
    if (robe_visual_link_ctor_address == 0 ||
        hat_visual_link_ctor_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the stock helper constructors.";
        }
        return false;
    }

    // A stock 0x1397 actor is a short-lived create-wizard preview, not a safe
    // participant-side descriptor scratch object. The transport already owns
    // the remote player's native robe/hat helper payload, so use that payload
    // as the materialization seed and avoid creating a preview actor at all.
    const auto runtime_state = multiplayer::SnapshotRuntimeState();
    const auto* participant = multiplayer::FindParticipant(runtime_state, participant_id);
    if (participant == nullptr ||
        !multiplayer::IsRemoteParticipant(*participant)) {
        if (error_message != nullptr) {
            *error_message = "Gameplay-slot participant visual state is unavailable.";
        }
        return false;
    }

    ActorRenderBuildSnapshot built_snapshot;
    static_assert(
        multiplayer::kParticipantVisualLinkColorBlockBytes ==
        kActorHubVisualDescriptorBlockSize);
    std::string stage_error;
    if (multiplayer::IsNativeControlledParticipant(*participant)) {
        const bool have_visual_payload =
            (participant->runtime.presentation_flags &
             multiplayer::ParticipantPresentationFlagVisualLinkColorBlocks) != 0 &&
            participant->runtime.primary_visual_link_type_id != 0;
        if (!have_visual_payload) {
            if (error_message != nullptr) {
                *error_message =
                    "Remote participant visual helper payload is not ready.";
            }
            return false;
        }
        std::copy(
            participant->runtime.primary_visual_link_color_block.begin(),
            participant->runtime.primary_visual_link_color_block.end(),
            built_snapshot.descriptor.begin());
        built_snapshot.variant_primary = 1;
        built_snapshot.variant_secondary = 1;
        built_snapshot.weapon_type = 0;
        built_snapshot.render_selection = static_cast<std::uint8_t>(
            ResolveStandaloneWizardRenderSelectionIndex(
                character_profile.element_id));
        built_snapshot.variant_tertiary = 0;
    } else if (multiplayer::IsLuaControlledParticipant(*participant)) {
        if (!SeedWizardCloneSourceActorFromNativeDerivedProfile(
                actor_address,
                native_visual_actor_address,
                character_profile,
                x,
                y,
                heading,
                &stage_error)) {
            if (error_message != nullptr) {
                *error_message = stage_error;
            }
            return false;
        }
        built_snapshot = CaptureActorRenderBuildSnapshot(actor_address);
    } else {
        if (error_message != nullptr) {
            *error_message = "Unsupported gameplay-slot participant controller.";
        }
        return false;
    }

    if (!ApplySourceActorRenderSelectorsToTargetActor(
            actor_address,
            built_snapshot,
            &stage_error)) {
        if (error_message != nullptr) {
            *error_message = stage_error;
        }
        return false;
    }

    const auto& built_descriptor = built_snapshot.descriptor;
    if (!AttachBuiltDescriptorToEquipVisualLane(
            actor_address,
            kActorEquipRuntimeVisualLinkPrimaryOffset,
            robe_visual_link_ctor_address,
            built_descriptor,
            "primary",
            &stage_error) ||
        !AttachBuiltDescriptorToEquipVisualLane(
            actor_address,
            kActorEquipRuntimeVisualLinkSecondaryOffset,
            hat_visual_link_ctor_address,
            built_descriptor,
            "secondary",
            &stage_error)) {
        if (error_message != nullptr) {
            *error_message = stage_error;
        }
        return false;
    }

    if (!AttachGameplaySlotBotStaffItem(actor_address, &stage_error)) {
        if (error_message != nullptr) {
            *error_message = stage_error;
        }
        return false;
    }

    NormalizeGameplaySlotBotSyntheticVisualState(actor_address);
    if constexpr (kEnableWizardBotHotPathDiagnostics) {
        Log(
            "[bots] visual stage=slot_actor_helper_lanes_seeded bot={" +
            BuildActorVisualDebugSummary(actor_address) + "}");
    }
    return true;
}

bool CreateGameplaySlotBotActor(
    uintptr_t gameplay_address,
    uintptr_t world_address,
    int slot_index,
    std::uint64_t participant_id,
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
    uintptr_t slot_actor_address = 0;
    uintptr_t slot_progression_address = 0;
    uintptr_t slot_progression_wrapper_address = 0;
    const bool have_existing_slot_actor =
        TryResolvePlayerActorForSlot(gameplay_address, slot_index, &slot_actor_address) &&
        slot_actor_address != 0;
    const bool have_existing_slot_progression =
        TryResolvePlayerProgressionForSlot(gameplay_address, slot_index, &slot_progression_address) &&
        slot_progression_address != 0;
    const bool have_existing_progression_wrapper =
        TryResolvePlayerProgressionHandleForSlot(
            gameplay_address,
            slot_index,
            &slot_progression_wrapper_address) &&
        slot_progression_wrapper_address != 0;

    if (!have_existing_slot_actor || !have_existing_slot_progression || !have_existing_progression_wrapper) {
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
        if (!TryResolvePlayerProgressionHandleForSlot(
                gameplay_address,
                slot_index,
                &slot_progression_wrapper_address) ||
            slot_progression_wrapper_address == 0) {
            if (error_message != nullptr) {
                *error_message =
                    "Gameplay_CreatePlayerSlot did not publish a slot progression wrapper.";
            }
            return false;
        }
    }

    // Clear stale synthetic markers from older experimental paths before the
    // stock runtime refresh runs, so the slot factory's fresh state isn't
    // shadowed by leftovers from a prior bot in this slot.
    (void)memory.TryWriteField<std::uint32_t>(slot_actor_address, kActorHubVisualSourceKindOffset, 0);
    (void)memory.TryWriteField<uintptr_t>(slot_actor_address, kActorHubVisualSourceProfileOffset, 0);
    (void)memory.TryWriteField<uintptr_t>(slot_actor_address, kActorHubVisualSourceAuxPointerOffset, 0);
    (void)memory.TryWriteField<uintptr_t>(slot_actor_address, kActorHubVisualAttachmentPtrOffset, 0);

    std::string prime_error;
    Log(
        "[bots] create_slot_actor before_prime gameplay=" + HexString(gameplay_address) +
        " slot=" + std::to_string(slot_index) +
        " actor=" + HexString(slot_actor_address) +
        " slot_prog=" + HexString(slot_progression_wrapper_address) +
        " slot_prog_inner=" + HexString(slot_progression_address));
    if (!PrimeGameplaySlotBotActor(
            gameplay_address,
            world_address,
            slot_index,
            slot_actor_address,
            slot_progression_address,
            participant_id,
            character_profile,
            x,
            y,
            heading,
            &prime_error)) {
        if (error_message != nullptr) {
            *error_message = std::move(prime_error);
        }
        return false;
    }

    uintptr_t debug_local_actor = 0;
    (void)memory.TryReadField(gameplay_address, kGameplayPlayerActorOffset, &debug_local_actor);
    LogBotVisualDebugStage(
        "slot_actor_pre_register",
        debug_local_actor,
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
    if (gameplay_address == 0 || world_address == 0 || actor_address == 0 || slot_index < 0) {
        if (error_message != nullptr) {
            *error_message =
                "Gameplay-slot publish requires a live gameplay scene, world, slot index, and actor.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto actor_slot_offset =
        kGameplayPlayerActorOffset + static_cast<std::size_t>(slot_index) * kGameplayPlayerSlotStride;
    const auto progression_slot_offset =
        kGameplayPlayerProgressionHandleOffset + static_cast<std::size_t>(slot_index) * kGameplayPlayerSlotStride;
    uintptr_t published_actor_address = 0;
    uintptr_t published_progression_wrapper = 0;
    if (!memory.TryReadField(gameplay_address, actor_slot_offset, &published_actor_address) ||
        !memory.TryReadField(gameplay_address, progression_slot_offset, &published_progression_wrapper)) {
        if (error_message != nullptr) {
            *error_message = "Gameplay-slot registration could not read stock slot table entries.";
        }
        return false;
    }
    if (published_actor_address != actor_address || published_progression_wrapper == 0) {
        if (error_message != nullptr) {
            *error_message =
                "Gameplay-slot registration requires the stock slot tables to contain the created actor. actor=" +
                HexString(published_actor_address) +
                " progression=" + HexString(published_progression_wrapper);
        }
        return false;
    }

    const auto register_slot_address =
        memory.ResolveGameAddressOrZero(kActorWorldRegisterGameplaySlotActor);
    if (register_slot_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve ActorWorld_RegisterGameplaySlotActor.";
        }
        return false;
    }

    DWORD exception_code = 0;
    if (!CallActorWorldRegisterGameplaySlotActorSafe(
            register_slot_address,
            world_address,
            slot_index,
            &exception_code)) {
        if (error_message != nullptr) {
            *error_message =
                "ActorWorld_RegisterGameplaySlotActor failed with 0x" +
                HexString(exception_code) + ".";
        }
        return false;
    }

    if (binding != nullptr) {
        binding->gameplay_attach_applied = true;
    }
    LogBotVisualDebugStage(
        "finalize_slot_registered",
        world_address,
        actor_address,
        0);
    return true;
}
