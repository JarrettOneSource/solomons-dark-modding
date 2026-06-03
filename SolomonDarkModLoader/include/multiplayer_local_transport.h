#pragma once

#include <cstdint>

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

}  // namespace sdmod::multiplayer
