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
    // PlayerActorTick: stock clears actor+0x270 every frame before it ever
    // reaches FUN_00548A00. Re-pin the prepared fields here and, if stock never
    // preserved the skill id, perform a single post-stock startup dispatch
    // under the same slot-0 shim the native handler expects.
    if (binding->ongoing_cast.active) {
        auto& ongoing = binding->ongoing_cast;

        if (actor_dead) {
            ReleaseBotSpellHandle(cast_context, ongoing, "dead", true);
            ongoing = ParticipantEntityBinding::OngoingCastState{};
            return true;
        }

        if (ongoing.bounded_cleanup_completed) {
            const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
            if (ongoing.bounded_cleanup_clear_after_ms == 0 ||
                now_ms >= ongoing.bounded_cleanup_clear_after_ms) {
                ClearBotBoundedReleaseCastLatch(cast_context, ongoing, "post_cleanup_delay");
            }
            return true;
        }

        // Keep native target/aim fresh for startup and true held primaries.
        // Projectile-style primaries keep the target captured at startup so a
        // later nearest-enemy swap cannot redirect an already spawned cast.
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
        const bool publish_ongoing_skill_id =
            ongoing.uses_dispatcher_skill_id &&
            !(SkillRequiresBoundedHeldCastInputDuringNativeTick(native_active_skill_id) &&
              ongoing.bounded_release_requested);
        (void)memory.TryWriteField<std::int32_t>(
            actor_address,
            kActorPrimarySkillIdOffset,
            publish_ongoing_skill_id ? ongoing.dispatcher_skill_id : 0);
        if (refresh_ongoing_target_state) {
            RefreshSelectionBrainTargetForOngoingCast(ongoing);
        }

        if (IsGameplaySlotWizardKind(binding->kind) &&
            ongoing.startup_in_progress &&
            ongoing.uses_dispatcher_skill_id &&
            !ongoing.post_stock_dispatch_attempted) {
            if (ongoing.uses_dispatcher_skill_id) {
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
            InvokeBotCastWithLocalPlayerSlot(cast_context, [&] {
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
                " no_int_post=" + HexString(no_interrupt_after_dispatch));
            if (!startup_dispatched) {
                ReleaseBotSpellHandle(cast_context, ongoing, "dispatch_seh", true);
                ongoing = ParticipantEntityBinding::OngoingCastState{};
                return true;
            }
        }

        const auto drive_state =
            memory.ReadFieldOr<std::uint8_t>(actor_address, kActorAnimationDriveStateByteOffset, 0);
        const auto no_interrupt =
            memory.ReadFieldOr<std::uint8_t>(actor_address, kActorNoInterruptFlagOffset, 0);
        const auto actor_e4 =
            memory.ReadFieldOr<std::uint32_t>(actor_address, 0xE4, 0);
        const auto actor_e8 =
            memory.ReadFieldOr<std::uint32_t>(actor_address, 0xE8, 0);
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
        if (ongoing.mana_charge_kind == multiplayer::BotManaChargeKind::PerCast &&
            ongoing.progression_runtime_address != 0 &&
            ongoing.saw_activity &&
            ongoing.mana_cost > 0.0f &&
            ongoing.mana_spent_total <= 0.0f) {
            const auto mana_spend =
                TrySpendProgressionMana(ongoing.progression_runtime_address, ongoing.mana_cost, false);
            if (mana_spend.spent) {
                ongoing.mana_spent_total += mana_spend.actual;
                Log(
                    "[bots] mana spent. bot_id=" + std::to_string(binding->bot_id) +
                    " skill_id=" + std::to_string(ongoing.skill_id) +
                    " mode=per_cast statbook_level=" +
                        std::to_string(ongoing.mana_statbook_level) +
                    " cost=" + std::to_string(ongoing.mana_cost) +
                    " before=" + std::to_string(mana_spend.before) +
                    " after=" + std::to_string(mana_spend.after) +
                    " total=" + std::to_string(ongoing.mana_spent_total));
            } else {
                mana_depleted = true;
                Log(
                    "[bots] mana rejected. bot_id=" + std::to_string(binding->bot_id) +
                    " skill_id=" + std::to_string(ongoing.skill_id) +
                    " mode=per_cast cost=" + std::to_string(ongoing.mana_cost) +
                    " before=" + std::to_string(mana_spend.before) +
                    " readable=" + (mana_spend.readable ? std::string("1") : std::string("0")));
            }
        }
        if (ongoing.mana_charge_kind == multiplayer::BotManaChargeKind::PerSecond &&
            ongoing.progression_runtime_address != 0 &&
            ongoing.saw_activity &&
            !ongoing.bounded_release_requested &&
            ongoing.mana_cost > 0.0f) {
            const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
            if (ongoing.mana_last_charge_ms == 0) {
                ongoing.mana_last_charge_ms = now_ms;
            }
            const auto elapsed_ms =
                now_ms > ongoing.mana_last_charge_ms ? now_ms - ongoing.mana_last_charge_ms : 0;
            if (elapsed_ms > 0) {
                const float requested_mana =
                    ongoing.mana_cost * (static_cast<float>(elapsed_ms) / 1000.0f);
                const auto mana_spend =
                    TrySpendProgressionMana(ongoing.progression_runtime_address, requested_mana, true);
                ongoing.mana_last_charge_ms = now_ms;
                if (mana_spend.spent) {
                    ongoing.mana_spent_total += mana_spend.actual;
                    Log(
                        "[bots] mana spent. bot_id=" + std::to_string(binding->bot_id) +
                        " skill_id=" + std::to_string(ongoing.skill_id) +
                        " mode=per_second statbook_level=" +
                            std::to_string(ongoing.mana_statbook_level) +
                        " rate=" + std::to_string(ongoing.mana_cost) +
                        " cost=" + std::to_string(requested_mana) +
                        " before=" + std::to_string(mana_spend.before) +
                        " after=" + std::to_string(mana_spend.after) +
                        " total=" + std::to_string(ongoing.mana_spent_total));
                }
                if (!mana_spend.spent || mana_spend.actual + 0.001f < requested_mana) {
                    mana_depleted = true;
                    Log(
                        "[bots] mana depleted. bot_id=" + std::to_string(binding->bot_id) +
                        " skill_id=" + std::to_string(ongoing.skill_id) +
                        " mode=per_second requested=" + std::to_string(requested_mana) +
                        " actual=" + std::to_string(mana_spend.actual) +
                        " before=" + std::to_string(mana_spend.before) +
                        " after=" + std::to_string(mana_spend.after));
                }
            }
        }

        // Some native primary actions do not publish a live spell-object handle,
        // but their emission still runs through actor+0xE4/0xE8. Do not clear
        // that latch at the first short settle or the hit path can be cut off.
        constexpr int kPurePrimaryNoHandleSettleTicks = 160;
        const bool pure_primary_no_handle_settled =
            ongoing.lane == ParticipantEntityBinding::OngoingCastState::Lane::PurePrimary &&
            !ongoing.requires_local_slot_native_tick &&
            ongoing.saw_activity &&
            !has_live_handle &&
            ongoing.ticks_waiting >= kPurePrimaryNoHandleSettleTicks;
        const bool held_native_cast =
            SkillRequiresHeldCastInputDuringNativeTick(native_active_skill_id);
        const bool bounded_held_native_cast =
            SkillRequiresBoundedHeldCastInputDuringNativeTick(native_active_skill_id);
        const auto active_spell_snapshot = ReadBotActiveSpellObjectSnapshot(cast_context, false);
        const auto earth_max_charge =
            ongoing.progression_runtime_address != 0
                ? memory.ReadFieldOr<float>(ongoing.progression_runtime_address, 0x8AC, 1.0f)
                : 1.0f;
        const auto earth_damage_projection =
            bounded_held_native_cast
                ? ReadBotBoulderDamageProjectionSnapshot(cast_context, active_spell_snapshot)
                : BotBoulderDamageProjectionSnapshot{};
        const bool earth_object_charge_reached =
            bounded_held_native_cast &&
            active_spell_snapshot.readable &&
            std::isfinite(active_spell_snapshot.object_f74) &&
            std::isfinite(earth_max_charge) &&
            earth_max_charge > 0.0f &&
            active_spell_snapshot.object_f74 >= earth_max_charge - 0.001f;
        const bool earth_max_size_reached =
            bounded_held_native_cast &&
            active_spell_snapshot.readable &&
            (active_spell_snapshot.boulder_max_size_reached || earth_object_charge_reached);
        const bool earth_damage_threshold_reached =
            bounded_held_native_cast &&
            earth_damage_projection.readable &&
            earth_damage_projection.target_hp > 0.0f &&
            earth_damage_projection.projected_damage >= earth_damage_projection.target_hp;
        const bool bounded_held_release_ready =
            bounded_held_native_cast &&
            active_spell_snapshot.readable &&
            (earth_max_size_reached || earth_damage_threshold_reached);
        const bool bounded_release_just_requested =
            bounded_held_release_ready && !ongoing.bounded_release_requested;
        if (bounded_release_just_requested) {
            float release_charge = earth_damage_projection.charge;
            float release_base_damage = earth_damage_projection.base_damage;
            float release_statbook_damage = earth_damage_projection.statbook_damage;
            float release_projected_damage = earth_damage_projection.projected_damage;
            if ((!std::isfinite(release_charge) || release_charge <= 0.0f) &&
                active_spell_snapshot.readable &&
                std::isfinite(active_spell_snapshot.object_f74) &&
                active_spell_snapshot.object_f74 > 0.0f) {
                release_charge = active_spell_snapshot.object_f74;
            }
            if (!std::isfinite(release_base_damage) || release_base_damage <= 0.0f) {
                release_base_damage =
                    ResolveEarthBoulderBaseDamage(
                        binding,
                        ongoing.progression_runtime_address,
                        nullptr);
            }
            if (!std::isfinite(release_statbook_damage) || release_statbook_damage <= 0.0f) {
                release_statbook_damage = release_base_damage;
            }
            if (std::isfinite(release_base_damage) &&
                release_base_damage > 0.0f &&
                std::isfinite(release_charge) &&
                release_charge > 0.0f) {
                release_projected_damage = release_base_damage * release_charge * release_charge;
            }
            ongoing.bounded_release_requested = true;
            ongoing.bounded_max_size_reached = earth_max_size_reached;
            ongoing.bounded_release_at_max_size = earth_max_size_reached;
            ongoing.bounded_release_at_damage_threshold =
                earth_damage_threshold_reached && !earth_max_size_reached;
            ongoing.bounded_release_charge = release_charge;
            ongoing.bounded_release_base_damage = release_base_damage;
            ongoing.bounded_release_statbook_damage =
                release_statbook_damage;
            ongoing.bounded_release_projected_damage =
                release_projected_damage;
            ongoing.bounded_release_target_hp = earth_damage_projection.target_hp;
            ongoing.bounded_release_target_actor = earth_damage_projection.target_actor;
            ongoing.bounded_release_damage_native =
                earth_damage_projection.native_damage_scale_available;
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
        // The native Earth handler does not drop the active handle by itself.
        // Once release is requested, keep input released while the live boulder
        // gets a native world-object update window, then run the same cleanup
        // the player's skill transition would have invoked.
        constexpr int kBoundedHeldPostReleaseWorldUpdateTicks = 60;
        const bool bounded_held_release_tick_processed =
            bounded_held_native_cast &&
            ongoing.bounded_release_requested &&
            !bounded_release_just_requested &&
            ongoing.saw_live_handle &&
            ongoing.saw_activity &&
            ongoing.bounded_post_release_ticks_waiting >=
                kBoundedHeldPostReleaseWorldUpdateTicks;
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
            ReleaseBotSpellHandle(cast_context, ongoing, "mana_depleted", true);
            ongoing = ParticipantEntityBinding::OngoingCastState{};
            return true;
        }

        if (bounded_release_just_requested) {
            ongoing.startup_in_progress = false;
            const bool release_for_damage =
                ongoing.bounded_release_at_damage_threshold &&
                !ongoing.bounded_release_at_max_size;
            bool threshold_charge_write_ok = !release_for_damage;
            bool threshold_max_write_ok = !release_for_damage;
            bool release_charge_write_ok = false;
            const float finalized_release_charge =
                std::isfinite(ongoing.bounded_release_charge) &&
                        ongoing.bounded_release_charge > 0.0f
                    ? ongoing.bounded_release_charge
                    : active_spell_snapshot.object_f74;
            if (active_spell_snapshot.object != 0 &&
                std::isfinite(finalized_release_charge) &&
                finalized_release_charge > 0.0f) {
                // Stock cleanup's secondary release consumes object+0x1F0.
                // Keep it synchronized to the chosen release charge before the
                // native world-update window begins.
                release_charge_write_ok =
                    memory.TryWriteField<float>(
                        active_spell_snapshot.object,
                        0x1F0,
                        finalized_release_charge);
            }
            if (active_spell_snapshot.object != 0 &&
                std::isfinite(finalized_release_charge) &&
                finalized_release_charge > 0.0f) {
                if (release_for_damage) {
                    threshold_charge_write_ok = release_charge_write_ok;
                }
                // Finalize copies object+0x74 into object+0x1FC. Set 0x1FC
                // too so pre-finalize readers use the finalized damage size.
                threshold_max_write_ok =
                    memory.TryWriteField<float>(
                        active_spell_snapshot.object,
                        0x1FC,
                        finalized_release_charge);
            }
            Log(
                std::string("[bots] native ") +
                (release_for_damage ? "damage-threshold" : "max-size") +
                " reached; releasing held cast input for native launch. bot_id=" +
                std::to_string(binding->bot_id) +
                " skill_id=" + std::to_string(ongoing.skill_id) +
                " ticks=" + std::to_string(ongoing.ticks_waiting) +
                " group=" + HexString(active_spell_snapshot.group) +
                " slot=" + HexString(active_spell_snapshot.slot) +
                " handle_source=" +
                    (active_spell_snapshot.handle_from_selection_state ? std::string("selection") : std::string("actor")) +
                " selection_state=" + HexString(active_spell_snapshot.selection_state) +
                " obj_ptr=" + HexString(active_spell_snapshot.object) +
                " obj_type=" + HexString(active_spell_snapshot.object_type) +
                " obj_vt_6c=" + HexString(active_spell_snapshot.release_secondary_fn) +
                " obj_vt_70=" + HexString(active_spell_snapshot.release_finalize_fn) +
                " obj_74=" + std::to_string(active_spell_snapshot.object_f74) +
                " obj_1f0=" + std::to_string(active_spell_snapshot.object_f1f0) +
                " obj_1fc=" + std::to_string(active_spell_snapshot.object_f1fc) +
                " obj_22c=" + HexString(active_spell_snapshot.object_f22c) +
                " obj_230=" + HexString(active_spell_snapshot.object_f230) +
                " max_charge=" + std::to_string(earth_max_charge) +
                " statbook_level=" + std::to_string(earth_damage_projection.statbook_level) +
                " stat_source=" + HexString(earth_damage_projection.stat_source) +
                " stat_vt=" + HexString(earth_damage_projection.stat_vtable) +
                " damage_getter=" + HexString(earth_damage_projection.damage_getter) +
                " damage_getter_attempt=" +
                    (earth_damage_projection.damage_getter_attempted ? std::string("1") : std::string("0")) +
                " damage_getter_seh=" + HexString(earth_damage_projection.damage_getter_seh) +
                " damage_native=" +
                    (earth_damage_projection.native_damage_scale_available ? std::string("1") : std::string("0")) +
                " impact_context_write=" +
                    (earth_damage_projection.impact_context_write_ok ? std::string("1") : std::string("0")) +
                " impact_context_x=" +
                    std::to_string(earth_damage_projection.impact_context_x) +
                " impact_context_y=" +
                    std::to_string(earth_damage_projection.impact_context_y) +
                " impact_context_radius=" +
                    std::to_string(earth_damage_projection.impact_context_radius) +
                " base_damage=" + std::to_string(earth_damage_projection.base_damage) +
                " statbook_damage=" + std::to_string(earth_damage_projection.statbook_damage) +
                " projected_damage=" +
                    std::to_string(earth_damage_projection.projected_damage) +
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
                " target_damage_scale=" +
                    std::to_string(earth_damage_projection.target_damage_scale) +
                " target_in_impact=" +
                    (earth_damage_projection.target_in_impact ? std::string("1") : std::string("0")) +
                " native_cleanup_release=" + (release_for_damage ? std::string("1") : std::string("0")) +
                " threshold_charge_write=" +
                    (threshold_charge_write_ok ? std::string("1") : std::string("0")) +
                " threshold_max_write=" +
                    (threshold_max_write_ok ? std::string("1") : std::string("0")) +
                " release_charge_write=" +
                    (release_charge_write_ok ? std::string("1") : std::string("0")));
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
                exit_label = ongoing.bounded_release_at_damage_threshold &&
                                     !ongoing.bounded_release_at_max_size
                                 ? "damage_threshold_released"
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
            ReleaseBotSpellHandle(cast_context, ongoing, exit_label, target_lost);
            if (completed_bounded_release &&
                ongoing.bounded_release_requested &&
                ongoing.bounded_release_at_damage_threshold &&
                !ongoing.bounded_release_at_max_size) {
                ScheduleBotBoundedReleaseLatchClear(ongoing);
            } else {
                ongoing = ParticipantEntityBinding::OngoingCastState{};
            }
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
