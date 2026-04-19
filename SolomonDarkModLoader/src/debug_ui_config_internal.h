#pragma once

#include "debug_ui_config.h"

#include <filesystem>
#include <map>
#include <optional>
#include <string>

namespace sdmod::detail::debug_ui_config_internal {

using IniSection = std::map<std::string, std::string>;
using IniDocument = std::map<std::string, IniSection>;

std::string Trim(std::string value);
std::string ToLower(std::string value);
bool TryParseBoolean(std::string value, bool* parsed);
std::optional<uintptr_t> TryParseAddress(std::string value);
std::optional<size_t> TryParseSize(std::string value);
bool LoadIniDocument(const std::filesystem::path& path, IniDocument* document, std::string* error_message);

bool ReadRequiredBoolean(
    const IniSection& section,
    const char* key,
    bool* destination,
    std::string* error_message);
bool ReadRequiredAddress(
    const IniSection& section,
    const char* key,
    uintptr_t* destination,
    std::string* error_message);
bool ReadOptionalAddress(
    const IniSection& section,
    const char* key,
    uintptr_t* destination,
    std::string* error_message);
bool ReadRequiredSize(
    const IniSection& section,
    const char* key,
    size_t* destination,
    std::string* error_message);
bool ReadOptionalPositiveSize(
    const IniSection& section,
    const char* key,
    size_t* destination,
    std::string* error_message);

}  // namespace sdmod::detail::debug_ui_config_internal
