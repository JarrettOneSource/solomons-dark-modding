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

    bool standalone_puppet_actor = false;
    bool gameplay_slot_wizard_actor = false;
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
    const auto native_tick_now_ms = static_cast<std::uint64_t>(GetTickCount64());
    {
        std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
        if (auto* binding = FindParticipantEntityForActor(actor_address);
            binding != nullptr && IsWizardParticipantKind(binding->kind)) {
            standalone_puppet_actor = IsStandaloneWizardKind(binding->kind);
            gameplay_slot_wizard_actor = IsGameplaySlotWizardKind(binding->kind);
            tracked_actor_dead = IsActorRuntimeDead(actor_address);
            if (tracked_actor_dead) {
                QuiesceDeadWizardBinding(binding);
                StopDeadWizardBotActorMotion(actor_address);
            } else {
                binding->death_transition_stock_tick_seen = false;
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
            tracked_actor_moving = binding->movement_active;
            tracked_actor_should_restore_desired_heading =
                !tracked_actor_dead &&
                binding->movement_active &&
                binding->desired_heading_valid &&
                binding->controller_state != multiplayer::BotControllerState::Attacking;
            tracked_actor_desired_heading = binding->desired_heading;
            tracked_actor_slot = static_cast<int>(ProcessMemory::Instance().ReadFieldOr<std::int8_t>(
                actor_address,
                kActorSlotOffset,
                static_cast<std::int8_t>(-1)));
            tracked_actor_world = ProcessMemory::Instance().ReadFieldOr<uintptr_t>(
                actor_address,
                kActorOwnerOffset,
                binding->materialized_world_address);
            tracked_actor_progression_runtime =
                ProcessMemory::Instance().ReadFieldOr<uintptr_t>(
                    actor_address,
                    kActorProgressionRuntimeStateOffset,
                    0);
            tracked_actor_equip_runtime =
                ProcessMemory::Instance().ReadFieldOr<uintptr_t>(
                    actor_address,
                    kActorEquipRuntimeStateOffset,
                    0);
            tracked_actor_selection_state =
                ProcessMemory::Instance().ReadFieldOr<uintptr_t>(
                    actor_address,
                    kActorAnimationSelectionStateOffset,
                    0);
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

        uintptr_t gameplay_address = 0;
        std::uint8_t saved_cast_intent = 0;
        std::uint8_t saved_mouse_left = 0;
        std::size_t live_mouse_left_offset = 0;
        bool synthetic_cast_intent_applied = false;
        bool synthetic_mouse_left_applied = false;
        LocalPlayerCastShimState stock_tick_shim_state;
        bool stock_tick_shim_active = false;
        std::uint8_t saved_global_1abe_for_stock_tick = 0;
        bool global_1abe_zeroed_for_stock_tick = false;
        PurePrimaryLocalActorWindowShim pure_primary_actor_window_shim{};
        // Press the stock cast gate for startup, and keep it held for continuous
        // pure primaries whose damage hitbox only runs while input is down.
        // Aim is refreshed before stock tick, so held input does not freeze the
        // first target sample.
        const bool drive_stock_cast_input =
            binding->ongoing_cast.active &&
            OngoingCastShouldDriveSyntheticCastInput(binding->ongoing_cast);
        const bool apply_local_slot_for_native_tick =
            binding->ongoing_cast.active &&
            (binding->ongoing_cast.startup_in_progress ||
             binding->ongoing_cast.requires_local_slot_native_tick);
        const bool pure_primary_stock_shim =
            apply_local_slot_for_native_tick &&
            binding->ongoing_cast.lane == ParticipantEntityBinding::OngoingCastState::Lane::PurePrimary;
        const bool refresh_selection_target_for_stock_tick =
            apply_local_slot_for_native_tick &&
            OngoingCastShouldRefreshNativeTargetState(binding->ongoing_cast) &&
            binding->ongoing_cast.selection_target_seed_active;
        if (drive_stock_cast_input &&
            TryResolveCurrentGameplayScene(&gameplay_address) &&
            gameplay_address != 0) {
            saved_cast_intent = memory.ReadFieldOr<std::uint8_t>(
                gameplay_address,
                kGameplayCastIntentOffset,
                0);
            synthetic_cast_intent_applied =
                memory.TryWriteField<std::uint8_t>(
                    gameplay_address,
                    kGameplayCastIntentOffset,
                    static_cast<std::uint8_t>(1));
            const auto input_buffer_index =
                memory.ReadFieldOr<int>(gameplay_address, kGameplayInputBufferIndexOffset, -1);
            if (input_buffer_index >= 0) {
                live_mouse_left_offset =
                    static_cast<std::size_t>(
                        input_buffer_index * kGameplayInputBufferStride +
                        kGameplayMouseLeftButtonOffset);
                saved_mouse_left = memory.ReadFieldOr<std::uint8_t>(
                    gameplay_address,
                    live_mouse_left_offset,
                    0);
                synthetic_mouse_left_applied =
                    memory.TryWriteField<std::uint8_t>(
                        gameplay_address,
                        live_mouse_left_offset,
                        static_cast<std::uint8_t>(1));
            } else {
                live_mouse_left_offset = kGameplayMouseLeftButtonOffset;
                saved_mouse_left = memory.ReadFieldOr<std::uint8_t>(
                    gameplay_address,
                    live_mouse_left_offset,
                    0);
                synthetic_mouse_left_applied =
                    memory.TryWriteField<std::uint8_t>(
                        gameplay_address,
                        live_mouse_left_offset,
                        static_cast<std::uint8_t>(1));
            }
        }
        if (apply_local_slot_for_native_tick) {
            stock_tick_shim_active = EnterLocalPlayerCastShim(binding, &stock_tick_shim_state);
            if (pure_primary_stock_shim) {
                const auto global_1abe_address =
                    memory.ResolveGameAddressOrZero(0x0081C264 + 0x1ABE);
                saved_global_1abe_for_stock_tick =
                    memory.ReadValueOr<std::uint8_t>(global_1abe_address, 0);
                if (global_1abe_address != 0 && saved_global_1abe_for_stock_tick != 0) {
                    global_1abe_zeroed_for_stock_tick =
                        memory.TryWriteValue<std::uint8_t>(
                            global_1abe_address,
                            0);
                }
                pure_primary_actor_window_shim =
                    EnterPurePrimaryLocalActorWindow(actor_address);
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
        original(self);
        LeavePurePrimaryLocalActorWindow(actor_address, pure_primary_actor_window_shim);
        if (refresh_selection_target_for_stock_tick) {
            RefreshSelectionBrainTargetForOngoingCast(binding->ongoing_cast);
        }
        if (global_1abe_zeroed_for_stock_tick) {
            (void)memory.TryWriteValue<std::uint8_t>(
                memory.ResolveGameAddressOrZero(0x0081C264 + 0x1ABE),
                saved_global_1abe_for_stock_tick);
        }
        if (stock_tick_shim_active) {
            LeaveLocalPlayerCastShim(stock_tick_shim_state);
        }

        if (synthetic_cast_intent_applied) {
            (void)memory.TryWriteField<std::uint8_t>(
                gameplay_address,
                kGameplayCastIntentOffset,
                saved_cast_intent);
        }
        if (synthetic_mouse_left_applied) {
            (void)memory.TryWriteField<std::uint8_t>(
                gameplay_address,
                live_mouse_left_offset,
                saved_mouse_left);
        }
        if (synthetic_cast_intent_applied) {
            static std::uint64_t s_last_synthetic_cast_intent_log_ms = 0;
            if (native_tick_now_ms - s_last_synthetic_cast_intent_log_ms >= 250) {
                s_last_synthetic_cast_intent_log_ms = native_tick_now_ms;
                Log(
                    "[bots] wizard synthetic cast intent. actor=" +
                    HexString(actor_address) +
                    " gameplay=" + HexString(gameplay_address) +
                    " mouse_left=" + (synthetic_mouse_left_applied ? std::string("1") : std::string("0")) +
                    " kind=" +
                        (IsGameplaySlotWizardKind(binding->kind)
                             ? std::string("gameplay_slot")
                             : std::string("standalone")) +
                    " gameplay_slot=" + std::to_string(binding->gameplay_slot));
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
        const auto position_before_x =
            memory.ReadFieldOr<float>(actor_address, kActorPositionXOffset, 0.0f);
        const auto position_before_y =
            memory.ReadFieldOr<float>(actor_address, kActorPositionYOffset, 0.0f);
        const auto heading_before =
            memory.ReadFieldOr<float>(actor_address, kActorHeadingOffset, 0.0f);

        if (tracked_actor_dead) {
            bool run_stock_death_transition = false;
            {
                std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
                if (auto* binding = FindParticipantEntityForActor(actor_address);
                    binding != nullptr && IsStandaloneWizardKind(binding->kind)) {
                    std::string cast_error_message;
                    QuiesceDeadWizardBinding(binding);
                    StopDeadWizardBotActorMotion(actor_address);
                    (void)ProcessPendingBotCast(binding, &cast_error_message);
                    run_stock_death_transition = !binding->death_transition_stock_tick_seen;
                    binding->death_transition_stock_tick_seen = true;
                    PublishParticipantGameplaySnapshot(*binding);
                }
            }
            if (run_stock_death_transition) {
                original(self);
                (void)memory.TryWriteField(actor_address, kActorPositionXOffset, position_before_x);
                (void)memory.TryWriteField(actor_address, kActorPositionYOffset, position_before_y);
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
                ApplyStandaloneWizardAnimationDriveProfile(
                    binding,
                    actor_address,
                    tracked_actor_moving);
                ApplyStandaloneWizardPuppetDriveState(
                    binding,
                    actor_address,
                    tracked_actor_moving);
                std::string cast_error_message;
                if (!binding->ongoing_cast.active) {
                    (void)PreparePendingWizardBotCast(binding, &cast_error_message);
                    if (!cast_error_message.empty()) {
                        Log(
                            "[bots] standalone cast prepare failed. bot_id=" +
                            std::to_string(binding->bot_id) +
                            " actor=" + HexString(actor_address) +
                            " error=" + cast_error_message);
                        cast_error_message.clear();
                    }
                }
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
        {
            std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
            if (auto* binding = FindParticipantEntityForActor(actor_address);
                binding != nullptr && IsStandaloneWizardKind(binding->kind)) {
                RunStockTick(binding);
            } else {
                original(self);
            }
        }

        const auto position_after_stock_x =
            memory.ReadFieldOr<float>(actor_address, kActorPositionXOffset, position_before_x);
        const auto position_after_stock_y =
            memory.ReadFieldOr<float>(actor_address, kActorPositionYOffset, position_before_y);
        const auto stock_delta_x = position_after_stock_x - position_before_x;
        const auto stock_delta_y = position_after_stock_y - position_before_y;
        const auto stock_displacement =
            std::sqrt((stock_delta_x * stock_delta_x) + (stock_delta_y * stock_delta_y));
        if (stock_displacement > 0.01f) {
            static std::uint64_t s_last_stock_position_drift_log_ms = 0;
            if (native_tick_now_ms - s_last_stock_position_drift_log_ms >= 1000) {
                s_last_stock_position_drift_log_ms = native_tick_now_ms;
                Log(
                    "[bots] standalone stock tick rewrote actor position. actor=" +
                    HexString(actor_address) +
                    " before=(" + std::to_string(position_before_x) + ", " +
                        std::to_string(position_before_y) + ")" +
                    " stock_after=(" + std::to_string(position_after_stock_x) + ", " +
                        std::to_string(position_after_stock_y) + ")" +
                    " moving=" + std::to_string(tracked_actor_moving ? 1 : 0));
            }
        }

        // Standalone clone-rail actor position is loader-owned. Live probes
        // showed stock PlayerActorTick continuing to move idle clones whenever
        // stale +0x158/+0x15C walk accumulators were left behind, which caused
        // the visible "sliding" regression. Always discard the stock tick's
        // position write here, then apply only loader-owned movement and
        // explicit collision-push logic below.
        (void)memory.TryWriteField(actor_address, kActorPositionXOffset, position_before_x);
        (void)memory.TryWriteField(actor_address, kActorPositionYOffset, position_before_y);

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
                if (!ApplyWizardBindingFacingState(binding, actor_address)) {
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
        ApplyStandalonePuppetCollisionPushFromActor(actor_address);
        TickBotOwnedSkillsWizard(actor_address);
        return;
    }

    if (gameplay_slot_wizard_actor) {
        const auto position_before_x =
            memory.ReadFieldOr<float>(actor_address, kActorPositionXOffset, 0.0f);
        const auto position_before_y =
            memory.ReadFieldOr<float>(actor_address, kActorPositionYOffset, 0.0f);
        auto position_after_stock_x = position_before_x;
        auto position_after_stock_y = position_before_y;

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
                    (void)ProcessPendingBotCast(binding, &cast_error_message);
                    binding->death_transition_stock_tick_seen = true;
                    if (run_stock_death_transition) {
                        RunStockTick(binding);
                        (void)memory.TryWriteField(actor_address, kActorPositionXOffset, position_before_x);
                        (void)memory.TryWriteField(actor_address, kActorPositionYOffset, position_before_y);
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
                position_after_stock_x =
                    memory.ReadFieldOr<float>(actor_address, kActorPositionXOffset, position_before_x);
                position_after_stock_y =
                    memory.ReadFieldOr<float>(actor_address, kActorPositionYOffset, position_before_y);
                // Gameplay-slot bots still run through the stock player-family
                // tick, but the loader owns their transform just like the
                // standalone clone rail. Restore pre-stock position before the
                // loader-owned path/move step reads actor coordinates.
                (void)memory.TryWriteField(actor_address, kActorPositionXOffset, position_before_x);
                (void)memory.TryWriteField(actor_address, kActorPositionYOffset, position_before_y);
                if (!ApplyWizardBotMovementStep(binding, &tracked_move_error_message) &&
                    !tracked_move_error_message.empty()) {
                    Log(
                        "[bots] gameplay-slot movement step failed. bot_id=" + std::to_string(binding->bot_id) +
                        " actor=" + HexString(actor_address) +
                        " error=" + tracked_move_error_message);
                    tracked_move_error_message.clear();
                }
                binding->stock_tick_facing_origin_valid = true;
                binding->stock_tick_facing_origin_x =
                    memory.ReadFieldOr<float>(actor_address, kActorPositionXOffset, position_before_x);
                binding->stock_tick_facing_origin_y =
                    memory.ReadFieldOr<float>(actor_address, kActorPositionYOffset, position_before_y);
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
                        ApplyActorAnimationDriveState(actor_address, true);
                    } else {
                        StopWizardBotActorMotion(actor_address);
                    }
                }
                (void)ApplyWizardBindingFacingState(binding, actor_address);
                PublishParticipantGameplaySnapshot(*binding);
            }
        }
        const auto stock_delta_x = position_after_stock_x - position_before_x;
        const auto stock_delta_y = position_after_stock_y - position_before_y;
        const auto stock_displacement =
            std::sqrt((stock_delta_x * stock_delta_x) + (stock_delta_y * stock_delta_y));
        if constexpr (kEnableWizardBotHotPathDiagnostics) {
            if (stock_displacement > 0.01f) {
                static std::uint64_t s_last_gameplay_slot_stock_position_drift_log_ms = 0;
                if (native_tick_now_ms - s_last_gameplay_slot_stock_position_drift_log_ms >= 1000) {
                    s_last_gameplay_slot_stock_position_drift_log_ms = native_tick_now_ms;
                    Log(
                        "[bots] gameplay-slot stock tick rewrote actor position. actor=" +
                        HexString(actor_address) +
                        " before=(" + std::to_string(position_before_x) + ", " +
                            std::to_string(position_before_y) + ")" +
                        " stock_after=(" + std::to_string(position_after_stock_x) + ", " +
                            std::to_string(position_after_stock_y) + ")" +
                        " moving=" + std::to_string(tracked_actor_moving ? 1 : 0));
                }
            }
        }
        ApplyStandalonePuppetCollisionPushFromActor(actor_address);
        TickBotOwnedSkillsWizard(actor_address);
        return;
    }

    if (local_player_actor) {
        MaybeLogLocalPlayerCastProbe(gameplay_address_for_pump, actor_address, false);
    }
    original(self);
    if (local_player_actor) {
        MaybeLogLocalPlayerCastProbe(gameplay_address_for_pump, actor_address, true);
    }
    ApplyStandalonePuppetCollisionPushFromActor(actor_address);
    if (memory.ReadFieldOr<std::int8_t>(actor_address, kActorSlotOffset, static_cast<std::int8_t>(-1)) == 0) {
        TickParticipantSceneBindingsIfActive();
    }
    LogLocalPlayerAnimationProbe();
}
