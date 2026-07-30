static_assert(
    sizeof(TransportPacketBuffer) <=
        kLocalUdpMaximumLogicalPacketBytes,
    "Local UDP framing cannot carry the largest gameplay packet");

constexpr std::size_t kLocalUdpMaximumIngressPackets = 2048;
constexpr std::size_t kLocalUdpMaximumIngressBytes =
    2 * 1024 * 1024;
constexpr long kLocalUdpIngressPollMicroseconds = 10'000;

struct QueuedLocalUdpPacket {
    std::vector<char> bytes;
    sockaddr_in from{};
    std::uint64_t arrival_microseconds = 0;
};

struct LocalUdpIngressQueueSnapshot {
    std::size_t packet_count = 0;
    std::size_t byte_count = 0;
    std::uint64_t oldest_arrival_microseconds = 0;
    std::uint64_t dropped_packets = 0;
    std::uint64_t dropped_bytes = 0;
};

struct DroppedLocalUdpPacket {
    std::uint16_t kind = 0;
    std::uint32_t sequence = 0;
    std::size_t bytes = 0;
    std::size_t queue_depth = 0;
    std::size_t queue_bytes = 0;
    std::uint64_t cumulative_dropped_packets = 0;
    std::uint64_t cumulative_dropped_bytes = 0;
};

std::mutex g_local_udp_ingress_mutex;
std::deque<QueuedLocalUdpPacket> g_local_udp_ingress_packets;
std::size_t g_local_udp_ingress_bytes = 0;
std::uint64_t g_local_udp_ingress_dropped_packets = 0;
std::uint64_t g_local_udp_ingress_dropped_bytes = 0;
std::atomic<bool> g_local_udp_ingress_stop_requested{false};
HANDLE g_local_udp_ingress_thread = nullptr;
LocalUdpFragmentReassembler g_local_udp_fragment_reassembler;

PacketHeader ReadTelemetryPacketHeader(
    const void* bytes,
    std::size_t byte_count) {
    PacketHeader header{};
    if (bytes != nullptr &&
        byte_count >= sizeof(header)) {
        std::memcpy(&header, bytes, sizeof(header));
    }
    return header;
}

std::uint64_t LocalUdpEndpointKey(
    const sockaddr_in& endpoint) {
    return
        (static_cast<std::uint64_t>(
             ntohl(endpoint.sin_addr.s_addr)) << 16) |
        static_cast<std::uint64_t>(
            ntohs(endpoint.sin_port));
}

LocalUdpIngressQueueSnapshot SnapshotLocalUdpIngressQueue() {
    std::lock_guard<std::mutex> lock(
        g_local_udp_ingress_mutex);
    LocalUdpIngressQueueSnapshot snapshot;
    snapshot.packet_count =
        g_local_udp_ingress_packets.size();
    snapshot.byte_count = g_local_udp_ingress_bytes;
    snapshot.oldest_arrival_microseconds =
        g_local_udp_ingress_packets.empty()
        ? 0
        : g_local_udp_ingress_packets.front()
              .arrival_microseconds;
    snapshot.dropped_packets =
        g_local_udp_ingress_dropped_packets;
    snapshot.dropped_bytes =
        g_local_udp_ingress_dropped_bytes;
    return snapshot;
}

void RecordDroppedLocalUdpPackets(
    const std::vector<DroppedLocalUdpPacket>& dropped_packets) {
    for (const auto& dropped : dropped_packets) {
        RecordNetworkIngressDrop(
            dropped.kind,
            dropped.sequence,
            dropped.bytes,
            dropped.queue_depth,
            dropped.queue_bytes,
            dropped.cumulative_dropped_packets,
            dropped.cumulative_dropped_bytes);
    }
}

