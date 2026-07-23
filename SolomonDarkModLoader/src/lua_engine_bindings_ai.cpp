#include "lua_engine_bindings_internal.h"

#include "lua_engine_values.h"
#include "mod_loader.h"
#include "multiplayer_local_transport.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <string>
#include <string_view>
#include <vector>

namespace sdmod::detail {
namespace {

constexpr std::size_t kLuaMaximumEnemyAiRegistrationsPerMod = 256;
constexpr std::uint32_t kLuaEnemyAiMinimumThinkIntervalMs = 16;
constexpr std::uint32_t kLuaEnemyAiMaximumThinkIntervalMs = 5000;
constexpr std::size_t kLuaEnemyAiMaximumBlackboardBytes = 4096;

LoadedLuaMod* RequireAiMod(lua_State* state, const char* api_name) {
    auto* mod = GetLoadedLuaMod(state);
    if (mod == nullptr) {
        luaL_error(state, "%s is unavailable", api_name);
    }
    return mod;
}

void RequireAiAuthority(lua_State* state, const char* api_name) {
    if (!multiplayer::IsLuaModSimulationAuthority()) {
        luaL_error(
            state,
            "%s may only be called by the simulation authority",
            api_name);
    }
}

bool IsKnownAiRegistrationField(std::string_view field) {
    return field == "enemy" || field == "interval_ms" ||
        field == "blackboard" || field == "on_think";
}

void RejectUnknownAiRegistrationFields(lua_State* state, int table_index) {
    const int absolute_index = lua_absindex(state, table_index);
    lua_pushnil(state);
    while (lua_next(state, absolute_index) != 0) {
        if (lua_type(state, -2) != LUA_TSTRING) {
            lua_pop(state, 2);
            luaL_error(
                state,
                "sd.ai.register accepts only named fields");
        }
        std::size_t length = 0;
        const auto* field = lua_tolstring(state, -2, &length);
        if (!IsKnownAiRegistrationField(
                std::string_view(field, length))) {
            const std::string owned_field(field, length);
            lua_pop(state, 2);
            luaL_error(
                state,
                "sd.ai.register received unknown field '%s'",
                owned_field.c_str());
        }
        lua_pop(state, 1);
    }
}

const LuaEnemyDefinition* FindOwnedEnemyDefinition(
    const LoadedLuaMod& mod,
    std::uint64_t content_id) {
    const auto found = std::find_if(
        mod.enemy_definitions.begin(),
        mod.enemy_definitions.end(),
        [content_id](const LuaEnemyDefinition& definition) {
            return definition.identity.network_id == content_id;
        });
    return found == mod.enemy_definitions.end() ? nullptr : &*found;
}

const LuaEnemyDefinition* FindOwnedEnemyDefinition(
    const LoadedLuaMod& mod,
    std::string_view key) {
    const auto found = std::find_if(
        mod.enemy_definitions.begin(),
        mod.enemy_definitions.end(),
        [key](const LuaEnemyDefinition& definition) {
            return definition.identity.key == key;
        });
    return found == mod.enemy_definitions.end() ? nullptr : &*found;
}

const LuaEnemyDefinition* ReadOwnedEnemyDefinition(
    lua_State* state,
    const LoadedLuaMod& mod,
    int index,
    const char* api_name) {
    if (lua_type(state, index) == LUA_TSTRING) {
        std::size_t length = 0;
        const auto* key = lua_tolstring(state, index, &length);
        const auto* definition = FindOwnedEnemyDefinition(
            mod,
            std::string_view(key, length));
        if (definition != nullptr) {
            return definition;
        }
    } else if (lua_isinteger(state, index)) {
        const auto value = lua_tointeger(state, index);
        if (value > 0) {
            const auto* definition = FindOwnedEnemyDefinition(
                mod,
                static_cast<std::uint64_t>(value));
            if (definition != nullptr) {
                return definition;
            }
        }
    }
    luaL_error(
        state,
        "%s enemy must name an enemy registered by this mod",
        api_name);
    return nullptr;
}

std::uint64_t ReadAiNetworkActorId(
    lua_State* state,
    int index,
    const char* api_name) {
    if (!lua_isinteger(state, index)) {
        luaL_error(
            state,
            "%s network_actor_id must be a positive integer",
            api_name);
    }
    const auto value = lua_tointeger(state, index);
    if (value <= 0) {
        luaL_error(
            state,
            "%s network_actor_id must be a positive integer",
            api_name);
    }
    return static_cast<std::uint64_t>(value);
}

LuaEnemyAiInstance* FindAiInstance(
    LoadedLuaMod* mod,
    std::uint64_t network_actor_id) {
    if (mod == nullptr) {
        return nullptr;
    }
    const auto found = std::find_if(
        mod->enemy_ai_instances.begin(),
        mod->enemy_ai_instances.end(),
        [network_actor_id](const LuaEnemyAiInstance& instance) {
            return instance.network_actor_id == network_actor_id;
        });
    return found == mod->enemy_ai_instances.end() ? nullptr : &*found;
}

LuaEnemyAiInstance* RequireAiInstance(
    lua_State* state,
    LoadedLuaMod* mod,
    std::uint64_t network_actor_id,
    const char* api_name) {
    auto* instance = FindAiInstance(mod, network_actor_id);
    if (instance == nullptr) {
        luaL_error(
            state,
            "%s requires a live enemy controlled by this mod",
            api_name);
    }
    return instance;
}

const LuaEnemyAiRegistration* FindAiRegistration(
    const LoadedLuaMod& mod,
    std::uint64_t content_id) {
    const auto found = std::find_if(
        mod.enemy_ai_registrations.begin(),
        mod.enemy_ai_registrations.end(),
        [content_id](const LuaEnemyAiRegistration& registration) {
            return registration.content_id == content_id;
        });
    return found == mod.enemy_ai_registrations.end() ? nullptr : &*found;
}

const char* AiTargetModeName(SDModLuaEnemyAiTargetMode mode) {
    switch (mode) {
    case SDModLuaEnemyAiTargetMode::Stock:
        return "stock";
    case SDModLuaEnemyAiTargetMode::Clear:
        return "clear";
    case SDModLuaEnemyAiTargetMode::LocalPlayer:
        return "local";
    case SDModLuaEnemyAiTargetMode::Participant:
        return "participant";
    }
    return "stock";
}

void PushAiRegistration(
    lua_State* state,
    const LoadedLuaMod& mod,
    const LuaEnemyAiRegistration& registration) {
    lua_createtable(state, 0, 7);
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(registration.content_id));
    lua_setfield(state, -2, "enemy_id");
    lua_pushlstring(
        state,
        registration.enemy_key.data(),
        registration.enemy_key.size());
    lua_setfield(state, -2, "enemy_key");
    lua_pushlstring(
        state,
        mod.descriptor.id.data(),
        mod.descriptor.id.size());
    lua_setfield(state, -2, "mod_id");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(registration.interval_ms));
    lua_setfield(state, -2, "interval_ms");
    lua_pushboolean(state, 1);
    lua_setfield(state, -2, "has_on_think");
    PushLuaModValue(state, registration.initial_blackboard);
    lua_setfield(state, -2, "blackboard");
}

