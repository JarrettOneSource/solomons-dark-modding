#include "lua_engine_bindings_internal.h"

#include "lua_engine.h"
#include "mod_loader.h"
#include "multiplayer_local_transport.h"

#include <algorithm>
#include <array>
#include <cstdint>
#include <string>
#include <string_view>
#include <utility>

namespace sdmod::detail {
namespace {

constexpr std::size_t kLuaMaximumRegisteredItemsPerMod = 256;
constexpr std::size_t kLuaMaximumItemRecipeNameBytes = 128;
constexpr std::size_t kLuaItemColorStateBytes =
    multiplayer::kParticipantVisualLinkColorBlockBytes;

struct ItemTypeBinding {
    std::string_view name;
    std::uint32_t native_type_id;
};

constexpr std::array<ItemTypeBinding, 6> kItemTypeBindings = {{
    {"ring", 7002},
    {"amulet", 7003},
    {"staff", 7004},
    {"hat", 7005},
    {"robe", 7006},
    {"wand", 7011},
}};

const ItemTypeBinding* FindItemTypeBinding(std::string_view item_type) {
    const auto found = std::find_if(
        kItemTypeBindings.begin(),
        kItemTypeBindings.end(),
        [item_type](const ItemTypeBinding& binding) {
            return binding.name == item_type;
        });
    return found == kItemTypeBindings.end() ? nullptr : &*found;
}

bool IsKnownItemRegistrationField(std::string_view field) {
    return field == "key" || field == "name" || field == "type" ||
        field == "description" || field == "icon" ||
        field == "duration_ms" || field == "on_consume" ||
        field == "consume_vfx";
}

bool IsKnownItemGrantOptionField(std::string_view field) {
    return field == "participant_id" || field == "color_state";
}

int RejectUnknownItemGrantOptionFields(lua_State* state, int table_index) {
    const int absolute_index = lua_absindex(state, table_index);
    lua_pushnil(state);
    while (lua_next(state, absolute_index) != 0) {
        if (lua_type(state, -2) != LUA_TSTRING) {
            lua_pop(state, 2);
            return luaL_error(
                state,
                "sd.items.grant options accept only named participant_id and color_state fields");
        }
        std::size_t field_length = 0;
        const auto* field = lua_tolstring(state, -2, &field_length);
        const std::string_view field_name(field, field_length);
        if (!IsKnownItemGrantOptionField(field_name)) {
            const std::string owned_field(field_name);
            lua_pop(state, 2);
            return luaL_error(
                state,
                "sd.items.grant received unknown option '%s'",
                owned_field.c_str());
        }
        lua_pop(state, 1);
    }
    return 0;
}

void ReadItemGrantColorState(
    lua_State* state,
    int table_index,
    std::array<std::uint8_t, kLuaItemColorStateBytes>* color_state,
    bool* color_state_valid) {
    *color_state = {};
    *color_state_valid = false;
    lua_getfield(state, table_index, "color_state");
    if (lua_isnil(state, -1)) {
        lua_pop(state, 1);
        return;
    }
    if (!lua_istable(state, -1) ||
        lua_rawlen(state, -1) != kLuaItemColorStateBytes) {
        luaL_error(
            state,
            "sd.items.grant color_state must contain exactly %zu bytes",
            kLuaItemColorStateBytes);
    }
    const int color_table_index = lua_absindex(state, -1);
    for (std::size_t index = 0; index < kLuaItemColorStateBytes; ++index) {
        lua_geti(state, color_table_index, static_cast<lua_Integer>(index + 1));
        if (!lua_isinteger(state, -1)) {
            luaL_error(
                state,
                "sd.items.grant color_state byte %zu must be an integer from 0 through 255",
                index + 1);
        }
        const auto value = lua_tointeger(state, -1);
        if (value < 0 || value > 255) {
            luaL_error(
                state,
                "sd.items.grant color_state byte %zu must be an integer from 0 through 255",
                index + 1);
        }
        (*color_state)[index] = static_cast<std::uint8_t>(value);
        lua_pop(state, 1);
    }
    lua_pushnil(state);
    while (lua_next(state, color_table_index) != 0) {
        const bool valid_index =
            lua_isinteger(state, -2) &&
            lua_tointeger(state, -2) >= 1 &&
            lua_tointeger(state, -2) <=
                static_cast<lua_Integer>(kLuaItemColorStateBytes);
        lua_pop(state, 1);
        if (!valid_index) {
            luaL_error(
                state,
                "sd.items.grant color_state must be a dense 1-based byte array");
        }
    }
    lua_pop(state, 1);
    *color_state_valid = true;
}

int RejectUnknownItemRegistrationFields(lua_State* state, int table_index) {
    const int absolute_index = lua_absindex(state, table_index);
    lua_pushnil(state);
    while (lua_next(state, absolute_index) != 0) {
        if (lua_type(state, -2) != LUA_TSTRING) {
            lua_pop(state, 2);
            return luaL_error(
                state,
                "sd.items.register accepts only named item descriptor fields");
        }
        std::size_t field_length = 0;
        const auto* field = lua_tolstring(state, -2, &field_length);
        const std::string_view field_name(field, field_length);
        if (!IsKnownItemRegistrationField(field_name)) {
            const std::string owned_field(field_name);
            lua_pop(state, 2);
            return luaL_error(
                state,
                "sd.items.register received unknown field '%s'",
                owned_field.c_str());
        }
        lua_pop(state, 1);
    }
    return 0;
}

std::string ReadRequiredItemString(
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

void RejectRecipeOnlyItemExtras(lua_State* state, int table_index) {
    constexpr std::array<const char*, 5> potion_only_fields = {{
        "description",
        "icon",
        "duration_ms",
        "on_consume",
        "consume_vfx",
    }};
    for (const auto* field : potion_only_fields) {
        lua_getfield(state, table_index, field);
        const bool present = !lua_isnil(state, -1);
        lua_pop(state, 1);
        if (present) {
            luaL_error(
                state,
                "sd.items.register field '%s' is valid only for type 'potion'",
                field);
        }
    }
}

bool SameNativeRecipeBinding(
    const LuaItemDefinition& definition,
    std::string_view recipe_name,
    std::uint32_t native_type_id) {
    return !definition.consumable &&
           definition.recipe_name == recipe_name &&
           definition.native_type_id == native_type_id;
}

const LuaItemDefinition* FindItemDefinitionById(std::uint64_t content_id) {
    for (const auto& loaded_mod : LoadedLuaModsStorage()) {
        const auto found = std::find_if(
            loaded_mod->item_definitions.begin(),
            loaded_mod->item_definitions.end(),
            [content_id](const LuaItemDefinition& definition) {
                return definition.identity.network_id == content_id;
            });
        if (found != loaded_mod->item_definitions.end()) {
            return &*found;
        }
    }
    return nullptr;
}

const LuaItemDefinition* FindOwnedItemDefinitionByKey(
    const LoadedLuaMod& mod,
    std::string_view key) {
    const auto found = std::find_if(
        mod.item_definitions.begin(),
        mod.item_definitions.end(),
        [key](const LuaItemDefinition& definition) {
            return definition.identity.key == key;
        });
    return found == mod.item_definitions.end() ? nullptr : &*found;
}

void PushItemDefinition(lua_State* state, const LuaItemDefinition& definition) {
    lua_createtable(state, 0, 14);
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(definition.identity.network_id));
    lua_setfield(state, -2, "id");
    lua_pushlstring(
        state,
        definition.identity.mod_id.data(),
        definition.identity.mod_id.size());
    lua_setfield(state, -2, "mod_id");
    lua_pushlstring(
        state,
        definition.identity.key.data(),
        definition.identity.key.size());
    lua_setfield(state, -2, "key");
    lua_pushlstring(
        state,
        definition.recipe_name.data(),
        definition.recipe_name.size());
    lua_setfield(state, -2, "name");
    lua_pushlstring(
        state,
        definition.item_type.data(),
        definition.item_type.size());
    lua_setfield(state, -2, "type");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(definition.native_type_id));
    lua_setfield(state, -2, "native_type_id");

