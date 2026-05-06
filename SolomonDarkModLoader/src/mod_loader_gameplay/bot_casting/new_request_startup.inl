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
        float current_heading = 0.0f;
        const bool current_heading_readable =
            TryReadFiniteFloatField(actor_address, kActorHeadingOffset, &current_heading);
        (void)multiplayer::FinishBotAttack(
            binding->bot_id,
            current_heading_readable,
            current_heading,
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
        float actor_x = 0.0f;
        float actor_y = 0.0f;
        if (!TryReadFiniteFloatField(actor_address, kActorPositionXOffset, &actor_x) ||
            !TryReadFiniteFloatField(actor_address, kActorPositionYOffset, &actor_y)) {
            if (error_message != nullptr) {
                *error_message = "actor position unreadable for bot cast aim";
            }
            return false;
        }
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

    float heading_before = 0.0f;
    float aim_x_before = 0.0f;
    float aim_y_before = 0.0f;
    std::uint32_t aim_aux0_before = 0;
    std::uint32_t aim_aux1_before = 0;
    std::uint8_t spread_before = 0;
    if (!TryReadFiniteFloatField(actor_address, kActorHeadingOffset, &heading_before) ||
        !TryReadFiniteFloatField(actor_address, kActorAimTargetXOffset, &aim_x_before) ||
        !TryReadFiniteFloatField(actor_address, kActorAimTargetYOffset, &aim_y_before) ||
        !memory.TryReadField(actor_address, kActorAimTargetAux0Offset, &aim_aux0_before) ||
        !memory.TryReadField(actor_address, kActorAimTargetAux1Offset, &aim_aux1_before) ||
        !memory.TryReadField(actor_address, kActorCastSpreadModeByteOffset, &spread_before)) {
        if (error_message != nullptr) {
            *error_message = "actor cast startup state unreadable";
        }
        return false;
    }

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

    std::uint8_t active_cast_group_before = kBotCastActorActiveCastGroupSentinel;
    std::uint16_t active_cast_slot_before = kBotCastActorActiveCastSlotSentinel;
    if (!memory.TryReadField(actor_address, kActorActiveCastGroupByteOffset, &active_cast_group_before) ||
        !memory.TryReadField(actor_address, kActorActiveCastSlotShortOffset, &active_cast_slot_before)) {
        if (error_message != nullptr) {
            *error_message = "native active-cast handle unreadable before bot cast";
        }
        return false;
    }
    // If a prior cast left the handle cached (e.g. SEH abort), release it
    // properly before starting init so we don't leak a world-storage slot.
    if (active_cast_group_before != kBotCastActorActiveCastGroupSentinel) {
        DWORD prior_cleanup_seh = 0;
        bool prior_cleanup_ok = false;
        InvokeBotCastWithNativeActorSlot(cast_context, [&] {
            prior_cleanup_ok = CallCastActiveHandleCleanupSafe(
                cleanup_address, actor_address, &prior_cleanup_seh);
        });
        if (!prior_cleanup_ok) {
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
                heading_before,
                true);
            if (error_message != nullptr) {
                *error_message =
                    "prior native active-handle cleanup failed with " +
                    HexString(prior_cleanup_seh);
            }
            Log(
                "[bots] prior native active-handle cleanup failed. bot_id=" +
                std::to_string(binding->bot_id) +
                " skill_id=" + std::to_string(request.skill_id) +
                " group_before=" + HexString(active_cast_group_before) +
                " slot_before=" + HexString(active_cast_slot_before) +
                " seh=" + HexString(prior_cleanup_seh));
            return false;
        }
    }

    DWORD exception_code = 0;
    bool dispatched = false;
    InvokeBotCastWithNativeActorSlot(cast_context, [&] {
        dispatched = CallSpellCastDispatcherSafe(
            dispatcher_address, actor_address, &exception_code);
    });

    std::uint8_t active_group_post = kBotCastActorActiveCastGroupSentinel;
    if (!memory.TryReadField(actor_address, kActorActiveCastGroupByteOffset, &active_group_post)) {
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
        (void)multiplayer::FinishBotAttack(binding->bot_id, true, heading_before, true);
        if (error_message != nullptr) {
            *error_message = "native active-cast group unreadable after bot cast";
        }
        return false;
    }

    // Diagnostic: immediately after dispatcher returns and before any cleanup,
    // ask the native world lookup for the active spell object so we can see
    // what the handler actually produced.
    {
        const auto spell_state = ReadBotNativeActiveSpellObjectState(cast_context, false);
        Log(
            std::string("[bots] spell_obj diag. bot_id=") + std::to_string(binding->bot_id) +
            " group=" + HexString(spell_state.group) +
            " slot=" + HexString(spell_state.slot) +
            " world=" + HexString(spell_state.world) +
            " native_lookup=" + (spell_state.lookup_attempted ? std::string("1") : std::string("0")) +
            " native_lookup_ok=" + (spell_state.lookup_succeeded ? std::string("1") : std::string("0")) +
            " native_lookup_seh=" + HexString(spell_state.lookup_exception) +
            " obj_ptr=" + HexString(spell_state.object) +
            " obj_type=" + HexString(spell_state.object_type) +
            " obj_charge=" + std::to_string(spell_state.charge) +
            " obj_max_charge=" + std::to_string(spell_state.max_charge) +
            " obj_phase=" + std::to_string(spell_state.phase) +
            " obj_release_timer=" + std::to_string(spell_state.release_timer));
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
            heading_before,
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
    // Instant-hit spells (e.g. many melees) may complete inside this primer
    // dispatch: the handler allocates, fires, and drops back to an empty handle
    // all in one call. Detect and release immediately so we don't spin in
    // the watch loop waiting for a latch that already came and went. Combo
    // dispatcher primaries arm through the gameplay-slot startup path instead
    // of this direct one so late native emission stays visible there.
    std::uint8_t drive_state_post = 0;
    std::uint8_t no_interrupt_post = 0;
    if (!memory.TryReadField(actor_address, kActorAnimationDriveStateByteOffset, &drive_state_post) ||
        !memory.TryReadField(actor_address, kActorNoInterruptFlagOffset, &no_interrupt_post)) {
        ParticipantEntityBinding::OngoingCastState rollback = ongoing;
        RestoreBotCastAim(cast_context, rollback);
        (void)multiplayer::FinishBotAttack(binding->bot_id, true, heading_before, true);
        ongoing = ParticipantEntityBinding::OngoingCastState{};
        if (error_message != nullptr) {
            *error_message = "native cast latch state unreadable after bot cast";
        }
        return false;
    }
    ongoing.saw_activity =
        active_group_post != kBotCastActorActiveCastGroupSentinel ||
        drive_state_post != 0 ||
        no_interrupt_post != 0;
    if (active_group_post == kBotCastActorActiveCastGroupSentinel ||
        (drive_state_post == 0 && no_interrupt_post == 0)) {
        ongoing.saw_latch = (drive_state_post != 0 || no_interrupt_post != 0);
        ongoing.saw_activity = ongoing.saw_activity || ongoing.saw_latch;
        FinishBotCastNativeLifecycle(cast_context, ongoing, "instant", false);
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
        " native_actor_slot=" + [&]() {
            std::int8_t actor_slot = -1;
            return memory.TryReadField(actor_address, kActorSlotOffset, &actor_slot)
                ? std::to_string(static_cast<int>(actor_slot))
                : std::string("unreadable");
        }() +
        " watch_armed=" + (binding->ongoing_cast.active ? std::string("1") : std::string("0")));
    return true;
}
