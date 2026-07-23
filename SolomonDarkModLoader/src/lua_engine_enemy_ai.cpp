#include "lua_engine_internal.h"
#include "logger.h"
#include "lua_engine_values.h"
#include "mod_loader.h"
#include "multiplayer_local_transport.h"
#include "multiplayer_runtime_state.h"
extern "C" {
#include "lauxlib.h"
#include "lua.h"
}
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <string>
#include <string_view>
#include <unordered_set>
#include <utility>
#include <vector>
namespace sdmod::detail {
namespace {

constexpr std::size_t kLuaEnemyAiMaximumInstancesPerMod = 512;
constexpr std::size_t kLuaEnemyAiMaximumCallbacksPerPump = 64;
constexpr std::size_t kLuaEnemyAiMaximumBlackboardBytes = 4096;
constexpr float kLuaEnemyAiDefaultStopDistance = 24.0f;
struct EnemyAiDecision {
    bool target_changed = false;
    SDModLuaEnemyAiTargetMode target_mode =
        SDModLuaEnemyAiTargetMode::Stock;
    std::uint64_t target_participant_id = 0;
    bool move_goal_changed = false;
    bool move_goal_active = false;
    float move_goal_x = 0.0f;
    float move_goal_y = 0.0f;
    float move_goal_stop_distance = kLuaEnemyAiDefaultStopDistance;
    bool blackboard_changed = false;
    LuaModValue blackboard;
};
const LuaEnemyAiRegistration* FindEnemyAiRegistration(
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
const LuaEnemyDefinition* FindEnemyDefinition(
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
LuaEnemyAiInstance* FindEnemyAiInstance(
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
void PushVec2(lua_State* state, float x, float y) {
    lua_createtable(state, 0, 2);
    lua_pushnumber(state, x);
    lua_setfield(state, -2, "x");
    lua_pushnumber(state, y);
    lua_setfield(state, -2, "y");
}
void PushRuntimeParticipant(
    lua_State* state,
    const multiplayer::ParticipantInfo& participant,
    bool local) {
    lua_createtable(state, 0, 12);
    if (local) {
        lua_pushstring(state, "local");
    } else {
        lua_pushinteger(
            state,
            static_cast<lua_Integer>(participant.participant_id));
    }
    lua_setfield(state, -2, "ref");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(participant.participant_id));
    lua_setfield(state, -2, "participant_id");
    lua_pushboolean(state, local ? 1 : 0);
    lua_setfield(state, -2, "local_player");
    lua_pushlstring(state, participant.name.data(), participant.name.size());
    lua_setfield(state, -2, "name");
    lua_pushstring(
        state,
        participant.controller_kind ==
                multiplayer::ParticipantControllerKind::LuaBrain
            ? "lua"
            : "native");
    lua_setfield(state, -2, "controller");
    lua_pushboolean(state, participant.runtime.in_run ? 1 : 0);
    lua_setfield(state, -2, "in_run");
    lua_pushboolean(
        state,
        participant.runtime.valid &&
                participant.runtime.life_current > 0.0f
            ? 1
            : 0);
    lua_setfield(state, -2, "alive");
    lua_pushnumber(state, participant.runtime.position_x);
    lua_setfield(state, -2, "x");
    lua_pushnumber(state, participant.runtime.position_y);
    lua_setfield(state, -2, "y");
    lua_pushnumber(state, participant.runtime.life_current);
    lua_setfield(state, -2, "hp");
    lua_pushnumber(state, participant.runtime.life_max);
    lua_setfield(state, -2, "max_hp");
}
void PushLocalPlayerParticipant(lua_State* state) {
    SDModPlayerState player;
    if (!TryGetPlayerState(&player) || !player.valid) {
        lua_pushnil(state);
        return;
    }
    lua_createtable(state, 0, 11);
    lua_pushstring(state, "local");
    lua_setfield(state, -2, "ref");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(
            multiplayer::GetLocalTransportParticipantId()));
    lua_setfield(state, -2, "participant_id");
    lua_pushboolean(state, 1);
    lua_setfield(state, -2, "local_player");
    lua_pushstring(state, "Local Player");
    lua_setfield(state, -2, "name");
    lua_pushstring(state, "native");
    lua_setfield(state, -2, "controller");
    lua_pushboolean(state, IsRunLifecycleActive() ? 1 : 0);
    lua_setfield(state, -2, "in_run");
    lua_pushboolean(state, player.hp > 0.0f ? 1 : 0);
    lua_setfield(state, -2, "alive");
    lua_pushnumber(state, player.x);
    lua_setfield(state, -2, "x");
    lua_pushnumber(state, player.y);
    lua_setfield(state, -2, "y");
    lua_pushnumber(state, player.hp);
    lua_setfield(state, -2, "hp");
    lua_pushnumber(state, player.max_hp);
    lua_setfield(state, -2, "max_hp");
}
void PushEnemyAiParticipants(lua_State* state) {
    const auto runtime = multiplayer::SnapshotRuntimeState();
    std::vector<const multiplayer::ParticipantInfo*> participants;
    participants.reserve(runtime.participants.size());
    for (const auto& participant : runtime.participants) {
        if (participant.participant_id != 0 && participant.runtime.valid) {
            participants.push_back(&participant);
        }
    }
    std::sort(
        participants.begin(),
        participants.end(),
        [](const auto* left, const auto* right) {
            return left->participant_id < right->participant_id;
        });

    const auto local_id = multiplayer::GetLocalTransportParticipantId();
    const auto local = std::find_if(
        participants.begin(),
        participants.end(),
        [&](const auto* participant) {
            return participant->participant_id == local_id &&
                participant->kind == multiplayer::ParticipantKind::LocalHuman;
        });
    lua_createtable(
        state,
        static_cast<int>(participants.size() + (local == participants.end())),
        0);
    lua_Integer output_index = 1;
    if (local == participants.end()) {
        PushLocalPlayerParticipant(state);
        if (!lua_isnil(state, -1)) {
            lua_rawseti(state, -2, output_index++);
        } else {
            lua_pop(state, 1);
        }
    }
    for (const auto* participant : participants) {
        PushRuntimeParticipant(
            state,
            *participant,
            participant == (local == participants.end() ? nullptr : *local));
        lua_rawseti(state, -2, output_index++);
    }
}
void PushEnemyAiThinkContext(
    lua_State* state,
    const LoadedLuaMod& mod,
    const LuaEnemyAiRegistration& registration,
    const LuaEnemyAiInstance& instance,
    const SDModSceneActorState& actor,
    const SDModRuntimeTickContext& tick) {
    const auto* definition = FindEnemyDefinition(mod, instance.content_id);
    SDModLuaEnemyAiCommandState command;
    const bool have_command = TryGetLuaEnemyAiCommandState(
        mod.descriptor.id,
        instance.network_actor_id,
        &command);

    lua_createtable(state, 0, 19);
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(instance.network_actor_id));
    lua_setfield(state, -2, "network_actor_id");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(instance.content_id));
    lua_setfield(state, -2, "content_id");
    lua_pushlstring(
        state,
        registration.enemy_key.data(),
        registration.enemy_key.size());
    lua_setfield(state, -2, "key");
    if (definition != nullptr) {
        lua_pushlstring(
            state,
            definition->base_name.data(),
            definition->base_name.size());
        lua_setfield(state, -2, "base");
    }
    lua_pushinteger(state, actor.enemy_type);
    lua_setfield(state, -2, "enemy_type");
    lua_pushnumber(state, actor.x);
    lua_setfield(state, -2, "x");
    lua_pushnumber(state, actor.y);
    lua_setfield(state, -2, "y");
    PushVec2(state, actor.x, actor.y);
    lua_setfield(state, -2, "position");
    lua_pushnumber(state, actor.radius);
    lua_setfield(state, -2, "radius");
    lua_pushnumber(state, actor.hp);
    lua_setfield(state, -2, "hp");
    lua_pushnumber(state, actor.max_hp);
    lua_setfield(state, -2, "max_hp");
    lua_pushboolean(state, actor.dead ? 1 : 0);
    lua_setfield(state, -2, "dead");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(instance.think_count));
    lua_setfield(state, -2, "think_count");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(tick.monotonic_milliseconds));
    lua_setfield(state, -2, "monotonic_milliseconds");
    PushLuaModValue(state, instance.blackboard);
    lua_setfield(state, -2, "blackboard");
    lua_pushstring(
        state,
        !have_command
            ? "stock"
            : command.target_mode == SDModLuaEnemyAiTargetMode::Clear
                ? "clear"
                : command.target_mode ==
                          SDModLuaEnemyAiTargetMode::LocalPlayer
                    ? "local"
                    : command.target_mode ==
                              SDModLuaEnemyAiTargetMode::Participant
                        ? "participant"
                        : "stock");
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
    PushEnemyAiParticipants(state);
    lua_setfield(state, -2, "participants");
}
bool RejectUnknownDecisionFields(
    lua_State* state,
    int table_index,
    std::string* error_message) {
    const int absolute_index = lua_absindex(state, table_index);
    lua_pushnil(state);
    while (lua_next(state, absolute_index) != 0) {
        if (lua_type(state, -2) != LUA_TSTRING) {
            lua_pop(state, 2);
            *error_message = "on_think result accepts only named fields";
            return false;
        }
        std::size_t length = 0;
        const auto* field = lua_tolstring(state, -2, &length);
        const std::string_view name(field, length);
        if (name != "target" && name != "move_goal" &&
            name != "blackboard") {
            *error_message = "on_think result has unknown field '" +
                std::string(name) + "'";
            lua_pop(state, 2);
            return false;
        }
        lua_pop(state, 1);
    }
    return true;
}
bool ReadEnemyAiDecision(
    lua_State* state,
    int result_index,
    EnemyAiDecision* decision,
    std::string* error_message) {
    if (lua_isnil(state, result_index)) {
        return true;
    }
    if (!lua_istable(state, result_index) || decision == nullptr ||
        error_message == nullptr) {
        if (error_message != nullptr) {
            *error_message = "on_think must return nil or a decision table";
        }
        return false;
    }
    const int result = lua_absindex(state, result_index);
    if (!RejectUnknownDecisionFields(state, result, error_message)) {
        return false;
    }

    lua_getfield(state, result, "target");
    if (!lua_isnil(state, -1)) {
        decision->target_changed = true;
        if (lua_type(state, -1) == LUA_TBOOLEAN &&
            lua_toboolean(state, -1) == 0) {
            decision->target_mode = SDModLuaEnemyAiTargetMode::Clear;
        } else if (lua_type(state, -1) == LUA_TSTRING) {
            std::size_t length = 0;
            const auto* text = lua_tolstring(state, -1, &length);
            const std::string_view value(text, length);
            if (value == "local") {
                decision->target_mode =
                    SDModLuaEnemyAiTargetMode::LocalPlayer;
            } else if (value == "stock") {
                decision->target_mode = SDModLuaEnemyAiTargetMode::Stock;
            } else {
                *error_message = "on_think target must be false, 'local', 'stock', or a participant id";
                lua_pop(state, 1);
                return false;
            }
        } else if (lua_isinteger(state, -1) &&
                   lua_tointeger(state, -1) > 0) {
            decision->target_mode =
                SDModLuaEnemyAiTargetMode::Participant;
            decision->target_participant_id =
                static_cast<std::uint64_t>(lua_tointeger(state, -1));
        } else {
            *error_message = "on_think target must be false, 'local', 'stock', or a participant id";
            lua_pop(state, 1);
            return false;
        }
    }
    lua_pop(state, 1);

    lua_getfield(state, result, "move_goal");
    if (!lua_isnil(state, -1)) {
        decision->move_goal_changed = true;
        if (lua_type(state, -1) == LUA_TBOOLEAN &&
            lua_toboolean(state, -1) == 0) {
            decision->move_goal_active = false;
        } else if (lua_istable(state, -1)) {
            decision->move_goal_active = true;
            lua_getfield(state, -1, "x");
            lua_getfield(state, -2, "y");
            if (!lua_isnumber(state, -2) || !lua_isnumber(state, -1)) {
                lua_pop(state, 3);
                *error_message = "on_think move_goal requires numeric x and y";
                return false;
            }
            decision->move_goal_x =
                static_cast<float>(lua_tonumber(state, -2));
            decision->move_goal_y =
                static_cast<float>(lua_tonumber(state, -1));
            lua_pop(state, 2);
            lua_getfield(state, -1, "stop_distance");
            if (!lua_isnil(state, -1)) {
                if (!lua_isnumber(state, -1)) {
                    lua_pop(state, 2);
                    *error_message = "on_think move_goal stop_distance must be numeric";
                    return false;
                }
                decision->move_goal_stop_distance =
                    static_cast<float>(lua_tonumber(state, -1));
            }
            lua_pop(state, 1);
        } else {
            lua_pop(state, 1);
            *error_message = "on_think move_goal must be false or a table";
            return false;
        }
    }
    lua_pop(state, 1);

    lua_getfield(state, result, "blackboard");
    if (!lua_isnil(state, -1)) {
        std::string conversion_error;
        std::vector<std::uint8_t> encoded;
        if (!ReadLuaModValue(
                state,
                -1,
                &decision->blackboard,
                &conversion_error) ||
            !EncodeLuaModValue(
                decision->blackboard,
                &encoded,
                &conversion_error) ||
            encoded.size() > kLuaEnemyAiMaximumBlackboardBytes) {
            lua_pop(state, 1);
            *error_message = "on_think blackboard exceeds the bounded Lua value contract";
            return false;
        }
        decision->blackboard_changed = true;
    }
    lua_pop(state, 1);
    return true;
}

