int ResolveCombatSelectionStateForSkillId(std::int32_t skill_id) {
    switch (skill_id) {
    case 0x18:
    case 0x20:
    case 0x28:
        return skill_id;
    case 0x3F2:
        return 0x08;
    case 0x3F3:
        return 0x10;
    case 0x3F5:
        return 0x18;
    case 0x3F4:
        return 0x20;
    case 0x3F6:
        return 0x28;
    case 0x3EB:
    case 0x3EC:
    case 0x3ED:
    case 0x3EE:
    case 0x3EF:
    case 0x3F0:
    case 0x3F1:
        return 0x34;
    default:
        return -1;
    }
}

int ResolveOngoingCastSelectionState(
    const ParticipantEntityBinding::OngoingCastState& ongoing) {
    if (ongoing.selection_state_target != kUnknownAnimationStateId &&
        ongoing.selection_state_target >= 0) {
        return ongoing.selection_state_target;
    }

    const auto active_skill_id =
        ongoing.uses_dispatcher_skill_id && ongoing.dispatcher_skill_id > 0
            ? ongoing.dispatcher_skill_id
            : ongoing.skill_id;
    return ResolveCombatSelectionStateForSkillId(active_skill_id);
}

void ReapplyOngoingCastSelectionState(
    ParticipantEntityBinding* binding,
    uintptr_t actor_address,
    const ParticipantEntityBinding::OngoingCastState& ongoing,
    bool write_actor_selection_state) {
    if (binding == nullptr ||
        actor_address == 0 ||
        !ongoing.gameplay_selection_state_override_active ||
        binding->gameplay_slot < 0) {
        return;
    }

    const auto selection_state = ResolveOngoingCastSelectionState(ongoing);
    if (selection_state < 0) {
        return;
    }

    if (write_actor_selection_state) {
        (void)TryWriteActorAnimationStateIdDirect(actor_address, selection_state);
    }

    std::string selection_error;
    (void)TryWriteGameplaySelectionStateForSlot(
        binding->gameplay_slot,
        selection_state,
        &selection_error);
}

