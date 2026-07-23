#pragma once

#include <cstddef>
#include <cstdint>
#include <string>

namespace sdmod {

inline constexpr std::size_t kLuaNetMaximumChannelBytes = 64;
inline constexpr std::size_t kLuaNetMaximumPayloadBytes = 60 * 1024;
inline constexpr std::size_t kLuaNetMaximumSubscriptionsPerMod = 64;
inline constexpr std::size_t kLuaNetMaximumQueuedMessages = 16;
inline constexpr std::size_t kLuaNetMaximumQueuedBytes = 256 * 1024;
inline constexpr std::size_t kLuaNetMaximumPendingDeliveries = 64;
inline constexpr std::size_t kLuaNetMaximumPendingDeliveryBytes = 512 * 1024;

struct LuaNetMessage {
    std::string mod_id;
    std::string channel;
    std::string payload;
    std::uint64_t sender_participant_id = 0;
    std::uint64_t target_participant_id = 0;
    std::uint64_t sequence = 0;
    bool broadcast = false;
};

bool QueueLuaNetMessageDelivery(LuaNetMessage message);

}  // namespace sdmod

