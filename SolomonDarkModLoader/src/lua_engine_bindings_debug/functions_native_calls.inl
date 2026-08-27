// sd.debug.queue_nested_sack_inventory_fixture(potion_slot, stack_count)
//     -> boolean, string
// The native constructors and inventory transfers run after this Lua callback.
int LuaDebugQueueNestedSackInventoryFixture(lua_State* state) {
    const auto potion_slot =
        CheckLuaSignedInteger<std::int32_t>(state, 1, "potion_slot");
    const auto stack_count =
        CheckLuaSignedInteger<std::int32_t>(state, 2, "stack_count");

    std::string error_message;
    const bool queued = QueueNestedSackInventoryFixture(
        potion_slot,
        stack_count,
        &error_message);
    lua_pushboolean(state, queued ? 1 : 0);
    lua_pushlstring(state, error_message.c_str(), error_message.size());
    return 2;
}

bool NativeCallStackBalanced(
    const char* binding_name,
    const X86NativeCallResult& call) {
    if (call.stack_delta_bytes == 0) {
        return true;
    }
    Log(
        std::string("[lua][debug] ") + binding_name +
        " rejected a native call with x86 stack delta " +
        std::to_string(call.stack_delta_bytes) + ".");
    return false;
}

// sd.debug.call_thiscall_u32(function_address, this_ptr, arg0) -> boolean
int LuaDebugCallThiscallU32(lua_State* state) {
    const auto requested_function_address = CheckLuaAddress(state, 1, "function_address");
    const auto this_ptr = CheckLuaAddress(state, 2, "this_ptr");
    const auto arg0 = CheckLuaUnsignedInteger<std::uint32_t>(state, 3, "arg0");

    auto& memory = ProcessMemory::Instance();
    const auto function_address = RequireExecutableLuaAddress(memory, requested_function_address);
    if (function_address == 0 || this_ptr == 0) {
        lua_pushboolean(state, 0);
        return 1;
    }

    X86NativeCallResult call;
    bool completed = false;
    __try {
        call = InvokeX86ThiscallU32(function_address, this_ptr, arg0);
        completed = true;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        completed = false;
    }

    const bool ok =
        completed && NativeCallStackBalanced("call_thiscall_u32", call);
    lua_pushboolean(state, ok ? 1 : 0);
    return 1;
}

// sd.debug.call_thiscall_u32_ret_u32(function_address, this_ptr, arg0) -> integer|nil
int LuaDebugCallThiscallU32RetU32(lua_State* state) {
    const auto requested_function_address = CheckLuaAddress(state, 1, "function_address");
    const auto this_ptr = CheckLuaAddress(state, 2, "this_ptr");
    const auto arg0 = CheckLuaUnsignedInteger<std::uint32_t>(state, 3, "arg0");

    auto& memory = ProcessMemory::Instance();
    const auto function_address = RequireExecutableLuaAddress(memory, requested_function_address);
    if (function_address == 0 || this_ptr == 0) {
        lua_pushnil(state);
        return 1;
    }

    X86NativeCallResult call;
    bool completed = false;
    __try {
        call = InvokeX86ThiscallU32(function_address, this_ptr, arg0);
        completed = true;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        completed = false;
    }

    if (!completed ||
        !NativeCallStackBalanced("call_thiscall_u32_ret_u32", call) ||
        call.result == 0) {
        lua_pushnil(state);
        return 1;
    }

    lua_pushinteger(state, static_cast<lua_Integer>(call.result));
    return 1;
}

// sd.debug.call_thiscall_ret_u32(function_address, this_ptr) -> integer|nil
int LuaDebugCallThiscallRetU32(lua_State* state) {
    const auto requested_function_address = CheckLuaAddress(state, 1, "function_address");
    const auto this_ptr = CheckLuaAddress(state, 2, "this_ptr");

    auto& memory = ProcessMemory::Instance();
    const auto function_address = RequireExecutableLuaAddress(memory, requested_function_address);
    if (function_address == 0 || this_ptr == 0) {
        lua_pushnil(state);
        return 1;
    }

    X86NativeCallResult call;
    bool completed = false;
    __try {
        call = InvokeX86Thiscall(function_address, this_ptr);
        completed = true;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        completed = false;
    }

    if (!completed ||
        !NativeCallStackBalanced("call_thiscall_ret_u32", call)) {
        lua_pushnil(state);
        return 1;
    }
    lua_pushinteger(state, static_cast<lua_Integer>(call.result));
    return 1;
}

