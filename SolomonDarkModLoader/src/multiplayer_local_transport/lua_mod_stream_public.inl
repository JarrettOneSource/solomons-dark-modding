bool IsLuaModSimulationAuthority() {
    return !g_local_transport.initialized || g_local_transport.is_host;
}

bool PublishAuthoritativeLuaModStateSet(
    const std::string& mod_id,
    const std::string& key,
    const LuaModValue& value,
    std::uint64_t state_revision,
    std::uint64_t* stream_sequence,
    std::string* error_message) {
    if (!IsValidLuaModStateKey(key) || state_revision == 0) {
        SetLuaModStreamError(
            error_message,
            "Lua mod state set has an invalid key or revision");
        return false;
    }
    std::vector<std::uint8_t> payload;
    if (!EncodeLuaModStreamPayload(
            mod_id,
            &key,
            &value,
            kLuaModMaxValueBytes,
            &payload,
            error_message)) {
        return false;
    }
    return QueueAuthoritativeLuaModStreamMessage(
        LuaModStreamMessageKind::StateSet,
        state_revision,
        std::move(payload),
        stream_sequence,
        error_message);
}

bool PublishAuthoritativeLuaModStateDelete(
    const std::string& mod_id,
    const std::string& key,
    std::uint64_t state_revision,
    std::uint64_t* stream_sequence,
    std::string* error_message) {
    if (!IsValidLuaModStateKey(key) || state_revision == 0) {
        SetLuaModStreamError(
            error_message,
            "Lua mod state delete has an invalid key or revision");
        return false;
    }
    std::vector<std::uint8_t> payload;
    if (!EncodeLuaModStreamPayload(
            mod_id,
            &key,
            nullptr,
            0,
            &payload,
            error_message)) {
        return false;
    }
    return QueueAuthoritativeLuaModStreamMessage(
        LuaModStreamMessageKind::StateDelete,
        state_revision,
        std::move(payload),
        stream_sequence,
        error_message);
}

bool PublishAuthoritativeLuaModStateClear(
    const std::string& mod_id,
    std::uint64_t state_revision,
    std::uint64_t* stream_sequence,
    std::string* error_message) {
    if (state_revision == 0) {
        SetLuaModStreamError(
            error_message,
            "Lua mod state clear has an invalid revision");
        return false;
    }
    std::vector<std::uint8_t> payload;
    if (!EncodeLuaModStreamPayload(
            mod_id,
            nullptr,
            nullptr,
            0,
            &payload,
            error_message)) {
        return false;
    }
    return QueueAuthoritativeLuaModStreamMessage(
        LuaModStreamMessageKind::StateClear,
        state_revision,
        std::move(payload),
        stream_sequence,
        error_message);
}

bool PublishAuthoritativeLuaModEvent(
    const std::string& mod_id,
    const std::string& event_name,
    const LuaModValue& payload_value,
    std::uint64_t* stream_sequence,
    std::string* error_message) {
    if (!IsValidLuaModIdentifier(event_name)) {
        SetLuaModStreamError(
            error_message,
            "Lua mod event name is invalid");
        return false;
    }
    std::vector<std::uint8_t> payload;
    if (!EncodeLuaModStreamPayload(
            mod_id,
            &event_name,
            &payload_value,
            kLuaModMaxEventPayloadBytes,
            &payload,
            error_message)) {
        return false;
    }
    return QueueAuthoritativeLuaModStreamMessage(
        LuaModStreamMessageKind::Event,
        GetLuaModStateRevision(),
        std::move(payload),
        stream_sequence,
        error_message);
}
