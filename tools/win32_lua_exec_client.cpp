#define NOMINMAX
#include <Windows.h>

#include <fcntl.h>
#include <io.h>

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <limits>
#include <string>
#include <vector>

namespace {

constexpr DWORD kPipeTimeoutMs = 5000;
constexpr DWORD kPipeReconnectPollMs = 10;
constexpr DWORD kWineHandlesClosedError = 676;
constexpr std::size_t kMaximumRequestBytes = 1024 * 1024;

void PrintLastError(const char* operation) {
    std::fprintf(
        stderr,
        "%s failed with Win32 error %lu\n",
        operation,
        static_cast<unsigned long>(GetLastError()));
}

bool ReadExact(FILE* stream, void* destination, std::size_t size) {
    auto* bytes = static_cast<unsigned char*>(destination);
    while (size != 0) {
        const std::size_t read = std::fread(bytes, 1, size, stream);
        if (read == 0) {
            return false;
        }
        bytes += read;
        size -= read;
    }
    return true;
}

bool WriteExact(FILE* stream, const void* source, std::size_t size) {
    const auto* bytes = static_cast<const unsigned char*>(source);
    while (size != 0) {
        const std::size_t written = std::fwrite(bytes, 1, size, stream);
        if (written == 0) {
            return false;
        }
        bytes += written;
        size -= written;
    }
    return true;
}

bool IsTransientPipeOpenError(DWORD error) {
    return error == ERROR_FILE_NOT_FOUND ||
           error == ERROR_PIPE_BUSY ||
           error == ERROR_SEM_TIMEOUT ||
           error == ERROR_NO_DATA ||
           error == ERROR_BROKEN_PIPE ||
           error == kWineHandlesClosedError;
}

HANDLE OpenPipe(const std::string& pipe_name) {
    const ULONGLONG deadline = GetTickCount64() + kPipeTimeoutMs;
    DWORD last_error = ERROR_SUCCESS;
    for (;;) {
        const HANDLE pipe = CreateFileA(
            pipe_name.c_str(),
            GENERIC_READ | GENERIC_WRITE,
            0,
            nullptr,
            OPEN_EXISTING,
            0,
            nullptr);
        if (pipe != INVALID_HANDLE_VALUE) {
            return pipe;
        }

        last_error = GetLastError();
        const ULONGLONG now = GetTickCount64();
        if (!IsTransientPipeOpenError(last_error) || now >= deadline) {
            SetLastError(last_error);
            return INVALID_HANDLE_VALUE;
        }

        const DWORD remaining = static_cast<DWORD>(deadline - now);
        const DWORD wait = remaining < kPipeReconnectPollMs
            ? remaining
            : kPipeReconnectPollMs;
        if (wait != 0) {
            Sleep(wait);
        }
    }
}

bool ExecuteRequest(
    const std::string& pipe_name,
    const char* code,
    std::size_t code_size,
    std::vector<char>* response) {
    const HANDLE pipe = OpenPipe(pipe_name);
    if (pipe == INVALID_HANDLE_VALUE) {
        PrintLastError("OpenPipe");
        return false;
    }

    DWORD read_mode = PIPE_READMODE_MESSAGE;
    if (!SetNamedPipeHandleState(pipe, &read_mode, nullptr, nullptr)) {
        PrintLastError("SetNamedPipeHandleState");
        CloseHandle(pipe);
        return false;
    }

    if (code_size > std::numeric_limits<DWORD>::max()) {
        std::fprintf(stderr, "Lua request exceeds Win32 pipe size limit\n");
        CloseHandle(pipe);
        return false;
    }
    DWORD written = 0;
    const auto request_size = static_cast<DWORD>(code_size);
    if (!WriteFile(pipe, code, request_size, &written, nullptr) ||
        written != request_size) {
        PrintLastError("WriteFile");
        CloseHandle(pipe);
        return false;
    }

    response->clear();
    char buffer[4096];
    for (;;) {
        DWORD read = 0;
        const BOOL ok = ReadFile(pipe, buffer, sizeof(buffer), &read, nullptr);
        response->insert(response->end(), buffer, buffer + read);
        if (ok) {
            break;
        }
        if (GetLastError() != ERROR_MORE_DATA) {
            PrintLastError("ReadFile");
            CloseHandle(pipe);
            return false;
        }
    }
    CloseHandle(pipe);
    return true;
}

int RunDaemon(const std::string& pipe_name) {
    if (_setmode(_fileno(stdin), _O_BINARY) == -1 ||
        _setmode(_fileno(stdout), _O_BINARY) == -1) {
        std::fprintf(stderr, "failed to select binary stdio mode\n");
        return 9;
    }

    for (;;) {
        std::uint32_t request_size = 0;
        if (!ReadExact(stdin, &request_size, sizeof(request_size))) {
            return std::feof(stdin) ? 0 : 10;
        }
        if (request_size == 0 || request_size > kMaximumRequestBytes) {
            std::fprintf(stderr, "invalid daemon request size: %lu\n",
                         static_cast<unsigned long>(request_size));
            return 11;
        }

        std::vector<char> request(request_size);
        if (!ReadExact(stdin, request.data(), request.size())) {
            return 12;
        }
        std::vector<char> response;
        if (!ExecuteRequest(
                pipe_name, request.data(), request.size(), &response)) {
            return 13;
        }
        if (response.size() > std::numeric_limits<std::uint32_t>::max()) {
            std::fprintf(stderr, "Lua response exceeds daemon frame size\n");
            return 14;
        }
        const auto response_size = static_cast<std::uint32_t>(response.size());
        if (!WriteExact(stdout, &response_size, sizeof(response_size)) ||
            !WriteExact(stdout, response.data(), response.size()) ||
            std::fflush(stdout) != 0) {
            return 15;
        }
    }
}

}  // namespace

int main(int argc, char** argv) {
    if (argc != 3 || argv[1][0] == '\0' || argv[2][0] == '\0') {
        std::fprintf(
            stderr,
            "usage: win32_lua_exec_client <pipe-name> <lua-code|--daemon>\n");
        return 2;
    }

    std::string pipe_name = argv[1];
    constexpr char kPipePrefix[] = "\\\\.\\pipe\\";
    if (pipe_name.rfind(kPipePrefix, 0) != 0) {
        pipe_name.insert(0, kPipePrefix);
    }
    std::vector<char> response;
    if (std::strcmp(argv[2], "--daemon") == 0) {
        return RunDaemon(pipe_name);
    }
    if (!ExecuteRequest(
            pipe_name, argv[2], std::strlen(argv[2]), &response)) {
        return 3;
    }
    if (!response.empty() &&
        std::fwrite(response.data(), 1, response.size(), stdout) != response.size()) {
        return 4;
    }
    return 0;
}
