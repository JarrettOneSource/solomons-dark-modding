#include "lua_mod_runtime.h"

#include <cmath>
#include <cstring>
#include <limits>
#include <type_traits>
#include <utility>

namespace sdmod {
namespace {

constexpr std::uint8_t kLuaModValueWireVersion = 1;
constexpr std::uint8_t kLuaModStateWireVersion = 1;

void SetError(std::string* error_message, const char* message) {
    if (error_message != nullptr) {
        *error_message = message;
    }
}

bool IsValidBoundedText(
    const std::string& value,
    std::size_t maximum_bytes) {
    if (value.empty() || value.size() > maximum_bytes) {
        return false;
    }
    for (const unsigned char ch : value) {
        if (ch < 0x20 || ch == 0x7F) {
            return false;
        }
    }
    return true;
}

bool IsValidIdentifierCharacter(unsigned char ch) {
    return (ch >= 'a' && ch <= 'z') ||
           (ch >= 'A' && ch <= 'Z') ||
           (ch >= '0' && ch <= '9') ||
           ch == '.' || ch == '_' || ch == '-' || ch == ':';
}

bool AppendBytes(
    std::vector<std::uint8_t>* output,
    const void* bytes,
    std::size_t byte_count,
    std::size_t maximum_size,
    std::string* error_message) {
    if (output == nullptr ||
        byte_count > maximum_size ||
        output->size() > maximum_size - byte_count) {
        SetError(error_message, "encoded Lua mod value exceeds its size limit");
        return false;
    }
    if (byte_count == 0) {
        return true;
    }
    const auto* begin = static_cast<const std::uint8_t*>(bytes);
    output->insert(output->end(), begin, begin + byte_count);
    return true;
}

template <typename Unsigned>
bool AppendUnsigned(
    std::vector<std::uint8_t>* output,
    Unsigned value,
    std::size_t maximum_size,
    std::string* error_message) {
    static_assert(std::is_unsigned_v<Unsigned>, "wire integers must be unsigned");
    std::uint8_t bytes[sizeof(Unsigned)]{};
    for (std::size_t index = 0; index < sizeof(Unsigned); ++index) {
        bytes[index] = static_cast<std::uint8_t>(value & 0xFFu);
        value >>= 8u;
    }
    return AppendBytes(
        output,
        bytes,
        sizeof(bytes),
        maximum_size,
        error_message);
}

bool AppendText16(
    std::vector<std::uint8_t>* output,
    const std::string& text,
    std::size_t maximum_text_bytes,
    std::size_t maximum_output_size,
    std::string* error_message) {
    if (!IsValidBoundedText(text, maximum_text_bytes) ||
        text.size() > (std::numeric_limits<std::uint16_t>::max)()) {
        SetError(error_message, "Lua mod text field is empty, invalid, or too long");
        return false;
    }
    return AppendUnsigned(
               output,
               static_cast<std::uint16_t>(text.size()),
               maximum_output_size,
               error_message) &&
           AppendBytes(
               output,
               text.data(),
               text.size(),
               maximum_output_size,
               error_message);
}

bool EncodeValueNode(
    const LuaModValue& value,
    std::size_t depth,
    std::size_t* node_count,
    std::vector<std::uint8_t>* output,
    std::size_t maximum_output_size,
    std::string* error_message) {
    if (node_count == nullptr || depth > kLuaModMaxValueDepth) {
        SetError(error_message, "Lua mod value exceeds the maximum nesting depth");
        return false;
    }
    ++(*node_count);
    if (*node_count > kLuaModMaxValueNodes) {
        SetError(error_message, "Lua mod value exceeds the maximum node count");
        return false;
    }

    if (!AppendUnsigned(
            output,
            static_cast<std::uint8_t>(value.type),
            maximum_output_size,
            error_message)) {
        return false;
    }

    switch (value.type) {
    case LuaModValueType::Nil:
        return true;
    case LuaModValueType::Boolean:
        return AppendUnsigned(
            output,
            static_cast<std::uint8_t>(value.boolean_value ? 1 : 0),
            maximum_output_size,
            error_message);
    case LuaModValueType::Integer:
        return AppendUnsigned(
            output,
            static_cast<std::uint64_t>(value.integer_value),
            maximum_output_size,
            error_message);
    case LuaModValueType::Number: {
        if (!std::isfinite(value.number_value)) {
            SetError(error_message, "Lua mod numbers must be finite");
            return false;
        }
        std::uint64_t bits = 0;
        static_assert(sizeof(bits) == sizeof(value.number_value));
        std::memcpy(&bits, &value.number_value, sizeof(bits));
        return AppendUnsigned(
            output,
            bits,
            maximum_output_size,
            error_message);
    }
    case LuaModValueType::String:
        if (value.string_value.size() > kLuaModMaxStringBytes ||
            value.string_value.size() >
                (std::numeric_limits<std::uint32_t>::max)()) {
            SetError(error_message, "Lua mod string exceeds the size limit");
            return false;
        }
        return AppendUnsigned(
                   output,
                   static_cast<std::uint32_t>(value.string_value.size()),
                   maximum_output_size,
                   error_message) &&
               AppendBytes(
                   output,
                   value.string_value.data(),
                   value.string_value.size(),
                   maximum_output_size,
                   error_message);
    case LuaModValueType::Array:
        if (value.array_value.size() > kLuaModMaxValueNodes ||
            !AppendUnsigned(
                output,
                static_cast<std::uint32_t>(value.array_value.size()),
                maximum_output_size,
                error_message)) {
            SetError(error_message, "Lua mod array exceeds the element limit");
            return false;
        }
        for (const auto& element : value.array_value) {
            if (!EncodeValueNode(
                    element,
                    depth + 1,
                    node_count,
                    output,
                    maximum_output_size,
                    error_message)) {
                return false;
            }
        }
        return true;
    case LuaModValueType::Object:
        if (value.object_value.size() > kLuaModMaxValueNodes ||
            !AppendUnsigned(
                output,
                static_cast<std::uint32_t>(value.object_value.size()),
                maximum_output_size,
                error_message)) {
            SetError(error_message, "Lua mod object exceeds the field limit");
            return false;
        }
        for (const auto& [key, field_value] : value.object_value) {
            if (!AppendText16(
                    output,
                    key,
                    kLuaModMaxKeyBytes,
                    maximum_output_size,
                    error_message) ||
                !EncodeValueNode(
                    field_value,
                    depth + 1,
                    node_count,
                    output,
                    maximum_output_size,
                    error_message)) {
                return false;
            }
        }
        return true;
    }

    SetError(error_message, "Lua mod value contains an unknown type");
    return false;
}

class WireReader {
public:
    WireReader(const std::uint8_t* bytes, std::size_t byte_count)
        : bytes_(bytes), byte_count_(byte_count) {}

