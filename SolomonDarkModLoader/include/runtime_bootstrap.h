#pragma once

#include <cstdint>
#include <filesystem>
#include <string>
#include <vector>

namespace sdmod {

inline constexpr char kRuntimeApiVersion[] = "0.2.0";

struct RuntimeBoneyardDescriptor {
    std::string display_name;
    std::string source_mod_id;
    std::string source_mod_name;
    std::string source_mod_version;
    std::string filename;
    std::string source_relative_path;
    std::string content_sha256;
    std::filesystem::path stock_relative_path;
    std::filesystem::path stage_path;
    std::uint64_t file_length = 0;
    std::uint32_t chunk_count = 0;
    std::uint32_t named_buffer_count = 0;
    std::uint32_t max_depth = 0;
};

struct RuntimeModDescriptor {
    std::string id;
    std::string storage_key;
    std::string name;
    std::string version;
    std::string api_version;
    std::string runtime_kind;
    std::filesystem::path root_path;
    std::filesystem::path manifest_path;
    std::filesystem::path sandbox_root_path;
    std::filesystem::path data_root_path;
    std::filesystem::path cache_root_path;
    std::filesystem::path temp_root_path;
    bool hot_reload = false;
    std::filesystem::path source_root_path;
    std::filesystem::path source_entry_script_path;
    std::filesystem::path entry_script_path;
    std::vector<std::string> required_capabilities;
    std::vector<std::string> optional_capabilities;
    std::vector<std::string> provides;
    std::vector<std::string> requires;

    bool HasLuaEntry() const {
        return !entry_script_path.empty();
    }
};

struct RuntimeBootstrap {
    std::string api_version;
    std::filesystem::path stage_root;
    std::filesystem::path runtime_root;
    std::filesystem::path mods_root;
    std::filesystem::path sandbox_root;
    std::vector<RuntimeModDescriptor> mods;
    std::vector<RuntimeBoneyardDescriptor> boneyards;
};

bool LoadRuntimeBootstrap(
    const std::filesystem::path& stage_runtime_directory,
    RuntimeBootstrap* bootstrap,
    std::string* error_message);
std::filesystem::path GetRuntimeBootstrapPath(const std::filesystem::path& stage_runtime_directory);
std::string DescribeRuntimeBootstrap(const RuntimeBootstrap& bootstrap);

}  // namespace sdmod
