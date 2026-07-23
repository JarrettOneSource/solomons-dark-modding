#include "lua_engine_bindings_internal.h"

#include "lua_camera_runtime.h"

#include <cmath>
#include <string>

namespace sdmod::detail {
namespace {

constexpr float kLuaCameraMaximumCoordinateMagnitude = 1000000.0f;

LoadedLuaMod* RequireCameraMod(lua_State* state, const char* api_name) {
    auto* mod = GetLoadedLuaMod(state);
    if (mod == nullptr) {
        luaL_error(state, "%s is unavailable", api_name);
    }
    return mod;
}

void RequireArgumentCount(
    lua_State* state,
    int expected,
    const char* api_name) {
    if (lua_gettop(state) != expected) {
        luaL_error(
            state,
            "%s expects exactly %d argument%s",
            api_name,
            expected,
            expected == 1 ? "" : "s");
    }
}

float ReadFiniteCoordinate(
    lua_State* state,
    int index,
    const char* api_name,
    const char* argument_name) {
    const auto value = static_cast<float>(luaL_checknumber(state, index));
    if (!std::isfinite(value) ||
        std::abs(value) > kLuaCameraMaximumCoordinateMagnitude) {
        luaL_error(
            state,
            "%s %s must be finite and between -1000000 and 1000000",
            api_name,
            argument_name);
    }
    return value;
}

void SetNumberField(
    lua_State* state,
    const char* field,
    float value) {
    lua_pushnumber(state, static_cast<lua_Number>(value));
    lua_setfield(state, -2, field);
}

int LuaCameraGetState(lua_State* state) {
    constexpr const char* kApiName = "sd.camera.get_state";
    RequireArgumentCount(state, 0, kApiName);
    const auto* mod = RequireCameraMod(state, kApiName);

    LuaCameraSnapshot snapshot;
    if (!TryGetLuaCameraSnapshot(mod->descriptor.id, &snapshot)) {
        return luaL_error(state, "%s could not inspect the native camera", kApiName);
    }

    lua_createtable(state, 0, 15);
    lua_pushboolean(state, snapshot.runtime_available ? 1 : 0);
    lua_setfield(state, -2, "available");
    lua_pushboolean(state, snapshot.scene_available ? 1 : 0);
    lua_setfield(state, -2, "scene_available");
    lua_pushboolean(state, snapshot.focus_active ? 1 : 0);
    lua_setfield(state, -2, "focus_active");
    lua_pushboolean(state, snapshot.caller_owns_focus ? 1 : 0);
    lua_setfield(state, -2, "owns_focus");
    SetNumberField(state, "origin_x", snapshot.origin_x);
    SetNumberField(state, "origin_y", snapshot.origin_y);
    SetNumberField(state, "width", snapshot.width);
    SetNumberField(state, "height", snapshot.height);
    SetNumberField(state, "center_x", snapshot.center_x);
    SetNumberField(state, "center_y", snapshot.center_y);
    SetNumberField(state, "scale", snapshot.scale);
    SetNumberField(state, "shake_magnitude", snapshot.shake_magnitude);
    SetNumberField(state, "shake_accumulator", snapshot.shake_accumulator);
    if (snapshot.focus_active) {
        SetNumberField(state, "focus_x", snapshot.focus_x);
        SetNumberField(state, "focus_y", snapshot.focus_y);
    }
    return 1;
}

int LuaCameraSetFocus(lua_State* state) {
    constexpr const char* kApiName = "sd.camera.set_focus";
    RequireArgumentCount(state, 2, kApiName);
    auto* mod = RequireCameraMod(state, kApiName);
    const float world_x = ReadFiniteCoordinate(
        state, 1, kApiName, "world_x");
    const float world_y = ReadFiniteCoordinate(
        state, 2, kApiName, "world_y");

    std::string error_message;
    if (!SetLuaCameraFocus(
            mod->descriptor.id,
            world_x,
            world_y,
            &error_message)) {
        return luaL_error(state, "%s: %s", kApiName, error_message.c_str());
    }
    lua_pushboolean(state, 1);
    return 1;
}

int LuaCameraClearFocus(lua_State* state) {
    constexpr const char* kApiName = "sd.camera.clear_focus";
    RequireArgumentCount(state, 0, kApiName);
    const auto* mod = RequireCameraMod(state, kApiName);
    lua_pushboolean(
        state,
        ClearLuaCameraFocus(mod->descriptor.id) ? 1 : 0);
    return 1;
}

int LuaCameraShake(lua_State* state) {
    constexpr const char* kApiName = "sd.camera.shake";
    RequireArgumentCount(state, 1, kApiName);
    (void)RequireCameraMod(state, kApiName);
    const auto intensity = static_cast<float>(luaL_checknumber(state, 1));

    std::string error_message;
    if (!ApplyLuaCameraShake(intensity, &error_message)) {
        return luaL_error(state, "%s: %s", kApiName, error_message.c_str());
    }
    lua_pushboolean(state, 1);
    return 1;
}

}  // namespace

void RegisterLuaCameraBindings(lua_State* state) {
    lua_createtable(state, 0, 4);
    RegisterFunction(state, &LuaCameraGetState, "get_state");
    RegisterFunction(state, &LuaCameraSetFocus, "set_focus");
    RegisterFunction(state, &LuaCameraClearFocus, "clear_focus");
    RegisterFunction(state, &LuaCameraShake, "shake");
    lua_setfield(state, -2, "camera");
}

}  // namespace sdmod::detail
