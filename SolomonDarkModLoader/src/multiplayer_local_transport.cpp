#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <WinSock2.h>
#include <Ws2tcpip.h>

#include "multiplayer_local_transport.h"

#include "bot_runtime.h"
#include "gameplay_seams.h"
#include "logger.h"
#include "memory_access.h"
#include "mod_loader.h"
#include "multiplayer_runtime_protocol.h"
#include "multiplayer_runtime_state.h"
#include "native_enemy_lifecycle.h"
#include "native_spell_stats.h"

#include <algorithm>
#include <array>
#include <charconv>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <mutex>
#include <sstream>
#include <string>
#include <system_error>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

#pragma comment(lib, "Ws2_32.lib")

namespace sdmod::multiplayer {
namespace {

constexpr const char* kTransportEnvironmentVariable = "SDMOD_MULTIPLAYER_TRANSPORT";
constexpr const char* kRoleEnvironmentVariable = "SDMOD_MULTIPLAYER_ROLE";
constexpr const char* kLocalPortEnvironmentVariable = "SDMOD_MULTIPLAYER_LOCAL_PORT";
constexpr const char* kRemoteHostEnvironmentVariable = "SDMOD_MULTIPLAYER_REMOTE_HOST";
constexpr const char* kRemotePortEnvironmentVariable = "SDMOD_MULTIPLAYER_REMOTE_PORT";
constexpr const char* kParticipantIdEnvironmentVariable = "SDMOD_MULTIPLAYER_PARTICIPANT_ID";
constexpr const char* kPlayerNameEnvironmentVariable = "SDMOD_MULTIPLAYER_PLAYER_NAME";
constexpr std::uint16_t kDefaultHostPort = 47770;
constexpr std::uint16_t kDefaultClientPort = 47771;
constexpr std::uint64_t kLocalDevParticipantIdBase = 0x2000000000000000ull;
constexpr std::uint64_t kRunWorldActorNetworkIdBase = 0x1000000000000ull;
constexpr std::uint64_t kRunHostLocalWorldActorNetworkIdBase = 0x1001000000000ull;
constexpr std::uint64_t kRunLootDropNetworkIdBase = 0x1002000000000ull;
constexpr std::uint64_t kLocalTransportSendIntervalMs = 50;
constexpr std::uint64_t kLocalTransportWorldSnapshotIntervalMs = 100;
constexpr std::uint64_t kLocalTransportLootSnapshotIntervalMs = 100;
constexpr std::uint64_t kLocalCastInputUpdateIntervalMs = 50;
constexpr std::uint64_t kClientHostRunFollowRetryMs = 1000;
constexpr std::uint64_t kRecentRunEnemyDeathSnapshotHoldMs = 2500;
constexpr float kEnemyDamageClaimHpEpsilon = 0.05f;
constexpr float kEnemyDamageClaimMaxDistance = 2200.0f;
constexpr float kEnemyDamageClaimMaxTargetDrift = 384.0f;
constexpr float kEnemyDamageClaimMaxHpFactor = 2.5f;
constexpr float kEnemyDamageClaimAbsoluteCap = 20000.0f;
constexpr std::uint64_t kEnemyDamageRejectedRetrySuppressMs = 500;
constexpr float kLootPickupMaxDistance = 320.0f;
constexpr float kLootPickupDropDriftMaxDistance = 160.0f;
constexpr float kLootPickupResourceEpsilon = 0.001f;
constexpr float kLootPickupMaxResourceDelta = 10000.0f;
constexpr std::uint32_t kOrbRewardNativeTypeId = 0x07DB;
constexpr std::uint32_t kGoldRewardNativeTypeId = 0x07DC;
constexpr std::uint32_t kItemDropNativeTypeId = 0x07DD;
constexpr std::uint32_t kPotionItemTypeId = 0x1B59;
constexpr std::uint32_t kSolomonDigNativeTypeId = 0x1391;
constexpr std::uint32_t kSolomonRunStaticNativeTypeId = 0x1392;
constexpr std::size_t kGoldRewardAmountTierOffset = 0x13C;
constexpr std::size_t kGoldRewardAmountOffset = 0x140;
constexpr std::size_t kGoldRewardLifetimeOffset = 0x144;
constexpr std::size_t kGoldRewardActiveOffset = 0x148;
constexpr std::size_t kOrbRewardResourceKindOffset = 0x13C;
constexpr std::size_t kOrbRewardValueOffset = 0x140;
constexpr std::size_t kOrbRewardLifetimeOffset = 0x144;
constexpr std::size_t kOrbRewardMotionOffset = 0x148;
constexpr float kOrbHealthRewardScale = 25.0f;
constexpr float kOrbManaRewardScale = 40.0f;
constexpr std::size_t kAttachmentStaffVisualStateOffset = 0x84;
constexpr std::size_t kVisualLinkColorBlockOffset = 0x88;
constexpr std::uint32_t kAttachmentStaffItemTypeId = 0x1B5C;
constexpr int kMaxPacketsPerTick = 64;
constexpr float kRenderDriveEffectTimerEpsilon = 0.001f;

struct RenderDriveEffectState {
    float timer = 0.0f;
    float progress = 0.0f;
};

struct RecentRunEnemyDeathSnapshot {
    std::uint64_t network_actor_id = 0;
    std::uint32_t native_type_id = 0;
    std::int32_t enemy_type = -1;
    float position_x = 0.0f;
    float position_y = 0.0f;
    float radius = 0.0f;
    float heading = 0.0f;
    float max_hp = 0.0f;
    std::uint64_t expires_ms = 0;
};

enum class LootOrbResourceKind : std::uint8_t {
    Health = 0,
    Mana = 1,
};

struct LootPickupResultPayload {
    std::int32_t amount = 0;
    std::int32_t resulting_gold = 0;
    std::uint32_t gold_revision = 0;
    std::int32_t resource_kind = -1;
    float resource_delta = 0.0f;
    float resulting_life_current = 0.0f;
    float resulting_life_max = 0.0f;
    float resulting_mana_current = 0.0f;
    float resulting_mana_max = 0.0f;
    std::uint32_t item_type_id = 0;
    std::int32_t item_slot = -1;
    std::int32_t stack_count = 0;
    std::uint32_t inventory_revision = 0;
};

RenderDriveEffectState NormalizeRenderDriveEffectState(float timer, float progress) {
    RenderDriveEffectState state;
    if (!std::isfinite(timer) || timer <= kRenderDriveEffectTimerEpsilon) {
        return state;
    }

    state.timer = timer;
    if (std::isfinite(progress)) {
        state.progress = (std::clamp)(progress, 0.0f, 1.0f);
    }
    return state;
}

bool TryReadAttachmentStaffVisualState(
    const SDModEquipVisualLaneState& attachment_lane,
    std::uint32_t* visual_state) {
    if (visual_state == nullptr ||
        attachment_lane.current_object_address == 0 ||
        attachment_lane.current_object_type_id != kAttachmentStaffItemTypeId) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    return memory.TryReadField(
        attachment_lane.current_object_address,
        kAttachmentStaffVisualStateOffset,
        visual_state);
}

bool TryReadVisualLinkColorBlock(
    const SDModEquipVisualLaneState& visual_lane,
    std::uint32_t* type_id,
    std::array<std::uint8_t, kParticipantVisualLinkColorBlockBytes>* color_block) {
    if (type_id == nullptr ||
        color_block == nullptr ||
        visual_lane.current_object_address == 0 ||
        visual_lane.current_object_type_id == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    if (!memory.TryRead(
            visual_lane.current_object_address + kVisualLinkColorBlockOffset,
            color_block->data(),
            color_block->size())) {
        return false;
    }

    *type_id = visual_lane.current_object_type_id;
    return true;
}

std::uint16_t ClampInventoryCountForPacket(int value) {
    if (value <= 0) {
        return 0;
    }
    if (value > static_cast<int>((std::numeric_limits<std::uint16_t>::max)())) {
        return (std::numeric_limits<std::uint16_t>::max)();
    }
    return static_cast<std::uint16_t>(value);
}

std::vector<ParticipantInventoryItemState> BuildOwnedInventoryItems(
    const SDModInventoryState& inventory_state) {
    std::vector<ParticipantInventoryItemState> items;
    items.reserve(inventory_state.items.size());
    for (const auto& item : inventory_state.items) {
        if (!item.valid || item.type_id == 0) {
            continue;
        }
        ParticipantInventoryItemState built;
        built.type_id = item.type_id;
        built.slot = item.slot;
        built.stack_count = item.stack_count;
        items.push_back(built);
    }
    return items;
}

bool InventoryItemsEqual(
    const std::vector<ParticipantInventoryItemState>& left,
    const std::vector<ParticipantInventoryItemState>& right) {
    if (left.size() != right.size()) {
        return false;
    }
    for (std::size_t index = 0; index < left.size(); ++index) {
        if (left[index].type_id != right[index].type_id ||
            left[index].slot != right[index].slot ||
            left[index].stack_count != right[index].stack_count) {
            return false;
        }
    }
    return true;
}

void RefreshOwnedInventoryFromSnapshot(
    const SDModInventoryState& inventory_state,
    ParticipantOwnedProgressionState* owned_progression) {
    if (owned_progression == nullptr || !inventory_state.valid) {
        return;
    }

    auto next_items = BuildOwnedInventoryItems(inventory_state);
    const auto next_total_count = ClampInventoryCountForPacket(inventory_state.item_count);
    const bool next_truncated =
        inventory_state.truncated ||
        inventory_state.item_count > static_cast<int>(next_items.size());
    const bool changed =
        owned_progression->inventory_item_total_count != next_total_count ||
        owned_progression->inventory_truncated != next_truncated ||
        !InventoryItemsEqual(owned_progression->inventory_items, next_items);
    if (!changed) {
        return;
    }

    owned_progression->inventory_item_total_count = next_total_count;
    owned_progression->inventory_truncated = next_truncated;
    owned_progression->inventory_items = std::move(next_items);
    owned_progression->inventory_revision += 1;
}

std::uint16_t ClampProgressionBookEntryCountForPacket(int value) {
    if (value <= 0) {
        return 0;
    }
    if (value > static_cast<int>((std::numeric_limits<std::uint16_t>::max)())) {
        return (std::numeric_limits<std::uint16_t>::max)();
    }
    return static_cast<std::uint16_t>(value);
}

std::vector<ParticipantProgressionBookEntryState> BuildOwnedProgressionBookEntries(
    const SDModProgressionBookState& book_state) {
    std::vector<ParticipantProgressionBookEntryState> entries;
    entries.reserve(book_state.entries.size());
    for (const auto& entry : book_state.entries) {
        if (!entry.valid) {
            continue;
        }

        ParticipantProgressionBookEntryState built;
        built.entry_index = entry.entry_index;
        built.internal_id = entry.internal_id;
        built.active = entry.active;
        built.visible = entry.visible;
        built.category = entry.category;
        built.statbook_max_level = entry.statbook_max_level;
        entries.push_back(built);
    }
    return entries;
}

bool ProgressionBookEntriesEqual(
    const std::vector<ParticipantProgressionBookEntryState>& left,
    const std::vector<ParticipantProgressionBookEntryState>& right) {
    if (left.size() != right.size()) {
        return false;
    }
    for (std::size_t index = 0; index < left.size(); ++index) {
        if (left[index].entry_index != right[index].entry_index ||
            left[index].internal_id != right[index].internal_id ||
            left[index].active != right[index].active ||
            left[index].visible != right[index].visible ||
            left[index].category != right[index].category ||
            left[index].statbook_max_level != right[index].statbook_max_level) {
            return false;
        }
    }
    return true;
}

void RefreshOwnedProgressionBookFromSnapshot(
    const SDModProgressionBookState& book_state,
    ParticipantOwnedProgressionState* owned_progression) {
    if (owned_progression == nullptr || !book_state.valid) {
        return;
    }

    auto next_entries = BuildOwnedProgressionBookEntries(book_state);
    const auto next_total_count = ClampProgressionBookEntryCountForPacket(book_state.entry_count);
    const bool next_truncated =
        book_state.truncated ||
        book_state.entry_count > static_cast<int>(next_entries.size());
    const bool changed =
        owned_progression->progression_book_entry_total_count != next_total_count ||
        owned_progression->progression_book_truncated != next_truncated ||
        !ProgressionBookEntriesEqual(owned_progression->progression_book_entries, next_entries);
    if (!changed) {
        return;
    }

    owned_progression->progression_book_entry_total_count = next_total_count;
    owned_progression->progression_book_truncated = next_truncated;
    owned_progression->progression_book_entries = std::move(next_entries);
    owned_progression->statbook_revision += 1;
}

bool LoadoutsEqual(const BotLoadoutInfo& left, const BotLoadoutInfo& right) {
    return left.primary_entry_index == right.primary_entry_index &&
           left.primary_combo_entry_index == right.primary_combo_entry_index &&
           left.secondary_entry_indices == right.secondary_entry_indices;
}

void RefreshOwnedAbilityLoadoutFromProfile(
    const BotLoadoutInfo& loadout,
    ParticipantOwnedProgressionState* owned_progression) {
    if (owned_progression == nullptr) {
        return;
    }

    const bool changed =
        !owned_progression->ability_loadout_valid ||
        !LoadoutsEqual(owned_progression->ability_loadout, loadout);
    owned_progression->ability_loadout_valid = true;
    owned_progression->ability_loadout = loadout;
    if (changed) {
        owned_progression->loadout_revision += 1;
    }
}

std::int32_t NormalizeInventoryLootStackCount(std::uint32_t type_id, std::int32_t stack_count) {
    if (type_id != kPotionItemTypeId) {
        return stack_count > 0 ? stack_count : 0;
    }
    return (std::max)(stack_count, 1);
}

bool ApplyOwnedInventoryLootItem(
    std::uint32_t type_id,
    std::int32_t slot,
    std::int32_t stack_count,
    ParticipantOwnedProgressionState* owned_progression) {
    if (owned_progression == nullptr || type_id == 0) {
        return false;
    }

    const auto normalized_stack_count = NormalizeInventoryLootStackCount(type_id, stack_count);
    if (type_id == kPotionItemTypeId) {
        for (auto& item : owned_progression->inventory_items) {
            if (item.type_id == type_id && item.slot == slot) {
                const auto next_stack =
                    static_cast<std::int64_t>(item.stack_count) +
                    static_cast<std::int64_t>(normalized_stack_count);
                item.stack_count = next_stack >
                        static_cast<std::int64_t>((std::numeric_limits<std::int32_t>::max)())
                    ? (std::numeric_limits<std::int32_t>::max)()
                    : static_cast<std::int32_t>(next_stack);
                owned_progression->inventory_item_total_count =
                    ClampInventoryCountForPacket(
                        static_cast<int>(owned_progression->inventory_items.size()));
                owned_progression->inventory_truncated =
                    owned_progression->inventory_items.size() > kParticipantInventorySnapshotMaxItems;
                owned_progression->inventory_revision += 1;
                return true;
            }
        }
    }

    ParticipantInventoryItemState item;
    item.type_id = type_id;
    item.slot = slot;
    item.stack_count = normalized_stack_count;
    owned_progression->inventory_items.push_back(item);
    owned_progression->inventory_item_total_count =
        ClampInventoryCountForPacket(static_cast<int>(owned_progression->inventory_items.size()));
    owned_progression->inventory_truncated =
        owned_progression->inventory_items.size() > kParticipantInventorySnapshotMaxItems;
    owned_progression->inventory_revision += 1;
    return true;
}

struct LocalPeerEndpoint {
    sockaddr_in address{};
    std::uint64_t participant_id = 0;
    std::uint64_t last_packet_ms = 0;
};

struct QueuedLocalCastEvent {
    std::uint64_t native_queue_id = 0;
    std::int32_t skill_id = 0;
    std::uint64_t target_network_actor_id = 0;
    uintptr_t target_actor_address = 0;
    std::uint64_t minimum_hold_until_ms = 0;
    float position_x = 0.0f;
    float position_y = 0.0f;
    float direction_x = 0.0f;
    float direction_y = 0.0f;
    bool has_aim_target = false;
    float aim_target_x = 0.0f;
    float aim_target_y = 0.0f;
};

struct ActiveLocalCastInput {
    bool active = false;
    std::uint32_t cast_sequence = 0;
    std::int32_t skill_id = 0;
    std::uint64_t target_network_actor_id = 0;
    uintptr_t target_actor_address = 0;
    std::uint64_t minimum_hold_until_ms = 0;
    float last_position_x = 0.0f;
    float last_position_y = 0.0f;
    float last_direction_x = 0.0f;
    float last_direction_y = 0.0f;
    bool has_aim_target = false;
    float last_aim_target_x = 0.0f;
    float last_aim_target_y = 0.0f;
    std::uint64_t last_sent_ms = 0;
};

struct RemoteCastInputTracker {
    std::uint32_t cast_sequence = 0;
    std::uint32_t last_packet_sequence = 0;
    bool start_queued = false;
    bool release_seen = false;
    std::uint64_t last_packet_ms = 0;
};

struct QueuedLocalEnemyDamageClaim {
    std::uint64_t network_actor_id = 0;
    std::int32_t skill_id = 0;
    float authoritative_hp = 0.0f;
    float local_hp = 0.0f;
    float max_hp = 0.0f;
    float target_position_x = 0.0f;
    float target_position_y = 0.0f;
};

struct QueuedLocalLootPickupRequest {
    std::uint64_t network_drop_id = 0;
    std::uint32_t request_sequence = 0;
};

struct LocalTransportState {
    bool configured = false;
    bool initialized = false;
    bool winsock_initialized = false;
    bool is_host = false;
    SOCKET socket_handle = INVALID_SOCKET;
    std::uint16_t local_port = 0;
    std::string remote_host;
    std::uint16_t remote_port = 0;
    bool configured_remote_valid = false;
    sockaddr_in configured_remote{};
    std::uint64_t local_peer_id = 0;
    std::uint64_t last_send_ms = 0;
    std::uint64_t last_world_snapshot_send_ms = 0;
    std::uint64_t last_loot_snapshot_send_ms = 0;
    std::uint64_t last_client_host_run_request_ms = 0;
    std::uint32_t next_sequence = 1;
    std::uint32_t world_scene_epoch = 0;
    std::uint64_t packets_sent = 0;
    std::uint64_t packets_received = 0;
    std::uint32_t next_cast_sequence = 1;
    std::uint32_t next_enemy_damage_claim_sequence = 1;
    std::string world_scene_key;
    std::unordered_map<uintptr_t, std::uint64_t> hub_world_actor_ids_by_address;
    std::unordered_map<uintptr_t, std::uint64_t> run_host_local_world_actor_ids_by_address;
    std::unordered_map<uintptr_t, std::uint64_t> run_loot_drop_ids_by_address;
    std::unordered_map<std::uint64_t, RecentRunEnemyDeathSnapshot> recent_run_enemy_deaths_by_network_id;
    std::unordered_map<std::uint64_t, float> last_enemy_claimed_hp_by_network_id;
    std::unordered_map<std::uint64_t, std::uint64_t> rejected_enemy_damage_retry_suppressed_until_ms;
    std::unordered_map<std::uint64_t, std::uint32_t> last_cast_sequence_by_participant;
    std::unordered_map<std::uint64_t, RemoteCastInputTracker> remote_cast_inputs_by_participant;
    std::unordered_map<std::uint64_t, std::uint32_t> last_enemy_claim_sequence_by_participant;
    std::unordered_map<std::uint64_t, std::uint32_t> last_loot_pickup_request_sequence_by_participant;
    std::unordered_set<std::uint64_t> accepted_loot_pickup_drop_ids;
    ActiveLocalCastInput active_local_cast_input;
    std::uint32_t next_hub_world_actor_serial = 1;
    std::uint32_t next_run_host_local_world_actor_serial = 1;
    std::uint32_t next_run_loot_drop_serial = 1;
    std::vector<LocalPeerEndpoint> peers;
};

LocalTransportState g_local_transport;
std::mutex g_local_transport_event_mutex;
std::vector<QueuedLocalCastEvent> g_queued_local_cast_events;
std::uint64_t g_next_local_cast_event_id = 1;
std::vector<QueuedLocalEnemyDamageClaim> g_queued_local_enemy_damage_claims;
std::vector<QueuedLocalLootPickupRequest> g_queued_local_loot_pickup_requests;
std::uint32_t g_next_local_loot_pickup_request_sequence = 1;

std::string ReadEnvironmentVariable(const char* name) {
    char* value = nullptr;
    std::size_t value_length = 0;
    if (_dupenv_s(&value, &value_length, name) != 0 || value == nullptr) {
        return {};
    }

    std::string result(value);
    std::free(value);
    return result;
}

std::string ToLowerAscii(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char ch) {
        if (ch >= 'A' && ch <= 'Z') {
            return static_cast<char>(ch - 'A' + 'a');
        }
        return static_cast<char>(ch);
    });
    return value;
}

bool TryParseUnsigned64(const std::string& text, std::uint64_t* value) {
    if (value == nullptr || text.empty()) {
        return false;
    }

    const char* first = text.data();
    const char* last = text.data() + text.size();
    int base = 10;
    if (text.size() > 2 && text[0] == '0' && (text[1] == 'x' || text[1] == 'X')) {
        first += 2;
        base = 16;
    }

    std::uint64_t parsed = 0;
    const auto result = std::from_chars(first, last, parsed, base);
    if (result.ec != std::errc{} || result.ptr != last) {
        return false;
    }

    *value = parsed;
    return true;
}

std::uint16_t ReadPortEnvironmentVariable(const char* name, std::uint16_t default_value) {
    const auto text = ReadEnvironmentVariable(name);
    std::uint64_t parsed = 0;
    if (!TryParseUnsigned64(text, &parsed) ||
        parsed == 0 ||
        parsed > (std::numeric_limits<std::uint16_t>::max)()) {
        return default_value;
    }
    return static_cast<std::uint16_t>(parsed);
}

std::uint64_t ReadParticipantId(std::uint16_t local_port) {
    const auto text = ReadEnvironmentVariable(kParticipantIdEnvironmentVariable);
    std::uint64_t parsed = 0;
    if (TryParseUnsigned64(text, &parsed) && parsed != 0 && parsed != kLocalParticipantId) {
        return parsed;
    }
    return kLocalDevParticipantIdBase | static_cast<std::uint64_t>(local_port);
}

bool SameEndpoint(const sockaddr_in& left, const sockaddr_in& right) {
    return left.sin_family == right.sin_family &&
           left.sin_port == right.sin_port &&
           left.sin_addr.S_un.S_addr == right.sin_addr.S_un.S_addr;
}

std::string EndpointToString(const sockaddr_in& address) {
    std::array<char, INET_ADDRSTRLEN> text{};
    const char* converted = InetNtopA(AF_INET, const_cast<IN_ADDR*>(&address.sin_addr), text.data(), text.size());
    std::ostringstream stream;
    stream << (converted != nullptr ? converted : "0.0.0.0")
           << ":" << ntohs(address.sin_port);
    return stream.str();
}

bool ResolveIpv4Endpoint(const std::string& host, std::uint16_t port, sockaddr_in* address) {
    if (address == nullptr || host.empty() || port == 0) {
        return false;
    }

    sockaddr_in resolved{};
    resolved.sin_family = AF_INET;
    resolved.sin_port = htons(port);
    if (InetPtonA(AF_INET, host.c_str(), &resolved.sin_addr) != 1) {
        addrinfo hints{};
        hints.ai_family = AF_INET;
        hints.ai_socktype = SOCK_DGRAM;
        addrinfo* result = nullptr;
        if (getaddrinfo(host.c_str(), nullptr, &hints, &result) != 0 || result == nullptr) {
            return false;
        }
        resolved.sin_addr = reinterpret_cast<sockaddr_in*>(result->ai_addr)->sin_addr;
        freeaddrinfo(result);
    }

    *address = resolved;
    return true;
}

bool IsLocalUdpRequested() {
    const auto transport = ToLowerAscii(ReadEnvironmentVariable(kTransportEnvironmentVariable));
    return transport == "local_udp" || transport == "local-udp" || transport == "udp";
}

bool ConfigureLocalTransport() {
    if (!IsLocalUdpRequested()) {
        g_local_transport = LocalTransportState{};
        std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
        g_queued_local_cast_events.clear();
        g_queued_local_enemy_damage_claims.clear();
        return false;
    }

    const auto role = ToLowerAscii(ReadEnvironmentVariable(kRoleEnvironmentVariable));
    const bool is_host = role.empty() || role == "host" || role == "server";
    const auto local_port = ReadPortEnvironmentVariable(
        kLocalPortEnvironmentVariable,
        is_host ? kDefaultHostPort : kDefaultClientPort);
    const auto remote_port = ReadPortEnvironmentVariable(
        kRemotePortEnvironmentVariable,
        is_host ? kDefaultClientPort : kDefaultHostPort);
    auto remote_host = ReadEnvironmentVariable(kRemoteHostEnvironmentVariable);
    if (remote_host.empty()) {
        remote_host = "127.0.0.1";
    }

    g_local_transport = LocalTransportState{};
    g_local_transport.configured = true;
    g_local_transport.is_host = is_host;
    g_local_transport.local_port = local_port;
    g_local_transport.remote_host = remote_host;
    g_local_transport.remote_port = remote_port;
    g_local_transport.local_peer_id = ReadParticipantId(local_port);
    g_local_transport.configured_remote_valid = ResolveIpv4Endpoint(
        remote_host,
        remote_port,
        &g_local_transport.configured_remote);
    {
        std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
        g_queued_local_cast_events.clear();
        g_queued_local_enemy_damage_claims.clear();
    }
    return true;
}

void UpsertPeerEndpoint(const sockaddr_in& address, std::uint64_t participant_id, std::uint64_t now_ms) {
    for (auto& peer : g_local_transport.peers) {
        if (SameEndpoint(peer.address, address) && peer.participant_id == participant_id) {
            peer.participant_id = participant_id;
            peer.last_packet_ms = now_ms;
            return;
        }
    }

    LocalPeerEndpoint peer;
    peer.address = address;
    peer.participant_id = participant_id;
    peer.last_packet_ms = now_ms;
    g_local_transport.peers.push_back(peer);
    Log(
        "Multiplayer local UDP learned peer endpoint=" + EndpointToString(address) +
        " participant_id=" + std::to_string(participant_id));
}

std::string ReadLocalDisplayName() {
    auto name = ReadEnvironmentVariable(kPlayerNameEnvironmentVariable);
    if (name.empty()) {
        return {};
    }
    if (name.size() >= kParticipantDisplayNameBytes) {
        name.resize(kParticipantDisplayNameBytes - 1);
    }
    return name;
}

void CopyPacketDisplayName(const std::string& name, StatePacket* packet) {
    if (packet == nullptr) {
        return;
    }
    std::memset(packet->display_name, 0, sizeof(packet->display_name));
    if (name.empty()) {
        return;
    }
    const auto count = (std::min)(name.size(), sizeof(packet->display_name) - 1);
    std::memcpy(packet->display_name, name.data(), count);
}

std::string PacketDisplayName(const StatePacket& packet) {
    std::size_t length = 0;
    while (length < sizeof(packet.display_name) && packet.display_name[length] != '\0') {
        ++length;
    }
    return std::string(packet.display_name, packet.display_name + length);
}

ParticipantSceneIntent SceneIntentFromPacket(const StatePacket& packet) {
    ParticipantSceneIntent intent;
    intent.kind = packet.in_run != 0 ? ParticipantSceneIntentKind::Run
                                     : ParticipantSceneIntentKind::SharedHub;
    return intent;
}

ParticipantSceneIntent SceneIntentFromLocalScene() {
    SDModSceneState scene_state;
    if (!TryGetSceneState(&scene_state) || !scene_state.valid) {
        return DefaultParticipantSceneIntent();
    }

    ParticipantSceneIntent intent;
    if (scene_state.kind == "arena") {
        intent.kind = ParticipantSceneIntentKind::Run;
        return intent;
    }
    if (scene_state.kind == "hub") {
        intent.kind = ParticipantSceneIntentKind::SharedHub;
        return intent;
    }

    intent.kind = ParticipantSceneIntentKind::PrivateRegion;
    intent.region_index = scene_state.current_region_index;
    intent.region_type_id = scene_state.region_type_id;
    return intent;
}

WorldSceneKind WorldSceneKindFromSceneIntent(const ParticipantSceneIntent& intent) {
    switch (intent.kind) {
    case ParticipantSceneIntentKind::SharedHub:
        return WorldSceneKind::SharedHub;
    case ParticipantSceneIntentKind::PrivateRegion:
        return WorldSceneKind::PrivateRegion;
    case ParticipantSceneIntentKind::Run:
        return WorldSceneKind::Run;
    }

    return WorldSceneKind::Unknown;
}

ParticipantSceneIntent SceneIntentFromWorldSceneKind(WorldSceneKind kind) {
    ParticipantSceneIntent intent;
    switch (kind) {
    case WorldSceneKind::SharedHub:
        intent.kind = ParticipantSceneIntentKind::SharedHub;
        break;
    case WorldSceneKind::PrivateRegion:
        intent.kind = ParticipantSceneIntentKind::PrivateRegion;
        break;
    case WorldSceneKind::Run:
        intent.kind = ParticipantSceneIntentKind::Run;
        break;
    case WorldSceneKind::Unknown:
    default:
        intent.kind = ParticipantSceneIntentKind::PrivateRegion;
        break;
    }
    return intent;
}

LootDropKind LootDropKindFromPacketValue(std::uint8_t kind) {
    switch (static_cast<LootDropKind>(kind)) {
    case LootDropKind::Gold:
        return LootDropKind::Gold;
    case LootDropKind::Item:
        return LootDropKind::Item;
    case LootDropKind::Potion:
        return LootDropKind::Potion;
    case LootDropKind::Orb:
        return LootDropKind::Orb;
    case LootDropKind::Powerup:
        return LootDropKind::Powerup;
    case LootDropKind::Unknown:
    default:
        return LootDropKind::Unknown;
    }
}

LootPickupResultCode LootPickupResultCodeFromPacketValue(std::uint8_t code) {
    switch (static_cast<LootPickupResultCode>(code)) {
    case LootPickupResultCode::Accepted:
        return LootPickupResultCode::Accepted;
    case LootPickupResultCode::AlreadyGone:
        return LootPickupResultCode::AlreadyGone;
    case LootPickupResultCode::OutOfRange:
        return LootPickupResultCode::OutOfRange;
    case LootPickupResultCode::WrongRun:
        return LootPickupResultCode::WrongRun;
    case LootPickupResultCode::Unsupported:
        return LootPickupResultCode::Unsupported;
    case LootPickupResultCode::Rejected:
    default:
        return LootPickupResultCode::Rejected;
    }
}

std::string BuildWorldSceneKey(const SDModSceneState& scene_state) {
    std::ostringstream stream;
    stream << scene_state.kind
           << ":" << scene_state.name
           << ":" << scene_state.current_region_index
           << ":" << scene_state.region_type_id
           << ":" << scene_state.gameplay_scene_address;
    return stream.str();
}

std::uint64_t BuildRunWorldActorNetworkId(std::uint32_t spawn_serial) {
    if (spawn_serial == 0) {
        return 0;
    }
    return kRunWorldActorNetworkIdBase | static_cast<std::uint64_t>(spawn_serial);
}

std::uint64_t BuildRunLootDropNetworkId(std::uint32_t spawn_serial) {
    if (spawn_serial == 0) {
        return 0;
    }
    return kRunLootDropNetworkIdBase | static_cast<std::uint64_t>(spawn_serial);
}

std::uint64_t AllocateRunHostLocalWorldActorNetworkId(const SDModSceneActorState& actor) {
    if (actor.actor_address == 0 || actor.object_type_id == 0) {
        return 0;
    }

    const auto existing = g_local_transport.run_host_local_world_actor_ids_by_address.find(actor.actor_address);
    if (existing != g_local_transport.run_host_local_world_actor_ids_by_address.end()) {
        return existing->second;
    }

    if (g_local_transport.next_run_host_local_world_actor_serial == 0) {
        g_local_transport.next_run_host_local_world_actor_serial = 1;
    }
    const auto serial = g_local_transport.next_run_host_local_world_actor_serial++;
    const auto network_actor_id =
        kRunHostLocalWorldActorNetworkIdBase | static_cast<std::uint64_t>(serial);
    g_local_transport.run_host_local_world_actor_ids_by_address.emplace(actor.actor_address, network_actor_id);
    Log(
        "world_snapshot: assigned host-local run actor network id. actor=" +
        HexString(actor.actor_address) +
        " type=" + HexString(static_cast<uintptr_t>(actor.object_type_id)) +
        " enemy_type=" + std::to_string(actor.enemy_type) +
        " network_actor_id=" + std::to_string(network_actor_id));
    return network_actor_id;
}

std::uint64_t AllocateRunLootDropNetworkId(const SDModSceneActorState& actor) {
    if (actor.actor_address == 0 || actor.object_type_id == 0) {
        return 0;
    }

    const auto existing = g_local_transport.run_loot_drop_ids_by_address.find(actor.actor_address);
    if (existing != g_local_transport.run_loot_drop_ids_by_address.end()) {
        return existing->second;
    }

    if (g_local_transport.next_run_loot_drop_serial == 0) {
        g_local_transport.next_run_loot_drop_serial = 1;
    }
    const auto serial = g_local_transport.next_run_loot_drop_serial++;
    const auto network_drop_id = BuildRunLootDropNetworkId(serial);
    g_local_transport.run_loot_drop_ids_by_address.emplace(actor.actor_address, network_drop_id);
    return network_drop_id;
}

bool IsRunStaticLayoutActorType(std::uint32_t native_type_id) {
    return native_type_id == kSolomonDigNativeTypeId ||
           native_type_id == kSolomonRunStaticNativeTypeId;
}

bool IsRunStaticLayoutActor(const SDModSceneActorState& actor) {
    return !actor.tracked_enemy &&
           IsRunStaticLayoutActorType(actor.object_type_id);
}

bool ShouldReplicateWorldActor(
    const SDModSceneActorState& actor,
    ParticipantSceneIntentKind scene_kind) {
    if (!actor.valid ||
        actor.actor_address == 0 ||
        actor.owner_address == 0 ||
        actor.object_type_id == 0 ||
        actor.object_type_id == 1 ||
        !std::isfinite(actor.x) ||
        !std::isfinite(actor.y) ||
        !std::isfinite(actor.radius) ||
        actor.radius < 0.0f) {
        return false;
    }

    if (scene_kind == ParticipantSceneIntentKind::Run) {
        return (actor.tracked_enemy &&
                std::isfinite(actor.hp) &&
                std::isfinite(actor.max_hp) &&
                actor.max_hp > 0.0f &&
                (actor.dead || actor.hp > kEnemyDamageClaimHpEpsilon)) ||
               IsRunStaticLayoutActor(actor);
    }

    return scene_kind == ParticipantSceneIntentKind::SharedHub;
}

bool IsReplicatedLootDropNativeType(std::uint32_t native_type_id) {
    return native_type_id == kGoldRewardNativeTypeId ||
           native_type_id == kOrbRewardNativeTypeId ||
           native_type_id == kItemDropNativeTypeId;
}

bool ShouldReplicateLootDropActor(
    const SDModSceneActorState& actor,
    ParticipantSceneIntentKind scene_kind) {
    return scene_kind == ParticipantSceneIntentKind::Run &&
           actor.valid &&
           actor.actor_address != 0 &&
           IsReplicatedLootDropNativeType(actor.object_type_id) &&
           std::isfinite(actor.x) &&
           std::isfinite(actor.y) &&
           std::isfinite(actor.radius) &&
           actor.radius >= 0.0f;
}

std::uint64_t AllocateHubWorldActorNetworkId(const SDModSceneActorState& actor) {
    if (actor.actor_address == 0 || actor.object_type_id == 0) {
        return 0;
    }

    const auto existing = g_local_transport.hub_world_actor_ids_by_address.find(actor.actor_address);
    if (existing != g_local_transport.hub_world_actor_ids_by_address.end()) {
        return existing->second;
    }

    if (g_local_transport.next_hub_world_actor_serial == 0) {
        g_local_transport.next_hub_world_actor_serial = 1;
    }
    const auto serial = g_local_transport.next_hub_world_actor_serial++;
    const auto network_actor_id =
        (static_cast<std::uint64_t>(actor.object_type_id) << 32) |
        static_cast<std::uint64_t>(serial);
    g_local_transport.hub_world_actor_ids_by_address.emplace(actor.actor_address, network_actor_id);
    return network_actor_id;
}

void ClearHubWorldActorNetworkIds() {
    g_local_transport.hub_world_actor_ids_by_address.clear();
    g_local_transport.next_hub_world_actor_serial = 1;
}

void ClearRunHostLocalWorldActorNetworkIds() {
    g_local_transport.run_host_local_world_actor_ids_by_address.clear();
    g_local_transport.recent_run_enemy_deaths_by_network_id.clear();
    g_local_transport.next_run_host_local_world_actor_serial = 1;
}

void ClearRunLootDropNetworkIds() {
    g_local_transport.run_loot_drop_ids_by_address.clear();
    g_local_transport.accepted_loot_pickup_drop_ids.clear();
    g_local_transport.next_run_loot_drop_serial = 1;
}

void RefreshWorldSceneTracking(const SDModSceneState& scene_state) {
    const auto scene_key = BuildWorldSceneKey(scene_state);
    if (scene_key == g_local_transport.world_scene_key) {
        return;
    }

    g_local_transport.world_scene_key = scene_key;
    g_local_transport.world_scene_epoch += 1;
    ClearHubWorldActorNetworkIds();
    ClearRunHostLocalWorldActorNetworkIds();
    ClearRunLootDropNetworkIds();
}

void PruneHubWorldActorNetworkIds(
    const std::vector<SDModSceneActorState>& actors,
    ParticipantSceneIntentKind scene_kind) {
    if (scene_kind != ParticipantSceneIntentKind::SharedHub) {
        ClearHubWorldActorNetworkIds();
        return;
    }

    std::unordered_set<uintptr_t> live_actor_addresses;
    for (const auto& actor : actors) {
        if (ShouldReplicateWorldActor(actor, scene_kind)) {
            live_actor_addresses.insert(actor.actor_address);
        }
    }

    for (auto iterator = g_local_transport.hub_world_actor_ids_by_address.begin();
         iterator != g_local_transport.hub_world_actor_ids_by_address.end();) {
        if (live_actor_addresses.find(iterator->first) == live_actor_addresses.end()) {
            iterator = g_local_transport.hub_world_actor_ids_by_address.erase(iterator);
        } else {
            ++iterator;
        }
    }
}

void PruneRunHostLocalWorldActorNetworkIds(
    const std::vector<SDModSceneActorState>& actors,
    ParticipantSceneIntentKind scene_kind) {
    if (scene_kind != ParticipantSceneIntentKind::Run) {
        ClearRunHostLocalWorldActorNetworkIds();
        return;
    }

    std::unordered_set<uintptr_t> live_actor_addresses;
    for (const auto& actor : actors) {
        if (ShouldReplicateWorldActor(actor, scene_kind)) {
            live_actor_addresses.insert(actor.actor_address);
        }
    }

    for (auto iterator = g_local_transport.run_host_local_world_actor_ids_by_address.begin();
         iterator != g_local_transport.run_host_local_world_actor_ids_by_address.end();) {
        if (live_actor_addresses.find(iterator->first) == live_actor_addresses.end()) {
            iterator = g_local_transport.run_host_local_world_actor_ids_by_address.erase(iterator);
        } else {
            ++iterator;
        }
    }
}

void PruneRunLootDropNetworkIds(
    const std::vector<SDModSceneActorState>& actors,
    ParticipantSceneIntentKind scene_kind) {
    if (scene_kind != ParticipantSceneIntentKind::Run) {
        ClearRunLootDropNetworkIds();
        return;
    }

    std::unordered_set<uintptr_t> live_actor_addresses;
    for (const auto& actor : actors) {
        if (ShouldReplicateLootDropActor(actor, scene_kind)) {
            live_actor_addresses.insert(actor.actor_address);
        }
    }

    for (auto iterator = g_local_transport.run_loot_drop_ids_by_address.begin();
         iterator != g_local_transport.run_loot_drop_ids_by_address.end();) {
        if (live_actor_addresses.find(iterator->first) == live_actor_addresses.end()) {
            iterator = g_local_transport.run_loot_drop_ids_by_address.erase(iterator);
        } else {
            ++iterator;
        }
    }
}

float ReadActorHeadingOrZero(uintptr_t actor_address) {
    if (actor_address == 0 || kActorHeadingOffset == 0) {
        return 0.0f;
    }

    float heading = 0.0f;
    if (!ProcessMemory::Instance().TryReadField(actor_address, kActorHeadingOffset, &heading) ||
        !std::isfinite(heading)) {
        return 0.0f;
    }
    return heading;
}

void PruneRecentRunEnemyDeathSnapshots(std::uint64_t now_ms) {
    for (auto it = g_local_transport.recent_run_enemy_deaths_by_network_id.begin();
         it != g_local_transport.recent_run_enemy_deaths_by_network_id.end();) {
        if (it->second.expires_ms <= now_ms) {
            it = g_local_transport.recent_run_enemy_deaths_by_network_id.erase(it);
            continue;
        }
        ++it;
    }
}

void RecordRecentRunEnemyDeathSnapshot(
    std::uint64_t network_actor_id,
    const SDModSceneActorState& actor,
    std::uint64_t now_ms) {
    if (network_actor_id == 0 ||
        !actor.tracked_enemy ||
        actor.actor_address == 0 ||
        actor.object_type_id == 0 ||
        !std::isfinite(actor.x) ||
        !std::isfinite(actor.y) ||
        !std::isfinite(actor.radius) ||
        !std::isfinite(actor.max_hp) ||
        actor.max_hp <= 0.0f) {
        return;
    }

    RecentRunEnemyDeathSnapshot snapshot;
    snapshot.network_actor_id = network_actor_id;
    snapshot.native_type_id = actor.object_type_id;
    snapshot.enemy_type = actor.enemy_type;
    snapshot.position_x = actor.x;
    snapshot.position_y = actor.y;
    snapshot.radius = actor.radius;
    snapshot.heading = ReadActorHeadingOrZero(actor.actor_address);
    snapshot.max_hp = actor.max_hp;
    snapshot.expires_ms = now_ms + kRecentRunEnemyDeathSnapshotHoldMs;
    g_local_transport.recent_run_enemy_deaths_by_network_id[network_actor_id] = snapshot;
}

bool IsHubStudentActorType(std::uint32_t native_type_id) {
    return native_type_id == 0x138A;
}

bool IsSharedHubFactoryActorType(std::uint32_t native_type_id) {
    switch (native_type_id) {
    case 0x1389:
    case 0x138A:
    case 0x138B:
    case 0x138C:
    case 0x138D:
    case 0x138F:
    case 0x1390:
        return true;
    default:
        return false;
    }
}

void PopulateWorldActorPresentationSnapshot(
    uintptr_t actor_address,
    std::uint32_t native_type_id,
    ParticipantSceneIntentKind scene_kind,
    bool tracked_enemy,
    WorldActorSnapshotPacketState* snapshot) {
    if (actor_address == 0 || snapshot == nullptr) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    if (scene_kind == ParticipantSceneIntentKind::Run &&
        tracked_enemy &&
        kActorWalkCyclePrimaryOffset != 0 &&
        kActorWalkCycleSecondaryOffset != 0) {
        auto read_sane_animation_float = [&](std::size_t offset, float* value) -> bool {
            if (value == nullptr ||
                !memory.TryReadField(actor_address, offset, value) ||
                !std::isfinite(*value)) {
                return false;
            }
            constexpr float kMaxSaneRunEnemyLocomotionMagnitude = 4096.0f;
            return *value >= -kMaxSaneRunEnemyLocomotionMagnitude &&
                   *value <= kMaxSaneRunEnemyLocomotionMagnitude;
        };

        float walk_cycle_primary = 0.0f;
        float walk_cycle_secondary = 0.0f;
        if (read_sane_animation_float(kActorWalkCyclePrimaryOffset, &walk_cycle_primary) &&
            read_sane_animation_float(kActorWalkCycleSecondaryOffset, &walk_cycle_secondary)) {
            snapshot->presentation_flags |= WorldActorPresentationFlagLocomotionFloats;
            snapshot->walk_cycle_primary = walk_cycle_primary;
            snapshot->walk_cycle_secondary = walk_cycle_secondary;
        }
    }

    if (scene_kind == ParticipantSceneIntentKind::SharedHub &&
        IsSharedHubFactoryActorType(native_type_id) &&
        kActorAnimationDriveStateByteOffset != 0) {
        std::uint32_t drive_word = 0;
        if (memory.TryReadField(actor_address, kActorAnimationDriveStateByteOffset, &drive_word)) {
            snapshot->presentation_flags |= WorldActorPresentationFlagAnimationDriveWord;
            snapshot->anim_drive_state_word = drive_word;
        }
    }

    if (scene_kind != ParticipantSceneIntentKind::SharedHub ||
        !IsHubStudentActorType(native_type_id)) {
        return;
    }

    if (kActorRenderVariantPrimaryOffset != 0 &&
        kActorRenderVariantSecondaryOffset != 0 &&
        kActorRenderWeaponTypeOffset != 0 &&
        kActorRenderSelectionByteOffset != 0 &&
        kActorRenderVariantTertiaryOffset != 0) {
        bool have_variant_bytes = true;
        have_variant_bytes = memory.TryReadField(
            actor_address,
            kActorRenderVariantPrimaryOffset,
            &snapshot->render_variant_primary) && have_variant_bytes;
        have_variant_bytes = memory.TryReadField(
            actor_address,
            kActorRenderVariantSecondaryOffset,
            &snapshot->render_variant_secondary) && have_variant_bytes;
        have_variant_bytes = memory.TryReadField(
            actor_address,
            kActorRenderWeaponTypeOffset,
            &snapshot->render_weapon_type) && have_variant_bytes;
        have_variant_bytes = memory.TryReadField(
            actor_address,
            kActorRenderSelectionByteOffset,
            &snapshot->render_selection_byte) && have_variant_bytes;
        have_variant_bytes = memory.TryReadField(
            actor_address,
            kActorRenderVariantTertiaryOffset,
            &snapshot->render_variant_tertiary) && have_variant_bytes;
        if (have_variant_bytes) {
            snapshot->presentation_flags |= WorldActorPresentationFlagStudentVariantBytes;
        }
    }

    if (kStudentVisualStateBlockOffset != 0 &&
        memory.TryRead(
            actor_address + kStudentVisualStateBlockOffset,
            snapshot->student_visual_state,
            kWorldActorStudentVisualStateBytes)) {
        snapshot->presentation_flags |= WorldActorPresentationFlagStudentVisualState;
    }
}

std::int32_t RoundRewardAmountToInt(float amount) {
    if (!std::isfinite(amount) || amount <= 0.0f) {
        return 0;
    }
    if (amount >= static_cast<float>((std::numeric_limits<std::int32_t>::max)())) {
        return (std::numeric_limits<std::int32_t>::max)();
    }
    return static_cast<std::int32_t>(std::lround(amount));
}

bool TryResolveLootOrbResourceKind(std::int32_t resource_kind, LootOrbResourceKind* kind) {
    if (kind == nullptr) {
        return false;
    }
    switch (resource_kind) {
    case static_cast<std::int32_t>(LootOrbResourceKind::Health):
        *kind = LootOrbResourceKind::Health;
        return true;
    case static_cast<std::int32_t>(LootOrbResourceKind::Mana):
        *kind = LootOrbResourceKind::Mana;
        return true;
    default:
        return false;
    }
}

float LootOrbScaleForResourceKind(LootOrbResourceKind kind) {
    return kind == LootOrbResourceKind::Health ? kOrbHealthRewardScale : kOrbManaRewardScale;
}

float ComputeLootOrbResourceDelta(std::int32_t resource_kind, float raw_value) {
    LootOrbResourceKind kind = LootOrbResourceKind::Health;
    if (!TryResolveLootOrbResourceKind(resource_kind, &kind) ||
        !std::isfinite(raw_value) ||
        raw_value <= kLootPickupResourceEpsilon) {
        return 0.0f;
    }
    const float delta = raw_value * LootOrbScaleForResourceKind(kind);
    if (!std::isfinite(delta) || delta <= kLootPickupResourceEpsilon) {
        return 0.0f;
    }
    return (std::min)(delta, kLootPickupMaxResourceDelta);
}

bool TryReadItemDropHeldItemMetadata(
    uintptr_t drop_actor_address,
    std::uint32_t* item_type_id,
    std::int32_t* item_slot,
    std::int32_t* stack_count) {
    if (drop_actor_address == 0 ||
        item_type_id == nullptr ||
        item_slot == nullptr ||
        stack_count == nullptr ||
        kItemDropHeldItemOffset == 0 ||
        kGameObjectTypeIdOffset == 0 ||
        kItemSlotOffset == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    std::uint32_t held_item_address = 0;
    if (!memory.TryReadField(drop_actor_address, kItemDropHeldItemOffset, &held_item_address) ||
        held_item_address == 0 ||
        !memory.IsReadableRange(held_item_address + kGameObjectTypeIdOffset, sizeof(std::uint32_t)) ||
        !memory.IsReadableRange(held_item_address + kItemSlotOffset, sizeof(std::int32_t))) {
        return false;
    }

    std::uint32_t read_item_type_id = 0;
    std::int32_t read_item_slot = -1;
    if (!memory.TryReadField(held_item_address, kGameObjectTypeIdOffset, &read_item_type_id) ||
        read_item_type_id == 0 ||
        !memory.TryReadField(held_item_address, kItemSlotOffset, &read_item_slot)) {
        return false;
    }

    std::int32_t read_stack_count = 0;
    if (read_item_type_id == kPotionItemTypeId &&
        kPotionStackCountOffset != 0 &&
        memory.IsReadableRange(held_item_address + kPotionStackCountOffset, sizeof(std::int32_t))) {
        (void)memory.TryReadField(held_item_address, kPotionStackCountOffset, &read_stack_count);
    }

    *item_type_id = read_item_type_id;
    *item_slot = read_item_slot;
    *stack_count = NormalizeInventoryLootStackCount(read_item_type_id, read_stack_count);
    return true;
}

bool TryPopulateGoldLootDropSnapshot(
    const SDModSceneActorState& actor,
    std::uint64_t network_drop_id,
    LootDropSnapshotPacketState* snapshot) {
    if (snapshot == nullptr ||
        network_drop_id == 0 ||
        !ShouldReplicateLootDropActor(actor, ParticipantSceneIntentKind::Run) ||
        actor.object_type_id != kGoldRewardNativeTypeId) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    std::uint8_t amount_tier = 0;
    std::uint32_t amount_raw = 0;
    std::uint32_t lifetime = 0;
    if (!memory.TryReadField(actor.actor_address, kGoldRewardAmountTierOffset, &amount_tier) ||
        !memory.TryReadField(actor.actor_address, kGoldRewardAmountOffset, &amount_raw) ||
        !memory.TryReadField(actor.actor_address, kGoldRewardLifetimeOffset, &lifetime)) {
        return false;
    }

    LootDropSnapshotPacketState built{};
    built.network_drop_id = network_drop_id;
    built.native_type_id = actor.object_type_id;
    built.drop_kind = static_cast<std::uint8_t>(LootDropKind::Gold);
    built.amount = amount_raw <= static_cast<std::uint32_t>((std::numeric_limits<std::int32_t>::max)())
                       ? static_cast<std::int32_t>(amount_raw)
                       : (std::numeric_limits<std::int32_t>::max)();
    built.flags = built.amount > 0 && lifetime != 0 ? LootDropSnapshotFlagActive : 0;
    built.amount_tier = amount_tier;
    built.value = static_cast<float>(built.amount);
    built.actor_slot = actor.actor_slot;
    built.world_slot = actor.world_slot;
    built.lifetime = lifetime;
    built.position_x = actor.x;
    built.position_y = actor.y;
    built.radius = actor.radius;
    *snapshot = built;
    return true;
}

bool TryPopulateOrbLootDropSnapshot(
    const SDModSceneActorState& actor,
    std::uint64_t network_drop_id,
    LootDropSnapshotPacketState* snapshot) {
    if (snapshot == nullptr ||
        network_drop_id == 0 ||
        !ShouldReplicateLootDropActor(actor, ParticipantSceneIntentKind::Run) ||
        actor.object_type_id != kOrbRewardNativeTypeId) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    std::uint8_t resource_kind = 0;
    float raw_value = 0.0f;
    std::uint32_t lifetime = 0;
    float motion = 0.0f;
    if (!memory.TryReadField(actor.actor_address, kOrbRewardResourceKindOffset, &resource_kind) ||
        !memory.TryReadField(actor.actor_address, kOrbRewardValueOffset, &raw_value) ||
        !memory.TryReadField(actor.actor_address, kOrbRewardLifetimeOffset, &lifetime) ||
        !memory.TryReadField(actor.actor_address, kOrbRewardMotionOffset, &motion)) {
        return false;
    }

    LootOrbResourceKind resolved_kind = LootOrbResourceKind::Health;
    if (!TryResolveLootOrbResourceKind(resource_kind, &resolved_kind) ||
        !std::isfinite(raw_value) ||
        !std::isfinite(motion)) {
        return false;
    }

    const float resource_delta = ComputeLootOrbResourceDelta(resource_kind, raw_value);
    LootDropSnapshotPacketState built{};
    built.network_drop_id = network_drop_id;
    built.native_type_id = actor.object_type_id;
    built.drop_kind = static_cast<std::uint8_t>(LootDropKind::Orb);
    built.flags = lifetime != 0 && resource_delta > kLootPickupResourceEpsilon
                      ? LootDropSnapshotFlagActive
                      : 0;
    built.amount = RoundRewardAmountToInt(resource_delta);
    built.amount_tier = resource_kind;
    built.value = raw_value;
    built.actor_slot = actor.actor_slot;
    built.world_slot = actor.world_slot;
    built.lifetime = lifetime;
    built.position_x = actor.x;
    built.position_y = actor.y;
    built.radius = actor.radius;
    *snapshot = built;
    return true;
}

bool TryPopulateItemLootDropSnapshot(
    const SDModSceneActorState& actor,
    std::uint64_t network_drop_id,
    LootDropSnapshotPacketState* snapshot) {
    if (snapshot == nullptr ||
        network_drop_id == 0 ||
        !ShouldReplicateLootDropActor(actor, ParticipantSceneIntentKind::Run) ||
        actor.object_type_id != kItemDropNativeTypeId) {
        return false;
    }

    std::uint32_t item_type_id = 0;
    std::int32_t item_slot = -1;
    std::int32_t stack_count = 0;
    if (!TryReadItemDropHeldItemMetadata(
            actor.actor_address,
            &item_type_id,
            &item_slot,
            &stack_count)) {
        return false;
    }

    LootDropSnapshotPacketState built{};
    built.network_drop_id = network_drop_id;
    built.native_type_id = actor.object_type_id;
    built.drop_kind = static_cast<std::uint8_t>(
        item_type_id == kPotionItemTypeId ? LootDropKind::Potion : LootDropKind::Item);
    built.flags = LootDropSnapshotFlagActive;
    built.amount = stack_count;
    built.amount_tier = item_slot;
    built.value = 0.0f;
    built.item_type_id = item_type_id;
    built.item_slot = item_slot;
    built.stack_count = stack_count;
    built.actor_slot = actor.actor_slot;
    built.world_slot = actor.world_slot;
    built.lifetime = 0;
    built.position_x = actor.x;
    built.position_y = actor.y;
    built.radius = actor.radius;
    *snapshot = built;
    return true;
}

bool TryPopulateLootDropSnapshot(
    const SDModSceneActorState& actor,
    std::uint64_t network_drop_id,
    LootDropSnapshotPacketState* snapshot) {
    if (actor.object_type_id == kGoldRewardNativeTypeId) {
        return TryPopulateGoldLootDropSnapshot(actor, network_drop_id, snapshot);
    }
    if (actor.object_type_id == kOrbRewardNativeTypeId) {
        return TryPopulateOrbLootDropSnapshot(actor, network_drop_id, snapshot);
    }
    if (actor.object_type_id == kItemDropNativeTypeId) {
        return TryPopulateItemLootDropSnapshot(actor, network_drop_id, snapshot);
    }
    return false;
}

bool TryFindHostRunLootDropByNetworkId(
    std::uint64_t network_drop_id,
    SDModSceneActorState* actor_out,
    LootDropSnapshotPacketState* snapshot_out) {
    if (actor_out != nullptr) {
        *actor_out = {};
    }
    if (snapshot_out != nullptr) {
        *snapshot_out = {};
    }
    if (network_drop_id == 0 || !g_local_transport.is_host) {
        return false;
    }

    const auto scene_intent = SceneIntentFromLocalScene();
    if (scene_intent.kind != ParticipantSceneIntentKind::Run) {
        return false;
    }

    std::vector<SDModSceneActorState> actors;
    if (!TryListSceneActors(&actors)) {
        return false;
    }

    for (const auto& actor : actors) {
        if (!ShouldReplicateLootDropActor(actor, scene_intent.kind)) {
            continue;
        }

        const auto network_candidate = AllocateRunLootDropNetworkId(actor);
        if (network_candidate != network_drop_id) {
            continue;
        }

        LootDropSnapshotPacketState snapshot{};
        if (!TryPopulateLootDropSnapshot(actor, network_candidate, &snapshot)) {
            return false;
        }

        if (actor_out != nullptr) {
            *actor_out = actor;
        }
        if (snapshot_out != nullptr) {
            *snapshot_out = snapshot;
        }
        return true;
    }
    return false;
}

bool TryDeactivateHostGoldLootDrop(uintptr_t actor_address) {
    if (actor_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const std::uint8_t inactive = 0;
    const std::uint32_t zero_amount = 0;
    const std::uint32_t expired_lifetime = 0;
    (void)
        memory.TryWriteField(actor_address, kGoldRewardActiveOffset, inactive);
    const bool wrote_amount =
        memory.TryWriteField(actor_address, kGoldRewardAmountOffset, zero_amount);
    const bool wrote_lifetime =
        memory.TryWriteField(actor_address, kGoldRewardLifetimeOffset, expired_lifetime);
    return wrote_amount && wrote_lifetime;
}

bool TryDeactivateHostOrbLootDrop(uintptr_t actor_address) {
    if (actor_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const float zero_value = 0.0f;
    const std::uint32_t expired_lifetime = 0;
    const float settled_motion = 0.0f;
    const bool wrote_value =
        memory.TryWriteField(actor_address, kOrbRewardValueOffset, zero_value);
    const bool wrote_lifetime =
        memory.TryWriteField(actor_address, kOrbRewardLifetimeOffset, expired_lifetime);
    const bool wrote_motion =
        memory.TryWriteField(actor_address, kOrbRewardMotionOffset, settled_motion);
    return wrote_value && wrote_lifetime && wrote_motion;
}

bool TryDeactivateHostItemLootDrop(uintptr_t actor_address) {
    if (actor_address == 0 || kItemDropHeldItemOffset == 0) {
        return false;
    }

    const std::uint32_t no_held_item = 0;
    return ProcessMemory::Instance().TryWriteField(actor_address, kItemDropHeldItemOffset, no_held_item);
}

bool TryDeactivateHostLootDrop(uintptr_t actor_address, LootDropKind kind) {
    switch (kind) {
    case LootDropKind::Gold:
        return TryDeactivateHostGoldLootDrop(actor_address);
    case LootDropKind::Orb:
        return TryDeactivateHostOrbLootDrop(actor_address);
    case LootDropKind::Item:
    case LootDropKind::Potion:
        return TryDeactivateHostItemLootDrop(actor_address);
    default:
        return false;
    }
}

bool TryWriteLocalGlobalGold(std::int32_t gold) {
    const auto address = ProcessMemory::Instance().ResolveGameAddressOrZero(kGoldGlobal);
    return address != 0 && ProcessMemory::Instance().TryWriteValue(address, gold);
}

bool TryWriteLocalPlayerOrbResource(
    std::int32_t resource_kind_value,
    float life_current,
    float life_max,
    float mana_current,
    float mana_max) {
    SDModPlayerState player_state;
    if (!TryGetPlayerState(&player_state) ||
        !player_state.valid ||
        player_state.progression_address == 0 ||
        kProgressionHpOffset == 0 ||
        kProgressionMaxHpOffset == 0 ||
        kProgressionMpOffset == 0 ||
        kProgressionMaxMpOffset == 0 ||
        !std::isfinite(life_current) ||
        !std::isfinite(life_max) ||
        !std::isfinite(mana_current) ||
        !std::isfinite(mana_max)) {
        return false;
    }

    LootOrbResourceKind resource_kind = LootOrbResourceKind::Health;
    if (!TryResolveLootOrbResourceKind(resource_kind_value, &resource_kind)) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    if (resource_kind == LootOrbResourceKind::Health) {
        if (life_max <= 0.0f) {
            return false;
        }
        const float clamped_life = (std::clamp)(life_current, 0.0f, life_max);
        return memory.TryWriteField(player_state.progression_address, kProgressionMaxHpOffset, life_max) &&
               memory.TryWriteField(player_state.progression_address, kProgressionHpOffset, clamped_life);
    }

    if (mana_max <= 0.0f) {
        return false;
    }
    const float clamped_mana = (std::clamp)(mana_current, 0.0f, mana_max);
    return memory.TryWriteField(player_state.progression_address, kProgressionMaxMpOffset, mana_max) &&
           memory.TryWriteField(player_state.progression_address, kProgressionMpOffset, clamped_mana);
}

bool IsLootPickupRequestSequenceDuplicate(const LootPickupRequestPacket& packet) {
    const auto it =
        g_local_transport.last_loot_pickup_request_sequence_by_participant.find(packet.participant_id);
    if (it == g_local_transport.last_loot_pickup_request_sequence_by_participant.end() ||
        packet.request_sequence == 0) {
        return false;
    }
    return static_cast<std::int32_t>(packet.request_sequence - it->second) <= 0;
}

void RememberLootPickupRequestSequence(const LootPickupRequestPacket& packet) {
    if (packet.request_sequence != 0) {
        g_local_transport.last_loot_pickup_request_sequence_by_participant[packet.participant_id] =
            packet.request_sequence;
    }
}

bool TryApplyLivePlayerSelectionToProfile(
    const SDModGameplaySelectionDebugState& selection_state,
    MultiplayerCharacterProfile* profile) {
    if (profile == nullptr || !selection_state.valid) {
        return false;
    }

    const auto selected_primary_entry = selection_state.slot_selection_entries[0];
    int element_id = -1;
    switch (selected_primary_entry) {
    case 0x10:
        element_id = 0;
        break;
    case 0x20:
        element_id = 1;
        break;
    case 0x28:
        element_id = 2;
        break;
    case 0x18:
        element_id = 3;
        break;
    case 0x08:
        element_id = 4;
        break;
    default:
        break;
    }
    if (element_id < 0) {
        return false;
    }

    auto updated = *profile;
    updated.element_id = element_id;

    int resolved_primary_entry = -1;
    NativePrimarySpellSelection primary_selection;
    if (TryResolveNativePrimarySelectionFromPair(
            selected_primary_entry,
            selected_primary_entry,
            &primary_selection)) {
        resolved_primary_entry = selected_primary_entry;
    } else if (!TryResolveNativePrimaryEntryForElement(element_id, &resolved_primary_entry)) {
        return false;
    }

    updated.loadout.primary_entry_index = resolved_primary_entry;
    updated.loadout.primary_combo_entry_index = resolved_primary_entry;
    for (std::size_t index = 0; index < updated.loadout.secondary_entry_indices.size(); ++index) {
        const auto selection_index = index + 1;
        updated.loadout.secondary_entry_indices[index] =
            selection_index < 4 ? selection_state.slot_selection_entries[selection_index] : -1;
    }

    if (!IsValidCharacterProfile(updated)) {
        return false;
    }

    *profile = updated;
    return true;
}

std::vector<sockaddr_in> BuildKnownSendEndpoints() {
    std::vector<sockaddr_in> endpoints;
    if (g_local_transport.configured_remote_valid) {
        endpoints.push_back(g_local_transport.configured_remote);
    }
    for (const auto& peer : g_local_transport.peers) {
        const bool already_added = std::any_of(endpoints.begin(), endpoints.end(), [&](const sockaddr_in& existing) {
            return SameEndpoint(existing, peer.address);
        });
        if (!already_added) {
            endpoints.push_back(peer.address);
        }
    }
    return endpoints;
}

void RefreshLocalParticipantFromGameState() {
    SDModPlayerState player_state;
    if (!TryGetPlayerState(&player_state) || !player_state.valid) {
        return;
    }

    SDModGameplaySelectionDebugState selection_state;
    const bool have_selection_state =
        TryGetGameplaySelectionDebugState(&selection_state) && selection_state.valid;
    const auto scene_intent = SceneIntentFromLocalScene();
    const auto configured_name = ReadLocalDisplayName();
    SDModWorldState world_state;
    const bool have_world_state = TryGetWorldState(&world_state) && world_state.valid;
    SDModInventoryState inventory_state;
    const bool have_inventory_state =
        TryGetPlayerInventoryState(&inventory_state) && inventory_state.valid;
    SDModProgressionBookState progression_book_state;
    const bool have_progression_book_state =
        TryGetPlayerProgressionBookState(&progression_book_state) && progression_book_state.valid;
    UpdateRuntimeState([&](RuntimeState& state) {
        auto* local = UpsertLocalParticipant(state);
        if (local == nullptr) {
            return;
        }

        local->ready = true;
        if (!configured_name.empty()) {
            local->name = configured_name;
        }
        if (have_selection_state) {
            const auto previous_element_id = local->character_profile.element_id;
            const auto previous_primary_entry = local->character_profile.loadout.primary_entry_index;
            const auto previous_combo_entry = local->character_profile.loadout.primary_combo_entry_index;
            const auto previous_secondary_entries = local->character_profile.loadout.secondary_entry_indices;
            if (TryApplyLivePlayerSelectionToProfile(selection_state, &local->character_profile)) {
                local->character_profile.level = player_state.level;
                local->character_profile.experience = player_state.xp;
                if (local->character_profile.element_id != previous_element_id ||
                    local->character_profile.loadout.primary_entry_index != previous_primary_entry ||
                    local->character_profile.loadout.primary_combo_entry_index != previous_combo_entry ||
                    local->character_profile.loadout.secondary_entry_indices != previous_secondary_entries) {
                    Log(
                        "Multiplayer local character profile refreshed from live selection. element_id=" +
                        std::to_string(local->character_profile.element_id) +
                        " primary_entry=" +
                        std::to_string(local->character_profile.loadout.primary_entry_index) +
                        " combo_entry=" +
                        std::to_string(local->character_profile.loadout.primary_combo_entry_index));
                }
            }
        }
        local->transport_connected = true;
        local->transport_using_relay = false;
        local->runtime.valid = true;
        local->runtime.transform_valid = true;
        local->runtime.in_run = scene_intent.kind == ParticipantSceneIntentKind::Run;
        local->runtime.scene_intent = scene_intent;
        local->runtime.life_current = player_state.hp;
        local->runtime.life_max = player_state.max_hp;
        local->runtime.mana_current = player_state.mp;
        local->runtime.mana_max = player_state.max_mp;
        local->runtime.level = player_state.level;
        local->runtime.experience_current = player_state.xp;
        local->runtime.primary_entry_index = local->character_profile.loadout.primary_entry_index;
        local->runtime.primary_combo_entry_index = local->character_profile.loadout.primary_combo_entry_index;
        local->runtime.queued_secondary_entry_indices = local->character_profile.loadout.secondary_entry_indices;
        const auto previous_owned_gold = local->owned_progression.gold;
        const bool previous_owned_progression_initialized = local->owned_progression.initialized;
        local->owned_progression.initialized = true;
        local->owned_progression.gold = player_state.gold;
        if (previous_owned_progression_initialized && previous_owned_gold != player_state.gold) {
            local->owned_progression.gold_revision += 1;
        }
        if (scene_intent.kind != ParticipantSceneIntentKind::Run) {
            local->owned_progression.inventory_host_authoritative = false;
        }
        if (have_inventory_state && !local->owned_progression.inventory_host_authoritative) {
            RefreshOwnedInventoryFromSnapshot(inventory_state, &local->owned_progression);
        }
        if (have_progression_book_state) {
            RefreshOwnedProgressionBookFromSnapshot(progression_book_state, &local->owned_progression);
        }
        RefreshOwnedAbilityLoadoutFromProfile(local->character_profile.loadout, &local->owned_progression);
        if (have_world_state) {
            local->runtime.wave = world_state.wave;
        }
        local->runtime.position_x = player_state.x;
        local->runtime.position_y = player_state.y;
        local->runtime.heading = player_state.heading;
        local->runtime.anim_drive_state = player_state.anim_drive_state;
        local->runtime.presentation_flags =
            ParticipantPresentationFlagAnimationDriveWord |
            ParticipantPresentationFlagRenderDriveFloats;
        // The staff attachment tail field at +0x84 is native-owned and can hold
        // process-local/pointer-like data in run scenes. Do not mirror it across
        // clients; remote cast playback and local materialization own staff glow.
        local->runtime.attachment_staff_visual_state = 0;
        if (kActorRenderVariantPrimaryOffset != 0 &&
            kActorRenderVariantSecondaryOffset != 0 &&
            kActorRenderWeaponTypeOffset != 0 &&
            kActorRenderSelectionByteOffset != 0 &&
            kActorRenderVariantTertiaryOffset != 0) {
            local->runtime.presentation_flags |= ParticipantPresentationFlagRenderSelectorBytes;
            local->runtime.render_variant_primary = player_state.render_variant_primary;
            local->runtime.render_variant_secondary = player_state.render_variant_secondary;
            local->runtime.render_weapon_type = player_state.render_weapon_type;
            local->runtime.render_selection_byte = player_state.render_selection_byte;
            local->runtime.render_variant_tertiary = player_state.render_variant_tertiary;
        } else {
            local->runtime.render_variant_primary = 0;
            local->runtime.render_variant_secondary = 0;
            local->runtime.render_weapon_type = 0;
            local->runtime.render_selection_byte = 0;
            local->runtime.render_variant_tertiary = 0;
        }
        std::uint32_t primary_visual_type = 0;
        std::uint32_t secondary_visual_type = 0;
        std::array<std::uint8_t, kParticipantVisualLinkColorBlockBytes> primary_visual_block = {};
        std::array<std::uint8_t, kParticipantVisualLinkColorBlockBytes> secondary_visual_block = {};
        if (TryReadVisualLinkColorBlock(
                player_state.primary_visual_lane,
                &primary_visual_type,
                &primary_visual_block) &&
            TryReadVisualLinkColorBlock(
                player_state.secondary_visual_lane,
                &secondary_visual_type,
                &secondary_visual_block)) {
            local->runtime.presentation_flags |= ParticipantPresentationFlagVisualLinkColorBlocks;
            local->runtime.primary_visual_link_type_id = primary_visual_type;
            local->runtime.secondary_visual_link_type_id = secondary_visual_type;
            local->runtime.primary_visual_link_color_block = primary_visual_block;
            local->runtime.secondary_visual_link_color_block = secondary_visual_block;
        } else {
            local->runtime.primary_visual_link_type_id = 0;
            local->runtime.secondary_visual_link_type_id = 0;
            local->runtime.primary_visual_link_color_block = {};
            local->runtime.secondary_visual_link_color_block = {};
        }
        local->runtime.anim_drive_state_word = player_state.anim_drive_state_word;
        local->runtime.walk_cycle_primary = player_state.walk_cycle_primary;
        local->runtime.walk_cycle_secondary = player_state.walk_cycle_secondary;
        local->runtime.render_drive_stride = player_state.render_drive_stride;
        local->runtime.render_advance_rate = player_state.render_advance_rate;
        local->runtime.render_advance_phase = player_state.render_advance_phase;
        const auto effect_state = NormalizeRenderDriveEffectState(
            player_state.render_drive_effect_timer,
            player_state.render_drive_effect_progress);
        local->runtime.render_drive_effect_timer = effect_state.timer;
        local->runtime.render_drive_effect_progress = effect_state.progress;
        local->runtime.render_drive_overlay_alpha = player_state.render_drive_overlay_alpha;
        local->runtime.render_drive_move_blend = player_state.render_drive_move_blend;
    });
}

StatePacket BuildLocalStatePacket() {
    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);

    StatePacket packet{};
    packet.header = MakePacketHeader(PacketKind::State, g_local_transport.next_sequence++);
    packet.participant_id = g_local_transport.local_peer_id;
    if (local == nullptr) {
        return packet;
    }

    CopyPacketDisplayName(local->name, &packet);
    packet.ready = local->ready ? 1 : 0;
    packet.in_run = local->runtime.in_run ? 1 : 0;
    packet.transform_valid = local->runtime.transform_valid ? 1 : 0;
    packet.controller_kind = static_cast<std::uint8_t>(ParticipantControllerKind::Native);
    packet.run_nonce = local->runtime.run_nonce;
    packet.element_id = local->character_profile.element_id;
    packet.discipline_id = static_cast<std::int32_t>(local->character_profile.discipline_id);
    for (std::size_t index = 0; index < local->character_profile.appearance.choice_ids.size(); ++index) {
        packet.appearance_choice_ids[index] = local->character_profile.appearance.choice_ids[index];
    }
    packet.level = local->runtime.level;
    packet.wave = local->runtime.wave;
    packet.life_current = local->runtime.life_current;
    packet.life_max = local->runtime.life_max;
    packet.mana_current = local->runtime.mana_current;
    packet.mana_max = local->runtime.mana_max;
    packet.experience_current = local->runtime.experience_current;
    packet.experience_next = local->runtime.experience_next;
    packet.owned_gold = local->owned_progression.gold;
    packet.gold_revision = local->owned_progression.gold_revision;
    packet.inventory_revision = local->owned_progression.inventory_revision;
    packet.spellbook_revision = local->owned_progression.spellbook_revision;
    packet.statbook_revision = local->owned_progression.statbook_revision;
    packet.loadout_revision = local->owned_progression.loadout_revision;
    const auto inventory_packet_count =
        (std::min)(
            local->owned_progression.inventory_items.size(),
            static_cast<std::size_t>(kParticipantInventorySnapshotMaxItems));
    packet.inventory_item_count = static_cast<std::uint16_t>(inventory_packet_count);
    packet.inventory_item_total_count = local->owned_progression.inventory_item_total_count;
    packet.inventory_snapshot_flags =
        local->owned_progression.inventory_truncated ||
            local->owned_progression.inventory_items.size() > kParticipantInventorySnapshotMaxItems
            ? ParticipantInventorySnapshotFlagTruncated
            : 0;
    for (std::size_t index = 0; index < inventory_packet_count; ++index) {
        const auto& item = local->owned_progression.inventory_items[index];
        packet.inventory_items[index].type_id = item.type_id;
        packet.inventory_items[index].slot = item.slot;
        packet.inventory_items[index].stack_count = item.stack_count;
    }
    const auto progression_book_packet_count =
        (std::min)(
            local->owned_progression.progression_book_entries.size(),
            static_cast<std::size_t>(kParticipantProgressionBookSnapshotMaxEntries));
    packet.progression_book_entry_count = static_cast<std::uint16_t>(progression_book_packet_count);
    packet.progression_book_entry_total_count =
        local->owned_progression.progression_book_entry_total_count;
    packet.progression_book_snapshot_flags =
        local->owned_progression.progression_book_truncated ||
            local->owned_progression.progression_book_entries.size() >
                kParticipantProgressionBookSnapshotMaxEntries
            ? ParticipantProgressionBookSnapshotFlagTruncated
            : 0;
    for (std::size_t index = 0; index < progression_book_packet_count; ++index) {
        const auto& entry = local->owned_progression.progression_book_entries[index];
        packet.progression_book_entries[index].entry_index = entry.entry_index;
        packet.progression_book_entries[index].internal_id = entry.internal_id;
        packet.progression_book_entries[index].active = entry.active;
        packet.progression_book_entries[index].visible = entry.visible;
        packet.progression_book_entries[index].category = entry.category;
        packet.progression_book_entries[index].statbook_max_level = entry.statbook_max_level;
    }
    packet.primary_entry_index = local->character_profile.loadout.primary_entry_index;
    packet.primary_combo_entry_index = local->character_profile.loadout.primary_combo_entry_index;
    for (std::size_t index = 0; index < local->character_profile.loadout.secondary_entry_indices.size(); ++index) {
        packet.queued_secondary_entry_indices[index] =
            local->character_profile.loadout.secondary_entry_indices[index];
    }
    packet.position_x = local->runtime.position_x;
    packet.position_y = local->runtime.position_y;
    packet.heading = local->runtime.heading;
    packet.anim_drive_state = local->runtime.anim_drive_state;
    packet.presentation_flags = local->runtime.presentation_flags;
    packet.attachment_staff_visual_state = local->runtime.attachment_staff_visual_state;
    packet.render_variant_primary = local->runtime.render_variant_primary;
    packet.render_variant_secondary = local->runtime.render_variant_secondary;
    packet.render_weapon_type = local->runtime.render_weapon_type;
    packet.render_selection_byte = local->runtime.render_selection_byte;
    packet.render_variant_tertiary = local->runtime.render_variant_tertiary;
    packet.primary_visual_link_type_id = local->runtime.primary_visual_link_type_id;
    packet.secondary_visual_link_type_id = local->runtime.secondary_visual_link_type_id;
    std::memcpy(
        packet.primary_visual_link_color_block,
        local->runtime.primary_visual_link_color_block.data(),
        local->runtime.primary_visual_link_color_block.size());
    std::memcpy(
        packet.secondary_visual_link_color_block,
        local->runtime.secondary_visual_link_color_block.data(),
        local->runtime.secondary_visual_link_color_block.size());
    packet.anim_drive_state_word = local->runtime.anim_drive_state_word;
    packet.walk_cycle_primary = local->runtime.walk_cycle_primary;
    packet.walk_cycle_secondary = local->runtime.walk_cycle_secondary;
    packet.render_drive_stride = local->runtime.render_drive_stride;
    packet.render_advance_rate = local->runtime.render_advance_rate;
    packet.render_advance_phase = local->runtime.render_advance_phase;
    packet.render_drive_effect_timer = local->runtime.render_drive_effect_timer;
    packet.render_drive_effect_progress = local->runtime.render_drive_effect_progress;
    packet.render_drive_overlay_alpha = local->runtime.render_drive_overlay_alpha;
    packet.render_drive_move_blend = local->runtime.render_drive_move_blend;
    return packet;
}

bool BuildLocalWorldSnapshotPacket(WorldSnapshotPacket* packet) {
    if (packet == nullptr || !g_local_transport.is_host) {
        return false;
    }

    SDModSceneState scene_state;
    if (!TryGetSceneState(&scene_state) || !scene_state.valid) {
        return false;
    }

    std::vector<SDModSceneActorState> actors;
    if (!TryListSceneActors(&actors)) {
        return false;
    }

    const auto scene_intent = SceneIntentFromLocalScene();
    if (scene_intent.kind != ParticipantSceneIntentKind::SharedHub &&
        scene_intent.kind != ParticipantSceneIntentKind::Run) {
        return false;
    }

    RefreshWorldSceneTracking(scene_state);
    PruneHubWorldActorNetworkIds(actors, scene_intent.kind);
    PruneRunHostLocalWorldActorNetworkIds(actors, scene_intent.kind);

    WorldSnapshotPacket built{};
    built.header = MakePacketHeader(PacketKind::WorldSnapshot, g_local_transport.next_sequence++);
    built.authority_participant_id = g_local_transport.local_peer_id;
    built.scene_epoch = g_local_transport.world_scene_epoch;
    built.scene_kind = static_cast<std::uint8_t>(WorldSceneKindFromSceneIntent(scene_intent));

    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);
    if (local != nullptr) {
        built.run_nonce = local->runtime.run_nonce;
    }

    const bool run_scene = scene_intent.kind == ParticipantSceneIntentKind::Run;
    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    if (run_scene) {
        PruneRecentRunEnemyDeathSnapshots(now_ms);
    }
    std::unordered_set<std::uint64_t> included_actor_ids;
    std::uint32_t total_actor_count = 0;
    for (const auto& actor : actors) {
        if (!ShouldReplicateWorldActor(actor, scene_intent.kind)) {
            continue;
        }
        std::uint64_t network_actor_id = 0;
        if (run_scene) {
            std::uint32_t spawn_serial = 0;
            if (TryGetRunLifecycleEnemySpawnSerial(actor.actor_address, &spawn_serial)) {
                g_local_transport.run_host_local_world_actor_ids_by_address.erase(actor.actor_address);
                network_actor_id = BuildRunWorldActorNetworkId(spawn_serial);
            } else {
                network_actor_id = AllocateRunHostLocalWorldActorNetworkId(actor);
            }
        } else {
            network_actor_id = AllocateHubWorldActorNetworkId(actor);
        }
        if (network_actor_id == 0) {
            continue;
        }
        included_actor_ids.insert(network_actor_id);
        total_actor_count += 1;
        if (built.actor_count >= kWorldSnapshotMaxActors) {
            continue;
        }

        auto& snapshot = built.actors[built.actor_count];
        snapshot.network_actor_id = network_actor_id;
        snapshot.native_type_id = actor.object_type_id;
        snapshot.enemy_type = actor.enemy_type;
        snapshot.actor_slot = actor.actor_slot;
        snapshot.world_slot = actor.world_slot;
        snapshot.anim_drive_state = actor.anim_drive_state;
        snapshot.position_x = actor.x;
        snapshot.position_y = actor.y;
        snapshot.radius = actor.radius;
        snapshot.heading = ReadActorHeadingOrZero(actor.actor_address);
        snapshot.hp = std::isfinite(actor.hp) ? actor.hp : 0.0f;
        snapshot.max_hp = std::isfinite(actor.max_hp) ? actor.max_hp : 0.0f;
        PopulateWorldActorPresentationSnapshot(
            actor.actor_address,
            actor.object_type_id,
            scene_intent.kind,
            actor.tracked_enemy,
            &snapshot);
        if (actor.dead) {
            snapshot.flags |= WorldActorSnapshotFlagDead;
        }
        if (actor.tracked_enemy) {
            snapshot.flags |= WorldActorSnapshotFlagTrackedEnemy;
        }
        if (run_scene && IsRunStaticLayoutActor(actor)) {
            snapshot.flags |= WorldActorSnapshotFlagRunStatic;
        }
        if (run_scene) {
            snapshot.flags |= WorldActorSnapshotFlagLifecycleOwned;
        }
        built.actor_count += 1;
    }
    if (run_scene) {
        for (const auto& [network_actor_id, death_snapshot] :
             g_local_transport.recent_run_enemy_deaths_by_network_id) {
            if (network_actor_id == 0 ||
                included_actor_ids.find(network_actor_id) != included_actor_ids.end() ||
                death_snapshot.native_type_id == 0 ||
                !std::isfinite(death_snapshot.max_hp) ||
                death_snapshot.max_hp <= 0.0f) {
                continue;
            }
            total_actor_count += 1;
            if (built.actor_count >= kWorldSnapshotMaxActors) {
                continue;
            }

            auto& snapshot = built.actors[built.actor_count];
            snapshot.network_actor_id = network_actor_id;
            snapshot.native_type_id = death_snapshot.native_type_id;
            snapshot.enemy_type = death_snapshot.enemy_type;
            snapshot.actor_slot = -1;
            snapshot.world_slot = -1;
            snapshot.flags =
                WorldActorSnapshotFlagDead |
                WorldActorSnapshotFlagTrackedEnemy |
                WorldActorSnapshotFlagLifecycleOwned;
            snapshot.position_x = death_snapshot.position_x;
            snapshot.position_y = death_snapshot.position_y;
            snapshot.radius = death_snapshot.radius;
            snapshot.heading = death_snapshot.heading;
            snapshot.hp = 0.0f;
            snapshot.max_hp = death_snapshot.max_hp;
            built.actor_count += 1;
        }
    }
    built.actor_total_count = static_cast<std::uint8_t>((std::min<std::uint32_t>)(total_actor_count, 0xFFu));
    if (total_actor_count > built.actor_count) {
        built.snapshot_flags |= WorldSnapshotFlagTruncated;
    }

    *packet = built;
    return true;
}

bool BuildLocalLootSnapshotPacket(LootSnapshotPacket* packet) {
    if (packet == nullptr || !g_local_transport.is_host) {
        return false;
    }

    SDModSceneState scene_state;
    if (!TryGetSceneState(&scene_state) || !scene_state.valid) {
        return false;
    }

    std::vector<SDModSceneActorState> actors;
    if (!TryListSceneActors(&actors)) {
        return false;
    }

    const auto scene_intent = SceneIntentFromLocalScene();
    if (scene_intent.kind != ParticipantSceneIntentKind::Run) {
        PruneRunLootDropNetworkIds(actors, scene_intent.kind);
        return false;
    }

    RefreshWorldSceneTracking(scene_state);
    PruneRunLootDropNetworkIds(actors, scene_intent.kind);

    LootSnapshotPacket built{};
    built.header = MakePacketHeader(PacketKind::LootSnapshot, g_local_transport.next_sequence++);
    built.authority_participant_id = g_local_transport.local_peer_id;
    built.scene_epoch = g_local_transport.world_scene_epoch;
    built.scene_kind = static_cast<std::uint8_t>(WorldSceneKindFromSceneIntent(scene_intent));

    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);
    if (local != nullptr) {
        built.run_nonce = local->runtime.run_nonce;
    }

    std::uint32_t total_drop_count = 0;
    for (const auto& actor : actors) {
        if (!ShouldReplicateLootDropActor(actor, scene_intent.kind)) {
            continue;
        }

        const auto network_drop_id = AllocateRunLootDropNetworkId(actor);
        if (network_drop_id == 0) {
            continue;
        }
        if (g_local_transport.accepted_loot_pickup_drop_ids.find(network_drop_id) !=
            g_local_transport.accepted_loot_pickup_drop_ids.end()) {
            continue;
        }

        LootDropSnapshotPacketState snapshot{};
        if (!TryPopulateLootDropSnapshot(actor, network_drop_id, &snapshot)) {
            continue;
        }

        total_drop_count += 1;
        if (built.drop_count >= kLootSnapshotMaxDrops) {
            continue;
        }

        built.drops[built.drop_count] = snapshot;
        built.drop_count += 1;
    }

    built.drop_total_count = static_cast<std::uint8_t>((std::min<std::uint32_t>)(total_drop_count, 0xFFu));
    if (total_drop_count > built.drop_count) {
        built.snapshot_flags |= LootSnapshotFlagTruncated;
    }

    *packet = built;
    return true;
}

float ClampEnemyHp(float hp, float max_hp) {
    if (!std::isfinite(hp)) {
        return 0.0f;
    }
    if (hp < 0.0f) {
        return 0.0f;
    }
    if (std::isfinite(max_hp) && max_hp > 0.0f && hp > max_hp) {
        return max_hp;
    }
    return hp;
}

float DistanceSquared(float ax, float ay, float bx, float by) {
    const float dx = ax - bx;
    const float dy = ay - by;
    return dx * dx + dy * dy;
}

uintptr_t ReadTransportSmartPointerInnerObject(uintptr_t wrapper_address) {
    if (wrapper_address == 0) {
        return 0;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t direct_inner = 0;
    if (!memory.TryReadValue(wrapper_address, &direct_inner)) {
        return 0;
    }
    if (direct_inner != 0 && memory.IsReadableRange(direct_inner, 1)) {
        return direct_inner;
    }

    uintptr_t gameplay_inner = 0;
    if (!memory.TryReadValue(wrapper_address + 0x0C, &gameplay_inner)) {
        return 0;
    }
    if (gameplay_inner != 0 && memory.IsReadableRange(gameplay_inner, 1)) {
        return gameplay_inner;
    }

    return 0;
}

uintptr_t ResolveActorProgressionRuntimeForTransport(uintptr_t actor_address) {
    if (actor_address == 0) {
        return 0;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t progression_runtime = 0;
    if (memory.TryReadField(
            actor_address,
            kActorProgressionRuntimeStateOffset,
            &progression_runtime) &&
        progression_runtime != 0 &&
        memory.IsReadableRange(progression_runtime, 1)) {
        return progression_runtime;
    }

    uintptr_t progression_handle = 0;
    if (!memory.TryReadField(actor_address, kActorProgressionHandleOffset, &progression_handle)) {
        return 0;
    }
    return ReadTransportSmartPointerInnerObject(progression_handle);
}

bool TryWriteRunEnemyHealth(uintptr_t actor_address, float hp, float max_hp) {
    if (actor_address == 0 ||
        kEnemyCurrentHpOffset == 0 ||
        kEnemyMaxHpOffset == 0 ||
        !std::isfinite(max_hp) ||
        max_hp <= 0.0f) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const float clamped_hp = ClampEnemyHp(hp, max_hp);
    const bool wrote_enemy_fields =
        memory.TryWriteField(actor_address, kEnemyMaxHpOffset, max_hp) &&
        memory.TryWriteField(actor_address, kEnemyCurrentHpOffset, clamped_hp);

    bool wrote_progression_fields = false;
    const auto progression_runtime = ResolveActorProgressionRuntimeForTransport(actor_address);
    if (progression_runtime != 0 &&
        memory.IsReadableRange(progression_runtime + kProgressionHpOffset, sizeof(float)) &&
        memory.IsReadableRange(progression_runtime + kProgressionMaxHpOffset, sizeof(float))) {
        wrote_progression_fields =
            memory.TryWriteField(progression_runtime, kProgressionMaxHpOffset, max_hp) &&
            memory.TryWriteField(progression_runtime, kProgressionHpOffset, clamped_hp);
    }

    return wrote_enemy_fields || wrote_progression_fields;
}

bool TryFindHostRunEnemyByNetworkId(
    std::uint64_t network_actor_id,
    SDModSceneActorState* actor_out) {
    if (actor_out != nullptr) {
        *actor_out = {};
    }
    if (network_actor_id == 0 || !g_local_transport.is_host) {
        return false;
    }

    const auto scene_intent = SceneIntentFromLocalScene();
    if (scene_intent.kind != ParticipantSceneIntentKind::Run) {
        return false;
    }

    std::vector<SDModSceneActorState> actors;
    if (!TryListSceneActors(&actors)) {
        return false;
    }

    for (const auto& actor : actors) {
        if (!ShouldReplicateWorldActor(actor, scene_intent.kind) ||
            !actor.tracked_enemy) {
            continue;
        }

        std::uint64_t candidate_id = 0;
        std::uint32_t spawn_serial = 0;
        if (TryGetRunLifecycleEnemySpawnSerial(actor.actor_address, &spawn_serial)) {
            candidate_id = BuildRunWorldActorNetworkId(spawn_serial);
        } else {
            const auto existing =
                g_local_transport.run_host_local_world_actor_ids_by_address.find(actor.actor_address);
            candidate_id = existing != g_local_transport.run_host_local_world_actor_ids_by_address.end()
                               ? existing->second
                               : AllocateRunHostLocalWorldActorNetworkId(actor);
        }

        if (candidate_id == network_actor_id) {
            if (actor_out != nullptr) {
                *actor_out = actor;
            }
            return true;
        }
    }
    return false;
}

const WorldActorSnapshot* FindSnapshotActorByNetworkId(
    const WorldSnapshotRuntimeInfo& snapshot,
    std::uint64_t network_actor_id) {
    for (const auto& actor : snapshot.actors) {
        if (actor.network_actor_id == network_actor_id) {
            return &actor;
        }
    }
    return nullptr;
}

uintptr_t FindReplicatedLocalActorAddress(std::uint64_t network_actor_id) {
    const auto runtime_state = SnapshotRuntimeState();
    for (const auto& binding : runtime_state.world_snapshot_apply.actor_bindings) {
        if (binding.network_actor_id == network_actor_id &&
            binding.local_actor_address != 0 &&
            binding.matched &&
            !binding.parked &&
            !binding.removed) {
            return binding.local_actor_address;
        }
    }
    return 0;
}

std::uint64_t FindReplicatedLocalNetworkActorId(uintptr_t actor_address) {
    if (actor_address == 0) {
        return 0;
    }

    const auto runtime_state = SnapshotRuntimeState();
    for (const auto& binding : runtime_state.world_snapshot_apply.actor_bindings) {
        if (binding.local_actor_address == actor_address &&
            binding.network_actor_id != 0 &&
            binding.matched &&
            !binding.parked &&
            !binding.removed) {
            return binding.network_actor_id;
        }
    }
    return 0;
}

bool TryGetLiveRunEnemyActorByAddress(
    uintptr_t actor_address,
    SDModSceneActorState* actor_out) {
    if (actor_out != nullptr) {
        *actor_out = {};
    }
    if (actor_address == 0) {
        return false;
    }

    const auto scene_intent = SceneIntentFromLocalScene();
    if (scene_intent.kind != ParticipantSceneIntentKind::Run) {
        return false;
    }

    std::vector<SDModSceneActorState> actors;
    if (!TryListSceneActors(&actors)) {
        return false;
    }

    for (const auto& actor : actors) {
        if (actor.actor_address == actor_address &&
            ShouldReplicateWorldActor(actor, scene_intent.kind) &&
            actor.tracked_enemy) {
            if (actor_out != nullptr) {
                *actor_out = actor;
            }
            return true;
        }
    }
    return false;
}

std::uint64_t ResolveLocalRunEnemyNetworkActorId(const SDModSceneActorState& actor) {
    if (!actor.tracked_enemy || actor.actor_address == 0) {
        return 0;
    }

    if (g_local_transport.is_host) {
        std::uint32_t spawn_serial = 0;
        if (TryGetRunLifecycleEnemySpawnSerial(actor.actor_address, &spawn_serial)) {
            return BuildRunWorldActorNetworkId(spawn_serial);
        }

        const auto existing =
            g_local_transport.run_host_local_world_actor_ids_by_address.find(actor.actor_address);
        return existing != g_local_transport.run_host_local_world_actor_ids_by_address.end()
                   ? existing->second
                   : AllocateRunHostLocalWorldActorNetworkId(actor);
    }

    return FindReplicatedLocalNetworkActorId(actor.actor_address);
}

std::uint64_t ResolveLocalRunEnemyNetworkActorId(uintptr_t actor_address) {
    SDModSceneActorState actor;
    if (!TryGetLiveRunEnemyActorByAddress(actor_address, &actor)) {
        return 0;
    }
    return ResolveLocalRunEnemyNetworkActorId(actor);
}

bool TryFindLocalRunEnemyByNetworkId(
    std::uint64_t network_actor_id,
    SDModSceneActorState* actor_out) {
    if (actor_out != nullptr) {
        *actor_out = {};
    }
    if (network_actor_id == 0) {
        return false;
    }

    if (g_local_transport.is_host) {
        return TryFindHostRunEnemyByNetworkId(network_actor_id, actor_out);
    }

    return TryGetLiveRunEnemyActorByAddress(
        FindReplicatedLocalActorAddress(network_actor_id),
        actor_out);
}

bool TryNormalizeCastDirection(
    float direction_x,
    float direction_y,
    float position_x,
    float position_y,
    float aim_target_x,
    float aim_target_y,
    float* normalized_x,
    float* normalized_y,
    float* aim_distance) {
    if (normalized_x == nullptr || normalized_y == nullptr || aim_distance == nullptr) {
        return false;
    }

    float dx = direction_x;
    float dy = direction_y;
    float length = std::sqrt((dx * dx) + (dy * dy));
    if (!std::isfinite(length) || length <= 0.0001f) {
        dx = aim_target_x - position_x;
        dy = aim_target_y - position_y;
        length = std::sqrt((dx * dx) + (dy * dy));
    }
    if (!std::isfinite(length) || length <= 0.0001f) {
        return false;
    }

    *normalized_x = dx / length;
    *normalized_y = dy / length;
    const float aim_dx = aim_target_x - position_x;
    const float aim_dy = aim_target_y - position_y;
    const float raw_aim_distance = std::sqrt((aim_dx * aim_dx) + (aim_dy * aim_dy));
    *aim_distance =
        std::isfinite(raw_aim_distance) && raw_aim_distance > 0.0001f
            ? raw_aim_distance
            : length;
    return std::isfinite(*normalized_x) &&
           std::isfinite(*normalized_y) &&
           std::isfinite(*aim_distance);
}

bool IsUsableLocalCastAimTarget(
    float position_x,
    float position_y,
    float aim_target_x,
    float aim_target_y) {
    if (!std::isfinite(position_x) ||
        !std::isfinite(position_y) ||
        !std::isfinite(aim_target_x) ||
        !std::isfinite(aim_target_y)) {
        return false;
    }
    if (std::abs(aim_target_x) < 0.001f && std::abs(aim_target_y) < 0.001f) {
        return false;
    }

    const auto dx = aim_target_x - position_x;
    const auto dy = aim_target_y - position_y;
    const auto distance = std::sqrt((dx * dx) + (dy * dy));
    constexpr float kMinCastAimDistance = 1.0f;
    constexpr float kMaxCastAimDistance = 4096.0f;
    constexpr float kMaxCastAimCoordinateMagnitude = 20000.0f;
    return std::isfinite(distance) &&
           distance >= kMinCastAimDistance &&
           distance <= kMaxCastAimDistance &&
           std::abs(aim_target_x) <= kMaxCastAimCoordinateMagnitude &&
           std::abs(aim_target_y) <= kMaxCastAimCoordinateMagnitude;
}

bool TryFindLocalRunEnemyForCastAim(
    float position_x,
    float position_y,
    float direction_x,
    float direction_y,
    float aim_target_x,
    float aim_target_y,
    SDModSceneActorState* actor_out) {
    if (actor_out != nullptr) {
        *actor_out = {};
    }
    if (!std::isfinite(position_x) ||
        !std::isfinite(position_y) ||
        !std::isfinite(aim_target_x) ||
        !std::isfinite(aim_target_y)) {
        return false;
    }

    const auto scene_intent = SceneIntentFromLocalScene();
    if (scene_intent.kind != ParticipantSceneIntentKind::Run) {
        return false;
    }

    float normalized_x = 0.0f;
    float normalized_y = 0.0f;
    float aim_distance = 0.0f;
    if (!TryNormalizeCastDirection(
            direction_x,
            direction_y,
            position_x,
            position_y,
            aim_target_x,
            aim_target_y,
            &normalized_x,
            &normalized_y,
            &aim_distance)) {
        return false;
    }

    std::vector<SDModSceneActorState> actors;
    if (!TryListSceneActors(&actors)) {
        return false;
    }

    constexpr float kCastAimBackwardTolerance = 96.0f;
    constexpr float kCastAimForwardTolerance = 512.0f;
    constexpr float kCastAimMaxPerpendicular = 256.0f;
    float best_score = (std::numeric_limits<float>::max)();
    SDModSceneActorState best_actor{};
    bool have_best = false;
    for (const auto& actor : actors) {
        if (!ShouldReplicateWorldActor(actor, scene_intent.kind) ||
            !actor.tracked_enemy) {
            continue;
        }

        const float dx = actor.x - position_x;
        const float dy = actor.y - position_y;
        const float forward = (dx * normalized_x) + (dy * normalized_y);
        const float max_forward = (std::max)(aim_distance + kCastAimForwardTolerance, 768.0f);
        if (!std::isfinite(forward) ||
            forward < -kCastAimBackwardTolerance ||
            forward > max_forward) {
            continue;
        }

        const float distance_sq = (dx * dx) + (dy * dy);
        const float perpendicular_sq = (std::max)(0.0f, distance_sq - (forward * forward));
        const float max_perpendicular =
            (std::max)(kCastAimMaxPerpendicular, actor.radius + 192.0f);
        if (!std::isfinite(perpendicular_sq) ||
            perpendicular_sq > max_perpendicular * max_perpendicular) {
            continue;
        }

        const float aim_delta = forward - aim_distance;
        const float score = perpendicular_sq + (aim_delta * aim_delta * 0.05f);
        if (score < best_score) {
            best_score = score;
            best_actor = actor;
            have_best = true;
        }
    }

    if (!have_best) {
        return false;
    }
    if (actor_out != nullptr) {
        *actor_out = best_actor;
    }
    return true;
}

bool IsRunEnemyAlignedWithPlayerCastAim(
    const SDModSceneActorState& actor,
    float position_x,
    float position_y,
    float direction_x,
    float direction_y,
    float aim_target_x,
    float aim_target_y) {
    if (!actor.tracked_enemy ||
        actor.dead ||
        !std::isfinite(actor.x) ||
        !std::isfinite(actor.y) ||
        !std::isfinite(actor.radius) ||
        !std::isfinite(position_x) ||
        !std::isfinite(position_y) ||
        !std::isfinite(aim_target_x) ||
        !std::isfinite(aim_target_y)) {
        return false;
    }

    float normalized_x = 0.0f;
    float normalized_y = 0.0f;
    float aim_distance = 0.0f;
    if (!TryNormalizeCastDirection(
            direction_x,
            direction_y,
            position_x,
            position_y,
            aim_target_x,
            aim_target_y,
            &normalized_x,
            &normalized_y,
            &aim_distance)) {
        return false;
    }

    const float dx = actor.x - position_x;
    const float dy = actor.y - position_y;
    const float forward = (dx * normalized_x) + (dy * normalized_y);
    if (!std::isfinite(forward) || forward < -16.0f) {
        return false;
    }

    const float distance_sq = (dx * dx) + (dy * dy);
    const float perpendicular_sq = (std::max)(0.0f, distance_sq - (forward * forward));
    const float max_perpendicular = (std::max)(actor.radius + 72.0f, 96.0f);
    if (!std::isfinite(perpendicular_sq) ||
        perpendicular_sq > max_perpendicular * max_perpendicular) {
        return false;
    }

    const float max_forward = (std::max)(aim_distance + 160.0f, 640.0f);
    return std::isfinite(max_forward) && forward <= max_forward;
}

bool IsSaneExplicitCastTarget(
    const SDModSceneActorState& actor,
    float position_x,
    float position_y) {
    if (!actor.tracked_enemy ||
        actor.dead ||
        !std::isfinite(actor.x) ||
        !std::isfinite(actor.y) ||
        !std::isfinite(actor.hp) ||
        !std::isfinite(actor.max_hp) ||
        !std::isfinite(position_x) ||
        !std::isfinite(position_y) ||
        actor.max_hp <= 0.0f ||
        actor.hp <= kEnemyDamageClaimHpEpsilon) {
        return false;
    }

    constexpr float kMaxExplicitCastTargetDistance = 4096.0f;
    const auto dx = actor.x - position_x;
    const auto dy = actor.y - position_y;
    const auto distance = std::sqrt((dx * dx) + (dy * dy));
    return std::isfinite(distance) && distance <= kMaxExplicitCastTargetDistance;
}

bool TryResolveExplicitCastTargetNetworkActorId(
    uintptr_t target_actor_address,
    float position_x,
    float position_y,
    std::uint64_t* network_actor_id_out) {
    if (network_actor_id_out != nullptr) {
        *network_actor_id_out = 0;
    }

    SDModSceneActorState actor;
    if (!TryGetLiveRunEnemyActorByAddress(target_actor_address, &actor) ||
        !IsSaneExplicitCastTarget(actor, position_x, position_y)) {
        return false;
    }

    const auto network_actor_id = ResolveLocalRunEnemyNetworkActorId(actor);
    if (network_actor_id == 0) {
        return false;
    }
    if (network_actor_id_out != nullptr) {
        *network_actor_id_out = network_actor_id;
    }
    return true;
}

void ApplyEnemyDamageCorrection(const EnemyDamageResultPacket& packet) {
    if (!IsLocalTransportClient() ||
        packet.claimant_participant_id != g_local_transport.local_peer_id ||
        packet.target_network_actor_id == 0 ||
        !std::isfinite(packet.authoritative_hp) ||
        !std::isfinite(packet.authoritative_max_hp) ||
        packet.authoritative_max_hp <= 0.0f) {
        return;
    }

    const auto actor_address = FindReplicatedLocalActorAddress(packet.target_network_actor_id);
    if (actor_address == 0) {
        return;
    }

    if (TryWriteRunEnemyHealth(
            actor_address,
            packet.authoritative_hp,
            packet.authoritative_max_hp)) {
        const bool accepted =
            packet.result_code == static_cast<std::uint8_t>(EnemyDamageResultCode::Accepted);
        const bool dead =
            packet.dead != 0 || packet.authoritative_hp <= kEnemyDamageClaimHpEpsilon;
        std::uint32_t death_exception_code = 0;
        bool death_called = false;
        if (accepted && dead) {
            death_called = sdmod::TryTriggerRunEnemyDeath(actor_address, &death_exception_code);
        }
        if (packet.result_code == static_cast<std::uint8_t>(EnemyDamageResultCode::Accepted)) {
            g_local_transport.last_enemy_claimed_hp_by_network_id[packet.target_network_actor_id] =
                packet.authoritative_hp;
            g_local_transport.rejected_enemy_damage_retry_suppressed_until_ms.erase(
                packet.target_network_actor_id);
        } else {
            g_local_transport.last_enemy_claimed_hp_by_network_id.erase(packet.target_network_actor_id);
            g_local_transport.rejected_enemy_damage_retry_suppressed_until_ms[packet.target_network_actor_id] =
                static_cast<std::uint64_t>(GetTickCount64()) +
                kEnemyDamageRejectedRetrySuppressMs;
        }
        Log(
            "Multiplayer enemy damage correction applied. target_network_actor_id=" +
            std::to_string(packet.target_network_actor_id) +
            " result=" + std::to_string(static_cast<int>(packet.result_code)) +
            " hp=" + std::to_string(packet.authoritative_hp) +
            " max_hp=" + std::to_string(packet.authoritative_max_hp) +
            " death_called=" + std::to_string(death_called ? 1 : 0) +
            " death_seh=" + HexString(static_cast<uintptr_t>(death_exception_code)));
    }
}

void SendBufferToEndpoint(const void* packet, std::size_t packet_size, const sockaddr_in& endpoint) {
    if (packet == nullptr || packet_size == 0 || packet_size > static_cast<std::size_t>((std::numeric_limits<int>::max)())) {
        return;
    }
    const int sent = sendto(
        g_local_transport.socket_handle,
        reinterpret_cast<const char*>(packet),
        static_cast<int>(packet_size),
        0,
        reinterpret_cast<const sockaddr*>(&endpoint),
        sizeof(endpoint));
    if (sent == static_cast<int>(packet_size)) {
        g_local_transport.packets_sent += 1;
    }
}

void SendPacketToEndpoint(const StatePacket& packet, const sockaddr_in& endpoint) {
    SendBufferToEndpoint(&packet, sizeof(packet), endpoint);
}

void SendPacketToEndpoint(const CastPacket& packet, const sockaddr_in& endpoint) {
    SendBufferToEndpoint(&packet, sizeof(packet), endpoint);
}

void SendPacketToEndpoint(const WorldSnapshotPacket& packet, const sockaddr_in& endpoint) {
    SendBufferToEndpoint(&packet, sizeof(packet), endpoint);
}

void SendPacketToEndpoint(const LootSnapshotPacket& packet, const sockaddr_in& endpoint) {
    SendBufferToEndpoint(&packet, sizeof(packet), endpoint);
}

void SendPacketToEndpoint(const EnemyDamageClaimPacket& packet, const sockaddr_in& endpoint) {
    SendBufferToEndpoint(&packet, sizeof(packet), endpoint);
}

void SendPacketToEndpoint(const EnemyDamageResultPacket& packet, const sockaddr_in& endpoint) {
    SendBufferToEndpoint(&packet, sizeof(packet), endpoint);
}

void SendPacketToEndpoint(const LootPickupRequestPacket& packet, const sockaddr_in& endpoint) {
    SendBufferToEndpoint(&packet, sizeof(packet), endpoint);
}

void SendPacketToEndpoint(const LootPickupResultPacket& packet, const sockaddr_in& endpoint) {
    SendBufferToEndpoint(&packet, sizeof(packet), endpoint);
}

void PublishWorldSnapshotRuntimeInfo(const WorldSnapshotPacket& packet, std::uint64_t now_ms);

void SendLocalState(std::uint64_t now_ms) {
    if (now_ms - g_local_transport.last_send_ms < kLocalTransportSendIntervalMs) {
        return;
    }
    g_local_transport.last_send_ms = now_ms;

    const auto packet = BuildLocalStatePacket();
    if (packet.transform_valid == 0) {
        return;
    }

    const auto endpoints = BuildKnownSendEndpoints();
    for (const auto& endpoint : endpoints) {
        SendPacketToEndpoint(packet, endpoint);
    }
}

void SendWorldSnapshot(std::uint64_t now_ms) {
    if (!g_local_transport.is_host ||
        now_ms - g_local_transport.last_world_snapshot_send_ms < kLocalTransportWorldSnapshotIntervalMs) {
        return;
    }
    g_local_transport.last_world_snapshot_send_ms = now_ms;

    WorldSnapshotPacket packet{};
    if (!BuildLocalWorldSnapshotPacket(&packet)) {
        return;
    }
    const auto scene_kind = static_cast<WorldSceneKind>(packet.scene_kind);
    if (packet.actor_count == 0 && scene_kind != WorldSceneKind::Run) {
        return;
    }

    PublishWorldSnapshotRuntimeInfo(packet, now_ms);

    const auto endpoints = BuildKnownSendEndpoints();
    for (const auto& endpoint : endpoints) {
        SendPacketToEndpoint(packet, endpoint);
    }
}

void SendLootSnapshot(std::uint64_t now_ms) {
    if (!g_local_transport.is_host ||
        now_ms - g_local_transport.last_loot_snapshot_send_ms < kLocalTransportLootSnapshotIntervalMs) {
        return;
    }
    g_local_transport.last_loot_snapshot_send_ms = now_ms;

    LootSnapshotPacket packet{};
    if (!BuildLocalLootSnapshotPacket(&packet)) {
        return;
    }

    const auto endpoints = BuildKnownSendEndpoints();
    for (const auto& endpoint : endpoints) {
        SendPacketToEndpoint(packet, endpoint);
    }
}

std::vector<QueuedLocalLootPickupRequest> TakeQueuedLocalLootPickupRequests() {
    std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
    std::vector<QueuedLocalLootPickupRequest> requests;
    requests.swap(g_queued_local_loot_pickup_requests);
    return requests;
}

const LootDropSnapshot* FindLootDropSnapshotByNetworkId(
    const LootSnapshotRuntimeInfo& snapshot,
    std::uint64_t network_drop_id) {
    for (const auto& drop : snapshot.drops) {
        if (drop.network_drop_id == network_drop_id) {
            return &drop;
        }
    }
    return nullptr;
}

void SendQueuedLootPickupRequests() {
    if (!IsLocalTransportClient()) {
        return;
    }

    auto requests = TakeQueuedLocalLootPickupRequests();
    if (requests.empty()) {
        return;
    }

    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);
    if (local == nullptr ||
        !local->runtime.valid ||
        !local->runtime.in_run ||
        local->runtime.scene_intent.kind != ParticipantSceneIntentKind::Run ||
        !runtime_state.loot_snapshot.valid ||
        runtime_state.loot_snapshot.scene_intent.kind != ParticipantSceneIntentKind::Run) {
        return;
    }
    if (runtime_state.loot_snapshot.run_nonce != 0 &&
        local->runtime.run_nonce != 0 &&
        runtime_state.loot_snapshot.run_nonce != local->runtime.run_nonce) {
        return;
    }

    const auto endpoints = BuildKnownSendEndpoints();
    if (endpoints.empty()) {
        return;
    }

    for (const auto& request : requests) {
        const auto* drop =
            FindLootDropSnapshotByNetworkId(runtime_state.loot_snapshot, request.network_drop_id);
        const bool have_recent_pickup_result =
            runtime_state.last_loot_pickup_result.valid &&
            runtime_state.last_loot_pickup_result.network_drop_id == request.network_drop_id;
        if (drop == nullptr && !have_recent_pickup_result) {
            Log(
                "Multiplayer loot pickup request skipped; replicated drop not found. network_drop_id=" +
                std::to_string(request.network_drop_id) +
                " request_sequence=" + std::to_string(request.request_sequence));
            continue;
        }

        LootPickupRequestPacket packet{};
        packet.header = MakePacketHeader(PacketKind::LootPickupRequest, g_local_transport.next_sequence++);
        packet.participant_id = g_local_transport.local_peer_id;
        packet.request_sequence = request.request_sequence;
        packet.run_nonce = local->runtime.run_nonce != 0
                               ? local->runtime.run_nonce
                               : runtime_state.loot_snapshot.run_nonce;
        packet.network_drop_id = request.network_drop_id;
        packet.requester_position_x = local->runtime.position_x;
        packet.requester_position_y = local->runtime.position_y;
        packet.drop_position_x = drop != nullptr ? drop->position_x : local->runtime.position_x;
        packet.drop_position_y = drop != nullptr ? drop->position_y : local->runtime.position_y;

        for (const auto& endpoint : endpoints) {
            SendPacketToEndpoint(packet, endpoint);
        }
        Log(
            "Multiplayer loot pickup request sent. participant_id=" +
            std::to_string(packet.participant_id) +
            " request_sequence=" + std::to_string(packet.request_sequence) +
            " network_drop_id=" + std::to_string(packet.network_drop_id));
    }
}

std::vector<QueuedLocalCastEvent> TakeQueuedLocalCastEvents() {
    std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
    std::vector<QueuedLocalCastEvent> events;
    events.swap(g_queued_local_cast_events);
    return events;
}

bool IsCastInputPhaseValue(std::uint8_t phase) {
    return phase == static_cast<std::uint8_t>(CastInputPhase::Pressed) ||
           phase == static_cast<std::uint8_t>(CastInputPhase::Held) ||
           phase == static_cast<std::uint8_t>(CastInputPhase::Released);
}

const char* CastInputPhaseLabel(std::uint8_t phase) {
    switch (static_cast<CastInputPhase>(phase)) {
        case CastInputPhase::Pressed:
            return "pressed";
        case CastInputPhase::Held:
            return "held";
        case CastInputPhase::Released:
            return "released";
    }
    return "unknown";
}

std::uint64_t ResolveLocalCastTargetNetworkActorId(
    const QueuedLocalCastEvent& event,
    float position_x,
    float position_y,
    float direction_x,
    float direction_y) {
    const float aim_target_x =
        event.has_aim_target ? event.aim_target_x : position_x + direction_x * 512.0f;
    const float aim_target_y =
        event.has_aim_target ? event.aim_target_y : position_y + direction_y * 512.0f;
    if (event.target_network_actor_id != 0) {
        SDModSceneActorState target_actor;
        if (TryFindLocalRunEnemyByNetworkId(event.target_network_actor_id, &target_actor) &&
            IsSaneExplicitCastTarget(target_actor, position_x, position_y)) {
            return event.target_network_actor_id;
        }
        return 0;
    }

    if (event.target_actor_address != 0) {
        std::uint64_t target_network_actor_id = 0;
        if (TryResolveExplicitCastTargetNetworkActorId(
                event.target_actor_address,
                position_x,
                position_y,
                &target_network_actor_id)) {
            return target_network_actor_id;
        }
    }

    if (event.has_aim_target) {
        SDModSceneActorState target_actor;
        if (TryFindLocalRunEnemyForCastAim(
                position_x,
                position_y,
                direction_x,
                direction_y,
                aim_target_x,
                aim_target_y,
                &target_actor)) {
            return ResolveLocalRunEnemyNetworkActorId(target_actor);
        }
    }
    return 0;
}

bool BuildLocalCastPacket(
    const RuntimeState& runtime_state,
    const ParticipantInfo& local,
    const QueuedLocalCastEvent& event,
    std::uint32_t cast_sequence,
    CastInputPhase phase,
    CastPacket* packet) {
    if (packet == nullptr ||
        cast_sequence == 0 ||
        event.skill_id < 0 ||
        !std::isfinite(event.position_x) ||
        !std::isfinite(event.position_y) ||
        !std::isfinite(event.direction_x) ||
        !std::isfinite(event.direction_y)) {
        return false;
    }

    (void)runtime_state;
    CastPacket built{};
    built.header = MakePacketHeader(PacketKind::Cast, g_local_transport.next_sequence++);
    built.participant_id = g_local_transport.local_peer_id;
    built.cast_sequence = cast_sequence;
    built.cast_kind = static_cast<std::uint8_t>(CastKind::Primary);
    built.secondary_slot = -1;
    built.input_phase = static_cast<std::uint8_t>(phase);
    built.input_flags = 0;
    built.run_nonce = local.runtime.run_nonce;
    built.target_network_actor_id =
        ResolveLocalCastTargetNetworkActorId(
            event,
            event.position_x,
            event.position_y,
            event.direction_x,
            event.direction_y);
    built.skill_id = event.skill_id;
    built.element_id = local.character_profile.element_id;
    built.discipline_id = static_cast<std::int32_t>(local.character_profile.discipline_id);
    built.primary_entry_index = local.character_profile.loadout.primary_entry_index;
    built.primary_combo_entry_index = local.character_profile.loadout.primary_combo_entry_index;
    for (std::size_t index = 0; index < local.character_profile.loadout.secondary_entry_indices.size(); ++index) {
        built.queued_secondary_entry_indices[index] =
            local.character_profile.loadout.secondary_entry_indices[index];
    }
    built.position_x = event.position_x;
    built.position_y = event.position_y;
    built.heading = local.runtime.heading;
    built.direction_x = event.direction_x;
    built.direction_y = event.direction_y;
    built.aim_target_x =
        event.has_aim_target ? event.aim_target_x : event.position_x + event.direction_x * 512.0f;
    built.aim_target_y =
        event.has_aim_target ? event.aim_target_y : event.position_y + event.direction_y * 512.0f;

    *packet = built;
    return true;
}

bool TryRefreshActiveLocalCastEvent(QueuedLocalCastEvent* event) {
    if (event == nullptr || !g_local_transport.active_local_cast_input.active) {
        return false;
    }

    const auto& active = g_local_transport.active_local_cast_input;
    *event = QueuedLocalCastEvent{};
    event->skill_id = active.skill_id;
    event->target_network_actor_id = active.target_network_actor_id;
    event->target_actor_address = active.target_actor_address;
    event->minimum_hold_until_ms = active.minimum_hold_until_ms;
    event->position_x = active.last_position_x;
    event->position_y = active.last_position_y;
    event->direction_x = active.last_direction_x;
    event->direction_y = active.last_direction_y;
    event->has_aim_target = active.has_aim_target;
    event->aim_target_x = active.last_aim_target_x;
    event->aim_target_y = active.last_aim_target_y;

    SDModPlayerState player_state;
    if (!TryGetPlayerState(&player_state) || !player_state.valid) {
        return true;
    }

    constexpr float kDegreesToRadians = 0.01745329251994329576923690768489f;
    float normalized_heading = player_state.heading;
    while (normalized_heading < 0.0f) {
        normalized_heading += 360.0f;
    }
    while (normalized_heading >= 360.0f) {
        normalized_heading -= 360.0f;
    }
    auto radians = (normalized_heading - 90.0f) * kDegreesToRadians;
    auto direction_x = static_cast<float>(std::cos(radians));
    auto direction_y = static_cast<float>(std::sin(radians));
    if (!std::isfinite(player_state.x) ||
        !std::isfinite(player_state.y) ||
        !std::isfinite(direction_x) ||
        !std::isfinite(direction_y)) {
        return true;
    }

    event->position_x = player_state.x;
    event->position_y = player_state.y;

    float aim_target_x = 0.0f;
    float aim_target_y = 0.0f;
    if (player_state.actor_address != 0 &&
        ProcessMemory::Instance().TryReadField(player_state.actor_address, kActorAimTargetXOffset, &aim_target_x) &&
        ProcessMemory::Instance().TryReadField(player_state.actor_address, kActorAimTargetYOffset, &aim_target_y) &&
        IsUsableLocalCastAimTarget(player_state.x, player_state.y, aim_target_x, aim_target_y)) {
        const auto aim_dx = aim_target_x - player_state.x;
        const auto aim_dy = aim_target_y - player_state.y;
        const auto aim_length = std::sqrt((aim_dx * aim_dx) + (aim_dy * aim_dy));
        if (std::isfinite(aim_length) && aim_length > 0.0001f) {
            direction_x = aim_dx / aim_length;
            direction_y = aim_dy / aim_length;
            event->has_aim_target = true;
            event->aim_target_x = aim_target_x;
            event->aim_target_y = aim_target_y;
        }
    }

    event->direction_x = direction_x;
    event->direction_y = direction_y;

    uintptr_t target_actor_address = 0;
    if (player_state.actor_address != 0 &&
        ProcessMemory::Instance().TryReadField(
            player_state.actor_address,
            kActorCurrentTargetActorOffset,
            &target_actor_address) &&
        target_actor_address != 0) {
        std::uint64_t target_network_actor_id = 0;
        if (TryResolveExplicitCastTargetNetworkActorId(
                target_actor_address,
                event->position_x,
                event->position_y,
                &target_network_actor_id)) {
            event->target_actor_address = target_actor_address;
            event->target_network_actor_id = target_network_actor_id;
        } else {
            event->target_actor_address = 0;
            event->target_network_actor_id = 0;
        }
    }
    return true;
}

void RememberActiveLocalCastInput(
    const QueuedLocalCastEvent& event,
    const CastPacket& packet,
    std::uint64_t now_ms) {
    auto& active = g_local_transport.active_local_cast_input;
    active.active = true;
    active.cast_sequence = packet.cast_sequence;
    active.skill_id = event.skill_id;
    active.target_network_actor_id = packet.target_network_actor_id;
    active.target_actor_address = event.target_actor_address;
    active.minimum_hold_until_ms = event.minimum_hold_until_ms;
    active.last_position_x = event.position_x;
    active.last_position_y = event.position_y;
    active.last_direction_x = event.direction_x;
    active.last_direction_y = event.direction_y;
    active.has_aim_target = event.has_aim_target;
    active.last_aim_target_x = event.aim_target_x;
    active.last_aim_target_y = event.aim_target_y;
    active.last_sent_ms = now_ms;
}

void SendCastPacketToEndpoints(const CastPacket& packet, const std::vector<sockaddr_in>& endpoints) {
    for (const auto& endpoint : endpoints) {
        SendPacketToEndpoint(packet, endpoint);
    }
    Log(
        "Multiplayer local cast sent. participant_id=" +
        std::to_string(packet.participant_id) +
        " cast_sequence=" + std::to_string(packet.cast_sequence) +
        " phase=" + CastInputPhaseLabel(packet.input_phase) +
        " skill_id=" + std::to_string(packet.skill_id) +
        " target_network_actor_id=" + std::to_string(packet.target_network_actor_id));
}

void ReleaseActiveLocalCastInputForReplacement(
    const RuntimeState& runtime_state,
    const ParticipantInfo& local,
    const std::vector<sockaddr_in>& endpoints,
    std::uint64_t now_ms,
    std::uint64_t replacement_native_queue_id) {
    if (!g_local_transport.active_local_cast_input.active) {
        return;
    }

    const auto replaced_cast_sequence =
        g_local_transport.active_local_cast_input.cast_sequence;
    QueuedLocalCastEvent release_event{};
    const bool refreshed = TryRefreshActiveLocalCastEvent(&release_event);
    if (refreshed) {
        CastPacket release_packet{};
        if (BuildLocalCastPacket(
                runtime_state,
                local,
                release_event,
                replaced_cast_sequence,
                CastInputPhase::Released,
                &release_packet)) {
            SendCastPacketToEndpoints(release_packet, endpoints);
        }
    }

    g_local_transport.active_local_cast_input = ActiveLocalCastInput{};
    Log(
        "Multiplayer local active cast replaced by native cast. released_cast_sequence=" +
        std::to_string(replaced_cast_sequence) +
        " replacement_native_queue_id=" +
        std::to_string(replacement_native_queue_id) +
        " replacement_tick_ms=" +
        std::to_string(now_ms));
}

void SendQueuedCastEvents(std::uint64_t now_ms) {
    auto events = TakeQueuedLocalCastEvents();
    if (events.empty()) {
        return;
    }

    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);
    if (local == nullptr ||
        !local->runtime.valid ||
        !local->runtime.in_run ||
        local->runtime.scene_intent.kind != ParticipantSceneIntentKind::Run) {
        return;
    }

    const auto endpoints = BuildKnownSendEndpoints();
    if (endpoints.empty()) {
        return;
    }

    for (const auto& event : events) {
        if (g_local_transport.active_local_cast_input.active) {
            ReleaseActiveLocalCastInputForReplacement(
                runtime_state,
                *local,
                endpoints,
                now_ms,
                event.native_queue_id);
        }

        const auto cast_sequence = g_local_transport.next_cast_sequence++;
        CastPacket packet{};
        if (!BuildLocalCastPacket(
                runtime_state,
                *local,
                event,
                cast_sequence,
                CastInputPhase::Pressed,
                &packet)) {
            continue;
        }

        SendCastPacketToEndpoints(packet, endpoints);
        if (event.native_queue_id != 0) {
            Log(
                "Multiplayer local native cast sent. native_queue_id=" +
                std::to_string(event.native_queue_id) +
                " cast_sequence=" + std::to_string(cast_sequence) +
                " participant_id=" + std::to_string(packet.participant_id));
        }
        RememberActiveLocalCastInput(event, packet, now_ms);
    }
}

void SendActiveLocalCastInput(std::uint64_t now_ms) {
    if (!g_local_transport.active_local_cast_input.active) {
        return;
    }

    const bool still_held =
        IsGameplayMouseLeftDown() ||
        now_ms < g_local_transport.active_local_cast_input.minimum_hold_until_ms;
    if (still_held &&
        now_ms - g_local_transport.active_local_cast_input.last_sent_ms <
            kLocalCastInputUpdateIntervalMs) {
        return;
    }

    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);
    if (local == nullptr ||
        !local->runtime.valid ||
        !local->runtime.in_run ||
        local->runtime.scene_intent.kind != ParticipantSceneIntentKind::Run) {
        g_local_transport.active_local_cast_input = ActiveLocalCastInput{};
        return;
    }