// sd.debug.open_stock_map_picker_for_capture() -> boolean, string
// This is an evidence-only seam. It calls the already-installed MapPicker
// trampoline, not the loader's authority hook, and performs no alternate dispatch.
int LuaDebugOpenStockMapPickerForCapture(lua_State* state) {
    std::string error_message;
    const bool opened = OpenStockMapPickerForDebugCapture(&error_message);
    lua_pushboolean(state, opened ? 1 : 0);
    lua_pushlstring(
        state,
        error_message.c_str(),
        error_message.size());
    return 2;
}

// sd.debug.queue_native_poison_behavior_probe(participant_id, duration_ticks,
//     damage_per_tick, source_slot) -> boolean, string
// participant_id=0 targets the local player. The native factory/OnApply work
// is deferred until after the Lua callback returns to avoid re-entering Lua
// through retail object-factory hooks.
int LuaDebugQueueNativePoisonBehaviorProbe(lua_State* state) {
    const auto participant_id =
        CheckLuaUnsignedInteger<std::uint64_t>(state, 1, "participant_id");
    const auto duration_ticks =
        CheckLuaSignedInteger<std::int32_t>(state, 2, "duration_ticks");
    const auto damage_per_tick =
        static_cast<float>(luaL_checknumber(state, 3));
    const auto source_slot =
        CheckLuaSignedInteger<std::int8_t>(state, 4, "source_slot");

    std::string error_message;
    const bool queued = QueueNativePoisonBehaviorProbe(
        participant_id,
        duration_ticks,
        damage_per_tick,
        source_slot,
        &error_message);
    lua_pushboolean(state, queued ? 1 : 0);
    lua_pushlstring(state, error_message.c_str(), error_message.size());
    return 2;
}

// sd.debug.queue_native_magic_hit_behavior_probe(projectile_damage,
//     magic_damage, attempts, target_participant_id=0, poison_damage=0)
//     -> boolean, string, integer
// The retail magic-hit work is deferred until after the Lua callback returns.
int LuaDebugQueueNativeMagicHitBehaviorProbe(lua_State* state) {
    const auto projectile_damage =
        static_cast<float>(luaL_checknumber(state, 1));
    const auto magic_damage = static_cast<float>(luaL_checknumber(state, 2));
    const auto attempts =
        CheckLuaUnsignedInteger<std::uint32_t>(state, 3, "attempts");
    const auto target_participant_integer = luaL_optinteger(state, 4, 0);
    if (target_participant_integer < 0) {
        return luaL_error(state, "target_participant_id must be non-negative");
    }
    const auto target_participant_id =
        static_cast<std::uint64_t>(target_participant_integer);
    const auto poison_damage =
        static_cast<float>(luaL_optnumber(state, 5, 0.0));

    std::string error_message;
    std::uint64_t request_serial = 0;
    const bool queued = QueueNativeMagicHitBehaviorProbe(
        projectile_damage,
        magic_damage,
        poison_damage,
        attempts,
        target_participant_id,
        &request_serial,
        &error_message);
    lua_pushboolean(state, queued ? 1 : 0);
    lua_pushlstring(state, error_message.c_str(), error_message.size());
    lua_pushinteger(state, static_cast<lua_Integer>(request_serial));
    return 3;
}

