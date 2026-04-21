#pragma once

#include "runtime_bootstrap.h"
#include "sdmod_plugin_api.h"

#include <atomic>
#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace sdmod {

namespace lua_exec_diag {

extern std::atomic<std::uint64_t> g_last_endscene_ms;
extern std::atomic<std::uint64_t> g_last_pump_enter_ms;
extern std::atomic<std::uint64_t> g_last_pump_locked_ms;
extern std::atomic<std::uint64_t> g_last_lua_locked_ms;

}  // namespace lua_exec_diag

bool InitializeLuaEngine(const RuntimeBootstrap& bootstrap, std::string* error_message);
void ShutdownLuaEngine();
bool IsLuaEngineInitialized();
std::size_t GetLoadedLuaModCount();
bool HasLuaRuntimeTickHandlers();

// Result of a queued Lua exec request serviced on the gameplay thread.
struct LuaExecResult {
    bool ok = false;
    std::string print_output;
    std::vector<std::string> results;
    std::string error;
};

// Queue a Lua chunk for execution on the gameplay thread and block the
// caller for up to `timeout_ms` waiting for the result. Safe to call from
// any thread (the Lua state itself is never touched off-thread; the
// gameplay-thread pump services the queue under the engine mutex).
//
// On timeout the caller receives an error result but the queued request
// may still execute on a later tick — callers must treat exec as
// advisory when a timeout is returned.
LuaExecResult QueueLuaExecRequestAndWait(const std::string& code, std::uint32_t timeout_ms);

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
// dispatching runtime.tick. Safe to call from the D3D9 EndScene frame
// pump, which fires every frame on the main thread regardless of
// whether gameplay is active (main menu, loading screens, etc.). This
// lets pipe-exec snippets run in contexts where HookPlayerActorTick
// never fires. Runtime.tick dispatch stays gated on gameplay via
// PumpLuaWorkOnGameplayThread.
void PumpLuaExecQueueOnMainThread();

}  // namespace sdmod
