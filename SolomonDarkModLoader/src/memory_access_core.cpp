#include "binary_layout.h"
#include "memory_access.h"

namespace sdmod {

ProcessMemory& ProcessMemory::Instance() {
    static ProcessMemory instance;
    return instance;
}

uintptr_t ProcessMemory::ModuleBase() const {
    auto cached = module_base_.load(std::memory_order_relaxed);
    if (cached != 0) {
        return cached;
    }

    cached = reinterpret_cast<uintptr_t>(GetModuleHandleW(nullptr));
    module_base_.store(cached, std::memory_order_relaxed);
    return cached;
}

bool ProcessMemory::TryResolveGameAddress(uintptr_t absolute_address, uintptr_t* resolved_address) const {
    const auto image_base = GetConfiguredImageBase();
    if (resolved_address == nullptr || image_base == 0 || absolute_address < image_base) {
        return false;
    }

    const auto module_base = ModuleBase();
    if (module_base == 0) {
        return false;
    }

    *resolved_address = module_base + (absolute_address - image_base);
    return true;
}

uintptr_t ProcessMemory::ResolveGameAddressOrZero(uintptr_t absolute_address) const {
    uintptr_t resolved = 0;
    return TryResolveGameAddress(absolute_address, &resolved) ? resolved : 0;
}

}  // namespace sdmod
