#pragma once

#include "steam_bootstrap.h"

#include <cstddef>
#include <cstdint>
#include <deque>
#include <functional>
#include <unordered_map>
#include <vector>

namespace sdmod::multiplayer {

static_assert(
    kSteamGameplayControlChannel != kSteamSessionAndBulkChannel,
    "gameplay control traffic requires a channel independent of bulk");

struct SteamGameplayQueueStats {
    std::uint64_t packets_sent = 0;
    std::uint64_t send_failures = 0;
    std::uint64_t reliable_send_failures = 0;
    std::uint64_t limit_exceeded_failures = 0;
    std::uint64_t backpressure_episodes = 0;
    std::uint64_t sustained_backpressure_reports = 0;
    std::uint64_t dropped_outbound_packets = 0;
    std::uint64_t superseded_outbound_packets = 0;
    std::uint64_t control_packets_sent_under_pressure = 0;
    std::uint64_t dropped_inbound_packets = 0;
    std::size_t queued_outbound_packets = 0;
    std::size_t congested_peers = 0;
    std::int32_t last_send_failure_result = 0;
};

struct SteamGameplayBackpressureEvent {
    std::uint64_t remote_steam_id = 0;
    std::uint64_t first_backpressure_ms = 0;
    std::uint64_t duration_ms = 0;
    std::size_t queued_reliable_packets = 0;
    std::uint64_t dropped_disposable_packets = 0;
};

struct SteamGameplayRouteQueueStatus {
    bool connected = false;
    std::int32_t send_rate_bytes_per_second = 0;
    std::int32_t pending_unreliable_bytes = 0;
    std::int32_t pending_reliable_bytes = 0;
    std::int32_t unacked_reliable_bytes = 0;
    std::int64_t queue_time_microseconds = 0;
};

using SteamGameplaySendFunction = std::function<bool(
    std::uint64_t remote_steam_id,
    const void* data,
    std::size_t size,
    SteamNetworkSendMode mode,
    std::int32_t channel,
    std::int32_t* result_code)>;

using SteamGameplayRouteStatusFunction = std::function<
    SteamGameplayRouteQueueStatus(std::uint64_t remote_steam_id)>;

class SteamGameplayOutboundQueuePolicy {
public:
    static constexpr std::int32_t kResultLimitExceeded = 25;
    static constexpr std::size_t kMaximumQueuedPackets = 1024;
    static constexpr std::size_t kMaximumSendsPerServiceTick = 256;
    static constexpr std::size_t
        kMaximumRememberedLogicalEvents = 4096;
    static constexpr std::uint64_t kLimitRetryIntervalMs = 250;
    static constexpr std::int64_t kQueueTimeHighWaterMicroseconds =
        250'000;
    static constexpr std::int64_t kQueueTimeLowWaterMicroseconds =
        50'000;
    static constexpr std::uint64_t
        kSustainedBackpressureReportIntervalMs = 2000;

    bool Queue(
        std::uint64_t remote_steam_id,
        const void* data,
        std::size_t size,
        SteamNetworkSendMode mode);

    std::vector<SteamGameplayBackpressureEvent> Service(
        std::uint64_t now_ms,
        const SteamGameplaySendFunction& send,
        const SteamGameplayRouteStatusFunction& route_status);

    void Reset();
    void ResetPeer(std::uint64_t remote_steam_id);
    SteamGameplayQueueStats SnapshotStats() const;

private:
    enum class Retention {
        Ordered,
        LatestStream,
        LatestGeneration,
        DistinctLogicalEvent,
    };

    struct PacketIdentity {
        std::uint16_t kind = 0;
        Retention retention = Retention::Ordered;
        std::uint32_t packet_sequence = 0;
        std::uint64_t stream_id = 0;
        std::uint64_t logical_a = 0;
        std::uint64_t logical_b = 0;
        std::uint32_t fragment_index = 0;
        std::uint32_t fragment_count = 0;
    };

    struct OutboundPacket {
        std::uint64_t remote_steam_id = 0;
        SteamNetworkSendMode mode =
            SteamNetworkSendMode::UnreliableNoNagle;
        PacketIdentity identity;
        std::int32_t channel =
            kSteamSessionAndBulkChannel;
        std::vector<std::uint8_t> payload;
    };

    struct AcceptedLogicalEvent {
        std::uint64_t remote_steam_id = 0;
        PacketIdentity identity;
    };

    struct PeerBackpressure {
        bool limited = false;
        bool sustained_reported = false;
        std::uint64_t first_backpressure_ms = 0;
        std::uint64_t retry_after_ms = 0;
        std::uint64_t last_control_probe_ms = 0;
        std::uint64_t dropped_disposable_packets = 0;
    };

    static bool IsReliable(SteamNetworkSendMode mode);
    static bool IsControlPacket(
        const OutboundPacket& packet);
    static PacketIdentity DescribePacket(
        const void* data,
        std::size_t size,
        SteamNetworkSendMode mode);
    static bool Supersedes(
        const OutboundPacket& incoming,
        const OutboundPacket& queued);
    static bool IsDuplicateLogicalEvent(
        const OutboundPacket& incoming,
        const OutboundPacket& queued);
    static bool IsSameEvictionUnit(
        const OutboundPacket& left,
        const OutboundPacket& right);
    bool IsAcceptedLogicalEvent(
        const OutboundPacket& packet) const;
    void RememberAcceptedLogicalEvent(
        const OutboundPacket& packet);
    bool MakeRoom(const OutboundPacket& incoming);
    std::size_t EvictReplaceableUnit(
        std::deque<OutboundPacket>::iterator candidate);
    void RemoveSupersededPackets(
        const OutboundPacket& incoming);
    void EnterBackpressure(
        std::uint64_t remote_steam_id,
        std::uint64_t now_ms);
    bool RouteCanAcceptGameplay(
        std::uint64_t remote_steam_id,
        std::uint64_t now_ms,
        bool control_packet,
        const SteamGameplayRouteStatusFunction& route_status,
        bool* sent_under_pressure);
    std::size_t CountQueuedReliablePackets(
        std::uint64_t remote_steam_id) const;
    void RefreshGauges();

    std::deque<OutboundPacket> packets_;
    std::deque<AcceptedLogicalEvent>
        accepted_logical_events_;
    std::unordered_map<std::uint64_t, PeerBackpressure>
        backpressure_by_peer_;
    SteamGameplayQueueStats stats_;
};

}  // namespace sdmod::multiplayer
