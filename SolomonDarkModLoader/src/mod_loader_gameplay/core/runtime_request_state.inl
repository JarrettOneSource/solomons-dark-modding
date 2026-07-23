struct ArenaWaveStartState {
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

struct PendingRewardSpawnRequest {
    std::string kind;
    int amount = 0;
    float x = 0.0f;
    float y = 0.0f;
};

struct PendingNestedSackInventoryFixture {
    std::int32_t potion_slot = 0;
    std::int32_t stack_count = 1;
};

struct PendingClientLocalLootSuppressionRequest {
    std::string reason;
    std::uint64_t not_before_ms = 0;
};

struct PendingNativeInventoryCredit {
    std::uint64_t authority_participant_id = 0;
    std::uint32_t run_nonce = 0;
    std::uint64_t network_drop_id = 0;
    std::uint32_t item_type_id = 0;
    std::uint32_t item_recipe_uid = 0;
    bool item_color_state_valid = false;
    std::array<std::uint8_t, multiplayer::kParticipantVisualLinkColorBlockBytes>
        item_color_state = {};
    std::int32_t item_slot = -1;
    std::int32_t stack_count = 0;
    std::uint32_t inventory_revision = 0;
    std::uint32_t attempts = 0;
    std::uint64_t queued_ms = 0;
    std::uint64_t next_attempt_ms = 0;
};

struct PendingLuaItemGrant {
    std::uint64_t authority_participant_id = 0;
    std::uint64_t request_id = 0;
    std::uint64_t content_id = 0;
    bool color_state_valid = false;
    std::array<std::uint8_t, multiplayer::kParticipantVisualLinkColorBlockBytes>
        color_state = {};
    std::uint32_t attempts = 0;
    std::uint64_t queued_ms = 0;
    std::uint64_t next_attempt_ms = 0;
};

struct PendingLocalInventoryEquipRequest {
    std::uint32_t recipe_uid = 0;
    uintptr_t gameplay_scene_address = 0;
};

struct PendingHostLootDropDeactivation {
    std::uint32_t run_nonce = 0;
    std::uint64_t network_drop_id = 0;
    uintptr_t actor_address = 0;
    multiplayer::LootDropKind drop_kind = multiplayer::LootDropKind::Unknown;
};

struct PendingParticipantEntitySyncRequest {
    std::uint64_t bot_id = 0;
    multiplayer::MultiplayerCharacterProfile character_profile;
    multiplayer::ParticipantSceneIntent scene_intent;
    bool has_transform = false;
    bool has_heading = false;
    float x = 0.0f;
    float y = 0.0f;
    float heading = 0.0f;
    std::uint64_t next_attempt_ms = 0;
};

struct PendingGameplayRegionSwitchRequest {
    int region_index = -1;
    std::uint64_t next_attempt_ms = 0;
};

struct PendingMultiplayerDampenEffectRequest {
    std::uint64_t owner_participant_id = 0;
    std::uint32_t cast_sequence = 0;
    float position_x = 0.0f;
    float position_y = 0.0f;
};

struct PendingLocalPlayerVitalsCorrection {
    std::uint32_t correction_sequence = 0;
    std::uint8_t transient_status_flags = 0;
    std::int32_t poison_remaining_ticks = 0;
    float poison_damage_per_tick = 0.0f;
    std::int32_t webbed_remaining_ticks = 0;
    float webbed_strength = 0.0f;
    std::uint8_t correction_flags = 0;
    float magic_shield_absorb_remaining = 0.0f;
    float magic_shield_absorb_capacity = 0.0f;
    float magic_shield_explosion_fraction = 0.0f;
    float magic_shield_hit_flash = 0.0f;
};

struct PendingNativePoisonBehaviorProbe {
    std::uint64_t target_participant_id = 0;
    std::int32_t duration_ticks = 0;
    float damage_per_tick = 0.0f;
    std::int8_t source_slot = 0;
};

struct PendingNativeMagicHitBehaviorProbe {
    std::uint64_t request_serial = 0;
    std::uint64_t target_participant_id = 0;
    float projectile_damage = 0.0f;
    float magic_damage = 0.0f;
    float poison_damage = 0.0f;
    std::uint32_t attempts = 0;
};

struct NativeMagicHitBehaviorProbeResult {
    std::uint64_t request_serial = 0;
    bool success = false;
    float hp_before = 0.0f;
    float hp_after = 0.0f;
    std::string error;
};

struct PendingNativeEnemyDeathProbe {
    std::uint64_t request_serial = 0;
    uintptr_t actor_address = 0;
    uintptr_t expected_config_address = 0;
    uintptr_t restore_config_address = 0;
};

struct NativeEnemyDeathProbeResult {
    std::uint64_t request_serial = 0;
    bool success = false;
    std::uint32_t exception_code = 0;
    bool config_restored = false;
    std::string error;
};

struct PendingNativeExperienceGainProbe {
    std::uint64_t request_serial = 0;
    float amount = 0.0f;
    bool apply_native_scaling = false;
};

struct NativeExperienceGainProbeResult {
    std::uint64_t request_serial = 0;
    bool success = false;
    float xp_before = 0.0f;
    float xp_after = 0.0f;
    std::uint32_t exception_code = 0;
    std::string error;
};

struct PendingNativeStaffEffectProbe {
    std::uint64_t request_serial = 0;
    uintptr_t source_actor = 0;
    uintptr_t target_actor = 0;
    std::uint32_t variant = 0;
};

struct NativeStaffEffectProbeResult {
    std::uint64_t request_serial = 0;
    bool success = false;
    float hp_before = 0.0f;
    float hp_after = 0.0f;
    std::string error;
};

struct GameplayKeyboardInjectionState {
    X86Hook mouse_refresh_hook;
    X86Hook edge_hook;
    X86Hook player_actor_tick_hook;
    X86Hook player_actor_progression_handle_hook;
    X86Hook player_actor_apply_mana_delta_hook;
    X86Hook player_actor_dtor_hook;
    X86Hook player_actor_vtable28_hook;
    X86Hook player_actor_secondary_spell_cast_hook;
    X86Hook secondary_cursor_world_projection_hook;
    X86Hook player_actor_magic_damage_hook;
    X86Hook badguy_damage_hook;
    X86Hook poisoned_modifier_tick_hook;
    X86Hook webbed_modifier_tick_hook;
    X86Hook player_actor_pure_primary_gate_hook;
    X86Hook player_control_brain_update_hook;
    X86Hook pure_primary_spell_start_hook;
    X86Hook pure_primary_attack_dispatch_hook;
    X86Hook fire_ember_ctor_hook;
    X86Hook pure_primary_post_builder_hook;
    X86Hook spell_cast_dispatcher_hook;
    X86Hook spell_action_builder_hook;
    X86Hook spell_builder_reset_hook;
    X86Hook spell_builder_finalize_hook;
    X86Hook gameplay_hud_render_dispatch_hook;
    X86Hook gameplay_ui_glyph_draw_hook;
    X86Hook gameplay_ui_ally_label_glyph_draw_hook;
    X86Hook actor_animation_advance_hook;
    X86Hook puppet_manager_delete_puppet_hook;
    X86Hook pointer_list_delete_batch_hook;
    X86Hook actor_world_unregister_hook;
    X86Hook gameplay_switch_region_hook;
    X86Hook monster_pathfinding_refresh_target_hook;
    X86Hook badguy_move_step_hook;
    X86Hook gold_pickup_hook;
    X86Hook orb_pickup_hook;
    X86Hook item_drop_pickup_hook;
    X86Hook powerup_pickup_hook;
    uintptr_t damage_context_reset_address = 0;
    uintptr_t damage_context_target_address = 0;
    uintptr_t damage_context_source_address = 0;
    uintptr_t damage_context_flags_address = 0;
    uintptr_t damage_context_primary_address = 0;
    uintptr_t damage_context_secondary_address = 0;
    bool initialized = false;
    std::array<std::atomic<std::uint32_t>, 256> pending_scancodes{};
    std::atomic<bool> last_observed_mouse_left_down{false};
    std::atomic<std::uint64_t> mouse_left_edge_serial{0};
    std::atomic<std::uint64_t> mouse_left_edge_tick_ms{0};
    std::atomic<std::uint64_t> claimed_primary_cast_edge_serial{0};
    std::atomic<std::int32_t> last_belt_slot_edge{-1};
    std::atomic<std::uint64_t> last_belt_slot_edge_tick_ms{0};
    std::atomic<std::uint32_t> pending_mouse_left_edge_events{0};
    std::atomic<std::uint32_t> pending_mouse_left_frames{0};
    std::atomic<std::uint64_t> last_mouse_left_hold_player_tick_generation{0};
    std::atomic<bool> last_observed_mouse_right_down{false};
    std::atomic<std::uint64_t> mouse_right_edge_serial{0};
    std::atomic<std::uint32_t> pending_mouse_right_frames{0};
    std::atomic<std::uint64_t> last_mouse_right_hold_player_tick_generation{0};
    std::atomic<uintptr_t> input_state_address{0};
    std::atomic<float> pending_movement_x{0.0f};
    std::atomic<float> pending_movement_y{0.0f};
    std::atomic<std::uint32_t> pending_movement_frames{0};
    std::atomic<float> local_movement_intent_x{0.0f};
    std::atomic<float> local_movement_intent_y{0.0f};
    std::atomic<std::uint64_t> local_movement_intent_observed_ms{0};
    std::atomic<std::uint32_t> pending_injected_keyboard_control_frames{0};
    std::atomic<std::uint32_t> pending_manual_spawner_primary_cast_allowances{0};
    std::atomic<std::uint64_t> manual_spawner_primary_cast_control_grace_until_ms{0};
    std::atomic<uintptr_t> manual_spawner_primary_target_actor{0};
    std::atomic<bool> injected_mouse_left_active{false};
    std::atomic<bool> injected_mouse_right_active{false};
    std::atomic<std::uint32_t> pending_hub_start_testrun_requests{0};
    std::atomic<std::uint32_t> pending_hub_service_request{0};
    std::atomic<std::uint32_t> pending_start_waves_requests{0};
    std::atomic<std::uint32_t> pending_enable_combat_prelude_requests{0};
    std::atomic<std::uint32_t> pending_run_generation_seed{0};
    std::atomic<std::uint8_t> pending_run_generation_seed_valid{0};
    std::atomic<std::uint32_t> applied_run_generation_seed{0};
    std::atomic<std::uint64_t> hub_start_testrun_cooldown_until_ms{0};
    std::atomic<std::uint64_t> start_waves_retry_not_before_ms{0};
    std::atomic<std::uint64_t> wizard_bot_sync_not_before_ms{0};
    std::atomic<std::uint64_t> gameplay_region_switch_not_before_ms{0};
    std::atomic<std::uint64_t> scene_churn_not_before_ms{0};
    std::atomic<uintptr_t> local_player_tick_scene_address{0};
    std::atomic<uintptr_t> local_player_tick_actor_address{0};
    std::atomic<std::uint64_t> local_player_tick_generation{0};
    std::atomic<std::uint64_t> local_player_tick_observed_ms{0};
    std::atomic<std::uint64_t>
        app_tick_observed_local_player_tick_generation{0};
    std::mutex pending_gameplay_world_actions_mutex;
    std::deque<PendingRewardSpawnRequest> pending_reward_spawn_requests;
    std::deque<PendingNestedSackInventoryFixture>
        pending_nested_sack_inventory_fixtures;
    std::deque<PendingClientLocalLootSuppressionRequest> pending_client_local_loot_suppression_requests;
    std::deque<PendingNativeInventoryCredit> pending_native_inventory_credits;
    std::deque<PendingLuaItemGrant> pending_lua_item_grants;
    std::deque<PendingLocalInventoryEquipRequest>
        pending_local_inventory_equip_requests;
    std::unordered_set<std::uint64_t> pending_native_inventory_credit_drop_ids;
    std::unordered_set<std::uint64_t> completed_native_inventory_credit_drop_ids;
    std::uint32_t native_inventory_credit_run_nonce = 0;
    std::deque<multiplayer::LootSnapshotRuntimeInfo> pending_replicated_loot_snapshots;
    std::deque<PendingHostLootDropDeactivation>
        pending_host_loot_drop_deactivations;
    std::unordered_set<std::uint64_t>
        pending_host_loot_drop_deactivation_ids;
    std::deque<SDModHostLootDropDeactivationResult>
        completed_host_loot_drop_deactivations;
    std::uint32_t host_loot_drop_deactivation_run_nonce = 0;
    std::deque<PendingParticipantEntitySyncRequest> pending_participant_sync_requests;
    std::deque<PendingGameplayRegionSwitchRequest> pending_gameplay_region_switch_requests;
    std::deque<PendingMultiplayerDampenEffectRequest> pending_multiplayer_dampen_effect_requests;
    std::deque<PendingLocalPlayerVitalsCorrection>
        pending_local_player_vitals_corrections;
    std::deque<PendingNativePoisonBehaviorProbe> pending_native_poison_behavior_probes;
    std::deque<PendingNativeMagicHitBehaviorProbe> pending_native_magic_hit_behavior_probes;
    std::uint64_t next_native_magic_hit_behavior_probe_serial = 1;
    NativeMagicHitBehaviorProbeResult native_magic_hit_behavior_probe_result;
    std::deque<PendingNativeEnemyDeathProbe> pending_native_enemy_death_probes;
    std::uint64_t next_native_enemy_death_probe_serial = 1;
    NativeEnemyDeathProbeResult native_enemy_death_probe_result;
    std::deque<PendingNativeExperienceGainProbe>
        pending_native_experience_gain_probes;
    std::uint64_t next_native_experience_gain_probe_serial = 1;
    NativeExperienceGainProbeResult native_experience_gain_probe_result;
    std::deque<PendingNativeStaffEffectProbe> pending_native_staff_effect_probes;
    std::uint64_t next_native_staff_effect_probe_serial = 1;
    NativeStaffEffectProbeResult native_staff_effect_probe_result;
    std::deque<std::uint64_t> pending_participant_destroy_requests;
} g_gameplay_keyboard_injection;

void PublishLocalPlayerTickOwnership(
    uintptr_t gameplay_address,
    uintptr_t actor_address) {
    if (gameplay_address == 0 || actor_address == 0) {
        return;
    }

    g_gameplay_keyboard_injection.local_player_tick_scene_address.store(
        gameplay_address,
        std::memory_order_relaxed);
    g_gameplay_keyboard_injection.local_player_tick_actor_address.store(
        actor_address,
        std::memory_order_relaxed);
    g_gameplay_keyboard_injection.local_player_tick_observed_ms.store(
        static_cast<std::uint64_t>(GetTickCount64()),
        std::memory_order_relaxed);
    g_gameplay_keyboard_injection.local_player_tick_generation.fetch_add(
        1,
        std::memory_order_release);
}

void ClearLocalPlayerTickOwnership() {
    g_gameplay_keyboard_injection.local_player_tick_scene_address.store(
        0,
        std::memory_order_relaxed);
    g_gameplay_keyboard_injection.local_player_tick_actor_address.store(
        0,
        std::memory_order_relaxed);
    g_gameplay_keyboard_injection.local_player_tick_observed_ms.store(
        0,
        std::memory_order_relaxed);
    g_gameplay_keyboard_injection.local_player_tick_generation.fetch_add(
        1,
        std::memory_order_release);
}

void ResetLocalPlayerTickOwnershipState() {
    g_gameplay_keyboard_injection.local_player_tick_scene_address.store(
        0,
        std::memory_order_relaxed);
    g_gameplay_keyboard_injection.local_player_tick_actor_address.store(
        0,
        std::memory_order_relaxed);
    g_gameplay_keyboard_injection.local_player_tick_observed_ms.store(
        0,
        std::memory_order_relaxed);
    g_gameplay_keyboard_injection.local_player_tick_generation.store(
        0,
        std::memory_order_relaxed);
    g_gameplay_keyboard_injection
        .app_tick_observed_local_player_tick_generation.store(
            0,
            std::memory_order_relaxed);
}

thread_local std::uint32_t g_multiplayer_client_authorized_hub_run_switch_depth = 0;
thread_local std::uint32_t g_loader_owned_actor_destroy_unregister_depth = 0;
thread_local std::uint32_t g_remote_secondary_spell_dispatch_depth = 0;
thread_local uintptr_t g_client_owner_authorized_damage_target = 0;
thread_local bool g_authoritative_local_player_damage_replay_active = false;
