#include "lua_event_filters.h"

#include "logger.h"
#include "lua_engine_bindings_internal.h"
#include "lua_engine_internal.h"

extern "C" {
#include "lua.h"
#include "lauxlib.h"
}

#include <atomic>
#include <cmath>
#include <cstdint>
#include <mutex>
#include <string>
#include <string_view>

namespace sdmod {
namespace {

constexpr std::uint32_t kDamageDealingFilterMask = 1u << 0;
constexpr std::uint32_t kDamageTakenFilterMask = 1u << 1;
constexpr std::uint32_t kDamageFilterMask =
    kDamageDealingFilterMask | kDamageTakenFilterMask;
constexpr float kMaximumAbsoluteDamageLane = 1'000'000.0f;
constexpr std::uint32_t kMaximumBusyLogCount = 4;

std::atomic<std::uint32_t> g_registered_filter_mask{0};
std::atomic<std::uint32_t> g_busy_log_count{0};

std::uint32_t FilterMaskForName(std::string_view filter_name) {
    if (filter_name == "damage.dealing") {
        return kDamageDealingFilterMask;
    }
    if (filter_name == "damage.taken") {
        return kDamageTakenFilterMask;
    }
    return 0;
}

bool IsValidDamageLane(lua_Number value) {
    return std::isfinite(value) &&
        std::abs(value) <=
            static_cast<lua_Number>(kMaximumAbsoluteDamageLane);
}

void PushParticipantId(
    lua_State* state,
    const char* field_name,
    std::uint64_t participant_id) {
    if (participant_id == 0) {
        lua_pushnil(state);
    } else {
        lua_pushinteger(state, static_cast<lua_Integer>(participant_id));
    }
    lua_setfield(state, -2, field_name);
}

void PushDamageFilterPayload(
    lua_State* state,
    const char* filter_name,
    const LuaDamageFilterContext& context) {
    lua_createtable(state, 0, 10);

    lua_pushstring(state, filter_name);
    lua_setfield(state, -2, "event");

    lua_pushinteger(
        state,
        static_cast<lua_Integer>(context.source_actor_address));
    lua_setfield(state, -2, "source_actor_address");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(context.target_actor_address));
    lua_setfield(state, -2, "target_actor_address");

    PushParticipantId(
        state,
        "source_participant_id",
        context.source_participant_id);
    PushParticipantId(
        state,
        "target_participant_id",
        context.target_participant_id);

    lua_pushinteger(state, static_cast<lua_Integer>(context.flags));
    lua_setfield(state, -2, "flags");
    lua_pushnumber(state, static_cast<lua_Number>(context.lanes[0]));
    lua_setfield(state, -2, "projectile_damage");
    lua_pushnumber(state, static_cast<lua_Number>(context.lanes[1]));
    lua_setfield(state, -2, "magic_damage");

    lua_Number total = 0.0;
    lua_createtable(
        state,
        static_cast<int>(context.lanes.size()),
        0);
    for (std::size_t index = 0; index < context.lanes.size(); ++index) {
        const auto lane = static_cast<lua_Number>(context.lanes[index]);
        total += lane;
        lua_pushnumber(state, lane);
        lua_rawseti(state, -2, static_cast<lua_Integer>(index + 1));
    }
    lua_setfield(state, -2, "lanes");

