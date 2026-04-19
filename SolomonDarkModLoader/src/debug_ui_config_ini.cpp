#include "debug_ui_config_internal.h"

#include <algorithm>
#include <cctype>
#include <cstdlib>
#include <fstream>

namespace sdmod::detail::debug_ui_config_internal {

std::string Trim(std::string value) {
    const auto is_space = [](unsigned char ch) { return std::isspace(ch) != 0; };

    value.erase(
        value.begin(),
        std::find_if(value.begin(), value.end(), [&](char ch) { return !is_space(static_cast<unsigned char>(ch)); }));
    value.erase(
        std::find_if(value.rbegin(), value.rend(), [&](char ch) { return !is_space(static_cast<unsigned char>(ch)); }).base(),
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

std::optional<uintptr_t> TryParseAddress(std::string value) {
    value = Trim(std::move(value));
    if (value.empty()) {
        return std::nullopt;
    }

    const auto base = value.size() > 2 && value[0] == '0' && (value[1] == 'x' || value[1] == 'X') ? 16 : 10;
    char* end = nullptr;
    const auto parsed = std::strtoull(value.c_str(), &end, base);
    if (end == value.c_str() || *end != '\0') {
        return std::nullopt;
    }

    return static_cast<uintptr_t>(parsed);
}

std::optional<size_t> TryParseSize(std::string value) {
    auto parsed = TryParseAddress(std::move(value));
    if (!parsed.has_value()) {
        return std::nullopt;
    }

    return static_cast<size_t>(*parsed);
}

bool LoadIniDocument(const std::filesystem::path& path, IniDocument* document, std::string* error_message) {
    if (document == nullptr) {
        if (error_message != nullptr) {
            *error_message = "INI destination is null.";
        }
        return false;
    }

    std::ifstream stream(path, std::ios::in | std::ios::binary);
    if (!stream.is_open()) {
        if (error_message != nullptr) {
            *error_message = "Unable to open " + path.string();
        }
        return false;
    }

    document->clear();

    std::string current_section;
    std::string line;
    size_t line_number = 0;
    while (std::getline(stream, line)) {
        ++line_number;

        if (!line.empty() && line.back() == '\r') {
            line.pop_back();
        }

        line = Trim(std::move(line));
        if (line.empty() || line[0] == ';' || line[0] == '#') {
            continue;
        }

        if (line.front() == '[') {
            if (line.back() != ']') {
                if (error_message != nullptr) {
                    *error_message = "Invalid section header at line " + std::to_string(line_number);
                }
                return false;
            }

            current_section = Trim(line.substr(1, line.size() - 2));
            if (current_section.empty()) {
                if (error_message != nullptr) {
                    *error_message = "Empty section header at line " + std::to_string(line_number);
                }
                return false;
            }

            (*document)[current_section];
            continue;
        }

        const auto separator = line.find('=');
        if (separator == std::string::npos) {
            if (error_message != nullptr) {
                *error_message = "Invalid key/value entry at line " + std::to_string(line_number);
            }
            return false;
        }

        if (current_section.empty()) {
            if (error_message != nullptr) {
                *error_message = "Key/value entry before any section at line " + std::to_string(line_number);
            }
            return false;
        }

        auto key = Trim(line.substr(0, separator));
        auto value = Trim(line.substr(separator + 1));
        if (key.empty()) {
            if (error_message != nullptr) {
                *error_message = "Empty key at line " + std::to_string(line_number);
            }
            return false;
        }

        (*document)[current_section][key] = value;
    }

    return true;
}

bool ReadRequiredBoolean(
    const IniSection& section,
    const char* key,
    bool* destination,
    std::string* error_message) {
    const auto value_it = section.find(key);
    if (value_it == section.end()) {
        if (error_message != nullptr) {
            *error_message = "Debug UI config is missing [overlay]." + std::string(key) + ".";
        }
        return false;
    }

    if (destination == nullptr || !TryParseBoolean(value_it->second, destination)) {
        if (error_message != nullptr) {
            *error_message = "Debug UI config contains an invalid [overlay]." + std::string(key) + " value.";
        }
        return false;
    }

    return true;
}

bool ReadRequiredAddress(
    const IniSection& section,
    const char* key,
    uintptr_t* destination,
    std::string* error_message) {
    const auto value_it = section.find(key);
    if (value_it == section.end()) {
        if (error_message != nullptr) {
            *error_message = "Debug UI config is missing [overlay]." + std::string(key) + ".";
        }
        return false;
    }

    const auto parsed = TryParseAddress(value_it->second);
    if (destination == nullptr || !parsed.has_value() || *parsed == 0) {
        if (error_message != nullptr) {
            *error_message = "Debug UI config contains an invalid [overlay]." + std::string(key) + " value.";
        }
        return false;
    }

    *destination = *parsed;
    return true;
}

bool ReadOptionalAddress(
    const IniSection& section,
    const char* key,
    uintptr_t* destination,
    std::string* error_message) {
    const auto value_it = section.find(key);
    if (value_it == section.end()) {
        return true;
    }

    const auto parsed = TryParseAddress(value_it->second);
    if (destination == nullptr || !parsed.has_value()) {
        if (error_message != nullptr) {
            *error_message = "Debug UI config contains an invalid [overlay]." + std::string(key) + " value.";
        }
        return false;
    }

    *destination = *parsed;
    return true;
}

bool ReadRequiredSize(
    const IniSection& section,
    const char* key,
    size_t* destination,
    std::string* error_message) {
    const auto value_it = section.find(key);
    if (value_it == section.end()) {
        if (error_message != nullptr) {
            *error_message = "Debug UI config is missing [overlay]." + std::string(key) + ".";
        }
        return false;
    }

    const auto parsed = TryParseSize(value_it->second);
    if (destination == nullptr || !parsed.has_value()) {
        if (error_message != nullptr) {
            *error_message = "Debug UI config contains an invalid [overlay]." + std::string(key) + " value.";
        }
        return false;
    }

    *destination = *parsed;
    return true;
}

bool ReadOptionalPositiveSize(
    const IniSection& section,
    const char* key,
    size_t* destination,
    std::string* error_message) {
    const auto value_it = section.find(key);
    if (value_it == section.end()) {
        return true;
    }

    const auto parsed = TryParseSize(value_it->second);
    if (destination == nullptr || !parsed.has_value() || *parsed == 0) {
        if (error_message != nullptr) {
            *error_message = "Debug UI config contains an invalid [overlay]." + std::string(key) + " value.";
        }
        return false;
    }

    *destination = *parsed;
    return true;
}

}  // namespace sdmod::detail::debug_ui_config_internal
