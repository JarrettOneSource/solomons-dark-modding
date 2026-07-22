bool NativeRemoteParticipantPlaybackTargetIsMoving(
    const ParticipantEntityBinding* binding,
    uintptr_t actor_address) {
    if (!IsNativeRemoteParticipantBinding(binding) ||
        actor_address == 0 ||
        !binding->replicated_transform_valid) {
        return false;
    }

    float x = 0.0f;
    float y = 0.0f;
    float heading = 0.0f;
    if (!TryReadFiniteFloatField(actor_address, kActorPositionXOffset, &x) ||
        !TryReadFiniteFloatField(actor_address, kActorPositionYOffset, &y) ||
        !TryReadFiniteFloatField(actor_address, kActorHeadingOffset, &heading)) {
        return false;
    }

    const float dx = binding->replicated_target_x - x;
    const float dy = binding->replicated_target_y - y;
    const float heading_delta =
        ShortestHeadingDeltaDegrees(heading, binding->replicated_target_heading);
    return dx * dx + dy * dy > 2.25f || std::fabs(heading_delta) > 2.0f;
}

NativeRemoteVitalSyncResult ApplyNativeRemoteParticipantVitalState(
    ParticipantEntityBinding* binding,
    uintptr_t actor_address) {
    NativeRemoteVitalSyncResult result;
    if (!IsNativeRemoteParticipantBinding(binding) ||
        actor_address == 0 ||
        binding->bot_id == 0) {
        return result;
    }

    const auto runtime_state = multiplayer::SnapshotRuntimeState();
    const auto* participant = multiplayer::FindParticipant(runtime_state, binding->bot_id);
    if (participant == nullptr ||
        !multiplayer::IsRemoteParticipant(*participant) ||
        !multiplayer::IsNativeControlledParticipant(*participant) ||
        !participant->runtime.valid) {
        return result;
    }
    result.applicable = true;

    uintptr_t progression_address = 0;
    if (!TryResolveActorProgressionRuntime(actor_address, &progression_address) ||
        progression_address == 0) {
        return result;
    }

    auto& memory = ProcessMemory::Instance();
    const auto clamp_to_max = [](float value, float maximum) {
        if (!std::isfinite(value)) {
            return 0.0f;
        }
        if (value < 0.0f) {
            return 0.0f;
        }
        if (std::isfinite(maximum) && maximum > 0.0f && value > maximum) {
            return maximum;
        }
        return value;
    };

    float native_hp = 0.0f;
    float native_max_hp = 0.0f;
    const bool native_health_readable =
        TryReadFiniteFloatField(
            progression_address,
            kProgressionHpOffset,
            &native_hp) &&
        TryReadFiniteFloatField(
            progression_address,
            kProgressionMaxHpOffset,
            &native_max_hp);
    NativeWizardTransientStatusState native_transient_state;
    const bool native_transient_readable =
        TryReadWizardActorTransientStatusState(
            actor_address,
            &native_transient_state);
    const auto native_transient_flags = native_transient_state.flags;
    const auto native_poison_remaining_ticks =
        native_transient_state.poison_remaining_ticks;
    const auto native_poison_modifier =
        native_transient_state.poison_modifier_address;
    const auto native_webbed_remaining_ticks =
        native_transient_state.webbed_remaining_ticks;
    const auto native_webbed_strength =
        native_transient_state.webbed_strength;
    float native_poison_damage_per_tick = 0.0f;
    const bool native_poison_damage_readable =
        native_poison_modifier != 0 &&
        memory.TryReadField(
            native_poison_modifier,
            kNativePoisonDamagePerTickOffset,
            &native_poison_damage_per_tick) &&
        std::isfinite(native_poison_damage_per_tick) &&
        native_poison_damage_per_tick >= 0.0f &&
        native_poison_damage_per_tick <= 10000.0f;
    std::int8_t native_poison_source_slot = 1;
    const bool native_poison_source_readable =
        native_poison_modifier != 0 &&
        memory.TryReadField(
            native_poison_modifier,
            kNativePoisonSourceSlotOffset,
            &native_poison_source_slot);
    const float expected_hp =
        clamp_to_max(
            participant->runtime.life_current,
            participant->runtime.life_max);
    const bool native_max_matches_last_write =
        native_health_readable &&
        binding->native_remote_vital_baseline_valid &&
        std::isfinite(binding->native_remote_last_written_max_hp) &&
        binding->native_remote_last_written_max_hp > 0.0f &&
        std::fabs(
            native_max_hp - binding->native_remote_last_written_max_hp) <=
            (std::max)(
                1.0f,
                binding->native_remote_last_written_max_hp * 0.1f);
    const bool replicated_life_increased_since_last_write =
        binding->native_remote_vital_baseline_valid &&
        expected_hp > binding->native_remote_last_written_hp + 0.0001f;
    const float damage_reference_hp =
        (std::min)(expected_hp, binding->native_remote_last_written_hp);
    const bool native_damage_observed =
        native_max_matches_last_write &&
        !replicated_life_increased_since_last_write &&
        native_hp >= 0.0f &&
        native_hp + 0.05f < damage_reference_hp;
    const bool native_hagatha_runtime_observed =
        native_max_matches_last_write &&
        native_hp >= 0.0f &&
        multiplayer::HasAuthoritativeHagathaRuntimeStateChanged(
            binding->bot_id);
    const bool native_poison_observed =
        native_transient_readable &&
        (native_transient_flags &
         multiplayer::ParticipantTransientStatusFlagPoisoned) != 0 &&
        (participant->runtime.transient_status_flags &
         multiplayer::ParticipantTransientStatusFlagPoisoned) == 0 &&
        native_poison_damage_readable &&
        native_poison_source_readable &&
        (native_poison_source_slot != 1 ||
         native_poison_damage_per_tick > 0.000001f);
    const bool native_webbed_observed =
        native_transient_readable &&
        (native_transient_flags &
         multiplayer::ParticipantTransientStatusFlagWebbed) != 0 &&
        (participant->runtime.transient_status_flags &
         multiplayer::ParticipantTransientStatusFlagWebbed) == 0 &&
        native_webbed_remaining_ticks > 0 &&
        std::isfinite(native_webbed_strength) &&
        native_webbed_strength > 0.0f &&
        native_webbed_strength <=
            multiplayer::kParticipantWebbedMaxStrength &&
        !binding->native_remote_webbed_owner_acknowledged &&
        (!binding->native_remote_webbed_authority_pending ||
         static_cast<std::uint64_t>(GetTickCount64()) -
                 binding->native_remote_webbed_authority_pending_since_ms >=
             2000);
    if (native_damage_observed ||
        native_hagatha_runtime_observed ||
        native_poison_observed ||
        native_webbed_observed) {
        std::uint8_t corrected_status_flags = 0;
        if (native_poison_observed) {
            corrected_status_flags |=
                multiplayer::ParticipantTransientStatusFlagPoisoned;
        }
        if (native_webbed_observed) {
            corrected_status_flags |=
                multiplayer::ParticipantTransientStatusFlagWebbed;
            binding->native_remote_webbed_authority_pending = true;
            binding->native_remote_webbed_authority_pending_since_ms =
                static_cast<std::uint64_t>(GetTickCount64());
        }
        const float corrected_life =
            (native_damage_observed || native_hagatha_runtime_observed)
                ? native_hp
                : expected_hp;
        multiplayer::QueueHostParticipantVitalsCorrection(
            binding->bot_id,
            corrected_life,
            native_max_matches_last_write
                ? native_max_hp
                : participant->runtime.life_max,
            corrected_status_flags,
            native_poison_observed ? native_poison_remaining_ticks : 0,
            native_poison_observed && native_poison_damage_readable
                ? native_poison_damage_per_tick
                : 0.0f,
            native_webbed_observed ? native_webbed_remaining_ticks : 0,
            native_webbed_observed ? native_webbed_strength : 0.0f,
            0,
            0.0f,
            0.0f,
            0.0f,
            0.0f);
    }

    if (std::isfinite(participant->runtime.life_max) &&
        participant->runtime.life_max > 0.0f &&
        std::isfinite(participant->runtime.life_current) &&
        memory.IsReadableRange(progression_address + kProgressionHpOffset, sizeof(float)) &&
        memory.IsReadableRange(progression_address + kProgressionMaxHpOffset, sizeof(float))) {
        const float max_hp = participant->runtime.life_max;
        const float hp = clamp_to_max(participant->runtime.life_current, max_hp);
        result.wrote_health =
            memory.TryWriteField(progression_address, kProgressionMaxHpOffset, max_hp) &&
            memory.TryWriteField(progression_address, kProgressionHpOffset, hp);
        if (result.wrote_health) {
            binding->native_remote_vital_baseline_valid = true;
            binding->native_remote_last_written_hp = hp;
            binding->native_remote_last_written_max_hp = max_hp;
        } else {
            binding->native_remote_vital_baseline_valid = false;
        }
        result.dead = result.wrote_health && hp <= 0.0f;
    }

    if (std::isfinite(participant->runtime.mana_max) &&
        participant->runtime.mana_max > 0.0f &&
        std::isfinite(participant->runtime.mana_current) &&
        memory.IsReadableRange(progression_address + kProgressionMpOffset, sizeof(float)) &&
        memory.IsReadableRange(progression_address + kProgressionMaxMpOffset, sizeof(float))) {
        const float max_mp = participant->runtime.mana_max;
        const float mp = clamp_to_max(participant->runtime.mana_current, max_mp);
        result.wrote_mana =
            memory.TryWriteField(progression_address, kProgressionMaxMpOffset, max_mp) &&
            memory.TryWriteField(progression_address, kProgressionMpOffset, mp);
    }

    return result;
}

