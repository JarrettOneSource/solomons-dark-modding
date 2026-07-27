bool TryCaptureNativeMinionStateInternal(
    uintptr_t actor_address,
    SDModNativeMinionState* state) {
    if (state != nullptr) {
        *state = {};
    }
    std::uint32_t native_type_id = 0;
    if (state == nullptr ||
        !TryReadNativeMinionType(
            actor_address,
            &native_type_id)) {
        return false;
    }
    const auto* descriptor =
        FindNativeMinionDescriptor(native_type_id);
    if (descriptor == nullptr) {
        return false;
    }

    state->kind = descriptor->kind;
    state->native_type_id = native_type_id;
    state->owner_participant_id =
        ResolveNativeMinionOwnerParticipantId(actor_address);
    if (state->owner_participant_id == 0) {
        return false;
    }
    state->state_flags =
        multiplayer::NativeMinionStateFlagActive;

    switch (descriptor->state_shape) {
    case NativeMinionStateShape::GoodImp:
        if (!ProcessMemory::Instance().TryReadField(
                actor_address,
                kGoodImpLifetimeOffset,
                &state->native_age)) {
            return false;
        }
        break;
    case NativeMinionStateShape::Leviathan: {
        std::uint8_t phase = 0;
        std::int32_t phase_timer = 0;
        if (!ProcessMemory::Instance().TryReadField(
                actor_address,
                kLeviathanScaleOffset,
                &state->steering_heading) ||
            !ProcessMemory::Instance().TryReadField(
                actor_address,
                kLeviathanPhaseOffset,
                &phase) ||
            !ProcessMemory::Instance().TryReadField(
                actor_address,
                kLeviathanPhaseTimerOffset,
                &phase_timer) ||
            !std::isfinite(state->steering_heading)) {
            return false;
        }
        state->animation_phase =
            static_cast<float>(phase);
        state->native_age = static_cast<std::uint32_t>(
            (std::max)(phase_timer, 0));
        break;
    }
    case NativeMinionStateShape::Golem:
        if (!TryCaptureGolemNativeMinionState(
                actor_address,
                state)) {
            return false;
        }
        break;
    }

    state->valid = true;
    return true;
}

bool ShouldRetireUnboundNativeMinionObserver(
    uintptr_t actor_address,
    std::uint32_t native_type_id,
    const multiplayer::WorldSnapshotRuntimeInfo& snapshot,
    std::uint64_t now_ms) {
    if (!multiplayer::IsLocalTransportClient() ||
        actor_address == 0 ||
        !multiplayer::IsNativeMinionType(native_type_id)) {
        return false;
    }

    SDModNativeMinionState local_state;
    if (!TryCaptureNativeMinionStateInternal(
            actor_address,
            &local_state) ||
        !local_state.valid ||
        local_state.owner_participant_id == 0) {
        return false;
    }

    std::uint64_t first_observed_ms = now_ms;
    {
        std::lock_guard<std::recursive_mutex> lock(
            g_native_minion_state_mutex);
        const auto [entry, inserted] =
            g_native_minion_first_observed_ms_by_actor
                .try_emplace(actor_address, now_ms);
        (void)inserted;
        first_observed_ms = entry->second;
    }
    if (now_ms < first_observed_ms ||
        now_ms - first_observed_ms <
            kNativeMinionObserverBindingGraceMs) {
        return false;
    }

    return std::any_of(
        snapshot.actors.begin(),
        snapshot.actors.end(),
        [&](const multiplayer::WorldActorSnapshot&
                authoritative_actor) {
            return authoritative_actor.native_minion &&
                authoritative_actor.native_type_id ==
                    native_type_id &&
                authoritative_actor.native_minion_state
                    .owner_participant_id ==
                    local_state.owner_participant_id;
        });
}

bool IsSaneNativeMinionApplyFloat(float value) {
    return std::isfinite(value) &&
        std::abs(value) <= 1'000'000.0f;
}