    template <typename Unsigned>
    bool ReadUnsigned(Unsigned* value) {
        static_assert(std::is_unsigned_v<Unsigned>, "wire integers must be unsigned");
        if (value == nullptr || Remaining() < sizeof(Unsigned)) {
            return false;
        }
        Unsigned parsed = 0;
        for (std::size_t index = 0; index < sizeof(Unsigned); ++index) {
            parsed |= static_cast<Unsigned>(bytes_[offset_ + index]) <<
                      (index * 8u);
        }
        offset_ += sizeof(Unsigned);
        *value = parsed;
        return true;
    }

    bool ReadText16(std::size_t maximum_bytes, std::string* text) {
        std::uint16_t length = 0;
        if (text == nullptr || !ReadUnsigned(&length) ||
            length > maximum_bytes || Remaining() < length) {
            return false;
        }
        text->assign(
            reinterpret_cast<const char*>(bytes_ + offset_),
            length);
        offset_ += length;
        return IsValidBoundedText(*text, maximum_bytes);
    }

    bool ReadBytes(std::size_t byte_count, const std::uint8_t** bytes) {
        if (bytes == nullptr || Remaining() < byte_count) {
            return false;
        }
        *bytes = bytes_ + offset_;
        offset_ += byte_count;
        return true;
    }

