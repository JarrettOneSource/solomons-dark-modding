bool PumpQueuedBotNativeActionManager(
    ParticipantEntityBinding* binding,
    uintptr_t actor_address,
    std::uint64_t now_ms) {
    if (binding == nullptr ||
        actor_address == 0 ||
        !binding->ongoing_cast.active) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto tick_address =
        memory.ResolveGameAddressOrZero(kPlayerActorActionManagerTick);
    if (tick_address == 0 ||
        kActorCastDiagnosticContextOffset == 0 ||
        kPointerListCountOffset == 0) {
        return false;
    }

    const auto action_manager_address =
        actor_address + kActorCastDiagnosticContextOffset;
    std::int32_t action_count_before = 0;
    if (!memory.TryReadValue(
            action_manager_address + kPointerListCountOffset,
            &action_count_before) ||
        action_count_before <= 0 ||
        action_count_before > 64) {
        return false;
    }

    uintptr_t first_action_wrapper = 0;
    uintptr_t first_action_object = 0;
    uintptr_t first_action_vtable = 0;
    uintptr_t action_items = 0;
    if (memory.TryReadValue(
            action_manager_address + kPointerListItemsOffset,
            &action_items) &&
        action_items != 0 &&
        memory.TryReadValue(action_items, &first_action_wrapper) &&
        first_action_wrapper != 0 &&
        memory.TryReadValue(first_action_wrapper, &first_action_object) &&
        first_action_object != 0) {
        (void)memory.TryReadValue(first_action_object, &first_action_vtable);
    }

    DWORD exception_code = 0;
    const bool pumped =
        CallPlayerActorActionManagerTickSafe(
            tick_address,
            action_manager_address,
            &exception_code);

    std::int32_t action_count_after = -1;
    (void)memory.TryReadValue(
        action_manager_address + kPointerListCountOffset,
        &action_count_after);

    static std::uint64_t s_last_action_pump_log_ms = 0;
    if (!pumped ||
        (kEnableWizardBotHotPathDiagnostics &&
         now_ms - s_last_action_pump_log_ms >= 500)) {
        s_last_action_pump_log_ms = now_ms;
        Log(
            "[bots] native action manager pump. bot_id=" +
            std::to_string(binding->bot_id) +
            " actor=" + HexString(actor_address) +
            " action_manager=" + HexString(action_manager_address) +
            " count_before=" + std::to_string(action_count_before) +
            " count_after=" + std::to_string(action_count_after) +
            " first_wrapper=" + HexString(first_action_wrapper) +
            " first_object=" + HexString(first_action_object) +
            " first_vtable=" + HexString(first_action_vtable) +
            " ok=" + (pumped ? std::string("1") : std::string("0")) +
            " seh=" + HexString(exception_code));
    }
    return pumped;
}

