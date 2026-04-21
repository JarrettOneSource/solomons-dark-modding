float ReadResolvedGameFloatOr(uintptr_t absolute_address, float fallback) {
    auto& memory = ProcessMemory::Instance();
    const auto resolved_address = memory.ResolveGameAddressOrZero(absolute_address);
    if (resolved_address == 0) {
        return fallback;
    }

    return memory.ReadValueOr<float>(resolved_address, fallback);
}

float ReadResolvedGameDoubleAsFloatOr(uintptr_t absolute_address, float fallback) {
    auto& memory = ProcessMemory::Instance();
    const auto resolved_address = memory.ResolveGameAddressOrZero(absolute_address);
    if (resolved_address == 0) {
        return fallback;
    }

    return static_cast<float>(memory.ReadValueOr<double>(resolved_address, static_cast<double>(fallback)));
}

void AdvanceStandaloneWizardWalkCycleState(
    ParticipantEntityBinding* binding,
    float displacement_distance) {
    if (binding == nullptr || !std::isfinite(displacement_distance) || displacement_distance <= 0.0001f) {
        return;
    }

    const auto primary_divisor =
        (std::max)(0.0001f, ReadResolvedGameDoubleAsFloatOr(kActorWalkCyclePrimaryDivisorGlobal, 1.0f));
    const auto secondary_divisor =
        (std::max)(0.0001f, ReadResolvedGameDoubleAsFloatOr(kActorWalkCycleSecondaryDivisorGlobal, 1.0f));
    const auto primary_wrap_threshold =
        (std::max)(0.0001f, ReadResolvedGameFloatOr(kActorWalkCyclePrimaryWrapThresholdGlobal, 1.0f));
    const auto secondary_wrap_threshold =
        (std::max)(0.0001f, ReadResolvedGameFloatOr(kActorWalkCycleSecondaryWrapThresholdGlobal, 1.0f));
    const auto secondary_wrap_step =
        (std::max)(0.0001f, ReadResolvedGameDoubleAsFloatOr(kActorWalkCycleSecondaryWrapStepGlobal, secondary_wrap_threshold));
    const auto stride_step = ReadResolvedGameDoubleAsFloatOr(kActorWalkCycleStrideStepGlobal, 1.0f);

    auto primary = binding->dynamic_walk_cycle_primary;
    auto secondary = binding->dynamic_walk_cycle_secondary;

    primary += displacement_distance / primary_divisor;
    if (std::isfinite(primary) && primary_wrap_threshold > 0.0001f) {
        primary = std::fmod(primary, primary_wrap_threshold);
        if (primary < 0.0f) {
            primary += primary_wrap_threshold;
        }
    }

    secondary += displacement_distance / secondary_divisor;
    if (std::isfinite(secondary) && secondary_wrap_threshold > 0.0001f) {
        while (secondary >= secondary_wrap_threshold) {
            secondary -= secondary_wrap_step;
        }
        while (secondary < 0.0f) {
            secondary += secondary_wrap_step;
        }
    }

    binding->dynamic_walk_cycle_primary = primary;
    binding->dynamic_walk_cycle_secondary = secondary;
    binding->dynamic_render_drive_stride = stride_step;
    binding->dynamic_render_advance_rate = displacement_distance;
    binding->dynamic_render_drive_move_blend = 1.0f;
    binding->dynamic_render_advance_phase = primary;
}

