bool IsGameplayKeyboardInjectionInitialized() {
    return g_gameplay_keyboard_injection.initialized;
}

std::uint64_t GetGameplayMouseLeftEdgeSerial() {
    return g_gameplay_keyboard_injection.mouse_left_edge_serial.load(std::memory_order_acquire);
}

std::uint64_t GetGameplayMouseLeftEdgeTickMs() {
    return g_gameplay_keyboard_injection.mouse_left_edge_tick_ms.load(std::memory_order_acquire);
}

std::uint64_t GetGameplayMouseRightEdgeSerial() {
    return g_gameplay_keyboard_injection.mouse_right_edge_serial.load(
        std::memory_order_acquire);
}

bool TryClaimGameplayMouseLeftPrimaryCastEdge(std::uint64_t edge_serial) {
    if (edge_serial == 0 ||
        edge_serial != g_gameplay_keyboard_injection.mouse_left_edge_serial.load(
                           std::memory_order_acquire)) {
        return false;
    }

    auto claimed =
        g_gameplay_keyboard_injection.claimed_primary_cast_edge_serial.load(
            std::memory_order_acquire);
    while (claimed < edge_serial) {
        if (g_gameplay_keyboard_injection.claimed_primary_cast_edge_serial
                .compare_exchange_weak(
                    claimed,
                    edge_serial,
                    std::memory_order_acq_rel,
                    std::memory_order_acquire)) {
            return true;
        }
    }
    return false;
}

bool IsGameplayMouseLeftDown() {
    return g_gameplay_keyboard_injection.last_observed_mouse_left_down.load(std::memory_order_acquire);
}

bool IsGameplayMouseRightDown() {
    return g_gameplay_keyboard_injection.last_observed_mouse_right_down.load(
        std::memory_order_acquire);
}

bool PinManualSpawnerPrimaryTarget(uintptr_t actor_address, std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!IsRunLifecycleManualEnemySpawnerTestModeEnabled()) {
        if (error_message != nullptr) {
            *error_message = "Manual enemy spawner test mode is not active.";
        }
        return false;
    }
    if (!IsManualSpawnerPrimaryTargetActor(actor_address)) {
        if (error_message != nullptr) {
            *error_message = "Manual spawner primary target actor is not a live arena target.";
        }
        return false;
    }

    g_gameplay_keyboard_injection.manual_spawner_primary_target_actor.store(
        actor_address,
        std::memory_order_release);
    return true;
}

bool ApplyPinnedManualSpawnerPrimaryTarget(uintptr_t actor_address) {
    if (!IsRunLifecycleManualEnemySpawnerTestModeEnabled() ||
        !IsActorCurrentLocalPlayerSlotZero(actor_address) ||
        !IsManualSpawnerPrimaryCastControlGraceActive()) {
        return false;
    }

    const auto target_actor_address =
        g_gameplay_keyboard_injection.manual_spawner_primary_target_actor.load(
            std::memory_order_acquire);
    return IsManualSpawnerPrimaryTargetActor(target_actor_address) &&
           ApplyManualSpawnerPrimaryTargetState(
               actor_address,
               0,
               target_actor_address);
}

bool QueueLocalPlayerNativeDispatcherPrimaryCast(
    uintptr_t actor_address,
    std::int32_t dispatched_skill_id) {
    return QueueLocalPlayerPrimaryCastForMultiplayer(
        actor_address,
        LocalPrimaryCastCaptureKind::NativeDispatcherPrimary,
        dispatched_skill_id);
}

bool QueueGameplayMouseLeftClick(std::string* error_message) {
    return QueueGameplayMouseLeftHoldFrames(kInjectedGameplayMouseClickFrames, error_message);
}

bool QueueGameplayMouseRightClick(std::string* error_message) {
    return QueueGameplayMouseRightHoldFrames(
        kInjectedGameplayMouseClickFrames,
        error_message);
}

bool QueueGameplayMovementHoldFrames(
    float direction_x,
    float direction_y,
    std::uint32_t frames,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!g_gameplay_keyboard_injection.initialized) {
        if (error_message != nullptr) {
            *error_message = "Gameplay input injection is not initialized.";
        }
        return false;
    }
    if (frames == 0 || frames > 3600) {
        if (error_message != nullptr) {
            *error_message = "Movement hold frames must be in the range 1..3600.";
        }
        return false;
    }
    const auto magnitude = std::sqrt(
        direction_x * direction_x + direction_y * direction_y);
    if (!std::isfinite(magnitude) || magnitude <= 0.0001f) {
        if (error_message != nullptr) {
            *error_message = "Movement direction must be finite and non-zero.";
        }
        return false;
    }
    if (magnitude > 1.0f) {
        direction_x /= magnitude;
        direction_y /= magnitude;
    }

    uintptr_t scene_address = 0;
    if (!TryResolveCurrentGameplayScene(&scene_address) || scene_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Gameplay scene is not active.";
        }
        return false;
    }

    g_gameplay_keyboard_injection.pending_movement_x.store(
        direction_x,
        std::memory_order_release);
    g_gameplay_keyboard_injection.pending_movement_y.store(
        direction_y,
        std::memory_order_release);
    g_gameplay_keyboard_injection.pending_movement_frames.fetch_add(
        frames,
        std::memory_order_acq_rel);
    return true;
}

