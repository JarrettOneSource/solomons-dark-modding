#include "steam_bootstrap_internal.h"

#include "logger.h"
#include "mod_loader.h"

#include <filesystem>
#include <string>

namespace sdmod::detail {
namespace {

constexpr wchar_t kDefaultApiDllName[] = L"steam_api.dll";

template <typename T>
bool TryLoadExport(SteamBootstrapState* state, T* target, const char* export_name) {
    if (state == nullptr || target == nullptr || state->module == nullptr) {
        return false;
    }

    const auto address = reinterpret_cast<T>(GetProcAddress(state->module, export_name));
    if (address == nullptr) {
        return false;
    }

    *target = address;
    return true;
}

template <typename T>
bool LoadRequiredExport(SteamBootstrapState* state, T* target, const char* export_name) {
    if (TryLoadExport(state, target, export_name)) {
        return true;
    }

    Log(std::string("Steam bootstrap: missing export ") + export_name);
    state->snapshot.error_text = std::string("Missing Steam export: ") + export_name;
    state->snapshot.status_text = "Steam export binding failed.";
    return false;
}

bool LoadOptionalInitExport(SteamBootstrapState* state) {
    if (TryLoadExport(state, &state->init, "SteamAPI_Init")) {
        Log("Steam bootstrap: using SteamAPI_Init.");
        state->snapshot.using_init_safe = false;
        return true;
    }

    if (TryLoadExport(state, &state->init, "SteamAPI_InitSafe")) {
        Log("Steam bootstrap: SteamAPI_Init was unavailable; using SteamAPI_InitSafe.");
        state->snapshot.using_init_safe = true;
        return true;
    }

    Log("Steam bootstrap: missing export SteamAPI_Init and SteamAPI_InitSafe.");
    state->snapshot.error_text = "Missing Steam initialization export.";
    state->snapshot.status_text = "Steam export binding failed.";
    return false;
}

}  // namespace

bool LoadSteamApiModule(SteamBootstrapState* state,
                        const SteamBootstrapConfiguration& configuration,
                        const std::filesystem::path& host_process_directory) {
    if (state == nullptr) {
        return false;
    }

    if (state->module != nullptr) {
        return true;
    }

    if (!configuration.api_dll_path.empty()) {
        Log("Steam bootstrap: attempting explicit steam_api.dll load from " + configuration.api_dll_path.string());
        state->module = LoadLibraryW(configuration.api_dll_path.c_str());
    }

    if (state->module == nullptr) {
        const auto staged_api_path = host_process_directory / kDefaultApiDllName;
        if (std::filesystem::exists(staged_api_path)) {
            Log("Steam bootstrap: attempting staged steam_api.dll load from " + staged_api_path.string());
            state->module = LoadLibraryW(staged_api_path.c_str());
        }
    }

    if (state->module == nullptr) {
        state->module = GetModuleHandleW(kDefaultApiDllName);
        if (state->module != nullptr) {
            Log("Steam bootstrap: reusing already-loaded steam_api.dll.");
        }
    }

    if (state->module == nullptr) {
        Log("Steam bootstrap: steam_api.dll was not available in the staged game root or configured override path.");
        return false;
    }

    state->snapshot.module_loaded = true;
    state->snapshot.module_path = GetModulePath(state->module).string();
    Log("Steam bootstrap: loaded steam_api.dll from " + state->snapshot.module_path);
    return true;
}

bool LoadSteamApiExports(SteamBootstrapState* state) {
    if (state == nullptr) {
        return false;
    }

    const bool success =
        LoadRequiredExport(state, &state->restart_app_if_necessary, "SteamAPI_RestartAppIfNecessary") &&
        LoadOptionalInitExport(state) &&
        LoadRequiredExport(state, &state->shutdown, "SteamAPI_Shutdown") &&
        LoadRequiredExport(state, &state->get_pipe, "SteamAPI_GetHSteamPipe") &&
        LoadRequiredExport(state, &state->manual_dispatch_init, "SteamAPI_ManualDispatch_Init") &&
        LoadRequiredExport(state, &state->manual_dispatch_run_frame, "SteamAPI_ManualDispatch_RunFrame") &&
        LoadRequiredExport(
            state,
            &state->manual_dispatch_get_next_callback,
            "SteamAPI_ManualDispatch_GetNextCallback") &&
        LoadRequiredExport(
            state,
            &state->manual_dispatch_free_last_callback,
            "SteamAPI_ManualDispatch_FreeLastCallback") &&
        LoadRequiredExport(
            state,
            &state->manual_dispatch_get_api_call_result,
            "SteamAPI_ManualDispatch_GetAPICallResult") &&
        LoadRequiredExport(state, &state->steam_friends_v017, "SteamAPI_SteamFriends_v017") &&
        LoadRequiredExport(state, &state->steam_matchmaking_v009, "SteamAPI_SteamMatchmaking_v009") &&
        LoadRequiredExport(
            state,
            &state->steam_networking_messages_v002,
            "SteamAPI_SteamNetworkingMessages_SteamAPI_v002") &&
        LoadRequiredExport(state, &state->steam_user_v023, "SteamAPI_SteamUser_v023") &&
        LoadRequiredExport(state, &state->steam_utils_v010, "SteamAPI_SteamUtils_v010") &&
        LoadRequiredExport(state, &state->friends_get_persona_name, "SteamAPI_ISteamFriends_GetPersonaName") &&
        LoadRequiredExport(
            state,
            &state->friends_get_friend_persona_name,
            "SteamAPI_ISteamFriends_GetFriendPersonaName") &&
        LoadRequiredExport(
            state,
            &state->friends_activate_game_overlay_invite_dialog,
            "SteamAPI_ISteamFriends_ActivateGameOverlayInviteDialog") &&
        LoadRequiredExport(
            state,
            &state->friends_set_rich_presence,
            "SteamAPI_ISteamFriends_SetRichPresence") &&
        LoadRequiredExport(state, &state->user_get_steam_id, "SteamAPI_ISteamUser_GetSteamID") &&
        LoadRequiredExport(
            state,
            &state->utils_is_overlay_enabled,
            "SteamAPI_ISteamUtils_IsOverlayEnabled") &&
        LoadRequiredExport(
            state,
            &state->matchmaking_create_lobby,
            "SteamAPI_ISteamMatchmaking_CreateLobby") &&
        LoadRequiredExport(
            state,
            &state->matchmaking_join_lobby,
            "SteamAPI_ISteamMatchmaking_JoinLobby") &&
        LoadRequiredExport(
            state,
            &state->matchmaking_leave_lobby,
            "SteamAPI_ISteamMatchmaking_LeaveLobby") &&
        LoadRequiredExport(
            state,
            &state->matchmaking_request_lobby_data,
            "SteamAPI_ISteamMatchmaking_RequestLobbyData") &&
        LoadRequiredExport(
            state,
            &state->matchmaking_set_lobby_joinable,
            "SteamAPI_ISteamMatchmaking_SetLobbyJoinable") &&
        LoadRequiredExport(
            state,
            &state->matchmaking_set_lobby_data,
            "SteamAPI_ISteamMatchmaking_SetLobbyData") &&
        LoadRequiredExport(
            state,
            &state->matchmaking_get_lobby_data,
            "SteamAPI_ISteamMatchmaking_GetLobbyData") &&
        LoadRequiredExport(
            state,
            &state->matchmaking_set_lobby_member_data,
            "SteamAPI_ISteamMatchmaking_SetLobbyMemberData") &&
        LoadRequiredExport(
            state,
            &state->matchmaking_get_lobby_member_data,
            "SteamAPI_ISteamMatchmaking_GetLobbyMemberData") &&
        LoadRequiredExport(
            state,
            &state->matchmaking_get_lobby_owner,
            "SteamAPI_ISteamMatchmaking_GetLobbyOwner") &&
        LoadRequiredExport(
            state,
            &state->matchmaking_get_num_lobby_members,
            "SteamAPI_ISteamMatchmaking_GetNumLobbyMembers") &&
        LoadRequiredExport(
            state,
            &state->matchmaking_get_lobby_member_by_index,
            "SteamAPI_ISteamMatchmaking_GetLobbyMemberByIndex") &&
        LoadRequiredExport(
            state,
            &state->identity_clear,
            "SteamAPI_SteamNetworkingIdentity_Clear") &&
        LoadRequiredExport(
            state,
            &state->identity_set_steam_id64,
            "SteamAPI_SteamNetworkingIdentity_SetSteamID64") &&
        LoadRequiredExport(
            state,
            &state->identity_get_steam_id64,
            "SteamAPI_SteamNetworkingIdentity_GetSteamID64") &&
        LoadRequiredExport(
            state,
            &state->networking_messages_send,
            "SteamAPI_ISteamNetworkingMessages_SendMessageToUser") &&
        LoadRequiredExport(
            state,
            &state->networking_messages_receive,
            "SteamAPI_ISteamNetworkingMessages_ReceiveMessagesOnChannel") &&
        LoadRequiredExport(
            state,
            &state->networking_messages_accept,
            "SteamAPI_ISteamNetworkingMessages_AcceptSessionWithUser") &&
        LoadRequiredExport(
            state,
            &state->networking_messages_close,
            "SteamAPI_ISteamNetworkingMessages_CloseSessionWithUser") &&
        LoadRequiredExport(
            state,
            &state->networking_messages_get_session_info,
            "SteamAPI_ISteamNetworkingMessages_GetSessionConnectionInfo") &&
        LoadRequiredExport(
            state,
            &state->networking_message_release,
            "SteamAPI_SteamNetworkingMessage_t_Release");
    state->snapshot.exports_loaded = success;
    return success;
}

}  // namespace sdmod::detail
