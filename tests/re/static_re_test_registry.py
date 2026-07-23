"""Canonical registry for all static reverse-engineering contracts."""

from __future__ import annotations

from typing import Callable

from repository_identity_contract import (
    test_repository_history_uses_approved_identities,
)
from static_re_boneyard_contracts import (
    test_boneyard_parser_rejects_empty_truncated_and_trailing_files,
    test_flat_boneyard_fixture_matches_native_syncbuffer_envelope,
    test_multiplayer_boneyard_scenery_shares_the_host_generation_boundary,
)
from static_lua_mod_state_contracts import (
    test_lua_mod_state_and_events_are_authority_replicated,
)
from static_lua_draw_contracts import (
    test_lua_draw_is_bounded_local_and_backbuffer_verified,
)
from static_lua_sprites_contracts import (
    test_lua_sprites_are_owned_bounded_sandboxed_and_revisioned,
)
from static_lua_authoring_contracts import (
    test_lua_authoring_is_generated_reloadable_and_safe_thread_executed,
)
from static_lua_roadmap_closure_contracts import (
    test_lua_roadmap_is_closed_under_exact_mod_parity,
)
from static_lua_event_filter_contracts import (
    test_lua_damage_filters_are_ordered_owner_side_and_transactional,
)
from static_lua_enemy_spawn_filter_contracts import (
    test_lua_enemy_spawn_filter_preserves_stock_call_shape_and_ownership,
)
from static_lua_drop_roll_filter_contracts import (
    test_lua_drop_roll_filters_are_owner_side_transactional_and_stock_preserving,
)
from static_lua_wave_spawn_filter_contracts import (
    test_lua_wave_spawn_filters_are_owner_side_transactional_and_stock_preserving,
)
from static_lua_spell_cast_filter_contracts import (
    test_lua_spell_filter_is_owner_side_precast_and_once_per_attempt,
)
from static_lua_resource_filter_contracts import (
    test_lua_resource_filters_are_native_ordered_and_authoritative,
)
from static_lua_storage_contracts import (
    test_lua_storage_is_scoped_bounded_and_transactional,
)
from static_lua_timer_contracts import (
    test_lua_timers_are_bounded_local_and_tick_driven,
)
from static_lua_bus_contracts import (
    test_lua_bus_is_manifest_resolved_bounded_and_local,
)
from static_lua_net_contracts import (
    test_lua_net_is_fragmented_authenticated_and_host_relayed,
)
from static_lua_time_contracts import (
    test_lua_time_is_authority_owned_replicated_and_coherently_gated,
)
from static_lua_content_identity_contracts import (
    test_lua_content_ids_are_canonical_deterministic_and_load_scoped,
)
from static_lua_items_contracts import (
    test_lua_items_register_stable_identity_and_resolve_peer_local_recipes,
)
from static_lua_enemies_contracts import (
    test_lua_enemies_use_exact_stock_spawn_and_replicated_content_identity,
)
from static_lua_spells_contracts import (
    test_lua_spells_register_stable_metadata_and_owned_callbacks,
)
from static_lua_ai_contracts import (
    test_lua_enemy_ai_is_bounded_authority_owned_and_collision_preserving,
)
from static_lua_audio_contracts import (
    test_lua_audio_is_scoped_bounded_local_and_game_owned,
)
from static_lua_camera_contracts import (
    test_lua_camera_is_native_bounded_owned_and_presentation_local,
)
from static_lua_ui_authoring_contracts import (
    test_lua_ui_authoring_is_native_bounded_and_authority_routed,
)
from static_lua_foundations_contracts import (
    test_lua_nav_is_bounded_read_only_and_native_backed,
    test_lua_run_seed_is_authority_owned_and_native_applied,
)
from static_lua_scene_contracts import (
    test_lua_scene_is_address_free_authority_owned_and_peer_followed,
)
from static_lua_waves_contracts import (
    test_lua_waves_parse_track_and_replicate_semantic_summaries,
)
from static_multiplayer_transport_contracts import (
    test_app_thread_transport_verifier_tracks_named_cadence_gap,
    test_build_all_rebuilds_native_loader_from_clean_intermediates,
    test_client_enemy_hot_path_uses_constant_time_authority_cache,
    test_client_replicated_enemy_movement_is_host_authored,
    test_empty_run_snapshot_unregisters_stale_enemies_without_parking,
    test_hub_service_fragments_are_visual_studio_project_items,
    test_hub_students_remain_in_the_stock_transient_lifecycle,
    test_native_project_uses_repo_local_lua_sources,
    test_exact_spawn_retires_invalid_featured_enemy,
    test_run_enemy_death_tombstones_precede_structural_omission,
    test_run_enemy_materialization_preserves_exact_native_type,
    test_scene_tick_keeps_dead_remote_participants_inert,
    test_snapshot_streams_are_compact_and_bandwidth_bounded,
    test_unreliable_snapshot_ordering_is_wrap_safe,
)
from static_multiplayer_ownership_contracts import (
    test_active_pair_visual_capture_routes_by_pair_backend,
    test_client_loot_pickup_requests_are_single_flight_per_drop,
    test_exact_native_equipment_identity_and_color_replicate,
    test_loot_deactivation_uses_stock_deferred_retirement,
    test_lua_exec_timeout_cancels_pending_work,
    test_native_item_pickup_converges_into_stock_inventory,
    test_native_unregister_retires_address_bound_network_identity,
    test_transient_status_correction_ack_waits_for_native_application,
    test_powerup_rewards_are_authoritative_and_native,
    test_remote_windows_lua_bridge_is_persistent_and_framed,
    test_steam_client_reauthentication_preserves_live_message_session,
    test_steam_pair_recovers_lobby_membership_and_requires_stable_readiness,
)
from static_multiplayer_platform_contracts import (
    test_active_steam_behavior_harnesses_preserve_fixture_state,
    test_beta_release_documents_steam_deck_shortcut,
    test_beta_release_smoke_canonicalizes_packaged_steam_path,
    test_defense_probes_follow_host_damage_authority,
    test_explicit_blank_boneyard_removes_native_scenery_and_collision,
    test_host_run_exit_is_authoritative_and_self_correcting,
    test_launcher_auto_accepts_steam_invites_and_hub_gates_discovery,
    test_native_local_player_keeps_stock_input_and_equipment_ownership,
    test_packaged_ui_uses_proton_compatible_launcher,
    test_packaged_ui_does_not_inherit_test_world_overrides,
    test_pair_launcher_drains_redirected_json_output,
    test_progression_matrices_prearm_quiet_spawning_before_run_entry,
    test_proton_contract_runner_avoids_ge11_umu_shim_hang,
    test_proton_input_targets_the_exact_native_game_window,
    test_staff_target_selection_skips_local_only_enemies,
    test_steam_behavior_arena_reset_waits_for_native_spawner,
    test_ui_sandbox_retries_unlatched_create_choices,
    test_website_lobby_links_register_and_route_to_launcher,
)
from static_multiplayer_progression_contracts import (
    test_boneyard_generator_skips_empty_candidate_interpolation,
    test_cpu_tick_stops_after_virtual_update_marks_object_for_removal,
    test_frozen_manual_enemy_cell_membership_stays_position_coherent,
    test_level_up_barrier_waits_for_forced_picker_confirmation,
    test_level_up_choice_result_advances_owned_book_before_resume,
    test_lightning_manual_cluster_stays_inside_flat_arena_spatial_grid,
    test_manual_primary_target_survives_stock_cursor_refresh,
    test_meditation_transient_counters_self_repair_to_native_bounds,
    test_native_item_recipe_selection_excludes_equipped_items,
    test_native_remote_fireball_converts_cast_heading_until_projectile_birth,
    test_native_remote_fireball_conversion_is_scoped_to_stock_fire,
    test_new_run_retires_the_prior_host_run_exit_latch,
    test_orb_pickup_verifier_preserves_native_maxima,
    test_pointer_list_batch_rejects_stale_managed_release_callbacks,
    test_primary_spell_effect_snapshots_do_not_fight_native_replay,
    test_spell_verifiers_quiesce_input_and_prearm_manual_spawning,
    test_steam_friend_active_run_reconnect_is_wired,
    test_steam_friend_native_inventory_matrix_is_wired,
    test_steam_onboarding_waits_out_blocking_dialogs_and_scene_churn,
)
from static_multiplayer_behavior_contracts import (
    test_animated_loot_comparison_bounds_snapshot_phase_skew,
    test_beta_artifact_verifier_reads_bounded_zip_headers,
    test_beta_package_smoke_forwards_a_valid_website_lobby_uri,
    test_cursor_placed_secondaries_replay_owner_world_position,
    test_health_up_contract_composes_with_life_charm,
    test_hub_presentation_uses_stored_authority_across_lifecycle_rotation,
    test_hub_services_use_typed_native_lua_dispatch,
    test_loot_materialization_waits_for_native_field_convergence,
    test_magic_trap_lifetime_follows_cast_owner,
    test_mana_recovery_precondition_holds_zero_until_replication,
    test_mana_recovery_tolerance_respects_float32_precision,
    test_mana_up_contract_replaces_the_initial_rank_bonus,
    test_network_clients_reject_stock_incoming_damage_authority,
    test_natural_offer_expectation_clamps_to_native_maximum,
    test_primary_kill_stress_accepts_a_late_death_from_the_prior_cast,
    test_primary_kill_stress_requires_native_death_evidence_at_epsilon_hp,
    test_primary_kill_stress_resumes_only_a_contiguous_passed_prefix,
    test_reconnect_verifier_has_a_dedicated_cold_launch_timeout,
    test_remote_webbed_escape_consumes_owner_movement_intent,
    test_run_reentry_audits_only_logs_written_during_the_test,
    test_secondary_replay_preserves_owner_authored_aim_when_target_resolves,
    test_secondary_behavior_matrix_uses_native_two_owner_witnesses,
    test_secondary_matrix_isolates_prior_native_effect_lifetimes,
    test_secondary_matrix_drives_targeted_stock_cursor_geometry,
    test_shared_menu_pause_is_host_authoritative_and_time_bounded,
    test_stat_matrix_waits_for_expected_derived_contract,
    test_webbed_fixture_requires_canonical_safe_pair_placement,
    test_webbed_fixture_pins_selected_spider_target_until_contact,
    test_webbed_status_replicates_stock_state_to_remote_presentation,
    test_world_stale_hold_controls_the_exact_remote_host_process,
)
from static_multiplayer_vitals_contracts import (
    test_client_owned_magic_shield_consumption_is_host_authoritative,
)
from static_re_primary_combat_contracts import (
    test_active_cast_movement_clears_stale_vector_before_stock_tick,
    test_bot_cast_admission_refreshes_live_mana_before_queue,
    test_bot_mana_reserve_uses_hysteresis_for_casting,
    test_bot_mana_spend_is_stock_owned_through_native_gate_patch,
    test_bot_out_of_mana_probe_checks_pre_execution_rejection,
    test_boulder_held_charge_tracks_live_target_until_release,
    test_boulder_live_retarget_probe_is_documented,
    test_boulder_projection_is_read_only_native_formula,
    test_earth_boulder_damage_uses_native_live_spell_stats,
    test_gameplay_selection_writes_do_not_corrupt_stock_run_placement_vector,
    test_held_primary_mana_uses_native_spend_scale_and_start_rate,
    test_lua_earth_retargeting_uses_live_boulder_impact_anchor,
    test_primary_build_skill_mapping_has_single_runtime_owner,
    test_primary_mana_resolver_uses_native_live_spell_stats,
)
from static_re_multiplayer_combat_contracts import (
    test_bot_element_damage_probe_supports_upgraded_primary_victim_validation,
    test_bot_equip_materialization_stays_scoped_to_bot_creation,
    test_bot_level_sync_uses_native_level_up,
    test_bot_skill_upgrade_combat_probe_checks_native_damage_and_mana,
    test_bot_upgrade_damage_delta_probe_checks_native_mana_projection_and_release_policy,
    test_hub_start_testrun_uses_gameplay_region_switch,
    test_hub_start_testrun_waits_for_app_tick_pump,
    test_lightning_chaining_verifier_uses_native_dispatcher_loop,
    test_native_primary_output_layout_is_stat_ordered,
    test_native_stat_refresh_preserves_live_vitals,
    test_primary_attack_window_uses_live_native_selection_range,
    test_primary_kill_stress_verifier_uses_manual_spawns_without_waves,
    test_primary_kill_stress_verifier_uses_native_hub_start,
    test_primary_mana_resolver_accepts_native_dispatcher_entry_ids,
    test_primary_selection_mapping_is_native_backed_not_static_table,
    test_replicated_manual_run_enemy_materialization_is_client_bounded,
    test_unverified_play_boneyard_shortcut_is_not_exposed,
)
from static_re_native_actor_contracts import (
    test_bot_movement_speed_uses_native_live_envelope,
    test_default_ally_hp_native_constructor_evidence_is_recorded,
    test_default_ally_hp_spawn_paths_preserve_native_defaults,
    test_enemy_spawn_scaling_native_wave_seam_is_documented,
    test_participant_transform_updates_preserve_exact_hub_sync,
    test_pathfinding_movement_layout_is_named_and_documented,
    test_player_gamenpc_movement_seed_layout_is_named_and_documented,
    test_synthetic_source_profile_blocker_is_documented,
)
from static_re_native_movement_contracts import (
    test_accepted_native_shims_are_documented,
    test_active_sources_reject_read_or_and_stale_path_language,
    test_cast_state_native_contracts_are_documented_and_layout_backed,
    test_hot_path_diagnostics_are_default_off_and_gated,
    test_lua_bot_constants_are_semantic_or_documented,
    test_participant_collision_resolver_is_documented_and_live_probed,
    test_remaining_active_hardcode_sources_are_removed,
    test_smell_source_inventory_is_current,
)
from static_re_transport_core_contracts import (
    test_all_stock_potion_subtypes_replicate_as_native_pickups,
    test_client_gold_pickup_replays_stock_feedback_once_after_authority_accepts,
    test_client_non_gold_pickups_replay_stock_feedback_once_after_authority_accepts,
    test_misc_ground_items_replicate_without_recipe_identity,
    test_local_multiplayer_udp_transport_is_wired,
)
from static_re_steam_contracts import (
    test_manual_enemy_test_mode_logging_is_transition_only,
    test_packet_send_mode_dispatch_is_type_safe,
    test_player_state_exports_native_heading_for_bot_spawn,
    test_solomon_dark_steam_app_id_is_consistent,
    test_steam_friend_hub_lifecycle_soak_is_wired,
    test_steam_friend_multiplayer_contract_is_wired,
    test_steam_pair_driver_rejects_ended_runs_before_client_navigation,
    test_wsl_lua_bridge_bootstraps_from_clean_worktree,
    test_world_snapshots_are_complete_mtu_sized_generations,
)
from static_re_wsl_steam_stability_contracts import (
    test_wsl_steam_runtime_uses_the_stable_proton_generation,
)
from static_re_inventory_container_contracts import (
    test_nested_sack_inventory_preserves_owner_authored_container_paths,
)
from static_re_hagatha_perk_contracts import (
    test_cheat_death_health_increase_is_captured_as_authoritative_damage,
    test_hagatha_client_damage_ratio_allows_one_claim_quantum,
    test_hagatha_combat_modifiers_have_exact_two_owner_coverage,
    test_hagatha_derived_stats_have_a_two_owner_steam_matrix,
    test_hagatha_one_shot_runtime_state_is_host_authoritative,
    test_hagatha_perks_replicate_as_participant_owned_native_state,
    test_native_hagatha_perk_catalog_is_complete,
)
from static_re_runtime_cast_contracts import (
    test_earth_live_verifier_requires_native_boulder_visual_emission,
    test_earth_primary_is_captured_from_its_native_dispatcher,
    test_memory_region_cache_refreshes_newly_committed_native_objects,
    test_multiplayer_nameplates_render_from_native_scene_passes,
    test_player_control_brain_requires_published_gameplay_slot,
    test_primary_cast_lane_requires_native_collision_segment,
    test_queued_mouse_holds_use_player_tick_duration,
    test_remote_held_input_casts_defer_lifecycle_to_sender_input,
    test_remote_per_cast_primary_settles_without_waiting_for_release,
    test_local_primary_network_capture_is_single_owner_and_preserves_lua_events,
    test_water_continuous_primary_is_captured_from_its_native_dispatcher,
    test_water_live_verifier_requires_native_visual_emission,
    test_write_watch_rearm_is_owned_by_faulting_thread,
    test_write_watches_are_transparent_to_loader_memory_access,
)
from static_re_runtime_platform_contracts import (
    test_client_run_switch_requires_fresh_authenticated_host_intent,
    test_launcher_saves_are_isolated_link_gated_and_proton_persisted,
    test_remote_progression_preserves_local_concentration_context,
    test_remote_progression_uses_passive_authoritative_hydration,
    test_steam_combat_stat_profiles_isolate_concentration,
    test_steam_peer_disconnect_resets_remote_session_epoch,
    test_steam_spell_behavior_verifiers_use_real_upgrades_and_wait_for_delivery,
    test_wine_stage_savegames_uses_directory_mirror,
    test_wsl_steam_launcher_applies_test_boneyard_before_process_start,
    test_wsl_steam_launcher_isolates_build_artifacts_from_live_host,
)
from static_re_runtime_behavior_contracts import (
    test_debug_ui_frame_render_does_not_log_each_snapshot_generation,
    test_main_thread_work_pump_is_not_render_owned,
    test_mindstar_semantic_spell_projection_ignores_raw_storage_tail,
    test_steam_io_is_service_thread_owned_and_gameplay_application_is_app_thread_owned,
    test_participant_native_state_is_owned_by_current_scene,
    test_regenerate_behavior_traces_stock_native_heal_updates,
    test_semantic_air_damage_quantum_uses_authoritative_total,
    test_semantic_ui_actions_dispatch_only_on_app_update_thread,
    test_steam_rush_reuses_strict_prepared_matrix,
)
from static_re_binary_tooling_contracts import (
    test_autonomous_probe_uses_bot_scoped_diagnostics_and_native_damage_evidence,
    test_binary_layout_matches_staged_layout_identity,
    test_crash_reports_preserve_faulting_x86_frame_chain,
    test_investigation_register_has_static_coverage,
    test_lua_follow_preserves_timeout_teleport,
    test_multiplayer_launch_preflights_steam_before_starting_game,
    test_native_derived_wizard_visuals_are_layout_backed,
    test_native_global_reads_do_not_use_loader_substitutes,
    test_path_builder_does_not_walk_to_unrequested_alternate_goals,
    test_path_builder_expands_cells_before_los_smoothing,
    test_process_termination_skips_loader_shutdown,
    test_remaining_native_addresses_and_probe_offsets_are_layout_backed,
    test_repo_wide_native_reads_do_not_publish_substitute_state,
    test_residual_probe_and_skill_choice_offsets_are_layout_backed,
    test_runtime_debug_trace_rejects_overlapping_detours_and_untraces_rebased_addresses,
    test_second_residual_runtime_and_trace_addresses_are_layout_backed,
    test_stage_mirror_publishes_and_verifies_file_contents,
    test_stage_mirror_repairs_denied_destination_acl,
    test_staged_binary_matches_analysis_binary,
    test_standalone_animation_drive_applies_dynamic_fields,
)

