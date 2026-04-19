#pragma once

#include "runtime_debug.h"

#include "logger.h"
#include "memory_access.h"
#include "mod_loader.h"
#include "third_party/hde32.h"
#include "x86_hook.h"

#include <Windows.h>

#include <algorithm>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <iomanip>
#include <limits>
#include <memory>
#include <mutex>
#include <sstream>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace sdmod::detail::runtime_debug {

static_assert(sizeof(void*) == 4, "runtime_debug only supports x86 builds.");
static_assert(sizeof(uintptr_t) == 4, "runtime_debug only supports x86 builds.");

constexpr size_t kDefaultTracePatchSize = 0;
constexpr size_t kMaxLoggedBytes = 32;
constexpr size_t kMaxLoggedDiffs = 128;
constexpr size_t kMaxStoredTraceHits = 256;
constexpr size_t kMaxStoredWriteHits = 256;
constexpr DWORD kWriteWatchTrapFlag = 0x100;

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

struct TraceHitRecord {
    std::string name;
    uintptr_t requested_address = 0;
    uintptr_t resolved_address = 0;
    DWORD thread_id = 0;
    std::uint32_t eflags = 0;
    std::uint32_t edi = 0;
    std::uint32_t esi = 0;
    std::uint32_t ebp = 0;
    std::uint32_t esp_before_pushad = 0;
    std::uint32_t ebx = 0;
    std::uint32_t edx = 0;
    std::uint32_t ecx = 0;
    std::uint32_t eax = 0;
    std::uint32_t ret = 0;
    std::uint32_t arg0 = 0;
    std::uint32_t arg1 = 0;
    std::uint32_t arg2 = 0;
    std::uint32_t arg3 = 0;
    std::uint32_t arg4 = 0;
    bool arg3_words_valid = false;
    std::uint32_t arg3_word0 = 0;
    std::uint32_t arg3_word1 = 0;
    std::uint32_t arg3_word2 = 0;
    std::uint32_t arg3_word3 = 0;
    bool arg4_words_valid = false;
    std::uint32_t arg4_word0 = 0;
    std::uint32_t arg4_word1 = 0;
    std::uint32_t arg4_word2 = 0;
    std::uint32_t arg4_word3 = 0;
};

struct Snapshot {
    std::string name;
    uintptr_t requested_address = 0;
    uintptr_t resolved_address = 0;
    std::vector<std::uint8_t> bytes;
};

struct WriteWatch {
    WatchKind kind = WatchKind::Direct;
    uintptr_t requested_address = 0;
    uintptr_t resolved_address = 0;
    uintptr_t base_address = 0;
    uintptr_t value_address = 0;
    size_t offset = 0;
    size_t size = 0;
    std::string name;
    std::vector<uintptr_t> page_bases;
};

struct GuardedPageState {
    uintptr_t page_base = 0;
    DWORD base_protect = 0;
    size_t ref_count = 0;
    bool pending_rearm = false;
};

struct PendingWriteHit {
    DWORD thread_id = 0;
    WatchKind kind = WatchKind::Direct;
    std::string name;
    uintptr_t requested_address = 0;
    uintptr_t resolved_address = 0;
    uintptr_t base_address = 0;
    uintptr_t value_address = 0;
    size_t offset = 0;
    uintptr_t access_address = 0;
    size_t size = 0;
    std::uint32_t eip = 0;
    std::uint32_t esp = 0;
    std::uint32_t ebp = 0;
    std::uint32_t eax = 0;
    std::uint32_t ecx = 0;
    std::uint32_t edx = 0;
    std::uint32_t ret = 0;
    std::uint32_t arg0 = 0;
    std::uint32_t arg1 = 0;
    std::uint32_t arg2 = 0;
    std::vector<std::uint8_t> before_bytes;
};

