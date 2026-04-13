#pragma once

#include <Windows.h>

#include <atomic>
#include <cstddef>
#include <cstdint>
#include <map>
#include <shared_mutex>
#include <string>

namespace sdmod {

struct MemoryRegionInfo {
    uintptr_t base = 0;
    uintptr_t end = 0;
    DWORD state = 0;
    DWORD protect = 0;
    DWORD type = 0;
    bool committed = false;
    bool guarded = false;
    bool no_access = false;
    bool readable = false;
    bool writable = false;
    bool executable = false;
};

class ProcessMemory final {
public:
    static ProcessMemory& Instance();

    uintptr_t ModuleBase() const;
    bool TryResolveGameAddress(uintptr_t absolute_address, uintptr_t* resolved_address) const;
    uintptr_t ResolveGameAddressOrZero(uintptr_t absolute_address) const;

    bool IsReadableRange(uintptr_t address, size_t size);
    bool IsWritableRange(uintptr_t address, size_t size);
    bool IsExecutableRange(uintptr_t address, size_t size);

    bool TryRead(uintptr_t address, void* buffer, size_t size);
    bool TryWrite(uintptr_t address, const void* buffer, size_t size);

    template <typename T>
    bool TryReadValue(uintptr_t address, T* value) {
        return value != nullptr && TryRead(address, value, sizeof(T));
    }

    template <typename T>
    T ReadValueOr(uintptr_t address, T fallback = T{}) {
        T value = fallback;
        if (!TryReadValue(address, &value)) {
            return fallback;
        }

        return value;
    }

    template <typename T>
    bool TryWriteValue(uintptr_t address, const T& value) {
        return TryWrite(address, &value, sizeof(T));
    }

    template <typename T>
    bool TryReadField(uintptr_t base_address, size_t offset, T* value) {
        if (base_address == 0) {
            return false;
        }

        return TryReadValue(base_address + offset, value);
    }

    template <typename T>
    T ReadFieldOr(uintptr_t base_address, size_t offset, T fallback = T{}) {
        if (base_address == 0) {
            return fallback;
        }

        return ReadValueOr(base_address + offset, fallback);
    }

    template <typename T>
    bool TryWriteField(uintptr_t base_address, size_t offset, const T& value) {
        if (base_address == 0) {
            return false;
        }

        return TryWriteValue(base_address + offset, value);
    }

    bool TryReadCString(uintptr_t address, size_t max_length, std::string* value);
    bool RefreshRegion(uintptr_t address, MemoryRegionInfo* region = nullptr);
    void InvalidateRegion(uintptr_t address);
    void InvalidateRange(uintptr_t address, size_t size);

private:
    ProcessMemory() = default;

    bool ResolveRegion(uintptr_t address, MemoryRegionInfo* region);
    bool QueryRegion(uintptr_t address, MemoryRegionInfo* region) const;
    bool IsRangeAccessible(uintptr_t address, size_t size, bool require_write);

    static bool HasReadableProtection(DWORD protection);
    static bool HasWritableProtection(DWORD protection);
    static bool HasExecutableProtection(DWORD protection);

    mutable std::shared_mutex region_cache_mutex_;
    mutable std::map<uintptr_t, MemoryRegionInfo> region_cache_;
    mutable std::atomic<uintptr_t> module_base_{0};
};

}  // namespace sdmod
