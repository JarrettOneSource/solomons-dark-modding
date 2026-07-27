#pragma once

#include <map>
#include <string>
#include <string_view>
#include <vector>

namespace sdmod::settings_json {

enum class Type {
    Null,
    Boolean,
    Number,
    String,
    Array,
    Object,
};

struct Value {
    Type type = Type::Null;
    bool boolean_value = false;
    double number_value = 0.0;
    std::string string_value;
    std::vector<Value> array_value;
    std::map<std::string, Value, std::less<>> object_value;

    const Value* Find(std::string_view key) const;
};

bool Parse(std::string_view json, Value* value, std::string* error_message);
std::string Serialize(const Value& value);
bool IsValidUtf8(std::string_view value);
std::size_t CountUtf8Scalars(std::string_view value);

}  // namespace sdmod::settings_json
