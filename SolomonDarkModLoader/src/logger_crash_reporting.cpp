#include "logger_internal.h"

namespace sdmod::detail::logger {

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

void AppendMovementContextCandidate(std::ostringstream* out, const char* label, uintptr_t context_address) {
    if (out == nullptr || label == nullptr) {
        return;
    }
    if (context_address < 0x10000) {
        return;
    }

    std::uint32_t primary_count = 0;
    std::uint32_t primary_list = 0;
    std::uint32_t secondary_count = 0;
    std::uint32_t secondary_list = 0;
    if (!TryReadCrashU32(context_address + 0x40, &primary_count) ||
        !TryReadCrashU32(context_address + 0x4C, &primary_list) ||
        !TryReadCrashU32(context_address + 0x70, &secondary_count) ||
        !TryReadCrashU32(context_address + 0x7C, &secondary_list)) {
        return;
    }
    if (primary_count > 256 || secondary_count > 256) {
        return;
    }

    *out << " " << label << "{ctx=0x" << HexString(context_address)
         << " primary_count=" << std::dec << primary_count
         << " primary_list=0x" << HexString(primary_list)
         << " secondary_count=" << std::dec << secondary_count
         << " secondary_list=0x" << HexString(secondary_list);

    const auto append_entries = [&](const char* entry_label, std::uint32_t list_address) {
        if (list_address == 0) {
            return;
        }
        for (int index = 0; index < 4; ++index) {
            std::uint32_t entry_address = 0;
            if (!TryReadCrashU32(
                    static_cast<uintptr_t>(list_address) + static_cast<uintptr_t>(index * sizeof(std::uint32_t)),
                    &entry_address)) {
                break;
            }
            *out << " " << entry_label << index << "=0x" << HexString(entry_address);
            if (entry_address == 0) {
                continue;
            }

            std::uint32_t value_0c = 0;
            std::uint32_t value_10 = 0;
            std::uint32_t value_14 = 0;
            if (TryReadCrashU32(static_cast<uintptr_t>(entry_address) + 0x0C, &value_0c)) {
                *out << " " << entry_label << index << "_0c=0x" << HexString(value_0c);
            }
            if (TryReadCrashU32(static_cast<uintptr_t>(entry_address) + 0x10, &value_10)) {
                *out << " " << entry_label << index << "_10=0x" << HexString(value_10);
            }
            if (TryReadCrashU32(static_cast<uintptr_t>(entry_address) + 0x14, &value_14)) {
                *out << " " << entry_label << index << "_14=0x" << HexString(value_14);
            }
        }
    };

    append_entries("primary", primary_list);
    append_entries("secondary", secondary_list);
    *out << "}";
}

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

}  // namespace sdmod::detail::logger