// sd.debug.get_native_magic_hit_behavior_probe_result(request_serial)
//     -> boolean, boolean, number, number, string
int LuaDebugGetNativeMagicHitBehaviorProbeResult(lua_State* state) {
    const auto request_serial =
        CheckLuaUnsignedInteger<std::uint64_t>(state, 1, "request_serial");
    bool completed = false;
    bool success = false;
    float hp_before = 0.0f;
    float hp_after = 0.0f;
    std::string error_message;
    if (!GetNativeMagicHitBehaviorProbeResult(
            request_serial,
            &completed,
            &success,
            &hp_before,
            &hp_after,
            &error_message)) {
        lua_pushboolean(state, 0);
        lua_pushboolean(state, 0);
        lua_pushnumber(state, 0.0);
        lua_pushnumber(state, 0.0);
        lua_pushliteral(state, "invalid request serial");
        return 5;
    }
    lua_pushboolean(state, completed ? 1 : 0);
    lua_pushboolean(state, success ? 1 : 0);
    lua_pushnumber(state, static_cast<lua_Number>(hp_before));
    lua_pushnumber(state, static_cast<lua_Number>(hp_after));
    lua_pushlstring(state, error_message.c_str(), error_message.size());
    return 5;
}

// sd.debug.queue_native_enemy_death_probe(actor_address,
//     expected_config_address, restore_config_address) -> boolean, string, integer
// The native death presenter runs after Lua returns so synchronous event filters
// can acquire the Lua engine and inspect the stock drop selector.
int LuaDebugQueueNativeEnemyDeathProbe(lua_State* state) {
    const auto actor_address = CheckLuaAddress(state, 1, "actor_address");
    const auto expected_config_address =
        CheckLuaAddress(state, 2, "expected_config_address");
    const auto restore_config_address =
        CheckLuaAddress(state, 3, "restore_config_address");

    std::string error_message;
    std::uint64_t request_serial = 0;
    const bool queued = QueueNativeEnemyDeathProbe(
        actor_address,
        expected_config_address,
        restore_config_address,
        &request_serial,
        &error_message);
    lua_pushboolean(state, queued ? 1 : 0);
    lua_pushlstring(state, error_message.c_str(), error_message.size());
    lua_pushinteger(state, static_cast<lua_Integer>(request_serial));
    return 3;
}

// sd.debug.get_native_enemy_death_probe_result(request_serial)
//     -> boolean, boolean, integer, boolean, string
int LuaDebugGetNativeEnemyDeathProbeResult(lua_State* state) {
    const auto request_serial =
        CheckLuaUnsignedInteger<std::uint64_t>(state, 1, "request_serial");
    bool completed = false;
    bool success = false;
    std::uint32_t exception_code = 0;
    bool config_restored = false;
    std::string error_message;
    if (!GetNativeEnemyDeathProbeResult(
            request_serial,
            &completed,
            &success,
            &exception_code,
            &config_restored,
            &error_message)) {
        lua_pushboolean(state, 0);
        lua_pushboolean(state, 0);
        lua_pushinteger(state, 0);
        lua_pushboolean(state, 0);
        lua_pushliteral(state, "invalid request serial");
        return 5;
    }
    lua_pushboolean(state, completed ? 1 : 0);
    lua_pushboolean(state, success ? 1 : 0);
    lua_pushinteger(state, static_cast<lua_Integer>(exception_code));
    lua_pushboolean(state, config_restored ? 1 : 0);
    lua_pushlstring(state, error_message.c_str(), error_message.size());
    return 5;
}

// sd.debug.queue_native_experience_gain_probe(amount, apply_native_scaling)
//     -> boolean, string, integer
// The native XP seam runs after Lua returns so its synchronous filter can
// acquire the Lua engine instead of failing open on re-entry.
int LuaDebugQueueNativeExperienceGainProbe(lua_State* state) {
    const auto amount = static_cast<float>(luaL_checknumber(state, 1));
    luaL_checktype(state, 2, LUA_TBOOLEAN);
    const bool apply_native_scaling = lua_toboolean(state, 2) != 0;

    std::string error_message;
    std::uint64_t request_serial = 0;
    const bool queued = QueueNativeExperienceGainProbe(
        amount,
        apply_native_scaling,
        &request_serial,
        &error_message);
    lua_pushboolean(state, queued ? 1 : 0);
    lua_pushlstring(state, error_message.c_str(), error_message.size());
    lua_pushinteger(state, static_cast<lua_Integer>(request_serial));
    return 3;
}

