extern "C" bool RuntimeDebug_TraceFunction(uintptr_t address, const char* name) {
    return RuntimeDebug_TraceFunctionEx(address, kDefaultTracePatchSize, name);
}

extern "C" bool RuntimeDebug_TraceFunctionEx(uintptr_t address, size_t patch_size, const char* name) {
    const auto resolved_address = ResolveExecutableRuntimeAddress(address);
    if (resolved_address == 0 || (patch_size != 0 && patch_size < 5)) {
        const auto message =
            "TRACE: failed to resolve target " + sdmod::HexString(address) +
            " patch=" + std::to_string(patch_size);
        SetRuntimeDebugLastError(message);
        Log(message);
        return false;
    }

    MEMORY_BASIC_INFORMATION target_info = {};
    if (!TryQueryMemoryInfo(resolved_address, &target_info) || target_info.State != MEM_COMMIT) {
        const auto message =
            "TRACE: target " + sdmod::HexString(address) +
            " is not backed by committed memory.";
        SetRuntimeDebugLastError(message);
        Log(message);
        return false;
    }

    if (!IsExecutableProtection(target_info.Protect)) {
        const auto message =
            "TRACE: target " + sdmod::HexString(address) +
            " resolved to non-executable memory protect=" + sdmod::HexString(target_info.Protect) +
            ". The address is likely data, a thunk table entry, or a bad mapping.";
        SetRuntimeDebugLastError(message);
        Log(message);
        return false;
    }

    std::string patch_error_message;
    const auto effective_patch_size = patch_size == 0
        ? ResolveInstructionBoundaryPatchSize(resolved_address, 5, &patch_error_message)
        : ResolveInstructionBoundaryPatchSize(resolved_address, patch_size, &patch_error_message);
    if (effective_patch_size == 0) {
        const auto message =
            "TRACE: unable to compute a safe patch size for " + sdmod::HexString(address) +
            ": " + patch_error_message;
        SetRuntimeDebugLastError(message);
        Log(message);
        return false;
    }

    auto* trace = std::make_unique<FunctionTrace>().release();
    trace->requested_address = address;
    trace->resolved_address = resolved_address;
    trace->name = NormalizeName(name, "trace", address);
    trace->patch_size = effective_patch_size;

    {
        std::scoped_lock lock(g_runtime_debug_state.mutex);
        if (g_runtime_debug_state.active_traces.find(resolved_address) != g_runtime_debug_state.active_traces.end()) {
            const auto message =
                "TRACE: " + trace->name + " already active at " + sdmod::HexString(address);
            ClearRuntimeDebugLastError();
            Log(message);
            delete trace;
            return true;
        }
    }

    if (LooksLikeExistingJumpPatch(resolved_address, trace->patch_size)) {
        const auto message =
            "TRACE: refusing to patch " + trace->name + " at " + sdmod::HexString(address) +
            " because the target already looks detoured.";
        SetRuntimeDebugLastError(message);
        Log(message);
        delete trace;
        return false;
    }

    std::string error_message;
    if (!BuildTraceStub(trace, &error_message)) {
        const auto message =
            "TRACE: failed to build stub for " + trace->name + ": " + error_message;
        SetRuntimeDebugLastError(message);
        Log(message);
        delete trace;
        return false;
    }

    if (!sdmod::InstallX86Hook(
            reinterpret_cast<void*>(resolved_address),
            trace->stub,
            trace->patch_size,
            &trace->hook,
            &error_message)) {
        if (trace->stub != nullptr) {
            VirtualFree(trace->stub, 0, MEM_RELEASE);
            trace->stub = nullptr;
        }
        const auto message =
            "TRACE: failed to install hook for " + trace->name + ": " + error_message;
        SetRuntimeDebugLastError(message);
        Log(message);
        delete trace;
        return false;
    }

    trace->active.store(true, std::memory_order_release);

    {
        std::scoped_lock lock(g_runtime_debug_state.mutex);
        g_runtime_debug_state.active_traces[resolved_address] = trace;
        g_runtime_debug_state.trace_storage.emplace_back(trace);
    }

    Log(
        "TRACE: armed " + trace->name + " at " + sdmod::HexString(address) +
        " runtime=" + sdmod::HexString(resolved_address) +
        " patch=" + std::to_string(trace->patch_size));
    ClearRuntimeDebugLastError();
    return true;
}

extern "C" void RuntimeDebug_UntraceFunction(uintptr_t address) {
    const auto resolved_address = ResolveRuntimeAddress(address);
    FunctionTrace* trace = nullptr;

    {
        std::scoped_lock lock(g_runtime_debug_state.mutex);
        const auto it = g_runtime_debug_state.active_traces.find(resolved_address);
        if (it == g_runtime_debug_state.active_traces.end()) {
            return;
        }
        trace = it->second;
        g_runtime_debug_state.active_traces.erase(it);
    }

    if (trace == nullptr) {
        return;
    }

    trace->active.store(false, std::memory_order_release);
    sdmod::RemoveX86Hook(&trace->hook);
    Log("TRACE: disarmed " + trace->name + " at " + sdmod::HexString(trace->requested_address));
}

