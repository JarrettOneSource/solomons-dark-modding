#pragma once

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
std::uint64_t GetLocalTransportParticipantId();
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
void QueueLocalEnemyDamageClaim(
    std::uint64_t network_actor_id,
    std::int32_t skill_id,
    float authoritative_hp,
    float local_hp,
    float max_hp,
    float target_position_x,
    float target_position_y);
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
