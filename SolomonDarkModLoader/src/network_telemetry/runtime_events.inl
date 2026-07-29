void RecordNetworkPacketApply(
    std::uint16_t kind,
    std::uint32_t sequence,
    std::size_t bytes,
    bool accepted,
    std::uint64_t queue_age_microseconds,
    std::uint64_t duration_microseconds) {
    if (!IsNetworkTelemetryEnabled()) {
        return;
    }
    std::ostringstream fields;
    fields << ",\"kind\":" << kind
           << ",\"sequence\":" << sequence
           << ",\"bytes\":" << bytes
           << ",\"accepted\":"
           << (accepted ? "true" : "false")
           << ",\"queue_age_us\":"
           << queue_age_microseconds
           << ",\"duration_us\":" << duration_microseconds;
    EnqueueEvent("packet_apply", fields.str());
}

void RecordNetworkReceiveBatch(
    std::size_t packet_count,
    std::size_t byte_count,
    bool packet_limit_reached,
    bool time_limit_reached,
    int terminal_error_code,
    std::size_t queue_depth_start,
    std::size_t queue_depth_end,
    std::size_t queue_bytes_start,
    std::size_t queue_bytes_end,
    std::uint64_t oldest_queue_age_microseconds,
    std::uint64_t duration_microseconds) {
    if (!IsNetworkTelemetryEnabled()) {
        return;
    }
    std::ostringstream fields;
    fields << ",\"packet_count\":" << packet_count
           << ",\"byte_count\":" << byte_count
           << ",\"packet_limit_reached\":"
           << (packet_limit_reached ? "true" : "false")
           << ",\"time_limit_reached\":"
           << (time_limit_reached ? "true" : "false")
           << ",\"terminal_error_code\":"
           << terminal_error_code
           << ",\"queue_depth_start\":"
           << queue_depth_start
           << ",\"queue_depth_end\":"
           << queue_depth_end
           << ",\"queue_bytes_start\":"
           << queue_bytes_start
           << ",\"queue_bytes_end\":"
           << queue_bytes_end
           << ",\"oldest_queue_age_us\":"
           << oldest_queue_age_microseconds
           << ",\"duration_us\":" << duration_microseconds;
    EnqueueEvent("receive_batch", fields.str());
}

void RecordNetworkWorldApply(
    bool valid,
    bool holding_stale,
    std::uint32_t sequence,
    std::uint64_t snapshot_age_milliseconds,
    std::uint32_t local_actor_count,
    std::uint32_t matched_actor_count,
    std::uint32_t created_actor_count,
    std::uint32_t removed_actor_count,
    std::uint32_t transform_write_count,
    std::uint32_t presentation_write_count,
    std::uint64_t duration_microseconds) {
    if (!IsNetworkTelemetryEnabled()) {
        return;
    }
    std::ostringstream fields;
    fields << ",\"valid\":" << (valid ? "true" : "false")
           << ",\"holding_stale\":"
           << (holding_stale ? "true" : "false")
           << ",\"sequence\":" << sequence
           << ",\"snapshot_age_ms\":"
           << snapshot_age_milliseconds
           << ",\"local_actor_count\":" << local_actor_count
           << ",\"matched_actor_count\":"
           << matched_actor_count
           << ",\"created_actor_count\":"
           << created_actor_count
           << ",\"removed_actor_count\":"
           << removed_actor_count
           << ",\"transform_write_count\":"
           << transform_write_count
           << ",\"presentation_write_count\":"
           << presentation_write_count
           << ",\"duration_us\":" << duration_microseconds;
    EnqueueEvent("world_apply", fields.str());
}

void RecordNetworkPresent(
    std::uint64_t started_microseconds,
    std::uint64_t duration_microseconds) {
    if (!IsNetworkTelemetryEnabled()) {
        return;
    }

    std::uint64_t gap_microseconds = 0;
    {
        std::lock_guard<std::mutex> lock(
            g_network_telemetry.present_mutex);
        auto& state = g_network_telemetry.present;
        if (state.last_started_microseconds != 0 &&
            started_microseconds >=
                state.last_started_microseconds) {
            gap_microseconds =
                started_microseconds -
                state.last_started_microseconds;
        }
        state.last_started_microseconds =
            started_microseconds;
    }

    std::ostringstream fields;
    fields << ",\"gap_us\":" << gap_microseconds
           << ",\"duration_us\":" << duration_microseconds;
    EnqueueEvent("present", fields.str());
}

void RecordNetworkLoggerEnqueue(
    std::size_t message_bytes,
    std::uint64_t mutex_wait_microseconds,
    std::size_t queue_depth,
    bool queued,
    std::uint64_t dropped_line_count,
    std::uint64_t total_microseconds) {
    if (!IsNetworkTelemetryEnabled()) {
        return;
    }
    std::ostringstream fields;
    fields << ",\"message_bytes\":" << message_bytes
           << ",\"mutex_wait_us\":"
           << mutex_wait_microseconds
           << ",\"queue_depth\":" << queue_depth
           << ",\"queued\":" << (queued ? "true" : "false")
           << ",\"dropped_line_count\":"
           << dropped_line_count
           << ",\"total_us\":" << total_microseconds;
    EnqueueEvent("logger_enqueue", fields.str());
}

void RecordNetworkLoggerFlush(
    std::size_t line_count,
    std::size_t bytes,
    std::uint64_t dropped_line_count,
    std::uint64_t duration_microseconds) {
    if (!IsNetworkTelemetryEnabled()) {
        return;
    }
    std::ostringstream fields;
    fields << ",\"line_count\":" << line_count
           << ",\"bytes\":" << bytes
           << ",\"dropped_line_count\":"
           << dropped_line_count
           << ",\"duration_us\":" << duration_microseconds;
    EnqueueEvent("logger_flush", fields.str());
}

void RecordNetworkRecoverySend(
    std::string_view channel,
    std::uint64_t participant_id,
    std::uint32_t event_sequence,
    std::uint32_t packet_sequence,
    std::size_t pending_count,
    std::size_t in_flight_count,
    std::size_t send_window,
    bool retransmit,
    std::uint64_t previous_send_age_milliseconds) {
    if (!IsNetworkTelemetryEnabled()) {
        return;
    }
    std::ostringstream fields;
    fields << ",\"channel\":\"" << EscapeJson(channel) << "\""
           << ",\"participant_id\":" << participant_id
           << ",\"event_sequence\":" << event_sequence
           << ",\"packet_sequence\":" << packet_sequence
           << ",\"pending_count\":" << pending_count
           << ",\"in_flight_count\":" << in_flight_count
           << ",\"send_window\":" << send_window
           << ",\"retransmit\":"
           << (retransmit ? "true" : "false")
           << ",\"previous_send_age_ms\":"
           << previous_send_age_milliseconds;
    EnqueueEvent("recovery_send", fields.str());
}

void RecordNetworkRecoveryAck(
    std::string_view channel,
    std::uint64_t participant_id,
    std::uint32_t acknowledged_sequence,
    std::size_t retired_count,
    std::size_t pending_count) {
    if (!IsNetworkTelemetryEnabled()) {
        return;
    }
    std::ostringstream fields;
    fields << ",\"channel\":\"" << EscapeJson(channel) << "\""
           << ",\"participant_id\":" << participant_id
           << ",\"acknowledged_sequence\":"
           << acknowledged_sequence
           << ",\"retired_count\":" << retired_count
           << ",\"pending_count\":" << pending_count;
    EnqueueEvent("recovery_ack", fields.str());
}