    const auto endpoints = BuildKnownSendEndpoints();
    if (endpoints.empty()) {
        return;
    }

    QueuedLocalCastEvent event{};
    if (!TryRefreshActiveLocalCastEvent(&event)) {
        g_local_transport.active_local_cast_input = ActiveLocalCastInput{};
        return;
    }

    CastPacket packet{};
    if (!BuildLocalCastPacket(
            runtime_state,
            *local,
            event,
            g_local_transport.active_local_cast_input.cast_sequence,
            still_held ? CastInputPhase::Held : CastInputPhase::Released,
            &packet)) {
        return;
    }

    SendCastPacketToEndpoints(packet, endpoints);
    if (still_held) {
        RememberActiveLocalCastInput(event, packet, now_ms);
    } else {
        g_local_transport.active_local_cast_input = ActiveLocalCastInput{};
    }
}

std::unordered_map<uintptr_t, SDModSceneActorState> BuildSceneActorMapByAddress() {
    std::vector<SDModSceneActorState> actors;
    std::unordered_map<uintptr_t, SDModSceneActorState> by_address;
    if (!TryListSceneActors(&actors)) {
        return by_address;
    }

    by_address.reserve(actors.size());
    for (const auto& actor : actors) {
        if (actor.actor_address != 0) {
            by_address[actor.actor_address] = actor;
        }
    }
    return by_address;
}