void StopWizardBotActorMotion(uintptr_t actor_address) {
    if (actor_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    // Standalone clone-rail bots seed the stock walk accumulators at +0x158/+0x15C
    // so our loader-owned MoveStep can mirror player movement. Once loader
    // movement stops, those accumulators must be cleared immediately; otherwise
    // the stock PlayerActorTick keeps consuming the stale vector and slides the
    // clone even while our controller is idle.
    (void)memory.TryWriteField(actor_address, kActorAnimationConfigBlockOffset, 0.0f);
    (void)memory.TryWriteField(actor_address, kActorAnimationDriveParameterOffset, 0.0f);

    std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
    if (auto* binding = FindParticipantEntityForActor(actor_address);
        binding != nullptr && binding->kind == ParticipantEntityBinding::Kind::StandaloneWizard) {
        ApplyObservedBotAnimationState(binding, actor_address, false);
        binding->dynamic_walk_cycle_primary = 0.0f;
        binding->dynamic_walk_cycle_secondary = 0.0f;
        binding->dynamic_render_drive_stride = 0.0f;
        binding->dynamic_render_advance_rate = 0.0f;
        binding->dynamic_render_advance_phase = 0.0f;
        binding->dynamic_render_drive_move_blend = 0.0f;
        ApplyStandaloneWizardDynamicAnimationState(binding, actor_address);
        return;
    }

    ApplyActorAnimationDriveState(actor_address, false);
}

void ApplyObservedBotAnimationState(ParticipantEntityBinding* binding, uintptr_t actor_address, bool moving) {
    if (binding == nullptr || actor_address == 0 || binding->kind != ParticipantEntityBinding::Kind::StandaloneWizard) {
        return;
    }

    ApplyStandaloneWizardAnimationDriveProfile(binding, actor_address, moving);
    ApplyStandaloneWizardPuppetDriveState(binding, actor_address, moving);
    ApplyStandaloneWizardDynamicAnimationState(binding, actor_address);

    const auto desired_state_id = ResolveProfileSelectionState(binding->character_profile);
    if (TryWriteActorAnimationStateIdDirect(actor_address, desired_state_id)) {
        binding->last_applied_animation_state_id = desired_state_id;
        return;
    }

    binding->last_applied_animation_state_id = ResolveActorAnimationStateId(actor_address);
}

void LogWizardBotMovementFrame(
    ParticipantEntityBinding* binding,
    uintptr_t actor_address,
    uintptr_t owner_address,
    uintptr_t movement_controller_address,
    float direction_x,
    float direction_y,
    float velocity_x,
    float velocity_y,
    float position_before_x,
    float position_before_y,
    float position_after_x,
    float position_after_y,
    const char* path_label) {
    (void)owner_address;
    (void)movement_controller_address;
    (void)velocity_x;
    (void)velocity_y;
    if (binding == nullptr || actor_address == 0) {
        return;
    }
    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    (void)now_ms;
    auto& memory = ProcessMemory::Instance();
    const auto delta_x = position_after_x - position_before_x;
    const auto delta_y = position_after_y - position_before_y;
    const auto d = std::sqrt(delta_x * delta_x + delta_y * delta_y);
    const auto scale_0x74 = memory.ReadFieldOr<float>(actor_address, kActorMoveSpeedScaleOffset, 0.0f);
    const auto move_step_scale_0x218 =
        memory.ReadFieldOr<float>(actor_address, kActorMoveStepScaleOffset, 0.0f);
    const auto dir_x_0x158 =
        memory.ReadFieldOr<float>(actor_address, kActorAnimationConfigBlockOffset, 0.0f);
    const auto dir_y_0x15C =
        memory.ReadFieldOr<float>(actor_address, kActorAnimationDriveParameterOffset, 0.0f);
    Log(
        "[bots] standalone_mv bot=" + std::to_string(binding->bot_id) +
        " before=(" + std::to_string(position_before_x) + "," + std::to_string(position_before_y) + ")" +
        " after=(" + std::to_string(position_after_x) + "," + std::to_string(position_after_y) + ")" +
        " d=" + std::to_string(d) +
        " dir=(" + std::to_string(direction_x) + "," + std::to_string(direction_y) + ")" +
        " 0x74=" + std::to_string(scale_0x74) +
        " 0x218=" + std::to_string(move_step_scale_0x218) +
        " 0x158=" + std::to_string(dir_x_0x158) +
        " 0x15C=" + std::to_string(dir_y_0x15C) +
        " path=" + std::string(path_label != nullptr ? path_label : ""));
}

int ResolveCombatSelectionStateForSkillId(std::int32_t skill_id) {
    switch (skill_id) {
    case 0x18:
    case 0x20:
    case 0x28:
        return skill_id;
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

std::string DescribeGameplaySlotCastStartupWindow(uintptr_t actor_address) {
    if (actor_address == 0) {
        return "actor=0x0";
    }

    auto& memory = ProcessMemory::Instance();
    const auto selection_ptr =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorAnimationSelectionStateOffset, 0);
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
        " g27c=" + HexString(memory.ReadFieldOr<std::uint8_t>(actor_address, kActorActiveCastGroupByteOffset, 0xFF)) +
        " s27e=" + HexString(memory.ReadFieldOr<std::uint16_t>(actor_address, kActorActiveCastSlotShortOffset, 0xFFFF)) +
        " f1b8=" + std::to_string(memory.ReadFieldOr<float>(actor_address, 0x1B8, 0.0f)) +
        " f278=" + std::to_string(memory.ReadFieldOr<std::uint32_t>(actor_address, 0x278, 0)) +
        " f29c=" + std::to_string(memory.ReadFieldOr<float>(actor_address, 0x29C, 0.0f)) +
        " f2a0=" + std::to_string(memory.ReadFieldOr<float>(actor_address, 0x2A0, 0.0f)) +
        " aimx=" + std::to_string(memory.ReadFieldOr<float>(actor_address, kActorAimTargetXOffset, 0.0f)) +
        " aimy=" + std::to_string(memory.ReadFieldOr<float>(actor_address, kActorAimTargetYOffset, 0.0f)) +
        " aux0=" + HexString(memory.ReadFieldOr<std::uint32_t>(actor_address, kActorAimTargetAux0Offset, 0)) +
        " aux1=" + HexString(memory.ReadFieldOr<std::uint32_t>(actor_address, kActorAimTargetAux1Offset, 0)) +
        " spread=" + HexString(memory.ReadFieldOr<std::uint8_t>(actor_address, kActorCastSpreadModeByteOffset, 0)) +
        " f2d0=" + std::to_string(memory.ReadFieldOr<float>(actor_address, 0x2D0, 0.0f)) +
        " f2d4=" + std::to_string(memory.ReadFieldOr<float>(actor_address, 0x2D4, 0.0f)) +
        " f2d8=" + std::to_string(memory.ReadFieldOr<float>(actor_address, 0x2D8, 0.0f)) +
        " heading=" + std::to_string(memory.ReadFieldOr<float>(actor_address, kActorHeadingOffset, 0.0f)) +
        " " + selection_summary;
}

bool SkillRequiresLocalSlotDuringNativeTick(std::int32_t skill_id) {
    // FUN_0052BB60 (0x3EF / Iceblast) has a slot-0-only emission branch in
    // the stock handler body, not just at init/cleanup.
    return skill_id == 0x3EF;
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
    constexpr std::size_t kActorCooldownByteOffset = 0x164;
    constexpr std::size_t kActorCooldownWordOffset = 0x166;
    constexpr std::uint8_t kCooldownByteSentinel = 0xFF;
    constexpr std::uint16_t kCooldownWordSentinel = 0xFFFF;

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
    (void)memory.TryWriteField<std::uint8_t>(
        actor_address,
        kActorCooldownByteOffset,
        kCooldownByteSentinel);
    (void)memory.TryWriteField<std::uint16_t>(
        actor_address,
        kActorCooldownWordOffset,
        kCooldownWordSentinel);
}

void PrimeSelectionBrainForCastStartup(
    uintptr_t actor_address,
    uintptr_t selection_pointer,
    uintptr_t target_actor_address) {
    if (selection_pointer == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    constexpr std::uint8_t kTargetHandleGroupSentinel = 0xFF;
    constexpr std::uint16_t kTargetHandleSlotSentinel = 0xFFFF;

    const auto actor_owner =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, 0);
    const auto target_owner =
        memory.ReadFieldOr<uintptr_t>(target_actor_address, kActorOwnerOffset, 0);
    const auto target_group =
        memory.ReadFieldOr<std::uint8_t>(target_actor_address, kActorSlotOffset, kTargetHandleGroupSentinel);
    const auto target_slot =
        memory.ReadFieldOr<std::uint16_t>(target_actor_address, kActorWorldSlotOffset, kTargetHandleSlotSentinel);
    const bool have_explicit_target_handle =
        target_actor_address != 0 &&
        actor_owner != 0 &&
        actor_owner == target_owner &&
        target_group != kTargetHandleGroupSentinel &&
        target_slot != kTargetHandleSlotSentinel;

    // PlayerActorTick clears actor+0x270 every tick and only rebuilds it when
    // FUN_0052C910 produces a non-zero control vector. That helper drives from
    // the actor-owned +0x21C control brain; if the cached retarget timer/handle
    // stay stale through cast startup, cVar5 never rises and stock never
    // re-enters FUN_00548A00. When the Lua brain already picked a concrete
    // hostile, seed that exact stock target handle into +0x04/+0x06 and keep a
    // short positive retarget timer so the next native tick consumes the handle
    // immediately instead of racing a nearest-hostile refresh. If no explicit
    // target is available, fall back to invalidating the cached handle and
    // forcing a fresh acquisition.
    if (have_explicit_target_handle) {
        (void)memory.TryWriteField<std::uint8_t>(selection_pointer, 0x04, target_group);
        (void)memory.TryWriteField<std::uint16_t>(selection_pointer, 0x06, target_slot);
        (void)memory.TryWriteField<std::int32_t>(selection_pointer, 0x08, 2);
    } else {
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

bool PreparePendingGameplaySlotBotCast(ParticipantEntityBinding* binding, std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (binding == nullptr || binding->actor_address == 0 || binding->bot_id == 0 ||
        !IsGameplaySlotWizardKind(binding->kind)) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto actor_address = binding->actor_address;
    constexpr float kRadiansToDegrees = 57.2957795130823208767981548141051703f;
    constexpr std::uint8_t kActorActiveCastGroupSentinel = 0xFF;
    constexpr std::uint16_t kActorActiveCastSlotSentinel = 0xFFFF;
    const auto kActorPreviousSkillIdOffset =
        kActorPrimarySkillIdOffset + sizeof(std::int32_t);
    constexpr std::size_t kProgressionCurrentSpellIdOffset = 0x750;
    const auto finish_attack_idle = [&]() {
        const auto heading =
            memory.ReadFieldOr<float>(actor_address, kActorHeadingOffset, 0.0f);
        (void)multiplayer::FinishBotAttack(binding->bot_id, true, heading);
    };

    auto ApplyPreparedState = [&](ParticipantEntityBinding::OngoingCastState* ongoing) {
        if (ongoing == nullptr) {
            return;
        }

        if (ongoing->gameplay_selection_state_override_active &&
            binding->gameplay_slot >= 0) {
            const auto combat_selection_state = ResolveCombatSelectionStateForSkillId(ongoing->skill_id);
            if (combat_selection_state >= 0) {
                std::string selection_error;
                (void)TryWriteActorAnimationStateIdDirect(actor_address, combat_selection_state);
                (void)TryWriteGameplaySelectionStateForSlot(
                    binding->gameplay_slot,
                    combat_selection_state,
                    &selection_error);
            }
        }
        if (ongoing->progression_spell_id_override_active && ongoing->progression_runtime_address != 0) {
            (void)memory.TryWriteField<std::int32_t>(
                ongoing->progression_runtime_address,
                kProgressionCurrentSpellIdOffset,
                ongoing->skill_id);
        }
        if (ongoing->have_aim_heading) {
            (void)memory.TryWriteField(actor_address, kActorHeadingOffset, ongoing->aim_heading);
        }
        if (ongoing->have_aim_target) {
            (void)memory.TryWriteField(actor_address, kActorAimTargetXOffset, ongoing->aim_target_x);
            (void)memory.TryWriteField(actor_address, kActorAimTargetYOffset, ongoing->aim_target_y);
            (void)memory.TryWriteField<std::uint32_t>(actor_address, kActorAimTargetAux0Offset, 0);
            (void)memory.TryWriteField<std::uint32_t>(actor_address, kActorAimTargetAux1Offset, 0);
        }
        (void)memory.TryWriteField<std::uint8_t>(actor_address, kActorCastSpreadModeByteOffset, 0);
        (void)memory.TryWriteField<std::int32_t>(actor_address, kActorPrimarySkillIdOffset, ongoing->skill_id);
        (void)memory.TryWriteField<std::int32_t>(actor_address, kActorPreviousSkillIdOffset, 0);
    };

    multiplayer::BotCastRequest request{};
    if (!multiplayer::ConsumePendingBotCast(binding->bot_id, &request)) {
        return false;
    }
    int requested_skill_id = request.skill_id;
    if (requested_skill_id <= 0 && request.kind == multiplayer::BotCastKind::Primary) {
        int primary_entry_index = -1;
        int combo_entry_index = -1;
        if (!TryResolveProfilePrimarySelectionPair(
                binding->character_profile,
                &primary_entry_index,
                &combo_entry_index,
                &requested_skill_id)) {
            finish_attack_idle();
            if (error_message != nullptr) {
                *error_message =
                    "primary cast has no stock loadout pair. primary=" +
                    std::to_string(primary_entry_index) +
                    " combo=" + std::to_string(combo_entry_index);
            }
            return false;
        }
    }
    if (requested_skill_id <= 0) {
        finish_attack_idle();
        if (error_message != nullptr) {
            *error_message = "cast has no resolvable skill_id";
        }
        return false;
    }

    const auto combat_selection_state = ResolveCombatSelectionStateForSkillId(requested_skill_id);
    if (combat_selection_state < 0) {
        finish_attack_idle();
        if (error_message != nullptr) {
            *error_message = "unsupported gameplay-slot stock cast skill_id=" + std::to_string(requested_skill_id);
        }
        return false;
    }

    float aim_heading = 0.0f;
    bool have_aim_heading = false;
    float aim_target_x = 0.0f;
    float aim_target_y = 0.0f;
    bool have_aim_target = false;
    if (request.has_aim_target) {
        const auto actor_x =
            memory.ReadFieldOr<float>(actor_address, kActorPositionXOffset, 0.0f);
        const auto actor_y =
            memory.ReadFieldOr<float>(actor_address, kActorPositionYOffset, 0.0f);
        const auto dx = request.aim_target_x - actor_x;
        const auto dy = request.aim_target_y - actor_y;
        if ((dx * dx) + (dy * dy) > 0.0001f) {
            aim_heading = std::atan2(dy, dx) * kRadiansToDegrees + 90.0f;
            if (aim_heading < 0.0f) {
                aim_heading += 360.0f;
            } else if (aim_heading >= 360.0f) {
                aim_heading -= 360.0f;
            }
            have_aim_heading = true;
        }
        aim_target_x = request.aim_target_x;
        aim_target_y = request.aim_target_y;
        have_aim_target = true;
    } else if (request.has_aim_angle && std::isfinite(request.aim_angle)) {
        aim_heading = request.aim_angle;
        have_aim_heading = true;
    }

    auto& ongoing = binding->ongoing_cast;
    ongoing = ParticipantEntityBinding::OngoingCastState{};
    ongoing.active = true;
    ongoing.skill_id = requested_skill_id;
    ongoing.have_aim_heading = have_aim_heading;
    ongoing.aim_heading = aim_heading;
    ongoing.have_aim_target = have_aim_target;
    ongoing.aim_target_x = aim_target_x;
    ongoing.aim_target_y = aim_target_y;
    ongoing.heading_before = memory.ReadFieldOr<float>(actor_address, kActorHeadingOffset, 0.0f);
    ongoing.aim_x_before = memory.ReadFieldOr<float>(actor_address, kActorAimTargetXOffset, 0.0f);
    ongoing.aim_y_before = memory.ReadFieldOr<float>(actor_address, kActorAimTargetYOffset, 0.0f);
    ongoing.aim_aux0_before =
        memory.ReadFieldOr<std::uint32_t>(actor_address, kActorAimTargetAux0Offset, 0);
    ongoing.aim_aux1_before =
        memory.ReadFieldOr<std::uint32_t>(actor_address, kActorAimTargetAux1Offset, 0);
    ongoing.spread_before =
        memory.ReadFieldOr<std::uint8_t>(actor_address, kActorCastSpreadModeByteOffset, 0);

    ongoing.selection_state_pointer =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorAnimationSelectionStateOffset, 0);
    PrimeSelectionBrainForCastStartup(
        actor_address,
        ongoing.selection_state_pointer,
        request.target_actor_address);
    ongoing.selection_state_before = ResolveActorAnimationStateId(actor_address);
    if (binding->gameplay_slot >= 0 && ongoing.selection_state_before != kUnknownAnimationStateId) {
        ongoing.gameplay_selection_state_before = ongoing.selection_state_before;
        std::string selection_error;
        (void)TryWriteActorAnimationStateIdDirect(actor_address, combat_selection_state);
        ongoing.gameplay_selection_state_override_active =
            TryWriteGameplaySelectionStateForSlot(
                binding->gameplay_slot,
                combat_selection_state,
                &selection_error);
    }

    if (TryResolveActorProgressionRuntime(actor_address, &ongoing.progression_runtime_address) &&
        ongoing.progression_runtime_address != 0) {
        ongoing.progression_spell_id_before =
            memory.ReadFieldOr<std::int32_t>(
                ongoing.progression_runtime_address,
                kProgressionCurrentSpellIdOffset,
                0);
        if (request.kind == multiplayer::BotCastKind::Primary && request.skill_id <= 0) {
            int resolved_primary_skill_id = -1;
            std::string loadout_error;
            if (!ApplyProfilePrimaryLoadoutToSkillsWizard(
                    ongoing.progression_runtime_address,
                    binding->character_profile,
                    &resolved_primary_skill_id,
                    &loadout_error)) {
                finish_attack_idle();
                if (error_message != nullptr) {
                    *error_message = std::move(loadout_error);
                }
                return false;
            }
            ongoing.skill_id = resolved_primary_skill_id;
            if (ongoing.progression_spell_id_before <= 0) {
                ongoing.progression_spell_id_before = ongoing.skill_id;
            }
            ongoing.progression_spell_id_override_active =
                memory.TryWriteField<std::int32_t>(
                    ongoing.progression_runtime_address,
                    kProgressionCurrentSpellIdOffset,
                    ongoing.skill_id);
        } else {
            ongoing.progression_spell_id_override_active =
                memory.TryWriteField<std::int32_t>(
                    ongoing.progression_runtime_address,
                    kProgressionCurrentSpellIdOffset,
                    requested_skill_id);
        }
    }
    ongoing.requires_local_slot_native_tick =
        SkillRequiresLocalSlotDuringNativeTick(ongoing.skill_id);
    ongoing.startup_in_progress = true;
    ongoing.startup_ticks_waiting = 0;

    const auto cleanup_address = memory.ResolveGameAddressOrZero(kCastActiveHandleCleanup);
    const auto active_cast_group_before =
        memory.ReadFieldOr<std::uint8_t>(actor_address, kActorActiveCastGroupByteOffset, 0);
    if (cleanup_address != 0 && active_cast_group_before != kActorActiveCastGroupSentinel) {
        LocalPlayerCastShimState shim_state;
        const auto shim_active = EnterLocalPlayerCastShim(binding, &shim_state);
        DWORD cleanup_exception_code = 0;
        const auto cleanup_ok = shim_active &&
            CallCastActiveHandleCleanupSafe(cleanup_address, actor_address, &cleanup_exception_code);
        LeaveLocalPlayerCastShim(shim_state);
        if (!cleanup_ok) {
            (void)memory.TryWriteField<std::uint8_t>(
                actor_address, kActorActiveCastGroupByteOffset, kActorActiveCastGroupSentinel);
            (void)memory.TryWriteField<std::uint16_t>(
                actor_address, kActorActiveCastSlotShortOffset, kActorActiveCastSlotSentinel);
        }
    }

    ApplyPreparedState(&ongoing);
    Log(
        "[bots] gameplay-slot cast prepped. bot_id=" + std::to_string(binding->bot_id) +
        " skill_id=" + std::to_string(ongoing.skill_id) +
        " selection_state=" + std::to_string(combat_selection_state) +
        " progression_runtime=" + HexString(ongoing.progression_runtime_address) +
        " progression_spell_id=" + std::to_string(
            ongoing.progression_runtime_address != 0
                ? memory.ReadFieldOr<std::int32_t>(
                      ongoing.progression_runtime_address,
                      kProgressionCurrentSpellIdOffset,
                      0)
                : 0) +
        " selection_ptr=" + HexString(ongoing.selection_state_pointer) +
        " startup={" + DescribeGameplaySlotCastStartupWindow(actor_address) + "}");
    return true;
}

// Cast architecture (standalone verified 2026-04-20; gameplay-slot fix 2026-04-21):
//
//   * Player flow: input sets actor+0x270 (primary skill id); PlayerActorTick
//     (0x00548B00) calls FUN_00548A00 every gameplay tick; FUN_00548A00 routes
//     by actor+0x270 to the per-spell handler (e.g. FUN_00545360 for 0x3EE).
//     The handler owns a cached spell-object handle stored at actor+0x27C
//     (group byte) + actor+0x27E (world slot short). It latches cast-active
//     state via actor+0x160 (animation_drive_state) and actor+0x1EC
//     (mNoInterrupt). When the handler decides the cast is done it clears
//     both latch fields. PlayerActorTick's skill-transition block
//     (0x5496e5..0x5497ac) then calls FUN_0052F3B0 on skill change to release
//     the spell-object handle (sets +0x27C=0xFF, +0x27E=0xFFFF).
//
//   * Per-spell handler init gate: `(actor+0x5C == 0) && (actor+0x27C == 0xFF)`.
//     FUN_0052F3B0 cleanup shares the slot==0 early-out. Standalone clone-rail
//     bots inherit slot 0 from the source player actor so the gate passes
//     naturally; gameplay-slot bots carry their true slot (1/2/3) in
//     actor+0x5C, so without a temp-flip the dispatcher runs but the handler
//     bails before allocating the spell object and no visual effect renders.
//     InvokeWithLocalPlayerSlot below wraps each native dispatcher/cleanup
//     call with a transient actor+0x5C = 0 write and an immediate restore.
//
//   * Bot flow (this function): PlayerActorTick still runs for the bot actor
//     via `original(self)` in the tick hook, so FUN_00548A00 keeps driving
//     the per-spell handler natively. Our job is (a) initiate the cast by
//     setting aim + actor+0x270 + a primer dispatch; (b) each subsequent tick
//     watch for (actor+0x160 == 0 && actor+0x1EC == 0) — the handler's own
//     latch-release — and then call FUN_0052F3B0 ourselves to release the
//     cached spell-object handle (native code only triggers cleanup from the
//     skill-transition path, which bots never hit because they don't change
//     actor+0x270 via input). kMaxTicksWaiting is a safety cap against
//     unexpected latch states, not a timing assumption.
bool ProcessPendingBotCast(ParticipantEntityBinding* binding, std::string* error_message) {
    if (binding == nullptr || binding->actor_address == 0 || binding->bot_id == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto actor_address = binding->actor_address;
    const auto dispatcher_address = memory.ResolveGameAddressOrZero(kSpellCastDispatcher);
    const auto cleanup_address = memory.ResolveGameAddressOrZero(kCastActiveHandleCleanup);
    if (dispatcher_address == 0 || cleanup_address == 0) {
        if (error_message != nullptr && binding->ongoing_cast.active) {
            *error_message = "cast seam addresses unresolved";
        }
        return false;
    }

    constexpr float kRadiansToDegrees = 57.2957795130823208767981548141051703f;
    constexpr std::uint8_t kActorActiveCastGroupSentinel = 0xFF;
    constexpr std::uint16_t kActorActiveCastSlotSentinel = 0xFFFF;
    constexpr std::size_t kProgressionCurrentSpellIdOffset = 0x750;

    // Per-spell handler init gate (docs/spell-cast-cleanup-chain.md) is
    // `(actor+0x5C == 0) && (actor+0x27C == 0xFF)`. FUN_0052F3B0 cleanup has the
    // same slot==0 early-out. Standalone clone-rail bots inherit slot 0 from the
    // source player actor, so on April-20 verification the gate passed and
    // effects spawned. Gameplay-slot bots (task #18) carry their real slot
    // (1/2/3) in actor+0x5C — the gate fails, dispatcher returns without
    // allocating a spell object, and no projectile/cone ever renders even though
    // animation flags and aim fields were written. Temp-flip actor+0x5C to 0
    // around the native dispatcher/cleanup calls so the handler treats the bot
    // as the local player for the gate check; restore immediately after so the
    // rest of the tick (hostile AI, HUD, rendering) still sees the bot's true
    // gameplay slot.
    auto InvokeWithLocalPlayerSlot = [&](auto&& invoke) {
        LocalPlayerCastShimState shim_state;
        const auto shim_active = EnterLocalPlayerCastShim(binding, &shim_state);
        invoke();
        LeaveLocalPlayerCastShim(shim_state);
        Log(
            std::string("[bots] slot_flip diag. actor=") + HexString(actor_address) +
            " slot_offset=" + HexString(static_cast<std::uint32_t>(kActorSlotOffset)) +
            " saved=" + HexString(shim_state.saved_actor_slot) +
            " during=" + HexString(
                memory.ReadFieldOr<std::uint8_t>(
                    actor_address,
                    kActorSlotOffset,
                    static_cast<std::uint8_t>(0xFE))) +
            " flip_needed=" + (shim_active ? "1" : "0") +
            " flip_wr=" + (shim_active ? "1" : "0") +
            " restore_wr=" + (shim_active ? "1" : "0") +
            " shim_slot=" + std::to_string(binding->gameplay_slot));
    };

    auto RestoreAim = [&](const ParticipantEntityBinding::OngoingCastState& state) {
        if (state.have_aim_heading) {
            (void)memory.TryWriteField(actor_address, kActorHeadingOffset, state.heading_before);
        }
        if (state.have_aim_target) {
            (void)memory.TryWriteField(actor_address, kActorAimTargetXOffset, state.aim_x_before);
            (void)memory.TryWriteField(actor_address, kActorAimTargetYOffset, state.aim_y_before);
            (void)memory.TryWriteField<std::uint32_t>(
                actor_address, kActorAimTargetAux0Offset, state.aim_aux0_before);
            (void)memory.TryWriteField<std::uint32_t>(
                actor_address, kActorAimTargetAux1Offset, state.aim_aux1_before);
        }
        (void)memory.TryWriteField<std::uint8_t>(
            actor_address, kActorCastSpreadModeByteOffset, state.spread_before);
    };

    auto ReleaseSpellHandle = [&](const ParticipantEntityBinding::OngoingCastState& state,
                                  const char* exit_label) {
        const auto group_before =
            memory.ReadFieldOr<std::uint8_t>(actor_address, kActorActiveCastGroupByteOffset, 0);
        DWORD cleanup_exception_code = 0;
        bool cleanup_ok = true;
        if (group_before != kActorActiveCastGroupSentinel) {
            InvokeWithLocalPlayerSlot([&] {
                cleanup_ok = CallCastActiveHandleCleanupSafe(
                    cleanup_address, actor_address, &cleanup_exception_code);
            });
            if (!cleanup_ok) {
                // Native cleanup raised SEH. Fall back to writing the sentinels
                // directly so the next cast's init gate passes; vtable-side
                // effects (slot 0x6C/0x70) get skipped but the handle is
                // released and future casts are safe.
                (void)memory.TryWriteField<std::uint8_t>(
                    actor_address, kActorActiveCastGroupByteOffset, kActorActiveCastGroupSentinel);
                (void)memory.TryWriteField<std::uint16_t>(
                    actor_address, kActorActiveCastSlotShortOffset, kActorActiveCastSlotSentinel);
            }
        }
        (void)memory.TryWriteField<std::int32_t>(actor_address, kActorPrimarySkillIdOffset, 0);
        RestoreAim(state);
        if (state.gameplay_selection_state_override_active &&
            binding->gameplay_slot >= 0 &&
            state.gameplay_selection_state_before != kUnknownAnimationStateId) {
            std::string selection_error;
            (void)TryWriteActorAnimationStateIdDirect(actor_address, state.gameplay_selection_state_before);
            (void)TryWriteGameplaySelectionStateForSlot(
                binding->gameplay_slot,
                state.gameplay_selection_state_before,
                &selection_error);
        }
        if (state.progression_spell_id_override_active && state.progression_runtime_address != 0) {
            (void)memory.TryWriteField<std::int32_t>(
                state.progression_runtime_address,
                0x750,
                state.progression_spell_id_before);
        }

        const auto group_after =
            memory.ReadFieldOr<std::uint8_t>(actor_address, kActorActiveCastGroupByteOffset, 0);
        const auto settled_heading =
            memory.ReadFieldOr<float>(actor_address, kActorHeadingOffset, 0.0f);
        (void)multiplayer::FinishBotAttack(binding->bot_id, true, settled_heading);
        Log(
            std::string("[bots] cast complete (") + exit_label + "). bot_id=" +
            std::to_string(binding->bot_id) +
            " skill_id=" + std::to_string(state.skill_id) +
            " ticks=" + std::to_string(state.ticks_waiting) +
            " saw_latch=" + (state.saw_latch ? std::string("1") : std::string("0")) +
            " group_before=" + HexString(group_before) +
            " group_after=" + HexString(group_after) +
            (cleanup_ok ? std::string("") :
                          std::string(" cleanup_seh=") + HexString(cleanup_exception_code)));
    };

    auto ApplyPreparedGameplaySlotState =
        [&](const ParticipantEntityBinding::OngoingCastState& state) {
            if (state.gameplay_selection_state_override_active &&
                binding->gameplay_slot >= 0) {
                const auto combat_selection_state =
                    ResolveCombatSelectionStateForSkillId(state.skill_id);
                if (combat_selection_state >= 0) {
                    std::string selection_error;
                    (void)TryWriteActorAnimationStateIdDirect(actor_address, combat_selection_state);
                    (void)TryWriteGameplaySelectionStateForSlot(
                        binding->gameplay_slot,
                        combat_selection_state,
                        &selection_error);
                }
            }
            if (state.progression_spell_id_override_active &&
                state.progression_runtime_address != 0) {
                (void)memory.TryWriteField<std::int32_t>(
                    state.progression_runtime_address,
                    kProgressionCurrentSpellIdOffset,
                    state.skill_id);
            }
            if (state.have_aim_heading) {
                (void)memory.TryWriteField(actor_address, kActorHeadingOffset, state.aim_heading);
            }
            if (state.have_aim_target) {
                (void)memory.TryWriteField(actor_address, kActorAimTargetXOffset, state.aim_target_x);
                (void)memory.TryWriteField(actor_address, kActorAimTargetYOffset, state.aim_target_y);
                (void)memory.TryWriteField<std::uint32_t>(actor_address, kActorAimTargetAux0Offset, 0);
                (void)memory.TryWriteField<std::uint32_t>(actor_address, kActorAimTargetAux1Offset, 0);
            }
            (void)memory.TryWriteField<std::uint8_t>(actor_address, kActorCastSpreadModeByteOffset, 0);
            (void)memory.TryWriteField<std::int32_t>(
                actor_address,
                kActorPrimarySkillIdOffset,
                state.skill_id);
        };

    auto LogSpellObjectDiag = [&](std::uint8_t active_group_post) {
        const auto group_post_diag = active_group_post;
        const auto slot_post_diag =
            memory.ReadFieldOr<std::uint16_t>(actor_address, kActorActiveCastSlotShortOffset, 0xFFFF);
        const auto world_ptr_diag =
            memory.ReadFieldOr<std::uintptr_t>(actor_address, kActorOwnerOffset, 0);
        std::uintptr_t spell_obj_ptr = 0;
        std::uint32_t obj_type = 0;
        std::uint32_t obj_f74_raw = 0;
        std::uint32_t obj_f1fc_raw = 0;
        std::uint32_t obj_f22c = 0;
        std::uint32_t obj_f230 = 0;
        if (group_post_diag != kActorActiveCastGroupSentinel &&
            slot_post_diag != kActorActiveCastSlotSentinel && world_ptr_diag != 0) {
            const std::uintptr_t entry_address =
                world_ptr_diag + kActorWorldBucketTableOffset +
                static_cast<std::uintptr_t>(
                    static_cast<std::uint32_t>(group_post_diag) * kActorWorldBucketStride +
                    static_cast<std::uint32_t>(slot_post_diag)) *
                    sizeof(std::uintptr_t);
            spell_obj_ptr = memory.ReadValueOr<std::uintptr_t>(entry_address, 0);
            if (spell_obj_ptr != 0 && memory.IsReadableRange(spell_obj_ptr, 0x240)) {
                obj_type = memory.ReadFieldOr<std::uint32_t>(spell_obj_ptr, 0x08, 0);
                obj_f74_raw = memory.ReadFieldOr<std::uint32_t>(spell_obj_ptr, 0x74, 0);
                obj_f1fc_raw = memory.ReadFieldOr<std::uint32_t>(spell_obj_ptr, 0x1FC, 0);
                obj_f22c = memory.ReadFieldOr<std::uint32_t>(spell_obj_ptr, 0x22C, 0);
                obj_f230 = memory.ReadFieldOr<std::uint32_t>(spell_obj_ptr, 0x230, 0);
            }
        }
        Log(
            std::string("[bots] spell_obj diag. bot_id=") + std::to_string(binding->bot_id) +
            " group=" + HexString(group_post_diag) +
            " slot=" + HexString(slot_post_diag) +
            " world=" + HexString(world_ptr_diag) +
            " obj_ptr=" + HexString(spell_obj_ptr) +
            " obj_type=" + HexString(obj_type) +
            " obj_74_raw=" + HexString(obj_f74_raw) +
            " obj_1fc_raw=" + HexString(obj_f1fc_raw) +
            " obj_22c=" + std::to_string(obj_f22c) +
            " obj_230=" + std::to_string(obj_f230) +
            " startup={" + DescribeGameplaySlotCastStartupWindow(actor_address) + "}");
    };

    // --- Watch continuation path ---------------------------------------------
    // Gameplay-slot bots keep stock movement/render ownership, but their cast
    // startup cannot rely on the local-player input gate inside
    // PlayerActorTick: stock clears actor+0x270 every frame before it ever
    // reaches FUN_00548A00. Re-pin the prepared fields here and, if stock never
    // preserved the skill id, perform a single post-stock startup dispatch
    // under the same slot-0 shim the native handler expects.
    if (binding->ongoing_cast.active) {
        auto& ongoing = binding->ongoing_cast;

        // Re-pin aim while the cast animation plays so the handler's per-tick
        // reads (projectile spawn angle, facing) see consistent state.
        if (ongoing.have_aim_heading) {
            (void)memory.TryWriteField(actor_address, kActorHeadingOffset, ongoing.aim_heading);
        }
        if (ongoing.have_aim_target) {
            (void)memory.TryWriteField(actor_address, kActorAimTargetXOffset, ongoing.aim_target_x);
            (void)memory.TryWriteField(actor_address, kActorAimTargetYOffset, ongoing.aim_target_y);
            (void)memory.TryWriteField<std::uint32_t>(actor_address, kActorAimTargetAux0Offset, 0);
            (void)memory.TryWriteField<std::uint32_t>(actor_address, kActorAimTargetAux1Offset, 0);
        }
        (void)memory.TryWriteField<std::uint8_t>(actor_address, kActorCastSpreadModeByteOffset, 0);
        (void)memory.TryWriteField<std::int32_t>(
            actor_address, kActorPrimarySkillIdOffset, ongoing.skill_id);

        if (IsGameplaySlotWizardKind(binding->kind) &&
            ongoing.startup_in_progress &&
            !ongoing.post_stock_dispatch_attempted) {
            PrimeGameplaySlotPostGateDispatchState(actor_address, ongoing.skill_id);
            DWORD startup_exception_code = 0;
            bool startup_dispatched = false;
            InvokeWithLocalPlayerSlot([&] {
                startup_dispatched = CallSpellCastDispatcherSafe(
                    dispatcher_address,
                    actor_address,
                    &startup_exception_code);
            });
            ongoing.post_stock_dispatch_attempted = true;
            const auto drive_after_dispatch =
                memory.ReadFieldOr<std::uint8_t>(actor_address, kActorAnimationDriveStateByteOffset, 0);
            const auto no_interrupt_after_dispatch =
                memory.ReadFieldOr<std::uint8_t>(actor_address, kActorNoInterruptFlagOffset, 0);
            const auto active_group_after_dispatch =
                memory.ReadFieldOr<std::uint8_t>(actor_address, kActorActiveCastGroupByteOffset, 0xFF);
            Log(
                "[bots] gameplay-slot post-stock dispatch. bot_id=" +
                std::to_string(binding->bot_id) +
                " skill_id=" + std::to_string(ongoing.skill_id) +
                " ok=" + (startup_dispatched ? std::string("1") : std::string("0")) +
                " seh=" + HexString(startup_exception_code) +
                " group_post=" + HexString(active_group_after_dispatch) +
                " drive_post=" + HexString(drive_after_dispatch) +
                " no_int_post=" + HexString(no_interrupt_after_dispatch));
            if (!startup_dispatched) {
                ReleaseSpellHandle(ongoing, "dispatch_seh");
                ongoing = ParticipantEntityBinding::OngoingCastState{};
                return true;
            }
        }

        const auto drive_state =
            memory.ReadFieldOr<std::uint8_t>(actor_address, kActorAnimationDriveStateByteOffset, 0);
        const auto no_interrupt =
            memory.ReadFieldOr<std::uint8_t>(actor_address, kActorNoInterruptFlagOffset, 0);
        const auto active_cast_group =
            memory.ReadFieldOr<std::uint8_t>(actor_address, kActorActiveCastGroupByteOffset, 0);
        const bool has_live_handle = active_cast_group != kActorActiveCastGroupSentinel;

        ongoing.ticks_waiting += 1;
        if (ongoing.startup_in_progress) {
            ongoing.startup_ticks_waiting += 1;
        }
        if (drive_state != 0 || no_interrupt != 0) {
            ongoing.saw_latch = true;
        }
        if (has_live_handle || drive_state != 0 || no_interrupt != 0) {
            ongoing.saw_activity = true;
            ongoing.startup_in_progress = false;
        }

        const bool startup_timeout_hit =
            ongoing.startup_in_progress &&
            ongoing.startup_ticks_waiting >=
                ResolveMaxStartupTicksWaiting(ongoing.skill_id);
        const bool activity_released =
            ongoing.saw_activity && !has_live_handle && drive_state == 0 && no_interrupt == 0;
        const bool safety_cap_hit =
            ongoing.ticks_waiting >= ParticipantEntityBinding::OngoingCastState::kMaxTicksWaiting;

        if (startup_timeout_hit || activity_released || safety_cap_hit) {
            const char* exit_label = startup_timeout_hit
                ? "startup_timeout"
                : (activity_released ? "activity_released" : "safety_cap");
            if (startup_timeout_hit) {
                LogSpellObjectDiag(active_cast_group);
            }
            ReleaseSpellHandle(ongoing, exit_label);
            ongoing = ParticipantEntityBinding::OngoingCastState{};
        }
        return true;
    }

    if (IsGameplaySlotWizardKind(binding->kind)) {
        return false;
    }

    // --- New-request consumption path ----------------------------------------
    multiplayer::BotCastRequest request{};
    if (!multiplayer::ConsumePendingBotCast(binding->bot_id, &request)) {
        return false;
    }

    if (request.skill_id <= 0) {
        (void)multiplayer::FinishBotAttack(
            binding->bot_id,
            true,
            memory.ReadFieldOr<float>(actor_address, kActorHeadingOffset, 0.0f));
        if (error_message != nullptr) {
            *error_message = "cast has no skill_id";
        }
        return false;
    }

    float aim_heading = 0.0f;
    bool have_aim_heading = false;
    float aim_target_x = 0.0f;
    float aim_target_y = 0.0f;
    bool have_aim_target = false;
    if (request.has_aim_target) {
        const auto actor_x =
            memory.ReadFieldOr<float>(actor_address, kActorPositionXOffset, 0.0f);
        const auto actor_y =
            memory.ReadFieldOr<float>(actor_address, kActorPositionYOffset, 0.0f);
        const auto dx = request.aim_target_x - actor_x;
        const auto dy = request.aim_target_y - actor_y;
        if ((dx * dx) + (dy * dy) > 0.0001f) {
            aim_heading = std::atan2(dy, dx) * kRadiansToDegrees + 90.0f;
            if (aim_heading < 0.0f) {
                aim_heading += 360.0f;
            } else if (aim_heading >= 360.0f) {
                aim_heading -= 360.0f;
            }
            have_aim_heading = true;
        }
        aim_target_x = request.aim_target_x;
        aim_target_y = request.aim_target_y;
        have_aim_target = true;
    } else if (request.has_aim_angle && std::isfinite(request.aim_angle)) {
        aim_heading = request.aim_angle;
        have_aim_heading = true;
    }

    const auto heading_before =
        memory.ReadFieldOr<float>(actor_address, kActorHeadingOffset, 0.0f);
    const auto aim_x_before =
        memory.ReadFieldOr<float>(actor_address, kActorAimTargetXOffset, 0.0f);
    const auto aim_y_before =
        memory.ReadFieldOr<float>(actor_address, kActorAimTargetYOffset, 0.0f);
    const auto aim_aux0_before =
        memory.ReadFieldOr<std::uint32_t>(actor_address, kActorAimTargetAux0Offset, 0);
    const auto aim_aux1_before =
        memory.ReadFieldOr<std::uint32_t>(actor_address, kActorAimTargetAux1Offset, 0);
    const auto spread_before =
        memory.ReadFieldOr<std::uint8_t>(actor_address, kActorCastSpreadModeByteOffset, 0);

    if (have_aim_heading) {
        (void)memory.TryWriteField(actor_address, kActorHeadingOffset, aim_heading);
    }
    if (have_aim_target) {
        (void)memory.TryWriteField(actor_address, kActorAimTargetXOffset, aim_target_x);
        (void)memory.TryWriteField(actor_address, kActorAimTargetYOffset, aim_target_y);
        (void)memory.TryWriteField<std::uint32_t>(actor_address, kActorAimTargetAux0Offset, 0);
        (void)memory.TryWriteField<std::uint32_t>(actor_address, kActorAimTargetAux1Offset, 0);
    }
    // Force non-spread path in FUN_0052BB60 so projectile copies actor aim
    // fields (0x2a8/0x2ac) into projectile target (0x168/0x16c) instead of
    // using a random spawn angle.
    (void)memory.TryWriteField<std::uint8_t>(actor_address, kActorCastSpreadModeByteOffset, 0);

    (void)memory.TryWriteField<std::int32_t>(
        actor_address, kActorPrimarySkillIdOffset, request.skill_id);

    const auto active_cast_group_before =
        memory.ReadFieldOr<std::uint8_t>(actor_address, kActorActiveCastGroupByteOffset, 0);
    const auto active_cast_slot_before =
        memory.ReadFieldOr<std::uint16_t>(actor_address, kActorActiveCastSlotShortOffset, 0);
    // If a prior cast left the handle cached (e.g. SEH abort), release it
    // properly before starting init so we don't leak a world-storage slot.
    if (active_cast_group_before != kActorActiveCastGroupSentinel) {
        DWORD prior_cleanup_seh = 0;
        bool prior_cleanup_ok = false;
        InvokeWithLocalPlayerSlot([&] {
            prior_cleanup_ok = CallCastActiveHandleCleanupSafe(
                cleanup_address, actor_address, &prior_cleanup_seh);
        });
        if (!prior_cleanup_ok) {
            (void)memory.TryWriteField<std::uint8_t>(
                actor_address, kActorActiveCastGroupByteOffset, kActorActiveCastGroupSentinel);
            (void)memory.TryWriteField<std::uint16_t>(
                actor_address, kActorActiveCastSlotShortOffset, kActorActiveCastSlotSentinel);
        }
    }

    DWORD exception_code = 0;
    bool dispatched = false;
    InvokeWithLocalPlayerSlot([&] {
        dispatched = CallSpellCastDispatcherSafe(
            dispatcher_address, actor_address, &exception_code);
    });

    const auto active_group_post =
        memory.ReadFieldOr<std::uint8_t>(actor_address, kActorActiveCastGroupByteOffset, 0);

    // Diagnostic: immediately after dispatcher returns and before any cleanup,
    // snapshot the spell_obj registered at (world+0x500, group*0x800+slot)*4 so
    // we can see what the handler actually produced. Fragment-spawn gate at
    // FUN_00545360:215 requires spell_obj[0x22C] > 1. FUN_0052B150 can collapse
    // it to 1 in init, which silently kills the spawn loop.
    {
        const auto group_post_diag = active_group_post;
        const auto slot_post_diag =
            memory.ReadFieldOr<std::uint16_t>(actor_address, kActorActiveCastSlotShortOffset, 0xFFFF);
        const auto world_ptr_diag =
            memory.ReadFieldOr<std::uintptr_t>(actor_address, kActorOwnerOffset, 0);
        std::uintptr_t spell_obj_ptr = 0;
        std::uint32_t obj_type = 0;
        std::uint32_t obj_f74_raw = 0;
        std::uint32_t obj_f1fc_raw = 0;
        std::uint32_t obj_f22c = 0;
        std::uint32_t obj_f230 = 0;
        if (group_post_diag != kActorActiveCastGroupSentinel &&
            slot_post_diag != kActorActiveCastSlotSentinel && world_ptr_diag != 0) {
            const std::uintptr_t entry_address =
                world_ptr_diag + kActorWorldBucketTableOffset +
                static_cast<std::uintptr_t>(
                    static_cast<std::uint32_t>(group_post_diag) * kActorWorldBucketStride +
                    static_cast<std::uint32_t>(slot_post_diag)) *
                    sizeof(std::uintptr_t);
            spell_obj_ptr = memory.ReadValueOr<std::uintptr_t>(entry_address, 0);
            if (spell_obj_ptr != 0 && memory.IsReadableRange(spell_obj_ptr, 0x240)) {
                obj_type = memory.ReadFieldOr<std::uint32_t>(spell_obj_ptr, 0x08, 0);
                obj_f74_raw = memory.ReadFieldOr<std::uint32_t>(spell_obj_ptr, 0x74, 0);
                obj_f1fc_raw = memory.ReadFieldOr<std::uint32_t>(spell_obj_ptr, 0x1FC, 0);
                obj_f22c = memory.ReadFieldOr<std::uint32_t>(spell_obj_ptr, 0x22C, 0);
                obj_f230 = memory.ReadFieldOr<std::uint32_t>(spell_obj_ptr, 0x230, 0);
            }
        }
        Log(
            std::string("[bots] spell_obj diag. bot_id=") + std::to_string(binding->bot_id) +
            " group=" + HexString(group_post_diag) +
            " slot=" + HexString(slot_post_diag) +
            " world=" + HexString(world_ptr_diag) +
            " obj_ptr=" + HexString(spell_obj_ptr) +
            " obj_type=" + HexString(obj_type) +
            " obj_74_raw=" + HexString(obj_f74_raw) +
            " obj_1fc_raw=" + HexString(obj_f1fc_raw) +
            " obj_22c=" + std::to_string(obj_f22c) +
            " obj_230=" + std::to_string(obj_f230));
    }

    if (!dispatched) {
        ParticipantEntityBinding::OngoingCastState rollback{};
        rollback.have_aim_heading = have_aim_heading;
        rollback.have_aim_target = have_aim_target;
        rollback.heading_before = heading_before;
        rollback.aim_x_before = aim_x_before;
        rollback.aim_y_before = aim_y_before;
        rollback.aim_aux0_before = aim_aux0_before;
        rollback.aim_aux1_before = aim_aux1_before;
        rollback.spread_before = spread_before;
        (void)memory.TryWriteField<std::int32_t>(actor_address, kActorPrimarySkillIdOffset, 0);
        RestoreAim(rollback);
        (void)multiplayer::FinishBotAttack(
            binding->bot_id,
            true,
            memory.ReadFieldOr<float>(actor_address, kActorHeadingOffset, heading_before));

        if (error_message != nullptr) {
            *error_message =
                "spell_cast_dispatcher threw SEH " + HexString(exception_code);
        }
        Log(
            "[bots] cast dispatch failed. bot_id=" + std::to_string(binding->bot_id) +
            " skill_id=" + std::to_string(request.skill_id) +
            " seh=" + HexString(exception_code));
        return false;
    }

    if (have_aim_heading) {
        binding->facing_heading_value = aim_heading;
        binding->facing_heading_valid = true;
    }

    auto& ongoing = binding->ongoing_cast;
    ongoing.active = true;
    ongoing.skill_id = request.skill_id;
    ongoing.have_aim_heading = have_aim_heading;
    ongoing.aim_heading = aim_heading;
    ongoing.have_aim_target = have_aim_target;
    ongoing.aim_target_x = aim_target_x;
    ongoing.aim_target_y = aim_target_y;
    ongoing.heading_before = heading_before;
    ongoing.aim_x_before = aim_x_before;
    ongoing.aim_y_before = aim_y_before;
    ongoing.aim_aux0_before = aim_aux0_before;
    ongoing.aim_aux1_before = aim_aux1_before;
    ongoing.spread_before = spread_before;
    ongoing.ticks_waiting = 0;
    ongoing.saw_latch = false;
    ongoing.saw_activity = false;
    ongoing.requires_local_slot_native_tick =
        SkillRequiresLocalSlotDuringNativeTick(request.skill_id);

    // Instant-hit spells (e.g. many melees) may complete inside this primer
    // dispatch: the handler allocates, fires, and drops back to the sentinel
    // all in one call. Detect and release immediately so we don't spin in
    // the watch loop waiting for a latch that already came and went. 0x3EF is
    // intentionally excluded: the stock family can return from the primer with
    // no live handle or latch, then emit on a later native tick only while the
    // gameplay-slot bot is temporarily masquerading as slot 0.
    const auto drive_state_post =
        memory.ReadFieldOr<std::uint8_t>(actor_address, kActorAnimationDriveStateByteOffset, 0);
    const auto no_interrupt_post =
        memory.ReadFieldOr<std::uint8_t>(actor_address, kActorNoInterruptFlagOffset, 0);
    ongoing.saw_activity =
        active_group_post != kActorActiveCastGroupSentinel ||
        drive_state_post != 0 ||
        no_interrupt_post != 0;
    if (!ongoing.requires_local_slot_native_tick &&
        (active_group_post == kActorActiveCastGroupSentinel ||
         (drive_state_post == 0 && no_interrupt_post == 0))) {
        ongoing.saw_latch = (drive_state_post != 0 || no_interrupt_post != 0);
        ongoing.saw_activity = ongoing.saw_activity || ongoing.saw_latch;
        ReleaseSpellHandle(ongoing, "instant");
        ongoing = ParticipantEntityBinding::OngoingCastState{};
    }

    Log(
        "[bots] cast dispatched. bot_id=" + std::to_string(binding->bot_id) +
        " skill_id=" + std::to_string(request.skill_id) +
        " aim_heading=" + (have_aim_heading ? std::to_string(aim_heading) : std::string("<none>")) +
        " aim_target=" + (have_aim_target ? (std::to_string(aim_target_x) + "," + std::to_string(aim_target_y)) : std::string("<none>")) +
        " cast_handle_before=(" + HexString(active_cast_group_before) + "," +
        HexString(active_cast_slot_before) + ")" +
        " group_post=" + HexString(active_group_post) +
        " drive_post=" + HexString(drive_state_post) +
        " no_int_post=" + HexString(no_interrupt_post) +
        " native_slot0_tick=" +
        (binding->ongoing_cast.requires_local_slot_native_tick ? std::string("1") : std::string("0")) +
        " watch_armed=" + (binding->ongoing_cast.active ? std::string("1") : std::string("0")));
    return true;
}

void LogLocalPlayerAnimationProbe() {
    uintptr_t gameplay_address = 0;
    uintptr_t actor_address = 0;
    if (!TryResolveCurrentGameplayScene(&gameplay_address) || gameplay_address == 0 ||
        !TryResolvePlayerActorForSlot(gameplay_address, 0, &actor_address) ||
        actor_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    const auto current_x = memory.ReadFieldOr<float>(actor_address, kActorPositionXOffset, 0.0f);
    const auto current_y = memory.ReadFieldOr<float>(actor_address, kActorPositionYOffset, 0.0f);

    bool moving_now = false;
    if (g_local_player_animation_probe_has_last_position) {
        const auto delta_x = current_x - g_local_player_animation_probe_last_x;
        const auto delta_y = current_y - g_local_player_animation_probe_last_y;
        moving_now = std::sqrt((delta_x * delta_x) + (delta_y * delta_y)) > 0.01f;
    }

    g_local_player_animation_probe_last_x = current_x;
    g_local_player_animation_probe_last_y = current_y;
    g_local_player_animation_probe_has_last_position = true;
    CaptureObservedPlayerAnimationDriveProfile(actor_address, moving_now);
}
