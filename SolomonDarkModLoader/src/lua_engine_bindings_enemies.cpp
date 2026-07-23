#include "lua_engine_bindings_internal.h"

#include "mod_loader.h"
#include "multiplayer_local_transport.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <string>
#include <string_view>
#include <utility>

namespace sdmod::detail {
namespace {

constexpr std::size_t kLuaMaximumRegisteredEnemiesPerMod = 256;
constexpr float kMaximumEnemySpawnValue = 1'000'000.0f;
constexpr float kMinimumEnemyScale = 0.01f;
constexpr float kMaximumEnemyScale = 1'000.0f;

struct EnemyBaseBinding {
    std::string_view name;
    std::uint32_t native_type_id;
};

constexpr std::array<EnemyBaseBinding, 15> kEnemyBaseBindings = {{
    {"skeleton", 0x3E9},
    {"skeleton_archer", 0x3EA},
    {"skeleton_mage", 0x3EB},
    {"imp", 0x3EC},
    {"zombie", 0x3EE},
    {"wraith", 0x3EF},
    {"demon_skull", 0x3F0},
    {"demon", 0x3F1},
    {"dire_faculty", 0x3F2},
    {"heartmonger", 0x3F3},
    {"coffin", 0x3F5},
    {"green_imp", 0x7FC},
    {"maggot", 0x7FD},
    {"spider", 0x809},
    {"portal", 0x139D},
}};

const EnemyBaseBinding* FindEnemyBaseBinding(std::string_view base_name) {
    const auto found = std::find_if(
        kEnemyBaseBindings.begin(),
        kEnemyBaseBindings.end(),
        [base_name](const EnemyBaseBinding& binding) {
            return binding.name == base_name;
        });
    return found == kEnemyBaseBindings.end() ? nullptr : &*found;
}

const char* EnemyLootPolicyName(LuaEnemyLootPolicy policy) {
    switch (policy) {
    case LuaEnemyLootPolicy::Stock:
        return "stock";
    case LuaEnemyLootPolicy::None:
        return "none";
    case LuaEnemyLootPolicy::Orb:
        return "orb";
    case LuaEnemyLootPolicy::Gold:
        return "gold";
    case LuaEnemyLootPolicy::Item:
        return "item";
    case LuaEnemyLootPolicy::Powerup:
        return "powerup";
    case LuaEnemyLootPolicy::Potion:
        return "potion";
    }
    return "stock";
}

bool TryParseEnemyLootPolicy(
    std::string_view name,
    LuaEnemyLootPolicy* policy) {
    if (policy == nullptr) {
        return false;
    }
    if (name == "stock") {
        *policy = LuaEnemyLootPolicy::Stock;
    } else if (name == "none") {
        *policy = LuaEnemyLootPolicy::None;
    } else if (name == "orb") {
        *policy = LuaEnemyLootPolicy::Orb;
    } else if (name == "gold") {
        *policy = LuaEnemyLootPolicy::Gold;
    } else if (name == "item") {
        *policy = LuaEnemyLootPolicy::Item;
    } else if (name == "powerup") {
        *policy = LuaEnemyLootPolicy::Powerup;
    } else if (name == "potion") {
        *policy = LuaEnemyLootPolicy::Potion;
    } else {
        return false;
    }
    return true;
}

SDModLuaEnemyLootPolicy ToRuntimeLootPolicy(LuaEnemyLootPolicy policy) {
    switch (policy) {
    case LuaEnemyLootPolicy::Stock:
        return SDModLuaEnemyLootPolicy::Stock;
    case LuaEnemyLootPolicy::None:
        return SDModLuaEnemyLootPolicy::None;
    case LuaEnemyLootPolicy::Orb:
        return SDModLuaEnemyLootPolicy::Orb;
    case LuaEnemyLootPolicy::Gold:
        return SDModLuaEnemyLootPolicy::Gold;
    case LuaEnemyLootPolicy::Item:
        return SDModLuaEnemyLootPolicy::Item;
    case LuaEnemyLootPolicy::Powerup:
        return SDModLuaEnemyLootPolicy::Powerup;
    case LuaEnemyLootPolicy::Potion:
        return SDModLuaEnemyLootPolicy::Potion;
    }
    return SDModLuaEnemyLootPolicy::Stock;
}

bool IsKnownEnemyRegistrationField(std::string_view field) {
    return field == "key" || field == "base" || field == "hp" ||
        field == "speed" || field == "scale" || field == "loot";
}

bool IsKnownEnemySpawnOptionField(std::string_view field) {
    return field == "x" || field == "y" || field == "hp" ||
        field == "speed" || field == "scale" || field == "loot";
}

int RejectUnknownEnemyFields(
    lua_State* state,
    int table_index,
    bool registration) {
    const int absolute_index = lua_absindex(state, table_index);
    lua_pushnil(state);
    while (lua_next(state, absolute_index) != 0) {
        if (lua_type(state, -2) != LUA_TSTRING) {
            lua_pop(state, 2);
            return luaL_error(
                state,
                registration
                    ? "sd.enemies.register accepts only named fields"
                    : "sd.enemies.spawn options accept only named fields");
        }
        std::size_t field_length = 0;
        const auto* field = lua_tolstring(state, -2, &field_length);
        const std::string_view field_name(field, field_length);
        const bool known = registration
            ? IsKnownEnemyRegistrationField(field_name)
            : IsKnownEnemySpawnOptionField(field_name);
        if (!known) {
            const std::string owned_field(field_name);
            lua_pop(state, 2);
            return luaL_error(
                state,
                registration
                    ? "sd.enemies.register received unknown field '%s'"
                    : "sd.enemies.spawn received unknown option '%s'",
                owned_field.c_str());
        }
        lua_pop(state, 1);
    }
    return 0;
}

std::string ReadRequiredEnemyString(
    lua_State* state,
    int table_index,
    const char* operation,
    const char* field_name) {
    lua_getfield(state, table_index, field_name);
    if (lua_type(state, -1) != LUA_TSTRING) {
        luaL_error(
            state,
            "%s requires string field '%s'",
            operation,
            field_name);
    }
    std::size_t length = 0;
    const auto* value = lua_tolstring(state, -1, &length);
    std::string result(value, length);
    lua_pop(state, 1);
    return result;
}

float ReadEnemyNumber(
    lua_State* state,
    int table_index,
    const char* operation,
    const char* field_name,
    bool required,
    float minimum,
    float maximum,
    bool* valid) {
    *valid = false;
    lua_getfield(state, table_index, field_name);
    if (lua_isnil(state, -1) && !required) {
        lua_pop(state, 1);
        return 0.0f;
    }
    if (lua_type(state, -1) != LUA_TNUMBER) {
        luaL_error(
            state,
            "%s field '%s' must be a number",
            operation,
            field_name);
    }
    const auto value = lua_tonumber(state, -1);
    lua_pop(state, 1);
    if (!std::isfinite(value) || value < minimum || value > maximum) {
        luaL_error(
            state,
            "%s field '%s' is outside the supported native range",
            operation,
            field_name);
    }
    *valid = true;
    return static_cast<float>(value);
}

LuaEnemyLootPolicy ReadEnemyLootPolicy(
    lua_State* state,
    int table_index,
    const char* operation,
    LuaEnemyLootPolicy default_policy) {
    lua_getfield(state, table_index, "loot");
    if (lua_isnil(state, -1)) {
        lua_pop(state, 1);
        return default_policy;
    }
    if (lua_type(state, -1) != LUA_TSTRING) {
        luaL_error(state, "%s field 'loot' must be a string", operation);
    }
    std::size_t length = 0;
    const auto* value = lua_tolstring(state, -1, &length);
    LuaEnemyLootPolicy policy = LuaEnemyLootPolicy::Stock;
    const bool parsed = TryParseEnemyLootPolicy(
        std::string_view(value, length),
        &policy);
    lua_pop(state, 1);
    if (!parsed) {
        luaL_error(
            state,
            "%s field 'loot' must be stock, none, orb, gold, item, powerup, or potion",
            operation);
    }
    return policy;
}

const LuaEnemyDefinition* FindEnemyDefinitionById(std::uint64_t content_id) {
    for (const auto& loaded_mod : LoadedLuaModsStorage()) {
        const auto found = std::find_if(
            loaded_mod->enemy_definitions.begin(),
            loaded_mod->enemy_definitions.end(),
            [content_id](const LuaEnemyDefinition& definition) {
                return definition.identity.network_id == content_id;
            });
        if (found != loaded_mod->enemy_definitions.end()) {
            return &*found;
        }
    }
    return nullptr;
}

const LuaEnemyDefinition* FindOwnedEnemyDefinitionByKey(
    const LoadedLuaMod& mod,
    std::string_view key) {
    const auto found = std::find_if(
        mod.enemy_definitions.begin(),
        mod.enemy_definitions.end(),
        [key](const LuaEnemyDefinition& definition) {
            return definition.identity.key == key;
        });
    return found == mod.enemy_definitions.end() ? nullptr : &*found;
}

void PushEnemyDefinition(
    lua_State* state,
    const LuaEnemyDefinition& definition) {
    lua_createtable(state, 0, 10);
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
        definition.base_name.data(),
        definition.base_name.size());
    lua_setfield(state, -2, "base");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(definition.native_type_id));
    lua_setfield(state, -2, "native_type_id");
    if (definition.hp_valid) {
        lua_pushnumber(state, static_cast<lua_Number>(definition.hp));
        lua_setfield(state, -2, "hp");
    }
    if (definition.speed_valid) {
        lua_pushnumber(state, static_cast<lua_Number>(definition.speed));
        lua_setfield(state, -2, "speed");
    }
    if (definition.scale_valid) {
        lua_pushnumber(state, static_cast<lua_Number>(definition.scale));
        lua_setfield(state, -2, "scale");
    }
    lua_pushstring(state, EnemyLootPolicyName(definition.loot_policy));
    lua_setfield(state, -2, "loot");
}

