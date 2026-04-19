void __fastcall HookMonsterPathfindingRefreshTarget(void* self, void* /*unused_edx*/) {
    const auto original = GetX86HookTrampoline<MonsterPathfindingRefreshTargetFn>(
        g_gameplay_keyboard_injection.monster_pathfinding_refresh_target_hook);
    if (original == nullptr) {
        return;
    }

    original(self, nullptr);

    const auto hostile_actor_address = reinterpret_cast<uintptr_t>(self);
    if (hostile_actor_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t gameplay_address = 0;
    if (!TryResolveCurrentGameplayScene(&gameplay_address) || gameplay_address == 0) {
        return;
    }

    const auto hostile_world_address =
        memory.ReadFieldOr<uintptr_t>(hostile_actor_address, kActorOwnerOffset, 0);
    if (hostile_world_address == 0) {
        return;
    }

    const auto hostile_actor_slot =
        static_cast<std::int32_t>(memory.ReadFieldOr<std::int8_t>(
            hostile_actor_address,
            kActorSlotOffset,
            static_cast<std::int8_t>(-1)));
    if (hostile_actor_slot < 0) {
        return;
    }

    const auto compute_distance_to = [&](uintptr_t candidate_actor_address, float* distance) -> bool {
        if (distance == nullptr || candidate_actor_address == 0 || candidate_actor_address == hostile_actor_address) {
            return false;
        }
        if (memory.ReadFieldOr<uintptr_t>(candidate_actor_address, kActorOwnerOffset, 0) != hostile_world_address) {
            return false;
        }
        if (memory.ReadFieldOr<std::uint8_t>(candidate_actor_address, kActorAnimationDriveStateByteOffset, 0) != 0) {
            return false;
        }

        const auto delta_x =
            memory.ReadFieldOr<float>(hostile_actor_address, kActorPositionXOffset, 0.0f) -
            memory.ReadFieldOr<float>(candidate_actor_address, kActorPositionXOffset, 0.0f);
        const auto delta_y =
            memory.ReadFieldOr<float>(hostile_actor_address, kActorPositionYOffset, 0.0f) -
            memory.ReadFieldOr<float>(candidate_actor_address, kActorPositionYOffset, 0.0f);
        *distance = std::sqrt((delta_x * delta_x) + (delta_y * delta_y));
        return true;
    };

    auto best_distance = (std::numeric_limits<float>::max)();
    uintptr_t best_actor_address = 0;
    const auto current_target_actor_address =
        memory.ReadFieldOr<uintptr_t>(hostile_actor_address, kHostileCurrentTargetActorOffset, 0);
    (void)compute_distance_to(current_target_actor_address, &best_distance);

    for (int slot_index = kFirstWizardBotSlot;
         slot_index < static_cast<int>(kGameplayPlayerSlotCount);
         ++slot_index) {
        uintptr_t candidate_actor_address = 0;
        if (!TryResolvePlayerActorForSlot(gameplay_address, slot_index, &candidate_actor_address) ||
            candidate_actor_address == 0) {
            continue;
        }

        if (memory.ReadFieldOr<std::int8_t>(candidate_actor_address, kActorSlotOffset, -1) != slot_index) {
            continue;
        }

        auto candidate_distance = 0.0f;
        if (!compute_distance_to(candidate_actor_address, &candidate_distance)) {
            continue;
        }

        if (candidate_distance < best_distance) {
            best_distance = candidate_distance;
            best_actor_address = candidate_actor_address;
        }
    }

    if (best_actor_address == 0) {
        return;
    }

    const auto best_world_slot =
        static_cast<std::int32_t>(memory.ReadFieldOr<std::int16_t>(
            best_actor_address,
            kActorWorldSlotOffset,
            static_cast<std::int16_t>(-1)));
    if (best_world_slot < 0) {
        return;
    }

    const auto current_target_world_slot =
        current_target_actor_address != 0
            ? static_cast<std::int32_t>(memory.ReadFieldOr<std::int16_t>(
                  current_target_actor_address,
                  kActorWorldSlotOffset,
                  static_cast<std::int16_t>(-1)))
            : -1;
    const auto current_target_slot =
        current_target_actor_address != 0
            ? static_cast<std::int32_t>(memory.ReadFieldOr<std::int8_t>(
                  current_target_actor_address,
                  kActorSlotOffset,
                  static_cast<std::int8_t>(-1)))
            : -1;
    const auto best_actor_slot =
        static_cast<std::int32_t>(memory.ReadFieldOr<std::int8_t>(
            best_actor_address,
            kActorSlotOffset,
            static_cast<std::int8_t>(-1)));
    if (best_actor_slot < 0) {
        return;
    }

    const auto best_bucket_delta =
        best_actor_slot * kActorWorldBucketStride + best_world_slot -
        hostile_actor_slot * kActorWorldBucketStride;
    if (best_bucket_delta < 0) {
        return;
    }

    (void)memory.TryWriteField(hostile_actor_address, kHostileCurrentTargetActorOffset, best_actor_address);
    (void)memory.TryWriteField(hostile_actor_address, kHostileTargetBucketDeltaOffset, best_bucket_delta);

    if (best_actor_address != current_target_actor_address) {
        static std::uint64_t s_last_selector_promotion_log_ms = 0;
        const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
        if (now_ms - s_last_selector_promotion_log_ms >= 250) {
            s_last_selector_promotion_log_ms = now_ms;
            Log(
                "[hostile_ai] selector promoted gameplay-slot participant. hostile=" +
                HexString(hostile_actor_address) +
                " stock_target=" + HexString(current_target_actor_address) +
                " stock_slot=" + std::to_string(current_target_slot) +
                " stock_world_slot=" + std::to_string(current_target_world_slot) +
                " promoted_target=" + HexString(best_actor_address) +
                " promoted_slot=" + std::to_string(best_actor_slot) +
                " promoted_world_slot=" + std::to_string(best_world_slot) +
                " promoted_bucket_delta=" + std::to_string(best_bucket_delta));
        }
    }
}

void __fastcall HookPlayerActorVtable28(void* self, void* /*unused_edx*/) {
    const auto original =
        GetX86HookTrampoline<PlayerActorNoArgMethodFn>(g_gameplay_keyboard_injection.player_actor_vtable28_hook);
    if (original == nullptr) {
        return;
    }

    const auto actor_address = reinterpret_cast<uintptr_t>(self);
    const auto previous_depth = g_player_actor_vslot28_depth;
    const auto previous_actor = g_player_actor_vslot28_actor;
    const auto previous_caller = g_player_actor_vslot28_caller;
    ++g_player_actor_vslot28_depth;
    g_player_actor_vslot28_actor = actor_address;
    g_player_actor_vslot28_caller = reinterpret_cast<uintptr_t>(_ReturnAddress());
    {
        static std::uint64_t s_last_overlay_callback_log_ms = 0;
        static std::uint64_t s_last_nonlocal_overlay_callback_log_ms = 0;
        const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
        const auto slot =
            ProcessMemory::Instance().ReadFieldOr<std::int8_t>(
                actor_address,
                kActorSlotOffset,
                static_cast<std::int8_t>(-1));
        if (slot > 0) {
            if (now_ms - s_last_nonlocal_overlay_callback_log_ms >= 1000) {
                s_last_nonlocal_overlay_callback_log_ms = now_ms;
                Log(
                    "[bots] nonlocal slot overlay callback. actor=" + HexString(actor_address) +
                    " slot=" + std::to_string(static_cast<int>(slot)) +
                    " hud_case100_depth=" + std::to_string(g_gameplay_hud_case100_depth));
            }
        } else if (slot == 0 && now_ms - s_last_overlay_callback_log_ms >= 1000) {
            s_last_overlay_callback_log_ms = now_ms;
            Log(
                "[bots] slot overlay callback. actor=" + HexString(actor_address) +
                " slot=0 hud_case100_depth=" + std::to_string(g_gameplay_hud_case100_depth));
        }
    }

    original(self);
    g_player_actor_vslot28_depth = previous_depth;
    g_player_actor_vslot28_actor = previous_actor;
    g_player_actor_vslot28_caller = previous_caller;
}

void __fastcall HookGameplayHudRenderDispatch(void* self, void* /*unused_edx*/, int render_case) {
    const auto original = GetX86HookTrampoline<GameplayHudRenderDispatchFn>(
        g_gameplay_keyboard_injection.gameplay_hud_render_dispatch_hook);
    if (original == nullptr) {
        return;
    }

    if (render_case != 100) {
        original(self, render_case);
        return;
    }

    const auto previous_depth = g_gameplay_hud_case100_depth;
    const auto previous_owner = g_gameplay_hud_case100_owner;
    const auto previous_caller = g_gameplay_hud_case100_caller;
    ++g_gameplay_hud_case100_depth;
    g_gameplay_hud_case100_owner = reinterpret_cast<uintptr_t>(self);
    g_gameplay_hud_case100_caller = reinterpret_cast<uintptr_t>(_ReturnAddress());
    original(self, render_case);
    g_gameplay_hud_case100_depth = previous_depth;
    g_gameplay_hud_case100_owner = previous_owner;
    g_gameplay_hud_case100_caller = previous_caller;
}

void __fastcall HookActorAnimationAdvance(void* self, void* /*unused_edx*/) {
    const auto original =
        GetX86HookTrampoline<ActorAnimationAdvanceFn>(g_gameplay_keyboard_injection.actor_animation_advance_hook);
    if (original == nullptr) {
        return;
    }

    const auto actor_address = reinterpret_cast<uintptr_t>(self);
    if (TryCaptureTrackedStandaloneWizardBindingIdentity(actor_address, nullptr, nullptr)) {
        NormalizeGameplaySlotBotSyntheticVisualState(actor_address);
    }
    original(self);
}

// The loader-owned standalone puppet bot is not registered in the world
// movement controller's primary collider list, so the stock tick never applies
// collision response to it. Replicate a simple circle-vs-circle push here:
// after `pusher_actor_address` ticks, compare its radius-inflated position
// against each tracked standalone puppet and nudge the puppet along the
// separating axis until the radii no longer overlap.
void ApplyStandalonePuppetCollisionPushFromActor(uintptr_t pusher_actor_address) {
    if (pusher_actor_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    const auto pusher_x =
        memory.ReadFieldOr<float>(pusher_actor_address, kActorPositionXOffset, 0.0f);
    const auto pusher_y =
        memory.ReadFieldOr<float>(pusher_actor_address, kActorPositionYOffset, 0.0f);
    const auto pusher_radius =
        memory.ReadFieldOr<float>(pusher_actor_address, kActorCollisionRadiusOffset, 0.0f);
    if (!std::isfinite(pusher_x) || !std::isfinite(pusher_y) ||
        !std::isfinite(pusher_radius) || pusher_radius <= 0.0f) {
        return;
    }
    const auto pusher_world =
        memory.ReadFieldOr<uintptr_t>(pusher_actor_address, kActorOwnerOffset, 0);

    std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
    for (auto& binding : g_participant_entities) {
        if (binding.actor_address == 0 ||
            binding.actor_address == pusher_actor_address) {
            continue;
        }
        if (!IsStandaloneWizardKind(binding.kind)) {
            continue;
        }
        const auto bot_world =
            memory.ReadFieldOr<uintptr_t>(binding.actor_address, kActorOwnerOffset, 0);
        if (pusher_world != 0 && bot_world != 0 && pusher_world != bot_world) {
            continue;
        }
        const auto bot_x =
            memory.ReadFieldOr<float>(binding.actor_address, kActorPositionXOffset, 0.0f);
        const auto bot_y =
            memory.ReadFieldOr<float>(binding.actor_address, kActorPositionYOffset, 0.0f);
        const auto bot_radius =
            memory.ReadFieldOr<float>(binding.actor_address, kActorCollisionRadiusOffset, 0.0f);
        if (!std::isfinite(bot_x) || !std::isfinite(bot_y) ||
            !std::isfinite(bot_radius) || bot_radius <= 0.0f) {
            continue;
        }
        const auto dx = bot_x - pusher_x;
        const auto dy = bot_y - pusher_y;
        const auto min_sep = pusher_radius + bot_radius;
        const auto dist2 = dx * dx + dy * dy;
        if (dist2 >= min_sep * min_sep) {
            continue;
        }
        const auto dist = std::sqrt(dist2);
        float direction_x = 1.0f;
        float direction_y = 0.0f;
        if (dist > 0.0001f) {
            direction_x = dx / dist;
            direction_y = dy / dist;
        }
        const auto pushed_x = pusher_x + direction_x * min_sep;
        const auto pushed_y = pusher_y + direction_y * min_sep;
        (void)memory.TryWriteField(binding.actor_address, kActorPositionXOffset, pushed_x);
        (void)memory.TryWriteField(binding.actor_address, kActorPositionYOffset, pushed_y);

        static std::uint64_t s_last_puppet_push_log_ms = 0;
        const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
        if (now_ms - s_last_puppet_push_log_ms >= 1000) {
            s_last_puppet_push_log_ms = now_ms;
            Log(
                "[bots] pushed standalone puppet. bot_id=" + std::to_string(binding.bot_id) +
                " actor=" + HexString(binding.actor_address) +
                " pusher=" + HexString(pusher_actor_address) +
                " before=(" + std::to_string(bot_x) + "," + std::to_string(bot_y) + ")" +
                " after=(" + std::to_string(pushed_x) + "," + std::to_string(pushed_y) + ")" +
                " overlap=" + std::to_string(min_sep - dist));
        }
    }
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
        const auto previous_allow = g_allow_gameplay_action_pump_in_gameplay;
        g_allow_gameplay_action_pump_in_gameplay = true;
        PumpQueuedGameplayActions();
        g_allow_gameplay_action_pump_in_gameplay = previous_allow;
    }

    bool standalone_puppet_actor = false;
    bool gameplay_slot_wizard_actor = false;
    bool tracked_actor_moving = false;
    bool tracked_actor_should_restore_desired_heading = false;
    float tracked_actor_desired_heading = 0.0f;
    uintptr_t tracked_actor_world = 0;
    std::string tracked_path_error_message;
    std::string tracked_move_error_message;
    const auto native_tick_now_ms = static_cast<std::uint64_t>(GetTickCount64());
    {
        std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
        if (auto* binding = FindParticipantEntityForActor(actor_address);
            binding != nullptr && IsWizardParticipantKind(binding->kind)) {
            SyncWizardBotMovementIntent(binding);
            if (!UpdateWizardBotPathMotion(binding, native_tick_now_ms, &tracked_path_error_message) &&
                !tracked_path_error_message.empty()) {
                Log(
                    "[bots] native tick path update failed. bot_id=" + std::to_string(binding->bot_id) +
                    " actor=" + HexString(actor_address) +
                    " error=" + tracked_path_error_message);
                tracked_path_error_message.clear();
            }
            standalone_puppet_actor = IsStandaloneWizardKind(binding->kind);
            gameplay_slot_wizard_actor = IsGameplaySlotWizardKind(binding->kind);
            tracked_actor_moving = binding->movement_active;
            tracked_actor_should_restore_desired_heading =
                binding->movement_active &&
                binding->desired_heading_valid &&
                binding->controller_state != multiplayer::BotControllerState::Attacking;
            tracked_actor_desired_heading = binding->desired_heading;
            tracked_actor_world = ProcessMemory::Instance().ReadFieldOr<uintptr_t>(
                actor_address,
                kActorOwnerOffset,
                binding->materialized_world_address);
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
        }
    }

    auto& memory = ProcessMemory::Instance();
    if (standalone_puppet_actor) {
        static std::uint64_t s_last_native_bot_tick_log_ms = 0;
        if (native_tick_now_ms - s_last_native_bot_tick_log_ms >= 1000) {
            s_last_native_bot_tick_log_ms = native_tick_now_ms;
            Log(
                "[bots] native bot tick. actor=" + HexString(actor_address) +
                " moving=" + std::to_string(tracked_actor_moving ? 1 : 0) +
                " desired_heading=" + std::to_string(tracked_actor_desired_heading));
        }
        const auto position_before_x =
            memory.ReadFieldOr<float>(actor_address, kActorPositionXOffset, 0.0f);
        const auto position_before_y =
            memory.ReadFieldOr<float>(actor_address, kActorPositionYOffset, 0.0f);
        const auto heading_before =
            memory.ReadFieldOr<float>(actor_address, kActorHeadingOffset, 0.0f);

        (void)EnsureStandaloneWizardWorldOwner(
            actor_address,
            tracked_actor_world,
            "player_tick",
            nullptr);
        {
            std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
            if (const auto* binding = FindParticipantEntityForActor(actor_address);
                binding != nullptr && IsStandaloneWizardKind(binding->kind)) {
                ApplyStandaloneWizardAnimationDriveProfile(
                    binding,
                    actor_address,
                    tracked_actor_moving);
                ApplyStandaloneWizardPuppetDriveState(
                    binding,
                    actor_address,
                    tracked_actor_moving);
            }
        }
        original(self);

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

        // Stock tick code can rewrite the standalone puppet transform as an
        // animation side effect. When the bot is following a commanded path we
        // want deterministic motion, so snap back to the pre-tick position and
        // let our own movement step drive the next delta. When the bot is idle
        // we preserve the stock write so collision responses from other actors
        // (pushes) remain visible.
        if (tracked_actor_moving) {
            (void)memory.TryWriteField(actor_address, kActorPositionXOffset, position_before_x);
            (void)memory.TryWriteField(actor_address, kActorPositionYOffset, position_before_y);
        }

        std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
        if (auto* binding = FindParticipantEntityForActor(actor_address);
            binding != nullptr && IsStandaloneWizardKind(binding->kind)) {
            if (!ApplyWizardBotMovementStep(binding, &tracked_move_error_message) &&
                !tracked_move_error_message.empty()) {
                Log(
                    "[bots] native tick movement step failed. bot_id=" + std::to_string(binding->bot_id) +
                    " actor=" + HexString(actor_address) +
                    " error=" + tracked_move_error_message);
                tracked_move_error_message.clear();
            }
            (void)memory.TryWriteField(
                actor_address,
                kActorHeadingOffset,
                tracked_actor_should_restore_desired_heading ? tracked_actor_desired_heading : heading_before);
            ApplyObservedBotAnimationState(binding, actor_address, binding->movement_active);
            PublishParticipantGameplaySnapshot(*binding);
        }
        NormalizeGameplaySlotBotSyntheticVisualState(actor_address);
        ApplyStandalonePuppetCollisionPushFromActor(actor_address);
        return;
    }

    if (gameplay_slot_wizard_actor) {
        original(self);

        {
            std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
            if (auto* binding = FindParticipantEntityForActor(actor_address);
                binding != nullptr && IsGameplaySlotWizardKind(binding->kind)) {
                if (binding->movement_active) {
                    if (!ApplyWizardBotMovementStep(binding, &tracked_move_error_message) &&
                        !tracked_move_error_message.empty()) {
                        Log(
                            "[bots] gameplay-slot movement step failed. bot_id=" + std::to_string(binding->bot_id) +
                            " actor=" + HexString(actor_address) +
                            " error=" + tracked_move_error_message);
                        tracked_move_error_message.clear();
                    }
                    if (tracked_actor_should_restore_desired_heading) {
                        (void)memory.TryWriteField(
                            actor_address,
                            kActorHeadingOffset,
                            tracked_actor_desired_heading);
                    }
                }
                PublishParticipantGameplaySnapshot(*binding);
            }
        }
        ApplyStandalonePuppetCollisionPushFromActor(actor_address);
        return;
    }

    original(self);
    ApplyStandalonePuppetCollisionPushFromActor(actor_address);
    if (memory.ReadFieldOr<std::int8_t>(actor_address, kActorSlotOffset, static_cast<std::int8_t>(-1)) == 0) {
        TickParticipantSceneBindingsIfActive();
    }
    LogLocalPlayerAnimationProbe();
}

std::uint8_t __fastcall HookGameplayKeyboardEdge(void* self, void* /*unused_edx*/, std::uint32_t scancode) {
    if (scancode < g_gameplay_keyboard_injection.pending_scancodes.size()) {
        auto& pending = g_gameplay_keyboard_injection.pending_scancodes[scancode];
        auto available = pending.load(std::memory_order_acquire);
        while (available > 0) {
            if (pending.compare_exchange_weak(
                    available,
                    available - 1,
                    std::memory_order_acq_rel,
                    std::memory_order_acquire)) {
                return 1;
            }
        }
    }

    const auto original =
        GetX86HookTrampoline<GameplayKeyboardEdgeFn>(g_gameplay_keyboard_injection.edge_hook);
    return original != nullptr ? original(self, scancode) : 0;
}