bool ApplyEnemyAiDecision(
    LoadedLuaMod* mod,
    LuaEnemyAiInstance* instance,
    const EnemyAiDecision& decision,
    std::string* error_message) {
    if (decision.move_goal_changed && decision.move_goal_active &&
        (!std::isfinite(decision.move_goal_x) ||
         !std::isfinite(decision.move_goal_y) ||
         !std::isfinite(decision.move_goal_stop_distance) ||
         std::abs(decision.move_goal_x) > 20000.0f ||
         std::abs(decision.move_goal_y) > 20000.0f ||
         decision.move_goal_stop_distance < 0.0f ||
         decision.move_goal_stop_distance > 4096.0f)) {
        *error_message = "on_think move_goal is outside the supported world range";
        return false;
    }
    if (decision.target_changed &&
        !SetLuaEnemyAiTargetOverride(
            mod->descriptor.id,
            instance->network_actor_id,
            instance->content_id,
            instance->spawn_serial,
            instance->actor_address,
            decision.target_mode,
            decision.target_participant_id,
            error_message)) {
        return false;
    }
    if (decision.move_goal_changed) {
        if (decision.move_goal_active) {
            if (!SetLuaEnemyAiMoveGoal(
                    mod->descriptor.id,
                    instance->network_actor_id,
                    instance->content_id,
                    instance->spawn_serial,
                    instance->actor_address,
                    decision.move_goal_x,
                    decision.move_goal_y,
                    decision.move_goal_stop_distance,
                    error_message)) {
                return false;
            }
        } else {
            (void)StopLuaEnemyAiMoveGoal(
                mod->descriptor.id,
                instance->network_actor_id);
        }
    }
    if (decision.blackboard_changed) {
        instance->blackboard = decision.blackboard;
    }
    return true;
}