const LuaEnemyDefinition* ResolveEnemyDefinitionArgument(
    lua_State* state,
    int argument_index,
    const char* operation) {
    if (lua_type(state, argument_index) == LUA_TSTRING) {
        auto* mod = GetLoadedLuaMod(state);
        if (mod == nullptr) {
            luaL_error(state, "%s requires an owning Lua mod", operation);
        }
        std::size_t key_length = 0;
        const auto* key = lua_tolstring(state, argument_index, &key_length);
        return FindOwnedEnemyDefinitionByKey(
            *mod,
            std::string_view(key, key_length));
    }
    if (lua_isinteger(state, argument_index)) {
        const auto raw_id = lua_tointeger(state, argument_index);
        if (raw_id <= 0) {
            luaL_error(state, "%s content id must be a positive integer", operation);
        }
        return FindEnemyDefinitionById(static_cast<std::uint64_t>(raw_id));
    }
    luaL_error(state, "%s expects a content key or content id", operation);
    return nullptr;
}

int LuaEnemiesRegister(lua_State* state) {
    luaL_checktype(state, 1, LUA_TTABLE);
    RejectUnknownEnemyFields(state, 1, true);

    auto* mod = GetLoadedLuaMod(state);
    if (mod == nullptr) {
        return luaL_error(state, "sd.enemies.register requires an owning Lua mod");
    }
    if (mod->enemy_definitions.size() >= kLuaMaximumRegisteredEnemiesPerMod) {
        return luaL_error(
            state,
            "sd.enemies.register exceeds the per-mod limit of %zu",
            kLuaMaximumRegisteredEnemiesPerMod);
    }

    const auto key = ReadRequiredEnemyString(
        state,
        1,
        "sd.enemies.register",
        "key");
    const auto base_name = ReadRequiredEnemyString(
        state,
        1,
        "sd.enemies.register",
        "base");
    const auto* base = FindEnemyBaseBinding(base_name);
    if (base == nullptr) {
        return luaL_error(
            state,
            "sd.enemies.register base is not a supported hostile stock class");
    }

    LuaEnemyDefinition definition;
    definition.base_name = base_name;
    definition.native_type_id = base->native_type_id;
    definition.hp = ReadEnemyNumber(
        state,
        1,
        "sd.enemies.register",
        "hp",
        false,
        0.0001f,
        kMaximumEnemySpawnValue,
        &definition.hp_valid);
    definition.speed = ReadEnemyNumber(
        state,
        1,
        "sd.enemies.register",
        "speed",
        false,
        0.0f,
        kMaximumEnemySpawnValue,
        &definition.speed_valid);
    definition.scale = ReadEnemyNumber(
        state,
        1,
        "sd.enemies.register",
        "scale",
        false,
        kMinimumEnemyScale,
        kMaximumEnemyScale,
        &definition.scale_valid);
    definition.loot_policy = ReadEnemyLootPolicy(
        state,
        1,
        "sd.enemies.register",
        LuaEnemyLootPolicy::Stock);

    std::string registration_error;
    if (!RegisterLuaContentIdentityForMod(
            mod,
            LuaContentKind::Enemy,
            key,
            &definition.identity,
            &registration_error)) {
        return luaL_error(state, "%s", registration_error.c_str());
    }

    mod->enemy_definitions.push_back(std::move(definition));
    PushEnemyDefinition(state, mod->enemy_definitions.back());
    return 1;
}

