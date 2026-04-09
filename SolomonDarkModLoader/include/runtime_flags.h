#pragma once

#include <filesystem>
#include <string>

namespace sdmod {

enum class RuntimeProfile {
    Full,
    BootstrapOnly,
};

struct LoaderRuntimeFeatureFlags {
    bool lua_engine = true;
    bool native_mods = true;
    bool runtime_tick_service = true;
    bool debug_ui = true;
};

struct MultiplayerRuntimeFeatureFlags {
    bool steam_bootstrap = true;
    bool foundation = true;
    bool service_loop = true;
};

struct RuntimeFeatureFlags {
    RuntimeProfile profile = RuntimeProfile::Full;
    LoaderRuntimeFeatureFlags loader;
    MultiplayerRuntimeFeatureFlags multiplayer;
};

RuntimeFeatureFlags DefaultRuntimeFeatureFlags();
RuntimeFeatureFlags BootstrapOnlyRuntimeFeatureFlags();
bool LoadRuntimeFeatureFlags(
    const std::filesystem::path& stage_runtime_directory,
    RuntimeFeatureFlags* flags,
    std::string* error_message);
void SetActiveRuntimeFeatureFlags(const RuntimeFeatureFlags& flags);
const RuntimeFeatureFlags& GetActiveRuntimeFeatureFlags();
bool RuntimeFeatureFlagsEqual(const RuntimeFeatureFlags& left, const RuntimeFeatureFlags& right);
const char* RuntimeProfileName(RuntimeProfile profile);
std::string DescribeRuntimeFeatureFlags(const RuntimeFeatureFlags& flags);
std::filesystem::path GetRuntimeFlagsPath(const std::filesystem::path& stage_runtime_directory);

}  // namespace sdmod