extern "C" void RuntimeDebug_WatchMemory(uintptr_t address, size_t size, const char* name) {
    const auto resolved_address = ResolveRuntimeAddress(address);
    if (resolved_address == 0 || size == 0) {
        Log("WATCH: failed to arm direct watch at " + sdmod::HexString(address));
        return;
    }

    MemoryWatch watch;
    watch.kind = WatchKind::Direct;
    watch.requested_address = address;
    watch.resolved_address = resolved_address;
    watch.size = size;
    watch.name = NormalizeName(name, "watch", address);

    const MemoryWatch watch_to_log = watch;
    bool replaced_existing = false;
    {
        std::scoped_lock lock(g_runtime_debug_state.mutex);
        const auto duplicate = std::find_if(
            g_runtime_debug_state.watches.begin(),
            g_runtime_debug_state.watches.end(),
            [&](const MemoryWatch& existing) { return SameWatchDefinition(existing, watch); });
        if (duplicate != g_runtime_debug_state.watches.end()) {
            return;
        }

        RemoveNamedWatches(&g_runtime_debug_state.watches, watch.name, &replaced_existing);
        g_runtime_debug_state.watches.push_back(std::move(watch));
    }

    if (replaced_existing) {
        Log("WATCH: replaced " + watch_to_log.name);
    }
    LogWatchRegistered(watch_to_log);
}

extern "C" void RuntimeDebug_WatchPtrField(uintptr_t ptr_address, size_t offset, size_t size, const char* name) {
    const auto resolved_ptr_address = ResolveRuntimeAddress(ptr_address);
    if (resolved_ptr_address == 0 || size == 0) {
        Log("WATCH: failed to arm ptr-field watch at " + sdmod::HexString(ptr_address));
        return;
    }

    MemoryWatch watch;
    watch.kind = WatchKind::PtrField;
    watch.requested_address = ptr_address;
    watch.resolved_address = resolved_ptr_address;
    watch.offset = offset;
    watch.size = size;
    watch.name = NormalizeName(name, "watch_ptr", ptr_address);

    const MemoryWatch watch_to_log = watch;
    bool replaced_existing = false;
    {
        std::scoped_lock lock(g_runtime_debug_state.mutex);
        const auto duplicate = std::find_if(
            g_runtime_debug_state.watches.begin(),
            g_runtime_debug_state.watches.end(),
            [&](const MemoryWatch& existing) { return SameWatchDefinition(existing, watch); });
        if (duplicate != g_runtime_debug_state.watches.end()) {
            return;
        }

        RemoveNamedWatches(&g_runtime_debug_state.watches, watch.name, &replaced_existing);
        g_runtime_debug_state.watches.push_back(std::move(watch));
    }

    if (replaced_existing) {
        Log("WATCH: replaced " + watch_to_log.name);
    }
    LogWatchRegistered(watch_to_log);
}

