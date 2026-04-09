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
        LoadRequiredExport(state, &state->run_callbacks, "SteamAPI_RunCallbacks") &&
        LoadRequiredExport(state, &state->steam_friends_v017, "SteamAPI_SteamFriends_v017") &&
        LoadRequiredExport(state, &state->steam_matchmaking_v009, "SteamAPI_SteamMatchmaking_v009") &&
        LoadRequiredExport(state, &state->steam_networking_v006, "SteamAPI_SteamNetworking_v006") &&
        LoadRequiredExport(state, &state->steam_user_v023, "SteamAPI_SteamUser_v023") &&
        LoadRequiredExport(state, &state->friends_get_persona_name, "SteamAPI_ISteamFriends_GetPersonaName") &&
        LoadRequiredExport(state, &state->user_get_steam_id, "SteamAPI_ISteamUser_GetSteamID");
    state->snapshot.exports_loaded = success;
    return success;
}

}  // namespace sdmod::detail
