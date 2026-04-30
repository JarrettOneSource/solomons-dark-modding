bool StartPendingBotCastRequest(
    const BotCastProcessingContext& cast_context,
    uintptr_t dispatcher_address,
    std::string* error_message) {
    auto* binding = cast_context.binding;
    auto& memory = *cast_context.memory;
    const auto actor_address = cast_context.actor_address;
    const auto cleanup_address = cast_context.cleanup_address;

    // --- New-request consumption path ----------------------------------------
    multiplayer::BotCastRequest request{};
    if (!multiplayer::ConsumePendingBotCast(binding->bot_id, &request)) {
        return false;
    }
    const auto queued_target_actor_address = request.target_actor_address;

    if (request.skill_id <= 0) {
        (void)multiplayer::FinishBotAttack(
            binding->bot_id,
            true,
            memory.ReadFieldOr<float>(actor_address, kActorHeadingOffset, 0.0f),
            true);
        if (error_message != nullptr) {
            *error_message = "cast has no skill_id";
        }
        return false;
    }

    float aim_heading = 0.0f;
    bool have_aim_heading = false;
    float aim_target_x = 0.0f;
    float aim_target_y = 0.0f;
    bool have_aim_target = false;
    if (request.has_aim_target) {
        const auto actor_x =
            memory.ReadFieldOr<float>(actor_address, kActorPositionXOffset, 0.0f);
        const auto actor_y =
            memory.ReadFieldOr<float>(actor_address, kActorPositionYOffset, 0.0f);
        const auto dx = request.aim_target_x - actor_x;
        const auto dy = request.aim_target_y - actor_y;
        if ((dx * dx) + (dy * dy) > 0.0001f) {
            aim_heading = std::atan2(dy, dx) * kBotCastRadiansToDegrees + 90.0f;
            if (aim_heading < 0.0f) {
                aim_heading += 360.0f;
            } else if (aim_heading >= 360.0f) {
                aim_heading -= 360.0f;
            }
            have_aim_heading = true;
        }
        aim_target_x = request.aim_target_x;
        aim_target_y = request.aim_target_y;
        have_aim_target = true;
    } else if (request.has_aim_angle && std::isfinite(request.aim_angle)) {
        aim_heading = request.aim_angle;
        have_aim_heading = true;
    }
    auto effective_target_actor_address =
        queued_target_actor_address != 0
            ? queued_target_actor_address
            : binding->facing_target_actor_address;
    if (effective_target_actor_address != 0) {
        float live_target_x = 0.0f;
        float live_target_y = 0.0f;
        float live_target_heading = 0.0f;
        if (TryComputeActorAimTowardTarget(
                actor_address,
                effective_target_actor_address,
                &live_target_heading,
                &live_target_x,
                &live_target_y)) {
            binding->facing_target_actor_address = effective_target_actor_address;
            aim_heading = live_target_heading;
            have_aim_heading = true;
            aim_target_x = live_target_x;
            aim_target_y = live_target_y;
            have_aim_target = true;
        } else if (effective_target_actor_address != binding->facing_target_actor_address &&
                   binding->facing_target_actor_address != 0 &&
                   TryComputeActorAimTowardTarget(
                       actor_address,
                       binding->facing_target_actor_address,
                       &live_target_heading,
                       &live_target_x,
                       &live_target_y)) {
            effective_target_actor_address = binding->facing_target_actor_address;
            binding->facing_target_actor_address = effective_target_actor_address;
            aim_heading = live_target_heading;
            have_aim_heading = true;
            aim_target_x = live_target_x;
            aim_target_y = live_target_y;
            have_aim_target = true;
        }
    }

    const auto heading_before =
        memory.ReadFieldOr<float>(actor_address, kActorHeadingOffset, 0.0f);
    const auto aim_x_before =
        memory.ReadFieldOr<float>(actor_address, kActorAimTargetXOffset, 0.0f);
    const auto aim_y_before =
        memory.ReadFieldOr<float>(actor_address, kActorAimTargetYOffset, 0.0f);
    const auto aim_aux0_before =
        memory.ReadFieldOr<std::uint32_t>(actor_address, kActorAimTargetAux0Offset, 0);
    const auto aim_aux1_before =
        memory.ReadFieldOr<std::uint32_t>(actor_address, kActorAimTargetAux1Offset, 0);
    const auto spread_before =
        memory.ReadFieldOr<std::uint8_t>(actor_address, kActorCastSpreadModeByteOffset, 0);

    if (have_aim_heading) {
        ApplyWizardActorFacingState(actor_address, aim_heading);
    }
    if (have_aim_target) {
        (void)memory.TryWriteField(actor_address, kActorAimTargetXOffset, aim_target_x);
        (void)memory.TryWriteField(actor_address, kActorAimTargetYOffset, aim_target_y);
        (void)memory.TryWriteField<std::uint32_t>(actor_address, kActorAimTargetAux0Offset, 0);
        (void)memory.TryWriteField<std::uint32_t>(actor_address, kActorAimTargetAux1Offset, 0);
    }
    // Force non-spread path in FUN_0052BB60 so projectile copies actor aim
    // fields (0x2a8/0x2ac) into projectile target (0x168/0x16c) instead of
    // using a random spawn angle.
    (void)memory.TryWriteField<std::uint8_t>(actor_address, kActorCastSpreadModeByteOffset, 0);

    (void)memory.TryWriteField<std::int32_t>(
        actor_address, kActorPrimarySkillIdOffset, request.skill_id);

    const auto active_cast_group_before =
        memory.ReadFieldOr<std::uint8_t>(actor_address, kActorActiveCastGroupByteOffset, 0);
    const auto active_cast_slot_before =
        memory.ReadFieldOr<std::uint16_t>(actor_address, kActorActiveCastSlotShortOffset, 0);
    // If a prior cast left the handle cached (e.g. SEH abort), release it
    // properly before starting init so we don't leak a world-storage slot.
    if (active_cast_group_before != kBotCastActorActiveCastGroupSentinel) {
        DWORD prior_cleanup_seh = 0;
        bool prior_cleanup_ok = false;
        InvokeBotCastWithLocalPlayerSlot(cast_context, [&] {
            prior_cleanup_ok = CallCastActiveHandleCleanupSafe(
                cleanup_address, actor_address, &prior_cleanup_seh);
        });
        if (!prior_cleanup_ok) {
            (void)memory.TryWriteField<std::uint8_t>(
                actor_address, kActorActiveCastGroupByteOffset, kBotCastActorActiveCastGroupSentinel);
            (void)memory.TryWriteField<std::uint16_t>(
                actor_address, kActorActiveCastSlotShortOffset, kBotCastActorActiveCastSlotSentinel);
        }
    }

    DWORD exception_code = 0;
    bool dispatched = false;
    InvokeBotCastWithLocalPlayerSlot(cast_context, [&] {
        dispatched = CallSpellCastDispatcherSafe(
            dispatcher_address, actor_address, &exception_code);
    });

    const auto active_group_post =
        memory.ReadFieldOr<std::uint8_t>(actor_address, kActorActiveCastGroupByteOffset, 0);

    // Diagnostic: immediately after dispatcher returns and before any cleanup,
    // snapshot the spell_obj registered at (world+0x500, group*0x800+slot)*4 so
    // we can see what the handler actually produced. Fragment-spawn gate at
    // FUN_00545360:215 requires spell_obj[0x22C] > 1. FUN_0052B150 can collapse
    // it to 1 in init, which silently kills the spawn loop.
    {
        const auto group_post_diag = active_group_post;
        const auto slot_post_diag =
            memory.ReadFieldOr<std::uint16_t>(actor_address, kActorActiveCastSlotShortOffset, 0xFFFF);
        const auto world_ptr_diag =
            memory.ReadFieldOr<std::uintptr_t>(actor_address, kActorOwnerOffset, 0);
        std::uintptr_t spell_obj_ptr = 0;
        std::uint32_t obj_type = 0;
        std::uint32_t obj_f74_raw = 0;
        std::uint32_t obj_f1fc_raw = 0;
        std::uint32_t obj_f22c = 0;
        std::uint32_t obj_f230 = 0;
        if (group_post_diag != kBotCastActorActiveCastGroupSentinel &&
            slot_post_diag != kBotCastActorActiveCastSlotSentinel && world_ptr_diag != 0) {
            const std::uintptr_t entry_address =
                world_ptr_diag + kActorWorldBucketTableOffset +
                static_cast<std::uintptr_t>(
                    static_cast<std::uint32_t>(group_post_diag) * kActorWorldBucketStride +
                    static_cast<std::uint32_t>(slot_post_diag)) *
                    sizeof(std::uintptr_t);
            spell_obj_ptr = memory.ReadValueOr<std::uintptr_t>(entry_address, 0);
            if (spell_obj_ptr != 0 && memory.IsReadableRange(spell_obj_ptr, 0x240)) {
                obj_type = memory.ReadFieldOr<std::uint32_t>(spell_obj_ptr, 0x08, 0);
                obj_f74_raw = memory.ReadFieldOr<std::uint32_t>(spell_obj_ptr, 0x74, 0);
                obj_f1fc_raw = memory.ReadFieldOr<std::uint32_t>(spell_obj_ptr, 0x1FC, 0);
                obj_f22c = memory.ReadFieldOr<std::uint32_t>(spell_obj_ptr, 0x22C, 0);
                obj_f230 = memory.ReadFieldOr<std::uint32_t>(spell_obj_ptr, 0x230, 0);
            }
        }
        Log(
            std::string("[bots] spell_obj diag. bot_id=") + std::to_string(binding->bot_id) +
            " group=" + HexString(group_post_diag) +
            " slot=" + HexString(slot_post_diag) +
            " world=" + HexString(world_ptr_diag) +
            " obj_ptr=" + HexString(spell_obj_ptr) +
            " obj_type=" + HexString(obj_type) +
            " obj_74_raw=" + HexString(obj_f74_raw) +
            " obj_1fc_raw=" + HexString(obj_f1fc_raw) +
            " obj_22c=" + std::to_string(obj_f22c) +
            " obj_230=" + std::to_string(obj_f230));
    }

    if (!dispatched) {
        ParticipantEntityBinding::OngoingCastState rollback{};
        rollback.have_aim_heading = have_aim_heading;
        rollback.have_aim_target = have_aim_target;
        rollback.heading_before = heading_before;
        rollback.aim_x_before = aim_x_before;
        rollback.aim_y_before = aim_y_before;
        rollback.aim_aux0_before = aim_aux0_before;
        rollback.aim_aux1_before = aim_aux1_before;
        rollback.spread_before = spread_before;
        (void)memory.TryWriteField<std::int32_t>(actor_address, kActorPrimarySkillIdOffset, 0);
        RestoreBotCastAim(cast_context, rollback);
        (void)multiplayer::FinishBotAttack(
            binding->bot_id,
            true,
            memory.ReadFieldOr<float>(actor_address, kActorHeadingOffset, heading_before),
            true);

        if (error_message != nullptr) {
            *error_message =
                "spell_cast_dispatcher threw SEH " + HexString(exception_code);
        }
        Log(
            "[bots] cast dispatch failed. bot_id=" + std::to_string(binding->bot_id) +
            " skill_id=" + std::to_string(request.skill_id) +
            " seh=" + HexString(exception_code));
        return false;
    }

    if (have_aim_heading) {
        binding->facing_heading_value = aim_heading;
        binding->facing_heading_valid = true;
    }

    auto& ongoing = binding->ongoing_cast;
    ongoing.active = true;
    ongoing.skill_id = request.skill_id;
    ongoing.have_aim_heading = have_aim_heading;
    ongoing.aim_heading = aim_heading;
    ongoing.have_aim_target = have_aim_target;
    ongoing.aim_target_x = aim_target_x;
    ongoing.aim_target_y = aim_target_y;
    ongoing.target_actor_address = effective_target_actor_address;
    ongoing.heading_before = heading_before;
    ongoing.aim_x_before = aim_x_before;
    ongoing.aim_y_before = aim_y_before;
    ongoing.aim_aux0_before = aim_aux0_before;
    ongoing.aim_aux1_before = aim_aux1_before;
    ongoing.spread_before = spread_before;
    ongoing.ticks_waiting = 0;
    ongoing.saw_latch = false;
    ongoing.saw_activity = false;
    ongoing.requires_local_slot_native_tick =
        SkillRequiresLocalSlotDuringNativeTick(request.skill_id);

    // Instant-hit spells (e.g. many melees) may complete inside this primer
    // dispatch: the handler allocates, fires, and drops back to the sentinel
    // all in one call. Detect and release immediately so we don't spin in
    // the watch loop waiting for a latch that already came and went. 0x3EF is
    // intentionally excluded: the stock family can return from the primer with
    // no live handle or latch, then emit on a later native tick only while the
    // gameplay-slot bot is temporarily masquerading as slot 0.
    const auto drive_state_post =
        memory.ReadFieldOr<std::uint8_t>(actor_address, kActorAnimationDriveStateByteOffset, 0);
    const auto no_interrupt_post =
        memory.ReadFieldOr<std::uint8_t>(actor_address, kActorNoInterruptFlagOffset, 0);
    ongoing.saw_activity =
        active_group_post != kBotCastActorActiveCastGroupSentinel ||
        drive_state_post != 0 ||
        no_interrupt_post != 0;
    if (!ongoing.requires_local_slot_native_tick &&
        (active_group_post == kBotCastActorActiveCastGroupSentinel ||
         (drive_state_post == 0 && no_interrupt_post == 0))) {
        ongoing.saw_latch = (drive_state_post != 0 || no_interrupt_post != 0);
        ongoing.saw_activity = ongoing.saw_activity || ongoing.saw_latch;
        ReleaseBotSpellHandle(cast_context, ongoing, "instant", false);
        ongoing = ParticipantEntityBinding::OngoingCastState{};
    }

    Log(
        "[bots] cast dispatched. bot_id=" + std::to_string(binding->bot_id) +
        " skill_id=" + std::to_string(request.skill_id) +
        " aim_heading=" + (have_aim_heading ? std::to_string(aim_heading) : std::string("<none>")) +
        " aim_target=" + (have_aim_target ? (std::to_string(aim_target_x) + "," + std::to_string(aim_target_y)) : std::string("<none>")) +
        " cast_handle_before=(" + HexString(active_cast_group_before) + "," +
        HexString(active_cast_slot_before) + ")" +
        " group_post=" + HexString(active_group_post) +
        " drive_post=" + HexString(drive_state_post) +
        " no_int_post=" + HexString(no_interrupt_post) +
        " native_slot0_tick=" +
        (binding->ongoing_cast.requires_local_slot_native_tick ? std::string("1") : std::string("0")) +
        " watch_armed=" + (binding->ongoing_cast.active ? std::string("1") : std::string("0")));
    return true;
}
