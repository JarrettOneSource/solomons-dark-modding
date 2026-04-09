#pragma once

#include <cstdint>
#include <string>

namespace sdmod {

struct SteamBootstrapSnapshot {
    bool requested = false;
    bool module_loaded = false;
    bool exports_loaded = false;
    bool initialized = false;
    bool transport_interfaces_ready = false;
    bool using_init_safe = false;
    uint64_t local_steam_id = 0;
    uint64_t callback_pump_count = 0;
    uint64_t last_callback_pump_ms = 0;
    std::string module_path;
    std::string persona_name;
    std::string status_text;
    std::string error_text;
};

bool InitializeSteamBootstrap();
void ShutdownSteamBootstrap();
void SteamBootstrapTick();
SteamBootstrapSnapshot GetSteamBootstrapSnapshot();

}  // namespace sdmod