bool RuntimeDebug_WatchWriteMemory(uintptr_t address, size_t size, const char* name) {
    const auto resolved_address = ResolveRuntimeAddress(address);
    if (resolved_address == 0 || size == 0) {
        Log("WRITE WATCH: failed to arm direct watch at " + sdmod::HexString(address));
        return false;
    }

    WriteWatch watch;
    watch.kind = WatchKind::Direct;
    watch.requested_address = address;
    watch.resolved_address = resolved_address;
    watch.value_address = resolved_address;
    watch.size = size;
    watch.name = NormalizeName(name, "watch_write", address);

    uintptr_t start_address = 0;
    uintptr_t end_address = 0;
    if (!ResolveWriteWatchTarget(watch, &start_address, &end_address)) {
        Log("WRITE WATCH: failed to resolve direct watch range at " + sdmod::HexString(address));
        return false;
    }

    const auto start_page = AlignToPageBase(start_address);
    const auto end_page = AlignToPageBase(end_address - 1);
    for (auto page = start_page; page <= end_page; page += GetSystemPageSize()) {
        watch.page_bases.push_back(page);
    }

    const auto watch_to_log = watch;
    bool replaced_existing = false;
    std::vector<GuardedPageState> pages_to_restore;
    {
        std::scoped_lock lock(g_runtime_debug_state.mutex);
        const auto duplicate = std::find_if(
            g_runtime_debug_state.write_watches.begin(),
            g_runtime_debug_state.write_watches.end(),
            [&](const WriteWatch& existing) { return SameWriteWatchDefinition(existing, watch); });
        if (duplicate != g_runtime_debug_state.write_watches.end()) {
            return true;
        }

        RemoveNamedWriteWatchesAndCollectPages(
            &g_runtime_debug_state.write_watches,
            &g_runtime_debug_state.guarded_pages,
            watch.name,
            &replaced_existing,
            &pages_to_restore);

        for (const auto& page : pages_to_restore) {
            (void)TrySetPageProtection(page.page_base, page.base_protect);
        }
        pages_to_restore.clear();

        if (g_runtime_debug_state.write_watch_handler == nullptr) {
            g_runtime_debug_state.write_watch_handler =
                AddVectoredExceptionHandler(1, &RuntimeDebug_WriteWatchExceptionHandler);
            if (g_runtime_debug_state.write_watch_handler == nullptr) {
                Log("WRITE WATCH: failed to install vectored exception handler.");
                return false;
            }
        }

        for (const auto page_base : watch.page_bases) {
            auto page_it = g_runtime_debug_state.guarded_pages.find(page_base);
            if (page_it == g_runtime_debug_state.guarded_pages.end()) {
                GuardedPageState state;
                state.page_base = page_base;
                if (!TryQueryPageProtection(page_base, &state.base_protect) ||
                    !TrySetPageProtection(page_base, state.base_protect | PAGE_GUARD)) {
                    Log(
                        "WRITE WATCH: failed to guard page " + sdmod::HexString(page_base) +
                        " for " + watch.name);
                    return false;
                }
                state.ref_count = 1;
                g_runtime_debug_state.guarded_pages.emplace(page_base, state);
            } else {
                ++page_it->second.ref_count;
            }
        }

        g_runtime_debug_state.write_watches.push_back(std::move(watch));
    }

    if (replaced_existing) {
        Log("WRITE WATCH: replaced " + watch_to_log.name);
    }
    LogWriteWatchRegistered(watch_to_log);
    return true;
}

bool RuntimeDebug_WatchWritePtrField(uintptr_t ptr_address, size_t offset, size_t size, const char* name) {
    const auto resolved_ptr_address = ResolveRuntimeAddress(ptr_address);
    if (resolved_ptr_address == 0 || size == 0) {
        Log("WRITE WATCH: failed to arm ptr-field watch at " + sdmod::HexString(ptr_address));
        return false;
    }

    uintptr_t base_address = 0;
    if (!sdmod::ProcessMemory::Instance().TryReadValue(resolved_ptr_address, &base_address) || base_address == 0) {
        Log("WRITE WATCH: failed to resolve ptr-field base at " + sdmod::HexString(ptr_address));
        return false;
    }

    uintptr_t value_address = 0;
    if (!TryAddRuntimeOffset(base_address, offset, &value_address)) {
        Log("WRITE WATCH: ptr-field offset overflow at " + sdmod::HexString(ptr_address));
        return false;
    }

    WriteWatch watch;
    watch.kind = WatchKind::PtrField;
    watch.requested_address = ptr_address;
    watch.resolved_address = resolved_ptr_address;
    watch.base_address = base_address;
    watch.value_address = value_address;
    watch.offset = offset;
    watch.size = size;
    watch.name = NormalizeName(name, "watch_write_ptr", ptr_address);

    uintptr_t start_address = 0;
    uintptr_t end_address = 0;
    if (!ResolveWriteWatchTarget(watch, &start_address, &end_address)) {
        Log("WRITE WATCH: failed to resolve ptr-field watch range at " + sdmod::HexString(ptr_address));
        return false;
    }

    const auto start_page = AlignToPageBase(start_address);
    const auto end_page = AlignToPageBase(end_address - 1);
    for (auto page = start_page; page <= end_page; page += GetSystemPageSize()) {
        watch.page_bases.push_back(page);
    }

    const auto watch_to_log = watch;
    bool replaced_existing = false;
    std::vector<GuardedPageState> pages_to_restore;
    {
        std::scoped_lock lock(g_runtime_debug_state.mutex);
        const auto duplicate = std::find_if(
            g_runtime_debug_state.write_watches.begin(),
            g_runtime_debug_state.write_watches.end(),
            [&](const WriteWatch& existing) { return SameWriteWatchDefinition(existing, watch); });
        if (duplicate != g_runtime_debug_state.write_watches.end()) {
            return true;
        }

        RemoveNamedWriteWatchesAndCollectPages(
            &g_runtime_debug_state.write_watches,
            &g_runtime_debug_state.guarded_pages,
            watch.name,
            &replaced_existing,
            &pages_to_restore);

        for (const auto& page : pages_to_restore) {
            (void)TrySetPageProtection(page.page_base, page.base_protect);
        }
        pages_to_restore.clear();

        if (g_runtime_debug_state.write_watch_handler == nullptr) {
            g_runtime_debug_state.write_watch_handler =
                AddVectoredExceptionHandler(1, &RuntimeDebug_WriteWatchExceptionHandler);
            if (g_runtime_debug_state.write_watch_handler == nullptr) {
                Log("WRITE WATCH: failed to install vectored exception handler.");
                return false;
            }
        }

        for (const auto page_base : watch.page_bases) {
            auto page_it = g_runtime_debug_state.guarded_pages.find(page_base);
            if (page_it == g_runtime_debug_state.guarded_pages.end()) {
                GuardedPageState state;
                state.page_base = page_base;
                if (!TryQueryPageProtection(page_base, &state.base_protect) ||
                    !TrySetPageProtection(page_base, state.base_protect | PAGE_GUARD)) {
                    Log(
                        "WRITE WATCH: failed to guard page " + sdmod::HexString(page_base) +
                        " for " + watch.name);
                    return false;
                }
                state.ref_count = 1;
                g_runtime_debug_state.guarded_pages.emplace(page_base, state);
            } else {
                ++page_it->second.ref_count;
            }
        }

        g_runtime_debug_state.write_watches.push_back(std::move(watch));
    }

    if (replaced_existing) {
        Log("WRITE WATCH: replaced " + watch_to_log.name);
    }
    LogWriteWatchRegistered(watch_to_log);
    return true;
}

