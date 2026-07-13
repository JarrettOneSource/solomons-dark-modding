#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace sdmod {

struct SteamBootstrapSnapshot {
    bool requested = false;
    bool module_loaded = false;
    bool exports_loaded = false;
    bool initialized = false;
    bool transport_interfaces_ready = false;
    bool overlay_enabled = false;
    bool using_init_safe = false;
    std::uint32_t app_id = 0;
    uint64_t local_steam_id = 0;
    uint64_t callback_pump_count = 0;
    uint64_t last_callback_pump_ms = 0;
    std::string module_path;
    std::string persona_name;
    std::string status_text;
    std::string error_text;
};

enum class SteamEventKind {
    LobbyCreated,
    LobbyEntered,
    LobbyJoinRequested,
    RichPresenceJoinRequested,
    LobbyInviteReceived,
    LobbyDataUpdated,
    LobbyMemberChanged,
    NetworkSessionRequested,
    NetworkSessionFailed,
};

struct SteamPeerNetworkStatus {
    std::uint64_t steam_id = 0;
    std::int32_t connection_state = 0;
    std::int32_t end_reason = 0;
    std::int32_t ping_ms = 0;
    std::int32_t pending_reliable_bytes = 0;
    bool using_relay = false;
    std::string debug_text;
    std::string connection_description;
};

struct SteamEvent {
    SteamEventKind kind = SteamEventKind::LobbyDataUpdated;
    std::uint64_t api_call = 0;
    std::uint64_t lobby_id = 0;
    std::uint64_t user_id = 0;
    std::uint64_t actor_id = 0;
    std::uint32_t state_change = 0;
    std::int32_t result_code = 0;
    bool success = false;
    std::string connect_string;
    SteamPeerNetworkStatus network_status;
};

struct SteamNetworkMessage {
    std::uint64_t sender_steam_id = 0;
    bool reliable = false;
    std::vector<std::uint8_t> payload;
};

enum class SteamNetworkSendMode {
    UnreliableNoNagle,
    ReliableNoNagle,
};

bool InitializeSteamBootstrap();
void ShutdownSteamBootstrap();
void SteamBootstrapTick();
SteamBootstrapSnapshot GetSteamBootstrapSnapshot();
std::vector<SteamEvent> DrainSteamEvents();

std::uint64_t SteamCreateFriendsOnlyLobby(std::int32_t max_members);
std::uint64_t SteamJoinLobby(std::uint64_t lobby_id);
void SteamLeaveLobby(std::uint64_t lobby_id);
bool SteamRequestLobbyData(std::uint64_t lobby_id);
bool SteamSetLobbyJoinable(std::uint64_t lobby_id, bool joinable);
bool SteamSetLobbyData(std::uint64_t lobby_id, const char* key, const char* value);
std::string SteamGetLobbyData(std::uint64_t lobby_id, const char* key);
void SteamSetLobbyMemberData(std::uint64_t lobby_id, const char* key, const char* value);
std::string SteamGetLobbyMemberData(
    std::uint64_t lobby_id,
    std::uint64_t member_id,
    const char* key);
std::uint64_t SteamGetLobbyOwner(std::uint64_t lobby_id);
std::vector<std::uint64_t> SteamGetLobbyMembers(std::uint64_t lobby_id);
void SteamOpenLobbyInviteDialog(std::uint64_t lobby_id);
bool SteamIsOverlayEnabled();
bool SteamSetRichPresence(const char* key, const char* value);
std::string SteamGetFriendPersonaName(std::uint64_t steam_id);

bool SteamSendNetworkMessage(
    std::uint64_t remote_steam_id,
    const void* data,
    std::size_t size,
    SteamNetworkSendMode mode,
    std::int32_t* result_code = nullptr);
std::vector<SteamNetworkMessage> SteamReceiveNetworkMessages(
    std::int32_t channel,
    std::int32_t max_messages);
bool SteamAcceptNetworkSession(std::uint64_t remote_steam_id);
bool SteamCloseNetworkSession(std::uint64_t remote_steam_id);
SteamPeerNetworkStatus SteamGetNetworkSessionStatus(std::uint64_t remote_steam_id);

}  // namespace sdmod
