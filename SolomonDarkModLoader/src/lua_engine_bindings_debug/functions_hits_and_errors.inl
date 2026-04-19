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

