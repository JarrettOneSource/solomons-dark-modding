#pragma once

#include <cstddef>
#include <filesystem>
#include <map>
#include <string>
#include <string_view>
#include <vector>

namespace sdmod {

inline constexpr std::size_t kModSettingListMaxSerializedBytes = 8192;

enum class ModSettingType {
    Toggle,
    Number,
    Text,
    Choice,
    Keybind,
    Action,
    List,
};

enum class ModSettingScope {
    Local,
    Host,
};

enum class ModSettingValueType {
    Boolean,
    Number,
    String,
    List,
};

struct ModSettingValue;
using ModSettingListItem =
    std::map<std::string, ModSettingValue, std::less<>>;

struct ModSettingValue {
    ModSettingValueType type = ModSettingValueType::Boolean;
    bool boolean_value = false;
    double number_value = 0.0;
    std::string string_value;
    std::vector<ModSettingListItem> list_value;

    static ModSettingValue Boolean(bool value);
    static ModSettingValue Number(double value);
    static ModSettingValue String(std::string value);
    static ModSettingValue List(std::vector<ModSettingListItem> value);
};

bool operator==(const ModSettingValue& left, const ModSettingValue& right);
bool operator!=(const ModSettingValue& left, const ModSettingValue& right);

struct ModSettingChoice {
    std::string value;
    std::string label;
};

struct ModSettingEntry {
    std::string key;
    ModSettingType type = ModSettingType::Toggle;
    std::string label;
    std::string description;
    std::string group;
    ModSettingScope scope = ModSettingScope::Local;
    bool requires_restart = false;
    bool has_default = false;
    ModSettingValue default_value;

    double minimum = 0.0;
    double maximum = 0.0;
    double step = 1.0;
    bool integer = false;

    std::size_t max_length = 256;
    std::string placeholder;
    std::vector<ModSettingChoice> choices;
    bool confirm = false;

    std::size_t min_items = 0;
    std::size_t max_items = 0;
    std::string item_label;
    std::vector<ModSettingEntry> item_fields;

    const ModSettingEntry* FindItemField(std::string_view key) const;
};

struct ModSettingsDeclaration {
    int version = 1;
    std::vector<ModSettingEntry> entries;

    const ModSettingEntry* Find(std::string_view key) const;
};

struct ModSettingsManifestResult {
    bool has_settings = false;
    bool valid = false;
    ModSettingsDeclaration declaration;
    std::string error;
};

using ModSettingValues =
    std::map<std::string, ModSettingValue, std::less<>>;

struct ModSettingsValuesResult {
    bool valid = false;
    ModSettingValues values;
    std::vector<std::string> warnings;
    std::map<std::string, std::string, std::less<>> entry_errors;
    std::string error;
};

bool ParseModSettingsManifestJson(
    std::string_view manifest_json,
    ModSettingsManifestResult* result);
bool LoadModSettingsManifest(
    const std::filesystem::path& manifest_path,
    ModSettingsManifestResult* result,
    std::string* read_error);
bool ValidateModSettingValue(
    const ModSettingEntry& entry,
    const ModSettingValue& value,
    std::string* error_message);
bool NormalizeModSettingValue(
    const ModSettingEntry& entry,
    const ModSettingValue& value,
    ModSettingValue* normalized,
    std::string* error_message);
std::size_t SerializedModSettingListValueBytes(
    const ModSettingValue& value);
bool IsCanonicalModSettingKeybind(std::string_view value);
bool ParsePersistedModSettingsJson(
    std::string_view persisted_json,
    const ModSettingsDeclaration& declaration,
    ModSettingsValuesResult* result);
bool LoadPersistedModSettings(
    const std::filesystem::path& settings_path,
    const ModSettingsDeclaration& declaration,
    ModSettingsValuesResult* result,
    bool* file_found,
    std::string* read_error);

}  // namespace sdmod
