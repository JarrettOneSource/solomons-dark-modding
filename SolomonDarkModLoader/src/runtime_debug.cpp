#include "runtime_debug.h"

#include "logger.h"
#include "memory_access.h"
#include "mod_loader.h"
#include "x86_hook.h"

#include <Windows.h>

#include <algorithm>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <iomanip>
#include <memory>
#include <mutex>
#include <sstream>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

using sdmod::Log;

namespace {

static_assert(sizeof(void*) == 4, "runtime_debug only supports x86 builds.");
static_assert(sizeof(uintptr_t) == 4, "runtime_debug only supports x86 builds.");

constexpr size_t kDefaultTracePatchSize = 7;
constexpr size_t kMaxLoggedBytes = 32;
constexpr size_t kMaxLoggedDiffs = 128;

enum class WatchKind {
    Direct,
    PtrField,
};

struct FunctionTrace {
    uintptr_t requested_address = 0;
    uintptr_t resolved_address = 0;
    std::string name;
    std::atomic<bool> active = false;
    sdmod::X86Hook hook = {};
    void* stub = nullptr;
    size_t patch_size = 0;
};

struct TraceEntryFrame {
    std::uint32_t eflags = 0;
    std::uint32_t edi = 0;
    std::uint32_t esi = 0;
    std::uint32_t ebp = 0;
    std::uint32_t esp_before_pushad = 0;
    std::uint32_t ebx = 0;
    std::uint32_t edx = 0;
    std::uint32_t ecx = 0;
    std::uint32_t eax = 0;
};

static_assert(sizeof(TraceEntryFrame) == 9 * sizeof(std::uint32_t), "Unexpected trace frame size.");

struct MemoryWatch {
    WatchKind kind = WatchKind::Direct;
    uintptr_t requested_address = 0;
    uintptr_t resolved_address = 0;
    size_t offset = 0;
    size_t size = 0;
    std::string name;
    bool last_valid = false;
    uintptr_t last_base_address = 0;
    uintptr_t last_value_address = 0;
    std::vector<std::uint8_t> last_bytes;
};

struct Snapshot {
    std::string name;
    uintptr_t requested_address = 0;
    uintptr_t resolved_address = 0;
    std::vector<std::uint8_t> bytes;
};

struct RuntimeDebugState {
    std::mutex mutex;
    std::unordered_map<uintptr_t, FunctionTrace*> active_traces;
    std::vector<std::unique_ptr<FunctionTrace>> trace_storage;
    std::vector<MemoryWatch> watches;
    std::unordered_map<std::string, Snapshot> snapshots;
};

RuntimeDebugState g_runtime_debug_state;

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
            " arg2=" << sdmod::HexString(stack_words[3]);
        AppendTracePointerInfo(&out, "ecx", frame->ecx);
        AppendTracePointerInfo(&out, "edx", frame->edx);
        AppendTracePointerInfo(&out, "arg0", stack_words[1]);
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

    *base_address = object_address;
    *value_address = object_address + watch.offset;
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

}  // namespace

extern "C" bool RuntimeDebug_TraceFunction(uintptr_t address, const char* name) {
    const auto resolved_address = ResolveRuntimeAddress(address);
    if (resolved_address == 0) {
        Log("TRACE: failed to resolve target " + sdmod::HexString(address));
        return false;
    }

    auto* trace = std::make_unique<FunctionTrace>().release();
    trace->requested_address = address;
    trace->resolved_address = resolved_address;
    trace->name = NormalizeName(name, "trace", address);
    trace->patch_size = kDefaultTracePatchSize;

    {
        std::scoped_lock lock(g_runtime_debug_state.mutex);
        if (g_runtime_debug_state.active_traces.find(resolved_address) != g_runtime_debug_state.active_traces.end()) {
            Log("TRACE: " + trace->name + " already active at " + sdmod::HexString(address));
            delete trace;
            return true;
        }
    }

    if (LooksLikeExistingJumpPatch(resolved_address, trace->patch_size)) {
        Log(
            "TRACE: refusing to patch " + trace->name + " at " + sdmod::HexString(address) +
            " because the target already looks detoured.");
        delete trace;
        return false;
    }

    std::string error_message;
    if (!BuildTraceStub(trace, &error_message)) {
        Log("TRACE: failed to build stub for " + trace->name + ": " + error_message);
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
        Log("TRACE: failed to install hook for " + trace->name + ": " + error_message);
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

    {
        std::scoped_lock lock(g_runtime_debug_state.mutex);
        const auto duplicate = std::find_if(
            g_runtime_debug_state.watches.begin(),
            g_runtime_debug_state.watches.end(),
            [&](const MemoryWatch& existing) { return SameWatchDefinition(existing, watch); });
        if (duplicate != g_runtime_debug_state.watches.end()) {
            return;
        }

        g_runtime_debug_state.watches.push_back(std::move(watch));
        LogWatchRegistered(g_runtime_debug_state.watches.back());
    }
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

    {
        std::scoped_lock lock(g_runtime_debug_state.mutex);
        const auto duplicate = std::find_if(
            g_runtime_debug_state.watches.begin(),
            g_runtime_debug_state.watches.end(),
            [&](const MemoryWatch& existing) { return SameWatchDefinition(existing, watch); });
        if (duplicate != g_runtime_debug_state.watches.end()) {
            return;
        }

        g_runtime_debug_state.watches.push_back(std::move(watch));
        LogWatchRegistered(g_runtime_debug_state.watches.back());
    }
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

    RuntimeDebug_Snapshot(name, base_address + offset, size);
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

    uintptr_t nested_address = 0;
    if (!sdmod::ProcessMemory::Instance().TryReadValue(base_address + outer_offset, &nested_address) ||
        nested_address == 0) {
        Log(
            "SNAPSHOT: failed to resolve nested base for " +
            NormalizeName(name, "snapshot", ptr_address) +
            " base=" + sdmod::HexString(base_address + outer_offset));
        return;
    }

    RuntimeDebug_Snapshot(name, nested_address + inner_offset, size);
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

    uintptr_t nested_address = 0;
    if (!sdmod::ProcessMemory::Instance().TryReadValue(base_address + outer_offset, &nested_address) ||
        nested_address == 0) {
        Log(
            "SNAPSHOT: failed to resolve first nested base for " +
            NormalizeName(name, "snapshot", ptr_address) +
            " base=" + sdmod::HexString(base_address + outer_offset));
        return;
    }

    uintptr_t inner_address = 0;
    if (!sdmod::ProcessMemory::Instance().TryReadValue(nested_address + middle_offset, &inner_address) ||
        inner_address == 0) {
        Log(
            "SNAPSHOT: failed to resolve second nested base for " +
            NormalizeName(name, "snapshot", ptr_address) +
            " base=" + sdmod::HexString(nested_address + middle_offset));
        return;
    }

    RuntimeDebug_Snapshot(name, inner_address + inner_offset, size);
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
