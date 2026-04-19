// sd.debug.read_ptr(address) -> integer|nil
int LuaDebugReadPtr(lua_State* state) {
    const auto address = CheckLuaAddress(state, 1, "address");
    return PushLuaAbsoluteValueResult<uintptr_t>(state, address);
}

// sd.debug.read_ptr_field(ptr_address, offset) -> integer|nil
int LuaDebugReadPtrField(lua_State* state) {
    const auto ptr_address = CheckLuaAddress(state, 1, "ptr_address");
    const auto offset = CheckLuaOffset(state, 2, "offset");
    return PushLuaFieldValueResult<uintptr_t>(state, ptr_address, offset);
}

// sd.debug.switch_region(region_index)
int LuaDebugSwitchRegion(lua_State* state) {
    const auto region_index = static_cast<int>(luaL_checkinteger(state, 1));
    std::string error_message;
    if (!QueueGameplaySwitchRegion(region_index, &error_message)) {
        return luaL_error(state, "sd.debug.switch_region failed: %s", error_message.c_str());
    }

    lua_pushboolean(state, 1);
    return 1;
}

int LuaDebugReadU8(lua_State* state) {
    const auto address = CheckLuaAddress(state, 1, "address");
    return PushLuaAbsoluteValueResult<std::uint8_t>(state, address);
}

int LuaDebugReadI8(lua_State* state) {
    const auto address = CheckLuaAddress(state, 1, "address");
    return PushLuaAbsoluteValueResult<std::int8_t>(state, address);
}

int LuaDebugReadI16(lua_State* state) {
    const auto address = CheckLuaAddress(state, 1, "address");
    return PushLuaAbsoluteValueResult<std::int16_t>(state, address);
}

int LuaDebugReadU16(lua_State* state) {
    const auto address = CheckLuaAddress(state, 1, "address");
    return PushLuaAbsoluteValueResult<std::uint16_t>(state, address);
}

int LuaDebugReadU32(lua_State* state) {
    const auto address = CheckLuaAddress(state, 1, "address");
    return PushLuaAbsoluteValueResult<std::uint32_t>(state, address);
}

int LuaDebugReadI32(lua_State* state) {
    const auto address = CheckLuaAddress(state, 1, "address");
    return PushLuaAbsoluteValueResult<std::int32_t>(state, address);
}

int LuaDebugReadFloat(lua_State* state) {
    const auto address = CheckLuaAddress(state, 1, "address");
    return PushLuaAbsoluteValueResult<float>(state, address);
}

int LuaDebugWriteU8(lua_State* state) {
    const auto address = CheckLuaAddress(state, 1, "address");
    const auto value = CheckLuaUnsignedInteger<std::uint8_t>(state, 2, "value");
    lua_pushboolean(state, TryWriteLuaAbsoluteValue(address, value) ? 1 : 0);
    return 1;
}

int LuaDebugWriteI8(lua_State* state) {
    const auto address = CheckLuaAddress(state, 1, "address");
    const auto value = CheckLuaSignedInteger<std::int8_t>(state, 2, "value");
    lua_pushboolean(state, TryWriteLuaAbsoluteValue(address, value) ? 1 : 0);
    return 1;
}

int LuaDebugWriteU16(lua_State* state) {
    const auto address = CheckLuaAddress(state, 1, "address");
    const auto value = CheckLuaUnsignedInteger<std::uint16_t>(state, 2, "value");
    lua_pushboolean(state, TryWriteLuaAbsoluteValue(address, value) ? 1 : 0);
    return 1;
}

int LuaDebugWriteI16(lua_State* state) {
    const auto address = CheckLuaAddress(state, 1, "address");
    const auto value = CheckLuaSignedInteger<std::int16_t>(state, 2, "value");
    lua_pushboolean(state, TryWriteLuaAbsoluteValue(address, value) ? 1 : 0);
    return 1;
}

int LuaDebugWriteU32(lua_State* state) {
    const auto address = CheckLuaAddress(state, 1, "address");
    const auto value = CheckLuaUnsignedInteger<std::uint32_t>(state, 2, "value");
    lua_pushboolean(state, TryWriteLuaAbsoluteValue(address, value) ? 1 : 0);
    return 1;
}

int LuaDebugWriteI32(lua_State* state) {
    const auto address = CheckLuaAddress(state, 1, "address");
    const auto value = CheckLuaSignedInteger<std::int32_t>(state, 2, "value");
    lua_pushboolean(state, TryWriteLuaAbsoluteValue(address, value) ? 1 : 0);
    return 1;
}

int LuaDebugWriteFloat(lua_State* state) {
    const auto address = CheckLuaAddress(state, 1, "address");
    const auto value = static_cast<float>(luaL_checknumber(state, 2));
    lua_pushboolean(state, TryWriteLuaAbsoluteValue(address, value) ? 1 : 0);
    return 1;
}

int LuaDebugWritePtr(lua_State* state) {
    const auto address = CheckLuaAddress(state, 1, "address");
    const auto value = CheckLuaAddress(state, 2, "value");
    lua_pushboolean(state, TryWriteLuaAbsoluteValue(address, value) ? 1 : 0);
    return 1;
}