bool SendLocalEnemyDamageClaim(
    const RuntimeState& runtime_state,
    const ParticipantInfo& local,
    std::uint64_t network_actor_id,
    std::int32_t skill_id,
    float authoritative_hp,
    float local_hp,
    float max_hp,
    float target_position_x,
    float target_position_y) {
    const auto endpoints = BuildKnownSendEndpoints();
    if (endpoints.empty()) {
        return false;
    }
    if (network_actor_id == 0 ||
        !std::isfinite(authoritative_hp) ||
        !std::isfinite(local_hp) ||
        !std::isfinite(max_hp) ||
        max_hp <= 0.0f ||
        !std::isfinite(target_position_x) ||
        !std::isfinite(target_position_y)) {
        return false;
    }

    authoritative_hp = ClampEnemyHp(authoritative_hp, max_hp);
    local_hp = ClampEnemyHp(local_hp, max_hp);
    if (local_hp + kEnemyDamageClaimHpEpsilon >= authoritative_hp) {
        g_local_transport.last_enemy_claimed_hp_by_network_id.erase(network_actor_id);
        g_local_transport.rejected_enemy_damage_retry_suppressed_until_ms.erase(network_actor_id);
        return false;
    }

    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    const auto retry_suppressed_it =
        g_local_transport.rejected_enemy_damage_retry_suppressed_until_ms.find(network_actor_id);
    if (retry_suppressed_it !=
        g_local_transport.rejected_enemy_damage_retry_suppressed_until_ms.end()) {
        if (retry_suppressed_it->second > now_ms) {
            return false;
        }
        g_local_transport.rejected_enemy_damage_retry_suppressed_until_ms.erase(
            retry_suppressed_it);
    }

    const auto last_claim_it =
        g_local_transport.last_enemy_claimed_hp_by_network_id.find(network_actor_id);
    if (last_claim_it != g_local_transport.last_enemy_claimed_hp_by_network_id.end() &&
        std::fabs(last_claim_it->second - local_hp) <= kEnemyDamageClaimHpEpsilon) {
        return false;
    }

    EnemyDamageClaimPacket packet{};
    packet.header = MakePacketHeader(PacketKind::EnemyDamageClaim, g_local_transport.next_sequence++);
    packet.participant_id = g_local_transport.local_peer_id;
    packet.claim_sequence = g_local_transport.next_enemy_damage_claim_sequence++;
    packet.run_nonce = local.runtime.run_nonce != 0
                           ? local.runtime.run_nonce
                           : runtime_state.world_snapshot.run_nonce;
    packet.target_network_actor_id = network_actor_id;
    packet.skill_id = skill_id;
    packet.claimed_damage = authoritative_hp - local_hp;
    packet.client_before_hp = authoritative_hp;
    packet.client_after_hp = local_hp;
    packet.caster_position_x = local.runtime.position_x;
    packet.caster_position_y = local.runtime.position_y;
    packet.target_position_x = target_position_x;
    packet.target_position_y = target_position_y;
    packet.lethal = local_hp <= kEnemyDamageClaimHpEpsilon ? 1 : 0;

    for (const auto& endpoint : endpoints) {
        SendPacketToEndpoint(packet, endpoint);
    }
    std::uint32_t local_death_exception_code = 0;
    bool local_death_called = false;
    if (packet.lethal != 0) {
        const auto local_actor_address = FindReplicatedLocalActorAddress(network_actor_id);
        if (local_actor_address != 0) {
            local_death_called =
                sdmod::TryTriggerRunEnemyDeath(local_actor_address, &local_death_exception_code);
        }
    }
    g_local_transport.last_enemy_claimed_hp_by_network_id[network_actor_id] = local_hp;
    Log(
        "Multiplayer enemy damage claim sent. target_network_actor_id=" +
        std::to_string(network_actor_id) +
        " sequence=" + std::to_string(packet.claim_sequence) +
        " damage=" + std::to_string(packet.claimed_damage) +
        " after_hp=" + std::to_string(packet.client_after_hp) +
        " local_death_called=" + std::to_string(local_death_called ? 1 : 0) +
        " local_death_seh=" + HexString(static_cast<uintptr_t>(local_death_exception_code)));
    return true;
}

