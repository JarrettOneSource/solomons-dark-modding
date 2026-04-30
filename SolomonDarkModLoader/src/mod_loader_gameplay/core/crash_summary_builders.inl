void AppendMovementControllerSummary(std::ostringstream* out, uintptr_t world_address) {
    if (out == nullptr || world_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    const auto movement_controller_address = world_address + kActorOwnerMovementControllerOffset;
    const auto primary_count = memory.ReadFieldOr<std::int32_t>(movement_controller_address, 0x40, 0);
    const auto primary_list = memory.ReadFieldOr<uintptr_t>(movement_controller_address, 0x4C, 0);
    const auto secondary_count = memory.ReadFieldOr<std::int32_t>(movement_controller_address, 0x70, 0);
    const auto secondary_list = memory.ReadFieldOr<uintptr_t>(movement_controller_address, 0x7C, 0);

    *out << " movement{ctx=" << HexString(movement_controller_address)
         << " primary_count=" << primary_count
         << " primary_list=" << HexString(primary_list);

    if (primary_list != 0) {
        *out << " primary0=" << HexString(memory.ReadFieldOr<uintptr_t>(primary_list, 0x0, 0))
             << " primary1=" << HexString(memory.ReadFieldOr<uintptr_t>(primary_list, 0x4, 0));
    }

    *out << " secondary_count=" << secondary_count
         << " secondary_list=" << HexString(secondary_list);

    if (secondary_list != 0) {
        *out << " secondary0=" << HexString(memory.ReadFieldOr<uintptr_t>(secondary_list, 0x0, 0))
             << " secondary1=" << HexString(memory.ReadFieldOr<uintptr_t>(secondary_list, 0x4, 0));
    }

    *out << "}";
}

void AppendActorCoreStateSummary(std::ostringstream* out, uintptr_t actor_address) {
    if (out == nullptr || actor_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    *out << " actor_core{cell=" << HexString(memory.ReadFieldOr<uintptr_t>(actor_address, 0x54, 0))
         << " owner_field=" << HexString(memory.ReadFieldOr<uintptr_t>(actor_address, 0x58, 0))
         << " slot=" << std::to_string(static_cast<int>(memory.ReadFieldOr<std::int8_t>(
                actor_address,
                kActorSlotOffset,
                -1)))
         << " world_slot=" << std::to_string(static_cast<int>(memory.ReadFieldOr<std::int16_t>(
                actor_address,
                kActorWorldSlotOffset,
                static_cast<std::int16_t>(-1))))
         << " radius=" << std::to_string(memory.ReadFieldOr<float>(actor_address, kActorCollisionRadiusOffset, 0.0f))
         << " mask=" << HexString(static_cast<uintptr_t>(memory.ReadFieldOr<std::uint32_t>(
                actor_address,
                kActorPrimaryFlagMaskOffset,
                0)))
         << " mask2=" << HexString(static_cast<uintptr_t>(memory.ReadFieldOr<std::uint32_t>(
                actor_address,
                kActorSecondaryFlagMaskOffset,
                0)))
         << "}";
}

void AppendGameNpcStateSummary(std::ostringstream* out, uintptr_t actor_address) {
    if (out == nullptr || actor_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    *out << " gamenpc{source_kind=" << std::to_string(memory.ReadFieldOr<std::int32_t>(actor_address, 0x174, 0))
         << " source_profile=" << HexString(memory.ReadFieldOr<uintptr_t>(actor_address, 0x178, 0))
         << " source_aux=" << HexString(memory.ReadFieldOr<uintptr_t>(actor_address, 0x17C, 0))
         << " branch=" << std::to_string(memory.ReadFieldOr<std::uint8_t>(actor_address, 0x181, 0))
         << " active=" << std::to_string(memory.ReadFieldOr<std::uint8_t>(actor_address, 0x180, 0))
         << " desired_yaw=" << std::to_string(memory.ReadFieldOr<float>(actor_address, 0x188, 0.0f))
         << " source_profile_74_mirror=" << HexString(memory.ReadFieldOr<std::uint32_t>(actor_address, 0x194, 0))
         << " tick_counter=" << std::to_string(memory.ReadFieldOr<std::int32_t>(actor_address, 0x18C, 0))
         << " goal_x=" << std::to_string(memory.ReadFieldOr<float>(actor_address, 0x19C, 0.0f))
         << " goal_y=" << std::to_string(memory.ReadFieldOr<float>(actor_address, 0x1A0, 0.0f))
         << " move_flag=" << std::to_string(memory.ReadFieldOr<std::uint8_t>(actor_address, 0x198, 0))
         << " move_speed=" << std::to_string(memory.ReadFieldOr<float>(actor_address, 0x1B4, 0.0f))
         << " source_profile_56_mirror=" << HexString(memory.ReadFieldOr<std::uint32_t>(actor_address, 0x1C0, 0))
         << " tracked_slot=" << std::to_string(memory.ReadFieldOr<std::int8_t>(actor_address, 0x1C2, -1))
         << " callback=" << std::to_string(memory.ReadFieldOr<std::uint8_t>(actor_address, 0x1C3, 0))
         << " render_drive_effect_timer=" << std::to_string(memory.ReadFieldOr<std::int32_t>(actor_address, 0x1C4, 0))
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
