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

// sd.debug.get_last_error() -> string|nil
int LuaDebugGetLastError(lua_State* state) {
    const auto message = RuntimeDebug_GetLastError();
    if (message.empty()) {
        lua_pushnil(state);
        return 1;
    }

    lua_pushlstring(state, message.data(), message.size());
    return 1;
}

// sd.debug.get_trace_hits(name?) -> table[]
int LuaDebugGetTraceHits(lua_State* state) {
    const char* filter = nullptr;
    if (lua_gettop(state) >= 1 && !lua_isnil(state, 1)) {
        filter = luaL_checkstring(state, 1);
    }

    std::vector<RuntimeDebugTraceHitInfo> hits;
    RuntimeDebug_ListTraceHits(&hits, filter);

    lua_createtable(state, static_cast<int>(hits.size()), 0);
    for (std::size_t index = 0; index < hits.size(); ++index) {
        const auto& hit = hits[index];
        lua_createtable(state, 0, 15);
        lua_pushstring(state, hit.name.c_str());
        lua_setfield(state, -2, "name");
        lua_pushinteger(state, static_cast<lua_Integer>(hit.requested_address));
        lua_setfield(state, -2, "requested_address");
        lua_pushinteger(state, static_cast<lua_Integer>(hit.resolved_address));
        lua_setfield(state, -2, "resolved_address");
        lua_pushinteger(state, static_cast<lua_Integer>(hit.thread_id));
        lua_setfield(state, -2, "thread_id");
        lua_pushinteger(state, static_cast<lua_Integer>(hit.eax));
        lua_setfield(state, -2, "eax");
        lua_pushinteger(state, static_cast<lua_Integer>(hit.ecx));
        lua_setfield(state, -2, "ecx");
        lua_pushinteger(state, static_cast<lua_Integer>(hit.edx));
        lua_setfield(state, -2, "edx");
        lua_pushinteger(state, static_cast<lua_Integer>(hit.ebx));
        lua_setfield(state, -2, "ebx");
        lua_pushinteger(state, static_cast<lua_Integer>(hit.esi));
        lua_setfield(state, -2, "esi");
        lua_pushinteger(state, static_cast<lua_Integer>(hit.edi));
        lua_setfield(state, -2, "edi");
        lua_pushinteger(state, static_cast<lua_Integer>(hit.ebp));
        lua_setfield(state, -2, "ebp");
        lua_pushinteger(state, static_cast<lua_Integer>(hit.esp_before_pushad));
        lua_setfield(state, -2, "esp_before_pushad");
        lua_pushinteger(state, static_cast<lua_Integer>(hit.eflags));
        lua_setfield(state, -2, "eflags");
        lua_pushinteger(state, static_cast<lua_Integer>(hit.ret));
        lua_setfield(state, -2, "ret");
        lua_pushinteger(state, static_cast<lua_Integer>(hit.arg0));
        lua_setfield(state, -2, "arg0");
        lua_pushinteger(state, static_cast<lua_Integer>(hit.arg1));
        lua_setfield(state, -2, "arg1");
        lua_pushinteger(state, static_cast<lua_Integer>(hit.arg2));
        lua_setfield(state, -2, "arg2");
        lua_pushinteger(state, static_cast<lua_Integer>(hit.arg3));
        lua_setfield(state, -2, "arg3");
        lua_pushinteger(state, static_cast<lua_Integer>(hit.arg4));
        lua_setfield(state, -2, "arg4");
        lua_pushboolean(state, hit.arg3_words_valid ? 1 : 0);
        lua_setfield(state, -2, "arg3_words_valid");
        if (hit.arg3_words_valid) {
            lua_createtable(state, 4, 0);
            lua_pushinteger(state, static_cast<lua_Integer>(hit.arg3_word0));
            lua_rawseti(state, -2, 1);
            lua_pushinteger(state, static_cast<lua_Integer>(hit.arg3_word1));
            lua_rawseti(state, -2, 2);
            lua_pushinteger(state, static_cast<lua_Integer>(hit.arg3_word2));
            lua_rawseti(state, -2, 3);
            lua_pushinteger(state, static_cast<lua_Integer>(hit.arg3_word3));
            lua_rawseti(state, -2, 4);
            lua_setfield(state, -2, "arg3_words");
        }
        lua_pushboolean(state, hit.arg4_words_valid ? 1 : 0);
        lua_setfield(state, -2, "arg4_words_valid");
        if (hit.arg4_words_valid) {
            lua_createtable(state, 4, 0);
            lua_pushinteger(state, static_cast<lua_Integer>(hit.arg4_word0));
            lua_rawseti(state, -2, 1);
            lua_pushinteger(state, static_cast<lua_Integer>(hit.arg4_word1));
            lua_rawseti(state, -2, 2);
            lua_pushinteger(state, static_cast<lua_Integer>(hit.arg4_word2));
            lua_rawseti(state, -2, 3);
            lua_pushinteger(state, static_cast<lua_Integer>(hit.arg4_word3));
            lua_rawseti(state, -2, 4);
            lua_setfield(state, -2, "arg4_words");
        }
        lua_rawseti(state, -2, static_cast<lua_Integer>(index + 1));
    }
    return 1;
}