bool RuntimeDebug_UnwatchMemoryByName(const char* name) {
    if (name == nullptr || *name == '\0') {
        return false;
    }

    const std::string watch_name(name);
    auto removed = false;
    std::vector<GuardedPageState> pages_to_restore;
    auto remove_write_handler = false;
    {
        std::scoped_lock lock(g_runtime_debug_state.mutex);
        RemoveNamedWatches(&g_runtime_debug_state.watches, watch_name, &removed);
        auto write_it = g_runtime_debug_state.write_watches.begin();
        while (write_it != g_runtime_debug_state.write_watches.end()) {
            if (write_it->name != watch_name) {
                ++write_it;
                continue;
            }

            removed = true;
            for (const auto page_base : write_it->page_bases) {
                auto page_it = g_runtime_debug_state.guarded_pages.find(page_base);
                if (page_it == g_runtime_debug_state.guarded_pages.end()) {
                    continue;
                }
                if (page_it->second.ref_count > 0) {
                    --page_it->second.ref_count;
                }
                if (page_it->second.ref_count == 0) {
                    pages_to_restore.push_back(page_it->second);
                    g_runtime_debug_state.guarded_pages.erase(page_it);
                }
            }
            write_it = g_runtime_debug_state.write_watches.erase(write_it);
        }

        if (g_runtime_debug_state.write_watches.empty() &&
            g_runtime_debug_state.write_watch_handler != nullptr) {
            remove_write_handler = true;
        }
    }

    for (const auto& page : pages_to_restore) {
        (void)TrySetPageProtection(page.page_base, page.base_protect);
    }

    if (remove_write_handler) {
        std::scoped_lock lock(g_runtime_debug_state.mutex);
        if (g_runtime_debug_state.write_watches.empty() &&
            g_runtime_debug_state.write_watch_handler != nullptr) {
            RemoveVectoredExceptionHandler(g_runtime_debug_state.write_watch_handler);
            g_runtime_debug_state.write_watch_handler = nullptr;
        }
    }

    if (removed) {
        Log("WATCH: disarmed " + watch_name);
    }
    return removed;
}

void RuntimeDebug_ListWatches(std::vector<RuntimeDebugWatchInfo>* watches) {
    if (watches == nullptr) {
        return;
    }

    watches->clear();

    std::scoped_lock lock(g_runtime_debug_state.mutex);
    watches->reserve(g_runtime_debug_state.watches.size());
    for (const auto& watch : g_runtime_debug_state.watches) {
        RuntimeDebugWatchInfo info;
        info.name = watch.name;
        info.requested_address = watch.requested_address;
        info.resolved_address = watch.resolved_address;
        info.last_base_address = watch.last_base_address;
        info.last_value_address = watch.last_value_address;
        info.offset = watch.offset;
        info.size = watch.size;
        info.is_ptr_field = watch.kind == WatchKind::PtrField;
        info.last_valid = watch.last_valid;
        watches->push_back(std::move(info));
    }
}

void RuntimeDebug_ListTraces(std::vector<RuntimeDebugTraceInfo>* traces) {
    if (traces == nullptr) {
        return;
    }

    traces->clear();

    std::scoped_lock lock(g_runtime_debug_state.mutex);
    traces->reserve(g_runtime_debug_state.trace_storage.size());
    for (const auto& trace_ptr : g_runtime_debug_state.trace_storage) {
        if (!trace_ptr) {
            continue;
        }
        RuntimeDebugTraceInfo info;
        info.name = trace_ptr->name;
        info.requested_address = trace_ptr->requested_address;
        info.resolved_address = trace_ptr->resolved_address;
        info.patch_size = trace_ptr->patch_size;
        info.active = trace_ptr->active.load(std::memory_order_acquire);
        traces->push_back(std::move(info));
    }
}

