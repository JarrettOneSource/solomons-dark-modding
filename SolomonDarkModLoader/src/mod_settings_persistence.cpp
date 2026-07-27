#include "mod_settings.h"

#include "mod_settings_json.h"

#include <chrono>
#include <fstream>
#include <iterator>
#include <system_error>
#include <thread>

namespace sdmod {
namespace {

using settings_json::Type;
using settings_json::Value;

constexpr int kReadAttemptCount = 3;
constexpr auto kReadRetryDelay = std::chrono::milliseconds(10);

bool ConvertValue(const Value& source, ModSettingValue* value) {
    switch (source.type) {
    case Type::Boolean:
        *value = ModSettingValue::Boolean(source.boolean_value);
        return true;
    case Type::Number:
        *value = ModSettingValue::Number(source.number_value);
        return true;
    case Type::String:
        *value = ModSettingValue::String(source.string_value);
        return true;
    default:
        return false;
    }
}

}  // namespace

bool ParsePersistedModSettingsJson(
    std::string_view persisted_json,
    const ModSettingsDeclaration& declaration,
    ModSettingsValuesResult* result) {
    if (result == nullptr) {
        return false;
    }
    *result = ModSettingsValuesResult{};

    Value root;
    std::string parse_error;
    if (!settings_json::Parse(
            persisted_json,
            &root,
            &parse_error)) {
        result->error =
            "persisted settings JSON is invalid: " + parse_error;
        return true;
    }
    if (root.type != Type::Object) {
        result->error = "persisted settings root must be an object";
        return true;
    }
    for (const auto& [name, ignored] : root.object_value) {
        (void)ignored;
        if (name != "schemaVersion" && name != "values") {
            result->error =
                "persisted settings contains unknown field '" +
                name + "'";
            return true;
        }
    }
    const auto* schema_version = root.Find("schemaVersion");
    if (schema_version == nullptr ||
        schema_version->type != Type::Number ||
        schema_version->number_value != 1.0) {
        result->error = "persisted settings schemaVersion must be 1";
        return true;
    }
    const auto* values = root.Find("values");
    if (values == nullptr || values->type != Type::Object) {
        result->error = "persisted settings values must be an object";
        return true;
    }

    for (const auto& [key, source] : values->object_value) {
        const auto* entry = declaration.Find(key);
        if (entry == nullptr) {
            result->warnings.push_back(
                "ignored unknown persisted setting '" + key + "'");
            continue;
        }
        if (entry->type == ModSettingType::Action) {
            result->warnings.push_back(
                "ignored persisted action setting '" + key + "'");
            continue;
        }
        ModSettingValue value;
        if (!ConvertValue(source, &value)) {
            result->warnings.push_back(
                "ignored persisted setting '" + key +
                "': value must be a boolean, number, or string");
            continue;
        }
        std::string value_error;
        if (!ValidateModSettingValue(*entry, value, &value_error)) {
            result->warnings.push_back(
                "ignored persisted setting '" + key +
                "': " + value_error);
            continue;
        }
        result->values.emplace(key, std::move(value));
    }
    result->valid = true;
    return true;
}

bool LoadPersistedModSettings(
    const std::filesystem::path& settings_path,
    const ModSettingsDeclaration& declaration,
    ModSettingsValuesResult* result,
    bool* file_found,
    std::string* read_error) {
    if (result == nullptr ||
        file_found == nullptr ||
        read_error == nullptr) {
        return false;
    }
    *result = ModSettingsValuesResult{};
    *file_found = false;
    read_error->clear();

    for (int attempt = 0; attempt < kReadAttemptCount; ++attempt) {
        std::error_code exists_error;
        if (!std::filesystem::exists(settings_path, exists_error)) {
            if (exists_error) {
                *read_error =
                    "unable to inspect persisted settings: " +
                    exists_error.message();
                return false;
            }
            result->valid = true;
            return true;
        }
        *file_found = true;

        std::ifstream stream(settings_path, std::ios::binary);
        if (stream.is_open()) {
            const std::string source{
                std::istreambuf_iterator<char>(stream),
                std::istreambuf_iterator<char>()};
            if (!stream.bad()) {
                return ParsePersistedModSettingsJson(
                    source,
                    declaration,
                    result);
            }
        }

        if (attempt + 1 < kReadAttemptCount) {
            std::this_thread::sleep_for(kReadRetryDelay);
        }
    }

    *read_error =
        "unable to read persisted settings after atomic-replace retry: " +
        settings_path.string();
    return false;
}

}  // namespace sdmod
