std::string EscapeJson(std::string_view value) {
    std::ostringstream out;
    for (const unsigned char character : value) {
        switch (character) {
        case '"':
            out << "\\\"";
            break;
        case '\\':
            out << "\\\\";
            break;
        case '\b':
            out << "\\b";
            break;
        case '\f':
            out << "\\f";
            break;
        case '\n':
            out << "\\n";
            break;
        case '\r':
            out << "\\r";
            break;
        case '\t':
            out << "\\t";
            break;
        default:
            if (character < 0x20u) {
                out << "\\u"
                    << std::hex
                    << std::setw(4)
                    << std::setfill('0')
                    << static_cast<unsigned int>(character)
                    << std::dec;
            } else {
                out << static_cast<char>(character);
            }
            break;
        }
    }
    return out.str();
}

std::string EventPrefix(std::string_view event) {
    std::ostringstream out;
    out << "{\"schema\":1"
        << ",\"event\":\"" << EscapeJson(event) << "\""
        << ",\"utc_100ns\":" << SystemTime100Nanoseconds()
        << ",\"mono_us\":" << NetworkTelemetryNowMicroseconds()
        << ",\"thread_id\":" << GetCurrentThreadId();
    return out.str();
}

void EnqueueLine(std::string line) {
    auto& state = g_network_telemetry;
    if (!state.enabled.load(std::memory_order_acquire)) {
        return;
    }

    std::lock_guard<std::mutex> lock(state.queue_mutex);
    if (!state.enabled.load(std::memory_order_relaxed) ||
        state.stopping) {
        return;
    }
    if (state.queued_lines.size() >= kMaximumQueuedLines) {
        ++state.dropped_lines;
        return;
    }
    state.queued_lines.emplace_back(std::move(line));
    state.queue_changed.notify_one();
}

void EnqueueEvent(
    std::string_view event,
    const std::string& fields) {
    if (!g_network_telemetry.enabled.load(
            std::memory_order_acquire)) {
        return;
    }
    auto line = EventPrefix(event);
    line += fields;
    line += "}";
    EnqueueLine(std::move(line));
}

void WriterMain() {
    auto& state = g_network_telemetry;
    for (;;) {
        std::deque<std::string> lines;
        bool stopping = false;
        {
            std::unique_lock<std::mutex> lock(state.queue_mutex);
            state.queue_changed.wait_for(
                lock,
                std::chrono::milliseconds(250),
                [&state]() {
                    return state.stopping ||
                           !state.queued_lines.empty();
                });
            lines.swap(state.queued_lines);
            stopping = state.stopping;
        }

        for (const auto& line : lines) {
            state.stream << line << '\n';
        }
        if (!lines.empty() || stopping) {
            state.stream.flush();
        }
        if (stopping && lines.empty()) {
            break;
        }
    }
}
