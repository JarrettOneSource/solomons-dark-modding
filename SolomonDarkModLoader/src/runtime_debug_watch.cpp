#include "runtime_debug_internal.h"

namespace sdmod::detail::runtime_debug {

void LogWatchRegistered(const MemoryWatch& watch) {
    if (watch.kind == WatchKind::Direct) {
        sdmod::Log(
            "WATCH: armed " + watch.name + " addr=" + sdmod::HexString(watch.requested_address) +
            " size=" + std::to_string(watch.size));
        return;
    }

    sdmod::Log(
        "WATCH: armed " + watch.name + " ptr=" + sdmod::HexString(watch.requested_address) +
        " offset=" + sdmod::HexString(static_cast<uintptr_t>(watch.offset)) +
        " size=" + std::to_string(watch.size));
}

bool ReadWatchValue(
    const MemoryWatch& watch,
    uintptr_t* base_address,
    uintptr_t* value_address,
    std::vector<std::uint8_t>* bytes) {
    if (base_address == nullptr || value_address == nullptr || bytes == nullptr) {
        return false;
    }

    bytes->assign(watch.size, 0);
    *base_address = 0;
    *value_address = 0;

    if (watch.kind == WatchKind::Direct) {
        *value_address = watch.resolved_address;
        return sdmod::ProcessMemory::Instance().TryRead(
            watch.resolved_address,
            bytes->data(),
            bytes->size());
    }

    uintptr_t object_address = 0;
    if (!sdmod::ProcessMemory::Instance().TryReadValue(watch.resolved_address, &object_address) || object_address == 0) {
        return false;
    }

    uintptr_t field_address = 0;
    if (!TryAddRuntimeOffset(object_address, watch.offset, &field_address)) {
        return false;
    }

    *base_address = object_address;
    *value_address = field_address;
    return sdmod::ProcessMemory::Instance().TryRead(*value_address, bytes->data(), bytes->size());
}

bool SameWatchDefinition(const MemoryWatch& lhs, const MemoryWatch& rhs) {
    return lhs.kind == rhs.kind &&
        lhs.requested_address == rhs.requested_address &&
        lhs.resolved_address == rhs.resolved_address &&
        lhs.offset == rhs.offset &&
        lhs.size == rhs.size &&
        lhs.name == rhs.name;
}

void RemoveNamedWatches(std::vector<MemoryWatch>* watches, const std::string& name, bool* removed_any) {
    if (watches == nullptr) {
        return;
    }

    const auto new_end = std::remove_if(
        watches->begin(),
        watches->end(),
        [&](const MemoryWatch& watch) { return watch.name == name; });
    const auto removed = new_end != watches->end();
    watches->erase(new_end, watches->end());
    if (removed_any != nullptr) {
        *removed_any = removed;
    }
}

bool SameWriteWatchDefinition(const WriteWatch& lhs, const WriteWatch& rhs) {
    return lhs.kind == rhs.kind &&
        lhs.requested_address == rhs.requested_address &&
        lhs.resolved_address == rhs.resolved_address &&
        lhs.base_address == rhs.base_address &&
        lhs.value_address == rhs.value_address &&
        lhs.offset == rhs.offset &&
        lhs.size == rhs.size &&
        lhs.name == rhs.name;
}

bool ResolveWriteWatchTarget(const WriteWatch& watch, uintptr_t* start_address, uintptr_t* end_address) {
    if (start_address == nullptr || end_address == nullptr) {
        return false;
    }

    uintptr_t resolved_start = 0;
    switch (watch.kind) {
    case WatchKind::Direct:
        resolved_start = watch.resolved_address;
        break;
    case WatchKind::PtrField:
        resolved_start = watch.value_address;
        break;
    default:
        return false;
    }

    if (resolved_start == 0 || watch.size == 0) {
        return false;
    }

    if (watch.size - 1 > static_cast<size_t>((std::numeric_limits<uintptr_t>::max)() - resolved_start)) {
        return false;
    }

    *start_address = resolved_start;
    *end_address = resolved_start + watch.size;
    return true;
}

void RemoveNamedWriteWatchesAndCollectPages(
    std::vector<WriteWatch>* watches,
    std::unordered_map<uintptr_t, GuardedPageState>* guarded_pages,
    const std::string& name,
    bool* removed_any,
    std::vector<GuardedPageState>* pages_to_restore) {
    if (watches == nullptr || guarded_pages == nullptr) {
        return;
    }

    auto removed = false;
    auto it = watches->begin();
    while (it != watches->end()) {
        if (it->name != name) {
            ++it;
            continue;
        }

        removed = true;
        for (const auto page_base : it->page_bases) {
            auto page_it = guarded_pages->find(page_base);
            if (page_it == guarded_pages->end()) {
                continue;
            }
            if (page_it->second.ref_count > 0) {
                --page_it->second.ref_count;
            }
            if (page_it->second.ref_count == 0) {
                if (pages_to_restore != nullptr) {
                    pages_to_restore->push_back(page_it->second);
                }
                guarded_pages->erase(page_it);
            }
        }

        it = watches->erase(it);
    }

    if (removed_any != nullptr) {
        *removed_any = removed;
    }
}

void LogWriteWatchRegistered(const WriteWatch& watch) {
    if (watch.kind == WatchKind::PtrField) {
        sdmod::Log(
            "WRITE WATCH: armed " + watch.name +
            " ptr=" + sdmod::HexString(watch.requested_address) +
            " base=" + sdmod::HexString(watch.base_address) +
            " field=" + sdmod::HexString(watch.value_address) +
            " offset=" + sdmod::HexString(static_cast<uintptr_t>(watch.offset)) +
            " size=" + std::to_string(watch.size));
        return;
    }

    sdmod::Log(
        "WRITE WATCH: armed " + watch.name +
        " addr=" + sdmod::HexString(watch.requested_address) +
        " size=" + std::to_string(watch.size));
}

void LogWriteWatchHit(const PendingWriteHit& hit, const std::vector<std::uint8_t>& after_bytes) {
    {
        RuntimeDebugWriteHitInfo record;
        record.name = hit.name;
        record.requested_address = hit.requested_address;
        record.resolved_address = hit.resolved_address;
        record.base_address = hit.base_address;
        record.value_address = hit.value_address;
        record.access_address = hit.access_address;
        record.offset = hit.offset;
        record.size = hit.size;
        record.is_ptr_field = hit.kind == WatchKind::PtrField;
        record.thread_id = hit.thread_id;
        record.eip = hit.eip;
        record.esp = hit.esp;
        record.ebp = hit.ebp;
        record.eax = hit.eax;
        record.ecx = hit.ecx;
        record.edx = hit.edx;
        record.ret = hit.ret;
        record.arg0 = hit.arg0;
        record.arg1 = hit.arg1;
        record.arg2 = hit.arg2;
        record.before_bytes_hex = FormatBytes(hit.before_bytes);
        record.after_bytes_hex = FormatBytes(after_bytes);
        std::scoped_lock lock(g_runtime_debug_state.mutex);
        g_runtime_debug_state.write_hits.push_back(std::move(record));
        if (g_runtime_debug_state.write_hits.size() > kMaxStoredWriteHits) {
            g_runtime_debug_state.write_hits.erase(g_runtime_debug_state.write_hits.begin());
        }
    }

    std::ostringstream out;
    out <<
        "WRITE WATCH: " << hit.name <<
        " thread=" << std::dec << hit.thread_id <<
        (hit.kind == WatchKind::PtrField ? " ptr=" : " addr=") << sdmod::HexString(hit.requested_address) <<
        (hit.kind == WatchKind::PtrField ? " base=" : " runtime=") <<
            sdmod::HexString(hit.kind == WatchKind::PtrField ? hit.base_address : hit.resolved_address) <<
        (hit.kind == WatchKind::PtrField ? " field=" : "") <<
            (hit.kind == WatchKind::PtrField ? sdmod::HexString(hit.value_address) : std::string()) <<
        " access=" << sdmod::HexString(hit.access_address) <<
        " size=" << std::dec << hit.size <<
        " old=" << FormatBytes(hit.before_bytes) <<
        " new=" << FormatBytes(after_bytes) <<
        " eip=" << sdmod::HexString(hit.eip) <<
        " esp=" << sdmod::HexString(hit.esp) <<
        " ebp=" << sdmod::HexString(hit.ebp) <<
        " eax=" << sdmod::HexString(hit.eax) <<
        " ret=" << sdmod::HexString(hit.ret) <<
        " arg0=" << sdmod::HexString(hit.arg0) <<
        " arg1=" << sdmod::HexString(hit.arg1) <<
        " arg2=" << sdmod::HexString(hit.arg2);
    AppendTracePointerInfo(&out, "ecx", hit.ecx);
    AppendTracePointerInfo(&out, "edx", hit.edx);
    AppendTracePointerInfo(&out, "arg0", hit.arg0);
    sdmod::Log(out.str());
}

LONG CALLBACK RuntimeDebug_WriteWatchExceptionHandler(EXCEPTION_POINTERS* exception_pointers) {
    if (exception_pointers == nullptr ||
        exception_pointers->ExceptionRecord == nullptr ||
        exception_pointers->ContextRecord == nullptr) {
        return EXCEPTION_CONTINUE_SEARCH;
    }

    const auto code = exception_pointers->ExceptionRecord->ExceptionCode;
    auto* const context = exception_pointers->ContextRecord;
    if (code == STATUS_GUARD_PAGE_VIOLATION) {
        if (exception_pointers->ExceptionRecord->NumberParameters < 2) {
            return EXCEPTION_CONTINUE_SEARCH;
        }

        const auto access_type =
            static_cast<uintptr_t>(exception_pointers->ExceptionRecord->ExceptionInformation[0]);
        const auto access_address =
            static_cast<uintptr_t>(exception_pointers->ExceptionRecord->ExceptionInformation[1]);
        const auto page_base = AlignToPageBase(access_address);
        const auto is_write = access_type == 1u;

        bool handled = false;
        std::vector<PendingWriteHit> hits;
        {
            std::scoped_lock lock(g_runtime_debug_state.mutex);
            auto page_it = g_runtime_debug_state.guarded_pages.find(page_base);
            if (page_it == g_runtime_debug_state.guarded_pages.end()) {
                return EXCEPTION_CONTINUE_SEARCH;
            }

            page_it->second.pending_rearm = true;
            handled = true;

            if (is_write) {
                std::uint32_t stack_words[4] = {};
                (void)TryReadStackWords(context->Esp, stack_words, 4);
                for (const auto& watch : g_runtime_debug_state.write_watches) {
                    uintptr_t watch_start = 0;
                    uintptr_t watch_end = 0;
                    if (!ResolveWriteWatchTarget(watch, &watch_start, &watch_end) ||
                        access_address < watch_start ||
                        access_address >= watch_end) {
                        continue;
                    }

                    PendingWriteHit hit;
                    hit.thread_id = GetCurrentThreadId();
                    hit.kind = watch.kind;
                    hit.name = watch.name;
                    hit.requested_address = watch.requested_address;
                    hit.resolved_address = watch.resolved_address;
                    hit.base_address = watch.base_address;
                    hit.value_address = watch.value_address;
                    hit.offset = watch.offset;
                    hit.access_address = access_address;
                    hit.size = watch.size;
                    hit.eip = context->Eip;
                    hit.esp = context->Esp;
                    hit.ebp = context->Ebp;
                    hit.eax = context->Eax;
                    hit.ecx = context->Ecx;
                    hit.edx = context->Edx;
                    hit.ret = stack_words[0];
                    hit.arg0 = stack_words[1];
                    hit.arg1 = stack_words[2];
                    hit.arg2 = stack_words[3];
                    const auto bytes_to_capture = (std::min)(watch.size, kMaxLoggedBytes);
                    hit.before_bytes.assign(bytes_to_capture, 0);
                    (void)sdmod::ProcessMemory::Instance().TryRead(
                        watch.value_address != 0 ? watch.value_address : watch.resolved_address,
                        hit.before_bytes.data(),
                        hit.before_bytes.size());
                    hits.push_back(std::move(hit));
                }
            }

            for (auto& hit : hits) {
                g_runtime_debug_state.pending_write_hits.push_back(std::move(hit));
            }
        }

        if (handled) {
            context->EFlags |= kWriteWatchTrapFlag;
            return EXCEPTION_CONTINUE_EXECUTION;
        }
        return EXCEPTION_CONTINUE_SEARCH;
    }

    if (code == EXCEPTION_SINGLE_STEP) {
        const auto thread_id = GetCurrentThreadId();
        std::vector<GuardedPageState> pages_to_rearm;
        std::vector<PendingWriteHit> hits_to_log;
        {
            std::scoped_lock lock(g_runtime_debug_state.mutex);
            for (auto& [page_base, state] : g_runtime_debug_state.guarded_pages) {
                if (!state.pending_rearm) {
                    continue;
                }
                state.pending_rearm = false;
                pages_to_rearm.push_back(state);
            }

            auto pending_it = g_runtime_debug_state.pending_write_hits.begin();
            while (pending_it != g_runtime_debug_state.pending_write_hits.end()) {
                if (pending_it->thread_id == thread_id) {
                    hits_to_log.push_back(std::move(*pending_it));
                    pending_it = g_runtime_debug_state.pending_write_hits.erase(pending_it);
                } else {
                    ++pending_it;
                }
            }
        }

        if (pages_to_rearm.empty() && hits_to_log.empty()) {
            return EXCEPTION_CONTINUE_SEARCH;
        }

        for (const auto& page : pages_to_rearm) {
            (void)TrySetPageProtection(page.page_base, page.base_protect | PAGE_GUARD);
        }

        for (const auto& hit : hits_to_log) {
            std::vector<std::uint8_t> after_bytes((std::min)(hit.size, kMaxLoggedBytes), 0);
            (void)sdmod::ProcessMemory::Instance().TryRead(
                hit.value_address != 0 ? hit.value_address : hit.resolved_address,
                after_bytes.data(),
                after_bytes.size());
            LogWriteWatchHit(hit, after_bytes);
        }

        return EXCEPTION_CONTINUE_EXECUTION;
    }

    return EXCEPTION_CONTINUE_SEARCH;
}

}  // namespace sdmod::detail::runtime_debug

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