bool SetGameplayNativeControlAllowanceFrames(
    std::uint32_t frames,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!g_gameplay_keyboard_injection.initialized) {
        if (error_message != nullptr) {
            *error_message = "Gameplay input injection is not initialized.";
        }
        return false;
    }
    if (frames > 3600) {
        if (error_message != nullptr) {
            *error_message = "Native control allowance frames must be in the range 0..3600.";
        }
        return false;
    }
    g_gameplay_keyboard_injection.pending_injected_keyboard_control_frames.store(
        frames,
        std::memory_order_release);
    return true;
}

bool QueueGameplayMouseLeftHoldFrames(std::uint32_t frames, std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!g_gameplay_keyboard_injection.initialized) {
        if (error_message != nullptr) {
            *error_message = "Gameplay input injection is not initialized.";
        }
        return false;
    }
    if (frames == 0 || frames > 3600) {
        if (error_message != nullptr) {
            *error_message = "Mouse-left hold frames must be in the range 1..3600.";
        }
        return false;
    }

    uintptr_t scene_address = 0;
    if (!TryResolveCurrentGameplayScene(&scene_address) || scene_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Gameplay scene is not active.";
        }
        return false;
    }

    const auto queued_frames =
        g_gameplay_keyboard_injection.pending_mouse_left_frames.fetch_add(
            frames,
            std::memory_order_acq_rel) + frames;
    g_gameplay_keyboard_injection.pending_mouse_left_edge_events.store(
        1,
        std::memory_order_release);
    if (IsRunLifecycleManualEnemySpawnerTestModeEnabled()) {
        constexpr std::uint64_t kManualSpawnerPrimaryCastControlGraceMinMs = 1500;
        const auto frame_grace_ms =
            static_cast<std::uint64_t>(queued_frames) * 50 + 250;
        const auto grace_ms =
            frame_grace_ms > kManualSpawnerPrimaryCastControlGraceMinMs
                ? frame_grace_ms
                : kManualSpawnerPrimaryCastControlGraceMinMs;
        g_gameplay_keyboard_injection.pending_manual_spawner_primary_cast_allowances.fetch_add(
            1,
            std::memory_order_acq_rel);
        g_gameplay_keyboard_injection.manual_spawner_primary_target_actor.store(
            0,
            std::memory_order_release);
        g_gameplay_keyboard_injection.manual_spawner_primary_cast_control_grace_until_ms.store(
            static_cast<std::uint64_t>(GetTickCount64()) + grace_ms,
            std::memory_order_release);
    }
    Log("Queued gameplay mouse-left hold. gameplay=" + HexString(scene_address) +
        " frames=" + std::to_string(frames));
    return true;
}

bool QueueGameplayMouseRightHoldFrames(
    std::uint32_t frames,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!g_gameplay_keyboard_injection.initialized) {
        if (error_message != nullptr) {
            *error_message = "Gameplay input injection is not initialized.";
        }
        return false;
    }
    if (frames == 0 || frames > 3600) {
        if (error_message != nullptr) {
            *error_message = "Mouse-right hold frames must be in the range 1..3600.";
        }
        return false;
    }

    uintptr_t scene_address = 0;
    if (!TryResolveCurrentGameplayScene(&scene_address) || scene_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Gameplay scene is not active.";
        }
        return false;
    }

    g_gameplay_keyboard_injection.pending_mouse_right_frames.fetch_add(
        frames,
        std::memory_order_acq_rel);
    constexpr std::uint32_t kInjectedMouseControlFrames = 3;
    g_gameplay_keyboard_injection.pending_injected_keyboard_control_frames.store(
        kInjectedMouseControlFrames,
        std::memory_order_release);
    Log(
        "Queued gameplay mouse-right hold. gameplay=" + HexString(scene_address) +
        " frames=" + std::to_string(frames));
    return true;
}

