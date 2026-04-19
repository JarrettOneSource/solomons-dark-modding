#include "logger_internal.h"

namespace sdmod::detail::logger {

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
    const auto eax = static_cast<unsigned long>(context != nullptr ? context->Eax : 0);
    const auto ebx = static_cast<unsigned long>(context != nullptr ? context->Ebx : 0);
    const auto ecx = static_cast<unsigned long>(context != nullptr ? context->Ecx : 0);
    const auto edx = static_cast<unsigned long>(context != nullptr ? context->Edx : 0);
    const auto esi = static_cast<unsigned long>(context != nullptr ? context->Esi : 0);
    const auto edi = static_cast<unsigned long>(context != nullptr ? context->Edi : 0);
    const auto length = std::snprintf(
        line,
        sizeof(line),
        "[%04u-%02u-%02u %02u:%02u:%02u.%03u] unhandled exception"
        " tid=%lu code=0x%08lX address=0x%08lX access_type=0x%08lX access_address=0x%08lX"
        " eip=0x%08lX esp=0x%08lX ebp=0x%08lX"
        " eax=0x%08lX ebx=0x%08lX ecx=0x%08lX edx=0x%08lX esi=0x%08lX edi=0x%08lX\r\n",
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
        ebp,
        eax,
        ebx,
        ecx,
        edx,
        esi,
        edi);
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

thread_local int g_first_chance_handler_depth = 0;

struct FirstChanceHandlerDepthGuard {
    FirstChanceHandlerDepthGuard() { ++g_first_chance_handler_depth; }
    ~FirstChanceHandlerDepthGuard() { --g_first_chance_handler_depth; }
};

LONG CALLBACK FirstChanceExceptionLogger(EXCEPTION_POINTERS* exception_pointers) {
    if (exception_pointers == nullptr || exception_pointers->ExceptionRecord == nullptr) {
        return EXCEPTION_CONTINUE_SEARCH;
    }

    if (g_first_chance_handler_depth > 0) {
        return EXCEPTION_CONTINUE_SEARCH;
    }

    const auto* record = exception_pointers->ExceptionRecord;
    auto* context = exception_pointers->ContextRecord;
    const DWORD code = record->ExceptionCode;
    if (code != 0xE06D7363 && code != EXCEPTION_ACCESS_VIOLATION && code != 0x40000015) {
        return EXCEPTION_CONTINUE_SEARCH;
    }

    FirstChanceHandlerDepthGuard reentrancy_scope;

    const DWORD access_type_for_recovery = record->NumberParameters >= 1
        ? static_cast<DWORD>(record->ExceptionInformation[0])
        : 0xFFFFFFFFu;
    if (code == EXCEPTION_ACCESS_VIOLATION && context != nullptr &&
        access_type_for_recovery == 0) {
        const uintptr_t eax_val = static_cast<uintptr_t>(context->Eax);
        const uintptr_t esi_val = static_cast<uintptr_t>(context->Esi);
        const uintptr_t eip_val = static_cast<uintptr_t>(context->Eip);
        const uintptr_t access_addr = record->NumberParameters >= 2
            ? static_cast<uintptr_t>(record->ExceptionInformation[1])
            : 0;
        const uintptr_t exception_addr = reinterpret_cast<uintptr_t>(record->ExceptionAddress);
        const auto& memory = ProcessMemory::Instance();

        struct NullPrimaryEntryRecovery {
            const char* description;
            std::uintptr_t crash_ghidra_eip;
            std::uintptr_t recover_ghidra_eip;
            bool match_eax_null;
            std::uintptr_t expected_access;
        };
        static constexpr NullPrimaryEntryRecovery kNullEntryRecoveries[] = {
            {"MovementCollision_QueryType2Hazards", 0x009125E0, 0x009126C2, false, 0xC},
            {"MovementCollision_IteratePrimary", 0x00522D10, 0x00522E00, true, 0x10},
        };

        for (const auto& entry : kNullEntryRecoveries) {
            const uintptr_t crash_eip = memory.ResolveGameAddressOrZero(entry.crash_ghidra_eip);
            if (crash_eip == 0 || eip_val != crash_eip) {
                continue;
            }
            if (exception_addr != eip_val) {
                continue;
            }
            const bool reg_matches = entry.match_eax_null ? (eax_val == 0) : (esi_val == 0);
            if (!reg_matches || access_addr != entry.expected_access) {
                continue;
            }
            const uintptr_t recover_eip = memory.ResolveGameAddressOrZero(entry.recover_ghidra_eip);
            if (recover_eip == 0) {
                break;
            }
            static std::atomic<unsigned int> g_null_hazard_recoveries{0};
            const unsigned int recovery_seq = ++g_null_hazard_recoveries;
            std::ostringstream recovered;
            recovered << '[' << Timestamp()
                      << "] recovered NULL primary_list entry in "
                      << entry.description
                      << " tid=" << GetCurrentThreadId()
                      << " seq=" << recovery_seq
                      << " eip=0x" << HexString(eip_val)
                      << " -> 0x" << HexString(recover_eip);
            sdmod::Log(recovered.str());
            context->Eip = static_cast<DWORD>(recover_eip);
            return EXCEPTION_CONTINUE_EXECUTION;
        }
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
    const uintptr_t eax =
        context != nullptr ? static_cast<uintptr_t>(context->Eax) : 0;
    const uintptr_t ebx =
        context != nullptr ? static_cast<uintptr_t>(context->Ebx) : 0;
    const uintptr_t ecx =
        context != nullptr ? static_cast<uintptr_t>(context->Ecx) : 0;
    const uintptr_t edx =
        context != nullptr ? static_cast<uintptr_t>(context->Edx) : 0;
    const uintptr_t esi =
        context != nullptr ? static_cast<uintptr_t>(context->Esi) : 0;
    const uintptr_t edi =
        context != nullptr ? static_cast<uintptr_t>(context->Edi) : 0;
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
        << " ebp=0x" << HexString(ebp)
        << " eax=0x" << HexString(eax)
        << " ebx=0x" << HexString(ebx)
        << " ecx=0x" << HexString(ecx)
        << " edx=0x" << HexString(edx)
        << " esi=0x" << HexString(esi)
        << " edi=0x" << HexString(edi);
    if (eip != 0) {
        out << " eip_info: " << DescribeAddress(eip);
        std::uint8_t bytes[16] = {};
        std::size_t bytes_read = 0;
        for (std::size_t i = 0; i < sizeof(bytes); ++i) {
            std::uint32_t word = 0;
            if (TryReadCrashU32(eip + static_cast<uintptr_t>(i & ~std::size_t{0x3}), &word)) {
                bytes[i] = static_cast<std::uint8_t>((word >> ((i & 0x3) * 8)) & 0xFF);
                ++bytes_read;
            } else {
                break;
            }
        }
        if (bytes_read > 0) {
            out << " eip_bytes=";
            for (std::size_t i = 0; i < bytes_read; ++i) {
                if (i > 0) {
                    out << ' ';
                }
                out << std::uppercase << std::setw(2) << std::setfill('0') << std::hex
                    << static_cast<unsigned int>(bytes[i]) << std::nouppercase << std::setfill(' ');
            }
        }
    }
    if (esp != 0) {
        out << " esp_info: " << DescribeAddress(esp);
        out << " stack_words";
        for (int i = 0; i < 16; ++i) {
            std::uint32_t word = 0;
            const auto word_address = esp + static_cast<uintptr_t>(i * sizeof(std::uint32_t));
            if (TryReadCrashU32(word_address, &word)) {
                out << " [" << HexString(word_address) << "]=0x" << HexString(word);
            }
        }
    }
    if (code == EXCEPTION_ACCESS_VIOLATION) {
        AppendMovementContextCandidate(&out, "ctx_ebx", ebx);
        if (esi != ebx) {
            AppendMovementContextCandidate(&out, "ctx_esi", esi);
        }
        if (ecx != ebx && ecx != esi) {
            AppendMovementContextCandidate(&out, "ctx_ecx", ecx);
        }
    }
    sdmod::Log(out.str());
    const auto stack_trace = FormatCapturedStackTrace(0, 16);
    if (!stack_trace.empty()) {
        sdmod::Log(stack_trace);
    }
    return EXCEPTION_CONTINUE_SEARCH;
}

}  // namespace sdmod::detail::logger

namespace sdmod {

void InstallCrashHandler(const std::filesystem::path& crash_log_path) {
    using namespace sdmod::detail::logger;

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

void ShutdownCrashHandler() {
    using namespace sdmod::detail::logger;

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

}  // namespace sdmod