// sd.debug.clear_trace_hits(name?)
int LuaDebugClearTraceHits(lua_State* state) {
    const char* filter = nullptr;
    if (lua_gettop(state) >= 1 && !lua_isnil(state, 1)) {
        filter = luaL_checkstring(state, 1);
    }
    RuntimeDebug_ClearTraceHits(filter);
    return 0;
}

// sd.debug.get_write_hits(name?) -> table[]
int LuaDebugGetWriteHits(lua_State* state) {
    const char* filter = nullptr;
    if (lua_gettop(state) >= 1 && !lua_isnil(state, 1)) {
        filter = luaL_checkstring(state, 1);
    }

    std::vector<RuntimeDebugWriteHitInfo> hits;
    RuntimeDebug_ListWriteHits(&hits, filter);

    lua_createtable(state, static_cast<int>(hits.size()), 0);
    for (std::size_t index = 0; index < hits.size(); ++index) {
        const auto& hit = hits[index];
        lua_createtable(state, 0, 18);
        lua_pushstring(state, hit.name.c_str());
        lua_setfield(state, -2, "name");
        lua_pushboolean(state, hit.is_ptr_field ? 1 : 0);
        lua_setfield(state, -2, "is_ptr_field");
        lua_pushinteger(state, static_cast<lua_Integer>(hit.requested_address));
        lua_setfield(state, -2, "requested_address");
        lua_pushinteger(state, static_cast<lua_Integer>(hit.resolved_address));
        lua_setfield(state, -2, "resolved_address");
        lua_pushinteger(state, static_cast<lua_Integer>(hit.base_address));
        lua_setfield(state, -2, "base_address");
        lua_pushinteger(state, static_cast<lua_Integer>(hit.value_address));
        lua_setfield(state, -2, "value_address");
        lua_pushinteger(state, static_cast<lua_Integer>(hit.access_address));
        lua_setfield(state, -2, "access_address");
        lua_pushinteger(state, static_cast<lua_Integer>(hit.offset));
        lua_setfield(state, -2, "offset");
        lua_pushinteger(state, static_cast<lua_Integer>(hit.size));
        lua_setfield(state, -2, "size");
        lua_pushinteger(state, static_cast<lua_Integer>(hit.thread_id));
        lua_setfield(state, -2, "thread_id");
        lua_pushinteger(state, static_cast<lua_Integer>(hit.eip));
        lua_setfield(state, -2, "eip");
        lua_pushinteger(state, static_cast<lua_Integer>(hit.esp));
        lua_setfield(state, -2, "esp");
        lua_pushinteger(state, static_cast<lua_Integer>(hit.ebp));
        lua_setfield(state, -2, "ebp");
        lua_pushinteger(state, static_cast<lua_Integer>(hit.eax));
        lua_setfield(state, -2, "eax");
        lua_pushinteger(state, static_cast<lua_Integer>(hit.ecx));
        lua_setfield(state, -2, "ecx");
        lua_pushinteger(state, static_cast<lua_Integer>(hit.edx));
        lua_setfield(state, -2, "edx");
        lua_pushinteger(state, static_cast<lua_Integer>(hit.ret));
        lua_setfield(state, -2, "ret");
        lua_pushinteger(state, static_cast<lua_Integer>(hit.arg0));
        lua_setfield(state, -2, "arg0");
        lua_pushinteger(state, static_cast<lua_Integer>(hit.arg1));
        lua_setfield(state, -2, "arg1");
        lua_pushinteger(state, static_cast<lua_Integer>(hit.arg2));
        lua_setfield(state, -2, "arg2");
        lua_pushstring(state, hit.before_bytes_hex.c_str());
        lua_setfield(state, -2, "before_bytes_hex");
        lua_pushstring(state, hit.after_bytes_hex.c_str());
        lua_setfield(state, -2, "after_bytes_hex");
        lua_rawseti(state, -2, static_cast<lua_Integer>(index + 1));
    }
    return 1;
}

