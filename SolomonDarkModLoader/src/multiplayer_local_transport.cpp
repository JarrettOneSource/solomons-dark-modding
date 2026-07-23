#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <WinSock2.h>
#include <Ws2tcpip.h>

#include "multiplayer_local_transport.h"

#include "bot_runtime.h"
#include "debug_ui_overlay.h"
#include "gameplay_seams.h"
#include "logger.h"
#include "lua_engine.h"
#include "lua_engine_events.h"
#include "lua_event_filters.h"
#include "lua_net_runtime.h"
#include "lua_ui_runtime.h"
#include "memory_access.h"
#include "mod_loader.h"
#include "multiplayer_runtime_protocol.h"
#include "multiplayer_runtime_state.h"
#include "multiplayer_steam_gameplay_queue.h"
#include "native_enemy_lifecycle.h"
#include "native_spell_stats.h"
#include "steam_bootstrap.h"
#include "wave_intelligence.h"
#include "x86_hook.h"

#include <algorithm>
#include <array>
#include <atomic>
#include <charconv>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <filesystem>
#include <fstream>
#include <initializer_list>
#include <iterator>
#include <limits>
#include <map>
#include <mutex>
#include <random>
#include <set>
#include <sstream>
#include <string>
#include <system_error>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

#pragma comment(lib, "Ws2_32.lib")

