#include "runtime_debug_internal.h"

extern "C" void RuntimeDebug_WatchMemory(uintptr_t address, size_t size, const char* name) {
    namespace rt = sdmod::detail::runtime_debug;

    const auto resolved_address = rt::ResolveRuntimeAddress(address);
    if (resolved_address == 0 || size == 0) {
        sdmod::Log("WATCH: failed to arm direct watch at " + sdmod::HexString(address));
        return;
    }

    rt::MemoryWatch watch;
    watch.kind = rt::WatchKind::Direct;
    watch.requested_address = address;
    watch.resolved_address = resolved_address;
    watch.size = size;
    watch.name = rt::NormalizeName(name, "watch", address);

    const rt::MemoryWatch watch_to_log = watch;
    bool replaced_existing = false;
    {
        std::scoped_lock lock(rt::g_runtime_debug_state.mutex);
        const auto duplicate = std::find_if(
            rt::g_runtime_debug_state.watches.begin(),
            rt::g_runtime_debug_state.watches.end(),
            [&](const rt::MemoryWatch& existing) { return rt::SameWatchDefinition(existing, watch); });
        if (duplicate != rt::g_runtime_debug_state.watches.end()) {
            return;
        }

        rt::RemoveNamedWatches(&rt::g_runtime_debug_state.watches, watch.name, &replaced_existing);
        rt::g_runtime_debug_state.watches.push_back(std::move(watch));
    }

    if (replaced_existing) {
        sdmod::Log("WATCH: replaced " + watch_to_log.name);
    }
    rt::LogWatchRegistered(watch_to_log);
}

extern "C" void RuntimeDebug_WatchPtrField(uintptr_t ptr_address, size_t offset, size_t size, const char* name) {
    namespace rt = sdmod::detail::runtime_debug;

    const auto resolved_ptr_address = rt::ResolveRuntimeAddress(ptr_address);
    if (resolved_ptr_address == 0 || size == 0) {
        sdmod::Log("WATCH: failed to arm ptr-field watch at " + sdmod::HexString(ptr_address));
        return;
    }

    rt::MemoryWatch watch;
    watch.kind = rt::WatchKind::PtrField;
    watch.requested_address = ptr_address;
    watch.resolved_address = resolved_ptr_address;
    watch.offset = offset;
    watch.size = size;
    watch.name = rt::NormalizeName(name, "watch_ptr", ptr_address);

    const rt::MemoryWatch watch_to_log = watch;
    bool replaced_existing = false;
    {
        std::scoped_lock lock(rt::g_runtime_debug_state.mutex);
        const auto duplicate = std::find_if(
            rt::g_runtime_debug_state.watches.begin(),
            rt::g_runtime_debug_state.watches.end(),
            [&](const rt::MemoryWatch& existing) { return rt::SameWatchDefinition(existing, watch); });
        if (duplicate != rt::g_runtime_debug_state.watches.end()) {
            return;
        }

        rt::RemoveNamedWatches(&rt::g_runtime_debug_state.watches, watch.name, &replaced_existing);
        rt::g_runtime_debug_state.watches.push_back(std::move(watch));
    }

    if (replaced_existing) {
        sdmod::Log("WATCH: replaced " + watch_to_log.name);
    }
    rt::LogWatchRegistered(watch_to_log);
}