void ReconcileEnemyAiInstances(
    LoadedLuaMod* mod,
    const std::vector<SDModTrackedEnemyState>& tracked,
    std::uint64_t now_ms) {
    std::unordered_set<std::uint64_t> live_ids;
    for (const auto& tracked_enemy : tracked) {
        SDModLuaEnemySpawnConfig config;
        std::uint32_t spawn_serial = 0;
        if (!TryGetRunLifecycleLuaEnemySpawnConfig(
                tracked_enemy.actor_address,
                &config) ||
            FindEnemyAiRegistration(*mod, config.content_id) == nullptr ||
            !TryGetRunLifecycleEnemySpawnSerial(
                tracked_enemy.actor_address,
                &spawn_serial)) {
            continue;
        }
        const auto network_actor_id =
            multiplayer::GetLocalRunEnemyNetworkActorId(
                tracked_enemy.actor_address);
        SDModSceneActorState actor;
        if (network_actor_id == 0 ||
            !multiplayer::TryFindLocalRunEnemyByNetworkId(
                network_actor_id,
                &actor) ||
            actor.dead) {
            continue;
        }
        live_ids.insert(network_actor_id);
        auto* instance = FindEnemyAiInstance(mod, network_actor_id);
        if (instance == nullptr) {
            if (mod->enemy_ai_instances.size() >=
                kLuaEnemyAiMaximumInstancesPerMod) {
                continue;
            }
            const auto* registration =
                FindEnemyAiRegistration(*mod, config.content_id);
            LuaEnemyAiInstance created;
            created.network_actor_id = network_actor_id;
            created.content_id = config.content_id;
            created.spawn_serial = spawn_serial;
            created.actor_address = tracked_enemy.actor_address;
            created.next_think_ms = now_ms;
            created.blackboard = registration->initial_blackboard;
            mod->enemy_ai_instances.push_back(std::move(created));
        } else {
            instance->spawn_serial = spawn_serial;
            instance->actor_address = tracked_enemy.actor_address;
        }
    }

    for (auto it = mod->enemy_ai_instances.begin();
         it != mod->enemy_ai_instances.end();) {
        if (live_ids.find(it->network_actor_id) == live_ids.end()) {
            (void)ClearLuaEnemyAiOverrides(
                mod->descriptor.id,
                it->network_actor_id);
            it = mod->enemy_ai_instances.erase(it);
        } else {
            ++it;
        }
    }
    std::sort(
        mod->enemy_ai_instances.begin(),
        mod->enemy_ai_instances.end(),
        [](const auto& left, const auto& right) {
            return left.network_actor_id < right.network_actor_id;
        });
}

