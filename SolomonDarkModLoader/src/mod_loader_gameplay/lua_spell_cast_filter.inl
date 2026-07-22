bool IsUsableSpellCastAimTarget(
    float position_x,
    float position_y,
    float aim_target_x,
    float aim_target_y) {
    if (!std::isfinite(position_x) ||
        !std::isfinite(position_y) ||
        !std::isfinite(aim_target_x) ||
        !std::isfinite(aim_target_y) ||
        (std::abs(aim_target_x) < 0.001f &&
         std::abs(aim_target_y) < 0.001f)) {
        return false;
    }

    const auto dx = aim_target_x - position_x;
    const auto dy = aim_target_y - position_y;
    const auto distance = std::sqrt(dx * dx + dy * dy);
    constexpr float kMinimumAimDistance = 1.0f;
    constexpr float kMaximumAimDistance = 4096.0f;
    constexpr float kMaximumAimCoordinateMagnitude = 20000.0f;
    return std::isfinite(distance) &&
           distance >= kMinimumAimDistance &&
           distance <= kMaximumAimDistance &&
           std::abs(aim_target_x) <= kMaximumAimCoordinateMagnitude &&
           std::abs(aim_target_y) <= kMaximumAimCoordinateMagnitude;
}

LuaSpellCastFilterContext CaptureLuaSpellCastFilterContext(
    uintptr_t actor_address,
    std::uint64_t participant_id,
    LuaSpellCastKind kind,
    std::int32_t skill_id,
    std::int32_t secondary_slot = -1) {
    LuaSpellCastFilterContext context{};
    context.caster_actor_address = actor_address;
    context.caster_participant_id = participant_id;
    context.kind = kind;
    context.skill_id = skill_id;
    context.secondary_slot = secondary_slot;
    if (actor_address == 0) {
        return context;
    }

    auto& memory = ProcessMemory::Instance();
    context.has_position =
        TryReadFiniteFloatField(
            actor_address,
            kActorPositionXOffset,
            &context.position_x) &&
        TryReadFiniteFloatField(
            actor_address,
            kActorPositionYOffset,
            &context.position_y);

    float heading = 0.0f;
    if (TryReadFiniteFloatField(
            actor_address,
            kActorHeadingOffset,
            &heading)) {
        const auto radians =
            (NormalizeWizardActorHeadingForWrite(heading) - 90.0f) /
            kWizardHeadingRadiansToDegrees;
        context.direction_x = static_cast<float>(std::cos(radians));
        context.direction_y = static_cast<float>(std::sin(radians));
        context.has_direction =
            std::isfinite(context.direction_x) &&
            std::isfinite(context.direction_y);
    }

    (void)memory.TryReadField(
        actor_address,
        kActorCurrentTargetActorOffset,
        &context.target_actor_address);
    const bool aim_target_readable =
        TryReadFiniteFloatField(
            actor_address,
            kActorAimTargetXOffset,
            &context.aim_target_x) &&
        TryReadFiniteFloatField(
            actor_address,
            kActorAimTargetYOffset,
            &context.aim_target_y);
    context.has_aim_target =
        aim_target_readable &&
        context.has_position &&
        IsUsableSpellCastAimTarget(
            context.position_x,
            context.position_y,
            context.aim_target_x,
            context.aim_target_y);
    return context;
}

void ApplyLuaSpellCastAimOverrides(
    bool have_aim_heading,
    float aim_heading,
    bool have_aim_target,
    float aim_target_x,
    float aim_target_y,
    uintptr_t target_actor_address,
    LuaSpellCastFilterContext* context) {
    if (context == nullptr) {
        return;
    }
    if (have_aim_heading && std::isfinite(aim_heading)) {
        const auto radians =
            (NormalizeWizardActorHeadingForWrite(aim_heading) - 90.0f) /
            kWizardHeadingRadiansToDegrees;
        context->direction_x = static_cast<float>(std::cos(radians));
        context->direction_y = static_cast<float>(std::sin(radians));
        context->has_direction =
            std::isfinite(context->direction_x) &&
            std::isfinite(context->direction_y);
    }
    if (have_aim_target &&
        std::isfinite(aim_target_x) &&
        std::isfinite(aim_target_y)) {
        context->has_aim_target = true;
        context->aim_target_x = aim_target_x;
        context->aim_target_y = aim_target_y;
    }
    context->target_actor_address = target_actor_address;
}

void RetireCanceledOwnerBotSpellCast(ParticipantEntityBinding* binding) {
    if (binding == nullptr || binding->actor_address == 0) {
        return;
    }

    const auto actor_address = binding->actor_address;
    float heading = 0.0f;
    const bool heading_readable =
        TryReadFiniteFloatField(
            actor_address,
            kActorHeadingOffset,
            &heading);
    (void)multiplayer::FinishBotAttack(
        binding->bot_id,
        heading_readable,
        heading,
        true);
    // QueueBotCast installs a persistent face-heading override for its aim.
    // FinishBotAttack preserves that override so completed attacks keep their
    // last facing, but a rejected request must not feed it back into the stock
    // control brain on the following idle tick. That nonzero desired-facing
    // value is itself enough for PlayerActorTick to author a pure-primary
    // action, even though the Lua request and native cast fields are clear.
    (void)multiplayer::FaceBotTarget(binding->bot_id, 0, false, 0.0f);
    binding->facing_heading_valid = false;
    binding->facing_heading_value = 0.0f;

    auto& memory = ProcessMemory::Instance();
    (void)memory.TryWriteField<std::int32_t>(
        actor_address,
        kActorPrimarySkillIdOffset,
        0);
    (void)memory.TryWriteField<std::int32_t>(
        actor_address,
        kActorPreviousSkillIdOffset,
        0);
    (void)memory.TryWriteField<std::uint32_t>(
        actor_address,
        kActorPrimaryActionLatchE4Offset,
        0);
    (void)memory.TryWriteField<std::uint32_t>(
        actor_address,
        kActorPrimaryActionLatchE8Offset,
        0);
    (void)memory.TryWriteField<std::uint8_t>(
        actor_address,
        kActorPostGateActiveByteOffset,
        0);
    (void)memory.TryWriteField<std::uint8_t>(
        actor_address,
        kActorSpellTargetGroupByteOffset,
        kTargetHandleGroupSentinel);
    (void)memory.TryWriteField<std::uint16_t>(
        actor_address,
        kActorSpellTargetSlotShortOffset,
        kTargetHandleSlotSentinel);
    ResetStandaloneWizardControlBrain(actor_address);
    binding->facing_target_actor_address = 0;
    binding->suppress_next_stock_tick_after_spell_filter_cancel = true;
}
