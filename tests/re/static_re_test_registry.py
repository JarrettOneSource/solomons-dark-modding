"""Canonical registry for all static reverse-engineering contracts."""

from __future__ import annotations

from typing import Callable

from repository_identity_contract import (
    test_identity_contract_cannot_run_against_a_shallow_clone,
    test_repository_history_uses_approved_identities,
)
from static_re_boneyard_contracts import (
    test_boneyard_generator_control_flow_and_output_census_is_complete,
    test_boneyard_parser_rejects_empty_truncated_and_trailing_files,
    test_boneyard_scripting_model_and_runtime_anchors_are_registered,
    test_default_boneyard_load_seed_and_compact_decor_findings_are_registered,
    test_flat_boneyard_fixture_matches_native_syncbuffer_envelope,
    test_loading_screen_uses_native_stage_progress_and_shared_d3d9_lifetime,
    test_multiplayer_boneyard_scenery_shares_the_host_generation_boundary,
    test_solomon_dig_and_wave_director_contract_is_registered,
)
from static_re_boneyard_picker_contracts import (
    test_boneyard_picker_owns_its_keys_and_centers_row_text,
    test_boneyard_picker_presents_mod_description_and_scales_with_viewport,
    test_boneyard_picker_provider_is_immutable_stock_routed_and_stock_transparent,
    test_boneyard_picker_replication_is_authoritative_missing_safe_and_late_joined,
    test_default_boneyard_is_pinned_and_bypasses_the_native_picker,
    test_stock_map_picker_recovery_pins_selected_value_and_launch_path,
)
from static_re_ui_interaction_gate_contracts import (
    test_blocking_overlay_owns_all_gameplay_input_without_deferral,
    test_connected_client_courtyard_start_is_render_and_activation_suppressed,
)
from static_re_native_input_model_contracts import (
    test_native_action_thresholds_absences_and_intent_shape_are_pinned,
    test_native_input_ingress_sampling_and_tick_order_are_pinned,
    test_native_surface_priority_and_loading_input_seal_are_pinned,
)
from static_re_native_session_flow_contracts import (
    test_first_wizard_college_admission_contract_is_pinned,
    test_native_session_flow_input_seal_boundaries_are_pinned,
    test_native_session_flow_legal_edge_set_is_pinned,
    test_native_session_flow_state_enum_is_pinned,
    test_native_session_flow_transition_step_order_is_pinned,
)
from static_re_native_web_combat_lifecycle_contracts import (
    test_native_web_combat_lifecycle_integration_contract_is_pinned,
)
from static_re_native_enemy_damage_presentation_contracts import (
    test_enemy_damage_audio_identity_is_exact,
    test_enemy_damage_receiver_slot_membership_matches_finite_catalog,
    test_native_enemy_damage_presenter_contract_is_pinned,
)
from static_re_native_class_loadout_contracts import (
    test_native_class_loadout_census_and_identity_are_pinned,
    test_native_class_loadout_definition_to_actor_mapping_is_pinned,
    test_native_class_loadout_documented_starting_kit_stats_are_exact,
    test_native_class_loadout_goldens_are_live_settled_and_participant_owned,
    test_native_class_loadout_starting_kits_are_stat_exact,
    test_native_class_loadout_unlock_conditions_are_pinned,
)
from static_re_native_save_format_contracts import (
    test_launcher_save_layer_and_account_seam_are_pinned,
    test_native_active_wizard_saved_run_and_tutorial_boundaries_are_pinned,
    test_native_memoratorium_fifo_profile_fields_are_named_and_closed,
    test_native_save_container_codec_and_layout_are_pinned,
    test_native_save_document_node_and_payload_tables_are_exact,
    test_native_save_fixture_provenance_hashes_the_committed_recording,
    test_native_save_fresh_defaults_and_runtime_offsets_are_pinned,
    test_native_save_goldens_round_trip_all_committed_files,
    test_native_save_lifecycle_and_failure_semantics_are_pinned,
    test_native_save_recorder_is_self_provenanced_settled_bounded_and_owned,
)
from static_re_native_animation_contracts import (
    test_native_animation_attachment_and_emitter_facings_are_pinned,
    test_native_animation_frame_programs_and_tick_anchor_are_pinned,
    test_native_animation_lighting_shadow_and_camera_constants_are_pinned,
    test_native_animation_recorder_is_self_provenanced_settled_and_bounded,
    test_native_animation_state_lists_and_legal_transitions_are_pinned,
)
from static_re_native_scene_composition_contracts import (
    test_native_player_level_up_presentation_is_pinned,
    test_native_scene_camera_transform_and_backdrop_rate_are_pinned,
    test_native_scene_decor_determinism_path_is_pinned,
    test_native_scene_physical_layer_list_is_pinned,
    test_native_scene_world_sort_key_and_ties_are_pinned,
)
from static_re_native_hud_contracts import (
    test_native_hud_document_element_table_is_exact,
    test_native_hud_element_census_and_rects_are_pinned,
    test_native_hud_fill_cooldown_charge_and_notification_behavior_are_pinned,
    test_native_hud_recorder_is_self_provenanced_settled_and_visual_diffable,
    test_native_hud_visibility_scaling_and_multiplayer_are_pinned,
    test_tutorial_pointer_quad_pivot_and_complete_call_membership_are_pinned,
)
from static_re_native_hud_skill_selector_contracts import (
    test_native_hud_skill_selector_ownership_geometry_and_audio_are_pinned,
    test_native_skill_screen_ambient_seal_motion_is_pinned,
)
from static_re_native_ui_kit_contracts import (
    test_native_ui_kit_catalog_is_complete_and_regenerable,
)
from static_re_webgame_asset_contracts import (
    test_webgame_asset_double_build_and_weight_report_are_pinned,
    test_webgame_asset_fixture_covers_native_families_and_golden_references,
    test_webgame_asset_manifest_schema_and_provenance_are_pinned,
    test_webgame_workspace_battery_is_strict_ratcheted_and_ci_wired,
)
from static_re_webgame_shell_contracts import (
    test_webgame_shell_architecture_keeps_devices_inside_input,
    test_webgame_shell_boot_capture_performance_and_ci_are_wired,
    test_webgame_shell_controller_traversal_covers_live_graph,
    test_webgame_shell_manifest_renderer_and_layout_replay_are_strict,
    test_webgame_shell_twin_stick_and_focus_follow_landed_contracts,
    test_webgame_shell_visual_waiver_is_exact_two_directional_and_self_expiring,
)
from static_re_webgame_sim_core_contracts import (
    test_webgame_sim_core_is_pure_single_path_and_actor_model_pinned,
    test_webgame_sim_fire_projectile_replays_the_landed_g2_contract,
    test_webgame_sim_movement_and_collision_replay_the_landed_t2_contract,
    test_webgame_sim_replay_determinism_and_ci_gates_are_wired,
    test_webgame_sim_rng_is_bit_exact_for_integer_and_sealed_float_corpora,
    test_webgame_sim_tick_graph_and_cadences_match_g1_tables,
)
from static_re_webgame_hub_contracts import (
    test_webgame_hub_architecture_is_client_owned_provisional_and_sim_independent,
    test_webgame_hub_capture_assets_performance_provenance_and_ci_are_wired,
    test_webgame_hub_controller_traversal_covers_every_talk_purchase_and_run_boundary,
    test_webgame_hub_scene_economy_animation_and_manifest_replays_are_strict,
    test_webgame_hub_session_graph_phase_order_and_fixture_timings_are_pinned,
)
from static_re_native_hub_economy_contracts import (
    test_native_hub_dig_and_run_boundary_fields_are_pinned,
    test_native_hub_entity_census_and_interactions_are_pinned,
    test_native_hub_inventory_generation_and_rng_provenance_are_pinned,
    test_native_hub_npc_markers_and_profile_help_rows_are_pinned,
    test_native_hub_price_formulas_and_transaction_constants_are_pinned,
    test_native_hub_trader_ui_family_and_inventory_capture_are_pinned,
)
from static_re_native_loot_selector_contracts import (
    test_native_loot_actor_private_seed_lifecycle_replays_bit_exact,
    test_native_loot_amounts_and_non_enemy_sources_are_pinned,
    test_native_loot_golden_provenance_and_recorder_contract_are_pinned,
    test_native_loot_physics_lifetimes_and_multiplayer_credit_are_pinned,
    test_native_loot_selector_tables_and_decision_traces_are_pinned,
)
from static_re_native_progression_contracts import (
    test_native_level_up_presentation_and_picker_reveal_are_pinned,
    test_native_progression_actor_layout_and_all_skill_rows_are_pinned,
    test_native_progression_five_live_effect_formulas_are_pinned,
    test_native_progression_golden_and_recorder_provenance_are_pinned,
    test_native_progression_level_curve_and_xp_awards_are_pinned,
    test_native_progression_offer_pool_selection_and_rng_are_pinned,
    test_native_secondary_cooldown_and_action_gate_is_pinned,
    test_native_staff_admission_distinguishes_movement_and_current_contact,
    test_native_skill_picker_text_and_palette_abi_is_pinned,
    test_native_spell_welding_picker_art_contract_is_pinned,
)
from static_re_native_secondary_ability_contracts import (
    test_native_secondary_ability_art_audio_and_lifecycle_are_pinned,
    test_native_secondary_belt_presentation_is_closed,
    test_native_secondary_cooldown_rows_and_composite_mana_are_closed,
    test_native_secondary_ability_documents_and_generator_are_wired,
    test_native_secondary_ability_membership_rank_and_identity_are_closed,
    test_native_secondary_region_screen_feedback_lane_is_closed,
)
from static_re_native_menu_shell_contracts import (
    test_designed_menu_focus_model_consumes_g14_intents,
    test_native_menu_browser_tab_measurement_records_are_aggregable,
    test_native_menu_capture_surface_agreement_is_fail_closed,
    test_native_menu_hall_layout_retention_is_native_owner_bounded,
    test_native_menu_live_transition_graph_is_pinned,
    test_native_menu_landed_population_override_is_fail_closed,
    test_native_menu_motion_capability_campaign_resolution_is_fail_closed,
    test_native_menu_ambient_overlay_derivation_is_fail_closed,
    test_native_menu_overlay_contamination_override_is_fail_closed,
    test_native_menu_path_dependent_core_fork_is_exact,
    test_native_menu_profile_state_and_browser_tab_are_pinned,
    test_native_menu_recorders_settle_and_derive_provenance,
    test_native_menu_screen_census_and_live_layouts_are_pinned,
    test_native_menu_settlement_v2_classifier_is_strict_and_ci_wired,
    test_native_menu_settled_destinations_equal_standalones,
    test_native_menu_transition_endpoint_provenance_is_pinned,
    test_native_menu_v210_controls_title_correction_is_exact,
    test_native_menu_v211_controls_core_supersession_is_exact,
    test_native_menu_v220_dark_cloud_login_title_correction_is_exact,
    test_native_menu_v221_census_era_disposition_is_exact,
    test_native_menu_v222_final_four_disposition_is_exact,
)
from static_re_boneyard_lighting_contracts import (
    test_boneyard_tree_last_writer_render_path_is_registered,
    test_complete_native_lighting_and_shadow_system_is_registered,
)
from static_lua_mod_state_contracts import (
    test_lua_mod_state_and_events_are_authority_replicated,
)
from static_mod_transfer_contracts import (
    test_mod_transfer_consent_reuses_the_existing_join_prompt,
    test_mod_transfer_file_io_is_worker_owned_and_tick_budgeted,
    test_mod_transfer_protocol_is_versioned_fixed_width_and_bounded,
    test_mod_transfer_reuses_package_integrity_and_atomic_staging,
    test_mod_transfer_uses_one_session_service_for_udp_and_steam,
)
from static_re_mod_settings_contracts import (
    test_mod_settings_are_scoped_atomic_privileged_and_replicated,
)
from static_lua_bot_players_contracts import (
    test_lua_bot_player_docs_and_acceptance_surface,
    test_lua_bots_are_synthetic_remote_participants,
)
from static_lua_bot_brain_contracts import (
    test_bot_loadout_details_are_cached_address_free_and_observation_safe,
    test_lua_bot_brain_late_join_waits_for_complete_host_settings,
    test_lua_bot_brain_is_rostered_native_routed_and_damage_gated,
)
from static_lua_bot_play_contracts import (
    test_bot_play_for_me_reuses_one_brain_and_owner_control_rails,
    test_lua_local_player_takeover_is_owner_scoped_and_stock_routed,
)
from static_lua_ml_bot_contracts import (
    test_ml_bot_phase3_observation_masks_and_assists_are_pinned,
    test_ml_bot_phase5_rotation_and_live_acceptance_are_pinned,
    test_ml_bot_v2_native_loadout_schema_is_semantic_and_complete,
    test_ml_bot_is_simulation_timed_local_and_native_action_routed,
)
from static_lua_draw_contracts import (
    test_lua_draw_is_bounded_local_and_backbuffer_verified,
)
from static_lua_minimap_contracts import (
    test_lua_minimap_is_local_live_configurable_and_semantic,
)
from static_lua_sprites_contracts import (
    test_lua_sprites_are_owned_bounded_sandboxed_and_revisioned,
)
from static_world_render_seam_contracts import (
    test_world_sprites_use_native_order_while_screen_ui_stays_overlay,
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
from static_lua_consumables_contracts import (
    test_lua_consumables_are_native_stable_and_owner_executed,
    test_registered_item_icons_and_consumable_vfx_follow_native_duration,
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
    test_lua_scene_is_address_free_authority_owned_and_rooms_are_participant_local,
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
    test_local_native_interaction_completion_precedes_authority_retirement,
    test_native_project_uses_repo_local_lua_sources,
    test_exact_spawn_retires_invalid_featured_enemy,
    test_run_enemy_death_tombstones_precede_structural_omission,
    test_run_enemy_materialization_preserves_exact_native_type,
    test_scene_tick_keeps_dead_remote_participants_inert,
    test_snapshot_streams_are_compact_and_bandwidth_bounded,
    test_transport_telemetry_names_slow_app_thread_stages,
    test_unreliable_snapshot_ordering_is_wrap_safe,
    test_local_udp_ingress_and_wire_framing_are_bounded,
)
from static_multiplayer_ownership_contracts import (
    test_active_pair_visual_capture_routes_by_pair_backend,
    test_client_loot_pickup_requests_are_single_flight_per_drop,
    test_exact_native_equipment_identity_and_color_replicate,
    test_loot_deactivation_uses_stock_deferred_retirement,
    test_lua_exec_timeout_cancels_pending_work,
    test_native_item_pickup_converges_into_stock_inventory,
    test_native_unregister_retires_address_bound_network_identity,
    test_participant_destroy_is_deferred_until_after_stock_tick,
    test_transient_status_correction_ack_waits_for_native_application,
    test_powerup_rewards_are_authoritative_and_native,
    test_remote_windows_lua_bridge_is_persistent_and_framed,
    test_steam_client_reauthentication_preserves_live_message_session,
    test_steam_pair_recovers_lobby_membership_and_requires_stable_readiness,
)
from static_multiplayer_platform_contracts import (
    test_active_steam_behavior_harnesses_preserve_fixture_state,
    test_beta_release_contains_no_bundled_mods_or_generated_residue,
    test_beta_release_documents_steam_deck_shortcut,
    test_beta_release_smoke_canonicalizes_packaged_steam_path,
    test_defense_probes_follow_host_damage_authority,
    test_explicit_blank_boneyard_removes_native_scenery_and_collision,
    test_host_run_exit_is_authoritative_and_self_correcting,
    test_launcher_accepts_steam_invites_without_auto_launching_the_game,
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
    test_create_discipline_actions_use_stock_raw_indices,
    test_frozen_manual_enemy_cell_membership_stays_position_coherent,
    test_human_profiles_capture_and_prime_the_complete_native_loadout_quartet,
    test_level_up_barrier_waits_for_forced_picker_confirmation,
    test_level_up_choice_result_advances_owned_book_before_resume,
    test_lightning_manual_cluster_stays_inside_flat_arena_spatial_grid,
    test_manual_primary_target_survives_each_spell_dispatch_tick,
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
    test_local_participant_hit_feedback_is_event_owned_and_presentation_only,
    test_vitals_delivery_ack_does_not_retire_authority_before_hp_converges,
)
from static_dead_progression_round_respawn_contracts import (
    test_dead_picker_uses_only_the_stock_screen_virtual_gate,
    test_live_gate_is_isolated_and_reads_exact_actor_state,
    test_re_note_records_picker_respawn_and_same_actor_findings,
    test_respawn_uses_live_arena_spawn_and_restores_actor_registration,
    test_wave_respawn_is_a_transport_sequence_barrier,
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
    test_earth_boulder_damage_formula_addresses_are_registered,
    test_earth_boulder_damage_uses_native_live_spell_stats,
    test_gameplay_selection_writes_do_not_corrupt_stock_run_placement_vector,
    test_held_primary_mana_uses_native_spend_scale_and_start_rate,
    test_lua_earth_retargeting_uses_live_boulder_impact_anchor,
    test_primary_build_skill_mapping_has_single_runtime_owner,
    test_primary_mana_resolver_uses_native_live_spell_stats,
    test_water_frost_visual_heading_and_terrain_ownership_are_pinned,
)
from static_re_multiplayer_combat_contracts import (
    test_bot_element_damage_probe_supports_upgraded_primary_victim_validation,
    test_bot_equip_materialization_stays_scoped_to_bot_creation,
    test_bot_level_sync_uses_native_level_up,
    test_bot_skill_upgrade_combat_probe_checks_native_damage_and_mana,
    test_bot_upgrade_damage_delta_probe_checks_native_mana_projection_and_release_policy,
    test_client_enemy_death_presentation_requires_host_authority,
    test_primary_slot_gate_registry_is_authoritative_and_cast_scoped,
    test_hub_start_match_uses_stock_generated_boneyard_selection,
    test_hub_start_match_waits_for_app_tick_pump,
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
    test_openable_obstacle_path_policy_uses_native_collision_classes,
    test_participant_transform_updates_preserve_exact_hub_sync,
    test_pathfinding_movement_layout_is_named_and_documented,
    test_player_gamenpc_movement_seed_layout_is_named_and_documented,
    test_synthetic_source_profile_blocker_is_documented,
)
from static_re_native_sim_core_contracts import (
    test_app_tick_seeding_provenance_is_documented_and_byte_verified,
    test_movement_golden_provenance_and_schema_are_live_recorded,
    test_movement_golden_traces_pin_normalization_slide_stop_and_knockback,
    test_native_movement_integrators_and_collision_are_address_pinned,
    test_native_rng_float_primitive_reaches_both_endpoints,
    test_native_rng_float_primitive_rounds_at_three_points,
    test_native_rng_golden_replays_exact_retail_recurrence,
    test_native_rng_stream_ownership_and_callsite_census_are_pinned,
    test_native_sim_recorder_seam_is_bounded_isolated_and_registered,
    test_native_tick_graph_reconciles_simulation_and_service_cadences,
    test_recorded_run_seed_is_app_tick_derived_not_wall_clock,
)
from static_re_native_float_rng_golden_contracts import (
    test_native_float_rng_capture_seam_is_opt_in_runnable_and_fail_closed,
    test_native_float_rng_divisor_is_object_local_at_e4,
    test_native_float_rng_golden_outputs_replay_bit_exact,
    test_native_float_rng_golden_provenance_and_capture_census_are_pinned,
    test_native_float_rng_signed_draws_consume_two_stream_words,
)
from static_re_all_bot_match_contracts import (
    test_all_bot_match_uses_native_slots_real_trigger_and_hp_edges,
)
from static_re_bot_combat_parity_contracts import (
    test_botcombat_live_harnesses_require_applied_damage_and_peer_respawn,
    test_four_element_primary_slot_gates_share_one_audited_registry,
    test_wave_respawn_applies_same_actor_contract_to_synthetic_participants,
)
from static_re_enemy_target_acquisition_contracts import (
    test_enemy_retarget_is_authoritative_nearest_and_event_driven,
    test_enemy_retarget_acceptance_gate_is_wired,
    test_extended_target_selection_completes_native_chase_latch,
    test_native_enemy_target_acquisition_is_recovered_and_layout_backed,
)
from static_re_native_enemy_behavior_contracts import (
    test_enemy_behavior_goldens_pin_live_provenance_and_attack_timing,
    test_monster_recipe_field_semantics_are_complete,
    test_skeleton_behavior_transition_set_is_pinned,
)
from static_re_native_movement_contracts import (
    test_accepted_native_shims_are_documented,
    test_active_sources_reject_read_or_and_stale_path_language,
    test_cast_state_native_contracts_are_documented_and_layout_backed,
    test_hot_path_diagnostics_are_default_off_and_gated,
    test_lua_bot_constants_are_semantic_or_documented,
    test_participant_collision_resolver_is_documented_and_live_probed,
    test_player_family_locomotion_uses_native_step_and_footstep_dispatch,
    test_remaining_active_hardcode_sources_are_removed,
    test_smell_source_inventory_is_current,
)
from static_re_transport_core_contracts import (
    test_all_dead_dispatches_native_game_over_once_per_participant,
    test_dead_client_spectates_alive_players_with_local_camera_and_hud,
    test_death_spectator_has_isolated_three_owner_live_regression,
    test_all_stock_potion_subtypes_replicate_as_native_pickups,
    test_client_gold_pickup_replays_stock_feedback_once_after_authority_accepts,
    test_client_non_gold_pickups_replay_stock_feedback_once_after_authority_accepts,
    test_misc_ground_items_replicate_without_recipe_identity,
    test_local_multiplayer_udp_transport_is_wired,
    test_participant_presentation_epoch_owns_every_actor_timeline,
    test_session_status_io_is_coalesced_off_the_game_thread,
    test_multiplayer_death_epoch_owns_presentation_and_staff_drop_once,
    test_multiplayer_death_preserves_stock_audio_then_enters_spectator_mode,
    test_solo_death_bypasses_spectator_and_dispatches_stock_game_over,
    test_wave_boundary_respawn_has_staged_save_two_owner_live_regression,
    test_wave_completion_respawns_only_dead_owners_from_host_command,
    test_async_logger_keeps_blocking_output_off_callers,
    test_dead_multiplayer_participants_are_authority_inert,
)
from static_multiplayer_session_lifecycle_contracts import (
    test_match_end_preserves_lobby_and_reports_explicit_activity_state,
    test_run_loading_waits_for_every_peer_visibility_and_is_bounded,
    test_run_termination_resets_every_participant_without_retiring_wan_death_durability,
)
from static_re_steam_contracts import (
    test_manual_enemy_test_mode_logging_is_transition_only,
    test_packet_send_mode_dispatch_is_type_safe,
    test_player_state_exports_native_heading_for_bot_spawn,
    test_solomon_dark_steam_app_id_is_consistent,
    test_steam_send_queue_owns_backpressure_without_resetting_session,
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
    test_hagatha_effect_contract_is_complete,
    test_hagatha_one_shot_runtime_state_is_host_authoritative,
    test_hagatha_perks_replicate_as_participant_owned_native_state,
    test_native_hagatha_perk_catalog_is_complete,
)
from static_re_runtime_cast_contracts import (
    test_earth_live_verifier_requires_native_boulder_visual_emission,
    test_earth_primary_is_captured_from_its_native_dispatcher,
    test_memory_region_cache_refreshes_newly_committed_native_objects,
    test_multiplayer_nameplates_render_from_native_scene_passes,
    test_participant_roster_owns_every_multiplayer_ally_hud_registration,
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
from static_re_projectile_spell_mechanics_contracts import (
    test_air_and_frost_channels_remain_tick_queries_with_exact_stop_edges,
    test_air_lightning_cadence_and_contact_light_source_are_pinned,
    test_cast_glyph_emitter_index_and_offsets_are_pinned,
    test_cast_glyph_emitter_resolves_every_recorded_projectile_spawn,
    test_class_specific_rails_wall_shadow_painters_are_pinned,
    test_earth_charge_curve_and_release_geometry_are_exact,
    test_earth_boulder_second_pass_visual_ownership_is_pinned,
    test_ether_flight_compositor_and_contact_ownership_are_pinned,
    test_fireball_contact_range_and_recast_closure_is_pinned,
    test_fireball_scenery_and_terrain_masks_are_pinned,
    test_frost_jet_operand_widths_and_rank_one_update_ownership_are_pinned,
    test_held_one_shot_staff_action_handoff_is_pinned,
    test_staff_phase_edges_and_one_shot_cadence_are_pinned,
    test_materialized_projectile_trajectories_pin_native_motion,
    test_low_mana_primary_branch_and_all_consumers_are_pinned,
    test_primary_targeting_homing_and_staff_cadence_are_pinned,
    test_projectile_contact_events_cross_check_existing_damage_goldens,
    test_projectile_goldens_pin_live_capture_provenance_and_rank_coverage,
    test_projectile_presentation_and_fire_goodguy_semantics_are_pinned,
    test_projectile_spell_native_dispatch_contract_is_complete,
    test_primary_collision_and_target_priority_reopening_is_pinned,
)
from static_wan_corpse_rendering_contracts import (
    test_authoritative_life_correction_uses_the_recipient_native_maximum,
    test_driven_remote_players_use_the_stock_light_branch_skipped_by_their_slot,
    test_wan_death_presentation_is_a_convergent_transaction,
    test_dead_owner_vitals_are_reasserted_after_the_progression_tick,
)
from static_re_audio_disable_contracts import (
    test_automation_launch_surfaces_default_to_disabled_audio,
    test_launch_audio_disable_is_engine_level_and_player_opt_in,
    test_stock_audio_bootstrap_and_settings_are_layout_backed,
)
from static_re_native_audio_event_contracts import (
    test_native_audio_document_trigger_asset_rows_are_exact,
    test_native_audio_event_census_and_dispatch_golden_are_pinned,
    test_native_audio_loop_points_and_playback_semantics_are_pinned,
    test_native_audio_multiplayer_ownership_is_stock_transition_owned,
)
from static_staged_release_loader_contracts import (
    test_live_acceptance_launchers_require_release_loader,
    test_native_loader_build_flavor_stamp_is_explicit_and_logged,
    test_staged_release_loader_assertion_is_fail_closed,
)
from static_re_runtime_platform_contracts import (
    test_client_run_switch_requires_fresh_authenticated_host_intent,
    test_launcher_tutorial_bypass_is_standalone_and_default_on,
    test_launcher_multiplayer_quick_start_uses_live_ui_and_scene_readiness,
    test_launcher_saves_are_isolated_link_gated_and_proton_persisted,
    test_multiplayer_quick_start_keeps_private_gameplay_visible,
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
    test_exact_text_capture_does_not_read_retired_ui_trees,
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
    test_ci_runs_every_contract_that_needs_no_local_artifact,
    test_ci_runs_every_test_module_it_can,
    test_crash_reports_preserve_faulting_x86_frame_chain,
    test_every_defined_contract_reaches_the_registry,
    test_recorded_capture_provenance_resolves_or_is_declared,
    test_investigation_register_has_static_coverage,
    test_lua_follow_preserves_timeout_teleport,
    test_multiplayer_launch_preflights_steam_before_starting_game,
    test_native_derived_wizard_visuals_are_layout_backed,
    test_native_global_reads_do_not_use_loader_substitutes,
    test_native_d3d_device_lifetime_outlives_stock_teardown,
    test_path_builder_does_not_walk_to_unrequested_alternate_goals,
    test_path_builder_expands_cells_before_los_smoothing,
    test_process_termination_has_no_joinable_static_worker_destructors,
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
from static_qol_backend_contracts import (
    test_all_session_end_paths_share_provider_and_directory_teardown,
    test_live_session_leave_acks_before_canonical_teardown,
    test_raptisoft_close_url_call_is_runtime_nopped,
)

TESTS: list[tuple[str, Callable[[], str]]] = [
    (
        "Native UI kit catalog is complete and regenerable",
        test_native_ui_kit_catalog_is_complete_and_regenerable,
    ),
    (
        "Mod transfer protocol is versioned, fixed-width, and bounded",
        test_mod_transfer_protocol_is_versioned_fixed_width_and_bounded,
    ),
    (
        "Mod transfer file IO is worker-owned and tick-budgeted",
        test_mod_transfer_file_io_is_worker_owned_and_tick_budgeted,
    ),
    (
        "Mod transfer shares one session service across UDP and Steam",
        test_mod_transfer_uses_one_session_service_for_udp_and_steam,
    ),
    (
        "Mod transfer reuses the existing join consent prompt",
        test_mod_transfer_consent_reuses_the_existing_join_prompt,
    ),
    (
        "Mod transfer reuses integrity and atomic package staging",
        test_mod_transfer_reuses_package_integrity_and_atomic_staging,
    ),
    (
        "live-session leave ACK precedes canonical teardown",
        test_live_session_leave_acks_before_canonical_teardown,
    ),
    (
        "all session end paths share provider and directory teardown",
        test_all_session_end_paths_share_provider_and_directory_teardown,
    ),
    (
        "Raptisoft close URL call is runtime NOPed",
        test_raptisoft_close_url_call_is_runtime_nopped,
    ),
    (
        "Lua run seed is authority-owned and native-applied",
        test_lua_run_seed_is_authority_owned_and_native_applied,
    ),
    (
        "Lua navigation is bounded, read-only, and native-backed",
        test_lua_nav_is_bounded_read_only_and_native_backed,
    ),
    (
        "Lua scene control is semantic, authority-owned, and participant-local",
        test_lua_scene_is_address_free_authority_owned_and_rooms_are_participant_local,
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
        "Lua consumables are native, stable, and owner-executed",
        test_lua_consumables_are_native_stable_and_owner_executed,
    ),
    (
        "Registered item icons and consumable VFX follow native duration",
        test_registered_item_icons_and_consumable_vfx_follow_native_duration,
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
        "Lua Minimap is local, live-configurable, and semantic",
        test_lua_minimap_is_local_live_configurable_and_semantic,
    ),
    (
        "Lua sprites are owned, bounded, sandboxed, and revisioned",
        test_lua_sprites_are_owned_bounded_sandboxed_and_revisioned,
    ),
    (
        "World sprites use native order while screen UI stays overlay",
        test_world_sprites_use_native_order_while_screen_ui_stays_overlay,
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
        "Lua mod settings are scoped, atomic, privileged, and replicated",
        test_mod_settings_are_scoped_atomic_privileged_and_replicated,
    ),
    (
        "Lua bots are synthetic remote participants",
        test_lua_bots_are_synthetic_remote_participants,
    ),
    (
        "Lua bot brain is rostered and applied-damage gated",
        test_lua_bot_brain_is_rostered_native_routed_and_damage_gated,
    ),
    (
        "Lua local-player takeover is owner-scoped and stock-routed",
        test_lua_local_player_takeover_is_owner_scoped_and_stock_routed,
    ),
    (
        "Bot Play For Me reuses one brain and owner-control rails",
        test_bot_play_for_me_reuses_one_brain_and_owner_control_rails,
    ),
    (
        "Lua bot loadout details are cached and observation-safe",
        test_bot_loadout_details_are_cached_address_free_and_observation_safe,
    ),
    (
        "Learned Lua bot is simulation-timed and native action-routed",
        test_ml_bot_is_simulation_timed_local_and_native_action_routed,
    ),
    (
        "ML bot v2 native loadout schema is semantic and complete",
        test_ml_bot_v2_native_loadout_schema_is_semantic_and_complete,
    ),
    (
        "ML bot v2 Phase 3 observation, masks, and assists are pinned",
        test_ml_bot_phase3_observation_masks_and_assists_are_pinned,
    ),
    (
        "ML bot v2 Phase 5 rotation and live acceptance are pinned",
        test_ml_bot_phase5_rotation_and_live_acceptance_are_pinned,
    ),
    (
        "Lua bot brain late join waits for complete host settings",
        test_lua_bot_brain_late_join_waits_for_complete_host_settings,
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
        "Boneyard scripting object model and runtime anchors are registered",
        test_boneyard_scripting_model_and_runtime_anchors_are_registered,
    ),
    (
        "Default Boneyard load, seed, and compact-decor findings are registered",
        test_default_boneyard_load_seed_and_compact_decor_findings_are_registered,
    ),
    (
        "Boneyard generator control flow and output census are complete",
        test_boneyard_generator_control_flow_and_output_census_is_complete,
    ),
    (
        "Solomon Dig encounter and survival wave director are registered",
        test_solomon_dig_and_wave_director_contract_is_registered,
    ),
    (
        "Stock map picker recovery pins the selected value and launch path",
        test_stock_map_picker_recovery_pins_selected_value_and_launch_path,
    ),
    (
        "Default Boneyard is pinned and bypasses the native picker",
        test_default_boneyard_is_pinned_and_bypasses_the_native_picker,
    ),
    (
        "Boneyard picker provider is immutable, stock-routed, and stock-transparent",
        test_boneyard_picker_provider_is_immutable_stock_routed_and_stock_transparent,
    ),
    (
        "Boneyard picker replication is authoritative, missing-safe, and late-joined",
        test_boneyard_picker_replication_is_authoritative_missing_safe_and_late_joined,
    ),
    (
        "Boneyard picker presents the mod description and scales with the viewport",
        test_boneyard_picker_presents_mod_description_and_scales_with_viewport,
    ),
    (
        "Boneyard picker owns its keyboard edges and centers row text",
        test_boneyard_picker_owns_its_keys_and_centers_row_text,
    ),
    (
        "Connected client Courtyard start is render and activation suppressed",
        test_connected_client_courtyard_start_is_render_and_activation_suppressed,
    ),
    (
        "Multiplayer Boneyard scenery shares the host generation boundary",
        test_multiplayer_boneyard_scenery_shares_the_host_generation_boundary,
    ),
    (
        "Loading screen uses native stage progress and shared D3D9 lifetime",
        test_loading_screen_uses_native_stage_progress_and_shared_d3d9_lifetime,
    ),
    (
        "Blocking overlay owns all gameplay input without deferral",
        test_blocking_overlay_owns_all_gameplay_input_without_deferral,
    ),
    (
        "Native input ingress, sampling, and tick order are pinned",
        test_native_input_ingress_sampling_and_tick_order_are_pinned,
    ),
    (
        "Native surface priority and loading input seal are pinned",
        test_native_surface_priority_and_loading_input_seal_are_pinned,
    ),
    (
        "Native action thresholds, absences, and Intent shape are pinned",
        test_native_action_thresholds_absences_and_intent_shape_are_pinned,
    ),
    (
        "Native session-flow state enum is pinned",
        test_native_session_flow_state_enum_is_pinned,
    ),
    (
        "Native session-flow legal edge set is pinned",
        test_native_session_flow_legal_edge_set_is_pinned,
    ),
    (
        "Native session-flow transition step order is pinned",
        test_native_session_flow_transition_step_order_is_pinned,
    ),
    (
        "Native session-flow input seal boundaries are pinned",
        test_native_session_flow_input_seal_boundaries_are_pinned,
    ),
    (
        "First-wizard College admission ownership is pinned",
        test_first_wizard_college_admission_contract_is_pinned,
    ),
    (
        "Native class-loadout census and identity are pinned",
        test_native_class_loadout_census_and_identity_are_pinned,
    ),
    (
        "Native class-loadout starting kits are stat-exact",
        test_native_class_loadout_starting_kits_are_stat_exact,
    ),
    (
        "Native class-loadout document starting-kit table is stat-exact",
        test_native_class_loadout_documented_starting_kit_stats_are_exact,
    ),
    (
        "Native class-loadout definition-to-actor mapping is pinned",
        test_native_class_loadout_definition_to_actor_mapping_is_pinned,
    ),
    (
        "Native class-loadout unlock conditions are pinned",
        test_native_class_loadout_unlock_conditions_are_pinned,
    ),
    (
        "Native class-loadout goldens are live-settled and participant-owned",
        test_native_class_loadout_goldens_are_live_settled_and_participant_owned,
    ),
    (
        "Native animation state lists and legal transitions are pinned",
        test_native_animation_state_lists_and_legal_transitions_are_pinned,
    ),
    (
        "Native animation frame programs and tick anchor are pinned",
        test_native_animation_frame_programs_and_tick_anchor_are_pinned,
    ),
    (
        "Native animation attachment and emitter facings are pinned",
        test_native_animation_attachment_and_emitter_facings_are_pinned,
    ),
    (
        "Native animation lighting, shadow, and camera constants are pinned",
        test_native_animation_lighting_shadow_and_camera_constants_are_pinned,
    ),
    (
        "Native animation recorder is self-provenanced, settled, and bounded",
        test_native_animation_recorder_is_self_provenanced_settled_and_bounded,
    ),
    (
        "Native scene physical layer list is pinned",
        test_native_scene_physical_layer_list_is_pinned,
    ),
    (
        "Native scene world sort key and ties are pinned",
        test_native_scene_world_sort_key_and_ties_are_pinned,
    ),
    (
        "Native player level-up presentation is pinned",
        test_native_player_level_up_presentation_is_pinned,
    ),
    (
        "Native scene camera transform and backdrop rate are pinned",
        test_native_scene_camera_transform_and_backdrop_rate_are_pinned,
    ),
    (
        "Native scene decor determinism path is pinned",
        test_native_scene_decor_determinism_path_is_pinned,
    ),
    (
        "Native HUD document element table is exact",
        test_native_hud_document_element_table_is_exact,
    ),
    (
        "Native HUD element census and rects are pinned",
        test_native_hud_element_census_and_rects_are_pinned,
    ),
    (
        "Native HUD fills, cooldown, charge, and notifications are pinned",
        test_native_hud_fill_cooldown_charge_and_notification_behavior_are_pinned,
    ),
    (
        "Native HUD visibility, scaling, and multiplayer are pinned",
        test_native_hud_visibility_scaling_and_multiplayer_are_pinned,
    ),
    (
        "Native HUD recorder is self-provenanced, settled, and visual-diffable",
        test_native_hud_recorder_is_self_provenanced_settled_and_visual_diffable,
    ),
    (
        "Tutorial pointer centred quad and complete call membership are pinned",
        test_tutorial_pointer_quad_pivot_and_complete_call_membership_are_pinned,
    ),
    (
        "Native HUD selected-skill selector ownership, geometry, and audio are pinned",
        test_native_hud_skill_selector_ownership_geometry_and_audio_are_pinned,
    ),
    (
        "Native SkillScreen ambient seal motion is pinned",
        test_native_skill_screen_ambient_seal_motion_is_pinned,
    ),
    (
        "Webgame asset manifest schema and provenance are pinned",
        test_webgame_asset_manifest_schema_and_provenance_are_pinned,
    ),
    (
        "Webgame asset double-build and weight report are pinned",
        test_webgame_asset_double_build_and_weight_report_are_pinned,
    ),
    (
        "Webgame asset fixture covers native families and golden references",
        test_webgame_asset_fixture_covers_native_families_and_golden_references,
    ),
    (
        "Webgame workspace battery is strict, ratcheted, and CI-wired",
        test_webgame_workspace_battery_is_strict_ratcheted_and_ci_wired,
    ),
    (
        "Webgame shell architecture keeps devices inside input",
        test_webgame_shell_architecture_keeps_devices_inside_input,
    ),
    (
        "Webgame shell twin-stick and focus follow landed contracts",
        test_webgame_shell_twin_stick_and_focus_follow_landed_contracts,
    ),
    (
        "Webgame shell manifest renderer and layout replay are strict",
        test_webgame_shell_manifest_renderer_and_layout_replay_are_strict,
    ),
    (
        "Webgame shell controller traversal covers live graph",
        test_webgame_shell_controller_traversal_covers_live_graph,
    ),
    (
        "Webgame shell visual waiver is exact, two-directional, and self-expiring",
        test_webgame_shell_visual_waiver_is_exact_two_directional_and_self_expiring,
    ),
    (
        "Webgame shell boot capture performance and CI are wired",
        test_webgame_shell_boot_capture_performance_and_ci_are_wired,
    ),
    (
        "Webgame P2 sim core is pure, single-path, and actor-model pinned",
        test_webgame_sim_core_is_pure_single_path_and_actor_model_pinned,
    ),
    (
        "Webgame P2 tick graph and cadences match G1 tables",
        test_webgame_sim_tick_graph_and_cadences_match_g1_tables,
    ),
    (
        "Webgame P2 movement and collision replay landed T2",
        test_webgame_sim_movement_and_collision_replay_the_landed_t2_contract,
    ),
    (
        "Webgame P2 RNG is bit-exact for integer and sealed float corpora",
        test_webgame_sim_rng_is_bit_exact_for_integer_and_sealed_float_corpora,
    ),
    (
        "Webgame P2 FIRE projectile replays landed G2",
        test_webgame_sim_fire_projectile_replays_the_landed_g2_contract,
    ),
    (
        "Webgame P2 replay, determinism, and CI gates are wired",
        test_webgame_sim_replay_determinism_and_ci_gates_are_wired,
    ),
    (
        "Webgame P1 hub architecture is client-owned, provisional, and sim-independent",
        test_webgame_hub_architecture_is_client_owned_provisional_and_sim_independent,
    ),
    (
        "Webgame P1 hub scene, economy, animation, and manifest replays are strict",
        test_webgame_hub_scene_economy_animation_and_manifest_replays_are_strict,
    ),
    (
        "Webgame P1 hub session graph, phase order, and fixture timings are pinned",
        test_webgame_hub_session_graph_phase_order_and_fixture_timings_are_pinned,
    ),
    (
        "Webgame P1 hub controller traversal covers talk, purchase, and run boundaries",
        test_webgame_hub_controller_traversal_covers_every_talk_purchase_and_run_boundary,
    ),
    (
        "Webgame P1 hub capture, assets, performance, provenance, and CI are wired",
        test_webgame_hub_capture_assets_performance_provenance_and_ci_are_wired,
    ),
    (
        "Native hub entity census and interactions are pinned",
        test_native_hub_entity_census_and_interactions_are_pinned,
    ),
    (
        "Native hub NPC markers and profile help rows are pinned",
        test_native_hub_npc_markers_and_profile_help_rows_are_pinned,
    ),
    (
        "Native hub price formulas and transaction constants are pinned",
        test_native_hub_price_formulas_and_transaction_constants_are_pinned,
    ),
    (
        "Native hub inventory generation and RNG provenance are pinned",
        test_native_hub_inventory_generation_and_rng_provenance_are_pinned,
    ),
    (
        "Native hub Dig and run boundary fields are pinned",
        test_native_hub_dig_and_run_boundary_fields_are_pinned,
    ),
    (
        "Native hub/trader UI family and inventory capture is pinned",
        test_native_hub_trader_ui_family_and_inventory_capture_are_pinned,
    ),
    (
        "Native loot golden provenance and recorder contract are pinned",
        test_native_loot_golden_provenance_and_recorder_contract_are_pinned,
    ),
    (
        "Native loot actor-private seed lifecycle replays bit-exact",
        test_native_loot_actor_private_seed_lifecycle_replays_bit_exact,
    ),
    (
        "Native loot selector tables and decision traces are pinned",
        test_native_loot_selector_tables_and_decision_traces_are_pinned,
    ),
    (
        "Native loot amounts and non-enemy sources are pinned",
        test_native_loot_amounts_and_non_enemy_sources_are_pinned,
    ),
    (
        "Native loot physics, lifetimes, and multiplayer credit are pinned",
        test_native_loot_physics_lifetimes_and_multiplayer_credit_are_pinned,
    ),
    (
        "Native level-up presentation and picker reveal are pinned",
        test_native_level_up_presentation_and_picker_reveal_are_pinned,
    ),
    (
        "Native progression level curve and XP awards are pinned",
        test_native_progression_level_curve_and_xp_awards_are_pinned,
    ),
    (
        "Native progression offer pool, selection, and RNG are pinned",
        test_native_progression_offer_pool_selection_and_rng_are_pinned,
    ),
    (
        "Native secondary cooldown and action gate are pinned",
        test_native_secondary_cooldown_and_action_gate_is_pinned,
    ),
    (
        "Native progression five live effect formulas are pinned",
        test_native_progression_five_live_effect_formulas_are_pinned,
    ),
    (
        "Native progression actor layout and all skill rows are pinned",
        test_native_progression_actor_layout_and_all_skill_rows_are_pinned,
    ),
    (
        "Native skill picker text and palette ABI is pinned",
        test_native_skill_picker_text_and_palette_abi_is_pinned,
    ),
    (
        "Native Staff admission distinguishes movement and current contact",
        test_native_staff_admission_distinguishes_movement_and_current_contact,
    ),
    (
        "Native Spell Welding picker art contract is pinned",
        test_native_spell_welding_picker_art_contract_is_pinned,
    ),
    (
        "Native progression golden and recorder provenance are pinned",
        test_native_progression_golden_and_recorder_provenance_are_pinned,
    ),
    (
        "Native secondary ability membership, rank, and identity are closed",
        test_native_secondary_ability_membership_rank_and_identity_are_closed,
    ),
    (
        "Native secondary BeltButton presentation is closed",
        test_native_secondary_belt_presentation_is_closed,
    ),
    (
        "Native secondary cooldown rows and composite mana are closed",
        test_native_secondary_cooldown_rows_and_composite_mana_are_closed,
    ),
    (
        "Native secondary Region screen-feedback lane is closed",
        test_native_secondary_region_screen_feedback_lane_is_closed,
    ),
    (
        "Native secondary ability art, audio, and lifecycle are pinned",
        test_native_secondary_ability_art_audio_and_lifecycle_are_pinned,
    ),
    (
        "Native secondary ability documents and generator are wired",
        test_native_secondary_ability_documents_and_generator_are_wired,
    ),
    (
        "Native menu screen census and live layouts are pinned",
        test_native_menu_screen_census_and_live_layouts_are_pinned,
    ),
    (
        "Native menu recorders settle and derive provenance",
        test_native_menu_recorders_settle_and_derive_provenance,
    ),
    (
        "Native menu profile state and browser tab are pinned",
        test_native_menu_profile_state_and_browser_tab_are_pinned,
    ),
    (
        "Native menu browser tab measurement records are aggregable",
        test_native_menu_browser_tab_measurement_records_are_aggregable,
    ),
    (
        "Native menu Hall layout retention is native-owner bounded",
        test_native_menu_hall_layout_retention_is_native_owner_bounded,
    ),
    (
        "Native menu capture surface agreement is fail closed",
        test_native_menu_capture_surface_agreement_is_fail_closed,
    ),
    (
        "Native menu Settlement v2 classifier is strict and CI wired",
        test_native_menu_settlement_v2_classifier_is_strict_and_ci_wired,
    ),
    (
        "Native menu motion capability campaign resolution is fail closed",
        test_native_menu_motion_capability_campaign_resolution_is_fail_closed,
    ),
    (
        "Native menu v2.10 Controls title correction is exact",
        test_native_menu_v210_controls_title_correction_is_exact,
    ),
    (
        "Native menu v2.11 Controls structural supersession is exact",
        test_native_menu_v211_controls_core_supersession_is_exact,
    ),
    (
        "Native menu v2.20 Dark Cloud login title correction is exact",
        test_native_menu_v220_dark_cloud_login_title_correction_is_exact,
    ),
    (
        "Native menu v2.21 census-era disposition is exact",
        test_native_menu_v221_census_era_disposition_is_exact,
    ),
    (
        "Native menu v2.22 final four-row disposition is exact",
        test_native_menu_v222_final_four_disposition_is_exact,
    ),
    (
        "Native menu path-dependent core fork is exact",
        test_native_menu_path_dependent_core_fork_is_exact,
    ),
    (
        "Native menu landed population override is fail closed",
        test_native_menu_landed_population_override_is_fail_closed,
    ),
    (
        "Native menu overlay contamination override is fail closed",
        test_native_menu_overlay_contamination_override_is_fail_closed,
    ),
    (
        "Native menu ambient overlay derivation is fail closed",
        test_native_menu_ambient_overlay_derivation_is_fail_closed,
    ),
    (
        "Native menu live transition graph is pinned",
        test_native_menu_live_transition_graph_is_pinned,
    ),
    (
        "Native menu transition endpoint provenance is pinned",
        test_native_menu_transition_endpoint_provenance_is_pinned,
    ),
    (
        "Native menu settled destinations equal standalones",
        test_native_menu_settled_destinations_equal_standalones,
    ),
    (
        "Designed menu focus model consumes G14 intents",
        test_designed_menu_focus_model_consumes_g14_intents,
    ),
    (
        "Boneyard Tree last-writer render path is registered",
        test_boneyard_tree_last_writer_render_path_is_registered,
    ),
    (
        "Complete native lighting and shadow system is registered",
        test_complete_native_lighting_and_shadow_system_is_registered,
    ),
    (
        "Repository history uses approved project identities",
        test_repository_history_uses_approved_identities,
    ),
    (
        "Identity census refuses to run against a shallow clone",
        test_identity_contract_cannot_run_against_a_shallow_clone,
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
        "local native interaction completion precedes authority retirement",
        test_local_native_interaction_completion_precedes_authority_retirement,
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
        "participant teardown waits until after the stock application tick",
        test_participant_destroy_is_deferred_until_after_stock_tick,
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
        "beta release contains no bundled mods or generated residue",
        test_beta_release_contains_no_bundled_mods_or_generated_residue,
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
        "launcher joins Steam lobbies without auto-launching the game",
        test_launcher_accepts_steam_invites_without_auto_launching_the_game,
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
        "manual primary targets survive each spell-dispatch tick",
        test_manual_primary_target_survives_each_spell_dispatch_tick,
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
        "local participant hit feedback is event-owned and presentation-only",
        test_local_participant_hit_feedback_is_event_owned_and_presentation_only,
    ),
    (
        "vitals delivery ACK waits for matching owner HP",
        test_vitals_delivery_ack_does_not_retire_authority_before_hp_converges,
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
    (
        "Water Frost visual heading and terrain ownership are pinned",
        test_water_frost_visual_heading_and_terrain_ownership_are_pinned,
    ),
    ("Earth boulder damage uses native live spell stats", test_earth_boulder_damage_uses_native_live_spell_stats),
    (
        "Earth Boulder damage formula addresses are registered",
        test_earth_boulder_damage_formula_addresses_are_registered,
    ),
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
        "launcher tutorial bypass is standalone and default-on",
        test_launcher_tutorial_bypass_is_standalone_and_default_on,
    ),
    (
        "launcher multiplayer quick start uses live UI and scene readiness",
        test_launcher_multiplayer_quick_start_uses_live_ui_and_scene_readiness,
    ),
    (
        "multiplayer quick start keeps private gameplay visible",
        test_multiplayer_quick_start_keeps_private_gameplay_visible,
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
        "human profiles capture and prime the complete native loadout quartet",
        test_human_profiles_capture_and_prime_the_complete_native_loadout_quartet,
    ),
    (
        "Create discipline actions use stock raw indices",
        test_create_discipline_actions_use_stock_raw_indices,
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
        "process termination has no joinable static worker destructors",
        test_process_termination_has_no_joinable_static_worker_destructors,
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
        "Exact-text capture does not read retired UI trees",
        test_exact_text_capture_does_not_read_retired_ui_trees,
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
    ("hub Start Match uses stock generated Boneyard selection", test_hub_start_match_uses_stock_generated_boneyard_selection),
    ("hub Start Match waits for app-tick pump", test_hub_start_match_waits_for_app_tick_pump),
    ("primary kill stress verifier uses native hub start", test_primary_kill_stress_verifier_uses_native_hub_start),
    ("unverified play boneyard shortcut is not exposed", test_unverified_play_boneyard_shortcut_is_not_exposed),
    ("replicated manual run enemy materialization is client bounded", test_replicated_manual_run_enemy_materialization_is_client_bounded),
    ("primary mana resolver accepts native dispatcher entry ids", test_primary_mana_resolver_accepts_native_dispatcher_entry_ids),
    ("native primary output layout follows Skills_Wizard stat order", test_native_primary_output_layout_is_stat_ordered),
    ("Lightning Chaining verifier uses native dispatcher loop", test_lightning_chaining_verifier_uses_native_dispatcher_loop),
    ("primary selection mapping is native-backed", test_primary_selection_mapping_is_native_backed_not_static_table),
    ("primary attack window uses live native selection range", test_primary_attack_window_uses_live_native_selection_range),
    ("Elemental primary slot-gate registry is authoritative and cast scoped", test_primary_slot_gate_registry_is_authoritative_and_cast_scoped),
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
    (
        "Openable obstacle path policy uses native collision classes",
        test_openable_obstacle_path_policy_uses_native_collision_classes,
    ),
    (
        "All-bot match uses native slots, real trigger, and HP edges",
        test_all_bot_match_uses_native_slots_real_trigger_and_hp_edges,
    ),
    (
        "Four elemental primary slot gates share one audited registry",
        test_four_element_primary_slot_gates_share_one_audited_registry,
    ),
    (
        "Wave respawn applies the same-actor contract to synthetic participants",
        test_wave_respawn_applies_same_actor_contract_to_synthetic_participants,
    ),
    (
        "Botcombat live harnesses require applied damage and peer respawn",
        test_botcombat_live_harnesses_require_applied_damage_and_peer_respawn,
    ),
    (
        "Native enemy target acquisition is recovered and layout-backed",
        test_native_enemy_target_acquisition_is_recovered_and_layout_backed,
    ),
    (
        "Native-to-Website survival combat integration contract is pinned",
        test_native_web_combat_lifecycle_integration_contract_is_pinned,
    ),
    (
        "Native enemy damage presenter contract is pinned",
        test_native_enemy_damage_presenter_contract_is_pinned,
    ),
    (
        "Enemy damage receiver slot membership matches the finite catalog",
        test_enemy_damage_receiver_slot_membership_matches_finite_catalog,
    ),
    (
        "Enemy damage audio identity is exact",
        test_enemy_damage_audio_identity_is_exact,
    ),
    (
        "Extended target selection completes the native chase latch",
        test_extended_target_selection_completes_native_chase_latch,
    ),
    (
        "Enemy retarget acceptance gate is wired",
        test_enemy_retarget_acceptance_gate_is_wired,
    ),
    (
        "Enemy retarget is authoritative, nearest, and event-driven",
        test_enemy_retarget_is_authoritative_nearest_and_event_driven,
    ),
    (
        "MonsterRecipe fields have complete runtime semantics",
        test_monster_recipe_field_semantics_are_complete,
    ),
    (
        "Skeleton-family behavior transition set is pinned",
        test_skeleton_behavior_transition_set_is_pinned,
    ),
    (
        "Enemy behavior live goldens and attack timing are pinned",
        test_enemy_behavior_goldens_pin_live_provenance_and_attack_timing,
    ),
    ("Player/GameNpc movement seed layout is named and documented", test_player_gamenpc_movement_seed_layout_is_named_and_documented),
    ("Bot movement speed uses native live envelope", test_bot_movement_speed_uses_native_live_envelope),
    ("Participant collision resolver is documented and live-probed", test_participant_collision_resolver_is_documented_and_live_probed),
    (
        "Player-family locomotion uses native step and footstep dispatch",
        test_player_family_locomotion_uses_native_step_and_footstep_dispatch,
    ),
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
    (
        "multiplayer death preserves stock audio then enters spectator mode",
        test_multiplayer_death_preserves_stock_audio_then_enters_spectator_mode,
    ),
    (
        "multiplayer death epoch owns presentation and staff drop once",
        test_multiplayer_death_epoch_owns_presentation_and_staff_drop_once,
    ),
    (
        "solo death bypasses spectator and dispatches stock Game Over",
        test_solo_death_bypasses_spectator_and_dispatches_stock_game_over,
    ),
    (
        "all dead dispatches native Game Over once per participant",
        test_all_dead_dispatches_native_game_over_once_per_participant,
    ),
    (
        "match end preserves lobby and reports explicit activity state",
        test_match_end_preserves_lobby_and_reports_explicit_activity_state,
    ),
    (
        "run loading waits for every peer visibility and is bounded",
        test_run_loading_waits_for_every_peer_visibility_and_is_bounded,
    ),
    (
        "run termination resets every participant without retiring WAN death durability",
        test_run_termination_resets_every_participant_without_retiring_wan_death_durability,
    ),
    (
        "dead client spectates alive players with local camera and HUD",
        test_dead_client_spectates_alive_players_with_local_camera_and_hud,
    ),
    (
        "wave boundary respawns only dead owners from reliable host command",
        test_wave_completion_respawns_only_dead_owners_from_host_command,
    ),
    (
        "wave boundary respawn has staged-save two-owner live regression",
        test_wave_boundary_respawn_has_staged_save_two_owner_live_regression,
    ),
    (
        "death spectator has isolated three-owner live regression",
        test_death_spectator_has_isolated_three_owner_live_regression,
    ),
    (
        "dead picker advances only through its stock screen virtual",
        test_dead_picker_uses_only_the_stock_screen_virtual_gate,
    ),
    (
        "wave respawn rejects pre-respawn vitals authority",
        test_wave_respawn_is_a_transport_sequence_barrier,
    ),
    (
        "dead progression RE note records lifecycle findings",
        test_re_note_records_picker_respawn_and_same_actor_findings,
    ),
    (
        "respawn uses the live Arena spawn and restores actor registration",
        test_respawn_uses_live_arena_spawn_and_restores_actor_registration,
    ),
    (
        "dead progression live gate uses stock input and exact actor reads",
        test_live_gate_is_isolated_and_reads_exact_actor_state,
    ),
    ("local multiplayer UDP transport is wired", test_local_multiplayer_udp_transport_is_wired),
    (
        "participant presentation epoch owns every actor timeline",
        test_participant_presentation_epoch_owns_every_actor_timeline,
    ),
    (
        "session status IO is coalesced off the game thread",
        test_session_status_io_is_coalesced_off_the_game_thread,
    ),
    (
        "world snapshots are complete MTU-sized generations",
        test_world_snapshots_are_complete_mtu_sized_generations,
    ),
    (
        "Steam send queue owns backpressure without resetting session",
        test_steam_send_queue_owns_backpressure_without_resetting_session,
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
        "Hagatha gameplay effect contract is complete",
        test_hagatha_effect_contract_is_complete,
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
    (
        "CI runs every contract that needs no local artifact",
        test_ci_runs_every_contract_that_needs_no_local_artifact,
    ),
    (
        "CI runs every test module it can",
        test_ci_runs_every_test_module_it_can,
    ),
    (
        "every defined contract reaches the registry",
        test_every_defined_contract_reaches_the_registry,
    ),
    (
        "recorded capture provenance resolves or is declared",
        test_recorded_capture_provenance_resolves_or_is_declared,
    ),
    ("staged binary matches analysis binary", test_staged_binary_matches_analysis_binary),
    (
        "stock audio bootstrap and settings are layout-backed",
        test_stock_audio_bootstrap_and_settings_are_layout_backed,
    ),
    (
        "launch audio disable is engine-level and player opt-in",
        test_launch_audio_disable_is_engine_level_and_player_opt_in,
    ),
    (
        "native audio document trigger asset rows are exact",
        test_native_audio_document_trigger_asset_rows_are_exact,
    ),
    (
        "native audio event census and dispatch golden are pinned",
        test_native_audio_event_census_and_dispatch_golden_are_pinned,
    ),
    (
        "native audio loop points and playback semantics are pinned",
        test_native_audio_loop_points_and_playback_semantics_are_pinned,
    ),
    (
        "native audio multiplayer ownership is stock-transition owned",
        test_native_audio_multiplayer_ownership_is_stock_transition_owned,
    ),
    (
        "automation launch surfaces default to disabled audio",
        test_automation_launch_surfaces_default_to_disabled_audio,
    ),
    (
        "native loader build flavor is explicit and logged",
        test_native_loader_build_flavor_stamp_is_explicit_and_logged,
    ),
    (
        "staged Release-loader assertion is fail-closed",
        test_staged_release_loader_assertion_is_fail_closed,
    ),
    (
        "live-acceptance launchers require a Release loader",
        test_live_acceptance_launchers_require_release_loader,
    ),
    ("binary layout identity is staged", test_binary_layout_matches_staged_layout_identity),
    (
        "native D3D device lifetime outlives stock teardown",
        test_native_d3d_device_lifetime_outlives_stock_teardown,
    ),
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
    (
        "participant roster owns every multiplayer ally-HUD registration",
        test_participant_roster_owns_every_multiplayer_ally_hud_registration,
    ),
    (
        "client enemy death presentation requires host authority",
        test_client_enemy_death_presentation_requires_host_authority,
    ),
    (
        "driven remote players use the skipped stock light branch",
        test_driven_remote_players_use_the_stock_light_branch_skipped_by_their_slot,
    ),
    (
        "projectile/spell native dispatch is complete",
        test_projectile_spell_native_dispatch_contract_is_complete,
    ),
    (
        "held one-shot Staff action handoff is pinned",
        test_held_one_shot_staff_action_handoff_is_pinned,
    ),
    (
        "projectile goldens pin live provenance and ranks",
        test_projectile_goldens_pin_live_capture_provenance_and_rank_coverage,
    ),
    (
        "materialized projectile motion is native-tick exact",
        test_materialized_projectile_trajectories_pin_native_motion,
    ),
    (
        "Earth charge and release geometry are exact",
        test_earth_charge_curve_and_release_geometry_are_exact,
    ),
    (
        "Earth second-pass visual ownership is pinned",
        test_earth_boulder_second_pass_visual_ownership_is_pinned,
    ),
    (
        "Low-mana primary branch and consumers are pinned",
        test_low_mana_primary_branch_and_all_consumers_are_pinned,
    ),
    (
        "Air and Frost remain tick queries with exact stop edges",
        test_air_and_frost_channels_remain_tick_queries_with_exact_stop_edges,
    ),
    (
        "Air Lightning cadence and contact light source are pinned",
        test_air_lightning_cadence_and_contact_light_source_are_pinned,
    ),
    (
        "Frost Jet operand widths and rank-one update ownership are pinned",
        test_frost_jet_operand_widths_and_rank_one_update_ownership_are_pinned,
    ),
    (
        "projectile contacts cross-check existing damage goldens",
        test_projectile_contact_events_cross_check_existing_damage_goldens,
    ),
    (
        "projectile presentation and Fire_Goodguy semantics are pinned",
        test_projectile_presentation_and_fire_goodguy_semantics_are_pinned,
    ),
    (
        "Primary targeting, homing, range, and Staff cadence are pinned",
        test_primary_targeting_homing_and_staff_cadence_are_pinned,
    ),
    (
        "Fireball contact, range, and recast closure is pinned",
        test_fireball_contact_range_and_recast_closure_is_pinned,
    ),
    (
        "Fireball scenery and terrain masks are pinned",
        test_fireball_scenery_and_terrain_masks_are_pinned,
    ),
    (
        "Primary collision and target priority reopening is pinned",
        test_primary_collision_and_target_priority_reopening_is_pinned,
    ),
    (
        "Ether flight compositor and contact ownership are pinned",
        test_ether_flight_compositor_and_contact_ownership_are_pinned,
    ),
    (
        "Staff phase edges and one-shot cadence are pinned",
        test_staff_phase_edges_and_one_shot_cadence_are_pinned,
    ),
    (
        "Rails and Wall custom shadow painters are pinned",
        test_class_specific_rails_wall_shadow_painters_are_pinned,
    ),
    (
        "Cast glyph emitter index arithmetic and element offsets are pinned",
        test_cast_glyph_emitter_index_and_offsets_are_pinned,
    ),
    (
        "Cast glyph emitter resolves every recorded projectile spawn",
        test_cast_glyph_emitter_resolves_every_recorded_projectile_spawn,
    ),
    (
        "Native movement integrators and collision are address-pinned",
        test_native_movement_integrators_and_collision_are_address_pinned,
    ),
    (
        "Native tick graph reconciles simulation and service cadences",
        test_native_tick_graph_reconciles_simulation_and_service_cadences,
    ),
    (
        "Movement goldens have clean live provenance and schema",
        test_movement_golden_provenance_and_schema_are_live_recorded,
    ),
    (
        "Movement goldens pin normalization, wall response, and Knockback",
        test_movement_golden_traces_pin_normalization_slide_stop_and_knockback,
    ),
    (
        "Native RNG float primitive rounds to float32 at three points",
        test_native_rng_float_primitive_rounds_at_three_points,
    ),
    (
        "Native RNG float primitive reaches both range endpoints",
        test_native_rng_float_primitive_reaches_both_endpoints,
    ),
    (
        "Native float RNG goldens have exact provenance and capture census",
        test_native_float_rng_golden_provenance_and_capture_census_are_pinned,
    ),
    (
        "Native float RNG golden outputs replay bit-exact",
        test_native_float_rng_golden_outputs_replay_bit_exact,
    ),
    (
        "Native float RNG signed draws consume two stream words",
        test_native_float_rng_signed_draws_consume_two_stream_words,
    ),
    (
        "Native float RNG divisor is object-local at this+0xE4",
        test_native_float_rng_divisor_is_object_local_at_e4,
    ),
    (
        "Native float RNG capture seam is opt-in and fail-closed",
        test_native_float_rng_capture_seam_is_opt_in_runnable_and_fail_closed,
    ),
    (
        "Native RNG goldens replay the exact retail recurrence",
        test_native_rng_golden_replays_exact_retail_recurrence,
    ),
    (
        "Native RNG ownership and gameplay call-site census are pinned",
        test_native_rng_stream_ownership_and_callsite_census_are_pinned,
    ),
    (
        "Native sim recorder seam is bounded, isolated, and registered",
        test_native_sim_recorder_seam_is_bounded_isolated_and_registered,
    ),
    (
        "Recorded run seed is App-tick derived, not wall-clock",
        test_recorded_run_seed_is_app_tick_derived_not_wall_clock,
    ),
    (
        "App-tick seeding provenance is documented and byte-verified",
        test_app_tick_seeding_provenance_is_documented_and_byte_verified,
    ),
    (
        "Lua bot player docs and acceptance surface are pinned",
        test_lua_bot_player_docs_and_acceptance_surface,
    ),
    (
        "Transport telemetry names slow app-thread stages",
        test_transport_telemetry_names_slow_app_thread_stages,
    ),
    (
        "WSL Steam launcher isolates build artifacts from the live host",
        test_wsl_steam_launcher_isolates_build_artifacts_from_live_host,
    ),
    (
        "Authoritative life correction uses the recipient native maximum",
        test_authoritative_life_correction_uses_the_recipient_native_maximum,
    ),
    (
        "WAN death presentation is a convergent transaction",
        test_wan_death_presentation_is_a_convergent_transaction,
    ),
    (
        "asynchronous logger keeps blocking output off callers",
        test_async_logger_keeps_blocking_output_off_callers,
    ),
    (
        "dead multiplayer participants are authority inert",
        test_dead_multiplayer_participants_are_authority_inert,
    ),
    (
        "local UDP ingress and wire framing are bounded",
        test_local_udp_ingress_and_wire_framing_are_bounded,
    ),
    (
        "dead owner vitals are reasserted after the progression tick",
        test_dead_owner_vitals_are_reasserted_after_the_progression_tick,
    ),
    (
        "Proton input targets the exact native game window",
        test_proton_input_targets_the_exact_native_game_window,
    ),
    (
        "Steam behavior arena reset waits for the native spawner",
        test_steam_behavior_arena_reset_waits_for_native_spawner,
    ),
    (
        "Steam friend native inventory matrix is wired",
        test_steam_friend_native_inventory_matrix_is_wired,
    ),
    (
        "Native save container codec and layout are pinned",
        test_native_save_container_codec_and_layout_are_pinned,
    ),
    (
        "Native save goldens round-trip every committed file",
        test_native_save_goldens_round_trip_all_committed_files,
    ),
    (
        "Native Memoratorium FIFO profile fields are named and closed",
        test_native_memoratorium_fifo_profile_fields_are_named_and_closed,
    ),
    (
        "Native save document node and payload tables are exact",
        test_native_save_document_node_and_payload_tables_are_exact,
    ),
    (
        "Native save fresh defaults and runtime offsets are pinned",
        test_native_save_fresh_defaults_and_runtime_offsets_are_pinned,
    ),
    (
        "Native save recorder is self-provenanced, settled, bounded, and owned",
        test_native_save_recorder_is_self_provenanced_settled_bounded_and_owned,
    ),
    (
        "Native save lifecycle and failure semantics are pinned",
        test_native_save_lifecycle_and_failure_semantics_are_pinned,
    ),
    (
        "Launcher save layer and account seam are pinned",
        test_launcher_save_layer_and_account_seam_are_pinned,
    ),
    (
        "Native active wizard, saved run, and tutorial boundaries are pinned",
        test_native_active_wizard_saved_run_and_tutorial_boundaries_are_pinned,
    ),
    (
        "Native save fixture provenance hashes the committed recording",
        test_native_save_fixture_provenance_hashes_the_committed_recording,
    ),
]

# The only contracts CI cannot run, because each one reads an artifact that is
# not in the repository: the retail binary, which lives outside the checkout and
# is not ours to redistribute, or a Ghidra/stage output under the gitignored
# `runtime/` tree. Everything else runs on every push -- see
# `run_static_re_tests.py --ci` and
# `test_ci_runs_every_contract_that_needs_no_local_artifact`, which refuses a
# name that is parked here without actually reading such an artifact.
LOCAL_ARTIFACT_TESTS: dict[str, str] = {
    "Raptisoft close URL call is runtime NOPed": "retail binary",
    "stock audio bootstrap and settings are layout-backed": "retail binary",
    "native D3D device lifetime outlives stock teardown": "retail binary",
    "staged binary matches analysis binary": "runtime/stage/SolomonDark.exe",
    "binary layout identity is staged": "runtime/stage layout identity",
    "native stat refresh preserves live vitals": "runtime/ghidra_primary_spell_builder_resource_paths.txt",
    "Synthetic source-profile native blocker is documented": "runtime/ghidra_source_profile_negative_producer_scan.txt",
    "Default ally HP native constructor evidence is recorded": "runtime/ghidra_ally_hp_progression_paths.txt",
    "Enemy spawn scaling native wave seam is documented": "runtime/ghidra_enemy_wave_spawn_paths.txt",
    "Pathfinding movement layout is named and documented": "runtime/ghidra_pathfinding_movement_paths.txt",
    "Player/GameNpc movement seed layout is named and documented": "runtime/ghidra_player_gamenpc_movement_seed_paths.txt",
    "Participant collision resolver is documented and live-probed": "runtime/ghidra_standalone_collision_registration_paths.txt",
    "Cast-state native contracts are documented and layout-backed": "runtime/ghidra_stock_tick_slot_shim_cast_paths.txt",
}
