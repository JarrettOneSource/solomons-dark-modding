struct BotBoulderReleaseHoldWrites {
    bool charge = false;
    bool release_charge = false;
    bool growth_rate = false;
    bool growth_stop_eligible = false;
    float growth_stop_min_charge = 0.0f;
};

BotBoulderReleaseHoldWrites HoldBotBoulderAtReleaseCharge(
    ProcessMemory& memory,
    const BotNativeActiveSpellObjectState& active_spell_state,
    float release_charge) {
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
    writes.growth_stop_min_charge =
        ResolveEarthBoulderReleaseGrowthStopMinCharge();
    writes.growth_stop_eligible =
        release_charge > writes.growth_stop_min_charge;
    if (writes.growth_stop_eligible) {
        writes.growth_rate =
            memory.TryWriteField<float>(
                active_spell_state.object,
                kSpellObjectGrowthRateOffset,
                0.0f);
    }
    return writes;
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
        const bool preserve_bounded_release_edge =
            ongoing.bounded_release_requested &&
            ongoing.bounded_post_release_ticks_waiting < kBoundedHeldNativeReleaseEdgeTicks;
        const bool publish_ongoing_skill_id =
            ongoing.uses_dispatcher_skill_id &&
            !(SkillRequiresBoundedHeldCastInputDuringNativeTick(native_active_skill_id) &&
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
                PrimeGameplaySlotPostGateDispatchState(actor_address, ongoing.dispatcher_skill_id);
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
                if (TryResolveCurrentGameplayScene(&startup_gameplay_address) &&
                    startup_gameplay_address != 0) {
                    saved_cast_intent = memory.ReadFieldOr<std::uint8_t>(
                        startup_gameplay_address,
                        kGameplayCastIntentOffset,
                        0);
                    startup_cast_intent_applied =
                        memory.TryWriteField<std::uint8_t>(
                            startup_gameplay_address,
                            kGameplayCastIntentOffset,
                            static_cast<std::uint8_t>(1));
                    const auto input_buffer_index =
                        memory.ReadFieldOr<int>(startup_gameplay_address, kGameplayInputBufferIndexOffset, -1);
                    if (input_buffer_index >= 0) {
                        live_mouse_left_offset =
                            static_cast<std::size_t>(
                                input_buffer_index * kGameplayInputBufferStride +
                                kGameplayMouseLeftButtonOffset);
                    } else {
                        live_mouse_left_offset = kGameplayMouseLeftButtonOffset;
                    }
                    saved_mouse_left = memory.ReadFieldOr<std::uint8_t>(
                        startup_gameplay_address,
                        live_mouse_left_offset,
                        0);
                    startup_mouse_left_applied =
                        memory.TryWriteField<std::uint8_t>(
                            startup_gameplay_address,
                            live_mouse_left_offset,
                            static_cast<std::uint8_t>(1));
                }
                InvokeBotCastWithNativeActorSlot(cast_context, [&] {
                    startup_dispatched = CallSpellCastDispatcherSafe(
                        dispatcher_address,
                        actor_address,
                        &startup_exception_code);
                });
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
                const auto drive_after_dispatch =
                    memory.ReadFieldOr<std::uint8_t>(actor_address, kActorAnimationDriveStateByteOffset, 0);
                const auto no_interrupt_after_dispatch =
                    memory.ReadFieldOr<std::uint8_t>(actor_address, kActorNoInterruptFlagOffset, 0);
                const auto active_group_after_dispatch =
                    memory.ReadFieldOr<std::uint8_t>(actor_address, kActorActiveCastGroupByteOffset, 0xFF);
                Log(
                    "[bots] gameplay-slot post-stock dispatch. bot_id=" +
                    std::to_string(binding->bot_id) +
                    " skill_id=" + std::to_string(ongoing.dispatcher_skill_id) +
                    " ok=" + (startup_dispatched ? std::string("1") : std::string("0")) +
                    " seh=" + HexString(startup_exception_code) +
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

        const auto drive_state =
            memory.ReadFieldOr<std::uint8_t>(actor_address, kActorAnimationDriveStateByteOffset, 0);
        const auto no_interrupt =
            memory.ReadFieldOr<std::uint8_t>(actor_address, kActorNoInterruptFlagOffset, 0);
        const auto actor_e4 =
            memory.ReadFieldOr<std::uint32_t>(actor_address, kActorPrimaryActionLatchE4Offset, 0);
        const auto actor_e8 =
            memory.ReadFieldOr<std::uint32_t>(actor_address, kActorPrimaryActionLatchE8Offset, 0);
        const auto active_cast_group =
            memory.ReadFieldOr<std::uint8_t>(actor_address, kActorActiveCastGroupByteOffset, 0);
        const bool has_live_handle = active_cast_group != kBotCastActorActiveCastGroupSentinel;
        const bool native_primary_action_active =
            OngoingCastNeedsNativeTargetActor(ongoing) &&
            (actor_e4 != 0 || actor_e8 != 0);

        ongoing.ticks_waiting += 1;
        if (ongoing.startup_in_progress) {
            ongoing.startup_ticks_waiting += 1;
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
        bool mana_depleted = false;
        if (ongoing.mana_charge_kind == multiplayer::BotManaChargeKind::PerSecond &&
            ongoing.progression_runtime_address != 0 &&
            ongoing.saw_activity &&
            !ongoing.bounded_release_requested &&
            ongoing.mana_cost > 0.0f) {
            float current_mp = 0.0f;
            float max_mp = 0.0f;
            constexpr float kNativeManaDepletedEpsilon = 0.001f;
            if (TryReadProgressionMana(ongoing.progression_runtime_address, &current_mp, &max_mp) &&
                current_mp <= kNativeManaDepletedEpsilon) {
                mana_depleted = true;
                Log(
                    "[bots] native mana depleted. bot_id=" + std::to_string(binding->bot_id) +
                    " skill_id=" + std::to_string(ongoing.skill_id) +
                    " mode=per_second progression_level=" +
                        std::to_string(ongoing.mana_progression_level) +
                    " mp=" + std::to_string(current_mp) +
                    " max_mp=" + std::to_string(max_mp));
            }
        }

        // Some native primary actions do not publish a live spell-object handle,
        // but their emission still runs through actor+0xE4/0xE8. Do not clear
        // that latch at the first short settle or the hit path can be cut off.
        constexpr int kPurePrimaryNoHandleSettleTicks = 160;
        const bool pure_primary_no_handle_settled =
            ongoing.lane == ParticipantEntityBinding::OngoingCastState::Lane::PurePrimary &&
            ongoing.saw_activity &&
            !has_live_handle &&
            ongoing.ticks_waiting >= kPurePrimaryNoHandleSettleTicks;
        const bool held_native_cast =
            SkillRequiresHeldCastInputDuringNativeTick(native_active_skill_id);
        const bool bounded_held_native_cast =
            SkillRequiresBoundedHeldCastInputDuringNativeTick(native_active_skill_id);
        const auto active_spell_state = ReadBotNativeActiveSpellObjectState(cast_context, false);
        const auto earth_max_charge =
            ongoing.progression_runtime_address != 0
                ? memory.ReadFieldOr<float>(
                      ongoing.progression_runtime_address,
                      kProgressionEarthChargeCapOffset,
                      1.0f)
                : 1.0f;
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
        const bool earth_target_lethal_release_ready =
            bounded_held_native_cast &&
            earth_damage_projection.readable &&
            earth_damage_projection.target_actor != 0 &&
            std::isfinite(earth_damage_projection.target_hp) &&
            earth_damage_projection.target_hp > 0.0f &&
            std::isfinite(earth_damage_projection.projected_hp_damage) &&
            earth_damage_projection.projected_hp_damage + 0.001f >= earth_damage_projection.target_hp;
        const bool bounded_held_release_ready =
            bounded_held_native_cast &&
            active_spell_state.readable &&
            (earth_max_size_reached || earth_target_lethal_release_ready);
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
                release_base_damage = active_spell_state.release_base_damage;
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
                !earth_max_size_reached && earth_target_lethal_release_ready;
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
            !has_live_handle;
        // Once release is requested, keep only a stock-sized native release
        // window. The Earth handler gets a few frames with the chosen charge
        // and stopped growth-rate field, then the fallback cleanup below
        // finalizes the active handle before the visual can continue toward
        // max size.
        constexpr int kBoundedHeldPostReleaseWorldUpdateTicks = kBoundedHeldNativeReleaseEdgeTicks;
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
                ongoing.bounded_release_charge);
        }
        const bool startup_timeout_hit =
            ongoing.startup_in_progress &&
            ongoing.startup_ticks_waiting >=
                ResolveMaxStartupTicksWaiting(native_active_skill_id);
        const bool activity_released =
            !bounded_held_native_cast &&
            ongoing.saw_activity &&
            !has_live_handle &&
            drive_state == 0 &&
            no_interrupt == 0 &&
            actor_e4 == 0 &&
            actor_e8 == 0;
        const bool gesture_window_complete =
            !held_native_cast &&
            !bounded_held_native_cast &&
            ongoing.saw_activity &&
            ongoing.ticks_waiting >= ResolveBotCastGestureTicks(native_active_skill_id);
        const bool held_target_missing =
            held_native_cast &&
            ongoing.saw_activity &&
            !target_refreshed &&
            binding->facing_target_actor_address == 0 &&
            ongoing.target_actor_address == 0;
        if (held_native_cast && target_refreshed &&
            binding->facing_target_actor_address != 0 &&
            ongoing.target_actor_address != 0) {
            ongoing.targetless_ticks_waiting = 0;
        } else if (held_target_missing) {
            ongoing.targetless_ticks_waiting += 1;
        }
        const bool target_lost =
            held_target_missing &&
            ongoing.targetless_ticks_waiting >=
                ParticipantEntityBinding::OngoingCastState::kTargetlessRetargetGraceTicks;
        // A live target does not prove a pure-primary handler is still making
        // progress. Ether can leave actor+0xE4/0xE8 asserted without publishing
        // a handle, so the safety cap must always be able to release the cast.
        const bool safety_cap_hit =
            ongoing.ticks_waiting >= ResolveBotCastSafetyCapTicks(native_active_skill_id);

        if (mana_depleted) {
            FinishBotCastNativeLifecycle(cast_context, ongoing, "mana_depleted", true);
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
                    finalized_release_charge);
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
                " release_growth_stop=" +
                    (release_hold_writes.growth_rate ? std::string("1") : std::string("0")) +
                " release_growth_stop_eligible=" +
                    (release_hold_writes.growth_stop_eligible ? std::string("1") : std::string("0")) +
                " release_growth_stop_min_charge=" +
                    std::to_string(release_hold_writes.growth_stop_min_charge));
            return true;
        }

        if (pure_primary_no_handle_settled || startup_timeout_hit || activity_released ||
            bounded_held_native_released || bounded_held_release_tick_processed ||
            gesture_window_complete || target_lost || safety_cap_hit) {
            const char* exit_label = "safety_cap";
            if (startup_timeout_hit) {
                exit_label = "startup_timeout";
            } else if (pure_primary_no_handle_settled) {
                exit_label = "pure_primary_no_handle_settled";
            } else if (bounded_held_native_released || bounded_held_release_tick_processed) {
                exit_label = ongoing.bounded_release_target_lethal
                    ? "target_lethal_released"
                    : "max_size_released";
            } else if (activity_released) {
                exit_label = "activity_released";
            } else if (gesture_window_complete) {
                exit_label = "gesture_window_complete";
            } else if (target_lost) {
                exit_label = "target_lost";
            }
            if (startup_timeout_hit) {
                LogBotSpellObjectDiag(cast_context, active_cast_group);
            }
            const bool completed_bounded_release =
                bounded_held_native_released || bounded_held_release_tick_processed;
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
        (void)multiplayer::FinishBotAttack(
            binding->bot_id,
            true,
            memory.ReadFieldOr<float>(actor_address, kActorHeadingOffset, 0.0f),
            true);
        return false;
    }

    if (IsGameplaySlotWizardKind(binding->kind)) {
        return false;
    }

    return StartPendingBotCastRequest(cast_context, dispatcher_address, error_message);
}