int LuaEnemiesGet(lua_State* state) {
    const auto* definition = ResolveEnemyDefinitionArgument(
        state,
        1,
        "sd.enemies.get");
    if (definition == nullptr) {
        lua_pushnil(state);
        return 1;
    }
    PushEnemyDefinition(state, *definition);
    return 1;
}

int LuaEnemiesList(lua_State* state) {
    std::size_t count = 0;
    for (const auto& loaded_mod : LoadedLuaModsStorage()) {
        count += loaded_mod->enemy_definitions.size();
    }
    lua_createtable(state, static_cast<int>(count), 0);
    lua_Integer output_index = 1;
    for (const auto& loaded_mod : LoadedLuaModsStorage()) {
        for (const auto& definition : loaded_mod->enemy_definitions) {
            PushEnemyDefinition(state, definition);
            lua_seti(state, -2, output_index++);
        }
    }
    return 1;
}

int LuaEnemiesSpawn(lua_State* state) {
    if (!multiplayer::IsLuaModSimulationAuthority()) {
        return luaL_error(
            state,
            "sd.enemies.spawn may only be called by the simulation authority");
    }
    if (lua_gettop(state) != 2) {
        return luaL_error(
            state,
            "sd.enemies.spawn expects a content key or id and an options table");
    }
    luaL_checktype(state, 2, LUA_TTABLE);
    RejectUnknownEnemyFields(state, 2, false);

    const auto* definition = ResolveEnemyDefinitionArgument(
        state,
        1,
        "sd.enemies.spawn");
    if (definition == nullptr) {
        return luaL_error(
            state,
            "sd.enemies.spawn content identity is not registered");
    }

    bool x_valid = false;
    bool y_valid = false;
    const float x = ReadEnemyNumber(
        state,
        2,
        "sd.enemies.spawn",
        "x",
        true,
        -kMaximumEnemySpawnValue,
        kMaximumEnemySpawnValue,
        &x_valid);
    const float y = ReadEnemyNumber(
        state,
        2,
        "sd.enemies.spawn",
        "y",
        true,
        -kMaximumEnemySpawnValue,
        kMaximumEnemySpawnValue,
        &y_valid);
    (void)x_valid;
    (void)y_valid;

    SDModLuaEnemySpawnConfig config;
    config.content_id = definition->identity.network_id;
    config.hp_valid = definition->hp_valid;
    config.hp = definition->hp;
    config.chase_speed_valid = definition->speed_valid;
    config.chase_speed = definition->speed;
    config.scale_valid = definition->scale_valid;
    config.scale = definition->scale;
    config.loot_policy = ToRuntimeLootPolicy(definition->loot_policy);

    bool override_valid = false;
    const float hp = ReadEnemyNumber(
        state,
        2,
        "sd.enemies.spawn",
        "hp",
        false,
        0.0001f,
        kMaximumEnemySpawnValue,
        &override_valid);
    if (override_valid) {
        config.hp_valid = true;
        config.hp = hp;
    }
    const float speed = ReadEnemyNumber(
        state,
        2,
        "sd.enemies.spawn",
        "speed",
        false,
        0.0f,
        kMaximumEnemySpawnValue,
        &override_valid);
    if (override_valid) {
        config.chase_speed_valid = true;
        config.chase_speed = speed;
    }
    const float scale = ReadEnemyNumber(
        state,
        2,
        "sd.enemies.spawn",
        "scale",
        false,
        kMinimumEnemyScale,
        kMaximumEnemyScale,
        &override_valid);
    if (override_valid) {
        config.scale_valid = true;
        config.scale = scale;
    }
    config.loot_policy = ToRuntimeLootPolicy(ReadEnemyLootPolicy(
        state,
        2,
        "sd.enemies.spawn",
        definition->loot_policy));

    std::string error_message;
    std::uint64_t request_id = 0;
    if (!QueueRunLifecycleLuaEnemySpawn(
            config,
            static_cast<int>(definition->native_type_id),
            x,
            y,
            &error_message,
            &request_id)) {
        return luaL_error(
            state,
            "sd.enemies.spawn failed: %s",
            error_message.c_str());
    }

    lua_createtable(state, 0, 7);
    lua_pushboolean(state, 1);
    lua_setfield(state, -2, "queued");
    lua_pushinteger(state, static_cast<lua_Integer>(request_id));
    lua_setfield(state, -2, "request_id");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(definition->identity.network_id));
    lua_setfield(state, -2, "content_id");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(definition->native_type_id));
    lua_setfield(state, -2, "native_type_id");
    lua_pushnumber(state, static_cast<lua_Number>(x));
    lua_setfield(state, -2, "x");
    lua_pushnumber(state, static_cast<lua_Number>(y));
    lua_setfield(state, -2, "y");
    return 1;
}

}  // namespace

void RegisterLuaEnemyBindings(lua_State* state) {
    lua_createtable(state, 0, 4);
    RegisterFunction(state, &LuaEnemiesRegister, "register");
    RegisterFunction(state, &LuaEnemiesGet, "get");
    RegisterFunction(state, &LuaEnemiesList, "list");
    RegisterFunction(state, &LuaEnemiesSpawn, "spawn");
    lua_setfield(state, -2, "enemies");
}

}  // namespace sdmod::detail
