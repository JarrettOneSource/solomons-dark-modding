#include "mod_settings_list.h"

#include <algorithm>
#include <cmath>
#include <set>
#include <unordered_set>
#include <utility>

namespace sdmod::detail {
namespace {

using settings_json::Type;
using settings_json::Value;

bool Fail(std::string* error, std::string message) {
    if (error != nullptr) {
        *error = std::move(message);
    }
    return false;
}

bool IsIntegral(double value) {
    return std::isfinite(value) && std::floor(value) == value;
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
    bool* value,
    std::string* error) {
    const auto* found = object.Find(field);
    if (found == nullptr) {
        *value = false;
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

bool ConvertScalarJsonValue(
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
        return Fail(
            error,
            "setting value must be a boolean, number, or string");
    }
}

std::unordered_set<std::string> AllowedItemFieldFields(
    std::string_view type) {
    std::unordered_set<std::string> allowed = {
        "key",
        "type",
        "label",
        "description",
        "default",
    };
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
    }
    return allowed;
}

bool ParseNumberField(
    const Value& object,
    std::string_view label,
    ModSettingEntry* field,
    std::string* error) {
    if (!ReadRequiredNumber(
            object,
            "min",
            label,
            &field->minimum,
            error) ||
        !ReadRequiredNumber(
            object,
            "max",
            label,
            &field->maximum,
            error) ||
        !(field->minimum < field->maximum)) {
        if (error->empty()) {
            *error = std::string(label) + ".min must be less than max";
        }
        return false;
    }
    const auto* step = object.Find("step");
    if (step == nullptr) {
        field->step = 1.0;
    } else if (step->type != Type::Number ||
               !(step->number_value > 0.0)) {
        return Fail(
            error,
            std::string(label) +
                ".step must be a number greater than zero");
    } else {
        field->step = step->number_value;
    }
    if (!ReadOptionalBoolean(
            object,
            "integer",
            label,
            &field->integer,
            error)) {
        return false;
    }
    if (field->integer &&
        (!IsIntegral(field->minimum) ||
         !IsIntegral(field->maximum) ||
         !IsIntegral(field->step))) {
        return Fail(
            error,
            std::string(label) +
                ".min, max, and step must be integral when integer is true");
    }
    return true;
}

bool ParseTextField(
    const Value& object,
    std::string_view label,
    ModSettingEntry* field,
    std::string* error) {
    const auto* max_length = object.Find("max_length");
    if (max_length == nullptr) {
        field->max_length = 256;
    } else if (max_length->type != Type::Number ||
               !IsIntegral(max_length->number_value) ||
               max_length->number_value < 1 ||
               max_length->number_value > 1024) {
        return Fail(
            error,
            std::string(label) +
                ".max_length must be an integer from 1 through 1024");
    } else {
        field->max_length =
            static_cast<std::size_t>(max_length->number_value);
    }
    return ReadOptionalString(
        object,
        "placeholder",
        label,
        &field->placeholder,
        error);
}

bool ParseChoiceField(
    const Value& object,
    std::string_view label,
    ModSettingEntry* field,
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
        field->choices.push_back(std::move(parsed));
    }
    return true;
}

bool ParseItemField(
    const Value& object,
    std::string_view label,
    ModSettingEntry* field,
    std::string* error) {
    if (object.type != Type::Object) {
        return Fail(error, std::string(label) + " must be an object");
    }
    std::string type_name;
    if (!ReadRequiredString(
            object,
            "key",
            label,
            &field->key,
            error) ||
        !IsValidSettingKey(field->key)) {
        if (error->empty()) {
            *error =
                std::string(label) +
                ".key must match ^[a-z0-9_]{1,48}$";
        }
        return false;
    }
    if (!ReadRequiredString(
            object,
            "type",
            label,
            &type_name,
            error)) {
        return false;
    }
    if (type_name == "toggle") {
        field->type = ModSettingType::Toggle;
    } else if (type_name == "number") {
        field->type = ModSettingType::Number;
    } else if (type_name == "text") {
        field->type = ModSettingType::Text;
    } else if (type_name == "choice") {
        field->type = ModSettingType::Choice;
    } else {
        return Fail(
            error,
            std::string(label) +
                ".type must be toggle, number, text, or choice");
    }
    if (!HasOnlyFields(
            object,
            AllowedItemFieldFields(type_name),
            label,
            error) ||
        !ReadRequiredString(
            object,
            "label",
            label,
            &field->label,
            error) ||
        !ValidateCharacterCount(
            field->label,
            1,
            64,
            std::string(label) + ".label",
            error) ||
        !ReadOptionalString(
            object,
            "description",
            label,
            &field->description,
            error) ||
        !ValidateCharacterCount(
            field->description,
            0,
            256,
            std::string(label) + ".description",
            error)) {
        return false;
    }
    if (field->type == ModSettingType::Number &&
        !ParseNumberField(object, label, field, error)) {
        return false;
    }
    if (field->type == ModSettingType::Text &&
        !ParseTextField(object, label, field, error)) {
        return false;
    }
    if (field->type == ModSettingType::Choice &&
        !ParseChoiceField(object, label, field, error)) {
        return false;
    }

    const auto* default_value = object.Find("default");
    if (default_value == nullptr) {
        return Fail(
            error,
            std::string(label) + ".default is required");
    }
    ModSettingValue parsed_default;
    if (!ConvertScalarJsonValue(
            *default_value,
            &parsed_default,
            error)) {
        *error =
            std::string(label) + ".default " + *error;
        return false;
    }
    std::string value_error;
    if (!NormalizeModSettingValue(
            *field,
            parsed_default,
            &field->default_value,
            &value_error)) {
        return Fail(
            error,
            std::string(label) +
                ".default is invalid: " + value_error);
    }
    field->has_default = true;
    return true;
}

bool ValidateItemLabel(
    const ModSettingEntry& entry,
    std::string_view label,
    std::string* error) {
    std::size_t position = 0;
    while (position < entry.item_label.size()) {
        if (entry.item_label[position] == '}') {
            return Fail(
                error,
                std::string(label) +
                    ".item_label contains an unmatched '}'");
        }
        if (entry.item_label[position] != '{') {
            ++position;
            continue;
        }
        const auto close = entry.item_label.find('}', position + 1);
        if (close == std::string::npos) {
            return Fail(
                error,
                std::string(label) +
                    ".item_label contains an unclosed placeholder");
        }
        const auto key = std::string_view(entry.item_label)
            .substr(position + 1, close - position - 1);
        if (!IsValidSettingKey(key) ||
            entry.FindItemField(key) == nullptr) {
            return Fail(
                error,
                std::string(label) +
                    ".item_label references unknown field '{" +
                    std::string(key) + "}'");
        }
        position = close + 1;
    }
    return true;
}

}  // namespace

