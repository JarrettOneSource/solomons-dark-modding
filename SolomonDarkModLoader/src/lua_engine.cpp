#include "lua_engine.h"

#include "bot_runtime.h"
#include "logger.h"
#include "lua_engine_bindings_internal.h"
#include "lua_engine_internal.h"
#include "mod_loader.h"
#include "multiplayer_foundation.h"

extern "C" {
#include "lauxlib.h"
#include "lua.h"
#include "lualib.h"
}

#include <algorithm>
#include <chrono>
#include <deque>
#include <filesystem>
#include <future>
#include <memory>
#include <mutex>
#include <string>
#include <utility>
#include <vector>

#include <Windows.h>

namespace sdmod {

namespace lua_exec_diag {

std::atomic<std::uint64_t> g_last_endscene_ms{0};
std::atomic<std::uint64_t> g_last_pump_enter_ms{0};
std::atomic<std::uint64_t> g_last_pump_locked_ms{0};
std::atomic<std::uint64_t> g_last_lua_locked_ms{0};

}  // namespace lua_exec_diag

namespace detail {
namespace {

struct PendingLuaExecRequest {
    std::string code;
    std::promise<LuaExecResult> promise;
};

std::mutex& LuaExecQueueMutex() {
    static std::mutex mutex;
    return mutex;
}

std::deque<PendingLuaExecRequest>& LuaExecQueueStorage() {
    static std::deque<PendingLuaExecRequest> storage;
    return storage;
}

std::future<LuaExecResult> EnqueueLuaExecRequest(std::string code) {
    std::promise<LuaExecResult> promise;
    auto future = promise.get_future();
    {
        std::lock_guard<std::mutex> lock(LuaExecQueueMutex());
        PendingLuaExecRequest request;
        request.code = std::move(code);
        request.promise = std::move(promise);
        LuaExecQueueStorage().emplace_back(std::move(request));
    }
    return future;
}

std::deque<PendingLuaExecRequest> DrainLuaExecQueue() {
    std::lock_guard<std::mutex> lock(LuaExecQueueMutex());
    std::deque<PendingLuaExecRequest> drained;
    std::swap(drained, LuaExecQueueStorage());
    return drained;
}

void SetPromiseValueSafely(std::promise<LuaExecResult>& promise, LuaExecResult result) {
    try {
        promise.set_value(std::move(result));
    } catch (...) {
        // promise already satisfied or broken; the caller has long since
        // moved on. Swallow so shutdown/drain never throws.
    }
}

void ResolveDrainedAsError(std::deque<PendingLuaExecRequest>& drained, const char* reason) {
    for (auto& request : drained) {
        LuaExecResult result;
        result.error = reason == nullptr ? "Lua engine is unavailable." : reason;
        SetPromiseValueSafely(request.promise, std::move(result));
    }
}

void RemoveUnsafeGlobals(lua_State* state) {
    const char* globals_to_remove[] = {
        "debug",
        "dofile",
        "io",
        "loadfile",
        "os",
        "package",
        "require",
    };

    for (const auto* global_name : globals_to_remove) {
        lua_pushnil(state);
        lua_setglobal(state, global_name);
    }
}

int LuaPanic(lua_State* state) {
    const auto* message = lua_tostring(state, -1);
    Log(std::string("[lua] panic: ") + (message == nullptr ? "unknown" : message));
    return 0;
}

bool EnsureSdGlobal(lua_State* state) {
    if (state == nullptr) {
        return false;
    }

    lua_getglobal(state, "sd");
    const bool has_global_sd = lua_istable(state, -1);
    lua_pop(state, 1);
    if (has_global_sd) {
        return true;
    }

    lua_getfield(state, LUA_REGISTRYINDEX, kLuaSdRegistryKey);
    const bool has_registry_sd = lua_istable(state, -1);
    if (has_registry_sd) {
        lua_pushvalue(state, -1);
        lua_setglobal(state, "sd");
    }
    lua_pop(state, 1);
    return has_registry_sd;
}

LuaExecResult ExecuteLuaCodeOnLockedState(lua_State* state, const std::string& code) {
    LuaExecResult response;
    if (state == nullptr) {
        response.error = "No loaded Lua mod state is available.";
        return response;
    }
    if (code.empty()) {
        response.error = "No Lua code was provided.";
        return response;
    }

    const int stack_top_before = lua_gettop(state);
    if (!EnsureSdGlobal(state)) {
        response.error = "Lua runtime binding 'sd' is unavailable.";
        lua_settop(state, stack_top_before);
        return response;
    }

    // g_lua_print_capture_sink is thread_local in lua_engine_bindings.cpp,
    // so the swap must happen on the gameplay thread (where we're
    // executing right now — this function is only callable from the
    // pump).
    auto* previous_sink = SwapLuaPrintCaptureSink(&response.print_output);

    const int status = luaL_dostring(state, code.c_str());
    if (status != LUA_OK) {
        const char* error = lua_tostring(state, -1);
        response.error = error == nullptr ? "unknown Lua error" : error;
        lua_settop(state, stack_top_before);
        SwapLuaPrintCaptureSink(previous_sink);
        return response;
    }

    const int result_count = lua_gettop(state) - stack_top_before;
    response.results.reserve(static_cast<std::size_t>(result_count));
    for (int index = stack_top_before + 1; index <= lua_gettop(state); ++index) {
        std::string result_text;
        std::string stringify_error;
        if (!TryLuaValueToString(state, index, &result_text, &stringify_error)) {
            response.error =
                "Failed to stringify Lua result: " +
                (stringify_error.empty() ? std::string("unknown Lua tostring failure") : stringify_error);
            lua_settop(state, stack_top_before);
            SwapLuaPrintCaptureSink(previous_sink);
            return response;
        }
        response.results.push_back(std::move(result_text));
    }

    SwapLuaPrintCaptureSink(previous_sink);
    lua_settop(state, stack_top_before);
    response.ok = true;
    return response;
}

bool ExecuteEntryScript(LoadedLuaMod* mod, std::string* error_message) {
    if (mod == nullptr || mod->state == nullptr || error_message == nullptr) {
        return false;
    }

    const auto script_path = mod->descriptor.entry_script_path.string();
    if (luaL_loadfile(mod->state, script_path.c_str()) != LUA_OK) {
        *error_message = lua_tostring(mod->state, -1);
        lua_pop(mod->state, 1);
        return false;
    }

    if (lua_pcall(mod->state, 0, 0, 0) != LUA_OK) {
        *error_message = lua_tostring(mod->state, -1);
        lua_pop(mod->state, 1);
        return false;
    }

    return true;
}

}  // namespace

std::mutex& LuaEngineMutex() {
    static std::mutex mutex;
    return mutex;
}

bool& LuaEngineInitializedFlag() {
    static bool initialized = false;
    return initialized;
}

std::filesystem::path& LuaRuntimeDirectoryStorage() {
    static std::filesystem::path runtime_directory;
    return runtime_directory;
}

RuntimeBootstrap& LuaRuntimeBootstrapStorage() {
    static RuntimeBootstrap bootstrap;
    return bootstrap;
}

std::vector<std::unique_ptr<LoadedLuaMod>>& LoadedLuaModsStorage() {
    static std::vector<std::unique_ptr<LoadedLuaMod>> loaded_mods;
    return loaded_mods;
}

std::vector<std::string> BuildLuaCapabilitySet() {
    std::vector<std::string> capabilities = {
        "lua.engine",
        "events.runtime.tick",
        "runtime.mod.info",
        "ui.snapshot.read",
        "ui.element.query",
        "ui.action.query",
        "ui.action.activate",
    };

    if (multiplayer::IsFoundationInitialized()) {
        capabilities.emplace_back("multiplayer.foundation");
    }

    if (IsGameplayKeyboardInjectionInitialized()) {
        capabilities.emplace_back("input.keyboard.inject");
    }

    if (multiplayer::IsBotRuntimeInitialized()) {
        capabilities.emplace_back("bots.runtime");
        capabilities.emplace_back("bots.state.read");
        capabilities.emplace_back("bots.create");
        capabilities.emplace_back("bots.update");
        capabilities.emplace_back("bots.move");
        capabilities.emplace_back("bots.stop");
        capabilities.emplace_back("bots.destroy");
        capabilities.emplace_back("bots.cast");
    }

    return capabilities;
}

bool SupportsLuaModRequiredCapabilities(
    const RuntimeModDescriptor& mod,
    const std::vector<std::string>& capabilities,
    std::string* missing_capability) {
    if (missing_capability != nullptr) {
        missing_capability->clear();
    }

    for (const auto& required_capability : mod.required_capabilities) {
        const auto found = std::find(capabilities.begin(), capabilities.end(), required_capability);
        if (found == capabilities.end()) {
            if (missing_capability != nullptr) {
                *missing_capability = required_capability;
            }
            return false;
        }
    }

    return true;
}

bool CreateLuaStateForMod(LoadedLuaMod* mod, std::string* error_message) {
    if (mod == nullptr || error_message == nullptr) {
        return false;
    }

    mod->state = luaL_newstate();
    if (mod->state == nullptr) {
        *error_message = "luaL_newstate failed.";
        return false;
    }

    lua_atpanic(mod->state, &LuaPanic);
    luaL_openlibs(mod->state);
    RemoveUnsafeGlobals(mod->state);

    if (!RegisterLuaBindings(mod, error_message)) {
        return false;
    }

    if (!ExecuteEntryScript(mod, error_message)) {
        return false;
    }

    return true;
}

void CloseLuaStateForMod(LoadedLuaMod* mod) {
    if (mod == nullptr || mod->state == nullptr) {
        return;
    }

    lua_close(mod->state);
    mod->state = nullptr;
    mod->runtime_tick_registered = false;
    mod->run_started_registered = false;
    mod->run_ended_registered = false;
    mod->wave_started_registered = false;
    mod->wave_completed_registered = false;
    mod->enemy_death_registered = false;
    mod->enemy_spawned_registered = false;
    mod->spell_cast_registered = false;
    mod->gold_changed_registered = false;
    mod->drop_spawned_registered = false;
    mod->level_up_registered = false;
}

void LogLuaMessage(const LoadedLuaMod& mod, const std::string& message) {
    Log("[lua][" + mod.descriptor.id + "] " + message);
}

}  // namespace detail

bool InitializeLuaEngine(const RuntimeBootstrap& bootstrap, std::string* error_message) {
    std::scoped_lock lock(detail::LuaEngineMutex());
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (detail::LuaEngineInitializedFlag()) {
        return true;
    }

    auto& runtime_bootstrap = detail::LuaRuntimeBootstrapStorage();
    auto& runtime_directory = detail::LuaRuntimeDirectoryStorage();
    auto& loaded_mods = detail::LoadedLuaModsStorage();
    runtime_bootstrap = bootstrap;
    runtime_directory = bootstrap.runtime_root / "lua";
    std::filesystem::create_directories(runtime_directory);
    loaded_mods.clear();

    const auto capabilities = detail::BuildLuaCapabilitySet();
    for (const auto& mod : bootstrap.mods) {
        if (!mod.HasLuaEntry()) {
            continue;
        }

        if (mod.api_version != SDMOD_RUNTIME_API_VERSION) {
            Log(
                "[lua][" + mod.id + "] skipping mod due to apiVersion mismatch. host=" +
                std::string(SDMOD_RUNTIME_API_VERSION) + " mod=" + mod.api_version);
            continue;
        }

        std::string missing_capability;
        if (!detail::SupportsLuaModRequiredCapabilities(mod, capabilities, &missing_capability)) {
            Log(
                "[lua][" + mod.id + "] skipping mod due to unsupported required capability: " + missing_capability);
            continue;
        }

        auto loaded_mod = std::make_unique<detail::LoadedLuaMod>();
        loaded_mod->descriptor = mod;
        loaded_mod->capabilities = capabilities;

        std::string load_error;
        if (!detail::CreateLuaStateForMod(loaded_mod.get(), &load_error)) {
            detail::CloseLuaStateForMod(loaded_mod.get());
            Log("[lua][" + mod.id + "] failed to load entry script: " + load_error);
            continue;
        }

        detail::LogLuaMessage(*loaded_mod, "loaded entry script: " + mod.entry_script_path.string());
        loaded_mods.push_back(std::move(loaded_mod));
    }

    Log("Lua engine initialized.");
    Log("Lua runtime directory: " + runtime_directory.string());
    Log("Lua bootstrap manifest root: " + bootstrap.runtime_root.string());
    Log("Lua runtime mods loaded: " + std::to_string(loaded_mods.size()));
    detail::LuaEngineInitializedFlag() = true;
    return true;
}

void ShutdownLuaEngine() {
    // Drain any pending pipe-exec requests first so waiters don't
    // deadlock behind the engine mutex while we tear down Lua states.
    auto drained = detail::DrainLuaExecQueue();
    detail::ResolveDrainedAsError(drained, "Lua engine is shutting down.");

    std::scoped_lock lock(detail::LuaEngineMutex());
    if (!detail::LuaEngineInitializedFlag()) {
        return;
    }

    auto& loaded_mods = detail::LoadedLuaModsStorage();
    for (auto it = loaded_mods.rbegin(); it != loaded_mods.rend(); ++it) {
        detail::CloseLuaStateForMod(it->get());
    }
    loaded_mods.clear();
    detail::LuaRuntimeDirectoryStorage().clear();
    detail::LuaRuntimeBootstrapStorage() = RuntimeBootstrap{};
    detail::LuaEngineInitializedFlag() = false;

    // A request could have been enqueued between the first drain and
    // acquiring the engine mutex; flush again before returning.
    auto late_drained = detail::DrainLuaExecQueue();
    detail::ResolveDrainedAsError(late_drained, "Lua engine is shutting down.");

    Log("Lua engine shut down.");
}

bool IsLuaEngineInitialized() {
    std::scoped_lock lock(detail::LuaEngineMutex());
    return detail::LuaEngineInitializedFlag();
}

std::size_t GetLoadedLuaModCount() {
    std::scoped_lock lock(detail::LuaEngineMutex());
    return detail::LoadedLuaModsStorage().size();
}

bool HasLuaRuntimeTickHandlers() {
    std::scoped_lock lock(detail::LuaEngineMutex());
    return detail::LuaEngineInitializedFlag() && detail::HasAnyLuaRuntimeTickHandlers();
}

LuaExecResult QueueLuaExecRequestAndWait(const std::string& code, std::uint32_t timeout_ms) {
    LuaExecResult result;
    if (code.empty()) {
        result.error = "No Lua code was provided.";
        return result;
    }

    // Admission check + enqueue must happen under the same engine-mutex
    // critical section as ShutdownLuaEngine's flag flip and late drain,
    // otherwise a request can slip in after shutdown's late drain and
    // strand its caller until timeout (and survive into a later re-init,
    // since the queue is static). Holding LuaEngineMutex while briefly
    // taking LuaExecQueueMutex inside EnqueueLuaExecRequest does not
    // invert any lock order: ProcessLuaExecQueueOnMainThread releases
    // the queue mutex before acquiring LuaEngineMutex, so the two are
    // never held simultaneously in the opposite direction.
    std::future<LuaExecResult> future;
    {
        std::scoped_lock lock(detail::LuaEngineMutex());
        if (!detail::LuaEngineInitializedFlag()) {
            result.error = "Lua engine is not initialized.";
            return result;
        }
        future = detail::EnqueueLuaExecRequest(code);
    }
    const auto wait_status = future.wait_for(std::chrono::milliseconds(timeout_ms));
    if (wait_status != std::future_status::ready) {
        const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
        const auto endscene_ms = lua_exec_diag::g_last_endscene_ms.load(std::memory_order_acquire);
        const auto pump_enter_ms = lua_exec_diag::g_last_pump_enter_ms.load(std::memory_order_acquire);
        const auto pump_locked_ms = lua_exec_diag::g_last_pump_locked_ms.load(std::memory_order_acquire);
        const auto lua_locked_ms = lua_exec_diag::g_last_lua_locked_ms.load(std::memory_order_acquire);
        Log(
            "[lua-exec-diag] timeout. now_ms=" + std::to_string(now_ms) +
            " endscene_ago_ms=" + std::to_string(endscene_ms == 0 ? -1LL : static_cast<std::int64_t>(now_ms - endscene_ms)) +
            " pump_enter_ago_ms=" + std::to_string(pump_enter_ms == 0 ? -1LL : static_cast<std::int64_t>(now_ms - pump_enter_ms)) +
            " pump_locked_ago_ms=" + std::to_string(pump_locked_ms == 0 ? -1LL : static_cast<std::int64_t>(now_ms - pump_locked_ms)) +
            " lua_locked_ago_ms=" + std::to_string(lua_locked_ms == 0 ? -1LL : static_cast<std::int64_t>(now_ms - lua_locked_ms)));
        result.error = "Lua exec request timed out waiting for gameplay thread.";
        return result;
    }

    try {
        return future.get();
    } catch (const std::future_error& e) {
        result.error = std::string("Lua exec promise error: ") + e.what();
        return result;
    } catch (...) {
        result.error = "Lua exec failed with an unknown exception.";
        return result;
    }
}

namespace detail {
namespace {

// Drain the exec queue and execute every pending chunk under the
// engine mutex. Must be called on the main thread (the same one that
// runs HookPlayerActorTick and D3D9 EndScene), because the executed
// Lua snippets may reach into stock gameplay state via sd.* bindings.
// Returns immediately if nothing is queued, without taking the engine
// mutex.
void ProcessLuaExecQueueOnMainThread() {
    auto drained = DrainLuaExecQueue();
    if (drained.empty()) {
        return;
    }

    std::unique_lock<std::mutex> lock(LuaEngineMutex());
    lua_exec_diag::g_last_lua_locked_ms.store(
        static_cast<std::uint64_t>(GetTickCount64()),
        std::memory_order_release);
    if (!LuaEngineInitializedFlag()) {
        lock.unlock();
        ResolveDrainedAsError(drained, "Lua engine is not initialized.");
        return;
    }

    auto& mods = LoadedLuaModsStorage();
    lua_State* shared_state =
        (mods.empty() || mods.front() == nullptr) ? nullptr : mods.front()->state;

    for (auto& request : drained) {
        LuaExecResult result = ExecuteLuaCodeOnLockedState(shared_state, request.code);
        SetPromiseValueSafely(request.promise, std::move(result));
    }
}

}  // namespace
}  // namespace detail

void PumpLuaExecQueueOnMainThread() {
    detail::ProcessLuaExecQueueOnMainThread();
}

void PumpLuaWorkOnMainThread(const SDModRuntimeTickContext& context) {
    detail::ProcessLuaExecQueueOnMainThread();

    std::scoped_lock lock(detail::LuaEngineMutex());
    if (!detail::LuaEngineInitializedFlag()) {
        return;
    }
    if (detail::HasAnyLuaRuntimeTickHandlers()) {
        detail::DispatchRuntimeTickToLuaMods(context);
    }
}

void PumpLuaWorkOnGameplayThread(const SDModRuntimeTickContext& context) {
    detail::ProcessLuaExecQueueOnMainThread();

    std::scoped_lock lock(detail::LuaEngineMutex());
    if (!detail::LuaEngineInitializedFlag()) {
        return;
    }
    if (detail::HasAnyLuaRuntimeTickHandlers()) {
        detail::DispatchRuntimeTickToLuaMods(context);
    }
}

}  // namespace sdmod
