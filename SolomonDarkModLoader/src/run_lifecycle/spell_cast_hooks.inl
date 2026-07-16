bool IsLocalPlayerActorForRunLifecycle(uintptr_t actor_address) {
    if (actor_address == 0) {
        return false;
    }

    const auto local_actor_address = ResolveLocalPlayerActorForRunLifecycle();
    return local_actor_address != 0 && local_actor_address == actor_address;
}

void DispatchSpellCastForSelf(uintptr_t self_address, int spell_id) {
    if (self_address == 0 || spell_id <= 0 || !IsRunActive()) {
        return;
    }
    if (!IsLocalPlayerActorForRunLifecycle(self_address)) {
        return;
    }

    const auto click_serial = GetGameplayMouseLeftEdgeSerial();
    const auto click_tick_ms = GetGameplayMouseLeftEdgeTickMs();
    const auto now = static_cast<std::uint64_t>(GetTickCount64());
    if (click_serial == 0 ||
        click_tick_ms == 0 ||
        now < click_tick_ms ||
        now - click_tick_ms > kSpellCastClickWindowMs) {
        return;
    }

    const auto last_consumed_click_serial =
        g_state.last_consumed_spell_click_serial.load(std::memory_order_acquire);
    if (last_consumed_click_serial == click_serial) {
        return;
    }

    float x = 0.0f;
    float y = 0.0f;
    float direction_x = 0.0f;
    float direction_y = 0.0f;
    if (!TryReadActorPosition(self_address, &x, &y) ||
        !TryReadFloatField(self_address, kSpellDirectionXOffset, &direction_x) ||
        !TryReadFloatField(self_address, kSpellDirectionYOffset, &direction_y)) {
        Log(
            "spell.cast native event fields unavailable. spell_id=" + std::to_string(spell_id) +
            " actor=" + HexString(self_address));
        return;
    }
    g_state.last_consumed_spell_click_serial.store(click_serial, std::memory_order_release);

    uintptr_t target_actor_address = 0;
    (void)ProcessMemory::Instance().TryReadField(
        self_address,
        kActorCurrentTargetActorOffset,
        &target_actor_address);
    float aim_target_x = 0.0f;
    float aim_target_y = 0.0f;
    const bool has_aim_target =
        TryReadFloatField(self_address, kActorAimTargetXOffset, &aim_target_x) &&
        TryReadFloatField(self_address, kActorAimTargetYOffset, &aim_target_y) &&
        std::isfinite(aim_target_x) &&
        std::isfinite(aim_target_y);

    Log(
        "spell.cast hook invoked. spell_id=" + std::to_string(spell_id) +
        " pos=(" + std::to_string(x) + "," + std::to_string(y) + ")" +
        " dir=(" + std::to_string(direction_x) + "," + std::to_string(direction_y) + ")" +
        " aim_target=" +
            (has_aim_target
                ? (std::to_string(aim_target_x) + "," + std::to_string(aim_target_y))
                : std::string("<none>")) +
        " target=" + HexString(target_actor_address) +
        " run_active=" + std::to_string(IsRunActive() ? 1 : 0));
    multiplayer::QueueLocalSpellCastEvent(
        spell_id,
        x,
        y,
        direction_x,
        direction_y,
        0,
        target_actor_address,
        0,
        has_aim_target,
        aim_target_x,
        aim_target_y);
    DispatchLuaSpellCast(spell_id, x, y, direction_x, direction_y);
}

bool TryReadSpellCastHookSkillId(uintptr_t self_address, int* spell_id) {
    if (spell_id == nullptr) {
        return false;
    }

    *spell_id = 0;
    if (self_address == 0 || kActorPrimarySkillIdOffset == 0) {
        return false;
    }
    auto& memory = ProcessMemory::Instance();
    if (!memory.IsReadableRange(self_address + kActorPrimarySkillIdOffset, sizeof(std::int32_t))) {
        return false;
    }
    return memory.TryReadField(self_address, kActorPrimarySkillIdOffset, spell_id);
}

