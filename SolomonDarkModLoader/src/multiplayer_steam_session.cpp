#include "multiplayer_steam_session.h"

#include "logger.h"
#include "mod_loader.h"
#include "multiplayer_local_transport.h"
#include "multiplayer_runtime_protocol.h"
#include "multiplayer_runtime_state.h"
#include "startup_status.h"
#include "steam_bootstrap.h"

#include <Windows.h>
#include <Shellapi.h>

#include <algorithm>
#include <array>
#include <charconv>
#include <cctype>
#include <cstdlib>
#include <cstring>
#include <random>
#include <sstream>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

namespace sdmod::multiplayer {
namespace {

constexpr const char* kTransportEnvironmentVariable = "SDMOD_MULTIPLAYER_TRANSPORT";
constexpr const char* kRoleEnvironmentVariable = "SDMOD_MULTIPLAYER_ROLE";
constexpr const char* kSessionModeEnvironmentVariable = "SDMOD_STEAM_SESSION_MODE";
constexpr const char* kLobbyIdEnvironmentVariable = "SDMOD_STEAM_LOBBY_ID";
constexpr const char* kManifestEnvironmentVariable = "SDMOD_MULTIPLAYER_MANIFEST_SHA256";
constexpr const char* kMaxParticipantsEnvironmentVariable = "SDMOD_MULTIPLAYER_MAX_PARTICIPANTS";
constexpr const char* kOpenInviteEnvironmentVariable = "SDMOD_STEAM_OPEN_INVITE";
constexpr const char* kLaunchTokenEnvironmentVariable = "SDMOD_LAUNCH_TOKEN";

constexpr const char* kLobbyProtocolKey = "sdmod_protocol";
constexpr const char* kLobbyManifestKey = "sdmod_manifest";
constexpr const char* kLobbyHostKey = "sdmod_host";
constexpr const char* kLobbyAppIdKey = "sdmod_app_id";
constexpr const char* kLobbyMaxParticipantsKey = "sdmod_max_players";
constexpr const char* kLobbyStateKey = "sdmod_state";
constexpr const char* kLobbyStateOpen = "open";
constexpr const char* kLobbyStateClosed = "closed";
constexpr const char* kMemberProtocolKey = "sdmod_protocol";
constexpr const char* kMemberManifestKey = "sdmod_manifest";

constexpr std::uint32_t kDefaultMaxParticipants = 4;
constexpr std::uint32_t kMaximumSupportedParticipants = 4;
constexpr std::uint64_t kHelloRetryIntervalMs = 1000;
constexpr std::uint64_t kAuthenticatedPeerTimeoutMs = 10000;
constexpr std::uint64_t kLobbyReconcileIntervalMs = 500;
constexpr std::uint64_t kRouteStatusIntervalMs = 1000;
constexpr std::uint64_t kSessionStatusWriteIntervalMs = 1000;
constexpr std::int32_t kReceiveBatchSize = 64;

enum class SteamSessionPhase {
    Disabled,
    WaitingForInvite,
    CreatingLobby,
    JoiningLobby,
    Handshaking,
    LobbyReady,
    Connected,
    Error,
};

const char* SteamSessionPhaseLabel(SteamSessionPhase phase) {
    switch (phase) {
    case SteamSessionPhase::WaitingForInvite:
        return "WaitingForInvite";
    case SteamSessionPhase::CreatingLobby:
        return "CreatingLobby";
    case SteamSessionPhase::JoiningLobby:
        return "JoiningLobby";
    case SteamSessionPhase::Handshaking:
        return "Handshaking";
    case SteamSessionPhase::LobbyReady:
        return "LobbyReady";
    case SteamSessionPhase::Connected:
        return "Connected";
    case SteamSessionPhase::Error:
        return "Error";
    case SteamSessionPhase::Disabled:
    default:
        return "Disabled";
    }
}

struct SteamSessionPeer {
    std::uint64_t steam_id = 0;
    std::uint64_t session_nonce = 0;
    std::uint64_t last_packet_ms = 0;
    bool authenticated = false;
    bool rejected = false;
    std::string display_name;
    SteamPeerNetworkStatus network_status;
};

struct SteamSessionState {
    bool configured = false;
    bool initialized = false;
    bool is_host = false;
    bool open_invite_dialog = true;
    bool invite_fallback_logged = false;
    bool invite_dialog_opened = false;
    bool overlay_enabled = false;
    SteamSessionPhase phase = SteamSessionPhase::Disabled;
    std::uint32_t app_id = 0;
    std::uint32_t max_participants = kDefaultMaxParticipants;
    std::uint32_t next_sequence = 1;
    std::uint64_t local_steam_id = 0;
    std::uint64_t lobby_id = 0;
    std::uint64_t desired_lobby_id = 0;
    std::uint64_t host_steam_id = 0;
    std::uint64_t pending_api_call = 0;
    std::uint64_t local_session_nonce = 0;
    std::uint64_t last_hello_send_ms = 0;
    std::uint64_t last_lobby_reconcile_ms = 0;
    std::uint64_t last_route_status_ms = 0;
    std::uint64_t last_status_write_ms = 0;
    std::array<std::uint8_t, 32> manifest_sha256{};
    std::string manifest_sha256_text;
    std::string launch_token;
    std::string last_status_signature;
    std::string error_text;
    std::unordered_set<std::uint64_t> lobby_members;
    std::unordered_map<std::uint64_t, SteamSessionPeer> peers;
};

SteamSessionState g_session;

void RemoveAllPeers();

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

std::string TrimAscii(std::string value) {
    const auto is_space = [](unsigned char ch) { return std::isspace(ch) != 0; };
    while (!value.empty() && is_space(static_cast<unsigned char>(value.front()))) {
        value.erase(value.begin());
    }
    while (!value.empty() && is_space(static_cast<unsigned char>(value.back()))) {
        value.pop_back();
    }
    return value;
}

std::string ToLowerAscii(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char ch) {
        return static_cast<char>(std::tolower(ch));
    });
    return value;
}

bool ReadBooleanEnvironmentVariable(const char* name, bool default_value) {
    const auto value = ToLowerAscii(TrimAscii(ReadEnvironmentVariable(name)));
    if (value.empty()) {
        return default_value;
    }
    if (value == "1" || value == "true" || value == "yes" || value == "on") {
        return true;
    }
    if (value == "0" || value == "false" || value == "no" || value == "off") {
        return false;
    }
    return default_value;
}

