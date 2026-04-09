#pragma once

#include <filesystem>
#include <string>
#include <vector>

namespace sdmod {

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
    std::filesystem::path entry_script_path;
    std::filesystem::path entry_dll_path;
    std::vector<std::string> required_capabilities;
    std::vector<std::string> optional_capabilities;

    bool HasLuaEntry() const {
        return !entry_script_path.empty();
    }

    bool HasNativeEntry() const {
        return !entry_dll_path.empty();
    }
};

struct RuntimeBootstrap {
    std::string api_version;
    std::filesystem::path stage_root;
    std::filesystem::path runtime_root;
    std::filesystem::path mods_root;
    std::filesystem::path sandbox_root;
    std::vector<RuntimeModDescriptor> mods;
};

bool LoadRuntimeBootstrap(
    const std::filesystem::path& stage_runtime_directory,
    RuntimeBootstrap* bootstrap,
    std::string* error_message);
std::filesystem::path GetRuntimeBootstrapPath(const std::filesystem::path& stage_runtime_directory);
std::string DescribeRuntimeBootstrap(const RuntimeBootstrap& bootstrap);

}  // namespace sdmod
