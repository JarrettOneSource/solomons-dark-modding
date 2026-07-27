#include "mod_settings_json.h"

#include <charconv>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <limits>
#include <sstream>
#include <utility>

namespace sdmod::settings_json {
namespace {

class Parser {
public:
    explicit Parser(std::string_view source) : source_(source) {}

    bool Run(Value* value, std::string* error_message) {
        if (value == nullptr || error_message == nullptr) {
            return false;
        }
        error_message->clear();
        SkipWhitespace();
        if (!ParseValue(value)) {
            *error_message = error_;
            return false;
        }
        SkipWhitespace();
        if (position_ != source_.size()) {
            Fail("unexpected trailing content");
            *error_message = error_;
            return false;
        }
        return true;
    }

private:
    bool ParseValue(Value* value) {
        if (position_ >= source_.size()) {
            return Fail("expected a JSON value");
        }
        switch (source_[position_]) {
        case 'n':
            return ParseLiteral("null", Type::Null, value);
        case 't':
            if (!ParseLiteral("true", Type::Boolean, value)) {
                return false;
            }
            value->boolean_value = true;
            return true;
        case 'f':
            if (!ParseLiteral("false", Type::Boolean, value)) {
                return false;
            }
            value->boolean_value = false;
            return true;
        case '"':
            value->type = Type::String;
            return ParseString(&value->string_value);
        case '[':
            return ParseArray(value);
        case '{':
            return ParseObject(value);
        default:
            if (source_[position_] == '-' ||
                (source_[position_] >= '0' && source_[position_] <= '9')) {
                return ParseNumber(value);
            }
            return Fail("unexpected character");
        }
    }

    bool ParseLiteral(
        std::string_view literal,
        Type type,
        Value* value) {
        if (source_.substr(position_, literal.size()) != literal) {
            return Fail("invalid JSON literal");
        }
        position_ += literal.size();
        *value = Value{};
        value->type = type;
        return true;
    }

    bool ParseNumber(Value* value) {
        const auto start = position_;
        if (source_[position_] == '-') {
            ++position_;
            if (position_ >= source_.size()) {
                return Fail("incomplete JSON number");
            }
        }
        if (source_[position_] == '0') {
            ++position_;
            if (position_ < source_.size() &&
                source_[position_] >= '0' && source_[position_] <= '9') {
                return Fail("JSON number has a leading zero");
            }
        } else if (source_[position_] >= '1' && source_[position_] <= '9') {
            while (position_ < source_.size() &&
                   source_[position_] >= '0' && source_[position_] <= '9') {
                ++position_;
            }
        } else {
            return Fail("JSON number is missing its integer part");
        }
        if (position_ < source_.size() && source_[position_] == '.') {
            ++position_;
            const auto fraction_start = position_;
            while (position_ < source_.size() &&
                   source_[position_] >= '0' && source_[position_] <= '9') {
                ++position_;
            }
            if (fraction_start == position_) {
                return Fail("JSON number is missing fraction digits");
            }
        }
        if (position_ < source_.size() &&
            (source_[position_] == 'e' || source_[position_] == 'E')) {
            ++position_;
            if (position_ < source_.size() &&
                (source_[position_] == '+' || source_[position_] == '-')) {
                ++position_;
            }
            const auto exponent_start = position_;
            while (position_ < source_.size() &&
                   source_[position_] >= '0' && source_[position_] <= '9') {
                ++position_;
            }
            if (exponent_start == position_) {
                return Fail("JSON number is missing exponent digits");
            }
        }

        const auto raw = source_.substr(start, position_ - start);
        double parsed = 0.0;
        const auto conversion = std::from_chars(
            raw.data(),
            raw.data() + raw.size(),
            parsed,
            std::chars_format::general);
        if (conversion.ec != std::errc{} ||
            conversion.ptr != raw.data() + raw.size() ||
            !std::isfinite(parsed)) {
            return Fail("JSON number is not finite");
        }
        *value = Value{};
        value->type = Type::Number;
        value->number_value = parsed;
        return true;
    }