TESTS: list[tuple[str, Callable[[], str]]] = [
    (
        "Lua run seed is authority-owned and native-applied",
        test_lua_run_seed_is_authority_owned_and_native_applied,
    ),
    (
        "Lua navigation is bounded, read-only, and native-backed",
        test_lua_nav_is_bounded_read_only_and_native_backed,
    ),
    (
        "Lua scene control is semantic, authority-owned, and peer-followed",
        test_lua_scene_is_address_free_authority_owned_and_peer_followed,
    ),
    (
        "Lua wave intelligence is parsed, tracked, and authority-replicated",
        test_lua_waves_parse_track_and_replicate_semantic_summaries,
    ),
    (
        "Lua bus is manifest-resolved, bounded, and local",
        test_lua_bus_is_manifest_resolved_bounded_and_local,
    ),
    (
        "Lua net is fragmented, authenticated, and host-relayed",
        test_lua_net_is_fragmented_authenticated_and_host_relayed,
    ),
    (
        "Lua time is authority-owned, replicated, and coherently gated",
        test_lua_time_is_authority_owned_replicated_and_coherently_gated,
    ),
    (
        "Lua content IDs are canonical, deterministic, and load-scoped",
        test_lua_content_ids_are_canonical_deterministic_and_load_scoped,
    ),
    (
        "Lua items register stable identity and resolve peer-local recipes",
        test_lua_items_register_stable_identity_and_resolve_peer_local_recipes,
    ),
    (
        "Lua enemies use exact stock spawning and replicated content identity",
        test_lua_enemies_use_exact_stock_spawn_and_replicated_content_identity,
    ),
    (
        "Lua spells register stable metadata and owned callbacks",
        test_lua_spells_register_stable_metadata_and_owned_callbacks,
    ),
    (
        "Lua enemy AI is bounded, authority-owned, and collision-preserving",
        test_lua_enemy_ai_is_bounded_authority_owned_and_collision_preserving,
    ),
    (
        "Lua audio is scoped, bounded, local, and game-owned",
        test_lua_audio_is_scoped_bounded_local_and_game_owned,
    ),
    (
        "Lua camera is native, bounded, owned, and presentation-local",
        test_lua_camera_is_native_bounded_owned_and_presentation_local,
    ),
    (
        "Lua UI authoring is native, bounded, and authority-routed",
        test_lua_ui_authoring_is_native_bounded_and_authority_routed,
    ),
    (
        "Lua timers are bounded, local, and tick-driven",
        test_lua_timers_are_bounded_local_and_tick_driven,
    ),
    (
        "Lua storage is scoped, bounded, and transactional",
        test_lua_storage_is_scoped_bounded_and_transactional,
    ),
    (
        "Lua resource filters are native-ordered and authoritative",
        test_lua_resource_filters_are_native_ordered_and_authoritative,
    ),
    (
        "Lua spell filters are owner-side and once per attempt",
        test_lua_spell_filter_is_owner_side_precast_and_once_per_attempt,
    ),
    (
        "Lua enemy-spawn filter preserves stock call shape and ownership",
        test_lua_enemy_spawn_filter_preserves_stock_call_shape_and_ownership,
    ),
    (
        "Lua drop-roll filters are owner-side, transactional, and stock-preserving",
        test_lua_drop_roll_filters_are_owner_side_transactional_and_stock_preserving,
    ),
    (
        "Lua wave-spawn filters are owner-side, transactional, and stock-preserving",
        test_lua_wave_spawn_filters_are_owner_side_transactional_and_stock_preserving,
    ),
    (
        "Lua damage filters are ordered, owner-side, and transactional",
        test_lua_damage_filters_are_ordered_owner_side_and_transactional,
    ),
    (
        "Lua draw is bounded, local, and backbuffer-verified",
        test_lua_draw_is_bounded_local_and_backbuffer_verified,
    ),
    (
        "Lua sprites are owned, bounded, sandboxed, and revisioned",
        test_lua_sprites_are_owned_bounded_sandboxed_and_revisioned,
    ),
    (
        "Lua authoring is generated, reloadable, and safe-thread executed",
        test_lua_authoring_is_generated_reloadable_and_safe_thread_executed,
    ),
    (
        "Lua seam roadmap is closed under exact mod parity",
        test_lua_roadmap_is_closed_under_exact_mod_parity,
    ),
    (
        "Lua mod state and events are authority-replicated",
        test_lua_mod_state_and_events_are_authority_replicated,
    ),
    (
        "flat Boneyard fixture matches the native SyncBuffer envelope",
        test_flat_boneyard_fixture_matches_native_syncbuffer_envelope,
    ),
    (
        "Boneyard parser rejects malformed native containers",
        test_boneyard_parser_rejects_empty_truncated_and_trailing_files,
    ),
    (
        "Multiplayer Boneyard scenery shares the host generation boundary",
        test_multiplayer_boneyard_scenery_shares_the_host_generation_boundary,
    ),
    (
        "Repository history uses approved project identities",
        test_repository_history_uses_approved_identities,
    ),
    (
        "App-thread transport verifier tracks the named cadence gap",
        test_app_thread_transport_verifier_tracks_named_cadence_gap,
    ),
    (
        "Hub service fragments are Visual Studio project items",
        test_hub_service_fragments_are_visual_studio_project_items,
    ),
    (
        "Native project uses repository-local Lua sources",
        test_native_project_uses_repo_local_lua_sources,
    ),
    (
        "Build-All cleans native intermediates across toolsets",
        test_build_all_rebuilds_native_loader_from_clean_intermediates,
    ),
    (
        "Lua exec timeouts cancel pending gameplay mutations",
        test_lua_exec_timeout_cancels_pending_work,
    ),
    (
        "remote Windows Lua uses a bounded persistent framed bridge",
        test_remote_windows_lua_bridge_is_persistent_and_framed,
    ),
    (
        "active-pair visual capture routes by pair backend",
        test_active_pair_visual_capture_routes_by_pair_backend,
    ),
    (
        "unreliable multiplayer snapshots reject stale visual state",
        test_unreliable_snapshot_ordering_is_wrap_safe,
    ),
    (
        "snapshot streams are compact and bandwidth bounded",
        test_snapshot_streams_are_compact_and_bandwidth_bounded,
    ),
    (
        "empty run snapshots unregister stale enemies without parking",
        test_empty_run_snapshot_unregisters_stale_enemies_without_parking,
    ),
    (
        "run-enemy death tombstones precede structural omission",
        test_run_enemy_death_tombstones_precede_structural_omission,
    ),
    (
        "Steam pairs recover lobby membership and require stable readiness",
        test_steam_pair_recovers_lobby_membership_and_requires_stable_readiness,
    ),
    (
        "Steam client reauthentication preserves the live message session",
        test_steam_client_reauthentication_preserves_live_message_session,
    ),
    (
        "poison correction acknowledgements wait for native application",
        test_transient_status_correction_ack_waits_for_native_application,
    ),
    (
        "accepted remote item pickups converge into native inventory",
        test_native_item_pickup_converges_into_stock_inventory,
    ),
    (
        "loot removal uses stock deferred retirement",
        test_loot_deactivation_uses_stock_deferred_retirement,
    ),
    (
        "client loot pickup requests stay single-flight per drop",
        test_client_loot_pickup_requests_are_single_flight_per_drop,
    ),
    (
        "native unregister retires address-bound network identity",
        test_native_unregister_retires_address_bound_network_identity,
    ),
    (
        "stock powerups remain host-authoritative and native",
        test_powerup_rewards_are_authoritative_and_native,
    ),
    (
        "exact native equipment identity and color replicate",
        test_exact_native_equipment_identity_and_color_replicate,
    ),
    (
        "hub services use typed native Lua dispatch",
        test_hub_services_use_typed_native_lua_dispatch,
    ),
    (
        "explicit blank Boneyard removes native scenery and collision",
        test_explicit_blank_boneyard_removes_native_scenery_and_collision,
    ),
    (
        "native local player keeps stock input and equipment ownership",
        test_native_local_player_keeps_stock_input_and_equipment_ownership,
    ),
    (
        "host run exit is authoritative and self-correcting",
        test_host_run_exit_is_authoritative_and_self_correcting,
    ),
    (
        "pair launcher drains redirected JSON output",
        test_pair_launcher_drains_redirected_json_output,
    ),
    (
        "UI sandbox retries unlatched create choices",
        test_ui_sandbox_retries_unlatched_create_choices,
    ),
    (
        "packaged desktop UI uses its Proton-compatible launcher",
        test_packaged_ui_uses_proton_compatible_launcher,
    ),
    (
        "beta release documents its Steam Deck shortcut",
        test_beta_release_documents_steam_deck_shortcut,
    ),
    (
        "Proton contract runner avoids the GE11 UMU shim hang",
        test_proton_contract_runner_avoids_ge11_umu_shim_hang,
    ),
    (
        "beta package smoke canonicalizes Windows path aliases",
        test_beta_release_smoke_canonicalizes_packaged_steam_path,
    ),
    (
        "packaged desktop UI strips test-only world overrides",
        test_packaged_ui_does_not_inherit_test_world_overrides,
    ),
    (
        "launcher auto-accepts Steam invites and hub-gates discovery",
        test_launcher_auto_accepts_steam_invites_and_hub_gates_discovery,
    ),
    (
        "website lobby links register and route to the launcher",
        test_website_lobby_links_register_and_route_to_launcher,
    ),
    (
        "progression matrices prearm quiet spawning before run entry",
        test_progression_matrices_prearm_quiet_spawning_before_run_entry,
    ),
    (
        "active Steam behavior harnesses preserve fixture state",
        test_active_steam_behavior_harnesses_preserve_fixture_state,
    ),
    (
        "native defense probes follow host damage authority",
        test_defense_probes_follow_host_damage_authority,
    ),
    (
        "staff target selection skips local-only enemies",
        test_staff_target_selection_skips_local_only_enemies,
    ),
    (
        "frozen manual enemy cells stay position-coherent",
        test_frozen_manual_enemy_cell_membership_stays_position_coherent,
    ),
    (
        "Steam onboarding waits out blocking dialogs and scene churn",
        test_steam_onboarding_waits_out_blocking_dialogs_and_scene_churn,
    ),
    (
        "manual primary targets survive stock cursor refresh",
        test_manual_primary_target_survives_stock_cursor_refresh,
    ),
    (
        "new runs retire the prior host run-exit latch",
        test_new_run_retires_the_prior_host_run_exit_latch,
    ),
    (
        "secondary behavior matrix uses native two-owner witnesses",
        test_secondary_behavior_matrix_uses_native_two_owner_witnesses,
    ),
    (
        "secondary matrix drives targeted stock cursor geometry",
        test_secondary_matrix_drives_targeted_stock_cursor_geometry,
    ),
    (
        "secondary matrix isolates prior native effect lifetimes",
        test_secondary_matrix_isolates_prior_native_effect_lifetimes,
    ),
    (
        "Magic Trap lifetime follows its cast owner",
        test_magic_trap_lifetime_follows_cast_owner,
    ),
    (
        "secondary replay preserves owner-authored aim",
        test_secondary_replay_preserves_owner_authored_aim_when_target_resolves,
    ),
    (
        "cursor-placed secondaries replay owner world position",
        test_cursor_placed_secondaries_replay_owner_world_position,
    ),
    (
        "webbed stock state drives remote actor presentation",
        test_webbed_status_replicates_stock_state_to_remote_presentation,
    ),
    (
        "Webbed fixture pins the selected Spider target until contact",
        test_webbed_fixture_pins_selected_spider_target_until_contact,
    ),
    (
        "Webbed fixture requires canonical safe pair placement",
        test_webbed_fixture_requires_canonical_safe_pair_placement,
    ),
    (
        "remote Webbed escape consumes owner movement intent",
        test_remote_webbed_escape_consumes_owner_movement_intent,
    ),
    (
        "network clients reject stock incoming damage authority",
        test_network_clients_reject_stock_incoming_damage_authority,
    ),
    (
        "client-owned Magic Shield consumption is host authoritative",
        test_client_owned_magic_shield_consumption_is_host_authoritative,
    ),
    (
        "spell verifiers quiesce input and prearm manual spawning",
        test_spell_verifiers_quiesce_input_and_prearm_manual_spawning,
    ),
    (
        "Meditation transient counters self-repair to native bounds",
        test_meditation_transient_counters_self_repair_to_native_bounds,
    ),
    (
        "mana recovery tolerance respects native float precision",
        test_mana_recovery_tolerance_respects_float32_precision,
    ),
    (
        "HEALTH UP contract composes with Life Charm",
        test_health_up_contract_composes_with_life_charm,
    ),
    (
        "MANA UP contract replaces inherited rank bonuses",
        test_mana_up_contract_replaces_the_initial_rank_bonus,
    ),
    (
        "world stale hold controls the exact remote host process",
        test_world_stale_hold_controls_the_exact_remote_host_process,
    ),
    (
        "hub presentation uses stored authority across lifecycle rotation",
        test_hub_presentation_uses_stored_authority_across_lifecycle_rotation,
    ),
    (
        "natural offer expectations clamp to native maxima",
        test_natural_offer_expectation_clamps_to_native_maximum,
    ),
    (
        "stat matrix waits for the expected derived contract",
        test_stat_matrix_waits_for_expected_derived_contract,
    ),
    (
        "mana recovery holds its zero precondition until replication",
        test_mana_recovery_precondition_holds_zero_until_replication,
    ),
    (
        "reconnect verifier separates cold launch and gameplay timeouts",
        test_reconnect_verifier_has_a_dedicated_cold_launch_timeout,
    ),
    (
        "loot materialization waits for native field convergence",
        test_loot_materialization_waits_for_native_field_convergence,
    ),
    (
        "primary kill stress resumes only a contiguous passed prefix",
        test_primary_kill_stress_resumes_only_a_contiguous_passed_prefix,
    ),
    (
        "primary kill stress attributes late death to the prior cast",
        test_primary_kill_stress_accepts_a_late_death_from_the_prior_cast,
    ),
    (
        "primary kill stress requires native death evidence at epsilon HP",
        test_primary_kill_stress_requires_native_death_evidence_at_epsilon_hp,
    ),
    (
        "run reentry audits only logs written during the test",
        test_run_reentry_audits_only_logs_written_during_the_test,
    ),
    (
        "beta artifact verifier reads bounded ZIP headers",
        test_beta_artifact_verifier_reads_bounded_zip_headers,
    ),
    (
        "beta package smoke forwards a valid website lobby URI",
        test_beta_package_smoke_forwards_a_valid_website_lobby_uri,
    ),
    (
        "animated loot bounds transport-phase position skew",
        test_animated_loot_comparison_bounds_snapshot_phase_skew,
    ),
    (
        "level-up barrier waits for forced picker confirmation",
        test_level_up_barrier_waits_for_forced_picker_confirmation,
    ),
    (
        "level-up choice results advance owned books before resume",
        test_level_up_choice_result_advances_owned_book_before_resume,
    ),
    (
        "pointer-list batches reject stale managed release callbacks",
        test_pointer_list_batch_rejects_stale_managed_release_callbacks,
    ),
    (
        "CPU ticks stop after virtual updates mark objects for removal",
        test_cpu_tick_stops_after_virtual_update_marks_object_for_removal,
    ),
    (
        "active Steam reconnect starts a clean owned-state epoch",
        test_steam_friend_active_run_reconnect_is_wired,
    ),
    (
        "orb pickup verifier preserves native resource maxima",
        test_orb_pickup_verifier_preserves_native_maxima,
    ),
    (
        "primary spell-effect snapshots do not fight native replay",
        test_primary_spell_effect_snapshots_do_not_fight_native_replay,
    ),
    (
        "native remote Fireball heading conversion is scoped to stock Fire",
        test_native_remote_fireball_conversion_is_scoped_to_stock_fire,
    ),
    (
        "native remote Fireball converts cast heading until projectile birth",
        test_native_remote_fireball_converts_cast_heading_until_projectile_birth,
    ),
    (
        "manual Lightning cluster stays inside flat-arena spatial grid",
        test_lightning_manual_cluster_stays_inside_flat_arena_spatial_grid,
    ),
    (
        "Boneyard generator skips empty candidate interpolation",
        test_boneyard_generator_skips_empty_candidate_interpolation,
    ),
    (
        "native item recipe selection includes equipped ownership",
        test_native_item_recipe_selection_excludes_equipped_items,
    ),
    ("primary mana resolver uses native live spell stats", test_primary_mana_resolver_uses_native_live_spell_stats),
    ("Earth boulder damage uses native live spell stats", test_earth_boulder_damage_uses_native_live_spell_stats),
    ("Earth boulder projection stays read-only and drives target-lethal release", test_boulder_projection_is_read_only_native_formula),
    ("Earth boulder held charge tracks live target until release", test_boulder_held_charge_tracks_live_target_until_release),
    ("Earth boulder live retarget probe is documented", test_boulder_live_retarget_probe_is_documented),
    ("Lua Earth retargeting uses live Boulder impact anchor", test_lua_earth_retargeting_uses_live_boulder_impact_anchor),
    ("Active-cast movement clears stale vector before stock tick", test_active_cast_movement_clears_stale_vector_before_stock_tick),
    (
        "bot mana spend is stock-owned through native gate patch",
        test_bot_mana_spend_is_stock_owned_through_native_gate_patch,
    ),
    ("bot cast admission refreshes live mana before queue", test_bot_cast_admission_refreshes_live_mana_before_queue),
    ("bot mana reserve uses native hysteresis", test_bot_mana_reserve_uses_hysteresis_for_casting),
    ("bot out-of-mana probe checks pre-execution rejection", test_bot_out_of_mana_probe_checks_pre_execution_rejection),
    ("held primary mana uses native spend scale and start rate", test_held_primary_mana_uses_native_spend_scale_and_start_rate),
    ("remote per-cast primary settles without waiting for release", test_remote_per_cast_primary_settles_without_waiting_for_release),
    ("queued mouse holds use player-tick duration", test_queued_mouse_holds_use_player_tick_duration),
    ("remote held input casts defer lifecycle to sender input", test_remote_held_input_casts_defer_lifecycle_to_sender_input),
    (
        "local primary network capture is single-owner and preserves Lua events",
        test_local_primary_network_capture_is_single_owner_and_preserves_lua_events,
    ),
    (
        "Water continuous primary is captured from its native dispatcher",
        test_water_continuous_primary_is_captured_from_its_native_dispatcher,
    ),
    (
        "Water live verifier requires native visual emission",
        test_water_live_verifier_requires_native_visual_emission,
    ),
    (
        "Earth primary is captured from its native dispatcher",
        test_earth_primary_is_captured_from_its_native_dispatcher,
    ),
    (
        "Earth live verifier requires native Boulder visual emission",
        test_earth_live_verifier_requires_native_boulder_visual_emission,
    ),
    ("multiplayer nameplates render through native scene passes", test_multiplayer_nameplates_render_from_native_scene_passes),
    ("primary build skill mapping has single runtime owner", test_primary_build_skill_mapping_has_single_runtime_owner),
    ("gameplay selection writes preserve stock run-placement vector", test_gameplay_selection_writes_do_not_corrupt_stock_run_placement_vector),
    ("primary kill stress verifier uses manual spawns without waves", test_primary_kill_stress_verifier_uses_manual_spawns_without_waves),
    ("bot equip materialization stays scoped to bot creation", test_bot_equip_materialization_stays_scoped_to_bot_creation),
    (
        "memory-region cache refreshes newly committed native objects",
        test_memory_region_cache_refreshes_newly_committed_native_objects,
    ),
    (
        "write watches remain transparent to loader memory access",
        test_write_watches_are_transparent_to_loader_memory_access,
    ),
    (
        "write-watch rearm is owned by the faulting thread",
        test_write_watch_rearm_is_owned_by_faulting_thread,
    ),
    (
        "primary-cast lanes require native collision-segment clearance",
        test_primary_cast_lane_requires_native_collision_segment,
    ),
    (
        "player control-brain requires a published gameplay slot",
        test_player_control_brain_requires_published_gameplay_slot,
    ),
    (
        "client run switch requires fresh authenticated host intent",
        test_client_run_switch_requires_fresh_authenticated_host_intent,
    ),
    (
        "Wine stage savegames uses a directory mirror",
        test_wine_stage_savegames_uses_directory_mirror,
    ),
    (
        "launcher saves are isolated, link-gated, and Proton-persisted",
        test_launcher_saves_are_isolated_link_gated_and_proton_persisted,
    ),
    (
        "WSL Steam stages the test Boneyard before Proton starts",
        test_wsl_steam_launcher_applies_test_boneyard_before_process_start,
    ),
    (
        "remote progression preserves local Concentrate context",
        test_remote_progression_preserves_local_concentration_context,
    ),
    (
        "remote progression hydrates authoritative ranks after native no-op",
        test_remote_progression_uses_passive_authoritative_hydration,
    ),
    (
        "Steam peer disconnect resets participant replication epoch",
        test_steam_peer_disconnect_resets_remote_session_epoch,
    ),
    (
        "process termination skips loader-lock Steam shutdown",
        test_process_termination_skips_loader_shutdown,
    ),
    (
        "crash reports preserve the faulting x86 frame chain",
        test_crash_reports_preserve_faulting_x86_frame_chain,
    ),
    (
        "stage mirror repairs denied destination ACLs",
        test_stage_mirror_repairs_denied_destination_acl,
    ),
    (
        "stage mirror atomically publishes and verifies file contents",
        test_stage_mirror_publishes_and_verifies_file_contents,
    ),
    (
        "multiplayer launch validates Steam before starting the game",
        test_multiplayer_launch_preflights_steam_before_starting_game,
    ),
    (
        "Steam spell behavior verification uses real upgrades and delivery waits",
        test_steam_spell_behavior_verifiers_use_real_upgrades_and_wait_for_delivery,
    ),
    (
        "Steam combat-stat profiles isolate concentration-sensitive behavior",
        test_steam_combat_stat_profiles_isolate_concentration,
    ),
    (
        "semantic Air damage quantum uses authoritative HP loss",
        test_semantic_air_damage_quantum_uses_authoritative_total,
    ),
    (
        "Mindstar spell parity ignores only grow-only native output tails",
        test_mindstar_semantic_spell_projection_ignores_raw_storage_tail,
    ),
    (
        "Regenerate behavior traces stock native heal updates",
        test_regenerate_behavior_traces_stock_native_heal_updates,
    ),
    (
        "Steam Rush reuses the strict prepared behavior matrix",
        test_steam_rush_reuses_strict_prepared_matrix,
    ),
    (
        "Semantic UI actions dispatch only on the app update thread",
        test_semantic_ui_actions_dispatch_only_on_app_update_thread,
    ),
    (
        "Debug UI frame rendering does not log each snapshot generation",
        test_debug_ui_frame_render_does_not_log_each_snapshot_generation,
    ),
    (
        "Main-thread work pump is not render-owned",
        test_main_thread_work_pump_is_not_render_owned,
    ),
    (
        "Steam I/O is service-thread owned and gameplay application is app-thread owned",
        test_steam_io_is_service_thread_owned_and_gameplay_application_is_app_thread_owned,
    ),
    (
        "Participant native state is owned by the current scene",
        test_participant_native_state_is_owned_by_current_scene,
    ),
    ("hub start testrun uses gameplay region switch", test_hub_start_testrun_uses_gameplay_region_switch),
    ("hub start testrun waits for app-tick pump", test_hub_start_testrun_waits_for_app_tick_pump),
    ("primary kill stress verifier uses native hub start", test_primary_kill_stress_verifier_uses_native_hub_start),
    ("unverified play boneyard shortcut is not exposed", test_unverified_play_boneyard_shortcut_is_not_exposed),
    ("replicated manual run enemy materialization is client bounded", test_replicated_manual_run_enemy_materialization_is_client_bounded),
    ("primary mana resolver accepts native dispatcher entry ids", test_primary_mana_resolver_accepts_native_dispatcher_entry_ids),
    ("native primary output layout follows Skills_Wizard stat order", test_native_primary_output_layout_is_stat_ordered),
    ("Lightning Chaining verifier uses native dispatcher loop", test_lightning_chaining_verifier_uses_native_dispatcher_loop),
    ("primary selection mapping is native-backed", test_primary_selection_mapping_is_native_backed_not_static_table),
    ("primary attack window uses live native selection range", test_primary_attack_window_uses_live_native_selection_range),
    ("bot level sync uses native level_up", test_bot_level_sync_uses_native_level_up),
    ("native stat refresh preserves live vitals", test_native_stat_refresh_preserves_live_vitals),
    ("bot skill-upgrade combat probe checks native damage and mana", test_bot_skill_upgrade_combat_probe_checks_native_damage_and_mana),
    ("bot element damage probe supports upgraded primary victim validation", test_bot_element_damage_probe_supports_upgraded_primary_victim_validation),
    ("bot upgrade damage delta probe checks native mana, projection, and release policy", test_bot_upgrade_damage_delta_probe_checks_native_mana_projection_and_release_policy),
    ("Synthetic source-profile native blocker is documented", test_synthetic_source_profile_blocker_is_documented),
    ("Default ally HP native constructor evidence is recorded", test_default_ally_hp_native_constructor_evidence_is_recorded),
    ("Default ally HP spawn paths preserve native defaults", test_default_ally_hp_spawn_paths_preserve_native_defaults),
    ("Participant transform updates preserve exact hub sync", test_participant_transform_updates_preserve_exact_hub_sync),
    ("Enemy spawn scaling native wave seam is documented", test_enemy_spawn_scaling_native_wave_seam_is_documented),
    ("Pathfinding movement layout is named and documented", test_pathfinding_movement_layout_is_named_and_documented),
    ("Player/GameNpc movement seed layout is named and documented", test_player_gamenpc_movement_seed_layout_is_named_and_documented),
    ("Bot movement speed uses native live envelope", test_bot_movement_speed_uses_native_live_envelope),
    ("Participant collision resolver is documented and live-probed", test_participant_collision_resolver_is_documented_and_live_probed),
    ("Cast-state native contracts are documented and layout-backed", test_cast_state_native_contracts_are_documented_and_layout_backed),
    ("Lua bot constants are semantic or documented", test_lua_bot_constants_are_semantic_or_documented),
    ("remaining active hardcode sources are removed", test_remaining_active_hardcode_sources_are_removed),
    ("smell source inventory is current", test_smell_source_inventory_is_current),
    ("active sources reject substitute read APIs and stale path language", test_active_sources_reject_read_or_and_stale_path_language),
    ("accepted native shims are documented", test_accepted_native_shims_are_documented),
    ("hot-path diagnostics are default-off and gated", test_hot_path_diagnostics_are_default_off_and_gated),
    (
        "accepted client gold pickups replay stock feedback exactly once",
        test_client_gold_pickup_replays_stock_feedback_once_after_authority_accepts,
    ),
    (
        "accepted client non-gold pickups replay stock feedback exactly once",
        test_client_non_gold_pickups_replay_stock_feedback_once_after_authority_accepts,
    ),
    (
        "all stock potion subtypes replicate as native pickups",
        test_all_stock_potion_subtypes_replicate_as_native_pickups,
    ),
    (
        "misc ground items replicate without recipe identity",
        test_misc_ground_items_replicate_without_recipe_identity,
    ),
    ("local multiplayer UDP transport is wired", test_local_multiplayer_udp_transport_is_wired),
    (
        "world snapshots are complete MTU-sized generations",
        test_world_snapshots_are_complete_mtu_sized_generations,
    ),
    (
        "run enemy materialization preserves exact native type",
        test_run_enemy_materialization_preserves_exact_native_type,
    ),
    (
        "exact spawn retires an invalid featured enemy",
        test_exact_spawn_retires_invalid_featured_enemy,
    ),
    (
        "client enemy hot path uses constant-time authority lookup",
        test_client_enemy_hot_path_uses_constant_time_authority_cache,
    ),
    (
        "hub Students remain in the stock transient lifecycle",
        test_hub_students_remain_in_the_stock_transient_lifecycle,
    ),
    (
        "client replicated enemy movement remains host-authored",
        test_client_replicated_enemy_movement_is_host_authored,
    ),
    (
        "scene ticks keep dead remote participants inert",
        test_scene_tick_keeps_dead_remote_participants_inert,
    ),
    (
        "packet send-mode dispatch is type-safe",
        test_packet_send_mode_dispatch_is_type_safe,
    ),
    (
        "Steam pair driver refuses ended runs before client navigation",
        test_steam_pair_driver_rejects_ended_runs_before_client_navigation,
    ),
    (
        "manual enemy test mode logs only state transitions",
        test_manual_enemy_test_mode_logging_is_transition_only,
    ),
    ("Steam friend multiplayer contract is wired", test_steam_friend_multiplayer_contract_is_wired),
    (
        "WSL Lua bridge bootstraps from a clean worktree",
        test_wsl_lua_bridge_bootstraps_from_clean_worktree,
    ),
    (
        "WSL Steam runtime uses the stable Proton generation",
        test_wsl_steam_runtime_uses_the_stable_proton_generation,
    ),
    (
        "Nested sack inventory preserves owner-authored container paths",
        test_nested_sack_inventory_preserves_owner_authored_container_paths,
    ),
    (
        "Native Hagatha perk catalog is complete",
        test_native_hagatha_perk_catalog_is_complete,
    ),
    (
        "Hagatha perks replicate as participant-owned native state",
        test_hagatha_perks_replicate_as_participant_owned_native_state,
    ),
    (
        "Hagatha one-shot runtime state is host-authoritative",
        test_hagatha_one_shot_runtime_state_is_host_authoritative,
    ),
    (
        "Hagatha derived stats have a two-owner Steam matrix",
        test_hagatha_derived_stats_have_a_two_owner_steam_matrix,
    ),
    (
        "Cheat Death HP recovery is captured as authoritative damage",
        test_cheat_death_health_increase_is_captured_as_authoritative_damage,
    ),
    (
        "Hagatha combat modifiers have exact two-owner coverage",
        test_hagatha_combat_modifiers_have_exact_two_owner_coverage,
    ),
    (
        "Hagatha client damage ratios allow one claim quantum",
        test_hagatha_client_damage_ratio_allows_one_claim_quantum,
    ),
    ("Solomon Dark Steam AppID is consistent", test_solomon_dark_steam_app_id_is_consistent),
    (
        "Steam friend hub lifecycle soak is wired",
        test_steam_friend_hub_lifecycle_soak_is_wired,
    ),
    ("player state exports native heading for bot spawn", test_player_state_exports_native_heading_for_bot_spawn),
    (
        "shared menu pause is host-authoritative and time-bounded",
        test_shared_menu_pause_is_host_authoritative_and_time_bounded,
    ),
    ("investigation register has static coverage", test_investigation_register_has_static_coverage),
    ("staged binary matches analysis binary", test_staged_binary_matches_analysis_binary),
    ("binary layout identity is staged", test_binary_layout_matches_staged_layout_identity),
    ("residual probe and skill-choice offsets are layout-backed", test_residual_probe_and_skill_choice_offsets_are_layout_backed),
    ("second residual runtime offsets and trace addresses are layout-backed", test_second_residual_runtime_and_trace_addresses_are_layout_backed),
    ("Remaining native addresses and probe offsets are layout-backed", test_remaining_native_addresses_and_probe_offsets_are_layout_backed),
    ("Runtime debug trace rejects overlapping detours", test_runtime_debug_trace_rejects_overlapping_detours_and_untraces_rebased_addresses),
    ("Autonomous probe uses bot-scoped diagnostics", test_autonomous_probe_uses_bot_scoped_diagnostics_and_native_damage_evidence),
    ("Lua follow preserves timeout teleport", test_lua_follow_preserves_timeout_teleport),
    ("Wizard visuals use native-derived source data", test_native_derived_wizard_visuals_are_layout_backed),
    ("Standalone animation drive applies dynamic fields", test_standalone_animation_drive_applies_dynamic_fields),
    ("Native global reads reject loader substitutes", test_native_global_reads_do_not_use_loader_substitutes),
    ("Repo-wide native reads reject substitute state", test_repo_wide_native_reads_do_not_publish_substitute_state),
    ("Path builder rejects unrequested alternate goals", test_path_builder_does_not_walk_to_unrequested_alternate_goals),
    ("Path builder expands cells before LOS smoothing", test_path_builder_expands_cells_before_los_smoothing),
]
