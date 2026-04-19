int LuaDebugReadFieldU8(lua_State* state) {
    const auto ptr_address = CheckLuaAddress(state, 1, "ptr_address");
    const auto offset = CheckLuaOffset(state, 2, "offset");
    return PushLuaFieldValueResult<std::uint8_t>(state, ptr_address, offset);
}

int LuaDebugReadFieldU32(lua_State* state) {
    const auto ptr_address = CheckLuaAddress(state, 1, "ptr_address");
    const auto offset = CheckLuaOffset(state, 2, "offset");
    return PushLuaFieldValueResult<std::uint32_t>(state, ptr_address, offset);
}

int LuaDebugReadFieldFloat(lua_State* state) {
    const auto ptr_address = CheckLuaAddress(state, 1, "ptr_address");
    const auto offset = CheckLuaOffset(state, 2, "offset");
    return PushLuaFieldValueResult<float>(state, ptr_address, offset);
}

int LuaDebugWriteFieldU8(lua_State* state) {
    const auto ptr_address = CheckLuaAddress(state, 1, "ptr_address");
    const auto offset = CheckLuaOffset(state, 2, "offset");
    const auto value = CheckLuaUnsignedInteger<std::uint8_t>(state, 3, "value");
    lua_pushboolean(state, TryWriteLuaFieldValue(ptr_address, offset, value) ? 1 : 0);
    return 1;
}

int LuaDebugWriteFieldU32(lua_State* state) {
    const auto ptr_address = CheckLuaAddress(state, 1, "ptr_address");
    const auto offset = CheckLuaOffset(state, 2, "offset");
    const auto value = CheckLuaUnsignedInteger<std::uint32_t>(state, 3, "value");
    lua_pushboolean(state, TryWriteLuaFieldValue(ptr_address, offset, value) ? 1 : 0);
    return 1;
}

int LuaDebugWriteFieldFloat(lua_State* state) {
    const auto ptr_address = CheckLuaAddress(state, 1, "ptr_address");
    const auto offset = CheckLuaOffset(state, 2, "offset");
    const auto value = static_cast<float>(luaL_checknumber(state, 3));
    lua_pushboolean(state, TryWriteLuaFieldValue(ptr_address, offset, value) ? 1 : 0);
    return 1;
}
