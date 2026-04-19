// sd.debug.watch_ptr_field(ptr_address, offset, size, name)
int LuaDebugWatchPtrField(lua_State* state) {
    const auto ptr_address = CheckLuaAddress(state, 1, "ptr_address");
    const auto offset = CheckLuaOffset(state, 2, "offset");
    const auto size = CheckLuaTransferSize(state, 3, "size");
    const char* name = luaL_checkstring(state, 4);
    RuntimeDebug_WatchPtrField(ptr_address, offset, size, name);
    return 0;
}

// sd.debug.snapshot(name, address, size)
int LuaDebugSnapshot(lua_State* state) {
    const char* name = luaL_checkstring(state, 1);
    const auto address = CheckLuaAddress(state, 2, "address");
    const auto size = CheckLuaTransferSize(state, 3, "size");
    RuntimeDebug_Snapshot(name, address, size);
    return 0;
}

// sd.debug.snapshot_ptr_field(name, ptr_address, offset, size)
int LuaDebugSnapshotPtrField(lua_State* state) {
    const char* name = luaL_checkstring(state, 1);
    const auto ptr_address = CheckLuaAddress(state, 2, "ptr_address");
    const auto offset = CheckLuaOffset(state, 3, "offset");
    const auto size = CheckLuaTransferSize(state, 4, "size");
    RuntimeDebug_SnapshotPtrField(name, ptr_address, offset, size);
    return 0;
}

// sd.debug.snapshot_nested_ptr_field(name, ptr_address, outer_offset, inner_offset, size)
int LuaDebugSnapshotNestedPtrField(lua_State* state) {
    const char* name = luaL_checkstring(state, 1);
    const auto ptr_address = CheckLuaAddress(state, 2, "ptr_address");
    const auto outer_offset = CheckLuaOffset(state, 3, "outer_offset");
    const auto inner_offset = CheckLuaOffset(state, 4, "inner_offset");
    const auto size = CheckLuaTransferSize(state, 5, "size");
    RuntimeDebug_SnapshotNestedPtrField(name, ptr_address, outer_offset, inner_offset, size);
    return 0;
}

// sd.debug.snapshot_double_nested_ptr_field(name, ptr_address, outer_offset, middle_offset, inner_offset, size)
int LuaDebugSnapshotDoubleNestedPtrField(lua_State* state) {
    const char* name = luaL_checkstring(state, 1);
    const auto ptr_address = CheckLuaAddress(state, 2, "ptr_address");
    const auto outer_offset = CheckLuaOffset(state, 3, "outer_offset");
    const auto middle_offset = CheckLuaOffset(state, 4, "middle_offset");
    const auto inner_offset = CheckLuaOffset(state, 5, "inner_offset");
    const auto size = CheckLuaTransferSize(state, 6, "size");
    RuntimeDebug_SnapshotDoubleNestedPtrField(
        name,
        ptr_address,
        outer_offset,
        middle_offset,
        inner_offset,
        size);
    return 0;
}

// sd.debug.diff(name_a, name_b)
int LuaDebugDiff(lua_State* state) {
    const char* name_a = luaL_checkstring(state, 1);
    const char* name_b = luaL_checkstring(state, 2);
    RuntimeDebug_DiffSnapshots(name_a, name_b);
    return 0;
}

// sd.debug.resolve_ptr_chain(ptr_address, offsets) -> integer|nil
int LuaDebugResolvePtrChain(lua_State* state) {
    const auto ptr_address = CheckLuaAddress(state, 1, "ptr_address");
    std::vector<size_t> offsets;
    std::string error_message;
    if (!TryParseLuaOffsetTable(state, 2, &offsets, &error_message)) {
        return luaL_argerror(state, 2, error_message.c_str());
    }

    uintptr_t final_address = 0;
    if (!TryResolveLuaPtrChainFromPointerSlot(ptr_address, offsets, &final_address)) {
        lua_pushnil(state);
        return 1;
    }

    lua_pushinteger(state, static_cast<lua_Integer>(final_address));
    return 1;
}

// sd.debug.resolve_object_ptr_chain(base_address, offsets) -> integer|nil
int LuaDebugResolveObjectPtrChain(lua_State* state) {
    const auto base_address = CheckLuaAddress(state, 1, "base_address");
    std::vector<size_t> offsets;
    std::string error_message;
    if (!TryParseLuaOffsetTable(state, 2, &offsets, &error_message)) {
        return luaL_argerror(state, 2, error_message.c_str());
    }

    uintptr_t final_address = 0;
    if (!TryResolveLuaPtrChainFromObjectBase(base_address, offsets, &final_address)) {
        lua_pushnil(state);
        return 1;
    }

    lua_pushinteger(state, static_cast<lua_Integer>(final_address));
    return 1;
}