bool TryParseUnsigned64(const std::string& text, std::uint64_t* value) {
    if (value == nullptr || text.empty()) {
        return false;
    }
    std::uint64_t parsed = 0;
    const auto result = std::from_chars(
        text.data(),
        text.data() + text.size(),
        parsed,
        10);
    if (result.ec != std::errc{} || result.ptr != text.data() + text.size()) {
        return false;
    }
    *value = parsed;
    return true;
}

bool TryParseLobbyIdFromConnectString(
    const std::string& connect_string,
    std::uint64_t* lobby_id) {
    std::istringstream stream(connect_string);
    std::string command;
    std::string lobby_text;
    std::string trailing;
    return (stream >> command >> lobby_text) &&
           !(stream >> trailing) &&
           command == "+connect_lobby" &&
           TryParseUnsigned64(lobby_text, lobby_id) &&
           *lobby_id != 0;
}

std::uint32_t ReadMaxParticipants() {
    std::uint64_t parsed = 0;
    if (!TryParseUnsigned64(
            TrimAscii(ReadEnvironmentVariable(kMaxParticipantsEnvironmentVariable)),
            &parsed)) {
        return kDefaultMaxParticipants;
    }
    return static_cast<std::uint32_t>((std::clamp<std::uint64_t>)(
        parsed,
        2,
        kMaximumSupportedParticipants));
}

int HexNibble(char ch) {
    if (ch >= '0' && ch <= '9') {
        return ch - '0';
    }
    if (ch >= 'a' && ch <= 'f') {
        return 10 + ch - 'a';
    }
    if (ch >= 'A' && ch <= 'F') {
        return 10 + ch - 'A';
    }
    return -1;
}

bool ParseSha256(
    const std::string& text,
    std::array<std::uint8_t, 32>* digest) {
    if (digest == nullptr || text.size() != digest->size() * 2) {
        return false;
    }
    for (std::size_t index = 0; index < digest->size(); ++index) {
        const int high = HexNibble(text[index * 2]);
        const int low = HexNibble(text[index * 2 + 1]);
        if (high < 0 || low < 0) {
            return false;
        }
        (*digest)[index] = static_cast<std::uint8_t>((high << 4) | low);
    }
    return true;
}

std::uint64_t ParseCommandLineLobbyId() {
    int argument_count = 0;
    auto** arguments = CommandLineToArgvW(GetCommandLineW(), &argument_count);
    if (arguments == nullptr) {
        return 0;
    }
    std::uint64_t lobby_id = 0;
    for (int index = 0; index + 1 < argument_count; ++index) {
        if (_wcsicmp(arguments[index], L"+connect_lobby") != 0) {
            continue;
        }
        const auto* first = arguments[index + 1];
        const auto* last = first + wcslen(first);
        wchar_t* end = nullptr;
        lobby_id = _wcstoui64(first, &end, 10);
        if (lobby_id != 0 && end == last) {
            break;
        }
        lobby_id = 0;
    }
    LocalFree(arguments);
    return lobby_id;
}

std::uint64_t GenerateSessionNonce() {
    std::random_device random;
    std::uint64_t nonce =
        (static_cast<std::uint64_t>(random()) << 32) ^
        static_cast<std::uint64_t>(random()) ^
        GetTickCount64() ^
        (g_session.local_steam_id << 1);
    return nonce != 0 ? nonce : 1;
}

bool HasProtocolMagic(const PacketHeader& header) {
    return header.magic[0] == kProtocolMagic[0] &&
           header.magic[1] == kProtocolMagic[1] &&
           header.magic[2] == kProtocolMagic[2] &&
           header.magic[3] == kProtocolMagic[3];
}

template <typename Packet>
bool CopyNetworkPacket(const SteamNetworkMessage& message, Packet* packet) {
    if (packet == nullptr || message.payload.size() != sizeof(Packet)) {
        return false;
    }
    std::memcpy(packet, message.payload.data(), sizeof(Packet));
    return true;
}

std::string PacketDisplayName(const char* name, std::size_t capacity) {
    std::size_t length = 0;
    while (length < capacity && name[length] != '\0') {
        ++length;
    }
    return std::string(name, length);
}

void CopyDisplayName(const std::string& name, char* target, std::size_t capacity) {
    if (target == nullptr || capacity == 0) {
        return;
    }
    std::memset(target, 0, capacity);
    const auto count = (std::min)(name.size(), capacity - 1);
    std::memcpy(target, name.data(), count);
}

const char* HelloResultLabel(SessionHelloResultCode result) {
    switch (result) {
    case SessionHelloResultCode::Accepted:
        return "accepted";
    case SessionHelloResultCode::ProtocolMismatch:
        return "protocol_mismatch";
    case SessionHelloResultCode::ManifestMismatch:
        return "manifest_mismatch";
    case SessionHelloResultCode::LobbyMismatch:
        return "lobby_mismatch";
    case SessionHelloResultCode::IdentityMismatch:
        return "identity_mismatch";
    case SessionHelloResultCode::LobbyFull:
        return "lobby_full";
    case SessionHelloResultCode::HostMismatch:
        return "host_mismatch";
    case SessionHelloResultCode::CapabilityMismatch:
        return "capability_mismatch";
    }
    return "unknown";
}

void SetError(std::string message, bool leave_lobby) {
    Log("Steam multiplayer session error: " + message);
    g_session.error_text = std::move(message);
    g_session.phase = SteamSessionPhase::Error;
    RemoveAllPeers();
    SteamSetRichPresence("connect", nullptr);
    SteamSetRichPresence("status", nullptr);
    if (leave_lobby && g_session.lobby_id != 0) {
        SteamLeaveLobby(g_session.lobby_id);
        g_session.lobby_id = 0;
        g_session.lobby_members.clear();
    }
}

bool IsLobbyMember(std::uint64_t steam_id) {
    return steam_id != 0 &&
           g_session.lobby_members.find(steam_id) != g_session.lobby_members.end();
}

void RemovePeer(std::uint64_t steam_id) {
    if (steam_id == 0) {
        return;
    }
    UnregisterSteamGameplayPeer(steam_id);
    SteamCloseNetworkSession(steam_id);
    g_session.peers.erase(steam_id);
}

