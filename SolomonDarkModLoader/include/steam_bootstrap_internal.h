#pragma once

#include "steam_bootstrap.h"

#include <Windows.h>

#include <cstdint>
#include <filesystem>

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
using SteamRunCallbacksFn = void(__cdecl*)();
using SteamFriendsAccessorFn = void*(__cdecl*)();
using SteamMatchmakingAccessorFn = void*(__cdecl*)();
using SteamNetworkingAccessorFn = void*(__cdecl*)();
using SteamUserAccessorFn = void*(__cdecl*)();
using SteamFriendsGetPersonaNameFn = const char*(__cdecl*)(void*);
using SteamUserGetSteamIdFn = std::uint64_t(__cdecl*)(void*);

struct SteamBootstrapState {
    HMODULE module = nullptr;
    bool initialized = false;
    SteamBootstrapSnapshot snapshot;

    SteamRestartAppIfNecessaryFn restart_app_if_necessary = nullptr;
    SteamInitFn init = nullptr;
    SteamShutdownFn shutdown = nullptr;
    SteamRunCallbacksFn run_callbacks = nullptr;
    SteamFriendsAccessorFn steam_friends_v017 = nullptr;
    SteamMatchmakingAccessorFn steam_matchmaking_v009 = nullptr;
    SteamNetworkingAccessorFn steam_networking_v006 = nullptr;
    SteamUserAccessorFn steam_user_v023 = nullptr;
    SteamFriendsGetPersonaNameFn friends_get_persona_name = nullptr;
    SteamUserGetSteamIdFn user_get_steam_id = nullptr;
};

bool ReadSteamBootstrapConfiguration(const std::filesystem::path& host_process_directory,
                                     SteamBootstrapConfiguration* configuration,
                                     SteamBootstrapSnapshot* snapshot);
void LogSteamBootstrapConfiguration(const SteamBootstrapConfiguration& configuration);

bool LoadSteamApiModule(SteamBootstrapState* state,
                        const SteamBootstrapConfiguration& configuration,
                        const std::filesystem::path& host_process_directory);
bool LoadSteamApiExports(SteamBootstrapState* state);

}  // namespace sdmod::detail
