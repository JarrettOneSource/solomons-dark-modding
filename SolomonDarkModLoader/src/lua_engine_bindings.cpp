#include "lua_engine_bindings_internal.h"

#include "logger.h"

#include <string>

namespace sdmod::detail {
namespace {

thread_local std::string* g_lua_print_capture_sink = nullptr;

int LuaPrint(lua_State* state) {
    auto* mod = GetLoadedLuaMod(state);
    std::string message;
    const auto argument_count = lua_gettop(state);
    for (int index = 1; index <= argument_count; ++index) {
        const auto* text = luaL_tolstring(state, index, nullptr);
        if (!message.empty()) {
            message.append("\t");
        }
        if (text != nullptr) {
            message.append(text);
        }
        lua_pop(state, 1);
    }

    if (g_lua_print_capture_sink != nullptr) {
        if (!g_lua_print_capture_sink->empty()) {
            g_lua_print_capture_sink->append("\n");
        }
        g_lua_print_capture_sink->append(message);
    }

    if (mod != nullptr) {
        LogLuaMessage(*mod, message);
    } else {
        Log("[lua] " + message);
    }
    return 0;
}

}  // namespace

void RegisterFunction(lua_State* state, lua_CFunction function, const char* name) {
    lua_pushcfunction(state, function);
    lua_setfield(state, -2, name);
}

std::string* SwapLuaPrintCaptureSink(std::string* sink) {
    auto* previous_sink = g_lua_print_capture_sink;
    g_lua_print_capture_sink = sink;
    return previous_sink;
}

LoadedLuaMod* GetLoadedLuaMod(lua_State* state) {
    if (state == nullptr) {
        return nullptr;
    }

    lua_getfield(state, LUA_REGISTRYINDEX, kLuaLoadedModRegistryKey);
    auto* mod = static_cast<LoadedLuaMod*>(lua_touserdata(state, -1));
    lua_pop(state, 1);
    return mod;
}

const LoadedLuaMod* GetLoadedLuaMod(const lua_State* state) {
    return GetLoadedLuaMod(const_cast<lua_State*>(state));
}

bool RegisterLuaBindings(LoadedLuaMod* mod, std::string* error_message) {
    if (mod == nullptr || mod->state == nullptr || error_message == nullptr) {
        return false;
    }

    lua_pushlightuserdata(mod->state, mod);
    lua_setfield(mod->state, LUA_REGISTRYINDEX, kLuaLoadedModRegistryKey);

    lua_createtable(mod->state, 0, 1);
    lua_setfield(mod->state, LUA_REGISTRYINDEX, kLuaEventHandlersRegistryKey);

    lua_pushcfunction(mod->state, &LuaPrint);
    lua_setglobal(mod->state, "print");

    lua_createtable(mod->state, 0, 8);
    RegisterLuaRuntimeBindings(mod->state);
    RegisterLuaEventBindings(mod->state);
    RegisterLuaBotBindings(mod->state);
    RegisterLuaUiBindings(mod->state);
    RegisterLuaInputBindings(mod->state);
    RegisterLuaGameplayBindings(mod->state);
    RegisterLuaHubBindings(mod->state);
    RegisterLuaDebugBindings(mod->state);
    lua_setglobal(mod->state, "sd");
    return true;
}

}  // namespace sdmod::detail
