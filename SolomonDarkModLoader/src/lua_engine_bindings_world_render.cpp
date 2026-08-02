#include "lua_engine_bindings_internal.h"

#include "lua_draw_runtime.h"
#include "lua_world_render_runtime.h"

#include <cmath>
#include <cstdint>
#include <limits>
#include <string>
#include <string_view>
#include <utility>

namespace sdmod::detail {
namespace {

LoadedLuaMod* RequireWorldRenderMod(
    lua_State* state,
    const char* api_name) {
    auto* mod = GetLoadedLuaMod(state);
    if (mod == nullptr) {
        luaL_error(state, "%s is unavailable", api_name);
    }
    return mod;
}

float ReadWorldRenderNumber(
    lua_State* state,
    int index,
    const char* api_name,
    const char* argument_name,
    float minimum,
    float maximum) {
    const auto value = static_cast<float>(luaL_checknumber(state, index));
    if (!std::isfinite(value) || value < minimum || value > maximum) {
        luaL_error(
            state,
            "%s %s must be finite and between %.3f and %.3f",
            api_name,
            argument_name,
            minimum,
            maximum);
    }
    return value;
}

int NormalizeWorldRenderOptions(
    lua_State* state,
    int index,
    const char* api_name) {
    if (lua_gettop(state) < index || lua_isnil(state, index)) {
        return 0;
    }
    if (!lua_istable(state, index)) {
        luaL_error(state, "%s options must be a table", api_name);
    }
    return lua_absindex(state, index);
}

float ReadWorldRenderOption(
    lua_State* state,
    int options_index,
    const char* field_name,
    float default_value,
    float minimum,
    float maximum,
    const char* api_name) {
    if (options_index == 0) {
        return default_value;
    }
    lua_getfield(state, options_index, field_name);
    if (lua_isnil(state, -1)) {
        lua_pop(state, 1);
        return default_value;
    }
    if (!lua_isnumber(state, -1)) {
        return static_cast<float>(luaL_error(
            state,
            "%s options.%s must be a number",
            api_name,
            field_name));
    }
    const auto value = static_cast<float>(lua_tonumber(state, -1));
    lua_pop(state, 1);
    if (!std::isfinite(value) || value < minimum || value > maximum) {
        luaL_error(
            state,
            "%s options.%s must be finite and between %.3f and %.3f",
            api_name,
            field_name,
            minimum,
            maximum);
    }
    return value;
}

int LuaWorldSprite(lua_State* state) {
    constexpr const char* kApiName = "sd.world.sprite";
    const auto* mod = RequireWorldRenderMod(state, kApiName);
    std::size_t atlas_length = 0;
    const char* atlas = luaL_checklstring(state, 1, &atlas_length);
    const auto raw_sprite_index = luaL_checkinteger(state, 2);
    if (raw_sprite_index < 0 ||
        static_cast<lua_Unsigned>(raw_sprite_index) >
            (std::numeric_limits<std::uint32_t>::max)()) {
        return luaL_error(
            state,
            "%s record must be a nonnegative 32-bit integer",
            kApiName);
    }

    LuaDrawSpriteInfo sprite;
    std::string canonical_atlas;
    std::string error_message;
    if (!TryGetLuaDrawSpriteInfo(
            std::string_view(atlas, atlas_length),
            static_cast<std::uint32_t>(raw_sprite_index),
            &sprite,
            &canonical_atlas,
            &error_message)) {
        return luaL_error(state, "%s", error_message.c_str());
    }
    if (sprite.rotated) {
        return luaL_error(
            state,
            "%s does not support rotated bundle records",
            kApiName);
    }

    LuaWorldSpriteCommand command;
    command.atlas = std::move(canonical_atlas);
    command.sprite_index =
        static_cast<std::uint32_t>(raw_sprite_index);
    command.x = ReadWorldRenderNumber(
        state,
        3,
        kApiName,
        "x",
        -kLuaWorldRenderMaximumCoordinate,
        kLuaWorldRenderMaximumCoordinate);
    command.y = ReadWorldRenderNumber(
        state,
        4,
        kApiName,
        "y",
        -kLuaWorldRenderMaximumCoordinate,
        kLuaWorldRenderMaximumCoordinate);
    const int options = NormalizeWorldRenderOptions(state, 5, kApiName);
    command.width = ReadWorldRenderOption(
        state,
        options,
        "width",
        static_cast<float>(sprite.logical_width),
        0.001f,
        kLuaWorldRenderMaximumDimension,
        kApiName);
    command.height = ReadWorldRenderOption(
        state,
        options,
        "height",
        static_cast<float>(sprite.logical_height),
        0.001f,
        kLuaWorldRenderMaximumDimension,
        kApiName);
    command.offset_x = ReadWorldRenderOption(
        state,
        options,
        "offset_x",
        0.0f,
        -kLuaWorldRenderMaximumCoordinate,
        kLuaWorldRenderMaximumCoordinate,
        kApiName);
    command.offset_y = ReadWorldRenderOption(
        state,
        options,
        "offset_y",
        0.0f,
        -kLuaWorldRenderMaximumCoordinate,
        kLuaWorldRenderMaximumCoordinate,
        kApiName);
    command.sort_bias = ReadWorldRenderOption(
        state,
        options,
        "sort_bias",
        0.0f,
        -kLuaWorldRenderMaximumSortBias,
        kLuaWorldRenderMaximumSortBias,
        kApiName);

    if (!SubmitLuaWorldSpriteCommand(
            mod->descriptor.id,
            std::move(command),
            &error_message)) {
        return luaL_error(state, "%s", error_message.c_str());
    }
    lua_pushboolean(state, 1);
    return 1;
}

}  // namespace

void RegisterLuaWorldRenderBindings(lua_State* state) {
    RegisterFunction(state, &LuaWorldSprite, "sprite");
}

}  // namespace sdmod::detail