std::string DescribeGameplaySlotCastStartupWindow(uintptr_t actor_address) {
    if (actor_address == 0) {
        return "actor=0x0";
    }

    auto& memory = ProcessMemory::Instance();
    const auto gameplay_global_flag_1abe =
        memory.ReadValueOr<std::uint8_t>(
            memory.ResolveGameAddressOrZero(0x0081C264 + 0x1ABE),
            0);
    const auto gameplay_global_flag_1abd =
        memory.ReadValueOr<std::uint8_t>(
            memory.ResolveGameAddressOrZero(0x0081C264 + 0x1ABD),
            0);
    const auto gameplay_global_flag_85 =
        memory.ReadValueOr<std::uint8_t>(
            memory.ResolveGameAddressOrZero(0x0081C264 + 0x85),
            0);
    const auto selection_ptr =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorAnimationSelectionStateOffset, 0);
    const auto control_brain_ptr =
        memory.ReadFieldOr<uintptr_t>(actor_address, 0x21C, 0);
    const auto control_brain_value =
        control_brain_ptr != 0 && memory.IsReadableRange(control_brain_ptr, sizeof(uintptr_t))
            ? memory.ReadValueOr<std::uint32_t>(control_brain_ptr, 0xFFFFFFFFu)
            : 0xFFFFFFFFu;
    const auto actor_dc_ptr =
        memory.ReadFieldOr<uintptr_t>(actor_address, 0xDC, 0);
    const auto actor_dc_vtable =
        actor_dc_ptr != 0 && memory.IsReadableRange(actor_dc_ptr, sizeof(uintptr_t))
            ? memory.ReadValueOr<uintptr_t>(actor_dc_ptr, 0)
            : 0;
    const auto actor_dc_slot_10 =
        actor_dc_ptr != 0 && memory.IsReadableRange(actor_dc_ptr + 0x10, sizeof(uintptr_t))
            ? memory.ReadValueOr<uintptr_t>(actor_dc_ptr + 0x10, 0)
            : 0;
    const auto actor_dc_callback_10 =
        actor_dc_vtable != 0 && memory.IsReadableRange(actor_dc_vtable + 0x10, sizeof(uintptr_t))
            ? memory.ReadValueOr<uintptr_t>(actor_dc_vtable + 0x10, 0)
            : 0;
    const auto progression_handle = memory.ReadFieldOr<uintptr_t>(actor_address, 0x300, 0);
    auto progression_runtime = memory.ReadFieldOr<uintptr_t>(actor_address, 0x200, 0);
    if (progression_runtime == 0 &&
        progression_handle != 0 &&
        memory.IsReadableRange(progression_handle, sizeof(uintptr_t))) {
        progression_runtime = memory.ReadValueOr<uintptr_t>(progression_handle, 0);
    }
    const auto read_progression_u32 = [&](std::size_t offset) -> std::uint32_t {
        return progression_runtime != 0 &&
               memory.IsReadableRange(progression_runtime + offset, sizeof(std::uint32_t))
            ? memory.ReadValueOr<std::uint32_t>(progression_runtime + offset, 0)
            : 0;
    };
    const auto read_progression_float = [&](std::size_t offset) -> float {
        return progression_runtime != 0 &&
               memory.IsReadableRange(progression_runtime + offset, sizeof(float))
            ? memory.ReadValueOr<float>(progression_runtime + offset, 0.0f)
            : 0.0f;
    };
    std::string selection_summary = "sel_ptr=" + HexString(selection_ptr);
    if (selection_ptr != 0) {
        selection_summary +=
            " sel_id=" + std::to_string(memory.ReadValueOr<int>(selection_ptr + 0x0, -9999)) +
            " sel_group=" + HexString(memory.ReadValueOr<std::uint8_t>(selection_ptr + 0x4, 0xFF)) +
            " sel_slot=" + HexString(memory.ReadValueOr<std::uint16_t>(selection_ptr + 0x6, 0xFFFF)) +
            " sel_t8=" + std::to_string(memory.ReadValueOr<int>(selection_ptr + 0x8, 0)) +
            " sel_tC=" + std::to_string(memory.ReadValueOr<int>(selection_ptr + 0xC, 0)) +
            " sel_t10=" + std::to_string(memory.ReadValueOr<int>(selection_ptr + 0x10, 0)) +
            " sel_t14=" + std::to_string(memory.ReadValueOr<int>(selection_ptr + 0x14, 0)) +
            " sel_a1c=" + std::to_string(memory.ReadValueOr<float>(selection_ptr + 0x1C, 0.0f)) +
            " sel_a20=" + std::to_string(memory.ReadValueOr<float>(selection_ptr + 0x20, 0.0f)) +
            " sel_f24=" + HexString(memory.ReadValueOr<std::uint8_t>(selection_ptr + 0x24, 0)) +
            " sel_v28=" + std::to_string(memory.ReadValueOr<float>(selection_ptr + 0x28, 0.0f)) +
            " sel_v2c=" + std::to_string(memory.ReadValueOr<float>(selection_ptr + 0x2C, 0.0f)) +
            " sel_v30=" + std::to_string(memory.ReadValueOr<float>(selection_ptr + 0x30, 0.0f)) +
            " sel_v34=" + std::to_string(memory.ReadValueOr<float>(selection_ptr + 0x34, 0.0f));
    }

    return
        "skill=" + std::to_string(memory.ReadFieldOr<std::int32_t>(actor_address, kActorPrimarySkillIdOffset, 0)) +
        " prev=" + std::to_string(memory.ReadFieldOr<std::int32_t>(actor_address, kActorPrimarySkillIdOffset + sizeof(std::int32_t), 0)) +
        " c21c=" + HexString(control_brain_ptr) +
        " c21c_val=" + HexString(control_brain_value) +
        " dc=" + HexString(actor_dc_ptr) +
        " dc_vt=" + HexString(actor_dc_vtable) +
        " dc_slot10=" + HexString(actor_dc_slot_10) +
        " dc_vt_cb10=" + HexString(actor_dc_callback_10) +
        " g1abe=" + HexString(gameplay_global_flag_1abe) +
        " g1abd=" + HexString(gameplay_global_flag_1abd) +
        " g85=" + HexString(gameplay_global_flag_85) +
        " e4=" + HexString(memory.ReadFieldOr<std::uint32_t>(actor_address, 0xE4, 0)) +
        " e8=" + HexString(memory.ReadFieldOr<std::uint32_t>(actor_address, 0xE8, 0)) +
        " a160=" + HexString(memory.ReadFieldOr<std::uint8_t>(actor_address, 0x160, 0)) +
        " a164=" + HexString(memory.ReadFieldOr<std::uint32_t>(actor_address, 0x164, 0)) +
        " a168=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorCurrentTargetActorOffset, 0)) +
        " a1ec=" + HexString(memory.ReadFieldOr<std::uint8_t>(actor_address, 0x1EC, 0)) +
        " a258=" + HexString(memory.ReadFieldOr<std::uint32_t>(actor_address, kActorContinuousPrimaryModeOffset, 0)) +
        " a264=" + HexString(memory.ReadFieldOr<std::uint32_t>(actor_address, kActorContinuousPrimaryActiveOffset, 0)) +
        " g27c=" + HexString(memory.ReadFieldOr<std::uint8_t>(actor_address, kActorActiveCastGroupByteOffset, 0xFF)) +
        " s27e=" + HexString(memory.ReadFieldOr<std::uint16_t>(actor_address, kActorActiveCastSlotShortOffset, 0xFFFF)) +
        " prog=" + HexString(progression_runtime) +
        " ph=" + HexString(progression_handle) +
        " p750=" + HexString(read_progression_u32(0x750)) +
        " p8a8=" + std::to_string(read_progression_float(0x8A8)) +
        " p8ac=" + std::to_string(read_progression_float(0x8AC)) +
        " p8b0=" + std::to_string(read_progression_float(0x8B0)) +
        " p8b4=" + std::to_string(read_progression_float(0x8B4)) +
        " f1b4=" + std::to_string(memory.ReadFieldOr<float>(actor_address, 0x1B4, 0.0f)) +
        " f1b8=" + std::to_string(memory.ReadFieldOr<float>(actor_address, 0x1B8, 0.0f)) +
        " f278=" + std::to_string(memory.ReadFieldOr<std::uint32_t>(actor_address, 0x278, 0)) +
        " f28c=" + std::to_string(memory.ReadFieldOr<float>(actor_address, 0x28C, 0.0f)) +
        " f290=" + std::to_string(memory.ReadFieldOr<float>(actor_address, 0x290, 0.0f)) +
        " f294=" + std::to_string(memory.ReadFieldOr<float>(actor_address, 0x294, 0.0f)) +
        " f298=" + std::to_string(memory.ReadFieldOr<std::uint32_t>(actor_address, 0x298, 0)) +
        " f29c=" + std::to_string(memory.ReadFieldOr<float>(actor_address, 0x29C, 0.0f)) +
        " f2a0=" + std::to_string(memory.ReadFieldOr<float>(actor_address, 0x2A0, 0.0f)) +
        " f2a4=" + std::to_string(memory.ReadFieldOr<float>(actor_address, 0x2A4, 0.0f)) +
        " aimx=" + std::to_string(memory.ReadFieldOr<float>(actor_address, kActorAimTargetXOffset, 0.0f)) +
        " aimy=" + std::to_string(memory.ReadFieldOr<float>(actor_address, kActorAimTargetYOffset, 0.0f)) +
        " aux0=" + HexString(memory.ReadFieldOr<std::uint32_t>(actor_address, kActorAimTargetAux0Offset, 0)) +
        " aux1=" + HexString(memory.ReadFieldOr<std::uint32_t>(actor_address, kActorAimTargetAux1Offset, 0)) +
        " spread=" + HexString(memory.ReadFieldOr<std::uint8_t>(actor_address, kActorCastSpreadModeByteOffset, 0)) +
        " f2c8=" + std::to_string(memory.ReadFieldOr<std::uint32_t>(actor_address, 0x2C8, 0)) +
        " f2cc=" + std::to_string(memory.ReadFieldOr<float>(actor_address, 0x2CC, 0.0f)) +
        " f2d0=" + std::to_string(memory.ReadFieldOr<float>(actor_address, 0x2D0, 0.0f)) +
        " f2d4=" + std::to_string(memory.ReadFieldOr<float>(actor_address, 0x2D4, 0.0f)) +
        " f2d8=" + std::to_string(memory.ReadFieldOr<float>(actor_address, 0x2D8, 0.0f)) +
        " heading=" + std::to_string(memory.ReadFieldOr<float>(actor_address, kActorHeadingOffset, 0.0f)) +
        " " + selection_summary;
}

