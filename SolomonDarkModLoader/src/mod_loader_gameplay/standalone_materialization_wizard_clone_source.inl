bool SeedWizardCloneSourceActorFromNativeVisualActor(
    uintptr_t source_actor_address,
    uintptr_t native_visual_actor_address,
    float x,
    float y,
    float heading,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (source_actor_address == 0 || native_visual_actor_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Wizard clone-source seeding requires a source actor and native visual actor.";
        }
        return false;
    }

    auto snapshot = CaptureActorRenderBuildSnapshot(native_visual_actor_address);
    const auto descriptor_has_data = std::any_of(
        snapshot.descriptor.begin(),
        snapshot.descriptor.end(),
        [](std::uint8_t value) {
            return value != 0;
        });
    if (!descriptor_has_data) {
        if (error_message != nullptr) {
            *error_message =
                "Native visual actor has no descriptor block available for clone-source seeding.";
        }
        return false;
    }

    // Do not copy a live actor's attachment object pointer into the temporary
    // source actor. FUN_0061AA00 transfers source+0x264 ownership into the new
    // clone, so carrying a pointer from the local actor would steal native
    // player state. Slot bots attach their own staff item after render seeding.
    snapshot.attachment_address = 0;

    std::string restore_error;
    if (!RestoreActorRenderBuildSnapshot(source_actor_address, snapshot, &restore_error)) {
        if (error_message != nullptr) {
            *error_message = std::move(restore_error);
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    if (!memory.TryWriteField(source_actor_address, kActorPositionXOffset, x) ||
        !memory.TryWriteField(source_actor_address, kActorPositionYOffset, y) ||
        !memory.TryWriteField(source_actor_address, kActorHeadingOffset, heading) ||
        !memory.TryWriteField<std::int32_t>(
            source_actor_address,
            kActorHubVisualSourceKindOffset,
            kWizardCloneSourceActorKind) ||
        !memory.TryWriteField<uintptr_t>(
            source_actor_address,
            kActorHubVisualSourceProfileOffset,
            0) ||
        !memory.TryWriteField<uintptr_t>(
            source_actor_address,
            kActorHubVisualSourceAuxPointerOffset,
            0)) {
        if (error_message != nullptr) {
            *error_message = "Failed to seed the temporary clone-source actor from native visual state.";
        }
        return false;
    }

    ApplyActorAnimationDriveState(source_actor_address, false);
    Log(
        "[bots] native clone-source seeded. source_actor=" + HexString(source_actor_address) +
        " native_visual_actor=" + HexString(native_visual_actor_address) +
        " render_selection=" + std::to_string(snapshot.render_selection) +
        " variant_primary=" + std::to_string(snapshot.variant_primary) +
        " variant_secondary=" + std::to_string(snapshot.variant_secondary));
    return true;
}

bool ResolveNativeVisualProgressionRuntime(uintptr_t native_visual_actor_address, uintptr_t* progression_address) {
    if (progression_address != nullptr) {
        *progression_address = 0;
    }
    if (native_visual_actor_address == 0 || progression_address == nullptr) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto direct_runtime =
        memory.ReadFieldOr<uintptr_t>(native_visual_actor_address, kActorProgressionRuntimeStateOffset, 0);
    if (direct_runtime != 0) {
        *progression_address = direct_runtime;
        return true;
    }

    const auto progression_wrapper =
        memory.ReadFieldOr<uintptr_t>(native_visual_actor_address, kActorProgressionHandleOffset, 0);
    const auto progression_inner = ReadSmartPointerInnerObject(progression_wrapper);
    if (progression_inner != 0) {
        *progression_address = progression_inner;
        return true;
    }

    return false;
}

bool RecoverSourceProfileColorFromNativeHelperColor(const float native_color[4], float out_source_color[4]) {
    if (native_color == nullptr || out_source_color == nullptr) {
        return false;
    }
    for (int index = 0; index < 4; ++index) {
        if (!std::isfinite(native_color[index])) {
            return false;
        }
    }

    constexpr float kLumaR = 0.3086f;
    constexpr float kLumaG = 0.6094f;
    constexpr float kLumaB = 0.0820f;
    constexpr float kNativeSourceMix = 0.2f;
    constexpr float kNativeLumaMix = 0.8f;
    const auto grayscale =
        (native_color[0] * kLumaR) + (native_color[1] * kLumaG) + (native_color[2] * kLumaB);
    out_source_color[0] = (native_color[0] - (kNativeLumaMix * grayscale)) / kNativeSourceMix;
    out_source_color[1] = (native_color[1] - (kNativeLumaMix * grayscale)) / kNativeSourceMix;
    out_source_color[2] = (native_color[2] - (kNativeLumaMix * grayscale)) / kNativeSourceMix;
    out_source_color[3] = native_color[3];
    return std::isfinite(out_source_color[0]) &&
        std::isfinite(out_source_color[1]) &&
        std::isfinite(out_source_color[2]) &&
        std::isfinite(out_source_color[3]);
}

bool BuildNativeDerivedWizardSourceProfile(
    uintptr_t native_visual_actor_address,
    const multiplayer::MultiplayerCharacterProfile& character_profile,
    uintptr_t* source_profile_address,
    std::string* error_message) {
    if (source_profile_address != nullptr) {
        *source_profile_address = 0;
    }
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (native_visual_actor_address == 0 || source_profile_address == nullptr) {
        if (error_message != nullptr) {
            *error_message = "Native-derived source profile requires a visual actor and output pointer.";
        }
        return false;
    }

    uintptr_t progression_address = 0;
    if (!ResolveNativeVisualProgressionRuntime(native_visual_actor_address, &progression_address) ||
        progression_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve a native Skills_Wizard runtime for visual color recovery.";
        }
        return false;
    }

    const auto primary_entry = ResolveNativePrimaryEntryForElement(character_profile.element_id);
    if (primary_entry < 0) {
        if (error_message != nullptr) {
            *error_message =
                "Character profile element does not resolve to a native primary entry. element=" +
                std::to_string(character_profile.element_id);
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto get_color_address = memory.ResolveGameAddressOrZero(kSkillsWizardGetPrimaryColor);
    if (get_color_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve Skills_Wizard native primary color seam.";
        }
        return false;
    }

    float native_color[4] = {};
    DWORD exception_code = 0;
    if (!CallSkillsWizardGetPrimaryColorSafe(
            get_color_address,
            progression_address,
            EncodeSkillsWizardSelectionArg(primary_entry),
            native_color,
            &exception_code)) {
        if (error_message != nullptr) {
            *error_message =
                "Skills_Wizard native primary color seam failed with 0x" +
                HexString(exception_code) + ".";
        }
        return false;
    }

    float source_color[4] = {};
    if (!RecoverSourceProfileColorFromNativeHelperColor(native_color, source_color)) {
        if (error_message != nullptr) {
            *error_message = "Native primary color output was not finite.";
        }
        return false;
    }

    auto* buffer = static_cast<std::uint8_t*>(
        _aligned_malloc(kNativeDerivedSourceProfileSize, 16));
    if (buffer == nullptr) {
        if (error_message != nullptr) {
            *error_message = "Unable to allocate native-derived source profile staging buffer.";
        }
        return false;
    }
    std::memset(buffer, 0, kNativeDerivedSourceProfileSize);

    *reinterpret_cast<std::int32_t*>(buffer + kSourceProfileVisualSourceTypeOffset) =
        kWizardCloneSourceActorKind;
    *reinterpret_cast<std::int8_t*>(buffer + kSourceProfileVariantPrimaryOffset) = 1;
    *reinterpret_cast<std::int8_t*>(buffer + kSourceProfileVariantSecondaryOffset) = 1;
    *reinterpret_cast<std::uint8_t*>(buffer + kSourceProfileRenderSelectionOffset) =
        static_cast<std::uint8_t>(ResolveStandaloneWizardRenderSelectionIndex(character_profile.element_id));
    *reinterpret_cast<std::int8_t*>(buffer + kSourceProfileWeaponTypeOffset) = 1;
    *reinterpret_cast<std::uint8_t*>(buffer + kSourceProfileVariantTertiaryOffset) = 0;

    auto write_color = [&](std::size_t offset, const float color[4]) {
        *reinterpret_cast<float*>(buffer + offset + 0x00) = color[0];
        *reinterpret_cast<float*>(buffer + offset + 0x04) = color[1];
        *reinterpret_cast<float*>(buffer + offset + 0x08) = color[2];
        *reinterpret_cast<float*>(buffer + offset + 0x0C) = color[3];
    };
    write_color(kSourceProfileClothColorOffset, source_color);
    const float trim_color[4] = {1.0f, 1.0f, 1.0f, 1.0f};
    write_color(kSourceProfileTrimColorOffset, trim_color);

    *source_profile_address = reinterpret_cast<uintptr_t>(buffer);
    Log(
        "[bots] native-derived source profile. progression=" + HexString(progression_address) +
        " element=" + std::to_string(character_profile.element_id) +
        " primary_entry=" + std::to_string(primary_entry) +
        " native_color=(" + std::to_string(native_color[0]) + ", " +
            std::to_string(native_color[1]) + ", " + std::to_string(native_color[2]) + ")" +
        " source_color=(" + std::to_string(source_color[0]) + ", " +
            std::to_string(source_color[1]) + ", " + std::to_string(source_color[2]) + ")");
    return true;
}

void DestroyNativeDerivedWizardSourceProfile(uintptr_t source_profile_address) {
    if (source_profile_address != 0) {
        _aligned_free(reinterpret_cast<void*>(source_profile_address));
    }
}

bool SeedWizardCloneSourceActorFromNativeDerivedProfile(
    uintptr_t source_actor_address,
    uintptr_t native_visual_actor_address,
    const multiplayer::MultiplayerCharacterProfile& character_profile,
    float x,
    float y,
    float heading,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (source_actor_address == 0 || native_visual_actor_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Native-derived clone-source seeding requires a source actor and native visual actor.";
        }
        return false;
    }

    uintptr_t source_profile_address = 0;
    std::string profile_error;
    if (!BuildNativeDerivedWizardSourceProfile(
            native_visual_actor_address,
            character_profile,
            &source_profile_address,
            &profile_error)) {
        if (error_message != nullptr) {
            *error_message = std::move(profile_error);
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    auto clear_staged_profile = [&]() {
        (void)memory.TryWriteField<uintptr_t>(
            source_actor_address,
            kActorHubVisualSourceProfileOffset,
            0);
        (void)memory.TryWriteField<uintptr_t>(
            source_actor_address,
            kActorHubVisualSourceAuxPointerOffset,
            0);
    };

    if (!memory.TryWriteField(source_actor_address, kActorPositionXOffset, x) ||
        !memory.TryWriteField(source_actor_address, kActorPositionYOffset, y) ||
        !memory.TryWriteField(source_actor_address, kActorHeadingOffset, heading) ||
        !memory.TryWriteField<std::int32_t>(
            source_actor_address,
            kActorHubVisualSourceKindOffset,
            kWizardCloneSourceActorKind) ||
        !memory.TryWriteField<uintptr_t>(
            source_actor_address,
            kActorHubVisualSourceProfileOffset,
            source_profile_address) ||
        !memory.TryWriteField<uintptr_t>(
            source_actor_address,
            kActorHubVisualSourceAuxPointerOffset,
            0)) {
        clear_staged_profile();
        DestroyNativeDerivedWizardSourceProfile(source_profile_address);
        if (error_message != nullptr) {
            *error_message = "Failed to stage the native-derived source profile on the clone-source actor.";
        }
        return false;
    }

    const auto build_descriptor_address =
        memory.ResolveGameAddressOrZero(kActorBuildRenderDescriptorFromSource);
    if (build_descriptor_address == 0) {
        clear_staged_profile();
        DestroyNativeDerivedWizardSourceProfile(source_profile_address);
        if (error_message != nullptr) {
            *error_message = "Unable to resolve ActorBuildRenderDescriptorFromSource.";
        }
        return false;
    }

    DWORD exception_code = 0;
    if (!CallActorBuildRenderDescriptorFromSourceSafe(
            build_descriptor_address,
            source_actor_address,
            &exception_code)) {
        clear_staged_profile();
        DestroyNativeDerivedWizardSourceProfile(source_profile_address);
        if (error_message != nullptr) {
            *error_message =
                "ActorBuildRenderDescriptorFromSource failed for native-derived source profile with 0x" +
                HexString(exception_code) + ".";
        }
        return false;
    }

    clear_staged_profile();
    DestroyNativeDerivedWizardSourceProfile(source_profile_address);
    (void)memory.TryWriteField<std::int32_t>(
        source_actor_address,
        kActorHubVisualSourceKindOffset,
        kWizardCloneSourceActorKind);
    ApplyActorAnimationDriveState(source_actor_address, false);
    Log(
        "[bots] native-derived clone-source seeded. source_actor=" + HexString(source_actor_address) +
        " native_visual_actor=" + HexString(native_visual_actor_address) +
        " element=" + std::to_string(character_profile.element_id) +
        " render_selection=" +
            std::to_string(ResolveStandaloneWizardRenderSelectionIndex(character_profile.element_id)));
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
    uintptr_t native_visual_actor_address,
    const multiplayer::MultiplayerCharacterProfile& character_profile,
    float x,
    float y,
    float heading,
    uintptr_t* source_actor_address,
    std::string* error_message) {
    if (source_actor_address != nullptr) {
        *source_actor_address = 0;
    }
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (world_address == 0 || native_visual_actor_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Wizard clone source creation requires a live world and native visual actor.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto factory_address = memory.ResolveGameAddressOrZero(kGameObjectFactory);
    const auto factory_context_address =
        memory.ResolveGameAddressOrZero(kGameObjectFactoryContextGlobal);
    if (factory_address == 0 || factory_context_address == 0) {
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

    uintptr_t staged_source_actor_address = 0;
    auto cleanup_failed_source = [&](std::string_view failure_message) {
        std::string cleanup_error;
        if (staged_source_actor_address != 0) {
            (void)DestroyWizardCloneSourceActor(staged_source_actor_address, &cleanup_error);
        }
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
        0);
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
        0);

    (void)memory.TryWriteField(staged_source_actor_address, kActorPositionXOffset, x);
    (void)memory.TryWriteField(staged_source_actor_address, kActorPositionYOffset, y);
    (void)memory.TryWriteField(staged_source_actor_address, kActorHeadingOffset, heading);
    LogWizardCloneSourceCreationStage(
        "transform_seeded",
        world_address,
        staged_source_actor_address,
        0);
    ApplyActorAnimationDriveState(staged_source_actor_address, false);
    LogWizardCloneSourceCreationStage(
        "animation_drive_seeded",
        world_address,
        staged_source_actor_address,
        0);

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
        0);

    std::string staging_error;
    LogWizardCloneSourceCreationStage(
        "native_derived_visual_seed_before",
        world_address,
        staged_source_actor_address,
        0);
    if (!SeedWizardCloneSourceActorFromNativeDerivedProfile(
            staged_source_actor_address,
            native_visual_actor_address,
            character_profile,
            x,
            y,
            heading,
            &staging_error)) {
        return cleanup_failed_source(staging_error);
    }
    LogWizardCloneSourceCreationStage(
        "native_derived_visual_seed_after",
        world_address,
        staged_source_actor_address,
        0);

    LogBotVisualDebugStage("clone_source_ready", 0, 0, staged_source_actor_address);
    if (source_actor_address != nullptr) {
        *source_actor_address = staged_source_actor_address;
    }
    return true;
}
