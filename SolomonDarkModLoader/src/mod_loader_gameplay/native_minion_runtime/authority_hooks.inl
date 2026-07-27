#include "authority_state.inl"

std::uint64_t ResolveNativeMinionOwnerParticipantId(
    uintptr_t actor_address) {
    if (actor_address == 0 || kActorSlotOffset == 0) {
        return 0;
    }
    {
        std::lock_guard<std::recursive_mutex> lock(
            g_native_minion_state_mutex);
        const auto remembered =
            g_native_minion_owner_by_actor.find(actor_address);
        if (remembered != g_native_minion_owner_by_actor.end()) {
            return remembered->second;
        }
    }

    std::int8_t actor_group = -1;
    if (!ProcessMemory::Instance().TryReadField(
            actor_address,
            kActorSlotOffset,
            &actor_group) ||
        actor_group < 0) {
        return 0;
    }

    SDModPlayerState local_player;
    const auto local_participant_id =
        multiplayer::GetLocalTransportParticipantId();
    if (local_participant_id != 0 &&
        TryGetPlayerState(&local_player) &&
        local_player.valid &&
        local_player.actor_slot == actor_group) {
        RememberNativeMinionOwner(
            actor_address,
            local_participant_id);
        return local_participant_id;
    }

    const auto runtime_state = multiplayer::SnapshotRuntimeState();
    for (const auto& participant : runtime_state.participants) {
        if (participant.participant_id == 0 ||
            participant.participant_id == local_participant_id) {
            continue;
        }
        SDModParticipantGameplayState gameplay_state;
        if (TryGetParticipantGameplayState(
                participant.participant_id,
                &gameplay_state) &&
            gameplay_state.available &&
            gameplay_state.entity_materialized &&
            gameplay_state.actor_slot == actor_group) {
            RememberNativeMinionOwner(
                actor_address,
                participant.participant_id);
            return participant.participant_id;
        }
    }
    return 0;
}

uintptr_t ResolveNativeMinionOwnerActor(
    std::uint64_t owner_participant_id) {
    if (owner_participant_id == 0) {
        return 0;
    }
    if (owner_participant_id ==
        multiplayer::GetLocalTransportParticipantId()) {
        SDModPlayerState player;
        return TryGetPlayerState(&player) && player.valid
            ? player.actor_address
            : 0;
    }

    std::lock_guard<std::recursive_mutex> lock(
        g_participant_entities_mutex);
    const auto* binding =
        FindParticipantEntity(owner_participant_id);
    return binding != nullptr ? binding->actor_address : 0;
}

bool TryResolveNativeMinionOwnerGameplaySlot(
    std::uint64_t owner_participant_id,
    int* gameplay_slot) {
    if (gameplay_slot != nullptr) {
        *gameplay_slot = -1;
    }
    if (owner_participant_id == 0 || gameplay_slot == nullptr) {
        return false;
    }
    if (owner_participant_id ==
        multiplayer::GetLocalTransportParticipantId()) {
        SDModPlayerState local_player;
        if (TryGetPlayerState(&local_player) &&
            local_player.valid &&
            local_player.actor_slot >= 0) {
            *gameplay_slot = local_player.actor_slot;
            return true;
        }
        return false;
    }

    SDModParticipantGameplayState state;
    if (!TryGetParticipantGameplayState(
            owner_participant_id,
            &state) ||
        !state.available ||
        !state.entity_materialized ||
        state.actor_slot < 0) {
        return false;
    }
    *gameplay_slot = state.actor_slot;
    return true;
}

struct ScopedNativeMinionObserverSlotContext {
    uintptr_t actor_address = 0;
    std::int8_t original_slot = -1;
    bool active = false;
    bool ready = false;

    explicit ScopedNativeMinionObserverSlotContext(
        uintptr_t actor_address_in)
        : actor_address(actor_address_in) {
        auto& memory = ProcessMemory::Instance();
        if (actor_address == 0 ||
            !memory.TryReadField(
                actor_address,
                kActorSlotOffset,
                &original_slot)) {
            return;
        }
        if (original_slot != 0) {
            ready = true;
            return;
        }
        active = memory.TryWriteField<std::int8_t>(
            actor_address,
            kActorSlotOffset,
            1);
        ready = active;
    }

