#pragma once

#include <cstddef>
#include <cstdint>
#include <string>

namespace sdmod {
struct SDModSceneActorState;
}

namespace sdmod::multiplayer {

bool InitializeLocalTransport();
void ShutdownLocalTransport();
void TickLocalTransport(std::uint64_t now_ms);
bool IsLocalTransportEnabled();
bool IsLocalTransportHost();
bool IsLocalTransportClient();
bool TryAuthorizeLocalClientRunSwitch(std::string* error_message);
std::uint64_t GetLocalTransportParticipantId();
bool IsSteamGameplayTransportEnabled();
bool RegisterSteamGameplayPeer(
    std::uint64_t steam_id,
    bool authoritative_host);
void UnregisterSteamGameplayPeer(std::uint64_t steam_id);
bool SubmitSteamGameplayPacket(
    std::uint64_t sender_steam_id,
    const void* data,
    std::size_t size,
    std::uint64_t now_ms);
std::uint64_t QueueLocalSpellCastEvent(
    std::int32_t skill_id,
    float position_x,
    float position_y,
    float direction_x,
    float direction_y,
    std::uint64_t target_network_actor_id = 0,
    uintptr_t target_actor_address = 0,
    std::uint32_t hold_frames = 0,
    bool has_aim_target = false,
    float aim_target_x = 0.0f,
    float aim_target_y = 0.0f);
std::uint64_t QueueLocalSecondarySpellCastEvent(
    std::int32_t skill_id,
    std::int32_t secondary_slot,
    float position_x,
    float position_y,
    float direction_x,
    float direction_y,
    std::uint64_t target_network_actor_id = 0,
    uintptr_t target_actor_address = 0,
    bool has_aim_target = false,
    float aim_target_x = 0.0f,
    float aim_target_y = 0.0f,
    const std::int32_t* live_secondary_entry_indices = nullptr,
    std::size_t live_secondary_entry_count = 0);
void QueueLocalEnemyDamageClaim(
    std::uint64_t network_actor_id,
    std::int32_t skill_id,
    float authoritative_hp,
    float local_hp,
    float max_hp,
    float target_position_x,
    float target_position_y,
    bool target_position_optional = false);
void ObserveReplicatedRunEnemyDamage(
    std::uint64_t network_actor_id,
    float authoritative_hp,
    float local_hp,
    float max_hp,
    float target_position_x,
    float target_position_y,
    bool target_position_optional = false);
void QueueHostParticipantVitalsCorrection(
    std::uint64_t target_participant_id,
    float life_current,
    float life_max,
    std::uint8_t transient_status_flags,
    std::int32_t poison_remaining_ticks,
    float poison_damage_per_tick);
bool HasReplicatedRunEnemyDamageBaseline(std::uint64_t network_actor_id);
void MarkReplicatedRunEnemyDamageBaseline(std::uint64_t network_actor_id, float authoritative_hp);
void ClearReplicatedRunEnemyDamageBaseline(std::uint64_t network_actor_id);
bool HasLocalPendingLethalEnemyDamageClaim(
    std::uint64_t network_actor_id,
    std::uint64_t now_ms);
bool TryFindLocalRunEnemyByNetworkId(
    std::uint64_t network_actor_id,
    SDModSceneActorState* actor_out);
std::uint64_t GetLocalRunEnemyNetworkActorId(uintptr_t actor_address);

struct AirChainTargetCapture {
    std::uint64_t network_actor_id = 0;
    uintptr_t actor_address = 0;
    float source_x = 0.0f;
    float source_y = 0.0f;
    float target_x = 0.0f;
    float target_y = 0.0f;
};

struct AirChainSourceEndpoint {
    bool valid = false;
    float x = 0.0f;
    float y = 0.0f;
};

struct AirChainTargetEndpoint {
    bool valid = false;
    float x = 0.0f;
    float y = 0.0f;
};

// Called from the native Air dispatcher on the gameplay thread. The transport
// keeps only the newest bounded frame until its matching Cast packet has a
// network sequence.
void PublishLocalAirChainFrame(
    uintptr_t caster_actor_address,
    const AirChainTargetCapture* targets,
    std::size_t target_count,
    std::size_t target_total_count);

// Called by the observer's native nearest-target query. A fresh authoritative
// frame may deliberately resolve to zero when the owner found no target.
uintptr_t ResolveReplicatedAirChainTarget(
    uintptr_t caster_actor_address,
    std::uint64_t owner_participant_id,
    std::uint16_t target_ordinal,
    uintptr_t fallback_actor_address,
    float source_x,
    float source_y,
    AirChainSourceEndpoint* authoritative_source,
    AirChainTargetEndpoint* authoritative_target);
void RecordReplicatedAirChainSourceOverride(
    std::uint64_t owner_participant_id,
    std::uint16_t target_ordinal,
    bool applied);
void RecordReplicatedAirChainTargetOverride(
    std::uint64_t owner_participant_id,
    std::uint16_t target_ordinal,
    bool applied);
bool TrySetRunEnemyHealth(uintptr_t actor_address, float hp, float max_hp);
void NotifyLocalRunEnemyDeath(uintptr_t actor_address);
struct LootPickupRequestCapture {
    bool valid = false;
    float requester_position_x = 0.0f;
    float requester_position_y = 0.0f;
    float drop_position_x = 0.0f;
    float drop_position_y = 0.0f;
};
bool QueueLocalLootPickupRequest(
    std::uint64_t network_drop_id,
    std::uint32_t* request_sequence,
    std::string* error_message,
    const LootPickupRequestCapture* capture = nullptr);
void PublishHostLevelUpOffers(
    std::int32_t level,
    std::int32_t experience,
    uintptr_t source_progression_address);
void PublishLocalHostSelfLevelUpOffer(
    std::int32_t level,
    std::int32_t experience,
    uintptr_t source_progression_address);
bool DebugPublishHostLevelUpOffer(
    std::uint64_t target_participant_id,
    std::int32_t level,
    std::int32_t experience,
    std::int32_t option_id,
    std::int32_t apply_count,
    std::string* error_message);
// Deterministic live-test seam for proving snapshot recovery when a remote
// native progression object intentionally lacks an owned upgrade. Only one
// participant may be suppressed at a time, and shutdown always clears it.
bool SetRemoteNativeProgressionReconcileSuppressedForTest(
    std::uint64_t participant_id,
    bool suppressed);
bool ShouldSuppressLocalLevelUpFanoutForDebug();
bool QueueLocalLevelUpChoice(
    std::uint64_t offer_id,
    std::int32_t option_index,
    std::int32_t option_id,
    std::string* error_message);
void ReconcileLocalLevelUpOfferPresentation(std::uint64_t now_ms, bool allow_native_create = true);
bool HasLocalLevelUpOfferAwaitingNativePresentation();
bool ShouldPauseGameplayForLevelUpSelection();
bool TryBuildLevelUpWaitStatusText(std::string* text);

}  // namespace sdmod::multiplayer