void RestartClientHostHandshake(
    std::uint64_t host_steam_id,
    const char* reason) {
    if (g_session.is_host ||
        host_steam_id == 0 ||
        host_steam_id != g_session.host_steam_id ||
        !IsLobbyMember(host_steam_id)) {
        return;
    }
    RemovePeer(host_steam_id);
    auto& peer = g_session.peers[host_steam_id];
    peer.steam_id = host_steam_id;
    peer.display_name = SteamGetFriendPersonaName(host_steam_id);
    g_session.local_session_nonce = GenerateSessionNonce();
    g_session.last_hello_send_ms = 0;
    g_session.phase = SteamSessionPhase::Handshaking;
    Log(
        "Steam multiplayer restarting host handshake. reason=" +
        std::string(reason != nullptr ? reason : "unknown"));
}

void RemoveAllPeers() {
    std::vector<std::uint64_t> peer_ids;
    peer_ids.reserve(g_session.peers.size());
    for (const auto& [steam_id, peer] : g_session.peers) {
        (void)peer;
        peer_ids.push_back(steam_id);
    }
    for (const auto steam_id : peer_ids) {
        RemovePeer(steam_id);
    }
}

bool SetHostLobbyMetadata() {
    const auto lobby_id = g_session.lobby_id;
    return SteamSetLobbyData(lobby_id, kLobbyProtocolKey, std::to_string(kProtocolVersion).c_str()) &&
           SteamSetLobbyData(lobby_id, kLobbyManifestKey, g_session.manifest_sha256_text.c_str()) &&
           SteamSetLobbyData(lobby_id, kLobbyHostKey, std::to_string(g_session.local_steam_id).c_str()) &&
           SteamSetLobbyData(lobby_id, kLobbyAppIdKey, std::to_string(g_session.app_id).c_str()) &&
           SteamSetLobbyData(
               lobby_id,
               kLobbyMaxParticipantsKey,
               std::to_string(g_session.max_participants).c_str()) &&
           SteamSetLobbyData(lobby_id, kLobbyStateKey, kLobbyStateOpen) &&
           SteamSetLobbyJoinable(lobby_id, true);
}

void SetLocalLobbyMemberMetadata() {
    if (g_session.lobby_id == 0) {
        return;
    }
    SteamSetLobbyMemberData(
        g_session.lobby_id,
        kMemberProtocolKey,
        std::to_string(kProtocolVersion).c_str());
    SteamSetLobbyMemberData(
        g_session.lobby_id,
        kMemberManifestKey,
        g_session.manifest_sha256_text.c_str());
}

bool ValidateJoinedLobby(std::string* error_message) {
    const auto owner = SteamGetLobbyOwner(g_session.lobby_id);
    std::uint64_t advertised_host = 0;
    std::uint64_t advertised_protocol = 0;
    std::uint64_t advertised_app_id = 0;
    std::uint64_t advertised_max = 0;
    if (owner == 0 ||
        !TryParseUnsigned64(SteamGetLobbyData(g_session.lobby_id, kLobbyHostKey), &advertised_host) ||
        owner != advertised_host) {
        *error_message = "Lobby owner metadata does not match the Steam lobby owner.";
        return false;
    }
    if (!TryParseUnsigned64(
            SteamGetLobbyData(g_session.lobby_id, kLobbyProtocolKey),
            &advertised_protocol) ||
        advertised_protocol != kProtocolVersion) {
        *error_message = "Lobby uses a different multiplayer protocol version.";
        return false;
    }
    if (SteamGetLobbyData(g_session.lobby_id, kLobbyManifestKey) !=
        g_session.manifest_sha256_text) {
        *error_message = "Lobby mod/game build fingerprint does not match.";
        return false;
    }
    if (!TryParseUnsigned64(
            SteamGetLobbyData(g_session.lobby_id, kLobbyAppIdKey),
            &advertised_app_id) ||
        advertised_app_id != g_session.app_id) {
        *error_message = "Lobby Steam AppID does not match this launch.";
        return false;
    }
    if (!TryParseUnsigned64(
            SteamGetLobbyData(g_session.lobby_id, kLobbyMaxParticipantsKey),
            &advertised_max) ||
        advertised_max < 2 ||
        advertised_max > kMaximumSupportedParticipants) {
        *error_message = "Lobby participant limit is unsupported.";
        return false;
    }
    if (SteamGetLobbyData(g_session.lobby_id, kLobbyStateKey) != kLobbyStateOpen) {
        *error_message = "Lobby is no longer accepting players.";
        return false;
    }
    g_session.host_steam_id = owner;
    g_session.max_participants = static_cast<std::uint32_t>(advertised_max);
    return true;
}

void ReconcileLobbyMembers(std::uint64_t now_ms) {
    if (g_session.lobby_id == 0) {
        return;
    }
    const auto members = SteamGetLobbyMembers(g_session.lobby_id);
    std::unordered_set<std::uint64_t> current(members.begin(), members.end());
    if (current.find(g_session.local_steam_id) == current.end()) {
        SetError("Local Steam user is no longer a lobby member.", false);
        return;
    }
    const auto owner = SteamGetLobbyOwner(g_session.lobby_id);
    if ((g_session.is_host && owner != g_session.local_steam_id) ||
        (!g_session.is_host && owner != g_session.host_steam_id)) {
        SetError("Steam lobby ownership changed; host migration is not supported.", true);
        return;
    }

    std::vector<std::uint64_t> removed;
    for (const auto& [steam_id, peer] : g_session.peers) {
        (void)peer;
        if (current.find(steam_id) == current.end()) {
            removed.push_back(steam_id);
        }
    }
    for (const auto steam_id : removed) {
        RemovePeer(steam_id);
    }

    for (const auto steam_id : current) {
        if (steam_id == g_session.local_steam_id ||
            (!g_session.is_host && steam_id != g_session.host_steam_id)) {
            continue;
        }
        auto& peer = g_session.peers[steam_id];
        peer.steam_id = steam_id;
        if (peer.display_name.empty()) {
            peer.display_name = SteamGetFriendPersonaName(steam_id);
        }
    }
    g_session.lobby_members = std::move(current);
    g_session.last_lobby_reconcile_ms = now_ms;
}