extern "C" bool RuntimeDebug_WatchWriteMemory(uintptr_t address, size_t size, const char* name) {
    namespace rt = sdmod::detail::runtime_debug;

    const auto resolved_address = rt::ResolveRuntimeAddress(address);
    if (resolved_address == 0 || size == 0) {
        sdmod::Log("WRITE WATCH: failed to arm direct watch at " + sdmod::HexString(address));
        return false;
    }

    rt::WriteWatch watch;
    watch.kind = rt::WatchKind::Direct;
    watch.requested_address = address;
    watch.resolved_address = resolved_address;
    watch.value_address = resolved_address;
    watch.size = size;
    watch.name = rt::NormalizeName(name, "watch_write", address);

    uintptr_t start_address = 0;
    uintptr_t end_address = 0;
    if (!rt::ResolveWriteWatchTarget(watch, &start_address, &end_address)) {
        sdmod::Log("WRITE WATCH: failed to resolve direct watch range at " + sdmod::HexString(address));
        return false;
    }

    const auto start_page = rt::AlignToPageBase(start_address);
    const auto end_page = rt::AlignToPageBase(end_address - 1);
    for (auto page = start_page; page <= end_page; page += rt::GetSystemPageSize()) {
        watch.page_bases.push_back(page);
    }

    const auto watch_to_log = watch;
    bool replaced_existing = false;
    std::vector<rt::GuardedPageState> pages_to_restore;
    {
        std::scoped_lock lock(rt::g_runtime_debug_state.mutex);
        const auto duplicate = std::find_if(
            rt::g_runtime_debug_state.write_watches.begin(),
            rt::g_runtime_debug_state.write_watches.end(),
            [&](const rt::WriteWatch& existing) { return rt::SameWriteWatchDefinition(existing, watch); });
        if (duplicate != rt::g_runtime_debug_state.write_watches.end()) {
            return true;
        }

        rt::RemoveNamedWriteWatchesAndCollectPages(
            &rt::g_runtime_debug_state.write_watches,
            &rt::g_runtime_debug_state.guarded_pages,
            watch.name,
            &replaced_existing,
            &pages_to_restore);

        for (const auto& page : pages_to_restore) {
            (void)rt::TrySetPageProtection(page.page_base, page.base_protect);
        }
        pages_to_restore.clear();

        if (rt::g_runtime_debug_state.write_watch_handler == nullptr) {
            rt::g_runtime_debug_state.write_watch_handler =
                AddVectoredExceptionHandler(1, &rt::RuntimeDebug_WriteWatchExceptionHandler);
            if (rt::g_runtime_debug_state.write_watch_handler == nullptr) {
                sdmod::Log("WRITE WATCH: failed to install vectored exception handler.");
                return false;
            }
        }

        for (const auto page_base : watch.page_bases) {
            auto page_it = rt::g_runtime_debug_state.guarded_pages.find(page_base);
            if (page_it == rt::g_runtime_debug_state.guarded_pages.end()) {
                rt::GuardedPageState state;
                state.page_base = page_base;
                if (!rt::TryQueryPageProtection(page_base, &state.base_protect) ||
                    !rt::TrySetPageProtection(page_base, state.base_protect | PAGE_GUARD)) {
                    sdmod::Log(
                        "WRITE WATCH: failed to guard page " + sdmod::HexString(page_base) +
                        " for " + watch.name);
                    return false;
                }
                state.ref_count = 1;
                rt::g_runtime_debug_state.guarded_pages.emplace(page_base, state);
            } else {
                ++page_it->second.ref_count;
            }
        }

        rt::g_runtime_debug_state.write_watches.push_back(std::move(watch));
    }

    if (replaced_existing) {
        sdmod::Log("WRITE WATCH: replaced " + watch_to_log.name);
    }
    rt::LogWriteWatchRegistered(watch_to_log);
    return true;
}

