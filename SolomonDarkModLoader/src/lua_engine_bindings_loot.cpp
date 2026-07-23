#include "lua_engine_bindings_internal.h"

#include "lua_item_runtime.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <string>
#include <string_view>

namespace sdmod::detail {
namespace {

bool IsKnownLootRegistrationField(std::string_view field) {
    return field == "item" || field == "chance" ||
        field == "boss_chance";
}

void RejectUnknownLootRegistrationFields(
    lua_State* state,
    int table_index) {
    const int absolute_index = lua_absindex(state, table_index);
    lua_pushnil(state);
    while (lua_next(state, absolute_index) != 0) {
        if (lua_type(state, -2) != LUA_TSTRING) {
            lua_pop(state, 2);
            luaL_error(
                state,
                "sd.loot.register accepts only named item, chance, and boss_chance fields");
        }
        std::size_t field_length = 0;
        const auto* field = lua_tolstring(state, -2, &field_length);
        const std::string_view field_name(field, field_length);
        if (!IsKnownLootRegistrationField(field_name)) {
            const std::string owned_field(field_name);
            lua_pop(state, 2);
            luaL_error(
                state,
                "sd.loot.register received unknown field '%s'",
                owned_field.c_str());
        }
        lua_pop(state, 1);
    }
}

const LuaItemDefinition* FindOwnedConsumable(
    const LoadedLuaMod& mod,
    std::string_view key) {
    const auto found = std::find_if(
        mod.item_definitions.begin(),
        mod.item_definitions.end(),
        [&](const LuaItemDefinition& definition) {
            return definition.consumable &&
                definition.identity.key == key;
        });
    return found == mod.item_definitions.end() ? nullptr : &*found;
}

const LuaItemDefinition* FindConsumableById(std::uint64_t content_id) {
    for (const auto& mod : LoadedLuaModsStorage()) {
        const auto found = std::find_if(
            mod->item_definitions.begin(),
            mod->item_definitions.end(),
            [&](const LuaItemDefinition& definition) {
                return definition.consumable &&
                    definition.identity.network_id == content_id;
            });
        if (found != mod->item_definitions.end()) {
            return &*found;
        }
    }
    return nullptr;
}

const LuaItemDefinition* ReadLootItem(
    lua_State* state,
    int table_index,
    const LoadedLuaMod& owner) {
    lua_getfield(state, table_index, "item");
    const LuaItemDefinition* definition = nullptr;
    if (lua_type(state, -1) == LUA_TSTRING) {
        std::size_t key_length = 0;
        const auto* key = lua_tolstring(state, -1, &key_length);
        definition = FindOwnedConsumable(
            owner,
            std::string_view(key, key_length));
    } else if (lua_isinteger(state, -1) && lua_tointeger(state, -1) > 0) {
        definition = FindConsumableById(
            static_cast<std::uint64_t>(lua_tointeger(state, -1)));
    } else {
        lua_pop(state, 1);
        luaL_error(
            state,
            "sd.loot.register item must be a registered consumable key or positive content id");
    }
    lua_pop(state, 1);
    if (definition == nullptr) {
        luaL_error(
            state,
            "sd.loot.register item is not a registered consumable");
    }
    return definition;
}

double ReadLootChance(
    lua_State* state,
    int table_index,
    const char* field_name) {
    lua_getfield(state, table_index, field_name);
    if (lua_type(state, -1) != LUA_TNUMBER) {
        lua_pop(state, 1);
        luaL_error(
            state,
            "sd.loot.register %s must be a number in 0 through 1",
            field_name);
    }
    const auto chance = lua_tonumber(state, -1);
    lua_pop(state, 1);
    if (!std::isfinite(chance) || chance < 0.0 || chance > 1.0) {
        luaL_error(
            state,
            "sd.loot.register %s must be a finite number in 0 through 1",
            field_name);
    }
    return static_cast<double>(chance);
}

void PushLootEntry(lua_State* state, const LuaLootPoolEntry& entry) {
    lua_createtable(state, 0, 4);
    lua_pushlstring(state, entry.mod_id.data(), entry.mod_id.size());
    lua_setfield(state, -2, "mod_id");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(entry.item_content_id));
    lua_setfield(state, -2, "item");
    lua_pushnumber(state, static_cast<lua_Number>(entry.normal_chance));
    lua_setfield(state, -2, "chance");
    lua_pushnumber(state, static_cast<lua_Number>(entry.boss_chance));
    lua_setfield(state, -2, "boss_chance");
}

int LuaLootRegister(lua_State* state) {
    luaL_checktype(state, 1, LUA_TTABLE);
    RejectUnknownLootRegistrationFields(state, 1);
    auto* mod = GetLoadedLuaMod(state);
    if (mod == nullptr || !mod->content_registration_open) {
        return luaL_error(
            state,
            "sd.loot.register is available only while the owning mod is loading");
    }

    const auto* definition = ReadLootItem(state, 1, *mod);
    LuaLootPoolEntry entry;
    entry.mod_id = mod->descriptor.id;
    entry.item_content_id = definition->identity.network_id;
    entry.normal_chance = ReadLootChance(state, 1, "chance");
    entry.boss_chance = ReadLootChance(state, 1, "boss_chance");

    std::string error_message;
    if (!RegisterLuaLootPoolEntry(entry, &error_message)) {
        return luaL_error(
            state,
            "sd.loot.register failed: %s",
            error_message.c_str());
    }
    PushLootEntry(state, entry);
    return 1;
}

int LuaLootList(lua_State* state) {
    const auto entries = SnapshotLuaLootPool();
    lua_createtable(state, static_cast<int>(entries.size()), 0);
    lua_Integer index = 1;
    for (const auto& entry : entries) {
        PushLootEntry(state, entry);
        lua_seti(state, -2, index++);
    }
    return 1;
}

}  // namespace

void RegisterLuaLootBindings(lua_State* state) {
    lua_createtable(state, 0, 2);
    RegisterFunction(state, &LuaLootRegister, "register");
    RegisterFunction(state, &LuaLootList, "list");
    lua_setfield(state, -2, "loot");
}

}  // namespace sdmod::detail
