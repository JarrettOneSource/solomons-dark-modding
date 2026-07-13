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
#include "steam_bootstrap.h"

#include <algorithm>
#include <array>
#include <charconv>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
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

int CaptureLocalTransportSehCode(EXCEPTION_POINTERS* exception_pointers, DWORD* exception_code);

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
constexpr std::uint64_t kLocalTransportAnimatedLootSnapshotIntervalMs = 16;
constexpr std::uint64_t kLocalTransportSpellEffectSnapshotIntervalMs = 16;
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
constexpr std::uint64_t kNativeProgressionReconcileRetryMs = 250;
constexpr std::uint64_t kNativeProgressionReconcileAuditMs = 1000;
constexpr int kNativeProgressionReconcileMaxApplyCallsPerTick = 8;
constexpr std::size_t kGameplayBeltButtonArrayOffset = 0x5EC;
constexpr std::size_t kGameplayBeltButtonStride = 0xEC;
constexpr std::size_t kBeltButtonTypeOffset = 0xB4;
constexpr std::size_t kBeltButtonSkillEntryIndexOffset = 0xB8;
constexpr std::uint32_t kBeltButtonSkillTypeId = 0x1B67;
constexpr std::uint64_t kRecentRunEnemyDeathSnapshotHoldMs = 2500;
constexpr float kEnemyDamageClaimHpEpsilon = 0.05f;
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
constexpr std::uint32_t kOrbRewardNativeTypeId = 0x07DB;
constexpr std::uint32_t kGoldRewardNativeTypeId = 0x07DC;
constexpr std::uint32_t kItemDropNativeTypeId = 0x07DD;
constexpr std::uint32_t kPotionItemTypeId = 0x1B59;
constexpr std::uint32_t kEtherPrimaryNativeTypeId = 0x07D3;
constexpr std::uint32_t kFireballPrimaryNativeTypeId = 0x07D4;
constexpr std::uint32_t kWaterPrimaryNativeTypeId = 0x07D5;
constexpr std::uint32_t kFireEmberNativeTypeId = 0x07D6;
constexpr std::uint32_t kFirewalkerTrailNativeTypeId = 0x07EE;
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
constexpr float kOrbHealthRewardScale = 25.0f;
constexpr float kOrbManaRewardScale = 40.0f;
constexpr std::size_t kAttachmentStaffVisualStateOffset = 0x84;
constexpr std::size_t kVisualLinkColorBlockOffset = 0x88;
constexpr std::uint32_t kAttachmentStaffItemTypeId = 0x1B5C;
constexpr int kMaxPacketsPerTick = 64;
constexpr float kRenderDriveEffectTimerEpsilon = 0.001f;
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
using NativeActorWorldUnregisterFn = void(__thiscall*)(void* self, void* actor, char remove_from_container);

struct RenderDriveEffectState {
    float timer = 0.0f;
    float progress = 0.0f;
};

struct RecentRunEnemyDeathSnapshot {
    std::uint64_t network_actor_id = 0;
    uintptr_t actor_address = 0;
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
};

