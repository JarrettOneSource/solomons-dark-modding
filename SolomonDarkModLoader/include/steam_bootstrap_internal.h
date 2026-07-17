#pragma once

#include "steam_bootstrap.h"
#include "steamworks_abi.h"

#include <Windows.h>

#include <cstdint>
#include <filesystem>
#include <mutex>
#include <vector>

namespace sdmod::detail {

struct SteamBootstrapConfiguration {
    bool allow_restart_if_necessary = false;
    std::uint32_t app_id = 0;
    std::filesystem::path app_id_path;
    std::filesystem::path api_dll_path;
};

using SteamRestartAppIfNecessaryFn = bool(__cdecl*)(std::uint32_t);
using SteamInitFn = bool(__cdecl*)();
using SteamShutdownFn = void(__cdecl*)();
using SteamGetPipeFn = steamabi::SteamPipe(__cdecl*)();
using SteamManualDispatchInitFn = void(__cdecl*)();
using SteamManualDispatchRunFrameFn = void(__cdecl*)(steamabi::SteamPipe);
using SteamManualDispatchGetNextCallbackFn = bool(__cdecl*)(
    steamabi::SteamPipe,
    steamabi::CallbackMessage*);
using SteamManualDispatchFreeLastCallbackFn = void(__cdecl*)(steamabi::SteamPipe);
using SteamManualDispatchGetApiCallResultFn = bool(__cdecl*)(
    steamabi::SteamPipe,
    steamabi::SteamApiCall,
    void*,
    int,
    int,
    bool*);
using SteamFriendsAccessorFn = void*(__cdecl*)();
using SteamMatchmakingAccessorFn = void*(__cdecl*)();
using SteamNetworkingMessagesAccessorFn = void*(__cdecl*)();
using SteamUserAccessorFn = void*(__cdecl*)();
using SteamUtilsAccessorFn = void*(__cdecl*)();
using SteamFriendsGetPersonaNameFn = const char*(__cdecl*)(void*);
using SteamFriendsGetFriendPersonaNameFn = const char*(__cdecl*)(void*, std::uint64_t);
using SteamFriendsGetFriendCountFn = int(__cdecl*)(void*, int);
using SteamFriendsGetFriendByIndexFn = std::uint64_t(__cdecl*)(void*, int, int);
using SteamFriendsHasFriendFn = bool(__cdecl*)(void*, std::uint64_t, int);
using SteamFriendsActivateGameOverlayInviteDialogFn = void(__cdecl*)(void*, std::uint64_t);
using SteamFriendsSetRichPresenceFn = bool(__cdecl*)(void*, const char*, const char*);
using SteamUserGetSteamIdFn = std::uint64_t(__cdecl*)(void*);
using SteamUtilsIsOverlayEnabledFn = bool(__cdecl*)(void*);
using SteamMatchmakingCreateLobbyFn = std::uint64_t(__cdecl*)(void*, int, int);
using SteamMatchmakingJoinLobbyFn = std::uint64_t(__cdecl*)(void*, std::uint64_t);
using SteamMatchmakingLeaveLobbyFn = void(__cdecl*)(void*, std::uint64_t);
using SteamMatchmakingRequestLobbyDataFn = bool(__cdecl*)(void*, std::uint64_t);
using SteamMatchmakingSetLobbyJoinableFn = bool(__cdecl*)(void*, std::uint64_t, bool);
using SteamMatchmakingInviteUserToLobbyFn = bool(__cdecl*)(
    void*,
    std::uint64_t,
    std::uint64_t);
using SteamMatchmakingSetLobbyDataFn = bool(__cdecl*)(void*, std::uint64_t, const char*, const char*);
using SteamMatchmakingGetLobbyDataFn = const char*(__cdecl*)(void*, std::uint64_t, const char*);
using SteamMatchmakingSetLobbyMemberDataFn = void(__cdecl*)(void*, std::uint64_t, const char*, const char*);
using SteamMatchmakingGetLobbyMemberDataFn = const char*(__cdecl*)(
    void*,
    std::uint64_t,
    std::uint64_t,
    const char*);
using SteamMatchmakingGetLobbyOwnerFn = std::uint64_t(__cdecl*)(void*, std::uint64_t);
using SteamMatchmakingGetNumLobbyMembersFn = int(__cdecl*)(void*, std::uint64_t);
using SteamMatchmakingGetLobbyMemberByIndexFn = std::uint64_t(__cdecl*)(void*, std::uint64_t, int);
using SteamIdentityClearFn = void(__cdecl*)(steamabi::NetworkingIdentity*);
using SteamIdentitySetSteamId64Fn = void(__cdecl*)(steamabi::NetworkingIdentity*, std::uint64_t);
using SteamIdentityGetSteamId64Fn = std::uint64_t(__cdecl*)(const steamabi::NetworkingIdentity*);
using SteamNetworkingMessagesSendFn = std::int32_t(__cdecl*)(
    void*,
    const steamabi::NetworkingIdentity*,
    const void*,
    std::uint32_t,
    int,
    int);
using SteamNetworkingMessagesReceiveFn = int(__cdecl*)(
    void*,
    int,
    steamabi::NetworkingMessage**,
    int);
using SteamNetworkingMessagesAcceptFn = bool(__cdecl*)(
    void*,
    const steamabi::NetworkingIdentity*);
using SteamNetworkingMessagesCloseFn = bool(__cdecl*)(
    void*,
    const steamabi::NetworkingIdentity*);
using SteamNetworkingMessagesGetSessionInfoFn = std::int32_t(__cdecl*)(
    void*,
    const steamabi::NetworkingIdentity*,
    steamabi::NetworkConnectionInfo*,
    steamabi::NetworkRealtimeStatus*);
using SteamNetworkingMessageReleaseFn = void(__cdecl*)(steamabi::NetworkingMessage*);

struct SteamBootstrapState {
    HMODULE module = nullptr;
    bool initialized = false;
    steamabi::SteamPipe pipe = 0;
    SteamBootstrapSnapshot snapshot;
    std::vector<SteamEvent> pending_events;

