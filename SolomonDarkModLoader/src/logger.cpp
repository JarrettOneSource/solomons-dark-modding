#include "logger.h"

#include <Windows.h>
#include <DbgHelp.h>

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <algorithm>
#include <deque>
#include <fstream>
#include <iomanip>
#include <mutex>
#include <sstream>
#include <string>
#include <unordered_map>

namespace sdmod {
namespace {

std::mutex g_log_mutex;
std::ofstream g_log_stream;
std::filesystem::path g_log_path;
std::filesystem::path g_crash_log_path;
LPTOP_LEVEL_EXCEPTION_FILTER g_previous_exception_filter = nullptr;
bool g_crash_handler_installed = false;
PVOID g_vectored_exception_handler = nullptr;
std::deque<std::string> g_recent_log_lines;
std::string g_crash_context_summary;
std::unordered_map<DWORD, unsigned int> g_first_chance_exception_counts;

constexpr std::size_t kRecentLogLineLimit = 128;

std::string Timestamp() {
    SYSTEMTIME now{};
    GetLocalTime(&now);

    std::ostringstream out;
    out << std::setfill('0')
        << std::setw(4) << now.wYear << '-'
        << std::setw(2) << now.wMonth << '-'
        << std::setw(2) << now.wDay << ' '
        << std::setw(2) << now.wHour << ':'
        << std::setw(2) << now.wMinute << ':'
        << std::setw(2) << now.wSecond << '.'
        << std::setw(3) << now.wMilliseconds;
    return out.str();
}

std::string HexString(uintptr_t value) {
    std::ostringstream out;
    out << std::uppercase << std::hex << std::setfill('0') << std::setw(sizeof(uintptr_t) * 2) << value;
    return out.str();
}

void CloseStream(std::ofstream& stream) {
    if (!stream.is_open()) {
        return;
    }

    stream.flush();
    stream.close();
}

void FlushOpenStream() {
    if (g_log_stream.is_open()) {
        g_log_stream.flush();
    }
}

void RememberRecentLogLine(std::string_view line) {
    if (line.empty()) {
        return;
    }

    if (g_recent_log_lines.size() >= kRecentLogLineLimit) {
        g_recent_log_lines.pop_front();
    }
    g_recent_log_lines.emplace_back(line);
}

void AppendCrashText(const char* text) {
    if (text == nullptr || *text == '\0' || g_crash_log_path.empty()) {
        return;
    }

    const auto file = CreateFileW(
        g_crash_log_path.c_str(),
        FILE_APPEND_DATA,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        nullptr,
        OPEN_ALWAYS,
        FILE_ATTRIBUTE_NORMAL | FILE_FLAG_WRITE_THROUGH,
        nullptr);
    if (file == INVALID_HANDLE_VALUE) {
        return;
    }

    const auto length = static_cast<DWORD>(std::strlen(text));
    DWORD written = 0;
    if (length != 0) {
        (void)WriteFile(file, text, length, &written, nullptr);
    }
    CloseHandle(file);
}

std::string FormatWin32Error(DWORD error_code) {
    if (error_code == 0) {
        return "0";
    }

    char buffer[256] = {};
    auto length = FormatMessageA(
        FORMAT_MESSAGE_FROM_SYSTEM | FORMAT_MESSAGE_IGNORE_INSERTS,
        nullptr,
        error_code,
        0,
        buffer,
        static_cast<DWORD>(sizeof(buffer)),
        nullptr);
    if (length == 0) {
        std::ostringstream out;
        out << "0x" << std::uppercase << std::hex << error_code;
        return out.str();
    }

    while (length != 0 &&
           (buffer[length - 1] == '\r' || buffer[length - 1] == '\n' || buffer[length - 1] == ' ')) {
        buffer[length - 1] = '\0';
        --length;
    }
    return std::string(buffer);
}

const char* MemoryStateName(DWORD state) {
    switch (state) {
    case MEM_COMMIT:
        return "MEM_COMMIT";
    case MEM_FREE:
        return "MEM_FREE";
    case MEM_RESERVE:
        return "MEM_RESERVE";
    default:
        return "MEM_UNKNOWN";
    }
}

const char* MemoryTypeName(DWORD type) {
    switch (type) {
    case MEM_IMAGE:
        return "MEM_IMAGE";
    case MEM_MAPPED:
        return "MEM_MAPPED";
    case MEM_PRIVATE:
        return "MEM_PRIVATE";
    default:
        return "MEM_NONE";
    }
}

std::string MemoryProtectName(DWORD protect) {
    if (protect == 0) {
        return "0";
    }

    struct ProtectName {
        DWORD flag;
        const char* name;
    };
    static const ProtectName kProtectNames[] = {
        {PAGE_NOACCESS, "PAGE_NOACCESS"},
        {PAGE_READONLY, "PAGE_READONLY"},
        {PAGE_READWRITE, "PAGE_READWRITE"},
        {PAGE_WRITECOPY, "PAGE_WRITECOPY"},
        {PAGE_EXECUTE, "PAGE_EXECUTE"},
        {PAGE_EXECUTE_READ, "PAGE_EXECUTE_READ"},
        {PAGE_EXECUTE_READWRITE, "PAGE_EXECUTE_READWRITE"},
        {PAGE_EXECUTE_WRITECOPY, "PAGE_EXECUTE_WRITECOPY"},
        {PAGE_GUARD, "PAGE_GUARD"},
        {PAGE_NOCACHE, "PAGE_NOCACHE"},
        {PAGE_WRITECOMBINE, "PAGE_WRITECOMBINE"},
    };

    std::ostringstream out;
    bool first = true;
    for (const auto& entry : kProtectNames) {
        if ((protect & entry.flag) == 0) {
            continue;
        }
        if (!first) {
            out << '|';
        }
        out << entry.name;
        first = false;
    }
    if (first) {
        out << "0x" << std::uppercase << std::hex << protect;
    }
    return out.str();
}

bool TryReadCrashU32(uintptr_t address, std::uint32_t* value) {
    if (value == nullptr || address == 0) {
        return false;
    }

    __try {
        *value = *reinterpret_cast<const std::uint32_t*>(address);
        return true;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        *value = 0;
        return false;
    }
}

std::string DescribeAddress(uintptr_t address);

std::string FormatCapturedStackTrace(unsigned short frames_to_skip, unsigned short max_frames) {
    if (max_frames == 0) {
        return std::string();
    }

    void* frames[32] = {};
    max_frames = (std::min<unsigned short>)(
        max_frames,
        static_cast<unsigned short>(sizeof(frames) / sizeof(frames[0])));
    const auto captured = CaptureStackBackTrace(frames_to_skip, max_frames, frames, nullptr);
    if (captured == 0) {
        return std::string();
    }

    std::ostringstream out;
    out << "  stack_trace";
    for (USHORT index = 0; index < captured; ++index) {
        const auto address = reinterpret_cast<uintptr_t>(frames[index]);
        out << "\r\n"
            << "    [" << std::dec << index << "] 0x" << HexString(address)
            << " " << DescribeAddress(address);
    }
    out << "\r\n";
    return out.str();
}

std::string DescribeAddress(uintptr_t address) {
    std::ostringstream out;
    out << "addr=0x" << std::uppercase << std::hex << std::setw(8) << std::setfill('0') << address;
    if (address == 0) {
        return out.str();
    }

    MEMORY_BASIC_INFORMATION mbi{};
    if (VirtualQuery(reinterpret_cast<LPCVOID>(address), &mbi, sizeof(mbi)) == 0) {
        out << " virtual_query_failed=" << FormatWin32Error(GetLastError());
        return out.str();
    }

    const auto allocation_base = reinterpret_cast<uintptr_t>(mbi.AllocationBase);
    const auto region_base = reinterpret_cast<uintptr_t>(mbi.BaseAddress);
    out << " alloc_base=0x" << std::setw(8) << allocation_base;
    out << " base=0x" << std::setw(8) << region_base;
    out << " size=0x" << std::setw(8) << static_cast<std::uint32_t>(mbi.RegionSize);
    out << " state=" << MemoryStateName(mbi.State);
    out << " protect=" << MemoryProtectName(mbi.Protect);
    out << " type=" << MemoryTypeName(mbi.Type);

    if (allocation_base != 0 && mbi.Type == MEM_IMAGE) {
        char module_path[MAX_PATH] = {};
        const auto length = GetModuleFileNameA(
            reinterpret_cast<HMODULE>(mbi.AllocationBase),
            module_path,
            static_cast<DWORD>(sizeof(module_path)));
        if (length != 0) {
            out << " module=" << module_path;
            out << " module_offset=0x" << std::setw(8) << (address - allocation_base);
        }
    }

    return out.str();
}

std::filesystem::path BuildCrashDumpPath(const SYSTEMTIME& now, DWORD thread_id) {
    auto dump_path = g_crash_log_path;
    const auto stem = dump_path.stem().wstring();
    std::wostringstream name;
    name << stem
         << L'.'
         << std::setfill(L'0')
         << std::setw(4) << now.wYear
         << std::setw(2) << now.wMonth
         << std::setw(2) << now.wDay
         << L'_'
         << std::setw(2) << now.wHour
         << std::setw(2) << now.wMinute
         << std::setw(2) << now.wSecond
         << L'_'
         << std::setw(3) << now.wMilliseconds
         << L".tid"
         << thread_id
         << L".dmp";
    dump_path.replace_filename(name.str());
    return dump_path;
}

std::string TryWriteCrashDump(const SYSTEMTIME& now, EXCEPTION_POINTERS* exception_pointers) {
    if (g_crash_log_path.empty()) {
        return "crash log path unavailable";
    }

    const auto dump_path = BuildCrashDumpPath(now, GetCurrentThreadId());

    HMODULE dbghelp = LoadLibraryW(L"dbghelp.dll");
    if (dbghelp == nullptr) {
        return "LoadLibrary(dbghelp.dll) failed: " + FormatWin32Error(GetLastError());
    }

    using MiniDumpWriteDumpFn = BOOL(WINAPI*)(
        HANDLE,
        DWORD,
        HANDLE,
        MINIDUMP_TYPE,
        PMINIDUMP_EXCEPTION_INFORMATION,
        PMINIDUMP_USER_STREAM_INFORMATION,
        PMINIDUMP_CALLBACK_INFORMATION);
    const auto mini_dump_write_dump = reinterpret_cast<MiniDumpWriteDumpFn>(
        GetProcAddress(dbghelp, "MiniDumpWriteDump"));
    if (mini_dump_write_dump == nullptr) {
        const auto error = GetLastError();
        FreeLibrary(dbghelp);
        return "GetProcAddress(MiniDumpWriteDump) failed: " + FormatWin32Error(error);
    }

    const auto dump_file = CreateFileW(
        dump_path.c_str(),
        GENERIC_WRITE,
        FILE_SHARE_READ,
        nullptr,
        CREATE_ALWAYS,
        FILE_ATTRIBUTE_NORMAL | FILE_FLAG_WRITE_THROUGH,
        nullptr);
    if (dump_file == INVALID_HANDLE_VALUE) {
        const auto error = GetLastError();
        FreeLibrary(dbghelp);
        return "CreateFile(" + dump_path.string() + ") failed: " + FormatWin32Error(error);
    }

    MINIDUMP_EXCEPTION_INFORMATION exception_info{};
    exception_info.ThreadId = GetCurrentThreadId();
    exception_info.ExceptionPointers = exception_pointers;
    exception_info.ClientPointers = FALSE;

    const auto dump_type = static_cast<MINIDUMP_TYPE>(
        MiniDumpWithDataSegs |
        MiniDumpWithHandleData |
        MiniDumpWithIndirectlyReferencedMemory |
        MiniDumpScanMemory |
        MiniDumpWithThreadInfo |
        MiniDumpWithUnloadedModules |
        MiniDumpWithFullMemoryInfo |
        MiniDumpWithCodeSegs);
    const BOOL wrote_dump = mini_dump_write_dump(
        GetCurrentProcess(),
        GetCurrentProcessId(),
        dump_file,
        dump_type,
        exception_pointers != nullptr ? &exception_info : nullptr,
        nullptr,
        nullptr);
    const auto dump_error = wrote_dump ? ERROR_SUCCESS : GetLastError();

    CloseHandle(dump_file);
    FreeLibrary(dbghelp);

    if (!wrote_dump) {
        return "MiniDumpWriteDump failed: " + FormatWin32Error(dump_error);
    }

    return dump_path.string();
}

void AppendRecentLogTailToCrashReport() {
    std::deque<std::string> recent_lines;
    std::string crash_summary;
    if (g_log_mutex.try_lock()) {
        recent_lines = g_recent_log_lines;
        crash_summary = g_crash_context_summary;
        g_log_mutex.unlock();
    }

    if (!recent_lines.empty()) {
        AppendCrashText("  recent_log_tail:\r\n");
        for (const auto& line : recent_lines) {
            AppendCrashText("    ");
            AppendCrashText(line.c_str());
            AppendCrashText("\r\n");
        }
    }

    if (!crash_summary.empty()) {
        AppendCrashText("  crash_context_summary:\r\n");
        AppendCrashText(crash_summary.c_str());
        AppendCrashText("\r\n");
    }
}

LONG WINAPI CrashExceptionFilter(EXCEPTION_POINTERS* exception_pointers) {
    SYSTEMTIME now{};
    GetLocalTime(&now);

    const auto* record = exception_pointers != nullptr ? exception_pointers->ExceptionRecord : nullptr;
    const auto* context = exception_pointers != nullptr ? exception_pointers->ContextRecord : nullptr;

    const DWORD code = record != nullptr ? record->ExceptionCode : 0;
    const auto exception_address = static_cast<unsigned long>(
        reinterpret_cast<uintptr_t>(record != nullptr ? record->ExceptionAddress : nullptr));
    unsigned long access_type = 0;
    unsigned long access_address = 0;
    if (record != nullptr && record->NumberParameters >= 2) {
        access_type = static_cast<unsigned long>(record->ExceptionInformation[0]);
        access_address = static_cast<unsigned long>(record->ExceptionInformation[1]);
    }

    char line[1024];
#if defined(_M_IX86)
    const auto eip = static_cast<unsigned long>(context != nullptr ? context->Eip : 0);
    const auto esp = static_cast<unsigned long>(context != nullptr ? context->Esp : 0);
    const auto ebp = static_cast<unsigned long>(context != nullptr ? context->Ebp : 0);
    const auto length = std::snprintf(
        line,
        sizeof(line),
        "[%04u-%02u-%02u %02u:%02u:%02u.%03u] unhandled exception"
        " tid=%lu code=0x%08lX address=0x%08lX access_type=0x%08lX access_address=0x%08lX"
        " eip=0x%08lX esp=0x%08lX ebp=0x%08lX\r\n",
        static_cast<unsigned>(now.wYear),
        static_cast<unsigned>(now.wMonth),
        static_cast<unsigned>(now.wDay),
        static_cast<unsigned>(now.wHour),
        static_cast<unsigned>(now.wMinute),
        static_cast<unsigned>(now.wSecond),
        static_cast<unsigned>(now.wMilliseconds),
        static_cast<unsigned long>(GetCurrentThreadId()),
        static_cast<unsigned long>(code),
        exception_address,
        access_type,
        access_address,
        eip,
        esp,
        ebp);
#else
    const auto length = std::snprintf(
        line,
        sizeof(line),
        "[%04u-%02u-%02u %02u:%02u:%02u.%03u] unhandled exception"
        " tid=%lu code=0x%08lX address=0x%08lX access_type=0x%08lX access_address=0x%08lX\r\n",
        static_cast<unsigned>(now.wYear),
        static_cast<unsigned>(now.wMonth),
        static_cast<unsigned>(now.wDay),
        static_cast<unsigned>(now.wHour),
        static_cast<unsigned>(now.wMinute),
        static_cast<unsigned>(now.wSecond),
        static_cast<unsigned>(now.wMilliseconds),
        static_cast<unsigned long>(GetCurrentThreadId()),
        static_cast<unsigned long>(code),
        exception_address,
        access_type,
        access_address);
#endif

    if (length > 0) {
        AppendCrashText(line);
    }

    if (record != nullptr) {
        std::ostringstream out;
        out << "  record_parameters=" << std::dec << record->NumberParameters;
        for (ULONG index = 0; index < record->NumberParameters; ++index) {
            out << " p" << index << "=0x"
                << std::uppercase << std::hex
                << static_cast<unsigned long>(record->ExceptionInformation[index]);
        }
        out << "\r\n";
        AppendCrashText(out.str().c_str());
    }

    {
        const auto exception_description = DescribeAddress(
            reinterpret_cast<uintptr_t>(record != nullptr ? record->ExceptionAddress : nullptr));
        const std::string line_text = "  exception_address_info: " + exception_description + "\r\n";
        AppendCrashText(line_text.c_str());
    }

#if defined(_M_IX86)
    {
        const auto eip_address = static_cast<uintptr_t>(context != nullptr ? context->Eip : 0);
        const auto esp_address = static_cast<uintptr_t>(context != nullptr ? context->Esp : 0);
        const auto ebp_address = static_cast<uintptr_t>(context != nullptr ? context->Ebp : 0);
        const std::string eip_text = "  eip_info: " + DescribeAddress(eip_address) + "\r\n";
        const std::string esp_text = "  esp_info: " + DescribeAddress(esp_address) + "\r\n";
        const std::string ebp_text = "  ebp_info: " + DescribeAddress(ebp_address) + "\r\n";
        AppendCrashText(eip_text.c_str());
        AppendCrashText(esp_text.c_str());
        AppendCrashText(ebp_text.c_str());

        if (esp_address != 0) {
            std::ostringstream out;
            out << "  stack_words";
            for (int index = 0; index < 16; ++index) {
                const auto word_address = esp_address + static_cast<uintptr_t>(index * sizeof(std::uint32_t));
                std::uint32_t value = 0;
                if (!TryReadCrashU32(word_address, &value)) {
                    out << " [0x" << HexString(word_address) << "]=<unreadable>";
                    break;
                }
                out << " [0x" << HexString(word_address) << "]=0x" << HexString(value);
            }
            out << "\r\n";
            AppendCrashText(out.str().c_str());
        }
    }
#endif

    if (access_address != 0) {
        const std::string access_text =
            "  access_address_info: " + DescribeAddress(access_address) + "\r\n";
        AppendCrashText(access_text.c_str());
    }

    {
        const auto dump_result = TryWriteCrashDump(now, exception_pointers);
        const std::string dump_text = "  dump: " + dump_result + "\r\n";
        AppendCrashText(dump_text.c_str());
    }

    {
        const auto stack_trace = FormatCapturedStackTrace(0, 16);
        if (!stack_trace.empty()) {
            AppendCrashText(stack_trace.c_str());
        }
    }

    AppendRecentLogTailToCrashReport();

    if (g_previous_exception_filter != nullptr &&
        g_previous_exception_filter != &CrashExceptionFilter) {
        return g_previous_exception_filter(exception_pointers);
    }

    return EXCEPTION_CONTINUE_SEARCH;
}

LONG CALLBACK FirstChanceExceptionLogger(EXCEPTION_POINTERS* exception_pointers) {
    if (exception_pointers == nullptr || exception_pointers->ExceptionRecord == nullptr) {
        return EXCEPTION_CONTINUE_SEARCH;
    }

    const auto* record = exception_pointers->ExceptionRecord;
    const auto* context = exception_pointers->ContextRecord;
    const DWORD code = record->ExceptionCode;
    if (code != 0xE06D7363 && code != EXCEPTION_ACCESS_VIOLATION && code != 0x40000015) {
        return EXCEPTION_CONTINUE_SEARCH;
    }

    unsigned int occurrence = 0;
    {
        std::lock_guard<std::mutex> lock(g_log_mutex);
        occurrence = ++g_first_chance_exception_counts[code];
    }
    if (occurrence > 32) {
        return EXCEPTION_CONTINUE_SEARCH;
    }

    const uintptr_t exception_address =
        reinterpret_cast<uintptr_t>(record->ExceptionAddress);
    const uintptr_t eip =
        context != nullptr ? static_cast<uintptr_t>(context->Eip) : 0;
    const uintptr_t esp =
        context != nullptr ? static_cast<uintptr_t>(context->Esp) : 0;
    const uintptr_t ebp =
        context != nullptr ? static_cast<uintptr_t>(context->Ebp) : 0;
    const DWORD access_type =
        record->NumberParameters >= 1 ? static_cast<DWORD>(record->ExceptionInformation[0]) : 0;
    const uintptr_t access_address =
        record->NumberParameters >= 2 ? static_cast<uintptr_t>(record->ExceptionInformation[1]) : 0;

    std::ostringstream out;
    out << '[' << Timestamp() << "] first-chance exception tid=" << GetCurrentThreadId()
        << " count=" << occurrence
        << " code=0x" << HexString(code)
        << " address=0x" << HexString(exception_address)
        << " access_type=0x" << HexString(access_type)
        << " access_address=0x" << HexString(access_address)
        << " eip=0x" << HexString(eip)
        << " esp=0x" << HexString(esp)
        << " ebp=0x" << HexString(ebp);
    if (esp != 0) {
        out << " esp_info: " << DescribeAddress(esp);
        out << " stack_words";
        for (int i = 0; i < 8; ++i) {
            std::uint32_t word = 0;
            const auto word_address = esp + static_cast<uintptr_t>(i * sizeof(std::uint32_t));
            if (TryReadCrashU32(word_address, &word)) {
                out << " [" << HexString(word_address) << "]=0x" << HexString(word);
            }
        }
    }
    Log(out.str());
    const auto stack_trace = FormatCapturedStackTrace(0, 16);
    if (!stack_trace.empty()) {
        Log(stack_trace);
    }
    return EXCEPTION_CONTINUE_SEARCH;
}

}  // namespace

void InitializeLogger(const std::filesystem::path& log_path) {
    std::scoped_lock lock(g_log_mutex);

    CloseStream(g_log_stream);
    g_log_path.clear();
    g_recent_log_lines.clear();
    g_crash_context_summary.clear();

    const auto log_directory = log_path.parent_path();
    if (!log_directory.empty()) {
        std::filesystem::create_directories(log_directory);
    }

    g_log_stream.open(log_path, std::ios::out | std::ios::trunc);
    g_log_path = log_path;
}

void InstallCrashHandler(const std::filesystem::path& crash_log_path) {
    std::scoped_lock lock(g_log_mutex);

    g_crash_log_path = crash_log_path;
    const auto crash_directory = crash_log_path.parent_path();
    if (!crash_directory.empty()) {
        std::filesystem::create_directories(crash_directory);
    }

    if (!g_crash_handler_installed) {
        g_previous_exception_filter = SetUnhandledExceptionFilter(&CrashExceptionFilter);
        g_vectored_exception_handler = AddVectoredExceptionHandler(1, &FirstChanceExceptionLogger);
        g_crash_handler_installed = true;
    }
}

void FlushLogger() {
    std::scoped_lock lock(g_log_mutex);
    FlushOpenStream();
}

std::filesystem::path GetLoggerPath() {
    std::scoped_lock lock(g_log_mutex);
    return g_log_path;
}

void ShutdownCrashHandler() {
    std::scoped_lock lock(g_log_mutex);

    if (g_crash_handler_installed) {
        SetUnhandledExceptionFilter(g_previous_exception_filter);
        if (g_vectored_exception_handler != nullptr) {
            RemoveVectoredExceptionHandler(g_vectored_exception_handler);
            g_vectored_exception_handler = nullptr;
        }
        g_previous_exception_filter = nullptr;
        g_crash_handler_installed = false;
    }

    g_crash_log_path.clear();
    g_crash_context_summary.clear();
    g_first_chance_exception_counts.clear();
}

void ShutdownLogger() {
    std::scoped_lock lock(g_log_mutex);
    g_recent_log_lines.clear();
    g_crash_context_summary.clear();
    CloseStream(g_log_stream);
    g_log_path.clear();
}

void Log(std::string_view message) {
    std::scoped_lock lock(g_log_mutex);

    const std::string line = "[" + Timestamp() + "] " + std::string(message);
    RememberRecentLogLine(line);
    if (g_log_stream.is_open()) {
        g_log_stream << line << '\n';
        g_log_stream.flush();
    }

    std::wstring wide(line.begin(), line.end());
    wide.append(L"\n");
    OutputDebugStringW(wide.c_str());
}

void SetCrashContextSummary(std::string_view summary) {
    std::scoped_lock lock(g_log_mutex);
    g_crash_context_summary.assign(summary.begin(), summary.end());
}

}  // namespace sdmod
