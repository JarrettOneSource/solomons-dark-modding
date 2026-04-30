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
        SDMOD_ADDR("gameplay.hooks", "player_actor_pure_primary_gate", kPlayerActorPurePrimaryGate),
        SDMOD_ADDR("gameplay.hooks", "player_control_brain_update", kPlayerControlBrainUpdate),
        SDMOD_ADDR("gameplay.hooks", "gameplay_hud_render_dispatch", kGameplayHudRenderDispatch),
        SDMOD_ADDR("gameplay.hooks", "gameplay_string_assign", kGameplayStringAssign),
        SDMOD_ADDR("gameplay.hooks", "gameplay_exact_text_object_render", kGameplayExactTextObjectRender),
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
        SDMOD_ADDR("gameplay.hooks", "equip_attachment_get_current_item", kEquipAttachmentSinkGetCurrentItem),
        SDMOD_ADDR("gameplay.hooks", "spell_action_builder", kSpellActionBuilder),
        SDMOD_ADDR("gameplay.hooks", "spell_builder_reset", kSpellBuilderReset),
        SDMOD_ADDR("gameplay.hooks", "spell_builder_finalize", kSpellBuilderFinalize),
        SDMOD_ADDR("gameplay.hooks", "pure_primary_post_builder", kPurePrimaryPostBuilder),
        SDMOD_ADDR("gameplay.hooks", "item_staff_ctor", kItemStaffCtor),
        SDMOD_ADDR("gameplay.hooks", "item_wand_ctor", kItemWandCtor),
        SDMOD_ADDR("gameplay.hooks", "arena_start_run_dispatch", kArenaStartRunDispatch),
        SDMOD_ADDR("gameplay.hooks", "arena_create", kArenaCreate),
        SDMOD_ADDR("gameplay.hooks", "arena_start_waves", kArenaStartWaves),
        SDMOD_ADDR("gameplay.hooks", "gameplay_combat_prelude_primary_mode", kGameplayCombatPreludePrimaryMode),
        SDMOD_ADDR("gameplay.hooks", "gameplay_combat_prelude_secondary_mode", kGameplayCombatPreludeSecondaryMode),
        SDMOD_ADDR("gameplay.hooks", "arena_combat_prelude_dispatch", kArenaCombatPreludeDispatch),
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
        SDMOD_ADDR("gameplay.hooks", "native_int_array_clear", kNativeIntArrayClear),
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
        SDMOD_ADDR("gameplay.globals", "gameplay_runtime", kGameplayRuntimeGlobal),
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
        SDMOD_ADDR("gameplay.globals", "native_int_array_vtable", kNativeIntArrayVtable),
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
        SDMOD_ADDR("gameplay.globals", "gameplay_exact_text_object", kGameplayExactTextObjectGlobal),

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
        SDMOD_ADDR("run_lifecycle.hooks", "spell_cast_pure_primary", kSpellCastPurePrimary),
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
