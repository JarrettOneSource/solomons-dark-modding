#include "lua_engine_bindings_internal.h"

#include "multiplayer_runtime_state.h"

#include <algorithm>
#include <cctype>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <string>
#include <string_view>

namespace sdmod::detail {
namespace {

int LuaRuntimeGetMod(lua_State* state) {
    const auto* mod = GetLoadedLuaMod(state);
    if (mod == nullptr) {
        lua_pushnil(state);
        return 1;
    }

    lua_createtable(state, 0, 10);
    lua_pushstring(state, mod->descriptor.id.c_str());
    lua_setfield(state, -2, "id");
    lua_pushstring(state, mod->descriptor.name.c_str());
    lua_setfield(state, -2, "name");
    lua_pushstring(state, mod->descriptor.version.c_str());
    lua_setfield(state, -2, "version");
    lua_pushstring(state, mod->descriptor.api_version.c_str());
    lua_setfield(state, -2, "api_version");
    lua_pushstring(state, mod->descriptor.runtime_kind.c_str());
    lua_setfield(state, -2, "runtime_kind");
    lua_pushstring(state, mod->descriptor.storage_key.c_str());
    lua_setfield(state, -2, "storage_key");
    lua_pushstring(state, mod->descriptor.root_path.string().c_str());
    lua_setfield(state, -2, "root_path");
    lua_pushstring(state, mod->descriptor.entry_script_path.string().c_str());
    lua_setfield(state, -2, "entry_script_path");
    lua_pushstring(state, mod->descriptor.data_root_path.string().c_str());
    lua_setfield(state, -2, "data_root_path");
    lua_pushstring(state, mod->descriptor.temp_root_path.string().c_str());
    lua_setfield(state, -2, "temp_root_path");
    return 1;
}

void PushOwnedProgressionState(
    lua_State* state,
    const multiplayer::ParticipantOwnedProgressionState& progression) {
    lua_createtable(state, 0, 6);
    lua_pushboolean(state, progression.initialized ? 1 : 0);
    lua_setfield(state, -2, "initialized");
    lua_pushinteger(state, static_cast<lua_Integer>(progression.gold));
    lua_setfield(state, -2, "gold");
    lua_pushinteger(state, static_cast<lua_Integer>(progression.inventory_revision));
    lua_setfield(state, -2, "inventory_revision");
    lua_pushinteger(state, static_cast<lua_Integer>(progression.spellbook_revision));
    lua_setfield(state, -2, "spellbook_revision");
    lua_pushinteger(state, static_cast<lua_Integer>(progression.statbook_revision));
    lua_setfield(state, -2, "statbook_revision");
    lua_pushinteger(state, static_cast<lua_Integer>(progression.loadout_revision));
    lua_setfield(state, -2, "loadout_revision");
}

int LuaRuntimeGetMultiplayerState(lua_State* state) {
    const auto runtime = multiplayer::SnapshotRuntimeState();

    lua_createtable(state, 0, 9);
    lua_pushboolean(state, runtime.foundation_ready ? 1 : 0);
    lua_setfield(state, -2, "foundation_ready");
    lua_pushboolean(state, runtime.transport_ready ? 1 : 0);
    lua_setfield(state, -2, "transport_ready");
    lua_pushstring(state, multiplayer::SessionStatusLabel(runtime.session_status));
    lua_setfield(state, -2, "session_status");
    lua_pushstring(state, multiplayer::SessionTransportLabel(runtime.session_transport));
    lua_setfield(state, -2, "session_transport");
    lua_pushinteger(state, static_cast<lua_Integer>(runtime.local_steam_id));
    lua_setfield(state, -2, "local_steam_id");
    lua_pushinteger(state, static_cast<lua_Integer>(runtime.participants.size()));
    lua_setfield(state, -2, "participant_count");

    lua_createtable(state, static_cast<int>(runtime.participants.size()), 0);
    int lua_index = 1;
    for (const auto& participant : runtime.participants) {
        lua_createtable(state, 0, 19);
        lua_pushinteger(state, static_cast<lua_Integer>(participant.participant_id));
        lua_setfield(state, -2, "participant_id");
        lua_pushinteger(state, static_cast<lua_Integer>(participant.steam_id));
        lua_setfield(state, -2, "steam_id");
        lua_pushstring(state, participant.name.c_str());
        lua_setfield(state, -2, "name");
        lua_pushstring(state, multiplayer::ParticipantKindLabel(participant.kind));
        lua_setfield(state, -2, "kind");
        lua_pushstring(state, multiplayer::ParticipantControllerKindLabel(participant.controller_kind));
        lua_setfield(state, -2, "controller_kind");
        lua_pushboolean(state, participant.ready ? 1 : 0);
        lua_setfield(state, -2, "ready");
        lua_pushboolean(state, participant.is_owner ? 1 : 0);
        lua_setfield(state, -2, "is_owner");
        lua_pushboolean(state, participant.transport_connected ? 1 : 0);
        lua_setfield(state, -2, "transport_connected");
        lua_pushboolean(state, participant.transport_using_relay ? 1 : 0);
        lua_setfield(state, -2, "transport_using_relay");
        lua_pushinteger(state, static_cast<lua_Integer>(participant.last_packet_ms));
        lua_setfield(state, -2, "last_packet_ms");
        lua_pushboolean(state, participant.runtime.valid ? 1 : 0);
        lua_setfield(state, -2, "runtime_valid");
        lua_pushboolean(state, participant.runtime.in_run ? 1 : 0);
        lua_setfield(state, -2, "in_run");
        lua_pushinteger(state, static_cast<lua_Integer>(participant.runtime.run_nonce));
        lua_setfield(state, -2, "run_nonce");
        lua_pushstring(state, multiplayer::ParticipantSceneIntentKindLabel(participant.runtime.scene_intent.kind));
        lua_setfield(state, -2, "scene_kind");
        lua_pushnumber(state, static_cast<lua_Number>(participant.runtime.life_current));
        lua_setfield(state, -2, "life_current");
        lua_pushnumber(state, static_cast<lua_Number>(participant.runtime.life_max));
        lua_setfield(state, -2, "life_max");
        lua_pushnumber(state, static_cast<lua_Number>(participant.runtime.mana_current));
        lua_setfield(state, -2, "mana_current");
        lua_pushnumber(state, static_cast<lua_Number>(participant.runtime.mana_max));
        lua_setfield(state, -2, "mana_max");
        PushOwnedProgressionState(state, participant.owned_progression);
        lua_setfield(state, -2, "owned_progression");
        lua_rawseti(state, -2, static_cast<lua_Integer>(lua_index));
        ++lua_index;
    }
    lua_setfield(state, -2, "participants");

    return 1;
}

int LuaRuntimeHasCapability(lua_State* state) {
    const auto* mod = GetLoadedLuaMod(state);
    const auto* capability = luaL_checkstring(state, 1);
    if (mod == nullptr || capability == nullptr) {
        lua_pushboolean(state, 0);
        return 1;
    }

    const auto capability_name = std::string(capability);
    const auto found = std::find(mod->capabilities.begin(), mod->capabilities.end(), capability_name);
    lua_pushboolean(state, found != mod->capabilities.end() ? 1 : 0);
    return 1;
}

int LuaRuntimeGetCapabilities(lua_State* state) {
    const auto* mod = GetLoadedLuaMod(state);
    if (mod == nullptr) {
        lua_newtable(state);
        return 1;
    }

    lua_createtable(state, static_cast<int>(mod->capabilities.size()), 0);
    for (std::size_t index = 0; index < mod->capabilities.size(); ++index) {
        lua_pushstring(state, mod->capabilities[index].c_str());
        lua_rawseti(state, -2, static_cast<lua_Integer>(index + 1));
    }
    return 1;
}

int LuaRuntimeGetEnvironmentVariable(lua_State* state) {
    const auto* variable_name = luaL_checkstring(state, 1);
    if (variable_name == nullptr || *variable_name == '\0') {
        lua_pushnil(state);
        return 1;
    }

    char* value = nullptr;
    std::size_t value_length = 0;
    if (_dupenv_s(&value, &value_length, variable_name) != 0 || value == nullptr) {
        lua_pushnil(state);
        return 1;
    }

    lua_pushstring(state, value);
    free(value);
    return 1;
}

bool IsSafeRelativeModPath(const std::filesystem::path& path) {
    if (path.empty() || path.is_absolute() || path.has_root_name() || path.has_root_directory()) {
        return false;
    }

    for (const auto& component : path) {
        if (component == "..") {
            return false;
        }
    }

    return true;
}

int LuaRuntimeGetModTextFile(lua_State* state) {
    const auto* mod = GetLoadedLuaMod(state);
    const auto* relative_path_text = luaL_checkstring(state, 1);
    if (mod == nullptr || relative_path_text == nullptr || *relative_path_text == '\0') {
        lua_pushnil(state);
        return 1;
    }

    const std::filesystem::path relative_path(relative_path_text);
    if (!IsSafeRelativeModPath(relative_path)) {
        lua_pushnil(state);
        return 1;
    }

    const auto file_path = (mod->descriptor.root_path / relative_path).lexically_normal();
    std::ifstream stream(file_path, std::ios::binary);
    if (!stream) {
        lua_pushnil(state);
        return 1;
    }

    std::string contents((std::istreambuf_iterator<char>(stream)), std::istreambuf_iterator<char>());
    lua_pushlstring(state, contents.data(), contents.size());
    return 1;
}

bool IsSupportedLuaEventName(std::string_view event_name) {
    return event_name == kRuntimeTickEventName || event_name == kRunStartedEventName ||
        event_name == kRunEndedEventName || event_name == kWaveStartedEventName ||
        event_name == kWaveCompletedEventName || event_name == kEnemyDeathEventName ||
        event_name == kEnemySpawnedEventName || event_name == kSpellCastEventName ||
        event_name == kGoldChangedEventName || event_name == kDropSpawnedEventName ||
        event_name == kLevelUpEventName;
}

void MarkLuaEventRegistered(LoadedLuaMod* mod, std::string_view event_name) {
    if (mod == nullptr) {
        return;
    }

    if (event_name == kRuntimeTickEventName) {
        mod->runtime_tick_registered = true;
    } else if (event_name == kRunStartedEventName) {
        mod->run_started_registered = true;
    } else if (event_name == kRunEndedEventName) {
        mod->run_ended_registered = true;
    } else if (event_name == kWaveStartedEventName) {
        mod->wave_started_registered = true;
    } else if (event_name == kWaveCompletedEventName) {
        mod->wave_completed_registered = true;
    } else if (event_name == kEnemyDeathEventName) {
        mod->enemy_death_registered = true;
    } else if (event_name == kEnemySpawnedEventName) {
        mod->enemy_spawned_registered = true;
    } else if (event_name == kSpellCastEventName) {
        mod->spell_cast_registered = true;
    } else if (event_name == kGoldChangedEventName) {
        mod->gold_changed_registered = true;
    } else if (event_name == kDropSpawnedEventName) {
        mod->drop_spawned_registered = true;
    } else if (event_name == kLevelUpEventName) {
        mod->level_up_registered = true;
    }
}

int LuaEventsOn(lua_State* state) {
    auto* mod = GetLoadedLuaMod(state);
    const auto* event_name = luaL_checkstring(state, 1);
    luaL_checktype(state, 2, LUA_TFUNCTION);
    if (mod == nullptr || event_name == nullptr) {
        return luaL_error(state, "sd.events.on is unavailable");
    }

    const std::string_view event_name_view(event_name);
    if (!IsSupportedLuaEventName(event_name_view)) {
        return luaL_error(state, "unsupported event: %s", event_name);
    }

    lua_getfield(state, LUA_REGISTRYINDEX, kLuaEventHandlersRegistryKey);
    if (!lua_istable(state, -1)) {
        lua_pop(state, 1);
        return luaL_error(state, "event registry is unavailable");
    }

    lua_getfield(state, -1, event_name);
    if (!lua_istable(state, -1)) {
        lua_pop(state, 1);
        lua_createtable(state, 0, 0);
        lua_pushvalue(state, -1);
        lua_setfield(state, -3, event_name);
    }

    const auto next_index = lua_rawlen(state, -1) + 1;
    lua_pushvalue(state, 2);
    lua_rawseti(state, -2, static_cast<lua_Integer>(next_index));
    lua_pop(state, 2);

    MarkLuaEventRegistered(mod, event_name_view);
    lua_pushboolean(state, 1);
    return 1;
}

}  // namespace

void RegisterLuaRuntimeBindings(lua_State* state) {
    lua_createtable(state, 0, 6);
    RegisterFunction(state, &LuaRuntimeGetMod, "get_mod");
    RegisterFunction(state, &LuaRuntimeGetMultiplayerState, "get_multiplayer_state");
    RegisterFunction(state, &LuaRuntimeHasCapability, "has_capability");
    RegisterFunction(state, &LuaRuntimeGetCapabilities, "get_capabilities");
    RegisterFunction(state, &LuaRuntimeGetEnvironmentVariable, "get_environment_variable");
    RegisterFunction(state, &LuaRuntimeGetModTextFile, "get_mod_text_file");
    lua_setfield(state, -2, "runtime");
}

void RegisterLuaEventBindings(lua_State* state) {
    lua_createtable(state, 0, 1);
    RegisterFunction(state, &LuaEventsOn, "on");
    lua_setfield(state, -2, "events");
}

}  // namespace sdmod::detail
