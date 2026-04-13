#pragma once

#include <cstddef>
#include <cstdint>

#ifdef __cplusplus
#include <string>
#include <vector>

extern "C" {
#endif

bool RuntimeDebug_TraceFunction(uintptr_t address, const char* name);
bool RuntimeDebug_TraceFunctionEx(uintptr_t address, size_t patch_size, const char* name);
void RuntimeDebug_UntraceFunction(uintptr_t address);
void RuntimeDebug_WatchMemory(uintptr_t address, size_t size, const char* name);
void RuntimeDebug_WatchPtrField(uintptr_t ptr_address, size_t offset, size_t size, const char* name);
bool RuntimeDebug_WatchWriteMemory(uintptr_t address, size_t size, const char* name);
bool RuntimeDebug_WatchWritePtrField(uintptr_t ptr_address, size_t offset, size_t size, const char* name);
void RuntimeDebug_Snapshot(const char* name, uintptr_t address, size_t size);
void RuntimeDebug_SnapshotPtrField(const char* name, uintptr_t ptr_address, size_t offset, size_t size);
void RuntimeDebug_SnapshotNestedPtrField(
    const char* name,
    uintptr_t ptr_address,
    size_t outer_offset,
    size_t inner_offset,
    size_t size);
void RuntimeDebug_SnapshotDoubleNestedPtrField(
    const char* name,
    uintptr_t ptr_address,
    size_t outer_offset,
    size_t middle_offset,
    size_t inner_offset,
    size_t size);
void RuntimeDebug_DiffSnapshots(const char* name_a, const char* name_b);
void RuntimeDebug_Tick();
void RuntimeDebug_Shutdown();

#ifdef __cplusplus
}

struct RuntimeDebugTraceInfo {
    std::string name;
    uintptr_t requested_address = 0;
    uintptr_t resolved_address = 0;
    size_t patch_size = 0;
    bool active = false;
};

struct RuntimeDebugTraceHitInfo {
    std::string name;
    uintptr_t requested_address = 0;
    uintptr_t resolved_address = 0;
    std::uint32_t thread_id = 0;
    std::uint32_t eax = 0;
    std::uint32_t ecx = 0;
    std::uint32_t edx = 0;
    std::uint32_t ebx = 0;
    std::uint32_t esi = 0;
    std::uint32_t edi = 0;
    std::uint32_t ebp = 0;
    std::uint32_t esp_before_pushad = 0;
    std::uint32_t eflags = 0;
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

struct RuntimeDebugWatchInfo {
    std::string name;
    uintptr_t requested_address = 0;
    uintptr_t resolved_address = 0;
    uintptr_t last_base_address = 0;
    uintptr_t last_value_address = 0;
    size_t offset = 0;
    size_t size = 0;
    bool is_ptr_field = false;
    bool last_valid = false;
};

struct RuntimeDebugWriteHitInfo {
    std::string name;
    uintptr_t requested_address = 0;
    uintptr_t resolved_address = 0;
    uintptr_t base_address = 0;
    uintptr_t value_address = 0;
    uintptr_t access_address = 0;
    size_t offset = 0;
    size_t size = 0;
    bool is_ptr_field = false;
    std::uint32_t thread_id = 0;
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
    std::string before_bytes_hex;
    std::string after_bytes_hex;
};

bool RuntimeDebug_UnwatchMemoryByName(const char* name);
void RuntimeDebug_ListWatches(std::vector<RuntimeDebugWatchInfo>* watches);
void RuntimeDebug_ListTraces(std::vector<RuntimeDebugTraceInfo>* traces);
void RuntimeDebug_ListTraceHits(std::vector<RuntimeDebugTraceHitInfo>* hits, const char* name_filter = nullptr);
void RuntimeDebug_ClearTraceHits(const char* name_filter = nullptr);
void RuntimeDebug_ListWriteHits(std::vector<RuntimeDebugWriteHitInfo>* hits, const char* name_filter = nullptr);
void RuntimeDebug_ClearWriteHits(const char* name_filter = nullptr);
std::string RuntimeDebug_GetLastError();
#endif
