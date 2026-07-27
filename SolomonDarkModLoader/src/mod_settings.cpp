#include "mod_settings.h"

#include "mod_settings_json.h"
#include "mod_settings_list.h"

#include <algorithm>
#include <cmath>
#include <fstream>
#include <iterator>
#include <set>
#include <unordered_set>
#include <utility>

namespace sdmod {
namespace {

using settings_json::Type;
using settings_json::Value;

constexpr const char* kCommonFields[] = {
    "key",
    "type",
    "label",
    "description",
    "group",
    "scope",
    "requires_restart",
    "default",
};

bool Fail(std::string* error, std::string message) {
    if (error != nullptr) {
        *error = std::move(message);
    }
    return false;
}

bool IsIntegral(double value) {
    return std::isfinite(value) && std::floor(value) == value;
}

bool HasOnlyFields(
    const Value& object,
    const std::unordered_set<std::string>& allowed,
    std::string_view label,
    std::string* error) {
    for (const auto& [name, ignored] : object.object_value) {
        (void)ignored;
        if (allowed.find(name) == allowed.end()) {
            return Fail(
                error,
                std::string(label) + " contains unknown field '" + name + "'");
        }
    }
    return true;
}

bool ReadRequiredString(
    const Value& object,
    const char* field,
    std::string_view label,
    std::string* value,
    std::string* error) {
    const auto* found = object.Find(field);
    if (found == nullptr || found->type != Type::String) {
        return Fail(
            error,
            std::string(label) + "." + field + " must be a string");
    }
    *value = found->string_value;
    return true;
}

bool ReadOptionalString(
    const Value& object,
    const char* field,
    std::string_view label,
    std::string* value,
    std::string* error) {
    const auto* found = object.Find(field);
    if (found == nullptr) {
        value->clear();
        return true;
    }
    if (found->type != Type::String) {
        return Fail(
            error,
            std::string(label) + "." + field + " must be a string");
    }
    *value = found->string_value;
    return true;
}

bool ReadOptionalBoolean(
    const Value& object,
    const char* field,
    std::string_view label,
    bool default_value,
    bool* value,
    std::string* error) {
    const auto* found = object.Find(field);
    if (found == nullptr) {
        *value = default_value;
        return true;
    }
    if (found->type != Type::Boolean) {
        return Fail(
            error,
            std::string(label) + "." + field + " must be a boolean");
    }
    *value = found->boolean_value;
    return true;
}

bool ReadRequiredNumber(
    const Value& object,
    const char* field,
    std::string_view label,
    double* value,
    std::string* error) {
    const auto* found = object.Find(field);
    if (found == nullptr || found->type != Type::Number) {
        return Fail(
            error,
            std::string(label) + "." + field + " must be a number");
    }
    *value = found->number_value;
    return true;
}

bool TryConvertValue(
    const Value& source,
    ModSettingValue* value,
    std::string* error) {
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
        return Fail(error, "setting value must be a boolean, number, or string");
    }
}

bool IsValidSettingKey(std::string_view key) {
    if (key.empty() || key.size() > 48) {
        return false;
    }
    return std::all_of(key.begin(), key.end(), [](char character) {
        return (character >= 'a' && character <= 'z') ||
               (character >= '0' && character <= '9') ||
               character == '_';
    });
}

bool ValidateCharacterCount(
    std::string_view value,
    std::size_t minimum,
    std::size_t maximum,
    std::string_view field,
    std::string* error) {
    if (!settings_json::IsValidUtf8(value)) {
        return Fail(error, std::string(field) + " must be valid UTF-8");
    }
    const auto count = settings_json::CountUtf8Scalars(value);
    if (count < minimum || count > maximum) {
        return Fail(
            error,
            std::string(field) + " must contain " +
                std::to_string(minimum) + "-" +
                std::to_string(maximum) + " characters");
    }
    return true;
}

bool ParseCommonFields(
    const Value& object,
    std::size_t index,
    ModSettingEntry* entry,
    std::string* type_name,
    std::string* error) {
    const auto label = "settings.entries[" + std::to_string(index) + "]";
    if (!ReadRequiredString(
            object,
            "key",
            label,
            &entry->key,
            error) ||
        !IsValidSettingKey(entry->key)) {
        if (error->empty()) {
            *error = label + ".key must match ^[a-z0-9_]{1,48}$";
        }
        return false;
    }
    if (!ReadRequiredString(object, "type", label, type_name, error) ||
        !ReadRequiredString(object, "label", label, &entry->label, error) ||
        !ValidateCharacterCount(
            entry->label,
            1,
            64,
            label + ".label",
            error) ||
        !ReadOptionalString(
            object,
            "description",
            label,
            &entry->description,
            error) ||
        (!entry->description.empty() &&
         !ValidateCharacterCount(
             entry->description,
             0,
             256,
             label + ".description",
             error)) ||
        !ReadOptionalString(
            object,
            "group",
            label,
            &entry->group,
            error) ||
        (!entry->group.empty() &&
         !ValidateCharacterCount(
             entry->group,
             0,
             32,
             label + ".group",
             error)) ||
        !ReadOptionalBoolean(
            object,
            "requires_restart",
            label,
            false,
            &entry->requires_restart,
            error)) {
        return false;
    }

    const auto* scope = object.Find("scope");
    if (scope == nullptr) {
        entry->scope = ModSettingScope::Local;
    } else if (scope->type != Type::String ||
               (scope->string_value != "local" &&
                scope->string_value != "host")) {
        return Fail(error, label + ".scope must be 'local' or 'host'");
    } else {
        entry->scope = scope->string_value == "host"
            ? ModSettingScope::Host
            : ModSettingScope::Local;
    }
    return true;
}

std::unordered_set<std::string> AllowedFieldsForType(
    std::string_view type) {
    std::unordered_set<std::string> allowed(
        std::begin(kCommonFields),
        std::end(kCommonFields));
    if (type == "number") {
        allowed.insert("min");
        allowed.insert("max");
        allowed.insert("step");
        allowed.insert("integer");
    } else if (type == "text") {
        allowed.insert("max_length");
        allowed.insert("placeholder");
    } else if (type == "choice") {
        allowed.insert("choices");
    } else if (type == "action") {
        allowed.insert("confirm");
    } else if (type == "list") {
        allowed.insert("min_items");
        allowed.insert("max_items");
        allowed.insert("item_label");
        allowed.insert("item");
    }
    return allowed;
}

bool ParseNumberEntry(
    const Value& object,
    std::string_view label,
    ModSettingEntry* entry,
    std::string* error) {
    if (!ReadRequiredNumber(
            object,
            "min",
            label,
            &entry->minimum,
            error) ||
        !ReadRequiredNumber(
            object,
            "max",
            label,
            &entry->maximum,
            error) ||
        !(entry->minimum < entry->maximum)) {
        if (error->empty()) {
            *error = std::string(label) + ".min must be less than max";
        }
        return false;
    }
    const auto* step = object.Find("step");
    if (step == nullptr) {
        entry->step = 1.0;
    } else if (step->type != Type::Number ||
               !(step->number_value > 0.0)) {
        return Fail(
            error,
            std::string(label) + ".step must be a number greater than zero");
    } else {
        entry->step = step->number_value;
    }
    if (!ReadOptionalBoolean(
            object,
            "integer",
            label,
            false,
            &entry->integer,
            error)) {
        return false;
    }
    if (entry->integer &&
        (!IsIntegral(entry->minimum) ||
         !IsIntegral(entry->maximum) ||
         !IsIntegral(entry->step))) {
        return Fail(
            error,
            std::string(label) +
                ".min, max, and step must be integral when integer is true");
    }
    return true;
}

bool ParseTextEntry(
    const Value& object,
    std::string_view label,
    ModSettingEntry* entry,
    std::string* error) {
    const auto* max_length = object.Find("max_length");
    if (max_length == nullptr) {
        entry->max_length = 256;
    } else if (max_length->type != Type::Number ||
               !IsIntegral(max_length->number_value) ||
               max_length->number_value < 1 ||
               max_length->number_value > 1024) {
        return Fail(
            error,
            std::string(label) +
                ".max_length must be an integer from 1 through 1024");
    } else {
        entry->max_length =
            static_cast<std::size_t>(max_length->number_value);
    }
    return ReadOptionalString(
        object,
        "placeholder",
        label,
        &entry->placeholder,
        error);
}

bool ParseChoiceEntry(
    const Value& object,
    std::string_view label,
    ModSettingEntry* entry,
    std::string* error) {
    const auto* choices = object.Find("choices");
    if (choices == nullptr || choices->type != Type::Array ||
        choices->array_value.size() < 2 ||
        choices->array_value.size() > 32) {
        return Fail(
            error,
            std::string(label) +
                ".choices must be an array containing 2-32 choices");
    }
    std::set<std::string, std::less<>> values;
    for (std::size_t index = 0;
         index < choices->array_value.size();
         ++index) {
        const auto& choice = choices->array_value[index];
        const auto choice_label =
            std::string(label) + ".choices[" + std::to_string(index) + "]";
        if (choice.type != Type::Object ||
            !HasOnlyFields(
                choice,
                {"value", "label"},
                choice_label,
                error)) {
            if (error->empty()) {
                *error = choice_label + " must be an object";
            }
            return false;
        }
        ModSettingChoice parsed;
        if (!ReadRequiredString(
                choice,
                "value",
                choice_label,
                &parsed.value,
                error) ||
            !ValidateCharacterCount(
                parsed.value,
                1,
                64,
                choice_label + ".value",
                error) ||
            !ReadRequiredString(
                choice,
                "label",
                choice_label,
                &parsed.label,
                error)) {
            return false;
        }
        if (!values.insert(parsed.value).second) {
            return Fail(
                error,
                std::string(label) +
                    ".choices contains duplicate value '" +
                    parsed.value + "'");
        }
        entry->choices.push_back(std::move(parsed));
    }
    return true;
}

bool ParseEntry(
    const Value& object,
    std::size_t index,
    ModSettingEntry* entry,
    std::string* error) {
    const auto label = "settings.entries[" + std::to_string(index) + "]";
    if (object.type != Type::Object) {
        return Fail(error, label + " must be an object");
    }
    std::string type;
    if (!ParseCommonFields(object, index, entry, &type, error)) {
        return false;
    }

    if (type == "toggle") {
        entry->type = ModSettingType::Toggle;
    } else if (type == "number") {
        entry->type = ModSettingType::Number;
    } else if (type == "text") {
        entry->type = ModSettingType::Text;
    } else if (type == "choice") {
        entry->type = ModSettingType::Choice;
    } else if (type == "keybind") {
        entry->type = ModSettingType::Keybind;
    } else if (type == "action") {
        entry->type = ModSettingType::Action;
    } else if (type == "list") {
        entry->type = ModSettingType::List;
    } else {
        return Fail(
            error,
            label + ".type is not a supported settings type");
    }
    if (!HasOnlyFields(
            object,
            AllowedFieldsForType(type),
            label,
            error)) {
        return false;
    }

    if (entry->type == ModSettingType::Number &&
        !ParseNumberEntry(object, label, entry, error)) {
        return false;
    }
    if (entry->type == ModSettingType::Text &&
        !ParseTextEntry(object, label, entry, error)) {
        return false;
    }
    if (entry->type == ModSettingType::Choice &&
        !ParseChoiceEntry(object, label, entry, error)) {
        return false;
    }
    if (entry->type == ModSettingType::Action) {
        if (object.Find("default") != nullptr) {
            return Fail(
                error,
                label + ".default is forbidden for action entries");
        }
        return ReadOptionalBoolean(
            object,
            "confirm",
            label,
            false,
            &entry->confirm,
            error);
    }
    if (entry->type == ModSettingType::List) {
        return detail::ParseListModSettingEntry(
            object,
            label,
            entry,
            error);
    }

    const auto* default_value = object.Find("default");
    if (default_value == nullptr) {
        return Fail(
            error,
            label + ".default is required for non-action entries");
    }
    if (!TryConvertValue(*default_value, &entry->default_value, error)) {
        *error = label + ".default " + *error;
        return false;
    }
    entry->has_default = true;
    std::string value_error;
    if (!ValidateModSettingValue(
            *entry,
            entry->default_value,
            &value_error)) {
        return Fail(
            error,
            label + ".default is invalid: " + value_error);
    }
    return true;
}

}  // namespace