struct AirLightningDispatchContext {
    bool active = false;
    bool local_owner = false;
    bool truncated = false;
    uintptr_t caster_actor_address = 0;
    std::uint64_t owner_participant_id = 0;
    std::uint16_t next_target_ordinal = 0;
    std::size_t target_count = 0;
    std::array<multiplayer::AirChainTargetCapture, multiplayer::kAirChainSnapshotMaxTargets>
        targets{};
    struct TargetPositionOverride {
        uintptr_t actor_address = 0;
        float original_x = 0.0f;
        float original_y = 0.0f;
    };
    std::size_t target_position_override_count = 0;
    std::array<TargetPositionOverride, multiplayer::kAirChainSnapshotMaxTargets>
        target_position_overrides{};
};

thread_local AirLightningDispatchContext g_air_lightning_dispatch_context;

bool TryGetReplicatedParticipantForAirChain(
    uintptr_t actor_address,
    std::uint64_t* participant_id_out) {
    if (participant_id_out != nullptr) {
        *participant_id_out = 0;
    }
    std::string display_name;
    std::uint64_t participant_id = 0;
    const bool found = actor_address != 0 &&
        TryGetGameplayHudParticipantDisplayNameForActor(
            actor_address,
            &display_name,
            &participant_id) &&
        participant_id != 0 &&
        participant_id != multiplayer::GetLocalTransportParticipantId();
    if (found && participant_id_out != nullptr) {
        *participant_id_out = participant_id;
    }
    return found;
}

void RestoreAirChainTargetPositionOverrides(
    AirLightningDispatchContext* context) {
    if (context == nullptr || context->target_position_override_count == 0) {
        return;
    }
    auto& memory = ProcessMemory::Instance();
    for (std::size_t index = 0;
         index < context->target_position_override_count;
         ++index) {
        const auto& position = context->target_position_overrides[index];
        if (position.actor_address == 0) {
            continue;
        }
        (void)memory.TryWriteField(
            position.actor_address,
            kActorPositionXOffset,
            position.original_x);
        (void)memory.TryWriteField(
            position.actor_address,
            kActorPositionYOffset,
            position.original_y);
    }
    context->target_position_override_count = 0;
}

bool ApplyAuthoritativeAirChainTargetEndpointForNativeCopy(
    AirLightningDispatchContext* context,
    uintptr_t target_actor_address,
    const multiplayer::AirChainTargetEndpoint& authoritative_target) {
    if (context == nullptr ||
        target_actor_address == 0 ||
        !authoritative_target.valid ||
        !std::isfinite(authoritative_target.x) ||
        !std::isfinite(authoritative_target.y) ||
        context->target_position_override_count >=
            context->target_position_overrides.size()) {
        return false;
    }

    float original_x = 0.0f;
    float original_y = 0.0f;
    if (!TryReadActorPosition(
            target_actor_address,
            &original_x,
            &original_y)) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const bool wrote_x = memory.TryWriteField(
        target_actor_address,
        kActorPositionXOffset,
        authoritative_target.x);
    const bool wrote_y = wrote_x && memory.TryWriteField(
        target_actor_address,
        kActorPositionYOffset,
        authoritative_target.y);
    if (!wrote_y) {
        if (wrote_x) {
            (void)memory.TryWriteField(
                target_actor_address,
                kActorPositionXOffset,
                original_x);
        }
        return false;
    }

    auto& position = context->target_position_overrides[
        context->target_position_override_count++];
    position.actor_address = target_actor_address;
    position.original_x = original_x;
    position.original_y = original_y;
    return true;
}

