void ClearManualSpawnerSuppressedLocalPrimaryCastState(uintptr_t actor_address);
bool IsUsableLocalPlayerCastAimTarget(
    float position_x,
    float position_y,
    float aim_target_x,
    float aim_target_y);

bool IsManualSpawnerPrimaryCastControlGraceActive() {
    const auto grace_until =
        g_gameplay_keyboard_injection.manual_spawner_primary_cast_control_grace_until_ms.load(
            std::memory_order_acquire);
    return grace_until != 0 &&
           static_cast<std::uint64_t>(GetTickCount64()) <= grace_until;
}

bool IsManualSpawnerPrimaryTargetActor(uintptr_t actor_address) {
    if (actor_address == 0) {
        return false;
    }

    std::uint32_t object_type_id = 0;
    auto& memory = ProcessMemory::Instance();
    return memory.TryReadField(actor_address, kGameObjectTypeIdOffset, &object_type_id) &&
           IsArenaCombatActorTypeInternal(object_type_id);
}

bool ApplyManualSpawnerPrimaryTargetState(
    uintptr_t actor_address,
    uintptr_t selection_pointer,
    uintptr_t target_actor_address) {
    if (actor_address == 0 || selection_pointer == 0 ||
        !IsManualSpawnerPrimaryTargetActor(target_actor_address)) {
        return false;
    }

    std::uint8_t target_group = kTargetHandleGroupSentinel;
    std::uint16_t target_slot = kTargetHandleSlotSentinel;
    if (!TryResolveSameWorldTargetHandle(
            actor_address,
            target_actor_address,
            &target_group,
            &target_slot)) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    constexpr std::int32_t kManualSpawnerTargetHoldTicks = 60;
    return memory.TryWriteField<uintptr_t>(
               actor_address,
               kActorCurrentTargetActorOffset,
               target_actor_address) &&
           memory.TryWriteField<std::int32_t>(
               actor_address,
               kActorCurrentTargetBucketDeltaOffset,
               0) &&
           memory.TryWriteField<std::uint8_t>(
               actor_address,
               kActorSpellTargetGroupByteOffset,
               target_group) &&
           memory.TryWriteField<std::uint16_t>(
               actor_address,
               kActorSpellTargetSlotShortOffset,
               target_slot) &&
           memory.TryWriteField<std::uint8_t>(
               selection_pointer,
               kActorControlBrainTargetSlotOffset,
               target_group) &&
           memory.TryWriteField<std::uint16_t>(
               selection_pointer,
               kActorControlBrainTargetHandleOffset,
               target_slot) &&
           memory.TryWriteField<std::int32_t>(
               selection_pointer,
               kActorControlBrainRetargetTicksOffset,
               kManualSpawnerTargetHoldTicks) &&
           memory.TryWriteField<std::int32_t>(
               selection_pointer,
               kActorControlBrainTargetCooldownTicksOffset,
               0) &&
           memory.TryWriteField<std::int32_t>(
               selection_pointer,
               kActorControlBrainActionCooldownTicksOffset,
               0) &&
           memory.TryWriteField<std::int32_t>(
               selection_pointer,
               kActorControlBrainActionBurstTicksOffset,
               0);
}