    bool ParseString(std::string* value) {
        if (source_[position_] != '"') {
            return Fail("expected a JSON string");
        }
        ++position_;
        value->clear();
        while (position_ < source_.size()) {
            const auto character =
                static_cast<unsigned char>(source_[position_++]);
            if (character == '"') {
                if (!IsValidUtf8(*value)) {
                    return Fail("JSON string contains invalid UTF-8");
                }
                return true;
            }
            if (character < 0x20) {
                return Fail("JSON string contains a control character");
            }
            if (character != '\\') {
                value->push_back(static_cast<char>(character));
                continue;
            }
            if (position_ >= source_.size()) {
                return Fail("incomplete JSON escape");
            }
            const auto escaped = source_[position_++];
            switch (escaped) {
            case '"':
            case '\\':
            case '/':
                value->push_back(escaped);
                break;
            case 'b':
                value->push_back('\b');
                break;
            case 'f':
                value->push_back('\f');
                break;
            case 'n':
                value->push_back('\n');
                break;
            case 'r':
                value->push_back('\r');
                break;
            case 't':
                value->push_back('\t');
                break;
            case 'u': {
                std::uint32_t scalar = 0;
                if (!ParseHexQuad(&scalar)) {
                    return false;
                }
                if (scalar >= 0xD800 && scalar <= 0xDBFF) {
                    if (source_.substr(position_, 2) != "\\u") {
                        return Fail("JSON high surrogate has no low surrogate");
                    }
                    position_ += 2;
                    std::uint32_t low = 0;
                    if (!ParseHexQuad(&low)) {
                        return false;
                    }
                    if (low < 0xDC00 || low > 0xDFFF) {
                        return Fail("JSON high surrogate has an invalid low surrogate");
                    }
                    scalar = 0x10000 +
                        ((scalar - 0xD800) << 10) +
                        (low - 0xDC00);
                } else if (scalar >= 0xDC00 && scalar <= 0xDFFF) {
                    return Fail("JSON string contains an unpaired low surrogate");
                }
                AppendUtf8(scalar, value);
                break;
            }
            default:
                return Fail("invalid JSON escape");
            }
        }
        return Fail("unterminated JSON string");
    }

    bool ParseHexQuad(std::uint32_t* value) {
        if (position_ + 4 > source_.size()) {
            return Fail("incomplete JSON Unicode escape");
        }
        std::uint32_t parsed = 0;
        for (int index = 0; index < 4; ++index) {
            const auto character = source_[position_++];
            parsed <<= 4;
            if (character >= '0' && character <= '9') {
                parsed |= static_cast<std::uint32_t>(character - '0');
            } else if (character >= 'a' && character <= 'f') {
                parsed |= static_cast<std::uint32_t>(character - 'a' + 10);
            } else if (character >= 'A' && character <= 'F') {
                parsed |= static_cast<std::uint32_t>(character - 'A' + 10);
            } else {
                return Fail("invalid JSON Unicode escape");
            }
        }
        *value = parsed;
        return true;
    }

    static void AppendUtf8(std::uint32_t scalar, std::string* value) {
        if (scalar <= 0x7F) {
            value->push_back(static_cast<char>(scalar));
        } else if (scalar <= 0x7FF) {
            value->push_back(static_cast<char>(0xC0 | (scalar >> 6)));
            value->push_back(static_cast<char>(0x80 | (scalar & 0x3F)));
        } else if (scalar <= 0xFFFF) {
            value->push_back(static_cast<char>(0xE0 | (scalar >> 12)));
            value->push_back(
                static_cast<char>(0x80 | ((scalar >> 6) & 0x3F)));
            value->push_back(static_cast<char>(0x80 | (scalar & 0x3F)));
        } else {
            value->push_back(static_cast<char>(0xF0 | (scalar >> 18)));
            value->push_back(
                static_cast<char>(0x80 | ((scalar >> 12) & 0x3F)));
            value->push_back(
                static_cast<char>(0x80 | ((scalar >> 6) & 0x3F)));
            value->push_back(static_cast<char>(0x80 | (scalar & 0x3F)));
        }
    }

    bool ParseArray(Value* value) {
        ++position_;
        *value = Value{};
        value->type = Type::Array;
        SkipWhitespace();
        if (position_ < source_.size() && source_[position_] == ']') {
            ++position_;
            return true;
        }
        while (true) {
            Value element;
            if (!ParseValue(&element)) {
                return false;
            }
            value->array_value.push_back(std::move(element));
            SkipWhitespace();
            if (position_ >= source_.size()) {
                return Fail("unterminated JSON array");
            }
            if (source_[position_] == ']') {
                ++position_;
                return true;
            }
            if (source_[position_] != ',') {
                return Fail("expected a comma in JSON array");
            }
            ++position_;
            SkipWhitespace();
        }
    }

    bool ParseObject(Value* value) {
        ++position_;
        *value = Value{};
        value->type = Type::Object;
        SkipWhitespace();
        if (position_ < source_.size() && source_[position_] == '}') {
            ++position_;
            return true;
        }
        while (true) {
            if (position_ >= source_.size() || source_[position_] != '"') {
                return Fail("expected a property name in JSON object");
            }
            std::string key;
            if (!ParseString(&key)) {
                return false;
            }
            SkipWhitespace();
            if (position_ >= source_.size() || source_[position_] != ':') {
                return Fail("expected a colon after JSON property name");
            }
            ++position_;
            SkipWhitespace();
            Value field;
            if (!ParseValue(&field)) {
                return false;
            }
            if (!value->object_value.emplace(key, std::move(field)).second) {
                return Fail("duplicate JSON property '" + key + "'");
            }
            SkipWhitespace();
            if (position_ >= source_.size()) {
                return Fail("unterminated JSON object");
            }
            if (source_[position_] == '}') {
                ++position_;
                return true;
            }
            if (source_[position_] != ',') {
                return Fail("expected a comma in JSON object");
            }
            ++position_;
            SkipWhitespace();
        }
    }

