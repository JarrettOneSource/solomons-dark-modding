#include "lua_engine_bindings_internal.h"

#include "lua_engine_values.h"
#include "multiplayer_local_transport.h"

#include <cstdint>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace sdmod::detail {
namespace {

LoadedLuaMod* RequireLoadedMod(lua_State* state, const char* api_name) {
    auto* mod = GetLoadedLuaMod(state);
    if (mod == nullptr) {
        luaL_error(state, "%s is unavailable", api_name);
    }
    return mod;
}

void RequireSimulationAuthority(lua_State* state, const char* api_name) {
    if (!multiplayer::IsLuaModSimulationAuthority()) {
        luaL_error(
            state,
            "%s may only be called by the simulation authority",
            api_name);
    }
}

std::string ReadStateKey(lua_State* state, int index, const char* api_name) {
    std::size_t length = 0;
    const char* text = luaL_checklstring(state, index, &length);
    std::string key(text, length);
    if (!IsValidLuaModStateKey(key)) {
        luaL_error(state, "%s key must be nonempty bounded text", api_name);
    }
    return key;
}

int LuaStateGet(lua_State* state) {
    const auto* mod = RequireLoadedMod(state, "sd.state.get");
    const auto key = ReadStateKey(state, 1, "sd.state.get");
    LuaModValue value;
    if (TryGetLuaModStateValue(mod->descriptor.id, key, &value)) {
        PushLuaModValue(state, value);
        return 1;
    }
    if (lua_gettop(state) >= 2) {
        lua_pushvalue(state, 2);
    } else {
        lua_pushnil(state);
    }
    return 1;
}

int LuaStateSet(lua_State* state) {
    RequireSimulationAuthority(state, "sd.state.set");
    const auto* mod = RequireLoadedMod(state, "sd.state.set");
    const auto key = ReadStateKey(state, 1, "sd.state.set");
    luaL_checkany(state, 2);
    LuaModValue value;
    std::string error_message;
    if (!ReadLuaModValue(state, 2, &value, &error_message)) {
        return luaL_error(state, "%s", error_message.c_str());
    }

    std::uint64_t state_revision = 0;
    if (!SetLuaModStateValue(
            mod->descriptor.id,
            key,
            value,
            &state_revision,
            &error_message)) {
        return luaL_error(state, "%s", error_message.c_str());
    }
    std::uint64_t stream_sequence = 0;
    if (!multiplayer::PublishAuthoritativeLuaModStateSet(
            mod->descriptor.id,
            key,
            value,
            state_revision,
            &stream_sequence,
            &error_message)) {
        return luaL_error(state, "%s", error_message.c_str());
    }
    lua_pushinteger(state, static_cast<lua_Integer>(state_revision));
    return 1;
}

int LuaStateDelete(lua_State* state) {
    RequireSimulationAuthority(state, "sd.state.delete");
    const auto* mod = RequireLoadedMod(state, "sd.state.delete");
    const auto key = ReadStateKey(state, 1, "sd.state.delete");
    bool deleted = false;
    std::uint64_t state_revision = 0;
    std::string error_message;
    if (!DeleteLuaModStateValue(
            mod->descriptor.id,
            key,
            &deleted,
            &state_revision,
            &error_message)) {
        return luaL_error(state, "%s", error_message.c_str());
    }
    if (deleted) {
        std::uint64_t stream_sequence = 0;
        if (!multiplayer::PublishAuthoritativeLuaModStateDelete(
                mod->descriptor.id,
                key,
                state_revision,
                &stream_sequence,
                &error_message)) {
            return luaL_error(state, "%s", error_message.c_str());
        }
    }
    lua_pushboolean(state, deleted ? 1 : 0);
    return 1;
}

int LuaStateClear(lua_State* state) {
    RequireSimulationAuthority(state, "sd.state.clear");
    const auto* mod = RequireLoadedMod(state, "sd.state.clear");
    bool cleared = false;
    std::uint64_t state_revision = 0;
    std::string error_message;
    if (!ClearLuaModStateValues(
            mod->descriptor.id,
            &cleared,
            &state_revision,
            &error_message)) {
        return luaL_error(state, "%s", error_message.c_str());
    }
    if (cleared) {
        std::uint64_t stream_sequence = 0;
        if (!multiplayer::PublishAuthoritativeLuaModStateClear(
                mod->descriptor.id,
                state_revision,
                &stream_sequence,
                &error_message)) {
            return luaL_error(state, "%s", error_message.c_str());
        }
    }
    lua_pushboolean(state, cleared ? 1 : 0);
    return 1;
}

int LuaStateSnapshot(lua_State* state) {
    const auto* mod = RequireLoadedMod(state, "sd.state.snapshot");
    const auto snapshot = SnapshotLuaModState();
    const auto own_values = snapshot.find(mod->descriptor.id);
    lua_createtable(
        state,
        0,
        own_values == snapshot.end()
            ? 0
            : static_cast<int>(own_values->second.size()));
    if (own_values != snapshot.end()) {
        for (const auto& [key, value] : own_values->second) {
            lua_pushlstring(state, key.data(), key.size());
            PushLuaModValue(state, value);
            lua_settable(state, -3);
        }
    }
    return 1;
}

int LuaStateGetRevision(lua_State* state) {
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(GetLuaModStateRevision()));
    return 1;
}

