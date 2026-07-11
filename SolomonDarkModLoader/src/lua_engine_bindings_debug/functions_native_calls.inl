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

// sd.debug.resolve_native_primary_spell_stats(progression_runtime, primary_entry, combo_entry) -> table
int LuaDebugResolveNativePrimarySpellStats(lua_State* state) {
    const auto progression_runtime =
        CheckLuaAddress(state, 1, "progression_runtime");
    const auto primary_entry =
        CheckLuaSignedInteger<int>(state, 2, "primary_entry");
    const auto combo_entry =
        CheckLuaSignedInteger<int>(state, 3, "combo_entry");

    lua_createtable(state, 0, 18);
    lua_pushinteger(state, static_cast<lua_Integer>(progression_runtime));
    lua_setfield(state, -2, "progression_runtime");
    lua_pushinteger(state, static_cast<lua_Integer>(primary_entry));
    lua_setfield(state, -2, "primary_entry");
    lua_pushinteger(state, static_cast<lua_Integer>(combo_entry));
    lua_setfield(state, -2, "combo_entry");

    NativePrimarySpellSelection selection{};
    if (!TryResolveNativePrimarySelectionFromPair(
            primary_entry,
            combo_entry,
            &selection)) {
        lua_pushboolean(state, 0);
        lua_setfield(state, -2, "resolved");
        lua_pushstring(state, "selection_unresolved");
        lua_setfield(state, -2, "error");
        return 1;
    }

    lua_pushinteger(state, static_cast<lua_Integer>(selection.build_skill_id));
    lua_setfield(state, -2, "build_skill_id");
    lua_pushboolean(state, selection.pure_primary ? 1 : 0);
    lua_setfield(state, -2, "pure_primary");
    lua_pushboolean(state, selection.per_second_mana ? 1 : 0);
    lua_setfield(state, -2, "per_second_mana");

    NativePrimarySpellStats stats{};
    std::string error_message;
    const bool resolved =
        TryResolveNativePrimarySpellStats(
            progression_runtime,
            selection,
            &stats,
            &error_message);
    lua_pushboolean(state, resolved ? 1 : 0);
    lua_setfield(state, -2, "resolved");
    lua_pushlstring(state, error_message.c_str(), error_message.size());
    lua_setfield(state, -2, "error");
    if (!resolved) {
        return 1;
    }

    lua_pushinteger(state, static_cast<lua_Integer>(stats.selection.build_skill_id));
    lua_setfield(state, -2, "resolved_build_skill_id");
    lua_pushinteger(state, static_cast<lua_Integer>(stats.current_spell_id));
    lua_setfield(state, -2, "current_spell_id");
    lua_pushinteger(state, static_cast<lua_Integer>(stats.progression_level));
    lua_setfield(state, -2, "progression_level");
    lua_pushinteger(state, static_cast<lua_Integer>(stats.output_values_address));
    lua_setfield(state, -2, "output_values_address");
    lua_pushinteger(state, static_cast<lua_Integer>(stats.output_count));
    lua_setfield(state, -2, "output_count");
    lua_pushnumber(state, static_cast<lua_Number>(stats.damage));
    lua_setfield(state, -2, "damage");
    lua_pushnumber(state, static_cast<lua_Number>(stats.secondary_damage));
    lua_setfield(state, -2, "secondary_damage");
    lua_pushboolean(state, stats.secondary_damage_available ? 1 : 0);
    lua_setfield(state, -2, "secondary_damage_available");
    lua_pushnumber(state, static_cast<lua_Number>(stats.mana_cost));
    lua_setfield(state, -2, "mana_cost");
    lua_pushboolean(state, stats.mana_cost_available ? 1 : 0);
    lua_setfield(state, -2, "mana_cost_available");
    lua_pushnumber(state, static_cast<lua_Number>(stats.mana_spend_cost));
    lua_setfield(state, -2, "mana_spend_cost");
    lua_pushboolean(state, stats.mana_spend_cost_available ? 1 : 0);
    lua_setfield(state, -2, "mana_spend_cost_available");
    lua_pushnumber(state, static_cast<lua_Number>(stats.mana_output_scale));
    lua_setfield(state, -2, "mana_output_scale");
    lua_pushboolean(state, stats.mana_output_scaled ? 1 : 0);
    lua_setfield(state, -2, "mana_output_scaled");
    lua_pushinteger(state, static_cast<lua_Integer>(stats.builder_seh_code));
    lua_setfield(state, -2, "builder_seh_code");

    lua_createtable(state, static_cast<int>(stats.output_count), 0);
    auto& memory = ProcessMemory::Instance();
    const auto output_limit = (std::min)(stats.output_count, static_cast<std::size_t>(16));
    for (std::size_t index = 0; index < output_limit; ++index) {
        float value = 0.0f;
        if (stats.output_values_address != 0 &&
            memory.TryReadValue(
                stats.output_values_address + index * sizeof(float),
                &value)) {
            lua_pushnumber(state, static_cast<lua_Number>(value));
        } else {
            lua_pushnil(state);
        }
        lua_rawseti(state, -2, static_cast<lua_Integer>(index + 1));
    }
    lua_setfield(state, -2, "outputs");
    return 1;
}