bool ConvertJsonModSettingValue(
    const ModSettingEntry& entry,
    const Value& source,
    ModSettingValue* value,
    std::string* error) {
    if (value == nullptr) {
        return false;
    }
    if (entry.type != ModSettingType::List) {
        ModSettingValue scalar;
        if (!ConvertScalarJsonValue(source, &scalar, error)) {
            return false;
        }
        return NormalizeModSettingValue(
            entry,
            scalar,
            value,
            error);
    }
    if (source.type != Type::Array) {
        return Fail(error, "value must be an array");
    }
    std::vector<ModSettingListItem> items;
    items.reserve(source.array_value.size());
    for (std::size_t item_index = 0;
         item_index < source.array_value.size();
         ++item_index) {
        const auto& source_item = source.array_value[item_index];
        if (source_item.type != Type::Object) {
            return Fail(
                error,
                "list item " + std::to_string(item_index + 1) +
                    " must be an object");
        }
        ModSettingListItem item;
        for (const auto& [key, source_field] :
             source_item.object_value) {
            const auto* field = entry.FindItemField(key);
            if (field == nullptr) {
                return Fail(
                    error,
                    "list item " + std::to_string(item_index + 1) +
                        " contains unknown field '" + key + "'");
            }
            ModSettingValue field_value;
            std::string field_error;
            if (!ConvertScalarJsonValue(
                    source_field,
                    &field_value,
                    &field_error)) {
                return Fail(
                    error,
                    "list item " + std::to_string(item_index + 1) +
                        " field '" + key + "' is invalid: " +
                        field_error);
            }
            item.emplace(key, std::move(field_value));
        }
        items.push_back(std::move(item));
    }
    return NormalizeModSettingValue(
        entry,
        ModSettingValue::List(std::move(items)),
        value,
        error);
}

