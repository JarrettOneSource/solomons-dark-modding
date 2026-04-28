#include "lua_engine_bindings_internal.h"
#include "memory_access.h"
#include "mod_loader.h"
#include "runtime_debug.h"

#include <algorithm>
#include <cctype>
#include <cstring>
#include <iomanip>
#include <limits>
#include <sstream>
#include <string>
#include <string_view>
#include <type_traits>
#include <vector>

namespace sdmod::detail {
namespace {

constexpr size_t kMaxLuaDebugTransferSize = 1024 * 1024;
constexpr size_t kMaxLuaDebugSearchRangeSize = 64 * 1024 * 1024;
constexpr size_t kLuaDebugSearchChunkSize = 64 * 1024;

enum class LuaDebugFieldType {
    U8,
    U16,
    U32,
    I8,
    I16,
    I32,
    Float,
    Ptr,
};

#include "lua_engine_bindings_debug/helpers.inl"

#include "lua_engine_bindings_debug/functions.inl"

}  // namespace

void RegisterLuaDebugBindings(lua_State* state) {
    lua_createtable(state, 0, 60);
    RegisterFunction(state, &LuaDebugTraceFunction, "trace_function");
    RegisterFunction(state, &LuaDebugUntraceFunction, "untrace_function");
    RegisterFunction(state, &LuaDebugListTraces, "list_traces");
    RegisterFunction(state, &LuaDebugGetLastError, "get_last_error");
    RegisterFunction(state, &LuaDebugGetTraceHits, "get_trace_hits");
    RegisterFunction(state, &LuaDebugClearTraceHits, "clear_trace_hits");
    RegisterFunction(state, &LuaDebugWatch, "watch");
    RegisterFunction(state, &LuaDebugWatchWrite, "watch_write");
    RegisterFunction(state, &LuaDebugWatchWritePtrField, "watch_write_ptr_field");
    RegisterFunction(state, &LuaDebugGetWriteHits, "get_write_hits");
    RegisterFunction(state, &LuaDebugClearWriteHits, "clear_write_hits");
    RegisterFunction(state, &LuaDebugUnwatch, "unwatch");
    RegisterFunction(state, &LuaDebugListWatches, "list_watches");
    RegisterFunction(state, &LuaDebugWatchPtrField, "watch_ptr_field");
    RegisterFunction(state, &LuaDebugSnapshot, "snapshot");
    RegisterFunction(state, &LuaDebugSnapshotPtrField, "snapshot_ptr_field");
    RegisterFunction(state, &LuaDebugSnapshotNestedPtrField, "snapshot_nested_ptr_field");
    RegisterFunction(state, &LuaDebugSnapshotDoubleNestedPtrField, "snapshot_double_nested_ptr_field");
    RegisterFunction(state, &LuaDebugSnapshotPtrChain, "snapshot_ptr_chain");
    RegisterFunction(state, &LuaDebugSnapshotObjectPtrChain, "snapshot_object_ptr_chain");
    RegisterFunction(state, &LuaDebugDiff, "diff");
    RegisterFunction(state, &LuaDebugResolvePtrChain, "resolve_ptr_chain");
    RegisterFunction(state, &LuaDebugResolveObjectPtrChain, "resolve_object_ptr_chain");
    RegisterFunction(state, &LuaDebugDumpPtrChain, "dump_ptr_chain");
    RegisterFunction(state, &LuaDebugDumpObjectPtrChain, "dump_object_ptr_chain");
    RegisterFunction(state, &LuaDebugReadBytes, "read_bytes");
    RegisterFunction(state, &LuaDebugReadString, "read_string");
    RegisterFunction(state, &LuaDebugSearchBytes, "search_bytes");
    RegisterFunction(state, &LuaDebugResolveGameAddress, "resolve_game_address");
    RegisterFunction(state, &LuaDebugQueryMemory, "query_memory");
    RegisterFunction(state, &LuaDebugDumpStruct, "dump_struct");
    RegisterFunction(state, &LuaDebugDumpVtable, "dump_vtable");
    RegisterFunction(state, &LuaDebugReadPtr, "read_ptr");
    RegisterFunction(state, &LuaDebugReadPtrField, "read_ptr_field");
    RegisterFunction(state, &LuaDebugSwitchRegion, "switch_region");
    RegisterFunction(state, &LuaDebugReadU8, "read_u8");
    RegisterFunction(state, &LuaDebugReadI8, "read_i8");
    RegisterFunction(state, &LuaDebugReadI16, "read_i16");
    RegisterFunction(state, &LuaDebugReadU16, "read_u16");
    RegisterFunction(state, &LuaDebugReadU32, "read_u32");
    RegisterFunction(state, &LuaDebugReadI32, "read_i32");
    RegisterFunction(state, &LuaDebugReadFloat, "read_float");
    RegisterFunction(state, &LuaDebugWriteU8, "write_u8");
    RegisterFunction(state, &LuaDebugWriteI8, "write_i8");
    RegisterFunction(state, &LuaDebugWriteU16, "write_u16");
    RegisterFunction(state, &LuaDebugWriteI16, "write_i16");
    RegisterFunction(state, &LuaDebugWriteU32, "write_u32");
    RegisterFunction(state, &LuaDebugWriteI32, "write_i32");
    RegisterFunction(state, &LuaDebugWriteFloat, "write_float");
    RegisterFunction(state, &LuaDebugWritePtr, "write_ptr");
    RegisterFunction(state, &LuaDebugCallThiscallU32, "call_thiscall_u32");
    RegisterFunction(state, &LuaDebugCallThiscallU32RetU32, "call_thiscall_u32_ret_u32");
    RegisterFunction(state, &LuaDebugCallThiscallOutF32x4U32, "call_thiscall_out_f32x4_u32");
    RegisterFunction(state, &LuaDebugGetNavGrid, "get_nav_grid");
    RegisterFunction(state, &LuaDebugGetGameNpcMotion, "get_gamenpc_motion");
    RegisterFunction(state, &LuaDebugGetWorldMovementGeometry, "get_world_movement_geometry");
    RegisterFunction(state, &LuaDebugCallCdeclU32RetU32, "call_cdecl_u32_ret_u32");
    RegisterFunction(state, &LuaDebugCallCdeclU32U32, "call_cdecl_u32_u32");
    RegisterFunction(state, &LuaDebugCopyBytes, "copy_bytes");
    RegisterFunction(state, &LuaDebugReadFieldU8, "read_field_u8");
    RegisterFunction(state, &LuaDebugReadFieldU32, "read_field_u32");
    RegisterFunction(state, &LuaDebugReadFieldFloat, "read_field_float");
    RegisterFunction(state, &LuaDebugWriteFieldU8, "write_field_u8");
    RegisterFunction(state, &LuaDebugWriteFieldU32, "write_field_u32");
    RegisterFunction(state, &LuaDebugWriteFieldFloat, "write_field_float");
    lua_setfield(state, -2, "debug");
}

}  // namespace sdmod::detail
