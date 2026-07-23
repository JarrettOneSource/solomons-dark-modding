#include "lua_engine_bindings_internal.h"

#include "mod_loader.h"
#include "multiplayer_local_transport.h"
#include "multiplayer_runtime_state.h"

#include <cmath>
#include <cstdint>
#include <limits>
#include <string>

namespace sdmod::detail {
namespace {

constexpr lua_Integer kMaximumRunGenerationSeed = 0x3FFFFFFF;
constexpr lua_Integer kMaximumNavGridSubdivisions = 4;

void RequireSimulationAuthority(lua_State* state, const char* api_name) {
    if (!multiplayer::IsLuaModSimulationAuthority()) {
        luaL_error(
            state,
            "%s may only be called by the simulation authority",
            api_name);
    }
}

float CheckFiniteFloat(lua_State* state, int index, const char* argument_name) {
    const auto value = luaL_checknumber(state, index);
    const auto maximum =
        static_cast<lua_Number>((std::numeric_limits<float>::max)());
    if (!std::isfinite(value) || value < -maximum || value > maximum) {
        luaL_error(state, "%s must be a finite 32-bit number", argument_name);
    }
    return static_cast<float>(value);
}

int LuaRngGetSeed(lua_State* state) {
    const auto runtime = multiplayer::SnapshotRuntimeState();
    const auto* local = multiplayer::FindLocalParticipant(runtime);
    if (local == nullptr || local->runtime.run_nonce == 0) {
        lua_pushnil(state);
        return 1;
    }

    lua_pushinteger(
        state,
        static_cast<lua_Integer>(local->runtime.run_nonce));
    return 1;
}

int LuaRngSetSeed(lua_State* state) {
    RequireSimulationAuthority(state, "sd.rng.set_seed");
    if (!lua_isinteger(state, 1)) {
        return luaL_error(
            state,
            "sd.rng.set_seed seed must be an integer from 1 through 0x3fffffff");
    }

    const auto seed = lua_tointeger(state, 1);
    if (seed < 1 || seed > kMaximumRunGenerationSeed) {
        return luaL_error(
            state,
            "sd.rng.set_seed seed must be an integer from 1 through 0x3fffffff");
    }

    const auto runtime = multiplayer::SnapshotRuntimeState();
    const auto* local = multiplayer::FindLocalParticipant(runtime);
    if (local != nullptr && local->runtime.in_run) {
        return luaL_error(
            state,
            "sd.rng.set_seed must be called before entering a run");
    }

    std::string error_message;
    if (!SetPendingRunGenerationSeed(
            static_cast<std::uint32_t>(seed),
            &error_message)) {
        return luaL_error(
            state,
            "sd.rng.set_seed failed: %s",
            error_message.c_str());
    }

    lua_pushinteger(state, seed);
    return 1;
}

void PushNavGrid(lua_State* state, const SDModGameplayNavGridState& grid, int requested_subdivisions) {
    lua_createtable(state, 0, 10);
    lua_pushinteger(state, static_cast<lua_Integer>(grid.width));
    lua_setfield(state, -2, "width");
    lua_pushinteger(state, static_cast<lua_Integer>(grid.height));
    lua_setfield(state, -2, "height");
    lua_pushnumber(state, static_cast<lua_Number>(grid.cell_width));
    lua_setfield(state, -2, "cell_width");
    lua_pushnumber(state, static_cast<lua_Number>(grid.cell_height));
    lua_setfield(state, -2, "cell_height");
    lua_pushnumber(state, static_cast<lua_Number>(grid.probe_x));
    lua_setfield(state, -2, "probe_x");
    lua_pushnumber(state, static_cast<lua_Number>(grid.probe_y));
    lua_setfield(state, -2, "probe_y");
    lua_pushinteger(state, static_cast<lua_Integer>(grid.subdivisions));
    lua_setfield(state, -2, "subdivisions");
    lua_pushinteger(state, static_cast<lua_Integer>(requested_subdivisions));
    lua_setfield(state, -2, "requested_subdivisions");
    lua_pushboolean(state, grid.subdivisions != requested_subdivisions ? 1 : 0);
    lua_setfield(state, -2, "refresh_pending");

    lua_createtable(state, static_cast<int>(grid.cells.size()), 0);
    lua_Integer cell_index = 1;
    for (const auto& cell : grid.cells) {
        lua_createtable(state, 0, 7);
        lua_pushinteger(state, static_cast<lua_Integer>(cell.grid_x));
        lua_setfield(state, -2, "grid_x");
        lua_pushinteger(state, static_cast<lua_Integer>(cell.grid_y));
        lua_setfield(state, -2, "grid_y");
        lua_pushnumber(state, static_cast<lua_Number>(cell.center_x));
        lua_setfield(state, -2, "center_x");
        lua_pushnumber(state, static_cast<lua_Number>(cell.center_y));
        lua_setfield(state, -2, "center_y");
        lua_pushboolean(state, cell.traversable ? 1 : 0);
        lua_setfield(state, -2, "traversable");
        lua_pushboolean(state, cell.path_traversable ? 1 : 0);
        lua_setfield(state, -2, "path_traversable");

        lua_createtable(state, static_cast<int>(cell.samples.size()), 0);
        lua_Integer sample_index = 1;
        for (const auto& sample : cell.samples) {
            lua_createtable(state, 0, 5);
            lua_pushinteger(state, static_cast<lua_Integer>(sample.sample_x));
            lua_setfield(state, -2, "sample_x");
            lua_pushinteger(state, static_cast<lua_Integer>(sample.sample_y));
            lua_setfield(state, -2, "sample_y");
            lua_pushnumber(state, static_cast<lua_Number>(sample.world_x));
            lua_setfield(state, -2, "world_x");
            lua_pushnumber(state, static_cast<lua_Number>(sample.world_y));
            lua_setfield(state, -2, "world_y");
            lua_pushboolean(state, sample.traversable ? 1 : 0);
            lua_setfield(state, -2, "traversable");
            lua_rawseti(state, -2, sample_index++);
        }
        lua_setfield(state, -2, "samples");
        lua_rawseti(state, -2, cell_index++);
    }
    lua_setfield(state, -2, "cells");
}

int LuaNavGetGrid(lua_State* state) {
    lua_Integer subdivisions = 1;
    if (lua_gettop(state) >= 1 && !lua_isnil(state, 1)) {
        if (!lua_isinteger(state, 1)) {
            return luaL_error(
                state,
                "sd.nav.get_grid subdivisions must be an integer from 1 through 4");
        }
        subdivisions = lua_tointeger(state, 1);
    }
    if (subdivisions < 1 || subdivisions > kMaximumNavGridSubdivisions) {
        return luaL_error(
            state,
            "sd.nav.get_grid subdivisions must be an integer from 1 through 4");
    }

    RequestNavGridSnapshotRebuild(static_cast<int>(subdivisions));
    const auto snapshot = GetLastNavGridSnapshotShared();
    if (snapshot == nullptr || !snapshot->valid) {
        lua_pushnil(state);
        return 1;
    }

    SDModPlayerState player;
    if (!TryGetPlayerState(&player) ||
        !player.valid ||
        player.world_address == 0 ||
        player.world_address != snapshot->world_address) {
        lua_pushnil(state);
        return 1;
    }

    PushNavGrid(state, *snapshot, static_cast<int>(subdivisions));
    return 1;
}

int LuaNavTestSegment(lua_State* state) {
    const auto from_x = CheckFiniteFloat(state, 1, "from_x");
    const auto from_y = CheckFiniteFloat(state, 2, "from_y");
    const auto to_x = CheckFiniteFloat(state, 3, "to_x");
    const auto to_y = CheckFiniteFloat(state, 4, "to_y");

    bool traversable = false;
    std::string error_message;
    if (!TryTestGameplayNavSegment(
            from_x,
            from_y,
            to_x,
            to_y,
            &traversable,
            &error_message)) {
        return luaL_error(
            state,
            "sd.nav.test_segment failed: %s",
            error_message.c_str());
    }

    lua_pushboolean(state, traversable ? 1 : 0);
    return 1;
}

}  // namespace

void RegisterLuaRngBindings(lua_State* state) {
    lua_createtable(state, 0, 2);
    RegisterFunction(state, &LuaRngGetSeed, "get_seed");
    RegisterFunction(state, &LuaRngSetSeed, "set_seed");
    lua_setfield(state, -2, "rng");
}

void RegisterLuaNavBindings(lua_State* state) {
    lua_createtable(state, 0, 2);
    RegisterFunction(state, &LuaNavGetGrid, "get_grid");
    RegisterFunction(state, &LuaNavTestSegment, "test_segment");
    lua_setfield(state, -2, "nav");
}

}  // namespace sdmod::detail
