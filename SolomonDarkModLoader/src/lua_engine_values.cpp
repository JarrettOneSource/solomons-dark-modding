#include "lua_engine_values.h"

extern "C" {
#include "lua.h"
}

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <string>
#include <unordered_set>
#include <utility>

namespace sdmod::detail {
namespace {

void SetError(std::string* error_message, const std::string& message) {
    if (error_message != nullptr) {
        *error_message = message;
    }
}

bool ReadValueNode(
    lua_State* state,
    int index,
    std::size_t depth,
    std::size_t* node_count,
    std::unordered_set<const void*>* active_tables,
    LuaModValue* value,
    std::string* error_message) {
    if (state == nullptr || node_count == nullptr ||
        active_tables == nullptr || value == nullptr) {
        SetError(error_message, "Lua value conversion received a null argument");
        return false;
    }
    if (depth > kLuaModMaxValueDepth) {
        SetError(error_message, "Lua value exceeds the maximum nesting depth");
        return false;
    }
    ++(*node_count);
    if (*node_count > kLuaModMaxValueNodes) {
        SetError(error_message, "Lua value exceeds the maximum node count");
        return false;
    }

    const int absolute_index = lua_absindex(state, index);
    LuaModValue parsed;
    switch (lua_type(state, absolute_index)) {
    case LUA_TNIL:
        parsed.type = LuaModValueType::Nil;
        break;
    case LUA_TBOOLEAN:
        parsed.type = LuaModValueType::Boolean;
        parsed.boolean_value = lua_toboolean(state, absolute_index) != 0;
        break;
    case LUA_TNUMBER:
        if (lua_isinteger(state, absolute_index)) {
            parsed.type = LuaModValueType::Integer;
            parsed.integer_value = static_cast<std::int64_t>(
                lua_tointeger(state, absolute_index));
        } else {
            parsed.type = LuaModValueType::Number;
            parsed.number_value = static_cast<double>(
                lua_tonumber(state, absolute_index));
            if (!std::isfinite(parsed.number_value)) {
                SetError(error_message, "Lua values cannot contain NaN or infinity");
                return false;
            }
        }
        break;
    case LUA_TSTRING: {
        std::size_t length = 0;
        const char* text = lua_tolstring(state, absolute_index, &length);
        if (text == nullptr || length > kLuaModMaxStringBytes) {
            SetError(error_message, "Lua string exceeds the size limit");
            return false;
        }
        parsed.type = LuaModValueType::String;
        parsed.string_value.assign(text, length);
        break;
    }
    case LUA_TTABLE: {
        const void* table_identity = lua_topointer(state, absolute_index);
        if (table_identity == nullptr ||
            !active_tables->insert(table_identity).second) {
            SetError(error_message, "Lua values cannot contain table cycles");
            return false;
        }

        bool has_integer_keys = false;
        bool has_string_keys = false;
        std::size_t entry_count = 0;
        std::size_t maximum_index = 0;
        lua_pushnil(state);
        while (lua_next(state, absolute_index) != 0) {
            ++entry_count;
            if (entry_count > kLuaModMaxValueNodes) {
                lua_pop(state, 2);
                active_tables->erase(table_identity);
                SetError(error_message, "Lua table exceeds the element limit");
                return false;
            }
            if (lua_isinteger(state, -2)) {
                const auto key = lua_tointeger(state, -2);
                if (key <= 0 ||
                    static_cast<lua_Unsigned>(key) >
                        static_cast<lua_Unsigned>(kLuaModMaxValueNodes)) {
                    lua_pop(state, 2);
                    active_tables->erase(table_identity);
                    SetError(error_message, "Lua array keys must be bounded positive integers");
                    return false;
                }
                has_integer_keys = true;
                maximum_index = (std::max)(
                    maximum_index,
                    static_cast<std::size_t>(key));
            } else if (lua_type(state, -2) == LUA_TSTRING) {
                std::size_t key_length = 0;
                const char* key_text = lua_tolstring(state, -2, &key_length);
                const std::string key(
                    key_text == nullptr ? "" : key_text,
                    key_length);
                if (!IsValidLuaModStateKey(key)) {
                    lua_pop(state, 2);
                    active_tables->erase(table_identity);
                    SetError(error_message, "Lua object keys must be nonempty bounded text");
                    return false;
                }
                has_string_keys = true;
            } else {
                lua_pop(state, 2);
                active_tables->erase(table_identity);
                SetError(error_message, "Lua table keys must be strings or positive integers");
                return false;
            }
            lua_pop(state, 1);
        }

        if (has_integer_keys && has_string_keys) {
            active_tables->erase(table_identity);
            SetError(error_message, "Lua values cannot contain mixed array/object tables");
            return false;
        }
        if (has_integer_keys) {
            if (maximum_index != entry_count) {
                active_tables->erase(table_identity);
                SetError(error_message, "Lua arrays must be dense and one-indexed");
                return false;
            }
            parsed.type = LuaModValueType::Array;
            parsed.array_value.reserve(entry_count);
            for (std::size_t item_index = 1;
                 item_index <= entry_count;
                 ++item_index) {
                lua_rawgeti(
                    state,
                    absolute_index,
                    static_cast<lua_Integer>(item_index));
                LuaModValue element;
                const bool converted = ReadValueNode(
                    state,
                    -1,
                    depth + 1,
                    node_count,
                    active_tables,
                    &element,
                    error_message);
                lua_pop(state, 1);
                if (!converted) {
                    active_tables->erase(table_identity);
                    return false;
                }
                parsed.array_value.push_back(std::move(element));
            }
        } else {
            parsed.type = LuaModValueType::Object;
            lua_pushnil(state);
            while (lua_next(state, absolute_index) != 0) {
                std::size_t key_length = 0;
                const char* key_text = lua_tolstring(state, -2, &key_length);
                std::string key(key_text, key_length);
                LuaModValue field_value;
                const bool converted = ReadValueNode(
                    state,
                    -1,
                    depth + 1,
                    node_count,
                    active_tables,
                    &field_value,
                    error_message);
                lua_pop(state, 1);
                if (!converted) {
                    lua_pop(state, 1);
                    active_tables->erase(table_identity);
                    return false;
                }
                parsed.object_value.emplace(
                    std::move(key),
                    std::move(field_value));
            }
        }
        active_tables->erase(table_identity);
        break;
    }
    default:
        SetError(
            error_message,
            std::string("unsupported Lua value type: ") +
                lua_typename(state, lua_type(state, absolute_index)));
        return false;
    }

    *value = std::move(parsed);
    return true;
}

void PushValueNode(lua_State* state, const LuaModValue& value) {
    switch (value.type) {
    case LuaModValueType::Nil:
        lua_pushnil(state);
        break;
    case LuaModValueType::Boolean:
        lua_pushboolean(state, value.boolean_value ? 1 : 0);
        break;
    case LuaModValueType::Integer:
        lua_pushinteger(
            state,
            static_cast<lua_Integer>(value.integer_value));
        break;
    case LuaModValueType::Number:
        lua_pushnumber(state, static_cast<lua_Number>(value.number_value));
        break;
    case LuaModValueType::String:
        lua_pushlstring(
            state,
            value.string_value.data(),
            value.string_value.size());
        break;
    case LuaModValueType::Array:
        lua_createtable(
            state,
            static_cast<int>(value.array_value.size()),
            0);
        for (std::size_t index = 0;
             index < value.array_value.size();
             ++index) {
            PushValueNode(state, value.array_value[index]);
            lua_rawseti(
                state,
                -2,
                static_cast<lua_Integer>(index + 1));
        }
        break;
    case LuaModValueType::Object:
        lua_createtable(
            state,
            0,
            static_cast<int>(value.object_value.size()));
        for (const auto& [key, field_value] : value.object_value) {
            lua_pushlstring(state, key.data(), key.size());
            PushValueNode(state, field_value);
            lua_settable(state, -3);
        }
        break;
    }
}

}  // namespace

bool ReadLuaModValue(
    lua_State* state,
    int index,
    LuaModValue* value,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    std::size_t node_count = 0;
    std::unordered_set<const void*> active_tables;
    if (!ReadValueNode(
            state,
            index,
            0,
            &node_count,
            &active_tables,
            value,
            error_message)) {
        return false;
    }
    std::vector<std::uint8_t> encoded;
    return EncodeLuaModValue(*value, &encoded, error_message);
}

void PushLuaModValue(lua_State* state, const LuaModValue& value) {
    PushValueNode(state, value);
}

}  // namespace sdmod::detail