void PushAiInstance(
    lua_State* state,
    const LoadedLuaMod& mod,
    const LuaEnemyAiInstance& instance) {
    const auto* definition =
        FindOwnedEnemyDefinition(mod, instance.content_id);
    const auto* registration =
        FindAiRegistration(mod, instance.content_id);
    SDModSceneActorState actor;
    const bool live = multiplayer::TryFindLocalRunEnemyByNetworkId(
        instance.network_actor_id,
        &actor);
    SDModLuaEnemyAiCommandState command;
    const bool have_command = TryGetLuaEnemyAiCommandState(
        mod.descriptor.id,
        instance.network_actor_id,
        &command);

    lua_createtable(state, 0, 17);
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(instance.network_actor_id));
    lua_setfield(state, -2, "network_actor_id");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(instance.content_id));
    lua_setfield(state, -2, "content_id");
    if (definition != nullptr) {
        lua_pushlstring(
            state,
            definition->identity.key.data(),
            definition->identity.key.size());
        lua_setfield(state, -2, "key");
        lua_pushlstring(
            state,
            definition->base_name.data(),
            definition->base_name.size());
        lua_setfield(state, -2, "base");
    }
    lua_pushboolean(state, live ? 1 : 0);
    lua_setfield(state, -2, "active");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(instance.think_count));
    lua_setfield(state, -2, "think_count");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(
            registration == nullptr ? 0 : registration->interval_ms));
    lua_setfield(state, -2, "interval_ms");
    PushLuaModValue(state, instance.blackboard);
    lua_setfield(state, -2, "blackboard");

    if (live) {
        lua_pushinteger(state, static_cast<lua_Integer>(actor.enemy_type));
        lua_setfield(state, -2, "enemy_type");
        lua_pushnumber(state, static_cast<lua_Number>(actor.x));
        lua_setfield(state, -2, "x");
        lua_pushnumber(state, static_cast<lua_Number>(actor.y));
        lua_setfield(state, -2, "y");
        lua_pushnumber(state, static_cast<lua_Number>(actor.radius));
        lua_setfield(state, -2, "radius");
        lua_pushnumber(state, static_cast<lua_Number>(actor.hp));
        lua_setfield(state, -2, "hp");
        lua_pushnumber(state, static_cast<lua_Number>(actor.max_hp));
        lua_setfield(state, -2, "max_hp");
        lua_pushboolean(state, actor.dead ? 1 : 0);
        lua_setfield(state, -2, "dead");
    }

    lua_pushstring(
        state,
        AiTargetModeName(
            have_command
                ? command.target_mode
                : SDModLuaEnemyAiTargetMode::Stock));
    lua_setfield(state, -2, "target_mode");
    if (have_command &&
        command.target_mode == SDModLuaEnemyAiTargetMode::Participant) {
        lua_pushinteger(
            state,
            static_cast<lua_Integer>(command.target_participant_id));
        lua_setfield(state, -2, "target_participant_id");
    }
    if (have_command && command.move_goal_active) {
        lua_createtable(state, 0, 3);
        lua_pushnumber(state, command.move_goal_x);
        lua_setfield(state, -2, "x");
        lua_pushnumber(state, command.move_goal_y);
        lua_setfield(state, -2, "y");
        lua_pushnumber(state, command.move_goal_stop_distance);
        lua_setfield(state, -2, "stop_distance");
        lua_setfield(state, -2, "move_goal");
    }
}