namespace sdmod::multiplayer {

int CaptureLocalTransportSehCode(EXCEPTION_POINTERS* exception_pointers, DWORD* exception_code);
bool IssueHostLevelUpOfferForParticipant(
    std::uint64_t target_participant_id,
    std::uint32_t run_nonce,
    std::int32_t level,
    std::int32_t experience,
    std::vector<BotSkillChoiceOption> options,
    bool suppress_native_picker);
bool IssueLocalHostSelfLevelUpOffer(
    std::int32_t level,
    std::int32_t experience,
    std::vector<BotSkillChoiceOption> options,
    bool suppress_native_picker,
    std::string* error_message);

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
constexpr std::uint64_t kLocalTransportParticipantFrameIntervalMs = 50;
constexpr std::uint64_t kLocalTransportStateCheckpointIntervalMs = 1000;
constexpr std::uint64_t kLocalTransportWorldSnapshotIntervalMs = 200;
constexpr std::uint64_t kLocalTransportWorldSnapshotReliableCheckpointIntervalMs = 1000;
constexpr std::uint64_t kLocalTransportLootSnapshotIntervalMs = 250;
constexpr std::uint64_t kLocalTransportAnimatedLootSnapshotIntervalMs = 50;
constexpr std::uint64_t kLocalTransportSpellEffectSnapshotIntervalMs = 16;
constexpr std::uint64_t kLuaModStateCheckpointIntervalMs = 5000;
constexpr std::uint64_t kLuaModFragmentAssemblyExpiryMs = 10000;
constexpr std::size_t kLuaModMaxPendingAssemblies = 64;
constexpr std::size_t kLuaModMaxCompletedMessages = 128;
constexpr std::size_t kLuaNetMaxPendingAssemblies = 32;
constexpr std::size_t kLuaNetMaxPendingAssemblyBytes = 512 * 1024;
constexpr std::size_t kLuaNetMaxRememberedSequencesPerParticipant = 256;
constexpr std::size_t kLocalTransportAuxiliarySnapshotBudgetBytesPerSecond =
    48u * 1024u;
constexpr std::size_t kLocalTransportWorldSnapshotBudgetBytesPerSecond =
    96u * 1024u;
constexpr std::size_t
    kLocalTransportWorldReliableCheckpointBudgetBytesPerSecond =
        24u * 1024u;
constexpr std::uint64_t kAirChainSnapshotFreshnessMs = 750;
constexpr std::uint64_t kAirChainTerminalHoldMs = 1000;
constexpr std::uint64_t kAirChainTerminalResendIntervalMs = 50;
constexpr std::int32_t kAirPrimarySkillId = 0x18;
// Keep short-lived child-effect terminal states long enough to overlap the
// longest sibling lifetime and survive transient UDP loss. The 32-effect
// packet bound still caps the amount of retained wire state.
constexpr std::uint64_t kLocalSpellEffectTombstoneHoldMs = 4000;
constexpr std::uint64_t kRecentLocalCastAssociationWindowMs = 3000;
constexpr std::uint64_t kLocalCastInputUpdateIntervalMs = 50;
constexpr std::uint64_t kClientHostRunFollowRetryMs = 1000;
constexpr std::uint64_t kClientHostRegionFollowRetryMs = 1000;
constexpr int kClientHostSharedHubRegionIndex = 0;
constexpr int kClientHostMaximumPrivateRegionIndex = 4;
constexpr std::uint64_t kClientHostRunAuthorizationFreshnessMs = 3000;
constexpr std::uint64_t kClientHostRunExitFollowExpiryMs = 15000;
constexpr std::uint64_t kClientHostRunExitMenuRetryMs = 2500;
constexpr std::uint64_t kClientHostRunExitActionRetryMs = 500;
constexpr std::uint32_t kClientHostRunExitMenuMaxAttempts = 3;
constexpr std::uint64_t kNativeProgressionReconcileRetryMs = 250;
constexpr std::uint64_t kNativeProgressionReconcileAuditMs = 1000;
constexpr int kNativeProgressionReconcileMaxEntryWritesPerTick = 8;
constexpr std::size_t kGameplayBeltButtonArrayOffset = 0x5EC;
constexpr std::size_t kGameplayBeltButtonStride = 0xEC;
constexpr std::size_t kBeltButtonTypeOffset = 0xB4;
constexpr std::size_t kBeltButtonSkillEntryIndexOffset = 0xB8;
constexpr std::uint32_t kBeltButtonSkillTypeId = 0x1B67;
constexpr std::uint64_t kRecentRunEnemyDeathSnapshotHoldMs = 2500;
constexpr std::size_t kLuaItemGrantMaximumQueuedRequests = 256;
constexpr std::size_t kLuaItemGrantMaximumRememberedRequests = 512;
constexpr std::size_t kLuaRegisteredSpellMaximumQueuedCasts = 256;
constexpr std::size_t kLuaRegisteredSpellMaximumRememberedCasts = 512;
constexpr std::uint64_t kLuaRegisteredSpellEffectSnapshotIntervalMs = 50;
constexpr std::uint64_t kLuaRegisteredSpellEffectSnapshotExpiryMs = 1500;
constexpr std::size_t
    kLuaRegisteredSpellEffectSnapshotBudgetBytesPerSecond = 128u * 1024u;

std::uint64_t BandwidthLimitedSnapshotIntervalMs(
    std::size_t wire_size,
    std::uint64_t minimum_interval_ms,
    std::size_t budget_bytes_per_second) {
    if (wire_size == 0) {
        return minimum_interval_ms;
    }
    const auto budget_interval_ms = static_cast<std::uint64_t>(
        (wire_size * 1000u +
         budget_bytes_per_second - 1u) /
        budget_bytes_per_second);
    return (std::max)(minimum_interval_ms, budget_interval_ms);
}

std::uint64_t BandwidthLimitedSnapshotIntervalMs(
    std::size_t wire_size,
    std::uint64_t minimum_interval_ms) {
    return BandwidthLimitedSnapshotIntervalMs(
        wire_size,
        minimum_interval_ms,
        kLocalTransportAuxiliarySnapshotBudgetBytesPerSecond);
}
constexpr float kEnemyDamageClaimHpEpsilon = 0.05f;
constexpr float kEnemyDamageObservationEpsilon = 0.0001f;
constexpr std::uint64_t kEnemyDamageClaimResultRetryMs = 3000;
constexpr float kEnemyDamageClaimMaxDistance = 2200.0f;
constexpr float kEnemyDamageClaimMaxTargetDrift = 384.0f;
constexpr float kEnemyDamageClaimMaxHpFactor = 2.5f;
constexpr float kEnemyDamageClaimAbsoluteCap = 20000.0f;
constexpr std::uint64_t kEnemyDamageRejectedRetrySuppressMs = 500;
constexpr std::uint64_t kEnemyDamageLethalClaimPendingSuppressMs = 2500;
constexpr std::int32_t kFireballExplodeProgressionEntryId = 18;
constexpr float kFireballExplodeConfigFootToWorldUnits = 2.4f;
constexpr float kLootPickupDropDriftMaxDistance = 160.0f;
constexpr float kLootPickupResourceEpsilon = 0.001f;
constexpr float kLootPickupMaxResourceDelta = 10000.0f;
constexpr std::uint64_t kLocalLootPickupRequestRetryMs = 3000;
constexpr std::uint64_t kPowerupPreparationMaterializationTimeoutMs = 60000;
constexpr std::uint32_t kOrbRewardNativeTypeId = 0x07DB;
constexpr std::uint32_t kGoldRewardNativeTypeId = 0x07DC;
constexpr std::uint32_t kItemDropNativeTypeId = 0x07DD;
constexpr std::uint32_t kPowerupRewardNativeTypeId = 0x07F6;
constexpr std::uint32_t kPotionItemTypeId = 0x1B59;
constexpr std::uint32_t kMiscItemTypeId = 0x1B64;
constexpr std::int32_t kStockPotionSubtypeMin = 0;
constexpr std::int32_t kStockPotionSubtypeMax = 5;
constexpr std::int32_t kMiscItemSubtypeMin = 0;
constexpr std::int32_t kMiscItemSubtypeMax = 3;

bool IsSupportedNonRecipeLootItem(
    std::uint32_t item_type_id,
    std::uint32_t item_recipe_uid,
    std::int32_t item_slot) {
    return item_type_id == kMiscItemTypeId &&
           item_recipe_uid == 0 &&
           item_slot >= kMiscItemSubtypeMin &&
           item_slot <= kMiscItemSubtypeMax;
}
constexpr std::uint32_t kEtherPrimaryNativeTypeId = 0x07D3;
constexpr std::uint32_t kFireballPrimaryNativeTypeId = 0x07D4;
constexpr std::uint32_t kWaterPrimaryNativeTypeId = 0x07D5;
constexpr std::uint32_t kFireEmberNativeTypeId = 0x07D6;
constexpr std::uint32_t kFirewalkerTrailNativeTypeId = 0x07EE;
constexpr std::uint32_t kMagicStormNativeTypeId = 0x07F0;
constexpr std::uint32_t kMagicTrapNativeTypeId = 0x07F5;
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
constexpr std::size_t kOrbRewardProgressOffset = 0x14C;
constexpr std::size_t kPowerupRewardKindOffset = 0x13C;
constexpr std::size_t kPowerupRewardMotionOffset = 0x150;
constexpr std::size_t kPowerupRewardLifetimeOffset = 0x154;
constexpr std::size_t kPowerupRewardProgressOffset = 0x158;
constexpr std::size_t kPowerupRewardValueOffset = 0x15C;
constexpr std::size_t kPowerupRewardAuxiliaryOffset = 0x160;
constexpr float kOrbHealthRewardScale = 25.0f;
constexpr float kOrbManaRewardScale = 40.0f;
constexpr std::size_t kAttachmentStaffVisualStateOffset = 0x84;
constexpr std::size_t kVisualLinkColorBlockOffset = 0x88;
constexpr std::uint32_t kAttachmentStaffItemTypeId = 0x1B5C;
constexpr std::uint32_t kHatItemTypeId = 0x1B5D;
constexpr std::uint32_t kRobeItemTypeId = 0x1B5E;
constexpr int kMaxPacketsPerTick = 64;
constexpr float kMagicShieldAbsorbEpsilon = 0.001f;
constexpr float kMagicShieldMaximumAbsorb = 1'000'000.0f;
constexpr float kMagicShieldMaximumExplosionFraction = 100.0f;
constexpr std::size_t kProgressionLevelUpPendingChoiceCountOffset = 0x44;
constexpr std::size_t kProgressionLevelUpIncomingChoiceCountOffset = 0x48;
constexpr std::size_t kProgressionLevelUpPickerUiFlagOffset = 0x839;
constexpr std::size_t kProgressionLevelUpTemporaryPickerObjectOffset = 0x860;
constexpr std::size_t kProgressionLevelUpTemporaryPickerValueOffset = 0x864;
constexpr std::size_t kLevelUpScreenDesiredChoiceCountOffset = 0x88;
constexpr std::size_t kLevelUpScreenOptionValuesOffset = 0x90;
constexpr std::size_t kLevelUpScreenOptionCountOffset = 0x94;
constexpr std::size_t kLevelUpScreenSelectedOptionIndexOffset = 0x5F8;
constexpr std::size_t kLevelUpScreenCloseVtableOffset = 0x18;

using NativeLevelUpScreenCreateFn = void(__thiscall*)(void* progression, char preserve_existing_flag);
using NativeLevelUpScreenCloseFn = void(__thiscall*)(void* screen);
struct NativeLevelUpOptionArray {
    uintptr_t vtable = 0;
    std::int32_t* values = nullptr;
    std::int32_t count = 0;
    std::uint16_t flags = 0;
    std::uint16_t padding = 0;
};

static_assert(sizeof(NativeLevelUpOptionArray) == 0x10, "Native level-up option array layout changed");

using NativeLevelUpOptionRollFn =
    void(__thiscall*)(void* progression, int desired_count, NativeLevelUpOptionArray* output);

struct ArmedLocalLevelUpOptionRoll {
    uintptr_t progression_address = 0;
    std::uint64_t offer_id = 0;
    std::size_t option_count = 0;
    std::array<std::int32_t, kLevelUpOfferMaxOptions> option_ids = {};
};

X86Hook g_local_level_up_option_roll_hook;
std::mutex g_local_level_up_option_roll_mutex;
// Serializes native picker presentation with local offer creation, selection,
// cleanup, and retirement. Reconciliation can synchronously queue a choice,
// so this lock must be recursive. Keep the lock order picker -> runtime state
// -> transport event -> option roll; RuntimeState update lambdas must not call
// back into picker operations.
std::recursive_mutex g_local_level_up_picker_mutex;
ArmedLocalLevelUpOptionRoll g_armed_local_level_up_option_roll;
std::atomic<std::uint64_t> g_last_applied_local_level_up_option_roll_offer_id{0};

void ShutdownLocalLevelUpOptionRollHook();

struct MagicShieldState {
    float absorb_remaining = 0.0f;
    float absorb_capacity = 0.0f;
    float explosion_fraction = 0.0f;
    float hit_flash = 0.0f;
};

struct RecentRunEnemyDeathSnapshot {
    std::uint64_t network_actor_id = 0;
    uintptr_t actor_address = 0;
    std::uint32_t native_type_id = 0;
    std::int32_t enemy_type = -1;
    std::uint64_t lua_content_id = 0;
    float position_x = 0.0f;
    float position_y = 0.0f;
    float radius = 0.0f;
    float heading = 0.0f;
    float max_hp = 0.0f;
    std::uint64_t expires_ms = 0;
};

struct RetainedRunEnemySnapshot {
    uintptr_t actor_address = 0;
    WorldActorSnapshotPacketState packet{};
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
    std::uint32_t item_recipe_uid = 0;
    bool item_color_state_valid = false;
    std::array<std::uint8_t, kParticipantVisualLinkColorBlockBytes> item_color_state = {};
    std::int32_t item_slot = -1;
    std::int32_t stack_count = 0;
    std::uint32_t inventory_revision = 0;
    PowerupRewardKind powerup_kind = PowerupRewardKind::BonusSkillPoint;
    std::int32_t powerup_skill_entry_index = -1;
    std::int32_t powerup_skill_apply_count = 0;
    std::uint16_t powerup_skill_resulting_active = 0;
    std::int32_t damage_x4_remaining_ticks = 0;
    std::uint32_t spellbook_revision = 0;
    std::uint32_t statbook_revision = 0;
};

MagicShieldState NormalizeMagicShieldState(
    float absorb_remaining,
    float absorb_capacity,
    float explosion_fraction,
    float hit_flash) {
    MagicShieldState state;
    if (!std::isfinite(absorb_remaining) ||
        !std::isfinite(absorb_capacity) ||
        !std::isfinite(explosion_fraction) ||
        absorb_remaining <= kMagicShieldAbsorbEpsilon ||
        absorb_remaining > kMagicShieldMaximumAbsorb ||
        absorb_capacity < absorb_remaining ||
        absorb_capacity > kMagicShieldMaximumAbsorb ||
        explosion_fraction < 0.0f ||
        explosion_fraction > kMagicShieldMaximumExplosionFraction) {
        return state;
    }

    state.absorb_remaining = absorb_remaining;
    state.absorb_capacity = absorb_capacity;
    state.explosion_fraction = explosion_fraction;
    if (std::isfinite(hit_flash)) {
        state.hit_flash = (std::clamp)(hit_flash, 0.0f, 1.0f);
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
    std::uint32_t* recipe_uid,
    std::array<std::uint8_t, kParticipantVisualLinkColorBlockBytes>* color_block) {
    if (type_id == nullptr ||
        recipe_uid == nullptr ||
        color_block == nullptr ||
        visual_lane.holder_address == 0) {
        return false;
    }

    *type_id = visual_lane.current_object_type_id;
    *recipe_uid = visual_lane.current_object_recipe_uid;
    *color_block = {};
    if (visual_lane.current_object_address == 0) {
        return true;
    }
    if (visual_lane.current_object_type_id == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    if (!memory.TryRead(
            visual_lane.current_object_address + kVisualLinkColorBlockOffset,
            color_block->data(),
            color_block->size())) {
        return false;
    }

    return true;
}

#include "multiplayer_local_transport/owned_progression_state.inl"

enum class GameplayTransportBackend {
    LocalUdp,
    Steam,
};

struct TransportPeerEndpoint {
    GameplayTransportBackend backend = GameplayTransportBackend::LocalUdp;
    sockaddr_in udp_address{};
    std::uint64_t steam_id = 0;
};

struct LocalPeerEndpoint {
    TransportPeerEndpoint endpoint;
    std::uint64_t participant_id = 0;
    std::uint64_t last_packet_ms = 0;
};

struct QueuedLocalCastEvent {
    std::uint64_t native_queue_id = 0;
    CastKind cast_kind = CastKind::Primary;
    std::int32_t secondary_slot = -1;
    std::int32_t skill_id = 0;
    bool has_live_secondary_loadout = false;
    std::array<std::int32_t, kSecondaryLoadoutSlotCount>
        live_secondary_entry_indices = {-1, -1, -1, -1, -1, -1, -1, -1};
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
    bool has_cursor_world_placement = false;
    float cursor_world_x = 0.0f;
    float cursor_world_y = 0.0f;
};

struct QueuedLuaUiActionRequest {
    std::uint64_t request_id = 0;
    std::string mod_id;
    std::string surface_id;
    std::string action_id;
};

struct QueuedLuaNetMessage {
    std::uint64_t source_participant_id = 0;
    std::uint64_t source_session_nonce = 0;
    std::uint64_t target_participant_id = 0;
    std::uint64_t message_sequence = 0;
    bool local_delivery_complete = false;
    std::vector<std::uint8_t> envelope;
};

struct QueuedHostParticipantVitalsCorrection {
    std::uint64_t target_participant_id = 0;
    float life_current = 0.0f;
    float life_max = 0.0f;
    std::uint8_t transient_status_flags = 0;
    std::int32_t poison_remaining_ticks = 0;
    float poison_damage_per_tick = 0.0f;
    std::int32_t webbed_remaining_ticks = 0;
    float webbed_strength = 0.0f;
    std::uint8_t correction_flags = 0;
    float magic_shield_absorb_remaining = 0.0f;
    float magic_shield_absorb_capacity = 0.0f;
    float magic_shield_explosion_fraction = 0.0f;
    float magic_shield_hit_flash = 0.0f;
    std::int32_t hagatha_cheat_death_charges = 0;
    bool hagatha_serendipity_active = false;
    bool hagatha_reverie_active = false;
    bool hagatha_runtime_valid = false;
};

struct ActiveLocalCastInput {
    bool active = false;
    std::uint32_t cast_sequence = 0;
    std::int32_t skill_id = 0;
    std::uint32_t run_nonce = 0;
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
    bool target_position_optional = false;
    bool baseline_prevalidated = false;
};

struct ObservedLocalEnemyDamage {
    float pending_damage = 0.0f;
    float latest_authoritative_hp = 0.0f;
    float max_hp = 0.0f;
    float target_position_x = 0.0f;
    float target_position_y = 0.0f;
    bool target_position_optional = true;
    bool reference_hp_valid = false;
    float reference_hp = 0.0f;
    std::uint32_t in_flight_claim_sequence = 0;
    std::uint64_t in_flight_sent_ms = 0;
    float in_flight_before_hp = 0.0f;
    float in_flight_after_hp = 0.0f;
};

struct QueuedLocalLootPickupRequest {
    std::uint64_t network_drop_id = 0;
    std::uint32_t request_sequence = 0;
    bool automatic_proximity_request = false;
    bool has_pickup_positions = false;
    float requester_position_x = 0.0f;
    float requester_position_y = 0.0f;
    float drop_position_x = 0.0f;
    float drop_position_y = 0.0f;
};

struct InFlightLocalLootPickupRequest {
    std::uint32_t request_sequence = 0;
    std::uint64_t sent_ms = 0;
};

struct QueuedLocalHostPowerupPickup {
    uintptr_t actor_address = 0;
    LootPickupRequestCapture capture;
};

struct PreparedPowerupReward {
    PowerupRewardKind kind = PowerupRewardKind::BonusSkillPoint;
    std::vector<BotSkillChoiceOption> skill_choice_options;
    BotSkillChoiceOption skill_rank_option;
    std::uint16_t skill_rank_resulting_active = 0;
    std::int32_t damage_x4_duration_ticks = 0;
};

struct PendingHostLootPickup {
    LootPickupRequestPacket packet{};
    TransportPeerEndpoint endpoint;
    LootDropKind drop_kind = LootDropKind::Unknown;
    LootPickupResultPayload payload;
    PreparedPowerupReward powerup;
    uintptr_t actor_address = 0;
    std::uint64_t queued_ms = 0;
    bool host_self = false;
    bool powerup_prepared = false;
    bool awaiting_powerup_preparation = false;
};

struct IssuedLevelUpOffer {
    std::uint64_t offer_id = 0;
    std::uint64_t target_participant_id = 0;
    std::uint32_t run_nonce = 0;
    std::int32_t level = 0;
    std::int32_t experience = 0;
    std::vector<BotSkillChoiceOption> options;
    std::uint64_t barrier_id = 0;
    std::uint64_t issued_ms = 0;
    std::int32_t local_progression_option_index = -1;
    std::int32_t local_progression_option_id = -1;
    bool resolved = false;
    bool auto_picked = false;
    bool local_progression_applied = false;
    LevelUpChoiceResultCode result_code = LevelUpChoiceResultCode::Rejected;
};

struct HostLevelUpBarrierParticipant {
    std::uint64_t participant_id = 0;
    std::uint64_t offer_id = 0;
    std::uint64_t last_offer_attempt_ms = 0;
    std::int32_t option_index = -1;
    std::int32_t option_id = -1;
    std::int32_t apply_count = 0;
    std::uint16_t resulting_active = 0;
    std::uint64_t last_auto_pick_result_ms = 0;
    bool resolved = false;
    bool auto_picked = false;
    bool disconnected = false;
};

struct HostLevelUpBarrierState {
    bool active = false;
    bool timed_out = false;
    std::uint64_t barrier_id = 0;
    std::uint32_t run_nonce = 0;
    std::uint32_t revision = 0;
    std::int32_t level = 0;
    std::int32_t experience = 0;
    uintptr_t source_progression_address = 0;
    std::uint64_t started_ms = 0;
    std::uint64_t deadline_ms = 0;
    std::uint64_t last_broadcast_ms = 0;
    std::uint64_t resume_broadcast_until_ms = 0;
    std::vector<HostLevelUpBarrierParticipant> participants;
};

struct PendingHostLevelUpOfferTarget {
    std::uint64_t target_participant_id = 0;
    std::uint32_t run_nonce = 0;
    std::int32_t level = 0;
    std::int32_t experience = 0;
    uintptr_t source_progression_address = 0;
    std::uint64_t requested_ms = 0;
    std::uint64_t last_log_ms = 0;
};

struct QueuedLocalLevelUpChoice {
    std::uint64_t offer_id = 0;
    std::int32_t option_index = -1;
    std::int32_t option_id = -1;
};

struct FireballExplodeEffectConfig {
    bool loaded = false;
    std::vector<float> damage_by_level;
    std::vector<float> radius_feet_by_level;
};

struct HostLocalExplodeTargetBaseline {
    std::uint64_t network_actor_id = 0;
    float hp = 0.0f;
    float max_hp = 0.0f;
};

struct HostLocalExplodeCastBaseline {
    bool valid = false;
    std::uint32_t cast_sequence = 0;
    std::uint32_t run_nonce = 0;
    std::uint64_t target_network_actor_id = 0;
    std::uint64_t captured_ms = 0;
    float primary_hp = 0.0f;
    float primary_x = 0.0f;
    float primary_y = 0.0f;
    float splash_damage = 0.0f;
    float splash_radius_world = 0.0f;
    std::vector<HostLocalExplodeTargetBaseline> targets;
};

struct NativeProgressionReconcileCheckpoint {
    uintptr_t progression_address = 0;
    int gameplay_slot = -1;
    std::uint32_t spellbook_revision = 0;
    std::uint32_t statbook_revision = 0;
    std::uint32_t concentration_revision = 0;
    std::uint32_t derived_stat_revision = 0;
    std::uint32_t hagatha_perk_revision = 0;
    bool concentration_selection_valid = false;
    std::int32_t concentration_entry_a = -1;
    std::int32_t concentration_entry_b = -1;
    std::int32_t level = 0;
    std::int32_t experience = 0;
    float move_speed = 0.0f;
    std::uint64_t last_attempt_ms = 0;
    std::uint64_t last_concentration_failure_log_ms = 0;
    std::uint64_t last_derived_stat_failure_log_ms = 0;
    bool complete = false;
};

struct LocalSpellEffectTracking {
    uintptr_t actor_address = 0;
    std::uint32_t effect_serial = 0;
    std::uint32_t cast_sequence = 0;
    std::uint32_t native_type_id = 0;
    std::uint16_t effect_ordinal = 0;
    std::uint64_t last_seen_ms = 0;
    std::uint64_t terminal_expires_ms = 0;
    SpellEffectPacketState last_state{};
};

struct QueuedLocalAirChainFrame {
    uintptr_t caster_actor_address = 0;
    std::uint64_t captured_ms = 0;
    std::uint8_t target_count = 0;
    std::uint8_t target_total_count = 0;
    bool truncated = false;
    std::array<AirChainTargetCapture, kAirChainSnapshotMaxTargets> targets{};
};

struct PendingAirChainTerminal {
    std::uint32_t cast_sequence = 0;
    std::uint32_t run_nonce = 0;
    std::uint64_t expires_ms = 0;
    std::uint64_t last_sent_ms = 0;
};

struct PendingParticipantVitalsCorrection {
    ParticipantVitalsCorrectionPacket packet{};
    std::uint64_t last_sent_ms = 0;
};

struct QueuedLuaModStreamMessage {
    LuaModStreamMessageKind kind = LuaModStreamMessageKind::StateCheckpoint;
    std::uint64_t stream_sequence = 0;
    std::uint64_t state_revision = 0;
    std::vector<std::uint8_t> payload;
};

struct QueuedAuthoritativeLuaItemGrant {
    std::uint64_t request_id = 0;
    std::uint64_t target_participant_id = 0;
    std::uint64_t content_id = 0;
    bool color_state_valid = false;
    std::array<std::uint8_t, kParticipantVisualLinkColorBlockBytes>
        color_state = {};
};

struct QueuedLuaRegisteredSpellCast {
    LuaRegisteredSpellCastRequest request;
};

struct PendingLuaRegisteredSpellEffectSnapshot {
    std::uint32_t generation = 0;
    std::uint32_t run_nonce = 0;
    std::uint32_t scene_epoch = 0;
    std::uint16_t fragment_count = 0;
    std::uint16_t received_fragment_count = 0;
    std::uint16_t effect_total_count = 0;
    std::uint64_t last_update_ms = 0;
    std::vector<LuaRegisteredSpellEffectState> effects;
    std::vector<std::uint8_t> received_fragments;
};

struct CompletedLuaRegisteredSpellEffectSnapshot {
    std::uint64_t owner_participant_id = 0;
    std::uint32_t generation = 0;
    std::uint32_t run_nonce = 0;
    std::uint32_t scene_epoch = 0;
    std::uint64_t received_ms = 0;
    std::vector<LuaRegisteredSpellEffectState> effects;
};

struct PendingLuaModStreamAssembly {
    LuaModStreamMessageKind kind = LuaModStreamMessageKind::StateCheckpoint;
    std::uint64_t authority_participant_id = 0;
    std::uint64_t stream_sequence = 0;
    std::uint64_t state_revision = 0;
    std::uint32_t total_payload_bytes = 0;
    std::uint16_t fragment_count = 0;
    std::uint16_t received_fragment_count = 0;
    std::uint64_t last_update_ms = 0;
    std::vector<std::uint8_t> payload;
    std::vector<std::uint8_t> received_fragments;
};

struct CompletedLuaModStreamMessage {
    LuaModStreamMessageKind kind = LuaModStreamMessageKind::StateCheckpoint;
    std::uint64_t authority_participant_id = 0;
    std::uint64_t stream_sequence = 0;
    std::uint64_t state_revision = 0;
    std::vector<std::uint8_t> payload;
};

struct PendingLuaNetMessageAssembly {
    std::uint64_t transport_participant_id = 0;
    std::uint64_t source_participant_id = 0;
    std::uint64_t source_session_nonce = 0;
    std::uint64_t target_participant_id = 0;
    std::uint64_t message_sequence = 0;
    std::uint32_t total_payload_bytes = 0;
    std::uint16_t fragment_count = 0;
    std::uint16_t received_fragment_count = 0;
    std::uint64_t last_update_ms = 0;
    std::vector<std::uint8_t> payload;
    std::vector<std::uint8_t> received_fragments;
};

struct ClientHostRunAuthorization {
    bool valid = false;
    std::uint64_t authority_participant_id = 0;
    std::uint32_t run_nonce = 0;
    std::uint64_t received_ms = 0;
};

struct ClientHostRunExitFollow {
    bool active = false;
    std::uint32_t run_nonce = 0;
    std::uint64_t received_ms = 0;
    std::uint64_t last_menu_request_ms = 0;
    std::uint64_t last_action_attempt_ms = 0;
    std::uint64_t action_request_id = 0;
    std::uint32_t menu_request_count = 0;
};

struct HostMenuPauseRequestState {
    std::uint32_t request_epoch = 0;
    std::uint32_t run_nonce = 0;
    bool requested = false;
    bool timed_out_until_release = false;
    std::uint64_t deadline_ms = 0;
    std::uint64_t last_update_ms = 0;
};

#include "multiplayer_local_transport/world_snapshot_fragmentation.inl"

struct LocalTransportState {
    bool configured = false;
    bool initialized = false;
    bool winsock_initialized = false;
    bool is_host = false;
    bool suppress_local_level_up_fanout = false;
    GameplayTransportBackend backend = GameplayTransportBackend::LocalUdp;
    SOCKET socket_handle = INVALID_SOCKET;
    std::uint16_t local_port = 0;
    std::string remote_host;
    std::uint16_t remote_port = 0;
    bool configured_remote_valid = false;
    TransportPeerEndpoint configured_remote;
    std::uint64_t local_peer_id = 0;
    std::uint64_t last_participant_frame_send_ms = 0;
    std::uint64_t last_state_checkpoint_send_ms = 0;
    std::uint64_t last_world_snapshot_send_ms = 0;
    std::uint64_t last_world_snapshot_reliable_checkpoint_ms = 0;
    std::uint64_t last_loot_snapshot_send_ms = 0;
    std::uint64_t last_spell_effect_snapshot_send_ms = 0;
    std::uint64_t last_lua_mod_checkpoint_send_ms = 0;
    std::uint64_t last_lua_registered_spell_effect_snapshot_send_ms = 0;
    std::uint64_t last_lua_mod_stream_sent_sequence = 0;
    std::uint64_t last_lua_mod_stream_applied_sequence = 0;
    std::uint32_t next_lua_mod_message_id = 1;
    std::uint64_t last_client_host_run_request_ms = 0;
    std::uint64_t last_client_host_region_request_ms = 0;
    ClientHostRunExitFollow client_host_run_exit_follow;
    bool local_menu_pause_requested = false;
    std::uint32_t local_menu_pause_request_epoch = 0;
    std::string local_menu_pause_surface_id;
    std::uint32_t next_sequence = 1;
    std::uint32_t next_world_snapshot_id = 1;
    std::uint64_t local_session_nonce = 0;
    std::uint32_t world_scene_epoch = 0;
    std::uint64_t packets_sent = 0;
    std::uint64_t packets_received = 0;
    std::uint64_t steam_send_failures = 0;
    std::uint64_t steam_reliable_send_failures = 0;
    std::int32_t last_steam_send_failure_result = 0;
    std::uint32_t next_cast_sequence = 1;
    std::uint32_t next_spell_effect_serial = 1;
    std::uint32_t next_air_chain_frame_sequence = 1;
    std::uint32_t next_participant_vitals_correction_sequence = 1;
    std::uint32_t last_applied_participant_vitals_correction_sequence = 0;
    std::uint32_t recent_local_cast_sequence = 0;
    std::int32_t recent_local_cast_skill_id = -1;
    std::uint64_t recent_local_cast_ms = 0;
    std::uint64_t recent_local_cast_target_network_actor_id = 0;
    std::uint32_t last_local_explode_splash_cast_sequence = 0;
    HostLocalExplodeCastBaseline host_local_explode_cast_baseline;
    bool spell_effect_snapshot_had_effects = false;
    std::uint32_t next_enemy_damage_claim_sequence = 1;
    std::uint64_t next_level_up_offer_id = 1;
    std::uint64_t next_level_up_barrier_id = 1;
    std::string world_scene_key;
    std::unordered_map<uintptr_t, std::uint64_t> hub_world_actor_ids_by_address;
    std::unordered_map<uintptr_t, std::uint64_t> run_host_local_world_actor_ids_by_address;
    std::unordered_map<uintptr_t, std::uint64_t> run_loot_drop_ids_by_address;
    std::unordered_map<std::uint64_t, RecentRunEnemyDeathSnapshot> recent_run_enemy_deaths_by_network_id;
    std::unordered_map<std::uint64_t, RetainedRunEnemySnapshot>
        retained_run_enemy_snapshots_by_network_id;
    PendingWorldSnapshotAssemblies pending_world_snapshots;
    std::unordered_map<std::uint64_t, float> last_synced_enemy_hp_by_network_id;
    std::unordered_map<std::uint64_t, float> last_enemy_claimed_hp_by_network_id;
    std::unordered_map<std::uint64_t, ObservedLocalEnemyDamage>
        observed_enemy_damage_by_network_id;
    std::unordered_map<std::uint64_t, std::uint64_t>
        recent_local_air_chain_target_until_ms;
    std::unordered_map<std::uint64_t, std::uint64_t> pending_lethal_enemy_damage_claim_until_ms;
    std::unordered_map<std::uint64_t, std::uint64_t> rejected_enemy_damage_retry_suppressed_until_ms;
    std::unordered_map<std::uint64_t, std::uint32_t> last_state_packet_sequence_by_participant;
    std::unordered_map<std::uint64_t, std::uint32_t>
        last_participant_frame_sequence_by_participant;
    std::unordered_map<std::uint64_t, std::uint64_t>
        session_nonce_by_participant;
    std::unordered_map<std::uint64_t, std::uint64_t>
        last_lua_ui_action_request_by_participant;
    std::unordered_map<std::uint64_t, std::unordered_set<std::uint64_t>>
        retired_session_nonces_by_participant;
    std::unordered_map<std::uint64_t, std::uint32_t> last_cast_sequence_by_participant;
    std::unordered_map<std::uint64_t, std::uint32_t>
        last_spell_effect_packet_sequence_by_participant;
    std::unordered_map<std::uint64_t, std::uint32_t>
        last_air_chain_packet_sequence_by_participant;
    std::unordered_map<std::uint64_t, std::uint32_t>
        last_participant_vitals_correction_sequence_by_authority;
    std::unordered_map<std::uint64_t, PendingParticipantVitalsCorrection>
        pending_participant_vitals_corrections_by_participant;
    std::unordered_map<std::uint64_t, std::uint64_t>
        last_participant_vitals_correction_send_ms_by_participant;
    std::unordered_map<uintptr_t, LocalSpellEffectTracking> local_spell_effects_by_address;
    std::vector<LocalSpellEffectTracking> local_spell_effect_tombstones;
    std::unordered_map<std::uint64_t, std::uint16_t> next_spell_effect_ordinal_by_cast_type;
    std::unordered_map<std::uint64_t, RemoteCastInputTracker> remote_cast_inputs_by_participant;
    std::unordered_map<std::uint64_t, std::uint32_t> last_enemy_claim_sequence_by_participant;
    std::unordered_map<std::uint64_t, std::uint32_t> last_loot_pickup_request_sequence_by_participant;
    std::unordered_map<std::uint64_t, IssuedLevelUpOffer> issued_level_up_offers_by_id;
    std::unordered_map<std::uint64_t, PendingHostLevelUpOfferTarget> pending_level_up_offer_targets_by_participant;
    HostLevelUpBarrierState host_level_up_barrier;
    std::unordered_map<std::uint64_t, NativeProgressionReconcileCheckpoint>
        native_progression_reconcile_by_participant;
    std::unordered_set<std::uint64_t> native_applied_level_up_result_offer_ids;
    std::unordered_set<std::uint64_t> confirmed_auto_pick_level_up_offer_ids;
    std::unordered_set<std::uint64_t> accepted_loot_pickup_drop_ids;
    std::unordered_set<std::uint64_t>
        native_applied_powerup_result_drop_ids;
    std::unordered_map<std::uint64_t, PendingHostLootPickup>
        pending_host_loot_pickups_by_drop_id;
    std::unordered_map<std::uint64_t, HostMenuPauseRequestState>
        host_menu_pause_requests_by_participant;
    std::unordered_set<std::uint64_t> lua_mod_checkpointed_participants;
    std::unordered_map<std::uint32_t, PendingLuaModStreamAssembly>
        pending_lua_mod_stream_assemblies;
    std::map<std::uint64_t, CompletedLuaModStreamMessage>
        completed_lua_mod_stream_messages;
    std::map<
        std::pair<std::uint64_t, std::uint64_t>,
        PendingLuaNetMessageAssembly> pending_lua_net_message_assemblies;
    std::unordered_map<std::uint64_t, std::unordered_set<std::uint64_t>>
        received_lua_net_sequences_by_participant;
    std::unordered_map<std::uint64_t, std::deque<std::uint64_t>>
        received_lua_net_sequence_order_by_participant;
    std::unordered_map<std::uint64_t, std::uint64_t>
        received_lua_net_session_nonce_by_participant;
    std::unordered_set<std::uint64_t> received_lua_item_grant_request_ids;
    std::deque<std::uint64_t> received_lua_item_grant_request_order;
    std::unordered_set<std::uint64_t>
        received_lua_registered_spell_cast_request_ids;
    std::deque<std::uint64_t>
        received_lua_registered_spell_cast_request_order;
    std::unordered_map<std::uint64_t, std::uint32_t>
        next_lua_registered_spell_effect_generation_by_owner;
    std::unordered_set<std::uint64_t>
        local_lua_registered_spell_effect_snapshot_owners;
    std::unordered_map<std::uint64_t, PendingLuaRegisteredSpellEffectSnapshot>
        pending_lua_registered_spell_effect_snapshots;
    std::unordered_map<std::uint64_t, CompletedLuaRegisteredSpellEffectSnapshot>
        completed_lua_registered_spell_effect_snapshots;
    ActiveLocalCastInput active_local_cast_input;
    std::vector<PendingAirChainTerminal> pending_air_chain_terminals;
    std::uint32_t next_hub_world_actor_serial = 1;
    std::uint32_t next_run_host_local_world_actor_serial = 1;
    std::uint32_t next_run_loot_drop_serial = 1;
    std::vector<LocalPeerEndpoint> peers;
};

LocalTransportState g_local_transport;
std::atomic<std::uint32_t> g_local_run_exit_latched_nonce{0};
std::atomic<std::uint64_t>
    g_remote_native_progression_reconcile_suppressed_for_test{0};
std::mutex g_local_transport_event_mutex;
std::mutex g_local_enemy_damage_claim_observation_mutex;
std::unordered_map<std::uint64_t, LocalEnemyDamageClaimObservation>
    g_local_enemy_damage_claim_observations;
ClientHostRunAuthorization g_client_host_run_authorization;
std::mutex g_client_host_run_authorization_mutex;
std::vector<QueuedLocalCastEvent> g_queued_local_cast_events;
std::uint64_t g_next_local_cast_event_id = 1;
std::vector<QueuedLocalEnemyDamageClaim> g_queued_local_enemy_damage_claims;
std::vector<QueuedHostParticipantVitalsCorrection>
    g_queued_host_participant_vitals_corrections;
std::vector<QueuedLocalLootPickupRequest> g_queued_local_loot_pickup_requests;
std::unordered_map<std::uint64_t, InFlightLocalLootPickupRequest>
    g_in_flight_local_loot_pickup_requests_by_drop_id;
std::vector<QueuedLocalHostPowerupPickup>
    g_queued_local_host_powerup_pickups;
std::vector<QueuedLocalLevelUpChoice> g_queued_local_level_up_choices;
std::vector<QueuedLuaModStreamMessage> g_queued_lua_mod_stream_messages;
std::uint64_t g_next_lua_mod_stream_sequence = 1;
std::vector<QueuedAuthoritativeLuaItemGrant>
    g_queued_authoritative_lua_item_grants;
std::uint64_t g_next_lua_item_grant_request_id = 1;
std::vector<QueuedLuaRegisteredSpellCast>
    g_queued_lua_registered_spell_casts;
std::uint64_t g_next_lua_registered_spell_cast_request_id = 1;
std::vector<QueuedLuaUiActionRequest> g_queued_lua_ui_action_requests;
std::uint64_t g_next_lua_ui_action_request_id = 1;
std::vector<QueuedLuaNetMessage> g_queued_lua_net_messages;
std::uint64_t g_next_lua_net_message_sequence = 1;
std::size_t g_queued_lua_net_message_bytes = 0;
std::mutex g_lua_registered_spell_effect_snapshot_mutex;
QueuedLocalAirChainFrame g_queued_local_air_chain_frame;
bool g_have_queued_local_air_chain_frame = false;
std::uint32_t g_next_local_loot_pickup_request_sequence = 1;
FireballExplodeEffectConfig g_fireball_explode_effect_config;
bool g_fireball_explode_effect_config_attempted = false;

void ClearLocalLootPickupRequestStateLocked() {
    g_queued_local_loot_pickup_requests.clear();
    g_in_flight_local_loot_pickup_requests_by_drop_id.clear();
}

void CompleteInFlightLocalLootPickupRequest(
    std::uint64_t network_drop_id,
    std::uint32_t request_sequence) {
    std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
    const auto request_it =
        g_in_flight_local_loot_pickup_requests_by_drop_id.find(
            network_drop_id);
    if (request_it ==
            g_in_flight_local_loot_pickup_requests_by_drop_id.end() ||
        request_it->second.request_sequence != request_sequence) {
        return;
    }
    g_in_flight_local_loot_pickup_requests_by_drop_id.erase(request_it);
}

void ClearLocalEnemyDamageClaimObservationsInternal() {
    std::lock_guard<std::mutex> lock(
        g_local_enemy_damage_claim_observation_mutex);
    g_local_enemy_damage_claim_observations.clear();
}

void ResetLocalEnemyDamageClaimObservationInternal(
    std::uint64_t network_actor_id) {
    if (network_actor_id == 0) {
        return;
    }
    std::lock_guard<std::mutex> lock(
        g_local_enemy_damage_claim_observation_mutex);
    g_local_enemy_damage_claim_observations[network_actor_id] =
        LocalEnemyDamageClaimObservation{};
}

void RecordLocalEnemyDamageClaimObservationInternal(
    std::uint64_t network_actor_id,
    float claimed_damage,
    std::int32_t associated_skill_id) {
    if (network_actor_id == 0 ||
        !std::isfinite(claimed_damage) ||
        claimed_damage <= 0.0f) {
        return;
    }

    std::lock_guard<std::mutex> lock(
        g_local_enemy_damage_claim_observation_mutex);
    const auto existing =
        g_local_enemy_damage_claim_observations.find(network_actor_id);
    if (existing == g_local_enemy_damage_claim_observations.end()) {
        return;
    }

    auto& observation = existing->second;
    observation.valid = true;
    observation.network_actor_id = network_actor_id;
    ++observation.claim_count;
    if (associated_skill_id < 0) {
        ++observation.unassociated_claim_count;
        return;
    }
    ++observation.associated_claim_count;
    if (observation.associated_claim_count == 1) {
        observation.associated_skill_id = associated_skill_id;
    } else if (observation.associated_skill_id != associated_skill_id) {
        observation.associated_skill_consistent = false;
    }
    observation.claimed_damage_total += claimed_damage;
    if (observation.associated_claim_count == 1) {
        observation.minimum_claimed_damage = claimed_damage;
        observation.maximum_claimed_damage = claimed_damage;
    } else {
        observation.minimum_claimed_damage =
            (std::min)(observation.minimum_claimed_damage, claimed_damage);
        observation.maximum_claimed_damage =
            (std::max)(observation.maximum_claimed_damage, claimed_damage);
    }
    if (observation.sample_count <
        observation.claimed_damage_samples.size()) {
        observation.claimed_damage_samples[observation.sample_count++] =
            claimed_damage;
    }
}

std::mutex g_air_chain_runtime_mutex;
AirChainSnapshotRuntimeInfo g_local_air_chain_capture_runtime;
std::vector<AirChainSnapshotRuntimeInfo> g_local_air_chain_history_runtime;
std::unordered_map<std::uint64_t, AirChainSnapshotRuntimeInfo>
    g_replicated_air_chain_snapshots_by_participant;
std::vector<AirChainSnapshotRuntimeInfo> g_replicated_air_chain_history_runtime;
AirChainApplyRuntimeInfo g_air_chain_apply_runtime;

void ResetAirChainRuntimeState();
void QueueAirChainTerminal(
    std::uint32_t cast_sequence,
    std::uint32_t run_nonce,
    std::uint64_t now_ms);
bool TryReadParticipantProgressionEntryActive(
    std::uint64_t participant_id,
    std::int32_t entry_index,
    std::uint16_t* active);
bool HydrateAuthoritativeRemoteProgressionEntryState(
    std::uint64_t participant_id,
    std::int32_t entry_index,
    std::uint16_t resulting_active,
    std::uint16_t resulting_visible,
    std::string* error_message);
bool ApplyAuthoritativeRemoteSkillRankDelta(
    std::uint64_t participant_id,
    const BotSkillChoiceOption& option,
    std::uint16_t* resulting_active,
    std::string* error_message);
LootPickupResultPayload BuildLootPickupResultPayloadFromParticipant(
    const ParticipantInfo* participant);

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

bool SameEndpoint(const TransportPeerEndpoint& left, const TransportPeerEndpoint& right) {
    if (left.backend != right.backend) {
        return false;
    }
    if (left.backend == GameplayTransportBackend::Steam) {
        return left.steam_id != 0 && left.steam_id == right.steam_id;
    }
    return left.udp_address.sin_family == right.udp_address.sin_family &&
           left.udp_address.sin_port == right.udp_address.sin_port &&
           left.udp_address.sin_addr.S_un.S_addr == right.udp_address.sin_addr.S_un.S_addr;
}

std::string EndpointToString(const TransportPeerEndpoint& endpoint) {
    if (endpoint.backend == GameplayTransportBackend::Steam) {
        return "steam:" + std::to_string(endpoint.steam_id);
    }
    const auto& address = endpoint.udp_address;
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

std::filesystem::path ResolveRuntimeWizardSkillConfigPath(const wchar_t* file_name) {
    if (file_name == nullptr || *file_name == L'\0') {
        return {};
    }

    std::array<wchar_t, MAX_PATH> executable_path{};
    const auto length =
        GetModuleFileNameW(nullptr, executable_path.data(), static_cast<DWORD>(executable_path.size()));
    if (length == 0 || length >= executable_path.size()) {
        return {};
    }

    std::filesystem::path path(executable_path.data());
    return path.parent_path() / "data" / "wizardskills" / file_name;
}

void PopulateHostLevelUpBarrierStatePacket(
    StatePacket* packet,
    std::uint64_t now_ms);
bool ApplyAuthoritativeLevelUpWaitStatus(
    std::uint64_t authority_participant_id,
    std::uint64_t barrier_id,
    std::uint32_t revision,
    std::uint32_t deadline_remaining_ms,
    bool pause_active,
    bool timed_out,
    std::vector<std::uint64_t> waiting_participant_ids,
    std::uint64_t now_ms);
void RefreshLocalMenuPauseRequest(std::uint64_t now_ms);
void RefreshHostSharedGameplayPause(std::uint64_t now_ms);
void PopulateSharedGameplayPausePacketFields(
    const RuntimeState& runtime_state,
    StatePacket* packet);
void PopulateSharedGameplayPausePacketFields(
    const RuntimeState& runtime_state,
    ParticipantFramePacket* packet);
void ApplyHostMenuPauseRequest(
    std::uint64_t participant_id,
    std::uint32_t run_nonce,
    std::uint32_t request_epoch,
    bool requested,
    std::uint64_t now_ms);
void ApplyAuthoritativeSharedGameplayPause(
    std::uint64_t authority_participant_id,
    std::uint32_t run_nonce,
    std::uint64_t origin_participant_id,
    std::uint32_t deadline_remaining_ms,
    bool pause_active,
    bool timed_out,
    std::uint64_t now_ms);
bool ShouldPauseForSharedGameplayMenu();
void MarkHostLevelUpBarrierParticipantResolved(
    const LevelUpChoiceResultPacket& result,
    bool auto_picked,
    std::uint64_t now_ms);
HostLevelUpBarrierParticipant* FindHostLevelUpBarrierParticipant(
    std::uint64_t participant_id);
void ResetRemoteParticipantSessionEpoch(
    std::uint64_t participant_id,
    bool configured_authority_disconnected,
    bool preserve_session_nonce_history = false);
bool CallLevelUpScreenCloseSafe(uintptr_t screen_address, DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (screen_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t vtable_address = 0;
    uintptr_t close_address = 0;
    if (!memory.TryReadValue(screen_address, &vtable_address) ||
        vtable_address == 0 ||
        !memory.TryReadValue(
            vtable_address + kLevelUpScreenCloseVtableOffset,
            &close_address) ||
        close_address == 0) {
        return false;
    }

    auto* close_screen = reinterpret_cast<NativeLevelUpScreenCloseFn>(close_address);
    __try {
        close_screen(reinterpret_cast<void*>(screen_address));
        return true;
    } __except (CaptureLocalTransportSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

#include "multiplayer_local_transport/skill_config_and_packet_helpers.inl"
#include "multiplayer_local_transport/hagatha_perk_state.inl"
#include "multiplayer_local_transport/run_exit_sync.inl"
#include "multiplayer_local_transport/world_snapshot_capture.inl"
#include "multiplayer_local_transport/loot_snapshot_capture.inl"
#include "multiplayer_local_transport/wave_summary_sync.inl"
#include "multiplayer_local_transport/local_state_packet_sync.inl"
#include "multiplayer_local_transport/local_snapshot_packet_builders.inl"
#include "multiplayer_local_transport/cast_target_resolution.inl"
#include "multiplayer_local_transport/outgoing_packet_sync.inl"
#include "multiplayer_local_transport/outgoing_cast_packet_sync.inl"
#include "multiplayer_local_transport/client_enemy_damage_sync.inl"
#include "multiplayer_local_transport/incoming_packet_sync.inl"
#include "multiplayer_local_transport/lua_item_grant_sync.inl"
#include "multiplayer_local_transport/lua_registered_spell_cast_sync.inl"
#include "multiplayer_local_transport/lua_registered_spell_effect_sync.inl"
#include "multiplayer_local_transport/lua_ui_action_sync.inl"
#include "multiplayer_local_transport/lua_net_message_codec.inl"
#include "multiplayer_local_transport/lua_net_message_sync.inl"
#include "multiplayer_local_transport/lua_mod_stream_codec.inl"
#include "multiplayer_local_transport/lua_mod_stream_sync.inl"
#include "multiplayer_local_transport/shared_gameplay_pause_sync.inl"
#include "multiplayer_local_transport/incoming_cast_packet_sync.inl"
#include "multiplayer_local_transport/incoming_snapshot_packet_sync.inl"
#include "multiplayer_local_transport/incoming_packet_dispatch.inl"
#include "multiplayer_local_transport/native_progression_sync.inl"
#include "multiplayer_local_transport/remote_peer_lifecycle.inl"

void PublishLocalTransportRuntimeState() {
    AirChainSnapshotRuntimeInfo local_air_chain_capture;
    std::vector<AirChainSnapshotRuntimeInfo> local_air_chain_history;
    std::vector<AirChainSnapshotRuntimeInfo> air_chain_snapshots;
    std::vector<AirChainSnapshotRuntimeInfo> air_chain_snapshot_history;
    AirChainApplyRuntimeInfo air_chain_apply;
    {
        std::lock_guard<std::mutex> lock(g_air_chain_runtime_mutex);
        local_air_chain_capture = g_local_air_chain_capture_runtime;
        local_air_chain_history = g_local_air_chain_history_runtime;
        air_chain_snapshot_history = g_replicated_air_chain_history_runtime;
        air_chain_apply = g_air_chain_apply_runtime;
        air_chain_snapshots.reserve(
            g_replicated_air_chain_snapshots_by_participant.size());
        for (const auto& [participant_id, snapshot] :
             g_replicated_air_chain_snapshots_by_participant) {
            (void)participant_id;
            air_chain_snapshots.push_back(snapshot);
        }
    }
    std::sort(
        air_chain_snapshots.begin(),
        air_chain_snapshots.end(),
        [](const AirChainSnapshotRuntimeInfo& left,
           const AirChainSnapshotRuntimeInfo& right) {
            return left.owner_participant_id < right.owner_participant_id;
        });

    if (g_local_transport.backend == GameplayTransportBackend::Steam) {
        const auto queue_stats = SnapshotSteamGameplayQueueStats();
        g_local_transport.packets_sent = queue_stats.packets_sent;
        g_local_transport.steam_send_failures = queue_stats.send_failures;
        g_local_transport.steam_reliable_send_failures =
            queue_stats.reliable_send_failures;
        g_local_transport.last_steam_send_failure_result =
            queue_stats.last_send_failure_result;
    }

    UpdateRuntimeState([&](RuntimeState& state) {
        state.transport_packets_sent = g_local_transport.packets_sent;
        state.transport_packets_received = g_local_transport.packets_received;
        state.steam_send_failures = g_local_transport.steam_send_failures;
        state.steam_reliable_send_failures =
            g_local_transport.steam_reliable_send_failures;
        state.last_steam_send_failure_result =
            g_local_transport.last_steam_send_failure_result;
        if (g_local_transport.backend == GameplayTransportBackend::LocalUdp) {
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
        }
        state.local_air_chain_capture = std::move(local_air_chain_capture);
        state.local_air_chain_history = std::move(local_air_chain_history);
        state.air_chain_snapshots = std::move(air_chain_snapshots);
        state.air_chain_snapshot_history = std::move(air_chain_snapshot_history);
        state.air_chain_apply = std::move(air_chain_apply);
        if (g_local_transport.is_host) {
            state.level_up_wait_status = BuildHostLevelUpWaitStatusRuntimeInfo(
                static_cast<std::uint64_t>(GetTickCount64()));
        }
    });
}

}  // namespace

void ConfirmLocalParticipantVitalsCorrection(
    std::uint32_t correction_sequence) {
    if (!g_local_transport.initialized ||
        g_local_transport.is_host ||
        correction_sequence == 0) {
        return;
    }
    const auto previous =
        g_local_transport.last_applied_participant_vitals_correction_sequence;
    if (previous == 0 ||
        correction_sequence == previous ||
        IsPacketSequenceNewer(correction_sequence, previous)) {
        g_local_transport.last_applied_participant_vitals_correction_sequence =
            correction_sequence;
    }
}

void NotifyLocalRunStarted() {
    if (!g_local_transport.initialized) {
        return;
    }

    const auto previous_exit_nonce =
        g_local_run_exit_latched_nonce.exchange(0, std::memory_order_acq_rel);
    const bool cleared_client_exit_follow =
        g_local_transport.client_host_run_exit_follow.active;
    g_local_transport.client_host_run_exit_follow = ClientHostRunExitFollow{};
    if (previous_exit_nonce != 0 || cleared_client_exit_follow) {
        Log(
            "Multiplayer new run retired prior run-exit state. role=" +
            std::string(g_local_transport.is_host ? "host" : "client") +
            " prior_exit_nonce=" + std::to_string(previous_exit_nonce) +
            " cleared_client_follow=" +
            std::to_string(cleared_client_exit_follow ? 1 : 0));
    }
}

void NotifyLocalRunEnded(std::string_view reason) {
    if (!g_local_transport.initialized) {
        return;
    }

    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);
    const auto current_nonce =
        local != nullptr && local->runtime.run_nonce != 0
            ? local->runtime.run_nonce
            : g_local_run_exit_latched_nonce.load(std::memory_order_acquire);
    if (g_local_transport.is_host && current_nonce != 0) {
        g_local_run_exit_latched_nonce.store(current_nonce, std::memory_order_release);
    }

    UpdateRuntimeState([&](RuntimeState& state) {
        auto* mutable_local = FindLocalParticipant(state);
        if (mutable_local == nullptr) {
            return;
        }
        mutable_local->runtime.in_run = false;
        mutable_local->runtime.transform_valid = false;
        mutable_local->runtime.scene_intent = DefaultParticipantSceneIntent();
        if (g_local_transport.is_host && current_nonce != 0) {
            mutable_local->runtime.run_nonce = current_nonce;
        }
    });

    Log(
        "Multiplayer local run exit latched. role=" +
        std::string(g_local_transport.is_host ? "host" : "client") +
        " run_nonce=" + std::to_string(current_nonce) +
        " reason=" + std::string(reason));
}

bool SetRemoteNativeProgressionReconcileSuppressedForTest(
    std::uint64_t participant_id,
    bool suppressed) {
    if (participant_id == 0) {
        return false;
    }
    if (suppressed) {
        g_remote_native_progression_reconcile_suppressed_for_test.store(
            participant_id,
            std::memory_order_release);
        return true;
    }

    auto expected = participant_id;
    return g_remote_native_progression_reconcile_suppressed_for_test
        .compare_exchange_strong(
            expected,
            0,
            std::memory_order_acq_rel,
            std::memory_order_acquire);
}

void ProcessPendingHostLevelUpOffers(std::uint64_t now_ms);
void ProcessHostLevelUpBarrier(std::uint64_t now_ms);
int CaptureLocalTransportSehCode(EXCEPTION_POINTERS* exception_pointers, DWORD* exception_code);

#include "multiplayer_local_transport/public_cast_loot_api.inl"
#include "multiplayer_local_transport/public_cast_loot_queue_api.inl"
#include "multiplayer_local_transport/lua_mod_stream_public.inl"

#include "multiplayer_local_transport/level_up_authority.inl"
#include "multiplayer_local_transport/level_up_debug_authority.inl"
#include "multiplayer_local_transport/level_up_barrier_authority.inl"

bool QueueAuthoritativeLuaItemGrant(
    std::uint64_t content_id,
    std::uint64_t requested_target_participant_id,
    const std::array<std::uint8_t, kParticipantVisualLinkColorBlockBytes>&
        color_state,
    bool color_state_valid,
    std::uint64_t* request_id,
    std::uint64_t* target_participant_id,
    bool* local_target,
    std::string* error_message) {
    return QueueAuthoritativeLuaItemGrantInternal(
        content_id,
        requested_target_participant_id,
        color_state,
        color_state_valid,
        request_id,
        target_participant_id,
        local_target,
        error_message);
}

bool QueueOwnerRoutedLuaRegisteredSpellCast(
    std::uint64_t content_id,
    std::uint64_t requested_owner_participant_id,
    std::uint64_t target_network_actor_id,
    float origin_x,
    float origin_y,
    float aim_x,
    float aim_y,
    std::uint64_t* request_id,
    std::uint64_t* owner_participant_id,
    bool* local_owner,
    std::string* error_message) {
    return QueueOwnerRoutedLuaRegisteredSpellCastInternal(
        content_id,
        requested_owner_participant_id,
        target_network_actor_id,
        origin_x,
        origin_y,
        aim_x,
        aim_y,
        request_id,
        owner_participant_id,
        local_owner,
        error_message);
}

bool QueueLuaUiSimulationAction(
    std::string_view mod_id,
    std::string_view surface_id,
    std::string_view action_id,
    std::uint64_t* request_id,
    std::string* error_message) {
    return QueueLuaUiSimulationActionInternal(
        mod_id, surface_id, action_id, request_id, error_message);
}

bool QueueLuaNetMessage(
    std::string_view mod_id,
    std::string_view channel,
    std::string_view payload,
    std::uint64_t target_participant_id,
    bool broadcast,
    std::uint64_t* message_sequence,
    std::string* error_message) {
    return QueueLuaNetMessageInternal(
        mod_id,
        channel,
        payload,
        target_participant_id,
        broadcast,
        message_sequence,
        error_message);
}

std::vector<LuaRegisteredSpellEffectState>
SnapshotReplicatedLuaRegisteredSpellEffects() {
    std::lock_guard<std::mutex> lock(
        g_lua_registered_spell_effect_snapshot_mutex);
    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    std::vector<LuaRegisteredSpellEffectState> effects;
    for (auto it = g_local_transport
                       .completed_lua_registered_spell_effect_snapshots.begin();
         it != g_local_transport
                   .completed_lua_registered_spell_effect_snapshots.end();) {
        if (now_ms - it->second.received_ms >
            kLuaRegisteredSpellEffectSnapshotExpiryMs) {
            it = g_local_transport
                     .completed_lua_registered_spell_effect_snapshots.erase(it);
            continue;
        }
        effects.insert(
            effects.end(),
            it->second.effects.begin(),
            it->second.effects.end());
        ++it;
    }
    std::sort(
        effects.begin(),
        effects.end(),
        [](const LuaRegisteredSpellEffectState& left,
           const LuaRegisteredSpellEffectState& right) {
            if (left.owner_participant_id != right.owner_participant_id) {
                return left.owner_participant_id < right.owner_participant_id;
            }
            if (left.content_id != right.content_id) {
                return left.content_id < right.content_id;
            }
            return left.effect_id < right.effect_id;
        });
    return effects;
}

bool QueueLocalLevelUpChoice(
    std::uint64_t offer_id,
    std::int32_t option_index,
    std::int32_t option_id,
    std::string* error_message) {
    return QueueLocalLevelUpChoiceInternal(
        offer_id,
        option_index,
        option_id,
        false,
        error_message);
}

}  // namespace sdmod::multiplayer
