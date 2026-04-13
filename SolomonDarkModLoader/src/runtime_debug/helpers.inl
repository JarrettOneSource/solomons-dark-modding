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
    if (memory.IsExecutableRange(address, 1)) {
        return address;
    }

    const auto resolved = memory.ResolveGameAddressOrZero(address);
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

void LogTraceHit(FunctionTrace* trace, const TraceEntryFrame* frame) {
    if (trace == nullptr || !trace->active.load(std::memory_order_acquire)) {
        return;
    }

    if (frame != nullptr) {
        const auto* stack_words = reinterpret_cast<const std::uint32_t*>(
            reinterpret_cast<const std::uint8_t*>(frame) + sizeof(TraceEntryFrame));
        TraceHitRecord hit;
        hit.name = trace->name;
        hit.requested_address = trace->requested_address;
        hit.resolved_address = trace->resolved_address;
        hit.thread_id = GetCurrentThreadId();
        hit.eflags = frame->eflags;
        hit.edi = frame->edi;
        hit.esi = frame->esi;
        hit.ebp = frame->ebp;
        hit.esp_before_pushad = frame->esp_before_pushad;
        hit.ebx = frame->ebx;
        hit.edx = frame->edx;
        hit.ecx = frame->ecx;
        hit.eax = frame->eax;
        hit.ret = stack_words[0];
        hit.arg0 = stack_words[1];
        hit.arg1 = stack_words[2];
        hit.arg2 = stack_words[3];
        hit.arg3 = stack_words[4];
        hit.arg4 = stack_words[5];
        std::uint32_t arg3_words[4] = {};
        if (stack_words[4] != 0 &&
            sdmod::ProcessMemory::Instance().TryRead(stack_words[4], arg3_words, sizeof(arg3_words))) {
            hit.arg3_words_valid = true;
            hit.arg3_word0 = arg3_words[0];
            hit.arg3_word1 = arg3_words[1];
            hit.arg3_word2 = arg3_words[2];
            hit.arg3_word3 = arg3_words[3];
        }
        std::uint32_t arg4_words[4] = {};
        if (stack_words[5] != 0 &&
            sdmod::ProcessMemory::Instance().TryRead(stack_words[5], arg4_words, sizeof(arg4_words))) {
            hit.arg4_words_valid = true;
            hit.arg4_word0 = arg4_words[0];
            hit.arg4_word1 = arg4_words[1];
            hit.arg4_word2 = arg4_words[2];
            hit.arg4_word3 = arg4_words[3];
        }
        std::scoped_lock lock(g_runtime_debug_state.mutex);
        g_runtime_debug_state.trace_hits.push_back(std::move(hit));
        if (g_runtime_debug_state.trace_hits.size() > kMaxStoredTraceHits) {
            g_runtime_debug_state.trace_hits.erase(g_runtime_debug_state.trace_hits.begin());
        }
    }

    std::ostringstream out;
    out <<
        "TRACE: " << trace->name << " called at " << sdmod::HexString(trace->requested_address) <<
        " runtime=" << sdmod::HexString(trace->resolved_address);

    if (frame != nullptr) {
        const auto* stack_words = reinterpret_cast<const std::uint32_t*>(
            reinterpret_cast<const std::uint8_t*>(frame) + sizeof(TraceEntryFrame));
        out <<
            " eax=" << sdmod::HexString(frame->eax) <<
            " ecx=" << sdmod::HexString(frame->ecx) <<
            " edx=" << sdmod::HexString(frame->edx) <<
            " ebx=" << sdmod::HexString(frame->ebx) <<
            " ebp=" << sdmod::HexString(frame->ebp) <<
            " esi=" << sdmod::HexString(frame->esi) <<
            " edi=" << sdmod::HexString(frame->edi) <<
            " esp0=" << sdmod::HexString(frame->esp_before_pushad) <<
            " ret=" << sdmod::HexString(stack_words[0]) <<
            " arg0=" << sdmod::HexString(stack_words[1]) <<
            " arg1=" << sdmod::HexString(stack_words[2]) <<
            " arg2=" << sdmod::HexString(stack_words[3]) <<
            " arg3=" << sdmod::HexString(stack_words[4]) <<
            " arg4=" << sdmod::HexString(stack_words[5]);
        AppendTracePointerInfo(&out, "ecx", frame->ecx);
        AppendTracePointerInfo(&out, "edx", frame->edx);
        AppendTracePointerInfo(&out, "arg0", stack_words[1]);
        AppendTracePointerInfo(&out, "arg3", stack_words[4]);
        std::uint32_t arg3_words[4] = {};
        if (stack_words[4] != 0 &&
            sdmod::ProcessMemory::Instance().TryRead(stack_words[4], arg3_words, sizeof(arg3_words))) {
            out <<
                " arg3_words=" <<
                sdmod::HexString(arg3_words[0]) << "," <<
                sdmod::HexString(arg3_words[1]) << "," <<
                sdmod::HexString(arg3_words[2]) << "," <<
                sdmod::HexString(arg3_words[3]);
        }
        std::uint32_t arg4_words[4] = {};
        if (stack_words[5] != 0 &&
            sdmod::ProcessMemory::Instance().TryRead(stack_words[5], arg4_words, sizeof(arg4_words))) {
            out <<
                " arg4_words=" <<
                sdmod::HexString(arg4_words[0]) << "," <<
                sdmod::HexString(arg4_words[1]) << "," <<
                sdmod::HexString(arg4_words[2]) << "," <<
                sdmod::HexString(arg4_words[3]);
        }
    }

    Log(out.str());
}

