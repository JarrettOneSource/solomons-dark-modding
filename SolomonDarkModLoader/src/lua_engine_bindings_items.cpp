#include "lua_engine_bindings_internal.h"

#include "mod_loader.h"

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
    return field == "key" || field == "name" || field == "type";
}

int RejectUnknownItemRegistrationFields(lua_State* state, int table_index) {
    const int absolute_index = lua_absindex(state, table_index);
    lua_pushnil(state);
    while (lua_next(state, absolute_index) != 0) {
        if (lua_type(state, -2) != LUA_TSTRING) {
            lua_pop(state, 2);
            return luaL_error(
                state,
                "sd.items.register accepts only named key, name, and type fields");
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

bool SameNativeRecipeBinding(
    const LuaItemDefinition& definition,
    std::string_view recipe_name,
    std::uint32_t native_type_id) {
    return definition.recipe_name == recipe_name &&
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
    lua_createtable(state, 0, 9);
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
    const auto* type_binding = FindItemTypeBinding(item_type);
    if (type_binding == nullptr) {
        return luaL_error(
            state,
            "sd.items.register type must be ring, amulet, staff, hat, robe, or wand");
    }

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
    definition.identity = std::move(identity);
    definition.recipe_name = recipe_name;
    definition.item_type = item_type;
    definition.native_type_id = type_binding->native_type_id;
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

}  // namespace

void RegisterLuaItemBindings(lua_State* state) {
    lua_createtable(state, 0, 3);
    RegisterFunction(state, &LuaItemsRegister, "register");
    RegisterFunction(state, &LuaItemsGet, "get");
    RegisterFunction(state, &LuaItemsList, "list");
    lua_setfield(state, -2, "items");
}

}  // namespace sdmod::detail