bool EnqueueLocalUdpPacket(
    std::vector<char> packet_bytes,
    const sockaddr_in& from,
    std::uint64_t arrival_microseconds,
    bool physical_datagram) {
    if (packet_bytes.empty() ||
        packet_bytes.size() >
            kLocalUdpMaximumLogicalPacketBytes ||
        packet_bytes.size() >
            sizeof(TransportPacketBuffer)) {
        return false;
    }

    const auto header = ReadTelemetryPacketHeader(
        packet_bytes.data(),
        packet_bytes.size());
    const auto logical_bytes = packet_bytes.size();
    std::vector<DroppedLocalUdpPacket> dropped_packets;
    std::size_t queue_depth = 0;
    std::size_t queue_bytes = 0;
    bool enqueued = false;
    {
        std::lock_guard<std::mutex> lock(
            g_local_udp_ingress_mutex);
        while (!g_local_udp_ingress_packets.empty() &&
               (g_local_udp_ingress_packets.size() >=
                    kLocalUdpMaximumIngressPackets ||
                g_local_udp_ingress_bytes +
                        packet_bytes.size() >
                    kLocalUdpMaximumIngressBytes)) {
            auto& oldest =
                g_local_udp_ingress_packets.front();
            const auto oldest_header =
                ReadTelemetryPacketHeader(
                    oldest.bytes.data(),
                    oldest.bytes.size());
            const auto oldest_bytes = oldest.bytes.size();
            g_local_udp_ingress_bytes -= oldest_bytes;
            g_local_udp_ingress_packets.pop_front();
            ++g_local_udp_ingress_dropped_packets;
            g_local_udp_ingress_dropped_bytes +=
                oldest_bytes;
            dropped_packets.push_back({
                oldest_header.kind,
                oldest_header.sequence,
                oldest_bytes,
                g_local_udp_ingress_packets.size(),
                g_local_udp_ingress_bytes,
                g_local_udp_ingress_dropped_packets,
                g_local_udp_ingress_dropped_bytes,
            });
        }
        if (g_local_udp_ingress_packets.size() >=
                kLocalUdpMaximumIngressPackets ||
            g_local_udp_ingress_bytes +
                    packet_bytes.size() >
                kLocalUdpMaximumIngressBytes) {
            ++g_local_udp_ingress_dropped_packets;
            g_local_udp_ingress_dropped_bytes +=
                packet_bytes.size();
            dropped_packets.push_back({
                header.kind,
                header.sequence,
                packet_bytes.size(),
                g_local_udp_ingress_packets.size(),
                g_local_udp_ingress_bytes,
                g_local_udp_ingress_dropped_packets,
                g_local_udp_ingress_dropped_bytes,
            });
        } else {
            g_local_udp_ingress_bytes +=
                packet_bytes.size();
            g_local_udp_ingress_packets.push_back({
                std::move(packet_bytes),
                from,
                arrival_microseconds,
            });
            enqueued = true;
        }
        queue_depth = g_local_udp_ingress_packets.size();
        queue_bytes = g_local_udp_ingress_bytes;
    }

    RecordDroppedLocalUdpPackets(dropped_packets);
    if (!enqueued) {
        return false;
    }
    RecordNetworkPacketReceive(
        header.kind,
        header.sequence,
        logical_bytes,
        ntohl(from.sin_addr.s_addr),
        ntohs(from.sin_port),
        queue_depth,
        queue_bytes,
        physical_datagram);
    return true;
}

void ProcessLocalUdpDatagram(
    const char* datagram,
    std::size_t datagram_bytes,
    const sockaddr_in& from,
    std::uint64_t arrival_microseconds) {
    if (datagram == nullptr || datagram_bytes == 0) {
        return;
    }

    if (IsLocalUdpFragmentMagic(
            datagram,
            datagram_bytes)) {
        LocalUdpFragmentHeader fragment_header{};
        if (datagram_bytes >= sizeof(fragment_header)) {
            std::memcpy(
                &fragment_header,
                datagram,
                sizeof(fragment_header));
        }
        std::vector<std::uint8_t> completed_packet;
        const auto result =
            g_local_udp_fragment_reassembler.Accept(
                LocalUdpEndpointKey(from),
                datagram,
                datagram_bytes,
                arrival_microseconds,
                &completed_packet);
        const bool accepted =
            result !=
            LocalUdpFragmentAcceptResult::Invalid;
        const bool complete =
            result ==
            LocalUdpFragmentAcceptResult::Complete;
        RecordNetworkFragmentReceive(
            fragment_header.original_kind,
            fragment_header.original_sequence,
            fragment_header.total_bytes,
            datagram_bytes,
            fragment_header.fragment_index,
            fragment_header.fragment_count,
            ntohl(from.sin_addr.s_addr),
            ntohs(from.sin_port),
            accepted,
            complete);
        if (!complete) {
            return;
        }

        std::vector<char> packet(
            completed_packet.begin(),
            completed_packet.end());
        (void)EnqueueLocalUdpPacket(
            std::move(packet),
            from,
            arrival_microseconds,
            false);
        return;
    }

    if (datagram_bytes >
        kLocalUdpMaximumDatagramBytes) {
        const auto header =
            ReadTelemetryPacketHeader(
                datagram,
                datagram_bytes);
        std::uint64_t dropped_packets = 0;
        std::uint64_t dropped_bytes = 0;
        std::size_t queue_depth = 0;
        std::size_t queue_bytes = 0;
        {
            std::lock_guard<std::mutex> lock(
                g_local_udp_ingress_mutex);
            ++g_local_udp_ingress_dropped_packets;
            g_local_udp_ingress_dropped_bytes +=
                datagram_bytes;
            dropped_packets =
                g_local_udp_ingress_dropped_packets;
            dropped_bytes =
                g_local_udp_ingress_dropped_bytes;
            queue_depth =
                g_local_udp_ingress_packets.size();
            queue_bytes = g_local_udp_ingress_bytes;
        }
        RecordNetworkIngressDrop(
            header.kind,
            header.sequence,
            datagram_bytes,
            queue_depth,
            queue_bytes,
            dropped_packets,
            dropped_bytes);
        return;
    }

    std::vector<char> packet(
        datagram,
        datagram + datagram_bytes);
    (void)EnqueueLocalUdpPacket(
        std::move(packet),
        from,
        arrival_microseconds,
        true);
}