// sd.debug.get_native_experience_gain_probe_result(request_serial)
//     -> boolean, boolean, number, number, integer, string
int LuaDebugGetNativeExperienceGainProbeResult(lua_State* state) {
    const auto request_serial =
        CheckLuaUnsignedInteger<std::uint64_t>(state, 1, "request_serial");
    bool completed = false;
    bool success = false;
    float xp_before = 0.0f;
    float xp_after = 0.0f;
    std::uint32_t exception_code = 0;
    std::string error_message;
    if (!GetNativeExperienceGainProbeResult(
            request_serial,
            &completed,
            &success,
            &xp_before,
            &xp_after,
            &exception_code,
            &error_message)) {
        lua_pushboolean(state, 0);
        lua_pushboolean(state, 0);
        lua_pushnumber(state, 0.0);
        lua_pushnumber(state, 0.0);
        lua_pushinteger(state, 0);
        lua_pushliteral(state, "invalid request serial");
        return 6;
    }
    lua_pushboolean(state, completed ? 1 : 0);
    lua_pushboolean(state, success ? 1 : 0);
    lua_pushnumber(state, static_cast<lua_Number>(xp_before));
    lua_pushnumber(state, static_cast<lua_Number>(xp_after));
    lua_pushinteger(state, static_cast<lua_Integer>(exception_code));
    lua_pushlstring(state, error_message.c_str(), error_message.size());
    return 6;
}

// sd.debug.queue_native_staff_effect_probe(source_actor, target_actor, variant)
//     -> boolean, string, integer
// The resolver applies damage and can allocate native effects, so it must run
// after the current Lua callback has returned to the gameplay action pump.
int LuaDebugQueueNativeStaffEffectProbe(lua_State* state) {
    const auto source_actor =
        CheckLuaAddress(state, 1, "source_actor");
    const auto target_actor =
        CheckLuaAddress(state, 2, "target_actor");
    const auto variant =
        CheckLuaUnsignedInteger<std::uint32_t>(state, 3, "variant");

    std::string error_message;
    std::uint64_t request_serial = 0;
    const bool queued = QueueNativeStaffEffectProbe(
        source_actor,
        target_actor,
        variant,
        &request_serial,
        &error_message);
    lua_pushboolean(state, queued ? 1 : 0);
    lua_pushlstring(state, error_message.c_str(), error_message.size());
    lua_pushinteger(state, static_cast<lua_Integer>(request_serial));
    return 3;
}

// sd.debug.get_native_staff_effect_probe_result(request_serial)
//     -> boolean, boolean, number, number, string
int LuaDebugGetNativeStaffEffectProbeResult(lua_State* state) {
    const auto request_serial =
        CheckLuaUnsignedInteger<std::uint64_t>(state, 1, "request_serial");
    bool completed = false;
    bool success = false;
    float hp_before = 0.0f;
    float hp_after = 0.0f;
    std::string error_message;
    if (!GetNativeStaffEffectProbeResult(
            request_serial,
            &completed,
            &success,
            &hp_before,
            &hp_after,
            &error_message)) {
        lua_pushboolean(state, 0);
        lua_pushboolean(state, 0);
        lua_pushnumber(state, 0.0);
        lua_pushnumber(state, 0.0);
        lua_pushliteral(state, "invalid request serial");
        return 5;
    }
    lua_pushboolean(state, completed ? 1 : 0);
    lua_pushboolean(state, success ? 1 : 0);
    lua_pushnumber(state, static_cast<lua_Number>(hp_before));
    lua_pushnumber(state, static_cast<lua_Number>(hp_after));
    lua_pushlstring(state, error_message.c_str(), error_message.size());
    return 5;
}

