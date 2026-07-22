constexpr std::uint8_t kLuaModStreamPayloadVersion = 1;

void SetLuaModStreamError(
    std::string* error_message,
    const std::string& message) {
    if (error_message != nullptr) {
        *error_message = message;
    }
}

void AppendLuaModU16(
    std::vector<std::uint8_t>* output,
    std::uint16_t value) {
    output->push_back(static_cast<std::uint8_t>(value));
    output->push_back(static_cast<std::uint8_t>(value >> 8));
}

void AppendLuaModU32(
    std::vector<std::uint8_t>* output,
    std::uint32_t value) {
    for (unsigned int shift = 0; shift < 32; shift += 8) {
        output->push_back(static_cast<std::uint8_t>(value >> shift));
    }
}

void AppendLuaModText(
    std::vector<std::uint8_t>* output,
    const std::string& value) {
    AppendLuaModU16(
        output,
        static_cast<std::uint16_t>(value.size()));
    output->insert(output->end(), value.begin(), value.end());
}

bool EncodeLuaModStreamPayload(
    const std::string& mod_id,
    const std::string* secondary_name,
    const LuaModValue* value,
    std::size_t maximum_value_bytes,
    std::vector<std::uint8_t>* payload,
    std::string* error_message) {
    if (payload == nullptr || !IsValidLuaModIdentifier(mod_id)) {
        SetLuaModStreamError(
            error_message,
            "Lua mod stream payload has an invalid mod id");
        return false;
    }
    std::vector<std::uint8_t> encoded_value;
    if (value != nullptr &&
        (!EncodeLuaModValue(*value, &encoded_value, error_message) ||
         encoded_value.size() > maximum_value_bytes)) {
        if (error_message != nullptr && error_message->empty()) {
            *error_message = "Lua mod stream value exceeds its encoded limit";
        }
        return false;
    }

    payload->clear();
    payload->reserve(
        1 + 2 + mod_id.size() +
        (secondary_name == nullptr ? 0 : 2 + secondary_name->size()) +
        (value == nullptr ? 0 : 4 + encoded_value.size()));
    payload->push_back(kLuaModStreamPayloadVersion);
    AppendLuaModText(payload, mod_id);
    if (secondary_name != nullptr) {
        AppendLuaModText(payload, *secondary_name);
    }
    if (value != nullptr) {
        AppendLuaModU32(
            payload,
            static_cast<std::uint32_t>(encoded_value.size()));
        payload->insert(
            payload->end(),
            encoded_value.begin(),
            encoded_value.end());
    }
    if (payload->empty() ||
        payload->size() > kLuaModMaxStateSnapshotBytes) {
        SetLuaModStreamError(
            error_message,
            "Lua mod stream message exceeds the wire payload limit");
        payload->clear();
        return false;
    }
    return true;
}

class LuaModPayloadReader {
public:
    explicit LuaModPayloadReader(const std::vector<std::uint8_t>& payload)
        : payload_(payload) {}

    bool ReadVersion() {
        std::uint8_t version = 0;
        return ReadU8(&version) && version == kLuaModStreamPayloadVersion;
    }

    bool ReadText(std::size_t maximum_bytes, std::string* value) {
        std::uint16_t length = 0;
        if (value == nullptr || !ReadU16(&length) ||
            length == 0 || length > maximum_bytes ||
            Remaining() < length) {
            return false;
        }
        value->assign(
            reinterpret_cast<const char*>(payload_.data() + offset_),
            length);
        offset_ += length;
        return true;
    }

    bool ReadValue(
        std::size_t maximum_bytes,
        LuaModValue* value,
        std::string* error_message) {
        std::uint32_t encoded_size = 0;
        if (value == nullptr || !ReadU32(&encoded_size) ||
            encoded_size == 0 || encoded_size > maximum_bytes ||
            Remaining() < encoded_size) {
            SetLuaModStreamError(
                error_message,
                "Lua mod stream value has an invalid encoded size");
            return false;
        }
        if (!DecodeLuaModValue(
                payload_.data() + offset_,
                encoded_size,
                value,
                error_message)) {
            return false;
        }
        offset_ += encoded_size;
        return true;
    }

    bool AtEnd() const {
        return offset_ == payload_.size();
    }

private:
    std::size_t Remaining() const {
        return payload_.size() - offset_;
    }

    bool ReadU8(std::uint8_t* value) {
        if (value == nullptr || Remaining() < 1) {
            return false;
        }
        *value = payload_[offset_++];
        return true;
    }

    bool ReadU16(std::uint16_t* value) {
        if (value == nullptr || Remaining() < 2) {
            return false;
        }
        *value = static_cast<std::uint16_t>(payload_[offset_]) |
                 (static_cast<std::uint16_t>(payload_[offset_ + 1]) << 8);
        offset_ += 2;
        return true;
    }

    bool ReadU32(std::uint32_t* value) {
        if (value == nullptr || Remaining() < 4) {
            return false;
        }
        *value = static_cast<std::uint32_t>(payload_[offset_]) |
                 (static_cast<std::uint32_t>(payload_[offset_ + 1]) << 8) |
                 (static_cast<std::uint32_t>(payload_[offset_ + 2]) << 16) |
                 (static_cast<std::uint32_t>(payload_[offset_ + 3]) << 24);
        offset_ += 4;
        return true;
    }

    const std::vector<std::uint8_t>& payload_;
    std::size_t offset_ = 0;
};

bool DecodeLuaModStreamPayload(
    LuaModStreamMessageKind kind,
    const std::vector<std::uint8_t>& payload,
    std::string* mod_id,
    std::string* secondary_name,
    LuaModValue* value,
    std::string* error_message) {
    LuaModPayloadReader reader(payload);
    if (!reader.ReadVersion() ||
        !reader.ReadText(kLuaModMaxIdentifierBytes, mod_id)) {
        SetLuaModStreamError(
            error_message,
            "Lua mod stream payload header is invalid");
        return false;
    }

    const bool has_secondary_name =
        kind == LuaModStreamMessageKind::StateSet ||
        kind == LuaModStreamMessageKind::StateDelete ||
        kind == LuaModStreamMessageKind::Event;
    if (has_secondary_name &&
        !reader.ReadText(kLuaModMaxKeyBytes, secondary_name)) {
        SetLuaModStreamError(
            error_message,
            "Lua mod stream payload name is invalid");
        return false;
    }

    const bool has_value =
        kind == LuaModStreamMessageKind::StateSet ||
        kind == LuaModStreamMessageKind::Event;
    const auto value_limit =
        kind == LuaModStreamMessageKind::Event
            ? kLuaModMaxEventPayloadBytes
            : kLuaModMaxValueBytes;
    if (has_value &&
        !reader.ReadValue(value_limit, value, error_message)) {
        return false;
    }
    if (!reader.AtEnd()) {
        SetLuaModStreamError(
            error_message,
            "Lua mod stream payload contains trailing bytes");
        return false;
    }
    return true;
}
