#pragma once

#include "runtime_bootstrap.h"
#include "lua_mod_runtime.h"
#include "sdmod_plugin_api.h"

#include <atomic>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <string>
#include <vector>

namespace sdmod {

namespace lua_exec_diag {

extern std::atomic<std::uint64_t> g_last_endscene_ms;
extern std::atomic<std::uint64_t> g_endscene_generation;
extern std::atomic<std::uint64_t> g_last_pump_enter_ms;
extern std::atomic<std::uint64_t> g_last_pump_locked_ms;
extern std::atomic<std::uint64_t> g_last_lua_locked_ms;

}  // namespace lua_exec_diag

bool InitializeLuaEngine(const RuntimeBootstrap& bootstrap, std::string* error_message);
void ShutdownLuaEngine();
bool IsLuaEngineInitialized();
std::size_t GetLoadedLuaModCount();
bool HasLuaRuntimeTickHandlers();
bool TryResolveLuaItemNativeRecipe(
    std::uint64_t content_id,
    std::uint32_t* item_type_id,
    std::uint32_t* recipe_uid,
    std::string* error_message);

struct LuaRegisteredSpellCastRequest {
    std::uint64_t authority_participant_id = 0;
    std::uint64_t owner_participant_id = 0;
    std::uint64_t request_id = 0;
    std::uint64_t content_id = 0;
    std::uint64_t target_network_actor_id = 0;
    float origin_x = 0.0f;
    float origin_y = 0.0f;
    float aim_x = 0.0f;
    float aim_y = 0.0f;
};

struct LuaRegisteredSpellEffectState {
    std::uint64_t owner_participant_id = 0;
    std::uint64_t cast_request_id = 0;
    std::uint64_t content_id = 0;
    std::uint64_t effect_id = 0;
    std::string key;
    float x = 0.0f;
    float y = 0.0f;
    float velocity_x = 0.0f;
    float velocity_y = 0.0f;
    float radius = 0.0f;
    std::uint32_t age_ms = 0;
    std::uint32_t remaining_ms = 0;
    LuaModValue data;
};

inline constexpr std::size_t kLuaRegisteredSpellSecondaryInputSlotCount = 8;

struct LuaRegisteredSpellInputSelection {
    std::uint64_t content_id = 0;
    bool primary = false;
    std::int32_t secondary_slot = -1;
    float mana_cost = 0.0f;
    std::uint32_t cooldown_ms = 0;
    float cast_range = 100.0f;
};

bool QueueLuaRegisteredSpellCastRequest(
    const LuaRegisteredSpellCastRequest& request,
    std::string* error_message);
std::vector<LuaRegisteredSpellEffectState>
SnapshotLocalLuaRegisteredSpellEffects();
bool TryGetSelectedLuaRegisteredPrimarySpell(
    LuaRegisteredSpellInputSelection* selection);
bool TryGetSelectedLuaRegisteredSecondarySpell(
    std::size_t secondary_slot,
    LuaRegisteredSpellInputSelection* selection);
bool TryGetLuaRegisteredSpellInputCooldownRemaining(
    std::uint64_t content_id,
    std::uint64_t now_ms,
    std::uint32_t* remaining_ms);
void CommitLuaRegisteredSpellInputCast(
    std::uint64_t content_id,
    std::uint64_t now_ms);

// Result of a queued Lua exec request serviced on the gameplay thread.
struct LuaExecResult {
    bool ok = false;
    std::string print_output;
    std::vector<std::string> results;
    std::string error;
};

using LuaExecCompletion = std::function<void(LuaExecResult)>;

// Queue a Lua chunk for execution by the same gameplay-safe pump used by the
// external exec pipe. The completion runs on that pump thread after execution,
// or synchronously when admission fails.
bool QueueLuaExecRequestAsync(
    const std::string& code,
    LuaExecCompletion completion);

// Return the mod id targeted by queued exec requests (the first loaded Lua
// mod), or an empty string when no target is available.
std::string GetLuaExecTargetModId();

// Queue a Lua chunk for execution on the gameplay thread and block the
// caller for up to `timeout_ms` waiting for the result. Safe to call from
// any thread (the Lua state itself is never touched off-thread; the
// gameplay-thread pump services the queue under the engine mutex).
//
// On timeout a request that has not begun is canceled. If execution already
// began on the gameplay thread, the caller receives a distinct timeout error
// and must treat the mutation result as unknown.
LuaExecResult QueueLuaExecRequestAndWait(
    const std::string& code,
    std::uint32_t timeout_ms,
    const std::atomic<bool>* service_running = nullptr);

// Drain any pending Lua exec requests and dispatch a runtime.tick event
// to all registered handlers. Takes the engine mutex once for the whole
// batch. Must be called from the gameplay tick thread only: stock
// gameplay code and the world-shared movement scratch at `world + 0x378`
// are not safe to touch from any other thread, and Lua handlers and
// pipe-exec snippets routinely reach into those paths via
// sd.debug.*/sd.world.*, so running this off-thread produces data races
// on the overlap list used by MovementCollision_TestCirclePlacement.
void PumpLuaWorkOnGameplayThread(const SDModRuntimeTickContext& context);

// Drain pending Lua exec requests on the main thread without
// dispatching runtime.tick. During gameplay this is called from the
// local PlayerActorTick safe phase so snippets may access stock world
// state. Front-end contexts use PumpLuaWorkOnMainThread from MyApp's
// update tick instead.
void PumpLuaExecQueueOnMainThread();

// Drain pending Lua exec requests and dispatch runtime.tick from the
// main thread while gameplay is inactive. This is specifically for
// front-end UI automation and menu/runtime mods that are driven by
// runtime.tick before a gameplay scene exists. Do not call this while
// gameplay is active; gameplay-owned runtime.tick remains the contract
// of PumpLuaWorkOnGameplayThread.
void PumpLuaWorkOnMainThread(const SDModRuntimeTickContext& context);

}  // namespace sdmod
