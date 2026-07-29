#include "multiplayer_runtime_protocol.h"
#include "multiplayer_steam_gameplay_queue_policy.h"

#include <cstdint>
#include <cstring>
#include <iostream>
#include <unordered_map>
#include <utility>
#include <vector>

namespace sdmod::multiplayer {
namespace {

constexpr std::uint64_t kLimitedPeer = 11;
constexpr std::uint64_t kHealthyPeer = 22;

bool Require(bool condition, const char* message) {
    if (!condition) {
        std::cerr << message << '\n';
    }
    return condition;
}

SteamGameplayRouteQueueStatus ConnectedRoute(
    std::int64_t queue_time_microseconds = 0) {
    SteamGameplayRouteQueueStatus status;
    status.connected = true;
    status.send_rate_bytes_per_second = 64 * 1024;
    status.queue_time_microseconds = queue_time_microseconds;
    return status;
}

SteamGameplayRouteStatusFunction HealthyRoute() {
    return [](std::uint64_t) {
        return ConnectedRoute();
    };
}

WorldSnapshotPacket WorldFragment(
    std::uint32_t packet_sequence,
    std::uint32_t snapshot_id,
    std::uint16_t fragment_index,
    std::uint16_t fragment_count) {
    WorldSnapshotPacket packet{};
    packet.header = MakePacketHeader(
        PacketKind::WorldSnapshot,
        packet_sequence);
    packet.authority_participant_id = 101;
    packet.scene_epoch = 7;
    packet.run_nonce = 9;
    packet.snapshot_id = snapshot_id;
    packet.fragment_index = fragment_index;
    packet.fragment_count = fragment_count;
    packet.actor_start_index = static_cast<std::uint16_t>(
        fragment_index * kWorldSnapshotActorsPerFragment);
    packet.actor_total_count =
        static_cast<std::uint32_t>(fragment_count) *
        kWorldSnapshotActorsPerFragment;
    packet.scene_kind =
        static_cast<std::uint8_t>(WorldSceneKind::Run);
    return packet;
}

ParticipantHitFeedbackPacket HitFeedback(
    std::uint32_t packet_sequence,
    std::uint32_t event_sequence) {
    ParticipantHitFeedbackPacket packet{};
    packet.header = MakePacketHeader(
        PacketKind::ParticipantHitFeedback,
        packet_sequence);
    packet.authority_participant_id = 101;
    packet.target_participant_id = 202;
    packet.event_sequence = event_sequence;
    packet.run_nonce = 9;
    return packet;
}

bool ReliablePacketsSurviveTemporaryLimitExceeded() {
    SteamGameplayOutboundQueuePolicy queue;
    const std::uint32_t payload = 1;
    if (!queue.Queue(
            kLimitedPeer,
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
    const auto route = HealthyRoute();

    if (!Require(
            queue.Service(100, send, route).empty(),
            "temporary saturation emitted a sustained diagnostic") ||
        !Require(
            queue.SnapshotStats().queued_outbound_packets == 1,
            "reliable packet was discarded on result 25") ||
        !Require(
            queue.SnapshotStats().congested_peers == 1,
            "peer did not enter backpressure") ||
        !Require(
            queue.Service(200, send, route).empty() &&
                attempts == 1,
            "backpressure retry interval was ignored") ||
        !Require(
            queue.Service(350, send, route).empty(),
            "successful retry emitted a sustained diagnostic")) {
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

bool ProactiveRoutePacingKeepsOnlyFreshState() {
    SteamGameplayOutboundQueuePolicy queue;
    StatePacket first{};
    first.header = MakePacketHeader(PacketKind::State, 1);
    first.participant_id = 101;
    StatePacket latest = first;
    latest.header.sequence = 2;

    if (!queue.Queue(
            kLimitedPeer,
            &first,
            sizeof(first),
            SteamNetworkSendMode::ReliableNoNagle)) {
        return false;
    }

    std::int64_t route_queue_time = 300'000;
    std::size_t attempts = 0;
    std::uint32_t delivered_sequence = 0;
    const SteamGameplayRouteStatusFunction route =
        [&](std::uint64_t) {
            return ConnectedRoute(route_queue_time);
        };
    const SteamGameplaySendFunction send =
        [&](std::uint64_t,
            const void* data,
            std::size_t size,
            SteamNetworkSendMode,
            std::int32_t* result_code) {
            attempts += 1;
            StatePacket packet{};
            if (size == sizeof(packet)) {
                std::memcpy(&packet, data, sizeof(packet));
                delivered_sequence = packet.header.sequence;
            }
            *result_code = 1;
            return true;
        };

    queue.Service(100, send, route);
    if (!Require(
            attempts == 0,
            "gameplay entered an already delayed Steam route") ||
        !Require(
            queue.SnapshotStats().congested_peers == 1,
            "proactive route pressure was not tracked") ||
        !Require(
            queue.Queue(
                kLimitedPeer,
                &latest,
                sizeof(latest),
                SteamNetworkSendMode::ReliableNoNagle),
            "fresh state was rejected during route pressure") ||
        !Require(
            queue.SnapshotStats().queued_outbound_packets == 1,
            "superseded state accumulated in the app queue")) {
        return false;
    }

    route_queue_time = 60'000;
    queue.Service(200, send, route);
    if (!Require(
            attempts == 0,
            "route-pressure hysteresis resumed above low water")) {
        return false;
    }

    route_queue_time = 49'000;
    queue.Service(201, send, route);
    const auto stats = queue.SnapshotStats();
    return Require(
               attempts == 1 && delivered_sequence == 2,
               "route recovery did not send only the freshest state") &&
        Require(
            stats.limit_exceeded_failures == 0,
            "proactive pacing waited for a result-25 rejection") &&
        Require(
            stats.superseded_outbound_packets == 1,
            "state supersession accounting is wrong") &&
        Require(
            stats.queued_outbound_packets == 0 &&
                stats.congested_peers == 0,
            "route recovery did not clear queue pressure");
}

bool RoutePressureDoesNotBlockAnotherPeer() {
    SteamGameplayOutboundQueuePolicy queue;
    for (std::uint32_t value = 1; value <= 10; ++value) {
        if (!queue.Queue(
                kLimitedPeer,
                &value,
                sizeof(value),
                SteamNetworkSendMode::ReliableNoNagle)) {
            return false;
        }
    }
    const std::uint32_t healthy_payload = 99;
    if (!queue.Queue(
            kHealthyPeer,
            &healthy_payload,
            sizeof(healthy_payload),
            SteamNetworkSendMode::ReliableNoNagle)) {
        return false;
    }

    std::unordered_map<std::uint64_t, std::size_t> route_checks;
    std::unordered_map<std::uint64_t, std::size_t> sends;
    const SteamGameplayRouteStatusFunction route =
        [&](std::uint64_t peer) {
            const auto check = ++route_checks[peer];
            if (peer == kLimitedPeer && check > 3) {
                return ConnectedRoute(300'000);
            }
            return ConnectedRoute();
        };
    const SteamGameplaySendFunction send =
        [&](std::uint64_t peer,
            const void*,
            std::size_t,
            SteamNetworkSendMode,
            std::int32_t* result_code) {
            sends[peer] += 1;
            *result_code = 1;
            return true;
        };

    queue.Service(100, send, route);
    return Require(
               sends[kLimitedPeer] == 3,
               "service continued feeding a route after high water") &&
        Require(
            sends[kHealthyPeer] == 1,
            "one pressured peer blocked an independent peer") &&
        Require(
            queue.SnapshotStats().queued_outbound_packets == 7,
            "route pressure lost or sent the wrong peer backlog") &&
        Require(
            queue.SnapshotStats().congested_peers == 1,
            "only the pressured peer should be congested");
}

bool LatestWorldGenerationSupersedesStaleFragments() {
    SteamGameplayOutboundQueuePolicy queue;
    for (std::uint16_t fragment = 0; fragment < 3; ++fragment) {
        const auto packet = WorldFragment(
            static_cast<std::uint32_t>(fragment + 1),
            100,
            fragment,
            3);
        if (!queue.Queue(
                kLimitedPeer,
                &packet,
                sizeof(packet),
                SteamNetworkSendMode::ReliableNoNagle)) {
            return false;
        }
    }

    auto packet = WorldFragment(10, 101, 0, 4);
    queue.Queue(
        kLimitedPeer,
        &packet,
        sizeof(packet),
        SteamNetworkSendMode::ReliableNoNagle);
    const auto stale = WorldFragment(11, 100, 2, 3);
    queue.Queue(
        kLimitedPeer,
        &stale,
        sizeof(stale),
        SteamNetworkSendMode::ReliableNoNagle);
    for (std::uint16_t fragment = 1; fragment < 4; ++fragment) {
        packet = WorldFragment(
            static_cast<std::uint32_t>(11 + fragment),
            101,
            fragment,
            4);
        queue.Queue(
            kLimitedPeer,
            &packet,
            sizeof(packet),
            SteamNetworkSendMode::ReliableNoNagle);
    }
    packet = WorldFragment(20, 101, 2, 4);
    queue.Queue(
        kLimitedPeer,
        &packet,
        sizeof(packet),
        SteamNetworkSendMode::ReliableNoNagle);

    std::vector<std::pair<std::uint32_t, std::uint16_t>> delivered;
    const SteamGameplaySendFunction send =
        [&](std::uint64_t,
            const void* data,
            std::size_t size,
            SteamNetworkSendMode,
            std::int32_t* result_code) {
            WorldSnapshotPacket sent{};
            if (size == sizeof(sent)) {
                std::memcpy(&sent, data, sizeof(sent));
                delivered.emplace_back(
                    sent.snapshot_id,
                    sent.fragment_index);
            }
            *result_code = 1;
            return true;
        };
    queue.Service(100, send, HealthyRoute());

    return Require(
               delivered ==
                   std::vector<
                       std::pair<std::uint32_t, std::uint16_t>>{
                       {101, 0},
                       {101, 1},
                       {101, 3},
                       {101, 2},
                   },
               "latest complete world generation was split or regressed") &&
        Require(
            queue.SnapshotStats().queued_outbound_packets == 0,
            "latest world generation did not drain") &&
        Require(
            queue.SnapshotStats().superseded_outbound_packets >= 5,
            "world generation supersession was not accounted");
}

bool CapacityEvictsWholeReplaceableGeneration() {
    SteamGameplayOutboundQueuePolicy queue;
    for (std::size_t index = 0;
         index <
         SteamGameplayOutboundQueuePolicy::kMaximumQueuedPackets - 3;
         ++index) {
        const auto payload = static_cast<std::uint32_t>(index);
        if (!queue.Queue(
                kLimitedPeer,
                &payload,
                sizeof(payload),
                SteamNetworkSendMode::ReliableNoNagle)) {
            return false;
        }
    }
    for (std::uint16_t fragment = 0; fragment < 3; ++fragment) {
        const auto packet = WorldFragment(
            static_cast<std::uint32_t>(fragment + 1),
            200,
            fragment,
            3);
        if (!queue.Queue(
                kLimitedPeer,
                &packet,
                sizeof(packet),
                SteamNetworkSendMode::ReliableNoNagle)) {
            return false;
        }
    }
    StatePacket state{};
    state.header = MakePacketHeader(PacketKind::State, 50);
    state.participant_id = 101;
    if (!queue.Queue(
            kLimitedPeer,
            &state,
            sizeof(state),
            SteamNetworkSendMode::ReliableNoNagle)) {
        return false;
    }

    std::size_t delivered_world_fragments = 0;
    const SteamGameplaySendFunction send =
        [&](std::uint64_t,
            const void* data,
            std::size_t size,
            SteamNetworkSendMode,
            std::int32_t* result_code) {
            if (size >= sizeof(PacketHeader)) {
                PacketHeader header{};
                std::memcpy(&header, data, sizeof(header));
                if (IsValidPacketHeader(header) &&
                    static_cast<PacketKind>(header.kind) ==
                        PacketKind::WorldSnapshot) {
                    delivered_world_fragments += 1;
                }
            }
            *result_code = 1;
            return true;
        };
    for (std::uint64_t now_ms = 100;
         queue.SnapshotStats().queued_outbound_packets != 0;
         now_ms += 16) {
        queue.Service(now_ms, send, HealthyRoute());
    }

    const auto stats = queue.SnapshotStats();
    return Require(
               delivered_world_fragments == 0,
               "capacity eviction left a partial world generation") &&
        Require(
            stats.dropped_outbound_packets == 3,
            "whole-generation eviction accounting is wrong");
}

bool ReliableRecoveryRetriesAreDeduplicatedAfterAcceptance() {
    SteamGameplayOutboundQueuePolicy queue;
    auto first = HitFeedback(1, 7);
    auto first_retry = HitFeedback(2, 7);
    auto second = HitFeedback(3, 8);
    queue.Queue(
        kLimitedPeer,
        &first,
        sizeof(first),
        SteamNetworkSendMode::ReliableNoNagle);
    queue.Queue(
        kLimitedPeer,
        &first_retry,
        sizeof(first_retry),
        SteamNetworkSendMode::ReliableNoNagle);
    queue.Queue(
        kLimitedPeer,
        &second,
        sizeof(second),
        SteamNetworkSendMode::ReliableNoNagle);

    std::vector<std::uint32_t> delivered;
    const SteamGameplaySendFunction send =
        [&](std::uint64_t,
            const void* data,
            std::size_t size,
            SteamNetworkSendMode,
            std::int32_t* result_code) {
            ParticipantHitFeedbackPacket packet{};
            if (size == sizeof(packet)) {
                std::memcpy(&packet, data, sizeof(packet));
                delivered.push_back(packet.event_sequence);
            }
            *result_code = 1;
            return true;
        };
    queue.Service(100, send, HealthyRoute());
    if (!Require(
            delivered == std::vector<std::uint32_t>{7, 8},
            "distinct recovery events were collapsed or reordered")) {
        return false;
    }

    first_retry.header.sequence = 4;
    if (!queue.Queue(
            kLimitedPeer,
            &first_retry,
            sizeof(first_retry),
            SteamNetworkSendMode::ReliableNoNagle)) {
        return false;
    }
    queue.Service(200, send, HealthyRoute());
    if (!Require(
            delivered == std::vector<std::uint32_t>{7, 8},
            "accepted reliable recovery retry re-entered Steam")) {
        return false;
    }

    queue.ResetPeer(kLimitedPeer);
    first_retry.header.sequence = 5;
    queue.Queue(
        kLimitedPeer,
        &first_retry,
        sizeof(first_retry),
        SteamNetworkSendMode::ReliableNoNagle);
    queue.Service(300, send, HealthyRoute());
    return Require(
               delivered == std::vector<std::uint32_t>{7, 8, 7},
               "peer reset did not reopen recovery delivery") &&
        Require(
            queue.SnapshotStats().superseded_outbound_packets == 2,
            "recovery retry deduplication accounting is wrong");
}

bool OrderedReliablePacketsRemainOrdered() {
    SteamGameplayOutboundQueuePolicy queue;
    SessionGoodbyePacket first{};
    first.header = MakePacketHeader(PacketKind::SessionGoodbye, 1);
    SessionGoodbyePacket second = first;
    second.header.sequence = 2;
    queue.Queue(
        kLimitedPeer,
        &first,
        sizeof(first),
        SteamNetworkSendMode::ReliableNoNagle);
    queue.Queue(
        kLimitedPeer,
        &second,
        sizeof(second),
        SteamNetworkSendMode::ReliableNoNagle);

    std::vector<std::uint32_t> delivered;
    const SteamGameplaySendFunction send =
        [&](std::uint64_t,
            const void* data,
            std::size_t,
            SteamNetworkSendMode,
            std::int32_t* result_code) {
            PacketHeader header{};
            std::memcpy(&header, data, sizeof(header));
            delivered.push_back(header.sequence);
            *result_code = 1;
            return true;
        };
    queue.Service(100, send, HealthyRoute());
    return Require(
        delivered == std::vector<std::uint32_t>{1, 2},
        "ordered reliable events were collapsed or reordered");
}

bool ResetPeerDropsOnlyTheTargetPeer() {
    SteamGameplayOutboundQueuePolicy queue;
    const std::uint32_t first = 1;
    const std::uint32_t second = 2;
    queue.Queue(
        kLimitedPeer,
        &first,
        sizeof(first),
        SteamNetworkSendMode::ReliableNoNagle);
    queue.Queue(
        kHealthyPeer,
        &second,
        sizeof(second),
        SteamNetworkSendMode::ReliableNoNagle);
    queue.ResetPeer(kLimitedPeer);

    std::vector<std::uint64_t> delivered;
    const SteamGameplaySendFunction send =
        [&](std::uint64_t peer,
            const void*,
            std::size_t,
            SteamNetworkSendMode,
            std::int32_t* result_code) {
            delivered.push_back(peer);
            *result_code = 1;
            return true;
        };
    queue.Service(100, send, HealthyRoute());
    return Require(
               delivered == std::vector<std::uint64_t>{kHealthyPeer},
               "peer reset disturbed an independent route") &&
        Require(
            queue.SnapshotStats().queued_outbound_packets == 0,
            "peer reset left stale packets queued");
}

}  // namespace
}  // namespace sdmod::multiplayer

int main() {
    using namespace sdmod::multiplayer;
    if (!ReliablePacketsSurviveTemporaryLimitExceeded() ||
        !ProactiveRoutePacingKeepsOnlyFreshState() ||
        !RoutePressureDoesNotBlockAnotherPeer() ||
        !LatestWorldGenerationSupersedesStaleFragments() ||
        !CapacityEvictsWholeReplaceableGeneration() ||
        !ReliableRecoveryRetriesAreDeduplicatedAfterAcceptance() ||
        !OrderedReliablePacketsRemainOrdered() ||
        !ResetPeerDropsOnlyTheTargetPeer()) {
        return 1;
    }
    std::cout << "Steam gameplay queue policy tests passed\n";
    return 0;
}
