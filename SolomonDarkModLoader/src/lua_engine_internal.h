#pragma once

#include "bot_runtime.h"
#include "lua_content_registry.h"
#include "lua_engine_events.h"
#include "lua_item_runtime.h"
#include "lua_mod_runtime.h"
#include "lua_ui_runtime.h"
#include "runtime_bootstrap.h"
#include "runtime_tick_service.h"

#include <array>
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
inline constexpr char kItemConsumedEventName[] = "item.consumed";

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

struct LuaNetSubscription {
    std::uint64_t id = 0;
    std::string channel;
    int callback_reference = -2;
};

struct LuaItemDefinition {
    LuaContentIdentity identity;
    std::string recipe_name;
    std::string item_type;
    std::uint32_t native_type_id = 0;
    std::string description;
    std::string icon_atlas;
    std::uint32_t icon_frame = 0;
    std::uint32_t duration_ms = 0;
    std::int32_t native_subtype = -1;
    LuaConsumableVfxKind consume_vfx_kind = LuaConsumableVfxKind::None;
    std::array<float, 4> consume_vfx_color = {0.25f, 1.0f, 0.35f, 1.0f};
    int on_consume_reference = -2;
    bool consumable = false;
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

enum class LuaAudioPlaybackKind : std::uint8_t {
    Sample,
    Stream,
};

struct LuaAudioPlayback {
    std::uint64_t id = 0;
    LuaAudioPlaybackKind kind = LuaAudioPlaybackKind::Sample;
    std::string relative_path;
    std::uint32_t sample_handle = 0;
    std::uint32_t channel_handle = 0;
    float volume = 1.0f;
    bool loop = false;
    std::uint64_t created_ms = 0;
};

struct LuaAudioPlaybackSnapshot {
    std::uint64_t id = 0;
    LuaAudioPlaybackKind kind = LuaAudioPlaybackKind::Sample;
    std::string relative_path;
    float volume = 1.0f;
    bool loop = false;
    std::uint64_t created_ms = 0;
    std::string activity;
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

struct LuaEnemyAiRegistration {
    std::uint64_t content_id = 0;
    std::string enemy_key;
    std::uint32_t interval_ms = 100;
    int on_think_reference = -2;
    LuaModValue initial_blackboard;
};

struct LuaEnemyAiInstance {
    std::uint64_t network_actor_id = 0;
    std::uint64_t content_id = 0;
    std::uint32_t spawn_serial = 0;
    uintptr_t actor_address = 0;
    std::uint64_t next_think_ms = 0;
    std::uint64_t think_count = 0;
    LuaModValue blackboard;
};

struct LuaUiActionRegistration {
    std::uint64_t surface_handle = 0;
    std::uint64_t element_handle = 0;
    std::string surface_id;
    std::string action_id;
    LuaUiActionClass action_class = LuaUiActionClass::Presentation;
    int callback_reference = -2;
};

struct LuaSourceFingerprint {
    bool exists = false;
    std::uint64_t size = 0;
    std::uint64_t hash = 0;
};

struct LuaHotReloadState {
    bool initialized = false;
    bool read_error_logged = false;
    LuaSourceFingerprint accepted;
    bool pending = false;
    LuaSourceFingerprint pending_fingerprint;
    std::uint64_t pending_since_ms = 0;
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
    bool item_consumed_registered = false;
    std::uint32_t event_filter_mask = 0;
    bool profile_storage_loaded = false;
    LuaModStateValues profile_storage_values;
    std::vector<LuaTimerEntry> timers;
    std::uint64_t next_timer_id = 1;
    std::vector<LuaBusSubscription> bus_subscriptions;
    std::uint64_t next_bus_subscription_id = 1;
    std::vector<LuaNetSubscription> net_subscriptions;
    std::uint64_t next_net_subscription_id = 1;
    std::vector<LuaSpellDefinition> spell_definitions;
    std::vector<LuaSpellEffectInstance> spell_effects;
    std::uint64_t next_spell_effect_id = 1;
    std::vector<LuaItemDefinition> item_definitions;
    std::vector<LuaEnemyDefinition> enemy_definitions;
    std::vector<LuaEnemyAiRegistration> enemy_ai_registrations;
    std::vector<LuaEnemyAiInstance> enemy_ai_instances;
    std::vector<LuaAudioPlayback> audio_playbacks;
    std::uint64_t next_audio_playback_id = 1;
    std::vector<LuaUiActionRegistration> ui_actions;
    LuaHotReloadState hot_reload;
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

bool CreateLuaStateForMod(
    LoadedLuaMod* mod,
    const std::filesystem::path& entry_script_path,
    std::string* error_message);
void CloseLuaStateForMod(LoadedLuaMod* mod);
void InitializeLuaHotReloadState(LoadedLuaMod* mod);
void ResetLuaHotReloadRuntime();
void PollLuaHotReloadsOnLockedThread(
    bool multiplayer_transport_enabled,
    std::uint64_t now_ms);
void ClearLuaUiBindingsForMod(LoadedLuaMod* mod);
void DispatchPendingLuaUiActions();

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
    const RuntimeTickContext& context);
void ClearLuaTimersForMod(LoadedLuaMod* mod);
void ClearLuaBusSubscriptionsForMod(LoadedLuaMod* mod);
void ClearLuaNetSubscriptionsForMod(LoadedLuaMod* mod);
void StartLuaNetDeliveryQueue();
void StopLuaNetDeliveryQueue();
void DispatchPendingLuaNetMessages();
void ResetLuaEnemySpawnFilterDiagnostics();
void ResetLuaDropRollFilterDiagnostics();
void ResetLuaWaveSpawnFilterDiagnostics();
void ResetLuaSpellCastFilterDiagnostics();
void ResetLuaResourceFilterDiagnostics();
void ResetLuaRegisteredSpellRuntime();
void ResetLuaRegisteredSpellInputSelections();
bool SelectLuaRegisteredSpellForInput(
    const LuaSpellDefinition& definition,
    std::int32_t secondary_slot,
    std::string* error_message);
bool ClearLuaRegisteredSpellInputSelection(
    LuaSpellSlot slot,
    std::int32_t secondary_slot);
void ClearLuaRegisteredSpellInputSelectionsForMod(std::string_view mod_id);
void DispatchPendingLuaRegisteredSpellCasts(
    const RuntimeTickContext& context);
void TickLuaRegisteredSpellEffects(
    const RuntimeTickContext& context);
bool HasLuaEnemyAiRegistrations(const LoadedLuaMod* mod);
void DispatchLuaEnemyAiThink(
    const RuntimeTickContext& context);
void ResetLuaEnemyAiRuntime();
void ClearLuaEnemyAiRuntimeForMod(LoadedLuaMod* mod);
void InitializeLuaAudioRuntime();
void ShutdownLuaAudioRuntime();
bool IsLuaAudioRuntimeAvailable();
void AppendLuaAudioCapabilities(std::vector<std::string>* capabilities);
bool PlayLuaAudio(
    LoadedLuaMod* mod,
    LuaAudioPlaybackKind kind,
    std::string_view relative_path,
    float volume,
    bool loop,
    std::uint64_t* playback_id,
    std::string* error_message);
bool StopLuaAudioPlayback(LoadedLuaMod* mod, std::uint64_t playback_id);
bool SetLuaAudioPlaybackVolume(
    LoadedLuaMod* mod,
    std::uint64_t playback_id,
    float volume,
    bool* found,
    std::string* error_message);
bool TryGetLuaAudioPlaybackSnapshot(
    const LoadedLuaMod* mod,
    std::uint64_t playback_id,
    LuaAudioPlaybackSnapshot* snapshot);
std::vector<LuaAudioPlaybackSnapshot> SnapshotLuaAudioPlaybacks(
    const LoadedLuaMod* mod);
bool HasLuaAudioPlaybacks(const LoadedLuaMod* mod);
void TickLuaAudioRuntime();
std::size_t ClearLuaAudioRuntimeForMod(LoadedLuaMod* mod);
void ResetLuaAudioRuntimeForMod(LoadedLuaMod* mod);
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
