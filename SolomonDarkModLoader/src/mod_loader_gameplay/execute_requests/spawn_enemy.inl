bool ExecuteSpawnEnemyNow(int type_id, float x, float y, uintptr_t* out_enemy_address, std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (out_enemy_address != nullptr) {
        *out_enemy_address = 0;
    }

    if (type_id <= 0) {
        if (error_message != nullptr) {
            *error_message =
                "spawn_enemy: invalid type_id=" + std::to_string(type_id) +
                " (must be > 0; known-good types include 2012 and 5010).";
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

    ArenaWaveStartState wave_state;
    if (TryReadArenaWaveStartState(arena_address, &wave_state) && wave_state.combat_active != 0) {
        if (error_message != nullptr) {
            *error_message =
                "spawn_enemy: refusing manual spawn while arena combat is active. "
                "Our hardcoded (anchor=nullptr, mode=0, param_5=0, param_6=0, override=0) call "
                "shape wedges Enemy_Create's placement sweep once combat state is populated. "
                "arena=" + HexString(arena_address) +
                " state=" + DescribeArenaWaveStartState(wave_state);
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto enemy_config_ctor_address = memory.ResolveGameAddressOrZero(kEnemyConfigCtor);
    const auto enemy_config_dtor_address = memory.ResolveGameAddressOrZero(kEnemyConfigDtor);
    const auto build_config_address = memory.ResolveGameAddressOrZero(kBuildEnemyConfig);
    const auto spawn_enemy_address = memory.ResolveGameAddressOrZero(kSpawnEnemy);
    if (enemy_config_ctor_address == 0 ||
        enemy_config_dtor_address == 0 ||
        build_config_address == 0 ||
        spawn_enemy_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve one or more enemy spawn entrypoints.";
        }
        return false;
    }

    EnemyModifierList modifiers;
    ResetEnemyModifierList(&modifiers);
    if (modifiers.vtable == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the Array<int> vtable used by enemy modifiers.";
        }
        return false;
    }

    alignas(void*) std::array<std::uint8_t, kEnemyConfigWrapperSize> config_wrapper{};
    void* const config_wrapper_address = config_wrapper.data();
    void* const config_buffer_address = config_wrapper.data() + 4;

    SpawnEnemyCallContext call_context;
    call_context.arena_address = arena_address;
    call_context.config_ctor = reinterpret_cast<EnemyConfigCtorFn>(enemy_config_ctor_address);
    call_context.config_dtor = reinterpret_cast<EnemyConfigDtorFn>(enemy_config_dtor_address);
    call_context.build_config = reinterpret_cast<EnemyConfigBuildFn>(build_config_address);
    call_context.spawn_enemy = reinterpret_cast<EnemySpawnFn>(spawn_enemy_address);
    call_context.modifiers = &modifiers;
    call_context.config_wrapper = config_wrapper_address;
    call_context.config_buffer = config_buffer_address;
    call_context.type_id = type_id;

    DWORD exception_code = 0;
    auto* enemy = CallSpawnEnemyInternal(&call_context, &exception_code);
    CleanupEnemyModifierList(&modifiers);
    if (enemy == nullptr) {
        if (error_message != nullptr) {
            *error_message =
                "Enemy_Create failed for type_id=" + std::to_string(type_id) +
                " exception=" + HexString(exception_code);
        }
        return false;
    }

    const auto enemy_address = reinterpret_cast<uintptr_t>(enemy);
    if (out_enemy_address != nullptr) {
        *out_enemy_address = enemy_address;
    }
    const bool wrote_x = memory.TryWriteField(enemy_address, kActorPositionXOffset, x);
    const bool wrote_y = memory.TryWriteField(enemy_address, kActorPositionYOffset, y);
    if (!wrote_x || !wrote_y) {
        Log(
            "spawn_enemy: created enemy but failed to overwrite final position. type_id=" +
            std::to_string(type_id) +
            " enemy=" + HexString(enemy_address) +
            " wrote_x=" + std::to_string(wrote_x ? 1 : 0) +
            " wrote_y=" + std::to_string(wrote_y ? 1 : 0));
    }

    return true;
}
