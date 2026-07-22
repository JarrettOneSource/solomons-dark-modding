#include "lua_engine_bindings_internal.h"

#include "lua_draw_runtime.h"

#include <cmath>
#include <cstdint>
#include <limits>
#include <string>
#include <utility>

namespace sdmod::detail {
namespace {

constexpr float kMaximumCoordinateMagnitude = 1000000.0f;
constexpr float kMaximumDrawExtent = 8192.0f;
constexpr float kMinimumTextScale = 0.1f;
constexpr float kMaximumTextScale = 16.0f;
constexpr float kMinimumLineThickness = 1.0f;
constexpr float kMaximumLineThickness = 64.0f;

LoadedLuaMod* RequireDrawMod(lua_State* state, const char* api_name) {
    auto* mod = GetLoadedLuaMod(state);
    if (mod == nullptr) {
        luaL_error(state, "%s is unavailable", api_name);
    }
    return mod;
}

float ReadFiniteNumber(
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

int NormalizeOptionsIndex(lua_State* state, int index, const char* api_name) {
    if (lua_gettop(state) < index || lua_isnil(state, index)) {
        return 0;
    }
    if (!lua_istable(state, index)) {
        luaL_error(state, "%s options must be a table", api_name);
    }
    return lua_absindex(state, index);
}

float ReadOptionNumber(
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

bool ReadOptionBoolean(
    lua_State* state,
    int options_index,
    const char* field_name,
    bool default_value,
    const char* api_name) {
    if (options_index == 0) {
        return default_value;
    }
    lua_getfield(state, options_index, field_name);
    if (lua_isnil(state, -1)) {
        lua_pop(state, 1);
        return default_value;
    }
    if (!lua_isboolean(state, -1)) {
        luaL_error(
            state,
            "%s options.%s must be a boolean",
            api_name,
            field_name);
    }
    const bool value = lua_toboolean(state, -1) != 0;
    lua_pop(state, 1);
    return value;
}

std::uint8_t ReadColorChannel(
    lua_State* state,
    int color_index,
    const char* field_name,
    std::uint8_t default_value,
    const char* api_name) {
    lua_getfield(state, color_index, field_name);
    if (lua_isnil(state, -1)) {
        lua_pop(state, 1);
        return default_value;
    }
    if (!lua_isinteger(state, -1)) {
        luaL_error(
            state,
            "%s options.color.%s must be an integer from 0 through 255",
            api_name,
            field_name);
    }
    const auto value = lua_tointeger(state, -1);
    lua_pop(state, 1);
    if (value < 0 || value > 255) {
        luaL_error(
            state,
            "%s options.color.%s must be an integer from 0 through 255",
            api_name,
            field_name);
    }
    return static_cast<std::uint8_t>(value);
}

LuaDrawColor ReadOptionColor(
    lua_State* state,
    int options_index,
    const char* api_name) {
    LuaDrawColor color;
    if (options_index == 0) {
        return color;
    }
    lua_getfield(state, options_index, "color");
    if (lua_isnil(state, -1)) {
        lua_pop(state, 1);
        return color;
    }
    if (!lua_istable(state, -1)) {
        luaL_error(state, "%s options.color must be a table", api_name);
    }
    const int color_index = lua_absindex(state, -1);
    color.red = ReadColorChannel(state, color_index, "r", color.red, api_name);
    color.green = ReadColorChannel(state, color_index, "g", color.green, api_name);
    color.blue = ReadColorChannel(state, color_index, "b", color.blue, api_name);
    color.alpha = ReadColorChannel(state, color_index, "a", color.alpha, api_name);
    lua_pop(state, 1);
    return color;
}

int SubmitCommand(
    lua_State* state,
    const char* api_name,
    LuaDrawCommand command) {
    const auto* mod = RequireDrawMod(state, api_name);
    std::string error_message;
    if (!SubmitLuaDrawCommand(
            mod->descriptor.id,
            std::move(command),
            &error_message)) {
        return luaL_error(state, "%s", error_message.c_str());
    }
    lua_pushboolean(state, 1);
    return 1;
}

int LuaDrawText(lua_State* state) {
    constexpr const char* kApiName = "sd.draw.text";
    std::size_t text_length = 0;
    const char* text = luaL_checklstring(state, 1, &text_length);
    if (text_length == 0 || text_length > kLuaDrawMaxTextCommandBytes) {
        return luaL_error(
            state,
            "%s text must contain 1 through %zu bytes",
            kApiName,
            kLuaDrawMaxTextCommandBytes);
    }

    LuaDrawCommand command;
    command.kind = LuaDrawCommandKind::Text;
    command.text.assign(text, text_length);
    command.x = ReadFiniteNumber(
        state, 2, kApiName, "x", -kMaximumCoordinateMagnitude,
        kMaximumCoordinateMagnitude);
    command.y = ReadFiniteNumber(
        state, 3, kApiName, "y", -kMaximumCoordinateMagnitude,
        kMaximumCoordinateMagnitude);
    const int options = NormalizeOptionsIndex(state, 4, kApiName);
    command.scale = ReadOptionNumber(
        state,
        options,
        "scale",
        1.0f,
        kMinimumTextScale,
        kMaximumTextScale,
        kApiName);
    command.color = ReadOptionColor(state, options, kApiName);
    return SubmitCommand(state, kApiName, std::move(command));
}

int LuaDrawRect(lua_State* state) {
    constexpr const char* kApiName = "sd.draw.rect";
    LuaDrawCommand command;
    command.x = ReadFiniteNumber(
        state, 1, kApiName, "x", -kMaximumCoordinateMagnitude,
        kMaximumCoordinateMagnitude);
    command.y = ReadFiniteNumber(
        state, 2, kApiName, "y", -kMaximumCoordinateMagnitude,
        kMaximumCoordinateMagnitude);
    command.width = ReadFiniteNumber(
        state, 3, kApiName, "width", 0.001f, kMaximumDrawExtent);
    command.height = ReadFiniteNumber(
        state, 4, kApiName, "height", 0.001f, kMaximumDrawExtent);
    const int options = NormalizeOptionsIndex(state, 5, kApiName);
    const bool filled = ReadOptionBoolean(
        state, options, "filled", true, kApiName);
    command.kind = filled
        ? LuaDrawCommandKind::FilledRect
        : LuaDrawCommandKind::OutlinedRect;
    command.thickness = ReadOptionNumber(
        state,
        options,
        "thickness",
        1.0f,
        kMinimumLineThickness,
        kMaximumLineThickness,
        kApiName);
    command.color = ReadOptionColor(state, options, kApiName);
    return SubmitCommand(state, kApiName, std::move(command));
}

int LuaDrawLine(lua_State* state) {
    constexpr const char* kApiName = "sd.draw.line";
    LuaDrawCommand command;
    command.kind = LuaDrawCommandKind::Line;
    command.x = ReadFiniteNumber(
        state, 1, kApiName, "x1", -kMaximumCoordinateMagnitude,
        kMaximumCoordinateMagnitude);
    command.y = ReadFiniteNumber(
        state, 2, kApiName, "y1", -kMaximumCoordinateMagnitude,
        kMaximumCoordinateMagnitude);
    command.x2 = ReadFiniteNumber(
        state, 3, kApiName, "x2", -kMaximumCoordinateMagnitude,
        kMaximumCoordinateMagnitude);
    command.y2 = ReadFiniteNumber(
        state, 4, kApiName, "y2", -kMaximumCoordinateMagnitude,
        kMaximumCoordinateMagnitude);
    const int options = NormalizeOptionsIndex(state, 5, kApiName);
    command.thickness = ReadOptionNumber(
        state,
        options,
        "thickness",
        1.0f,
        kMinimumLineThickness,
        kMaximumLineThickness,
        kApiName);
    command.color = ReadOptionColor(state, options, kApiName);
    return SubmitCommand(state, kApiName, std::move(command));
}

int LuaDrawSprite(lua_State* state) {
    constexpr const char* kApiName = "sd.draw.sprite";
    std::size_t atlas_length = 0;
    const char* atlas = luaL_checklstring(state, 1, &atlas_length);
    const auto raw_sprite_index = luaL_checkinteger(state, 2);
    if (raw_sprite_index < 0 ||
        static_cast<lua_Unsigned>(raw_sprite_index) >
            (std::numeric_limits<std::uint32_t>::max)()) {
        return luaL_error(state, "%s record must be a nonnegative 32-bit integer", kApiName);
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
            "%s does not support rotated stock bundle records",
            kApiName);
    }

    LuaDrawCommand command;
    command.kind = LuaDrawCommandKind::Sprite;
    command.atlas = std::move(canonical_atlas);
    command.sprite_index = static_cast<std::uint32_t>(raw_sprite_index);
    command.x = ReadFiniteNumber(
        state, 3, kApiName, "x", -kMaximumCoordinateMagnitude,
        kMaximumCoordinateMagnitude);
    command.y = ReadFiniteNumber(
        state, 4, kApiName, "y", -kMaximumCoordinateMagnitude,
        kMaximumCoordinateMagnitude);
    const int options = NormalizeOptionsIndex(state, 5, kApiName);
    command.width = ReadOptionNumber(
        state,
        options,
        "width",
        static_cast<float>(sprite.logical_width),
        0.001f,
        kMaximumDrawExtent,
        kApiName);
    command.height = ReadOptionNumber(
        state,
        options,
        "height",
        static_cast<float>(sprite.logical_height),
        0.001f,
        kMaximumDrawExtent,
        kApiName);
    command.centered = ReadOptionBoolean(
        state, options, "centered", false, kApiName);
    command.color = ReadOptionColor(state, options, kApiName);
    return SubmitCommand(state, kApiName, std::move(command));
}

int LuaDrawWorldToScreen(lua_State* state) {
    constexpr const char* kApiName = "sd.draw.world_to_screen";
    const float world_x = ReadFiniteNumber(
        state, 1, kApiName, "x", -kMaximumCoordinateMagnitude,
        kMaximumCoordinateMagnitude);
    const float world_y = ReadFiniteNumber(
        state, 2, kApiName, "y", -kMaximumCoordinateMagnitude,
        kMaximumCoordinateMagnitude);
    float world_z = 0.0f;
    if (lua_gettop(state) >= 3 && !lua_isnil(state, 3)) {
        world_z = ReadFiniteNumber(
            state, 3, kApiName, "z", -kMaximumCoordinateMagnitude,
            kMaximumCoordinateMagnitude);
    }

    LuaDrawProjectionResult result;
    std::string error_message;
    if (!TryProjectLuaDrawWorldPoint(
            world_x,
            world_y,
            world_z,
            &result,
            &error_message)) {
        lua_pushnil(state);
        lua_pushlstring(state, error_message.data(), error_message.size());
        return 2;
    }

    lua_createtable(state, 0, 6);
    lua_pushnumber(state, result.x);
    lua_setfield(state, -2, "x");
    lua_pushnumber(state, result.y);
    lua_setfield(state, -2, "y");
    lua_pushboolean(state, result.visible ? 1 : 0);
    lua_setfield(state, -2, "visible");
    lua_pushinteger(state, result.viewport_width);
    lua_setfield(state, -2, "viewport_width");
    lua_pushinteger(state, result.viewport_height);
    lua_setfield(state, -2, "viewport_height");
    lua_pushinteger(state, static_cast<lua_Integer>(result.generation));
    lua_setfield(state, -2, "generation");
    return 1;
}

int LuaDrawGetViewport(lua_State* state) {
    std::uint32_t width = 0;
    std::uint32_t height = 0;
    std::string error_message;
    if (!TryGetLuaDrawViewport(&width, &height, &error_message)) {
        lua_pushnil(state);
        lua_pushlstring(state, error_message.data(), error_message.size());
        return 2;
    }
    lua_createtable(state, 0, 2);
    lua_pushinteger(state, width);
    lua_setfield(state, -2, "width");
    lua_pushinteger(state, height);
    lua_setfield(state, -2, "height");
    return 1;
}

int LuaDrawGetSpriteInfo(lua_State* state) {
    std::size_t atlas_length = 0;
    const char* atlas = luaL_checklstring(state, 1, &atlas_length);
    const auto raw_sprite_index = luaL_checkinteger(state, 2);
    if (raw_sprite_index < 0 ||
        static_cast<lua_Unsigned>(raw_sprite_index) >
            (std::numeric_limits<std::uint32_t>::max)()) {
        return luaL_error(
            state,
            "sd.draw.get_sprite_info record must be a nonnegative 32-bit integer");
    }

    LuaDrawSpriteInfo info;
    std::string canonical_atlas;
    std::string error_message;
    if (!TryGetLuaDrawSpriteInfo(
            std::string_view(atlas, atlas_length),
            static_cast<std::uint32_t>(raw_sprite_index),
            &info,
            &canonical_atlas,
            &error_message)) {
        lua_pushnil(state);
        lua_pushlstring(state, error_message.data(), error_message.size());
        return 2;
    }

    lua_createtable(state, 0, 13);
    lua_pushlstring(state, canonical_atlas.data(), canonical_atlas.size());
    lua_setfield(state, -2, "atlas");
    lua_pushinteger(state, raw_sprite_index);
    lua_setfield(state, -2, "record");
#define SDMOD_PUSH_DRAW_NUMBER(field, value) \
    lua_pushnumber(state, static_cast<lua_Number>(value)); \
    lua_setfield(state, -2, field)
    SDMOD_PUSH_DRAW_NUMBER("atlas_x", info.atlas_x);
    SDMOD_PUSH_DRAW_NUMBER("atlas_y", info.atlas_y);
    SDMOD_PUSH_DRAW_NUMBER("packed_width", info.packed_width);
    SDMOD_PUSH_DRAW_NUMBER("packed_height", info.packed_height);
    SDMOD_PUSH_DRAW_NUMBER("logical_width", info.logical_width);
    SDMOD_PUSH_DRAW_NUMBER("logical_height", info.logical_height);
    SDMOD_PUSH_DRAW_NUMBER("content_width", info.content_width);
    SDMOD_PUSH_DRAW_NUMBER("content_height", info.content_height);
    SDMOD_PUSH_DRAW_NUMBER("center_offset_x", info.center_offset_x);
    SDMOD_PUSH_DRAW_NUMBER("center_offset_y", info.center_offset_y);
#undef SDMOD_PUSH_DRAW_NUMBER
    lua_pushboolean(state, info.rotated ? 1 : 0);
    lua_setfield(state, -2, "rotated");
    return 1;
}

int LuaDrawGetLimits(lua_State* state) {
    lua_createtable(state, 0, 4);
    lua_pushinteger(state, kLuaDrawMaxCommandsPerMod);
    lua_setfield(state, -2, "commands_per_mod_frame");
    lua_pushinteger(state, kLuaDrawMaxTextBytesPerMod);
    lua_setfield(state, -2, "text_bytes_per_mod_frame");
    lua_pushinteger(state, kLuaDrawMaxTextCommandBytes);
    lua_setfield(state, -2, "text_bytes_per_command");
    lua_pushinteger(state, 28);
    lua_setfield(state, -2, "stock_atlas_count");
    return 1;
}

}  // namespace

void RegisterLuaDrawBindings(lua_State* state) {
    lua_createtable(state, 0, 8);
    RegisterFunction(state, &LuaDrawText, "text");
    RegisterFunction(state, &LuaDrawRect, "rect");
    RegisterFunction(state, &LuaDrawLine, "line");
    RegisterFunction(state, &LuaDrawSprite, "sprite");
    RegisterFunction(state, &LuaDrawWorldToScreen, "world_to_screen");
    RegisterFunction(state, &LuaDrawGetViewport, "get_viewport");
    RegisterFunction(state, &LuaDrawGetSpriteInfo, "get_sprite_info");
    RegisterFunction(state, &LuaDrawGetLimits, "get_limits");
    lua_pushvalue(state, -1);
    lua_setfield(state, -3, "hud");
    lua_setfield(state, -2, "draw");
}

}  // namespace sdmod::detail
