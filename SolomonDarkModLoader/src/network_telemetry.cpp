#include "network_telemetry.h"

#include <Windows.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <cstdlib>
#include <deque>
#include <fstream>
#include <iomanip>
#include <iterator>
#include <limits>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <utility>

namespace sdmod {
namespace {

constexpr wchar_t kEnableEnvironmentVariable[] =
    L"SDMOD_NETWORK_TELEMETRY";
constexpr wchar_t kPathEnvironmentVariable[] =
    L"SDMOD_NETWORK_TELEMETRY_PATH";
constexpr std::size_t kMaximumQueuedLines = 65536;
constexpr std::uint64_t kLikelyFragmentedIpv4DatagramBytes = 1472;
constexpr std::uint64_t kTransportStageTelemetryThresholdMicroseconds = 5000;

struct SequenceState {
    bool have_packet = false;
    std::uint32_t latest_sequence = 0;
    std::uint64_t last_arrival_microseconds = 0;
    std::uint64_t last_wire_arrival_microseconds = 0;
    std::uint64_t inferred_missing_packets = 0;
    std::uint64_t reordered_packets = 0;
    std::uint64_t duplicate_packets = 0;
};

struct PresentState {
    std::uint64_t last_started_microseconds = 0;
};

struct NetworkTelemetryState {
    std::atomic<bool> enabled{false};
    std::mutex queue_mutex;
    std::condition_variable queue_changed;
    std::deque<std::string> queued_lines;
    bool stopping = false;
    std::uint64_t dropped_lines = 0;
    std::thread writer_thread;
    std::ofstream stream;

    std::mutex receive_mutex;
    SequenceState receive_sequence;

