void AppendSourceProfileDebugSummary(
    std::ostringstream* out,
    uintptr_t source_profile_address) {
    if (out == nullptr || source_profile_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    *out << " source_profile=" << HexString(source_profile_address)
         << " src_selectors="
         << std::to_string(memory.ReadValueOr<std::uint8_t>(
                source_profile_address + kSourceProfileVariantPrimaryOffset,
                0xFF))
         << "/"
         << std::to_string(memory.ReadValueOr<std::uint8_t>(
                source_profile_address + kSourceProfileVariantSecondaryOffset,
                0xFF))
         << "/"
         << std::to_string(memory.ReadValueOr<std::uint8_t>(
                source_profile_address + kSourceProfileWeaponTypeOffset,
                0xFF))
         << "/"
         << std::to_string(memory.ReadValueOr<std::uint8_t>(
                source_profile_address + kSourceProfileVariantTertiaryOffset,
                0xFF))
         << "/"
         << std::to_string(memory.ReadValueOr<std::uint8_t>(
                source_profile_address + kSourceProfileRenderSelectionOffset,
                0xFF))
         << " cloth="
         << std::to_string(memory.ReadValueOr<float>(
                source_profile_address + kSourceProfileClothColorOffset + 0x00,
                0.0f))
         << ","
         << std::to_string(memory.ReadValueOr<float>(
                source_profile_address + kSourceProfileClothColorOffset + 0x04,
                0.0f))
         << ","
         << std::to_string(memory.ReadValueOr<float>(
                source_profile_address + kSourceProfileClothColorOffset + 0x08,
                0.0f))
         << " trim="
         << std::to_string(memory.ReadValueOr<float>(
                source_profile_address + kSourceProfileTrimColorOffset + 0x00,
                0.0f))
         << ","
         << std::to_string(memory.ReadValueOr<float>(
                source_profile_address + kSourceProfileTrimColorOffset + 0x04,
                0.0f))
         << ","
         << std::to_string(memory.ReadValueOr<float>(
                source_profile_address + kSourceProfileTrimColorOffset + 0x08,
                0.0f));
}

std::string FormatDebugBytes(const std::uint8_t* bytes, size_t size) {
    if (bytes == nullptr || size == 0) {
        return "<empty>";
    }

    std::ostringstream out;
    out << std::uppercase << std::hex << std::setfill('0');
    for (size_t index = 0; index < size; ++index) {
        if (index != 0) {
            out << ' ';
        }
        out << std::setw(2) << static_cast<unsigned int>(bytes[index]);
    }
    return out.str();
}

void AppendAttachmentObjectDebugSummary(
    std::ostringstream* out,
    std::string_view label,
    uintptr_t object_address) {
    if (out == nullptr || object_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    std::uint8_t bytes[64] = {};
    const bool have_bytes = memory.TryRead(object_address, bytes, sizeof(bytes));
    const auto field_04 = memory.ReadFieldOr<std::uint32_t>(object_address, 0x04, 0);
    const auto field_0c = memory.ReadFieldOr<std::uint32_t>(object_address, 0x0C, 0);
    const auto field_14 = memory.ReadFieldOr<std::uint32_t>(object_address, 0x14, 0);

    *out << " " << label
         << "{addr=" << HexString(object_address)
         << " +04=0x" << HexString(static_cast<uintptr_t>(field_04))
         << " +0C=0x" << HexString(static_cast<uintptr_t>(field_0c))
         << " +14=0x" << HexString(static_cast<uintptr_t>(field_14));
    if (have_bytes) {
        *out << " head=" << FormatDebugBytes(bytes, sizeof(bytes));
    }
    *out << "}";
}

std::string BuildActorVisualDebugSummary(uintptr_t actor_address) {
    std::ostringstream out;
    out << "actor=" << HexString(actor_address);
    if (actor_address == 0) {
        return out.str();
    }

    auto& memory = ProcessMemory::Instance();
    const auto equip_runtime_state_address =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorEquipRuntimeStateOffset, 0);
    const auto source_profile_address =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorHubVisualSourceProfileOffset, 0);

    out << " ctx=" << HexString(memory.ReadFieldOr<uintptr_t>(actor_address, 0x04, 0))
        << " world=" << HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, 0))
        << " slot=" << std::to_string(static_cast<int>(memory.ReadFieldOr<std::int8_t>(
               actor_address,
               kActorSlotOffset,
               -1)))
        << " actor_selectors="
        << std::to_string(memory.ReadFieldOr<std::uint8_t>(
               actor_address,
               kActorRenderVariantPrimaryOffset,
               0xFF))
        << "/"
        << std::to_string(memory.ReadFieldOr<std::uint8_t>(
               actor_address,
               kActorRenderVariantSecondaryOffset,
               0xFF))
        << "/"
        << std::to_string(memory.ReadFieldOr<std::uint8_t>(
               actor_address,
               kActorRenderWeaponTypeOffset,
               0xFF))
        << "/"
        << std::to_string(memory.ReadFieldOr<std::uint8_t>(
               actor_address,
               kActorRenderVariantTertiaryOffset,
               0xFF))
        << "/"
        << std::to_string(memory.ReadFieldOr<std::uint8_t>(
               actor_address,
               kActorRenderSelectionByteOffset,
               0xFF))
        << " anim=" << std::to_string(ResolveActorAnimationStateId(actor_address))
        << " attach=" << HexString(memory.ReadFieldOr<uintptr_t>(
               actor_address,
               kActorHubVisualAttachmentPtrOffset,
               0))
        << " equip=" << HexString(equip_runtime_state_address)
        << " desc=0x" << HexString(HashMemoryBlockFNV1a32(
               actor_address + kActorHubVisualDescriptorBlockOffset,
               kActorHubVisualDescriptorBlockSize))
        << " source_kind=" << std::to_string(memory.ReadFieldOr<std::int32_t>(
               actor_address,
               kActorHubVisualSourceKindOffset,
               0));
    AppendSourceProfileDebugSummary(&out, source_profile_address);

    if (equip_runtime_state_address != 0) {
        AppendEquipVisualLaneSummary(
            &out,
            "primary",
            ReadEquipVisualLaneState(
                equip_runtime_state_address,
                kActorEquipRuntimeVisualLinkPrimaryOffset));
        AppendEquipVisualLaneSummary(
            &out,
            "secondary",
            ReadEquipVisualLaneState(
                equip_runtime_state_address,
                kActorEquipRuntimeVisualLinkSecondaryOffset));
        AppendEquipVisualLaneSummary(
            &out,
            "attachment",
            ReadEquipVisualLaneState(
                equip_runtime_state_address,
                kActorEquipRuntimeVisualLinkAttachmentOffset));
    }

    return out.str();
}

