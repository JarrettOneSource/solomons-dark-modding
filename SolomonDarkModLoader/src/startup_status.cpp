#include "startup_status.h"

#include "logger.h"

#include <Windows.h>

#include <fstream>
#include <sstream>

namespace sdmod {
namespace {

constexpr wchar_t kStartupStatusFileName[] = L"startup-status.json";
constexpr wchar_t kMultiplayerSessionStatusFileName[] =
    L"multiplayer-session-status.json";

std::string EscapeJsonString(const std::string& value) {
    std::string escaped;
    escaped.reserve(value.size() + 8);
    for (const auto ch : value) {
        switch (ch) {
            case '\\':
                escaped += "\\\\";
                break;
            case '"':
                escaped += "\\\"";
                break;
            case '\r':
                escaped += "\\r";
                break;
            case '\n':
                escaped += "\\n";
                break;
            case '\t':
                escaped += "\\t";
                break;
            default:
                escaped.push_back(ch);
                break;
        }
    }

    return escaped;
}

std::string NarrowPath(const std::filesystem::path& path) {
    return path.string();
}

std::string MakeUtcTimestamp() {
    SYSTEMTIME utc_now{};
    GetSystemTime(&utc_now);

    std::ostringstream stream;
    stream.fill('0');
    stream << std::setw(4) << utc_now.wYear << '-'
           << std::setw(2) << utc_now.wMonth << '-'
           << std::setw(2) << utc_now.wDay << 'T'
           << std::setw(2) << utc_now.wHour << ':'
           << std::setw(2) << utc_now.wMinute << ':'
           << std::setw(2) << utc_now.wSecond << '.'
           << std::setw(3) << utc_now.wMilliseconds << 'Z';
    return stream.str();
}

}  // namespace

std::filesystem::path GetStartupStatusPath(const std::filesystem::path& stage_runtime_directory) {
    return stage_runtime_directory / kStartupStatusFileName;
}

void ResetStartupStatus(const std::filesystem::path& stage_runtime_directory) {
    std::error_code error;
    std::filesystem::remove(GetStartupStatusPath(stage_runtime_directory), error);
}

void WriteStartupStatus(
    const std::filesystem::path& stage_runtime_directory,
    const StartupStatusSnapshot& snapshot) {
    const auto status_path = GetStartupStatusPath(stage_runtime_directory);
    std::error_code create_error;
    std::filesystem::create_directories(status_path.parent_path(), create_error);

    std::ofstream stream(status_path, std::ios::binary | std::ios::trunc);
    if (!stream.is_open()) {
        Log("Failed to write startup status: " + status_path.string());
        return;
    }

    stream << "{\n";
    stream << "  \"updatedAtUtc\": \"" << EscapeJsonString(MakeUtcTimestamp()) << "\",\n";
    stream << "  \"completed\": " << (snapshot.completed ? "true" : "false") << ",\n";
    stream << "  \"success\": " << (snapshot.success ? "true" : "false") << ",\n";
    stream << "  \"launchToken\": \"" << EscapeJsonString(snapshot.launch_token) << "\",\n";
    stream << "  \"code\": \"" << EscapeJsonString(snapshot.code) << "\",\n";
    stream << "  \"message\": \"" << EscapeJsonString(snapshot.message) << "\",\n";
    stream << "  \"logPath\": \"" << EscapeJsonString(NarrowPath(snapshot.log_path)) << "\",\n";
    stream << "  \"runtimeFlagsPath\": \"" << EscapeJsonString(NarrowPath(snapshot.runtime_flags_path)) << "\",\n";
    stream << "  \"runtimeBootstrapPath\": \"" << EscapeJsonString(NarrowPath(snapshot.runtime_bootstrap_path))
           << "\",\n";
    stream << "  \"binaryLayoutPath\": \"" << EscapeJsonString(NarrowPath(snapshot.binary_layout_path)) << "\",\n";
    stream << "  \"binaryLayoutLoaded\": " << (snapshot.binary_layout_loaded ? "true" : "false") << ",\n";
    stream << "  \"steamTransportReady\": " << (snapshot.steam_transport_ready ? "true" : "false") << ",\n";
    stream << "  \"multiplayerFoundationReady\": "
           << (snapshot.multiplayer_foundation_ready ? "true" : "false") << ",\n";
    stream << "  \"luaEngineEnabled\": " << (snapshot.lua_engine_enabled ? "true" : "false") << ",\n";
    stream << "  \"luaEngineInitialized\": " << (snapshot.lua_engine_initialized ? "true" : "false") << ",\n";
    stream << "  \"luaLoadedModCount\": " << snapshot.lua_loaded_mod_count << ",\n";
    stream << "  \"botRuntimeInitialized\": " << (snapshot.bot_runtime_initialized ? "true" : "false") << ",\n";
    stream << "  \"nativeModsEnabled\": " << (snapshot.native_mods_enabled ? "true" : "false") << ",\n";
    stream << "  \"nativeModCount\": " << snapshot.native_mod_count << ",\n";
    stream << "  \"runtimeTickServiceEnabled\": "
           << (snapshot.runtime_tick_service_enabled ? "true" : "false") << ",\n";
    stream << "  \"runtimeTickServiceRunning\": "
           << (snapshot.runtime_tick_service_running ? "true" : "false") << "\n";
    stream << "}\n";
}

std::filesystem::path GetMultiplayerSessionStatusPath(
    const std::filesystem::path& stage_runtime_directory) {
    return stage_runtime_directory / kMultiplayerSessionStatusFileName;
}

void ResetMultiplayerSessionStatus(
    const std::filesystem::path& stage_runtime_directory) {
    std::error_code error;
    std::filesystem::remove(
        GetMultiplayerSessionStatusPath(stage_runtime_directory),
        error);
}

void WriteMultiplayerSessionStatus(
    const std::filesystem::path& stage_runtime_directory,
    const MultiplayerSessionStatusSnapshot& snapshot) {
    const auto status_path =
        GetMultiplayerSessionStatusPath(stage_runtime_directory);
    std::error_code create_error;
    std::filesystem::create_directories(
        status_path.parent_path(),
        create_error);

    std::ofstream stream(status_path, std::ios::binary | std::ios::trunc);
    if (!stream.is_open()) {
        Log("Failed to write multiplayer session status: " +
            status_path.string());
        return;
    }

    stream << "{\n";
    stream << "  \"updatedAtUtc\": \""
           << EscapeJsonString(MakeUtcTimestamp()) << "\",\n";
    stream << "  \"launchToken\": \""
           << EscapeJsonString(snapshot.launch_token) << "\",\n";
    stream << "  \"enabled\": "
           << (snapshot.enabled ? "true" : "false") << ",\n";
    stream << "  \"isHost\": "
           << (snapshot.is_host ? "true" : "false") << ",\n";
    stream << "  \"phase\": \""
           << EscapeJsonString(snapshot.phase) << "\",\n";
    stream << "  \"gamePhase\": \""
           << EscapeJsonString(snapshot.game_phase) << "\",\n";
    stream << "  \"appId\": " << snapshot.app_id << ",\n";
    stream << "  \"lobbyId\": " << snapshot.lobby_id << ",\n";
    stream << "  \"hostSteamId\": " << snapshot.host_steam_id << ",\n";
    stream << "  \"localSteamId\": " << snapshot.local_steam_id << ",\n";
    stream << "  \"personaName\": \""
           << EscapeJsonString(snapshot.persona_name) << "\",\n";
    stream << "  \"privacy\": \""
           << EscapeJsonString(snapshot.privacy) << "\",\n";
    stream << "  \"protocolVersion\": " << snapshot.protocol_version << ",\n";
    stream << "  \"manifestSha256\": \""
           << EscapeJsonString(snapshot.manifest_sha256) << "\",\n";
    stream << "  \"friendSteamIds\": [";
    for (std::size_t index = 0; index < snapshot.friend_steam_ids.size(); ++index) {
        stream << (index == 0 ? "" : ", ") << snapshot.friend_steam_ids[index];
    }
    stream << "],\n";
    stream << "  \"maxParticipants\": "
           << snapshot.max_participants << ",\n";
    stream << "  \"authenticatedPeerCount\": "
           << snapshot.authenticated_peer_count << ",\n";
    stream << "  \"overlayEnabled\": "
           << (snapshot.overlay_enabled ? "true" : "false") << ",\n";
    stream << "  \"inviteDialogOpened\": "
           << (snapshot.invite_dialog_opened ? "true" : "false") << ",\n";
    stream << "  \"inviteSent\": "
           << (snapshot.invite_sent ? "true" : "false") << ",\n";
    stream << "  \"routeRelayed\": "
           << (snapshot.route_relayed ? "true" : "false") << ",\n";
    stream << "  \"routePingMs\": " << snapshot.route_ping_ms << ",\n";
    stream << "  \"members\": [";
    for (std::size_t index = 0; index < snapshot.members.size(); ++index) {
        const auto& member = snapshot.members[index];
        stream << (index == 0 ? "\n" : ",\n")
               << "    {\"steamId\": " << member.steam_id
               << ", \"name\": \"" << EscapeJsonString(member.name)
               << "\", \"isHost\": " << (member.is_host ? "true" : "false")
               << ", \"isLocal\": " << (member.is_local ? "true" : "false")
               << "}";
    }
    stream << (snapshot.members.empty() ? "],\n" : "\n  ],\n");
    stream << "  \"statusText\": \""
           << EscapeJsonString(snapshot.status_text) << "\",\n";
    stream << "  \"errorText\": \""
           << EscapeJsonString(snapshot.error_text) << "\"\n";
    stream << "}\n";
}

}  // namespace sdmod
