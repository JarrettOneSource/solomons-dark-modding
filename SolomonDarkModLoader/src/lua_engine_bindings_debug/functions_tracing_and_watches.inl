// sd.debug.trace_function(address, name) -> bool
int LuaDebugTraceFunction(lua_State* state) {
    const auto address = CheckLuaAddress(state, 1, "address");
    const char* name = luaL_checkstring(state, 2);
    size_t patch_size = 0;
    if (lua_gettop(state) >= 3 && !lua_isnil(state, 3)) {
        patch_size = CheckLuaTransferSize(state, 3, "patch_size");
    }

    const bool ok = patch_size == 0
        ? RuntimeDebug_TraceFunction(address, name)
        : RuntimeDebug_TraceFunctionEx(address, patch_size, name);
    lua_pushboolean(state, ok ? 1 : 0);
    return 1;
}

// sd.debug.untrace_function(address)
int LuaDebugUntraceFunction(lua_State* state) {
    const auto address = CheckLuaAddress(state, 1, "address");
    RuntimeDebug_UntraceFunction(address);
    return 0;
}

// sd.debug.watch(name, address, size)
int LuaDebugWatch(lua_State* state) {
    const char* name = luaL_checkstring(state, 1);
    const auto address = CheckLuaAddress(state, 2, "address");
    const auto size = CheckLuaTransferSize(state, 3, "size");
    RuntimeDebug_WatchMemory(address, size, name);
    return 0;
}

// sd.debug.watch_write(name, address, size) -> boolean
int LuaDebugWatchWrite(lua_State* state) {
    const char* name = luaL_checkstring(state, 1);
    const auto address = CheckLuaAddress(state, 2, "address");
    const auto size = CheckLuaTransferSize(state, 3, "size");
    lua_pushboolean(state, RuntimeDebug_WatchWriteMemory(address, size, name) ? 1 : 0);
    return 1;
}

// sd.debug.watch_write_ptr_field(ptr_address, offset, size, name) -> boolean
int LuaDebugWatchWritePtrField(lua_State* state) {
    const auto ptr_address = CheckLuaAddress(state, 1, "ptr_address");
    const auto offset = CheckLuaOffset(state, 2, "offset");
    const auto size = CheckLuaTransferSize(state, 3, "size");
    const char* name = luaL_checkstring(state, 4);
    lua_pushboolean(state, RuntimeDebug_WatchWritePtrField(ptr_address, offset, size, name) ? 1 : 0);
    return 1;
}

// sd.debug.unwatch(name) -> boolean
int LuaDebugUnwatch(lua_State* state) {
    const char* name = luaL_checkstring(state, 1);
    lua_pushboolean(state, RuntimeDebug_UnwatchMemoryByName(name) ? 1 : 0);
    return 1;
}

// sd.debug.list_watches() -> table[]
int LuaDebugListWatches(lua_State* state) {
    std::vector<RuntimeDebugWatchInfo> watches;
    RuntimeDebug_ListWatches(&watches);

    lua_createtable(state, static_cast<int>(watches.size()), 0);
    for (std::size_t index = 0; index < watches.size(); ++index) {
        const auto& watch = watches[index];
        lua_createtable(state, 0, 9);
        lua_pushstring(state, watch.name.c_str());
        lua_setfield(state, -2, "name");
        lua_pushstring(state, watch.is_ptr_field ? "ptr_field" : "direct");
        lua_setfield(state, -2, "kind");
        lua_pushinteger(state, static_cast<lua_Integer>(watch.requested_address));
        lua_setfield(state, -2, "address");
        lua_pushinteger(state, static_cast<lua_Integer>(watch.resolved_address));
        lua_setfield(state, -2, "resolved_address");
        lua_pushinteger(state, static_cast<lua_Integer>(watch.offset));
        lua_setfield(state, -2, "offset");
        lua_pushinteger(state, static_cast<lua_Integer>(watch.size));
        lua_setfield(state, -2, "size");
        lua_pushboolean(state, watch.last_valid ? 1 : 0);
        lua_setfield(state, -2, "valid");
        lua_pushinteger(state, static_cast<lua_Integer>(watch.last_base_address));
        lua_setfield(state, -2, "base_address");
        lua_pushinteger(state, static_cast<lua_Integer>(watch.last_value_address));
        lua_setfield(state, -2, "value_address");
        lua_rawseti(state, -2, static_cast<lua_Integer>(index + 1));
    }
    return 1;
}

