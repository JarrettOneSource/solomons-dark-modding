#pragma once

#include <cstddef>
#include <cstdint>

// Minimal ABI declarations for the dynamically loaded 32-bit Steamworks
// interfaces used by the mod loader.  Keeping these declarations here avoids
// a build-time dependency on a particular Steamworks SDK while still making
// every structure size crossing steam_api.dll explicit and testable.
namespace sdmod::steamabi {

using SteamApiCall = std::uint64_t;
using SteamId = std::uint64_t;
using SteamPipe = std::int32_t;
using SteamUser = std::int32_t;

constexpr SteamApiCall kInvalidApiCall = 0;
constexpr std::int32_t kResultOk = 1;
constexpr std::int32_t kLobbyTypeFriendsOnly = 1;
constexpr std::uint32_t kLobbyEnterSuccess = 1;

constexpr std::uint32_t kChatMemberStateEntered = 0x01;
constexpr std::uint32_t kChatMemberStateLeft = 0x02;
constexpr std::uint32_t kChatMemberStateDisconnected = 0x04;
constexpr std::uint32_t kChatMemberStateKicked = 0x08;
constexpr std::uint32_t kChatMemberStateBanned = 0x10;

constexpr std::int32_t kNetworkingConnectionNone = 0;
constexpr std::int32_t kNetworkingConnectionConnecting = 1;
constexpr std::int32_t kNetworkingConnectionFindingRoute = 2;
constexpr std::int32_t kNetworkingConnectionConnected = 3;
constexpr std::int32_t kNetworkingConnectionClosedByPeer = 4;
constexpr std::int32_t kNetworkingConnectionProblemDetectedLocally = 5;
constexpr std::int32_t kNetworkConnectionInfoRelayed = 0x10;

constexpr std::int32_t kNetworkingSendUnreliableNoNagle = 1;
constexpr std::int32_t kNetworkingSendUnreliableNoDelay = 5;
constexpr std::int32_t kNetworkingSendReliable = 8;
constexpr std::int32_t kNetworkingSendReliableNoNagle = 9;

constexpr std::int32_t kCallbackGameLobbyJoinRequested = 333;
constexpr std::int32_t kCallbackGameRichPresenceJoinRequested = 337;
constexpr std::int32_t kCallbackLobbyInvite = 503;
constexpr std::int32_t kCallbackLobbyEnter = 504;
constexpr std::int32_t kCallbackLobbyDataUpdate = 505;
constexpr std::int32_t kCallbackLobbyChatUpdate = 506;
constexpr std::int32_t kCallbackLobbyCreated = 513;
constexpr std::int32_t kCallbackSteamApiCallCompleted = 703;
constexpr std::int32_t kCallbackNetworkingMessagesSessionRequest = 1251;
constexpr std::int32_t kCallbackNetworkingMessagesSessionFailed = 1252;

#pragma pack(push, 1)
struct NetworkingIpAddress {
    std::uint8_t ipv6[16] = {};
    std::uint16_t port = 0;
};

struct NetworkingIdentity {
    std::int32_t type = 0;
    std::int32_t size = 0;
    std::uint8_t value[128] = {};
};
#pragma pack(pop)

#pragma pack(push, 4)
struct NetworkConnectionInfo {
    NetworkingIdentity remote_identity;
    std::int64_t user_data = 0;
    std::uint32_t listen_socket = 0;
    NetworkingIpAddress remote_address;
    std::uint16_t address_padding = 0;
    std::uint32_t remote_pop = 0;
    std::uint32_t relay_pop = 0;
    std::int32_t state = 0;
    std::int32_t end_reason = 0;
    char end_debug[128] = {};
    char connection_description[128] = {};
    std::int32_t flags = 0;
    std::uint32_t reserved[63] = {};
};

struct NetworkRealtimeStatus {
    std::int32_t state = 0;
    std::int32_t ping_ms = 0;
    float local_connection_quality = 0.0f;
    float remote_connection_quality = 0.0f;
    float outbound_packets_per_second = 0.0f;
    float outbound_bytes_per_second = 0.0f;
    float inbound_packets_per_second = 0.0f;
    float inbound_bytes_per_second = 0.0f;
    std::int32_t send_rate_bytes_per_second = 0;
    std::int32_t pending_unreliable_bytes = 0;
    std::int32_t pending_reliable_bytes = 0;
    std::int32_t unacked_reliable_bytes = 0;
    std::int64_t queue_time_microseconds = 0;
    std::int32_t max_jitter_microseconds = 0;
    std::uint32_t reserved[15] = {};
};

struct NetworkingMessage {
    void* data = nullptr;
    std::int32_t size = 0;
    std::uint32_t connection = 0;
    NetworkingIdentity peer_identity;
    std::int64_t connection_user_data = 0;
    std::int64_t received_microseconds = 0;
    std::int64_t message_number = 0;
    void(__cdecl* free_data)(NetworkingMessage*) = nullptr;
    void(__cdecl* release)(NetworkingMessage*) = nullptr;
    std::int32_t channel = 0;
    std::int32_t flags = 0;
    std::int64_t user_data = 0;
    std::uint16_t lane = 0;
    std::uint16_t lane_padding = 0;
};

struct CallbackMessage {
    SteamUser user = 0;
    std::int32_t callback_id = 0;
    std::uint8_t* parameter = nullptr;
    std::int32_t parameter_size = 0;
};
#pragma pack(pop)

#pragma pack(push, 8)
struct SteamApiCallCompleted {
    SteamApiCall call = 0;
    std::int32_t callback_id = 0;
    std::uint32_t parameter_size = 0;
};

struct LobbyCreated {
    std::int32_t result = 0;
    SteamId lobby_id = 0;
};

struct LobbyEnter {
    SteamId lobby_id = 0;
    std::uint32_t chat_permissions = 0;
    std::uint8_t locked = 0;
    std::uint32_t response = 0;
};

struct GameLobbyJoinRequested {
    SteamId lobby_id = 0;
    SteamId friend_id = 0;
};

struct GameRichPresenceJoinRequested {
    SteamId friend_id = 0;
    char connect[256] = {};
};

struct LobbyInvite {
    SteamId sender_id = 0;
    SteamId lobby_id = 0;
    std::uint64_t game_id = 0;
};

struct LobbyDataUpdate {
    SteamId lobby_id = 0;
    SteamId member_id = 0;
    std::uint8_t success = 0;
};

struct LobbyChatUpdate {
    SteamId lobby_id = 0;
    SteamId changed_user_id = 0;
    SteamId making_change_user_id = 0;
    std::uint32_t state_change = 0;
};
#pragma pack(pop)

// Steam's callback ABI uses 4-byte packing when a Win32 game runs through
// Proton and 8-byte packing on native 32-bit Windows. Most callback fields
// retain the same offsets, but the total sizes differ; LobbyCreated also moves
// its SteamId. Keep both layouts explicit so manual dispatch can decode the
// payload size reported by the active Steam client.
#pragma pack(push, 4)
struct LobbyCreatedSmall {
    std::int32_t result = 0;
    SteamId lobby_id = 0;
};

struct LobbyEnterSmall {
    SteamId lobby_id = 0;
    std::uint32_t chat_permissions = 0;
    std::uint8_t locked = 0;
    std::uint32_t response = 0;
};

struct LobbyDataUpdateSmall {
    SteamId lobby_id = 0;
    SteamId member_id = 0;
    std::uint8_t success = 0;
};

struct LobbyChatUpdateSmall {
    SteamId lobby_id = 0;
    SteamId changed_user_id = 0;
    SteamId making_change_user_id = 0;
    std::uint32_t state_change = 0;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct NetworkingMessagesSessionRequest {
    NetworkingIdentity remote_identity;
};

struct NetworkingMessagesSessionFailed {
    NetworkConnectionInfo info;
};
#pragma pack(pop)

static_assert(sizeof(NetworkingIpAddress) == 18, "SteamNetworkingIPAddr ABI changed");
static_assert(sizeof(NetworkingIdentity) == 136, "SteamNetworkingIdentity ABI changed");
static_assert(sizeof(NetworkConnectionInfo) == 696, "SteamNetConnectionInfo_t ABI changed");
static_assert(sizeof(NetworkRealtimeStatus) == 120, "SteamNetConnectionRealTimeStatus_t ABI changed");
static_assert(sizeof(SteamApiCallCompleted) == 16, "SteamAPICallCompleted_t ABI changed");
static_assert(sizeof(LobbyCreated) == 16, "LobbyCreated_t ABI changed");
static_assert(sizeof(LobbyEnter) == 24, "LobbyEnter_t ABI changed");
static_assert(sizeof(GameLobbyJoinRequested) == 16, "GameLobbyJoinRequested_t ABI changed");
static_assert(sizeof(GameRichPresenceJoinRequested) == 264,
              "GameRichPresenceJoinRequested_t ABI changed");
static_assert(sizeof(LobbyInvite) == 24, "LobbyInvite_t ABI changed");
static_assert(sizeof(LobbyDataUpdate) == 24, "LobbyDataUpdate_t ABI changed");
static_assert(sizeof(LobbyChatUpdate) == 32, "LobbyChatUpdate_t ABI changed");
static_assert(sizeof(LobbyCreatedSmall) == 12,
              "small-pack LobbyCreated_t ABI changed");
static_assert(sizeof(LobbyEnterSmall) == 20,
              "small-pack LobbyEnter_t ABI changed");
static_assert(sizeof(LobbyDataUpdateSmall) == 20,
              "small-pack LobbyDataUpdate_t ABI changed");
static_assert(sizeof(LobbyChatUpdateSmall) == 28,
              "small-pack LobbyChatUpdate_t ABI changed");
static_assert(sizeof(NetworkingMessagesSessionRequest) == 136,
              "SteamNetworkingMessagesSessionRequest_t ABI changed");
static_assert(sizeof(NetworkingMessagesSessionFailed) == 696,
              "SteamNetworkingMessagesSessionFailed_t ABI changed");

#if defined(_WIN32) && !defined(_WIN64)
static_assert(sizeof(CallbackMessage) == 16, "CallbackMsg_t Win32 ABI changed");
static_assert(sizeof(NetworkingMessage) == 200, "SteamNetworkingMessage_t Win32 ABI changed");
#endif

}  // namespace sdmod::steamabi
