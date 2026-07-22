#include "lua_event_filters.h"

#include "logger.h"
#include "lua_engine_internal.h"

extern "C" {
#include "lua.h"
}

#include <atomic>
#include <cstdint>
#include <mutex>
#include <string>

namespace sdmod {
namespace {

constexpr char kSpellCastingFilterName[] = "spell.casting";
constexpr std::uint32_t kMaximumBusyLogCount = 4;

std::atomic<std::uint32_t> g_spell_cast_busy_log_count{0};

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

void PushSpellCastFilterPayload(
    lua_State* state,
    const LuaSpellCastFilterContext& context) {
    lua_createtable(state, 0, 15);

    lua_pushstring(state, kSpellCastingFilterName);
    lua_setfield(state, -2, "event");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(context.caster_actor_address));
    lua_setfield(state, -2, "caster_actor_address");
    PushOptionalParticipantId(
        state,
        "caster_participant_id",
        context.caster_participant_id);
    lua_pushstring(
        state,
        context.kind == LuaSpellCastKind::Primary ? "primary" : "secondary");
    lua_setfield(state, -2, "kind");
    lua_pushinteger(state, static_cast<lua_Integer>(context.skill_id));
    lua_setfield(state, -2, "skill_id");
    if (context.secondary_slot < 0) {
        lua_pushnil(state);
    } else {
        lua_pushinteger(
            state,
            static_cast<lua_Integer>(context.secondary_slot));
    }
    lua_setfield(state, -2, "secondary_slot");

    if (context.has_position) {
        lua_pushnumber(state, static_cast<lua_Number>(context.position_x));
        lua_setfield(state, -2, "x");
        lua_pushnumber(state, static_cast<lua_Number>(context.position_y));
        lua_setfield(state, -2, "y");
    }
    if (context.has_direction) {
        lua_pushnumber(state, static_cast<lua_Number>(context.direction_x));
        lua_setfield(state, -2, "direction_x");
        lua_pushnumber(state, static_cast<lua_Number>(context.direction_y));
        lua_setfield(state, -2, "direction_y");
    }
    if (context.target_actor_address == 0) {
        lua_pushnil(state);
    } else {
        lua_pushinteger(
            state,
            static_cast<lua_Integer>(context.target_actor_address));
    }
    lua_setfield(state, -2, "target_actor_address");
    if (context.has_aim_target) {
        lua_pushnumber(state, static_cast<lua_Number>(context.aim_target_x));
        lua_setfield(state, -2, "aim_target_x");
        lua_pushnumber(state, static_cast<lua_Number>(context.aim_target_y));
        lua_setfield(state, -2, "aim_target_y");
    }
}

bool ReadSpellCastCancellation(
    lua_State* state,
    int result_index,
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

    const auto absolute_table_index = lua_absindex(state, result_index);
    lua_getfield(state, absolute_table_index, "cancel");
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

bool ApplySpellCastFilterToMod(
    detail::LoadedLuaMod* mod,
    const LuaSpellCastFilterContext& context) {
    if (mod == nullptr || mod->state == nullptr ||
        (mod->event_filter_mask & kLuaSpellCastingFilterMask) == 0) {
        return true;
    }

    auto* state = mod->state;
    const int original_top = lua_gettop(state);
    lua_getfield(state, LUA_REGISTRYINDEX, detail::kLuaEventFiltersRegistryKey);
    if (!lua_istable(state, -1)) {
        lua_settop(state, original_top);
        return true;
    }
    lua_getfield(state, -1, kSpellCastingFilterName);
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
        PushSpellCastFilterPayload(state, context);
        if (lua_pcall(state, 1, 1, 0) != LUA_OK) {
            const auto* message = lua_tostring(state, -1);
            detail::LogLuaMessage(
                *mod,
                std::string(kSpellCastingFilterName) + " filter failed: " +
                    (message == nullptr ? "unknown" : message));
            lua_pop(state, 1);
            continue;
        }

        bool canceled = false;
        std::string parse_error;
        if (!ReadSpellCastCancellation(
                state,
                -1,
                &canceled,
                &parse_error)) {
            detail::LogLuaMessage(
                *mod,
                std::string(kSpellCastingFilterName) +
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

bool ApplyLuaSpellCastFilters(const LuaSpellCastFilterContext& context) {
    if (!HasLuaSpellCastFilterHandlers()) {
        return true;
    }

    std::unique_lock<std::mutex> lock(
        detail::LuaEngineMutex(),
        std::try_to_lock);
    if (!lock.owns_lock()) {
        const auto log_index =
            g_spell_cast_busy_log_count.fetch_add(1, std::memory_order_relaxed);
        if (log_index < kMaximumBusyLogCount) {
            Log("[lua] spell cast filters skipped because the Lua engine is busy");
        }
        return true;
    }
    if (!detail::LuaEngineInitializedFlag()) {
        return true;
    }

    for (const auto& mod : detail::LoadedLuaModsStorage()) {
        if (!ApplySpellCastFilterToMod(mod.get(), context)) {
            return false;
        }
    }
    return true;
}

namespace detail {

void ResetLuaSpellCastFilterDiagnostics() {
    g_spell_cast_busy_log_count.store(0, std::memory_order_relaxed);
}

}  // namespace detail
}  // namespace sdmod
