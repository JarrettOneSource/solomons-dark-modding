#pragma once

#include "multiplayer_runtime_state.h"

#include <cstdint>
#include <filesystem>
#include <functional>
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

struct SDModEquipVisualLaneState {
    uintptr_t wrapper_address = 0;
    uintptr_t holder_address = 0;
    uintptr_t current_object_address = 0;
    std::uint32_t holder_kind = 0;
    uintptr_t current_object_vtable = 0;
    std::uint32_t current_object_type_id = 0;
    std::uint32_t current_object_recipe_uid = 0;
    bool current_object_color_state_valid = false;
    std::array<std::uint8_t, multiplayer::kParticipantVisualLinkColorBlockBytes>
        current_object_color_state = {};
};

constexpr std::size_t kSDModInventorySnapshotMaxItems = 64;
constexpr std::uint16_t kSDModInventorySnapshotMaxDepth = 8;

struct SDModInventoryItemState {
    bool valid = false;
    uintptr_t item_address = 0;
    std::uint32_t type_id = 0;
    std::uint32_t recipe_uid = 0;
    int slot = -1;
    int stack_count = 0;
    std::int16_t parent_item_index = -1;
    std::uint16_t container_depth = 0;
    bool color_state_valid = false;
    std::array<std::uint8_t, multiplayer::kParticipantVisualLinkColorBlockBytes>
        color_state = {};
};

struct SDModInventoryState {
    bool valid = false;
    uintptr_t gameplay_scene_address = 0;
    uintptr_t item_list_root_address = 0;
    uintptr_t item_array_address = 0;
    int raw_item_count = 0;
    int item_count = 0;
    int enumerated_item_count = 0;
    bool truncated = false;
    std::vector<SDModInventoryItemState> items;
    SDModEquipVisualLaneState primary_visual_lane;
    SDModEquipVisualLaneState secondary_visual_lane;
    SDModEquipVisualLaneState attachment_visual_lane;
    std::array<SDModEquipVisualLaneState, multiplayer::kParticipantRingSlotCount>
        ring_lanes;
    SDModEquipVisualLaneState amulet_lane;
};

constexpr std::size_t kSDModProgressionBookSnapshotMaxEntries = 128;

struct SDModProgressionBookEntryState {
    bool valid = false;
    uintptr_t entry_address = 0;
    uintptr_t statbook_address = 0;
    int entry_index = -1;
    int internal_id = -1;
    std::uint16_t active = 0;
    std::uint16_t visible = 0;
    std::uint16_t category = 0;
    int statbook_max_level = -1;
};

struct SDModProgressionBookState {
    bool valid = false;
    uintptr_t progression_address = 0;
    uintptr_t entry_table_address = 0;
    int entry_count = 0;
    int enumerated_entry_count = 0;
    bool truncated = false;
    std::vector<SDModProgressionBookEntryState> entries;
};

struct SDModDerivedProgressionStatState {
    bool valid = false;
    float cast_speed_multiplier = 0.0f;
    float mana_recovery_multiplier = 0.0f;
    float resist_magic_fraction = 0.0f;
    float resist_poison_fraction = 0.0f;
    float deflect_chance = 0.0f;
    float staff_melee_damage_a = 0.0f;
    float staff_melee_damage_b = 0.0f;
    float pickup_range = 0.0f;
    float secondary_recharge_multiplier = 0.0f;
    float offensive_damage_multiplier = 0.0f;
    float offensive_mana_multiplier = 0.0f;
    float meditation_recovery_bonus = 0.0f;
    std::int32_t meditation_idle_ticks = -1;
};

struct SDModPlayerState {
    bool valid = false;
    std::uint64_t local_player_tick_count = 0;
    std::uint64_t local_player_tick_observed_ms = 0;
    std::uint8_t persistent_status_flags = 0;
    std::uint8_t transient_status_flags = 0;
    std::int32_t poison_remaining_ticks = 0;
    std::int32_t webbed_remaining_ticks = 0;
    float webbed_strength = 0.0f;
    std::int32_t damage_x4_remaining_ticks = 0;
    float hp = 0.0f;
    float max_hp = 0.0f;
    float mp = 0.0f;
    float max_mp = 0.0f;
    float move_speed = 0.0f;
    SDModDerivedProgressionStatState derived_stats;
    int xp = -1;
    int level = 0;
    float x = 0.0f;
    float y = 0.0f;
    float heading = 0.0f;
    float movement_intent_x = 0.0f;
    float movement_intent_y = 0.0f;
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
    std::uint32_t anim_drive_state_word = 0;
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
    float magic_shield_absorb_remaining = 0.0f;
    float magic_shield_absorb_capacity = 0.0f;
    float magic_shield_explosion_fraction = 0.0f;
    float magic_shield_hit_flash = 0.0f;
    float render_drive_overlay_alpha = 0.0f;
    float render_drive_move_blend = 0.0f;
    bool gameplay_attach_applied = false;
    SDModEquipVisualLaneState primary_visual_lane;
    SDModEquipVisualLaneState secondary_visual_lane;
    SDModEquipVisualLaneState attachment_visual_lane;
};