bool SkillRequiresLocalSlotDuringNativeTick(std::int32_t skill_id) {
    // These stock spell families keep doing useful native work after the
    // startup edge. Gameplay-slot bots must keep masquerading as slot 0 for
    // that active window or projectile/cone emission can silently stop.
    switch (skill_id) {
    case 0x3EF:
    case 0x3F2:
    case 0x3F3:
    case 0x3F4:
    case 0x3F5:
    case 0x3F6:
    case 0x18:
    case 0x20:
    case 0x28:
        return true;
    default:
        return false;
    }
}

bool SkillRequiresHeldCastInputDuringNativeTick(std::int32_t skill_id) {
    // These stock primaries keep doing native work only while the gameplay cast
    // input is held. This is separate from live target tracking: projectile
    // families still keep their startup target captured, while channel families
    // keep refreshing their victim/aim lane.
    switch (skill_id) {
    case 0x3F2: // ether pure primary projectile stream
    case 0x3F3: // fire pure primary projectile stream
    case 0x3F4: // water pure primary
    case 0x3F5: // air pure primary
    case 0x18: // air primary handler
    case 0x20: // water primary handler
        return true;
    default:
        return false;
    }
}

bool SkillTracksLiveTargetDuringNativeTick(std::int32_t skill_id) {
    switch (skill_id) {
    case 0x3F4: // water pure primary cone
    case 0x3F5: // air pure primary beam
    case 0x18: // air primary handler
    case 0x20: // water primary handler
        return true;
    default:
        return false;
    }
}