void RepairInvalidNativeMeditationTransientState(uintptr_t actor_address) {
    if (actor_address == 0 ||
        kActorProgressionRuntimeStateOffset == 0 ||
        kProgressionMeditationIdleTicksOffset == 0 ||
        kProgressionMeditationIdleElapsedTicksOffset == 0 ||
        kProgressionMeditationRecoveryRampTicksOffset == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t progression_address = 0;
    std::int32_t idle_ticks = -1;
    std::int32_t idle_elapsed_ticks = 0;
    std::int32_t recovery_ramp_ticks = 0;
    if (!memory.TryReadField(
            actor_address,
            kActorProgressionRuntimeStateOffset,
            &progression_address) ||
        progression_address == 0 ||
        !memory.TryReadField(
            progression_address,
            kProgressionMeditationIdleTicksOffset,
            &idle_ticks) ||
        !memory.TryReadField(
            progression_address,
            kProgressionMeditationIdleElapsedTicksOffset,
            &idle_elapsed_ticks) ||
        !memory.TryReadField(
            progression_address,
            kProgressionMeditationRecoveryRampTicksOffset,
            &recovery_ramp_ticks) ||
        idle_ticks < -1 ||
        idle_ticks > 1000000) {
        return;
    }

    const auto maximum_ramp_ticks = (std::max)(idle_ticks, 0);
    const bool repair_idle_elapsed = idle_elapsed_ticks < 0;
    const bool repair_recovery_ramp =
        idle_ticks == -1
            ? recovery_ramp_ticks < -1 || recovery_ramp_ticks > 0
            : recovery_ramp_ticks < 0 ||
                  recovery_ramp_ticks > maximum_ramp_ticks;
    if (!repair_idle_elapsed && !repair_recovery_ramp) {
        return;
    }

    bool repaired = true;
    if (repair_idle_elapsed) {
        repaired = memory.TryWriteField<std::int32_t>(
                       progression_address,
                       kProgressionMeditationIdleElapsedTicksOffset,
                       0) &&
                   repaired;
    }
    if (repair_recovery_ramp) {
        repaired = memory.TryWriteField<std::int32_t>(
                       progression_address,
                       kProgressionMeditationRecoveryRampTicksOffset,
                       0) &&
                   repaired;
    }
    Log(
        "[gameplay] Meditation transient state repair. actor=" +
        HexString(actor_address) +
        " progression=" + HexString(progression_address) +
        " idle_ticks=" + std::to_string(idle_ticks) +
        " idle_elapsed_before=" + std::to_string(idle_elapsed_ticks) +
        " ramp_before=" + std::to_string(recovery_ramp_ticks) +
        " ok=" + std::to_string(repaired ? 1 : 0));
}

void __fastcall HookPlayerActorTick(void* self, void* /*unused_edx*/) {
    const auto original =
        GetX86HookTrampoline<PlayerActorTickFn>(g_gameplay_keyboard_injection.player_actor_tick_hook);
    if (original == nullptr) {
        return;
    }

    const auto actor_address = reinterpret_cast<uintptr_t>(self);
    uintptr_t gameplay_address_for_pump = 0;
    uintptr_t local_actor_address = 0;
    if (TryResolveCurrentGameplayScene(&gameplay_address_for_pump) &&
        gameplay_address_for_pump != 0 &&
        TryResolvePlayerActorForSlot(gameplay_address_for_pump, 0, &local_actor_address) &&
        local_actor_address == actor_address) {
        PublishLocalPlayerTickOwnership(
            gameplay_address_for_pump,
            actor_address);
        MaybeArmLocalPlayerCastProbe(gameplay_address_for_pump, actor_address);
        const auto previous_allow = g_allow_gameplay_action_pump_in_gameplay;
        g_allow_gameplay_action_pump_in_gameplay = true;
        PumpQueuedGameplayActions();
        const SDModRuntimeTickContext lua_tick_context = {
            sizeof(SDModRuntimeTickContext),
            GetRuntimeTickServiceIntervalMs(),
            0,
            static_cast<std::uint64_t>(GetTickCount64()),
        };
        PumpLuaWorkOnGameplayThread(lua_tick_context);
        g_allow_gameplay_action_pump_in_gameplay = previous_allow;
    }

    const bool local_player_actor =
        gameplay_address_for_pump != 0 &&
        local_actor_address != 0 &&
        local_actor_address == actor_address;
    const auto native_tick_now_ms = static_cast<std::uint64_t>(GetTickCount64());

    if (local_player_actor) {
        (void)MaybeInitializeLocalPlayerNativePrimaryRuntime(
            gameplay_address_for_pump,
            actor_address,
            native_tick_now_ms);
    }

    RepairInvalidNativeMeditationTransientState(actor_address);

    if (multiplayer::ShouldPauseMultiplayerGameplay()) {
        static std::uint64_t s_last_shared_simulation_hold_log_ms = 0;
        const auto pause_now_ms = static_cast<std::uint64_t>(::GetTickCount64());
        if (pause_now_ms - s_last_shared_simulation_hold_log_ms >= 1000) {
            s_last_shared_simulation_hold_log_ms = pause_now_ms;
            std::string wait_text;
            (void)multiplayer::TryBuildLevelUpWaitStatusText(&wait_text);
            Log(
                "Shared simulation control suppressing actor tick. actor=" +
                HexString(actor_address) +
                " local_player=" + std::to_string(local_player_actor ? 1 : 0) +
                " status=\"" + wait_text + "\"");
        }
        if (local_player_actor) {
            TickParticipantSceneBindingsIfActive();
            ApplyReplicatedWorldSnapshotIfActive(
                gameplay_address_for_pump,
                pause_now_ms);
            ApplyReplicatedSpellEffectSnapshotsIfActive(pause_now_ms);
        }
        return;
    }

    bool standalone_puppet_actor = false;
    bool gameplay_slot_wizard_actor = false;
    bool tracked_actor_native_remote = false;
    bool tracked_actor_moving = false;
    bool tracked_actor_should_restore_desired_heading = false;
    float tracked_actor_desired_heading = 0.0f;
    uintptr_t tracked_actor_world = 0;
    int tracked_actor_slot = -1;
    uintptr_t tracked_actor_progression_runtime = 0;
    uintptr_t tracked_actor_equip_runtime = 0;
    uintptr_t tracked_actor_selection_state = 0;
    bool tracked_actor_runtime_invalid = false;
    bool tracked_actor_dead = false;
    std::string tracked_path_error_message;
    std::string tracked_move_error_message;
    {
        std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
        if (auto* binding = FindParticipantEntityForActor(actor_address);
            binding != nullptr && IsWizardParticipantKind(binding->kind)) {
            standalone_puppet_actor = IsStandaloneWizardKind(binding->kind);
            gameplay_slot_wizard_actor = IsGameplaySlotWizardKind(binding->kind);
            (void)RefreshNativeRemoteParticipantTransformTarget(binding, native_tick_now_ms);
            tracked_actor_native_remote = IsNativeRemoteParticipantBinding(binding);
            if (tracked_actor_native_remote) {
                (void)EnsureActorProgressionRuntimeFieldFromHandle(
                    actor_address,
                    "native_remote_pre_tick_progression_runtime");
                (void)ApplyNativeRemoteParticipantVitalState(binding, actor_address);
            }
            tracked_actor_dead = IsActorRuntimeDead(actor_address);
            if (tracked_actor_dead) {
                QuiesceDeadWizardBinding(binding);
                StopDeadWizardBotActorMotion(actor_address);
                (void)ClearHostileTargetsForDeadWizardActor(actor_address);
            } else {
                binding->death_transition_stock_tick_seen = false;
                if (!tracked_actor_native_remote) {
                    SyncWizardBotMovementIntent(binding);
                    if (!UpdateWizardBotPathMotion(binding, native_tick_now_ms, &tracked_path_error_message) &&
                        !tracked_path_error_message.empty()) {
                        Log(
                            "[bots] native tick path update failed. bot_id=" + std::to_string(binding->bot_id) +
                            " actor=" + HexString(actor_address) +
                            " error=" + tracked_path_error_message);
                        tracked_path_error_message.clear();
                    }
                }
            }
            tracked_actor_moving =
                tracked_actor_native_remote
                    ? NativeRemoteParticipantPlaybackTargetIsMoving(binding, actor_address)
                    : binding->movement_active;
            tracked_actor_should_restore_desired_heading =
                !tracked_actor_dead &&
                !tracked_actor_native_remote &&
                binding->movement_active &&
                binding->desired_heading_valid &&
                binding->controller_state != multiplayer::BotControllerState::Attacking;
            tracked_actor_desired_heading = binding->desired_heading;
            std::int8_t tracked_actor_slot_i8 = -1;
            auto& memory = ProcessMemory::Instance();
            if (!memory.TryReadField(actor_address, kActorSlotOffset, &tracked_actor_slot_i8) ||
                !memory.TryReadField(actor_address, kActorOwnerOffset, &tracked_actor_world) ||
                !memory.TryReadField(actor_address, kActorProgressionRuntimeStateOffset, &tracked_actor_progression_runtime) ||
                !memory.TryReadField(actor_address, kActorEquipRuntimeStateOffset, &tracked_actor_equip_runtime) ||
                !memory.TryReadField(actor_address, kActorAnimationSelectionStateOffset, &tracked_actor_selection_state)) {
                tracked_actor_runtime_invalid = true;
            }
            tracked_actor_slot = static_cast<int>(tracked_actor_slot_i8);
            if (binding->materialized_world_address != tracked_actor_world) {
                Log(
                    "[bots] tracked actor owner changed. bot_id=" + std::to_string(binding->bot_id) +
                    " actor=" + HexString(actor_address) +
                    " kind=" + std::to_string(static_cast<int>(binding->kind)) +
                    " old_world=" + HexString(binding->materialized_world_address) +
                    " new_world=" + HexString(tracked_actor_world));
            }
            if (tracked_actor_world != 0 &&
                binding->materialized_world_address != tracked_actor_world) {
                binding->materialized_world_address = tracked_actor_world;
            }
            tracked_actor_runtime_invalid =
                binding->materialized_world_address != 0 &&
                (tracked_actor_world == 0 ||
                 tracked_actor_slot < 0 ||
                 (tracked_actor_progression_runtime == 0 &&
                  tracked_actor_equip_runtime == 0 &&
                  tracked_actor_selection_state == 0));
        }
    }

    if ((standalone_puppet_actor || gameplay_slot_wizard_actor) && tracked_actor_runtime_invalid) {
        Log(
            "[bots] tracked actor invalidated out-of-band. actor=" + HexString(actor_address) +
            " kind=" + std::to_string(static_cast<int>(
                gameplay_slot_wizard_actor
                    ? ParticipantEntityBinding::Kind::GameplaySlotWizard
                    : ParticipantEntityBinding::Kind::StandaloneWizard)) +
            " live_owner=" + HexString(tracked_actor_world) +
            " live_slot=" + std::to_string(tracked_actor_slot) +
            " live_progression=" + HexString(tracked_actor_progression_runtime) +
            " live_equip=" + HexString(tracked_actor_equip_runtime) +
            " live_selection=" + HexString(tracked_actor_selection_state));
        MarkParticipantEntityWorldUnregistered(actor_address);
        return;
    }

    auto& memory = ProcessMemory::Instance();
    auto RunStockTick = [&](ParticipantEntityBinding* binding) {
        if (binding == nullptr) {
            original(self);
            return;
        }

        // A rejected request is consumed before this hook reaches the retail
        // tick. Letting that same tick continue can turn the already-authored
        // control-brain facing vector into a one-shot action at 0x0052DA80,
        // after Lua has canceled the attempt. Suppress exactly that tick; the
        // binding returns to the ordinary idle path on the next frame.
        if (binding->suppress_next_stock_tick_after_spell_filter_cancel) {
            binding->suppress_next_stock_tick_after_spell_filter_cancel = false;
            Log(
                "[lua] suppressed owner-side bot stock tick after canceled spell cast. "
                "participant_id=" + std::to_string(binding->bot_id) +
                " actor=" + HexString(actor_address));
            return;
        }

        // Clear stale loader movement input before every stock bot tick.
        // Clear the previous frame's vector before stock can use it.
        // active casts receive target/control input through selection state, and
        // loader-owned movement runs once after stock tick through the recovered
        // native MoveStep path. Leaving +0x158/+0x15C populated here lets stock
        // consume the previous frame's vector and then our movement step
        // consumes the new vector again.
        const bool native_remote_binding = IsNativeRemoteParticipantBinding(binding);
        const bool idle_native_remote_binding =
            native_remote_binding && !binding->ongoing_cast.active;
        const bool loader_owned_movement_vector_present =
            binding->movement_active || binding->last_movement_displacement > 0.0001f;
        const bool stock_tick_may_consume_stale_loader_vector =
            native_remote_binding || loader_owned_movement_vector_present;
        if (stock_tick_may_consume_stale_loader_vector) {
            ClearWizardBotMovementVectorInputs(actor_address);
        }
        if (idle_native_remote_binding) {
            ClearIdleNativeRemoteCastReplayState(actor_address);
        }
        if (binding->ongoing_cast.active && !native_remote_binding) {
            (void)StopOngoingBotCastForManaReserve(
                binding,
                "pre_bot_stock_tick_mana_reserve");
        }
        bool mana_reserve_active_for_stock_tick = false;
        if (!binding->ongoing_cast.active && !native_remote_binding) {
            mana_reserve_active_for_stock_tick =
                ApplyBotNativeManaReserveRecovery(
                    binding,
                    actor_address,
                    native_tick_now_ms);
        }
        if (mana_reserve_active_for_stock_tick) {
            (void)RepairGameplayPlayerProgressionSlotOwner(
                "skip_reserved_bot_stock_tick",
                actor_address);
            return;
        }

        uintptr_t gameplay_address = 0;
        std::uint8_t saved_cast_intent = 0;
        std::uint8_t saved_mouse_left = 0;
        std::size_t live_mouse_left_offset = 0;
        bool stock_cast_intent_applied = false;
        bool stock_mouse_left_applied = false;
        std::uint8_t saved_global_1abe_for_stock_tick = 0;
        bool global_1abe_zeroed_for_stock_tick = false;
        // Press the stock cast gate for startup, and keep it held for continuous
        // pure primaries whose damage hitbox only runs while input is down.
        // Aim is refreshed before stock tick, so held input does not freeze the
        // first target sample.
        const bool drive_stock_cast_input =
            binding->ongoing_cast.active &&
            OngoingCastShouldDriveSyntheticCastInput(binding->ongoing_cast);
        const bool pure_primary_needs_primary_gate_open =
            binding->ongoing_cast.active &&
            binding->ongoing_cast.lane == ParticipantEntityBinding::OngoingCastState::Lane::PurePrimary;
        const bool refresh_selection_target_for_stock_tick =
            binding->ongoing_cast.active &&
            OngoingCastShouldRefreshNativeTargetState(binding->ongoing_cast) &&
            binding->ongoing_cast.selection_target_seed_active;
        // Every PlayerActor tick reads the one gameplay-scene input buffer.
        // Mask that local input while ticking an idle remote participant so a
        // local press cannot start and immediately cancel the remote spell on
        // every frame. Active remote casts still receive their authored input.
        if ((drive_stock_cast_input || idle_native_remote_binding) &&
            TryResolveCurrentGameplayScene(&gameplay_address) &&
            gameplay_address != 0) {
            if (memory.TryReadField(
                    gameplay_address,
                    kGameplayCastIntentOffset,
                    &saved_cast_intent)) {
                stock_cast_intent_applied =
                    memory.TryWriteField<std::uint8_t>(
                        gameplay_address,
                        kGameplayCastIntentOffset,
                        static_cast<std::uint8_t>(drive_stock_cast_input ? 1 : 0));
                int input_buffer_index = -1;
                if (memory.TryReadField(
                        gameplay_address,
                        kGameplayInputBufferIndexOffset,
                        &input_buffer_index) &&
                    input_buffer_index >= 0) {
                    live_mouse_left_offset =
                        static_cast<std::size_t>(
                            input_buffer_index * kGameplayInputBufferStride +
                            kGameplayMouseLeftButtonOffset);
                    if (memory.TryReadField(
                            gameplay_address,
                            live_mouse_left_offset,
                        &saved_mouse_left)) {
                        stock_mouse_left_applied =
                            memory.TryWriteField<std::uint8_t>(
                                gameplay_address,
                                live_mouse_left_offset,
                                static_cast<std::uint8_t>(drive_stock_cast_input ? 1 : 0));
                    }
                }
            }
        }
        if (pure_primary_needs_primary_gate_open) {
            const auto global_1abe_address =
                memory.ResolveGameAddressOrZero(kGameObjectGlobal + kGameplayPrimaryGateBlockFlagOffset);
            (void)memory.TryReadValue(global_1abe_address, &saved_global_1abe_for_stock_tick);
            if (global_1abe_address != 0 && saved_global_1abe_for_stock_tick != 0) {
                global_1abe_zeroed_for_stock_tick =
                    memory.TryWriteValue<std::uint8_t>(
                        global_1abe_address,
                        0);
            }
        }
        if (refresh_selection_target_for_stock_tick) {
            RefreshSelectionBrainTargetForOngoingCast(binding->ongoing_cast);
        }
        if (binding->ongoing_cast.active &&
            binding->ongoing_cast.uses_dispatcher_skill_id &&
            OngoingCastShouldRefreshNativeTargetState(binding->ongoing_cast)) {
            ReapplyOngoingCastSelectionState(binding, actor_address, binding->ongoing_cast, true);
        }
        const bool bot_stock_tick_uses_actor_progression_cache =
            IsWizardParticipantKind(binding->kind);
        if (bot_stock_tick_uses_actor_progression_cache) {
            (void)EnsureActorProgressionRuntimeFieldFromHandle(
                actor_address,
                "pre_bot_stock_tick_progression_runtime");
        }
        uintptr_t remote_firewalker_profile = 0;
        std::uint8_t remote_firewalker_active = 0;
        const bool remote_firewalker_suppressed =
            native_remote_binding &&
            TryResolveWizardActorProfileAddress(
                actor_address,
                &remote_firewalker_profile) &&
            memory.TryReadField(
                remote_firewalker_profile,
                kWizardProfileFirewalkerActiveOffset,
                &remote_firewalker_active) &&
            remote_firewalker_active != 0 &&
            memory.TryWriteField<std::uint8_t>(
                remote_firewalker_profile,
                kWizardProfileFirewalkerActiveOffset,
                0);
        InvokeWithParticipantConcentrationContext(
            binding,
            [&] {
                original(self);
            });
        if (remote_firewalker_suppressed &&
            !memory.TryWriteField(
                remote_firewalker_profile,
                kWizardProfileFirewalkerActiveOffset,
                remote_firewalker_active)) {
            Log(
                "[bots] remote Firewalker stock-tick mask restore failed. actor=" +
                HexString(actor_address) +
                " profile=" + HexString(remote_firewalker_profile));
        }
        if (bot_stock_tick_uses_actor_progression_cache) {
            (void)EnsureActorProgressionRuntimeFieldFromHandle(
                actor_address,
                "post_bot_stock_tick_progression_runtime");
        }
        (void)PumpQueuedBotNativeActionManager(
            binding,
            actor_address,
            native_tick_now_ms);
        (void)RepairGameplayPlayerProgressionSlotOwner(
            "post_bot_stock_tick",
            actor_address);
        if (refresh_selection_target_for_stock_tick) {
            RefreshSelectionBrainTargetForOngoingCast(binding->ongoing_cast);
        }
        if (global_1abe_zeroed_for_stock_tick) {
            (void)memory.TryWriteValue<std::uint8_t>(
                memory.ResolveGameAddressOrZero(kGameObjectGlobal + kGameplayPrimaryGateBlockFlagOffset),
                saved_global_1abe_for_stock_tick);
        }
        if (stock_cast_intent_applied) {
            (void)memory.TryWriteField<std::uint8_t>(
                gameplay_address,
                kGameplayCastIntentOffset,
                saved_cast_intent);
        }
        if (stock_mouse_left_applied) {
            (void)memory.TryWriteField<std::uint8_t>(
                gameplay_address,
                live_mouse_left_offset,
                saved_mouse_left);
        }
        if (stock_cast_intent_applied) {
            static std::uint64_t s_last_stock_cast_input_log_ms = 0;
            if constexpr (kEnableWizardBotHotPathDiagnostics) {
                if (native_tick_now_ms - s_last_stock_cast_input_log_ms >= 250) {
                    s_last_stock_cast_input_log_ms = native_tick_now_ms;
                    Log(
                        "[bots] wizard stock cast input. actor=" +
                        HexString(actor_address) +
                        " gameplay=" + HexString(gameplay_address) +
                        " mouse_left=" + (stock_mouse_left_applied ? std::string("1") : std::string("0")) +
                        " kind=" +
                            (IsGameplaySlotWizardKind(binding->kind)
                                 ? std::string("gameplay_slot")
                                 : std::string("standalone")) +
                        " gameplay_slot=" + std::to_string(binding->gameplay_slot));
                }
            }
        }
    };

    if (standalone_puppet_actor) {
        static std::uint64_t s_last_native_bot_tick_log_ms = 0;
        if constexpr (kEnableWizardBotHotPathDiagnostics) {
            if (native_tick_now_ms - s_last_native_bot_tick_log_ms >= 1000) {
                s_last_native_bot_tick_log_ms = native_tick_now_ms;
                Log(
                    "[bots] native bot tick. actor=" + HexString(actor_address) +
                    " moving=" + std::to_string(tracked_actor_moving ? 1 : 0) +
                    " desired_heading=" + std::to_string(tracked_actor_desired_heading));
            }
        }
        float heading_before = 0.0f;
        const bool heading_before_readable =
            TryReadFiniteFloatField(actor_address, kActorHeadingOffset, &heading_before);

        if (tracked_actor_dead) {
            bool run_stock_death_transition = false;
            {
                std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
                if (auto* binding = FindParticipantEntityForActor(actor_address);
                    binding != nullptr && IsStandaloneWizardKind(binding->kind)) {
                    std::string cast_error_message;
                    QuiesceDeadWizardBinding(binding);
                    StopDeadWizardBotActorMotion(actor_address);
                    (void)ClearHostileTargetsForDeadWizardActor(actor_address);
                    (void)ProcessPendingBotCast(binding, &cast_error_message);
                    run_stock_death_transition = !binding->death_transition_stock_tick_seen;
                    binding->death_transition_stock_tick_seen = true;
                    PublishParticipantGameplaySnapshot(*binding);
                }
            }
            if (run_stock_death_transition) {
                original(self);
                StopDeadWizardBotActorMotion(actor_address);
                std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
                if (auto* binding = FindParticipantEntityForActor(actor_address);
                    binding != nullptr && IsStandaloneWizardKind(binding->kind)) {
                    PublishParticipantGameplaySnapshot(*binding);
                }
            }
            return;
        }

        (void)EnsureStandaloneWizardWorldOwner(
            actor_address,
            tracked_actor_world,
            "player_tick",
            nullptr);
        {
            std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
            if (auto* binding = FindParticipantEntityForActor(actor_address);
                binding != nullptr && IsStandaloneWizardKind(binding->kind)) {
                const bool native_remote = IsNativeRemoteParticipantBinding(binding);
                if (!native_remote) {
                    ApplyStandaloneWizardAnimationDriveProfile(
                        binding,
                        actor_address,
                        tracked_actor_moving);
                    ApplyStandaloneWizardPuppetDriveState(
                        binding,
                        actor_address,
                        tracked_actor_moving);
                }
                std::string cast_error_message;
                if (!binding->ongoing_cast.active) {
                    (void)PreparePendingWizardBotCast(binding, &cast_error_message);
                    if (!cast_error_message.empty()) {
                        Log(
                            "[bots] standalone cast prepare failed. bot_id=" +
                            std::to_string(binding->bot_id) +
                            " actor=" + HexString(actor_address) +
                            " remote=" + std::to_string(native_remote ? 1 : 0) +
                            " error=" + cast_error_message);
                        cast_error_message.clear();
                    }
                }
                if (!native_remote) {
                    if (!binding->ongoing_cast.active) {
                        ClearLiveWizardActorAnimationDriveState(actor_address);
                    } else {
                        if (OngoingCastShouldRefreshNativeTargetState(binding->ongoing_cast)) {
                            (void)RefreshOngoingCastAimFromFacingTarget(binding, &binding->ongoing_cast);
                        }
                    }
                    (void)RefreshWizardBindingTargetFacing(binding);
                    (void)ApplyWizardBindingFacingState(binding, actor_address);
                }
            }
        }
        {
            std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
            if (auto* binding = FindParticipantEntityForActor(actor_address);
                binding != nullptr && IsStandaloneWizardKind(binding->kind)) {
                RunStockTick(binding);
            } else {
                original(self);
            }
        }

        {
            std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
            if (auto* binding = FindParticipantEntityForActor(actor_address);
                binding != nullptr && IsStandaloneWizardKind(binding->kind)) {
                if (tracked_actor_dead) {
                    std::string cast_error_message;
                    QuiesceDeadWizardBinding(binding);
                    (void)ProcessPendingBotCast(binding, &cast_error_message);
                    PublishParticipantGameplaySnapshot(*binding);
                    return;
                }
                if (IsNativeRemoteParticipantBinding(binding)) {
                    std::string cast_error_message;
                    const auto playback =
                        ApplyNativeRemoteParticipantPlayback(binding, actor_address, native_tick_now_ms);
                    if (!playback.presentation_valid) {
                        if (playback.moving) {
                            ApplyObservedBotAnimationState(binding, actor_address, true);
                    } else {
                        StopWizardBotActorMotion(actor_address);
                    }
                }
                (void)ProcessPendingBotCast(binding, &cast_error_message);
                (void)ReconcileNativeRemoteParticipantPersistentStatuses(
                    binding,
                    native_tick_now_ms);
                (void)ReconcileNativeRemoteParticipantTransientStatuses(
                    binding,
                    native_tick_now_ms);
                if (playback.presentation_valid) {
                    (void)ApplyNativeRemoteParticipantPresentationState(binding, actor_address);
                }
                if (!cast_error_message.empty()) {
                        Log(
                            "[bots] native-remote standalone cast detail. bot_id=" +
                            std::to_string(binding->bot_id) +
                            " actor=" + HexString(actor_address) +
                            " error=" + cast_error_message);
                    }
                    PublishParticipantGameplaySnapshot(*binding);
                    NormalizeGameplaySlotBotSyntheticVisualState(actor_address);
                    ResolveWizardParticipantActorCollisions();
                    return;
                }
                if (!ApplyWizardBotMovementStep(binding, &tracked_move_error_message) &&
                    !tracked_move_error_message.empty()) {
                    Log(
                        "[bots] native tick movement step failed. bot_id=" + std::to_string(binding->bot_id) +
                        " actor=" + HexString(actor_address) +
                        " error=" + tracked_move_error_message);
                    tracked_move_error_message.clear();
                }
                // Movement step contributes to facing first. Cast (below) runs
                // after and overrides when both fire on the same tick, making
                // attack direction take priority over movement direction.
                if (tracked_actor_should_restore_desired_heading && !binding->facing_heading_valid) {
                    binding->facing_heading_value = tracked_actor_desired_heading;
                    binding->facing_heading_valid = true;
                }
                std::string cast_error_message;
                (void)ProcessPendingBotCast(binding, &cast_error_message);
                if (!cast_error_message.empty()) {
                    Log(
                        "[bots] standalone cast post-tick detail. bot_id=" +
                        std::to_string(binding->bot_id) +
                        " actor=" + HexString(actor_address) +
                        " error=" + cast_error_message);
                }
                (void)RefreshWizardBindingTargetFacing(binding);
                if (!ApplyWizardBindingFacingState(binding, actor_address) && heading_before_readable) {
                    ApplyWizardActorFacingState(actor_address, heading_before);
                }
                if (!binding->ongoing_cast.active) {
                    const bool moved_this_tick =
                        binding->movement_active && binding->last_movement_displacement > 0.0001f;
                    if (moved_this_tick) {
                        ApplyObservedBotAnimationState(binding, actor_address, true);
                    } else {
                        StopWizardBotActorMotion(actor_address);
                        (void)ApplyWizardBindingFacingState(binding, actor_address);
                    }
                }
                PublishParticipantGameplaySnapshot(*binding);
            }
        }
        NormalizeGameplaySlotBotSyntheticVisualState(actor_address);
        ResolveWizardParticipantActorCollisions();
        return;
    }

    if (gameplay_slot_wizard_actor) {
        float position_before_x = 0.0f;
        float position_before_y = 0.0f;
        if (!TryReadFiniteFloatField(actor_address, kActorPositionXOffset, &position_before_x) ||
            !TryReadFiniteFloatField(actor_address, kActorPositionYOffset, &position_before_y)) {
            original(self);
            return;
        }

        {
            std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
            if (auto* binding = FindParticipantEntityForActor(actor_address);
                binding != nullptr && IsGameplaySlotWizardKind(binding->kind)) {
                std::string cast_error_message;
                binding->stock_tick_facing_origin_valid = true;
                binding->stock_tick_facing_origin_x = position_before_x;
                binding->stock_tick_facing_origin_y = position_before_y;
                if (tracked_actor_dead) {
                    const bool run_stock_death_transition = !binding->death_transition_stock_tick_seen;
                    QuiesceDeadWizardBinding(binding);
                    StopDeadWizardBotActorMotion(actor_address);
                    (void)ClearHostileTargetsForDeadWizardActor(actor_address);
                    (void)ProcessPendingBotCast(binding, &cast_error_message);
                    binding->death_transition_stock_tick_seen = true;
                    if (run_stock_death_transition) {
                        RunStockTick(binding);
                        StopDeadWizardBotActorMotion(actor_address);
                    }
                    if (!cast_error_message.empty()) {
                        Log(
                            "[bots] gameplay-slot dead cast cleanup detail. bot_id=" +
                            std::to_string(binding->bot_id) +
                            " actor=" + HexString(actor_address) +
                            " error=" + cast_error_message);
                    }
                    PublishParticipantGameplaySnapshot(*binding);
                    return;
                }
                if (IsNativeRemoteParticipantBinding(binding)) {
                    std::string native_remote_cast_error;
                    const bool cast_active_before = binding->ongoing_cast.active;
                    bool prepared_cast = false;
                    if (!binding->ongoing_cast.active) {
                        prepared_cast = PreparePendingWizardBotCast(
                            binding,
                            &native_remote_cast_error);
                    } else if (OngoingCastShouldRefreshNativeTargetState(binding->ongoing_cast)) {
                        (void)RefreshOngoingCastAimFromFacingTarget(binding, &binding->ongoing_cast);
                    }
                    // Stock tick maintains native run overlay/nameplate child state;
                    // replicated playback below restores the authoritative transform.
                    RunStockTick(binding);
                    if (binding->ongoing_cast.active || prepared_cast || cast_active_before) {
                        (void)ProcessPendingBotCast(binding, &native_remote_cast_error);
                    }
                    (void)ReconcileNativeRemoteParticipantPersistentStatuses(
                        binding,
                        native_tick_now_ms);
                    (void)ReconcileNativeRemoteParticipantTransientStatuses(
                        binding,
                        native_tick_now_ms);
                    const auto playback =
                        ApplyNativeRemoteParticipantPlayback(binding, actor_address, native_tick_now_ms);
                    if (!playback.presentation_valid) {
                        if (playback.moving) {
                            ApplyObservedBotAnimationState(binding, actor_address, true);
                        } else {
                            StopWizardBotActorMotion(actor_address);
                        }
                    }
                    if (!native_remote_cast_error.empty()) {
                        Log(
                            "[bots] native-remote gameplay-slot cast detail. bot_id=" +
                            std::to_string(binding->bot_id) +
                            " actor=" + HexString(actor_address) +
                            " error=" + native_remote_cast_error);
                    }
                    PublishParticipantGameplaySnapshot(*binding);
                    ResolveWizardParticipantActorCollisions();
                    return;
                }
                if (!binding->ongoing_cast.active) {
                    (void)PreparePendingWizardBotCast(binding, &cast_error_message);
                    if (!cast_error_message.empty()) {
                        Log(
                            "[bots] gameplay-slot cast prepare failed. bot_id=" +
                            std::to_string(binding->bot_id) +
                            " actor=" + HexString(actor_address) +
                            " error=" + cast_error_message);
                        cast_error_message.clear();
                    }
                } else {
                    if (OngoingCastShouldRefreshNativeTargetState(binding->ongoing_cast)) {
                        (void)RefreshOngoingCastAimFromFacingTarget(binding, &binding->ongoing_cast);
                    }
                }
                if (!binding->ongoing_cast.active) {
                    ResetStandaloneWizardControlBrain(actor_address);
                }
                (void)RefreshWizardBindingTargetFacing(binding);
                (void)ApplyWizardBindingFacingState(binding, actor_address);
                RunStockTick(binding);
                if (!ApplyWizardBotMovementStep(binding, &tracked_move_error_message) &&
                    !tracked_move_error_message.empty()) {
                    Log(
                        "[bots] gameplay-slot movement step failed. bot_id=" + std::to_string(binding->bot_id) +
                        " actor=" + HexString(actor_address) +
                        " error=" + tracked_move_error_message);
                    tracked_move_error_message.clear();
                }
                binding->stock_tick_facing_origin_valid = true;
                if (!TryReadFiniteFloatField(actor_address, kActorPositionXOffset, &binding->stock_tick_facing_origin_x) ||
                    !TryReadFiniteFloatField(actor_address, kActorPositionYOffset, &binding->stock_tick_facing_origin_y)) {
                    binding->stock_tick_facing_origin_valid = false;
                }
                if (binding->movement_active &&
                    tracked_actor_should_restore_desired_heading &&
                    !binding->facing_heading_valid) {
                    binding->facing_heading_value = tracked_actor_desired_heading;
                    binding->facing_heading_valid = true;
                }
                (void)ProcessPendingBotCast(binding, &cast_error_message);
                if (!binding->ongoing_cast.active) {
                    ResetStandaloneWizardControlBrain(actor_address);
                }
                (void)RefreshWizardBindingTargetFacing(binding);
                if (!cast_error_message.empty()) {
                    Log(
                        "[bots] gameplay-slot cast post-tick detail. bot_id=" +
                        std::to_string(binding->bot_id) +
                        " actor=" + HexString(actor_address) +
                        " error=" + cast_error_message);
                }
                if (!binding->ongoing_cast.active) {
                    const bool moved_this_tick =
                        binding->movement_active && binding->last_movement_displacement > 0.0001f;
                    if (moved_this_tick) {
                        ApplyObservedBotAnimationState(binding, actor_address, true);
                    } else {
                        StopWizardBotActorMotion(actor_address);
                    }
                }
                (void)ApplyWizardBindingFacingState(binding, actor_address);
                PublishParticipantGameplaySnapshot(*binding);
            }
        }
        ResolveWizardParticipantActorCollisions();
        return;
    }

    if (local_player_actor) {
        MaybeLogLocalPlayerCastProbe(gameplay_address_for_pump, actor_address, false);
        ScopedLocalPlayerScriptedMovementInput scripted_movement_input(
            gameplay_address_for_pump);
        ScopedLocalPlayerRushMovementScale rush_movement_scale(actor_address);

        std::uint8_t saved_cast_intent = 0;
        std::uint8_t saved_mouse_left = 0;
        std::size_t live_mouse_left_offset = 0;
        const bool have_cast_intent =
            memory.TryReadField(
                gameplay_address_for_pump,
                kGameplayCastIntentOffset,
                &saved_cast_intent);
        int input_buffer_index = -1;
        bool have_mouse_left = false;
        if (memory.TryReadField(
                gameplay_address_for_pump,
                kGameplayInputBufferIndexOffset,
                &input_buffer_index) &&
            input_buffer_index >= 0 &&
            input_buffer_index < kGameplayInputBufferCount) {
            live_mouse_left_offset = static_cast<std::size_t>(
                input_buffer_index * kGameplayInputBufferStride +
                kGameplayMouseLeftButtonOffset);
            have_mouse_left =
                memory.TryReadField(
                    gameplay_address_for_pump,
                    live_mouse_left_offset,
                    &saved_mouse_left);
        }
        bool cast_intent_masked = false;
        bool mouse_left_masked = false;
        if (((have_cast_intent && saved_cast_intent != 0) ||
             (have_mouse_left && saved_mouse_left != 0)) &&
            HasLuaSpellCastFilterHandlers()) {
            std::int32_t skill_id = 0;
            if (TryResolveLocalPlayerPrimarySpellFilterSkillId(
                    actor_address,
                    &skill_id) &&
                !ApplyLocalPlayerPrimarySpellFilter(actor_address, skill_id)) {
                if (have_cast_intent) {
                    cast_intent_masked =
                        memory.TryWriteField<std::uint8_t>(
                            gameplay_address_for_pump,
                            kGameplayCastIntentOffset,
                            0);
                }
                if (have_mouse_left) {
                    mouse_left_masked =
                        memory.TryWriteField<std::uint8_t>(
                            gameplay_address_for_pump,
                            live_mouse_left_offset,
                            0);
                }
            }
        }
        original(self);
        if (cast_intent_masked) {
            (void)memory.TryWriteField<std::uint8_t>(
                gameplay_address_for_pump,
                kGameplayCastIntentOffset,
                saved_cast_intent);
        }
        if (mouse_left_masked) {
            (void)memory.TryWriteField<std::uint8_t>(
                gameplay_address_for_pump,
                live_mouse_left_offset,
                saved_mouse_left);
        }
    } else {
        original(self);
    }
    if (local_player_actor) {
        MaybeLogLocalPlayerCastProbe(gameplay_address_for_pump, actor_address, true);
        ResolveWizardParticipantActorCollisions();
        TickParticipantSceneBindingsIfActive();
        ApplyReplicatedWorldSnapshotIfActive(gameplay_address_for_pump, static_cast<std::uint64_t>(::GetTickCount64()));
        ApplyReplicatedSpellEffectSnapshotsIfActive(
            static_cast<std::uint64_t>(::GetTickCount64()));
    }
    LogLocalPlayerAnimationProbe();
}
