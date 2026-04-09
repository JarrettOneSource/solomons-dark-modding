#include "steam_bootstrap.h"

#include "steam_bootstrap_internal.h"

#include "logger.h"
#include "mod_loader.h"

#include <mutex>
#include <sstream>

namespace sdmod {
namespace {

std::mutex g_steam_mutex;
detail::SteamBootstrapState g_steam;

void ResetAfterFailedInitialization() {
    if (g_steam.initialized && g_steam.shutdown != nullptr) {
        g_steam.shutdown();
    }
    g_steam.initialized = false;
    g_steam.snapshot.initialized = false;
    g_steam.snapshot.transport_interfaces_ready = false;
}

}  // namespace

bool InitializeSteamBootstrap() {
    std::scoped_lock lock(g_steam_mutex);
    if (g_steam.initialized) {
        return true;
    }

    g_steam.snapshot = SteamBootstrapSnapshot{};
    detail::SteamBootstrapConfiguration configuration;
    if (!detail::ReadSteamBootstrapConfiguration(GetHostProcessDirectory(), &configuration, &g_steam.snapshot)) {
        if (g_steam.snapshot.requested) {
            Log("Steam bootstrap: missing or invalid SDMOD_STEAM_APP_ID.");
        } else {
            Log("Steam bootstrap: not requested by launcher environment.");
        }
        return false;
    }

    detail::LogSteamBootstrapConfiguration(configuration);

    if (!detail::LoadSteamApiModule(&g_steam, configuration, GetHostProcessDirectory())) {
        g_steam.snapshot.error_text = "steam_api.dll was not available.";
        g_steam.snapshot.status_text = "Steam API DLL is missing.";
        return false;
    }

    if (!detail::LoadSteamApiExports(&g_steam)) {
        Log("Steam bootstrap: steam_api.dll did not expose the flat Steamworks entry points required by the future P2P path.");
        return false;
    }

    if (configuration.allow_restart_if_necessary) {
        if (g_steam.restart_app_if_necessary(configuration.app_id)) {
            Log("Steam bootstrap: Steam requested a relaunch through Steam, but restart from the injected loader is not supported. Leaving the current process running.");
            g_steam.snapshot.error_text = "Steam requested relaunch through Steam.";
            g_steam.snapshot.status_text = "Steam relaunch is unsupported from the injected loader.";
            return false;
        }
    } else {
        Log("Steam bootstrap: SteamAPI_RestartAppIfNecessary skipped for the staged injected-loader bootstrap.");
    }

    if (!g_steam.init()) {
        Log("Steam bootstrap: SteamAPI_Init failed. Common causes are Steam not running, no active license for the configured AppID, an admin/user-context mismatch, or a missing steam_appid.txt next to the staged executable.");
        g_steam.snapshot.error_text =
            "SteamAPI_Init failed. Check Steam login, license, admin context, and steam_appid.txt.";
        g_steam.snapshot.status_text = "Steam initialization failed.";
        return false;
    }

    g_steam.initialized = true;
    g_steam.snapshot.initialized = true;
    g_steam.snapshot.status_text = "Steam initialized.";
    Log("Steam bootstrap: SteamAPI_Init succeeded.");

    auto* friends = g_steam.steam_friends_v017();
    auto* matchmaking = g_steam.steam_matchmaking_v009();
    auto* networking = g_steam.steam_networking_v006();
    auto* user = g_steam.steam_user_v023();
    if (friends == nullptr || matchmaking == nullptr || networking == nullptr || user == nullptr) {
        Log("Steam bootstrap: Steam initialized, but the legacy friends, matchmaking, networking, or user interfaces were not available.");
        g_steam.snapshot.error_text = "Legacy Steam transport interfaces were not available.";
        g_steam.snapshot.status_text = "Steam transport interfaces unavailable.";
        ResetAfterFailedInitialization();
        return false;
    }

    const auto* persona_name = g_steam.friends_get_persona_name(friends);
    g_steam.snapshot.transport_interfaces_ready = true;
    g_steam.snapshot.local_steam_id = g_steam.user_get_steam_id(user);
    g_steam.snapshot.persona_name = persona_name != nullptr ? persona_name : "";
    g_steam.snapshot.error_text.clear();
    g_steam.snapshot.status_text = "Steam transport ready.";
    if (g_steam.run_callbacks != nullptr) {
        g_steam.run_callbacks();
        g_steam.snapshot.callback_pump_count = 1;
        g_steam.snapshot.last_callback_pump_ms = GetTickCount64();
    }

    std::ostringstream message;
    message << "Steam bootstrap: ready for future P2P work."
            << " module=" << g_steam.snapshot.module_path
            << " steam_id=" << g_steam.snapshot.local_steam_id;
    if (!g_steam.snapshot.persona_name.empty()) {
        message << " persona=" << g_steam.snapshot.persona_name;
    }
    message << " interfaces={friends_v017, matchmaking_v009, networking_v006, user_v023}";
    Log(message.str());
    return true;
}

void ShutdownSteamBootstrap() {
    std::scoped_lock lock(g_steam_mutex);
    if (g_steam.initialized && g_steam.shutdown != nullptr) {
        Log("Steam bootstrap: shutting down SteamAPI.");
        g_steam.shutdown();
    }

    g_steam = detail::SteamBootstrapState{};
}

void SteamBootstrapTick() {
    std::scoped_lock lock(g_steam_mutex);
    if (!g_steam.initialized || g_steam.run_callbacks == nullptr) {
        return;
    }

    g_steam.run_callbacks();
    g_steam.snapshot.callback_pump_count += 1;
    g_steam.snapshot.last_callback_pump_ms = GetTickCount64();
}

SteamBootstrapSnapshot GetSteamBootstrapSnapshot() {
    std::scoped_lock lock(g_steam_mutex);
    return g_steam.snapshot;
}

}  // namespace sdmod