bool IsPlayerActorPublishedInCurrentGameplaySlot(
    uintptr_t actor_address,
    uintptr_t* gameplay_address,
    int* actor_slot,
    uintptr_t* published_actor_address) {
    if (gameplay_address != nullptr) {
        *gameplay_address = 0;
    }
    if (actor_slot != nullptr) {
        *actor_slot = -1;
    }
    if (published_actor_address != nullptr) {
        *published_actor_address = 0;
    }
    if (actor_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    std::int8_t live_actor_slot = -1;
    if (!memory.TryReadField(actor_address, kActorSlotOffset, &live_actor_slot)) {
        return false;
    }
    if (actor_slot != nullptr) {
        *actor_slot = static_cast<int>(live_actor_slot);
    }
    if (live_actor_slot < 0 ||
        live_actor_slot >= static_cast<std::int8_t>(kGameplayPlayerSlotCount)) {
        return false;
    }

    uintptr_t live_gameplay_address = 0;
    if (!TryResolveCurrentGameplayScene(&live_gameplay_address) ||
        live_gameplay_address == 0) {
        return false;
    }
    if (gameplay_address != nullptr) {
        *gameplay_address = live_gameplay_address;
    }

    uintptr_t live_published_actor_address = 0;
    if (!TryResolvePlayerActorForSlot(
            live_gameplay_address,
            static_cast<int>(live_actor_slot),
            &live_published_actor_address)) {
        return false;
    }
    if (published_actor_address != nullptr) {
        *published_actor_address = live_published_actor_address;
    }
    return live_published_actor_address == actor_address;
}

void __fastcall HookPlayerControlBrainUpdate(
    void* self,
    void* /*unused_edx*/,
    void* param2,
    void* param3) {
    const auto original =
        GetX86HookTrampoline<PlayerControlBrainUpdateFn>(
            g_gameplay_keyboard_injection.player_control_brain_update_hook);
    if (original == nullptr) {
        return;
    }

    const auto actor_address = reinterpret_cast<uintptr_t>(self);
    if (IsBoundReplicatedRunEnemyActorForLocalClient(actor_address)) {
        (void)ApplyLatestReplicatedRunEnemyTargetForLocalActor(actor_address, false);
        return;
    }

    // FUN_0052C910 indexes gameplay+0x1358 with actor+0x5C and immediately
    // dereferences the resulting player actor. During native scene creation a
    // slot-assigned PlayerActor can enter the world tick before the gameplay
    // slot table publishes it. Letting that half-created actor reach the stock
    // routine turns a null slot entry into a read at 0x18. A published slot is
    // therefore a hard precondition for both local and replicated players.
    uintptr_t publication_gameplay_address = 0;
    uintptr_t published_actor_address = 0;
    int publication_actor_slot = -1;
    static std::atomic<bool> s_logged_unpublished_actor{false};
    if (!IsPlayerActorPublishedInCurrentGameplaySlot(
            actor_address,
            &publication_gameplay_address,
            &publication_actor_slot,
            &published_actor_address)) {
        if (!s_logged_unpublished_actor.exchange(true, std::memory_order_acq_rel)) {
            Log(
                "[bots] control_brain skipped unpublished player actor during scene transition. actor=" +
                HexString(actor_address) +
                " slot=" + std::to_string(publication_actor_slot) +
                " gameplay=" + HexString(publication_gameplay_address) +
                " published_actor=" + HexString(published_actor_address));
        }
        return;
    }

    auto& memory = ProcessMemory::Instance();
    bool log_this = false;
    std::uint64_t bot_id = 0;
    bool startup = false;
    bool native_target_control_active = false;
    bool selection_target_seed_active = false;
    std::uint8_t selection_target_group_seed = 0xFF;
    std::uint16_t selection_target_slot_seed = 0xFFFF;
    std::int32_t selection_target_hold_ticks = 0;
    bool have_aim_target = false;
    float aim_target_x = 0.0f;
    float aim_target_y = 0.0f;
    bool face_control_active = false;
    bool have_face_vector = false;
    float face_vector_x = 0.0f;
    float face_vector_y = 0.0f;
    bool have_startup_move_vector = false;
    float startup_move_vector_x = 0.0f;
    float startup_move_vector_y = 0.0f;
    float face_heading = 0.0f;
    bool have_face_target = false;
    float face_target_x = 0.0f;
    float face_target_y = 0.0f;
    bool sanitize_native_remote_idle_control_brain = false;
    {
        std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
        if (auto* binding = FindParticipantEntityForActor(actor_address);
            binding != nullptr &&
            (IsGameplaySlotWizardKind(binding->kind) ||
             IsStandaloneWizardKind(binding->kind))) {
            if (binding->ongoing_cast.active &&
                OngoingCastShouldRefreshNativeTargetState(binding->ongoing_cast)) {
                (void)RefreshOngoingCastAimFromFacingTarget(binding, &binding->ongoing_cast);
            }
            (void)RefreshAndApplyWizardBindingFacingState(binding, actor_address);
            have_startup_move_vector = TryGetBindingMovementInputVector(
                *binding,
                &startup_move_vector_x,
                &startup_move_vector_y);
            face_control_active = binding->facing_heading_valid;
            face_heading = binding->facing_heading_value;
            if (binding->facing_target_actor_address != 0) {
                float live_face_heading = 0.0f;
                float live_target_x = 0.0f;
                float live_target_y = 0.0f;
                if (TryComputeActorAimTowardTargetFromOrigin(
                        actor_address,
                        binding->facing_target_actor_address,
                        binding->stock_tick_facing_origin_valid,
                        binding->stock_tick_facing_origin_x,
                        binding->stock_tick_facing_origin_y,
                        &live_face_heading,
                        &live_target_x,
                        &live_target_y)) {
                    face_control_active = true;
                    have_face_target = true;
                    face_target_x = live_target_x;
                    face_target_y = live_target_y;
                    face_heading = live_face_heading;
                    float origin_x = binding->stock_tick_facing_origin_x;
                    float origin_y = binding->stock_tick_facing_origin_y;
                    bool have_origin = binding->stock_tick_facing_origin_valid;
                    if (!have_origin) {
                        have_origin =
                            TryReadFiniteFloatField(actor_address, kActorPositionXOffset, &origin_x) &&
                            TryReadFiniteFloatField(actor_address, kActorPositionYOffset, &origin_y);
                    }
                    if (have_origin) {
                        const auto dx = live_target_x - origin_x;
                        const auto dy = live_target_y - origin_y;
                        const auto distance = std::sqrt((dx * dx) + (dy * dy));
                        if (std::isfinite(distance) && distance > 0.0001f) {
                            have_face_vector = true;
                            face_vector_x = dx / distance;
                            face_vector_y = dy / distance;
                        }
                    }
                }
            }
            if (face_control_active && !have_face_vector) {
                const auto radians =
                    (NormalizeWizardActorHeadingForWrite(face_heading) - 90.0f) /
                    kWizardHeadingRadiansToDegrees;
                face_vector_x = std::cos(radians);
                face_vector_y = std::sin(radians);
                have_face_vector = std::isfinite(face_vector_x) && std::isfinite(face_vector_y);
            }
            bot_id = binding->bot_id;
            startup = binding->ongoing_cast.startup_in_progress;
            sanitize_native_remote_idle_control_brain =
                IsNativeRemoteParticipantBinding(binding) &&
                !binding->ongoing_cast.active;
            native_target_control_active =
                binding->ongoing_cast.active &&
                OngoingCastNeedsNativeTargetActor(binding->ongoing_cast);
            log_this = startup;
            if (!log_this &&
                native_target_control_active &&
                g_pure_primary_control_log_budget > 0) {
                log_this = true;
                --g_pure_primary_control_log_budget;
            }
            selection_target_seed_active =
                binding->ongoing_cast.selection_target_seed_active;
            selection_target_group_seed =
                binding->ongoing_cast.selection_target_group_seed;
            selection_target_slot_seed =
                binding->ongoing_cast.selection_target_slot_seed;
            selection_target_hold_ticks =
                binding->ongoing_cast.selection_target_hold_ticks;
            have_aim_target = binding->ongoing_cast.have_aim_target;
            aim_target_x = binding->ongoing_cast.aim_target_x;
            aim_target_y = binding->ongoing_cast.aim_target_y;
        }
    }
    if (!log_this) {
        uintptr_t gameplay_address = 0;
        uintptr_t local_actor_address = 0;
        if (TryResolveCurrentGameplayScene(&gameplay_address) &&
            gameplay_address != 0 &&
            TryResolvePlayerActorForSlot(gameplay_address, 0, &local_actor_address) &&
            local_actor_address == actor_address &&
            g_local_player_cast_probe.ticks_remaining > 0) {
            log_this = true;
        }
    }

    uintptr_t selection_pointer = 0;
    const bool have_selection_pointer =
        memory.TryReadField(actor_address, kActorAnimationSelectionStateOffset, &selection_pointer);
    constexpr auto kControlBrainVectorSize = sizeof(float) * 2;
    const auto read_vector2 = [&](void* vector_pointer, float* x, float* y) -> bool {
        if (x == nullptr || y == nullptr) {
            return false;
        }
        *x = 0.0f;
        *y = 0.0f;
        const auto address = reinterpret_cast<uintptr_t>(vector_pointer);
        if (address == 0 || !memory.IsReadableRange(address, kControlBrainVectorSize)) {
            return false;
        }
        return memory.TryReadValue(address, x) &&
               memory.TryReadValue(address + sizeof(float), y);
    };
    const auto write_vector2 = [&](void* vector_pointer, float x, float y) -> bool {
        const auto address = reinterpret_cast<uintptr_t>(vector_pointer);
        if (address == 0 || !memory.IsWritableRange(address, kControlBrainVectorSize)) {
            return false;
        }
        const auto wrote_x = memory.TryWriteValue<float>(address, x);
        const auto wrote_y = memory.TryWriteValue<float>(address + sizeof(float), y);
        return wrote_x && wrote_y;
    };

    uintptr_t current_gameplay_address = 0;
    uintptr_t current_local_actor_address = 0;
    const bool manual_spawner_test_mode =
        IsRunLifecycleManualEnemySpawnerTestModeEnabled();
    const bool current_actor_is_local_player =
        manual_spawner_test_mode &&
        TryResolveCurrentGameplayScene(&current_gameplay_address) &&
        current_gameplay_address != 0 &&
        TryResolvePlayerActorForSlot(current_gameplay_address, 0, &current_local_actor_address) &&
        current_local_actor_address == actor_address;
    const auto pending_manual_spawner_primary_allowances =
        g_gameplay_keyboard_injection.pending_manual_spawner_primary_cast_allowances.load(
            std::memory_order_acquire);
    const bool manual_spawner_primary_grace_active =
        IsManualSpawnerPrimaryCastControlGraceActive();
    const auto pending_scripted_movement_frames =
        g_gameplay_keyboard_injection.pending_movement_frames.load(
            std::memory_order_acquire);
    auto& injected_keyboard_control_frames =
        g_gameplay_keyboard_injection.pending_injected_keyboard_control_frames;
    const auto pending_injected_keyboard_control_frames =
        injected_keyboard_control_frames.load(std::memory_order_acquire);
    const bool manual_spawner_scripted_local_primary_control =
        current_actor_is_local_player &&
        (pending_manual_spawner_primary_allowances > 0 ||
         manual_spawner_primary_grace_active);
    const bool suppress_manual_spawner_local_control =
        current_actor_is_local_player &&
        pending_manual_spawner_primary_allowances == 0 &&
        !manual_spawner_primary_grace_active &&
        pending_scripted_movement_frames == 0 &&
        pending_injected_keyboard_control_frames == 0;
    if (suppress_manual_spawner_local_control) {
        ClearManualSpawnerSuppressedLocalPrimaryCastState(actor_address);
        (void)write_vector2(param2, 0.0f, 0.0f);
        (void)write_vector2(param3, 0.0f, 0.0f);
        static std::uint64_t s_last_suppressed_manual_spawner_control_log_ms = 0;
        const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
        if (now_ms - s_last_suppressed_manual_spawner_control_log_ms >= 1000) {
            s_last_suppressed_manual_spawner_control_log_ms = now_ms;
            Log(
                "manual run enemy spawn: suppressed local control-brain update before queued primary. actor=" +
                HexString(actor_address));
        }
        return;
    }

    if (current_actor_is_local_player && pending_injected_keyboard_control_frames > 0) {
        auto available = pending_injected_keyboard_control_frames;
        while (available > 0 &&
               !injected_keyboard_control_frames.compare_exchange_weak(
                   available,
                   available - 1,
                   std::memory_order_acq_rel,
                   std::memory_order_acquire)) {
        }
    }

    float move_x_before = 0.0f;
    float move_y_before = 0.0f;
    float face_x_before = 0.0f;
    float face_y_before = 0.0f;
    (void)read_vector2(param2, &move_x_before, &move_y_before);
    (void)read_vector2(param3, &face_x_before, &face_y_before);
    if (log_this) {
        Log(
            "[bots] control_brain enter actor=" + HexString(actor_address) +
            " bot_id=" + std::to_string(bot_id) +
            " startup=" + std::to_string(startup ? 1 : 0) +
            " native_target_control=" + std::to_string(native_target_control_active ? 1 : 0) +
            " sel_ptr=" + (have_selection_pointer ? HexString(selection_pointer) : UnreadableMemoryFieldText()) +
            " sel_group=" +
                (selection_pointer != 0
                    ? ReadValueDiagnosticText<std::uint8_t>(
                        selection_pointer + kActorControlBrainTargetSlotOffset,
                        [](std::uint8_t value) { return HexString(static_cast<uintptr_t>(value)); })
                    : UnreadableMemoryFieldText()) +
            " sel_slot=" +
                (selection_pointer != 0
                    ? ReadValueDiagnosticText<std::uint16_t>(
                        selection_pointer + kActorControlBrainTargetHandleOffset,
                        [](std::uint16_t value) { return HexString(static_cast<uintptr_t>(value)); })
                    : UnreadableMemoryFieldText()) +
            " sel_t8=" +
                (selection_pointer != 0
                    ? ReadValueDiagnosticText<std::int32_t>(
                        selection_pointer + kActorControlBrainRetargetTicksOffset,
                        [](std::int32_t value) { return std::to_string(value); })
                    : UnreadableMemoryFieldText()) +
            " move_before=(" + std::to_string(move_x_before) + "," + std::to_string(move_y_before) + ")" +
            " face_before=(" + std::to_string(face_x_before) + "," + std::to_string(face_y_before) + ")" +
            " startup_state={" + DescribeGameplaySlotCastStartupWindow(actor_address) + "}");
    }

    const auto seed_selection_target = [&]() {
        if (!native_target_control_active || selection_pointer == 0 || !selection_target_seed_active) {
            return;
        }
        (void)memory.TryWriteField<std::uint8_t>(
            selection_pointer,
            kActorControlBrainTargetSlotOffset,
            selection_target_group_seed);
        (void)memory.TryWriteField<std::uint16_t>(
            selection_pointer,
            kActorControlBrainTargetHandleOffset,
            selection_target_slot_seed);
        (void)memory.TryWriteField<std::int32_t>(
            selection_pointer,
            kActorControlBrainRetargetTicksOffset,
            selection_target_hold_ticks);
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
    };

    const auto apply_face_control = [&]() {
        if (!face_control_active || !have_face_vector) {
            return;
        }
        (void)write_vector2(param3, face_vector_x, face_vector_y);
        ApplyWizardActorFacingState(actor_address, face_heading);
        if (native_target_control_active && startup && selection_pointer != 0) {
            // The stock pure-primary startup gate needs a non-zero movement
            // vector. Use the follow lane while moving and attack-facing when idle.
            const auto startup_input_x =
                have_startup_move_vector ? startup_move_vector_x : face_vector_x;
            const auto startup_input_y =
                have_startup_move_vector ? startup_move_vector_y : face_vector_y;
            (void)memory.TryWriteValue<float>(
                selection_pointer + kActorControlBrainMoveInputXOffset,
                startup_input_x);
            (void)memory.TryWriteValue<float>(
                selection_pointer + kActorControlBrainMoveInputYOffset,
                startup_input_y);
        }
        if (have_face_target) {
            (void)memory.TryWriteField(actor_address, kActorAimTargetXOffset, face_target_x);
            (void)memory.TryWriteField(actor_address, kActorAimTargetYOffset, face_target_y);
            (void)memory.TryWriteField<std::uint32_t>(actor_address, kActorAimTargetAux0Offset, 0);
            (void)memory.TryWriteField<std::uint32_t>(actor_address, kActorAimTargetAux1Offset, 0);
        } else if (have_aim_target) {
            (void)memory.TryWriteField(actor_address, kActorAimTargetXOffset, aim_target_x);
            (void)memory.TryWriteField(actor_address, kActorAimTargetYOffset, aim_target_y);
            (void)memory.TryWriteField<std::uint32_t>(actor_address, kActorAimTargetAux0Offset, 0);
            (void)memory.TryWriteField<std::uint32_t>(actor_address, kActorAimTargetAux1Offset, 0);
        }
    };

    const auto apply_manual_spawner_local_primary_control = [&]() {
        if (!manual_spawner_scripted_local_primary_control || selection_pointer == 0) {
            return;
        }

        const auto manual_spawner_target_actor =
            g_gameplay_keyboard_injection.manual_spawner_primary_target_actor.load(
                std::memory_order_acquire);
        const bool target_state_seeded = ApplyManualSpawnerPrimaryTargetState(
            actor_address,
            selection_pointer,
            manual_spawner_target_actor);

        float position_x = 0.0f;
        float position_y = 0.0f;
        float aim_target_x = 0.0f;
        float aim_target_y = 0.0f;
        if (!TryReadFiniteFloatField(actor_address, kActorPositionXOffset, &position_x) ||
            !TryReadFiniteFloatField(actor_address, kActorPositionYOffset, &position_y) ||
            !TryReadFiniteFloatField(actor_address, kActorAimTargetXOffset, &aim_target_x) ||
            !TryReadFiniteFloatField(actor_address, kActorAimTargetYOffset, &aim_target_y) ||
            !IsUsableLocalPlayerCastAimTarget(position_x, position_y, aim_target_x, aim_target_y)) {
            return;
        }

        const auto dx = aim_target_x - position_x;
        const auto dy = aim_target_y - position_y;
        const auto distance = std::sqrt((dx * dx) + (dy * dy));
        if (!std::isfinite(distance) || distance <= 0.0001f) {
            return;
        }

        const auto control_x = dx / distance;
        const auto control_y = dy / distance;
        if (!std::isfinite(control_x) || !std::isfinite(control_y)) {
            return;
        }

        const auto desired_heading = NormalizeWizardActorHeadingForWrite(
            static_cast<float>(std::atan2(control_y, control_x) * kWizardHeadingRadiansToDegrees + 90.0f));
        (void)write_vector2(param2, 0.0f, 0.0f);
        (void)write_vector2(param3, control_x, control_y);
        ApplyWizardActorFacingState(actor_address, desired_heading);
        (void)memory.TryWriteValue<float>(
            selection_pointer + kActorControlBrainMoveInputXOffset,
            control_x);
        (void)memory.TryWriteValue<float>(
            selection_pointer + kActorControlBrainMoveInputYOffset,
            control_y);
        (void)memory.TryWriteField(actor_address, kActorAimTargetXOffset, aim_target_x);
        (void)memory.TryWriteField(actor_address, kActorAimTargetYOffset, aim_target_y);
        (void)memory.TryWriteField<std::uint32_t>(actor_address, kActorAimTargetAux0Offset, 0);
        (void)memory.TryWriteField<std::uint32_t>(actor_address, kActorAimTargetAux1Offset, 0);

        static std::uint64_t s_last_manual_spawner_local_control_seed_log_ms = 0;
        const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
        if (now_ms - s_last_manual_spawner_local_control_seed_log_ms >= 1000) {
            s_last_manual_spawner_local_control_seed_log_ms = now_ms;
            Log(
                "manual run enemy spawn: seeded local scripted primary control. actor=" +
                HexString(actor_address) +
                " target=" + HexString(manual_spawner_target_actor) +
                " target_state_seeded=" + std::to_string(target_state_seeded ? 1 : 0) +
                " aim=(" + std::to_string(aim_target_x) + "," + std::to_string(aim_target_y) + ")" +
                " control=(" + std::to_string(control_x) + "," + std::to_string(control_y) + ")");
        }
    };

    if (sanitize_native_remote_idle_control_brain) {
        ClearIdleNativeRemoteCastReplayState(actor_address, selection_pointer);
        (void)write_vector2(param2, 0.0f, 0.0f);
    }

    // Stock attack/cast code consumes the face lane during its own update, so
    // provide the current target-facing vector before the original runs. Re-pin
    // after the original too because stock may clear the cached target fields.
    seed_selection_target();
    apply_manual_spawner_local_primary_control();
    apply_face_control();
    if (manual_spawner_scripted_local_primary_control) {
        uintptr_t manual_spawner_target_actor = 0;
        if (memory.TryReadField(
                actor_address,
                kActorCurrentTargetActorOffset,
                &manual_spawner_target_actor) &&
            IsManualSpawnerPrimaryTargetActor(manual_spawner_target_actor)) {
            g_gameplay_keyboard_injection.manual_spawner_primary_target_actor.store(
                manual_spawner_target_actor,
                std::memory_order_release);
        }
    }
    original(self, param2, param3);
    if (sanitize_native_remote_idle_control_brain) {
        ClearIdleNativeRemoteCastReplayState(actor_address, selection_pointer);
        (void)write_vector2(param2, 0.0f, 0.0f);
    }

    float raw_move_x_after = 0.0f;
    float raw_move_y_after = 0.0f;
    float raw_face_x_after = 0.0f;
    float raw_face_y_after = 0.0f;
    (void)read_vector2(param2, &raw_move_x_after, &raw_move_y_after);
    (void)read_vector2(param3, &raw_face_x_after, &raw_face_y_after);
    const auto raw_move_mag_sq_after =
        raw_move_x_after * raw_move_x_after + raw_move_y_after * raw_move_y_after;
    const auto raw_face_mag_sq_after =
        raw_face_x_after * raw_face_x_after + raw_face_y_after * raw_face_y_after;

    seed_selection_target();
    apply_manual_spawner_local_primary_control();
    apply_face_control();

    // Deterministic held movement is injected at the control-brain output.
    // It intentionally exercises the standing movement envelope, collision,
    // transform publication, and replication, but it is downstream of ranked
    // input modifiers such as Rush. Ranked behavior tests must validate that
    // native lane separately instead of treating this as raw keyboard input.
    uintptr_t movement_gameplay_address = 0;
    uintptr_t movement_local_actor_address = 0;
    const bool movement_actor_is_local_player =
        TryResolveCurrentGameplayScene(&movement_gameplay_address) &&
        movement_gameplay_address != 0 &&
        TryResolvePlayerActorForSlot(
            movement_gameplay_address,
            0,
            &movement_local_actor_address) &&
        movement_local_actor_address == actor_address;
    if (movement_actor_is_local_player) {
        auto& pending_frames =
            g_gameplay_keyboard_injection.pending_movement_frames;
        auto available = pending_frames.load(std::memory_order_acquire);
        while (available > 0) {
            if (pending_frames.compare_exchange_weak(
                    available,
                    available - 1,
                    std::memory_order_acq_rel,
                    std::memory_order_acquire)) {
                const auto movement_x =
                    g_gameplay_keyboard_injection.pending_movement_x.load(
                        std::memory_order_acquire);
                const auto movement_y =
                    g_gameplay_keyboard_injection.pending_movement_y.load(
                        std::memory_order_acquire);
                (void)write_vector2(param2, movement_x, movement_y);
                break;
            }
        }
    }

    float move_x_after = 0.0f;
    float move_y_after = 0.0f;
    float face_x_after = 0.0f;
    float face_y_after = 0.0f;
    (void)read_vector2(param2, &move_x_after, &move_y_after);
    (void)read_vector2(param3, &face_x_after, &face_y_after);
    if (log_this) {
        Log(
            "[bots] control_brain exit actor=" + HexString(actor_address) +
            " bot_id=" + std::to_string(bot_id) +
            " native_target_control=" + std::to_string(native_target_control_active ? 1 : 0) +
            " raw_move_after=(" + std::to_string(raw_move_x_after) + "," + std::to_string(raw_move_y_after) + ")" +
            " raw_move_mag_sq=" + std::to_string(raw_move_mag_sq_after) +
            " raw_face_after=(" + std::to_string(raw_face_x_after) + "," + std::to_string(raw_face_y_after) + ")" +
            " raw_face_mag_sq=" + std::to_string(raw_face_mag_sq_after) +
            " move_after=(" + std::to_string(move_x_after) + "," + std::to_string(move_y_after) + ")" +
            " face_after=(" + std::to_string(face_x_after) + "," + std::to_string(face_y_after) + ")" +
            " startup_state={" + DescribeGameplaySlotCastStartupWindow(actor_address) + "}");
    }
}

bool IsActorCurrentLocalPlayerSlotZero(uintptr_t actor_address) {
    if (actor_address == 0) {
        return false;
    }

    uintptr_t gameplay_address = 0;
    uintptr_t local_actor_address = 0;
    return TryResolveCurrentGameplayScene(&gameplay_address) &&
           gameplay_address != 0 &&
           TryResolvePlayerActorForSlot(gameplay_address, 0, &local_actor_address) &&
           local_actor_address == actor_address;
}

bool IsUsableLocalPlayerCastAimTarget(
    float position_x,
    float position_y,
    float aim_target_x,
    float aim_target_y) {
    if (!std::isfinite(position_x) ||
        !std::isfinite(position_y) ||
        !std::isfinite(aim_target_x) ||
        !std::isfinite(aim_target_y)) {
        return false;
    }
    if (std::abs(aim_target_x) < 0.001f && std::abs(aim_target_y) < 0.001f) {
        return false;
    }

    const auto dx = aim_target_x - position_x;
    const auto dy = aim_target_y - position_y;
    const auto distance = std::sqrt((dx * dx) + (dy * dy));
    constexpr float kMinCastAimDistance = 1.0f;
    constexpr float kMaxCastAimDistance = 4096.0f;
    constexpr float kMaxCastAimCoordinateMagnitude = 20000.0f;
    return std::isfinite(distance) &&
           distance >= kMinCastAimDistance &&
           distance <= kMaxCastAimDistance &&
           std::abs(aim_target_x) <= kMaxCastAimCoordinateMagnitude &&
           std::abs(aim_target_y) <= kMaxCastAimCoordinateMagnitude;
}

void ClearManualSpawnerSuppressedLocalPrimaryCastState(uintptr_t actor_address) {
    if (actor_address == 0) {
        return;
    }

    g_gameplay_keyboard_injection.pending_mouse_left_frames.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.pending_mouse_left_edge_events.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.pending_manual_spawner_primary_cast_allowances.store(
        0,
        std::memory_order_release);
    g_gameplay_keyboard_injection.manual_spawner_primary_cast_control_grace_until_ms.store(
        0,
        std::memory_order_release);
    g_gameplay_keyboard_injection.manual_spawner_primary_target_actor.store(
        0,
        std::memory_order_release);
    g_gameplay_keyboard_injection.last_observed_mouse_left_down.store(false, std::memory_order_release);
    g_gameplay_keyboard_injection.injected_mouse_left_active.store(false, std::memory_order_release);

    auto& memory = ProcessMemory::Instance();
    uintptr_t gameplay_address = 0;
    if (TryResolveCurrentGameplayScene(&gameplay_address) && gameplay_address != 0) {
        const std::uint8_t released = 0;
        (void)memory.TryWriteField(gameplay_address, kGameplayCastIntentOffset, released);
        int input_buffer_index = -1;
        if (memory.TryReadField(gameplay_address, kGameplayInputBufferIndexOffset, &input_buffer_index) &&
            input_buffer_index >= 0) {
            for (int buffer_index = 0; buffer_index < kGameplayInputBufferCount; ++buffer_index) {
                const auto mouse_left_offset = static_cast<std::size_t>(
                    buffer_index * kGameplayInputBufferStride + kGameplayMouseLeftButtonOffset);
                (void)memory.TryWriteField(gameplay_address, mouse_left_offset, released);
            }
        }
    }

    (void)memory.TryWriteField<std::int32_t>(actor_address, kActorPrimarySkillIdOffset, 0);
    (void)memory.TryWriteField<std::int32_t>(actor_address, kActorPreviousSkillIdOffset, 0);
    (void)memory.TryWriteField<std::uint32_t>(actor_address, kActorPrimaryActionLatchE4Offset, 0);
    (void)memory.TryWriteField<std::uint32_t>(actor_address, kActorPrimaryActionLatchE8Offset, 0);
    (void)memory.TryWriteField<std::uint8_t>(actor_address, kActorPostGateActiveByteOffset, 0);
    (void)memory.TryWriteField<std::uint8_t>(
        actor_address,
        kActorSpellTargetGroupByteOffset,
        kTargetHandleGroupSentinel);
    (void)memory.TryWriteField<std::uint16_t>(
        actor_address,
        kActorSpellTargetSlotShortOffset,
        kTargetHandleSlotSentinel);
    (void)memory.TryWriteField<uintptr_t>(actor_address, kActorCurrentTargetActorOffset, 0);
    (void)memory.TryWriteField<std::int32_t>(actor_address, kActorCurrentTargetBucketDeltaOffset, 0);

    uintptr_t selection_pointer = 0;
    if (!memory.TryReadField(actor_address, kActorAnimationSelectionStateOffset, &selection_pointer) ||
        selection_pointer == 0) {
        return;
    }

    constexpr std::int32_t kSuppressedLocalPrimaryRetargetTicks = 60;
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
        kSuppressedLocalPrimaryRetargetTicks);
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
    (void)memory.TryWriteField<std::int32_t>(
        selection_pointer,
        kActorControlBrainHeadingLockTicksOffset,
        0);
    (void)memory.TryWriteField<float>(
        selection_pointer,
        kActorControlBrainMoveInputXOffset,
        0.0f);
    (void)memory.TryWriteField<float>(
        selection_pointer,
        kActorControlBrainMoveInputYOffset,
        0.0f);
}

