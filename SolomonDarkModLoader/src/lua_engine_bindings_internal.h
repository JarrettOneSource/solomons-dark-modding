#pragma once

#include "lua_engine_internal.h"

#include <string>

extern "C" {
#include "lauxlib.h"
#include "lua.h"
}

namespace sdmod::detail {

void RegisterFunction(lua_State* state, lua_CFunction function, const char* name);
std::string* SwapLuaPrintCaptureSink(std::string* sink);
bool TryLuaValueToString(lua_State* state, int index, std::string* text, std::string* error_message);

void RegisterLuaRuntimeBindings(lua_State* state);
void RegisterLuaEventBindings(lua_State* state);
void RegisterLuaBotBindings(lua_State* state);
void RegisterLuaUiBindings(lua_State* state);
void RegisterLuaInputBindings(lua_State* state);
void RegisterLuaGameplayBindings(lua_State* state);
void RegisterLuaHubBindings(lua_State* state);
void RegisterLuaDebugBindings(lua_State* state);

}  // namespace sdmod::detail
