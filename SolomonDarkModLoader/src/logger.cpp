#include "logger_internal.h"

namespace sdmod::detail::logger {

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

}  // namespace sdmod::detail::logger