void RuntimeDebug_ListTraceHits(std::vector<RuntimeDebugTraceHitInfo>* hits, const char* name_filter) {
    if (hits == nullptr) {
        return;
    }

    hits->clear();
    const std::string filter = name_filter != nullptr ? std::string(name_filter) : std::string();

    std::scoped_lock lock(g_runtime_debug_state.mutex);
    hits->reserve(g_runtime_debug_state.trace_hits.size());
    for (const auto& hit : g_runtime_debug_state.trace_hits) {
        if (!filter.empty() && hit.name != filter) {
            continue;
        }

        RuntimeDebugTraceHitInfo info;
        info.name = hit.name;
        info.requested_address = hit.requested_address;
        info.resolved_address = hit.resolved_address;
        info.thread_id = hit.thread_id;
        info.eax = hit.eax;
        info.ecx = hit.ecx;
        info.edx = hit.edx;
        info.ebx = hit.ebx;
        info.esi = hit.esi;
        info.edi = hit.edi;
        info.ebp = hit.ebp;
        info.esp_before_pushad = hit.esp_before_pushad;
        info.eflags = hit.eflags;
        info.ret = hit.ret;
        info.arg0 = hit.arg0;
        info.arg1 = hit.arg1;
        info.arg2 = hit.arg2;
        info.arg3 = hit.arg3;
        info.arg4 = hit.arg4;
        info.arg3_words_valid = hit.arg3_words_valid;
        info.arg3_word0 = hit.arg3_word0;
        info.arg3_word1 = hit.arg3_word1;
        info.arg3_word2 = hit.arg3_word2;
        info.arg3_word3 = hit.arg3_word3;
        info.arg4_words_valid = hit.arg4_words_valid;
        info.arg4_word0 = hit.arg4_word0;
        info.arg4_word1 = hit.arg4_word1;
        info.arg4_word2 = hit.arg4_word2;
        info.arg4_word3 = hit.arg4_word3;
        hits->push_back(std::move(info));
    }
}

void RuntimeDebug_ClearTraceHits(const char* name_filter) {
    const std::string filter = name_filter != nullptr ? std::string(name_filter) : std::string();

    std::scoped_lock lock(g_runtime_debug_state.mutex);
    if (filter.empty()) {
        g_runtime_debug_state.trace_hits.clear();
        return;
    }

    g_runtime_debug_state.trace_hits.erase(
        std::remove_if(
            g_runtime_debug_state.trace_hits.begin(),
            g_runtime_debug_state.trace_hits.end(),
            [&](const TraceHitRecord& hit) { return hit.name == filter; }),
        g_runtime_debug_state.trace_hits.end());
}

void RuntimeDebug_ListWriteHits(std::vector<RuntimeDebugWriteHitInfo>* hits, const char* name_filter) {
    if (hits == nullptr) {
        return;
    }

    hits->clear();
    const std::string filter = name_filter != nullptr ? std::string(name_filter) : std::string();

    std::scoped_lock lock(g_runtime_debug_state.mutex);
    hits->reserve(g_runtime_debug_state.write_hits.size());
    for (const auto& hit : g_runtime_debug_state.write_hits) {
        if (!filter.empty() && hit.name != filter) {
            continue;
        }
        hits->push_back(hit);
    }
}

void RuntimeDebug_ClearWriteHits(const char* name_filter) {
    const std::string filter = name_filter != nullptr ? std::string(name_filter) : std::string();

    std::scoped_lock lock(g_runtime_debug_state.mutex);
    if (filter.empty()) {
        g_runtime_debug_state.write_hits.clear();
        return;
    }

    g_runtime_debug_state.write_hits.erase(
        std::remove_if(
            g_runtime_debug_state.write_hits.begin(),
            g_runtime_debug_state.write_hits.end(),
            [&](const RuntimeDebugWriteHitInfo& hit) { return hit.name == filter; }),
        g_runtime_debug_state.write_hits.end());
}

std::string RuntimeDebug_GetLastError() {
    return GetRuntimeDebugLastError();
}