    void SkipWhitespace() {
        while (position_ < source_.size()) {
            const auto character = source_[position_];
            if (character != ' ' && character != '\t' &&
                character != '\r' && character != '\n') {
                break;
            }
            ++position_;
        }
    }

    bool Fail(std::string message) {
        if (error_.empty()) {
            error_ = std::move(message) + " at byte " +
                std::to_string(position_);
        }
        return false;
    }

    std::string_view source_;
    std::size_t position_ = 0;
    std::string error_;
};

void AppendEscaped(std::string_view source, std::string* output) {
    output->push_back('"');
    for (const auto raw : source) {
        const auto character = static_cast<unsigned char>(raw);
        switch (character) {
        case '"':
            output->append("\\\"");
            break;
        case '\\':
            output->append("\\\\");
            break;
        case '\b':
            output->append("\\b");
            break;
        case '\f':
            output->append("\\f");
            break;
        case '\n':
            output->append("\\n");
            break;
        case '\r':
            output->append("\\r");
            break;
        case '\t':
            output->append("\\t");
            break;
        default:
            if (character < 0x20) {
                char escaped[7]{};
                std::snprintf(
                    escaped,
                    sizeof(escaped),
                    "\\u%04x",
                    static_cast<unsigned int>(character));
                output->append(escaped);
            } else {
                output->push_back(static_cast<char>(character));
            }
            break;
        }
    }
    output->push_back('"');
}

void AppendSerialized(const Value& value, std::string* output) {
    switch (value.type) {
    case Type::Null:
        output->append("null");
        break;
    case Type::Boolean:
        output->append(value.boolean_value ? "true" : "false");
        break;
    case Type::Number: {
        std::ostringstream stream;
        stream.precision(std::numeric_limits<double>::max_digits10);
        stream << value.number_value;
        output->append(stream.str());
        break;
    }
    case Type::String:
        AppendEscaped(value.string_value, output);
        break;
    case Type::Array:
        output->push_back('[');
        for (std::size_t index = 0; index < value.array_value.size(); ++index) {
            if (index != 0) {
                output->push_back(',');
            }
            AppendSerialized(value.array_value[index], output);
        }
        output->push_back(']');
        break;
    case Type::Object:
        output->push_back('{');
        {
            bool first = true;
            for (const auto& [key, field] : value.object_value) {
                if (!first) {
                    output->push_back(',');
                }
                first = false;
                AppendEscaped(key, output);
                output->push_back(':');
                AppendSerialized(field, output);
            }
        }
        output->push_back('}');
        break;
    }
}

}  // namespace

const Value* Value::Find(std::string_view key) const {
    if (type != Type::Object) {
        return nullptr;
    }
    const auto found = object_value.find(key);
    return found == object_value.end() ? nullptr : &found->second;
}

bool Parse(
    std::string_view json,
    Value* value,
    std::string* error_message) {
    return Parser(json).Run(value, error_message);
}

std::string Serialize(const Value& value) {
    std::string output;
    AppendSerialized(value, &output);
    return output;
}

bool IsValidUtf8(std::string_view value) {
    std::size_t index = 0;
    while (index < value.size()) {
        const auto first = static_cast<unsigned char>(value[index]);
        std::size_t length = 0;
        std::uint32_t scalar = 0;
        if (first <= 0x7F) {
            length = 1;
            scalar = first;
        } else if (first >= 0xC2 && first <= 0xDF) {
            length = 2;
            scalar = first & 0x1F;
        } else if (first >= 0xE0 && first <= 0xEF) {
            length = 3;
            scalar = first & 0x0F;
        } else if (first >= 0xF0 && first <= 0xF4) {
            length = 4;
            scalar = first & 0x07;
        } else {
            return false;
        }
        if (index + length > value.size()) {
            return false;
        }
        for (std::size_t offset = 1; offset < length; ++offset) {
            const auto next =
                static_cast<unsigned char>(value[index + offset]);
            if ((next & 0xC0) != 0x80) {
                return false;
            }
            scalar = (scalar << 6) | (next & 0x3F);
        }
        if ((length == 3 &&
             ((first == 0xE0 && scalar < 0x800) ||
              (first == 0xED && scalar >= 0xD800))) ||
            (length == 4 &&
             ((first == 0xF0 && scalar < 0x10000) ||
              (first == 0xF4 && scalar > 0x10FFFF))) ||
            (scalar >= 0xD800 && scalar <= 0xDFFF) ||
            scalar > 0x10FFFF) {
            return false;
        }
        index += length;
    }
    return true;
}

std::size_t CountUtf8Scalars(std::string_view value) {
    if (!IsValidUtf8(value)) {
        return 0;
    }
    std::size_t count = 0;
    for (const auto raw : value) {
        if ((static_cast<unsigned char>(raw) & 0xC0) != 0x80) {
            ++count;
        }
    }
    return count;
}

}  // namespace sdmod::settings_json
