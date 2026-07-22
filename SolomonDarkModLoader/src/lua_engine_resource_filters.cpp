#include "lua_event_filters.h"

#include "logger.h"
#include "lua_engine_internal.h"

extern "C" {
#include "lua.h"
}

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdint>
#include <limits>
#include <mutex>
#include <string>

namespace sdmod {
namespace {

constexpr char kXpGainingFilterName[] = "xp.gaining";
constexpr char kGoldChangingFilterName[] = "gold.changing";
constexpr float kMaximumXpGain = 1'000'000.0f;
constexpr std::uint32_t kMaximumBusyLogCount = 4;

std::atomic<std::uint32_t> g_resource_filter_busy_log_count{0};

void PushOptionalParticipantId(
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

void PushXpGainFilterPayload(
    lua_State* state,
    const LuaXpGainFilterContext& context) {
    lua_createtable(state, 0, 7);
    lua_pushstring(state, kXpGainingFilterName);
    lua_setfield(state, -2, "event");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(context.progression_address));
    lua_setfield(state, -2, "progression_address");
    PushOptionalParticipantId(state, "participant_id", context.participant_id);
    lua_pushnumber(state, static_cast<lua_Number>(context.current_xp));
    lua_setfield(state, -2, "current_xp");
    lua_pushnumber(state, static_cast<lua_Number>(context.amount));
    lua_setfield(state, -2, "amount");
    lua_pushboolean(state, context.apply_native_scaling ? 1 : 0);
    lua_setfield(state, -2, "native_scaling");
    lua_pushstring(state, context.source == nullptr ? "unknown" : context.source);
    lua_setfield(state, -2, "source");
}

bool ComputeGoldResult(
    const LuaGoldChangeFilterContext& context,
    std::int32_t* resulting_gold,
    bool* would_succeed) {
    const auto sum =
        static_cast<std::int64_t>(context.current_gold) +
        static_cast<std::int64_t>(context.delta);
    if (sum < (std::numeric_limits<std::int32_t>::min)() ||
        sum > (std::numeric_limits<std::int32_t>::max)()) {
        return false;
    }

    *would_succeed = context.allow_negative || sum >= 0;
    *resulting_gold = !*would_succeed
        ? context.current_gold
        : static_cast<std::int32_t>((std::max)(std::int64_t{0}, sum));
    return true;
}

void PushGoldChangeFilterPayload(
    lua_State* state,
    const LuaGoldChangeFilterContext& context) {
    std::int32_t resulting_gold = context.current_gold;
    bool would_succeed = false;
    (void)ComputeGoldResult(context, &resulting_gold, &would_succeed);

    lua_createtable(state, 0, 8);
    lua_pushstring(state, kGoldChangingFilterName);
    lua_setfield(state, -2, "event");
    PushOptionalParticipantId(state, "participant_id", context.participant_id);
    lua_pushinteger(state, static_cast<lua_Integer>(context.current_gold));
    lua_setfield(state, -2, "current_gold");
    lua_pushinteger(state, static_cast<lua_Integer>(context.delta));
    lua_setfield(state, -2, "delta");
    lua_pushinteger(state, static_cast<lua_Integer>(resulting_gold));
    lua_setfield(state, -2, "resulting_gold");
    lua_pushboolean(state, context.allow_negative ? 1 : 0);
    lua_setfield(state, -2, "allow_negative");
    lua_pushboolean(state, would_succeed ? 1 : 0);
    lua_setfield(state, -2, "would_succeed");
    lua_pushstring(state, context.source == nullptr ? "unknown" : context.source);
    lua_setfield(state, -2, "source");
}

bool ReadCancellation(
    lua_State* state,
    int table_index,
    bool* canceled,
    std::string* error_message) {
    lua_getfield(state, table_index, "cancel");
    if (!lua_isnil(state, -1) && !lua_isboolean(state, -1)) {
        if (error_message != nullptr) {
            *error_message = "cancel must be a boolean";
        }
        lua_pop(state, 1);
        return false;
    }
    *canceled = lua_toboolean(state, -1) != 0;
    lua_pop(state, 1);
    return true;
}

bool ParseXpGainPatch(
    lua_State* state,
    int table_index,
    LuaXpGainFilterContext* candidate,
    bool* canceled,
    std::string* error_message) {
    const auto absolute_index = lua_absindex(state, table_index);
    bool requested_cancel = false;
    if (!ReadCancellation(
            state,
            absolute_index,
            &requested_cancel,
            error_message)) {
        return false;
    }

    lua_getfield(state, absolute_index, "amount");
    if (!lua_isnil(state, -1)) {
        if (lua_type(state, -1) != LUA_TNUMBER) {
            if (error_message != nullptr) {
                *error_message = "amount must be a number";
            }
            lua_pop(state, 1);
            return false;
        }
        const auto amount = lua_tonumber(state, -1);
        if (!std::isfinite(amount) || amount < 0.0 || amount > kMaximumXpGain) {
            if (error_message != nullptr) {
                *error_message = "amount must be finite and within 0..1000000";
            }
            lua_pop(state, 1);
            return false;
        }
        candidate->amount = static_cast<float>(amount);
    }
    lua_pop(state, 1);
    *canceled = requested_cancel;
    return true;
}

bool ParseGoldChangePatch(
    lua_State* state,
    int table_index,
    LuaGoldChangeFilterContext* candidate,
    bool* canceled,
    std::string* error_message) {
    const auto absolute_index = lua_absindex(state, table_index);
    bool requested_cancel = false;
    if (!ReadCancellation(
            state,
            absolute_index,
            &requested_cancel,
            error_message)) {
        return false;
    }

    lua_getfield(state, absolute_index, "delta");
    if (!lua_isnil(state, -1)) {
        if (lua_type(state, -1) != LUA_TNUMBER) {
            if (error_message != nullptr) {
                *error_message = "delta must be an integer";
            }
            lua_pop(state, 1);
            return false;
        }
        const auto delta = lua_tonumber(state, -1);
        if (!std::isfinite(delta) || std::trunc(delta) != delta ||
            delta < static_cast<lua_Number>((std::numeric_limits<std::int32_t>::min)()) ||
            delta > static_cast<lua_Number>((std::numeric_limits<std::int32_t>::max)())) {
            if (error_message != nullptr) {
                *error_message = "delta must be a signed 32-bit integer";
            }
            lua_pop(state, 1);
            return false;
        }
        candidate->delta = static_cast<std::int32_t>(delta);
        std::int32_t resulting_gold = 0;
        bool would_succeed = false;
        if (!ComputeGoldResult(*candidate, &resulting_gold, &would_succeed)) {
            if (error_message != nullptr) {
                *error_message = "delta would overflow the native gold total";
            }
            lua_pop(state, 1);
            return false;
        }
    }
    lua_pop(state, 1);
    *canceled = requested_cancel;
    return true;
}

template <typename Context, typename ParsePatch>
bool ApplyResourceFilterResult(
    lua_State* state,
    int result_index,
    Context* context,
    ParsePatch parse_patch,
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
    bool requested_cancel = false;
    if (!parse_patch(
            state,
            result_index,
            &candidate,
            &requested_cancel,
            error_message)) {
        return false;
    }
    if (!requested_cancel) {
        *context = candidate;
    }
    *canceled = requested_cancel;
    return true;
}

template <typename Context, typename PushPayload, typename ParsePatch>
bool ApplyResourceFilterToMod(
    detail::LoadedLuaMod* mod,
    const char* filter_name,
    std::uint32_t filter_mask,
    Context* context,
    PushPayload push_payload,
    ParsePatch parse_patch) {
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
        push_payload(state, *context);
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
        if (!ApplyResourceFilterResult(
                state,
                -1,
                context,
                parse_patch,
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

template <typename Apply>
bool ApplyResourceFiltersWithLock(const char* label, Apply apply) {
    std::unique_lock<std::mutex> lock(
        detail::LuaEngineMutex(),
        std::try_to_lock);
    if (!lock.owns_lock()) {
        const auto log_index =
            g_resource_filter_busy_log_count.fetch_add(1, std::memory_order_relaxed);
        if (log_index < kMaximumBusyLogCount) {
            Log(std::string("[lua] ") + label +
                " filters skipped because the Lua engine is busy");
        }
        return true;
    }
    if (!detail::LuaEngineInitializedFlag()) {
        return true;
    }
    return apply();
}

}  // namespace

bool ApplyLuaXpGainFilters(LuaXpGainFilterContext* context) {
    if (context == nullptr || !HasLuaXpGainFilterHandlers()) {
        return true;
    }
    return ApplyResourceFiltersWithLock("XP gain", [&]() {
        for (const auto& mod : detail::LoadedLuaModsStorage()) {
            if (!ApplyResourceFilterToMod(
                    mod.get(),
                    kXpGainingFilterName,
                    kLuaXpGainingFilterMask,
                    context,
                    PushXpGainFilterPayload,
                    ParseXpGainPatch)) {
                return false;
            }
        }
        return true;
    });
}

bool ApplyLuaGoldChangeFilters(LuaGoldChangeFilterContext* context) {
    if (context == nullptr || !HasLuaGoldChangeFilterHandlers()) {
        return true;
    }
    return ApplyResourceFiltersWithLock("gold change", [&]() {
        for (const auto& mod : detail::LoadedLuaModsStorage()) {
            if (!ApplyResourceFilterToMod(
                    mod.get(),
                    kGoldChangingFilterName,
                    kLuaGoldChangingFilterMask,
                    context,
                    PushGoldChangeFilterPayload,
                    ParseGoldChangePatch)) {
                return false;
            }
        }
        return true;
    });
}

namespace detail {

void ResetLuaResourceFilterDiagnostics() {
    g_resource_filter_busy_log_count.store(0, std::memory_order_relaxed);
}

}  // namespace detail
}  // namespace sdmod
