#include "steam_bootstrap.h"

#include "steam_bootstrap_internal.h"

#include "logger.h"
#include "mod_loader.h"

#include <algorithm>
#include <cstring>
#include <mutex>
#include <sstream>
#include <utility>
#include <vector>

namespace sdmod::detail {

std::mutex& SteamBootstrapMutex() {
    static std::mutex mutex;
    return mutex;
}

SteamBootstrapState& MutableSteamBootstrapState() {
    static SteamBootstrapState state;
    return state;
}

}  // namespace sdmod::detail

namespace sdmod {
namespace {

constexpr std::size_t kMaxPendingSteamEvents = 256;
constexpr std::uint32_t kMaxCallResultBytes = 64 * 1024;

std::string BoundedText(const char* text, std::size_t capacity) {
    if (text == nullptr || capacity == 0) {
        return {};
    }
    std::size_t length = 0;
    while (length < capacity && text[length] != '\0') {
        ++length;
    }
    return std::string(text, length);
}

void QueueSteamEvent(detail::SteamBootstrapState& state, SteamEvent event) {
    if (state.pending_events.size() >= kMaxPendingSteamEvents) {
        state.pending_events.erase(state.pending_events.begin());
    }
    state.pending_events.push_back(std::move(event));
}

SteamPeerNetworkStatus BuildPeerNetworkStatus(
    const detail::SteamBootstrapState& state,
    const steamabi::NetworkConnectionInfo& info,
    const steamabi::NetworkRealtimeStatus* realtime_status = nullptr) {
    SteamPeerNetworkStatus status;
    if (state.identity_get_steam_id64 != nullptr) {
        status.steam_id = state.identity_get_steam_id64(&info.remote_identity);
    }
    status.connection_state = info.state;
    status.end_reason = info.end_reason;
    status.using_relay = (info.flags & steamabi::kNetworkConnectionInfoRelayed) != 0;
    status.debug_text = BoundedText(info.end_debug, sizeof(info.end_debug));
    status.connection_description =
        BoundedText(info.connection_description, sizeof(info.connection_description));
    if (realtime_status != nullptr) {
        status.connection_state = realtime_status->state;
        status.ping_ms = realtime_status->ping_ms;
        status.pending_reliable_bytes = realtime_status->pending_reliable_bytes;
    }
    return status;
}

template <typename Payload>
bool CopyCallbackPayload(
    const void* source,
    std::size_t source_size,
    Payload* payload) {
    if (source == nullptr || payload == nullptr || source_size != sizeof(Payload)) {
        return false;
    }
    std::memcpy(payload, source, sizeof(Payload));
    return true;
}

void DecodeSteamCallback(
    detail::SteamBootstrapState& state,
    std::int32_t callback_id,
    const void* payload,
    std::size_t payload_size,
    std::uint64_t api_call) {
    switch (callback_id) {
    case steamabi::kCallbackLobbyCreated: {
        steamabi::LobbyCreated callback{};
        if (!CopyCallbackPayload(payload, payload_size, &callback)) {
            return;
        }
        SteamEvent event;
        event.kind = SteamEventKind::LobbyCreated;
        event.api_call = api_call;
        event.lobby_id = callback.lobby_id;
        event.result_code = callback.result;
        event.success = callback.result == steamabi::kResultOk && callback.lobby_id != 0;
        QueueSteamEvent(state, std::move(event));
        return;
    }
    case steamabi::kCallbackLobbyEnter: {
        steamabi::LobbyEnter callback{};
        if (!CopyCallbackPayload(payload, payload_size, &callback)) {
            return;
        }
        SteamEvent event;
        event.kind = SteamEventKind::LobbyEntered;
        event.api_call = api_call;
        event.lobby_id = callback.lobby_id;
        event.result_code = static_cast<std::int32_t>(callback.response);
        event.success = callback.response == steamabi::kLobbyEnterSuccess && callback.lobby_id != 0;
        QueueSteamEvent(state, std::move(event));
        return;
    }
    case steamabi::kCallbackGameLobbyJoinRequested: {
        steamabi::GameLobbyJoinRequested callback{};
        if (!CopyCallbackPayload(payload, payload_size, &callback)) {
            return;
        }
        SteamEvent event;
        event.kind = SteamEventKind::LobbyJoinRequested;
        event.lobby_id = callback.lobby_id;
        event.user_id = callback.friend_id;
        event.success = callback.lobby_id != 0;
        QueueSteamEvent(state, std::move(event));
        return;
    }
    case steamabi::kCallbackGameRichPresenceJoinRequested: {
        steamabi::GameRichPresenceJoinRequested callback{};
        if (!CopyCallbackPayload(payload, payload_size, &callback)) {
            return;
        }
        SteamEvent event;
        event.kind = SteamEventKind::RichPresenceJoinRequested;
        event.user_id = callback.friend_id;
        event.connect_string = BoundedText(callback.connect, sizeof(callback.connect));
        event.success = !event.connect_string.empty();
        QueueSteamEvent(state, std::move(event));
        return;
    }
    case steamabi::kCallbackLobbyInvite: {
        steamabi::LobbyInvite callback{};
        if (!CopyCallbackPayload(payload, payload_size, &callback)) {
            return;
        }
        SteamEvent event;
        event.kind = SteamEventKind::LobbyInviteReceived;
        event.lobby_id = callback.lobby_id;
        event.user_id = callback.sender_id;
        event.success = callback.lobby_id != 0;
        QueueSteamEvent(state, std::move(event));
        return;
    }
    case steamabi::kCallbackLobbyDataUpdate: {
        steamabi::LobbyDataUpdate callback{};
        if (!CopyCallbackPayload(payload, payload_size, &callback)) {
            return;
        }
        SteamEvent event;
        event.kind = SteamEventKind::LobbyDataUpdated;
        event.lobby_id = callback.lobby_id;
        event.user_id = callback.member_id;
        event.success = callback.success != 0;
        QueueSteamEvent(state, std::move(event));
        return;
    }
    case steamabi::kCallbackLobbyChatUpdate: {
        steamabi::LobbyChatUpdate callback{};
        if (!CopyCallbackPayload(payload, payload_size, &callback)) {
            return;
        }
        SteamEvent event;
        event.kind = SteamEventKind::LobbyMemberChanged;
        event.lobby_id = callback.lobby_id;
        event.user_id = callback.changed_user_id;
        event.actor_id = callback.making_change_user_id;
        event.state_change = callback.state_change;
        event.success = true;
        QueueSteamEvent(state, std::move(event));
        return;
    }
    case steamabi::kCallbackNetworkingMessagesSessionRequest: {
        steamabi::NetworkingMessagesSessionRequest callback{};
        if (!CopyCallbackPayload(payload, payload_size, &callback)) {
            return;
        }
        SteamEvent event;
        event.kind = SteamEventKind::NetworkSessionRequested;
        if (state.identity_get_steam_id64 != nullptr) {
            event.user_id = state.identity_get_steam_id64(&callback.remote_identity);
        }
        event.success = event.user_id != 0;
        QueueSteamEvent(state, std::move(event));
        return;
    }
    case steamabi::kCallbackNetworkingMessagesSessionFailed: {
        steamabi::NetworkingMessagesSessionFailed callback{};
        if (!CopyCallbackPayload(payload, payload_size, &callback)) {
            return;
        }
        SteamEvent event;
        event.kind = SteamEventKind::NetworkSessionFailed;
        event.network_status = BuildPeerNetworkStatus(state, callback.info);
        event.user_id = event.network_status.steam_id;
        event.result_code = callback.info.end_reason;
        event.success = false;
        QueueSteamEvent(state, std::move(event));
        return;
    }
    default:
        return;
    }
}

void DecodeApiCallCompleted(
    detail::SteamBootstrapState& state,
    const steamabi::CallbackMessage& callback) {
    steamabi::SteamApiCallCompleted completed{};
    if (!CopyCallbackPayload(
            callback.parameter,
            static_cast<std::size_t>(callback.parameter_size),
            &completed) ||
        completed.call == steamabi::kInvalidApiCall ||
        completed.parameter_size == 0 ||
        completed.parameter_size > kMaxCallResultBytes) {
        return;
    }

    std::vector<std::uint8_t> result(completed.parameter_size);
    bool failed = false;
    if (!state.manual_dispatch_get_api_call_result(
            state.pipe,
            completed.call,
            result.data(),
            static_cast<int>(result.size()),
            completed.callback_id,
            &failed) ||
        failed) {
        SteamEvent event;
        event.api_call = completed.call;
        event.result_code = -1;
        event.success = false;
        if (completed.callback_id == steamabi::kCallbackLobbyCreated) {
            event.kind = SteamEventKind::LobbyCreated;
            QueueSteamEvent(state, std::move(event));
        } else if (completed.callback_id == steamabi::kCallbackLobbyEnter) {
            event.kind = SteamEventKind::LobbyEntered;
            QueueSteamEvent(state, std::move(event));
        }
        return;
    }

    DecodeSteamCallback(
        state,
        completed.callback_id,
        result.data(),
        result.size(),
        completed.call);
}

void PumpSteamCallbacks(detail::SteamBootstrapState& state) {
    state.manual_dispatch_run_frame(state.pipe);
    steamabi::CallbackMessage callback{};
    while (state.manual_dispatch_get_next_callback(state.pipe, &callback)) {
        if (callback.callback_id == steamabi::kCallbackSteamApiCallCompleted) {
            DecodeApiCallCompleted(state, callback);
        } else if (callback.parameter_size >= 0) {
            DecodeSteamCallback(
                state,
                callback.callback_id,
                callback.parameter,
                static_cast<std::size_t>(callback.parameter_size),
                0);
        }
        state.manual_dispatch_free_last_callback(state.pipe);
        callback = steamabi::CallbackMessage{};
    }
    state.snapshot.callback_pump_count += 1;
    state.snapshot.last_callback_pump_ms = GetTickCount64();
}

void ResetAfterFailedInitialization(detail::SteamBootstrapState& state) {
    if (state.initialized && state.shutdown != nullptr) {
        state.shutdown();
    }
    state.initialized = false;
    state.snapshot.initialized = false;
    state.snapshot.transport_interfaces_ready = false;
}

}  // namespace

bool InitializeSteamBootstrap() {
    std::scoped_lock lock(detail::SteamBootstrapMutex());
    auto& state = detail::MutableSteamBootstrapState();
    if (state.initialized) {
        return true;
    }

    state.snapshot = SteamBootstrapSnapshot{};
    state.pending_events.clear();
    detail::SteamBootstrapConfiguration configuration;
    if (!detail::ReadSteamBootstrapConfiguration(
            GetHostProcessDirectory(),
            &configuration,
            &state.snapshot)) {
        if (state.snapshot.requested) {
            Log("Steam bootstrap: missing or invalid SDMOD_STEAM_APP_ID.");
        } else {
            Log("Steam bootstrap: not requested by launcher environment.");
        }
        return false;
    }
    state.snapshot.app_id = configuration.app_id;

    detail::LogSteamBootstrapConfiguration(configuration);

    if (!detail::LoadSteamApiModule(&state, configuration, GetHostProcessDirectory())) {
        state.snapshot.error_text = "steam_api.dll was not available.";
        state.snapshot.status_text = "Steam API DLL is missing.";
        return false;
    }

    if (!detail::LoadSteamApiExports(&state)) {
        Log("Steam bootstrap: steam_api.dll does not provide the required lobby and Networking Messages exports.");
        return false;
    }

    if (configuration.allow_restart_if_necessary) {
        if (state.restart_app_if_necessary(configuration.app_id)) {
            Log("Steam bootstrap: Steam requested a relaunch; injected staged launches must continue directly.");
            state.snapshot.error_text = "Steam requested relaunch through Steam.";
            state.snapshot.status_text = "Steam relaunch is unsupported from the injected loader.";
            return false;
        }
    } else {
        Log("Steam bootstrap: SteamAPI_RestartAppIfNecessary skipped for the staged injected-loader bootstrap.");
    }

    if (!state.init()) {
        Log("Steam bootstrap: SteamAPI_Init failed. Check Steam login, AppID ownership, process privilege, and steam_appid.txt.");
        state.snapshot.error_text =
            "SteamAPI_Init failed. Check Steam login, license, admin context, and steam_appid.txt.";
        state.snapshot.status_text = "Steam initialization failed.";
        return false;
    }

    state.initialized = true;
    state.snapshot.initialized = true;
    state.manual_dispatch_init();
    state.pipe = state.get_pipe();
    if (state.pipe == 0) {
        state.snapshot.error_text = "Steam did not provide a client callback pipe.";
        state.snapshot.status_text = "Steam callback dispatch unavailable.";
        ResetAfterFailedInitialization(state);
        return false;
    }

    auto* friends = state.steam_friends_v017();
    auto* matchmaking = state.steam_matchmaking_v009();
    auto* networking_messages = state.steam_networking_messages_v002();
    auto* user = state.steam_user_v023();
    auto* utils = state.steam_utils_v010();
    if (friends == nullptr || matchmaking == nullptr || networking_messages == nullptr ||
        user == nullptr || utils == nullptr) {
        Log("Steam bootstrap: required friends, matchmaking, Networking Messages, user, or utils interface unavailable.");
        state.snapshot.error_text = "Steam multiplayer interfaces were not available.";
        state.snapshot.status_text = "Steam multiplayer interfaces unavailable.";
        ResetAfterFailedInitialization(state);
        return false;
    }

    const auto* persona_name = state.friends_get_persona_name(friends);
    state.snapshot.transport_interfaces_ready = true;
    state.snapshot.local_steam_id = state.user_get_steam_id(user);
    state.snapshot.overlay_enabled = state.utils_is_overlay_enabled(utils);
    state.snapshot.persona_name = persona_name != nullptr ? persona_name : "";
    state.snapshot.error_text.clear();
    state.snapshot.status_text = "Steam API ready; multiplayer session idle.";
    PumpSteamCallbacks(state);

    std::ostringstream message;
    message << "Steam bootstrap ready. app_id=" << state.snapshot.app_id
            << " module=" << state.snapshot.module_path
            << " steam_id=" << state.snapshot.local_steam_id
            << " overlay=" << (state.snapshot.overlay_enabled ? 1 : 0)
            << " interfaces={friends_v017,matchmaking_v009,networking_messages_v002,user_v023,utils_v010}";
    Log(message.str());
    return true;
}

void ShutdownSteamBootstrap() {
    std::scoped_lock lock(detail::SteamBootstrapMutex());
    auto& state = detail::MutableSteamBootstrapState();
    if (state.initialized && state.shutdown != nullptr) {
        Log("Steam bootstrap: shutting down SteamAPI.");
        state.shutdown();
    }
    state = detail::SteamBootstrapState{};
}

void SteamBootstrapTick() {
    std::scoped_lock lock(detail::SteamBootstrapMutex());
    auto& state = detail::MutableSteamBootstrapState();
    if (!state.initialized || state.pipe == 0) {
        return;
    }
    PumpSteamCallbacks(state);
}

SteamBootstrapSnapshot GetSteamBootstrapSnapshot() {
    std::scoped_lock lock(detail::SteamBootstrapMutex());
    return detail::MutableSteamBootstrapState().snapshot;
}

std::vector<SteamEvent> DrainSteamEvents() {
    std::scoped_lock lock(detail::SteamBootstrapMutex());
    auto& events = detail::MutableSteamBootstrapState().pending_events;
    std::vector<SteamEvent> drained;
    drained.swap(events);
    return drained;
}

}  // namespace sdmod