int LuaStateIsAuthority(lua_State* state) {
    lua_pushboolean(
        state,
        multiplayer::IsLuaModSimulationAuthority() ? 1 : 0);
    return 1;
}

int LuaEventsBroadcast(lua_State* state) {
    RequireSimulationAuthority(state, "sd.events.broadcast");
    const auto* mod = RequireLoadedMod(state, "sd.events.broadcast");
    std::size_t event_name_length = 0;
    const char* event_name_text =
        luaL_checklstring(state, 1, &event_name_length);
    const std::string event_name(event_name_text, event_name_length);
    if (!IsValidCustomLuaEventName(event_name)) {
        return luaL_error(
            state,
            "sd.events.broadcast requires a non-reserved event identifier");
    }

    LuaModValue payload;
    if (lua_gettop(state) >= 2) {
        std::string conversion_error;
        if (!ReadLuaModValue(
                state,
                2,
                &payload,
                &conversion_error)) {
            return luaL_error(state, "%s", conversion_error.c_str());
        }
    }
    std::vector<std::uint8_t> encoded_payload;
    std::string error_message;
    if (!EncodeLuaModValue(
            payload,
            &encoded_payload,
            &error_message) ||
        encoded_payload.size() > kLuaModMaxEventPayloadBytes) {
        return luaL_error(state, "%s", error_message.c_str());
    }

    std::uint64_t stream_sequence = 0;
    if (!multiplayer::PublishAuthoritativeLuaModEvent(
            mod->descriptor.id,
            event_name,
            payload,
            &stream_sequence,
            &error_message)) {
        return luaL_error(state, "%s", error_message.c_str());
    }
    DispatchLuaCustomEvent(
        mod->descriptor.id,
        event_name,
        payload,
        multiplayer::GetLocalTransportParticipantId(),
        stream_sequence);
    lua_pushinteger(state, static_cast<lua_Integer>(stream_sequence));
    return 1;
}

}  // namespace

bool IsBuiltInLuaEventName(std::string_view event_name) {
    return event_name == kRuntimeTickEventName ||
           event_name == kRunStartedEventName ||
           event_name == kRunEndedEventName ||
           event_name == kWaveStartedEventName ||
           event_name == kWaveCompletedEventName ||
           event_name == kEnemyDeathEventName ||
           event_name == kEnemySpawnedEventName ||
           event_name == kSpellCastEventName ||
           event_name == kGoldChangedEventName ||
           event_name == kDropSpawnedEventName ||
           event_name == kLevelUpEventName;
}

bool IsValidCustomLuaEventName(std::string_view event_name) {
    const std::string owned_name(event_name);
    return !IsBuiltInLuaEventName(event_name) &&
           IsValidLuaModIdentifier(owned_name);
}

void RegisterLuaStateBindings(lua_State* state) {
    lua_createtable(state, 0, 7);
    RegisterFunction(state, &LuaStateGet, "get");
    RegisterFunction(state, &LuaStateSet, "set");
    RegisterFunction(state, &LuaStateDelete, "delete");
    RegisterFunction(state, &LuaStateClear, "clear");
    RegisterFunction(state, &LuaStateSnapshot, "snapshot");
    RegisterFunction(state, &LuaStateGetRevision, "get_revision");
    RegisterFunction(state, &LuaStateIsAuthority, "is_authority");
    lua_setfield(state, -2, "state");
}

void RegisterLuaEventBroadcastBinding(lua_State* state) {
    RegisterFunction(state, &LuaEventsBroadcast, "broadcast");
}

}  // namespace sdmod::detail