void PublishSessionRuntime(std::uint64_t now_ms) {
    bool any_relayed = false;
    std::int32_t maximum_ping = 0;
    std::uint32_t authenticated_count = 0;
    for (const auto& [steam_id, peer] : g_session.peers) {
        (void)steam_id;
        if (!peer.authenticated) {
            continue;
        }
        authenticated_count += 1;
        any_relayed = any_relayed || peer.network_status.using_relay;
        maximum_ping = (std::max)(maximum_ping, peer.network_status.ping_ms);
    }

    std::ostringstream status;
    switch (g_session.phase) {
    case SteamSessionPhase::WaitingForInvite:
        status << "Steam multiplayer waiting for a lobby invite.";
        break;
    case SteamSessionPhase::CreatingLobby:
        status << "Creating friends-only Steam lobby.";
        break;
    case SteamSessionPhase::JoiningLobby:
        status << "Joining Steam lobby " << g_session.desired_lobby_id << '.';
        break;
    case SteamSessionPhase::Handshaking:
        status << "Steam lobby " << g_session.lobby_id
               << " joined; validating host build identity.";
        break;
    case SteamSessionPhase::LobbyReady:
        status << "Steam lobby " << g_session.lobby_id
               << " ready for invites; authenticated peers="
               << authenticated_count;
        break;
    case SteamSessionPhase::Connected:
        status << "Steam lobby " << g_session.lobby_id
               << " connected; authenticated peers=" << authenticated_count
               << " route=" << (any_relayed ? "SDR" : "direct-or-pending")
               << " ping_ms=" << maximum_ping;
        break;
    case SteamSessionPhase::Error:
        status << "Steam multiplayer error: " << g_session.error_text;
        break;
    case SteamSessionPhase::Disabled:
    default:
        status << "Steam multiplayer disabled.";
        break;
    }
    const auto status_text = status.str();

    UpdateRuntimeState([&](RuntimeState& state) {
        state.session_transport = SessionTransportKind::Steam;
        state.session_is_host = g_session.is_host;
        state.steam_app_id = g_session.app_id;
        state.steam_lobby_id = g_session.lobby_id;
        state.steam_host_id = g_session.host_steam_id;
        state.session_max_participants = g_session.max_participants;
        state.authenticated_peer_count = authenticated_count;
        state.steam_route_relayed = any_relayed;
        state.steam_route_ping_ms = maximum_ping;
        state.multiplayer_manifest_sha256 = g_session.manifest_sha256_text;
        state.transport_ready =
            g_session.phase == SteamSessionPhase::LobbyReady ||
            g_session.phase == SteamSessionPhase::Connected;
        switch (g_session.phase) {
        case SteamSessionPhase::WaitingForInvite:
            state.session_status = SessionStatus::WaitingForInvite;
            break;
        case SteamSessionPhase::CreatingLobby:
            state.session_status = SessionStatus::CreatingLobby;
            break;
        case SteamSessionPhase::JoiningLobby:
            state.session_status = SessionStatus::JoiningLobby;
            break;
        case SteamSessionPhase::Handshaking:
            state.session_status = SessionStatus::Handshaking;
            break;
        case SteamSessionPhase::LobbyReady:
        case SteamSessionPhase::Connected:
            state.session_status = SessionStatus::Ready;
            break;
        case SteamSessionPhase::Error:
            state.session_status = SessionStatus::Error;
            break;
        case SteamSessionPhase::Disabled:
        default:
            state.session_status = SessionStatus::Idle;
            break;
        }

        state.status_text = status_text;
        state.error_text = g_session.phase == SteamSessionPhase::Error
            ? g_session.error_text
            : std::string{};

        auto* local = UpsertLocalParticipant(state);
        if (local != nullptr) {
            local->steam_id = g_session.local_steam_id;
            local->transport_connected = state.transport_ready;
            local->transport_using_relay = any_relayed;
            local->last_packet_ms = now_ms;
        }
        for (const auto& [steam_id, peer] : g_session.peers) {
            auto* participant = FindParticipant(state, steam_id);
            if (participant == nullptr && peer.authenticated) {
                participant = UpsertRemoteParticipant(
                    state,
                    steam_id,
                    ParticipantControllerKind::Native);
            }
            if (participant == nullptr) {
                continue;
            }
            participant->steam_id = steam_id;
            participant->transport_connected = peer.authenticated;
            participant->transport_using_relay = peer.network_status.using_relay;
            if (!peer.display_name.empty() &&
                (participant->name.empty() || participant->name == "Remote Wizard")) {
                participant->name = peer.display_name;
            }
        }
    });

    std::ostringstream signature;
    signature << SteamSessionPhaseLabel(g_session.phase) << '|'
              << g_session.lobby_id << '|'
              << g_session.host_steam_id << '|'
              << authenticated_count << '|'
              << (g_session.overlay_enabled ? 1 : 0) << '|'
              << (g_session.invite_dialog_opened ? 1 : 0) << '|'
              << (any_relayed ? 1 : 0) << '|'
              << maximum_ping << '|'
              << g_session.error_text;
    const auto status_signature = signature.str();
    if (status_signature != g_session.last_status_signature ||
        g_session.last_status_write_ms == 0 ||
        now_ms >= g_session.last_status_write_ms +
            kSessionStatusWriteIntervalMs) {
        MultiplayerSessionStatusSnapshot snapshot;
        snapshot.launch_token = g_session.launch_token;
        snapshot.enabled = g_session.configured;
        snapshot.is_host = g_session.is_host;
        snapshot.phase = SteamSessionPhaseLabel(g_session.phase);
        snapshot.app_id = g_session.app_id;
        snapshot.lobby_id = g_session.lobby_id;
        snapshot.host_steam_id = g_session.host_steam_id;
        snapshot.max_participants = g_session.max_participants;
        snapshot.authenticated_peer_count = authenticated_count;
        snapshot.overlay_enabled = g_session.overlay_enabled;
        snapshot.invite_dialog_opened = g_session.invite_dialog_opened;
        snapshot.route_relayed = any_relayed;
        snapshot.route_ping_ms = maximum_ping;
        snapshot.status_text = status_text;
        snapshot.error_text = g_session.error_text;
        WriteMultiplayerSessionStatus(
            GetStageRuntimeDirectory(),
            snapshot);
        g_session.last_status_signature = status_signature;
        g_session.last_status_write_ms = now_ms;
    }
}

