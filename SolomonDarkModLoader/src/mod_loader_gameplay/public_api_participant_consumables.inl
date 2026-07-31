namespace {

constexpr float kConsumableVitalEpsilon = 0.01f;
constexpr std::int32_t kConsumableTimerMaximumTicks =
    24 * 60 * 60 * 100;

struct ParticipantConsumableNativeContext {
    uintptr_t actor_address = 0;
    uintptr_t progression_address = 0;
    std::uint32_t run_nonce = 0;
};

bool ResolveParticipantConsumableNativeContext(
    std::uint64_t participant_id,
    ParticipantConsumableNativeContext* context) {
    if (context == nullptr || participant_id == 0) {
        return false;
    }
    *context = {};

    const auto runtime = multiplayer::SnapshotRuntimeState();
    const auto* participant =
        multiplayer::FindParticipant(runtime, participant_id);
    if (participant == nullptr || !participant->runtime.in_run) {
        return false;
    }
    context->run_nonce = participant->runtime.run_nonce;

    if (participant->kind ==
        multiplayer::ParticipantKind::LocalHuman) {
        SDModPlayerState player;
        if (!TryGetPlayerState(&player) || !player.valid ||
            player.actor_address == 0 ||
            player.progression_address == 0) {
            return false;
        }
        context->actor_address = player.actor_address;
        context->progression_address =
            player.progression_address;
        return true;
    }

    SDModParticipantGameplayState gameplay;
    if (!TryGetParticipantGameplayState(
            participant_id,
            &gameplay) ||
        !gameplay.available ||
        !gameplay.entity_materialized ||
        gameplay.actor_address == 0 ||
        gameplay.progression_runtime_state_address == 0) {
        return false;
    }
    context->actor_address = gameplay.actor_address;
    context->progression_address =
        gameplay.progression_runtime_state_address;
    return true;
}

bool ReadParticipantConsumableVitals(
    const ParticipantConsumableNativeContext& context,
    float* hp,
    float* max_hp,
    float* mp,
    float* max_mp) {
    return hp != nullptr && max_hp != nullptr &&
        mp != nullptr && max_mp != nullptr &&
        TryReadFiniteFloatField(
            context.progression_address,
            kProgressionHpOffset,
            hp) &&
        TryReadFiniteFloatField(
            context.progression_address,
            kProgressionMaxHpOffset,
            max_hp) &&
        TryReadFiniteFloatField(
            context.progression_address,
            kProgressionMpOffset,
            mp) &&
        TryReadFiniteFloatField(
            context.progression_address,
            kProgressionMaxMpOffset,
            max_mp) &&
        *max_hp > 0.0f && *max_mp > 0.0f;
}

bool ReadConsumableTimerTicks(
    uintptr_t progression_address,
    std::size_t offset,
    std::int32_t* ticks) {
    if (ticks == nullptr || progression_address == 0 ||
        offset == 0 ||
        !ProcessMemory::Instance().TryReadField(
            progression_address,
            offset,
            ticks)) {
        return false;
    }
    *ticks = (std::clamp)(
        *ticks,
        std::int32_t{0},
        kConsumableTimerMaximumTicks);
    return true;
}

bool CallParticipantHealthDeltaSafe(
    uintptr_t actor_address,
    float delta) {
    const auto address =
        ProcessMemory::Instance().ResolveGameAddressOrZero(
            kPlayerActorApplyHealthDelta);
    if (actor_address == 0 || address == 0 ||
        !std::isfinite(delta) ||
        !ProcessMemory::Instance().IsExecutableRange(
            address,
            1)) {
        return false;
    }
    auto* apply = reinterpret_cast<
        PlayerActorApplyHealthDeltaFn>(address);
    __try {
        (void)apply(
            reinterpret_cast<void*>(actor_address),
            delta);
        return true;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return false;
    }
}

bool ParticipantManaDeltaAvailable() {
    return GetX86HookTrampoline<PlayerActorApplyManaDeltaFn>(
        g_gameplay_keyboard_injection
            .player_actor_apply_mana_delta_hook) != nullptr;
}

}  // namespace

