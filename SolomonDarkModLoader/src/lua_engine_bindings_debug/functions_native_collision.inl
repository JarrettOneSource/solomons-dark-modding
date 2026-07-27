using DebugMovementCollisionTestCirclePlacementFn =
    std::uint32_t(__thiscall*)(
        void* self,
        float x,
        float y,
        float radius,
        std::uint32_t mask);

using DebugMovementCollisionTestCirclePlacementExtendedFn =
    std::uint32_t(__thiscall*)(
        void* self,
        float x,
        float y,
        float radius,
        std::uint32_t circle_block_mask,
        std::uint32_t overlap_allow_mask);

bool CallMovementCollisionTestCirclePlacementSafe(
    uintptr_t function_address,
    uintptr_t movement_controller_address,
    float x,
    float y,
    float radius,
    std::uint32_t mask,
    std::uint32_t* blocked,
    DWORD* exception_code) {
    if (blocked != nullptr) {
        *blocked = 0;
    }
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (function_address == 0 ||
        movement_controller_address == 0 ||
        blocked == nullptr) {
        return false;
    }

    auto* test =
        reinterpret_cast<
            DebugMovementCollisionTestCirclePlacementFn>(
                function_address);
    __try {
        *blocked =
            test(
                reinterpret_cast<void*>(
                    movement_controller_address),
                x,
                y,
                radius,
                mask);
        return true;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        if (exception_code != nullptr) {
            *exception_code = EXCEPTION_ACCESS_VIOLATION;
        }
        return false;
    }
}

bool CallMovementCollisionTestCirclePlacementExtendedSafe(
    uintptr_t function_address,
    uintptr_t movement_controller_address,
    float x,
    float y,
    float radius,
    std::uint32_t circle_block_mask,
    std::uint32_t overlap_allow_mask,
    std::uint32_t* blocked,
    DWORD* exception_code) {
    if (blocked != nullptr) {
        *blocked = 0;
    }
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (function_address == 0 ||
        movement_controller_address == 0 ||
        blocked == nullptr) {
        return false;
    }

    auto* test =
        reinterpret_cast<
            DebugMovementCollisionTestCirclePlacementExtendedFn>(
                function_address);
    __try {
        *blocked =
            test(
                reinterpret_cast<void*>(
                    movement_controller_address),
                x,
                y,
                radius,
                circle_block_mask,
                overlap_allow_mask);
        return true;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        if (exception_code != nullptr) {
            *exception_code = EXCEPTION_ACCESS_VIOLATION;
        }
        return false;
    }
}

// sd.debug.test_native_movement_collision(
//   x, y[, radius[, circle_block_mask[, overlap_allow_mask]]]) -> table
int LuaDebugTestNativeMovementCollision(lua_State* state) {
    const auto x = static_cast<float>(
        luaL_checknumber(state, 1));
    const auto y = static_cast<float>(
        luaL_checknumber(state, 2));
    if (!std::isfinite(x) || !std::isfinite(y)) {
        return luaL_error(
            state,
            "native movement collision coordinates must be finite");
    }

    SDModPlayerState player;
    if (!TryGetPlayerState(&player) ||
        !player.valid ||
        player.actor_address == 0 ||
        player.world_address == 0) {
        return luaL_error(
            state,
            "native movement collision query requires a live player");
    }

    auto& memory = ProcessMemory::Instance();
    float radius = 0.0f;
    if (!memory.TryReadField(
            player.actor_address,
            kActorCollisionRadiusOffset,
            &radius) ||
        !std::isfinite(radius) ||
        radius <= 0.0f) {
        return luaL_error(
            state,
            "native movement collision query could not read player radius");
    }
    if (lua_gettop(state) >= 3 &&
        !lua_isnil(state, 3)) {
        radius = static_cast<float>(
            luaL_checknumber(state, 3));
        if (!std::isfinite(radius) ||
            radius <= 0.0f) {
            return luaL_error(
                state,
                "native movement collision radius must be positive and finite");
        }
    }
    std::uint32_t circle_block_mask = 0;
    if (lua_gettop(state) >= 4 &&
        !lua_isnil(state, 4)) {
        circle_block_mask =
            CheckLuaUnsignedInteger<std::uint32_t>(
                state,
                4,
                "circle_block_mask");
    }
    std::uint32_t overlap_allow_mask = 0;
    if (lua_gettop(state) >= 5 &&
        !lua_isnil(state, 5)) {
        overlap_allow_mask =
            CheckLuaUnsignedInteger<std::uint32_t>(
                state,
                5,
                "overlap_allow_mask");
    }

    const auto movement_controller_address =
        player.world_address +
        kActorOwnerMovementControllerOffset;
    const auto basic_function_address =
        memory.ResolveGameAddressOrZero(
            kMovementCollisionTestCirclePlacement);
    const auto extended_function_address =
        memory.ResolveGameAddressOrZero(
            kMovementCollisionTestCirclePlacementExtended);
    std::uint32_t blocked = 0;
    DWORD exception_code = 0;
    bool used_extended = extended_function_address != 0;
    const bool ok =
        used_extended
            ? CallMovementCollisionTestCirclePlacementExtendedSafe(
                  extended_function_address,
                  movement_controller_address,
                  x,
                  y,
                  radius,
                  circle_block_mask,
                  overlap_allow_mask,
                  &blocked,
                  &exception_code)
            : CallMovementCollisionTestCirclePlacementSafe(
                  basic_function_address,
                  movement_controller_address,
                  x,
                  y,
                  radius,
                  overlap_allow_mask,
                  &blocked,
                  &exception_code);

    lua_createtable(state, 0, 9);
    lua_pushboolean(state, ok ? 1 : 0);
    lua_setfield(state, -2, "ok");
    lua_pushboolean(state, blocked != 0 ? 1 : 0);
    lua_setfield(state, -2, "blocked");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(blocked));
    lua_setfield(state, -2, "native_result");
    lua_pushnumber(
        state,
        static_cast<lua_Number>(radius));
    lua_setfield(state, -2, "radius");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(
            circle_block_mask));
    lua_setfield(state, -2, "circle_block_mask");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(
            overlap_allow_mask));
    lua_setfield(state, -2, "overlap_allow_mask");
    lua_pushstring(
        state,
        used_extended ? "extended" : "basic");
    lua_setfield(state, -2, "mode");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(
            movement_controller_address));
    lua_setfield(state, -2, "movement_controller_address");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(exception_code));
    lua_setfield(state, -2, "exception_code");
    return 1;
}
