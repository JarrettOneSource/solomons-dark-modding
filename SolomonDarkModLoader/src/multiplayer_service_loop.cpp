#include "multiplayer_service_loop.h"

#include "logger.h"
#include "multiplayer_runtime_state.h"
#include "steam_bootstrap.h"

#include <Windows.h>

#include <atomic>
#include <cstdint>
#include <string>
#include <thread>

namespace sdmod::multiplayer {
namespace {

constexpr std::uint32_t kServiceTickIntervalMs = 50;

std::atomic<bool> g_service_running = false;
std::thread g_service_thread;
HANDLE g_service_stop_event = nullptr;

void LogStateTransitionIfNeeded(const RuntimeState& runtime_state,
                                SessionStatus& last_status,
                                SessionTransportKind& last_transport,
                                std::string& last_status_text) {
    if (runtime_state.session_status != last_status || runtime_state.session_transport != last_transport) {
        Log(std::string("Multiplayer foundation state: status=") + SessionStatusLabel(runtime_state.session_status) +
            " transport=" + SessionTransportLabel(runtime_state.session_transport));
        last_status = runtime_state.session_status;
        last_transport = runtime_state.session_transport;
    }

    if (!runtime_state.status_text.empty() && runtime_state.status_text != last_status_text) {
        Log("Multiplayer foundation status: " + runtime_state.status_text);
        last_status_text = runtime_state.status_text;
    }
}

void ServiceThreadMain() {
    bool logged_ready = false;
    std::string last_error;
    SessionStatus last_status = SessionStatus::Idle;
    SessionTransportKind last_transport = SessionTransportKind::None;
    std::string last_status_text;

    while (g_service_running.load(std::memory_order_acquire)) {
        const auto now_ms = GetTickCount64();
        SteamBootstrapTick();
        const auto steam_snapshot = GetSteamBootstrapSnapshot();
        ApplySteamSnapshotToRuntime(now_ms, steam_snapshot);
        const auto runtime_state = SnapshotRuntimeState();

        if (steam_snapshot.transport_interfaces_ready && !logged_ready) {
            Log("Multiplayer foundation: Steam transport is ready for higher-level session work.");
            logged_ready = true;
        }

        LogStateTransitionIfNeeded(runtime_state, last_status, last_transport, last_status_text);

        if (!steam_snapshot.error_text.empty() && steam_snapshot.error_text != last_error) {
            Log("Multiplayer foundation: " + steam_snapshot.error_text);
            last_error = steam_snapshot.error_text;
        }

        if (WaitForSingleObject(g_service_stop_event, kServiceTickIntervalMs) == WAIT_OBJECT_0) {
            break;
        }
    }

    UpdateRuntimeState([](RuntimeState& state) {
        state.service_loop_running = false;
    });
}

}  // namespace

bool StartServiceLoop() {
    if (g_service_running.exchange(true, std::memory_order_acq_rel)) {
        return true;
    }

    g_service_stop_event = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    if (g_service_stop_event == nullptr) {
        g_service_running.store(false, std::memory_order_release);
        Log("Multiplayer foundation: failed to create the service loop stop event.");
        return false;
    }

    try {
        g_service_thread = std::thread(ServiceThreadMain);
        return true;
    } catch (...) {
        g_service_running.store(false, std::memory_order_release);
        CloseHandle(g_service_stop_event);
        g_service_stop_event = nullptr;
        Log("Multiplayer foundation: failed to start the service loop thread.");
        return false;
    }
}

void StopServiceLoop() {
    g_service_running.store(false, std::memory_order_release);
    if (g_service_stop_event != nullptr) {
        SetEvent(g_service_stop_event);
    }
    if (g_service_thread.joinable()) {
        g_service_thread.join();
    }
    if (g_service_stop_event != nullptr) {
        CloseHandle(g_service_stop_event);
        g_service_stop_event = nullptr;
    }
}

bool IsServiceLoopRunning() {
    return g_service_running.load(std::memory_order_acquire);
}

std::uint32_t GetServiceTickIntervalMs() {
    return kServiceTickIntervalMs;
}

}  // namespace sdmod::multiplayer
