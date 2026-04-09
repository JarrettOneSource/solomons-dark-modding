#include "runtime_tick_service.h"

#include "bot_runtime.h"
#include "logger.h"
#include "lua_engine.h"
#include "native_mods.h"
#include "runtime_debug.h"

#include <Windows.h>

#include <atomic>
#include <cstdint>
#include <thread>

namespace sdmod {
namespace {

constexpr std::uint32_t kRuntimeTickIntervalMs = 50;

std::atomic<bool> g_runtime_tick_running = false;
std::thread g_runtime_tick_thread;
HANDLE g_runtime_tick_stop_event = nullptr;

void RuntimeTickThreadMain() {
    std::uint64_t tick_count = 0;
    while (g_runtime_tick_running.load(std::memory_order_acquire)) {
        ++tick_count;
        const SDModRuntimeTickContext context = {
            sizeof(SDModRuntimeTickContext),
            kRuntimeTickIntervalMs,
            tick_count,
            GetTickCount64(),
        };
        multiplayer::TickBotRuntime(context.monotonic_milliseconds);
        DispatchLuaRuntimeTick(context);
        DispatchNativeModRuntimeTick(context);
        RuntimeDebug_Tick();

        if (WaitForSingleObject(g_runtime_tick_stop_event, kRuntimeTickIntervalMs) == WAIT_OBJECT_0) {
            break;
        }
    }
}

}  // namespace

bool StartRuntimeTickService() {
    if (g_runtime_tick_running.exchange(true, std::memory_order_acq_rel)) {
        return true;
    }

    g_runtime_tick_stop_event = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    if (g_runtime_tick_stop_event == nullptr) {
        g_runtime_tick_running.store(false, std::memory_order_release);
        Log("Runtime tick service failed to create the stop event.");
        return false;
    }

    try {
        g_runtime_tick_thread = std::thread(RuntimeTickThreadMain);
        Log("Runtime tick service started.");
        return true;
    } catch (...) {
        g_runtime_tick_running.store(false, std::memory_order_release);
        CloseHandle(g_runtime_tick_stop_event);
        g_runtime_tick_stop_event = nullptr;
        Log("Runtime tick service failed to start the worker thread.");
        return false;
    }
}

void StopRuntimeTickService() {
    g_runtime_tick_running.store(false, std::memory_order_release);
    if (g_runtime_tick_stop_event != nullptr) {
        SetEvent(g_runtime_tick_stop_event);
    }
    if (g_runtime_tick_thread.joinable()) {
        g_runtime_tick_thread.join();
    }
    if (g_runtime_tick_stop_event != nullptr) {
        CloseHandle(g_runtime_tick_stop_event);
        g_runtime_tick_stop_event = nullptr;
    }
}

bool IsRuntimeTickServiceRunning() {
    return g_runtime_tick_running.load(std::memory_order_acquire);
}

std::uint32_t GetRuntimeTickServiceIntervalMs() {
    return kRuntimeTickIntervalMs;
}

}  // namespace sdmod
