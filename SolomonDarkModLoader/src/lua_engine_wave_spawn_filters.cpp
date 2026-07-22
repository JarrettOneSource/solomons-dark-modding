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

constexpr char kWaveSpawningFilterName[] = "wave.spawning";
constexpr std::int32_t kMaximumWaveSpawnCount = 4096;
constexpr std::int32_t kMaximumWaveDelayTicks = 1'000'000;
constexpr std::uint32_t kMaximumBusyLogCount = 4;

std::atomic<std::uint32_t> g_wave_spawn_busy_log_count{0};

void PushWaveSpawnFilterPayload(
    lua_State* state,
    const LuaWaveSpawnFilterContext& context) {
    lua_createtable(state, 0, 11);

    lua_pushstring(state, kWaveSpawningFilterName);
    lua_setfield(state, -2, "event");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(context.spawner_address));
    lua_setfield(state, -2, "spawner_address");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(context.action_record_address));
    lua_setfield(state, -2, "action_record_address");
    lua_pushinteger(state, static_cast<lua_Integer>(context.wave_index));
    lua_setfield(state, -2, "wave_index");
    lua_pushinteger(state, static_cast<lua_Integer>(context.count));
    lua_setfield(state, -2, "count");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(context.spawn_delay_remaining));
    lua_setfield(state, -2, "spawn_delay_remaining");
    lua_pushinteger(state, static_cast<lua_Integer>(context.spawn_delay));
    lua_setfield(state, -2, "spawn_delay");
    lua_pushinteger(state, static_cast<lua_Integer>(context.wave_delay));
    lua_setfield(state, -2, "wave_delay");
    lua_pushboolean(state, context.randomize_spawn_delay ? 1 : 0);
    lua_setfield(state, -2, "randomize_spawn_delay");
    lua_pushboolean(state, context.sequential_groups ? 1 : 0);
    lua_setfield(state, -2, "sequential_groups");
}

bool ReadOptionalWaveInteger(
    lua_State* state,
    int table_index,
    const char* field_name,
    std::int32_t maximum,
    std::int32_t* value,
    std::string* error_message) {
    lua_getfield(state, table_index, field_name);
    if (lua_isnil(state, -1)) {
        lua_pop(state, 1);
        return true;
    }
    if (lua_type(state, -1) != LUA_TNUMBER) {
        if (error_message != nullptr) {
            *error_message = std::string(field_name) + " must be an integer";
        }
        lua_pop(state, 1);
        return false;
    }

    const auto candidate = lua_tonumber(state, -1);
    lua_pop(state, 1);
    if (!std::isfinite(candidate) || std::floor(candidate) != candidate ||
        candidate < 0.0 || candidate > static_cast<lua_Number>(maximum)) {
        if (error_message != nullptr) {
            *error_message = std::string(field_name) +
                " must be an integer in 0.." + std::to_string(maximum);
        }
        return false;
    }
    *value = static_cast<std::int32_t>(candidate);
    return true;
}

bool ReadOptionalWaveBoolean(
    lua_State* state,
    int table_index,
    const char* field_name,
    bool* value,
    std::string* error_message) {
    lua_getfield(state, table_index, field_name);
    if (lua_isnil(state, -1)) {
        lua_pop(state, 1);
        return true;
    }
    if (!lua_isboolean(state, -1)) {
        if (error_message != nullptr) {
            *error_message = std::string(field_name) + " must be a boolean";
        }
        lua_pop(state, 1);
        return false;
    }
    *value = lua_toboolean(state, -1) != 0;
    lua_pop(state, 1);
    return true;
}

bool ParseWaveSpawnFilterTable(
    lua_State* state,
    int table_index,
    LuaWaveSpawnFilterContext* candidate,
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

    if (!ReadOptionalWaveInteger(
            state,
            absolute_table_index,
            "count",
            kMaximumWaveSpawnCount,
            &candidate->count,
            error_message) ||
        !ReadOptionalWaveInteger(
            state,
            absolute_table_index,
            "spawn_delay",
            kMaximumWaveDelayTicks,
            &candidate->spawn_delay,
            error_message) ||
        !ReadOptionalWaveInteger(
            state,
            absolute_table_index,
            "wave_delay",
            kMaximumWaveDelayTicks,
            &candidate->wave_delay,
            error_message) ||
        !ReadOptionalWaveBoolean(
            state,
            absolute_table_index,
            "randomize_spawn_delay",
            &candidate->randomize_spawn_delay,
            error_message)) {
        return false;
    }

    lua_getfield(state, absolute_table_index, "spawn_delay");
    if (!lua_isnil(state, -1)) {
        candidate->spawn_delay_remaining = candidate->spawn_delay;
    }
    lua_pop(state, 1);

    *canceled = requested_cancel;
    return true;
}

bool ApplyWaveSpawnFilterResult(
    lua_State* state,
    int result_index,
    LuaWaveSpawnFilterContext* context,
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
    if (!ParseWaveSpawnFilterTable(
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

bool ApplyWaveSpawnFilterToMod(
    detail::LoadedLuaMod* mod,
    LuaWaveSpawnFilterContext* context) {
    if (mod == nullptr || mod->state == nullptr ||
        (mod->event_filter_mask & kLuaWaveSpawningFilterMask) == 0) {
        return true;
    }

    auto* state = mod->state;
    const int original_top = lua_gettop(state);
    lua_getfield(state, LUA_REGISTRYINDEX, detail::kLuaEventFiltersRegistryKey);
    if (!lua_istable(state, -1)) {
        lua_settop(state, original_top);
        return true;
    }
    lua_getfield(state, -1, kWaveSpawningFilterName);
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
        PushWaveSpawnFilterPayload(state, *context);
        if (lua_pcall(state, 1, 1, 0) != LUA_OK) {
            const auto* message = lua_tostring(state, -1);
            detail::LogLuaMessage(
                *mod,
                std::string(kWaveSpawningFilterName) + " filter failed: " +
                    (message == nullptr ? "unknown" : message));
            lua_pop(state, 1);
            continue;
        }

        bool canceled = false;
        std::string parse_error;
        if (!ApplyWaveSpawnFilterResult(
                state,
                -1,
                context,
                &canceled,
                &parse_error)) {
            detail::LogLuaMessage(
                *mod,
                std::string(kWaveSpawningFilterName) +
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

bool ApplyLuaWaveSpawnFilters(LuaWaveSpawnFilterContext* context) {
    if (context == nullptr || !HasLuaWaveSpawnFilterHandlers()) {
        return true;
    }

    std::unique_lock<std::mutex> lock(
        detail::LuaEngineMutex(),
        std::try_to_lock);
    if (!lock.owns_lock()) {
        const auto log_index =
            g_wave_spawn_busy_log_count.fetch_add(1, std::memory_order_relaxed);
        if (log_index < kMaximumBusyLogCount) {
            Log("[lua] wave spawn filters skipped because the Lua engine is busy");
        }
        return true;
    }
    if (!detail::LuaEngineInitializedFlag()) {
        return true;
    }

    for (const auto& mod : detail::LoadedLuaModsStorage()) {
        if (!ApplyWaveSpawnFilterToMod(mod.get(), context)) {
            return false;
        }
    }
    return true;
}

namespace detail {

void ResetLuaWaveSpawnFilterDiagnostics() {
    g_wave_spawn_busy_log_count.store(0, std::memory_order_relaxed);
}

}  // namespace detail
}  // namespace sdmod
