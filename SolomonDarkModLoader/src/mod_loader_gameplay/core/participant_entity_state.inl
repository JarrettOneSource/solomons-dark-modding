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
        RegisteredGameNpc = 3,
    };

    std::uint64_t bot_id = 0;
    multiplayer::MultiplayerCharacterProfile character_profile;
    multiplayer::ParticipantSceneIntent scene_intent;
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
    float dynamic_render_drive_move_blend = 0.0f;
    uintptr_t standalone_progression_wrapper_address = 0;
    uintptr_t standalone_progression_inner_address = 0;
    uintptr_t standalone_equip_wrapper_address = 0;
    uintptr_t standalone_equip_inner_address = 0;
    bool registered_gamenpc_goal_active = false;
    bool registered_gamenpc_following_local_slot = false;
    float registered_gamenpc_goal_x = 0.0f;
    float registered_gamenpc_goal_y = 0.0f;
    bool gameplay_attach_applied = false;
    bool raw_allocation = false;
    uintptr_t synthetic_source_profile_address = 0;
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

    // Ongoing cast state. The loader primes the cast once and, for gameplay-slot
    // bots, keeps a stock-owned startup/watch state alive across ticks. Startup
    // runs by letting the native PlayerActorTick see the prepared actor/progression
    // fields while the bot is temporarily presented as local slot 0. After the
    // stock handler latches or allocates a spell object, the loader just watches
    // actor+0x160 (animation_drive_state), actor+0x1EC (mNoInterrupt), and the
    // cached spell handle (actor+0x27C / +0x27E) until cleanup.
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
        bool saw_latch = false;
        bool saw_activity = false;
        bool saw_live_handle = false;
        bool bounded_release_requested = false;
        bool bounded_release_at_max_size = false;
        bool bounded_release_at_damage_threshold = false;
        float bounded_release_charge = 0.0f;
        float bounded_release_base_damage = 0.0f;
        float bounded_release_statbook_damage = 0.0f;
        float bounded_release_projected_damage = 0.0f;
        float bounded_release_target_hp = 0.0f;
        uintptr_t bounded_release_target_actor = 0;
        bool bounded_release_damage_native = false;
        bool bounded_max_size_reached = false;
        int bounded_post_release_ticks_waiting = 0;
        bool bounded_cleanup_completed = false;
        std::uint64_t bounded_cleanup_clear_after_ms = 0;
        bool startup_in_progress = false;
        bool requires_local_slot_native_tick = false;
        bool post_stock_dispatch_attempted = false;
        uintptr_t pure_primary_item_sink_fallback = 0;
        multiplayer::BotManaChargeKind mana_charge_kind =
            multiplayer::BotManaChargeKind::None;
        float mana_cost = 0.0f;
        float mana_spent_total = 0.0f;
        std::int32_t mana_statbook_level = 1;
        std::uint64_t mana_last_charge_ms = 0;
        static constexpr int kMaxTicksWaiting = 300;
        static constexpr int kMaxStartupTicksWaiting = 12;
        // Lua retargets every 100 ms. Keep continuous primaries alive through
        // short handoffs, but release promptly when the target is really gone.
        static constexpr int kTargetlessRetargetGraceTicks = kMaxStartupTicksWaiting * 2;
    };
    OngoingCastState ongoing_cast{};
};

struct LocalPlayerCastShimState {
    bool active = false;
    uintptr_t actor_address = 0;
    std::uint8_t saved_actor_slot = 0;
    uintptr_t gameplay_address = 0;
    uintptr_t local_progression_slot_offset = 0;
    uintptr_t saved_local_progression_handle = 0;
    uintptr_t redirected_progression_handle = 0;
    bool progression_slot_restore_needed = false;
    bool progression_slot_redirected = false;
};
