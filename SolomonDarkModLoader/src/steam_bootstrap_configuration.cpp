#include "steam_bootstrap_internal.h"

#include "logger.h"

#include <cctype>
#include <cwctype>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <string>

namespace sdmod::detail {
namespace {

constexpr wchar_t kEnableEnvironmentVariable[] = L"SDMOD_STEAM_BOOTSTRAP";
constexpr wchar_t kAppIdEnvironmentVariable[] = L"SDMOD_STEAM_APP_ID";
constexpr wchar_t kAppIdPathEnvironmentVariable[] = L"SDMOD_STEAM_APP_ID_PATH";
constexpr wchar_t kApiDllPathEnvironmentVariable[] = L"SDMOD_STEAM_API_DLL";
constexpr wchar_t kAllowRestartEnvironmentVariable[] = L"SDMOD_STEAM_ALLOW_RESTART";
constexpr wchar_t kDefaultAppIdFileName[] = L"steam_appid.txt";

std::wstring GetEnvironmentVariableString(const wchar_t* name) {
    const auto required_size = GetEnvironmentVariableW(name, nullptr, 0);
    if (required_size == 0) {
        return {};
    }

    std::wstring value(required_size, L'\0');
    const auto written = GetEnvironmentVariableW(name, value.data(), required_size);
    if (written == 0) {
        return {};
    }

    value.resize(written);
    return value;
}

std::wstring TrimWhitespace(std::wstring value) {
    auto is_space = [](wchar_t ch) { return std::iswspace(static_cast<wint_t>(ch)) != 0; };

    while (!value.empty() && is_space(value.front())) {
        value.erase(value.begin());
    }

    while (!value.empty() && is_space(value.back())) {
        value.pop_back();
    }

    return value;
}

bool ReadBooleanEnvironmentVariable(const wchar_t* name) {
    auto value = TrimWhitespace(GetEnvironmentVariableString(name));
    if (value.empty()) {
        return false;
    }

    for (auto& ch : value) {
        ch = static_cast<wchar_t>(std::towlower(static_cast<wint_t>(ch)));
    }

    return value == L"1" || value == L"true" || value == L"yes" || value == L"on";
}

std::string ReadTrimmedFile(const std::filesystem::path& path) {
    std::ifstream input(path);
    if (!input) {
        return {};
    }

    std::string content;
    std::getline(input, content);
    while (!content.empty() && std::isspace(static_cast<unsigned char>(content.back())) != 0) {
        content.pop_back();
    }
    return content;
}

std::uint32_t ReadAppId() {
    const auto text = TrimWhitespace(GetEnvironmentVariableString(kAppIdEnvironmentVariable));
    if (text.empty()) {
        return 0;
    }

    return static_cast<std::uint32_t>(wcstoul(text.c_str(), nullptr, 10));
}

}  // namespace

bool ReadSteamBootstrapConfiguration(const std::filesystem::path& host_process_directory,
                                     SteamBootstrapConfiguration* configuration,
                                     SteamBootstrapSnapshot* snapshot) {
    if (configuration == nullptr || snapshot == nullptr) {
        return false;
    }

    *configuration = SteamBootstrapConfiguration{};
    snapshot->status_text = "Steam bootstrap not requested.";

    if (!ReadBooleanEnvironmentVariable(kEnableEnvironmentVariable)) {
        return false;
    }

    snapshot->requested = true;
    snapshot->status_text = "Preparing Steam bootstrap.";

    configuration->app_id = ReadAppId();
    if (configuration->app_id == 0) {
        snapshot->error_text = "Missing or invalid SDMOD_STEAM_APP_ID.";
        snapshot->status_text = "Steam AppID is invalid.";
        return false;
    }

    configuration->allow_restart_if_necessary = ReadBooleanEnvironmentVariable(kAllowRestartEnvironmentVariable);

    const auto app_id_path = TrimWhitespace(GetEnvironmentVariableString(kAppIdPathEnvironmentVariable));
    configuration->app_id_path = app_id_path.empty()
        ? (host_process_directory / kDefaultAppIdFileName)
        : std::filesystem::path(app_id_path);

    const auto api_dll_path = TrimWhitespace(GetEnvironmentVariableString(kApiDllPathEnvironmentVariable));
    if (!api_dll_path.empty()) {
        configuration->api_dll_path = std::filesystem::path(api_dll_path);
    }

    return true;
}

void LogSteamBootstrapConfiguration(const SteamBootstrapConfiguration& configuration) {
    std::ostringstream message;
    message << "Steam bootstrap: requested with AppID=" << configuration.app_id
            << ", steam_appid=" << configuration.app_id_path.string()
            << ", steam_api=" << (configuration.api_dll_path.empty() ? std::string("(default lookup)") : configuration.api_dll_path.string());
    Log(message.str());

    if (std::filesystem::exists(configuration.app_id_path)) {
        const auto staged_app_id = ReadTrimmedFile(configuration.app_id_path);
        if (!staged_app_id.empty()) {
            Log("Steam bootstrap: staged steam_appid.txt contains " + staged_app_id);
        }
    } else {
        Log("Steam bootstrap: steam_appid.txt was not present at " + configuration.app_id_path.string());
    }
}

}  // namespace sdmod::detail