bool RuntimeDebug_UnwatchMemoryByName(const char* name) {
    namespace rt = sdmod::detail::runtime_debug;

    if (name == nullptr || *name == '\0') {
        return false;
    }

    const std::string watch_name(name);
    auto removed = false;
    std::vector<rt::GuardedPageState> pages_to_restore;
    auto remove_write_handler = false;
    {
        std::scoped_lock lock(rt::g_runtime_debug_state.mutex);
        rt::RemoveNamedWatches(&rt::g_runtime_debug_state.watches, watch_name, &removed);
        auto write_it = rt::g_runtime_debug_state.write_watches.begin();
        while (write_it != rt::g_runtime_debug_state.write_watches.end()) {
            if (write_it->name != watch_name) {
                ++write_it;
                continue;
            }

            removed = true;
            for (const auto page_base : write_it->page_bases) {
                auto page_it = rt::g_runtime_debug_state.guarded_pages.find(page_base);
                if (page_it == rt::g_runtime_debug_state.guarded_pages.end()) {
                    continue;
                }
                if (page_it->second.ref_count > 0) {
                    --page_it->second.ref_count;
                }
                if (page_it->second.ref_count == 0) {
                    pages_to_restore.push_back(page_it->second);
                    rt::g_runtime_debug_state.guarded_pages.erase(page_it);
                }
            }
            write_it = rt::g_runtime_debug_state.write_watches.erase(write_it);
        }

        if (rt::g_runtime_debug_state.write_watches.empty() &&
            rt::g_runtime_debug_state.write_watch_handler != nullptr) {
            remove_write_handler = true;
        }
    }

    for (const auto& page : pages_to_restore) {
        (void)rt::TrySetPageProtection(page.page_base, page.base_protect);
    }

    if (remove_write_handler) {
        std::scoped_lock lock(rt::g_runtime_debug_state.mutex);
        if (rt::g_runtime_debug_state.write_watches.empty() &&
            rt::g_runtime_debug_state.write_watch_handler != nullptr) {
            RemoveVectoredExceptionHandler(rt::g_runtime_debug_state.write_watch_handler);
            rt::g_runtime_debug_state.write_watch_handler = nullptr;
        }
    }

    if (removed) {
        sdmod::Log("WATCH: disarmed " + watch_name);
    }
    return removed;
}

