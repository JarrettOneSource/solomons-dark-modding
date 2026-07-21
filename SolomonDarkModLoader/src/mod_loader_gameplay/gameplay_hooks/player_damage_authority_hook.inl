struct RemoteMagicShieldDamageAuthority {
    bool applicable = false;
    std::uint64_t participant_id = 0;
    uintptr_t actor_address = 0;
};

constexpr float kRemoteMagicShieldAuthorityEpsilon = 0.001f;
constexpr float kRemoteMagicShieldMaximumAbsorb = 1'000'000.0f;
constexpr float kRemoteMagicShieldMaximumExplosionFraction = 100.0f;

bool TryPrepareRemoteMagicShieldDamageAuthority(
    uintptr_t actor_address,
    RemoteMagicShieldDamageAuthority* authority,
    std::string* error_message) {
    if (authority == nullptr) {
        return false;
    }
    *authority = RemoteMagicShieldDamageAuthority{};
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!multiplayer::IsLocalTransportHost() || actor_address == 0) {
        return true;
    }

    float absorb_remaining = 0.0f;
    float absorb_capacity = 0.0f;
    float explosion_fraction = 0.0f;
    float hit_flash = 0.0f;
    {
        std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
        const auto* binding = FindParticipantEntityForActor(actor_address);
        if (binding == nullptr ||
            !IsNativeRemoteParticipantBinding(binding) ||
            binding->bot_id == 0) {
            return true;
        }
        absorb_remaining =
            binding->replicated_magic_shield_absorb_remaining;
        if (!std::isfinite(absorb_remaining) ||
            absorb_remaining <= kRemoteMagicShieldAuthorityEpsilon) {
            return true;
        }
        authority->applicable = true;
        authority->participant_id = binding->bot_id;
        authority->actor_address = actor_address;
        absorb_capacity = binding->replicated_magic_shield_absorb_capacity;
        explosion_fraction =
            binding->replicated_magic_shield_explosion_fraction;
        hit_flash = binding->replicated_magic_shield_hit_flash;
    }

    if (!std::isfinite(absorb_capacity) ||
        !std::isfinite(explosion_fraction) ||
        !std::isfinite(hit_flash) ||
        absorb_remaining > kRemoteMagicShieldMaximumAbsorb ||
        absorb_capacity < absorb_remaining ||
        absorb_capacity > kRemoteMagicShieldMaximumAbsorb ||
        explosion_fraction < 0.0f ||
        explosion_fraction > kRemoteMagicShieldMaximumExplosionFraction) {
        if (error_message != nullptr) {
            *error_message = "replicated Magic Shield state is invalid";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    if (!memory.TryWriteField(
            actor_address,
            kActorMagicShieldAbsorbRemainingOffset,
            absorb_remaining) ||
        !memory.TryWriteField(
            actor_address,
            kActorMagicShieldAbsorbCapacityOffset,
            absorb_capacity) ||
        !memory.TryWriteField(
            actor_address,
            kActorMagicShieldExplosionFractionOffset,
            explosion_fraction) ||
        !memory.TryWriteField(
            actor_address,
            kActorMagicShieldHitFlashOffset,
            (std::clamp)(hit_flash, 0.0f, 1.0f))) {
        if (error_message != nullptr) {
            *error_message = "native Magic Shield state could not be primed";
        }
        return false;
    }
    return true;
}

bool PublishRemoteMagicShieldDamageAuthority(
    const RemoteMagicShieldDamageAuthority& authority,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!authority.applicable ||
        authority.participant_id == 0 ||
        authority.actor_address == 0) {
        return true;
    }

    auto& memory = ProcessMemory::Instance();
    float absorb_remaining = 0.0f;
    float absorb_capacity = 0.0f;
    float explosion_fraction = 0.0f;
    float hit_flash = 0.0f;
    uintptr_t progression_address = 0;
    float life_current = 0.0f;
    float life_max = 0.0f;
    if (!TryReadFiniteFloatField(
            authority.actor_address,
            kActorMagicShieldAbsorbRemainingOffset,
            &absorb_remaining) ||
        !TryReadFiniteFloatField(
            authority.actor_address,
            kActorMagicShieldAbsorbCapacityOffset,
            &absorb_capacity) ||
        !TryReadFiniteFloatField(
            authority.actor_address,
            kActorMagicShieldExplosionFractionOffset,
            &explosion_fraction) ||
        !TryReadFiniteFloatField(
            authority.actor_address,
            kActorMagicShieldHitFlashOffset,
            &hit_flash) ||
        !TryResolveActorProgressionRuntime(
            authority.actor_address,
            &progression_address) ||
        progression_address == 0 ||
        !TryReadFiniteFloatField(
            progression_address,
            kProgressionHpOffset,
            &life_current) ||
        !TryReadFiniteFloatField(
            progression_address,
            kProgressionMaxHpOffset,
            &life_max) ||
        life_max <= 0.0f) {
        if (error_message != nullptr) {
            *error_message = "post-hit remote participant vitals are unreadable";
        }
        return false;
    }

    if (absorb_remaining <= kRemoteMagicShieldAuthorityEpsilon) {
        absorb_remaining = 0.0f;
        absorb_capacity = 0.0f;
        explosion_fraction = 0.0f;
        hit_flash = 0.0f;
    } else if (
        absorb_remaining > kRemoteMagicShieldMaximumAbsorb ||
        absorb_capacity < absorb_remaining ||
        absorb_capacity > kRemoteMagicShieldMaximumAbsorb ||
        explosion_fraction < 0.0f ||
        explosion_fraction > kRemoteMagicShieldMaximumExplosionFraction) {
        if (error_message != nullptr) {
            *error_message = "post-hit native Magic Shield state is invalid";
        }
        return false;
    } else {
        hit_flash = (std::clamp)(hit_flash, 0.0f, 1.0f);
    }

    std::uint8_t transient_status_flags = 0;
    std::int32_t poison_remaining_ticks = 0;
    float poison_damage_per_tick = 0.0f;
    std::int32_t webbed_remaining_ticks = 0;
    float webbed_strength = 0.0f;
    const auto runtime_state = multiplayer::SnapshotRuntimeState();
    const auto* participant =
        multiplayer::FindParticipant(runtime_state, authority.participant_id);
    if (participant == nullptr ||
        !multiplayer::IsRemoteParticipant(*participant) ||
        !participant->runtime.valid ||
        !participant->runtime.in_run) {
        if (error_message != nullptr) {
            *error_message = "remote participant runtime is unavailable";
        }
        return false;
    }
    NativeWizardTransientStatusState native_transient_state;
    if (!TryReadWizardActorTransientStatusState(
            authority.actor_address,
            &native_transient_state)) {
        if (error_message != nullptr) {
            *error_message = "post-hit remote transient state is unreadable";
        }
        return false;
    }
    transient_status_flags = static_cast<std::uint8_t>(
        native_transient_state.flags &
        (multiplayer::ParticipantTransientStatusFlagPoisoned |
         multiplayer::ParticipantTransientStatusFlagWebbed));
    if ((transient_status_flags &
         multiplayer::ParticipantTransientStatusFlagPoisoned) != 0) {
        poison_remaining_ticks =
            native_transient_state.poison_remaining_ticks;
        if (native_transient_state.poison_modifier_address == 0 ||
            !memory.TryReadField(
                native_transient_state.poison_modifier_address,
                kNativePoisonDamagePerTickOffset,
                &poison_damage_per_tick) ||
            !std::isfinite(poison_damage_per_tick) ||
            poison_damage_per_tick < 0.0f ||
            poison_damage_per_tick > 10000.0f) {
            if (error_message != nullptr) {
                *error_message = "post-hit remote poison state is invalid";
            }
            return false;
        }
    }
    if ((transient_status_flags &
         multiplayer::ParticipantTransientStatusFlagWebbed) != 0) {
        webbed_remaining_ticks =
            native_transient_state.webbed_remaining_ticks;
        webbed_strength = native_transient_state.webbed_strength;
    }

    {
        std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
        auto* binding = FindParticipantEntityForActor(authority.actor_address);
        if (binding == nullptr ||
            binding->bot_id != authority.participant_id ||
            !IsNativeRemoteParticipantBinding(binding)) {
            if (error_message != nullptr) {
                *error_message = "remote participant binding changed during damage";
            }
            return false;
        }
        binding->replicated_magic_shield_absorb_remaining = absorb_remaining;
        binding->replicated_magic_shield_absorb_capacity = absorb_capacity;
        binding->replicated_magic_shield_explosion_fraction =
            explosion_fraction;
        binding->replicated_magic_shield_hit_flash = hit_flash;
        binding->native_remote_magic_shield_authority_pending = true;
    }

    multiplayer::QueueHostParticipantVitalsCorrection(
        authority.participant_id,
        life_current,
        life_max,
        transient_status_flags,
        poison_remaining_ticks,
        poison_damage_per_tick,
        webbed_remaining_ticks,
        webbed_strength,
        multiplayer::ParticipantVitalsCorrectionFlagMagicShieldState,
        absorb_remaining,
        absorb_capacity,
        explosion_fraction,
        hit_flash);
    return true;
}