struct SDModLocalManaDeltaObservation {
    bool armed = false;
    bool valid = false;
    uintptr_t actor_address = 0;
    std::uint32_t call_count = 0;
    std::uint32_t spend_call_count = 0;
    std::uint32_t recovery_call_count = 0;
    float spent_total = 0.0f;
    float recovered_total = 0.0f;
    float last_delta = 0.0f;
};

struct SDModNativeModifierState {
    std::uint32_t type_id = 0;
    std::int32_t duration_ticks = 0;
};

struct SDModWorldState {
    bool valid = false;
    int wave = 0;
    int enemy_count = 0;
    std::uint64_t time_elapsed_ms = 0;
};

struct SDModGameplayCombatState {
    bool valid = false;
    uintptr_t arena_address = 0;
    std::int32_t combat_section_index = 0;
    std::int32_t combat_wave_index = 0;
    std::int32_t combat_wait_ticks = 0;
    std::int32_t combat_advance_mode = 0;
    std::int32_t combat_advance_threshold = 0;
    std::int32_t combat_wave_counter = 0;
    std::uint8_t combat_started_music = 0;
    std::uint8_t combat_transition_requested = 0;
    std::uint8_t combat_active = 0;
};

struct SDModManualRunEnemySpawnResult {
    bool valid = false;
    bool ok = false;
    std::uint64_t request_id = 0;
    int type_id = 0;
    uintptr_t actor_address = 0;
    float requested_x = 0.0f;
    float requested_y = 0.0f;
    float x = 0.0f;
    float y = 0.0f;
    bool wrote_x = false;
    bool wrote_y = false;
    bool rebind_ok = false;
    DWORD rebind_exception_code = 0;
    std::uint64_t completed_tick_ms = 0;
    std::string error_message;
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
    float radius = 0.0f;
    std::uint8_t anim_drive_state = 0;
    uintptr_t progression_handle_address = 0;
    uintptr_t progression_runtime_address = 0;
    float hp = 0.0f;
    float max_hp = 0.0f;
    bool dead = false;
    uintptr_t equip_handle_address = 0;
    uintptr_t animation_state_ptr = 0;
    bool tracked_enemy = false;
    int enemy_type = -1;
};

struct SDModNativeSpellEffectActorState {
    bool valid = false;
    uintptr_t actor_address = 0;
    std::uint32_t native_type_id = 0;
    std::uint64_t created_ms = 0;
    int actor_slot = -1;
    float x = 0.0f;
    float y = 0.0f;
    float radius = 0.0f;
};

struct SDModTrackedEnemyState {
    uintptr_t actor_address = 0;
    int enemy_type = -1;
};