void LogBotVisualDebugStage(
    std::string_view stage,
    uintptr_t local_actor_address,
    uintptr_t bot_actor_address,
    uintptr_t visual_source_actor_address) {
    std::ostringstream out;
    out << "[bots] visual stage=" << stage;
    if (local_actor_address != 0) {
        out << " player={" << BuildActorVisualDebugSummary(local_actor_address) << "}";
    }
    if (bot_actor_address != 0) {
        out << " bot={" << BuildActorVisualDebugSummary(bot_actor_address) << "}";
        const auto bot_equip_runtime =
            ProcessMemory::Instance().ReadFieldOr<uintptr_t>(
                bot_actor_address,
                kActorEquipRuntimeStateOffset,
                0);
        if (bot_equip_runtime != 0) {
            AppendAttachmentObjectDebugSummary(
                &out,
                "bot_attachment_object",
                ReadEquipVisualLaneState(
                    bot_equip_runtime,
                    kActorEquipRuntimeVisualLinkAttachmentOffset).current_object_address);
        }
    }
    if (visual_source_actor_address != 0) {
        out << " source={" << BuildActorVisualDebugSummary(visual_source_actor_address) << "}";
        AppendAttachmentObjectDebugSummary(
            &out,
            "source_attachment_object",
            ProcessMemory::Instance().ReadFieldOr<uintptr_t>(
                visual_source_actor_address,
                kActorHubVisualAttachmentPtrOffset,
                0));
    }
    Log(out.str());
}

void LogWizardCloneSourceCreationStage(
    std::string_view stage,
    uintptr_t world_address,
    uintptr_t source_actor_address,
    uintptr_t source_profile_address) {
    std::ostringstream out;
    out << "[bots] source_create stage=" << stage
        << " world=" << HexString(world_address)
        << " actor=" << HexString(source_actor_address)
        << " profile=" << HexString(source_profile_address);
    if (source_actor_address != 0) {
        out << " actor_summary={" << BuildActorVisualDebugSummary(source_actor_address) << "}";
        AppendAttachmentObjectDebugSummary(
            &out,
            "source_attachment_object",
            ProcessMemory::Instance().ReadFieldOr<uintptr_t>(
                source_actor_address,
                kActorHubVisualAttachmentPtrOffset,
                0));
    }
    if (source_profile_address != 0) {
        out << " profile{";
        AppendSourceProfileDebugSummary(&out, source_profile_address);
        out << " }";
    }
    Log(out.str());
}

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

struct ActorRenderBuildSnapshot {
    std::array<std::uint8_t, kActorHubVisualDescriptorBlockSize> descriptor{};
    std::uint32_t source_profile_unknown74_mirror = 0;
    std::uint16_t source_profile_unknown56_mirror = 0;
    std::uint8_t variant_primary = 0;
    std::uint8_t variant_secondary = 0;
    std::uint8_t weapon_type = 0;
    std::uint8_t render_selection = 0;
    std::uint8_t variant_tertiary = 0;
    uintptr_t attachment_address = 0;
};

ActorRenderBuildSnapshot CaptureActorRenderBuildSnapshot(uintptr_t actor_address) {
    ActorRenderBuildSnapshot snapshot;
    if (actor_address == 0) {
        return snapshot;
    }

    auto& memory = ProcessMemory::Instance();
    (void)memory.TryRead(
        actor_address + kActorHubVisualDescriptorBlockOffset,
        snapshot.descriptor.data(),
        snapshot.descriptor.size());
    snapshot.source_profile_unknown74_mirror =
        memory.ReadFieldOr<std::uint32_t>(actor_address, 0x194, 0);
    snapshot.source_profile_unknown56_mirror =
        memory.ReadFieldOr<std::uint16_t>(actor_address, 0x1C0, 0);
    snapshot.variant_primary =
        memory.ReadFieldOr<std::uint8_t>(actor_address, kActorRenderVariantPrimaryOffset, 0);
    snapshot.variant_secondary =
        memory.ReadFieldOr<std::uint8_t>(actor_address, kActorRenderVariantSecondaryOffset, 0);
    snapshot.weapon_type =
        memory.ReadFieldOr<std::uint8_t>(actor_address, kActorRenderWeaponTypeOffset, 0);
    snapshot.render_selection =
        memory.ReadFieldOr<std::uint8_t>(actor_address, kActorRenderSelectionByteOffset, 0);
    snapshot.variant_tertiary =
        memory.ReadFieldOr<std::uint8_t>(actor_address, kActorRenderVariantTertiaryOffset, 0);
    snapshot.attachment_address =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorHubVisualAttachmentPtrOffset, 0);
    return snapshot;
}

