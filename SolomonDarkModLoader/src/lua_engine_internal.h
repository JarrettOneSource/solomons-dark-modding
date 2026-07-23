#pragma once

#include "bot_runtime.h"
#include "lua_content_registry.h"
#include "lua_engine_events.h"
#include "lua_mod_runtime.h"
#include "runtime_bootstrap.h"
#include "sdmod_plugin_api.h"

#include <filesystem>
#include <cstdint>
#include <memory>
#include <mutex>
#include <string>
#include <string_view>
#include <unordered_set>
#include <vector>

struct lua_State;

namespace sdmod {
struct LuaRegisteredSpellCastRequest;

namespace detail {

inline constexpr char kLuaLoadedModRegistryKey[] = "sdmod.loaded_mod";
inline constexpr char kLuaEventHandlersRegistryKey[] = "sdmod.event_handlers";
inline constexpr char kLuaEventFiltersRegistryKey[] = "sdmod.event_filters";
inline constexpr char kLuaSdRegistryKey[] = "sdmod.globals.sd";
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

enum class LuaTimerKind {
    Once,
    Repeating,
    Sequence,
};

struct LuaTimerSequenceStep {
    std::uint32_t delay_ms = 0;
    int callback_reference = -2;
};

struct LuaTimerEntry {
    std::uint64_t id = 0;
    std::uint64_t due_ms = 0;
    std::uint32_t interval_ms = 0;
    int callback_reference = -2;
    LuaTimerKind kind = LuaTimerKind::Once;
    std::vector<LuaTimerSequenceStep> sequence_steps;
    std::size_t sequence_index = 0;
};

struct LuaBusSubscription {
    std::uint64_t id = 0;
    std::string topic;
    int callback_reference = -2;
};

struct LuaItemDefinition {
    LuaContentIdentity identity;
    std::string recipe_name;
    std::string item_type;
    std::uint32_t native_type_id = 0;
};

enum class LuaSpellSlot : std::uint8_t {
    Primary = 0,
    Secondary,
};

struct LuaSpellDefinition {
    LuaContentIdentity identity;
    LuaSpellSlot slot = LuaSpellSlot::Primary;
    LuaModValue config;
    int on_cast_reference = -2;
    int on_tick_reference = -2;
    int on_hit_reference = -2;
};

struct LuaSpellEffectInstance {
    std::uint64_t effect_id = 0;
    std::uint64_t cast_request_id = 0;
    std::uint64_t content_id = 0;
    std::uint64_t owner_participant_id = 0;
    std::string key;
    float x = 0.0f;
    float y = 0.0f;
    float velocity_x = 0.0f;
    float velocity_y = 0.0f;
    float radius = 0.0f;
    std::uint64_t created_ms = 0;
    std::uint64_t updated_ms = 0;
    std::uint64_t expires_ms = 0;
    std::uint64_t next_tick_ms = 0;
    std::uint32_t tick_interval_ms = 16;
    LuaModValue data;
    std::unordered_set<uintptr_t> hit_actor_addresses;
};

enum class LuaEnemyLootPolicy : std::uint8_t {
    Stock = 0,
    None,
    Orb,
    Gold,
    Item,
    Powerup,
    Potion,
};

struct LuaEnemyDefinition {
    LuaContentIdentity identity;
    std::string base_name;
    std::uint32_t native_type_id = 0;
    bool hp_valid = false;
    float hp = 0.0f;
    bool speed_valid = false;
    float speed = 0.0f;
    bool scale_valid = false;
    float scale = 1.0f;
    LuaEnemyLootPolicy loot_policy = LuaEnemyLootPolicy::Stock;
};

struct LoadedLuaMod {
    RuntimeModDescriptor descriptor;
    std::vector<std::string> capabilities;
    lua_State* state = nullptr;
    bool content_registration_open = false;
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
    std::uint32_t event_filter_mask = 0;
    bool profile_storage_loaded = false;
    LuaModStateValues profile_storage_values;
    std::vector<LuaTimerEntry> timers;
    std::uint64_t next_timer_id = 1;
    std::vector<LuaBusSubscription> bus_subscriptions;
    std::uint64_t next_bus_subscription_id = 1;
    std::vector<LuaSpellDefinition> spell_definitions;
    std::vector<LuaSpellEffectInstance> spell_effects;
    std::uint64_t next_spell_effect_id = 1;
    std::vector<LuaItemDefinition> item_definitions;
    std::vector<LuaEnemyDefinition> enemy_definitions;
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
void LoadLuaModsForBootstrap(
    const RuntimeBootstrap& bootstrap,
    const std::vector<std::string>& capabilities);
bool RegisterLuaContentIdentityForMod(
    LoadedLuaMod* mod,
    LuaContentKind kind,
    std::string_view content_key,
    LuaContentIdentity* identity,
    std::string* error_message);

bool CreateLuaStateForMod(LoadedLuaMod* mod, std::string* error_message);
void CloseLuaStateForMod(LoadedLuaMod* mod);

bool RegisterLuaBindings(LoadedLuaMod* mod, std::string* error_message);
void PushWaveStartedPayload(lua_State* state, const WaveSummary& summary);

void LogLuaMessage(const LoadedLuaMod& mod, const std::string& message);
LoadedLuaMod* GetLoadedLuaMod(lua_State* state);
const LoadedLuaMod* GetLoadedLuaMod(const lua_State* state);
bool IsBuiltInLuaEventName(std::string_view event_name);
bool IsValidCustomLuaEventName(std::string_view event_name);
void ResetLuaEventFilterRegistrations();
void ClearLuaEventFilterRegistrationsForMod(LoadedLuaMod* mod);
bool HasLuaTimers(const LoadedLuaMod* mod);
void DispatchLuaTimersToMod(
    LoadedLuaMod* mod,
    const SDModRuntimeTickContext& context);
void ClearLuaTimersForMod(LoadedLuaMod* mod);
void ClearLuaBusSubscriptionsForMod(LoadedLuaMod* mod);
void ResetLuaEnemySpawnFilterDiagnostics();
void ResetLuaDropRollFilterDiagnostics();
void ResetLuaWaveSpawnFilterDiagnostics();
void ResetLuaSpellCastFilterDiagnostics();
void ResetLuaResourceFilterDiagnostics();
void ResetLuaRegisteredSpellRuntime();
void DispatchPendingLuaRegisteredSpellCasts(
    const SDModRuntimeTickContext& context);
void TickLuaRegisteredSpellEffects(
    const SDModRuntimeTickContext& context);
bool CreateLuaSpellEffectsFromCallbackResult(
    LoadedLuaMod* mod,
    const LuaSpellDefinition& definition,
    const LuaRegisteredSpellCastRequest& request,
    std::uint64_t now_ms,
    int result_index,
    std::string* error_message);

void StartLuaEventQueue();
void StopLuaEventQueue();
void DispatchPendingLuaEventsToLuaMods();

bool ParseBotCreateRequest(lua_State* state, int index, multiplayer::BotCreateRequest* request, std::string* error_message);
bool ParseBotUpdateRequest(lua_State* state, int index, multiplayer::BotUpdateRequest* request, std::string* error_message);
bool ParseBotCastRequest(lua_State* state, int index, multiplayer::BotCastRequest* request, std::string* error_message);
bool ParseBotIdArgument(lua_State* state, int index, std::uint64_t* bot_id, std::string* error_message);
void PushBotSnapshot(lua_State* state, const multiplayer::BotSnapshot& snapshot);
void PushBotSnapshotArray(lua_State* state);

}  // namespace detail
}  // namespace sdmod
