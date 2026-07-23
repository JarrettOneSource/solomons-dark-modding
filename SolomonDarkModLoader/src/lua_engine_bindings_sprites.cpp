#include "lua_engine_bindings_internal.h"

#include "lua_content_registry.h"
#include "lua_sprite_runtime.h"

#include <string>
#include <string_view>

namespace sdmod::detail {
namespace {

LoadedLuaMod* RequireSpriteMod(lua_State* state, const char* api_name) {
    auto* mod = GetLoadedLuaMod(state);
    if (mod == nullptr) {
        luaL_error(state, "%s requires an owning Lua mod", api_name);
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

std::string_view ReadString(
    lua_State* state,
    int index,
    const char* api_name,
    const char* argument_name) {
    if (lua_type(state, index) != LUA_TSTRING) {
        luaL_error(state, "%s %s must be a string", api_name, argument_name);
    }
    std::size_t length = 0;
    const auto* value = lua_tolstring(state, index, &length);
    return std::string_view(value, length);
}

std::string_view ReadKey(
    lua_State* state,
    int index,
    const char* api_name) {
    const auto key = ReadString(state, index, api_name, "key");
    if (!IsValidLuaContentIdentifier(key)) {
        luaL_error(
            state,
            "%s key must be a lowercase content identifier",
            api_name);
    }
    return key;
}

void PushSpriteAtlas(
    lua_State* state,
    const LuaSpriteAtlasSnapshot& atlas) {
    lua_createtable(state, 0, 9);
    lua_pushlstring(state, atlas.id.data(), atlas.id.size());
    lua_setfield(state, -2, "id");
    lua_pushlstring(state, atlas.key.data(), atlas.key.size());
    lua_setfield(state, -2, "key");
    lua_pushlstring(
        state, atlas.image_path.data(), atlas.image_path.size());
    lua_setfield(state, -2, "image");
    lua_pushlstring(
        state, atlas.bundle_path.data(), atlas.bundle_path.size());
    lua_setfield(state, -2, "bundle");
    lua_pushinteger(state, static_cast<lua_Integer>(atlas.frame_count));
    lua_setfield(state, -2, "frame_count");
    lua_pushinteger(state, atlas.image_width);
    lua_setfield(state, -2, "image_width");
    lua_pushinteger(state, atlas.image_height);
    lua_setfield(state, -2, "image_height");
    lua_pushinteger(state, static_cast<lua_Integer>(atlas.revision));
    lua_setfield(state, -2, "revision");
    lua_pushboolean(state, 1);
    lua_setfield(state, -2, "local_only");
}

int LuaSpritesRegister(lua_State* state) {
    constexpr const char* kApiName = "sd.sprites.register";
    RequireArgumentCount(state, 3, kApiName);
    auto* mod = RequireSpriteMod(state, kApiName);
    const auto key = ReadKey(state, 1, kApiName);
    const auto image = ReadString(state, 2, kApiName, "image path");
    const auto bundle = ReadString(state, 3, kApiName, "bundle path");

    LuaSpriteAtlasSnapshot atlas;
    std::string error_message;
    if (!RegisterLuaSpriteAtlas(
            mod->descriptor.id,
            mod->descriptor.root_path,
            key,
            image,
            bundle,
            &atlas,
            &error_message)) {
        return luaL_error(state, "%s: %s", kApiName, error_message.c_str());
    }
    PushSpriteAtlas(state, atlas);
    return 1;
}

int LuaSpritesUnregister(lua_State* state) {
    constexpr const char* kApiName = "sd.sprites.unregister";
    RequireArgumentCount(state, 1, kApiName);
    const auto* mod = RequireSpriteMod(state, kApiName);
    const auto key = ReadKey(state, 1, kApiName);
    lua_pushboolean(
        state,
        UnregisterLuaSpriteAtlas(mod->descriptor.id, key) ? 1 : 0);
    return 1;
}

int LuaSpritesGet(lua_State* state) {
    constexpr const char* kApiName = "sd.sprites.get";
    RequireArgumentCount(state, 1, kApiName);
    const auto* mod = RequireSpriteMod(state, kApiName);
    const auto key = ReadKey(state, 1, kApiName);
    const auto atlas = FindLuaSpriteAtlas(mod->descriptor.id, key);
    if (!atlas.has_value()) {
        lua_pushnil(state);
        return 1;
    }
    PushSpriteAtlas(state, *atlas);
    return 1;
}

int LuaSpritesList(lua_State* state) {
    constexpr const char* kApiName = "sd.sprites.list";
    RequireArgumentCount(state, 0, kApiName);
    const auto* mod = RequireSpriteMod(state, kApiName);
    const auto atlases = ListLuaSpriteAtlases(mod->descriptor.id);
    lua_createtable(state, static_cast<int>(atlases.size()), 0);
    lua_Integer index = 1;
    for (const auto& atlas : atlases) {
        PushSpriteAtlas(state, atlas);
        lua_seti(state, -2, index++);
    }
    return 1;
}

int LuaSpritesGetLimits(lua_State* state) {
    constexpr const char* kApiName = "sd.sprites.get_limits";
    RequireArgumentCount(state, 0, kApiName);
    lua_createtable(state, 0, 10);
    lua_pushinteger(state, kLuaSpriteMaximumAtlasesPerMod);
    lua_setfield(state, -2, "atlases_per_mod");
    lua_pushinteger(state, kLuaSpriteMaximumGlobalAtlases);
    lua_setfield(state, -2, "global_atlases");
    lua_pushinteger(state, kLuaSpriteMaximumFramesPerAtlas);
    lua_setfield(state, -2, "frames_per_atlas");
    lua_pushinteger(state, kLuaSpriteMaximumGlobalFrames);
    lua_setfield(state, -2, "global_frames");
    lua_pushinteger(state, kLuaSpriteMaximumRelativePathBytes);
    lua_setfield(state, -2, "relative_path_bytes");
    lua_pushinteger(state, kLuaSpriteMaximumAtlasIdBytes);
    lua_setfield(state, -2, "atlas_id_bytes");
    lua_pushinteger(
        state, static_cast<lua_Integer>(kLuaSpriteMaximumImageBytes));
    lua_setfield(state, -2, "image_bytes");
    lua_pushinteger(
        state, static_cast<lua_Integer>(kLuaSpriteMaximumBundleBytes));
    lua_setfield(state, -2, "bundle_bytes");
    lua_pushinteger(state, kLuaSpriteMaximumImageDimension);
    lua_setfield(state, -2, "image_dimension");
    lua_pushnumber(state, kLuaSpriteMaximumFrameGeometry);
    lua_setfield(state, -2, "frame_geometry");
    return 1;
}

}  // namespace

void RegisterLuaSpriteBindings(lua_State* state) {
    lua_createtable(state, 0, 5);
    RegisterFunction(state, &LuaSpritesRegister, "register");
    RegisterFunction(state, &LuaSpritesUnregister, "unregister");
    RegisterFunction(state, &LuaSpritesGet, "get");
    RegisterFunction(state, &LuaSpritesList, "list");
    RegisterFunction(state, &LuaSpritesGetLimits, "get_limits");
    lua_setfield(state, -2, "sprites");
}

}  // namespace sdmod::detail
