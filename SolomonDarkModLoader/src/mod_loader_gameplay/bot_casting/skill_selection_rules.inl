int ResolveOngoingCastSelectionState(
    const ParticipantEntityBinding::OngoingCastState& ongoing) {
    if (ongoing.selection_state_target != kUnknownAnimationStateId &&
        ongoing.selection_state_target >= 0) {
        return ongoing.selection_state_target;
    }

    return -1;
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
    const auto unreadable = []() { return std::string("unreadable"); };
    const auto read_u8_hex = [&](uintptr_t address) -> std::string {
        std::uint8_t value = 0;
        return address != 0 && memory.TryReadValue(address, &value)
            ? HexString(value)
            : unreadable();
    };
    const auto read_u16_hex = [&](uintptr_t address) -> std::string {
        std::uint16_t value = 0;
        return address != 0 && memory.TryReadValue(address, &value)
            ? HexString(value)
            : unreadable();
    };
    const auto read_u32_hex = [&](uintptr_t address) -> std::string {
        std::uint32_t value = 0;
        return address != 0 && memory.TryReadValue(address, &value)
            ? HexString(value)
            : unreadable();
    };
    const auto read_ptr_hex = [&](uintptr_t address) -> std::string {
        uintptr_t value = 0;
        return address != 0 && memory.TryReadValue(address, &value)
            ? HexString(value)
            : unreadable();
    };
    const auto read_i32_text = [&](uintptr_t address) -> std::string {
        std::int32_t value = 0;
        return address != 0 && memory.TryReadValue(address, &value)
            ? std::to_string(value)
            : unreadable();
    };
    const auto read_float_text = [&](uintptr_t address) -> std::string {
        float value = 0.0f;
        return address != 0 && memory.TryReadValue(address, &value) && std::isfinite(value)
            ? std::to_string(value)
            : unreadable();
    };
    const auto field_u8_hex = [&](std::size_t offset) -> std::string {
        std::uint8_t value = 0;
        return memory.TryReadField(actor_address, offset, &value)
            ? HexString(value)
            : unreadable();
    };
    const auto field_i8_text = [&](std::size_t offset) -> std::string {
        std::int8_t value = 0;
        return memory.TryReadField(actor_address, offset, &value)
            ? std::to_string(static_cast<int>(value))
            : unreadable();
    };
    const auto field_i32_text = [&](std::size_t offset) -> std::string {
        std::int32_t value = 0;
        return memory.TryReadField(actor_address, offset, &value)
            ? std::to_string(value)
            : unreadable();
    };
    const auto field_u32_hex = [&](std::size_t offset) -> std::string {
        std::uint32_t value = 0;
        return memory.TryReadField(actor_address, offset, &value)
            ? HexString(value)
            : unreadable();
    };
    const auto field_u32_text = [&](std::size_t offset) -> std::string {
        std::uint32_t value = 0;
        return memory.TryReadField(actor_address, offset, &value)
            ? std::to_string(value)
            : unreadable();
    };
    const auto field_u16_hex = [&](std::size_t offset) -> std::string {
        std::uint16_t value = 0;
        return memory.TryReadField(actor_address, offset, &value)
            ? HexString(value)
            : unreadable();
    };
    const auto field_ptr_hex = [&](std::size_t offset) -> std::string {
        uintptr_t value = 0;
        return memory.TryReadField(actor_address, offset, &value)
            ? HexString(value)
            : unreadable();
    };
    const auto field_float_text = [&](std::size_t offset) -> std::string {
        float value = 0.0f;
        return TryReadFiniteFloatField(actor_address, offset, &value)
            ? std::to_string(value)
            : unreadable();
    };
    const auto gameplay_global_flag_1abe =
        read_u8_hex(memory.ResolveGameAddressOrZero(kGameObjectGlobal + kGameplayPrimaryGateBlockFlagOffset));
    const auto gameplay_global_flag_1abd =
        read_u8_hex(memory.ResolveGameAddressOrZero(kGameObjectGlobal + kGameplayCastUiBlockFlagOffset));
    const auto gameplay_global_flag_85 =
        read_u8_hex(memory.ResolveGameAddressOrZero(kGameObjectGlobal + kGameplayInputGateFlagOffset));
    uintptr_t selection_ptr = 0;
    const bool selection_ptr_readable =
        memory.TryReadField(actor_address, kActorAnimationSelectionStateOffset, &selection_ptr);
    const auto selection_ptr_text =
        selection_ptr_readable ? HexString(selection_ptr) : unreadable();
    uintptr_t control_brain_ptr = 0;
    const bool control_brain_ptr_readable =
        memory.TryReadField(actor_address, kActorAnimationSelectionStateOffset, &control_brain_ptr);
    const auto control_brain_ptr_text =
        control_brain_ptr_readable ? HexString(control_brain_ptr) : unreadable();
    const auto control_brain_value =
        control_brain_ptr != 0 ? read_u32_hex(control_brain_ptr) : unreadable();
    uintptr_t actor_dc_ptr = 0;
    const bool actor_dc_ptr_readable =
        memory.TryReadField(actor_address, kActorCastDiagnosticContextOffset, &actor_dc_ptr);
    const auto actor_dc_ptr_text =
        actor_dc_ptr_readable ? HexString(actor_dc_ptr) : unreadable();
    const auto actor_dc_vtable =
        actor_dc_ptr != 0 ? read_ptr_hex(actor_dc_ptr + kObjectVtableOffset) : unreadable();
    uintptr_t actor_dc_vtable_address = 0;
    (void)(actor_dc_ptr != 0 &&
           memory.TryReadValue(actor_dc_ptr + kObjectVtableOffset, &actor_dc_vtable_address));
    const auto actor_dc_slot_10 =
        actor_dc_ptr != 0
            ? read_ptr_hex(actor_dc_ptr + kCastDiagnosticCallbackSlotOffset)
            : unreadable();
    const auto actor_dc_callback_10 =
        actor_dc_vtable_address != 0
            ? read_ptr_hex(actor_dc_vtable_address + kCastDiagnosticVtableCallbackOffset)
            : unreadable();
    uintptr_t progression_handle = 0;
    const bool progression_handle_readable =
        memory.TryReadField(actor_address, kActorProgressionHandleOffset, &progression_handle);
    uintptr_t progression_runtime = 0;
    const bool progression_runtime_readable =
        memory.TryReadField(actor_address, kActorProgressionRuntimeStateOffset, &progression_runtime);
    const auto read_progression_u32 = [&](std::size_t offset) -> std::string {
        return progression_runtime_readable && progression_runtime != 0
            ? read_u32_hex(progression_runtime + offset)
            : unreadable();
    };
    const auto read_progression_float = [&](std::size_t offset) -> std::string {
        return progression_runtime_readable && progression_runtime != 0
            ? read_float_text(progression_runtime + offset)
            : unreadable();
    };
    std::string selection_summary = "sel_ptr=" + selection_ptr_text;
    if (selection_ptr != 0) {
        selection_summary +=
            " sel_id=" + read_i32_text(selection_ptr + kActorControlBrainStateIdOffset) +
            " sel_group=" + read_u8_hex(selection_ptr + kActorControlBrainTargetSlotOffset) +
            " sel_slot=" + read_u16_hex(selection_ptr + kActorControlBrainTargetHandleOffset) +
            " sel_t8=" + read_i32_text(selection_ptr + kActorControlBrainRetargetTicksOffset) +
            " sel_tC=" + read_i32_text(selection_ptr + kActorControlBrainTargetCooldownTicksOffset) +
            " sel_t10=" + read_i32_text(selection_ptr + kActorControlBrainActionCooldownTicksOffset) +
            " sel_t14=" + read_i32_text(selection_ptr + kActorControlBrainActionBurstTicksOffset) +
            " sel_a1c=" + read_float_text(selection_ptr + kActorControlBrainHeadingAccumulatorOffset) +
            " sel_a20=" + read_float_text(selection_ptr + kActorControlBrainPursuitRangeOffset) +
            " sel_f24=" + read_u8_hex(selection_ptr + kActorControlBrainFollowLeaderOffset) +
            " sel_v28=" + read_float_text(selection_ptr + kActorControlBrainDesiredFacingOffset) +
            " sel_v2c=" + read_float_text(selection_ptr + kActorControlBrainDesiredFacingSmoothedOffset) +
            " sel_v30=" + read_float_text(selection_ptr + kActorControlBrainMoveInputXOffset) +
            " sel_v34=" + read_float_text(selection_ptr + kActorControlBrainMoveInputYOffset);
    }

    return
        "skill=" + field_i32_text(kActorPrimarySkillIdOffset) +
        " prev=" + field_i32_text(kActorPreviousSkillIdOffset) +
        " c21c=" + control_brain_ptr_text +
        " c21c_val=" + control_brain_value +
        " dc=" + actor_dc_ptr_text +
        " dc_vt=" + actor_dc_vtable +
        " dc_slot10=" + actor_dc_slot_10 +
        " dc_vt_cb10=" + actor_dc_callback_10 +
        " g1abe=" + gameplay_global_flag_1abe +
        " g1abd=" + gameplay_global_flag_1abd +
        " g85=" + gameplay_global_flag_85 +
        " e4=" + field_u32_hex(kActorPrimaryActionLatchE4Offset) +
        " e8=" + field_u32_hex(kActorPrimaryActionLatchE8Offset) +
        " drive=" + field_u8_hex(kActorAnimationDriveStateByteOffset) +
        " target_handle=" + field_u32_hex(kActorSpellTargetGroupByteOffset) +
        " a168=" + field_ptr_hex(kActorCurrentTargetActorOffset) +
        " no_int=" + field_u8_hex(kActorNoInterruptFlagOffset) +
        " a258=" + field_u32_hex(kActorContinuousPrimaryModeOffset) +
        " a264=" + field_u32_hex(kActorContinuousPrimaryActiveOffset) +
        " g27c=" + field_u8_hex(kActorActiveCastGroupByteOffset) +
        " s27e=" + field_u16_hex(kActorActiveCastSlotShortOffset) +
        " prog=" + (progression_runtime_readable ? HexString(progression_runtime) : unreadable()) +
        " ph=" + (progression_handle_readable ? HexString(progression_handle) : unreadable()) +
        " p750=" + read_progression_u32(kProgressionCurrentSpellIdOffset) +
        " p8a8=" + read_progression_float(kProgressionCastChargeAOffset) +
        " p8ac=" + read_progression_float(kProgressionEarthChargeCapOffset) +
        " p8b0=" + read_progression_float(kProgressionCastChargeBOffset) +
        " p8b4=" + read_progression_float(kProgressionCastChargeCOffset) +
        " f1b4=" + field_float_text(kActorPurePrimaryTimingAOffset) +
        " f1b8=" + field_float_text(kActorPurePrimaryTimingBOffset) +
        " f278=" + field_u32_text(kActorStartupCounterOffset) +
        " f28c=" + field_float_text(kActorSpellConfig28cOffset) +
        " f290=" + field_float_text(kActorSpellConfig290Offset) +
        " f294=" + field_float_text(kActorSpellConfig294Offset) +
        " f298=" + field_u32_text(kActorSpellConfig298Offset) +
        " f29c=" + field_float_text(kActorSpellConfig29cOffset) +
        " f2a0=" + field_float_text(kActorSpellConfig2a0Offset) +
        " f2a4=" + field_float_text(kActorSpellConfig2a4Offset) +
        " aimx=" + field_float_text(kActorAimTargetXOffset) +
        " aimy=" + field_float_text(kActorAimTargetYOffset) +
        " aux0=" + field_u32_hex(kActorAimTargetAux0Offset) +
        " aux1=" + field_u32_hex(kActorAimTargetAux1Offset) +
        " spread=" + field_u8_hex(kActorCastSpreadModeByteOffset) +
        " f2c8=" + field_u32_text(kActorSpellConfig2c8Offset) +
        " f2cc=" + field_float_text(kActorSpellConfig2ccOffset) +
        " f2d0=" + field_float_text(kActorSpellConfig2d0Offset) +
        " f2d4=" + field_float_text(kActorSpellConfig2d4Offset) +
        " f2d8=" + field_float_text(kActorSpellConfig2d8Offset) +
        " heading=" + field_float_text(kActorHeadingOffset) +
        " " + selection_summary;
}

