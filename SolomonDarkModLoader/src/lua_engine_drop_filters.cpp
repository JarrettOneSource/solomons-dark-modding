#include "lua_event_filters.h"

#include "logger.h"
#include "lua_engine_internal.h"

extern "C" {
#include "lua.h"
}

#include <array>
#include <atomic>
#include <cmath>
#include <cstdint>
#include <mutex>
#include <string>
#include <string_view>

namespace sdmod {
namespace {

constexpr char kDropRollingFilterName[] = "drop.rolling";
constexpr std::uint8_t kMaximumNativeDropSelector = 5;
constexpr std::uint32_t kMaximumBusyLogCount = 4;
constexpr std::array<const char*, kLuaDropSelectorCount> kSelectorNames = {
    "orb",
    "powerup",
    "item",
    "gold",
    "specific_item",
    "potion",
};

std::atomic<std::uint32_t> g_drop_roll_busy_log_count{0};

const char* DropKindName(LuaDropForcedKind kind) {
    switch (kind) {
    case LuaDropForcedKind::Stock:
        return "stock";
    case LuaDropForcedKind::None:
        return "none";
    case LuaDropForcedKind::Orb:
        return "orb";
    case LuaDropForcedKind::Gold:
        return "gold";
    case LuaDropForcedKind::Item:
        return "item";
    case LuaDropForcedKind::Powerup:
        return "powerup";
    case LuaDropForcedKind::Potion:
        return "potion";
    }
    return "stock";
}

bool TryParseDropKind(std::string_view name, LuaDropForcedKind* kind) {
    if (kind == nullptr) {
        return false;
    }
    if (name == "stock") {
        *kind = LuaDropForcedKind::Stock;
    } else if (name == "none") {
        *kind = LuaDropForcedKind::None;
    } else if (name == "orb") {
        *kind = LuaDropForcedKind::Orb;
    } else if (name == "gold") {
        *kind = LuaDropForcedKind::Gold;
    } else if (name == "item") {
        *kind = LuaDropForcedKind::Item;
    } else if (name == "powerup") {
        *kind = LuaDropForcedKind::Powerup;
    } else if (name == "potion") {
        *kind = LuaDropForcedKind::Potion;
    } else {
        return false;
    }
    return true;
}

void PushDropRollFilterPayload(
    lua_State* state,
    const LuaDropRollFilterContext& context) {
    lua_createtable(state, 0, 14);

    lua_pushstring(state, kDropRollingFilterName);
    lua_setfield(state, -2, "event");
    lua_pushstring(state, DropKindName(context.forced_kind));
    lua_setfield(state, -2, "kind");
    lua_pushinteger(state, static_cast<lua_Integer>(context.native_type_id));
    lua_setfield(state, -2, "native_type_id");
    lua_pushinteger(state, static_cast<lua_Integer>(context.enemy_address));
    lua_setfield(state, -2, "enemy_address");
    lua_pushinteger(state, static_cast<lua_Integer>(context.arena_address));
    lua_setfield(state, -2, "arena_address");
    lua_pushinteger(state, static_cast<lua_Integer>(context.config_address));
    lua_setfield(state, -2, "config_address");
    lua_pushnumber(state, static_cast<lua_Number>(context.x));
    lua_setfield(state, -2, "x");
    lua_pushnumber(state, static_cast<lua_Number>(context.y));
    lua_setfield(state, -2, "y");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(context.arena_disable_mask));
    lua_setfield(state, -2, "arena_disable_mask");

    lua_createtable(
        state,
        static_cast<int>(context.selectors.size()),
        static_cast<int>(context.selectors.size()));
    for (std::size_t index = 0; index < context.selectors.size(); ++index) {
        lua_pushinteger(
            state,
            static_cast<lua_Integer>(context.selectors[index]));
        lua_rawseti(state, -2, static_cast<lua_Integer>(index + 1));
        lua_pushinteger(
            state,
            static_cast<lua_Integer>(context.selectors[index]));
        lua_setfield(state, -2, kSelectorNames[index]);
    }
    lua_setfield(state, -2, "selectors");