extern "C" bool RuntimeDebug_WatchWritePtrField(uintptr_t ptr_address, size_t offset, size_t size, const char* name) {
    namespace rt = sdmod::detail::runtime_debug;

    const auto resolved_ptr_address = rt::ResolveRuntimeAddress(ptr_address);
    if (resolved_ptr_address == 0 || size == 0) {
        sdmod::Log("WRITE WATCH: failed to arm ptr-field watch at " + sdmod::HexString(ptr_address));
        return false;
    }

    uintptr_t base_address = 0;
    if (!sdmod::ProcessMemory::Instance().TryReadValue(resolved_ptr_address, &base_address) || base_address == 0) {
        sdmod::Log("WRITE WATCH: failed to resolve ptr-field base at " + sdmod::HexString(ptr_address));
        return false;
    }

    uintptr_t value_address = 0;
    if (!rt::TryAddRuntimeOffset(base_address, offset, &value_address)) {
        sdmod::Log("WRITE WATCH: ptr-field offset overflow at " + sdmod::HexString(ptr_address));
        return false;
    }

    rt::WriteWatch watch;
    watch.kind = rt::WatchKind::PtrField;
    watch.requested_address = ptr_address;
    watch.resolved_address = resolved_ptr_address;
    watch.base_address = base_address;
    watch.value_address = value_address;
    watch.offset = offset;
    watch.size = size;
    watch.name = rt::NormalizeName(name, "watch_write_ptr", ptr_address);

    uintptr_t start_address = 0;
    uintptr_t end_address = 0;
    if (!rt::ResolveWriteWatchTarget(watch, &start_address, &end_address)) {
        sdmod::Log("WRITE WATCH: failed to resolve ptr-field watch range at " + sdmod::HexString(ptr_address));
        return false;
    }

    const auto start_page = rt::AlignToPageBase(start_address);
    const auto end_page = rt::AlignToPageBase(end_address - 1);
    for (auto page = start_page; page <= end_page; page += rt::GetSystemPageSize()) {
        watch.page_bases.push_back(page);
    }

    const auto watch_to_log = watch;
    bool replaced_existing = false;
    std::vector<rt::GuardedPageState> pages_to_restore;
    {
        std::scoped_lock lock(rt::g_runtime_debug_state.mutex);
        const auto duplicate = std::find_if(
            rt::g_runtime_debug_state.write_watches.begin(),
            rt::g_runtime_debug_state.write_watches.end(),
            [&](const rt::WriteWatch& existing) { return rt::SameWriteWatchDefinition(existing, watch); });
        if (duplicate != rt::g_runtime_debug_state.write_watches.end()) {
            return true;
        }

        rt::RemoveNamedWriteWatchesAndCollectPages(
            &rt::g_runtime_debug_state.write_watches,
            &rt::g_runtime_debug_state.guarded_pages,
            watch.name,
            &replaced_existing,
            &pages_to_restore);

        for (const auto& page : pages_to_restore) {
            (void)rt::TrySetPageProtection(page.page_base, page.base_protect);
        }
        pages_to_restore.clear();

        if (rt::g_runtime_debug_state.write_watch_handler == nullptr) {
            rt::g_runtime_debug_state.write_watch_handler =
                AddVectoredExceptionHandler(1, &rt::RuntimeDebug_WriteWatchExceptionHandler);
            if (rt::g_runtime_debug_state.write_watch_handler == nullptr) {
                sdmod::Log("WRITE WATCH: failed to install vectored exception handler.");
                return false;
            }
        }

        for (const auto page_base : watch.page_bases) {
            auto page_it = rt::g_runtime_debug_state.guarded_pages.find(page_base);
            if (page_it == rt::g_runtime_debug_state.guarded_pages.end()) {
                rt::GuardedPageState state;
                state.page_base = page_base;
                if (!rt::TryQueryPageProtection(page_base, &state.base_protect) ||
                    !rt::TrySetPageProtection(page_base, state.base_protect | PAGE_GUARD)) {
                    sdmod::Log(
                        "WRITE WATCH: failed to guard page " + sdmod::HexString(page_base) +
                        " for " + watch.name);
                    return false;
                }
                state.ref_count = 1;
                rt::g_runtime_debug_state.guarded_pages.emplace(page_base, state);
            } else {
                ++page_it->second.ref_count;
            }
        }

        rt::g_runtime_debug_state.write_watches.push_back(std::move(watch));
    }

    if (replaced_existing) {
        sdmod::Log("WRITE WATCH: replaced " + watch_to_log.name);
    }
    rt::LogWriteWatchRegistered(watch_to_log);
    return true;
}
