#include "lua_engine_bindings_internal.h"

#include "multiplayer_session_teardown.h"

#include <string>

namespace sdmod::detail {
namespace {

int LuaPrivilegedSessionLeave(lua_State* state) {
    constexpr const char* kApiName = "sd.__session_leave";
    if (GetLuaSettingsPrivilegedExecState() != state) {
        return luaL_error(
            state,
            "%s is available only to the launcher exec pipe",
            kApiName);
    }
    if (lua_gettop(state) != 0) {
        return luaL_error(state, "%s expects no arguments", kApiName);
    }

    std::string error;
    const bool accepted =
        multiplayer::RequestSessionLeaveAfterPipeAck(&error);
    lua_createtable(state, 0, 2);
    lua_pushboolean(state, accepted ? 1 : 0);
    lua_setfield(state, -2, "ok");
    lua_pushlstring(state, error.data(), error.size());
    lua_setfield(state, -2, "error");
    return 1;
}

}  // namespace

void InstallLuaSessionPrivilegedBindings(lua_State* state) {
    lua_getglobal(state, "sd");
    if (!lua_istable(state, -1)) {
        lua_pop(state, 1);
        return;
    }
    RegisterFunction(
        state,
        &LuaPrivilegedSessionLeave,
        "__session_leave");
    lua_pop(state, 1);
}

void RemoveLuaSessionPrivilegedBindings(lua_State* state) {
    lua_getglobal(state, "sd");
    if (!lua_istable(state, -1)) {
        lua_pop(state, 1);
        return;
    }
    lua_pushnil(state);
    lua_setfield(state, -2, "__session_leave");
    lua_pop(state, 1);
}

}  // namespace sdmod::detail
