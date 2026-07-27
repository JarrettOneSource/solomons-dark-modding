// sd.debug.get_native_audio_channels(include_inactive?) -> array
int LuaDebugGetNativeAudioChannels(lua_State* state) {
    const bool include_inactive =
        lua_gettop(state) >= 1 && lua_toboolean(state, 1) != 0;
    const auto channels =
        SnapshotNativeAudioChannels(include_inactive);
    lua_createtable(state, static_cast<int>(channels.size()), 0);
    for (std::size_t index = 0; index < channels.size(); ++index) {
        const auto& channel = channels[index];
        lua_createtable(state, 0, 24);
        lua_pushnumber(
            state,
            static_cast<lua_Number>(channel.event_sequence));
        lua_setfield(state, -2, "event_sequence");
        lua_pushinteger(
            state,
            static_cast<lua_Integer>(channel.object_address));
        lua_setfield(state, -2, "object_address");
        lua_pushinteger(
            state,
            static_cast<lua_Integer>(channel.channel_handle));
        lua_setfield(state, -2, "channel_handle");
        lua_pushinteger(
            state,
            static_cast<lua_Integer>(channel.start_return_address));
        lua_setfield(state, -2, "start_return_address");
        lua_pushinteger(
            state,
            static_cast<lua_Integer>(channel.last_return_address));
        lua_setfield(state, -2, "last_return_address");
        lua_pushinteger(
            state,
            static_cast<lua_Integer>(channel.actor_address));
        lua_setfield(state, -2, "actor_address");
        lua_pushnumber(
            state,
            static_cast<lua_Number>(channel.participant_id));
        lua_setfield(state, -2, "participant_id");
        lua_pushstring(
            state,
            std::to_string(channel.participant_id).c_str());
        lua_setfield(state, -2, "participant_id_text");
        lua_pushnumber(
            state,
            static_cast<lua_Number>(channel.started_ms));
        lua_setfield(state, -2, "started_ms");
        lua_pushnumber(
            state,
            static_cast<lua_Number>(channel.stopped_ms));
        lua_setfield(state, -2, "stopped_ms");
        lua_pushnumber(
            state,
            static_cast<lua_Number>(channel.age_ms));
        lua_setfield(state, -2, "age_ms");
        lua_pushinteger(
            state,
            static_cast<lua_Integer>(channel.start_count));
        lua_setfield(state, -2, "start_count");
        lua_pushinteger(
            state,
            static_cast<lua_Integer>(channel.stop_count));
        lua_setfield(state, -2, "stop_count");
        lua_pushinteger(
            state,
            static_cast<lua_Integer>(channel.cast_sequence));
        lua_setfield(state, -2, "cast_sequence");
        lua_pushinteger(
            state,
            static_cast<lua_Integer>(
                channel.native_reference_count));
        lua_setfield(state, -2, "native_reference_count");
        lua_pushinteger(
            state,
            static_cast<lua_Integer>(channel.registry_index));
        lua_setfield(state, -2, "registry_index");
        lua_pushinteger(
            state,
            static_cast<lua_Integer>(channel.skill_id));
        lua_setfield(state, -2, "skill_id");
        lua_pushboolean(state, channel.active ? 1 : 0);
        lua_setfield(state, -2, "active");
        lua_pushboolean(state, channel.loop_flag ? 1 : 0);
        lua_setfield(state, -2, "loop_flag");
        lua_pushboolean(state, channel.remote ? 1 : 0);
        lua_setfield(state, -2, "remote");
        lua_pushstring(state, channel.asset.c_str());
        lua_setfield(state, -2, "asset");
        lua_pushstring(state, channel.owner.c_str());
        lua_setfield(state, -2, "owner");
        lua_rawseti(
            state,
            -2,
            static_cast<lua_Integer>(index + 1));
    }
    return 1;
}

// sd.debug.dump_native_audio_channels(include_inactive?) -> count
int LuaDebugDumpNativeAudioChannels(lua_State* state) {
    const bool include_inactive =
        lua_gettop(state) >= 1 && lua_toboolean(state, 1) != 0;
    const auto count =
        DumpNativeAudioChannelsToLog(include_inactive);
    lua_pushinteger(state, static_cast<lua_Integer>(count));
    return 1;
}

// sd.debug.clear_native_audio_channel_history() -> removed_count
int LuaDebugClearNativeAudioChannelHistory(lua_State* state) {
    (void)state;
    const auto removed =
        ClearInactiveNativeAudioChannelHistory();
    lua_pushinteger(state, static_cast<lua_Integer>(removed));
    return 1;
}
