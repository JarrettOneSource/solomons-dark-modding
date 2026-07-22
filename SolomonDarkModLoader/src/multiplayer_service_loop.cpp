#include "multiplayer_service_loop.h"

#include "logger.h"
#include "multiplayer_local_transport.h"
#include "multiplayer_runtime_state.h"
#include "multiplayer_steam_session.h"
#include "multiplayer_steam_gameplay_queue.h"
#include "steam_bootstrap.h"

#include <Windows.h>

#include <atomic>
#include <cstdint>
#include <mutex>
#include <string>
#include <thread>

namespace sdmod::multiplayer {
namespace {

constexpr std::uint32_t kServiceTickIntervalMs = 16;
constexpr std::uint64_t kTransportTickGapDiagnosticMs = 250;
constexpr std::uint64_t kSteamStageDurationDiagnosticMs = 100;
constexpr std::uint64_t kSteamStageDiagnosticIntervalMs = 1000;

std::atomic<bool> g_service_running = false;
std::thread g_service_thread;
HANDLE g_service_stop_event = nullptr;
std::mutex g_session_transport_lifecycle_mutex;
std::atomic<DWORD> g_gameplay_transport_owner_thread_id{0};
std::atomic<bool> g_wrong_gameplay_transport_thread_logged{false};
std::uint64_t g_last_gameplay_transport_tick_ms = 0;
bool g_has_gameplay_transport_tick = false;

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
    std::uint64_t last_slow_stage_log_ms = 0;

    Log(
        "Multiplayer Steam service thread owns callback, session, and "
        "network I/O. thread_id=" +
        std::to_string(GetCurrentThreadId()));

    while (g_service_running.load(std::memory_order_acquire)) {
        const auto now_ms = GetTickCount64();
        const auto bootstrap_started_ms =
            static_cast<std::uint64_t>(GetTickCount64());
        SteamBootstrapTick();
        const auto bootstrap_finished_ms =
            static_cast<std::uint64_t>(GetTickCount64());
        const auto steam_snapshot = GetSteamBootstrapSnapshot();
        ApplySteamSnapshotToRuntime(now_ms, steam_snapshot);
        const auto session_started_ms =
            static_cast<std::uint64_t>(GetTickCount64());
        TickSteamSession(now_ms);
        const auto session_finished_ms =
            static_cast<std::uint64_t>(GetTickCount64());
        ServiceSteamGameplaySendQueue();
        const auto send_finished_ms =
            static_cast<std::uint64_t>(GetTickCount64());
        const auto runtime_state = SnapshotRuntimeState();

        const auto bootstrap_duration_ms =
            bootstrap_finished_ms - bootstrap_started_ms;
        const auto session_duration_ms =
            session_finished_ms - session_started_ms;
        const auto send_duration_ms = send_finished_ms - session_finished_ms;
        if ((bootstrap_duration_ms >= kSteamStageDurationDiagnosticMs ||
             session_duration_ms >= kSteamStageDurationDiagnosticMs ||
             send_duration_ms >= kSteamStageDurationDiagnosticMs) &&
            (last_slow_stage_log_ms == 0 ||
             now_ms >= last_slow_stage_log_ms +
                 kSteamStageDiagnosticIntervalMs)) {
            last_slow_stage_log_ms = now_ms;
            Log(
                "Multiplayer Steam service stage slow. bootstrap_ms=" +
                std::to_string(bootstrap_duration_ms) +
                " session_ms=" + std::to_string(session_duration_ms) +
                " gameplay_send_ms=" + std::to_string(send_duration_ms));
        }

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

    ShutdownSteamSession();
    UpdateRuntimeState([](RuntimeState& state) {
        state.service_loop_running = false;
    });
}

}  // namespace

bool StartServiceLoop() {
    std::scoped_lock lifecycle_lock(g_session_transport_lifecycle_mutex);
    if (g_service_running.load(std::memory_order_acquire)) {
        return true;
    }

    if (!InitializeLocalTransport()) {
        return false;
    }

    if (!InitializeSteamSession()) {
        ShutdownSteamSession();
        ShutdownLocalTransport();
        return false;
    }

    g_service_stop_event = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    if (g_service_stop_event == nullptr) {
        ShutdownSteamSession();
        ShutdownLocalTransport();
        Log("Multiplayer foundation: failed to create the service loop stop event.");
        return false;
    }

    g_gameplay_transport_owner_thread_id.store(0, std::memory_order_release);
    g_wrong_gameplay_transport_thread_logged.store(false, std::memory_order_release);
    g_last_gameplay_transport_tick_ms = 0;
    g_has_gameplay_transport_tick = false;
    g_service_running.store(true, std::memory_order_release);
    try {
        g_service_thread = std::thread(ServiceThreadMain);
        return true;
    } catch (...) {
        g_service_running.store(false, std::memory_order_release);
        CloseHandle(g_service_stop_event);
        g_service_stop_event = nullptr;
        ShutdownSteamSession();
        ShutdownLocalTransport();
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
    {
        std::scoped_lock lifecycle_lock(g_session_transport_lifecycle_mutex);
        ShutdownLocalTransport();
        g_gameplay_transport_owner_thread_id.store(0, std::memory_order_release);
        g_wrong_gameplay_transport_thread_logged.store(false, std::memory_order_release);
        g_last_gameplay_transport_tick_ms = 0;
        g_has_gameplay_transport_tick = false;
    }
}

void TickGameplayTransportOnAppThread(std::uint64_t now_ms) {
    if (!g_service_running.load(std::memory_order_acquire)) {
        return;
    }

    std::scoped_lock lifecycle_lock(g_session_transport_lifecycle_mutex);
    if (!g_service_running.load(std::memory_order_acquire)) {
        return;
    }

    const auto current_thread_id = GetCurrentThreadId();
    auto owner_thread_id =
        g_gameplay_transport_owner_thread_id.load(std::memory_order_acquire);
    if (owner_thread_id == 0) {
        auto expected = static_cast<DWORD>(0);
        if (g_gameplay_transport_owner_thread_id.compare_exchange_strong(
                expected,
                current_thread_id,
                std::memory_order_acq_rel,
                std::memory_order_acquire)) {
            owner_thread_id = current_thread_id;
        } else {
            owner_thread_id = expected;
        }
    }
    if (owner_thread_id != current_thread_id) {
        if (!g_wrong_gameplay_transport_thread_logged.exchange(
                true,
                std::memory_order_acq_rel)) {
            Log(
                "Multiplayer gameplay transport tick rejected outside its "
                "owning AppMainTick thread.");
        }
        return;
    }

    if (g_has_gameplay_transport_tick &&
        now_ms >= g_last_gameplay_transport_tick_ms) {
        const auto tick_gap_ms = now_ms - g_last_gameplay_transport_tick_ms;
        if (tick_gap_ms < kServiceTickIntervalMs) {
            return;
        }
        if (tick_gap_ms >= kTransportTickGapDiagnosticMs) {
            Log(
                "Multiplayer app-thread gameplay tick gap. gap_ms=" +
                std::to_string(tick_gap_ms));
        }
    }
    g_last_gameplay_transport_tick_ms = now_ms;
    g_has_gameplay_transport_tick = true;

    TickLocalTransport(now_ms);
}

bool IsServiceLoopRunning() {
    return g_service_running.load(std::memory_order_acquire);
}

std::uint32_t GetServiceTickIntervalMs() {
    return kServiceTickIntervalMs;
}

}  // namespace sdmod::multiplayer
