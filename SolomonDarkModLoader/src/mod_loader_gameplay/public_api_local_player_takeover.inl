void ClearLocalPlayerControlTakeoverInputState() {
    g_gameplay_keyboard_injection.pending_movement_x.store(
        0.0f,
        std::memory_order_release);
    g_gameplay_keyboard_injection.pending_movement_y.store(
        0.0f,
        std::memory_order_release);
    g_gameplay_keyboard_injection.pending_movement_frames.store(
        0,
        std::memory_order_release);
    g_gameplay_keyboard_injection.local_movement_intent_x.store(
        0.0f,
        std::memory_order_release);
    g_gameplay_keyboard_injection.local_movement_intent_y.store(
        0.0f,
        std::memory_order_release);
    g_gameplay_keyboard_injection.local_movement_intent_observed_ms.store(
        0,
        std::memory_order_release);
    g_gameplay_keyboard_injection.pending_injected_keyboard_control_frames.store(
        0,
        std::memory_order_release);
    for (auto& pending : g_gameplay_keyboard_injection.pending_scancodes) {
        pending.store(0, std::memory_order_release);
    }

    ClearQueuedGameplayMouseLeft();
    ClearQueuedGameplayMouseRight();
    g_gameplay_keyboard_injection.local_player_takeover_target_actor.store(
        0,
        std::memory_order_release);
    g_gameplay_keyboard_injection.local_player_takeover_target_x.store(
        0.0f,
        std::memory_order_release);
    g_gameplay_keyboard_injection.local_player_takeover_target_y.store(
        0.0f,
        std::memory_order_release);
    g_gameplay_keyboard_injection.local_player_takeover_target_valid.store(
        false,
        std::memory_order_release);
    g_gameplay_keyboard_injection.last_observed_mouse_left_down.store(
        false,
        std::memory_order_release);
    g_gameplay_keyboard_injection.last_observed_mouse_right_down.store(
        false,
        std::memory_order_release);
    g_gameplay_keyboard_injection.injected_mouse_left_active.store(
        false,
        std::memory_order_release);
    g_gameplay_keyboard_injection.injected_mouse_right_active.store(
        false,
        std::memory_order_release);

    uintptr_t gameplay_address = 0;
    if (!TryResolveCurrentGameplayScene(&gameplay_address) ||
        gameplay_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    const std::uint8_t released = 0;
    (void)memory.TryWriteField(
        gameplay_address,
        kGameplayCastIntentOffset,
        released);
    (void)memory.TryWriteField(
        gameplay_address,
        kGameplayLocalMovementInputXOffset,
        0.0f);
    (void)memory.TryWriteField(
        gameplay_address,
        kGameplayLocalMovementInputYOffset,
        0.0f);
    for (int buffer_index = 0;
         buffer_index < kGameplayInputBufferCount;
         ++buffer_index) {
        const auto left_offset = static_cast<std::size_t>(
            buffer_index * kGameplayInputBufferStride +
            kGameplayMouseLeftButtonOffset);
        const auto right_offset = static_cast<std::size_t>(
            buffer_index * kGameplayInputBufferStride +
            kGameplayMouseRightButtonOffset);
        (void)memory.TryWriteField(
            gameplay_address,
            left_offset,
            released);
        (void)memory.TryWriteField(
            gameplay_address,
            right_offset,
            released);
    }
    uintptr_t actor_address = 0;
    if (TryResolvePlayerActorForSlot(
            gameplay_address,
            0,
            &actor_address) &&
        actor_address != 0) {
        std::string ignored_error;
        (void)ClearWizardActorGameplayCastState(
            actor_address,
            &ignored_error);
    }
}

bool EnsureLocalPlayerControlBrainForTakeover(
    std::string* error_message) {
    uintptr_t gameplay_address = 0;
    uintptr_t actor_address = 0;
    if (!TryResolveCurrentGameplayScene(&gameplay_address) ||
        gameplay_address == 0 ||
        !TryResolvePlayerActorForSlot(
            gameplay_address,
            0,
            &actor_address) ||
        actor_address == 0) {
        if (error_message != nullptr) {
            *error_message =
                "Local player actor is not available for takeover.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto control_brain_size =
        kActorControlBrainMoveInputYOffset +
        sizeof(float);
    const auto control_brain_is_live =
        [&](uintptr_t control_brain_address) {
            return
                control_brain_address != 0 &&
                memory.IsReadableRange(
                    control_brain_address,
                    control_brain_size) &&
                memory.IsWritableRange(
                    control_brain_address,
                    control_brain_size);
        };

    uintptr_t control_brain_address = 0;
    if (memory.TryReadField(
            actor_address,
            kActorAnimationSelectionStateOffset,
            &control_brain_address) &&
        control_brain_is_live(control_brain_address)) {
        return true;
    }

    const auto initialize_address =
        memory.ResolveGameAddressOrZero(
            kPlayerActorInitializeControlBrain);
    DWORD exception_code = 0;
    if (initialize_address == 0 ||
        !CallPlayerActorInitializeControlBrainSafe(
            initialize_address,
            actor_address,
            &exception_code) ||
        !memory.TryReadField(
            actor_address,
            kActorAnimationSelectionStateOffset,
            &control_brain_address) ||
        !control_brain_is_live(control_brain_address)) {
        if (error_message != nullptr) {
            *error_message =
                "Stock local control brain could not be initialized";
            if (exception_code != 0) {
                *error_message +=
                    " (SEH 0x" +
                    HexString(exception_code) +
                    ")";
            }
            *error_message += ".";
        }
        return false;
    }

    Log(
        "[lua] initialized missing stock local control brain for takeover. "
        "actor=" +
        HexString(actor_address) +
        " control_brain=" +
        HexString(control_brain_address));
    return true;
}

bool SetLocalPlayerControlTakeover(
    std::string_view owner_mod_id,
    bool enabled,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (owner_mod_id.empty()) {
        if (error_message != nullptr) {
            *error_message =
                "Local player control takeover requires a mod owner.";
        }
        return false;
    }
    if (!g_gameplay_keyboard_injection.initialized) {
        if (error_message != nullptr) {
            *error_message =
                "Gameplay input control is not initialized.";
        }
        return false;
    }

    auto& takeover_mutex =
        g_gameplay_keyboard_injection.local_player_takeover_mutex;
    {
        std::lock_guard<std::mutex> lock(takeover_mutex);
        const auto& current_owner =
            g_gameplay_keyboard_injection
                .local_player_takeover_owner_mod_id;
        const bool active =
            g_gameplay_keyboard_injection
                .local_player_takeover_active.load(
                    std::memory_order_acquire);
        if (!current_owner.empty() &&
            current_owner != owner_mod_id) {
            if (error_message != nullptr) {
                *error_message =
                    "Local player controls are already owned by mod " +
                    current_owner + ".";
            }
            return false;
        }
        if (enabled && active) {
            return true;
        }
        if (!enabled && !active && current_owner.empty()) {
            return true;
        }
        if (!enabled) {
            g_gameplay_keyboard_injection
                .local_player_takeover_active.store(
                    false,
                    std::memory_order_release);
        }
    }

    if (enabled &&
        !EnsureLocalPlayerControlBrainForTakeover(
            error_message)) {
        return false;
    }
    ClearLocalPlayerControlTakeoverInputState();

    {
        std::lock_guard<std::mutex> lock(takeover_mutex);
        if (enabled) {
            g_gameplay_keyboard_injection
                .local_player_takeover_owner_mod_id.assign(
                    owner_mod_id.data(),
                    owner_mod_id.size());
            g_gameplay_keyboard_injection
                .local_player_takeover_active.store(
                    true,
                    std::memory_order_release);
            Log(
                "[lua] local player control takeover enabled. owner=" +
                g_gameplay_keyboard_injection
                    .local_player_takeover_owner_mod_id);
        } else {
            g_gameplay_keyboard_injection
                .local_player_takeover_owner_mod_id.clear();
            Log(
                "[lua] local player control takeover released. owner=" +
                std::string(owner_mod_id));
        }
    }
    return true;
}

bool IsLocalPlayerControlTakeoverActive() {
    return g_gameplay_keyboard_injection
        .local_player_takeover_active.load(
            std::memory_order_acquire);
}

bool TryGetLocalPlayerControlTakeoverTarget(
    uintptr_t* target_actor_address,
    float* target_x,
    float* target_y) {
    if (target_actor_address == nullptr ||
        target_x == nullptr ||
        target_y == nullptr) {
        return false;
    }
    *target_actor_address = 0;
    *target_x = 0.0f;
    *target_y = 0.0f;
    if (!IsLocalPlayerControlTakeoverActive() ||
        !g_gameplay_keyboard_injection
             .local_player_takeover_target_valid.load(
                 std::memory_order_acquire)) {
        return false;
    }

    const auto actor =
        g_gameplay_keyboard_injection
            .local_player_takeover_target_actor.load(
                std::memory_order_acquire);
    const auto x =
        g_gameplay_keyboard_injection
            .local_player_takeover_target_x.load(
                std::memory_order_acquire);
    const auto y =
        g_gameplay_keyboard_injection
            .local_player_takeover_target_y.load(
                std::memory_order_acquire);
    if (actor == 0 ||
        !std::isfinite(x) ||
        !std::isfinite(y)) {
        return false;
    }
    *target_actor_address = actor;
    *target_x = x;
    *target_y = y;
    return true;
}

bool ApplyPinnedLocalPlayerControlTakeoverTarget(
    uintptr_t actor_address) {
    if (!IsActorCurrentLocalPlayerSlotZero(actor_address)) {
        return false;
    }

    uintptr_t target_actor_address = 0;
    float target_x = 0.0f;
    float target_y = 0.0f;
    if (!TryGetLocalPlayerControlTakeoverTarget(
            &target_actor_address,
            &target_x,
            &target_y)) {
        return false;
    }

    uintptr_t selection_pointer = 0;
    (void)ProcessMemory::Instance().TryReadField(
        actor_address,
        kActorAnimationSelectionStateOffset,
        &selection_pointer);
    (void)ApplyLocalPlayerControlTakeoverPrimarySelection(
        actor_address);
    return ApplyManualSpawnerPrimaryTargetState(
        actor_address,
        selection_pointer,
        target_actor_address);
}

bool SetLocalPlayerControlTakeoverTarget(
    std::string_view owner_mod_id,
    uintptr_t target_actor_address,
    float target_x,
    float target_y,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (owner_mod_id.empty() ||
        target_actor_address == 0 ||
        !std::isfinite(target_x) ||
        !std::isfinite(target_y)) {
        if (error_message != nullptr) {
            *error_message =
                "A live target actor and finite world position are required.";
        }
        return false;
    }
    if (!IsManualSpawnerPrimaryTargetActor(
            target_actor_address)) {
        if (error_message != nullptr) {
            *error_message =
                "The local takeover target is not a live arena actor.";
        }
        return false;
    }
    {
        std::lock_guard<std::mutex> lock(
            g_gameplay_keyboard_injection
                .local_player_takeover_mutex);
        if (!g_gameplay_keyboard_injection
                 .local_player_takeover_active.load(
                     std::memory_order_acquire) ||
            g_gameplay_keyboard_injection
                    .local_player_takeover_owner_mod_id !=
                owner_mod_id) {
            if (error_message != nullptr) {
                *error_message =
                    "The calling mod does not own local player controls.";
            }
            return false;
        }
    }

    g_gameplay_keyboard_injection
        .local_player_takeover_target_actor.store(
            target_actor_address,
            std::memory_order_release);
    g_gameplay_keyboard_injection
        .local_player_takeover_target_x.store(
            target_x,
            std::memory_order_release);
    g_gameplay_keyboard_injection
        .local_player_takeover_target_y.store(
            target_y,
            std::memory_order_release);
    g_gameplay_keyboard_injection
        .local_player_takeover_target_valid.store(
            true,
            std::memory_order_release);

    uintptr_t gameplay_address = 0;
    uintptr_t actor_address = 0;
    if (TryResolveCurrentGameplayScene(
            &gameplay_address) &&
        gameplay_address != 0 &&
        TryResolvePlayerActorForSlot(
            gameplay_address,
            0,
            &actor_address) &&
        actor_address != 0) {
        (void)ApplyPinnedLocalPlayerControlTakeoverTarget(
            actor_address);
    }
    return true;
}

bool TryGetLocalPlayerControlTakeoverState(
    SDModLocalPlayerControlTakeoverState* state) {
    if (state == nullptr) {
        return false;
    }
    *state = SDModLocalPlayerControlTakeoverState{};
    state->active =
        IsLocalPlayerControlTakeoverActive();
    {
        std::lock_guard<std::mutex> lock(
            g_gameplay_keyboard_injection
                .local_player_takeover_mutex);
        state->owner_mod_id =
            g_gameplay_keyboard_injection
                .local_player_takeover_owner_mod_id;
    }
    state->target_actor_address =
        g_gameplay_keyboard_injection
            .local_player_takeover_target_actor.load(
                std::memory_order_acquire);
    state->target_x =
        g_gameplay_keyboard_injection
            .local_player_takeover_target_x.load(
                std::memory_order_acquire);
    state->target_y =
        g_gameplay_keyboard_injection
            .local_player_takeover_target_y.load(
                std::memory_order_acquire);
    state->target_valid =
        g_gameplay_keyboard_injection
            .local_player_takeover_target_valid.load(
                std::memory_order_acquire);
    state->pending_movement_x =
        g_gameplay_keyboard_injection
            .pending_movement_x.load(
                std::memory_order_acquire);
    state->pending_movement_y =
        g_gameplay_keyboard_injection
            .pending_movement_y.load(
                std::memory_order_acquire);
    state->pending_movement_frames =
        g_gameplay_keyboard_injection
            .pending_movement_frames.load(
                std::memory_order_acquire);
    state->pending_mouse_left_frames =
        g_gameplay_keyboard_injection
            .pending_mouse_left_frames.load(
                std::memory_order_acquire);
    state->pending_mouse_right_frames =
        g_gameplay_keyboard_injection
            .pending_mouse_right_frames.load(
                std::memory_order_acquire);
    state->pending_native_control_frames =
        g_gameplay_keyboard_injection
            .pending_injected_keyboard_control_frames.load(
                std::memory_order_acquire);
    std::uint64_t pending_scancodes = 0;
    for (const auto& pending :
         g_gameplay_keyboard_injection.pending_scancodes) {
        pending_scancodes +=
            pending.load(std::memory_order_acquire);
    }
    state->pending_scancode_count =
        static_cast<std::uint32_t>(
            (std::min)(
                pending_scancodes,
                static_cast<std::uint64_t>(
                    (std::numeric_limits<std::uint32_t>::max)())));

    uintptr_t gameplay_address = 0;
    if (TryResolveCurrentGameplayScene(
            &gameplay_address) &&
        gameplay_address != 0) {
        auto& memory = ProcessMemory::Instance();
        (void)memory.TryReadField(
            gameplay_address,
            kGameplayLocalMovementInputXOffset,
            &state->movement_input_x);
        (void)memory.TryReadField(
            gameplay_address,
            kGameplayLocalMovementInputYOffset,
            &state->movement_input_y);
        (void)memory.TryReadField(
            gameplay_address,
            kGameplayCastIntentOffset,
            &state->cast_intent);
        uintptr_t local_actor_address = 0;
        (void)TryResolvePlayerActorForSlot(
            gameplay_address,
            0,
            &local_actor_address);
        if (state->active) {
            state->actor_address = local_actor_address;
        }
        if (local_actor_address != 0) {
            (void)memory.TryReadField(
                local_actor_address,
                kActorPrimarySkillIdOffset,
                &state->primary_skill_id);
            (void)memory.TryReadField(
                local_actor_address,
                kActorPreviousSkillIdOffset,
                &state->previous_skill_id);
            (void)memory.TryReadField(
                local_actor_address,
                kActorCurrentTargetActorOffset,
                &state->current_target_actor_address);
            uintptr_t selection_pointer = 0;
            if (memory.TryReadField(
                    local_actor_address,
                    kActorAnimationSelectionStateOffset,
                    &selection_pointer) &&
                selection_pointer != 0) {
                (void)memory.TryReadField(
                    selection_pointer,
                    kActorControlBrainMoveInputXOffset,
                    &state->control_brain_move_x);
                (void)memory.TryReadField(
                    selection_pointer,
                    kActorControlBrainMoveInputYOffset,
                    &state->control_brain_move_y);
            }
        }
    }

    constexpr float kCleanInputEpsilon = 0.0001f;
    state->clean =
        !state->active &&
        state->owner_mod_id.empty() &&
        state->actor_address == 0 &&
        !state->target_valid &&
        state->target_actor_address == 0 &&
        state->pending_movement_frames == 0 &&
        state->pending_mouse_left_frames == 0 &&
        state->pending_mouse_right_frames == 0 &&
        state->pending_scancode_count == 0 &&
        state->pending_native_control_frames == 0 &&
        std::abs(state->pending_movement_x) <=
            kCleanInputEpsilon &&
        std::abs(state->pending_movement_y) <=
            kCleanInputEpsilon;
    return true;
}

bool ClearLocalPlayerControlTakeoverForMod(
    std::string_view owner_mod_id) {
    {
        std::lock_guard<std::mutex> lock(
            g_gameplay_keyboard_injection
                .local_player_takeover_mutex);
        if (owner_mod_id.empty() ||
            g_gameplay_keyboard_injection
                    .local_player_takeover_owner_mod_id !=
                owner_mod_id) {
            return false;
        }
    }
    std::string ignored_error;
    return SetLocalPlayerControlTakeover(
        owner_mod_id,
        false,
        &ignored_error);
}