bool BeginJoinLobby(std::uint64_t lobby_id) {
    if (lobby_id == 0 || g_session.is_host) {
        return false;
    }
    if (g_session.lobby_id != 0) {
        SteamLeaveLobby(g_session.lobby_id);
    }
    RemoveAllPeers();
    g_session.lobby_members.clear();
    g_session.lobby_id = 0;
    g_session.host_steam_id = 0;
    g_session.desired_lobby_id = lobby_id;
    g_session.local_session_nonce = GenerateSessionNonce();
    g_session.pending_api_call = SteamJoinLobby(lobby_id);
    if (g_session.pending_api_call == 0) {
        SetError("Steam rejected the JoinLobby request before it was queued.", false);
        return false;
    }
    g_session.phase = SteamSessionPhase::JoiningLobby;
    g_session.error_text.clear();
    Log("Steam multiplayer joining lobby_id=" + std::to_string(lobby_id));
    return true;
}

void RefreshOverlayAndInviteDialog() {
    g_session.overlay_enabled = SteamIsOverlayEnabled();
    if (!g_session.is_host ||
        !g_session.open_invite_dialog ||
        g_session.lobby_id == 0 ||
        g_session.invite_dialog_opened) {
        return;
    }
    if (g_session.overlay_enabled) {
        SteamOpenLobbyInviteDialog(g_session.lobby_id);
        g_session.invite_dialog_opened = true;
        Log("Steam multiplayer opened the lobby invite dialog in the Steam overlay.");
        return;
    }
    if (!g_session.invite_fallback_logged) {
        g_session.invite_fallback_logged = true;
        Log(
            "Steam multiplayer lobby is inviteable, but the overlay is not active. "
            "Invite or join through the Steam Friends window, or share the lobby id.");
    }
}

void OnHostLobbyReady(std::uint64_t lobby_id, std::uint64_t now_ms) {
    if (g_session.lobby_id == lobby_id &&
        (g_session.phase == SteamSessionPhase::LobbyReady ||
         g_session.phase == SteamSessionPhase::Connected)) {
        return;
    }
    if (lobby_id == 0 || SteamGetLobbyOwner(lobby_id) != g_session.local_steam_id) {
        SetError("Created lobby does not report the local Steam user as owner.", true);
        return;
    }
    g_session.lobby_id = lobby_id;
    g_session.host_steam_id = g_session.local_steam_id;
    g_session.pending_api_call = 0;
    if (!SetHostLobbyMetadata()) {
        SetError("Could not publish required build metadata to the Steam lobby.", true);
        return;
    }
    SetLocalLobbyMemberMetadata();
    ReconcileLobbyMembers(now_ms);
    if (g_session.phase == SteamSessionPhase::Error) {
        return;
    }
    g_session.phase = SteamSessionPhase::LobbyReady;
    SteamSetRichPresence("status", "Hosting Solomon Dark multiplayer");
    const auto connect = "+connect_lobby " + std::to_string(lobby_id);
    SteamSetRichPresence("connect", connect.c_str());
    RefreshOverlayAndInviteDialog();
    Log("Steam multiplayer lobby ready. lobby_id=" + std::to_string(lobby_id));
}

void OnClientLobbyEntered(std::uint64_t lobby_id, std::uint64_t now_ms) {
    g_session.lobby_id = lobby_id;
    g_session.pending_api_call = 0;
    std::string error;
    if (!ValidateJoinedLobby(&error)) {
        SetError(std::move(error), true);
        return;
    }
    SetLocalLobbyMemberMetadata();
    ReconcileLobbyMembers(now_ms);
    if (g_session.phase == SteamSessionPhase::Error) {
        return;
    }
    g_session.phase = SteamSessionPhase::Handshaking;
    g_session.last_hello_send_ms = 0;
    SteamSetRichPresence("status", "Joining Solomon Dark multiplayer");
    Log(
        "Steam multiplayer lobby entered. lobby_id=" + std::to_string(lobby_id) +
        " host_steam_id=" + std::to_string(g_session.host_steam_id));
}

void HandleSteamEvent(const SteamEvent& event, std::uint64_t now_ms) {
    switch (event.kind) {
    case SteamEventKind::LobbyCreated:
        if (!g_session.is_host ||
            (event.api_call != 0 && event.api_call != g_session.pending_api_call)) {
            return;
        }
        if (!event.success) {
            SetError(
                "CreateLobby failed with Steam result " +
                    std::to_string(event.result_code) + '.',
                false);
            return;
        }
        OnHostLobbyReady(event.lobby_id, now_ms);
        return;
    case SteamEventKind::LobbyEntered:
        if (!event.success) {
            if (!g_session.is_host &&
                (event.api_call == 0 || event.api_call == g_session.pending_api_call)) {
                SetError(
                    "JoinLobby failed with response " +
                        std::to_string(event.result_code) + '.',
                    false);
            }
            return;
        }
        if (g_session.is_host) {
            if (g_session.phase == SteamSessionPhase::CreatingLobby ||
                event.lobby_id == g_session.lobby_id) {
                OnHostLobbyReady(event.lobby_id, now_ms);
            }
        } else if (event.lobby_id == g_session.desired_lobby_id &&
                   (event.api_call == 0 || event.api_call == g_session.pending_api_call)) {
            OnClientLobbyEntered(event.lobby_id, now_ms);
        }
        return;
    case SteamEventKind::LobbyJoinRequested:
        if (!g_session.is_host && event.lobby_id != 0) {
            BeginJoinLobby(event.lobby_id);
        }
        return;
    case SteamEventKind::RichPresenceJoinRequested: {
        std::uint64_t lobby_id = 0;
        if (!g_session.is_host &&
            TryParseLobbyIdFromConnectString(event.connect_string, &lobby_id)) {
            BeginJoinLobby(lobby_id);
        }
        return;
    }
    case SteamEventKind::LobbyMemberChanged:
        if (event.lobby_id == g_session.lobby_id) {
            ReconcileLobbyMembers(now_ms);
        }
        return;
    case SteamEventKind::LobbyDataUpdated:
        if (!g_session.is_host && event.lobby_id == g_session.lobby_id) {
            std::string error;
            if (!ValidateJoinedLobby(&error)) {
                SetError(std::move(error), true);
            }
        }
        return;
    case SteamEventKind::NetworkSessionRequested:
        if (IsLobbyMember(event.user_id)) {
            SteamAcceptNetworkSession(event.user_id);
        } else if (event.user_id != 0) {
            SteamCloseNetworkSession(event.user_id);
        }
        return;
    case SteamEventKind::NetworkSessionFailed:
        if (event.user_id == 0 || !IsLobbyMember(event.user_id)) {
            return;
        }
        if (!g_session.is_host && event.user_id == g_session.host_steam_id) {
            RestartClientHostHandshake(event.user_id, "network_session_failed");
        } else {
            RemovePeer(event.user_id);
        }
        return;
    case SteamEventKind::LobbyInviteReceived:
        if (!g_session.is_host &&
            g_session.phase == SteamSessionPhase::WaitingForInvite &&
            event.lobby_id != 0) {
            BeginJoinLobby(event.lobby_id);
        }
        return;
    }
}