struct QueuedHostParticipantVitalsCorrection {
    std::uint64_t target_participant_id = 0;
    float life_current = 0.0f;
    float life_max = 0.0f;
    std::uint8_t transient_status_flags = 0;
    std::int32_t poison_remaining_ticks = 0;
    float poison_damage_per_tick = 0.0f;
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
    std::uint32_t deferred_start_packet_count = 0;
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

struct QueuedLocalLootPickupRequest {
    std::uint64_t network_drop_id = 0;
    std::uint32_t request_sequence = 0;
    bool has_pickup_positions = false;
    float requester_position_x = 0.0f;
    float requester_position_y = 0.0f;
    float drop_position_x = 0.0f;
    float drop_position_y = 0.0f;
};

struct IssuedLevelUpOffer {
    std::uint64_t offer_id = 0;
    std::uint64_t target_participant_id = 0;
    std::uint32_t run_nonce = 0;
    std::int32_t level = 0;
    std::int32_t experience = 0;
    std::vector<BotSkillChoiceOption> options;
    bool resolved = false;
    LevelUpChoiceResultCode result_code = LevelUpChoiceResultCode::Rejected;
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
    bool concentration_selection_valid = false;
    std::int32_t concentration_entry_a = -1;
    std::int32_t concentration_entry_b = -1;
    std::int32_t level = 0;
    std::int32_t experience = 0;
    float move_speed = 0.0f;
    std::uint64_t last_attempt_ms = 0;
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

struct LocalTransportState {
    bool configured = false;
    bool initialized = false;
    bool winsock_initialized = false;
    bool is_host = false;
    bool suppress_local_level_up_fanout_for_debug = false;
    GameplayTransportBackend backend = GameplayTransportBackend::LocalUdp;
    SOCKET socket_handle = INVALID_SOCKET;
    std::uint16_t local_port = 0;
    std::string remote_host;
    std::uint16_t remote_port = 0;
    bool configured_remote_valid = false;
    TransportPeerEndpoint configured_remote;
    std::uint64_t local_peer_id = 0;
    std::uint64_t last_send_ms = 0;
    std::uint64_t last_world_snapshot_send_ms = 0;
    std::uint64_t last_loot_snapshot_send_ms = 0;
    std::uint64_t last_spell_effect_snapshot_send_ms = 0;
    std::uint64_t last_client_host_run_request_ms = 0;
    std::uint32_t next_sequence = 1;
    std::uint32_t world_scene_epoch = 0;
    std::uint64_t packets_sent = 0;
    std::uint64_t packets_received = 0;
    std::uint32_t next_cast_sequence = 1;
    std::uint32_t next_spell_effect_serial = 1;
    std::uint32_t next_air_chain_frame_sequence = 1;
    std::uint32_t next_participant_vitals_correction_sequence = 1;
    std::uint32_t last_applied_participant_vitals_correction_sequence = 0;
    std::uint32_t recent_local_cast_sequence = 0;
    std::uint64_t recent_local_cast_ms = 0;
    std::uint64_t recent_local_cast_target_network_actor_id = 0;
    std::uint32_t last_local_explode_splash_cast_sequence = 0;
    HostLocalExplodeCastBaseline host_local_explode_cast_baseline;
    bool spell_effect_snapshot_had_effects = false;
    std::uint32_t next_enemy_damage_claim_sequence = 1;
    std::uint64_t next_level_up_offer_id = 1;
    std::string world_scene_key;
    std::unordered_map<uintptr_t, std::uint64_t> hub_world_actor_ids_by_address;
    std::unordered_map<uintptr_t, std::uint64_t> run_host_local_world_actor_ids_by_address;
    std::unordered_map<uintptr_t, std::uint64_t> run_loot_drop_ids_by_address;
    std::unordered_map<std::uint64_t, RecentRunEnemyDeathSnapshot> recent_run_enemy_deaths_by_network_id;
    std::unordered_map<std::uint64_t, float> last_synced_enemy_hp_by_network_id;
    std::unordered_map<std::uint64_t, float> last_enemy_claimed_hp_by_network_id;
    std::unordered_map<std::uint64_t, std::uint64_t> pending_lethal_enemy_damage_claim_until_ms;
    std::unordered_map<std::uint64_t, std::uint64_t> rejected_enemy_damage_retry_suppressed_until_ms;
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
    std::unordered_set<std::uint32_t> local_cast_damage_claimed_sequences;
    std::unordered_map<std::uint64_t, IssuedLevelUpOffer> issued_level_up_offers_by_id;
    std::unordered_map<std::uint64_t, PendingHostLevelUpOfferTarget> pending_level_up_offer_targets_by_participant;
    std::unordered_map<std::uint64_t, NativeProgressionReconcileCheckpoint>
        native_progression_reconcile_by_participant;
    std::unordered_set<std::uint64_t> native_applied_level_up_result_offer_ids;
    std::unordered_set<std::uint64_t> accepted_loot_pickup_drop_ids;
    ActiveLocalCastInput active_local_cast_input;
    std::vector<PendingAirChainTerminal> pending_air_chain_terminals;
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
std::vector<QueuedHostParticipantVitalsCorrection>
    g_queued_host_participant_vitals_corrections;
std::vector<QueuedLocalLootPickupRequest> g_queued_local_loot_pickup_requests;
std::vector<QueuedLocalLevelUpChoice> g_queued_local_level_up_choices;
QueuedLocalAirChainFrame g_queued_local_air_chain_frame;
bool g_have_queued_local_air_chain_frame = false;
std::uint32_t g_next_local_loot_pickup_request_sequence = 1;
FireballExplodeEffectConfig g_fireball_explode_effect_config;
bool g_fireball_explode_effect_config_attempted = false;

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

#include "multiplayer_local_transport/skill_config_and_packet_helpers.inl"
#include "multiplayer_local_transport/world_snapshot_capture.inl"
#include "multiplayer_local_transport/loot_snapshot_capture.inl"
bool TryApplyLivePrimarySelectionToProfile(
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

    if (!IsValidCharacterProfile(updated)) {
        return false;
    }

    *profile = updated;
    return true;
}

bool TryApplyLiveBeltSkillLoadoutToProfile(MultiplayerCharacterProfile* profile) {
    if (profile == nullptr || kGameObjectGlobal == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto game_object_global_address =
        memory.ResolveGameAddressOrZero(kGameObjectGlobal);
    uintptr_t gameplay_address = 0;
    if (game_object_global_address == 0 ||
        !memory.TryReadValue(game_object_global_address, &gameplay_address) ||
        gameplay_address == 0) {
        return false;
    }

    auto secondary_entries = profile->loadout.secondary_entry_indices;
    for (std::size_t slot = 0; slot < secondary_entries.size(); ++slot) {
        const auto button_address =
            gameplay_address + kGameplayBeltButtonArrayOffset +
            slot * kGameplayBeltButtonStride;
        std::uint32_t button_type = 0;
        std::int32_t skill_entry_index = -1;
        if (!memory.TryReadField(button_address, kBeltButtonTypeOffset, &button_type) ||
            !memory.TryReadField(
                button_address,
                kBeltButtonSkillEntryIndexOffset,
                &skill_entry_index)) {
            return false;
        }
        secondary_entries[slot] =
            button_type == kBeltButtonSkillTypeId &&
                    skill_entry_index >= 0 &&
                    skill_entry_index <
                        static_cast<std::int32_t>(kParticipantProgressionBookSnapshotMaxEntries)
                ? skill_entry_index
                : -1;
    }

    profile->loadout.secondary_entry_indices = secondary_entries;
    return true;
}

std::vector<TransportPeerEndpoint> BuildKnownSendEndpoints() {
    std::vector<TransportPeerEndpoint> endpoints;
    if (g_local_transport.configured_remote_valid) {
        endpoints.push_back(g_local_transport.configured_remote);
    }
    for (const auto& peer : g_local_transport.peers) {
        const bool already_added = std::any_of(endpoints.begin(), endpoints.end(), [&](const TransportPeerEndpoint& existing) {
            return SameEndpoint(existing, peer.endpoint);
        });
        if (!already_added) {
            endpoints.push_back(peer.endpoint);
        }
    }
    return endpoints;
}

void AddUniqueLevelUpWaitParticipantId(
    std::vector<std::uint64_t>* participant_ids,
    std::uint64_t participant_id) {
    if (participant_ids == nullptr || participant_id == 0) {
        return;
    }
    if (std::find(
            participant_ids->begin(),
            participant_ids->end(),
            participant_id) == participant_ids->end()) {
        participant_ids->push_back(participant_id);
    }
}

bool HasUnresolvedIssuedLevelUpOfferForParticipant(std::uint64_t participant_id) {
    if (participant_id == 0) {
        return false;
    }
    for (const auto& [offer_id, offer] : g_local_transport.issued_level_up_offers_by_id) {
        (void)offer_id;
        if (!offer.resolved && offer.target_participant_id == participant_id) {
            return true;
        }
    }
    return false;
}

std::vector<std::uint64_t> CollectUnresolvedLevelUpOfferParticipantIds() {
    std::vector<std::uint64_t> participant_ids;
    if (!g_local_transport.initialized || !g_local_transport.is_host) {
        return participant_ids;
    }

    participant_ids.reserve(
        g_local_transport.issued_level_up_offers_by_id.size() +
        g_local_transport.pending_level_up_offer_targets_by_participant.size());
    for (const auto& [offer_id, offer] : g_local_transport.issued_level_up_offers_by_id) {
        (void)offer_id;
        if (offer.resolved || offer.target_participant_id == 0) {
            continue;
        }
        AddUniqueLevelUpWaitParticipantId(&participant_ids, offer.target_participant_id);
    }
    for (const auto& [participant_id, pending] : g_local_transport.pending_level_up_offer_targets_by_participant) {
        (void)participant_id;
        AddUniqueLevelUpWaitParticipantId(&participant_ids, pending.target_participant_id);
    }
    std::sort(participant_ids.begin(), participant_ids.end());
    return participant_ids;
}

bool HasPendingLocalLevelUpChoice(const RuntimeState& runtime_state) {
    const auto& offer = runtime_state.active_level_up_offer;
    return offer.valid &&
           !offer.selection_submitted &&
           offer.target_participant_id == g_local_transport.local_peer_id;
}

std::string ResolveParticipantNameForStatus(
    const RuntimeState& runtime_state,
    std::uint64_t participant_id) {
    if (participant_id == g_local_transport.local_peer_id) {
        const auto* local = FindLocalParticipant(runtime_state);
        if (local != nullptr && !local->name.empty()) {
            return local->name;
        }
        return "You";
    }

    const auto* participant = FindParticipant(runtime_state, participant_id);
    if (participant != nullptr && !participant->name.empty()) {
        return participant->name;
    }
    return "Player " + std::to_string(participant_id);
}

std::string BuildLevelUpWaitStatusTextFromIds(
    const RuntimeState& runtime_state,
    const std::vector<std::uint64_t>& participant_ids) {
    if (participant_ids.empty()) {
        return {};
    }

    std::string text = "Waiting for skill picks: ";
    for (std::size_t index = 0; index < participant_ids.size(); ++index) {
        if (index != 0) {
            text += ", ";
        }
        text += ResolveParticipantNameForStatus(runtime_state, participant_ids[index]);
    }
    return text;
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
        local->character_profile.level = player_state.level;
        local->character_profile.experience = player_state.xp;
        if (have_selection_state) {
            const auto previous_element_id = local->character_profile.element_id;
            const auto previous_primary_entry = local->character_profile.loadout.primary_entry_index;
            const auto previous_combo_entry = local->character_profile.loadout.primary_combo_entry_index;
            if (TryApplyLivePrimarySelectionToProfile(selection_state, &local->character_profile)) {
                if (local->character_profile.element_id != previous_element_id ||
                    local->character_profile.loadout.primary_entry_index != previous_primary_entry ||
                    local->character_profile.loadout.primary_combo_entry_index != previous_combo_entry) {
                    Log(
                        "Multiplayer local primary selection refreshed. element_id=" +
                        std::to_string(local->character_profile.element_id) +
                        " primary_entry=" +
                        std::to_string(local->character_profile.loadout.primary_entry_index) +
                        " combo_entry=" +
                        std::to_string(local->character_profile.loadout.primary_combo_entry_index));
                }
            }
        }
        const auto previous_secondary_entries =
            local->character_profile.loadout.secondary_entry_indices;
        if (TryApplyLiveBeltSkillLoadoutToProfile(&local->character_profile) &&
            local->character_profile.loadout.secondary_entry_indices !=
                previous_secondary_entries) {
            std::ostringstream entries;
            for (std::size_t slot = 0;
                 slot < local->character_profile.loadout.secondary_entry_indices.size();
                 ++slot) {
                if (slot != 0) {
                    entries << ',';
                }
                entries << local->character_profile.loadout.secondary_entry_indices[slot];
            }
            Log(
                "Multiplayer local native belt loadout refreshed. entries=" +
                entries.str());
        }
        local->transport_connected = true;
        if (g_local_transport.backend == GameplayTransportBackend::LocalUdp) {
            local->transport_using_relay = false;
        }
        local->runtime.valid = true;
        local->runtime.transform_valid = true;
        local->runtime.in_run = scene_intent.kind == ParticipantSceneIntentKind::Run;
        local->runtime.scene_intent = scene_intent;
        if (local->runtime.life_max > 0.0f &&
            local->runtime.life_current > 0.0f &&
            player_state.max_hp > 0.0f &&
            player_state.hp <= 0.0f) {
            Log(
                "Multiplayer local participant vitals crossed to zero before state publish. participant_id=" +
                std::to_string(g_local_transport.local_peer_id) +
                " hp=" + std::to_string(player_state.hp) +
                "/" + std::to_string(player_state.max_hp) +
                " previous_hp=" + std::to_string(local->runtime.life_current) +
                "/" + std::to_string(local->runtime.life_max) +
                " level=" + std::to_string(player_state.level) +
                " xp=" + std::to_string(player_state.xp) +
                " progression=" + HexString(player_state.progression_address));
        }
        local->runtime.life_current = player_state.hp;
        local->runtime.life_max = player_state.max_hp;
        local->runtime.mana_current = player_state.mp;
        local->runtime.mana_max = player_state.max_mp;
        local->runtime.move_speed = player_state.move_speed;
        local->runtime.persistent_status_flags =
            player_state.persistent_status_flags;
        local->runtime.transient_status_flags =
            player_state.transient_status_flags;
        local->runtime.poison_remaining_ticks =
            player_state.poison_remaining_ticks;
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
        if (have_selection_state) {
            RefreshOwnedConcentrationSelections(
                selection_state.concentration_entry_a,
                selection_state.concentration_entry_b,
                &local->owned_progression);
        }
        RefreshOwnedDerivedStats(
            player_state.derived_stats,
            &local->owned_progression);
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
    packet.authority_participant_id =
        g_local_transport.is_host ? g_local_transport.local_peer_id : 0;
    if (local == nullptr) {
        return packet;
    }

    CopyPacketDisplayName(local->name, &packet);
    packet.ready = local->ready ? 1 : 0;
    packet.in_run = local->runtime.in_run ? 1 : 0;
    packet.transform_valid = local->runtime.transform_valid ? 1 : 0;
    packet.controller_kind = static_cast<std::uint8_t>(ParticipantControllerKind::Native);
    packet.run_nonce = local->runtime.run_nonce;
    packet.participant_vitals_correction_ack_sequence =
        g_local_transport.last_applied_participant_vitals_correction_sequence;
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
    packet.move_speed = local->runtime.move_speed;
    packet.persistent_status_flags =
        local->runtime.persistent_status_flags;
    packet.transient_status_flags =
        local->runtime.transient_status_flags;
    packet.poison_remaining_ticks =
        local->runtime.poison_remaining_ticks;
    packet.experience_current = local->runtime.experience_current;
    packet.experience_next = local->runtime.experience_next;
    packet.owned_gold = local->owned_progression.gold;
    packet.gold_revision = local->owned_progression.gold_revision;
    packet.inventory_revision = local->owned_progression.inventory_revision;
    packet.spellbook_revision = local->owned_progression.spellbook_revision;
    packet.statbook_revision = local->owned_progression.statbook_revision;
    packet.loadout_revision = local->owned_progression.loadout_revision;
    packet.concentration_revision = local->owned_progression.concentration_revision;
    packet.concentration_selection_valid =
        local->owned_progression.concentration_selection_valid ? 1 : 0;
    packet.concentration_entry_a = local->owned_progression.concentration_entry_a;
    packet.concentration_entry_b = local->owned_progression.concentration_entry_b;
    BuildDerivedStatPacketState(
        local->owned_progression,
        &packet.derived_stat_revision,
        &packet.derived_stats);
    if (g_local_transport.is_host) {
        const auto waiting_participant_ids = CollectUnresolvedLevelUpOfferParticipantIds();
        packet.level_up_pause_active = waiting_participant_ids.empty() ? 0 : 1;
        const auto waiting_count =
            (std::min)(
                waiting_participant_ids.size(),
                static_cast<std::size_t>(kLevelUpWaitStatusMaxParticipants));
        packet.level_up_waiting_count = static_cast<std::uint8_t>(waiting_count);
        for (std::size_t index = 0; index < waiting_count; ++index) {
            packet.level_up_waiting_participant_ids[index] = waiting_participant_ids[index];
        }
    }
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
    std::uint32_t valid_recent_death_count = 0;
    if (run_scene) {
        for (const auto& [network_actor_id, death_snapshot] :
             g_local_transport.recent_run_enemy_deaths_by_network_id) {
            if (network_actor_id != 0 &&
                death_snapshot.native_type_id != 0 &&
                std::isfinite(death_snapshot.max_hp) &&
                death_snapshot.max_hp > 0.0f) {
                valid_recent_death_count += 1;
            }
        }
    }
    constexpr std::uint32_t kWorldSnapshotRecentDeathReservedSlots = 16;
    const std::uint32_t reserved_recent_death_slots =
        run_scene
            ? (std::min<std::uint32_t>)(
                  valid_recent_death_count,
                  (std::min<std::uint32_t>)(kWorldSnapshotRecentDeathReservedSlots, kWorldSnapshotMaxActors))
            : 0;
    const std::uint32_t live_actor_snapshot_budget =
        kWorldSnapshotMaxActors > reserved_recent_death_slots
            ? kWorldSnapshotMaxActors - reserved_recent_death_slots
            : 0;
    std::unordered_set<std::uint64_t> included_actor_ids;
    std::uint32_t total_actor_count = 0;
    for (const auto& actor : actors) {
        if (!ShouldReplicateWorldActor(actor, scene_intent.kind)) {
            continue;
        }
        if (run_scene &&
            actor.tracked_enemy &&
            actor.dead &&
            HasRecentRunEnemyDeathSnapshotForActor(actor.actor_address)) {
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
        if (built.actor_count >= live_actor_snapshot_budget) {
            continue;
        }

        auto& snapshot = built.actors[built.actor_count];
        snapshot.network_actor_id = network_actor_id;
        snapshot.native_type_id = actor.object_type_id;
        snapshot.enemy_type = actor.enemy_type;
        snapshot.actor_slot = actor.actor_slot;
        snapshot.world_slot = actor.world_slot;
        snapshot.target_actor_slot = -1;
        snapshot.target_world_slot = -1;
        if (run_scene && actor.tracked_enemy) {
            snapshot.flags |= WorldActorSnapshotFlagTargetAuthoritative;
            snapshot.target_participant_id = ResolveRunEnemyTargetParticipantId(actor.actor_address);
            (void)PopulateRunEnemyNativeTargetSnapshot(actor.actor_address, &snapshot);
        }
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
        if (run_scene &&
            IsReplicatedRunPlayerCreatedActorType(actor.object_type_id)) {
            snapshot.flags |= WorldActorSnapshotFlagPlayerCreated;
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
            snapshot.target_actor_slot = -1;
            snapshot.target_world_slot = -1;
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
        if ((snapshot.flags & LootDropSnapshotFlagActive) == 0) {
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

std::uint64_t LootSnapshotIntervalForPacket(const LootSnapshotPacket& packet) {
    for (std::size_t index = 0; index < packet.drop_count; ++index) {
        const auto& drop = packet.drops[index];
        const auto drop_kind = LootDropKindFromPacketValue(drop.drop_kind);
        const bool active = (drop.flags & LootDropSnapshotFlagActive) != 0;
        if (!active) {
            continue;
        }
        if (drop_kind == LootDropKind::Gold || drop_kind == LootDropKind::Orb) {
            return kLocalTransportAnimatedLootSnapshotIntervalMs;
        }
    }
    return kLocalTransportLootSnapshotIntervalMs;
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
    // Run enemies own health directly on their arena-actor object.  Do not
    // probe the wizard-only actor+0x200 progression seam here: on stock enemy
    // classes that field has unrelated meaning, and a readable pointer is not
    // proof that it names a progression object.  Writing HP through that
    // pointer corrupted native callbacks/heap metadata with values such as
    // 0x42200000 (40.0f) during clustered spell tests.
    return
        memory.TryWriteField(actor_address, kEnemyMaxHpOffset, max_hp) &&
        memory.TryWriteField(actor_address, kEnemyCurrentHpOffset, clamped_hp);
}

#include "multiplayer_local_transport/cast_target_resolution.inl"
SteamNetworkSendMode SteamSendModeForPacket(const void* packet, std::size_t packet_size) {
    if (packet == nullptr || packet_size < sizeof(PacketHeader)) {
        return SteamNetworkSendMode::ReliableNoNagle;
    }
    PacketHeader header{};
    std::memcpy(&header, packet, sizeof(header));
    const auto kind = static_cast<PacketKind>(header.kind);
    if (kind == PacketKind::Cast && packet_size == sizeof(CastPacket)) {
        CastPacket cast{};
        std::memcpy(&cast, packet, sizeof(cast));
        return cast.input_phase == static_cast<std::uint8_t>(CastInputPhase::Held)
            ? SteamNetworkSendMode::UnreliableNoNagle
            : SteamNetworkSendMode::ReliableNoNagle;
    }
    switch (kind) {
    case PacketKind::State:
    case PacketKind::WorldSnapshot:
    case PacketKind::LootSnapshot:
    case PacketKind::SpellEffectSnapshot:
    case PacketKind::AirChainSnapshot:
        return SteamNetworkSendMode::UnreliableNoNagle;
    default:
        return SteamNetworkSendMode::ReliableNoNagle;
    }
}

void SendBufferToEndpoint(
    const void* packet,
    std::size_t packet_size,
    const TransportPeerEndpoint& endpoint) {
    if (packet == nullptr || packet_size == 0 || packet_size > static_cast<std::size_t>((std::numeric_limits<int>::max)())) {
        return;
    }
    if (endpoint.backend == GameplayTransportBackend::Steam) {
        std::int32_t result_code = 0;
        if (SteamSendNetworkMessage(
                endpoint.steam_id,
                packet,
                packet_size,
                SteamSendModeForPacket(packet, packet_size),
                &result_code)) {
            g_local_transport.packets_sent += 1;
        }
        return;
    }
    const int sent = sendto(
        g_local_transport.socket_handle,
        reinterpret_cast<const char*>(packet),
        static_cast<int>(packet_size),
        0,
        reinterpret_cast<const sockaddr*>(&endpoint.udp_address),
        sizeof(endpoint.udp_address));
    if (sent == static_cast<int>(packet_size)) {
        g_local_transport.packets_sent += 1;
    }
}

template <typename Packet>
void SendPacketToEndpoint(const Packet& packet, const TransportPeerEndpoint& endpoint) {
    SendBufferToEndpoint(&packet, sizeof(packet), endpoint);
}

void PublishWorldSnapshotRuntimeInfo(const WorldSnapshotPacket& packet, std::uint64_t now_ms);
void PublishLootSnapshotRuntimeInfo(const LootSnapshotPacket& packet, std::uint64_t now_ms);
int ApplyHostAcceptedFireballExplodeSplash(
    const EnemyDamageClaimPacket& packet,
    const ParticipantInfo* participant,
    std::uint64_t now_ms,
    const SDModSceneActorState& primary_target);
void CaptureHostLocalFireballExplodeBaseline(
    const ParticipantInfo& local,
    const CastPacket& packet,
    std::uint64_t now_ms);
void ReconcileHostLocalFireballExplodeSplash(std::uint64_t now_ms);

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

    ReconcileHostLocalFireballExplodeSplash(now_ms);

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
    if (!g_local_transport.is_host) {
        return;
    }

    LootSnapshotPacket packet{};
    if (!BuildLocalLootSnapshotPacket(&packet)) {
        return;
    }

    const auto send_interval_ms = LootSnapshotIntervalForPacket(packet);
    if (now_ms - g_local_transport.last_loot_snapshot_send_ms < send_interval_ms) {
        return;
    }
    g_local_transport.last_loot_snapshot_send_ms = now_ms;

    PublishLootSnapshotRuntimeInfo(packet, now_ms);

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
        packet.requester_position_x =
            request.has_pickup_positions ? request.requester_position_x : local->runtime.position_x;
        packet.requester_position_y =
            request.has_pickup_positions ? request.requester_position_y : local->runtime.position_y;
        packet.drop_position_x =
            request.has_pickup_positions
                ? request.drop_position_x
                : (drop != nullptr ? drop->position_x : local->runtime.position_x);
        packet.drop_position_y =
            request.has_pickup_positions
                ? request.drop_position_y
                : (drop != nullptr ? drop->position_y : local->runtime.position_y);

        for (const auto& endpoint : endpoints) {
            SendPacketToEndpoint(packet, endpoint);
        }
        Log(
            "Multiplayer loot pickup request sent. participant_id=" +
            std::to_string(packet.participant_id) +
            " request_sequence=" + std::to_string(packet.request_sequence) +
            " network_drop_id=" + std::to_string(packet.network_drop_id) +
            " requester_pos=(" + std::to_string(packet.requester_position_x) + "," +
            std::to_string(packet.requester_position_y) + ")" +
            " drop_pos=(" + std::to_string(packet.drop_position_x) + "," +
            std::to_string(packet.drop_position_y) + ")" +
            " captured_positions=" + std::to_string(request.has_pickup_positions ? 1 : 0));
    }
}

template <typename Packet>
void SendPacketToParticipantOrPeers(const Packet& packet, std::uint64_t participant_id) {
    bool sent_to_target = false;
    for (const auto& peer : g_local_transport.peers) {
        if (peer.participant_id != participant_id) {
            continue;
        }
        SendPacketToEndpoint(packet, peer.endpoint);
        sent_to_target = true;
    }
    if (sent_to_target) {
        return;
    }

    const auto endpoints = BuildKnownSendEndpoints();
    for (const auto& endpoint : endpoints) {
        SendPacketToEndpoint(packet, endpoint);
    }
}

std::vector<QueuedLocalLevelUpChoice> TakeQueuedLocalLevelUpChoices() {
    std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
    std::vector<QueuedLocalLevelUpChoice> choices;
    choices.swap(g_queued_local_level_up_choices);
    return choices;
}

bool TryResolveOfferedLevelUpOption(
    const std::vector<LevelUpChoiceOptionState>& options,
    std::int32_t option_index,
    std::int32_t option_id,
    LevelUpChoiceOptionState* resolved) {
    if (resolved != nullptr) {
        *resolved = LevelUpChoiceOptionState{};
    }
    if (option_index > 0) {
        const auto zero_based_index = static_cast<std::size_t>(option_index - 1);
        if (zero_based_index >= options.size()) {
            return false;
        }
        if (option_id >= 0 && options[zero_based_index].option_id != option_id) {
            return false;
        }
        if (resolved != nullptr) {
            *resolved = options[zero_based_index];
        }
        return true;
    }
    if (option_id >= 0) {
        const auto it = std::find_if(
            options.begin(),
            options.end(),
            [&](const LevelUpChoiceOptionState& option) {
                return option.option_id == option_id;
            });
        if (it == options.end()) {
            return false;
        }
        if (resolved != nullptr) {
            *resolved = *it;
        }
        return true;
    }
    return false;
}

LevelUpChoiceOptionState ToRuntimeLevelUpOption(const BotSkillChoiceOption& option) {
    LevelUpChoiceOptionState state;
    state.option_id = option.option_id;
    state.apply_count = option.apply_count;
    return state;
}

bool TryResolveIssuedLevelUpOption(
    const IssuedLevelUpOffer& offer,
    std::int32_t option_index,
    std::int32_t option_id,
    BotSkillChoiceOption* resolved) {
    if (resolved != nullptr) {
        *resolved = BotSkillChoiceOption{};
    }
    if (option_index > 0) {
        const auto zero_based_index = static_cast<std::size_t>(option_index - 1);
        if (zero_based_index >= offer.options.size()) {
            return false;
        }
        if (option_id >= 0 && offer.options[zero_based_index].option_id != option_id) {
            return false;
        }
        if (resolved != nullptr) {
            *resolved = offer.options[zero_based_index];
        }
        return true;
    }
    if (option_id >= 0) {
        const auto it = std::find_if(
            offer.options.begin(),
            offer.options.end(),
            [&](const BotSkillChoiceOption& option) {
                return option.option_id == option_id;
            });
        if (it == offer.options.end()) {
            return false;
        }
        if (resolved != nullptr) {
            *resolved = *it;
        }
        return true;
    }
    return false;
}

void SendQueuedLevelUpChoices() {
    if (!IsLocalTransportClient()) {
        return;
    }

    auto choices = TakeQueuedLocalLevelUpChoices();
    if (choices.empty()) {
        return;
    }

    const auto runtime_state = SnapshotRuntimeState();
    const auto& offer = runtime_state.active_level_up_offer;
    if (!offer.valid) {
        return;
    }

    const auto endpoints = BuildKnownSendEndpoints();
    if (endpoints.empty()) {
        return;
    }

    for (const auto& choice : choices) {
        if (choice.offer_id != offer.offer_id) {
            Log(
                "Multiplayer level-up choice skipped; offer id is stale. queued_offer_id=" +
                std::to_string(choice.offer_id) +
                " active_offer_id=" + std::to_string(offer.offer_id));
            continue;
        }

        LevelUpChoicePacket packet{};
        packet.header = MakePacketHeader(PacketKind::LevelUpChoice, g_local_transport.next_sequence++);
        packet.participant_id = g_local_transport.local_peer_id;
        packet.offer_id = choice.offer_id;
        packet.run_nonce = offer.run_nonce;
        packet.option_index = choice.option_index;
        packet.option_id = choice.option_id;
        for (const auto& endpoint : endpoints) {
            SendPacketToEndpoint(packet, endpoint);
        }
        Log(
            "Multiplayer level-up choice sent. participant_id=" +
            std::to_string(packet.participant_id) +
            " offer_id=" + std::to_string(packet.offer_id) +
            " option_index=" + std::to_string(packet.option_index) +
            " option_id=" + std::to_string(packet.option_id));
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
        if (TryFindLocalRunEnemyByNetworkIdInternal(event.target_network_actor_id, &target_actor) &&
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
        (event.cast_kind != CastKind::Primary &&
         event.cast_kind != CastKind::Secondary) ||
        (event.cast_kind == CastKind::Secondary &&
         (event.secondary_slot < 0 ||
          event.secondary_slot >=
              static_cast<std::int32_t>(kSecondaryLoadoutSlotCount))) ||
        (event.cast_kind == CastKind::Primary && event.secondary_slot != -1) ||
        (event.cast_kind == CastKind::Secondary && phase != CastInputPhase::Pressed) ||
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
    built.cast_kind = static_cast<std::uint8_t>(event.cast_kind);
    built.secondary_slot = static_cast<std::int8_t>(event.secondary_slot);
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
    for (std::size_t index = 0;
         index < local.character_profile.loadout.secondary_entry_indices.size();
         ++index) {
        built.queued_secondary_entry_indices[index] =
            event.cast_kind == CastKind::Secondary &&
                    event.has_live_secondary_loadout
                ? event.live_secondary_entry_indices[index]
                : local.character_profile.loadout.secondary_entry_indices[index];
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
    event->cast_kind = CastKind::Primary;
    event->secondary_slot = -1;
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
    active.run_nonce = packet.run_nonce;
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

void SendCastPacketToEndpoints(
    const CastPacket& packet,
    const std::vector<TransportPeerEndpoint>& endpoints) {
    for (const auto& endpoint : endpoints) {
        SendPacketToEndpoint(packet, endpoint);
    }
    Log(
        "Multiplayer local cast sent. participant_id=" +
        std::to_string(packet.participant_id) +
        " cast_sequence=" + std::to_string(packet.cast_sequence) +
        " kind=" +
        std::string(
            static_cast<CastKind>(packet.cast_kind) == CastKind::Secondary
                ? "secondary"
                : "primary") +
        " secondary_slot=" + std::to_string(packet.secondary_slot) +
        " phase=" + CastInputPhaseLabel(packet.input_phase) +
        " skill_id=" + std::to_string(packet.skill_id) +
        " target_network_actor_id=" + std::to_string(packet.target_network_actor_id));
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
    float target_position_y,
    bool target_position_optional = false,
    bool baseline_prevalidated = false);

bool TryResolveLocalPrimaryCastClaimDamage(
    const ParticipantInfo& local,
    const CastPacket& packet,
    float authoritative_hp,
    float authoritative_max_hp,
    float* damage_out,
    std::string* error_message) {
    if (damage_out != nullptr) {
        *damage_out = 0.0f;
    }
    if (error_message != nullptr) {
        error_message->clear();
    }
    auto reject = [&](const char* reason) {
        if (error_message != nullptr) {
            *error_message = reason;
        }
        return false;
    };

    if (damage_out == nullptr) {
        return reject("missing_damage_out");
    }
    if (static_cast<CastKind>(packet.cast_kind) != CastKind::Primary ||
        static_cast<CastInputPhase>(packet.input_phase) != CastInputPhase::Pressed ||
        packet.target_network_actor_id == 0 ||
        !std::isfinite(authoritative_hp) ||
        !std::isfinite(authoritative_max_hp) ||
        authoritative_max_hp <= 0.0f ||
        authoritative_hp <= kEnemyDamageClaimHpEpsilon) {
        return reject("not_claimable_primary_cast");
    }

    SDModPlayerState player_state;
    if (!TryGetPlayerState(&player_state) ||
        !player_state.valid ||
        player_state.progression_address == 0) {
        return reject("local_progression_unavailable");
    }

    NativePrimarySpellSelection selection{};
    std::string selection_error;
    bool selection_resolved = false;
    if (packet.skill_id > 0) {
        selection_resolved = TryResolveNativePrimarySelectionFromSkillId(
            player_state.progression_address,
            packet.skill_id,
            &selection,
            &selection_error);
    }
    if (!selection_resolved) {
        selection_error.clear();
        selection_resolved =
            TryResolveNativePrimarySelectionForProfile(local.character_profile, &selection);
    }
    if (!selection_resolved) {
        if (error_message != nullptr) {
            *error_message =
                selection_error.empty()
                    ? std::string("primary_selection_unresolved")
                    : ("primary_selection_unresolved: " + selection_error);
        }
        return false;
    }
    if (!selection.pure_primary) {
        return reject("primary_cast_not_pure_projectile");
    }

    NativePrimarySpellStats stats{};
    std::string stats_error;
    if (!TryResolveNativePrimarySpellStats(
            player_state.progression_address,
            selection,
            &stats,
            &stats_error)) {
        if (error_message != nullptr) {
            *error_message =
                stats_error.empty()
                    ? std::string("primary_native_stats_unresolved")
                    : ("primary_native_stats_unresolved: " + stats_error);
        }
        return false;
    }
    if (!std::isfinite(stats.damage) || stats.damage <= kEnemyDamageClaimHpEpsilon) {
        return reject("primary_native_damage_invalid");
    }
    // The Skills_Wizard damage output is a native diagnostic value, but some
    // stock primaries (notably Fireball) publish it in a spell-specific scale
    // rather than direct enemy-HP units.  Never turn that value into an
    // immediate network hit unless it is already inside the same bounded HP
    // envelope accepted by the authoritative claim validator.  Otherwise the
    // normal local-HP delta path will report the real native impact.
    const float maximum_hp_scaled_damage =
        (std::min)(
            kEnemyDamageClaimAbsoluteCap,
            authoritative_max_hp * kEnemyDamageClaimMaxHpFactor);
    if (!std::isfinite(maximum_hp_scaled_damage) ||
        maximum_hp_scaled_damage <= kEnemyDamageClaimHpEpsilon ||
        stats.damage > maximum_hp_scaled_damage) {
        return reject("primary_native_damage_not_hp_scaled");
    }

    *damage_out = stats.damage;
    return true;
}

bool TrySendLocalCastEnemyDamageClaim(
    const RuntimeState& runtime_state,
    const ParticipantInfo& local,
    const CastPacket& packet) {
    if (!IsLocalTransportClient() ||
        packet.cast_sequence == 0 ||
        packet.target_network_actor_id == 0 ||
        static_cast<CastInputPhase>(packet.input_phase) != CastInputPhase::Pressed ||
        g_local_transport.local_cast_damage_claimed_sequences.find(packet.cast_sequence) !=
            g_local_transport.local_cast_damage_claimed_sequences.end() ||
        !runtime_state.world_snapshot.valid ||
        runtime_state.world_snapshot.scene_intent.kind != ParticipantSceneIntentKind::Run) {
        return false;
    }

    SDModSceneActorState local_target;
    if (!TryFindLocalRunEnemyByNetworkIdInternal(packet.target_network_actor_id, &local_target) ||
        !IsRunEnemyAlignedWithPlayerCastAim(
            local_target,
            packet.position_x,
            packet.position_y,
            packet.direction_x,
            packet.direction_y,
            packet.aim_target_x,
            packet.aim_target_y)) {
        Log(
            "Multiplayer local cast damage claim skipped. reason=target_not_aligned"
            " cast_sequence=" + std::to_string(packet.cast_sequence) +
            " target_network_actor_id=" + std::to_string(packet.target_network_actor_id));
        return false;
    }

    const auto* authoritative_actor = FindSnapshotActorByNetworkId(
        runtime_state.world_snapshot,
        packet.target_network_actor_id);
    if (authoritative_actor == nullptr ||
        !authoritative_actor->tracked_enemy ||
        authoritative_actor->run_static ||
        authoritative_actor->dead ||
        !std::isfinite(authoritative_actor->hp) ||
        !std::isfinite(authoritative_actor->max_hp) ||
        authoritative_actor->max_hp <= 0.0f ||
        authoritative_actor->hp <= kEnemyDamageClaimHpEpsilon) {
        Log(
            "Multiplayer local cast damage claim skipped. reason=authoritative_target_not_live"
            " cast_sequence=" + std::to_string(packet.cast_sequence) +
            " target_network_actor_id=" + std::to_string(packet.target_network_actor_id));
        return false;
    }

    const float authoritative_hp =
        ClampEnemyHp(authoritative_actor->hp, authoritative_actor->max_hp);
    float claim_damage = 0.0f;
    std::string damage_error;
    if (!TryResolveLocalPrimaryCastClaimDamage(
            local,
            packet,
            authoritative_hp,
            authoritative_actor->max_hp,
            &claim_damage,
            &damage_error)) {
        Log(
            "Multiplayer local cast damage claim skipped. reason=" + damage_error +
            " cast_sequence=" + std::to_string(packet.cast_sequence) +
            " target_network_actor_id=" + std::to_string(packet.target_network_actor_id));
        return false;
    }

    const float claimed_after_hp =
        ClampEnemyHp(authoritative_hp - claim_damage, authoritative_actor->max_hp);
    if (claimed_after_hp + kEnemyDamageClaimHpEpsilon >= authoritative_hp) {
        return false;
    }
    if (!HasReplicatedRunEnemyDamageBaseline(packet.target_network_actor_id)) {
        MarkReplicatedRunEnemyDamageBaseline(packet.target_network_actor_id, authoritative_hp);
    }

    const bool sent = SendLocalEnemyDamageClaim(
        runtime_state,
        local,
        packet.target_network_actor_id,
        packet.skill_id,
        authoritative_hp,
        claimed_after_hp,
        authoritative_actor->max_hp,
        authoritative_actor->position_x,
        authoritative_actor->position_y);
    if (!sent) {
        return false;
    }

    g_local_transport.local_cast_damage_claimed_sequences.insert(packet.cast_sequence);
    if (g_local_transport.local_cast_damage_claimed_sequences.size() > 256) {
        g_local_transport.local_cast_damage_claimed_sequences.clear();
        g_local_transport.local_cast_damage_claimed_sequences.insert(packet.cast_sequence);
    }
    Log(
        "Multiplayer local cast damage claim sent from cast packet. cast_sequence=" +
        std::to_string(packet.cast_sequence) +
        " target_network_actor_id=" + std::to_string(packet.target_network_actor_id) +
        " damage=" + std::to_string(claim_damage) +
        " before_hp=" + std::to_string(authoritative_hp) +
        " after_hp=" + std::to_string(claimed_after_hp));
    return true;
}

void ReleaseActiveLocalCastInputForReplacement(
    const RuntimeState& runtime_state,
    const ParticipantInfo& local,
    const std::vector<TransportPeerEndpoint>& endpoints,
    std::uint64_t now_ms,
    std::uint64_t replacement_native_queue_id) {
    if (!g_local_transport.active_local_cast_input.active) {
        return;
    }

    const auto replaced_cast = g_local_transport.active_local_cast_input;
    const auto replaced_cast_sequence = replaced_cast.cast_sequence;
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

    if (replaced_cast.skill_id == kAirPrimarySkillId) {
        QueueAirChainTerminal(
            replaced_cast.cast_sequence,
            replaced_cast.run_nonce,
            now_ms);
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
        g_local_transport.recent_local_cast_sequence = cast_sequence;
        g_local_transport.recent_local_cast_ms = now_ms;
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
        if (event.cast_kind == CastKind::Primary) {
            CaptureHostLocalFireballExplodeBaseline(*local, packet, now_ms);
        }
        g_local_transport.recent_local_cast_target_network_actor_id =
            packet.target_network_actor_id;

        SendCastPacketToEndpoints(packet, endpoints);
        if (event.cast_kind == CastKind::Secondary &&
            event.skill_id == 0x33) {
            std::string dampen_error;
            if (!QueueMultiplayerDampenEffect(
                    packet.participant_id,
                    packet.cast_sequence,
                    packet.position_x,
                    packet.position_y,
                    &dampen_error)) {
                Log(
                    "Multiplayer local Dampen behavior queue failed. cast_sequence=" +
                    std::to_string(packet.cast_sequence) +
                    " error=" + dampen_error);
            }
        }
        (void)TrySendLocalCastEnemyDamageClaim(runtime_state, *local, packet);
        if (event.native_queue_id != 0) {
            Log(
                "Multiplayer local native cast sent. native_queue_id=" +
                std::to_string(event.native_queue_id) +
                " cast_sequence=" + std::to_string(cast_sequence) +
                " participant_id=" + std::to_string(packet.participant_id));
        }
        if (event.cast_kind == CastKind::Primary) {
            RememberActiveLocalCastInput(event, packet, now_ms);
        }
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
        const auto abandoned_cast = g_local_transport.active_local_cast_input;
        if (abandoned_cast.skill_id == kAirPrimarySkillId) {
            QueueAirChainTerminal(
                abandoned_cast.cast_sequence,
                abandoned_cast.run_nonce,
                now_ms);
        }
        g_local_transport.active_local_cast_input = ActiveLocalCastInput{};
        return;
    }

    const auto endpoints = BuildKnownSendEndpoints();
    if (endpoints.empty()) {
        return;
    }

    QueuedLocalCastEvent event{};
    if (!TryRefreshActiveLocalCastEvent(&event)) {
        const auto abandoned_cast = g_local_transport.active_local_cast_input;
        if (abandoned_cast.skill_id == kAirPrimarySkillId) {
            QueueAirChainTerminal(
                abandoned_cast.cast_sequence,
                abandoned_cast.run_nonce,
                now_ms);
        }
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
        const auto released_cast = g_local_transport.active_local_cast_input;
        if (released_cast.skill_id == kAirPrimarySkillId) {
            QueueAirChainTerminal(
                released_cast.cast_sequence,
                released_cast.run_nonce,
                now_ms);
        }
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
    float target_position_y,
    bool target_position_optional,
    bool baseline_prevalidated) {
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
    if (IsLocalTransportClient() &&
        !baseline_prevalidated &&
        !HasReplicatedRunEnemyDamageBaseline(network_actor_id)) {
        if (local_hp + kEnemyDamageClaimHpEpsilon >= authoritative_hp) {
            MarkReplicatedRunEnemyDamageBaseline(network_actor_id, authoritative_hp);
        }
        Log(
            "Multiplayer enemy damage claim suppressed until first authoritative HP baseline. "
            "target_network_actor_id=" + std::to_string(network_actor_id) +
            " authoritative_hp=" + std::to_string(authoritative_hp) +
            " local_hp=" + std::to_string(local_hp));
        return false;
    }
    if (local_hp + kEnemyDamageClaimHpEpsilon >= authoritative_hp) {
        g_local_transport.last_enemy_claimed_hp_by_network_id.erase(network_actor_id);
        g_local_transport.pending_lethal_enemy_damage_claim_until_ms.erase(network_actor_id);
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
    packet.claim_flags = target_position_optional
                             ? kEnemyDamageClaimFlagTargetPositionOptional
                             : 0;
    if (packet.lethal != 0) {
        g_local_transport.pending_lethal_enemy_damage_claim_until_ms[network_actor_id] =
            now_ms + kEnemyDamageLethalClaimPendingSuppressMs;
    }

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
            sdmod::ClearManualRunEnemyFreeze(local_actor_address);
            if (local_death_called) {
                sdmod::MarkReplicatedRunEnemyDeathPresented(network_actor_id);
                sdmod::SuppressClientLocalLootActors("client_local_enemy_death_claim");
            }
        }
    }
    g_local_transport.last_enemy_claimed_hp_by_network_id[network_actor_id] = local_hp;
    Log(
        "Multiplayer enemy damage claim sent. target_network_actor_id=" +
        std::to_string(network_actor_id) +
        " sequence=" + std::to_string(packet.claim_sequence) +
        " damage=" + std::to_string(packet.claimed_damage) +
        " after_hp=" + std::to_string(packet.client_after_hp) +
        " baseline_prevalidated=" + std::to_string(baseline_prevalidated ? 1 : 0) +
        " local_death_called=" + std::to_string(local_death_called ? 1 : 0) +
        " local_death_seh=" + HexString(static_cast<uintptr_t>(local_death_exception_code)));
    return true;
}

bool HasLocalPendingLethalEnemyDamageClaimInternal(
    std::uint64_t network_actor_id,
    std::uint64_t now_ms) {
    if (!IsLocalTransportClient() || network_actor_id == 0) {
        return false;
    }
    if (now_ms == 0) {
        now_ms = static_cast<std::uint64_t>(GetTickCount64());
    }
    const auto pending_it =
        g_local_transport.pending_lethal_enemy_damage_claim_until_ms.find(network_actor_id);
    if (pending_it == g_local_transport.pending_lethal_enemy_damage_claim_until_ms.end()) {
        return false;
    }
    if (pending_it->second > now_ms) {
        return true;
    }
    g_local_transport.pending_lethal_enemy_damage_claim_until_ms.erase(pending_it);
    return false;
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
            claim.target_position_y,
            claim.target_position_optional,
            claim.baseline_prevalidated);
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
            if (binding.network_actor_id != 0 && (binding.parked || binding.removed)) {
                ClearReplicatedRunEnemyDamageBaseline(binding.network_actor_id);
            }
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
            ClearReplicatedRunEnemyDamageBaseline(binding.network_actor_id);
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
        const float authoritative_max_hp = authoritative_actor->max_hp;
        if (std::fabs(local_actor.max_hp - authoritative_max_hp) > kEnemyDamageClaimHpEpsilon) {
            ClearReplicatedRunEnemyDamageBaseline(binding.network_actor_id);
            continue;
        }
        const float authoritative_hp =
            ClampEnemyHp(authoritative_actor->hp, authoritative_max_hp);
        if (!HasReplicatedRunEnemyDamageBaseline(binding.network_actor_id)) {
            if (local_hp + kEnemyDamageClaimHpEpsilon >= authoritative_hp) {
                MarkReplicatedRunEnemyDamageBaseline(binding.network_actor_id, authoritative_hp);
            }
            continue;
        }
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
            local_actor.y,
            true);
    }
}

void RelayStatePacketToPeers(
    const StatePacket& packet,
    const TransportPeerEndpoint& source) {
    if (!g_local_transport.is_host) {
        return;
    }

    std::vector<TransportPeerEndpoint> endpoints;
    for (const auto& peer : g_local_transport.peers) {
        if (SameEndpoint(peer.endpoint, source)) {
            continue;
        }
        const bool already_added = std::any_of(endpoints.begin(), endpoints.end(), [&](const TransportPeerEndpoint& existing) {
            return SameEndpoint(existing, peer.endpoint);
        });
        if (!already_added) {
            endpoints.push_back(peer.endpoint);
        }
    }

    auto relayed_packet = packet;
    relayed_packet.authority_participant_id = g_local_transport.local_peer_id;
    for (const auto& endpoint : endpoints) {
        SendPacketToEndpoint(relayed_packet, endpoint);
    }
}

template <typename Packet>
void RelayPacketToPeers(const Packet& packet, const TransportPeerEndpoint& source) {
    if (!g_local_transport.is_host) {
        return;
    }

    std::vector<TransportPeerEndpoint> endpoints;
    for (const auto& peer : g_local_transport.peers) {
        if (SameEndpoint(peer.endpoint, source)) {
            continue;
        }
        const bool already_added = std::any_of(endpoints.begin(), endpoints.end(), [&](const TransportPeerEndpoint& existing) {
            return SameEndpoint(existing, peer.endpoint);
        });
        if (!already_added) {
            endpoints.push_back(peer.endpoint);
        }
    }

    for (const auto& endpoint : endpoints) {
        SendPacketToEndpoint(packet, endpoint);
    }
}

bool IsConfiguredRemoteAuthorityEndpoint(const TransportPeerEndpoint& from) {
    return g_local_transport.configured_remote_valid &&
           SameEndpoint(from, g_local_transport.configured_remote);
}

bool IsAuthoritativeHostStatePacket(
    const StatePacket& packet,
    const TransportPeerEndpoint& from) {
    return IsLocalTransportClient() &&
           IsConfiguredRemoteAuthorityEndpoint(from) &&
           packet.authority_participant_id != 0 &&
           packet.participant_id == packet.authority_participant_id;
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
    const TransportPeerEndpoint& from,
    std::uint64_t now_ms) {
    if (!IsLocalTransportClient() ||
        scene_intent.kind != ParticipantSceneIntentKind::Run ||
        packet.ready == 0 ||
        !IsAuthoritativeHostStatePacket(packet, from)) {
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

void ApplyRemoteStatePacket(
    const StatePacket& packet,
    const TransportPeerEndpoint& from,
    std::uint64_t now_ms) {
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
    const auto transient_status_flags = static_cast<std::uint8_t>(
        packet.transient_status_flags &
        (kParticipantTransientStatusValueMask |
         ParticipantTransientStatusFlagSnapshotValid));
    const bool poison_snapshot_active =
        (transient_status_flags &
         (ParticipantTransientStatusFlagSnapshotValid |
          ParticipantTransientStatusFlagPoisoned)) ==
        (ParticipantTransientStatusFlagSnapshotValid |
         ParticipantTransientStatusFlagPoisoned);
    const auto poison_remaining_ticks = poison_snapshot_active
        ? (std::clamp)(
              packet.poison_remaining_ticks,
              std::int32_t{1},
              kParticipantPoisonMaxDurationTicks)
        : 0;
    float effective_life_current = packet.life_current;
    float effective_life_max = packet.life_max;
    std::uint8_t effective_transient_status_flags = transient_status_flags;
    std::int32_t effective_poison_remaining_ticks = poison_remaining_ticks;
    if (g_local_transport.is_host) {
        const auto pending_it =
            g_local_transport.pending_participant_vitals_corrections_by_participant.find(
                packet.participant_id);
        if (pending_it !=
            g_local_transport.pending_participant_vitals_corrections_by_participant.end()) {
            const auto& correction = pending_it->second.packet;
            const bool life_acknowledged =
                packet.participant_vitals_correction_ack_sequence != 0 &&
                static_cast<std::int32_t>(
                    packet.participant_vitals_correction_ack_sequence -
                    correction.correction_sequence) >= 0;
            const bool correction_poisoned =
                (correction.transient_status_flags &
                 ParticipantTransientStatusFlagPoisoned) != 0;
            const bool poison_acknowledged =
                !correction_poisoned ||
                ((transient_status_flags &
                  ParticipantTransientStatusFlagPoisoned) != 0 &&
                 poison_remaining_ticks > 0);
            if (life_acknowledged && poison_acknowledged) {
                g_local_transport.pending_participant_vitals_corrections_by_participant.erase(
                    pending_it);
            } else {
                if (!life_acknowledged &&
                    std::isfinite(correction.life_current)) {
                    effective_life_current =
                        (std::min)(effective_life_current, correction.life_current);
                }
                if (!life_acknowledged &&
                    std::isfinite(correction.life_max) &&
                    correction.life_max > 0.0f) {
                    effective_life_max = correction.life_max;
                }
                if (!poison_acknowledged && correction_poisoned) {
                    effective_transient_status_flags =
                        ParticipantTransientStatusFlagSnapshotValid |
                        ParticipantTransientStatusFlagPoisoned;
                    effective_poison_remaining_ticks =
                        (std::max)(
                            effective_poison_remaining_ticks,
                            correction.poison_remaining_ticks);
                }
            }
        }
    }
    const bool packet_from_configured_authority =
        IsAuthoritativeHostStatePacket(packet, from);

    UpdateRuntimeState([&](RuntimeState& state) {
        if (packet_from_configured_authority) {
            LevelUpWaitStatusRuntimeInfo wait_status;
            wait_status.valid = true;
            wait_status.pause_active = packet.level_up_pause_active != 0;
            wait_status.authority_participant_id = packet.authority_participant_id;
            wait_status.received_ms = now_ms;
            const auto waiting_count =
                (std::min<std::size_t>)(
                    packet.level_up_waiting_count,
                    kLevelUpWaitStatusMaxParticipants);
            wait_status.waiting_participant_ids.reserve(waiting_count);
            for (std::size_t index = 0; index < waiting_count; ++index) {
                const auto participant_id = packet.level_up_waiting_participant_ids[index];
                if (participant_id != 0) {
                    wait_status.waiting_participant_ids.push_back(participant_id);
                }
            }
            state.level_up_wait_status = std::move(wait_status);
        }

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
        if (g_local_transport.backend == GameplayTransportBackend::LocalUdp) {
            participant->transport_using_relay = false;
        }
        participant->last_packet_ms = now_ms;
        participant->character_profile = profile;
        participant->runtime.valid = true;
        participant->runtime.in_run = packet.in_run != 0;
        participant->runtime.run_nonce = packet.run_nonce;
        participant->runtime.scene_intent = scene_intent;
        participant->runtime.level = packet.level;
        participant->runtime.wave = packet.wave;
        if (participant->runtime.life_max > 0.0f &&
            participant->runtime.life_current > 0.0f &&
            packet.life_max > 0.0f &&
            effective_life_current <= 0.0f) {
            Log(
                "Multiplayer remote participant vitals crossed to zero from state packet. participant_id=" +
                std::to_string(packet.participant_id) +
                " hp=" + std::to_string(effective_life_current) +
                "/" + std::to_string(effective_life_max) +
                " previous_hp=" + std::to_string(participant->runtime.life_current) +
                "/" + std::to_string(participant->runtime.life_max) +
                " level=" + std::to_string(packet.level) +
                " xp=" + std::to_string(packet.experience_current) +
                " packet_sequence=" + std::to_string(packet.header.sequence));
        }
        participant->runtime.life_current = effective_life_current;
        participant->runtime.life_max = effective_life_max;
        participant->runtime.mana_current = packet.mana_current;
        participant->runtime.mana_max = packet.mana_max;
        participant->runtime.move_speed = packet.move_speed;
        participant->runtime.persistent_status_flags =
            packet.persistent_status_flags;
        participant->runtime.transient_status_flags =
            effective_transient_status_flags;
        participant->runtime.poison_remaining_ticks =
            effective_poison_remaining_ticks;
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
            packet.statbook_revision >= participant->owned_progression.statbook_revision ||
            packet.spellbook_revision >= participant->owned_progression.spellbook_revision;
        if (should_apply_progression_book) {
            participant->owned_progression.spellbook_revision = packet.spellbook_revision;
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
        const bool should_apply_concentration =
            packet.concentration_selection_valid != 0 &&
            (!participant->owned_progression.concentration_selection_valid ||
             packet.concentration_revision >
                 participant->owned_progression.concentration_revision);
        if (should_apply_concentration) {
            participant->owned_progression.concentration_selection_valid = true;
            participant->owned_progression.concentration_revision =
                packet.concentration_revision;
            participant->owned_progression.concentration_entry_a =
                packet.concentration_entry_a;
            participant->owned_progression.concentration_entry_b =
                packet.concentration_entry_b;
        }
        ApplyDerivedStatPacketState(
            packet.derived_stat_revision,
            packet.derived_stats,
            &participant->owned_progression);
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

void ApplyRemoteCastPacket(
    const CastPacket& packet,
    const TransportPeerEndpoint& from,
    std::uint64_t now_ms) {
    const auto cast_kind = static_cast<CastKind>(packet.cast_kind);
    const auto input_phase = static_cast<CastInputPhase>(packet.input_phase);
    auto log_cast_drop = [&](const std::string& reason) {
        Log(
            "Multiplayer remote cast ignored. reason=" + reason +
            " participant_id=" + std::to_string(packet.participant_id) +
            " cast_sequence=" + std::to_string(packet.cast_sequence) +
            " packet_sequence=" + std::to_string(packet.header.sequence) +
            " phase=" + CastInputPhaseLabel(packet.input_phase) +
            " skill_id=" + std::to_string(packet.skill_id) +
            " run_nonce=" + std::to_string(packet.run_nonce));
    };

    if (packet.participant_id == 0 ||
        packet.participant_id == kLocalParticipantId ||
        packet.participant_id == g_local_transport.local_peer_id ||
        packet.cast_sequence == 0 ||
        packet.skill_id < 0 ||
        (cast_kind != CastKind::Primary && cast_kind != CastKind::Secondary) ||
        !IsCastInputPhaseValue(packet.input_phase) ||
        (cast_kind == CastKind::Primary && packet.secondary_slot != -1) ||
        (cast_kind == CastKind::Secondary &&
         (packet.secondary_slot < 0 ||
          packet.secondary_slot >=
              static_cast<std::int32_t>(kSecondaryLoadoutSlotCount) ||
          input_phase != CastInputPhase::Pressed)) ||
        !std::isfinite(packet.position_x) ||
        !std::isfinite(packet.position_y) ||
        !std::isfinite(packet.heading) ||
        !std::isfinite(packet.aim_target_x) ||
        !std::isfinite(packet.aim_target_y)) {
        log_cast_drop("invalid_packet");
        return;
    }

    UpsertPeerEndpoint(from, packet.participant_id, now_ms);
    RelayPacketToPeers(packet, from);

    const auto last_sequence_it =
        g_local_transport.last_cast_sequence_by_participant.find(packet.participant_id);
    if (last_sequence_it != g_local_transport.last_cast_sequence_by_participant.end() &&
        static_cast<std::int32_t>(packet.cast_sequence - last_sequence_it->second) < 0) {
        log_cast_drop(
            "stale_cast_sequence last_cast_sequence=" +
            std::to_string(last_sequence_it->second));
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
        log_cast_drop(
            "stale_packet_sequence last_packet_sequence=" +
            std::to_string(input_tracker.last_packet_sequence));
        return;
    }
    input_tracker.last_packet_sequence = packet.header.sequence;
    input_tracker.last_packet_ms = now_ms;

    const auto runtime_state = SnapshotRuntimeState();
    const auto* participant = FindParticipant(runtime_state, packet.participant_id);
    if (participant == nullptr) {
        log_cast_drop("participant_missing");
        return;
    }
    if (!IsRemoteParticipant(*participant)) {
        log_cast_drop(
            "participant_not_remote kind=" +
            std::to_string(static_cast<int>(participant->kind)));
        return;
    }
    if (!IsNativeControlledParticipant(*participant)) {
        log_cast_drop(
            "participant_not_native_controlled controller=" +
            std::to_string(static_cast<int>(participant->controller_kind)));
        return;
    }
    if (!participant->runtime.valid) {
        log_cast_drop("participant_runtime_invalid");
        return;
    }
    if (!participant->runtime.in_run) {
        log_cast_drop("participant_not_in_run");
        return;
    }
    if (participant->runtime.scene_intent.kind != ParticipantSceneIntentKind::Run) {
        log_cast_drop(
            "participant_scene_not_run scene_intent=" +
            std::to_string(static_cast<int>(participant->runtime.scene_intent.kind)));
        return;
    }
    if (participant->runtime.run_nonce != 0 &&
        packet.run_nonce != 0 &&
        participant->runtime.run_nonce != packet.run_nonce) {
        log_cast_drop(
            "run_nonce_mismatch participant_run_nonce=" +
            std::to_string(participant->runtime.run_nonce));
        return;
    }
    if (cast_kind == CastKind::Secondary) {
        const auto secondary_slot = static_cast<std::size_t>(packet.secondary_slot);
        const auto* owned_entry =
            FindProgressionBookEntryById(
                participant->owned_progression,
                packet.skill_id);
        if (packet.queued_secondary_entry_indices[secondary_slot] != packet.skill_id ||
            owned_entry == nullptr ||
            owned_entry->active == 0) {
            log_cast_drop("secondary_skill_not_owned_by_packet_and_progression");
            return;
        }
    }

    SDModParticipantGameplayState gameplay_state;
    if (!TryGetParticipantGameplayState(packet.participant_id, &gameplay_state) ||
        !gameplay_state.entity_materialized ||
        gameplay_state.actor_address == 0) {
        log_cast_drop(
            "participant_not_materialized actor=" +
            HexString(gameplay_state.actor_address) +
            " entity_materialized=" +
            std::to_string(gameplay_state.entity_materialized ? 1 : 0));
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
        if (cast_kind == CastKind::Secondary) {
            const auto secondary_slot =
                static_cast<std::size_t>(packet.secondary_slot);
            // A native belt edit and its cast can occur between consecutive
            // 20 Hz state packets. The hook's live belt snapshot is therefore
            // the freshest authenticated state for this one slot.
            live_participant->character_profile.loadout
                .secondary_entry_indices[secondary_slot] = packet.skill_id;
            live_participant->runtime
                .queued_secondary_entry_indices[secondary_slot] = packet.skill_id;
        }

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

    if (cast_kind == CastKind::Secondary && packet.skill_id == 0x33) {
        std::string dampen_error;
        if (!QueueMultiplayerDampenEffect(
                packet.participant_id,
                packet.cast_sequence,
                packet.position_x,
                packet.position_y,
                &dampen_error)) {
            log_cast_drop("dampen_behavior_queue_failed error=" + dampen_error);
            return;
        }
    }

    BotCastRequest request;
    request.bot_id = packet.participant_id;
    request.kind = cast_kind == CastKind::Secondary
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
        TryFindLocalRunEnemyByNetworkIdInternal(packet.target_network_actor_id, &cast_target) &&
        IsSaneExplicitCastTarget(cast_target, packet.position_x, packet.position_y);
    uintptr_t resolved_target_actor_address = 0;
    if (resolved_target_by_id) {
        resolved_target_actor_address = cast_target.actor_address;
        request.target_actor_address = resolved_target_actor_address;
        request.aim_target_x = cast_target.x;
        request.aim_target_y = cast_target.y;
    }

    const auto phase = input_phase;
    const bool release_phase = phase == CastInputPhase::Released;
    request.cast_sequence = packet.cast_sequence;
    request.remote_input_controlled = true;
    if (cast_kind == CastKind::Secondary) {
        if (!input_tracker.start_queued) {
            if (QueueBotCast(request)) {
                input_tracker.start_queued = true;
                Log(
                    "Multiplayer remote secondary cast queued. participant_id=" +
                    std::to_string(packet.participant_id) +
                    " cast_sequence=" + std::to_string(packet.cast_sequence) +
                    " skill_id=" + std::to_string(packet.skill_id) +
                    " secondary_slot=" + std::to_string(packet.secondary_slot) +
                    " target_network_actor_id=" +
                    std::to_string(packet.target_network_actor_id) +
                    " target_actor=" + HexString(request.target_actor_address));
            } else {
                log_cast_drop("queue_secondary_bot_cast_failed");
            }
        }
        return;
    }

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

    // Lightning can kill its initial target inside the stock pressed-frame
    // dispatcher before the post-dispatch cast hook publishes the packet. The
    // receiver may therefore see one or more packets whose exact network target
    // is already dead or not materialized yet, followed by a held packet for a
    // live target. Starting remote playback before that target resolves leaves
    // Lightning's native target validation false for the whole action, so an
    // upgraded cast never enters Chaining's extra-target loop on observers.
    // Other elements retain their targetless directional/projectile behavior.
    const bool air_primary_packet =
        packet.element_id == 3 &&
        (packet.primary_entry_index == 0x18 || packet.skill_id == 0x18);
    if (!input_tracker.start_queued && air_primary_packet && !resolved_target_by_id) {
        input_tracker.deferred_start_packet_count += 1;
        if (input_tracker.deferred_start_packet_count <= 3 ||
            input_tracker.deferred_start_packet_count % 10 == 0) {
            Log(
                "Multiplayer remote Air cast start deferred until exact target resolves. participant_id=" +
                std::to_string(packet.participant_id) +
                " cast_sequence=" + std::to_string(packet.cast_sequence) +
                " phase=" + CastInputPhaseLabel(packet.input_phase) +
                " target_network_actor_id=" + std::to_string(packet.target_network_actor_id) +
                " deferred_packets=" + std::to_string(input_tracker.deferred_start_packet_count));
        }
        return;
    }
    if (!input_tracker.start_queued) {
        if (QueueBotCast(request)) {
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
        } else {
            log_cast_drop("queue_bot_cast_failed");
        }
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
        actor.target_participant_id = packet_actor.target_participant_id;
        actor.target_native_type_id = packet_actor.target_native_type_id;
        actor.target_actor_slot = packet_actor.target_actor_slot;
        actor.target_world_slot = packet_actor.target_world_slot;
        actor.target_bucket_delta = packet_actor.target_bucket_delta;
        actor.dead = (packet_actor.flags & WorldActorSnapshotFlagDead) != 0;
        actor.tracked_enemy = (packet_actor.flags & WorldActorSnapshotFlagTrackedEnemy) != 0;
        actor.lifecycle_owned = (packet_actor.flags & WorldActorSnapshotFlagLifecycleOwned) != 0;
        actor.run_static = (packet_actor.flags & WorldActorSnapshotFlagRunStatic) != 0;
        actor.player_created =
            (packet_actor.flags & WorldActorSnapshotFlagPlayerCreated) != 0;
        actor.target_authoritative =
            (packet_actor.flags & WorldActorSnapshotFlagTargetAuthoritative) != 0;
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

void ApplyWorldSnapshotPacket(
    const WorldSnapshotPacket& packet,
    const TransportPeerEndpoint& from,
    std::uint64_t now_ms) {
    if (g_local_transport.is_host ||
        packet.authority_participant_id == 0 ||
        packet.authority_participant_id == g_local_transport.local_peer_id) {
        return;
    }

    UpsertPeerEndpoint(from, packet.authority_participant_id, now_ms);
    PublishWorldSnapshotRuntimeInfo(packet, now_ms);
}

LootSnapshotRuntimeInfo BuildLootSnapshotRuntimeInfo(
    const LootSnapshotPacket& packet,
    std::uint64_t now_ms) {
    const auto drop_count = static_cast<std::uint8_t>(
        (std::min<std::uint32_t>)(packet.drop_count, kLootSnapshotMaxDrops));
    const auto scene_kind = static_cast<WorldSceneKind>(packet.scene_kind);

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
        drop.presentation_state = packet_drop.presentation_state;
        drop.amount = packet_drop.amount;
        drop.amount_tier = packet_drop.amount_tier;
        drop.value = packet_drop.value;
        drop.motion = packet_drop.motion;
        drop.progress = packet_drop.progress;
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

    return snapshot;
}

void PublishLootSnapshotRuntimeInfo(const LootSnapshotPacket& packet, std::uint64_t now_ms) {
    UpdateRuntimeState([&](RuntimeState& state) {
        state.loot_snapshot = BuildLootSnapshotRuntimeInfo(packet, now_ms);
    });
}

void ApplyLootSnapshotPacket(
    const LootSnapshotPacket& packet,
    const TransportPeerEndpoint& from,
    std::uint64_t now_ms) {
    if (g_local_transport.is_host ||
        packet.authority_participant_id == 0 ||
        packet.authority_participant_id == g_local_transport.local_peer_id) {
        return;
    }

    UpsertPeerEndpoint(from, packet.authority_participant_id, now_ms);
    PublishLootSnapshotRuntimeInfo(packet, now_ms);

    std::string queue_error;
    (void)sdmod::QueueReplicatedLootSnapshot(SnapshotRuntimeState().loot_snapshot, &queue_error);
}

#include "multiplayer_local_transport/enemy_damage_authority.inl"

#include "multiplayer_local_transport/loot_pickup_authority.inl"

#include "multiplayer_local_transport/level_up_packet_sync.inl"

#include "multiplayer_local_transport/spell_effect_sync.inl"
#include "multiplayer_local_transport/air_chain_sync.inl"
#include "multiplayer_local_transport/participant_vitals_authority.inl"

using TransportPacketBuffer = std::array<char, sizeof(WorldSnapshotPacket)>;

template <typename Packet, typename OwnerAccessor>
bool SteamPacketOwnerMatches(
    const void* data,
    std::size_t size,
    std::uint64_t sender_steam_id,
    OwnerAccessor owner_accessor) {
    if (size != sizeof(Packet)) {
        return false;
    }
    Packet packet{};
    std::memcpy(&packet, data, sizeof(packet));
    return owner_accessor(packet) == sender_steam_id;
}

bool IsAuthorizedSteamGameplayPacket(
    std::uint64_t sender_steam_id,
    const void* data,
    std::size_t size) {
    if (data == nullptr || size < sizeof(PacketHeader)) {
        return false;
    }

    if (!g_local_transport.is_host) {
        return g_local_transport.configured_remote_valid &&
               g_local_transport.configured_remote.backend ==
                   GameplayTransportBackend::Steam &&
               g_local_transport.configured_remote.steam_id == sender_steam_id;
    }

    PacketHeader header{};
    std::memcpy(&header, data, sizeof(header));
    switch (static_cast<PacketKind>(header.kind)) {
    case PacketKind::State:
        return SteamPacketOwnerMatches<StatePacket>(
            data,
            size,
            sender_steam_id,
            [](const StatePacket& packet) {
                return packet.authority_participant_id == 0
                    ? packet.participant_id
                    : std::uint64_t{0};
            });
    case PacketKind::Cast:
        return SteamPacketOwnerMatches<CastPacket>(
            data,
            size,
            sender_steam_id,
            [](const CastPacket& packet) { return packet.participant_id; });
    case PacketKind::SpellEffectSnapshot:
        return SteamPacketOwnerMatches<SpellEffectSnapshotPacket>(
            data,
            size,
            sender_steam_id,
            [](const SpellEffectSnapshotPacket& packet) {
                return packet.owner_participant_id;
            });
    case PacketKind::AirChainSnapshot:
        return SteamPacketOwnerMatches<AirChainSnapshotPacket>(
            data,
            size,
            sender_steam_id,
            [](const AirChainSnapshotPacket& packet) {
                return packet.owner_participant_id;
            });
    case PacketKind::EnemyDamageClaim:
        return SteamPacketOwnerMatches<EnemyDamageClaimPacket>(
            data,
            size,
            sender_steam_id,
            [](const EnemyDamageClaimPacket& packet) {
                return packet.participant_id;
            });
    case PacketKind::LootPickupRequest:
        return SteamPacketOwnerMatches<LootPickupRequestPacket>(
            data,
            size,
            sender_steam_id,
            [](const LootPickupRequestPacket& packet) {
                return packet.participant_id;
            });
    case PacketKind::LevelUpChoice:
        return SteamPacketOwnerMatches<LevelUpChoicePacket>(
            data,
            size,
            sender_steam_id,
            [](const LevelUpChoicePacket& packet) {
                return packet.participant_id;
            });
    default:
        return false;
    }
}

void DispatchReceivedPacket(
    const TransportPacketBuffer& packet_buffer,
    int received,
    const TransportPeerEndpoint& from,
    std::uint64_t now_ms) {
    do {
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

        if (kind == PacketKind::SpellEffectSnapshot &&
            received == static_cast<int>(sizeof(SpellEffectSnapshotPacket))) {
            SpellEffectSnapshotPacket packet{};
            std::memcpy(&packet, packet_buffer.data(), sizeof(packet));
            if (!IsValidHeader(packet.header, PacketKind::SpellEffectSnapshot)) {
                continue;
            }
            g_local_transport.packets_received += 1;
            ApplySpellEffectSnapshotPacket(packet, from, now_ms);
            continue;
        }

        if (kind == PacketKind::AirChainSnapshot &&
            received == static_cast<int>(sizeof(AirChainSnapshotPacket))) {
            AirChainSnapshotPacket packet{};
            std::memcpy(&packet, packet_buffer.data(), sizeof(packet));
            if (!IsValidHeader(packet.header, PacketKind::AirChainSnapshot)) {
                continue;
            }
            g_local_transport.packets_received += 1;
            ApplyAirChainSnapshotPacket(packet, from, now_ms);
            continue;
        }

        if (kind == PacketKind::ParticipantVitalsCorrection &&
            received == static_cast<int>(sizeof(ParticipantVitalsCorrectionPacket))) {
            ParticipantVitalsCorrectionPacket packet{};
            std::memcpy(&packet, packet_buffer.data(), sizeof(packet));
            if (!IsValidHeader(
                    packet.header,
                    PacketKind::ParticipantVitalsCorrection)) {
                continue;
            }
            g_local_transport.packets_received += 1;
            ApplyParticipantVitalsCorrectionPacket(packet, from, now_ms);
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
            continue;
        }

        if (kind == PacketKind::LevelUpOffer && received == static_cast<int>(sizeof(LevelUpOfferPacket))) {
            LevelUpOfferPacket packet{};
            std::memcpy(&packet, packet_buffer.data(), sizeof(packet));
            if (!IsValidHeader(packet.header, PacketKind::LevelUpOffer)) {
                continue;
            }
            g_local_transport.packets_received += 1;
            ApplyLevelUpOfferPacket(packet, from, now_ms);
            continue;
        }

        if (kind == PacketKind::LevelUpChoice && received == static_cast<int>(sizeof(LevelUpChoicePacket))) {
            LevelUpChoicePacket packet{};
            std::memcpy(&packet, packet_buffer.data(), sizeof(packet));
            if (!IsValidHeader(packet.header, PacketKind::LevelUpChoice)) {
                continue;
            }
            g_local_transport.packets_received += 1;
            ApplyLevelUpChoicePacket(packet, from, now_ms);
            continue;
        }

        if (kind == PacketKind::LevelUpChoiceResult &&
            received == static_cast<int>(sizeof(LevelUpChoiceResultPacket))) {
            LevelUpChoiceResultPacket packet{};
            std::memcpy(&packet, packet_buffer.data(), sizeof(packet));
            if (!IsValidHeader(packet.header, PacketKind::LevelUpChoiceResult)) {
                continue;
            }
            g_local_transport.packets_received += 1;
            ApplyLevelUpChoiceResultPacket(packet, from, now_ms);
        }
    } while (false);
}

void ReceivePackets(std::uint64_t now_ms) {
    if (g_local_transport.backend != GameplayTransportBackend::LocalUdp) {
        return;
    }
    for (int packet_index = 0; packet_index < kMaxPacketsPerTick; ++packet_index) {
        TransportPacketBuffer packet_buffer{};
        sockaddr_in udp_from{};
        int from_length = sizeof(udp_from);
        const int received = recvfrom(
            g_local_transport.socket_handle,
            packet_buffer.data(),
            static_cast<int>(packet_buffer.size()),
            0,
            reinterpret_cast<sockaddr*>(&udp_from),
            &from_length);
        if (received == SOCKET_ERROR) {
            return;
        }
        TransportPeerEndpoint from;
        from.backend = GameplayTransportBackend::LocalUdp;
        from.udp_address = udp_from;
        DispatchReceivedPacket(packet_buffer, received, from, now_ms);
    }
}

#include "multiplayer_local_transport/native_progression_sync.inl"

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

    UpdateRuntimeState([&](RuntimeState& state) {
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
            LevelUpWaitStatusRuntimeInfo wait_status;
            const auto waiting_participant_ids = CollectUnresolvedLevelUpOfferParticipantIds();
            wait_status.valid = true;
            wait_status.pause_active = !waiting_participant_ids.empty();
            wait_status.authority_participant_id = g_local_transport.local_peer_id;
            wait_status.received_ms = static_cast<std::uint64_t>(GetTickCount64());
            wait_status.waiting_participant_ids = waiting_participant_ids;
            state.level_up_wait_status = std::move(wait_status);
        }
    });
}

}  // namespace

void ProcessPendingHostLevelUpOffers(std::uint64_t now_ms);
int CaptureLocalTransportSehCode(EXCEPTION_POINTERS* exception_pointers, DWORD* exception_code);

#include "multiplayer_local_transport/public_cast_loot_api.inl"

#include "multiplayer_local_transport/level_up_authority.inl"

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
