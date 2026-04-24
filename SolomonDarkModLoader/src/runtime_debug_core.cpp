#include "runtime_debug_internal.h"

namespace sdmod::detail::runtime_debug {

uintptr_t ResolveRuntimeAddress(uintptr_t address) {
    if (address == 0) {
        return 0;
    }

    auto& memory = sdmod::ProcessMemory::Instance();
    if (memory.IsReadableRange(address, 1)) {
        return address;
    }

    const auto resolved = memory.ResolveGameAddressOrZero(address);
    return resolved != 0 ? resolved : address;
}

uintptr_t ResolveExecutableRuntimeAddress(uintptr_t address) {
    if (address == 0) {
        return 0;
    }

    auto& memory = sdmod::ProcessMemory::Instance();
    const auto resolved = memory.ResolveGameAddressOrZero(address);
    if (resolved != 0 && resolved != address && memory.IsExecutableRange(resolved, 1)) {
        return resolved;
    }

    if (memory.IsExecutableRange(address, 1)) {
        return address;
    }

    if (resolved != 0 && memory.IsExecutableRange(resolved, 1)) {
        return resolved;
    }

    if (memory.IsReadableRange(address, 1)) {
        return address;
    }

    return resolved != 0 ? resolved : address;
}

std::string MakeDefaultName(const char* prefix, uintptr_t address) {
    const auto base = prefix == nullptr ? std::string("runtime_debug") : std::string(prefix);
    return base + "_" + sdmod::HexString(address);
}

std::string NormalizeName(const char* name, const char* prefix, uintptr_t address) {
    if (name != nullptr && *name != '\0') {
        return std::string(name);
    }

    return MakeDefaultName(prefix, address);
}

void SetRuntimeDebugLastError(std::string message) {
    std::scoped_lock lock(g_runtime_debug_state.mutex);
    g_runtime_debug_state.last_error_message = std::move(message);
}

void ClearRuntimeDebugLastError() {
    SetRuntimeDebugLastError("");
}

std::string GetRuntimeDebugLastError() {
    std::scoped_lock lock(g_runtime_debug_state.mutex);
    return g_runtime_debug_state.last_error_message;
}

std::string FormatBytes(const std::uint8_t* bytes, size_t size) {
    if (bytes == nullptr || size == 0) {
        return "<empty>";
    }

    std::ostringstream out;
    out << std::uppercase << std::hex << std::setfill('0');
    const auto count = (std::min)(size, kMaxLoggedBytes);
    for (size_t index = 0; index < count; ++index) {
        if (index != 0) {
            out << ' ';
        }
        out << std::setw(2) << static_cast<unsigned int>(bytes[index]);
    }
    if (count < size) {
        out << " ... (" << std::dec << size << " bytes)";
    }

    return out.str();
}

std::string FormatBytes(const std::vector<std::uint8_t>& bytes) {
    return FormatBytes(bytes.data(), bytes.size());
}

bool TryAddRuntimeOffset(uintptr_t base_address, size_t offset, uintptr_t* result) {
    if (result == nullptr) {
        return false;
    }

    if (offset > static_cast<size_t>((std::numeric_limits<uintptr_t>::max)() - base_address)) {
        return false;
    }

    *result = base_address + offset;
    return true;
}

size_t GetSystemPageSize() {
    static const size_t page_size = []() -> size_t {
        SYSTEM_INFO info = {};
        GetSystemInfo(&info);
        return info.dwPageSize == 0 ? 4096u : static_cast<size_t>(info.dwPageSize);
    }();
    return page_size;
}

uintptr_t AlignToPageBase(uintptr_t address) {
    const auto page_size = static_cast<uintptr_t>(GetSystemPageSize());
    return address & ~(page_size - 1u);
}

bool TryQueryPageProtection(uintptr_t address, DWORD* protect) {
    if (protect == nullptr || address == 0) {
        return false;
    }

    MEMORY_BASIC_INFORMATION info = {};
    if (VirtualQuery(reinterpret_cast<void*>(address), &info, sizeof(info)) != sizeof(info)) {
        return false;
    }

    auto base_protect = info.Protect & ~(PAGE_GUARD | PAGE_NOCACHE | PAGE_WRITECOMBINE);
    if (base_protect == 0) {
        return false;
    }

    *protect = base_protect;
    return true;
}

bool TryQueryMemoryInfo(uintptr_t address, MEMORY_BASIC_INFORMATION* info) {
    if (info == nullptr || address == 0) {
        return false;
    }

    std::memset(info, 0, sizeof(*info));
    return VirtualQuery(reinterpret_cast<void*>(address), info, sizeof(*info)) == sizeof(*info);
}

bool IsExecutableProtection(DWORD protect) {
    const auto base_protect = protect & ~(PAGE_GUARD | PAGE_NOCACHE | PAGE_WRITECOMBINE);
    switch (base_protect) {
    case PAGE_EXECUTE:
    case PAGE_EXECUTE_READ:
    case PAGE_EXECUTE_READWRITE:
    case PAGE_EXECUTE_WRITECOPY:
        return true;
    default:
        return false;
    }
}

bool TrySetPageProtection(uintptr_t page_base, DWORD protect) {
    DWORD previous = 0;
    return VirtualProtect(
               reinterpret_cast<void*>(page_base),
               GetSystemPageSize(),
               protect,
               &previous) != FALSE;
}

bool TryReadStackWords(uintptr_t esp, std::uint32_t* stack_words, size_t word_count) {
    if (stack_words == nullptr || word_count == 0 || esp == 0) {
        return false;
    }

    return sdmod::ProcessMemory::Instance().TryRead(
        esp,
        reinterpret_cast<std::uint8_t*>(stack_words),
        word_count * sizeof(std::uint32_t));
}

bool LooksLikeExistingJumpPatch(uintptr_t address, size_t patch_size) {
    if (address == 0 || patch_size < 7) {
        return false;
    }

    std::uint8_t bytes[16] = {};
    if (!sdmod::ProcessMemory::Instance().TryRead(address, bytes, patch_size)) {
        return false;
    }

    if (bytes[0] != 0xE9) {
        return false;
    }

    for (size_t index = 5; index < patch_size; ++index) {
        if (bytes[index] != 0x90) {
            return false;
        }
    }

    return true;
}

size_t ResolveInstructionBoundaryPatchSize(uintptr_t address, size_t minimum_size, std::string* error_message) {
    if (address == 0 || minimum_size < 5) {
        if (error_message != nullptr) {
            *error_message = "invalid trace patch-size request";
        }
        return 0;
    }

    auto& memory = sdmod::ProcessMemory::Instance();
    size_t total_size = 0;
    while (total_size < minimum_size) {
        std::uint8_t buffer[16] = {};
        const auto instruction_address = address + total_size;
        if (!memory.TryRead(instruction_address, buffer, sizeof(buffer))) {
            if (error_message != nullptr) {
                *error_message =
                    "unable to read instruction bytes at " + sdmod::HexString(instruction_address);
            }
            return 0;
        }

        hde32s hs = {};
        const auto length = static_cast<size_t>(hde32_disasm(buffer, &hs));
        if (length == 0 || (hs.flags & F_ERROR) != 0) {
            if (error_message != nullptr) {
                *error_message =
                    "instruction decode failed at " + sdmod::HexString(instruction_address) +
                    " flags=" + sdmod::HexString(hs.flags);
            }
            return 0;
        }

        if ((hs.flags & F_RELATIVE) != 0) {
            if (error_message != nullptr) {
                *error_message =
                    "relative control-flow instruction in trace prologue at " +
                    sdmod::HexString(instruction_address) +
                    "; the current trace stub cannot relocate relative branches/calls";
            }
            return 0;
        }

        total_size += length;
        if (total_size > 16) {
            if (error_message != nullptr) {
                *error_message = "trace patch would exceed the 16-byte hook buffer";
            }
            return 0;
        }
    }

    return total_size;
}

void AppendTracePointerInfo(std::ostringstream* out, const char* label, uintptr_t value) {
    if (out == nullptr || label == nullptr) {
        return;
    }

    *out << ' ' << label << '=' << sdmod::HexString(value);
    if (value == 0) {
        return;
    }

    uintptr_t pointee = 0;
    if (sdmod::ProcessMemory::Instance().TryReadValue(value, &pointee)) {
        *out << ' ' << label << "_deref=" << sdmod::HexString(pointee);
    }
}

}  // namespace sdmod::detail::runtime_debug
