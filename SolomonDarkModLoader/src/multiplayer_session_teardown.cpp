#include "multiplayer_session_teardown.h"

#include "logger.h"
#include "mod_loader.h"
#include "multiplayer_local_transport.h"
#include "multiplayer_runtime_state.h"
#include "multiplayer_steam_session.h"

#include <Windows.h>

#include <atomic>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <mutex>
#include <string>

namespace sdmod::multiplayer {
namespace {

constexpr std::uint64_t kTransportGoodbyeGraceMs = 150;
constexpr std::uint64_t kDirectoryDelistWaitMs = 3000;

enum class LeavePipeState {
    Idle,
    AwaitingResponse,
    Armed,
};

enum class RemoteEndRequest {
    None,
    HostClosed,
    AuthorityLost,
};

struct SessionTeardownState {
    bool active = false;
    bool is_host = false;
    bool steam_required = false;
    bool local_transport_required = false;
    bool directory_delist_required = false;
    bool close_posted = false;
    std::uint64_t started_ms = 0;
    std::string trigger;
    std::filesystem::path directory_completion_path;
};

std::atomic<LeavePipeState> g_leave_pipe_state{LeavePipeState::Idle};
std::atomic<RemoteEndRequest> g_remote_end_request{RemoteEndRequest::None};
std::atomic<bool> g_teardown_active{false};
std::mutex g_teardown_mutex;
SessionTeardownState g_teardown;

std::string ReadEnvironmentVariable(const char* name) {
    char* value = nullptr;
    std::size_t value_length = 0;
    if (_dupenv_s(&value, &value_length, name) != 0 || value == nullptr) {
        return {};
    }
    std::string result(value);
    std::free(value);
    return result;
}

bool IsSafeLaunchToken(const std::string& value) {
    if (value.empty() || value.size() > 128) {
        return false;
    }
    for (const auto ch : value) {
        if ((ch < 'a' || ch > 'z') &&
            (ch < 'A' || ch > 'Z') &&
            (ch < '0' || ch > '9') &&
            ch != '-' &&
            ch != '_') {
            return false;
        }
    }
    return true;
}

std::filesystem::path DirectorySignalPath(
    const std::string& launch_token,
    const char* suffix) {
    return GetStageRuntimeDirectory() /
        ("session-teardown-" + launch_token + suffix);
}

bool RequestDirectoryDelist(
    const std::string& launch_token,
    std::filesystem::path* completion_path) {
    if (completion_path == nullptr || !IsSafeLaunchToken(launch_token)) {
        return false;
    }

    const auto request_path =
        DirectorySignalPath(launch_token, ".request.json");
    const auto temporary_path =
        DirectorySignalPath(launch_token, ".request.tmp");
    *completion_path =
        DirectorySignalPath(launch_token, ".complete.json");

    std::error_code error;
    std::filesystem::remove(*completion_path, error);
    error.clear();
    std::filesystem::remove(temporary_path, error);

    std::ofstream stream(
        temporary_path,
        std::ios::binary | std::ios::trunc);
    if (!stream.is_open()) {
        Log(
            "Session teardown could not create the website delist request: " +
            temporary_path.string());
        return false;
    }
    stream << "{\"launchToken\":\"" << launch_token
           << "\",\"requestedBy\":\"loader\"}\n";
    stream.close();
    if (!stream) {
        std::filesystem::remove(temporary_path, error);
        return false;
    }

    error.clear();
    std::filesystem::rename(temporary_path, request_path, error);
    if (error) {
        std::filesystem::remove(temporary_path, error);
        Log(
            "Session teardown could not publish the website delist request: " +
            request_path.string());
        return false;
    }
    Log(
        "Session teardown requested website lobby delist. path=" +
        request_path.string());
    return true;
}

BOOL CALLBACK FindMainWindow(HWND hwnd, LPARAM context) {
    auto* result = reinterpret_cast<HWND*>(context);
    if (result == nullptr || *result != nullptr) {
        return FALSE;
    }

    DWORD process_id = 0;
    GetWindowThreadProcessId(hwnd, &process_id);
    if (process_id != GetCurrentProcessId() ||
        GetWindow(hwnd, GW_OWNER) != nullptr ||
        !IsWindowVisible(hwnd)) {
        return TRUE;
    }

    *result = hwnd;
    return FALSE;
}

void PostGracefulGameClose() {
    HWND window = nullptr;
    EnumWindows(&FindMainWindow, reinterpret_cast<LPARAM>(&window));
    if (window == nullptr || !PostMessageW(window, WM_CLOSE, 0, 0)) {
        Log("Session teardown could not post WM_CLOSE to the staged game.");
        return;
    }
    Log("Session teardown posted WM_CLOSE to the staged game.");
}

bool HasActiveSession(const RuntimeState& runtime) {
    return runtime.service_loop_running &&
        runtime.session_transport != SessionTransportKind::None &&
        runtime.session_status != SessionStatus::Idle;
}

void BeginSessionTeardown(
    std::uint64_t now_ms,
    const char* trigger,
    RemoteEndRequest remote_end) {
    std::scoped_lock lock(g_teardown_mutex);
    if (g_teardown.active) {
        return;
    }

    const auto runtime = SnapshotRuntimeState();
    g_teardown = SessionTeardownState{};
    g_teardown.active = true;
    g_teardown.is_host = runtime.session_is_host;
    g_teardown.steam_required = IsSteamSessionEnabled();
    g_teardown.local_transport_required = IsLocalTransportEnabled();
    g_teardown.started_ms = now_ms;
    g_teardown.trigger = trigger == nullptr ? "unknown" : trigger;

    if (g_teardown.is_host &&
        ReadEnvironmentVariable(
            "SDMOD_LOBBY_DIRECTORY_PUBLISHER") == "1") {
        const auto launch_token =
            ReadEnvironmentVariable("SDMOD_LAUNCH_TOKEN");
        g_teardown.directory_delist_required = RequestDirectoryDelist(
            launch_token,
            &g_teardown.directory_completion_path);
    }

    RequestSteamSessionTeardown(
        remote_end != RemoteEndRequest::None
            ? SessionGoodbyeReason::TransportFailure
            : g_teardown.is_host
                ? SessionGoodbyeReason::LobbyClosed
                : SessionGoodbyeReason::Leaving,
        remote_end == RemoteEndRequest::None);
    RequestLocalTransportTeardown(
        remote_end != RemoteEndRequest::None
            ? SessionGoodbyeReason::TransportFailure
            : g_teardown.is_host
                ? SessionGoodbyeReason::LobbyClosed
                : SessionGoodbyeReason::Leaving,
        remote_end == RemoteEndRequest::None);

    UpdateRuntimeState([&](RuntimeState& state) {
        state.transport_ready = false;
        state.status_text =
            remote_end == RemoteEndRequest::HostClosed
            ? "The host closed the lobby."
            : remote_end == RemoteEndRequest::AuthorityLost
                ? "The multiplayer host connection was lost."
            : g_teardown.is_host
                ? "Closing the multiplayer lobby cleanly."
                : "Leaving the multiplayer lobby cleanly.";
        state.error_text.clear();
    });
    Log(
        "Canonical session teardown started. trigger=" +
        g_teardown.trigger +
        " role=" + (g_teardown.is_host ? "host" : "client") +
        " steam=" + (g_teardown.steam_required ? "1" : "0") +
        " gameplay_transport=" +
        (g_teardown.local_transport_required ? "1" : "0") +
        " directory=" +
        (g_teardown.directory_delist_required ? "1" : "0"));
    g_teardown_active.store(true, std::memory_order_release);
}

bool DirectoryDelistFinished(std::uint64_t now_ms) {
    if (!g_teardown.directory_delist_required) {
        return true;
    }
    std::error_code error;
    if (std::filesystem::is_regular_file(
            g_teardown.directory_completion_path,
            error)) {
        return true;
    }
    return now_ms >= g_teardown.started_ms + kDirectoryDelistWaitMs;
}

}  // namespace

bool RequestSessionLeaveAfterPipeAck(std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }

    if (g_teardown_active.load(std::memory_order_acquire)) {
        return true;
    }
    if (!HasActiveSession(SnapshotRuntimeState())) {
        if (error_message != nullptr) {
            *error_message = "No live multiplayer session is active.";
        }
        return false;
    }

    auto expected = LeavePipeState::Idle;
    if (!g_leave_pipe_state.compare_exchange_strong(
            expected,
            LeavePipeState::AwaitingResponse,
            std::memory_order_acq_rel,
            std::memory_order_acquire)) {
        if (expected == LeavePipeState::Armed) {
            return true;
        }
        if (error_message != nullptr) {
            *error_message = "A live-session leave request is already awaiting acknowledgement.";
        }
        return false;
    }
    return true;
}

void ResolveSessionLeavePipeResponse(bool delivered) {
    auto expected = LeavePipeState::AwaitingResponse;
    g_leave_pipe_state.compare_exchange_strong(
        expected,
        delivered ? LeavePipeState::Armed : LeavePipeState::Idle,
        std::memory_order_acq_rel,
        std::memory_order_acquire);
}

void NotifyRemoteHostSessionClosed() {
    g_remote_end_request.store(
        RemoteEndRequest::HostClosed,
        std::memory_order_release);
}

void NotifySessionAuthorityLost() {
    auto expected = RemoteEndRequest::None;
    g_remote_end_request.compare_exchange_strong(
        expected,
        RemoteEndRequest::AuthorityLost,
        std::memory_order_acq_rel,
        std::memory_order_acquire);
}

