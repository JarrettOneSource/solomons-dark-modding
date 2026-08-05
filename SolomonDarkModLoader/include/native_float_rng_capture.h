#pragma once

#include <cstdint>
#include <string>
#include <string_view>

namespace sdmod {

enum class NativeFloatRngPrimitive {
    Scaled,
    Unit,
};

bool IsNativeFloatRngCaptureRequested();
bool IsNativeFloatRngCaptureInitialized();
bool InitializeNativeFloatRngCapture(std::string* error_message);
void ShutdownNativeFloatRngCapture();

bool CaptureNativeFloatRngRecording(
    std::string_view label,
    std::uint32_t seed,
    NativeFloatRngPrimitive primitive,
    float magnitude,
    bool signed_request,
    std::uint32_t count,
    std::string* output_path,
    std::string* error_message);

}  // namespace sdmod