bool RestoreActorRenderBuildSnapshot(
    uintptr_t actor_address,
    const ActorRenderBuildSnapshot& snapshot,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (actor_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Actor render-state restore requires a live actor.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    if (!memory.TryWriteField(
            actor_address,
            kActorRenderVariantPrimaryOffset,
            snapshot.variant_primary) ||
        !memory.TryWriteField(
            actor_address,
            kActorRenderVariantSecondaryOffset,
            snapshot.variant_secondary) ||
        !memory.TryWriteField(
            actor_address,
            kActorRenderWeaponTypeOffset,
            snapshot.weapon_type) ||
        !memory.TryWriteField(
            actor_address,
            kActorRenderSelectionByteOffset,
            snapshot.render_selection) ||
        !memory.TryWriteField(
            actor_address,
            kActorRenderVariantTertiaryOffset,
            snapshot.variant_tertiary) ||
        !memory.TryWriteValue(
            actor_address + 0x194,
            snapshot.source_profile_unknown74_mirror) ||
        !memory.TryWriteValue(
            actor_address + 0x1C0,
            snapshot.source_profile_unknown56_mirror) ||
        !memory.TryWrite(
            actor_address + kActorHubVisualDescriptorBlockOffset,
            snapshot.descriptor.data(),
            snapshot.descriptor.size()) ||
        !memory.TryWriteField(
            actor_address,
            kActorHubVisualAttachmentPtrOffset,
            snapshot.attachment_address)) {
        if (error_message != nullptr) {
            *error_message = "Failed to restore the actor render-state snapshot.";
        }
        return false;
    }

    return true;
}

void ClearActorSyntheticVisualSourceState(uintptr_t actor_address) {
    if (actor_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    (void)memory.TryWriteField<std::int32_t>(
        actor_address,
        kActorHubVisualSourceKindOffset,
        0);
    (void)memory.TryWriteField<uintptr_t>(
        actor_address,
        kActorHubVisualSourceProfileOffset,
        0);
    (void)memory.TryWriteField<uintptr_t>(
        actor_address,
        kActorHubVisualSourceAuxPointerOffset,
        0);
}

void NormalizeGameplaySlotBotActorVisualState(uintptr_t actor_address) {
    (void)actor_address;
}

bool CreateStandaloneWizardVisualLinkObject(
    uintptr_t ctor_address,
    const std::array<std::uint8_t, kActorHubVisualDescriptorBlockSize>& descriptor,
    uintptr_t* object_address,
    std::string* error_message) {
    if (object_address != nullptr) {
        *object_address = 0;
    }
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (ctor_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Standalone visual-link creation requires a live ctor address.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto operator_new_address = memory.ResolveGameAddressOrZero(kGameOperatorNew);
    const auto free_address = memory.ResolveGameAddressOrZero(kGameFree);
    if (operator_new_address == 0 || free_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the visual-link allocation entrypoints.";
        }
        return false;
    }

    uintptr_t object_memory = 0;
    DWORD exception_code = 0;
    if (!CallGameOperatorNewSafe(
            operator_new_address,
            kStandaloneWizardVisualLinkSize,
            &object_memory,
            &exception_code) ||
        object_memory == 0) {
        if (error_message != nullptr) {
            *error_message =
                "Standalone visual-link allocation failed with 0x" +
                HexString(exception_code) + ".";
        }
        return false;
    }

    uintptr_t built_object_address = 0;
    exception_code = 0;
    if (!CallRawObjectCtorSafe(
            ctor_address,
            reinterpret_cast<void*>(object_memory),
            &built_object_address,
            &exception_code) ||
        built_object_address == 0) {
        DWORD release_exception_code = 0;
        (void)CallGameFreeSafe(free_address, object_memory, &release_exception_code);
        if (error_message != nullptr) {
            *error_message =
                "Standalone visual-link ctor failed with 0x" +
                HexString(exception_code) + ".";
        }
        return false;
    }

    if (!memory.TryWriteField(
            built_object_address,
            kStandaloneWizardVisualLinkResetStateOffset,
            static_cast<std::int32_t>(0)) ||
        !memory.TryWriteField(
            built_object_address,
            kStandaloneWizardVisualLinkActiveFlagOffset,
            static_cast<std::uint8_t>(1)) ||
        !memory.TryWrite(
            built_object_address + kStandaloneWizardVisualLinkColorBlockOffset,
            descriptor.data(),
            descriptor.size())) {
        DWORD destroy_exception_code = 0;
        (void)CallScalarDeletingDestructorSafe(
            built_object_address,
            1,
            &destroy_exception_code);
        if (error_message != nullptr) {
            *error_message = "Failed to seed the standalone visual-link payload.";
        }
        return false;
    }

    if (object_address != nullptr) {
        *object_address = built_object_address;
    }
    return true;
}

bool SetEquipVisualLaneObject(
    uintptr_t actor_address,
    std::size_t lane_offset,
    uintptr_t object_address,
    std::string_view label,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (actor_address == 0) {
        if (error_message != nullptr) {
            *error_message =
                "Standalone " + std::string(label) +
                " lane update requires a live actor.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto equip_runtime_state_address =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorEquipRuntimeStateOffset, 0);
    const auto lane = ReadEquipVisualLaneState(equip_runtime_state_address, lane_offset);
    if (lane.holder_address == 0) {
        if (error_message != nullptr) {
            *error_message =
                "Standalone " + std::string(label) +
                " attach could not resolve the equip sink holder.";
        }
        return false;
    }

    const auto attach_address = memory.ResolveGameAddressOrZero(kStandaloneWizardVisualLinkAttach);
    if (attach_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve EquipAttachmentSink_Attach.";
        }
        return false;
    }

    const auto holder_object_before = memory.ReadFieldOr<uintptr_t>(
        lane.holder_address,
        kVisualLaneHolderCurrentObjectOffset,
        0);
    std::ostringstream before_out;
    before_out << "[bots] equip_attach before label=" << label
               << " actor=" << HexString(actor_address)
               << " holder=" << HexString(lane.holder_address)
               << " object_before=" << HexString(holder_object_before)
               << " object_new=" << HexString(object_address);
    if (holder_object_before != 0) {
        AppendAttachmentObjectDebugSummary(
            &before_out,
            "holder_object_before",
            holder_object_before);
    }
    if (object_address != 0) {
        AppendAttachmentObjectDebugSummary(
            &before_out,
            "object_new_state",
            object_address);
    }
    Log(before_out.str());

    DWORD exception_code = 0;
    if (!CallStandaloneWizardVisualLinkAttachSafe(
            attach_address,
            lane.holder_address,
            object_address,
            &exception_code)) {
        if (error_message != nullptr) {
            *error_message =
                "Standalone " + std::string(label) +
                " lane update failed with 0x" + HexString(exception_code) + ".";
        }
        return false;
    }

    const auto holder_object_after = memory.ReadFieldOr<uintptr_t>(
        lane.holder_address,
        kVisualLaneHolderCurrentObjectOffset,
        0);
    std::ostringstream after_out;
    after_out << "[bots] equip_attach after label=" << label
              << " actor=" << HexString(actor_address)
              << " holder=" << HexString(lane.holder_address)
              << " object_after=" << HexString(holder_object_after);
    if (holder_object_after != 0) {
        AppendAttachmentObjectDebugSummary(
            &after_out,
            "holder_object_after",
            holder_object_after);
    }
    Log(after_out.str());

    return true;
}

bool DetachGameplaySlotBotVisualLanes(uintptr_t actor_address, std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (actor_address == 0) {
        return true;
    }

    std::string lane_error;
    if (!SetEquipVisualLaneObject(
            actor_address,
            kActorEquipRuntimeVisualLinkPrimaryOffset,
            0,
            "primary",
            &lane_error)) {
        if (error_message != nullptr) {
            *error_message = lane_error;
        }
        return false;
    }

    if (!SetEquipVisualLaneObject(
            actor_address,
            kActorEquipRuntimeVisualLinkSecondaryOffset,
            0,
            "secondary",
            &lane_error)) {
        if (error_message != nullptr) {
            *error_message = lane_error;
        }
        return false;
    }

    if (!SetEquipVisualLaneObject(
            actor_address,
            kActorEquipRuntimeVisualLinkAttachmentOffset,
            0,
            "attachment",
            &lane_error)) {
        if (error_message != nullptr) {
            *error_message = lane_error;
        }
        return false;
    }

    return true;
}

bool AttachBuiltDescriptorToEquipVisualLane(
    uintptr_t actor_address,
    std::size_t lane_offset,
    uintptr_t ctor_address,
    const std::array<std::uint8_t, kActorHubVisualDescriptorBlockSize>& descriptor,
    std::string_view label,
    std::string* error_message) {
    uintptr_t object_address = 0;
    if (!CreateStandaloneWizardVisualLinkObject(
            ctor_address,
            descriptor,
            &object_address,
            error_message)) {
        return false;
    }

    if (!SetEquipVisualLaneObject(
            actor_address,
            lane_offset,
            object_address,
            label,
            error_message)) {
        DWORD exception_code = 0;
        (void)CallScalarDeletingDestructorSafe(object_address, 1, &exception_code);
        return false;
    }

    return true;
}

bool TransferActorAttachmentToEquipVisualLane(
    uintptr_t actor_address,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (actor_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Attachment transfer requires a live actor.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto attachment_address =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorHubVisualAttachmentPtrOffset, 0);
    if (attachment_address == 0) {
        return true;
    }

    if (!SetEquipVisualLaneObject(
            actor_address,
            kActorEquipRuntimeVisualLinkAttachmentOffset,
            attachment_address,
            "attachment",
            error_message)) {
        return false;
    }

    if (!memory.TryWriteField<uintptr_t>(
            actor_address,
            kActorHubVisualAttachmentPtrOffset,
            0)) {
        if (error_message != nullptr) {
            *error_message = "Failed to clear the actor attachment staging pointer.";
        }
        return false;
    }

    return true;
}

bool TransferSourceActorAttachmentToTargetEquipVisualLane(
    uintptr_t source_actor_address,
    uintptr_t target_actor_address,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (source_actor_address == 0 || target_actor_address == 0) {
        if (error_message != nullptr) {
            *error_message =
                "Source attachment transfer requires both the source actor and target actor.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto source_attachment_address =
        memory.ReadFieldOr<uintptr_t>(source_actor_address, kActorHubVisualAttachmentPtrOffset, 0);
    if (source_attachment_address == 0) {
        return true;
    }

    if (!SetEquipVisualLaneObject(
            target_actor_address,
            kActorEquipRuntimeVisualLinkAttachmentOffset,
            source_attachment_address,
            "attachment",
            error_message)) {
        return false;
    }

    if (!memory.TryWriteField<uintptr_t>(
            source_actor_address,
            kActorHubVisualAttachmentPtrOffset,
            0)) {
        if (error_message != nullptr) {
            *error_message = "Failed to clear the temporary source actor attachment pointer.";
        }
        return false;
    }

    return true;
}

bool PrimeGameplaySlotBotSelectionState(
    uintptr_t actor_address,
    uintptr_t progression_address,
    int slot_index,
    const multiplayer::MultiplayerCharacterProfile& character_profile,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (actor_address == 0 || progression_address == 0 || slot_index < 0) {
        if (error_message != nullptr) {
            *error_message =
                "Gameplay-slot selection prime requires a live actor, progression object, and slot index.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto choice_ids = ResolveProfileAppearanceChoiceIds(character_profile);
    const auto selection_state = ResolveProfileSelectionState(character_profile);
    const auto apply_choice_address = memory.ResolveGameAddressOrZero(kPlayerAppearanceApplyChoice);
    if (apply_choice_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve PlayerAppearance_ApplyChoice.";
        }
        return false;
    }

    const auto apply_choice = [&](int choice_id, int ensure_assets, const char* label) {
        DWORD exception_code = 0;
        if (CallPlayerAppearanceApplyChoiceSafe(
                apply_choice_address,
                progression_address,
                choice_id,
                ensure_assets,
                &exception_code)) {
            return true;
        }
        if (error_message != nullptr) {
            *error_message =
                std::string("PlayerAppearance_ApplyChoice failed for ") + label +
                " with 0x" + HexString(exception_code) + ".";
        }
        return false;
    };

    if (!apply_choice(choice_ids.primary_a, 0, "primary_a") ||
        !apply_choice(choice_ids.primary_b, 0, "primary_b") ||
        !apply_choice(choice_ids.primary_c, 0, "primary_c")) {
        return false;
    }

    if (!memory.TryWriteField(
            progression_address,
            kPlayerProgressionAppearancePrimaryAOffset,
            static_cast<std::int32_t>(choice_ids.primary_a)) ||
        !memory.TryWriteField(
            progression_address,
            kPlayerProgressionAppearancePrimaryBOffset,
            static_cast<std::int32_t>(choice_ids.primary_b)) ||
        !memory.TryWriteField(
            progression_address,
            kPlayerProgressionAppearancePrimaryCOffset,
            static_cast<std::int32_t>(choice_ids.primary_c))) {
        if (error_message != nullptr) {
            *error_message =
                "Failed to mirror the primary wizard appearance ids into the slot progression object.";
        }
        return false;
    }

    if (!apply_choice(choice_ids.secondary, 1, "secondary")) {
        return false;
    }

    if (!TryWriteGameplaySelectionStateForSlot(slot_index, selection_state, error_message)) {
        return false;
    }

    const auto animation_selection_state_address =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorAnimationSelectionStateOffset, 0);
    if (animation_selection_state_address != 0) {
        (void)memory.TryWriteValue(animation_selection_state_address, selection_state);
    }
    Log(
        "[bots] visual stage=selection_pre_refresh bot={" +
        BuildActorVisualDebugSummary(actor_address) +
        "} progression=" + HexString(progression_address) +
        " choice_ids=" + std::to_string(choice_ids.primary_a) + "/" +
        std::to_string(choice_ids.primary_b) + "/" +
        std::to_string(choice_ids.primary_c) + "/" +
        std::to_string(choice_ids.secondary));

    if (!PrimeStandaloneWizardProgressionSelectionState(
            progression_address,
            selection_state,
            error_message)) {
        return false;
    }

    const auto refresh_progression_address = memory.ResolveGameAddressOrZero(kActorProgressionRefresh);
    if (refresh_progression_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve ActorProgressionRefresh.";
        }
        return false;
    }

    DWORD exception_code = 0;
    if (!CallActorProgressionRefreshSafe(
            refresh_progression_address,
            actor_address,
            &exception_code)) {
        if (error_message != nullptr) {
            *error_message =
                "Actor progression refresh failed with 0x" + HexString(exception_code) + ".";
        }
        return false;
    }

    if (!memory.TryWriteField(
            progression_address,
            kPlayerProgressionAppearanceSecondaryOffset,
            static_cast<std::int32_t>(choice_ids.secondary))) {
        if (error_message != nullptr) {
            *error_message = "Failed to mirror the secondary wizard appearance id into the slot progression object.";
        }
        return false;
    }

    if (animation_selection_state_address != 0) {
        (void)memory.TryWriteValue(animation_selection_state_address, selection_state);
    }
    if (!TryWriteActorAnimationStateIdDirect(actor_address, selection_state)) {
        Log(
            "[bots] gameplay-slot actor animation prime skipped. actor=" + HexString(actor_address) +
            " desired=" + std::to_string(selection_state));
    }
    ApplyStandaloneWizardPuppetDriveState(nullptr, actor_address, false);
    Log(
        "[bots] visual stage=selection_post_refresh bot={" +
        BuildActorVisualDebugSummary(actor_address) +
        "} progression=" + HexString(progression_address) +
        " selection_state=" + std::to_string(selection_state));
    return true;
}

bool PrimeStandaloneWizardProgressionSelectionState(
    uintptr_t progression_inner_address,
    int selection_state,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (selection_state < 0) {
        return true;
    }
    if (progression_inner_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Standalone progression selection prime requires a live runtime object.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto progression_table_address = memory.ReadFieldOr<uintptr_t>(
        progression_inner_address,
        kStandaloneWizardProgressionTableBaseOffset,
        0);
    const auto progression_table_count = memory.ReadFieldOr<int>(
        progression_inner_address,
        kStandaloneWizardProgressionTableCountOffset,
        0);
    if (progression_table_address == 0 || progression_table_count <= selection_state) {
        if (error_message != nullptr) {
            *error_message =
                "Standalone progression selection table is unavailable for state=" +
                std::to_string(selection_state) + ".";
        }
        return false;
    }

    const auto selection_offset =
        static_cast<std::size_t>(selection_state) * kStandaloneWizardProgressionEntryStride;
    if (!memory.TryWriteField<std::uint16_t>(
            progression_table_address,
            selection_offset + kStandaloneWizardProgressionActiveFlagOffset,
            1) ||
        !memory.TryWriteField<std::uint16_t>(
            progression_table_address,
            selection_offset + kStandaloneWizardProgressionVisibleFlagOffset,
            1)) {
        if (error_message != nullptr) {
            *error_message =
                "Failed to mark standalone progression state=" + std::to_string(selection_state) +
                " as active.";
        }
        return false;
    }

    return true;
}

void ReleaseStandaloneWizardSmartPointerResource(
    uintptr_t actor_address,
    std::size_t handle_offset,
    std::size_t runtime_state_offset,
    uintptr_t wrapper_address,
    uintptr_t inner_address,
    const char* label) {
    auto& memory = ProcessMemory::Instance();
    if (actor_address != 0 &&
        memory.ReadFieldOr<uintptr_t>(actor_address, handle_offset, 0) == wrapper_address) {
        (void)memory.TryWriteField<uintptr_t>(actor_address, handle_offset, 0);
        (void)memory.TryWriteField<uintptr_t>(actor_address, runtime_state_offset, 0);
    }

    if (wrapper_address != 0) {
        DWORD exception_code = 0;
        if (!ReleaseSmartPointerWrapperSafe(wrapper_address, &exception_code)) {
            Log(
                "[bots] standalone " + std::string(label) + " release skipped. wrapper=" +
                HexString(wrapper_address) +
                " inner=" + HexString(inner_address) +
                " code=0x" + HexString(exception_code));
        }
    }
}

void ReleaseStandaloneWizardVisualResources(
    uintptr_t actor_address,
    uintptr_t progression_wrapper_address,
    uintptr_t progression_inner_address,
    uintptr_t equip_wrapper_address,
    uintptr_t equip_inner_address) {
    ReleaseStandaloneWizardSmartPointerResource(
        actor_address,
        kActorProgressionHandleOffset,
        kActorProgressionRuntimeStateOffset,
        progression_wrapper_address,
        progression_inner_address,
        "visual");
    ReleaseStandaloneWizardSmartPointerResource(
        actor_address,
        kActorEquipHandleOffset,
        kActorEquipRuntimeStateOffset,
        equip_wrapper_address,
        equip_inner_address,
        "equip");
}

bool CreateStandaloneWizardEquipWrapper(
    uintptr_t* wrapper_address,
    uintptr_t* inner_address,
    std::string* error_message) {
    if (wrapper_address != nullptr) {
        *wrapper_address = 0;
    }
    if (inner_address != nullptr) {
        *inner_address = 0;
    }
    if (error_message != nullptr) {
        error_message->clear();
    }

    auto& memory = ProcessMemory::Instance();
    const auto operator_new_address = memory.ResolveGameAddressOrZero(kGameOperatorNew);
    const auto free_address = memory.ResolveGameAddressOrZero(kGameFree);
    const auto equip_ctor_address = memory.ResolveGameAddressOrZero(kStandaloneWizardEquipCtor);
    if (operator_new_address == 0 || free_address == 0 || equip_ctor_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the standalone equip entrypoints.";
        }
        return false;
    }

    uintptr_t equip_object_memory = 0;
    DWORD exception_code = 0;
    if (!CallGameOperatorNewSafe(
            operator_new_address,
            kStandaloneWizardEquipSize,
            &equip_object_memory,
            &exception_code) ||
        equip_object_memory == 0) {
        if (error_message != nullptr) {
            *error_message = "Standalone equip allocation failed with 0x" + HexString(exception_code) + ".";
        }
        return false;
    }

    uintptr_t equip_object_address = 0;
    exception_code = 0;
    if (!CallRawObjectCtorSafe(
            equip_ctor_address,
            reinterpret_cast<void*>(equip_object_memory),
            &equip_object_address,
            &exception_code) ||
        equip_object_address == 0) {
        DWORD release_exception_code = 0;
        if (!CallGameFreeSafe(free_address, equip_object_memory, &release_exception_code) &&
            release_exception_code != 0) {
            Log(
                "[bots] standalone equip raw cleanup skipped. inner=" +
                HexString(equip_object_memory) +
                " code=0x" + HexString(release_exception_code));
        }
        if (error_message != nullptr) {
            *error_message = "Standalone equip ctor failed with 0x" + HexString(exception_code) + ".";
        }
        return false;
    }

    uintptr_t equip_wrapper_address = 0;
    exception_code = 0;
    if (!CallGameOperatorNewSafe(
            operator_new_address,
            sizeof(std::uint32_t) * 2,
            &equip_wrapper_address,
            &exception_code) ||
        equip_wrapper_address == 0) {
        DWORD release_exception_code = 0;
        if (!CallScalarDeletingDestructorSafe(equip_object_address, 1, &release_exception_code) &&
            release_exception_code != 0) {
            Log(
                "[bots] standalone equip object cleanup skipped. inner=" +
                HexString(equip_object_address) +
                " code=0x" + HexString(release_exception_code));
        }
        if (error_message != nullptr) {
            *error_message = "Standalone equip wrapper allocation failed with 0x" +
                             HexString(exception_code) + ".";
        }
        return false;
    }

    auto* wrapper_words = reinterpret_cast<std::uint32_t*>(equip_wrapper_address);
    wrapper_words[0] = static_cast<std::uint32_t>(equip_object_address);
    wrapper_words[1] = 0;

    if (wrapper_address != nullptr) {
        *wrapper_address = equip_wrapper_address;
    }
    if (inner_address != nullptr) {
        *inner_address = equip_object_address;
    }
    return true;
}

bool CreateStandaloneWizardProgressionWrapper(
    uintptr_t* wrapper_address,
    uintptr_t* inner_address,
    std::string* error_message) {
    if (wrapper_address != nullptr) {
        *wrapper_address = 0;
    }
    if (inner_address != nullptr) {
        *inner_address = 0;
    }
    if (error_message != nullptr) {
        error_message->clear();
    }

    auto& memory = ProcessMemory::Instance();
    const auto operator_new_address = memory.ResolveGameAddressOrZero(kGameOperatorNew);
    const auto free_address = memory.ResolveGameAddressOrZero(kGameFree);
    const auto progression_ctor_address =
        memory.ResolveGameAddressOrZero(kStandaloneWizardVisualRuntimeCtor);
    if (operator_new_address == 0 ||
        free_address == 0 ||
        progression_ctor_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the standalone progression entrypoints.";
        }
        return false;
    }

    uintptr_t progression_object_memory = 0;
    DWORD exception_code = 0;
    if (!CallGameOperatorNewSafe(
            operator_new_address,
            kStandaloneWizardVisualRuntimeSize,
            &progression_object_memory,
            &exception_code) ||
        progression_object_memory == 0) {
        if (error_message != nullptr) {
            *error_message =
                "Standalone progression allocation failed with 0x" +
                HexString(exception_code) + ".";
        }
        return false;
    }

    uintptr_t progression_object_address = 0;
    exception_code = 0;
    if (!CallRawObjectCtorSafe(
            progression_ctor_address,
            reinterpret_cast<void*>(progression_object_memory),
            &progression_object_address,
            &exception_code) ||
        progression_object_address == 0) {
        DWORD release_exception_code = 0;
        if (!CallGameFreeSafe(free_address, progression_object_memory, &release_exception_code) &&
            release_exception_code != 0) {
            Log(
                "[bots] standalone progression raw cleanup skipped. inner=" +
                HexString(progression_object_memory) +
                " code=0x" + HexString(release_exception_code));
        }
        if (error_message != nullptr) {
            *error_message =
                "Standalone progression ctor failed with 0x" +
                HexString(exception_code) + ".";
        }
        return false;
    }

    uintptr_t progression_wrapper_address = 0;
    exception_code = 0;
    if (!CallGameOperatorNewSafe(
            operator_new_address,
            sizeof(std::uint32_t) * 2,
            &progression_wrapper_address,
            &exception_code) ||
        progression_wrapper_address == 0) {
        DWORD release_exception_code = 0;
        if (!CallScalarDeletingDestructorSafe(
                progression_object_address,
                1,
                &release_exception_code) &&
            release_exception_code != 0) {
            Log(
                "[bots] standalone progression object cleanup skipped. inner=" +
                HexString(progression_object_address) +
                " code=0x" + HexString(release_exception_code));
        }
        if (error_message != nullptr) {
            *error_message =
                "Standalone progression wrapper allocation failed with 0x" +
                HexString(exception_code) + ".";
        }
        return false;
    }

    auto* wrapper_words = reinterpret_cast<std::uint32_t*>(progression_wrapper_address);
    wrapper_words[0] = static_cast<std::uint32_t>(progression_object_address);
    wrapper_words[1] = 0;

    if (wrapper_address != nullptr) {
        *wrapper_address = progression_wrapper_address;
    }
    if (inner_address != nullptr) {
        *inner_address = progression_object_address;
    }
    return true;
}

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

    auto& memory = ProcessMemory::Instance();
    const auto primary_visual_link_ctor_address =
        memory.ResolveGameAddressOrZero(kStandaloneWizardVisualLinkPrimaryCtor);
    const auto secondary_visual_link_ctor_address =
        memory.ResolveGameAddressOrZero(kStandaloneWizardVisualLinkSecondaryCtor);
    if (primary_visual_link_ctor_address == 0 ||
        secondary_visual_link_ctor_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the stock visual-link constructors.";
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
        const auto bot_attachment_before_cleanup = ReadEquipVisualLaneState(
            memory.ReadFieldOr<uintptr_t>(actor_address, kActorEquipRuntimeStateOffset, 0),
            kActorEquipRuntimeVisualLinkAttachmentOffset).current_object_address;
        if (bot_attachment_before_cleanup != 0) {
            std::ostringstream before_out;
            before_out << "[bots] attachment transfer cleanup-before";
            AppendAttachmentObjectDebugSummary(
                &before_out,
                "bot_attachment_object",
                bot_attachment_before_cleanup);
            Log(before_out.str());
        }
        if (source_actor_address != 0) {
            (void)DestroyWizardCloneSourceActor(source_actor_address, &cleanup_error);
        }
        if (source_profile_address != 0) {
            DestroySyntheticWizardSourceProfile(source_profile_address);
        }
        const auto bot_attachment_after_cleanup = ReadEquipVisualLaneState(
            memory.ReadFieldOr<uintptr_t>(actor_address, kActorEquipRuntimeStateOffset, 0),
            kActorEquipRuntimeVisualLinkAttachmentOffset).current_object_address;
        if (bot_attachment_after_cleanup != 0) {
            std::ostringstream after_out;
            after_out << "[bots] attachment transfer cleanup-after";
            AppendAttachmentObjectDebugSummary(
                &after_out,
                "bot_attachment_object",
                bot_attachment_after_cleanup);
            Log(after_out.str());
        }
        if (!cleanup_error.empty()) {
            Log("[bots] source actor cleanup detail: " + cleanup_error);
        }
    };

    constexpr bool kKeepSourceActorAliveDiagnostic = false;

    const auto built_descriptor =
        CaptureActorRenderBuildSnapshot(source_actor_address).descriptor;

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
            &stage_error) ||
        !TransferSourceActorAttachmentToTargetEquipVisualLane(
            source_actor_address,
            actor_address,
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
    Log(
        "[bots] visual stage=slot_actor_helper_lanes_seeded bot={" +
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
    const auto ensure_progression_handle_address =
        memory.ResolveGameAddressOrZero(kPlayerActorEnsureProgressionHandle);
    if (ensure_progression_handle_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve PlayerActor_EnsureProgressionHandleFromGameplaySlot.";
        }
        return false;
    }
    DWORD ensure_exception_code = 0;
    if (!CallPlayerActorEnsureProgressionHandleSafe(
            ensure_progression_handle_address,
            slot_actor_address,
            &ensure_exception_code)) {
        if (error_message != nullptr) {
            *error_message =
                "PlayerActor_EnsureProgressionHandleFromGameplaySlot failed with 0x" +
                HexString(ensure_exception_code) + ".";
        }
        return false;
    }

    const auto slot_progression_handle_address =
        memory.ReadFieldOr<uintptr_t>(slot_actor_address, kActorProgressionHandleOffset, 0);
    if (slot_progression_handle_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Gameplay-slot actor did not publish the stock progression handle.";
        }
        return false;
    }
    if (slot_progression_handle_address !=
        memory.ReadFieldOr<uintptr_t>(
            gameplay_address,
            kGameplayPlayerProgressionHandleOffset +
                static_cast<std::size_t>(slot_index) * kGameplayPlayerSlotStride,
            0)) {
        if (error_message != nullptr) {
            *error_message = "Gameplay-slot actor progression handle did not bind back to the slot table.";
        }
        return false;
    }

    // Gameplay-slot actors do not own standalone clone runtimes. Keep the actor
    // on the stock slot contract: borrowed slot progression handle at `+0x300`,
    // null direct progression/equip runtime pointers, and no actor-side attachment.
    (void)memory.TryWriteField<uintptr_t>(slot_actor_address, kActorProgressionRuntimeStateOffset, 0);
    (void)memory.TryWriteField<uintptr_t>(slot_actor_address, kActorEquipHandleOffset, 0);
    (void)memory.TryWriteField<uintptr_t>(slot_actor_address, kActorEquipRuntimeStateOffset, 0);
    (void)memory.TryWriteField<std::uint32_t>(slot_actor_address, kActorHubVisualSourceKindOffset, 0);
    (void)memory.TryWriteField<uintptr_t>(slot_actor_address, kActorHubVisualSourceProfileOffset, 0);
    (void)memory.TryWriteField<std::uint32_t>(slot_actor_address, kActorHubVisualSourceAuxPointerOffset, 0x00000101u);
    (void)memory.TryWriteField<uintptr_t>(slot_actor_address, kActorHubVisualAttachmentPtrOffset, 0);

    if (!PrimeGameplaySlotBotSelectionState(
            slot_actor_address,
            slot_progression_address,
            slot_index,
            character_profile,
            &stage_error)) {
        if (error_message != nullptr) {
            *error_message = std::move(stage_error);
        }
        return false;
    }

    if (!WireGameplaySlotBotRuntimeHandles(
            slot_actor_address,
            &stage_error)) {
        if (error_message != nullptr) {
            *error_message = std::move(stage_error);
        }
        return false;
    }

    if (!SeedGameplaySlotBotRenderStateFromSourceActor(
            slot_actor_address,
            world_address,
            character_profile,
            x,
            y,
            heading,
            &stage_error)) {
        if (error_message != nullptr) {
            *error_message = std::move(stage_error);
        }
        return false;
    }

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
    BotEntityBinding* binding,
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

    const auto register_slot_address =
        memory.ResolveGameAddressOrZero(kActorWorldRegisterGameplaySlotActor);
    if (register_slot_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve ActorWorld_RegisterGameplaySlotActor.";
        }
        return false;
    }

    uintptr_t local_actor_address = 0;
    if (TryResolvePlayerActorForSlot(gameplay_address, 0, &local_actor_address) &&
        local_actor_address != 0) {
        const auto local_header_word =
            memory.ReadFieldOr<std::uint32_t>(local_actor_address, kObjectHeaderWordOffset, 0);
        (void)memory.TryWriteField(actor_address, kObjectHeaderWordOffset, local_header_word);
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

    LogBotVisualDebugStage(
        "finalize_after_slot_register",
        0,
        actor_address,
        0);

    if (local_actor_address != 0) {
        const auto local_header_word =
            memory.ReadFieldOr<std::uint32_t>(local_actor_address, kObjectHeaderWordOffset, 0);
        (void)memory.TryWriteField(actor_address, kObjectHeaderWordOffset, local_header_word);
    }

    if (!SyncActorRegisteredSlotMirrorsFromCurrentIdentity(actor_address, error_message)) {
        return false;
    }

    // Keep the wrapper handle cleared, but preserve the live equip runtime
    // pointer so the seeded robe/hat helper lanes remain reachable.
    (void)memory.TryWriteField(actor_address, kActorEquipHandleOffset, static_cast<uintptr_t>(0));

    // Stock gameplay-slot registration already inserts and rebinds the actor
    // into the live region/cell path. The extra gameplay attach call appears to
    // feed the immediate world-unregister wave for bot actors, so keep the slot
    // registration path authoritative here.
    if (binding != nullptr) {
        binding->gameplay_attach_applied = false;
    }
    return true;
}

bool DestroyGameplaySlotBotResources(
    uintptr_t gameplay_address,
    int slot_index,
    uintptr_t actor_address,
    uintptr_t world_address,
    uintptr_t synthetic_source_profile_address,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (gameplay_address == 0 || slot_index < 0) {
        if (error_message != nullptr) {
            *error_message = "Gameplay slot cleanup requires a live gameplay scene and slot index.";
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
    if (actor_address == 0) {
        actor_address = published_actor_address;
    }

    if (world_address == 0 && actor_address != 0) {
        world_address = memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, 0);
    }

    if (actor_address != 0) {
        std::string detach_error;
        if (!DetachGameplaySlotBotVisualLanes(actor_address, &detach_error)) {
            if (error_message != nullptr) {
                *error_message = detach_error;
            }
            return false;
        }
    }

    if (world_address != 0) {
        const auto unregister_slot_address =
            memory.ResolveGameAddressOrZero(kActorWorldUnregisterGameplaySlotActor);
        if (unregister_slot_address == 0) {
            if (error_message != nullptr) {
                *error_message = "Unable to resolve ActorWorld_UnregisterGameplaySlotActor.";
            }
            return false;
        }

        DWORD exception_code = 0;
        if (!CallActorWorldUnregisterGameplaySlotActorSafe(
                unregister_slot_address,
                world_address,
                slot_index,
                &exception_code)) {
            if (error_message != nullptr) {
                *error_message =
                    "ActorWorld_UnregisterGameplaySlotActor failed with 0x" +
                    HexString(exception_code) + ".";
            }
            return false;
        }
    }

    (void)memory.TryWriteField<uintptr_t>(gameplay_address, actor_slot_offset, 0);
    (void)memory.TryWriteField<uintptr_t>(gameplay_address, progression_slot_offset, 0);

    (void)synthetic_source_profile_address;

    return true;
}

bool DestroyLoaderOwnedWizardActor(
    uintptr_t actor_address,
    uintptr_t world_address,
    bool raw_allocation,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (actor_address == 0) {
        return true;
    }

    auto& memory = ProcessMemory::Instance();
    const auto live_owner_address =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, 0);
    if (live_owner_address != 0) {
        world_address = live_owner_address;
    } else if (!raw_allocation) {
        world_address = 0;
    }

    auto build_destroy_summary = [&](std::string_view stage) {
        std::ostringstream out;
        out << "stage=" << stage
            << " actor=" << HexString(actor_address)
            << " world=" << HexString(world_address)
            << " raw_allocation=" << (raw_allocation ? "true" : "false")
            << " actor_summary={" << BuildActorVisualDebugSummary(actor_address) << "}"
            << " byte5=" << static_cast<int>(memory.ReadFieldOr<std::uint8_t>(actor_address, 0x05, 0))
            << " byte6=" << static_cast<int>(memory.ReadFieldOr<std::uint8_t>(actor_address, 0x06, 0))
            << " vtable=" << HexString(memory.ReadValueOr<uintptr_t>(actor_address, 0))
            << " owner=" << HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, 0))
            << " attach=" << HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorHubVisualAttachmentPtrOffset, 0));
        return out.str();
    };

    if (world_address != 0) {
        const auto puppet_manager_delete_puppet_address =
            memory.ResolveGameAddressOrZero(kPuppetManagerDeletePuppet);
        const auto puppet_manager_address =
            kRegionPuppetManagerOffset == 0 ? 0 : world_address + kRegionPuppetManagerOffset;
        if (!raw_allocation &&
            puppet_manager_delete_puppet_address != 0 &&
            puppet_manager_address != 0) {
            DWORD exception_code = 0;
            if (!CallPuppetManagerDeletePuppetSafe(
                    puppet_manager_delete_puppet_address,
                    puppet_manager_address,
                    actor_address,
                    &exception_code)) {
                Log(
                    "[bots] destroy_loader_owned_actor puppet_delete_failed " +
                    build_destroy_summary("pre_puppet_delete_exception"));
                if (error_message != nullptr) {
                    *error_message =
                        "PuppetManager_DeletePuppet failed with 0x" + HexString(exception_code) + ".";
                }
                return false;
            }
            return true;
        }

        const auto unregister_address = memory.ResolveGameAddressOrZero(kActorWorldUnregister);
        if (unregister_address == 0) {
            if (error_message != nullptr) {
                *error_message = "Unable to resolve ActorWorld_Unregister.";
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
            Log("[bots] destroy_loader_owned_actor unregister_failed " + build_destroy_summary("post_unregister_exception"));
            if (error_message != nullptr) {
                *error_message = "ActorWorld_Unregister failed with 0x" + HexString(exception_code) + ".";
            }
            return false;
        }
    }

    if (!raw_allocation) {
        const auto object_delete_address = memory.ResolveGameAddressOrZero(kObjectDelete);
        if (object_delete_address == 0) {
            if (error_message != nullptr) {
                *error_message = "Unable to resolve Object_Delete.";
            }
            return false;
        }

        DWORD exception_code = 0;
        if (!CallObjectDeleteSafe(object_delete_address, actor_address, &exception_code)) {
            Log(
                "[bots] destroy_loader_owned_actor object_delete_failed " +
                build_destroy_summary("post_unregister"));
            if (error_message != nullptr) {
                *error_message = "Object_Delete failed with 0x" + HexString(exception_code) + ".";
            }
            return false;
        }
        return true;
    }

    SehExceptionDetails exception_details = {};
    if (!CallScalarDeletingDestructorDetailedSafe(
            actor_address,
            0,
            &exception_details)) {
        const auto detail_summary = FormatSehExceptionDetails(exception_details);
        Log(
            "[bots] destroy_loader_owned_actor dtor_failed " +
            build_destroy_summary("post_unregister") +
            " seh{" + detail_summary + "}");
        if (error_message != nullptr) {
            *error_message = "Actor scalar deleting destructor failed. " + detail_summary;
        }
        return false;
    }

    if (raw_allocation) {
        _aligned_free(reinterpret_cast<void*>(actor_address));
    }

    return true;
}