void RuntimeDebug_ListWatches(std::vector<RuntimeDebugWatchInfo>* watches) {
    namespace rt = sdmod::detail::runtime_debug;

    if (watches == nullptr) {
        return;
    }

    watches->clear();

    std::scoped_lock lock(rt::g_runtime_debug_state.mutex);
    watches->reserve(rt::g_runtime_debug_state.watches.size());
    for (const auto& watch : rt::g_runtime_debug_state.watches) {
        RuntimeDebugWatchInfo info;
        info.name = watch.name;
        info.requested_address = watch.requested_address;
        info.resolved_address = watch.resolved_address;
        info.last_base_address = watch.last_base_address;
        info.last_value_address = watch.last_value_address;
        info.offset = watch.offset;
        info.size = watch.size;
        info.is_ptr_field = watch.kind == rt::WatchKind::PtrField;
        info.last_valid = watch.last_valid;
        watches->push_back(std::move(info));
    }
}

void RuntimeDebug_ListWriteHits(std::vector<RuntimeDebugWriteHitInfo>* hits, const char* name_filter) {
    namespace rt = sdmod::detail::runtime_debug;

    if (hits == nullptr) {
        return;
    }

    hits->clear();
    const std::string filter = name_filter != nullptr ? std::string(name_filter) : std::string();

    std::scoped_lock lock(rt::g_runtime_debug_state.mutex);
    hits->reserve(rt::g_runtime_debug_state.write_hits.size());
    for (const auto& hit : rt::g_runtime_debug_state.write_hits) {
        if (!filter.empty() && hit.name != filter) {
            continue;
        }
        hits->push_back(hit);
    }
}

