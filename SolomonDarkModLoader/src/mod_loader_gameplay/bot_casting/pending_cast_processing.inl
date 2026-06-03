struct BotBoulderReleaseHoldWrites {
    bool charge = false;
    bool release_charge = false;
    bool release_damage = false;
    bool release_base_damage = false;
    bool growth_rate = false;
    bool growth_stop_eligible = false;
    float growth_stop_min_charge = 0.0f;
    float damage_output_scale = 0.0f;
    float scaled_release_base_damage = 0.0f;
};

struct BotCastActivitySnapshot {
    std::uint8_t active_cast_group = kBotCastActorActiveCastGroupSentinel;
    std::uint8_t drive_state = 0;
    std::uint8_t no_interrupt = 0;
    std::uint32_t action_latch_e4 = 0;
    std::uint32_t action_latch_e8 = 0;
};

bool TryReadBotCastActivitySnapshot(
    ProcessMemory& memory,
    uintptr_t actor_address,
    BotCastActivitySnapshot* snapshot) {
    if (actor_address == 0 || snapshot == nullptr) {
        return false;
    }

    BotCastActivitySnapshot candidate{};
    if (!memory.TryReadField(actor_address, kActorActiveCastGroupByteOffset, &candidate.active_cast_group) ||
        !memory.TryReadField(actor_address, kActorAnimationDriveStateByteOffset, &candidate.drive_state) ||
        !memory.TryReadField(actor_address, kActorNoInterruptFlagOffset, &candidate.no_interrupt) ||
        !memory.TryReadField(actor_address, kActorPrimaryActionLatchE4Offset, &candidate.action_latch_e4) ||
        !memory.TryReadField(actor_address, kActorPrimaryActionLatchE8Offset, &candidate.action_latch_e8)) {
        return false;
    }

    *snapshot = candidate;
    return true;
}

bool HasBotNativeCastActivity(const BotCastActivitySnapshot& snapshot) {
    return snapshot.active_cast_group != kBotCastActorActiveCastGroupSentinel ||
           snapshot.drive_state != 0 ||
           snapshot.no_interrupt != 0 ||
           snapshot.action_latch_e4 != 0 ||
           snapshot.action_latch_e8 != 0;
}

BotBoulderReleaseHoldWrites HoldBotBoulderAtReleaseCharge(
    ProcessMemory& memory,
    const BotNativeActiveSpellObjectState& active_spell_state,
    float release_charge,
    bool write_release_damage_fields) {
    BotBoulderReleaseHoldWrites writes{};
    if (active_spell_state.object == 0 ||
        !std::isfinite(release_charge) ||
        release_charge <= 0.0f) {
        return writes;
    }

    writes.charge =
        memory.TryWriteField<float>(
            active_spell_state.object,
            kSpellObjectChargeOffset,
            release_charge);
    writes.release_charge =
        memory.TryWriteField<float>(
            active_spell_state.object,
            kSpellObjectReleaseChargeOffset,
            release_charge);
    if (write_release_damage_fields) {
        writes.damage_output_scale = ResolveEarthBoulderDamageOutputScale();
        writes.scaled_release_base_damage =
            ResolveEarthBoulderScaledReleaseBaseDamage(
                active_spell_state.release_base_damage,
                writes.damage_output_scale);
        if (std::isfinite(writes.scaled_release_base_damage) &&
            writes.scaled_release_base_damage > 0.0f) {
            writes.release_damage =
                memory.TryWriteField<float>(
                    active_spell_state.object,
                    kSpellObjectReleaseDamageOffset,
                    writes.scaled_release_base_damage);
            writes.release_base_damage =
                memory.TryWriteField<float>(
                    active_spell_state.object,
                    kSpellObjectReleaseBaseDamageOffset,
                    writes.scaled_release_base_damage);
        }
    }
    writes.growth_stop_min_charge =
        ResolveEarthBoulderReleaseGrowthStopMinCharge();
    writes.growth_stop_eligible =
        release_charge + 0.001f >= writes.growth_stop_min_charge;
    if (writes.growth_stop_eligible) {
        writes.growth_rate =
            memory.TryWriteField<float>(
                active_spell_state.object,
                kSpellObjectGrowthRateOffset,
                0.0f);
    }
    return writes;
}