    SteamRestartAppIfNecessaryFn restart_app_if_necessary = nullptr;
    SteamInitFn init = nullptr;
    SteamShutdownFn shutdown = nullptr;
    SteamGetPipeFn get_pipe = nullptr;
    SteamManualDispatchInitFn manual_dispatch_init = nullptr;
    SteamManualDispatchRunFrameFn manual_dispatch_run_frame = nullptr;
    SteamManualDispatchGetNextCallbackFn manual_dispatch_get_next_callback = nullptr;
    SteamManualDispatchFreeLastCallbackFn manual_dispatch_free_last_callback = nullptr;
    SteamManualDispatchGetApiCallResultFn manual_dispatch_get_api_call_result = nullptr;
    SteamFriendsAccessorFn steam_friends_v017 = nullptr;
    SteamMatchmakingAccessorFn steam_matchmaking_v009 = nullptr;
    SteamNetworkingMessagesAccessorFn steam_networking_messages_v002 = nullptr;
    SteamUserAccessorFn steam_user_v023 = nullptr;
    SteamUtilsAccessorFn steam_utils_v010 = nullptr;
    SteamFriendsGetPersonaNameFn friends_get_persona_name = nullptr;
    SteamFriendsGetFriendPersonaNameFn friends_get_friend_persona_name = nullptr;
    SteamFriendsGetFriendCountFn friends_get_friend_count = nullptr;
    SteamFriendsGetFriendByIndexFn friends_get_friend_by_index = nullptr;
    SteamFriendsHasFriendFn friends_has_friend = nullptr;
    SteamFriendsActivateGameOverlayInviteDialogFn friends_activate_game_overlay_invite_dialog = nullptr;
    SteamFriendsSetRichPresenceFn friends_set_rich_presence = nullptr;
    SteamUserGetSteamIdFn user_get_steam_id = nullptr;
    SteamUtilsIsOverlayEnabledFn utils_is_overlay_enabled = nullptr;
    SteamMatchmakingCreateLobbyFn matchmaking_create_lobby = nullptr;
    SteamMatchmakingJoinLobbyFn matchmaking_join_lobby = nullptr;
    SteamMatchmakingLeaveLobbyFn matchmaking_leave_lobby = nullptr;
    SteamMatchmakingRequestLobbyDataFn matchmaking_request_lobby_data = nullptr;
    SteamMatchmakingSetLobbyJoinableFn matchmaking_set_lobby_joinable = nullptr;
    SteamMatchmakingInviteUserToLobbyFn matchmaking_invite_user_to_lobby = nullptr;
    SteamMatchmakingSetLobbyDataFn matchmaking_set_lobby_data = nullptr;
    SteamMatchmakingGetLobbyDataFn matchmaking_get_lobby_data = nullptr;
    SteamMatchmakingSetLobbyMemberDataFn matchmaking_set_lobby_member_data = nullptr;
    SteamMatchmakingGetLobbyMemberDataFn matchmaking_get_lobby_member_data = nullptr;
    SteamMatchmakingGetLobbyOwnerFn matchmaking_get_lobby_owner = nullptr;
    SteamMatchmakingGetNumLobbyMembersFn matchmaking_get_num_lobby_members = nullptr;
    SteamMatchmakingGetLobbyMemberByIndexFn matchmaking_get_lobby_member_by_index = nullptr;
    SteamIdentityClearFn identity_clear = nullptr;
    SteamIdentitySetSteamId64Fn identity_set_steam_id64 = nullptr;
    SteamIdentityGetSteamId64Fn identity_get_steam_id64 = nullptr;
    SteamNetworkingMessagesSendFn networking_messages_send = nullptr;
    SteamNetworkingMessagesReceiveFn networking_messages_receive = nullptr;
    SteamNetworkingMessagesAcceptFn networking_messages_accept = nullptr;
    SteamNetworkingMessagesCloseFn networking_messages_close = nullptr;
    SteamNetworkingMessagesGetSessionInfoFn networking_messages_get_session_info = nullptr;
    SteamNetworkingMessageReleaseFn networking_message_release = nullptr;
};

std::mutex& SteamBootstrapMutex();
SteamBootstrapState& MutableSteamBootstrapState();

bool ReadSteamBootstrapConfiguration(const std::filesystem::path& host_process_directory,
                                     SteamBootstrapConfiguration* configuration,
                                     SteamBootstrapSnapshot* snapshot);
void LogSteamBootstrapConfiguration(const SteamBootstrapConfiguration& configuration);

bool LoadSteamApiModule(SteamBootstrapState* state,
                        const SteamBootstrapConfiguration& configuration,
                        const std::filesystem::path& host_process_directory);
bool LoadSteamApiExports(SteamBootstrapState* state);

}  // namespace sdmod::detail
