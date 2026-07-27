#pragma once

#include "steam_bootstrap.h"

#include <cstddef>
#include <cstdint>
#include <deque>
#include <functional>
#include <unordered_map>
#include <vector>

namespace sdmod::multiplayer {

struct SteamGameplayQueueStats {
    std::uint64_t packets_sent = 0;
    std::uint64_t send_failures = 0;
    std::uint64_t reliable_send_failures = 0;
    std::uint64_t limit_exceeded_failures = 0;
    std::uint64_t backpressure_episodes = 0;
    std::uint64_t congestion_recoveries = 0;
    std::uint64_t dropped_outbound_packets = 0;
    std::uint64_t dropped_inbound_packets = 0;
    std::size_t queued_outbound_packets = 0;
    std::size_t congested_peers = 0;
    std::int32_t last_send_failure_result = 0;
};

struct SteamGameplayCongestionEvent {
    std::uint64_t remote_steam_id = 0;
    std::uint64_t first_limit_exceeded_ms = 0;
    std::uint64_t duration_ms = 0;
    std::size_t queued_reliable_packets = 0;
    std::uint64_t dropped_disposable_packets = 0;
};

using SteamGameplaySendFunction = std::function<bool(
    std::uint64_t remote_steam_id,
    const void* data,
    std::size_t size,
    SteamNetworkSendMode mode,
    std::int32_t* result_code)>;

class SteamGameplayOutboundQueuePolicy {
public:
    static constexpr std::int32_t kResultLimitExceeded = 25;
    static constexpr std::size_t kMaximumQueuedPackets = 1024;
    static constexpr std::size_t kMaximumSendsPerServiceTick = 256;
    static constexpr std::uint64_t kLimitRetryIntervalMs = 250;
    static constexpr std::uint64_t kCongestionRecoveryIntervalMs = 2000;

    bool Queue(
        std::uint64_t remote_steam_id,
        const void* data,
        std::size_t size,
        SteamNetworkSendMode mode);

    std::vector<SteamGameplayCongestionEvent> Service(
        std::uint64_t now_ms,
        const SteamGameplaySendFunction& send);

    void Reset();
    void ResetPeer(std::uint64_t remote_steam_id);
    SteamGameplayQueueStats SnapshotStats() const;

private:
    struct OutboundPacket {
        std::uint64_t remote_steam_id = 0;
        SteamNetworkSendMode mode =
            SteamNetworkSendMode::UnreliableNoNagle;
        std::vector<std::uint8_t> payload;
    };

    struct PeerBackpressure {
        bool limited = false;
        bool recovery_reported = false;
        std::uint64_t first_limit_exceeded_ms = 0;
        std::uint64_t retry_after_ms = 0;
        std::uint64_t dropped_disposable_packets = 0;
    };

    static bool IsReliable(SteamNetworkSendMode mode);
    bool MakeRoom(bool reliable);
    void RequeueReliableBeforePeerPackets(OutboundPacket packet);
    void CoalesceDisposablePackets(std::uint64_t remote_steam_id);
    std::size_t CountQueuedReliablePackets(
        std::uint64_t remote_steam_id) const;
    void RefreshGauges();

    std::deque<OutboundPacket> packets_;
    std::unordered_map<std::uint64_t, PeerBackpressure>
        backpressure_by_peer_;
    SteamGameplayQueueStats stats_;
};

}  // namespace sdmod::multiplayer