std::vector<QueuedLocalEnemyDamageClaim> TakeQueuedLocalEnemyDamageClaims() {
    std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
    std::vector<QueuedLocalEnemyDamageClaim> claims;
    claims.swap(g_queued_local_enemy_damage_claims);
    return claims;
}

void SendLocalEnemyDamageClaims() {
    if (!IsLocalTransportClient()) {
        return;
    }

    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);
    if (local == nullptr ||
        !local->runtime.valid ||
        !local->runtime.in_run ||
        local->runtime.scene_intent.kind != ParticipantSceneIntentKind::Run ||
        !runtime_state.world_snapshot.valid ||
        runtime_state.world_snapshot.scene_intent.kind != ParticipantSceneIntentKind::Run) {
        return;
    }
    if (runtime_state.world_snapshot.run_nonce != 0 &&
        local->runtime.run_nonce != 0 &&
        runtime_state.world_snapshot.run_nonce != local->runtime.run_nonce) {
        return;
    }

    for (const auto& claim : TakeQueuedLocalEnemyDamageClaims()) {
        (void)SendLocalEnemyDamageClaim(
            runtime_state,
            *local,
            claim.network_actor_id,
            claim.skill_id,
            claim.authoritative_hp,
            claim.local_hp,
            claim.max_hp,
            claim.target_position_x,
            claim.target_position_y);
    }

    const auto local_scene_actors = BuildSceneActorMapByAddress();
    if (local_scene_actors.empty()) {
        return;
    }

    for (const auto& binding : runtime_state.world_snapshot_apply.actor_bindings) {
        if (binding.network_actor_id == 0 ||
            binding.local_actor_address == 0 ||
            !binding.matched ||
            binding.parked ||
            binding.removed) {
            continue;
        }

        const auto* authoritative_actor = FindSnapshotActorByNetworkId(
            runtime_state.world_snapshot,
            binding.network_actor_id);
        if (authoritative_actor == nullptr ||
            !authoritative_actor->tracked_enemy ||
            authoritative_actor->run_static ||
            !std::isfinite(authoritative_actor->hp) ||
            !std::isfinite(authoritative_actor->max_hp) ||
            authoritative_actor->max_hp <= 0.0f ||
            authoritative_actor->hp <= kEnemyDamageClaimHpEpsilon) {
            g_local_transport.last_enemy_claimed_hp_by_network_id.erase(binding.network_actor_id);
            continue;
        }

        const auto local_it = local_scene_actors.find(binding.local_actor_address);
        if (local_it == local_scene_actors.end()) {
            continue;
        }
        const auto& local_actor = local_it->second;
        if (!local_actor.tracked_enemy ||
            !std::isfinite(local_actor.hp) ||
            !std::isfinite(local_actor.max_hp) ||
            local_actor.max_hp <= 0.0f) {
            continue;
        }

        const float local_hp = ClampEnemyHp(local_actor.hp, local_actor.max_hp);
        const float authoritative_hp =
            ClampEnemyHp(authoritative_actor->hp, authoritative_actor->max_hp);
        if (local_hp + kEnemyDamageClaimHpEpsilon >= authoritative_hp) {
            g_local_transport.last_enemy_claimed_hp_by_network_id.erase(binding.network_actor_id);
            continue;
        }
        (void)SendLocalEnemyDamageClaim(
            runtime_state,
            *local,
            binding.network_actor_id,
            0,
            authoritative_hp,
            local_hp,
            authoritative_actor->max_hp,
            local_actor.x,
            local_actor.y);
    }
}

