#pragma once

#include "logger.h"

#include "memory_access.h"

#include <Windows.h>
#include <DbgHelp.h>

#include <atomic>
#include <algorithm>
#include <condition_variable>
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
extern std::condition_variable g_log_queue_changed;
extern std::condition_variable g_log_queue_drained;
extern std::deque<std::string> g_queued_log_lines;
extern std::size_t g_queued_log_bytes;
extern std::uint64_t g_enqueued_log_line_count;
extern std::uint64_t g_written_log_line_count;
extern std::uint64_t g_dropped_log_line_count;
extern bool g_log_writer_stopping;
extern bool g_log_writer_running;
extern HANDLE g_log_writer_thread;
extern std::filesystem::path g_crash_log_path;
extern LPTOP_LEVEL_EXCEPTION_FILTER g_previous_exception_filter;
extern bool g_crash_handler_installed;
extern PVOID g_vectored_exception_handler;
extern std::deque<std::string> g_recent_log_lines;
extern std::string g_crash_context_summary;
extern std::unordered_map<DWORD, unsigned int> g_first_chance_exception_counts;

constexpr std::size_t kRecentLogLineLimit = 128;
constexpr std::size_t kQueuedLogLineLimit = 8192;
constexpr std::size_t kQueuedLogByteLimit = 4 * 1024 * 1024;

std::string Timestamp();
std::string HexString(uintptr_t value);
void CloseStream(std::ofstream& stream);
void FlushOpenStream();
void RememberRecentLogLine(std::string_view line);
bool StartLogWriter();
void FlushLogWriter();
void StopLogWriter();
bool EnqueueLogLine(
    std::string line,
    std::size_t* queue_depth,
    std::uint64_t* dropped_line_count);

void AppendCrashText(const char* text);
std::string FormatWin32Error(DWORD error_code);
const char* MemoryStateName(DWORD state);
const char* MemoryTypeName(DWORD type);
std::string MemoryProtectName(DWORD protect);
bool TryReadCrashU32(uintptr_t address, std::uint32_t* value);
void AppendMovementContextCandidate(std::ostringstream* out, const char* label, uintptr_t context_address);
std::string DescribeAddress(uintptr_t address);
std::string FormatCapturedStackTrace(unsigned short frames_to_skip, unsigned short max_frames);
std::string FormatX86FrameChain(uintptr_t frame_pointer, unsigned short max_frames);
std::filesystem::path BuildCrashDumpPath(const SYSTEMTIME& now, DWORD thread_id);
std::string TryWriteCrashDump(const SYSTEMTIME& now, EXCEPTION_POINTERS* exception_pointers);
void AppendRecentLogTailToCrashReport();

LONG WINAPI CrashExceptionFilter(EXCEPTION_POINTERS* exception_pointers);
LONG CALLBACK FirstChanceExceptionLogger(EXCEPTION_POINTERS* exception_pointers);

}  // namespace sdmod::detail::logger
