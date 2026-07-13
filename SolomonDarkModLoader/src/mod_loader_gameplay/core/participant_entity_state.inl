struct ObservedActorAnimationDriveProfile {
    bool valid = false;
    std::array<std::uint8_t, kActorAnimationConfigBlockSize> config_bytes{};
    float walk_cycle_primary = 0.0f;
    float walk_cycle_secondary = 0.0f;
    float render_drive_stride = 0.0f;
    float render_advance_rate = 0.0f;
};

struct BotPathWaypoint {
    int grid_x = -1;
    int grid_y = -1;
    float x = 0.0f;
    float y = 0.0f;
};

struct ParticipantEntityBinding {
    enum class Kind : std::uint8_t {
        PlaceholderEnemy = 0,
        StandaloneWizard = 1,
        GameplaySlotWizard = 2,
    };

    std::uint64_t bot_id = 0;
    multiplayer::MultiplayerCharacterProfile character_profile;
    multiplayer::ParticipantSceneIntent scene_intent;
    multiplayer::ParticipantControllerKind controller_kind = multiplayer::ParticipantControllerKind::LuaBrain;
    std::uint32_t concentration_revision = 0;
    bool concentration_selection_valid = false;
    std::int32_t concentration_entry_a = -1;
    std::int32_t concentration_entry_b = -1;
    uintptr_t actor_address = 0;
    int gameplay_slot = -1;
    Kind kind = Kind::PlaceholderEnemy;
    multiplayer::BotControllerState controller_state = multiplayer::BotControllerState::Idle;
    std::uint64_t movement_intent_revision = 0;
    bool movement_active = false;
    float last_movement_displacement = 0.0f;
    bool has_target = false;
    float direction_x = 0.0f;
    float direction_y = 0.0f;
    float native_movement_accumulator_x = 0.0f;
    float native_movement_accumulator_y = 0.0f;
    bool desired_heading_valid = false;
    float desired_heading = 0.0f;
    float target_x = 0.0f;
    float target_y = 0.0f;
    float distance_to_target = 0.0f;
    bool path_active = false;
    bool path_failed = false;
    std::uint64_t active_path_revision = 0;
    std::uint64_t next_path_retry_not_before_ms = 0;
    std::uint64_t last_path_debug_log_ms = 0;
    std::size_t path_waypoint_index = 0;
    float current_waypoint_x = 0.0f;
    float current_waypoint_y = 0.0f;
    std::vector<BotPathWaypoint> path_waypoints;
    std::uint64_t next_scene_materialize_retry_ms = 0;
    uintptr_t materialized_scene_address = 0;
    uintptr_t materialized_world_address = 0;
    int materialized_region_index = -1;
    int last_applied_animation_state_id = kUnknownAnimationStateId - 1;
    ObservedActorAnimationDriveProfile standalone_idle_animation_drive_profile;
    ObservedActorAnimationDriveProfile standalone_moving_animation_drive_profile;
    float dynamic_walk_cycle_primary = 0.0f;
    float dynamic_walk_cycle_secondary = 0.0f;
    float dynamic_render_drive_stride = 0.0f;
    float dynamic_render_advance_rate = 0.0f;
    float dynamic_render_advance_phase = 0.0f;
    uintptr_t standalone_progression_wrapper_address = 0;
    uintptr_t standalone_progression_inner_address = 0;
    uintptr_t standalone_equip_wrapper_address = 0;
    uintptr_t standalone_equip_inner_address = 0;
    bool gameplay_attach_applied = false;
    bool raw_allocation = false;
    bool replicated_transform_valid = false;
    float replicated_target_x = 0.0f;
    float replicated_target_y = 0.0f;
    float replicated_target_heading = 0.0f;
    bool replicated_presentation_valid = false;
    std::uint8_t replicated_anim_drive_state = 0;
    std::uint16_t replicated_presentation_flags = 0;
    std::uint32_t replicated_attachment_staff_visual_state = 0;
    std::uint8_t replicated_render_variant_primary = 0;
    std::uint8_t replicated_render_variant_secondary = 0;
    std::uint8_t replicated_render_weapon_type = 0;
    std::uint8_t replicated_render_selection_byte = 0;
    std::uint8_t replicated_render_variant_tertiary = 0;
    std::uint32_t replicated_primary_visual_link_type_id = 0;
    std::uint32_t replicated_secondary_visual_link_type_id = 0;
    std::array<std::uint8_t, multiplayer::kParticipantVisualLinkColorBlockBytes>
        replicated_primary_visual_link_color_block = {};
    std::array<std::uint8_t, multiplayer::kParticipantVisualLinkColorBlockBytes>
        replicated_secondary_visual_link_color_block = {};
    std::uint32_t replicated_anim_drive_state_word = 0;
    float replicated_walk_cycle_primary = 0.0f;
    float replicated_walk_cycle_secondary = 0.0f;
    float replicated_render_drive_stride = 0.0f;
    float replicated_render_advance_rate = 0.0f;
    float replicated_render_advance_phase = 0.0f;
    float replicated_render_drive_effect_timer = 0.0f;
    float replicated_render_drive_effect_progress = 0.0f;
    std::uint64_t replicated_transform_packet_ms = 0;
    std::uint64_t replicated_transform_playback_ms = 0;
    // "Currently facing" heading pinned across ticks. Sources: movement step
    // and cast dispatch each write this when they fire. Last setter wins, and
    // within a single tick cast is processed after movement so it takes
    // priority. The tick hook writes this value to the actor's heading field
    // every tick while valid, so the bot keeps facing whichever direction was
    // last set until something explicitly changes it again.
    float facing_heading_value = 0.0f;
    bool facing_heading_valid = false;
    uintptr_t facing_target_actor_address = 0;
    bool stock_tick_facing_origin_valid = false;
    float stock_tick_facing_origin_x = 0.0f;
    float stock_tick_facing_origin_y = 0.0f;
    bool death_transition_stock_tick_seen = false;
    bool native_remote_vital_baseline_valid = false;
    float native_remote_last_written_hp = 0.0f;
    float native_remote_last_written_max_hp = 0.0f;
    std::uint64_t mana_recovery_not_before_ms = 0;
    std::uint64_t last_mana_recovery_log_ms = 0;
    std::uint64_t last_mana_reserve_cleanup_log_ms = 0;
    std::uint8_t persistent_status_reconcile_desired_flags = 0;
    std::uint64_t persistent_status_reconcile_desired_since_ms = 0;
    std::uint64_t persistent_status_reconcile_not_before_ms = 0;

