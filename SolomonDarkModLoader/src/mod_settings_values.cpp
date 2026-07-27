#include "mod_settings.h"

#include "mod_settings_json.h"

#include <algorithm>
#include <cmath>
#include <utility>

namespace sdmod {
namespace {

bool Fail(std::string* error_message, const char* message) {
    if (error_message != nullptr) {
        *error_message = message;
    }
    return false;
}

bool IsIntegral(double value) {
    return std::isfinite(value) && std::floor(value) == value;
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

bool ValidateModSettingValue(
    const ModSettingEntry& entry,
    const ModSettingValue& value,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
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
    }
    return Fail(error_message, "setting type is invalid");
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