    lua_pushnumber(state, total);
    lua_setfield(state, -2, "total_damage");
}

bool ReadOptionalDamageLane(
    lua_State* state,
    int table_index,
    const char* field_name,
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
    if (!IsValidDamageLane(candidate)) {
        if (error_message != nullptr) {
            *error_message = std::string(field_name) +
                " must be finite and within +/-1000000";
        }
        return false;
    }
    *value = static_cast<float>(candidate);
    return true;
}

bool ParseDamageFilterTable(
    lua_State* state,
    int table_index,
    LuaDamageFilterContext* candidate,
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

    lua_getfield(state, absolute_table_index, "lanes");
    if (!lua_isnil(state, -1)) {
        if (!lua_istable(state, -1)) {
            if (error_message != nullptr) {
                *error_message = "lanes must be a table";
            }
            lua_pop(state, 1);
            return false;
        }
        for (std::size_t index = 0; index < candidate->lanes.size(); ++index) {
            lua_rawgeti(state, -1, static_cast<lua_Integer>(index + 1));
            if (lua_isnil(state, -1)) {
                lua_pop(state, 1);
                continue;
            }
            if (lua_type(state, -1) != LUA_TNUMBER) {
                if (error_message != nullptr) {
                    *error_message = "lanes[" + std::to_string(index + 1) +
                        "] must be a number";
                }
                lua_pop(state, 2);
                return false;
            }
            const auto lane = lua_tonumber(state, -1);
            lua_pop(state, 1);
            if (!IsValidDamageLane(lane)) {
                if (error_message != nullptr) {
                    *error_message = "lanes[" + std::to_string(index + 1) +
                        "] must be finite and within +/-1000000";
                }
                lua_pop(state, 1);
                return false;
            }
            candidate->lanes[index] = static_cast<float>(lane);
        }
    }
    lua_pop(state, 1);

    if (!ReadOptionalDamageLane(
            state,
            absolute_table_index,
            "projectile_damage",
            &candidate->lanes[0],
            error_message) ||
        !ReadOptionalDamageLane(
            state,
            absolute_table_index,
            "magic_damage",
            &candidate->lanes[1],
            error_message)) {
        return false;
    }

    *canceled = requested_cancel;
    return true;
}

bool ApplyDamageFilterResult(
    lua_State* state,
    int result_index,
    LuaDamageFilterContext* context,
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
    if (!ParseDamageFilterTable(
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

bool ApplyDamageFilterToMod(
    detail::LoadedLuaMod* mod,
    const char* filter_name,
    std::uint32_t filter_mask,
    LuaDamageFilterContext* context) {
    if (mod == nullptr || mod->state == nullptr ||
        (mod->event_filter_mask & filter_mask) == 0) {
        return true;
    }

    auto* state = mod->state;
    const int original_top = lua_gettop(state);
    lua_getfield(state, LUA_REGISTRYINDEX, detail::kLuaEventFiltersRegistryKey);
    if (!lua_istable(state, -1)) {
        lua_settop(state, original_top);
        return true;
    }
    lua_getfield(state, -1, filter_name);
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
        PushDamageFilterPayload(state, filter_name, *context);
        if (lua_pcall(state, 1, 1, 0) != LUA_OK) {
            const auto* message = lua_tostring(state, -1);
            detail::LogLuaMessage(
                *mod,
                std::string(filter_name) + " filter failed: " +
                    (message == nullptr ? "unknown" : message));
            lua_pop(state, 1);
            continue;
        }

        bool canceled = false;
        std::string parse_error;
        if (!ApplyDamageFilterResult(
                state,
                -1,
                context,
                &canceled,
                &parse_error)) {
            detail::LogLuaMessage(
                *mod,
                std::string(filter_name) +
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

int LuaEventsFilter(lua_State* state) {
    auto* mod = detail::GetLoadedLuaMod(state);
    const auto* filter_name = luaL_checkstring(state, 1);
    luaL_checktype(state, 2, LUA_TFUNCTION);
    if (mod == nullptr || filter_name == nullptr) {
        return luaL_error(state, "sd.events.filter is unavailable");
    }

    const auto filter_mask = FilterMaskForName(filter_name);
    if (filter_mask == 0) {
        return luaL_error(state, "unsupported mutable event filter: %s", filter_name);
    }

    lua_getfield(state, LUA_REGISTRYINDEX, detail::kLuaEventFiltersRegistryKey);
    if (!lua_istable(state, -1)) {
        lua_pop(state, 1);
        return luaL_error(state, "event filter registry is unavailable");
    }
    lua_getfield(state, -1, filter_name);
    if (!lua_istable(state, -1)) {
        lua_pop(state, 1);
        lua_createtable(state, 0, 0);
        lua_pushvalue(state, -1);
        lua_setfield(state, -3, filter_name);
    }

    const auto next_index = lua_rawlen(state, -1) + 1;
    lua_pushvalue(state, 2);
    lua_rawseti(state, -2, static_cast<lua_Integer>(next_index));
    lua_pop(state, 2);

    mod->event_filter_mask |= filter_mask;
    g_registered_filter_mask.fetch_or(filter_mask, std::memory_order_release);
    lua_pushboolean(state, 1);
    return 1;
}

void RefreshRegisteredFilterMask() {
    std::uint32_t registered_mask = 0;
    for (const auto& mod : detail::LoadedLuaModsStorage()) {
        if (mod != nullptr) {
            registered_mask |= mod->event_filter_mask;
        }
    }
    g_registered_filter_mask.store(registered_mask, std::memory_order_release);
}

}  // namespace

bool HasLuaDamageFilterHandlers() {
    return (g_registered_filter_mask.load(std::memory_order_acquire) &
            kDamageFilterMask) != 0;
}

bool ApplyLuaDamageFilters(LuaDamageFilterContext* context) {
    if (context == nullptr || !HasLuaDamageFilterHandlers()) {
        return true;
    }

    std::unique_lock<std::mutex> lock(
        detail::LuaEngineMutex(),
        std::try_to_lock);
    if (!lock.owns_lock()) {
        const auto log_index =
            g_busy_log_count.fetch_add(1, std::memory_order_relaxed);
        if (log_index < kMaximumBusyLogCount) {
            Log("[lua] damage filters skipped because the Lua engine is busy");
        }
        return true;
    }
    if (!detail::LuaEngineInitializedFlag()) {
        return true;
    }

    constexpr struct {
        const char* name;
        std::uint32_t mask;
    } filters[] = {
        {"damage.dealing", kDamageDealingFilterMask},
        {"damage.taken", kDamageTakenFilterMask},
    };

    const auto registered_mask =
        g_registered_filter_mask.load(std::memory_order_acquire);
    for (const auto& filter : filters) {
        if ((registered_mask & filter.mask) == 0) {
            continue;
        }
        for (const auto& mod : detail::LoadedLuaModsStorage()) {
            if (!ApplyDamageFilterToMod(
                    mod.get(),
                    filter.name,
                    filter.mask,
                    context)) {
                return false;
            }
        }
    }
    return true;
}

namespace detail {

void RegisterLuaEventFilterBinding(lua_State* state) {
    RegisterFunction(state, &LuaEventsFilter, "filter");
}

void ResetLuaEventFilterRegistrations() {
    g_registered_filter_mask.store(0, std::memory_order_release);
    g_busy_log_count.store(0, std::memory_order_relaxed);
}

void ClearLuaEventFilterRegistrationsForMod(LoadedLuaMod* mod) {
    if (mod == nullptr) {
        return;
    }
    mod->event_filter_mask = 0;
    RefreshRegisteredFilterMask();
}

}  // namespace detail
}  // namespace sdmod