void RelayStatePacketToPeers(const StatePacket& packet, const sockaddr_in& source) {
    if (!g_local_transport.is_host) {
        return;
    }

    std::vector<sockaddr_in> endpoints;
    for (const auto& peer : g_local_transport.peers) {
        if (SameEndpoint(peer.address, source)) {
            continue;
        }
        const bool already_added = std::any_of(endpoints.begin(), endpoints.end(), [&](const sockaddr_in& existing) {
            return SameEndpoint(existing, peer.address);
        });
        if (!already_added) {
            endpoints.push_back(peer.address);
        }
    }

    for (const auto& endpoint : endpoints) {
        SendPacketToEndpoint(packet, endpoint);
    }
}

template <typename Packet>
void RelayPacketToPeers(const Packet& packet, const sockaddr_in& source) {
    if (!g_local_transport.is_host) {
        return;
    }

    std::vector<sockaddr_in> endpoints;
    for (const auto& peer : g_local_transport.peers) {
        if (SameEndpoint(peer.address, source)) {
            continue;
        }
        const bool already_added = std::any_of(endpoints.begin(), endpoints.end(), [&](const sockaddr_in& existing) {
            return SameEndpoint(existing, peer.address);
        });
        if (!already_added) {
            endpoints.push_back(peer.address);
        }
    }

    for (const auto& endpoint : endpoints) {
        SendPacketToEndpoint(packet, endpoint);
    }
}

