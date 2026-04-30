#pragma once

#include "multiplayer_runtime_state.h"

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

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

enum class BotManaChargeKind {
    None,
    PerCast,
    PerSecond,
};

struct BotManaCost {
    bool resolved = false;
    BotManaChargeKind kind = BotManaChargeKind::None;
    float cost = 0.0f;
    std::int32_t statbook_level = 1;
    std::int32_t skill_id = 0;
};

struct BotCreateRequest {
    std::string display_name;
    MultiplayerCharacterProfile character_profile;
    bool has_scene_intent = false;
    ParticipantSceneIntent scene_intent;
    bool ready = false;
    bool has_transform = false;
    bool has_heading = false;
    float position_x = 0.0f;
    float position_y = 0.0f;
    float heading = 0.0f;
};

struct BotUpdateRequest {
    std::uint64_t bot_id = 0;
    bool has_display_name = false;
    std::string display_name;
    bool has_character_profile = false;
    MultiplayerCharacterProfile character_profile;
    bool has_scene_intent = false;
    ParticipantSceneIntent scene_intent;
    bool has_ready = false;
    bool ready = false;
    bool has_transform = false;
    bool has_heading = false;
    float position_x = 0.0f;
    float position_y = 0.0f;
    float heading = 0.0f;
};

struct BotCastRequest {
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
};

struct BotMoveToRequest {
    std::uint64_t bot_id = 0;
    float target_x = 0.0f;
    float target_y = 0.0f;
};

struct BotSkillChoiceOption {
    std::int32_t option_id = -1;
    std::int32_t apply_count = 1;
};

struct BotSkillChoiceSnapshot {
    bool pending = false;
    std::uint64_t bot_id = 0;
    std::uint64_t generation = 0;
    std::int32_t level = 0;
    std::int32_t experience = 0;
    std::vector<BotSkillChoiceOption> options;
};

struct BotSkillChoiceRequest {
    std::uint64_t bot_id = 0;
    std::uint64_t generation = 0;
    std::int32_t option_index = -1;
    std::int32_t option_id = -1;
};

struct BotMovementIntentSnapshot {
    bool available = false;
    std::uint64_t revision = 0;
    BotControllerState state = BotControllerState::Idle;
    bool moving = false;
    bool has_target = false;
    float direction_x = 0.0f;
    float direction_y = 0.0f;
    bool desired_heading_valid = false;
    float desired_heading = 0.0f;
    bool face_heading_valid = false;
    float face_heading = 0.0f;
    uintptr_t face_target_actor_address = 0;
    float target_x = 0.0f;
    float target_y = 0.0f;
    float distance_to_target = 0.0f;
};

struct BotEquipVisualLaneState {
    uintptr_t wrapper_address = 0;
    uintptr_t holder_address = 0;
    uintptr_t current_object_address = 0;
    std::uint32_t holder_kind = 0;
    uintptr_t current_object_vtable = 0;
    std::uint32_t current_object_type_id = 0;
};

struct BotSnapshot {
    bool available = false;
    std::uint64_t bot_id = 0;
    std::string display_name;
    ParticipantKind participant_kind = ParticipantKind::RemoteParticipant;
    ParticipantControllerKind controller_kind = ParticipantControllerKind::LuaBrain;
    MultiplayerCharacterProfile character_profile;
    bool ready = false;
    bool in_run = false;
    bool runtime_valid = false;
    bool transform_valid = false;
    std::uint32_t run_nonce = 0;
    ParticipantSceneIntent scene_intent;
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
    std::uint8_t no_interrupt = 0;
    std::uint8_t active_cast_group = 0xFF;
    std::uint16_t active_cast_slot = 0xFFFF;
    std::uint8_t render_variant_primary = 0;
    std::uint8_t render_variant_secondary = 0;
    std::uint8_t render_weapon_type = 0;
    std::uint8_t render_selection_byte = 0;
    std::uint8_t render_variant_tertiary = 0;
    bool cast_pending = false;
    bool cast_active = false;
    bool cast_ready = false;
    bool cast_startup_in_progress = false;
    bool cast_saw_activity = false;
    std::int32_t cast_skill_id = 0;
    int cast_ticks_waiting = 0;
    uintptr_t cast_target_actor_address = 0;
    float walk_cycle_primary = 0.0f;
    float walk_cycle_secondary = 0.0f;
    float render_drive_stride = 0.0f;
    float render_advance_rate = 0.0f;
    float render_advance_phase = 0.0f;
    float render_drive_overlay_alpha = 0.0f;
    float render_drive_move_blend = 0.0f;
    bool gameplay_attach_applied = false;
    BotEquipVisualLaneState primary_visual_lane;
    BotEquipVisualLaneState secondary_visual_lane;
    BotEquipVisualLaneState attachment_visual_lane;
    BotControllerState state = BotControllerState::Idle;
    bool moving = false;
    bool has_target = false;
    float target_x = 0.0f;
    float target_y = 0.0f;
    float distance_to_target = 0.0f;
    std::uint64_t queued_cast_count = 0;
    std::uint64_t last_queued_cast_ms = 0;
    bool skill_choice_pending = false;
    std::uint64_t skill_choice_generation = 0;
    std::int32_t skill_choice_level = 0;
    std::int32_t skill_choice_experience = 0;
    std::vector<BotSkillChoiceOption> skill_choice_options;
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
bool FaceBotTarget(std::uint64_t bot_id, uintptr_t target_actor_address, bool fallback_heading_valid, float fallback_heading);
bool ReadBotMovementIntent(std::uint64_t bot_id, BotMovementIntentSnapshot* snapshot);
bool QueueBotCast(const BotCastRequest& request);
BotManaCost ResolveBotCastManaCost(
    const MultiplayerCharacterProfile& character_profile,
    BotCastKind kind,
    std::int32_t secondary_slot,
    std::int32_t skill_id);
float ResolveBotManaRequiredToStart(const BotManaCost& cost);
const char* BotManaChargeKindLabel(BotManaChargeKind kind);
bool FinishBotAttack(
    std::uint64_t bot_id,
    bool desired_heading_valid,
    float desired_heading,
    bool clear_face_target);
bool ConsumePendingBotCast(std::uint64_t bot_id, BotCastRequest* request);
std::uint32_t GetBotCount();
bool ReadBotSnapshot(std::uint64_t bot_id, BotSnapshot* snapshot);
bool ReadBotSnapshotByIndex(std::uint32_t index, BotSnapshot* snapshot);
void SyncBotsToSharedLevelUp(std::int32_t level, std::int32_t experience, uintptr_t source_progression_address = 0);
bool ReadBotSkillChoices(std::uint64_t bot_id, BotSkillChoiceSnapshot* snapshot);
bool ChooseBotSkill(const BotSkillChoiceRequest& request, std::string* error_message);
std::size_t GetPendingBotCastCount();
void SetAllBotSceneIntentsToRun();
void SetAllBotSceneIntentsToSharedHub();
const char* BotControllerStateLabel(BotControllerState state);

}  // namespace sdmod::multiplayer