    std::size_t Remaining() const {
        return offset_ <= byte_count_ ? byte_count_ - offset_ : 0;
    }

private:
    const std::uint8_t* bytes_ = nullptr;
    std::size_t byte_count_ = 0;
    std::size_t offset_ = 0;
};

bool DecodeValueNode(
    WireReader* reader,
    std::size_t depth,
    std::size_t* node_count,
    LuaModValue* value,
    std::string* error_message) {
    if (reader == nullptr || value == nullptr || node_count == nullptr ||
        depth > kLuaModMaxValueDepth) {
        SetError(error_message, "Lua mod value exceeds the maximum nesting depth");
        return false;
    }
    ++(*node_count);
    if (*node_count > kLuaModMaxValueNodes) {
        SetError(error_message, "Lua mod value exceeds the maximum node count");
        return false;
    }

    std::uint8_t type = 0;
    if (!reader->ReadUnsigned(&type) ||
        type > static_cast<std::uint8_t>(LuaModValueType::Object)) {
        SetError(error_message, "Lua mod value has an invalid type tag");
        return false;
    }
    LuaModValue parsed;
    parsed.type = static_cast<LuaModValueType>(type);

    switch (parsed.type) {
    case LuaModValueType::Nil:
        break;
    case LuaModValueType::Boolean: {
        std::uint8_t boolean = 0;
        if (!reader->ReadUnsigned(&boolean) || boolean > 1) {
            SetError(error_message, "Lua mod value has an invalid boolean");
            return false;
        }
        parsed.boolean_value = boolean != 0;
        break;
    }
    case LuaModValueType::Integer: {
        std::uint64_t integer = 0;
        if (!reader->ReadUnsigned(&integer)) {
            SetError(error_message, "Lua mod value has a truncated integer");
            return false;
        }
        parsed.integer_value = static_cast<std::int64_t>(integer);
        break;
    }
    case LuaModValueType::Number: {
        std::uint64_t bits = 0;
        if (!reader->ReadUnsigned(&bits)) {
            SetError(error_message, "Lua mod value has a truncated number");
            return false;
        }
        std::memcpy(&parsed.number_value, &bits, sizeof(bits));
        if (!std::isfinite(parsed.number_value)) {
            SetError(error_message, "Lua mod numbers must be finite");
            return false;
        }
        break;
    }
    case LuaModValueType::String: {
        std::uint32_t length = 0;
        const std::uint8_t* bytes = nullptr;
        if (!reader->ReadUnsigned(&length) ||
            length > kLuaModMaxStringBytes ||
            !reader->ReadBytes(length, &bytes)) {
            SetError(error_message, "Lua mod value has a truncated or oversized string");
            return false;
        }
        parsed.string_value.assign(
            reinterpret_cast<const char*>(bytes),
            length);
        break;
    }
    case LuaModValueType::Array: {
        std::uint32_t count = 0;
        if (!reader->ReadUnsigned(&count) || count > kLuaModMaxValueNodes) {
            SetError(error_message, "Lua mod value has an invalid array size");
            return false;
        }
        parsed.array_value.reserve(count);
        for (std::uint32_t index = 0; index < count; ++index) {
            LuaModValue element;
            if (!DecodeValueNode(
                    reader,
                    depth + 1,
                    node_count,
                    &element,
                    error_message)) {
                return false;
            }
            parsed.array_value.push_back(std::move(element));
        }
        break;
    }
    case LuaModValueType::Object: {
        std::uint32_t count = 0;
        if (!reader->ReadUnsigned(&count) || count > kLuaModMaxValueNodes) {
            SetError(error_message, "Lua mod value has an invalid object size");
            return false;
        }
        for (std::uint32_t index = 0; index < count; ++index) {
            std::string key;
            LuaModValue field_value;
            if (!reader->ReadText16(kLuaModMaxKeyBytes, &key) ||
                parsed.object_value.find(key) != parsed.object_value.end() ||
                !DecodeValueNode(
                    reader,
                    depth + 1,
                    node_count,
                    &field_value,
                    error_message)) {
                SetError(error_message, "Lua mod value has an invalid object field");
                return false;
            }
            parsed.object_value.emplace(std::move(key), std::move(field_value));
        }
        break;
    }
    }

    *value = std::move(parsed);
    return true;
}

}  // namespace

bool IsValidLuaModIdentifier(const std::string& value) {
    if (value.empty() || value.size() > kLuaModMaxIdentifierBytes) {
        return false;
    }
    for (const unsigned char ch : value) {
        if (!IsValidIdentifierCharacter(ch)) {
            return false;
        }
    }
    return true;
}

bool IsValidLuaModStateKey(const std::string& value) {
    return IsValidBoundedText(value, kLuaModMaxKeyBytes);
}

bool EncodeLuaModValue(
    const LuaModValue& value,
    std::vector<std::uint8_t>* encoded,
    std::string* error_message) {
    if (encoded == nullptr) {
        SetError(error_message, "encoded Lua mod value output is null");
        return false;
    }
    encoded->clear();
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!AppendUnsigned(
            encoded,
            kLuaModValueWireVersion,
            kLuaModMaxValueBytes,
            error_message)) {
        return false;
    }
    std::size_t node_count = 0;
    return EncodeValueNode(
        value,
        0,
        &node_count,
        encoded,
        kLuaModMaxValueBytes,
        error_message);
}