void DispatchEnemyAiInstance(
    LoadedLuaMod* mod,
    LuaEnemyAiInstance* instance,
    const SDModRuntimeTickContext& context) {
    const auto* registration =
        FindEnemyAiRegistration(*mod, instance->content_id);
    SDModSceneActorState actor;
    if (registration == nullptr || mod->state == nullptr ||
        registration->on_think_reference == LUA_NOREF ||
        registration->on_think_reference == LUA_REFNIL ||
        !multiplayer::TryFindLocalRunEnemyByNetworkId(
            instance->network_actor_id,
            &actor) ||
        actor.dead) {
        return;
    }

    instance->next_think_ms = context.monotonic_milliseconds +
        registration->interval_ms;
    lua_rawgeti(
        mod->state,
        LUA_REGISTRYINDEX,
        registration->on_think_reference);
    if (!lua_isfunction(mod->state, -1)) {
        lua_pop(mod->state, 1);
        return;
    }
    PushEnemyAiThinkContext(
        mod->state,
        *mod,
        *registration,
        *instance,
        actor,
        context);
    instance->think_count += 1;
    if (lua_pcall(mod->state, 1, 1, 0) != LUA_OK) {
        const auto* message = lua_tostring(mod->state, -1);
        LogLuaMessage(
            *mod,
            "sd.ai on_think failed: " +
                std::string(message == nullptr ? "unknown" : message));
        lua_pop(mod->state, 1);
        return;
    }

    EnemyAiDecision decision;
    std::string error_message;
    if (!ReadEnemyAiDecision(
            mod->state,
            -1,
            &decision,
            &error_message) ||
        !ApplyEnemyAiDecision(
            mod,
            instance,
            decision,
            &error_message)) {
        LogLuaMessage(*mod, "sd.ai on_think decision rejected: " + error_message);
    }
    lua_pop(mod->state, 1);
}

