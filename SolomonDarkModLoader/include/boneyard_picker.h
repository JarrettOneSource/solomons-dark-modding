#pragma once

#include "runtime_bootstrap.h"

#include <array>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace sdmod {

inline constexpr std::size_t kBoneyardPickerDigestBytes = 32;
inline constexpr std::size_t kBoneyardPickerNoSelection =
    static_cast<std::size_t>(-1);

using BoneyardPickerDigest =
    std::array<std::uint8_t, kBoneyardPickerDigestBytes>;

enum class BoneyardPickerPhase : std::uint8_t {
    Closed = 0,
    Choosing = 1,
    WaitingForPeers = 2,
    Launching = 3,
    Error = 4,
};

enum class BoneyardResolutionStatus : std::uint8_t {
    None = 0,
    Ready = 1,
    Missing = 2,
};

struct BoneyardPickerPreviewMetadata {
    std::uint64_t file_length = 0;
    std::uint32_t chunk_count = 0;
    std::uint32_t named_buffer_count = 0;
    std::uint32_t max_depth = 0;
};

enum class BoneyardPickerEntryKind : std::uint8_t {
    Default = 0,
    Custom = 1,
};

struct BoneyardPickerEntry {
    BoneyardPickerEntryKind kind = BoneyardPickerEntryKind::Custom;
    std::string display_name;
    std::string source_mod_id;
    std::string source_mod_name;
    std::string source_mod_version;
    std::string source_mod_description;
    std::string updated_utc;
    std::string filename;
    std::string source_relative_path;
    std::string content_sha256;
    BoneyardPickerDigest content_digest{};
    std::string stock_relative_path;
    std::filesystem::path stage_path;
    BoneyardPickerPreviewMetadata preview;
};

struct BoneyardPickerCatalog {
    std::vector<BoneyardPickerEntry> entries;
    std::size_t custom_entry_count = 0;
};

struct BoneyardPickerSnapshot {
    BoneyardPickerPhase phase = BoneyardPickerPhase::Closed;
    bool is_open = false;
    std::shared_ptr<const BoneyardPickerCatalog> catalog;
    std::size_t selected_index = kBoneyardPickerNoSelection;
    std::uint32_t selection_revision = 0;
    std::string selected_content_sha256;
    BoneyardResolutionStatus local_resolution =
        BoneyardResolutionStatus::None;
    std::vector<std::uint64_t> missing_participant_ids;
    std::string error_message;
    std::string applied_stock_relative_path;
};

// Stable frontend provider. Pick and cancel queue events; native work is
// performed by PumpBoneyardPickerOnGameThread.
BoneyardPickerSnapshot GetBoneyardPickerSnapshot();
bool PickBoneyard(std::size_t index, std::string* error_message);
bool CancelBoneyardPicker(std::string* error_message);

struct BoneyardPickerPacketState {
    std::uint32_t revision = 0;
    BoneyardResolutionStatus resolution =
        BoneyardResolutionStatus::None;
    BoneyardPickerDigest digest{};
};

bool InitializeBoneyardPicker(
    const RuntimeBootstrap& bootstrap,
    std::string* error_message);
void ShutdownBoneyardPicker();
void PumpBoneyardPickerOnGameThread();

bool ShouldHijackHostBoneyardStart();
bool OpenHostBoneyardPicker(std::string* error_message);
bool TryDispatchAuthoritativeBoneyardRunOnGameThread(
    bool* handled,
    std::string* error_message);

BoneyardPickerPacketState BuildLocalBoneyardPickerPacketState();
void ApplyAuthoritativeBoneyardPickerPacket(
    const BoneyardPickerPacketState& packet);
void RecordRemoteBoneyardPickerPacket(
    std::uint64_t participant_id,
    const BoneyardPickerPacketState& packet);

const char* BoneyardPickerPhaseLabel(BoneyardPickerPhase phase);
const char* BoneyardResolutionStatusLabel(
    BoneyardResolutionStatus status);

}  // namespace sdmod
