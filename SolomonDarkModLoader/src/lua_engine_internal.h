#pragma once

#include "bot_runtime.h"
#include "lua_engine_events.h"
#include "runtime_bootstrap.h"
#include "sdmod_plugin_api.h"

#include <filesystem>
#include <memory>
#include <mutex>
#include <string>
#include <vector>

struct lua_State;

namespace sdmod {
namespace detail {

inline constexpr char kLuaLoadedModRegistryKey[] = "sdmod.loaded_mod";
inline constexpr char kLuaEventHandlersRegistryKey[] = "sdmod.event_handlers";
inline constexpr char kRuntimeTickEventName[] = "runtime.tick";
inline constexpr char kRunStartedEventName[] = "run.started";
inline constexpr char kRunEndedEventName[] = "run.ended";
inline constexpr char kWaveStartedEventName[] = "wave.started";
inline constexpr char kWaveCompletedEventName[] = "wave.completed";
inline constexpr char kEnemyDeathEventName[] = "enemy.death";
inline constexpr char kEnemySpawnedEventName[] = "enemy.spawned";
inline constexpr char kSpellCastEventName[] = "spell.cast";
inline constexpr char kGoldChangedEventName[] = "gold.changed";
inline constexpr char kDropSpawnedEventName[] = "drop.spawned";
inline constexpr char kLevelUpEventName[] = "level.up";

struct LoadedLuaMod {
    RuntimeModDescriptor descriptor;
    std::vector<std::string> capabilities;
    lua_State* state = nullptr;
    bool runtime_tick_registered = false;
    bool run_started_registered = false;
    bool run_ended_registered = false;
    bool wave_started_registered = false;
    bool wave_completed_registered = false;
    bool enemy_death_registered = false;
    bool enemy_spawned_registered = false;
    bool spell_cast_registered = false;
    bool gold_changed_registered = false;
    bool drop_spawned_registered = false;
    bool level_up_registered = false;
};

std::mutex& LuaEngineMutex();
bool& LuaEngineInitializedFlag();
std::filesystem::path& LuaRuntimeDirectoryStorage();
RuntimeBootstrap& LuaRuntimeBootstrapStorage();
std::vector<std::unique_ptr<LoadedLuaMod>>& LoadedLuaModsStorage();

std::vector<std::string> BuildLuaCapabilitySet();
bool SupportsLuaModRequiredCapabilities(
    const RuntimeModDescriptor& mod,
    const std::vector<std::string>& capabilities,
    std::string* missing_capability);

bool CreateLuaStateForMod(LoadedLuaMod* mod, std::string* error_message);
void CloseLuaStateForMod(LoadedLuaMod* mod);

bool RegisterLuaBindings(LoadedLuaMod* mod, std::string* error_message);

void LogLuaMessage(const LoadedLuaMod& mod, const std::string& message);
LoadedLuaMod* GetLoadedLuaMod(lua_State* state);
const LoadedLuaMod* GetLoadedLuaMod(const lua_State* state);

bool ParseBotCreateRequest(lua_State* state, int index, multiplayer::BotCreateRequest* request, std::string* error_message);
bool ParseBotUpdateRequest(lua_State* state, int index, multiplayer::BotUpdateRequest* request, std::string* error_message);
bool ParseBotCastRequest(lua_State* state, int index, multiplayer::BotCastRequest* request, std::string* error_message);
bool ParseBotIdArgument(lua_State* state, int index, std::uint64_t* bot_id, std::string* error_message);
void PushBotSnapshot(lua_State* state, const multiplayer::BotSnapshot& snapshot);
void PushBotSnapshotArray(lua_State* state);

}  // namespace detail
}  // namespace sdmod
