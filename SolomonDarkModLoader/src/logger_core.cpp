#include "logger_internal.h"

namespace sdmod::detail::logger {

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

}  // namespace sdmod::detail::logger

namespace sdmod {

void InitializeLogger(const std::filesystem::path& log_path) {
    using namespace sdmod::detail::logger;

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

void FlushLogger() {
    using namespace sdmod::detail::logger;

    std::scoped_lock lock(g_log_mutex);
    FlushOpenStream();
}

std::filesystem::path GetLoggerPath() {
    using namespace sdmod::detail::logger;

    std::scoped_lock lock(g_log_mutex);
    return g_log_path;
}

void ShutdownLogger() {
    using namespace sdmod::detail::logger;

    std::scoped_lock lock(g_log_mutex);
    g_recent_log_lines.clear();
    g_crash_context_summary.clear();
    CloseStream(g_log_stream);
    g_log_path.clear();
}

void Log(std::string_view message) {
    using namespace sdmod::detail::logger;

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
    using namespace sdmod::detail::logger;

    std::scoped_lock lock(g_log_mutex);
    g_crash_context_summary.assign(summary.begin(), summary.end());
}

}  // namespace sdmod
