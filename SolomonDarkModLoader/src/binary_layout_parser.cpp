#include "binary_layout_internal.h"

#include <algorithm>
#include <cctype>
#include <fstream>
#include <optional>
#include <stdexcept>

namespace sdmod {
namespace {

std::string Trim(std::string_view value) {
    auto begin = value.begin();
    auto end = value.end();

    while (begin != end && std::isspace(static_cast<unsigned char>(*begin)) != 0) {
        ++begin;
    }

    while (begin != end && std::isspace(static_cast<unsigned char>(*(end - 1))) != 0) {
        --end;
    }

    return std::string(begin, end);
}

bool StartsWith(std::string_view value, std::string_view prefix) {
    return value.size() >= prefix.size() && value.substr(0, prefix.size()) == prefix;
}

std::vector<std::string> SplitCommaSeparated(std::string_view value) {
    std::vector<std::string> parts;
    size_t start = 0;
    while (start < value.size()) {
        const auto comma = value.find(',', start);
        const auto token = comma == std::string_view::npos
            ? value.substr(start)
            : value.substr(start, comma - start);
        auto trimmed = Trim(token);
        if (!trimmed.empty()) {
            parts.push_back(std::move(trimmed));
        }

        if (comma == std::string_view::npos) {
            break;
        }

        start = comma + 1;
    }

    return parts;
}

std::optional<uintptr_t> TryParseAddress(std::string_view value) {
    auto trimmed = Trim(value);
    if (trimmed.empty()) {
        return std::nullopt;
    }

    try {
        size_t parsed_characters = 0;
        const auto parsed = std::stoull(trimmed, &parsed_characters, 0);
        if (parsed_characters != trimmed.size()) {
            return std::nullopt;
        }

        return static_cast<uintptr_t>(parsed);
    }
    catch (const std::exception&) {
        return std::nullopt;
    }
}

bool ParseIniFile(
    const std::filesystem::path& path,
    BinaryLayoutSectionMap* sections,
    std::string* error_message) {
    if (sections == nullptr) {
        if (error_message != nullptr) {
            *error_message = "Binary layout parser was called without a destination section map.";
        }
        return false;
    }

    std::ifstream input(path);
    if (!input) {
        if (error_message != nullptr) {
            *error_message = "Unable to open binary layout file: " + path.string();
        }
        return false;
    }

    std::string current_section;
    std::string line;
    size_t line_number = 0;
    while (std::getline(input, line)) {
        ++line_number;
        auto trimmed = Trim(line);
        if (trimmed.empty() || trimmed[0] == ';' || trimmed[0] == '#') {
            continue;
        }

        if (trimmed.front() == '[' && trimmed.back() == ']') {
            current_section = Trim(std::string_view(trimmed).substr(1, trimmed.size() - 2));
            if (current_section.empty()) {
                if (error_message != nullptr) {
                    *error_message = "Binary layout contains an empty section name on line " + std::to_string(line_number) + ".";
                }
                return false;
            }

            (*sections)[current_section];
            continue;
        }

        const auto equals = trimmed.find('=');
        if (equals == std::string::npos) {
            if (error_message != nullptr) {
                *error_message = "Binary layout contains a malformed key/value line " + std::to_string(line_number) + ".";
            }
            return false;
        }

        if (current_section.empty()) {
            if (error_message != nullptr) {
                *error_message = "Binary layout key/value line " + std::to_string(line_number) + " appears before any section header.";
            }
            return false;
        }

        auto key = Trim(std::string_view(trimmed).substr(0, equals));
        auto value = Trim(std::string_view(trimmed).substr(equals + 1));
        (*sections)[current_section][key] = value;
    }

    return true;
}

UiSurfaceDefinition BuildUiSurfaceDefinition(
    const std::string& section_name,
    const BinaryLayoutProperties& properties) {
    UiSurfaceDefinition definition;
    definition.id = section_name.substr(std::string("surface.").size());

    auto property_it = properties.find("title");
    if (property_it != properties.end()) {
        definition.title = property_it->second;
    }

    property_it = properties.find("kind");
    if (property_it != properties.end()) {
        definition.kind = property_it->second;
    }

    property_it = properties.find("dispatch_timing");
    if (property_it != properties.end()) {
        definition.dispatch_timing = property_it->second;
    }

    property_it = properties.find("asset");
    if (property_it != properties.end()) {
        definition.asset = property_it->second;
    }

    property_it = properties.find("asset_2x");
    if (property_it != properties.end()) {
        definition.asset_2x = property_it->second;
    }

    property_it = properties.find("actions");
    if (property_it != properties.end()) {
        definition.action_ids = SplitCommaSeparated(property_it->second);
    }

    for (const auto& [key, value] : properties) {
        if (key == "title" || key == "kind" || key == "dispatch_timing" || key == "asset" || key == "asset_2x" ||
            key == "actions") {
            continue;
        }

        const auto parsed = TryParseAddress(value);
        if (parsed.has_value()) {
            definition.addresses[key] = *parsed;
        }
    }

    return definition;
}

UiActionDefinition BuildUiActionDefinition(
    const std::string& section_name,
    const BinaryLayoutProperties& properties) {
    UiActionDefinition definition;
    definition.id = section_name.substr(std::string("action.").size());

    auto property_it = properties.find("surface");
    if (property_it != properties.end()) {
        definition.surface_id = property_it->second;
    }

    property_it = properties.find("label");
    if (property_it != properties.end()) {
        definition.label = property_it->second;
    }

    property_it = properties.find("dispatch_timing");
    if (property_it != properties.end()) {
        definition.dispatch_timing = property_it->second;
    }

    property_it = properties.find("dispatch_kind");
    if (property_it != properties.end()) {
        definition.dispatch_kind = property_it->second;
    }

    for (const auto& [key, value] : properties) {
        if (key == "surface" || key == "label" || key == "dispatch_timing" || key == "dispatch_kind") {
            continue;
        }

        const auto parsed = TryParseAddress(value);
        if (parsed.has_value()) {
            definition.addresses[key] = *parsed;
        }
    }

    return definition;
}

}  // namespace

bool LoadBinaryLayoutFromDisk(
    const std::filesystem::path& path,
    BinaryLayout* layout,
    std::string* error_message) {
    if (layout == nullptr) {
        if (error_message != nullptr) {
            *error_message = "Binary layout load was called without an output layout object.";
        }
        return false;
    }

    BinaryLayoutSectionMap sections;
    if (!ParseIniFile(path, &sections, error_message)) {
        return false;
    }

    BinaryLayout parsed_layout;
    parsed_layout.source_path = path;

    const auto binary_section = sections.find("binary");
    if (binary_section == sections.end()) {
        if (error_message != nullptr) {
            *error_message = "Binary layout is missing the [binary] section.";
        }
        return false;
    }

    auto value_it = binary_section->second.find("name");
    if (value_it != binary_section->second.end()) {
        parsed_layout.binary_name = value_it->second;
    }

    value_it = binary_section->second.find("version");
    if (value_it != binary_section->second.end()) {
        parsed_layout.binary_version = value_it->second;
    }

    value_it = binary_section->second.find("image_base");
    if (value_it != binary_section->second.end()) {
        const auto parsed_address = TryParseAddress(value_it->second);
        if (!parsed_address.has_value()) {
            if (error_message != nullptr) {
                *error_message = "Binary layout contains an invalid [binary].image_base value: " + value_it->second;
            }
            return false;
        }

        parsed_layout.image_base = *parsed_address;
    }

    for (const auto& [section_name, properties] : sections) {
        if (StartsWith(section_name, "surface.")) {
            parsed_layout.ui_surfaces.push_back(BuildUiSurfaceDefinition(section_name, properties));
            continue;
        }

        if (StartsWith(section_name, "action.")) {
            parsed_layout.ui_actions.push_back(BuildUiActionDefinition(section_name, properties));
        }
    }

    std::sort(parsed_layout.ui_surfaces.begin(), parsed_layout.ui_surfaces.end(), [](const auto& left, const auto& right) {
        return left.id < right.id;
    });
    std::sort(parsed_layout.ui_actions.begin(), parsed_layout.ui_actions.end(), [](const auto& left, const auto& right) {
        return left.id < right.id;
    });

    if (!ValidateBinaryLayout(parsed_layout, error_message)) {
        return false;
    }

    *layout = std::move(parsed_layout);
    return true;
}

}  // namespace sdmod
