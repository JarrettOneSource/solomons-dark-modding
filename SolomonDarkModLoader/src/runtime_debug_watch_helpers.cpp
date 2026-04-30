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
