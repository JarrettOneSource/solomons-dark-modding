bool PreparePendingWizardBotCast(ParticipantEntityBinding* binding, std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (binding == nullptr || binding->actor_address == 0 || binding->bot_id == 0 ||
        (!IsGameplaySlotWizardKind(binding->kind) &&
         !IsStandaloneWizardKind(binding->kind))) {
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
        (void)multiplayer::FinishBotAttack(binding->bot_id, true, heading, true);
    };

    auto ApplyPreparedState = [&](ParticipantEntityBinding::OngoingCastState* ongoing) {
        if (ongoing == nullptr) {
            return;
        }

        if (ongoing->gameplay_selection_state_override_active &&
            binding->gameplay_slot >= 0) {
            const auto combat_selection_state = ResolveOngoingCastSelectionState(*ongoing);
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
            ApplyWizardActorFacingState(actor_address, ongoing->aim_heading);
        }
        if (ongoing->have_aim_target) {
            (void)memory.TryWriteField(actor_address, kActorAimTargetXOffset, ongoing->aim_target_x);
            (void)memory.TryWriteField(actor_address, kActorAimTargetYOffset, ongoing->aim_target_y);
            (void)memory.TryWriteField<std::uint32_t>(actor_address, kActorAimTargetAux0Offset, 0);
            (void)memory.TryWriteField<std::uint32_t>(actor_address, kActorAimTargetAux1Offset, 0);
        }
        (void)memory.TryWriteField<std::uint8_t>(actor_address, kActorCastSpreadModeByteOffset, 0);
        (void)memory.TryWriteField<std::int32_t>(
            actor_address,
            kActorPrimarySkillIdOffset,
            ongoing->uses_dispatcher_skill_id ? ongoing->dispatcher_skill_id : 0);
        (void)memory.TryWriteField<std::int32_t>(actor_address, kActorPreviousSkillIdOffset, 0);
    };

    auto RollbackPreparedStartup = [&](ParticipantEntityBinding::OngoingCastState* ongoing) {
        if (ongoing == nullptr) {
            return;
        }

        RestoreSelectionBrainAfterCast(*ongoing);
        ClearSelectionBrainTarget(ongoing->selection_state_pointer);
        RestoreOngoingCastNativeTargetActor(actor_address, *ongoing);
        binding->facing_target_actor_address = 0;
        if (ongoing->gameplay_selection_state_override_active &&
            binding->gameplay_slot >= 0 &&
            ongoing->gameplay_selection_state_before != kUnknownAnimationStateId) {
            std::string selection_error;
            if (ongoing->lane != ParticipantEntityBinding::OngoingCastState::Lane::PurePrimary) {
                (void)TryWriteActorAnimationStateIdDirect(
                    actor_address,
                    ongoing->gameplay_selection_state_before);
            }
            (void)TryWriteGameplaySelectionStateForSlot(
                binding->gameplay_slot,
                ongoing->gameplay_selection_state_before,
                &selection_error);
        }
        if (ongoing->progression_spell_id_override_active &&
            ongoing->progression_runtime_address != 0) {
            (void)memory.TryWriteField<std::int32_t>(
                ongoing->progression_runtime_address,
                kProgressionCurrentSpellIdOffset,
                ongoing->progression_spell_id_before);
        }
        *ongoing = ParticipantEntityBinding::OngoingCastState{};
    };

    multiplayer::BotCastRequest request{};
    if (!multiplayer::ConsumePendingBotCast(binding->bot_id, &request)) {
        return false;
    }
    const auto queued_target_actor_address = request.target_actor_address;
    int requested_skill_id = request.skill_id;
    ResolvedPrimaryCastDescriptor primary_descriptor{};
    bool have_primary_descriptor = false;
    if (requested_skill_id <= 0 && request.kind == multiplayer::BotCastKind::Primary) {
        if (!TryResolveProfilePrimaryCastDescriptor(
                binding->character_profile,
                &primary_descriptor)) {
            finish_attack_idle();
            if (error_message != nullptr) {
                *error_message =
                    "primary cast has no stock loadout pair. primary=" +
                    std::to_string(primary_descriptor.primary_entry_index) +
                    " combo=" + std::to_string(primary_descriptor.combo_entry_index);
            }
            return false;
        }
        have_primary_descriptor = true;
        requested_skill_id = primary_descriptor.dispatcher_skill_id;
    }
    if (requested_skill_id <= 0 &&
        (!have_primary_descriptor ||
         primary_descriptor.lane ==
             ParticipantEntityBinding::OngoingCastState::Lane::Dispatcher)) {
        finish_attack_idle();
        if (error_message != nullptr) {
            *error_message = "cast has no resolvable skill_id";
        }
        return false;
    }

    const auto combat_selection_state =
        have_primary_descriptor
            ? primary_descriptor.selection_state
            : ResolveCombatSelectionStateForSkillId(requested_skill_id);
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
    auto effective_target_actor_address =
        queued_target_actor_address != 0
            ? queued_target_actor_address
            : binding->facing_target_actor_address;
    if (effective_target_actor_address != 0) {
        float live_target_x = 0.0f;
        float live_target_y = 0.0f;
        float live_target_heading = 0.0f;
        if (TryComputeActorAimTowardTarget(
                actor_address,
                effective_target_actor_address,
                &live_target_heading,
                &live_target_x,
                &live_target_y)) {
            binding->facing_target_actor_address = effective_target_actor_address;
            aim_heading = live_target_heading;
            have_aim_heading = true;
            aim_target_x = live_target_x;
            aim_target_y = live_target_y;
            have_aim_target = true;
        } else if (effective_target_actor_address != binding->facing_target_actor_address &&
                   binding->facing_target_actor_address != 0 &&
                   TryComputeActorAimTowardTarget(
                       actor_address,
                       binding->facing_target_actor_address,
                       &live_target_heading,
                       &live_target_x,
                       &live_target_y)) {
            effective_target_actor_address = binding->facing_target_actor_address;
            binding->facing_target_actor_address = effective_target_actor_address;
            aim_heading = live_target_heading;
            have_aim_heading = true;
            aim_target_x = live_target_x;
            aim_target_y = live_target_y;
            have_aim_target = true;
        }
    }

    auto& ongoing = binding->ongoing_cast;
    ongoing = ParticipantEntityBinding::OngoingCastState{};
    ongoing.active = true;
    ongoing.lane =
        have_primary_descriptor
            ? primary_descriptor.lane
            : ParticipantEntityBinding::OngoingCastState::Lane::Dispatcher;
    ongoing.skill_id =
        have_primary_descriptor && primary_descriptor.build_skill_id > 0
            ? primary_descriptor.build_skill_id
            : requested_skill_id;
    ongoing.dispatcher_skill_id = requested_skill_id;
    ongoing.selection_state_target = combat_selection_state;
    ongoing.uses_dispatcher_skill_id =
        ongoing.lane == ParticipantEntityBinding::OngoingCastState::Lane::Dispatcher &&
        ongoing.dispatcher_skill_id > 0;
    ongoing.have_aim_heading = have_aim_heading;
    ongoing.aim_heading = aim_heading;
    ongoing.have_aim_target = have_aim_target;
    ongoing.aim_target_x = aim_target_x;
    ongoing.aim_target_y = aim_target_y;
    ongoing.target_actor_address = effective_target_actor_address;
    if (have_aim_heading) {
        binding->facing_heading_value = aim_heading;
        binding->facing_heading_valid = true;
    }
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
    if (ongoing.lane == ParticipantEntityBinding::OngoingCastState::Lane::PurePrimary &&
        ongoing.selection_state_pointer != 0 &&
        memory.IsReadableRange(
            ongoing.selection_state_pointer,
            ongoing.selection_state_object_snapshot.size()) &&
        memory.TryRead(
            ongoing.selection_state_pointer,
            ongoing.selection_state_object_snapshot.data(),
            ongoing.selection_state_object_snapshot.size())) {
        ongoing.selection_state_object_snapshot_valid = true;
    }
    if (ongoing.selection_state_pointer != 0) {
        PrimeSelectionBrainForCastStartup(
            actor_address,
            ongoing.selection_state_pointer,
            effective_target_actor_address,
            &ongoing);
    }
    ongoing.selection_state_before = ResolveActorAnimationStateId(actor_address);
    if (binding->gameplay_slot >= 0 && ongoing.selection_state_before != kUnknownAnimationStateId) {
        ongoing.gameplay_selection_state_before = ongoing.selection_state_before;
        std::string selection_error;
        if (ongoing.lane != ParticipantEntityBinding::OngoingCastState::Lane::PurePrimary) {
            (void)TryWriteActorAnimationStateIdDirect(actor_address, combat_selection_state);
        }
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
                RollbackPreparedStartup(&ongoing);
                finish_attack_idle();
                if (error_message != nullptr) {
                    *error_message = std::move(loadout_error);
                }
                return false;
            }
            const auto refresh_progression_address =
                memory.ResolveGameAddressOrZero(kActorProgressionRefresh);
            DWORD refresh_exception_code = 0;
            if (refresh_progression_address == 0 ||
                !CallActorProgressionRefreshSafe(
                    refresh_progression_address,
                    actor_address,
                    &refresh_exception_code)) {
                RollbackPreparedStartup(&ongoing);
                finish_attack_idle();
                if (error_message != nullptr) {
                    *error_message =
                        refresh_progression_address == 0
                            ? "Unable to resolve ActorProgressionRefresh."
                            : "Actor progression refresh (post primary build) failed with 0x" +
                                HexString(refresh_exception_code) + ".";
                }
                return false;
            }
            if (resolved_primary_skill_id > 0) {
                ongoing.skill_id = resolved_primary_skill_id;
            }
            if (ongoing.lane == ParticipantEntityBinding::OngoingCastState::Lane::PurePrimary) {
                ongoing.progression_spell_id_override_active =
                    memory.TryWriteField<std::int32_t>(
                        ongoing.progression_runtime_address,
                        kProgressionCurrentSpellIdOffset,
                        ongoing.skill_id);
            }
        } else {
            ongoing.progression_spell_id_override_active =
                memory.TryWriteField<std::int32_t>(
                    ongoing.progression_runtime_address,
                    kProgressionCurrentSpellIdOffset,
                    requested_skill_id);
        }
    }
    const auto native_tick_skill_id =
        ongoing.uses_dispatcher_skill_id && ongoing.dispatcher_skill_id > 0
            ? ongoing.dispatcher_skill_id
            : ongoing.skill_id;
    ongoing.requires_local_slot_native_tick =
        SkillRequiresLocalSlotDuringNativeTick(native_tick_skill_id);
    const auto cast_mana =
        multiplayer::ResolveBotCastManaCost(
            binding->character_profile,
            request.kind,
            request.secondary_slot,
            ongoing.skill_id);
    if (!cast_mana.resolved) {
        Log(
            "[bots] mana rejected. bot_id=" + std::to_string(binding->bot_id) +
            " skill_id=" + std::to_string(ongoing.skill_id) +
            " kind=" + (request.kind == multiplayer::BotCastKind::Primary ? std::string("primary") : std::string("secondary")) +
            " slot=" + std::to_string(request.secondary_slot) +
            " mode=unknown");
        RollbackPreparedStartup(&ongoing);
        finish_attack_idle();
        if (error_message != nullptr) {
            *error_message = "unknown mana cost for bot cast";
        }
        return false;
    }
    ongoing.mana_charge_kind = cast_mana.kind;
    ongoing.mana_cost = cast_mana.cost;
    ongoing.mana_statbook_level = cast_mana.statbook_level;
    ongoing.mana_last_charge_ms = static_cast<std::uint64_t>(GetTickCount64());
    if (cast_mana.kind != multiplayer::BotManaChargeKind::None) {
        if (ongoing.progression_runtime_address == 0) {
            RollbackPreparedStartup(&ongoing);
            finish_attack_idle();
            if (error_message != nullptr) {
                *error_message = "bot cast requires mana but has no progression runtime";
            }
            return false;
        }

        if (cast_mana.kind == multiplayer::BotManaChargeKind::PerCast) {
            float current_mp = 0.0f;
            float max_mp = 0.0f;
            if (!TryReadProgressionMana(ongoing.progression_runtime_address, &current_mp, &max_mp) ||
                current_mp + 0.001f < cast_mana.cost) {
                Log(
                    "[bots] mana rejected. bot_id=" + std::to_string(binding->bot_id) +
                    " skill_id=" + std::to_string(ongoing.skill_id) +
                    " kind=" + (request.kind == multiplayer::BotCastKind::Primary ? std::string("primary") : std::string("secondary")) +
                    " slot=" + std::to_string(request.secondary_slot) +
                    " mode=per_cast cost=" + std::to_string(cast_mana.cost) +
                    " before=" + std::to_string(current_mp));
                RollbackPreparedStartup(&ongoing);
                finish_attack_idle();
                if (error_message != nullptr) {
                    *error_message = "insufficient mana for bot cast";
                }
                return false;
            }
        } else {
            float current_mp = 0.0f;
            float max_mp = 0.0f;
            const float required_mana =
                multiplayer::ResolveBotManaRequiredToStart(cast_mana);
            if (!TryReadProgressionMana(ongoing.progression_runtime_address, &current_mp, &max_mp) ||
                current_mp + 0.001f < required_mana) {
                Log(
                    "[bots] mana rejected. bot_id=" + std::to_string(binding->bot_id) +
                    " skill_id=" + std::to_string(ongoing.skill_id) +
                    " kind=" + (request.kind == multiplayer::BotCastKind::Primary ? std::string("primary") : std::string("secondary")) +
                    " slot=" + std::to_string(request.secondary_slot) +
                    " mode=per_second rate=" + std::to_string(cast_mana.cost) +
                    " required=" + std::to_string(required_mana) +
                    " before=" + std::to_string(current_mp));
                RollbackPreparedStartup(&ongoing);
                finish_attack_idle();
                if (error_message != nullptr) {
                    *error_message = "insufficient mana for held bot cast";
                }
                return false;
            }
        }
    }
    ongoing.startup_in_progress = true;
    ongoing.startup_ticks_waiting = 0;
    if (ongoing.target_actor_address != 0) {
        (void)WriteOngoingCastNativeTargetActor(
            actor_address,
            &ongoing,
            ongoing.target_actor_address);
    }

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
    bool pure_primary_primer_called = false;
    DWORD pure_primary_primer_exception = 0;
    const bool dispatcher_primary_uses_primer =
        have_primary_descriptor &&
        ongoing.uses_dispatcher_skill_id &&
        !SkillRequiresBoundedHeldCastInputDuringNativeTick(ongoing.dispatcher_skill_id);
    const bool should_run_primary_damage_primer =
        request.kind == multiplayer::BotCastKind::Primary &&
        (ongoing.lane == ParticipantEntityBinding::OngoingCastState::Lane::PurePrimary ||
         dispatcher_primary_uses_primer);
    if (should_run_primary_damage_primer) {
        const auto pure_primary_start_address =
            memory.ResolveGameAddressOrZero(kSpellCastPurePrimary);
        if (pure_primary_start_address != 0) {
            LocalPlayerCastShimState shim_state;
            const auto shim_active = EnterLocalPlayerCastShim(binding, &shim_state);
            pure_primary_primer_called =
                shim_active &&
                CallPurePrimarySpellStartSafe(
                    pure_primary_start_address,
                    actor_address,
                    &pure_primary_primer_exception);
            LeaveLocalPlayerCastShim(shim_state);
        }
        if (pure_primary_primer_called && ongoing.uses_dispatcher_skill_id) {
            PrimeGameplaySlotPostGateDispatchState(actor_address, ongoing.dispatcher_skill_id);
            if (ongoing.target_actor_address != 0) {
                (void)WriteOngoingCastNativeTargetActor(
                    actor_address,
                    &ongoing,
                    ongoing.target_actor_address);
            }
            ReapplyOngoingCastSelectionState(binding, actor_address, ongoing, true);
        }
    }
    g_gameplay_slot_hud_probe_actor = actor_address;
    g_gameplay_slot_hud_probe_until_ms = static_cast<std::uint64_t>(GetTickCount64()) + 400;
    Log(
        "[bots] wizard cast prepped. bot_id=" + std::to_string(binding->bot_id) +
        " kind=" +
            (IsGameplaySlotWizardKind(binding->kind)
                 ? std::string("gameplay_slot")
                 : std::string("standalone")) +
        " gameplay_slot=" + std::to_string(binding->gameplay_slot) +
        " skill_id=" + std::to_string(ongoing.skill_id) +
        " dispatcher_skill_id=" + std::to_string(ongoing.dispatcher_skill_id) +
        " lane=" +
            (ongoing.lane == ParticipantEntityBinding::OngoingCastState::Lane::PurePrimary
                 ? std::string("pure_primary")
                 : std::string("dispatcher")) +
        " selection_state=" + std::to_string(combat_selection_state) +
        " progression_runtime=" + HexString(ongoing.progression_runtime_address) +
        " progression_spell_id=" + std::to_string(
            ongoing.progression_runtime_address != 0
                ? memory.ReadFieldOr<std::int32_t>(
                      ongoing.progression_runtime_address,
                      kProgressionCurrentSpellIdOffset,
                      0)
                : 0) +
        " pure_primary_primer=" + std::to_string(pure_primary_primer_called ? 1 : 0) +
        " pure_primary_primer_seh=" + HexString(pure_primary_primer_exception) +
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
    //     keeps stock input held only for native-held primaries; (c) bounded held
    //     primaries release synthetic input when native charge reaches the chosen
    //     release point, let the live world object update, then invoke the stock
    //     active-handle cleanup so native damage/effect code remains authoritative.
    //     kMaxTicksWaiting is a safety cap against unexpected latch states, not a
