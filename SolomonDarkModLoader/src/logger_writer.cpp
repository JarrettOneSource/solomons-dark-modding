#include "logger_internal.h"
#include "network_telemetry.h"

#include <chrono>

namespace sdmod::detail::logger {
namespace {

void WriteDebuggerLine(const std::string& line) {
    std::wstring wide(line.begin(), line.end());
    wide.append(L"\n");
    OutputDebugStringW(wide.c_str());
}

void LogWriterMain() {
    for (;;) {
        std::deque<std::string> lines;
        std::uint64_t dropped_lines = 0;
        bool stopping = false;
        {
            std::unique_lock<std::mutex> lock(g_log_mutex);
            g_log_queue_changed.wait_for(
                lock,
                std::chrono::milliseconds(250),
                []() {
                    return g_log_writer_stopping ||
                           !g_queued_log_lines.empty();
                });
            lines.swap(g_queued_log_lines);
            g_queued_log_bytes = 0;
            dropped_lines = g_dropped_log_line_count;
            g_dropped_log_line_count = 0;
            stopping = g_log_writer_stopping;
        }

        std::size_t written_bytes = 0;
        const auto write_started_us =
            IsNetworkTelemetryEnabled()
                ? NetworkTelemetryNowMicroseconds()
                : 0;
        for (const auto& line : lines) {
            if (g_log_stream.is_open()) {
                g_log_stream << line << '\n';
            }
            WriteDebuggerLine(line);
            written_bytes += line.size() + 1;
        }
        if (dropped_lines != 0) {
            const std::string warning =
                "[" + Timestamp() + "] Logger dropped " +
                std::to_string(dropped_lines) +
                " lines because its asynchronous queue was full.";
            if (g_log_stream.is_open()) {
                g_log_stream << warning << '\n';
            }
            WriteDebuggerLine(warning);
            written_bytes += warning.size() + 1;
        }
        if (!lines.empty() || dropped_lines != 0 || stopping) {
            FlushOpenStream();
        }
        if (write_started_us != 0) {
            RecordNetworkLoggerFlush(
                lines.size(),
                written_bytes,
                dropped_lines,
                NetworkTelemetryNowMicroseconds() -
                    write_started_us);
        }

        {
            std::lock_guard<std::mutex> lock(g_log_mutex);
            g_written_log_line_count += lines.size();
        }
        g_log_queue_drained.notify_all();

        if (stopping && lines.empty()) {
            break;
        }
    }
}

}  // namespace

bool StartLogWriter() {
    std::lock_guard<std::mutex> lock(g_log_mutex);
    if (g_log_writer_running || !g_log_stream.is_open()) {
        return g_log_writer_running;
    }

    g_queued_log_lines.clear();
    g_queued_log_bytes = 0;
    g_enqueued_log_line_count = 0;
    g_written_log_line_count = 0;
    g_dropped_log_line_count = 0;
    g_log_writer_stopping = false;
    try {
        g_log_writer_thread = std::thread(&LogWriterMain);
        g_log_writer_running = true;
    } catch (...) {
        g_log_writer_running = false;
    }
    return g_log_writer_running;
}

void FlushLogWriter() {
    std::unique_lock<std::mutex> lock(g_log_mutex);
    if (!g_log_writer_running) {
        FlushOpenStream();
        return;
    }

    const auto target_line_count = g_enqueued_log_line_count;
    g_log_queue_changed.notify_one();
    g_log_queue_drained.wait(
        lock,
        [target_line_count]() {
            return g_written_log_line_count >=
                   target_line_count;
        });
}

void StopLogWriter() {
    {
        std::lock_guard<std::mutex> lock(g_log_mutex);
        if (!g_log_writer_running) {
            return;
        }
        g_log_writer_stopping = true;
    }
    g_log_queue_changed.notify_one();
    if (g_log_writer_thread.joinable()) {
        g_log_writer_thread.join();
    }

    std::lock_guard<std::mutex> lock(g_log_mutex);
    g_log_writer_running = false;
    g_log_writer_stopping = false;
    g_queued_log_lines.clear();
    g_queued_log_bytes = 0;
}

bool EnqueueLogLine(
    std::string line,
    std::size_t* queue_depth,
    std::uint64_t* dropped_line_count) {
    if (!g_log_writer_running || g_log_writer_stopping) {
        return false;
    }

    const auto line_bytes = line.size() + 1;
    if (g_queued_log_lines.size() >= kQueuedLogLineLimit ||
        line_bytes > kQueuedLogByteLimit - g_queued_log_bytes) {
        ++g_dropped_log_line_count;
        if (queue_depth != nullptr) {
            *queue_depth = g_queued_log_lines.size();
        }
        if (dropped_line_count != nullptr) {
            *dropped_line_count = g_dropped_log_line_count;
        }
        g_log_queue_changed.notify_one();
        return false;
    }

    g_queued_log_bytes += line_bytes;
    g_queued_log_lines.emplace_back(std::move(line));
    ++g_enqueued_log_line_count;
    if (queue_depth != nullptr) {
        *queue_depth = g_queued_log_lines.size();
    }
    if (dropped_line_count != nullptr) {
        *dropped_line_count = g_dropped_log_line_count;
    }
    g_log_queue_changed.notify_one();
    return true;
}

}  // namespace sdmod::detail::logger
