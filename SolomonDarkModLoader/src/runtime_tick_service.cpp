#include "runtime_tick_service.h"

#include "bot_runtime.h"
#include "logger.h"
#include "runtime_debug.h"

#include <Windows.h>
#include <process.h>

#include <atomic>
#include <cstdint>

namespace sdmod {
namespace {

constexpr std::uint32_t kRuntimeTickIntervalMs = 50;

std::atomic<bool> g_runtime_tick_running = false;
HANDLE g_runtime_tick_thread = nullptr;
HANDLE g_runtime_tick_stop_event = nullptr;

unsigned __stdcall RuntimeTickThreadMain(void*) {
    std::uint64_t tick_count = 0;
    while (g_runtime_tick_running.load(std::memory_order_acquire)) {
        ++tick_count;
        const RuntimeTickContext context = {
            kRuntimeTickIntervalMs,
            tick_count,
            GetTickCount64(),
        };
        multiplayer::TickBotRuntime(context.monotonic_milliseconds);
        RuntimeDebug_Tick();

        if (WaitForSingleObject(g_runtime_tick_stop_event, kRuntimeTickIntervalMs) == WAIT_OBJECT_0) {
            break;
        }
    }
    return 0;
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

    const auto runtime_tick_thread = _beginthreadex(
        nullptr,
        0,
        &RuntimeTickThreadMain,
        nullptr,
        0,
        nullptr);
    if (runtime_tick_thread == 0) {
        g_runtime_tick_running.store(false, std::memory_order_release);
        CloseHandle(g_runtime_tick_stop_event);
        g_runtime_tick_stop_event = nullptr;
        Log("Runtime tick service failed to start the worker thread.");
        return false;
    }

    g_runtime_tick_thread = reinterpret_cast<HANDLE>(runtime_tick_thread);
    Log("Runtime tick service started.");
    return true;
}

void StopRuntimeTickService() {
    g_runtime_tick_running.store(false, std::memory_order_release);
    if (g_runtime_tick_stop_event != nullptr) {
        SetEvent(g_runtime_tick_stop_event);
    }
    if (g_runtime_tick_thread != nullptr) {
        WaitForSingleObject(g_runtime_tick_thread, INFINITE);
        CloseHandle(g_runtime_tick_thread);
        g_runtime_tick_thread = nullptr;
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