bool StopOngoingBotCastForManaReserve(
    ParticipantEntityBinding* binding,
    std::string_view phase) {
    if (binding == nullptr ||
        binding->actor_address == 0 ||
        binding->bot_id == 0 ||
        !binding->ongoing_cast.active) {
        return false;
    }

    auto& ongoing = binding->ongoing_cast;
    if (ongoing.mana_charge_kind == multiplayer::BotManaChargeKind::None ||
        ongoing.bounded_release_requested ||
        !std::isfinite(ongoing.mana_cost) ||
        ongoing.mana_cost <= 0.0f) {
        return false;
    }

    const auto actor_address = binding->actor_address;
    uintptr_t progression_runtime_address = ongoing.progression_runtime_address;
    if (progression_runtime_address == 0) {
        (void)TryResolveActorProgressionRuntime(actor_address, &progression_runtime_address);
        ongoing.progression_runtime_address = progression_runtime_address;
    }
    if (progression_runtime_address == 0) {
        return false;
    }

    float current_mp = 0.0f;
    float max_mp = 0.0f;
    if (!TryReadProgressionMana(progression_runtime_address, &current_mp, &max_mp)) {
        return false;
    }

    bool mana_reserve_active = false;
    if (!multiplayer::RefreshBotManaReserveState(
            binding->bot_id,
            current_mp,
            max_mp,
            &mana_reserve_active) ||
        !mana_reserve_active) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto cleanup_address = memory.ResolveGameAddressOrZero(kCastActiveHandleCleanup);
    if (cleanup_address == 0) {
        return false;
    }

    const float mana_ratio =
        std::isfinite(max_mp) && max_mp > 0.0f
            ? current_mp / max_mp
            : 0.0f;
    Log(
        "[bots] native mana reserve. bot_id=" + std::to_string(binding->bot_id) +
        " skill_id=" + std::to_string(ongoing.skill_id) +
        " mode=" + multiplayer::BotManaChargeKindLabel(ongoing.mana_charge_kind) +
        " phase=" + std::string(phase) +
        " progression_level=" + std::to_string(ongoing.mana_progression_level) +
        " mp=" + std::to_string(current_mp) +
        " max_mp=" + std::to_string(max_mp) +
        " ratio=" + std::to_string(mana_ratio) +
        " enter_ratio=" +
            std::to_string(multiplayer::kBotManaReserveEnterRatio) +
        " exit_ratio=" +
            std::to_string(multiplayer::kBotManaReserveExitRatio));

    BotCastProcessingContext cast_context{binding, actor_address, cleanup_address, &memory};
    FinishBotCastNativeLifecycle(cast_context, ongoing, "mana_reserve", true);
    ongoing = ParticipantEntityBinding::OngoingCastState{};
    return true;
}

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

    BotCastProcessingContext cast_context{binding, actor_address, cleanup_address, &memory};
    const bool actor_dead = IsActorRuntimeDead(actor_address);

    // --- Watch continuation path ---------------------------------------------
    // Gameplay-slot bots keep stock movement/render ownership, but their cast
    // startup cannot rely on the local-player input gate inside
    // PlayerActorTick: stock clears actor+0x270 every frame before it reaches
    // FUN_00548A00. Re-pin the prepared fields here and, if stock never
    // preserved the skill id, perform a single post-stock startup dispatch with
    // the actor still carrying its real gameplay slot.
    if (binding->ongoing_cast.active) {
        auto& ongoing = binding->ongoing_cast;

        if (actor_dead) {
            FinishBotCastNativeLifecycle(cast_context, ongoing, "dead", true);
            ongoing = ParticipantEntityBinding::OngoingCastState{};
            return true;
        }

        // Keep native target/aim fresh for startup and native held primaries.
        // Bounded held Earth follows the bot's live target while the boulder is
        // charging; once release is requested, target refresh stops so damage
        // projection and release cleanup stay tied to the same victim.
        const auto native_active_skill_id = ResolveOngoingNativeTickSkillId(ongoing);
        const bool refresh_ongoing_target_state =
            OngoingCastShouldRefreshNativeTargetState(ongoing);
        bool target_refreshed = false;
        if (refresh_ongoing_target_state) {
            target_refreshed = RefreshOngoingCastAimFromFacingTarget(binding, &ongoing);
        }
        // Do not re-write pure-primary actor selection state after startup.
        // Those handlers mutate the first word as their continuous action
        // state. Dispatcher primaries still need the element selection state
        // pinned so PlayerActorTick runs the matching native stat initializer
        // before it calls the dispatcher.
        if (ongoing.uses_dispatcher_skill_id && refresh_ongoing_target_state) {
            ReapplyOngoingCastSelectionState(binding, actor_address, ongoing, true);
        }
        if (ongoing.have_aim_heading) {
            ApplyWizardActorFacingState(actor_address, ongoing.aim_heading);
            binding->facing_heading_value = ongoing.aim_heading;
            binding->facing_heading_valid = true;
        }
        if (ongoing.have_aim_target) {
            (void)memory.TryWriteField(actor_address, kActorAimTargetXOffset, ongoing.aim_target_x);
            (void)memory.TryWriteField(actor_address, kActorAimTargetYOffset, ongoing.aim_target_y);
            (void)memory.TryWriteField<std::uint32_t>(actor_address, kActorAimTargetAux0Offset, 0);
            (void)memory.TryWriteField<std::uint32_t>(actor_address, kActorAimTargetAux1Offset, 0);
        }
        (void)memory.TryWriteField<std::uint8_t>(actor_address, kActorCastSpreadModeByteOffset, 0);
        constexpr int kBoundedHeldNativeReleaseEdgeTicks = 3;
        constexpr int kBoundedHeldPostReleaseWorldUpdateTicks =
            kBoundedHeldNativeReleaseEdgeTicks + 8;
        const bool preserve_bounded_release_edge =
            ongoing.bounded_release_requested &&
            ongoing.bounded_post_release_ticks_waiting < kBoundedHeldNativeReleaseEdgeTicks;
        const bool publish_ongoing_skill_id =
            ongoing.uses_dispatcher_skill_id &&
            !(OngoingCastRequiresBoundedHeldCastInputDuringNativeTick(ongoing) &&
              ongoing.bounded_release_requested &&
              !preserve_bounded_release_edge);
        (void)memory.TryWriteField<std::int32_t>(
            actor_address,
            kActorPrimarySkillIdOffset,
            publish_ongoing_skill_id ? ongoing.dispatcher_skill_id : 0);
        if (ongoing.bounded_release_requested) {
            (void)memory.TryWriteField<std::int32_t>(
                actor_address,
                kActorPreviousSkillIdOffset,
                preserve_bounded_release_edge ? native_active_skill_id : 0);
            if (!preserve_bounded_release_edge) {
                (void)memory.TryWriteField<std::uint32_t>(
                    actor_address,
                    kActorPrimaryActionLatchE4Offset,
                    0);
                (void)memory.TryWriteField<std::uint32_t>(
                    actor_address,
                    kActorPrimaryActionLatchE8Offset,
                    0);
                (void)memory.TryWriteField<std::uint8_t>(
                    actor_address,
                    kActorPostGateActiveByteOffset,
                    0);
            }
        }
        if (refresh_ongoing_target_state) {
            RefreshSelectionBrainTargetForOngoingCast(ongoing);
        }

        if (IsGameplaySlotWizardKind(binding->kind) &&
            ongoing.startup_in_progress &&
            ongoing.uses_dispatcher_skill_id &&
            !ongoing.post_stock_dispatch_attempted) {
            const auto native_mana_rate_config =
                ValidateNativeManaRateConfigForOngoingCast(actor_address, ongoing);
            if (native_mana_rate_config.required &&
                !native_mana_rate_config.plausible) {
                if (!ongoing.native_mana_rate_config_pending_logged) {
                    ongoing.native_mana_rate_config_pending_logged = true;
                    Log(
                        "[bots] native mana rate config pending. bot_id=" +
                        std::to_string(binding->bot_id) +
                        " skill_id=" + std::to_string(ongoing.skill_id) +
                        " dispatcher_skill_id=" +
                            std::to_string(ongoing.dispatcher_skill_id) +
                        " reason=" + native_mana_rate_config.reason +
                        " invalidated=" +
                            std::to_string(native_mana_rate_config.invalidated ? 1 : 0) +
                        " readable=" +
                            std::to_string(native_mana_rate_config.readable ? 1 : 0) +
                        " native_rate=" +
                            std::to_string(native_mana_rate_config.native_rate) +
                        " expected_rate=" +
                            std::to_string(native_mana_rate_config.expected_rate) +
                        " max_allowed_rate=" +
                            std::to_string(native_mana_rate_config.max_allowed_rate) +
                        " ticks=" + std::to_string(ongoing.startup_ticks_waiting));
                }
            } else if (ongoing.uses_dispatcher_skill_id) {
                PrimeGameplaySlotPostGateDispatchState(actor_address, ongoing);
                const auto native_target_actor_address =
                    ResolveOngoingCastNativeTargetActor(binding, ongoing);
                if (native_target_actor_address != 0) {
                    (void)WriteOngoingCastNativeTargetActor(
                        actor_address,
                        &ongoing,
                        native_target_actor_address);
                }
                ReapplyOngoingCastSelectionState(binding, actor_address, ongoing, true);
            }
            if (!native_mana_rate_config.required ||
                native_mana_rate_config.plausible) {
                DWORD startup_exception_code = 0;
                bool startup_dispatched = false;
                uintptr_t startup_gameplay_address = 0;
                std::uint8_t saved_cast_intent = 0;
                std::uint8_t saved_mouse_left = 0;
                std::size_t live_mouse_left_offset = 0;
                bool startup_cast_intent_applied = false;
                bool startup_mouse_left_applied = false;
                bool gameplay_input_buffer_readable = false;
                bool gameplay_mouse_left_readable = false;
                BotCastActivitySnapshot activity_before_dispatch{};
                const bool native_activity_before_dispatch =
                    TryReadBotCastActivitySnapshot(
                        memory,
                        actor_address,
                        &activity_before_dispatch) &&
                    HasBotNativeCastActivity(activity_before_dispatch);
                if (!native_activity_before_dispatch &&
                    TryResolveCurrentGameplayScene(&startup_gameplay_address) &&
                    startup_gameplay_address != 0) {
                    if (!memory.TryReadField(
                        startup_gameplay_address,
                        kGameplayCastIntentOffset,
                        &saved_cast_intent)) {
                        startup_gameplay_address = 0;
                    } else {
                        startup_cast_intent_applied =
                            memory.TryWriteField<std::uint8_t>(
                                startup_gameplay_address,
                                kGameplayCastIntentOffset,
                                static_cast<std::uint8_t>(1));
                    }
                    int input_buffer_index = -1;
                    if (startup_gameplay_address != 0 &&
                        memory.TryReadField(
                            startup_gameplay_address,
                            kGameplayInputBufferIndexOffset,
                            &input_buffer_index) &&
                        input_buffer_index >= 0) {
                        gameplay_input_buffer_readable = true;
                        live_mouse_left_offset =
                            static_cast<std::size_t>(
                                input_buffer_index * kGameplayInputBufferStride +
                                kGameplayMouseLeftButtonOffset);
                        if (memory.TryReadField(
                            startup_gameplay_address,
                            live_mouse_left_offset,
                            &saved_mouse_left)) {
                            gameplay_mouse_left_readable = true;
                            startup_mouse_left_applied =
                                memory.TryWriteField<std::uint8_t>(
                                    startup_gameplay_address,
                                    live_mouse_left_offset,
                                    static_cast<std::uint8_t>(1));
                        }
                    }
                }
                if (native_activity_before_dispatch) {
                    startup_dispatched = true;
                } else {
                    InvokeBotCastWithNativeActorSlot(cast_context, [&] {
                        startup_dispatched = CallSpellCastDispatcherSafe(
                            dispatcher_address,
                            actor_address,
                            &startup_exception_code);
                    });
                }
                if (startup_gameplay_address != 0) {
                    if (startup_mouse_left_applied) {
                        (void)memory.TryWriteField<std::uint8_t>(
                            startup_gameplay_address,
                            live_mouse_left_offset,
                            saved_mouse_left);
                    }
                    if (startup_cast_intent_applied) {
                        (void)memory.TryWriteField<std::uint8_t>(
                            startup_gameplay_address,
                            kGameplayCastIntentOffset,
                            saved_cast_intent);
                    }
                }
                ongoing.post_stock_dispatch_attempted = true;
                std::uint8_t drive_after_dispatch = 0;
                std::uint8_t no_interrupt_after_dispatch = 0;
                std::uint8_t active_group_after_dispatch = kBotCastActorActiveCastGroupSentinel;
                if (!memory.TryReadField(actor_address, kActorAnimationDriveStateByteOffset, &drive_after_dispatch) ||
                    !memory.TryReadField(actor_address, kActorNoInterruptFlagOffset, &no_interrupt_after_dispatch) ||
                    !memory.TryReadField(actor_address, kActorActiveCastGroupByteOffset, &active_group_after_dispatch)) {
                    FinishBotCastNativeLifecycle(
                        cast_context,
                        ongoing,
                        "post_dispatch_state_unreadable",
                        true);
                    ongoing = ParticipantEntityBinding::OngoingCastState{};
                    return true;
                }
                Log(
                    "[bots] gameplay-slot post-stock dispatch. bot_id=" +
                    std::to_string(binding->bot_id) +
                    " skill_id=" + std::to_string(ongoing.dispatcher_skill_id) +
                    " ok=" + (startup_dispatched ? std::string("1") : std::string("0")) +
                    " seh=" + HexString(startup_exception_code) +
                    " native_activity_before=" +
                    (native_activity_before_dispatch ? std::string("1") : std::string("0")) +
                    " input_buffer=" +
                    (gameplay_input_buffer_readable ? std::string("1") : std::string("0")) +
                    " mouse_left=" +
                    (gameplay_mouse_left_readable ? std::string("1") : std::string("0")) +
                    " group_post=" + HexString(active_group_after_dispatch) +
                    " drive_post=" + HexString(drive_after_dispatch) +
                    " no_int_post=" + HexString(no_interrupt_after_dispatch) +
                    " mana_rate=" +
                        std::to_string(native_mana_rate_config.native_rate));
                if (!startup_dispatched) {
                    FinishBotCastNativeLifecycle(cast_context, ongoing, "dispatch_seh", true);
                    ongoing = ParticipantEntityBinding::OngoingCastState{};
                    return true;
                }
            }
        }

        std::uint8_t drive_state = 0;
        std::uint8_t no_interrupt = 0;
        std::uint32_t actor_e4 = 0;
        std::uint32_t actor_e8 = 0;
        std::uint8_t active_cast_group = kBotCastActorActiveCastGroupSentinel;
        if (!memory.TryReadField(actor_address, kActorAnimationDriveStateByteOffset, &drive_state) ||
            !memory.TryReadField(actor_address, kActorNoInterruptFlagOffset, &no_interrupt) ||
            !memory.TryReadField(actor_address, kActorPrimaryActionLatchE4Offset, &actor_e4) ||
            !memory.TryReadField(actor_address, kActorPrimaryActionLatchE8Offset, &actor_e8) ||
            !memory.TryReadField(actor_address, kActorActiveCastGroupByteOffset, &active_cast_group)) {
            FinishBotCastNativeLifecycle(cast_context, ongoing, "active_cast_state_unreadable", true);
            ongoing = ParticipantEntityBinding::OngoingCastState{};
            return true;
        }
        const bool has_live_handle = active_cast_group != kBotCastActorActiveCastGroupSentinel;
        const bool native_primary_action_active =
            OngoingCastNeedsNativeTargetActor(ongoing) &&
            (actor_e4 != 0 || actor_e8 != 0);
        const bool native_remote_participant = IsNativeRemoteParticipantBinding(binding);
        const bool remote_input_driven_cast =
            native_remote_participant && ongoing.remote_input_controlled;
        if (remote_input_driven_cast) {
            multiplayer::BotCastInputState remote_input_state{};
            const bool have_remote_input =
                multiplayer::ReadBotCastInputState(
                    binding->bot_id,
                    &remote_input_state) &&
                remote_input_state.cast_sequence ==
                    ongoing.remote_input_cast_sequence;
            const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
            if (have_remote_input) {
                ongoing.remote_input_release_requested =
                    remote_input_state.release_requested;
                ongoing.remote_input_timed_out =
                    !remote_input_state.release_requested &&
                    remote_input_state.last_update_ms != 0 &&
                    now_ms > remote_input_state.last_update_ms &&
                    now_ms - remote_input_state.last_update_ms >= 400;
                if (remote_input_state.has_aim_target) {
                    ongoing.have_aim_target = true;
                    ongoing.aim_target_x = remote_input_state.aim_target_x;
                    ongoing.aim_target_y = remote_input_state.aim_target_y;
                }
                if (remote_input_state.has_aim_angle) {
                    ongoing.have_aim_heading = true;
                    ongoing.aim_heading = remote_input_state.aim_angle;
                }
                if (remote_input_state.target_actor_address != 0) {
                    ongoing.target_actor_address =
                        remote_input_state.target_actor_address;
                    binding->facing_target_actor_address =
                        remote_input_state.target_actor_address;
                } else {
                    ongoing.target_actor_address = 0;
                    binding->facing_target_actor_address = 0;
                    ClearOngoingCastNativeTargetActor(actor_address, &ongoing);
                }
            } else {
                ongoing.remote_input_timed_out =
                    ongoing.ticks_waiting >
                    ParticipantEntityBinding::OngoingCastState::kTargetlessRetargetGraceTicks;
            }
        }

        ongoing.ticks_waiting += 1;
        if (ongoing.startup_in_progress) {
            ongoing.startup_ticks_waiting += 1;
        }
        if (ongoing.remote_input_release_requested ||
            ongoing.remote_input_timed_out) {
            ongoing.remote_input_release_ticks_waiting += 1;
        } else {
            ongoing.remote_input_release_ticks_waiting = 0;
        }
        if (drive_state != 0 || no_interrupt != 0 || native_primary_action_active) {
            ongoing.saw_latch = true;
        }
        if (has_live_handle || drive_state != 0 || no_interrupt != 0 || native_primary_action_active) {
            ongoing.saw_activity = true;
            ongoing.startup_in_progress = false;
        }
        if (has_live_handle) {
            ongoing.saw_live_handle = true;
        }
        bool mana_stop_requested = false;
        const char* mana_stop_label = "mana_depleted";
        if (ongoing.mana_charge_kind != multiplayer::BotManaChargeKind::None &&
            ongoing.progression_runtime_address != 0 &&
            ongoing.saw_activity &&
            !remote_input_driven_cast &&
            !ongoing.bounded_release_requested &&
            ongoing.mana_cost > 0.0f) {
            float current_mp = 0.0f;
            float max_mp = 0.0f;
            constexpr float kNativeManaDepletedEpsilon = 0.001f;
            if (TryReadProgressionMana(ongoing.progression_runtime_address, &current_mp, &max_mp)) {
                bool mana_reserve_active = false;
                const bool mana_reserve_refreshed =
                    multiplayer::RefreshBotManaReserveState(
                        binding->bot_id,
                        current_mp,
                        max_mp,
                        &mana_reserve_active);
                if (current_mp <= kNativeManaDepletedEpsilon) {
                    mana_stop_requested = true;
                    mana_stop_label = "mana_depleted";
                    Log(
                        "[bots] native mana depleted. bot_id=" + std::to_string(binding->bot_id) +
                        " skill_id=" + std::to_string(ongoing.skill_id) +
                        " mode=" + multiplayer::BotManaChargeKindLabel(ongoing.mana_charge_kind) +
                        " progression_level=" +
                            std::to_string(ongoing.mana_progression_level) +
                        " mp=" + std::to_string(current_mp) +
                        " max_mp=" + std::to_string(max_mp));
                } else if (mana_reserve_refreshed && mana_reserve_active) {
                    const float mana_ratio =
                        std::isfinite(max_mp) && max_mp > 0.0f
                            ? current_mp / max_mp
                            : 0.0f;
                    mana_stop_requested = true;
                    mana_stop_label = "mana_reserve";
                    Log(
                        "[bots] native mana reserve. bot_id=" + std::to_string(binding->bot_id) +
                        " skill_id=" + std::to_string(ongoing.skill_id) +
                        " mode=" + multiplayer::BotManaChargeKindLabel(ongoing.mana_charge_kind) +
                        " progression_level=" +
                            std::to_string(ongoing.mana_progression_level) +
                        " mp=" + std::to_string(current_mp) +
                        " max_mp=" + std::to_string(max_mp) +
                        " ratio=" + std::to_string(mana_ratio) +
                        " enter_ratio=" +
                            std::to_string(multiplayer::kBotManaReserveEnterRatio) +
                        " exit_ratio=" +
                            std::to_string(multiplayer::kBotManaReserveExitRatio));
                }
            }
        }

        // Some native primary actions do not publish a live spell-object handle,
        // but their emission still runs through actor+0xE4/0xE8. Remote player
        // mirror casts are driven by explicit input phases: keep them alive
        // while the sender is holding input, then settle promptly after release
        // or input timeout.
        constexpr int kRemoteReleasedPurePrimaryNoHandleSettleTicks = 2;
        constexpr int kRemotePerCastPurePrimaryProjectileSettleTicks = 2;
        constexpr int kRemotePerCastPurePrimaryNoProjectileSafetyTicks = 90;
        constexpr int kRemotePurePrimaryNoHandleMinimumVisibleTicks = 20;
        constexpr int kBotPurePrimaryNoHandleSettleTicks = 160;
        const bool remote_input_release_or_timeout =
            remote_input_driven_cast &&
            (ongoing.remote_input_release_requested ||
             ongoing.remote_input_timed_out);
        const bool pure_primary_without_live_handle =
            ongoing.lane == ParticipantEntityBinding::OngoingCastState::Lane::PurePrimary &&
            ongoing.saw_activity &&
            !has_live_handle;
        const bool remote_per_cast_pure_primary_without_live_handle =
            remote_input_driven_cast &&
            pure_primary_without_live_handle &&
            ongoing.mana_charge_kind == multiplayer::BotManaChargeKind::PerCast;
        if (remote_per_cast_pure_primary_without_live_handle &&
            ongoing.remote_per_cast_projectile_baseline_valid &&
            !ongoing.remote_per_cast_projectile_observed) {
            uintptr_t observed_projectile_actor = 0;
            if (TryFindNewPurePrimaryProjectileActorInScene(
                    ongoing.remote_per_cast_projectile_expected_type,
                    ongoing.remote_per_cast_projectile_addresses_before,
                    &observed_projectile_actor)) {
                ongoing.remote_per_cast_projectile_observed = true;
                ongoing.remote_per_cast_projectile_observed_actor = observed_projectile_actor;
            }
        }
        if (ongoing.remote_per_cast_projectile_observed) {
            ongoing.remote_per_cast_projectile_observed_ticks_waiting += 1;
        } else {
            ongoing.remote_per_cast_projectile_observed_ticks_waiting = 0;
        }
        const bool remote_per_cast_pure_primary_no_handle_settled =
            remote_per_cast_pure_primary_without_live_handle &&
            ((ongoing.remote_per_cast_projectile_observed &&
              ongoing.remote_per_cast_projectile_observed_ticks_waiting >=
                  kRemotePerCastPurePrimaryProjectileSettleTicks) ||
             ongoing.ticks_waiting >= kRemotePerCastPurePrimaryNoProjectileSafetyTicks);
        const bool remote_release_driven_pure_primary_no_handle_settled =
            remote_input_driven_cast &&
            pure_primary_without_live_handle &&
            ongoing.mana_charge_kind != multiplayer::BotManaChargeKind::PerCast &&
            remote_input_release_or_timeout &&
            ongoing.remote_input_release_ticks_waiting >=
                kRemoteReleasedPurePrimaryNoHandleSettleTicks &&
            ongoing.ticks_waiting >= kRemotePurePrimaryNoHandleMinimumVisibleTicks;
        const bool pure_primary_no_handle_settled =
            pure_primary_without_live_handle &&
            (remote_input_driven_cast
                 ? (remote_per_cast_pure_primary_no_handle_settled ||
                    remote_release_driven_pure_primary_no_handle_settled)
                 : ongoing.ticks_waiting >= kBotPurePrimaryNoHandleSettleTicks);
        const bool held_native_cast =
            OngoingCastRequiresHeldCastInputDuringNativeTick(ongoing);
        const bool bounded_held_native_cast =
            OngoingCastRequiresBoundedHeldCastInputDuringNativeTick(ongoing);
        const auto active_spell_state = ReadBotNativeActiveSpellObjectState(cast_context, false);
        const auto earth_max_charge = active_spell_state.max_charge;
        const auto earth_damage_projection =
            bounded_held_native_cast
                ? ReadBotBoulderDamageProjectionSnapshot(cast_context, active_spell_state)
                : BotBoulderDamageProjectionSnapshot{};
        const bool earth_object_charge_reached =
            bounded_held_native_cast &&
            active_spell_state.readable &&
            std::isfinite(active_spell_state.charge) &&
            std::isfinite(earth_max_charge) &&
            earth_max_charge > 0.0f &&
            active_spell_state.charge >= earth_max_charge - 0.001f;
        const bool earth_max_size_reached =
            bounded_held_native_cast &&
            active_spell_state.readable &&
            (active_spell_state.boulder_max_size_reached || earth_object_charge_reached);
        const float earth_min_release_charge =
            bounded_held_native_cast
                ? ResolveEarthBoulderReleaseGrowthStopMinCharge()
                : 0.0f;
        const bool earth_min_release_charge_known =
            std::isfinite(earth_min_release_charge) &&
            earth_min_release_charge > 0.0f;
        const bool earth_native_min_release_charge_reached =
            bounded_held_native_cast &&
            active_spell_state.readable &&
            std::isfinite(active_spell_state.charge) &&
            (!earth_min_release_charge_known ||
             active_spell_state.charge + 0.001f >= earth_min_release_charge);
        const bool earth_target_lethal_release_ready =
            bounded_held_native_cast &&
            earth_native_min_release_charge_reached &&
            earth_damage_projection.readable &&
            earth_damage_projection.target_actor != 0 &&
            std::isfinite(earth_damage_projection.target_hp) &&
            earth_damage_projection.target_hp > 0.0f &&
            std::isfinite(earth_damage_projection.projected_hp_damage) &&
            earth_damage_projection.projected_hp_damage + 0.001f >= earth_damage_projection.target_hp;
        const bool remote_bounded_release_ready =
            remote_input_driven_cast &&
            remote_input_release_or_timeout &&
            earth_native_min_release_charge_reached &&
            active_spell_state.readable;
        const bool bot_bounded_release_ready =
            !remote_input_driven_cast &&
            (earth_max_size_reached || earth_target_lethal_release_ready);
        const bool bounded_held_release_ready =
            bounded_held_native_cast &&
            active_spell_state.readable &&
            (remote_bounded_release_ready || bot_bounded_release_ready);
        const bool bounded_release_just_requested =
            bounded_held_release_ready && !ongoing.bounded_release_requested;
        if (bounded_release_just_requested) {
            float release_charge = earth_damage_projection.charge;
            float release_base_damage = earth_damage_projection.base_damage;
            float release_projected_damage = earth_damage_projection.projected_damage;
            float release_damage_output_scale =
                earth_damage_projection.damage_output_scale;
            float release_damage_scale =
                earth_damage_projection.release_damage_scale;
            float release_damage_floor =
                earth_damage_projection.release_damage_floor;
            float release_damage_cap_scale =
                earth_damage_projection.release_damage_cap_scale;
            float release_projected_release_damage =
                earth_damage_projection.projected_release_damage;
            float release_projected_hp_damage =
                earth_damage_projection.projected_hp_damage;
            if ((!std::isfinite(release_charge) || release_charge <= 0.0f) &&
                active_spell_state.readable &&
                std::isfinite(active_spell_state.charge) &&
                active_spell_state.charge > 0.0f) {
                release_charge = active_spell_state.charge;
            }
            if (!std::isfinite(release_base_damage) || release_base_damage <= 0.0f) {
                release_base_damage =
                    ResolveEarthBoulderScaledReleaseBaseDamage(
                        active_spell_state.release_base_damage,
                        release_damage_output_scale);
            }
            if (!std::isfinite(release_damage_output_scale) ||
                release_damage_output_scale <= 0.0f) {
                release_damage_output_scale = ResolveEarthBoulderDamageOutputScale();
            }
            if (!std::isfinite(release_damage_scale) ||
                release_damage_scale <= 0.0f) {
                release_damage_scale = ResolveEarthBoulderReleaseDamageScale();
            }
            if (!std::isfinite(release_damage_floor) ||
                release_damage_floor < 0.0f) {
                release_damage_floor = ResolveEarthBoulderReleaseDamageFloor();
            }
            if (!std::isfinite(release_damage_cap_scale) ||
                release_damage_cap_scale <= 0.0f) {
                release_damage_cap_scale = ResolveEarthBoulderReleaseDamageCapScale();
            }
            if (std::isfinite(release_base_damage) &&
                release_base_damage > 0.0f &&
                std::isfinite(release_charge) &&
                release_charge > 0.0f) {
                release_projected_damage = release_base_damage * release_charge * release_charge;
                release_projected_release_damage =
                    ProjectEarthBoulderReleaseDamage(
                        release_base_damage,
                        release_charge,
                        release_damage_scale,
                        release_damage_floor,
                        release_damage_cap_scale);
                release_projected_hp_damage = release_projected_release_damage;
            }
            ongoing.bounded_release_requested = true;
            ongoing.bounded_max_size_reached = earth_max_size_reached;
            ongoing.bounded_release_at_max_size = earth_max_size_reached;
            ongoing.bounded_release_target_lethal =
                !remote_input_driven_cast &&
                !earth_max_size_reached &&
                earth_target_lethal_release_ready;
            ongoing.bounded_release_charge = release_charge;
            ongoing.bounded_release_base_damage = release_base_damage;
            ongoing.bounded_release_projected_damage =
                release_projected_damage;
            ongoing.bounded_release_damage_output_scale =
                release_damage_output_scale;
            ongoing.bounded_release_damage_scale =
                release_damage_scale;
            ongoing.bounded_release_damage_floor =
                release_damage_floor;
            ongoing.bounded_release_damage_cap_scale =
                release_damage_cap_scale;
            ongoing.bounded_release_projected_release_damage =
                release_projected_release_damage;
            ongoing.bounded_release_projected_hp_damage =
                release_projected_hp_damage;
            ongoing.bounded_release_target_hp = earth_damage_projection.target_hp;
            ongoing.bounded_release_target_actor = earth_damage_projection.target_actor;
            ongoing.bounded_post_release_ticks_waiting = 0;
        } else if (bounded_held_native_cast && ongoing.bounded_release_requested) {
            ongoing.bounded_post_release_ticks_waiting += 1;
        }
        const bool bounded_held_native_released =
            bounded_held_native_cast &&
            ongoing.bounded_release_requested &&
            ongoing.saw_live_handle &&
            ongoing.saw_activity &&
            ongoing.bounded_post_release_ticks_waiting >=
                kBoundedHeldPostReleaseWorldUpdateTicks &&
            !has_live_handle;
        // ProcessPendingBotCast runs after the stock tick. After the held
        // release edge, keep the lifecycle alive for several passes so stock
        // sees input released and can drive the native Boulder impact path.
        const bool bounded_held_release_tick_processed =
            bounded_held_native_cast &&
            ongoing.bounded_release_requested &&
            !bounded_release_just_requested &&
            ongoing.saw_live_handle &&
            ongoing.saw_activity &&
            ongoing.bounded_post_release_ticks_waiting >=
                kBoundedHeldPostReleaseWorldUpdateTicks;
        if (bounded_held_native_cast &&
            ongoing.bounded_release_requested &&
            !bounded_release_just_requested &&
            active_spell_state.object != 0) {
            (void)HoldBotBoulderAtReleaseCharge(
                memory,
                active_spell_state,
                ongoing.bounded_release_charge,
                false);
        }
        const bool startup_timeout_hit =
            ongoing.startup_in_progress &&
            ongoing.startup_ticks_waiting >=
                ResolveMaxStartupTicksWaiting(ongoing);
        const bool activity_released =
            !bounded_held_native_cast &&
            ongoing.saw_activity &&
            !has_live_handle &&
            drive_state == 0 &&
            no_interrupt == 0 &&
            actor_e4 == 0 &&
            actor_e8 == 0;
        const bool targetless_aim_point_primary =
            ongoing.have_aim_target &&
            binding->facing_target_actor_address == 0 &&
            ongoing.target_actor_address == 0 &&
            !OngoingCastTracksLiveTargetDuringNativeTick(ongoing) &&
            !OngoingCastRequiresBoundedHeldCastInputDuringNativeTick(ongoing);
        const bool held_target_missing =
            held_native_cast &&
            ongoing.saw_activity &&
            !target_refreshed &&
            !targetless_aim_point_primary &&
            binding->facing_target_actor_address == 0 &&
            ongoing.target_actor_address == 0;
        if (held_native_cast && target_refreshed &&
            binding->facing_target_actor_address != 0 &&
            ongoing.target_actor_address != 0) {
            ongoing.targetless_ticks_waiting = 0;
        } else if (held_target_missing) {
            ongoing.targetless_ticks_waiting += 1;
        }
        // Remote-player casts are driven by the sender's input stream. A
        // targetless held cast such as lightning must stay alive until release
        // or input timeout instead of being cleaned up by the bot retarget
        // watchdog.
        const bool target_lost =
            !remote_input_driven_cast &&
            held_target_missing &&
            ongoing.targetless_ticks_waiting >=
                ParticipantEntityBinding::OngoingCastState::kTargetlessRetargetGraceTicks;
        // A live target does not prove a pure-primary handler is still making
        // progress. Keep the final cap generic, but do not cut off an observable
        // bounded native object that is still charging toward its live release
        // condition.
        const bool bounded_native_charge_observable =
            bounded_held_native_cast &&
            active_spell_state.readable &&
            !ongoing.bounded_release_requested;
        const bool bounded_release_window_pending =
            bounded_held_native_cast &&
            ongoing.bounded_release_requested &&
            ongoing.bounded_post_release_ticks_waiting <
                kBoundedHeldPostReleaseWorldUpdateTicks;
        const bool remote_pure_primary_no_handle_visibility_pending =
            remote_input_driven_cast &&
            ongoing.lane == ParticipantEntityBinding::OngoingCastState::Lane::PurePrimary &&
            !has_live_handle &&
            ongoing.ticks_waiting <
                kRemotePurePrimaryNoHandleMinimumVisibleTicks;
        const bool remote_input_release_settled =
            remote_input_release_or_timeout &&
            ongoing.saw_activity &&
            !bounded_held_native_cast &&
            !remote_per_cast_pure_primary_without_live_handle &&
            !remote_pure_primary_no_handle_visibility_pending &&
            ongoing.remote_input_release_ticks_waiting >= 2;
        const bool remote_input_active_without_release =
            remote_input_driven_cast &&
            !remote_input_release_or_timeout;
        const bool safety_cap_hit =
            !remote_input_active_without_release &&
            !bounded_native_charge_observable &&
            !bounded_release_window_pending &&
            ongoing.ticks_waiting >=
                ParticipantEntityBinding::OngoingCastState::kMaxTicksWaiting;
        const bool bounded_held_release_requested_safety_cap =
            bounded_held_native_cast &&
            ongoing.bounded_release_requested &&
            safety_cap_hit;

        if (mana_stop_requested) {
            FinishBotCastNativeLifecycle(cast_context, ongoing, mana_stop_label, true);
            ongoing = ParticipantEntityBinding::OngoingCastState{};
            return true;
        }

        if (bounded_release_just_requested) {
            ongoing.startup_in_progress = false;
            const float finalized_release_charge =
                std::isfinite(ongoing.bounded_release_charge) &&
                        ongoing.bounded_release_charge > 0.0f
                    ? ongoing.bounded_release_charge
                    : active_spell_state.charge;
            const auto release_hold_writes =
                HoldBotBoulderAtReleaseCharge(
                    memory,
                    active_spell_state,
                    finalized_release_charge,
                    true);
            (void)memory.TryWriteField<std::int32_t>(actor_address, kActorPrimarySkillIdOffset, 0);
            (void)memory.TryWriteField<std::int32_t>(
                actor_address,
                kActorPreviousSkillIdOffset,
                native_active_skill_id);
            const std::string release_reason =
                ongoing.bounded_release_at_max_size
                    ? std::string("max_size")
                    : ongoing.bounded_release_target_lethal
                        ? std::string("target_lethal")
                        : std::string("native");
            Log(
                std::string("[bots] native boulder release requested. bot_id=") +
                std::to_string(binding->bot_id) +
                " skill_id=" + std::to_string(ongoing.skill_id) +
                " release_reason=" + release_reason +
                " ticks=" + std::to_string(ongoing.ticks_waiting) +
                " group=" + HexString(active_spell_state.group) +
                " slot=" + HexString(active_spell_state.slot) +
                " handle_source=" +
                    (active_spell_state.handle_from_selection_state ? std::string("selection") : std::string("actor")) +
                " selection_state=" + HexString(active_spell_state.selection_state) +
                " native_lookup=" + (active_spell_state.lookup_attempted ? std::string("1") : std::string("0")) +
                " native_lookup_ok=" + (active_spell_state.lookup_succeeded ? std::string("1") : std::string("0")) +
                " native_lookup_seh=" + HexString(active_spell_state.lookup_exception) +
                " obj_ptr=" + HexString(active_spell_state.object) +
                " obj_type=" + HexString(active_spell_state.object_type) +
                " obj_x=" + std::to_string(active_spell_state.object_x) +
                " obj_y=" + std::to_string(active_spell_state.object_y) +
                " obj_heading=" + std::to_string(active_spell_state.object_heading) +
                " obj_radius=" + std::to_string(active_spell_state.object_radius) +
                " obj_charge=" + std::to_string(active_spell_state.charge) +
                " obj_growth_rate=" + std::to_string(active_spell_state.growth_rate) +
                " obj_release_charge=" + std::to_string(active_spell_state.release_charge) +
                " obj_release_damage=" + std::to_string(active_spell_state.release_damage) +
                " obj_release_base_damage=" + std::to_string(active_spell_state.release_base_damage) +
                " obj_max_charge=" + std::to_string(active_spell_state.max_charge) +
                " obj_phase=" + HexString(active_spell_state.phase) +
                " obj_release_timer=" + HexString(active_spell_state.release_timer) +
                " max_charge=" + std::to_string(earth_max_charge) +
                " min_release_charge=" + std::to_string(earth_min_release_charge) +
                " min_release_ready=" +
                    (earth_native_min_release_charge_reached ? std::string("1") : std::string("0")) +
                " progression_level=" + std::to_string(earth_damage_projection.progression_level) +
                " base_damage=" + std::to_string(earth_damage_projection.base_damage) +
                " damage_output_scale=" +
                    std::to_string(earth_damage_projection.damage_output_scale) +
                " release_damage_scale=" +
                    std::to_string(earth_damage_projection.release_damage_scale) +
                " release_damage_floor=" +
                    std::to_string(earth_damage_projection.release_damage_floor) +
                " release_damage_cap_scale=" +
                    std::to_string(earth_damage_projection.release_damage_cap_scale) +
                " projected_damage=" +
                    std::to_string(earth_damage_projection.projected_damage) +
                " projected_release_damage=" +
                    std::to_string(earth_damage_projection.projected_release_damage) +
                " projected_hp_damage=" +
                    std::to_string(earth_damage_projection.projected_hp_damage) +
                " binding_face_target=" + HexString(binding->facing_target_actor_address) +
                " ongoing_target=" + HexString(ongoing.target_actor_address) +
                " requested_target_actor=" +
                    HexString(earth_damage_projection.requested_target_actor) +
                " requested_target_health=" +
                    HexString(earth_damage_projection.requested_target_health_base) +
                " requested_target_health_kind=" +
                    earth_damage_projection.requested_target_health_kind +
                " requested_target_health_readable=" +
                    (earth_damage_projection.requested_target_health_readable ? std::string("1") : std::string("0")) +
                " requested_target_hp=" +
                    std::to_string(earth_damage_projection.requested_target_hp) +
                " requested_target_max_hp=" +
                    std::to_string(earth_damage_projection.requested_target_max_hp) +
                " target_actor=" + HexString(earth_damage_projection.target_actor) +
                " target_health=" + HexString(earth_damage_projection.target_health_base) +
                " target_health_kind=" + earth_damage_projection.target_health_kind +
                " target_hp=" + std::to_string(earth_damage_projection.target_hp) +
                " target_max_hp=" + std::to_string(earth_damage_projection.target_max_hp) +
                " target_x=" + std::to_string(earth_damage_projection.target_x) +
                " target_y=" + std::to_string(earth_damage_projection.target_y) +
                " target_radius=" + std::to_string(earth_damage_projection.target_radius) +
                " target_distance=" + std::to_string(earth_damage_projection.target_distance) +
                " target_impact_radius=" +
                    std::to_string(earth_damage_projection.target_impact_radius) +
                " target_in_impact=" +
                    (earth_damage_projection.target_in_impact ? std::string("1") : std::string("0")) +
                " projection_target_in_impact=" +
                    (earth_damage_projection.native_radius_damage_eligible ? std::string("1") : std::string("0")) +
                " release_charge_write=" +
                    (release_hold_writes.release_charge ? std::string("1") : std::string("0")) +
                " release_charge_hold=" +
                    (release_hold_writes.charge ? std::string("1") : std::string("0")) +
                " release_damage_hold=" +
                    (release_hold_writes.release_damage ? std::string("1") : std::string("0")) +
                " release_base_damage_hold=" +
                    (release_hold_writes.release_base_damage ? std::string("1") : std::string("0")) +
                " release_scaled_base_damage=" +
                    std::to_string(release_hold_writes.scaled_release_base_damage) +
                " release_damage_output_scale_hold=" +
                    std::to_string(release_hold_writes.damage_output_scale) +
                " release_growth_stop=" +
                    (release_hold_writes.growth_rate ? std::string("1") : std::string("0")) +
                " release_growth_stop_eligible=" +
                    (release_hold_writes.growth_stop_eligible ? std::string("1") : std::string("0")) +
                " release_growth_stop_min_charge=" +
                    std::to_string(release_hold_writes.growth_stop_min_charge));
            return true;
        }

        if (pure_primary_no_handle_settled || startup_timeout_hit || activity_released ||
            remote_input_release_settled ||
            bounded_held_native_released || bounded_held_release_tick_processed ||
            bounded_held_release_requested_safety_cap || target_lost || safety_cap_hit) {
            const char* exit_label = "safety_cap";
            if (startup_timeout_hit) {
                exit_label = "startup_timeout";
            } else if (pure_primary_no_handle_settled) {
                exit_label = "pure_primary_no_handle_settled";
            } else if (remote_input_release_settled) {
                exit_label = ongoing.remote_input_timed_out
                    ? "remote_input_timeout"
                    : "remote_input_released";
            } else if (bounded_held_native_released || bounded_held_release_tick_processed ||
                       bounded_held_release_requested_safety_cap) {
                exit_label = ongoing.bounded_release_target_lethal
                    ? "target_lethal_released"
                    : "max_size_released";
            } else if (activity_released) {
                exit_label = "activity_released";
            } else if (target_lost) {
                exit_label = "target_lost";
            }
            if (startup_timeout_hit) {
                LogBotSpellObjectDiag(cast_context, active_cast_group);
            }
            const bool completed_bounded_release =
                bounded_held_native_released || bounded_held_release_tick_processed ||
                bounded_held_release_requested_safety_cap;
            FinishBotCastNativeLifecycle(cast_context, ongoing, exit_label, target_lost);
            (void)completed_bounded_release;
            ongoing = ParticipantEntityBinding::OngoingCastState{};
        }
        return true;
    }

    if (actor_dead) {
        multiplayer::BotCastRequest discarded_request{};
        while (multiplayer::ConsumePendingBotCast(binding->bot_id, &discarded_request)) {
            discarded_request = multiplayer::BotCastRequest{};
        }
        float heading = 0.0f;
        const bool heading_readable =
            TryReadFiniteFloatField(actor_address, kActorHeadingOffset, &heading);
        (void)multiplayer::FinishBotAttack(
            binding->bot_id,
            heading_readable,
            heading,
            true);
        return false;
    }

    if (IsGameplaySlotWizardKind(binding->kind)) {
        return false;
    }

    return StartPendingBotCastRequest(cast_context, dispatcher_address, error_message);
}
