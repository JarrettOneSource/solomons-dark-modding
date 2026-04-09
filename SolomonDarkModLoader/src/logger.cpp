#include "logger.h"

#include <Windows.h>

#include <cstdint>
#include <fstream>
#include <iomanip>
#include <mutex>
#include <sstream>
#include <string>

namespace sdmod {
namespace {

std::mutex g_log_mutex;
std::ofstream g_log_stream;
std::filesystem::path g_log_path;

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

}  // namespace

void InitializeLogger(const std::filesystem::path& log_path) {
    std::scoped_lock lock(g_log_mutex);

    CloseStream(g_log_stream);
    g_log_path.clear();

    const auto log_directory = log_path.parent_path();
    if (!log_directory.empty()) {
        std::filesystem::create_directories(log_directory);
    }

    g_log_stream.open(log_path, std::ios::out | std::ios::trunc);
    g_log_path = log_path;
}

void FlushLogger() {
    std::scoped_lock lock(g_log_mutex);
    FlushOpenStream();
}

std::filesystem::path GetLoggerPath() {
    std::scoped_lock lock(g_log_mutex);
    return g_log_path;
}

void ShutdownLogger() {
    std::scoped_lock lock(g_log_mutex);
    CloseStream(g_log_stream);
    g_log_path.clear();
}

void Log(std::string_view message) {
    std::scoped_lock lock(g_log_mutex);

    const std::string line = "[" + Timestamp() + "] " + std::string(message);
    if (g_log_stream.is_open()) {
        g_log_stream << line << '\n';
        g_log_stream.flush();
    }

    std::wstring wide(line.begin(), line.end());
    wide.append(L"\n");
    OutputDebugStringW(wide.c_str());
}

}  // namespace sdmod