extern "C" void __cdecl RuntimeDebug_HandleTrace(FunctionTrace* trace, const TraceEntryFrame* frame) {
    LogTraceHit(trace, frame);
}

std::size_t TraceStubSize(size_t patch_size) {
    return 21 + patch_size + 6 + 8;
}

bool BuildTraceStub(FunctionTrace* trace, std::string* error_message) {
    if (trace == nullptr || trace->resolved_address == 0 || trace->patch_size < 5) {
        if (error_message != nullptr) {
            *error_message = "Invalid trace stub parameters.";
        }
        return false;
    }

    std::vector<std::uint8_t> original_bytes(trace->patch_size);
    if (!sdmod::ProcessMemory::Instance().TryRead(
            trace->resolved_address,
            original_bytes.data(),
            original_bytes.size())) {
        if (error_message != nullptr) {
            *error_message = "Unable to read original bytes for trace target.";
        }
        return false;
    }

    const auto stub_size = TraceStubSize(trace->patch_size);
    auto* stub = static_cast<std::uint8_t*>(
        VirtualAlloc(nullptr, stub_size, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE));
    if (stub == nullptr) {
        if (error_message != nullptr) {
            *error_message = "VirtualAlloc failed while creating a trace stub.";
        }
        return false;
    }

    const auto handler_slot_offset = stub_size - sizeof(void*) - sizeof(std::uintptr_t);
    const auto continuation_slot_offset = stub_size - sizeof(std::uintptr_t);

    // The stub logs the call, replays the overwritten prologue bytes in-place,
    // then jumps back to target+patch_size. That keeps it independent from the
    // X86Hook trampoline so untrace/shutdown can safely tear hooks down.
    size_t cursor = 0;
    stub[cursor++] = 0x60;  // pushad
    stub[cursor++] = 0x9C;  // pushfd

    stub[cursor++] = 0x8B;  // mov eax, esp
    stub[cursor++] = 0xC4;

    stub[cursor++] = 0x50;  // push eax (TraceEntryFrame*)
    stub[cursor++] = 0x68;  // push imm32
    *reinterpret_cast<std::uint32_t*>(stub + cursor) =
        static_cast<std::uint32_t>(reinterpret_cast<std::uintptr_t>(trace));
    cursor += sizeof(std::uint32_t);

    stub[cursor++] = 0xFF;  // call dword ptr [abs32]
    stub[cursor++] = 0x15;
    *reinterpret_cast<std::uint32_t*>(stub + cursor) = static_cast<std::uint32_t>(
        reinterpret_cast<std::uintptr_t>(stub + handler_slot_offset));
    cursor += sizeof(std::uint32_t);

    stub[cursor++] = 0x83;  // add esp, 8
    stub[cursor++] = 0xC4;
    stub[cursor++] = 0x08;
    stub[cursor++] = 0x9D;  // popfd
    stub[cursor++] = 0x61;  // popad

    std::memcpy(stub + cursor, original_bytes.data(), original_bytes.size());
    cursor += original_bytes.size();

    stub[cursor++] = 0xFF;  // jmp dword ptr [abs32]
    stub[cursor++] = 0x25;
    *reinterpret_cast<std::uint32_t*>(stub + cursor) = static_cast<std::uint32_t>(
        reinterpret_cast<std::uintptr_t>(stub + continuation_slot_offset));
    cursor += sizeof(std::uint32_t);

    *reinterpret_cast<void**>(stub + cursor) = reinterpret_cast<void*>(&RuntimeDebug_HandleTrace);
    cursor += sizeof(void*);
    *reinterpret_cast<std::uintptr_t*>(stub + cursor) = trace->resolved_address + trace->patch_size;
    cursor += sizeof(std::uintptr_t);

    trace->stub = stub;
    return true;
}

void LogWatchRegistered(const MemoryWatch& watch) {
    if (watch.kind == WatchKind::Direct) {
        Log(
            "WATCH: armed " + watch.name + " addr=" + sdmod::HexString(watch.requested_address) +
            " size=" + std::to_string(watch.size));
        return;
    }

    Log(
        "WATCH: armed " + watch.name + " ptr=" + sdmod::HexString(watch.requested_address) +
        " offset=" + sdmod::HexString(static_cast<uintptr_t>(watch.offset)) +
        " size=" + std::to_string(watch.size));
}

bool ReadWatchValue(const MemoryWatch& watch, uintptr_t* base_address, uintptr_t* value_address, std::vector<std::uint8_t>* bytes) {
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

void RemoveNamedWriteWatches(std::vector<WriteWatch>* watches, const std::string& name, bool* removed_any) {
    if (watches == nullptr) {
        return;
    }

    const auto new_end = std::remove_if(
        watches->begin(),
        watches->end(),
        [&](const WriteWatch& watch) { return watch.name == name; });
    const auto removed = new_end != watches->end();
    watches->erase(new_end, watches->end());
    if (removed_any != nullptr) {
        *removed_any = removed;
    }
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
        Log(
            "WRITE WATCH: armed " + watch.name +
            " ptr=" + sdmod::HexString(watch.requested_address) +
            " base=" + sdmod::HexString(watch.base_address) +
            " field=" + sdmod::HexString(watch.value_address) +
            " offset=" + sdmod::HexString(static_cast<uintptr_t>(watch.offset)) +
            " size=" + std::to_string(watch.size));
        return;
    }

    Log(
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
    Log(out.str());
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