struct RuntimeDebugState {
    std::mutex mutex;
    std::unordered_map<uintptr_t, FunctionTrace*> active_traces;
    std::vector<std::unique_ptr<FunctionTrace>> trace_storage;
    std::vector<TraceHitRecord> trace_hits;
    std::vector<MemoryWatch> watches;
    std::vector<WriteWatch> write_watches;
    std::unordered_map<uintptr_t, GuardedPageState> guarded_pages;
    std::vector<PendingWriteHit> pending_write_hits;
    std::vector<RuntimeDebugWriteHitInfo> write_hits;
    std::unordered_map<std::string, Snapshot> snapshots;
    std::string last_error_message;
    void* write_watch_handler = nullptr;
};

extern RuntimeDebugState g_runtime_debug_state;

uintptr_t ResolveRuntimeAddress(uintptr_t address);
uintptr_t ResolveExecutableRuntimeAddress(uintptr_t address);
std::string MakeDefaultName(const char* prefix, uintptr_t address);
std::string NormalizeName(const char* name, const char* prefix, uintptr_t address);
void SetRuntimeDebugLastError(std::string message);
void ClearRuntimeDebugLastError();
std::string GetRuntimeDebugLastError();
std::string FormatBytes(const std::uint8_t* bytes, size_t size);
std::string FormatBytes(const std::vector<std::uint8_t>& bytes);
bool TryAddRuntimeOffset(uintptr_t base_address, size_t offset, uintptr_t* result);
size_t GetSystemPageSize();
uintptr_t AlignToPageBase(uintptr_t address);
bool TryQueryPageProtection(uintptr_t address, DWORD* protect);
bool TryQueryMemoryInfo(uintptr_t address, MEMORY_BASIC_INFORMATION* info);
bool IsExecutableProtection(DWORD protect);
bool TrySetPageProtection(uintptr_t page_base, DWORD protect);
bool TryReadStackWords(uintptr_t esp, std::uint32_t* stack_words, size_t word_count);
bool LooksLikeExistingJumpPatch(uintptr_t address, size_t patch_size);
size_t ResolveInstructionBoundaryPatchSize(uintptr_t address, size_t minimum_size, std::string* error_message);
void AppendTracePointerInfo(std::ostringstream* out, const char* label, uintptr_t value);

void LogTraceHit(FunctionTrace* trace, const TraceEntryFrame* frame);
void __cdecl RuntimeDebug_HandleTrace(FunctionTrace* trace, const TraceEntryFrame* frame);
std::size_t TraceStubSize(size_t patch_size);
bool BuildTraceStub(FunctionTrace* trace, std::string* error_message);

void LogWatchRegistered(const MemoryWatch& watch);
bool ReadWatchValue(
    const MemoryWatch& watch,
    uintptr_t* base_address,
    uintptr_t* value_address,
    std::vector<std::uint8_t>* bytes);
bool SameWatchDefinition(const MemoryWatch& lhs, const MemoryWatch& rhs);
void RemoveNamedWatches(std::vector<MemoryWatch>* watches, const std::string& name, bool* removed_any);

bool SameWriteWatchDefinition(const WriteWatch& lhs, const WriteWatch& rhs);
bool ResolveWriteWatchTarget(const WriteWatch& watch, uintptr_t* start_address, uintptr_t* end_address);
void RemoveNamedWriteWatchesAndCollectPages(
    std::vector<WriteWatch>* watches,
    std::unordered_map<uintptr_t, GuardedPageState>* guarded_pages,
    const std::string& name,
    bool* removed_any,
    std::vector<GuardedPageState>* pages_to_restore);
void LogWriteWatchRegistered(const WriteWatch& watch);
void LogWriteWatchHit(const PendingWriteHit& hit, const std::vector<std::uint8_t>& after_bytes);
LONG CALLBACK RuntimeDebug_WriteWatchExceptionHandler(EXCEPTION_POINTERS* exception_pointers);

}  // namespace sdmod::detail::runtime_debug