    for (std::size_t index = 0; index < context.selectors.size(); ++index) {
        const std::string field_name =
            std::string(kSelectorNames[index]) + "_selector";
        lua_pushinteger(
            state,
            static_cast<lua_Integer>(context.selectors[index]));
        lua_setfield(state, -2, field_name.c_str());
    }
}

bool ReadSelectorValue(
    lua_State* state,
    int value_index,
    const std::string& field_name,
    std::uint8_t* value,
    std::string* error_message) {
    if (lua_type(state, value_index) != LUA_TNUMBER) {
        if (error_message != nullptr) {
            *error_message = field_name + " must be an integer";
        }
        return false;
    }

    const auto candidate = lua_tonumber(state, value_index);
    if (!std::isfinite(candidate) ||
        std::floor(candidate) != candidate ||
        candidate < 0.0 ||
        candidate > static_cast<lua_Number>(kMaximumNativeDropSelector)) {
        if (error_message != nullptr) {
            *error_message = field_name + " must be an integer in 0..5";
        }
        return false;
    }
    *value = static_cast<std::uint8_t>(candidate);
    return true;
}

bool ReadOptionalNamedSelector(
    lua_State* state,
    int table_index,
    const char* field_name,
    std::uint8_t* value,
    std::string* error_message) {
    lua_getfield(state, table_index, field_name);
    if (lua_isnil(state, -1)) {
        lua_pop(state, 1);
        return true;
    }
    const bool valid = ReadSelectorValue(
        state,
        -1,
        field_name,
        value,
        error_message);
    lua_pop(state, 1);
    return valid;
}

bool ParseDropRollFilterTable(
    lua_State* state,
    int table_index,
    LuaDropRollFilterContext* candidate,
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

    lua_getfield(state, absolute_table_index, "kind");
    if (!lua_isnil(state, -1)) {
        if (lua_type(state, -1) != LUA_TSTRING) {
            if (error_message != nullptr) {
                *error_message = "kind must be a string";
            }
            lua_pop(state, 1);
            return false;
        }
        const auto* kind_name = lua_tostring(state, -1);
        LuaDropForcedKind kind = LuaDropForcedKind::Stock;
        if (kind_name == nullptr || !TryParseDropKind(kind_name, &kind)) {
            if (error_message != nullptr) {
                *error_message =
                    "kind must be stock, none, orb, gold, item, powerup, or potion";
            }
            lua_pop(state, 1);
            return false;
        }
        candidate->forced_kind = kind;
    }
    lua_pop(state, 1);

    lua_getfield(state, absolute_table_index, "selectors");
    if (!lua_isnil(state, -1)) {
        if (!lua_istable(state, -1)) {
            if (error_message != nullptr) {
                *error_message = "selectors must be a table";
            }
            lua_pop(state, 1);
            return false;
        }
        const auto selectors_index = lua_absindex(state, -1);
        for (std::size_t index = 0; index < candidate->selectors.size(); ++index) {
            lua_getfield(state, selectors_index, kSelectorNames[index]);
            if (lua_isnil(state, -1)) {
                lua_pop(state, 1);
                lua_rawgeti(
                    state,
                    selectors_index,
                    static_cast<lua_Integer>(index + 1));
            }
            if (!lua_isnil(state, -1) &&
                !ReadSelectorValue(
                    state,
                    -1,
                    std::string("selectors.") + kSelectorNames[index],
                    &candidate->selectors[index],
                    error_message)) {
                lua_pop(state, 2);
                return false;
            }
            lua_pop(state, 1);
        }
    }
    lua_pop(state, 1);

    for (std::size_t index = 0; index < candidate->selectors.size(); ++index) {
        const std::string field_name =
            std::string(kSelectorNames[index]) + "_selector";
        if (!ReadOptionalNamedSelector(
                state,
                absolute_table_index,
                field_name.c_str(),
                &candidate->selectors[index],
                error_message)) {
            return false;
        }
    }

    *canceled = requested_cancel;
    return true;
}

bool ApplyDropRollFilterResult(
    lua_State* state,
    int result_index,
    LuaDropRollFilterContext* context,
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
    if (!ParseDropRollFilterTable(
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

bool ApplyDropRollFilterToMod(
    detail::LoadedLuaMod* mod,
    LuaDropRollFilterContext* context) {
    if (mod == nullptr || mod->state == nullptr ||
        (mod->event_filter_mask & kLuaDropRollingFilterMask) == 0) {
        return true;
    }

    auto* state = mod->state;
    const int original_top = lua_gettop(state);
    lua_getfield(state, LUA_REGISTRYINDEX, detail::kLuaEventFiltersRegistryKey);
    if (!lua_istable(state, -1)) {
        lua_settop(state, original_top);
        return true;
    }
    lua_getfield(state, -1, kDropRollingFilterName);
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
        PushDropRollFilterPayload(state, *context);
        if (lua_pcall(state, 1, 1, 0) != LUA_OK) {
            const auto* message = lua_tostring(state, -1);
            detail::LogLuaMessage(
                *mod,
                std::string(kDropRollingFilterName) + " filter failed: " +
                    (message == nullptr ? "unknown" : message));
            lua_pop(state, 1);
            continue;
        }

        bool canceled = false;
        std::string parse_error;
        if (!ApplyDropRollFilterResult(
                state,
                -1,
                context,
                &canceled,
                &parse_error)) {
            detail::LogLuaMessage(
                *mod,
                std::string(kDropRollingFilterName) +
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

bool ApplyLuaDropRollFilters(LuaDropRollFilterContext* context) {
    if (context == nullptr || !HasLuaDropRollFilterHandlers()) {
        return true;
    }

    std::unique_lock<std::mutex> lock(
        detail::LuaEngineMutex(),
        std::try_to_lock);
    if (!lock.owns_lock()) {
        const auto log_index =
            g_drop_roll_busy_log_count.fetch_add(1, std::memory_order_relaxed);
        if (log_index < kMaximumBusyLogCount) {
            Log("[lua] drop roll filters skipped because the Lua engine is busy");
        }
        return true;
    }
    if (!detail::LuaEngineInitializedFlag()) {
        return true;
    }

    for (const auto& mod : detail::LoadedLuaModsStorage()) {
        if (!ApplyDropRollFilterToMod(mod.get(), context)) {
            return false;
        }
    }
    return true;
}

namespace detail {

void ResetLuaDropRollFilterDiagnostics() {
    g_drop_roll_busy_log_count.store(0, std::memory_order_relaxed);
}

}  // namespace detail
}  // namespace sdmod