void ClearQueuedGameplayMouseLeft() {
    g_gameplay_keyboard_injection.pending_mouse_left_frames.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.last_mouse_left_hold_player_tick_generation.store(0, std::memory_order_release);
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
    g_gameplay_keyboard_injection.injected_mouse_left_active.store(true, std::memory_order_release);

    const auto input_state_address =
        g_gameplay_keyboard_injection.input_state_address.load(std::memory_order_acquire);
    const bool cleared_raw_mouse_left = ClearRawGameplayMouseLeft(input_state_address);

    uintptr_t gameplay_address = 0;
    if (TryResolveCurrentGameplayScene(&gameplay_address) && gameplay_address != 0) {
        const std::uint8_t released = 0;
        ProcessMemory::Instance().TryWriteField(gameplay_address, kGameplayCastIntentOffset, released);
    }
    Log(
        "Cleared queued gameplay mouse-left input. input_state=" +
        (input_state_address != 0 ? HexString(input_state_address) : std::string("0x00000000")) +
        " raw_mouse_left=" + std::to_string(cleared_raw_mouse_left ? 1 : 0));
}

void ClearQueuedGameplayMouseRight() {
    g_gameplay_keyboard_injection.pending_mouse_right_frames.store(
        0,
        std::memory_order_release);
    g_gameplay_keyboard_injection.last_mouse_right_hold_player_tick_generation.store(
        0,
        std::memory_order_release);
    g_gameplay_keyboard_injection.last_observed_mouse_right_down.store(
        false,
        std::memory_order_release);
    g_gameplay_keyboard_injection.injected_mouse_right_active.store(
        true,
        std::memory_order_release);

    const auto input_state_address =
        g_gameplay_keyboard_injection.input_state_address.load(
            std::memory_order_acquire);
    const bool cleared_raw_mouse_right =
        ClearRawGameplayMouseRight(input_state_address);
    Log(
        "Cleared queued gameplay mouse-right input. input_state=" +
        (input_state_address != 0
             ? HexString(input_state_address)
             : std::string("0x00000000")) +
        " raw_mouse_right=" +
        std::to_string(cleared_raw_mouse_right ? 1 : 0));
}

bool ClearLocalPlayerGameplayCastState(std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }

    ClearQueuedGameplayMouseLeft();
    ClearQueuedGameplayMouseRight();

    uintptr_t gameplay_address = 0;
    if (!TryResolveCurrentGameplayScene(&gameplay_address) || gameplay_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Gameplay scene is not active.";
        }
        return false;
    }

    uintptr_t actor_address = 0;
    if (!TryResolvePlayerActorForSlot(gameplay_address, 0, &actor_address) || actor_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Local player actor is not available.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    bool wrote = true;
    wrote = memory.TryWriteField<std::int32_t>(actor_address, kActorPrimarySkillIdOffset, 0) && wrote;
    wrote = memory.TryWriteField<std::int32_t>(actor_address, kActorPreviousSkillIdOffset, 0) && wrote;
    wrote = memory.TryWriteField<std::uint32_t>(actor_address, kActorPrimaryActionLatchE4Offset, 0) && wrote;
    wrote = memory.TryWriteField<std::uint32_t>(actor_address, kActorPrimaryActionLatchE8Offset, 0) && wrote;
    wrote = memory.TryWriteField<std::uint8_t>(actor_address, kActorPostGateActiveByteOffset, 0) && wrote;
    wrote = memory.TryWriteField<std::uint8_t>(
        actor_address,
        kActorSpellTargetGroupByteOffset,
        kTargetHandleGroupSentinel) && wrote;
    wrote = memory.TryWriteField<std::uint16_t>(
        actor_address,
        kActorSpellTargetSlotShortOffset,
        kTargetHandleSlotSentinel) && wrote;
    wrote = memory.TryWriteField<uintptr_t>(actor_address, kActorCurrentTargetActorOffset, 0) && wrote;
    wrote = memory.TryWriteField<std::int32_t>(actor_address, kActorCurrentTargetBucketDeltaOffset, 0) && wrote;

    uintptr_t selection_pointer = 0;
    if (!memory.TryReadField(
            actor_address,
            kActorAnimationSelectionStateOffset,
            &selection_pointer)) {
        if (error_message != nullptr) {
            *error_message = "Local player animation-selection field is not readable.";
        }
        return false;
    }

    if (selection_pointer != 0) {
        constexpr int kLocalCastStateSuppressedRetargetTicks = 60;
        wrote = memory.TryWriteField<std::uint8_t>(
            selection_pointer,
            kActorControlBrainTargetSlotOffset,
            kTargetHandleGroupSentinel) && wrote;
        wrote = memory.TryWriteField<std::uint16_t>(
            selection_pointer,
            kActorControlBrainTargetHandleOffset,
            kTargetHandleSlotSentinel) && wrote;
        wrote = memory.TryWriteField<std::int32_t>(
            selection_pointer,
            kActorControlBrainRetargetTicksOffset,
            kLocalCastStateSuppressedRetargetTicks) && wrote;
        wrote = memory.TryWriteField<std::int32_t>(
            selection_pointer,
            kActorControlBrainTargetCooldownTicksOffset,
            0) && wrote;
        wrote = memory.TryWriteField<std::int32_t>(
            selection_pointer,
            kActorControlBrainActionCooldownTicksOffset,
            0) && wrote;
        wrote = memory.TryWriteField<std::int32_t>(
            selection_pointer,
            kActorControlBrainActionBurstTicksOffset,
            0) && wrote;
        wrote = memory.TryWriteField<std::int32_t>(
            selection_pointer,
            kActorControlBrainHeadingLockTicksOffset,
            0) && wrote;
        wrote = memory.TryWriteField<float>(
            selection_pointer,
            kActorControlBrainMoveInputXOffset,
            0.0f) && wrote;
        wrote = memory.TryWriteField<float>(
            selection_pointer,
            kActorControlBrainMoveInputYOffset,
            0.0f) && wrote;
    }

    Log(
        "Cleared local player gameplay cast state. gameplay=" + HexString(gameplay_address) +
        " actor=" + HexString(actor_address) +
        " selection=" + HexString(selection_pointer) +
        " wrote=" + std::to_string(wrote ? 1 : 0));

    if (!wrote && error_message != nullptr) {
        *error_message = "One or more local player cast-state fields could not be cleared.";
    }
    return wrote;
}

