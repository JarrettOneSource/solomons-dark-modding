#include "runtime_bootstrap.h"

#include <algorithm>
#include <cctype>
#include <fstream>
#include <sstream>
#include <unordered_map>

namespace sdmod {
namespace {

constexpr wchar_t kRuntimeDirectoryName[] = L"runtime";
constexpr wchar_t kRuntimeBootstrapFileName[] = L"runtime-bootstrap.ini";

struct IniSection {
    std::unordered_map<std::string, std::string> values;
};

std::string Trim(std::string value) {
    const auto is_space = [](unsigned char ch) { return std::isspace(ch) != 0; };
    value.erase(
        value.begin(),
        std::find_if(value.begin(), value.end(), [&](char ch) { return !is_space(static_cast<unsigned char>(ch)); }));
    value.erase(
        std::find_if(value.rbegin(), value.rend(), [&](char ch) { return !is_space(static_cast<unsigned char>(ch)); })
            .base(),
        value.end());
    return value;
}

std::string ToLower(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char ch) {
        return static_cast<char>(std::tolower(ch));
    });
    return value;
}

bool TryParseUnsigned(const std::string& raw_value, std::size_t* parsed_value) {
    if (parsed_value == nullptr) {
        return false;
    }

    try {
        const auto parsed = std::stoull(raw_value);
        *parsed_value = static_cast<std::size_t>(parsed);
        return true;
    } catch (...) {
        return false;
    }
}

bool ParseIniFile(
    const std::filesystem::path& path,
    std::unordered_map<std::string, IniSection>* sections,
    std::string* error_message) {
    if (sections == nullptr || error_message == nullptr) {
        return false;
    }

    sections->clear();
    error_message->clear();

    std::ifstream stream(path, std::ios::in);
    if (!stream.is_open()) {
        *error_message = "Runtime bootstrap file was not found: " + path.string();
        return false;
    }

    std::string current_section = "runtime";
    std::string line;
    std::size_t line_number = 0;
    while (std::getline(stream, line)) {
        ++line_number;
        line = Trim(std::move(line));
        if (line.empty() || line[0] == '#') {
            continue;
        }

        if (line.front() == '[' && line.back() == ']') {
            current_section = ToLower(Trim(line.substr(1, line.size() - 2)));
            if (current_section.empty()) {
                *error_message =
                    "Runtime bootstrap file contains a blank section name at line " + std::to_string(line_number) +
                    ": " + path.string();
                return false;
            }

            continue;
        }

        const auto separator = line.find('=');
        if (separator == std::string::npos) {
            *error_message =
                "Runtime bootstrap file contains an invalid line at " + std::to_string(line_number) + ": " +
                path.string();
            return false;
        }

        const auto key = ToLower(Trim(line.substr(0, separator)));
        const auto value = Trim(line.substr(separator + 1));
        if (key.empty()) {
            *error_message =
                "Runtime bootstrap file contains a blank key at line " + std::to_string(line_number) + ": " +
                path.string();
            return false;
        }

        (*sections)[current_section].values[key] = value;
    }

    return true;
}

const std::string* FindSectionValue(
    const std::unordered_map<std::string, IniSection>& sections,
    const std::string& section_name,
    const std::string& key) {
    const auto section_it = sections.find(section_name);
    if (section_it == sections.end()) {
        return nullptr;
    }

    const auto value_it = section_it->second.values.find(key);
    if (value_it == section_it->second.values.end()) {
        return nullptr;
    }

    return &value_it->second;
}

bool TryReadRequiredValue(
    const std::unordered_map<std::string, IniSection>& sections,
    const std::string& section_name,
    const std::string& key,
    std::string* value,
    std::string* error_message,
    const std::filesystem::path& path) {
    if (value == nullptr || error_message == nullptr) {
        return false;
    }

    const auto* found_value = FindSectionValue(sections, section_name, key);
    if (found_value == nullptr) {
        *error_message =
            "Runtime bootstrap file is missing '" + key + "' in section [" + section_name + "]: " + path.string();
        return false;
    }

    *value = *found_value;
    return true;
}

std::vector<std::string> SplitCapabilities(const std::string& raw_value) {
    std::vector<std::string> values;
    std::string current;
    std::istringstream stream(raw_value);
    while (std::getline(stream, current, ',')) {
        current = Trim(std::move(current));
        if (!current.empty()) {
            values.push_back(std::move(current));
        }
    }

    return values;
}

}  // namespace