bool ApplyReplicatedNativeMinionState(
    uintptr_t actor_address,
    const multiplayer::WorldActorSnapshot& authoritative_actor) {
    if (actor_address == 0 ||
        !authoritative_actor.native_minion ||
        authoritative_actor.native_minion_state.owner_participant_id == 0 ||
        (authoritative_actor.native_minion_state.state_flags &
         multiplayer::NativeMinionStateFlagActive) == 0 ||
        (authoritative_actor.native_minion_state.state_flags &
         multiplayer::NativeMinionStateFlagTerminal) != 0) {
        return false;
    }

    std::uint32_t native_type_id = 0;
    if (!TryReadNativeMinionType(
            actor_address,
            &native_type_id) ||
        native_type_id != authoritative_actor.native_type_id) {
        return false;
    }
    RememberNativeMinionOwner(
        actor_address,
        authoritative_actor.native_minion_state
            .owner_participant_id);

    const auto& state =
        authoritative_actor.native_minion_state;
    auto& memory = ProcessMemory::Instance();
    if (native_type_id == kGoodImpNativeTypeId) {
        return memory.TryWriteField(
            actor_address,
            kGoodImpLifetimeOffset,
            state.native_age);
    }
    if (native_type_id == kLeviathanNativeTypeId) {
        const auto phase = static_cast<std::uint8_t>(
            state.animation_phase);
        const auto phase_timer = static_cast<std::int32_t>(
            state.native_age);
        return IsSaneNativeMinionApplyFloat(
                   state.steering_heading) &&
            memory.TryWriteField(
                actor_address,
                kLeviathanScaleOffset,
                state.steering_heading) &&
            memory.TryWriteField(
                actor_address,
                kLeviathanPhaseOffset,
                phase) &&
            memory.TryWriteField(
                actor_address,
                kLeviathanPhaseTimerOffset,
                phase_timer);
    }
    if (native_type_id != kGolemNativeTypeId ||
        !IsSaneNativeMinionApplyFloat(
            authoritative_actor.hp) ||
        !IsSaneNativeMinionApplyFloat(
            authoritative_actor.max_hp) ||
        authoritative_actor.max_hp <= 0.0f) {
        return false;
    }

    const auto gait_primary = static_cast<std::int32_t>(
        state.gait_primary);
    const auto gait_secondary = static_cast<std::int32_t>(
        state.gait_secondary);
    const auto target_refresh_timer =
        static_cast<std::int32_t>(
            state.target_refresh_timer);
    const auto locomotion_sample_counter =
        static_cast<std::int32_t>(
            state.locomotion_sample_counter);
    const auto ambient_effect_timer =
        static_cast<std::int32_t>(
            state.ambient_effect_timer);
    const auto iron = static_cast<std::int32_t>(state.iron);
    const std::array<std::size_t, 13> integer_field_offsets = {{
        kGolemHpOffset,
        kGolemMaxHpOffset,
        kActorSpellTargetGroupByteOffset,
        kActorSpellTargetSlotShortOffset,
        kGolemNativeAgeOffset,
        kGolemAttackTimerOffset,
        kGolemAttackCooldownOffset,
        kGolemGaitPrimaryOffset,
        kGolemGaitSecondaryOffset,
        kGolemTargetRefreshTimerOffset,
        kGolemLocomotionSampleCounterOffset,
        kGolemAmbientEffectTimerOffset,
        kGolemIronOffset,
    }};
    if (std::any_of(
            integer_field_offsets.begin(),
            integer_field_offsets.end(),
            [](std::size_t offset) {
                return offset == 0;
            })) {
        return false;
    }
    const std::int8_t no_target_group = -1;
    const std::int16_t no_target_slot = -1;
    const std::array<std::pair<std::size_t, float>, 6>
        float_fields = {{
            {kGolemAnimationPhaseOffset,
             state.animation_phase},
            {kGolemSteeringHeadingOffset,
             state.steering_heading},
            {kGolemSteeringStepOffset,
             state.steering_step},
            {kGolemDamagePrimaryOffset,
             state.damage_primary},
            {kGolemDamageSecondaryOffset,
             state.damage_secondary},
            {kGolemReflectRatioOffset,
             state.reflect_ratio},
        }};
    if (!std::all_of(
            float_fields.begin(),
            float_fields.end(),
            [](const auto& field) {
                return field.first != 0 &&
                    IsSaneNativeMinionApplyFloat(
                        field.second);
            })) {
        return false;
    }
    return memory.TryWriteField(
               actor_address,
               kGolemHpOffset,
               authoritative_actor.hp) &&
        memory.TryWriteField(
            actor_address,
            kGolemMaxHpOffset,
            authoritative_actor.max_hp) &&
        memory.TryWriteField(
            actor_address,
            kActorSpellTargetGroupByteOffset,
            no_target_group) &&
        memory.TryWriteField(
            actor_address,
            kActorSpellTargetSlotShortOffset,
            no_target_slot) &&
        memory.TryWriteField(
            actor_address,
            kGolemNativeAgeOffset,
            state.native_age) &&
        memory.TryWriteField(
            actor_address,
            kGolemAttackTimerOffset,
            state.attack_timer) &&
        memory.TryWriteField(
            actor_address,
            kGolemAttackCooldownOffset,
            state.attack_cooldown) &&
        memory.TryWriteField(
            actor_address,
            kGolemGaitPrimaryOffset,
            gait_primary) &&
        memory.TryWriteField(
            actor_address,
            kGolemGaitSecondaryOffset,
            gait_secondary) &&
        memory.TryWriteField(
            actor_address,
            kGolemTargetRefreshTimerOffset,
            target_refresh_timer) &&
        memory.TryWriteField(
            actor_address,
            kGolemLocomotionSampleCounterOffset,
            locomotion_sample_counter) &&
        memory.TryWriteField(
            actor_address,
            kGolemAmbientEffectTimerOffset,
            ambient_effect_timer) &&
        memory.TryWriteField(
            actor_address,
            kGolemIronOffset,
            iron) &&
        std::all_of(
            float_fields.begin(),
            float_fields.end(),
            [&](const auto& field) {
                return memory.TryWriteField(
                    actor_address,
                    field.first,
                    field.second);
            });
}

bool CallNativeMinionNoArgSafe(
    uintptr_t function_address,
    uintptr_t actor_address,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (function_address == 0 || actor_address == 0) {
        return false;
    }
    auto* function =
        reinterpret_cast<NativeMinionTickFn>(
            function_address);
    __try {
        function(reinterpret_cast<void*>(actor_address));
        return true;
    } __except (
        CaptureSehCode(
            GetExceptionInformation(),
            exception_code)) {
        return false;
    }
}
