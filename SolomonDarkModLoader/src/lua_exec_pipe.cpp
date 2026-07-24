#include "lua_exec_pipe.h"

#include "logger.h"
#include "lua_engine.h"

#include <Windows.h>
#include <process.h>

#include <atomic>
#include <cstdint>
#include <limits>
#include <sstream>
#include <string>
#include <string_view>
#include <vector>

namespace sdmod {
namespace {

constexpr wchar_t kDefaultPipeName[] = L"\\\\.\\pipe\\SolomonDarkModLoader_LuaExec";
constexpr wchar_t kPipeNamePrefix[] = L"\\\\.\\pipe\\";
constexpr wchar_t kPipeNameEnvironmentVariable[] = L"SDMOD_LUA_EXEC_PIPE_NAME";
constexpr DWORD kPipeBufferSize = 64 * 1024;
constexpr DWORD kPipeReconnectDelayMs = 250;
constexpr size_t kMaxPipeMessageSize = 1024 * 1024;
// Stock scene construction can block every game-thread pump for several
// seconds. This is a hang backstop, not a frame budget; pump-generation checks
// in the Lua engine detect a running pump that actually skips queued work.
constexpr std::uint32_t kLuaExecHangBackstopMs = 30000;

std::atomic<bool> g_pipe_running = false;
HANDLE g_pipe_thread = nullptr;
HANDLE g_pipe_stop_event = nullptr;

enum class PipeReadStatus {
    Success,
    ClientDisconnected,
    MessageTooLarge,
    Error,
};

std::string FormatWindowsError(DWORD error) {
    if (error == ERROR_SUCCESS) {
        return "success";
    }

    LPSTR message_buffer = nullptr;
    const DWORD written = FormatMessageA(
        FORMAT_MESSAGE_ALLOCATE_BUFFER | FORMAT_MESSAGE_FROM_SYSTEM | FORMAT_MESSAGE_IGNORE_INSERTS,
        nullptr,
        error,
        0,
        reinterpret_cast<LPSTR>(&message_buffer),
        0,
        nullptr);

    std::string message = written == 0 || message_buffer == nullptr
        ? "error " + std::to_string(error)
        : std::string(message_buffer, written);

    if (message_buffer != nullptr) {
        LocalFree(message_buffer);
    }

    while (!message.empty() &&
           (message.back() == '\r' || message.back() == '\n' || message.back() == ' ' || message.back() == '\t')) {
        message.pop_back();
    }

    return message;
}

void LogPipeWin32Failure(const char* operation, DWORD error) {
    Log(
        std::string("[lua-exec-pipe] ") + operation + " failed: " + FormatWindowsError(error) +
        " (code=" + std::to_string(error) + ")");
}

bool IsPipeStopRequested() {
    return g_pipe_stop_event != nullptr && WaitForSingleObject(g_pipe_stop_event, 0) == WAIT_OBJECT_0;
}

std::string WideToUtf8(const std::wstring& value) {
    if (value.empty()) {
        return {};
    }

    const int required = WideCharToMultiByte(
        CP_UTF8,
        0,
        value.c_str(),
        static_cast<int>(value.size()),
        nullptr,
        0,
        nullptr,
        nullptr);
    if (required <= 0) {
        return {};
    }

    std::string output(static_cast<size_t>(required), '\0');
    const int written = WideCharToMultiByte(
        CP_UTF8,
        0,
        value.c_str(),
        static_cast<int>(value.size()),
        output.data(),
        required,
        nullptr,
        nullptr);
    if (written <= 0) {
        return {};
    }
    return output;
}

std::wstring ReadEnvironmentString(const wchar_t* name) {
    if (name == nullptr || name[0] == L'\0') {
        return {};
    }

    const DWORD required = GetEnvironmentVariableW(name, nullptr, 0);
    if (required == 0) {
        return {};
    }

    std::wstring value(required, L'\0');
    const DWORD written = GetEnvironmentVariableW(name, value.data(), required);
    if (written == 0 || written >= required) {
        return {};
    }
    value.resize(written);
    return value;
}

std::wstring ResolvePipeName() {
    std::wstring configured = ReadEnvironmentString(kPipeNameEnvironmentVariable);
    if (configured.empty()) {
        return kDefaultPipeName;
    }

    if (configured.compare(0, std::wstring_view(kPipeNamePrefix).size(), kPipeNamePrefix) == 0) {
        return configured;
    }

    for (wchar_t& ch : configured) {
        if (ch == L'\\' || ch == L'/') {
            ch = L'_';
        }
    }
    return std::wstring(kPipeNamePrefix) + configured;
}

const std::wstring& PipeName() {
    static const std::wstring pipe_name = ResolvePipeName();
    return pipe_name;
}

bool BuildPipeSecurityAttributes(SECURITY_ATTRIBUTES* attributes, SECURITY_DESCRIPTOR* descriptor) {
    if (attributes == nullptr || descriptor == nullptr) {
        return false;
    }

    if (!InitializeSecurityDescriptor(descriptor, SECURITY_DESCRIPTOR_REVISION)) {
        return false;
    }

    if (!SetSecurityDescriptorDacl(descriptor, TRUE, nullptr, FALSE)) {
        return false;
    }

    attributes->nLength = sizeof(*attributes);
    attributes->lpSecurityDescriptor = descriptor;
    attributes->bInheritHandle = FALSE;
    return true;
}

std::string JsonEscape(std::string_view value) {
    std::ostringstream escaped;
    for (const unsigned char ch : value) {
        switch (ch) {
        case '\"':
            escaped << "\\\"";
            break;
        case '\\':
            escaped << "\\\\";
            break;
        case '\b':
            escaped << "\\b";
            break;
        case '\f':
            escaped << "\\f";
            break;
        case '\n':
            escaped << "\\n";
            break;
        case '\r':
            escaped << "\\r";
            break;
        case '\t':
            escaped << "\\t";
            break;
        default:
            if (ch < 0x20) {
                static constexpr char kHex[] = "0123456789abcdef";
                escaped << "\\u00" << kHex[(ch >> 4) & 0x0F] << kHex[ch & 0x0F];
            } else {
                escaped << static_cast<char>(ch);
            }
            break;
        }
    }

    return escaped.str();
}

std::string SerializeResponse(const LuaExecResult& response) {
    std::ostringstream payload;
    payload << "{\"ok\":" << (response.ok ? "true" : "false")
            << ",\"print_output\":\"" << JsonEscape(response.print_output) << "\""
            << ",\"results\":[";
    for (std::size_t index = 0; index < response.results.size(); ++index) {
        if (index != 0) {
            payload << ',';
        }
        payload << "\"" << JsonEscape(response.results[index]) << "\"";
    }
    payload << "]"
            << ",\"error\":\"" << JsonEscape(response.error) << "\"}";
    return payload.str();
}

PipeReadStatus ReadPipeMessage(HANDLE pipe, std::string* message) {
    if (message == nullptr) {
        return PipeReadStatus::Error;
    }

    message->clear();
    std::vector<char> buffer(kPipeBufferSize);
    bool too_large = false;
    for (;;) {
        DWORD bytes_read = 0;
        const BOOL ok = ReadFile(pipe, buffer.data(), static_cast<DWORD>(buffer.size()), &bytes_read, nullptr);
        if (ok) {
            if (bytes_read == 0 && message->empty() && !too_large) {
                return PipeReadStatus::ClientDisconnected;
            }

            if (!too_large && bytes_read != 0) {
                if (message->size() > kMaxPipeMessageSize - static_cast<size_t>(bytes_read)) {
                    too_large = true;
                    message->clear();
                } else {
                    message->append(buffer.data(), static_cast<size_t>(bytes_read));
                }
            }
            return too_large ? PipeReadStatus::MessageTooLarge : PipeReadStatus::Success;
        }

        const DWORD error = GetLastError();
        if (error == ERROR_MORE_DATA) {
            if (!too_large && bytes_read != 0) {
                if (message->size() > kMaxPipeMessageSize - static_cast<size_t>(bytes_read)) {
                    too_large = true;
                    message->clear();
                } else {
                    message->append(buffer.data(), static_cast<size_t>(bytes_read));
                }
            }
            continue;
        }

        if ((error == ERROR_BROKEN_PIPE || error == ERROR_NO_DATA || error == ERROR_OPERATION_ABORTED) &&
            message->empty() && !too_large) {
            return PipeReadStatus::ClientDisconnected;
        }

        if (error != ERROR_BROKEN_PIPE && error != ERROR_NO_DATA &&
            !(error == ERROR_OPERATION_ABORTED && IsPipeStopRequested())) {
            LogPipeWin32Failure("ReadFile", error);
        }
        return PipeReadStatus::Error;
    }
}

bool WritePipeMessage(HANDLE pipe, const std::string& message) {
    if (message.size() > (std::numeric_limits<DWORD>::max)()) {
        Log("[lua-exec-pipe] response exceeded Win32 pipe write limit.");
        return false;
    }

    DWORD bytes_written = 0;
    const BOOL ok = WriteFile(
        pipe,
        message.data(),
        static_cast<DWORD>(message.size()),
        &bytes_written,
        nullptr);
    if (!ok) {
        const DWORD error = GetLastError();
        if (error != ERROR_BROKEN_PIPE && error != ERROR_NO_DATA &&
            !(error == ERROR_OPERATION_ABORTED && IsPipeStopRequested())) {
            LogPipeWin32Failure("WriteFile", error);
        }
        return false;
    }

    if (bytes_written != message.size()) {
        Log(
            "[lua-exec-pipe] short write: wrote " + std::to_string(bytes_written) + " of " +
            std::to_string(message.size()) + " bytes.");
        return false;
    }

    if (!FlushFileBuffers(pipe)) {
        const DWORD error = GetLastError();
        if (error != ERROR_BROKEN_PIPE && error != ERROR_NO_DATA &&
            !(error == ERROR_OPERATION_ABORTED && IsPipeStopRequested())) {
            LogPipeWin32Failure("FlushFileBuffers", error);
            return false;
        }
    }

    return true;
}

bool WaitForPipeClient(HANDLE pipe) {
    if (IsPipeStopRequested()) {
        SetLastError(ERROR_OPERATION_ABORTED);
        return false;
    }

    const BOOL connected = ConnectNamedPipe(pipe, nullptr);
    if (connected) {
        return true;
    }

    const DWORD connect_error = GetLastError();
    if (connect_error == ERROR_PIPE_CONNECTED) {
        return true;
    }
    SetLastError(connect_error);
    return false;
}

void NudgePipeServerForShutdown() {
    if (g_pipe_stop_event == nullptr) {
        return;
    }

    HANDLE handle = CreateFileW(
        PipeName().c_str(),
        GENERIC_READ | GENERIC_WRITE,
        0,
        nullptr,
        OPEN_EXISTING,
        0,
        nullptr);
    if (handle != INVALID_HANDLE_VALUE) {
        CloseHandle(handle);
    }
}

unsigned __stdcall PipeServerMain(void*) {
    Log("[lua-exec-pipe] server started. name=" + WideToUtf8(PipeName()));

    while (g_pipe_running.load(std::memory_order_acquire)) {
        SECURITY_ATTRIBUTES sa = {};
        SECURITY_DESCRIPTOR sd = {};
        if (!BuildPipeSecurityAttributes(&sa, &sd)) {
            LogPipeWin32Failure("BuildPipeSecurityAttributes", GetLastError());
            break;
        }

        sa.nLength = sizeof(sa);
        sa.bInheritHandle = FALSE;

        HANDLE pipe = CreateNamedPipeW(
            PipeName().c_str(),
            PIPE_ACCESS_DUPLEX,
            PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS,
            1,
            kPipeBufferSize,
            kPipeBufferSize,
            0,
            &sa);

        if (pipe == INVALID_HANDLE_VALUE) {
            LogPipeWin32Failure("CreateNamedPipeW", GetLastError());
            if (WaitForSingleObject(g_pipe_stop_event, kPipeReconnectDelayMs) == WAIT_OBJECT_0) {
                break;
            }
            continue;
        }

        if (!WaitForPipeClient(pipe)) {
            const DWORD error = GetLastError();
            if (error != ERROR_NO_DATA && !(error == ERROR_OPERATION_ABORTED && IsPipeStopRequested())) {
                LogPipeWin32Failure("ConnectNamedPipe", error);
            }
            CloseHandle(pipe);
            continue;
        }

        std::string code;
        switch (ReadPipeMessage(pipe, &code)) {
        case PipeReadStatus::Success: {
            const LuaExecResult response = QueueLuaExecRequestAndWait(
                code,
                kLuaExecHangBackstopMs,
                &g_pipe_running);
            std::string payload = SerializeResponse(response);
            if (payload.size() > kMaxPipeMessageSize) {
                payload =
                    "{\"ok\":false,\"print_output\":\"\",\"results\":[],\"error\":\"response exceeded maximum pipe payload size\"}";
            }
            WritePipeMessage(pipe, payload);
            break;
        }
        case PipeReadStatus::MessageTooLarge:
            WritePipeMessage(
                pipe,
                "{\"ok\":false,\"print_output\":\"\",\"results\":[],\"error\":\"request exceeded maximum pipe payload size\"}");
            break;
        case PipeReadStatus::ClientDisconnected:
        case PipeReadStatus::Error:
            break;
        }

        DisconnectNamedPipe(pipe);
        CloseHandle(pipe);
    }

    g_pipe_running.store(false, std::memory_order_release);
    Log("[lua-exec-pipe] server stopped.");
    return 0;
}

}  // namespace

bool StartLuaExecPipeServer() {
    if (g_pipe_running.exchange(true, std::memory_order_acq_rel)) {
        return true;
    }

    g_pipe_stop_event = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    if (g_pipe_stop_event == nullptr) {
        g_pipe_running.store(false, std::memory_order_release);
        Log("Lua exec pipe: failed to create stop event.");
        return false;
    }

    const auto pipe_thread = _beginthreadex(
        nullptr,
        0,
        &PipeServerMain,
        nullptr,
        0,
        nullptr);
    if (pipe_thread == 0) {
        g_pipe_running.store(false, std::memory_order_release);
        CloseHandle(g_pipe_stop_event);
        g_pipe_stop_event = nullptr;
        Log("Lua exec pipe: failed to start thread.");
        return false;
    }

    g_pipe_thread = reinterpret_cast<HANDLE>(pipe_thread);
    return true;
}

void StopLuaExecPipeServer() {
    const bool was_running = g_pipe_running.exchange(false, std::memory_order_acq_rel);
    if (!was_running && g_pipe_thread == nullptr && g_pipe_stop_event == nullptr) {
        return;
    }

    if (g_pipe_stop_event != nullptr) {
        SetEvent(g_pipe_stop_event);
    }
    if (g_pipe_thread != nullptr) {
        const BOOL canceled = CancelSynchronousIo(g_pipe_thread);
        if (!canceled) {
            const DWORD error = GetLastError();
            if (error != ERROR_NOT_FOUND && error != ERROR_INVALID_HANDLE) {
                LogPipeWin32Failure("CancelSynchronousIo", error);
            }
        }
        NudgePipeServerForShutdown();
        WaitForSingleObject(g_pipe_thread, INFINITE);
        CloseHandle(g_pipe_thread);
        g_pipe_thread = nullptr;
    }
    if (g_pipe_stop_event != nullptr) {
        CloseHandle(g_pipe_stop_event);
        g_pipe_stop_event = nullptr;
    }
}

bool IsLuaExecPipeServerRunning() {
    return g_pipe_running.load(std::memory_order_acquire);
}

}  // namespace sdmod
