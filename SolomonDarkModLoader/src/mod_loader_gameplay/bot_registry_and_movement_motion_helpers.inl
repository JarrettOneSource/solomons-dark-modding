float ReadResolvedGameFloatOr(uintptr_t absolute_address, float fallback) {
    auto& memory = ProcessMemory::Instance();
    const auto resolved_address = memory.ResolveGameAddressOrZero(absolute_address);
    if (resolved_address == 0) {
        return fallback;
    }

    return memory.ReadValueOr<float>(resolved_address, fallback);
}

float ReadResolvedGameDoubleAsFloatOr(uintptr_t absolute_address, float fallback) {
    auto& memory = ProcessMemory::Instance();
    const auto resolved_address = memory.ResolveGameAddressOrZero(absolute_address);
    if (resolved_address == 0) {
        return fallback;
    }

    return static_cast<float>(memory.ReadValueOr<double>(resolved_address, static_cast<double>(fallback)));
}

constexpr std::int32_t kSuppressedSelectionRetargetTicks = 60;
constexpr std::size_t kArenaEnemyMaxHpOffset = 0x170;
constexpr std::size_t kArenaEnemyCurrentHpOffset = 0x174;
constexpr std::size_t kArenaEnemyHealthReadSize = kArenaEnemyCurrentHpOffset + sizeof(float);

bool IsArenaEnemyActorHealthType(std::uint32_t object_type_id) {
    return object_type_id == 1001;
}

struct ActorHealthRuntime {
    uintptr_t base_address = 0;
    std::size_t current_hp_offset = 0;
    std::size_t max_hp_offset = 0;
    uintptr_t progression_address = 0;
    const char* kind = "unknown";
    float hp = 0.0f;
    float max_hp = 0.0f;
};

bool TryReadArenaEnemyActorHealth(uintptr_t actor_address, ActorHealthRuntime* health) {
    if (actor_address == 0 || health == nullptr) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    if (!memory.IsReadableRange(actor_address, kArenaEnemyHealthReadSize)) {
        return false;
    }

    const auto object_type_id =
        memory.ReadFieldOr<std::uint32_t>(actor_address, kGameObjectTypeIdOffset, 0);
    if (!IsArenaEnemyActorHealthType(object_type_id)) {
        return false;
    }

    const auto hp =
        memory.ReadFieldOr<float>(actor_address, kArenaEnemyCurrentHpOffset, 0.0f);
    auto max_hp = memory.ReadFieldOr<float>(actor_address, kArenaEnemyMaxHpOffset, 0.0f);
    if (!std::isfinite(hp) || !std::isfinite(max_hp)) {
        return false;
    }
    if (max_hp <= 0.0f && hp > 0.0f) {
        max_hp = hp;
    }
    if (max_hp <= 0.0f) {
        return false;
    }

    health->base_address = actor_address;
    health->current_hp_offset = kArenaEnemyCurrentHpOffset;
    health->max_hp_offset = kArenaEnemyMaxHpOffset;
    health->progression_address = 0;
    health->kind = "arena_enemy";
    health->hp = hp;
    health->max_hp = max_hp;
    return true;
}

bool TryReadActorProgressionHealth(uintptr_t actor_address, ActorHealthRuntime* health) {
    if (actor_address == 0 || health == nullptr) {
        return false;
    }

    uintptr_t progression_address = 0;
    if (!TryResolveActorProgressionRuntime(actor_address, &progression_address) ||
        progression_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    if (!memory.IsReadableRange(progression_address + kProgressionHpOffset, sizeof(float)) ||
        !memory.IsReadableRange(progression_address + kProgressionMaxHpOffset, sizeof(float))) {
        return false;
    }

    const auto hp = memory.ReadFieldOr<float>(progression_address, kProgressionHpOffset, 0.0f);
    const auto max_hp =
        memory.ReadFieldOr<float>(progression_address, kProgressionMaxHpOffset, 0.0f);
    if (!std::isfinite(hp) || !std::isfinite(max_hp) || max_hp <= 0.0f) {
        return false;
    }

    health->base_address = progression_address;
    health->current_hp_offset = kProgressionHpOffset;
    health->max_hp_offset = kProgressionMaxHpOffset;
    health->progression_address = progression_address;
    health->kind = "progression";
    health->hp = hp;
    health->max_hp = max_hp;
    return true;
}

bool TryReadActorHealthRuntime(uintptr_t actor_address, ActorHealthRuntime* health) {
    if (actor_address == 0 || health == nullptr) {
        return false;
    }
    if (TryReadArenaEnemyActorHealth(actor_address, health)) {
        return true;
    }
    return TryReadActorProgressionHealth(actor_address, health);
}

struct ManaSpendResult {
    bool readable = false;
    bool spent = false;
    float before = 0.0f;
    float after = 0.0f;
    float requested = 0.0f;
    float actual = 0.0f;
};

bool TryReadProgressionMana(uintptr_t progression_address, float* mp, float* max_mp) {
    if (progression_address == 0 || mp == nullptr || max_mp == nullptr) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    if (!memory.IsReadableRange(progression_address + kProgressionMpOffset, sizeof(float)) ||
        !memory.IsReadableRange(progression_address + kProgressionMaxMpOffset, sizeof(float))) {
        return false;
    }
    const auto current = memory.ReadFieldOr<float>(progression_address, kProgressionMpOffset, 0.0f);
    const auto maximum =
        memory.ReadFieldOr<float>(progression_address, kProgressionMaxMpOffset, 0.0f);
    if (!std::isfinite(current) || !std::isfinite(maximum) || maximum <= 0.0f) {
        return false;
    }
    *mp = current;
    *max_mp = maximum;
    return true;
}

ManaSpendResult TrySpendProgressionMana(
    uintptr_t progression_address,
    float requested_amount,
    bool allow_partial) {
    ManaSpendResult result{};
    result.requested = requested_amount;
    if (!std::isfinite(requested_amount) || requested_amount <= 0.0f) {
        result.spent = true;
        return result;
    }

    float before = 0.0f;
    float max_mp = 0.0f;
    if (!TryReadProgressionMana(progression_address, &before, &max_mp)) {
        return result;
    }
    result.readable = true;
    result.before = before;
    if (before <= 0.0f) {
        result.after = before;
        return result;
    }

    const float actual_amount =
        allow_partial && before < requested_amount ? before : requested_amount;
    if (before + 0.001f < requested_amount && !allow_partial) {
        result.after = before;
        return result;
    }
    const float after = before > actual_amount ? before - actual_amount : 0.0f;
    auto& memory = ProcessMemory::Instance();
    result.spent =
        memory.TryWriteField<float>(progression_address, kProgressionMpOffset, after);
    if (result.spent) {
        result.after = after;
        result.actual = actual_amount;
    } else {
        result.after = before;
    }
    return result;
}

constexpr std::array<float, 26> kEarthBoulderBaseDamageByLevel = {
    0.0f,   10.0f,  30.0f,  50.0f,  75.0f,  100.0f, 120.0f, 140.0f, 160.0f,
    180.0f, 200.0f, 220.0f, 240.0f, 260.0f, 280.0f, 300.0f, 320.0f, 340.0f,
    360.0f, 380.0f, 400.0f, 420.0f, 440.0f, 460.0f, 480.0f, 500.0f,
};

int ResolveEarthBoulderStatbookLevel(
    const ParticipantEntityBinding* binding,
    uintptr_t progression_runtime_address) {
    int level = binding != nullptr ? binding->character_profile.level : 1;
    auto& memory = ProcessMemory::Instance();
    if (progression_runtime_address != 0 &&
        kProgressionLevelOffset != 0 &&
        memory.IsReadableRange(progression_runtime_address + kProgressionLevelOffset, sizeof(int))) {
        level = memory.ReadFieldOr<int>(progression_runtime_address, kProgressionLevelOffset, level);
    }
    if (level < 1) {
        return 1;
    }
    const auto max_level = static_cast<int>(kEarthBoulderBaseDamageByLevel.size()) - 1;
    return level > max_level ? max_level : level;
}

float ResolveEarthBoulderBaseDamage(
    const ParticipantEntityBinding* binding,
    uintptr_t progression_runtime_address,
    int* resolved_level) {
    const auto level = ResolveEarthBoulderStatbookLevel(binding, progression_runtime_address);
    if (resolved_level != nullptr) {
        *resolved_level = level;
    }
    return kEarthBoulderBaseDamageByLevel[static_cast<std::size_t>(level)];
}

bool IsActorRuntimeDead(uintptr_t actor_address) {
    if (actor_address == 0) {
        return false;
    }

    ActorHealthRuntime health;
    auto& memory = ProcessMemory::Instance();
    const auto object_type_id =
        memory.ReadFieldOr<std::uint32_t>(actor_address, kGameObjectTypeIdOffset, 0);
    if (IsArenaEnemyActorHealthType(object_type_id) &&
        TryReadArenaEnemyActorHealth(actor_address, &health)) {
        return health.max_hp > 0.0f && health.hp <= 0.0f;
    }

    if (TryReadActorProgressionHealth(actor_address, &health)) {
        return health.max_hp > 0.0f && health.hp <= 0.0f;
    }

    if (memory.ReadFieldOr<std::uint8_t>(actor_address, kEnemyDeathHandledOffset, 0) != 0) {
        return true;
    }
    return false;
}

bool TryComputeActorAimTowardTarget(
    uintptr_t actor_address,
    uintptr_t target_actor_address,
    float* heading_degrees,
    float* target_x_out,
    float* target_y_out);

bool TryComputeActorAimTowardTargetFromOrigin(
    uintptr_t actor_address,
    uintptr_t target_actor_address,
    bool origin_valid,
    float origin_x,
    float origin_y,
    float* heading_degrees,
    float* target_x_out,
    float* target_y_out);

bool SkillRequiresHeldCastInputDuringNativeTick(std::int32_t skill_id);

bool SkillRequiresBoundedHeldCastInputDuringNativeTick(std::int32_t skill_id);

bool SkillRequiresSyntheticCastInputDuringNativeTick(std::int32_t skill_id);

bool SkillTracksLiveTargetDuringNativeTick(std::int32_t skill_id);

std::int32_t ResolveOngoingNativeTickSkillId(
    const ParticipantEntityBinding::OngoingCastState& ongoing);

bool OngoingCastShouldRefreshNativeTargetState(
    const ParticipantEntityBinding::OngoingCastState& ongoing);

bool OngoingCastShouldUseLiveFacingTarget(
    const ParticipantEntityBinding::OngoingCastState& ongoing);

uintptr_t ResolveOngoingCastNativeTargetActor(
    const ParticipantEntityBinding* binding,
    const ParticipantEntityBinding::OngoingCastState& ongoing);

bool SkillRequiresNativeActorTargetHandle(std::int32_t skill_id) {
    // Air primary (lightning) is not projectile/collision based. The native
    // handler resolves the victim through actor+0x164/0x166 and only runs the
    // damage branch when that handle points at a live world actor.
    switch (skill_id) {
    case 0x18:
    case 0x3F5:
        return true;
    default:
        return false;
    }
}

bool OngoingCastNeedsNativeTargetHandle(
    const ParticipantEntityBinding::OngoingCastState& ongoing) {
    return SkillRequiresNativeActorTargetHandle(ongoing.skill_id) ||
           SkillRequiresNativeActorTargetHandle(ongoing.dispatcher_skill_id);
}

bool TryResolveSameWorldTargetHandle(
    uintptr_t actor_address,
    uintptr_t target_actor_address,
    std::uint8_t* group_out,
    std::uint16_t* slot_out) {
    if (group_out != nullptr) {
        *group_out = kTargetHandleGroupSentinel;
    }
    if (slot_out != nullptr) {
        *slot_out = kTargetHandleSlotSentinel;
    }
    if (actor_address == 0 || target_actor_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto actor_owner =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, 0);
    const auto target_owner =
        memory.ReadFieldOr<uintptr_t>(target_actor_address, kActorOwnerOffset, 0);
    if (actor_owner == 0 || actor_owner != target_owner) {
        return false;
    }

    const auto target_group =
        memory.ReadFieldOr<std::uint8_t>(
            target_actor_address,
            kActorSlotOffset,
            kTargetHandleGroupSentinel);
    const auto target_slot =
        memory.ReadFieldOr<std::uint16_t>(
            target_actor_address,
            kActorWorldSlotOffset,
            kTargetHandleSlotSentinel);
    if (target_group == kTargetHandleGroupSentinel ||
        target_slot == kTargetHandleSlotSentinel) {
        return false;
    }

    if (group_out != nullptr) {
        *group_out = target_group;
    }
    if (slot_out != nullptr) {
        *slot_out = target_slot;
    }
    return true;
}

bool TryComputeActorHeadingTowardTarget(
    uintptr_t actor_address,
    uintptr_t target_actor_address,
    float* heading_degrees) {
    float ignored_target_x = 0.0f;
    float ignored_target_y = 0.0f;
    return TryComputeActorAimTowardTarget(
        actor_address,
        target_actor_address,
        heading_degrees,
        &ignored_target_x,
        &ignored_target_y);
}

bool TryComputeActorAimTowardTarget(
    uintptr_t actor_address,
    uintptr_t target_actor_address,
    float* heading_degrees,
    float* target_x_out,
    float* target_y_out) {
    return TryComputeActorAimTowardTargetFromOrigin(
        actor_address,
        target_actor_address,
        false,
        0.0f,
        0.0f,
        heading_degrees,
        target_x_out,
        target_y_out);
}

bool TryComputeActorAimTowardTargetFromOrigin(
    uintptr_t actor_address,
    uintptr_t target_actor_address,
    bool origin_valid,
    float origin_x,
    float origin_y,
    float* heading_degrees,
    float* target_x_out,
    float* target_y_out) {
    if (actor_address == 0 || target_actor_address == 0 || heading_degrees == nullptr) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    constexpr std::size_t kActorFacingReadSize = 0x80;
    if (!memory.IsReadableRange(actor_address, kActorFacingReadSize) ||
        !memory.IsReadableRange(target_actor_address, kActorFacingReadSize) ||
        IsActorRuntimeDead(target_actor_address)) {
        return false;
    }

    const auto actor_owner = memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, 0);
    const auto target_owner = memory.ReadFieldOr<uintptr_t>(target_actor_address, kActorOwnerOffset, 0);
    if (actor_owner == 0 || target_owner == 0 || actor_owner != target_owner) {
        return false;
    }

    const auto actor_x =
        origin_valid && std::isfinite(origin_x)
            ? origin_x
            : memory.ReadFieldOr<float>(actor_address, kActorPositionXOffset, 0.0f);
    const auto actor_y =
        origin_valid && std::isfinite(origin_y)
            ? origin_y
            : memory.ReadFieldOr<float>(actor_address, kActorPositionYOffset, 0.0f);
    const auto target_x = memory.ReadFieldOr<float>(target_actor_address, kActorPositionXOffset, 0.0f);
    const auto target_y = memory.ReadFieldOr<float>(target_actor_address, kActorPositionYOffset, 0.0f);
    const auto dx = target_x - actor_x;
    const auto dy = target_y - actor_y;
    if (!std::isfinite(dx) || !std::isfinite(dy) || ((dx * dx) + (dy * dy)) <= 0.0001f) {
        return false;
    }

    *heading_degrees = NormalizeWizardActorHeadingForWrite(
        static_cast<float>(std::atan2(dy, dx) * kWizardHeadingRadiansToDegrees + 90.0f));
    if (target_x_out != nullptr) {
        *target_x_out = target_x;
    }
    if (target_y_out != nullptr) {
        *target_y_out = target_y;
    }
    return true;
}

bool TryGetBindingMovementInputVector(
    const ParticipantEntityBinding& binding,
    float* direction_x_out,
    float* direction_y_out) {
    if (direction_x_out == nullptr || direction_y_out == nullptr || !binding.movement_active) {
        return false;
    }

    const auto direction_x = binding.direction_x;
    const auto direction_y = binding.direction_y;
    const auto magnitude_squared = (direction_x * direction_x) + (direction_y * direction_y);
    if (!std::isfinite(magnitude_squared) || magnitude_squared <= 0.0001f) {
        return false;
    }

    const auto inverse_magnitude = 1.0f / std::sqrt(magnitude_squared);
    *direction_x_out = direction_x * inverse_magnitude;
    *direction_y_out = direction_y * inverse_magnitude;
    return std::isfinite(*direction_x_out) && std::isfinite(*direction_y_out);
}

bool OngoingCastNeedsNativeTargetActor(
    const ParticipantEntityBinding::OngoingCastState& ongoing) {
    if (ongoing.lane == ParticipantEntityBinding::OngoingCastState::Lane::PurePrimary) {
        return true;
    }

    // Only live-target channel handlers consume actor+0x298 during the native
    // tick. Earth's boulder is a world spell object; publishing a target actor
    // there changes the native projectile collision/damage path even though
    // aim and selection state still need to be refreshed while charging.
    return ongoing.uses_dispatcher_skill_id &&
           ongoing.requires_local_slot_native_tick &&
           SkillTracksLiveTargetDuringNativeTick(ResolveOngoingNativeTickSkillId(ongoing));
}

bool OngoingCastShouldPreserveAimAfterTargetLoss(
    const ParticipantEntityBinding::OngoingCastState& ongoing) {
    return ongoing.active &&
           OngoingCastNeedsNativeTargetActor(ongoing) &&
           ongoing.requires_local_slot_native_tick &&
           ongoing.have_aim_target;
}

bool WriteOngoingCastNativeTargetActor(
    uintptr_t actor_address,
    ParticipantEntityBinding::OngoingCastState* ongoing,
    uintptr_t target_actor_address) {
    if (actor_address == 0 || ongoing == nullptr || !OngoingCastNeedsNativeTargetActor(*ongoing)) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    if (!ongoing->current_target_actor_override_active) {
        ongoing->current_target_actor_before =
            memory.ReadFieldOr<uintptr_t>(actor_address, kActorCurrentTargetActorOffset, 0);
        ongoing->current_target_actor_override_active = true;
    }
    const bool target_pointer_written = memory.TryWriteField<uintptr_t>(
        actor_address,
        kActorCurrentTargetActorOffset,
        target_actor_address);

    if (OngoingCastNeedsNativeTargetHandle(*ongoing)) {
        std::uint8_t target_group = kTargetHandleGroupSentinel;
        std::uint16_t target_slot = kTargetHandleSlotSentinel;
        if (TryResolveSameWorldTargetHandle(
                actor_address,
                target_actor_address,
                &target_group,
                &target_slot)) {
            if (!ongoing->native_target_handle_override_active) {
                ongoing->native_target_group_before =
                    memory.ReadFieldOr<std::uint8_t>(
                        actor_address,
                        kActorSpellTargetGroupByteOffset,
                        kTargetHandleGroupSentinel);
                ongoing->native_target_slot_before =
                    memory.ReadFieldOr<std::uint16_t>(
                        actor_address,
                        kActorSpellTargetSlotShortOffset,
                        kTargetHandleSlotSentinel);
                ongoing->native_target_handle_override_active = true;
            }
            (void)memory.TryWriteField<std::uint8_t>(
                actor_address,
                kActorSpellTargetGroupByteOffset,
                target_group);
            (void)memory.TryWriteField<std::uint16_t>(
                actor_address,
                kActorSpellTargetSlotShortOffset,
                target_slot);
        } else if (ongoing->native_target_handle_override_active) {
            (void)memory.TryWriteField<std::uint8_t>(
                actor_address,
                kActorSpellTargetGroupByteOffset,
                kTargetHandleGroupSentinel);
            (void)memory.TryWriteField<std::uint16_t>(
                actor_address,
                kActorSpellTargetSlotShortOffset,
                kTargetHandleSlotSentinel);
        }
    }

    return target_pointer_written;
}

