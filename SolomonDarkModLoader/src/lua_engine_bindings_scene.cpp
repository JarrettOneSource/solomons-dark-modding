#include "lua_engine_bindings_internal.h"

#include "mod_loader.h"
#include "multiplayer_local_transport.h"

#include <string>

namespace sdmod::detail {
namespace {

constexpr lua_Integer kHubRegionIndex = 0;
constexpr lua_Integer kArenaRegionIndex = 5;

void RequireSceneAuthority(lua_State* state) {
    if (!multiplayer::IsLuaModSimulationAuthority()) {
        luaL_error(
            state,
            "sd.scene.switch_region may only be called by the simulation authority");
    }
}

int LuaSceneGetState(lua_State* state) {
    SDModSceneState scene;
    if (!TryGetSceneState(&scene) || !scene.valid) {
        lua_pushnil(state);
        return 1;
    }

    const bool transitioning =
        scene.kind == "transition" || scene.name == "transition";
    const bool authority = multiplayer::IsLuaModSimulationAuthority();

    lua_createtable(state, 0, 11);
    lua_pushstring(state, scene.kind.c_str());
    lua_setfield(state, -2, "kind");
    lua_pushstring(state, scene.name.c_str());
    lua_setfield(state, -2, "name");
    lua_pushinteger(state, static_cast<lua_Integer>(scene.current_region_index));
    lua_setfield(state, -2, "region_index");
    lua_pushinteger(state, static_cast<lua_Integer>(scene.region_type_id));
    lua_setfield(state, -2, "region_type_id");
    lua_pushinteger(state, static_cast<lua_Integer>(scene.pending_level_kind));
    lua_setfield(state, -2, "pending_level_kind");
    lua_pushinteger(state, static_cast<lua_Integer>(scene.transition_target_a));
    lua_setfield(state, -2, "transition_target_a");
    lua_pushinteger(state, static_cast<lua_Integer>(scene.transition_target_b));
    lua_setfield(state, -2, "transition_target_b");
    lua_pushboolean(state, transitioning ? 1 : 0);
    lua_setfield(state, -2, "transitioning");
    lua_pushboolean(state, authority ? 1 : 0);
    lua_setfield(state, -2, "is_authority");
    lua_pushboolean(
        state,
        authority && !transitioning && scene.kind != "arena" ? 1 : 0);
    lua_setfield(state, -2, "can_switch_region");
    lua_pushboolean(
        state,
        authority && !transitioning && scene.kind == "hub" ? 1 : 0);
    lua_setfield(state, -2, "can_enter_run");
    return 1;
}

int LuaSceneSwitchRegion(lua_State* state) {
    RequireSceneAuthority(state);
    if (!lua_isinteger(state, 1)) {
        return luaL_error(
            state,
            "sd.scene.switch_region region_index must be an integer from 0 through 5");
    }

    const auto region_index = lua_tointeger(state, 1);
    if (region_index < kHubRegionIndex || region_index > kArenaRegionIndex) {
        return luaL_error(
            state,
            "sd.scene.switch_region region_index must be an integer from 0 through 5");
    }

    SDModSceneState scene;
    if (!TryGetSceneState(&scene) || !scene.valid) {
        return luaL_error(state, "sd.scene.switch_region requires an active gameplay scene");
    }
    if (scene.kind == "transition" || scene.name == "transition") {
        return luaL_error(state, "sd.scene.switch_region cannot run during a scene transition");
    }

    std::string error_message;
    bool queued = false;
    if (region_index == kArenaRegionIndex) {
        if (scene.kind != "hub") {
            return luaL_error(
                state,
                "sd.scene.switch_region can enter region 5 only from the shared hub");
        }
        queued = QueueHubStartTestrun(&error_message);
    } else {
        queued = QueueGameplaySwitchRegion(
            static_cast<int>(region_index),
            &error_message);
    }
    if (!queued) {
        return luaL_error(
            state,
            "sd.scene.switch_region failed: %s",
            error_message.c_str());
    }

    lua_pushboolean(state, 1);
    return 1;
}

}  // namespace

void RegisterLuaSceneBindings(lua_State* state) {
    lua_createtable(state, 0, 2);
    RegisterFunction(state, &LuaSceneGetState, "get_state");
    RegisterFunction(state, &LuaSceneSwitchRegion, "switch_region");
    lua_setfield(state, -2, "scene");
}

}  // namespace sdmod::detail