bool IsConfiguredRemoteAuthorityEndpoint(const sockaddr_in& from) {
    return g_local_transport.configured_remote_valid &&
           SameEndpoint(from, g_local_transport.configured_remote);
}

bool IsLocalSceneAlreadyRun(const SDModSceneState& scene_state) {
    return scene_state.kind == "arena" || scene_state.name == "testrun";
}

bool IsLocalSceneSharedHub(const SDModSceneState& scene_state) {
    return scene_state.kind == "hub" || scene_state.name == "hub";
}

bool DoesLocalSceneMatchParticipantIntent(const ParticipantSceneIntent& scene_intent) {
    SDModSceneState scene_state;
    if (!TryGetSceneState(&scene_state) || !scene_state.valid) {
        return false;
    }

    switch (scene_intent.kind) {
    case ParticipantSceneIntentKind::Run:
        return IsLocalSceneAlreadyRun(scene_state);
    case ParticipantSceneIntentKind::SharedHub:
        return IsLocalSceneSharedHub(scene_state);
    case ParticipantSceneIntentKind::PrivateRegion: {
        if (scene_state.kind == "transition" || scene_state.name == "transition") {
            return false;
        }
        const bool region_matches =
            scene_intent.region_index >= 0 &&
            scene_state.current_region_index >= 0 &&
            scene_intent.region_index == scene_state.current_region_index;
        const bool type_matches =
            scene_intent.region_type_id >= 0 &&
            scene_state.region_type_id >= 0 &&
            scene_intent.region_type_id == scene_state.region_type_id;
        return region_matches || type_matches;
    }
    }

    return false;
}

void MaybeQueueClientHostRunStart(
    const StatePacket& packet,
    const ParticipantSceneIntent& scene_intent,
    const sockaddr_in& from,
    std::uint64_t now_ms) {
    if (!IsLocalTransportClient() ||
        scene_intent.kind != ParticipantSceneIntentKind::Run ||
        packet.ready == 0 ||
        !IsConfiguredRemoteAuthorityEndpoint(from)) {
        return;
    }

    SDModSceneState scene_state;
    if (!TryGetSceneState(&scene_state) || !scene_state.valid ||
        IsLocalSceneAlreadyRun(scene_state)) {
        return;
    }
    if (!IsLocalSceneSharedHub(scene_state)) {
        Log(
            "Multiplayer local UDP ignored host run intent outside hub. authority_participant_id=" +
            std::to_string(packet.participant_id) +
            " local_scene=" + scene_state.name +
            " kind=" + scene_state.kind);
        return;
    }

    const auto last_request_ms = g_local_transport.last_client_host_run_request_ms;
    if (last_request_ms != 0 && now_ms < last_request_ms + kClientHostRunFollowRetryMs) {
        return;
    }

    std::string error_message;
    if (packet.run_nonce != 0 && !SetPendingRunGenerationSeed(packet.run_nonce, &error_message)) {
        Log(
            "Multiplayer local UDP failed to accept host run generation seed. authority_participant_id=" +
            std::to_string(packet.participant_id) +
            " seed=" + HexString(static_cast<uintptr_t>(packet.run_nonce)) +
            " error=" + error_message);
        return;
    }

    g_local_transport.last_client_host_run_request_ms = now_ms;
    if (!QueueHubStartTestrun(&error_message)) {
        Log(
            "Multiplayer local UDP failed to follow host run intent. authority_participant_id=" +
            std::to_string(packet.participant_id) +
            " error=" + error_message);
        return;
    }

    Log(
        "Multiplayer local UDP queued host-authoritative run entry. authority_participant_id=" +
        std::to_string(packet.participant_id) +
        " run_generation_seed=" + HexString(static_cast<uintptr_t>(packet.run_nonce)) +
        " sequence=" + std::to_string(packet.header.sequence));
}

void ApplyRemoteStatePacket(const StatePacket& packet, const sockaddr_in& from, std::uint64_t now_ms) {
    if (packet.participant_id == 0 ||
        packet.participant_id == kLocalParticipantId ||
        packet.participant_id == g_local_transport.local_peer_id) {
        return;
    }

    UpsertPeerEndpoint(from, packet.participant_id, now_ms);
    RelayStatePacketToPeers(packet, from);

    MultiplayerCharacterProfile profile;
    profile.element_id = packet.element_id;
    profile.discipline_id = static_cast<CharacterDisciplineId>(packet.discipline_id);
    for (std::size_t index = 0; index < profile.appearance.choice_ids.size(); ++index) {
        profile.appearance.choice_ids[index] = packet.appearance_choice_ids[index];
    }
    profile.loadout.primary_entry_index = packet.primary_entry_index;
    profile.loadout.primary_combo_entry_index = packet.primary_combo_entry_index;
    for (std::size_t index = 0; index < profile.loadout.secondary_entry_indices.size(); ++index) {
        profile.loadout.secondary_entry_indices[index] = packet.queued_secondary_entry_indices[index];
    }
    profile.level = packet.level;
    profile.experience = packet.experience_current;
    if (!IsValidCharacterProfile(profile)) {
        return;
    }

    const auto scene_intent = SceneIntentFromPacket(packet);
    const auto display_name = PacketDisplayName(packet);
    const bool transform_valid = packet.transform_valid != 0 &&
        std::isfinite(packet.position_x) &&
        std::isfinite(packet.position_y) &&
        std::isfinite(packet.heading);
    const auto effect_state = NormalizeRenderDriveEffectState(
        packet.render_drive_effect_timer,
        packet.render_drive_effect_progress);

    UpdateRuntimeState([&](RuntimeState& state) {
        auto* participant = UpsertRemoteParticipant(
            state,
            packet.participant_id,
            ParticipantControllerKind::Native);
        if (participant == nullptr) {
            return;
        }

        if (!display_name.empty()) {
            participant->name = display_name;
        } else if (participant->name.empty() || participant->name == "Remote Wizard") {
            participant->name = "Remote Wizard " + std::to_string(packet.participant_id);
        }
        participant->ready = packet.ready != 0;
        participant->transport_connected = true;
        participant->transport_using_relay = false;
        participant->last_packet_ms = now_ms;
        participant->character_profile = profile;
        participant->runtime.valid = true;
        participant->runtime.in_run = packet.in_run != 0;
        participant->runtime.run_nonce = packet.run_nonce;
        participant->runtime.scene_intent = scene_intent;
        participant->runtime.level = packet.level;
        participant->runtime.wave = packet.wave;
        participant->runtime.life_current = packet.life_current;
        participant->runtime.life_max = packet.life_max;
        participant->runtime.mana_current = packet.mana_current;
        participant->runtime.mana_max = packet.mana_max;
        participant->runtime.experience_current = packet.experience_current;
        participant->runtime.experience_next = packet.experience_next;
        const bool should_apply_gold =
            !participant->owned_progression.initialized ||
            packet.gold_revision >= participant->owned_progression.gold_revision;
        participant->owned_progression.initialized = true;
        if (should_apply_gold) {
            participant->owned_progression.gold = packet.owned_gold;
            participant->owned_progression.gold_revision = packet.gold_revision;
        }
        const bool should_apply_inventory =
            packet.inventory_revision >= participant->owned_progression.inventory_revision;
        if (should_apply_inventory) {
            participant->owned_progression.inventory_revision = packet.inventory_revision;
            participant->owned_progression.inventory_item_total_count = packet.inventory_item_total_count;
            participant->owned_progression.inventory_truncated =
                (packet.inventory_snapshot_flags & ParticipantInventorySnapshotFlagTruncated) != 0;
            participant->owned_progression.inventory_items.clear();
            const auto packet_inventory_count =
                (std::min)(
                    static_cast<std::size_t>(packet.inventory_item_count),
                    static_cast<std::size_t>(kParticipantInventorySnapshotMaxItems));
            participant->owned_progression.inventory_items.reserve(packet_inventory_count);
            for (std::size_t index = 0; index < packet_inventory_count; ++index) {
                const auto& packet_item = packet.inventory_items[index];
                if (packet_item.type_id == 0) {
                    continue;
                }
                ParticipantInventoryItemState item;
                item.type_id = packet_item.type_id;
                item.slot = packet_item.slot;
                item.stack_count = packet_item.stack_count;
                participant->owned_progression.inventory_items.push_back(item);
            }
        }
        const bool should_apply_progression_book =
            packet.statbook_revision >= participant->owned_progression.statbook_revision;
        if (should_apply_progression_book) {
            participant->owned_progression.statbook_revision = packet.statbook_revision;
            participant->owned_progression.progression_book_entry_total_count =
                packet.progression_book_entry_total_count;
            participant->owned_progression.progression_book_truncated =
                (packet.progression_book_snapshot_flags & ParticipantProgressionBookSnapshotFlagTruncated) != 0;
            participant->owned_progression.progression_book_entries.clear();
            const auto packet_progression_book_count =
                (std::min)(
                    static_cast<std::size_t>(packet.progression_book_entry_count),
                    static_cast<std::size_t>(kParticipantProgressionBookSnapshotMaxEntries));
            participant->owned_progression.progression_book_entries.reserve(packet_progression_book_count);
            for (std::size_t index = 0; index < packet_progression_book_count; ++index) {
                const auto& packet_entry = packet.progression_book_entries[index];
                if (packet_entry.entry_index < 0) {
                    continue;
                }
                ParticipantProgressionBookEntryState entry;
                entry.entry_index = packet_entry.entry_index;
                entry.internal_id = packet_entry.internal_id;
                entry.active = packet_entry.active;
                entry.visible = packet_entry.visible;
                entry.category = packet_entry.category;
                entry.statbook_max_level = packet_entry.statbook_max_level;
                participant->owned_progression.progression_book_entries.push_back(entry);
            }
        }
        participant->owned_progression.spellbook_revision =
            (std::max)(participant->owned_progression.spellbook_revision, packet.spellbook_revision);
        const bool should_apply_loadout =
            packet.loadout_revision >= participant->owned_progression.loadout_revision;
        if (should_apply_loadout) {
            participant->owned_progression.loadout_revision = packet.loadout_revision;
            participant->owned_progression.ability_loadout_valid = true;
            participant->owned_progression.ability_loadout = profile.loadout;
        }
        participant->runtime.primary_entry_index = packet.primary_entry_index;
        participant->runtime.primary_combo_entry_index = packet.primary_combo_entry_index;
        for (std::size_t index = 0; index < participant->runtime.queued_secondary_entry_indices.size(); ++index) {
            participant->runtime.queued_secondary_entry_indices[index] =
                packet.queued_secondary_entry_indices[index];
        }
        participant->runtime.anim_drive_state = packet.anim_drive_state;
        participant->runtime.presentation_flags =
            packet.presentation_flags & ~ParticipantPresentationFlagStaffVisualState;
        participant->runtime.attachment_staff_visual_state = 0;
        participant->runtime.render_variant_primary = packet.render_variant_primary;
        participant->runtime.render_variant_secondary = packet.render_variant_secondary;
        participant->runtime.render_weapon_type = packet.render_weapon_type;
        participant->runtime.render_selection_byte = packet.render_selection_byte;
        participant->runtime.render_variant_tertiary = packet.render_variant_tertiary;
        participant->runtime.primary_visual_link_type_id = packet.primary_visual_link_type_id;
        participant->runtime.secondary_visual_link_type_id = packet.secondary_visual_link_type_id;
        std::memcpy(
            participant->runtime.primary_visual_link_color_block.data(),
            packet.primary_visual_link_color_block,
            participant->runtime.primary_visual_link_color_block.size());
        std::memcpy(
            participant->runtime.secondary_visual_link_color_block.data(),
            packet.secondary_visual_link_color_block,
            participant->runtime.secondary_visual_link_color_block.size());
        participant->runtime.anim_drive_state_word = packet.anim_drive_state_word;
        participant->runtime.walk_cycle_primary = packet.walk_cycle_primary;
        participant->runtime.walk_cycle_secondary = packet.walk_cycle_secondary;
        participant->runtime.render_drive_stride = packet.render_drive_stride;
        participant->runtime.render_advance_rate = packet.render_advance_rate;
        participant->runtime.render_advance_phase = packet.render_advance_phase;
        participant->runtime.render_drive_effect_timer = effect_state.timer;
        participant->runtime.render_drive_effect_progress = effect_state.progress;
        participant->runtime.render_drive_overlay_alpha = packet.render_drive_overlay_alpha;
        participant->runtime.render_drive_move_blend = packet.render_drive_move_blend;
        if (transform_valid) {
            participant->runtime.transform_valid = true;
            participant->runtime.position_x = packet.position_x;
            participant->runtime.position_y = packet.position_y;
            participant->runtime.heading = packet.heading;

            ParticipantTransformSample sample;
            sample.valid = true;
            sample.received_ms = now_ms;
            sample.sequence = packet.header.sequence;
            sample.run_nonce = packet.run_nonce;
            sample.scene_intent = scene_intent;
            sample.position_x = packet.position_x;
            sample.position_y = packet.position_y;
            sample.heading = packet.heading;
            sample.anim_drive_state = packet.anim_drive_state;
            sample.presentation_flags =
                packet.presentation_flags & ~ParticipantPresentationFlagStaffVisualState;
            sample.attachment_staff_visual_state = 0;
            sample.render_variant_primary = packet.render_variant_primary;
            sample.render_variant_secondary = packet.render_variant_secondary;
            sample.render_weapon_type = packet.render_weapon_type;
            sample.render_selection_byte = packet.render_selection_byte;
            sample.render_variant_tertiary = packet.render_variant_tertiary;
            sample.primary_visual_link_type_id = packet.primary_visual_link_type_id;
            sample.secondary_visual_link_type_id = packet.secondary_visual_link_type_id;
            std::memcpy(
                sample.primary_visual_link_color_block.data(),
                packet.primary_visual_link_color_block,
                sample.primary_visual_link_color_block.size());
            std::memcpy(
                sample.secondary_visual_link_color_block.data(),
                packet.secondary_visual_link_color_block,
                sample.secondary_visual_link_color_block.size());
            sample.anim_drive_state_word = packet.anim_drive_state_word;
            sample.walk_cycle_primary = packet.walk_cycle_primary;
            sample.walk_cycle_secondary = packet.walk_cycle_secondary;
            sample.render_drive_stride = packet.render_drive_stride;
            sample.render_advance_rate = packet.render_advance_rate;
            sample.render_advance_phase = packet.render_advance_phase;
            sample.render_drive_effect_timer = effect_state.timer;
            sample.render_drive_effect_progress = effect_state.progress;
            sample.render_drive_overlay_alpha = packet.render_drive_overlay_alpha;
            sample.render_drive_move_blend = packet.render_drive_move_blend;
            AppendParticipantTransformSample(participant, sample);
        }
    });

    MaybeQueueClientHostRunStart(packet, scene_intent, from, now_ms);

    SDModParticipantGameplayState gameplay_state;
    const bool participant_materialized =
        TryGetParticipantGameplayState(packet.participant_id, &gameplay_state) &&
        gameplay_state.entity_materialized &&
        gameplay_state.actor_address != 0;
    if (transform_valid &&
        !participant_materialized &&
        DoesLocalSceneMatchParticipantIntent(scene_intent)) {
        std::string sync_error;
        (void)QueueParticipantEntitySync(
            packet.participant_id,
            profile,
            scene_intent,
            true,
            true,
            packet.position_x,
            packet.position_y,
            packet.heading,
            &sync_error);
    }
}

void ApplyRemoteCastPacket(const CastPacket& packet, const sockaddr_in& from, std::uint64_t now_ms) {
    if (packet.participant_id == 0 ||
        packet.participant_id == kLocalParticipantId ||
        packet.participant_id == g_local_transport.local_peer_id ||
        packet.cast_sequence == 0 ||
        packet.skill_id < 0 ||
        !IsCastInputPhaseValue(packet.input_phase) ||
        !std::isfinite(packet.position_x) ||
        !std::isfinite(packet.position_y) ||
        !std::isfinite(packet.heading) ||
        !std::isfinite(packet.aim_target_x) ||
        !std::isfinite(packet.aim_target_y)) {
        return;
    }

    UpsertPeerEndpoint(from, packet.participant_id, now_ms);
    RelayPacketToPeers(packet, from);

    const auto last_sequence_it =
        g_local_transport.last_cast_sequence_by_participant.find(packet.participant_id);
    if (last_sequence_it != g_local_transport.last_cast_sequence_by_participant.end() &&
        static_cast<std::int32_t>(packet.cast_sequence - last_sequence_it->second) < 0) {
        return;
    }
    auto& input_tracker = g_local_transport.remote_cast_inputs_by_participant[packet.participant_id];
    if (input_tracker.cast_sequence != packet.cast_sequence) {
        input_tracker = RemoteCastInputTracker{};
        input_tracker.cast_sequence = packet.cast_sequence;
        g_local_transport.last_cast_sequence_by_participant[packet.participant_id] =
            packet.cast_sequence;
    } else if (input_tracker.last_packet_sequence != 0 &&
               static_cast<std::int32_t>(packet.header.sequence - input_tracker.last_packet_sequence) <= 0) {
        return;
    }
    input_tracker.last_packet_sequence = packet.header.sequence;
    input_tracker.last_packet_ms = now_ms;

    const auto runtime_state = SnapshotRuntimeState();
    const auto* participant = FindParticipant(runtime_state, packet.participant_id);
    if (participant == nullptr ||
        !IsRemoteParticipant(*participant) ||
        !IsNativeControlledParticipant(*participant) ||
        !participant->runtime.valid ||
        !participant->runtime.in_run ||
        participant->runtime.scene_intent.kind != ParticipantSceneIntentKind::Run ||
        (participant->runtime.run_nonce != 0 &&
         packet.run_nonce != 0 &&
         participant->runtime.run_nonce != packet.run_nonce)) {
        return;
    }

    SDModParticipantGameplayState gameplay_state;
    if (!TryGetParticipantGameplayState(packet.participant_id, &gameplay_state) ||
        !gameplay_state.entity_materialized ||
        gameplay_state.actor_address == 0) {
        return;
    }

    UpdateRuntimeState([&](RuntimeState& state) {
        auto* live_participant = FindParticipant(state, packet.participant_id);
        if (live_participant == nullptr) {
            return;
        }
        live_participant->runtime.transform_valid = true;
        live_participant->runtime.position_x = packet.position_x;
        live_participant->runtime.position_y = packet.position_y;
        live_participant->runtime.heading = packet.heading;

        ParticipantTransformSample sample;
        sample.valid = true;
        sample.received_ms = now_ms;
        sample.sequence = packet.header.sequence;
        sample.run_nonce = packet.run_nonce;
        sample.scene_intent = live_participant->runtime.scene_intent;
        sample.position_x = packet.position_x;
        sample.position_y = packet.position_y;
        sample.heading = packet.heading;
        AppendParticipantTransformSample(live_participant, sample);
    });

    BotCastRequest request;
    request.bot_id = packet.participant_id;
    request.kind = static_cast<CastKind>(packet.cast_kind) == CastKind::Secondary
                       ? BotCastKind::Secondary
                       : BotCastKind::Primary;
    request.secondary_slot = packet.secondary_slot;
    request.skill_id = packet.skill_id;
    request.has_origin_transform = true;
    request.origin_position_x = packet.position_x;
    request.origin_position_y = packet.position_y;
    request.has_origin_heading = true;
    request.origin_heading = packet.heading;
    request.has_aim_target = true;
    request.aim_target_x = packet.aim_target_x;
    request.aim_target_y = packet.aim_target_y;
    request.has_aim_angle = true;
    request.aim_angle = packet.heading;

    SDModSceneActorState cast_target;
    const bool resolved_target_by_id =
        packet.target_network_actor_id != 0 &&
        TryFindLocalRunEnemyByNetworkId(packet.target_network_actor_id, &cast_target) &&
        IsRunEnemyAlignedWithPlayerCastAim(
            cast_target,
            packet.position_x,
            packet.position_y,
            packet.direction_x,
            packet.direction_y,
            packet.aim_target_x,
            packet.aim_target_y);
    uintptr_t resolved_target_actor_address = 0;
    if (resolved_target_by_id) {
        resolved_target_actor_address = cast_target.actor_address;
        request.target_actor_address = resolved_target_actor_address;
        request.aim_target_x = cast_target.x;
        request.aim_target_y = cast_target.y;
    }

    const auto phase = static_cast<CastInputPhase>(packet.input_phase);
    const bool release_phase = phase == CastInputPhase::Released;
    BotCastInputState cast_input_state{};
    cast_input_state.bot_id = packet.participant_id;
    cast_input_state.active = !release_phase;
    cast_input_state.release_requested = release_phase;
    cast_input_state.cast_sequence = packet.cast_sequence;
    cast_input_state.last_update_ms = now_ms;
    cast_input_state.has_aim_target = true;
    cast_input_state.aim_target_x = request.aim_target_x;
    cast_input_state.aim_target_y = request.aim_target_y;
    cast_input_state.has_aim_angle = true;
    cast_input_state.aim_angle = packet.heading;
    cast_input_state.target_actor_address = resolved_target_actor_address;
    (void)UpdateBotCastInput(cast_input_state);

    if (release_phase) {
        input_tracker.release_seen = true;
        Log(
            "Multiplayer remote cast input release. participant_id=" +
            std::to_string(packet.participant_id) +
            " cast_sequence=" + std::to_string(packet.cast_sequence) +
            " skill_id=" + std::to_string(packet.skill_id));
        return;
    }

    request.cast_sequence = packet.cast_sequence;
    request.remote_input_controlled = true;
    if (!input_tracker.start_queued && QueueBotCast(request)) {
        input_tracker.start_queued = true;
        Log(
            "Multiplayer remote cast queued. participant_id=" +
            std::to_string(packet.participant_id) +
            " cast_sequence=" + std::to_string(packet.cast_sequence) +
            " phase=" + CastInputPhaseLabel(packet.input_phase) +
            " skill_id=" + std::to_string(packet.skill_id) +
            " target_network_actor_id=" + std::to_string(packet.target_network_actor_id) +
            " target_actor=" + HexString(request.target_actor_address) +
            " target_source=" + std::string(
                resolved_target_by_id
                    ? "network_id"
                    : (packet.target_network_actor_id != 0 ? "invalid_network_id" : "none")));
    }
}

