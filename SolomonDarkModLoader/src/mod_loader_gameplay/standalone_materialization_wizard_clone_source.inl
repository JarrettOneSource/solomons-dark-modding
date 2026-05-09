bool ResolveNativeVisualProgressionRuntime(uintptr_t native_visual_actor_address, uintptr_t* progression_address) {
    if (progression_address != nullptr) {
        *progression_address = 0;
    }
    if (native_visual_actor_address == 0 || progression_address == nullptr) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t direct_runtime = 0;
    if (!memory.TryReadField(
            native_visual_actor_address,
            kActorProgressionRuntimeStateOffset,
            &direct_runtime)) {
        return false;
    }
    if (direct_runtime != 0) {
        *progression_address = direct_runtime;
        return true;
    }

    uintptr_t progression_wrapper = 0;
    if (!memory.TryReadField(
            native_visual_actor_address,
            kActorProgressionHandleOffset,
            &progression_wrapper)) {
        return false;
    }
    const auto progression_inner = ReadSmartPointerInnerObject(progression_wrapper);
    if (progression_inner != 0) {
        *progression_address = progression_inner;
        return true;
    }

    return false;
}

bool IsFiniteColorPayload(const float color[4]) {
    if (color == nullptr) {
        return false;
    }
    for (int index = 0; index < 4; ++index) {
        if (!std::isfinite(color[index])) {
            return false;
        }
    }
    return true;
}

bool TryWriteSourceProfileColor(
    std::uint8_t* buffer,
    std::size_t offset,
    const float color[4]) {
    if (buffer == nullptr || !IsFiniteColorPayload(color)) {
        return false;
    }
    for (int index = 0; index < 4; ++index) {
        *reinterpret_cast<float*>(
            buffer + offset + sizeof(float) * index) = color[index];
    }
    return true;
}

bool TryReadNativeSourceActorDefaultTrimColor(
    uintptr_t source_actor_address,
    float out_color[4]) {
    if (source_actor_address == 0 || out_color == nullptr) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    if (!memory.TryRead(
            source_actor_address + kActorHubVisualDescriptorBlockOffset + sizeof(float) * 4,
            out_color,
            sizeof(float) * 4)) {
        return false;
    }
    return IsFiniteColorPayload(out_color) && out_color[3] > 0.0f;
}

bool TryBuildSourceProfileColorPreimage(
    const float native_descriptor_color[4],
    float out_source_profile_color[4]) {
    if (!IsFiniteColorPayload(native_descriptor_color) ||
        out_source_profile_color == nullptr) {
        return false;
    }

    // 0x005E3080 feeds source-profile color through 0x0040FC60 before helper
    // publication. 0x0040FC60 applies the stock robe mix:
    //     out = 0.2 * source + 0.8 * luminance(source)
    // with 0.3086/0.6094/0.0820 channel weights. Those weights sum to one, so
    // the preimage is source = 5 * target - 4 * luminance(target).
    const float luminance =
        0.3086f * native_descriptor_color[0] +
        0.6094f * native_descriptor_color[1] +
        0.0820f * native_descriptor_color[2];
    for (int index = 0; index < 3; ++index) {
        out_source_profile_color[index] =
            native_descriptor_color[index] * 5.0f - luminance * 4.0f;
    }
    out_source_profile_color[3] = native_descriptor_color[3];
    return IsFiniteColorPayload(out_source_profile_color);
}

bool BuildNativeDerivedWizardSourceProfile(
    uintptr_t source_actor_address,
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
    if (source_actor_address == 0 ||
        native_visual_actor_address == 0 ||
        source_profile_address == nullptr) {
        if (error_message != nullptr) {
            *error_message =
                "Native-derived source profile requires a source actor, visual actor, and output pointer.";
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

    float native_element_color[4] = {};
    DWORD exception_code = 0;
    if (!CallSkillsWizardGetPrimaryColorSafe(
            get_color_address,
            progression_address,
            EncodeSkillsWizardSelectionArg(primary_entry),
            native_element_color,
            &exception_code)) {
        if (error_message != nullptr) {
            *error_message =
                "Skills_Wizard native primary color seam failed with 0x" +
                HexString(exception_code) + ".";
        }
        return false;
    }

    if (!IsFiniteColorPayload(native_element_color)) {
        if (error_message != nullptr) {
            *error_message = "Native source-profile color output was not finite.";
        }
        return false;
    }

    float source_profile_cloth_color[4] = {};
    if (!TryBuildSourceProfileColorPreimage(
            native_element_color,
            source_profile_cloth_color)) {
        if (error_message != nullptr) {
            *error_message = "Native descriptor color could not be converted to source-profile color.";
        }
        return false;
    }

    float native_default_trim_color[4] = {};
    if (!TryReadNativeSourceActorDefaultTrimColor(
            source_actor_address,
            native_default_trim_color)) {
        if (error_message != nullptr) {
            *error_message = "Native source actor default trim color was unavailable.";
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

    if (!TryWriteSourceProfileColor(buffer, kSourceProfileClothColorOffset, source_profile_cloth_color) ||
        !TryWriteSourceProfileColor(buffer, kSourceProfileTrimColorOffset, native_default_trim_color)) {
        _aligned_free(buffer);
        if (error_message != nullptr) {
            *error_message = "Native-derived source profile color payload was not finite.";
        }
        return false;
    }

    *source_profile_address = reinterpret_cast<uintptr_t>(buffer);
    Log(
        "[bots] native-derived source profile. progression=" + HexString(progression_address) +
        " element=" + std::to_string(character_profile.element_id) +
        " primary_entry=" + std::to_string(primary_entry) +
        " native_color=(" + std::to_string(native_element_color[0]) + ", " +
            std::to_string(native_element_color[1]) + ", " +
            std::to_string(native_element_color[2]) + ")" +
        " source_profile_cloth=(" + std::to_string(source_profile_cloth_color[0]) + ", " +
            std::to_string(source_profile_cloth_color[1]) + ", " +
            std::to_string(source_profile_cloth_color[2]) + ")" +
        " native_trim=(" + std::to_string(native_default_trim_color[0]) + ", " +
            std::to_string(native_default_trim_color[1]) + ", " +
            std::to_string(native_default_trim_color[2]) + ")");
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
            source_actor_address,
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
    uintptr_t live_world_address = 0;
    if (!memory.TryReadField(actor_address, kActorOwnerOffset, &live_world_address)) {
        if (error_message != nullptr) {
            *error_message = "Clone-source cleanup could not read actor world owner.";
        }
        return false;
    }
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
