namespace {

constexpr std::uint32_t kDebugSpawnOrbRewardNativeTypeId = 0x07DB;
constexpr std::size_t kDebugSpawnOrbResourceKindOffset = 0x13C;
constexpr std::size_t kDebugSpawnOrbValueOffset = 0x140;
constexpr std::size_t kDebugSpawnOrbLifetimeOffset = 0x144;
constexpr std::size_t kDebugSpawnOrbMotionOffset = 0x148;
constexpr std::size_t kDebugSpawnOrbProgressOffset = 0x14C;
constexpr std::uint32_t kDebugSpawnRewardLifetime = 900;

bool CallRewardWorldAttachSafe(
    uintptr_t actor_world_attach_address,
    uintptr_t world_address,
    uintptr_t actor_address,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    auto* actor_world_attach = reinterpret_cast<ActorWorldAttachFn>(actor_world_attach_address);
    if (actor_world_attach == nullptr || world_address == 0 || actor_address == 0) {
        return false;
    }

    __try {
        actor_world_attach(reinterpret_cast<void*>(world_address), reinterpret_cast<void*>(actor_address));
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallOrbRewardInitializeSafe(
    uintptr_t initializer_address,
    uintptr_t actor_address,
    uintptr_t rng_state_address,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    auto* initialize = reinterpret_cast<OrbRewardInitializeFn>(initializer_address);
    if (initialize == nullptr || actor_address == 0 || rng_state_address == 0) {
        return false;
    }

    __try {
        initialize(reinterpret_cast<void*>(actor_address), reinterpret_cast<void*>(rng_state_address));
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool ExecuteSpawnOrbRewardNow(
    std::string_view kind,
    int amount,
    float x,
    float y,
    std::string* error_message) {
    const bool is_health_orb = kind == "health_orb" || kind == "hp_orb" || kind == "life_orb";
    const bool is_mana_orb = kind == "mana_orb" || kind == "mp_orb";
    if (!is_health_orb && !is_mana_orb) {
        return false;
    }

    SDModPlayerState player_state;
    if (!TryGetPlayerState(&player_state) ||
        !player_state.valid ||
        player_state.world_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Current player world is not active.";
        }
        return true;
    }

    auto& memory = ProcessMemory::Instance();
    const auto factory_address = memory.ResolveGameAddressOrZero(kGameObjectFactory);
    const auto factory_context_address = memory.ResolveGameAddressOrZero(kGameObjectFactoryContextGlobal);
    const auto initializer_address = memory.ResolveGameAddressOrZero(kOrbRewardInitialize);
    if (factory_address == 0 || factory_context_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Orb reward factory entrypoint is unavailable.";
        }
        return true;
    }

    uintptr_t actor_address = 0;
    DWORD exception_code = 0;
    if (!CallGameObjectFactorySafe(
            factory_address,
            factory_context_address,
            static_cast<int>(kDebugSpawnOrbRewardNativeTypeId),
            &actor_address,
            &exception_code) ||
        actor_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Orb reward factory failed with 0x" + HexString(exception_code) + ".";
        }
        return true;
    }

    uintptr_t rng_state_address = 0;
    if (!TryResolveNativeGlobalRngState(nullptr, &rng_state_address) ||
        initializer_address == 0 ||
        !CallOrbRewardInitializeSafe(initializer_address, actor_address, rng_state_address, &exception_code)) {
        const auto object_delete_address = memory.ResolveGameAddressOrZero(kObjectDelete);
        DWORD delete_exception_code = 0;
        if (object_delete_address != 0) {
            (void)CallObjectDeleteSafe(object_delete_address, actor_address, &delete_exception_code);
        }
        if (error_message != nullptr) {
            *error_message =
                "Orb reward initializer failed with 0x" + HexString(exception_code) +
                " actor=" + HexString(actor_address) +
                " rng_state=" + HexString(rng_state_address) +
                " delete_seh=" + HexString(delete_exception_code);
        }
        return true;
    }

    const std::uint8_t resource_kind = is_health_orb ? 0 : 1;
    const float raw_value = static_cast<float>((std::max)(amount, 1));
    const float zero_motion = 0.0f;
    const bool seeded =
        memory.TryWriteField(actor_address, kActorPositionXOffset, x) &&
        memory.TryWriteField(actor_address, kActorPositionYOffset, y) &&
        memory.TryWriteField(actor_address, kDebugSpawnOrbResourceKindOffset, resource_kind) &&
        memory.TryWriteField(actor_address, kDebugSpawnOrbValueOffset, raw_value) &&
        memory.TryWriteField(actor_address, kDebugSpawnOrbLifetimeOffset, kDebugSpawnRewardLifetime) &&
        memory.TryWriteField(actor_address, kDebugSpawnOrbMotionOffset, zero_motion) &&
        memory.TryWriteField(actor_address, kDebugSpawnOrbProgressOffset, zero_motion);
    if (!seeded) {
        const auto object_delete_address = memory.ResolveGameAddressOrZero(kObjectDelete);
        DWORD delete_exception_code = 0;
        if (object_delete_address != 0) {
            (void)CallObjectDeleteSafe(object_delete_address, actor_address, &delete_exception_code);
        }
        if (error_message != nullptr) {
            *error_message =
                "Orb reward field seeding failed for actor=" + HexString(actor_address) +
                " delete_seh=" + HexString(delete_exception_code);
        }
        return true;
    }

    exception_code = 0;
    const auto actor_world_attach_address = memory.ResolveGameAddressOrZero(kActorWorldAttach);
    if (!CallRewardWorldAttachSafe(
            actor_world_attach_address,
            player_state.world_address,
            actor_address,
            &exception_code)) {
        const auto object_delete_address = memory.ResolveGameAddressOrZero(kObjectDelete);
        DWORD delete_exception_code = 0;
        if (object_delete_address != 0) {
            (void)CallObjectDeleteSafe(object_delete_address, actor_address, &delete_exception_code);
        }
        if (error_message != nullptr) {
            *error_message =
                "Orb reward world attach failed with 0x" + HexString(exception_code) +
                " actor=" + HexString(actor_address) +
                " delete_seh=" + HexString(delete_exception_code);
        }
        return true;
    }

    return true;
}

}  // namespace

bool ExecuteSpawnRewardNow(std::string_view kind, int amount, float x, float y, std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (ExecuteSpawnOrbRewardNow(kind, amount, x, y, error_message)) {
        return error_message == nullptr || error_message->empty();
    }
    if (kind != "gold") {
        if (error_message != nullptr) {
            *error_message = "Only gold and health_orb/mana_orb rewards are supported right now.";
        }
        return false;
    }

    uintptr_t arena_address = 0;
    if (!TryResolveArena(&arena_address) || arena_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Arena is not active.";
        }
        return false;
    }

    const auto spawn_reward_address = ProcessMemory::Instance().ResolveGameAddressOrZero(kSpawnRewardGold);
    if (spawn_reward_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the gold reward spawn function.";
        }
        return false;
    }

    auto spawn_reward = reinterpret_cast<SpawnRewardGoldFn>(spawn_reward_address);
    spawn_reward(
        reinterpret_cast<void*>(arena_address),
        FloatToBits(x),
        FloatToBits(y),
        amount,
        kSpawnRewardDefaultLifetime);
    return true;
}
