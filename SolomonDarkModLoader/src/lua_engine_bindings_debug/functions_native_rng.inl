constexpr std::uint32_t kDebugNativeRngSeedMask = 0x3FFFFFFFu;
constexpr std::size_t kDebugNativeRngStateSize = 0xE8;
constexpr std::uint32_t kDebugNativeRngMaximumSamples = 256;

using DebugNativeRngInitializeFn =
    void(__thiscall*)(void* self, std::uint32_t seed);
using DebugNativeRngIntegerFn =
    std::int32_t(__thiscall*)(
        void* self,
        std::int32_t range,
        std::int32_t sign_mode);

int CaptureDebugNativeRngException(
    EXCEPTION_POINTERS* exception,
    DWORD* out_code) {
    if (exception != nullptr && exception->ExceptionRecord != nullptr &&
        out_code != nullptr) {
        *out_code = exception->ExceptionRecord->ExceptionCode;
    }
    return EXCEPTION_EXECUTE_HANDLER;
}

// sd.debug.sample_native_rng(seed, range, count) -> table
// Recorder-only seam: the retail initializer and integer sampler operate on
// an isolated stack state, never on the active gameplay RNG at 0x00818B08.
int LuaDebugSampleNativeRng(lua_State* state) {
    const auto seed =
        CheckLuaUnsignedInteger<std::uint32_t>(state, 1, "seed");
    const auto range =
        CheckLuaSignedInteger<std::int32_t>(state, 2, "range");
    const auto count =
        CheckLuaUnsignedInteger<std::uint32_t>(state, 3, "count");
    if (seed > kDebugNativeRngSeedMask) {
        return luaL_error(state, "seed must be at most 0x3fffffff");
    }
    if (range <= 0) {
        return luaL_error(state, "range must be positive");
    }
    if (count == 0 || count > kDebugNativeRngMaximumSamples) {
        return luaL_error(state, "count must be from 1 through 256");
    }

    auto& memory = ProcessMemory::Instance();
    const auto initialize_address =
        memory.ResolveGameAddressOrZero(kNativeRngInitialize);
    const auto integer_address =
        memory.ResolveGameAddressOrZero(kNativeRngInteger);
    if (initialize_address == 0 || integer_address == 0) {
        return luaL_error(state, "native RNG functions are unavailable");
    }

    alignas(8) std::array<std::uint8_t, kDebugNativeRngStateSize>
        rng_state{};
    auto* initialize =
        reinterpret_cast<DebugNativeRngInitializeFn>(initialize_address);
    auto* sample =
        reinterpret_cast<DebugNativeRngIntegerFn>(integer_address);
    std::array<std::int32_t, kDebugNativeRngMaximumSamples> outputs{};
    DWORD exception_code = 0;
    __try {
        initialize(rng_state.data(), seed);
        for (std::uint32_t index = 0; index < count; ++index) {
            outputs[index] = sample(rng_state.data(), range, 0);
        }
    } __except (CaptureDebugNativeRngException(
        GetExceptionInformation(),
        &exception_code)) {
    }
    if (exception_code != 0) {
        return luaL_error(
            state,
            "native RNG sample failed with SEH 0x%08lx",
            static_cast<unsigned long>(exception_code));
    }

    lua_createtable(state, 0, 8);
    lua_pushinteger(state, static_cast<lua_Integer>(seed));
    lua_setfield(state, -2, "seed");
    lua_pushinteger(state, static_cast<lua_Integer>(range));
    lua_setfield(state, -2, "range");
    lua_pushinteger(state, static_cast<lua_Integer>(count));
    lua_setfield(state, -2, "count");
    lua_pushliteral(state, "native-private-stack-state");
    lua_setfield(state, -2, "stream");

    lua_createtable(state, static_cast<int>(count), 0);
    for (std::uint32_t index = 0; index < count; ++index) {
        lua_pushinteger(
            state,
            static_cast<lua_Integer>(outputs[index]));
        lua_rawseti(state, -2, static_cast<lua_Integer>(index + 1));
    }
    lua_setfield(state, -2, "outputs");

    const auto* words = reinterpret_cast<const std::uint32_t*>(
        rng_state.data());
    lua_pushinteger(state, static_cast<lua_Integer>(words[0]));
    lua_setfield(state, -2, "final_index_a");
    lua_pushinteger(state, static_cast<lua_Integer>(words[1]));
    lua_setfield(state, -2, "final_index_b");
    lua_createtable(state, 55, 0);
    for (std::size_t index = 0; index < 55; ++index) {
        lua_pushinteger(
            state,
            static_cast<lua_Integer>(words[index + 2]));
        lua_rawseti(state, -2, static_cast<lua_Integer>(index + 1));
    }
    lua_setfield(state, -2, "final_state_words");
    return 1;
}

// sd.debug.capture_native_float_rng(
//     label, seed, primitive, magnitude, signed, count) -> boolean, string
// This function is registered only when the opt-in recorder initialized.
int LuaDebugCaptureNativeFloatRng(lua_State* state) {
    std::size_t label_size = 0;
    const char* label = luaL_checklstring(state, 1, &label_size);
    const auto seed =
        CheckLuaUnsignedInteger<std::uint32_t>(state, 2, "seed");
    const char* primitive_name = luaL_checkstring(state, 3);
    const auto magnitude = static_cast<float>(luaL_checknumber(state, 4));
    luaL_checktype(state, 5, LUA_TBOOLEAN);
    const bool signed_request = lua_toboolean(state, 5) != 0;
    const auto count =
        CheckLuaUnsignedInteger<std::uint32_t>(state, 6, "count");

    NativeFloatRngPrimitive primitive;
    if (std::strcmp(primitive_name, "scaled") == 0) {
        primitive = NativeFloatRngPrimitive::Scaled;
    } else if (std::strcmp(primitive_name, "unit") == 0) {
        primitive = NativeFloatRngPrimitive::Unit;
    } else {
        return luaL_error(state, "primitive must be 'scaled' or 'unit'");
    }

    std::string output_path;
    std::string error_message;
    const bool captured = CaptureNativeFloatRngRecording(
        std::string_view(label, label_size),
        seed,
        primitive,
        magnitude,
        signed_request,
        count,
        &output_path,
        &error_message);
    lua_pushboolean(state, captured ? 1 : 0);
    const auto& detail = captured ? output_path : error_message;
    lua_pushlstring(state, detail.c_str(), detail.size());
    return 2;
}