bool TryConsumeManualSpawnerPrimaryCastAllowance() {
    auto& allowances = g_gameplay_keyboard_injection.pending_manual_spawner_primary_cast_allowances;
    auto available = allowances.load(std::memory_order_acquire);
    while (available > 0) {
        if (allowances.compare_exchange_weak(
                available,
                available - 1,
                std::memory_order_acq_rel,
                std::memory_order_acquire)) {
            return true;
        }
    }
    return false;
}

bool ShouldSuppressManualSpawnerTestLocalPurePrimary(uintptr_t actor_address) {
    if (!IsRunLifecycleManualEnemySpawnerTestModeEnabled() ||
        !IsActorCurrentLocalPlayerSlotZero(actor_address)) {
        return false;
    }

    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    if (TryConsumeManualSpawnerPrimaryCastAllowance()) {
        return false;
    }

    if (IsManualSpawnerPrimaryCastControlGraceActive()) {
        static std::uint64_t s_last_grace_suppressed_manual_spawner_primary_log_ms = 0;
        if (now_ms - s_last_grace_suppressed_manual_spawner_primary_log_ms >= 1000) {
            s_last_grace_suppressed_manual_spawner_primary_log_ms = now_ms;
            Log(
                "manual run enemy spawn: suppressed extra local pure-primary start during scripted cast grace. actor=" +
                HexString(actor_address));
        }
        return true;
    }

    ClearManualSpawnerSuppressedLocalPrimaryCastState(actor_address);
    static std::uint64_t s_last_suppressed_manual_spawner_primary_log_ms = 0;
    if (now_ms - s_last_suppressed_manual_spawner_primary_log_ms >= 1000) {
        s_last_suppressed_manual_spawner_primary_log_ms = now_ms;
        Log(
            "manual run enemy spawn: suppressed unintentional local pure-primary start. actor=" +
            HexString(actor_address));
    }
    return true;
}