bool SelectionStateRequiresHeldCastInputDuringNativeTick(int selection_state) {
    // These stock primaries keep doing native work only while the gameplay cast
    // input is held. This is separate from live target tracking: projectile
    // families still keep their startup target captured, while channel families
    // keep refreshing their victim/aim lane.
    switch (selection_state) {
    case 0x08: // ether pure primary projectile stream
    case 0x10: // fire pure primary projectile stream
    case 0x18: // air primary handler
    case 0x20: // water primary handler
        return true;
    default:
        return false;
    }
}

bool SelectionStateTracksLiveTargetDuringNativeTick(int selection_state) {
    switch (selection_state) {
    case 0x18: // air primary handler
    case 0x20: // water primary handler
        return true;
    default:
        return false;
    }
}

bool SelectionStateRequiresBoundedHeldCastInputDuringNativeTick(int selection_state) {
    // Earth is a projectile/effect primary, but the stock dispatcher needs the
    // cast input held until the native boulder object reaches its configured
    // max size. The release path watches the live object instead of assuming a
    // fixed gesture duration.
    switch (selection_state) {
    case 0x28: // earth primary handler
        return true;
    default:
        return false;
    }
}

bool OngoingCastRequiresHeldCastInputDuringNativeTick(
    const ParticipantEntityBinding::OngoingCastState& ongoing) {
    return SelectionStateRequiresHeldCastInputDuringNativeTick(ongoing.selection_state_target);
}

