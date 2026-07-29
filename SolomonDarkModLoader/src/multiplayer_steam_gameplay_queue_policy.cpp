#include "multiplayer_steam_gameplay_queue_policy.h"

#include <algorithm>
#include <iterator>
#include <unordered_set>
#include <utility>

namespace sdmod::multiplayer {

bool SteamGameplayOutboundQueuePolicy::IsReliable(
    SteamNetworkSendMode mode) {
    return mode == SteamNetworkSendMode::ReliableNoNagle;
}

bool SteamGameplayOutboundQueuePolicy::MakeRoom(bool reliable) {
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
        packets_.erase(disposable);
        stats_.dropped_outbound_packets += 1;
        return true;
    }
    stats_.dropped_outbound_packets += 1;
    stats_.send_failures += 1;
    if (reliable) {
        stats_.reliable_send_failures += 1;
    }
    stats_.last_send_failure_result = -1;
    return false;
}

bool SteamGameplayOutboundQueuePolicy::Queue(
    std::uint64_t remote_steam_id,
    const void* data,
    std::size_t size,
    SteamNetworkSendMode mode) {
    if (remote_steam_id == 0 || data == nullptr || size == 0) {
        return false;
    }

    const bool reliable = IsReliable(mode);
    const auto pressure = backpressure_by_peer_.find(
        remote_steam_id);
    if (!reliable &&
        pressure != backpressure_by_peer_.end() &&
        pressure->second.limited) {
        for (auto packet = packets_.begin();
             packet != packets_.end();) {
            if (packet->remote_steam_id == remote_steam_id &&
                !IsReliable(packet->mode)) {
                packet = packets_.erase(packet);
                pressure->second.dropped_disposable_packets += 1;
                stats_.dropped_outbound_packets += 1;
                continue;
            }
            ++packet;
        }
    }

    if (!MakeRoom(reliable)) {
        RefreshGauges();
        return false;
    }
    OutboundPacket packet;
    packet.remote_steam_id = remote_steam_id;
    packet.mode = mode;
    const auto* begin = static_cast<const std::uint8_t*>(data);
    packet.payload.assign(begin, begin + size);
    packets_.push_back(std::move(packet));
    RefreshGauges();
    return true;
}

void SteamGameplayOutboundQueuePolicy::CoalesceDisposablePackets(
    std::uint64_t remote_steam_id) {
    OutboundPacket latest;
    std::size_t disposable_count = 0;
    for (auto packet = packets_.begin();
         packet != packets_.end();) {
        if (packet->remote_steam_id != remote_steam_id ||
            IsReliable(packet->mode)) {
            ++packet;
            continue;
        }
        latest = std::move(*packet);
        packet = packets_.erase(packet);
        disposable_count += 1;
    }
    if (disposable_count == 0) {
        return;
    }
    packets_.push_back(std::move(latest));
    auto& pressure = backpressure_by_peer_[remote_steam_id];
    pressure.dropped_disposable_packets +=
        disposable_count - 1;
    stats_.dropped_outbound_packets +=
        disposable_count - 1;
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
    const SteamGameplaySendFunction& send) {
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

        const auto pressure = backpressure_by_peer_.find(
            packet.remote_steam_id);
        if (blocked_peers.find(packet.remote_steam_id) !=
                blocked_peers.end() ||
            (pressure != backpressure_by_peer_.end() &&
             pressure->second.limited &&
             now_ms < pressure->second.retry_after_ms)) {
            deferred.push_back(std::move(packet));
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
            backpressure_by_peer_.erase(
                packet.remote_steam_id);
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
        auto& peer_pressure =
            backpressure_by_peer_[packet.remote_steam_id];
        if (!peer_pressure.limited) {
            peer_pressure.limited = true;
            peer_pressure.first_limit_exceeded_ms = now_ms;
            stats_.backpressure_episodes += 1;
        }
        peer_pressure.retry_after_ms =
            now_ms + kLimitRetryIntervalMs;

        const auto limited_peer = packet.remote_steam_id;
        if (IsReliable(packet.mode)) {
            deferred.push_back(std::move(packet));
        } else {
            peer_pressure.dropped_disposable_packets += 1;
            stats_.dropped_outbound_packets += 1;
        }
        CoalesceDisposablePackets(
            limited_peer);
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
            now_ms < pressure.first_limit_exceeded_ms ||
            now_ms - pressure.first_limit_exceeded_ms <
                kSustainedBackpressureReportIntervalMs) {
            continue;
        }
        pressure.sustained_reported = true;
        SteamGameplayBackpressureEvent event;
        event.remote_steam_id = steam_id;
        event.first_limit_exceeded_ms =
            pressure.first_limit_exceeded_ms;
        event.duration_ms =
            now_ms - pressure.first_limit_exceeded_ms;
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
