#include "lua_engine_bindings_internal.h"
#include "lua_engine_internal.h"

extern "C" {
#include "lauxlib.h"
#include "lualib.h"
}

namespace sdmod::detail {
namespace {

int ControlStatePanic(lua_State*) {
    return 0;
}

void RemoveUnsafeControlGlobals(lua_State* state) {
    const char* names[] = {
        "debug",
        "dofile",
        "io",
        "loadfile",
        "os",
        "package",
        "require",
    };
    for (const auto* name : names) {
        lua_pushnil(state);
        lua_setglobal(state, name);
    }
}

}  // namespace

lua_State*& LuaExecControlStateStorage() {
    static lua_State* state = nullptr;
    return state;
}

bool InitializeLuaExecControlState(std::string* error_message) {
    auto& state = LuaExecControlStateStorage();
    state = luaL_newstate();
    if (state == nullptr) {
        if (error_message != nullptr) {
            *error_message =
                "luaL_newstate failed for the launcher control state.";
        }
        return false;
    }

    lua_atpanic(state, &ControlStatePanic);
    luaL_openlibs(state);
    RemoveUnsafeControlGlobals(state);
    lua_createtable(state, 0, 1);
    lua_pushvalue(state, -1);
    lua_setfield(state, LUA_REGISTRYINDEX, kLuaSdRegistryKey);
    lua_setglobal(state, "sd");
    return true;
}

void ShutdownLuaExecControlState() {
    auto& state = LuaExecControlStateStorage();
    if (state != nullptr) {
        lua_close(state);
        state = nullptr;
    }
}

}  // namespace sdmod::detail