WorldSnapshotRuntimeInfo BuildWorldSnapshotRuntimeInfo(
    const WorldSnapshotPacket& packet,
    std::uint64_t now_ms) {
    const auto actor_count = static_cast<std::uint8_t>(
        (std::min<std::uint32_t>)(packet.actor_count, kWorldSnapshotMaxActors));
    const auto scene_kind = static_cast<WorldSceneKind>(packet.scene_kind);
    WorldSnapshotRuntimeInfo snapshot;
    snapshot.valid = true;
    snapshot.authority_participant_id = packet.authority_participant_id;
    snapshot.received_ms = now_ms;
    snapshot.sequence = packet.header.sequence;
    snapshot.scene_epoch = packet.scene_epoch;
    snapshot.run_nonce = packet.run_nonce;
    snapshot.actor_total_count = packet.actor_total_count;
    snapshot.truncated = (packet.snapshot_flags & WorldSnapshotFlagTruncated) != 0;
    snapshot.scene_intent = SceneIntentFromWorldSceneKind(scene_kind);
    snapshot.actors.reserve(actor_count);

    for (std::uint8_t index = 0; index < actor_count; ++index) {
        const auto& packet_actor = packet.actors[index];
        if (packet_actor.network_actor_id == 0 ||
            packet_actor.native_type_id == 0 ||
            !std::isfinite(packet_actor.position_x) ||
            !std::isfinite(packet_actor.position_y) ||
            !std::isfinite(packet_actor.radius) ||
            packet_actor.radius < 0.0f) {
            continue;
        }

        WorldActorSnapshot actor;
        actor.network_actor_id = packet_actor.network_actor_id;
        actor.native_type_id = packet_actor.native_type_id;
        actor.enemy_type = packet_actor.enemy_type;
        actor.actor_slot = packet_actor.actor_slot;
        actor.world_slot = packet_actor.world_slot;
        actor.dead = (packet_actor.flags & WorldActorSnapshotFlagDead) != 0;
        actor.tracked_enemy = (packet_actor.flags & WorldActorSnapshotFlagTrackedEnemy) != 0;
        actor.lifecycle_owned = (packet_actor.flags & WorldActorSnapshotFlagLifecycleOwned) != 0;
        actor.run_static = (packet_actor.flags & WorldActorSnapshotFlagRunStatic) != 0;
        actor.anim_drive_state = packet_actor.anim_drive_state;
        actor.presentation_flags = packet_actor.presentation_flags;
        actor.position_x = packet_actor.position_x;
        actor.position_y = packet_actor.position_y;
        actor.radius = packet_actor.radius;
        actor.heading = std::isfinite(packet_actor.heading) ? packet_actor.heading : 0.0f;
        actor.hp = std::isfinite(packet_actor.hp) ? packet_actor.hp : 0.0f;
        actor.max_hp = std::isfinite(packet_actor.max_hp) ? packet_actor.max_hp : 0.0f;
        actor.anim_drive_state_word = packet_actor.anim_drive_state_word;
        actor.walk_cycle_primary =
            std::isfinite(packet_actor.walk_cycle_primary) ? packet_actor.walk_cycle_primary : 0.0f;
        actor.walk_cycle_secondary =
            std::isfinite(packet_actor.walk_cycle_secondary) ? packet_actor.walk_cycle_secondary : 0.0f;
        actor.render_variant_primary = packet_actor.render_variant_primary;
        actor.render_variant_secondary = packet_actor.render_variant_secondary;
        actor.render_weapon_type = packet_actor.render_weapon_type;
        actor.render_selection_byte = packet_actor.render_selection_byte;
        actor.render_variant_tertiary = packet_actor.render_variant_tertiary;
        std::memcpy(
            actor.student_visual_state.data(),
            packet_actor.student_visual_state,
            actor.student_visual_state.size());
        snapshot.actors.push_back(actor);
    }

    return snapshot;
}

void PublishWorldSnapshotRuntimeInfo(const WorldSnapshotPacket& packet, std::uint64_t now_ms) {
    UpdateRuntimeState([&](RuntimeState& state) {
        AppendWorldSnapshot(&state, BuildWorldSnapshotRuntimeInfo(packet, now_ms));
    });
}

void ApplyWorldSnapshotPacket(const WorldSnapshotPacket& packet, const sockaddr_in& from, std::uint64_t now_ms) {
    if (g_local_transport.is_host ||
        packet.authority_participant_id == 0 ||
        packet.authority_participant_id == g_local_transport.local_peer_id) {
        return;
    }

    UpsertPeerEndpoint(from, packet.authority_participant_id, now_ms);
    PublishWorldSnapshotRuntimeInfo(packet, now_ms);
}

void ApplyLootSnapshotPacket(const LootSnapshotPacket& packet, const sockaddr_in& from, std::uint64_t now_ms) {
    if (g_local_transport.is_host ||
        packet.authority_participant_id == 0 ||
        packet.authority_participant_id == g_local_transport.local_peer_id) {
        return;
    }

    const auto drop_count = static_cast<std::uint8_t>(
        (std::min<std::uint32_t>)(packet.drop_count, kLootSnapshotMaxDrops));
    UpsertPeerEndpoint(from, packet.authority_participant_id, now_ms);

    const auto scene_kind = static_cast<WorldSceneKind>(packet.scene_kind);
    UpdateRuntimeState([&](RuntimeState& state) {
        LootSnapshotRuntimeInfo snapshot;
        snapshot.valid = true;
        snapshot.authority_participant_id = packet.authority_participant_id;
        snapshot.received_ms = now_ms;
        snapshot.sequence = packet.header.sequence;
        snapshot.scene_epoch = packet.scene_epoch;
        snapshot.run_nonce = packet.run_nonce;
        snapshot.drop_total_count = packet.drop_total_count;
        snapshot.truncated = (packet.snapshot_flags & LootSnapshotFlagTruncated) != 0;
        snapshot.scene_intent = SceneIntentFromWorldSceneKind(scene_kind);
        snapshot.drops.reserve(drop_count);

        for (std::uint8_t index = 0; index < drop_count; ++index) {
            const auto& packet_drop = packet.drops[index];
            const auto drop_kind = LootDropKindFromPacketValue(packet_drop.drop_kind);
            if (packet_drop.network_drop_id == 0 ||
                packet_drop.native_type_id == 0 ||
                !std::isfinite(packet_drop.position_x) ||
                !std::isfinite(packet_drop.position_y) ||
                !std::isfinite(packet_drop.radius) ||
                packet_drop.radius < 0.0f ||
                (drop_kind == LootDropKind::Orb && !std::isfinite(packet_drop.value)) ||
                ((drop_kind == LootDropKind::Item || drop_kind == LootDropKind::Potion) &&
                    packet_drop.item_type_id == 0)) {
                continue;
            }

            LootDropSnapshot drop;
            drop.network_drop_id = packet_drop.network_drop_id;
            drop.native_type_id = packet_drop.native_type_id;
            drop.drop_kind = drop_kind;
            drop.active = (packet_drop.flags & LootDropSnapshotFlagActive) != 0;
            drop.amount = packet_drop.amount;
            drop.amount_tier = packet_drop.amount_tier;
            drop.value = packet_drop.value;
            drop.item_type_id = packet_drop.item_type_id;
            drop.item_slot = packet_drop.item_slot;
            drop.stack_count = packet_drop.stack_count;
            drop.actor_slot = packet_drop.actor_slot;
            drop.world_slot = packet_drop.world_slot;
            drop.lifetime = packet_drop.lifetime;
            drop.position_x = packet_drop.position_x;
            drop.position_y = packet_drop.position_y;
            drop.radius = packet_drop.radius;
            snapshot.drops.push_back(drop);
        }

        state.loot_snapshot = std::move(snapshot);
    });
}

bool IsEnemyDamageClaimSequenceDuplicate(const EnemyDamageClaimPacket& packet) {
    const auto it = g_local_transport.last_enemy_claim_sequence_by_participant.find(packet.participant_id);
    if (it == g_local_transport.last_enemy_claim_sequence_by_participant.end() ||
        packet.claim_sequence == 0) {
        return false;
    }
    return static_cast<std::int32_t>(packet.claim_sequence - it->second) <= 0;
}

void RememberEnemyDamageClaimSequence(const EnemyDamageClaimPacket& packet) {
    if (packet.claim_sequence != 0) {
        g_local_transport.last_enemy_claim_sequence_by_participant[packet.participant_id] =
            packet.claim_sequence;
    }
}

void SendEnemyDamageResult(
    const EnemyDamageClaimPacket& claim,
    const sockaddr_in& endpoint,
    EnemyDamageResultCode result_code,
    float authoritative_hp,
    float authoritative_max_hp,
    bool dead) {
    EnemyDamageResultPacket result{};
    result.header = MakePacketHeader(PacketKind::EnemyDamageResult, g_local_transport.next_sequence++);
    result.authority_participant_id = g_local_transport.local_peer_id;
    result.claimant_participant_id = claim.participant_id;
    result.claim_sequence = claim.claim_sequence;
    result.run_nonce = claim.run_nonce;
    result.target_network_actor_id = claim.target_network_actor_id;
    result.result_code = static_cast<std::uint8_t>(result_code);
    result.dead = dead ? 1 : 0;
    result.authoritative_hp = authoritative_hp;
    result.authoritative_max_hp = authoritative_max_hp;
    SendPacketToEndpoint(result, endpoint);
}

bool ValidateEnemyDamageClaim(
    const EnemyDamageClaimPacket& packet,
    const ParticipantInfo* participant,
    const SDModSceneActorState& target_actor,
    std::string* reject_reason) {
    auto reject = [&](const char* reason) {
        if (reject_reason != nullptr) {
            *reject_reason = reason;
        }
        return false;
    };

    if (participant == nullptr ||
        !IsRemoteParticipant(*participant) ||
        !IsNativeControlledParticipant(*participant) ||
        !participant->runtime.valid ||
        !participant->runtime.in_run ||
        participant->runtime.scene_intent.kind != ParticipantSceneIntentKind::Run) {
        return reject("participant_not_active_run");
    }
    if (packet.run_nonce != 0 &&
        participant->runtime.run_nonce != 0 &&
        packet.run_nonce != participant->runtime.run_nonce) {
        return reject("participant_run_nonce_mismatch");
    }

    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);
    if (local == nullptr ||
        !local->runtime.valid ||
        !local->runtime.in_run ||
        local->runtime.scene_intent.kind != ParticipantSceneIntentKind::Run) {
        return reject("host_not_active_run");
    }
    if (packet.run_nonce != 0 &&
        local->runtime.run_nonce != 0 &&
        packet.run_nonce != local->runtime.run_nonce) {
        return reject("host_run_nonce_mismatch");
    }
    if (!target_actor.tracked_enemy ||
        target_actor.dead ||
        !std::isfinite(target_actor.hp) ||
        !std::isfinite(target_actor.max_hp) ||
        target_actor.max_hp <= 0.0f ||
        target_actor.hp <= kEnemyDamageClaimHpEpsilon) {
        return reject("target_not_live_enemy");
    }
    if (!std::isfinite(packet.claimed_damage) ||
        !std::isfinite(packet.client_before_hp) ||
        !std::isfinite(packet.client_after_hp) ||
        packet.claimed_damage <= kEnemyDamageClaimHpEpsilon ||
        packet.client_after_hp < -kEnemyDamageClaimHpEpsilon ||
        packet.client_before_hp <= packet.client_after_hp + kEnemyDamageClaimHpEpsilon) {
        return reject("invalid_damage_numbers");
    }

    const float damage_cap =
        (std::min)(kEnemyDamageClaimAbsoluteCap, target_actor.max_hp * kEnemyDamageClaimMaxHpFactor);
    if (packet.claimed_damage > damage_cap) {
        return reject("damage_cap");
    }

    if (!std::isfinite(packet.caster_position_x) ||
        !std::isfinite(packet.caster_position_y) ||
        !std::isfinite(packet.target_position_x) ||
        !std::isfinite(packet.target_position_y)) {
        return reject("invalid_positions");
    }
    const float distance_limit_sq = kEnemyDamageClaimMaxDistance * kEnemyDamageClaimMaxDistance;
    if (DistanceSquared(
            packet.caster_position_x,
            packet.caster_position_y,
            target_actor.x,
            target_actor.y) > distance_limit_sq &&
        DistanceSquared(
            participant->runtime.position_x,
            participant->runtime.position_y,
            target_actor.x,
            target_actor.y) > distance_limit_sq) {
        return reject("distance_sanity");
    }
    const float target_drift_limit_sq =
        kEnemyDamageClaimMaxTargetDrift * kEnemyDamageClaimMaxTargetDrift;
    if (DistanceSquared(
            packet.target_position_x,
            packet.target_position_y,
            target_actor.x,
            target_actor.y) > target_drift_limit_sq) {
        return reject("target_position_drift");
    }

    return true;
}

void ApplyEnemyDamageClaimPacket(
    const EnemyDamageClaimPacket& packet,
    const sockaddr_in& from,
    std::uint64_t now_ms) {
    if (!g_local_transport.is_host ||
        packet.participant_id == 0 ||
        packet.participant_id == g_local_transport.local_peer_id ||
        packet.target_network_actor_id == 0) {
        return;
    }

    UpsertPeerEndpoint(from, packet.participant_id, now_ms);
    if (IsEnemyDamageClaimSequenceDuplicate(packet)) {
        return;
    }

    const auto runtime_state = SnapshotRuntimeState();
    const auto* participant = FindParticipant(runtime_state, packet.participant_id);

    SDModSceneActorState target_actor;
    if (!TryFindHostRunEnemyByNetworkId(packet.target_network_actor_id, &target_actor)) {
        SendEnemyDamageResult(packet, from, EnemyDamageResultCode::Rejected, 0.0f, 0.0f, true);
        RememberEnemyDamageClaimSequence(packet);
        Log(
            "Multiplayer enemy damage claim rejected. reason=target_not_found participant_id=" +
            std::to_string(packet.participant_id) +
            " target_network_actor_id=" + std::to_string(packet.target_network_actor_id));
        return;
    }

    std::string reject_reason;
    if (!ValidateEnemyDamageClaim(packet, participant, target_actor, &reject_reason)) {
        SendEnemyDamageResult(
            packet,
            from,
            EnemyDamageResultCode::Rejected,
            ClampEnemyHp(target_actor.hp, target_actor.max_hp),
            target_actor.max_hp,
            target_actor.dead);
        RememberEnemyDamageClaimSequence(packet);
        Log(
            "Multiplayer enemy damage claim rejected. reason=" + reject_reason +
            " participant_id=" + std::to_string(packet.participant_id) +
            " target_network_actor_id=" + std::to_string(packet.target_network_actor_id) +
            " damage=" + std::to_string(packet.claimed_damage) +
            " host_hp=" + std::to_string(target_actor.hp) +
            " client_after_hp=" + std::to_string(packet.client_after_hp));
        return;
    }

    const float current_hp = ClampEnemyHp(target_actor.hp, target_actor.max_hp);
    const float claimed_after_hp = ClampEnemyHp(packet.client_after_hp, target_actor.max_hp);
    const float accepted_hp = (std::min)(current_hp, claimed_after_hp);
    const bool wrote = TryWriteRunEnemyHealth(
        target_actor.actor_address,
        accepted_hp,
        target_actor.max_hp);
    std::uint32_t death_exception_code = 0;
    bool death_called = false;
    if (wrote && accepted_hp <= kEnemyDamageClaimHpEpsilon) {
        death_called = sdmod::TryTriggerRunEnemyDeath(target_actor.actor_address, &death_exception_code);
        if (death_called) {
            RecordRecentRunEnemyDeathSnapshot(
                packet.target_network_actor_id,
                target_actor,
                now_ms);
        }
    }

    RememberEnemyDamageClaimSequence(packet);
    SendEnemyDamageResult(
        packet,
        from,
        wrote ? EnemyDamageResultCode::Accepted : EnemyDamageResultCode::Rejected,
        wrote ? accepted_hp : current_hp,
        target_actor.max_hp,
        wrote ? accepted_hp <= kEnemyDamageClaimHpEpsilon : target_actor.dead);

    Log(
        "Multiplayer enemy damage claim " + std::string(wrote ? "accepted" : "rejected") +
        ". participant_id=" + std::to_string(packet.participant_id) +
        " target_network_actor_id=" + std::to_string(packet.target_network_actor_id) +
        " damage=" + std::to_string(packet.claimed_damage) +
        " before_hp=" + std::to_string(current_hp) +
        " after_hp=" + std::to_string(wrote ? accepted_hp : current_hp) +
        " lethal=" + std::to_string(accepted_hp <= kEnemyDamageClaimHpEpsilon ? 1 : 0) +
        " death_called=" + std::to_string(death_called ? 1 : 0) +
        " death_seh=" + HexString(static_cast<uintptr_t>(death_exception_code)));
}

void PublishLootPickupResultRuntimeInfo(
    const LootPickupResultPacket& packet,
    std::uint64_t now_ms) {
    UpdateRuntimeState([&](RuntimeState& state) {
        LootPickupResultRuntimeInfo result;
        result.valid = true;
        result.authority_participant_id = packet.authority_participant_id;
        result.participant_id = packet.participant_id;
        result.received_ms = now_ms;
        result.sequence = packet.header.sequence;
        result.request_sequence = packet.request_sequence;
        result.run_nonce = packet.run_nonce;
        result.network_drop_id = packet.network_drop_id;
        result.result_code = LootPickupResultCodeFromPacketValue(packet.result_code);
        result.drop_kind = LootDropKindFromPacketValue(packet.drop_kind);
        result.amount = packet.amount;
        result.resulting_gold = packet.resulting_gold;
        result.gold_revision = packet.gold_revision;
        result.resource_kind = packet.resource_kind;
        result.resource_delta = packet.resource_delta;
        result.resulting_life_current = packet.resulting_life_current;
        result.resulting_life_max = packet.resulting_life_max;
        result.resulting_mana_current = packet.resulting_mana_current;
        result.resulting_mana_max = packet.resulting_mana_max;
        result.item_type_id = packet.item_type_id;
        result.item_slot = packet.item_slot;
        result.stack_count = packet.stack_count;
        result.inventory_revision = packet.inventory_revision;
        state.last_loot_pickup_result = result;

        if (result.result_code != LootPickupResultCode::Accepted) {
            return;
        }

        ParticipantInfo* participant = nullptr;
        if (packet.participant_id == g_local_transport.local_peer_id) {
            participant = FindLocalParticipant(state);
        } else {
            participant = FindParticipant(state, packet.participant_id);
            if (participant == nullptr) {
                participant = UpsertRemoteParticipant(
                    state,
                    packet.participant_id,
                    ParticipantControllerKind::Native);
            }
        }
        if (participant == nullptr) {
            return;
        }

        if (result.drop_kind == LootDropKind::Gold) {
            const bool should_apply =
                !participant->owned_progression.initialized ||
                packet.gold_revision >= participant->owned_progression.gold_revision;
            if (!should_apply) {
                return;
            }
            participant->owned_progression.initialized = true;
            participant->owned_progression.gold = packet.resulting_gold;
            participant->owned_progression.gold_revision = packet.gold_revision;
            return;
        }

        if (result.drop_kind == LootDropKind::Orb) {
            LootOrbResourceKind resource_kind = LootOrbResourceKind::Health;
            if (!TryResolveLootOrbResourceKind(packet.resource_kind, &resource_kind)) {
                return;
            }
            participant->runtime.valid = true;
            if (resource_kind == LootOrbResourceKind::Health &&
                std::isfinite(packet.resulting_life_current) &&
                std::isfinite(packet.resulting_life_max) &&
                packet.resulting_life_max > 0.0f) {
                participant->runtime.life_max = packet.resulting_life_max;
                participant->runtime.life_current =
                    (std::clamp)(packet.resulting_life_current, 0.0f, packet.resulting_life_max);
            } else if (resource_kind == LootOrbResourceKind::Mana &&
                std::isfinite(packet.resulting_mana_current) &&
                std::isfinite(packet.resulting_mana_max) &&
                packet.resulting_mana_max > 0.0f) {
                participant->runtime.mana_max = packet.resulting_mana_max;
                participant->runtime.mana_current =
                    (std::clamp)(packet.resulting_mana_current, 0.0f, packet.resulting_mana_max);
            }
            return;
        }

        if (result.drop_kind == LootDropKind::Item || result.drop_kind == LootDropKind::Potion) {
            if (packet.item_type_id == 0 ||
                packet.inventory_revision <= participant->owned_progression.inventory_revision) {
                return;
            }
            participant->owned_progression.initialized = true;
            participant->owned_progression.inventory_host_authoritative = true;
            if (ApplyOwnedInventoryLootItem(
                    packet.item_type_id,
                    packet.item_slot,
                    packet.stack_count,
                    &participant->owned_progression)) {
                participant->owned_progression.inventory_revision =
                    (std::max)(
                        participant->owned_progression.inventory_revision,
                        packet.inventory_revision);
            }
        }
    });
}

LootPickupResultPayload BuildLootPickupResultPayloadFromParticipant(const ParticipantInfo* participant) {
    LootPickupResultPayload payload;
    if (participant == nullptr) {
        return payload;
    }
    payload.resulting_gold = participant->owned_progression.gold;
    payload.gold_revision = participant->owned_progression.gold_revision;
    payload.resulting_life_current = participant->runtime.life_current;
    payload.resulting_life_max = participant->runtime.life_max;
    payload.resulting_mana_current = participant->runtime.mana_current;
    payload.resulting_mana_max = participant->runtime.mana_max;
    payload.inventory_revision = participant->owned_progression.inventory_revision;
    return payload;
}

bool TryBuildAcceptedOrbLootPickupPayload(
    const LootDropSnapshotPacketState& drop,
    const ParticipantInfo* participant,
    LootPickupResultPayload* payload) {
    if (participant == nullptr || payload == nullptr) {
        return false;
    }

    LootOrbResourceKind resource_kind = LootOrbResourceKind::Health;
    if (!TryResolveLootOrbResourceKind(drop.amount_tier, &resource_kind) ||
        !participant->runtime.valid ||
        !std::isfinite(participant->runtime.life_current) ||
        !std::isfinite(participant->runtime.life_max) ||
        !std::isfinite(participant->runtime.mana_current) ||
        !std::isfinite(participant->runtime.mana_max) ||
        participant->runtime.life_max <= 0.0f ||
        participant->runtime.mana_max <= 0.0f) {
        return false;
    }

    const float resource_delta = ComputeLootOrbResourceDelta(drop.amount_tier, drop.value);
    if (resource_delta <= kLootPickupResourceEpsilon) {
        return false;
    }

    *payload = BuildLootPickupResultPayloadFromParticipant(participant);
    payload->amount = RoundRewardAmountToInt(resource_delta);
    payload->resource_kind = drop.amount_tier;
    payload->resource_delta = resource_delta;
    if (resource_kind == LootOrbResourceKind::Health) {
        payload->resulting_life_current =
            (std::min)(participant->runtime.life_current + resource_delta, participant->runtime.life_max);
    } else {
        payload->resulting_mana_current =
            (std::min)(participant->runtime.mana_current + resource_delta, participant->runtime.mana_max);
    }
    return true;
}

bool TryBuildAcceptedItemLootPickupPayload(
    const LootDropSnapshotPacketState& drop,
    const ParticipantInfo* participant,
    LootPickupResultPayload* payload) {
    if (participant == nullptr || payload == nullptr || drop.item_type_id == 0) {
        return false;
    }

    *payload = BuildLootPickupResultPayloadFromParticipant(participant);
    payload->amount = drop.item_type_id == kPotionItemTypeId
        ? (std::max)(drop.stack_count, 1)
        : 1;
    payload->item_type_id = drop.item_type_id;
    payload->item_slot = drop.item_slot;
    payload->stack_count = NormalizeInventoryLootStackCount(drop.item_type_id, drop.stack_count);
    return true;
}

void SendLootPickupResult(
    const LootPickupRequestPacket& request,
    const sockaddr_in& endpoint,
    LootPickupResultCode result_code,
    LootDropKind drop_kind,
    const LootPickupResultPayload& payload) {
    LootPickupResultPacket result{};
    result.header = MakePacketHeader(PacketKind::LootPickupResult, g_local_transport.next_sequence++);
    result.authority_participant_id = g_local_transport.local_peer_id;
    result.participant_id = request.participant_id;
    result.request_sequence = request.request_sequence;
    result.run_nonce = request.run_nonce;
    result.network_drop_id = request.network_drop_id;
    result.result_code = static_cast<std::uint8_t>(result_code);
    result.drop_kind = static_cast<std::uint8_t>(drop_kind);
    result.amount = payload.amount;
    result.resulting_gold = payload.resulting_gold;
    result.gold_revision = payload.gold_revision;
    result.resource_kind = payload.resource_kind;
    result.resource_delta = payload.resource_delta;
    result.resulting_life_current = payload.resulting_life_current;
    result.resulting_life_max = payload.resulting_life_max;
    result.resulting_mana_current = payload.resulting_mana_current;
    result.resulting_mana_max = payload.resulting_mana_max;
    result.item_type_id = payload.item_type_id;
    result.item_slot = payload.item_slot;
    result.stack_count = payload.stack_count;
    result.inventory_revision = payload.inventory_revision;

    SendPacketToEndpoint(result, endpoint);
    RelayPacketToPeers(result, endpoint);
    PublishLootPickupResultRuntimeInfo(
        result,
        static_cast<std::uint64_t>(GetTickCount64()));
}