unsigned __stdcall LocalUdpIngressWorkerMain(void* parameter) {
    const auto socket_handle =
        reinterpret_cast<SOCKET>(parameter);
    std::array<
        char,
        kLocalUdpMaximumLogicalPacketBytes> datagram{};
    while (!g_local_udp_ingress_stop_requested.load(
        std::memory_order_acquire)) {
        fd_set read_set;
        FD_ZERO(&read_set);
        FD_SET(socket_handle, &read_set);
        timeval timeout{};
        timeout.tv_usec =
            kLocalUdpIngressPollMicroseconds;
        const int ready = select(
            0,
            &read_set,
            nullptr,
            nullptr,
            &timeout);
        if (ready == SOCKET_ERROR) {
            if (!g_local_udp_ingress_stop_requested.load(
                    std::memory_order_acquire)) {
                Sleep(1);
            }
            continue;
        }
        if (ready == 0) {
            g_local_udp_fragment_reassembler.Prune(
                NetworkTelemetryNowMicroseconds());
            continue;
        }

        for (;;) {
            sockaddr_in from{};
            int from_length = sizeof(from);
            const int received = recvfrom(
                socket_handle,
                datagram.data(),
                static_cast<int>(datagram.size()),
                0,
                reinterpret_cast<sockaddr*>(&from),
                &from_length);
            if (received == SOCKET_ERROR) {
                const auto error = WSAGetLastError();
                if (error != WSAEWOULDBLOCK &&
                    error != WSAEINTR &&
                    !g_local_udp_ingress_stop_requested.load(
                        std::memory_order_acquire)) {
                    const auto snapshot =
                        SnapshotLocalUdpIngressQueue();
                    RecordNetworkIngressDrop(
                        0,
                        0,
                        0,
                        snapshot.packet_count,
                        snapshot.byte_count,
                        snapshot.dropped_packets,
                        snapshot.dropped_bytes);
                }
                break;
            }
            ProcessLocalUdpDatagram(
                datagram.data(),
                static_cast<std::size_t>(received),
                from,
            NetworkTelemetryNowMicroseconds());
        }
    }
    return 0;
}

bool StartLocalUdpIngressWorker(
    SOCKET socket_handle) {
    if (socket_handle == INVALID_SOCKET ||
        g_local_udp_ingress_thread != nullptr) {
        return false;
    }
    {
        std::lock_guard<std::mutex> lock(
            g_local_udp_ingress_mutex);
        g_local_udp_ingress_packets.clear();
        g_local_udp_ingress_bytes = 0;
        g_local_udp_ingress_dropped_packets = 0;
        g_local_udp_ingress_dropped_bytes = 0;
    }
    g_local_udp_fragment_reassembler.Clear();
    g_local_udp_ingress_stop_requested.store(
        false,
        std::memory_order_release);
    const auto ingress_thread = _beginthreadex(
        nullptr,
        0,
        &LocalUdpIngressWorkerMain,
        reinterpret_cast<void*>(socket_handle),
        0,
        nullptr);
    if (ingress_thread == 0) {
        g_local_udp_ingress_stop_requested.store(
            true,
            std::memory_order_release);
        return false;
    }
    g_local_udp_ingress_thread =
        reinterpret_cast<HANDLE>(ingress_thread);
    return true;
}

