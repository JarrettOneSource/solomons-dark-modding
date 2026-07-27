#include "multiplayer_steam_gameplay_queue_policy.h"

#include <cstdint>
#include <iostream>
#include <unordered_map>
#include <vector>

namespace sdmod::multiplayer {
namespace {

bool Require(bool condition, const char* message) {
    if (!condition) {
        std::cerr << message << '\n';
    }
    return condition;
}

bool ReliablePacketsSurviveTemporaryLimitExceeded() {
    SteamGameplayOutboundQueuePolicy queue;
    const std::uint32_t payload = 1;
    if (!queue.Queue(
            11,
            &payload,
            sizeof(payload),
            SteamNetworkSendMode::ReliableNoNagle)) {
        return false;
    }

    std::size_t attempts = 0;
    const SteamGameplaySendFunction send =
        [&](std::uint64_t,
            const void*,
            std::size_t,
            SteamNetworkSendMode,
            std::int32_t* result_code) {
            attempts += 1;
            if (attempts == 1) {
                *result_code =
                    SteamGameplayOutboundQueuePolicy::
                        kResultLimitExceeded;
                return false;
            }
            *result_code = 1;
            return true;
        };

    if (!Require(
            queue.Service(100, send).empty(),
            "temporary saturation requested route recovery") ||
        !Require(
            queue.SnapshotStats().queued_outbound_packets == 1,
            "reliable packet was discarded on result 25") ||
        !Require(
            queue.SnapshotStats().congested_peers == 1,
            "peer did not enter backpressure") ||
        !Require(
            queue.Service(200, send).empty() &&
                attempts == 1,
            "backpressure retry interval was ignored") ||
        !Require(
            queue.Service(350, send).empty(),
            "successful retry requested route recovery")) {
        return false;
    }

    const auto stats = queue.SnapshotStats();
    return Require(
               attempts == 2,
               "reliable packet was not retried") &&
        Require(
            stats.packets_sent == 1 &&
                stats.queued_outbound_packets == 0,
            "successful retry did not drain the reliable packet") &&
        Require(
            stats.congested_peers == 0,
            "successful retry did not clear backpressure");
}

bool DisposableTrafficCoalescesWithoutBlockingOtherPeers() {
    SteamGameplayOutboundQueuePolicy queue;
    const std::uint32_t first = 1;
    const std::uint32_t other = 2;
    queue.Queue(
        11,
        &first,
        sizeof(first),
        SteamNetworkSendMode::UnreliableNoDelay);
    queue.Queue(
        22,
        &other,
        sizeof(other),
        SteamNetworkSendMode::ReliableNoNagle);

    std::unordered_map<std::uint64_t, std::size_t> attempts;
    const SteamGameplaySendFunction send =
        [&](std::uint64_t peer,
            const void*,
            std::size_t,
            SteamNetworkSendMode,
            std::int32_t* result_code) {
            attempts[peer] += 1;
            if (peer == 11) {
                *result_code =
                    SteamGameplayOutboundQueuePolicy::
                        kResultLimitExceeded;
                return false;
            }
            *result_code = 1;
            return true;
        };
    queue.Service(100, send);
    if (!Require(
            attempts[11] == 1 && attempts[22] == 1,
            "one saturated peer blocked an independent peer")) {
        return false;
    }

    for (std::uint32_t value = 3; value <= 5; ++value) {
        queue.Queue(
            11,
            &value,
            sizeof(value),
            SteamNetworkSendMode::UnreliableNoDelay);
    }
    const auto stats = queue.SnapshotStats();
    return Require(
               stats.queued_outbound_packets == 1,
               "disposable congestion backlog was not coalesced") &&
        Require(
            stats.dropped_outbound_packets == 3,
            "coalesced disposable packet accounting is wrong") &&
        Require(
            stats.packets_sent == 1,
            "independent peer packet was not sent");
}

bool SustainedLimitExceededRequestsOneRouteRecovery() {
    SteamGameplayOutboundQueuePolicy queue;
    const std::uint32_t payload = 1;
    queue.Queue(
        11,
        &payload,
        sizeof(payload),
        SteamNetworkSendMode::ReliableNoNagle);
    const SteamGameplaySendFunction reject =
        [](std::uint64_t,
           const void*,
           std::size_t,
           SteamNetworkSendMode,
           std::int32_t* result_code) {
            *result_code =
                SteamGameplayOutboundQueuePolicy::
                    kResultLimitExceeded;
            return false;
        };

    std::vector<SteamGameplayCongestionEvent> events;
    for (std::uint64_t now_ms :
         {100ull, 350ull, 600ull, 850ull, 1100ull,
          1350ull, 1600ull, 1850ull, 2100ull}) {
        const auto tick_events =
            queue.Service(now_ms, reject);
        events.insert(
            events.end(),
            tick_events.begin(),
            tick_events.end());
    }
    if (!Require(
            events.size() == 1,
            "sustained congestion did not request exactly one recovery") ||
        !Require(
            events.front().remote_steam_id == 11 &&
                events.front().duration_ms == 2000 &&
                events.front().queued_reliable_packets == 1,
            "congestion recovery event lost peer or backlog state") ||
        !Require(
            queue.Service(2350, reject).empty(),
            "congestion recovery was emitted twice")) {
        return false;
    }

    queue.ResetPeer(11);
    const auto stats = queue.SnapshotStats();
    return Require(
               stats.queued_outbound_packets == 0 &&
                   stats.congested_peers == 0,
               "peer route reset did not clear stale backlog") &&
        Require(
            stats.congestion_recoveries == 1,
            "route recovery accounting is wrong");
}

}  // namespace
}  // namespace sdmod::multiplayer

int main() {
    using namespace sdmod::multiplayer;
    if (!ReliablePacketsSurviveTemporaryLimitExceeded() ||
        !DisposableTrafficCoalescesWithoutBlockingOtherPeers() ||
        !SustainedLimitExceededRequestsOneRouteRecovery()) {
        return 1;
    }
    std::cout << "Steam gameplay queue policy tests passed\n";
    return 0;
}
