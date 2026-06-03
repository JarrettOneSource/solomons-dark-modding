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

struct GameplayKeyboardInjectionState {
    X86Hook mouse_refresh_hook;
    X86Hook edge_hook;
    X86Hook player_actor_tick_hook;
    X86Hook player_actor_progression_handle_hook;
    X86Hook player_actor_apply_mana_delta_hook;
    X86Hook player_actor_dtor_hook;
    X86Hook player_actor_vtable28_hook;
    X86Hook player_actor_pure_primary_gate_hook;
    X86Hook player_control_brain_update_hook;
    X86Hook pure_primary_spell_start_hook;
    X86Hook pure_primary_post_builder_hook;
    X86Hook spell_cast_dispatcher_hook;
    X86Hook spell_action_builder_hook;
    X86Hook spell_builder_reset_hook;
    X86Hook spell_builder_finalize_hook;
    X86Hook gameplay_hud_render_dispatch_hook;
    X86Hook actor_animation_advance_hook;
    X86Hook puppet_manager_delete_puppet_hook;
    X86Hook pointer_list_delete_batch_hook;
    X86Hook actor_world_unregister_hook;
    X86Hook gameplay_switch_region_hook;
    X86Hook monster_pathfinding_refresh_target_hook;
    bool initialized = false;
    std::array<std::atomic<std::uint32_t>, 256> pending_scancodes{};
    std::atomic<bool> last_observed_mouse_left_down{false};
    std::atomic<std::uint64_t> mouse_left_edge_serial{0};
    std::atomic<std::uint64_t> mouse_left_edge_tick_ms{0};
    std::atomic<std::uint32_t> pending_mouse_left_edge_events{0};
    std::atomic<std::uint32_t> pending_mouse_left_frames{0};
    std::atomic<std::uint32_t> pending_hub_start_testrun_requests{0};
    std::atomic<std::uint32_t> pending_start_waves_requests{0};
    std::atomic<std::uint32_t> pending_enable_combat_prelude_requests{0};
    std::atomic<std::uint32_t> pending_run_generation_seed{0};
    std::atomic<std::uint8_t> pending_run_generation_seed_valid{0};
    std::atomic<std::uint64_t> hub_start_testrun_cooldown_until_ms{0};
    std::atomic<std::uint64_t> start_waves_retry_not_before_ms{0};
    std::atomic<std::uint64_t> wizard_bot_sync_not_before_ms{0};
    std::atomic<std::uint64_t> gameplay_region_switch_not_before_ms{0};
    std::atomic<std::uint64_t> scene_churn_not_before_ms{0};
    std::mutex pending_gameplay_world_actions_mutex;
    std::deque<PendingRewardSpawnRequest> pending_reward_spawn_requests;
    std::deque<PendingParticipantEntitySyncRequest> pending_participant_sync_requests;
    std::deque<PendingGameplayRegionSwitchRequest> pending_gameplay_region_switch_requests;
    std::deque<std::uint64_t> pending_participant_destroy_requests;
} g_gameplay_keyboard_injection;

thread_local std::uint32_t g_multiplayer_client_authorized_hub_run_switch_depth = 0;
thread_local std::uint32_t g_loader_owned_actor_destroy_unregister_depth = 0;
