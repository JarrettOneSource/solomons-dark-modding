#include "runtime_debug_internal.h"

namespace sdmod::detail::runtime_debug {

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

    sdmod::Log(out.str());
}

void __cdecl RuntimeDebug_HandleTrace(FunctionTrace* trace, const TraceEntryFrame* frame) {
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
    stub[cursor++] = 0x60;
    stub[cursor++] = 0x9C;

    stub[cursor++] = 0x8B;
    stub[cursor++] = 0xC4;

    stub[cursor++] = 0x50;
    stub[cursor++] = 0x68;
    *reinterpret_cast<std::uint32_t*>(stub + cursor) =
        static_cast<std::uint32_t>(reinterpret_cast<std::uintptr_t>(trace));
    cursor += sizeof(std::uint32_t);

    stub[cursor++] = 0xFF;
    stub[cursor++] = 0x15;
    *reinterpret_cast<std::uint32_t*>(stub + cursor) = static_cast<std::uint32_t>(
        reinterpret_cast<std::uintptr_t>(stub + handler_slot_offset));
    cursor += sizeof(std::uint32_t);

    stub[cursor++] = 0x83;
    stub[cursor++] = 0xC4;
    stub[cursor++] = 0x08;
    stub[cursor++] = 0x9D;
    stub[cursor++] = 0x61;

    std::memcpy(stub + cursor, original_bytes.data(), original_bytes.size());
    cursor += original_bytes.size();

    stub[cursor++] = 0xFF;
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

}  // namespace sdmod::detail::runtime_debug

extern "C" bool RuntimeDebug_TraceFunction(uintptr_t address, const char* name) {
    return RuntimeDebug_TraceFunctionEx(address, sdmod::detail::runtime_debug::kDefaultTracePatchSize, name);
}

extern "C" bool RuntimeDebug_TraceFunctionEx(uintptr_t address, size_t patch_size, const char* name) {
    namespace rt = sdmod::detail::runtime_debug;

    const auto resolved_address = rt::ResolveExecutableRuntimeAddress(address);
    if (resolved_address == 0 || (patch_size != 0 && patch_size < 5)) {
        const auto message =
            "TRACE: failed to resolve target " + sdmod::HexString(address) +
            " patch=" + std::to_string(patch_size);
        rt::SetRuntimeDebugLastError(message);
        sdmod::Log(message);
        return false;
    }

    MEMORY_BASIC_INFORMATION target_info = {};
    if (!rt::TryQueryMemoryInfo(resolved_address, &target_info) || target_info.State != MEM_COMMIT) {
        const auto message =
            "TRACE: target " + sdmod::HexString(address) +
            " is not backed by committed memory.";
        rt::SetRuntimeDebugLastError(message);
        sdmod::Log(message);
        return false;
    }

    if (!rt::IsExecutableProtection(target_info.Protect)) {
        const auto message =
            "TRACE: target " + sdmod::HexString(address) +
            " resolved to non-executable memory protect=" + sdmod::HexString(target_info.Protect) +
            ". The address is likely data, a thunk table entry, or a bad mapping.";
        rt::SetRuntimeDebugLastError(message);
        sdmod::Log(message);
        return false;
    }

    std::string patch_error_message;
    const auto effective_patch_size = patch_size == 0
        ? rt::ResolveInstructionBoundaryPatchSize(resolved_address, 5, &patch_error_message)
        : rt::ResolveInstructionBoundaryPatchSize(resolved_address, patch_size, &patch_error_message);
    if (effective_patch_size == 0) {
        const auto message =
            "TRACE: unable to compute a safe patch size for " + sdmod::HexString(address) +
            ": " + patch_error_message;
        rt::SetRuntimeDebugLastError(message);
        sdmod::Log(message);
        return false;
    }

    auto* trace = std::make_unique<rt::FunctionTrace>().release();
    trace->requested_address = address;
    trace->resolved_address = resolved_address;
    trace->name = rt::NormalizeName(name, "trace", address);
    trace->patch_size = effective_patch_size;

    {
        std::scoped_lock lock(rt::g_runtime_debug_state.mutex);
        if (rt::g_runtime_debug_state.active_traces.find(resolved_address) !=
            rt::g_runtime_debug_state.active_traces.end()) {
            const auto message =
                "TRACE: " + trace->name + " already active at " + sdmod::HexString(address);
            rt::ClearRuntimeDebugLastError();
            sdmod::Log(message);
            delete trace;
            return true;
        }
    }

    if (rt::LooksLikeExistingJumpPatch(resolved_address, trace->patch_size)) {
        const auto message =
            "TRACE: refusing to patch " + trace->name + " at " + sdmod::HexString(address) +
            " because the target already looks detoured.";
        rt::SetRuntimeDebugLastError(message);
        sdmod::Log(message);
        delete trace;
        return false;
    }

    std::string error_message;
    if (!rt::BuildTraceStub(trace, &error_message)) {
        const auto message =
            "TRACE: failed to build stub for " + trace->name + ": " + error_message;
        rt::SetRuntimeDebugLastError(message);
        sdmod::Log(message);
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
        rt::SetRuntimeDebugLastError(message);
        sdmod::Log(message);
        delete trace;
        return false;
    }

    trace->active.store(true, std::memory_order_release);

    {
        std::scoped_lock lock(rt::g_runtime_debug_state.mutex);
        rt::g_runtime_debug_state.active_traces[resolved_address] = trace;
        rt::g_runtime_debug_state.trace_storage.emplace_back(trace);
    }

    sdmod::Log(
        "TRACE: armed " + trace->name + " at " + sdmod::HexString(address) +
        " runtime=" + sdmod::HexString(resolved_address) +
        " patch=" + std::to_string(trace->patch_size));
    rt::ClearRuntimeDebugLastError();
    return true;
}

