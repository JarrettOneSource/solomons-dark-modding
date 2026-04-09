#include "lua_engine_bindings_internal.h"
#include "memory_access.h"
#include "mod_loader.h"
#include "runtime_debug.h"

namespace sdmod::detail {
namespace {

// sd.debug.trace_function(address, name) -> bool
int LuaDebugTraceFunction(lua_State* state) {
    const auto address = static_cast<uintptr_t>(luaL_checkinteger(state, 1));
    const char* name = luaL_checkstring(state, 2);
    const bool ok = RuntimeDebug_TraceFunction(address, name);
    lua_pushboolean(state, ok ? 1 : 0);
    return 1;
}

// sd.debug.untrace_function(address)
int LuaDebugUntraceFunction(lua_State* state) {
    const auto address = static_cast<uintptr_t>(luaL_checkinteger(state, 1));
    RuntimeDebug_UntraceFunction(address);
    return 0;
}

// sd.debug.watch(address, size, name)
int LuaDebugWatch(lua_State* state) {
    const auto address = static_cast<uintptr_t>(luaL_checkinteger(state, 1));
    const auto size = static_cast<size_t>(luaL_checkinteger(state, 2));
    const char* name = luaL_checkstring(state, 3);
    RuntimeDebug_WatchMemory(address, size, name);
    return 0;
}

// sd.debug.watch_ptr_field(ptr_address, offset, size, name)
int LuaDebugWatchPtrField(lua_State* state) {
    const auto ptr_address = static_cast<uintptr_t>(luaL_checkinteger(state, 1));
    const auto offset = static_cast<size_t>(luaL_checkinteger(state, 2));
    const auto size = static_cast<size_t>(luaL_checkinteger(state, 3));
    const char* name = luaL_checkstring(state, 4);
    RuntimeDebug_WatchPtrField(ptr_address, offset, size, name);
    return 0;
}

// sd.debug.snapshot(name, address, size)
int LuaDebugSnapshot(lua_State* state) {
    const char* name = luaL_checkstring(state, 1);
    const auto address = static_cast<uintptr_t>(luaL_checkinteger(state, 2));
    const auto size = static_cast<size_t>(luaL_checkinteger(state, 3));
    RuntimeDebug_Snapshot(name, address, size);
    return 0;
}

// sd.debug.snapshot_ptr_field(name, ptr_address, offset, size)
int LuaDebugSnapshotPtrField(lua_State* state) {
    const char* name = luaL_checkstring(state, 1);
    const auto ptr_address = static_cast<uintptr_t>(luaL_checkinteger(state, 2));
    const auto offset = static_cast<size_t>(luaL_checkinteger(state, 3));
    const auto size = static_cast<size_t>(luaL_checkinteger(state, 4));
    RuntimeDebug_SnapshotPtrField(name, ptr_address, offset, size);
    return 0;
}

// sd.debug.snapshot_nested_ptr_field(name, ptr_address, outer_offset, inner_offset, size)
int LuaDebugSnapshotNestedPtrField(lua_State* state) {
    const char* name = luaL_checkstring(state, 1);
    const auto ptr_address = static_cast<uintptr_t>(luaL_checkinteger(state, 2));
    const auto outer_offset = static_cast<size_t>(luaL_checkinteger(state, 3));
    const auto inner_offset = static_cast<size_t>(luaL_checkinteger(state, 4));
    const auto size = static_cast<size_t>(luaL_checkinteger(state, 5));
    RuntimeDebug_SnapshotNestedPtrField(name, ptr_address, outer_offset, inner_offset, size);
    return 0;
}

// sd.debug.snapshot_double_nested_ptr_field(name, ptr_address, outer_offset, middle_offset, inner_offset, size)
int LuaDebugSnapshotDoubleNestedPtrField(lua_State* state) {
    const char* name = luaL_checkstring(state, 1);
    const auto ptr_address = static_cast<uintptr_t>(luaL_checkinteger(state, 2));
    const auto outer_offset = static_cast<size_t>(luaL_checkinteger(state, 3));
    const auto middle_offset = static_cast<size_t>(luaL_checkinteger(state, 4));
    const auto inner_offset = static_cast<size_t>(luaL_checkinteger(state, 5));
    const auto size = static_cast<size_t>(luaL_checkinteger(state, 6));
    RuntimeDebug_SnapshotDoubleNestedPtrField(
        name,
        ptr_address,
        outer_offset,
        middle_offset,
        inner_offset,
        size);
    return 0;
}

// sd.debug.diff(name_a, name_b)
int LuaDebugDiff(lua_State* state) {
    const char* name_a = luaL_checkstring(state, 1);
    const char* name_b = luaL_checkstring(state, 2);
    RuntimeDebug_DiffSnapshots(name_a, name_b);
    return 0;
}

// sd.debug.read_ptr(address) -> integer|nil
int LuaDebugReadPtr(lua_State* state) {
    const auto address = static_cast<uintptr_t>(luaL_checkinteger(state, 1));
    auto& memory = ProcessMemory::Instance();
    const auto resolved_address = memory.IsReadableRange(address, sizeof(uintptr_t))
        ? address
        : memory.ResolveGameAddressOrZero(address);
    if (resolved_address == 0) {
        lua_pushnil(state);
        return 1;
    }

    uintptr_t value = 0;
    if (!memory.TryReadValue(resolved_address, &value)) {
        lua_pushnil(state);
        return 1;
    }

    lua_pushinteger(state, static_cast<lua_Integer>(value));
    return 1;
}

// sd.debug.read_ptr_field(ptr_address, offset) -> integer|nil
int LuaDebugReadPtrField(lua_State* state) {
    const auto ptr_address = static_cast<uintptr_t>(luaL_checkinteger(state, 1));
    const auto offset = static_cast<size_t>(luaL_checkinteger(state, 2));
    auto& memory = ProcessMemory::Instance();
    const auto resolved_ptr_address = memory.IsReadableRange(ptr_address, sizeof(uintptr_t))
        ? ptr_address
        : memory.ResolveGameAddressOrZero(ptr_address);
    if (resolved_ptr_address == 0) {
        lua_pushnil(state);
        return 1;
    }

    uintptr_t base_address = 0;
    if (!memory.TryReadValue(resolved_ptr_address, &base_address) || base_address == 0) {
        lua_pushnil(state);
        return 1;
    }

    uintptr_t value = 0;
    if (!memory.TryReadValue(base_address + offset, &value)) {
        lua_pushnil(state);
        return 1;
    }

    lua_pushinteger(state, static_cast<lua_Integer>(value));
    return 1;
}

// sd.debug.switch_region(region_index)
int LuaDebugSwitchRegion(lua_State* state) {
    const auto region_index = static_cast<int>(luaL_checkinteger(state, 1));
    std::string error_message;
    if (!QueueGameplaySwitchRegion(region_index, &error_message)) {
        return luaL_error(state, "sd.debug.switch_region failed: %s", error_message.c_str());
    }

    lua_pushboolean(state, 1);
    return 1;
}

}  // namespace

void RegisterLuaDebugBindings(lua_State* state) {
    lua_createtable(state, 0, 12);
    RegisterFunction(state, &LuaDebugTraceFunction, "trace_function");
    RegisterFunction(state, &LuaDebugUntraceFunction, "untrace_function");
    RegisterFunction(state, &LuaDebugWatch, "watch");
    RegisterFunction(state, &LuaDebugWatchPtrField, "watch_ptr_field");
    RegisterFunction(state, &LuaDebugSnapshot, "snapshot");
    RegisterFunction(state, &LuaDebugSnapshotPtrField, "snapshot_ptr_field");
    RegisterFunction(state, &LuaDebugSnapshotNestedPtrField, "snapshot_nested_ptr_field");
    RegisterFunction(state, &LuaDebugSnapshotDoubleNestedPtrField, "snapshot_double_nested_ptr_field");
    RegisterFunction(state, &LuaDebugDiff, "diff");
    RegisterFunction(state, &LuaDebugReadPtr, "read_ptr");
    RegisterFunction(state, &LuaDebugReadPtrField, "read_ptr_field");
    RegisterFunction(state, &LuaDebugSwitchRegion, "switch_region");
    lua_setfield(state, -2, "debug");
}

}  // namespace sdmod::detail
