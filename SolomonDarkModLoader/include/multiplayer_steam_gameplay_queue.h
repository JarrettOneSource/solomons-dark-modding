#pragma once

#include "steam_bootstrap.h"

#include <cstddef>
#include <cstdint>
#include <vector>

namespace sdmod::multiplayer {

enum class SteamGameplayInboundEventKind {
    PeerConnected,
    PeerDisconnected,
    PacketReceived,
};

struct SteamGameplayInboundEvent {
    SteamGameplayInboundEventKind kind =
        SteamGameplayInboundEventKind::PacketReceived;
    std::uint64_t steam_id = 0;
    std::uint64_t received_ms = 0;
    bool authoritative_host = false;
    bool reliable = false;
    std::vector<std::uint8_t> payload;
};

struct SteamGameplayQueueStats {
    std::uint64_t packets_sent = 0;
    std::uint64_t send_failures = 0;
    std::uint64_t reliable_send_failures = 0;
    std::uint64_t dropped_outbound_packets = 0;
    std::uint64_t dropped_inbound_packets = 0;
    std::int32_t last_send_failure_result = 0;
};

void ResetSteamGameplayQueues();

bool QueueSteamGameplayPeerConnected(
    std::uint64_t steam_id,
    bool authoritative_host);
bool QueueSteamGameplayPeerDisconnected(std::uint64_t steam_id);
bool QueueSteamGameplayPacketReceived(
    std::uint64_t sender_steam_id,
    const void* data,
    std::size_t size,
    std::uint64_t received_ms,
    bool reliable);
std::vector<SteamGameplayInboundEvent> DrainSteamGameplayInboundEvents();

bool QueueSteamGameplayPacketSend(
    std::uint64_t remote_steam_id,
    const void* data,
    std::size_t size,
    SteamNetworkSendMode mode);
void ServiceSteamGameplaySendQueue();
SteamGameplayQueueStats SnapshotSteamGameplayQueueStats();

}  // namespace sdmod::multiplayer