bool OngoingCastTracksLiveTargetDuringNativeTick(
    const ParticipantEntityBinding::OngoingCastState& ongoing) {
    return SelectionStateTracksLiveTargetDuringNativeTick(ongoing.selection_state_target);
}

bool OngoingCastRequiresBoundedHeldCastInputDuringNativeTick(
    const ParticipantEntityBinding::OngoingCastState& ongoing) {
    return SelectionStateRequiresBoundedHeldCastInputDuringNativeTick(ongoing.selection_state_target);
}

bool OngoingCastShouldDriveSyntheticCastInput(
    const ParticipantEntityBinding::OngoingCastState& ongoing) {
    if (ongoing.startup_in_progress) {
        return true;
    }
    if (OngoingCastRequiresHeldCastInputDuringNativeTick(ongoing)) {
        return true;
    }
    if (OngoingCastRequiresBoundedHeldCastInputDuringNativeTick(ongoing)) {
        return !ongoing.bounded_release_requested;
    }
    return false;
}

std::int32_t ResolveOngoingNativeTickSkillId(
    const ParticipantEntityBinding::OngoingCastState& ongoing) {
    return ongoing.uses_dispatcher_skill_id && ongoing.dispatcher_skill_id > 0
        ? ongoing.dispatcher_skill_id
        : ongoing.skill_id;
}