// sd.debug.clear_write_hits(name?)
int LuaDebugClearWriteHits(lua_State* state) {
    const char* filter = nullptr;
    if (lua_gettop(state) >= 1 && !lua_isnil(state, 1)) {
        filter = luaL_checkstring(state, 1);
    }
    RuntimeDebug_ClearWriteHits(filter);
    return 0;
}

// sd.debug.read_bytes(address, count) -> string|nil
int LuaDebugReadBytes(lua_State* state) {
    const auto address = CheckLuaAddress(state, 1, "address");
    const auto count = CheckLuaTransferSize(state, 2, "count");

    std::vector<std::uint8_t> bytes;
    if (!TryReadLuaBytes(address, count, &bytes)) {
        lua_pushnil(state);
        return 1;
    }

    const auto hex_bytes = FormatLuaHexBytes(bytes.data(), bytes.size());
    lua_pushlstring(state, hex_bytes.c_str(), hex_bytes.size());
    return 1;
}

// sd.debug.read_string(address, max_len) -> string|nil
int LuaDebugReadString(lua_State* state) {
    const auto address = CheckLuaAddress(state, 1, "address");
    const auto max_length = CheckLuaTransferSize(state, 2, "max_len");

    auto& memory = ProcessMemory::Instance();
    const auto resolved_address = ResolveReadableLuaAddress(memory, address, 1);
    if (resolved_address == 0) {
        lua_pushnil(state);
        return 1;
    }

    std::string value;
    if (!memory.TryReadCString(resolved_address, max_length, &value)) {
        lua_pushnil(state);
        return 1;
    }

    lua_pushlstring(state, value.c_str(), value.size());
    return 1;
}

