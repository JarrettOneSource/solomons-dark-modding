#include "lua_event_filters.h"

#include "logger.h"
#include "lua_engine_internal.h"

extern "C" {
#include "lua.h"
}

#include <atomic>
#include <cmath>
#include <cstdint>
#include <mutex>
#include <string>

namespace sdmod {
namespace {

constexpr char kEnemySpawningFilterName[] = "enemy.spawning";
constexpr float kMaximumEnemySpawnValue = 1'000'000.0f;
constexpr float kMinimumEnemyScale = 0.01f;
constexpr float kMaximumEnemyScale = 1'000.0f;
constexpr std::uint32_t kMaximumBusyLogCount = 4;

std::atomic<std::uint32_t> g_enemy_spawn_busy_log_count{0};

bool IsValidSpawnValue(lua_Number value, lua_Number minimum, lua_Number maximum) {
    return std::isfinite(value) && value >= minimum && value <= maximum;
}

void PushEnemySpawnFilterPayload(
    lua_State* state,
    const LuaEnemySpawnFilterContext& context) {
    lua_createtable(state, 0, 12);

    lua_pushstring(state, kEnemySpawningFilterName);
    lua_setfield(state, -2, "event");
    lua_pushinteger(state, static_cast<lua_Integer>(context.native_type_id));
    lua_setfield(state, -2, "native_type_id");
    lua_pushinteger(state, static_cast<lua_Integer>(context.arena_address));
    lua_setfield(state, -2, "arena_address");
    lua_pushinteger(state, static_cast<lua_Integer>(context.config_address));
    lua_setfield(state, -2, "config_address");
    if (context.wave_spawner_address == 0) {
        lua_pushnil(state);
    } else {
        lua_pushinteger(
            state,
            static_cast<lua_Integer>(context.wave_spawner_address));
    }
    lua_setfield(state, -2, "wave_spawner_address");

    lua_pushnumber(state, static_cast<lua_Number>(context.hp));
    lua_setfield(state, -2, "hp");
    lua_pushnumber(
        state,
        static_cast<lua_Number>(context.family_values[0]));
    lua_setfield(state, -2, "primary_damage");
    lua_pushnumber(
        state,
        static_cast<lua_Number>(context.family_values[1]));
    lua_setfield(state, -2, "secondary_damage");

    lua_createtable(
        state,
        static_cast<int>(context.family_values.size()),
        0);
    for (std::size_t index = 0; index < context.family_values.size(); ++index) {
        lua_pushnumber(
            state,
            static_cast<lua_Number>(context.family_values[index]));
        lua_rawseti(state, -2, static_cast<lua_Integer>(index + 1));
    }
    lua_setfield(state, -2, "family_values");

    lua_pushnumber(state, static_cast<lua_Number>(context.chase_speed));
    lua_setfield(state, -2, "chase_speed");
    lua_pushnumber(state, static_cast<lua_Number>(context.attack_speed));
    lua_setfield(state, -2, "attack_speed");
    lua_pushnumber(state, static_cast<lua_Number>(context.scale));
    lua_setfield(state, -2, "scale");
}

bool ReadOptionalSpawnValue(
    lua_State* state,
    int table_index,
    const char* field_name,
    float minimum,
    float maximum,
    float* value,
    std::string* error_message) {
    lua_getfield(state, table_index, field_name);
    if (lua_isnil(state, -1)) {
        lua_pop(state, 1);
        return true;
    }
    if (lua_type(state, -1) != LUA_TNUMBER) {
        if (error_message != nullptr) {
            *error_message = std::string(field_name) + " must be a number";
        }
        lua_pop(state, 1);
        return false;
    }

    const auto candidate = lua_tonumber(state, -1);
    lua_pop(state, 1);
    if (!IsValidSpawnValue(candidate, minimum, maximum)) {
        if (error_message != nullptr) {
            *error_message = std::string(field_name) +
                " is outside the supported native range";
        }
        return false;
    }
    *value = static_cast<float>(candidate);
    return true;
}

bool ParseEnemySpawnFilterTable(
    lua_State* state,
    int table_index,
    LuaEnemySpawnFilterContext* candidate,
    bool* canceled,
    std::string* error_message) {
    const auto absolute_table_index = lua_absindex(state, table_index);

    lua_getfield(state, absolute_table_index, "cancel");
    if (!lua_isnil(state, -1) && !lua_isboolean(state, -1)) {
        if (error_message != nullptr) {
            *error_message = "cancel must be a boolean";
        }
        lua_pop(state, 1);
        return false;
    }
    const bool requested_cancel = lua_toboolean(state, -1) != 0;
    lua_pop(state, 1);

    lua_getfield(state, absolute_table_index, "family_values");
    if (!lua_isnil(state, -1)) {
        if (!lua_istable(state, -1)) {
            if (error_message != nullptr) {
                *error_message = "family_values must be a table";
            }
            lua_pop(state, 1);
            return false;
        }
        for (std::size_t index = 0;
             index < candidate->family_values.size();
             ++index) {
            lua_rawgeti(state, -1, static_cast<lua_Integer>(index + 1));
            if (lua_isnil(state, -1)) {
                lua_pop(state, 1);
                continue;
            }
            if (lua_type(state, -1) != LUA_TNUMBER) {
                if (error_message != nullptr) {
                    *error_message = "family_values[" +
                        std::to_string(index + 1) + "] must be a number";
                }
                lua_pop(state, 2);
                return false;
            }
            const auto value = lua_tonumber(state, -1);
            lua_pop(state, 1);
            if (!IsValidSpawnValue(value, 0.0, kMaximumEnemySpawnValue)) {
                if (error_message != nullptr) {
                    *error_message = "family_values[" +
                        std::to_string(index + 1) +
                        "] is outside the supported native range";
                }
                lua_pop(state, 1);
                return false;
            }
            candidate->family_values[index] = static_cast<float>(value);
        }
    }
    lua_pop(state, 1);

    if (!ReadOptionalSpawnValue(
            state,
            absolute_table_index,
            "hp",
            0.0f,
            kMaximumEnemySpawnValue,
            &candidate->hp,
            error_message) ||
        !ReadOptionalSpawnValue(
            state,
            absolute_table_index,
            "primary_damage",
            0.0f,
            kMaximumEnemySpawnValue,
            &candidate->family_values[0],
            error_message) ||
        !ReadOptionalSpawnValue(
            state,
            absolute_table_index,
            "secondary_damage",
            0.0f,
            kMaximumEnemySpawnValue,
            &candidate->family_values[1],
            error_message) ||
        !ReadOptionalSpawnValue(
            state,
            absolute_table_index,
            "chase_speed",
            0.0f,
            kMaximumEnemySpawnValue,
            &candidate->chase_speed,
            error_message) ||
        !ReadOptionalSpawnValue(
            state,
            absolute_table_index,
            "attack_speed",
            0.0f,
            kMaximumEnemySpawnValue,
            &candidate->attack_speed,
            error_message) ||
        !ReadOptionalSpawnValue(
            state,
            absolute_table_index,
            "scale",
            kMinimumEnemyScale,
            kMaximumEnemyScale,
            &candidate->scale,
            error_message)) {
        return false;
    }

    *canceled = requested_cancel;
    return true;
}

bool ApplyEnemySpawnFilterResult(
    lua_State* state,
    int result_index,
    LuaEnemySpawnFilterContext* context,
    bool* canceled,
    std::string* error_message) {
    *canceled = false;
    const auto result_type = lua_type(state, result_index);
    if (result_type == LUA_TNIL ||
        (result_type == LUA_TBOOLEAN && lua_toboolean(state, result_index))) {
        return true;
    }
    if (result_type == LUA_TBOOLEAN) {
        *canceled = true;
        return true;
    }
    if (result_type != LUA_TTABLE) {
        if (error_message != nullptr) {
            *error_message = "handler must return nil, a boolean, or a table";
        }
        return false;
    }

    auto candidate = *context;
    if (!ParseEnemySpawnFilterTable(
            state,
            result_index,
            &candidate,
            canceled,
            error_message)) {
        return false;
    }
    if (!*canceled) {
        *context = candidate;
    }
    return true;
}

bool ApplyEnemySpawnFilterToMod(
    detail::LoadedLuaMod* mod,
    LuaEnemySpawnFilterContext* context) {
    if (mod == nullptr || mod->state == nullptr ||
        (mod->event_filter_mask & kLuaEnemySpawningFilterMask) == 0) {
        return true;
    }

    auto* state = mod->state;
    const int original_top = lua_gettop(state);
    lua_getfield(state, LUA_REGISTRYINDEX, detail::kLuaEventFiltersRegistryKey);
    if (!lua_istable(state, -1)) {
        lua_settop(state, original_top);
        return true;
    }
    lua_getfield(state, -1, kEnemySpawningFilterName);
    if (!lua_istable(state, -1)) {
        lua_settop(state, original_top);
        return true;
    }

    const auto handler_count = lua_rawlen(state, -1);
    for (lua_Unsigned index = 1; index <= handler_count; ++index) {
        lua_rawgeti(state, -1, static_cast<lua_Integer>(index));
        if (!lua_isfunction(state, -1)) {
            lua_pop(state, 1);
            continue;
        }
        PushEnemySpawnFilterPayload(state, *context);
        if (lua_pcall(state, 1, 1, 0) != LUA_OK) {
            const auto* message = lua_tostring(state, -1);
            detail::LogLuaMessage(
                *mod,
                std::string(kEnemySpawningFilterName) + " filter failed: " +
                    (message == nullptr ? "unknown" : message));
            lua_pop(state, 1);
            continue;
        }

        bool canceled = false;
        std::string parse_error;
        if (!ApplyEnemySpawnFilterResult(
                state,
                -1,
                context,
                &canceled,
                &parse_error)) {
            detail::LogLuaMessage(
                *mod,
                std::string(kEnemySpawningFilterName) +
                    " filter result ignored: " + parse_error);
        }
        lua_pop(state, 1);
        if (canceled) {
            lua_settop(state, original_top);
            return false;
        }
    }

    lua_settop(state, original_top);
    return true;
}

}  // namespace

bool ApplyLuaEnemySpawnFilters(LuaEnemySpawnFilterContext* context) {
    if (context == nullptr || !HasLuaEnemySpawnFilterHandlers()) {
        return true;
    }

    std::unique_lock<std::mutex> lock(
        detail::LuaEngineMutex(),
        std::try_to_lock);
    if (!lock.owns_lock()) {
        const auto log_index =
            g_enemy_spawn_busy_log_count.fetch_add(1, std::memory_order_relaxed);
        if (log_index < kMaximumBusyLogCount) {
            Log("[lua] enemy spawn filters skipped because the Lua engine is busy");
        }
        return true;
    }
    if (!detail::LuaEngineInitializedFlag()) {
        return true;
    }

    for (const auto& mod : detail::LoadedLuaModsStorage()) {
        if (!ApplyEnemySpawnFilterToMod(mod.get(), context)) {
            return false;
        }
    }
    return true;
}

namespace detail {

void ResetLuaEnemySpawnFilterDiagnostics() {
    g_enemy_spawn_busy_log_count.store(0, std::memory_order_relaxed);
}

}  // namespace detail
}  // namespace sdmod