bool QueueGameplayScancodePress(std::uint32_t scancode, std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!g_gameplay_keyboard_injection.initialized) {
        if (error_message != nullptr) {
            *error_message = "Gameplay keyboard injection is not initialized.";
        }
        return false;
    }
    if (scancode > 0xFF) {
        if (error_message != nullptr) {
            *error_message = "Scancode must be in the range 0..255.";
        }
        return false;
    }

    g_gameplay_keyboard_injection.pending_scancodes[scancode].fetch_add(1, std::memory_order_acq_rel);
    // Manual-spawner mode normally suppresses the local control-brain update
    // so idle test players cannot emit accidental primary casts.  A queued
    // keyboard edge is explicit test input and needs a brief control window of
    // its own; otherwise the edge is consumed but belt/menu actions never reach
    // the native dispatcher.  Store rather than accumulate so a fast producer
    // cannot leave manual mode unsuppressed indefinitely.
    constexpr std::uint32_t kInjectedKeyboardControlFrames = 3;
    g_gameplay_keyboard_injection.pending_injected_keyboard_control_frames.store(
        kInjectedKeyboardControlFrames,
        std::memory_order_release);
    return true;
}

bool QueueGameplayKeyPress(std::string_view binding_name, std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }

    uintptr_t absolute_global = 0;
    if (!TryResolveInjectedBindingGlobal(binding_name, &absolute_global)) {
        if (error_message != nullptr) {
            *error_message =
                "Unknown gameplay key binding. Use menu, inventory, skills, or belt_slot_1..belt_slot_8.";
        }
        return false;
    }

    std::uint32_t raw_binding_code = 0;
    if (!TryReadInjectedBindingCode(absolute_global, &raw_binding_code)) {
        if (error_message != nullptr) {
            *error_message = "Failed to read the live gameplay key binding.";
        }
        return false;
    }

    if (raw_binding_code > 0xFF) {
        if (error_message != nullptr) {
            *error_message =
                "The live gameplay binding is mouse-backed. Use sd.input.press_binding "
                "to dispatch the current binding exactly.";
        }
        return false;
    }

    return QueueGameplayScancodePress(raw_binding_code, error_message);
}

bool QueueGameplayBindingPress(
    std::string_view binding_name,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }

    uintptr_t absolute_global = 0;
    if (!TryResolveInjectedBindingGlobal(binding_name, &absolute_global)) {
        if (error_message != nullptr) {
            *error_message =
                "Unknown gameplay binding. Use menu, inventory, skills, or "
                "belt_slot_1..belt_slot_8.";
        }
        return false;
    }

    std::uint32_t raw_binding_code = 0;
    if (!TryReadInjectedBindingCode(absolute_global, &raw_binding_code)) {
        if (error_message != nullptr) {
            *error_message = "Failed to read the live gameplay binding.";
        }
        return false;
    }

    constexpr std::uint32_t kMouseLeftBindingCode = 0x200;
    constexpr std::uint32_t kMouseRightBindingCode = 0x201;
    if (raw_binding_code <= 0xFF) {
        return QueueGameplayScancodePress(raw_binding_code, error_message);
    }
    if (raw_binding_code == kMouseLeftBindingCode) {
        return QueueGameplayMouseLeftClick(error_message);
    }
    if (raw_binding_code == kMouseRightBindingCode) {
        return QueueGameplayMouseRightClick(error_message);
    }
    if (error_message != nullptr) {
        *error_message =
            "The live gameplay binding uses an unsupported mouse button code " +
            std::to_string(raw_binding_code) + ".";
    }
    return false;
}
