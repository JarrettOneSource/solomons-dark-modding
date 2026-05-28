void AppendSourceProfileDebugSummary(
    std::ostringstream* out,
    uintptr_t source_profile_address) {
    if (out == nullptr || source_profile_address == 0) {
        return;
    }

    *out << " source_profile=" << HexString(source_profile_address)
         << " src_selectors="
         << ReadU8ValueText(source_profile_address + kSourceProfileVariantPrimaryOffset)
         << "/"
         << ReadU8ValueText(source_profile_address + kSourceProfileVariantSecondaryOffset)
         << "/"
         << ReadU8ValueText(source_profile_address + kSourceProfileWeaponTypeOffset)
         << "/"
         << ReadU8ValueText(source_profile_address + kSourceProfileVariantTertiaryOffset)
         << "/"
         << ReadU8ValueText(source_profile_address + kSourceProfileRenderSelectionOffset)
         << " cloth="
         << ReadFloatValueText(source_profile_address + kSourceProfileClothColorOffset + 0x00)
         << ","
         << ReadFloatValueText(source_profile_address + kSourceProfileClothColorOffset + 0x04)
         << ","
         << ReadFloatValueText(source_profile_address + kSourceProfileClothColorOffset + 0x08)
         << " trim="
         << ReadFloatValueText(source_profile_address + kSourceProfileTrimColorOffset + 0x00)
         << ","
         << ReadFloatValueText(source_profile_address + kSourceProfileTrimColorOffset + 0x04)
         << ","
         << ReadFloatValueText(source_profile_address + kSourceProfileTrimColorOffset + 0x08);
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

    *out << " " << label
         << "{addr=" << HexString(object_address)
         << " +04=" << ReadU32FieldHexText(object_address, 0x04)
         << " +0C=" << ReadU32FieldHexText(object_address, 0x0C)
         << " +14=" << ReadU32FieldHexText(object_address, 0x14);
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
    uintptr_t equip_runtime_state_address = 0;
    const bool have_equip_runtime_state = memory.TryReadField(
        actor_address,
        kActorEquipRuntimeStateOffset,
        &equip_runtime_state_address);
    uintptr_t source_profile_address = 0;
    const bool have_source_profile = memory.TryReadField(
        actor_address,
        kActorHubVisualSourceProfileOffset,
        &source_profile_address);

    out << " ctx=" << ReadPointerFieldText(actor_address, 0x04)
        << " world=" << ReadPointerFieldText(actor_address, kActorOwnerOffset)
        << " slot=" << ReadI8FieldText(actor_address, kActorSlotOffset)
        << " actor_selectors="
        << ReadU8FieldText(actor_address, kActorRenderVariantPrimaryOffset)
        << "/"
        << ReadU8FieldText(actor_address, kActorRenderVariantSecondaryOffset)
        << "/"
        << ReadU8FieldText(actor_address, kActorRenderWeaponTypeOffset)
        << "/"
        << ReadU8FieldText(actor_address, kActorRenderVariantTertiaryOffset)
        << "/"
        << ReadU8FieldText(actor_address, kActorRenderSelectionByteOffset)
        << " anim=" << std::to_string(ResolveActorAnimationStateId(actor_address))
        << " attach=" << ReadPointerFieldText(actor_address, kActorHubVisualAttachmentPtrOffset)
        << " equip=" << (have_equip_runtime_state ? HexString(equip_runtime_state_address) : UnreadableMemoryFieldText())
        << " desc=0x" << HexString(HashMemoryBlockFNV1a32(
               actor_address + kActorHubVisualDescriptorBlockOffset,
               kActorHubVisualDescriptorBlockSize))
        << " source_kind=" << ReadI32FieldText(actor_address, kActorHubVisualSourceKindOffset);
    if (have_source_profile) {
        AppendSourceProfileDebugSummary(&out, source_profile_address);
    }

    if (have_equip_runtime_state && equip_runtime_state_address != 0) {
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
    if constexpr (!kEnableWizardBotHotPathDiagnostics) {
        return;
    }

    std::ostringstream out;
    out << "[bots] visual stage=" << stage;
    if (local_actor_address != 0) {
        out << " player={" << BuildActorVisualDebugSummary(local_actor_address) << "}";
    }
    if (bot_actor_address != 0) {
        out << " bot={" << BuildActorVisualDebugSummary(bot_actor_address) << "}";
        uintptr_t bot_equip_runtime = 0;
        if (ProcessMemory::Instance().TryReadField(
                bot_actor_address,
                kActorEquipRuntimeStateOffset,
                &bot_equip_runtime) &&
            bot_equip_runtime != 0) {
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
        uintptr_t attachment_ptr = 0;
        if (ProcessMemory::Instance().TryReadField(
                visual_source_actor_address,
                kActorHubVisualAttachmentPtrOffset,
                &attachment_ptr)) {
            AppendAttachmentObjectDebugSummary(&out, "source_attachment_object", attachment_ptr);
        }
    }
    Log(out.str());
}

void LogWizardCloneSourceCreationStage(
    std::string_view stage,
    uintptr_t world_address,
    uintptr_t source_actor_address,
    uintptr_t source_profile_address) {
    if constexpr (!kEnableWizardBotHotPathDiagnostics) {
        return;
    }

    std::ostringstream out;
    out << "[bots] source_create stage=" << stage
        << " world=" << HexString(world_address)
        << " actor=" << HexString(source_actor_address)
        << " profile=" << HexString(source_profile_address);
    if (source_actor_address != 0) {
        out << " actor_summary={" << BuildActorVisualDebugSummary(source_actor_address) << "}";
        uintptr_t attachment_ptr = 0;
        if (ProcessMemory::Instance().TryReadField(
                source_actor_address,
                kActorHubVisualAttachmentPtrOffset,
                &attachment_ptr)) {
            AppendAttachmentObjectDebugSummary(&out, "source_attachment_object", attachment_ptr);
        }
    }
    if (source_profile_address != 0) {
        out << " profile{";
        AppendSourceProfileDebugSummary(&out, source_profile_address);
        out << " }";
    }
    Log(out.str());
}
