#include "native_close_url_patch.h"

#include "binary_layout.h"
#include "logger.h"
#include "memory_access.h"

#include <array>
#include <cstdint>
#include <string>

namespace sdmod {
namespace {

constexpr std::array<std::uint8_t, 5> kOriginalCall = {
    0xE8, 0xCD, 0xD5, 0xE6, 0xFF};
constexpr std::array<std::uint8_t, 5> kNopCall = {
    0x90, 0x90, 0x90, 0x90, 0x90};

uintptr_t g_patch_address = 0;

}  // namespace

bool InitializeNativeCloseUrlPatch(std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (g_patch_address != 0) {
        return true;
    }

    uintptr_t configured_address = 0;
    uintptr_t patch_address = 0;
    auto& memory = ProcessMemory::Instance();
    if (!TryGetBinaryLayoutNumericValue(
            "native.runtime_patches",
            "raptisoft_close_url_launch_call",
            &configured_address) ||
        configured_address == 0 ||
        !memory.TryResolveGameAddress(
            configured_address,
            &patch_address)) {
        if (error_message != nullptr) {
            *error_message =
                "The Raptisoft close-URL call address is missing from binary-layout.ini.";
        }
        return false;
    }

    std::array<std::uint8_t, kOriginalCall.size()> observed{};
    if (!memory.TryRead(
            patch_address,
            observed.data(),
            observed.size()) ||
        observed != kOriginalCall) {
        if (error_message != nullptr) {
            *error_message =
                "The Raptisoft close-URL call bytes do not match the supported retail build.";
        }
        return false;
    }
    if (!memory.TryWrite(
            patch_address,
            kNopCall.data(),
            kNopCall.size())) {
        if (error_message != nullptr) {
            *error_message =
                "The Raptisoft close-URL call could not be disabled in process memory.";
        }
        return false;
    }

    g_patch_address = patch_address;
    Log(
        "Native close URL patch installed. address=0x005B65DE "
        "original=E8CDD5E6FF patch=9090909090");
    return true;
}

void ShutdownNativeCloseUrlPatch() {
    // Keep the close-path call disabled through the retail application's
    // destructor. Process teardown discards the in-memory patch; restoring it
    // here could race the destructor and launch the browser after all.
    g_patch_address = 0;
}

}  // namespace sdmod
