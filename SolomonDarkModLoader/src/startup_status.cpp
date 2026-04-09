#include "startup_status.h"

#include "logger.h"

#include <Windows.h>

#include <fstream>
#include <sstream>

namespace sdmod {
namespace {

constexpr wchar_t kStartupStatusFileName[] = L"startup-status.json";

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

}  // namespace sdmod
