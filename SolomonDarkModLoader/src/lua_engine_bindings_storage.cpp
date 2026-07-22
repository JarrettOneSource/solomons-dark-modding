#include "lua_engine_bindings_internal.h"

#include "lua_engine_values.h"

#include <Windows.h>

#include <cstdint>
#include <filesystem>
#include <fstream>
#include <string>
#include <system_error>
#include <utility>
#include <vector>

namespace sdmod::detail {
namespace {

constexpr wchar_t kProfileStorageFileName[] = L"profile-storage.bin";

void SetStorageError(std::string* error_message, const std::string& message) {
    if (error_message != nullptr) {
        *error_message = message;
    }
}

LoadedLuaMod* RequireStorageMod(lua_State* state, const char* api_name) {
    auto* mod = GetLoadedLuaMod(state);
    if (mod == nullptr) {
        luaL_error(state, "%s is unavailable", api_name);
    }
    return mod;
}

std::string ReadStorageKey(
    lua_State* state,
    int index,
    const char* api_name) {
    std::size_t length = 0;
    const char* text = luaL_checklstring(state, index, &length);
    std::string key(text, length);
    if (!IsValidLuaModStateKey(key)) {
        luaL_error(state, "%s key must be nonempty bounded text", api_name);
    }
    return key;
}

bool ContainsNilValue(const LuaModValue& value) {
    if (value.type == LuaModValueType::Nil) {
        return true;
    }
    if (value.type == LuaModValueType::Array) {
        for (const auto& element : value.array_value) {
            if (ContainsNilValue(element)) {
                return true;
            }
        }
    } else if (value.type == LuaModValueType::Object) {
        for (const auto& [key, field_value] : value.object_value) {
            (void)key;
            if (ContainsNilValue(field_value)) {
                return true;
            }
        }
    }
    return false;
}

std::filesystem::path ProfileStoragePath(const LoadedLuaMod& mod) {
    return mod.descriptor.data_root_path / kProfileStorageFileName;
}

bool EncodeProfileStorage(
    const LoadedLuaMod& mod,
    const LuaModStateValues& values,
    std::vector<std::uint8_t>* encoded,
    std::string* error_message) {
    LuaModStateSnapshot snapshot;
    if (!values.empty()) {
        snapshot.emplace(mod.descriptor.id, values);
    }
    return EncodeLuaModStateSnapshot(snapshot, encoded, error_message);
}

bool PersistProfileStorage(
    const LoadedLuaMod& mod,
    const LuaModStateValues& values,
    std::string* error_message) {
    if (mod.descriptor.data_root_path.empty()) {
        SetStorageError(error_message, "profile storage root is unavailable");
        return false;
    }

    std::vector<std::uint8_t> encoded;
    if (!EncodeProfileStorage(mod, values, &encoded, error_message)) {
        return false;
    }

    std::error_code filesystem_error;
    std::filesystem::create_directories(
        mod.descriptor.data_root_path,
        filesystem_error);
    if (filesystem_error) {
        SetStorageError(
            error_message,
            "profile storage directory could not be created: " +
                filesystem_error.message());
        return false;
    }

    const auto storage_path = ProfileStoragePath(mod);
    auto temporary_path = storage_path;
    temporary_path += L".tmp";
    {
        std::ofstream stream(
            temporary_path,
            std::ios::binary | std::ios::trunc);
        if (!stream) {
            SetStorageError(
                error_message,
                "profile storage temporary file could not be opened");
            return false;
        }
        stream.write(
            reinterpret_cast<const char*>(encoded.data()),
            static_cast<std::streamsize>(encoded.size()));
        stream.flush();
        if (!stream) {
            stream.close();
            std::filesystem::remove(temporary_path, filesystem_error);
            SetStorageError(
                error_message,
                "profile storage temporary file could not be written");
            return false;
        }
    }

    if (!::MoveFileExW(
            temporary_path.c_str(),
            storage_path.c_str(),
            MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)) {
        const auto error_code = ::GetLastError();
        std::filesystem::remove(temporary_path, filesystem_error);
        SetStorageError(
            error_message,
            "profile storage publish failed with Win32 error " +
                std::to_string(error_code));
        return false;
    }
    return true;
}

bool EnsureProfileStorageLoaded(
    LoadedLuaMod* mod,
    std::string* error_message) {
    if (mod == nullptr) {
        SetStorageError(error_message, "profile storage mod is unavailable");
        return false;
    }
    if (mod->profile_storage_loaded) {
        return true;
    }
    if (mod->descriptor.data_root_path.empty()) {
        SetStorageError(error_message, "profile storage root is unavailable");
        return false;
    }

    const auto storage_path = ProfileStoragePath(*mod);
    std::error_code filesystem_error;
    const bool exists = std::filesystem::exists(storage_path, filesystem_error);
    if (filesystem_error) {
        SetStorageError(
            error_message,
            "profile storage file could not be inspected: " +
                filesystem_error.message());
        return false;
    }
    if (!exists) {
        mod->profile_storage_values.clear();
        mod->profile_storage_loaded = true;
        return true;
    }

    const auto file_size = std::filesystem::file_size(
        storage_path,
        filesystem_error);
    if (filesystem_error || file_size == 0 ||
        file_size > kLuaModMaxStateSnapshotBytes) {
        SetStorageError(
            error_message,
            "profile storage file is empty, unreadable, or oversized");
        return false;
    }

    std::vector<std::uint8_t> encoded(static_cast<std::size_t>(file_size));
    std::ifstream stream(storage_path, std::ios::binary);
    if (!stream ||
        !stream.read(
            reinterpret_cast<char*>(encoded.data()),
            static_cast<std::streamsize>(encoded.size()))) {
        SetStorageError(error_message, "profile storage file could not be read");
        return false;
    }

    LuaModStateSnapshot snapshot;
    if (!DecodeLuaModStateSnapshot(
            encoded.data(),
            encoded.size(),
            &snapshot,
            error_message)) {
        return false;
    }
    if (snapshot.size() > 1 ||
        (!snapshot.empty() && snapshot.begin()->first != mod->descriptor.id)) {
        SetStorageError(
            error_message,
            "profile storage file belongs to a different mod");
        return false;
    }

    mod->profile_storage_values = snapshot.empty()
        ? LuaModStateValues{}
        : std::move(snapshot.begin()->second);
    mod->profile_storage_loaded = true;
    return true;
}

int LuaStorageGet(lua_State* state) {
    auto* mod = RequireStorageMod(state, "sd.storage.get");
    const auto key = ReadStorageKey(state, 1, "sd.storage.get");
    std::string error_message;
    if (!EnsureProfileStorageLoaded(mod, &error_message)) {
        return luaL_error(state, "%s", error_message.c_str());
    }
    const auto entry = mod->profile_storage_values.find(key);
    if (entry != mod->profile_storage_values.end()) {
        PushLuaModValue(state, entry->second);
    } else if (lua_gettop(state) >= 2) {
        lua_pushvalue(state, 2);
    } else {
        lua_pushnil(state);
    }
    return 1;
}

int LuaStorageSet(lua_State* state) {
    auto* mod = RequireStorageMod(state, "sd.storage.set");
    const auto key = ReadStorageKey(state, 1, "sd.storage.set");
    luaL_checkany(state, 2);
    std::string error_message;
    if (!EnsureProfileStorageLoaded(mod, &error_message)) {
        return luaL_error(state, "%s", error_message.c_str());
    }

    LuaModValue value;
    if (!ReadLuaModValue(state, 2, &value, &error_message)) {
        return luaL_error(state, "%s", error_message.c_str());
    }
    if (ContainsNilValue(value)) {
        return luaL_error(
            state,
            "profile storage values cannot contain nil; delete the key instead");
    }

    auto next = mod->profile_storage_values;
    next[key] = std::move(value);
    if (!PersistProfileStorage(*mod, next, &error_message)) {
        return luaL_error(state, "%s", error_message.c_str());
    }
    mod->profile_storage_values = std::move(next);
    lua_pushboolean(state, 1);
    return 1;
}

int LuaStorageDelete(lua_State* state) {
    auto* mod = RequireStorageMod(state, "sd.storage.delete");
    const auto key = ReadStorageKey(state, 1, "sd.storage.delete");
    std::string error_message;
    if (!EnsureProfileStorageLoaded(mod, &error_message)) {
        return luaL_error(state, "%s", error_message.c_str());
    }
    if (mod->profile_storage_values.find(key) ==
        mod->profile_storage_values.end()) {
        lua_pushboolean(state, 0);
        return 1;
    }

    auto next = mod->profile_storage_values;
    next.erase(key);
    if (!PersistProfileStorage(*mod, next, &error_message)) {
        return luaL_error(state, "%s", error_message.c_str());
    }
    mod->profile_storage_values = std::move(next);
    lua_pushboolean(state, 1);
    return 1;
}

int LuaStorageClear(lua_State* state) {
    auto* mod = RequireStorageMod(state, "sd.storage.clear");
    std::string error_message;
    if (!EnsureProfileStorageLoaded(mod, &error_message)) {
        return luaL_error(state, "%s", error_message.c_str());
    }
    if (mod->profile_storage_values.empty()) {
        lua_pushboolean(state, 0);
        return 1;
    }

    LuaModStateValues next;
    if (!PersistProfileStorage(*mod, next, &error_message)) {
        return luaL_error(state, "%s", error_message.c_str());
    }
    mod->profile_storage_values.clear();
    lua_pushboolean(state, 1);
    return 1;
}

int LuaStorageSnapshot(lua_State* state) {
    auto* mod = RequireStorageMod(state, "sd.storage.snapshot");
    std::string error_message;
    if (!EnsureProfileStorageLoaded(mod, &error_message)) {
        return luaL_error(state, "%s", error_message.c_str());
    }

    lua_createtable(
        state,
        0,
        static_cast<int>(mod->profile_storage_values.size()));
    for (const auto& [key, value] : mod->profile_storage_values) {
        lua_pushlstring(state, key.data(), key.size());
        PushLuaModValue(state, value);
        lua_settable(state, -3);
    }
    return 1;
}

}  // namespace

void RegisterLuaStorageBindings(lua_State* state) {
    lua_createtable(state, 0, 5);
    RegisterFunction(state, &LuaStorageGet, "get");
    RegisterFunction(state, &LuaStorageSet, "set");
    RegisterFunction(state, &LuaStorageDelete, "delete");
    RegisterFunction(state, &LuaStorageClear, "clear");
    RegisterFunction(state, &LuaStorageSnapshot, "snapshot");
    lua_setfield(state, -2, "storage");
}

}  // namespace sdmod::detail