int LuaAiRegister(lua_State* state) {
    auto* mod = RequireAiMod(state, "sd.ai.register");
    if (!mod->content_registration_open) {
        return luaL_error(
            state,
            "sd.ai.register may only be called from the mod entry script");
    }
    luaL_checktype(state, 1, LUA_TTABLE);
    RejectUnknownAiRegistrationFields(state, 1);
    if (mod->enemy_ai_registrations.size() >=
        kLuaMaximumEnemyAiRegistrationsPerMod) {
        return luaL_error(
            state,
            "sd.ai.register per-mod registration limit reached");
    }

    lua_getfield(state, 1, "enemy");
    const auto* definition = ReadOwnedEnemyDefinition(
        state,
        *mod,
        -1,
        "sd.ai.register");
    lua_pop(state, 1);
    if (FindAiRegistration(
            *mod,
            definition->identity.network_id) != nullptr) {
        return luaL_error(
            state,
            "sd.ai.register already controls enemy '%s'",
            definition->identity.key.c_str());
    }

    std::uint32_t interval_ms = 100;
    lua_getfield(state, 1, "interval_ms");
    if (!lua_isnil(state, -1)) {
        if (!lua_isinteger(state, -1)) {
            lua_pop(state, 1);
            return luaL_error(
                state,
                "sd.ai.register interval_ms must be an integer");
        }
        const auto value = lua_tointeger(state, -1);
        if (value < kLuaEnemyAiMinimumThinkIntervalMs ||
            value > kLuaEnemyAiMaximumThinkIntervalMs) {
            lua_pop(state, 1);
            return luaL_error(
                state,
                "sd.ai.register interval_ms must be between %u and %u",
                kLuaEnemyAiMinimumThinkIntervalMs,
                kLuaEnemyAiMaximumThinkIntervalMs);
        }
        interval_ms = static_cast<std::uint32_t>(value);
    }
    lua_pop(state, 1);

    LuaModValue initial_blackboard;
    lua_getfield(state, 1, "blackboard");
    if (!lua_isnil(state, -1)) {
        std::string conversion_error;
        if (!ReadLuaModValue(
                state,
                -1,
                &initial_blackboard,
                &conversion_error)) {
            lua_pop(state, 1);
            return luaL_error(state, "%s", conversion_error.c_str());
        }
        std::vector<std::uint8_t> encoded;
        if (!EncodeLuaModValue(
                initial_blackboard,
                &encoded,
                &conversion_error) ||
            encoded.size() > kLuaEnemyAiMaximumBlackboardBytes) {
            lua_pop(state, 1);
            return luaL_error(
                state,
                "sd.ai.register blackboard exceeds %zu bytes",
                kLuaEnemyAiMaximumBlackboardBytes);
        }
    }
    lua_pop(state, 1);

    lua_getfield(state, 1, "on_think");
    if (!lua_isfunction(state, -1)) {
        lua_pop(state, 1);
        return luaL_error(
            state,
            "sd.ai.register on_think must be a function");
    }
    const int on_think_reference = luaL_ref(state, LUA_REGISTRYINDEX);

    LuaEnemyAiRegistration registration;
    registration.content_id = definition->identity.network_id;
    registration.enemy_key = definition->identity.key;
    registration.interval_ms = interval_ms;
    registration.on_think_reference = on_think_reference;
    registration.initial_blackboard = std::move(initial_blackboard);
    mod->enemy_ai_registrations.push_back(std::move(registration));
    PushAiRegistration(state, *mod, mod->enemy_ai_registrations.back());
    return 1;
}