bool SendHelloAck(
    std::uint64_t remote_steam_id,
    std::uint64_t session_nonce,
    SessionHelloResultCode result) {
    SessionHelloAckPacket packet{};
    packet.header = MakePacketHeader(PacketKind::SessionHelloAck, g_session.next_sequence++);
    packet.lobby_id = g_session.lobby_id;
    packet.authority_participant_id = g_session.local_steam_id;
    packet.target_participant_id = remote_steam_id;
    packet.target_steam_id = remote_steam_id;
    packet.session_nonce = session_nonce;
    packet.capabilities = kRequiredSessionCapabilities;
    packet.result_code = static_cast<std::uint8_t>(result);
    packet.authority_role = static_cast<std::uint8_t>(SessionPeerRole::Host);
    packet.max_participants = static_cast<std::uint8_t>(g_session.max_participants);
    std::memcpy(
        packet.manifest_sha256,
        g_session.manifest_sha256.data(),
        g_session.manifest_sha256.size());
    return SteamSendNetworkMessage(
        remote_steam_id,
        &packet,
        sizeof(packet),
        SteamNetworkSendMode::ReliableNoNagle);
}

void HandleSessionHello(
    const SteamNetworkMessage& message,
    const SessionHelloPacket& packet,
    bool protocol_matches,
    std::uint64_t now_ms) {
    if (!g_session.is_host ||
        (g_session.phase != SteamSessionPhase::LobbyReady &&
         g_session.phase != SteamSessionPhase::Connected)) {
        return;
    }
    SessionHelloResultCode result = SessionHelloResultCode::Accepted;
    if (!protocol_matches) {
        result = SessionHelloResultCode::ProtocolMismatch;
    } else if (!IsLobbyMember(message.sender_steam_id) ||
               packet.lobby_id != g_session.lobby_id) {
        result = SessionHelloResultCode::LobbyMismatch;
    } else if (packet.participant_id != message.sender_steam_id ||
               packet.steam_id != message.sender_steam_id ||
               packet.session_nonce == 0 ||
               packet.role != static_cast<std::uint8_t>(SessionPeerRole::Client)) {
        result = SessionHelloResultCode::IdentityMismatch;
    } else if (packet.host_steam_id != g_session.local_steam_id) {
        result = SessionHelloResultCode::HostMismatch;
    } else if (packet.app_id != g_session.app_id) {
        result = SessionHelloResultCode::LobbyMismatch;
    } else if ((packet.capabilities & kRequiredSessionCapabilities) !=
               kRequiredSessionCapabilities) {
        result = SessionHelloResultCode::CapabilityMismatch;
    } else if (std::memcmp(
                   packet.manifest_sha256,
                   g_session.manifest_sha256.data(),
                   g_session.manifest_sha256.size()) != 0) {
        result = SessionHelloResultCode::ManifestMismatch;
    } else {
        std::uint32_t authenticated_count = 1;
        for (const auto& [steam_id, peer] : g_session.peers) {
            if (steam_id != message.sender_steam_id && peer.authenticated) {
                authenticated_count += 1;
            }
        }
        if (authenticated_count >= g_session.max_participants) {
            result = SessionHelloResultCode::LobbyFull;
        }
    }

    auto& peer = g_session.peers[message.sender_steam_id];
    peer.steam_id = message.sender_steam_id;
    peer.session_nonce = packet.session_nonce;
    peer.last_packet_ms = now_ms;
    peer.display_name = PacketDisplayName(packet.display_name, sizeof(packet.display_name));
    if (result == SessionHelloResultCode::Accepted) {
        peer.authenticated = true;
        peer.rejected = false;
        SteamAcceptNetworkSession(message.sender_steam_id);
        RegisterSteamGameplayPeer(message.sender_steam_id, false);
        g_session.phase = SteamSessionPhase::Connected;
    } else {
        peer.authenticated = false;
        peer.rejected = true;
    }
    SendHelloAck(message.sender_steam_id, packet.session_nonce, result);
    Log(
        "Steam multiplayer hello result. steam_id=" +
        std::to_string(message.sender_steam_id) +
        " result=" + HelloResultLabel(result));
}

void SendClientHello(std::uint64_t now_ms) {
    if (g_session.is_host ||
        g_session.phase != SteamSessionPhase::Handshaking ||
        g_session.host_steam_id == 0 ||
        (g_session.last_hello_send_ms != 0 &&
         now_ms < g_session.last_hello_send_ms + kHelloRetryIntervalMs)) {
        return;
    }
    SessionHelloPacket packet{};
    packet.header = MakePacketHeader(PacketKind::SessionHello, g_session.next_sequence++);
    packet.lobby_id = g_session.lobby_id;
    packet.participant_id = g_session.local_steam_id;
    packet.steam_id = g_session.local_steam_id;
    packet.host_steam_id = g_session.host_steam_id;
    packet.session_nonce = g_session.local_session_nonce;
    packet.app_id = g_session.app_id;
    packet.capabilities = kRequiredSessionCapabilities;
    packet.role = static_cast<std::uint8_t>(SessionPeerRole::Client);
    CopyDisplayName(
        GetSteamBootstrapSnapshot().persona_name,
        packet.display_name,
        sizeof(packet.display_name));
    std::memcpy(
        packet.manifest_sha256,
        g_session.manifest_sha256.data(),
        g_session.manifest_sha256.size());
    SteamSendNetworkMessage(
        g_session.host_steam_id,
        &packet,
        sizeof(packet),
        SteamNetworkSendMode::ReliableNoNagle);
    g_session.last_hello_send_ms = now_ms;
}

