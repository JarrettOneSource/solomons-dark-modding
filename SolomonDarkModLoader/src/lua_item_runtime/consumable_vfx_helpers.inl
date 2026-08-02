// Included by lua_item_runtime.cpp inside its anonymous namespace.

int CaptureNativeVfxSehCode(
    EXCEPTION_POINTERS* exception_pointers,
    DWORD* exception_code) {
    if (exception_code != nullptr && exception_pointers != nullptr &&
        exception_pointers->ExceptionRecord != nullptr) {
        *exception_code =
            exception_pointers->ExceptionRecord->ExceptionCode;
    }
    return EXCEPTION_EXECUTE_HANDLER;
}

using ObjectAllocateFn = void*(__cdecl*)(std::size_t);
using SpellGlowCtorFn = void*(__thiscall*)(void*);
using RegisterAnimationFn =
    void(__thiscall*)(void* world, void* animation, float layer);

constexpr float kSpellGlowAnimationLayer = 75.0f;
constexpr std::uint64_t kSpellGlowPulseIntervalMs = 16;
constexpr std::uint64_t kSpellGlowPulseDurationMs = 4000;

struct ConsumableVfxTarget {
    uintptr_t actor_address = 0;
    uintptr_t world_address = 0;
    float x = 0.0f;
    float y = 0.0f;
};

bool TryResolveConsumableVfxTarget(
    std::uint64_t participant_id,
    ConsumableVfxTarget* target) {
    if (target == nullptr || participant_id == 0) {
        return false;
    }
    *target = ConsumableVfxTarget{};

    const auto transport_participant_id =
        multiplayer::GetLocalTransportParticipantId();
    const auto local_participant_id = transport_participant_id != 0
        ? transport_participant_id
        : multiplayer::kLocalParticipantId;
    if (participant_id == local_participant_id) {
        SDModPlayerState player;
        if (!TryGetPlayerState(&player) ||
            !player.valid ||
            player.actor_address == 0 ||
            player.world_address == 0) {
            return false;
        }
        target->actor_address = player.actor_address;
        target->world_address = player.world_address;
        target->x = player.x;
        target->y = player.y;
        return true;
    }

    SDModParticipantGameplayState participant;
    if (!TryGetParticipantGameplayState(participant_id, &participant) ||
        !participant.available ||
        !participant.entity_materialized ||
        participant.actor_address == 0) {
        return false;
    }
    target->actor_address = participant.actor_address;
    target->world_address = participant.world_address;
    target->x = participant.x;
    target->y = participant.y;
    return true;
}

bool ConstructSpellGlowSafe(
    uintptr_t allocate_address,
    uintptr_t constructor_address,
    void** allocation,
    void** glow,
    DWORD* exception_code) {
    if (allocation != nullptr) {
        *allocation = nullptr;
    }
    if (glow != nullptr) {
        *glow = nullptr;
    }
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (allocation == nullptr || glow == nullptr ||
        allocate_address == 0 || constructor_address == 0) {
        return false;
    }
    auto* allocate =
        reinterpret_cast<ObjectAllocateFn>(allocate_address);
    auto* constructor =
        reinterpret_cast<SpellGlowCtorFn>(constructor_address);
    __try {
        *allocation = allocate(0x38);
        if (*allocation != nullptr) {
            *glow = constructor(*allocation);
        }
        return *glow != nullptr;
    } __except (
        CaptureNativeVfxSehCode(
            GetExceptionInformation(),
            exception_code)) {
        return false;
    }
}

bool RegisterSpellGlowSafe(
    uintptr_t register_address,
    uintptr_t world_address,
    void* glow,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (register_address == 0 ||
        world_address == 0 ||
        glow == nullptr) {
        return false;
    }
    auto* register_animation =
        reinterpret_cast<RegisterAnimationFn>(register_address);
    __try {
        register_animation(
            reinterpret_cast<void*>(world_address),
            glow,
            kSpellGlowAnimationLayer);
        return true;
    } __except (
        CaptureNativeVfxSehCode(
            GetExceptionInformation(),
            exception_code)) {
        return false;
    }
}

bool SpawnSpellGlowForParticipant(
    const LuaConsumableDefinition& definition,
    std::uint64_t participant_id,
    std::uint64_t use_id,
    std::string* error_message) {
    ConsumableVfxTarget target;
    if (!TryResolveConsumableVfxTarget(participant_id, &target)) {
        SetError(
            error_message,
            "participant actor is not materialized");
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t world_address = target.world_address;
    if (world_address == 0 &&
        (kActorOwnerOffset == 0 ||
         !memory.TryReadField(
             target.actor_address,
             kActorOwnerOffset,
             &world_address))) {
        SetError(error_message, "participant world is unavailable");
        return false;
    }

    const auto allocate_address =
        memory.ResolveGameAddressOrZero(kObjectAllocate);
    const auto free_address =
        memory.ResolveGameAddressOrZero(kObjectFree);
    const auto constructor_address =
        memory.ResolveGameAddressOrZero(kSpellGlowCtor);
    const auto register_address =
        memory.ResolveGameAddressOrZero(kActorWorldRegisterAnimation);
    if (allocate_address == 0 || constructor_address == 0 ||
        register_address == 0 || world_address == 0) {
        SetError(error_message, "SpellGlow native seams are unavailable");
        return false;
    }

    using ObjectFreeFn = void(__cdecl*)(void*);
    auto* object_free = reinterpret_cast<ObjectFreeFn>(free_address);

    void* allocation = nullptr;
    void* glow = nullptr;
    DWORD exception_code = 0;
    if (!ConstructSpellGlowSafe(
            allocate_address,
            constructor_address,
            &allocation,
            &glow,
            &exception_code)) {
        if (allocation != nullptr && object_free != nullptr) {
            object_free(allocation);
        }
        SetError(
            error_message,
            "SpellGlow allocation or construction failed with 0x" +
                HexString(static_cast<uintptr_t>(exception_code)));
        return false;
    }

    const uintptr_t glow_address = reinterpret_cast<uintptr_t>(glow);
    const float phase =
        0.8f +
        static_cast<float>((use_id ^ (use_id >> 32)) & 0xFFu) /
            255.0f * 0.4f;
    const std::uint32_t selector = 0x18;
    if (!memory.TryWriteField(
            glow_address,
            0x14,
            target.x) ||
        !memory.TryWriteField(
            glow_address,
            0x18,
            target.y) ||
        !memory.TryWriteField(glow_address, 0x1C, phase) ||
        !memory.TryWriteField(glow_address, 0x20, phase) ||
        !memory.TryWriteField(glow_address, 0x24, selector) ||
        !memory.TryWriteField(
            glow_address,
            0x28,
            definition.consume_vfx_color[0]) ||
        !memory.TryWriteField(
            glow_address,
            0x2C,
            definition.consume_vfx_color[1]) ||
        !memory.TryWriteField(
            glow_address,
            0x30,
            definition.consume_vfx_color[2]) ||
        !memory.TryWriteField(
            glow_address,
            0x34,
            definition.consume_vfx_color[3])) {
        if (object_free != nullptr) {
            object_free(glow);
        }
        SetError(error_message, "SpellGlow state write failed");
        return false;
    }

    exception_code = 0;
    if (!RegisterSpellGlowSafe(
            register_address,
            world_address,
            glow,
            &exception_code)) {
        if (object_free != nullptr) {
            object_free(glow);
        }
        SetError(
            error_message,
            "SpellGlow registration failed with 0x" +
                HexString(static_cast<uintptr_t>(exception_code)));
        return false;
    }
    return true;
}
