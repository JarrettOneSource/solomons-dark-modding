#include "lua_engine_bindings_internal.h"

#include <cmath>
#include <cstdint>
#include <string>
#include <string_view>

namespace sdmod::detail {
namespace {

constexpr float kLuaAudioMinimumVolume = 0.0f;
constexpr float kLuaAudioMaximumVolume = 1.0f;

LoadedLuaMod* RequireAudioMod(lua_State* state, const char* api_name) {
    auto* mod = GetLoadedLuaMod(state);
    if (mod == nullptr) {
        luaL_error(state, "%s is unavailable", api_name);
    }
    return mod;
}

void RequireArgumentCount(
    lua_State* state,
    int expected,
    const char* api_name) {
    if (lua_gettop(state) != expected) {
        luaL_error(
            state,
            "%s expects exactly %d argument%s",
            api_name,
            expected,
            expected == 1 ? "" : "s");
    }
}

bool IsKnownAudioOption(std::string_view field) {
    return field == "volume" || field == "loop";
}

void RejectUnknownAudioOptions(
    lua_State* state,
    int options_index,
    const char* api_name) {
    lua_pushnil(state);
    while (lua_next(state, options_index) != 0) {
        if (lua_type(state, -2) != LUA_TSTRING) {
            lua_pop(state, 2);
            luaL_error(state, "%s options accept only named fields", api_name);
        }
        std::size_t field_length = 0;
        const auto* field = lua_tolstring(state, -2, &field_length);
        if (!IsKnownAudioOption(std::string_view(field, field_length))) {
            const std::string owned_field(field, field_length);
            lua_pop(state, 2);
            luaL_error(
                state,
                "%s options received unknown field '%s'",
                api_name,
                owned_field.c_str());
        }
        lua_pop(state, 1);
    }
}

int ReadAudioOptionsIndex(
    lua_State* state,
    int index,
    const char* api_name) {
    if (lua_gettop(state) < index || lua_isnil(state, index)) {
        return 0;
    }
    if (!lua_istable(state, index)) {
        luaL_error(state, "%s options must be a table", api_name);
    }
    const int absolute_index = lua_absindex(state, index);
    RejectUnknownAudioOptions(state, absolute_index, api_name);
    return absolute_index;
}

float ReadVolume(
    lua_State* state,
    int index,
    const char* api_name,
    const char* argument_name) {
    if (!lua_isnumber(state, index)) {
        luaL_error(
            state,
            "%s %s must be a number",
            api_name,
            argument_name);
    }
    const auto volume = static_cast<float>(lua_tonumber(state, index));
    if (!std::isfinite(volume) || volume < kLuaAudioMinimumVolume ||
        volume > kLuaAudioMaximumVolume) {
        luaL_error(
            state,
            "%s %s must be finite and between 0 and 1",
            api_name,
            argument_name);
    }
    return volume;
}

float ReadAudioOptionVolume(
    lua_State* state,
    int options_index,
    const char* api_name) {
    if (options_index == 0) {
        return 1.0f;
    }
    lua_getfield(state, options_index, "volume");
    if (lua_isnil(state, -1)) {
        lua_pop(state, 1);
        return 1.0f;
    }
    const float volume = ReadVolume(state, -1, api_name, "options.volume");
    lua_pop(state, 1);
    return volume;
}

bool ReadAudioOptionLoop(
    lua_State* state,
    int options_index,
    const char* api_name) {
    if (options_index == 0) {
        return false;
    }
    lua_getfield(state, options_index, "loop");
    if (lua_isnil(state, -1)) {
        lua_pop(state, 1);
        return false;
    }
    if (!lua_isboolean(state, -1)) {
        luaL_error(state, "%s options.loop must be a boolean", api_name);
    }
    const bool loop = lua_toboolean(state, -1) != 0;
    lua_pop(state, 1);
    return loop;
}

std::uint64_t ReadAudioHandle(
    lua_State* state,
    int index,
    const char* api_name) {
    if (!lua_isinteger(state, index)) {
        luaL_error(state, "%s handle must be a positive integer", api_name);
    }
    const auto handle = lua_tointeger(state, index);
    if (handle <= 0) {
        luaL_error(state, "%s handle must be a positive integer", api_name);
    }
    return static_cast<std::uint64_t>(handle);
}

void PushAudioPlayback(
    lua_State* state,
    const LuaAudioPlaybackSnapshot& playback) {
    lua_createtable(state, 0, 7);
    lua_pushinteger(state, static_cast<lua_Integer>(playback.id));
    lua_setfield(state, -2, "handle");
    const char* kind =
        playback.kind == LuaAudioPlaybackKind::Sample ? "sample" : "stream";
    lua_pushstring(state, kind);
    lua_setfield(state, -2, "kind");
    lua_pushlstring(
        state, playback.relative_path.data(), playback.relative_path.size());
    lua_setfield(state, -2, "path");
    lua_pushnumber(state, static_cast<lua_Number>(playback.volume));
    lua_setfield(state, -2, "volume");
    lua_pushboolean(state, playback.loop ? 1 : 0);
    lua_setfield(state, -2, "loop");
    lua_pushinteger(state, static_cast<lua_Integer>(playback.created_ms));
    lua_setfield(state, -2, "created_milliseconds");
    lua_pushlstring(
        state, playback.activity.data(), playback.activity.size());
    lua_setfield(state, -2, "state");
}

int PlayAudio(lua_State* state, LuaAudioPlaybackKind kind) {
    const char* api_name = kind == LuaAudioPlaybackKind::Sample
        ? "sd.audio.play_sample"
        : "sd.audio.play_stream";
    const int argument_count = lua_gettop(state);
    if (argument_count < 1 || argument_count > 2) {
        return luaL_error(
            state, "%s expects a path and optional options table", api_name);
    }

    auto* mod = RequireAudioMod(state, api_name);
    std::size_t path_length = 0;
    const auto* path = luaL_checklstring(state, 1, &path_length);
    const int options_index = ReadAudioOptionsIndex(state, 2, api_name);
    const float volume = ReadAudioOptionVolume(state, options_index, api_name);
    const bool loop = ReadAudioOptionLoop(state, options_index, api_name);

    std::uint64_t playback_id = 0;
    std::string error_message;
    if (!PlayLuaAudio(
            mod,
            kind,
            std::string_view(path, path_length),
            volume,
            loop,
            &playback_id,
            &error_message)) {
        return luaL_error(state, "%s: %s", api_name, error_message.c_str());
    }
    lua_pushinteger(state, static_cast<lua_Integer>(playback_id));
    return 1;
}

int LuaAudioPlaySample(lua_State* state) {
    return PlayAudio(state, LuaAudioPlaybackKind::Sample);
}

int LuaAudioPlayStream(lua_State* state) {
    return PlayAudio(state, LuaAudioPlaybackKind::Stream);
}

int LuaAudioStop(lua_State* state) {
    constexpr const char* kApiName = "sd.audio.stop";
    RequireArgumentCount(state, 1, kApiName);
    auto* mod = RequireAudioMod(state, kApiName);
    const auto playback_id = ReadAudioHandle(state, 1, kApiName);
    lua_pushboolean(
        state, StopLuaAudioPlayback(mod, playback_id) ? 1 : 0);
    return 1;
}

int LuaAudioSetVolume(lua_State* state) {
    constexpr const char* kApiName = "sd.audio.set_volume";
    RequireArgumentCount(state, 2, kApiName);
    auto* mod = RequireAudioMod(state, kApiName);
    const auto playback_id = ReadAudioHandle(state, 1, kApiName);
    const float volume = ReadVolume(state, 2, kApiName, "volume");
    bool found = false;
    std::string error_message;
    if (!SetLuaAudioPlaybackVolume(
            mod, playback_id, volume, &found, &error_message)) {
        return luaL_error(state, "%s: %s", kApiName, error_message.c_str());
    }
    lua_pushboolean(state, found ? 1 : 0);
    return 1;
}

int LuaAudioGetState(lua_State* state) {
    constexpr const char* kApiName = "sd.audio.get_state";
    const int argument_count = lua_gettop(state);
    auto* mod = RequireAudioMod(state, kApiName);
    if (argument_count == 0 ||
        (argument_count == 1 && lua_isnil(state, 1))) {
        const auto playbacks = SnapshotLuaAudioPlaybacks(mod);
        lua_createtable(state, static_cast<int>(playbacks.size()), 0);
        int index = 1;
        for (const auto& playback : playbacks) {
            PushAudioPlayback(state, playback);
            lua_rawseti(state, -2, index++);
        }
        return 1;
    }
    if (argument_count != 1) {
        return luaL_error(
            state, "%s expects no arguments or one handle", kApiName);
    }

    LuaAudioPlaybackSnapshot playback;
    if (!TryGetLuaAudioPlaybackSnapshot(
            mod,
            ReadAudioHandle(state, 1, kApiName),
            &playback)) {
        lua_pushnil(state);
        return 1;
    }
    PushAudioPlayback(state, playback);
    return 1;
}

int LuaAudioClear(lua_State* state) {
    constexpr const char* kApiName = "sd.audio.clear";
    RequireArgumentCount(state, 0, kApiName);
    auto* mod = RequireAudioMod(state, kApiName);
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(ClearLuaAudioRuntimeForMod(mod)));
    return 1;
}

int LuaAudioIsAvailable(lua_State* state) {
    constexpr const char* kApiName = "sd.audio.is_available";
    RequireArgumentCount(state, 0, kApiName);
    lua_pushboolean(state, IsLuaAudioRuntimeAvailable() ? 1 : 0);
    return 1;
}

}  // namespace

void RegisterLuaAudioBindings(lua_State* state) {
    lua_createtable(state, 0, 7);
    RegisterFunction(state, &LuaAudioPlaySample, "play_sample");
    RegisterFunction(state, &LuaAudioPlayStream, "play_stream");
    RegisterFunction(state, &LuaAudioStop, "stop");
    RegisterFunction(state, &LuaAudioSetVolume, "set_volume");
    RegisterFunction(state, &LuaAudioGetState, "get_state");
    RegisterFunction(state, &LuaAudioClear, "clear");
    RegisterFunction(state, &LuaAudioIsAvailable, "is_available");
    lua_setfield(state, -2, "audio");
}

}  // namespace sdmod::detail
