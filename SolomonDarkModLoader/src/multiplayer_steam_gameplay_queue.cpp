#include "multiplayer_steam_gameplay_queue.h"

#include "logger.h"

#include <Windows.h>

#include <algorithm>
#include <deque>
#include <mutex>
#include <string>
#include <utility>
#include <vector>

namespace sdmod::multiplayer {
namespace {

constexpr std::size_t kMaximumQueuedInboundEvents = 1024;
constexpr std::size_t kMaximumQueuedOutboundPackets = 1024;
constexpr std::size_t kMaximumSendsPerServiceTick = 256;
constexpr std::uint64_t kSendFailureLogIntervalMs = 1000;

struct SteamGameplayOutboundPacket {
    std::uint64_t remote_steam_id = 0;
    SteamNetworkSendMode mode = SteamNetworkSendMode::UnreliableNoNagle;
    std::vector<std::uint8_t> payload;
};

std::mutex g_queue_mutex;
std::deque<SteamGameplayInboundEvent> g_inbound_events;
std::deque<SteamGameplayOutboundPacket> g_outbound_packets;
SteamGameplayQueueStats g_queue_stats;
std::uint64_t g_last_send_failure_log_ms = 0;

bool IsReliable(SteamNetworkSendMode mode) {
    return mode == SteamNetworkSendMode::ReliableNoNagle;
}

bool MakeInboundRoom() {
    if (g_inbound_events.size() < kMaximumQueuedInboundEvents) {
        return true;
    }
    const auto disposable = std::find_if(
        g_inbound_events.begin(),
        g_inbound_events.end(),
        [](const SteamGameplayInboundEvent& event) {
            return event.kind == SteamGameplayInboundEventKind::PacketReceived &&
                   !event.reliable;
        });
    if (disposable != g_inbound_events.end()) {
        g_inbound_events.erase(disposable);
        g_queue_stats.dropped_inbound_packets += 1;
        return true;
    }
    g_queue_stats.dropped_inbound_packets += 1;
    return false;
}

bool MakeOutboundRoom(bool reliable) {
    if (g_outbound_packets.size() < kMaximumQueuedOutboundPackets) {
        return true;
    }
    const auto disposable = std::find_if(
        g_outbound_packets.begin(),
        g_outbound_packets.end(),
        [](const SteamGameplayOutboundPacket& packet) {
            return !IsReliable(packet.mode);
        });
    if (disposable != g_outbound_packets.end()) {
        g_outbound_packets.erase(disposable);
        g_queue_stats.dropped_outbound_packets += 1;
        g_queue_stats.send_failures += 1;
        g_queue_stats.last_send_failure_result = -1;
        return true;
    }
    g_queue_stats.dropped_outbound_packets += 1;
    if (reliable) {
        g_queue_stats.reliable_send_failures += 1;
    }
    g_queue_stats.send_failures += 1;
    g_queue_stats.last_send_failure_result = -1;
    return false;
}

}  // namespace

void ResetSteamGameplayQueues() {
    std::scoped_lock lock(g_queue_mutex);
    g_inbound_events.clear();
    g_outbound_packets.clear();
    g_queue_stats = SteamGameplayQueueStats{};
    g_last_send_failure_log_ms = 0;
}

bool QueueSteamGameplayPeerConnected(
    std::uint64_t steam_id,
    bool authoritative_host) {
    if (steam_id == 0) {
        return false;
    }
    std::scoped_lock lock(g_queue_mutex);
    if (!MakeInboundRoom()) {
        return false;
    }
    SteamGameplayInboundEvent event;
    event.kind = SteamGameplayInboundEventKind::PeerConnected;
    event.steam_id = steam_id;
    event.authoritative_host = authoritative_host;
    event.reliable = true;
    g_inbound_events.push_back(std::move(event));
    return true;
}

bool QueueSteamGameplayPeerDisconnected(std::uint64_t steam_id) {
    if (steam_id == 0) {
        return false;
    }
    std::scoped_lock lock(g_queue_mutex);
    if (!MakeInboundRoom()) {
        return false;
    }
    SteamGameplayInboundEvent event;
    event.kind = SteamGameplayInboundEventKind::PeerDisconnected;
    event.steam_id = steam_id;
    event.reliable = true;
    g_inbound_events.push_back(std::move(event));
    return true;
}

bool QueueSteamGameplayPacketReceived(
    std::uint64_t sender_steam_id,
    const void* data,
    std::size_t size,
    std::uint64_t received_ms,
    bool reliable) {
    if (sender_steam_id == 0 || data == nullptr || size == 0) {
        return false;
    }
    std::scoped_lock lock(g_queue_mutex);
    if (!MakeInboundRoom()) {
        return false;
    }
    SteamGameplayInboundEvent event;
    event.kind = SteamGameplayInboundEventKind::PacketReceived;
    event.steam_id = sender_steam_id;
    event.received_ms = received_ms;
    event.reliable = reliable;
    const auto* begin = static_cast<const std::uint8_t*>(data);
    event.payload.assign(begin, begin + size);
    g_inbound_events.push_back(std::move(event));
    return true;
}

std::vector<SteamGameplayInboundEvent> DrainSteamGameplayInboundEvents() {
    std::scoped_lock lock(g_queue_mutex);
    std::vector<SteamGameplayInboundEvent> events;
    events.reserve(g_inbound_events.size());
    while (!g_inbound_events.empty()) {
        events.push_back(std::move(g_inbound_events.front()));
        g_inbound_events.pop_front();
    }
    return events;
}

bool QueueSteamGameplayPacketSend(
    std::uint64_t remote_steam_id,
    const void* data,
    std::size_t size,
    SteamNetworkSendMode mode) {
    if (remote_steam_id == 0 || data == nullptr || size == 0) {
        return false;
    }
    std::scoped_lock lock(g_queue_mutex);
    if (!MakeOutboundRoom(IsReliable(mode))) {
        return false;
    }
    SteamGameplayOutboundPacket packet;
    packet.remote_steam_id = remote_steam_id;
    packet.mode = mode;
    const auto* begin = static_cast<const std::uint8_t*>(data);
    packet.payload.assign(begin, begin + size);
    g_outbound_packets.push_back(std::move(packet));
    return true;
}

void ServiceSteamGameplaySendQueue() {
    std::vector<SteamGameplayOutboundPacket> pending;
    {
        std::scoped_lock lock(g_queue_mutex);
        const auto count = (std::min)(
            g_outbound_packets.size(),
            kMaximumSendsPerServiceTick);
        pending.reserve(count);
        for (std::size_t index = 0; index < count; ++index) {
            pending.push_back(std::move(g_outbound_packets.front()));
            g_outbound_packets.pop_front();
        }
    }

    std::uint64_t sent = 0;
    std::uint64_t failed = 0;
    std::uint64_t reliable_failed = 0;
    std::int32_t last_failure_result = 0;
    for (const auto& packet : pending) {
        std::int32_t result_code = 0;
        if (SteamSendNetworkMessage(
                packet.remote_steam_id,
                packet.payload.data(),
                packet.payload.size(),
                packet.mode,
                &result_code)) {
            sent += 1;
            continue;
        }
        failed += 1;
        if (IsReliable(packet.mode)) {
            reliable_failed += 1;
        }
        last_failure_result = result_code;
    }

    bool should_log_failure = false;
    std::uint64_t total_failures = 0;
    {
        std::scoped_lock lock(g_queue_mutex);
        g_queue_stats.packets_sent += sent;
        g_queue_stats.send_failures += failed;
        g_queue_stats.reliable_send_failures += reliable_failed;
        if (failed != 0) {
            g_queue_stats.last_send_failure_result = last_failure_result;
            const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
            if (g_last_send_failure_log_ms == 0 ||
                now_ms >= g_last_send_failure_log_ms +
                    kSendFailureLogIntervalMs) {
                g_last_send_failure_log_ms = now_ms;
                should_log_failure = true;
                total_failures = g_queue_stats.send_failures;
            }
        }
    }
    if (should_log_failure) {
        Log(
            "Steam gameplay send rejected. result=" +
            std::to_string(last_failure_result) +
            " failures=" + std::to_string(total_failures));
    }
}

SteamGameplayQueueStats SnapshotSteamGameplayQueueStats() {
    std::scoped_lock lock(g_queue_mutex);
    return g_queue_stats;
}

}  // namespace sdmod::multiplayer
