#pragma once

#include "multiplayer_runtime_protocol.h"

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <iterator>
#include <unordered_map>
#include <utility>
#include <vector>

namespace sdmod::multiplayer {

// Stay comfortably below the common 1,500-byte IPv4 path MTU. This ceiling
// includes the transport-fragment header when fragmentation is required.
constexpr std::size_t kLocalUdpMaximumDatagramBytes = 1200;
constexpr std::size_t kLocalUdpMaximumLogicalPacketBytes = 8192;
constexpr std::size_t kLocalUdpMaximumPendingFragmentAssemblies = 64;
constexpr std::size_t kLocalUdpMaximumPendingFragmentBytes = 512 * 1024;
constexpr std::uint64_t kLocalUdpFragmentAssemblyExpiryMicroseconds =
    5'000'000;
constexpr char kLocalUdpFragmentMagic[4] = {'S', 'D', 'F', 'R'};

struct LocalUdpFragmentHeader {
    char magic[4];
    std::uint16_t protocol_version;
    std::uint16_t original_kind;
    std::uint32_t original_sequence;
    std::uint32_t total_bytes;
    std::uint16_t fragment_index;
    std::uint16_t fragment_count;
    std::uint16_t fragment_bytes;
    std::uint16_t reserved;
};

static_assert(
    sizeof(LocalUdpFragmentHeader) == 24,
    "Unexpected local UDP fragment header size");

constexpr std::size_t kLocalUdpFragmentPayloadBytes =
    kLocalUdpMaximumDatagramBytes -
    sizeof(LocalUdpFragmentHeader);
constexpr std::uint16_t kLocalUdpMaximumFragments =
    static_cast<std::uint16_t>(
        (kLocalUdpMaximumLogicalPacketBytes +
         kLocalUdpFragmentPayloadBytes - 1) /
        kLocalUdpFragmentPayloadBytes);

constexpr std::uint16_t LocalUdpFragmentCountForBytes(
    std::size_t bytes) {
    return bytes == 0
        ? 0
        : static_cast<std::uint16_t>(
            (bytes + kLocalUdpFragmentPayloadBytes - 1) /
            kLocalUdpFragmentPayloadBytes);
}

inline bool IsLocalUdpFragmentMagic(
    const void* datagram,
    std::size_t datagram_bytes) {
    if (datagram == nullptr || datagram_bytes < 4) {
        return false;
    }
    return std::memcmp(
               datagram,
               kLocalUdpFragmentMagic,
               sizeof(kLocalUdpFragmentMagic)) == 0;
}

inline bool BuildLocalUdpFragmentDatagrams(
    const void* packet,
    std::size_t packet_bytes,
    std::vector<std::vector<std::uint8_t>>* datagrams) {
    if (datagrams == nullptr) {
        return false;
    }
    datagrams->clear();
    if (packet == nullptr ||
        packet_bytes <= kLocalUdpMaximumDatagramBytes ||
        packet_bytes > kLocalUdpMaximumLogicalPacketBytes ||
        packet_bytes < sizeof(PacketHeader)) {
        return false;
    }

    PacketHeader packet_header{};
    std::memcpy(&packet_header, packet, sizeof(packet_header));
    if (!IsValidPacketHeader(packet_header)) {
        return false;
    }

    const auto fragment_count =
        LocalUdpFragmentCountForBytes(packet_bytes);
    if (fragment_count < 2 ||
        fragment_count > kLocalUdpMaximumFragments) {
        return false;
    }

    const auto* packet_bytes_begin =
        static_cast<const std::uint8_t*>(packet);
    datagrams->reserve(fragment_count);
    for (std::uint16_t fragment_index = 0;
         fragment_index < fragment_count;
         ++fragment_index) {
        const auto payload_offset =
            static_cast<std::size_t>(fragment_index) *
            kLocalUdpFragmentPayloadBytes;
        const auto payload_bytes =
            (std::min)(
                kLocalUdpFragmentPayloadBytes,
                packet_bytes - payload_offset);

        LocalUdpFragmentHeader fragment_header{};
        std::memcpy(
            fragment_header.magic,
            kLocalUdpFragmentMagic,
            sizeof(fragment_header.magic));
        fragment_header.protocol_version = kProtocolVersion;
        fragment_header.original_kind = packet_header.kind;
        fragment_header.original_sequence = packet_header.sequence;
        fragment_header.total_bytes =
            static_cast<std::uint32_t>(packet_bytes);
        fragment_header.fragment_index = fragment_index;
        fragment_header.fragment_count = fragment_count;
        fragment_header.fragment_bytes =
            static_cast<std::uint16_t>(payload_bytes);

        std::vector<std::uint8_t> datagram(
            sizeof(fragment_header) + payload_bytes);
        std::memcpy(
            datagram.data(),
            &fragment_header,
            sizeof(fragment_header));
        std::memcpy(
            datagram.data() + sizeof(fragment_header),
            packet_bytes_begin + payload_offset,
            payload_bytes);
        datagrams->push_back(std::move(datagram));
    }
    return true;
}

enum class LocalUdpFragmentAcceptResult {
    Invalid,
    Pending,
    Complete,
};

class LocalUdpFragmentReassembler {
public:
    LocalUdpFragmentAcceptResult Accept(
        std::uint64_t peer_id,
        const void* datagram,
        std::size_t datagram_bytes,
        std::uint64_t now_microseconds,
        std::vector<std::uint8_t>* completed_packet) {
        if (completed_packet == nullptr) {
            return LocalUdpFragmentAcceptResult::Invalid;
        }
        completed_packet->clear();
        Prune(now_microseconds);

        LocalUdpFragmentHeader header{};
        if (datagram == nullptr ||
            datagram_bytes < sizeof(header)) {
            return LocalUdpFragmentAcceptResult::Invalid;
        }
        std::memcpy(&header, datagram, sizeof(header));
        if (!IsValidHeader(header, datagram_bytes)) {
            return LocalUdpFragmentAcceptResult::Invalid;
        }

        const AssemblyKey key{
            peer_id,
            header.original_kind,
            header.original_sequence,
        };
        auto existing = assemblies_.find(key);
        if (existing != assemblies_.end() &&
            (existing->second.total_bytes != header.total_bytes ||
             existing->second.fragment_count !=
                 header.fragment_count)) {
            Erase(existing);
            return LocalUdpFragmentAcceptResult::Invalid;
        }
        if (existing == assemblies_.end()) {
            MakeRoom(header.total_bytes);
            if (assemblies_.size() >=
                    kLocalUdpMaximumPendingFragmentAssemblies ||
                pending_bytes_ + header.total_bytes >
                    kLocalUdpMaximumPendingFragmentBytes) {
                return LocalUdpFragmentAcceptResult::Invalid;
            }
            PendingAssembly assembly;
            assembly.total_bytes = header.total_bytes;
            assembly.fragment_count = header.fragment_count;
            assembly.last_update_microseconds = now_microseconds;
            assembly.payload.resize(header.total_bytes);
            assembly.received.resize(header.fragment_count);
            pending_bytes_ += header.total_bytes;
            existing = assemblies_.emplace(
                key,
                std::move(assembly)).first;
        }

        auto& assembly = existing->second;
        assembly.last_update_microseconds = now_microseconds;
        if (assembly.received[header.fragment_index] == 0) {
            const auto payload_offset =
                static_cast<std::size_t>(header.fragment_index) *
                kLocalUdpFragmentPayloadBytes;
            std::memcpy(
                assembly.payload.data() + payload_offset,
                static_cast<const std::uint8_t*>(datagram) +
                    sizeof(header),
                header.fragment_bytes);
            assembly.received[header.fragment_index] = 1;
            ++assembly.received_fragment_count;
        }
        if (assembly.received_fragment_count !=
            assembly.fragment_count) {
            return LocalUdpFragmentAcceptResult::Pending;
        }

        PacketHeader packet_header{};
        std::memcpy(
            &packet_header,
            assembly.payload.data(),
            sizeof(packet_header));
        if (!IsValidPacketHeader(packet_header) ||
            packet_header.kind != header.original_kind ||
            packet_header.sequence != header.original_sequence) {
            Erase(existing);
            return LocalUdpFragmentAcceptResult::Invalid;
        }

        *completed_packet = std::move(assembly.payload);
        Erase(existing);
        return LocalUdpFragmentAcceptResult::Complete;
    }