// sd.debug.dump_ptr_chain(ptr_address, offsets) -> table
int LuaDebugDumpPtrChain(lua_State* state) {
    const auto ptr_address = CheckLuaAddress(state, 1, "ptr_address");
    std::vector<size_t> offsets;
    std::string error_message;
    if (!TryParseLuaOffsetTable(state, 2, &offsets, &error_message)) {
        return luaL_argerror(state, 2, error_message.c_str());
    }

    PushLuaPtrChainSteps(state, ptr_address, offsets, true);
    return 1;
}

// sd.debug.dump_object_ptr_chain(base_address, offsets) -> table
int LuaDebugDumpObjectPtrChain(lua_State* state) {
    const auto base_address = CheckLuaAddress(state, 1, "base_address");
    std::vector<size_t> offsets;
    std::string error_message;
    if (!TryParseLuaOffsetTable(state, 2, &offsets, &error_message)) {
        return luaL_argerror(state, 2, error_message.c_str());
    }

    PushLuaPtrChainSteps(state, base_address, offsets, false);
    return 1;
}

// sd.debug.snapshot_ptr_chain(name, ptr_address, offsets, size)
int LuaDebugSnapshotPtrChain(lua_State* state) {
    const char* name = luaL_checkstring(state, 1);
    const auto ptr_address = CheckLuaAddress(state, 2, "ptr_address");
    std::vector<size_t> offsets;
    std::string error_message;
    if (!TryParseLuaOffsetTable(state, 3, &offsets, &error_message)) {
        return luaL_argerror(state, 3, error_message.c_str());
    }
    const auto size = CheckLuaTransferSize(state, 4, "size");

    uintptr_t final_address = 0;
    if (!TryResolveLuaPtrChainFromPointerSlot(ptr_address, offsets, &final_address)) {
        lua_pushboolean(state, 0);
        return 1;
    }

    RuntimeDebug_Snapshot(name, final_address, size);
    lua_pushboolean(state, 1);
    return 1;
}

// sd.debug.snapshot_object_ptr_chain(name, base_address, offsets, size)
int LuaDebugSnapshotObjectPtrChain(lua_State* state) {
    const char* name = luaL_checkstring(state, 1);
    const auto base_address = CheckLuaAddress(state, 2, "base_address");
    std::vector<size_t> offsets;
    std::string error_message;
    if (!TryParseLuaOffsetTable(state, 3, &offsets, &error_message)) {
        return luaL_argerror(state, 3, error_message.c_str());
    }
    const auto size = CheckLuaTransferSize(state, 4, "size");

    uintptr_t final_address = 0;
    if (!TryResolveLuaPtrChainFromObjectBase(base_address, offsets, &final_address)) {
        lua_pushboolean(state, 0);
        return 1;
    }

    RuntimeDebug_Snapshot(name, final_address, size);
    lua_pushboolean(state, 1);
    return 1;
}

// sd.debug.list_traces() -> table[]
int LuaDebugListTraces(lua_State* state) {
    std::vector<RuntimeDebugTraceInfo> traces;
    RuntimeDebug_ListTraces(&traces);

    lua_createtable(state, static_cast<int>(traces.size()), 0);
    for (std::size_t index = 0; index < traces.size(); ++index) {
        const auto& trace = traces[index];
        lua_createtable(state, 0, 5);
        lua_pushstring(state, trace.name.c_str());
        lua_setfield(state, -2, "name");
        lua_pushinteger(state, static_cast<lua_Integer>(trace.requested_address));
        lua_setfield(state, -2, "requested_address");
        lua_pushinteger(state, static_cast<lua_Integer>(trace.resolved_address));
        lua_setfield(state, -2, "resolved_address");
        lua_pushinteger(state, static_cast<lua_Integer>(trace.patch_size));
        lua_setfield(state, -2, "patch_size");
        lua_pushboolean(state, trace.active ? 1 : 0);
        lua_setfield(state, -2, "active");
        lua_rawseti(state, -2, static_cast<lua_Integer>(index + 1));
    }
    return 1;
}