NativeRemotePlaybackResult ApplyNativeRemoteParticipantPlayback(
    ParticipantEntityBinding* binding,
    uintptr_t actor_address,
    std::uint64_t now_ms) {
    NativeRemotePlaybackResult result;
    if (!IsNativeRemoteParticipantBinding(binding) ||
        actor_address == 0 ||
        !binding->replicated_transform_valid) {
        return result;
    }
    result.applicable = true;

    float x = 0.0f;
    float y = 0.0f;
    float heading = 0.0f;
    if (!TryReadFiniteFloatField(actor_address, kActorPositionXOffset, &x) ||
        !TryReadFiniteFloatField(actor_address, kActorPositionYOffset, &y) ||
        !TryReadFiniteFloatField(actor_address, kActorHeadingOffset, &heading)) {
        return result;
    }

    const auto& ongoing_cast = binding->ongoing_cast;
    // Fire's native projectile allocator samples actor+0x6C when the projectile
    // is born, several stock ticks after the replicated cast was prepared.
    // The replay aim heading uses the wizard presentation convention, while
    // Fire converts actor+0x6C through (cos(angle), -sin(angle)). Convert to
    // that native direction convention until projectile birth; an older
    // transform heading or the presentation heading would seed the wrong
    // Fireball+0x13C/+0x140 velocity.
    const bool live_cast_heading_valid =
        ongoing_cast.active &&
        ongoing_cast.have_aim_heading &&
        std::isfinite(ongoing_cast.aim_heading);
    const bool fireball_heading_owns_native_initialization =
        live_cast_heading_valid &&
        ongoing_cast.selection_state_target ==
            ResolveNativePrimaryEntryForElement(0) &&
        !ongoing_cast.remote_per_cast_projectile_observed;
    const float next_heading =
        fireball_heading_owns_native_initialization
            ? NormalizeWizardActorHeadingForWrite(90.0f - ongoing_cast.aim_heading)
            : (live_cast_heading_valid
                   ? NormalizeWizardActorHeadingForWrite(ongoing_cast.aim_heading)
                   : binding->replicated_target_heading);

    const float dx = binding->replicated_target_x - x;
    const float dy = binding->replicated_target_y - y;
    const float distance_sq = dx * dx + dy * dy;
    const float distance = std::sqrt(distance_sq);
    const float heading_delta =
        ShortestHeadingDeltaDegrees(heading, next_heading);
    result.moving = distance > 1.5f || std::fabs(heading_delta) > 2.0f;

    constexpr float kRemoteSnapDistance = 360.0f;
    constexpr float kRemoteSettleDistance = 0.05f;

    const bool large_discontinuity = distance > kRemoteSnapDistance;
    const float position_write_distance = large_discontinuity ? 0.0f : kRemoteSettleDistance;
    const float next_x = binding->replicated_target_x;
    const float next_y = binding->replicated_target_y;
    auto& memory = ProcessMemory::Instance();
    if (distance > position_write_distance) {
        result.wrote_position =
            memory.TryWriteField(actor_address, kActorPositionXOffset, next_x) &&
            memory.TryWriteField(actor_address, kActorPositionYOffset, next_y);
        if (result.wrote_position) {
            const auto rebind_actor_address = memory.ResolveGameAddressOrZero(kWorldCellGridRebindActor);
            uintptr_t world_address = 0;
            if (rebind_actor_address != 0 &&
                memory.TryReadField(actor_address, kActorOwnerOffset, &world_address) &&
                world_address != 0) {
                DWORD rebind_exception_code = 0;
                (void)CallWorldCellGridRebindActorSafe(
                    rebind_actor_address,
                    world_address,
                    actor_address,
                    &rebind_exception_code);
            }
        }
    }
    ApplyWizardActorFacingState(actor_address, next_heading);
    result.presentation_valid = binding->replicated_presentation_valid;
    result.wrote_presentation =
        ApplyNativeRemoteParticipantPresentationState(binding, actor_address);
    binding->replicated_transform_playback_ms = now_ms;
    PublishParticipantGameplaySnapshot(*binding);
    return result;
}