int LuaAiGetState(lua_State* state) {
    auto* mod = RequireAiMod(state, "sd.ai.get_state");
    const auto network_actor_id =
        ReadAiNetworkActorId(state, 1, "sd.ai.get_state");
    const auto* instance = FindAiInstance(mod, network_actor_id);
    if (instance == nullptr) {
        lua_pushnil(state);
        return 1;
    }
    PushAiInstance(state, *mod, *instance);
    return 1;
}

int LuaAiList(lua_State* state) {
    auto* mod = RequireAiMod(state, "sd.ai.list");
    std::vector<const LuaEnemyAiInstance*> instances;
    instances.reserve(mod->enemy_ai_instances.size());
    for (const auto& instance : mod->enemy_ai_instances) {
        instances.push_back(&instance);
    }
    std::sort(
        instances.begin(),
        instances.end(),
        [](const auto* left, const auto* right) {
            return left->network_actor_id < right->network_actor_id;
        });
    lua_createtable(state, static_cast<int>(instances.size()), 0);
    lua_Integer index = 1;
    for (const auto* instance : instances) {
        PushAiInstance(state, *mod, *instance);
        lua_rawseti(state, -2, index++);
    }
    return 1;
}

int LuaAiSetTarget(lua_State* state) {
    RequireAiAuthority(state, "sd.ai.set_target");
    auto* mod = RequireAiMod(state, "sd.ai.set_target");
    const auto network_actor_id =
        ReadAiNetworkActorId(state, 1, "sd.ai.set_target");
    const auto* instance = RequireAiInstance(
        state,
        mod,
        network_actor_id,
        "sd.ai.set_target");

    SDModLuaEnemyAiTargetMode mode = SDModLuaEnemyAiTargetMode::Stock;
    std::uint64_t participant_id = 0;
    if (lua_isnil(state, 2)) {
        mode = SDModLuaEnemyAiTargetMode::Stock;
    } else if (lua_type(state, 2) == LUA_TBOOLEAN &&
               lua_toboolean(state, 2) == 0) {
        mode = SDModLuaEnemyAiTargetMode::Clear;
    } else if (lua_type(state, 2) == LUA_TSTRING) {
        std::size_t length = 0;
        const auto* value = lua_tolstring(state, 2, &length);
        if (std::string_view(value, length) != "local") {
            return luaL_error(
                state,
                "sd.ai.set_target string target must be 'local'");
        }
        mode = SDModLuaEnemyAiTargetMode::LocalPlayer;
    } else if (lua_isinteger(state, 2) && lua_tointeger(state, 2) > 0) {
        mode = SDModLuaEnemyAiTargetMode::Participant;
        participant_id =
            static_cast<std::uint64_t>(lua_tointeger(state, 2));
    } else {
        return luaL_error(
            state,
            "sd.ai.set_target expects nil, false, 'local', or a participant id");
    }

    std::string error_message;
    if (!SetLuaEnemyAiTargetOverride(
            mod->descriptor.id,
            instance->network_actor_id,
            instance->content_id,
            instance->spawn_serial,
            instance->actor_address,
            mode,
            participant_id,
            &error_message)) {
        return luaL_error(state, "%s", error_message.c_str());
    }
    lua_pushboolean(state, 1);
    return 1;
}

