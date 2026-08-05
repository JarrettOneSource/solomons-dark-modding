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

// sd.debug.get_native_scene_capture_status() -> table
int LuaDebugGetNativeSceneCaptureStatus(lua_State* state) {
    NativeSceneCaptureStatus status;
    if (!TryGetNativeSceneCaptureStatus(&status)) {
        lua_pushnil(state);
        return 1;
    }
    lua_createtable(state, 0, 8);
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
    return 1;
}