bool QueueLocalPlayerPrimaryCastForMultiplayer(uintptr_t actor_address) {
    if (!multiplayer::IsLocalTransportEnabled() ||
        !IsActorCurrentLocalPlayerSlotZero(actor_address)) {
        return false;
    }

    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());

    static std::atomic<uintptr_t> s_last_multiplayer_primary_actor{0};
    static std::atomic<std::uint64_t> s_last_multiplayer_primary_tick_ms{0};
    const auto last_actor =
        s_last_multiplayer_primary_actor.load(std::memory_order_acquire);
    const auto last_tick_ms =
        s_last_multiplayer_primary_tick_ms.load(std::memory_order_acquire);
    if (last_actor == actor_address && last_tick_ms == now_ms) {
        return false;
    }
    s_last_multiplayer_primary_actor.store(actor_address, std::memory_order_release);
    s_last_multiplayer_primary_tick_ms.store(now_ms, std::memory_order_release);

    float x = 0.0f;
    float y = 0.0f;
    float heading = 0.0f;
    if (!TryReadFiniteFloatField(actor_address, kActorPositionXOffset, &x) ||
        !TryReadFiniteFloatField(actor_address, kActorPositionYOffset, &y) ||
        !TryReadFiniteFloatField(actor_address, kActorHeadingOffset, &heading)) {
        Log("Multiplayer local primary cast skipped: actor fields unavailable. actor=" + HexString(actor_address));
        return false;
    }

    auto radians =
        (NormalizeWizardActorHeadingForWrite(heading) - 90.0f) /
        kWizardHeadingRadiansToDegrees;
    auto direction_x = static_cast<float>(std::cos(radians));
    auto direction_y = static_cast<float>(std::sin(radians));
    if (!std::isfinite(direction_x) || !std::isfinite(direction_y)) {
        return false;
    }

    bool has_aim_target = false;
    float aim_target_x = 0.0f;
    float aim_target_y = 0.0f;
    if (TryReadFiniteFloatField(actor_address, kActorAimTargetXOffset, &aim_target_x) &&
        TryReadFiniteFloatField(actor_address, kActorAimTargetYOffset, &aim_target_y) &&
        IsUsableLocalPlayerCastAimTarget(x, y, aim_target_x, aim_target_y)) {
        const auto aim_dx = aim_target_x - x;
        const auto aim_dy = aim_target_y - y;
        const auto aim_length = std::sqrt((aim_dx * aim_dx) + (aim_dy * aim_dy));
        if (std::isfinite(aim_length) && aim_length > 0.0001f) {
            direction_x = aim_dx / aim_length;
            direction_y = aim_dy / aim_length;
            has_aim_target = true;
        }
    }

    uintptr_t target_actor_address = 0;
    (void)ProcessMemory::Instance().TryReadField(
        actor_address,
        kActorCurrentTargetActorOffset,
        &target_actor_address);

    const auto native_queue_id = multiplayer::QueueLocalSpellCastEvent(
        0,
        x,
        y,
            direction_x,
            direction_y,
            0,
            target_actor_address,
            12,
            has_aim_target,
            aim_target_x,
            aim_target_y);
    if (native_queue_id == 0) {
        return false;
    }
    Log(
        "Multiplayer local primary cast queued from native pure-primary. actor=" +
        HexString(actor_address) +
        " native_queue_id=" + std::to_string(native_queue_id) +
        " native_tick_ms=" + std::to_string(now_ms) +
        " pos=(" + std::to_string(x) + "," + std::to_string(y) + ")" +
        " heading=" + std::to_string(heading) +
        " dir=(" + std::to_string(direction_x) + "," + std::to_string(direction_y) + ")" +
        " aim_target=" +
            (has_aim_target
                ? (std::to_string(aim_target_x) + "," + std::to_string(aim_target_y))
                : std::string("<none>")) +
        " target=" + HexString(target_actor_address));
    return true;
}