    std::mutex present_mutex;
    PresentState present;
};

struct TransportTickState {
    bool active = false;
    std::uint64_t gap_microseconds = 0;
    std::size_t queue_depth_start = 0;
    std::size_t queue_depth_end = 0;
    bool have_queue_depth_start = false;
    bool have_queue_depth_end = false;
    std::uint64_t send_attempt_count = 0;
    std::uint64_t send_success_count = 0;
    std::uint64_t send_failure_count = 0;
    std::uint64_t send_bytes = 0;
    std::uint64_t largest_send_bytes = 0;
    std::uint64_t likely_fragmented_send_count = 0;
};

NetworkTelemetryState g_network_telemetry;
thread_local TransportTickState g_transport_tick;

bool EnvironmentEnabled() {
    wchar_t value[8]{};
    const auto written = GetEnvironmentVariableW(
        kEnableEnvironmentVariable,
        value,
        static_cast<DWORD>(std::size(value)));
    return written == 1 && value[0] == L'1';
}

std::filesystem::path EnvironmentPath() {
    std::wstring value(256, L'\0');
    for (;;) {
        const auto written = GetEnvironmentVariableW(
            kPathEnvironmentVariable,
            value.data(),
            static_cast<DWORD>(value.size()));
        if (written == 0) {
            return {};
        }
        if (written < value.size()) {
            value.resize(written);
            return std::filesystem::path(value);
        }
        value.resize(static_cast<std::size_t>(written) + 1);
    }
}

std::uint64_t SystemTime100Nanoseconds() {
    FILETIME time{};
    GetSystemTimeAsFileTime(&time);
    ULARGE_INTEGER combined{};
    combined.LowPart = time.dwLowDateTime;
    combined.HighPart = time.dwHighDateTime;
    return combined.QuadPart;
}

#include "network_telemetry/writer.inl"

std::uint64_t EndpointIpv4Identifier(std::uint64_t endpoint_id) {
    return endpoint_id & 0xFFFFFFFFull;
}

}  // namespace

std::uint64_t NetworkTelemetryNowMicroseconds() {
    static const std::int64_t frequency = []() {
        LARGE_INTEGER value{};
        return QueryPerformanceFrequency(&value)
            ? value.QuadPart
            : 0;
    }();

    LARGE_INTEGER counter{};
    if (frequency <= 0 ||
        !QueryPerformanceCounter(&counter)) {
        return static_cast<std::uint64_t>(GetTickCount64()) *
            1000ull;
    }
    const auto seconds =
        counter.QuadPart / frequency;
    const auto remainder =
        counter.QuadPart % frequency;
    return static_cast<std::uint64_t>(seconds) * 1000000ull +
        static_cast<std::uint64_t>(
            remainder * 1000000ll / frequency);
}

bool IsNetworkTelemetryEnabled() {
    return g_network_telemetry.enabled.load(
        std::memory_order_acquire);
}

void InitializeNetworkTelemetry(
    const std::filesystem::path& default_output_path) {
    auto& state = g_network_telemetry;
    if (!EnvironmentEnabled() ||
        state.enabled.load(std::memory_order_acquire)) {
        return;
    }

    auto output_path = EnvironmentPath();
    if (output_path.empty()) {
        output_path = default_output_path;
    }
    if (output_path.empty()) {
        return;
    }

    const auto parent = output_path.parent_path();
    if (!parent.empty()) {
        std::error_code error;
        std::filesystem::create_directories(parent, error);
        if (error) {
            return;
        }
    }

    state.stream.open(
        output_path,
        std::ios::out | std::ios::trunc);
    if (!state.stream.is_open()) {
        return;
    }

    {
        std::lock_guard<std::mutex> queue_lock(state.queue_mutex);
        state.stopping = false;
        state.dropped_lines = 0;
        state.queued_lines.clear();
    }
    {
        std::lock_guard<std::mutex> receive_lock(state.receive_mutex);
        state.receive_sequence = SequenceState{};
    }
    {
        std::lock_guard<std::mutex> present_lock(state.present_mutex);
        state.present = PresentState{};
    }

    try {
        state.enabled.store(true, std::memory_order_release);
        state.writer_thread = std::thread(WriterMain);
    } catch (...) {
        state.enabled.store(false, std::memory_order_release);
        state.stream.close();
        return;
    }

    std::ostringstream fields;
    fields << ",\"process_id\":" << GetCurrentProcessId()
           << ",\"path\":\""
           << EscapeJson(output_path.u8string())
           << "\""
           << ",\"queue_capacity\":" << kMaximumQueuedLines;
    EnqueueEvent("telemetry_start", fields.str());
}

void ShutdownNetworkTelemetry() {
    auto& state = g_network_telemetry;
    if (!state.enabled.load(std::memory_order_acquire)) {
        return;
    }

    std::uint64_t dropped_lines = 0;
    {
        std::lock_guard<std::mutex> lock(state.queue_mutex);
        dropped_lines = state.dropped_lines;
    }
    std::ostringstream fields;
    fields << ",\"dropped_lines\":" << dropped_lines;
    EnqueueEvent("telemetry_stop", fields.str());

    {
        std::lock_guard<std::mutex> lock(state.queue_mutex);
        state.enabled.store(false, std::memory_order_release);
        state.stopping = true;
    }
    state.queue_changed.notify_one();
    if (state.writer_thread.joinable()) {
        state.writer_thread.join();
    }
    state.stream.flush();
    state.stream.close();
}

void RecordNetworkTransportStart(
    std::string_view backend,
    std::string_view role,
    std::uint16_t local_port,
    int socket_receive_buffer_bytes,
    int socket_send_buffer_bytes) {
    if (!IsNetworkTelemetryEnabled()) {
        return;
    }
    {
        std::lock_guard<std::mutex> lock(
            g_network_telemetry.receive_mutex);
        g_network_telemetry.receive_sequence = SequenceState{};
    }

    std::ostringstream fields;
    fields << ",\"backend\":\"" << EscapeJson(backend) << "\""
           << ",\"role\":\"" << EscapeJson(role) << "\""
           << ",\"local_port\":" << local_port
           << ",\"socket_receive_buffer_bytes\":"
           << socket_receive_buffer_bytes
           << ",\"socket_send_buffer_bytes\":"
           << socket_send_buffer_bytes;
    EnqueueEvent("transport_start", fields.str());
}

void BeginNetworkTransportTick(
    std::uint64_t gap_microseconds) {
    if (!IsNetworkTelemetryEnabled()) {
        return;
    }
    g_transport_tick = TransportTickState{};
    g_transport_tick.active = true;
    g_transport_tick.gap_microseconds = gap_microseconds;
}

void SetNetworkTransportQueueDepth(
    bool tick_start,
    std::size_t queue_depth) {
    if (!g_transport_tick.active) {
        return;
    }
    if (tick_start) {
        g_transport_tick.queue_depth_start = queue_depth;
        g_transport_tick.have_queue_depth_start = true;
    } else {
        g_transport_tick.queue_depth_end = queue_depth;
        g_transport_tick.have_queue_depth_end = true;
    }
}

void RecordNetworkTransportStage(
    std::string_view stage,
    std::uint64_t duration_microseconds) {
    if (!IsNetworkTelemetryEnabled() ||
        duration_microseconds <
            kTransportStageTelemetryThresholdMicroseconds) {
        return;
    }

    std::ostringstream fields;
    fields << ",\"stage\":\"" << EscapeJson(stage) << "\""
           << ",\"duration_us\":" << duration_microseconds;
    EnqueueEvent("transport_stage", fields.str());
}

void EndNetworkTransportTick(
    std::uint64_t duration_microseconds) {
    if (!g_transport_tick.active) {
        return;
    }
    const auto tick = g_transport_tick;
    g_transport_tick = TransportTickState{};

    std::ostringstream fields;
    fields << ",\"gap_us\":" << tick.gap_microseconds
           << ",\"duration_us\":" << duration_microseconds
           << ",\"send_attempt_count\":"
           << tick.send_attempt_count
           << ",\"send_success_count\":"
           << tick.send_success_count
           << ",\"send_failure_count\":"
           << tick.send_failure_count
           << ",\"send_bytes\":" << tick.send_bytes
           << ",\"largest_send_bytes\":"
           << tick.largest_send_bytes
           << ",\"likely_fragmented_send_count\":"
           << tick.likely_fragmented_send_count;
    if (tick.have_queue_depth_start) {
        fields << ",\"queue_depth_start\":"
               << tick.queue_depth_start;
    }
    if (tick.have_queue_depth_end) {
        fields << ",\"queue_depth_end\":"
               << tick.queue_depth_end;
    }
    EnqueueEvent("transport_tick", fields.str());
}

void RecordNetworkPacketSend(
    std::string_view backend,
    std::uint16_t kind,
    std::uint32_t sequence,
    std::size_t logical_bytes,
    std::size_t wire_bytes,
    std::size_t datagram_count,
    std::size_t largest_datagram_bytes,
    std::uint64_t endpoint_id,
    std::uint16_t endpoint_port,
    int result,
    int error_code,
    std::uint64_t duration_microseconds) {
    if (!IsNetworkTelemetryEnabled()) {
        return;
    }

    if (g_transport_tick.active) {
        ++g_transport_tick.send_attempt_count;
        g_transport_tick.send_bytes += wire_bytes;
        g_transport_tick.largest_send_bytes =
            (std::max)(
                g_transport_tick.largest_send_bytes,
                static_cast<std::uint64_t>(
                    largest_datagram_bytes));
        if (largest_datagram_bytes >
            kLikelyFragmentedIpv4DatagramBytes) {
            ++g_transport_tick.likely_fragmented_send_count;
        }
        if (result == static_cast<int>(logical_bytes) ||
            (backend == "steam" && result != 0)) {
            ++g_transport_tick.send_success_count;
        } else {
            ++g_transport_tick.send_failure_count;
        }
    }

    std::ostringstream fields;
    fields << ",\"backend\":\"" << EscapeJson(backend) << "\""
           << ",\"kind\":" << kind
           << ",\"sequence\":" << sequence
           << ",\"bytes\":" << logical_bytes
           << ",\"wire_bytes\":" << wire_bytes
           << ",\"datagram_count\":" << datagram_count
           << ",\"largest_datagram_bytes\":"
           << largest_datagram_bytes
           << ",\"endpoint_id\":" << endpoint_id
           << ",\"endpoint_ipv4\":"
           << EndpointIpv4Identifier(endpoint_id)
           << ",\"endpoint_port\":" << endpoint_port
           << ",\"result\":" << result
           << ",\"error_code\":" << error_code
           << ",\"duration_us\":" << duration_microseconds
           << ",\"likely_fragmented\":"
           << (largest_datagram_bytes >
                       kLikelyFragmentedIpv4DatagramBytes
                   ? "true"
                   : "false")
           << ",\"transport_fragmented\":"
           << (datagram_count > 1 ? "true" : "false");
    EnqueueEvent("packet_send", fields.str());
}

void RecordNetworkSteamSendResult(
    std::uint16_t kind,
    std::uint32_t sequence,
    std::size_t bytes,
    std::uint64_t endpoint_id,
    bool reliable,
    bool accepted,
    std::int32_t result_code,
    std::uint64_t duration_microseconds) {
    if (!IsNetworkTelemetryEnabled()) {
        return;
    }

    std::ostringstream fields;
    fields << ",\"kind\":" << kind
           << ",\"sequence\":" << sequence
           << ",\"bytes\":" << bytes
           << ",\"endpoint_id\":" << endpoint_id
           << ",\"endpoint_ipv4\":"
           << EndpointIpv4Identifier(endpoint_id)
           << ",\"reliable\":"
           << (reliable ? "true" : "false")
           << ",\"accepted\":"
           << (accepted ? "true" : "false")
           << ",\"result_code\":" << result_code
           << ",\"duration_us\":" << duration_microseconds;
    EnqueueEvent("steam_send_result", fields.str());
}

void RecordNetworkPacketReceive(
    std::uint16_t kind,
    std::uint32_t sequence,
    std::size_t bytes,
    std::uint64_t endpoint_id,
    std::uint16_t endpoint_port,
    std::size_t ingress_queue_depth,
    std::size_t ingress_queue_bytes,
    bool physical_datagram) {
    if (!IsNetworkTelemetryEnabled()) {
        return;
    }

    const auto now_microseconds =
        NetworkTelemetryNowMicroseconds();
    std::uint64_t arrival_gap_microseconds = 0;
    std::uint64_t wire_arrival_gap_microseconds = 0;
    std::uint32_t sequence_delta = 0;
    std::uint32_t missing_before = 0;
    bool reordered = false;
    bool duplicate = false;
    std::uint64_t cumulative_missing = 0;
    std::uint64_t cumulative_reordered = 0;
    std::uint64_t cumulative_duplicates = 0;
    {
        std::lock_guard<std::mutex> lock(
            g_network_telemetry.receive_mutex);
        auto& state = g_network_telemetry.receive_sequence;
        if (physical_datagram) {
            if (state.last_wire_arrival_microseconds != 0 &&
                now_microseconds >=
                    state.last_wire_arrival_microseconds) {
                wire_arrival_gap_microseconds =
                    now_microseconds -
                    state.last_wire_arrival_microseconds;
            }
            state.last_wire_arrival_microseconds =
                now_microseconds;
        }
        if (state.last_arrival_microseconds != 0 &&
            now_microseconds >= state.last_arrival_microseconds) {
            arrival_gap_microseconds =
                now_microseconds -
                state.last_arrival_microseconds;
        }
        state.last_arrival_microseconds = now_microseconds;

        if (!state.have_packet) {
            state.have_packet = true;
            state.latest_sequence = sequence;
        } else {
            sequence_delta =
                sequence - state.latest_sequence;
            if (sequence_delta == 0) {
                duplicate = true;
                ++state.duplicate_packets;
            } else if (
                sequence_delta <
                (std::numeric_limits<std::uint32_t>::max)() /
                    2u) {
                missing_before = sequence_delta - 1u;
                state.inferred_missing_packets +=
                    missing_before;
                state.latest_sequence = sequence;
            } else {
                reordered = true;
                ++state.reordered_packets;
            }
        }
        cumulative_missing =
            state.inferred_missing_packets;
        cumulative_reordered =
            state.reordered_packets;
        cumulative_duplicates =
            state.duplicate_packets;
    }

    std::ostringstream fields;
    fields << ",\"kind\":" << kind
           << ",\"sequence\":" << sequence
           << ",\"bytes\":" << bytes
           << ",\"endpoint_id\":" << endpoint_id
           << ",\"endpoint_ipv4\":"
           << EndpointIpv4Identifier(endpoint_id)
           << ",\"endpoint_port\":" << endpoint_port
           << ",\"arrival_gap_us\":"
           << arrival_gap_microseconds
           << ",\"wire_arrival_gap_us\":"
           << wire_arrival_gap_microseconds
           << ",\"physical_datagram\":"
           << (physical_datagram ? "true" : "false")
           << ",\"sequence_delta\":" << sequence_delta
           << ",\"missing_before\":" << missing_before
           << ",\"reordered\":"
           << (reordered ? "true" : "false")
           << ",\"duplicate\":"
           << (duplicate ? "true" : "false")
           << ",\"cumulative_missing\":"
           << cumulative_missing
           << ",\"cumulative_reordered\":"
           << cumulative_reordered
           << ",\"cumulative_duplicates\":"
           << cumulative_duplicates
           << ",\"ingress_queue_depth\":"
           << ingress_queue_depth
           << ",\"ingress_queue_bytes\":"
           << ingress_queue_bytes;
    EnqueueEvent("packet_receive", fields.str());
}

void RecordNetworkFragmentReceive(
    std::uint16_t original_kind,
    std::uint32_t original_sequence,
    std::size_t logical_bytes,
    std::size_t datagram_bytes,
    std::uint16_t fragment_index,
    std::uint16_t fragment_count,
    std::uint64_t endpoint_id,
    std::uint16_t endpoint_port,
    bool accepted,
    bool assembly_complete) {
    if (!IsNetworkTelemetryEnabled()) {
        return;
    }

    const auto now_microseconds =
        NetworkTelemetryNowMicroseconds();
    std::uint64_t wire_arrival_gap_microseconds = 0;
    {
        std::lock_guard<std::mutex> lock(
            g_network_telemetry.receive_mutex);
        auto& state = g_network_telemetry.receive_sequence;
        if (state.last_wire_arrival_microseconds != 0 &&
            now_microseconds >=
                state.last_wire_arrival_microseconds) {
            wire_arrival_gap_microseconds =
                now_microseconds -
                state.last_wire_arrival_microseconds;
        }
        state.last_wire_arrival_microseconds =
            now_microseconds;
    }

    std::ostringstream fields;
    fields << ",\"kind\":" << original_kind
           << ",\"sequence\":" << original_sequence
           << ",\"logical_bytes\":" << logical_bytes
           << ",\"datagram_bytes\":" << datagram_bytes
           << ",\"fragment_index\":" << fragment_index
           << ",\"fragment_count\":" << fragment_count
           << ",\"endpoint_id\":" << endpoint_id
           << ",\"endpoint_ipv4\":"
           << EndpointIpv4Identifier(endpoint_id)
           << ",\"endpoint_port\":" << endpoint_port
           << ",\"wire_arrival_gap_us\":"
           << wire_arrival_gap_microseconds
           << ",\"accepted\":"
           << (accepted ? "true" : "false")
           << ",\"assembly_complete\":"
           << (assembly_complete ? "true" : "false");
    EnqueueEvent("fragment_receive", fields.str());
}

void RecordNetworkIngressDrop(
    std::uint16_t kind,
    std::uint32_t sequence,
    std::size_t bytes,
    std::size_t queue_depth,
    std::size_t queue_bytes,
    std::uint64_t cumulative_dropped_packets,
    std::uint64_t cumulative_dropped_bytes) {
    if (!IsNetworkTelemetryEnabled()) {
        return;
    }
    std::ostringstream fields;
    fields << ",\"kind\":" << kind
           << ",\"sequence\":" << sequence
           << ",\"bytes\":" << bytes
           << ",\"queue_depth\":" << queue_depth
           << ",\"queue_bytes\":" << queue_bytes
           << ",\"cumulative_dropped_packets\":"
           << cumulative_dropped_packets
           << ",\"cumulative_dropped_bytes\":"
           << cumulative_dropped_bytes;
    EnqueueEvent("ingress_drop", fields.str());
}

#include "network_telemetry/runtime_events.inl"

}  // namespace sdmod