void HandleSessionHelloAck(
    const SteamNetworkMessage& message,
    const SessionHelloAckPacket& packet,
    std::uint64_t now_ms) {
    if (g_session.is_host ||
        g_session.phase != SteamSessionPhase::Handshaking ||
        message.sender_steam_id != g_session.host_steam_id ||
        packet.lobby_id != g_session.lobby_id ||
        packet.authority_participant_id != g_session.host_steam_id ||
        packet.target_participant_id != g_session.local_steam_id ||
        packet.target_steam_id != g_session.local_steam_id ||
        packet.session_nonce != g_session.local_session_nonce ||
        packet.authority_role != static_cast<std::uint8_t>(SessionPeerRole::Host)) {
        return;
    }
    const auto result = static_cast<SessionHelloResultCode>(packet.result_code);
    if (result != SessionHelloResultCode::Accepted) {
        SetError(
            std::string("Host rejected session handshake: ") +
                HelloResultLabel(result) + '.',
            true);
        return;
    }
    if ((packet.capabilities & kRequiredSessionCapabilities) !=
            kRequiredSessionCapabilities ||
        std::memcmp(
            packet.manifest_sha256,
            g_session.manifest_sha256.data(),
            g_session.manifest_sha256.size()) != 0 ||
        packet.max_participants != g_session.max_participants) {
        SetError("Host acknowledgement changed session identity data.", true);
        return;
    }

    auto& peer = g_session.peers[message.sender_steam_id];
    peer.steam_id = message.sender_steam_id;
    peer.session_nonce = packet.session_nonce;
    peer.last_packet_ms = now_ms;
    peer.authenticated = true;
    peer.rejected = false;
    if (peer.display_name.empty()) {
        peer.display_name = SteamGetFriendPersonaName(message.sender_steam_id);
    }
    RegisterSteamGameplayPeer(message.sender_steam_id, true);
    g_session.phase = SteamSessionPhase::Connected;
    SteamSetRichPresence("status", "Playing Solomon Dark multiplayer");
    Log(
        "Steam multiplayer host handshake accepted. host_steam_id=" +
        std::to_string(message.sender_steam_id));
}

void HandleSessionGoodbye(
    const SteamNetworkMessage& message,
    const SessionGoodbyePacket& packet) {
    if (packet.lobby_id != g_session.lobby_id ||
        packet.steam_id != message.sender_steam_id ||
        packet.participant_id != message.sender_steam_id) {
        return;
    }
    RemovePeer(message.sender_steam_id);
    if (!g_session.is_host && message.sender_steam_id == g_session.host_steam_id) {
        SetError("The Steam lobby host ended the multiplayer session.", true);
    }
}

void PumpNetworkMessages(std::uint64_t now_ms) {
    for (auto& message : SteamReceiveNetworkMessages(0, kReceiveBatchSize)) {
        if (!IsLobbyMember(message.sender_steam_id) ||
            message.payload.size() < sizeof(PacketHeader)) {
            SteamCloseNetworkSession(message.sender_steam_id);
            continue;
        }
        PacketHeader header{};
        std::memcpy(&header, message.payload.data(), sizeof(header));
        if (!HasProtocolMagic(header)) {
            continue;
        }
        const auto kind = static_cast<PacketKind>(header.kind);
        if (kind == PacketKind::SessionHello) {
            SessionHelloPacket packet{};
            if (CopyNetworkPacket(message, &packet)) {
                HandleSessionHello(
                    message,
                    packet,
                    header.version == kProtocolVersion,
                    now_ms);
            }
            continue;
        }
        if (!IsValidPacketHeader(header)) {
            continue;
        }
        if (kind == PacketKind::SessionHelloAck) {
            SessionHelloAckPacket packet{};
            if (CopyNetworkPacket(message, &packet)) {
                HandleSessionHelloAck(message, packet, now_ms);
            }
            continue;
        }
        if (kind == PacketKind::SessionGoodbye) {
            SessionGoodbyePacket packet{};
            if (CopyNetworkPacket(message, &packet)) {
                HandleSessionGoodbye(message, packet);
            }
            continue;
        }

        const auto peer_it = g_session.peers.find(message.sender_steam_id);
        if (peer_it == g_session.peers.end() || !peer_it->second.authenticated) {
            continue;
        }
        peer_it->second.last_packet_ms = now_ms;
        SubmitSteamGameplayPacket(
            message.sender_steam_id,
            message.payload.data(),
            message.payload.size(),
            now_ms);
    }
}

void ExpireInactivePeers(std::uint64_t now_ms) {
    std::vector<std::uint64_t> expired;
    for (const auto& [steam_id, peer] : g_session.peers) {
        if (peer.authenticated &&
            peer.last_packet_ms != 0 &&
            now_ms >= peer.last_packet_ms &&
            now_ms - peer.last_packet_ms >= kAuthenticatedPeerTimeoutMs) {
            expired.push_back(steam_id);
        }
    }

    for (const auto steam_id : expired) {
        if (!g_session.is_host && steam_id == g_session.host_steam_id) {
            RestartClientHostHandshake(steam_id, "authenticated_peer_timeout");
            continue;
        }
        Log(
            "Steam multiplayer peer timed out. steam_id=" +
            std::to_string(steam_id));
        RemovePeer(steam_id);
    }

    if (g_session.is_host && g_session.phase == SteamSessionPhase::Connected) {
        const bool has_authenticated_peer = std::any_of(
            g_session.peers.begin(),
            g_session.peers.end(),
            [](const auto& entry) { return entry.second.authenticated; });
        if (!has_authenticated_peer) {
            g_session.phase = SteamSessionPhase::LobbyReady;
        }
    }
}

void RefreshRouteStatus(std::uint64_t now_ms) {
    if (g_session.last_route_status_ms != 0 &&
        now_ms < g_session.last_route_status_ms + kRouteStatusIntervalMs) {
        return;
    }
    for (auto& [steam_id, peer] : g_session.peers) {
        if (!peer.authenticated) {
            continue;
        }
        peer.network_status = SteamGetNetworkSessionStatus(steam_id);
    }
    g_session.last_route_status_ms = now_ms;
}

