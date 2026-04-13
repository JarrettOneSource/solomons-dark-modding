bool TryAddOffset(uintptr_t base_address, size_t offset, uintptr_t* result) {
    if (result == nullptr) {
        return false;
    }

    if (offset > static_cast<size_t>((std::numeric_limits<uintptr_t>::max)() - base_address)) {
        return false;
    }

    *result = base_address + offset;
    return true;
}

bool TrySubtractOffset(uintptr_t base_address, size_t offset, uintptr_t* result) {
    if (result == nullptr || offset > base_address) {
        return false;
    }

    *result = base_address - offset;
    return true;
}

template <typename T>
T CheckLuaUnsignedInteger(lua_State* state, int index, const char* argument_name) {
    static_assert(std::is_integral_v<T> && std::is_unsigned_v<T>, "Expected an unsigned integer type.");

    const lua_Integer value = luaL_checkinteger(state, index);
    if (value < 0) {
        const std::string message = std::string(argument_name) + " must be non-negative";
        luaL_argerror(state, index, message.c_str());
        return 0;
    }

    using LuaUnsigned = std::make_unsigned_t<lua_Integer>;
    const auto unsigned_value = static_cast<LuaUnsigned>(value);
    if (unsigned_value > static_cast<LuaUnsigned>((std::numeric_limits<T>::max)())) {
        const std::string message = std::string(argument_name) + " is out of range";
        luaL_argerror(state, index, message.c_str());
        return 0;
    }

    return static_cast<T>(unsigned_value);
}

template <typename T>
T CheckLuaSignedInteger(lua_State* state, int index, const char* argument_name) {
    static_assert(std::is_integral_v<T> && std::is_signed_v<T>, "Expected a signed integer type.");

    const lua_Integer value = luaL_checkinteger(state, index);
    if (value < static_cast<lua_Integer>((std::numeric_limits<T>::min)()) ||
        value > static_cast<lua_Integer>((std::numeric_limits<T>::max)())) {
        const std::string message = std::string(argument_name) + " is out of range";
        luaL_argerror(state, index, message.c_str());
        return 0;
    }

    return static_cast<T>(value);
}

size_t CheckLuaTransferSize(lua_State* state, int index, const char* argument_name) {
    const size_t size = CheckLuaUnsignedInteger<size_t>(state, index, argument_name);
    if (size == 0) {
        const std::string message = std::string(argument_name) + " must be greater than zero";
        luaL_argerror(state, index, message.c_str());
        return 0;
    }

    if (size > kMaxLuaDebugTransferSize) {
        const std::string message =
            std::string(argument_name) + " exceeds the maximum allowed size of " +
            std::to_string(kMaxLuaDebugTransferSize) + " bytes";
        luaL_argerror(state, index, message.c_str());
        return 0;
    }

    return size;
}

uintptr_t CheckLuaAddress(lua_State* state, int index, const char* argument_name) {
    return CheckLuaUnsignedInteger<uintptr_t>(state, index, argument_name);
}

size_t CheckLuaOffset(lua_State* state, int index, const char* argument_name) {
    return CheckLuaUnsignedInteger<size_t>(state, index, argument_name);
}

bool TryParseLuaOffsetTable(
    lua_State* state,
    int index,
    std::vector<size_t>* offsets,
    std::string* error_message = nullptr) {
    if (offsets == nullptr) {
        return false;
    }

    offsets->clear();
    if (!lua_istable(state, index)) {
        if (error_message != nullptr) {
            *error_message = "offsets must be a table";
        }
        return false;
    }

    const auto table_index = lua_absindex(state, index);
    const auto count = lua_rawlen(state, table_index);
    offsets->reserve(static_cast<size_t>(count));
    for (lua_Integer item_index = 1; item_index <= static_cast<lua_Integer>(count); ++item_index) {
        lua_rawgeti(state, table_index, item_index);
        if (!lua_isinteger(state, -1)) {
            if (error_message != nullptr) {
                *error_message =
                    "offsets[" + std::to_string(static_cast<int>(item_index)) + "] must be an integer";
            }
            lua_pop(state, 1);
            offsets->clear();
            return false;
        }

        const auto offset_value = lua_tointeger(state, -1);
        if (offset_value < 0 ||
            static_cast<unsigned long long>(offset_value) >
                static_cast<unsigned long long>((std::numeric_limits<size_t>::max)())) {
            if (error_message != nullptr) {
                *error_message =
                    "offsets[" + std::to_string(static_cast<int>(item_index)) + "] is out of range";
            }
            lua_pop(state, 1);
            offsets->clear();
            return false;
        }

        offsets->push_back(static_cast<size_t>(offset_value));
        lua_pop(state, 1);
    }

    return true;
}