struct SDModGameplaySelectionDebugState {
    bool valid = false;
    uintptr_t table_address = 0;
    int entry_count = 0;
    std::int32_t slot_selection_entries[4] = {};
    std::int32_t concentration_entries_a_by_slot[4] = {-1, -1, -1, -1};
    std::int32_t concentration_entries_b_by_slot[4] = {-1, -1, -1, -1};
    std::int32_t concentration_entry_a = -1;
    std::int32_t concentration_entry_b = -1;
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
    bool path_traversable = false;
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

struct SDModReplicatedLootPresentationState {
    bool valid = false;
    std::uint64_t network_drop_id = 0;
    std::uint64_t authority_participant_id = 0;
    std::uint32_t scene_epoch = 0;
    std::uint32_t run_nonce = 0;
    std::uint32_t native_type_id = 0;
    multiplayer::LootDropKind drop_kind = multiplayer::LootDropKind::Unknown;
    uintptr_t actor_address = 0;
    bool active = false;
    std::int32_t amount = 0;
    std::int32_t amount_tier = 0;
    float value = 0.0f;
    float motion = 0.0f;
    float progress = 0.0f;
    float auxiliary = 0.0f;
    std::uint32_t lifetime = 0;
    float x = 0.0f;
    float y = 0.0f;
    float radius = 0.0f;
    std::uint64_t last_seen_ms = 0;
};

struct SDModHostLootDropDeactivationResult {
    std::uint32_t run_nonce = 0;
    std::uint64_t network_drop_id = 0;
    uintptr_t actor_address = 0;
    multiplayer::LootDropKind drop_kind = multiplayer::LootDropKind::Unknown;
    bool deactivated = false;
    std::uint32_t exception_code = 0;
};

#include "mod_loader_hub_state.inl"
#include "mod_loader_participant_gameplay_state.inl"

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
bool QueueGameplayMouseLeftHoldFrames(std::uint32_t frames, std::string* error_message);
bool QueueGameplayMouseRightClick(std::string* error_message);
bool QueueGameplayMouseRightHoldFrames(std::uint32_t frames, std::string* error_message);
bool QueueGameplayMovementHoldFrames(
    float direction_x,
    float direction_y,
    std::uint32_t frames,
    std::string* error_message);
bool SetGameplayNativeControlAllowanceFrames(
    std::uint32_t frames,
    std::string* error_message);
bool PinManualSpawnerPrimaryTarget(uintptr_t actor_address, std::string* error_message);
bool ApplyPinnedManualSpawnerPrimaryTarget(uintptr_t actor_address);
bool QueueLocalPlayerNativeAirPrimaryCast(
    uintptr_t actor_address,
    std::int32_t dispatched_skill_id);
void ClearQueuedGameplayMouseLeft();
void ClearQueuedGameplayMouseRight();
bool ClearLocalPlayerGameplayCastState(std::string* error_message);
std::uint64_t GetGameplayMouseLeftEdgeSerial();
std::uint64_t GetGameplayMouseLeftEdgeTickMs();
bool TryClaimGameplayMouseLeftPrimaryCastEdge(std::uint64_t edge_serial);
bool IsGameplayMouseLeftDown();
bool IsGameplayMouseRightDown();
bool QueueGameplayBindingPress(std::string_view binding_name, std::string* error_message);
bool QueueGameplayKeyPress(std::string_view binding_name, std::string* error_message);
bool QueueGameplayScancodePress(std::uint32_t scancode, std::string* error_message);
bool QueueGameplayStartWaves(std::string* error_message);
bool QueueGameplayEnableCombatPrelude(std::string* error_message);
bool QueueHubStartTestrun(std::string* error_message);
bool QueueHubOpenService(
    std::string_view service_name,
    std::string* error_message);
bool TryGetHubSurfaceState(
    SDModHubSurfaceState* state,
    std::string* error_message);
bool SetPendingRunGenerationSeed(std::uint32_t seed, std::string* error_message);
bool PrepareArenaRunGenerationSeed(const char* source, std::string* error_message);
void ClearLocalRunGenerationSeed();
bool QueueGameplaySwitchRegion(int region_index, std::string* error_message);
bool QueueMultiplayerDampenEffect(
    std::uint64_t owner_participant_id,
    std::uint32_t cast_sequence,
    float position_x,
    float position_y,
    std::string* error_message);
bool QueueLocalPlayerVitalsCorrection(
    std::uint32_t correction_sequence,
    std::uint8_t transient_status_flags,
    std::int32_t poison_remaining_ticks,
    float poison_damage_per_tick,
    std::int32_t webbed_remaining_ticks,
    float webbed_strength,
    std::uint8_t correction_flags,
    float magic_shield_absorb_remaining,
    float magic_shield_absorb_capacity,
    float magic_shield_explosion_fraction,
    float magic_shield_hit_flash,
    std::string* error_message);
bool QueueNativePoisonBehaviorProbe(
    std::uint64_t target_participant_id,
    std::int32_t duration_ticks,
    float damage_per_tick,
    std::int8_t source_slot,
    std::string* error_message);
bool QueueNativeMagicHitBehaviorProbe(
    float projectile_damage,
    float magic_damage,
    std::uint32_t attempts,
    std::uint64_t target_participant_id,
    std::uint64_t* request_serial,
    std::string* error_message);
bool GetNativeMagicHitBehaviorProbeResult(
    std::uint64_t request_serial,
    bool* completed,
    bool* success,
    float* hp_before,
    float* hp_after,
    std::string* error_message);
bool QueueNativeStaffEffectProbe(
    uintptr_t source_actor,
    uintptr_t target_actor,
    std::uint32_t variant,
    std::uint64_t* request_serial,
    std::string* error_message);
bool GetNativeStaffEffectProbeResult(
    std::uint64_t request_serial,
    bool* completed,
    bool* success,
    float* hp_before,
    float* hp_after,
    std::string* error_message);
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
#include "mod_loader_gameplay_api.inl"
