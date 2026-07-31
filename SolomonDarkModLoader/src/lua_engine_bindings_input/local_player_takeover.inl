int LuaInputSetLocalPlayerTakeover(lua_State* state) {
    auto* mod = GetLoadedLuaMod(state);
    if (mod == nullptr) {
        return luaL_error(
            state,
            "sd.input.set_local_player_takeover requires a loaded mod.");
    }
    if (!lua_isboolean(state, 1)) {
        return luaL_error(
            state,
            "sd.input.set_local_player_takeover expects a boolean.");
    }

    std::string error_message;
    if (!SetLocalPlayerControlTakeover(
            mod->descriptor.id,
            lua_toboolean(state, 1) != 0,
            &error_message)) {
        return luaL_error(
            state,
            "sd.input.set_local_player_takeover failed: %s",
            error_message.c_str());
    }
    lua_pushboolean(state, 1);
    return 1;
}

int LuaInputSetLocalPlayerTakeoverTarget(lua_State* state) {
    auto* mod = GetLoadedLuaMod(state);
    if (mod == nullptr) {
        return luaL_error(
            state,
            "sd.input.set_local_player_takeover_target requires a loaded mod.");
    }
    const auto raw_actor = luaL_checkinteger(state, 1);
    const auto target_x =
        static_cast<float>(luaL_checknumber(state, 2));
    const auto target_y =
        static_cast<float>(luaL_checknumber(state, 3));
    if (raw_actor <= 0) {
        return luaL_error(
            state,
            "sd.input.set_local_player_takeover_target actor_address must be positive.");
    }

    std::string error_message;
    if (!SetLocalPlayerControlTakeoverTarget(
            mod->descriptor.id,
            static_cast<uintptr_t>(raw_actor),
            target_x,
            target_y,
            &error_message)) {
        return luaL_error(
            state,
            "sd.input.set_local_player_takeover_target failed: %s",
            error_message.c_str());
    }
    lua_pushboolean(state, 1);
    return 1;
}

int LuaInputGetLocalPlayerTakeoverState(lua_State* state) {
    SDModLocalPlayerControlTakeoverState takeover;
    if (!TryGetLocalPlayerControlTakeoverState(&takeover)) {
        return luaL_error(
            state,
            "sd.input.get_local_player_takeover_state failed.");
    }

    lua_createtable(state, 0, 24);
    lua_pushboolean(state, takeover.active ? 1 : 0);
    lua_setfield(state, -2, "active");
    lua_pushboolean(state, takeover.clean ? 1 : 0);
    lua_setfield(state, -2, "clean");
    lua_pushlstring(
        state,
        takeover.owner_mod_id.data(),
        takeover.owner_mod_id.size());
    lua_setfield(state, -2, "owner_mod_id");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(takeover.actor_address));
    lua_setfield(state, -2, "actor_address");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(
            takeover.target_actor_address));
    lua_setfield(state, -2, "target_actor_address");
    lua_pushnumber(state, takeover.target_x);
    lua_setfield(state, -2, "target_x");
    lua_pushnumber(state, takeover.target_y);
    lua_setfield(state, -2, "target_y");
    lua_pushboolean(state, takeover.target_valid ? 1 : 0);
    lua_setfield(state, -2, "target_valid");
    lua_pushnumber(state, takeover.movement_input_x);
    lua_setfield(state, -2, "movement_input_x");
    lua_pushnumber(state, takeover.movement_input_y);
    lua_setfield(state, -2, "movement_input_y");
    lua_pushnumber(state, takeover.pending_movement_x);
    lua_setfield(state, -2, "pending_movement_x");
    lua_pushnumber(state, takeover.pending_movement_y);
    lua_setfield(state, -2, "pending_movement_y");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(
            takeover.pending_movement_frames));
    lua_setfield(state, -2, "pending_movement_frames");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(
            takeover.pending_mouse_left_frames));
    lua_setfield(state, -2, "pending_mouse_left_frames");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(
            takeover.pending_mouse_right_frames));
    lua_setfield(state, -2, "pending_mouse_right_frames");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(
            takeover.pending_scancode_count));
    lua_setfield(state, -2, "pending_scancode_count");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(
            takeover.pending_native_control_frames));
    lua_setfield(state, -2, "pending_native_control_frames");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(takeover.cast_intent));
    lua_setfield(state, -2, "cast_intent");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(
            takeover.primary_skill_id));
    lua_setfield(state, -2, "primary_skill_id");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(
            takeover.previous_skill_id));
    lua_setfield(state, -2, "previous_skill_id");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(
            takeover.current_target_actor_address));
    lua_setfield(state, -2, "current_target_actor_address");
    lua_pushnumber(state, takeover.control_brain_move_x);
    lua_setfield(state, -2, "control_brain_move_x");
    lua_pushnumber(state, takeover.control_brain_move_y);
    lua_setfield(state, -2, "control_brain_move_y");
    return 1;
}
