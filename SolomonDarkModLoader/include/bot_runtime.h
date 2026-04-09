#pragma once

#include "multiplayer_runtime_state.h"

#include <cstddef>
#include <cstdint>
#include <string>

namespace sdmod::multiplayer {

enum class BotCastKind {
    Primary,
    Secondary,
};

enum class BotControllerState {
    Idle,
    Moving,
    Attacking,
};

struct BotCreateRequest {
    std::string display_name;
    std::int32_t wizard_id = 0;
    bool ready = false;
    bool has_transform = false;
    float position_x = 0.0f;
    float position_y = 0.0f;
    float heading = 0.0f;
    BotLoadoutInfo loadout;
};

struct BotUpdateRequest {
    std::uint64_t bot_id = 0;
    bool has_display_name = false;
    std::string display_name;
    bool has_wizard_id = false;
    std::int32_t wizard_id = 0;
    bool has_ready = false;
    bool ready = false;
    bool has_transform = false;
    float position_x = 0.0f;
    float position_y = 0.0f;
    float heading = 0.0f;
    bool has_loadout = false;
    BotLoadoutInfo loadout;
};

struct BotCastRequest {
    std::uint64_t bot_id = 0;
    BotCastKind kind = BotCastKind::Primary;
    std::int32_t secondary_slot = -1;
};

struct BotMoveToRequest {
    std::uint64_t bot_id = 0;
    float target_x = 0.0f;
    float target_y = 0.0f;
};

struct BotMovementIntentSnapshot {
    bool available = false;
    BotControllerState state = BotControllerState::Idle;
    bool moving = false;
    bool has_target = false;
    float direction_x = 0.0f;
    float direction_y = 0.0f;
    bool desired_heading_valid = false;
    float desired_heading = 0.0f;
    float target_x = 0.0f;
    float target_y = 0.0f;
    float distance_to_target = 0.0f;
};

struct BotSnapshot {
    bool available = false;
    std::uint64_t bot_id = 0;
    std::string display_name;
    std::int32_t wizard_id = 0;
    bool ready = false;
    bool in_run = false;
    bool runtime_valid = false;
    bool transform_valid = false;
    std::uint32_t run_nonce = 0;
    float position_x = 0.0f;
    float position_y = 0.0f;
    float heading = 0.0f;
    float hp = 0.0f;
    float max_hp = 0.0f;
    float mp = 0.0f;
    float max_mp = 0.0f;
    bool entity_materialized = false;
    uintptr_t actor_address = 0;
    uintptr_t world_address = 0;
    uintptr_t animation_state_ptr = 0;
    uintptr_t render_frame_table = 0;
    uintptr_t hub_visual_attachment_ptr = 0;
    uintptr_t hub_visual_proxy_address = 0;
    uintptr_t hub_visual_source_profile_address = 0;
    uintptr_t progression_handle_address = 0;
    uintptr_t equip_handle_address = 0;
    uintptr_t progression_runtime_state_address = 0;
    uintptr_t equip_runtime_state_address = 0;
    int gameplay_slot = -1;
    int actor_slot = -1;
    int slot_anim_state_index = -1;
    int resolved_animation_state_id = -1;
    int hub_visual_source_kind = 0;
    std::uint32_t hub_visual_descriptor_signature = 0;
    std::uint32_t render_drive_flags = 0;
    std::uint8_t anim_drive_state = 0;
    std::uint8_t render_variant_primary = 0;
    std::uint8_t render_variant_secondary = 0;
    std::uint8_t render_weapon_type = 0;
    std::uint8_t render_selection_byte = 0;
    std::uint8_t render_variant_tertiary = 0;
    float walk_cycle_primary = 0.0f;
    float walk_cycle_secondary = 0.0f;
    float render_drive_stride = 0.0f;
    float render_advance_rate = 0.0f;
    float render_advance_phase = 0.0f;
    float render_drive_overlay_alpha = 0.0f;
    float render_drive_move_blend = 0.0f;
    bool gameplay_attach_applied = false;
    BotControllerState state = BotControllerState::Idle;
    bool moving = false;
    bool has_target = false;
    float target_x = 0.0f;
    float target_y = 0.0f;
    float distance_to_target = 0.0f;
    BotLoadoutInfo loadout;
    std::uint64_t queued_cast_count = 0;
    std::uint64_t last_queued_cast_ms = 0;
};

bool InitializeBotRuntime();
void ShutdownBotRuntime();
bool IsBotRuntimeInitialized();
void TickBotRuntime(std::uint64_t monotonic_ms);

bool CreateBot(const BotCreateRequest& request, std::uint64_t* out_bot_id);
bool DestroyBot(std::uint64_t bot_id);
void DestroyAllBots();
bool UpdateBot(const BotUpdateRequest& request);
bool MoveBotTo(const BotMoveToRequest& request);
bool StopBot(std::uint64_t bot_id);
bool FaceBot(std::uint64_t bot_id, float heading);
bool ReadBotMovementIntent(std::uint64_t bot_id, BotMovementIntentSnapshot* snapshot);
bool QueueBotCast(const BotCastRequest& request);
std::uint32_t GetBotCount();
bool ReadBotSnapshot(std::uint64_t bot_id, BotSnapshot* snapshot);
bool ReadBotSnapshotByIndex(std::uint32_t index, BotSnapshot* snapshot);
std::size_t GetPendingBotCastCount();
const char* BotControllerStateLabel(BotControllerState state);

}  // namespace sdmod::multiplayer
