#pragma once

#include "multiplayer_runtime_protocol.h"
#include "steam_bootstrap.h"

#include <array>
#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace sdmod::multiplayer {

enum class ParticipantKind {
    LocalHuman,
    RemoteParticipant,
};

enum class ParticipantControllerKind {
    Native,
    LuaBrain,
};

struct BotLoadoutInfo {
    // Stock Skills_Wizard primary selection is expressed as entry indices,
    // not as a direct spell id. A primary attack is a pair of entry indices
    // that later resolve to the concrete spell id at runtime.
    std::int32_t primary_entry_index = -1;
    std::int32_t primary_combo_entry_index = -1;
    std::array<std::int32_t, kSecondaryLoadoutSlotCount> secondary_entry_indices = {
        -1, -1, -1, -1, -1, -1, -1, -1};
};

enum class CharacterDisciplineId : std::int32_t {
    Mind = 0,
    Body = 1,
    Arcane = 2,
};

enum class ParticipantSceneIntentKind : std::int32_t {
    SharedHub = 0,
    PrivateRegion = 1,
    Run = 2,
};

struct CharacterAppearanceInfo {
    std::array<std::int32_t, 4> choice_ids = {-1, -1, -1, -1};
};

struct MultiplayerCharacterProfile {
    std::int32_t element_id = 0;
    CharacterDisciplineId discipline_id = CharacterDisciplineId::Arcane;
    CharacterAppearanceInfo appearance;
    BotLoadoutInfo loadout;
    std::int32_t level = 0;
    std::int32_t experience = 0;
};

struct ParticipantSceneIntent {
    ParticipantSceneIntentKind kind = ParticipantSceneIntentKind::SharedHub;
    std::int32_t region_index = -1;
    std::int32_t region_type_id = -1;
};

struct ParticipantRuntimeInfo {
    bool valid = false;
    bool in_run = false;
    bool transform_valid = false;
    std::uint32_t run_nonce = 0;
    std::int32_t level = 0;
    std::int32_t wave = 0;
    float life_current = 0.0f;
    float life_max = 0.0f;
    float mana_current = 0.0f;
    float mana_max = 0.0f;
    float move_speed = 0.0f;
    std::int32_t experience_current = 0;
    std::int32_t experience_next = 0;
    std::int32_t primary_entry_index = -1;
    std::int32_t primary_combo_entry_index = -1;
    std::array<std::int32_t, kSecondaryLoadoutSlotCount> queued_secondary_entry_indices = {
        -1, -1, -1, -1, -1, -1, -1, -1};
    float position_x = 0.0f;
    float position_y = 0.0f;
    float heading = 0.0f;
    std::uint8_t anim_drive_state = 0;
    std::uint8_t persistent_status_flags = 0;
    std::uint8_t transient_status_flags = 0;
    std::int32_t poison_remaining_ticks = 0;
    std::uint16_t presentation_flags = 0;
    std::uint32_t attachment_staff_visual_state = 0;
    std::uint8_t render_variant_primary = 0;
    std::uint8_t render_variant_secondary = 0;
    std::uint8_t render_weapon_type = 0;
    std::uint8_t render_selection_byte = 0;
    std::uint8_t render_variant_tertiary = 0;
    std::uint32_t primary_visual_link_type_id = 0;
    std::uint32_t secondary_visual_link_type_id = 0;
    std::array<std::uint8_t, kParticipantVisualLinkColorBlockBytes> primary_visual_link_color_block = {};
    std::array<std::uint8_t, kParticipantVisualLinkColorBlockBytes> secondary_visual_link_color_block = {};
    std::uint32_t anim_drive_state_word = 0;
    float walk_cycle_primary = 0.0f;
    float walk_cycle_secondary = 0.0f;
    float render_drive_stride = 0.0f;
    float render_advance_rate = 0.0f;
    float render_advance_phase = 0.0f;
    float render_drive_effect_timer = 0.0f;
    float render_drive_effect_progress = 0.0f;
    float render_drive_overlay_alpha = 0.0f;
    float render_drive_move_blend = 0.0f;
    ParticipantSceneIntent scene_intent;
};

struct ParticipantInventoryItemState {
    std::uint32_t type_id = 0;
    std::int32_t slot = -1;
    std::int32_t stack_count = 0;
};

struct ParticipantProgressionBookEntryState {
    std::int32_t entry_index = -1;
    std::int32_t internal_id = -1;
    std::uint16_t active = 0;
    std::uint16_t visible = 0;
    std::uint16_t category = 0;
    std::int32_t statbook_max_level = -1;
};