bool DecodeLuaModValue(
    const std::uint8_t* encoded,
    std::size_t encoded_size,
    LuaModValue* value,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (encoded == nullptr || value == nullptr || encoded_size == 0 ||
        encoded_size > kLuaModMaxValueBytes) {
        SetError(error_message, "encoded Lua mod value is empty or oversized");
        return false;
    }
    WireReader reader(encoded, encoded_size);
    std::uint8_t version = 0;
    if (!reader.ReadUnsigned(&version) || version != kLuaModValueWireVersion) {
        SetError(error_message, "encoded Lua mod value has an unsupported version");
        return false;
    }
    LuaModValue parsed;
    std::size_t node_count = 0;
    if (!DecodeValueNode(
            &reader,
            0,
            &node_count,
            &parsed,
            error_message) ||
        reader.Remaining() != 0) {
        if (error_message != nullptr && error_message->empty()) {
            *error_message = "encoded Lua mod value has trailing bytes";
        }
        return false;
    }
    *value = std::move(parsed);
    return true;
}

bool EncodeLuaModStateSnapshot(
    const LuaModStateSnapshot& snapshot,
    std::vector<std::uint8_t>* encoded,
    std::string* error_message) {
    if (encoded == nullptr) {
        SetError(error_message, "encoded Lua mod state output is null");
        return false;
    }
    encoded->clear();
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (snapshot.size() > kLuaModMaxValueNodes ||
        !AppendUnsigned(
            encoded,
            kLuaModStateWireVersion,
            kLuaModMaxStateSnapshotBytes,
            error_message) ||
        !AppendUnsigned(
            encoded,
            static_cast<std::uint32_t>(snapshot.size()),
            kLuaModMaxStateSnapshotBytes,
            error_message)) {
        SetError(error_message, "Lua mod state contains too many mods");
        return false;
    }

    for (const auto& [mod_id, values] : snapshot) {
        if (!IsValidLuaModIdentifier(mod_id) ||
            values.size() > kLuaModMaxValueNodes ||
            !AppendText16(
                encoded,
                mod_id,
                kLuaModMaxIdentifierBytes,
                kLuaModMaxStateSnapshotBytes,
                error_message) ||
            !AppendUnsigned(
                encoded,
                static_cast<std::uint32_t>(values.size()),
                kLuaModMaxStateSnapshotBytes,
                error_message)) {
            SetError(error_message, "Lua mod state contains an invalid mod entry");
            return false;
        }
        for (const auto& [key, value] : values) {
            std::vector<std::uint8_t> encoded_value;
            if (!IsValidLuaModStateKey(key) ||
                !EncodeLuaModValue(value, &encoded_value, error_message) ||
                !AppendText16(
                    encoded,
                    key,
                    kLuaModMaxKeyBytes,
                    kLuaModMaxStateSnapshotBytes,
                    error_message) ||
                !AppendUnsigned(
                    encoded,
                    static_cast<std::uint32_t>(encoded_value.size()),
                    kLuaModMaxStateSnapshotBytes,
                    error_message) ||
                !AppendBytes(
                    encoded,
                    encoded_value.data(),
                    encoded_value.size(),
                    kLuaModMaxStateSnapshotBytes,
                    error_message)) {
                SetError(error_message, "Lua mod state contains an invalid value entry");
                return false;
            }
        }
    }
    return true;
}