    void Prune(std::uint64_t now_microseconds) {
        for (auto it = assemblies_.begin();
             it != assemblies_.end();) {
            const auto last_update =
                it->second.last_update_microseconds;
            if (now_microseconds >= last_update &&
                now_microseconds - last_update >=
                    kLocalUdpFragmentAssemblyExpiryMicroseconds) {
                auto expired = it++;
                Erase(expired);
            } else {
                ++it;
            }
        }
    }

    void Clear() {
        assemblies_.clear();
        pending_bytes_ = 0;
    }

    std::size_t pending_assembly_count() const {
        return assemblies_.size();
    }

    std::size_t pending_bytes() const {
        return pending_bytes_;
    }

private:
    struct AssemblyKey {
        std::uint64_t peer_id;
        std::uint16_t original_kind;
        std::uint32_t original_sequence;

        bool operator==(const AssemblyKey& other) const {
            return peer_id == other.peer_id &&
                original_kind == other.original_kind &&
                original_sequence == other.original_sequence;
        }
    };

    struct AssemblyKeyHash {
        std::size_t operator()(const AssemblyKey& key) const {
            auto hash = static_cast<std::size_t>(key.peer_id);
            hash ^= static_cast<std::size_t>(
                key.peer_id >> 32);
            hash ^= static_cast<std::size_t>(
                key.original_kind) << 1;
            hash ^= static_cast<std::size_t>(
                key.original_sequence) << 17;
            return hash;
        }
    };

