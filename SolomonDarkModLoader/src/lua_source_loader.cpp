#include "lua_source_loader.h"

extern "C" {
#include "lauxlib.h"
#include "lua.h"
}

#include <algorithm>
#include <limits>
#include <new>
#include <string>
#include <system_error>
#include <vector>
#include <Windows.h>

namespace sdmod::detail {
namespace {

constexpr DWORD kReadChunkBytes = 1024 * 1024;

class ScopedFileHandle {
public:
    explicit ScopedFileHandle(HANDLE handle) : handle_(handle) {}
    ~ScopedFileHandle() {
        if (handle_ != INVALID_HANDLE_VALUE) {
            CloseHandle(handle_);
        }
    }

    ScopedFileHandle(const ScopedFileHandle&) = delete;
    ScopedFileHandle& operator=(const ScopedFileHandle&) = delete;

    HANDLE get() const {
        return handle_;
    }

private:
    HANDLE handle_ = INVALID_HANDLE_VALUE;
};

std::string FormatWindowsError(DWORD error) {
    return std::error_code(
               static_cast<int>(error),
               std::system_category())
        .message();
}

bool TryBuildExtendedLengthPath(
    const std::filesystem::path& path,
    std::wstring* extended_path,
    std::string* error_message) {
    if (extended_path == nullptr || error_message == nullptr) {
        return false;
    }

    std::error_code filesystem_error;
    const auto absolute_path = path.is_absolute()
        ? path
        : std::filesystem::absolute(path, filesystem_error);
    if (filesystem_error) {
        *error_message =
            "could not resolve Lua source path: " +
            filesystem_error.message();
        return false;
    }

    auto native_path = absolute_path.lexically_normal().wstring();
    if (native_path.rfind(LR"(\\?\)", 0) == 0) {
        *extended_path = std::move(native_path);
        return true;
    }
    if (native_path.rfind(LR"(\\)", 0) == 0) {
        *extended_path = LR"(\\?\UNC\)" + native_path.substr(2);
        return true;
    }

    *extended_path = LR"(\\?\)" + native_path;
    return true;
}

bool TryReadSourceBytes(
    const std::filesystem::path& path,
    std::vector<char>* bytes,
    std::string* error_message) {
    if (bytes == nullptr || error_message == nullptr) {
        return false;
    }

    std::wstring extended_path;
    if (!TryBuildExtendedLengthPath(path, &extended_path, error_message)) {
        return false;
    }

    ScopedFileHandle file(CreateFileW(
        extended_path.c_str(),
        GENERIC_READ,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        nullptr,
        OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL | FILE_FLAG_SEQUENTIAL_SCAN,
        nullptr));
    if (file.get() == INVALID_HANDLE_VALUE) {
        *error_message =
            "could not open Lua source file: " +
            FormatWindowsError(GetLastError());
        return false;
    }

    LARGE_INTEGER file_size = {};
    if (!GetFileSizeEx(file.get(), &file_size)) {
        *error_message =
            "could not measure Lua source file: " +
            FormatWindowsError(GetLastError());
        return false;
    }
    if (file_size.QuadPart < 0 ||
        static_cast<unsigned long long>(file_size.QuadPart) >
            (std::numeric_limits<std::size_t>::max)()) {
        *error_message = "Lua source file is too large to load.";
        return false;
    }

    const auto source_size = static_cast<std::size_t>(file_size.QuadPart);
    if (source_size > bytes->max_size()) {
        *error_message = "Lua source file is too large to load.";
        return false;
    }
    try {
        bytes->assign(source_size, '\0');
    } catch (const std::bad_alloc&) {
        *error_message = "could not allocate memory for Lua source file.";
        return false;
    }

    std::size_t offset = 0;
    while (offset < bytes->size()) {
        const auto remaining = bytes->size() - offset;
        const auto requested = static_cast<DWORD>(
            std::min<std::size_t>(remaining, kReadChunkBytes));
        DWORD bytes_read = 0;
        if (!ReadFile(
                file.get(),
                bytes->data() + offset,
                requested,
                &bytes_read,
                nullptr)) {
            *error_message =
                "could not read Lua source file: " +
                FormatWindowsError(GetLastError());
            return false;
        }
        if (bytes_read == 0) {
            *error_message = "Lua source file ended before its reported size.";
            return false;
        }
        offset += bytes_read;
    }
    return true;
}

void PrepareLuaSource(
    const std::vector<char>& bytes,
    const char** source,
    std::size_t* source_size,
    std::string* adjusted_source) {
    std::size_t offset = 0;
    if (bytes.size() >= 3 &&
        static_cast<unsigned char>(bytes[0]) == 0xEF &&
        static_cast<unsigned char>(bytes[1]) == 0xBB &&
        static_cast<unsigned char>(bytes[2]) == 0xBF) {
        offset = 3;
    }

    if (offset < bytes.size() && bytes[offset] == '#') {
        const auto newline = std::find(
            bytes.begin() + static_cast<std::ptrdiff_t>(offset),
            bytes.end(),
            '\n');
        adjusted_source->assign(1, '\n');
        if (newline != bytes.end()) {
            adjusted_source->append(newline + 1, bytes.end());
        }
        *source = adjusted_source->data();
        *source_size = adjusted_source->size();
        return;
    }

    *source = bytes.empty() ? "" : bytes.data() + offset;
    *source_size = bytes.size() - offset;
}

}  // namespace

bool LoadLuaSourceFile(
    lua_State* state,
    const std::filesystem::path& path,
    std::string* error_message) {
    if (state == nullptr || error_message == nullptr) {
        return false;
    }
    error_message->clear();

    std::vector<char> bytes;
    if (!TryReadSourceBytes(path, &bytes, error_message)) {
        return false;
    }

    const char* source = nullptr;
    std::size_t source_size = 0;
    std::string adjusted_source;
    PrepareLuaSource(bytes, &source, &source_size, &adjusted_source);

    std::string chunk_name;
    try {
        chunk_name = "@" + path.u8string();
    } catch (const std::filesystem::filesystem_error& error) {
        *error_message =
            "could not encode Lua source path: " +
            std::string(error.what());
        return false;
    }

    if (luaL_loadbufferx(
            state,
            source,
            source_size,
            chunk_name.c_str(),
            nullptr) != LUA_OK) {
        const auto* lua_error = lua_tostring(state, -1);
        *error_message =
            lua_error == nullptr ? "unknown Lua load error" : lua_error;
        lua_pop(state, 1);
        return false;
    }
    return true;
}

}  // namespace sdmod::detail