std::uint32_t __fastcall HookPlayerActorMagicDamage(
    void* self,
    void* /*unused_edx*/) {
    const auto original = GetX86HookTrampoline<PlayerActorMagicDamageFn>(
        g_gameplay_keyboard_injection.player_actor_magic_damage_hook);
    if (original == nullptr) {
        return 0;
    }

    if (multiplayer::IsLocalTransportClient()) {
        // The host owns all incoming wizard damage and transient statuses.
        // Resetting the stock context also releases a rejected queued native
        // modifier so it cannot contaminate a later authoritative correction.
        const auto reset = reinterpret_cast<DamageContextResetFn>(
            g_gameplay_keyboard_injection.damage_context_reset_address);
        reset(reinterpret_cast<void*>(
            g_gameplay_keyboard_injection.damage_context_source_address));
        return 0;
    }

    const auto actor_address = reinterpret_cast<uintptr_t>(self);
    RemoteMagicShieldDamageAuthority shield_authority;
    std::string authority_error;
    if (!TryPrepareRemoteMagicShieldDamageAuthority(
            actor_address,
            &shield_authority,
            &authority_error)) {
        Log(
            "[gameplay] remote Magic Shield damage rejected. actor=" +
            HexString(actor_address) + " error=" + authority_error);
        return 0;
    }
    if (!shield_authority.applicable) {
        return original(self);
    }

    ScopedGameplayPlayerActorSlotContext player_slot_context(
        actor_address,
        true);
    ScopedActorSlotZeroContext actor_slot_context(actor_address, true);
    if (!player_slot_context.ready || !actor_slot_context.ready) {
        actor_slot_context.Restore();
        player_slot_context.Restore();
        Log(
            "[gameplay] remote Magic Shield slot transaction rejected. actor=" +
            HexString(actor_address) + " player_context={" +
            player_slot_context.Describe() + "} actor_context={" +
            actor_slot_context.Describe() + "}");
        return 0;
    }

    const auto result = original(self);
    actor_slot_context.Restore();
    player_slot_context.Restore();
    if (!actor_slot_context.restored || !player_slot_context.restored) {
        Log(
            "[gameplay] remote Magic Shield slot transaction restore failed. actor=" +
            HexString(actor_address) + " player_context={" +
            player_slot_context.Describe() + "} actor_context={" +
            actor_slot_context.Describe() + "}");
    }
    if (!PublishRemoteMagicShieldDamageAuthority(
            shield_authority,
            &authority_error)) {
        Log(
            "[gameplay] remote Magic Shield correction failed. participant_id=" +
            std::to_string(shield_authority.participant_id) +
            " actor=" + HexString(actor_address) +
            " error=" + authority_error);
    }
    return result;
}
