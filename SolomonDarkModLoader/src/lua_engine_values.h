#pragma once

#include "lua_mod_runtime.h"

#include <string>

struct lua_State;

namespace sdmod::detail {

bool ReadLuaModValue(
    lua_State* state,
    int index,
    LuaModValue* value,
    std::string* error_message);
void PushLuaModValue(lua_State* state, const LuaModValue& value);

}  // namespace sdmod::detail
