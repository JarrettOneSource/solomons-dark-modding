#pragma once

#include <cstdint>

namespace sdmod::multiplayer {

constexpr std::uint16_t kProtocolVersion = 5;
constexpr char kProtocolMagic[4] = {'S', 'D', 'M', 'P'};

enum class PacketKind : std::uint16_t {
    State = 1,
    Launch = 2,
    Cast = 3,
    Progression = 4,
};

enum class CastKind : std::uint8_t {
    Primary = 1,
    Secondary = 2,
};

enum class ProgressionEventKind : std::uint8_t {
    ExperienceContribution = 1,
    ExperienceAward = 2,
};

#pragma pack(push, 1)
struct PacketHeader {
    char magic[4];
    std::uint16_t version;
    std::uint16_t kind;
    std::uint32_t sequence;
};

struct StatePacket {
    PacketHeader header;
    std::uint8_t ready;
    std::uint8_t in_run;
    std::uint8_t transform_valid;
    std::uint8_t reserved = 0;
    std::uint32_t run_nonce;
    std::int32_t element_id;
    std::int32_t discipline_id;
    std::int32_t appearance_choice_ids[4];
    std::int32_t level;
    std::int32_t wave;
    std::int32_t life_current;
    std::int32_t life_max;
    std::int32_t mana_current;
    std::int32_t mana_max;
    std::int32_t experience_current;
    std::int32_t experience_next;
    std::int32_t primary_entry_index;
    std::int32_t primary_combo_entry_index;
    std::int32_t queued_secondary_entry_indices[3];
    float position_x;
    float position_y;
    float heading;
};

struct LaunchPacket {
    PacketHeader header;
    std::uint32_t run_nonce;
    std::int32_t mission_ids[10];
};

struct CastPacket {
    PacketHeader header;
    std::uint8_t cast_kind;
    std::int8_t secondary_slot;
    std::uint16_t reserved = 0;
    std::uint32_t run_nonce;
    std::int32_t element_id;
    std::int32_t discipline_id;
    std::int32_t primary_entry_index;
    std::int32_t primary_combo_entry_index;
    std::int32_t queued_secondary_entry_indices[3];
    float position_x;
    float position_y;
    float heading;
};

struct ProgressionPacket {
    PacketHeader header;
    std::uint8_t event_kind;
    std::uint8_t award_mode;
    std::uint16_t reserved = 0;
    std::uint32_t run_nonce;
    std::uint64_t source_steam_id;
    float experience_delta;
};
#pragma pack(pop)

inline PacketHeader MakePacketHeader(PacketKind kind, std::uint32_t sequence) {
    PacketHeader header{};
    header.magic[0] = kProtocolMagic[0];
    header.magic[1] = kProtocolMagic[1];
    header.magic[2] = kProtocolMagic[2];
    header.magic[3] = kProtocolMagic[3];
    header.version = kProtocolVersion;
    header.kind = static_cast<std::uint16_t>(kind);
    header.sequence = sequence;
    return header;
}

inline bool IsValidHeader(const PacketHeader& header, PacketKind expected_kind) {
    return header.magic[0] == kProtocolMagic[0] &&
           header.magic[1] == kProtocolMagic[1] &&
           header.magic[2] == kProtocolMagic[2] &&
           header.magic[3] == kProtocolMagic[3] &&
           header.version == kProtocolVersion &&
           header.kind == static_cast<std::uint16_t>(expected_kind);
}

static_assert(sizeof(PacketHeader) == 12, "Unexpected packet header size");
static_assert(sizeof(StatePacket) == 108, "Unexpected state packet size");
static_assert(sizeof(LaunchPacket) == 56, "Unexpected launch packet size");
static_assert(sizeof(CastPacket) == 60, "Unexpected cast packet size");
static_assert(sizeof(ProgressionPacket) == 32, "Unexpected progression packet size");

}  // namespace sdmod::multiplayer
