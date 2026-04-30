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
                    const auto origin_x =
                        binding->stock_tick_facing_origin_valid
                            ? binding->stock_tick_facing_origin_x
                            : memory.ReadFieldOr<float>(actor_address, kActorPositionXOffset, 0.0f);
                    const auto origin_y =
                        binding->stock_tick_facing_origin_valid
                            ? binding->stock_tick_facing_origin_y
                            : memory.ReadFieldOr<float>(actor_address, kActorPositionYOffset, 0.0f);
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

    const auto selection_pointer =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorAnimationSelectionStateOffset, 0);
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
        *x = memory.ReadValueOr<float>(address, 0.0f);
        *y = memory.ReadValueOr<float>(address + sizeof(float), 0.0f);
        return true;
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
            " sel_ptr=" + HexString(selection_pointer) +
            " sel_group=" +
                HexString(selection_pointer != 0 ? memory.ReadValueOr<std::uint8_t>(selection_pointer + 0x4, 0xFF) : 0xFF) +
            " sel_slot=" +
                HexString(selection_pointer != 0 ? memory.ReadValueOr<std::uint16_t>(selection_pointer + 0x6, 0xFFFF) : 0xFFFF) +
            " sel_t8=" +
                std::to_string(selection_pointer != 0 ? memory.ReadValueOr<std::int32_t>(selection_pointer + 0x8, 0) : 0) +
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
            0x04,
            selection_target_group_seed);
        (void)memory.TryWriteField<std::uint16_t>(
            selection_pointer,
            0x06,
            selection_target_slot_seed);
        (void)memory.TryWriteField<std::int32_t>(
            selection_pointer,
            0x08,
            selection_target_hold_ticks);
        (void)memory.TryWriteField<std::int32_t>(selection_pointer, 0x0C, 0);
        (void)memory.TryWriteField<std::int32_t>(selection_pointer, 0x10, 0);
        (void)memory.TryWriteField<std::int32_t>(selection_pointer, 0x14, 0);
    };

    const auto apply_face_control = [&]() {
        if (!face_control_active || !have_face_vector) {
            return;
        }
        (void)write_vector2(param3, face_vector_x, face_vector_y);
        ApplyWizardActorFacingState(actor_address, face_heading);
        if (native_target_control_active && startup && selection_pointer != 0) {
            // The stock pure-primary startup gate needs a non-zero movement
            // vector. Use the follow lane while moving and only fall back to
            // attack-facing when idle.
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

    // Stock attack/cast code consumes the face lane during its own update, so
    // provide the current target-facing vector before the original runs. Re-pin
    // after the original too because stock may clear the cached target fields.
    seed_selection_target();
    apply_face_control();
    original(self, param2, param3);

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
    apply_face_control();

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

void __fastcall HookPurePrimarySpellStart(void* self, void* /*unused_edx*/) {
    const auto original =
        GetX86HookTrampoline<PlayerActorNoArgMethodFn>(g_gameplay_keyboard_injection.pure_primary_spell_start_hook);
    if (original == nullptr) {
        return;
    }

    const auto actor_address = reinterpret_cast<uintptr_t>(self);
    bool log_this = false;
    std::uint64_t bot_id = 0;
    bool startup = false;
    bool apply_local_selection_shim = false;
    bool local_player = false;
    uintptr_t fallback_slot_obj = 0;
    {
        std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
        if (auto* binding = FindParticipantEntityForActor(actor_address);
            binding != nullptr &&
            (IsGameplaySlotWizardKind(binding->kind) ||
             IsStandaloneWizardKind(binding->kind))) {
            SyncWizardBotMovementIntent(binding);
            log_this = true;
            bot_id = binding->bot_id;
            startup = binding->ongoing_cast.startup_in_progress;
            apply_local_selection_shim =
                binding->ongoing_cast.active &&
                binding->ongoing_cast.lane ==
                    ParticipantEntityBinding::OngoingCastState::Lane::PurePrimary;
            if (apply_local_selection_shim) {
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

    auto& memory = ProcessMemory::Instance();
    uintptr_t pure_primary_slot_sink_inner = 0;
    uintptr_t pure_primary_attachment_item = 0;
    std::uint32_t pure_primary_saved_slot_item = 0;
    bool pure_primary_slot_item_shim_applied = false;
    if (apply_local_selection_shim) {
        pure_primary_attachment_item = ResolveActorAttachmentLaneItem(actor_address);
        {
            std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
            if (auto* binding = FindParticipantEntityForActor(actor_address);
                binding != nullptr &&
                (IsGameplaySlotWizardKind(binding->kind) ||
                 IsStandaloneWizardKind(binding->kind))) {
                if (pure_primary_attachment_item != 0) {
                    binding->ongoing_cast.pure_primary_item_sink_fallback =
                        pure_primary_attachment_item;
                } else {
                    pure_primary_attachment_item =
                        binding->ongoing_cast.pure_primary_item_sink_fallback;
                }
            }
        }
    }

    PurePrimaryLocalActorWindowShim pure_primary_actor_window_shim{};
    if (apply_local_selection_shim) {
        pure_primary_actor_window_shim = EnterPurePrimaryLocalActorWindow(actor_address);
        std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
        if (auto* binding = FindParticipantEntityForActor(actor_address);
            binding != nullptr &&
            (IsGameplaySlotWizardKind(binding->kind) ||
             IsStandaloneWizardKind(binding->kind))) {
            SyncWizardBotMovementIntent(binding);
            (void)RefreshAndApplyWizardBindingFacingState(binding, actor_address);
        }
    }

    if (apply_local_selection_shim) {
        const auto gameplay_global = memory.ReadValueOr<uintptr_t>(
            memory.ResolveGameAddressOrZero(0x0081c264),
            0);
        const auto shim_slot_obj =
            gameplay_global != 0
                ? gameplay_global + 0x1410
                : 0;
        const auto fallback_slot_obj30 =
            shim_slot_obj != 0 &&
                    memory.IsReadableRange(shim_slot_obj + 0x30, sizeof(uintptr_t))
                ? memory.ReadValueOr<uintptr_t>(shim_slot_obj + 0x30, 0)
                : 0;
        pure_primary_slot_sink_inner =
            fallback_slot_obj30 != 0 &&
                    memory.IsReadableRange(fallback_slot_obj30, sizeof(uintptr_t))
                ? memory.ReadValueOr<uintptr_t>(fallback_slot_obj30, 0)
                : 0;
        if (pure_primary_attachment_item != 0 &&
            pure_primary_slot_sink_inner != 0 &&
            memory.IsReadableRange(pure_primary_slot_sink_inner + 4, sizeof(std::uint32_t))) {
            pure_primary_saved_slot_item =
                memory.ReadValueOr<std::uint32_t>(pure_primary_slot_sink_inner + 4, 0);
            pure_primary_slot_item_shim_applied =
                memory.TryWriteValue<std::uint32_t>(
                    pure_primary_slot_sink_inner + 4,
                    static_cast<std::uint32_t>(pure_primary_attachment_item));
        }
    }

    if (log_this) {
        const auto actor_1fc = memory.ReadFieldOr<std::uint32_t>(actor_address, 0x1FC, 0);
        const auto actor_1fc_ptr = static_cast<uintptr_t>(actor_1fc);
        const auto actor_1fc_obj30 =
            actor_1fc_ptr != 0 && memory.IsReadableRange(actor_1fc_ptr + 0x30, sizeof(uintptr_t))
                ? memory.ReadValueOr<uintptr_t>(actor_1fc_ptr + 0x30, 0)
                : 0;
        const auto actor_1fc_inner =
            actor_1fc_obj30 != 0 && memory.IsReadableRange(actor_1fc_obj30, sizeof(uintptr_t))
                ? memory.ReadValueOr<uintptr_t>(actor_1fc_obj30, 0)
                : 0;
        const auto actor_1fc_plus4 =
            actor_1fc_inner != 0 && memory.IsReadableRange(actor_1fc_inner + 4, sizeof(std::uint32_t))
                ? memory.ReadValueOr<std::uint32_t>(actor_1fc_inner + 4, 0)
                : 0;
        const auto actor_1fc_plus4_type =
            actor_1fc_plus4 != 0 && memory.IsReadableRange(static_cast<uintptr_t>(actor_1fc_plus4) + 8, sizeof(std::uint32_t))
                ? memory.ReadValueOr<std::uint32_t>(static_cast<uintptr_t>(actor_1fc_plus4) + 8, 0)
                : 0;
        std::uint8_t effective_slot_byte =
            memory.ReadFieldOr<std::uint8_t>(actor_address, kActorSlotOffset, 0xFF);
        if (apply_local_selection_shim) {
            effective_slot_byte = 0;
        }
        const auto gameplay_global =
            ProcessMemory::Instance().ReadValueOr<uintptr_t>(
                ProcessMemory::Instance().ResolveGameAddressOrZero(0x0081c264),
                0);
        fallback_slot_obj =
            gameplay_global != 0
                ? gameplay_global +
                    static_cast<std::size_t>(effective_slot_byte) * 0x64 +
                    0x1410
                : 0;
        const auto fallback_slot_obj30 =
            fallback_slot_obj != 0 && memory.IsReadableRange(fallback_slot_obj + 0x30, sizeof(uintptr_t))
                ? memory.ReadValueOr<uintptr_t>(fallback_slot_obj + 0x30, 0)
                : 0;
        const auto fallback_slot_inner =
            fallback_slot_obj30 != 0 && memory.IsReadableRange(fallback_slot_obj30, sizeof(uintptr_t))
                ? memory.ReadValueOr<uintptr_t>(fallback_slot_obj30, 0)
                : 0;
        const auto fallback_slot_plus4 =
            fallback_slot_inner != 0 && memory.IsReadableRange(fallback_slot_inner + 4, sizeof(std::uint32_t))
                ? memory.ReadValueOr<std::uint32_t>(fallback_slot_inner + 4, 0)
                : 0;
        const auto fallback_slot_plus4_type =
            fallback_slot_plus4 != 0 && memory.IsReadableRange(static_cast<uintptr_t>(fallback_slot_plus4) + 8, sizeof(std::uint32_t))
                ? memory.ReadValueOr<std::uint32_t>(static_cast<uintptr_t>(fallback_slot_plus4) + 8, 0)
                : 0;
        Log(
            "[bots] pure_primary_start enter actor=" + HexString(actor_address) +
            " bot_id=" + std::to_string(bot_id) +
            " startup=" + std::to_string(startup ? 1 : 0) +
            " local_sel_shim=" + std::to_string(apply_local_selection_shim ? 1 : 0) +
            " local_window_shim=" + std::to_string(pure_primary_actor_window_shim.active ? 1 : 0) +
            " actor1fc=" + HexString(actor_1fc_ptr) +
            " actor1fc30=" + HexString(actor_1fc_obj30) +
            " actor1fc_inner=" + HexString(actor_1fc_inner) +
            " actor1fc_plus4=" + HexString(actor_1fc_plus4) +
            " actor1fc_plus4_type=" + HexString(actor_1fc_plus4_type) +
            " fallback_slot_byte=" + HexString(effective_slot_byte) +
            " fallback_slot_obj=" + HexString(fallback_slot_obj) +
            " fallback_slot_obj30=" + HexString(fallback_slot_obj30) +
            " fallback_slot_inner=" + HexString(fallback_slot_inner) +
            " fallback_slot_plus4=" + HexString(fallback_slot_plus4) +
            " fallback_slot_plus4_type=" + HexString(fallback_slot_plus4_type) +
            " slot_item_shim=" + std::to_string(pure_primary_slot_item_shim_applied ? 1 : 0) +
            " slot_item_saved=" + HexString(pure_primary_saved_slot_item) +
            " attachment_item=" + HexString(pure_primary_attachment_item) +
            " startup={" + DescribeGameplaySlotCastStartupWindow(actor_address) + "}");
    }
    SpellDispatchProbeState saved_probe = g_spell_dispatch_probe;
    if (log_this) {
        g_spell_dispatch_probe.depth = saved_probe.depth + 1;
        g_spell_dispatch_probe.actor_address = actor_address;
        g_spell_dispatch_probe.bot_id = bot_id;
        g_spell_dispatch_probe.pure_primary_item_sink_fallback =
            pure_primary_attachment_item;
        g_spell_dispatch_probe.startup = startup;
        g_spell_dispatch_probe.pure_primary_startup = apply_local_selection_shim;
        g_spell_dispatch_probe.local_player = local_player;
    }
    original(self);
    if (pure_primary_slot_item_shim_applied) {
        (void)memory.TryWriteValue<std::uint32_t>(
            pure_primary_slot_sink_inner + 4,
            pure_primary_saved_slot_item);
    }
    g_spell_dispatch_probe = saved_probe;
    if (apply_local_selection_shim) {
        std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
        if (auto* binding = FindParticipantEntityForActor(actor_address);
            binding != nullptr &&
            (IsGameplaySlotWizardKind(binding->kind) ||
             IsStandaloneWizardKind(binding->kind))) {
            (void)RefreshAndApplyWizardBindingFacingState(binding, actor_address);
        }
    }
    if (log_this) {
        Log(
            "[bots] pure_primary_start exit actor=" + HexString(actor_address) +
            " bot_id=" + std::to_string(bot_id) +
            " startup={" + DescribeGameplaySlotCastStartupWindow(actor_address) + "}");
    }
    LeavePurePrimaryLocalActorWindow(actor_address, pure_primary_actor_window_shim);
}
