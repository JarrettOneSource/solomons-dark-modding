// sd.debug.call_thiscall_u32(function_address, this_ptr, arg0) -> boolean
int LuaDebugCallThiscallU32(lua_State* state) {
    const auto requested_function_address = CheckLuaAddress(state, 1, "function_address");
    const auto this_ptr = CheckLuaAddress(state, 2, "this_ptr");
    const auto arg0 = CheckLuaUnsignedInteger<std::uint32_t>(state, 3, "arg0");

    auto& memory = ProcessMemory::Instance();
    const auto function_address = ResolveExecutableLuaAddress(memory, requested_function_address);
    if (function_address == 0 || this_ptr == 0) {
        lua_pushboolean(state, 0);
        return 1;
    }

    using ThiscallU32Fn = void(__thiscall*)(void*, std::uint32_t);
    auto* fn = reinterpret_cast<ThiscallU32Fn>(function_address);
    bool ok = false;
    __try {
        fn(reinterpret_cast<void*>(this_ptr), arg0);
        ok = true;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        ok = false;
    }

    lua_pushboolean(state, ok ? 1 : 0);
    return 1;
}

// sd.debug.call_thiscall_u32_ret_u32(function_address, this_ptr, arg0) -> integer|nil
int LuaDebugCallThiscallU32RetU32(lua_State* state) {
    const auto requested_function_address = CheckLuaAddress(state, 1, "function_address");
    const auto this_ptr = CheckLuaAddress(state, 2, "this_ptr");
    const auto arg0 = CheckLuaUnsignedInteger<std::uint32_t>(state, 3, "arg0");

    auto& memory = ProcessMemory::Instance();
    const auto function_address = ResolveExecutableLuaAddress(memory, requested_function_address);
    if (function_address == 0 || this_ptr == 0) {
        lua_pushnil(state);
        return 1;
    }

    using ThiscallU32RetU32Fn = std::uint32_t(__thiscall*)(void*, std::uint32_t);
    auto* fn = reinterpret_cast<ThiscallU32RetU32Fn>(function_address);
    std::uint32_t result = 0;
    bool ok = false;
    __try {
        result = fn(reinterpret_cast<void*>(this_ptr), arg0);
        ok = true;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        ok = false;
    }

    if (!ok || result == 0) {
        lua_pushnil(state);
        return 1;
    }

    lua_pushinteger(state, static_cast<lua_Integer>(result));
    return 1;
}

// sd.debug.call_thiscall_out_f32x4_u32(function_address, this_ptr, arg0) -> table|nil
int LuaDebugCallThiscallOutF32x4U32(lua_State* state) {
    const auto requested_function_address = CheckLuaAddress(state, 1, "function_address");
    const auto this_ptr = CheckLuaAddress(state, 2, "this_ptr");
    const auto arg0 = CheckLuaUnsignedInteger<std::uint32_t>(state, 3, "arg0");

    auto& memory = ProcessMemory::Instance();
    const auto function_address = ResolveExecutableLuaAddress(memory, requested_function_address);
    if (function_address == 0 || this_ptr == 0) {
        lua_pushnil(state);
        return 1;
    }

    using ThiscallOutF32x4U32Fn = void(__thiscall*)(void*, float*, std::uint32_t);
    auto* fn = reinterpret_cast<ThiscallOutF32x4U32Fn>(function_address);
    float result[4] = {};
    bool ok = false;
    __try {
        fn(reinterpret_cast<void*>(this_ptr), result, arg0);
        ok = true;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        ok = false;
    }

    if (!ok) {
        lua_pushnil(state);
        return 1;
    }

    lua_createtable(state, 4, 0);
    for (int i = 0; i < 4; ++i) {
        lua_pushnumber(state, static_cast<lua_Number>(result[i]));
        lua_rawseti(state, -2, i + 1);
    }
    return 1;
}

// sd.debug.call_cdecl_u32_ret_u32(function_address, arg0) -> integer|nil
int LuaDebugCallCdeclU32RetU32(lua_State* state) {
    const auto requested_function_address = CheckLuaAddress(state, 1, "function_address");
    const auto arg0 = CheckLuaUnsignedInteger<std::uint32_t>(state, 2, "arg0");

    auto& memory = ProcessMemory::Instance();
    const auto function_address = ResolveExecutableLuaAddress(memory, requested_function_address);
    if (function_address == 0) {
        lua_pushnil(state);
        return 1;
    }

    using CdeclU32RetU32Fn = std::uint32_t(__cdecl*)(std::uint32_t);
    auto* fn = reinterpret_cast<CdeclU32RetU32Fn>(function_address);
    std::uint32_t result = 0;
    bool ok = false;
    __try {
        result = fn(arg0);
        ok = true;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        ok = false;
    }

    if (!ok || result == 0) {
        lua_pushnil(state);
        return 1;
    }

    lua_pushinteger(state, static_cast<lua_Integer>(result));
    return 1;
}

