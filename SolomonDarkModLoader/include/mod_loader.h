#pragma once

#include "multiplayer_runtime_state.h"

#include <cstdint>
#include <filesystem>
#include <memory>
#include <string>
#include <string_view>
#include <vector>

#include <Windows.h>

namespace sdmod {

constexpr int kSDModParticipantGameplayKindUnknown = -1;
constexpr int kSDModParticipantGameplayKindPlaceholderEnemy = 0;
constexpr int kSDModParticipantGameplayKindStandaloneWizard = 1;
constexpr int kSDModParticipantGameplayKindGameplaySlotWizard = 2;
constexpr int kSDModParticipantGameplayKindRegisteredGameNpc = 3;

struct SDModEquipVisualLaneState {
    uintptr_t wrapper_address = 0;
    uintptr_t holder_address = 0;
    uintptr_t current_object_address = 0;
    std::uint32_t holder_kind = 0;
    uintptr_t current_object_vtable = 0;
    std::uint32_t current_object_type_id = 0;
};

struct SDModPlayerState {
    bool valid = false;
    float hp = 0.0f;
    float max_hp = 0.0f;
    float mp = 0.0f;
    float max_mp = 0.0f;
    int xp = -1;
    int level = 0;
    float x = 0.0f;
    float y = 0.0f;
    int gold = 0;
    uintptr_t actor_address = 0;
    uintptr_t render_subject_address = 0;
    uintptr_t world_address = 0;
    uintptr_t progression_address = 0;
    uintptr_t animation_state_ptr = 0;
    uintptr_t render_frame_table = 0;
    uintptr_t hub_visual_attachment_ptr = 0;
    uintptr_t hub_visual_source_profile_address = 0;
    std::uint32_t hub_visual_descriptor_signature = 0;
    uintptr_t render_subject_animation_state_ptr = 0;
    uintptr_t render_subject_frame_table = 0;
    uintptr_t render_subject_hub_visual_attachment_ptr = 0;
    uintptr_t render_subject_hub_visual_source_profile_address = 0;
    std::uint32_t render_subject_hub_visual_descriptor_signature = 0;
    uintptr_t progression_handle_address = 0;
    uintptr_t equip_handle_address = 0;
    uintptr_t equip_runtime_state_address = 0;
    int actor_slot = -1;
    int resolved_animation_state_id = -1;
    int hub_visual_source_kind = 0;
    int render_subject_hub_visual_source_kind = 0;
    std::uint32_t render_drive_flags = 0;
    std::uint32_t render_subject_drive_flags = 0;
    std::uint8_t anim_drive_state = 0;
    std::uint8_t render_subject_anim_drive_state = 0;
    std::uint8_t render_variant_primary = 0;
    std::uint8_t render_variant_secondary = 0;
    std::uint8_t render_weapon_type = 0;
    std::uint8_t render_selection_byte = 0;
    std::uint8_t render_variant_tertiary = 0;
    std::uint8_t render_subject_variant_primary = 0;
    std::uint8_t render_subject_variant_secondary = 0;
    std::uint8_t render_subject_weapon_type = 0;
    std::uint8_t render_subject_selection_byte = 0;
    std::uint8_t render_subject_variant_tertiary = 0;
    float walk_cycle_primary = 0.0f;
    float walk_cycle_secondary = 0.0f;
    float render_drive_stride = 0.0f;
    float render_advance_rate = 0.0f;
    float render_advance_phase = 0.0f;
    float render_drive_overlay_alpha = 0.0f;
    float render_drive_move_blend = 0.0f;
    bool gameplay_attach_applied = false;
    SDModEquipVisualLaneState primary_visual_lane;
    SDModEquipVisualLaneState secondary_visual_lane;
    SDModEquipVisualLaneState attachment_visual_lane;
};

struct SDModWorldState {
    bool valid = false;
    int wave = 0;
    int enemy_count = 0;
    std::uint64_t time_elapsed_ms = 0;
};

struct SDModSceneState {
    bool valid = false;
    std::string kind;
    std::string name;
    uintptr_t gameplay_scene_address = 0;
    uintptr_t world_address = 0;
    uintptr_t arena_address = 0;
    uintptr_t region_state_address = 0;
    int current_region_index = -1;
    int region_type_id = -1;
    int pending_level_kind = 0;
    int transition_target_a = 0;
    int transition_target_b = 0;
};

struct SDModSceneActorState {
    bool valid = false;
    uintptr_t actor_address = 0;
    uintptr_t vtable_address = 0;
    uintptr_t first_method_address = 0;
    std::uint32_t object_type_id = 0;
    std::uint32_t object_header_word = 0;
    uintptr_t owner_address = 0;
    int actor_slot = -1;
    int world_slot = -1;
    float x = 0.0f;
    float y = 0.0f;
    std::uint8_t anim_drive_state = 0;
    uintptr_t progression_handle_address = 0;
    uintptr_t equip_handle_address = 0;
    uintptr_t animation_state_ptr = 0;
};

struct SDModGameplaySelectionDebugState {
    bool valid = false;
    uintptr_t table_address = 0;
    int entry_count = 0;
    std::int32_t slot_selection_entries[4] = {};
    std::int32_t player_selection_state_0 = 0;
    std::int32_t player_selection_state_1 = 0;
};

struct SDModGameplayNavCellState {
    struct Sample {
        int sample_x = 0;
        int sample_y = 0;
        float world_x = 0.0f;
        float world_y = 0.0f;
        bool traversable = false;
    };

