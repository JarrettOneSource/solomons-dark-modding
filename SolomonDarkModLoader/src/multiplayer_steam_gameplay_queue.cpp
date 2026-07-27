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
constexpr std::uint64_t kSendFailureLogIntervalMs = 1000;

std::mutex g_queue_mutex;
std::deque<SteamGameplayInboundEvent> g_inbound_events;
SteamGameplayOutboundQueuePolicy g_outbound_queue;
std::uint64_t g_dropped_inbound_packets = 0;
std::uint64_t g_last_send_failure_log_ms = 0;

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
        g_dropped_inbound_packets += 1;
        return true;
    }
    g_dropped_inbound_packets += 1;
    return false;
}

}  // namespace

void ResetSteamGameplayQueues() {
    std::scoped_lock lock(g_queue_mutex);
    g_inbound_events.clear();
    g_outbound_queue.Reset();
    g_dropped_inbound_packets = 0;
    g_last_send_failure_log_ms = 0;
}

void ResetSteamGameplayPeerSendQueue(
    std::uint64_t remote_steam_id) {
    std::scoped_lock lock(g_queue_mutex);
    g_outbound_queue.ResetPeer(remote_steam_id);
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
    return g_outbound_queue.Queue(
        remote_steam_id,
        data,
        size,
        mode);
}

std::vector<SteamGameplayCongestionEvent>
ServiceSteamGameplaySendQueue() {
    bool should_log_failure = false;
    SteamGameplayQueueStats stats;
    std::vector<SteamGameplayCongestionEvent> events;
    {
        std::scoped_lock lock(g_queue_mutex);
        const auto before =
            g_outbound_queue.SnapshotStats().send_failures;
        events = g_outbound_queue.Service(
            static_cast<std::uint64_t>(GetTickCount64()),
            [](std::uint64_t remote_steam_id,
               const void* data,
               std::size_t size,
               SteamNetworkSendMode mode,
               std::int32_t* result_code) {
                return SteamSendNetworkMessage(
                    remote_steam_id,
                    data,
                    size,
                    mode,
                    result_code);
            });
        stats = g_outbound_queue.SnapshotStats();
        if (stats.send_failures != before) {
            const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
            if (g_last_send_failure_log_ms == 0 ||
                now_ms >= g_last_send_failure_log_ms +
                    kSendFailureLogIntervalMs) {
                g_last_send_failure_log_ms = now_ms;
                should_log_failure = true;
            }
        }
    }
    if (should_log_failure) {
        Log(
            "Steam gameplay send rejected. result=" +
            std::to_string(stats.last_send_failure_result) +
            " failures=" + std::to_string(stats.send_failures) +
            " queued=" +
            std::to_string(stats.queued_outbound_packets) +
            " congested_peers=" +
            std::to_string(stats.congested_peers));
    }
    return events;
}

SteamGameplayQueueStats SnapshotSteamGameplayQueueStats() {
    std::scoped_lock lock(g_queue_mutex);
    auto stats = g_outbound_queue.SnapshotStats();
    stats.dropped_inbound_packets =
        g_dropped_inbound_packets;
    return stats;
}

}  // namespace sdmod::multiplayer
