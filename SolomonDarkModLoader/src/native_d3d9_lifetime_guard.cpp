#include "native_d3d9_lifetime_guard.h"

#include "binary_layout.h"
#include "logger.h"
#include "memory_access.h"
#include "mod_loader.h"

#include <Windows.h>
#include <d3d9.h>

#include <array>
#include <cstdint>
#include <cstring>
#include <limits>
#include <string>

namespace sdmod {
namespace {

constexpr std::uint64_t kDeviceAcquireTimeoutMs = 10000;
constexpr DWORD kDeviceAcquirePollMs = 10;
constexpr std::size_t kDeviceClearInstructionSize = 6;
constexpr std::uint8_t kMovAbsoluteFromEbxOpcode0 = 0x89;
constexpr std::uint8_t kMovAbsoluteFromEbxOpcode1 = 0x1D;

// The retail run loop outlives neither its asset worker nor its global
// SpriteBundle destructors. This reference intentionally belongs to the
// process, not to a loader subsystem. Process termination reclaims it after
// those native consumers finish; releasing it from loader shutdown would
// recreate the ownership inversion this guard closes.
IDirect3DDevice9* g_process_lifetime_device = nullptr;
bool g_guard_installed = false;

void SetError(
    std::string* error_message,
    const std::string& message) {
    if (error_message != nullptr) {
        *error_message = message;
    }
}

bool ReadRequiredAddress(
    const char* key,
    std::uintptr_t* address,
    std::string* error_message) {
    std::uintptr_t configured = 0;
    if (key == nullptr ||
        address == nullptr ||
        !TryGetBinaryLayoutNumericValue(
            "native_d3d_lifetime",
            key,
            &configured) ||
        configured == 0) {
        SetError(
            error_message,
            "Binary layout is missing native_d3d_lifetime." +
                std::string(key != nullptr ? key : "unknown") +
                ".");
        return false;
    }
    *address = ProcessMemory::Instance()
        .ResolveGameAddressOrZero(configured);
    if (*address == 0) {
        SetError(
            error_message,
            "Could not resolve native_d3d_lifetime." +
                std::string(key) + ".");
        return false;
    }
    return true;
}

bool RetainDevice(IDirect3DDevice9* device) {
    if (device == nullptr) {
        return false;
    }
    ULONG reference_count = 0;
    __try {
        reference_count = device->AddRef();
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return false;
    }
    return reference_count != 0;
}

void ReleaseDevice(IDirect3DDevice9* device) {
    if (device == nullptr) {
        return;
    }
    __try {
        device->Release();
    } __except (EXCEPTION_EXECUTE_HANDLER) {
    }
}

bool ValidateDeviceClearInstruction(
    std::uintptr_t instruction,
    std::uintptr_t device_global,
    std::string* error_message) {
    if (device_global >
        (std::numeric_limits<std::uint32_t>::max)()) {
        SetError(
            error_message,
            "Resolved D3D9 device global is not an x86 address.");
        return false;
    }
    std::array<std::uint8_t, kDeviceClearInstructionSize>
        expected{
            kMovAbsoluteFromEbxOpcode0,
            kMovAbsoluteFromEbxOpcode1,
            0,
            0,
            0,
            0};
    const auto operand =
        static_cast<std::uint32_t>(device_global);
    std::memcpy(
        expected.data() + 2,
        &operand,
        sizeof(operand));

    std::array<std::uint8_t, kDeviceClearInstructionSize>
        actual{};
    if (!ProcessMemory::Instance().TryRead(
            instruction,
            actual.data(),
            actual.size()) ||
        actual != expected) {
        SetError(
            error_message,
            "Native D3D9 device-clear instruction did not "
            "match the configured retail ownership seam.");
        return false;
    }
    return true;
}

}  // namespace

bool InitializeNativeD3d9LifetimeGuard(
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (g_guard_installed) {
        return true;
    }

    std::uintptr_t device_global = 0;
    std::uintptr_t device_clear = 0;
    if (!ReadRequiredAddress(
            "device_pointer_global",
            &device_global,
            error_message) ||
        !ReadRequiredAddress(
            "device_pointer_clear",
            &device_clear,
            error_message) ||
        !ValidateDeviceClearInstruction(
            device_clear,
            device_global,
            error_message)) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto started_ms =
        static_cast<std::uint64_t>(GetTickCount64());
    while (static_cast<std::uint64_t>(GetTickCount64()) -
               started_ms <
           kDeviceAcquireTimeoutMs) {
        IDirect3DDevice9* device = nullptr;
        if (!memory.TryReadValue(
                device_global,
                &device) ||
            device == nullptr) {
            Sleep(kDeviceAcquirePollMs);
            continue;
        }
        if (!RetainDevice(device)) {
            Sleep(kDeviceAcquirePollMs);
            continue;
        }

        IDirect3DDevice9* confirmed_device = nullptr;
        if (!memory.TryReadValue(
                device_global,
                &confirmed_device) ||
            confirmed_device != device) {
            ReleaseDevice(device);
            Sleep(kDeviceAcquirePollMs);
            continue;
        }

        const std::array<
            std::uint8_t,
            kDeviceClearInstructionSize> no_op{
                0x90,
                0x90,
                0x90,
                0x90,
                0x90,
                0x90};
        if (!memory.TryWrite(
                device_clear,
                no_op.data(),
                no_op.size())) {
            ReleaseDevice(device);
            SetError(
                error_message,
                "Could not patch the native D3D9 device-clear "
                "ownership seam.");
            return false;
        }

        if (!memory.TryWriteValue(
                device_global,
                device)) {
            SetError(
                error_message,
                "Could not publish the retained D3D9 device after "
                "installing its process-lifetime guard.");
            return false;
        }
        IDirect3DDevice9* device_after_patch = nullptr;
        if (!memory.TryReadValue(
                device_global,
                &device_after_patch) ||
            device_after_patch != device) {
            SetError(
                error_message,
                "Could not verify the retained D3D9 device after "
                "installing its process-lifetime guard.");
            return false;
        }

        g_process_lifetime_device = device;
        g_guard_installed = true;
        Log(
            "Native D3D9 process-lifetime guard installed. "
            "device_global=" +
            HexString(device_global) +
            " clear_instruction=" +
            HexString(device_clear));
        return true;
    }

    SetError(
        error_message,
        "Timed out waiting for the native D3D9 device needed "
        "by the process-lifetime guard.");
    return false;
}

bool IsNativeD3d9LifetimeGuardInstalled() {
    return g_guard_installed &&
        g_process_lifetime_device != nullptr;
}

}  // namespace sdmod