bool ParseListModSettingEntry(
    const Value& object,
    std::string_view label,
    ModSettingEntry* entry,
    std::string* error) {
    if (entry == nullptr || error == nullptr) {
        return false;
    }
    const auto* max_items = object.Find("max_items");
    if (max_items == nullptr ||
        max_items->type != Type::Number ||
        !IsIntegral(max_items->number_value) ||
        max_items->number_value < 1 ||
        max_items->number_value > 32) {
        return Fail(
            error,
            std::string(label) +
                ".max_items must be an integer from 1 through 32");
    }
    entry->max_items =
        static_cast<std::size_t>(max_items->number_value);

    const auto* min_items = object.Find("min_items");
    if (min_items == nullptr) {
        entry->min_items = 0;
    } else if (min_items->type != Type::Number ||
               !IsIntegral(min_items->number_value) ||
               min_items->number_value < 0 ||
               min_items->number_value >
                   static_cast<double>(entry->max_items)) {
        return Fail(
            error,
            std::string(label) +
                ".min_items must be an integer from 0 through max_items");
    } else {
        entry->min_items =
            static_cast<std::size_t>(min_items->number_value);
    }

    if (!ReadOptionalString(
            object,
            "item_label",
            label,
            &entry->item_label,
            error) ||
        !ValidateCharacterCount(
            entry->item_label,
            0,
            64,
            std::string(label) + ".item_label",
            error)) {
        return false;
    }

    const auto* item = object.Find("item");
    if (item == nullptr || item->type != Type::Object ||
        !HasOnlyFields(*item, {"fields"}, std::string(label) + ".item", error)) {
        if (error->empty()) {
            *error = std::string(label) + ".item must be an object";
        }
        return false;
    }
    const auto* fields = item->Find("fields");
    if (fields == nullptr || fields->type != Type::Array ||
        fields->array_value.empty() ||
        fields->array_value.size() > 12) {
        return Fail(
            error,
            std::string(label) +
                ".item.fields must contain 1-12 fields");
    }
    std::set<std::string, std::less<>> field_keys;
    entry->item_fields.reserve(fields->array_value.size());
    for (std::size_t index = 0;
         index < fields->array_value.size();
         ++index) {
        ModSettingEntry field;
        const auto field_label =
            std::string(label) + ".item.fields[" +
            std::to_string(index) + "]";
        if (!ParseItemField(
                fields->array_value[index],
                field_label,
                &field,
                error)) {
            return false;
        }
        if (!field_keys.insert(field.key).second) {
            return Fail(
                error,
                std::string(label) +
                    ".item.fields contains duplicate key '" +
                    field.key + "'");
        }
        entry->item_fields.push_back(std::move(field));
    }
    if (!ValidateItemLabel(*entry, label, error)) {
        return false;
    }

    const auto* default_value = object.Find("default");
    if (default_value == nullptr) {
        return Fail(
            error,
            std::string(label) +
                ".default is required for list entries");
    }
    std::string value_error;
    if (!ConvertJsonModSettingValue(
            *entry,
            *default_value,
            &entry->default_value,
            &value_error)) {
        return Fail(
            error,
            std::string(label) +
                ".default is invalid: " + value_error);
    }
    entry->has_default = true;
    return true;
}

}  // namespace sdmod::detail