bool SkillRequiresBoundedHeldCastInputDuringNativeTick(std::int32_t skill_id) {
    // Earth is a projectile/effect primary, but the stock dispatcher needs the
    // cast input held until the native boulder object reaches its configured
    // max size. The release path watches the live object instead of assuming a
    // fixed gesture duration.
    switch (skill_id) {
    case 0x3F6: // earth pure primary build id
    case 0x28: // earth primary handler
        return true;
    default:
        return false;
    }
}

bool SkillRequiresSyntheticCastInputDuringNativeTick(std::int32_t skill_id) {
    return SkillRequiresHeldCastInputDuringNativeTick(skill_id) ||
           SkillRequiresBoundedHeldCastInputDuringNativeTick(skill_id);
}

bool OngoingCastShouldDriveSyntheticCastInput(
    const ParticipantEntityBinding::OngoingCastState& ongoing) {
    const auto active_skill_id =
        ongoing.uses_dispatcher_skill_id && ongoing.dispatcher_skill_id > 0
            ? ongoing.dispatcher_skill_id
            : ongoing.skill_id;
    if (ongoing.startup_in_progress) {
        return true;
    }
    if (SkillRequiresHeldCastInputDuringNativeTick(active_skill_id)) {
        return true;
    }
    if (SkillRequiresBoundedHeldCastInputDuringNativeTick(active_skill_id)) {
        return !ongoing.bounded_release_requested;
    }
    return false;
}

