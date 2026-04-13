#include "lua_exec_pipe.h"

#include "logger.h"
#include "lua_engine_bindings_internal.h"
#include "lua_engine_internal.h"

extern "C" {
#include "lauxlib.h"
#include "lua.h"
}

#include <Windows.h>

#include <atomic>
#include <cstdint>
#include <limits>
#include <sstream>
#include <string>
#include <string_view>
#include <thread>
#include <vector>

namespace sdmod {
namespace {

constexpr wchar_t kPipeName[] = L"\\\\.\\pipe\\SolomonDarkModLoader_LuaExec";
constexpr DWORD kPipeBufferSize = 64 * 1024;
constexpr DWORD kPipeReconnectDelayMs = 250;
constexpr size_t kMaxPipeMessageSize = 1024 * 1024;

std::atomic<bool> g_pipe_running = false;
std::thread g_pipe_thread;
HANDLE g_pipe_stop_event = nullptr;

enum class PipeReadStatus {
    Success,
    ClientDisconnected,
    MessageTooLarge,
    Error,
};

struct LuaExecResponse {
    bool ok = false;
    std::string print_output;
    std::vector<std::string> results;
    std::string error;
};

class LuaPrintCaptureGuard {
public:
    explicit LuaPrintCaptureGuard(std::string* sink) : previous_sink_(detail::SwapLuaPrintCaptureSink(sink)) {}

    LuaPrintCaptureGuard(const LuaPrintCaptureGuard&) = delete;
    LuaPrintCaptureGuard& operator=(const LuaPrintCaptureGuard&) = delete;

    ~LuaPrintCaptureGuard() {
        detail::SwapLuaPrintCaptureSink(previous_sink_);
    }

private:
    std::string* previous_sink_ = nullptr;
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

std::string SerializeResponse(const LuaExecResponse& response) {
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

bool EnsureSdGlobal(lua_State* state) {
    if (state == nullptr) {
        return false;
    }

    lua_getglobal(state, "sd");
    const bool has_global_sd = lua_istable(state, -1);
    lua_pop(state, 1);
    if (has_global_sd) {
        return true;
    }

    lua_getfield(state, LUA_REGISTRYINDEX, detail::kLuaSdRegistryKey);
    const bool has_registry_sd = lua_istable(state, -1);
    if (has_registry_sd) {
        lua_pushvalue(state, -1);
        lua_setglobal(state, "sd");
    }
    lua_pop(state, 1);
    return has_registry_sd;
}

LuaExecResponse ExecuteLuaCode(const std::string& code) {
    LuaExecResponse response;
    if (code.empty()) {
        response.error = "No Lua code was provided.";
        return response;
    }

    std::unique_lock lock(detail::LuaEngineMutex(), std::try_to_lock);
    if (!lock.owns_lock()) {
        response.error = "Lua engine is busy executing on another thread. Try again.";
        return response;
    }

    if (!detail::LuaEngineInitializedFlag()) {
        response.error = "Lua engine is not initialized.";
        return response;
    }

    auto& mods = detail::LoadedLuaModsStorage();
    if (mods.empty() || mods.front() == nullptr || mods.front()->state == nullptr) {
        response.error = "No loaded Lua mod state is available.";
        return response;
    }

    lua_State* state = mods.front()->state;
    const int stack_top_before = lua_gettop(state);
    if (!EnsureSdGlobal(state)) {
        response.error = "Lua runtime binding 'sd' is unavailable.";
        lua_settop(state, stack_top_before);
        return response;
    }
    LuaPrintCaptureGuard capture_guard(&response.print_output);

    const int status = luaL_dostring(state, code.c_str());
    if (status != LUA_OK) {
        const char* error = lua_tostring(state, -1);
        response.error = error == nullptr ? "unknown Lua error" : error;
        lua_settop(state, stack_top_before);
        return response;
    }

    const int result_count = lua_gettop(state) - stack_top_before;
    response.results.reserve(static_cast<std::size_t>(result_count));
    for (int index = stack_top_before + 1; index <= lua_gettop(state); ++index) {
        std::string result_text;
        std::string stringify_error;
        if (!detail::TryLuaValueToString(state, index, &result_text, &stringify_error)) {
            response.error =
                "Failed to stringify Lua result: " +
                (stringify_error.empty() ? std::string("unknown Lua tostring failure") : stringify_error);
            lua_settop(state, stack_top_before);
            return response;
        }
        response.results.push_back(std::move(result_text));
    }

    lua_settop(state, stack_top_before);
    response.ok = true;
    return response;
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
        kPipeName,
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

void PipeServerMain() {
    Log("[lua-exec-pipe] server started.");

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
            kPipeName,
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
            const LuaExecResponse response = ExecuteLuaCode(code);
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

    try {
        g_pipe_thread = std::thread(PipeServerMain);
        return true;
    } catch (...) {
        g_pipe_running.store(false, std::memory_order_release);
        CloseHandle(g_pipe_stop_event);
        g_pipe_stop_event = nullptr;
        Log("Lua exec pipe: failed to start thread.");
        return false;
    }
}

void StopLuaExecPipeServer() {
    const bool was_running = g_pipe_running.exchange(false, std::memory_order_acq_rel);
    if (!was_running && !g_pipe_thread.joinable() && g_pipe_stop_event == nullptr) {
        return;
    }

    if (g_pipe_stop_event != nullptr) {
        SetEvent(g_pipe_stop_event);
    }
    if (g_pipe_thread.joinable()) {
        std::atomic<bool> keep_nudging = true;
        std::thread nudge_thread([&keep_nudging]() {
            while (keep_nudging.load(std::memory_order_acquire)) {
                NudgePipeServerForShutdown();
                Sleep(10);
            }
        });

        const BOOL canceled = CancelSynchronousIo(g_pipe_thread.native_handle());
        if (!canceled) {
            const DWORD error = GetLastError();
            if (error != ERROR_NOT_FOUND && error != ERROR_INVALID_HANDLE) {
                LogPipeWin32Failure("CancelSynchronousIo", error);
            }
        }
        g_pipe_thread.join();
        keep_nudging.store(false, std::memory_order_release);
        nudge_thread.join();
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
