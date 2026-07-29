#include "multiplayer_steam_gameplay_queue_policy.h"

#include "multiplayer_runtime_protocol.h"

#include <algorithm>
#include <cstddef>
#include <cstring>
#include <iterator>
#include <unordered_set>
#include <utility>

namespace sdmod::multiplayer {
namespace {

template <typename Value>
bool ReadPacketValue(
    const void* data,
    std::size_t size,
    std::size_t offset,
    Value* value) {
    if (data == nullptr ||
        value == nullptr ||
        offset > size ||
        sizeof(Value) > size - offset) {
        return false;
    }
    std::memcpy(
        value,
        static_cast<const std::uint8_t*>(data) + offset,
        sizeof(Value));
    return true;
}

std::uint64_t PackedPair(
    std::uint32_t high,
    std::uint32_t low) {
    return
        (static_cast<std::uint64_t>(high) << 32u) |
        static_cast<std::uint64_t>(low);
}

}  // namespace

bool SteamGameplayOutboundQueuePolicy::IsReliable(
    SteamNetworkSendMode mode) {
    return mode == SteamNetworkSendMode::ReliableNoNagle;
}

#include "multiplayer_steam_gameplay_packet_identity.inl"

bool SteamGameplayOutboundQueuePolicy::Supersedes(
    const OutboundPacket& incoming,
    const OutboundPacket& queued) {
    if (incoming.remote_steam_id != queued.remote_steam_id ||
        incoming.identity.kind == 0 ||
        incoming.identity.kind != queued.identity.kind ||
        incoming.identity.stream_id !=
            queued.identity.stream_id ||
        incoming.identity.retention ==
            Retention::Ordered ||
        incoming.identity.retention !=
            queued.identity.retention) {
        return false;
    }
    if (!IsReliable(incoming.mode) &&
        IsReliable(queued.mode)) {
        return false;
    }

    switch (incoming.identity.retention) {
    case Retention::LatestStream:
        if (incoming.identity.logical_a !=
            queued.identity.logical_a) {
            return false;
        }
        return
            incoming.identity.packet_sequence ==
                queued.identity.packet_sequence ||
            IsPacketSequenceNewer(
                incoming.identity.packet_sequence,
                queued.identity.packet_sequence);
    case Retention::LatestGeneration:
        if (incoming.identity.logical_a !=
            queued.identity.logical_a) {
            return IsPacketSequenceNewer(
                incoming.identity.packet_sequence,
                queued.identity.packet_sequence);
        }
        if (incoming.identity.logical_b !=
            queued.identity.logical_b) {
            return IsPacketSequenceNewer(
                static_cast<std::uint32_t>(
                    incoming.identity.logical_b),
                static_cast<std::uint32_t>(
                    queued.identity.logical_b));
        }
        if (incoming.identity.fragment_index !=
            queued.identity.fragment_index) {
            return false;
        }
        return
            incoming.identity.packet_sequence ==
                queued.identity.packet_sequence ||
            IsPacketSequenceNewer(
                incoming.identity.packet_sequence,
                queued.identity.packet_sequence);
    case Retention::DistinctLogicalEvent:
        return false;
    case Retention::Ordered:
    default:
        return false;
    }
}

bool SteamGameplayOutboundQueuePolicy::
    IsDuplicateLogicalEvent(
        const OutboundPacket& incoming,
        const OutboundPacket& queued) {
    return
        incoming.remote_steam_id ==
            queued.remote_steam_id &&
        incoming.identity.kind != 0 &&
        incoming.identity.kind == queued.identity.kind &&
        incoming.identity.retention ==
            Retention::DistinctLogicalEvent &&
        queued.identity.retention ==
            Retention::DistinctLogicalEvent &&
        incoming.identity.stream_id ==
            queued.identity.stream_id &&
        incoming.identity.logical_a ==
            queued.identity.logical_a &&
        incoming.identity.logical_b ==
            queued.identity.logical_b;
}

bool SteamGameplayOutboundQueuePolicy::
    IsSameEvictionUnit(
        const OutboundPacket& left,
        const OutboundPacket& right) {
    if (left.remote_steam_id != right.remote_steam_id ||
        left.identity.kind == 0 ||
        left.identity.kind != right.identity.kind ||
        left.identity.retention !=
            right.identity.retention ||
        left.identity.stream_id !=
            right.identity.stream_id) {
        return false;
    }
    switch (left.identity.retention) {
    case Retention::LatestStream:
        return left.identity.logical_a ==
            right.identity.logical_a;
    case Retention::LatestGeneration:
        return
            left.identity.logical_a ==
                right.identity.logical_a &&
            left.identity.logical_b ==
                right.identity.logical_b;
    case Retention::DistinctLogicalEvent:
    case Retention::Ordered:
    default:
        return false;
    }
}

bool SteamGameplayOutboundQueuePolicy::
    IsAcceptedLogicalEvent(
        const OutboundPacket& packet) const {
    if (packet.identity.retention !=
        Retention::DistinctLogicalEvent) {
        return false;
    }
    return std::any_of(
        accepted_logical_events_.begin(),
        accepted_logical_events_.end(),
        [&](const AcceptedLogicalEvent& accepted) {
            return
                packet.remote_steam_id ==
                    accepted.remote_steam_id &&
                packet.identity.kind ==
                    accepted.identity.kind &&
                packet.identity.stream_id ==
                    accepted.identity.stream_id &&
                packet.identity.logical_a ==
                    accepted.identity.logical_a &&
                packet.identity.logical_b ==
                    accepted.identity.logical_b;
        });
}

void SteamGameplayOutboundQueuePolicy::
    RememberAcceptedLogicalEvent(
        const OutboundPacket& packet) {
    if (packet.identity.retention !=
        Retention::DistinctLogicalEvent) {
        return;
    }
    AcceptedLogicalEvent accepted;
    accepted.remote_steam_id = packet.remote_steam_id;
    accepted.identity = packet.identity;
    accepted_logical_events_.push_back(
        std::move(accepted));
    if (accepted_logical_events_.size() >
        kMaximumRememberedLogicalEvents) {
        accepted_logical_events_.pop_front();
    }
}

std::size_t SteamGameplayOutboundQueuePolicy::
    EvictReplaceableUnit(
        std::deque<OutboundPacket>::iterator candidate) {
    if (candidate == packets_.end()) {
        return 0;
    }
    if (candidate->identity.retention !=
            Retention::LatestStream &&
        candidate->identity.retention !=
            Retention::LatestGeneration) {
        auto pressure = backpressure_by_peer_.find(
            candidate->remote_steam_id);
        if (pressure != backpressure_by_peer_.end() &&
            !IsReliable(candidate->mode)) {
            pressure->second.dropped_disposable_packets += 1;
        }
        packets_.erase(candidate);
        stats_.dropped_outbound_packets += 1;
        return 1;
    }

    OutboundPacket unit;
    unit.remote_steam_id = candidate->remote_steam_id;
    unit.identity = candidate->identity;
    std::size_t dropped = 0;
    for (auto packet = packets_.begin();
         packet != packets_.end();) {
        if (!IsSameEvictionUnit(unit, *packet)) {
            ++packet;
            continue;
        }
        auto pressure = backpressure_by_peer_.find(
            packet->remote_steam_id);
        if (pressure != backpressure_by_peer_.end() &&
            !IsReliable(packet->mode)) {
            pressure->second.dropped_disposable_packets += 1;
        }
        packet = packets_.erase(packet);
        dropped += 1;
    }
    stats_.dropped_outbound_packets += dropped;
    return dropped;
}

bool SteamGameplayOutboundQueuePolicy::MakeRoom(
    const OutboundPacket& incoming) {
    if (packets_.size() < kMaximumQueuedPackets) {
        return true;
    }
    const auto disposable = std::find_if(
        packets_.begin(),
        packets_.end(),
        [](const OutboundPacket& packet) {
            return !IsReliable(packet.mode);
        });
    if (disposable != packets_.end()) {
        EvictReplaceableUnit(disposable);
        return true;
    }
    const auto checkpoint = std::find_if(
        packets_.begin(),
        packets_.end(),
        [](const OutboundPacket& packet) {
            return
                packet.identity.retention ==
                    Retention::LatestStream ||
                packet.identity.retention ==
                    Retention::LatestGeneration;
        });
    if (checkpoint != packets_.end()) {
        EvictReplaceableUnit(checkpoint);
        return true;
    }
    stats_.dropped_outbound_packets += 1;
    stats_.send_failures += 1;
    if (IsReliable(incoming.mode)) {
        stats_.reliable_send_failures += 1;
    }
    stats_.last_send_failure_result = -1;
    return false;
}

void SteamGameplayOutboundQueuePolicy::
    RemoveSupersededPackets(
        const OutboundPacket& incoming) {
    for (auto packet = packets_.begin();
         packet != packets_.end();) {
        if (!Supersedes(incoming, *packet)) {
            ++packet;
            continue;
        }
        auto pressure = backpressure_by_peer_.find(
            packet->remote_steam_id);
        if (pressure != backpressure_by_peer_.end() &&
            !IsReliable(packet->mode)) {
            pressure->second.dropped_disposable_packets += 1;
        }
        packet = packets_.erase(packet);
        stats_.superseded_outbound_packets += 1;
    }
}

bool SteamGameplayOutboundQueuePolicy::Queue(
    std::uint64_t remote_steam_id,
    const void* data,
    std::size_t size,
    SteamNetworkSendMode mode) {
    if (remote_steam_id == 0 || data == nullptr || size == 0) {
        return false;
    }

    OutboundPacket packet;
    packet.remote_steam_id = remote_steam_id;
    packet.mode = mode;
    packet.identity = DescribePacket(data, size, mode);
    const auto* begin = static_cast<const std::uint8_t*>(data);
    packet.payload.assign(begin, begin + size);
    if (IsAcceptedLogicalEvent(packet) ||
        std::any_of(
            packets_.begin(),
            packets_.end(),
            [&](const OutboundPacket& queued) {
                return IsDuplicateLogicalEvent(
                    packet,
                    queued);
            })) {
        stats_.superseded_outbound_packets += 1;
        RefreshGauges();
        return true;
    }
    if (std::any_of(
            packets_.begin(),
            packets_.end(),
            [&](const OutboundPacket& queued) {
                return Supersedes(queued, packet);
            })) {
        stats_.superseded_outbound_packets += 1;
        RefreshGauges();
        return true;
    }
    RemoveSupersededPackets(packet);
    if (!MakeRoom(packet)) {
        RefreshGauges();
        return false;
    }
    packets_.push_back(std::move(packet));
    RefreshGauges();
    return true;
}

void SteamGameplayOutboundQueuePolicy::EnterBackpressure(
    std::uint64_t remote_steam_id,
    std::uint64_t now_ms) {
    auto& pressure =
        backpressure_by_peer_[remote_steam_id];
    if (pressure.limited) {
        return;
    }
    pressure.limited = true;
    pressure.sustained_reported = false;
    pressure.first_backpressure_ms = now_ms;
    stats_.backpressure_episodes += 1;
}

bool SteamGameplayOutboundQueuePolicy::
    RouteCanAcceptGameplay(
        std::uint64_t remote_steam_id,
        std::uint64_t now_ms,
        const SteamGameplayRouteStatusFunction&
            route_status) {
    if (!route_status) {
        EnterBackpressure(remote_steam_id, now_ms);
        return false;
    }
    const auto status = route_status(remote_steam_id);
    auto pressure = backpressure_by_peer_.find(
        remote_steam_id);
    const bool already_limited =
        pressure != backpressure_by_peer_.end() &&
        pressure->second.limited;
    const auto threshold = already_limited
        ? kQueueTimeLowWaterMicroseconds
        : kQueueTimeHighWaterMicroseconds;
    if (!status.connected ||
        status.queue_time_microseconds >= threshold) {
        EnterBackpressure(remote_steam_id, now_ms);
        return false;
    }
    if (already_limited &&
        now_ms < pressure->second.retry_after_ms) {
        return false;
    }
    if (already_limited) {
        backpressure_by_peer_.erase(pressure);
    }
    return true;
}

std::size_t SteamGameplayOutboundQueuePolicy::
    CountQueuedReliablePackets(
        std::uint64_t remote_steam_id) const {
    return static_cast<std::size_t>(std::count_if(
        packets_.begin(),
        packets_.end(),
        [&](const OutboundPacket& packet) {
            return packet.remote_steam_id == remote_steam_id &&
                IsReliable(packet.mode);
        }));
}

std::vector<SteamGameplayBackpressureEvent>
SteamGameplayOutboundQueuePolicy::Service(
    std::uint64_t now_ms,
    const SteamGameplaySendFunction& send,
    const SteamGameplayRouteStatusFunction&
        route_status) {
    std::unordered_set<std::uint64_t> blocked_peers;
    const auto packets_at_start = packets_.size();
    std::size_t examined = 0;
    std::size_t attempts = 0;
    std::deque<OutboundPacket> deferred;

    while (examined < packets_at_start &&
           attempts < kMaximumSendsPerServiceTick &&
           !packets_.empty()) {
        auto packet = std::move(packets_.front());
        packets_.pop_front();
        examined += 1;

        if (blocked_peers.find(packet.remote_steam_id) !=
                blocked_peers.end() ||
            !RouteCanAcceptGameplay(
                packet.remote_steam_id,
                now_ms,
                route_status)) {
            deferred.push_back(std::move(packet));
            blocked_peers.insert(
                packet.remote_steam_id);
            continue;
        }

        std::int32_t result_code = 0;
        const bool sent =
            static_cast<bool>(send) &&
            send(
                packet.remote_steam_id,
                packet.payload.data(),
                packet.payload.size(),
                packet.mode,
                &result_code);
        attempts += 1;
        if (sent) {
            stats_.packets_sent += 1;
            RememberAcceptedLogicalEvent(packet);
            continue;
        }

        stats_.send_failures += 1;
        if (IsReliable(packet.mode)) {
            stats_.reliable_send_failures += 1;
        }
        stats_.last_send_failure_result = result_code;
        if (result_code != kResultLimitExceeded) {
            stats_.dropped_outbound_packets += 1;
            continue;
        }

        stats_.limit_exceeded_failures += 1;
        EnterBackpressure(
            packet.remote_steam_id,
            now_ms);
        auto& peer_pressure =
            backpressure_by_peer_[packet.remote_steam_id];
        peer_pressure.retry_after_ms =
            now_ms + kLimitRetryIntervalMs;

        const auto limited_peer = packet.remote_steam_id;
        if (IsReliable(packet.mode)) {
            deferred.push_back(std::move(packet));
        } else {
            peer_pressure.dropped_disposable_packets += 1;
            stats_.dropped_outbound_packets += 1;
        }
        blocked_peers.insert(limited_peer);
    }

    deferred.insert(
        deferred.end(),
        std::make_move_iterator(packets_.begin()),
        std::make_move_iterator(packets_.end()));
    packets_ = std::move(deferred);

    std::vector<SteamGameplayBackpressureEvent> events;
    for (auto& [steam_id, pressure] :
         backpressure_by_peer_) {
        if (!pressure.limited ||
            pressure.sustained_reported ||
            now_ms < pressure.first_backpressure_ms ||
            now_ms - pressure.first_backpressure_ms <
                kSustainedBackpressureReportIntervalMs) {
            continue;
        }
        pressure.sustained_reported = true;
        SteamGameplayBackpressureEvent event;
        event.remote_steam_id = steam_id;
        event.first_backpressure_ms =
            pressure.first_backpressure_ms;
        event.duration_ms =
            now_ms - pressure.first_backpressure_ms;
        event.queued_reliable_packets =
            CountQueuedReliablePackets(steam_id);
        event.dropped_disposable_packets =
            pressure.dropped_disposable_packets;
        events.push_back(event);
        stats_.sustained_backpressure_reports += 1;
    }
    RefreshGauges();
    return events;
}

void SteamGameplayOutboundQueuePolicy::Reset() {
    packets_.clear();
    accepted_logical_events_.clear();
    backpressure_by_peer_.clear();
    stats_ = SteamGameplayQueueStats{};
}

void SteamGameplayOutboundQueuePolicy::ResetPeer(
    std::uint64_t remote_steam_id) {
    if (remote_steam_id == 0) {
        return;
    }
    for (auto packet = packets_.begin();
         packet != packets_.end();) {
        if (packet->remote_steam_id == remote_steam_id) {
            packet = packets_.erase(packet);
            stats_.dropped_outbound_packets += 1;
            continue;
        }
        ++packet;
    }
    for (auto accepted =
             accepted_logical_events_.begin();
         accepted != accepted_logical_events_.end();) {
        if (accepted->remote_steam_id ==
            remote_steam_id) {
            accepted =
                accepted_logical_events_.erase(accepted);
            continue;
        }
        ++accepted;
    }
    backpressure_by_peer_.erase(remote_steam_id);
    RefreshGauges();
}

SteamGameplayQueueStats
SteamGameplayOutboundQueuePolicy::SnapshotStats() const {
    return stats_;
}

void SteamGameplayOutboundQueuePolicy::RefreshGauges() {
    stats_.queued_outbound_packets = packets_.size();
    stats_.congested_peers = static_cast<std::size_t>(
        std::count_if(
            backpressure_by_peer_.begin(),
            backpressure_by_peer_.end(),
            [](const auto& entry) {
                return entry.second.limited;
            }));
}

}  // namespace sdmod::multiplayer