    struct PendingAssembly {
        std::uint32_t total_bytes = 0;
        std::uint16_t fragment_count = 0;
        std::uint16_t received_fragment_count = 0;
        std::uint64_t last_update_microseconds = 0;
        std::vector<std::uint8_t> payload;
        std::vector<std::uint8_t> received;
    };

    using AssemblyMap = std::unordered_map<
        AssemblyKey,
        PendingAssembly,
        AssemblyKeyHash>;

    static bool IsValidHeader(
        const LocalUdpFragmentHeader& header,
        std::size_t datagram_bytes) {
        if (std::memcmp(
                header.magic,
                kLocalUdpFragmentMagic,
                sizeof(header.magic)) != 0 ||
            header.protocol_version != kProtocolVersion ||
            header.original_kind == 0 ||
            header.total_bytes <=
                kLocalUdpMaximumDatagramBytes ||
            header.total_bytes >
                kLocalUdpMaximumLogicalPacketBytes ||
            header.fragment_count < 2 ||
            header.fragment_count >
                kLocalUdpMaximumFragments ||
            header.fragment_index >= header.fragment_count ||
            header.fragment_count !=
                LocalUdpFragmentCountForBytes(
                    header.total_bytes)) {
            return false;
        }

        const auto payload_offset =
            static_cast<std::size_t>(header.fragment_index) *
            kLocalUdpFragmentPayloadBytes;
        const auto expected_fragment_bytes =
            (std::min)(
                kLocalUdpFragmentPayloadBytes,
                static_cast<std::size_t>(header.total_bytes) -
                    payload_offset);
        return header.fragment_bytes ==
                expected_fragment_bytes &&
            datagram_bytes ==
                sizeof(LocalUdpFragmentHeader) +
                    expected_fragment_bytes &&
            datagram_bytes <= kLocalUdpMaximumDatagramBytes;
    }

    void MakeRoom(std::size_t incoming_bytes) {
        while (!assemblies_.empty() &&
               (assemblies_.size() >=
                    kLocalUdpMaximumPendingFragmentAssemblies ||
                pending_bytes_ + incoming_bytes >
                    kLocalUdpMaximumPendingFragmentBytes)) {
            auto oldest = assemblies_.begin();
            for (auto it = std::next(assemblies_.begin());
                 it != assemblies_.end();
                 ++it) {
                if (it->second.last_update_microseconds <
                    oldest->second.last_update_microseconds) {
                    oldest = it;
                }
            }
            Erase(oldest);
        }
    }

    void Erase(AssemblyMap::iterator assembly) {
        pending_bytes_ -= assembly->second.total_bytes;
        assemblies_.erase(assembly);
    }

    AssemblyMap assemblies_;
    std::size_t pending_bytes_ = 0;
};

}  // namespace sdmod::multiplayer
