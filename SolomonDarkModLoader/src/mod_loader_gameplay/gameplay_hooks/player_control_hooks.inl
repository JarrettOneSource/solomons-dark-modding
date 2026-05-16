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

    auto& memory = ProcessMemory::Instance();
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
    if (log_this) {
        Log(
            "[bots] pure_primary_start exit actor=" + HexString(actor_address) +
            " bot_id=" + std::to_string(bot_id) +
            " standalone_slot_owner_context={" + slot_owner_context + "}" +
            " startup={" + DescribeGameplaySlotCastStartupWindow(actor_address) + "}");
    }
}