void RuntimeDebug_ClearWriteHits(const char* name_filter) {
    namespace rt = sdmod::detail::runtime_debug;

    const std::string filter = name_filter != nullptr ? std::string(name_filter) : std::string();

    std::scoped_lock lock(rt::g_runtime_debug_state.mutex);
    if (filter.empty()) {
        rt::g_runtime_debug_state.write_hits.clear();
        return;
    }

    rt::g_runtime_debug_state.write_hits.erase(
        std::remove_if(
            rt::g_runtime_debug_state.write_hits.begin(),
            rt::g_runtime_debug_state.write_hits.end(),
            [&](const RuntimeDebugWriteHitInfo& hit) { return hit.name == filter; }),
        rt::g_runtime_debug_state.write_hits.end());
}

extern "C" void RuntimeDebug_Tick() {
    namespace rt = sdmod::detail::runtime_debug;

    std::vector<std::string> log_lines;

    {
        std::scoped_lock lock(rt::g_runtime_debug_state.mutex);
        for (auto& watch : rt::g_runtime_debug_state.watches) {
            uintptr_t base_address = 0;
            uintptr_t value_address = 0;
            std::vector<std::uint8_t> current_bytes;
            const auto valid = rt::ReadWatchValue(watch, &base_address, &value_address, &current_bytes);
            if (!valid) {
                if (watch.last_valid) {
                    if (watch.kind == rt::WatchKind::Direct) {
                        log_lines.push_back(
                            "WATCH: " + watch.name + " became unreadable at " +
                            sdmod::HexString(watch.requested_address));
                    } else {
                        log_lines.push_back(
                            "WATCH: " + watch.name + " became unreadable ptr=" +
                            sdmod::HexString(watch.requested_address) +
                            " base=" + sdmod::HexString(watch.last_base_address) +
                            " field=" + sdmod::HexString(watch.last_value_address));
                    }
                }
                watch.last_valid = false;
                watch.last_base_address = base_address;
                watch.last_value_address = value_address;
                watch.last_bytes.clear();
                continue;
            }

            if (!watch.last_valid) {
                if (watch.kind == rt::WatchKind::Direct) {
                    log_lines.push_back(
                        "WATCH: " + watch.name + " initial addr=" + sdmod::HexString(watch.requested_address) +
                        " value=" + rt::FormatBytes(current_bytes));
                } else {
                    log_lines.push_back(
                        "WATCH: " + watch.name + " initial ptr=" + sdmod::HexString(watch.requested_address) +
                        " base=" + sdmod::HexString(base_address) +
                        " field=" + sdmod::HexString(value_address) +
                        " value=" + rt::FormatBytes(current_bytes));
                }
                watch.last_valid = true;
                watch.last_base_address = base_address;
                watch.last_value_address = value_address;
                watch.last_bytes = std::move(current_bytes);
                continue;
            }

            const auto base_changed = watch.kind == rt::WatchKind::PtrField && base_address != watch.last_base_address;
            const auto value_changed = watch.last_bytes != current_bytes;
            if (!base_changed && !value_changed) {
                watch.last_base_address = base_address;
                watch.last_value_address = value_address;
                continue;
            }

            if (watch.kind == rt::WatchKind::Direct) {
                log_lines.push_back(
                    "WATCH: " + watch.name + " changed addr=" + sdmod::HexString(watch.requested_address) +
                    " old=" + rt::FormatBytes(watch.last_bytes) +
                    " new=" + rt::FormatBytes(current_bytes));
            } else {
                log_lines.push_back(
                    "WATCH: " + watch.name + " changed ptr=" + sdmod::HexString(watch.requested_address) +
                    " base=" + sdmod::HexString(watch.last_base_address) +
                    " -> " + sdmod::HexString(base_address) +
                    " field=" + sdmod::HexString(watch.last_value_address) +
                    " -> " + sdmod::HexString(value_address) +
                    " old=" + rt::FormatBytes(watch.last_bytes) +
                    " new=" + rt::FormatBytes(current_bytes));
            }

            watch.last_valid = true;
            watch.last_base_address = base_address;
            watch.last_value_address = value_address;
            watch.last_bytes = std::move(current_bytes);
        }
    }

    for (const auto& line : log_lines) {
        sdmod::Log(line);
    }
}