    lua_pushboolean(state, definition.consumable ? 1 : 0);
    lua_setfield(state, -2, "consumable");
    if (definition.consumable) {
        lua_pushlstring(
            state,
            definition.description.data(),
            definition.description.size());
        lua_setfield(state, -2, "description");
        lua_pushinteger(
            state,
            static_cast<lua_Integer>(definition.duration_ms));
        lua_setfield(state, -2, "duration_ms");
        lua_pushinteger(
            state,
            static_cast<lua_Integer>(definition.native_subtype));
        lua_setfield(state, -2, "native_subtype");
        lua_createtable(state, 0, 2);
        lua_pushlstring(
            state,
            definition.icon_atlas.data(),
            definition.icon_atlas.size());
        lua_setfield(state, -2, "atlas");
        lua_pushinteger(
            state,
            static_cast<lua_Integer>(definition.icon_frame));
        lua_setfield(state, -2, "frame");
        lua_setfield(state, -2, "icon");
        if (definition.consume_vfx_kind != LuaConsumableVfxKind::None) {
            lua_createtable(state, 0, 2);
            lua_pushstring(state, "spell_glow");
            lua_setfield(state, -2, "kind");
            lua_createtable(state, 4, 0);
            for (std::size_t index = 0;
                 index < definition.consume_vfx_color.size();
                 ++index) {
                lua_pushnumber(
                    state,
                    static_cast<lua_Number>(
                        definition.consume_vfx_color[index]));
                lua_seti(
                    state,
                    -2,
                    static_cast<lua_Integer>(index + 1));
            }
            lua_setfield(state, -2, "color");
            lua_setfield(state, -2, "consume_vfx");
        }
        lua_pushboolean(state, 1);
        lua_setfield(state, -2, "available");
        return;
    }

