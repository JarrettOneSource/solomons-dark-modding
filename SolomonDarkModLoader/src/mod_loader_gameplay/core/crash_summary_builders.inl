std::string UnreadableMemoryFieldText() {
    return "unreadable";
}

template <typename T, typename Formatter>
std::string ReadFieldDiagnosticText(uintptr_t base_address, size_t offset, Formatter&& formatter) {
    T value{};
    if (!ProcessMemory::Instance().TryReadField(base_address, offset, &value)) {
        return UnreadableMemoryFieldText();
    }
    return formatter(value);
}

template <typename T, typename Formatter>
std::string ReadValueDiagnosticText(uintptr_t address, Formatter&& formatter) {
    T value{};
    if (!ProcessMemory::Instance().TryReadValue(address, &value)) {
        return UnreadableMemoryFieldText();
    }
    return formatter(value);
}

std::string ReadPointerFieldText(uintptr_t base_address, size_t offset) {
    return ReadFieldDiagnosticText<uintptr_t>(
        base_address,
        offset,
        [](uintptr_t value) { return HexString(value); });
}

std::string ReadPointerValueText(uintptr_t address) {
    return ReadValueDiagnosticText<uintptr_t>(
        address,
        [](uintptr_t value) { return HexString(value); });
}

std::string ReadU32FieldHexText(uintptr_t base_address, size_t offset) {
    return ReadFieldDiagnosticText<std::uint32_t>(
        base_address,
        offset,
        [](std::uint32_t value) { return HexString(static_cast<uintptr_t>(value)); });
}

std::string ReadU8FieldHexText(uintptr_t base_address, size_t offset) {
    return ReadFieldDiagnosticText<std::uint8_t>(
        base_address,
        offset,
        [](std::uint8_t value) { return HexString(static_cast<uintptr_t>(value)); });
}

std::string ReadU16FieldHexText(uintptr_t base_address, size_t offset) {
    return ReadFieldDiagnosticText<std::uint16_t>(
        base_address,
        offset,
        [](std::uint16_t value) { return HexString(static_cast<uintptr_t>(value)); });
}

std::string ReadU32FieldText(uintptr_t base_address, size_t offset) {
    return ReadFieldDiagnosticText<std::uint32_t>(
        base_address,
        offset,
        [](std::uint32_t value) { return std::to_string(value); });
}

std::string ReadU8FieldText(uintptr_t base_address, size_t offset) {
    return ReadFieldDiagnosticText<std::uint8_t>(
        base_address,
        offset,
        [](std::uint8_t value) { return std::to_string(static_cast<unsigned>(value)); });
}

std::string ReadI8FieldText(uintptr_t base_address, size_t offset) {
    return ReadFieldDiagnosticText<std::int8_t>(
        base_address,
        offset,
        [](std::int8_t value) { return std::to_string(static_cast<int>(value)); });
}

std::string ReadI16FieldText(uintptr_t base_address, size_t offset) {
    return ReadFieldDiagnosticText<std::int16_t>(
        base_address,
        offset,
        [](std::int16_t value) { return std::to_string(static_cast<int>(value)); });
}

std::string ReadI32FieldText(uintptr_t base_address, size_t offset) {
    return ReadFieldDiagnosticText<std::int32_t>(
        base_address,
        offset,
        [](std::int32_t value) { return std::to_string(value); });
}

std::string ReadFloatFieldText(uintptr_t base_address, size_t offset) {
    return ReadFieldDiagnosticText<float>(
        base_address,
        offset,
        [](float value) { return std::to_string(value); });
}

std::string ReadU8ValueText(uintptr_t address) {
    return ReadValueDiagnosticText<std::uint8_t>(
        address,
        [](std::uint8_t value) { return std::to_string(static_cast<unsigned>(value)); });
}

std::string ReadU32ValueHexText(uintptr_t address) {
    return ReadValueDiagnosticText<std::uint32_t>(
        address,
        [](std::uint32_t value) { return HexString(static_cast<uintptr_t>(value)); });
}

std::string ReadFloatValueText(uintptr_t address) {
    return ReadValueDiagnosticText<float>(
        address,
        [](float value) { return std::to_string(value); });
}

void AppendMovementControllerSummary(std::ostringstream* out, uintptr_t world_address) {
    if (out == nullptr || world_address == 0) {
        return;
    }

    const auto movement_controller_address = world_address + kActorOwnerMovementControllerOffset;
    uintptr_t primary_list = 0;
    const bool have_primary_list = ProcessMemory::Instance().TryReadField(
        movement_controller_address,
        kMovementControllerPrimaryListOffset,
        &primary_list);
    uintptr_t secondary_list = 0;
    const bool have_secondary_list = ProcessMemory::Instance().TryReadField(
        movement_controller_address,
        kMovementControllerSecondaryListOffset,
        &secondary_list);

    *out << " movement{ctx=" << HexString(movement_controller_address)
         << " primary_count=" << ReadI32FieldText(movement_controller_address, kMovementControllerPrimaryCountOffset)
         << " primary_list=" << (have_primary_list ? HexString(primary_list) : UnreadableMemoryFieldText());

    if (have_primary_list && primary_list != 0) {
        *out << " primary0=" << ReadPointerFieldText(primary_list, 0x0)
             << " primary1=" << ReadPointerFieldText(primary_list, 0x4);
    }

    *out << " secondary_count=" << ReadI32FieldText(movement_controller_address, kMovementControllerSecondaryCountOffset)
         << " secondary_list=" << (have_secondary_list ? HexString(secondary_list) : UnreadableMemoryFieldText());

    if (have_secondary_list && secondary_list != 0) {
        *out << " secondary0=" << ReadPointerFieldText(secondary_list, 0x0)
             << " secondary1=" << ReadPointerFieldText(secondary_list, 0x4);
    }

    *out << "}";
}