int ResolveBotCastGestureTicks(std::int32_t skill_id) {
    // The bot cast request models one primary-input gesture. Stock held spells
    // do not self-release while input is held, so the loader must release the
    // synthetic gesture once the native active window has had time to run.
    switch (skill_id) {
    case 0x3EF:
    case 0x3F2: // ether pure primary projectile
    case 0x3F3: // fire pure primary projectile
        return 36;
    default:
        return ParticipantEntityBinding::OngoingCastState::kMaxTicksWaiting;
    }
}

int ResolveBotCastSafetyCapTicks(std::int32_t skill_id) {
    switch (skill_id) {
    case 0x3F6: // earth pure primary build id
    case 0x28: // earth primary handler
        return 1200;
    default:
        return ParticipantEntityBinding::OngoingCastState::kMaxTicksWaiting;
    }
}

std::int32_t ResolveOngoingNativeTickSkillId(
    const ParticipantEntityBinding::OngoingCastState& ongoing) {
    return ongoing.uses_dispatcher_skill_id && ongoing.dispatcher_skill_id > 0
        ? ongoing.dispatcher_skill_id
        : ongoing.skill_id;
}

bool OngoingCastShouldUseLiveFacingTarget(
    const ParticipantEntityBinding::OngoingCastState& ongoing) {
    return SkillTracksLiveTargetDuringNativeTick(
        ResolveOngoingNativeTickSkillId(ongoing));
}

bool OngoingCastShouldRefreshNativeTargetState(
    const ParticipantEntityBinding::OngoingCastState& ongoing) {
    const auto active_skill_id = ResolveOngoingNativeTickSkillId(ongoing);
    if (SkillRequiresBoundedHeldCastInputDuringNativeTick(active_skill_id) &&
        ongoing.bounded_release_requested) {
        return false;
    }
    return ongoing.startup_in_progress ||
           SkillTracksLiveTargetDuringNativeTick(active_skill_id) ||
           SkillRequiresBoundedHeldCastInputDuringNativeTick(active_skill_id);
}

uintptr_t ResolveOngoingCastNativeTargetActor(
    const ParticipantEntityBinding* binding,
    const ParticipantEntityBinding::OngoingCastState& ongoing) {
    if (binding != nullptr &&
        OngoingCastShouldUseLiveFacingTarget(ongoing) &&
        binding->facing_target_actor_address != 0) {
        return binding->facing_target_actor_address;
    }
    if (ongoing.target_actor_address != 0) {
        return ongoing.target_actor_address;
    }
    return binding != nullptr ? binding->facing_target_actor_address : 0;
}

int ResolveMaxStartupTicksWaiting(std::int32_t skill_id) {
    if (skill_id == 0x3EF) {
        // Iceblast advances an internal startup counter at actor+0x278 and can
        // legitimately defer projectile allocation past the generic 12-tick
        // window. Cutting it off early produces the exact "animation only,
        // nothing emitted" symptom we were seeing in live runs.
        return 90;
    }
    return ParticipantEntityBinding::OngoingCastState::kMaxStartupTicksWaiting;
}