void StopLocalUdpIngressWorker() {
    g_local_udp_ingress_stop_requested.store(
        true,
        std::memory_order_release);
    if (g_local_udp_ingress_thread != nullptr) {
        WaitForSingleObject(
            g_local_udp_ingress_thread,
            INFINITE);
        CloseHandle(g_local_udp_ingress_thread);
        g_local_udp_ingress_thread = nullptr;
    }
    g_local_udp_fragment_reassembler.Clear();
    std::lock_guard<std::mutex> lock(
        g_local_udp_ingress_mutex);
    g_local_udp_ingress_packets.clear();
    g_local_udp_ingress_bytes = 0;
}

bool TakeNextLocalUdpPacket(
    QueuedLocalUdpPacket* packet) {
    if (packet == nullptr) {
        return false;
    }
    std::lock_guard<std::mutex> lock(
        g_local_udp_ingress_mutex);
    if (g_local_udp_ingress_packets.empty()) {
        return false;
    }
    *packet = std::move(
        g_local_udp_ingress_packets.front());
    g_local_udp_ingress_bytes -= packet->bytes.size();
    g_local_udp_ingress_packets.pop_front();
    return true;
}

void ReceivePackets(std::uint64_t now_ms) {
    if (g_local_transport.backend !=
        GameplayTransportBackend::LocalUdp) {
        return;
    }

    const bool telemetry_enabled =
        IsNetworkTelemetryEnabled();
    const auto batch_started_us =
        NetworkTelemetryNowMicroseconds();
    const auto queue_start =
        SnapshotLocalUdpIngressQueue();
    const auto oldest_queue_age_us =
        telemetry_enabled &&
            queue_start.oldest_arrival_microseconds != 0 &&
            batch_started_us >=
                queue_start.oldest_arrival_microseconds
        ? batch_started_us -
            queue_start.oldest_arrival_microseconds
        : 0;

    std::size_t packet_count = 0;
    std::size_t byte_count = 0;
    bool time_limit_reached = false;
    for (int packet_index = 0;
         packet_index < kMaxPacketsPerTick;
         ++packet_index) {
        QueuedLocalUdpPacket queued_packet;
        if (!TakeNextLocalUdpPacket(&queued_packet)) {
            break;
        }

        TransportPacketBuffer packet_buffer{};
        const auto received = queued_packet.bytes.size();
        std::memcpy(
            packet_buffer.data(),
            queued_packet.bytes.data(),
            received);
        TransportPeerEndpoint from;
        from.backend = GameplayTransportBackend::LocalUdp;
        from.udp_address = queued_packet.from;
        const auto header = ReadTelemetryPacketHeader(
            packet_buffer.data(),
            received);
        const auto apply_started_us = telemetry_enabled
            ? NetworkTelemetryNowMicroseconds()
            : 0;
        const auto accepted_before = telemetry_enabled
            ? g_local_transport.packets_received
            : 0;
        DispatchReceivedPacket(
            packet_buffer,
            static_cast<int>(received),
            from,
            now_ms);
        ++packet_count;
        byte_count += received;
        const auto apply_finished_us =
            NetworkTelemetryNowMicroseconds();
        if (telemetry_enabled) {
            const auto queue_age_us =
                apply_started_us >=
                    queued_packet.arrival_microseconds
                ? apply_started_us -
                    queued_packet.arrival_microseconds
                : 0;
            RecordNetworkPacketApply(
                header.kind,
                header.sequence,
                received,
                g_local_transport.packets_received >
                    accepted_before,
                queue_age_us,
                apply_finished_us -
                    apply_started_us);
        }
        if (apply_finished_us - batch_started_us >=
            kMaximumPacketApplyBatchMicroseconds) {
            time_limit_reached = true;
            break;
        }
    }

    const auto queue_end =
        SnapshotLocalUdpIngressQueue();
    const bool packet_limit_reached =
        packet_count ==
            static_cast<std::size_t>(
                kMaxPacketsPerTick) &&
        queue_end.packet_count != 0;
    RecordNetworkReceiveBatch(
        packet_count,
        byte_count,
        packet_limit_reached,
        time_limit_reached &&
            queue_end.packet_count != 0,
        0,
        queue_start.packet_count,
        queue_end.packet_count,
        queue_start.byte_count,
        queue_end.byte_count,
        oldest_queue_age_us,
        telemetry_enabled
            ? NetworkTelemetryNowMicroseconds() -
                batch_started_us
            : 0);
}