bool ApplyAuthoritativeAirChainSourceEndpointToNativeCaller(
    const multiplayer::AirChainSourceEndpoint& authoritative_source,
    float observed_source_x,
    float observed_source_y,
    uintptr_t actual_return_address,
    uintptr_t return_slot_address) {
    if (!authoritative_source.valid ||
        !std::isfinite(authoritative_source.x) ||
        !std::isfinite(authoritative_source.y) ||
        !std::isfinite(observed_source_x) ||
        !std::isfinite(observed_source_y) ||
        kAirLightningChainSourceFromReturnSlotOffset == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto expected_return_address =
        memory.ResolveGameAddressOrZero(kAirLightningChainTargetReturn);
    if (expected_return_address == 0 ||
        actual_return_address != expected_return_address) {
        return false;
    }

    // SpellCast_018 copies its current bolt endpoint into the five-argument
    // nearest-target call at 0x005403AA. The same Vec2 remains in the caller's
    // frame and is consumed by the stock arc builder after return. Validate
    // that binary-specific stack contract against the arguments received by
    // this hook before replacing the caller-owned endpoint.
    const auto caller_source_address =
        return_slot_address + kAirLightningChainSourceFromReturnSlotOffset;
    float caller_source_x = 0.0f;
    float caller_source_y = 0.0f;
    constexpr float kCallerSourceContractEpsilon = 0.01f;
    if (!memory.TryReadValue(caller_source_address, &caller_source_x) ||
        !memory.TryReadValue(
            caller_source_address + sizeof(float),
            &caller_source_y) ||
        !std::isfinite(caller_source_x) ||
        !std::isfinite(caller_source_y) ||
        std::abs(caller_source_x - observed_source_x) >
            kCallerSourceContractEpsilon ||
        std::abs(caller_source_y - observed_source_y) >
            kCallerSourceContractEpsilon) {
        return false;
    }

    return memory.TryWriteValue(
               caller_source_address,
               authoritative_source.x) &&
           memory.TryWriteValue(
               caller_source_address + sizeof(float),
               authoritative_source.y);
}

void* __fastcall HookAirLightningChainTarget(
    void* self,
    void* unused_edx,
    float source_x,
    float source_y,
    float radius,
    std::uint32_t mask,
    void* exclusions) {
    (void)unused_edx;
    const auto original = GetX86HookTrampoline<AirLightningChainTargetFn>(
        g_state.hooks[kHookAirLightningChainTarget]);
    if (original == nullptr) {
        return nullptr;
    }

    auto& context = g_air_lightning_dispatch_context;
    if (context.active && !context.local_owner) {
        // The previous return has already copied its endpoint into the stock
        // caller frame. Restore the actor before native target selection runs
        // again so world authority and selection geometry remain untouched.
        RestoreAirChainTargetPositionOverrides(&context);
    }

    const auto native_caller_return_address =
        reinterpret_cast<uintptr_t>(_ReturnAddress());
    const auto native_caller_return_slot_address =
        reinterpret_cast<uintptr_t>(_AddressOfReturnAddress());

    void* native_result = original(
        self,
        source_x,
        source_y,
        radius,
        mask,
        exclusions);
    if (!context.active) {
        return native_result;
    }

    const auto ordinal = context.next_target_ordinal++;
    if (!context.local_owner) {
        multiplayer::AirChainSourceEndpoint authoritative_source;
        multiplayer::AirChainTargetEndpoint authoritative_target;
        const auto resolved_target =
            multiplayer::ResolveReplicatedAirChainTarget(
                context.caster_actor_address,
                context.owner_participant_id,
                ordinal,
                reinterpret_cast<uintptr_t>(native_result),
                source_x,
                source_y,
                &authoritative_source,
                &authoritative_target);
        const bool source_endpoint_applied =
            resolved_target != 0 &&
            ApplyAuthoritativeAirChainSourceEndpointToNativeCaller(
                authoritative_source,
                source_x,
                source_y,
                native_caller_return_address,
                native_caller_return_slot_address);
        if (authoritative_source.valid) {
            multiplayer::RecordReplicatedAirChainSourceOverride(
                context.owner_participant_id,
                ordinal,
                source_endpoint_applied);
        }
        const bool target_endpoint_applied =
            resolved_target != 0 &&
            ApplyAuthoritativeAirChainTargetEndpointForNativeCopy(
                &context,
                resolved_target,
                authoritative_target);
        if (authoritative_target.valid) {
            multiplayer::RecordReplicatedAirChainTargetOverride(
                context.owner_participant_id,
                ordinal,
                target_endpoint_applied);
        }
        return reinterpret_cast<void*>(resolved_target);
    }

    if (context.target_count >= context.targets.size()) {
        context.truncated = true;
        return native_result;
    }

    auto& target = context.targets[context.target_count++];
    target.actor_address = reinterpret_cast<uintptr_t>(native_result);
    target.network_actor_id =
        multiplayer::GetLocalRunEnemyNetworkActorId(target.actor_address);
    target.source_x = source_x;
    target.source_y = source_y;
    if (target.actor_address == 0 ||
        !TryReadActorPosition(target.actor_address, &target.target_x, &target.target_y)) {
        target.target_x = 0.0f;
        target.target_y = 0.0f;
    }
    return native_result;
}

#define SDMOD_DEFINE_SPELL_CAST_HOOK(name, hook_index)                              \
    void __fastcall HookSpellCast_##name(void* self, void* unused_edx) {             \
        const auto original = GetX86HookTrampoline<SpellCastFn>(g_state.hooks[hook_index]); \
        if (original == nullptr) {                                                   \
            return;                                                                  \
        }                                                                            \
        const auto self_address = reinterpret_cast<uintptr_t>(self);                 \
        int spell_id = 0;                                                           \
        const bool have_spell_id = TryReadSpellCastHookSkillId(self_address, &spell_id); \
        original(self, unused_edx);                                                  \
        if (have_spell_id) {                                                         \
            DispatchSpellCastForSelf(self_address, spell_id);                        \
        } else {                                                                     \
            Log("spell.cast native skill id unavailable. actor=" + HexString(self_address)); \
        }                                                                            \
    }

