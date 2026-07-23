#include "lua_engine_bindings_internal.h"

#include "wave_intelligence.h"

#include <cstddef>

namespace sdmod::detail {
namespace {

void PushWaveComposition(
    lua_State* state,
    const std::vector<WaveCompositionRow>& composition,
    bool live_counts) {
    lua_createtable(state, static_cast<int>(composition.size()), 0);
    for (std::size_t index = 0; index < composition.size(); ++index) {
        const auto& row = composition[index];
        lua_createtable(state, 0, live_counts ? 5 : 2);
        lua_pushinteger(state, static_cast<lua_Integer>(row.enemy_type));
        lua_setfield(state, -2, "enemy_type");
        lua_pushinteger(state, static_cast<lua_Integer>(row.planned));
        lua_setfield(state, -2, "planned");
        if (live_counts) {
            lua_pushinteger(state, static_cast<lua_Integer>(row.spawned));
            lua_setfield(state, -2, "spawned");
            lua_pushinteger(state, static_cast<lua_Integer>(row.alive));
            lua_setfield(state, -2, "alive");
            lua_pushinteger(state, static_cast<lua_Integer>(row.killed));
            lua_setfield(state, -2, "killed");
        }
        lua_rawseti(state, -2, static_cast<lua_Integer>(index + 1));
    }
}

int LuaWavesGetState(lua_State* state) {
    const auto summary = SnapshotWaveSummary();
    if (!summary.valid) {
        lua_pushnil(state);
        return 1;
    }

    lua_createtable(state, 0, 8);
    lua_pushinteger(state, static_cast<lua_Integer>(summary.wave));
    lua_setfield(state, -2, "wave");
    lua_pushstring(state, WavePhaseLabel(summary.phase));
    lua_setfield(state, -2, "phase");
    lua_pushinteger(state, static_cast<lua_Integer>(summary.remaining_to_spawn));
    lua_setfield(state, -2, "remaining_to_spawn");
    lua_pushinteger(state, static_cast<lua_Integer>(summary.spawned));
    lua_setfield(state, -2, "spawned");
    lua_pushinteger(state, static_cast<lua_Integer>(summary.alive));
    lua_setfield(state, -2, "alive");
    lua_pushinteger(state, static_cast<lua_Integer>(summary.killed));
    lua_setfield(state, -2, "killed");
    std::int32_t planned = 0;
    for (const auto& row : summary.composition) {
        planned += row.planned;
    }
    lua_pushinteger(state, static_cast<lua_Integer>(planned));
    lua_setfield(state, -2, "planned");
    PushWaveComposition(state, summary.composition, true);
    lua_setfield(state, -2, "composition");
    return 1;
}

void PushWaveScheduleEntry(lua_State* state, const WaveScheduleEntry& entry) {
    lua_createtable(state, 0, 10);
    lua_pushinteger(state, static_cast<lua_Integer>(entry.wave));
    lua_setfield(state, -2, "wave");
    lua_pushinteger(state, static_cast<lua_Integer>(entry.spawn_budget));
    lua_setfield(state, -2, "spawn_budget");
    lua_pushinteger(state, static_cast<lua_Integer>(entry.spawn_delay_min));
    lua_setfield(state, -2, "spawn_delay_min");
    lua_pushinteger(state, static_cast<lua_Integer>(entry.spawn_delay_max));
    lua_setfield(state, -2, "spawn_delay_max");
    lua_pushinteger(state, static_cast<lua_Integer>(entry.wave_delay_min));
    lua_setfield(state, -2, "wave_delay_min");
    lua_pushinteger(state, static_cast<lua_Integer>(entry.wave_delay_max));
    lua_setfield(state, -2, "wave_delay_max");
    lua_pushinteger(state, static_cast<lua_Integer>(entry.max_enemies));
    lua_setfield(state, -2, "max_enemies");
    lua_pushboolean(state, entry.zombie_wave ? 1 : 0);
    lua_setfield(state, -2, "zombie_wave");
    lua_pushboolean(state, entry.random_group_projection ? 1 : 0);
    lua_setfield(state, -2, "random_group_projection");
    PushWaveComposition(state, entry.composition, false);
    lua_setfield(state, -2, "composition");
}

int LuaWavesGetSchedule(lua_State* state) {
    if (!lua_isinteger(state, 1)) {
        return luaL_error(state, "sd.waves.get_schedule count must be an integer from 1 through 64");
    }
    const auto count = lua_tointeger(state, 1);
    if (count < 1 || count > 64) {
        return luaL_error(state, "sd.waves.get_schedule count must be an integer from 1 through 64");
    }
    const auto schedule = GetUpcomingWaveSchedule(static_cast<std::size_t>(count));
    lua_createtable(state, static_cast<int>(schedule.size()), 0);
    for (std::size_t index = 0; index < schedule.size(); ++index) {
        PushWaveScheduleEntry(state, schedule[index]);
        lua_rawseti(state, -2, static_cast<lua_Integer>(index + 1));
    }
    return 1;
}

}  // namespace

void RegisterLuaWaveBindings(lua_State* state) {
    lua_createtable(state, 0, 2);
    RegisterFunction(state, &LuaWavesGetState, "get_state");
    RegisterFunction(state, &LuaWavesGetSchedule, "get_schedule");
    lua_setfield(state, -2, "waves");
}

}  // namespace sdmod::detail
