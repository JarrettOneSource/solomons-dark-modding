// sd.debug.capture_backbuffer(path) -> boolean, string
int LuaDebugCaptureBackBuffer(lua_State* state) {
    const char* utf8_path = luaL_checkstring(state, 1);
    if (utf8_path == nullptr || *utf8_path == '\0') {
        lua_pushboolean(state, 0);
        lua_pushliteral(state, "capture path must not be empty");
        return 2;
    }

    const int required_characters = MultiByteToWideChar(
        CP_UTF8,
        MB_ERR_INVALID_CHARS,
        utf8_path,
        -1,
        nullptr,
        0);
    if (required_characters <= 1) {
        lua_pushboolean(state, 0);
        lua_pushliteral(state, "capture path is not valid UTF-8");
        return 2;
    }

    std::wstring wide_path(static_cast<std::size_t>(required_characters), L'\0');
    if (MultiByteToWideChar(
            CP_UTF8,
            MB_ERR_INVALID_CHARS,
            utf8_path,
            -1,
            wide_path.data(),
            required_characters) != required_characters) {
        lua_pushboolean(state, 0);
        lua_pushliteral(state, "capture path UTF-8 conversion failed");
        return 2;
    }
    wide_path.resize(static_cast<std::size_t>(required_characters - 1));

    std::string error_message;
    const bool captured =
        sdmod::CaptureD3d9BackBufferBmp(wide_path, &error_message);
    lua_pushboolean(state, captured ? 1 : 0);
    lua_pushlstring(state, error_message.c_str(), error_message.size());
    return 2;
}