void AppendActorCoreStateSummary(std::ostringstream* out, uintptr_t actor_address) {
    if (out == nullptr || actor_address == 0) {
        return;
    }

    *out << " actor_core{cell=" << ReadPointerFieldText(actor_address, kActorGridCellPtrOffset)
         << " owner_field=" << ReadPointerFieldText(actor_address, kActorOwnerOffset)
         << " slot=" << ReadI8FieldText(actor_address, kActorSlotOffset)
         << " world_slot=" << ReadI16FieldText(actor_address, kActorWorldSlotOffset)
         << " radius=" << ReadFloatFieldText(actor_address, kActorCollisionRadiusOffset)
         << " mask=" << ReadU32FieldHexText(actor_address, kActorPrimaryFlagMaskOffset)
         << " mask2=" << ReadU32FieldHexText(actor_address, kActorSecondaryFlagMaskOffset)
         << "}";
}

void AppendGameNpcStateSummary(std::ostringstream* out, uintptr_t actor_address) {
    if (out == nullptr || actor_address == 0) {
        return;
    }

    *out << " gamenpc{source_kind=" << ReadI32FieldText(actor_address, kActorHubVisualSourceKindOffset)
         << " source_profile=" << ReadPointerFieldText(actor_address, kActorHubVisualSourceProfileOffset)
         << " source_aux=" << ReadPointerFieldText(actor_address, kActorHubVisualSourceAuxPointerOffset)
         << " branch=" << ReadU8FieldText(actor_address, kGameNpcBranchStateOffset)
         << " active=" << ReadU8FieldText(actor_address, kGameNpcActiveStateOffset)
         << " desired_yaw=" << ReadFloatFieldText(actor_address, kGameNpcDesiredYawOffset)
         << " source_profile_74_mirror=" << ReadU32FieldHexText(actor_address, kGameNpcSourceProfile74MirrorOffset)
         << " tick_counter=" << ReadI32FieldText(actor_address, kGameNpcTickCounterOffset)
         << " goal_x=" << ReadFloatFieldText(actor_address, kGameNpcGoalXOffset)
         << " goal_y=" << ReadFloatFieldText(actor_address, kGameNpcGoalYOffset)
         << " move_flag=" << ReadU8FieldText(actor_address, kGameNpcMoveFlagOffset)
         << " move_speed=" << ReadFloatFieldText(actor_address, kGameNpcSpeedScalarOffset)
         << " source_profile_56_mirror=" << ReadU32FieldHexText(actor_address, kGameNpcSourceProfile56MirrorOffset)
         << " tracked_slot=" << ReadI8FieldText(actor_address, kGameNpcTrackedSlotOffset)
         << " callback=" << ReadU8FieldText(actor_address, kGameNpcTrackedSlotCallbackOffset)
         << " render_drive_effect_timer=" << ReadI32FieldText(actor_address, kGameNpcLateTimerOffset)
         << "}";
}

std::string BuildWizardBotCrashSummaryLocked() {
    std::ostringstream out;
    out << "participant_snapshots count=" << g_participant_gameplay_snapshots.size()
        << " gameplay_injection_initialized="
        << (g_gameplay_keyboard_injection.initialized ? "true" : "false");
    for (const auto& snapshot : g_participant_gameplay_snapshots) {
        out << "\r\n"
            << "  bot_id=" << snapshot.bot_id
            << " element_id=" << snapshot.character_profile.element_id
            << " discipline_id=" << static_cast<std::int32_t>(snapshot.character_profile.discipline_id)
            << " materialized=" << (snapshot.entity_materialized ? "true" : "false")
            << " moving=" << (snapshot.moving ? "true" : "false")
            << " slot=" << snapshot.gameplay_slot
            << " actor_slot=" << snapshot.actor_slot
            << " actor=" << HexString(snapshot.actor_address)
            << " world=" << HexString(snapshot.world_address)
            << " progression=" << HexString(snapshot.progression_runtime_state_address)
            << " equip=" << HexString(snapshot.equip_runtime_state_address)
            << " source=" << HexString(snapshot.hub_visual_source_profile_address)
            << " attach=" << HexString(snapshot.hub_visual_attachment_ptr)
            << " variants="
            << std::to_string(snapshot.render_variant_primary) + "/" +
                   std::to_string(snapshot.render_variant_secondary) + "/" +
                   std::to_string(snapshot.render_weapon_type) + "/" +
                   std::to_string(snapshot.render_variant_tertiary) + "/" +
                   std::to_string(snapshot.render_selection_byte)
            << " anim=" << snapshot.resolved_animation_state_id
            << " desc=0x" << HexString(snapshot.hub_visual_descriptor_signature)
            << " pos=(" << snapshot.x << "," << snapshot.y << ")"
            << " heading=" << snapshot.heading;
        AppendEquipVisualLaneSummary(&out, "primary", snapshot.primary_visual_lane);
        AppendEquipVisualLaneSummary(&out, "secondary", snapshot.secondary_visual_lane);
        AppendEquipVisualLaneSummary(&out, "attachment", snapshot.attachment_visual_lane);
        AppendActorCoreStateSummary(&out, snapshot.actor_address);
        AppendGameNpcStateSummary(&out, snapshot.actor_address);
        AppendMovementControllerSummary(&out, snapshot.world_address);
    }
    return out.str();
}

void RefreshWizardBotCrashSummaryLocked() {
    SetCrashContextSummary(BuildWizardBotCrashSummaryLocked());
}