void __fastcall HookPurePrimarySpellStart(void* self, void* /*unused_edx*/) {
    const auto original =
        GetX86HookTrampoline<PlayerActorNoArgMethodFn>(g_gameplay_keyboard_injection.pure_primary_spell_start_hook);
    if (original == nullptr) {
        return;
    }

    const auto actor_address = reinterpret_cast<uintptr_t>(self);
    if (ShouldSuppressManualSpawnerTestLocalPurePrimary(actor_address)) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    if (IsRunLifecycleManualEnemySpawnerTestModeEnabled() &&
        IsActorCurrentLocalPlayerSlotZero(actor_address) &&
        IsManualSpawnerPrimaryCastControlGraceActive()) {
        const auto manual_spawner_target_actor =
            g_gameplay_keyboard_injection.manual_spawner_primary_target_actor.load(
                std::memory_order_acquire);
        if (IsManualSpawnerPrimaryTargetActor(manual_spawner_target_actor)) {
            uintptr_t selection_pointer = 0;
            const bool have_selection_pointer = memory.TryReadField(
                actor_address,
                kActorAnimationSelectionStateOffset,
                &selection_pointer);
            const bool target_state_seeded =
                have_selection_pointer &&
                ApplyManualSpawnerPrimaryTargetState(
                    actor_address,
                    selection_pointer,
                    manual_spawner_target_actor);
            if (target_state_seeded) {
                static std::uint64_t s_last_manual_spawner_target_restore_log_ms = 0;
                const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
                if (now_ms - s_last_manual_spawner_target_restore_log_ms >= 1000) {
                    s_last_manual_spawner_target_restore_log_ms = now_ms;
                    Log(
                        "manual run enemy spawn: restored scripted primary target and native handle before native start. actor=" +
                        HexString(actor_address) +
                        " target=" + HexString(manual_spawner_target_actor));
                }
            }
        }
    }

    bool log_this = false;
    std::uint64_t bot_id = 0;
    bool startup = false;
    bool active_pure_primary_cast = false;
    bool bot_owned_pure_primary_actor = false;
    bool local_player = false;
    bool pure_primary_bot_owner_context = false;
    {
        std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
        if (auto* binding = FindParticipantEntityForActor(actor_address);
            binding != nullptr &&
            (IsGameplaySlotWizardKind(binding->kind) ||
             IsStandaloneWizardKind(binding->kind))) {
            SyncWizardBotMovementIntent(binding);
            bot_id = binding->bot_id;
            startup = binding->ongoing_cast.startup_in_progress;
            bot_owned_pure_primary_actor = true;
            active_pure_primary_cast =
                binding->ongoing_cast.active &&
                binding->ongoing_cast.lane ==
                    ParticipantEntityBinding::OngoingCastState::Lane::PurePrimary;
            pure_primary_bot_owner_context = bot_owned_pure_primary_actor;
            log_this = startup;
            if (!log_this &&
                active_pure_primary_cast &&
                g_pure_primary_control_log_budget > 0) {
                log_this = true;
                --g_pure_primary_control_log_budget;
            }
            if (active_pure_primary_cast) {
                (void)RefreshAndApplyWizardBindingFacingState(binding, actor_address);
            }
        }
    }
    if (!log_this) {
        uintptr_t gameplay_address = 0;
        uintptr_t local_actor_address = 0;
        if (TryResolveCurrentGameplayScene(&gameplay_address) &&
            gameplay_address != 0 &&
            TryResolvePlayerActorForSlot(gameplay_address, 0, &local_actor_address) &&
            local_actor_address == actor_address) {
            log_this = true;
            local_player = true;
        }
    }

    if (log_this) {
        uintptr_t actor_1fc_ptr = 0;
        const bool have_actor_1fc =
            memory.TryReadField(actor_address, kActorEquipRuntimeStateOffset, &actor_1fc_ptr);
        uintptr_t actor_1fc_obj30 = 0;
        const bool have_actor_1fc_obj30 =
            have_actor_1fc &&
            actor_1fc_ptr != 0 &&
            memory.TryReadValue(
                actor_1fc_ptr + kActorEquipRuntimeVisualLinkAttachmentOffset,
                &actor_1fc_obj30);
        uintptr_t actor_1fc_inner = 0;
        const bool have_actor_1fc_inner =
            have_actor_1fc_obj30 &&
            actor_1fc_obj30 != 0 &&
            memory.TryReadValue(actor_1fc_obj30, &actor_1fc_inner);
        std::uint32_t actor_1fc_plus4 = 0;
        const bool have_actor_1fc_plus4 =
            have_actor_1fc_inner &&
            actor_1fc_inner != 0 &&
            memory.TryReadValue(
                actor_1fc_inner + kVisualLaneHolderCurrentObjectOffset,
                &actor_1fc_plus4);
        std::uint32_t actor_1fc_plus4_type = 0;
        const bool have_actor_1fc_plus4_type =
            have_actor_1fc_plus4 &&
            actor_1fc_plus4 != 0 &&
            memory.TryReadValue(
                static_cast<uintptr_t>(actor_1fc_plus4) + kGameObjectTypeIdOffset,
                &actor_1fc_plus4_type);
        Log(
            "[bots] pure_primary_start enter actor=" + HexString(actor_address) +
            " bot_id=" + std::to_string(bot_id) +
            " startup=" + std::to_string(startup ? 1 : 0) +
            " direct_actor_equip=" + (have_actor_1fc
                ? std::to_string(actor_1fc_ptr != 0 ? 1 : 0)
                : UnreadableMemoryFieldText()) +
            " actor1fc=" + (have_actor_1fc ? HexString(actor_1fc_ptr) : UnreadableMemoryFieldText()) +
            " actor1fc30=" + (have_actor_1fc_obj30 ? HexString(actor_1fc_obj30) : UnreadableMemoryFieldText()) +
            " actor1fc_inner=" + (have_actor_1fc_inner ? HexString(actor_1fc_inner) : UnreadableMemoryFieldText()) +
            " actor1fc_plus4=" + (have_actor_1fc_plus4 ? HexString(actor_1fc_plus4) : UnreadableMemoryFieldText()) +
            " actor1fc_plus4_type=" + (have_actor_1fc_plus4_type
                ? HexString(actor_1fc_plus4_type)
                : UnreadableMemoryFieldText()) +
            " startup={" + DescribeGameplaySlotCastStartupWindow(actor_address) + "}");
    }
    SpellDispatchProbeState saved_probe = g_spell_dispatch_probe;
    if (log_this) {
        g_spell_dispatch_probe.depth = saved_probe.depth + 1;
        g_spell_dispatch_probe.actor_address = actor_address;
        g_spell_dispatch_probe.bot_id = bot_id;
        g_spell_dispatch_probe.startup = startup;
        g_spell_dispatch_probe.pure_primary_startup = bot_owned_pure_primary_actor;
        g_spell_dispatch_probe.local_player = local_player;
    }
    std::string slot_owner_context;
    InvokeWithBotProgressionSlotOwnerContext(
        actor_address,
        pure_primary_bot_owner_context,
        [&] {
            original(self);
        },
        &slot_owner_context);
    g_spell_dispatch_probe = saved_probe;
    if (active_pure_primary_cast) {
        std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
        if (auto* binding = FindParticipantEntityForActor(actor_address);
            binding != nullptr &&
            (IsGameplaySlotWizardKind(binding->kind) ||
             IsStandaloneWizardKind(binding->kind))) {
            (void)RefreshAndApplyWizardBindingFacingState(binding, actor_address);
        }
    }
    (void)QueueLocalPlayerPrimaryCastForMultiplayer(actor_address);
    if (log_this) {
        Log(
            "[bots] pure_primary_start exit actor=" + HexString(actor_address) +
            " bot_id=" + std::to_string(bot_id) +
            " standalone_slot_owner_context={" + slot_owner_context + "}" +
            " startup={" + DescribeGameplaySlotCastStartupWindow(actor_address) + "}");
    }
}