void ClearOngoingCastNativeTargetActor(
    uintptr_t actor_address,
    ParticipantEntityBinding::OngoingCastState* ongoing) {
    if (actor_address == 0 || ongoing == nullptr ||
        (!ongoing->current_target_actor_override_active &&
         !ongoing->native_target_handle_override_active)) {
        return;
    }
    if (ongoing->current_target_actor_override_active) {
        (void)ProcessMemory::Instance().TryWriteField<uintptr_t>(
            actor_address,
            kActorCurrentTargetActorOffset,
            0);
    }
    if (OngoingCastNeedsNativeTargetHandle(*ongoing) &&
        ongoing->native_target_handle_override_active) {
        (void)ProcessMemory::Instance().TryWriteField<std::uint8_t>(
            actor_address,
            kActorSpellTargetGroupByteOffset,
            kTargetHandleGroupSentinel);
        (void)ProcessMemory::Instance().TryWriteField<std::uint16_t>(
            actor_address,
            kActorSpellTargetSlotShortOffset,
            kTargetHandleSlotSentinel);
    }
}

void RestoreOngoingCastNativeTargetActor(
    uintptr_t actor_address,
    const ParticipantEntityBinding::OngoingCastState& ongoing) {
    if (actor_address == 0 ||
        (!ongoing.current_target_actor_override_active &&
         !ongoing.native_target_handle_override_active)) {
        return;
    }
    if (ongoing.current_target_actor_override_active) {
        (void)ProcessMemory::Instance().TryWriteField<uintptr_t>(
            actor_address,
            kActorCurrentTargetActorOffset,
            ongoing.current_target_actor_before);
    }
    if (ongoing.native_target_handle_override_active) {
        (void)ProcessMemory::Instance().TryWriteField<std::uint8_t>(
            actor_address,
            kActorSpellTargetGroupByteOffset,
            ongoing.native_target_group_before);
        (void)ProcessMemory::Instance().TryWriteField<std::uint16_t>(
            actor_address,
            kActorSpellTargetSlotShortOffset,
            ongoing.native_target_slot_before);
    }
}

