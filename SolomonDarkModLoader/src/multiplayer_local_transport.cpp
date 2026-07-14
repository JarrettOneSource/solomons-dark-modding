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
#include <atomic>
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
constexpr std::uint64_t kClientHostRunAuthorizationFreshnessMs = 3000;
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

struct ClientHostRunAuthorization {
    bool valid = false;
    std::uint64_t authority_participant_id = 0;
    std::uint32_t run_nonce = 0;
    std::uint64_t received_ms = 0;
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
    std::int32_t recent_local_cast_skill_id = -1;
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
    std::unordered_map<std::uint64_t, ObservedLocalEnemyDamage>
        observed_enemy_damage_by_network_id;
    std::unordered_map<std::uint64_t, std::uint64_t>
        recent_local_air_chain_target_until_ms;
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
std::atomic<std::uint64_t>
    g_remote_native_progression_reconcile_suppressed_for_test{0};
std::mutex g_local_transport_event_mutex;
ClientHostRunAuthorization g_client_host_run_authorization;
std::mutex g_client_host_run_authorization_mutex;
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
#include "multiplayer_local_transport/local_state_packet_sync.inl"
#include "multiplayer_local_transport/cast_target_resolution.inl"
#include "multiplayer_local_transport/outgoing_packet_sync.inl"
#include "multiplayer_local_transport/client_enemy_damage_sync.inl"
#include "multiplayer_local_transport/incoming_packet_sync.inl"
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
