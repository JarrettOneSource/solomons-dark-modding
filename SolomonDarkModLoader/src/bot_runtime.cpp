#include "bot_runtime.h"

#include "logger.h"
#include "mod_loader.h"

#include <Windows.h>

#include <algorithm>
#include <cmath>
#include <mutex>
#include <vector>

// Bot runtime architecture (2026-04-07)
//
// This file owns the Lua-facing bot registry plus the authoritative
// intent-based controller state for each bot. Lua only issues high-level
// commands such as `move_to`, `stop`, and `face`.
//
// The controller model is intentionally NPC-like:
// - `move_to` stores a destination.
// - `TickBotRuntime` converts that destination into a normalized movement
//   direction, desired heading, and distance-to-target.
// - Gameplay consumes that controller snapshot every frame and applies the
//   game-owned velocity and heading system to the rendered actor.
//
// That split keeps pathing intent in the runtime layer while leaving collision,
// animation, and actual actor motion inside the game loop.

namespace sdmod::multiplayer {
namespace {

struct PendingBotCast {
    std::uint64_t bot_id = 0;
    BotCastKind kind = BotCastKind::Primary;
    std::int32_t secondary_slot = -1;
    std::int32_t skill_id = 0;
    uintptr_t target_actor_address = 0;
    bool has_aim_target = false;
    float aim_target_x = 0.0f;
    float aim_target_y = 0.0f;
    bool has_aim_angle = false;
    float aim_angle = 0.0f;
    std::uint64_t queued_cast_count = 0;
    std::uint64_t queued_at_ms = 0;
};

struct PendingBotEntitySync {
    std::uint64_t bot_id = 0;
    std::uint64_t generation = 0;
    MultiplayerCharacterProfile character_profile;
    ParticipantSceneIntent scene_intent;
    bool has_transform = false;
    bool has_heading = false;
    float position_x = 0.0f;
    float position_y = 0.0f;
    float heading = 0.0f;
    std::uint64_t next_attempt_ms = 0;
};

struct PendingBotMovementIntent {
    std::uint64_t bot_id = 0;
    std::uint64_t revision = 0;
    BotControllerState state = BotControllerState::Idle;
    bool has_target = false;
    float target_x = 0.0f;
    float target_y = 0.0f;
    float distance_to_target = 0.0f;
    float direction_x = 0.0f;
    float direction_y = 0.0f;
    bool desired_heading_valid = false;
    float desired_heading = 0.0f;
    bool face_heading_valid = false;
    float face_heading = 0.0f;
    std::uint64_t face_heading_expires_ms = 0;
    uintptr_t face_target_actor_address = 0;
};

struct PendingBotDestroy {
    std::uint64_t bot_id = 0;
    std::uint64_t generation = 0;
};

std::mutex g_bot_runtime_mutex;
bool g_bot_runtime_initialized = false;
std::uint64_t g_next_bot_id = kFirstLuaControlledParticipantId;
std::uint64_t g_next_cast_sequence = 1;
std::uint64_t g_next_entity_sync_generation = 1;
std::uint64_t g_next_movement_intent_revision = 1;
std::uint64_t g_next_destroy_generation = 1;
std::vector<PendingBotCast> g_pending_casts;
std::vector<PendingBotEntitySync> g_pending_entity_syncs;
std::vector<PendingBotMovementIntent> g_bot_movement_intents;
std::vector<PendingBotDestroy> g_pending_destroys;

constexpr float kBotArrivalThreshold = 0.5f;

#include "bot_runtime/helpers.inl"

}  // namespace

#include "bot_runtime/public_api.inl"
}  // namespace sdmod::multiplayer