    int grid_x = 0;
    int grid_y = 0;
    float center_x = 0.0f;
    float center_y = 0.0f;
    bool traversable = false;
    std::vector<Sample> samples;
};

struct SDModGameplayNavGridState {
    bool valid = false;
    uintptr_t world_address = 0;
    uintptr_t controller_address = 0;
    uintptr_t cells_address = 0;
    uintptr_t probe_actor_address = 0;
    int width = 0;
    int height = 0;
    float cell_width = 0.0f;
    float cell_height = 0.0f;
    float probe_x = 0.0f;
    float probe_y = 0.0f;
    int subdivisions = 1;
    std::vector<SDModGameplayNavCellState> cells;
};

struct SDModParticipantGameplayState {
    bool available = false;
    bool entity_materialized = false;
    bool moving = false;
    int entity_kind = kSDModParticipantGameplayKindUnknown;
    std::uint64_t movement_intent_revision = 0;
    std::uint64_t participant_id = 0;
    multiplayer::MultiplayerCharacterProfile character_profile;
    multiplayer::ParticipantSceneIntent scene_intent;
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
    float x = 0.0f;
    float y = 0.0f;
    float heading = 0.0f;
    float hp = 0.0f;
    float max_hp = 0.0f;
    float mp = 0.0f;
    float max_mp = 0.0f;
    float walk_cycle_primary = 0.0f;
    float walk_cycle_secondary = 0.0f;
    float render_drive_stride = 0.0f;
    float render_advance_rate = 0.0f;
    float render_advance_phase = 0.0f;
    float render_drive_overlay_alpha = 0.0f;
    float render_drive_move_blend = 0.0f;
    bool gameplay_attach_applied = false;
    SDModEquipVisualLaneState primary_visual_lane;
    SDModEquipVisualLaneState secondary_visual_lane;
    SDModEquipVisualLaneState attachment_visual_lane;
};

void Initialize(HMODULE module_handle);
void Shutdown();

std::filesystem::path GetModulePath(HMODULE module_handle);
std::filesystem::path GetModuleDirectory(HMODULE module_handle);
std::filesystem::path GetHostProcessPath();
std::filesystem::path GetHostProcessDirectory();
std::filesystem::path GetStageRuntimeDirectory();
std::filesystem::path GetProjectRoot(HMODULE module_handle);
std::string HexString(uintptr_t value);

bool InitializeGameplayKeyboardInjection(std::string* error_message);
void ShutdownGameplayKeyboardInjection();
bool IsGameplayKeyboardInjectionInitialized();
bool QueueGameplayMouseLeftClick(std::string* error_message);
std::uint64_t GetGameplayMouseLeftEdgeSerial();
std::uint64_t GetGameplayMouseLeftEdgeTickMs();
bool QueueGameplayKeyPress(std::string_view binding_name, std::string* error_message);
bool QueueGameplayScancodePress(std::uint32_t scancode, std::string* error_message);
bool QueueGameplayStartWaves(std::string* error_message);
bool QueueHubStartTestrun(std::string* error_message);
bool QueueGameplaySwitchRegion(int region_index, std::string* error_message);
bool QueueParticipantEntitySync(
    std::uint64_t participant_id,
    const multiplayer::MultiplayerCharacterProfile& character_profile,
    const multiplayer::ParticipantSceneIntent& scene_intent,
    bool has_transform,
    bool has_heading,
    float position_x,
    float position_y,
    float heading,
    std::string* error_message);
bool QueueParticipantDestroy(std::uint64_t participant_id, std::string* error_message);
bool IsRunLifecycleActive();
int GetRunLifecycleCurrentWave();
std::uint64_t GetRunLifecycleElapsedMilliseconds();
bool TryGetPlayerState(SDModPlayerState* state);
bool TryGetWorldState(SDModWorldState* state);
bool TryGetSceneState(SDModSceneState* state);
bool TryListSceneActors(std::vector<SDModSceneActorState>* actors);
bool TryGetGameplaySelectionDebugState(SDModGameplaySelectionDebugState* state);
bool TryGetGameplayNavGridState(SDModGameplayNavGridState* state, int subdivisions = 1);
void RequestNavGridSnapshotRebuild(int subdivisions);
std::shared_ptr<const SDModGameplayNavGridState> GetLastNavGridSnapshotShared();
void RebuildNavGridSnapshotIfRequested_GameplayThread();
void FlushNavGridSnapshotOnSceneUnload();
bool TryGetParticipantGameplayState(
    std::uint64_t participant_id,
    SDModParticipantGameplayState* state);
bool SpawnEnemyByType(int type_id, float x, float y, std::string* error_message);
bool SpawnReward(std::string_view kind, int amount, float x, float y, std::string* error_message);

}  // namespace sdmod
