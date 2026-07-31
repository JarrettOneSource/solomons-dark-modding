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

void PushCollisionGeometry(
    lua_State* state,
    const SDModCollisionGeometryState& geometry) {
    lua_createtable(state, 0, 14);
    lua_pushboolean(state, geometry.valid ? 1 : 0);
    lua_setfield(state, -2, "valid");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(geometry.scene_epoch));
    lua_setfield(state, -2, "scene_epoch");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(geometry.run_nonce));
    lua_setfield(state, -2, "run_nonce");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(geometry.static_revision));
    lua_setfield(state, -2, "static_revision");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(geometry.dynamic_revision));
    lua_setfield(state, -2, "dynamic_revision");
    lua_pushboolean(state, geometry.refresh_pending ? 1 : 0);
    lua_setfield(state, -2, "refresh_pending");
    lua_pushnumber(
        state,
        static_cast<lua_Number>(geometry.observer_radius));
    lua_setfield(state, -2, "observer_radius");
    lua_pushboolean(
        state,
        geometry.observer_radius_resolved ? 1 : 0);
    lua_setfield(state, -2, "observer_radius_resolved");
    lua_pushnumber(
        state,
        static_cast<lua_Number>(
            geometry.participant_collision_padding));
    lua_setfield(state, -2, "participant_collision_padding");

    lua_createtable(
        state,
        static_cast<int>(geometry.circles.size()),
        0);
    lua_Integer output_index = 1;
    for (const auto& circle : geometry.circles) {
        lua_createtable(state, 0, 12);
        lua_pushinteger(
            state,
            static_cast<lua_Integer>(circle.geometry_id));
        lua_setfield(state, -2, "geometry_id");
        lua_pushinteger(
            state,
            static_cast<lua_Integer>(circle.native_type_id));
        lua_setfield(state, -2, "native_type_id");
        lua_pushnumber(state, circle.x);
        lua_setfield(state, -2, "x");
        lua_pushnumber(state, circle.y);
        lua_setfield(state, -2, "y");
        lua_pushnumber(state, circle.radius);
        lua_setfield(state, -2, "radius");
        lua_pushinteger(
            state,
            static_cast<lua_Integer>(circle.mask));
        lua_setfield(state, -2, "mask");
        lua_pushboolean(state, circle.path_blocks ? 1 : 0);
        lua_setfield(state, -2, "path_blocks");
        lua_pushboolean(state, circle.pushable ? 1 : 0);
        lua_setfield(state, -2, "pushable");
        lua_pushboolean(state, circle.destructible ? 1 : 0);
        lua_setfield(state, -2, "destructible");
        lua_pushboolean(
            state,
            circle.destructible_resolved ? 1 : 0);
        lua_setfield(state, -2, "destructible_resolved");
        lua_pushboolean(state, circle.dynamic ? 1 : 0);
        lua_setfield(state, -2, "dynamic");
        lua_rawseti(state, -2, output_index++);
    }
    lua_setfield(state, -2, "circles");

    lua_createtable(
        state,
        static_cast<int>(geometry.segments.size()),
        0);
    output_index = 1;
    for (const auto& segment : geometry.segments) {
        lua_createtable(state, 0, 14);
        lua_pushinteger(
            state,
            static_cast<lua_Integer>(segment.geometry_id));
        lua_setfield(state, -2, "geometry_id");
        lua_pushinteger(
            state,
            static_cast<lua_Integer>(segment.native_type_id));
        lua_setfield(state, -2, "native_type_id");
        lua_pushnumber(state, segment.start_x);
        lua_setfield(state, -2, "start_x");
        lua_pushnumber(state, segment.start_y);
        lua_setfield(state, -2, "start_y");
        lua_pushnumber(state, segment.end_x);
        lua_setfield(state, -2, "end_x");
        lua_pushnumber(state, segment.end_y);
        lua_setfield(state, -2, "end_y");
        lua_pushinteger(
            state,
            static_cast<lua_Integer>(segment.mask));
        lua_setfield(state, -2, "mask");
        lua_pushboolean(state, segment.path_blocks ? 1 : 0);
        lua_setfield(state, -2, "path_blocks");
        lua_pushboolean(state, segment.openable ? 1 : 0);
        lua_setfield(state, -2, "openable");
        lua_pushboolean(state, segment.destructible ? 1 : 0);
        lua_setfield(state, -2, "destructible");
        lua_pushboolean(
            state,
            segment.destructible_resolved ? 1 : 0);
        lua_setfield(state, -2, "destructible_resolved");
        lua_pushboolean(state, segment.dynamic ? 1 : 0);
        lua_setfield(state, -2, "dynamic");
        lua_rawseti(state, -2, output_index++);
    }
    lua_setfield(state, -2, "segments");

    lua_createtable(
        state,
        static_cast<int>(geometry.polygons.size()),
        0);
    output_index = 1;
    for (const auto& polygon : geometry.polygons) {
        lua_createtable(state, 0, 13);
        lua_pushinteger(
            state,
            static_cast<lua_Integer>(polygon.geometry_id));
        lua_setfield(state, -2, "geometry_id");
        lua_pushinteger(
            state,
            static_cast<lua_Integer>(polygon.native_type_id));
        lua_setfield(state, -2, "native_type_id");
        lua_pushnumber(state, polygon.bounds_x);
        lua_setfield(state, -2, "bounds_x");
        lua_pushnumber(state, polygon.bounds_y);
        lua_setfield(state, -2, "bounds_y");
        lua_pushnumber(state, polygon.bounds_w);
        lua_setfield(state, -2, "bounds_w");
        lua_pushnumber(state, polygon.bounds_h);
        lua_setfield(state, -2, "bounds_h");
        lua_pushboolean(state, polygon.path_blocks ? 1 : 0);
        lua_setfield(state, -2, "path_blocks");
        lua_pushboolean(state, polygon.destructible ? 1 : 0);
        lua_setfield(state, -2, "destructible");
        lua_pushboolean(
            state,
            polygon.destructible_resolved ? 1 : 0);
        lua_setfield(state, -2, "destructible_resolved");
        lua_pushboolean(state, polygon.dynamic ? 1 : 0);
        lua_setfield(state, -2, "dynamic");
        lua_createtable(
            state,
            static_cast<int>(polygon.points.size()),
            0);
        lua_Integer point_index = 1;
        for (const auto& point : polygon.points) {
            lua_createtable(state, 0, 2);
            lua_pushnumber(state, point.x);
            lua_setfield(state, -2, "x");
            lua_pushnumber(state, point.y);
            lua_setfield(state, -2, "y");
            lua_rawseti(state, -2, point_index++);
        }
        lua_setfield(state, -2, "points");
        lua_rawseti(state, -2, output_index++);
    }
    lua_setfield(state, -2, "polygons");

    lua_createtable(
        state,
        static_cast<int>(geometry.participant_radii.size()),
        0);
    output_index = 1;
    for (const auto& participant :
         geometry.participant_radii) {
        lua_createtable(state, 0, 3);
        lua_pushinteger(
            state,
            static_cast<lua_Integer>(participant.participant_id));
        lua_setfield(state, -2, "participant_id");
        lua_pushnumber(state, participant.radius);
        lua_setfield(state, -2, "radius");
        lua_pushboolean(
            state,
            participant.radius_resolved ? 1 : 0);
        lua_setfield(state, -2, "radius_resolved");
        lua_rawseti(state, -2, output_index++);
    }
    lua_setfield(state, -2, "participant_radii");
}

int LuaNavGetCollisionGeometry(lua_State* state) {
    if ((!lua_isinteger(state, 1) &&
         !lua_isnumber(state, 1)) ||
        lua_tointeger(state, 1) <= 0) {
        return luaL_error(
            state,
            "sd.nav.get_collision_geometry expects a positive participant_id");
    }
    const auto participant_id =
        static_cast<std::uint64_t>(lua_tointeger(state, 1));
    SDModCollisionGeometryState geometry;
    std::string error_message;
    if (!TryGetGameplayCollisionGeometryState(
            participant_id,
            &geometry,
            &error_message)) {
        lua_pushnil(state);
        lua_pushlstring(
            state,
            error_message.data(),
            error_message.size());
        return 2;
    }
    PushCollisionGeometry(state, geometry);
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
    lua_createtable(state, 0, 3);
    RegisterFunction(state, &LuaNavGetGrid, "get_grid");
    RegisterFunction(
        state,
        &LuaNavGetCollisionGeometry,
        "get_collision_geometry");
    RegisterFunction(state, &LuaNavTestSegment, "test_segment");
    lua_setfield(state, -2, "nav");
}

}  // namespace sdmod::detail