extern "C" void RuntimeDebug_Snapshot(const char* name, uintptr_t address, size_t size) {
    const auto resolved_address = ResolveRuntimeAddress(address);
    if (resolved_address == 0 || size == 0) {
        Log("SNAPSHOT: failed to capture unnamed snapshot at " + sdmod::HexString(address));
        return;
    }

    Snapshot snapshot;
    snapshot.name = NormalizeName(name, "snapshot", address);
    snapshot.requested_address = address;
    snapshot.resolved_address = resolved_address;
    snapshot.bytes.assign(size, 0);

    if (!sdmod::ProcessMemory::Instance().TryRead(resolved_address, snapshot.bytes.data(), snapshot.bytes.size())) {
        Log(
            "SNAPSHOT: failed to capture " + snapshot.name + " from " + sdmod::HexString(address) +
            " size=" + std::to_string(size));
        return;
    }

    {
        std::scoped_lock lock(g_runtime_debug_state.mutex);
        g_runtime_debug_state.snapshots[snapshot.name] = snapshot;
    }

    Log(
        "SNAPSHOT: captured " + snapshot.name + " addr=" + sdmod::HexString(snapshot.requested_address) +
        " size=" + std::to_string(snapshot.bytes.size()));
}

extern "C" void RuntimeDebug_SnapshotPtrField(const char* name, uintptr_t ptr_address, size_t offset, size_t size) {
    const auto resolved_ptr_address = ResolveRuntimeAddress(ptr_address);
    if (resolved_ptr_address == 0 || size == 0) {
        Log("SNAPSHOT: failed to capture ptr-field snapshot at " + sdmod::HexString(ptr_address));
        return;
    }

    uintptr_t base_address = 0;
    if (!sdmod::ProcessMemory::Instance().TryReadValue(resolved_ptr_address, &base_address) || base_address == 0) {
        Log(
            "SNAPSHOT: failed to resolve ptr-field snapshot " + NormalizeName(name, "snapshot", ptr_address) +
            " ptr=" + sdmod::HexString(ptr_address));
        return;
    }

    uintptr_t field_address = 0;
    if (!TryAddRuntimeOffset(base_address, offset, &field_address)) {
        Log(
            "SNAPSHOT: ptr-field offset overflow for " + NormalizeName(name, "snapshot", ptr_address) +
            " base=" + sdmod::HexString(base_address));
        return;
    }

    RuntimeDebug_Snapshot(name, field_address, size);
}

extern "C" void RuntimeDebug_SnapshotNestedPtrField(
    const char* name,
    uintptr_t ptr_address,
    size_t outer_offset,
    size_t inner_offset,
    size_t size) {
    const auto resolved_ptr_address = ResolveRuntimeAddress(ptr_address);
    if (resolved_ptr_address == 0 || size == 0) {
        Log("SNAPSHOT: failed to capture nested ptr-field snapshot at " + sdmod::HexString(ptr_address));
        return;
    }

    uintptr_t base_address = 0;
    if (!sdmod::ProcessMemory::Instance().TryReadValue(resolved_ptr_address, &base_address) || base_address == 0) {
        Log(
            "SNAPSHOT: failed to resolve nested ptr-field snapshot " +
            NormalizeName(name, "snapshot", ptr_address) +
            " ptr=" + sdmod::HexString(ptr_address));
        return;
    }

    uintptr_t nested_slot_address = 0;
    if (!TryAddRuntimeOffset(base_address, outer_offset, &nested_slot_address)) {
        Log(
            "SNAPSHOT: nested ptr-field outer offset overflow for " +
            NormalizeName(name, "snapshot", ptr_address) +
            " base=" + sdmod::HexString(base_address));
        return;
    }

    uintptr_t nested_address = 0;
    if (!sdmod::ProcessMemory::Instance().TryReadValue(nested_slot_address, &nested_address) || nested_address == 0) {
        Log(
            "SNAPSHOT: failed to resolve nested base for " +
            NormalizeName(name, "snapshot", ptr_address) +
            " base=" + sdmod::HexString(nested_slot_address));
        return;
    }

    uintptr_t field_address = 0;
    if (!TryAddRuntimeOffset(nested_address, inner_offset, &field_address)) {
        Log(
            "SNAPSHOT: nested ptr-field inner offset overflow for " +
            NormalizeName(name, "snapshot", ptr_address) +
            " base=" + sdmod::HexString(nested_address));
        return;
    }

    RuntimeDebug_Snapshot(name, field_address, size);
}