bool OngoingCastShouldUseLiveFacingTarget(
    const ParticipantEntityBinding::OngoingCastState& ongoing) {
    if (OngoingCastTracksLiveTargetDuringNativeTick(ongoing)) {
        return true;
    }
    return OngoingCastRequiresBoundedHeldCastInputDuringNativeTick(ongoing) &&
           !ongoing.bounded_release_requested;
}

bool OngoingCastShouldRefreshNativeTargetState(
    const ParticipantEntityBinding::OngoingCastState& ongoing) {
    if (OngoingCastRequiresBoundedHeldCastInputDuringNativeTick(ongoing) &&
        ongoing.bounded_release_requested) {
        return false;
    }
    return ongoing.startup_in_progress ||
           OngoingCastTracksLiveTargetDuringNativeTick(ongoing) ||
           OngoingCastRequiresBoundedHeldCastInputDuringNativeTick(ongoing);
}

uintptr_t ResolveOngoingCastNativeTargetActor(
    const ParticipantEntityBinding* binding,
    const ParticipantEntityBinding::OngoingCastState& ongoing) {
    if (ongoing.remote_input_controlled) {
        return ongoing.target_actor_address;
    }
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

int ResolveMaxStartupTicksWaiting(
    const ParticipantEntityBinding::OngoingCastState& ongoing) {
    if (ongoing.selection_state_target == kPrimaryComboDispatcherSelectionState) {
        // Combo-dispatch primaries can advance the actor startup counter and
        // legitimately defer projectile allocation past the generic 12-tick
        // window. Cutting that off early produces the "animation only, nothing
        // emitted" symptom observed in live runs.
        return 90;
    }
    return ParticipantEntityBinding::OngoingCastState::kMaxStartupTicksWaiting;
}

void PrimeGameplaySlotPostGateDispatchState(
    uintptr_t actor_address,
    const ParticipantEntityBinding::OngoingCastState& ongoing) {
    if (actor_address == 0 || ongoing.dispatcher_skill_id <= 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    (void)memory.TryWriteField<std::int32_t>(
        actor_address,
        kActorPrimarySkillIdOffset,
        ongoing.dispatcher_skill_id);
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
    if (!OngoingCastNeedsNativeTargetHandle(ongoing)) {
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
        kActorControlBrainTargetSlotOffset,
        state.selection_target_group_before);
    (void)memory.TryWriteField<std::uint16_t>(
        state.selection_state_pointer,
        kActorControlBrainTargetHandleOffset,
        state.selection_target_slot_before);
    (void)memory.TryWriteField<std::int32_t>(
        state.selection_state_pointer,
        kActorControlBrainRetargetTicksOffset,
        state.selection_retarget_ticks_before);
    (void)memory.TryWriteField<std::int32_t>(
        state.selection_state_pointer,
        kActorControlBrainTargetCooldownTicksOffset,
        state.selection_target_cooldown_before);
    (void)memory.TryWriteField<std::int32_t>(
        state.selection_state_pointer,
        kActorControlBrainActionCooldownTicksOffset,
        state.selection_target_extra_before);
    (void)memory.TryWriteField<std::int32_t>(
        state.selection_state_pointer,
        kActorControlBrainActionBurstTicksOffset,
        state.selection_target_flags_before);
}

void ClearSelectionBrainTarget(uintptr_t selection_state_pointer) {
    if (selection_state_pointer == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    (void)memory.TryWriteField<std::uint8_t>(
        selection_state_pointer,
        kActorControlBrainTargetSlotOffset,
        0xFF);
    (void)memory.TryWriteField<std::uint16_t>(
        selection_state_pointer,
        kActorControlBrainTargetHandleOffset,
        0xFFFF);
    (void)memory.TryWriteField<std::int32_t>(
        selection_state_pointer,
        kActorControlBrainRetargetTicksOffset,
        kSuppressedSelectionRetargetTicks);
    (void)memory.TryWriteField<std::int32_t>(
        selection_state_pointer,
        kActorControlBrainTargetCooldownTicksOffset,
        0);
    (void)memory.TryWriteField<std::int32_t>(
        selection_state_pointer,
        kActorControlBrainActionCooldownTicksOffset,
        0);
    (void)memory.TryWriteField<std::int32_t>(
        selection_state_pointer,
        kActorControlBrainActionBurstTicksOffset,
        0);
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
        kActorControlBrainTargetSlotOffset,
        state.selection_target_group_seed);
    (void)memory.TryWriteField<std::uint16_t>(
        state.selection_state_pointer,
        kActorControlBrainTargetHandleOffset,
        state.selection_target_slot_seed);
    (void)memory.TryWriteField<std::int32_t>(
        state.selection_state_pointer,
        kActorControlBrainRetargetTicksOffset,
        hold_ticks);
    (void)memory.TryWriteField<std::int32_t>(
        state.selection_state_pointer,
        kActorControlBrainTargetCooldownTicksOffset,
        0);
    (void)memory.TryWriteField<std::int32_t>(
        state.selection_state_pointer,
        kActorControlBrainActionCooldownTicksOffset,
        0);
    (void)memory.TryWriteField<std::int32_t>(
        state.selection_state_pointer,
        kActorControlBrainActionBurstTicksOffset,
        0);
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
    std::uint8_t target_group = kTargetHandleGroupSentinel;
    std::uint16_t target_slot = kTargetHandleSlotSentinel;
    const bool have_explicit_target_handle =
        TryResolveSameWorldTargetHandle(
            actor_address,
            target_actor_address,
            &target_group,
            &target_slot);

    if (!memory.TryReadValue(
            selection_pointer + kActorControlBrainTargetSlotOffset,
            &ongoing->selection_target_group_before) ||
        !memory.TryReadValue(
            selection_pointer + kActorControlBrainTargetHandleOffset,
            &ongoing->selection_target_slot_before) ||
        !memory.TryReadValue(
            selection_pointer + kActorControlBrainRetargetTicksOffset,
            &ongoing->selection_retarget_ticks_before) ||
        !memory.TryReadValue(
            selection_pointer + kActorControlBrainTargetCooldownTicksOffset,
            &ongoing->selection_target_cooldown_before) ||
        !memory.TryReadValue(
            selection_pointer + kActorControlBrainActionCooldownTicksOffset,
            &ongoing->selection_target_extra_before) ||
        !memory.TryReadValue(
            selection_pointer + kActorControlBrainActionBurstTicksOffset,
            &ongoing->selection_target_flags_before)) {
        ongoing->selection_brain_override_active = false;
        ongoing->selection_target_seed_active = false;
        return;
    }
    ongoing->selection_brain_override_active = true;

    // PlayerActorTick clears actor_primary_skill_id every tick and only
    // rebuilds it when FUN_0052C910 produces a non-zero control vector. That
    // helper drives from the actor-owned animation-selection/control-brain
    // pointer. The stock function decrements retarget_ticks first and only
    // keeps the cached target handle on the cooldown path; when retarget_ticks
    // hits zero it re-runs candidate search and overwrites target_slot/handle.
    // For pure-primary bot startup, the Lua brain has already picked the real
    // hostile. Seed that exact stock target handle and keep retarget_ticks
    // positive so stock stays on the "use cached target" path instead of
    // discarding it before the cast gate evaluates cVar5.
    if (have_explicit_target_handle) {
        ongoing->selection_target_seed_active = true;
        ongoing->selection_target_group_seed = target_group;
        ongoing->selection_target_slot_seed = target_slot;
        ongoing->selection_target_hold_ticks = 60;
        if (!memory.TryWriteField<std::uint8_t>(
            selection_pointer,
            kActorControlBrainTargetSlotOffset,
            target_group) ||
            !memory.TryWriteField<std::uint16_t>(
            selection_pointer,
            kActorControlBrainTargetHandleOffset,
            target_slot) ||
            !memory.TryWriteField<std::int32_t>(
            selection_pointer,
            kActorControlBrainRetargetTicksOffset,
            ongoing->selection_target_hold_ticks)) {
            RestoreSelectionBrainAfterCast(*ongoing);
            ongoing->selection_brain_override_active = false;
            ongoing->selection_target_seed_active = false;
            return;
        }
    } else {
        ongoing->selection_target_seed_active = false;
        ongoing->selection_target_group_seed = kTargetHandleGroupSentinel;
        ongoing->selection_target_slot_seed = kTargetHandleSlotSentinel;
        ongoing->selection_target_hold_ticks = 0;
        if (!memory.TryWriteField<std::uint8_t>(
            selection_pointer,
            kActorControlBrainTargetSlotOffset,
            kTargetHandleGroupSentinel) ||
            !memory.TryWriteField<std::uint16_t>(
            selection_pointer,
            kActorControlBrainTargetHandleOffset,
            kTargetHandleSlotSentinel) ||
            !memory.TryWriteField<std::int32_t>(
            selection_pointer,
            kActorControlBrainRetargetTicksOffset,
            0)) {
            RestoreSelectionBrainAfterCast(*ongoing);
            ongoing->selection_brain_override_active = false;
            return;
        }
    }
    if (!memory.TryWriteField<std::int32_t>(
        selection_pointer,
        kActorControlBrainTargetCooldownTicksOffset,
        0) ||
        !memory.TryWriteField<std::int32_t>(
        selection_pointer,
        kActorControlBrainActionCooldownTicksOffset,
        0) ||
        !memory.TryWriteField<std::int32_t>(
        selection_pointer,
        kActorControlBrainActionBurstTicksOffset,
        0)) {
        RestoreSelectionBrainAfterCast(*ongoing);
        ongoing->selection_brain_override_active = false;
        ongoing->selection_target_seed_active = false;
    }
}