void SendGoodbyeToAuthenticatedPeers(SessionGoodbyeReason reason) {
    if (g_session.lobby_id == 0) {
        return;
    }
    SessionGoodbyePacket packet{};
    packet.header = MakePacketHeader(PacketKind::SessionGoodbye, g_session.next_sequence++);
    packet.lobby_id = g_session.lobby_id;
    packet.participant_id = g_session.local_steam_id;
    packet.steam_id = g_session.local_steam_id;
    packet.reason = static_cast<std::uint8_t>(reason);
    for (const auto& [steam_id, peer] : g_session.peers) {
        if (!peer.authenticated) {
            continue;
        }
        SteamSendNetworkMessage(
            steam_id,
            &packet,
            sizeof(packet),
            SteamNetworkSendMode::ReliableNoNagle);
    }
}

}  // namespace

bool InitializeSteamSession() {
    const auto transport = ToLowerAscii(TrimAscii(ReadEnvironmentVariable(kTransportEnvironmentVariable)));
    ResetMultiplayerSessionStatus(GetStageRuntimeDirectory());
    g_session = SteamSessionState{};
    g_session.launch_token =
        TrimAscii(ReadEnvironmentVariable(kLaunchTokenEnvironmentVariable));
    if (transport != "steam") {
        return true;
    }

    const auto mode = ToLowerAscii(TrimAscii(ReadEnvironmentVariable(kSessionModeEnvironmentVariable)));
    const auto role = ToLowerAscii(TrimAscii(ReadEnvironmentVariable(kRoleEnvironmentVariable)));
    g_session.configured = true;
    g_session.is_host = mode == "host" ||
        (mode.empty() && (role.empty() || role == "host" || role == "server"));
    g_session.max_participants = ReadMaxParticipants();
    g_session.open_invite_dialog = ReadBooleanEnvironmentVariable(
        kOpenInviteEnvironmentVariable,
        true);

    const auto steam = GetSteamBootstrapSnapshot();
    g_session.app_id = steam.app_id;
    g_session.local_steam_id = steam.local_steam_id;
    if (!steam.transport_interfaces_ready || steam.local_steam_id == 0) {
        SetError("Steam transport was requested but SteamAPI is not ready.", false);
        PublishSessionRuntime(GetTickCount64());
        return false;
    }
    g_session.manifest_sha256_text = ToLowerAscii(TrimAscii(
        ReadEnvironmentVariable(kManifestEnvironmentVariable)));
    if (!ParseSha256(
            g_session.manifest_sha256_text,
            &g_session.manifest_sha256)) {
        SetError("Missing or invalid multiplayer build fingerprint.", false);
        PublishSessionRuntime(GetTickCount64());
        return false;
    }

    g_session.initialized = true;
    g_session.overlay_enabled = SteamIsOverlayEnabled();
    g_session.local_session_nonce = GenerateSessionNonce();

    if (g_session.is_host) {
        g_session.pending_api_call = SteamCreateFriendsOnlyLobby(
            static_cast<std::int32_t>(g_session.max_participants));
        if (g_session.pending_api_call == 0) {
            SetError("Steam rejected the CreateLobby request before it was queued.", false);
            PublishSessionRuntime(GetTickCount64());
            return false;
        }
        g_session.phase = SteamSessionPhase::CreatingLobby;
    } else {
        std::uint64_t configured_lobby_id = 0;
        TryParseUnsigned64(
            TrimAscii(ReadEnvironmentVariable(kLobbyIdEnvironmentVariable)),
            &configured_lobby_id);
        if (configured_lobby_id == 0) {
            configured_lobby_id = ParseCommandLineLobbyId();
        }
        if (configured_lobby_id != 0) {
            BeginJoinLobby(configured_lobby_id);
        } else {
            g_session.phase = SteamSessionPhase::WaitingForInvite;
        }
    }
    PublishSessionRuntime(GetTickCount64());
    return g_session.phase != SteamSessionPhase::Error;
}

void ShutdownSteamSession() {
    if (!g_session.initialized) {
        g_session = SteamSessionState{};
        return;
    }
    SendGoodbyeToAuthenticatedPeers(
        g_session.is_host
            ? SessionGoodbyeReason::LobbyClosed
            : SessionGoodbyeReason::Leaving);
    if (g_session.is_host && g_session.lobby_id != 0) {
        SteamSetLobbyJoinable(g_session.lobby_id, false);
        SteamSetLobbyData(g_session.lobby_id, kLobbyStateKey, kLobbyStateClosed);
    }
    if (g_session.lobby_id != 0) {
        SteamLeaveLobby(g_session.lobby_id);
    }
    for (const auto& [steam_id, peer] : g_session.peers) {
        (void)peer;
        SteamCloseNetworkSession(steam_id);
        UnregisterSteamGameplayPeer(steam_id);
    }
    SteamSetRichPresence("connect", nullptr);
    SteamSetRichPresence("status", nullptr);
    g_session = SteamSessionState{};
}

void TickSteamSession(std::uint64_t now_ms) {
    if (!g_session.initialized || g_session.phase == SteamSessionPhase::Disabled) {
        return;
    }
    for (const auto& event : DrainSteamEvents()) {
        HandleSteamEvent(event, now_ms);
    }
    if (g_session.phase == SteamSessionPhase::Error) {
        PublishSessionRuntime(now_ms);
        return;
    }
    if (g_session.lobby_id != 0 &&
        (g_session.last_lobby_reconcile_ms == 0 ||
         now_ms >= g_session.last_lobby_reconcile_ms + kLobbyReconcileIntervalMs)) {
        ReconcileLobbyMembers(now_ms);
    }
    if (g_session.phase == SteamSessionPhase::Error) {
        PublishSessionRuntime(now_ms);
        return;
    }
    RefreshOverlayAndInviteDialog();
    SendClientHello(now_ms);
    PumpNetworkMessages(now_ms);
    ExpireInactivePeers(now_ms);
    RefreshRouteStatus(now_ms);
    PublishSessionRuntime(now_ms);
}

bool IsSteamSessionEnabled() {
    return g_session.initialized;
}

}  // namespace sdmod::multiplayer