extern "C" void RuntimeDebug_SnapshotDoubleNestedPtrField(
    const char* name,
    uintptr_t ptr_address,
    size_t outer_offset,
    size_t middle_offset,
    size_t inner_offset,
    size_t size) {
    const auto resolved_ptr_address = ResolveRuntimeAddress(ptr_address);
    if (resolved_ptr_address == 0 || size == 0) {
        Log("SNAPSHOT: failed to capture double nested ptr-field snapshot at " + sdmod::HexString(ptr_address));
        return;
    }

    uintptr_t base_address = 0;
    if (!sdmod::ProcessMemory::Instance().TryReadValue(resolved_ptr_address, &base_address) || base_address == 0) {
        Log(
            "SNAPSHOT: failed to resolve double nested ptr-field snapshot " +
            NormalizeName(name, "snapshot", ptr_address) +
            " ptr=" + sdmod::HexString(ptr_address));
        return;
    }

    uintptr_t nested_slot_address = 0;
    if (!TryAddRuntimeOffset(base_address, outer_offset, &nested_slot_address)) {
        Log(
            "SNAPSHOT: double nested outer offset overflow for " +
            NormalizeName(name, "snapshot", ptr_address) +
            " base=" + sdmod::HexString(base_address));
        return;
    }

    uintptr_t nested_address = 0;
    if (!sdmod::ProcessMemory::Instance().TryReadValue(nested_slot_address, &nested_address) || nested_address == 0) {
        Log(
            "SNAPSHOT: failed to resolve first nested base for " +
            NormalizeName(name, "snapshot", ptr_address) +
            " base=" + sdmod::HexString(nested_slot_address));
        return;
    }

    uintptr_t inner_slot_address = 0;
    if (!TryAddRuntimeOffset(nested_address, middle_offset, &inner_slot_address)) {
        Log(
            "SNAPSHOT: double nested middle offset overflow for " +
            NormalizeName(name, "snapshot", ptr_address) +
            " base=" + sdmod::HexString(nested_address));
        return;
    }

    uintptr_t inner_address = 0;
    if (!sdmod::ProcessMemory::Instance().TryReadValue(inner_slot_address, &inner_address) || inner_address == 0) {
        Log(
            "SNAPSHOT: failed to resolve second nested base for " +
            NormalizeName(name, "snapshot", ptr_address) +
            " base=" + sdmod::HexString(inner_slot_address));
        return;
    }

    uintptr_t field_address = 0;
    if (!TryAddRuntimeOffset(inner_address, inner_offset, &field_address)) {
        Log(
            "SNAPSHOT: double nested inner offset overflow for " +
            NormalizeName(name, "snapshot", ptr_address) +
            " base=" + sdmod::HexString(inner_address));
        return;
    }

    RuntimeDebug_Snapshot(name, field_address, size);
}

extern "C" void RuntimeDebug_DiffSnapshots(const char* name_a, const char* name_b) {
    const auto snapshot_name_a = NormalizeName(name_a, "snapshot_a", 0);
    const auto snapshot_name_b = NormalizeName(name_b, "snapshot_b", 0);

    Snapshot snapshot_a;
    Snapshot snapshot_b;
    {
        std::scoped_lock lock(g_runtime_debug_state.mutex);
        const auto it_a = g_runtime_debug_state.snapshots.find(snapshot_name_a);
        const auto it_b = g_runtime_debug_state.snapshots.find(snapshot_name_b);
        if (it_a == g_runtime_debug_state.snapshots.end() || it_b == g_runtime_debug_state.snapshots.end()) {
            Log("SNAPSHOT: diff failed because one or both snapshots are missing.");
            return;
        }
        snapshot_a = it_a->second;
        snapshot_b = it_b->second;
    }

    std::vector<std::string> diff_lines;
    size_t change_count = 0;
    const auto common_size = (std::min)(snapshot_a.bytes.size(), snapshot_b.bytes.size());
    for (size_t index = 0; index < common_size; ++index) {
        if (snapshot_a.bytes[index] == snapshot_b.bytes[index]) {
            continue;
        }

        ++change_count;
        if (diff_lines.size() < kMaxLoggedDiffs) {
            std::ostringstream line;
            line << "SNAPSHOT DIFF: " << snapshot_name_a << " -> " << snapshot_name_b
                 << " +0x" << std::uppercase << std::hex << index
                 << " " << std::setw(2) << std::setfill('0') << static_cast<unsigned int>(snapshot_a.bytes[index])
                 << " -> " << std::setw(2) << std::setfill('0') << static_cast<unsigned int>(snapshot_b.bytes[index]);
            diff_lines.push_back(line.str());
        }
    }

    if (snapshot_a.bytes.size() != snapshot_b.bytes.size()) {
        const auto smaller = common_size;
        const auto larger = (std::max)(snapshot_a.bytes.size(), snapshot_b.bytes.size());
        for (size_t index = smaller; index < larger; ++index) {
            ++change_count;
            if (diff_lines.size() < kMaxLoggedDiffs) {
                std::ostringstream line;
                line << "SNAPSHOT DIFF: " << snapshot_name_a << " -> " << snapshot_name_b
                     << " +0x" << std::uppercase << std::hex << index;
                if (index < snapshot_a.bytes.size()) {
                    line << " " << std::setw(2) << std::setfill('0')
                         << static_cast<unsigned int>(snapshot_a.bytes[index]) << " -> <missing>";
                } else {
                    line << " <missing> -> " << std::setw(2) << std::setfill('0')
                         << static_cast<unsigned int>(snapshot_b.bytes[index]);
                }
                diff_lines.push_back(line.str());
            }
        }
    }

    Log(
        "SNAPSHOT DIFF: " + snapshot_name_a + " vs " + snapshot_name_b +
        " changed=" + std::to_string(change_count) +
        " size_a=" + std::to_string(snapshot_a.bytes.size()) +
        " size_b=" + std::to_string(snapshot_b.bytes.size()));
    for (const auto& line : diff_lines) {
        Log(line);
    }
    if (change_count > diff_lines.size()) {
        Log(
            "SNAPSHOT DIFF: " + std::to_string(change_count - diff_lines.size()) +
            " additional byte changes not logged.");
    }
}