bool AnyEnemyAiInstances() {
    return std::any_of(
        LoadedLuaModsStorage().begin(),
        LoadedLuaModsStorage().end(),
        [](const auto& mod) {
            return mod != nullptr && !mod->enemy_ai_instances.empty();
        });
}

}  // namespace

bool HasLuaEnemyAiRegistrations(const LoadedLuaMod* mod) {
    return mod != nullptr && !mod->enemy_ai_registrations.empty();
}

void DispatchLuaEnemyAiThink(const SDModRuntimeTickContext& context) {
    if (!multiplayer::IsLuaModSimulationAuthority() ||
        !IsRunLifecycleActive()) {
        if (AnyEnemyAiInstances()) {
            ResetLuaEnemyAiRuntime();
        }
        return;
    }

    std::vector<SDModTrackedEnemyState> tracked;
    GetRunLifecycleTrackedEnemies(&tracked);
    for (const auto& mod : LoadedLuaModsStorage()) {
        if (HasLuaEnemyAiRegistrations(mod.get())) {
            ReconcileEnemyAiInstances(
                mod.get(),
                tracked,
                context.monotonic_milliseconds);
        }
    }

    std::size_t callbacks = 0;
    for (const auto& mod : LoadedLuaModsStorage()) {
        if (mod == nullptr) {
            continue;
        }
        for (auto& instance : mod->enemy_ai_instances) {
            if (callbacks >= kLuaEnemyAiMaximumCallbacksPerPump) {
                return;
            }
            if (instance.next_think_ms <= context.monotonic_milliseconds) {
                DispatchEnemyAiInstance(mod.get(), &instance, context);
                callbacks += 1;
            }
        }
    }
}

void ClearLuaEnemyAiRuntimeForMod(LoadedLuaMod* mod) {
    if (mod == nullptr) {
        return;
    }
    ClearLuaEnemyAiOverridesForMod(mod->descriptor.id);
    mod->enemy_ai_instances.clear();
}

void ResetLuaEnemyAiRuntime() {
    for (const auto& mod : LoadedLuaModsStorage()) {
        if (mod != nullptr) {
            mod->enemy_ai_instances.clear();
        }
    }
    ResetLuaEnemyAiOverrides();
}

}  // namespace sdmod::detail