bool TryGetParticipantConsumableState(
    std::uint64_t participant_id,
    SDModParticipantConsumableState* state) {
    if (state == nullptr) {
        return false;
    }
    *state = {};
    state->participant_id = participant_id;

    ParticipantConsumableNativeContext context;
    if (!ResolveParticipantConsumableNativeContext(
            participant_id,
            &context) ||
        !ReadParticipantConsumableVitals(
            context,
            &state->hp,
            &state->max_hp,
            &state->mp,
            &state->max_mp)) {
        return false;
    }

    std::int32_t damage_x4_ticks = 0;
    std::int32_t poison_immunity_ticks = 0;
    std::int32_t all_concentration_ticks = 0;
    state->timers_resolved =
        ReadConsumableTimerTicks(
            context.progression_address,
            kProgressionDamageX4RemainingTicksOffset,
            &damage_x4_ticks) &&
        ReadConsumableTimerTicks(
            context.progression_address,
            kProgressionPoisonImmunityRemainingTicksOffset,
            &poison_immunity_ticks) &&
        ReadConsumableTimerTicks(
            context.progression_address,
            kProgressionAllConcentrationRemainingTicksOffset,
            &all_concentration_ticks);
    if (state->timers_resolved) {
        constexpr float kNativeTimerTicksPerSecond = 100.0f;
        state->damage_x4_remaining_seconds =
            damage_x4_ticks / kNativeTimerTicksPerSecond;
        state->poison_immunity_remaining_seconds =
            poison_immunity_ticks / kNativeTimerTicksPerSecond;
        state->all_concentration_remaining_seconds =
            all_concentration_ticks /
            kNativeTimerTicksPerSecond;
    }
    state->run_nonce = context.run_nonce;
    state->available = true;
    return true;
}

bool TryGetParticipantPickupRange(
    std::uint64_t participant_id,
    float* pickup_range) {
    if (pickup_range == nullptr) {
        return false;
    }
    *pickup_range = 0.0f;

    ParticipantConsumableNativeContext context;
    return ResolveParticipantConsumableNativeContext(
               participant_id,
               &context) &&
        kProgressionPickupRangeOffset != 0 &&
        TryReadFiniteFloatField(
            context.progression_address,
            kProgressionPickupRangeOffset,
            pickup_range) &&
        *pickup_range > 0.0f;
}

bool TryApplyParticipantStockConsumable(
    std::uint64_t participant_id,
    std::int32_t stock_subtype,
    SDModParticipantStockConsumableResult* result,
    std::string* error_message) {
    if (result != nullptr) {
        *result = {};
        result->stock_subtype = stock_subtype;
    }
    if (error_message != nullptr) {
        error_message->clear();
    }
    const auto fail = [&](const char* message) {
        if (error_message != nullptr) {
            *error_message = message;
        }
        return false;
    };
    if (result == nullptr || error_message == nullptr) {
        return false;
    }
    if (stock_subtype != 0 &&
        stock_subtype != 1 &&
        stock_subtype != 5) {
        return fail(
            "This stock potion is observation-only because no participant-scoped native use path is proven.");
    }

    ParticipantConsumableNativeContext context;
    float max_hp = 0.0f;
    float max_mp = 0.0f;
    if (!ResolveParticipantConsumableNativeContext(
            participant_id,
            &context) ||
        !ReadParticipantConsumableVitals(
            context,
            &result->hp_before,
            &max_hp,
            &result->mp_before,
            &max_mp) ||
        result->hp_before <= 0.0f) {
        return fail(
            "The participant is dead or has no materialized native progression.");
    }

    const bool restore_hp =
        (stock_subtype == 0 || stock_subtype == 5) &&
        result->hp_before + kConsumableVitalEpsilon < max_hp;
    const bool restore_mp =
        (stock_subtype == 1 || stock_subtype == 5) &&
        result->mp_before + kConsumableVitalEpsilon < max_mp;
    if (!restore_hp && !restore_mp) {
        return fail(
            "The stock potion cannot change the participant's current vitals.");
    }
    if ((restore_hp &&
         ProcessMemory::Instance().ResolveGameAddressOrZero(
             kPlayerActorApplyHealthDelta) == 0) ||
        (restore_mp && !ParticipantManaDeltaAvailable())) {
        return fail(
            "The participant-scoped native potion effect path is unavailable.");
    }

    if (restore_hp &&
        !CallParticipantHealthDeltaSafe(
            context.actor_address,
            max_hp - result->hp_before)) {
        return fail(
            "The participant-scoped native health effect was rejected.");
    }
    if (restore_mp &&
        !TryApplyLocalRegisteredSpellManaDelta(
            context.actor_address,
            max_mp - result->mp_before)) {
        return fail(
            "The participant-scoped native mana effect was rejected.");
    }

    if (!ReadParticipantConsumableVitals(
            context,
            &result->hp_after,
            &max_hp,
            &result->mp_after,
            &max_mp) ||
        (restore_hp &&
         result->hp_after + kConsumableVitalEpsilon < max_hp) ||
        (restore_mp &&
         result->mp_after + kConsumableVitalEpsilon < max_mp)) {
        return fail(
            "The participant-scoped native potion effect did not reach its stock result.");
    }
    result->applied = true;
    return true;
}