void PrimeGameplaySlotPostGateDispatchState(uintptr_t actor_address, std::int32_t skill_id) {
    if (actor_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    const auto kActorPreviousSkillIdOffset =
        kActorPrimarySkillIdOffset + sizeof(std::int32_t);
    constexpr std::size_t kActorPostGateActiveByteOffset = 0x26C;
    constexpr std::size_t kActorStartupCounterOffset = 0x278;

    (void)memory.TryWriteField<std::int32_t>(
        actor_address,
        kActorPrimarySkillIdOffset,
        skill_id);
    (void)memory.TryWriteField<std::int32_t>(
        actor_address,
        kActorPreviousSkillIdOffset,
        0);
    (void)memory.TryWriteField<std::uint8_t>(
        actor_address,
        kActorPostGateActiveByteOffset,
        static_cast<std::uint8_t>(1));
    (void)memory.TryWriteField<std::int32_t>(
        actor_address,
        kActorStartupCounterOffset,
        0);
    if (!SkillRequiresNativeActorTargetHandle(skill_id)) {
        (void)memory.TryWriteField<std::uint8_t>(
            actor_address,
            kActorSpellTargetGroupByteOffset,
            kTargetHandleGroupSentinel);
        (void)memory.TryWriteField<std::uint16_t>(
            actor_address,
            kActorSpellTargetSlotShortOffset,
            kTargetHandleSlotSentinel);
    }
}

void RestoreSelectionBrainAfterCast(
    const ParticipantEntityBinding::OngoingCastState& state) {
    if (!state.selection_brain_override_active || state.selection_state_pointer == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    (void)memory.TryWriteField<std::uint8_t>(
        state.selection_state_pointer,
        0x04,
        state.selection_target_group_before);
    (void)memory.TryWriteField<std::uint16_t>(
        state.selection_state_pointer,
        0x06,
        state.selection_target_slot_before);
    (void)memory.TryWriteField<std::int32_t>(
        state.selection_state_pointer,
        0x08,
        state.selection_retarget_ticks_before);
    (void)memory.TryWriteField<std::int32_t>(
        state.selection_state_pointer,
        0x0C,
        state.selection_target_cooldown_before);
    (void)memory.TryWriteField<std::int32_t>(
        state.selection_state_pointer,
        0x10,
        state.selection_target_extra_before);
    (void)memory.TryWriteField<std::int32_t>(
        state.selection_state_pointer,
        0x14,
        state.selection_target_flags_before);
}

void ClearSelectionBrainTarget(uintptr_t selection_state_pointer) {
    if (selection_state_pointer == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    (void)memory.TryWriteField<std::uint8_t>(selection_state_pointer, 0x04, 0xFF);
    (void)memory.TryWriteField<std::uint16_t>(selection_state_pointer, 0x06, 0xFFFF);
    (void)memory.TryWriteField<std::int32_t>(
        selection_state_pointer,
        0x08,
        kSuppressedSelectionRetargetTicks);
    (void)memory.TryWriteField<std::int32_t>(selection_state_pointer, 0x0C, 0);
    (void)memory.TryWriteField<std::int32_t>(selection_state_pointer, 0x10, 0);
    (void)memory.TryWriteField<std::int32_t>(selection_state_pointer, 0x14, 0);
}

void RefreshSelectionBrainTargetForOngoingCast(
    const ParticipantEntityBinding::OngoingCastState& state) {
    if (!state.active || !state.selection_target_seed_active ||
        state.selection_state_pointer == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    const auto hold_ticks =
        state.selection_target_hold_ticks > 0 ? state.selection_target_hold_ticks : 60;
    (void)memory.TryWriteField<std::uint8_t>(
        state.selection_state_pointer,
        0x04,
        state.selection_target_group_seed);
    (void)memory.TryWriteField<std::uint16_t>(
        state.selection_state_pointer,
        0x06,
        state.selection_target_slot_seed);
    (void)memory.TryWriteField<std::int32_t>(state.selection_state_pointer, 0x08, hold_ticks);
    (void)memory.TryWriteField<std::int32_t>(state.selection_state_pointer, 0x0C, 0);
    (void)memory.TryWriteField<std::int32_t>(state.selection_state_pointer, 0x10, 0);
    (void)memory.TryWriteField<std::int32_t>(state.selection_state_pointer, 0x14, 0);
}

void RestoreSelectionStateObjectAfterCast(
    const ParticipantEntityBinding::OngoingCastState& state) {
    if (!state.selection_state_object_snapshot_valid || state.selection_state_pointer == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    (void)memory.TryWrite(
        state.selection_state_pointer,
        state.selection_state_object_snapshot.data(),
        state.selection_state_object_snapshot.size());
}

void PrimeSelectionBrainForCastStartup(
    uintptr_t actor_address,
    uintptr_t selection_pointer,
    uintptr_t target_actor_address,
    ParticipantEntityBinding::OngoingCastState* ongoing) {
    if (selection_pointer == 0 || ongoing == nullptr) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    const auto actor_owner =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, 0);
    const auto target_owner =
        memory.ReadFieldOr<uintptr_t>(target_actor_address, kActorOwnerOffset, 0);
    const auto target_group =
        memory.ReadFieldOr<std::uint8_t>(
            target_actor_address,
            kActorSlotOffset,
            kTargetHandleGroupSentinel);
    const auto target_slot =
        memory.ReadFieldOr<std::uint16_t>(target_actor_address, kActorWorldSlotOffset, kTargetHandleSlotSentinel);
    const bool have_explicit_target_handle =
        target_actor_address != 0 &&
        actor_owner != 0 &&
        actor_owner == target_owner &&
        target_group != kTargetHandleGroupSentinel &&
        target_slot != kTargetHandleSlotSentinel;

    ongoing->selection_target_group_before =
        memory.ReadValueOr<std::uint8_t>(selection_pointer + 0x04, kTargetHandleGroupSentinel);
    ongoing->selection_target_slot_before =
        memory.ReadValueOr<std::uint16_t>(selection_pointer + 0x06, kTargetHandleSlotSentinel);
    ongoing->selection_retarget_ticks_before =
        memory.ReadValueOr<std::int32_t>(selection_pointer + 0x08, 0);
    ongoing->selection_target_cooldown_before =
        memory.ReadValueOr<std::int32_t>(selection_pointer + 0x0C, 0);
    ongoing->selection_target_extra_before =
        memory.ReadValueOr<std::int32_t>(selection_pointer + 0x10, 0);
    ongoing->selection_target_flags_before =
        memory.ReadValueOr<std::int32_t>(selection_pointer + 0x14, 0);
    ongoing->selection_brain_override_active = true;

    // PlayerActorTick clears actor+0x270 every tick and only rebuilds it when
    // FUN_0052C910 produces a non-zero control vector. That helper drives from
    // the actor-owned +0x21C control brain. The stock function decrements +0x08
    // first and only keeps the cached target handle on the cooldown path; when
    // +0x08 hits zero it re-runs candidate search and overwrites +0x04/+0x06.
    // For pure-primary bot startup, the Lua brain has already picked the real
    // hostile. Seed that exact stock target handle into +0x04/+0x06 and keep
    // +0x08 positive so stock stays on the "use cached target" path instead of
    // discarding it before the cast gate evaluates cVar5.
    if (have_explicit_target_handle) {
        ongoing->selection_target_seed_active = true;
        ongoing->selection_target_group_seed = target_group;
        ongoing->selection_target_slot_seed = target_slot;
        ongoing->selection_target_hold_ticks = 60;
        (void)memory.TryWriteField<std::uint8_t>(selection_pointer, 0x04, target_group);
        (void)memory.TryWriteField<std::uint16_t>(selection_pointer, 0x06, target_slot);
        (void)memory.TryWriteField<std::int32_t>(selection_pointer, 0x08, ongoing->selection_target_hold_ticks);
    } else {
        ongoing->selection_target_seed_active = false;
        ongoing->selection_target_group_seed = kTargetHandleGroupSentinel;
        ongoing->selection_target_slot_seed = kTargetHandleSlotSentinel;
        ongoing->selection_target_hold_ticks = 0;
        (void)memory.TryWriteField<std::uint8_t>(
            selection_pointer,
            0x04,
            kTargetHandleGroupSentinel);
        (void)memory.TryWriteField<std::uint16_t>(
            selection_pointer,
            0x06,
            kTargetHandleSlotSentinel);
        (void)memory.TryWriteField<std::int32_t>(selection_pointer, 0x08, 0);
    }
    (void)memory.TryWriteField<std::int32_t>(selection_pointer, 0x0C, 0);
    (void)memory.TryWriteField<std::int32_t>(selection_pointer, 0x10, 0);
    (void)memory.TryWriteField<std::int32_t>(selection_pointer, 0x14, 0);
}