extern "C" void RuntimeDebug_Tick() {
    std::vector<std::string> log_lines;

    {
        std::scoped_lock lock(g_runtime_debug_state.mutex);
        for (auto& watch : g_runtime_debug_state.watches) {
            uintptr_t base_address = 0;
            uintptr_t value_address = 0;
            std::vector<std::uint8_t> current_bytes;
            const auto valid = ReadWatchValue(watch, &base_address, &value_address, &current_bytes);
            if (!valid) {
                if (watch.last_valid) {
                    if (watch.kind == WatchKind::Direct) {
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
                if (watch.kind == WatchKind::Direct) {
                    log_lines.push_back(
                        "WATCH: " + watch.name + " initial addr=" + sdmod::HexString(watch.requested_address) +
                        " value=" + FormatBytes(current_bytes));
                } else {
                    log_lines.push_back(
                        "WATCH: " + watch.name + " initial ptr=" + sdmod::HexString(watch.requested_address) +
                        " base=" + sdmod::HexString(base_address) +
                        " field=" + sdmod::HexString(value_address) +
                        " value=" + FormatBytes(current_bytes));
                }
                watch.last_valid = true;
                watch.last_base_address = base_address;
                watch.last_value_address = value_address;
                watch.last_bytes = std::move(current_bytes);
                continue;
            }

            const auto base_changed = watch.kind == WatchKind::PtrField && base_address != watch.last_base_address;
            const auto value_changed = watch.last_bytes != current_bytes;
            if (!base_changed && !value_changed) {
                watch.last_base_address = base_address;
                watch.last_value_address = value_address;
                continue;
            }

            if (watch.kind == WatchKind::Direct) {
                log_lines.push_back(
                    "WATCH: " + watch.name + " changed addr=" + sdmod::HexString(watch.requested_address) +
                    " old=" + FormatBytes(watch.last_bytes) +
                    " new=" + FormatBytes(current_bytes));
            } else {
                log_lines.push_back(
                    "WATCH: " + watch.name + " changed ptr=" + sdmod::HexString(watch.requested_address) +
                    " base=" + sdmod::HexString(watch.last_base_address) +
                    " -> " + sdmod::HexString(base_address) +
                    " field=" + sdmod::HexString(watch.last_value_address) +
                    " -> " + sdmod::HexString(value_address) +
                    " old=" + FormatBytes(watch.last_bytes) +
                    " new=" + FormatBytes(current_bytes));
            }

            watch.last_valid = true;
            watch.last_base_address = base_address;
            watch.last_value_address = value_address;
            watch.last_bytes = std::move(current_bytes);
        }
    }

    for (const auto& line : log_lines) {
        Log(line);
    }
}

extern "C" void RuntimeDebug_Shutdown() {
    std::vector<FunctionTrace*> active_traces;

    {
        std::scoped_lock lock(g_runtime_debug_state.mutex);
        active_traces.reserve(g_runtime_debug_state.active_traces.size());
        for (const auto& entry : g_runtime_debug_state.active_traces) {
            active_traces.push_back(entry.second);
        }
        g_runtime_debug_state.active_traces.clear();
        g_runtime_debug_state.watches.clear();
        for (const auto& [page_base, state] : g_runtime_debug_state.guarded_pages) {
            (void)TrySetPageProtection(page_base, state.base_protect);
        }
        g_runtime_debug_state.guarded_pages.clear();
        g_runtime_debug_state.write_watches.clear();
        g_runtime_debug_state.pending_write_hits.clear();
        g_runtime_debug_state.trace_hits.clear();
        g_runtime_debug_state.write_hits.clear();
        if (g_runtime_debug_state.write_watch_handler != nullptr) {
            RemoveVectoredExceptionHandler(g_runtime_debug_state.write_watch_handler);
            g_runtime_debug_state.write_watch_handler = nullptr;
        }
        g_runtime_debug_state.snapshots.clear();
    }

    for (auto* trace : active_traces) {
        if (trace == nullptr) {
            continue;
        }

        trace->active.store(false, std::memory_order_release);
        sdmod::RemoveX86Hook(&trace->hook);
    }
}