extern "C" void RuntimeDebug_UntraceFunction(uintptr_t address) {
    namespace rt = sdmod::detail::runtime_debug;

    const auto resolved_address = rt::ResolveRuntimeAddress(address);
    rt::FunctionTrace* trace = nullptr;

    {
        std::scoped_lock lock(rt::g_runtime_debug_state.mutex);
        const auto it = rt::g_runtime_debug_state.active_traces.find(resolved_address);
        if (it == rt::g_runtime_debug_state.active_traces.end()) {
            return;
        }
        trace = it->second;
        rt::g_runtime_debug_state.active_traces.erase(it);
    }

    if (trace == nullptr) {
        return;
    }

    trace->active.store(false, std::memory_order_release);
    sdmod::RemoveX86Hook(&trace->hook);
    sdmod::Log("TRACE: disarmed " + trace->name + " at " + sdmod::HexString(trace->requested_address));
}

void RuntimeDebug_ListTraces(std::vector<RuntimeDebugTraceInfo>* traces) {
    namespace rt = sdmod::detail::runtime_debug;

    if (traces == nullptr) {
        return;
    }

    traces->clear();

    std::scoped_lock lock(rt::g_runtime_debug_state.mutex);
    traces->reserve(rt::g_runtime_debug_state.trace_storage.size());
    for (const auto& trace_ptr : rt::g_runtime_debug_state.trace_storage) {
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
    namespace rt = sdmod::detail::runtime_debug;

    if (hits == nullptr) {
        return;
    }

    hits->clear();
    const std::string filter = name_filter != nullptr ? std::string(name_filter) : std::string();

    std::scoped_lock lock(rt::g_runtime_debug_state.mutex);
    hits->reserve(rt::g_runtime_debug_state.trace_hits.size());
    for (const auto& hit : rt::g_runtime_debug_state.trace_hits) {
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
    namespace rt = sdmod::detail::runtime_debug;

    const std::string filter = name_filter != nullptr ? std::string(name_filter) : std::string();

    std::scoped_lock lock(rt::g_runtime_debug_state.mutex);
    if (filter.empty()) {
        rt::g_runtime_debug_state.trace_hits.clear();
        return;
    }

    rt::g_runtime_debug_state.trace_hits.erase(
        std::remove_if(
            rt::g_runtime_debug_state.trace_hits.begin(),
            rt::g_runtime_debug_state.trace_hits.end(),
            [&](const rt::TraceHitRecord& hit) { return hit.name == filter; }),
        rt::g_runtime_debug_state.trace_hits.end());
}