// sd.debug.call_thiscall_out_f32x4_u32(function_address, this_ptr, arg0) -> table|nil
int LuaDebugCallThiscallOutF32x4U32(lua_State* state) {
    const auto requested_function_address = CheckLuaAddress(state, 1, "function_address");
    const auto this_ptr = CheckLuaAddress(state, 2, "this_ptr");
    const auto arg0 = CheckLuaUnsignedInteger<std::uint32_t>(state, 3, "arg0");

    auto& memory = ProcessMemory::Instance();
    const auto function_address = RequireExecutableLuaAddress(memory, requested_function_address);
    if (function_address == 0 || this_ptr == 0) {
        lua_pushnil(state);
        return 1;
    }

    float result[4] = {};
    X86NativeCallResult call;
    bool completed = false;
    __try {
        call = InvokeX86ThiscallU32U32(
            function_address,
            this_ptr,
            reinterpret_cast<std::uintptr_t>(result),
            arg0);
        completed = true;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        completed = false;
    }

    if (!completed ||
        !NativeCallStackBalanced("call_thiscall_out_f32x4_u32", call)) {
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
    const auto function_address = RequireExecutableLuaAddress(memory, requested_function_address);
    if (function_address == 0) {
        lua_pushnil(state);
        return 1;
    }

    X86NativeCallResult call;
    bool completed = false;
    __try {
        call = InvokeX86CdeclU32(function_address, arg0);
        completed = true;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        completed = false;
    }

    if (!completed ||
        !NativeCallStackBalanced("call_cdecl_u32_ret_u32", call) ||
        call.result == 0) {
        lua_pushnil(state);
        return 1;
    }

    lua_pushinteger(state, static_cast<lua_Integer>(call.result));
    return 1;
}

// sd.debug.call_stdcall_u32_u32_ret_u32(function_address, arg0, arg1) -> integer|nil
// This exists for read-only probes of retail helpers whose RET imm16 proves
// callee cleanup. It does not dispatch gameplay work on its own.
int LuaDebugCallStdcallU32U32RetU32(lua_State* state) {
    const auto requested_function_address = CheckLuaAddress(state, 1, "function_address");
    const auto arg0 = CheckLuaUnsignedInteger<std::uint32_t>(state, 2, "arg0");
    const auto arg1 = CheckLuaUnsignedInteger<std::uint32_t>(state, 3, "arg1");

    auto& memory = ProcessMemory::Instance();
    const auto function_address = RequireExecutableLuaAddress(memory, requested_function_address);
    if (function_address == 0) {
        lua_pushnil(state);
        return 1;
    }

    X86NativeCallResult call;
    bool completed = false;
    __try {
        call = InvokeX86StdcallU32U32(function_address, arg0, arg1);
        completed = true;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        completed = false;
    }

    if (!completed ||
        !NativeCallStackBalanced("call_stdcall_u32_u32_ret_u32", call)) {
        lua_pushnil(state);
        return 1;
    }

    lua_pushinteger(state, static_cast<lua_Integer>(call.result));
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

// sd.debug.resolve_native_secondary_mana_stats(progression_runtime, entry_index) -> table
int LuaDebugResolveNativeSecondaryManaStats(lua_State* state) {
    const auto progression_runtime =
        CheckLuaAddress(state, 1, "progression_runtime");
    const auto entry_index =
        CheckLuaSignedInteger<int>(state, 2, "entry_index");

    lua_createtable(state, 0, 8);
    lua_pushinteger(state, static_cast<lua_Integer>(progression_runtime));
    lua_setfield(state, -2, "progression_runtime");
    lua_pushinteger(state, static_cast<lua_Integer>(entry_index));
    lua_setfield(state, -2, "entry_index");

    NativeSecondarySpellManaStats stats{};
    std::string error_message;
    const bool resolved = TryResolveNativeSecondarySpellManaStats(
        progression_runtime,
        entry_index,
        &stats,
        &error_message);
    lua_pushboolean(state, resolved ? 1 : 0);
    lua_setfield(state, -2, "resolved");
    lua_pushlstring(state, error_message.c_str(), error_message.size());
    lua_setfield(state, -2, "error");
    lua_pushinteger(state, static_cast<lua_Integer>(stats.progression_level));
    lua_setfield(state, -2, "progression_level");
    lua_pushnumber(state, static_cast<lua_Number>(stats.base_cost));
    lua_setfield(state, -2, "base_cost");
    lua_pushnumber(state, static_cast<lua_Number>(stats.spend_cost));
    lua_setfield(state, -2, "spend_cost");
    lua_pushinteger(state, static_cast<lua_Integer>(stats.resolver_seh_code));
    lua_setfield(state, -2, "resolver_seh_code");
    return 1;
}
