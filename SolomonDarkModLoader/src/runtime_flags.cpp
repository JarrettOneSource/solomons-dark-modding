#include "runtime_flags.h"

#include <algorithm>
#include <array>
#include <cctype>
#include <fstream>
#include <sstream>

namespace sdmod {
namespace {

constexpr wchar_t kRuntimeDirectoryName[] = L"runtime";
constexpr wchar_t kRuntimeFlagsFileName[] = L"runtime-flags.ini";

RuntimeFeatureFlags g_runtime_feature_flags = DefaultRuntimeFeatureFlags();

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

bool TryParseBoolean(std::string value, bool* parsed) {
    if (parsed == nullptr) {
        return false;
    }

    value = ToLower(Trim(std::move(value)));
    if (value == "1" || value == "true" || value == "yes" || value == "on") {
        *parsed = true;
        return true;
    }

    if (value == "0" || value == "false" || value == "no" || value == "off") {
        *parsed = false;
        return true;
    }

    return false;
}

void NormalizeRuntimeFeatureFlags(RuntimeFeatureFlags* flags) {
    if (flags == nullptr) {
        return;
    }

    if (!flags->loader.native_mods) {
        flags->loader.runtime_tick_service = false;
    }

    if (!flags->multiplayer.foundation) {
        flags->multiplayer.service_loop = false;
    }
}

bool ApplyFlagOverride(RuntimeFeatureFlags* flags, const std::string& raw_key, bool value) {
    if (flags == nullptr) {
        return false;
    }

    const auto key = ToLower(Trim(raw_key));
    if (key == "loader.lua_engine") {
        flags->loader.lua_engine = value;
        return true;
    }
    if (key == "loader.native_mods") {
        flags->loader.native_mods = value;
        return true;
    }
    if (key == "loader.runtime_tick_service") {
        flags->loader.runtime_tick_service = value;
        return true;
    }
    if (key == "loader.debug_ui") {
        flags->loader.debug_ui = value;
        return true;
    }
    if (key == "multiplayer.steam_bootstrap") {
        flags->multiplayer.steam_bootstrap = value;
        return true;
    }
    if (key == "multiplayer.foundation") {
        flags->multiplayer.foundation = value;
        return true;
    }
    if (key == "multiplayer.service_loop") {
        flags->multiplayer.service_loop = value;
        return true;
    }

    return false;
}

}  // namespace

RuntimeFeatureFlags DefaultRuntimeFeatureFlags() {
    RuntimeFeatureFlags flags;
    NormalizeRuntimeFeatureFlags(&flags);
    return flags;
}

RuntimeFeatureFlags BootstrapOnlyRuntimeFeatureFlags() {
    RuntimeFeatureFlags flags;
    flags.profile = RuntimeProfile::BootstrapOnly;
    flags.loader.lua_engine = false;
    flags.loader.native_mods = false;
    flags.loader.runtime_tick_service = false;
    flags.loader.debug_ui = false;
    NormalizeRuntimeFeatureFlags(&flags);
    return flags;
}

bool LoadRuntimeFeatureFlags(
    const std::filesystem::path& stage_runtime_directory,
    RuntimeFeatureFlags* flags,
    std::string* error_message) {
    if (flags == nullptr || error_message == nullptr) {
        return false;
    }

    *flags = DefaultRuntimeFeatureFlags();
    error_message->clear();

    const auto path = GetRuntimeFlagsPath(stage_runtime_directory);
    std::ifstream stream(path, std::ios::in);
    if (!stream.is_open()) {
        *error_message = "Runtime flags file was not found: " + path.string();
        return false;
    }

    std::string line;
    std::size_t line_number = 0;
    while (std::getline(stream, line)) {
        ++line_number;
        line = Trim(std::move(line));
        if (line.empty() || line[0] == '#') {
            continue;
        }

        const auto separator = line.find('=');
        if (separator == std::string::npos) {
            *error_message =
                "Runtime flags file contains an invalid line at " + std::to_string(line_number) + ": " + path.string();
            return false;
        }

        const auto key = Trim(line.substr(0, separator));
        const auto value = Trim(line.substr(separator + 1));
        if (key.empty()) {
            *error_message =
                "Runtime flags file contains a blank key at line " + std::to_string(line_number) + ": " +
                path.string();
            return false;
        }

        if (ToLower(key) == "profile") {
            const auto lowered = ToLower(value);
            if (lowered == "full") {
                *flags = DefaultRuntimeFeatureFlags();
                continue;
            }

            if (lowered == "bootstrap_only" || lowered == "bootstrap-only") {
                *flags = BootstrapOnlyRuntimeFeatureFlags();
                continue;
            }

            *error_message =
                "Unsupported runtime profile '" + value + "' in " + path.string() + " at line " +
                std::to_string(line_number);
            return false;
        }

        bool parsed = false;
        if (!TryParseBoolean(value, &parsed)) {
            *error_message =
                "Runtime flags file contains an invalid boolean for key '" + key + "' in " + path.string() +
                " at line " + std::to_string(line_number);
            return false;
        }

        if (!ApplyFlagOverride(flags, key, parsed)) {
            *error_message =
                "Runtime flags file contains an unknown key '" + key + "' in " + path.string() + " at line " +
                std::to_string(line_number);
            return false;
        }
    }

    NormalizeRuntimeFeatureFlags(flags);
    return true;
}

void SetActiveRuntimeFeatureFlags(const RuntimeFeatureFlags& flags) {
    g_runtime_feature_flags = flags;
}

const RuntimeFeatureFlags& GetActiveRuntimeFeatureFlags() {
    return g_runtime_feature_flags;
}

bool RuntimeFeatureFlagsEqual(const RuntimeFeatureFlags& left, const RuntimeFeatureFlags& right) {
    return left.profile == right.profile &&
           left.loader.lua_engine == right.loader.lua_engine &&
           left.loader.native_mods == right.loader.native_mods &&
           left.loader.runtime_tick_service == right.loader.runtime_tick_service &&
           left.loader.debug_ui == right.loader.debug_ui &&
           left.multiplayer.steam_bootstrap == right.multiplayer.steam_bootstrap &&
           left.multiplayer.foundation == right.multiplayer.foundation &&
           left.multiplayer.service_loop == right.multiplayer.service_loop;
}

const char* RuntimeProfileName(RuntimeProfile profile) {
    switch (profile) {
        case RuntimeProfile::BootstrapOnly:
            return "bootstrap_only";
        case RuntimeProfile::Full:
        default:
            return "full";
    }
}

std::string DescribeRuntimeFeatureFlags(const RuntimeFeatureFlags& flags) {
    std::ostringstream stream;
    stream << "profile=" << RuntimeProfileName(flags.profile)
           << " loader{lua_engine=" << (flags.loader.lua_engine ? 1 : 0)
           << ",native_mods=" << (flags.loader.native_mods ? 1 : 0)
           << ",runtime_tick_service=" << (flags.loader.runtime_tick_service ? 1 : 0)
           << ",debug_ui=" << (flags.loader.debug_ui ? 1 : 0)
           << "} multiplayer{steam_bootstrap=" << (flags.multiplayer.steam_bootstrap ? 1 : 0)
           << ",foundation=" << (flags.multiplayer.foundation ? 1 : 0)
           << ",service_loop=" << (flags.multiplayer.service_loop ? 1 : 0)
           << "}";
    return stream.str();
}

std::filesystem::path GetRuntimeFlagsPath(const std::filesystem::path& stage_runtime_directory) {
    return stage_runtime_directory / kRuntimeDirectoryName / kRuntimeFlagsFileName;
}

}  // namespace sdmod
