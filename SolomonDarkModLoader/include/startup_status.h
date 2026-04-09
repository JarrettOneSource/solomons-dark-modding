#pragma once

#include <filesystem>
#include <string>

namespace sdmod {

struct StartupStatusSnapshot {
    bool completed = false;
    bool success = false;
    std::string launch_token;
    std::string code;
    std::string message;
    std::filesystem::path log_path;
    std::filesystem::path runtime_flags_path;
    std::filesystem::path runtime_bootstrap_path;
    std::filesystem::path binary_layout_path;
    bool binary_layout_loaded = false;
    bool steam_transport_ready = false;
    bool multiplayer_foundation_ready = false;
    bool lua_engine_enabled = false;
    bool lua_engine_initialized = false;
    int lua_loaded_mod_count = 0;
    bool bot_runtime_initialized = false;
    bool native_mods_enabled = false;
    int native_mod_count = 0;
    bool runtime_tick_service_enabled = false;
    bool runtime_tick_service_running = false;
};

std::filesystem::path GetStartupStatusPath(const std::filesystem::path& stage_runtime_directory);
void ResetStartupStatus(const std::filesystem::path& stage_runtime_directory);
void WriteStartupStatus(
    const std::filesystem::path& stage_runtime_directory,
    const StartupStatusSnapshot& snapshot);

}  // namespace sdmod
