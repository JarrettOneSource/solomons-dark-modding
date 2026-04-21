#include "gameplay_seams.h"

#include "binary_layout.h"

#include <mutex>
#include <string>

namespace sdmod {
namespace {

struct GameplaySeamState {
    std::mutex mutex;
    bool loaded = false;
    std::string last_error;
};

struct AddressBinding {
    const char* section;
    const char* key;
    uintptr_t* target;
};

struct SizeBinding {
    const char* section;
    const char* key;
    std::size_t* target;
};

#define SDMOD_ADDR(section, key, target) {section, key, &target}
#define SDMOD_SIZE(section, key, target) {section, key, &target}

GameplaySeamState& GetGameplaySeamState() {
    static GameplaySeamState state;
    return state;
}

const AddressBinding* GetAddressBindings(std::size_t* count) {
    static const AddressBinding bindings[] = {
        SDMOD_ADDR("background_focus.hooks", "game_window_proc", kGameWindowProc),

        SDMOD_ADDR("gameplay.hooks", "mouse_refresh_helper", kGameplayMouseRefreshHelper),
        SDMOD_ADDR("gameplay.hooks", "keyboard_edge_helper", kGameplayKeyboardEdgeHelper),
        SDMOD_ADDR("gameplay.hooks", "player_actor_tick", kPlayerActorTick),
        SDMOD_ADDR("gameplay.hooks", "player_actor_ensure_progression_handle", kPlayerActorEnsureProgressionHandle),
        SDMOD_ADDR("gameplay.hooks", "player_actor_destructor", kPlayerActorDtor),
        SDMOD_ADDR("gameplay.hooks", "player_actor_vtable28", kPlayerActorVtable28),
        SDMOD_ADDR("gameplay.hooks", "gameplay_hud_render_dispatch", kGameplayHudRenderDispatch),
        SDMOD_ADDR("gameplay.hooks", "puppet_manager_delete_puppet", kPuppetManagerDeletePuppet),
        SDMOD_ADDR("gameplay.hooks", "pointer_list_delete_batch", kPointerListDeleteBatch),
        SDMOD_ADDR("gameplay.hooks", "object_delete", kObjectDelete),
        SDMOD_ADDR("gameplay.hooks", "gameplay_switch_region", kGameplaySwitchRegion),
        SDMOD_ADDR("gameplay.hooks", "gameplay_create_player_slot", kGameplayCreatePlayerSlot),
        SDMOD_ADDR("gameplay.hooks", "wizard_clone_from_source_actor", kWizardCloneFromSourceActor),
        SDMOD_ADDR("gameplay.hooks", "player_actor_ctor", kPlayerActorCtor),
        SDMOD_ADDR("gameplay.hooks", "standalone_wizard_visual_runtime_ctor", kStandaloneWizardVisualRuntimeCtor),
        SDMOD_ADDR("gameplay.hooks", "standalone_wizard_visual_link_primary_ctor", kStandaloneWizardVisualLinkPrimaryCtor),
        SDMOD_ADDR("gameplay.hooks", "standalone_wizard_visual_link_secondary_ctor", kStandaloneWizardVisualLinkSecondaryCtor),
        SDMOD_ADDR("gameplay.hooks", "standalone_wizard_visual_link_attach", kStandaloneWizardVisualLinkAttach),
        SDMOD_ADDR("gameplay.hooks", "actor_build_render_descriptor_from_source", kActorBuildRenderDescriptorFromSource),
        SDMOD_ADDR("gameplay.hooks", "player_actor_move_step", kPlayerActorMoveStep),
        SDMOD_ADDR("gameplay.hooks", "actor_get_profile", kActorGetProfile),
        SDMOD_ADDR("gameplay.hooks", "profile_resolve_stat_entry", kProfileResolveStatEntry),
        SDMOD_ADDR("gameplay.hooks", "stat_book_compute_value", kStatBookComputeValue),
        SDMOD_ADDR("gameplay.hooks", "world_cell_grid_rebind_actor", kWorldCellGridRebindActor),
        SDMOD_ADDR("gameplay.hooks", "movement_collision_test_circle_placement", kMovementCollisionTestCirclePlacement),
        SDMOD_ADDR("gameplay.hooks", "movement_collision_test_circle_placement_extended", kMovementCollisionTestCirclePlacementExtended),
        SDMOD_ADDR("gameplay.hooks", "actor_move_by_delta", kActorMoveByDelta),
        SDMOD_ADDR("gameplay.hooks", "actor_animation_advance", kActorAnimationAdvance),
        SDMOD_ADDR("gameplay.hooks", "actor_world_register", kActorWorldRegister),
        SDMOD_ADDR("gameplay.hooks", "actor_world_unregister", kActorWorldUnregister),
        SDMOD_ADDR("gameplay.hooks", "actor_world_register_gameplay_slot_actor", kActorWorldRegisterGameplaySlotActor),
        SDMOD_ADDR("gameplay.hooks", "actor_world_unregister_gameplay_slot_actor", kActorWorldUnregisterGameplaySlotActor),
        SDMOD_ADDR("gameplay.hooks", "monster_pathfinding_refresh_target", kMonsterPathfindingRefreshTarget),
        SDMOD_ADDR("gameplay.hooks", "actor_progression_refresh", kActorProgressionRefresh),
        SDMOD_ADDR("gameplay.hooks", "player_appearance_apply_choice", kPlayerAppearanceApplyChoice),
        SDMOD_ADDR("gameplay.hooks", "player_actor_refresh_runtime_handles", kPlayerActorRefreshRuntimeHandles),
        SDMOD_ADDR("gameplay.hooks", "skills_wizard_build_primary_spell", kSkillsWizardBuildPrimarySpell),
        SDMOD_ADDR("gameplay.hooks", "standalone_wizard_equip_ctor", kStandaloneWizardEquipCtor),
        SDMOD_ADDR("gameplay.hooks", "gamenpc_set_move_goal", kGameNpcSetMoveGoal),
        SDMOD_ADDR("gameplay.hooks", "gamenpc_set_tracked_slot_assist", kGameNpcSetTrackedSlotAssist),
        SDMOD_ADDR("gameplay.hooks", "item_staff_ctor", kItemStaffCtor),
        SDMOD_ADDR("gameplay.hooks", "item_wand_ctor", kItemWandCtor),
        SDMOD_ADDR("gameplay.hooks", "arena_start_run_dispatch", kArenaStartRunDispatch),
        SDMOD_ADDR("gameplay.hooks", "arena_create", kArenaCreate),
        SDMOD_ADDR("gameplay.hooks", "arena_start_waves", kArenaStartWaves),
        SDMOD_ADDR("gameplay.hooks", "spawn_reward_gold", kSpawnRewardGold),
        SDMOD_ADDR("gameplay.hooks", "enemy_config_ctor", kEnemyConfigCtor),
        SDMOD_ADDR("gameplay.hooks", "enemy_config_destructor", kEnemyConfigDtor),
        SDMOD_ADDR("gameplay.hooks", "build_enemy_config", kBuildEnemyConfig),
        SDMOD_ADDR("gameplay.hooks", "spawn_enemy", kSpawnEnemy),
        SDMOD_ADDR("gameplay.hooks", "object_allocate", kObjectAllocate),
        SDMOD_ADDR("gameplay.hooks", "object_free", kObjectFree),
        SDMOD_ADDR("gameplay.hooks", "game_object_factory", kGameObjectFactory),
        SDMOD_ADDR("gameplay.hooks", "game_free", kGameFree),
        SDMOD_ADDR("gameplay.hooks", "game_operator_new", kGameOperatorNew),
        SDMOD_ADDR("gameplay.hooks", "cast_active_handle_cleanup", kCastActiveHandleCleanup),

        SDMOD_ADDR("gameplay.globals", "menu_keybinding", kMenuKeybindingGlobal),
        SDMOD_ADDR("gameplay.globals", "inventory_keybinding", kInventoryKeybindingGlobal),
        SDMOD_ADDR("gameplay.globals", "skills_keybinding", kSkillsKeybindingGlobal),
        SDMOD_ADDR("gameplay.globals", "belt_slot_1_keybinding", kBeltSlotKeybindingGlobals[0]),
        SDMOD_ADDR("gameplay.globals", "belt_slot_2_keybinding", kBeltSlotKeybindingGlobals[1]),
        SDMOD_ADDR("gameplay.globals", "belt_slot_3_keybinding", kBeltSlotKeybindingGlobals[2]),
        SDMOD_ADDR("gameplay.globals", "belt_slot_4_keybinding", kBeltSlotKeybindingGlobals[3]),
        SDMOD_ADDR("gameplay.globals", "belt_slot_5_keybinding", kBeltSlotKeybindingGlobals[4]),
        SDMOD_ADDR("gameplay.globals", "belt_slot_6_keybinding", kBeltSlotKeybindingGlobals[5]),
        SDMOD_ADDR("gameplay.globals", "belt_slot_7_keybinding", kBeltSlotKeybindingGlobals[6]),
        SDMOD_ADDR("gameplay.globals", "belt_slot_8_keybinding", kBeltSlotKeybindingGlobals[7]),
        SDMOD_ADDR("gameplay.globals", "game_object", kGameObjectGlobal),
        SDMOD_ADDR("gameplay.globals", "arena", kArenaGlobal),
        SDMOD_ADDR("gameplay.globals", "enemy_count", kEnemyCountGlobal),
        SDMOD_ADDR("gameplay.globals", "gold", kGoldGlobal),
        SDMOD_ADDR("gameplay.globals", "transition_target_a", kTransitionTargetAGlobal),
        SDMOD_ADDR("gameplay.globals", "transition_target_b", kTransitionTargetBGlobal),
        SDMOD_ADDR("gameplay.globals", "pending_level_kind", kPendingLevelKindGlobal),
        SDMOD_ADDR("gameplay.globals", "game_object_factory_context", kGameObjectFactoryContextGlobal),
        SDMOD_ADDR("gameplay.globals", "gameplay_index_state_table", kGameplayIndexStateTableGlobal),
        SDMOD_ADDR("gameplay.globals", "gameplay_index_state_count", kGameplayIndexStateCountGlobal),
        SDMOD_ADDR("gameplay.globals", "player_selection_state_0", kPlayerSelectionState0Global),
        SDMOD_ADDR("gameplay.globals", "player_selection_state_1", kPlayerSelectionState1Global),
        SDMOD_ADDR("gameplay.globals", "local_player_actor", kLocalPlayerActorGlobal),
        SDMOD_ADDR("gameplay.globals", "puppet_manager_vtable", kPuppetManagerVtable),
        SDMOD_ADDR("gameplay.globals", "enemy_modifier_list_vtable", kEnemyModifierListVtable),
        SDMOD_ADDR("gameplay.globals", "actor_walk_cycle_primary_divisor", kActorWalkCyclePrimaryDivisorGlobal),
        SDMOD_ADDR("gameplay.globals", "actor_walk_cycle_secondary_divisor", kActorWalkCycleSecondaryDivisorGlobal),
        SDMOD_ADDR("gameplay.globals", "actor_walk_cycle_primary_wrap_threshold", kActorWalkCyclePrimaryWrapThresholdGlobal),
        SDMOD_ADDR("gameplay.globals", "actor_walk_cycle_secondary_wrap_threshold", kActorWalkCycleSecondaryWrapThresholdGlobal),
        SDMOD_ADDR("gameplay.globals", "actor_walk_cycle_stride_step", kActorWalkCycleStrideStepGlobal),
        SDMOD_ADDR("gameplay.globals", "actor_walk_cycle_secondary_wrap_step", kActorWalkCycleSecondaryWrapStepGlobal),
        SDMOD_ADDR("gameplay.globals", "movement_direction_scale", kMovementDirectionScaleGlobal),
        SDMOD_ADDR("gameplay.globals", "movement_speed_scalar", kMovementSpeedScalarGlobal),

        SDMOD_ADDR("hub", "backend_dispatcher", kHubBackendDispatcher),

        SDMOD_ADDR("run_lifecycle.hooks", "start_game", kStartGame),
        SDMOD_ADDR("run_lifecycle.hooks", "run_ended", kRunEnded),
        SDMOD_ADDR("run_lifecycle.hooks", "wave_spawner_tick", kWaveSpawnerTick),
        SDMOD_ADDR("run_lifecycle.hooks", "enemy_death", kEnemyDeath),
        SDMOD_ADDR("run_lifecycle.hooks", "spell_cast_3eb", kSpellCast3EB),
        SDMOD_ADDR("run_lifecycle.hooks", "spell_cast_018", kSpellCast018),
        SDMOD_ADDR("run_lifecycle.hooks", "spell_cast_020", kSpellCast020),
        SDMOD_ADDR("run_lifecycle.hooks", "spell_cast_028", kSpellCast028),
        SDMOD_ADDR("run_lifecycle.hooks", "spell_cast_3ec", kSpellCast3EC),
        SDMOD_ADDR("run_lifecycle.hooks", "spell_cast_3ed", kSpellCast3ED),
        SDMOD_ADDR("run_lifecycle.hooks", "spell_cast_3ee", kSpellCast3EE),
        SDMOD_ADDR("run_lifecycle.hooks", "spell_cast_3ef", kSpellCast3EF),
        SDMOD_ADDR("run_lifecycle.hooks", "spell_cast_3f0", kSpellCast3F0),
        SDMOD_ADDR("run_lifecycle.hooks", "spell_cast_dispatcher", kSpellCastDispatcher),
        SDMOD_ADDR("run_lifecycle.hooks", "gold_changed", kGoldChanged),
        SDMOD_ADDR("run_lifecycle.hooks", "level_up", kLevelUp),

        SDMOD_ADDR("run_lifecycle.callers", "gold_pickup", kGoldPickupCaller),
        SDMOD_ADDR("run_lifecycle.callers", "gold_spend", kGoldSpendCaller),
        SDMOD_ADDR("run_lifecycle.callers", "gold_shop", kGoldShopCaller),
        SDMOD_ADDR("run_lifecycle.callers", "gold_mirror", kGoldMirrorCaller),
        SDMOD_ADDR("run_lifecycle.callers", "gold_script", kGoldScriptCaller),
    };

    if (count != nullptr) {
        *count = sizeof(bindings) / sizeof(bindings[0]);
    }
    return bindings;
}

const SizeBinding* GetSizeBindings(std::size_t* count) {
    static const SizeBinding bindings[] = {
        SDMOD_SIZE("hub", "start_testrun_control_byte_offset", kHubStartTestrunControlByteOffset),

        SDMOD_SIZE("gameplay.offsets", "standalone_wizard_progression_table_base", kStandaloneWizardProgressionTableBaseOffset),
        SDMOD_SIZE("gameplay.offsets", "standalone_wizard_progression_table_count", kStandaloneWizardProgressionTableCountOffset),
        SDMOD_SIZE("gameplay.offsets", "standalone_wizard_progression_entry_stride", kStandaloneWizardProgressionEntryStride),
        SDMOD_SIZE("gameplay.offsets", "standalone_wizard_progression_active_flag", kStandaloneWizardProgressionActiveFlagOffset),
        SDMOD_SIZE("gameplay.offsets", "standalone_wizard_progression_visible_flag", kStandaloneWizardProgressionVisibleFlagOffset),
        SDMOD_SIZE("gameplay.offsets", "standalone_wizard_progression_refresh_mode", kStandaloneWizardProgressionRefreshModeOffset),
        SDMOD_SIZE("gameplay.offsets", "player_progression_appearance_primary_a", kPlayerProgressionAppearancePrimaryAOffset),
        SDMOD_SIZE("gameplay.offsets", "player_progression_appearance_secondary", kPlayerProgressionAppearanceSecondaryOffset),
        SDMOD_SIZE("gameplay.offsets", "player_progression_appearance_primary_b", kPlayerProgressionAppearancePrimaryBOffset),
        SDMOD_SIZE("gameplay.offsets", "player_progression_appearance_primary_c", kPlayerProgressionAppearancePrimaryCOffset),
        SDMOD_SIZE("gameplay.offsets", "gameplay_testrun_mode_flag", kGameplayTestrunModeFlagOffset),
        SDMOD_SIZE("gameplay.offsets", "gameplay_cast_intent", kGameplayCastIntentOffset),
        SDMOD_SIZE("gameplay.offsets", "gameplay_region_table", kGameplayRegionTableOffset),
        SDMOD_SIZE("gameplay.offsets", "gameplay_player_actor", kGameplayPlayerActorOffset),
        SDMOD_SIZE("gameplay.offsets", "gameplay_player_fallback_position", kGameplayPlayerFallbackPositionOffset),
        SDMOD_SIZE("gameplay.offsets", "gameplay_player_progression_handle", kGameplayPlayerProgressionHandleOffset),
        SDMOD_SIZE("gameplay.offsets", "gameplay_input_buffer_index", kGameplayInputBufferIndexOffset),
        SDMOD_SIZE("gameplay.offsets", "gameplay_actor_attach_subobject", kGameplayActorAttachSubobjectOffset),
        SDMOD_SIZE("gameplay.offsets", "gameplay_mouse_left_button", kGameplayMouseLeftButtonOffset),
        SDMOD_SIZE("gameplay.offsets", "gameplay_visual_sink_primary", kGameplayVisualSinkPrimaryOffset),
        SDMOD_SIZE("gameplay.offsets", "gameplay_visual_sink_secondary", kGameplayVisualSinkSecondaryOffset),
        SDMOD_SIZE("gameplay.offsets", "gameplay_visual_sink_attachment", kGameplayVisualSinkAttachmentOffset),
        SDMOD_SIZE("gameplay.offsets", "region_object_type_id", kRegionObjectTypeIdOffset),
        SDMOD_SIZE("gameplay.offsets", "object_header_word", kObjectHeaderWordOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_owner", kActorOwnerOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_slot", kActorSlotOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_world_slot", kActorWorldSlotOffset),
        SDMOD_SIZE("gameplay.offsets", "puppet_manager_owner_region", kPuppetManagerOwnerRegionOffset),
        SDMOD_SIZE("gameplay.offsets", "region_puppet_manager", kRegionPuppetManagerOffset),
        SDMOD_SIZE("gameplay.offsets", "pointer_list_count", kPointerListCountOffset),
        SDMOD_SIZE("gameplay.offsets", "pointer_list_capacity", kPointerListCapacityOffset),
        SDMOD_SIZE("gameplay.offsets", "pointer_list_owns_storage_flag", kPointerListOwnsStorageFlagOffset),
        SDMOD_SIZE("gameplay.offsets", "pointer_list_items", kPointerListItemsOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_position_x", kActorPositionXOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_position_y", kActorPositionYOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_collision_radius", kActorCollisionRadiusOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_unknown_reset", kActorUnknownResetOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_primary_flag_mask", kActorPrimaryFlagMaskOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_secondary_flag_mask", kActorSecondaryFlagMaskOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_heading", kActorHeadingOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_move_speed_scale", kActorMoveSpeedScaleOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_render_drive_flags", kActorRenderDriveFlagsOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_movement_speed_multiplier", kActorMovementSpeedMultiplierOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_animation_config_block", kActorAnimationConfigBlockOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_animation_drive_parameter", kActorAnimationDriveParameterOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_move_step_scale", kActorMoveStepScaleOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_animation_drive_state_byte", kActorAnimationDriveStateByteOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_animation_move_duration_ticks", kActorAnimationMoveDurationTicksOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_hub_visual_source_kind", kActorHubVisualSourceKindOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_hub_visual_source_profile", kActorHubVisualSourceProfileOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_hub_visual_source_aux_pointer", kActorHubVisualSourceAuxPointerOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_walk_cycle_primary", kActorWalkCyclePrimaryOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_walk_cycle_secondary", kActorWalkCycleSecondaryOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_render_drive_stride_scale", kActorRenderDriveStrideScaleOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_render_drive_overlay_alpha", kActorRenderDriveOverlayAlphaOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_render_drive_move_blend", kActorRenderDriveMoveBlendOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_render_drive_effect_timer", kActorRenderDriveEffectTimerOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_render_drive_effect_progress", kActorRenderDriveEffectProgressOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_render_drive_idle_bob", kActorRenderDriveIdleBobOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_equip_runtime_state", kActorEquipRuntimeStateOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_progression_runtime_state", kActorProgressionRuntimeStateOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_animation_selection_state", kActorAnimationSelectionStateOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_control_brain_target_slot", kActorControlBrainTargetSlotOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_control_brain_target_handle", kActorControlBrainTargetHandleOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_control_brain_retarget_ticks", kActorControlBrainRetargetTicksOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_control_brain_action_cooldown_ticks", kActorControlBrainActionCooldownTicksOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_control_brain_action_burst_ticks", kActorControlBrainActionBurstTicksOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_control_brain_heading_lock_ticks", kActorControlBrainHeadingLockTicksOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_control_brain_heading_accumulator", kActorControlBrainHeadingAccumulatorOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_control_brain_pursuit_range", kActorControlBrainPursuitRangeOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_control_brain_follow_leader", kActorControlBrainFollowLeaderOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_control_brain_desired_facing", kActorControlBrainDesiredFacingOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_control_brain_desired_facing_smoothed", kActorControlBrainDesiredFacingSmoothedOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_control_brain_move_input_x", kActorControlBrainMoveInputXOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_control_brain_move_input_y", kActorControlBrainMoveInputYOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_progression_handle", kActorProgressionHandleOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_equip_handle", kActorEquipHandleOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_spatial_handle", kActorSpatialHandleOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_render_frame_table", kActorRenderFrameTableOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_render_advance_rate", kActorRenderAdvanceRateOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_render_advance_phase", kActorRenderAdvancePhaseOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_render_variant_primary", kActorRenderVariantPrimaryOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_render_variant_secondary", kActorRenderVariantSecondaryOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_render_weapon_type", kActorRenderWeaponTypeOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_render_selection_byte", kActorRenderSelectionByteOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_render_variant_tertiary", kActorRenderVariantTertiaryOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_hub_visual_descriptor_block", kActorHubVisualDescriptorBlockOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_hub_visual_attachment_ptr", kActorHubVisualAttachmentPtrOffset),
        SDMOD_SIZE("gameplay.offsets", "standalone_wizard_visual_link_reset", kStandaloneWizardVisualLinkResetOffset),
        SDMOD_SIZE("gameplay.offsets", "standalone_wizard_visual_link_active_byte", kStandaloneWizardVisualLinkActiveByteOffset),
        SDMOD_SIZE("gameplay.offsets", "standalone_wizard_visual_link_descriptor_block", kStandaloneWizardVisualLinkDescriptorBlockOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_equip_runtime_visual_link_primary", kActorEquipRuntimeVisualLinkPrimaryOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_equip_runtime_visual_link_secondary", kActorEquipRuntimeVisualLinkSecondaryOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_equip_runtime_visual_link_attachment", kActorEquipRuntimeVisualLinkAttachmentOffset),
        SDMOD_SIZE("gameplay.offsets", "visual_lane_holder_kind", kVisualLaneHolderKindOffset),
        SDMOD_SIZE("gameplay.offsets", "visual_lane_holder_current_object", kVisualLaneHolderCurrentObjectOffset),
        SDMOD_SIZE("gameplay.offsets", "game_object_type_id", kGameObjectTypeIdOffset),
        SDMOD_SIZE("gameplay.offsets", "arena_combat_section_index", kArenaCombatSectionIndexOffset),
        SDMOD_SIZE("gameplay.offsets", "arena_combat_wave_index", kArenaCombatWaveIndexOffset),
        SDMOD_SIZE("gameplay.offsets", "arena_combat_wait_ticks", kArenaCombatWaitTicksOffset),
        SDMOD_SIZE("gameplay.offsets", "arena_combat_advance_mode", kArenaCombatAdvanceModeOffset),
        SDMOD_SIZE("gameplay.offsets", "arena_combat_advance_threshold", kArenaCombatAdvanceThresholdOffset),
        SDMOD_SIZE("gameplay.offsets", "arena_combat_started_music", kArenaCombatStartedMusicOffset),
        SDMOD_SIZE("gameplay.offsets", "arena_combat_transition_requested", kArenaCombatTransitionRequestedOffset),
        SDMOD_SIZE("gameplay.offsets", "arena_combat_wave_counter", kArenaCombatWaveCounterOffset),
        SDMOD_SIZE("gameplay.offsets", "arena_combat_active_flag", kArenaCombatActiveFlagOffset),
        SDMOD_SIZE("gameplay.offsets", "progression_level", kProgressionLevelOffset),
        SDMOD_SIZE("gameplay.offsets", "progression_xp", kProgressionXpOffset),
        SDMOD_SIZE("gameplay.offsets", "progression_hp", kProgressionHpOffset),
        SDMOD_SIZE("gameplay.offsets", "progression_max_hp", kProgressionMaxHpOffset),
        SDMOD_SIZE("gameplay.offsets", "progression_mp", kProgressionMpOffset),
        SDMOD_SIZE("gameplay.offsets", "progression_max_mp", kProgressionMaxMpOffset),
        SDMOD_SIZE("gameplay.offsets", "progression_move_speed", kProgressionMoveSpeedOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_owner_movement_controller", kActorOwnerMovementControllerOffset),
        SDMOD_SIZE("gameplay.offsets", "source_profile_visual_source_type", kSourceProfileVisualSourceTypeOffset),
        SDMOD_SIZE("gameplay.offsets", "source_profile_aux_pointer_target", kSourceProfileAuxPointerTargetOffset),
        SDMOD_SIZE("gameplay.offsets", "source_profile_unknown_56", kSourceProfileUnknown56Offset),
        SDMOD_SIZE("gameplay.offsets", "source_profile_unknown_74", kSourceProfileUnknown74Offset),
        SDMOD_SIZE("gameplay.offsets", "source_profile_variant_primary", kSourceProfileVariantPrimaryOffset),
        SDMOD_SIZE("gameplay.offsets", "source_profile_variant_secondary", kSourceProfileVariantSecondaryOffset),
        SDMOD_SIZE("gameplay.offsets", "source_profile_render_selection", kSourceProfileRenderSelectionOffset),
        SDMOD_SIZE("gameplay.offsets", "source_profile_weapon_type", kSourceProfileWeaponTypeOffset),
        SDMOD_SIZE("gameplay.offsets", "source_profile_variant_tertiary", kSourceProfileVariantTertiaryOffset),
        SDMOD_SIZE("gameplay.offsets", "source_profile_cloth_color", kSourceProfileClothColorOffset),
        SDMOD_SIZE("gameplay.offsets", "source_profile_trim_color", kSourceProfileTrimColorOffset),
        SDMOD_SIZE("gameplay.offsets", "enemy_death_handled", kEnemyDeathHandledOffset),
        SDMOD_SIZE("gameplay.offsets", "enemy_config", kEnemyConfigOffset),
        SDMOD_SIZE("gameplay.offsets", "enemy_type", kEnemyTypeOffset),
        SDMOD_SIZE("gameplay.offsets", "spell_direction_x", kSpellDirectionXOffset),
        SDMOD_SIZE("gameplay.offsets", "spell_direction_y", kSpellDirectionYOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_primary_skill_id", kActorPrimarySkillIdOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_no_interrupt_flag", kActorNoInterruptFlagOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_active_cast_group_byte", kActorActiveCastGroupByteOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_active_cast_slot_short", kActorActiveCastSlotShortOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_aim_target_x", kActorAimTargetXOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_aim_target_y", kActorAimTargetYOffset),
        SDMOD_SIZE("gameplay.offsets", "actor_aim_target_aux0", kActorAimTargetAux0Offset),
        SDMOD_SIZE("gameplay.offsets", "actor_aim_target_aux1", kActorAimTargetAux1Offset),
        SDMOD_SIZE("gameplay.offsets", "actor_cast_spread_mode_byte", kActorCastSpreadModeByteOffset),
    };

    if (count != nullptr) {
        *count = sizeof(bindings) / sizeof(bindings[0]);
    }
    return bindings;
}

void ResetGameplaySeams() {
    std::size_t address_count = 0;
    const auto* address_bindings = GetAddressBindings(&address_count);
    for (std::size_t index = 0; index < address_count; ++index) {
        *address_bindings[index].target = 0;
    }

    std::size_t size_count = 0;
    const auto* size_bindings = GetSizeBindings(&size_count);
    for (std::size_t index = 0; index < size_count; ++index) {
        *size_bindings[index].target = 0;
    }
}

bool LoadAddressBinding(const AddressBinding& binding, std::string* error_message) {
    uintptr_t value = 0;
    if (!TryGetBinaryLayoutNumericValue(binding.section, binding.key, &value) || value == 0) {
        if (error_message != nullptr) {
            *error_message =
                "Binary layout is missing [" + std::string(binding.section) + "]." + binding.key + ".";
        }
        return false;
    }

    *binding.target = value;
    return true;
}

bool LoadSizeBinding(const SizeBinding& binding, std::string* error_message) {
    uintptr_t value = 0;
    if (!TryGetBinaryLayoutNumericValue(binding.section, binding.key, &value)) {
        if (error_message != nullptr) {
            *error_message =
                "Binary layout is missing [" + std::string(binding.section) + "]." + binding.key + ".";
        }
        return false;
    }

    *binding.target = static_cast<std::size_t>(value);
    return true;
}

#undef SDMOD_ADDR
#undef SDMOD_SIZE

}  // namespace

uintptr_t kGameWindowProc = 0;

uintptr_t kGameplayMouseRefreshHelper = 0;
uintptr_t kGameplayKeyboardEdgeHelper = 0;
uintptr_t kPlayerActorTick = 0;
uintptr_t kPlayerActorEnsureProgressionHandle = 0;
uintptr_t kPlayerActorDtor = 0;
uintptr_t kPlayerActorVtable28 = 0;
uintptr_t kGameplayHudRenderDispatch = 0;
uintptr_t kPuppetManagerDeletePuppet = 0;
uintptr_t kPointerListDeleteBatch = 0;
uintptr_t kObjectDelete = 0;
uintptr_t kGameplaySwitchRegion = 0;
uintptr_t kGameplayCreatePlayerSlot = 0;
uintptr_t kWizardCloneFromSourceActor = 0;
uintptr_t kPlayerActorCtor = 0;
uintptr_t kStandaloneWizardVisualRuntimeCtor = 0;
uintptr_t kStandaloneWizardVisualLinkPrimaryCtor = 0;
uintptr_t kStandaloneWizardVisualLinkSecondaryCtor = 0;
uintptr_t kStandaloneWizardVisualLinkAttach = 0;
uintptr_t kActorBuildRenderDescriptorFromSource = 0;
uintptr_t kPlayerActorMoveStep = 0;
uintptr_t kActorGetProfile = 0;
uintptr_t kProfileResolveStatEntry = 0;
uintptr_t kStatBookComputeValue = 0;
uintptr_t kWorldCellGridRebindActor = 0;
uintptr_t kMovementCollisionTestCirclePlacement = 0;
uintptr_t kMovementCollisionTestCirclePlacementExtended = 0;
uintptr_t kActorMoveByDelta = 0;
uintptr_t kActorAnimationAdvance = 0;
uintptr_t kActorWorldRegister = 0;
uintptr_t kActorWorldUnregister = 0;
uintptr_t kActorWorldRegisterGameplaySlotActor = 0;
uintptr_t kActorWorldUnregisterGameplaySlotActor = 0;
uintptr_t kMonsterPathfindingRefreshTarget = 0;
uintptr_t kActorProgressionRefresh = 0;
uintptr_t kPlayerAppearanceApplyChoice = 0;
uintptr_t kPlayerActorRefreshRuntimeHandles = 0;
uintptr_t kSkillsWizardBuildPrimarySpell = 0;
uintptr_t kStandaloneWizardEquipCtor = 0;
uintptr_t kGameNpcSetMoveGoal = 0;
uintptr_t kGameNpcSetTrackedSlotAssist = 0;
uintptr_t kItemStaffCtor = 0;
uintptr_t kItemWandCtor = 0;
uintptr_t kArenaStartRunDispatch = 0;
uintptr_t kArenaCreate = 0;
uintptr_t kArenaStartWaves = 0;
uintptr_t kSpawnRewardGold = 0;
uintptr_t kEnemyConfigCtor = 0;
uintptr_t kEnemyConfigDtor = 0;
uintptr_t kBuildEnemyConfig = 0;
uintptr_t kSpawnEnemy = 0;
uintptr_t kObjectAllocate = 0;
uintptr_t kObjectFree = 0;
uintptr_t kGameObjectFactory = 0;
uintptr_t kGameFree = 0;
uintptr_t kGameOperatorNew = 0;
uintptr_t kCastActiveHandleCleanup = 0;
uintptr_t kPuppetManagerVtable = 0;
uintptr_t kEnemyModifierListVtable = 0;

uintptr_t kMenuKeybindingGlobal = 0;
uintptr_t kInventoryKeybindingGlobal = 0;
uintptr_t kSkillsKeybindingGlobal = 0;
std::array<uintptr_t, 8> kBeltSlotKeybindingGlobals = {};
uintptr_t kGameObjectGlobal = 0;
uintptr_t kArenaGlobal = 0;
uintptr_t kEnemyCountGlobal = 0;
uintptr_t kGoldGlobal = 0;
uintptr_t kTransitionTargetAGlobal = 0;
uintptr_t kTransitionTargetBGlobal = 0;
uintptr_t kPendingLevelKindGlobal = 0;
uintptr_t kGameObjectFactoryContextGlobal = 0;
uintptr_t kGameplayIndexStateTableGlobal = 0;
uintptr_t kGameplayIndexStateCountGlobal = 0;
uintptr_t kPlayerSelectionState0Global = 0;
uintptr_t kPlayerSelectionState1Global = 0;
uintptr_t kLocalPlayerActorGlobal = 0;
uintptr_t kActorWalkCyclePrimaryDivisorGlobal = 0;
uintptr_t kActorWalkCycleSecondaryDivisorGlobal = 0;
uintptr_t kActorWalkCyclePrimaryWrapThresholdGlobal = 0;
uintptr_t kActorWalkCycleSecondaryWrapThresholdGlobal = 0;
uintptr_t kActorWalkCycleStrideStepGlobal = 0;
uintptr_t kActorWalkCycleSecondaryWrapStepGlobal = 0;
uintptr_t kMovementDirectionScaleGlobal = 0;
uintptr_t kMovementSpeedScalarGlobal = 0;
uintptr_t kHubBackendDispatcher = 0;

uintptr_t kStartGame = 0;
uintptr_t kRunEnded = 0;
uintptr_t kWaveSpawnerTick = 0;
uintptr_t kEnemyDeath = 0;
uintptr_t kSpellCast3EB = 0;
uintptr_t kSpellCast018 = 0;
uintptr_t kSpellCast020 = 0;
uintptr_t kSpellCast028 = 0;
uintptr_t kSpellCast3EC = 0;
uintptr_t kSpellCast3ED = 0;
uintptr_t kSpellCast3EE = 0;
uintptr_t kSpellCast3EF = 0;
uintptr_t kSpellCast3F0 = 0;
uintptr_t kSpellCastDispatcher = 0;
uintptr_t kGoldChanged = 0;
uintptr_t kLevelUp = 0;
uintptr_t kGoldPickupCaller = 0;
uintptr_t kGoldSpendCaller = 0;
uintptr_t kGoldShopCaller = 0;
uintptr_t kGoldMirrorCaller = 0;
uintptr_t kGoldScriptCaller = 0;

std::size_t kHubStartTestrunControlByteOffset = 0;
std::size_t kStandaloneWizardProgressionTableBaseOffset = 0;
std::size_t kStandaloneWizardProgressionTableCountOffset = 0;
std::size_t kStandaloneWizardProgressionEntryStride = 0;
std::size_t kStandaloneWizardProgressionActiveFlagOffset = 0;
std::size_t kStandaloneWizardProgressionVisibleFlagOffset = 0;
std::size_t kStandaloneWizardProgressionRefreshModeOffset = 0;
std::size_t kPlayerProgressionAppearancePrimaryAOffset = 0;
std::size_t kPlayerProgressionAppearanceSecondaryOffset = 0;
std::size_t kPlayerProgressionAppearancePrimaryBOffset = 0;
std::size_t kPlayerProgressionAppearancePrimaryCOffset = 0;
std::size_t kGameplayTestrunModeFlagOffset = 0;
std::size_t kGameplayCastIntentOffset = 0;
std::size_t kGameplayRegionTableOffset = 0;
std::size_t kGameplayPlayerActorOffset = 0;
std::size_t kGameplayPlayerFallbackPositionOffset = 0;
std::size_t kGameplayPlayerProgressionHandleOffset = 0;
std::size_t kGameplayInputBufferIndexOffset = 0;
std::size_t kGameplayActorAttachSubobjectOffset = 0;
std::size_t kGameplayMouseLeftButtonOffset = 0;
std::size_t kGameplayVisualSinkPrimaryOffset = 0;
std::size_t kGameplayVisualSinkSecondaryOffset = 0;
std::size_t kGameplayVisualSinkAttachmentOffset = 0;
std::size_t kRegionObjectTypeIdOffset = 0;
std::size_t kObjectHeaderWordOffset = 0;
std::size_t kActorOwnerOffset = 0;
std::size_t kActorSlotOffset = 0;
std::size_t kActorWorldSlotOffset = 0;
std::size_t kPuppetManagerOwnerRegionOffset = 0;
std::size_t kRegionPuppetManagerOffset = 0;
std::size_t kPointerListCountOffset = 0;
std::size_t kPointerListCapacityOffset = 0;
std::size_t kPointerListOwnsStorageFlagOffset = 0;
std::size_t kPointerListItemsOffset = 0;
std::size_t kActorPositionXOffset = 0;
std::size_t kActorPositionYOffset = 0;
std::size_t kActorCollisionRadiusOffset = 0;
std::size_t kActorUnknownResetOffset = 0;
std::size_t kActorPrimaryFlagMaskOffset = 0;
std::size_t kActorSecondaryFlagMaskOffset = 0;
std::size_t kActorHeadingOffset = 0;
std::size_t kActorMoveSpeedScaleOffset = 0;
std::size_t kActorRenderDriveFlagsOffset = 0;
std::size_t kActorMovementSpeedMultiplierOffset = 0;
std::size_t kActorAnimationConfigBlockOffset = 0;
std::size_t kActorAnimationDriveParameterOffset = 0;
std::size_t kActorMoveStepScaleOffset = 0;
std::size_t kActorAnimationDriveStateByteOffset = 0;
std::size_t kActorAnimationMoveDurationTicksOffset = 0;
std::size_t kActorHubVisualSourceKindOffset = 0;
std::size_t kActorHubVisualSourceProfileOffset = 0;
std::size_t kActorHubVisualSourceAuxPointerOffset = 0;
std::size_t kActorWalkCyclePrimaryOffset = 0;
std::size_t kActorWalkCycleSecondaryOffset = 0;
std::size_t kActorRenderDriveStrideScaleOffset = 0;
std::size_t kActorRenderDriveOverlayAlphaOffset = 0;
std::size_t kActorRenderDriveMoveBlendOffset = 0;
std::size_t kActorRenderDriveEffectTimerOffset = 0;
std::size_t kActorRenderDriveEffectProgressOffset = 0;
std::size_t kActorRenderDriveIdleBobOffset = 0;
std::size_t kActorEquipRuntimeStateOffset = 0;
std::size_t kActorProgressionRuntimeStateOffset = 0;
std::size_t kActorAnimationSelectionStateOffset = 0;
std::size_t kActorControlBrainTargetSlotOffset = 0;
std::size_t kActorControlBrainTargetHandleOffset = 0;
std::size_t kActorControlBrainRetargetTicksOffset = 0;
std::size_t kActorControlBrainActionCooldownTicksOffset = 0;
std::size_t kActorControlBrainActionBurstTicksOffset = 0;
std::size_t kActorControlBrainHeadingLockTicksOffset = 0;
std::size_t kActorControlBrainHeadingAccumulatorOffset = 0;
std::size_t kActorControlBrainPursuitRangeOffset = 0;
std::size_t kActorControlBrainFollowLeaderOffset = 0;
std::size_t kActorControlBrainDesiredFacingOffset = 0;
std::size_t kActorControlBrainDesiredFacingSmoothedOffset = 0;
std::size_t kActorControlBrainMoveInputXOffset = 0;
std::size_t kActorControlBrainMoveInputYOffset = 0;
std::size_t kActorProgressionHandleOffset = 0;
std::size_t kActorEquipHandleOffset = 0;
std::size_t kActorSpatialHandleOffset = 0;
std::size_t kActorRenderFrameTableOffset = 0;
std::size_t kActorRenderAdvanceRateOffset = 0;
std::size_t kActorRenderAdvancePhaseOffset = 0;
std::size_t kActorRenderVariantPrimaryOffset = 0;
std::size_t kActorRenderVariantSecondaryOffset = 0;
std::size_t kActorRenderWeaponTypeOffset = 0;
std::size_t kActorRenderSelectionByteOffset = 0;
std::size_t kActorRenderVariantTertiaryOffset = 0;
std::size_t kActorHubVisualDescriptorBlockOffset = 0;
std::size_t kActorHubVisualAttachmentPtrOffset = 0;
std::size_t kStandaloneWizardVisualLinkResetOffset = 0;
std::size_t kStandaloneWizardVisualLinkActiveByteOffset = 0;
std::size_t kStandaloneWizardVisualLinkDescriptorBlockOffset = 0;
std::size_t kActorEquipRuntimeVisualLinkPrimaryOffset = 0;
std::size_t kActorEquipRuntimeVisualLinkSecondaryOffset = 0;
std::size_t kActorEquipRuntimeVisualLinkAttachmentOffset = 0;
std::size_t kVisualLaneHolderKindOffset = 0;
std::size_t kVisualLaneHolderCurrentObjectOffset = 0;
std::size_t kGameObjectTypeIdOffset = 0;
std::size_t kArenaCombatSectionIndexOffset = 0;
std::size_t kArenaCombatWaveIndexOffset = 0;
std::size_t kArenaCombatWaitTicksOffset = 0;
std::size_t kArenaCombatAdvanceModeOffset = 0;
std::size_t kArenaCombatAdvanceThresholdOffset = 0;
std::size_t kArenaCombatStartedMusicOffset = 0;
std::size_t kArenaCombatTransitionRequestedOffset = 0;
std::size_t kArenaCombatWaveCounterOffset = 0;
std::size_t kArenaCombatActiveFlagOffset = 0;
std::size_t kProgressionLevelOffset = 0;
std::size_t kProgressionXpOffset = 0;
std::size_t kProgressionHpOffset = 0;
std::size_t kProgressionMaxHpOffset = 0;
std::size_t kProgressionMpOffset = 0;
std::size_t kProgressionMaxMpOffset = 0;
std::size_t kProgressionMoveSpeedOffset = 0;
std::size_t kActorOwnerMovementControllerOffset = 0;
std::size_t kSourceProfileVisualSourceTypeOffset = 0;
std::size_t kSourceProfileAuxPointerTargetOffset = 0;
std::size_t kSourceProfileUnknown56Offset = 0;
std::size_t kSourceProfileUnknown74Offset = 0;
std::size_t kSourceProfileVariantPrimaryOffset = 0;
std::size_t kSourceProfileVariantSecondaryOffset = 0;
std::size_t kSourceProfileRenderSelectionOffset = 0;
std::size_t kSourceProfileWeaponTypeOffset = 0;
std::size_t kSourceProfileVariantTertiaryOffset = 0;
std::size_t kSourceProfileClothColorOffset = 0;
std::size_t kSourceProfileTrimColorOffset = 0;
std::size_t kEnemyDeathHandledOffset = 0;
std::size_t kEnemyConfigOffset = 0;
std::size_t kEnemyTypeOffset = 0;
std::size_t kSpellDirectionXOffset = 0;
std::size_t kSpellDirectionYOffset = 0;
std::size_t kActorPrimarySkillIdOffset = 0;
std::size_t kActorNoInterruptFlagOffset = 0;
std::size_t kActorActiveCastGroupByteOffset = 0;
std::size_t kActorActiveCastSlotShortOffset = 0;
std::size_t kActorAimTargetXOffset = 0;
std::size_t kActorAimTargetYOffset = 0;
std::size_t kActorAimTargetAux0Offset = 0;
std::size_t kActorAimTargetAux1Offset = 0;
std::size_t kActorCastSpreadModeByteOffset = 0;

bool InitializeGameplaySeams(std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }

    auto& state = GetGameplaySeamState();
    std::scoped_lock lock(state.mutex);
    if (state.loaded) {
        return true;
    }

    if (!IsBinaryLayoutLoaded()) {
        state.last_error = "Binary layout is not loaded.";
        if (error_message != nullptr) {
            *error_message = state.last_error;
        }
        return false;
    }

    ResetGameplaySeams();

    std::size_t address_count = 0;
    const auto* address_bindings = GetAddressBindings(&address_count);
    for (std::size_t index = 0; index < address_count; ++index) {
        if (!LoadAddressBinding(address_bindings[index], &state.last_error)) {
            ResetGameplaySeams();
            if (error_message != nullptr) {
                *error_message = state.last_error;
            }
            return false;
        }
    }

    std::size_t size_count = 0;
    const auto* size_bindings = GetSizeBindings(&size_count);
    for (std::size_t index = 0; index < size_count; ++index) {
        if (!LoadSizeBinding(size_bindings[index], &state.last_error)) {
            ResetGameplaySeams();
            if (error_message != nullptr) {
                *error_message = state.last_error;
            }
            return false;
        }
    }

    state.loaded = true;
    state.last_error.clear();
    return true;
}

void ShutdownGameplaySeams() {
    auto& state = GetGameplaySeamState();
    std::scoped_lock lock(state.mutex);
    ResetGameplaySeams();
    state.loaded = false;
    state.last_error.clear();
}

bool AreGameplaySeamsLoaded() {
    auto& state = GetGameplaySeamState();
    std::scoped_lock lock(state.mutex);
    return state.loaded;
}

std::string GetGameplaySeamsLoadError() {
    auto& state = GetGameplaySeamState();
    std::scoped_lock lock(state.mutex);
    return state.last_error;
}

}  // namespace sdmod