bool DecodeLuaModStateSnapshot(
    const std::uint8_t* encoded,
    std::size_t encoded_size,
    LuaModStateSnapshot* snapshot,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (encoded == nullptr || snapshot == nullptr || encoded_size == 0 ||
        encoded_size > kLuaModMaxStateSnapshotBytes) {
        SetError(error_message, "encoded Lua mod state is empty or oversized");
        return false;
    }

    WireReader reader(encoded, encoded_size);
    std::uint8_t version = 0;
    std::uint32_t mod_count = 0;
    if (!reader.ReadUnsigned(&version) || version != kLuaModStateWireVersion ||
        !reader.ReadUnsigned(&mod_count) || mod_count > kLuaModMaxValueNodes) {
        SetError(error_message, "encoded Lua mod state has an invalid header");
        return false;
    }

    LuaModStateSnapshot parsed;
    for (std::uint32_t mod_index = 0; mod_index < mod_count; ++mod_index) {
        std::string mod_id;
        std::uint32_t value_count = 0;
        if (!reader.ReadText16(kLuaModMaxIdentifierBytes, &mod_id) ||
            !IsValidLuaModIdentifier(mod_id) ||
            parsed.find(mod_id) != parsed.end() ||
            !reader.ReadUnsigned(&value_count) ||
            value_count > kLuaModMaxValueNodes) {
            SetError(error_message, "encoded Lua mod state has an invalid mod entry");
            return false;
        }
        LuaModStateValues values;
        for (std::uint32_t value_index = 0;
             value_index < value_count;
             ++value_index) {
            std::string key;
            std::uint32_t value_size = 0;
            const std::uint8_t* value_bytes = nullptr;
            LuaModValue value;
            if (!reader.ReadText16(kLuaModMaxKeyBytes, &key) ||
                !IsValidLuaModStateKey(key) ||
                values.find(key) != values.end() ||
                !reader.ReadUnsigned(&value_size) ||
                value_size == 0 || value_size > kLuaModMaxValueBytes ||
                !reader.ReadBytes(value_size, &value_bytes) ||
                !DecodeLuaModValue(
                    value_bytes,
                    value_size,
                    &value,
                    error_message)) {
                SetError(error_message, "encoded Lua mod state has an invalid value entry");
                return false;
            }
            values.emplace(std::move(key), std::move(value));
        }
        parsed.emplace(std::move(mod_id), std::move(values));
    }
    if (reader.Remaining() != 0) {
        SetError(error_message, "encoded Lua mod state has trailing bytes");
        return false;
    }
    *snapshot = std::move(parsed);
    return true;
}

}  // namespace sdmod