bool RefreshWizardBindingTargetFacing(ParticipantEntityBinding* binding) {
    if (binding == nullptr || binding->actor_address == 0 || binding->facing_target_actor_address == 0) {
        return false;
    }

    float heading = 0.0f;
    float target_x = 0.0f;
    float target_y = 0.0f;
    if (!TryComputeActorAimTowardTargetFromOrigin(
            binding->actor_address,
            binding->facing_target_actor_address,
            binding->stock_tick_facing_origin_valid,
            binding->stock_tick_facing_origin_x,
            binding->stock_tick_facing_origin_y,
            &heading,
            &target_x,
            &target_y)) {
        binding->facing_target_actor_address = 0;
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    (void)memory.TryWriteField(binding->actor_address, kActorAimTargetXOffset, target_x);
    (void)memory.TryWriteField(binding->actor_address, kActorAimTargetYOffset, target_y);
    (void)memory.TryWriteField<std::uint32_t>(binding->actor_address, kActorAimTargetAux0Offset, 0);
    (void)memory.TryWriteField<std::uint32_t>(binding->actor_address, kActorAimTargetAux1Offset, 0);
    binding->facing_heading_value = heading;
    binding->facing_heading_valid = true;
    return true;
}

bool RefreshOngoingCastAimFromFacingTarget(
    ParticipantEntityBinding* binding,
    ParticipantEntityBinding::OngoingCastState* ongoing) {
    if (binding == nullptr || ongoing == nullptr) {
        return false;
    }

    auto target_actor_address = ResolveOngoingCastNativeTargetActor(binding, *ongoing);
    if (target_actor_address == 0) {
        ongoing->selection_target_seed_active = false;
        if (!OngoingCastShouldPreserveAimAfterTargetLoss(*ongoing)) {
            ongoing->have_aim_heading = false;
            ongoing->have_aim_target = false;
        }
        ClearOngoingCastNativeTargetActor(binding->actor_address, ongoing);
        return false;
    }

    float heading = 0.0f;
    float target_x = 0.0f;
    float target_y = 0.0f;
    if (!TryComputeActorAimTowardTargetFromOrigin(
            binding->actor_address,
            target_actor_address,
            binding->stock_tick_facing_origin_valid,
            binding->stock_tick_facing_origin_x,
            binding->stock_tick_facing_origin_y,
            &heading,
            &target_x,
            &target_y)) {
        if (binding->facing_target_actor_address == target_actor_address) {
            binding->facing_target_actor_address = 0;
        }
        if (ongoing->target_actor_address == target_actor_address) {
            ongoing->target_actor_address = 0;
        }
        ongoing->selection_target_seed_active = false;
        if (!OngoingCastShouldPreserveAimAfterTargetLoss(*ongoing)) {
            ongoing->have_aim_heading = false;
            ongoing->have_aim_target = false;
        }
        ClearOngoingCastNativeTargetActor(binding->actor_address, ongoing);
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    ongoing->targetless_ticks_waiting = 0;
    binding->facing_target_actor_address = target_actor_address;
    ongoing->target_actor_address = target_actor_address;
    const auto target_group =
        memory.ReadFieldOr<std::uint8_t>(
            target_actor_address,
            kActorSlotOffset,
            kTargetHandleGroupSentinel);
    const auto target_slot =
        memory.ReadFieldOr<std::uint16_t>(
            target_actor_address,
            kActorWorldSlotOffset,
            kTargetHandleSlotSentinel);
    if (target_group != kTargetHandleGroupSentinel &&
        target_slot != kTargetHandleSlotSentinel) {
        ongoing->selection_target_seed_active = true;
        ongoing->selection_target_group_seed = target_group;
        ongoing->selection_target_slot_seed = target_slot;
        ongoing->selection_target_hold_ticks = 60;
        if (ongoing->selection_state_pointer != 0) {
            (void)memory.TryWriteField<std::uint8_t>(
                ongoing->selection_state_pointer,
                0x04,
                target_group);
            (void)memory.TryWriteField<std::uint16_t>(
                ongoing->selection_state_pointer,
                0x06,
                target_slot);
            (void)memory.TryWriteField<std::int32_t>(
                ongoing->selection_state_pointer,
                0x08,
                ongoing->selection_target_hold_ticks);
            (void)memory.TryWriteField<std::int32_t>(ongoing->selection_state_pointer, 0x0C, 0);
            (void)memory.TryWriteField<std::int32_t>(ongoing->selection_state_pointer, 0x10, 0);
            (void)memory.TryWriteField<std::int32_t>(ongoing->selection_state_pointer, 0x14, 0);
        }
    } else {
        ongoing->selection_target_seed_active = false;
    }

    binding->facing_heading_value = heading;
    binding->facing_heading_valid = true;
    ongoing->aim_heading = heading;
    ongoing->have_aim_heading = true;
    ongoing->aim_target_x = target_x;
    ongoing->aim_target_y = target_y;
    ongoing->have_aim_target = true;
    ApplyWizardActorFacingState(binding->actor_address, heading);
    (void)WriteOngoingCastNativeTargetActor(
        binding->actor_address,
        ongoing,
        target_actor_address);

    if (ongoing->selection_state_pointer != 0 && ongoing->startup_in_progress) {
        float startup_input_x = 0.0f;
        float startup_input_y = 0.0f;
        auto have_startup_input =
            TryGetBindingMovementInputVector(*binding, &startup_input_x, &startup_input_y);
        if (!have_startup_input) {
            const auto actor_x = memory.ReadFieldOr<float>(
                binding->actor_address,
                kActorPositionXOffset,
                0.0f);
            const auto actor_y = memory.ReadFieldOr<float>(
                binding->actor_address,
                kActorPositionYOffset,
                0.0f);
            const auto dx = target_x - actor_x;
            const auto dy = target_y - actor_y;
            const auto distance = std::sqrt((dx * dx) + (dy * dy));
            if (std::isfinite(distance) && distance > 0.0001f) {
                startup_input_x = dx / distance;
                startup_input_y = dy / distance;
                have_startup_input = true;
            }
        }
        if (have_startup_input) {
            // Stock pure-primary startup needs a non-zero movement/control vector.
            // Prefer the follow lane so attacking does not steer the bot away from
            // the player; only fall back to attack-facing when the bot is idle.
            (void)memory.TryWriteValue<float>(
                ongoing->selection_state_pointer + kActorControlBrainMoveInputXOffset,
                startup_input_x);
            (void)memory.TryWriteValue<float>(
                ongoing->selection_state_pointer + kActorControlBrainMoveInputYOffset,
                startup_input_y);
        }
    }
    return true;
}

bool RefreshAndApplyWizardBindingFacingState(ParticipantEntityBinding* binding, uintptr_t actor_address) {
    if (binding == nullptr || actor_address == 0) {
        return false;
    }

    if (binding->ongoing_cast.active &&
        OngoingCastShouldRefreshNativeTargetState(binding->ongoing_cast)) {
        (void)RefreshOngoingCastAimFromFacingTarget(binding, &binding->ongoing_cast);
    }
    (void)RefreshWizardBindingTargetFacing(binding);
    return ApplyWizardBindingFacingState(binding, actor_address);
}

void QuiesceDeadWizardBinding(ParticipantEntityBinding* binding) {
    if (binding == nullptr) {
        return;
    }

    binding->controller_state = multiplayer::BotControllerState::Idle;
    binding->movement_active = false;
    binding->last_movement_displacement = 0.0f;
    binding->has_target = false;
    binding->direction_x = 0.0f;
    binding->direction_y = 0.0f;
    binding->desired_heading_valid = false;
    binding->desired_heading = 0.0f;
    binding->target_x = 0.0f;
    binding->target_y = 0.0f;
    binding->distance_to_target = 0.0f;
    binding->path_active = false;
    binding->path_failed = false;
    binding->path_waypoint_index = 0;
    binding->current_waypoint_x = 0.0f;
    binding->current_waypoint_y = 0.0f;
    binding->path_waypoints.clear();
    binding->facing_heading_valid = false;
    binding->facing_target_actor_address = 0;
    binding->stock_tick_facing_origin_valid = false;
    binding->stock_tick_facing_origin_x = 0.0f;
    binding->stock_tick_facing_origin_y = 0.0f;
}

void AdvanceStandaloneWizardWalkCycleState(
    ParticipantEntityBinding* binding,
    float displacement_distance) {
    if (binding == nullptr || !std::isfinite(displacement_distance) || displacement_distance <= 0.0001f) {
        return;
    }

    const auto primary_divisor =
        (std::max)(0.0001f, ReadResolvedGameDoubleAsFloatOr(kActorWalkCyclePrimaryDivisorGlobal, 1.0f));
    const auto secondary_divisor =
        (std::max)(0.0001f, ReadResolvedGameDoubleAsFloatOr(kActorWalkCycleSecondaryDivisorGlobal, 1.0f));
    const auto primary_wrap_threshold =
        (std::max)(0.0001f, ReadResolvedGameFloatOr(kActorWalkCyclePrimaryWrapThresholdGlobal, 1.0f));
    const auto secondary_wrap_threshold =
        (std::max)(0.0001f, ReadResolvedGameFloatOr(kActorWalkCycleSecondaryWrapThresholdGlobal, 1.0f));
    const auto secondary_wrap_step =
        (std::max)(0.0001f, ReadResolvedGameDoubleAsFloatOr(kActorWalkCycleSecondaryWrapStepGlobal, secondary_wrap_threshold));
    const auto stride_step = ReadResolvedGameDoubleAsFloatOr(kActorWalkCycleStrideStepGlobal, 1.0f);

    auto primary = binding->dynamic_walk_cycle_primary;
    auto secondary = binding->dynamic_walk_cycle_secondary;

    primary += displacement_distance / primary_divisor;
    if (std::isfinite(primary) && primary_wrap_threshold > 0.0001f) {
        primary = std::fmod(primary, primary_wrap_threshold);
        if (primary < 0.0f) {
            primary += primary_wrap_threshold;
        }
    }

    secondary += displacement_distance / secondary_divisor;
    if (std::isfinite(secondary) && secondary_wrap_threshold > 0.0001f) {
        while (secondary >= secondary_wrap_threshold) {
            secondary -= secondary_wrap_step;
        }
        while (secondary < 0.0f) {
            secondary += secondary_wrap_step;
        }
    }

    binding->dynamic_walk_cycle_primary = primary;
    binding->dynamic_walk_cycle_secondary = secondary;
    binding->dynamic_render_drive_stride = stride_step;
    binding->dynamic_render_advance_rate = displacement_distance;
    binding->dynamic_render_drive_move_blend = 1.0f;
    binding->dynamic_render_advance_phase = primary;
}

void ClearWizardBotLocomotionInputs(uintptr_t actor_address) {
    if (!IsParticipantActorMemoryFreshWritable(actor_address)) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    (void)memory.TryWriteField(actor_address, kActorAnimationConfigBlockOffset, 0.0f);
    (void)memory.TryWriteField(actor_address, kActorAnimationDriveParameterOffset, 0.0f);
    (void)memory.TryWriteField(actor_address, kActorWalkCyclePrimaryOffset, 0.0f);
    (void)memory.TryWriteField(actor_address, kActorWalkCycleSecondaryOffset, 0.0f);
    (void)memory.TryWriteField(actor_address, kActorRenderDriveStrideScaleOffset, 0.0f);
    (void)memory.TryWriteField(actor_address, kActorRenderAdvanceRateOffset, 0.0f);
    (void)memory.TryWriteField(actor_address, kActorRenderAdvancePhaseOffset, 0.0f);
    (void)memory.TryWriteField(actor_address, kActorRenderDriveMoveBlendOffset, 0.0f);
}

void StopWizardBotActorMotion(uintptr_t actor_address) {
    if (actor_address == 0) {
        return;
    }

    // Standalone clone-rail bots seed the stock walk accumulators at +0x158/+0x15C
    // so our loader-owned MoveStep can mirror player movement. Once loader
    // movement stops, those accumulators must be cleared immediately; otherwise
    // the stock PlayerActorTick keeps consuming the stale vector and slides the
    // clone even while our controller is idle.
    ClearWizardBotLocomotionInputs(actor_address);

    std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
    if (auto* binding = FindParticipantEntityForActor(actor_address);
        binding != nullptr && binding->kind == ParticipantEntityBinding::Kind::StandaloneWizard) {
        ApplyObservedBotAnimationState(binding, actor_address, false);
        binding->dynamic_walk_cycle_primary = 0.0f;
        binding->dynamic_walk_cycle_secondary = 0.0f;
        binding->dynamic_render_drive_stride = 0.0f;
        binding->dynamic_render_advance_rate = 0.0f;
        binding->dynamic_render_advance_phase = 0.0f;
        binding->dynamic_render_drive_move_blend = 0.0f;
        ApplyStandaloneWizardDynamicAnimationState(binding, actor_address);
        return;
    }

    ApplyActorAnimationDriveState(actor_address, false);
}

void StopDeadWizardBotActorMotion(uintptr_t actor_address) {
    if (actor_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    // Dead bots are deliberately moved onto the player-family alternate/corpse
    // drive branch. That branch can look wrong for living idle bots, but it is
    // the stable "body on the ground" pose we want after HP reaches zero.
    // Keep the rest of the drive inputs zero so the actor remains inert.
    ClearWizardBotLocomotionInputs(actor_address);
    (void)memory.TryWriteField(
        actor_address,
        kActorAnimationDriveStateByteOffset,
        kDeadWizardBotCorpseDriveState);
    (void)memory.TryWriteField(actor_address, kActorAnimationMoveDurationTicksOffset, 0);
    (void)memory.TryWriteField(actor_address, kActorMoveStepScaleOffset, 0.0f);
    ResetStandaloneWizardControlBrain(actor_address);

    std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
    if (auto* binding = FindParticipantEntityForActor(actor_address);
        binding != nullptr && binding->kind == ParticipantEntityBinding::Kind::StandaloneWizard) {
        binding->dynamic_walk_cycle_primary = 0.0f;
        binding->dynamic_walk_cycle_secondary = 0.0f;
        binding->dynamic_render_drive_stride = 0.0f;
        binding->dynamic_render_advance_rate = 0.0f;
        binding->dynamic_render_advance_phase = 0.0f;
        binding->dynamic_render_drive_move_blend = 0.0f;
        ApplyStandaloneWizardDynamicAnimationState(binding, actor_address);
    }
}

void ApplyObservedBotAnimationState(ParticipantEntityBinding* binding, uintptr_t actor_address, bool moving) {
    if (binding == nullptr || actor_address == 0 || binding->kind != ParticipantEntityBinding::Kind::StandaloneWizard) {
        return;
    }

    ClearLiveWizardActorAnimationDriveState(actor_address);
    ApplyStandaloneWizardAnimationDriveProfile(binding, actor_address, moving);
    ApplyStandaloneWizardPuppetDriveState(binding, actor_address, moving);
    ApplyStandaloneWizardDynamicAnimationState(binding, actor_address);

    const auto desired_state_id = ResolveProfileSelectionState(binding->character_profile);
    if (TryWriteActorAnimationStateIdDirect(actor_address, desired_state_id)) {
        binding->last_applied_animation_state_id = desired_state_id;
        return;
    }

    binding->last_applied_animation_state_id = ResolveActorAnimationStateId(actor_address);
}

void LogWizardBotMovementFrame(
    ParticipantEntityBinding* binding,
    uintptr_t actor_address,
    uintptr_t owner_address,
    uintptr_t movement_controller_address,
    float direction_x,
    float direction_y,
    float velocity_x,
    float velocity_y,
    float position_before_x,
    float position_before_y,
    float position_after_x,
    float position_after_y,
    const char* path_label) {
    (void)owner_address;
    (void)movement_controller_address;
    (void)velocity_x;
    (void)velocity_y;
    if (binding == nullptr || actor_address == 0) {
        return;
    }
    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    (void)now_ms;
    auto& memory = ProcessMemory::Instance();
    const auto delta_x = position_after_x - position_before_x;
    const auto delta_y = position_after_y - position_before_y;
    const auto d = std::sqrt(delta_x * delta_x + delta_y * delta_y);
    const auto scale_0x74 = memory.ReadFieldOr<float>(actor_address, kActorMoveSpeedScaleOffset, 0.0f);
    const auto move_step_scale_0x218 =
        memory.ReadFieldOr<float>(actor_address, kActorMoveStepScaleOffset, 0.0f);
    const auto dir_x_0x158 =
        memory.ReadFieldOr<float>(actor_address, kActorAnimationConfigBlockOffset, 0.0f);
    const auto dir_y_0x15C =
        memory.ReadFieldOr<float>(actor_address, kActorAnimationDriveParameterOffset, 0.0f);
    Log(
        "[bots] standalone_mv bot=" + std::to_string(binding->bot_id) +
        " before=(" + std::to_string(position_before_x) + "," + std::to_string(position_before_y) + ")" +
        " after=(" + std::to_string(position_after_x) + "," + std::to_string(position_after_y) + ")" +
        " d=" + std::to_string(d) +
        " dir=(" + std::to_string(direction_x) + "," + std::to_string(direction_y) + ")" +
        " 0x74=" + std::to_string(scale_0x74) +
        " 0x218=" + std::to_string(move_step_scale_0x218) +
        " 0x158=" + std::to_string(dir_x_0x158) +
        " 0x15C=" + std::to_string(dir_y_0x15C) +
        " path=" + std::string(path_label != nullptr ? path_label : ""));
}

int ResolveCombatSelectionStateForSkillId(std::int32_t skill_id) {
    switch (skill_id) {
    case 0x18:
    case 0x20:
    case 0x28:
        return skill_id;
    case 0x3F2:
        return 0x08;
    case 0x3F3:
        return 0x10;
    case 0x3F5:
        return 0x18;
    case 0x3F4:
        return 0x20;
    case 0x3F6:
        return 0x28;
    case 0x3EB:
    case 0x3EC:
    case 0x3ED:
    case 0x3EE:
    case 0x3EF:
    case 0x3F0:
    case 0x3F1:
        return 0x34;
    default:
        return -1;
    }
}

int ResolveOngoingCastSelectionState(
    const ParticipantEntityBinding::OngoingCastState& ongoing) {
    if (ongoing.selection_state_target != kUnknownAnimationStateId &&
        ongoing.selection_state_target >= 0) {
        return ongoing.selection_state_target;
    }

    const auto active_skill_id =
        ongoing.uses_dispatcher_skill_id && ongoing.dispatcher_skill_id > 0
            ? ongoing.dispatcher_skill_id
            : ongoing.skill_id;
    return ResolveCombatSelectionStateForSkillId(active_skill_id);
}

void ReapplyOngoingCastSelectionState(
    ParticipantEntityBinding* binding,
    uintptr_t actor_address,
    const ParticipantEntityBinding::OngoingCastState& ongoing,
    bool write_actor_selection_state) {
    if (binding == nullptr ||
        actor_address == 0 ||
        !ongoing.gameplay_selection_state_override_active ||
        binding->gameplay_slot < 0) {
        return;
    }

    const auto selection_state = ResolveOngoingCastSelectionState(ongoing);
    if (selection_state < 0) {
        return;
    }

    if (write_actor_selection_state) {
        (void)TryWriteActorAnimationStateIdDirect(actor_address, selection_state);
    }

    std::string selection_error;
    (void)TryWriteGameplaySelectionStateForSlot(
        binding->gameplay_slot,
        selection_state,
        &selection_error);
}

std::string DescribeGameplaySlotCastStartupWindow(uintptr_t actor_address) {
    if (actor_address == 0) {
        return "actor=0x0";
    }

    auto& memory = ProcessMemory::Instance();
    const auto gameplay_global_flag_1abe =
        memory.ReadValueOr<std::uint8_t>(
            memory.ResolveGameAddressOrZero(0x0081C264 + 0x1ABE),
            0);
    const auto gameplay_global_flag_1abd =
        memory.ReadValueOr<std::uint8_t>(
            memory.ResolveGameAddressOrZero(0x0081C264 + 0x1ABD),
            0);
    const auto gameplay_global_flag_85 =
        memory.ReadValueOr<std::uint8_t>(
            memory.ResolveGameAddressOrZero(0x0081C264 + 0x85),
            0);
    const auto selection_ptr =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorAnimationSelectionStateOffset, 0);
    const auto control_brain_ptr =
        memory.ReadFieldOr<uintptr_t>(actor_address, 0x21C, 0);
    const auto control_brain_value =
        control_brain_ptr != 0 && memory.IsReadableRange(control_brain_ptr, sizeof(uintptr_t))
            ? memory.ReadValueOr<std::uint32_t>(control_brain_ptr, 0xFFFFFFFFu)
            : 0xFFFFFFFFu;
    const auto actor_dc_ptr =
        memory.ReadFieldOr<uintptr_t>(actor_address, 0xDC, 0);
    const auto actor_dc_vtable =
        actor_dc_ptr != 0 && memory.IsReadableRange(actor_dc_ptr, sizeof(uintptr_t))
            ? memory.ReadValueOr<uintptr_t>(actor_dc_ptr, 0)
            : 0;
    const auto actor_dc_slot_10 =
        actor_dc_ptr != 0 && memory.IsReadableRange(actor_dc_ptr + 0x10, sizeof(uintptr_t))
            ? memory.ReadValueOr<uintptr_t>(actor_dc_ptr + 0x10, 0)
            : 0;
    const auto actor_dc_callback_10 =
        actor_dc_vtable != 0 && memory.IsReadableRange(actor_dc_vtable + 0x10, sizeof(uintptr_t))
            ? memory.ReadValueOr<uintptr_t>(actor_dc_vtable + 0x10, 0)
            : 0;
    const auto progression_handle = memory.ReadFieldOr<uintptr_t>(actor_address, 0x300, 0);
    auto progression_runtime = memory.ReadFieldOr<uintptr_t>(actor_address, 0x200, 0);
    if (progression_runtime == 0 &&
        progression_handle != 0 &&
        memory.IsReadableRange(progression_handle, sizeof(uintptr_t))) {
        progression_runtime = memory.ReadValueOr<uintptr_t>(progression_handle, 0);
    }
    const auto read_progression_u32 = [&](std::size_t offset) -> std::uint32_t {
        return progression_runtime != 0 &&
               memory.IsReadableRange(progression_runtime + offset, sizeof(std::uint32_t))
            ? memory.ReadValueOr<std::uint32_t>(progression_runtime + offset, 0)
            : 0;
    };
    const auto read_progression_float = [&](std::size_t offset) -> float {
        return progression_runtime != 0 &&
               memory.IsReadableRange(progression_runtime + offset, sizeof(float))
            ? memory.ReadValueOr<float>(progression_runtime + offset, 0.0f)
            : 0.0f;
    };
    std::string selection_summary = "sel_ptr=" + HexString(selection_ptr);
    if (selection_ptr != 0) {
        selection_summary +=
            " sel_id=" + std::to_string(memory.ReadValueOr<int>(selection_ptr + 0x0, -9999)) +
            " sel_group=" + HexString(memory.ReadValueOr<std::uint8_t>(selection_ptr + 0x4, 0xFF)) +
            " sel_slot=" + HexString(memory.ReadValueOr<std::uint16_t>(selection_ptr + 0x6, 0xFFFF)) +
            " sel_t8=" + std::to_string(memory.ReadValueOr<int>(selection_ptr + 0x8, 0)) +
            " sel_tC=" + std::to_string(memory.ReadValueOr<int>(selection_ptr + 0xC, 0)) +
            " sel_t10=" + std::to_string(memory.ReadValueOr<int>(selection_ptr + 0x10, 0)) +
            " sel_t14=" + std::to_string(memory.ReadValueOr<int>(selection_ptr + 0x14, 0)) +
            " sel_a1c=" + std::to_string(memory.ReadValueOr<float>(selection_ptr + 0x1C, 0.0f)) +
            " sel_a20=" + std::to_string(memory.ReadValueOr<float>(selection_ptr + 0x20, 0.0f)) +
            " sel_f24=" + HexString(memory.ReadValueOr<std::uint8_t>(selection_ptr + 0x24, 0)) +
            " sel_v28=" + std::to_string(memory.ReadValueOr<float>(selection_ptr + 0x28, 0.0f)) +
            " sel_v2c=" + std::to_string(memory.ReadValueOr<float>(selection_ptr + 0x2C, 0.0f)) +
            " sel_v30=" + std::to_string(memory.ReadValueOr<float>(selection_ptr + 0x30, 0.0f)) +
            " sel_v34=" + std::to_string(memory.ReadValueOr<float>(selection_ptr + 0x34, 0.0f));
    }

    return
        "skill=" + std::to_string(memory.ReadFieldOr<std::int32_t>(actor_address, kActorPrimarySkillIdOffset, 0)) +
        " prev=" + std::to_string(memory.ReadFieldOr<std::int32_t>(actor_address, kActorPrimarySkillIdOffset + sizeof(std::int32_t), 0)) +
        " c21c=" + HexString(control_brain_ptr) +
        " c21c_val=" + HexString(control_brain_value) +
        " dc=" + HexString(actor_dc_ptr) +
        " dc_vt=" + HexString(actor_dc_vtable) +
        " dc_slot10=" + HexString(actor_dc_slot_10) +
        " dc_vt_cb10=" + HexString(actor_dc_callback_10) +
        " g1abe=" + HexString(gameplay_global_flag_1abe) +
        " g1abd=" + HexString(gameplay_global_flag_1abd) +
        " g85=" + HexString(gameplay_global_flag_85) +
        " e4=" + HexString(memory.ReadFieldOr<std::uint32_t>(actor_address, 0xE4, 0)) +
        " e8=" + HexString(memory.ReadFieldOr<std::uint32_t>(actor_address, 0xE8, 0)) +
        " a160=" + HexString(memory.ReadFieldOr<std::uint8_t>(actor_address, 0x160, 0)) +
        " a164=" + HexString(memory.ReadFieldOr<std::uint32_t>(actor_address, 0x164, 0)) +
        " a168=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorCurrentTargetActorOffset, 0)) +
        " a1ec=" + HexString(memory.ReadFieldOr<std::uint8_t>(actor_address, 0x1EC, 0)) +
        " a258=" + HexString(memory.ReadFieldOr<std::uint32_t>(actor_address, kActorContinuousPrimaryModeOffset, 0)) +
        " a264=" + HexString(memory.ReadFieldOr<std::uint32_t>(actor_address, kActorContinuousPrimaryActiveOffset, 0)) +
        " g27c=" + HexString(memory.ReadFieldOr<std::uint8_t>(actor_address, kActorActiveCastGroupByteOffset, 0xFF)) +
        " s27e=" + HexString(memory.ReadFieldOr<std::uint16_t>(actor_address, kActorActiveCastSlotShortOffset, 0xFFFF)) +
        " prog=" + HexString(progression_runtime) +
        " ph=" + HexString(progression_handle) +
        " p750=" + HexString(read_progression_u32(0x750)) +
        " p8a8=" + std::to_string(read_progression_float(0x8A8)) +
        " p8ac=" + std::to_string(read_progression_float(0x8AC)) +
        " p8b0=" + std::to_string(read_progression_float(0x8B0)) +
        " p8b4=" + std::to_string(read_progression_float(0x8B4)) +
        " f1b4=" + std::to_string(memory.ReadFieldOr<float>(actor_address, 0x1B4, 0.0f)) +
        " f1b8=" + std::to_string(memory.ReadFieldOr<float>(actor_address, 0x1B8, 0.0f)) +
        " f278=" + std::to_string(memory.ReadFieldOr<std::uint32_t>(actor_address, 0x278, 0)) +
        " f28c=" + std::to_string(memory.ReadFieldOr<float>(actor_address, 0x28C, 0.0f)) +
        " f290=" + std::to_string(memory.ReadFieldOr<float>(actor_address, 0x290, 0.0f)) +
        " f294=" + std::to_string(memory.ReadFieldOr<float>(actor_address, 0x294, 0.0f)) +
        " f298=" + std::to_string(memory.ReadFieldOr<std::uint32_t>(actor_address, 0x298, 0)) +
        " f29c=" + std::to_string(memory.ReadFieldOr<float>(actor_address, 0x29C, 0.0f)) +
        " f2a0=" + std::to_string(memory.ReadFieldOr<float>(actor_address, 0x2A0, 0.0f)) +
        " f2a4=" + std::to_string(memory.ReadFieldOr<float>(actor_address, 0x2A4, 0.0f)) +
        " aimx=" + std::to_string(memory.ReadFieldOr<float>(actor_address, kActorAimTargetXOffset, 0.0f)) +
        " aimy=" + std::to_string(memory.ReadFieldOr<float>(actor_address, kActorAimTargetYOffset, 0.0f)) +
        " aux0=" + HexString(memory.ReadFieldOr<std::uint32_t>(actor_address, kActorAimTargetAux0Offset, 0)) +
        " aux1=" + HexString(memory.ReadFieldOr<std::uint32_t>(actor_address, kActorAimTargetAux1Offset, 0)) +
        " spread=" + HexString(memory.ReadFieldOr<std::uint8_t>(actor_address, kActorCastSpreadModeByteOffset, 0)) +
        " f2c8=" + std::to_string(memory.ReadFieldOr<std::uint32_t>(actor_address, 0x2C8, 0)) +
        " f2cc=" + std::to_string(memory.ReadFieldOr<float>(actor_address, 0x2CC, 0.0f)) +
        " f2d0=" + std::to_string(memory.ReadFieldOr<float>(actor_address, 0x2D0, 0.0f)) +
        " f2d4=" + std::to_string(memory.ReadFieldOr<float>(actor_address, 0x2D4, 0.0f)) +
        " f2d8=" + std::to_string(memory.ReadFieldOr<float>(actor_address, 0x2D8, 0.0f)) +
        " heading=" + std::to_string(memory.ReadFieldOr<float>(actor_address, kActorHeadingOffset, 0.0f)) +
        " " + selection_summary;
}

bool SkillRequiresLocalSlotDuringNativeTick(std::int32_t skill_id) {
    // These stock spell families keep doing useful native work after the
    // startup edge. Gameplay-slot bots must keep masquerading as slot 0 for
    // that active window or projectile/cone emission can silently stop.
    switch (skill_id) {
    case 0x3EF:
    case 0x3F2:
    case 0x3F3:
    case 0x3F4:
    case 0x3F5:
    case 0x3F6:
    case 0x18:
    case 0x20:
    case 0x28:
        return true;
    default:
        return false;
    }
}

bool SkillRequiresHeldCastInputDuringNativeTick(std::int32_t skill_id) {
    // These stock primaries keep doing native work only while the gameplay cast
    // input is held. This is separate from live target tracking: projectile
    // families still keep their startup target captured, while channel families
    // keep refreshing their victim/aim lane.
    switch (skill_id) {
    case 0x3F2: // ether pure primary projectile stream
    case 0x3F3: // fire pure primary projectile stream
    case 0x3F4: // water pure primary
    case 0x3F5: // air pure primary
    case 0x18: // air primary handler
    case 0x20: // water primary handler
        return true;
    default:
        return false;
    }
}

bool SkillTracksLiveTargetDuringNativeTick(std::int32_t skill_id) {
    switch (skill_id) {
    case 0x3F4: // water pure primary cone
    case 0x3F5: // air pure primary beam
    case 0x18: // air primary handler
    case 0x20: // water primary handler
        return true;
    default:
        return false;
    }
}

bool SkillRequiresBoundedHeldCastInputDuringNativeTick(std::int32_t skill_id) {
    // Earth is a projectile/effect primary, but the stock dispatcher needs the
    // cast input held until the native boulder object reaches its configured
    // max size. The release path watches the live object instead of assuming a
    // fixed gesture duration.
    switch (skill_id) {
    case 0x3F6: // earth pure primary build id
    case 0x28: // earth primary handler
        return true;
    default:
        return false;
    }
}

bool SkillRequiresSyntheticCastInputDuringNativeTick(std::int32_t skill_id) {
    return SkillRequiresHeldCastInputDuringNativeTick(skill_id) ||
           SkillRequiresBoundedHeldCastInputDuringNativeTick(skill_id);
}

bool OngoingCastShouldDriveSyntheticCastInput(
    const ParticipantEntityBinding::OngoingCastState& ongoing) {
    const auto active_skill_id =
        ongoing.uses_dispatcher_skill_id && ongoing.dispatcher_skill_id > 0
            ? ongoing.dispatcher_skill_id
            : ongoing.skill_id;
    if (ongoing.startup_in_progress) {
        return true;
    }
    if (SkillRequiresHeldCastInputDuringNativeTick(active_skill_id)) {
        return true;
    }
    if (SkillRequiresBoundedHeldCastInputDuringNativeTick(active_skill_id)) {
        return !ongoing.bounded_release_requested;
    }
    return false;
}

int ResolveBotCastGestureTicks(std::int32_t skill_id) {
    // The bot cast request models one primary-input gesture. Stock held spells
    // do not self-release while input is held, so the loader must release the
    // synthetic gesture once the native active window has had time to run.
    switch (skill_id) {
    case 0x3EF:
    case 0x3F2: // ether pure primary projectile
    case 0x3F3: // fire pure primary projectile
        return 36;
    default:
        return ParticipantEntityBinding::OngoingCastState::kMaxTicksWaiting;
    }
}

int ResolveBotCastSafetyCapTicks(std::int32_t skill_id) {
    switch (skill_id) {
    case 0x3F6: // earth pure primary build id
    case 0x28: // earth primary handler
        return 1200;
    default:
        return ParticipantEntityBinding::OngoingCastState::kMaxTicksWaiting;
    }
}

std::int32_t ResolveOngoingNativeTickSkillId(
    const ParticipantEntityBinding::OngoingCastState& ongoing) {
    return ongoing.uses_dispatcher_skill_id && ongoing.dispatcher_skill_id > 0
        ? ongoing.dispatcher_skill_id
        : ongoing.skill_id;
}

bool OngoingCastShouldUseLiveFacingTarget(
    const ParticipantEntityBinding::OngoingCastState& ongoing) {
    return SkillTracksLiveTargetDuringNativeTick(
        ResolveOngoingNativeTickSkillId(ongoing));
}

bool OngoingCastShouldRefreshNativeTargetState(
    const ParticipantEntityBinding::OngoingCastState& ongoing) {
    const auto active_skill_id = ResolveOngoingNativeTickSkillId(ongoing);
    if (SkillRequiresBoundedHeldCastInputDuringNativeTick(active_skill_id) &&
        ongoing.bounded_release_requested) {
        return false;
    }
    return ongoing.startup_in_progress ||
           SkillTracksLiveTargetDuringNativeTick(active_skill_id) ||
           SkillRequiresBoundedHeldCastInputDuringNativeTick(active_skill_id);
}

uintptr_t ResolveOngoingCastNativeTargetActor(
    const ParticipantEntityBinding* binding,
    const ParticipantEntityBinding::OngoingCastState& ongoing) {
    if (binding != nullptr &&
        OngoingCastShouldUseLiveFacingTarget(ongoing) &&
        binding->facing_target_actor_address != 0) {
        return binding->facing_target_actor_address;
    }
    if (ongoing.target_actor_address != 0) {
        return ongoing.target_actor_address;
    }
    return binding != nullptr ? binding->facing_target_actor_address : 0;
}

int ResolveMaxStartupTicksWaiting(std::int32_t skill_id) {
    if (skill_id == 0x3EF) {
        // Iceblast advances an internal startup counter at actor+0x278 and can
        // legitimately defer projectile allocation past the generic 12-tick
        // window. Cutting it off early produces the exact "animation only,
        // nothing emitted" symptom we were seeing in live runs.
        return 90;
    }
    return ParticipantEntityBinding::OngoingCastState::kMaxStartupTicksWaiting;
}

void PrimeGameplaySlotPostGateDispatchState(uintptr_t actor_address, std::int32_t skill_id) {
    if (actor_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    const auto kActorPreviousSkillIdOffset =
        kActorPrimarySkillIdOffset + sizeof(std::int32_t);
    constexpr std::size_t kActorPostGateActiveByteOffset = 0x26C;
    constexpr std::size_t kActorStartupCounterOffset = 0x278;

    (void)memory.TryWriteField<std::int32_t>(
        actor_address,
        kActorPrimarySkillIdOffset,
        skill_id);
    (void)memory.TryWriteField<std::int32_t>(
        actor_address,
        kActorPreviousSkillIdOffset,
        0);
    (void)memory.TryWriteField<std::uint8_t>(
        actor_address,
        kActorPostGateActiveByteOffset,
        static_cast<std::uint8_t>(1));
    (void)memory.TryWriteField<std::int32_t>(
        actor_address,
        kActorStartupCounterOffset,
        0);
    if (!SkillRequiresNativeActorTargetHandle(skill_id)) {
        (void)memory.TryWriteField<std::uint8_t>(
            actor_address,
            kActorSpellTargetGroupByteOffset,
            kTargetHandleGroupSentinel);
        (void)memory.TryWriteField<std::uint16_t>(
            actor_address,
            kActorSpellTargetSlotShortOffset,
            kTargetHandleSlotSentinel);
    }
}

void RestoreSelectionBrainAfterCast(
    const ParticipantEntityBinding::OngoingCastState& state) {
    if (!state.selection_brain_override_active || state.selection_state_pointer == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    (void)memory.TryWriteField<std::uint8_t>(
        state.selection_state_pointer,
        0x04,
        state.selection_target_group_before);
    (void)memory.TryWriteField<std::uint16_t>(
        state.selection_state_pointer,
        0x06,
        state.selection_target_slot_before);
    (void)memory.TryWriteField<std::int32_t>(
        state.selection_state_pointer,
        0x08,
        state.selection_retarget_ticks_before);
    (void)memory.TryWriteField<std::int32_t>(
        state.selection_state_pointer,
        0x0C,
        state.selection_target_cooldown_before);
    (void)memory.TryWriteField<std::int32_t>(
        state.selection_state_pointer,
        0x10,
        state.selection_target_extra_before);
    (void)memory.TryWriteField<std::int32_t>(
        state.selection_state_pointer,
        0x14,
        state.selection_target_flags_before);
}

void ClearSelectionBrainTarget(uintptr_t selection_state_pointer) {
    if (selection_state_pointer == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    (void)memory.TryWriteField<std::uint8_t>(selection_state_pointer, 0x04, 0xFF);
    (void)memory.TryWriteField<std::uint16_t>(selection_state_pointer, 0x06, 0xFFFF);
    (void)memory.TryWriteField<std::int32_t>(
        selection_state_pointer,
        0x08,
        kSuppressedSelectionRetargetTicks);
    (void)memory.TryWriteField<std::int32_t>(selection_state_pointer, 0x0C, 0);
    (void)memory.TryWriteField<std::int32_t>(selection_state_pointer, 0x10, 0);
    (void)memory.TryWriteField<std::int32_t>(selection_state_pointer, 0x14, 0);
}

void RefreshSelectionBrainTargetForOngoingCast(
    const ParticipantEntityBinding::OngoingCastState& state) {
    if (!state.active || !state.selection_target_seed_active ||
        state.selection_state_pointer == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    const auto hold_ticks =
        state.selection_target_hold_ticks > 0 ? state.selection_target_hold_ticks : 60;
    (void)memory.TryWriteField<std::uint8_t>(
        state.selection_state_pointer,
        0x04,
        state.selection_target_group_seed);
    (void)memory.TryWriteField<std::uint16_t>(
        state.selection_state_pointer,
        0x06,
        state.selection_target_slot_seed);
    (void)memory.TryWriteField<std::int32_t>(state.selection_state_pointer, 0x08, hold_ticks);
    (void)memory.TryWriteField<std::int32_t>(state.selection_state_pointer, 0x0C, 0);
    (void)memory.TryWriteField<std::int32_t>(state.selection_state_pointer, 0x10, 0);
    (void)memory.TryWriteField<std::int32_t>(state.selection_state_pointer, 0x14, 0);
}

void RestoreSelectionStateObjectAfterCast(
    const ParticipantEntityBinding::OngoingCastState& state) {
    if (!state.selection_state_object_snapshot_valid || state.selection_state_pointer == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    (void)memory.TryWrite(
        state.selection_state_pointer,
        state.selection_state_object_snapshot.data(),
        state.selection_state_object_snapshot.size());
}

void PrimeSelectionBrainForCastStartup(
    uintptr_t actor_address,
    uintptr_t selection_pointer,
    uintptr_t target_actor_address,
    ParticipantEntityBinding::OngoingCastState* ongoing) {
    if (selection_pointer == 0 || ongoing == nullptr) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    const auto actor_owner =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, 0);
    const auto target_owner =
        memory.ReadFieldOr<uintptr_t>(target_actor_address, kActorOwnerOffset, 0);
    const auto target_group =
        memory.ReadFieldOr<std::uint8_t>(
            target_actor_address,
            kActorSlotOffset,
            kTargetHandleGroupSentinel);
    const auto target_slot =
        memory.ReadFieldOr<std::uint16_t>(target_actor_address, kActorWorldSlotOffset, kTargetHandleSlotSentinel);
    const bool have_explicit_target_handle =
        target_actor_address != 0 &&
        actor_owner != 0 &&
        actor_owner == target_owner &&
        target_group != kTargetHandleGroupSentinel &&
        target_slot != kTargetHandleSlotSentinel;

    ongoing->selection_target_group_before =
        memory.ReadValueOr<std::uint8_t>(selection_pointer + 0x04, kTargetHandleGroupSentinel);
    ongoing->selection_target_slot_before =
        memory.ReadValueOr<std::uint16_t>(selection_pointer + 0x06, kTargetHandleSlotSentinel);
    ongoing->selection_retarget_ticks_before =
        memory.ReadValueOr<std::int32_t>(selection_pointer + 0x08, 0);
    ongoing->selection_target_cooldown_before =
        memory.ReadValueOr<std::int32_t>(selection_pointer + 0x0C, 0);
    ongoing->selection_target_extra_before =
        memory.ReadValueOr<std::int32_t>(selection_pointer + 0x10, 0);
    ongoing->selection_target_flags_before =
        memory.ReadValueOr<std::int32_t>(selection_pointer + 0x14, 0);
    ongoing->selection_brain_override_active = true;

    // PlayerActorTick clears actor+0x270 every tick and only rebuilds it when
    // FUN_0052C910 produces a non-zero control vector. That helper drives from
    // the actor-owned +0x21C control brain. The stock function decrements +0x08
    // first and only keeps the cached target handle on the cooldown path; when
    // +0x08 hits zero it re-runs candidate search and overwrites +0x04/+0x06.
    // For pure-primary bot startup, the Lua brain has already picked the real
    // hostile. Seed that exact stock target handle into +0x04/+0x06 and keep
    // +0x08 positive so stock stays on the "use cached target" path instead of
    // discarding it before the cast gate evaluates cVar5.
    if (have_explicit_target_handle) {
        ongoing->selection_target_seed_active = true;
        ongoing->selection_target_group_seed = target_group;
        ongoing->selection_target_slot_seed = target_slot;
        ongoing->selection_target_hold_ticks = 60;
        (void)memory.TryWriteField<std::uint8_t>(selection_pointer, 0x04, target_group);
        (void)memory.TryWriteField<std::uint16_t>(selection_pointer, 0x06, target_slot);
        (void)memory.TryWriteField<std::int32_t>(selection_pointer, 0x08, ongoing->selection_target_hold_ticks);
    } else {
        ongoing->selection_target_seed_active = false;
        ongoing->selection_target_group_seed = kTargetHandleGroupSentinel;
        ongoing->selection_target_slot_seed = kTargetHandleSlotSentinel;
        ongoing->selection_target_hold_ticks = 0;
        (void)memory.TryWriteField<std::uint8_t>(
            selection_pointer,
            0x04,
            kTargetHandleGroupSentinel);
        (void)memory.TryWriteField<std::uint16_t>(
            selection_pointer,
            0x06,
            kTargetHandleSlotSentinel);
        (void)memory.TryWriteField<std::int32_t>(selection_pointer, 0x08, 0);
    }
    (void)memory.TryWriteField<std::int32_t>(selection_pointer, 0x0C, 0);
    (void)memory.TryWriteField<std::int32_t>(selection_pointer, 0x10, 0);
    (void)memory.TryWriteField<std::int32_t>(selection_pointer, 0x14, 0);
}

bool PreparePendingGameplaySlotBotCast(ParticipantEntityBinding* binding, std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (binding == nullptr || binding->actor_address == 0 || binding->bot_id == 0 ||
        !IsGameplaySlotWizardKind(binding->kind)) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto actor_address = binding->actor_address;
    constexpr float kRadiansToDegrees = 57.2957795130823208767981548141051703f;
    constexpr std::uint8_t kActorActiveCastGroupSentinel = 0xFF;
    constexpr std::uint16_t kActorActiveCastSlotSentinel = 0xFFFF;
    const auto kActorPreviousSkillIdOffset =
        kActorPrimarySkillIdOffset + sizeof(std::int32_t);
    constexpr std::size_t kProgressionCurrentSpellIdOffset = 0x750;
    const auto finish_attack_idle = [&]() {
        const auto heading =
            memory.ReadFieldOr<float>(actor_address, kActorHeadingOffset, 0.0f);
        (void)multiplayer::FinishBotAttack(binding->bot_id, true, heading, true);
    };

    auto ApplyPreparedState = [&](ParticipantEntityBinding::OngoingCastState* ongoing) {
        if (ongoing == nullptr) {
            return;
        }

        if (ongoing->gameplay_selection_state_override_active &&
            binding->gameplay_slot >= 0) {
            const auto combat_selection_state = ResolveOngoingCastSelectionState(*ongoing);
            if (combat_selection_state >= 0) {
                std::string selection_error;
                (void)TryWriteActorAnimationStateIdDirect(actor_address, combat_selection_state);
                (void)TryWriteGameplaySelectionStateForSlot(
                    binding->gameplay_slot,
                    combat_selection_state,
                    &selection_error);
            }
        }
        if (ongoing->progression_spell_id_override_active && ongoing->progression_runtime_address != 0) {
            (void)memory.TryWriteField<std::int32_t>(
                ongoing->progression_runtime_address,
                kProgressionCurrentSpellIdOffset,
                ongoing->skill_id);
        }
        if (ongoing->have_aim_heading) {
            ApplyWizardActorFacingState(actor_address, ongoing->aim_heading);
        }
        if (ongoing->have_aim_target) {
            (void)memory.TryWriteField(actor_address, kActorAimTargetXOffset, ongoing->aim_target_x);
            (void)memory.TryWriteField(actor_address, kActorAimTargetYOffset, ongoing->aim_target_y);
            (void)memory.TryWriteField<std::uint32_t>(actor_address, kActorAimTargetAux0Offset, 0);
            (void)memory.TryWriteField<std::uint32_t>(actor_address, kActorAimTargetAux1Offset, 0);
        }
        (void)memory.TryWriteField<std::uint8_t>(actor_address, kActorCastSpreadModeByteOffset, 0);
        (void)memory.TryWriteField<std::int32_t>(
            actor_address,
            kActorPrimarySkillIdOffset,
            ongoing->uses_dispatcher_skill_id ? ongoing->dispatcher_skill_id : 0);
        (void)memory.TryWriteField<std::int32_t>(actor_address, kActorPreviousSkillIdOffset, 0);
    };

    auto RollbackPreparedStartup = [&](ParticipantEntityBinding::OngoingCastState* ongoing) {
        if (ongoing == nullptr) {
            return;
        }

        RestoreSelectionBrainAfterCast(*ongoing);
        ClearSelectionBrainTarget(ongoing->selection_state_pointer);
        RestoreOngoingCastNativeTargetActor(actor_address, *ongoing);
        binding->facing_target_actor_address = 0;
        if (ongoing->gameplay_selection_state_override_active &&
            binding->gameplay_slot >= 0 &&
            ongoing->gameplay_selection_state_before != kUnknownAnimationStateId) {
            std::string selection_error;
            if (ongoing->lane != ParticipantEntityBinding::OngoingCastState::Lane::PurePrimary) {
                (void)TryWriteActorAnimationStateIdDirect(
                    actor_address,
                    ongoing->gameplay_selection_state_before);
            }
            (void)TryWriteGameplaySelectionStateForSlot(
                binding->gameplay_slot,
                ongoing->gameplay_selection_state_before,
                &selection_error);
        }
        if (ongoing->progression_spell_id_override_active &&
            ongoing->progression_runtime_address != 0) {
            (void)memory.TryWriteField<std::int32_t>(
                ongoing->progression_runtime_address,
                kProgressionCurrentSpellIdOffset,
                ongoing->progression_spell_id_before);
        }
        *ongoing = ParticipantEntityBinding::OngoingCastState{};
    };

    multiplayer::BotCastRequest request{};
    if (!multiplayer::ConsumePendingBotCast(binding->bot_id, &request)) {
        return false;
    }
    const auto queued_target_actor_address = request.target_actor_address;
    int requested_skill_id = request.skill_id;
    ResolvedPrimaryCastDescriptor primary_descriptor{};
    bool have_primary_descriptor = false;
    if (requested_skill_id <= 0 && request.kind == multiplayer::BotCastKind::Primary) {
        if (!TryResolveProfilePrimaryCastDescriptor(
                binding->character_profile,
                &primary_descriptor)) {
            finish_attack_idle();
            if (error_message != nullptr) {
                *error_message =
                    "primary cast has no stock loadout pair. primary=" +
                    std::to_string(primary_descriptor.primary_entry_index) +
                    " combo=" + std::to_string(primary_descriptor.combo_entry_index);
            }
            return false;
        }
        have_primary_descriptor = true;
        requested_skill_id = primary_descriptor.dispatcher_skill_id;
    }
    if (requested_skill_id <= 0 &&
        (!have_primary_descriptor ||
         primary_descriptor.lane ==
             ParticipantEntityBinding::OngoingCastState::Lane::Dispatcher)) {
        finish_attack_idle();
        if (error_message != nullptr) {
            *error_message = "cast has no resolvable skill_id";
        }
        return false;
    }

    const auto combat_selection_state =
        have_primary_descriptor
            ? primary_descriptor.selection_state
            : ResolveCombatSelectionStateForSkillId(requested_skill_id);
    if (combat_selection_state < 0) {
        finish_attack_idle();
        if (error_message != nullptr) {
            *error_message = "unsupported gameplay-slot stock cast skill_id=" + std::to_string(requested_skill_id);
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
            aim_heading = std::atan2(dy, dx) * kRadiansToDegrees + 90.0f;
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

    auto& ongoing = binding->ongoing_cast;
    ongoing = ParticipantEntityBinding::OngoingCastState{};
    ongoing.active = true;
    ongoing.lane =
        have_primary_descriptor
            ? primary_descriptor.lane
            : ParticipantEntityBinding::OngoingCastState::Lane::Dispatcher;
    ongoing.skill_id =
        have_primary_descriptor && primary_descriptor.build_skill_id > 0
            ? primary_descriptor.build_skill_id
            : requested_skill_id;
    ongoing.dispatcher_skill_id = requested_skill_id;
    ongoing.selection_state_target = combat_selection_state;
    ongoing.uses_dispatcher_skill_id =
        ongoing.lane == ParticipantEntityBinding::OngoingCastState::Lane::Dispatcher &&
        ongoing.dispatcher_skill_id > 0;
    ongoing.have_aim_heading = have_aim_heading;
    ongoing.aim_heading = aim_heading;
    ongoing.have_aim_target = have_aim_target;
    ongoing.aim_target_x = aim_target_x;
    ongoing.aim_target_y = aim_target_y;
    ongoing.target_actor_address = effective_target_actor_address;
    if (have_aim_heading) {
        binding->facing_heading_value = aim_heading;
        binding->facing_heading_valid = true;
    }
    ongoing.heading_before = memory.ReadFieldOr<float>(actor_address, kActorHeadingOffset, 0.0f);
    ongoing.aim_x_before = memory.ReadFieldOr<float>(actor_address, kActorAimTargetXOffset, 0.0f);
    ongoing.aim_y_before = memory.ReadFieldOr<float>(actor_address, kActorAimTargetYOffset, 0.0f);
    ongoing.aim_aux0_before =
        memory.ReadFieldOr<std::uint32_t>(actor_address, kActorAimTargetAux0Offset, 0);
    ongoing.aim_aux1_before =
        memory.ReadFieldOr<std::uint32_t>(actor_address, kActorAimTargetAux1Offset, 0);
    ongoing.spread_before =
        memory.ReadFieldOr<std::uint8_t>(actor_address, kActorCastSpreadModeByteOffset, 0);

    ongoing.selection_state_pointer =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorAnimationSelectionStateOffset, 0);
    if (ongoing.lane == ParticipantEntityBinding::OngoingCastState::Lane::PurePrimary &&
        ongoing.selection_state_pointer != 0 &&
        memory.IsReadableRange(
            ongoing.selection_state_pointer,
            ongoing.selection_state_object_snapshot.size()) &&
        memory.TryRead(
            ongoing.selection_state_pointer,
            ongoing.selection_state_object_snapshot.data(),
            ongoing.selection_state_object_snapshot.size())) {
        ongoing.selection_state_object_snapshot_valid = true;
    }
    if (ongoing.selection_state_pointer != 0) {
        PrimeSelectionBrainForCastStartup(
            actor_address,
            ongoing.selection_state_pointer,
            effective_target_actor_address,
            &ongoing);
    }
    ongoing.selection_state_before = ResolveActorAnimationStateId(actor_address);
    if (binding->gameplay_slot >= 0 && ongoing.selection_state_before != kUnknownAnimationStateId) {
        ongoing.gameplay_selection_state_before = ongoing.selection_state_before;
        std::string selection_error;
        if (ongoing.lane != ParticipantEntityBinding::OngoingCastState::Lane::PurePrimary) {
            (void)TryWriteActorAnimationStateIdDirect(actor_address, combat_selection_state);
        }
        ongoing.gameplay_selection_state_override_active =
            TryWriteGameplaySelectionStateForSlot(
                binding->gameplay_slot,
                combat_selection_state,
                &selection_error);
    }

    if (TryResolveActorProgressionRuntime(actor_address, &ongoing.progression_runtime_address) &&
        ongoing.progression_runtime_address != 0) {
        ongoing.progression_spell_id_before =
            memory.ReadFieldOr<std::int32_t>(
                ongoing.progression_runtime_address,
                kProgressionCurrentSpellIdOffset,
                0);
        if (request.kind == multiplayer::BotCastKind::Primary && request.skill_id <= 0) {
            int resolved_primary_skill_id = -1;
            std::string loadout_error;
            if (!ApplyProfilePrimaryLoadoutToSkillsWizard(
                    ongoing.progression_runtime_address,
                    binding->character_profile,
                    &resolved_primary_skill_id,
                    &loadout_error)) {
                RollbackPreparedStartup(&ongoing);
                finish_attack_idle();
                if (error_message != nullptr) {
                    *error_message = std::move(loadout_error);
                }
                return false;
            }
            const auto refresh_progression_address =
                memory.ResolveGameAddressOrZero(kActorProgressionRefresh);
            DWORD refresh_exception_code = 0;
            if (refresh_progression_address == 0 ||
                !CallActorProgressionRefreshSafe(
                    refresh_progression_address,
                    actor_address,
                    &refresh_exception_code)) {
                RollbackPreparedStartup(&ongoing);
                finish_attack_idle();
                if (error_message != nullptr) {
                    *error_message =
                        refresh_progression_address == 0
                            ? "Unable to resolve ActorProgressionRefresh."
                            : "Actor progression refresh (post primary build) failed with 0x" +
                                HexString(refresh_exception_code) + ".";
                }
                return false;
            }
            if (resolved_primary_skill_id > 0) {
                ongoing.skill_id = resolved_primary_skill_id;
            }
            if (ongoing.lane == ParticipantEntityBinding::OngoingCastState::Lane::PurePrimary) {
                ongoing.progression_spell_id_override_active =
                    memory.TryWriteField<std::int32_t>(
                        ongoing.progression_runtime_address,
                        kProgressionCurrentSpellIdOffset,
                        ongoing.skill_id);
            }
        } else {
            ongoing.progression_spell_id_override_active =
                memory.TryWriteField<std::int32_t>(
                    ongoing.progression_runtime_address,
                    kProgressionCurrentSpellIdOffset,
                    requested_skill_id);
        }
    }
    const auto native_tick_skill_id =
        ongoing.uses_dispatcher_skill_id && ongoing.dispatcher_skill_id > 0
            ? ongoing.dispatcher_skill_id
            : ongoing.skill_id;
    ongoing.requires_local_slot_native_tick =
        SkillRequiresLocalSlotDuringNativeTick(native_tick_skill_id);
    const auto cast_mana =
        multiplayer::ResolveBotCastManaCost(
            binding->character_profile,
            request.kind,
            request.secondary_slot,
            ongoing.skill_id);
    if (!cast_mana.resolved) {
        Log(
            "[bots] mana rejected. bot_id=" + std::to_string(binding->bot_id) +
            " skill_id=" + std::to_string(ongoing.skill_id) +
            " kind=" + (request.kind == multiplayer::BotCastKind::Primary ? std::string("primary") : std::string("secondary")) +
            " slot=" + std::to_string(request.secondary_slot) +
            " mode=unknown");
        RollbackPreparedStartup(&ongoing);
        finish_attack_idle();
        if (error_message != nullptr) {
            *error_message = "unknown mana cost for bot cast";
        }
        return false;
    }
    ongoing.mana_charge_kind = cast_mana.kind;
    ongoing.mana_cost = cast_mana.cost;
    ongoing.mana_statbook_level = cast_mana.statbook_level;
    ongoing.mana_last_charge_ms = static_cast<std::uint64_t>(GetTickCount64());
    if (cast_mana.kind != multiplayer::BotManaChargeKind::None) {
        if (ongoing.progression_runtime_address == 0) {
            RollbackPreparedStartup(&ongoing);
            finish_attack_idle();
            if (error_message != nullptr) {
                *error_message = "bot cast requires mana but has no progression runtime";
            }
            return false;
        }

        if (cast_mana.kind == multiplayer::BotManaChargeKind::PerCast) {
            float current_mp = 0.0f;
            float max_mp = 0.0f;
            if (!TryReadProgressionMana(ongoing.progression_runtime_address, &current_mp, &max_mp) ||
                current_mp + 0.001f < cast_mana.cost) {
                Log(
                    "[bots] mana rejected. bot_id=" + std::to_string(binding->bot_id) +
                    " skill_id=" + std::to_string(ongoing.skill_id) +
                    " kind=" + (request.kind == multiplayer::BotCastKind::Primary ? std::string("primary") : std::string("secondary")) +
                    " slot=" + std::to_string(request.secondary_slot) +
                    " mode=per_cast cost=" + std::to_string(cast_mana.cost) +
                    " before=" + std::to_string(current_mp));
                RollbackPreparedStartup(&ongoing);
                finish_attack_idle();
                if (error_message != nullptr) {
                    *error_message = "insufficient mana for bot cast";
                }
                return false;
            }
        } else {
            float current_mp = 0.0f;
            float max_mp = 0.0f;
            const float required_mana =
                multiplayer::ResolveBotManaRequiredToStart(cast_mana);
            if (!TryReadProgressionMana(ongoing.progression_runtime_address, &current_mp, &max_mp) ||
                current_mp + 0.001f < required_mana) {
                Log(
                    "[bots] mana rejected. bot_id=" + std::to_string(binding->bot_id) +
                    " skill_id=" + std::to_string(ongoing.skill_id) +
                    " kind=" + (request.kind == multiplayer::BotCastKind::Primary ? std::string("primary") : std::string("secondary")) +
                    " slot=" + std::to_string(request.secondary_slot) +
                    " mode=per_second rate=" + std::to_string(cast_mana.cost) +
                    " required=" + std::to_string(required_mana) +
                    " before=" + std::to_string(current_mp));
                RollbackPreparedStartup(&ongoing);
                finish_attack_idle();
                if (error_message != nullptr) {
                    *error_message = "insufficient mana for held bot cast";
                }
                return false;
            }
        }
    }
    ongoing.startup_in_progress = true;
    ongoing.startup_ticks_waiting = 0;
    if (ongoing.target_actor_address != 0) {
        (void)WriteOngoingCastNativeTargetActor(
            actor_address,
            &ongoing,
            ongoing.target_actor_address);
    }

    const auto cleanup_address = memory.ResolveGameAddressOrZero(kCastActiveHandleCleanup);
    const auto active_cast_group_before =
        memory.ReadFieldOr<std::uint8_t>(actor_address, kActorActiveCastGroupByteOffset, 0);
    if (cleanup_address != 0 && active_cast_group_before != kActorActiveCastGroupSentinel) {
        LocalPlayerCastShimState shim_state;
        const auto shim_active = EnterLocalPlayerCastShim(binding, &shim_state);
        DWORD cleanup_exception_code = 0;
        const auto cleanup_ok = shim_active &&
            CallCastActiveHandleCleanupSafe(cleanup_address, actor_address, &cleanup_exception_code);
        LeaveLocalPlayerCastShim(shim_state);
        if (!cleanup_ok) {
            (void)memory.TryWriteField<std::uint8_t>(
                actor_address, kActorActiveCastGroupByteOffset, kActorActiveCastGroupSentinel);
            (void)memory.TryWriteField<std::uint16_t>(
                actor_address, kActorActiveCastSlotShortOffset, kActorActiveCastSlotSentinel);
        }
    }

    ApplyPreparedState(&ongoing);
    bool pure_primary_primer_called = false;
    DWORD pure_primary_primer_exception = 0;
    const bool dispatcher_primary_uses_primer =
        have_primary_descriptor &&
        ongoing.uses_dispatcher_skill_id &&
        !SkillRequiresBoundedHeldCastInputDuringNativeTick(ongoing.dispatcher_skill_id);
    const bool should_run_primary_damage_primer =
        request.kind == multiplayer::BotCastKind::Primary &&
        (ongoing.lane == ParticipantEntityBinding::OngoingCastState::Lane::PurePrimary ||
         dispatcher_primary_uses_primer);
    if (should_run_primary_damage_primer) {
        const auto pure_primary_start_address =
            memory.ResolveGameAddressOrZero(kSpellCastPurePrimary);
        if (pure_primary_start_address != 0) {
            LocalPlayerCastShimState shim_state;
            const auto shim_active = EnterLocalPlayerCastShim(binding, &shim_state);
            pure_primary_primer_called =
                shim_active &&
                CallPurePrimarySpellStartSafe(
                    pure_primary_start_address,
                    actor_address,
                    &pure_primary_primer_exception);
            LeaveLocalPlayerCastShim(shim_state);
        }
        if (pure_primary_primer_called && ongoing.uses_dispatcher_skill_id) {
            PrimeGameplaySlotPostGateDispatchState(actor_address, ongoing.dispatcher_skill_id);
            if (ongoing.target_actor_address != 0) {
                (void)WriteOngoingCastNativeTargetActor(
                    actor_address,
                    &ongoing,
                    ongoing.target_actor_address);
            }
            ReapplyOngoingCastSelectionState(binding, actor_address, ongoing, true);
        }
    }
    g_gameplay_slot_hud_probe_actor = actor_address;
    g_gameplay_slot_hud_probe_until_ms = static_cast<std::uint64_t>(GetTickCount64()) + 400;
    Log(
        "[bots] gameplay-slot cast prepped. bot_id=" + std::to_string(binding->bot_id) +
        " skill_id=" + std::to_string(ongoing.skill_id) +
        " dispatcher_skill_id=" + std::to_string(ongoing.dispatcher_skill_id) +
        " lane=" +
            (ongoing.lane == ParticipantEntityBinding::OngoingCastState::Lane::PurePrimary
                 ? std::string("pure_primary")
                 : std::string("dispatcher")) +
        " selection_state=" + std::to_string(combat_selection_state) +
        " progression_runtime=" + HexString(ongoing.progression_runtime_address) +
        " progression_spell_id=" + std::to_string(
            ongoing.progression_runtime_address != 0
                ? memory.ReadFieldOr<std::int32_t>(
                      ongoing.progression_runtime_address,
                      kProgressionCurrentSpellIdOffset,
                      0)
                : 0) +
        " pure_primary_primer=" + std::to_string(pure_primary_primer_called ? 1 : 0) +
        " pure_primary_primer_seh=" + HexString(pure_primary_primer_exception) +
        " selection_ptr=" + HexString(ongoing.selection_state_pointer) +
        " startup={" + DescribeGameplaySlotCastStartupWindow(actor_address) + "}");
    return true;
}

// Cast architecture (standalone verified 2026-04-20; gameplay-slot fix 2026-04-21):
//
//   * Player flow: input sets actor+0x270 (primary skill id); PlayerActorTick
//     (0x00548B00) calls FUN_00548A00 every gameplay tick; FUN_00548A00 routes
//     by actor+0x270 to the per-spell handler (e.g. FUN_00545360 for 0x3EE).
//     The handler owns a cached spell-object handle stored at actor+0x27C
//     (group byte) + actor+0x27E (world slot short). It latches cast-active
//     state via actor+0x160 (animation_drive_state) and actor+0x1EC
//     (mNoInterrupt). When the handler decides the cast is done it clears
//     both latch fields. PlayerActorTick's skill-transition block
//     (0x5496e5..0x5497ac) then calls FUN_0052F3B0 on skill change to release
//     the spell-object handle (sets +0x27C=0xFF, +0x27E=0xFFFF).
//
//   * Per-spell handler init gate: `(actor+0x5C == 0) && (actor+0x27C == 0xFF)`.
//     FUN_0052F3B0 cleanup shares the slot==0 early-out. Standalone clone-rail
//     bots inherit slot 0 from the source player actor so the gate passes
//     naturally; gameplay-slot bots carry their true slot (1/2/3) in
//     actor+0x5C, so without a temp-flip the dispatcher runs but the handler
//     bails before allocating the spell object and no visual effect renders.
//     InvokeWithLocalPlayerSlot below wraps each native dispatcher/cleanup
//     call with a transient actor+0x5C = 0 write and an immediate restore.
//
//   * Bot flow (this function): PlayerActorTick still runs for the bot actor
//     via `original(self)` in the tick hook, so FUN_00548A00 keeps driving
//     the per-spell handler natively. Our job is (a) initiate the cast by
//     setting aim + actor+0x270 + a primer dispatch; (b) each subsequent tick
    //     keeps stock input held only for native-held primaries; (c) bounded held
    //     primaries release synthetic input when native charge reaches the chosen
    //     release point, let the live world object update, then invoke the stock
    //     active-handle cleanup so native damage/effect code remains authoritative.
    //     kMaxTicksWaiting is a safety cap against unexpected latch states, not a
    //     timing assumption.
bool ProcessPendingBotCast(ParticipantEntityBinding* binding, std::string* error_message) {
    if (binding == nullptr || binding->actor_address == 0 || binding->bot_id == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto actor_address = binding->actor_address;
    const auto dispatcher_address = memory.ResolveGameAddressOrZero(kSpellCastDispatcher);
    const auto cleanup_address = memory.ResolveGameAddressOrZero(kCastActiveHandleCleanup);
    if (dispatcher_address == 0 || cleanup_address == 0) {
        if (error_message != nullptr && binding->ongoing_cast.active) {
            *error_message = "cast seam addresses unresolved";
        }
        return false;
    }

    constexpr float kRadiansToDegrees = 57.2957795130823208767981548141051703f;
    constexpr std::uint8_t kActorActiveCastGroupSentinel = 0xFF;
    constexpr std::uint16_t kActorActiveCastSlotSentinel = 0xFFFF;
    const bool actor_dead = IsActorRuntimeDead(actor_address);

    // Per-spell handler init gate (docs/spell-cast-cleanup-chain.md) is
    // `(actor+0x5C == 0) && (actor+0x27C == 0xFF)`. FUN_0052F3B0 cleanup has the
    // same slot==0 early-out. Standalone clone-rail bots inherit slot 0 from the
    // source player actor, so on April-20 verification the gate passed and
    // effects spawned. Gameplay-slot bots (task #18) carry their real slot
    // (1/2/3) in actor+0x5C — the gate fails, dispatcher returns without
    // allocating a spell object, and no projectile/cone ever renders even though
    // animation flags and aim fields were written. Temp-flip actor+0x5C to 0
    // around the native dispatcher/cleanup calls so the handler treats the bot
    // as the local player for the gate check; restore immediately after so the
    // rest of the tick (hostile AI, HUD, rendering) still sees the bot's true
    // gameplay slot.
    auto InvokeWithLocalPlayerSlot = [&](auto&& invoke) {
        LocalPlayerCastShimState shim_state;
        const auto shim_active = EnterLocalPlayerCastShim(binding, &shim_state);
        invoke();
        LeaveLocalPlayerCastShim(shim_state);
        Log(
            std::string("[bots] slot_flip diag. actor=") + HexString(actor_address) +
            " slot_offset=" + HexString(static_cast<std::uint32_t>(kActorSlotOffset)) +
            " saved=" + HexString(shim_state.saved_actor_slot) +
            " during=" + HexString(
                memory.ReadFieldOr<std::uint8_t>(
                    actor_address,
                    kActorSlotOffset,
                    static_cast<std::uint8_t>(0xFE))) +
            " flip_needed=" + (shim_active ? "1" : "0") +
            " flip_wr=" + (shim_active ? "1" : "0") +
            " restore_wr=" + (shim_active ? "1" : "0") +
            " shim_slot=" + std::to_string(binding->gameplay_slot) +
            " prog_redirect=" + (shim_state.progression_slot_redirected ? "1" : "0") +
            " prog_restore=" + (shim_state.progression_slot_restore_needed ? "1" : "0") +
            " prog_saved=" + HexString(shim_state.saved_local_progression_handle) +
            " prog_bot=" + HexString(shim_state.redirected_progression_handle));
    };

    auto RestoreAim = [&](const ParticipantEntityBinding::OngoingCastState& state) {
        if (state.have_aim_heading) {
            (void)RefreshWizardBindingTargetFacing(binding);
            if (!ApplyWizardBindingFacingState(binding, actor_address)) {
                ApplyWizardActorFacingState(actor_address, state.heading_before);
            }
        }
        if (state.have_aim_target) {
            (void)memory.TryWriteField(actor_address, kActorAimTargetXOffset, state.aim_x_before);
            (void)memory.TryWriteField(actor_address, kActorAimTargetYOffset, state.aim_y_before);
            (void)memory.TryWriteField<std::uint32_t>(
                actor_address, kActorAimTargetAux0Offset, state.aim_aux0_before);
            (void)memory.TryWriteField<std::uint32_t>(
                actor_address, kActorAimTargetAux1Offset, state.aim_aux1_before);
        }
        (void)memory.TryWriteField<std::uint8_t>(
            actor_address, kActorCastSpreadModeByteOffset, state.spread_before);
    };

    struct ActiveSpellObjectSnapshot {
        std::uint8_t group = 0xFF;
        std::uint16_t slot = 0xFFFF;
        std::uintptr_t world = 0;
        std::uintptr_t selection_state = 0;
        std::uintptr_t object = 0;
        std::uintptr_t vtable = 0;
        std::uintptr_t update_fn = 0;
        std::uintptr_t release_secondary_fn = 0;
        std::uintptr_t release_finalize_fn = 0;
        std::uint32_t object_type = 0;
        std::uint32_t object_f74_raw = 0;
        std::uint32_t object_f1f0_raw = 0;
        std::uint32_t object_f1fc_raw = 0;
        std::uint32_t object_f22c = 0;
        std::uint32_t object_f230 = 0;
        float object_x = 0.0f;
        float object_y = 0.0f;
        float object_heading = 0.0f;
        float object_radius = 0.0f;
        float object_f74 = 0.0f;
        float object_f1f0 = 0.0f;
        float object_f1fc = 0.0f;
        bool readable = false;
        bool handle_from_selection_state = false;
        bool boulder_max_size_reached = false;
    };

    auto ReadActiveSpellObjectSnapshot = [&](bool allow_selection_state_fallback = true) {
        ActiveSpellObjectSnapshot snapshot{};
        snapshot.group =
            memory.ReadFieldOr<std::uint8_t>(
                actor_address,
                kActorActiveCastGroupByteOffset,
                kActorActiveCastGroupSentinel);
        snapshot.slot =
            memory.ReadFieldOr<std::uint16_t>(
                actor_address,
                kActorActiveCastSlotShortOffset,
                kActorActiveCastSlotSentinel);
        snapshot.world = memory.ReadFieldOr<std::uintptr_t>(actor_address, kActorOwnerOffset, 0);
        snapshot.selection_state =
            memory.ReadFieldOr<std::uintptr_t>(
                actor_address,
                kActorAnimationSelectionStateOffset,
                0);
        if (allow_selection_state_fallback &&
            (snapshot.group == kActorActiveCastGroupSentinel ||
             snapshot.slot == kActorActiveCastSlotSentinel)) {
            if (snapshot.selection_state != 0 &&
                memory.IsReadableRange(snapshot.selection_state, 0x10)) {
                const auto selection_group =
                    memory.ReadValueOr<std::uint8_t>(
                        snapshot.selection_state + 0x4,
                        kActorActiveCastGroupSentinel);
                const auto selection_slot =
                    memory.ReadValueOr<std::uint16_t>(
                        snapshot.selection_state + 0x6,
                        kActorActiveCastSlotSentinel);
                if (selection_group != kActorActiveCastGroupSentinel &&
                    selection_slot != kActorActiveCastSlotSentinel) {
                    snapshot.group = selection_group;
                    snapshot.slot = selection_slot;
                    snapshot.handle_from_selection_state = true;
                }
            }
        }
        if (snapshot.group == kActorActiveCastGroupSentinel ||
            snapshot.slot == kActorActiveCastSlotSentinel ||
            snapshot.world == 0) {
            return snapshot;
        }

        const std::uintptr_t entry_address =
            snapshot.world + kActorWorldBucketTableOffset +
            static_cast<std::uintptr_t>(
                static_cast<std::uint32_t>(snapshot.group) * kActorWorldBucketStride +
                static_cast<std::uint32_t>(snapshot.slot)) *
                sizeof(std::uintptr_t);
        snapshot.object = memory.ReadValueOr<std::uintptr_t>(entry_address, 0);
        if (snapshot.object == 0 || !memory.IsReadableRange(snapshot.object, 0x240)) {
            return snapshot;
        }

        snapshot.readable = true;
        snapshot.vtable = memory.ReadFieldOr<std::uintptr_t>(snapshot.object, 0x00, 0);
        if (snapshot.vtable != 0 && memory.IsReadableRange(snapshot.vtable, 0x74)) {
            snapshot.update_fn = memory.ReadValueOr<std::uintptr_t>(snapshot.vtable + 0x1C, 0);
            snapshot.release_secondary_fn = memory.ReadValueOr<std::uintptr_t>(snapshot.vtable + 0x6C, 0);
            snapshot.release_finalize_fn = memory.ReadValueOr<std::uintptr_t>(snapshot.vtable + 0x70, 0);
        }
        snapshot.object_type = memory.ReadFieldOr<std::uint32_t>(snapshot.object, 0x08, 0);
        snapshot.object_f74 = memory.ReadFieldOr<float>(snapshot.object, 0x74, 0.0f);
        snapshot.object_f1f0 = memory.ReadFieldOr<float>(snapshot.object, 0x1F0, 0.0f);
        snapshot.object_f1fc = memory.ReadFieldOr<float>(snapshot.object, 0x1FC, 0.0f);
        snapshot.object_f74_raw = memory.ReadFieldOr<std::uint32_t>(snapshot.object, 0x74, 0);
        snapshot.object_f1f0_raw = memory.ReadFieldOr<std::uint32_t>(snapshot.object, 0x1F0, 0);
        snapshot.object_f1fc_raw = memory.ReadFieldOr<std::uint32_t>(snapshot.object, 0x1FC, 0);
        snapshot.object_f22c = memory.ReadFieldOr<std::uint32_t>(snapshot.object, 0x22C, 0);
        snapshot.object_f230 = memory.ReadFieldOr<std::uint32_t>(snapshot.object, 0x230, 0);
        snapshot.object_x = memory.ReadFieldOr<float>(snapshot.object, 0x18, 0.0f);
        snapshot.object_y = memory.ReadFieldOr<float>(snapshot.object, 0x1C, 0.0f);
        snapshot.object_heading = memory.ReadFieldOr<float>(snapshot.object, 0x6C, 0.0f);
        snapshot.object_radius = memory.ReadFieldOr<float>(snapshot.object, 0x70, 0.0f);
        snapshot.boulder_max_size_reached =
            std::isfinite(snapshot.object_f74) &&
            std::isfinite(snapshot.object_f1fc) &&
            snapshot.object_f1fc > 0.0f &&
            snapshot.object_f74 >= snapshot.object_f1fc - 0.001f;
        return snapshot;
    };

    struct BoulderDamageProjectionSnapshot {
        bool readable = false;
        uintptr_t target_actor = 0;
        uintptr_t target_health_base = 0;
        uintptr_t stat_source = 0;
        uintptr_t stat_vtable = 0;
        uintptr_t damage_getter = 0;
        const char* target_health_kind = "unknown";
        int statbook_level = 1;
        float target_hp = 0.0f;
        float target_max_hp = 0.0f;
        float target_x = 0.0f;
        float target_y = 0.0f;
        float target_radius = 0.0f;
        float target_distance = 0.0f;
        float target_impact_radius = 0.0f;
        float target_damage_scale = 0.0f;
        float charge = 0.0f;
        float base_damage = 0.0f;
        float statbook_damage = 0.0f;
        float projected_damage = 0.0f;
        DWORD damage_getter_seh = 0;
        bool damage_getter_attempted = false;
        bool native_damage_scale_available = false;
        bool target_position_readable = false;
        bool target_in_impact = false;
        bool impact_context_write_attempted = false;
        bool impact_context_write_ok = false;
        float impact_context_x = 0.0f;
        float impact_context_y = 0.0f;
        float impact_context_radius = 0.0f;
    };

    auto ReadBoulderDamageProjectionSnapshot =
        [&](const ActiveSpellObjectSnapshot& active_spell_snapshot) {
            BoulderDamageProjectionSnapshot snapshot{};
            if (!active_spell_snapshot.readable || active_spell_snapshot.object == 0) {
                return snapshot;
            }

            snapshot.target_actor = ResolveOngoingCastNativeTargetActor(
                binding,
                binding->ongoing_cast);
            ActorHealthRuntime target_health{};
            if (!TryReadActorHealthRuntime(snapshot.target_actor, &target_health) ||
                target_health.hp <= 0.0f) {
                return snapshot;
            }

            int statbook_level = 1;
            const auto resolved_statbook_damage = ResolveEarthBoulderBaseDamage(
                binding,
                binding->ongoing_cast.progression_runtime_address,
                &statbook_level);
            if (!std::isfinite(resolved_statbook_damage) ||
                resolved_statbook_damage <= 0.0f) {
                return snapshot;
            }
            const float release_charge =
                std::isfinite(active_spell_snapshot.object_f74) &&
                        active_spell_snapshot.object_f74 > 0.0f
                    ? active_spell_snapshot.object_f74
                    : 0.0f;
            if (release_charge <= 0.0f) {
                return snapshot;
            }

            snapshot.target_health_base = target_health.base_address;
            snapshot.target_health_kind = target_health.kind;
            snapshot.statbook_level = statbook_level;
            snapshot.target_hp = target_health.hp;
            snapshot.target_max_hp = target_health.max_hp;
            if (kActorPositionXOffset != 0 &&
                kActorPositionYOffset != 0 &&
                memory.IsReadableRange(
                    snapshot.target_actor + kActorPositionXOffset,
                    sizeof(float)) &&
                memory.IsReadableRange(
                    snapshot.target_actor + kActorPositionYOffset,
                    sizeof(float))) {
                snapshot.target_x =
                    memory.ReadFieldOr<float>(
                        snapshot.target_actor,
                        kActorPositionXOffset,
                        0.0f);
                snapshot.target_y =
                    memory.ReadFieldOr<float>(
                        snapshot.target_actor,
                        kActorPositionYOffset,
                        0.0f);
                snapshot.target_position_readable =
                    std::isfinite(snapshot.target_x) &&
                    std::isfinite(snapshot.target_y);
            }
            if (kActorCollisionRadiusOffset != 0 &&
                memory.IsReadableRange(
                    snapshot.target_actor + kActorCollisionRadiusOffset,
                    sizeof(float))) {
                snapshot.target_radius =
                    memory.ReadFieldOr<float>(
                        snapshot.target_actor,
                        kActorCollisionRadiusOffset,
                        0.0f);
                if (!std::isfinite(snapshot.target_radius) ||
                    snapshot.target_radius < 0.0f ||
                    snapshot.target_radius > 128.0f) {
                    snapshot.target_radius = 0.0f;
                }
            }
            if (snapshot.target_position_readable &&
                std::isfinite(active_spell_snapshot.object_x) &&
                std::isfinite(active_spell_snapshot.object_y)) {
                const auto target_dx = snapshot.target_x - active_spell_snapshot.object_x;
                const auto target_dy = snapshot.target_y - active_spell_snapshot.object_y;
                snapshot.target_distance =
                    std::sqrt((target_dx * target_dx) + (target_dy * target_dy));
                const float object_radius =
                    std::isfinite(active_spell_snapshot.object_radius) &&
                            active_spell_snapshot.object_radius > 0.0f &&
                            active_spell_snapshot.object_radius <= 128.0f
                        ? active_spell_snapshot.object_radius
                        : 0.0f;
                snapshot.target_impact_radius = object_radius + snapshot.target_radius;
                if (object_radius <= 0.0f ||
                    !std::isfinite(snapshot.target_impact_radius) ||
                    snapshot.target_impact_radius <= 0.0f ||
                    snapshot.target_impact_radius > 256.0f) {
                    snapshot.target_impact_radius = 0.0f;
                }
                snapshot.target_in_impact =
                    snapshot.target_impact_radius > 0.0f &&
                    std::isfinite(snapshot.target_distance) &&
                    snapshot.target_distance <= snapshot.target_impact_radius + 0.001f;
            }
            snapshot.charge = release_charge;
            snapshot.statbook_damage = resolved_statbook_damage;
            snapshot.base_damage = resolved_statbook_damage;
            snapshot.projected_damage =
                snapshot.base_damage * snapshot.charge * snapshot.charge;
            snapshot.readable =
                std::isfinite(snapshot.projected_damage) &&
                snapshot.projected_damage > 0.0f;
            if (!snapshot.readable) {
                return snapshot;
            }

            DWORD damage_getter_exception_code = 0;
            snapshot.stat_source =
                memory.ReadFieldOr<std::uintptr_t>(active_spell_snapshot.object, 0x58, 0);
            if (snapshot.stat_source != 0 &&
                memory.IsReadableRange(snapshot.stat_source, sizeof(std::uintptr_t))) {
                snapshot.stat_vtable =
                    memory.ReadValueOr<std::uintptr_t>(snapshot.stat_source, 0);
                if (snapshot.stat_vtable != 0 &&
                    memory.IsReadableRange(snapshot.stat_vtable + 0x100, sizeof(std::uintptr_t))) {
                    snapshot.damage_getter =
                        memory.ReadValueOr<std::uintptr_t>(snapshot.stat_vtable + 0x100, 0);
                }
            }
            if (snapshot.stat_source != 0 &&
                snapshot.target_in_impact &&
                snapshot.target_position_readable &&
                std::isfinite(active_spell_snapshot.object_x) &&
                std::isfinite(active_spell_snapshot.object_y) &&
                std::isfinite(snapshot.target_impact_radius) &&
                snapshot.target_impact_radius > 0.0f) {
                const float object_radius =
                    std::isfinite(active_spell_snapshot.object_radius) &&
                            active_spell_snapshot.object_radius > 0.0f
                        ? active_spell_snapshot.object_radius
                        : 0.0f;
                const float context_radius =
                    object_radius > snapshot.target_impact_radius
                        ? object_radius
                        : snapshot.target_impact_radius;
                if (std::isfinite(context_radius) && context_radius > 0.0f) {
                    snapshot.impact_context_write_attempted = true;
                    snapshot.impact_context_x = active_spell_snapshot.object_x - context_radius;
                    snapshot.impact_context_y = active_spell_snapshot.object_y;
                    snapshot.impact_context_radius = context_radius;
                    const bool write_x =
                        memory.TryWriteField<float>(
                            snapshot.stat_source,
                            0x8BCC,
                            snapshot.impact_context_x);
                    const bool write_y =
                        memory.TryWriteField<float>(
                            snapshot.stat_source,
                            0x8BD0,
                            snapshot.impact_context_y);
                    const bool write_radius =
                        memory.TryWriteField<float>(
                            snapshot.stat_source,
                            0x8BD4,
                            snapshot.impact_context_radius);
                    const bool write_y_extent =
                        memory.TryWriteField<float>(
                            snapshot.stat_source,
                            0x8BD8,
                            0.0f);
                    snapshot.impact_context_write_ok =
                        write_x && write_y && write_radius && write_y_extent;
                }
            }
            if (snapshot.damage_getter != 0 &&
                memory.IsExecutableRange(snapshot.damage_getter, 1)) {
                snapshot.damage_getter_attempted = true;
                snapshot.native_damage_scale_available =
                    CallNativeTwoFloatGetterSafe(
                        snapshot.damage_getter,
                        snapshot.stat_source,
                        snapshot.target_x,
                        snapshot.target_y,
                        &snapshot.target_damage_scale,
                        &damage_getter_exception_code) &&
                    snapshot.target_position_readable &&
                    std::isfinite(snapshot.target_damage_scale) &&
                    snapshot.target_damage_scale > 0.0f;
                snapshot.damage_getter_seh = damage_getter_exception_code;
            }

            // The vtable getter is useful as a native reachability diagnostic,
            // but damage magnitude follows the statbook "damage x size^2"
            // formula recovered from the Earth release path and confirmed
            // against live HP deltas.
            return snapshot;
        };

    auto ReleaseSpellHandle = [&](const ParticipantEntityBinding::OngoingCastState& state,
                                  const char* exit_label,
                                  bool clear_facing_target,
                                  bool run_active_handle_cleanup = true,
                                  const ActiveSpellObjectSnapshot* known_release_object_snapshot = nullptr) {
        const auto release_object_snapshot =
            known_release_object_snapshot != nullptr
                ? *known_release_object_snapshot
                : ReadActiveSpellObjectSnapshot(false);
        const auto actor_group_before =
            memory.ReadFieldOr<std::uint8_t>(actor_address, kActorActiveCastGroupByteOffset, 0);
        const auto actor_slot_before =
            memory.ReadFieldOr<std::uint16_t>(actor_address, kActorActiveCastSlotShortOffset, 0);
        DWORD cleanup_exception_code = 0;
        bool cleanup_ok = true;
        bool cleanup_actor_handle_live = false;
        uintptr_t cleanup_state_entry_address = 0;
        int cleanup_state_before = -1;
        int cleanup_state_for_call = -1;
        int cleanup_state_after = -1;
        bool cleanup_state_available = false;
        bool cleanup_state_write_ok = false;
        bool cleanup_state_restore_ok = true;
        cleanup_actor_handle_live =
            actor_group_before != kActorActiveCastGroupSentinel &&
            actor_slot_before != kActorActiveCastSlotSentinel;
        if (!run_active_handle_cleanup) {
            (void)memory.TryWriteField<std::uint8_t>(
                actor_address, kActorActiveCastGroupByteOffset, kActorActiveCastGroupSentinel);
            (void)memory.TryWriteField<std::uint16_t>(
                actor_address, kActorActiveCastSlotShortOffset, kActorActiveCastSlotSentinel);
        } else if (cleanup_actor_handle_live) {
            uintptr_t cleanup_state_table_address = 0;
            int cleanup_state_entry_count = 0;
            if (TryResolveGameplayIndexState(
                    &cleanup_state_table_address,
                    &cleanup_state_entry_count) &&
                cleanup_state_table_address != 0 &&
                cleanup_state_entry_count > 0 &&
                memory.TryReadValue<int>(cleanup_state_table_address, &cleanup_state_before)) {
                constexpr int kNativeCleanupRequiredGameplayState = 5;
                cleanup_state_entry_address = cleanup_state_table_address;
                cleanup_state_available = true;
                cleanup_state_for_call = cleanup_state_before;
                if (cleanup_state_before != kNativeCleanupRequiredGameplayState) {
                    cleanup_state_write_ok =
                        memory.TryWriteValue<int>(
                            cleanup_state_entry_address,
                            kNativeCleanupRequiredGameplayState);
                    if (cleanup_state_write_ok) {
                        cleanup_state_for_call = kNativeCleanupRequiredGameplayState;
                    }
                }
            }
            InvokeWithLocalPlayerSlot([&] {
                cleanup_ok = CallCastActiveHandleCleanupSafe(
                    cleanup_address, actor_address, &cleanup_exception_code);
            });
            if (cleanup_state_write_ok) {
                cleanup_state_restore_ok =
                    memory.TryWriteValue<int>(
                        cleanup_state_entry_address,
                        cleanup_state_before);
            }
            if (cleanup_state_available && cleanup_state_entry_address != 0) {
                cleanup_state_after =
                    memory.ReadValueOr<int>(cleanup_state_entry_address, -1);
            }
            if (!cleanup_ok) {
                // Native cleanup raised SEH. Fall back to writing the sentinels
                // directly so the next cast's init gate passes; vtable-side
                // effects get skipped, but the handle is released and future
                // casts are safe.
                (void)memory.TryWriteField<std::uint8_t>(
                    actor_address, kActorActiveCastGroupByteOffset, kActorActiveCastGroupSentinel);
                (void)memory.TryWriteField<std::uint16_t>(
                    actor_address, kActorActiveCastSlotShortOffset, kActorActiveCastSlotSentinel);
            }
        }
        const bool defer_bounded_latch_clear =
            state.bounded_release_requested &&
            state.bounded_release_at_damage_threshold &&
            !state.bounded_release_at_max_size;
        if (!defer_bounded_latch_clear) {
            (void)memory.TryWriteField<std::int32_t>(actor_address, kActorPrimarySkillIdOffset, 0);
        }
        const bool should_clear_cast_latch =
            !defer_bounded_latch_clear &&
            state.lane == ParticipantEntityBinding::OngoingCastState::Lane::PurePrimary &&
            (actor_group_before == kActorActiveCastGroupSentinel ||
             state.bounded_release_requested);
        if (should_clear_cast_latch) {
            (void)memory.TryWriteField<std::uint32_t>(actor_address, 0xE4, 0);
            (void)memory.TryWriteField<std::uint32_t>(actor_address, 0xE8, 0);
        }
        RestoreAim(state);
        if (state.lane == ParticipantEntityBinding::OngoingCastState::Lane::PurePrimary &&
            state.pure_primary_item_sink_fallback != 0) {
            std::string lane_error;
            if (!SetEquipVisualLaneObject(
                    actor_address,
                    kActorEquipRuntimeVisualLinkAttachmentOffset,
                    state.pure_primary_item_sink_fallback,
                    "attachment",
                    &lane_error) &&
                !lane_error.empty()) {
                Log(
                    "[bots] pure-primary attachment restore failed. bot_id=" +
                    std::to_string(binding->bot_id) +
                    " actor=" + HexString(actor_address) +
                    " error=" + lane_error);
            }
        }
        RestoreSelectionStateObjectAfterCast(state);
        RestoreSelectionBrainAfterCast(state);
        ClearSelectionBrainTarget(state.selection_state_pointer);
        RestoreOngoingCastNativeTargetActor(actor_address, state);
        if (clear_facing_target) {
            binding->facing_target_actor_address = 0;
        } else {
            (void)RefreshWizardBindingTargetFacing(binding);
        }
        if (state.gameplay_selection_state_override_active &&
            binding->gameplay_slot >= 0 &&
            state.gameplay_selection_state_before != kUnknownAnimationStateId) {
            std::string selection_error;
            (void)TryWriteActorAnimationStateIdDirect(actor_address, state.gameplay_selection_state_before);
            (void)TryWriteGameplaySelectionStateForSlot(
                binding->gameplay_slot,
                state.gameplay_selection_state_before,
                &selection_error);
        }
        if (state.progression_spell_id_override_active && state.progression_runtime_address != 0) {
            (void)memory.TryWriteField<std::int32_t>(
                state.progression_runtime_address,
                0x750,
                state.progression_spell_id_before);
        }

        const auto group_after =
            memory.ReadFieldOr<std::uint8_t>(actor_address, kActorActiveCastGroupByteOffset, 0);
        const auto settled_heading =
            memory.ReadFieldOr<float>(actor_address, kActorHeadingOffset, 0.0f);
        const bool completed_boulder_at_max =
            release_object_snapshot.boulder_max_size_reached ||
            state.bounded_release_at_max_size ||
            (SkillRequiresBoundedHeldCastInputDuringNativeTick(ResolveOngoingNativeTickSkillId(state)) &&
             std::strcmp(exit_label, "max_size_released") == 0);
        const std::string bounded_release_summary =
            state.bounded_release_requested
                ? std::string(" release_reason=") +
                      (state.bounded_release_at_damage_threshold
                           ? std::string("damage_threshold")
                           : (state.bounded_release_at_max_size ? std::string("max_size") : std::string("unknown"))) +
                      " release_charge=" + std::to_string(state.bounded_release_charge) +
                      " release_base_damage=" + std::to_string(state.bounded_release_base_damage) +
                      " release_statbook_damage=" +
                          std::to_string(state.bounded_release_statbook_damage) +
                      " release_projected_damage=" +
                          std::to_string(state.bounded_release_projected_damage) +
                      " release_target_hp=" + std::to_string(state.bounded_release_target_hp) +
                      " release_target_actor=" + HexString(state.bounded_release_target_actor) +
                      " release_damage_native=" +
                          (state.bounded_release_damage_native ? std::string("1") : std::string("0"))
                : std::string("");
        (void)multiplayer::FinishBotAttack(
            binding->bot_id,
            true,
            settled_heading,
            clear_facing_target);
        Log(
            std::string("[bots] cast complete (") + exit_label + "). bot_id=" +
            std::to_string(binding->bot_id) +
            " skill_id=" + std::to_string(state.skill_id) +
            " ticks=" + std::to_string(state.ticks_waiting) +
            " post_release_ticks=" + std::to_string(state.bounded_post_release_ticks_waiting) +
            " saw_latch=" + (state.saw_latch ? std::string("1") : std::string("0")) +
            " group_before=" + HexString(actor_group_before) +
            " slot_before=" + HexString(actor_slot_before) +
            " group_after=" + HexString(group_after) +
            " cleanup_requested=" + (run_active_handle_cleanup ? std::string("1") : std::string("0")) +
            " cleanup_actor_handle_live=" + (cleanup_actor_handle_live ? std::string("1") : std::string("0")) +
            " cleanup_state=" + HexString(cleanup_state_entry_address) +
            " cleanup_state_before=" + std::to_string(cleanup_state_before) +
            " cleanup_state_for_call=" + std::to_string(cleanup_state_for_call) +
            " cleanup_state_after=" + std::to_string(cleanup_state_after) +
            " cleanup_state_write=" + (cleanup_state_write_ok ? std::string("1") : std::string("0")) +
            " cleanup_state_restore=" + (cleanup_state_restore_ok ? std::string("1") : std::string("0")) +
            " handle_source=" +
                (release_object_snapshot.handle_from_selection_state ? std::string("selection") : std::string("actor")) +
            " selection_state=" + HexString(release_object_snapshot.selection_state) +
            " obj_ptr=" + HexString(release_object_snapshot.object) +
            " obj_vt=" + HexString(release_object_snapshot.vtable) +
            " obj_vt_1c=" + HexString(release_object_snapshot.update_fn) +
            " obj_vt_6c=" + HexString(release_object_snapshot.release_secondary_fn) +
            " obj_vt_70=" + HexString(release_object_snapshot.release_finalize_fn) +
            " obj_type=" + HexString(release_object_snapshot.object_type) +
            " obj_x=" + std::to_string(release_object_snapshot.object_x) +
            " obj_y=" + std::to_string(release_object_snapshot.object_y) +
            " obj_heading=" + std::to_string(release_object_snapshot.object_heading) +
            " obj_radius=" + std::to_string(release_object_snapshot.object_radius) +
            " obj_74=" + std::to_string(release_object_snapshot.object_f74) +
            " obj_1f0=" + std::to_string(release_object_snapshot.object_f1f0) +
            " obj_1fc=" + std::to_string(release_object_snapshot.object_f1fc) +
            " obj_22c=" + HexString(release_object_snapshot.object_f22c) +
            " obj_230=" + HexString(release_object_snapshot.object_f230) +
            " obj_74_raw=" + HexString(release_object_snapshot.object_f74_raw) +
            " obj_1f0_raw=" + HexString(release_object_snapshot.object_f1f0_raw) +
            " obj_1fc_raw=" + HexString(release_object_snapshot.object_f1fc_raw) +
            " boulder_max_size=" +
                (completed_boulder_at_max ? std::string("1") : std::string("0")) +
            bounded_release_summary +
            (cleanup_ok ? std::string("") :
                          std::string(" cleanup_seh=") + HexString(cleanup_exception_code)));
    };

    auto ScheduleBoundedReleaseLatchClear =
        [&](ParticipantEntityBinding::OngoingCastState& state) {
            constexpr std::uint64_t kBoundedCleanupLatchClearDelayMs = 100;
            state.bounded_cleanup_completed = true;
            state.bounded_cleanup_clear_after_ms =
                static_cast<std::uint64_t>(GetTickCount64()) +
                kBoundedCleanupLatchClearDelayMs;
        };

    auto ClearBoundedReleaseCastLatch =
        [&](ParticipantEntityBinding::OngoingCastState& state, const char* reason) {
            const auto actor_e4_before =
                memory.ReadFieldOr<std::uint32_t>(actor_address, 0xE4, 0);
            const auto actor_e8_before =
                memory.ReadFieldOr<std::uint32_t>(actor_address, 0xE8, 0);
            const bool primary_clear_ok =
                memory.TryWriteField<std::int32_t>(actor_address, kActorPrimarySkillIdOffset, 0);
            const bool e4_clear_ok =
                memory.TryWriteField<std::uint32_t>(actor_address, 0xE4, 0);
            const bool e8_clear_ok =
                memory.TryWriteField<std::uint32_t>(actor_address, 0xE8, 0);
            Log(
                "[bots] bounded release latch cleared. bot_id=" +
                std::to_string(binding->bot_id) +
                " skill_id=" + std::to_string(state.skill_id) +
                " reason=" + (reason != nullptr ? std::string(reason) : std::string("unknown")) +
                " ticks=" + std::to_string(state.ticks_waiting) +
                " clear_after_ms=" + std::to_string(state.bounded_cleanup_clear_after_ms) +
                " e4_before=" + HexString(actor_e4_before) +
                " e8_before=" + HexString(actor_e8_before) +
                " primary_clear=" + (primary_clear_ok ? std::string("1") : std::string("0")) +
                " e4_clear=" + (e4_clear_ok ? std::string("1") : std::string("0")) +
                " e8_clear=" + (e8_clear_ok ? std::string("1") : std::string("0")));
            state = ParticipantEntityBinding::OngoingCastState{};
        };

    auto LogSpellObjectDiag = [&](std::uint8_t active_group_post) {
        auto snapshot = ReadActiveSpellObjectSnapshot();
        snapshot.group = active_group_post;
        Log(
            std::string("[bots] spell_obj diag. bot_id=") + std::to_string(binding->bot_id) +
            " group=" + HexString(snapshot.group) +
            " slot=" + HexString(snapshot.slot) +
            " handle_source=" + (snapshot.handle_from_selection_state ? std::string("selection") : std::string("actor")) +
            " selection_state=" + HexString(snapshot.selection_state) +
            " world=" + HexString(snapshot.world) +
            " obj_ptr=" + HexString(snapshot.object) +
            " obj_vt=" + HexString(snapshot.vtable) +
            " obj_vt_1c=" + HexString(snapshot.update_fn) +
            " obj_vt_6c=" + HexString(snapshot.release_secondary_fn) +
            " obj_vt_70=" + HexString(snapshot.release_finalize_fn) +
            " obj_type=" + HexString(snapshot.object_type) +
            " obj_x=" + std::to_string(snapshot.object_x) +
            " obj_y=" + std::to_string(snapshot.object_y) +
            " obj_heading=" + std::to_string(snapshot.object_heading) +
            " obj_radius=" + std::to_string(snapshot.object_radius) +
            " obj_74=" + std::to_string(snapshot.object_f74) +
            " obj_1f0=" + std::to_string(snapshot.object_f1f0) +
            " obj_1fc=" + std::to_string(snapshot.object_f1fc) +
            " obj_74_raw=" + HexString(snapshot.object_f74_raw) +
            " obj_1f0_raw=" + HexString(snapshot.object_f1f0_raw) +
            " obj_1fc_raw=" + HexString(snapshot.object_f1fc_raw) +
            " obj_22c=" + std::to_string(snapshot.object_f22c) +
            " obj_230=" + std::to_string(snapshot.object_f230) +
            " boulder_max_size=" + (snapshot.boulder_max_size_reached ? std::string("1") : std::string("0")) +
            " startup={" + DescribeGameplaySlotCastStartupWindow(actor_address) + "}");
    };

    // --- Watch continuation path ---------------------------------------------
    // Gameplay-slot bots keep stock movement/render ownership, but their cast
    // startup cannot rely on the local-player input gate inside
    // PlayerActorTick: stock clears actor+0x270 every frame before it ever
    // reaches FUN_00548A00. Re-pin the prepared fields here and, if stock never
    // preserved the skill id, perform a single post-stock startup dispatch
    // under the same slot-0 shim the native handler expects.
    if (binding->ongoing_cast.active) {
        auto& ongoing = binding->ongoing_cast;

        if (actor_dead) {
            ReleaseSpellHandle(ongoing, "dead", true);
            ongoing = ParticipantEntityBinding::OngoingCastState{};
            return true;
        }

        if (ongoing.bounded_cleanup_completed) {
            const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
            if (ongoing.bounded_cleanup_clear_after_ms == 0 ||
                now_ms >= ongoing.bounded_cleanup_clear_after_ms) {
                ClearBoundedReleaseCastLatch(ongoing, "post_cleanup_delay");
            }
            return true;
        }

        // Keep native target/aim fresh for startup and true held primaries.
        // Projectile-style primaries keep the target captured at startup so a
        // later nearest-enemy swap cannot redirect an already spawned cast.
        const auto native_active_skill_id = ResolveOngoingNativeTickSkillId(ongoing);
        const bool refresh_ongoing_target_state =
            OngoingCastShouldRefreshNativeTargetState(ongoing);
        bool target_refreshed = false;
        if (refresh_ongoing_target_state) {
            target_refreshed = RefreshOngoingCastAimFromFacingTarget(binding, &ongoing);
        }
        // Do not re-write pure-primary actor selection state after startup.
        // Those handlers mutate the first word as their continuous action
        // state. Dispatcher primaries still need the element selection state
        // pinned so PlayerActorTick runs the matching native stat initializer
        // before it calls the dispatcher.
        if (ongoing.uses_dispatcher_skill_id && refresh_ongoing_target_state) {
            ReapplyOngoingCastSelectionState(binding, actor_address, ongoing, true);
        }
        if (ongoing.have_aim_heading) {
            ApplyWizardActorFacingState(actor_address, ongoing.aim_heading);
            binding->facing_heading_value = ongoing.aim_heading;
            binding->facing_heading_valid = true;
        }
        if (ongoing.have_aim_target) {
            (void)memory.TryWriteField(actor_address, kActorAimTargetXOffset, ongoing.aim_target_x);
            (void)memory.TryWriteField(actor_address, kActorAimTargetYOffset, ongoing.aim_target_y);
            (void)memory.TryWriteField<std::uint32_t>(actor_address, kActorAimTargetAux0Offset, 0);
            (void)memory.TryWriteField<std::uint32_t>(actor_address, kActorAimTargetAux1Offset, 0);
        }
        (void)memory.TryWriteField<std::uint8_t>(actor_address, kActorCastSpreadModeByteOffset, 0);
        const bool publish_ongoing_skill_id =
            ongoing.uses_dispatcher_skill_id &&
            !(SkillRequiresBoundedHeldCastInputDuringNativeTick(native_active_skill_id) &&
              ongoing.bounded_release_requested);
        (void)memory.TryWriteField<std::int32_t>(
            actor_address,
            kActorPrimarySkillIdOffset,
            publish_ongoing_skill_id ? ongoing.dispatcher_skill_id : 0);
        if (refresh_ongoing_target_state) {
            RefreshSelectionBrainTargetForOngoingCast(ongoing);
        }

        if (IsGameplaySlotWizardKind(binding->kind) &&
            ongoing.startup_in_progress &&
            ongoing.uses_dispatcher_skill_id &&
            !ongoing.post_stock_dispatch_attempted) {
            if (ongoing.uses_dispatcher_skill_id) {
                PrimeGameplaySlotPostGateDispatchState(actor_address, ongoing.dispatcher_skill_id);
                const auto native_target_actor_address =
                    ResolveOngoingCastNativeTargetActor(binding, ongoing);
                if (native_target_actor_address != 0) {
                    (void)WriteOngoingCastNativeTargetActor(
                        actor_address,
                        &ongoing,
                        native_target_actor_address);
                }
                ReapplyOngoingCastSelectionState(binding, actor_address, ongoing, true);
            }
            DWORD startup_exception_code = 0;
            bool startup_dispatched = false;
            uintptr_t startup_gameplay_address = 0;
            std::uint8_t saved_cast_intent = 0;
            std::uint8_t saved_mouse_left = 0;
            std::size_t live_mouse_left_offset = 0;
            bool startup_cast_intent_applied = false;
            bool startup_mouse_left_applied = false;
            if (TryResolveCurrentGameplayScene(&startup_gameplay_address) &&
                startup_gameplay_address != 0) {
                saved_cast_intent = memory.ReadFieldOr<std::uint8_t>(
                    startup_gameplay_address,
                    kGameplayCastIntentOffset,
                    0);
                startup_cast_intent_applied =
                    memory.TryWriteField<std::uint8_t>(
                        startup_gameplay_address,
                        kGameplayCastIntentOffset,
                        static_cast<std::uint8_t>(1));
                const auto input_buffer_index =
                    memory.ReadFieldOr<int>(startup_gameplay_address, kGameplayInputBufferIndexOffset, -1);
                if (input_buffer_index >= 0) {
                    live_mouse_left_offset =
                        static_cast<std::size_t>(
                            input_buffer_index * kGameplayInputBufferStride +
                            kGameplayMouseLeftButtonOffset);
                } else {
                    live_mouse_left_offset = kGameplayMouseLeftButtonOffset;
                }
                saved_mouse_left = memory.ReadFieldOr<std::uint8_t>(
                    startup_gameplay_address,
                    live_mouse_left_offset,
                    0);
                startup_mouse_left_applied =
                    memory.TryWriteField<std::uint8_t>(
                        startup_gameplay_address,
                        live_mouse_left_offset,
                        static_cast<std::uint8_t>(1));
            }
            InvokeWithLocalPlayerSlot([&] {
                startup_dispatched = CallSpellCastDispatcherSafe(
                    dispatcher_address,
                    actor_address,
                    &startup_exception_code);
            });
            if (startup_gameplay_address != 0) {
                if (startup_mouse_left_applied) {
                    (void)memory.TryWriteField<std::uint8_t>(
                        startup_gameplay_address,
                        live_mouse_left_offset,
                        saved_mouse_left);
                }
                if (startup_cast_intent_applied) {
                    (void)memory.TryWriteField<std::uint8_t>(
                        startup_gameplay_address,
                        kGameplayCastIntentOffset,
                        saved_cast_intent);
                }
            }
            ongoing.post_stock_dispatch_attempted = true;
            const auto drive_after_dispatch =
                memory.ReadFieldOr<std::uint8_t>(actor_address, kActorAnimationDriveStateByteOffset, 0);
            const auto no_interrupt_after_dispatch =
                memory.ReadFieldOr<std::uint8_t>(actor_address, kActorNoInterruptFlagOffset, 0);
            const auto active_group_after_dispatch =
                memory.ReadFieldOr<std::uint8_t>(actor_address, kActorActiveCastGroupByteOffset, 0xFF);
            Log(
                "[bots] gameplay-slot post-stock dispatch. bot_id=" +
                std::to_string(binding->bot_id) +
                " skill_id=" + std::to_string(ongoing.dispatcher_skill_id) +
                " ok=" + (startup_dispatched ? std::string("1") : std::string("0")) +
                " seh=" + HexString(startup_exception_code) +
                " group_post=" + HexString(active_group_after_dispatch) +
                " drive_post=" + HexString(drive_after_dispatch) +
                " no_int_post=" + HexString(no_interrupt_after_dispatch));
            if (!startup_dispatched) {
                ReleaseSpellHandle(ongoing, "dispatch_seh", true);
                ongoing = ParticipantEntityBinding::OngoingCastState{};
                return true;
            }
        }

        const auto drive_state =
            memory.ReadFieldOr<std::uint8_t>(actor_address, kActorAnimationDriveStateByteOffset, 0);
        const auto no_interrupt =
            memory.ReadFieldOr<std::uint8_t>(actor_address, kActorNoInterruptFlagOffset, 0);
        const auto actor_e4 =
            memory.ReadFieldOr<std::uint32_t>(actor_address, 0xE4, 0);
        const auto actor_e8 =
            memory.ReadFieldOr<std::uint32_t>(actor_address, 0xE8, 0);
        const auto active_cast_group =
            memory.ReadFieldOr<std::uint8_t>(actor_address, kActorActiveCastGroupByteOffset, 0);
        const bool has_live_handle = active_cast_group != kActorActiveCastGroupSentinel;
        const bool native_primary_action_active =
            OngoingCastNeedsNativeTargetActor(ongoing) &&
            (actor_e4 != 0 || actor_e8 != 0);

        ongoing.ticks_waiting += 1;
        if (ongoing.startup_in_progress) {
            ongoing.startup_ticks_waiting += 1;
        }
        if (drive_state != 0 || no_interrupt != 0 || native_primary_action_active) {
            ongoing.saw_latch = true;
        }
        if (has_live_handle || drive_state != 0 || no_interrupt != 0 || native_primary_action_active) {
            ongoing.saw_activity = true;
            ongoing.startup_in_progress = false;
        }
        if (has_live_handle) {
            ongoing.saw_live_handle = true;
        }
        bool mana_depleted = false;
        if (ongoing.mana_charge_kind == multiplayer::BotManaChargeKind::PerCast &&
            ongoing.progression_runtime_address != 0 &&
            ongoing.saw_activity &&
            ongoing.mana_cost > 0.0f &&
            ongoing.mana_spent_total <= 0.0f) {
            const auto mana_spend =
                TrySpendProgressionMana(ongoing.progression_runtime_address, ongoing.mana_cost, false);
            if (mana_spend.spent) {
                ongoing.mana_spent_total += mana_spend.actual;
                Log(
                    "[bots] mana spent. bot_id=" + std::to_string(binding->bot_id) +
                    " skill_id=" + std::to_string(ongoing.skill_id) +
                    " mode=per_cast statbook_level=" +
                        std::to_string(ongoing.mana_statbook_level) +
                    " cost=" + std::to_string(ongoing.mana_cost) +
                    " before=" + std::to_string(mana_spend.before) +
                    " after=" + std::to_string(mana_spend.after) +
                    " total=" + std::to_string(ongoing.mana_spent_total));
            } else {
                mana_depleted = true;
                Log(
                    "[bots] mana rejected. bot_id=" + std::to_string(binding->bot_id) +
                    " skill_id=" + std::to_string(ongoing.skill_id) +
                    " mode=per_cast cost=" + std::to_string(ongoing.mana_cost) +
                    " before=" + std::to_string(mana_spend.before) +
                    " readable=" + (mana_spend.readable ? std::string("1") : std::string("0")));
            }
        }
        if (ongoing.mana_charge_kind == multiplayer::BotManaChargeKind::PerSecond &&
            ongoing.progression_runtime_address != 0 &&
            ongoing.saw_activity &&
            !ongoing.bounded_release_requested &&
            ongoing.mana_cost > 0.0f) {
            const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
            if (ongoing.mana_last_charge_ms == 0) {
                ongoing.mana_last_charge_ms = now_ms;
            }
            const auto elapsed_ms =
                now_ms > ongoing.mana_last_charge_ms ? now_ms - ongoing.mana_last_charge_ms : 0;
            if (elapsed_ms > 0) {
                const float requested_mana =
                    ongoing.mana_cost * (static_cast<float>(elapsed_ms) / 1000.0f);
                const auto mana_spend =
                    TrySpendProgressionMana(ongoing.progression_runtime_address, requested_mana, true);
                ongoing.mana_last_charge_ms = now_ms;
                if (mana_spend.spent) {
                    ongoing.mana_spent_total += mana_spend.actual;
                    Log(
                        "[bots] mana spent. bot_id=" + std::to_string(binding->bot_id) +
                        " skill_id=" + std::to_string(ongoing.skill_id) +
                        " mode=per_second statbook_level=" +
                            std::to_string(ongoing.mana_statbook_level) +
                        " rate=" + std::to_string(ongoing.mana_cost) +
                        " cost=" + std::to_string(requested_mana) +
                        " before=" + std::to_string(mana_spend.before) +
                        " after=" + std::to_string(mana_spend.after) +
                        " total=" + std::to_string(ongoing.mana_spent_total));
                }
                if (!mana_spend.spent || mana_spend.actual + 0.001f < requested_mana) {
                    mana_depleted = true;
                    Log(
                        "[bots] mana depleted. bot_id=" + std::to_string(binding->bot_id) +
                        " skill_id=" + std::to_string(ongoing.skill_id) +
                        " mode=per_second requested=" + std::to_string(requested_mana) +
                        " actual=" + std::to_string(mana_spend.actual) +
                        " before=" + std::to_string(mana_spend.before) +
                        " after=" + std::to_string(mana_spend.after));
                }
            }
        }

        // Some native primary actions do not publish a live spell-object handle,
        // but their emission still runs through actor+0xE4/0xE8. Do not clear
        // that latch at the first short settle or the hit path can be cut off.
        constexpr int kPurePrimaryNoHandleSettleTicks = 160;
        const bool pure_primary_no_handle_settled =
            ongoing.lane == ParticipantEntityBinding::OngoingCastState::Lane::PurePrimary &&
            !ongoing.requires_local_slot_native_tick &&
            ongoing.saw_activity &&
            !has_live_handle &&
            ongoing.ticks_waiting >= kPurePrimaryNoHandleSettleTicks;
        const bool held_native_cast =
            SkillRequiresHeldCastInputDuringNativeTick(native_active_skill_id);
        const bool bounded_held_native_cast =
            SkillRequiresBoundedHeldCastInputDuringNativeTick(native_active_skill_id);
        const auto active_spell_snapshot = ReadActiveSpellObjectSnapshot(false);
        const auto earth_max_charge =
            ongoing.progression_runtime_address != 0
                ? memory.ReadFieldOr<float>(ongoing.progression_runtime_address, 0x8AC, 1.0f)
                : 1.0f;
        const auto earth_damage_projection =
            bounded_held_native_cast
                ? ReadBoulderDamageProjectionSnapshot(active_spell_snapshot)
                : BoulderDamageProjectionSnapshot{};
        const bool earth_object_charge_reached =
            bounded_held_native_cast &&
            active_spell_snapshot.readable &&
            std::isfinite(active_spell_snapshot.object_f74) &&
            std::isfinite(earth_max_charge) &&
            earth_max_charge > 0.0f &&
            active_spell_snapshot.object_f74 >= earth_max_charge - 0.001f;
        const bool earth_max_size_reached =
            bounded_held_native_cast &&
            active_spell_snapshot.readable &&
            (active_spell_snapshot.boulder_max_size_reached || earth_object_charge_reached);
        const bool earth_damage_threshold_reached =
            bounded_held_native_cast &&
            earth_damage_projection.readable &&
            earth_damage_projection.target_hp > 0.0f &&
            earth_damage_projection.projected_damage >= earth_damage_projection.target_hp;
        const bool bounded_held_release_ready =
            bounded_held_native_cast &&
            active_spell_snapshot.readable &&
            (earth_max_size_reached || earth_damage_threshold_reached);
        const bool bounded_release_just_requested =
            bounded_held_release_ready && !ongoing.bounded_release_requested;
        if (bounded_release_just_requested) {
            float release_charge = earth_damage_projection.charge;
            float release_base_damage = earth_damage_projection.base_damage;
            float release_statbook_damage = earth_damage_projection.statbook_damage;
            float release_projected_damage = earth_damage_projection.projected_damage;
            if ((!std::isfinite(release_charge) || release_charge <= 0.0f) &&
                active_spell_snapshot.readable &&
                std::isfinite(active_spell_snapshot.object_f74) &&
                active_spell_snapshot.object_f74 > 0.0f) {
                release_charge = active_spell_snapshot.object_f74;
            }
            if (!std::isfinite(release_base_damage) || release_base_damage <= 0.0f) {
                release_base_damage =
                    ResolveEarthBoulderBaseDamage(
                        binding,
                        ongoing.progression_runtime_address,
                        nullptr);
            }
            if (!std::isfinite(release_statbook_damage) || release_statbook_damage <= 0.0f) {
                release_statbook_damage = release_base_damage;
            }
            if (std::isfinite(release_base_damage) &&
                release_base_damage > 0.0f &&
                std::isfinite(release_charge) &&
                release_charge > 0.0f) {
                release_projected_damage = release_base_damage * release_charge * release_charge;
            }
            ongoing.bounded_release_requested = true;
            ongoing.bounded_max_size_reached = earth_max_size_reached;
            ongoing.bounded_release_at_max_size = earth_max_size_reached;
            ongoing.bounded_release_at_damage_threshold =
                earth_damage_threshold_reached && !earth_max_size_reached;
            ongoing.bounded_release_charge = release_charge;
            ongoing.bounded_release_base_damage = release_base_damage;
            ongoing.bounded_release_statbook_damage =
                release_statbook_damage;
            ongoing.bounded_release_projected_damage =
                release_projected_damage;
            ongoing.bounded_release_target_hp = earth_damage_projection.target_hp;
            ongoing.bounded_release_target_actor = earth_damage_projection.target_actor;
            ongoing.bounded_release_damage_native =
                earth_damage_projection.native_damage_scale_available;
            ongoing.bounded_post_release_ticks_waiting = 0;
        } else if (bounded_held_native_cast && ongoing.bounded_release_requested) {
            ongoing.bounded_post_release_ticks_waiting += 1;
        }
        const bool bounded_held_native_released =
            bounded_held_native_cast &&
            ongoing.bounded_release_requested &&
            ongoing.saw_live_handle &&
            ongoing.saw_activity &&
            !has_live_handle;
        // The native Earth handler does not drop the active handle by itself.
        // Once release is requested, keep input released while the live boulder
        // gets a native world-object update window, then run the same cleanup
        // the player's skill transition would have invoked.
        constexpr int kBoundedHeldPostReleaseWorldUpdateTicks = 60;
        const bool bounded_held_release_tick_processed =
            bounded_held_native_cast &&
            ongoing.bounded_release_requested &&
            !bounded_release_just_requested &&
            ongoing.saw_live_handle &&
            ongoing.saw_activity &&
            ongoing.bounded_post_release_ticks_waiting >=
                kBoundedHeldPostReleaseWorldUpdateTicks;
        const bool startup_timeout_hit =
            ongoing.startup_in_progress &&
            ongoing.startup_ticks_waiting >=
                ResolveMaxStartupTicksWaiting(native_active_skill_id);
        const bool activity_released =
            !bounded_held_native_cast &&
            ongoing.saw_activity &&
            !has_live_handle &&
            drive_state == 0 &&
            no_interrupt == 0 &&
            actor_e4 == 0 &&
            actor_e8 == 0;
        const bool gesture_window_complete =
            !held_native_cast &&
            !bounded_held_native_cast &&
            ongoing.saw_activity &&
            ongoing.ticks_waiting >= ResolveBotCastGestureTicks(native_active_skill_id);
        const bool held_target_missing =
            held_native_cast &&
            ongoing.saw_activity &&
            !target_refreshed &&
            binding->facing_target_actor_address == 0 &&
            ongoing.target_actor_address == 0;
        if (held_native_cast && target_refreshed &&
            binding->facing_target_actor_address != 0 &&
            ongoing.target_actor_address != 0) {
            ongoing.targetless_ticks_waiting = 0;
        } else if (held_target_missing) {
            ongoing.targetless_ticks_waiting += 1;
        }
        const bool target_lost =
            held_target_missing &&
            ongoing.targetless_ticks_waiting >=
                ParticipantEntityBinding::OngoingCastState::kTargetlessRetargetGraceTicks;
        // A live target does not prove a pure-primary handler is still making
        // progress. Ether can leave actor+0xE4/0xE8 asserted without publishing
        // a handle, so the safety cap must always be able to release the cast.
        const bool safety_cap_hit =
            ongoing.ticks_waiting >= ResolveBotCastSafetyCapTicks(native_active_skill_id);

        if (mana_depleted) {
            ReleaseSpellHandle(ongoing, "mana_depleted", true);
            ongoing = ParticipantEntityBinding::OngoingCastState{};
            return true;
        }

        if (bounded_release_just_requested) {
            ongoing.startup_in_progress = false;
            const bool release_for_damage =
                ongoing.bounded_release_at_damage_threshold &&
                !ongoing.bounded_release_at_max_size;
            bool threshold_charge_write_ok = !release_for_damage;
            bool threshold_max_write_ok = !release_for_damage;
            bool release_charge_write_ok = false;
            const float finalized_release_charge =
                std::isfinite(ongoing.bounded_release_charge) &&
                        ongoing.bounded_release_charge > 0.0f
                    ? ongoing.bounded_release_charge
                    : active_spell_snapshot.object_f74;
            if (active_spell_snapshot.object != 0 &&
                std::isfinite(finalized_release_charge) &&
                finalized_release_charge > 0.0f) {
                // Stock cleanup's secondary release consumes object+0x1F0.
                // Keep it synchronized to the chosen release charge before the
                // native world-update window begins.
                release_charge_write_ok =
                    memory.TryWriteField<float>(
                        active_spell_snapshot.object,
                        0x1F0,
                        finalized_release_charge);
            }
            if (active_spell_snapshot.object != 0 &&
                std::isfinite(finalized_release_charge) &&
                finalized_release_charge > 0.0f) {
                if (release_for_damage) {
                    threshold_charge_write_ok = release_charge_write_ok;
                }
                // Finalize copies object+0x74 into object+0x1FC. Set 0x1FC
                // too so pre-finalize readers use the finalized damage size.
                threshold_max_write_ok =
                    memory.TryWriteField<float>(
                        active_spell_snapshot.object,
                        0x1FC,
                        finalized_release_charge);
            }
            Log(
                std::string("[bots] native ") +
                (release_for_damage ? "damage-threshold" : "max-size") +
                " reached; releasing held cast input for native launch. bot_id=" +
                std::to_string(binding->bot_id) +
                " skill_id=" + std::to_string(ongoing.skill_id) +
                " ticks=" + std::to_string(ongoing.ticks_waiting) +
                " group=" + HexString(active_spell_snapshot.group) +
                " slot=" + HexString(active_spell_snapshot.slot) +
                " handle_source=" +
                    (active_spell_snapshot.handle_from_selection_state ? std::string("selection") : std::string("actor")) +
                " selection_state=" + HexString(active_spell_snapshot.selection_state) +
                " obj_ptr=" + HexString(active_spell_snapshot.object) +
                " obj_type=" + HexString(active_spell_snapshot.object_type) +
                " obj_vt_6c=" + HexString(active_spell_snapshot.release_secondary_fn) +
                " obj_vt_70=" + HexString(active_spell_snapshot.release_finalize_fn) +
                " obj_74=" + std::to_string(active_spell_snapshot.object_f74) +
                " obj_1f0=" + std::to_string(active_spell_snapshot.object_f1f0) +
                " obj_1fc=" + std::to_string(active_spell_snapshot.object_f1fc) +
                " obj_22c=" + HexString(active_spell_snapshot.object_f22c) +
                " obj_230=" + HexString(active_spell_snapshot.object_f230) +
                " max_charge=" + std::to_string(earth_max_charge) +
                " statbook_level=" + std::to_string(earth_damage_projection.statbook_level) +
                " stat_source=" + HexString(earth_damage_projection.stat_source) +
                " stat_vt=" + HexString(earth_damage_projection.stat_vtable) +
                " damage_getter=" + HexString(earth_damage_projection.damage_getter) +
                " damage_getter_attempt=" +
                    (earth_damage_projection.damage_getter_attempted ? std::string("1") : std::string("0")) +
                " damage_getter_seh=" + HexString(earth_damage_projection.damage_getter_seh) +
                " damage_native=" +
                    (earth_damage_projection.native_damage_scale_available ? std::string("1") : std::string("0")) +
                " impact_context_write=" +
                    (earth_damage_projection.impact_context_write_ok ? std::string("1") : std::string("0")) +
                " impact_context_x=" +
                    std::to_string(earth_damage_projection.impact_context_x) +
                " impact_context_y=" +
                    std::to_string(earth_damage_projection.impact_context_y) +
                " impact_context_radius=" +
                    std::to_string(earth_damage_projection.impact_context_radius) +
                " base_damage=" + std::to_string(earth_damage_projection.base_damage) +
                " statbook_damage=" + std::to_string(earth_damage_projection.statbook_damage) +
                " projected_damage=" +
                    std::to_string(earth_damage_projection.projected_damage) +
                " target_actor=" + HexString(earth_damage_projection.target_actor) +
                " target_health=" + HexString(earth_damage_projection.target_health_base) +
                " target_health_kind=" + earth_damage_projection.target_health_kind +
                " target_hp=" + std::to_string(earth_damage_projection.target_hp) +
                " target_max_hp=" + std::to_string(earth_damage_projection.target_max_hp) +
                " target_x=" + std::to_string(earth_damage_projection.target_x) +
                " target_y=" + std::to_string(earth_damage_projection.target_y) +
                " target_radius=" + std::to_string(earth_damage_projection.target_radius) +
                " target_distance=" + std::to_string(earth_damage_projection.target_distance) +
                " target_impact_radius=" +
                    std::to_string(earth_damage_projection.target_impact_radius) +
                " target_damage_scale=" +
                    std::to_string(earth_damage_projection.target_damage_scale) +
                " target_in_impact=" +
                    (earth_damage_projection.target_in_impact ? std::string("1") : std::string("0")) +
                " native_cleanup_release=" + (release_for_damage ? std::string("1") : std::string("0")) +
                " threshold_charge_write=" +
                    (threshold_charge_write_ok ? std::string("1") : std::string("0")) +
                " threshold_max_write=" +
                    (threshold_max_write_ok ? std::string("1") : std::string("0")) +
                " release_charge_write=" +
                    (release_charge_write_ok ? std::string("1") : std::string("0")));
            return true;
        }

        if (pure_primary_no_handle_settled || startup_timeout_hit || activity_released ||
            bounded_held_native_released || bounded_held_release_tick_processed ||
            gesture_window_complete || target_lost || safety_cap_hit) {
            const char* exit_label = "safety_cap";
            if (startup_timeout_hit) {
                exit_label = "startup_timeout";
            } else if (pure_primary_no_handle_settled) {
                exit_label = "pure_primary_no_handle_settled";
            } else if (bounded_held_native_released || bounded_held_release_tick_processed) {
                exit_label = ongoing.bounded_release_at_damage_threshold &&
                                     !ongoing.bounded_release_at_max_size
                                 ? "damage_threshold_released"
                                 : "max_size_released";
            } else if (activity_released) {
                exit_label = "activity_released";
            } else if (gesture_window_complete) {
                exit_label = "gesture_window_complete";
            } else if (target_lost) {
                exit_label = "target_lost";
            }
            if (startup_timeout_hit) {
                LogSpellObjectDiag(active_cast_group);
            }
            const bool completed_bounded_release =
                bounded_held_native_released || bounded_held_release_tick_processed;
            ReleaseSpellHandle(ongoing, exit_label, target_lost);
            if (completed_bounded_release &&
                ongoing.bounded_release_requested &&
                ongoing.bounded_release_at_damage_threshold &&
                !ongoing.bounded_release_at_max_size) {
                ScheduleBoundedReleaseLatchClear(ongoing);
            } else {
                ongoing = ParticipantEntityBinding::OngoingCastState{};
            }
        }
        return true;
    }

    if (actor_dead) {
        multiplayer::BotCastRequest discarded_request{};
        while (multiplayer::ConsumePendingBotCast(binding->bot_id, &discarded_request)) {
            discarded_request = multiplayer::BotCastRequest{};
        }
        (void)multiplayer::FinishBotAttack(
            binding->bot_id,
            true,
            memory.ReadFieldOr<float>(actor_address, kActorHeadingOffset, 0.0f),
            true);
        return false;
    }

    if (IsGameplaySlotWizardKind(binding->kind)) {
        return false;
    }

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
            aim_heading = std::atan2(dy, dx) * kRadiansToDegrees + 90.0f;
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
    if (active_cast_group_before != kActorActiveCastGroupSentinel) {
        DWORD prior_cleanup_seh = 0;
        bool prior_cleanup_ok = false;
        InvokeWithLocalPlayerSlot([&] {
            prior_cleanup_ok = CallCastActiveHandleCleanupSafe(
                cleanup_address, actor_address, &prior_cleanup_seh);
        });
        if (!prior_cleanup_ok) {
            (void)memory.TryWriteField<std::uint8_t>(
                actor_address, kActorActiveCastGroupByteOffset, kActorActiveCastGroupSentinel);
            (void)memory.TryWriteField<std::uint16_t>(
                actor_address, kActorActiveCastSlotShortOffset, kActorActiveCastSlotSentinel);
        }
    }

    DWORD exception_code = 0;
    bool dispatched = false;
    InvokeWithLocalPlayerSlot([&] {
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
        if (group_post_diag != kActorActiveCastGroupSentinel &&
            slot_post_diag != kActorActiveCastSlotSentinel && world_ptr_diag != 0) {
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
        RestoreAim(rollback);
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
        active_group_post != kActorActiveCastGroupSentinel ||
        drive_state_post != 0 ||
        no_interrupt_post != 0;
    if (!ongoing.requires_local_slot_native_tick &&
        (active_group_post == kActorActiveCastGroupSentinel ||
         (drive_state_post == 0 && no_interrupt_post == 0))) {
        ongoing.saw_latch = (drive_state_post != 0 || no_interrupt_post != 0);
        ongoing.saw_activity = ongoing.saw_activity || ongoing.saw_latch;
        ReleaseSpellHandle(ongoing, "instant", false);
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

void LogLocalPlayerAnimationProbe() {
    uintptr_t gameplay_address = 0;
    uintptr_t actor_address = 0;
    if (!TryResolveCurrentGameplayScene(&gameplay_address) || gameplay_address == 0 ||
        !TryResolvePlayerActorForSlot(gameplay_address, 0, &actor_address) ||
        actor_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    const auto current_x = memory.ReadFieldOr<float>(actor_address, kActorPositionXOffset, 0.0f);
    const auto current_y = memory.ReadFieldOr<float>(actor_address, kActorPositionYOffset, 0.0f);

    bool moving_now = false;
    if (g_local_player_animation_probe_has_last_position) {
        const auto delta_x = current_x - g_local_player_animation_probe_last_x;
        const auto delta_y = current_y - g_local_player_animation_probe_last_y;
        moving_now = std::sqrt((delta_x * delta_x) + (delta_y * delta_y)) > 0.01f;
    }

    g_local_player_animation_probe_last_x = current_x;
    g_local_player_animation_probe_last_y = current_y;
    g_local_player_animation_probe_has_last_position = true;
    CaptureObservedPlayerAnimationDriveProfile(actor_address, moving_now);
}