    std::uint32_t recipe_uid = 0;
    std::string resolution_error;
    const bool available = TryResolveNativeItemRecipeByName(
        definition.recipe_name,
        definition.native_type_id,
        &recipe_uid,
        &resolution_error);
    lua_pushboolean(state, available ? 1 : 0);
    lua_setfield(state, -2, "available");
    if (available) {
        lua_pushinteger(state, static_cast<lua_Integer>(recipe_uid));
        lua_setfield(state, -2, "recipe_uid");
    } else {
        lua_pushlstring(
            state,
            resolution_error.data(),
            resolution_error.size());
        lua_setfield(state, -2, "unavailable_reason");
    }
}

int LuaItemsRegister(lua_State* state) {
    luaL_checktype(state, 1, LUA_TTABLE);
    RejectUnknownItemRegistrationFields(state, 1);

    auto* mod = GetLoadedLuaMod(state);
    if (mod == nullptr) {
        return luaL_error(state, "sd.items.register requires an owning Lua mod");
    }
    if (mod->item_definitions.size() >= kLuaMaximumRegisteredItemsPerMod) {
        return luaL_error(
            state,
            "sd.items.register exceeds the per-mod limit of %zu",
            kLuaMaximumRegisteredItemsPerMod);
    }

    const auto key = ReadRequiredItemString(state, 1, "key");
    const auto recipe_name = ReadRequiredItemString(state, 1, "name");
    const auto item_type = ReadRequiredItemString(state, 1, "type");
    if (recipe_name.empty() ||
        recipe_name.size() > kLuaMaximumItemRecipeNameBytes ||
        recipe_name.find('\0') != std::string::npos) {
        return luaL_error(
            state,
            "sd.items.register name must contain 1..%zu bytes",
            kLuaMaximumItemRecipeNameBytes);
    }
    const bool consumable = item_type == "potion";
    const auto* type_binding =
        consumable ? nullptr : FindItemTypeBinding(item_type);
    if (!consumable && type_binding == nullptr) {
        return luaL_error(
            state,
            "sd.items.register type must be ring, amulet, staff, hat, robe, wand, or potion");
    }

    if (!consumable) {
        RejectRecipeOnlyItemExtras(state, 1);
        for (const auto& loaded_mod : LoadedLuaModsStorage()) {
            const auto duplicate = std::find_if(
                loaded_mod->item_definitions.begin(),
                loaded_mod->item_definitions.end(),
                [&](const LuaItemDefinition& definition) {
                    return SameNativeRecipeBinding(
                        definition,
                        recipe_name,
                        type_binding->native_type_id);
                });
            if (duplicate != loaded_mod->item_definitions.end()) {
                return luaL_error(
                    state,
                    "sd.items.register native recipe is already bound by %s:%s",
                    duplicate->identity.mod_id.c_str(),
                    duplicate->identity.key.c_str());
            }
        }
    }

    LuaContentIdentity identity;
    std::string registration_error;
    if (!RegisterLuaContentIdentityForMod(
            mod,
            LuaContentKind::Item,
            key,
            &identity,
            &registration_error)) {
        return luaL_error(state, "%s", registration_error.c_str());
    }

    LuaItemDefinition definition;
    if (consumable) {
        PopulateLuaConsumableItemDefinition(
            state,
            1,
            *mod,
            std::move(identity),
            recipe_name,
            &definition);
    } else {
        definition.identity = std::move(identity);
        definition.recipe_name = recipe_name;
        definition.item_type = item_type;
        definition.native_type_id = type_binding->native_type_id;
    }
    mod->item_definitions.push_back(std::move(definition));
    PushItemDefinition(state, mod->item_definitions.back());
    return 1;
}

int LuaItemsGet(lua_State* state) {
    const LuaItemDefinition* definition = nullptr;
    if (lua_type(state, 1) == LUA_TSTRING) {
        auto* mod = GetLoadedLuaMod(state);
        if (mod == nullptr) {
            return luaL_error(state, "sd.items.get requires an owning Lua mod");
        }
        std::size_t key_length = 0;
        const auto* key = lua_tolstring(state, 1, &key_length);
        definition = FindOwnedItemDefinitionByKey(
            *mod,
            std::string_view(key, key_length));
    } else if (lua_isinteger(state, 1)) {
        const auto raw_id = lua_tointeger(state, 1);
        if (raw_id <= 0) {
            return luaL_error(state, "sd.items.get id must be a positive integer");
        }
        definition = FindItemDefinitionById(static_cast<std::uint64_t>(raw_id));
    } else {
        return luaL_error(state, "sd.items.get expects a content key or content id");
    }

    if (definition == nullptr) {
        lua_pushnil(state);
        return 1;
    }
    PushItemDefinition(state, *definition);
    return 1;
}

int LuaItemsList(lua_State* state) {
    std::size_t count = 0;
    for (const auto& loaded_mod : LoadedLuaModsStorage()) {
        count += loaded_mod->item_definitions.size();
    }
    lua_createtable(state, static_cast<int>(count), 0);
    lua_Integer output_index = 1;
    for (const auto& loaded_mod : LoadedLuaModsStorage()) {
        for (const auto& definition : loaded_mod->item_definitions) {
            PushItemDefinition(state, definition);
            lua_seti(state, -2, output_index++);
        }
    }
    return 1;
}

int LuaItemsGrant(lua_State* state) {
    if (!multiplayer::IsLuaModSimulationAuthority()) {
        return luaL_error(
            state,
            "sd.items.grant may only be called by the simulation authority");
    }
    if (lua_gettop(state) > 2) {
        return luaL_error(
            state,
            "sd.items.grant expects a content key or id and optional options table");
    }

    const LuaItemDefinition* definition = nullptr;
    if (lua_type(state, 1) == LUA_TSTRING) {
        auto* mod = GetLoadedLuaMod(state);
        if (mod == nullptr) {
            return luaL_error(state, "sd.items.grant requires an owning Lua mod");
        }
        std::size_t key_length = 0;
        const auto* key = lua_tolstring(state, 1, &key_length);
        definition = FindOwnedItemDefinitionByKey(
            *mod,
            std::string_view(key, key_length));
    } else if (lua_isinteger(state, 1)) {
        const auto raw_id = lua_tointeger(state, 1);
        if (raw_id <= 0) {
            return luaL_error(
                state,
                "sd.items.grant content id must be a positive integer");
        }
        definition = FindItemDefinitionById(static_cast<std::uint64_t>(raw_id));
    } else {
        return luaL_error(
            state,
            "sd.items.grant expects a registered content key or content id");
    }
    if (definition == nullptr) {
        return luaL_error(state, "sd.items.grant content identity is not registered");
    }
    if (definition->consumable) {
        return luaL_error(
            state,
            "sd.items.grant supports recipe-backed items; registered consumables enter inventory through sd.loot");
    }

    std::uint64_t requested_target_participant_id = 0;
    std::array<std::uint8_t, kLuaItemColorStateBytes> color_state = {};
    bool color_state_valid = false;
    if (lua_gettop(state) >= 2 && !lua_isnil(state, 2)) {
        luaL_checktype(state, 2, LUA_TTABLE);
        RejectUnknownItemGrantOptionFields(state, 2);
        lua_getfield(state, 2, "participant_id");
        if (!lua_isnil(state, -1)) {
            if (!lua_isinteger(state, -1) || lua_tointeger(state, -1) <= 0) {
                return luaL_error(
                    state,
                    "sd.items.grant participant_id must be a positive integer");
            }
            requested_target_participant_id =
                static_cast<std::uint64_t>(lua_tointeger(state, -1));
        }
        lua_pop(state, 1);
        ReadItemGrantColorState(
            state,
            2,
            &color_state,
            &color_state_valid);
    }

    const bool wearable =
        definition->native_type_id == 7005 ||
        definition->native_type_id == 7006;
    if (color_state_valid && !wearable) {
        return luaL_error(
            state,
            "sd.items.grant color_state is valid only for hats and robes");
    }

    std::uint64_t request_id = 0;
    std::uint64_t target_participant_id = 0;
    bool local_target = false;
    std::string error_message;
    if (!multiplayer::QueueAuthoritativeLuaItemGrant(
            definition->identity.network_id,
            requested_target_participant_id,
            color_state,
            color_state_valid,
            &request_id,
            &target_participant_id,
            &local_target,
            &error_message)) {
        return luaL_error(
            state,
            "sd.items.grant failed: %s",
            error_message.c_str());
    }

    lua_createtable(state, 0, 4);
    lua_pushinteger(state, static_cast<lua_Integer>(request_id));
    lua_setfield(state, -2, "request_id");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(definition->identity.network_id));
    lua_setfield(state, -2, "content_id");
    lua_pushinteger(state, static_cast<lua_Integer>(target_participant_id));
    lua_setfield(state, -2, "target_participant_id");
    lua_pushboolean(state, local_target ? 1 : 0);
    lua_setfield(state, -2, "local_target");
    return 1;
}

}  // namespace