template <typename T>
void PushLuaScalarValue(lua_State* state, T value) {
    if constexpr (std::is_floating_point_v<T>) {
        lua_pushnumber(state, static_cast<lua_Number>(value));
    } else {
        lua_pushinteger(state, static_cast<lua_Integer>(value));
    }
}

uintptr_t ResolveReadableLuaAddress(ProcessMemory& memory, uintptr_t address, size_t size) {
    if (memory.IsReadableRange(address, size)) {
        return address;
    }

    const auto resolved = memory.ResolveGameAddressOrZero(address);
    return resolved != 0 && memory.IsReadableRange(resolved, size) ? resolved : 0;
}

uintptr_t ResolveExecutableLuaAddress(ProcessMemory& memory, uintptr_t address) {
    if (memory.IsExecutableRange(address, 1)) {
        return address;
    }

    const auto resolved = memory.ResolveGameAddressOrZero(address);
    if (resolved != 0 && memory.IsExecutableRange(resolved, 1)) {
        return resolved;
    }

    return 0;
}

uintptr_t ResolveWritableLuaAddress(ProcessMemory& memory, uintptr_t address, size_t size) {
    if (memory.IsWritableRange(address, size)) {
        return address;
    }

    const auto resolved = memory.ResolveGameAddressOrZero(address);
    return resolved != 0 && memory.IsWritableRange(resolved, size) ? resolved : 0;
}

bool TryResolveLuaReadableAddress(
    ProcessMemory& memory,
    uintptr_t address,
    size_t size,
    uintptr_t* resolved_address,
    bool* translated = nullptr) {
    if (resolved_address == nullptr) {
        return false;
    }

    if (memory.IsReadableRange(address, size)) {
        *resolved_address = address;
        if (translated != nullptr) {
            *translated = false;
        }
        return true;
    }

    const auto resolved = memory.ResolveGameAddressOrZero(address);
    if (resolved == 0 || !memory.IsReadableRange(resolved, size)) {
        return false;
    }

    *resolved_address = resolved;
    if (translated != nullptr) {
        *translated = true;
    }
    return true;
}

template <typename T>
bool TryReadLuaAbsoluteValue(uintptr_t address, T* value) {
    auto& memory = ProcessMemory::Instance();
    const auto resolved_address = ResolveReadableLuaAddress(memory, address, sizeof(T));
    if (resolved_address == 0) {
        return false;
    }

    return memory.TryReadValue(resolved_address, value);
}

template <typename T>
bool TryReadLuaFieldValue(uintptr_t ptr_address, size_t offset, T* value) {
    auto& memory = ProcessMemory::Instance();
    const auto resolved_ptr_address = ResolveReadableLuaAddress(memory, ptr_address, sizeof(uintptr_t));
    if (resolved_ptr_address == 0) {
        return false;
    }

    uintptr_t base_address = 0;
    if (!memory.TryReadValue(resolved_ptr_address, &base_address) || base_address == 0) {
        return false;
    }

    uintptr_t field_address = 0;
    if (!TryAddOffset(base_address, offset, &field_address)) {
        return false;
    }

    const auto resolved_field_address = ResolveReadableLuaAddress(memory, field_address, sizeof(T));
    if (resolved_field_address == 0) {
        return false;
    }

    return memory.TryReadValue(resolved_field_address, value);
}

template <typename T>
bool TryWriteLuaAbsoluteValue(uintptr_t address, const T& value) {
    auto& memory = ProcessMemory::Instance();
    const auto resolved_address = ResolveWritableLuaAddress(memory, address, sizeof(T));
    if (resolved_address == 0) {
        return false;
    }

    return memory.TryWriteValue(resolved_address, value);
}

template <typename T>
bool TryWriteLuaFieldValue(uintptr_t ptr_address, size_t offset, const T& value) {
    auto& memory = ProcessMemory::Instance();
    const auto resolved_ptr_address = ResolveReadableLuaAddress(memory, ptr_address, sizeof(uintptr_t));
    if (resolved_ptr_address == 0) {
        return false;
    }

    uintptr_t base_address = 0;
    if (!memory.TryReadValue(resolved_ptr_address, &base_address) || base_address == 0) {
        return false;
    }

    uintptr_t field_address = 0;
    if (!TryAddOffset(base_address, offset, &field_address)) {
        return false;
    }

    const auto resolved_field_address = ResolveWritableLuaAddress(memory, field_address, sizeof(T));
    if (resolved_field_address == 0) {
        return false;
    }

    return memory.TryWriteValue(resolved_field_address, value);
}