bool ValidateLootPickupRequest(
    const LootPickupRequestPacket& packet,
    const ParticipantInfo* participant,
    const LootDropSnapshotPacketState& drop,
    std::string* reject_reason,
    LootPickupResultCode* result_code) {
    auto reject = [&](const char* reason, LootPickupResultCode code) {
        if (reject_reason != nullptr) {
            *reject_reason = reason;
        }
        if (result_code != nullptr) {
            *result_code = code;
        }
        return false;
    };

    if (participant == nullptr ||
        !IsRemoteParticipant(*participant) ||
        !IsNativeControlledParticipant(*participant) ||
        !participant->runtime.valid ||
        !participant->runtime.in_run ||
        participant->runtime.scene_intent.kind != ParticipantSceneIntentKind::Run) {
        return reject("participant_not_active_run", LootPickupResultCode::Rejected);
    }
    if (packet.run_nonce != 0 &&
        participant->runtime.run_nonce != 0 &&
        packet.run_nonce != participant->runtime.run_nonce) {
        return reject("participant_run_nonce_mismatch", LootPickupResultCode::WrongRun);
    }

    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);
    if (local == nullptr ||
        !local->runtime.valid ||
        !local->runtime.in_run ||
        local->runtime.scene_intent.kind != ParticipantSceneIntentKind::Run) {
        return reject("host_not_active_run", LootPickupResultCode::WrongRun);
    }
    if (packet.run_nonce != 0 &&
        local->runtime.run_nonce != 0 &&
        packet.run_nonce != local->runtime.run_nonce) {
        return reject("host_run_nonce_mismatch", LootPickupResultCode::WrongRun);
    }

    const auto drop_kind = LootDropKindFromPacketValue(drop.drop_kind);
    if (drop_kind != LootDropKind::Gold &&
        drop_kind != LootDropKind::Orb &&
        drop_kind != LootDropKind::Item &&
        drop_kind != LootDropKind::Potion) {
        return reject("unsupported_drop_kind", LootPickupResultCode::Unsupported);
    }
    if (g_local_transport.accepted_loot_pickup_drop_ids.find(packet.network_drop_id) !=
        g_local_transport.accepted_loot_pickup_drop_ids.end()) {
        return reject("drop_already_gone", LootPickupResultCode::AlreadyGone);
    }
    if ((drop.flags & LootDropSnapshotFlagActive) == 0) {
        return reject("drop_inactive", LootPickupResultCode::AlreadyGone);
    }
    if (drop_kind == LootDropKind::Gold && drop.amount <= 0) {
        return reject("drop_empty", LootPickupResultCode::AlreadyGone);
    }
    if (drop_kind == LootDropKind::Orb) {
        LootOrbResourceKind resource_kind = LootOrbResourceKind::Health;
        if (!TryResolveLootOrbResourceKind(drop.amount_tier, &resource_kind)) {
            return reject("unsupported_orb_resource_kind", LootPickupResultCode::Unsupported);
        }
        if (ComputeLootOrbResourceDelta(drop.amount_tier, drop.value) <= kLootPickupResourceEpsilon) {
            return reject("orb_empty", LootPickupResultCode::AlreadyGone);
        }
    }
    if (drop_kind == LootDropKind::Item || drop_kind == LootDropKind::Potion) {
        if (drop.item_type_id == 0) {
            return reject("item_missing_type", LootPickupResultCode::AlreadyGone);
        }
        if (drop_kind == LootDropKind::Potion && drop.item_type_id != kPotionItemTypeId) {
            return reject("potion_type_mismatch", LootPickupResultCode::Rejected);
        }
        if (drop_kind == LootDropKind::Item && drop.item_type_id == kPotionItemTypeId) {
            return reject("item_type_mismatch", LootPickupResultCode::Rejected);
        }
    }
    if (!std::isfinite(packet.requester_position_x) ||
        !std::isfinite(packet.requester_position_y) ||
        !std::isfinite(packet.drop_position_x) ||
        !std::isfinite(packet.drop_position_y) ||
        !std::isfinite(drop.position_x) ||
        !std::isfinite(drop.position_y) ||
        (drop_kind == LootDropKind::Orb && !std::isfinite(drop.value))) {
        return reject("invalid_positions", LootPickupResultCode::Rejected);
    }

    const float range_limit =
        kLootPickupMaxDistance + (std::isfinite(drop.radius) && drop.radius > 0.0f ? drop.radius : 0.0f);
    const float range_limit_sq = range_limit * range_limit;
    const bool client_position_in_range =
        DistanceSquared(
            packet.requester_position_x,
            packet.requester_position_y,
            drop.position_x,
            drop.position_y) <= range_limit_sq;
    const bool host_observed_position_in_range =
        DistanceSquared(
            participant->runtime.position_x,
            participant->runtime.position_y,
            drop.position_x,
            drop.position_y) <= range_limit_sq;
    if (!client_position_in_range && !host_observed_position_in_range) {
        return reject("distance_sanity", LootPickupResultCode::OutOfRange);
    }

    const float drift_limit_sq = kLootPickupDropDriftMaxDistance * kLootPickupDropDriftMaxDistance;
    if (DistanceSquared(
            packet.drop_position_x,
            packet.drop_position_y,
            drop.position_x,
            drop.position_y) > drift_limit_sq) {
        return reject("drop_position_drift", LootPickupResultCode::Rejected);
    }

    if (result_code != nullptr) {
        *result_code = LootPickupResultCode::Accepted;
    }
    return true;
}

void ApplyLootPickupRequestPacket(
    const LootPickupRequestPacket& packet,
    const sockaddr_in& from,
    std::uint64_t now_ms) {
    if (!g_local_transport.is_host ||
        packet.participant_id == 0 ||
        packet.participant_id == g_local_transport.local_peer_id ||
        packet.network_drop_id == 0 ||
        packet.request_sequence == 0) {
        return;
    }

    UpsertPeerEndpoint(from, packet.participant_id, now_ms);
    if (IsLootPickupRequestSequenceDuplicate(packet)) {
        return;
    }

    const auto runtime_state = SnapshotRuntimeState();
    const auto* participant = FindParticipant(runtime_state, packet.participant_id);

    SDModSceneActorState actor;
    LootDropSnapshotPacketState drop{};
    if (!TryFindHostRunLootDropByNetworkId(packet.network_drop_id, &actor, &drop)) {
        LootPickupResultPayload payload = BuildLootPickupResultPayloadFromParticipant(participant);
        SendLootPickupResult(
            packet,
            from,
            LootPickupResultCode::AlreadyGone,
            LootDropKind::Unknown,
            payload);
        RememberLootPickupRequestSequence(packet);
        Log(
            "Multiplayer loot pickup rejected. reason=drop_not_found participant_id=" +
            std::to_string(packet.participant_id) +
            " network_drop_id=" + std::to_string(packet.network_drop_id));
        return;
    }

    std::string reject_reason;
    LootPickupResultCode result_code = LootPickupResultCode::Rejected;
    if (!ValidateLootPickupRequest(packet, participant, drop, &reject_reason, &result_code)) {
        LootPickupResultPayload payload = BuildLootPickupResultPayloadFromParticipant(participant);
        SendLootPickupResult(
            packet,
            from,
            result_code,
            LootDropKindFromPacketValue(drop.drop_kind),
            payload);
        RememberLootPickupRequestSequence(packet);
        Log(
            "Multiplayer loot pickup rejected. reason=" + reject_reason +
            " participant_id=" + std::to_string(packet.participant_id) +
            " network_drop_id=" + std::to_string(packet.network_drop_id));
        return;
    }

    const auto drop_kind = LootDropKindFromPacketValue(drop.drop_kind);
    LootPickupResultPayload payload = BuildLootPickupResultPayloadFromParticipant(participant);
    bool payload_ready = false;
    if (drop_kind == LootDropKind::Gold) {
        payload.amount = drop.amount;
        payload_ready = drop.amount > 0;
    } else if (drop_kind == LootDropKind::Orb) {
        payload_ready = TryBuildAcceptedOrbLootPickupPayload(drop, participant, &payload);
    } else if (drop_kind == LootDropKind::Item || drop_kind == LootDropKind::Potion) {
        payload_ready = TryBuildAcceptedItemLootPickupPayload(drop, participant, &payload);
    }

    const bool deactivated = payload_ready && TryDeactivateHostLootDrop(actor.actor_address, drop_kind);
    if (deactivated) {
        g_local_transport.accepted_loot_pickup_drop_ids.insert(packet.network_drop_id);
    }

    UpdateRuntimeState([&](RuntimeState& state) {
        if (!deactivated) {
            return;
        }
        auto* mutable_participant = FindParticipant(state, packet.participant_id);
        if (mutable_participant == nullptr) {
            return;
        }

        if (drop_kind == LootDropKind::Gold) {
            mutable_participant->owned_progression.initialized = true;
            mutable_participant->owned_progression.gold += drop.amount;
            mutable_participant->owned_progression.gold_revision += 1;
            payload.resulting_gold = mutable_participant->owned_progression.gold;
            payload.gold_revision = mutable_participant->owned_progression.gold_revision;
            return;
        }

        if (drop_kind == LootDropKind::Orb) {
            LootOrbResourceKind resource_kind = LootOrbResourceKind::Health;
            if (!TryResolveLootOrbResourceKind(payload.resource_kind, &resource_kind)) {
                return;
            }
            mutable_participant->runtime.valid = true;
            if (resource_kind == LootOrbResourceKind::Health) {
                mutable_participant->runtime.life_current = payload.resulting_life_current;
                mutable_participant->runtime.life_max = payload.resulting_life_max;
            } else {
                mutable_participant->runtime.mana_current = payload.resulting_mana_current;
                mutable_participant->runtime.mana_max = payload.resulting_mana_max;
            }
            return;
        }

        if (drop_kind == LootDropKind::Item || drop_kind == LootDropKind::Potion) {
            mutable_participant->owned_progression.initialized = true;
            mutable_participant->owned_progression.inventory_host_authoritative = true;
            if (ApplyOwnedInventoryLootItem(
                    payload.item_type_id,
                    payload.item_slot,
                    payload.stack_count,
                    &mutable_participant->owned_progression)) {
                payload.inventory_revision =
                    mutable_participant->owned_progression.inventory_revision;
            }
        }
    });

    RememberLootPickupRequestSequence(packet);
    SendLootPickupResult(
        packet,
        from,
        deactivated ? LootPickupResultCode::Accepted : LootPickupResultCode::Rejected,
        drop_kind,
        deactivated ? payload : BuildLootPickupResultPayloadFromParticipant(participant));

    Log(
        "Multiplayer loot pickup " + std::string(deactivated ? "accepted" : "rejected") +
        ". participant_id=" + std::to_string(packet.participant_id) +
        " network_drop_id=" + std::to_string(packet.network_drop_id) +
        " kind=" + LootDropKindLabel(drop_kind) +
        " amount=" + std::to_string(deactivated ? payload.amount : 0) +
        " resulting_gold=" + std::to_string(payload.resulting_gold) +
        " gold_revision=" + std::to_string(payload.gold_revision) +
        " resource_kind=" + std::to_string(payload.resource_kind) +
        " resource_delta=" + std::to_string(deactivated ? payload.resource_delta : 0.0f) +
        " resulting_life=" + std::to_string(payload.resulting_life_current) + "/" +
        std::to_string(payload.resulting_life_max) +
        " resulting_mana=" + std::to_string(payload.resulting_mana_current) + "/" +
        std::to_string(payload.resulting_mana_max) +
        " item_type_id=" + HexString(static_cast<uintptr_t>(payload.item_type_id)) +
        " item_slot=" + std::to_string(payload.item_slot) +
        " stack_count=" + std::to_string(payload.stack_count) +
        " inventory_revision=" + std::to_string(payload.inventory_revision) +
        " deactivated=" + std::to_string(deactivated ? 1 : 0));
}

void ApplyLootPickupResultPacket(
    const LootPickupResultPacket& packet,
    const sockaddr_in& from,
    std::uint64_t now_ms) {
    if (packet.authority_participant_id == 0 ||
        packet.authority_participant_id == g_local_transport.local_peer_id ||
        packet.participant_id == 0 ||
        packet.network_drop_id == 0 ||
        packet.request_sequence == 0) {
        return;
    }

    UpsertPeerEndpoint(from, packet.authority_participant_id, now_ms);
    const auto result_code = LootPickupResultCodeFromPacketValue(packet.result_code);
    const auto drop_kind = LootDropKindFromPacketValue(packet.drop_kind);
    if (result_code == LootPickupResultCode::Accepted &&
        packet.participant_id == g_local_transport.local_peer_id &&
        drop_kind == LootDropKind::Gold) {
        if (!TryWriteLocalGlobalGold(packet.resulting_gold)) {
            Log(
                "Multiplayer loot pickup result accepted but local gold write failed. resulting_gold=" +
                std::to_string(packet.resulting_gold) +
                " network_drop_id=" + std::to_string(packet.network_drop_id));
        }
    }
    if (result_code == LootPickupResultCode::Accepted &&
        packet.participant_id == g_local_transport.local_peer_id &&
        drop_kind == LootDropKind::Orb) {
        if (!TryWriteLocalPlayerOrbResource(
                packet.resource_kind,
                packet.resulting_life_current,
                packet.resulting_life_max,
                packet.resulting_mana_current,
                packet.resulting_mana_max)) {
            Log(
                "Multiplayer loot pickup result accepted but local vitals write failed. resource_delta=" +
                std::to_string(packet.resource_delta) +
                " network_drop_id=" + std::to_string(packet.network_drop_id));
        }
    }

    PublishLootPickupResultRuntimeInfo(packet, now_ms);
    Log(
        "Multiplayer loot pickup result applied. authority_participant_id=" +
        std::to_string(packet.authority_participant_id) +
        " participant_id=" + std::to_string(packet.participant_id) +
        " request_sequence=" + std::to_string(packet.request_sequence) +
        " network_drop_id=" + std::to_string(packet.network_drop_id) +
        " result=" + LootPickupResultCodeLabel(result_code) +
        " kind=" + LootDropKindLabel(drop_kind) +
        " amount=" + std::to_string(packet.amount) +
        " resulting_gold=" + std::to_string(packet.resulting_gold) +
        " gold_revision=" + std::to_string(packet.gold_revision) +
        " resource_kind=" + std::to_string(packet.resource_kind) +
        " resource_delta=" + std::to_string(packet.resource_delta) +
        " item_type_id=" + HexString(static_cast<uintptr_t>(packet.item_type_id)) +
        " item_slot=" + std::to_string(packet.item_slot) +
        " stack_count=" + std::to_string(packet.stack_count) +
        " inventory_revision=" + std::to_string(packet.inventory_revision));
}

void ReceivePackets(std::uint64_t now_ms) {
    for (int packet_index = 0; packet_index < kMaxPacketsPerTick; ++packet_index) {
        std::array<char, sizeof(WorldSnapshotPacket)> packet_buffer{};
        sockaddr_in from{};
        int from_length = sizeof(from);
        const int received = recvfrom(
            g_local_transport.socket_handle,
            packet_buffer.data(),
            static_cast<int>(packet_buffer.size()),
            0,
            reinterpret_cast<sockaddr*>(&from),
            &from_length);
        if (received == SOCKET_ERROR) {
            const int error = WSAGetLastError();
            if (error == WSAEWOULDBLOCK) {
                return;
            }
            return;
        }

        if (received < static_cast<int>(sizeof(PacketHeader))) {
            continue;
        }

        PacketHeader header{};
        std::memcpy(&header, packet_buffer.data(), sizeof(header));
        if (!IsValidPacketHeader(header)) {
            continue;
        }

        const auto kind = static_cast<PacketKind>(header.kind);
        if (kind == PacketKind::State && received == static_cast<int>(sizeof(StatePacket))) {
            StatePacket packet{};
            std::memcpy(&packet, packet_buffer.data(), sizeof(packet));
            if (!IsValidHeader(packet.header, PacketKind::State)) {
                continue;
            }
            g_local_transport.packets_received += 1;
            ApplyRemoteStatePacket(packet, from, now_ms);
            continue;
        }

        if (kind == PacketKind::Cast && received == static_cast<int>(sizeof(CastPacket))) {
            CastPacket packet{};
            std::memcpy(&packet, packet_buffer.data(), sizeof(packet));
            if (!IsValidHeader(packet.header, PacketKind::Cast)) {
                continue;
            }
            g_local_transport.packets_received += 1;
            ApplyRemoteCastPacket(packet, from, now_ms);
            continue;
        }

        if (kind == PacketKind::WorldSnapshot && received == static_cast<int>(sizeof(WorldSnapshotPacket))) {
            WorldSnapshotPacket packet{};
            std::memcpy(&packet, packet_buffer.data(), sizeof(packet));
            if (!IsValidHeader(packet.header, PacketKind::WorldSnapshot)) {
                continue;
            }
            g_local_transport.packets_received += 1;
            ApplyWorldSnapshotPacket(packet, from, now_ms);
            continue;
        }

        if (kind == PacketKind::LootSnapshot && received == static_cast<int>(sizeof(LootSnapshotPacket))) {
            LootSnapshotPacket packet{};
            std::memcpy(&packet, packet_buffer.data(), sizeof(packet));
            if (!IsValidHeader(packet.header, PacketKind::LootSnapshot)) {
                continue;
            }
            g_local_transport.packets_received += 1;
            ApplyLootSnapshotPacket(packet, from, now_ms);
            continue;
        }

        if (kind == PacketKind::EnemyDamageClaim && received == static_cast<int>(sizeof(EnemyDamageClaimPacket))) {
            EnemyDamageClaimPacket packet{};
            std::memcpy(&packet, packet_buffer.data(), sizeof(packet));
            if (!IsValidHeader(packet.header, PacketKind::EnemyDamageClaim)) {
                continue;
            }
            g_local_transport.packets_received += 1;
            ApplyEnemyDamageClaimPacket(packet, from, now_ms);
            continue;
        }

        if (kind == PacketKind::EnemyDamageResult && received == static_cast<int>(sizeof(EnemyDamageResultPacket))) {
            EnemyDamageResultPacket packet{};
            std::memcpy(&packet, packet_buffer.data(), sizeof(packet));
            if (!IsValidHeader(packet.header, PacketKind::EnemyDamageResult)) {
                continue;
            }
            g_local_transport.packets_received += 1;
            ApplyEnemyDamageCorrection(packet);
            continue;
        }

        if (kind == PacketKind::LootPickupRequest && received == static_cast<int>(sizeof(LootPickupRequestPacket))) {
            LootPickupRequestPacket packet{};
            std::memcpy(&packet, packet_buffer.data(), sizeof(packet));
            if (!IsValidHeader(packet.header, PacketKind::LootPickupRequest)) {
                continue;
            }
            g_local_transport.packets_received += 1;
            ApplyLootPickupRequestPacket(packet, from, now_ms);
            continue;
        }

        if (kind == PacketKind::LootPickupResult && received == static_cast<int>(sizeof(LootPickupResultPacket))) {
            LootPickupResultPacket packet{};
            std::memcpy(&packet, packet_buffer.data(), sizeof(packet));
            if (!IsValidHeader(packet.header, PacketKind::LootPickupResult)) {
                continue;
            }
            g_local_transport.packets_received += 1;
            ApplyLootPickupResultPacket(packet, from, now_ms);
        }
    }
}

void PublishLocalTransportRuntimeState() {
    UpdateRuntimeState([](RuntimeState& state) {
        state.transport_ready = true;
        state.session_status = SessionStatus::Ready;
        state.session_transport = SessionTransportKind::LocalUdp;
        std::ostringstream status;
        status << "Local UDP multiplayer transport ready. role="
               << (g_local_transport.is_host ? "host" : "client")
               << " local_port=" << g_local_transport.local_port
               << " participant_id=" << g_local_transport.local_peer_id
               << " peers=" << g_local_transport.peers.size()
               << " sent=" << g_local_transport.packets_sent
               << " received=" << g_local_transport.packets_received;
        state.status_text = status.str();
    });
}

}  // namespace

bool InitializeLocalTransport() {
    if (!ConfigureLocalTransport()) {
        return true;
    }

    WSADATA data{};
    if (WSAStartup(MAKEWORD(2, 2), &data) != 0) {
        Log("Multiplayer local UDP: WSAStartup failed.");
        g_local_transport = LocalTransportState{};
        return false;
    }
    g_local_transport.winsock_initialized = true;

    g_local_transport.socket_handle = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (g_local_transport.socket_handle == INVALID_SOCKET) {
        Log("Multiplayer local UDP: socket creation failed.");
        ShutdownLocalTransport();
        return false;
    }

    u_long nonblocking = 1;
    if (ioctlsocket(g_local_transport.socket_handle, FIONBIO, &nonblocking) != 0) {
        Log("Multiplayer local UDP: failed to set non-blocking mode.");
        ShutdownLocalTransport();
        return false;
    }

    sockaddr_in bind_address{};
    bind_address.sin_family = AF_INET;
    bind_address.sin_addr.s_addr = htonl(INADDR_ANY);
    bind_address.sin_port = htons(g_local_transport.local_port);
    if (bind(
            g_local_transport.socket_handle,
            reinterpret_cast<const sockaddr*>(&bind_address),
            sizeof(bind_address)) != 0) {
        Log("Multiplayer local UDP: bind failed on port " + std::to_string(g_local_transport.local_port) + ".");
        ShutdownLocalTransport();
        return false;
    }

    g_local_transport.initialized = true;
    std::ostringstream message;
    message << "Multiplayer local UDP transport initialized. role="
            << (g_local_transport.is_host ? "host" : "client")
            << " local_port=" << g_local_transport.local_port
            << " remote=" << g_local_transport.remote_host << ":" << g_local_transport.remote_port
            << " participant_id=" << g_local_transport.local_peer_id;
    Log(message.str());
    return true;
}

void ShutdownLocalTransport() {
    if (g_local_transport.socket_handle != INVALID_SOCKET) {
        closesocket(g_local_transport.socket_handle);
    }
    if (g_local_transport.winsock_initialized) {
        WSACleanup();
    }
    g_local_transport = LocalTransportState{};
    std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
    g_queued_local_cast_events.clear();
    g_queued_local_enemy_damage_claims.clear();
    g_queued_local_loot_pickup_requests.clear();
    g_next_local_loot_pickup_request_sequence = 1;
}

void TickLocalTransport(std::uint64_t now_ms) {
    if (!g_local_transport.initialized) {
        return;
    }

    RefreshLocalParticipantFromGameState();
    ReceivePackets(now_ms);
    SendLocalState(now_ms);
    SendActiveLocalCastInput(now_ms);
    SendQueuedCastEvents(now_ms);
    SendLocalEnemyDamageClaims();
    SendQueuedLootPickupRequests();
    SendWorldSnapshot(now_ms);
    SendLootSnapshot(now_ms);
    PublishLocalTransportRuntimeState();
}

bool IsLocalTransportEnabled() {
    return g_local_transport.initialized;
}

bool IsLocalTransportHost() {
    return g_local_transport.initialized && g_local_transport.is_host;
}

bool IsLocalTransportClient() {
    return g_local_transport.initialized && !g_local_transport.is_host;
}

std::uint64_t GetLocalTransportParticipantId() {
    return g_local_transport.initialized ? g_local_transport.local_peer_id : 0;
}

std::uint64_t QueueLocalSpellCastEvent(
    std::int32_t skill_id,
    float position_x,
    float position_y,
    float direction_x,
    float direction_y,
    std::uint64_t target_network_actor_id,
    uintptr_t target_actor_address,
    std::uint32_t hold_frames,
    bool has_aim_target,
    float aim_target_x,
    float aim_target_y) {
    if (skill_id < 0 ||
        !std::isfinite(position_x) ||
        !std::isfinite(position_y) ||
        !std::isfinite(direction_x) ||
        !std::isfinite(direction_y)) {
        return 0;
    }
    if (has_aim_target &&
        !IsUsableLocalCastAimTarget(position_x, position_y, aim_target_x, aim_target_y)) {
        has_aim_target = false;
        aim_target_x = 0.0f;
        aim_target_y = 0.0f;
    }

    std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
    constexpr std::size_t kMaxQueuedLocalCastEvents = 16;
    if (g_queued_local_cast_events.size() >= kMaxQueuedLocalCastEvents) {
        g_queued_local_cast_events.erase(g_queued_local_cast_events.begin());
    }
    QueuedLocalCastEvent event;
    event.native_queue_id = g_next_local_cast_event_id++;
    if (g_next_local_cast_event_id == 0) {
        g_next_local_cast_event_id = 1;
    }
    event.skill_id = skill_id;
    event.target_network_actor_id = target_network_actor_id;
    event.target_actor_address = target_actor_address;
    if (hold_frames > 0) {
        constexpr std::uint64_t kApproximateFrameMs = 16;
        event.minimum_hold_until_ms =
            static_cast<std::uint64_t>(GetTickCount64()) +
            static_cast<std::uint64_t>(hold_frames) * kApproximateFrameMs;
    }
    event.position_x = position_x;
    event.position_y = position_y;
    event.direction_x = direction_x;
    event.direction_y = direction_y;
    event.has_aim_target = has_aim_target;
    event.aim_target_x = aim_target_x;
    event.aim_target_y = aim_target_y;
    g_queued_local_cast_events.push_back(event);
    return event.native_queue_id;
}

void QueueLocalEnemyDamageClaim(
    std::uint64_t network_actor_id,
    std::int32_t skill_id,
    float authoritative_hp,
    float local_hp,
    float max_hp,
    float target_position_x,
    float target_position_y) {
    if (network_actor_id == 0 ||
        !std::isfinite(authoritative_hp) ||
        !std::isfinite(local_hp) ||
        !std::isfinite(max_hp) ||
        max_hp <= 0.0f ||
        !std::isfinite(target_position_x) ||
        !std::isfinite(target_position_y) ||
        local_hp + kEnemyDamageClaimHpEpsilon >= authoritative_hp) {
        return;
    }

    std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
    constexpr std::size_t kMaxQueuedLocalEnemyDamageClaims = 32;
    if (g_queued_local_enemy_damage_claims.size() >= kMaxQueuedLocalEnemyDamageClaims) {
        g_queued_local_enemy_damage_claims.erase(g_queued_local_enemy_damage_claims.begin());
    }
    QueuedLocalEnemyDamageClaim claim;
    claim.network_actor_id = network_actor_id;
    claim.skill_id = skill_id;
    claim.authoritative_hp = authoritative_hp;
    claim.local_hp = local_hp;
    claim.max_hp = max_hp;
    claim.target_position_x = target_position_x;
    claim.target_position_y = target_position_y;
    g_queued_local_enemy_damage_claims.push_back(claim);
}

bool QueueLocalLootPickupRequest(
    std::uint64_t network_drop_id,
    std::uint32_t* request_sequence,
    std::string* error_message) {
    if (request_sequence != nullptr) {
        *request_sequence = 0;
    }
    auto fail = [&](const char* message) {
        if (error_message != nullptr) {
            *error_message = message;
        }
        return false;
    };

    if (!IsLocalTransportEnabled()) {
        return fail("local transport is not enabled");
    }
    if (!IsLocalTransportClient()) {
        return fail("loot pickup requests are currently client-to-host only");
    }
    if (network_drop_id == 0) {
        return fail("network_drop_id must be non-zero");
    }

    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);
    if (local == nullptr ||
        !local->runtime.valid ||
        !local->runtime.in_run ||
        local->runtime.scene_intent.kind != ParticipantSceneIntentKind::Run) {
        return fail("local participant is not in a run");
    }
    const bool present_in_loot_snapshot =
        runtime_state.loot_snapshot.valid &&
        runtime_state.loot_snapshot.scene_intent.kind == ParticipantSceneIntentKind::Run &&
        FindLootDropSnapshotByNetworkId(runtime_state.loot_snapshot, network_drop_id) != nullptr;
    const bool matches_recent_pickup_result =
        runtime_state.last_loot_pickup_result.valid &&
        runtime_state.last_loot_pickup_result.network_drop_id == network_drop_id;
    if (!present_in_loot_snapshot && !matches_recent_pickup_result) {
        return fail("network_drop_id is not present in the replicated loot snapshot");
    }

    std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
    constexpr std::size_t kMaxQueuedLocalLootPickupRequests = 32;
    if (g_queued_local_loot_pickup_requests.size() >= kMaxQueuedLocalLootPickupRequests) {
        g_queued_local_loot_pickup_requests.erase(g_queued_local_loot_pickup_requests.begin());
    }

    QueuedLocalLootPickupRequest request;
    request.network_drop_id = network_drop_id;
    request.request_sequence = g_next_local_loot_pickup_request_sequence++;
    if (g_next_local_loot_pickup_request_sequence == 0) {
        g_next_local_loot_pickup_request_sequence = 1;
    }
    if (request_sequence != nullptr) {
        *request_sequence = request.request_sequence;
    }
    g_queued_local_loot_pickup_requests.push_back(request);
    return true;
}

}  // namespace sdmod::multiplayer