    ~ScopedNativeMinionObserverSlotContext() {
        if (active) {
            (void)ProcessMemory::Instance().TryWriteField(
                actor_address,
                kActorSlotOffset,
                original_slot);
        }
    }
};

struct ScopedAuthoritativeNativeMinionOwner {
    std::uint64_t previous_owner =
        g_authoritative_native_minion_tick_owner;

    explicit ScopedAuthoritativeNativeMinionOwner(
        std::uint64_t owner_participant_id) {
        g_authoritative_native_minion_tick_owner =
            owner_participant_id;
    }

    ~ScopedAuthoritativeNativeMinionOwner() {
        g_authoritative_native_minion_tick_owner =
            previous_owner;
    }
};

bool ReadActorRetirementPendingForNativeMinion(
    uintptr_t actor_address) {
    std::uint8_t pending = 0;
    return actor_address != 0 &&
        kActorPendingRemoveOffset != 0 &&
        ProcessMemory::Instance().TryReadField(
            actor_address,
            kActorPendingRemoveOffset,
            &pending) &&
        pending != 0;
}

void RunNativeMinionTick(
    void* self,
    X86Hook& hook,
    NativeMinionTerminalReason natural_terminal_reason) {
    const auto original =
        GetX86HookTrampoline<NativeMinionTickFn>(hook);
    if (original == nullptr || self == nullptr) {
        return;
    }
    if (!multiplayer::IsLocalTransportEnabled()) {
        original(self);
        return;
    }

    const auto actor_address =
        reinterpret_cast<uintptr_t>(self);
    const bool pending_before =
        ReadActorRetirementPendingForNativeMinion(actor_address);
    if (multiplayer::IsLocalTransportClient()) {
        ScopedNativeMinionObserverSlotContext observer_context(
            actor_address);
        if (observer_context.ready) {
            original(self);
        }
        return;
    }

    const auto owner_participant_id =
        ResolveNativeMinionOwnerParticipantId(actor_address);
    const auto owner_actor =
        ResolveNativeMinionOwnerActor(owner_participant_id);
    if (!multiplayer::IsLocalTransportHost() ||
        owner_participant_id == 0 ||
        owner_actor == 0) {
        original(self);
        return;
    }

    ScopedAuthoritativeNativeMinionOwner owner_scope(
        owner_participant_id);
    ScopedGameplayPlayerActorSlotContext player_context(
        owner_actor,
        true);
    ScopedActorSlotZeroContext actor_context(
        actor_address,
        true);
    if (!player_context.ready ||
        !actor_context.ready) {
        return;
    }
    original(self);

    if (!pending_before &&
        ReadActorRetirementPendingForNativeMinion(actor_address)) {
        multiplayer::NotifyLocalNativeMinionTerminal(
            actor_address,
            static_cast<multiplayer::NativeMinionTerminalReason>(
                natural_terminal_reason));
    }
}

void __fastcall HookGoodImpTick(
    void* self,
    void* /*unused_edx*/) {
    RunNativeMinionTick(
        self,
        g_gameplay_keyboard_injection.good_imp_tick_hook,
        NativeMinionTerminalReason::Expired);
}

void __fastcall HookLeviathanTick(
    void* self,
    void* /*unused_edx*/) {
    RunNativeMinionTick(
        self,
        g_gameplay_keyboard_injection.leviathan_tick_hook,
        NativeMinionTerminalReason::Expired);
}

void __fastcall HookGolemTick(
    void* self,
    void* /*unused_edx*/) {
    RunNativeMinionTick(
        self,
        g_gameplay_keyboard_injection.golem_tick_hook,
        NativeMinionTerminalReason::NativeDeath);
}

void __fastcall HookGolemDeath(
    void* self,
    void* /*unused_edx*/) {
    const auto original =
        GetX86HookTrampoline<NativeMinionTickFn>(
            g_gameplay_keyboard_injection.golem_death_hook);
    if (original == nullptr || self == nullptr) {
        return;
    }

    const auto actor_address =
        reinterpret_cast<uintptr_t>(self);
    if (multiplayer::IsLocalTransportHost()) {
        multiplayer::NotifyLocalNativeMinionTerminal(
            actor_address,
            CurrentGolemTerminalReason());
    }
    original(self);
}