    // Ongoing cast state. The loader primes the cast once and keeps a stock-owned
    // startup/watch state alive across ticks. Native slot gates are unlocked at
    // their recovered branch sites, so gameplay-slot bots keep their real slot
    // and progression handles while PlayerActorTick and the spell handlers run.
    struct OngoingCastState {
        enum class Lane : std::uint8_t {
            Dispatcher = 0,
            PurePrimary = 1,
        };
        bool active = false;
        Lane lane = Lane::Dispatcher;
        std::int32_t skill_id = 0;
        std::int32_t dispatcher_skill_id = 0;
        int selection_state_target = kUnknownAnimationStateId;
        bool uses_dispatcher_skill_id = false;
        bool have_aim_heading = false;
        float aim_heading = 0.0f;
        bool have_aim_target = false;
        float aim_target_x = 0.0f;
        float aim_target_y = 0.0f;
        uintptr_t target_actor_address = 0;
        float heading_before = 0.0f;
        float aim_x_before = 0.0f;
        float aim_y_before = 0.0f;
        std::uint32_t aim_aux0_before = 0;
        std::uint32_t aim_aux1_before = 0;
        std::uint8_t spread_before = 0;
        std::int32_t primary_skill_id_before = 0;
        std::int32_t previous_skill_id_before = 0;
        std::uint32_t primary_action_latch_e4_before = 0;
        std::uint32_t primary_action_latch_e8_before = 0;
        std::uint8_t post_gate_active_before = 0;
        uintptr_t current_target_actor_before = 0;
        bool current_target_actor_override_active = false;
        std::uint8_t native_target_group_before = kTargetHandleGroupSentinel;
        std::uint16_t native_target_slot_before = kTargetHandleSlotSentinel;
        bool native_target_handle_override_active = false;
        uintptr_t selection_state_pointer = 0;
        int selection_state_before = kUnknownAnimationStateId;
        bool selection_state_object_snapshot_valid = false;
        std::array<std::uint8_t, 0x38> selection_state_object_snapshot = {};
        std::uint8_t selection_target_group_before = 0xFF;
        std::uint16_t selection_target_slot_before = 0xFFFF;
        std::int32_t selection_retarget_ticks_before = 0;
        std::int32_t selection_target_cooldown_before = 0;
        std::int32_t selection_target_extra_before = 0;
        std::int32_t selection_target_flags_before = 0;
        bool selection_target_seed_active = false;
        std::uint8_t selection_target_group_seed = 0xFF;
        std::uint16_t selection_target_slot_seed = 0xFFFF;
        std::int32_t selection_target_hold_ticks = 0;
        bool selection_brain_override_active = false;
        bool selection_state_override_active = false;
        int gameplay_selection_state_before = kUnknownAnimationStateId;
        bool gameplay_selection_state_override_active = false;
        uintptr_t progression_runtime_address = 0;
        std::int32_t progression_spell_id_before = 0;
        bool progression_spell_id_override_active = false;
        int ticks_waiting = 0;
        int startup_ticks_waiting = 0;
        int targetless_ticks_waiting = 0;
        bool remote_input_controlled = false;
        std::uint32_t remote_input_cast_sequence = 0;
        bool remote_input_release_requested = false;
        bool remote_input_timed_out = false;
        int remote_input_release_ticks_waiting = 0;
        bool remote_per_cast_projectile_baseline_valid = false;
        std::uint32_t remote_per_cast_projectile_expected_type = 0;
        int remote_per_cast_projectile_count_before = 0;
        std::vector<uintptr_t> remote_per_cast_projectile_addresses_before;
        bool remote_per_cast_projectile_emission_latched = false;
        int remote_per_cast_duplicate_dispatches_suppressed = 0;
        bool remote_per_cast_projectile_observed = false;
        uintptr_t remote_per_cast_projectile_observed_actor = 0;
        int remote_per_cast_projectile_observed_ticks_waiting = 0;
        int remote_per_cast_projectile_missing_ticks_waiting = 0;
        bool remote_per_cast_projectile_reached_target = false;
        int remote_per_cast_projectile_target_ticks_waiting = 0;
        bool remote_per_cast_projectile_trajectory_valid = false;
        float remote_per_cast_projectile_first_x = 0.0f;
        float remote_per_cast_projectile_first_y = 0.0f;
        float remote_per_cast_projectile_last_x = 0.0f;
        float remote_per_cast_projectile_last_y = 0.0f;
        float remote_per_cast_projectile_min_target_distance = 0.0f;
        int remote_per_cast_projectile_trajectory_samples = 0;
        bool saw_latch = false;
        bool saw_activity = false;
        bool saw_live_handle = false;
        bool bounded_release_requested = false;
        bool bounded_release_at_max_size = false;
        bool bounded_release_target_lethal = false;
        float bounded_release_charge = 0.0f;
        float bounded_release_base_damage = 0.0f;
        float bounded_release_projected_damage = 0.0f;
        float bounded_release_damage_output_scale = 0.0f;
        float bounded_release_damage_scale = 0.0f;
        float bounded_release_damage_floor = 0.0f;
        float bounded_release_damage_cap_scale = 0.0f;
        float bounded_release_projected_release_damage = 0.0f;
        float bounded_release_projected_hp_damage = 0.0f;
        float bounded_release_target_hp = 0.0f;
        uintptr_t bounded_release_target_actor = 0;
        bool bounded_max_size_reached = false;
        int bounded_post_release_ticks_waiting = 0;
        bool startup_in_progress = false;
        bool post_stock_dispatch_attempted = false;
        bool native_mana_rate_config_invalidated = false;
        bool native_mana_rate_config_pending_logged = false;
        multiplayer::BotManaChargeKind mana_charge_kind =
            multiplayer::BotManaChargeKind::None;
        float mana_cost = 0.0f;
        std::int32_t mana_progression_level = 1;
        static constexpr int kMaxTicksWaiting = 300;
        static constexpr int kMaxStartupTicksWaiting = 12;
        // Lua retargets every 100 ms. Keep continuous primaries alive through
        // short handoffs, but release promptly when the target is really gone.
        static constexpr int kTargetlessRetargetGraceTicks = kMaxStartupTicksWaiting * 2;
    };
    OngoingCastState ongoing_cast{};
};