bool LoadRuntimeBootstrap(
    const std::filesystem::path& stage_runtime_directory,
    RuntimeBootstrap* bootstrap,
    std::string* error_message) {
    if (bootstrap == nullptr || error_message == nullptr) {
        return false;
    }

    *bootstrap = RuntimeBootstrap{};
    error_message->clear();

    const auto path = GetRuntimeBootstrapPath(stage_runtime_directory);
    std::unordered_map<std::string, IniSection> sections;
    if (!ParseIniFile(path, &sections, error_message)) {
        return false;
    }

    std::string runtime_api_version;
    if (!TryReadRequiredValue(sections, "runtime", "api_version", &runtime_api_version, error_message, path)) {
        return false;
    }

    std::string stage_root_path;
    if (!TryReadRequiredValue(sections, "runtime", "stage_root_path", &stage_root_path, error_message, path)) {
        return false;
    }

    std::string runtime_root_path;
    if (!TryReadRequiredValue(sections, "runtime", "runtime_root_path", &runtime_root_path, error_message, path)) {
        return false;
    }

    std::string mods_root_path;
    if (!TryReadRequiredValue(sections, "runtime", "mods_root_path", &mods_root_path, error_message, path)) {
        return false;
    }

    std::string sandbox_root_path;
    if (!TryReadRequiredValue(sections, "runtime", "sandbox_root_path", &sandbox_root_path, error_message, path)) {
        return false;
    }

    std::string mod_count_value;
    if (!TryReadRequiredValue(sections, "runtime", "mod_count", &mod_count_value, error_message, path)) {
        return false;
    }

    std::size_t mod_count = 0;
    if (!TryParseUnsigned(mod_count_value, &mod_count)) {
        *error_message = "Runtime bootstrap file contains an invalid mod_count in " + path.string();
        return false;
    }

    bootstrap->api_version = std::move(runtime_api_version);
    bootstrap->stage_root = std::filesystem::path(stage_root_path);
    bootstrap->runtime_root = std::filesystem::path(runtime_root_path);
    bootstrap->mods_root = std::filesystem::path(mods_root_path);
    bootstrap->sandbox_root = std::filesystem::path(sandbox_root_path);
    bootstrap->mods.reserve(mod_count);

    for (std::size_t index = 0; index < mod_count; ++index) {
        const auto section_name = "mod." + std::to_string(index);
        RuntimeModDescriptor mod;
        if (!TryReadRequiredValue(sections, section_name, "id", &mod.id, error_message, path) ||
            !TryReadRequiredValue(sections, section_name, "storage_key", &mod.storage_key, error_message, path) ||
            !TryReadRequiredValue(sections, section_name, "name", &mod.name, error_message, path) ||
            !TryReadRequiredValue(sections, section_name, "version", &mod.version, error_message, path) ||
            !TryReadRequiredValue(sections, section_name, "api_version", &mod.api_version, error_message, path) ||
            !TryReadRequiredValue(sections, section_name, "runtime_kind", &mod.runtime_kind, error_message, path)) {
            return false;
        }

        std::string root_path;
        std::string manifest_path;
        std::string sandbox_root;
        std::string data_root;
        std::string cache_root;
        std::string temp_root;
        std::string entry_script_path;
        std::string entry_dll_path;
        std::string required_capabilities;
        std::string optional_capabilities;

        if (!TryReadRequiredValue(sections, section_name, "root_path", &root_path, error_message, path) ||
            !TryReadRequiredValue(sections, section_name, "manifest_path", &manifest_path, error_message, path) ||
            !TryReadRequiredValue(
                sections,
                section_name,
                "sandbox_root_path",
                &sandbox_root,
                error_message,
                path) ||
            !TryReadRequiredValue(sections, section_name, "data_root_path", &data_root, error_message, path) ||
            !TryReadRequiredValue(sections, section_name, "cache_root_path", &cache_root, error_message, path) ||
            !TryReadRequiredValue(sections, section_name, "temp_root_path", &temp_root, error_message, path) ||
            !TryReadRequiredValue(
                sections,
                section_name,
                "entry_script_path",
                &entry_script_path,
                error_message,
                path) ||
            !TryReadRequiredValue(sections, section_name, "entry_dll_path", &entry_dll_path, error_message, path) ||
            !TryReadRequiredValue(
                sections,
                section_name,
                "required_capabilities",
                &required_capabilities,
                error_message,
                path) ||
            !TryReadRequiredValue(
                sections,
                section_name,
                "optional_capabilities",
                &optional_capabilities,
                error_message,
                path)) {
            return false;
        }

        mod.root_path = std::filesystem::path(root_path);
        mod.manifest_path = std::filesystem::path(manifest_path);
        mod.sandbox_root_path = std::filesystem::path(sandbox_root);
        mod.data_root_path = std::filesystem::path(data_root);
        mod.cache_root_path = std::filesystem::path(cache_root);
        mod.temp_root_path = std::filesystem::path(temp_root);
        if (!entry_script_path.empty()) {
            mod.entry_script_path = std::filesystem::path(entry_script_path);
        }
        if (!entry_dll_path.empty()) {
            mod.entry_dll_path = std::filesystem::path(entry_dll_path);
        }

        mod.required_capabilities = SplitCapabilities(required_capabilities);
        mod.optional_capabilities = SplitCapabilities(optional_capabilities);
        bootstrap->mods.push_back(std::move(mod));
    }

    return true;
}

std::filesystem::path GetRuntimeBootstrapPath(const std::filesystem::path& stage_runtime_directory) {
    return stage_runtime_directory / kRuntimeDirectoryName / kRuntimeBootstrapFileName;
}

std::string DescribeRuntimeBootstrap(const RuntimeBootstrap& bootstrap) {
    std::size_t lua_mod_count = 0;
    std::size_t native_mod_count = 0;
    for (const auto& mod : bootstrap.mods) {
        if (mod.HasLuaEntry()) {
            ++lua_mod_count;
        }
        if (mod.HasNativeEntry()) {
            ++native_mod_count;
        }
    }

    std::ostringstream stream;
    stream << "api_version=" << bootstrap.api_version
           << " mods=" << bootstrap.mods.size()
           << " lua=" << lua_mod_count
           << " native=" << native_mod_count
           << " runtime_root=" << bootstrap.runtime_root.string();
    return stream.str();
}

}  // namespace sdmod
