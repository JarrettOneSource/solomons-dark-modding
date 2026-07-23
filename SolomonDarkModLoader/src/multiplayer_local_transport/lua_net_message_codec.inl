constexpr std::uint8_t kLuaNetEnvelopeVersion = 1;

void SetLuaNetError(std::string* error_message, std::string message) {
    if (error_message != nullptr) {
        *error_message = std::move(message);
    }
}

bool IsValidLuaNetChannel(std::string_view channel) {
    return !channel.empty() &&
        channel.size() <= kLuaNetMaximumChannelBytes &&
        IsValidLuaModIdentifier(std::string(channel));
}

void AppendLuaNetU16(
    std::vector<std::uint8_t>* output,
    std::uint16_t value) {
    output->push_back(static_cast<std::uint8_t>(value));
    output->push_back(static_cast<std::uint8_t>(value >> 8));
}

void AppendLuaNetU32(
    std::vector<std::uint8_t>* output,
    std::uint32_t value) {
    for (unsigned int shift = 0; shift < 32; shift += 8) {
        output->push_back(static_cast<std::uint8_t>(value >> shift));
    }
}

bool EncodeLuaNetEnvelope(
    std::string_view mod_id,
    std::string_view channel,
    std::string_view payload,
    std::vector<std::uint8_t>* envelope,
    std::string* error_message) {
    if (envelope == nullptr ||
        !IsValidLuaModIdentifier(std::string(mod_id)) ||
        !IsValidLuaNetChannel(channel) ||
        payload.size() > kLuaNetMaximumPayloadBytes) {
        SetLuaNetError(error_message, "Lua net message identity or payload is invalid");
        return false;
    }
    envelope->clear();
    envelope->reserve(
        1 + 2 + mod_id.size() + 2 + channel.size() + 4 + payload.size());
    envelope->push_back(kLuaNetEnvelopeVersion);
    AppendLuaNetU16(envelope, static_cast<std::uint16_t>(mod_id.size()));
    envelope->insert(envelope->end(), mod_id.begin(), mod_id.end());
    AppendLuaNetU16(envelope, static_cast<std::uint16_t>(channel.size()));
    envelope->insert(envelope->end(), channel.begin(), channel.end());
    AppendLuaNetU32(envelope, static_cast<std::uint32_t>(payload.size()));
    envelope->insert(envelope->end(), payload.begin(), payload.end());
    if (envelope->empty() || envelope->size() >
        kLuaNetFragmentPayloadBytes * kLuaNetMaxFragments) {
        envelope->clear();
        SetLuaNetError(error_message, "Lua net message exceeds the fragmented wire limit");
        return false;
    }
    return true;
}

class LuaNetEnvelopeReader {
public:
    explicit LuaNetEnvelopeReader(const std::vector<std::uint8_t>& bytes)
        : bytes_(bytes) {}

    bool ReadVersion() {
        std::uint8_t version = 0;
        return ReadU8(&version) && version == kLuaNetEnvelopeVersion;
    }

    bool ReadText(std::size_t maximum, std::string* value) {
        std::uint16_t length = 0;
        if (value == nullptr || !ReadU16(&length) || length == 0 ||
            length > maximum || Remaining() < length) {
            return false;
        }
        value->assign(
            reinterpret_cast<const char*>(bytes_.data() + offset_),
            length);
        offset_ += length;
        return true;
    }

    bool ReadPayload(std::string* value) {
        std::uint32_t length = 0;
        if (value == nullptr || !ReadU32(&length) ||
            length > kLuaNetMaximumPayloadBytes || Remaining() != length) {
            return false;
        }
        value->assign(
            reinterpret_cast<const char*>(bytes_.data() + offset_),
            length);
        offset_ += length;
        return true;
    }

    bool AtEnd() const { return offset_ == bytes_.size(); }

private:
    std::size_t Remaining() const { return bytes_.size() - offset_; }

    bool ReadU8(std::uint8_t* value) {
        if (value == nullptr || Remaining() < 1) return false;
        *value = bytes_[offset_++];
        return true;
    }

    bool ReadU16(std::uint16_t* value) {
        if (value == nullptr || Remaining() < 2) return false;
        *value = static_cast<std::uint16_t>(bytes_[offset_]) |
            (static_cast<std::uint16_t>(bytes_[offset_ + 1]) << 8);
        offset_ += 2;
        return true;
    }

    bool ReadU32(std::uint32_t* value) {
        if (value == nullptr || Remaining() < 4) return false;
        *value = static_cast<std::uint32_t>(bytes_[offset_]) |
            (static_cast<std::uint32_t>(bytes_[offset_ + 1]) << 8) |
            (static_cast<std::uint32_t>(bytes_[offset_ + 2]) << 16) |
            (static_cast<std::uint32_t>(bytes_[offset_ + 3]) << 24);
        offset_ += 4;
        return true;
    }

    const std::vector<std::uint8_t>& bytes_;
    std::size_t offset_ = 0;
};

bool DecodeLuaNetEnvelope(
    const std::vector<std::uint8_t>& envelope,
    std::string* mod_id,
    std::string* channel,
    std::string* payload,
    std::string* error_message) {
    LuaNetEnvelopeReader reader(envelope);
    if (!reader.ReadVersion() ||
        !reader.ReadText(kLuaModMaxIdentifierBytes, mod_id) ||
        !reader.ReadText(kLuaNetMaximumChannelBytes, channel) ||
        !reader.ReadPayload(payload) || !reader.AtEnd() ||
        !IsValidLuaModIdentifier(*mod_id) ||
        !IsValidLuaNetChannel(*channel)) {
        SetLuaNetError(error_message, "Lua net message envelope is invalid");
        return false;
    }
    return true;
}

