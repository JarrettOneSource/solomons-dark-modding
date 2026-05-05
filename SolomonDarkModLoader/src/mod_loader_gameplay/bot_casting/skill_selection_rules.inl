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
    const auto gameplay_global_flag_1abe =
        memory.ReadValueOr<std::uint8_t>(
            memory.ResolveGameAddressOrZero(kGameObjectGlobal + kGameplayPrimaryGateBlockFlagOffset),
            0);
    const auto gameplay_global_flag_1abd =
        memory.ReadValueOr<std::uint8_t>(
            memory.ResolveGameAddressOrZero(kGameObjectGlobal + kGameplayCastUiBlockFlagOffset),
            0);
    const auto gameplay_global_flag_85 =
        memory.ReadValueOr<std::uint8_t>(
            memory.ResolveGameAddressOrZero(kGameObjectGlobal + kGameplayInputGateFlagOffset),
            0);
    const auto selection_ptr =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorAnimationSelectionStateOffset, 0);
    const auto control_brain_ptr =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorAnimationSelectionStateOffset, 0);
    const auto control_brain_value =
        control_brain_ptr != 0 && memory.IsReadableRange(control_brain_ptr, sizeof(uintptr_t))
            ? memory.ReadValueOr<std::uint32_t>(control_brain_ptr, 0xFFFFFFFFu)
            : 0xFFFFFFFFu;
    const auto actor_dc_ptr =
        memory.ReadFieldOr<uintptr_t>(
            actor_address,
            kActorCastDiagnosticContextOffset,
            0);
    const auto actor_dc_vtable =
        actor_dc_ptr != 0 && memory.IsReadableRange(actor_dc_ptr, sizeof(uintptr_t))
            ? memory.ReadValueOr<uintptr_t>(actor_dc_ptr + kObjectVtableOffset, 0)
            : 0;
    const auto actor_dc_slot_10 =
        actor_dc_ptr != 0 &&
                memory.IsReadableRange(
                    actor_dc_ptr + kCastDiagnosticCallbackSlotOffset,
                    sizeof(uintptr_t))
            ? memory.ReadValueOr<uintptr_t>(
                  actor_dc_ptr + kCastDiagnosticCallbackSlotOffset,
                  0)
            : 0;
    const auto actor_dc_callback_10 =
        actor_dc_vtable != 0 &&
                memory.IsReadableRange(
                    actor_dc_vtable + kCastDiagnosticVtableCallbackOffset,
                    sizeof(uintptr_t))
            ? memory.ReadValueOr<uintptr_t>(
                  actor_dc_vtable + kCastDiagnosticVtableCallbackOffset,
                  0)
            : 0;
    const auto progression_handle =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorProgressionHandleOffset, 0);
    auto progression_runtime =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorProgressionRuntimeStateOffset, 0);
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
            " sel_id=" + std::to_string(memory.ReadValueOr<int>(
                selection_ptr + kActorControlBrainStateIdOffset,
                -9999)) +
            " sel_group=" + HexString(memory.ReadValueOr<std::uint8_t>(
                selection_ptr + kActorControlBrainTargetSlotOffset,
                0xFF)) +
            " sel_slot=" + HexString(memory.ReadValueOr<std::uint16_t>(
                selection_ptr + kActorControlBrainTargetHandleOffset,
                0xFFFF)) +
            " sel_t8=" + std::to_string(memory.ReadValueOr<int>(
                selection_ptr + kActorControlBrainRetargetTicksOffset,
                0)) +
            " sel_tC=" + std::to_string(memory.ReadValueOr<int>(
                selection_ptr + kActorControlBrainTargetCooldownTicksOffset,
                0)) +
            " sel_t10=" + std::to_string(memory.ReadValueOr<int>(
                selection_ptr + kActorControlBrainActionCooldownTicksOffset,
                0)) +
            " sel_t14=" + std::to_string(memory.ReadValueOr<int>(
                selection_ptr + kActorControlBrainActionBurstTicksOffset,
                0)) +
            " sel_a1c=" + std::to_string(memory.ReadValueOr<float>(
                selection_ptr + kActorControlBrainHeadingAccumulatorOffset,
                0.0f)) +
            " sel_a20=" + std::to_string(memory.ReadValueOr<float>(
                selection_ptr + kActorControlBrainPursuitRangeOffset,
                0.0f)) +
            " sel_f24=" + HexString(memory.ReadValueOr<std::uint8_t>(
                selection_ptr + kActorControlBrainFollowLeaderOffset,
                0)) +
            " sel_v28=" + std::to_string(memory.ReadValueOr<float>(
                selection_ptr + kActorControlBrainDesiredFacingOffset,
                0.0f)) +
            " sel_v2c=" + std::to_string(memory.ReadValueOr<float>(
                selection_ptr + kActorControlBrainDesiredFacingSmoothedOffset,
                0.0f)) +
            " sel_v30=" + std::to_string(memory.ReadValueOr<float>(
                selection_ptr + kActorControlBrainMoveInputXOffset,
                0.0f)) +
            " sel_v34=" + std::to_string(memory.ReadValueOr<float>(
                selection_ptr + kActorControlBrainMoveInputYOffset,
                0.0f));
    }

    return
        "skill=" + std::to_string(memory.ReadFieldOr<std::int32_t>(actor_address, kActorPrimarySkillIdOffset, 0)) +
        " prev=" + std::to_string(memory.ReadFieldOr<std::int32_t>(actor_address, kActorPreviousSkillIdOffset, 0)) +
        " c21c=" + HexString(control_brain_ptr) +
        " c21c_val=" + HexString(control_brain_value) +
        " dc=" + HexString(actor_dc_ptr) +
        " dc_vt=" + HexString(actor_dc_vtable) +
        " dc_slot10=" + HexString(actor_dc_slot_10) +
        " dc_vt_cb10=" + HexString(actor_dc_callback_10) +
        " g1abe=" + HexString(gameplay_global_flag_1abe) +
        " g1abd=" + HexString(gameplay_global_flag_1abd) +
        " g85=" + HexString(gameplay_global_flag_85) +
        " e4=" + HexString(memory.ReadFieldOr<std::uint32_t>(actor_address, kActorPrimaryActionLatchE4Offset, 0)) +
        " e8=" + HexString(memory.ReadFieldOr<std::uint32_t>(actor_address, kActorPrimaryActionLatchE8Offset, 0)) +
        " drive=" + HexString(memory.ReadFieldOr<std::uint8_t>(
            actor_address,
            kActorAnimationDriveStateByteOffset,
            0)) +
        " target_handle=" + HexString(memory.ReadFieldOr<std::uint32_t>(
            actor_address,
            kActorSpellTargetGroupByteOffset,
            0)) +
        " a168=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorCurrentTargetActorOffset, 0)) +
        " no_int=" + HexString(memory.ReadFieldOr<std::uint8_t>(
            actor_address,
            kActorNoInterruptFlagOffset,
            0)) +
        " a258=" + HexString(memory.ReadFieldOr<std::uint32_t>(actor_address, kActorContinuousPrimaryModeOffset, 0)) +
        " a264=" + HexString(memory.ReadFieldOr<std::uint32_t>(actor_address, kActorContinuousPrimaryActiveOffset, 0)) +
        " g27c=" + HexString(memory.ReadFieldOr<std::uint8_t>(actor_address, kActorActiveCastGroupByteOffset, 0xFF)) +
        " s27e=" + HexString(memory.ReadFieldOr<std::uint16_t>(actor_address, kActorActiveCastSlotShortOffset, 0xFFFF)) +
        " prog=" + HexString(progression_runtime) +
        " ph=" + HexString(progression_handle) +
        " p750=" + HexString(read_progression_u32(kProgressionCurrentSpellIdOffset)) +
        " p8a8=" + std::to_string(read_progression_float(kProgressionCastChargeAOffset)) +
        " p8ac=" + std::to_string(read_progression_float(kProgressionEarthChargeCapOffset)) +
        " p8b0=" + std::to_string(read_progression_float(kProgressionCastChargeBOffset)) +
        " p8b4=" + std::to_string(read_progression_float(kProgressionCastChargeCOffset)) +
        " f1b4=" + std::to_string(memory.ReadFieldOr<float>(actor_address, kActorPurePrimaryTimingAOffset, 0.0f)) +
        " f1b8=" + std::to_string(memory.ReadFieldOr<float>(actor_address, kActorPurePrimaryTimingBOffset, 0.0f)) +
        " f278=" + std::to_string(memory.ReadFieldOr<std::uint32_t>(actor_address, kActorStartupCounterOffset, 0)) +
        " f28c=" + std::to_string(memory.ReadFieldOr<float>(actor_address, kActorSpellConfig28cOffset, 0.0f)) +
        " f290=" + std::to_string(memory.ReadFieldOr<float>(actor_address, kActorSpellConfig290Offset, 0.0f)) +
        " f294=" + std::to_string(memory.ReadFieldOr<float>(actor_address, kActorSpellConfig294Offset, 0.0f)) +
        " f298=" + std::to_string(memory.ReadFieldOr<std::uint32_t>(actor_address, kActorSpellConfig298Offset, 0)) +
        " f29c=" + std::to_string(memory.ReadFieldOr<float>(actor_address, kActorSpellConfig29cOffset, 0.0f)) +
        " f2a0=" + std::to_string(memory.ReadFieldOr<float>(actor_address, kActorSpellConfig2a0Offset, 0.0f)) +
        " f2a4=" + std::to_string(memory.ReadFieldOr<float>(actor_address, kActorSpellConfig2a4Offset, 0.0f)) +
        " aimx=" + std::to_string(memory.ReadFieldOr<float>(actor_address, kActorAimTargetXOffset, 0.0f)) +
        " aimy=" + std::to_string(memory.ReadFieldOr<float>(actor_address, kActorAimTargetYOffset, 0.0f)) +
        " aux0=" + HexString(memory.ReadFieldOr<std::uint32_t>(actor_address, kActorAimTargetAux0Offset, 0)) +
        " aux1=" + HexString(memory.ReadFieldOr<std::uint32_t>(actor_address, kActorAimTargetAux1Offset, 0)) +
        " spread=" + HexString(memory.ReadFieldOr<std::uint8_t>(actor_address, kActorCastSpreadModeByteOffset, 0)) +
        " f2c8=" + std::to_string(memory.ReadFieldOr<std::uint32_t>(actor_address, kActorSpellConfig2c8Offset, 0)) +
        " f2cc=" + std::to_string(memory.ReadFieldOr<float>(actor_address, kActorSpellConfig2ccOffset, 0.0f)) +
        " f2d0=" + std::to_string(memory.ReadFieldOr<float>(actor_address, kActorSpellConfig2d0Offset, 0.0f)) +
        " f2d4=" + std::to_string(memory.ReadFieldOr<float>(actor_address, kActorSpellConfig2d4Offset, 0.0f)) +
        " f2d8=" + std::to_string(memory.ReadFieldOr<float>(actor_address, kActorSpellConfig2d8Offset, 0.0f)) +
        " heading=" + std::to_string(memory.ReadFieldOr<float>(actor_address, kActorHeadingOffset, 0.0f)) +
        " " + selection_summary;
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
    const auto active_skill_id = ResolveOngoingNativeTickSkillId(ongoing);
    if (SkillTracksLiveTargetDuringNativeTick(active_skill_id)) {
        return true;
    }
    return SkillRequiresBoundedHeldCastInputDuringNativeTick(active_skill_id) &&
           !ongoing.bounded_release_requested;
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
        // Iceblast advances the actor startup counter and can legitimately
        // defer projectile allocation past the generic 12-tick
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
        memory.ReadValueOr<std::uint8_t>(
            selection_pointer + kActorControlBrainTargetSlotOffset,
            kTargetHandleGroupSentinel);
    ongoing->selection_target_slot_before =
        memory.ReadValueOr<std::uint16_t>(
            selection_pointer + kActorControlBrainTargetHandleOffset,
            kTargetHandleSlotSentinel);
    ongoing->selection_retarget_ticks_before =
        memory.ReadValueOr<std::int32_t>(
            selection_pointer + kActorControlBrainRetargetTicksOffset,
            0);
    ongoing->selection_target_cooldown_before =
        memory.ReadValueOr<std::int32_t>(
            selection_pointer + kActorControlBrainTargetCooldownTicksOffset,
            0);
    ongoing->selection_target_extra_before =
        memory.ReadValueOr<std::int32_t>(
            selection_pointer + kActorControlBrainActionCooldownTicksOffset,
            0);
    ongoing->selection_target_flags_before =
        memory.ReadValueOr<std::int32_t>(
            selection_pointer + kActorControlBrainActionBurstTicksOffset,
            0);
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
        (void)memory.TryWriteField<std::uint8_t>(
            selection_pointer,
            kActorControlBrainTargetSlotOffset,
            target_group);
        (void)memory.TryWriteField<std::uint16_t>(
            selection_pointer,
            kActorControlBrainTargetHandleOffset,
            target_slot);
        (void)memory.TryWriteField<std::int32_t>(
            selection_pointer,
            kActorControlBrainRetargetTicksOffset,
            ongoing->selection_target_hold_ticks);
    } else {
        ongoing->selection_target_seed_active = false;
        ongoing->selection_target_group_seed = kTargetHandleGroupSentinel;
        ongoing->selection_target_slot_seed = kTargetHandleSlotSentinel;
        ongoing->selection_target_hold_ticks = 0;
        (void)memory.TryWriteField<std::uint8_t>(
            selection_pointer,
            kActorControlBrainTargetSlotOffset,
            kTargetHandleGroupSentinel);
        (void)memory.TryWriteField<std::uint16_t>(
            selection_pointer,
            kActorControlBrainTargetHandleOffset,
            kTargetHandleSlotSentinel);
        (void)memory.TryWriteField<std::int32_t>(
            selection_pointer,
            kActorControlBrainRetargetTicksOffset,
            0);
    }
    (void)memory.TryWriteField<std::int32_t>(
        selection_pointer,
        kActorControlBrainTargetCooldownTicksOffset,
        0);
    (void)memory.TryWriteField<std::int32_t>(
        selection_pointer,
        kActorControlBrainActionCooldownTicksOffset,
        0);
    (void)memory.TryWriteField<std::int32_t>(
        selection_pointer,
        kActorControlBrainActionBurstTicksOffset,
        0);
}