std::uint32_t __fastcall HookGolemContact(
    void* self,
    void* /*unused_edx*/) {
    const auto original =
        GetX86HookTrampoline<NativeMinionContactFn>(
            g_gameplay_keyboard_injection.golem_contact_hook);
    if (original == nullptr || self == nullptr) {
        return 0;
    }
    if (multiplayer::IsLocalTransportClient()) {
        ResetActiveDamageContext();
        return 0;
    }

    const auto actor_address =
        reinterpret_cast<uintptr_t>(self);
    const auto owner_participant_id =
        ResolveNativeMinionOwnerParticipantId(
            actor_address);
    const auto owner_actor =
        ResolveNativeMinionOwnerActor(
            owner_participant_id);
    std::uint32_t result = 0;
    if (multiplayer::IsLocalTransportHost() &&
        owner_participant_id != 0 &&
        owner_actor != 0) {
        ScopedGameplayPlayerActorSlotContext player_context(
            owner_actor,
            true);
        ScopedActorSlotZeroContext actor_context(
            actor_address,
            true);
        if (player_context.ready &&
            actor_context.ready) {
            result = original(self);
        }
    } else {
        result = original(self);
    }
    float hp = 0.0f;
    if (multiplayer::IsLocalTransportHost() &&
        kGolemHpOffset != 0 &&
        ProcessMemory::Instance().TryReadField(
            actor_address,
            kGolemHpOffset,
            &hp) &&
        std::isfinite(hp) &&
        hp <= 0.0f) {
        multiplayer::NotifyLocalNativeMinionTerminal(
            actor_address,
            CurrentGolemTerminalReason());
    }
    return result;
}

uintptr_t __fastcall HookGameObjectFactoryForNativeMinions(
    void* self,
    void* /*unused_edx*/,
    int type_id) {
    const auto original =
        GetX86HookTrampoline<GameObjectFactoryFn>(
            g_gameplay_keyboard_injection
                .native_minion_game_object_factory_hook);
    if (original == nullptr) {
        return 0;
    }
    const auto actor_address = original(self, type_id);
    if (actor_address == 0) {
        return 0;
    }
    if (FindNativeMinionDescriptor(
            static_cast<std::uint32_t>(type_id)) != nullptr &&
        g_native_minion_creation_owner_participant_id != 0) {
        RememberNativeMinionOwner(
            actor_address,
            g_native_minion_creation_owner_participant_id);
        Log(
            "Tagged native minion at factory creation. actor=" +
            HexString(actor_address) +
            " type=" + std::to_string(type_id) +
            " owner=" +
            std::to_string(
                g_native_minion_creation_owner_participant_id));
    }
    if (type_id == static_cast<int>(
            kGolemKnockbackNativeTypeId) &&
        g_authoritative_native_minion_tick_owner != 0) {
        std::lock_guard<std::recursive_mutex> lock(
            g_native_minion_state_mutex);
        g_native_minion_knockback_owner_by_actor[
            actor_address] =
            g_authoritative_native_minion_tick_owner;
    }
    return actor_address;
}

void __fastcall HookKnockbackTick(
    void* self,
    void* /*unused_edx*/) {
    const auto original =
        GetX86HookTrampoline<NativeMinionTickFn>(
            g_gameplay_keyboard_injection.knockback_tick_hook);
    if (original == nullptr || self == nullptr) {
        return;
    }

    std::uint64_t owner_participant_id = 0;
    {
        std::lock_guard<std::recursive_mutex> lock(
            g_native_minion_state_mutex);
        const auto found =
            g_native_minion_knockback_owner_by_actor.find(
                reinterpret_cast<uintptr_t>(self));
        if (found !=
            g_native_minion_knockback_owner_by_actor.end()) {
            owner_participant_id = found->second;
        }
    }
    if (!multiplayer::IsLocalTransportHost() ||
        owner_participant_id == 0) {
        original(self);
        return;
    }

    const auto owner_actor =
        ResolveNativeMinionOwnerActor(owner_participant_id);
    if (owner_actor == 0) {
        original(self);
        return;
    }
    ScopedGameplayPlayerActorSlotContext player_context(
        owner_actor,
        true);
    ScopedActorSlotZeroContext actor_context(
        reinterpret_cast<uintptr_t>(self),
        true);
    if (player_context.ready &&
        actor_context.ready) {
        original(self);
    }
}

