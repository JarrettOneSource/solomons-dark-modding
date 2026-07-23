#include "lua_engine_bindings_internal.h"

#include "lua_item_runtime.h"
#include "lua_sprite_runtime.h"

#include <cstdint>
#include <cmath>
#include <limits>
#include <string>
#include <string_view>
#include <utility>

namespace sdmod::detail {
namespace {

constexpr std::size_t kLuaMaximumItemDescriptionBytes = 1024;

void ReadConsumableVfx(
    lua_State* state,
    int table_index,
    LuaConsumableVfxKind* kind,
    std::array<float, 4>* color) {
    *kind = LuaConsumableVfxKind::None;
    *color = {0.25f, 1.0f, 0.35f, 1.0f};
    lua_getfield(state, table_index, "consume_vfx");
    if (lua_isnil(state, -1)) {
        lua_pop(state, 1);
        return;
    }
    if (!lua_istable(state, -1)) {
        lua_pop(state, 1);
        luaL_error(
            state,
            "sd.items.register potion consume_vfx must be a table");
    }

    const int vfx_index = lua_absindex(state, -1);
    lua_pushnil(state);
    while (lua_next(state, vfx_index) != 0) {
        if (lua_type(state, -2) != LUA_TSTRING) {
            lua_pop(state, 3);
            luaL_error(
                state,
                "sd.items.register potion consume_vfx accepts only kind and color");
        }
        std::size_t field_length = 0;
        const auto* field = lua_tolstring(state, -2, &field_length);
        const std::string_view field_name(field, field_length);
        lua_pop(state, 1);
        if (field_name != "kind" && field_name != "color") {
            const std::string owned_field(field_name);
            lua_pop(state, 2);
            luaL_error(
                state,
                "sd.items.register potion consume_vfx received unknown field '%s'",
                owned_field.c_str());
        }
    }

    lua_getfield(state, vfx_index, "kind");
    if (lua_type(state, -1) != LUA_TSTRING) {
        lua_pop(state, 2);
        luaL_error(
            state,
            "sd.items.register potion consume_vfx.kind must be 'spell_glow'");
    }
    std::size_t kind_length = 0;
    const auto* kind_text = lua_tolstring(state, -1, &kind_length);
    const std::string_view kind_name(kind_text, kind_length);
    lua_pop(state, 1);
    if (kind_name != "spell_glow") {
        lua_pop(state, 1);
        luaL_error(
            state,
            "sd.items.register potion consume_vfx.kind must be 'spell_glow'");
    }

    lua_getfield(state, vfx_index, "color");
    if (!lua_istable(state, -1) || lua_rawlen(state, -1) != color->size()) {
        lua_pop(state, 2);
        luaL_error(
            state,
            "sd.items.register potion consume_vfx.color must contain exactly four RGBA numbers");
    }
    const int color_index = lua_absindex(state, -1);
    for (std::size_t index = 0; index < color->size(); ++index) {
        lua_geti(
            state,
            color_index,
            static_cast<lua_Integer>(index + 1));
        if (lua_type(state, -1) != LUA_TNUMBER) {
            lua_pop(state, 3);
            luaL_error(
                state,
                "sd.items.register potion consume_vfx.color values must be numbers in 0 through 1");
        }
        const auto component = lua_tonumber(state, -1);
        lua_pop(state, 1);
        if (!std::isfinite(component) || component < 0.0 || component > 1.0) {
            lua_pop(state, 2);
            luaL_error(
                state,
                "sd.items.register potion consume_vfx.color values must be finite numbers in 0 through 1");
        }
        (*color)[index] = static_cast<float>(component);
    }
    lua_pushnil(state);
    while (lua_next(state, color_index) != 0) {
        const bool valid_index =
            lua_isinteger(state, -2) &&
            lua_tointeger(state, -2) >= 1 &&
            lua_tointeger(state, -2) <=
                static_cast<lua_Integer>(color->size());
        lua_pop(state, 1);
        if (!valid_index) {
            lua_pop(state, 2);
            luaL_error(
                state,
                "sd.items.register potion consume_vfx.color must be a dense 1-based RGBA array");
        }
    }
    lua_pop(state, 2);
    *kind = LuaConsumableVfxKind::SpellGlow;
}

std::string ReadRequiredConsumableString(
    lua_State* state,
    int table_index,
    const char* field_name) {
    lua_getfield(state, table_index, field_name);
    if (lua_type(state, -1) != LUA_TSTRING) {
        luaL_error(
            state,
            "sd.items.register requires string field '%s'",
            field_name);
    }
    std::size_t length = 0;
    const auto* value = lua_tolstring(state, -1, &length);
    std::string result(value, length);
    lua_pop(state, 1);
    return result;
}

std::uint32_t ReadRequiredConsumableDuration(
    lua_State* state,
    int table_index) {
    lua_getfield(state, table_index, "duration_ms");
    if (!lua_isinteger(state, -1)) {
        luaL_error(
            state,
            "sd.items.register potion duration_ms must be an integer");
    }
    const auto duration = lua_tointeger(state, -1);
    lua_pop(state, 1);
    if (duration < 0 ||
        duration > static_cast<lua_Integer>(kLuaMaximumConsumableDurationMs)) {
        luaL_error(
            state,
            "sd.items.register potion duration_ms must be in 0..%u",
            kLuaMaximumConsumableDurationMs);
    }
    return static_cast<std::uint32_t>(duration);
}

void ReadConsumableIcon(
    lua_State* state,
    int table_index,
    const LoadedLuaMod& mod,
    std::string* canonical_atlas,
    std::uint32_t* frame) {
    lua_getfield(state, table_index, "icon");
    if (!lua_istable(state, -1)) {
        luaL_error(
            state,
            "sd.items.register potion icon must be a table");
    }
    const int icon_index = lua_absindex(state, -1);
    lua_pushnil(state);
    while (lua_next(state, icon_index) != 0) {
        if (lua_type(state, -2) != LUA_TSTRING) {
            lua_pop(state, 3);
            luaL_error(
                state,
                "sd.items.register potion icon accepts only atlas and frame");
        }
        std::size_t field_length = 0;
        const auto* field = lua_tolstring(state, -2, &field_length);
        const std::string_view field_name(field, field_length);
        lua_pop(state, 1);
        if (field_name != "atlas" && field_name != "frame") {
            const std::string owned_field(field_name);
            lua_pop(state, 2);
            luaL_error(
                state,
                "sd.items.register potion icon received unknown field '%s'",
                owned_field.c_str());
        }
    }

    lua_getfield(state, icon_index, "atlas");
    if (lua_type(state, -1) != LUA_TSTRING) {
        lua_pop(state, 2);
        luaL_error(
            state,
            "sd.items.register potion icon.atlas must be a registered sprite key");
    }
    std::size_t atlas_length = 0;
    const auto* atlas_key = lua_tolstring(state, -1, &atlas_length);
    const auto atlas = FindLuaSpriteAtlas(
        mod.descriptor.id,
        std::string_view(atlas_key, atlas_length));
    lua_pop(state, 1);
    if (!atlas.has_value()) {
        lua_pop(state, 1);
        luaL_error(
            state,
            "sd.items.register potion icon.atlas is not registered by this mod");
    }

    lua_getfield(state, icon_index, "frame");
    if (!lua_isinteger(state, -1) || lua_tointeger(state, -1) < 0) {
        lua_pop(state, 2);
        luaL_error(
            state,
            "sd.items.register potion icon.frame must be a non-negative integer");
    }
    const auto raw_frame = lua_tointeger(state, -1);
    lua_pop(state, 2);
    if (raw_frame >
        static_cast<lua_Integer>((std::numeric_limits<std::uint32_t>::max)())) {
        luaL_error(
            state,
            "sd.items.register potion icon.frame exceeds the runtime bound");
    }

    LuaDrawSpriteInfo sprite_info;
    std::string resolved_atlas;
    std::string sprite_error;
    if (!TryGetLuaRegisteredSpriteInfo(
            atlas->id,
            static_cast<std::uint32_t>(raw_frame),
            &sprite_info,
            &resolved_atlas,
            &sprite_error)) {
        luaL_error(
            state,
            "sd.items.register potion icon is invalid: %s",
            sprite_error.c_str());
    }
    *canonical_atlas = std::move(resolved_atlas);
    *frame = static_cast<std::uint32_t>(raw_frame);
}

}  // namespace

void PopulateLuaConsumableItemDefinition(
    lua_State* state,
    int table_index,
    LoadedLuaMod& mod,
    LuaContentIdentity identity,
    std::string item_name,
    LuaItemDefinition* definition) {
    if (definition == nullptr) {
        luaL_error(state, "sd.items.register potion received no output definition");
    }

    auto description =
        ReadRequiredConsumableString(state, table_index, "description");
    if (description.empty() ||
        description.size() > kLuaMaximumItemDescriptionBytes ||
        description.find('\0') != std::string::npos) {
        luaL_error(
            state,
            "sd.items.register description must contain 1..%zu bytes",
            kLuaMaximumItemDescriptionBytes);
    }

    std::string icon_atlas;
    std::uint32_t icon_frame = 0;
    ReadConsumableIcon(
        state,
        table_index,
        mod,
        &icon_atlas,
        &icon_frame);
    const auto duration_ms =
        ReadRequiredConsumableDuration(state, table_index);
    LuaConsumableVfxKind consume_vfx_kind = LuaConsumableVfxKind::None;
    std::array<float, 4> consume_vfx_color{};
    ReadConsumableVfx(
        state,
        table_index,
        &consume_vfx_kind,
        &consume_vfx_color);

    lua_getfield(state, table_index, "on_consume");
    if (!lua_isfunction(state, -1)) {
        lua_pop(state, 1);
        luaL_error(
            state,
            "sd.items.register potion on_consume must be a function");
    }
    lua_pop(state, 1);

    LuaConsumableDefinition runtime_definition;
    runtime_definition.content_id = identity.network_id;
    runtime_definition.mod_id = identity.mod_id;
    runtime_definition.key = identity.key;
    runtime_definition.name = item_name;
    runtime_definition.description = description;
    runtime_definition.icon_atlas = icon_atlas;
    runtime_definition.icon_frame = icon_frame;
    runtime_definition.duration_ms = duration_ms;
    runtime_definition.consume_vfx_kind = consume_vfx_kind;
    runtime_definition.consume_vfx_color = consume_vfx_color;

    LuaConsumableDefinition registered;
    std::string consumable_error;
    if (!RegisterLuaConsumableDefinition(
            std::move(runtime_definition),
            &registered,
            &consumable_error)) {
        luaL_error(
            state,
            "sd.items.register potion failed: %s",
            consumable_error.c_str());
    }

    definition->identity = std::move(identity);
    definition->recipe_name = std::move(item_name);
    definition->item_type = "potion";
    definition->native_type_id = 7001;
    definition->description = std::move(description);
    definition->icon_atlas = std::move(icon_atlas);
    definition->icon_frame = icon_frame;
    definition->duration_ms = duration_ms;
    definition->native_subtype = registered.native_subtype;
    definition->consume_vfx_kind = consume_vfx_kind;
    definition->consume_vfx_color = consume_vfx_color;
    definition->consumable = true;
    lua_getfield(state, table_index, "on_consume");
    definition->on_consume_reference =
        luaL_ref(state, LUA_REGISTRYINDEX);
}

}  // namespace sdmod::detail
