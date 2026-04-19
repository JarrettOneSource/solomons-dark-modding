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

