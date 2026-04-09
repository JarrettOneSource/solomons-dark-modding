#pragma once

#include <cstddef>
#include <cstdint>

#ifdef __cplusplus
extern "C" {
#endif

bool RuntimeDebug_TraceFunction(uintptr_t address, const char* name);
void RuntimeDebug_UntraceFunction(uintptr_t address);
void RuntimeDebug_WatchMemory(uintptr_t address, size_t size, const char* name);
void RuntimeDebug_WatchPtrField(uintptr_t ptr_address, size_t offset, size_t size, const char* name);
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
#endif