int LuaAiSetMoveGoal(lua_State* state) {
    RequireAiAuthority(state, "sd.ai.set_move_goal");
    auto* mod = RequireAiMod(state, "sd.ai.set_move_goal");
    const auto network_actor_id =
        ReadAiNetworkActorId(state, 1, "sd.ai.set_move_goal");
    const auto* instance = RequireAiInstance(
        state,
        mod,
        network_actor_id,
        "sd.ai.set_move_goal");
    if (!lua_isnumber(state, 2) || !lua_isnumber(state, 3)) {
        return luaL_error(
            state,
            "sd.ai.set_move_goal expects (network_actor_id, x, y[, stop_distance])");
    }
    const auto x = static_cast<float>(lua_tonumber(state, 2));
    const auto y = static_cast<float>(lua_tonumber(state, 3));
    float stop_distance = 24.0f;
    if (lua_gettop(state) >= 4 && !lua_isnil(state, 4)) {
        if (!lua_isnumber(state, 4)) {
            return luaL_error(
                state,
                "sd.ai.set_move_goal stop_distance must be a number");
        }
        stop_distance = static_cast<float>(lua_tonumber(state, 4));
    }

    std::string error_message;
    if (!SetLuaEnemyAiMoveGoal(
            mod->descriptor.id,
            instance->network_actor_id,
            instance->content_id,
            instance->spawn_serial,
            instance->actor_address,
            x,
            y,
            stop_distance,
            &error_message)) {
        return luaL_error(state, "%s", error_message.c_str());
    }
    lua_pushboolean(state, 1);
    return 1;
}

int LuaAiStop(lua_State* state) {
    RequireAiAuthority(state, "sd.ai.stop");
    auto* mod = RequireAiMod(state, "sd.ai.stop");
    const auto network_actor_id =
        ReadAiNetworkActorId(state, 1, "sd.ai.stop");
    (void)RequireAiInstance(
        state,
        mod,
        network_actor_id,
        "sd.ai.stop");
    lua_pushboolean(
        state,
        StopLuaEnemyAiMoveGoal(mod->descriptor.id, network_actor_id) ? 1 : 0);
    return 1;
}

int LuaAiClear(lua_State* state) {
    RequireAiAuthority(state, "sd.ai.clear");
    auto* mod = RequireAiMod(state, "sd.ai.clear");
    const auto network_actor_id =
        ReadAiNetworkActorId(state, 1, "sd.ai.clear");
    (void)RequireAiInstance(
        state,
        mod,
        network_actor_id,
        "sd.ai.clear");
    lua_pushboolean(
        state,
        ClearLuaEnemyAiOverrides(mod->descriptor.id, network_actor_id) ? 1 : 0);
    return 1;
}

}  // namespace

void RegisterLuaAiBindings(lua_State* state) {
    lua_createtable(state, 0, 7);
    RegisterFunction(state, &LuaAiRegister, "register");
    RegisterFunction(state, &LuaAiGetState, "get_state");
    RegisterFunction(state, &LuaAiList, "list");
    RegisterFunction(state, &LuaAiSetTarget, "set_target");
    RegisterFunction(state, &LuaAiSetMoveGoal, "set_move_goal");
    RegisterFunction(state, &LuaAiStop, "stop");
    RegisterFunction(state, &LuaAiClear, "clear");
    lua_setfield(state, -2, "ai");
}

}  // namespace sdmod::detail
