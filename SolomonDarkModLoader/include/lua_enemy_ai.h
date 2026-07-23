#pragma once

#include <cstdint>
#include <string>

namespace sdmod {

enum class SDModLuaEnemyAiTargetMode : std::uint8_t {
    Stock = 0,
    Clear,
    LocalPlayer,
    Participant,
};

struct SDModLuaEnemyAiCommandState {
    bool available = false;
    std::string owner_mod_id;
    std::uint64_t network_actor_id = 0;
    std::uint64_t content_id = 0;
    std::uint32_t spawn_serial = 0;
    SDModLuaEnemyAiTargetMode target_mode = SDModLuaEnemyAiTargetMode::Stock;
    std::uint64_t target_participant_id = 0;
    bool move_goal_active = false;
    float move_goal_x = 0.0f;
    float move_goal_y = 0.0f;
    float move_goal_stop_distance = 0.0f;
};

}  // namespace sdmod
