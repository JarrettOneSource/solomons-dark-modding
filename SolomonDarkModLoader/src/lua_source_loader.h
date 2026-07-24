#pragma once

#include <filesystem>
#include <string>

struct lua_State;

namespace sdmod::detail {

bool LoadLuaSourceFile(
    lua_State* state,
    const std::filesystem::path& path,
    std::string* error_message);

}  // namespace sdmod::detail
