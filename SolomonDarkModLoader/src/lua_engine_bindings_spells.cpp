#include "lua_engine_bindings_internal.h"

#include "lua_engine_values.h"

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <string>
#include <string_view>
#include <utility>

namespace sdmod::detail {
namespace {

constexpr std::size_t kLuaMaximumRegisteredSpellsPerMod = 256;
constexpr std::size_t kLuaSpellMaximumDisplayNameBytes = 96;
constexpr std::size_t kLuaSpellMaximumDescriptionBytes = 1024;
constexpr std::int64_t kLuaSpellMaximumDurationMs = 3'600'000;
constexpr double kLuaSpellMaximumScalar = 1'000'000.0;

constexpr std::array<std::string_view, 9> kLuaSpellConfigFields = {{
    "name",
    "description",
    "mana_cost",
    "cooldown_ms",
    "duration_ms",
    "tick_interval_ms",
    "radius",
    "range",
    "speed",
}};

const char* SpellSlotName(LuaSpellSlot slot) {
    return slot == LuaSpellSlot::Primary ? "primary" : "secondary";
}

bool TryParseSpellSlot(std::string_view value, LuaSpellSlot* slot) {
    if (slot == nullptr) {
        return false;
    }
    if (value == "primary") {
        *slot = LuaSpellSlot::Primary;
        return true;
    }
    if (value == "secondary") {
        *slot = LuaSpellSlot::Secondary;
        return true;
    }
    return false;
}

bool IsKnownSpellRegistrationField(std::string_view field) {
    return field == "key" || field == "slot" || field == "cfg" ||
        field == "on_cast" || field == "on_tick" || field == "on_hit";
}

int RejectUnknownSpellRegistrationFields(lua_State* state, int table_index) {
    const int absolute_index = lua_absindex(state, table_index);
    lua_pushnil(state);
    while (lua_next(state, absolute_index) != 0) {
        if (lua_type(state, -2) != LUA_TSTRING) {
            lua_pop(state, 2);
            return luaL_error(
                state,
                "sd.spells.register accepts only named key, slot, cfg, on_cast, on_tick, and on_hit fields");
        }
        std::size_t field_length = 0;
        const auto* field = lua_tolstring(state, -2, &field_length);
        const std::string_view field_name(field, field_length);
        if (!IsKnownSpellRegistrationField(field_name)) {
            const std::string owned_field(field_name);
            lua_pop(state, 2);
            return luaL_error(
                state,
                "sd.spells.register received unknown field '%s'",
                owned_field.c_str());
        }
        lua_pop(state, 1);
    }
    return 0;
}

std::string ReadRequiredSpellString(
    lua_State* state,
    int table_index,
    const char* field_name) {
    lua_getfield(state, table_index, field_name);
    if (lua_type(state, -1) != LUA_TSTRING) {
        luaL_error(
            state,
            "sd.spells.register requires string field '%s'",
            field_name);
    }
    std::size_t length = 0;
    const auto* value = lua_tolstring(state, -1, &length);
    std::string result(value, length);
    lua_pop(state, 1);
    return result;
}

bool IsKnownSpellConfigField(std::string_view field) {
    return std::find(
               kLuaSpellConfigFields.begin(),
               kLuaSpellConfigFields.end(),
               field) != kLuaSpellConfigFields.end();
}

bool IsNumericLuaModValue(const LuaModValue& value) {
    return value.type == LuaModValueType::Integer ||
        value.type == LuaModValueType::Number;
}

double LuaModValueAsNumber(const LuaModValue& value) {
    return value.type == LuaModValueType::Integer
        ? static_cast<double>(value.integer_value)
        : value.number_value;
}

bool ValidateBoundedConfigString(
    const LuaModValue& config,
    std::string_view field_name,
    bool required,
    std::size_t maximum_bytes,
    std::string* error_message) {
    const auto found = config.object_value.find(field_name);
    if (found == config.object_value.end()) {
        if (required) {
            *error_message =
                "sd.spells.register cfg requires string field '" +
                std::string(field_name) + "'";
            return false;
        }
        return true;
    }
    if (found->second.type != LuaModValueType::String ||
        found->second.string_value.empty() ||
        found->second.string_value.size() > maximum_bytes ||
        found->second.string_value.find('\0') != std::string::npos) {
        *error_message =
            "sd.spells.register cfg." + std::string(field_name) +
            " must contain 1.." + std::to_string(maximum_bytes) +
            " text bytes";
        return false;
    }
    return true;
}

bool ValidateConfigInteger(
    const LuaModValue& config,
    std::string_view field_name,
    std::int64_t minimum,
    std::int64_t maximum,
    std::string* error_message) {
    const auto found = config.object_value.find(field_name);
    if (found == config.object_value.end()) {
        return true;
    }
    if (found->second.type != LuaModValueType::Integer ||
        found->second.integer_value < minimum ||
        found->second.integer_value > maximum) {
        *error_message =
            "sd.spells.register cfg." + std::string(field_name) +
            " must be an integer from " + std::to_string(minimum) +
            " through " + std::to_string(maximum);
        return false;
    }
    return true;
}

bool ValidateConfigNumber(
    const LuaModValue& config,
    std::string_view field_name,
    double minimum,
    double maximum,
    std::string* error_message) {
    const auto found = config.object_value.find(field_name);
    if (found == config.object_value.end()) {
        return true;
    }
    if (!IsNumericLuaModValue(found->second)) {
        *error_message =
            "sd.spells.register cfg." + std::string(field_name) +
            " must be numeric";
        return false;
    }
    const auto value = LuaModValueAsNumber(found->second);
    if (value < minimum || value > maximum) {
        *error_message =
            "sd.spells.register cfg." + std::string(field_name) +
            " must be from " + std::to_string(minimum) + " through " +
            std::to_string(maximum);
        return false;
    }
    return true;
}

bool ValidateSpellConfig(
    const LuaModValue& config,
    std::string* error_message) {
    if (config.type != LuaModValueType::Object) {
        *error_message = "sd.spells.register cfg must be a named-field table";
        return false;
    }
    for (const auto& [field_name, unused] : config.object_value) {
        (void)unused;
        if (!IsKnownSpellConfigField(field_name)) {
            *error_message =
                "sd.spells.register cfg received unknown field '" +
                field_name + "'";
            return false;
        }
    }
    return ValidateBoundedConfigString(
               config,
               "name",
               true,
               kLuaSpellMaximumDisplayNameBytes,
               error_message) &&
        ValidateBoundedConfigString(
               config,
               "description",
               false,
               kLuaSpellMaximumDescriptionBytes,
               error_message) &&
        ValidateConfigNumber(
               config,
               "mana_cost",
               0.0,
               kLuaSpellMaximumScalar,
               error_message) &&
        ValidateConfigInteger(
               config,
               "cooldown_ms",
               0,
               kLuaSpellMaximumDurationMs,
               error_message) &&
        ValidateConfigInteger(
               config,
               "duration_ms",
               0,
               kLuaSpellMaximumDurationMs,
               error_message) &&
        ValidateConfigInteger(
               config,
               "tick_interval_ms",
               1,
               60'000,
               error_message) &&
        ValidateConfigNumber(
               config,
               "radius",
               0.0,
               kLuaSpellMaximumScalar,
               error_message) &&
        ValidateConfigNumber(
               config,
               "range",
               0.0,
               kLuaSpellMaximumScalar,
               error_message) &&
        ValidateConfigNumber(
               config,
               "speed",
               0.0,
               kLuaSpellMaximumScalar,
               error_message);
}

bool ValidateSpellCallback(
    lua_State* state,
    int table_index,
    const char* field_name,
    bool required) {
    lua_getfield(state, table_index, field_name);
    const bool present = !lua_isnil(state, -1);
    const bool valid = present ? lua_isfunction(state, -1) : !required;
    lua_pop(state, 1);
    return valid;
}

int CaptureSpellCallbackReference(
    lua_State* state,
    int table_index,
    const char* field_name) {
    lua_getfield(state, table_index, field_name);
    if (lua_isnil(state, -1)) {
        lua_pop(state, 1);
        return LUA_NOREF;
    }
    return luaL_ref(state, LUA_REGISTRYINDEX);
}

const LuaSpellDefinition* FindSpellDefinitionById(std::uint64_t content_id) {
    for (const auto& loaded_mod : LoadedLuaModsStorage()) {
        const auto found = std::find_if(
            loaded_mod->spell_definitions.begin(),
            loaded_mod->spell_definitions.end(),
            [content_id](const LuaSpellDefinition& definition) {
                return definition.identity.network_id == content_id;
            });
        if (found != loaded_mod->spell_definitions.end()) {
            return &*found;
        }
    }
    return nullptr;
}

const LuaSpellDefinition* FindOwnedSpellDefinitionByKey(
    const LoadedLuaMod& mod,
    std::string_view key) {
    const auto found = std::find_if(
        mod.spell_definitions.begin(),
        mod.spell_definitions.end(),
        [key](const LuaSpellDefinition& definition) {
            return definition.identity.key == key;
        });
    return found == mod.spell_definitions.end() ? nullptr : &*found;
}

void PushSpellDefinition(
    lua_State* state,
    const LuaSpellDefinition& definition) {
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
    lua_pushstring(state, SpellSlotName(definition.slot));
    lua_setfield(state, -2, "slot");
    PushLuaModValue(state, definition.config);
    lua_setfield(state, -2, "cfg");
    lua_pushboolean(state, definition.on_cast_reference != LUA_NOREF);
    lua_setfield(state, -2, "has_on_cast");
    lua_pushboolean(state, definition.on_tick_reference != LUA_NOREF);
    lua_setfield(state, -2, "has_on_tick");
    lua_pushboolean(state, definition.on_hit_reference != LUA_NOREF);
    lua_setfield(state, -2, "has_on_hit");
}

int LuaSpellsRegister(lua_State* state) {
    luaL_checktype(state, 1, LUA_TTABLE);
    RejectUnknownSpellRegistrationFields(state, 1);

    auto* mod = GetLoadedLuaMod(state);
    if (mod == nullptr) {
        return luaL_error(state, "sd.spells.register requires an owning Lua mod");
    }
    if (mod->spell_definitions.size() >= kLuaMaximumRegisteredSpellsPerMod) {
        return luaL_error(
            state,
            "sd.spells.register exceeds the per-mod limit of %zu",
            kLuaMaximumRegisteredSpellsPerMod);
    }

    const auto key = ReadRequiredSpellString(state, 1, "key");
    const auto slot_name = ReadRequiredSpellString(state, 1, "slot");
    LuaSpellSlot slot = LuaSpellSlot::Primary;
    if (!TryParseSpellSlot(slot_name, &slot)) {
        return luaL_error(
            state,
            "sd.spells.register slot must be primary or secondary");
    }

    lua_getfield(state, 1, "cfg");
    LuaModValue config;
    std::string config_error;
    const bool config_valid =
        lua_istable(state, -1) &&
        ReadLuaModValue(state, -1, &config, &config_error) &&
        ValidateSpellConfig(config, &config_error);
    lua_pop(state, 1);
    if (!config_valid) {
        return luaL_error(
            state,
            "%s",
            config_error.empty()
                ? "sd.spells.register cfg must be a bounded named-field table"
                : config_error.c_str());
    }

    if (!ValidateSpellCallback(state, 1, "on_cast", true)) {
        return luaL_error(state, "sd.spells.register on_cast must be a function");
    }
    if (!ValidateSpellCallback(state, 1, "on_tick", false)) {
        return luaL_error(
            state,
            "sd.spells.register on_tick must be nil or a function");
    }
    if (!ValidateSpellCallback(state, 1, "on_hit", false)) {
        return luaL_error(
            state,
            "sd.spells.register on_hit must be nil or a function");
    }

    LuaContentIdentity identity;
    std::string registration_error;
    if (!RegisterLuaContentIdentityForMod(
            mod,
            LuaContentKind::Spell,
            key,
            &identity,
            &registration_error)) {
        return luaL_error(state, "%s", registration_error.c_str());
    }

    LuaSpellDefinition definition;
    definition.identity = std::move(identity);
    definition.slot = slot;
    definition.config = std::move(config);
    definition.on_cast_reference =
        CaptureSpellCallbackReference(state, 1, "on_cast");
    definition.on_tick_reference =
        CaptureSpellCallbackReference(state, 1, "on_tick");
    definition.on_hit_reference =
        CaptureSpellCallbackReference(state, 1, "on_hit");
    mod->spell_definitions.push_back(std::move(definition));
    PushSpellDefinition(state, mod->spell_definitions.back());
    return 1;
}

int LuaSpellsGet(lua_State* state) {
    const LuaSpellDefinition* definition = nullptr;
    if (lua_type(state, 1) == LUA_TSTRING) {
        auto* mod = GetLoadedLuaMod(state);
        if (mod == nullptr) {
            return luaL_error(state, "sd.spells.get requires an owning Lua mod");
        }
        std::size_t key_length = 0;
        const auto* key = lua_tolstring(state, 1, &key_length);
        definition = FindOwnedSpellDefinitionByKey(
            *mod,
            std::string_view(key, key_length));
    } else if (lua_isinteger(state, 1)) {
        const auto raw_id = lua_tointeger(state, 1);
        if (raw_id <= 0) {
            return luaL_error(state, "sd.spells.get id must be a positive integer");
        }
        definition = FindSpellDefinitionById(static_cast<std::uint64_t>(raw_id));
    } else {
        return luaL_error(
            state,
            "sd.spells.get expects a content key or content id");
    }

    if (definition == nullptr) {
        lua_pushnil(state);
        return 1;
    }
    PushSpellDefinition(state, *definition);
    return 1;
}

int LuaSpellsList(lua_State* state) {
    std::size_t count = 0;
    for (const auto& loaded_mod : LoadedLuaModsStorage()) {
        count += loaded_mod->spell_definitions.size();
    }
    lua_createtable(state, static_cast<int>(count), 0);
    lua_Integer output_index = 1;
    for (const auto& loaded_mod : LoadedLuaModsStorage()) {
        for (const auto& definition : loaded_mod->spell_definitions) {
            PushSpellDefinition(state, definition);
            lua_seti(state, -2, output_index++);
        }
    }
    return 1;
}

}  // namespace

void RegisterLuaSpellBindings(lua_State* state) {
    lua_createtable(state, 0, 3);
    RegisterFunction(state, &LuaSpellsRegister, "register");
    RegisterFunction(state, &LuaSpellsGet, "get");
    RegisterFunction(state, &LuaSpellsList, "list");
    lua_setfield(state, -2, "spells");
}

}  // namespace sdmod::detail