bool TryResolveLuaItemNativeRecipeUnlocked(
    std::uint64_t content_id,
    std::uint32_t* item_type_id,
    std::uint32_t* recipe_uid,
    std::string* error_message) {
    if (item_type_id != nullptr) {
        *item_type_id = 0;
    }
    if (recipe_uid != nullptr) {
        *recipe_uid = 0;
    }
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (content_id == 0 || item_type_id == nullptr || recipe_uid == nullptr) {
        if (error_message != nullptr) {
            *error_message = "Lua item lookup requires a registered content id.";
        }
        return false;
    }
    const auto* definition = FindItemDefinitionById(content_id);
    if (definition == nullptr) {
        if (error_message != nullptr) {
            *error_message = "Lua item content identity is not registered.";
        }
        return false;
    }
    if (definition->consumable) {
        if (error_message != nullptr) {
            *error_message =
                "Lua consumables do not bind a stock item recipe.";
        }
        return false;
    }
    if (!TryResolveNativeItemRecipeByName(
            definition->recipe_name,
            definition->native_type_id,
            recipe_uid,
            error_message)) {
        return false;
    }
    *item_type_id = definition->native_type_id;
    return true;
}

void RegisterLuaItemBindings(lua_State* state) {
    lua_createtable(state, 0, 4);
    RegisterFunction(state, &LuaItemsRegister, "register");
    RegisterFunction(state, &LuaItemsGet, "get");
    RegisterFunction(state, &LuaItemsList, "list");
    RegisterFunction(state, &LuaItemsGrant, "grant");
    lua_setfield(state, -2, "items");
}

}  // namespace sdmod::detail

namespace sdmod {

bool TryResolveLuaItemNativeRecipe(
    std::uint64_t content_id,
    std::uint32_t* item_type_id,
    std::uint32_t* recipe_uid,
    std::string* error_message) {
    std::lock_guard<std::mutex> lock(detail::LuaEngineMutex());
    return detail::TryResolveLuaItemNativeRecipeUnlocked(
        content_id,
        item_type_id,
        recipe_uid,
        error_message);
}

}  // namespace sdmod
