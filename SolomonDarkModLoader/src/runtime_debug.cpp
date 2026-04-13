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

using sdmod::Log;

#include "runtime_debug/hde32_impl.inl"

namespace {

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

RuntimeDebugState g_runtime_debug_state;
#include "runtime_debug/helpers.inl"

}  // namespace

#include "runtime_debug/public_api.inl"
