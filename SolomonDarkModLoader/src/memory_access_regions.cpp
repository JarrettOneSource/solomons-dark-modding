#include "memory_access.h"

#include <limits>

namespace sdmod {
namespace {

bool TryAdvanceAddress(uintptr_t current, size_t advance, uintptr_t* next) {
    if (next == nullptr) {
        return false;
    }

    if (advance > static_cast<size_t>((std::numeric_limits<uintptr_t>::max)() - current)) {
        return false;
    }

    *next = current + advance;
    return true;
}

}  // namespace

bool ProcessMemory::HasReadableProtection(DWORD protection) {
    protection &= 0xffu;
    switch (protection) {
    case PAGE_READONLY:
    case PAGE_READWRITE:
    case PAGE_WRITECOPY:
    case PAGE_EXECUTE_READ:
    case PAGE_EXECUTE_READWRITE:
    case PAGE_EXECUTE_WRITECOPY:
        return true;
    default:
        return false;
    }
}

bool ProcessMemory::HasWritableProtection(DWORD protection) {
    protection &= 0xffu;
    switch (protection) {
    case PAGE_READWRITE:
    case PAGE_WRITECOPY:
    case PAGE_EXECUTE_READWRITE:
    case PAGE_EXECUTE_WRITECOPY:
        return true;
    default:
        return false;
    }
}

bool ProcessMemory::HasExecutableProtection(DWORD protection) {
    protection &= 0xffu;
    switch (protection) {
    case PAGE_EXECUTE:
    case PAGE_EXECUTE_READ:
    case PAGE_EXECUTE_READWRITE:
    case PAGE_EXECUTE_WRITECOPY:
        return true;
    default:
        return false;
    }
}

bool ProcessMemory::QueryRegion(uintptr_t address, MemoryRegionInfo* region) const {
    if (address == 0 || region == nullptr) {
        return false;
    }

    MEMORY_BASIC_INFORMATION memory_info{};
    const auto query_size = VirtualQuery(reinterpret_cast<LPCVOID>(address), &memory_info, sizeof(memory_info));
    if (query_size != sizeof(memory_info)) {
        return false;
    }

    MemoryRegionInfo resolved{};
    resolved.base = reinterpret_cast<uintptr_t>(memory_info.BaseAddress);
    resolved.end = resolved.base;
    if (!TryAdvanceAddress(resolved.base, memory_info.RegionSize, &resolved.end)) {
        resolved.end = (std::numeric_limits<uintptr_t>::max)();
    }
    resolved.state = memory_info.State;
    resolved.protect = memory_info.Protect;
    resolved.type = memory_info.Type;
    resolved.committed = memory_info.State == MEM_COMMIT;
    resolved.guarded = (memory_info.Protect & PAGE_GUARD) != 0;
    resolved.no_access = (memory_info.Protect & PAGE_NOACCESS) != 0;
    resolved.readable = HasReadableProtection(memory_info.Protect);
    resolved.writable = HasWritableProtection(memory_info.Protect);
    resolved.executable = HasExecutableProtection(memory_info.Protect);

    *region = resolved;
    return true;
}

bool ProcessMemory::ResolveRegion(uintptr_t address, MemoryRegionInfo* region) {
    if (address == 0 || region == nullptr) {
        return false;
    }

    {
        std::shared_lock lock(region_cache_mutex_);
        auto it = region_cache_.upper_bound(address);
        if (it != region_cache_.begin()) {
            --it;
            if (address >= it->second.base && address < it->second.end) {
                *region = it->second;
                return true;
            }
        }
    }

    return RefreshRegion(address, region);
}

bool ProcessMemory::RefreshRegion(uintptr_t address, MemoryRegionInfo* region) {
    MemoryRegionInfo refreshed{};
    if (!QueryRegion(address, &refreshed)) {
        return false;
    }

    {
        std::unique_lock lock(region_cache_mutex_);
        region_cache_[refreshed.base] = refreshed;
    }

    if (region != nullptr) {
        *region = refreshed;
    }
    return true;
}

void ProcessMemory::InvalidateRegion(uintptr_t address) {
    if (address == 0) {
        return;
    }

    std::unique_lock lock(region_cache_mutex_);
    auto it = region_cache_.upper_bound(address);
    if (it == region_cache_.begin()) {
        return;
    }

    --it;
    if (address >= it->second.base && address < it->second.end) {
        region_cache_.erase(it);
    }
}

void ProcessMemory::InvalidateRange(uintptr_t address, size_t size) {
    if (address == 0 || size == 0) {
        return;
    }

    uintptr_t end = address;
    if (!TryAdvanceAddress(address, size, &end)) {
        end = (std::numeric_limits<uintptr_t>::max)();
    }

    std::unique_lock lock(region_cache_mutex_);
    for (auto it = region_cache_.begin(); it != region_cache_.end();) {
        if (it->second.end > address && it->second.base < end) {
            it = region_cache_.erase(it);
            continue;
        }

        ++it;
    }
}

bool ProcessMemory::IsRangeAccessible(uintptr_t address, size_t size, bool require_write) {
    if (address == 0 || size == 0) {
        return false;
    }

    auto current = address;
    auto remaining = size;
    while (remaining > 0) {
        MemoryRegionInfo region{};
        if (!ResolveRegion(current, &region)) {
            return false;
        }

        if (!region.committed || region.guarded || region.no_access) {
            return false;
        }

        if (require_write) {
            if (!region.writable) {
                return false;
            }
        } else if (!region.readable) {
            return false;
        }

        if (current < region.base || current >= region.end) {
            return false;
        }

        const auto available = static_cast<size_t>(region.end - current);
        if (available >= remaining) {
            return true;
        }

        remaining -= available;
        current = region.end;
    }

    return true;
}

bool ProcessMemory::IsReadableRange(uintptr_t address, size_t size) {
    return IsRangeAccessible(address, size, false);
}

bool ProcessMemory::IsWritableRange(uintptr_t address, size_t size) {
    return IsRangeAccessible(address, size, true);
}

}  // namespace sdmod
