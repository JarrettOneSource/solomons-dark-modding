#pragma once

#include <cstdint>
#include <filesystem>
#include <map>
#include <string>
#include <string_view>
#include <vector>

namespace sdmod {

struct UiSurfaceDefinition {
    std::string id;
    std::string title;
    std::string kind;
    std::string dispatch_timing;
    std::string asset;
    std::string asset_2x;
    std::vector<std::string> action_ids;
    std::map<std::string, uintptr_t> addresses;
};

struct UiActionDefinition {
    std::string id;
    std::string surface_id;
    std::string label;
    std::string dispatch_timing;
    std::string dispatch_kind;
    std::map<std::string, uintptr_t> addresses;
};

struct BinaryLayout {
    std::filesystem::path source_path;
    std::string binary_name;
    std::string binary_version;
    uintptr_t image_base = 0;
    std::map<std::string, std::map<std::string, uintptr_t>> numeric_sections;
    std::vector<UiSurfaceDefinition> ui_surfaces;
    std::vector<UiActionDefinition> ui_actions;
};

bool InitializeBinaryLayout(const std::filesystem::path& stage_runtime_directory);
void ShutdownBinaryLayout();

bool IsBinaryLayoutLoaded();
const BinaryLayout* TryGetBinaryLayout();
std::string GetBinaryLayoutLoadError();

const UiSurfaceDefinition* FindUiSurfaceDefinition(std::string_view id);
const UiActionDefinition* FindUiActionDefinition(std::string_view id);
bool TryGetBinaryLayoutNumericValue(std::string_view section_id, std::string_view key, uintptr_t* value);

uintptr_t GetConfiguredImageBase();
std::filesystem::path GetBinaryLayoutPath(const std::filesystem::path& stage_runtime_directory);

}  // namespace sdmod