struct ParticipantDerivedStatState {
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

struct ParticipantOwnedProgressionState {
    bool initialized = false;
    std::int32_t gold = 0;
    std::uint32_t gold_revision = 0;
    std::uint32_t inventory_revision = 0;
    std::uint32_t spellbook_revision = 0;
    std::uint32_t statbook_revision = 0;
    std::uint32_t loadout_revision = 0;
    std::uint32_t concentration_revision = 0;
    bool concentration_selection_valid = false;
    std::int32_t concentration_entry_a = -1;
    std::int32_t concentration_entry_b = -1;
    std::uint32_t derived_stat_revision = 0;
    ParticipantDerivedStatState derived_stats;
    bool inventory_host_authoritative = false;
    std::uint16_t inventory_item_total_count = 0;
    bool inventory_truncated = false;
    std::vector<ParticipantInventoryItemState> inventory_items;
    std::uint16_t progression_book_entry_total_count = 0;
    bool progression_book_truncated = false;
    std::vector<ParticipantProgressionBookEntryState> progression_book_entries;
    bool ability_loadout_valid = false;
    BotLoadoutInfo ability_loadout;
};

struct LevelUpChoiceOptionState {
    std::int32_t option_id = -1;
    std::int32_t apply_count = 1;
};

struct LevelUpOfferRuntimeInfo {
    bool valid = false;
    bool selection_submitted = false;
    bool native_picker_presented = false;
    bool native_picker_options_pinned = false;
    bool native_picker_local_apply_observed = false;
    bool suppress_native_picker = false;
    std::uint64_t authority_participant_id = 0;
    std::uint64_t target_participant_id = 0;
    std::uint64_t offer_id = 0;
    std::uint32_t run_nonce = 0;
    std::uint64_t received_ms = 0;
    std::int32_t level = 0;
    std::int32_t experience = 0;
    std::int32_t selected_option_index = -1;
    std::int32_t selected_option_id = -1;
    std::vector<LevelUpChoiceOptionState> options;
};

struct LevelUpChoiceResultRuntimeInfo {
    bool valid = false;
    bool auto_picked = false;
    std::uint64_t authority_participant_id = 0;
    std::uint64_t target_participant_id = 0;
    std::uint64_t offer_id = 0;
    std::uint32_t run_nonce = 0;
    std::uint64_t received_ms = 0;
    std::int32_t level = 0;
    std::int32_t experience = 0;
    std::int32_t option_index = -1;
    std::int32_t option_id = -1;
    std::int32_t apply_count = 1;
    std::uint16_t resulting_active = 0;
    LevelUpChoiceResultCode result_code = LevelUpChoiceResultCode::Rejected;
};

struct LevelUpWaitStatusRuntimeInfo {
    bool valid = false;
    bool pause_active = false;
    bool timed_out = false;
    std::uint64_t authority_participant_id = 0;
    std::uint64_t barrier_id = 0;
    std::uint32_t revision = 0;
    std::uint32_t deadline_remaining_ms = 0;
    std::uint64_t received_ms = 0;
    std::vector<std::uint64_t> waiting_participant_ids;
};

struct ParticipantTransformSample {
    bool valid = false;
    std::uint64_t received_ms = 0;
    std::uint32_t sequence = 0;
    std::uint32_t run_nonce = 0;
    ParticipantSceneIntent scene_intent;
    float position_x = 0.0f;
    float position_y = 0.0f;
    float heading = 0.0f;
    std::uint8_t anim_drive_state = 0;
    std::uint16_t presentation_flags = 0;
    std::uint32_t attachment_staff_visual_state = 0;
    std::uint8_t render_variant_primary = 0;
    std::uint8_t render_variant_secondary = 0;
    std::uint8_t render_weapon_type = 0;
    std::uint8_t render_selection_byte = 0;
    std::uint8_t render_variant_tertiary = 0;
    std::uint32_t primary_visual_link_type_id = 0;
    std::uint32_t secondary_visual_link_type_id = 0;
    std::array<std::uint8_t, kParticipantVisualLinkColorBlockBytes> primary_visual_link_color_block = {};
    std::array<std::uint8_t, kParticipantVisualLinkColorBlockBytes> secondary_visual_link_color_block = {};
    std::uint32_t anim_drive_state_word = 0;
    float walk_cycle_primary = 0.0f;
    float walk_cycle_secondary = 0.0f;
    float render_drive_stride = 0.0f;
    float render_advance_rate = 0.0f;
    float render_advance_phase = 0.0f;
    float render_drive_effect_timer = 0.0f;
    float render_drive_effect_progress = 0.0f;
    float render_drive_overlay_alpha = 0.0f;
    float render_drive_move_blend = 0.0f;
};

struct ParticipantInfo {
    std::uint64_t participant_id = 0;
    ParticipantKind kind = ParticipantKind::LocalHuman;
    ParticipantControllerKind controller_kind = ParticipantControllerKind::Native;
    std::uint64_t steam_id = 0;
    std::string name;
    bool ready = false;
    bool is_owner = false;
    bool transport_connected = false;
    bool transport_using_relay = false;
    std::uint64_t last_packet_ms = 0;
    MultiplayerCharacterProfile character_profile;
    ParticipantRuntimeInfo runtime;
    ParticipantOwnedProgressionState owned_progression;
    std::vector<ParticipantTransformSample> transform_history;
};

struct WorldActorSnapshot {
    std::uint64_t network_actor_id = 0;
    std::uint32_t native_type_id = 0;
    std::int32_t enemy_type = -1;
    std::int32_t actor_slot = -1;
    std::int32_t world_slot = -1;
    std::uint64_t target_participant_id = 0;
    std::uint32_t target_native_type_id = 0;
    std::int32_t target_actor_slot = -1;
    std::int32_t target_world_slot = -1;
    std::int32_t target_bucket_delta = 0;
    bool dead = false;
    bool tracked_enemy = false;
    bool lifecycle_owned = false;
    bool run_static = false;
    bool player_created = false;
    bool target_authoritative = false;
    std::uint8_t anim_drive_state = 0;
    std::uint16_t presentation_flags = 0;
    float position_x = 0.0f;
    float position_y = 0.0f;
    float radius = 0.0f;
    float heading = 0.0f;
    float hp = 0.0f;
    float max_hp = 0.0f;
    std::uint32_t anim_drive_state_word = 0;
    float walk_cycle_primary = 0.0f;
    float walk_cycle_secondary = 0.0f;
    std::uint8_t render_variant_primary = 0;
    std::uint8_t render_variant_secondary = 0;
    std::uint8_t render_weapon_type = 0;
    std::uint8_t render_selection_byte = 0;
    std::uint8_t render_variant_tertiary = 0;
    std::array<std::uint8_t, kWorldActorStudentVisualStateBytes> student_visual_state = {};
};

struct WorldSnapshotActorBindingRuntimeInfo {
    std::uint64_t network_actor_id = 0;
    uintptr_t local_actor_address = 0;
    std::uint32_t native_type_id = 0;
    std::int32_t enemy_type = -1;
    bool matched = false;
    bool parked = false;
    bool removed = false;
};

struct WorldSnapshotRuntimeInfo {
    bool valid = false;
    std::uint64_t authority_participant_id = 0;
    std::uint64_t received_ms = 0;
    std::uint32_t sequence = 0;
    std::uint32_t scene_epoch = 0;
    std::uint32_t run_nonce = 0;
    std::uint32_t actor_total_count = 0;
    bool truncated = false;
    ParticipantSceneIntent scene_intent;
    std::vector<WorldActorSnapshot> actors;
};

struct LootDropSnapshot {
    std::uint64_t network_drop_id = 0;
    std::uint32_t native_type_id = 0;
    LootDropKind drop_kind = LootDropKind::Unknown;
    bool active = false;
    std::uint8_t presentation_state = 0;
    std::int32_t amount = 0;
    std::int32_t amount_tier = 0;
    float value = 0.0f;
    float motion = 0.0f;
    float progress = 0.0f;
    std::uint32_t item_type_id = 0;
    std::int32_t item_slot = -1;
    std::int32_t stack_count = 0;
    std::int32_t actor_slot = -1;
    std::int32_t world_slot = -1;
    std::uint32_t lifetime = 0;
    float position_x = 0.0f;
    float position_y = 0.0f;
    float radius = 0.0f;
};

struct LootSnapshotRuntimeInfo {
    bool valid = false;
    std::uint64_t authority_participant_id = 0;
    std::uint64_t received_ms = 0;
    std::uint32_t sequence = 0;
    std::uint32_t scene_epoch = 0;
    std::uint32_t run_nonce = 0;
    std::uint32_t drop_total_count = 0;
    bool truncated = false;
    ParticipantSceneIntent scene_intent;
    std::vector<LootDropSnapshot> drops;
};

struct SpellEffectSnapshot {
    std::uint32_t effect_serial = 0;
    std::uint32_t cast_sequence = 0;
    std::uint32_t native_type_id = 0;
    std::uint16_t effect_ordinal = 0;
    bool active = false;
    bool terminal = false;
    bool transform_valid = false;
    bool motion_valid = false;
    bool ember_runtime_valid = false;
    bool firewalker_runtime_valid = false;
    float position_x = 0.0f;
    float position_y = 0.0f;
    float radius = 0.0f;
    float heading = 0.0f;
    float motion_x = 0.0f;
    float motion_y = 0.0f;
    float ember_vertical_position = 0.0f;
    float ember_vertical_velocity = 0.0f;
    float ember_damage = 0.0f;
    float ember_lifetime = 0.0f;
    float ember_initial_lifetime = 0.0f;
    float ember_animation_progress = 0.0f;
    std::uint32_t ember_variant = 0;
    std::uint32_t ember_frame_interval = 0;
    std::uint16_t ember_config_primary = 0;
    std::uint16_t ember_config_secondary = 0;
    std::uint16_t ember_config_tertiary = 0;
    float firewalker_collision_scale = 0.0f;
    float firewalker_phase = 0.0f;
    float firewalker_phase_step = 0.0f;
    float firewalker_lifetime = 0.0f;
    float firewalker_fade = 0.0f;
    float firewalker_direction = 0.0f;
    float firewalker_visual_scale = 0.0f;
    float firewalker_damage = 0.0f;
    std::int8_t firewalker_source_slot = -1;
    std::uint8_t firewalker_active = 0;
    std::uint8_t firewalker_variant = 0;
    std::int32_t firewalker_aux = 0;
    std::uint32_t firewalker_damage_mask = 0;
};

struct SpellEffectSnapshotRuntimeInfo {
    bool valid = false;
    std::uint64_t owner_participant_id = 0;
    std::uint64_t received_ms = 0;
    std::uint32_t sequence = 0;
    std::uint32_t run_nonce = 0;
    std::uint32_t scene_epoch = 0;
    std::uint32_t effect_total_count = 0;
    bool truncated = false;
    std::vector<SpellEffectSnapshot> effects;
};

struct SpellEffectBindingRuntimeInfo {
    std::uint64_t owner_participant_id = 0;
    std::int32_t owner_gameplay_slot = -1;
    std::int32_t owner_actor_slot = -1;
    std::uint32_t effect_serial = 0;
    std::uint32_t cast_sequence = 0;
    std::uint32_t native_type_id = 0;
    std::uint16_t effect_ordinal = 0;
    uintptr_t local_actor_address = 0;
    std::int32_t local_actor_slot = -1;
    std::int32_t local_firewalker_source_slot = -1;
    bool matched = false;
    bool active = false;
    bool terminal = false;
    float authoritative_x = 0.0f;
    float authoritative_y = 0.0f;
    float local_x = 0.0f;
    float local_y = 0.0f;
    float position_error = 0.0f;
};

struct SpellEffectApplyRuntimeInfo {
    bool valid = false;
    std::uint64_t applied_ms = 0;
    std::uint64_t reconcile_revision = 0;
    std::uint32_t snapshot_count = 0;
    std::uint32_t effect_count = 0;
    std::uint32_t matched_effect_count = 0;
    std::uint32_t matched_ember_effect_count = 0;
    std::uint32_t matched_firewalker_effect_count = 0;
    std::uint32_t created_ember_effect_count = 0;
    std::uint32_t created_firewalker_effect_count = 0;
    std::uint32_t terminal_effect_count = 0;
    std::uint32_t max_matched_effect_count = 0;
    std::uint32_t max_matched_ember_effect_count = 0;
    std::uint32_t max_matched_firewalker_effect_count = 0;
    std::uint32_t transform_write_count = 0;
    std::uint32_t motion_write_count = 0;
    std::uint32_t ember_runtime_write_count = 0;
    std::uint32_t firewalker_runtime_write_count = 0;
    std::uint32_t terminal_write_count = 0;
    std::uint64_t cumulative_transform_write_count = 0;
    std::uint64_t cumulative_motion_write_count = 0;
    std::uint64_t cumulative_ember_runtime_write_count = 0;
    std::uint64_t cumulative_ember_create_count = 0;
    std::uint64_t cumulative_firewalker_create_count = 0;
    std::uint64_t cumulative_firewalker_runtime_write_count = 0;
    std::uint64_t cumulative_terminal_write_count = 0;
    std::vector<SpellEffectBindingRuntimeInfo> bindings;
};

#include "multiplayer_runtime_effect_state.inl"
