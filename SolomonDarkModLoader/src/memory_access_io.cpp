#include "memory_access.h"

#include <cstring>

namespace sdmod {

bool ProcessMemory::TryRead(uintptr_t address, void* buffer, size_t size) {
    if (buffer == nullptr || size == 0 || !IsReadableRange(address, size)) {
        return false;
    }

    __try {
        std::memcpy(buffer, reinterpret_cast<const void*>(address), size);
        return true;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        InvalidateRange(address, size);
        return false;
    }
}

bool ProcessMemory::TryWrite(uintptr_t address, const void* buffer, size_t size) {
    if (buffer == nullptr || size == 0 || address == 0) {
        return false;
    }

    auto protection_changed = false;
    DWORD previous_protect = 0;
    if (!IsWritableRange(address, size)) {
        if (!VirtualProtect(reinterpret_cast<void*>(address), size, PAGE_EXECUTE_READWRITE, &previous_protect)) {
            return false;
        }
        protection_changed = true;
    }

    auto success = false;
    __try {
        std::memcpy(reinterpret_cast<void*>(address), buffer, size);
        success = true;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        success = false;
    }

    if (protection_changed) {
        DWORD restored_protect = 0;
        VirtualProtect(reinterpret_cast<void*>(address), size, previous_protect, &restored_protect);
    }

    if (!success) {
        InvalidateRange(address, size);
        return false;
    }

    FlushInstructionCache(GetCurrentProcess(), reinterpret_cast<const void*>(address), size);
    InvalidateRange(address, size);
    return true;
}

bool ProcessMemory::TryReadCString(uintptr_t address, size_t max_length, std::string* value) {
    if (value == nullptr || max_length == 0) {
        return false;
    }

    value->clear();
    for (size_t offset = 0; offset < max_length; ++offset) {
        char character = '\0';
        if (!TryReadValue(address + offset, &character)) {
            return false;
        }

        if (character == '\0') {
            return true;
        }

        value->push_back(character);
    }

    return true;
}

}  // namespace sdmod