// sd.debug.search_bytes(start_addr, end_addr, hex_pattern) -> integer[]|nil
int LuaDebugSearchBytes(lua_State* state) {
    const auto requested_start = CheckLuaAddress(state, 1, "start_addr");
    const auto requested_end = CheckLuaAddress(state, 2, "end_addr");
    const char* hex_pattern = luaL_checkstring(state, 3);

    if (requested_end < requested_start) {
        return luaL_argerror(state, 2, "end_addr must be greater than or equal to start_addr");
    }

    size_t requested_range_size = 0;
    if (!TryComputeInclusiveRangeSize(requested_start, requested_end, &requested_range_size)) {
        return luaL_argerror(state, 2, "address range overflow");
    }
    if (requested_range_size > kMaxLuaDebugSearchRangeSize) {
        return luaL_argerror(state, 2, "address range exceeds the maximum search size");
    }

    std::vector<int> pattern;
    std::string parse_error;
    if (!TryParseLuaHexPattern(hex_pattern != nullptr ? hex_pattern : "", &pattern, &parse_error)) {
        return luaL_argerror(state, 3, parse_error.c_str());
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t resolved_start = 0;
    uintptr_t resolved_end = 0;
    bool start_translated = false;
    bool end_translated = false;
    if (!TryResolveLuaReadableAddress(memory, requested_start, 1, &resolved_start, &start_translated) ||
        !TryResolveLuaReadableAddress(memory, requested_end, 1, &resolved_end, &end_translated) ||
        resolved_end < resolved_start) {
        lua_pushnil(state);
        return 1;
    }

    size_t resolved_range_size = 0;
    if (!TryComputeInclusiveRangeSize(resolved_start, resolved_end, &resolved_range_size)) {
        lua_pushnil(state);
        return 1;
    }
    if (resolved_range_size < pattern.size()) {
        lua_createtable(state, 0, 0);
        return 1;
    }
    if (resolved_range_size > kMaxLuaDebugSearchRangeSize) {
        return luaL_argerror(state, 2, "resolved search range exceeds the maximum search size");
    }

    const auto preserve_requested_space =
        start_translated == end_translated &&
        (!start_translated || (resolved_start - requested_start) == (resolved_end - requested_end));

    lua_createtable(state, 0, 0);
    lua_Integer next_index = 1;

    uintptr_t current = resolved_start;
    while (current <= resolved_end) {
        MemoryRegionInfo region{};
        if (!memory.RefreshRegion(current, &region)) {
            break;
        }

        if (region.end == 0 || region.end <= current) {
            break;
        }

        const auto region_last_address = static_cast<uintptr_t>(region.end - 1);
        const auto scan_end = (std::min)(region_last_address, resolved_end);
        if (region.committed && !region.guarded && !region.no_access && region.readable && scan_end >= current) {
            std::vector<std::uint8_t> carry;
            uintptr_t chunk_address = current;
            while (chunk_address <= scan_end) {
                const auto remaining = static_cast<size_t>(scan_end - chunk_address + 1);
                const auto bytes_to_read = (std::min)(remaining, kLuaDebugSearchChunkSize);

                std::vector<std::uint8_t> buffer(carry.size() + bytes_to_read);
                if (!carry.empty()) {
                    std::memcpy(buffer.data(), carry.data(), carry.size());
                }
                if (!memory.TryRead(chunk_address, buffer.data() + carry.size(), bytes_to_read)) {
                    break;
                }

                uintptr_t buffer_base = chunk_address;
                if (!carry.empty() && !TrySubtractOffset(chunk_address, carry.size(), &buffer_base)) {
                    break;
                }

                if (buffer.size() >= pattern.size()) {
                    const auto max_offset = buffer.size() - pattern.size();
                    for (size_t offset = 0; offset <= max_offset; ++offset) {
                        if (!PatternMatchesAt(buffer.data(), buffer.size(), offset, pattern)) {
                            continue;
                        }

                        uintptr_t match_resolved = 0;
                        if (!TryAddOffset(buffer_base, offset, &match_resolved)) {
                            continue;
                        }

                        uintptr_t match_address = match_resolved;
                        if (preserve_requested_space) {
                            const auto match_delta = static_cast<size_t>(match_resolved - resolved_start);
                            if (!TryAddOffset(requested_start, match_delta, &match_address)) {
                                continue;
                            }
                        }

                        lua_pushinteger(state, static_cast<lua_Integer>(match_address));
                        lua_rawseti(state, -2, next_index++);
                    }
                }

                if (pattern.size() > 1) {
                    const auto carry_size = (std::min)(pattern.size() - 1, buffer.size());
                    carry.assign(
                        buffer.end() - static_cast<std::ptrdiff_t>(carry_size),
                        buffer.end());
                } else {
                    carry.clear();
                }

                uintptr_t next_chunk_address = 0;
                if (!TryAddOffset(chunk_address, bytes_to_read, &next_chunk_address) ||
                    next_chunk_address <= chunk_address) {
                    break;
                }
                chunk_address = next_chunk_address;
            }
        }

        current = region.end;
    }

    return 1;
}

// sd.debug.query_memory(address) -> table|nil
int LuaDebugQueryMemory(lua_State* state) {
    const auto address = CheckLuaAddress(state, 1, "address");
    auto& memory = ProcessMemory::Instance();
    uintptr_t resolved_address = 0;
    bool translated = false;
    if (!TryResolveLuaReadableAddress(memory, address, 1, &resolved_address, &translated)) {
        resolved_address = memory.ResolveGameAddressOrZero(address);
        if (resolved_address == 0) {
            lua_pushnil(state);
            return 1;
        }
        translated = resolved_address != address;
    }

    MemoryRegionInfo region{};
    if (!memory.RefreshRegion(resolved_address, &region)) {
        lua_pushnil(state);
        return 1;
    }

    lua_createtable(state, 0, 15);
    lua_pushinteger(state, static_cast<lua_Integer>(address));
    lua_setfield(state, -2, "requested_address");
    lua_pushinteger(state, static_cast<lua_Integer>(resolved_address));
    lua_setfield(state, -2, "resolved_address");
    lua_pushboolean(state, translated ? 1 : 0);
    lua_setfield(state, -2, "translated");
    lua_pushinteger(state, static_cast<lua_Integer>(region.base));
    lua_setfield(state, -2, "base");
    lua_pushinteger(state, static_cast<lua_Integer>(region.end));
    lua_setfield(state, -2, "end");
    lua_pushinteger(state, static_cast<lua_Integer>(region.state));
    lua_setfield(state, -2, "state");
    lua_pushinteger(state, static_cast<lua_Integer>(region.protect));
    lua_setfield(state, -2, "protect");
    lua_pushinteger(state, static_cast<lua_Integer>(region.type));
    lua_setfield(state, -2, "type");
    lua_pushboolean(state, region.committed ? 1 : 0);
    lua_setfield(state, -2, "committed");
    lua_pushboolean(state, region.guarded ? 1 : 0);
    lua_setfield(state, -2, "guarded");
    lua_pushboolean(state, region.no_access ? 1 : 0);
    lua_setfield(state, -2, "no_access");
    lua_pushboolean(state, region.readable ? 1 : 0);
    lua_setfield(state, -2, "readable");
    lua_pushboolean(state, region.writable ? 1 : 0);
    lua_setfield(state, -2, "writable");
    lua_pushboolean(state, region.executable ? 1 : 0);
    lua_setfield(state, -2, "executable");
    lua_pushinteger(state, static_cast<lua_Integer>(resolved_address));
    lua_setfield(state, -2, "address");
    lua_pushinteger(state, static_cast<lua_Integer>(region.end > region.base ? (region.end - region.base) : 0));
    lua_setfield(state, -2, "size");
    return 1;
}

// sd.debug.dump_struct(address, field_defs) -> table
int LuaDebugDumpStruct(lua_State* state) {
    const auto address = CheckLuaAddress(state, 1, "address");
    luaL_checktype(state, 2, LUA_TTABLE);

    const auto field_defs_index = lua_absindex(state, 2);
    const auto field_count = lua_rawlen(state, field_defs_index);
    lua_createtable(state, 0, static_cast<int>(field_count));

    for (lua_Integer field_index = 1; field_index <= static_cast<lua_Integer>(field_count); ++field_index) {
        lua_rawgeti(state, field_defs_index, field_index);
        if (!lua_istable(state, -1)) {
            return luaL_error(
                state,
                "sd.debug.dump_struct field_defs[%d] must be a table",
                static_cast<int>(field_index));
        }

        lua_getfield(state, -1, "name");
        if (!lua_isstring(state, -1)) {
            return luaL_error(
                state,
                "sd.debug.dump_struct field_defs[%d].name must be a string",
                static_cast<int>(field_index));
        }
        const std::string field_name = lua_tostring(state, -1);
        lua_pop(state, 1);

        lua_getfield(state, -1, "offset");
        if (!lua_isinteger(state, -1)) {
            return luaL_error(
                state,
                "sd.debug.dump_struct field_defs[%d].offset must be an integer",
                static_cast<int>(field_index));
        }
        const auto offset_value = lua_tointeger(state, -1);
        if (offset_value < 0 ||
            static_cast<unsigned long long>(offset_value) >
                static_cast<unsigned long long>((std::numeric_limits<size_t>::max)())) {
            return luaL_error(
                state,
                "sd.debug.dump_struct field_defs[%d].offset is out of range",
                static_cast<int>(field_index));
        }
        const auto offset = static_cast<size_t>(offset_value);
        lua_pop(state, 1);

        lua_getfield(state, -1, "type");
        if (!lua_isstring(state, -1)) {
            return luaL_error(
                state,
                "sd.debug.dump_struct field_defs[%d].type must be a string",
                static_cast<int>(field_index));
        }
        const std::string field_type_name = lua_tostring(state, -1);
        lua_pop(state, 1);
        lua_pop(state, 1);

        LuaDebugFieldType field_type = LuaDebugFieldType::U8;
        if (!TryParseLuaDebugFieldType(field_type_name, &field_type)) {
            return luaL_error(
                state,
                "sd.debug.dump_struct field_defs[%d].type '%s' is unsupported",
                static_cast<int>(field_index),
                field_type_name.c_str());
        }

        uintptr_t field_address = 0;
        if (!TryAddOffset(address, offset, &field_address)) {
            lua_pushnil(state);
            lua_setfield(state, -2, field_name.c_str());
            continue;
        }

        PushLuaAbsoluteValueByType(state, field_address, field_type);
        lua_setfield(state, -2, field_name.c_str());
    }

    return 1;
}

// sd.debug.dump_vtable(object_or_vtable_address, count, treat_as_object=true) -> table|nil
int LuaDebugDumpVtable(lua_State* state) {
    const auto source_address = CheckLuaAddress(state, 1, "object_or_vtable_address");
    const auto count = CheckLuaUnsignedInteger<size_t>(state, 2, "count");
    if (count == 0) {
        return luaL_argerror(state, 2, "count must be greater than zero");
    }
    if (count > 512) {
        return luaL_argerror(state, 2, "count exceeds the maximum supported entry count of 512");
    }

    bool treat_as_object = true;
    if (lua_gettop(state) >= 3 && !lua_isnil(state, 3)) {
        treat_as_object = lua_toboolean(state, 3) != 0;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t vtable_address = 0;
    if (treat_as_object) {
        if (!TryReadLuaAbsoluteValue(source_address, &vtable_address) || vtable_address == 0) {
            lua_pushnil(state);
            return 1;
        }
    } else {
        vtable_address = ResolveReadableLuaAddress(memory, source_address, sizeof(uintptr_t));
        if (vtable_address == 0) {
            lua_pushnil(state);
            return 1;
        }
    }

    lua_createtable(state, 0, 4);
    lua_pushinteger(state, static_cast<lua_Integer>(source_address));
    lua_setfield(state, -2, "source_address");
    lua_pushinteger(state, static_cast<lua_Integer>(vtable_address));
    lua_setfield(state, -2, "vtable_address");
    lua_pushboolean(state, treat_as_object ? 1 : 0);
    lua_setfield(state, -2, "treat_as_object");

    lua_createtable(state, static_cast<int>(count), 0);
    for (size_t index = 0; index < count; ++index) {
        uintptr_t entry_address = 0;
        uintptr_t entry_value = 0;
        if (!TryAddOffset(vtable_address, index * sizeof(uintptr_t), &entry_address) ||
            !TryReadLuaAbsoluteValue(entry_address, &entry_value)) {
            lua_pushnil(state);
        } else {
            lua_pushinteger(state, static_cast<lua_Integer>(entry_value));
        }
        lua_rawseti(state, -2, static_cast<lua_Integer>(index + 1));
    }
    lua_setfield(state, -2, "entries");
    return 1;
}

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

// sd.debug.call_cdecl_u32_u32(function_address, arg0, arg1) -> boolean
int LuaDebugCallCdeclU32U32(lua_State* state) {
    const auto requested_function_address = CheckLuaAddress(state, 1, "function_address");
    const auto arg0 = CheckLuaUnsignedInteger<std::uint32_t>(state, 2, "arg0");
    const auto arg1 = CheckLuaUnsignedInteger<std::uint32_t>(state, 3, "arg1");

    auto& memory = ProcessMemory::Instance();
    const auto function_address = ResolveExecutableLuaAddress(memory, requested_function_address);
    if (function_address == 0) {
        lua_pushboolean(state, 0);
        return 1;
    }

    using CdeclU32U32Fn = void(__cdecl*)(std::uint32_t, std::uint32_t);
    auto* fn = reinterpret_cast<CdeclU32U32Fn>(function_address);
    bool ok = false;
    __try {
        fn(arg0, arg1);
        ok = true;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        ok = false;
    }

    lua_pushboolean(state, ok ? 1 : 0);
    return 1;
}

// sd.debug.copy_bytes(src_addr, dst_addr, count) -> boolean
int LuaDebugCopyBytes(lua_State* state) {
    const auto source_address = CheckLuaAddress(state, 1, "src_addr");
    const auto destination_address = CheckLuaAddress(state, 2, "dst_addr");
    const auto count = CheckLuaTransferSize(state, 3, "count");

    std::vector<std::uint8_t> bytes;
    if (!TryReadLuaBytes(source_address, count, &bytes)) {
        lua_pushboolean(state, 0);
        return 1;
    }

    auto& memory = ProcessMemory::Instance();
    const auto resolved_destination = ResolveWritableLuaAddress(memory, destination_address, count);
    if (resolved_destination == 0) {
        lua_pushboolean(state, 0);
        return 1;
    }

    lua_pushboolean(state, memory.TryWrite(resolved_destination, bytes.data(), bytes.size()) ? 1 : 0);
    return 1;
}

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
