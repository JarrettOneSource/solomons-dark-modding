#pragma once

#include "logger.h"

#include "memory_access.h"

#include <Windows.h>
#include <DbgHelp.h>

#include <atomic>
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <deque>
#include <fstream>
#include <iomanip>
#include <mutex>
#include <sstream>
#include <string>
#include <unordered_map>

namespace sdmod::detail::logger {

extern std::mutex g_log_mutex;
extern std::ofstream g_log_stream;
extern std::filesystem::path g_log_path;
extern std::filesystem::path g_crash_log_path;
extern LPTOP_LEVEL_EXCEPTION_FILTER g_previous_exception_filter;
extern bool g_crash_handler_installed;
extern PVOID g_vectored_exception_handler;
extern std::deque<std::string> g_recent_log_lines;
extern std::string g_crash_context_summary;
extern std::unordered_map<DWORD, unsigned int> g_first_chance_exception_counts;

constexpr std::size_t kRecentLogLineLimit = 128;

std::string Timestamp();
std::string HexString(uintptr_t value);
void CloseStream(std::ofstream& stream);
void FlushOpenStream();
void RememberRecentLogLine(std::string_view line);

void AppendCrashText(const char* text);
std::string FormatWin32Error(DWORD error_code);
const char* MemoryStateName(DWORD state);
const char* MemoryTypeName(DWORD type);
std::string MemoryProtectName(DWORD protect);
bool TryReadCrashU32(uintptr_t address, std::uint32_t* value);
void AppendMovementContextCandidate(std::ostringstream* out, const char* label, uintptr_t context_address);
std::string DescribeAddress(uintptr_t address);
std::string FormatCapturedStackTrace(unsigned short frames_to_skip, unsigned short max_frames);
std::filesystem::path BuildCrashDumpPath(const SYSTEMTIME& now, DWORD thread_id);
std::string TryWriteCrashDump(const SYSTEMTIME& now, EXCEPTION_POINTERS* exception_pointers);
void AppendRecentLogTailToCrashReport();

LONG WINAPI CrashExceptionFilter(EXCEPTION_POINTERS* exception_pointers);
LONG CALLBACK FirstChanceExceptionLogger(EXCEPTION_POINTERS* exception_pointers);

}  // namespace sdmod::detail::logger
