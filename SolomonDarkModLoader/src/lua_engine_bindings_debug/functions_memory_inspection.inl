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