bool ParseModSettingsManifestJson(
    std::string_view manifest_json,
    ModSettingsManifestResult* result) {
    if (result == nullptr) {
        return false;
    }
    *result = ModSettingsManifestResult{};

    Value root;
    std::string parse_error;
    if (!settings_json::Parse(manifest_json, &root, &parse_error) ||
        root.type != Type::Object) {
        result->has_settings = true;
        result->error = parse_error.empty()
            ? "manifest root must be an object"
            : "manifest JSON is invalid: " + parse_error;
        return true;
    }
    const auto* settings = root.Find("settings");
    if (settings == nullptr) {
        result->valid = true;
        return true;
    }
    result->has_settings = true;
    if (settings->type != Type::Object) {
        result->error = "settings must be an object";
        return true;
    }
    if (!HasOnlyFields(
            *settings,
            {"version", "entries"},
            "settings",
            &result->error)) {
        return true;
    }
    const auto* version = settings->Find("version");
    if (version == nullptr ||
        version->type != Type::Number ||
        version->number_value != 1.0) {
        result->error = "settings.version must be 1";
        return true;
    }
    const auto* entries = settings->Find("entries");
    if (entries == nullptr || entries->type != Type::Array) {
        result->error = "settings.entries must be an array";
        return true;
    }

    std::set<std::string, std::less<>> keys;
    result->declaration.entries.reserve(entries->array_value.size());
    for (std::size_t index = 0;
         index < entries->array_value.size();
         ++index) {
        ModSettingEntry entry;
        if (!ParseEntry(
                entries->array_value[index],
                index,
                &entry,
                &result->error)) {
            result->declaration = ModSettingsDeclaration{};
            return true;
        }
        if (!keys.insert(entry.key).second) {
            result->error =
                "settings.entries contains duplicate key '" +
                entry.key + "'";
            result->declaration = ModSettingsDeclaration{};
            return true;
        }
        result->declaration.entries.push_back(std::move(entry));
    }
    result->valid = true;
    return true;
}

bool LoadModSettingsManifest(
    const std::filesystem::path& manifest_path,
    ModSettingsManifestResult* result,
    std::string* read_error) {
    if (result == nullptr || read_error == nullptr) {
        return false;
    }
    read_error->clear();
    std::ifstream stream(manifest_path, std::ios::binary);
    if (!stream.is_open()) {
        *read_error =
            "unable to open manifest: " + manifest_path.string();
        return false;
    }
    const std::string source{
        std::istreambuf_iterator<char>(stream),
        std::istreambuf_iterator<char>()};
    if (stream.bad()) {
        *read_error =
            "unable to read manifest: " + manifest_path.string();
        return false;
    }
    return ParseModSettingsManifestJson(source, result);
}

}  // namespace sdmod
