#include "logger_internal.h"

namespace sdmod::detail::logger {

std::mutex g_log_mutex;
std::ofstream g_log_stream;
std::filesystem::path g_log_path;
std::condition_variable g_log_queue_changed;
std::condition_variable g_log_queue_drained;
std::deque<std::string> g_queued_log_lines;
std::size_t g_queued_log_bytes = 0;
std::uint64_t g_enqueued_log_line_count = 0;
std::uint64_t g_written_log_line_count = 0;
std::uint64_t g_dropped_log_line_count = 0;
bool g_log_writer_stopping = false;
bool g_log_writer_running = false;
std::thread g_log_writer_thread;
std::filesystem::path g_crash_log_path;
LPTOP_LEVEL_EXCEPTION_FILTER g_previous_exception_filter = nullptr;
bool g_crash_handler_installed = false;
PVOID g_vectored_exception_handler = nullptr;
std::deque<std::string> g_recent_log_lines;
std::string g_crash_context_summary;
std::unordered_map<DWORD, unsigned int> g_first_chance_exception_counts;

}  // namespace sdmod::detail::logger