SDMOD_DEFINE_SPELL_CAST_HOOK(3EB, kHookSpellCast3EB)
SDMOD_DEFINE_SPELL_CAST_HOOK(020, kHookSpellCast020)
SDMOD_DEFINE_SPELL_CAST_HOOK(028, kHookSpellCast028)
SDMOD_DEFINE_SPELL_CAST_HOOK(3EC, kHookSpellCast3EC)
SDMOD_DEFINE_SPELL_CAST_HOOK(3ED, kHookSpellCast3ED)
SDMOD_DEFINE_SPELL_CAST_HOOK(3EE, kHookSpellCast3EE)
SDMOD_DEFINE_SPELL_CAST_HOOK(3F0, kHookSpellCast3F0)

void __fastcall HookSpellCast_018(void* self, void* unused_edx) {
    const auto original = GetX86HookTrampoline<SpellCastFn>(
        g_state.hooks[kHookSpellCast018]);
    if (original == nullptr) {
        return;
    }

    const auto self_address = reinterpret_cast<uintptr_t>(self);
    int spell_id = 0;
    const bool have_spell_id = TryReadSpellCastHookSkillId(self_address, &spell_id);

    // Scripted flat-boneyard casts have no real cursor hover to refresh the
    // actor's native target handle. Lightning consumes that handle at this
    // dispatcher entry, unlike projectile primaries which consume aim
    // coordinates later. This helper is inert during ordinary player input.
    if (IsLocalPlayerActorForRunLifecycle(self_address)) {
        (void)ApplyPinnedManualSpawnerPrimaryTarget(self_address);
    }

    const auto previous_context = g_air_lightning_dispatch_context;
    g_air_lightning_dispatch_context = AirLightningDispatchContext{};
    auto& context = g_air_lightning_dispatch_context;
    context.caster_actor_address = self_address;
    context.local_owner = IsLocalPlayerActorForRunLifecycle(self_address);
    context.active = context.local_owner ||
                     TryGetReplicatedParticipantForAirChain(
                         self_address,
                         &context.owner_participant_id);

    original(self, unused_edx);

    // The last chained target has no subsequent nearest-target call to restore
    // it. By this point stock code has copied every endpoint it needs.
    RestoreAirChainTargetPositionOverrides(&context);

    if (context.active && context.local_owner) {
        multiplayer::PublishLocalAirChainFrame(
            self_address,
            context.targets.data(),
            context.target_count,
            context.next_target_ordinal);
    }
    g_air_lightning_dispatch_context = previous_context;

    if (have_spell_id) {
        DispatchSpellCastForSelf(self_address, spell_id);
    } else {
        Log("spell.cast native skill id unavailable. actor=" + HexString(self_address));
    }
}

void __fastcall HookSpellCast_3EF(void* self, void* unused_edx) {
    const auto original = GetX86HookTrampoline<SpellCastFn>(g_state.hooks[kHookSpellCast3EF]);
    if (original == nullptr) {
        return;
    }

    const auto self_address = reinterpret_cast<uintptr_t>(self);
    int spell_id = 0;
    const bool have_spell_id = TryReadSpellCastHookSkillId(self_address, &spell_id);
    Log("[bots] spell_3ef hook enter. " + DescribeSpellCastHookActorState(self_address));
    original(self, unused_edx);
    Log("[bots] spell_3ef hook exit. " + DescribeSpellCastHookActorState(self_address));
    if (have_spell_id) {
        DispatchSpellCastForSelf(self_address, spell_id);
    } else {
        Log("spell.cast native skill id unavailable. actor=" + HexString(self_address));
    }
}

#undef SDMOD_DEFINE_SPELL_CAST_HOOK

// ---- Detour functions ----