extern "C" void RuntimeDebug_Shutdown() {
    namespace rt = sdmod::detail::runtime_debug;

    std::vector<rt::FunctionTrace*> active_traces;

    {
        std::scoped_lock lock(rt::g_runtime_debug_state.mutex);
        active_traces.reserve(rt::g_runtime_debug_state.active_traces.size());
        for (const auto& entry : rt::g_runtime_debug_state.active_traces) {
            active_traces.push_back(entry.second);
        }
        rt::g_runtime_debug_state.active_traces.clear();
        rt::g_runtime_debug_state.watches.clear();
        for (const auto& [page_base, state] : rt::g_runtime_debug_state.guarded_pages) {
            (void)rt::TrySetPageProtection(page_base, state.base_protect);
        }
        rt::g_runtime_debug_state.guarded_pages.clear();
        rt::g_runtime_debug_state.write_watches.clear();
        rt::g_runtime_debug_state.pending_write_hits.clear();
        rt::g_runtime_debug_state.trace_hits.clear();
        rt::g_runtime_debug_state.write_hits.clear();
        if (rt::g_runtime_debug_state.write_watch_handler != nullptr) {
            RemoveVectoredExceptionHandler(rt::g_runtime_debug_state.write_watch_handler);
            rt::g_runtime_debug_state.write_watch_handler = nullptr;
        }
        rt::g_runtime_debug_state.snapshots.clear();
    }

    for (auto* trace : active_traces) {
        if (trace == nullptr) {
            continue;
        }

        trace->active.store(false, std::memory_order_release);
        sdmod::RemoveX86Hook(&trace->hook);
    }
}

std::string RuntimeDebug_GetLastError() {
    return sdmod::detail::runtime_debug::GetRuntimeDebugLastError();
}