void TickSessionTeardownOnAppThread(std::uint64_t now_ms) {
    auto expected = LeavePipeState::Armed;
    const bool explicit_leave =
        g_leave_pipe_state.compare_exchange_strong(
            expected,
            LeavePipeState::Idle,
            std::memory_order_acq_rel,
            std::memory_order_acquire);
    const auto remote_request =
        g_remote_end_request.exchange(
            RemoteEndRequest::None,
            std::memory_order_acq_rel);
    if (!g_teardown_active.load(std::memory_order_acquire) &&
        (explicit_leave || remote_request != RemoteEndRequest::None)) {
        BeginSessionTeardown(
            now_ms,
            explicit_leave
                ? "explicit_leave"
                : remote_request == RemoteEndRequest::HostClosed
                    ? "host_closed"
                    : "authority_lost",
            remote_request);
    }

    std::scoped_lock lock(g_teardown_mutex);
    if (!g_teardown.active || g_teardown.close_posted) {
        return;
    }

    const bool steam_finished =
        !g_teardown.steam_required || IsSteamSessionTeardownComplete();
    const bool local_finished =
        !g_teardown.local_transport_required ||
        IsLocalTransportTeardownComplete();
    const bool goodbye_grace_finished =
        now_ms >= g_teardown.started_ms + kTransportGoodbyeGraceMs;
    if (!steam_finished ||
        !local_finished ||
        !goodbye_grace_finished ||
        !DirectoryDelistFinished(now_ms)) {
        return;
    }

    g_teardown.close_posted = true;
    PostGracefulGameClose();
}

void PrepareSessionTeardownForProcessExit() {
    if (!g_teardown_active.load(std::memory_order_acquire) &&
        HasActiveSession(SnapshotRuntimeState())) {
        BeginSessionTeardown(
            GetTickCount64(),
            "process_exit",
            RemoteEndRequest::None);
        return;
    }

    const bool is_host =
        IsSteamSessionHost() || IsLocalTransportHost();
    RequestSteamSessionTeardown(
        is_host
            ? SessionGoodbyeReason::LobbyClosed
            : SessionGoodbyeReason::Leaving,
        true);
    RequestLocalTransportTeardown(
        is_host
            ? SessionGoodbyeReason::LobbyClosed
            : SessionGoodbyeReason::Leaving,
        true);
}

void ResetSessionTeardownCoordinator() {
    std::scoped_lock lock(g_teardown_mutex);
    g_leave_pipe_state.store(LeavePipeState::Idle, std::memory_order_release);
    g_remote_end_request.store(RemoteEndRequest::None, std::memory_order_release);
    g_teardown = SessionTeardownState{};
    g_teardown_active.store(false, std::memory_order_release);
}

}  // namespace sdmod::multiplayer