ElementColorDescriptor GetWizardElementColor(int wizard_id) {
    // Preserve the existing external bot API semantics:
    //   0 fire, 1 water, 2 earth, 3 air, 4 ether
    // The synthetic source-profile path seeds cloth color *before* the stock
    // descriptor build runs. The stock helper colors visible on player items
    // are the result of `Float4_GrayscaleMixClamp` / `FUN_0040FC60`, not the
    // raw source-profile cloth triplet itself. These values are therefore the
    // reconstructed pre-transform source colors that reproduce the observed
    // stock helper palettes for Fire/Water/Earth/Air.
    //
    // Reconstruction basis:
    //   helper = 0.2 * source + 0.8 * grayscale(source)
    //   grayscale(source) uses weights 0.3086 / 0.6094 / 0.0820
    //
    // Fire/Water/Earth/Air were solved from clean stock player helper items on
    // 2026-04-12. Ether was solved from a fresh same-element player/bot check
    // on 2026-04-13 after the public semantic remap.
    switch (wizard_id) {
        case 0: // Fire
            return {1.08003414f, 0.15461998f, 0.00474097f, 1.0f, 1.0f, 1.0f, 1.0f, 1.0f};
        case 1: // Water
            return {0.18303899f, 0.51879197f, 0.94631803f, 1.0f, 1.0f, 1.0f, 1.0f, 1.0f};
        case 2: // Earth
            return {-0.09265301f, 0.72661299f, -0.02961797f, 1.0f, 1.0f, 1.0f, 1.0f, 1.0f};
        case 3: // Air
            return {0.01964684f, 1.01231515f, 1.02918804f, 1.0f, 1.0f, 1.0f, 1.0f, 1.0f};
        case 4: // Ether
            return {1.05664342f, 0.10103842f, 0.99839842f, 1.0f, 1.0f, 1.0f, 1.0f, 1.0f};
        default: // Fallback to neutral gray
            return {0.6f, 0.6f, 0.6f, 1.0f, 1.0f, 1.0f, 1.0f, 1.0f};
    }
}
