// sd.debug.queue_native_scene_capture(label) -> boolean, string
int LuaDebugQueueNativeSceneCapture(lua_State* state) {
    std::size_t label_size = 0;
    const char* label = luaL_checklstring(state, 1, &label_size);
    std::string error_message;
    const bool queued = QueueNativeSceneCapture(
        std::string_view(label, label_size), &error_message);
    lua_pushboolean(state, queued ? 1 : 0);
    lua_pushlstring(
        state, error_message.c_str(), error_message.size());
    return 2;
}

// sd.debug.queue_native_scene_capture_sequence(label, frame_count) -> boolean, string
int LuaDebugQueueNativeSceneCaptureSequence(lua_State* state) {
    std::size_t label_size = 0;
    const char* label = luaL_checklstring(state, 1, &label_size);
    const auto frame_count =
        CheckLuaUnsignedInteger<std::uint32_t>(state, 2, "frame_count");
    std::string error_message;
    const bool queued = QueueNativeSceneCaptureSequence(
        std::string_view(label, label_size), frame_count, &error_message);
    lua_pushboolean(state, queued ? 1 : 0);
    lua_pushlstring(
        state, error_message.c_str(), error_message.size());
    return 2;
}

// sd.debug.observe_native_cast_glyph_emitter() -> table
// Calls the retail resolver read-only; it does not reproduce the facing formula.
int LuaDebugObserveNativeCastGlyphEmitter(lua_State* state) {
    lua_createtable(state, 0, 14);
    SDModPlayerState player;
    if (!TryGetPlayerState(&player) || player.actor_address == 0) {
        lua_pushliteral(state, "unavailable");
        lua_setfield(state, -2, "status");
        lua_pushliteral(state, "local player actor is unavailable");
        lua_setfield(state, -2, "error");
        return 1;
    }

    auto& memory = ProcessMemory::Instance();
    constexpr uintptr_t kEmitterPreferredAddress = 0x0053B830;
    const auto emitter_address = ResolveExecutableLuaAddress(
        memory, kEmitterPreferredAddress);
    if (emitter_address == 0) {
        lua_pushliteral(state, "failed");
        lua_setfield(state, -2, "status");
        lua_pushliteral(state, "retail cast-glyph emitter is not executable");
        lua_setfield(state, -2, "error");
        return 1;
    }

    using EmitterFn = float*(__thiscall*)(void*, float*);
    auto* emitter = reinterpret_cast<EmitterFn>(emitter_address);
    float result[2] = {};
    float* returned = nullptr;
    bool call_ok = false;
    __try {
        returned = emitter(
            reinterpret_cast<void*>(player.actor_address), result);
        call_ok = returned == result;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        call_ok = false;
    }
    if (!call_ok || !std::isfinite(result[0]) || !std::isfinite(result[1])) {
        lua_pushliteral(state, "failed");
        lua_setfield(state, -2, "status");
        lua_pushliteral(state, "retail cast-glyph emitter call failed");
        lua_setfield(state, -2, "error");
        return 1;
    }

    float actor_scale = 0.0f;
    const auto attachment_address =
        player.attachment_visual_lane.current_object_address;
    const auto attachment_type =
        player.attachment_visual_lane.current_object_type_id;
    (void)memory.TryReadValue(player.actor_address + 0x74, &actor_scale);
    lua_pushliteral(state, "complete");
    lua_setfield(state, -2, "status");
    lua_pushliteral(state, "");
    lua_setfield(state, -2, "error");
    lua_pushinteger(state, static_cast<lua_Integer>(kEmitterPreferredAddress));
    lua_setfield(state, -2, "resolver_preferred_address");
    lua_pushinteger(state, static_cast<lua_Integer>(player.actor_address));
    lua_setfield(state, -2, "actor_address");
    lua_pushinteger(
        state, static_cast<lua_Integer>(player.local_player_tick_count));
    lua_setfield(state, -2, "tick");
    lua_pushnumber(state, static_cast<lua_Number>(player.x));
    lua_setfield(state, -2, "actor_x");
    lua_pushnumber(state, static_cast<lua_Number>(player.y));
    lua_setfield(state, -2, "actor_y");
    lua_pushnumber(state, static_cast<lua_Number>(player.heading));
    lua_setfield(state, -2, "heading");
    lua_pushnumber(
        state, static_cast<lua_Number>(player.render_advance_phase));
    lua_setfield(state, -2, "render_phase");
    lua_pushnumber(state, static_cast<lua_Number>(actor_scale));
    lua_setfield(state, -2, "actor_scale");
    lua_pushinteger(
        state, static_cast<lua_Integer>(player.render_weapon_type));
    lua_setfield(state, -2, "weapon_type");
    lua_pushinteger(state, static_cast<lua_Integer>(attachment_address));
    lua_setfield(state, -2, "attachment_address");
    lua_pushinteger(state, static_cast<lua_Integer>(attachment_type));
    lua_setfield(state, -2, "attachment_type");
    lua_pushnumber(state, static_cast<lua_Number>(result[0]));
    lua_setfield(state, -2, "emitter_x");
    lua_pushnumber(state, static_cast<lua_Number>(result[1]));
    lua_setfield(state, -2, "emitter_y");
    return 1;
}

// sd.debug.get_native_scene_capture_status() -> table
int LuaDebugGetNativeSceneCaptureStatus(lua_State* state) {
    NativeSceneCaptureStatus status;
    if (!TryGetNativeSceneCaptureStatus(&status)) {
        lua_pushnil(state);
        return 1;
    }
    lua_createtable(state, 0, 10);
    lua_pushboolean(state, status.requested ? 1 : 0);
    lua_setfield(state, -2, "requested");
    lua_pushboolean(state, status.initialized ? 1 : 0);
    lua_setfield(state, -2, "initialized");
    lua_pushlstring(state, status.state.c_str(), status.state.size());
    lua_setfield(state, -2, "state");
    lua_pushlstring(state, status.label.c_str(), status.label.size());
    lua_setfield(state, -2, "label");
    lua_pushlstring(
        state, status.output_path.c_str(), status.output_path.size());
    lua_setfield(state, -2, "output_path");
    lua_pushlstring(
        state, status.error_message.c_str(), status.error_message.size());
    lua_setfield(state, -2, "error_message");
    lua_pushinteger(
        state, static_cast<lua_Integer>(status.draw_count));
    lua_setfield(state, -2, "draw_count");
    lua_pushinteger(
        state, static_cast<lua_Integer>(status.requested_frame_count));
    lua_setfield(state, -2, "requested_frame_count");
    lua_pushinteger(
        state, static_cast<lua_Integer>(status.captured_frame_count));
    lua_setfield(state, -2, "captured_frame_count");
    return 1;
}