template <typename T>
int PushLuaAbsoluteValueResult(lua_State* state, uintptr_t address) {
    T value = {};
    if (!TryReadLuaAbsoluteValue(address, &value)) {
        lua_pushnil(state);
        return 1;
    }

    PushLuaScalarValue(state, value);
    return 1;
}

template <typename T>
int PushLuaFieldValueResult(lua_State* state, uintptr_t ptr_address, size_t offset) {
    T value = {};
    if (!TryReadLuaFieldValue(ptr_address, offset, &value)) {
        lua_pushnil(state);
        return 1;
    }

    PushLuaScalarValue(state, value);
    return 1;
}

bool TryReadLuaPointerValue(uintptr_t address, uintptr_t* value) {
    return TryReadLuaAbsoluteValue(address, value);
}

bool TryResolveLuaPtrChainFromPointerSlot(
    uintptr_t ptr_address,
    const std::vector<size_t>& offsets,
    uintptr_t* final_address) {
    if (final_address == nullptr) {
        return false;
    }

    uintptr_t current = 0;
    if (!TryReadLuaPointerValue(ptr_address, &current) || current == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    for (const auto offset : offsets) {
        uintptr_t field_address = 0;
        if (!TryAddOffset(current, offset, &field_address)) {
            return false;
        }

        const auto resolved_field_address =
            ResolveReadableLuaAddress(memory, field_address, sizeof(uintptr_t));
        if (resolved_field_address == 0 ||
            !memory.TryReadValue(resolved_field_address, &current) ||
            current == 0) {
            return false;
        }
    }

    *final_address = current;
    return true;
}

bool TryResolveLuaPtrChainFromObjectBase(
    uintptr_t base_address,
    const std::vector<size_t>& offsets,
    uintptr_t* final_address) {
    if (final_address == nullptr || base_address == 0) {
        return false;
    }

    uintptr_t current = base_address;
    auto& memory = ProcessMemory::Instance();
    for (const auto offset : offsets) {
        uintptr_t field_address = 0;
        if (!TryAddOffset(current, offset, &field_address)) {
            return false;
        }

        const auto resolved_field_address =
            ResolveReadableLuaAddress(memory, field_address, sizeof(uintptr_t));
        if (resolved_field_address == 0 ||
            !memory.TryReadValue(resolved_field_address, &current) ||
            current == 0) {
            return false;
        }
    }

    *final_address = current;
    return true;
}

void PushLuaPtrChainSteps(
    lua_State* state,
    uintptr_t start_address,
    const std::vector<size_t>& offsets,
    bool start_is_pointer_slot) {
    lua_createtable(state, static_cast<int>(offsets.size() + (start_is_pointer_slot ? 1 : 0)), 0);
    auto& memory = ProcessMemory::Instance();

    uintptr_t current = 0;
    lua_createtable(state, 0, 4);
    lua_pushinteger(state, static_cast<lua_Integer>(start_address));
    lua_setfield(state, -2, "address");
    lua_pushstring(state, start_is_pointer_slot ? "pointer_slot" : "object_base");
    lua_setfield(state, -2, "kind");
    if (start_is_pointer_slot) {
        uintptr_t initial = 0;
        const auto ok = TryReadLuaPointerValue(start_address, &initial) && initial != 0;
        current = ok ? initial : 0;
        if (ok) {
            lua_pushinteger(state, static_cast<lua_Integer>(initial));
            lua_setfield(state, -2, "value");
        } else {
            lua_pushnil(state);
            lua_setfield(state, -2, "value");
            lua_pushboolean(state, 0);
            lua_setfield(state, -2, "valid");
        }
    } else {
        current = start_address;
        lua_pushinteger(state, static_cast<lua_Integer>(current));
        lua_setfield(state, -2, "value");
    }
    lua_rawseti(state, -2, 1);

    for (size_t index = 0; index < offsets.size(); ++index) {
        lua_createtable(state, 0, 6);
        lua_pushinteger(state, static_cast<lua_Integer>(offsets[index]));
        lua_setfield(state, -2, "offset");
        lua_pushinteger(state, static_cast<lua_Integer>(current));
        lua_setfield(state, -2, "base");

        uintptr_t field_address = 0;
        uintptr_t resolved_field_address = 0;
        uintptr_t next_value = 0;
        const auto field_ok =
            current != 0 &&
            TryAddOffset(current, offsets[index], &field_address) &&
            (resolved_field_address = ResolveReadableLuaAddress(memory, field_address, sizeof(uintptr_t))) != 0 &&
            memory.TryReadValue(resolved_field_address, &next_value) &&
            next_value != 0;

        lua_pushinteger(state, static_cast<lua_Integer>(field_address));
        lua_setfield(state, -2, "field_address");
        if (field_ok) {
            lua_pushinteger(state, static_cast<lua_Integer>(next_value));
            lua_setfield(state, -2, "value");
            lua_pushboolean(state, 1);
            lua_setfield(state, -2, "valid");
            current = next_value;
        } else {
            lua_pushnil(state);
            lua_setfield(state, -2, "value");
            lua_pushboolean(state, 0);
            lua_setfield(state, -2, "valid");
            current = 0;
        }

        lua_rawseti(state, -2, static_cast<lua_Integer>(index + 2));
    }
}

std::string FormatLuaHexBytes(const std::uint8_t* bytes, size_t size) {
    if (bytes == nullptr || size == 0) {
        return "";
    }

    std::ostringstream out;
    out << std::uppercase << std::hex << std::setfill('0');
    for (size_t index = 0; index < size; ++index) {
        if (index != 0) {
            out << ' ';
        }
        out << std::setw(2) << static_cast<unsigned int>(bytes[index]);
    }
    return out.str();
}

bool TryReadLuaBytes(uintptr_t address, size_t size, std::vector<std::uint8_t>* bytes) {
    if (bytes == nullptr) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto resolved_address = ResolveReadableLuaAddress(memory, address, size);
    if (resolved_address == 0) {
        return false;
    }

    bytes->assign(size, 0);
    return memory.TryRead(resolved_address, bytes->data(), bytes->size());
}

bool HasAsciiWhitespace(std::string_view value) {
    return std::any_of(value.begin(), value.end(), [](unsigned char character) {
        return std::isspace(character) != 0;
    });
}

int ParseHexDigit(char character) {
    if (character >= '0' && character <= '9') {
        return character - '0';
    }
    if (character >= 'a' && character <= 'f') {
        return 10 + (character - 'a');
    }
    if (character >= 'A' && character <= 'F') {
        return 10 + (character - 'A');
    }
    return -1;
}

bool TryParseHexByteToken(std::string_view token, int* value, std::string* error_message) {
    if (value == nullptr) {
        return false;
    }

    if (token.size() >= 2 && token[0] == '0' && (token[1] == 'x' || token[1] == 'X')) {
        token.remove_prefix(2);
    }

    if (token == "??") {
        *value = -1;
        return true;
    }

    if (token.size() != 2) {
        if (error_message != nullptr) {
            *error_message = "hex_pattern must contain two hex digits per byte";
        }
        return false;
    }

    const auto upper_nibble = ParseHexDigit(token[0]);
    const auto lower_nibble = ParseHexDigit(token[1]);
    if (upper_nibble < 0 || lower_nibble < 0) {
        if (error_message != nullptr) {
            *error_message = "hex_pattern contains a non-hex byte";
        }
        return false;
    }

    *value = static_cast<int>((upper_nibble << 4) | lower_nibble);
    return true;
}

bool TryParseLuaHexPattern(std::string_view hex_pattern, std::vector<int>* pattern, std::string* error_message) {
    if (pattern == nullptr) {
        return false;
    }

    pattern->clear();
    if (hex_pattern.empty()) {
        if (error_message != nullptr) {
            *error_message = "hex_pattern must not be empty";
        }
        return false;
    }

    if (HasAsciiWhitespace(hex_pattern)) {
        size_t position = 0;
        while (position < hex_pattern.size()) {
            while (position < hex_pattern.size() &&
                   std::isspace(static_cast<unsigned char>(hex_pattern[position])) != 0) {
                ++position;
            }
            if (position >= hex_pattern.size()) {
                break;
            }

            const auto token_start = position;
            while (position < hex_pattern.size() &&
                   std::isspace(static_cast<unsigned char>(hex_pattern[position])) == 0) {
                ++position;
            }

            int value = 0;
            if (!TryParseHexByteToken(hex_pattern.substr(token_start, position - token_start), &value, error_message)) {
                pattern->clear();
                return false;
            }
            pattern->push_back(value);
        }
    } else {
        if (hex_pattern.size() >= 2 && hex_pattern[0] == '0' && (hex_pattern[1] == 'x' || hex_pattern[1] == 'X')) {
            hex_pattern.remove_prefix(2);
        }
        if ((hex_pattern.size() % 2) != 0) {
            if (error_message != nullptr) {
                *error_message = "hex_pattern must contain an even number of hex digits";
            }
            return false;
        }

        for (size_t index = 0; index < hex_pattern.size(); index += 2) {
            int value = 0;
            if (!TryParseHexByteToken(hex_pattern.substr(index, 2), &value, error_message)) {
                pattern->clear();
                return false;
            }
            pattern->push_back(value);
        }
    }

    if (pattern->empty()) {
        if (error_message != nullptr) {
            *error_message = "hex_pattern must not be empty";
        }
        return false;
    }

    return true;
}

bool PatternMatchesAt(const std::uint8_t* bytes, size_t size, size_t offset, const std::vector<int>& pattern) {
    if (bytes == nullptr || offset > size || pattern.size() > size - offset) {
        return false;
    }

    for (size_t index = 0; index < pattern.size(); ++index) {
        if (pattern[index] >= 0 && bytes[offset + index] != static_cast<std::uint8_t>(pattern[index])) {
            return false;
        }
    }

    return true;
}

std::string NormalizeLuaDebugTypeName(std::string_view value) {
    std::string normalized(value);
    std::transform(normalized.begin(), normalized.end(), normalized.begin(), [](unsigned char character) {
        return static_cast<char>(std::tolower(character));
    });
    return normalized;
}

bool TryParseLuaDebugFieldType(std::string_view type_name, LuaDebugFieldType* type) {
    if (type == nullptr) {
        return false;
    }

    const auto normalized = NormalizeLuaDebugTypeName(type_name);
    if (normalized == "u8" || normalized == "uint8" || normalized == "byte") {
        *type = LuaDebugFieldType::U8;
        return true;
    }
    if (normalized == "u16" || normalized == "uint16") {
        *type = LuaDebugFieldType::U16;
        return true;
    }
    if (normalized == "u32" || normalized == "uint32") {
        *type = LuaDebugFieldType::U32;
        return true;
    }
    if (normalized == "i8" || normalized == "int8") {
        *type = LuaDebugFieldType::I8;
        return true;
    }
    if (normalized == "i16" || normalized == "int16") {
        *type = LuaDebugFieldType::I16;
        return true;
    }
    if (normalized == "i32" || normalized == "int32" || normalized == "int") {
        *type = LuaDebugFieldType::I32;
        return true;
    }
    if (normalized == "float" || normalized == "f32") {
        *type = LuaDebugFieldType::Float;
        return true;
    }
    if (normalized == "ptr" || normalized == "pointer" || normalized == "address") {
        *type = LuaDebugFieldType::Ptr;
        return true;
    }

    return false;
}

bool PushLuaAbsoluteValueByType(lua_State* state, uintptr_t address, LuaDebugFieldType type) {
    switch (type) {
    case LuaDebugFieldType::U8:
        return PushLuaAbsoluteValueResult<std::uint8_t>(state, address), true;
    case LuaDebugFieldType::U16:
        return PushLuaAbsoluteValueResult<std::uint16_t>(state, address), true;
    case LuaDebugFieldType::U32:
        return PushLuaAbsoluteValueResult<std::uint32_t>(state, address), true;
    case LuaDebugFieldType::I8:
        return PushLuaAbsoluteValueResult<std::int8_t>(state, address), true;
    case LuaDebugFieldType::I16:
        return PushLuaAbsoluteValueResult<std::int16_t>(state, address), true;
    case LuaDebugFieldType::I32:
        return PushLuaAbsoluteValueResult<std::int32_t>(state, address), true;
    case LuaDebugFieldType::Float:
        return PushLuaAbsoluteValueResult<float>(state, address), true;
    case LuaDebugFieldType::Ptr:
        return PushLuaAbsoluteValueResult<uintptr_t>(state, address), true;
    }

    lua_pushnil(state);
    return false;
}

bool TryComputeInclusiveRangeSize(uintptr_t start, uintptr_t end, size_t* size) {
    if (size == nullptr || end < start) {
        return false;
    }

    const auto span = static_cast<unsigned long long>(end) - static_cast<unsigned long long>(start) + 1ull;
    if (span > static_cast<unsigned long long>((std::numeric_limits<size_t>::max)())) {
        return false;
    }

    *size = static_cast<size_t>(span);
    return true;
}