bool TryCaptureGolemNativeMinionState(
    uintptr_t actor_address,
    SDModNativeMinionState* state) {
    auto& memory = ProcessMemory::Instance();
    std::int8_t target_group = -1;
    std::int16_t target_slot = -1;
    std::int32_t gait_primary = 0;
    std::int32_t gait_secondary = 0;
    std::int32_t target_refresh_timer = 0;
    std::int32_t locomotion_sample_counter = 0;
    std::int32_t ambient_effect_timer = 0;
    std::int32_t iron = 0;
    if (!memory.TryReadField(
            actor_address,
            kGolemHpOffset,
            &state->hp) ||
        !memory.TryReadField(
            actor_address,
            kGolemMaxHpOffset,
            &state->max_hp) ||
        !memory.TryReadField(
            actor_address,
            kActorSpellTargetGroupByteOffset,
            &target_group) ||
        !memory.TryReadField(
            actor_address,
            kActorSpellTargetSlotShortOffset,
            &target_slot) ||
        !memory.TryReadField(
            actor_address,
            kGolemNativeAgeOffset,
            &state->native_age) ||
        !memory.TryReadField(
            actor_address,
            kGolemAttackTimerOffset,
            &state->attack_timer) ||
        !memory.TryReadField(
            actor_address,
            kGolemAttackCooldownOffset,
            &state->attack_cooldown) ||
        !memory.TryReadField(
            actor_address,
            kGolemGaitPrimaryOffset,
            &gait_primary) ||
        !memory.TryReadField(
            actor_address,
            kGolemGaitSecondaryOffset,
            &gait_secondary) ||
        !memory.TryReadField(
            actor_address,
            kGolemTargetRefreshTimerOffset,
            &target_refresh_timer) ||
        !memory.TryReadField(
            actor_address,
            kGolemLocomotionSampleCounterOffset,
            &locomotion_sample_counter) ||
        !memory.TryReadField(
            actor_address,
            kGolemAmbientEffectTimerOffset,
            &ambient_effect_timer) ||
        !memory.TryReadField(
            actor_address,
            kGolemAnimationPhaseOffset,
            &state->animation_phase) ||
        !memory.TryReadField(
            actor_address,
            kGolemIronOffset,
            &iron) ||
        !memory.TryReadField(
            actor_address,
            kGolemSteeringHeadingOffset,
            &state->steering_heading) ||
        !memory.TryReadField(
            actor_address,
            kGolemSteeringStepOffset,
            &state->steering_step) ||
        !memory.TryReadField(
            actor_address,
            kGolemDamagePrimaryOffset,
            &state->damage_primary) ||
        !memory.TryReadField(
            actor_address,
            kGolemDamageSecondaryOffset,
            &state->damage_secondary) ||
        !memory.TryReadField(
            actor_address,
            kGolemReflectRatioOffset,
            &state->reflect_ratio)) {
        return false;
    }
    state->target_actor_group =
        static_cast<std::int32_t>(target_group);
    state->target_world_slot =
        static_cast<std::int32_t>(target_slot);
    state->gait_primary =
        static_cast<std::uint32_t>((std::max)(gait_primary, 0));
    state->gait_secondary =
        static_cast<std::uint32_t>((std::max)(gait_secondary, 0));
    state->target_refresh_timer =
        (std::max)(target_refresh_timer, 0);
    state->locomotion_sample_counter =
        static_cast<std::uint32_t>(
            (std::max)(locomotion_sample_counter, 0));
    state->ambient_effect_timer =
        static_cast<std::uint32_t>(
            (std::max)(ambient_effect_timer, 0));
    state->iron =
        static_cast<std::uint32_t>((std::max)(iron, 0));
    state->state_flags |=
        multiplayer::NativeMinionStateFlagDamageable;
    return std::isfinite(state->hp) &&
        std::isfinite(state->max_hp) &&
        state->max_hp > 0.0f &&
        std::isfinite(state->animation_phase) &&
        std::isfinite(state->steering_heading) &&
        std::isfinite(state->steering_step) &&
        std::isfinite(state->damage_primary) &&
        std::isfinite(state->damage_secondary) &&
        std::isfinite(state->reflect_ratio);
}
