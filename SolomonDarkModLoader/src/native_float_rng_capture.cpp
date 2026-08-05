#include "native_float_rng_capture.h"

#include "binary_layout.h"
#include "logger.h"
#include "memory_access.h"

#include <Windows.h>

#include <algorithm>
#include <array>
#include <cctype>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <exception>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <sstream>
#include <string>
#include <string_view>
#include <system_error>
#include <vector>

namespace sdmod {
namespace {

constexpr const char* kCaptureDirectoryEnvironment =
    "SDMOD_NATIVE_FLOAT_RNG_CAPTURE_DIRECTORY";
constexpr const char* kInstanceEnvironment = "SDMOD_LUA_EXEC_PIPE_NAME";
constexpr const char* kLayoutSection = "gameplay.hooks";
constexpr const char* kConstructorKey = "native_rng_construct";
constexpr const char* kSeedKey = "native_rng_initialize";
constexpr const char* kScaledFloatKey = "native_rng_float";
constexpr const char* kUnitFloatKey = "native_rng_unit_float";
constexpr std::size_t kNativeRngStateSize = 0xE8;
constexpr std::size_t kNativeRngWordCount = 55;
constexpr std::size_t kNativeRngDivisorOffset = 0xE4;
constexpr std::uint32_t kNativeRngDivisor = 100000;
constexpr std::uint32_t kNativeRngSeedMask = 0x3FFFFFFFu;
constexpr std::uint32_t kMaximumDrawCount = 256;

struct NativeRngState {
    std::uint32_t index_a = 0;
    std::uint32_t index_b = 0;
    std::array<std::uint32_t, kNativeRngWordCount> words = {};
    std::uint32_t divisor = 0;
};

static_assert(
    sizeof(NativeRngState) == kNativeRngStateSize,
    "native RNG capture state must preserve the retail 0xE8-byte layout");
static_assert(
    offsetof(NativeRngState, divisor) == kNativeRngDivisorOffset,
    "native RNG divisor must remain at this+0xE4");

using NativeRngConstructorFn = void(__thiscall*)(void* self);
using NativeRngSeedFn = void(__thiscall*)(void* self, std::uint32_t seed);
using NativeRngScaledFloatFn =
    float(__thiscall*)(void* self, float magnitude, int sign_mode);
using NativeRngUnitFloatFn =
    float(__thiscall*)(void* self, int sign_mode);

struct NativeFloatRngDraw {
    NativeRngState pre_call;
    NativeRngState post_call;
    std::uint32_t returned_float32_bits = 0;
};

struct NativeFloatRngCaptureState {
    bool requested = false;
    bool initialized = false;
    std::filesystem::path directory;
    std::uintptr_t constructor_preferred = 0;
    std::uintptr_t seed_preferred = 0;
    std::uintptr_t scaled_float_preferred = 0;
    std::uintptr_t unit_float_preferred = 0;
    std::uintptr_t constructor_runtime = 0;
    std::uintptr_t seed_runtime = 0;
    std::uintptr_t scaled_float_runtime = 0;
    std::uintptr_t unit_float_runtime = 0;
};

NativeFloatRngCaptureState g_capture;

int CaptureNativeFloatRngException(
    EXCEPTION_POINTERS* exception,
    DWORD* out_code) {
    if (exception != nullptr && exception->ExceptionRecord != nullptr &&
        out_code != nullptr) {
        *out_code = exception->ExceptionRecord->ExceptionCode;
    }
    return EXCEPTION_EXECUTE_HANDLER;
}

bool InvokeNativeRngConstructor(
    NativeRngConstructorFn constructor,
    NativeRngState* state,
    DWORD* exception_code) {
    __try {
        constructor(state);
        return true;
    } __except (CaptureNativeFloatRngException(
        GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool InvokeNativeRngSeed(
    NativeRngSeedFn seed_function,
    NativeRngState* state,
    std::uint32_t seed,
    DWORD* exception_code) {
    __try {
        seed_function(state, seed);
        return true;
    } __except (CaptureNativeFloatRngException(
        GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool InvokeNativeRngDraw(
    NativeFloatRngPrimitive primitive,
    NativeRngScaledFloatFn scaled_float,
    NativeRngUnitFloatFn unit_float,
    NativeRngState* state,
    float magnitude,
    bool signed_request,
    float* result,
    DWORD* exception_code) {
    __try {
        *result = primitive == NativeFloatRngPrimitive::Scaled
            ? scaled_float(state, magnitude, signed_request ? 1 : 0)
            : unit_float(state, signed_request ? 1 : 0);
        return true;
    } __except (CaptureNativeFloatRngException(
        GetExceptionInformation(), exception_code)) {
        return false;
    }
}

std::string EnvironmentValue(const char* name) {
    char value[32768] = {};
    const auto length = GetEnvironmentVariableA(
        name, value, static_cast<DWORD>(sizeof(value)));
    if (length == 0 || length >= sizeof(value)) {
        return {};
    }
    return std::string(value, length);
}

std::string CaptureInstance() {
    constexpr std::string_view kLuaPipePrefix =
        "SolomonDarkModLoader_LuaExec_";
    const auto pipe_name = EnvironmentValue(kInstanceEnvironment);
    if (pipe_name.size() >= kLuaPipePrefix.size() &&
        pipe_name.compare(0, kLuaPipePrefix.size(), kLuaPipePrefix) == 0) {
        return pipe_name.substr(kLuaPipePrefix.size());
    }
    return pipe_name;
}

std::string HexAddress(std::uintptr_t value) {
    std::ostringstream stream;
    stream << "0x" << std::uppercase << std::hex << std::setfill('0')
           << std::setw(8) << value;
    return stream.str();
}

std::string HexWord(std::uint32_t value) {
    std::ostringstream stream;
    stream << "0x" << std::uppercase << std::hex << std::setfill('0')
           << std::setw(8) << value;
    return stream.str();
}

void WriteJsonString(std::ostream& stream, std::string_view value) {
    stream << '"';
    for (const unsigned char character : value) {
        switch (character) {
        case '"':
            stream << "\\\"";
            break;
        case '\\':
            stream << "\\\\";
            break;
        case '\b':
            stream << "\\b";
            break;
        case '\f':
            stream << "\\f";
            break;
        case '\n':
            stream << "\\n";
            break;
        case '\r':
            stream << "\\r";
            break;
        case '\t':
            stream << "\\t";
            break;
        default:
            if (character < 0x20) {
                stream << "\\u00" << std::uppercase << std::hex
                       << std::setfill('0') << std::setw(2)
                       << static_cast<unsigned int>(character) << std::dec;
            } else {
                stream << static_cast<char>(character);
            }
            break;
        }
    }
    stream << '"';
}

void WriteNativeRngState(
    std::ostream& stream,
    const NativeRngState& state,
    unsigned int indentation) {
    const std::string indent(indentation, ' ');
    const std::string field_indent(indentation + 2, ' ');
    stream << "{\n";
    stream << field_indent << "\"index_a\": " << state.index_a << ",\n";
    stream << field_indent << "\"index_b\": " << state.index_b << ",\n";
    stream << field_indent << "\"state_words\": [";
    for (std::size_t index = 0; index < state.words.size(); ++index) {
        if (index != 0) {
            stream << ", ";
        }
        stream << state.words[index];
    }
    stream << "],\n";
    stream << field_indent << "\"divisor\": " << state.divisor << "\n";
    stream << indent << '}';
}

bool ResolveCaptureAddress(
    const char* key,
    std::uintptr_t* preferred,
    std::uintptr_t* runtime,
    std::string* error_message) {
    if (!TryGetBinaryLayoutNumericValue(
            kLayoutSection, key, preferred) ||
        *preferred == 0) {
        *error_message =
            "native float RNG capture binary layout is missing [" +
            std::string(kLayoutSection) + "]." + key;
        return false;
    }
    auto& memory = ProcessMemory::Instance();
    *runtime = memory.ResolveGameAddressOrZero(*preferred);
    if (*runtime == 0 || !memory.IsExecutableRange(*runtime, 1)) {
        *error_message =
            "native float RNG capture resolved a non-runnable address for [" +
            std::string(kLayoutSection) + "]." + key;
        return false;
    }
    return true;
}

bool WriteCaptureFile(
    const std::filesystem::path& output,
    const std::filesystem::path& temporary,
    std::string_view label,
    std::uint32_t seed,
    NativeFloatRngPrimitive primitive,
    float magnitude,
    bool signed_request,
    const std::vector<NativeFloatRngDraw>& draws,
    std::string* error_message) {
    try {
        std::ofstream stream(temporary, std::ios::binary | std::ios::trunc);
        if (!stream) {
            *error_message =
                "native float RNG capture could not create its temporary recording";
            return false;
        }

        std::uint32_t magnitude_bits = 0;
        std::memcpy(&magnitude_bits, &magnitude, sizeof(magnitude_bits));
        const auto primitive_name =
            primitive == NativeFloatRngPrimitive::Scaled ? "scaled" : "unit";
        const auto preferred_function =
            primitive == NativeFloatRngPrimitive::Scaled
                ? g_capture.scaled_float_preferred
                : g_capture.unit_float_preferred;
        const auto runtime_function =
            primitive == NativeFloatRngPrimitive::Scaled
                ? g_capture.scaled_float_runtime
                : g_capture.unit_float_runtime;

        stream << "{\n  \"schema\": \"solomon-dark-native-float-rng-recording-v1\",\n";
        stream << "  \"header\": {\n";
        stream << "    \"recorded_live\": true,\n";
        stream << "    \"instance\": ";
        WriteJsonString(stream, CaptureInstance());
        stream << ",\n    \"capture_method\": "
                  "\"opt-in loader seam calling retail RNG constructor, seed routine, and float primitive on isolated 0xE8-byte state\",\n";
        stream << "    \"constructor_preferred_address\": ";
        WriteJsonString(stream, HexAddress(g_capture.constructor_preferred));
        stream << ",\n    \"constructor_runtime_address\": ";
        WriteJsonString(stream, HexAddress(g_capture.constructor_runtime));
        stream << ",\n    \"seed_preferred_address\": ";
        WriteJsonString(stream, HexAddress(g_capture.seed_preferred));
        stream << ",\n    \"seed_runtime_address\": ";
        WriteJsonString(stream, HexAddress(g_capture.seed_runtime));
        stream << ",\n    \"primitive_preferred_address\": ";
        WriteJsonString(stream, HexAddress(preferred_function));
        stream << ",\n    \"primitive_runtime_address\": ";
        WriteJsonString(stream, HexAddress(runtime_function));
        stream << ",\n    \"state_size_bytes\": " << kNativeRngStateSize
               << ",\n    \"divisor_offset\": ";
        WriteJsonString(stream, HexAddress(kNativeRngDivisorOffset));
        stream << "\n  },\n";

        stream << "  \"request\": {\n    \"label\": ";
        WriteJsonString(stream, label);
        stream << ",\n    \"seed\": " << seed
               << ",\n    \"primitive\": ";
        WriteJsonString(stream, primitive_name);
        stream << ",\n    \"magnitude_float32_bits\": ";
        WriteJsonString(stream, HexWord(magnitude_bits));
        stream << ",\n    \"magnitude_source\": ";
        WriteJsonString(
            stream,
            primitive == NativeFloatRngPrimitive::Scaled
                ? "request"
                : "implicit-unit");
        stream << ",\n    \"signed\": "
               << (signed_request ? "true" : "false")
               << ",\n    \"count\": " << draws.size() << "\n  },\n";

        stream << "  \"draws\": [\n";
        for (std::size_t index = 0; index < draws.size(); ++index) {
            const auto& draw = draws[index];
            stream << "    {\n      \"draw_index\": " << index
                   << ",\n      \"pre_call\": ";
            WriteNativeRngState(stream, draw.pre_call, 6);
            stream << ",\n      \"request\": {\n"
                      "        \"magnitude_float32_bits\": ";
            WriteJsonString(stream, HexWord(magnitude_bits));
            stream << ",\n        \"signed\": "
                   << (signed_request ? "true" : "false")
                   << "\n      },\n      \"returned_float32_bits\": ";
            WriteJsonString(stream, HexWord(draw.returned_float32_bits));
            stream << ",\n      \"post_call\": ";
            WriteNativeRngState(stream, draw.post_call, 6);
            stream << "\n    }";
            if (index + 1 != draws.size()) {
                stream << ',';
            }
            stream << '\n';
        }
        stream << "  ]\n}\n";
        stream.flush();
        if (!stream) {
            *error_message =
                "native float RNG capture failed while writing its temporary recording";
            stream.close();
            std::error_code remove_error;
            std::filesystem::remove(temporary, remove_error);
            return false;
        }
        stream.close();

        std::filesystem::rename(temporary, output);
        return true;
    } catch (const std::exception& ex) {
        std::error_code remove_error;
        std::filesystem::remove(temporary, remove_error);
        *error_message =
            std::string("native float RNG capture recording path is not runnable: ") +
            ex.what();
        return false;
    }
}

}  // namespace

bool IsNativeFloatRngCaptureRequested() {
    char value[2] = {};
    const auto length = GetEnvironmentVariableA(
        kCaptureDirectoryEnvironment,
        value,
        static_cast<DWORD>(sizeof(value)));
    return length != 0;
}

bool IsNativeFloatRngCaptureInitialized() {
    return g_capture.initialized;
}

bool InitializeNativeFloatRngCapture(std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (g_capture.initialized) {
        return true;
    }
    g_capture.requested = IsNativeFloatRngCaptureRequested();
    if (!g_capture.requested) {
        return true;
    }
    if (error_message == nullptr) {
        return false;
    }

    char directory_value[32768] = {};
    const auto directory_length = GetEnvironmentVariableA(
        kCaptureDirectoryEnvironment,
        directory_value,
        static_cast<DWORD>(sizeof(directory_value)));
    if (directory_length == 0 || directory_length >= sizeof(directory_value)) {
        *error_message =
            "native float RNG capture directory is missing or exceeds the Windows environment limit";
        return false;
    }

    try {
        g_capture.directory = std::filesystem::u8path(
            std::string(directory_value, directory_length));
        std::filesystem::create_directories(g_capture.directory);
        const auto write_probe =
            g_capture.directory / ".native-float-rng-capture-write-probe";
        {
            std::ofstream stream(
                write_probe, std::ios::binary | std::ios::trunc);
            stream << "native-float-rng-capture-write-probe\n";
            stream.flush();
            if (!stream) {
                *error_message =
                    "native float RNG capture directory exists but cannot write a probe file";
                return false;
            }
        }
        std::error_code remove_error;
        if (!std::filesystem::remove(write_probe, remove_error) ||
            remove_error) {
            *error_message =
                "native float RNG capture directory wrote but could not remove its probe file";
            return false;
        }
    } catch (const std::exception& ex) {
        *error_message =
            std::string("native float RNG capture directory is not runnable: ") +
            ex.what();
        return false;
    }

    if (!IsBinaryLayoutLoaded()) {
        *error_message =
            "native float RNG capture requires a loaded binary layout";
        return false;
    }
    if (!ResolveCaptureAddress(
            kConstructorKey,
            &g_capture.constructor_preferred,
            &g_capture.constructor_runtime,
            error_message) ||
        !ResolveCaptureAddress(
            kSeedKey,
            &g_capture.seed_preferred,
            &g_capture.seed_runtime,
            error_message) ||
        !ResolveCaptureAddress(
            kScaledFloatKey,
            &g_capture.scaled_float_preferred,
            &g_capture.scaled_float_runtime,
            error_message) ||
        !ResolveCaptureAddress(
            kUnitFloatKey,
            &g_capture.unit_float_preferred,
            &g_capture.unit_float_runtime,
            error_message)) {
        return false;
    }

    g_capture.initialized = true;
    Log(
        "Native float RNG capture initialized. directory=" +
        g_capture.directory.string());
    return true;
}

void ShutdownNativeFloatRngCapture() {
    g_capture = NativeFloatRngCaptureState{};
}

bool CaptureNativeFloatRngRecording(
    std::string_view label,
    std::uint32_t seed,
    NativeFloatRngPrimitive primitive,
    float magnitude,
    bool signed_request,
    std::uint32_t count,
    std::string* output_path,
    std::string* error_message) {
    if (output_path != nullptr) {
        output_path->clear();
    }
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (output_path == nullptr || error_message == nullptr) {
        return false;
    }
    if (!g_capture.requested || !g_capture.initialized) {
        *error_message =
            "native float RNG capture is unavailable; launch with SDMOD_NATIVE_FLOAT_RNG_CAPTURE_DIRECTORY";
        return false;
    }
    if (label.empty() || label.size() > 96 ||
        !std::all_of(
            label.begin(),
            label.end(),
            [](unsigned char character) {
                return std::isalnum(character) != 0 || character == '-' ||
                    character == '_';
            })) {
        *error_message =
            "native float RNG capture label must be 1-96 ASCII letters, digits, hyphens, or underscores";
        return false;
    }
    if (seed > kNativeRngSeedMask) {
        *error_message = "native float RNG capture seed exceeds 0x3fffffff";
        return false;
    }
    if (count == 0 || count > kMaximumDrawCount) {
        *error_message =
            "native float RNG capture count must be from 1 through 256";
        return false;
    }
    if (!std::isfinite(magnitude) || magnitude < 0.0f) {
        *error_message =
            "native float RNG capture magnitude must be finite and non-negative";
        return false;
    }
    if (primitive == NativeFloatRngPrimitive::Unit && magnitude != 1.0f) {
        *error_message =
            "native unit-float RNG capture requires the implicit magnitude 1.0";
        return false;
    }

    const auto output =
        g_capture.directory / (std::string(label) + ".json");
    const auto temporary =
        g_capture.directory / (std::string(label) + ".json.tmp");
    std::error_code exists_error;
    const bool output_exists = std::filesystem::exists(output, exists_error);
    if (exists_error) {
        *error_message =
            "native float RNG capture could not inspect its output path";
        return false;
    }
    const bool temporary_exists =
        std::filesystem::exists(temporary, exists_error);
    if (exists_error) {
        *error_message =
            "native float RNG capture could not inspect its temporary path";
        return false;
    }
    if (output_exists || temporary_exists) {
        *error_message =
            "native float RNG capture refuses to overwrite an existing output or temporary file";
        return false;
    }

    auto* constructor = reinterpret_cast<NativeRngConstructorFn>(
        g_capture.constructor_runtime);
    auto* seed_function = reinterpret_cast<NativeRngSeedFn>(
        g_capture.seed_runtime);
    auto* scaled_float = reinterpret_cast<NativeRngScaledFloatFn>(
        g_capture.scaled_float_runtime);
    auto* unit_float = reinterpret_cast<NativeRngUnitFloatFn>(
        g_capture.unit_float_runtime);
    NativeRngState state{};
    DWORD exception_code = 0;
    if (!InvokeNativeRngConstructor(
            constructor, &state, &exception_code)) {
        std::ostringstream message;
        message << "native float RNG constructor failed with SEH 0x"
                << std::uppercase << std::hex << std::setfill('0')
                << std::setw(8) << exception_code;
        *error_message = message.str();
        return false;
    }
    if (state.divisor != kNativeRngDivisor) {
        *error_message =
            "native float RNG constructor did not initialize this+0xE4 to 100000";
        return false;
    }
    exception_code = 0;
    if (!InvokeNativeRngSeed(
            seed_function, &state, seed, &exception_code)) {
        std::ostringstream message;
        message << "native float RNG seed routine failed with SEH 0x"
                << std::uppercase << std::hex << std::setfill('0')
                << std::setw(8) << exception_code;
        *error_message = message.str();
        return false;
    }
    if (state.divisor != kNativeRngDivisor) {
        *error_message =
            "native float RNG seed routine changed the constructor divisor at this+0xE4";
        return false;
    }

    std::vector<NativeFloatRngDraw> draws;
    draws.reserve(count);
    for (std::uint32_t index = 0; index < count; ++index) {
        NativeFloatRngDraw draw;
        draw.pre_call = state;
        float returned = 0.0f;
        exception_code = 0;
        if (!InvokeNativeRngDraw(
                primitive,
                scaled_float,
                unit_float,
                &state,
                magnitude,
                signed_request,
                &returned,
                &exception_code)) {
            std::ostringstream message;
            message << "native float RNG draw " << index
                    << " failed with SEH 0x" << std::uppercase << std::hex
                    << std::setfill('0') << std::setw(8) << exception_code;
            *error_message = message.str();
            return false;
        }
        std::memcpy(
            &draw.returned_float32_bits,
            &returned,
            sizeof(draw.returned_float32_bits));
        draw.post_call = state;
        if (draw.post_call.divisor != kNativeRngDivisor) {
            *error_message =
                "native float RNG primitive changed the per-object divisor at this+0xE4";
            return false;
        }
        draws.push_back(draw);
    }

    if (!WriteCaptureFile(
            output,
            temporary,
            label,
            seed,
            primitive,
            magnitude,
            signed_request,
            draws,
            error_message)) {
        return false;
    }
    *output_path = output.u8string();
    return true;
}

}  // namespace sdmod
