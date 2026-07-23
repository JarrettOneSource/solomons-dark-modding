namespace {

constexpr std::uint32_t kDebugSpawnOrbRewardNativeTypeId = 0x07DB;
constexpr std::uint32_t kDebugSpawnPowerupRewardNativeTypeId = 0x07F6;
constexpr std::uint32_t kDebugSpawnPotionItemTypeId = 0x1B59;
constexpr std::size_t kDebugSpawnPotionDropVfuncOffset = 0x148;
constexpr std::size_t kDebugSpawnOrbResourceKindOffset = 0x13C;
constexpr std::size_t kDebugSpawnOrbValueOffset = 0x140;
constexpr std::size_t kDebugSpawnOrbLifetimeOffset = 0x144;
constexpr std::size_t kDebugSpawnOrbMotionOffset = 0x148;
constexpr std::size_t kDebugSpawnOrbProgressOffset = 0x14C;
constexpr std::size_t kDebugSpawnPowerupKindOffset = 0x13C;
constexpr std::size_t kDebugSpawnPowerupLifetimeOffset = 0x154;
constexpr std::uint32_t kDebugSpawnRewardLifetime = 900;
constexpr std::uint32_t kDebugSpawnPowerupLifetime = 1200;

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

bool CallSpawnRewardGoldSafe(
    uintptr_t spawn_reward_address,
    uintptr_t arena_address,
    float x,
    float y,
    int amount,
    int lifetime,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    auto* spawn_reward = reinterpret_cast<SpawnRewardGoldFn>(spawn_reward_address);
    if (spawn_reward == nullptr || arena_address == 0) {
        return false;
    }

    __try {
        spawn_reward(
            reinterpret_cast<void*>(arena_address),
            FloatToBits(x),
            FloatToBits(y),
            amount,
            lifetime);
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool TryReadRewardSpawnVfunc(
    uintptr_t object_address,
    std::size_t vfunc_offset,
    uintptr_t* function_address) {
    if (function_address != nullptr) {
        *function_address = 0;
    }
    if (function_address == nullptr || object_address == 0) {
        return false;
    }

    uintptr_t vtable_address = 0;
    if (!ProcessMemory::Instance().TryReadValue(object_address, &vtable_address) ||
        vtable_address == 0) {
        return false;
    }

    return ProcessMemory::Instance().TryReadField(vtable_address, vfunc_offset, function_address) &&
           *function_address != 0;
}

bool CallDebugSpawnPotionDropSafe(
    uintptr_t function_address,
    uintptr_t arena_address,
    float x,
    float y,
    int potion_slot,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    auto* spawn_potion = reinterpret_cast<SpawnPotionDropFn>(function_address);
    if (spawn_potion == nullptr || arena_address == 0) {
        return false;
    }

    __try {
        spawn_potion(
            reinterpret_cast<void*>(arena_address),
            FloatToBits(x),
            FloatToBits(y),
            potion_slot);
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool ExecuteSpawnPotionRewardNow(
    std::string_view kind,
    int amount,
    float x,
    float y,
    std::string* error_message) {
    const bool is_lua_consumable = kind == "lua_consumable";
    const bool is_health_potion = kind == "health_potion" || kind == "life_potion" || kind == "potion0";
    const bool is_mana_potion = kind == "mana_potion" || kind == "mp_potion" || kind == "potion1" || kind == "potion";
    if (!is_lua_consumable && !is_health_potion && !is_mana_potion) {
        return false;
    }
    if (is_lua_consumable &&
        (amount < kLuaFirstConsumablePotionSubtype ||
         amount >= kLuaFirstConsumablePotionSubtype +
             static_cast<int>(kLuaMaximumRegisteredConsumables))) {
        if (error_message != nullptr) {
            *error_message = "Lua consumable potion subtype is outside the runtime range.";
        }
        return true;
    }

    uintptr_t arena_address = 0;
    if (!TryResolveArena(&arena_address) || arena_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Arena is not active.";
        }
        return true;
    }

    uintptr_t spawn_function_address = 0;
    if (!TryReadRewardSpawnVfunc(
            arena_address,
            kDebugSpawnPotionDropVfuncOffset,
            &spawn_function_address)) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the arena potion drop vfunc.";
        }
        return true;
    }

    int potion_slot = is_lua_consumable
        ? amount
        : (is_mana_potion ? 1 : 0);
    if (!is_lua_consumable && (amount == 0 || amount == 1)) {
        potion_slot = amount;
    }
    DWORD exception_code = 0;
    if (!CallDebugSpawnPotionDropSafe(
            spawn_function_address,
            arena_address,
            x,
            y,
            potion_slot,
            &exception_code)) {
        if (error_message != nullptr) {
            *error_message =
                "Potion reward spawn failed with 0x" +
                HexString(static_cast<uintptr_t>(exception_code)) +
                " arena=" + HexString(arena_address) +
                " vfunc=" + HexString(spawn_function_address);
        }
        return true;
    }

    return true;
}

bool ExecuteSpawnGoldRewardNow(int amount, float x, float y, std::string* error_message) {
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

    DWORD exception_code = 0;
    if (!CallSpawnRewardGoldSafe(
            spawn_reward_address,
            arena_address,
            x,
            y,
            (std::max)(amount, 1),
            kSpawnRewardDefaultLifetime,
            &exception_code)) {
        if (error_message != nullptr) {
            *error_message =
                "Gold reward native spawn failed with 0x" +
                HexString(static_cast<uintptr_t>(exception_code)) +
                " arena=" + HexString(arena_address) +
                " function=" + HexString(spawn_reward_address);
        }
        return false;
    }

    return true;
}

bool ExecuteSpawnItemRewardNow(
    std::string_view kind,
    int amount,
    float x,
    float y,
    std::string* error_message) {
    if (kind != "item") {
        return false;
    }
    if (amount <= 0) {
        if (error_message != nullptr) {
            *error_message = "Item reward spawn requires a positive stock recipe UID as amount.";
        }
        return true;
    }

    uintptr_t recipe_address = 0;
    std::uint32_t item_type_id = 0;
    if (!TryResolveNativeItemRecipe(
            static_cast<std::uint32_t>(amount),
            0,
            &recipe_address,
            &item_type_id,
            error_message)) {
        return true;
    }
    if (item_type_id == 0 || item_type_id == kDebugSpawnPotionItemTypeId) {
        if (error_message != nullptr) {
            *error_message =
                item_type_id == kDebugSpawnPotionItemTypeId
                    ? "Potion recipes must be spawned with health_potion or mana_potion."
                    : "Item recipe resolved without a native item type.";
        }
        return true;
    }

    multiplayer::LootDropSnapshot drop{};
    drop.drop_kind = multiplayer::LootDropKind::Item;
    drop.active = true;
    drop.item_type_id = item_type_id;
    drop.item_recipe_uid = static_cast<std::uint32_t>(amount);
    drop.item_slot = -1;
    drop.stack_count = 1;
    drop.position_x = x;
    drop.position_y = y;

    uintptr_t carrier_address = 0;
    uintptr_t held_item_address = 0;
    if (!SpawnNativeItemDropFromRecipe(
            drop,
            &carrier_address,
            &held_item_address,
            error_message)) {
        return true;
    }

    Log(
        "spawn_reward: spawned stock item recipe_uid=" + std::to_string(amount) +
        " type_id=0x" + HexString(static_cast<uintptr_t>(item_type_id)) +
        " carrier=" + HexString(carrier_address) +
        " item=" + HexString(held_item_address));
    return true;
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

bool ExecuteSpawnPowerupRewardNow(
    std::string_view kind,
    int amount,
    float x,
    float y,
    std::string* error_message) {
    int powerup_kind = -1;
    if (kind == "bonus_skill" || kind == "bonus_skill_point") {
        powerup_kind =
            static_cast<int>(multiplayer::PowerupRewardKind::BonusSkillPoint);
    } else if (kind == "random_skill" || kind == "random_skill_rank") {
        powerup_kind =
            static_cast<int>(multiplayer::PowerupRewardKind::RandomSkillRank);
    } else if (kind == "damage_x4" || kind == "quad_damage") {
        powerup_kind =
            static_cast<int>(multiplayer::PowerupRewardKind::DamageX4);
    } else if (kind == "powerup" &&
               amount >=
                   static_cast<int>(
                       multiplayer::PowerupRewardKind::BonusSkillPoint) &&
               amount <=
                   static_cast<int>(
                       multiplayer::PowerupRewardKind::DamageX4)) {
        powerup_kind = amount;
    } else {
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
    const auto factory_address =
        memory.ResolveGameAddressOrZero(kGameObjectFactory);
    const auto factory_context_address =
        memory.ResolveGameAddressOrZero(kGameObjectFactoryContextGlobal);
    if (factory_address == 0 || factory_context_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Powerup reward factory entrypoint is unavailable.";
        }
        return true;
    }

    uintptr_t actor_address = 0;
    DWORD exception_code = 0;
    if (!CallGameObjectFactorySafe(
            factory_address,
            factory_context_address,
            static_cast<int>(kDebugSpawnPowerupRewardNativeTypeId),
            &actor_address,
            &exception_code) ||
        actor_address == 0) {
        if (error_message != nullptr) {
            *error_message =
                "Powerup reward factory failed with 0x" +
                HexString(exception_code) + ".";
        }
        return true;
    }

    const auto native_kind = static_cast<std::uint8_t>(powerup_kind);
    const bool seeded =
        memory.TryWriteField(actor_address, kActorPositionXOffset, x) &&
        memory.TryWriteField(actor_address, kActorPositionYOffset, y) &&
        memory.TryWriteField(
            actor_address,
            kDebugSpawnPowerupKindOffset,
            native_kind) &&
        memory.TryWriteField(
            actor_address,
            kDebugSpawnPowerupLifetimeOffset,
            kDebugSpawnPowerupLifetime);
    if (!seeded) {
        const auto object_delete_address =
            memory.ResolveGameAddressOrZero(kObjectDelete);
        DWORD delete_exception_code = 0;
        if (object_delete_address != 0) {
            (void)CallObjectDeleteSafe(
                object_delete_address,
                actor_address,
                &delete_exception_code);
        }
        if (error_message != nullptr) {
            *error_message =
                "Powerup reward field seeding failed for actor=" +
                HexString(actor_address) +
                " delete_seh=" + HexString(delete_exception_code);
        }
        return true;
    }

    exception_code = 0;
    const auto actor_world_attach_address =
        memory.ResolveGameAddressOrZero(kActorWorldAttach);
    if (!CallRewardWorldAttachSafe(
            actor_world_attach_address,
            player_state.world_address,
            actor_address,
            &exception_code)) {
        const auto object_delete_address =
            memory.ResolveGameAddressOrZero(kObjectDelete);
        DWORD delete_exception_code = 0;
        if (object_delete_address != 0) {
            (void)CallObjectDeleteSafe(
                object_delete_address,
                actor_address,
                &delete_exception_code);
        }
        if (error_message != nullptr) {
            *error_message =
                "Powerup reward world attach failed with 0x" +
                HexString(exception_code) +
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
    if (ExecuteSpawnPotionRewardNow(kind, amount, x, y, error_message)) {
        return error_message == nullptr || error_message->empty();
    }
    if (ExecuteSpawnItemRewardNow(kind, amount, x, y, error_message)) {
        return error_message == nullptr || error_message->empty();
    }
    if (ExecuteSpawnPowerupRewardNow(kind, amount, x, y, error_message)) {
        return error_message == nullptr || error_message->empty();
    }
    if (kind == "gold") {
        return ExecuteSpawnGoldRewardNow(amount, x, y, error_message);
    }
    if (kind != "gold") {
        if (error_message != nullptr) {
            *error_message = "Supported rewards are gold, health_orb/mana_orb, health_potion/mana_potion, item with a stock recipe UID, bonus_skill, random_skill, and damage_x4.";
        }
        return false;
    }
    return false;
}
