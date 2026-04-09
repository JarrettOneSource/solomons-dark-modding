#include "lua_engine_bindings_internal.h"
#include "memory_access.h"
#include "mod_loader.h"
#include "runtime_debug.h"

#include <limits>
#include <string>
#include <type_traits>

namespace sdmod::detail {
namespace {

constexpr size_t kMaxLuaDebugTransferSize = 1024 * 1024;

bool TryAddOffset(uintptr_t base_address, size_t offset, uintptr_t* result) {
    if (result == nullptr) {
        return false;
    }

    if (offset > static_cast<size_t>((std::numeric_limits<uintptr_t>::max)() - base_address)) {
        return false;
    }

    *result = base_address + offset;
    return true;
}

template <typename T>
T CheckLuaUnsignedInteger(lua_State* state, int index, const char* argument_name) {
    static_assert(std::is_integral_v<T> && std::is_unsigned_v<T>, "Expected an unsigned integer type.");

    const lua_Integer value = luaL_checkinteger(state, index);
    if (value < 0) {
        const std::string message = std::string(argument_name) + " must be non-negative";
        luaL_argerror(state, index, message.c_str());
        return 0;
    }

    using LuaUnsigned = std::make_unsigned_t<lua_Integer>;
    const auto unsigned_value = static_cast<LuaUnsigned>(value);
    if (unsigned_value > static_cast<LuaUnsigned>((std::numeric_limits<T>::max)())) {
        const std::string message = std::string(argument_name) + " is out of range";
        luaL_argerror(state, index, message.c_str());
        return 0;
    }

    return static_cast<T>(unsigned_value);
}

size_t CheckLuaTransferSize(lua_State* state, int index, const char* argument_name) {
    const size_t size = CheckLuaUnsignedInteger<size_t>(state, index, argument_name);
    if (size == 0) {
        const std::string message = std::string(argument_name) + " must be greater than zero";
        luaL_argerror(state, index, message.c_str());
        return 0;
    }

    if (size > kMaxLuaDebugTransferSize) {
        const std::string message =
            std::string(argument_name) + " exceeds the maximum allowed size of " +
            std::to_string(kMaxLuaDebugTransferSize) + " bytes";
        luaL_argerror(state, index, message.c_str());
        return 0;
    }

    return size;
}

uintptr_t CheckLuaAddress(lua_State* state, int index, const char* argument_name) {
    return CheckLuaUnsignedInteger<uintptr_t>(state, index, argument_name);
}

size_t CheckLuaOffset(lua_State* state, int index, const char* argument_name) {
    return CheckLuaUnsignedInteger<size_t>(state, index, argument_name);
}

uintptr_t ResolveReadableLuaAddress(ProcessMemory& memory, uintptr_t address, size_t size) {
    return memory.IsReadableRange(address, size)
        ? address
        : memory.ResolveGameAddressOrZero(address);
}

uintptr_t ResolveWritableLuaAddress(ProcessMemory& memory, uintptr_t address, size_t size) {
    return memory.IsWritableRange(address, size)
        ? address
        : memory.ResolveGameAddressOrZero(address);
}

template <typename T>
bool TryReadLuaAbsoluteValue(uintptr_t address, T* value) {
    auto& memory = ProcessMemory::Instance();
    const auto resolved_address = ResolveReadableLuaAddress(memory, address, sizeof(T));
    if (resolved_address == 0) {
        return false;
    }

    return memory.TryReadValue(resolved_address, value);
}

template <typename T>
bool TryReadLuaFieldValue(uintptr_t ptr_address, size_t offset, T* value) {
    auto& memory = ProcessMemory::Instance();
    const auto resolved_ptr_address = ResolveReadableLuaAddress(memory, ptr_address, sizeof(uintptr_t));
    if (resolved_ptr_address == 0) {
        return false;
    }

    uintptr_t base_address = 0;
    if (!memory.TryReadValue(resolved_ptr_address, &base_address) || base_address == 0) {
        return false;
    }

    uintptr_t field_address = 0;
    if (!TryAddOffset(base_address, offset, &field_address)) {
        return false;
    }

    const auto resolved_field_address = ResolveReadableLuaAddress(memory, field_address, sizeof(T));
    if (resolved_field_address == 0) {
        return false;
    }

    return memory.TryReadValue(resolved_field_address, value);
}

template <typename T>
bool TryWriteLuaAbsoluteValue(uintptr_t address, const T& value) {
    auto& memory = ProcessMemory::Instance();
    const auto resolved_address = ResolveWritableLuaAddress(memory, address, sizeof(T));
    if (resolved_address == 0) {
        return false;
    }

    return memory.TryWriteValue(resolved_address, value);
}

template <typename T>
bool TryWriteLuaFieldValue(uintptr_t ptr_address, size_t offset, const T& value) {
    auto& memory = ProcessMemory::Instance();
    const auto resolved_ptr_address = ResolveReadableLuaAddress(memory, ptr_address, sizeof(uintptr_t));
    if (resolved_ptr_address == 0) {
        return false;
    }

    uintptr_t base_address = 0;
    if (!memory.TryReadValue(resolved_ptr_address, &base_address) || base_address == 0) {
        return false;
    }

    uintptr_t field_address = 0;
    if (!TryAddOffset(base_address, offset, &field_address)) {
        return false;
    }

    const auto resolved_field_address = ResolveWritableLuaAddress(memory, field_address, sizeof(T));
    if (resolved_field_address == 0) {
        return false;
    }

    return memory.TryWriteValue(resolved_field_address, value);
}

// sd.debug.trace_function(address, name) -> bool
int LuaDebugTraceFunction(lua_State* state) {
    const auto address = CheckLuaAddress(state, 1, "address");
    const char* name = luaL_checkstring(state, 2);
    const bool ok = RuntimeDebug_TraceFunction(address, name);
    lua_pushboolean(state, ok ? 1 : 0);
    return 1;
}

// sd.debug.untrace_function(address)
int LuaDebugUntraceFunction(lua_State* state) {
    const auto address = CheckLuaAddress(state, 1, "address");
    RuntimeDebug_UntraceFunction(address);
    return 0;
}

// sd.debug.watch(address, size, name)
int LuaDebugWatch(lua_State* state) {
    const auto address = CheckLuaAddress(state, 1, "address");
    const auto size = CheckLuaTransferSize(state, 2, "size");
    const char* name = luaL_checkstring(state, 3);
    RuntimeDebug_WatchMemory(address, size, name);
    return 0;
}

// sd.debug.watch_ptr_field(ptr_address, offset, size, name)
int LuaDebugWatchPtrField(lua_State* state) {
    const auto ptr_address = CheckLuaAddress(state, 1, "ptr_address");
    const auto offset = CheckLuaOffset(state, 2, "offset");
    const auto size = CheckLuaTransferSize(state, 3, "size");
    const char* name = luaL_checkstring(state, 4);
    RuntimeDebug_WatchPtrField(ptr_address, offset, size, name);
    return 0;
}

// sd.debug.snapshot(name, address, size)
int LuaDebugSnapshot(lua_State* state) {
    const char* name = luaL_checkstring(state, 1);
    const auto address = CheckLuaAddress(state, 2, "address");
    const auto size = CheckLuaTransferSize(state, 3, "size");
    RuntimeDebug_Snapshot(name, address, size);
    return 0;
}

// sd.debug.snapshot_ptr_field(name, ptr_address, offset, size)
int LuaDebugSnapshotPtrField(lua_State* state) {
    const char* name = luaL_checkstring(state, 1);
    const auto ptr_address = CheckLuaAddress(state, 2, "ptr_address");
    const auto offset = CheckLuaOffset(state, 3, "offset");
    const auto size = CheckLuaTransferSize(state, 4, "size");
    RuntimeDebug_SnapshotPtrField(name, ptr_address, offset, size);
    return 0;
}

// sd.debug.snapshot_nested_ptr_field(name, ptr_address, outer_offset, inner_offset, size)
int LuaDebugSnapshotNestedPtrField(lua_State* state) {
    const char* name = luaL_checkstring(state, 1);
    const auto ptr_address = CheckLuaAddress(state, 2, "ptr_address");
    const auto outer_offset = CheckLuaOffset(state, 3, "outer_offset");
    const auto inner_offset = CheckLuaOffset(state, 4, "inner_offset");
    const auto size = CheckLuaTransferSize(state, 5, "size");
    RuntimeDebug_SnapshotNestedPtrField(name, ptr_address, outer_offset, inner_offset, size);
    return 0;
}

// sd.debug.snapshot_double_nested_ptr_field(name, ptr_address, outer_offset, middle_offset, inner_offset, size)
int LuaDebugSnapshotDoubleNestedPtrField(lua_State* state) {
    const char* name = luaL_checkstring(state, 1);
    const auto ptr_address = CheckLuaAddress(state, 2, "ptr_address");
    const auto outer_offset = CheckLuaOffset(state, 3, "outer_offset");
    const auto middle_offset = CheckLuaOffset(state, 4, "middle_offset");
    const auto inner_offset = CheckLuaOffset(state, 5, "inner_offset");
    const auto size = CheckLuaTransferSize(state, 6, "size");
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
    const auto address = CheckLuaAddress(state, 1, "address");
    uintptr_t value = 0;
    if (!TryReadLuaAbsoluteValue(address, &value)) {
        lua_pushnil(state);
        return 1;
    }

    lua_pushinteger(state, static_cast<lua_Integer>(value));
    return 1;
}

// sd.debug.read_ptr_field(ptr_address, offset) -> integer|nil
int LuaDebugReadPtrField(lua_State* state) {
    const auto ptr_address = CheckLuaAddress(state, 1, "ptr_address");
    const auto offset = CheckLuaOffset(state, 2, "offset");
    uintptr_t value = 0;
    if (!TryReadLuaFieldValue(ptr_address, offset, &value)) {
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

int LuaDebugReadU8(lua_State* state) {
    const auto address = CheckLuaAddress(state, 1, "address");
    std::uint8_t value = 0;
    if (!TryReadLuaAbsoluteValue(address, &value)) {
        lua_pushnil(state);
        return 1;
    }

    lua_pushinteger(state, static_cast<lua_Integer>(value));
    return 1;
}

int LuaDebugReadU32(lua_State* state) {
    const auto address = CheckLuaAddress(state, 1, "address");
    std::uint32_t value = 0;
    if (!TryReadLuaAbsoluteValue(address, &value)) {
        lua_pushnil(state);
        return 1;
    }

    lua_pushinteger(state, static_cast<lua_Integer>(value));
    return 1;
}

int LuaDebugReadFloat(lua_State* state) {
    const auto address = CheckLuaAddress(state, 1, "address");
    float value = 0.0f;
    if (!TryReadLuaAbsoluteValue(address, &value)) {
        lua_pushnil(state);
        return 1;
    }

    lua_pushnumber(state, static_cast<lua_Number>(value));
    return 1;
}

int LuaDebugWriteU8(lua_State* state) {
    const auto address = CheckLuaAddress(state, 1, "address");
    const auto value = CheckLuaUnsignedInteger<std::uint8_t>(state, 2, "value");
    lua_pushboolean(state, TryWriteLuaAbsoluteValue(address, value) ? 1 : 0);
    return 1;
}

int LuaDebugWriteU16(lua_State* state) {
    const auto address = CheckLuaAddress(state, 1, "address");
    const auto value = CheckLuaUnsignedInteger<std::uint16_t>(state, 2, "value");
    lua_pushboolean(state, TryWriteLuaAbsoluteValue(address, value) ? 1 : 0);
    return 1;
}

int LuaDebugWriteU32(lua_State* state) {
    const auto address = CheckLuaAddress(state, 1, "address");
    const auto value = CheckLuaUnsignedInteger<std::uint32_t>(state, 2, "value");
    lua_pushboolean(state, TryWriteLuaAbsoluteValue(address, value) ? 1 : 0);
    return 1;
}

int LuaDebugWriteFloat(lua_State* state) {
    const auto address = CheckLuaAddress(state, 1, "address");
    const auto value = static_cast<float>(luaL_checknumber(state, 2));
    lua_pushboolean(state, TryWriteLuaAbsoluteValue(address, value) ? 1 : 0);
    return 1;
}

int LuaDebugWritePtr(lua_State* state) {
    const auto address = CheckLuaAddress(state, 1, "address");
    const auto value = CheckLuaAddress(state, 2, "value");
    lua_pushboolean(state, TryWriteLuaAbsoluteValue(address, value) ? 1 : 0);
    return 1;
}

int LuaDebugReadFieldU8(lua_State* state) {
    const auto ptr_address = CheckLuaAddress(state, 1, "ptr_address");
    const auto offset = CheckLuaOffset(state, 2, "offset");
    std::uint8_t value = 0;
    if (!TryReadLuaFieldValue(ptr_address, offset, &value)) {
        lua_pushnil(state);
        return 1;
    }

    lua_pushinteger(state, static_cast<lua_Integer>(value));
    return 1;
}

int LuaDebugReadFieldU32(lua_State* state) {
    const auto ptr_address = CheckLuaAddress(state, 1, "ptr_address");
    const auto offset = CheckLuaOffset(state, 2, "offset");
    std::uint32_t value = 0;
    if (!TryReadLuaFieldValue(ptr_address, offset, &value)) {
        lua_pushnil(state);
        return 1;
    }

    lua_pushinteger(state, static_cast<lua_Integer>(value));
    return 1;
}

int LuaDebugReadFieldFloat(lua_State* state) {
    const auto ptr_address = CheckLuaAddress(state, 1, "ptr_address");
    const auto offset = CheckLuaOffset(state, 2, "offset");
    float value = 0.0f;
    if (!TryReadLuaFieldValue(ptr_address, offset, &value)) {
        lua_pushnil(state);
        return 1;
    }

    lua_pushnumber(state, static_cast<lua_Number>(value));
    return 1;
}

int LuaDebugWriteFieldU8(lua_State* state) {
    const auto ptr_address = CheckLuaAddress(state, 1, "ptr_address");
    const auto offset = CheckLuaOffset(state, 2, "offset");
    const auto value = CheckLuaUnsignedInteger<std::uint8_t>(state, 3, "value");
    lua_pushboolean(state, TryWriteLuaFieldValue(ptr_address, offset, value) ? 1 : 0);
    return 1;
}

int LuaDebugWriteFieldU32(lua_State* state) {
    const auto ptr_address = CheckLuaAddress(state, 1, "ptr_address");
    const auto offset = CheckLuaOffset(state, 2, "offset");
    const auto value = CheckLuaUnsignedInteger<std::uint32_t>(state, 3, "value");
    lua_pushboolean(state, TryWriteLuaFieldValue(ptr_address, offset, value) ? 1 : 0);
    return 1;
}

int LuaDebugWriteFieldFloat(lua_State* state) {
    const auto ptr_address = CheckLuaAddress(state, 1, "ptr_address");
    const auto offset = CheckLuaOffset(state, 2, "offset");
    const auto value = static_cast<float>(luaL_checknumber(state, 3));
    lua_pushboolean(state, TryWriteLuaFieldValue(ptr_address, offset, value) ? 1 : 0);
    return 1;
}

}  // namespace

void RegisterLuaDebugBindings(lua_State* state) {
    lua_createtable(state, 0, 30);
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
    RegisterFunction(state, &LuaDebugReadU8, "read_u8");
    RegisterFunction(state, &LuaDebugReadU32, "read_u32");
    RegisterFunction(state, &LuaDebugReadFloat, "read_float");
    RegisterFunction(state, &LuaDebugWriteU8, "write_u8");
    RegisterFunction(state, &LuaDebugWriteU16, "write_u16");
    RegisterFunction(state, &LuaDebugWriteU32, "write_u32");
    RegisterFunction(state, &LuaDebugWriteFloat, "write_float");
    RegisterFunction(state, &LuaDebugWritePtr, "write_ptr");
    RegisterFunction(state, &LuaDebugReadFieldU8, "read_field_u8");
    RegisterFunction(state, &LuaDebugReadFieldU32, "read_field_u32");
    RegisterFunction(state, &LuaDebugReadFieldFloat, "read_field_float");
    RegisterFunction(state, &LuaDebugWriteFieldU8, "write_field_u8");
    RegisterFunction(state, &LuaDebugWriteFieldU32, "write_field_u32");
    RegisterFunction(state, &LuaDebugWriteFieldFloat, "write_field_float");
    lua_setfield(state, -2, "debug");
}

}  // namespace sdmod::detail
