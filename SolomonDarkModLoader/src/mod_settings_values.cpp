#include "mod_settings.h"

#include "mod_settings_json.h"

#include <algorithm>
#include <cmath>
#include <utility>

namespace sdmod {
namespace {

bool Fail(std::string* error_message, std::string message) {
    if (error_message != nullptr) {
        *error_message = std::move(message);
    }
    return false;
}

bool IsIntegral(double value) {
    return std::isfinite(value) && std::floor(value) == value;
}

settings_json::Value ToJsonValue(const ModSettingValue& source) {
    settings_json::Value result;
    switch (source.type) {
    case ModSettingValueType::Boolean:
        result.type = settings_json::Type::Boolean;
        result.boolean_value = source.boolean_value;
        break;
    case ModSettingValueType::Number:
        result.type = settings_json::Type::Number;
        result.number_value = source.number_value;
        break;
    case ModSettingValueType::String:
        result.type = settings_json::Type::String;
        result.string_value = source.string_value;
        break;
    case ModSettingValueType::List:
        result.type = settings_json::Type::Array;
        result.array_value.reserve(source.list_value.size());
        for (const auto& source_item : source.list_value) {
            settings_json::Value item;
            item.type = settings_json::Type::Object;
            for (const auto& [key, source_field] : source_item) {
                item.object_value.emplace(
                    key,
                    ToJsonValue(source_field));
            }
            result.array_value.push_back(std::move(item));
        }
        break;
    }
    return result;
}

bool ValidateScalarModSettingValue(
    const ModSettingEntry& entry,
    const ModSettingValue& value,
    std::string* error_message) {
    switch (entry.type) {
    case ModSettingType::Toggle:
        if (value.type != ModSettingValueType::Boolean) {
            return Fail(error_message, "value must be a boolean");
        }
        return true;
    case ModSettingType::Number:
        if (value.type != ModSettingValueType::Number ||
            !std::isfinite(value.number_value)) {
            return Fail(error_message, "value must be a finite number");
        }
        if (value.number_value < entry.minimum ||
            value.number_value > entry.maximum) {
            return Fail(error_message, "value is outside min and max");
        }
        if (entry.integer && !IsIntegral(value.number_value)) {
            return Fail(
                error_message,
                "value must be integral when integer is true");
        }
        return true;
    case ModSettingType::Text:
        if (value.type != ModSettingValueType::String) {
            return Fail(error_message, "value must be a string");
        }
        if (!settings_json::IsValidUtf8(value.string_value)) {
            return Fail(error_message, "value must be valid UTF-8");
        }
        if (value.string_value.find('\r') != std::string::npos ||
            value.string_value.find('\n') != std::string::npos) {
            return Fail(error_message, "value must be a single line");
        }
        if (value.string_value.size() > entry.max_length) {
            return Fail(
                error_message,
                "value exceeds max_length UTF-8 bytes");
        }
        return true;
    case ModSettingType::Choice:
        if (value.type != ModSettingValueType::String) {
            return Fail(error_message, "value must be a string");
        }
        if (std::none_of(
                entry.choices.begin(),
                entry.choices.end(),
                [&](const ModSettingChoice& choice) {
                    return choice.value == value.string_value;
                })) {
            return Fail(error_message, "value is not a declared choice");
        }
        return true;
    case ModSettingType::Keybind:
        if (value.type != ModSettingValueType::String ||
            !IsCanonicalModSettingKeybind(value.string_value)) {
            return Fail(
                error_message,
                "value is not a canonical keybind name");
        }
        return true;
    case ModSettingType::Action:
        return Fail(error_message, "action entries do not have values");
    case ModSettingType::List:
        return Fail(error_message, "nested list values are not supported");
    }
    return Fail(error_message, "setting type is invalid");
}

}  // namespace

ModSettingValue ModSettingValue::Boolean(bool value) {
    ModSettingValue result;
    result.type = ModSettingValueType::Boolean;
    result.boolean_value = value;
    return result;
}

ModSettingValue ModSettingValue::Number(double value) {
    ModSettingValue result;
    result.type = ModSettingValueType::Number;
    result.number_value = value;
    return result;
}

ModSettingValue ModSettingValue::String(std::string value) {
    ModSettingValue result;
    result.type = ModSettingValueType::String;
    result.string_value = std::move(value);
    return result;
}

ModSettingValue ModSettingValue::List(
    std::vector<ModSettingListItem> value) {
    ModSettingValue result;
    result.type = ModSettingValueType::List;
    result.list_value = std::move(value);
    return result;
}

bool operator==(
    const ModSettingValue& left,
    const ModSettingValue& right) {
    if (left.type != right.type) {
        return false;
    }
    switch (left.type) {
    case ModSettingValueType::Boolean:
        return left.boolean_value == right.boolean_value;
    case ModSettingValueType::Number:
        return left.number_value == right.number_value;
    case ModSettingValueType::String:
        return left.string_value == right.string_value;
    case ModSettingValueType::List:
        return left.list_value == right.list_value;
    }
    return false;
}

bool operator!=(
    const ModSettingValue& left,
    const ModSettingValue& right) {
    return !(left == right);
}

const ModSettingEntry* ModSettingsDeclaration::Find(
    std::string_view key) const {
    const auto found = std::find_if(
        entries.begin(),
        entries.end(),
        [&](const ModSettingEntry& entry) { return entry.key == key; });
    return found == entries.end() ? nullptr : &*found;
}

const ModSettingEntry* ModSettingEntry::FindItemField(
    std::string_view item_key) const {
    const auto found = std::find_if(
        item_fields.begin(),
        item_fields.end(),
        [&](const ModSettingEntry& field) {
            return field.key == item_key;
        });
    return found == item_fields.end() ? nullptr : &*found;
}

bool ValidateModSettingValue(
    const ModSettingEntry& entry,
    const ModSettingValue& value,
    std::string* error_message) {
    ModSettingValue normalized;
    return NormalizeModSettingValue(
        entry,
        value,
        &normalized,
        error_message);
}

bool NormalizeModSettingValue(
    const ModSettingEntry& entry,
    const ModSettingValue& value,
    ModSettingValue* normalized,
    std::string* error_message) {
    if (normalized == nullptr) {
        return false;
    }
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (entry.type != ModSettingType::List) {
        if (!ValidateScalarModSettingValue(
                entry,
                value,
                error_message)) {
            return false;
        }
        *normalized = value;
        return true;
    }
    if (value.type != ModSettingValueType::List) {
        return Fail(error_message, "value must be an array");
    }
    if (value.list_value.size() < entry.min_items ||
        value.list_value.size() > entry.max_items) {
        return Fail(
            error_message,
            "list value count is outside min_items and max_items");
    }

    std::vector<ModSettingListItem> normalized_items;
    normalized_items.reserve(value.list_value.size());
    for (std::size_t item_index = 0;
         item_index < value.list_value.size();
         ++item_index) {
        const auto& item = value.list_value[item_index];
        for (const auto& [key, ignored] : item) {
            (void)ignored;
            if (entry.FindItemField(key) == nullptr) {
                return Fail(
                    error_message,
                    "list item " + std::to_string(item_index + 1) +
                        " contains unknown field '" + key + "'");
            }
        }
        ModSettingListItem normalized_item;
        for (const auto& field : entry.item_fields) {
            const auto found = item.find(field.key);
            const auto& source =
                found == item.end() ? field.default_value : found->second;
            ModSettingValue normalized_field;
            std::string field_error;
            if (!NormalizeModSettingValue(
                    field,
                    source,
                    &normalized_field,
                    &field_error)) {
                return Fail(
                    error_message,
                    "list item " + std::to_string(item_index + 1) +
                        " field '" + field.key + "' is invalid: " +
                        field_error);
            }
            normalized_item.emplace(
                field.key,
                std::move(normalized_field));
        }
        normalized_items.push_back(std::move(normalized_item));
    }

    auto normalized_list =
        ModSettingValue::List(std::move(normalized_items));
    if (SerializedModSettingListValueBytes(normalized_list) >
        kModSettingListMaxSerializedBytes) {
        return Fail(
            error_message,
            "serialized list value exceeds 8192 UTF-8 bytes");
    }
    *normalized = std::move(normalized_list);
    return true;
}

std::size_t SerializedModSettingListValueBytes(
    const ModSettingValue& value) {
    if (value.type != ModSettingValueType::List) {
        return 0;
    }
    return settings_json::Serialize(ToJsonValue(value)).size();
}

bool IsCanonicalModSettingKeybind(std::string_view value) {
    if (value == "NONE" || value == "SPACE" || value == "TAB" ||
        value == "ENTER" || value == "SHIFT" || value == "CTRL" ||
        value == "ALT" || value == "UP" || value == "DOWN" ||
        value == "LEFT" || value == "RIGHT" ||
        value == "MOUSE3" || value == "MOUSE4" ||
        value == "MOUSE5") {
        return true;
    }
    if (value.size() == 1) {
        return (value[0] >= 'A' && value[0] <= 'Z') ||
               (value[0] >= '0' && value[0] <= '9');
    }
    if (value.size() >= 2 && value.size() <= 3 && value[0] == 'F') {
        if (value.size() == 3 && value[1] == '0') {
            return false;
        }
        int number = 0;
        for (std::size_t index = 1; index < value.size(); ++index) {
            if (value[index] < '0' || value[index] > '9') {
                return false;
            }
            number = number * 10 + (value[index] - '0');
        }
        return number >= 1 && number <= 24;
    }
    return false;
}

}  // namespace sdmod
