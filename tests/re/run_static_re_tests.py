#!/usr/bin/env python3
"""Static RE regression checks for native gameplay seams.

These tests keep the reverse-engineering cleanup honest: verified hardcoded
tables must stay removed, known workaround-heavy files must remain inventoried,
and the staged binary/layout must match the game binary used for analysis.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from static_multiplayer_runtime_contracts import (
    read_source_unit,
    test_app_thread_transport_verifier_tracks_named_cadence_gap,
    test_active_steam_behavior_harnesses_preserve_fixture_state,
    test_staff_target_selection_skips_local_only_enemies,
    test_client_loot_pickup_requests_are_single_flight_per_drop,
    test_client_replicated_enemy_movement_is_host_authored,
    test_scene_tick_keeps_dead_remote_participants_inert,
    test_cpu_tick_stops_after_virtual_update_marks_object_for_removal,
    test_hub_students_remain_in_the_stock_transient_lifecycle,
    test_run_enemy_materialization_preserves_exact_native_type,
    test_run_enemy_death_tombstones_precede_structural_omission,
    test_empty_run_snapshot_unregisters_stale_enemies_without_parking,
    test_explicit_blank_boneyard_removes_native_scenery_and_collision,
    test_frozen_manual_enemy_cell_membership_stays_position_coherent,
    test_host_run_exit_is_authoritative_and_self_correcting,
    test_loot_deactivation_uses_stock_deferred_retirement,
    test_health_up_contract_composes_with_life_charm,
    test_mana_up_contract_replaces_the_initial_rank_bonus,
    test_world_stale_hold_controls_the_exact_remote_host_process,
    test_hub_presentation_uses_stored_authority_across_lifecycle_rotation,
    test_hub_services_use_typed_native_lua_dispatch,
    test_level_up_barrier_waits_for_forced_picker_confirmation,
    test_level_up_choice_result_advances_owned_book_before_resume,
    test_loot_materialization_waits_for_native_field_convergence,
    test_mana_recovery_tolerance_respects_float32_precision,
    test_mana_recovery_precondition_holds_zero_until_replication,
    test_manual_primary_target_survives_stock_cursor_refresh,
    test_exact_native_equipment_identity_and_color_replicate,
    test_native_local_player_keeps_stock_input_and_equipment_ownership,
    test_lua_exec_timeout_cancels_pending_work,
    test_remote_windows_lua_bridge_is_persistent_and_framed,
    test_meditation_transient_counters_self_repair_to_native_bounds,
    test_native_item_pickup_converges_into_stock_inventory,
    test_native_item_recipe_selection_excludes_equipped_items,
    test_natural_offer_expectation_clamps_to_native_maximum,
    test_native_remote_fireball_retains_cast_heading_until_projectile_birth,
    test_native_unregister_retires_address_bound_network_identity,
    test_new_run_retires_the_prior_host_run_exit_latch,
    test_orb_pickup_verifier_preserves_native_maxima,
    test_primary_spell_effect_snapshots_do_not_fight_native_replay,
    test_powerup_rewards_are_authoritative_and_native,
    test_poison_correction_ack_waits_for_native_application,
    test_primary_kill_stress_resumes_only_a_contiguous_passed_prefix,
    test_primary_kill_stress_accepts_a_late_death_from_the_prior_cast,
    test_animated_loot_comparison_bounds_snapshot_phase_skew,
    test_packaged_ui_accepts_single_file_launcher,
    test_packaged_ui_does_not_inherit_test_world_overrides,
    test_launcher_auto_accepts_steam_invites_and_hub_gates_discovery,
    test_pair_launcher_drains_redirected_json_output,
    test_pointer_list_batch_rejects_stale_managed_release_callbacks,
    test_reconnect_verifier_has_a_dedicated_cold_launch_timeout,
    test_progression_matrices_prearm_quiet_spawning_before_run_entry,
    test_secondary_behavior_matrix_uses_native_two_owner_witnesses,
    test_spell_verifiers_quiesce_input_and_prearm_manual_spawning,
    test_snapshot_streams_are_compact_and_bandwidth_bounded,
    test_steam_client_reauthentication_preserves_live_message_session,
    test_steam_onboarding_waits_out_blocking_dialogs_and_scene_churn,
    test_steam_pair_recovers_lobby_membership_and_requires_stable_readiness,
    test_steam_friend_active_run_reconnect_is_wired,
    test_stat_matrix_waits_for_expected_derived_contract,
    test_unreliable_snapshot_ordering_is_wrap_safe,
)


ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

CASTING_API = ROOT / "SolomonDarkModLoader/src/bot_runtime/public_api/casting_api.inl"
BOT_RUNTIME_HEADER = ROOT / "SolomonDarkModLoader/include/bot_runtime.h"
BOT_RUNTIME_DEFAULTS_AND_LOOKUP = (
    ROOT / "SolomonDarkModLoader/src/bot_runtime/helpers/defaults_and_lookup.inl"
)
BOT_RUNTIME_LIFECYCLE_API = (
    ROOT / "SolomonDarkModLoader/src/bot_runtime/public_api/lifecycle_api.inl"
)
BOT_RUNTIME_SNAPSHOTS_API = (
    ROOT / "SolomonDarkModLoader/src/bot_runtime/public_api/snapshots_api.inl"
)
RESOURCE_STATE = ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/resource_state.inl"
PENDING_CAST_PREPARATION = (
    ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/pending_cast_preparation.inl"
)
PENDING_CAST_PROCESSING = (
    ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/pending_cast_processing.inl"
)
CAST_RELEASE_HELPERS = (
    ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/release_and_latch_helpers.inl"
)
BOT_SNAPSHOT_BUILDERS = (
    ROOT / "SolomonDarkModLoader/src/bot_runtime/helpers/snapshot_builders.inl"
)
SKILL_SELECTION_RULES = (
    ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/skill_selection_rules.inl"
)
BOULDER_PROJECTION = (
    ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/boulder_damage_projection.inl"
)
NATIVE_SPELL_STATS_HEADER = ROOT / "SolomonDarkModLoader/include/native_spell_stats.h"
NATIVE_SPELL_STATS_CPP = ROOT / "SolomonDarkModLoader/src/native_spell_stats.cpp"
NATIVE_SPELL_STATS_DIR = ROOT / "SolomonDarkModLoader/src/native_spell_stats"
LUA_ENGINE_BOTS_BINDING = ROOT / "SolomonDarkModLoader/src/lua_engine_bindings_bots.cpp"
LUA_ENGINE_PARSER_SNAPSHOTS = ROOT / "SolomonDarkModLoader/src/lua_engine_parser_snapshots.cpp"
NATIVE_STATBOOKS_HEADER = ROOT / "SolomonDarkModLoader/include/native_statbooks.h"
NATIVE_STATBOOKS_CPP = ROOT / "SolomonDarkModLoader/src/native_statbooks.cpp"
MOD_LOADER_PROJECT = ROOT / "SolomonDarkModLoader/SolomonDarkModLoader.vcxproj"
MOD_LOADER_PROJECT_FILTERS = ROOT / "SolomonDarkModLoader/SolomonDarkModLoader.vcxproj.filters"
MULTIPLAYER_PROTOCOL = ROOT / "SolomonDarkModLoader/include/multiplayer_runtime_protocol.h"
MULTIPLAYER_RUNTIME_STATE = ROOT / "SolomonDarkModLoader/include/multiplayer_runtime_state.h"
MULTIPLAYER_LOCAL_TRANSPORT = ROOT / "SolomonDarkModLoader/src/multiplayer_local_transport.cpp"
MULTIPLAYER_LOCAL_TRANSPORT_HEADER = ROOT / "SolomonDarkModLoader/include/multiplayer_local_transport.h"
WORLD_SNAPSHOT_FRAGMENTATION = (
    ROOT
    / "SolomonDarkModLoader/src/multiplayer_local_transport/world_snapshot_fragmentation.inl"
)
MULTIPLAYER_SERVICE_LOOP = ROOT / "SolomonDarkModLoader/src/multiplayer_service_loop.cpp"
NATIVE_ENEMY_LIFECYCLE_HEADER = ROOT / "SolomonDarkModLoader/include/native_enemy_lifecycle.h"
NATIVE_ENEMY_LIFECYCLE = ROOT / "SolomonDarkModLoader/src/native_enemy_lifecycle.cpp"
WORLD_SNAPSHOT_RECONCILIATION = (
    ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/world_snapshot_reconciliation.inl"
)
LUA_EXEC_PIPE = ROOT / "SolomonDarkModLoader/src/lua_exec_pipe.cpp"
STAGED_GAME_LAUNCHER = ROOT / "SolomonDarkModLauncher/src/Launch/StagedGameLauncher.cs"
MOD_LOADER_HEADER = ROOT / "SolomonDarkModLoader/include/mod_loader.h"
MOD_LOADER_GAMEPLAY = ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay.cpp"
MEMORY_ACCESS_REGIONS = ROOT / "SolomonDarkModLoader/src/memory_access_regions.cpp"
MEMORY_ACCESS_HEADER = ROOT / "SolomonDarkModLoader/include/memory_access.h"
RUNTIME_DEBUG_CORE = ROOT / "SolomonDarkModLoader/src/runtime_debug_core.cpp"
RUNTIME_DEBUG_WATCH = ROOT / "SolomonDarkModLoader/src/runtime_debug_watch.cpp"
RUNTIME_DEBUG_WATCH_HELPERS = (
    ROOT / "SolomonDarkModLoader/src/runtime_debug_watch_helpers.cpp"
)
RUNTIME_DEBUG_WATCH_MANAGEMENT = (
    ROOT / "SolomonDarkModLoader/src/runtime_debug_watch_management.cpp"
)
RUNTIME_DEBUG_WATCH_REGISTRATION = (
    ROOT / "SolomonDarkModLoader/src/runtime_debug_watch_registration.cpp"
)
PARTICIPANT_ENTITY_SYNC = (
    ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/execute_requests/participant_entity_sync.inl"
)
PARTICIPANT_SCENE_BINDING_TICKS = (
    ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_movement_tick/participant_scene_binding_ticks.inl"
)
NETWORKING_DOC = ROOT / "docs/networking/README.md"
WORLD_SYNC_AUTHORITY_PLAN_DOC = ROOT / "docs/networking/world-sync-authority-plan.md"
MULTIPLAYER_PARTICIPANT_MODEL_DOC = ROOT / "docs/multiplayer-participant-model.md"
LOCAL_MULTIPLAYER_PAIR_SCRIPT = ROOT / "scripts/Launch-LocalMultiplayerPair.ps1"
LOCAL_MULTIPLAYER_SYNC_VERIFIER = ROOT / "tools/verify_local_multiplayer_sync.py"
RUN_WORLD_SNAPSHOT_VERIFIER = ROOT / "tools/verify_run_world_snapshot.py"
ENEMY_DAMAGE_CLAIM_SYNC_VERIFIER = ROOT / "tools/verify_enemy_damage_claim_sync.py"
RUN_STATIC_LAYOUT_SYNC_VERIFIER = ROOT / "tools/verify_run_static_layout_sync.py"
PLAYER_HEALTH_DEATH_SYNC_VERIFIER = ROOT / "tools/verify_player_health_death_sync.py"
MULTIPLAYER_HUD_NAMES_VERIFIER = ROOT / "tools/verify_multiplayer_hud_names.py"
STEAM_FRIEND_HUB_VISUALS_VERIFIER = (
    ROOT / "tools/verify_steam_friend_hub_visuals.py"
)
STEAM_FRIEND_ACTIVE_PAIR_VISUALS_VERIFIER = (
    ROOT / "tools/verify_steam_friend_active_pair_visuals.py"
)
HUD_LABEL_ASSET_MATERIALIZER = (
    ROOT / "SolomonDarkModLauncher/src/Staging/HudLabelAssetMaterializer.cs"
)
REAL_INPUT_SPELL_CAST_SYNC_VERIFIER = ROOT / "tools/verify_real_input_spell_cast_sync.py"
PRIMARY_KILL_STRESS_VERIFIER = ROOT / "tools/verify_multiplayer_primary_kill_stress.py"
TARGETED_SPELL_MATRIX_VERIFIER = ROOT / "tools/verify_multiplayer_targeted_spell_matrix.py"
RUN_LIFECYCLE_SPELL_CAST_HOOKS = (
    ROOT / "SolomonDarkModLoader/src/run_lifecycle/spell_cast_hooks.inl"
)
RUN_ENEMY_SEED_VERIFIER = ROOT / "tools/verify_run_enemy_seed_viability.py"
RUN_ENEMY_PRESENTATION_PROBE = ROOT / "tools/probe_run_enemy_presentation_sync.py"
RUN_REWARD_SYNC_PROBE = ROOT / "tools/probe_run_reward_sync.py"
GAMEPLAY_HUD_HOOKS = (
    ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/gameplay_hud_hooks.inl"
)
GAMEPLAY_PUBLIC_STATE_GETTERS = (
    ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_state_getters.inl"
)
DEBUG_UI_OVERLAY_FRAME_RENDER = (
    ROOT / "SolomonDarkModLoader/src/debug_ui_overlay/label_resolution_surface_registry_and_frame_render.inl"
)
DEBUG_UI_OVERLAY_HEADER = ROOT / "SolomonDarkModLoader/include/debug_ui_overlay.h"
DEBUG_UI_OVERLAY_PUBLIC_SURFACE = (
    ROOT / "SolomonDarkModLoader/src/debug_ui_overlay/public_api_surface_dispatch.inl"
)
SCENE_SELECTION = (
    ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/scene_and_animation_bot_priming_and_selection.inl"
)
SCENE_ANIMATION_DRIVE_PROFILES = (
    ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/scene_and_animation_drive_profiles.inl"
)
BOT_PATHFINDING_PATH_BUILDING = (
    ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_pathfinding_path_building.inl"
)
BOT_PATHFINDING_TRAVERSABILITY = (
    ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_pathfinding_traversability.inl"
)
STANDALONE_CLONE_SOURCE = (
    ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/standalone_materialization_wizard_clone_source.inl"
)
SPAWN_STANDALONE_WIZARD = (
    ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/execute_requests/spawn_standalone_wizard.inl"
)
BOT_REGISTRY_AND_MOVEMENT_SPAWN = (
    ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_registry_and_movement_spawn_and_modifiers.inl"
)
NATIVE_SEAM_PLAN = ROOT / "docs/native-seam-re-plan.md"
ACCEPTED_NATIVE_SHIMS_DOC = ROOT / "docs/accepted-native-shims.md"
SOURCE_PROFILE_RE_DOC = ROOT / "docs/native-source-profile-re.md"
ALLY_HP_RE_DOC = ROOT / "docs/native-ally-hp-re.md"
WAVE_SCALING_RE_DOC = ROOT / "docs/wave-scaling-re.md"
PATHFINDING_RE_DOC = ROOT / "docs/pathfinding-investigation.md"
GAMEPLAY_CONSTANTS = ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/gameplay_constants.inl"
PLAYER_CAST_HOOKS = ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/player_cast_hooks.inl"
PLAYER_CAST_HOOKS_EFFECT_AND_DISPATCH = (
    ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/player_cast_hooks_effect_and_dispatch.inl"
)
PLAYER_ACTOR_TICK_HOOK = (
    ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/actor_tick/player_actor_tick_hook.inl"
)
SCENE_ANIMATION_GAMEPLAY_STATE = (
    ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/scene_and_animation_gameplay_state.inl"
)
PUBLIC_API_DEBUG_AND_SPAWN = (
    ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_debug_and_spawn.inl"
)
CAST_PROBE_STATE = (
    ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/cast_probe_state.inl"
)
ACTOR_ANIMATION_ADVANCE_HOOK = (
    ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/actor_tick/animation_advance_hook.inl"
)
GAMEPLAY_KEYBOARD_INJECTION = (
    ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_keyboard_injection.inl"
)
GAMEPLAY_NATIVE_FUNCTION_TYPES = (
    ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/native_function_types.inl"
)
STANDALONE_DEBUG_SUMMARIES = (
    ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/standalone_materialization_debug_summaries.inl"
)
STANDALONE_SLOT_BOT_CREATION = (
    ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/standalone_materialization_slot_bot_creation.inl"
)
STANDALONE_SELECTION_PRIMING = (
    ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/standalone_materialization_selection_priming.inl"
)
STANDALONE_EQUIP_VISUAL_LANES = (
    ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/standalone_materialization_equip_visual_lanes.inl"
)
DISPATCH_REQUEST_QUEUES = (
    ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_request_queues.inl"
)
DISPATCH_PUMP_LOOP = (
    ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_pump_loop.inl"
)
BINARY_LAYOUT = ROOT / "config/binary-layout.ini"
STAGED_BINARY_LAYOUT = ROOT / "runtime/stage/.sdmod/config/binary-layout.ini"
STAGED_BINARY = ROOT / "runtime/stage/SolomonDark.exe"
ABANDONWARE_BINARY = ROOT.parent / "SolomonDarkAbandonware/SolomonDark.exe"
ALLY_HP_PROGRESS_GHIDRA = ROOT / "runtime/ghidra_ally_hp_progression_paths.txt"
ALLY_HP_RECOMPUTE_GHIDRA = ROOT / "runtime/ghidra_ally_hp_recompute_candidate.txt"
PRIMARY_SPELL_BUILDER_GHIDRA = ROOT / "runtime/ghidra_primary_spell_builder_resource_paths.txt"
SYNTHETIC_SOURCE_PROFILE_GHIDRA = ROOT / "runtime/ghidra_synthetic_source_profile_paths.txt"
SOURCE_PROFILE_NEGATIVE_GHIDRA = ROOT / "runtime/ghidra_source_profile_negative_producer_scan.txt"
SOURCE_PROFILE_ACTOR174_EXPANDED_GHIDRA = ROOT / "runtime/ghidra_source_profile_actor174_expanded_scan.txt"
SOURCE_PROFILE_FIELD_CANDIDATE_GHIDRA = ROOT / "runtime/ghidra_source_profile_field_candidate_decompiles.txt"
SOURCE_PROFILE_WRITE_SITES_EXPANDED_GHIDRA = ROOT / "runtime/ghidra_source_profile_write_sites_expanded.txt"
SOURCE_PROFILE_NEGATIVE_LIVE_PROBE = ROOT / "tests/re/run_live_source_profile_negative_probe.py"
SOURCE_PROFILE_WRITER_LIVE_PROBE = ROOT / "tests/re/run_live_source_profile_writer_probe.py"
PURE_PRIMARY_STARTUP_LIVE_PROBE = ROOT / "tests/re/run_live_pure_primary_startup_probe.py"
PURE_PRIMARY_EQUIP_SINK_GHIDRA = ROOT / "runtime/ghidra_pure_primary_equip_sink_paths.txt"
BOT_MANA_TRACE_HELPERS = ROOT / "tests/re/bot_mana_trace_helpers.py"
BOT_MANA_WRITER_LIVE_PROBE = ROOT / "tests/re/run_live_bot_mana_writer_probe.py"
BOT_NATIVE_MANA_SPEND_LIVE_PROBE = ROOT / "tests/re/run_live_bot_native_mana_spend_probe.py"
BOT_SKILL_UPGRADE_COMBAT_FLOW_LIVE_PROBE = (
    ROOT / "tests/re/run_live_bot_skill_upgrade_combat_flow_probe.py"
)
BOT_UPGRADE_DAMAGE_DELTA_LIVE_PROBE = (
    ROOT / "tests/re/run_live_bot_upgrade_damage_delta_probe.py"
)
BOT_OUT_OF_MANA_REJECTION_LIVE_PROBE = (
    ROOT / "tests/re/run_live_bot_out_of_mana_rejection_probe.py"
)
BOT_ELEMENT_DAMAGE_PROBE = ROOT / "tools/probe_bot_element_damage.py"
BOULDER_RETARGET_LIVE_PROBE = ROOT / "tests/re/run_live_boulder_retarget_probe.py"
ENEMY_WAVE_GHIDRA = ROOT / "runtime/ghidra_enemy_wave_spawn_paths.txt"
ENEMY_SPAWN_CALL_SHAPES_GHIDRA = ROOT / "runtime/ghidra_enemy_spawn_call_shapes.txt"
ENEMY_SPAWN_API_REMOVED_LIVE_PROBE = ROOT / "tests/re/run_live_enemy_spawn_api_removed_probe.py"
PATHFINDING_MOVEMENT_GHIDRA = ROOT / "runtime/ghidra_pathfinding_movement_paths.txt"
PATHFINDING_POLICY_SCALARS_GHIDRA = ROOT / "runtime/ghidra_pathfinding_policy_scalar_scan.txt"
PATHFINDING_POLICY_SCALAR_DECOMPILE_GHIDRA = ROOT / "runtime/ghidra_pathfinding_policy_scalar_decompile.txt"
PATHFINDING_POLICY_FLOAT_GLOBALS_GHIDRA = ROOT / "runtime/ghidra_pathfinding_policy_float_globals.txt"
PATHFINDING_LAYOUT_LIVE_PROBE = ROOT / "tests/re/run_live_pathfinding_layout_probe.py"
PLAYER_GAMENPC_MOVEMENT_SEED_GHIDRA = ROOT / "runtime/ghidra_player_gamenpc_movement_seed_paths.txt"
PLAYER_GAMENPC_MOVEMENT_SEED_OFFSET_GHIDRA = (
    ROOT / "runtime/ghidra_player_gamenpc_movement_seed_offsets.txt"
)
STOCK_TICK_RESTORE_GHIDRA = ROOT / "runtime/ghidra_stock_tick_restore_paths.txt"
STOCK_TICK_OWNERSHIP_XREFS_GHIDRA = ROOT / "runtime/ghidra_stock_tick_ownership_xrefs.txt"
STOCK_TICK_INPUT_OFFSET_ACCESS_GHIDRA = ROOT / "runtime/ghidra_stock_tick_input_offset_accesses.txt"
STOCK_TICK_RESTORE_LIVE_PROBE = ROOT / "tests/re/run_live_stock_tick_restore_probe.py"
BOT_NATIVE_SPEED_LIVE_PROBE = ROOT / "tests/re/run_live_bot_native_speed_probe.py"
REGISTERED_GAMENPC_PUBLICATION_GHIDRA = (
    ROOT / "runtime/ghidra_registered_gamenpc_publication_blockers.txt"
)
REGISTERED_GAMENPC_PUBLICATION_XREFS_GHIDRA = (
    ROOT / "runtime/ghidra_registered_gamenpc_publication_xrefs.txt"
)
REGISTERED_GAMENPC_PUBLICATION_EXPANDED_GHIDRA = (
    ROOT / "runtime/ghidra_registered_gamenpc_publication_expanded.txt"
)
REGISTERED_GAMENPC_BLOCKER_LIVE_PROBE = (
    ROOT / "tests/re/run_live_registered_gamenpc_blocker_probe.py"
)
STANDALONE_COLLISION_REGISTRATION_GHIDRA = (
    ROOT / "runtime/ghidra_standalone_collision_registration_paths.txt"
)
STANDALONE_COLLISION_OVERLAP_GHIDRA = (
    ROOT / "runtime/ghidra_standalone_collision_overlap_builder_paths.txt"
)
STANDALONE_COLLISION_OWNERSHIP_XREFS_GHIDRA = (
    ROOT / "runtime/ghidra_standalone_collision_ownership_xrefs.txt"
)
STANDALONE_COLLISION_FIELD_WRITES_GHIDRA = (
    ROOT / "runtime/ghidra_standalone_collision_field_writes.txt"
)
STANDALONE_CLONE_INSTRUCTION_GHIDRA = (
    ROOT / "runtime/ghidra_wizard_clone_from_source_instructions.txt"
)
CAST_STATE_GHIDRA = ROOT / "runtime/ghidra_stock_tick_slot_shim_cast_paths.txt"
CAST_STATE_OFFSETS_GHIDRA = ROOT / "runtime/ghidra_cast_state_offsets.txt"
CAST_SPELL_OBJECT_GHIDRA = ROOT / "runtime/ghidra_cast_spell_object_handlers.txt"
CAST_SLOT0_DISPATCH_XREFS_GHIDRA = ROOT / "runtime/ghidra_cast_slot0_dispatch_xrefs.txt"
CAST_SLOT0_GATE_OFFSET_ACCESS_GHIDRA = ROOT / "runtime/ghidra_cast_slot0_gate_offset_accesses.txt"
CAST_SELECTION_LIFECYCLE_XREFS_GHIDRA = ROOT / "runtime/ghidra_selection_lifecycle_xrefs.txt"
CAST_SELECTION_CLEANUP_TARGETS_GHIDRA = ROOT / "runtime/ghidra_selection_and_cleanup_targets.txt"
CAST_SELECTION_BRAIN_OFFSET_ACCESS_GHIDRA = (
    ROOT / "runtime/ghidra_selection_brain_offset_accesses.txt"
)
CAST_ACTIVE_SPELL_LIFECYCLE_XREFS_GHIDRA = (
    ROOT / "runtime/ghidra_active_spell_lifecycle_xrefs.txt"
)
CAST_LATCH_OFFSET_ACCESS_GHIDRA = ROOT / "runtime/ghidra_cast_latch_offset_accesses.txt"
CAST_BOULDER_VTABLE_GHIDRA = ROOT / "runtime/ghidra_boulder_spell_object_vtable_slots.txt"
LUA_BOT_CONFIG = ROOT / "mods/lua_bots/scripts/lib/lua_bots/config.lua"
LUA_BOT_COMBAT = ROOT / "mods/lua_bots/scripts/lib/lua_bots/combat.lua"
LUA_BOT_FOLLOW = ROOT / "mods/lua_bots/scripts/lib/lua_bots/follow.lua"
LUA_BOT_STATE = ROOT / "mods/lua_bots/scripts/lib/lua_bots/state.lua"
LUA_BOT_TRAVEL = ROOT / "mods/lua_bots/scripts/lib/lua_bots/travel.lua"
LUA_BOT_CONSTANTS_RE_DOC = ROOT / "docs/lua-bot-constants-re.md"
LUA_BOT_ENEMY_SEMANTIC_LIVE_PROBE = ROOT / "tests/re/run_live_lua_bot_enemy_semantic_probe.py"
PROVE_LUA_FOLLOW = ROOT / "tools/prove_lua_follow.py"
NATIVE_WIZARD_DEFAULT_HP_GLOBAL_KEY = "wizard_default_hp"
NATIVE_WIZARD_DEFAULT_MP_GLOBAL_KEY = "wizard_default_mp"


SMELL_SOURCES = {}

CORRECTED_SMELL_GUARDS = {
    "slot-0 cast shim": (
        (
            ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_actor_calls/local_player_cast_shim.inl",
        ),
        (
            "EnterLocalPlayerCastShim",
            "InvokeBotCastWithLocalPlayerSlot",
            "requires_local_slot_native_tick",
        ),
    ),
    "manual skill selection fallback": (
        (),
        (
            "ResolveCombatSelectionStateForSkillId",
            "SkillRequiresLocalSlotDuringNativeTick",
        ),
    ),
    "manual active spell bucket/vtable snapshot": (
        (
            ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/active_spell_snapshot.inl",
        ),
        (
            "ReadBotActiveSpellObjectSnapshot",
            "BotActiveSpellObjectSnapshot",
            "active_spell_snapshot.object",
            "obj_vt",
        ),
    ),
    "active handle fallback cleanup": (
        (),
        (
            "ReleaseBotSpellHandle",
            "directly so the next cast",
        ),
    ),
    "lua bot smell constants": (
        (),
        (
            "WATER_BASE_CONE_RANGE",
            "SUPPORTED_PRIVATE_AREAS",
        ),
    ),
    "pure-primary local equip sink shim": (
        (),
        (
            "PurePrimaryLocalActorWindowShim",
            "EnterPurePrimaryLocalActorWindow",
            "LeavePurePrimaryLocalActorWindow",
            "apply_local_selection_shim",
            "pure_primary_slot_item_shim",
            "pure_primary_item_sink_fallback",
            "local_sel_shim",
            "local_window_shim",
            "slot_item_shim",
            "HookEquipAttachmentSinkGetCurrentItem",
            "equip_attachment_get_current_item_hook",
            "fallback_result",
        ),
    ),
}


INVESTIGATION_REGISTER_COVERAGE = {
    "Primary mana costs": ("test:primary mana resolver uses native live spell stats",),
    "Primary build-skill mapping": ("test:primary build skill mapping has single runtime owner",),
    "Manual mana spend": ("test:bot mana spend is stock-owned through native gate patch",),
    "Earth boulder damage": (
        "test:Earth boulder damage uses native live spell stats",
        "test:Earth boulder projection stays read-only and drives target-lethal release",
        "test:Earth boulder held charge tracks live target until release",
        "test:Earth boulder live retarget probe is documented",
    ),
    "Synthetic source profiles": (
        "test:Synthetic source-profile native blocker is documented",
    ),
    "Default ally HP": (
        "test:Default ally HP native constructor evidence is recorded",
        "test:Default ally HP spawn paths preserve native defaults",
    ),
    "Enemy spawn call shape": (
        "test:Enemy spawn scaling native wave seam is documented",
    ),
    "Pathfinding policy": ("test:Pathfinding movement layout is named and documented",),
    "Registered GameNpc movement": (
        "test:Player/GameNpc movement seed layout is named and documented",
    ),
    "PlayerActor movement seeds": (
        "test:Player/GameNpc movement seed layout is named and documented",
        "test:Bot movement speed uses native live envelope",
    ),
    "Standalone collision": (
        "test:Participant collision resolver is documented and live-probed",
    ),
    "Stock tick position restore": (
        "test:Player/GameNpc movement seed layout is named and documented",
    ),
    "Slot-0 cast shim": (
        "test:Cast-state native contracts are documented and layout-backed",
    ),
    "Pure-primary equip sink": (
        "test:Cast-state native contracts are documented and layout-backed",
    ),
    "Skill selection state": (
        "test:Cast-state native contracts are documented and layout-backed",
    ),
    "Active spell object lookup": (
        "test:Cast-state native contracts are documented and layout-backed",
    ),
    "Cast latch cleanup": (
        "test:Cast-state native contracts are documented and layout-backed",
    ),
    "Lua bot constants": (
        "test:Lua bot constants are semantic or documented",
    ),
    "Skill choice constants": (
        "test:bot level sync uses native level_up",
        "test:residual probe and skill-choice offsets are layout-backed",
        "test:Remaining native addresses and probe offsets are layout-backed",
    ),
    "Probe script constants": (
        "test:residual probe and skill-choice offsets are layout-backed",
        "test:second residual runtime offsets and trace addresses are layout-backed",
        "test:Remaining native addresses and probe offsets are layout-backed",
    ),
}


class StaticReTestFailure(AssertionError):
    pass


@dataclass(frozen=True)
class TestResult:
    name: str
    passed: bool
    detail: str


def read_text(path: Path) -> str:
    if not path.exists():
        raise StaticReTestFailure(f"missing file: {path.relative_to(ROOT)}")
    return path.read_text(encoding="utf-8", errors="replace")


def read_multiplayer_transport_source() -> str:
    """Read the transport coordinator and its behavior-domain includes."""
    domain_dir = MULTIPLAYER_LOCAL_TRANSPORT.parent / "multiplayer_local_transport"
    paths = (MULTIPLAYER_LOCAL_TRANSPORT, *sorted(domain_dir.glob("*.inl")))
    return "\n".join(read_text(path) for path in paths)


def read_native_spell_stats_source() -> str:
    paths = (NATIVE_SPELL_STATS_CPP, *sorted(NATIVE_SPELL_STATS_DIR.glob("*.inl")))
    return "\n".join(read_text(path) for path in paths)


def read_player_cast_hooks_source() -> str:
    return "\n".join(
        read_text(path)
        for path in (PLAYER_CAST_HOOKS, PLAYER_CAST_HOOKS_EFFECT_AND_DISPATCH)
    )


def read_bot_skill_choice_source() -> str:
    paths = (
        ROOT / "SolomonDarkModLoader/src/bot_runtime/helpers/skill_choices.inl",
        ROOT / "SolomonDarkModLoader/src/bot_runtime/helpers/skill_choice_level_sync.inl",
    )
    return "\n".join(read_text(path) for path in paths)


def read_multiplayer_runtime_state_source() -> str:
    paths = (
        MULTIPLAYER_RUNTIME_STATE,
        ROOT / "SolomonDarkModLoader/include/multiplayer_runtime_effect_state.inl",
    )
    return "\n".join(read_source_unit(path) for path in paths)


def read_mod_loader_header_source() -> str:
    paths = (
        MOD_LOADER_HEADER,
        ROOT / "SolomonDarkModLoader/include/mod_loader_gameplay_api.inl",
    )
    return "\n".join(read_source_unit(path) for path in paths)


def read_gameplay_seams_header_source() -> str:
    paths = (
        ROOT / "SolomonDarkModLoader/src/gameplay_seams.h",
        ROOT / "SolomonDarkModLoader/src/gameplay_seams/progression_and_actor_offsets.inl",
    )
    return "\n".join(read_text(path) for path in paths)


def read_lua_runtime_source() -> str:
    coordinator = ROOT / "SolomonDarkModLoader/src/lua_engine_bindings_runtime.cpp"
    domain_dir = ROOT / "SolomonDarkModLoader/src/lua_engine_bindings_runtime"
    paths = (coordinator, *sorted(domain_dir.glob("*.inl")))
    return "\n".join(read_text(path) for path in paths)


def read_layout_numeric(path: Path, key_name: str) -> int:
    text = read_text(path)
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", ";")) or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == key_name:
            return int(value.strip(), 0)
    raise StaticReTestFailure(f"layout missing {key_name!r} in {path.relative_to(ROOT)}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_pe_float_by_va(path: Path, virtual_address: int) -> float:
    data = path.read_bytes()
    if len(data) < 0x40 or data[:2] != b"MZ":
        raise StaticReTestFailure(f"not a PE image: {path.relative_to(ROOT)}")
    pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe_offset:pe_offset + 4] != b"PE\0\0":
        raise StaticReTestFailure(f"missing PE signature: {path.relative_to(ROOT)}")
    number_of_sections = struct.unpack_from("<H", data, pe_offset + 6)[0]
    optional_header_size = struct.unpack_from("<H", data, pe_offset + 20)[0]
    optional_header = pe_offset + 24
    image_base = struct.unpack_from("<I", data, optional_header + 28)[0]
    rva = virtual_address - image_base
    section_offset = optional_header + optional_header_size
    for section_index in range(number_of_sections):
        header = section_offset + section_index * 40
        virtual_size, section_rva, raw_size, raw_offset = struct.unpack_from("<IIII", data, header + 8)
        section_size = max(virtual_size, raw_size)
        if section_rva <= rva < section_rva + section_size:
            file_offset = raw_offset + (rva - section_rva)
            return struct.unpack_from("<f", data, file_offset)[0]
    raise StaticReTestFailure(
        f"virtual address 0x{virtual_address:X} is not mapped by PE sections in {path.relative_to(ROOT)}"
    )


def test_primary_mana_resolver_uses_native_live_spell_stats() -> str:
    casting_text = read_text(CASTING_API)
    helper_header_text = read_text(NATIVE_SPELL_STATS_HEADER)
    helper_cpp_text = read_native_spell_stats_source()
    project_text = read_text(MOD_LOADER_PROJECT)
    filters_text = read_text(MOD_LOADER_PROJECT_FILTERS)
    layout_text = read_text(BINARY_LAYOUT)
    combined_text = "\n".join((casting_text, helper_header_text, helper_cpp_text, project_text, filters_text))

    forbidden_tokens = (
        "kFireMana",
        "kWaterMana",
        "kEarthMana",
        "kAirMana",
        "kEtherMana",
        "kPrimaryManaTables",
        "TryGetWizardSkillFloatValue",
        "native_statbooks",
        "fireball.cfg",
        "frost_jet.cfg",
        "boulder.cfg",
        "lightning.cfg",
        "magic_missile.cfg",
    )
    present_forbidden = [token for token in forbidden_tokens if token in combined_text]
    if present_forbidden:
        raise StaticReTestFailure(
            "primary mana resolution still references staged or hardcoded stat data: " +
            ", ".join(present_forbidden))

    lingering_files = [
        str(path.relative_to(ROOT)) for path in (NATIVE_STATBOOKS_HEADER, NATIVE_STATBOOKS_CPP)
        if path.exists()
    ]
    if lingering_files:
        raise StaticReTestFailure(
            "staged statbook resolver file(s) still exist: " + ", ".join(lingering_files))

    required_helper_tokens = (
        "SkillsWizardBuildPrimarySpellFn",
        "CallSkillsWizardBuildPrimarySpellSafe",
        "TryReadNativePrimaryStatOutputs",
        "TryResolveNativePrimarySpellStats",
        "NativePrimarySpellStats",
        "kProgressionPrimaryStatValuesOffset",
        "kProgressionPrimaryStatCountOffset",
        "kProgressionLevelOffset",
        "kProgressionCurrentSpellIdOffset",
    )
    missing_helper = [token for token in required_helper_tokens if token not in helper_cpp_text + helper_header_text]
    if missing_helper:
        raise StaticReTestFailure(
            "native primary spell stat helper is missing token(s): " +
            ", ".join(missing_helper))

    required_casting_tokens = (
        "uintptr_t progression_runtime_address",
        "TryResolveNativePrimarySelectionForProfile",
        "TryResolveNativePrimarySelectionFromSkillId",
        "TryResolveNativePrimarySpellStats",
        "progression_level",
        "mana_cost",
    )
    missing_casting = [token for token in required_casting_tokens if token not in casting_text]
    if missing_casting:
        raise StaticReTestFailure(
            "bot mana resolver is not wired to live progression/native spell stats: " +
            ", ".join(missing_casting))

    required_layout_tokens = (
        "progression_primary_stat_values=0x774",
        "progression_primary_stat_count=0x778",
    )
    missing_layout = [token for token in required_layout_tokens if token not in layout_text]
    if missing_layout:
        raise StaticReTestFailure(
            "binary layout is missing native primary stat output offset(s): " +
            ", ".join(missing_layout))

    return "primary mana resolver uses live Skills_Wizard primary stat outputs"


def test_earth_boulder_damage_uses_native_live_spell_stats() -> str:
    resource_text = read_text(RESOURCE_STATE)
    projection_text = read_text(BOULDER_PROJECTION)
    processing_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/pending_cast_processing.inl")
    active_object_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/native_active_spell_object_state.inl")
    release_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/release_and_latch_helpers.inl")
    entity_state_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/participant_entity_state.inl")
    layout_text = read_text(BINARY_LAYOUT)
    combined_text = "\n".join(
        (resource_text, projection_text, processing_text, active_object_text,
         release_text, entity_state_text, layout_text))

    forbidden_tokens = (
        "kEarthBoulderBaseDamageByLevel",
        "TryGetWizardSkillFloatValue",
        "boulder.cfg",
        "ReadEarthBoulderRequestedStatbookLevel",
        "statbook_damage",
        "statbook_level",
        "mana_statbook_level",
        "bounded_release_statbook_damage",
        "native_damage_context_ready",
        "native_damage_scale_query_positive",
        "earth_damage_threshold_reached",
        "bounded_release_at_damage_threshold",
        "damage_threshold_released",
        "kBoundedHeldDamageThresholdPostReleaseWorldUpdateTicks",
        "native_cleanup_release",
        "release_damage_native",
    )
    present_forbidden = [token for token in forbidden_tokens if token in combined_text]
    if present_forbidden:
        raise StaticReTestFailure(
            "Earth boulder damage still carries staged-statbook naming or data flow: " +
            ", ".join(present_forbidden))
    required_tokens = (
        "ResolveEarthBoulderBaseDamage",
        "NativePrimarySpellSelection",
        "TryResolveNativePrimarySelectionFromLiveProgression",
        "ResolveNativePrimaryEntryForElement",
        "TryResolveNativePrimarySpellStats",
        "ReadBotNativeActiveSpellObjectState",
        "kSpellObjectReleaseDamageOffset",
        "kSpellObjectReleaseBaseDamageOffset",
        "spell_object_release_damage=0x1F4",
        "spell_object_release_base_damage=0x1F8",
        "active_spell_state.release_base_damage",
        "obj_release_base_damage",
        "earth_max_size_reached",
        "earth_target_lethal_release_ready",
        "ResolveEarthBoulderDamageOutputScale",
        "ResolveEarthBoulderReleaseDamageScale",
        "ResolveEarthBoulderReleaseDamageFloor",
        "ResolveEarthBoulderReleaseDamageCapScale",
        "kEarthBoulderDamageOutputScaleGlobal",
        "kEarthBoulderReleaseDamageScaleGlobal",
        "kEarthBoulderReleaseDamageFloorGlobal",
        "kEarthBoulderReleaseDamageCapScaleGlobal",
        "earth_boulder_release_damage_scale",
        "earth_boulder_release_damage_floor",
        "earth_boulder_release_damage_cap_scale",
        "ongoing.bounded_release_requested",
        "ongoing.bounded_release_target_lethal",
        "kBoundedHeldPostReleaseWorldUpdateTicks",
        "kActorPrimaryActionLatchE4Offset",
        "kActorPostGateActiveByteOffset",
        "kSpellObjectGrowthRateOffset",
        "release_growth_stop",
        "progression_level",
        "base_damage",
        "projected_damage",
        "damage_output_scale",
        "projected_release_damage",
        "projected_hp_damage",
        "projection_target_in_impact",
        "release_charge_write",
    )
    missing = [token for token in required_tokens if token not in combined_text]
    if missing:
        raise StaticReTestFailure(
            "Earth boulder damage is not backed by native live spell stats: " +
            ", ".join(missing))
    if "ResolveEarthBoulderBaseDamage(" in projection_text:
        raise StaticReTestFailure(
            "held Boulder projection still rebuilds native spell stats instead of reading the live Boulder release base")
    return "Earth boulder damage resolver uses live Boulder release fields and named native stat seams"


def test_boulder_projection_is_read_only_native_formula() -> str:
    projection_text = read_text(BOULDER_PROJECTION)
    processing_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/pending_cast_processing.inl"
    )
    forbidden_tokens = (
        "impact_context_write",
        "impact_context_x",
        "impact_context_y",
        "impact_context_radius",
        "0x8BCC",
        "0x8BD0",
        "0x8BD4",
        "0x8BD8",
        "TryWriteField<",
    )
    present = [token for token in forbidden_tokens if token in projection_text]
    if present:
        raise StaticReTestFailure(
            "boulder projection still writes guessed native query context: " +
            ", ".join(present))
    required_projection_tokens = (
        "native_secondary_reach_radius",
        "object_radius * release_charge * 2.0f",
        "candidate.target_radius * candidate.target_radius",
        "World_QueryRadius uses distance^2",
        "target_distance_squared < native_secondary_reach_radius_squared",
        "native_radius_damage_eligible",
        "base_damage * snapshot.charge * snapshot.charge",
        "ProjectEarthBoulderReleaseDamage",
        "FindBestNativeBoulderImpactVictim",
        "TryListSceneActors",
        "native_boulder_impact_victim_scan",
        "!candidate.native_radius_damage_eligible",
        "native_base_damage * release_damage_scale",
        "snapshot.projected_release_damage",
        "snapshot.projected_hp_damage",
        "snapshot.projected_hp_damage = snapshot.projected_release_damage",
    )
    required_processing_tokens = (
        "earth_target_lethal_release_ready",
        "earth_native_min_release_charge_reached",
        "ResolveEarthBoulderReleaseGrowthStopMinCharge",
        "min_release_ready",
        "earth_damage_projection.target_actor != 0",
        "earth_damage_projection.projected_hp_damage + 0.001f >= earth_damage_projection.target_hp",
        "target_lethal_released",
        "projection_target_in_impact",
        "kBoundedHeldPostReleaseWorldUpdateTicks =\n            kBoundedHeldNativeReleaseEdgeTicks + 8",
    )
    missing = [token for token in required_projection_tokens if token not in projection_text]
    missing += [token for token in required_processing_tokens if token not in processing_text]
    if missing:
        raise StaticReTestFailure(
            "boulder projection is missing native formula/release guard token(s): " +
            ", ".join(missing))
    target_lethal_guard = re.search(
        r"const bool earth_target_lethal_release_ready =(?P<body>.*?);",
        processing_text,
        re.DOTALL,
    )
    if target_lethal_guard is None:
        raise StaticReTestFailure("boulder target-lethal release guard was not found")
    if "native_radius_damage_eligible" in target_lethal_guard.group("body"):
        raise StaticReTestFailure(
            "target-lethal Boulder release should use live target HP and native projected damage without requiring current center-overlap")
    if "earth_native_min_release_charge_reached" not in target_lethal_guard.group("body"):
        raise StaticReTestFailure(
            "target-lethal Boulder release must wait for the native minimum release charge")
    remote_release_guard = re.search(
        r"const bool remote_bounded_release_ready =(?P<body>.*?);",
        processing_text,
        re.DOTALL,
    )
    if remote_release_guard is None:
        raise StaticReTestFailure("remote Boulder release guard was not found")
    if "earth_native_min_release_charge_reached" not in remote_release_guard.group("body"):
        raise StaticReTestFailure(
            "remote Boulder release must wait for the native minimum release charge")
    return "Earth boulder projection stays read-only and drives target-lethal release"


def test_boulder_held_charge_tracks_live_target_until_release() -> str:
    skill_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/skill_selection_rules.inl"
    )
    projection_text = read_text(BOULDER_PROJECTION)
    processing_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/pending_cast_processing.inl"
    )
    targeting_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/targeting_and_facing.inl"
    )
    release_text = read_text(CAST_RELEASE_HELPERS)
    snapshot_text = read_text(BOT_SNAPSHOT_BUILDERS)
    casting_api_text = read_text(CASTING_API)
    required_skill_tokens = (
        "OngoingCastTracksLiveTargetDuringNativeTick(ongoing)",
        "OngoingCastRequiresBoundedHeldCastInputDuringNativeTick(ongoing) &&",
        "!ongoing.bounded_release_requested",
        "OngoingCastShouldUseLiveFacingTarget(ongoing)",
        "binding->facing_target_actor_address",
        "return ongoing.target_actor_address",
    )
    required_projection_tokens = (
        "current_target_actor = ResolveOngoingCastNativeTargetActor",
        "TryPopulateBoulderProjectionTarget",
        "FindBestNativeBoulderImpactVictim",
        "binding->ongoing_cast",
    )
    required_processing_tokens = (
        "Bounded held Earth follows the bot's live target while the boulder is",
        "once release is requested, target refresh stops",
        "ongoing.bounded_release_requested = true",
        "ongoing.bounded_release_target_actor = earth_damage_projection.target_actor",
        "HasBotNativeCastActivity(activity_before_dispatch)",
        "native_activity_before_dispatch",
        "gameplay_input_buffer_readable",
        "bounded_held_release_requested_safety_cap",
        "target_lethal_released",
        "max_size_released",
    )
    required_release_tokens = (
        "kBotNativeActionRearmTicks",
        "native_action_rearm",
    )
    required_readiness_tokens = (
        "native_action_cooldown_ticks",
        "cast rejected for native action cooldown",
    )
    movement_tick_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_movement_tick/participant_scene_binding_ticks.inl"
    )
    required_movement_tokens = (
        "intent.face_target_actor_address != 0",
        "OngoingCastShouldUseLiveFacingTarget(binding->ongoing_cast)",
        "binding->ongoing_cast.target_actor_address = intent.face_target_actor_address",
    )
    required_targeting_tokens = (
        "OngoingCastShouldPreserveProjectionTargetAfterAimMiss",
        "OngoingCastRequiresBoundedHeldCastInputDuringNativeTick(ongoing)",
        "!ongoing.bounded_release_requested",
    )
    missing = [token for token in required_skill_tokens if token not in skill_text]
    missing += [token for token in required_projection_tokens if token not in projection_text]
    missing += [token for token in required_processing_tokens if token not in processing_text]
    missing += [token for token in required_release_tokens if token not in release_text]
    missing += [
        token for token in required_readiness_tokens
        if token not in snapshot_text and token not in casting_api_text
    ]
    missing += [token for token in required_movement_tokens if token not in movement_tick_text]
    missing += [token for token in required_targeting_tokens if token not in targeting_text]
    if missing:
        raise StaticReTestFailure(
            "Earth boulder held retarget/release contract is missing token(s): " +
            ", ".join(missing))
    forbidden_processing_tokens = (
        "gameplay_input_buffer_unreadable",
        "gameplay_mouse_left_unreadable",
    )
    present_forbidden = [
        token for token in forbidden_processing_tokens
        if token in processing_text
    ]
    if present_forbidden:
        raise StaticReTestFailure(
            "Earth boulder startup still treats optional gameplay input buffer reads as fatal: " +
            ", ".join(present_forbidden))
    return "Earth boulder held charge tracks live target until release"


def test_boulder_live_retarget_probe_is_documented() -> str:
    probe_text = read_text(BOULDER_RETARGET_LIVE_PROBE)
    readme_text = read_text(ROOT / "tests/re/README.md")
    plan_text = read_text(NATIVE_SEAM_PLAN)
    required_probe_tokens = (
        "boulder_release_logged",
        "[bots] native boulder release requested.",
        "default=25000.0",
        "release_target_actor",
        "target_in_impact",
        "retarget_removed",
        "retarget_death_logged",
        "retarget_impact_observed",
        "enemy.death hook invoked",
        "initial target was damaged after the bot swapped targets",
        "initial target died after the bot swapped targets",
    )
    required_doc_tokens = (
        "tests/re/run_live_boulder_retarget_probe.py",
        "charges Boulder on one real wave enemy",
        "freezes that retargeted actor at release",
        "high-HP target remains alive",
    )
    missing = [token for token in required_probe_tokens if token not in probe_text]
    missing += [
        token
        for token in required_doc_tokens
        if token not in readme_text and token not in plan_text
    ]
    if missing:
        raise StaticReTestFailure(
            "Earth boulder live retarget probe coverage is missing token(s): " +
            ", ".join(missing))
    return "Earth boulder live retarget probe is documented"


def test_lua_earth_retargeting_uses_live_boulder_impact_anchor() -> str:
    combat_text = read_text(ROOT / "mods/lua_bots/scripts/lib/lua_bots/combat.lua")
    snapshot_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_registry_and_movement_participant_snapshot.inl"
    )
    bot_snapshot_text = read_text(ROOT / "SolomonDarkModLoader/src/lua_engine_parser_snapshots.cpp")
    bot_runtime_text = read_text(ROOT / "SolomonDarkModLoader/include/bot_runtime.h")
    mod_loader_text = read_text(ROOT / "SolomonDarkModLoader/include/mod_loader.h")

    required_snapshot_tokens = (
        "active_spell_object_address",
        "active_spell_object_x",
        "active_spell_object_y",
        "active_spell_object_radius",
        "active_spell_object_charge",
        "CallActorWorldLookupObjectByHandleSafe",
        "kObjectCollisionRadiusOffset",
        "kSpellObjectChargeOffset",
    )
    missing_snapshot_tokens = []
    for token in required_snapshot_tokens:
        if (
            token not in snapshot_text
            and token not in bot_snapshot_text
            and token not in bot_runtime_text
            and token not in mod_loader_text
        ):
            missing_snapshot_tokens.append(token)
    if missing_snapshot_tokens:
        raise StaticReTestFailure(
            "bot snapshots do not expose live active Boulder object fields: " +
            ", ".join(missing_snapshot_tokens))

    required_lua_tokens = (
        "earth_boulder_impact_center",
        "target_in_native_boulder_impact",
        "find_earth_boulder_enemy",
        "active_spell_object_x",
        "active_spell_object_y",
        "active_spell_object_radius",
        "active_spell_object_charge",
        "object_radius * charge * 2.0",
        "native_overlap_radius",
        "enemy.radius",
        "earth_boulder_no_impact_target",
    )
    missing_lua_tokens = [token for token in required_lua_tokens if token not in combat_text]
    if missing_lua_tokens:
        raise StaticReTestFailure(
            "Lua Earth targeting is not anchored to the live native Boulder impact window: " +
            ", ".join(missing_lua_tokens))

    return "Lua Earth retargeting uses the live native Boulder object impact window"


def test_active_cast_movement_clears_stale_vector_before_stock_tick() -> str:
    player_tick_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/actor_tick/player_actor_tick_hook.inl"
    )
    movement_step_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_movement_tick/wizard_bot_movement_step.inl"
    )

    required_tokens = (
        "Clear stale loader movement input before every stock bot tick",
        "const bool stock_tick_may_consume_stale_loader_vector =",
        "binding->movement_active || binding->last_movement_displacement > 0.0001f",
        "ClearWizardBotMovementVectorInputs(actor_address);",
        "active casts receive target/control input through selection state",
        "CallPlayerActorMoveStepSafe",
    )
    missing = [
        token
        for token in required_tokens
        if token not in player_tick_text and token not in movement_step_text
    ]
    if missing:
        raise StaticReTestFailure(
            "active-cast movement can still double-consume stale loader vectors: " +
            ", ".join(missing))

    forbidden_patterns = (
        r"if\s*\(\s*!binding->ongoing_cast\.active\s*\)\s*\{\s*// Loader-owned movement runs after stock tick\.",
        r"if\s*\(\s*!binding->ongoing_cast\.active\s*\)\s*\{\s*ClearWizardBotMovementVectorInputs\(actor_address\);",
    )
    present = [
        pattern for pattern in forbidden_patterns if re.search(pattern, player_tick_text, re.S)
    ]
    if present:
        raise StaticReTestFailure(
            "RunStockTick still clears stale movement only when no cast is active")

    return "active casts clear stale loader movement before stock tick and move once through the native step"


def test_bot_mana_spend_is_stock_owned_through_native_gate_patch() -> str:
    layout_text = read_text(BINARY_LAYOUT)
    plan_text = read_text(NATIVE_SEAM_PLAN)
    resource_text = read_text(RESOURCE_STATE)
    processing_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/pending_cast_processing.inl"
    )
    processing_context_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/processing_context.inl"
    )
    preparation_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/pending_cast_preparation.inl"
    )
    dispatch_hook_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/player_cast_hooks.inl"
    )
    player_control_hook_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/player_control_hooks.inl"
    )
    player_mana_hook_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/player_mana_hooks.inl"
    )
    player_tick_hook_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/actor_tick/player_actor_tick_hook.inl"
    )
    standalone_slot_context_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/standalone_progression_slot_context.inl"
    )
    request_state_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/runtime_request_state.inl"
    )
    constants_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/gameplay_constants.inl"
    )
    public_api_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_keyboard_injection.inl"
    )
    patch_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/native_cast_gate_patches.inl"
    )
    helper_text = read_text(BOT_MANA_TRACE_HELPERS)
    writer_probe_text = read_text(BOT_MANA_WRITER_LIVE_PROBE)
    native_spend_probe_text = read_text(BOT_NATIVE_MANA_SPEND_LIVE_PROBE)
    pure_primary_probe_text = read_text(PURE_PRIMARY_STARTUP_LIVE_PROBE)
    required_tokens = {
        "binary layout": "player_actor_apply_mana_delta=0x0052B150",
        "gate branch layout": "player_actor_apply_mana_delta_local_actor_gate_branch=0x0052B171",
        "ether gate branch layout": "spell_cast_008_slot_gate_branch=0x0053D1B3",
        "ether projectile gate branch layout": "spell_cast_008_projectile_slot_gate_branch=0x0053D9D2",
        "fire gate branch layout": "spell_cast_010_slot_gate_branch=0x0053E4E8",
        "fireball secondary effect gate branch layout": "fireball_hit_secondary_effect_projectile_group_gate_branch=0x005E5387",
        "magic missile hit damage gate branch layout": "magic_missile_hit_damage_projectile_group_gate_branch=0x005F1F39",
        "gate patch name": "player_actor_apply_mana_delta_local_actor_gate",
        "ether gate patch name": "spell_cast_008_ether_slot_gate",
        "ether projectile gate patch name": "spell_cast_008_ether_projectile_slot_gate",
        "fire gate patch name": "spell_cast_010_fire_slot_gate",
        "fireball secondary effect gate patch name": "fireball_hit_secondary_effect_projectile_group_gate",
        "magic missile hit damage gate patch name": "magic_missile_hit_damage_projectile_group_gate",
        "gate patch binding": "kPlayerActorApplyManaDeltaLocalActorGateBranch",
        "ether gate patch binding": "kSpellCast008SlotGateBranch",
        "ether projectile gate patch binding": "kSpellCast008ProjectileSlotGateBranch",
        "fire gate patch binding": "kSpellCast010SlotGateBranch",
        "fireball secondary effect gate patch binding": "kFireballHitSecondaryEffectProjectileGroupGateBranch",
        "magic missile hit damage gate patch binding": "kMagicMissileHitDamageProjectileGroupGateBranch",
        "gate opcode validator": "LooksLikeNativeJnzGate",
        "short jnz gate validator": "bytes[0] == 0x75",
        "gate patch byte count": "patch->byte_count",
        "gate runtime restore": "patch->original = current",
        "processing live depletion": "native mana depleted",
        "processing live read": "TryReadProgressionMana",
        "native rate validator": "ValidateNativeManaRateConfigForOngoingCast",
        "native rate invalidation": "ClearNativeManaRateConfigForOngoingCast",
        "native rate pending log": "native mana rate config pending",
        "trace helper": "wait_for_bot_native_mana_delta",
        "trace rate plausibility": "assert_native_mana_delta_matches_prepared_rate",
        "writer stale guard": "coordinate_only_stale_config_guard",
        "writer target actor": "target_actor_address=target_actor_address",
        "writer probe": "stock_native_mana_delta",
        "writer trace summary": "negative_bot_actor_hits",
        "writer player trace guard": "negative_player_actor_hits",
        "writer player mana guard": "assert_gameplay_player_mana_not_decreased",
        "writer player mp delta": "player_mp_delta",
        "pure primary trace": "stock_native_mana_delta",
        "standalone owner context type": "ScopedStandaloneBotProgressionSlotContext",
        "standalone owner context invoke": "InvokeWithStandaloneBotProgressionSlotContext",
        "standalone owner context log": "standalone_slot_owner_context",
        "bot owner context invoke": "InvokeWithBotProgressionSlotOwnerContext",
        "bot owner context mode": "require_standalone_slot",
        "mana delta hook": "HookPlayerActorApplyManaDelta",
        "mana delta hook state": "player_actor_apply_mana_delta_hook",
        "mana delta hook size": "kPlayerActorApplyManaDeltaHookPatchSize",
        "native mana delta owner context": "native mana delta owner context",
        "pure primary bot owner context": "pure_primary_bot_owner_context",
        "actor progression runtime cache": "EnsureActorProgressionRuntimeFieldFromHandle",
        "pre stock tick progression runtime cache": "pre_bot_stock_tick_progression_runtime",
        "post native mana delta repair": "post_native_bot_mana_delta",
        "player slot owner repair": "RepairGameplayPlayerProgressionSlotOwner",
        "post bot stock tick repair": "post_bot_stock_tick",
    }
    missing: list[str] = []
    if required_tokens["binary layout"] not in layout_text:
        missing.append(required_tokens["binary layout"])
    if required_tokens["gate branch layout"] not in layout_text:
        missing.append(required_tokens["gate branch layout"])
    if required_tokens["ether gate branch layout"] not in layout_text:
        missing.append(required_tokens["ether gate branch layout"])
    if required_tokens["ether projectile gate branch layout"] not in layout_text:
        missing.append(required_tokens["ether projectile gate branch layout"])
    if required_tokens["fire gate branch layout"] not in layout_text:
        missing.append(required_tokens["fire gate branch layout"])
    if required_tokens["magic missile hit damage gate branch layout"] not in layout_text:
        missing.append(required_tokens["magic missile hit damage gate branch layout"])
    for label, token in (
        ("gate patch name", required_tokens["gate patch name"]),
        ("ether gate patch name", required_tokens["ether gate patch name"]),
        ("ether projectile gate patch name", required_tokens["ether projectile gate patch name"]),
        ("fire gate patch name", required_tokens["fire gate patch name"]),
        ("magic missile hit damage gate patch name", required_tokens["magic missile hit damage gate patch name"]),
        ("gate patch binding", required_tokens["gate patch binding"]),
        ("ether gate patch binding", required_tokens["ether gate patch binding"]),
        ("ether projectile gate patch binding", required_tokens["ether projectile gate patch binding"]),
        ("fire gate patch binding", required_tokens["fire gate patch binding"]),
        ("magic missile hit damage gate patch binding", required_tokens["magic missile hit damage gate patch binding"]),
        ("gate opcode validator", required_tokens["gate opcode validator"]),
        ("short jnz gate validator", required_tokens["short jnz gate validator"]),
        ("gate patch byte count", required_tokens["gate patch byte count"]),
        ("gate runtime restore", required_tokens["gate runtime restore"]),
    ):
        if token not in patch_text:
            missing.append(f"{label}:{token}")
    for label, token in (
        ("processing live depletion", required_tokens["processing live depletion"]),
        ("processing live read", required_tokens["processing live read"]),
        ("native rate pending log", required_tokens["native rate pending log"]),
    ):
        if token not in processing_text:
            missing.append(f"{label}:{token}")
    for label, token in (
        ("native rate validator", required_tokens["native rate validator"]),
        ("native rate invalidation", required_tokens["native rate invalidation"]),
    ):
        if token not in resource_text:
            missing.append(f"{label}:{token}")
    for label, text, token in (
        ("trace helper", helper_text, required_tokens["trace helper"]),
        ("trace rate plausibility", helper_text, required_tokens["trace rate plausibility"]),
        ("writer stale guard", writer_probe_text, required_tokens["writer stale guard"]),
        ("writer target actor", writer_probe_text, required_tokens["writer target actor"]),
        ("writer probe", writer_probe_text, required_tokens["writer probe"]),
        ("writer trace summary", writer_probe_text + helper_text, required_tokens["writer trace summary"]),
        ("writer player trace guard", writer_probe_text + native_spend_probe_text + pure_primary_probe_text + helper_text, required_tokens["writer player trace guard"]),
        ("writer player mana guard", writer_probe_text + native_spend_probe_text + pure_primary_probe_text + helper_text, required_tokens["writer player mana guard"]),
        ("writer player mp delta", writer_probe_text + native_spend_probe_text + helper_text, required_tokens["writer player mp delta"]),
        ("native spend probe", native_spend_probe_text, required_tokens["writer probe"]),
        ("pure primary trace", pure_primary_probe_text, required_tokens["pure primary trace"]),
        ("standalone owner context type", standalone_slot_context_text, required_tokens["standalone owner context type"]),
        ("standalone owner context invoke", standalone_slot_context_text + processing_context_text + preparation_text + dispatch_hook_text + player_control_hook_text + player_tick_hook_text, required_tokens["standalone owner context invoke"]),
        ("standalone owner context log", processing_context_text + preparation_text + dispatch_hook_text + player_control_hook_text + player_tick_hook_text, required_tokens["standalone owner context log"]),
        ("bot owner context invoke", standalone_slot_context_text + player_mana_hook_text, required_tokens["bot owner context invoke"]),
        ("bot owner context mode", standalone_slot_context_text, required_tokens["bot owner context mode"]),
        ("mana delta hook", player_mana_hook_text, required_tokens["mana delta hook"]),
        ("mana delta hook state", player_mana_hook_text + request_state_text + public_api_text, required_tokens["mana delta hook state"]),
        ("mana delta hook size", constants_text + public_api_text, required_tokens["mana delta hook size"]),
        ("native mana delta owner context", player_mana_hook_text, required_tokens["native mana delta owner context"]),
        ("pure primary bot owner context", preparation_text + dispatch_hook_text + player_control_hook_text, required_tokens["pure primary bot owner context"]),
        ("actor progression runtime cache", standalone_slot_context_text + player_tick_hook_text + player_mana_hook_text, required_tokens["actor progression runtime cache"]),
        ("pre stock tick progression runtime cache", player_tick_hook_text, required_tokens["pre stock tick progression runtime cache"]),
        ("post native mana delta repair", player_mana_hook_text, required_tokens["post native mana delta repair"]),
        ("player slot owner repair", standalone_slot_context_text, required_tokens["player slot owner repair"]),
        ("post bot stock tick repair", player_tick_hook_text, required_tokens["post bot stock tick repair"]),
    ):
        if token not in text:
            missing.append(f"{label}:{token}")
    if "standalone stock tick owner context" in player_tick_hook_text:
        missing.append("standalone stock tick still swaps the player progression slot")
    if "bot_stock_tick_needs_progression_owner" in player_tick_hook_text:
        missing.append("bot stock tick still carries broad progression owner state")
    if "bot stock tick mana owner context" in player_tick_hook_text:
        missing.append("bot stock tick still logs broad progression owner context")
    if "InvokeWithBotProgressionSlotOwnerContext(" in player_tick_hook_text:
        missing.append("bot stock tick still wraps the whole native tick in slot owner context")
    if re.search(r"TryWriteField\s*<\s*float\s*>\s*\([^;]*kProgressionMpOffset", resource_text, re.S):
        missing.append("direct progression MP write still present")
    if re.search(
        r"TryWriteField\s*<\s*float\s*>\s*\([^;]*kActorSpellConfig2d0Offset[^;]*ongoing\.mana_cost",
        "\n".join((resource_text, processing_text)),
        re.S,
    ):
        missing.append("actor+0x2D0 is being populated from loader-owned mana cost")
    forbidden_active_tokens = (
        "TryApplyNativeBotManaDelta",
        "TrySpendBotMana",
        "NativeBotManaDeltaShim",
        "CallPlayerActorApplyManaDeltaSafe",
        "[bots] mana spent.",
    )
    active_text = "\n".join((resource_text, processing_text, patch_text))
    stale_active = [token for token in forbidden_active_tokens if token in active_text]
    if stale_active:
        missing.append("active code still contains manual mana tokens:" + ",".join(stale_active))
    stale_probe_text = "\n".join((writer_probe_text, native_spend_probe_text, pure_primary_probe_text))
    stale_probe_tokens = [
        token for token in ("assert_shim_fields_restored", "capture_shim_fields", "wait_for_native_mana_spend")
        if token in stale_probe_text
    ]
    if stale_probe_tokens:
        missing.append("live probes still assert shim/log path:" + ",".join(stale_probe_tokens))
    stale_plan_tokens = (
        "PerCast spend branch is still not live-proven",
        "current Fire/Ether pure-primary bot casts can complete with `startup_timeout`",
        "scoped actor/progression shim",
    )
    for token in stale_plan_tokens:
        if token in plan_text:
            missing.append(f"stale native seam plan token:{token}")
    if missing:
        raise StaticReTestFailure(
            "bot mana spend is not stock-owned through native gate patch: " + ", ".join(missing)
        )
    return "bot mana spend is stock-owned through the native mana-delta gate patch"


def test_bot_cast_admission_refreshes_live_mana_before_queue() -> str:
    casting_text = read_text(CASTING_API)
    mod_loader_header_text = read_text(ROOT / "SolomonDarkModLoader/include/mod_loader.h")
    state_getters_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_state_getters.inl"
    )
    snapshot_text = read_text(
        ROOT / "SolomonDarkModLoader/src/bot_runtime/helpers/snapshot_builders.inl"
    )

    required_tokens = (
        "TryRefreshParticipantGameplayState",
        "PublishParticipantGameplaySnapshot(*binding)",
        "ApplyGameplayStateToSnapshot(request.bot_id, &live_snapshot)",
        "ApplyManaReserveStateToSnapshot(&live_snapshot)",
        "live_progression_available",
        "live_snapshot.max_mp > 0.0f",
        "live_snapshot.progression_runtime_state_address != 0",
        "live_snapshot.mana_reserve_active",
        "cast rejected for mana reserve",
        "mode=reserve before=",
        "live_snapshot.mp <= kBotManaReadinessEpsilon",
        "cast rejected for mana",
        "mode=unavailable before=",
        "snapshot->mp > kBotManaReadinessEpsilon && !snapshot->mana_reserve_active",
    )
    combined_text = "\n".join(
        (casting_text, mod_loader_header_text, state_getters_text, snapshot_text)
    )
    missing = [token for token in required_tokens if token not in combined_text]
    if missing:
        raise StaticReTestFailure(
            "bot cast admission does not refresh and reject live empty mana before queue: " +
            ", ".join(missing))

    refresh_pos = casting_text.find("TryRefreshParticipantGameplayState(request.bot_id")
    reject_pos = casting_text.find("cast rejected for mana")
    queue_pos = casting_text.find("g_pending_casts.push_back")
    if not (0 <= refresh_pos < reject_pos < queue_pos):
        raise StaticReTestFailure(
            "bot cast live mana rejection must run before pending-cast insertion")

    return "bot cast admission refreshes live mana and rejects empty MP before queueing"


def test_bot_mana_reserve_uses_hysteresis_for_casting() -> str:
    header_text = read_text(BOT_RUNTIME_HEADER)
    runtime_text = read_text(ROOT / "SolomonDarkModLoader/src/bot_runtime.cpp")
    lookup_text = read_text(BOT_RUNTIME_DEFAULTS_AND_LOOKUP)
    casting_text = read_text(CASTING_API)
    snapshot_text = read_text(BOT_SNAPSHOT_BUILDERS)
    snapshots_api_text = read_text(BOT_RUNTIME_SNAPSHOTS_API)
    lifecycle_text = read_text(BOT_RUNTIME_LIFECYCLE_API)
    state_mutation_text = read_text(
        ROOT / "SolomonDarkModLoader/src/bot_runtime/helpers/state_mutation.inl"
    )
    preparation_text = read_text(PENDING_CAST_PREPARATION)
    release_text = read_text(CAST_RELEASE_HELPERS)
    processing_text = read_text(PENDING_CAST_PROCESSING)
    release_helpers_text = read_text(CAST_RELEASE_HELPERS)
    player_mana_hook_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/player_mana_hooks.inl"
    )
    player_tick_hook_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/actor_tick/player_actor_tick_hook.inl"
    )
    constants_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/gameplay_constants.inl"
    )
    lua_snapshot_text = read_text(LUA_ENGINE_PARSER_SNAPSHOTS)

    required_tokens = (
        "constexpr float kBotManaReserveEnterRatio = 0.10f",
        "constexpr float kBotManaReserveExitRatio = 0.80f",
        "bool mana_reserve_active = false",
        "struct BotManaReserveState",
        "std::vector<BotManaReserveState> g_bot_mana_reserves",
        "ratio < kBotManaReserveEnterRatio",
        "ratio > kBotManaReserveExitRatio",
        "UpdateBotManaReserveStateLocked",
        "RefreshBotManaReserveState",
        "ApplyManaReserveStateToSnapshot(&live_snapshot)",
        "ApplyManaReserveStateToSnapshot(snapshot)",
        "live_snapshot.mana_reserve_active",
        "cast rejected for mana reserve",
        "mode=reserve before=",
        "mana_reserve_active ||",
        "native mana reserve",
        "mana_stop_label = \"mana_reserve\"",
        "StopOngoingBotCastForManaReserve",
        "pre_bot_stock_tick_mana_reserve",
        "ApplyBotNativeManaReserveRecovery",
        "ClearIdleBotManaReserveNativeCastState",
        "native mana reserve idle cast cleanup",
        "InvokeNativeManaDeltaTrampolineForBotSafe",
        "native mana reserve recovery",
        "post_native_bot_mana_recovery",
        "kBotManaReserveRecoveryIntervalMs",
        "kBotManaReserveRecoveryRatioPerSecond",
        "std::strcmp(exit_label, \"mana_reserve\") == 0",
        "std::strcmp(exit_label, \"mana_depleted\") == 0",
        "g_bot_mana_reserves.clear()",
        "RemoveBotManaReserveState(bot_id)",
        "lua_setfield(state, -2, \"mana_reserve_active\")",
    )
    combined_text = "\n".join((
        header_text,
        runtime_text,
        lookup_text,
        casting_text,
        snapshot_text,
        snapshots_api_text,
        lifecycle_text,
        state_mutation_text,
        preparation_text,
        processing_text,
        release_helpers_text,
        player_mana_hook_text,
        player_tick_hook_text,
        constants_text,
        lua_snapshot_text,
    ))
    missing = [token for token in required_tokens if token not in combined_text]
    if missing:
        raise StaticReTestFailure(
            "bot mana reserve hysteresis is missing native cast token(s): " +
            ", ".join(missing))

    enter_pos = lookup_text.find("ratio < kBotManaReserveEnterRatio")
    exit_pos = lookup_text.find("ratio > kBotManaReserveExitRatio")
    if not (0 <= enter_pos < exit_pos):
        raise StaticReTestFailure(
            "bot mana reserve must enter below the low threshold and exit above the high threshold")

    refresh_pos = casting_text.find("ApplyManaReserveStateToSnapshot(&live_snapshot)")
    reserve_reject_pos = casting_text.find("cast rejected for mana reserve")
    queue_pos = casting_text.find("g_pending_casts.push_back")
    if not (0 <= refresh_pos < reserve_reject_pos < queue_pos):
        raise StaticReTestFailure(
            "bot mana reserve rejection must run before pending-cast insertion")

    active_reserve_pos = processing_text.find("native mana reserve")
    active_finish_pos = processing_text.find(
        "FinishBotCastNativeLifecycle(cast_context, ongoing, mana_stop_label, true)")
    if not (0 <= active_reserve_pos < active_finish_pos):
        raise StaticReTestFailure(
            "active bot casts must finish through the native lifecycle when reserve is active")

    run_stock_tick_pos = player_tick_hook_text.find("auto RunStockTick")
    pre_stop_pos = player_tick_hook_text.find(
        "StopOngoingBotCastForManaReserve", run_stock_tick_pos)
    recovery_pos = player_tick_hook_text.find(
        "ApplyBotNativeManaReserveRecovery", run_stock_tick_pos)
    drive_input_pos = player_tick_hook_text.find(
        "const bool drive_stock_cast_input", run_stock_tick_pos)
    original_tick_pos = player_tick_hook_text.find("original(self);", drive_input_pos)
    if not (
        0 <= run_stock_tick_pos < pre_stop_pos < recovery_pos < drive_input_pos < original_tick_pos
    ):
        raise StaticReTestFailure(
            "bot mana reserve stop/recovery must run before stock cast input and native tick")

    return "bot mana reserve uses 10/80 hysteresis across native cast paths"


def test_bot_out_of_mana_probe_checks_pre_execution_rejection() -> str:
    probe_text = read_text(BOT_OUT_OF_MANA_REJECTION_LIVE_PROBE)
    readme_text = read_text(ROOT / "tests/re/README.md")

    required_tokens = (
        "force_bot_mana",
        "sd.debug.write_float(mp_address, {current_mp})",
        "sd.debug.write_float(max_mp_address, {max_mp})",
        "queue_default_primary(bot_id",
        "allow_queued_rejection",
        "cast_rejected_without_effects",
        "sd_bots_cast_returned_false",
        "mana_rejection_logged",
        "no_pending_cast_after_rejection",
        "no_active_cast_after_rejection",
        "no_startup_after_rejection",
        "no_cast_activity_after_rejection",
        "no_pending_cast_insert_log",
        "mp_not_spent",
        "no_native_mana_spend",
        "no_cast_lifecycle_or_effect_logs",
        "cast rejected for mana",
    )
    missing = [token for token in required_tokens if token not in probe_text]
    if missing:
        raise StaticReTestFailure(
            "bot out-of-mana live probe is missing pre-execution rejection token(s): " +
            ", ".join(missing))

    required_doc_tokens = (
        "run_live_bot_out_of_mana_rejection_probe.py",
        "--bot-key earth --bot-element-id 2 --current-mp 1 --max-mp 100 --allow-queued-rejection",
        "forces the bot's live progression MP to zero",
        "before pending-cast insertion",
        "held-cast preparation gate",
        "no cast lifecycle or effect logs",
    )
    missing_doc = [token for token in required_doc_tokens if token not in readme_text]
    if missing_doc:
        raise StaticReTestFailure(
            "RE test README is missing out-of-mana rejection coverage token(s): " +
            ", ".join(missing_doc))

    return "bot out-of-mana probe checks pre-execution rejection and no effects"


def test_held_primary_mana_uses_native_spend_scale_and_start_rate() -> str:
    casting_text = read_text(CASTING_API)
    native_stats_header_text = read_text(NATIVE_SPELL_STATS_HEADER)
    native_stats_text = read_native_spell_stats_source()
    preparation_text = read_text(PENDING_CAST_PREPARATION)

    required_tokens = (
        "mana_spend_cost",
        "mana_spend_cost_available",
        "NativePrimaryManaOutputUsesDisplayScale",
        "kActorWalkCyclePrimaryDivisorGlobal",
        "TryReadValue(scale_address",
        "cost.cost = stats.mana_spend_cost",
        "cost.native_stat_cost = stats.mana_cost",
        "cost.native_output_scale = stats.mana_output_scale",
        "CanBotManaStartCast",
        "case BotManaChargeKind::PerSecond:",
        "return cost.cost;",
        "ResolveBotManaRequiredToStart(cost)",
        "ResolveBotManaRequiredToStart(cast_mana)",
        "CanBotManaStartCast(cast_mana, current_mp, max_mp)",
        "mana_reserve_active ? std::string(\"reserve\") : std::string(\"per_second\")",
        "\" rate=\" + std::to_string(cast_mana.cost)",
        "native_stat_cost=",
        "native_output_scale=",
    )
    combined_text = "\n".join((
        casting_text,
        native_stats_header_text,
        native_stats_text,
        preparation_text,
    ))
    missing = [token for token in required_tokens if token not in combined_text]
    if missing:
        raise StaticReTestFailure(
            "held primary mana policy is missing native scale/start-rate token(s): " +
            ", ".join(missing))

    forbidden_patterns = (
        (
            casting_text,
            r"case\s+BotManaChargeKind::PerSecond:\s*return\s+current_mp\s*>\s*kBotManaReadinessEpsilon\s*;",
            "per-second start still accepts any positive mana",
        ),
        (
            preparation_text,
            r"current_mp\s*\+\s*0\.001f\s*<\s*required_mana",
            "preparation still gates held casts by required_mana instead of start policy",
        ),
    )
    present = [
        label for text, pattern, label in forbidden_patterns if re.search(pattern, text, re.S)
    ]
    if present:
        raise StaticReTestFailure("; ".join(present))

    return "held primaries spend the unscaled native mana cost and require the native start rate"


def test_primary_build_skill_mapping_has_single_runtime_owner() -> str:
    casting_text = read_text(CASTING_API)
    scene_text = read_text(SCENE_SELECTION)
    native_spell_stats_text = read_native_spell_stats_source()
    preparation_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/pending_cast_preparation.inl"
    )
    if "resolve_primary_build_skill_id" in casting_text:
        raise StaticReTestFailure("bot runtime still duplicates primary combo build-skill mapping")
    if "skill_id <= 0 || loadout_cost.resolved" in casting_text:
        raise StaticReTestFailure("bot mana resolver accepts arbitrary positive primary skill ids")
    if "TryResolvePrimaryCastDescriptorFromSkillId" not in scene_text:
        raise StaticReTestFailure("scene selection does not resolve explicit primary build ids")
    if "TryResolvePrimaryCastDescriptorFromSkillId" not in preparation_text:
        raise StaticReTestFailure("cast preparation does not use explicit primary descriptors")
    if "TryResolveNativePrimaryBuildSkillId" in scene_text or "TryResolveNativePrimaryBuildSkillId" in native_spell_stats_text:
        raise StaticReTestFailure(
            "primary combo build-skill mapping still uses a static helper instead of Skills_Wizard output")
    if re.search(r"case\s+(?:1000|0x3E[0-9A-F]|0x3F[0-9A-F])", native_spell_stats_text):
        raise StaticReTestFailure("native spell stats still reverse-map primary build ids with a switch")
    if re.search(r"case\s+(?:1000|0x3E[0-9A-F]|0x3F[0-9A-F])", scene_text):
        raise StaticReTestFailure("scene selection still classifies primary build ids with a switch")

    required_tokens = (
        "CallSkillsWizardBuildPrimarySpellSafe",
        "TryResolveNativePrimarySelectionFromLiveProgression",
        "TryResolveNativePrimarySelectionFromSkillId",
        "kSkillsWizardBuildPrimarySpell",
        "RestoreProgressionCurrentSpellIdIfNeeded",
    )
    missing_tokens = [
        token for token in required_tokens
        if token not in native_spell_stats_text and token not in scene_text
    ]
    if missing_tokens:
        raise StaticReTestFailure(
            "primary combo build-skill mapping is missing native builder token(s): " +
            ", ".join(missing_tokens))
    return "primary combo build-skill mapping is resolved from live Skills_Wizard output"


def test_gameplay_selection_writes_do_not_corrupt_stock_run_placement_vector() -> str:
    gameplay_state_text = read_text(SCENE_ANIMATION_GAMEPLAY_STATE)
    debug_state_text = read_text(PUBLIC_API_DEBUG_AND_SPAWN)
    cast_probe_text = read_text(CAST_PROBE_STATE)
    selection_doc_text = read_text(ROOT / "docs/spell-cast-cleanup-chain.md")

    required_tokens = (
        (
            gameplay_state_text,
            "gameplay selection writer",
            "TryWriteGameplayIndexStateValue(",
        ),
        (
            debug_state_text,
            "selection debug state",
            "state->player_selection_state_0 = state->slot_selection_entries[0];",
        ),
        (
            debug_state_text,
            "selection debug state",
            "state->player_selection_state_1 = state->slot_selection_entries[1];",
        ),
        (
            selection_doc_text,
            "selection lifecycle doc",
            "The globals at `0x00819EC4/0x00819EC8` are not a recovered bot selection API.",
        ),
    )
    missing = [f"{label}: {token}" for text, label, token in required_tokens if token not in text]
    if missing:
        raise StaticReTestFailure(
            "selection-state vector-corruption guard is missing token(s): " +
            ", ".join(missing))

    forbidden_tokens = (
        (gameplay_state_text, "gameplay selection writer", "TryWriteResolvedGlobalInt(selection_global"),
        (gameplay_state_text, "gameplay selection writer", "kPlayerSelectionState0Global"),
        (gameplay_state_text, "gameplay selection writer", "kPlayerSelectionState1Global"),
        (debug_state_text, "selection debug state", "TryReadResolvedGlobalInt(kPlayerSelectionState0Global"),
        (debug_state_text, "selection debug state", "TryReadResolvedGlobalInt(kPlayerSelectionState1Global"),
        (cast_probe_text, "cast probe", "TryReadResolvedGlobalInt(kPlayerSelectionState0Global"),
    )
    present = [f"{label}: {token}" for text, label, token in forbidden_tokens if token in text]
    if present:
        raise StaticReTestFailure(
            "selection-state code still touches stock run-placement vector global(s): " +
            ", ".join(present))

    return "gameplay selection writes stay on the slot table and do not touch stock vector globals"


def test_primary_kill_stress_verifier_uses_manual_spawns_without_waves() -> str:
    verifier_text = read_text(PRIMARY_KILL_STRESS_VERIFIER)
    runtime_state_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/runtime_request_state.inl")
    input_queue_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_input_queueing.inl")
    player_control_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/player_control_hooks.inl")
    player_cast_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/player_cast_hooks.inl")
    pump_loop_text = read_text(DISPATCH_PUMP_LOOP)
    run_lifecycle_state_text = read_text(
        ROOT / "SolomonDarkModLoader/src/run_lifecycle/state_and_targets.inl")
    run_lifecycle_hooks_text = read_text(
        ROOT / "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks.inl")
    run_lifecycle_cast_text = read_text(
        ROOT / "SolomonDarkModLoader/src/run_lifecycle/spell_cast_hooks.inl")
    run_lifecycle_public_api_text = read_text(
        ROOT / "SolomonDarkModLoader/src/run_lifecycle/public_api_and_install.inl")
    required_tokens = (
        "sd.gameplay.enable_combat_prelude()",
        "sd.gameplay.set_manual_enemy_spawner_test_mode(enabled)",
        "parse_int(state.get(\"wave_index\")) == 0",
        "parse_int(state.get(\"wave_counter\")) == 999999999",
        "spawn_manual_run_enemy",
        "sd.gameplay.set_run_enemy_health(actor_address, hp, hp)",
        "PRIMARY_CAST_HOOK_MARKER",
        "quiesce_gameplay_primary_input",
        "clear_gameplay_mouse_left",
        "PREPARE_AND_QUEUE_CASTER_LUA",
        "MAX_SCRIPTED_PRIMARY_TARGET_DISTANCE",
        "source_target_distance",
        "transport_active_count",
        "place_player_and_require_pair_views_at",
        "FORCED_PICKUP_POSITION_TOLERANCE",
        "select_forced_gold_location",
        "FORCED_GOLD_MIN_PLAYER_DISTANCE",
        "forced_gold_location",
        "before_spawn",
    )
    missing = [token for token in required_tokens if token not in verifier_text]
    if missing:
        raise StaticReTestFailure(
            "primary kill stress verifier is missing no-wave manual-spawn token(s): " +
            ", ".join(missing))
    native_required_tokens = (
        (verifier_text, "primary kill verifier", "START_WAVES_LUA"),
        (verifier_text, "primary kill verifier", "sd.gameplay.get_manual_enemy_spawner_state"),
        (verifier_text, "primary kill verifier", "host_manual_spawner_ready"),
        (verifier_text, "primary kill verifier", "client_manual_spawner_ready"),
        (verifier_text, "primary kill verifier", "host native manual-spawner priming leaked stock enemies"),
        (verifier_text, "primary kill verifier", "client native manual-spawner priming leaked stock enemies"),
        (pump_loop_text, "gameplay pump", "PumpRunLifecycleManualEnemySpawnRequest(&manual_spawn_error)"),
        (run_lifecycle_public_api_text, "run lifecycle API", "IsRunLifecycleManualEnemySpawnerReady()"),
        (run_lifecycle_public_api_text, "run lifecycle API", "g_state.last_wave_spawner.load"),
        (run_lifecycle_public_api_text, "run lifecycle API", "g_state.last_wave_spawner_vtable.load"),
        (run_lifecycle_public_api_text, "run lifecycle API", "g_state.last_wave_spawner_tick_ms.load"),
        (run_lifecycle_public_api_text, "run lifecycle API", "TryGetPreferredManualRunEnemySpawner"),
        (run_lifecycle_public_api_text, "run lifecycle API", "IsRememberedWaveSpawnerVtableValid"),
        (run_lifecycle_public_api_text, "run lifecycle API", "TryDispatchManualRunEnemySpawnFromSpawner("),
        (run_lifecycle_public_api_text, "run lifecycle API", "manual run enemy spawn: pumped remembered stock spawner"),
        (run_lifecycle_public_api_text, "run lifecycle API", "if (!IsRunLifecycleManualEnemySpawnerReady())"),
        (run_lifecycle_public_api_text, "run lifecycle API", "CompletePendingDirectManualRunEnemySpawnFailure"),
        (run_lifecycle_public_api_text, "run lifecycle API", "manual run enemy spawn: stock wave spawner became unavailable."),
        (run_lifecycle_state_text, "run lifecycle state", "last_arena_enemy_wave_spawner"),
        (run_lifecycle_state_text, "run lifecycle state", "g_current_wave_spawner_tick_address"),
        (run_lifecycle_hooks_text, "run lifecycle hooks", "RememberArenaEnemyWaveSpawner"),
        (run_lifecycle_hooks_text, "run lifecycle hooks", "TryReadActorObjectTypeForRunLifecycle(enemy_address, &actor_object_type)"),
        (run_lifecycle_hooks_text, "run lifecycle hooks", "g_current_wave_spawner_tick_address = spawner_address"),
        (run_lifecycle_hooks_text, "run lifecycle hooks", "g_current_wave_spawner_tick_address = self_address"),
        (run_lifecycle_hooks_text, "run lifecycle hooks", "IsArenaCombatActorType(actor_object_type)"),
        (run_lifecycle_hooks_text, "run lifecycle hooks", "actor_object_type="),
        (run_lifecycle_hooks_text, "run lifecycle hooks", "manual run enemy spawn: ignored non-arena stock spawn during controlled tick"),
        (runtime_state_text, "runtime request state", "manual_spawner_primary_cast_control_grace_until_ms"),
        (input_queue_text, "input queue", "kManualSpawnerPrimaryCastControlGraceMinMs"),
        (player_control_text, "player control hooks", "IsManualSpawnerPrimaryCastControlGraceActive()"),
        (player_control_text, "player control hooks", "suppressed extra local pure-primary start during scripted cast grace"),
        (player_control_text, "player control hooks", "manual_spawner_scripted_local_primary_control"),
        (player_control_text, "player control hooks", "seeded local scripted primary control"),
        (player_control_text, "player control hooks", "const bool actor_target_written ="),
        (player_control_text, "player control hooks", "const auto target_heading = NormalizeWizardActorHeadingForWrite("),
        (player_control_text, "player control hooks", "ApplyWizardActorFacingState(actor_address, target_heading)"),
        (player_control_text, "player control hooks", "if (!actor_target_written || selection_pointer == 0)"),
        (player_control_text, "player control hooks", "if (selection_pointer != 0)"),
        (input_queue_text, "input queue", "if (selection_pointer != 0)"),
        (player_cast_text, "player cast hooks", "void __fastcall HookPurePrimaryAttackDispatch("),
        (player_cast_text, "player cast hooks", "IsManualSpawnerPrimaryCastControlGraceActive()"),
        (player_cast_text, "player cast hooks", "ApplyManualSpawnerPrimaryTargetState("),
        (run_lifecycle_cast_text, "run lifecycle cast hooks", "ApplyPinnedManualSpawnerPrimaryTarget(self_address)"),
    )
    native_missing = [
        f"{label}: {token}"
        for text, label, token in native_required_tokens
        if token not in text
    ]
    if native_missing:
        raise StaticReTestFailure(
            "manual enemy spawn requests must be serviced by the gameplay action pump: " +
            ", ".join(native_missing))
    if "fallback_spawner" in run_lifecycle_public_api_text:
        raise StaticReTestFailure(
            "manual enemy spawning retained a fallback spawner path instead of "
            "failing an unavailable native-spawner request")
    if "if (!manual_spawner_scripted_local_primary_control || selection_pointer == 0)" in player_control_text:
        raise StaticReTestFailure(
            "scripted local primary aiming still requires a bot-owned selection pointer")
    if "x=target_x + FORCED_GOLD_OFFSET_X" in verifier_text:
        raise StaticReTestFailure(
            "primary kill stress verifier regressed to a blind forced-gold offset instead of nav-aware selection")
    active_gold_filter_tokens = (
        "FORCED_GOLD_MIN_PLAYER_DISTANCE = 900.0",
        "FORCED_GOLD_CANDIDATE_OFFSETS = (\n    (100.0, -1200.0)",
        "(-960.0, -720.0)",
        "(1280.0, FORCED_GOLD_OFFSET_Y)",
        "def list_host_active_native_gold_addresses()",
        "parse_int(row.get(\"amount\")) > 0",
        "parse_int(row.get(\"lifetime\")) != 0",
        "before_addresses = list_host_active_native_gold_addresses()",
    )
    missing_active_gold_filter_tokens = [
        token for token in active_gold_filter_tokens if token not in verifier_text
    ]
    if missing_active_gold_filter_tokens:
        raise StaticReTestFailure(
            "primary kill stress verifier must only exclude active pre-existing gold drops: " +
            ", ".join(missing_active_gold_filter_tokens))
    source_lane_tokens = (
        "def clear_lane_probe(target_x: float, target_y: float, pipe_name: str = HOST_PIPE)",
        "result[\"pipe\"] = pipe_name",
        "clear_lane_probe(planned_target_x, planned_target_y, pipe_name=direction.source_pipe)",
        "pipe_name=direction.source_pipe",
    )
    missing_source_lane_tokens = [
        token for token in source_lane_tokens if token not in verifier_text
    ]
    if missing_source_lane_tokens:
        raise StaticReTestFailure(
            "primary kill stress verifier must check clear cast lanes from the casting instance: " +
            ", ".join(missing_source_lane_tokens))
    return (
        "primary kill stress primes exact native spawners, rejects unavailable "
        "manual requests, and completes accepted readiness races"
    )


def test_bot_equip_materialization_stays_scoped_to_bot_creation() -> str:
    resources_text = read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/standalone_materialization_wizard_resources.inl")
    slot_creation_text = read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/standalone_materialization_slot_bot_creation.inl")
    shared_required_tokens = (
        (resources_text, "generic equip repair helper", "bool EnsureWizardActorEquipRuntimeHandles("),
        (resources_text, "generic equip repair helper", "CreateStandaloneWizardEquipWrapper("),
        (resources_text, "generic equip repair helper", "AssignActorSmartPointerWrapperSafe("),
        (resources_text, "generic equip repair helper", "[bots] wizard actor equip runtime handles created."),
        (slot_creation_text, "gameplay-slot equip repair wrapper", "\"gameplay_slot_bot\""),
    )
    shared_missing = [
        f"{label}: {token}"
        for text, label, token in shared_required_tokens
        if token not in text
    ]
    if shared_missing:
        raise StaticReTestFailure(
            "bot equip materialization is missing required token(s): " +
            ", ".join(shared_missing))
    if "local_player_run_cast_prime" in resources_text + slot_creation_text:
        raise StaticReTestFailure(
            "bot equip materialization still exposes the removed local-player path")
    return "wizard equip materialization remains available to bot creation without a local-player owner"


def test_hub_start_testrun_uses_gameplay_region_switch() -> str:
    seams_header_text = read_text(ROOT / "SolomonDarkModLoader/src/gameplay_seams.h")
    seam_address_text = read_text(ROOT / "SolomonDarkModLoader/src/gameplay_seams/address_storage.inl")
    seam_binding_text = read_text(ROOT / "SolomonDarkModLoader/src/gameplay_seams/state_and_address_bindings.inl")
    native_types_text = read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/native_function_types.inl")
    action_queue_text = read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_gameplay_action_queues.inl")
    dispatch_text = read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_gameplay_thread_dispatch.inl")
    actor_lifecycle_text = read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_actor_lifecycle_hooks.inl")
    config_text = read_text(ROOT / "config/binary-layout.ini")
    required_tokens = (
        (action_queue_text, "Queued hub testrun request."),
        (action_queue_text, "EnsureHostRunGenerationSeed(\"hub_start_testrun_queue\")"),
        (dispatch_text, "ProcessMemory::Instance().ResolveGameAddressOrZero(kGameplaySwitchRegion)"),
        (dispatch_text, "CallGameplaySwitchRegionSafe("),
        (dispatch_text, "ScopedHubRunSwitchAuthorization authorize_switch"),
        (dispatch_text, "kArenaRegionIndex"),
        (dispatch_text, "Hub testrun region switch completed."),
        (actor_lifecycle_text, "PrepareGameplaySceneSwitchOnGameThread(\n        gameplay_address,\n        region_index,\n        \"gameplay_switch_region_pre_dispatch\")"),
        (actor_lifecycle_text, "Blocked client run switch_region while connected to multiplayer"),
        (config_text, "gameplay_switch_region=0x005CDDD0"),
    )
    missing = [token for text, token in required_tokens if token not in text]
    if missing:
        raise StaticReTestFailure(
            "hub start testrun is missing native region-switch token(s): " +
            ", ".join(missing))
    forbidden_tokens = (
        "kHubStartTestrunNative",
        "kHubStartTestrunRemoveChild",
        "kHubStartTestrunPreviousChildGlobal",
        "HubStartTestrunNativeFn",
        "HubOwnerRemoveChildFn",
        "CallHubOwnerRemoveChildSafe",
        "CallHubStartTestrunNativeSafe",
        "hub_start_testrun_native_builder",
        "Hub testrun native builder completed.",
        "start_testrun_native=0x005B6D50",
        "start_testrun_remove_child=0x00428160",
        "start_testrun_previous_child_global=0x0081993C",
        "CallHubOwnerControlActionSafe",
        "HubOwnerControlActionFn",
        "kHubStartTestrunControlByteOffset",
        "CallHubStartTestrunPrepareSafe",
        "HubStartTestrunPrepareFn",
        "kHubStartTestrunPrepare",
        "start_testrun_prepare",
    )
    active_text = "\n".join((
        seams_header_text,
        seam_address_text,
        seam_binding_text,
        native_types_text,
        dispatch_text,
        config_text,
    ))
    present = [token for token in forbidden_tokens if token in active_text]
    if present:
        raise StaticReTestFailure(
            "hub start testrun still references incomplete native UI/builder dispatch token(s): " +
            ", ".join(present))
    return "hub start testrun dispatches through native Gameplay_SwitchRegion"


def test_hub_start_testrun_waits_for_app_tick_pump() -> str:
    pump_text = read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_pump_loop.inl")
    pending_index = pump_text.find("pending_hub_start_testrun_requests.load")
    app_tick_guard_index = pump_text.find("if (!g_allow_gameplay_action_pump_in_gameplay) {", pending_index)
    dispatch_index = pump_text.find("TryDispatchHubStartTestrunOnGameThread()", pending_index)
    gameplay_return_guard_index = pump_text.find(
        "if (!g_allow_gameplay_action_pump_in_gameplay && gameplay_active)",
        pending_index)
    if pending_index < 0 or app_tick_guard_index < 0 or dispatch_index < 0:
        raise StaticReTestFailure("hub start testrun pump no longer has app-tick guarded dispatch")
    if not (pending_index < app_tick_guard_index < dispatch_index < gameplay_return_guard_index):
        raise StaticReTestFailure(
            "hub start testrun dispatch must stay inside the app-tick guard and before the "
            "non-gameplay action return guard")
    return "hub start testrun remains app-tick owned and deferred out of the actor-tick gameplay pump"


def test_primary_kill_stress_verifier_uses_native_hub_start() -> str:
    verifier_text = read_text(PRIMARY_KILL_STRESS_VERIFIER)
    local_sync_text = read_text(ROOT / "tools/verify_local_multiplayer_sync.py")
    required_tokens = (
        (verifier_text, "start_host_testrun_and_wait_for_clients(timeout=60.0)"),
        (local_sync_text, "sd.hub.start_testrun()"),
        (local_sync_text, "assert_client_start_testrun_blocked"),
    )
    missing = [token for text, token in required_tokens if token not in text]
    if missing:
        raise StaticReTestFailure(
            "primary kill stress verifier is missing native hub-start token(s): " +
            ", ".join(missing))
    return "primary kill stress verifier enters runs through the native hub start request"


def test_unverified_play_boneyard_shortcut_is_not_exposed() -> str:
    active_texts = {
        "mod_loader_h": read_text(ROOT / "SolomonDarkModLoader/include/mod_loader.h"),
        "input_bindings": read_text(ROOT / "SolomonDarkModLoader/src/lua_engine_bindings_input.cpp"),
        "local_sync": read_text(ROOT / "tools/verify_local_multiplayer_sync.py"),
        "primary_kill_stress": read_text(PRIMARY_KILL_STRESS_VERIFIER),
    }
    forbidden = (
        "QueueHubStartPlayBoneyard",
        "start_play_boneyard",
        "stage_play_boneyard",
        "--boneyard-source",
        "play-boneyard",
    )
    present = [
        f"{name}:{token}"
        for name, text in active_texts.items()
        for token in forbidden
        if token in text
    ]
    if present:
        raise StaticReTestFailure(
            "unverified play.boneyard shortcut is still exposed in active code: " +
            ", ".join(present))
    return "unverified play.boneyard shortcut remains out of active runtime and verifier code"


def test_replicated_manual_run_enemy_materialization_is_client_bounded() -> str:
    world_snapshot_text = read_text(WORLD_SNAPSHOT_RECONCILIATION)
    run_lifecycle_api_text = read_text(
        ROOT / "SolomonDarkModLoader/src/run_lifecycle/public_api_and_install.inl")
    run_lifecycle_hooks_text = read_text(
        ROOT / "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks.inl")
    debug_spawn_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_debug_and_spawn.inl")
    local_transport_text = read_multiplayer_transport_source()
    local_transport_header_text = read_text(
        ROOT / "SolomonDarkModLoader/include/multiplayer_local_transport.h")
    required_tokens = (
        "g_replicated_run_pending_enemy_materialization_until_ms",
        "QueueReplicatedManualRunEnemyMaterialization",
        "!multiplayer::IsLocalTransportClient()",
        "QueueRunLifecycleReplicatedEnemyCatchupSpawn(",
        "request.allow_active_waves = allow_active_waves",
        "request.freeze_on_spawn = freeze_on_spawn",
        "if (request.freeze_on_spawn) {",
        "multiplayer::HasLocalPendingLethalEnemyDamageClaim(authoritative_actor.network_actor_id, now_ms)",
        "if (IsRunLifecycleManualEnemySpawnerTestModeEnabled())",
        "QueueRunLifecycleManualEnemySpawn(",
        "(void)QueueReplicatedManualRunEnemyMaterialization(authoritative_actor, now_ms)",
        "g_replicated_run_pending_enemy_materialization_until_ms.erase(network_actor_id)",
        "pending_lethal_enemy_damage_claim_until_ms",
        "kEnemyDamageLethalClaimPendingSuppressMs",
        "HasLocalPendingLethalEnemyDamageClaim",
        "manual run enemy spawn is host-authoritative while connected to multiplayer.",
    )
    haystacks = {
        "world snapshot reconciliation": world_snapshot_text,
        "run lifecycle API": run_lifecycle_api_text,
        "run lifecycle hooks": run_lifecycle_hooks_text,
        "debug spawn public API": debug_spawn_text,
        "local transport": local_transport_text,
        "local transport header": local_transport_header_text,
    }
    missing: list[str] = []
    for token in required_tokens:
        if not any(token in text for text in haystacks.values()):
            missing.append(token)
    if missing:
        raise StaticReTestFailure(
            "replicated manual enemy materialization is missing bounded-client token(s): " +
            ", ".join(missing))
    return "replicated manual run enemy materialization stays client/test-mode bounded and public API remains host-authoritative"


def test_primary_mana_resolver_accepts_native_dispatcher_entry_ids() -> str:
    casting_text = read_text(CASTING_API)
    scene_text = read_text(SCENE_SELECTION)
    native_spell_stats_text = read_native_spell_stats_source()

    resolver_match = re.search(
        r"BotManaCost\s+ResolveBotCastManaCost\([^{}]*\)\s*\{(?P<body>.*?)\n\}",
        casting_text,
        re.S,
    )
    if not resolver_match:
        raise StaticReTestFailure("could not find ResolveBotCastManaCost body")
    resolver_body = resolver_match.group("body")
    required_tokens = (
        "TryResolveNativePrimarySelectionFromSkillId",
        "if (!selection_resolved)",
        "TryResolveNativePrimarySelectionFromPair",
    )
    missing = [token for token in required_tokens if token not in resolver_body]
    if missing:
        raise StaticReTestFailure(
            "primary mana resolver does not accept native dispatcher entry ids: " +
            ", ".join(missing))
    if not re.search(
        r"TryResolveNativePrimarySelectionFromPair\(\s*skill_id,\s*skill_id,",
        resolver_body,
    ):
        raise StaticReTestFailure(
            "primary mana resolver does not validate a dispatcher entry as a primary pair")

    descriptor_tokens = (
        "case 0x18:",
        "case 0x20:",
        "case 0x28:",
        "TryResolvePrimaryCastDescriptorFromSelectionPair",
    )
    missing_descriptor_tokens = [
        token for token in descriptor_tokens if token not in scene_text
    ]
    if missing_descriptor_tokens:
        raise StaticReTestFailure(
            "primary descriptor resolver no longer accepts native dispatcher ids: " +
            ", ".join(missing_descriptor_tokens))

    dispatcher_mana_tokens = (
        "entry_pair_is_pure_projectile",
        "!EntryUsesContinuousMana(primary_entry_index)",
        "selection->pure_primary = entry_pair_is_pure_projectile",
    )
    missing_dispatcher_mana_tokens = [
        token for token in dispatcher_mana_tokens if token not in native_spell_stats_text
    ]
    if missing_dispatcher_mana_tokens:
        raise StaticReTestFailure(
            "native dispatcher entry ids still look like pure-projectile mana selections: " +
            ", ".join(missing_dispatcher_mana_tokens))

    return "primary mana resolver accepts native dispatcher ids through validated primary pairs"


def test_native_primary_output_layout_is_stat_ordered() -> str:
    native_spell_stats_text = read_native_spell_stats_source()

    required_tokens = (
        "kMinimumNativePrimaryStatOutputCount = 2",
        "ResolveNativePrimaryManaOutputIndex(selection)",
        "selection.primary_entry_index == selection.combo_entry_index ? 1u : 2u",
        "if (output_count <= mana_output_index)",
        "if (mana_output_index > 1)",
    )
    missing = [token for token in required_tokens if token not in native_spell_stats_text]
    if missing:
        raise StaticReTestFailure(
            "native primary output resolver no longer follows Skills_Wizard stat order: " +
            ", ".join(missing))

    forbidden_tokens = (
        "selection.pure_primary ? 1u : 2u",
        "selection.primary_entry_index != ether_entry",
        "mana_output_index = output_count - 1",
        "mana_output_index + 1",
        "!selection.pure_primary && output_count > 1",
    )
    present = [token for token in forbidden_tokens if token in native_spell_stats_text]
    if present:
        raise StaticReTestFailure(
            "native primary output resolver still derives stat layout from cast lifetime: " +
            ", ".join(present))

    return "native primary output resolver keeps base mana ahead of appended upgrade stats"


def test_lightning_chaining_verifier_uses_native_dispatcher_loop() -> str:
    layout_text = read_text(BINARY_LAYOUT)
    verifier_text = read_text(
        ROOT / "tools/verify_multiplayer_lightning_chaining_effect_sync.py"
    )
    transport_text = read_multiplayer_transport_source()
    protocol_text = read_text(MULTIPLAYER_PROTOCOL)
    runtime_state_text = read_multiplayer_runtime_state_source()
    lua_gameplay_text = read_text(ROOT / "SolomonDarkModLoader/src/lua_engine_bindings_gameplay.cpp")
    air_chain_sync_text = read_text(
        ROOT / "SolomonDarkModLoader/src/multiplayer_local_transport/air_chain_sync.inl"
    )
    run_lifecycle_state_text = read_text(
        ROOT / "SolomonDarkModLoader/src/run_lifecycle/state_and_targets.inl"
    )
    spell_cast_hooks_text = read_text(
        ROOT / "SolomonDarkModLoader/src/run_lifecycle/spell_cast_hooks.inl"
    )
    pending_cast_text = read_text(PENDING_CAST_PREPARATION)
    scene_selection_text = read_text(SCENE_SELECTION)
    targeted_spell_matrix_text = read_text(TARGETED_SPELL_MATRIX_VERIFIER)
    animation_verifier_text = read_text(
        ROOT / "tools/verify_multiplayer_animation_mana_elements.py"
    )
    active_pair_spell_text = read_text(
        ROOT / "tools/verify_steam_friend_active_pair_spell_behavior.py"
    )

    required_layout_tokens = (
        "actor_air_lightning_chain_count=0x284",
        "air_lightning_chain_target=0x00641340",
        "air_lightning_chain_target_return=0x005403AF",
        "air_lightning_chain_source_from_return_slot=0xB0",
        "spell_cast_018=0x0053F9C0",
    )
    missing_layout = [token for token in required_layout_tokens if token not in layout_text]
    if missing_layout:
        raise StaticReTestFailure(
            "Lightning Chaining native path is missing layout token(s): " +
            ", ".join(missing_layout))

    required_verifier_tokens = (
        'read_runtime_layout_offset("spell_cast_018")',
        'read_runtime_layout_offset("air_lightning_chain_target")',
        'read_runtime_layout_offset("actor_air_lightning_chain_count")',
        'emit("chain_count", ok and chain_count or "")',
        '"native_chain_state"',
        '"air_chain_sync"',
        'sd.world.get_replicated_air_chains',
        'build_air_chain_sync_evidence',
        '#selected - 127',
        '"applied_target_parity"',
        '"endpoint_error_ok"',
        '"applied_source_endpoint_parity"',
        '"applied_target_endpoint_parity"',
        '"source_override_failure_delta"',
        '"target_override_success_delta"',
        '"target_override_failure_delta"',
        'include_client=False',
        '"replicated_cast_delivery"',
        '"observer_native_cast_prepped"',
        "dispatcher_chain_count",
        "baseline_native_chain_evidence_ok",
        "upgraded_native_chain_evidence_ok",
    )
    missing_verifier = [
        token for token in required_verifier_tokens if token not in verifier_text
    ]
    if missing_verifier:
        raise StaticReTestFailure(
            "Lightning Chaining verifier is missing native behavior token(s): " +
            ", ".join(missing_verifier))
    if "0x00628F10" in verifier_text:
        raise StaticReTestFailure(
            "Lightning Chaining verifier still traces the unrelated Air action routine")
    if "trace_function(" in verifier_text or "untrace_function(" in verifier_text:
        raise StaticReTestFailure(
            "Lightning Chaining verifier still competes with the permanent target hook")

    required_network_tokens = (
        (protocol_text, "constexpr std::uint16_t kProtocolVersion = 64;"),
        (protocol_text, "AirChainSnapshot = 15"),
        (protocol_text, "kAirChainSnapshotMaxTargets = 8"),
        (protocol_text, "struct AirChainTargetPacketState"),
        (protocol_text, "struct AirChainSnapshotPacket"),
        (protocol_text, "static_assert(sizeof(AirChainSnapshotPacket) == 260"),
        (runtime_state_text, "AirChainSnapshotRuntimeInfo"),
        (runtime_state_text, "AirChainApplyRuntimeInfo"),
        (lua_gameplay_text, '"get_replicated_air_chains"'),
        (run_lifecycle_state_text, "kHookAirLightningChainTarget"),
        (run_lifecycle_state_text, "targets[kHookAirLightningChainTarget] = {kAirLightningChainTarget, 7}"),
        (spell_cast_hooks_text, "HookAirLightningChainTarget"),
        (spell_cast_hooks_text, "PublishLocalAirChainFrame"),
        (spell_cast_hooks_text, "ResolveReplicatedAirChainTarget"),
        (spell_cast_hooks_text, "ApplyAuthoritativeAirChainSourceEndpointToNativeCaller"),
        (spell_cast_hooks_text, "ApplyAuthoritativeAirChainTargetEndpointForNativeCopy"),
        (spell_cast_hooks_text, "RecordReplicatedAirChainTargetOverride"),
        (spell_cast_hooks_text, "kAirLightningChainTargetReturn"),
        (spell_cast_hooks_text, "kAirLightningChainSourceFromReturnSlotOffset"),
        (spell_cast_hooks_text, "kCallerSourceContractEpsilon"),
        (air_chain_sync_text, "RelayPacketToPeers(packet, from)"),
        (air_chain_sync_text, "kAirChainRuntimeHistoryCapacity = 128"),
        (air_chain_sync_text, "cumulative_override_success_count"),
        (air_chain_sync_text, "cumulative_unmapped_target_count"),
        (air_chain_sync_text, "cumulative_source_override_success_count"),
        (air_chain_sync_text, "cumulative_source_override_failure_count"),
        (air_chain_sync_text, "cumulative_target_override_success_count"),
        (air_chain_sync_text, "cumulative_target_override_failure_count"),
        (air_chain_sync_text, "binding.source_error_before_override"),
        (air_chain_sync_text, "binding.target_error_before_override"),
        (air_chain_sync_text, "return local_target.actor_address;"),
        (air_chain_sync_text, "An authoritative target that is not materialized"),
    )
    missing_network = [
        token for text, token in required_network_tokens if token not in text
    ]
    if missing_network:
        raise StaticReTestFailure(
            "Lightning Chaining authoritative target lane is incomplete: " +
            ", ".join(missing_network))

    exact_enemy_identity_tokens = (
        "if tonumber(binding.network_actor_id) == target_id",
        "bound_address = tonumber(binding.local_actor_address) or 0",
        "if not resolved and bound_address == 0 then",
        "clustered tests must never substitute a neighbour",
    )
    missing_enemy_identity = [
        token for token in exact_enemy_identity_tokens
        if token not in targeted_spell_matrix_text
    ]
    if missing_enemy_identity:
        raise StaticReTestFailure(
            "clustered spell verification can still read a neighbouring enemy instead of its exact binding: " +
            ", ".join(missing_enemy_identity))

    required_remote_start_tokens = (
        "IsSaneExplicitCastTarget(cast_target, packet.position_x, packet.position_y)",
        "cast_input_state.target_actor_address = resolved_target_actor_address",
        "if (!input_tracker.start_queued)",
        "if (QueueBotCast(request))",
    )
    missing_remote_start = [
        token for token in required_remote_start_tokens if token not in transport_text
    ]
    if missing_remote_start:
        raise StaticReTestFailure(
            "remote cast playback no longer queues targetless native presentation: " +
            ", ".join(missing_remote_start))
    forbidden_remote_start_tokens = (
        "air_primary_packet",
        "deferred_start_packet_count",
        "Multiplayer remote Air cast start deferred until exact target resolves",
    )
    present_remote_start = [
        token for token in forbidden_remote_start_tokens if token in transport_text
    ]
    if present_remote_start:
        raise StaticReTestFailure(
            "remote Air playback still suppresses a valid targetless cast: " +
            ", ".join(present_remote_start))

    required_targetless_air_regression_tokens = (
        'choices=("explode", "embers", "chaining", "targetless-air", "all")',
        "def verify_targetless_air(",
        'if args.behavior in ("targetless-air", "all"):',
        'animation.ELEMENT_BY_NAME["air"]',
        'flow["local_targetless_sequences"]',
        'flow["remote_targetless_queue_sequences"]',
        'flow["remote_prep_sequences"]',
        'flow["remote_release_sequences"]',
        'if not cast["active_seen"] or not cast["anim_seen"]:',
    )
    missing_targetless_air_regression = [
        token
        for token in required_targetless_air_regression_tokens
        if token not in active_pair_spell_text
    ]
    if missing_targetless_air_regression:
        raise StaticReTestFailure(
            "real-Steam targetless Air regression lacks exact lifecycle witness(es): "
            + ", ".join(missing_targetless_air_regression)
        )
    for token in (
        '"local_targetless_sequences": local_targetless_sequences',
        '"remote_targetless_queue_sequences": remote_targetless_queue_sequences',
        "target_network_actor_id=0 target_actor=0x0+ target_source=none",
        "require_remote_release=True",
        "receiver_deadline = time.monotonic() + 8.0",
    ):
        if token not in animation_verifier_text:
            raise StaticReTestFailure(
                "targetless Air flow parser lacks: " + token
            )

    forbidden_predicted_damage_tokens = (
        "TryResolveLocalPrimaryCastClaimDamage",
        "TrySendLocalCastEnemyDamageClaim",
        "local_cast_damage_claimed_sequences",
        "Multiplayer local cast damage claim sent from cast packet",
    )
    present_predicted_damage_tokens = [
        token for token in forbidden_predicted_damage_tokens
        if token in transport_text
    ]
    if present_predicted_damage_tokens:
        raise StaticReTestFailure(
            "cast press can still apply predicted spell output before native impact: " +
            ", ".join(present_predicted_damage_tokens))

    resolved_build_id_tokens = (
        "kProgressionCurrentSpellIdOffset,\n                    ongoing.skill_id",
        "request.secondary_slot,\n            ongoing.skill_id);",
    )
    missing_build_id = [
        token for token in resolved_build_id_tokens if token not in pending_cast_text
    ]
    if missing_build_id:
        raise StaticReTestFailure(
            "remote primary preparation still feeds a dispatcher entry to native spell stats: " +
            ", ".join(missing_build_id))
    dispatcher_build_tokens = (
        "const bool have_live_build =",
        "TryResolveNativePrimarySelectionFromLiveProgression(",
        "have_live_build ? live_selection.build_skill_id : -1",
    )
    missing_dispatcher_build = [
        token for token in dispatcher_build_tokens if token not in scene_selection_text
    ]
    if missing_dispatcher_build:
        raise StaticReTestFailure(
            "dispatcher-entry cast descriptors no longer retain their live Skills_Wizard build id: " +
            ", ".join(missing_dispatcher_build))

    return "Lightning Chaining verifies native delivery plus authoritative target IDs, endpoints, substitutions, and terminal state on both peers"


def test_primary_selection_mapping_is_native_backed_not_static_table() -> str:
    native_spell_stats_text = read_native_spell_stats_source()
    native_spell_stats_header_text = read_text(NATIVE_SPELL_STATS_HEADER)
    scene_text = read_text(SCENE_SELECTION)
    config_text = read_text(LUA_BOT_CONFIG)
    targeting_test_text = read_text(ROOT / "tools/test_lua_bots_targeting.lua")
    combined_text = "\n".join((
        native_spell_stats_text,
        native_spell_stats_header_text,
        scene_text,
        config_text,
        targeting_test_text,
    ))

    forbidden_tokens = (
        "NativePrimarySkillPair",
        "kNativePrimarySkillPairs",
        "PRIMARY_BUILD_SKILL_IDS",
        "[0] = 0x10",
        "[1] = 0x20",
        "[2] = 0x28",
        "[3] = 0x18",
        "[4] = 0x08",
    )
    present = [token for token in forbidden_tokens if token in combined_text]
    if present:
        raise StaticReTestFailure(
            "primary selection mapping still uses static hardcoded table token(s): " +
            ", ".join(present))

    required_tokens = (
        "TryResolveNativePrimaryEntryForElement",
        "TryResolveNativePrimarySelectionFromLiveProgression",
        "TryResolveNativePrimarySelectionFromSkillId",
        "kSkillsWizardBuildPrimarySpell",
        "kProgressionCurrentSpellIdOffset",
    )
    missing = [token for token in required_tokens if token not in combined_text]
    if missing:
        raise StaticReTestFailure(
            "primary selection mapping is missing native-backed resolver token(s): " +
            ", ".join(missing))

    return "primary selection mapping is backed by live Skills_Wizard output instead of a static table"


def test_primary_attack_window_uses_live_native_selection_range() -> str:
    lua_bots_binding_text = read_text(LUA_ENGINE_BOTS_BINDING)
    doc_text = read_text(LUA_BOT_CONSTANTS_RE_DOC)
    plan_text = read_text(NATIVE_SEAM_PLAN)
    targeting_test_text = read_text(ROOT / "tools/test_lua_bots_targeting.lua")

    forbidden_tokens = (
        "kProjectilePrimaryEngagementRange",
        "kBoulderPrimaryReleaseMinimumRange",
        "kWaterConeBaseRange",
        "kWaterConeRangePerShapeUnit",
        "kPrimaryEngagementSafetyMargin",
        "water_primary_native_base_cone",
        "water_primary_live_actor_cone",
        "projectile_primary_engagement",
        "earth_boulder_release_window",
        "max_range = 360.0",
        "max_range = 205.0",
        "min_range = 96.0",
    )
    combined_text = "\n".join((lua_bots_binding_text, targeting_test_text))
    present = [token for token in forbidden_tokens if token in combined_text]
    if present:
        raise StaticReTestFailure(
            "primary attack window still carries fixed engagement scalar token(s): " +
            ", ".join(present))

    required_tokens = (
        "ReadNativePrimarySelectionPursuitRange",
        "kActorAnimationSelectionStateOffset",
        "kActorControlBrainPursuitRangeOffset",
        "native_selection_pursuit_range",
        "FUN_0052C910",
        "actor_control_brain_pursuit_range",
    )
    evidence_text = "\n".join((lua_bots_binding_text, doc_text, plan_text))
    missing = [token for token in required_tokens if token not in evidence_text]
    if missing:
        raise StaticReTestFailure(
            "primary attack window is missing live native selection-range token(s): " +
            ", ".join(missing))

    drive_text = read_text(SCENE_ANIMATION_DRIVE_PROFILES)
    reset_start = drive_text.find("void ResetStandaloneWizardControlBrain")
    reset_end = drive_text.find("void ApplyStandaloneWizardPuppetDriveState", reset_start)
    if reset_start < 0 or reset_end < 0:
        raise StaticReTestFailure("ResetStandaloneWizardControlBrain was not found")
    if "kActorControlBrainPursuitRangeOffset" in drive_text[reset_start:reset_end]:
        raise StaticReTestFailure(
            "control-brain reset still clears the native primary pursuit range used by Lua attack windows")

    return "primary attack window reads the live native selection pursuit range"


def test_bot_level_sync_uses_native_level_up() -> str:
    skill_choices_text = read_bot_skill_choice_source()
    layout_text = read_text(BINARY_LAYOUT)
    skill_picker_doc_text = read_text(ROOT / "docs/skill-picker-re.md")

    required_layout_tokens = (
        "level_up=0x0067C250",
        "progression_level=0x30",
        "progression_xp=0x34",
        "progression_previous_xp_threshold=0x38",
        "progression_next_xp_threshold=0x3C",
        "progression_nonlocal_mode_flag=0x40",
        "progression_local_skill_picker_screen=0x83C",
    )
    missing_layout = [token for token in required_layout_tokens if token not in layout_text]
    if missing_layout:
        raise StaticReTestFailure(
            "native level-up layout evidence is missing token(s): " +
            ", ".join(missing_layout))

    required_code_tokens = (
        "using NativeLevelUpFn",
        "CallNativeLevelUpSafe",
        "kLevelUp",
        "SyncNativeBotProgressionLevel",
        "EnsureBotOwnedProgressionMode",
        "kProgressionNonLocalModeFlagOffset",
        "kProgressionNonLocalModeValue",
        "native level_up",
        "level_before",
        "level_after",
    )
    missing_code = [token for token in required_code_tokens if token not in skill_choices_text]
    if missing_code:
        raise StaticReTestFailure(
            "bot level sync is not wired through native level_up: " +
            ", ".join(missing_code))

    forbidden_direct_stat_writes = (
        (r"TryWriteField\s*<\s*std::int32_t\s*>\s*\(\s*progression_address\s*,\s*kProgressionLevelOffset", "level"),
        (r"TryWriteField\s*<\s*float\s*>\s*\(\s*progression_address\s*,\s*kProgressionHpOffset", "current HP"),
        (r"TryWriteField\s*<\s*float\s*>\s*\(\s*progression_address\s*,\s*kProgressionMaxHpOffset", "max HP"),
        (r"TryWriteField\s*<\s*float\s*>\s*\(\s*progression_address\s*,\s*kProgressionMpOffset", "current MP"),
        (r"TryWriteField\s*<\s*float\s*>\s*\(\s*progression_address\s*,\s*kProgressionMaxMpOffset", "max MP"),
    )
    present_direct_writes = [
        label for pattern, label in forbidden_direct_stat_writes
        if re.search(pattern, skill_choices_text)
    ]
    if present_direct_writes:
        raise StaticReTestFailure(
            "bot level sync still directly writes progression stat fields: " +
            ", ".join(present_direct_writes))

    required_doc_tokens = (
        "0x0067C250",
        "native level-up routine",
        "Bots call the same native `level_up` routine",
        "Bot-owned progressions are marked non-local through `progression + 0x40`",
        "does not write progression level, HP, max HP, MP, or max MP directly",
    )
    missing_doc = [token for token in required_doc_tokens if token not in skill_picker_doc_text]
    if missing_doc:
        raise StaticReTestFailure(
            "skill-picker RE doc does not describe the native bot level sync contract: " +
            ", ".join(missing_doc))

    return "bot level/stat sync uses native level_up instead of direct progression stat writes"


def test_native_stat_refresh_preserves_live_vitals() -> str:
    helper_cpp_text = read_native_spell_stats_source()
    preparation_text = read_text(PENDING_CAST_PREPARATION)
    builder_ghidra_text = read_text(PRIMARY_SPELL_BUILDER_GHIDRA)
    recompute_ghidra_text = read_text(ALLY_HP_RECOMPUTE_GHIDRA)

    required_native_tokens = (
        "CallSkillsWizardBuildPrimarySpellSafe",
        "TryReadNativePrimaryStatOutputs",
        "progression_runtime_address",
        "kProgressionPrimaryStatValuesOffset",
        "kProgressionPrimaryStatCountOffset",
    )
    missing_native = [token for token in required_native_tokens if token not in helper_cpp_text]
    if missing_native:
        raise StaticReTestFailure(
            "native primary stat query is missing native output-reader token(s): " +
            ", ".join(missing_native))

    forbidden_restore_tokens = (
        "ProgressionResourceSnapshot",
        "CaptureProgressionResourceSnapshot",
        "RestoreProgressionResourceSnapshot",
        "ProgressionVitalSnapshot",
        "CaptureProgressionVitals",
        "RestoreProgressionVitals",
    )
    present_restore_tokens = [
        token for token in forbidden_restore_tokens
        if token in helper_cpp_text or token in preparation_text
    ]
    if present_restore_tokens:
        raise StaticReTestFailure(
            "native stat/refresh path still uses loader-owned resource snapshot restore token(s): " +
            ", ".join(present_restore_tokens))

    forbidden_direct_restore_patterns = (
        (helper_cpp_text, "native_spell_stats.cpp"),
        (preparation_text, "pending_cast_preparation.inl"),
    )
    direct_restore_fields = (
        "kProgressionHpOffset",
        "kProgressionMaxHpOffset",
        "kProgressionMpOffset",
        "kProgressionMaxMpOffset",
    )
    direct_restore_hits: list[str] = []
    for text, label in forbidden_direct_restore_patterns:
        for field in direct_restore_fields:
            if re.search(
                rf"TryWriteField\s*<\s*float\s*>\s*\([^;]*{field}",
                text,
                re.S,
            ):
                direct_restore_hits.append(f"{label}:{field}")
    if direct_restore_hits:
        raise StaticReTestFailure(
            "native stat/refresh path still writes progression HP/MP directly: " +
            ", ".join(direct_restore_hits))

    refresh_call = preparation_text.find("CallActorProgressionRefreshSafe")
    if refresh_call == -1:
        raise StaticReTestFailure("cast preparation no longer calls native ActorProgressionRefresh")

    required_builder_evidence = (
        "FUNCTION FUN_00666020 @ 00666020",
        "*(undefined4 *)(param_1 + 0x750)",
        "param_1 + 0x774",
        "param_1 + 0x778",
    )
    missing_builder_evidence = [
        token for token in required_builder_evidence
        if token not in builder_ghidra_text
    ]
    if missing_builder_evidence:
        raise StaticReTestFailure(
            "primary spell builder Ghidra evidence is missing token(s): " +
            ", ".join(missing_builder_evidence))

    forbidden_builder_resource_writes = (
        "*(float *)(param_1 + 0x70)",
        "*(float *)(param_1 + 0x74)",
        "*(float *)(param_1 + 0x7c)",
        "*(float *)(param_1 + 0x80)",
        "param_1[0x1c] =",
        "param_1[0x1d] =",
        "param_1[0x1f] =",
        "param_1[0x20] =",
    )
    builder_resource_hits = [
        token for token in forbidden_builder_resource_writes
        if token in builder_ghidra_text.split("=== TARGET: 0x006741B0 ===", 1)[0]
    ]
    if builder_resource_hits:
        raise StaticReTestFailure(
            "primary spell builder evidence shows direct progression resource writes: " +
            ", ".join(builder_resource_hits))

    required_recompute_evidence = (
        "FUNCTION FUN_0065f9a0 @ 0065f9a0",
        "param_1[0x1c] = (int)((float)param_1[0x1d] * (fVar1 / fVar2));",
        "param_1[0x1f] = (int)((float)param_1[0x20] * (fVar3 / fVar4));",
    )
    missing_recompute_evidence = [
        token for token in required_recompute_evidence
        if token not in recompute_ghidra_text
    ]
    if missing_recompute_evidence:
        raise StaticReTestFailure(
            "ActorProgressionRefresh Ghidra evidence is missing native ratio-preserve token(s): " +
            ", ".join(missing_recompute_evidence))

    return "native stat query avoids resource writes and cast refresh uses native ratio-preserving recompute"


def test_bot_skill_upgrade_combat_probe_checks_native_damage_and_mana() -> str:
    probe_text = read_text(BOT_SKILL_UPGRADE_COMBAT_FLOW_LIVE_PROBE)
    readme_text = read_text(ROOT / "tests/re/README.md")

    required_tokens = (
        "query_primary_stat_output",
        "progression_primary_stat_values",
        "progression_primary_stat_count",
        "baseline_damage",
        "post_upgrade_damage",
        "post_damage <= baseline_damage",
        "baseline_stats_output.get(\"mana_cost\"",
        "post_stats_output.get(\"mana_cost\"",
        "entry_after.get(\"active\"",
        "profile_after.get(\"primary_entry_index\"",
    )
    missing = [token for token in required_tokens if token not in probe_text]
    if missing:
        raise StaticReTestFailure(
            "bot skill-upgrade combat probe no longer checks native output token(s): " +
            ", ".join(missing))

    required_doc_tokens = (
        "run_live_bot_skill_upgrade_combat_flow_probe.py",
        "reports increased",
        "damage and mana cost",
        "test_bot_skill_choice_regression.py --iterations 5 --active-bots all --min-bots 5",
    )
    missing_doc = [token for token in required_doc_tokens if token not in readme_text]
    if missing_doc:
        raise StaticReTestFailure(
            "RE test README is missing bot skill-upgrade coverage token(s): " +
            ", ".join(missing_doc))

    return "bot skill-upgrade combat probe checks native stat output damage, mana, entry, and loadout evidence"


def test_bot_element_damage_probe_supports_upgraded_primary_victim_validation() -> str:
    probe_text = read_text(BOT_ELEMENT_DAMAGE_PROBE)
    readme_text = read_text(ROOT / "tests/re/README.md")

    required_tokens = (
        "--apply-primary-upgrade",
        "apply_primary_upgrade_to_bot",
        "stress.debug_sync_level_up",
        "stress.choose_skill",
        "matched_primary_upgrade",
        "matching_native_mana_delta",
        "actual_victims",
        "any_hostile_damaged",
        "native_spell_stat_validation.get(\"ok\") is True",
        "native_target_lethal_waits_for_min_charge",
        "target_lethal_min_charge_ok",
    )
    missing = [token for token in required_tokens if token not in probe_text]
    if missing:
        raise StaticReTestFailure(
            "bot element damage probe no longer supports upgraded primary victim validation token(s): " +
            ", ".join(missing))

    run_element_match = re.search(
        r"def run_element_probe\(element: str, args: argparse\.Namespace\) -> dict\[str, object\]:(?P<body>.*?)\n\ndef ",
        probe_text,
        re.S,
    )
    if run_element_match is None:
        raise StaticReTestFailure("bot element damage probe run_element_probe block was not found")
    run_element_body = run_element_match.group("body")
    launch_index = run_element_body.find("result[\"navigation\"] = prepare_clean_run")
    config_index = run_element_body.find("config = element_config(element)")
    if launch_index == -1 or config_index == -1 or config_index < launch_index:
        raise StaticReTestFailure(
            "bot element damage probe resolves native primary entry before launching a clean Lua runtime")

    required_doc_tokens = (
        "run_live_bot_upgrade_damage_delta_probe.py",
        "probe_earth_baseline_35000_force_both_goal_confirm.json",
        "probe_earth_upgraded_35000_force_both_goal_confirm.json",
        "held Boulder release diagnostics",
        "skill picker",
        "native max-size release",
    )
    missing_doc = [token for token in required_doc_tokens if token not in readme_text]
    if missing_doc:
        raise StaticReTestFailure(
            "RE test README is missing upgraded primary victim validation token(s): " +
            ", ".join(missing_doc))

    return "bot element damage probe supports native-upgraded primary victim validation"


def test_bot_upgrade_damage_delta_probe_checks_native_mana_projection_and_release_policy() -> str:
    probe_text = read_text(BOT_UPGRADE_DAMAGE_DELTA_LIVE_PROBE)
    readme_text = read_text(ROOT / "tests/re/README.md")

    required_tokens = (
        "probe_earth_baseline_35000_force_both_goal_confirm.json",
        "probe_earth_upgraded_35000_force_both_goal_confirm.json",
        "DEFAULT_TARGET_HP = 35000.0",
        "DEFAULT_CAST_INTERVAL_SECONDS = 30.0",
        "MIN_POST_RELEASE_TICKS = 3",
        "DEFAULT_CHILD_ATTEMPTS = 2",
        "DEFAULT_CHILD_TIMEOUT_SECONDS = 240.0",
        "subprocess.TimeoutExpired",
        "child_artifact_has_native_boulder_release",
        "native_boulder_release_artifact",
        "output.unlink()",
        "--cast-interval-seconds",
        "--apply-primary-upgrade",
        "--positioning",
        "force_both",
        "matched_primary_upgrade",
        "live_progression_primary_stat_output",
        "upgraded native mana cost did not increase",
        "upgraded native boulder projected damage did not increase",
        "baseline did not use native max-size release",
        "upgraded native release was not max-size",
        "upgraded max-size release did not write release charge",
        "removed threshold-release fields",
        "native post-release launch window",
    )
    missing = [token for token in required_tokens if token not in probe_text]
    if missing:
        raise StaticReTestFailure(
            "bot upgrade damage delta probe no longer checks native upgrade projection token(s): " +
            ", ".join(missing))

    required_doc_tokens = (
        "run_live_bot_upgrade_damage_delta_probe.py",
        "same high-HP Earth setup twice",
        "force_both",
        "extended Earth cast window",
        "target HP is intentionally above",
        "upgraded max-size Boulder projection",
        "native Boulder upgrade",
        "native mana cost",
        "projected damage increase",
        "native max-size release",
        "incidental HP loss as proof",
    )
    missing_doc = [token for token in required_doc_tokens if token not in readme_text]
    if missing_doc:
        raise StaticReTestFailure(
            "RE test README is missing bot upgrade damage delta coverage token(s): " +
            ", ".join(missing_doc))

    return "bot upgrade damage delta probe checks native mana and projected damage without threshold-release shortcuts"


def test_synthetic_source_profile_blocker_is_documented() -> str:
    doc_text = read_text(SOURCE_PROFILE_RE_DOC)
    plan_text = read_text(NATIVE_SEAM_PLAN)
    clone_source_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/standalone_materialization_wizard_clone_source.inl"
    )
    slot_creation_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/standalone_materialization_slot_bot_creation.inl"
    )
    constants_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/gameplay_constants.inl"
    )
    project_text = read_text(MOD_LOADER_PROJECT)
    negative_scan_text = read_text(SOURCE_PROFILE_NEGATIVE_GHIDRA)
    actor174_scan_text = read_text(SOURCE_PROFILE_ACTOR174_EXPANDED_GHIDRA)
    field_candidate_text = read_text(SOURCE_PROFILE_FIELD_CANDIDATE_GHIDRA)
    write_site_text = read_text(SOURCE_PROFILE_WRITE_SITES_EXPANDED_GHIDRA)
    live_probe_text = read_text(SOURCE_PROFILE_NEGATIVE_LIVE_PROBE)
    writer_probe_text = read_text(SOURCE_PROFILE_WRITER_LIVE_PROBE)
    layout_text = read_text(BINARY_LAYOUT)
    required_doc_tokens = (
        "0x005E3080",
        "0x0061AA00",
        "0x005B7080",
        "0x005E9A90",
        "0x005D0290",
        "0x00515290",
        "0x00660760",
        "0x0040FC60",
        "That hardcoded workaround is removed",
        "native-derived source-profile staging",
        "source-profile preimage",
        "source actor's own",
        "runtime/ghidra_synthetic_source_profile_paths.txt",
        "runtime/ghidra_source_profile_negative_producer_scan.txt",
        "runtime/ghidra_source_profile_actor174_expanded_scan.txt",
        "runtime/ghidra_source_profile_field_candidate_decompiles.txt",
        "runtime/ghidra_source_profile_write_sites_expanded.txt",
        "runtime/live_source_profile_negative_probe.json",
        "runtime/live_source_profile_writer_probe.json",
        "BuildNativeDerivedWizardSourceProfile",
        "SeedWizardCloneSourceActorFromNativeDerivedProfile",
        "native element color seam",
        "cloth and trim",
        "CallSkillsWizardGetPrimaryColorSafe",
        "kWizardCloneSourceActorKind == 3",
    )
    missing_doc_tokens = [token for token in required_doc_tokens if token not in doc_text]
    if missing_doc_tokens:
        raise StaticReTestFailure(
            "synthetic source-profile RE doc is missing token(s): " +
            ", ".join(missing_doc_tokens))
    required_negative_scan_tokens = (
        "0x005B7080",
        "0x005E9A90",
        "zeroes",
        "actor+0x174",
        "actor+0x178",
        "not a source-profile materializer",
        "0x005E2AE0",
        "0x005EA1C0",
        "0x005EA350",
    )
    missing_negative_scan_tokens = [
        token for token in required_negative_scan_tokens if token not in negative_scan_text
    ]
    if missing_negative_scan_tokens:
        raise StaticReTestFailure(
            "synthetic source-profile negative scan is missing token(s): " +
            ", ".join(missing_negative_scan_tokens))
    required_actor174_scan_tokens = (
        "0x00515290",
        "0x139a",
        "0x139e",
    )
    missing_actor174_scan_tokens = [
        token for token in required_actor174_scan_tokens if token not in actor174_scan_text
    ]
    if missing_actor174_scan_tokens:
        raise StaticReTestFailure(
            "synthetic source-profile actor+0x174 expanded scan is missing token(s): " +
            ", ".join(missing_actor174_scan_tokens))
    required_field_candidate_tokens = (
        "0x005E3080",
        "0x0061AA00",
        "=== TARGET: 0x005E3080 ===",
        "=== TARGET: 0x0061AA00 ===",
    )
    missing_field_candidate_tokens = [
        token for token in required_field_candidate_tokens if token not in field_candidate_text
    ]
    if missing_field_candidate_tokens:
        raise StaticReTestFailure(
            "synthetic source-profile field-candidate decompile artifact is missing token(s): " +
            ", ".join(missing_field_candidate_tokens))
    required_write_site_tokens = (
        "FUN_00515290",
        "FUN_005e9a90",
        "[EAX + 0x174]",
        "[ESI + 0x178]",
    )
    missing_write_site_tokens = [
        token for token in required_write_site_tokens if token not in write_site_text
    ]
    if missing_write_site_tokens:
        raise StaticReTestFailure(
            "synthetic source-profile expanded write-site scan is missing token(s): " +
            ", ".join(missing_write_site_tokens))
    required_live_probe_tokens = (
        "live_source_profile_negative_probe.json",
        "actor_hub_visual_source_profile",
        "hub_visual_source_profile_address",
        "native_derived_visual_seed_before",
        "native_derived_visual_seed_after",
        "native-derived source profile",
        "native-derived clone-source seeded",
        "clone_source_ready",
        "actor+0x178",
    )
    missing_live_probe_tokens = [token for token in required_live_probe_tokens if token not in live_probe_text]
    if missing_live_probe_tokens:
        raise StaticReTestFailure(
            "synthetic source-profile live negative probe is missing token(s): " +
            ", ".join(missing_live_probe_tokens))
    required_writer_probe_tokens = (
        "live_source_profile_writer_probe.json",
        "source_actor_ctor",
        "source_profile_actor174_candidate_setup",
        "player_source_write_hits",
        "actor+0x178",
        "native-derived source-profile staging",
        "lua_bots_disable_tick",
        "wait_for_player_visual_state",
    )
    missing_writer_probe_tokens = [
        token for token in required_writer_probe_tokens if token not in writer_probe_text
    ]
    if missing_writer_probe_tokens:
        raise StaticReTestFailure(
            "synthetic source-profile live writer probe is missing token(s): " +
            ", ".join(missing_writer_probe_tokens))
    required_layout_tokens = (
        "source_actor_ctor=0x005E9A90",
        "source_profile_actor174_candidate_setup=0x00515290",
    )
    missing_layout_tokens = [token for token in required_layout_tokens if token not in layout_text]
    if missing_layout_tokens:
        raise StaticReTestFailure(
            "synthetic source-profile trace layout is missing token(s): " +
            ", ".join(missing_layout_tokens))
    removed_paths = (
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/synthetic_wizard_source_profiles.inl",
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/standalone_materialization_wizard_element_colors.inl",
    )
    still_present = [str(path.relative_to(ROOT)) for path in removed_paths if path.exists()]
    if still_present:
        raise StaticReTestFailure(
            "removed synthetic source-profile runtime file(s) still exist: " +
            ", ".join(still_present))
    removed_runtime_tokens = (
        "CreateSyntheticWizardSourceProfile",
        "DestroySyntheticWizardSourceProfile",
        "kWizardSourceProfileTemplates",
        "ResolveWizardAppearanceChoiceIds",
        "GetWizardElementColor",
        "kSyntheticSourceProfileSize",
        "source_profile_created",
        "source_profile_staged",
        "descriptor_build_before",
        "descriptor_build_after",
    )
    runtime_texts = {
        "clone source": clone_source_text,
        "slot creation": slot_creation_text,
        "constants": constants_text,
        "project": project_text,
    }
    regressions = [
        f"{name}: still contains {token}"
        for name, text in runtime_texts.items()
        for token in removed_runtime_tokens
        if token in text
    ]
    required_runtime_tokens = (
        "BuildNativeDerivedWizardSourceProfile",
        "native_element_color",
        "TryBuildSourceProfileColorPreimage",
        "TryReadNativeSourceActorDefaultTrimColor",
        "source_profile_cloth_color",
        "native_default_trim_color",
        "CallSkillsWizardGetPrimaryColorSafe",
        "ResolveNativePrimaryEntryForElement",
        "SeedWizardCloneSourceActorFromNativeDerivedProfile",
        "CaptureActorRenderBuildSnapshot",
        "ApplySourceActorRenderSelectorsToTargetActor",
        "AttachBuiltDescriptorToEquipVisualLane",
        "CallActorBuildRenderDescriptorFromSourceSafe",
        "kWizardCloneSourceActorKind",
        "native_visual_actor_address",
    )
    missing_runtime_tokens = [
        token for token in required_runtime_tokens
        if token not in clone_source_text and token not in slot_creation_text and token not in constants_text
    ]
    if missing_runtime_tokens:
        regressions.append(
            "native visual snapshot runtime is missing token(s): " +
            ", ".join(missing_runtime_tokens))
    if regressions:
        raise StaticReTestFailure(
            "synthetic source-profile runtime removal is incomplete: " +
            "; ".join(regressions))
    if re.search(r"CreateWizardCloneSourceActor[\s\S]*SeedWizardCloneSourceActorFromNativeVisualActor", clone_source_text):
        raise StaticReTestFailure(
            "CreateWizardCloneSourceActor still routes through snapshot-only visual seeding")
    if not re.search(
        r"\| Synthetic source profiles \|[^\n]*removed hardcoded profile buffer[^\n]*\|[^\n]*0x00660760[^\n]*\|[^\n]*native-derived source profile",
        plan_text,
    ):
        raise StaticReTestFailure(
            "native seam plan does not document the native-derived source-profile replacement")
    return "hardcoded synthetic source-profile code is removed and native-derived visual staging is documented"


def test_default_ally_hp_native_constructor_evidence_is_recorded() -> str:
    progress_text = read_text(ALLY_HP_PROGRESS_GHIDRA)
    recompute_text = read_text(ALLY_HP_RECOMPUTE_GHIDRA)
    clone_text = read_text(SYNTHETIC_SOURCE_PROFILE_GHIDRA)
    doc_text = read_text(ALLY_HP_RE_DOC)
    layout_text = read_text(BINARY_LAYOUT)
    plan_text = read_text(NATIVE_SEAM_PLAN)

    required_layout_tokens = (
        "standalone_wizard_visual_runtime_ctor=0x00674EE0",
        "wizard_clone_from_source_actor=0x0061AA00",
        "wizard_default_hp=0x00784CF8",
        "wizard_default_mp=0x007DE9B8",
        "progression_hp=0x70",
        "progression_max_hp=0x74",
        "progression_mp=0x7C",
        "progression_max_mp=0x80",
    )
    missing_layout = [token for token in required_layout_tokens if token not in layout_text]
    if missing_layout:
        raise StaticReTestFailure(
            "ally HP native layout evidence is missing token(s): " +
            ", ".join(missing_layout))

    constructor_tokens = (
        "FUNCTION FUN_00674ee0 @ 00674ee0",
        "param_1[0x1d] = param_1[0x1b];",
        "param_1[0x1c] = param_1[0x1b];",
        "param_1[0x20] = local_934;",
        "param_1[0x1f] = local_934;",
    )
    missing_constructor = [token for token in constructor_tokens if token not in progress_text]
    if missing_constructor:
        raise StaticReTestFailure(
            "ally HP constructor Ghidra evidence is missing token(s): " +
            ", ".join(missing_constructor))

    recompute_tokens = (
        "FUNCTION FUN_0065f9a0 @ 0065f9a0",
        "fVar1 = (float)param_1[0x1c];",
        "fVar2 = (float)param_1[0x1d];",
        "fVar3 = (float)param_1[0x1f];",
        "fVar4 = (float)param_1[0x20];",
        "param_1[0x1c] = (int)((float)param_1[0x1d] * (fVar1 / fVar2));",
        "param_1[0x1f] = (int)((float)param_1[0x20] * (fVar3 / fVar4));",
    )
    missing_recompute = [token for token in recompute_tokens if token not in recompute_text]
    if missing_recompute:
        raise StaticReTestFailure(
            "ally HP recompute Ghidra evidence is missing token(s): " +
            ", ".join(missing_recompute))

    clone_tokens = (
        "FUNCTION FUN_0061aa00 @ 0061aa00",
        "iVar9 = FUN_00674ee0();",
        "FUN_0065f9a0();",
    )
    missing_clone = [token for token in clone_tokens if token not in clone_text]
    if missing_clone:
        raise StaticReTestFailure(
            "clone-from-source path does not prove constructor + recompute call(s): " +
            ", ".join(missing_clone))

    default_hp_global = read_layout_numeric(BINARY_LAYOUT, NATIVE_WIZARD_DEFAULT_HP_GLOBAL_KEY)
    default_mp_global = read_layout_numeric(BINARY_LAYOUT, NATIVE_WIZARD_DEFAULT_MP_GLOBAL_KEY)
    default_hp = read_pe_float_by_va(STAGED_BINARY, default_hp_global)
    default_mp = read_pe_float_by_va(STAGED_BINARY, default_mp_global)
    if not math.isclose(default_hp, 50.0, rel_tol=0.0, abs_tol=0.001):
        raise StaticReTestFailure(f"unexpected native wizard HP default: {default_hp}")
    if not math.isclose(default_mp, 100.0, rel_tol=0.0, abs_tol=0.001):
        raise StaticReTestFailure(f"unexpected native wizard MP default: {default_mp}")

    required_doc_tokens = (
        "0x00674EE0",
        "0x0061AA00",
        "0x0065F9A0",
        "0x00784CF8",
        "0x007DE9B8",
        "runtime/ghidra_ally_hp_progression_paths.txt",
        "runtime/ghidra_ally_hp_recompute_candidate.txt",
        "tests/re/run_live_ally_hp_native_defaults_probe.py",
    )
    missing_doc = [token for token in required_doc_tokens if token not in doc_text]
    if missing_doc:
        raise StaticReTestFailure(
            "ally HP RE doc is missing token(s): " +
            ", ".join(missing_doc))
    if not re.search(
        r"\| Default ally HP \|[^\n]+\|[^\n]*0x00674EE0[^\n]*0x0065F9A0[^\n]*\|",
        plan_text,
    ):
        raise StaticReTestFailure(
            "native seam plan does not record the recovered ally HP constructor/recompute evidence")
    return "native clone path initializes ally HP/MP from constructor defaults and preserves full ratios"


def test_default_ally_hp_spawn_paths_preserve_native_defaults() -> str:
    failures: list[str] = []
    for label, path in (("standalone", SPAWN_STANDALONE_WIZARD),):
        text = read_text(path)
        forbidden_tokens = (
            "kDefaultAllyHp",
            "25.0f",
            "kProgressionHpOffset",
            "kProgressionMaxHpOffset",
        )
        present = [token for token in forbidden_tokens if token in text]
        if present:
            failures.append(f"{label}: hardcoded ally HP token(s) remain: {', '.join(present)}")
        if (
            "kActorAnimationSelectionStateOffset" not in text or
            "kActorControlBrainFollowLeaderOffset" not in text
        ):
            failures.append(f"{label}: clone selection-state priming was unexpectedly removed")
        if (
            "EnsureBotOwnedProgressionMode" not in text or
            "standalone_clone_spawn" not in text
        ):
            failures.append(f"{label}: standalone clone progression is not forced into bot-owned non-local mode")
    if failures:
        raise StaticReTestFailure("; ".join(failures))
    return "standalone clone rail preserves native HP defaults and bot-owned progression mode"


def test_participant_transform_updates_preserve_exact_hub_sync() -> str:
    update_text = read_text(BOT_REGISTRY_AND_MOVEMENT_SPAWN)
    entity_update_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/execute_requests/entity_update_and_rail_selection.inl"
    )
    if "placement_probe_actor_address = binding->actor_address" in update_text:
        raise StaticReTestFailure(
            "participant transform updates still validate placement from the existing bot actor; "
            "far-away bots can resolve teleport/update requests back near stale positions"
        )
    required_tokens = (
        "request.has_transform && !validate_placement",
        "*out_x = x;",
        "placement_probe_actor_address = local_actor_address",
        "TryResolveNearestTraversablePlacement(",
        "far-away bot does not force the",
    )
    missing = [token for token in required_tokens if token not in update_text]
    if missing:
        raise StaticReTestFailure(
            "participant transform resolver contract is missing token(s): " +
            ", ".join(missing))
    update_required_tokens = (
        "validate_transform_placement",
        "ParticipantSceneIntentKind::SharedHub",
        "request.scene_intent.kind !=",
    )
    missing_update = [token for token in update_required_tokens if token not in entity_update_text]
    if missing_update:
        raise StaticReTestFailure(
            "participant hub update exact-sync contract is missing token(s): " +
            ", ".join(missing_update))
    return "hub transform updates preserve exact requested positions while spawns still validate placement"


def test_enemy_spawn_scaling_native_wave_seam_is_documented() -> str:
    doc_text = read_text(WAVE_SCALING_RE_DOC)
    ghidra_text = read_text(ENEMY_WAVE_GHIDRA)
    call_shape_text = read_text(ENEMY_SPAWN_CALL_SHAPES_GHIDRA)
    live_probe_text = read_text(ENEMY_SPAWN_API_REMOVED_LIVE_PROBE)
    queue_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_request_queues.inl"
    )
    constants_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/gameplay_constants.inl"
    )
    lua_gameplay_text = read_text(ROOT / "SolomonDarkModLoader/src/lua_engine_bindings_gameplay.cpp")
    public_api_text = read_text(ROOT / "SolomonDarkModLoader/include/mod_loader.h")
    element_damage_probe_text = read_text(ROOT / "tools/probe_bot_element_damage.py")
    execute_request_include_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_execute_requests.inl"
    )

    required_doc_tokens = (
        "0x0046D000",
        "0x0046C9A0",
        "0x0046B390",
        "0x00469580",
        "Generate or overlay a scaled `data/wave.txt`",
        "Do not reintroduce a manual Lua/API `sd.world.spawn_enemy(...)` path",
        "runtime/ghidra_enemy_wave_spawn_paths.txt",
        "runtime/ghidra_enemy_spawn_call_shapes.txt",
        "tests/re/run_live_enemy_spawn_api_removed_probe.py",
        "`sd.world.spawn_enemy(...)` and `sd.world.get_last_spawned_enemy(...)` are no",
    )
    missing_doc = [token for token in required_doc_tokens if token not in doc_text]
    if missing_doc:
        raise StaticReTestFailure(
            "wave scaling RE doc is missing token(s): " +
            ", ".join(missing_doc))

    required_ghidra_tokens = (
        "FUNCTION FUN_0046d000 @ 0046d000",
        "FUNCTION FUN_0046c9a0 @ 0046c9a0",
        "FUNCTION FUN_0046b390 @ 0046b390",
        "FUNCTION FUN_00469580 @ 00469580",
        "param_1[8] = param_1[8] + -1;",
        "*(float *)(param_4 + 0x58) = *(float *)(param_1 + 0x9008) * *(float *)(param_4 + 0x58);",
        "*(float *)(iVar1 + 0x174) = (float)*(int *)(param_1 + 0x8fe4) * *(float *)(iVar1 + 0x174);",
        "uVar6 = FUN_00649f40(0);",
    )
    missing_ghidra = [token for token in required_ghidra_tokens if token not in ghidra_text]
    if missing_ghidra:
        raise StaticReTestFailure(
            "enemy wave Ghidra artifact is missing token(s): " +
            ", ".join(missing_ghidra))

    required_call_shape_tokens = (
        "0x0046BD82",
        "0x0046BCD0",
        "0x004890FB",
        "0x00689F14",
        "anchor=0",
        "mode=0",
        "mode=1",
        "Keep `sd.world.spawn_enemy(...)` removed",
    )
    missing_call_shapes = [token for token in required_call_shape_tokens if token not in call_shape_text]
    if missing_call_shapes:
        raise StaticReTestFailure(
            "enemy spawn call-shape artifact is missing token(s): " +
            ", ".join(missing_call_shapes))

    required_live_probe_tokens = (
        "Live regression probe for removal of the manual enemy-spawn API",
        "spawn_enemy_type",
        "get_last_spawned_enemy_type",
        '"spawn_enemy_type": "nil"',
        '"get_last_spawned_enemy_type": "nil"',
        "wait_for_nearest_enemy",
    )
    missing_live_probe_tokens = [token for token in required_live_probe_tokens if token not in live_probe_text]
    if missing_live_probe_tokens:
        raise StaticReTestFailure(
            "enemy spawn API-removal live probe is missing token(s): " +
            ", ".join(missing_live_probe_tokens))

    removed_runtime_tokens = (
        "QueueEnemySpawnRequest",
        "PendingEnemySpawnRequest",
        "ExecuteSpawnEnemyNow",
        "CallSpawnEnemyInternal",
        "SpawnEnemyByType",
        "TryGetLastEnemySpawnResult",
        "LuaWorldSpawnEnemy",
        "LuaWorldGetLastSpawnedEnemy",
        "PushEnemySpawnResult",
        "kSpawnEnemyVariantDefault",
        "kSpawnEnemyAllowOverrideDefault",
        "context->spawn_enemy(",
        'RegisterFunction(state, &LuaWorldSpawnEnemy, "spawn_enemy")',
        'RegisterFunction(state, &LuaWorldGetLastSpawnedEnemy, "get_last_spawned_enemy")',
    )
    runtime_sources = {
        "queue": queue_text,
        "constants": constants_text,
        "lua gameplay bindings": lua_gameplay_text,
        "public api": public_api_text,
        "execute request includes": execute_request_include_text,
        "element damage probe": element_damage_probe_text,
    }
    regressions = [
        f"{source_name}: still contains {token}"
        for source_name, source_text in runtime_sources.items()
        for token in removed_runtime_tokens
        if token in source_text
    ]
    if (ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/execute_requests/spawn_enemy.inl").exists():
        regressions.append("execute_requests/spawn_enemy.inl still exists")
    if "sd.world.spawn_enemy" in element_damage_probe_text:
        regressions.append("element damage probe still depends on manual enemy spawn")
    if regressions:
        raise StaticReTestFailure(
            "manual enemy spawn API was not fully removed from active code: " +
            "; ".join(regressions))

    return "enemy scaling is backed by native wave-spawner evidence; manual spawn API is removed from active code"


def test_pathfinding_movement_layout_is_named_and_documented() -> str:
    doc_text = read_text(PATHFINDING_RE_DOC)
    ghidra_text = read_text(PATHFINDING_MOVEMENT_GHIDRA)
    scalar_text = read_text(PATHFINDING_POLICY_SCALARS_GHIDRA)
    scalar_decompile_text = read_text(PATHFINDING_POLICY_SCALAR_DECOMPILE_GHIDRA)
    float_globals_text = read_text(PATHFINDING_POLICY_FLOAT_GLOBALS_GHIDRA)
    live_probe_text = read_text(PATHFINDING_LAYOUT_LIVE_PROBE)
    layout_text = read_text(BINARY_LAYOUT)
    grid_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_pathfinding_grid_setup.inl"
    )
    cell_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_pathfinding_cell_math.inl"
    )
    traversability_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_pathfinding_traversability.inl"
    )
    seam_text = read_text(ROOT / "SolomonDarkModLoader/src/gameplay_seams/size_bindings.inl")
    debug_text = read_text(
        ROOT / "SolomonDarkModLoader/src/lua_engine_bindings_debug/functions_nav_grid_and_copy.inl"
    )
    crash_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/crash_summary_builders.inl"
    )
    plan_text = read_text(NATIVE_SEAM_PLAN)

    required_doc_tokens = (
        "runtime/ghidra_pathfinding_movement_paths.txt",
        "0x00525800",
        "0x005238C0",
        "0x005E9D50",
        "0x005EA450",
        "0x006042C0",
        "loader-owned A*",
        "arbitrary point A-to-B path planner",
        "runtime/ghidra_pathfinding_policy_scalar_scan.txt",
        "0x005E1E20",
        "0x005E3D60",
        "0x007DE984",
        "[gameplay.pathfinding]",
    )
    missing_doc = [token for token in required_doc_tokens if token not in doc_text]
    if missing_doc:
        raise StaticReTestFailure(
            "pathfinding RE doc is missing token(s): " +
            ", ".join(missing_doc))

    required_ghidra_tokens = (
        "FUNCTION FUN_00525800 @ 00525800",
        "FUNCTION FUN_005238c0 @ 005238c0",
        "FUNCTION FUN_00523c90 @ 00523c90",
        "FUNCTION FUN_005e9d50 @ 005e9d50",
        "FUNCTION FUN_005ea450 @ 005ea450",
        "FUNCTION FUN_006042c0 @ 006042c0",
        "*(int *)(param_1 + 0xb4)",
        "*(int *)(param_1 + 0xa0)",
        "*(undefined1 *)(param_1 + 0x198) = 1;",
        "*(char *)(param_1 + 0x1c2) = (char)param_2;",
    )
    missing_ghidra = [token for token in required_ghidra_tokens if token not in ghidra_text]
    if missing_ghidra:
        raise StaticReTestFailure(
            "pathfinding movement Ghidra artifact is missing token(s): " +
            ", ".join(missing_ghidra))

    required_scalar_tokens = (
        "=== SCALAR 8196 / 0x2004",
        "005e3d96 op1 MOV dword ptr [ESI + 0x14],0x2004",
        "=== SCALAR 3006 / 0xbbe",
        "005e1e59 op1 MOV dword ptr [ESI + 0x8],0xbbe",
        "005f4448 op1 CMP dword ptr [ECX + 0x8],0xbbe",
    )
    missing_scalar = [token for token in required_scalar_tokens if token not in scalar_text]
    if missing_scalar:
        raise StaticReTestFailure(
            "pathfinding policy scalar scan is missing token(s): " +
            ", ".join(missing_scalar))

    required_scalar_decompile_tokens = (
        "FUNCTION FUN_005e1e20 @ 005e1e20",
        "param_1[2] = 0xbbe;",
        "param_1[5] = 4;",
        "FUNCTION FUN_005e3d60 @ 005e3d60",
        "param_1[5] = 0x2004;",
        "FUNCTION FUN_005f43e0 @ 005f43e0",
        "*(int *)(iVar4 + 8) == 0xbbe",
    )
    missing_scalar_decompile = [
        token for token in required_scalar_decompile_tokens if token not in scalar_decompile_text
    ]
    if missing_scalar_decompile:
        raise StaticReTestFailure(
            "pathfinding policy scalar decompile is missing token(s): " +
            ", ".join(missing_scalar_decompile))

    required_float_global_tokens = (
        "0x007DE984  bytes=00002041  float=10",
        "0x007DE9D0  bytes=00000040  float=2",
    )
    missing_float_globals = [
        token for token in required_float_global_tokens if token not in float_globals_text
    ]
    if missing_float_globals:
        raise StaticReTestFailure(
            "pathfinding policy float-global dump is missing token(s): " +
            ", ".join(missing_float_globals))

    required_layout_tokens = (
        "movement_controller_cells=0xB4",
        "movement_controller_grid_height=0xD8",
        "movement_controller_grid_width=0xDC",
        "movement_controller_cell_width=0xE0",
        "movement_controller_cell_height=0xE4",
        "movement_controller_circle_count=0xA0",
        "movement_controller_circle_list=0xAC",
        "movement_circle_mask=0x14",
        "movement_circle_x=0x18",
        "movement_circle_y=0x1C",
        "movement_circle_radius=0x30",
        "gamenpc_move_flag=0x198",
        "gamenpc_goal_x=0x19C",
        "gamenpc_goal_y=0x1A0",
        "gamenpc_tracked_slot=0x1C2",
        "gamenpc_tracked_slot_callback=0x1C3",
        "[gameplay.pathfinding]",
        "cell_placement_sample_resolution=5",
        "cell_line_sample_resolution=12",
        "static_circle_obstacle_mask=0x00000004",
        "pushable_circle_obstacle_mask=0x00002000",
        "push_through_gate_circle_object_type=0x00000BBE",
        "push_through_gate_circle_radius=10",
        "push_through_gate_radius_epsilon_milliunits=10",
        "max_static_circle_obstacles=8192",
    )
    missing_layout = [token for token in required_layout_tokens if token not in layout_text]
    if missing_layout:
        raise StaticReTestFailure(
            "movement/GameNpc layout is missing token(s): " +
            ", ".join(missing_layout))

    required_code_tokens = (
        (grid_text, "path grid", "kMovementControllerCellsOffset"),
        (grid_text, "path grid", "kMovementControllerGridHeightOffset"),
        (grid_text, "path grid", "kMovementCircleMaskOffset"),
        (grid_text, "path grid", "GameplayPathStaticCircleObstacleMask()"),
        (grid_text, "path grid", "GameplayPathPushThroughGateCircleObjectType()"),
        (cell_text, "path cell sampling", "GameplayPathCellLineSampleResolution()"),
        (cell_text, "path cell sampling", "GameplayPathCellPlacementSampleResolution()"),
        (traversability_text, "path traversability", "GameplayPathPushableCircleObstacleMask()"),
        (seam_text, "gameplay seams", 'SDMOD_SIZE("gameplay.pathfinding", "static_circle_obstacle_mask"'),
        (debug_text, "debug geometry", "kMovementControllerPrimaryCountOffset"),
        (debug_text, "debug geometry", "kGameNpcGoalXOffset"),
        (crash_text, "crash summaries", "kMovementControllerPrimaryCountOffset"),
    )
    missing_code = [
        f"{label}:{token}" for text, label, token in required_code_tokens if token not in text
    ]
    if missing_code:
        raise StaticReTestFailure(
            "movement/GameNpc code is not layout-backed: " +
            ", ".join(missing_code))

    forbidden_patterns = (
        (grid_text, "path grid", r"ReadFieldOr<[^>]+>\(controller_address,\s*0x(?:B4|D8|DC|E0|E4)"),
        (grid_text, "path grid", r"constexpr\s+(?:int|float|std::uint32_t|std::size_t)\s+kGameplayPath"),
        (grid_text, "path grid", r"0x0000(?:0004|2000|0BBE)"),
        (grid_text, "path grid", r"\b10\.0f\b"),
        (cell_text, "path cell sampling", r"constexpr\s+int\s+kGameplayPathCellLineSampleResolution"),
        (cell_text, "path cell sampling", r"kGameplayPathCellPlacementSampleResolution\s*;"),
        (traversability_text, "path traversability", r"kGameplayPath(?:StaticCircleObstacleMask|PushableCircleObstacleMask)(?!\()"),
        (debug_text, "debug geometry", r"constexpr std::size_t kWorldMovementControllerOffset = 0x378"),
        (debug_text, "debug geometry", r"constexpr std::size_t kMovementCircleCountOffset = 0xA0"),
        (crash_text, "crash summaries", r"ReadFieldOr<[^>]+>\(movement_controller_address,\s*0x(?:40|4C|70|7C)"),
    )
    present_forbidden = [
        label for text, label, pattern in forbidden_patterns if re.search(pattern, text)
    ]
    if present_forbidden:
        raise StaticReTestFailure(
            "raw recovered movement/GameNpc offsets remain in: " +
            ", ".join(present_forbidden))

    if not re.search(
        r"\| Pathfinding policy \|[^\n]+\|[^\n]*runtime/ghidra_pathfinding_movement_paths.txt[^\n]*\|",
        plan_text,
    ):
        raise StaticReTestFailure("native seam plan does not cite the pathfinding movement artifact")

    required_live_probe_tokens = (
        "query_movement_circle_policy_sample",
        "static_circle_obstacle_mask",
        "push_through_gate_circle_object_type",
        "gate_radius_match_count",
        "movement_circle_policy",
    )
    missing_live_probe = [token for token in required_live_probe_tokens if token not in live_probe_text]
    if missing_live_probe:
        raise StaticReTestFailure(
            "live pathfinding layout probe is missing policy-scalar coverage token(s): " +
            ", ".join(missing_live_probe))

    return "movement grid, circle, GameNpc, and pathfinding policy values are documented and layout-backed"


def test_player_gamenpc_movement_seed_layout_is_named_and_documented() -> str:
    doc_text = read_text(PATHFINDING_RE_DOC)
    ghidra_text = read_text(PLAYER_GAMENPC_MOVEMENT_SEED_GHIDRA)
    offset_text = read_text(PLAYER_GAMENPC_MOVEMENT_SEED_OFFSET_GHIDRA)
    stock_restore_text = read_text(STOCK_TICK_RESTORE_GHIDRA)
    stock_ownership_xrefs_text = read_text(STOCK_TICK_OWNERSHIP_XREFS_GHIDRA)
    stock_input_offsets_text = read_text(STOCK_TICK_INPUT_OFFSET_ACCESS_GHIDRA)
    registered_publication_text = read_text(REGISTERED_GAMENPC_PUBLICATION_GHIDRA)
    registered_xrefs_text = read_text(REGISTERED_GAMENPC_PUBLICATION_XREFS_GHIDRA)
    registered_expanded_text = read_text(REGISTERED_GAMENPC_PUBLICATION_EXPANDED_GHIDRA)
    layout_text = read_text(BINARY_LAYOUT)
    constants_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/gameplay_constants.inl"
    )
    registered_live_probe_text = read_text(REGISTERED_GAMENPC_BLOCKER_LIVE_PROBE)
    stock_restore_live_probe_text = read_text(STOCK_TICK_RESTORE_LIVE_PROBE)
    rail_selection_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/execute_requests/entity_update_and_rail_selection.inl"
    )
    movement_step_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_movement_tick/wizard_bot_movement_step.inl"
    )
    player_tick_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/actor_tick/player_actor_tick_hook.inl"
    )
    monster_hook_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/monster_pathfinding_hook.inl"
    )
    targeting_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/targeting_and_facing.inl"
    )
    seam_text = read_text(ROOT / "SolomonDarkModLoader/src/gameplay_seams.h")
    plan_text = read_text(NATIVE_SEAM_PLAN)

    required_doc_tokens = (
        "runtime/ghidra_player_gamenpc_movement_seed_paths.txt",
        "0x0052A500",
        "0x0052C910",
        "0x00548B00",
        "0x00483480",
        "actor_current_target_actor",
        "actor_target_repath_cadence",
        "no native bot-side producer",
        "runtime/ghidra_registered_gamenpc_publication_blockers.txt",
        "runtime/ghidra_registered_gamenpc_publication_xrefs.txt",
        "runtime/ghidra_registered_gamenpc_publication_expanded.txt",
        "tests/re/run_live_registered_gamenpc_blocker_probe.py",
        "long-lived `0x1397`",
        "gamenpc_count=0",
        "zero native GameNpc movement trace hits",
        "runtime/ghidra_stock_tick_restore_paths.txt",
        "runtime/ghidra_stock_tick_ownership_xrefs.txt",
        "runtime/ghidra_stock_tick_input_offset_accesses.txt",
        "tests/re/run_live_stock_tick_restore_probe.py",
        "runtime/live_stock_tick_restore_probe.json",
        "low-impact live watches",
        "stationary post-stop",
        "vtable target",
    )
    missing_doc = [token for token in required_doc_tokens if token not in doc_text]
    if missing_doc:
        raise StaticReTestFailure(
            "player/GameNpc movement seed doc is missing token(s): " +
            ", ".join(missing_doc))

    required_ghidra_tokens = (
        "FUNCTION FUN_0052a500 @ 0052a500",
        "param_1[0x86] = 0x3f800000;",
        "FUNCTION FUN_0052c910 @ 0052c910",
        "*(float *)(*(int *)(param_1 + 0x21c) + 0x30)",
        "*(float *)(*(int *)(param_1 + 0x21c) + 0x34)",
        "FUNCTION FUN_00548b00 @ 00548b00",
        "param_1[0x56]",
        "param_1[0x57]",
        "FUNCTION FUN_00483480 @ 00483480",
        "*(int *)(param_1 + 0x168) = iVar2;",
        "*(int *)(param_1 + 0x1dc) = *(int *)(param_1 + 0xc) % *(int *)(param_1 + 0x1e0);",
        "FUNCTION FUN_006042c0 @ 006042c0",
    )
    missing_ghidra = [token for token in required_ghidra_tokens if token not in ghidra_text]
    if missing_ghidra:
        raise StaticReTestFailure(
            "player/GameNpc movement seed Ghidra artifact is missing token(s): " +
            ", ".join(missing_ghidra))

    required_offset_tokens = (
        "FUNCTION FUN_00548b00 @ 00548b00 score=32",
        "FUNCTION FUN_00483480 @ 00483480 score=8",
        "FUNCTION FUN_0052a500 @ 0052a500 score=3",
    )
    missing_offsets = [token for token in required_offset_tokens if token not in offset_text]
    if missing_offsets:
        raise StaticReTestFailure(
            "movement seed offset scan is missing token(s): " +
            ", ".join(missing_offsets))

    required_stock_restore_tokens = (
        "FUNCTION FUN_00548b00 @ 00548b00",
        "param_1[0x56]",
        "param_1[0x57]",
        "FUN_00525800",
        "FUNCTION FUN_00525800 @ 00525800",
        "FUNCTION FUN_0052c910 @ 0052c910",
        "*(float *)(*(int *)(param_1 + 0x21c) + 0x30)",
        "*(float *)(*(int *)(param_1 + 0x21c) + 0x34)",
        "FUNCTION FUN_0052a500 @ 0052a500",
        "param_1[0x86] = 0x3f800000;",
    )
    missing_stock_restore = [
        token for token in required_stock_restore_tokens if token not in stock_restore_text
    ]
    if missing_stock_restore:
        raise StaticReTestFailure(
            "stock-tick restore Ghidra artifact is missing token(s): " +
            ", ".join(missing_stock_restore))

    required_stock_ownership_tokens = (
        "=== ADDRESS: 00548b00 ===",
        "REF from 00793f7c in [no containing function]",
        "FUNCTION_COUNT 0",
        "=== ADDRESS: 0052c910 ===",
        "REF from 00549353 in FUN_00548b00",
        "FUNCTION_COUNT 1",
        "=== ADDRESS: 00525800 ===",
        "REF from 0054b050 in FUN_00548b00",
        "REF from 0054b58d in FUN_00548b00",
        "REF from 00604656 in FUN_006042c0",
        "=== ADDRESS: 0052a500 ===",
        "REF from 0052b4ec in FUN_0052b4c0",
        "REF from 0052c793 in FUN_0052c790",
        "=== ADDRESS: 00548a00 ===",
        "REF from 0054ab7a in FUN_00548b00",
    )
    missing_stock_ownership = [
        token for token in required_stock_ownership_tokens if token not in stock_ownership_xrefs_text
    ]
    if missing_stock_ownership:
        raise StaticReTestFailure(
            "stock-tick ownership xref artifact is missing token(s): " +
            ", ".join(missing_stock_ownership))

    required_stock_input_offset_tokens = (
        "FUNCTION FUN_00548b00 @ 00548b00 score=97",
        "0x158=17",
        "0x15c=13",
        "0x218=2",
        "0x21c=3",
        "FUNCTION FUN_0052c910 @ 0052c910 score=58",
        "0x21c=34",
        "0x30=13",
        "0x34=8",
        "FUNCTION FUN_0061aa00 @ 0061aa00 score=10",
        "FUNCTION FUN_00525800 @ 00525800 score=4",
        "FUNCTION FUN_0052a500 @ 0052a500 score=3",
        "FUNCTION FUN_00548a00 @ 00548a00 score=3",
    )
    missing_stock_input_offsets = [
        token for token in required_stock_input_offset_tokens if token not in stock_input_offsets_text
    ]
    if missing_stock_input_offsets:
        raise StaticReTestFailure(
            "stock-tick input offset artifact is missing token(s): " +
            ", ".join(missing_stock_input_offsets))

    required_registered_publication_tokens = (
        "FUNCTION FUN_00466fa0 @ 00466fa0",
        "0x1397",
        "FUNCTION FUN_0061aa00 @ 0061aa00",
        "Object_Allocate(0x398",
        "FUNCTION FUN_005e9a90 @ 005e9a90",
        "FUNCTION FUN_00622d90 @ 00622d90",
        "FUN_005217b0(param_1)",
        "FUNCTION FUN_0063f6d0 @ 0063f6d0",
        "FUNCTION FUN_005e9d50 @ 005e9d50",
        "FUNCTION FUN_006042c0 @ 006042c0",
        "FUNCTION FUN_005ea450 @ 005ea450",
    )
    missing_registered_publication = [
        token for token in required_registered_publication_tokens
        if token not in registered_publication_text
    ]
    if missing_registered_publication:
        raise StaticReTestFailure(
            "registered GameNpc publication blocker artifact is missing token(s): " +
            ", ".join(missing_registered_publication))
    required_registered_xrefs_tokens = (
        "=== ADDRESS: 00466fa0 ===",
        "REF from 0068a4d6 in FUN_00689750",
        "FUNCTION_COUNT 1",
        "case 0x40f:",
        "FUN_00466fa0();",
        "=== ADDRESS: 005b7080 ===",
        "REF from 00466fd8 in FUN_00466fa0",
    )
    missing_registered_xrefs = [
        token for token in required_registered_xrefs_tokens if token not in registered_xrefs_text
    ]
    if missing_registered_xrefs:
        raise StaticReTestFailure(
            "registered GameNpc publication xref artifact is missing token(s): " +
            ", ".join(missing_registered_xrefs))
    required_registered_expanded_tokens = (
        "FUNCTION FUN_00466fa0 @ 00466fa0",
        "case 0x1397:",
        "Object_Allocate(0x268",
        "FUNCTION FUN_0063f6d0 @ 0063f6d0",
        "FUNCTION FUN_00641090 @ 00641090",
        "FUNCTION FUN_00622d90 @ 00622d90",
        "FUNCTION FUN_005217b0 @ 005217b0",
        "FUNCTION FUN_005e9d50 @ 005e9d50",
        "FUNCTION FUN_006042c0 @ 006042c0",
        "FUNCTION FUN_005ea450 @ 005ea450",
    )
    missing_registered_expanded = [
        token for token in required_registered_expanded_tokens if token not in registered_expanded_text
    ]
    if missing_registered_expanded:
        raise StaticReTestFailure(
            "registered GameNpc publication expanded artifact is missing token(s): " +
            ", ".join(missing_registered_expanded))

    required_layout_tokens = (
        "actor_current_target_actor=0x168",
        "actor_target_repath_cadence=0x1E0",
        "actor_animation_config_block=0x158",
        "actor_animation_drive_parameter=0x15C",
        "actor_move_step_scale=0x218",
        "create_wizard_preview_source=0x00466FA0",
        "gamenpc_movement_tick=0x006042C0",
    )
    missing_layout = [token for token in required_layout_tokens if token not in layout_text]
    if missing_layout:
        raise StaticReTestFailure(
            "movement seed layout is missing token(s): " +
            ", ".join(missing_layout))

    if "kActorCurrentTargetActorOffset = 0x168" in constants_text:
        raise StaticReTestFailure("actor current-target offset is still a gameplay_constants hardcode")
    if "kHostileCurrentTargetActorOffset = 0x168" in constants_text:
        raise StaticReTestFailure("hostile current-target offset still duplicates actor current-target offset")

    required_code_tokens = (
        (seam_text, "seam", "kActorCurrentTargetActorOffset"),
        (seam_text, "seam", "kActorTargetRepathCadenceOffset"),
        (registered_live_probe_text, "registered GameNpc live probe", "rail=standalone_clone"),
        (registered_live_probe_text, "registered GameNpc live probe", "raw.object_type_id"),
        (registered_live_probe_text, "registered GameNpc live probe", "0x1397"),
        (registered_live_probe_text, "registered GameNpc live probe", "rail=registered_gamenpc"),
        (registered_live_probe_text, "registered GameNpc live probe", "world_actor_type_summary"),
        (registered_live_probe_text, "registered GameNpc live probe", "gamenpc_count"),
        (registered_live_probe_text, "registered GameNpc live probe", "create_wizard_preview_source"),
        (registered_live_probe_text, "registered GameNpc live probe", "gamenpc_movement_tick"),
        (registered_live_probe_text, "registered GameNpc live probe", "lua_bots_disable_tick"),
        (stock_restore_live_probe_text, "stock tick restore live probe", "sd.debug.watch("),
        (stock_restore_live_probe_text, "stock tick restore live probe", "observe_stationary_actor"),
        (stock_restore_live_probe_text, "stock tick restore live probe", "stock_drift_events"),
        (stock_restore_live_probe_text, "stock tick restore live probe", "lua_bots_disable_tick"),
        (stock_restore_live_probe_text, "stock tick restore live probe", "WATCH: {WATCH_X} changed"),
        (stock_restore_live_probe_text, "stock tick restore live probe", "page-guard"),
        (stock_restore_live_probe_text, "stock tick restore live probe", "live_stock_tick_restore_probe.json"),
        (monster_hook_text, "monster hook", "ClearHostileTargetsForDeadWizardActor"),
        (monster_hook_text, "monster hook", "cleared dead wizard target refs"),
        (monster_hook_text, "monster hook", "kHostileTargetBucketDeltaOffset"),
        (monster_hook_text, "monster hook", "kActorCurrentTargetActorOffset"),
        (player_tick_text, "player tick", "ClearHostileTargetsForDeadWizardActor(actor_address)"),
        (targeting_text, "targeting", "kActorCurrentTargetActorOffset"),
        (movement_step_text, "movement step", "CallPlayerActorMoveStepSafe"),
        (movement_step_text, "movement step", "kActorMoveStepScaleOffset"),
    )
    missing_code = [
        f"{label}:{token}" for text, label, token in required_code_tokens if token not in text
    ]
    if missing_code:
        raise StaticReTestFailure(
            "movement seed code is not layout-backed: " +
            ", ".join(missing_code))

    forbidden_patterns = (
        (monster_hook_text, "monster hook", r"kHostileCurrentTargetActorOffset"),
        (movement_step_text, "movement step", r"kRecoveryRotations"),
        (movement_step_text, "movement step", r"player_move_step_detour"),
        (player_tick_text, "player tick", r"stock tick rewrote actor position"),
        (player_tick_text, "player tick", r"position_after_stock"),
        (player_tick_text, "player tick", r"TryWriteField\(actor_address,\s*kActorPositionXOffset"),
    )
    present_forbidden = [
        label for text, label, pattern in forbidden_patterns if re.search(pattern, text)
    ]
    if present_forbidden:
        raise StaticReTestFailure(
            "raw/duplicated target movement offsets remain in: " +
            ", ".join(present_forbidden))

    removed_registered_paths = (
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_movement_tick/registered_gamenpc_movement.inl",
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/execute_requests/spawn_registered_gamenpc.inl",
    )
    remaining_registered_paths = [
        str(path.relative_to(ROOT)) for path in removed_registered_paths if path.exists()
    ]
    if remaining_registered_paths:
        raise StaticReTestFailure(
            "registered GameNpc rail files still exist after rail removal: " +
            ", ".join(remaining_registered_paths))

    active_registered_text = "\n".join(
        read_text(path) for path in (
            ROOT / "SolomonDarkModLoader/include/mod_loader.h",
            ROOT / "SolomonDarkModLoader/src/bot_runtime/public_api/update_api.inl",
            ROOT / "SolomonDarkModLoader/src/bot_runtime/public_api/tick_service_api.inl",
            ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/participant_entity_state.inl",
            ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/participant_kind_helpers.inl",
            ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/execute_requests/entity_update_and_rail_selection.inl",
            ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/execute_requests/participant_entity_sync.inl",
            ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/execute_requests/spawn_safe_wrappers.inl",
            MOD_LOADER_PROJECT,
            MOD_LOADER_PROJECT_FILTERS,
        )
    )
    forbidden_registered_tokens = (
        "RegisteredGameNpc",
        "registered_gamenpc",
        "TrySpawnRegisteredGameNpc",
        "IsRegisteredGameNpcKind",
        "StopRegisteredGameNpcMotion",
        "DestroyRegisteredGameNpcActor",
        "kSDModParticipantGameplayKindRegisteredGameNpc",
        "spawn_registered_gamenpc.inl",
        "registered_gamenpc_movement.inl",
    )
    remaining_registered_tokens = [
        token for token in forbidden_registered_tokens if token in active_registered_text
    ]
    if remaining_registered_tokens:
        raise StaticReTestFailure(
            "registered GameNpc rail tokens remain in active code: " +
            ", ".join(remaining_registered_tokens))

    if not re.search(
        r"\| PlayerActor movement seeds \|[^\n]+\|[^\n]*0x0052C910[^\n]*0x00548B00[^\n]*\|",
        plan_text,
    ):
        raise StaticReTestFailure(
            "native seam plan does not cite the recovered PlayerActor control-brain/tick evidence")
    if not re.search(
        r"\| Stock tick position restore \|[^\n]+\|[^\n]*runtime/ghidra_stock_tick_ownership_xrefs\.txt[^\n]*runtime/live_stock_tick_restore_probe\.json[^\n]*\|",
        plan_text,
    ):
        raise StaticReTestFailure(
            "native seam plan does not cite the stock-tick restore artifact and live probe")
    if not re.search(
        r"\| Registered GameNpc movement \|[^\n]+\|[^\n]*runtime/ghidra_registered_gamenpc_publication_xrefs.txt[^\n]*gamenpc_count=0[^\n]*\|",
        plan_text,
    ):
        raise StaticReTestFailure(
            "native seam plan does not cite the registered GameNpc xref and live world-scan evidence")
    return "Player movement seeds are layout-backed and the unsafe registered GameNpc rail is removed"


def test_bot_movement_speed_uses_native_live_envelope() -> str:
    doc_text = read_text(PATHFINDING_RE_DOC)
    plan_text = read_text(NATIVE_SEAM_PLAN)
    readme_text = read_text(ROOT / "tests/re/README.md")
    layout_text = read_text(BINARY_LAYOUT)
    seam_text = read_text(ROOT / "SolomonDarkModLoader/src/gameplay_seams.h")
    address_text = read_text(ROOT / "SolomonDarkModLoader/src/gameplay_seams/state_and_address_bindings.inl")
    storage_text = read_text(ROOT / "SolomonDarkModLoader/src/gameplay_seams/address_storage.inl")
    movement_step_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_movement_tick/wizard_bot_movement_step.inl"
    )
    participant_state_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/participant_entity_state.inl"
    )
    lifecycle_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_registry_and_movement_participant_lifecycle.inl"
    )
    locomotion_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_movement/locomotion_and_animation.inl"
    )
    live_probe_text = read_text(BOT_NATIVE_SPEED_LIVE_PROBE)

    required_layout_tokens = (
        "movement_input_acceleration_divisor=0x007DE810",
        "movement_speed_scalar=0x00784740",
        "movement_velocity_damping=0x00784E20",
        "actor_move_speed_scale=0x74",
        "actor_movement_speed_multiplier=0x120",
        "actor_move_step_scale=0x218",
        "progression_move_speed=0x90",
    )
    missing_layout = [token for token in required_layout_tokens if token not in layout_text]
    if missing_layout:
        raise StaticReTestFailure(
            "native movement speed layout is missing token(s): " +
            ", ".join(missing_layout))

    required_doc_tokens = (
        "native PlayerActorTick speed envelope",
        "0x007DE810",
        "0x00784740",
        "0x00784E20",
        "actor +0x120",
        "actor +0x74",
        "progression +0x90",
        "tests/re/run_live_bot_native_speed_probe.py",
    )
    doc_combined = doc_text + "\n" + readme_text + "\n" + plan_text
    missing_doc = [token for token in required_doc_tokens if token not in doc_combined]
    if missing_doc:
        raise StaticReTestFailure(
            "native movement speed docs are missing token(s): " +
            ", ".join(missing_doc))

    required_code_tokens = (
        (seam_text, "seams header", "kMovementInputAccelerationDivisorGlobal"),
        (seam_text, "seams header", "kMovementSpeedScalarGlobal"),
        (seam_text, "seams header", "kMovementVelocityDampingGlobal"),
        (storage_text, "seam storage", "kMovementInputAccelerationDivisorGlobal = 0"),
        (address_text, "address bindings", '"movement_input_acceleration_divisor"'),
        (address_text, "address bindings", '"movement_velocity_damping"'),
        (participant_state_text, "participant state", "native_movement_accumulator_x"),
        (lifecycle_text, "participant lifecycle", "native_movement_accumulator_x = 0.0f"),
        (locomotion_text, "locomotion stop", "native_movement_accumulator_x = 0.0f"),
        (movement_step_text, "movement step", "TryResolveWizardBotNativeMovementEnvelope"),
        (movement_step_text, "movement step", "kActorMovementSpeedMultiplierOffset"),
        (movement_step_text, "movement step", "kActorMoveSpeedScaleOffset"),
        (movement_step_text, "movement step", "kProgressionMoveSpeedOffset"),
        (movement_step_text, "movement step", "kMovementInputAccelerationDivisorGlobal"),
        (movement_step_text, "movement step", "kMovementVelocityDampingGlobal"),
        (movement_step_text, "movement step", "binding->native_movement_accumulator_x +"),
        (movement_step_text, "movement step", "velocity_x * native_velocity_damping"),
    )
    missing_code = [
        f"{label}:{token}" for text, label, token in required_code_tokens if token not in text
    ]
    if missing_code:
        raise StaticReTestFailure(
            "native movement speed code is missing token(s): " +
            ", ".join(missing_code))

    required_probe_tokens = (
        "MOVEMENT_INPUT_ACCELERATION_DIVISOR_GLOBAL",
        "MOVEMENT_SPEED_SCALAR_GLOBAL",
        "MOVEMENT_VELOCITY_DAMPING_GLOBAL",
        "PROGRESSION_MOVE_SPEED_OFFSET",
        "write_progression_move_speed",
        "observe_velocity_after_move",
        "choose_until_rush",
        "find_bot_for_element",
        "native_cap",
        "post_rush_observation",
    )
    missing_probe = [token for token in required_probe_tokens if token not in live_probe_text]
    if missing_probe:
        raise StaticReTestFailure(
            "live bot native speed probe is missing token(s): " +
            ", ".join(missing_probe))

    forbidden_patterns = (
        (layout_text, "layout", r"movement_direction_scale"),
        (seam_text, "seams header", r"kMovementDirectionScaleGlobal"),
        (address_text, "address bindings", r"movement_direction_scale"),
        (storage_text, "seam storage", r"kMovementDirectionScaleGlobal"),
        (movement_step_text, "movement step", r"direction_x\s*\*\s*move_step_scale"),
        (movement_step_text, "movement step", r"direction_y\s*\*\s*move_step_scale"),
        (movement_step_text, "movement step", r"\b1\.25f\b|\b10\.0f\b|\b0\.95f\b"),
    )
    present_forbidden = [
        f"{label}:{pattern}" for text, label, pattern in forbidden_patterns if re.search(pattern, text)
    ]
    if present_forbidden:
        raise StaticReTestFailure(
            "native movement speed path still contains stale scalar/direct-step token(s): " +
            ", ".join(present_forbidden))

    return "bot movement speed is driven by the native PlayerActorTick live envelope"


def test_participant_collision_resolver_is_documented_and_live_probed() -> str:
    doc_text = read_text(PATHFINDING_RE_DOC)
    plan_text = read_text(NATIVE_SEAM_PLAN)
    registration_text = read_text(STANDALONE_COLLISION_REGISTRATION_GHIDRA)
    overlap_text = read_text(STANDALONE_COLLISION_OVERLAP_GHIDRA)
    ownership_xrefs_text = read_text(STANDALONE_COLLISION_OWNERSHIP_XREFS_GHIDRA)
    field_writes_text = read_text(STANDALONE_COLLISION_FIELD_WRITES_GHIDRA)
    clone_instruction_text = read_text(STANDALONE_CLONE_INSTRUCTION_GHIDRA)
    probe_text = read_text(ROOT / "tests/re/run_live_standalone_collision_probe.py")

    required_doc_tokens = (
        "runtime/ghidra_standalone_collision_registration_paths.txt",
        "runtime/ghidra_standalone_collision_overlap_builder_paths.txt",
        "runtime/ghidra_standalone_collision_ownership_xrefs.txt",
        "runtime/ghidra_standalone_collision_field_writes.txt",
        "runtime/ghidra_wizard_clone_from_source_instructions.txt",
        "0x0061AA00",
        "0x0063F6D0",
        "0x005217B0",
        "0x00521B80",
        "0x00522500",
        "0x00522C00",
        "0x00522B20",
        "tests/re/run_live_standalone_collision_probe.py",
        "runtime/live_standalone_collision_probe.json",
        "native publication/ownership path",
        "ResolveWizardParticipantActorCollisions",
        "participant collision resolver",
        "local player as solid",
        "WorldCellGrid_RebindActor",
    )
    missing_doc = [token for token in required_doc_tokens if token not in doc_text]
    if missing_doc:
        raise StaticReTestFailure(
            "standalone collision RE doc is missing token(s): " +
            ", ".join(missing_doc))

    required_registration_tokens = (
        "FUNCTION FUN_0063f6d0 @ 0063f6d0",
        "FUNCTION FUN_00641090 @ 00641090",
        "FUNCTION FUN_005217b0 @ 005217b0",
        "FUNCTION FUN_00525800 @ 00525800",
        "*(int **)(param_1 + 0x500 + (param_2 * 0x800 + param_4) * 4) = param_3;",
        "param_3[0x16] = param_1;",
        "*(short *)((int)param_3 + 0x5e) = (short)param_4;",
        "*(undefined1 *)(param_3 + 0x1a) = 0;",
        "if (*(char *)(param_2 + 0x36) != '\\0')",
    )
    missing_registration = [token for token in required_registration_tokens if token not in registration_text]
    if missing_registration:
        raise StaticReTestFailure(
            "standalone collision registration Ghidra artifact is missing token(s): " +
            ", ".join(missing_registration))

    required_overlap_tokens = (
        "FUNCTION FUN_00521b80 @ 00521b80",
        "FUNCTION FUN_00522500 @ 00522500",
        "FUNCTION FUN_00522c00 @ 00522c00",
        "FUNCTION FUN_00522b20 @ 00522b20",
        "*(undefined4 *)(param_1 + 0x40) = 0;",
        "*(undefined4 *)(param_1 + 0x70) = 0;",
        "(*(uint *)(param_2 + 0x38) & *(uint *)(iVar5 + 0x14)) == 0",
        "(*(char *)(param_1 + 0x120) != '\\0') && (*(char *)(param_2 + 0x37) != '\\0')",
    )
    missing_overlap = [token for token in required_overlap_tokens if token not in overlap_text]
    if missing_overlap:
        raise StaticReTestFailure(
            "standalone collision overlap Ghidra artifact is missing token(s): " +
            ", ".join(missing_overlap))

    required_ownership_tokens = (
        "=== ADDRESS: 00622d90 ===",
        "FUNCTION_COUNT 8",
        "=== ADDRESS: 005217b0 ===",
        "REF from 00622db2 in FUN_00622d90",
        "REF from 0064111a in FUN_00641090",
        "=== ADDRESS: 00525800 ===",
        "REF from 00604656 in FUN_006042c0",
        "=== ADDRESS: 00522c00 ===",
        "REF from 00525936 in FUN_00525800",
        "=== ADDRESS: 00522b20 ===",
        "REF from 00525917 in FUN_00525800",
    )
    missing_ownership = [token for token in required_ownership_tokens if token not in ownership_xrefs_text]
    if missing_ownership:
        raise StaticReTestFailure(
            "standalone collision ownership xref artifact is missing token(s): " +
            ", ".join(missing_ownership))

    required_field_write_tokens = (
        "=== OFFSET 0x54",
        "FUN_005217b0",
        "FUN_00525800",
        "dword ptr [EBX + 0x54]",
        "dword ptr [EDI + 0x54]",
        "=== OFFSET 0x36",
        "=== OFFSET 0x37",
        "=== OFFSET 0x80",
        "=== OFFSET 0x120",
    )
    missing_field_writes = [token for token in required_field_write_tokens if token not in field_writes_text]
    if missing_field_writes:
        raise StaticReTestFailure(
            "standalone collision field-write artifact is missing token(s): " +
            ", ".join(missing_field_writes))

    required_clone_instruction_tokens = (
        "FUNCTION FUN_0061aa00 @ 0061aa00",
        "0061aa5c MOV ECX,dword ptr [ESI + 0x58]",
        "0061aa63 PUSH EDI",
        "0061aa64 PUSH EBP",
        "0061aa66 MOV dword ptr [ESP + 0x30],EDI",
        "0061aa6a CALL 0x0063f6d0",
        "0061aeac MOV EDX,dword ptr [ECX + 0x1388]",
    )
    missing_clone = [token for token in required_clone_instruction_tokens if token not in clone_instruction_text]
    if missing_clone:
        raise StaticReTestFailure(
            "clone-from-source instruction artifact is missing token(s): " +
            ", ".join(missing_clone))

    removed_bridge_path = (
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/actor_tick/standalone_puppet_collision.inl"
    )
    if removed_bridge_path.exists():
        raise StaticReTestFailure("standalone collision bridge file still exists in active code")

    active_collision_text = "\n".join(
        read_text(path) for path in (
            ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_movement/participant_collision_response.inl",
            ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_registry_and_movement_motion_helpers.inl",
            ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/actor_tick_hooks.inl",
            ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/actor_tick/player_actor_tick_hook.inl",
            MOD_LOADER_PROJECT,
            MOD_LOADER_PROJECT_FILTERS,
        )
    )
    forbidden_collision_tokens = (
        "standalone_puppet_collision.inl",
        "ApplyStandalonePuppetCollisionPushFromActor",
        "pushed standalone puppet",
    )
    remaining_collision_tokens = [
        token for token in forbidden_collision_tokens if token in active_collision_text
    ]
    if remaining_collision_tokens:
        raise StaticReTestFailure(
            "standalone collision push bridge tokens remain in active code: " +
            ", ".join(remaining_collision_tokens))

    required_active_collision_tokens = (
        "ResolveWizardParticipantActorCollisions",
        "IsWizardParticipantKind(binding.kind)",
        "TryResolvePlayerActorForSlot",
        "CallWorldCellGridRebindActorSafe",
        "PublishParticipantGameplaySnapshot(*subject.binding)",
        "kActorCollisionRadiusOffset",
        "IsActorRuntimeDead(binding.actor_address)",
        "subject.movable",
        "bot_movement/participant_collision_response.inl",
        "ResolveWizardParticipantActorCollisions();",
    )
    missing_active_collision = [
        token for token in required_active_collision_tokens if token not in active_collision_text
    ]
    if missing_active_collision:
        raise StaticReTestFailure(
            "participant collision resolver is missing active token(s): " +
            ", ".join(missing_active_collision))

    required_probe_tokens = (
        "ACTOR_OFFSET_GRID_CELL = csp.read_runtime_layout_offset(\"actor_grid_cell_ptr\")",
        "ACTOR_OFFSET_GRID_MEMBER_FLAG = csp.read_runtime_layout_offset(\"actor_grid_member_flag\")",
        "ACTOR_OFFSET_COLLISION_RESPONSE_FLAG = csp.read_runtime_layout_offset(\"actor_collision_response_flag\")",
        "ACTOR_OFFSET_PRIMARY_FLAG_MASK = csp.read_runtime_layout_offset(\"actor_primary_flag_mask\")",
        "force_bot_overlap",
        "wait_for_collision_push",
        "bot_bot_collision_response",
        "player_bot_collision_response",
        "player_solid_after_collision_response",
        "grid_member_flag_36",
        "collision_response_flag_37",
        "live_standalone_collision_probe.json",
    )
    missing_probe = [token for token in required_probe_tokens if token not in probe_text]
    if missing_probe:
        raise StaticReTestFailure(
            "standalone collision live probe is missing token(s): " +
            ", ".join(missing_probe))

    if not re.search(
        r"\| Standalone collision \|[^\n]+\|[^\n]*runtime/ghidra_standalone_collision_ownership_xrefs\.txt[^\n]*runtime/live_standalone_collision_probe\.json[^\n]*\|[^\n]*done:",
        plan_text,
    ):
        raise StaticReTestFailure(
            "native seam plan does not record the recovered standalone collision blocker evidence")

    return "participant collision resolver is active, documented, and guarded against the old bridge"


def test_cast_state_native_contracts_are_documented_and_layout_backed() -> str:
    doc_text = read_text(ROOT / "docs/spell-cast-cleanup-chain.md")
    plan_text = read_text(NATIVE_SEAM_PLAN)
    layout_text = read_text(BINARY_LAYOUT)
    cast_text = read_text(CAST_STATE_GHIDRA)
    offset_text = read_text(CAST_STATE_OFFSETS_GHIDRA)
    spell_object_text = read_text(CAST_SPELL_OBJECT_GHIDRA)
    slot0_dispatch_xrefs_text = read_text(CAST_SLOT0_DISPATCH_XREFS_GHIDRA)
    slot0_gate_offsets_text = read_text(CAST_SLOT0_GATE_OFFSET_ACCESS_GHIDRA)
    selection_lifecycle_xrefs_text = read_text(CAST_SELECTION_LIFECYCLE_XREFS_GHIDRA)
    selection_cleanup_targets_text = read_text(CAST_SELECTION_CLEANUP_TARGETS_GHIDRA)
    selection_brain_offsets_text = read_text(CAST_SELECTION_BRAIN_OFFSET_ACCESS_GHIDRA)
    active_spell_lifecycle_text = read_text(CAST_ACTIVE_SPELL_LIFECYCLE_XREFS_GHIDRA)
    latch_offsets_text = read_text(CAST_LATCH_OFFSET_ACCESS_GHIDRA)
    boulder_vtable_text = read_text(CAST_BOULDER_VTABLE_GHIDRA)
    pure_primary_equip_sink_text = read_text(PURE_PRIMARY_EQUIP_SINK_GHIDRA)
    native_active_object_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/native_active_spell_object_state.inl"
    )
    selection_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/skill_selection_rules.inl"
    )
    processing_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/pending_cast_processing.inl"
    )
    preparation_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/pending_cast_preparation.inl"
    )
    startup_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/new_request_startup.inl"
    )
    release_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/release_and_latch_helpers.inl"
    )
    tick_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/actor_tick/player_actor_tick_hook.inl"
    )
    cast_probe_state_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/cast_probe_state.inl"
    )
    player_cast_hook_text = read_player_cast_hooks_source()
    player_control_hook_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/player_control_hooks.inl"
    )
    resource_state_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/resource_state.inl"
    )
    combat_prelude_text = read_text(
        ROOT / "SolomonDarkModLoader/src/run_lifecycle/combat_prelude_and_sources.inl"
    )
    lua_debug_text = (
        read_text(ROOT / "SolomonDarkModLoader/src/lua_engine_bindings_debug.cpp") +
        read_text(ROOT / "SolomonDarkModLoader/src/lua_engine_bindings_debug/functions_memory_inspection.inl")
    )
    constants_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/gameplay_constants.inl"
    )
    cast_state_probe_text = read_text(ROOT / "tools/cast_state_probe.py")
    player_watch_text = read_text(ROOT / "tools/watch_player_cast_dispatch.py")
    slot_watch_text = read_text(ROOT / "tools/watch_gameplay_slot_cast_startup.py")
    close_range_probe_text = read_text(ROOT / "tools/probe_bot_close_range_combat.py")
    autonomous_probe_text = read_text(ROOT / "tools/probe_bot_autonomous_combat_validation.py")
    element_damage_probe_text = read_text(ROOT / "tools/probe_bot_element_damage.py")
    primary_wave_probe_text = read_text(ROOT / "tools/probe_bot_primary_wave_cast.py")
    pure_primary_probe_text = read_text(PURE_PRIMARY_STARTUP_LIVE_PROBE)
    lua_combat_text = read_text(ROOT / "mods/lua_bots/scripts/lib/lua_bots/combat.lua")
    lua_bots_binding_text = read_text(ROOT / "SolomonDarkModLoader/src/lua_engine_bindings_bots.cpp")
    live_probe_text = read_text(ROOT / "tests/re/run_live_cast_shim_snapshot_probe.py")

    required_doc_tokens = (
        "runtime/ghidra_stock_tick_slot_shim_cast_paths.txt",
        "runtime/ghidra_cast_state_offsets.txt",
        "runtime/ghidra_cast_spell_object_handlers.txt",
        "runtime/ghidra_cast_slot0_dispatch_xrefs.txt",
        "runtime/ghidra_cast_slot0_gate_offset_accesses.txt",
        "runtime/ghidra_selection_lifecycle_xrefs.txt",
        "runtime/ghidra_selection_and_cleanup_targets.txt",
        "runtime/ghidra_selection_brain_offset_accesses.txt",
        "runtime/ghidra_active_spell_lifecycle_xrefs.txt",
        "runtime/ghidra_cast_latch_offset_accesses.txt",
        "runtime/ghidra_boulder_spell_object_vtable_slots.txt",
        "runtime/ghidra_pure_primary_equip_sink_paths.txt",
        "tests/re/run_live_cast_shim_snapshot_probe.py",
        "runtime/live_cast_shim_snapshot_probe.json",
        "0x00548B00",
        "0x00548A00",
        "0x0052F3B0",
        "0x0052C910",
        "0x0052DA40",
        "0x0052DA80",
        "0x00570D80",
        "0x0045ADE0",
        "0x00545360",
        "actor+0x1FC",
        "native cast gate patches",
        "0x0053D1B3",
        "0x0053D9D2",
        "0x0053E4E8",
        "0x00544C92",
        "0x00545393",
        "0x00545C2C",
        "0x005F1F39",
    )
    missing_doc = [token for token in required_doc_tokens if token not in doc_text]
    if missing_doc:
        raise StaticReTestFailure(
            "cast-state RE doc is missing token(s): " +
            ", ".join(missing_doc))

    required_cast_tokens = (
        "FUNCTION FUN_00548b00 @ 00548b00",
        "FUNCTION FUN_00548a00 @ 00548a00",
        "FUNCTION FUN_0052f3b0 @ 0052f3b0",
        "FUNCTION FUN_0052c910 @ 0052c910",
        "FUNCTION FUN_0052da80 @ 0052da80",
        "piVar2 = *(int **)(DAT_0081c264 + 0x1654 + *(char *)(param_1 + 0x5c) * 4);",
        "iVar1 = *(int *)(param_1 + 0x270);",
        "if (*(char *)(param_1 + 0x5c) == '\\0')",
        "(**(code **)(*piVar2 + 0x70))();",
        "(**(code **)(*piVar2 + 0x6c))();",
        "*(undefined1 *)(param_1 + 0x27c) = 0xff;",
        "*(undefined2 *)(param_1 + 0x27e) = 0xffff;",
    )
    missing_cast = [token for token in required_cast_tokens if token not in cast_text]
    if missing_cast:
        raise StaticReTestFailure(
            "cast-state Ghidra artifact is missing token(s): " +
            ", ".join(missing_cast))

    required_offset_tokens = (
        "FUNCTION FUN_00548b00 @ 00548b00 score=91",
        "FUNCTION FUN_0052c910 @ 0052c910 score=40",
        "0x270=15",
        "0x27c=6",
        "0x2dc",
        "0xe4=7",
    )
    missing_offsets = [token for token in required_offset_tokens if token not in offset_text]
    if missing_offsets:
        raise StaticReTestFailure(
            "cast-state offset scan is missing token(s): " +
            ", ".join(missing_offsets))

    required_spell_object_tokens = (
        "FUNCTION FUN_0052da40 @ 0052da40",
        "FUNCTION FUN_0045ade0 @ 0045ade0",
        "FUNCTION FUN_00544c60 @ 00544c60",
        "FUNCTION FUN_00545360 @ 00545360",
        "return *(undefined4 *)(param_1 + 0x500 + (cVar1 * 0x800 + (int)*(short *)(param_2 + 2)) * 4);",
        "if ((*(char *)(param_1 + 0x5c) == '\\0') && (*(char *)(param_1 + 0x27c) == -1))",
        "*(undefined1 *)(param_1 + 0x27c) = *(undefined1 *)(iVar9 + 0x5c);",
        "*(undefined2 *)(param_1 + 0x27e) = *(undefined2 *)(iVar9 + 0x5e);",
        "*(undefined4 *)(local_50 + 0x230) = uVar12;",
        "if (1 < *(int *)(local_50 + 0x22c))",
    )
    missing_spell_object = [token for token in required_spell_object_tokens if token not in spell_object_text]
    if missing_spell_object:
        raise StaticReTestFailure(
            "cast spell-object Ghidra artifact is missing token(s): " +
            ", ".join(missing_spell_object))

    required_slot0_xref_tokens = (
        "=== ADDRESS: 00548a00 ===",
        "REF from 0054ab7a in FUN_00548b00",
        "REF_COUNT 1",
        "=== ADDRESS: 0052f3b0 ===",
        "REF from 00545bd9 in FUN_00545360",
        "REF from 0054978a in FUN_00548b00",
        "FUNCTION_COUNT 2",
        "=== ADDRESS: 0052da40 ===",
        "REF_COUNT 8",
        "piVar2 = *(int **)(DAT_0081c264 + 0x1654 + *(char *)(param_1 + 0x5c) * 4);",
        "=== ADDRESS: 00545360 ===",
        "REF from 00548ad0 in FUN_00548a00",
        "=== ADDRESS: 00541870 ===",
        "REF from 00548ac0 in FUN_00548a00",
        "=== ADDRESS: 00544c60 ===",
        "REF from 00548a8f in FUN_00548a00",
        "if (*(char *)(param_1 + 0x5c) == '\\0')",
        "*(undefined1 *)(param_1 + 0x27c) = 0xff;",
        "*(undefined2 *)(param_1 + 0x27e) = 0xffff;",
    )
    missing_slot0_xrefs = [
        token for token in required_slot0_xref_tokens
        if token not in slot0_dispatch_xrefs_text
    ]
    if missing_slot0_xrefs:
        raise StaticReTestFailure(
            "slot-0 cast-dispatch xref artifact is missing token(s): " +
            ", ".join(missing_slot0_xrefs))

    required_slot0_offset_tokens = (
        "FUNCTION FUN_00548b00 @ 00548b00 score=69",
        "0x5c=46",
        "0x270=15",
        "0x27c=6",
        "0x164=1",
        "0x166=1",
        "FUNCTION FUN_00544c60 @ 00544c60 score=21",
        "FUNCTION FUN_00541870 @ 00541870 score=18",
        "FUNCTION FUN_00545360 @ 00545360 score=14",
        "FUNCTION FUN_0052da80 @ 0052da80 score=10",
        "FUNCTION FUN_0052f3b0 @ 0052f3b0 score=3",
        "FUNCTION FUN_00548a00 @ 00548a00 score=3",
        "FUNCTION FUN_0052da40 @ 0052da40 score=1",
    )
    missing_slot0_offsets = [
        token for token in required_slot0_offset_tokens
        if token not in slot0_gate_offsets_text
    ]
    if missing_slot0_offsets:
        raise StaticReTestFailure(
            "slot-0 cast gate offset scan is missing token(s): " +
            ", ".join(missing_slot0_offsets))

    required_selection_lifecycle_tokens = (
        "=== ADDRESS: 00819ec4 ===",
        "REF from 005bc9e5 in FUN_005bc8e0",
        "REF_COUNT 6",
        "FUNCTION_COUNT 4",
        "=== ADDRESS: 00819ec8 ===",
        "=== ADDRESS: 0052c910 ===",
        "REF from 00549353 in FUN_00548b00",
        "REF_COUNT 1",
        "FUNCTION_COUNT 1",
    )
    missing_selection_lifecycle = [
        token for token in required_selection_lifecycle_tokens
        if token not in selection_lifecycle_xrefs_text
    ]
    if missing_selection_lifecycle:
        raise StaticReTestFailure(
            "selection lifecycle xref artifact is missing token(s): " +
            ", ".join(missing_selection_lifecycle))

    required_selection_cleanup_tokens = (
        "FUNCTION FUN_0052c910 @ 0052c910",
        "*(undefined1 *)(iVar9 + 4) = 0xff;",
        "*(undefined2 *)(iVar9 + 6) = 0xffff;",
        "*(undefined4 *)(*(int *)(param_1 + 0x21c) + 8) = 100;",
        "param_1[0x9c] = (undefined ****)0x0",
        "param_1[0x9d] = ppppuVar7;",
        "FUN_0052f3b0();",
        "FUNCTION FUN_0052f3b0 @ 0052f3b0",
        "if (*(char *)(param_1 + 0x5c) == '\\0')",
        "(**(code **)(*piVar2 + 0x70))();",
        "(**(code **)(*piVar2 + 0x6c))();",
        "FUNCTION FUN_0052da40 @ 0052da40",
        "return **(undefined4 **)(param_1 + 0x21c);",
    )
    missing_selection_cleanup = [
        token for token in required_selection_cleanup_tokens
        if token not in selection_cleanup_targets_text
    ]
    if missing_selection_cleanup:
        raise StaticReTestFailure(
            "selection/cleanup target artifact is missing token(s): " +
            ", ".join(missing_selection_cleanup))

    required_selection_offset_tokens = (
        "FUNCTION FUN_0052c910 @ 0052c910 score=34 0x21c=34",
        "FUNCTION FUN_00548b00 @ 00548b00 score=5 0x21c=3 0x164=1 0x166=1",
        "FUNCTION FUN_0053f9c0 @ 0053f9c0 score=8 0x164=5 0x166=3",
        "*(undefined1 *)(param_1 + 0x164) = 0xff;",
        "*(undefined2 *)(param_1 + 0x166) = 0xffff;",
        "*(int *)(*(int *)(param_1 + 0x21c) + 0x14) - 1",
    )
    missing_selection_offsets = [
        token for token in required_selection_offset_tokens
        if token not in selection_brain_offsets_text
    ]
    if missing_selection_offsets:
        raise StaticReTestFailure(
            "selection brain offset artifact is missing token(s): " +
            ", ".join(missing_selection_offsets))

    required_active_lifecycle_tokens = (
        "=== ADDRESS: 0052f3b0 ===",
        "REF from 00545bd9 in FUN_00545360",
        "REF from 0054978a in FUN_00548b00",
        "REF_COUNT 4",
        "=== ADDRESS: 0045ade0 ===",
        "REF from 0052caef in FUN_0052c910",
        "REF from 0052f3f7 in FUN_0052f3b0",
        "REF_COUNT 23",
        "=== ADDRESS: 00524d70 ===",
        "REF from 0052f444 in FUN_0052f3b0",
        "REF from 00541c16 in FUN_00541870",
        "REF_COUNT 41",
        "(**(code **)(*piVar2 + 0x70))();",
        "(**(code **)(*piVar2 + 0x6c))();",
    )
    missing_active_lifecycle = [
        token for token in required_active_lifecycle_tokens
        if token not in active_spell_lifecycle_text
    ]
    if missing_active_lifecycle:
        raise StaticReTestFailure(
            "active spell lifecycle artifact is missing token(s): " +
            ", ".join(missing_active_lifecycle))

    required_latch_offset_tokens = (
        "FUNCTION FUN_00548b00 @ 00548b00 score=28 0xe4=7 0x270=15 0x27c=6",
        "FUNCTION FUN_0052c910 @ 0052c910 score=2 0x27c=2",
        "FUNCTION FUN_0052f3b0 @ 0052f3b0 score=2 0x27c=2",
        "FUNCTION FUN_00548a00 @ 00548a00 score=1 0x270=1",
        "FUNCTION FUN_00545360 @ 00545360 score=5 0x27c=3 0x27e=2",
    )
    missing_latch_offsets = [
        token for token in required_latch_offset_tokens
        if token not in latch_offsets_text
    ]
    if missing_latch_offsets:
        raise StaticReTestFailure(
            "cast latch offset artifact is missing token(s): " +
            ", ".join(missing_latch_offsets))

    required_boulder_vtable_tokens = (
        "===== Around 0xa6e014 =====",
        "00a6e014 [                              ] = 0x00000000",
        "References TO 0xa6e014:",
        "unique src funcs: 0",
        "FUNCTION FUN_004da650 @ 004da650",
        "FUNCTION FUN_004b53f0 @ 004b53f0",
    )
    missing_boulder_vtable = [
        token for token in required_boulder_vtable_tokens
        if token not in boulder_vtable_text
    ]
    if missing_boulder_vtable:
        raise StaticReTestFailure(
            "boulder dynamic vtable artifact is missing token(s): " +
            ", ".join(missing_boulder_vtable))

    required_pure_primary_equip_sink_tokens = (
        "FUNCTION FUN_0052da80 @ 0052da80",
        "FUNCTION FUN_00570d80 @ 00570d80",
        "0052dac3 MOV EAX,dword ptr [EDI + 0x1fc]",
        "0052dae0 MOV ECX,dword ptr [EAX + 0x30]",
        "0052dae3 MOV ECX,dword ptr [ECX]",
        "0052dae5 CALL 0x00570d80",
        "00570d80 MOV EAX,dword ptr [ECX + 0x4]",
        "if (*(int **)(param_1 + 0x21c) == (int *)0x0)",
        "iVar1 = FUN_00570d80();",
        "FUN_0044f5f0(param_1,uVar5,0);",
    )
    missing_pure_primary_equip_sink = [
        token for token in required_pure_primary_equip_sink_tokens
        if token not in pure_primary_equip_sink_text
    ]
    if missing_pure_primary_equip_sink:
        raise StaticReTestFailure(
            "pure-primary equip-sink Ghidra artifact is missing token(s): " +
            ", ".join(missing_pure_primary_equip_sink))

    required_layout_tokens = (
        "gameplay_primary_gate_block_flag=0x1ABE",
        "gameplay_cast_ui_block_flag=0x1ABD",
        "gameplay_input_gate_flag=0x85",
        "gameplay_visual_sink_slot_base=0x1410",
        "gameplay_visual_sink_slot_stride=0x64",
        "gameplay_visual_sink_slot_attachment=0x30",
        "actor_spell_target_group_byte=0x164",
        "actor_spell_target_slot_short=0x166",
        "actor_continuous_primary_mode=0x258",
        "actor_continuous_primary_active=0x264",
        "actor_post_gate_active_byte=0x26C",
        "actor_previous_skill_id=0x274",
        "actor_startup_counter=0x278",
        "actor_pure_primary_timing_b=0x1B8",
        "actor_spell_config_298=0x298",
        "actor_spell_config_2d8=0x2D8",
        "actor_primary_action_latch_e4=0xE4",
        "actor_primary_action_latch_e8=0xE8",
        "actor_world_bucket_table=0x500",
        "actor_world_bucket_stride=0x800",
        "actor_control_brain_state_id=0x00",
        "actor_control_brain_target_cooldown_ticks=0x0C",
        "progression_current_spell_id=0x750",
        "progression_cast_charge_a=0x8A8",
        "progression_earth_charge_cap=0x8AC",
        "progression_cast_charge_b=0x8B0",
        "progression_cast_charge_c=0x8B4",
        "object_vtable=0x00",
        "spell_object_stat_source=0x58",
        "spell_object_vfunc_update=0x1C",
        "spell_object_vfunc_release_secondary=0x6C",
        "spell_object_vfunc_release_finalize=0x70",
        "spell_object_damage_scale_vfunc=0x100",
        "spell_object_charge=0x74",
        "spell_object_release_charge=0x1F0",
        "spell_object_max_charge=0x1FC",
        "spell_object_phase=0x22C",
        "spell_object_release_timer=0x230",
        "spell_builder_result_param_a=0x34",
        "spell_builder_result_param_b=0x38",
        "enemy_max_hp=0x170",
        "enemy_current_hp=0x174",
    )
    missing_layout = [token for token in required_layout_tokens if token not in layout_text]
    if missing_layout:
        raise StaticReTestFailure(
            "cast-state layout is missing token(s): " +
            ", ".join(missing_layout))

    required_code_tokens = (
        (native_active_object_text, "native active object", "kActorWorldLookupObjectByHandle"),
        (native_active_object_text, "native active object", "CallActorWorldLookupObjectByHandleSafe"),
        (native_active_object_text, "native active object", "kSpellObjectReleaseTimerOffset"),
        (selection_text, "selection", "kActorControlBrainStateIdOffset"),
        (selection_text, "selection", "kActorPreviousSkillIdOffset"),
        (selection_text, "selection", "kActorPostGateActiveByteOffset"),
        (selection_text, "selection", "kActorControlBrainTargetSlotOffset"),
        (selection_text, "selection", "kActorControlBrainRetargetTicksOffset"),
        (selection_text, "selection", "kActorControlBrainFollowLeaderOffset"),
        (selection_text, "selection", "kActorSpellConfig298Offset"),
        (selection_text, "selection", "kProgressionCastChargeAOffset"),
        (processing_text, "processing", "kActorPrimaryActionLatchE4Offset"),
        (processing_text, "processing", "ReadBotNativeActiveSpellObjectState"),
        (release_text, "release", "kActorPrimaryActionLatchE8Offset"),
        (tick_text, "tick", "kGameplayPrimaryGateBlockFlagOffset"),
        (cast_probe_state_text, "cast_probe_state", "kSpellBuilderResultParamAOffset"),
        (cast_probe_state_text, "cast_probe_state", "kActorProgressionRuntimeStateOffset"),
        (player_cast_hook_text, "player_cast_hook", "kGameplayPlayerProgressionHandleOffset"),
        (player_control_hook_text, "player_control_hook", "kActorEquipRuntimeStateOffset"),
        (player_control_hook_text, "player_control_hook", "kActorEquipRuntimeVisualLinkAttachmentOffset"),
        (resource_state_text, "resource_state", "kEnemyCurrentHpOffset"),
        (resource_state_text, "resource_state", "kEnemyMaxHpOffset"),
        (combat_prelude_text, "combat_prelude", "kActorStartupCounterOffset"),
        (combat_prelude_text, "combat_prelude", "kActorSpellConfig29cOffset"),
        (lua_debug_text, "lua_debug", "LuaDebugLayoutOffset"),
        (lua_debug_text, "lua_debug", "layout_offset"),
        (lua_bots_binding_text, "lua_bots", "get_primary_attack_window"),
        (lua_bots_binding_text, "lua_bots", "kActorAnimationSelectionStateOffset"),
        (lua_bots_binding_text, "lua_bots", "kActorControlBrainPursuitRangeOffset"),
        (lua_bots_binding_text, "lua_bots", "kWaterPrimaryControlBrainRangeGlobal"),
        (cast_state_probe_text, "cast_state_probe", "read_runtime_layout_offset(\"actor_spell_config_298\")"),
        (player_watch_text, "player_watch", "ACTOR_ACTIVE_CAST_GROUP_OFFSET"),
        (slot_watch_text, "slot_watch", "ACTOR_ANIMATION_SELECTION_STATE_OFFSET"),
        (close_range_probe_text, "close_range_probe", "read_runtime_layout_offset(\"enemy_current_hp\")"),
        (close_range_probe_text, "close_range_probe", "read_runtime_layout_offset(\"actor_progression_runtime_state\")"),
        (autonomous_probe_text, "autonomous_probe", "read_runtime_layout_offset(\"trace_spell_cast_dispatcher_body\")"),
        (element_damage_probe_text, "element_damage_probe", "read_runtime_layout_offset(\"actor_move_step_scale\")"),
        (primary_wave_probe_text, "primary_wave_probe", "read_runtime_layout_offset(\"actor_progression_runtime_state\")"),
    )
    missing_code = [
        f"{label}:{token}" for text, label, token in required_code_tokens if token not in text
    ]
    if missing_code:
        raise StaticReTestFailure(
            "cast-state code is not layout-backed: " +
            ", ".join(missing_code))

    forbidden_patterns = (
        (constants_text, "gameplay constants", r"kActorSpellTargetGroupByteOffset\s*=\s*0x164"),
        (constants_text, "gameplay constants", r"kActorContinuousPrimaryModeOffset\s*=\s*0x258"),
        (constants_text, "gameplay constants", r"kActorWorldBucketTableOffset\s*=\s*0x500"),
        (selection_text, "selection", r"TryWriteField<[^>]+>\([^;]*,\s*0x0?[468C]"),
        (selection_text, "selection", r"ReadValueOr<[^>]+>\(selection_pointer \+ 0x0?[468C]"),
        (processing_text, "processing", r"actor_address,\s*0xE[48]"),
        (processing_text, "processing", r"active_spell_snapshot\.object,\s*0x1F[0C]"),
        (startup_text, "startup", r"spell_obj_ptr,\s*0x(?:08|74|1FC|22C|230)"),
        (release_text, "release", r"actor_address,\s*0xE[48]"),
        (tick_text, "tick", r"ResolveGameAddressOrZero\(0x0081C264 \+ 0x1ABE\)"),
        (cast_probe_state_text, "cast_probe_state", r"actor_address,\s*0x(?:200|21C)"),
        (cast_probe_state_text, "cast_probe_state", r"builder_result \+ 0x3[48]"),
        (player_cast_hook_text, "player_cast_hook", r"ResolveGameAddressOrZero\(0x0081C264\)"),
        (player_cast_hook_text, "player_cast_hook", r"\+ 0x1654"),
        (player_control_hook_text, "player_control_hook", r"ResolveGameAddressOrZero\(0x0081c264\)"),
        (player_control_hook_text, "player_control_hook", r"\+ 0x1410"),
        (player_control_hook_text, "player_control_hook", r"\* 0x64"),
        (resource_state_text, "resource_state", r"kArenaEnemy(?:Max|Current)HpOffset\s*=\s*0x17[04]"),
        (resource_state_text, "resource_state", r"actor_address,\s*0x17[04]"),
        (combat_prelude_text, "combat_prelude", r"kActorPrimarySkillIdOffset \+ sizeof"),
        (combat_prelude_text, "combat_prelude", r"actor_address,\s*0x(?:278|29C|2A0|2D0|2D4|2D8)"),
        (lua_combat_text, "lua_combat", r"0x290|actor\[0x290\]"),
        (cast_state_probe_text, "cast_state_probe", r"\(\"(?:u32|float|ptr|u8|u16)\",\s*0x(?:1B8|298|29C|2A0|2A4|2C8|2CC|2D0|2D4|2D8)\)"),
        (player_watch_text, "player_watch", r"actor \+ 0x(?:160|1EC|270|27C|27E)"),
        (slot_watch_text, "slot_watch", r"actor \+ 0x(?:160|1EC|200|21C|270|27C)"),
        (close_range_probe_text, "close_range_probe", r"(?:actor|bot_actor) \+ 0x(?:08|18|1C|6C|170|174|200|300)"),
        (autonomous_probe_text, "autonomous_probe", r"(?:actor|bot|hostile) \+ 0x(?:08|170|174|200|300)|0x00548A03|0x0052BB87"),
        (element_damage_probe_text, "element_damage_probe", r"(?:actor|bot|hostile|origin) \+ 0x(?:08|18|1C|6C|74|120|158|15C|170|174|200|218|300)"),
        (primary_wave_probe_text, "primary_wave_probe", r"actor \+ 0x(?:08|170|174|200|300)"),
    )
    present_forbidden = [
        label for text, label, pattern in forbidden_patterns if re.search(pattern, text, re.I | re.S)
    ]
    if present_forbidden:
        raise StaticReTestFailure(
            "raw cast-state offsets remain in: " +
            ", ".join(present_forbidden))

    required_live_probe_tokens = (
        "live_cast_shim_snapshot_probe.json",
        "CAST_SNAPSHOT_SKILL_ID = 0x3F6",
        "default=180.0",
        "capture_cast_fields",
        "assert_restore_fields",
        "assert_native_active_spell_object",
        "assert_post_cast_lifecycle",
        "native_active_spell_object",
        "gameplay_player_progression_handle",
        "bot_actor_slot",
        "selection_retarget_ticks",
        "MAX_POST_CAST_IDLE_ACTION_LATCH_E8",
    )
    missing_probe = [token for token in required_live_probe_tokens if token not in live_probe_text]
    if missing_probe:
        raise StaticReTestFailure(
            "cast shim/snapshot live probe is missing token(s): " +
            ", ".join(missing_probe))

    required_pure_primary_probe_tokens = (
        "assert_direct_actor_equip_startup",
        "actor1fc_plus4_type=0x1B5C",
        "forbidden_shim_tokens",
        "local_sel_shim=1",
        "local_window_shim=1",
        "slot_item_shim=1",
    )
    missing_pure_primary_probe = [
        token for token in required_pure_primary_probe_tokens
        if token not in pure_primary_probe_text
    ]
    if missing_pure_primary_probe:
        raise StaticReTestFailure(
            "pure-primary startup live probe is missing direct equip-sink assertion token(s): " +
            ", ".join(missing_pure_primary_probe))

    if not re.search(
        r"\| Slot-0 cast shim \|[^\n]+\|[^\n]*0x0052F3B9[^\n]*0x0053D1B3[^\n]*0x0053D9D2[^\n]*0x0053E4E8[^\n]*0x00544C92[^\n]*0x00545393[^\n]*0x00545C2C[^\n]*0x005F1F39[^\n]*\|[^\n]*done:",
        plan_text,
    ):
        raise StaticReTestFailure(
            "native seam plan does not record the native cast gate patch resolution")
    if not re.search(
        r"\| Active spell object lookup \|[^\n]+\|[^\n]*0x0045ADE0[^\n]*0x00545360[^\n]*\|[^\n]*done:",
        plan_text,
    ):
        raise StaticReTestFailure(
            "native seam plan does not record the native active spell object lookup")
    if not re.search(
        r"\| Skill selection state \|[^\n]+\|[^\n]*runtime/ghidra_selection_lifecycle_xrefs\.txt[^\n]*runtime/ghidra_selection_and_cleanup_targets\.txt[^\n]*done:",
        plan_text,
    ):
        raise StaticReTestFailure(
            "native seam plan does not record the selection lifecycle resolution")
    if not re.search(
        r"\| Cast latch cleanup \|[^\n]+\|[^\n]*runtime/ghidra_cast_latch_offset_accesses\.txt[^\n]*done:",
        plan_text,
    ):
        raise StaticReTestFailure(
            "native seam plan does not record the native cleanup resolution")

    return "cast-state native gate patches, lookups, and cleanup are backed by Ghidra artifacts, layout keys, docs, and live probe coverage"


def test_lua_bot_constants_are_semantic_or_documented() -> str:
    config_text = read_text(LUA_BOT_CONFIG)
    combat_text = read_text(LUA_BOT_COMBAT)
    constants_text = read_text(GAMEPLAY_CONSTANTS)
    doc_text = read_text(LUA_BOT_CONSTANTS_RE_DOC)
    plan_text = read_text(NATIVE_SEAM_PLAN)
    public_state_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_state_getters.inl"
    )
    live_probe_text = read_text(LUA_BOT_ENEMY_SEMANTIC_LIVE_PROBE)
    element_damage_probe_text = read_text(ROOT / "tools/probe_bot_element_damage.py")

    required_doc_tokens = (
        "Lua no longer owns a wave enemy object type constant",
        "actor.tracked_enemy",
        "IsArenaCombatActorType",
        "sd.bots.resolve_primary_entry",
        "sd.bots.get_primary_attack_window",
        "runtime/ghidra_primary_attack_window_dispatcher.txt",
        "FUN_0052C910",
        "FUN_00548B00",
        "FUN_00641B10",
        "kActorControlBrainPursuitRangeOffset",
        "actor_control_brain_pursuit_range",
        "water_primary_control_brain_range=0x00786CE8",
        "native_selection_pursuit_range",
        "native_water_control_brain_range",
        "Private-area travel no longer owns fixed entrance descriptors",
    )
    missing_doc = [token for token in required_doc_tokens if token not in doc_text]
    if missing_doc:
        raise StaticReTestFailure(
            "Lua bot constants RE doc is missing token(s): " +
            ", ".join(missing_doc))

    required_public_tokens = (
        "IsArenaCombatActorType",
        "state.tracked_enemy = true",
        "state.enemy_type = state.object_type_id",
        "IsArenaCombatActiveForUntrackedSceneActor",
        "tracked_enemy && !IsArenaCombatActorType(state.object_type_id)",
        "state.max_hp <= 0.0f",
        "return false",
    )
    missing_public = [token for token in required_public_tokens if token not in public_state_text]
    if missing_public:
        raise StaticReTestFailure(
            "Lua enemy semantic producer is missing token(s): " +
            ", ".join(missing_public))
    required_constants_tokens = (
        "FUN_005B7080 owns the stock GameNPC factory",
        "kFirstArenaCombatActorType = 1001",
        "kLastArenaCombatActorType = 1013",
        "object_type_id >= kFirstArenaCombatActorType",
        "object_type_id <= kLastArenaCombatActorType",
    )
    missing_constants = [token for token in required_constants_tokens if token not in constants_text]
    if missing_constants:
        raise StaticReTestFailure(
            "native arena combat actor semantic owner is missing token(s): " +
            ", ".join(missing_constants))
    forbidden_public_tokens = (
        "state.hp = 1.0f",
        "state.max_hp = 1.0f",
    )
    present_public = [token for token in forbidden_public_tokens if token in public_state_text]
    if present_public:
        raise StaticReTestFailure(
            "Lua enemy semantic producer still fabricates tracked-enemy HP: " +
            ", ".join(present_public))

    required_combat_tokens = (
        "actor.tracked_enemy ~= true",
        "sd.bots.get_primary_attack_window",
        "attack_window_unavailable",
    )
    missing_combat = [token for token in required_combat_tokens if token not in combat_text]
    if missing_combat:
        raise StaticReTestFailure(
            "Lua combat code is missing semantic/native-derived token(s): " +
            ", ".join(missing_combat))

    forbidden_combat_patterns = (
        r"WAVE_ENEMY_OBJECT_TYPE_ID",
        r"object_type_id\) or 0\)\s*~=.*1001",
        r"object_type_id\) or 0\)\s*~=.*config\.",
    )
    forbidden_config_patterns = (
        r"WAVE_ENEMY_OBJECT_TYPE_ID",
        r"\b1001\b",
    )
    present_forbidden = [
        f"combat:{pattern}" for pattern in forbidden_combat_patterns
        if re.search(pattern, combat_text)
    ]
    present_forbidden.extend(
        f"config:{pattern}" for pattern in forbidden_config_patterns
        if re.search(pattern, config_text)
    )
    if present_forbidden:
        raise StaticReTestFailure(
            "Lua still owns native enemy type constants: " +
            ", ".join(present_forbidden))

    required_live_probe_tokens = (
        "live_lua_bot_enemy_semantic_probe.json",
        "live_lua_bot_enemy_semantic_probe.source.raw.json",
        "probe_bot_element_damage.py",
        "semantic-snapshot-only",
        "tracked_enemy_semantic_snapshot",
        "tracked_enemy",
        "enemy_type",
        "type_mismatch_count",
        "collect_actor_entries",
        "extract_tracked_enemy_semantic_snapshot",
        "validate_source_summary",
        "validate_enemy_semantic_surface",
        "reuse-existing-source",
    )
    missing_live_probe = [token for token in required_live_probe_tokens if token not in live_probe_text]
    if missing_live_probe:
        raise StaticReTestFailure(
            "Lua enemy semantic live probe is missing token(s): " +
            ", ".join(missing_live_probe))

    required_source_probe_tokens = (
        "query_tracked_enemy_semantic_snapshot",
        "tracked_enemy_semantic_snapshot",
        "sd.world.list_actors",
        "actor.tracked_enemy == true",
    )
    missing_source_probe = [
        token for token in required_source_probe_tokens
        if token not in element_damage_probe_text
    ]
    if missing_source_probe:
        raise StaticReTestFailure(
            "Lua enemy semantic source probe is missing token(s): " +
            ", ".join(missing_source_probe))

    semantic_probe_paths = (
        ROOT / "tools/cast_state_probe.py",
        ROOT / "tools/probe_bot_close_range_combat.py",
        ROOT / "tools/probe_bot_element_damage.py",
        ROOT / "tools/probe_bot_primary_wave_cast.py",
        ROOT / "tools/probe_bot_autonomous_combat_validation.py",
    )
    forbidden_probe_patterns = (
        r"ARENA_ENEMY_OBJECT_TYPE_ID\s*=\s*1001",
        r"\bobj\s*==\s*1001\b",
        r"\bobject_type_id\s*==\s*1001\b",
        r"\btype_id\s*==\s*1001\b",
        r"tracked\s+or\s+obj\s*==",
    )
    probe_regressions: list[str] = []
    for path in semantic_probe_paths:
        text = read_text(path)
        missing_tokens = [
            token for token in ("sd.world.list_actors", "tracked_enemy == true")
            if token not in text
        ]
        if missing_tokens:
            probe_regressions.append(
                f"{path.relative_to(ROOT)}: missing token(s) {', '.join(missing_tokens)}")
        for pattern in forbidden_probe_patterns:
            if re.search(pattern, text):
                probe_regressions.append(
                    f"{path.relative_to(ROOT)}: forbidden probe enemy-type pattern {pattern}")
    helper_required_paths = semantic_probe_paths[1:]
    for path in helper_required_paths:
        text = read_text(path)
        if "is_tracked_enemy_actor" not in text:
            probe_regressions.append(
                f"{path.relative_to(ROOT)}: missing semantic actor-address classifier helper")
    close_range_probe_text = read_text(ROOT / "tools/probe_bot_close_range_combat.py")
    if "sd.world.spawn_enemy" in close_range_probe_text:
        probe_regressions.append(
            "tools/probe_bot_close_range_combat.py: close-range validation must use stock tracked hostiles")
    autonomous_probe_text = read_text(ROOT / "tools/probe_bot_autonomous_combat_validation.py")
    if "semantic-setup-only" not in autonomous_probe_text:
        probe_regressions.append(
            "tools/probe_bot_autonomous_combat_validation.py: missing semantic setup-only regression mode")
    if probe_regressions:
        raise StaticReTestFailure(
            "active Lua bot probes still own native enemy type knowledge: " +
            "; ".join(probe_regressions))

    if not re.search(
        r"\| Lua bot constants \|[^\n]*config\.lua[^\n]*combat\.lua[^\n]*\|[^\n]*tracked_enemy[^\n]*\|[^\n]*policy",
        plan_text,
    ):
        raise StaticReTestFailure(
            "native seam plan does not classify Lua bot constants as semantic/policy split")

    return "Lua bot combat consumes semantic enemy state and documents remaining policy/native-derived constants"


def test_remaining_active_hardcode_sources_are_removed() -> str:
    active_sources = {
        "Lua bot config": read_text(LUA_BOT_CONFIG),
        "Lua bot combat": read_text(LUA_BOT_COMBAT),
        "Lua bot follow": read_text(LUA_BOT_FOLLOW),
        "Lua bot state": read_text(LUA_BOT_STATE),
        "Lua bot travel": read_text(LUA_BOT_TRAVEL),
        "bot element damage probe": read_text(BOT_ELEMENT_DAMAGE_PROBE),
        "Lua follow proof tool": read_text(PROVE_LUA_FOLLOW),
        "cast skill selection rules": read_text(SKILL_SELECTION_RULES),
        "pending cast processing": read_text(PENDING_CAST_PROCESSING),
        "wizard clone source": read_text(STANDALONE_CLONE_SOURCE),
    }
    forbidden_tokens = {
        "Lua bot config": (
            "default_primary_entry_index_for_element",
            "WATER_NATIVE_CONE_BASE_RANGE",
            "WATER_RANGE_PER_SHAPE_UNIT",
            "ATTACK_RANGE_BY_ELEMENT_ID",
            "MIN_ATTACK_RANGE_BY_ELEMENT_ID",
            "PRIVATE_AREA_TRAVEL_DESCRIPTORS",
            "ENTRANCE_TRIGGER_DISTANCE",
            "ENTRANCE_ARRIVAL_DISTANCE",
            "HUB_ENTRANCE_ARM_DELAY_MS",
            "HUB_ENTRANCE_DWELL_MS",
            "PLAYER_MOVEMENT_ARM_DISTANCE",
        ),
        "Lua bot combat": (
            "config.WATER_NATIVE_CONE_BASE_RANGE",
            "config.WATER_RANGE_PER_SHAPE_UNIT",
            "config.ATTACK_RANGE_BY_ELEMENT_ID",
            "config.MIN_ATTACK_RANGE_BY_ELEMENT_ID",
        ),
        "Lua bot follow": (
            "hub_candidate_name",
            "hub_candidate_since_ms",
        ),
        "Lua bot state": (
            "last_player_sample",
            "hub_candidate_name",
            "hub_candidate_since_ms",
            "entrance_armed",
            "scene_entered_ms",
        ),
        "Lua bot travel": (
            "player_moved_recently",
            "last_player_sample",
            "hub_candidate_name",
            "hub_candidate_since_ms",
            "entrance_armed",
            "scene_entered_ms",
            "PLAYER_MOVEMENT_ARM_DISTANCE",
        ),
        "bot element damage probe": (
            '"fire": 0x10',
            '"water": 0x20',
            '"earth": 0x28',
            '"air": 0x18',
            '"ether": 0x08',
        ),
        "Lua follow proof tool": (
            "hub_candidate_name",
            "hub_candidate_since_ms",
            "scene_entered_ms",
        ),
        "cast skill selection rules": (
            "ResolveBotCastGestureTicks",
            "ResolveBotCastSafetyCapTicks",
        ),
        "pending cast processing": (
            "ResolveBotCastGestureTicks",
            "ResolveBotCastSafetyCapTicks",
        ),
        "wizard clone source": (
            "kLumaR",
            "kLumaG",
            "kLumaB",
            "kNativeSourceMix",
            "kNativeLumaMix",
            "descriptor_accent",
        ),
    }
    regressions = [
        f"{source_name}: active code still contains {token}"
        for source_name, tokens in forbidden_tokens.items()
        for token in tokens
        if token in active_sources[source_name]
    ]
    if regressions:
        raise StaticReTestFailure("; ".join(regressions))
    return "remaining active hardcode smell sources are removed from production and probe code"


def test_smell_source_inventory_is_current() -> str:
    active_roots = (
        ROOT / "SolomonDarkModLoader/src",
        ROOT / "SolomonDarkModLoader/include",
        ROOT / "mods/lua_bots/scripts",
    )
    active_text = "\n".join(
        read_text(path)
        for root in active_roots
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".cpp", ".h", ".hpp", ".inl", ".lua"}
    )
    regressions: list[str] = []
    for name, (removed_paths, forbidden_tokens) in CORRECTED_SMELL_GUARDS.items():
        for path in removed_paths:
            if path.exists():
                regressions.append(f"{name}: removed source still exists at {path.relative_to(ROOT)}")
        for token in forbidden_tokens:
            if token in active_text:
                regressions.append(f"{name}: active code still contains {token}")
    if regressions:
        raise StaticReTestFailure("; ".join(regressions))
    return "0 smell source entries still point at active code"


def test_active_sources_reject_read_or_and_stale_path_language() -> str:
    active_roots = (
        ROOT / "SolomonDarkModLoader/src",
        ROOT / "SolomonDarkModLoader/include",
        ROOT / "mods/lua_bots/scripts",
    )
    active_paths = [
        path
        for root in active_roots
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".cpp", ".h", ".hpp", ".inl", ".lua"}
    ]
    active_paths.extend((
        ROOT / "config/binary-layout.ini",
        ROOT / "tools/test_lua_bots_targeting.lua",
        ROOT / "tools/probe_bot_element_damage.py",
    ))

    forbidden_tokens = (
        "ReadValueOr",
        "ReadFieldOr",
        "sync_legacy_state_alias",
        "DEFAULT_SPAWN_OFFSET",
        "kDefaultWizardBotOffset",
        "gameplay_player_fallback_position",
        "main_menu_compatibility",
        "ALLYPROBE",
        "ALLYTEXTPROBE",
        "monotonic_milliseconds) or 0",
        "tonumber(choices.generation) or 0",
        "region_index or -1",
        "region_type_id or -1",
        "now_ms) or state.last_tick_ms or 0",
    )
    stale_path_word = re.compile(r"\b(?:fallback|legacy|backward|compatibility|compatible)\b", re.I)
    regressions: list[str] = []
    for path in active_paths:
        text = read_text(path)
        for token in forbidden_tokens:
            if token in text:
                regressions.append(f"{path.relative_to(ROOT)} contains {token}")
        if stale_path_word.search(text):
            regressions.append(f"{path.relative_to(ROOT)} contains stale path language")

    if regressions:
        raise StaticReTestFailure("; ".join(regressions))
    return "active C++/Lua/layout/probe sources contain no Read*Or API, default bot offsets, or stale path wording"


def test_accepted_native_shims_are_documented() -> str:
    doc_text = read_text(ACCEPTED_NATIVE_SHIMS_DOC)
    plan_text = read_text(NATIVE_SEAM_PLAN)
    required_tokens = (
        "# Accepted Native Shims",
        "Cast gate patches and progression-slot owner context",
        "Active spell object lookup and Boulder release normalization",
        "Native spell stats and mana spend scaling",
        "Source-profile staging for wizard visuals",
        "Movement and pathfinding bridge",
        "Participant collision and target cleanup",
        "Live memory/debug tooling",
        "Diagnostic logging gates",
        "kEnableWizardBotHotPathDiagnostics = false",
        "Would enabling several bots spam logs or per-frame memory dumps",
    )
    missing = [token for token in required_tokens if token not in doc_text]
    if missing:
        raise StaticReTestFailure(
            "accepted native shim doc is missing token(s): " + ", ".join(missing))
    if "docs/accepted-native-shims.md" not in plan_text:
        raise StaticReTestFailure("native seam plan does not link the accepted native shim inventory")
    return "accepted native shims and multiplayer guardrails are documented"


def test_hot_path_diagnostics_are_default_off_and_gated() -> str:
    constants_text = read_text(GAMEPLAY_CONSTANTS)
    if "constexpr bool kEnableWizardBotHotPathDiagnostics = false;" not in constants_text:
        raise StaticReTestFailure("wizard bot hot-path diagnostics are not default-off")

    player_cast_text = read_player_cast_hooks_source()
    required_dispatch_gate = (
        "log_this =\n"
        "                binding->ongoing_cast.startup_in_progress ||\n"
        "                kEnableWizardBotHotPathDiagnostics;"
    )
    if required_dispatch_gate not in player_cast_text:
        raise StaticReTestFailure(
            "spell_dispatch logging is no longer limited to cast startup or hot-path diagnostics")

    files_and_tokens = (
        (STANDALONE_DEBUG_SUMMARIES, "[bots] visual stage="),
        (STANDALONE_DEBUG_SUMMARIES, "[bots] source_create stage="),
        (STANDALONE_SLOT_BOT_CREATION, "[bots] visual stage=slot_actor_helper_lanes_seeded"),
        (STANDALONE_EQUIP_VISUAL_LANES, "[bots] visual stage=slot_actor_owned_staff_attached"),
        (STANDALONE_SELECTION_PRIMING, "[bots] visual stage=selection_pre_refresh"),
        (STANDALONE_SELECTION_PRIMING, "[bots] visual stage=selection_post_refresh"),
        (STANDALONE_EQUIP_VISUAL_LANES, "[bots] equip_attach before label="),
        (STANDALONE_EQUIP_VISUAL_LANES, "[bots] equip_attach after label="),
        (DISPATCH_REQUEST_QUEUES, "[bots] queued sync update bot_id="),
        (DISPATCH_PUMP_LOOP, "[bots] pump sync bot_id="),
        (PLAYER_ACTOR_TICK_HOOK, "[bots] wizard stock cast input. actor="),
    )
    ungated: list[str] = []
    for path, token in files_and_tokens:
        text = read_text(path)
        index = text.find(token)
        if index < 0:
            ungated.append(f"{path.relative_to(ROOT)} missing {token}")
            continue
        window = text[max(0, index - 500):index]
        if (
            "if constexpr (kEnableWizardBotHotPathDiagnostics)" not in window
            and "if constexpr (!kEnableWizardBotHotPathDiagnostics)" not in window
        ):
            ungated.append(f"{path.relative_to(ROOT)} has ungated {token}")
    if ungated:
        raise StaticReTestFailure("; ".join(ungated))
    actor_tick_text = read_text(PLAYER_ACTOR_TICK_HOOK)
    if (
        "[bots] native action manager pump. bot_id=" not in actor_tick_text or
        "kEnableWizardBotHotPathDiagnostics &&\n         now_ms - s_last_action_pump_log_ms >= 500" not in actor_tick_text
    ):
        raise StaticReTestFailure("native action manager pump success logging is not hot-path gated")
    return "high-volume dispatch, visual, equip, and sync diagnostics are gated by the default-off flag"


def test_local_multiplayer_udp_transport_is_wired() -> str:
    protocol_text = read_text(MULTIPLAYER_PROTOCOL)
    runtime_state_text = read_multiplayer_runtime_state_source()
    transport_header_text = read_text(MULTIPLAYER_LOCAL_TRANSPORT_HEADER)
    transport_text = read_multiplayer_transport_source()
    native_enemy_lifecycle_header_text = read_text(NATIVE_ENEMY_LIFECYCLE_HEADER)
    native_enemy_lifecycle_text = read_text(NATIVE_ENEMY_LIFECYCLE)
    world_snapshot_reconciliation_text = read_text(WORLD_SNAPSHOT_RECONCILIATION)
    service_loop_text = read_text(MULTIPLAYER_SERVICE_LOOP)
    lua_exec_pipe_text = read_text(LUA_EXEC_PIPE)
    staged_game_launcher_text = read_text(STAGED_GAME_LAUNCHER)
    launcher_command_parser_text = read_text(ROOT / "SolomonDarkModLauncher/src/Commands/LauncherCommandParser.cs")
    isolated_profile_bootstrapper_text = read_text(ROOT / "SolomonDarkModLauncher/src/Launch/IsolatedProfileBootstrapper.cs")
    stage_sandbox_links_text = read_text(ROOT / "SolomonDarkModLauncher/src/Staging/StageSandboxCompatibilityLinks.cs")
    project_text = read_text(MOD_LOADER_PROJECT)
    project_filters_text = read_text(MOD_LOADER_PROJECT_FILTERS)
    bot_runtime_header_text = read_text(BOT_RUNTIME_HEADER)
    bot_snapshots_text = read_text(BOT_RUNTIME_SNAPSHOTS_API)
    entity_sync_text = read_text(PARTICIPANT_ENTITY_SYNC)
    scene_binding_text = read_text(PARTICIPANT_SCENE_BINDING_TICKS)
    participant_snapshot_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_registry_and_movement_participant_snapshot.inl"
    )
    native_remote_playback_text = read_source_unit(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_movement/native_remote_playback.inl"
    )
    orb_pickup_hook_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/orb_pickup_hook.inl"
    )
    gold_pickup_hook_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/gold_pickup_hook.inl"
    )
    item_drop_pickup_hook_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/item_drop_pickup_hook.inl"
    )
    replicated_loot_reconciliation_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/replicated_loot_reconciliation.inl"
    )
    host_loot_drop_deactivation_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/host_loot_drop_deactivation.inl"
    )
    spell_effect_transport_text = read_text(
        ROOT / "SolomonDarkModLoader/src/multiplayer_local_transport/spell_effect_sync.inl"
    )
    spell_effect_reconciliation_text = "\n".join(
        (
            read_text(
                ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/spell_effect_reconciliation.inl"
            ),
            read_text(
                ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/spell_effect_materialization.inl"
            ),
        )
    )
    participant_collision_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_movement/participant_collision_response.inl"
    )
    networking_doc_text = read_text(NETWORKING_DOC)
    world_sync_plan_text = read_text(WORLD_SYNC_AUTHORITY_PLAN_DOC)
    participant_doc_text = read_text(MULTIPLAYER_PARTICIPANT_MODEL_DOC)
    script_text = read_text(LOCAL_MULTIPLAYER_PAIR_SCRIPT)
    verifier_text = read_text(LOCAL_MULTIPLAYER_SYNC_VERIFIER)
    run_snapshot_verifier_text = read_text(RUN_WORLD_SNAPSHOT_VERIFIER)
    enemy_damage_claim_verifier_text = read_text(ENEMY_DAMAGE_CLAIM_SYNC_VERIFIER)
    run_static_layout_verifier_text = read_text(RUN_STATIC_LAYOUT_SYNC_VERIFIER)
    player_health_death_verifier_text = read_text(PLAYER_HEALTH_DEATH_SYNC_VERIFIER)
    run_seed_verifier_text = read_text(RUN_ENEMY_SEED_VERIFIER)
    run_enemy_presentation_probe_text = read_text(RUN_ENEMY_PRESENTATION_PROBE)
    run_reward_sync_probe_text = read_text(RUN_REWARD_SYNC_PROBE)
    progression_ledger_sync_verifier_text = read_text(
        ROOT / "tools/verify_multiplayer_progression_ledger_sync.py"
    )
    level_up_offer_sync_verifier_text = read_text(
        ROOT / "tools/verify_multiplayer_level_up_offer_sync.py"
    )
    host_owned_level_up_sync_verifier_text = read_text(
        ROOT / "tools/verify_multiplayer_host_owned_level_up_sync.py"
    )
    progression_probe_text = read_text(
        ROOT / "tools/multiplayer_progression_probe.py"
    )
    fireball_explode_verifier_text = read_text(
        ROOT / "tools/verify_multiplayer_fireball_explode_effect_sync.py"
    )
    skill_choices_api_text = read_source_unit(
        ROOT / "SolomonDarkModLoader/src/bot_runtime/public_api/skill_choices_api.inl"
    )
    state_getters_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_state_getters.inl"
    )
    participant_snapshot_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_registry_and_movement_participant_snapshot.inl"
    )
    gold_pickup_authority_verifier_text = read_text(
        ROOT / "tools/verify_multiplayer_gold_pickup_authority.py"
    )
    orb_pickup_authority_verifier_text = read_text(
        ROOT / "tools/verify_multiplayer_orb_pickup_authority.py"
    )
    inventory_audit_verifier_text = read_text(
        ROOT / "tools/verify_multiplayer_inventory_audit.py"
    )
    item_potion_contract_verifier_text = read_text(
        ROOT / "tools/verify_multiplayer_item_potion_pickup_contract.py"
    )
    enemy_soft_reconciliation_verifier_text = read_text(
        ROOT / "tools/verify_multiplayer_enemy_soft_reconciliation.py"
    )
    level_up_choice_and_picker_text = read_source_unit(
        ROOT
        / "SolomonDarkModLoader/src/multiplayer_local_transport/level_up_choice_and_picker.inl"
    )
    skill_picker_visual_identity_verifier_text = read_text(
        ROOT / "tools/verify_multiplayer_skill_picker_visual_identity.py"
    )
    lua_input_text = read_text(ROOT / "SolomonDarkModLoader/src/lua_engine_bindings_input.cpp")
    lua_gameplay_text = read_text(ROOT / "SolomonDarkModLoader/src/lua_engine_bindings_gameplay.cpp")
    lua_runtime_text = read_lua_runtime_source()
    named_hub_npc_probe_text = read_text(ROOT / "tools/probe_named_hub_npc_fields.py")
    inventory_item_doc_text = read_text(ROOT / "docs/inventory-item-investigation.md")
    binary_layout_text = read_text(BINARY_LAYOUT)
    background_focus_text = read_text(ROOT / "SolomonDarkModLoader/src/background_focus_bypass.cpp")
    gameplay_seams_header_text = read_gameplay_seams_header_source()
    gameplay_seams_bindings_text = read_text(
        ROOT / "SolomonDarkModLoader/src/gameplay_seams/state_and_address_bindings.inl"
    )
    gameplay_seams_size_bindings_text = read_text(
        ROOT / "SolomonDarkModLoader/src/gameplay_seams/size_bindings.inl"
    )
    dispatch_thread_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_gameplay_thread_dispatch.inl"
    )
    dispatch_pump_loop_text = read_text(DISPATCH_PUMP_LOOP)
    run_generation_seed_helpers_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/run_generation_seed_helpers.inl"
    )
    run_lifecycle_level_hooks_text = read_text(
        ROOT / "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks.inl"
    )
    participant_entity_lifecycle_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_registry_and_movement_participant_lifecycle.inl"
    )

    required_pairs = (
        (protocol_text, "constexpr std::uint16_t kProtocolVersion = 64;"),
        (protocol_text, "kParticipantDisplayNameBytes"),
        (protocol_text, "kParticipantInventorySnapshotMaxItems"),
        (protocol_text, "kParticipantProgressionBookSnapshotMaxEntries"),
        (protocol_text, "kWorldSnapshotActorsPerFragment"),
        (protocol_text, "kWorldSnapshotMaxLogicalActors"),
        (protocol_text, "kLootSnapshotMaxDrops"),
        (protocol_text, "kWorldActorStudentVisualStateBytes"),
        (protocol_text, "kWorldActorStudentBookPaletteMaxEntries"),
        (protocol_text, "std::uint32_t snapshot_id;"),
        (protocol_text, "LootSnapshotFlagTruncated"),
        (protocol_text, "LootSnapshot = 6"),
        (protocol_text, "EnemyDamageClaim = 7"),
        (protocol_text, "EnemyDamageResult = 8"),
        (protocol_text, "std::uint8_t claim_flags;"),
        (protocol_text, "kEnemyDamageClaimFlagTargetPositionOptional"),
        (protocol_text, "kEnemyDamageClaimKnownFlags"),
        (protocol_text, "LootPickupRequest = 9"),
        (protocol_text, "LootPickupResult = 10"),
        (protocol_text, "LevelUpOffer = 11"),
        (protocol_text, "LevelUpChoice = 12"),
        (protocol_text, "LevelUpChoiceResult = 13"),
        (protocol_text, "SpellEffectSnapshot = 14"),
        (protocol_text, "kSpellEffectSnapshotMaxEffects"),
        (protocol_text, "SpellEffectStateFlagEmberRuntime"),
        (protocol_text, "SpellEffectStateFlagFirewalkerRuntime"),
        (protocol_text, "struct SpellEffectPacketState"),
        (protocol_text, "struct SpellEffectSnapshotPacket"),
        (protocol_text, "static_assert(sizeof(SpellEffectPacketState) == 124"),
        (protocol_text, "static_assert(sizeof(SpellEffectSnapshotPacket) == 4000"),
        (protocol_text, "kLevelUpWaitStatusMaxParticipants"),
        (protocol_text, "std::uint8_t level_up_pause_active"),
        (protocol_text, "std::uint8_t level_up_waiting_count"),
        (protocol_text, "std::uint64_t level_up_waiting_participant_ids"),
        (native_enemy_lifecycle_header_text, "TryTriggerRunEnemyDeath"),
        (native_enemy_lifecycle_text, "ResolveGameAddressOrZero(kEnemyDeath)"),
        (native_enemy_lifecycle_text, "kEnemyDeathHandledOffset"),
        (native_enemy_lifecycle_text, "kEnemyDeathPresenterVtableSlotOffset"),
        (native_enemy_lifecycle_text, "CallEnemyDeathPresenterVirtualSafe"),
        (native_enemy_lifecycle_text, "CallEnemyDeathSafe"),
        (binary_layout_text, "enemy_death_presenter_vtable_slot=0x50"),
        (gameplay_seams_header_text, "kEnemyDeathPresenterVtableSlotOffset"),
        (gameplay_seams_size_bindings_text, "enemy_death_presenter_vtable_slot"),
        (world_snapshot_reconciliation_text, "HoldReplicatedRunEnemyDeath"),
        (enemy_damage_claim_verifier_text, "wait_for_host_enemy_native_death_log"),
        (project_text, "include\\native_enemy_lifecycle.h"),
        (project_text, "src\\native_enemy_lifecycle.cpp"),
        (project_filters_text, "include\\native_enemy_lifecycle.h"),
        (project_filters_text, "src\\native_enemy_lifecycle.cpp"),
        (protocol_text, "Gold = 1"),
        (protocol_text, "enum class LootPickupResultCode"),
        (protocol_text, "enum class LevelUpChoiceResultCode"),
        (protocol_text, "struct LootPickupRequestPacket"),
        (protocol_text, "struct LootPickupResultPacket"),
        (protocol_text, "struct LevelUpOfferPacket"),
        (protocol_text, "struct LevelUpChoicePacket"),
        (protocol_text, "struct LevelUpChoiceResultPacket"),
        (protocol_text, "std::uint16_t resulting_active;"),
        (protocol_text, "struct ParticipantInventoryItemPacketState"),
        (protocol_text, "struct ParticipantProgressionBookEntryPacketState"),
        (protocol_text, "struct LevelUpOfferOptionPacketState"),
        (protocol_text, "Orb = 4"),
        (protocol_text, "WorldActorSnapshotFlagLifecycleOwned"),
        (protocol_text, "WorldActorPresentationFlagAnimationDriveWord"),
        (protocol_text, "WorldActorPresentationFlagStudentVisualState"),
        (protocol_text, "WorldActorPresentationFlagStudentVariantBytes"),
        (protocol_text, "WorldActorPresentationFlagLocomotionFloats"),
        (protocol_text, "WorldActorPresentationFlagStudentBookPalette"),
        (protocol_text, "WorldActorSnapshotFlagRunStatic"),
        (protocol_text, "WorldActorSnapshotFlagTargetAuthoritative"),
        (protocol_text, "std::uint64_t target_participant_id;"),
        (protocol_text, "std::uint32_t target_native_type_id;"),
        (protocol_text, "std::int32_t target_actor_slot;"),
        (protocol_text, "std::int32_t target_world_slot;"),
        (protocol_text, "std::int32_t target_bucket_delta;"),
        (protocol_text, "std::uint64_t participant_id;"),
        (protocol_text, "std::uint64_t target_network_actor_id;"),
        (protocol_text, "float life_current;"),
        (protocol_text, "float life_max;"),
        (protocol_text, "float mana_current;"),
        (protocol_text, "float mana_max;"),
        (protocol_text, "std::int32_t owned_gold;"),
        (protocol_text, "std::uint32_t gold_revision;"),
        (protocol_text, "std::uint32_t concentration_revision;"),
        (protocol_text, "std::int32_t concentration_entry_a;"),
        (protocol_text, "std::int32_t concentration_entry_b;"),
        (protocol_text, "struct ParticipantDerivedStatPacketState"),
        (protocol_text, "std::uint32_t derived_stat_revision;"),
        (protocol_text, "std::uint16_t inventory_item_count;"),
        (protocol_text, "ParticipantInventorySnapshotFlagTruncated"),
        (protocol_text, "ParticipantProgressionBookSnapshotFlagTruncated"),
        (protocol_text, "std::uint16_t progression_book_entry_count;"),
        (protocol_text, "ParticipantPresentationFlagAnimationDriveWord"),
        (protocol_text, "ParticipantPresentationFlagRenderDriveFloats"),
        (protocol_text, "ParticipantPresentationFlagStaffVisualState"),
        (protocol_text, "ParticipantPresentationFlagRenderSelectorBytes"),
        (protocol_text, "ParticipantPresentationFlagVisualLinkColorBlocks"),
        (protocol_text, "std::uint32_t attachment_staff_visual_state;"),
        (protocol_text, "std::uint8_t primary_visual_link_color_block"),
        (protocol_text, "std::uint32_t anim_drive_state_word;"),
        (protocol_text, "float magic_shield_absorb_remaining;"),
        (protocol_text, "float magic_shield_absorb_capacity;"),
        (protocol_text, "float magic_shield_explosion_fraction;"),
        (protocol_text, "float magic_shield_hit_flash;"),
        (protocol_text, "float render_drive_overlay_alpha;"),
        (protocol_text, "float render_drive_move_blend;"),
        (protocol_text, "display_name"),
        (protocol_text, "static_assert(sizeof(ParticipantInventoryItemPacketState) == 16"),
        (protocol_text, "static_assert(sizeof(ParticipantProgressionBookEntryPacketState) == 20"),
        (protocol_text, "std::uint64_t authority_participant_id;"),
        (protocol_text, "static_assert(sizeof(StatePacket) == 4204"),
        (protocol_text, "static_assert(sizeof(StudentBookPaletteEntryPacketState) == 24"),
        (protocol_text, "static_assert(sizeof(NamedHubNpcPresentationPacketState) == 40"),
        (protocol_text, "static_assert(sizeof(WorldActorSnapshotPacketState) == 304"),
        (protocol_text, "static_assert(sizeof(WorldSnapshotPacket) == 1264"),
        (protocol_text, "static_assert(sizeof(LootDropSnapshotPacketState) == 112"),
        (protocol_text, "static_assert(sizeof(LootSnapshotPacket) == 7200"),
        (protocol_text, "static_assert(sizeof(LootPickupRequestPacket) == 56"),
        (protocol_text, "static_assert(sizeof(LootPickupResultPacket) == 164"),
        (protocol_text, "static_assert(sizeof(LevelUpOfferPacket) == 116"),
        (protocol_text, "static_assert(sizeof(LevelUpChoicePacket) == 40"),
        (protocol_text, "static_assert(sizeof(LevelUpChoiceResultPacket) == 64"),
        (runtime_state_text, "LocalUdp"),
        (runtime_state_text, "ParticipantOwnedProgressionState"),
        (runtime_state_text, "ParticipantInventoryItemState"),
        (runtime_state_text, "ParticipantProgressionBookEntryState"),
        (runtime_state_text, "inventory_item_total_count"),
        (runtime_state_text, "std::vector<ParticipantInventoryItemState> inventory_items"),
        (runtime_state_text, "progression_book_entry_total_count"),
        (runtime_state_text, "concentration_selection_valid"),
        (runtime_state_text, "ParticipantDerivedStatState"),
        (runtime_state_text, "std::vector<ParticipantProgressionBookEntryState> progression_book_entries"),
        (runtime_state_text, "ability_loadout_valid"),
        (runtime_state_text, "WorldSnapshotRuntimeInfo"),
        (runtime_state_text, "LootSnapshotRuntimeInfo"),
        (runtime_state_text, "LootPickupResultRuntimeInfo"),
        (runtime_state_text, "SpellEffectSnapshotRuntimeInfo"),
        (runtime_state_text, "SpellEffectApplyRuntimeInfo"),
        (runtime_state_text, "std::vector<SpellEffectSnapshotRuntimeInfo> spell_effect_snapshots"),
        (runtime_state_text, "WorldSnapshotApplyRuntimeInfo"),
        (runtime_state_text, "WorldSnapshotActorBindingRuntimeInfo"),
        (runtime_state_text, "ParticipantTransformSample"),
        (runtime_state_text, "transform_history"),
        (runtime_state_text, "world_snapshot_history"),
        (runtime_state_text, "loot_snapshot"),
        (runtime_state_text, "last_loot_pickup_result"),
        (runtime_state_text, "LevelUpOfferRuntimeInfo"),
        (runtime_state_text, "LevelUpChoiceResultRuntimeInfo"),
        (runtime_state_text, "std::uint16_t resulting_active = 0;"),
        (runtime_state_text, "LevelUpWaitStatusRuntimeInfo"),
        (runtime_state_text, "active_level_up_offer"),
        (runtime_state_text, "last_level_up_choice_result"),
        (runtime_state_text, "level_up_wait_status"),
        (runtime_state_text, "kParticipantTransformHistoryCapacity"),
        (runtime_state_text, "kWorldSnapshotHistoryCapacity"),
        (runtime_state_text, "TrySampleParticipantTransform"),
        (runtime_state_text, "TrySampleWorldSnapshot"),
        (runtime_state_text, "InterpolateHeadingDegrees"),
        (runtime_state_text, "float life_current"),
        (runtime_state_text, "float mana_current"),
        (runtime_state_text, "std::uint32_t gold_revision"),
        (runtime_state_text, "inventory_host_authoritative"),
        (runtime_state_text, "float resource_delta"),
        (runtime_state_text, "std::int32_t resource_kind"),
        (runtime_state_text, "float resulting_life_current"),
        (lua_runtime_text, "participant.runtime.position_x"),
        (lua_runtime_text, "participant.runtime.position_y"),
        (lua_gameplay_text, "get_replicated_spell_effects"),
        (transport_text, '#include "multiplayer_local_transport/spell_effect_sync.inl"'),
        (transport_text, "ApplySpellEffectSnapshotPacket(packet, from, now_ms)"),
        (transport_text, "SendSpellEffectSnapshot(now_ms)"),
        (spell_effect_transport_text, "TryCaptureLocalSpellEffectState"),
        (spell_effect_transport_text, "actor.actor_slot != 0"),
        (spell_effect_transport_text, "SpellEffectStateFlagTerminal"),
        (transport_text, "kLocalSpellEffectTombstoneHoldMs = 4000"),
        (spell_effect_transport_text, "RelayPacketBufferToPeers("),
        (spell_effect_reconciliation_text, "MatchReplicatedSpellEffectActor"),
        (spell_effect_reconciliation_text, "owner_gameplay.gameplay_slot"),
        (spell_effect_reconciliation_text, "actor.actor_slot != owner_gameplay_slot"),
        (participant_snapshot_text, "std::int8_t native_actor_slot = -1;"),
        (participant_snapshot_text, "snapshot.actor_slot = static_cast<int>(native_actor_slot);"),
        (spell_effect_reconciliation_text, "TryApplyReplicatedSpellEffectState"),
        (spell_effect_reconciliation_text, "effect.ember_runtime_valid"),
        (spell_effect_reconciliation_text, "effect.terminal"),
        (fireball_explode_verifier_text, "include_client=False"),
        (binary_layout_text, "spell_effect_motion_x=0x13C"),
        (binary_layout_text, "ember_lifetime=0x150"),
        (gameplay_seams_header_text, "kEmberLifetimeOffset"),
        (gameplay_seams_size_bindings_text, "ember_lifetime"),
        (runtime_state_text, "std::uint16_t presentation_flags"),
        (runtime_state_text, "float magic_shield_absorb_remaining"),
        (runtime_state_text, "float magic_shield_absorb_capacity"),
        (runtime_state_text, "float magic_shield_explosion_fraction"),
        (runtime_state_text, "float magic_shield_hit_flash"),
        (runtime_state_text, "float render_drive_overlay_alpha"),
        (runtime_state_text, "float render_drive_move_blend"),
        (runtime_state_text, "actor_total_count"),
        (runtime_state_text, "truncated"),
        (runtime_state_text, "target_authoritative"),
        (runtime_state_text, "created_actor_count"),
        (runtime_state_text, "created_actor_total_count"),
        (runtime_state_text, "presentation_write_count"),
        (runtime_state_text, "health_write_count"),
        (runtime_state_text, "dead_actor_count"),
        (runtime_state_text, "removed_actor_count"),
        (runtime_state_text, "removed_actor_total_count"),
        (runtime_state_text, "failed_remove_actor_count"),
        (runtime_state_text, "failed_remove_actor_total_count"),
        (runtime_state_text, "actor_bindings"),
        (runtime_state_text, "LootDropKindLabel"),
        (transport_header_text, "TickLocalTransport"),
        (transport_header_text, "IsLocalTransportHost"),
        (transport_header_text, "IsLocalTransportClient"),
        (transport_header_text, "GetLocalTransportParticipantId"),
        (transport_header_text, "QueueLocalLootPickupRequest"),
        (transport_header_text, "ObserveReplicatedRunEnemyDamage"),
        (transport_header_text, "PublishHostLevelUpOffers"),
        (transport_header_text, "QueueLocalLevelUpChoice"),
        (transport_header_text, "ShouldPauseGameplayForLevelUpSelection"),
        (transport_header_text, "TryBuildLevelUpWaitStatusText"),
        (transport_text, "SDMOD_MULTIPLAYER_TRANSPORT"),
        (transport_text, "SDMOD_MULTIPLAYER_LOCAL_PORT"),
        (transport_text, "SDMOD_MULTIPLAYER_REMOTE_PORT"),
        (transport_text, "SDMOD_MULTIPLAYER_PLAYER_NAME"),
        (transport_text, "RelayParticipantPacketToPeers"),
        (transport_text, "NormalizeMagicShieldState"),
        (transport_text, "kMagicShieldAbsorbEpsilon"),
        (transport_text, "packet->anim_drive_state_word = local.runtime.anim_drive_state_word"),
        (transport_text, "packet->magic_shield_absorb_remaining ="),
        (transport_text, "packet->magic_shield_absorb_capacity ="),
        (transport_text, "packet->magic_shield_explosion_fraction ="),
        (transport_text, "participant->runtime.magic_shield_absorb_remaining ="),
        (transport_text, "participant->runtime.magic_shield_absorb_capacity ="),
        (transport_text, "participant->runtime.magic_shield_explosion_fraction ="),
        (transport_text, "sample.magic_shield_absorb_remaining = normalized.magic_shield_absorb_remaining"),
        (transport_text, "sample.render_drive_overlay_alpha = packet.render_drive_overlay_alpha"),
        (transport_text, "staff attachment tail field at +0x84 is native-owned"),
        (transport_text, "packet.presentation_flags &"),
        (transport_text, "participant->runtime.attachment_staff_visual_state = 0"),
        (transport_text, "BuildLocalWorldSnapshot"),
        (transport_text, "ResolveRunEnemyTargetParticipantId"),
        (transport_text, "target_native_type_id == 1"),
        (transport_text, "target_actor_slot == 0"),
        (transport_text, "PopulateRunEnemyNativeTargetSnapshot"),
        (transport_text, "kActorCurrentTargetBucketDeltaOffset"),
        (transport_text, "WorldActorSnapshotFlagTargetAuthoritative"),
        (transport_text, "snapshot.target_participant_id = ResolveRunEnemyTargetParticipantId(actor.actor_address)"),
        (transport_text, "TryTriggerRunEnemyDeath(target_actor.actor_address"),
        (transport_text, "TryTriggerRunEnemyDeath(actor_address"),
        (transport_text, "kRecentRunEnemyDeathSnapshotHoldMs"),
        (transport_text, "RecentRunEnemyDeathSnapshot"),
        (transport_text, "recent_run_enemy_deaths_by_network_id"),
        (transport_text, "RecordRecentRunEnemyDeathSnapshot"),
        (transport_text, "WorldActorSnapshotFlagDead |"),
        (transport_text, "WorldActorSnapshotFlagTrackedEnemy |"),
        (transport_text, "local_death_called"),
        (transport_text, "(actor.dead || actor.hp > kEnemyDamageClaimHpEpsilon)"),
        (transport_text, "BuildLocalLootSnapshotPacket"),
        (transport_text, "PopulateWorldActorPresentationSnapshot"),
        (transport_text, "student_visual_state"),
        (transport_text, "TryGetRunLifecycleEnemySpawnSerial"),
        (transport_text, "kRunHostLocalWorldActorNetworkIdBase"),
        (transport_text, "kRunLootDropNetworkIdBase"),
        (transport_text, "kOrbRewardNativeTypeId"),
        (transport_text, "kItemDropNativeTypeId"),
        (transport_text, "kSolomonDigNativeTypeId"),
        (transport_text, "IsRunStaticLayoutActor"),
        (transport_text, "run_host_local_world_actor_ids_by_address"),
        (transport_text, "run_loot_drop_ids_by_address"),
        (transport_text, "AllocateRunHostLocalWorldActorNetworkId"),
        (transport_text, "AllocateRunLootDropNetworkId"),
        (transport_text, "PruneRunHostLocalWorldActorNetworkIds"),
        (transport_text, "PruneRunLootDropNetworkIds"),
        (transport_text, "kGoldRewardAmountOffset"),
        (transport_text, "built.flags = built.amount > 0 && lifetime != 0 ? LootDropSnapshotFlagActive : 0"),
        (host_loot_drop_deactivation_text, "kReplicatedGoldAmountOffset"),
        (host_loot_drop_deactivation_text, "kReplicatedGoldLifetimeOffset"),
        (transport_text, "kOrbRewardValueOffset"),
        (transport_text, "kOrbRewardResourceKindOffset"),
        (transport_text, "kOrbHealthRewardScale"),
        (transport_text, "kOrbManaRewardScale"),
        (binary_layout_text, "actor_world_transient_actor_list=0x8B70"),
        (gameplay_seams_header_text, "kActorWorldTransientActorListOffset"),
        (gameplay_seams_size_bindings_text, "actor_world_transient_actor_list"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_state_getters.inl"), "AppendTransientRewardActors"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_state_getters.inl"), "0x07DB"),
        (transport_text, "assigned host-local run actor network id"),
        (transport_text, "BuildRunWorldActorNetworkId"),
        (transport_text, "ParticipantSceneIntentKind::SharedHub"),
        (transport_text, "ParticipantSceneIntentKind::Run"),
        (transport_text, "actor.tracked_enemy"),
        (transport_text, "TryAcceptWorldSnapshotFragment"),
        (transport_text, "LootSnapshotFlagTruncated"),
        (transport_text, "ApplyWorldSnapshotPacket"),
        (world_snapshot_reconciliation_text, "ResolveReplicatedRunEnemyTargetActor"),
        (world_snapshot_reconciliation_text, "TryReadActorWorldTargetSlotState"),
        (world_snapshot_reconciliation_text, "ApplyReplicatedRunEnemyTarget"),
        (world_snapshot_reconciliation_text, "kActorCurrentTargetActorOffset"),
        (world_snapshot_reconciliation_text, "kHostileTargetBucketDeltaOffset"),
        (world_snapshot_reconciliation_text, "authoritative_actor.target_participant_id"),
        (world_snapshot_reconciliation_text, "ApplyReplicatedRunEnemyTarget("),
        (lua_gameplay_text, "target_participant_id"),
        (lua_gameplay_text, "target_authoritative"),
        (read_text(ROOT / "tools/verify_run_enemy_target_authority.py"), "replicated_target_participant_id"),
        (read_text(ROOT / "tools/verify_run_enemy_target_authority.py"), "start_host_testrun_and_wait_for_clients(timeout=60.0)"),
        (transport_text, "ApplyLootSnapshotPacket"),
        (transport_text, "ApplyLootPickupRequestPacket"),
        (transport_text, "ApplyLootPickupResultPacket"),
        (transport_text, "ApplyLevelUpOfferPacket"),
        (transport_text, "ApplyLevelUpChoicePacket"),
        (transport_text, "ApplyLevelUpChoiceResultPacket"),
        (transport_text, "BuildLevelUpChoiceResultPacket"),
        (transport_text, "packet.resulting_active > 0"),
        (transport_text, "native_applied_level_up_result_offer_ids"),
        (transport_text, "Multiplayer host-self level-up choice resolved and broadcast"),
        (transport_text, "const auto endpoints = BuildKnownSendEndpoints();"),
        (transport_text, "CollectUnresolvedLevelUpOfferParticipantIds"),
        (transport_text, "BuildLevelUpWaitStatusTextFromIds"),
        (transport_text, "PendingHostLevelUpOfferTarget"),
        (transport_text, "pending_level_up_offer_targets_by_participant"),
        (transport_text, "QueuePendingHostLevelUpOfferTarget"),
        (transport_text, "ProcessPendingHostLevelUpOffers"),
        (transport_text, "IsLevelUpOfferMaterializationPendingError"),
        (transport_text, "Multiplayer level-up offer deferred; participant progression not materialized"),
        (transport_text, "ClearLocalLevelUpPickerAfterProgrammaticChoice"),
        (transport_text, "Multiplayer level-up native picker closed and cleared after programmatic accepted choice"),
        (transport_text, "kProgressionLevelUpPickerUiFlagOffset"),
        (transport_text, "kProgressionLevelUpTemporaryPickerObjectOffset"),
        (transport_text, "kProgressionLevelUpTemporaryPickerValueOffset"),
        (transport_text, "TryApplyLocalProgrammaticLevelUpChoiceThroughNativePicker"),
        (transport_text, "CallLevelUpScreenCloseSafe"),
        (transport_text, "Multiplayer level-up native picker applied locally through programmatic choice"),
        (level_up_choice_and_picker_text, "HookLocalLevelUpOptionRoll"),
        (level_up_choice_and_picker_text, "TryOverwriteNativeLevelUpOptions"),
        (level_up_choice_and_picker_text, "ArmLocalLevelUpOptionRoll"),
        (level_up_choice_and_picker_text, "native option roll replaced before visual build"),
        (transport_text, "ShutdownLocalLevelUpOptionRollHook"),
        (skill_picker_visual_identity_verifier_text, "SKILL_VISUAL_IDENTITY_RETURN = 0x0066FE0E"),
        (skill_picker_visual_identity_verifier_text, "visual_option_ids"),
        (skill_picker_visual_identity_verifier_text, "picker_option_ids"),
        (skill_picker_visual_identity_verifier_text, "wait_for_choice_result"),
        (transport_text, "RelayPacketToPeers(result, endpoint)"),
        (transport_text, "HydrateAuthoritativeRemoteProgressionEntryState(\n                    packet.target_participant_id"),
        (transport_text, "SendQueuedLevelUpChoices"),
        (transport_text, "SyncParticipantProgressionToSharedLevelUpAndRollChoices"),
        (transport_text, "ReconcileRemoteParticipantNativeProgression"),
        (transport_text, "kNativeProgressionReconcileAuditMs"),
        (transport_text, "SyncParticipantProgressionToSharedLevelUp("),
        (transport_text, "ReconcileRemoteParticipantNativeProgression(now_ms);"),
        (transport_text, "ApplyAuthoritativeRemoteSkillRankDelta"),
        (transport_text, "ApplyLocalPlayerSkillChoiceOption"),
        (transport_text, "LevelUpChoiceResultCode::InvalidOption"),
        (transport_text, "HasLocalLevelUpOfferAwaitingNativePresentation"),
        (transport_text, "if (HasPendingLocalLevelUpChoice(runtime_state)) {\n        return true;\n    }"),
        (dispatch_pump_loop_text, "allow_level_up_picker_create"),
        (dispatch_pump_loop_text, "HasLocalLevelUpOfferAwaitingNativePresentation"),
        (dispatch_pump_loop_text, "ReconcileLocalLevelUpOfferPresentation(\n            now_ms,\n            allow_level_up_picker_create)"),
        (skill_choices_api_text, "CaptureLocalSharedLevelUpVitals"),
        (skill_choices_api_text, "RestoreLocalSharedLevelUpVitals"),
        (skill_choices_api_text, "local shared level-up sync preserving live vitals"),
        (skill_choices_api_text, "SyncParticipantProgressionToSharedLevelUp("),
        (transport_text, "ValidateLootPickupRequest"),
        (transport_text, "TryPopulateOrbLootDropSnapshot"),
        (transport_text, "TryPopulateItemLootDropSnapshot"),
        (transport_text, "TryReadItemDropHeldItemMetadata"),
        (transport_text, "QueueHostLootDropDeactivation("),
        (transport_text, "ProcessCompletedHostLootPickups();"),
        (host_loot_drop_deactivation_text, "PumpHostLootDropDeactivation()"),
        (host_loot_drop_deactivation_text, "CallActorRequestRetirementSafe("),
        (transport_text, "TryBuildAcceptedOrbLootPickupPayload"),
        (transport_text, "TryBuildAcceptedItemLootPickupPayload"),
        (transport_text, "ApplyOwnedInventoryLootItem"),
        (transport_text, "TryWriteLocalPlayerOrbResource"),
        (transport_text, "last_synced_enemy_hp_by_network_id"),
        (transport_text, "HasReplicatedRunEnemyDamageBaseline"),
        (transport_text, "MarkReplicatedRunEnemyDamageBaseline"),
        (transport_text, "ClearReplicatedRunEnemyDamageBaseline"),
        (transport_text, "ObservedLocalEnemyDamage"),
        (transport_text, "observed_enemy_damage_by_network_id"),
        (transport_text, "recent_local_cast_skill_id"),
        (transport_text, "recent_local_air_chain_target_until_ms"),
        (transport_text, "active.target_network_actor_id == network_actor_id"),
        (transport_text, "kEnemyDamageObservationEpsilon"),
        (transport_text, "kEnemyDamageClaimResultRetryMs"),
        (transport_text, "Multiplayer observed enemy damage reached claim threshold"),
        (transport_text, "Multiplayer observed enemy damage claim sent"),
        (transport_text, "Multiplayer observed enemy damage claim retried"),
        (transport_text, "Multiplayer enemy damage claim suppressed until first authoritative HP baseline"),
        (world_snapshot_reconciliation_text, "const bool has_damage_baseline"),
        (world_snapshot_reconciliation_text, "const bool observed_local_damage"),
        (world_snapshot_reconciliation_text, "kReplicatedRunEnemyDamageObservationEpsilon"),
        (world_snapshot_reconciliation_text, "multiplayer::ObserveReplicatedRunEnemyDamage("),
        (transport_text, "unknown_claim_flags"),
        (transport_text, "const bool target_position_optional"),
        (transport_text, "!target_position_optional &&"),
        (transport_text, "kEnemyDamageClaimFlagTargetPositionOptional"),
        (world_snapshot_reconciliation_text, "float claimed_target_x = authoritative_actor.position_x;"),
        (world_snapshot_reconciliation_text, "TryReadFiniteFloatField(actor_address, kActorPositionXOffset, &local_target_x)"),
        (world_snapshot_reconciliation_text, "ApplyReplicatedRunEnemyHealth(binding.actor.actor_address, authoritative_actor, now_ms)"),
        (transport_text, "TryApplyAcceptedEnemyDamageTargetPosition"),
        (transport_text, "accepted_new_damage"),
        (transport_text, "position_applied="),
        (transport_text, "sdmod::RebindSceneActorCell(target_actor.actor_address"),
        (enemy_damage_claim_verifier_text, 'damage_client_enemy("damage_position")'),
        (enemy_damage_claim_verifier_text, "wait_for_host_position_accept_log"),
        (
            world_snapshot_reconciliation_text,
            "has_damage_baseline &&\n        max_hp_synced &&\n        local_health.hp + kReplicatedRunEnemyDamageObservationEpsilon < authoritative_hp",
        ),
        (world_snapshot_reconciliation_text, "void ClearReplicatedRunActorBindings()"),
        (world_snapshot_reconciliation_text, "void BindReplicatedRunActor"),
        (world_snapshot_reconciliation_text, "void UnbindReplicatedRunActor"),
        (
            world_snapshot_reconciliation_text,
            "for (const auto& binding : g_replicated_run_bindings_by_network_id) {\n        multiplayer::ClearReplicatedRunEnemyDamageBaseline(binding.first);",
        ),
        (world_snapshot_reconciliation_text, "multiplayer::ClearReplicatedRunEnemyDamageBaseline(previous_by_actor->second);"),
        (replicated_loot_reconciliation_text, "kReplicatedLootPotionItemTypeId = 0x1B59"),
        (replicated_loot_reconciliation_text, "kArenaSpawnPotionDropVfuncOffset = 0x148"),
        (replicated_loot_reconciliation_text, "SpawnPotionDropFn"),
        (replicated_loot_reconciliation_text, "ExecuteSpawnReplicatedPotionDropNow"),
        (replicated_loot_reconciliation_text, "drop.drop_kind == multiplayer::LootDropKind::Potion"),
        (replicated_loot_reconciliation_text, "held_item_type_id != drop.item_type_id"),
        (replicated_loot_reconciliation_text, "memory.TryWriteField(held_item_address, kItemSlotOffset, potion_slot)"),
        (replicated_loot_reconciliation_text, "kPotionStackCountOffset,"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/native_function_types.inl"), "using SpawnPotionDropFn"),
        (protocol_text, "std::uint32_t item_type_id;"),
        (protocol_text, "std::int32_t item_slot;"),
        (protocol_text, "std::int32_t stack_count;"),
        (protocol_text, "std::uint32_t inventory_revision;"),
        (binary_layout_text, "orb_pickup=0x005E62E0"),
        (gameplay_seams_header_text, "kOrbPickup"),
        (gameplay_seams_bindings_text, '"orb_pickup", kOrbPickup'),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/native_function_types.inl"), "using OrbPickupTickFn"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/native_function_types.inl"), "using ItemDropPickupTickFn"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/gameplay_constants.inl"), "kOrbPickupHookMinimumPatchSize"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/gameplay_constants.inl"), "kItemDropPickupHookMinimumPatchSize"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/runtime_request_state.inl"), "orb_pickup_hook"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/runtime_request_state.inl"), "item_drop_pickup_hook"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_keyboard_injection.inl"), "HookOrbPickupTick"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_keyboard_injection.inl"), "RemoveX86Hook(&g_gameplay_keyboard_injection.orb_pickup_hook)"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_keyboard_injection.inl"), "HookItemDropPickupTick"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_keyboard_injection.inl"), "RemoveX86Hook(&g_gameplay_keyboard_injection.item_drop_pickup_hook)"),
        (orb_pickup_hook_text, "ShouldSuppressRemoteParticipantOrbPickup"),
        (orb_pickup_hook_text, "TryQueueReplicatedLootPickupRequest"),
        (
            orb_pickup_hook_text,
            "last_result.result_code == multiplayer::LootPickupResultCode::Accepted",
        ),
        (
            orb_pickup_hook_text,
            "last_result.participant_id == local_transport_participant_id",
        ),
        (
            orb_pickup_hook_text,
            "last_result.result_code == multiplayer::LootPickupResultCode::AlreadyGone",
        ),
        (
            orb_pickup_hook_text,
            "g_replicated_loot_pickup_request_not_before_ms.erase(presentation.network_drop_id)",
        ),
        (orb_pickup_hook_text, "LootDropKind::Orb"),
        (orb_pickup_hook_text, "IsLocalTransportHost()"),
        (orb_pickup_hook_text, "IsNativeRemoteParticipantBinding(&binding)"),
        (orb_pickup_hook_text, "return false;"),
        (orb_pickup_hook_text, "original(self);"),
        (gold_pickup_hook_text, "TryQueueReplicatedLootPickupRequest"),
        (gold_pickup_hook_text, "LootDropKind::Gold"),
        (gold_pickup_hook_text, "client_gold_pickup_tick"),
        (item_drop_pickup_hook_text, "ShouldSuppressRemoteParticipantItemDropPickup"),
        (item_drop_pickup_hook_text, "kItemDropHeldItemOffset"),
        (item_drop_pickup_hook_text, "IsNativeRemoteParticipantBinding(&binding)"),
        (item_drop_pickup_hook_text, "original(self);"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/execute_requests/spawn_reward.inl"), "health_orb"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/execute_requests/spawn_reward.inl"), "mana_orb"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/execute_requests/spawn_reward.inl"), "ExecuteSpawnGoldRewardNow"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/execute_requests/spawn_reward.inl"), "CallSpawnRewardGoldSafe"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/execute_requests/spawn_reward.inl"), "ResolveGameAddressOrZero(kSpawnRewardGold)"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/execute_requests/spawn_reward.inl"), "kSpawnRewardDefaultLifetime"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/execute_requests/spawn_reward.inl"), "CallRewardWorldAttachSafe"),
        (transport_text, "QueueHostLootDropDeactivation("),
        (transport_text, "TryWriteLocalGlobalGold"),
        (transport_text, "accepted_loot_pickup_drop_ids"),
        (transport_text, "RefreshOwnedInventoryFromSnapshot"),
        (transport_text, "packet.inventory_item_count"),
        (transport_text, "participant->owned_progression.inventory_items"),
        (transport_text, "ParticipantInventorySnapshotFlagTruncated"),
        (read_mod_loader_header_source(), "SDModInventoryState"),
        (read_mod_loader_header_source(), "kSDModInventorySnapshotMaxItems"),
        (read_mod_loader_header_source(), "TryGetPlayerInventoryState"),
        (binary_layout_text, "gameplay_item_list_root=0x13B8"),
        (binary_layout_text, "gameplay_item_list_count=0x14"),
        (binary_layout_text, "gameplay_item_list_items=0x20"),
        (binary_layout_text, "item_slot=0x1C"),
        (binary_layout_text, "potion_stack_count=0x88"),
        (binary_layout_text, "item_drop_held_item=0x148"),
        (gameplay_seams_header_text, "kGameplayItemListRootOffset"),
        (gameplay_seams_header_text, "kPotionStackCountOffset"),
        (gameplay_seams_header_text, "kItemDropHeldItemOffset"),
        (gameplay_seams_size_bindings_text, "gameplay_item_list_root"),
        (gameplay_seams_size_bindings_text, "item_drop_held_item"),
        (
            read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_state_getters.inl"),
            "const bool owns_wizard_progression = state.object_type_id == 1;",
        ),
        (
            read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_state_getters.inl"),
            "} else if (owns_wizard_progression &&",
        ),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_state_getters.inl"), "TryGetPlayerInventoryState"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_state_getters.inl"), "kGameplayItemListRootOffset"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_state_getters.inl"), "kSDModInventorySnapshotMaxItems"),
        (lua_gameplay_text, "LuaPlayerGetInventoryState"),
        (lua_gameplay_text, "\"get_inventory_state\""),
        (inventory_audit_verifier_text, "Verify typed local inventory/equip audit"),
        (inventory_audit_verifier_text, "POTION_TYPE_ID = 0x1B59"),
        (inventory_audit_verifier_text, "STAFF_HELPER_TYPE_ID = 0x1B5C"),
        (inventory_audit_verifier_text, "has_inventory_items"),
        (inventory_audit_verifier_text, "has_skillbook_entries"),
        (inventory_audit_verifier_text, "has_spellbook_entries"),
        (inventory_audit_verifier_text, "assert_owned_inventory_rows"),
        (inventory_audit_verifier_text, "inventory_item_count"),
        (inventory_audit_verifier_text, "inventory_host_authoritative"),
        (inventory_audit_verifier_text, "owned inventory missing potion slots"),
        (item_potion_contract_verifier_text, "Verify the multiplayer item/potion pickup contract"),
        (item_potion_contract_verifier_text, "item_drop_held_item=0x148"),
        (item_potion_contract_verifier_text, "TryPopulateItemLootDropSnapshot"),
        (item_potion_contract_verifier_text, "HookItemDropPickupTick"),
        (inventory_audit_verifier_text, "assert_multiplayer_boundary"),
        (lua_runtime_text, "\"inventory_items\""),
        (lua_runtime_text, "\"inventory_item_total_count\""),
        (lua_runtime_text, "\"inventory_host_authoritative\""),
        (lua_gameplay_text, "\"item_type_id\""),
        (lua_gameplay_text, "\"item_slot\""),
        (lua_gameplay_text, "\"stack_count\""),
        (lua_gameplay_text, "\"inventory_revision\""),
        (lua_gameplay_text, "\"resource_kind\""),
        (lua_gameplay_text, "\"resource_delta\""),
        (lua_gameplay_text, "\"resulting_life_current\""),
        (lua_gameplay_text, "\"resulting_mana_current\""),
        (transport_text, "SendLootSnapshot"),
        (transport_text, "SendQueuedLootPickupRequests"),
        (transport_text, "bool automatic_proximity_request = false;"),
        (
            transport_text,
            "request.automatic_proximity_request = capture != nullptr && capture->valid;",
        ),
        (transport_text, "automatic_request_already_terminal"),
        (
            transport_text,
            "last_result.participant_id == g_local_transport.local_peer_id",
        ),
        (
            transport_text,
            "Multiplayer automatic loot pickup retry suppressed after terminal result.",
        ),
        (transport_text, "complete_snapshot.actors.empty() &&"),
        (transport_text, "MaybeQueueClientHostRunStart"),
        (transport_text, "IsAuthoritativeHostParticipantPacket"),
        (transport_text, "packet.participant_id == packet.authority_participant_id"),
        (transport_text, "kClientHostRunFollowRetryMs"),
        (transport_text, "host-authoritative run entry"),
        (transport_text, "SetPendingRunGenerationSeed(packet.run_nonce"),
        (transport_text, "run_generation_seed"),
        (run_generation_seed_helpers_text, "BuildHostRunGenerationSeed"),
        (run_generation_seed_helpers_text, "ApplyPendingRunGenerationSeedForSceneSwitch"),
        (run_generation_seed_helpers_text, "kNativeGlobalRngStateGlobal"),
        (run_generation_seed_helpers_text, "kNativeRngInitialize"),
        (run_generation_seed_helpers_text, "CallNativeRngInitializeSafe"),
        (run_generation_seed_helpers_text, "Initialized host-authoritative run generation RNG"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_gameplay_action_queues.inl"), "EnsureHostRunGenerationSeed(\"hub_start_testrun_queue\")"),
        (world_snapshot_reconciliation_text, "ApplyReplicatedWorldSnapshotIfActive"),
        (world_snapshot_reconciliation_text, "authoritative_actor.run_static"),
        (world_snapshot_reconciliation_text, "ApplyHostAuthoritativeRunEntryFormationIfNeeded"),
        (world_snapshot_reconciliation_text, "GetLocalTransportParticipantId"),
        (world_snapshot_reconciliation_text, "kRunEntryFormationNavSnapMaxAuthorityDistance"),
        (world_snapshot_reconciliation_text, "kRunEntryFormationBootstrapMs"),
        (world_snapshot_reconciliation_text, "kRunEntryFormationReapplyIntervalMs"),
        (world_snapshot_reconciliation_text, "g_run_entry_formation_settled"),
        (world_snapshot_reconciliation_text, "BuildLocalReplicatedWorldActorBindings"),
        (world_snapshot_reconciliation_text, "TryCreateReplicatedSharedHubActor"),
        (world_snapshot_reconciliation_text, "IsReplicatedSharedHubFactoryActorType"),
        (world_snapshot_reconciliation_text, "CallGameObjectFactorySafe"),
        (world_snapshot_reconciliation_text, "CallActorWorldRegisterSafe"),
        (world_snapshot_reconciliation_text, "RemoveReplicatedSharedHubActor"),
        (world_snapshot_reconciliation_text, "CallActorWorldUnregisterSafe"),
        (world_snapshot_reconciliation_text, "OverlayLatestWorldSnapshotPresentation"),
        (world_snapshot_reconciliation_text, "kHubAnimationDrivePhaseUnitsPerSecond"),
        (world_snapshot_reconciliation_text, "AdvanceHubAnimationDrivePhase"),
        (world_snapshot_reconciliation_text, "case 0x138F:"),
        (lua_gameplay_text, '"sampled_ms"'),
        (world_snapshot_reconciliation_text, "ApplyReplicatedWorldActorPresentation"),
        (world_snapshot_reconciliation_text, "kStudentVisualStateBlockOffset"),
        (world_snapshot_reconciliation_text, "presentation_write_count"),
        (world_snapshot_reconciliation_text, "removed_actor_count"),
        (world_snapshot_reconciliation_text, "failed_remove_actor_count"),
        (world_snapshot_reconciliation_text, "HasPendingParticipantWorldMutation"),
        (world_snapshot_reconciliation_text, "wizard_bot_sync_not_before_ms"),
        (world_snapshot_reconciliation_text, "pending_participant_sync_requests"),
        (world_snapshot_reconciliation_text, "CanMutateReplicatedSharedHubActors"),
        (world_snapshot_reconciliation_text, "RemoveReplicatedCreatedSharedHubActorsForSceneSwitch"),
        (world_snapshot_reconciliation_text, "abandoned replicated hub actor bindings for scene switch"),
        (world_snapshot_reconciliation_text, "RemoveReplicatedSharedHubActor(binding, &exception_code)"),
        (world_snapshot_reconciliation_text, "abandoned_count"),
        (dispatch_thread_text, "PrepareGameplaySceneSwitchOnGameThread"),
        (dispatch_thread_text, "RemoveReplicatedCreatedSharedHubActorsForSceneSwitch(source)"),
        (dispatch_thread_text, "wizard_bot_sync_not_before_ms.store"),
        (dispatch_thread_text, "pending_participant_sync_requests.clear()"),
        (dispatch_thread_text, "DematerializeAllMaterializedWizardBotsForSceneSwitch(source)"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_actor_lifecycle_hooks.inl"), "PrepareGameplaySceneSwitchOnGameThread(\n        gameplay_address,\n        region_index,\n        \"gameplay_switch_region_pre_dispatch\")"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_actor_lifecycle_hooks.inl"), "puppet_manager_delete_puppet skipped object delete during scene churn"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_actor_lifecycle_hooks.inl"), "CallActorWorldUnregisterSafe"),
        (participant_entity_lifecycle_text, "ResetParticipantEntityMaterializationState(&binding)"),
        (participant_entity_lifecycle_text, "PublishParticipantGameplaySnapshot(binding)"),
        (participant_entity_lifecycle_text, "abandoned materialized bot entity for scene switch"),
        (world_snapshot_reconciliation_text, "created_actor_total_count += counts.created_actor_count"),
        (world_snapshot_reconciliation_text, "removed_actor_total_count +="),
        (world_snapshot_reconciliation_text, "failed_remove_actor_total_count +="),
        (world_snapshot_reconciliation_text, "TryRebindActorToOwnerWorld"),
        (world_snapshot_reconciliation_text, "kWorldSnapshotApplyStaleMs"),
        (world_snapshot_reconciliation_text, "kWorldSnapshotInterpolationDelayMs"),
        (world_snapshot_reconciliation_text, "TrySampleWorldSnapshot"),
        (world_snapshot_reconciliation_text, "kReplicatedRunEnemySoftCorrectionFactor"),
        (world_snapshot_reconciliation_text, "kReplicatedRunEnemyHardSnapDistance"),
        (world_snapshot_reconciliation_text, "soft_correct_live_run_enemy"),
        (enemy_soft_reconciliation_verifier_text, "INJECTED_DRIFT = 96.0"),
        (enemy_soft_reconciliation_verifier_text, "MAX_CORRECTION_STEP = 48.0"),
        (enemy_soft_reconciliation_verifier_text, "correction_step_count"),
        (world_snapshot_reconciliation_text, "ParticipantSceneIntentKind::SharedHub"),
        (world_snapshot_reconciliation_text, "ParticipantSceneIntentKind::Run"),
        (world_snapshot_reconciliation_text, "QueueGameplayStartWaves"),
        (world_snapshot_reconciliation_text, "IsLocalRunCombatAlreadyActive"),
        (world_snapshot_reconciliation_text, "remote_state_wave"),
        (world_snapshot_reconciliation_text, "MaybeCatchUpRunEnemyPoolForAuthoritativeSnapshot"),
        (world_snapshot_reconciliation_text, "TryAccelerateRunLifecycleEnemyPoolForSnapshot"),
        (world_snapshot_reconciliation_text, "CountAuthoritativeTrackedRunEnemiesForScene"),
        (world_snapshot_reconciliation_text, "authoritative_counts_by_enemy_type"),
        (world_snapshot_reconciliation_text, "authoritative_actor.tracked_enemy &&"),
        (world_snapshot_reconciliation_text, "local_counts_by_enemy_type"),
        (world_snapshot_reconciliation_text, "authoritative_count - local_count"),
        (world_snapshot_reconciliation_text, "TryBindAuthoritativeRunActorToLocalPool"),
        (world_snapshot_reconciliation_text, "IsSameReplicatedRunEnemyKind"),
        (
            world_snapshot_reconciliation_text,
            "local_actor.object_type_id == authoritative_actor.native_type_id",
        ),
        (
            world_snapshot_reconciliation_text,
            "queued replicated manual run enemy materialization",
        ),
        (world_snapshot_reconciliation_text, "authoritative_actor.player_created"),
        (world_snapshot_reconciliation_text, "BindReplicatedRunActor"),
        (world_snapshot_reconciliation_text, "RecordWorldSnapshotBinding"),
        (world_snapshot_reconciliation_text, "ApplyReplicatedRunEnemyHealth"),
        (world_snapshot_reconciliation_text, "kReplicatedRunEnemyDeathHpEpsilon"),
        (world_snapshot_reconciliation_text, "kReplicatedRunEnemyRemoteDeathHoldMs"),
        (world_snapshot_reconciliation_text, "g_replicated_run_pending_enemy_death_until_ms"),
        (world_snapshot_reconciliation_text, "IsAuthoritativeRunTrackedEnemyDeadSnapshot"),
        (world_snapshot_reconciliation_text, "TryBindAuthoritativeDeadRunEnemyToLocalPool"),
        (world_snapshot_reconciliation_text, "bound authoritative dead run enemy snapshot to local actor"),
        (world_snapshot_reconciliation_text, "IsReplicatedRunEnemyDeathPending"),
        (world_snapshot_reconciliation_text, "!IsAuthoritativeRunTrackedEnemyDeadSnapshot(authoritative_actor)"),
        (world_snapshot_reconciliation_text, "TryTriggerRunEnemyDeath(actor_address"),
        (world_snapshot_reconciliation_text, "triggered replicated run enemy death"),
        (world_snapshot_reconciliation_text, "kEnemyCurrentHpOffset"),
        (world_snapshot_reconciliation_text, "kEnemyMaxHpOffset"),
        (world_snapshot_reconciliation_text, "snapshot.scene_intent.kind == multiplayer::ParticipantSceneIntentKind::SharedHub"),
        (transport_text, "CopyPacketDisplayName"),
        (transport_text, "QueueParticipantEntitySync"),
        (transport_text, "participant_materialized"),
        (transport_text, "!participant_materialized"),
        (transport_text, "ParticipantControllerKind::Native"),
        (transport_text, "AppendParticipantTransformSample"),
        (transport_text, "AppendWorldSnapshot"),
        (transport_text, "state.loot_snapshot"),
        (transport_text, "TryGetPlayerState"),
        (transport_text, "local->runtime.life_current = player_state.hp"),
        (transport_text, "packet.owned_gold = local->owned_progression.gold"),
        (transport_text, "participant->owned_progression.gold = packet.owned_gold"),
        (transport_text, "packet.gold_revision >= participant->owned_progression.gold_revision"),
        (transport_text, "local->owned_progression.gold_revision += 1"),
        (transport_text, "RefreshOwnedProgressionBookFromSnapshot"),
        (transport_text, "RefreshOwnedAbilityLoadoutFromProfile"),
        (transport_text, "packet.progression_book_entry_count"),
        (transport_text, "participant->owned_progression.progression_book_entries"),
        (state_getters_text, "const bool structural_tail_record ="),
        (state_getters_text, "entry.statbook_max_level > 256"),
        (progression_probe_text, "compare_book_rows"),
        (progression_probe_text, "compare_float_fields"),
        (host_owned_level_up_sync_verifier_text, "snapshot_recovery"),
        (host_owned_level_up_sync_verifier_text, "wait_for_bidirectional_progression_parity"),
        (host_owned_level_up_sync_verifier_text, "target_self"),
        (progression_ledger_sync_verifier_text, "verify_bidirectional_gold_ledger"),
        (progression_ledger_sync_verifier_text, "wait_for_participant_gold"),
        (progression_ledger_sync_verifier_text, "sd.debug.write_i32(address"),
        (progression_ledger_sync_verifier_text, "gold_revision"),
        (gold_pickup_authority_verifier_text, "request_loot_pickup"),
        (gold_pickup_authority_verifier_text, "AlreadyGone"),
        (gold_pickup_authority_verifier_text, "duplicate_rejected_without_second_credit"),
        (orb_pickup_authority_verifier_text, "health_orb"),
        (orb_pickup_authority_verifier_text, "mana_orb"),
        (orb_pickup_authority_verifier_text, "resource_delta"),
        (orb_pickup_authority_verifier_text, "resource_kind"),
        (orb_pickup_authority_verifier_text, "duplicate_rejected_without_second_credit"),
        (lua_gameplay_text, "request_loot_pickup"),
        (lua_gameplay_text, "last_pickup_result"),
        (transport_text, "TryGetWorldState"),
        (transport_text, "packet->wave = local.runtime.wave"),
        (lua_input_text, "host-only while connected to a multiplayer session"),
        (lua_input_text, "QueueGameplayMouseLeftClick(&gameplay_click_error)"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_actor_lifecycle_hooks.inl"), "Blocked client run switch_region while connected to multiplayer"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_gameplay_thread_dispatch.inl"), "g_multiplayer_client_authorized_hub_run_switch_depth"),
        (service_loop_text, "InitializeLocalTransport()"),
        (service_loop_text, "TickSessionAndTransportOnAppThread"),
        (service_loop_text, "ShutdownLocalTransport()"),
        (lua_exec_pipe_text, "SDMOD_LUA_EXEC_PIPE_NAME"),
        (staged_game_launcher_text, "SDMOD_MULTIPLAYER_TRANSPORT"),
        (staged_game_launcher_text, "SDMOD_MULTIPLAYER_PARTICIPANT_ID"),
        (staged_game_launcher_text, "SDMOD_MULTIPLAYER_PLAYER_NAME"),
        (staged_game_launcher_text, "SDMOD_LUA_EXEC_PIPE_NAME"),
        (staged_game_launcher_text, "temporaryProfile"),
        (staged_game_launcher_text, "StageSandboxCompatibilityLinks.Materialize(stage.StageRootPath, options.SavegamesRootPath)"),
        (launcher_command_parser_text, "--temporary-profile"),
        (isolated_profile_bootstrapper_text, "temporary-client-profile"),
        (stage_sandbox_links_text, "savegamesTargetPath"),
        (project_text, "include\\multiplayer_local_transport.h"),
        (project_text, "src\\multiplayer_local_transport.cpp"),
        (project_filters_text, "include\\multiplayer_local_transport.h"),
        (project_filters_text, "src\\multiplayer_local_transport.cpp"),
        (bot_runtime_header_text, "bool ReadParticipantSnapshot"),
        (bot_snapshots_text, "ReadParticipantSnapshot"),
        (read_text(LUA_ENGINE_BOTS_BINDING), "LuaBotsGetParticipantState"),
        (read_text(LUA_ENGINE_BOTS_BINDING), "LuaBotsGetParticipants"),
        (read_text(LUA_ENGINE_BOTS_BINDING), "LuaBotsGetNameplate"),
        (entity_sync_text, "ReadParticipantSnapshot(request.bot_id"),
        (scene_binding_text, "ReadParticipantSnapshot(binding.bot_id"),
        (scene_binding_text, "RefreshNativeRemoteParticipantTransformTarget"),
        (scene_binding_text, "ApplyNativeRemoteParticipantPlayback"),
        (native_remote_playback_text, "ApplyNativeRemoteParticipantPlayback"),
        (native_remote_playback_text, "ApplyNativeRemoteParticipantVitalState"),
        (native_remote_playback_text, "ApplyNativeRemoteParticipantPresentationState"),
        (native_remote_playback_text, "replicated_presentation_valid"),
        (read_text(PLAYER_ACTOR_TICK_HOOK), "binding->ongoing_cast.active && !native_remote_binding"),
        (read_text(PLAYER_ACTOR_TICK_HOOK), "if (!playback.presentation_valid)"),
        (read_text(ACTOR_ANIMATION_ADVANCE_HOOK), "struct AnimationAdvanceContextScope"),
        (read_text(ACTOR_ANIMATION_ADVANCE_HOOK), "~AnimationAdvanceContextScope()"),
        (read_text(PLAYER_ACTOR_TICK_HOOK), "ApplyNativeRemoteParticipantPresentationState(binding, actor_address)"),
        (native_remote_playback_text, "participant->runtime.life_current"),
        (native_remote_playback_text, "kProgressionHpOffset"),
        (native_remote_playback_text, "kProgressionMpOffset"),
        (participant_snapshot_text, "if (multiplayer::IsNativeControlledParticipant(*participant))"),
        (participant_snapshot_text, "participant->runtime.life_current = snapshot.hp"),
        (native_remote_playback_text, "replicated_transform_playback_ms"),
        (native_remote_playback_text, "kRemoteTransformInterpolationDelayMs"),
        (native_remote_playback_text, "TrySampleParticipantTransform"),
        (native_remote_playback_text, "kRemoteSnapDistance"),
        (participant_collision_text, "left.local_player && right.native_remote"),
        (participant_collision_text, "right.local_player && left.native_remote"),
        (participant_collision_text, "cross-instance feedback loop"),
        (participant_collision_text, "if (native_player_pair)"),
        (networking_doc_text, "client-predicted / authority-verified"),
        (networking_doc_text, "SDMOD_MULTIPLAYER_TRANSPORT=local_udp"),
        (networking_doc_text, "SDMOD_MULTIPLAYER_PLAYER_NAME"),
        (networking_doc_text, "verify_local_multiplayer_sync.py"),
        (networking_doc_text, "verify_player_health_death_sync.py"),
        (networking_doc_text, "SDMOD_LUA_EXEC_PIPE_NAME"),
        (networking_doc_text, "player/player"),
        (networking_doc_text, "WorldSnapshot"),
        (networking_doc_text, "LootSnapshot"),
        (networking_doc_text, "sd.world.get_replicated_loot()"),
        (networking_doc_text, "Protocol v30"),
        (networking_doc_text, "Gold, health/mana orbs, item/potion carriers, and powerups have host-authorized request/result ownership"),
        (networking_doc_text, "run-world"),
        (networking_doc_text, "tracked enemies"),
        (networking_doc_text, "bootstrap client wave activation"),
        (networking_doc_text, "accelerates its native wave-spawner timers"),
        (networking_doc_text, "host lifecycle spawn serial"),
        (networking_doc_text, "live HP/max-HP"),
        (networking_doc_text, "run enemy presentation probe"),
        (networking_doc_text, "host-authoritative run entry"),
        (networking_doc_text, "host-authored run generation seed"),
        (networking_doc_text, "run-static prop families"),
        (networking_doc_text, "verify_run_static_layout_sync.py"),
        (networking_doc_text, "connected-client"),
        (networking_doc_text, "empty Run"),
        (networking_doc_text, "one-shot run-entry formation placement"),
        (networking_doc_text, "death-handled byte"),
        (networking_doc_text, "per-family allocation sizes"),
        (networking_doc_text, "Synced host-owned run drops"),
        (networking_doc_text, "sd.player.get_inventory_state()"),
        (networking_doc_text, "tools/verify_multiplayer_inventory_audit.py"),
        (networking_doc_text, "Accepted potions and exact recipe-backed items enter the owning client's stock native inventory"),
        (networking_doc_text, "Observer processes intentionally retain replicated inventory rows"),
        (networking_doc_text, "pickup-request / pickup-result"),
        (networking_doc_text, "bounded full participant-owned inventory item rows"),
        (networking_doc_text, "progression-book/statbook/skillbook/spellbook rows"),
        (networking_doc_text, "Gold, health/mana orbs, item/potion carriers, and powerups have host-authorized request/result ownership"),
        (world_sync_plan_text, "tools/probe_named_hub_npc_fields.py"),
        (world_sync_plan_text, "FUN_00502120"),
        (world_sync_plan_text, "larger player/Student render window"),
        (world_sync_plan_text, "tools/probe_run_enemy_presentation_sync.py"),
        (world_sync_plan_text, "drive word stays zero"),
        (world_sync_plan_text, "WorldActorPresentationFlagLocomotionFloats"),
        (world_sync_plan_text, "death-handled byte"),
        (world_sync_plan_text, "tools/verify_run_enemy_seed_viability.py"),
        (world_sync_plan_text, "stock run-enemy lockstep was rejected"),
        (world_sync_plan_text, "client's native wave spawner as a local"),
        (world_sync_plan_text, "host lifecycle spawn serial"),
        (world_sync_plan_text, "extra_unparked_client_tracked_enemies"),
        (world_sync_plan_text, "tools/probe_run_reward_sync.py"),
        (world_sync_plan_text, "host gold reward actors are visible as native type `0x7DC`"),
        (world_sync_plan_text, "sd.world.get_replicated_loot()"),
        (world_sync_plan_text, "host-confirmed pickup and participant-owned"),
        (named_hub_npc_probe_text, "NAMED_TYPES"),
        (named_hub_npc_probe_text, "FUN_00502450"),
        (named_hub_npc_probe_text, "moving_drive_types"),
        (named_hub_npc_probe_text, "max_drive_phase_distance"),
        (run_enemy_presentation_probe_text, "KILL_HOST_ENEMY_LUA"),
        (run_enemy_presentation_probe_text, "setup_live_run_pair"),
        (run_enemy_presentation_probe_text, "max_drive_byte_mismatches"),
        (run_enemy_presentation_probe_text, "max_snapshot_locomotion_present"),
        (run_enemy_presentation_probe_text, "max_locomotion_mismatches"),
        (run_enemy_presentation_probe_text, "max_snapshot_dead"),
        (run_reward_sync_probe_text, "GOLD_REWARD_TYPE_ID = 0x07DC"),
        (run_reward_sync_probe_text, "park_players_away_from_reward"),
        (run_reward_sync_probe_text, "STATIONARY_REWARD_MIN_PLAYER_DISTANCE"),
        (run_reward_sync_probe_text, "current_world_snapshot_excludes_gold_drops"),
        (run_reward_sync_probe_text, "client_receives_host_loot_metadata"),
        (run_reward_sync_probe_text, "client_materializes_host_loot_actor"),
        (run_reward_sync_probe_text, "loot_gold.count"),
        (run_reward_sync_probe_text, "wait_for_client_replicated_loot"),
        (run_reward_sync_probe_text, "pickup_authority_is_participant_owned"),
        (lua_gameplay_text, "LuaWorldGetReplicatedLoot"),
        (lua_gameplay_text, '"get_replicated_loot"'),
        (lua_runtime_text, "LuaRuntimeGetMultiplayerState"),
        (lua_runtime_text, '"get_multiplayer_state"'),
        (lua_runtime_text, "PushLevelUpOfferRuntimeInfo"),
        (lua_runtime_text, "PushLevelUpChoiceResultRuntimeInfo"),
        (lua_runtime_text, "PushLevelUpWaitStatusRuntimeInfo"),
        (lua_runtime_text, '"active_level_up_offer"'),
        (lua_runtime_text, '"last_level_up_choice_result"'),
        (lua_runtime_text, '"level_up_wait_status"'),
        (lua_runtime_text, "LuaRuntimeChooseLevelUpOption"),
        (lua_runtime_text, '"choose_level_up_option"'),
        (lua_runtime_text, "LuaRuntimeDebugPublishLevelUpOffer"),
        (lua_runtime_text, '"debug_publish_level_up_offer"'),
        (level_up_offer_sync_verifier_text, "debug_publish_level_up_offer"),
        (level_up_offer_sync_verifier_text, "choose_level_up_option"),
        (level_up_offer_sync_verifier_text, "client_progression_mode"),
        (level_up_offer_sync_verifier_text, "client_picker_screen"),
        (level_up_offer_sync_verifier_text, "verify_level_up_offer_sync"),
        (run_lifecycle_level_hooks_text, "suppress_client_local_level_up"),
        (run_lifecycle_level_hooks_text, "kProgressionNonLocalModeValue"),
        (run_lifecycle_level_hooks_text, "PublishHostLevelUpBarrierOffers"),
        (run_seed_verifier_text, "stock_run_enemy_lockstep_viable"),
        (run_seed_verifier_text, "global_seed_as_primary_sync_recommended"),
        (run_seed_verifier_text, "tracked_count_sequence_diverged"),
        (run_seed_verifier_text, "launch_isolated_pair"),
        (run_snapshot_verifier_text, "run_lifecycle_status"),
        (run_snapshot_verifier_text, "authoritative_actors_matched"),
        (run_snapshot_verifier_text, "host_only_snapshot_actors"),
        (run_snapshot_verifier_text, "extra_client_tracked_enemies"),
        (run_snapshot_verifier_text, "extra_unparked_client_tracked_enemies"),
        (run_snapshot_verifier_text, "parked_client_tracked_enemies"),
        (run_snapshot_verifier_text, "matched_binding_count"),
        (run_snapshot_verifier_text, "lifecycle_owned_snapshot_actors"),
        (run_snapshot_verifier_text, "--require-complete-lifecycle"),
        (participant_doc_text, "RemoteParticipant + Native"),
        (participant_doc_text, "native-remote playback"),
        (participant_doc_text, "push both actors"),
        (participant_doc_text, "sd.bots.get_participants()"),
        (participant_doc_text, "sd.bots.get_nameplate(actor_address)"),
        (participant_doc_text, "Participant-Owned Inventory And Books"),
        (participant_doc_text, "ParticipantOwnedProgressionState"),
        (participant_doc_text, "gold revision"),
        (participant_doc_text, "host-authorized gold, health/mana orbs, and"),
        (participant_doc_text, "configured host reports `in_run`"),
        (participant_doc_text, "sd.runtime.get_multiplayer_state()"),
        (participant_doc_text, "inventory root and equipment sinks"),
        (participant_doc_text, "spellbook unlock/upgrade state"),
        (participant_doc_text, "statbook allocation/upgrade state"),
        (participant_doc_text, "sd.player.get_inventory_state()"),
        (participant_doc_text, "sd.player.get_progression_book_state()"),
        (participant_doc_text, "read-only native inventory audit surface"),
        (participant_doc_text, "Observers retain the authoritative participant rows"),
        (participant_doc_text, "Local UDP protocol v30 mirrors bounded full participant-owned"),
        (inventory_item_doc_text, "tools/probe_run_reward_sync.py --attempts 3"),
        (inventory_item_doc_text, "sd.world.get_replicated_loot()"),
        (inventory_item_doc_text, "sd.player.get_inventory_state()"),
        (inventory_item_doc_text, "tools/verify_multiplayer_inventory_audit.py"),
        (inventory_item_doc_text, "item row count, item pointer array address"),
        (inventory_item_doc_text, "local UDP `StatePacket` protocol v30 introduced a bounded full participant-owned"),
        (inventory_item_doc_text, "participant-owned progression-book/statbook/skillbook/"),
        (inventory_item_doc_text, "participant-owned starter potion rows"),
        (inventory_item_doc_text, "by exact item type and recipe identity"),
        (inventory_item_doc_text, "not a valid\n\"available for pickup\" predicate"),
        (inventory_item_doc_text, "verify_multiplayer_orb_pickup_authority.py --attempts 3"),
        (inventory_item_doc_text, "`0x005E6B50` -> `ItemDropActor_TickPickup`"),
        (inventory_item_doc_text, "`sd.player.equip_inventory_item(recipe_uid)`"),
        (inventory_item_doc_text, "tools/verify_multiplayer_native_item_inventory_sync.py"),
        (inventory_item_doc_text, "host snapshots `drop + 0x148` held-item metadata"),
        (binary_layout_text, "item_drop_pickup=0x005E6B50"),
        (binary_layout_text, "native_global_rng_state=0x00818B08"),
        (binary_layout_text, "native_rng_initialize=0x00401120"),
        (binary_layout_text, "window_input_scale_x=0x00818678"),
        (binary_layout_text, "window_input_scale_y=0x0081867C"),
        (background_focus_text, "UpdateWindowInputScale"),
        (background_focus_text, "IsMouseInputMessage"),
        (background_focus_text, "FindCurrentProcessMainWindow"),
        (background_focus_text, "WM_WINDOWPOSCHANGED"),
        (background_focus_text, "Updated SolomonDark window input scale"),
        (background_focus_text, "kWindowInputScaleXGlobal"),
        (background_focus_text, "kWindowInputScaleYGlobal"),
        (gameplay_seams_header_text, "kWindowInputScaleXGlobal"),
        (gameplay_seams_header_text, "kWindowInputScaleYGlobal"),
        (gameplay_seams_header_text, "kNativeGlobalRngStateGlobal"),
        (gameplay_seams_header_text, "kNativeRngInitialize"),
        (gameplay_seams_bindings_text, '"window_input_scale_x", kWindowInputScaleXGlobal'),
        (gameplay_seams_bindings_text, '"window_input_scale_y", kWindowInputScaleYGlobal'),
        (gameplay_seams_bindings_text, '"native_global_rng_state", kNativeGlobalRngStateGlobal'),
        (gameplay_seams_bindings_text, '"native_rng_initialize", kNativeRngInitialize'),
        (gameplay_seams_header_text, "kItemDropPickupCaller"),
        (gameplay_seams_bindings_text, '"item_drop_pickup", kItemDropPickupCaller'),
        (script_text, "local-mp-host"),
        (script_text, "local-mp-client"),
        (script_text, "[string]$HostPreset"),
        (script_text, "[string]$ClientPreset"),
        (script_text, "$effectiveHostPreset"),
        (script_text, "$effectiveClientPreset"),
        (script_text, '$hostLaunchPreset = "create_manual"'),
        (script_text, '$clientLaunchPreset = "create_manual"'),
        (read_text(ROOT / "mods/lua_ui_sandbox_lab/scripts/lib/setup.lua"), 'active_preset == "create_manual"'),
        (script_text, "SDMOD_MULTIPLAYER_PLAYER_NAME"),
        (script_text, "SDMOD_LUA_EXEC_PIPE_NAME"),
        (script_text, "multiplayer.steam_bootstrap=false"),
        (script_text, "--temporary-profile"),
        (script_text, "[switch]$AllowFocusSteal"),
        (script_text, "$showNoActivate = 4"),
        (script_text, "if ($AllowFocusSteal) {"),
        (script_text, "Window click fallback requires -AllowFocusSteal"),
        (script_text, "allowFocusSteal = [bool]$AllowFocusSteal"),
        (verifier_text, "wait_for_remote"),
        (verifier_text, "nudge_player"),
        (verifier_text, "wait_for_remote_convergence"),
        (verifier_text, "wait_for_local_transform_settled"),
        (verifier_text, "heading_tolerance: float = 0.25"),
        (verifier_text, "observed-motion heading"),
        (verifier_text, 'emit(prefix .. "actor_heading", actor_heading(peer.actor_address))'),
        (verifier_text, "heading_distance(actor_heading, expected_heading)"),
        (verifier_text, "verify_native_remote_overlap_policy"),
        (verifier_text, "skip_local_native_remote_push_to_avoid_replication_feedback"),
        (verifier_text, "sd.bots.get_nameplate"),
        (verifier_text, "sd.hub.start_testrun"),
        (verifier_text, "assert_client_start_testrun_blocked"),
        (verifier_text, "start_host_testrun_and_wait_for_clients"),
        (verifier_text, "verify_run_entry_bootstrap"),
        (verifier_text, "client_replicated_scene_kind"),
        (verifier_text, "client_followed_host"),
        (run_snapshot_verifier_text, "start_host_testrun_and_wait_for_clients"),
        (run_static_layout_verifier_text, "start_host_testrun_and_wait_for_clients"),
        (run_static_layout_verifier_text, "circle_digest"),
        (run_static_layout_verifier_text, "circle_mask4_digest"),
        (run_static_layout_verifier_text, "circle_mask4_count"),
        (run_static_layout_verifier_text, "shape_digest"),
        (run_static_layout_verifier_text, "static_actor_digest"),
        (run_static_layout_verifier_text, "local_run_nonce"),
        (player_health_death_verifier_text, "DEAD_CORPSE_DRIVE_STATE"),
        (player_health_death_verifier_text, "set_local_player_vitals"),
        (player_health_death_verifier_text, "assert_dead_remote_ignores_transform"),
        (player_health_death_verifier_text, "assert_restored_remote_follows_transform"),
        (player_health_death_verifier_text, "launch_trio"),
        (player_health_death_verifier_text, "VITAL_SYNC_TOLERANCE = 0.25"),
        (player_health_death_verifier_text, "host_to_client"),
        (player_health_death_verifier_text, "host_to_third"),
        (player_health_death_verifier_text, "client_to_host"),
        (player_health_death_verifier_text, "client_to_third"),
        (player_health_death_verifier_text, "third_to_host"),
        (player_health_death_verifier_text, "third_to_client"),
        (player_health_death_verifier_text, '"observer_relationship_count": 6'),
        (run_enemy_presentation_probe_text, "start_host_testrun_and_wait_for_clients"),
        (run_reward_sync_probe_text, "start_host_testrun_and_wait_for_clients"),
        (transport_text, "std::fabs(local_actor.max_hp - authoritative_max_hp)"),
        (world_snapshot_reconciliation_text, "max_hp_synced"),
    )
    missing = [token for text, token in required_pairs if token not in text]
    if re.search(
        r"claimed_target_y,\s*true\)",
        world_snapshot_reconciliation_text,
    ) is None:
        missing.append("enemy damage claims preserve a validated target position")
    native_remote_vital_guard = participant_snapshot_text.find(
        "if (multiplayer::IsNativeControlledParticipant(*participant))"
    )
    gameplay_snapshot_vital_feedback = participant_snapshot_text.find(
        "participant->runtime.life_current = snapshot.hp"
    )
    if not (0 <= native_remote_vital_guard < gameplay_snapshot_vital_feedback):
        missing.append(
            "native remote participant snapshot guard before gameplay vitals write"
        )
    if "built.flags = active != 0 ? LootDropSnapshotFlagActive : 0" in transport_text:
        missing.append("gold loot availability must not use the +0x148 state byte")
    if "ExecuteHostLootDropDeactivationNow(" not in host_loot_drop_deactivation_text:
        missing.append("gameplay-thread loot deactivation helper")
    if "CallActorRequestRetirementSafe(" not in host_loot_drop_deactivation_text:
        missing.append("accepted loot must enter the stock deferred-retirement lifecycle")
    if "CallActorRequestRetirementSafe(" not in replicated_loot_reconciliation_text:
        missing.append("client loot must enter the stock deferred-retirement lifecycle")
    if "CallActorWorldUnregisterSafe(" in host_loot_drop_deactivation_text:
        missing.append("accepted loot must not unregister actors while stock readers retain them")
    if "CallActorWorldUnregisterSafe(" in replicated_loot_reconciliation_text:
        missing.append("client loot cleanup must not unregister actors while stock readers retain them")
    if "ParkReplicatedLootPresentationActor" in host_loot_drop_deactivation_text:
        missing.append("host loot deactivation must not park native drop actors")
    if "ParkReplicatedLootPresentationActor" in replicated_loot_reconciliation_text:
        missing.append("client loot cleanup must not park native drop actors")
    if "g_client_non_authoritative_loot_suppressed_actors" in replicated_loot_reconciliation_text:
        missing.append("client loot cleanup must not retain suppressed actor tombstones")
    if "RemoveReplicatedLootPresentationActor(binding, &exception_code)" not in replicated_loot_reconciliation_text:
        missing.append("unbound client loot cleanup must unregister native drop actors")
    if "kItemDropHeldItemOffset" in host_loot_drop_deactivation_text:
        missing.append("item/potion loot deactivation must not null the native held-item pointer")
    if "CallActorWorldUnregisterSafe(" in transport_text:
        missing.append("network service thread must not mutate native world containers")
    if missing:
        raise StaticReTestFailure(
            "local multiplayer transport wiring missing token(s): " + ", ".join(missing))

    # TryListSceneActors includes the 0xFA1 hub scene/runtime record alongside
    # actual factory actors. Treating every finite shared-hub record as an
    # actor lets reconciliation write actor offsets into that scene record and
    # leaves stock code executing through its map-config pointer. Keep capture,
    # local binding, packet consumption, and pool binding independently guarded
    # so a future broadening at any one boundary cannot reintroduce that crash.
    shared_hub_actor_guards = (
        (
            transport_text,
            "ShouldReplicateWorldActor",
            r"IsSharedHubFactoryActorType\s*\(\s*actor\.object_type_id\s*\)",
        ),
        (
            world_snapshot_reconciliation_text,
            "ShouldReconcileLocalWorldActor",
            r"IsReplicatedSharedHubFactoryActorType\s*\(\s*actor\.object_type_id\s*\)",
        ),
        (
            world_snapshot_reconciliation_text,
            "ShouldUseAuthoritativeWorldActorForScene",
            r"IsReplicatedSharedHubFactoryActorType\s*\(\s*actor\.native_type_id\s*\)",
        ),
        (
            world_snapshot_reconciliation_text,
            "TryBindAuthoritativeSharedHubActorToLocalPool",
            r"IsReplicatedSharedHubFactoryActorType\s*"
            r"\(\s*authoritative_actor\.native_type_id\s*\)",
        ),
    )
    for source_text, function_name, required_guard in shared_hub_actor_guards:
        function_match = re.search(
            rf"(?:bool|std::vector<[^>]+>)\s+{function_name}\s*"
            rf"\([^)]*\)\s*\{{(?P<body>.*?)\n\}}",
            source_text,
            re.DOTALL,
        )
        if function_match is None:
            raise StaticReTestFailure(
                f"shared-hub actor safety function missing: {function_name}"
            )
        if re.search(required_guard, function_match.group("body")) is None:
            raise StaticReTestFailure(
                f"{function_name} must restrict shared-hub records to native factory actor types"
            )
    scene_switch_cleanup = re.search(
        r"void\s+RemoveReplicatedCreatedSharedHubActorsForSceneSwitch\s*"
        r"\([^)]*\)\s*\{(?P<body>.*?)\n\}",
        world_snapshot_reconciliation_text,
        re.DOTALL,
    )
    if scene_switch_cleanup is None:
        raise StaticReTestFailure("scene-switch replicated hub actor cleanup function missing")
    scene_switch_cleanup_body = scene_switch_cleanup.group("body")
    forbidden_scene_switch_cleanup = [
        token for token in (
            "RemoveReplicatedSharedHubActor(",
            "CallActorWorldUnregisterSafe",
            "CallObjectDeleteSafe",
        )
        if token in scene_switch_cleanup_body
    ]
    if forbidden_scene_switch_cleanup:
        raise StaticReTestFailure(
            "scene-switch replicated hub cleanup must abandon bindings and let native teardown own actors: " +
            ", ".join(forbidden_scene_switch_cleanup))
    actor_lifecycle_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_actor_lifecycle_hooks.inl"
    )
    switch_region_hook = re.search(
        r"void\s+__fastcall\s+HookGameplaySwitchRegion\s*"
        r"\([^)]*\)\s*\{(?P<body>.*?)\n\}",
        actor_lifecycle_text,
        re.DOTALL,
    )
    if switch_region_hook is None:
        raise StaticReTestFailure("gameplay switch-region hook missing")
    switch_region_body = switch_region_hook.group("body")
    if "tracked_standalone_scene_churn_actor" not in actor_lifecycle_text:
        raise StaticReTestFailure(
            "world_unregister hook must reset tracked standalone wizard bindings after any scene-churn unregister")
    if "PrepareGameplaySceneSwitchOnGameThread(" not in switch_region_body:
        raise StaticReTestFailure(
            "scene switch must run the shared scene-switch preparation helper")
    if "KeepMaterializedWizardBotsForNativeSceneTeardown" in actor_lifecycle_text:
        raise StaticReTestFailure(
            "scene switch must not preserve materialized remote wizard bindings for native teardown")
    if "DematerializeAllMaterializedWizardBotsForSceneSwitch(source)" not in dispatch_thread_text:
        raise StaticReTestFailure(
            "shared scene-switch preparation must dematerialize materialized remote wizard bindings")
    if "puppet_manager_delete_puppet skipped object delete during scene churn" not in actor_lifecycle_text:
        raise StaticReTestFailure(
            "tracked standalone remote wizard scene teardown must skip the native object delete/free path")
    allow_focus_gate = script_text.find("if ($AllowFocusSteal) {")
    foreground_call = script_text.find(
        "[void][SolomonDarkWindowActivator]::SetForegroundWindow")
    if allow_focus_gate < 0 or foreground_call < allow_focus_gate:
        raise StaticReTestFailure(
            "local multiplayer pair launcher must keep SetForegroundWindow behind -AllowFocusSteal")
    fallback_guard = script_text.find("Window click fallback requires -AllowFocusSteal")
    activate_flag = script_text.find("--activate")
    if fallback_guard < 0 or activate_flag < fallback_guard:
        raise StaticReTestFailure(
            "local multiplayer pair launcher must guard activate-click fallback behind -AllowFocusSteal")
    gameplay_click_queue = lua_input_text.find("QueueGameplayMouseLeftClick(&gameplay_click_error)")
    window_foreground_fallback = lua_input_text.find("SetForegroundWindow(window)")
    if not (0 <= gameplay_click_queue < window_foreground_fallback):
        raise StaticReTestFailure(
            "Lua input clicks must try the no-focus gameplay queue before foreground window fallback")
    if "latest runtime snapshot" in networking_doc_text:
        raise StaticReTestFailure("networking docs still describe latest-packet playback instead of interpolation history")
    forbidden_networking_tokens = (
        "Non-gold inventory stays SP",
        "Gold-only drops",
        "Inventory replication beyond gold",
    )
    present_networking_regressions = [
        token for token in forbidden_networking_tokens if token in networking_doc_text
    ]
    if present_networking_regressions:
        raise StaticReTestFailure(
            "networking docs still describe loot as single-player/gold-only: " +
            ", ".join(present_networking_regressions))

    return "local UDP dev transport is wired through protocol, service loop, interpolated participant/world sync, docs, and launch script"


def test_world_snapshots_are_complete_mtu_sized_generations() -> str:
    protocol_text = read_text(MULTIPLAYER_PROTOCOL)
    transport_text = read_multiplayer_transport_source()
    fragmentation_text = read_text(WORLD_SNAPSHOT_FRAGMENTATION)
    reconciliation_text = read_text(WORLD_SNAPSHOT_RECONCILIATION)
    run_lifecycle_text = read_text(
        ROOT / "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks.inl"
    )

    required_tokens = (
        (protocol_text, "constexpr std::uint16_t kProtocolVersion = 64;"),
        (protocol_text, "constexpr std::uint32_t kWorldSnapshotActorsPerFragment = 4;"),
        (protocol_text, "constexpr std::uint32_t kWorldSnapshotMaxLogicalActors = 512;"),
        (protocol_text, "std::uint32_t snapshot_id;"),
        (protocol_text, "std::uint16_t fragment_index;"),
        (protocol_text, "std::uint16_t fragment_count;"),
        (protocol_text, "std::uint16_t actor_start_index;"),
        (protocol_text, "std::uint16_t actor_count;"),
        (protocol_text, "std::uint32_t actor_total_count;"),
        (
            protocol_text,
            "WorldActorSnapshotPacketState actors[kWorldSnapshotActorsPerFragment];",
        ),
        (protocol_text, "static_assert(sizeof(WorldSnapshotPacket) == 1264"),
        (fragmentation_text, "struct CompleteWorldSnapshotPacketState"),
        (fragmentation_text, "struct PendingWorldSnapshotAssembly"),
        (fragmentation_text, "struct PendingWorldSnapshotAssemblies"),
        (
            fragmentation_text,
            "constexpr std::size_t kPendingWorldSnapshotAssemblyLimit = 8;",
        ),
        (
            fragmentation_text,
            "constexpr std::uint64_t kPendingWorldSnapshotAssemblyMaxAgeMs = 500;",
        ),
        (fragmentation_text, "std::deque<PendingWorldSnapshotAssembly> assemblies;"),
        (fragmentation_text, "PrunePendingWorldSnapshotAssemblies("),
        (fragmentation_text, "bool TryAcceptWorldSnapshotFragment("),
        (
            fragmentation_text,
            "assembly->received_fragment_count == assembly->fragment_count",
        ),
        (transport_text, "BuildLocalWorldSnapshot("),
        (transport_text, "BuildWorldSnapshotFragmentPackets("),
        (transport_text, "for (const auto& packet : packets)"),
        (transport_text, "TryAcceptWorldSnapshotFragment("),
        (
            transport_text,
            "PublishWorldSnapshotRuntimeInfo(complete_snapshot, now_ms)",
        ),
        (
            transport_text,
            "kLocalTransportWorldSnapshotReliableCheckpointIntervalMs = 1000",
        ),
        (reconciliation_text, "kWorldSnapshotApplyStaleMs = 1200"),
        (transport_text, "last_world_snapshot_reliable_checkpoint_ms"),
        (transport_text, "const bool reliable_checkpoint ="),
        (transport_text, "SteamNetworkSendMode::ReliableNoNagle"),
        (transport_text, "Steam gameplay packet send rejected."),
        (transport_text, "steam_reliable_send_failures"),
    )
    missing = [token for text, token in required_tokens if token not in text]
    if missing:
        raise StaticReTestFailure(
            "complete fragmented world snapshot contract is incomplete: "
            + ", ".join(missing)
        )

    forbidden_tokens = (
        (protocol_text, "kWorldSnapshotMaxActors"),
        (protocol_text, "WorldSnapshotFlagTruncated"),
        (transport_text, "BuildLocalWorldSnapshotPacket"),
        (transport_text, "WorldSnapshotFlagTruncated"),
        (reconciliation_text, "snapshot.truncated"),
        (run_lifecycle_text, "snapshot.truncated"),
        (transport_text, "PendingWorldSnapshotAssembly pending_world_snapshot;"),
    )
    present = [token for text, token in forbidden_tokens if token in text]
    if present:
        raise StaticReTestFailure(
            "partial world snapshot fallback remains active: " + ", ".join(present)
        )

    actors_per_fragment_match = re.search(
        r"kWorldSnapshotActorsPerFragment\s*=\s*(\d+)", protocol_text
    )
    maximum_actor_match = re.search(
        r"kWorldSnapshotMaxLogicalActors\s*=\s*(\d+)", protocol_text
    )
    packet_size_match = re.search(
        r"sizeof\(WorldSnapshotPacket\)\s*==\s*(\d+)", protocol_text
    )
    if (
        not actors_per_fragment_match
        or not maximum_actor_match
        or not packet_size_match
    ):
        raise StaticReTestFailure(
            "world snapshot fragment constants are not statically measurable"
        )

    actors_per_fragment = int(actors_per_fragment_match.group(1))
    maximum_actors = int(maximum_actor_match.group(1))
    packet_size = int(packet_size_match.group(1))
    retail_wave_actor_count = 80
    if maximum_actors < retail_wave_actor_count:
        raise StaticReTestFailure(
            f"logical world snapshots cannot represent a retail {retail_wave_actor_count}-enemy wave"
        )
    if packet_size > 1280:
        raise StaticReTestFailure(
            f"world snapshot fragment is {packet_size} bytes instead of staying below 1280 bytes"
        )
    expected_fragments = math.ceil(
        retail_wave_actor_count / actors_per_fragment
    )
    if expected_fragments != 20:
        raise StaticReTestFailure(
            f"retail 80-enemy generation should be 20 fragments, got {expected_fragments}"
        )

    return (
        "world snapshots publish only complete generations across "
        f"{expected_fragments} MTU-sized fragments for an 80-enemy retail wave, "
        "retain bounded interleaved assemblies, and send reliable convergence checkpoints"
    )


def test_packet_send_mode_dispatch_is_type_safe() -> str:
    outgoing_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/multiplayer_local_transport/outgoing_packet_sync.inl"
    )
    required_tokens = (
        "SteamNetworkSendMode SteamSendModeForPacket(const CastPacket& packet)",
        "template <typename Packet>\nSteamNetworkSendMode SteamSendModeForPacket(const Packet& packet)",
        "case PacketKind::WorldSnapshot:\n        // Ordinary generations are disposable visual updates.",
        "return SteamNetworkSendMode::UnreliableNoDelay;",
        "SteamSendModeForPacket(packet));",
    )
    missing = [token for token in required_tokens if token not in outgoing_text]
    if missing:
        raise StaticReTestFailure(
            "typed Steam send-mode dispatch is incomplete: " + ", ".join(missing)
        )

    forbidden_tokens = (
        "SteamSendModeForPacket(const void*",
        "std::memcpy(&cast, packet, sizeof(cast))",
    )
    present = [token for token in forbidden_tokens if token in outgoing_text]
    if present:
        raise StaticReTestFailure(
            "raw packet send-mode inspection can read beyond the concrete packet: "
            + ", ".join(present)
        )

    world_case = outgoing_text.find("case PacketKind::WorldSnapshot:")
    no_delay = outgoing_text.find(
        "return SteamNetworkSendMode::UnreliableNoDelay;", world_case
    )
    switch_end = outgoing_text.find("default:", world_case)
    if not 0 <= world_case < no_delay < switch_end:
        raise StaticReTestFailure(
            "ordinary fragmented world generations must be disposable NoDelay updates"
        )

    return "Steam send-mode selection is type-safe, keeps ordinary world generations disposable, and uses bounded reliable convergence checkpoints"


def test_steam_pair_driver_rejects_ended_runs_before_client_navigation() -> str:
    query_text = read_text(ROOT / "tools/verify_local_multiplayer_sync.py")
    driver_text = read_text(ROOT / "tools/drive_steam_friend_active_pair.py")

    required_query_tokens = (
        "if participant.is_owner then",
        'emit("local.in_run", local_participant and local_participant.in_run or false)',
    )
    missing_query = [
        token for token in required_query_tokens if token not in query_text
    ]
    if missing_query:
        raise StaticReTestFailure(
            "Steam pair query does not expose authoritative local run ownership: "
            + ", ".join(missing_query)
        )

    required_driver_tokens = (
        'parser.add_argument("--test-godmode", action="store_true")',
        'parser.add_argument("--test-manual-enemy-mode", action="store_true")',
        "sd.events.on('runtime.tick', sustain)",
        "if not local_participant_in_run() then",
        "sd.gameplay.get_manual_enemy_spawner_state()",
        "if state and state.manual_mode then",
        "sd.gameplay.set_manual_enemy_spawner_test_mode(true)",
        'host_view_before_client.get("local.in_run") != "true"',
        "host is still presenting an ended run; refusing to start a competing client scene load",
        'host_view.get("local.in_run") == "true"',
    )
    missing_driver = [
        token for token in required_driver_tokens if token not in driver_text
    ]
    if missing_driver:
        raise StaticReTestFailure(
            "Steam pair ended-run safety is incomplete: "
            + ", ".join(missing_driver)
        )

    host_query = driver_text.find("host_view_before_client = local_sync.query(HOST_ENDPOINT)")
    ended_run_guard = driver_text.find(
        'host_view_before_client.get("local.in_run") != "true"', host_query
    )
    client_navigation = driver_text.find(
        'output["client"] = drive_one_to_hub(', ended_run_guard
    )
    arm_host = driver_text.find(
        '"host": arm_test_godmode(pair, HOST_ENDPOINT)', client_navigation
    )
    arm_client = driver_text.find(
        '"client": arm_test_godmode(pair, CLIENT_ENDPOINT)', arm_host
    )
    arm_manual_host = driver_text.find(
        '"host": arm_test_manual_enemy_mode(pair, HOST_ENDPOINT)', arm_client
    )
    arm_manual_client = driver_text.find(
        '"client": arm_test_manual_enemy_mode(pair, CLIENT_ENDPOINT)',
        arm_manual_host,
    )
    run_start = driver_text.find("if args.start_run:", arm_manual_client)
    if not (
        0 <= host_query < ended_run_guard < client_navigation
        < arm_host < arm_client < arm_manual_host < arm_manual_client < run_start
    ):
        raise StaticReTestFailure(
            "Steam pair driver must reject an ended host run before client navigation "
            "and arm both test-safety callbacks on both peers before run start"
        )

    return "Steam pair onboarding refuses stale ended runs before client navigation and arms semantic test safety before run start"


def test_manual_enemy_test_mode_logging_is_transition_only() -> str:
    lifecycle_text = read_text(
        ROOT / "SolomonDarkModLoader/src/run_lifecycle/public_api_and_install.inl"
    )
    setter_start = lifecycle_text.find(
        "void SetRunLifecycleManualEnemySpawnerTestMode(bool enabled)"
    )
    setter_end = lifecycle_text.find(
        "bool IsRunLifecycleManualEnemySpawnerTestModeEnabled()", setter_start
    )
    body = lifecycle_text[setter_start:setter_end]
    required = (
        "manual_enemy_spawner_test_mode.exchange(",
        "if (previous == enabled)",
        "return;",
        'Log(\n        "manual run enemy spawn: stock-spawner test mode "',
    )
    missing = [token for token in required if token not in body]
    if setter_start == -1 or setter_end == -1 or missing:
        raise StaticReTestFailure(
            "manual enemy test-mode setter must log only actual state transitions: "
            + ", ".join(missing)
        )
    if not (
        body.find("manual_enemy_spawner_test_mode.exchange(")
        < body.find("if (previous == enabled)")
        < body.find("return;")
        < body.find("Log(")
    ):
        raise StaticReTestFailure(
            "manual enemy test-mode transition guard must precede logging"
        )
    return "manual enemy test mode is idempotent and logs only real state transitions"


def test_steam_friend_multiplayer_contract_is_wired() -> str:
    protocol_text = read_text(
        ROOT / "SolomonDarkModLoader/include/multiplayer_runtime_protocol.h"
    )
    bootstrap_api_text = read_text(
        ROOT / "SolomonDarkModLoader/src/steam_bootstrap_api.cpp"
    )
    bootstrap_text = read_text(
        ROOT / "SolomonDarkModLoader/src/steam_bootstrap.cpp"
    )
    steam_abi_text = read_text(
        ROOT / "SolomonDarkModLoader/include/steamworks_abi.h"
    )
    steam_bridge_text = read_text(
        ROOT / "SolomonDarkModLoader/src/steam_api_bridge.cpp"
    )
    session_root = ROOT / "SolomonDarkModLoader/src/multiplayer_steam_session"
    session_text = "\n".join(
        [
            read_text(
                ROOT / "SolomonDarkModLoader/src/multiplayer_steam_session.cpp"
            ),
            *(read_text(path) for path in sorted(session_root.glob("*.inl"))),
        ]
    )
    gameplay_transport_text = read_multiplayer_transport_source()
    launch_environment_text = read_text(
        ROOT / "SolomonDarkModLauncher/src/Launch/MultiplayerLaunchEnvironment.cs"
    )
    launch_options_text = read_text(
        ROOT / "SolomonDarkModLauncher/src/Launch/MultiplayerLaunchOptions.cs"
    )
    command_parser_text = read_text(
        ROOT / "SolomonDarkModLauncher/src/Commands/LauncherCommandParser.cs"
    )
    launch_executor_text = read_text(
        ROOT / "SolomonDarkModLauncher/src/App/LauncherCommandExecutor.cs"
    )
    steam_materializer_text = read_text(
        ROOT / "SolomonDarkModLauncher/src/Steam/SteamBootstrapMaterializer.cs"
    )
    compatibility_materializer_text = read_text(
        ROOT / "SolomonDarkModLauncher/src/Staging/MultiplayerCompatibilityMaterializer.cs"
    )
    startup_status_text = read_text(
        ROOT / "SolomonDarkModLoader/src/startup_status.cpp"
    )
    session_monitor_text = read_text(
        ROOT / "SolomonDarkModLauncher/src/Launch/MultiplayerSessionStatusMonitor.cs"
    )
    launcher_json_text = read_text(
        ROOT / "SolomonDarkModLauncher/src/App/LauncherJsonConsole.cs"
    )
    launcher_output_text = read_text(
        ROOT / "SolomonDarkModLauncher/src/App/LauncherOutputFormatter.cs"
    )
    ui_response_text = read_text(
        ROOT / "SolomonDarkModLauncher.UI/src/Infrastructure/LauncherCliResponse.cs"
    )
    ui_view_model_text = read_text(
        ROOT / "SolomonDarkModLauncher.UI/src/ViewModels/MainWindowViewModel.cs"
    )
    ui_command_client_text = read_text(
        ROOT / "SolomonDarkModLauncher.UI/src/Infrastructure/LauncherUiCommandClient.cs"
    )
    ui_response_reader_text = read_text(
        ROOT / "SolomonDarkModLauncher.UI/src/Infrastructure/LauncherJsonResponseReader.cs"
    )
    ui_session_status_reader_text = read_text(
        ROOT / "SolomonDarkModLauncher.UI/src/Infrastructure/"
        "LauncherMultiplayerSessionStatusReader.cs"
    )
    ui_xaml_text = read_text(
        ROOT / "SolomonDarkModLauncher.UI/src/Views/MainWindow.xaml"
    )
    wsl_steam_client_text = read_text(
        ROOT / "scripts/Launch-WslSteamMultiplayerClient.sh"
    )
    wsl_lua_client_text = read_text(
        ROOT / "scripts/Invoke-WslLuaExec.sh"
    )
    win32_lua_client_text = read_text(
        ROOT / "tools/win32_lua_exec_client.cpp"
    )

    required_pairs = (
        (protocol_text, "constexpr std::uint16_t kProtocolVersion = 64;"),
        (compatibility_materializer_text, "CurrentProtocolVersion = 64;"),
        (protocol_text, "SessionCapabilityHostAuthority"),
        (protocol_text, "struct SessionHelloPacket"),
        (protocol_text, "struct SessionHelloAckPacket"),
        (protocol_text, "struct SessionGoodbyePacket"),
        (protocol_text, "SessionKeepalive = 18"),
        (protocol_text, "struct SessionKeepalivePacket"),
        (steam_abi_text, "struct LobbyCreatedSmall"),
        (steam_abi_text, "struct LobbyEnterSmall"),
        (steam_abi_text, "small-pack LobbyEnter_t ABI changed"),
        (bootstrap_text, "DecodeLobbyCreatedPayload"),
        (bootstrap_text, "DecodeLobbyEnterPayload"),
        (bootstrap_api_text, '"SteamAPI_ManualDispatch_RunFrame"'),
        (bootstrap_api_text, '"SteamAPI_SteamNetworkingMessages_SteamAPI_v002"'),
        (bootstrap_api_text, '"SteamAPI_ISteamNetworkingMessages_SendMessageToUser"'),
        (bootstrap_api_text, '"SteamAPI_ISteamNetworkingMessages_ReceiveMessagesOnChannel"'),
        (bootstrap_api_text, '"SteamAPI_ISteamMatchmaking_InviteUserToLobby"'),
        (steam_bridge_text, "steamabi::kLobbyTypeFriendsOnly"),
        (steam_bridge_text, "SteamInviteUserToLobby"),
        (session_text, "SteamCreateLobby("),
        (session_text, "g_session.lobby_visibility"),
        (session_text, 'LobbyPrivacyToken(g_session.lobby_visibility)'),
        (session_text, "SteamInviteUserToLobby(lobby_id, g_session.invite_steam_id)"),
        (session_text, "g_session.phase == SteamSessionPhase::Error &&"),
        (session_text, "g_session.lobby_id == 0"),
        (session_text, 'SteamSetRichPresence("connect", connect.c_str())'),
        (session_text, "TryParseLobbyIdFromConnectString"),
        (session_text, "IsLobbyMember(message.sender_steam_id)"),
        (session_text, "packet.session_nonce == 0"),
        (session_text, "kRequiredSessionCapabilities"),
        (session_text, "RegisterSteamGameplayPeer(message.sender_steam_id, false)"),
        (session_text, "SendGoodbyeToAuthenticatedPeers"),
        (session_text, "kAuthenticatedPeerTimeoutMs"),
        (session_text, "kKeepaliveIntervalMs"),
        (session_text, "HandleSessionKeepalive"),
        (session_text, "SendSessionKeepalives(now_ms)"),
        (session_text, "packet.session_nonce != peer_it->second.session_nonce"),
        (session_text, "ExpireInactivePeers(now_ms)"),
        (session_text, "RestartClientHostHandshake"),
        (gameplay_transport_text, "IsAuthorizedSteamGameplayPacket"),
        (gameplay_transport_text, "packet.owner_participant_id;"),
        (gameplay_transport_text, "configured_remote.steam_id == sender_steam_id"),
        (launch_environment_text, 'environment[TransportVariable] = "steam";'),
        (launch_environment_text, 'InviteSteamIdVariable = "SDMOD_STEAM_INVITE_STEAM_ID"'),
        (launch_options_text, "InviteSteamId"),
        (command_parser_text, 'arg == "--invite-steam-id"'),
        (launch_executor_text, "SteamBootstrapConfiguration.SpacewarDevelopmentAppId"),
        (steam_materializer_text, "reader.PEHeaders.CoffHeader.Machine == Machine.I386"),
        (startup_status_text, 'L"multiplayer-session-status.json"'),
        (startup_status_text, '"  \\"inviteSent\\": "'),
        (session_text, "WriteMultiplayerSessionStatus("),
        (session_text, "g_session.overlay_enabled = SteamIsOverlayEnabled()"),
        (session_monitor_text, "WaitForHostReady("),
        (session_monitor_text, "WaitForConnectedJoin("),
        (session_monitor_text, "expectedLaunchToken"),
        (launcher_json_text, "MultiplayerSession ="),
        (launcher_json_text, "LaunchToken = session.LaunchToken"),
        (launcher_output_text, "Steam lobby id:"),
        (ui_response_text, "LauncherCliMultiplayerSession"),
        (ui_response_text, "public string LaunchToken"),
        (ui_view_model_text, "LobbyId = multiplayer.LobbyId.ToString();"),
        (ui_view_model_text, "StartSteamSessionMonitoring("),
        (ui_view_model_text, 'status.Phase == "Connected"'),
        (ui_view_model_text, "DescribeLobbyConnection(status)"),
        (ui_view_model_text, 'connection += $" · {status.RoutePingMs} ms"'),
        (ui_session_status_reader_text, "FileShare.ReadWrite | FileShare.Delete"),
        (ui_session_status_reader_text, "expectedLaunchToken"),
        (ui_xaml_text, 'Text="{Binding LobbyConnectionDetailsText}"'),
        (ui_command_client_text, "LauncherJsonResponseReader.ReadAsync("),
        (ui_response_reader_text, "ReadLineAsync(cancellationToken)"),
        (ui_response_reader_text, 'TryGetProperty("success"'),
        (wsl_steam_client_text, "--self-contained true"),
        (wsl_steam_client_text, "STEAM_COMPAT_DATA_PATH"),
        (wsl_steam_client_text, "SteamAppId=480"),
        (wsl_steam_client_text, "SteamGameId=480"),
        (wsl_steam_client_text, "--multiplayer join"),
        (wsl_steam_client_text, "--steam-api-dll"),
        (wsl_lua_client_text, "win32_lua_exec_client.exe"),
        (wsl_lua_client_text, 'export WINEPREFIX="$compat_data/pfx"'),
        (win32_lua_client_text, "PIPE_READMODE_MESSAGE"),
        (win32_lua_client_text, "GENERIC_READ | GENERIC_WRITE"),
        (win32_lua_client_text, "constexpr DWORD kPipeTimeoutMs = 20000;"),
    )
    missing = [token for text, token in required_pairs if token not in text]
    if missing:
        raise StaticReTestFailure(
            "Steam friend multiplayer contract is missing token(s): " +
            ", ".join(missing)
        )

    if "ReadToEndAsync" in ui_command_client_text:
        raise StaticReTestFailure(
            "WPF launcher still waits for inherited game pipe EOF instead of the CLI JSON response"
        )
    for removed_status in (
        "Steam invites ready",
        "HasSteamActivity",
        "IsSteamFriendConnected",
        "SteamConnectionText",
    ):
        if removed_status in ui_view_model_text or removed_status in ui_xaml_text:
            raise StaticReTestFailure(
                "WPF launcher retains the global Steam status: " + removed_status
            )
    return (
        "Steam friends-only lobby, authenticated v64 handshake, idle keepalive, owner-checked gameplay "
        "routing, Spacewar launch, x86 runtime staging, and a live launch-token-bound "
        "lobby connection panel are wired"
    )


def test_steam_friend_hub_lifecycle_soak_is_wired() -> str:
    runtime_state_text = read_multiplayer_runtime_state_source()
    reconciliation_text = read_text(WORLD_SNAPSHOT_RECONCILIATION)
    lua_gameplay_text = read_text(
        ROOT / "SolomonDarkModLoader/src/lua_engine_bindings_gameplay.cpp"
    )
    presentation_probe_text = read_text(
        ROOT / "tools/probe_hub_npc_presentation_sync.py"
    )
    soak_text = read_text(
        ROOT / "tools/verify_steam_friend_hub_soak.py"
    )

    required_pairs = (
        (runtime_state_text, "std::uint32_t removed_actor_total_count = 0;"),
        (
            runtime_state_text,
            "std::uint32_t failed_remove_actor_total_count = 0;",
        ),
        (
            reconciliation_text,
            "state.world_snapshot_apply.removed_actor_total_count +=",
        ),
        (
            reconciliation_text,
            "state.world_snapshot_apply.failed_remove_actor_total_count +=",
        ),
        (lua_gameplay_text, '"removed_actor_total_count"'),
        (lua_gameplay_text, '"failed_remove_actor_total_count"'),
        (lua_gameplay_text, '"apply_sequence"'),
        (lua_gameplay_text, '"apply_scene_epoch"'),
        (lua_gameplay_text, '"apply_presentation_sequence"'),
        (lua_gameplay_text, '"apply_presentation_scene_epoch"'),
        (lua_gameplay_text, '"apply_presentation_received_ms"'),
        (lua_gameplay_text, '"apply_presentation_available"'),
        (lua_gameplay_text, '"apply_presentation_actors"'),
        (
            reconciliation_text,
            "state.world_snapshot_apply.presentation_sequence = presentation_snapshot.sequence;",
        ),
        (
            presentation_probe_text,
            '"replicated.failed_remove_actor_total_count"',
        ),
        (
            presentation_probe_text,
            'client["replicated_applied_ms"]\n        - client["replicated_apply_presentation_received_ms"]',
        ),
        (presentation_probe_text, '"appactor"'),
        (presentation_probe_text, '"client_apply_presentation_available"'),
        (soak_text, '"same_machine": PAIR_BACKEND == "wsl"'),
        (soak_text, "def convergence_errors("),
        (soak_text, "ThreadPoolExecutor(max_workers=2)"),
        (soak_text, "host_future = executor.submit("),
        (soak_text, "client_future = executor.submit("),
        (soak_text, '"authoritative hub actor IDs are not unique"'),
        (soak_text, '"retired hub IDs remain bound"'),
        (soak_text, '"a persistent named hub NPC remains unbound"'),
        (soak_text, '"applied hub presentation source is unavailable"'),
        (soak_text, "failed_remove_totals[-1] != failed_remove_totals[0]"),
        (soak_text, "created_totals[-1] != created_totals[0]"),
        (soak_text, "removed_totals[-1] != removed_totals[0]"),
        (soak_text, "if lifecycle_change_count == 0:"),
        (soak_text, '"final_pair_responsive": True'),
        (soak_text, '"student_book_palette_mismatches"'),
        (soak_text, '"named_drive_phase_out_of_tolerance"'),
    )
    missing = [
        token
        for text, token in required_pairs
        if token not in text
    ]
    if missing:
        raise StaticReTestFailure(
            "same-machine Steam hub lifecycle soak is incomplete: "
            + ", ".join(missing)
        )

    forbidden_tokens = (
        "stable slot identity",
        "allow_failed_remove",
        "ignore_extra_actor",
        "sample_delta_ms = (",
        "sample_time_adjusted_host_drive",
    )
    present = [
        token
        for token in forbidden_tokens
        if token in soak_text or token in presentation_probe_text
    ]
    if present:
        raise StaticReTestFailure(
            "hub soak contains a slot-identity, divergence, or cross-process-clock escape path: "
            + ", ".join(present)
        )

    for forbidden in (
        'if PAIR_BACKEND != "wsl":',
        "hub soak requires the same-machine Windows plus WSL Steam pair",
    ):
        if forbidden in soak_text:
            raise StaticReTestFailure(
                "hub soak still rejects a genuine remote Windows Steam pair: "
                + forbidden
            )

    if re.search(
        r'client\["replicated_sampled_ms"\]\s*-\s*host\["replicated_sampled_ms"\]',
        presentation_probe_text,
    ):
        raise StaticReTestFailure(
            "hub presentation verification subtracts process-local Windows and Proton clocks"
        )

    return (
        "Steam hub soak supports both physical-Windows and same-machine test "
        "topologies while requiring one-to-one named NPC convergence, local-stock "
        "Student presentation sync, and zero multiplayer hub lifecycle mutation"
    )


def test_player_state_exports_native_heading_for_bot_spawn() -> str:
    header_text = read_text(ROOT / "SolomonDarkModLoader/include/mod_loader.h")
    state_getters_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_state_getters.inl"
    )
    lua_binding_text = read_text(ROOT / "SolomonDarkModLoader/src/lua_engine_bindings_gameplay.cpp")
    lua_scene_text = read_text(ROOT / "mods/lua_bots/scripts/lib/lua_bots/scene.lua")
    lua_follow_text = read_text(ROOT / "mods/lua_bots/scripts/lib/lua_bots/follow.lua")

    required_tokens = {
        "player state struct": (header_text, "float heading = 0.0f;"),
        "native heading read": (
            state_getters_text,
            "TryReadFiniteFloatField(actor_address, kActorHeadingOffset, &heading)",
        ),
        "player heading assignment": (state_getters_text, "state->heading = heading;"),
        "Lua player heading publish": (lua_binding_text, "player_state.heading"),
        "Lua player heading field": (lua_binding_text, '"heading"'),
        "Lua bot spawn requires heading": (lua_scene_text, "local heading = tonumber(player.heading)"),
        "Lua bot request top-level heading": (lua_scene_text, "heading = spawn.heading,\n        position = {"),
        "Lua follow request top-level heading": (lua_follow_text, "update.heading = tonumber(bot.heading)"),
    }
    missing = [
        label
        for label, (text, token) in required_tokens.items()
        if token not in text
    ]
    if missing:
        raise StaticReTestFailure("player heading live-state coverage missing: " + ", ".join(missing))

    if "local heading = tonumber(player.heading) or" in lua_scene_text:
        raise StaticReTestFailure("Lua bot spawn heading reintroduced a default instead of requiring live player heading")
    if re.search(r"position\s*=\s*\{[^}]*\bheading\b", lua_scene_text, re.S):
        raise StaticReTestFailure("Lua bot spawn/update nested heading inside position instead of using request heading")
    if "update.position.heading" in lua_follow_text:
        raise StaticReTestFailure("Lua follow nested heading inside position instead of using request heading")

    return "bot spawn heading comes from live actor state and is sent through the native request heading field"


def test_investigation_register_has_static_coverage() -> str:
    plan_text = read_text(NATIVE_SEAM_PLAN)
    register_areas: list[str] = []
    for raw_line in plan_text.splitlines():
        line = raw_line.strip()
        if not line.startswith("|") or line.startswith("| ---") or line.startswith("| Area "):
            continue
        parts = [part.strip() for part in line.strip("|").split("|")]
        if len(parts) >= 4:
            register_areas.append(parts[0])

    missing_coverage = [
        area for area in register_areas
        if area not in INVESTIGATION_REGISTER_COVERAGE
    ]
    stale_coverage = [
        area for area in INVESTIGATION_REGISTER_COVERAGE
        if area not in register_areas
    ]
    missing_refs: list[str] = []
    test_names = {name for name, _ in TESTS}
    for area, refs in INVESTIGATION_REGISTER_COVERAGE.items():
        for ref in refs:
            kind, _, name = ref.partition(":")
            if kind == "smell":
                if name not in SMELL_SOURCES:
                    missing_refs.append(f"{area}: unknown smell source {name}")
            elif kind == "test":
                if name not in test_names:
                    missing_refs.append(f"{area}: unknown test {name}")
            else:
                missing_refs.append(f"{area}: malformed coverage ref {ref}")

    failures = []
    if missing_coverage:
        failures.append("missing coverage for register area(s): " + ", ".join(missing_coverage))
    if stale_coverage:
        failures.append("stale coverage for removed area(s): " + ", ".join(stale_coverage))
    if missing_refs:
        failures.append("; ".join(missing_refs))
    if failures:
        raise StaticReTestFailure("; ".join(failures))
    return f"{len(register_areas)} investigation-register rows have static coverage"


def test_staged_binary_matches_analysis_binary() -> str:
    if not STAGED_BINARY.exists():
        raise StaticReTestFailure(f"missing staged binary: {STAGED_BINARY.relative_to(ROOT)}")
    if not ABANDONWARE_BINARY.exists():
        raise StaticReTestFailure(f"missing source binary: {ABANDONWARE_BINARY}")
    staged_hash = sha256(STAGED_BINARY)
    source_hash = sha256(ABANDONWARE_BINARY)
    if staged_hash != source_hash:
        raise StaticReTestFailure(f"binary hash mismatch staged={staged_hash} source={source_hash}")
    return f"staged binary matches source binary sha256={staged_hash}"


def test_binary_layout_matches_staged_layout_identity() -> str:
    root_layout = read_text(BINARY_LAYOUT)
    staged_layout = read_text(STAGED_BINARY_LAYOUT)
    required = ("version=SolomonDarkBeta_0.72.5", "image_base=0x00400000")
    for token in required:
        if token not in root_layout:
            raise StaticReTestFailure(f"root binary layout missing {token}")
        if token not in staged_layout:
            raise StaticReTestFailure(f"staged binary layout missing {token}")
    return "root and staged binary layouts declare the expected game version/image base"


def test_residual_probe_and_skill_choice_offsets_are_layout_backed() -> str:
    layout_text = read_text(BINARY_LAYOUT)
    skill_choices_text = read_bot_skill_choice_source()
    moving_probe_text = read_text(ROOT / "tools/probe_bot_moving_attack_damage.py")
    shared_probe_text = read_text(ROOT / "tools/probe_shared_hub_actor_contract.py")

    required_layout_tokens = (
        "actor_grid_cell_ptr=0x54",
        "progression_previous_xp_threshold=0x38",
        "progression_next_xp_threshold=0x3C",
        "progression_special_choice_argument=0x844",
        "native_skill_option_roll_vtable=0x74",
        "native_special_choice_post_refresh_vtable=0x94",
        "native_special_choice_activate_vtable=0x9C",
    )
    missing_layout = [token for token in required_layout_tokens if token not in layout_text]
    if missing_layout:
        raise StaticReTestFailure(
            "residual cleanup layout is missing token(s): " +
            ", ".join(missing_layout))

    required_code_tokens = (
        (skill_choices_text, "skill_choices", "kProgressionPreviousXpThresholdOffset"),
        (skill_choices_text, "skill_choices", "kNativeSkillOptionRollVtableOffset"),
        (moving_probe_text, "moving_attack_probe", "read_runtime_layout_offset(\"actor_position_x\")"),
        (moving_probe_text, "moving_attack_probe", "read_runtime_layout_offset(\"actor_heading\")"),
        (shared_probe_text, "shared_hub_probe", "read_runtime_layout_offset(\"actor_grid_cell_ptr\")"),
        (shared_probe_text, "shared_hub_probe", "read_runtime_layout_offset(\"gamenpc_goal_x\")"),
        (shared_probe_text, "shared_hub_probe", "movement_controller_primary_list"),
    )
    missing_code = [
        f"{label}:{token}" for text, label, token in required_code_tokens if token not in text
    ]
    if missing_code:
        raise StaticReTestFailure(
            "residual cleanup code is not layout-backed: " +
            ", ".join(missing_code))

    forbidden_patterns = (
        (skill_choices_text, "skill_choices", r"constexpr std::size_t k(?:Progression|Native)[A-Za-z0-9]+Offset\s*=\s*0x"),
        (moving_probe_text, "moving_attack_probe", r"actor \+ 0x(?:18|1C|6C)"),
        (shared_probe_text, "shared_hub_probe", r"actor \+ 0x(?:54|58|174|178|17C|194|1C0|264)"),
        (shared_probe_text, "shared_hub_probe", r"read_[uf][0-9]+\(actor_addr,\s*0x(?:30|38|3C|54|58|5C|174|178|17C|180|181|188|18C|194|198|19C|1A0|1B4|1C0|1C2|1C3|1C4|264)"),
        (shared_probe_text, "shared_hub_probe", r"world \+ 0x378|movement_ctx,\s*0x(?:40|4C|70|7C)|ctx \+ 0x(?:40|4C|70|7C)"),
    )
    present_forbidden = [
        label for text, label, pattern in forbidden_patterns if re.search(pattern, text, re.I)
    ]
    if present_forbidden:
        raise StaticReTestFailure(
            "raw residual offsets remain in: " +
            ", ".join(present_forbidden))

    return "residual probe and skill-choice offsets are layout-backed"


def test_second_residual_runtime_and_trace_addresses_are_layout_backed() -> str:
    layout_text = read_text(BINARY_LAYOUT)
    standalone_render_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/standalone_materialization_actor_render_state.inl"
    )
    clone_source_text = read_text(STANDALONE_CLONE_SOURCE)
    crash_summary_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/crash_summary_builders.inl"
    )
    crash_logger_text = read_text(ROOT / "SolomonDarkModLoader/src/logger_crash_reporting.cpp")
    native_active_object_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/native_active_spell_object_state.inl"
    )
    standalone_tracking_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_standalone_wizard_tracking.inl"
    )
    public_state_getters_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_state_getters.inl"
    )
    actor_world_calls_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_actor_calls/actor_world_and_visual_calls.inl"
    )
    actor_lifecycle_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_actor_lifecycle_hooks.inl"
    )
    standalone_destruction_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/standalone_materialization_slot_bot_destruction.inl"
    )
    player_cast_hooks_text = read_player_cast_hooks_source()
    boulder_projection_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/boulder_damage_projection.inl"
    )
    selection_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/skill_selection_rules.inl"
    )
    standalone_spawn_text = read_text(SPAWN_STANDALONE_WIZARD)
    cast_trace_text = read_text(ROOT / "tools/cast_trace_profiles.py")
    player_watch_text = read_text(ROOT / "tools/watch_player_cast_dispatch.py")
    element_damage_text = read_text(ROOT / "tools/probe_bot_element_damage.py")
    startup_trace_text = read_text(ROOT / "tools/trace_rich_item_startup.py")

    required_layout_tokens = (
        "actor_control_brain_state_id=0x00",
        "actor_cast_diagnostic_context=0xDC",
        "cast_diagnostic_callback_slot=0x10",
        "cast_diagnostic_vtable_callback=0x10",
        "object_vtable=0x00",
        "gameplay_actor_attach_vfunc=0x10",
        "gameplay_actor_detach_vfunc=0x1C",
        "actor_world_unregister_notify_vfunc=0x48",
        "skills_wizard_probe_vfunc=0x68",
        "actor_world_lookup_object_by_handle=0x0045ADE0",
        "trace_builder_entry=0x0044F5F0",
        "trace_sink_entry=0x00624610",
        "native_apply_damage=0x0063E7D0",
        "native_query_cone=0x00641B10",
        "native_query_radius=0x00642090",
        "earth_child_radius_damage=0x005F3830",
        "startup_rich_item_build=0x004645B0",
        "damage_context_source=0x0081C6E0",
    )
    missing_layout = [token for token in required_layout_tokens if token not in layout_text]
    if missing_layout:
        raise StaticReTestFailure(
            "second residual layout is missing token(s): " +
            ", ".join(missing_layout))

    required_code_tokens = (
        (crash_summary_text, "crash_summary", "kGameNpcSourceProfile74MirrorOffset"),
        (crash_summary_text, "crash_summary", "kGameNpcSourceProfile56MirrorOffset"),
        (crash_summary_text, "crash_summary", "kActorGridCellPtrOffset"),
        (crash_summary_text, "crash_summary", "kActorOwnerOffset"),
        (crash_logger_text, "crash_logger", "kMovementControllerPrimaryCountOffset"),
        (crash_logger_text, "crash_logger", "kMovementOverlapEntryAuxOffset"),
        (native_active_object_text, "native_active_object", "kActorWorldLookupObjectByHandle"),
        (native_active_object_text, "native_active_object", "CallActorWorldLookupObjectByHandleSafe"),
        (standalone_tracking_text, "standalone_tracking", "kObjectVtableOffset"),
        (public_state_getters_text, "public_state_getters", "kObjectVtableOffset"),
        (actor_world_calls_text, "actor_world_calls", "kGameplayActorAttachVfuncOffset"),
        (actor_world_calls_text, "actor_world_calls", "kGameplayActorDetachVfuncOffset"),
        (actor_lifecycle_text, "actor_lifecycle", "kActorWorldUnregisterNotifyVfuncOffset"),
        (actor_lifecycle_text, "actor_lifecycle", "IsActorWorldUnregisterNotifyCallable"),
        (actor_lifecycle_text, "actor_lifecycle", "skipped stale native teardown during scene churn"),
        (standalone_destruction_text, "standalone_destruction", "DetachLoaderOwnedWizardActorFromGameplayActorList"),
        (standalone_destruction_text, "standalone_destruction", "CallGameplayActorDetachSafe"),
        (standalone_destruction_text, "standalone_destruction", "actor_address,\n            0,\n            &exception_code"),
        (player_cast_hooks_text, "player_cast_hooks", "kSkillsWizardProbeVfuncOffset"),
        (boulder_projection_text, "boulder_projection", "active_spell_state.release_base_damage"),
        (selection_text, "selection", "kActorControlBrainStateIdOffset"),
        (selection_text, "selection", "kActorCastDiagnosticContextOffset"),
        (selection_text, "selection", "kCastDiagnosticVtableCallbackOffset"),
        (selection_text, "selection", "kActorControlBrainFollowLeaderOffset"),
        (standalone_spawn_text, "standalone_spawn", "kActorControlBrainFollowLeaderOffset"),
        (cast_trace_text, "cast_trace_profiles", "read_runtime_layout_offset(\"trace_builder_entry\")"),
        (player_watch_text, "player_watch", "read_runtime_layout_offset(\"earth_child_radius_damage\")"),
        (element_damage_text, "element_damage", "read_runtime_layout_offset(\"native_apply_damage\")"),
        (element_damage_text, "element_damage", "read_runtime_layout_offset(\"damage_context_source\")"),
        (startup_trace_text, "startup_trace", "read_runtime_layout_offset(\"startup_rich_item_build\")"),
    )
    missing_code = [
        f"{label}:{token}" for text, label, token in required_code_tokens if token not in text
    ]
    if missing_code:
        raise StaticReTestFailure(
            "second residual code is not layout-backed: " +
            ", ".join(missing_code))

    forbidden_patterns = (
        (standalone_render_text, "standalone_render", r"actor_address \+ 0x(?:194|1C0)|actor_address,\s*0x(?:194|1C0)"),
        (crash_summary_text, "crash_summary", r"actor_address,\s*0x(?:54|58)"),
        (crash_logger_text, "crash_logger", r"context_address \+ 0x(?:40|4C|70|7C)|entry_address\) \+ 0x(?:0C|10|14)"),
        (native_active_object_text, "native_active_object", r"state\.object,\s*0x00"),
        (standalone_tracking_text, "standalone_tracking", r"(?:actor|self|deleter)_address,\s*0x00"),
        (public_state_getters_text, "public_state_getters", r"actor_address,\s*0x00"),
        (actor_world_calls_text, "actor_world_calls", r"vtable \+ 0x10"),
        (actor_world_calls_text, "actor_world_calls", r"vtable \+ 0x1C"),
        (player_cast_hooks_text, "player_cast_hooks", r"chosen_runtime,\s*0|chosen_vtable \+ 0x68"),
        (boulder_projection_text, "boulder_projection", r"active_spell_snapshot\.object,\s*0x58|stat_vtable \+ 0x100"),
        (selection_text, "selection", r"selection_ptr \+ 0x(?:0|1C|20|24|28|2C|30|34)|actor_address,\s*0xDC|actor_dc_(?:ptr|vtable) \+ 0x10"),
        (standalone_spawn_text, "standalone_spawn", r"selection_state_address,\s*0x24"),
        (cast_trace_text, "cast_trace_profiles", r"0x00(?:44F5F0|45ADA0|44FED8|44FEE9|44FF03|624610|624652|44FF0F|44FF38|52DB09|52DB0B)"),
        (player_watch_text, "player_watch", r"0x00(?:544C60|45ADE0|52F3B0|5E5450|524D70|60B700|60AC40|5F1F00|5F2360|5F25B0|5F2980|5F3830)"),
        (element_damage_text, "element_damage", r"0x00(?:451DC0|63E7D0|52DA80|641B10|642090|53F9C0|543860|524D70|52F3B0|45ADE0|544C60|5FA270|5E5450|60B700|60AC40|5FA6D0|5F1F00|5F2360|5F25B0|5F2980|5F3830|81C6E0|81C6E4|81C6E8|81C6EC)"),
        (startup_trace_text, "startup_trace", r"0x00(?:5CFA80|5758D2|4645B0|4699B0)"),
    )
    present_forbidden = [
        label for text, label, pattern in forbidden_patterns if re.search(pattern, text, re.I)
    ]
    if present_forbidden:
        raise StaticReTestFailure(
            "second residual raw offsets/addresses remain in: " +
            ", ".join(present_forbidden))

    retired_tick_text = "\n".join(
        read_text(path)
        for path in (
            ROOT / "SolomonDarkModLoader/src/gameplay_seams.h",
            ROOT / "SolomonDarkModLoader/src/gameplay_seams/address_storage.inl",
            ROOT / "SolomonDarkModLoader/src/gameplay_seams/size_bindings.inl",
            ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/actor_tick_hooks.inl",
            ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/actor_tick/player_actor_tick_hook.inl",
            MOD_LOADER_PROJECT,
            MOD_LOADER_PROJECT_FILTERS,
            BINARY_LAYOUT,
        )
    )
    retired_tick_tokens = (
        "TickBotOwnedSkillsWizard",
        "kSkillsWizardTickVfuncOffset",
        "skills_wizard_tick_vfunc",
        "bot_owned_skills_tick",
    )
    present_retired_tick_tokens = [
        token for token in retired_tick_tokens if token in retired_tick_text
    ]
    if present_retired_tick_tokens:
        raise StaticReTestFailure(
            "retired unverified bot-owned Skills_Wizard tick remains: " +
            ", ".join(present_retired_tick_tokens))

    return "second residual runtime offsets and trace addresses are layout-backed"


def test_process_termination_skips_loader_shutdown() -> str:
    dllmain_text = read_text(ROOT / "SolomonDarkModLoader/src/dllmain.cpp")
    process_detach = re.search(
        r"case DLL_PROCESS_DETACH:\s*"
        r"if \(reserved == nullptr\) \{\s*"
        r"sdmod::Shutdown\(\);\s*"
        r"\}\s*break;",
        dllmain_text,
        re.S,
    )
    if process_detach is None:
        raise StaticReTestFailure(
            "process termination still performs full loader/Steam shutdown from DllMain"
        )
    if "(void)reserved;" in dllmain_text:
        raise StaticReTestFailure(
            "DllMain still discards the process-termination discriminator"
        )
    return "process termination bypasses loader-lock Steam/network shutdown"


def test_crash_reports_preserve_faulting_x86_frame_chain() -> str:
    internal_header = read_text(
        ROOT / "SolomonDarkModLoader/src/logger_internal.h"
    )
    reporting = read_text(
        ROOT / "SolomonDarkModLoader/src/logger_crash_reporting.cpp"
    )
    handlers = read_text(
        ROOT / "SolomonDarkModLoader/src/logger_exception_handlers.cpp"
    )
    for source, token in (
        (internal_header, "std::string FormatX86FrameChain("),
        (reporting, "std::string FormatX86FrameChain("),
        (reporting, "TryReadCrashU32(current_frame, &next_frame)"),
        (reporting, "DescribeAddress(return_address)"),
        (handlers, "FormatX86FrameChain(ebp_address, 12)"),
        (handlers, "FormatX86FrameChain(ebp, 12)"),
    ):
        if token not in source:
            raise StaticReTestFailure(
                "faulting x86 frame-chain diagnostics are missing: " + token
            )
    return "first-chance and unhandled reports preserve the faulting x86 frame chain"


def test_stage_mirror_repairs_denied_destination_acl() -> str:
    mirror_text = read_text(
        ROOT / "SolomonDarkModLauncher/src/Staging/FileTreeMirror.cs"
    )
    required_tokens = (
        "CopyStageFileWithAccessRecovery",
        "PrepareForDeletion(destinationFile)",
        '"/remove:d"',
        "currentUserName",
    )
    missing = [token for token in required_tokens if token not in mirror_text]
    if missing:
        raise StaticReTestFailure(
            "stage ACL recovery is missing: " + ", ".join(missing)
        )
    repair_start = mirror_text.find(
        "private static void PrepareForDeletion(FileSystemInfo entry)"
    )
    repair_end = mirror_text.find(
        "private static void ClearRestrictedAttributes",
        repair_start,
    )
    if repair_start < 0 or repair_end < 0:
        raise StaticReTestFailure("stage ACL recovery helper is missing")
    body = mirror_text[repair_start:repair_end]
    grant_index = body.find("GrantCurrentUserFullControl")
    attributes_index = body.find("ClearRestrictedAttributes")
    if grant_index < 0 or attributes_index < 0 or grant_index > attributes_index:
        raise StaticReTestFailure(
            "stage ACL recovery still clears attributes before repairing access"
        )
    return "stage mirror removes explicit deny ACLs before retrying destination writes"


def test_remaining_native_addresses_and_probe_offsets_are_layout_backed() -> str:
    layout_text = read_text(BINARY_LAYOUT)
    seams_header_text = read_gameplay_seams_header_source()
    address_storage_text = read_text(ROOT / "SolomonDarkModLoader/src/gameplay_seams/address_storage.inl")
    address_bindings_text = read_text(ROOT / "SolomonDarkModLoader/src/gameplay_seams/state_and_address_bindings.inl")
    size_bindings_text = read_text(ROOT / "SolomonDarkModLoader/src/gameplay_seams/size_bindings.inl")
    exception_handlers_text = read_text(ROOT / "SolomonDarkModLoader/src/logger_exception_handlers.cpp")
    skill_choices_text = read_bot_skill_choice_source()
    slot_destruction_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/standalone_materialization_slot_bot_destruction.inl"
    )
    stock_tick_probe_text = read_text(STOCK_TICK_RESTORE_LIVE_PROBE)
    ally_hp_probe_text = read_text(ROOT / "tests/re/run_live_ally_hp_native_defaults_probe.py")
    standalone_collision_probe_text = read_text(ROOT / "tests/re/run_live_standalone_collision_probe.py")
    combat_state_probe_text = read_text(ROOT / "tools/probe_combat_state_transition.py")
    slot_watch_text = read_text(ROOT / "tools/watch_gameplay_slot_cast_startup.py")
    autonomous_probe_text = read_text(ROOT / "tools/probe_bot_autonomous_combat_validation.py")
    cast_state_probe_text = read_text(ROOT / "tools/cast_state_probe.py")
    skill_choice_stress_text = read_text(ROOT / "tools/probe_bot_skill_choice_stress.py")
    shared_hub_probe_text = read_text(ROOT / "tools/probe_shared_hub_actor_contract.py")

    required_layout_tokens = (
        "wizard_default_hp=0x00784CF8",
        "wizard_default_mp=0x007DE9B8",
        "movement_collision_query_type2_hazards_crash=0x009125E0",
        "movement_collision_query_type2_hazards_recover=0x009126C2",
        "movement_collision_iterate_primary_crash=0x00522D10",
        "movement_collision_iterate_primary_recover=0x00522E00",
        "actor_move_blocked_flag=0x34",
        "actor_grid_member_flag=0x36",
        "actor_collision_response_flag=0x37",
        "actor_register_transient=0x68",
        "gameplay_wave_text_value=0x1C30",
        "trace_spell_cast_dispatcher_body=0x00548A03",
        "trace_spell_cast_3ef_body=0x0052BB87",
        "standalone_wizard_progression_entry_internal_id=0x1C",
        "standalone_wizard_progression_entry_category=0x26",
        "standalone_wizard_progression_entry_statbook=0x6C",
        "native_string_data=0x04",
        "native_string_length=0x10",
        "statbook_name_string=0x1C",
        "statbook_max_level=0x5C",
        "movement_controller_callback_a=0x38",
        "movement_controller_callback_b=0x50",
        "movement_controller_callback_c=0x68",
        "bonus_choice_count_skill_id=0x3F",
        "special_choice_activation_id=0x34",
        "cast_probe_default_skill_id=0x3EF",
    )
    missing_layout = [token for token in required_layout_tokens if token not in layout_text]
    if missing_layout:
        raise StaticReTestFailure(
            "remaining raw-address layout is missing token(s): " +
            ", ".join(missing_layout))

    required_code_tokens = (
        (seams_header_text, "seams_header", "kMovementCollisionQueryType2HazardsCrash"),
        (seams_header_text, "seams_header", "kGameplaySkillChoiceBonusChoiceCountSkillId"),
        (seams_header_text, "seams_header", "kGameplaySkillChoiceSpecialActivationId"),
        (address_storage_text, "address_storage", "kMovementCollisionIteratePrimaryRecover"),
        (address_storage_text, "address_storage", "kGameplaySkillChoiceBonusChoiceCountSkillId"),
        (size_bindings_text, "size_bindings", "bonus_choice_count_skill_id"),
        (size_bindings_text, "size_bindings", "special_choice_activation_id"),
        (address_bindings_text, "address_bindings", "movement_collision_query_type2_hazards_crash"),
        (skill_choices_text, "skill_choices", "NativeBonusLevelUpChoiceCountSkillId"),
        (skill_choices_text, "skill_choices", "NativeSpecialChoiceActivationId"),
        (exception_handlers_text, "exception_handlers", "kMovementCollisionQueryType2HazardsCrash"),
        (exception_handlers_text, "exception_handlers", "kMovementCollisionIteratePrimaryRecover"),
        (slot_destruction_text, "slot_destruction", "kGameplayRuntimeGlobal"),
        (stock_tick_probe_text, "stock_tick_probe", "read_runtime_layout_offset(\"player_actor_tick\")"),
        (stock_tick_probe_text, "stock_tick_probe", "read_runtime_layout_offset(\"player_actor_move_step\")"),
        (ally_hp_probe_text, "ally_hp_probe", "NATIVE_WIZARD_DEFAULT_HP_GLOBAL_KEY"),
        (ally_hp_probe_text, "ally_hp_probe", "read_runtime_layout_offset(NATIVE_WIZARD_DEFAULT_HP_GLOBAL_KEY)"),
        (standalone_collision_probe_text, "standalone_collision_probe", "read_runtime_layout_offset(\"actor_register_transient\")"),
        (standalone_collision_probe_text, "standalone_collision_probe", "read_runtime_layout_offset(\"actor_grid_member_flag\")"),
        (combat_state_probe_text, "combat_state_probe", "read_runtime_layout_offset(\"gameplay_wave_text_value\")"),
        (slot_watch_text, "slot_watch", "read_runtime_layout_offset(\"trace_spell_cast_dispatcher_body\")"),
        (slot_watch_text, "slot_watch", "read_runtime_layout_offset(\"trace_spell_cast_3ef_body\")"),
        (autonomous_probe_text, "autonomous_probe", "read_runtime_layout_offset(\"trace_spell_cast_dispatcher_body\")"),
        (autonomous_probe_text, "autonomous_probe", "read_runtime_layout_offset(\"trace_spell_cast_3ef_body\")"),
        (cast_state_probe_text, "cast_state_probe", "read_runtime_layout_offset(DEFAULT_BOT_SKILL_ID_KEY)"),
        (skill_choice_stress_text, "skill_choice_stress", "read_runtime_layout_offset(\"standalone_wizard_progression_entry_statbook\")"),
        (skill_choice_stress_text, "skill_choice_stress", "read_runtime_layout_offset(\"native_string_length\")"),
        (skill_choice_stress_text, "skill_choice_stress", "read_runtime_layout_offset(\"bonus_choice_count_skill_id\")"),
        (shared_hub_probe_text, "shared_hub_probe", "read_runtime_layout_offset(\"movement_overlap_entry_type\")"),
        (shared_hub_probe_text, "shared_hub_probe", "MOVEMENT_CONTROLLER_CALLBACK_OFFSETS"),
        (shared_hub_probe_text, "shared_hub_probe", "read_runtime_layout_offset(\"movement_controller_callback_a\")"),
    )
    missing_code = [
        f"{label}:{token}" for text, label, token in required_code_tokens if token not in text
    ]
    if missing_code:
        raise StaticReTestFailure(
            "remaining raw-address code is not layout-backed: " +
            ", ".join(missing_code))

    forbidden_patterns = (
        (exception_handlers_text, "exception_handlers", r"0x00(?:9125E0|9126C2|522D10|522E00)"),
        (slot_destruction_text, "slot_destruction", r"0x00C0C264"),
        (stock_tick_probe_text, "stock_tick_probe", r"query_memory\(0x00(?:548B00|525800)\)"),
        (ally_hp_probe_text, "ally_hp_probe", r"NATIVE_WIZARD_DEFAULT_[A-Z_]+\s*=\s*0x00(?:784CF8|7DE9B8)"),
        (standalone_collision_probe_text, "standalone_collision_probe", r"ACTOR_OFFSET_[A-Z_]+\s*=\s*0x(?:18|1C|30|34|36|37|38|3C|54|58|5C|5E|68)"),
        (combat_state_probe_text, "combat_state_probe", r"gameplay_global \+ 0x1C30"),
        (slot_watch_text, "slot_watch", r"read_runtime_layout_offset\(\"spell_cast_(?:dispatcher|3ef)\"\) \+ (?:3|0x27)"),
        (autonomous_probe_text, "autonomous_probe", r"read_runtime_layout_offset\(\"spell_cast_(?:dispatcher|3ef)\"\) \+ (?:3|0x27)"),
        (cast_state_probe_text, "cast_state_probe", r"DEFAULT_BOT_SKILL_ID\s*=\s*0x"),
        (skill_choice_stress_text, "skill_choice_stress", r"(?:PROGRESSION|STATBOOK)_[A-Z_]+_OFFSET\s*=\s*0x|BONUS_CHOICE_COUNT_SKILL_ID\s*=\s*0x|address \+ 0x10"),
        (shared_hub_probe_text, "shared_hub_probe", r"read_u32\((?:primary|secondary)(?:_list|[01]) \+ 0x|callback_offset in ipairs\(\{\{0x|i \* 4"),
    )
    present_forbidden = [
        label for text, label, pattern in forbidden_patterns if re.search(pattern, text, re.I)
    ]
    if present_forbidden:
        raise StaticReTestFailure(
            "remaining raw native addresses or probe offsets remain in: " +
            ", ".join(present_forbidden))

    return "remaining native addresses and probe offsets are layout-backed"


def test_runtime_debug_trace_rejects_overlapping_detours_and_untraces_rebased_addresses() -> str:
    runtime_debug_core_text = read_text(ROOT / "SolomonDarkModLoader/src/runtime_debug_core.cpp")
    runtime_debug_trace_text = read_text(ROOT / "SolomonDarkModLoader/src/runtime_debug_trace.cpp")
    runtime_debug_internal_text = read_text(ROOT / "SolomonDarkModLoader/src/runtime_debug_internal.h")
    trace_overlap_live_probe_text = read_text(ROOT / "tests/re/run_live_trace_overlap_guard_probe.py")

    required_tokens = (
        (runtime_debug_internal_text, "runtime_debug_internal", "OverlapsRelativeJumpPatch"),
        (runtime_debug_core_text, "runtime_debug_core", "OverlapsRelativeJumpPatch"),
        (runtime_debug_core_text, "runtime_debug_core", "candidate + 5 > address"),
        (runtime_debug_core_text, "runtime_debug_core", "bytes[0] == 0xE9"),
        (runtime_debug_trace_text, "runtime_debug_trace", "OverlapsRelativeJumpPatch(resolved_address, trace->patch_size"),
        (runtime_debug_trace_text, "runtime_debug_trace", "overlaps an existing relative jump patch"),
        (runtime_debug_trace_text, "runtime_debug_trace", "const auto resolved_address = rt::ResolveExecutableRuntimeAddress(address);"),
        (trace_overlap_live_probe_text, "trace_overlap_live_probe", "trace_spell_cast_dispatcher_body"),
        (trace_overlap_live_probe_text, "trace_overlap_live_probe", "trace_spell_cast_3ef_body"),
        (trace_overlap_live_probe_text, "trace_overlap_live_probe", "relative jump patch"),
        (trace_overlap_live_probe_text, "trace_overlap_live_probe", "clean_trace_disarmed_by_original_address"),
    )
    missing = [
        f"{label}:{token}" for text, label, token in required_tokens if token not in text
    ]
    if missing:
        raise StaticReTestFailure(
            "runtime trace overlap/untrace guard is missing token(s): " +
            ", ".join(missing))

    forbidden_patterns = (
        (
            runtime_debug_core_text,
            "runtime_debug_core",
            r"LooksLikeExistingJumpPatch\(uintptr_t address,\s*size_t patch_size\)\s*\{[^}]*patch_size < 7",
        ),
        (
            runtime_debug_trace_text,
            "runtime_debug_trace",
            r"RuntimeDebug_UntraceFunction\(uintptr_t address\)\s*\{[^}]*ResolveRuntimeAddress\(address\)",
        ),
    )
    present_forbidden = [
        label for text, label, pattern in forbidden_patterns if re.search(pattern, text, re.S)
    ]
    if present_forbidden:
        raise StaticReTestFailure(
            "runtime trace still has unsafe overlap/untrace behavior in: " +
            ", ".join(present_forbidden))

    return "runtime trace rejects overlapping detours and untraces rebased executable addresses"


def test_autonomous_probe_uses_bot_scoped_diagnostics_and_native_damage_evidence() -> str:
    autonomous_probe_text = read_text(ROOT / "tools/probe_bot_autonomous_combat_validation.py")

    required_tokens = (
        "configure_lua_probe_diagnostics",
        "clear_lua_probe_diagnostics",
        "lua_bots_enable_diagnostic_logs = true",
        "lua_bots_probe = {",
        "probe_bot_id",
        "observe_attack_window(args.observe_seconds, probe_bot_id)",
        "def read_attack_lines(bot_id: int | None = None)",
        '"attack id={bot_id} "',
        '"bot_id"',
        "native_cast_lines",
        "mana_spend_log_count",
        "targeted_damage_or_write_seen",
        "controlled_damage_or_write_seen",
        "first_target_health",
        "second_target_health",
        "first_targeted_death_seen",
        "second_targeted_death_seen",
        "wait_for_materialized_bots",
        "choose_probe_bot",
        "query_bot_state_by_id",
        "promote_bot_into_run_scene",
        "profile_element_id",
        "profile_element_id != 2",
    )
    missing = [token for token in required_tokens if token not in autonomous_probe_text]
    if missing:
        raise StaticReTestFailure(
            "autonomous combat probe is missing bot-scoped diagnostic/native evidence token(s): " +
            ", ".join(missing))

    forbidden_patterns = (
        r"def read_attack_lines\(\) -> list\[str\]:",
        r"observe_attack_window\(args\.observe_seconds\)(?!,)",
        r'"damage_or_hp_write_seen": hp_damage_or_write_seen,',
    )
    present_forbidden = [
        pattern for pattern in forbidden_patterns if re.search(pattern, autonomous_probe_text)
    ]
    if present_forbidden:
        raise StaticReTestFailure(
            "autonomous combat probe still relies on unscoped stale evidence: " +
            ", ".join(present_forbidden))

    return "autonomous probe captures bot-scoped Lua diagnostics and native damage evidence"


def test_lua_follow_preserves_timeout_teleport() -> str:
    follow_text = read_text(LUA_BOT_FOLLOW)
    targeting_test_text = read_text(ROOT / "tools/test_lua_bots_targeting.lua")

    required_tokens = (
        "teleport_to_follow_target",
        "follow_teleport",
        "pcall(sd.bots.update",
        "pcall(sd.bots.update, update)",
        "FOLLOW_STOP_DISTANCE",
        "expired follow watchdog should teleport the bot to its move target",
        "watchdog teleport should clear the active follow target",
    )
    combined_text = follow_text + "\n" + targeting_test_text
    missing = [token for token in required_tokens if token not in combined_text]
    if missing:
        raise StaticReTestFailure(
            "follow timeout teleport coverage is missing token(s): " +
            ", ".join(missing))

    forbidden_tokens = (
        "follow_timeout_reissue",
        "hub_follow_sync",
        "expired follow watchdog must not teleport",
    )
    present = [token for token in forbidden_tokens if token in combined_text]
    if present:
        raise StaticReTestFailure(
            "follow timeout coverage left walking-only token(s): " +
            ", ".join(present))

    return "follow uses timeout teleport recovery and the 100/250 band"


def test_native_derived_wizard_visuals_are_layout_backed() -> str:
    clone_source_text = read_text(STANDALONE_CLONE_SOURCE)
    slot_creation_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/standalone_materialization_slot_bot_creation.inl"
    )
    equip_visual_lanes_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/standalone_materialization_equip_visual_lanes.inl"
    )
    actor_render_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/standalone_materialization_actor_render_state.inl"
    )
    native_remote_playback_text = read_source_unit(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_movement/native_remote_playback.inl"
    )
    priming_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/scene_and_animation_bot_priming_and_selection.inl"
    )
    standalone_spawn_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/execute_requests/spawn_standalone_wizard.inl"
    )
    release_text = read_text(CAST_RELEASE_HELPERS)
    native_types_text = read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/native_function_types.inl")
    safe_decls_text = read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/seh_safe_call_declarations.inl")
    player_calls_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_actor_calls/player_runtime_and_progression_calls.inl"
    )
    seam_header_text = read_text(ROOT / "SolomonDarkModLoader/src/gameplay_seams.h")
    seam_storage_text = read_text(ROOT / "SolomonDarkModLoader/src/gameplay_seams/address_storage.inl")
    seam_bindings_text = read_text(ROOT / "SolomonDarkModLoader/src/gameplay_seams/state_and_address_bindings.inl")
    layout_text = read_text(BINARY_LAYOUT)

    required_tokens = (
        "skills_wizard_get_primary_color=0x00660760",
        "kSkillsWizardGetPrimaryColor",
        "SkillsWizardGetPrimaryColorFn",
        "CallSkillsWizardGetPrimaryColorSafe",
        "BuildNativeDerivedWizardSourceProfile",
        "native_element_color",
        "TryBuildSourceProfileColorPreimage",
        "TryReadNativeSourceActorDefaultTrimColor",
        "ResolveNativePrimaryEntryForElement",
        "CaptureActorRenderBuildSnapshot",
        "ApplySourceActorRenderSelectorsToTargetActor",
        "AttachBuiltDescriptorToEquipVisualLane",
        "AttachGameplaySlotBotStaffItem",
        "SeedWizardBotNativeCollisionStateFromSourceActor",
        "NormalizeStandaloneWizardSyntheticVisualState",
        "kNativeDerivedSourceProfileSize",
        "native-derived source profile",
        "Render selector bytes are materialization-local",
        "ApplyNativeRemoteParticipantProfileRenderSelectors",
        "reassert the local profile selector",
    )
    combined_text = "\n".join((
        clone_source_text,
        slot_creation_text,
        equip_visual_lanes_text,
        actor_render_text,
        priming_text,
        standalone_spawn_text,
        release_text,
        native_types_text,
        safe_decls_text,
        player_calls_text,
        seam_header_text,
        seam_storage_text,
        seam_bindings_text,
        layout_text,
        native_remote_playback_text,
    ))
    missing = [token for token in required_tokens if token not in combined_text]
    if missing:
        raise StaticReTestFailure(
            "native-derived wizard visual path is missing token(s): " +
            ", ".join(missing))

    forbidden_patterns = (
        r"kFireMana\s*\[",
        r"kWaterMana\s*\[",
        r"kEarthMana\s*\[",
        r"kAirMana\s*\[",
        r"kEtherMana\s*\[",
        r"GetWizardElementColor",
        r"kWizardElementColor",
        r"1\.08003414f",
        r"0\.18303899f",
        r"-0\.09265301f",
        r"1\.05664342f",
        r"TryReadActorDescriptorColor",
        r"descriptor_accent",
        r"ResolveNativeDisciplineEntryForDiscipline",
        r"ClearActorLiveDescriptorBlock",
        r"ApplySourceActorBodyDescriptorToTargetActor",
        r"ApplySourceActorGameplaySlotRenderSnapshotToTargetActor",
        r"TransferSourceActorAttachmentToEquipVisualLane",
    )
    present_forbidden = [
        pattern for pattern in forbidden_patterns if re.search(pattern, combined_text)
    ]
    if present_forbidden:
        raise StaticReTestFailure(
            "native-derived wizard visual path still contains hardcoded table/color token(s): " +
            ", ".join(present_forbidden))

    if not re.search(
        r"CallWizardCloneFromSourceActorSafe[\s\S]*SeedWizardBotNativeCollisionStateFromSourceActor[\s\S]*DestroyWizardCloneSourceActor",
        standalone_spawn_text,
    ):
        raise StaticReTestFailure(
            "standalone clone spawn does not seed native collision before source cleanup")
    if not re.search(
        r"ApplySourceActorRenderSelectorsToTargetActor[\s\S]*NormalizeStandaloneWizardSyntheticVisualState\(actor_address\)",
        standalone_spawn_text,
    ):
        raise StaticReTestFailure(
            "standalone clone spawn does not clear source-profile scratch pointers after native render selection")
    if not re.search(
        r"SeedWizardBotNativeCollisionStateFromSourceActor[\s\S]*SeedGameplaySlotBotRenderStateFromSourceActor",
        priming_text,
    ):
        raise StaticReTestFailure(
            "gameplay-slot bot priming does not seed native collision before render materialization")
    if "AttachBuiltDescriptorToEquipVisualLane" not in slot_creation_text:
        raise StaticReTestFailure(
            "gameplay-slot bot materialization does not publish the source descriptor through helper lanes")
    if re.search(
        r"SeedWizardCloneSourceActorFromNativeDerivedProfile\(\s*actor_address,",
        slot_creation_text,
    ):
        raise StaticReTestFailure(
            "gameplay-slot bot materialization still stages a source descriptor over the live target actor")
    if not re.search(
        r"IsLuaControlledParticipant[\s\S]*CreateWizardCloneSourceActor\(\s*"
        r"world_address,[\s\S]*&source_actor_address,[\s\S]*"
        r"CaptureActorRenderBuildSnapshot\(source_actor_address\)[\s\S]*"
        r"DestroyWizardCloneSourceActor\(source_actor_address,",
        slot_creation_text,
    ):
        raise StaticReTestFailure(
            "Lua gameplay-slot visuals do not build on a disposable source actor before helper publication")
    if "ApplyNativeRemoteParticipantRenderSelectorBytes" in native_remote_playback_text:
        raise StaticReTestFailure(
            "remote playback still overwrites profile-built clone render selector bytes")
    if not re.search(
        r"ApplyNativeRemoteParticipantProfileRenderSelectors[\s\S]*"
        r"binding->character_profile\.element_id[\s\S]*"
        r"ApplySourceActorRenderSelectorsToTargetActor",
        native_remote_playback_text,
    ):
        raise StaticReTestFailure(
            "remote playback does not recover a cast-mutated selector from the local profile")
    if not re.search(
        r"kActorEquipRuntimeVisualLinkPrimaryOffset,\s*robe_visual_link_ctor_address"
        r"[\s\S]*kActorEquipRuntimeVisualLinkSecondaryOffset,\s*hat_visual_link_ctor_address",
        slot_creation_text,
    ):
        raise StaticReTestFailure(
            "gameplay-slot materialization must keep the stock robe/hat actor-lane mapping")
    if not re.search(
        r"CaptureActorRenderBuildSnapshot[\s\S]*ApplySourceActorRenderSelectorsToTargetActor[\s\S]*AttachBuiltDescriptorToEquipVisualLane[\s\S]*AttachGameplaySlotBotStaffItem\(\s*actor_address,\s*&stage_error",
        slot_creation_text,
    ):
        raise StaticReTestFailure(
            "gameplay-slot bot materialization does not publish safe source selector bytes, helper lanes, and a target-owned staff attachment")
    staff_attach_match = re.search(
        r"AttachGameplaySlotBotStaffItem[\s\S]*?\n\}",
        equip_visual_lanes_text,
    )
    if not staff_attach_match:
        raise StaticReTestFailure("could not find gameplay-slot target-owned staff attach helper")
    staff_attach_text = staff_attach_match.group(0)
    missing_staff_attach_tokens = [
        token for token in (
            "CreateGameplaySlotStaffItemObject",
            "kActorEquipRuntimeVisualLinkAttachmentOffset",
            "staff_item_address",
            "CallScalarDeletingDestructorSafe",
            "slot_actor_owned_staff_attached",
        )
        if token not in staff_attach_text
    ]
    if missing_staff_attach_tokens:
        raise StaticReTestFailure(
            "gameplay-slot staff path does not create and attach a target-owned stock staff object: " +
            ", ".join(missing_staff_attach_tokens))
    forbidden_staff_attach_tokens = [
        token for token in (
            "source_attachment_address",
            "slot_actor_source_staff_transferred",
            "built_snapshot.attachment_address",
        )
        if token in slot_creation_text or token in staff_attach_text
    ]
    if forbidden_staff_attach_tokens:
        raise StaticReTestFailure(
            "gameplay-slot staff path must not attach the temporary source actor attachment: " +
            ", ".join(forbidden_staff_attach_tokens))

    required_remote_visual_settle_tokens = (
        "if (native_remote_participant)",
        "kActorContinuousPrimaryActiveOffset",
        "remote_visual_staging_before",
        "remote_visual_staging_clear_ok",
        "Remote casts run through stock spell handlers without the local player",
        "kActorRenderDriveOverlayAlphaOffset",
        "remote_overlay_alpha_clear_ok",
        "kActorRenderDriveMoveBlendOffset",
        "remote_overlay_phase_clear_ok",
    )
    missing_remote_visual_settle_tokens = [
        token for token in required_remote_visual_settle_tokens
        if token not in release_text
    ]
    if missing_remote_visual_settle_tokens:
        raise StaticReTestFailure(
            "native remote cast completion no longer settles continuous-primary visual staging: " +
            ", ".join(missing_remote_visual_settle_tokens))
    if "kActorContinuousPrimaryActiveOffset" in actor_render_text:
        raise StaticReTestFailure(
            "visual normalizers must not clear the active continuous-primary/orb staging field during active casts")

    native_remote_playback_text = read_source_unit(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_movement/native_remote_playback.inl")
    for required_token in (
        "kActorMagicShieldAbsorbRemainingOffset",
        "binding->replicated_magic_shield_absorb_remaining",
        "kActorMagicShieldAbsorbCapacityOffset",
        "binding->replicated_magic_shield_absorb_capacity",
        "kActorMagicShieldExplosionFractionOffset",
        "binding->replicated_magic_shield_explosion_fraction",
        "kActorMagicShieldHitFlashOffset",
        "binding->replicated_magic_shield_hit_flash",
    ):
        if required_token not in native_remote_playback_text:
            raise StaticReTestFailure(
                "native remote playback must sync the complete Magic Shield state block")

    if re.search(
        r"TryWriteField\(\s*actor_address,\s*kActorRenderDriveOverlayAlphaOffset",
        native_remote_playback_text,
        re.S,
    ) or re.search(
        r"TryWriteField\(\s*actor_address,\s*kActorRenderDriveMoveBlendOffset",
        native_remote_playback_text,
        re.S,
    ):
        raise StaticReTestFailure(
            "native remote playback must not write clone-owned overlay/cache offsets +0x248 or +0x268")

    return "wizard visuals are built from native Skills_Wizard colors and published through safe selectors plus helper lanes and a target-owned staff"


def test_standalone_animation_drive_applies_dynamic_fields() -> str:
    drive_text = read_text(SCENE_ANIMATION_DRIVE_PROFILES)
    locomotion_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_movement/locomotion_and_animation.inl"
    )
    movement_step_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_movement_tick/wizard_bot_movement_step.inl"
    )
    player_tick_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/actor_tick/player_actor_tick_hook.inl"
    )

    match = re.search(
        r"void ApplyWizardDynamicWalkCycleState\([^)]*\)\s*\{(?P<body>.*?)\n\}",
        drive_text,
        re.S)
    if not match:
        raise StaticReTestFailure("ApplyWizardDynamicWalkCycleState was not found")

    body = match.group("body")
    required_tokens = (
        "kActorWalkCyclePrimaryOffset",
        "kActorWalkCycleSecondaryOffset",
    )
    missing = [token for token in required_tokens if token not in body]
    if missing:
        raise StaticReTestFailure(
            "wizard animation drive is missing dynamic walk-cycle write token(s): " +
            ", ".join(missing))

    forbidden_dynamic_tokens = (
        "kActorRenderDriveStrideScaleOffset",
        "kActorRenderAdvanceRateOffset",
        "kActorRenderAdvancePhaseOffset",
        "kActorRenderDriveMoveBlendOffset",
        "dynamic_render_drive_move_blend",
    )
    dynamic_regressions = [
        token for token in forbidden_dynamic_tokens if token in body
    ]
    locomotion_regressions = [
        token for token in (
            "dynamic_render_drive_stride = stride_step",
            "dynamic_render_advance_rate = displacement_distance",
            "dynamic_render_advance_phase = primary",
            "dynamic_render_drive_move_blend = 1.0f",
        )
        if token in locomotion_text
    ]
    if dynamic_regressions or locomotion_regressions:
        raise StaticReTestFailure(
            "wizard dynamic movement still writes native-owned render phase/blend token(s): " +
            ", ".join(dynamic_regressions + locomotion_regressions))

    required_movement_tokens = (
        "Clear the previous",
        "ClearWizardBotMovementVectorInputs(actor_address);",
        "IsWizardParticipantKind(binding->kind) && !cast_active",
        "binding != nullptr && IsStandaloneWizardKind(binding->kind)",
        "AdvanceWizardWalkCycleState(binding, displacement_distance);",
        "ApplyWizardDynamicWalkCycleState(binding, actor_address);",
        "ApplyObservedBotAnimationState(binding, actor_address, true);",
        "ApplyActorAnimationDriveState(actor_address, moving);",
        "Restore the bot's own vector after applying the profile",
        "Keep the bot's own vector after replay",
    )
    movement_combined = player_tick_text + "\n" + movement_step_text + "\n" + drive_text + "\n" + locomotion_text
    missing_movement = [
        token for token in required_movement_tokens if token not in movement_combined
    ]
    if missing_movement:
        raise StaticReTestFailure(
            "bot movement/animation tick ownership is missing token(s): " +
            ", ".join(missing_movement))

    if "if (!IsStandaloneWizardKind(binding->kind))" not in locomotion_text:
        raise StaticReTestFailure("gameplay-slot bots can still enter standalone animation replay")

    return "bot movement clears stale stock-tick inputs, advances walk cycles for all wizard bots, and keeps standalone profile replay off gameplay-slot bots"


def test_native_global_reads_do_not_use_loader_substitutes() -> str:
    resource_text = read_text(RESOURCE_STATE)
    movement_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_movement_tick/wizard_bot_movement_step.inl"
    )
    locomotion_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_movement/locomotion_and_animation.inl"
    )
    gameplay_state_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/scene_and_animation_gameplay_state.inl"
    )
    actor_animation_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/scene_and_animation_actor_animation_state.inl"
    )
    public_debug_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_debug_and_spawn.inl"
    )
    public_state_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_state_getters.inl"
    )
    dispatch_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_gameplay_thread_dispatch.inl"
    )
    cast_probe_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/cast_probe_state.inl"
    )
    entity_update_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/execute_requests/entity_update_and_rail_selection.inl"
    )
    run_lifecycle_state_text = read_text(
        ROOT / "SolomonDarkModLoader/src/run_lifecycle/state_and_targets.inl"
    )
    run_lifecycle_hooks_text = read_text(
        ROOT / "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks.inl"
    )
    combined_text = "\n".join((
        resource_text,
        movement_text,
        locomotion_text,
        gameplay_state_text,
        actor_animation_text,
        public_debug_text,
        public_state_text,
        dispatch_text,
        cast_probe_text,
        entity_update_text,
        run_lifecycle_state_text,
        run_lifecycle_hooks_text,
    ))

    forbidden_tokens = (
        "ReadResolvedGameFloatOr",
        "ReadResolvedGameDoubleAsFloatOr",
        "ReadResolvedGlobalIntOr",
        "fallback_world_address",
    )
    present = [token for token in forbidden_tokens if token in combined_text]
    if present:
        raise StaticReTestFailure(
            "active native-global readers still allow loader substitute values: " +
            ", ".join(present))

    required_tokens = (
        "TryReadResolvedGameFloat",
        "TryReadResolvedGameDoubleAsFloat",
        "TryReadResolvedGlobalInt",
        "have_native_movement_globals",
        "have_native_walk_cycle_globals",
        "native walk-cycle globals unavailable",
        "native enemy-count global unavailable",
        "gold.changed native gold global unavailable",
        "pending-level-kind global unavailable",
        "TryResolveLocalPlayerWorldContext(",
    )
    missing = [token for token in required_tokens if token not in combined_text]
    if missing:
        raise StaticReTestFailure(
            "strict native-global read guard is missing token(s): " +
            ", ".join(missing))

    return "active movement/combat native globals fail visibly instead of using loader substitute values"


def test_repo_wide_native_reads_do_not_publish_substitute_state() -> str:
    run_lifecycle_text = "\n".join((
        read_text(ROOT / "SolomonDarkModLoader/src/run_lifecycle/combat_prelude_and_sources.inl"),
        read_text(ROOT / "SolomonDarkModLoader/src/run_lifecycle/enemy_tracking_and_reset.inl"),
        read_text(ROOT / "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks.inl"),
        read_text(ROOT / "SolomonDarkModLoader/src/run_lifecycle/spell_cast_hooks.inl"),
    ))
    skill_choice_text = "\n".join((
        read_text(ROOT / "SolomonDarkModLoader/src/bot_runtime/helpers/skill_choices.inl"),
        read_text(ROOT / "SolomonDarkModLoader/src/bot_runtime/public_api/bot_skill_choice_api.inl"),
        read_source_unit(ROOT / "SolomonDarkModLoader/src/bot_runtime/public_api/skill_choices_api.inl"),
    ))
    native_stats_text = read_native_spell_stats_source()
    player_state_text = "\n".join((
        read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/scene_and_animation_memory_and_progression.inl"),
        read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_state_getters.inl"),
    ))
    combined_text = "\n".join((run_lifecycle_text, skill_choice_text, native_stats_text, player_state_text))

    forbidden_tokens = (
        "ReadFloatFieldOrZero",
        "fallback_config_address",
        "ReadProgressionRoundedXpOrFallback",
        "ReadProgressionNextXpOrZero",
        "ReadValueOr<double>(scale_address",
        "ReadValueOr<float>(output_values_address",
        "ReadRoundedXpOrUnknown",
        "ReadFieldOr<std::uint8_t>(self_address, kEnemyDeathHandledOffset",
        "ReadFieldOr<int>(progression_address, kProgressionLevelOffset",
    )
    present = [token for token in forbidden_tokens if token in combined_text]
    if present:
        raise StaticReTestFailure(
            "repo-wide native reads still publish substitute state: " +
            ", ".join(present))

    required_tokens = (
        "TryReadActorPosition",
        "spell.cast native event fields unavailable",
        "enemy.spawned native position unavailable",
        "enemy.death native type unavailable",
        "enemy.death native handled flag unavailable",
        "level.up native xp unavailable",
        "TryReadPlayerRoundedXp",
        "TryReadFiniteFloatField(progression_address, kProgressionHpOffset",
        "TryReadProgressionRoundedXp",
        "native bot skill choice xp read failed",
        "native primary mana output read failed",
        "native primary damage output read failed",
    )
    missing = [token for token in required_tokens if token not in combined_text]
    if missing:
        raise StaticReTestFailure(
            "repo-wide strict native read cleanup is missing token(s): " +
            ", ".join(missing))

    return "run-lifecycle, skill-choice, and native spell stat reads fail visibly instead of publishing substitutes"


def test_path_builder_does_not_walk_to_unrequested_alternate_goals() -> str:
    path_text = read_text(BOT_PATHFINDING_PATH_BUILDING)
    traversability_text = read_text(BOT_PATHFINDING_TRAVERSABILITY)
    motion_text = read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_pathfinding_motion_update.inl")

    forbidden_tokens = (
        "best_reachable_index",
        "path fallback reachable-goal",
        "fallback_goal=(",
        "resolved_goal_index = best_reachable_index",
    )
    present = [token for token in forbidden_tokens if token in path_text]
    if present:
        raise StaticReTestFailure(
            "path builder can still walk toward an unrequested reachable-goal substitute: " +
            ", ".join(present))

    required_tokens = (
        "A* search found no path",
        "StopBotPathMotion",
        "native tick path update failed",
    )
    combined_text = path_text + "\n" + motion_text + "\n" + read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/actor_tick/player_actor_tick_hook.inl")
    missing = [token for token in required_tokens if token not in combined_text]
    if missing:
        raise StaticReTestFailure(
            "path failure guard is missing expected stop/failure token(s): " +
            ", ".join(missing))

    required_participant_block_tokens = (
        "IsGameplayPathBlockedByWizardParticipant",
        "std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex)",
        "other.actor_address == binding->actor_address",
        "other.materialized_world_address != binding->materialized_world_address",
        "Path placement overlaps another wizard participant",
    )
    missing_participant_block = [
        token for token in required_participant_block_tokens if token not in traversability_text
    ]
    if missing_participant_block:
        raise StaticReTestFailure(
            "path placement does not reject occupied wizard participant circles: " +
            ", ".join(missing_participant_block))

    required_occupied_waypoint_tokens = (
        "target_blocked_by_participant",
        "IsGameplayPathBlockedByWizardParticipant(binding, waypoint.x, waypoint.y, actor_radius, nullptr)",
        "StopBotPathMotion(binding, false);",
    )
    missing_occupied_waypoint = [
        token for token in required_occupied_waypoint_tokens if token not in motion_text
    ]
    if missing_occupied_waypoint:
        raise StaticReTestFailure(
            "path follower does not rebuild away from occupied wizard participant waypoints: " +
            ", ".join(missing_occupied_waypoint))

    return "unreachable or occupied movement targets fail cleanly instead of walking to hidden alternate goals"


def test_path_builder_expands_cells_before_los_smoothing() -> str:
    path_text = read_text(BOT_PATHFINDING_PATH_BUILDING)
    neighbor_block_match = re.search(
        r"for \(const auto& offset : neighbor_offsets\) \{(?P<body>.*?)"
        r"const auto next_index = GameplayPathCellIndex",
        path_text,
        re.S,
    )
    if neighbor_block_match is None:
        raise StaticReTestFailure("path builder neighbor expansion block was not found")
    neighbor_block = neighbor_block_match.group("body")
    forbidden_neighbor_tokens = (
        "true,\n                    true,\n                    current_point_x",
        "require_direct_reachability=true",
        "allow_anchor_fallback=true",
    )
    present_neighbor_tokens = [
        token for token in forbidden_neighbor_tokens if token in neighbor_block
    ]
    if present_neighbor_tokens:
        raise StaticReTestFailure(
            "A* neighbor expansion still requires direct LOS to each cell sample: " +
            ", ".join(present_neighbor_tokens))
    required_neighbor_tokens = (
        "false,\n                    false,\n                    current_point_x",
        "IsGameplayPathCellTraversable(",
    )
    missing_neighbor_tokens = [
        token for token in required_neighbor_tokens if token not in neighbor_block
    ]
    if missing_neighbor_tokens:
        raise StaticReTestFailure(
            "A* neighbor expansion is missing cell-grid planner token(s): " +
            ", ".join(missing_neighbor_tokens))
    if "node_point_x[static_cast<std::size_t>(next_index)] = candidate_point_x" not in path_text:
        raise StaticReTestFailure("A* cell sample points are no longer retained for waypoint reconstruction")

    simplifier_match = re.search(
        r"void SimplifyBotPathWaypoints\((?P<body>.*?)\n\}",
        path_text,
        re.S,
    )
    if simplifier_match is None:
        raise StaticReTestFailure("path simplifier block was not found")
    simplifier_block = simplifier_match.group("body")
    forbidden_simplifier_tokens = (
        "previous_dx == next_dx",
        "previous_dy == next_dy",
    )
    present_simplifier_tokens = [
        token for token in forbidden_simplifier_tokens if token in simplifier_block
    ]
    if present_simplifier_tokens:
        raise StaticReTestFailure(
            "path simplifier still only removes collinear waypoints instead of greedy LOS smoothing: " +
            ", ".join(present_simplifier_tokens))
    required_simplifier_tokens = (
        "furthest_reachable",
        "IsGameplayPathSegmentTraversable(",
        "simplified.push_back((*waypoints)[furthest_reachable])",
    )
    missing_simplifier_tokens = [
        token for token in required_simplifier_tokens if token not in simplifier_block
    ]
    if missing_simplifier_tokens:
        raise StaticReTestFailure(
            "path simplifier is missing greedy LOS smoothing token(s): " +
            ", ".join(missing_simplifier_tokens))
    return "A* expands traversable cells first and applies LOS as waypoint smoothing"


def test_remote_per_cast_primary_settles_without_waiting_for_release() -> str:
    processing_text = read_text(PENDING_CAST_PROCESSING)
    preparation_text = read_text(PENDING_CAST_PREPARATION)
    release_text = read_text(CAST_RELEASE_HELPERS)
    projectile_observation_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/projectile_observation.inl"
    )
    player_control_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/player_control_hooks.inl"
    )
    player_cast_text = read_player_cast_hooks_source()
    keyboard_injection_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_keyboard_injection.inl"
    )
    participant_state_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/participant_entity_state.inl"
    )
    transport_text = read_multiplayer_transport_source()
    runtime_state_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/runtime_request_state.inl"
    )
    mouse_refresh_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_mouse_refresh_hook.inl"
    )
    input_queue_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_input_queueing.inl"
    )
    verifier_text = read_text(REAL_INPUT_SPELL_CAST_SYNC_VERIFIER)
    animation_element_verifier_text = read_text(
        ROOT / "tools/verify_multiplayer_animation_mana_elements.py"
    )

    required_processing_tokens = (
        "remote_per_cast_pure_primary_no_handle_settled",
        "ongoing.mana_charge_kind == multiplayer::BotManaChargeKind::PerCast",
        "remote_per_cast_pure_primary_without_live_handle",
        "remote_per_cast_projectile_observed",
        "kRemotePerCastPurePrimaryProjectileSettleTicks",
        "kRemotePerCastPurePrimaryProjectileMissingSettleTicks",
        "remote_per_cast_projectile_impact_lifecycle_settled",
        "remote_per_cast_projectile_targetless_settled",
        "preserve_remote_per_cast_projectile_target",
        "kRemotePerCastPurePrimaryNoProjectileSafetyTicks",
        "remote_release_driven_pure_primary_no_handle_settled",
        "ongoing.mana_charge_kind != multiplayer::BotManaChargeKind::PerCast",
        "remote_input_release_or_timeout",
        "!remote_per_cast_pure_primary_without_live_handle",
    )
    missing_processing_tokens = [
        token for token in required_processing_tokens if token not in processing_text
    ]
    if missing_processing_tokens:
        raise StaticReTestFailure(
            "remote per-cast primary settlement is missing token(s): " +
            ", ".join(missing_processing_tokens))

    required_observation_tokens = (
        (preparation_text, "preparation", "remote_per_cast_projectile_baseline_valid"),
        (preparation_text, "preparation", "remote_per_cast_projectile_expected_type"),
        (preparation_text, "preparation", "remote_per_cast_projectile_addresses_before"),
        (preparation_text, "preparation", "ExpectedPurePrimaryProjectileTypeForSelectionState"),
        (preparation_text, "preparation", "TryListPurePrimaryProjectileActorAddressesInScene("),
        (preparation_text, "preparation", "ongoing.remote_per_cast_projectile_expected_type"),
        (preparation_text, "preparation", "remote_cast_sequence="),
        (projectile_observation_text, "projectile_observation", "IsPurePrimaryProjectileActorType"),
        (projectile_observation_text, "projectile_observation", "ExpectedPurePrimaryProjectileTypeForSelectionState"),
        (projectile_observation_text, "projectile_observation", "return 0x7D3"),
        (projectile_observation_text, "projectile_observation", "0x7D4"),
        (projectile_observation_text, "projectile_observation", "return 0x7D5"),
        (projectile_observation_text, "projectile_observation", "TryListSceneActors"),
        (projectile_observation_text, "projectile_observation", "TryFindNewPurePrimaryProjectileActorInScene("),
        (processing_text, "processing", "TryFindNewPurePrimaryProjectileActorInScene("),
        (processing_text, "processing", "TryFindPurePrimaryProjectileActorStateInScene("),
        (processing_text, "processing", "ongoing.remote_per_cast_projectile_expected_type"),
        (processing_text, "processing", "remote_per_cast_projectile_observed_actor"),
        (processing_text, "processing", "remote_per_cast_projectile_reached_target"),
        (processing_text, "processing", "remote_per_cast_projectile_missing_ticks_waiting"),
        (projectile_observation_text, "projectile_observation", "TryFindPurePrimaryProjectileActorStateInScene("),
        (release_text, "release", "remote_cast_sequence="),
        (release_text, "release", "remote_projectile_expected_type="),
        (release_text, "release", "remote_projectile_observed_actor="),
        (release_text, "release", "remote_projectile_reached_target="),
        (release_text, "release", "remote_projectile_missing_ticks="),
        (player_control_text, "player_control", "native_tick_ms="),
        (player_control_text, "player_control", "native_queue_id="),
        (player_control_text, "player_control", "s_last_multiplayer_primary_actor"),
    )
    missing_observation_tokens = [
        f"{label}:{token}" for text, label, token in required_observation_tokens if token not in text
    ]
    if missing_observation_tokens:
        raise StaticReTestFailure(
            "remote per-cast projectile observation is missing token(s): " +
            ", ".join(missing_observation_tokens))

    required_emission_guard_tokens = (
        "HasNativeRemotePerCastProjectileEmission",
        "binding->ongoing_cast.remote_per_cast_projectile_observed",
        "binding->ongoing_cast.remote_per_cast_projectile_emission_latched",
        "binding->ongoing_cast.mana_charge_kind !=\n            multiplayer::BotManaChargeKind::PerCast",
        "HookPurePrimaryAttackDispatch",
        "remote_per_cast_duplicate_dispatches_suppressed",
        "TryFindNewPurePrimaryProjectileActorInScene(",
        "ongoing.remote_per_cast_projectile_emission_latched = true",
    )
    missing_emission_guard_tokens = [
        token for token in required_emission_guard_tokens
        if token not in player_cast_text
    ]
    if missing_emission_guard_tokens:
        raise StaticReTestFailure(
            "observed remote per-cast projectiles must suppress repeat native emission: " +
            ", ".join(missing_emission_guard_tokens))
    required_dispatch_latch_tokens = (
        (participant_state_text, "participant_state", "remote_per_cast_projectile_emission_latched"),
        (participant_state_text, "participant_state", "remote_per_cast_duplicate_dispatches_suppressed"),
        (keyboard_injection_text, "keyboard_injection", "kPurePrimaryAttackDispatch"),
        (keyboard_injection_text, "keyboard_injection", "HookPurePrimaryAttackDispatch"),
        (keyboard_injection_text, "keyboard_injection", "pure_primary_attack_dispatch_hook"),
        (keyboard_injection_text, "keyboard_injection", "Failed to install pure-primary attack dispatch hook"),
    )
    missing_dispatch_latch_tokens = [
        f"{label}:{token}"
        for text, label, token in required_dispatch_latch_tokens
        if token not in text
    ]
    if missing_dispatch_latch_tokens:
        raise StaticReTestFailure(
            "remote per-cast native dispatch dedupe is not wired end-to-end: " +
            ", ".join(missing_dispatch_latch_tokens))
    dispatch_hook_start = player_cast_text.find(
        "void __fastcall HookPurePrimaryAttackDispatch")
    dispatch_hook_end = player_cast_text.find(
        "void __fastcall", dispatch_hook_start + 1)
    dispatch_hook_body = player_cast_text[
        dispatch_hook_start:
        dispatch_hook_end if dispatch_hook_end != -1 else len(player_cast_text)
    ]
    dispatch_latch_guard_pos = dispatch_hook_body.find(
        "if (ongoing.remote_per_cast_projectile_emission_latched)")
    dispatch_original_pos = dispatch_hook_body.find("original(self)")
    dispatch_observation_pos = dispatch_hook_body.find(
        "TryFindNewPurePrimaryProjectileActorInScene(")
    dispatch_latch_set_pos = dispatch_hook_body.find(
        "ongoing.remote_per_cast_projectile_emission_latched = true")
    if not (
        dispatch_latch_guard_pos != -1 and
        dispatch_original_pos != -1 and
        dispatch_observation_pos != -1 and
        dispatch_latch_set_pos != -1 and
        dispatch_latch_guard_pos < dispatch_original_pos <
        dispatch_observation_pos < dispatch_latch_set_pos
    ):
        raise StaticReTestFailure(
            "remote per-cast dispatch must guard, emit once, observe the real projectile, then latch")
    for hook_name in ("HookPlayerActorPurePrimaryGate", "HookSpellCastDispatcher"):
        hook_start = player_cast_text.find(f"void __fastcall {hook_name}")
        next_hook = player_cast_text.find("void __fastcall", hook_start + 1)
        hook_body = player_cast_text[
            hook_start:next_hook if next_hook != -1 else len(player_cast_text)
        ]
        guard_pos = hook_body.find("HasNativeRemotePerCastProjectileEmission(actor_address, nullptr)")
        original_pos = hook_body.find("original(self)")
        if guard_pos == -1 or original_pos == -1 or guard_pos > original_pos:
            raise StaticReTestFailure(
                f"{hook_name} must suppress repeat per-cast emission before stock execution")

    required_startup_sanitizer_tokens = (
        "TryReadRollbackAimTargetFloat",
        "std::isfinite(raw) ? raw : fallback_value",
        "memory.TryWriteField(actor_address, offset, *value)",
        "aim_x_fallback",
        "aim_y_fallback",
    )
    missing_startup_sanitizer_tokens = [
        token for token in required_startup_sanitizer_tokens
        if token not in preparation_text
    ]
    if missing_startup_sanitizer_tokens:
        raise StaticReTestFailure(
            "remote cast startup does not sanitize stale non-finite aim-target rollback fields: " +
            ", ".join(missing_startup_sanitizer_tokens))
    if re.search(
        r"TryReadFiniteFloatField\(\s*actor_address,\s*kActorAimTargetXOffset",
        preparation_text,
        re.S,
    ) or re.search(
        r"TryReadFiniteFloatField\(\s*actor_address,\s*kActorAimTargetYOffset",
        preparation_text,
        re.S,
    ):
        raise StaticReTestFailure(
            "remote cast startup must not reject stale non-finite actor aim-target cache fields")
    if re.search(
        r"remote_per_cast_pure_primary_no_handle_settled\s*=\s*"
        r".*remote_per_cast_projectile_observed_ticks_waiting\s*>=\s*"
        r"kRemotePerCastPurePrimaryProjectileSettleTicks",
        processing_text,
        re.S,
    ):
        raise StaticReTestFailure(
            "targeted remote pure-primary projectiles must not settle solely from observed tick count")
    if re.search(
        r"remote_per_cast_projectile_impact_lifecycle_settled\s*=\s*"
        r".*remote_per_cast_projectile_reached_target\s*&&",
        processing_text,
        re.S,
    ):
        raise StaticReTestFailure(
            "targeted remote pure-primary projectiles must wait for native projectile disappearance, not target proximity")
    impact_lifecycle_initializer = re.search(
        r"remote_per_cast_projectile_impact_lifecycle_settled\s*=\s*(?P<body>.*?);",
        processing_text,
        re.S,
    )
    if (
        impact_lifecycle_initializer is not None and
        "remote_per_cast_projectile_observed_ticks_waiting" in
        impact_lifecycle_initializer.group("body")
    ):
        raise StaticReTestFailure(
            "targeted remote pure-primary projectiles must not settle from an observed-tick safety cap")
    if not re.search(
        r"preserve_remote_per_cast_projectile_target\s*=\s*"
        r".*ParticipantEntityBinding::OngoingCastState::Lane::PurePrimary"
        r".*multiplayer::BotManaChargeKind::PerCast"
        r".*ongoing\.target_actor_address\s*!=\s*0",
        processing_text,
        re.S,
    ):
        raise StaticReTestFailure(
            "remote per-cast pure-primary casts must preserve the initial target through release updates")

    stale_click_tokens = [
        token for token in (
            "last_multiplayer_primary_cast_click_serial",
            "kLocalPrimaryCastClickWindowMs",
            "s_last_multiplayer_primary_edge_serial",
            "GetGameplayMouseLeftEdgeSerial",
            "GetGameplayMouseLeftEdgeTickMs",
            "click_serial=",
        )
        if token in player_control_text or token in runtime_state_text
    ]
    if stale_click_tokens:
        raise StaticReTestFailure(
            "multiplayer primary emission is still click-serial gated: " +
            ", ".join(stale_click_tokens))
    required_replacement_tokens = (
        "ReleaseActiveLocalCastInputForReplacement",
        "Multiplayer local active cast replaced by native cast",
        "replacement_native_queue_id",
        "CastInputPhase::Released",
    )
    missing_replacement_tokens = [
        token for token in required_replacement_tokens if token not in transport_text
    ]
    if missing_replacement_tokens:
        raise StaticReTestFailure(
            "held primary native restarts are still dropped instead of replacing the active replicated cast: " +
            ", ".join(missing_replacement_tokens))
    if "Multiplayer local cast event dropped while gesture active" in transport_text:
        raise StaticReTestFailure(
            "held primary native restarts still use the old drop path while a gesture is active")
    required_idle_remote_suppression_tokens = (
        "sanitize_native_remote_idle_control_brain",
        "ClearIdleNativeRemoteCastReplayState(actor_address, selection_pointer);",
        "ClearIdleNativeRemoteCastReplayState(actor_address);",
        "IsIdleNativeRemoteParticipantActor(actor_address, nullptr)",
        "IsNativeRemoteParticipantBinding(binding) &&",
        "!binding->ongoing_cast.active",
        "kActorPrimaryActionLatchE4Offset",
        "kActorPrimaryActionLatchE8Offset",
        "kActorPostGateActiveByteOffset",
        "(void)write_vector2(param2, 0.0f, 0.0f);",
    )
    missing_idle_remote_suppression_tokens = [
        token for token in required_idle_remote_suppression_tokens
        if token not in player_control_text and token not in player_cast_text
    ]
    if missing_idle_remote_suppression_tokens:
        raise StaticReTestFailure(
            "idle native-remote participants must not let stock control brain replay casts: " +
            ", ".join(missing_idle_remote_suppression_tokens))
    idle_remote_suppression = re.search(
        r"if\s*\(\s*sanitize_native_remote_idle_control_brain\s*\)\s*\{(?P<body>.*?)\n\s*\}",
        player_control_text,
        re.S,
    )
    if idle_remote_suppression is None:
        raise StaticReTestFailure("idle native-remote control-brain sanitation block is missing")
    idle_remote_suppression_body = idle_remote_suppression.group("body")
    if "return;" in idle_remote_suppression_body:
        raise StaticReTestFailure(
            "idle native-remote control-brain sanitation must not skip stock original()")
    original_call = player_control_text.find("original(self, param2, param3);")
    sanitation_before = player_control_text.find("if (sanitize_native_remote_idle_control_brain)")
    sanitation_after = player_control_text.find(
        "if (sanitize_native_remote_idle_control_brain)",
        original_call + len("original(self, param2, param3);") if original_call != -1 else 0,
    )
    if (
        original_call == -1 or
        sanitation_before == -1 or
        sanitation_after == -1 or
        sanitation_before > original_call or
        sanitation_after < original_call
    ):
        raise StaticReTestFailure(
            "idle native-remote control-brain sanitation must scrub before and after stock original()")
    for hook_name in ("HookPlayerActorPurePrimaryGate", "HookSpellCastDispatcher"):
        hook_start = player_cast_text.find(f"void __fastcall {hook_name}")
        if hook_start == -1:
            raise StaticReTestFailure(f"{hook_name} is missing")
        next_hook = player_cast_text.find("void __fastcall", hook_start + 1)
        hook_body = player_cast_text[hook_start:next_hook if next_hook != -1 else len(player_cast_text)]
        guard_pos = hook_body.find("IsIdleNativeRemoteParticipantActor(actor_address, nullptr)")
        original_pos = hook_body.find("original(self)")
        if guard_pos == -1 or original_pos == -1 or guard_pos > original_pos:
            raise StaticReTestFailure(
                f"{hook_name} must reject idle native-remote replay before stock cast execution")
    required_mouse_release_tokens = (
        (runtime_state_text, "runtime_state", "injected_mouse_left_active"),
        (mouse_refresh_text, "mouse_refresh", "Released injected gameplay mouse-left"),
        (mouse_refresh_text, "mouse_refresh", "kGameplayCastIntentOffset"),
        (input_queue_text, "input_queue", "ClearQueuedGameplayMouseLeft"),
        (input_queue_text, "input_queue", "pending_mouse_left_frames.store(0"),
        (verifier_text, "real_input_verifier", "sd.input.clear_mouse_left"),
    )
    missing_mouse_release_tokens = [
        f"{label}:{token}" for text, label, token in required_mouse_release_tokens if token not in text
    ]
    if missing_mouse_release_tokens:
        raise StaticReTestFailure(
            "queued gameplay mouse-left input must release its injected press/cast-intent state: " +
            ", ".join(missing_mouse_release_tokens))

    if "remote_projectile_observed_count != native_hook_count" not in verifier_text:
        if "assert_sequence_counts" not in verifier_text:
            raise StaticReTestFailure(
                "real-input spell verifier must reject remote projectile lifecycle overproduction")
    if "parse_remote_settle_sequences" not in verifier_text:
        raise StaticReTestFailure(
            "real-input spell verifier must compare completed remote cast sequences")
    if "parse_local_pressed_sequences" not in verifier_text:
        raise StaticReTestFailure(
            "real-input spell verifier must compare against source cast sequences")
    if "Multiplayer local native cast sent" not in verifier_text:
        raise StaticReTestFailure(
            "real-input spell verifier must map native queue ids to transport cast sequences")
    if '"sampled_fire_addresses": sorted(observed_fire)' not in verifier_text:
        raise StaticReTestFailure(
            "real-input spell verifier must report sampled projectile actors")
    if "remote_projectile_observed_sequences" not in verifier_text:
        raise StaticReTestFailure(
            "real-input spell verifier must report completed remote projectile lifecycle sequences")
    if "native_hook_count = count_local_native_queues" not in verifier_text:
        raise StaticReTestFailure(
            "real-input spell verifier must compare remote presentation against source native hook count")
    if "remote_settle_count" not in verifier_text:
        raise StaticReTestFailure(
            "real-input spell verifier must require one remote per-cast lifecycle settlement")
    if "held_fire |= parse_unique_fire(state)" not in verifier_text:
        raise StaticReTestFailure(
            "real-input spell verifier must sample short-lived projectiles during the hold window")
    required_animation_element_verifier_tokens = (
        "parse_remote_projectile_spawn_sequences",
        "remote_projectile_expected_type=",
        "remote_projectile_observed=1",
        "obj_type=",
        "runtime_observed_sequences",
        "sample_observed_projectile",
    )
    missing_animation_element_verifier_tokens = [
        token for token in required_animation_element_verifier_tokens
        if token not in animation_element_verifier_text
    ]
    if missing_animation_element_verifier_tokens:
        raise StaticReTestFailure(
            "all-element verifier does not assert exact runtime projectile type evidence: " +
            ", ".join(missing_animation_element_verifier_tokens))

    return "remote per-cast primaries settle from projectile observation and verifier rejects overfire"


def test_remote_held_input_casts_defer_lifecycle_to_sender_input() -> str:
    processing_text = read_text(PENDING_CAST_PROCESSING)

    target_lost_guard = re.search(
        r"const bool target_lost =(?P<body>.*?);",
        processing_text,
        re.DOTALL,
    )
    if target_lost_guard is None:
        raise StaticReTestFailure("target-lost guard was not found")
    target_lost_body = target_lost_guard.group("body")
    required_target_lost_tokens = (
        "!remote_input_driven_cast",
        "held_target_missing",
        "kTargetlessRetargetGraceTicks",
    )
    missing_target_lost_tokens = [
        token for token in required_target_lost_tokens
        if token not in target_lost_body
    ]
    if missing_target_lost_tokens:
        raise StaticReTestFailure(
            "remote held input can still be cleaned up as target-lost: " +
            ", ".join(missing_target_lost_tokens))

    required_processing_tokens = (
        "Remote-player casts are driven by the sender's input stream.",
        "remote_input_active_without_release",
        "remote_input_release_settled",
        "!remote_input_active_without_release",
    )
    missing_processing_tokens = [
        token for token in required_processing_tokens
        if token not in processing_text
    ]
    if missing_processing_tokens:
        raise StaticReTestFailure(
            "remote held input lifecycle is missing sender-input guard token(s): " +
            ", ".join(missing_processing_tokens))

    safety_cap_guard = re.search(
        r"const bool safety_cap_hit =(?P<body>.*?);",
        processing_text,
        re.DOTALL,
    )
    if safety_cap_guard is None:
        raise StaticReTestFailure("safety-cap guard was not found")
    if "!remote_input_active_without_release" not in safety_cap_guard.group("body"):
        raise StaticReTestFailure(
            "remote held input can still hit the generic safety cap while sender input is active")

    return "remote held input casts defer lifecycle cleanup to sender release or timeout"


def test_run_lifecycle_spell_hooks_only_forward_local_player_casts() -> str:
    spell_hook_text = read_text(RUN_LIFECYCLE_SPELL_CAST_HOOKS)
    required_tokens = (
        "bool IsLocalPlayerActorForRunLifecycle(uintptr_t actor_address)",
        "ResolveLocalPlayerActorForRunLifecycle()",
        "if (!IsLocalPlayerActorForRunLifecycle(self_address))",
        "g_state.last_consumed_spell_click_serial.store",
        "multiplayer::QueueLocalSpellCastEvent(",
    )
    missing = [token for token in required_tokens if token not in spell_hook_text]
    if missing:
        raise StaticReTestFailure(
            "run-lifecycle spell hooks can still forward non-local casts: " +
            ", ".join(missing))

    guard_pos = spell_hook_text.find("if (!IsLocalPlayerActorForRunLifecycle(self_address))")
    consume_pos = spell_hook_text.find("g_state.last_consumed_spell_click_serial.store")
    queue_pos = spell_hook_text.find("multiplayer::QueueLocalSpellCastEvent(")
    if not (guard_pos >= 0 and consume_pos >= 0 and queue_pos >= 0 and guard_pos < consume_pos < queue_pos):
        raise StaticReTestFailure(
            "run-lifecycle spell hook must prove local actor before consuming click serial or queueing network cast")

    return "run-lifecycle native spell hooks only forward local-player casts"


def test_multiplayer_nameplates_render_from_native_scene_passes() -> str:
    hud_text = read_text(GAMEPLAY_HUD_HOOKS)
    public_state_text = read_text(GAMEPLAY_PUBLIC_STATE_GETTERS)
    overlay_text = read_text(DEBUG_UI_OVERLAY_FRAME_RENDER)
    overlay_health_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/debug_ui_overlay/gameplay_health_bar_rendering.inl"
    )
    overlay_primitives_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/debug_ui_overlay/font_atlas_rendering.inl"
    )
    overlay_capture_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/debug_ui_overlay/exact_text_capture/capture_session.inl"
    )
    overlay_glyph_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/debug_ui_overlay/exact_text_capture/glyph_observation.inl"
    )
    overlay_projection_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/debug_ui_overlay/exact_text_capture/"
        "gameplay_nameplate_projection.inl"
    )
    overlay_render_hooks_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/debug_ui_overlay/exact_text_capture/render_hooks.inl"
    )
    overlay_header_text = read_text(DEBUG_UI_OVERLAY_HEADER)
    overlay_public_text = read_text(DEBUG_UI_OVERLAY_PUBLIC_SURFACE)
    mod_loader_header_text = read_text(MOD_LOADER_HEADER)
    mod_loader_text = read_text(MOD_LOADER_GAMEPLAY)
    layout_text = read_text(BINARY_LAYOUT)
    animation_text = read_text(ACTOR_ANIMATION_ADVANCE_HOOK)
    player_tick_text = read_text(PLAYER_ACTOR_TICK_HOOK)
    keyboard_injection_text = read_text(GAMEPLAY_KEYBOARD_INJECTION)
    native_types_text = read_text(GAMEPLAY_NATIVE_FUNCTION_TYPES)
    verifier_text = read_text(MULTIPLAYER_HUD_NAMES_VERIFIER)
    steam_verifier_text = read_text(STEAM_FRIEND_HUB_VISUALS_VERIFIER)
    physical_steam_verifier_text = read_text(
        STEAM_FRIEND_ACTIVE_PAIR_VISUALS_VERIFIER
    )
    hud_label_materializer_text = read_text(HUD_LABEL_ASSET_MATERIALIZER)

    required_animation_tokens = (
        "struct AnimationAdvanceContextScope",
        "~AnimationAdvanceContextScope()",
        "original(self);",
        "IsTrackedWizardParticipantActorForHud(actor_address)",
        "TryGetGameplayHudParticipantDisplayNameForActor(",
        "&health_ratio);",
        "DrawGameplayHudParticipantName(",
        "participant_id,",
        "health_ratio,",
        "source=playerwizard_render",
        "health_ratio=",
        "health_bar=dx9",
    )
    missing_animation = [
        token for token in required_animation_tokens
        if token not in animation_text
    ]
    if missing_animation:
        raise StaticReTestFailure(
            "PlayerWizard render callback no longer draws remote names and health bars: " +
            ", ".join(missing_animation))

    forbidden_animation_tokens = (
        "TryListGameplayParticipantNameplates(",
        "PublishGameplayParticipantNameplateOverlaySnapshot",
        "source=actor_callback",
        "DrawGameplayParticipantHealthBar(",
        "health_segments",
        # The rendered ratio must come from the authoritative participant
        # runtime snapshot, never from tick-synced actor progression memory
        # that freezes while player-actor ticks are paused.
        "TryGetGameplayParticipantHealthRatio(",
        "TryReadActorProgressionHealth(",
    )
    present_animation = [
        token for token in forbidden_animation_tokens if token in animation_text
    ]
    if present_animation:
        raise StaticReTestFailure(
            "PlayerWizard native render path contains stale overlay/callback plumbing: " +
            ", ".join(present_animation))

    forbidden_hud_tokens = (
        "TryListGameplayParticipantNameplates(",
        "multiplayer-nameplate",
        "ShouldDrawGameplayHudParticipantNameFromActorCallback",
        "PublishGameplayParticipantNameplateOverlaySnapshot",
        "ClearDebugUiGameplayNameplateOverlaySnapshot",
        "DebugUiGameplayNameplateOverlayItem",
        "PublishDebugUiGameplayNameplateOverlaySnapshot",
        "TryProjectGameplayHudNameplatePosition",
        "TryGetPlayerState(",
        "scene_state.kind != \"arena\"",
        "kGameplayHudVirtualWidth",
        "actor_x - player_state.x",
        "DrawGameplayHudUiExactTextAt(",
        "kGameplayUiExactTextObjectRender",
    )
    present_hud = [token for token in forbidden_hud_tokens if token in hud_text]
    if present_hud:
        raise StaticReTestFailure(
            "native nameplate helper still contains stale arena projection or overlay plumbing: " +
            ", ".join(present_hud))

    required_hud_tokens = (
        "void __fastcall HookGameplayUiAllyLabelGlyphDraw(",
        "IsGameplayAllyHudLabelGlyphCall(glyph_address, caller_address)",
        "BuildGameplayAllyHudRows()",
        "ResolveGameplayAllyHudRowIndex(y, rows.size())",
        "DrawGameplayHudAllyBarParticipantName(",
        "&name_layout,",
        "&exception_code);",
        "source=ally_healthbar",
        "stock_label=0",
        "BuildGameplayAllyHudExactText(",
        "EstimateGameplayAllyHudTextWidth(",
        "constexpr float kGameplayAllyHudReservedLabelWidth = 128.0f;",
        "constexpr float kGameplayAllyHudNameHorizontalPadding = 2.0f;",
        "multiplayer::kParticipantDisplayNameBytes - 1",
        '"The ally HUD reservation must fit the longest protocol display name."',
        "resolved.name_left_x = x + kGameplayAllyHudNameHorizontalPadding;",
        "layout_ok=",
        "bar_right_x=",
        "label_right_x=",
        "name_left_x=",
        "name_right_x=",
        "bool CallGameplayExactTextObjectRenderSafe(",
        "NativeStringAssignFn",
        "NativeExactTextObjectRenderFn",
        "NativeGameString native_text",
        "string_assign(&native_text, nullptr)",
        "std::string BuildGameplayNameplateExactText(const std::string& display_name)",
        "constexpr const char* kHalfScaleCommand = \"s(0.5)\"",
        "bool DrawGameplayHudParticipantName(",
        "native gameplay HUD participant name draw",
        "ResolveGameAddressOrZero(kGameplayStringAssign)",
        "ResolveGameAddressOrZero(kGameplayExactTextObjectRender)",
        "ResolveGameAddressOrZero(kGameplayExactTextObjectGlobal)",
        "kGameplayExactTextObjectOffset",
        "const auto text_object_address = text_object_base + kGameplayExactTextObjectOffset",
        "TryReadFiniteFloatField(actor_address, kActorPositionXOffset, &x)",
        "TryReadFiniteFloatField(actor_address, kActorPositionYOffset, &y)",
        "y -= 45.0f;",
        "float EstimateGameplayNameplateTextWidth(std::string_view display_name)",
        "constexpr float kNativeGlyphAdvance = 16.0f;",
        "constexpr float kNativeSpaceAdvance = 8.0f;",
        "float CalculateGameplayNameplateDrawX(float actor_x, std::string_view display_name)",
        "x = CalculateGameplayNameplateDrawX(x, display_name);",
        "const auto nameplate_text = BuildGameplayNameplateExactText(display_name);",
        "BeginDebugUiGameplayParticipantNameplateCapture(",
        "EndDebugUiGameplayParticipantNameplateCapture();",
        "CallGameplayExactTextObjectRenderSafe(",
        "nameplate_text.c_str()",
    )
    missing_hud = [token for token in required_hud_tokens if token not in hud_text]
    if missing_hud:
        raise StaticReTestFailure(
            "native remote-name or thin-health-bar rendering contract is incomplete: " +
            ", ".join(missing_hud))

    if "TryReadActorProgressionHealth(" in hud_text:
        raise StaticReTestFailure(
            "native nameplate helpers read tick-synced actor progression health "
            "instead of the authoritative participant runtime vitals")

    ally_rows = hud_text[
        hud_text.index("std::vector<GameplayAllyHudRow> BuildGameplayAllyHudRows()") :
        hud_text.index("\nbool IsGameplayAllyHudLabelGlyphCall(")
    ]
    if "SnapshotRuntimeState()" in ally_rows:
        raise StaticReTestFailure(
            "the per-row ally HUD path deep-copies the full multiplayer runtime")

    required_authoritative_vitals_tokens = (
        "bool TryGetGameplayHudParticipantDisplayNameForActor(",
        "TryGetRemoteParticipantDisplayState(",
        "!resolved_runtime.valid",
        "resolved_runtime.life_current / resolved_runtime.life_max",
        "resolved_runtime.life_max <= 0.0f",
    )
    missing_authoritative_vitals = [
        token for token in required_authoritative_vitals_tokens
        if token not in public_state_text
    ]
    if missing_authoritative_vitals:
        raise StaticReTestFailure(
            "nameplate health no longer resolves from the authoritative "
            "participant runtime snapshot: " +
            ", ".join(missing_authoritative_vitals))

    if "TryGetGameplayHudParticipantNameplateForActor" in public_state_text + animation_text:
        raise StaticReTestFailure(
            "nameplate health retained a redundant display-name API alias")

    nameplate_getter = public_state_text[
        public_state_text.index("bool TryGetGameplayHudParticipantDisplayNameForActor(") :
        public_state_text.index("\nbool TryGetPlayerState(")
    ]
    if "SnapshotRuntimeState()" in nameplate_getter:
        raise StaticReTestFailure(
            "the per-actor nameplate path deep-copies the full multiplayer runtime")

    forbidden_ascii_health_tokens = (
        "constexpr int kBarSegments",
        "std::string bar_text",
        "\"_s(0.25)[\"",
        "filled_segment_count",
        "bar_text.append",
    )
    present_ascii_health = [
        token for token in forbidden_ascii_health_tokens if token in hud_text
    ]
    if present_ascii_health:
        raise StaticReTestFailure(
            "ASCII participant health fallback remains active: "
            + ", ".join(present_ascii_health)
        )

    required_materializer_tokens = (
        'private const string DefaultAllyLabel = "ALLY";',
        "private const int GeneratedAllyLabelWidth = 128;",
        "return string.IsNullOrEmpty(configuredLabel) ? DefaultAllyLabel : configuredLabel;",
    )
    missing_materializer = [
        token for token in required_materializer_tokens
        if token not in hud_label_materializer_text
    ]
    if missing_materializer:
        raise StaticReTestFailure(
            "staged ally HUD label reservation no longer matches the native name layout: " +
            ", ".join(missing_materializer))

    forbidden_public_tokens = (
        "struct SDModGameplayNameplateDrawItem",
        "TryListGameplayParticipantNameplates(",
        "DebugUiGameplayNameplateOverlayItem",
        "PublishDebugUiGameplayNameplateOverlaySnapshot",
        "ClearDebugUiGameplayNameplateOverlaySnapshot",
    )
    present_public = [
        token for token in forbidden_public_tokens
        if token in public_state_text or token in mod_loader_header_text or token in overlay_header_text or token in overlay_public_text
    ]
    if present_public:
        raise StaticReTestFailure(
            "public nameplate snapshot or overlay API was reintroduced: " +
            ", ".join(present_public))

    forbidden_overlay_tokens = (
        "RenderGameplayParticipantNameplates(",
        "TryListGameplayParticipantNameplates(&items)",
        "TryGetPlayerState(",
        "TryGetSceneState(",
        "struct GameplayNameplateOverlayRenderItem",
        "CopyRecentGameplayNameplateOverlayItems()",
        "BuildGameplayNameplateOverlayRenderItems(",
        "kGameplayNameplateOverlayMaximumIdleMs",
        "kGameplayNameplateVirtualWidth",
        "kGameplayNameplateVirtualHeight",
        "TryProjectGameplayNameplateWithD3dTransform(",
        "DrawGameplayNameplateOverlayItem(",
        "Debug UI overlay rendered cached gameplay nameplates",
        "struct DebugUiGameplayNameplateOverlayItem",
        "PublishDebugUiGameplayNameplateOverlaySnapshot",
        "ClearDebugUiGameplayNameplateOverlaySnapshot",
        "gameplay_nameplate_overlay_items",
        "gameplay_nameplate_overlay_captured_at",
    )
    combined_overlay_text = "\n".join((
        overlay_text,
        overlay_health_text,
        overlay_primitives_text,
        overlay_capture_text,
        overlay_glyph_text,
        overlay_projection_text,
        overlay_render_hooks_text,
        overlay_header_text,
        overlay_public_text,
        mod_loader_text,
    ))
    present_overlay = [token for token in forbidden_overlay_tokens if token in combined_overlay_text]
    if present_overlay:
        raise StaticReTestFailure(
            "D3D gameplay nameplate overlay workaround was reintroduced instead of native commit 35378b3 path: " +
            ", ".join(present_overlay))

    required_dx9_health_tokens = (
        "BeginDebugUiGameplayParticipantNameplateCapture(",
        "EndDebugUiGameplayParticipantNameplateCapture()",
        'capture.surface_id = "gameplay_nameplate";',
        "BuildGameplayParticipantHealthBarRenderItems(",
        # The bar sits flush under the captured name bounds and spans the
        # nameplate width with a readable floor.
        "constexpr float kBarMinimumWidth = 64.0f;",
        "constexpr float kBarVerticalGap = 1.0f;",
        "element.max_x - element.min_x);",
        "item.top = element.max_y + kBarVerticalGap;",
        "GameplayParticipantHealthBarDrawResult DrawGameplayParticipantHealthBar(",
        "GameplayParticipantHealthBarDrawResult::Culled",
        "GameplayParticipantHealthBarDrawResult::Drawn",
        "GameplayParticipantHealthBarDrawResult::Failed",
        "LogGameplayParticipantHealthBarDraw(health_bar, draw_result)",
        'source=dx9_nameplate_healthbar',
        '" ok=" + std::string(drew_bar ? "1" : "0")',
        '" health_percent=" + std::to_string(health_percent)',
        "render_elements.empty() && gameplay_health_bars.empty()",
        "for (const auto& health_bar : gameplay_health_bars)",
        "DrawFilledRect(",
        "DrawRectOutline(",
        "SUCCEEDED(device->DrawPrimitiveUP(",
        "element.gameplay_health_ratio",
        "std::clamp(",
        "bool TryReadUiRenderBase(float* base_x, float* base_y)",
        "capture.expected_origin_x = render_base_x + origin_x;",
        "capture.expected_origin_y = render_base_y + origin_y;",
        "capture.capture_enabled = capture.has_expected_origin;",
        "capture.gameplay_world_width =",
        "TryBuildDestinationQuadBounds(",
        "TryProjectGameplayNameplateQuadBounds(",
        "TryApplyGameplayNameplateViewportClamp(",
        "constexpr float kViewportMargin = 2.0f;",
        "constexpr float kMinimumHealthBarWidth = 64.0f;",
        "const bool intersects_viewport =",
        "capture.gameplay_viewport_offset_resolved = true;",
        "GetLastSeenD3d9Device()",
        "kTextQuadDrawStateDepthOffset",
        "GetTransform(D3DTS_WORLD, &world)",
        "GetTransform(D3DTS_VIEW, &view)",
        "GetTransform(D3DTS_PROJECTION, &projection)",
        "point = TransformD3dRowVector(point, world);",
        "point = TransformD3dRowVector(point, view);",
        "clip.w <= kMinimumPositiveClipW",
        "name_bounds=(",
        "ObserveActiveExactTextQuad(self, draw_vertices, arg3);",
        "original(self, draw_vertices, arg3);",
        "const float* destination_vertices,",
        "const float* /*texture_coordinates*/",
    )
    missing_dx9_health = [
        token
        for token in required_dx9_health_tokens
        if token not in combined_overlay_text
    ]
    if missing_dx9_health:
        raise StaticReTestFailure(
            "DX9 participant health-bar rendering contract is incomplete: "
            + ", ".join(missing_dx9_health)
        )

    forbidden_quad_heuristics = (
        "alternate_valid",
        "alternate_area",
        "primary_area",
        "TryBuildGlyphQuadBounds(arg3",
        "capture.has_expected_origin = false;",
    )
    present_quad_heuristics = [
        token
        for token in forbidden_quad_heuristics
        if token in combined_overlay_text
    ]
    if present_quad_heuristics:
        raise StaticReTestFailure(
            "gameplay nameplate capture reintroduced unverified geometry "
            "fallbacks: " + ", ".join(present_quad_heuristics)
        )

    quad_function_start = overlay_glyph_text.index(
        "void ObserveActiveExactTextQuad("
    )
    gameplay_projection_start = overlay_glyph_text.index(
        'if (capture.surface_id == "gameplay_nameplate")',
        quad_function_start,
    )
    gameplay_projection_end = overlay_glyph_text.index(
        "capture.min_x =",
        gameplay_projection_start,
    )
    gameplay_projection_branch = overlay_glyph_text[
        gameplay_projection_start:gameplay_projection_end
    ]
    for token in (
        "TryProjectGameplayNameplateQuadBounds(",
        "draw_state,",
        "destination_vertices,",
        "base_x,",
        "base_y,",
    ):
        if token not in gameplay_projection_branch:
            raise StaticReTestFailure(
                "gameplay nameplate quad capture does not project through the "
                "stock fixed-function transform: " + token
            )

    required_layout_tokens = (
        "gameplay_ui_glyph_draw=0x004143D0",
        "gameplay_ui_centered_glyph_draw=0x004142E0",
        "gameplay_ally_label_glyph_return=0x005D3521",
        "gameplay_string_assign=0x00402AE0",
        "gameplay_exact_text_object_render=0x0043BCD0",
        "gameplay_ui_bundle=0x008199E4",
        "gameplay_exact_text_object=0x008199A0",
        "gameplay_ui_ally_label_glyph=0x38",
        "gameplay_exact_text_object=0xE7D98",
    )
    missing_layout = [token for token in required_layout_tokens if token not in layout_text]
    if missing_layout:
        raise StaticReTestFailure(
            "native exact-text layout keys are missing: " +
            ", ".join(missing_layout))

    forbidden_layout_tokens = ("gameplay_nameplate_text_object",)
    present_layout = [token for token in forbidden_layout_tokens if token in layout_text]
    if present_layout:
        raise StaticReTestFailure(
            "stale nameplate-only native text layout keys were reintroduced: " +
            ", ".join(present_layout))

    required_native_type_tokens = (
        "using GameplayUiGlyphDrawFn = void(__thiscall*)(void* self, float x, float y)",
        "using GameplayHudRenderDispatchFn = void(__thiscall*)(void* self, int render_case, uintptr_t arg1, uintptr_t arg2)",
        "struct NativeGameString",
        "static_assert(sizeof(NativeGameString) == 0x1C",
        "using NativeStringAssignFn = void(__thiscall*)(void* self, char* text)",
        "using NativeExactTextObjectRenderFn = void(__thiscall*)(void* self, NativeGameString text, float x, float y)",
    )
    missing_native_types = [
        token for token in required_native_type_tokens
        if token not in native_types_text
    ]
    if missing_native_types:
        raise StaticReTestFailure(
            "native text function types are missing: " +
            ", ".join(missing_native_types))

    required_injection_tokens = (
        "ResolveGameAddressOrZero(kGameplayUiGlyphDraw)",
        "ResolveGameAddressOrZero(kGameplayUiCenteredGlyphDraw)",
        "ResolveGameAddressOrZero(kGameplayAllyLabelGlyphReturn)",
        "ResolveGameAddressOrZero(kGameplayUiBundleGlobal)",
        "kGameplayUiAllyLabelGlyphOffset == 0",
        "reinterpret_cast<void*>(&HookGameplayUiGlyphDraw)",
        "reinterpret_cast<void*>(&HookGameplayUiAllyLabelGlyphDraw)",
        "kGameplayUiGlyphDrawHookPatchSize",
        "kGameplayUiCenteredGlyphDrawHookPatchSize",
        "gameplay_ui_glyph_draw_hook",
        "gameplay_ui_ally_label_glyph_draw_hook",
        "ResolveGameAddressOrZero(kGameplayStringAssign)",
        "ResolveGameAddressOrZero(kGameplayExactTextObjectRender)",
        "ResolveGameAddressOrZero(kGameplayExactTextObjectGlobal)",
        "kGameplayExactTextObjectOffset == 0",
        "native HUD text helpers",
        "gameplay_exact_text_object_offset=",
    )
    missing_injection = [
        token for token in required_injection_tokens
        if token not in keyboard_injection_text
    ]
    if missing_injection:
        raise StaticReTestFailure(
            "gameplay injection startup no longer validates native HUD text helpers: " +
            ", ".join(missing_injection))

    required_player_tick_tokens = (
        "native_remote_pre_tick_progression_runtime",
        "ApplyNativeRemoteParticipantPlayback(binding, actor_address, native_tick_now_ms)",
        "ApplyNativeRemoteParticipantPresentationState(binding, actor_address)",
        "ApplyReplicatedWorldSnapshotIfActive(gameplay_address_for_pump, static_cast<std::uint64_t>(::GetTickCount64()))",
    )
    missing_player_tick = [
        token for token in required_player_tick_tokens
        if token not in player_tick_text
    ]
    if missing_player_tick:
        raise StaticReTestFailure(
            "player tick no longer owns remote participant playback/presentation: " +
            ", ".join(missing_player_tick))

    if "PublishGameplayParticipantNameplateOverlaySnapshot();" in player_tick_text:
        raise StaticReTestFailure(
            "player tick still publishes stale D3D nameplate overlay snapshots")

    required_verifier_tokens = (
        "launch_trio(god_mode=False, tile_windows=True)",
        "wait_for_all_relationships(\"hub\", timeout)",
        "wait_for_all_relationships(\"testrun\", timeout)",
        "place_trio_for_capture(timeout)",
        "set_local_player_vitals(",
        "wait_for_remote_matches_owner_health(",
        "verify_dx9_nameplate_health_bar_geometry(",
        "name_bounds=",
        "DX9 health bar is not centered under its name",
        "DX9 health bar is not flush under its name",
        "health_percent={EXPECTED_HALF_HEALTH_PERCENT}",
        "source=playerwizard_render",
        "source=dx9_nameplate_healthbar",
        '"health_bar=dx9"',
        '"dx9_health_bar": dx9_health_line',
        "source=ally_healthbar",
        "stock_label=0",
        "layout_ok=1",
        "wait_for_render_logs(timeout)",
        "verify_ally_hud_name_layout(ally_hud_line)",
        "ally HUD name overlaps its health bar",
        "ally HUD name extends outside its reserved label slot",
        "reversed(log_text.splitlines())",
        "capture_game_backbuffer(",
    )
    missing_verifier = [
        token for token in required_verifier_tokens if token not in verifier_text
    ]
    if missing_verifier:
        raise StaticReTestFailure(
            "three-player name/health-bar regression verifier is incomplete: " +
            ", ".join(missing_verifier))

    required_steam_verifier_tokens = (
        "suspend_runtime_test_godmode(",
        "restore_runtime_test_godmode(",
        "_G.__sdmod_steam_test_godmode_enabled = false",
        "verify_dx9_nameplate_health_bar_geometry(",
        "attachment_visual_type",
        "attachment_visual_address",
    )
    missing_steam_verifier = [
        token
        for token in required_steam_verifier_tokens
        if token not in steam_verifier_text
    ]
    if missing_steam_verifier:
        raise StaticReTestFailure(
            "Steam friend name/health-bar regression verifier is incomplete: "
            + ", ".join(missing_steam_verifier)
        )

    required_physical_resolution_tokens = (
        "def verify_capture_resolution_contract(",
        'parser.add_argument("--require-distinct-resolutions", action="store_true")',
        'resolutions["host"] != resolutions["client"]',
        "participant name/health geometry escaped its",
        "VIEWPORT_EDGE_EXERCISE_DISTANCE = 24.0",
        "edge_contained_health_bars",
        "did not exercise a participant",
        'output["resolution_contract"] = verify_capture_resolution_contract(',
        "wait_for_local_transform_settled(",
        '"host_settled": list(host_target)',
        '"client_settled": list(client_target)',
        "suspend_runtime_test_godmode(",
        "restore_runtime_test_godmode(",
        "client_godmode_before = suspend_runtime_test_godmode(",
    )
    missing_physical_resolution = [
        token
        for token in required_physical_resolution_tokens
        if token not in physical_steam_verifier_text
    ]
    if missing_physical_resolution:
        raise StaticReTestFailure(
            "physical Steam cross-resolution verifier is incomplete: "
            + ", ".join(missing_physical_resolution)
        )

    return "remote names, DX9 health bars, and ally names render through the native PlayerWizard and ally-HUD passes"


def test_memory_region_cache_refreshes_newly_committed_native_objects() -> str:
    text = MEMORY_ACCESS_REGIONS.read_text(encoding="utf-8")
    required_tokens = (
        "if (!has_required_access(region))",
        "RefreshRegion(current, &region)",
        "if (!is_executable(region))",
        "formerly reserved range",
    )
    missing = [token for token in required_tokens if token not in text]
    if missing:
        raise StaticReTestFailure(
            "memory-region cache can reject newly committed native objects: "
            + ", ".join(missing)
        )

    stale_short_circuits = (
        "if (!region.committed || region.guarded || region.no_access) {\n"
        "            return false;",
        "if (!region.committed || region.guarded || region.no_access || !region.executable) {\n"
        "            return false;",
    )
    present = [token for token in stale_short_circuits if token in text]
    if present:
        raise StaticReTestFailure(
            "memory-region access still trusts an inaccessible cached reservation"
        )

    return "inaccessible cached reservations are refreshed after native heap/page commits"


def test_write_watches_are_transparent_to_loader_memory_access() -> str:
    memory_header = MEMORY_ACCESS_HEADER.read_text(encoding="utf-8")
    memory_regions = MEMORY_ACCESS_REGIONS.read_text(encoding="utf-8")
    debug_core = RUNTIME_DEBUG_CORE.read_text(encoding="utf-8")
    registration = RUNTIME_DEBUG_WATCH_REGISTRATION.read_text(encoding="utf-8")
    management = RUNTIME_DEBUG_WATCH_MANAGEMENT.read_text(encoding="utf-8")
    shutdown = RUNTIME_DEBUG_WATCH.read_text(encoding="utf-8")
    handler = RUNTIME_DEBUG_WATCH_HELPERS.read_text(encoding="utf-8")

    required_by_source = {
        "memory_access.h": (
            "RegisterManagedGuardRange",
            "UnregisterManagedGuardRange",
            "IsManagedGuardRange",
            "managed_guard_ranges_",
        ),
        "memory_access_regions.cpp": (
            "candidate.guarded && !IsManagedGuardRange(current, candidate_size)",
            "(!candidate.guarded || IsManagedGuardRange(current, candidate_size))",
        ),
        "runtime_debug_core.cpp": (
            "ProcessMemory::Instance().InvalidateRange(page_base, page_size)",
        ),
        "runtime_debug_watch_registration.cpp": (
            "RegisterManagedGuardRange(",
            "UnregisterManagedGuardRange(",
        ),
        "runtime_debug_watch_management.cpp": ("UnregisterManagedGuardRange(",),
        "runtime_debug_watch.cpp": ("UnregisterManagedGuardRange(",),
    }
    source_text = {
        "memory_access.h": memory_header,
        "memory_access_regions.cpp": memory_regions,
        "runtime_debug_core.cpp": debug_core,
        "runtime_debug_watch_registration.cpp": registration,
        "runtime_debug_watch_management.cpp": management,
        "runtime_debug_watch.cpp": shutdown,
    }
    missing = [
        f"{source}:{token}"
        for source, tokens in required_by_source.items()
        for token in tokens
        if token not in source_text[source]
    ]
    if missing:
        raise StaticReTestFailure(
            "write-watch guard transparency is incomplete: " + ", ".join(missing)
        )

    capture_position = handler.find("after_bytes_by_hit.reserve(hits_to_log.size())")
    rearm_position = handler.find("page.base_protect | PAGE_GUARD", capture_position)
    log_position = handler.find(
        "LogWriteWatchHit(hits_to_log[index], after_bytes_by_hit[index])",
        capture_position,
    )
    if capture_position == -1 or rearm_position == -1 or log_position == -1:
        raise StaticReTestFailure("write-watch post-write capture sequence was not found")
    capture_read_position = handler.find("ProcessMemory::Instance().TryRead(", capture_position)
    if capture_read_position == -1 or not (
        capture_position < capture_read_position < rearm_position < log_position
    ):
        raise StaticReTestFailure(
            "write-watch post-write bytes must be captured before PAGE_GUARD is rearmed"
        )

    return "managed PAGE_GUARD watches remain transparent to loader and Lua memory access"


def test_player_control_brain_requires_published_gameplay_slot() -> str:
    player_control_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/player_control_hooks.inl"
    )
    required_tokens = (
        "IsPlayerActorPublishedInCurrentGameplaySlot(",
        "kActorSlotOffset",
        "kGameplayPlayerSlotCount",
        "TryResolveCurrentGameplayScene(&live_gameplay_address)",
        "TryResolvePlayerActorForSlot(",
        "return live_published_actor_address == actor_address;",
        "control_brain skipped unpublished player actor during scene transition",
        "s_logged_unpublished_actor.exchange(true",
    )
    missing = [token for token in required_tokens if token not in player_control_text]
    if missing:
        raise StaticReTestFailure(
            "player control-brain scene-transition gate is missing token(s): " +
            ", ".join(missing))

    hook_start = player_control_text.find("void __fastcall HookPlayerControlBrainUpdate(")
    hook_end = player_control_text.find(
        "bool IsActorCurrentLocalPlayerSlotZero(", hook_start)
    if hook_start == -1 or hook_end == -1:
        raise StaticReTestFailure("player control-brain hook body was not found")
    hook_body = player_control_text[hook_start:hook_end]
    publication_guard = hook_body.find(
        "if (!IsPlayerActorPublishedInCurrentGameplaySlot(")
    stock_call = hook_body.find("original(self, param2, param3);")
    if publication_guard == -1 or stock_call == -1 or publication_guard > stock_call:
        raise StaticReTestFailure(
            "player slot publication must be validated before stock control-brain execution")

    if player_control_text.count(
            "static std::atomic<bool> s_logged_unpublished_actor") != 1:
        raise StaticReTestFailure(
            "unpublished player-actor logging must have one process-wide gate")

    guard_end = hook_body.find("\n    }", publication_guard)
    if guard_end == -1 or "return;" not in hook_body[publication_guard:guard_end]:
        raise StaticReTestFailure(
            "unpublished player actors must not reach the stock control-brain routine")

    return "player control-brain skips actors until the current gameplay slot table owns them"


def test_client_run_switch_requires_fresh_authenticated_host_intent() -> str:
    transport_header_text = read_text(
        ROOT / "SolomonDarkModLoader/include/multiplayer_local_transport.h"
    )
    transport_text = read_multiplayer_transport_source()
    public_api_text = read_text(
        ROOT / "SolomonDarkModLoader/src/multiplayer_local_transport/public_cast_loot_api.inl"
    )
    lifecycle_hook_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_actor_lifecycle_hooks.inl"
    )
    arena_hook_text = read_text(
        ROOT / "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks.inl"
    )
    lifecycle_state_text = read_text(
        ROOT / "SolomonDarkModLoader/src/run_lifecycle/state_and_targets.inl"
    )
    lifecycle_install_text = read_text(
        ROOT / "SolomonDarkModLoader/src/run_lifecycle/public_api_and_install.inl"
    )
    seam_binding_text = read_text(
        ROOT / "SolomonDarkModLoader/src/gameplay_seams/state_and_address_bindings.inl"
    )
    binary_layout_text = read_text(ROOT / "config/binary-layout.ini")
    run_seed_api_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_gameplay_action_queues.inl"
    )
    run_seed_helpers_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/run_generation_seed_helpers.inl"
    )
    run_reset_text = read_text(
        ROOT / "SolomonDarkModLoader/src/run_lifecycle/enemy_tracking_and_reset.inl"
    )
    active_pair_driver_text = read_text(
        ROOT / "tools/drive_steam_friend_active_pair.py"
    )

    required_pairs = (
        (transport_header_text, "TryAuthorizeLocalClientRunSwitch(std::string* error_message)"),
        (transport_text, "struct ClientHostRunAuthorization"),
        (transport_text, "kClientHostRunAuthorizationFreshnessMs = 3000"),
        (transport_text, "IsAuthoritativeHostParticipantPacket(packet, from)"),
        (transport_text, "Multiplayer cached authenticated host run intent"),
        (public_api_text, "bool TryAuthorizeLocalClientRunSwitch(std::string* error_message)"),
        (public_api_text, "No fresh authenticated host run intent is available."),
        (public_api_text, "authorization.run_nonce == 0"),
        (public_api_text, "SetPendingRunGenerationSeed(authorization.run_nonce"),
        (lifecycle_hook_text, "multiplayer::TryAuthorizeLocalClientRunSwitch(&authorization_error)"),
        (lifecycle_hook_text, "Authorized client run switch_region from fresh authenticated host intent."),
        (arena_hook_text, 'PrepareMultiplayerRunStart("arena_create")'),
        (arena_hook_text, 'PrepareMultiplayerRunStart("start_game")'),
        (arena_hook_text, "HookMainMenuControlAction"),
        (arena_hook_text, "void* /*unused_edx*/, void* control"),
        (arena_hook_text, "kMainMenuModeOffset = 0x3FC"),
        (arena_hook_text, "kMainMenuSavedRunMode = 1"),
        (arena_hook_text, "kMainMenuLastGameControlOffset = 0x78"),
        (arena_hook_text, "kMainMenuNewGameControlOffset = 0x12C"),
        (arena_hook_text, "TryPrepareMainMenuNewGameSaveReset(owner_address, &save_reset_error)"),
        (arena_hook_text, "multiplayer::IsLocalTransportClient() ||"),
        (arena_hook_text, "multiplayer::IsLocalTransportHost()"),
        (arena_hook_text, "dispatched_control = reinterpret_cast<void*>(owner_address + kMainMenuNewGameControlOffset)"),
        (arena_hook_text, "Redirected connected multiplayer Last Game control activation"),
        (arena_hook_text, "the native New Game control path."),
        (arena_hook_text, "Blocked multiplayer run start without a host-authoritative run seed."),
        (lifecycle_state_text, "MainMenuControlActionFn = void(__thiscall*)(void* self, void* control)"),
        (lifecycle_state_text, "kHookMainMenuControlAction"),
        (lifecycle_state_text, "{kMainMenuControlAction, 7}"),
        (lifecycle_install_text, "reinterpret_cast<void*>(&HookMainMenuControlAction)"),
        (seam_binding_text, '"main_menu_control_action", kMainMenuControlAction'),
        (binary_layout_text, "main_menu_control_action=0x0058E600"),
        (active_pair_driver_text, 'action = ("main_menu.new_game", "main_menu")'),
        (active_pair_driver_text, 'action = ("main_menu.resume_last_game", "main_menu")'),
        (active_pair_driver_text, 'parser.add_argument("--exercise-last-game-redirect", action="store_true")'),
        (run_seed_api_text, "bool PrepareArenaRunGenerationSeed(const char* source"),
        (run_seed_api_text, "applied_run_generation_seed.load("),
        (run_seed_api_text, "ApplyPendingRunGenerationSeedForSceneSwitch("),
        (run_seed_helpers_text, "applied_run_generation_seed.store("),
        (run_seed_helpers_text, "local->runtime.run_nonce != 0"),
        (run_reset_text, "ClearLocalRunGenerationSeed();"),
    )
    missing = [token for text, token in required_pairs if token not in text]
    if missing:
        raise StaticReTestFailure(
            "authenticated client run-transition contract is missing token(s): " +
            ", ".join(missing))

    if "ignored host run intent outside hub" in transport_text:
        raise StaticReTestFailure(
            "host run intent still floods once per state packet during a client transition")

    maybe_start = transport_text.find("void MaybeQueueClientHostRunStart(")
    maybe_end = transport_text.find("void ApplyRemoteStatePacket(", maybe_start)
    maybe_body = transport_text[maybe_start:maybe_end]
    authority_check = maybe_body.find("IsAuthoritativeHostParticipantPacket(packet, from)")
    authorization_write = maybe_body.find("g_client_host_run_authorization.valid = true;")
    if (
        maybe_start == -1 or maybe_end == -1 or authority_check == -1 or
        authorization_write == -1 or authority_check > authorization_write
    ):
        raise StaticReTestFailure(
            "host ownership must be validated before caching client run authorization")

    main_menu_hook_start = arena_hook_text.find("void __fastcall HookMainMenuControlAction(")
    main_menu_hook_end = arena_hook_text.find("\n}", main_menu_hook_start)
    main_menu_hook_body = arena_hook_text[main_menu_hook_start:main_menu_hook_end]
    last_game_match = main_menu_hook_body.find(
        "reinterpret_cast<uintptr_t>(control) == owner_address + kMainMenuLastGameControlOffset")
    native_new_game_redirect = main_menu_hook_body.find(
        "dispatched_control = reinterpret_cast<void*>(owner_address + kMainMenuNewGameControlOffset)")
    save_reset = main_menu_hook_body.find(
        "TryPrepareMainMenuNewGameSaveReset(owner_address, &save_reset_error)")
    stock_control_action = main_menu_hook_body.find("original(self, dispatched_control);")
    if (
        main_menu_hook_start == -1 or main_menu_hook_end == -1 or
        last_game_match == -1 or save_reset == -1 or native_new_game_redirect == -1 or
        stock_control_action == -1 or
        last_game_match > save_reset or save_reset > native_new_game_redirect or
        native_new_game_redirect > stock_control_action
    ):
        raise StaticReTestFailure(
            "connected Last Game must substitute the native New Game control before "
            "dispatching the stock MainMenu handler")
    if "PrepareMultiplayerRunStart" in main_menu_hook_body:
        raise StaticReTestFailure(
            "main-menu New Game/character creation must not require a host run nonce")
    forbidden_late_redirect_tokens = (
        "MainMenuRunTransition",
        "main_menu_run_transition",
        "kMainMenuTransitionKindOffset",
        "kMainMenuNewGameTransition",
        "kMainMenuLastGameTransition",
    )
    combined_lifecycle_text = (
        arena_hook_text + lifecycle_state_text + lifecycle_install_text +
        seam_binding_text + binary_layout_text
    )
    stale_redirects = [
        token for token in forbidden_late_redirect_tokens
        if token in combined_lifecycle_text
    ]
    if stale_redirects:
        raise StaticReTestFailure(
            "late MainMenu transition-kind rewrite was not fully removed: " +
            ", ".join(stale_redirects))
    redirect_opt_in = active_pair_driver_text.find("if exercise_last_game_redirect:")
    resume_dispatch = active_pair_driver_text.find(
        'action = ("main_menu.resume_last_game", "main_menu")', redirect_opt_in)
    normal_new_game_dispatch = active_pair_driver_text.find(
        'action = ("main_menu.new_game", "main_menu")', resume_dispatch)
    if not 0 <= redirect_opt_in < resume_dispatch < normal_new_game_dispatch:
        raise StaticReTestFailure(
            "Steam pair onboarding must keep Last Game behind the explicit redirect regression flag")

    hook_start = lifecycle_hook_text.find("void __fastcall HookGameplaySwitchRegion(")
    hook_end = lifecycle_hook_text.find("\n}", hook_start)
    hook_body = lifecycle_hook_text[hook_start:hook_end]
    authorization_check = hook_body.find("TryAuthorizeLocalClientRunSwitch")
    stock_switch = hook_body.find("original(self, region_index);")
    if (
        hook_start == -1 or hook_end == -1 or authorization_check == -1 or
        stock_switch == -1 or authorization_check > stock_switch
    ):
        raise StaticReTestFailure(
            "client arena switch must consume authenticated host authorization before stock dispatch")

    return "connected Last Game redirects at the native control boundary while automation selects New Game directly"


def test_wine_stage_savegames_uses_directory_mirror() -> str:
    stage_links_text = read_text(
        ROOT / "SolomonDarkModLauncher/src/Staging/StageSandboxCompatibilityLinks.cs"
    )
    required_tokens = (
        "if (IsWineRuntime())",
        "RecreateDirectoryMirror(linkPath, targetPath);",
        'Environment.GetEnvironmentVariable("WINEPREFIX")',
        'var malformedWineJunctionPath = directoryPath + "?";',
        "DeleteExistingPath(malformedWineJunctionPath);",
        "CopyDirectoryContents(sourcePath, directoryPath);",
    )
    missing = [token for token in required_tokens if token not in stage_links_text]
    if missing:
        raise StaticReTestFailure(
            "Wine savegames materialization is missing token(s): " +
            ", ".join(missing))
    return "Wine/Proton stages a real savegames directory and removes malformed junction residue"


def test_wsl_steam_launcher_applies_test_boneyard_before_process_start() -> str:
    launch_text = read_text(ROOT / "scripts/Launch-WslSteamMultiplayerClient.sh")
    required_tokens = (
        'test_boneyard_override="${SDMOD_TEST_SURVIVAL_BONEYARD_OVERRIDE:-}"',
        '[[ -f "$test_boneyard_override" ]]',
        '"SDMOD_TEST_SURVIVAL_BONEYARD_OVERRIDE=$(proton_path "$test_boneyard_override")"',
        'test_environment+=("SDMOD_TEST_BLANK_BONEYARD=1")',
        '"${test_environment[@]}"',
    )
    missing = [token for token in required_tokens if token not in launch_text]
    if missing:
        raise StaticReTestFailure(
            "WSL Steam test Boneyard launch contract is missing token(s): "
            + ", ".join(missing)
        )
    staging_environment = launch_text.find('"${test_environment[@]}"')
    proton_process = launch_text.find('"$proton" run "${args[@]}"')
    if staging_environment == -1 or proton_process == -1 or staging_environment > proton_process:
        raise StaticReTestFailure(
            "WSL Steam test Boneyard environment must be applied before Proton starts"
        )
    return "WSL Steam applies translated flat-Boneyard test inputs before Proton starts"


def test_wsl_steam_launcher_isolates_build_artifacts_from_live_host() -> str:
    launch_text = read_text(ROOT / "scripts/Launch-WslSteamMultiplayerClient.sh")
    required_tokens = (
        'build_artifacts="$root/runtime/wsl-steam-build-artifacts"',
        'mkdir -p "$build_artifacts"',
        '--artifacts-path "$build_artifacts"',
    )
    missing = [token for token in required_tokens if token not in launch_text]
    if missing:
        raise StaticReTestFailure(
            "WSL Steam launcher build can overwrite a live Windows host artifact: "
            + ", ".join(missing)
        )
    return "WSL Steam builds into isolated artifacts while the Windows host DLL is mapped"


def test_remote_progression_preserves_local_concentration_context() -> str:
    gameplay_api_text = read_text(
        ROOT / "SolomonDarkModLoader/include/mod_loader_gameplay_api.inl"
    )
    concentration_api_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_debug_and_spawn.inl"
    )
    skill_choices_text = read_source_unit(
        ROOT / "SolomonDarkModLoader/src/bot_runtime/public_api/skill_choices_api.inl"
    )

    required_pairs = (
        (gameplay_api_text, "bool RunWithParticipantConcentrationContext("),
        (concentration_api_text, "ScopedParticipantConcentrationContext context(binding);"),
        (concentration_api_text, "const bool operation_succeeded = operation();"),
        (concentration_api_text, "context.Restore();"),
        (concentration_api_text, "if (!context.restored)"),
    )
    missing = [token for text, token in required_pairs if token not in text]
    if missing:
        raise StaticReTestFailure(
            "remote progression Concentrate isolation is missing token(s): " +
            ", ".join(missing))

    protected_operations = (
        (
            "bool SyncParticipantProgressionToSharedLevelUp(",
            "bool SyncParticipantProgressionToSharedLevelUpAndRollChoices(",
            "SyncNativeBotProgressionLevel(",
        ),
        (
            "bool ApplyParticipantSkillChoiceOption(",
            "bool ApplyLocalPlayerSkillChoiceOption(",
            "ApplyNativeSkillChoiceToProgression(",
        ),
    )
    for start_token, end_token, native_call in protected_operations:
        start = skill_choices_text.find(start_token)
        end = skill_choices_text.find(end_token, start)
        body = skill_choices_text[start:end]
        context_call = body.find("RunWithParticipantConcentrationContext(")
        operation_call = body.find(native_call)
        if (
            start == -1 or end == -1 or context_call == -1 or
            operation_call == -1 or context_call > operation_call
        ):
            raise StaticReTestFailure(
                f"{start_token} does not protect {native_call} with participant Concentrate context")

    context_start = concentration_api_text.find(
        "bool RunWithParticipantConcentrationContext(")
    context_end = concentration_api_text.find(
        "bool TryReconcileParticipantConcentrationRuntimeSelections(",
        context_start,
    )
    context_body = concentration_api_text[context_start:context_end]
    install = context_body.find("ScopedParticipantConcentrationContext context(binding);")
    operation = context_body.find("operation();")
    restore = context_body.find("context.Restore();")
    if (
        context_start == -1 or context_end == -1 or install == -1 or
        operation == -1 or restore == -1 or not install < operation < restore
    ):
        raise StaticReTestFailure(
            "participant Concentrate guard must install, invoke, and restore in that order")

    return "remote native level and skill mutations restore the local player's Concentrate lanes"


def test_remote_progression_uses_passive_authoritative_hydration() -> str:
    native_sync_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/multiplayer_local_transport/native_progression_sync.inl"
    )
    level_handlers_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/multiplayer_local_transport/level_up_packet_handlers.inl"
    )
    barrier_authority_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/multiplayer_local_transport/level_up_barrier_authority.inl"
    )
    powerup_authority_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/multiplayer_local_transport/powerup_loot_authority.inl"
    )
    loot_result_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/multiplayer_local_transport/loot_pickup_packet_handlers.inl"
    )

    required_pairs = (
        (native_sync_text, "bool HydrateAuthoritativeRemoteProgressionEntryState("),
        (native_sync_text, "participant_id == g_local_transport.local_peer_id"),
        (native_sync_text, "kStandaloneWizardProgressionActiveFlagOffset,"),
        (native_sync_text, "kStandaloneWizardProgressionVisibleFlagOffset,"),
        (native_sync_text, "verified.active != resulting_active"),
        (native_sync_text, "verified.visible != resulting_visible"),
        (native_sync_text, "kNativeProgressionReconcileMaxEntryWritesPerTick"),
        (native_sync_text, "desired.active,\n                            desired.visible,"),
        (native_sync_text, "TryReconcileParticipantConcentrationRuntimeSelections("),
        (level_handlers_text, "ApplyAuthoritativeRemoteSkillRankDelta("),
        (
            level_handlers_text,
            "packet.resulting_active,\n                    1,\n                    &error_message",
        ),
        (barrier_authority_text, "ApplyAuthoritativeRemoteSkillRankDelta("),
        (
            powerup_authority_text,
            "pending->powerup.skill_rank_resulting_active,\n                  1,",
        ),
        (
            loot_result_text,
            "packet.powerup_skill_resulting_active,\n                                  1,",
        ),
    )
    missing = [token for text, token in required_pairs if token not in text]
    if missing:
        raise StaticReTestFailure(
            "passive authoritative remote progression hydration is missing token(s): "
            + ", ".join(missing)
        )

    observer_paths = (
        native_sync_text,
        level_handlers_text,
        barrier_authority_text,
        powerup_authority_text,
        loot_result_text,
    )
    if any("ApplyParticipantSkillChoiceOption(" in text for text in observer_paths):
        raise StaticReTestFailure(
            "observer-owned progression must not execute the stock skill-choice path"
        )

    helper_start = native_sync_text.find(
        "bool HydrateAuthoritativeRemoteProgressionEntryState("
    )
    helper_end = native_sync_text.find(
        "bool ApplyAuthoritativeRemoteSkillRankDelta(", helper_start
    )
    helper_body = native_sync_text[helper_start:helper_end]
    forbidden_helper_calls = (
        "ApplyParticipantSkillChoiceOption(",
        "ApplyNativeSkillChoiceToProgression(",
        "CallNativeActorProgressionRefresh(",
        "RefreshParticipantNativeProgression(",
    )
    present = [token for token in forbidden_helper_calls if token in helper_body]
    if helper_start == -1 or helper_end == -1 or present:
        raise StaticReTestFailure(
            "authoritative remote hydration must remain a verified field-only operation: "
            + ", ".join(present)
        )
    if "TryApplyParticipantConcentrationSelections(" in native_sync_text:
        raise StaticReTestFailure(
            "remote progression reconciliation must not invoke stock Concentrate refresh"
        )

    return "remote skillbook, level-up, and powerup state use exact passive hydration without observer-side stock callbacks"


def test_steam_peer_disconnect_resets_remote_session_epoch() -> str:
    lifecycle_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/multiplayer_local_transport/remote_peer_lifecycle.inl"
    )
    public_api_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/multiplayer_local_transport/public_cast_loot_api.inl"
    )
    transport_text = read_text(
        ROOT / "SolomonDarkModLoader/src/multiplayer_local_transport.cpp"
    )
    steam_session_text = read_source_unit(
        ROOT
        / "SolomonDarkModLoader/src/multiplayer_steam_session/lobby_and_events.inl"
    )

    required_pairs = (
        (transport_text, '#include "multiplayer_local_transport/remote_peer_lifecycle.inl"'),
        (public_api_text, "ResetRemoteParticipantSessionEpoch("),
        (lifecycle_text, "QueueParticipantDestroy(participant_id"),
        (lifecycle_text, "last_cast_sequence_by_participant.erase(participant_id)"),
        (
            lifecycle_text,
            "last_spell_effect_packet_sequence_by_participant.erase(\n"
            "        participant_id)",
        ),
        (
            lifecycle_text,
            "last_air_chain_packet_sequence_by_participant.erase(\n"
            "        participant_id)",
        ),
        (
            lifecycle_text,
            "native_progression_reconcile_by_participant.erase(\n"
            "        participant_id)",
        ),
        (lifecycle_text, "issued_level_up_offers_by_id.erase(it)"),
        (lifecycle_text, "state.participants.erase("),
        (lifecycle_text, "state.spell_effect_snapshots.erase("),
        (lifecycle_text, "state.world_snapshot = WorldSnapshotRuntimeInfo{}"),
        (lifecycle_text, "state.loot_snapshot = LootSnapshotRuntimeInfo{}"),
        (
            steam_session_text,
            "if (participant == nullptr && peer.authenticated)",
        ),
        (
            steam_session_text,
            "participant = UpsertRemoteParticipant(",
        ),
    )
    missing = [token for text, token in required_pairs if token not in text]
    if missing:
        raise StaticReTestFailure(
            "Steam reconnect epoch reset is missing token(s): " + ", ".join(missing)
        )

    unregister_start = public_api_text.find("void UnregisterSteamGameplayPeer(")
    unregister_end = public_api_text.find(
        "bool SubmitSteamGameplayPacket(", unregister_start
    )
    unregister_body = public_api_text[unregister_start:unregister_end]
    reset = unregister_body.find("ResetRemoteParticipantSessionEpoch(")
    clear_authority = unregister_body.find(
        "g_local_transport.configured_remote = TransportPeerEndpoint{}"
    )
    if (
        unregister_start == -1
        or unregister_end == -1
        or reset == -1
        or clear_authority == -1
        or reset > clear_authority
    ):
        raise StaticReTestFailure(
            "Steam peer unregister must reset participant-owned state before "
            "clearing the configured authority"
        )
    if "participant->transport_connected = false" in unregister_body:
        raise StaticReTestFailure(
            "Steam disconnect must remove the stale participant epoch, not retain "
            "its monotonic progression revisions"
        )

    return "Steam disconnect destroys the native proxy and removes every participant-owned replication epoch before authenticated re-upsert"


def test_steam_spell_behavior_verifiers_use_real_upgrades_and_wait_for_delivery() -> str:
    behavior_text = read_text(
        ROOT / "tools/verify_steam_friend_active_pair_spell_behavior.py"
    )
    explode_text = read_text(
        ROOT / "tools/verify_multiplayer_fireball_explode_effect_sync.py"
    )

    required_pairs = (
        (behavior_text, 'os.environ.get("SDMOD_STEAM_HOST_INSTANCE", "").strip()'),
        (behavior_text, 'os.environ.get("SDMOD_STEAM_CLIENT_INSTANCE", "").strip()'),
        (behavior_text, "both Steam instance environment variables are required"),
        (behavior_text, "Steam behavior log does not exist"),
        (behavior_text, '"--owners"'),
        (behavior_text, 'if args.owners != "both":'),
        (behavior_text, "def select_matching_owners("),
        (behavior_text, 'output["owner_primary_spells"] = primary_spell_ids'),
        (behavior_text, "for label, owner in fire_owner_labels:"),
        (behavior_text, "for label, owner in air_owner_labels:"),
        (behavior_text, "def ensure_upgrade_rank("),
        (behavior_text, "def owner_context("),
        (behavior_text, "def require_primary_spell("),
        (behavior_text, "FIRE_PRIMARY_SPELL_ID = 1011"),
        (behavior_text, "AIR_PRIMARY_SPELL_ID = 1013"),
        (behavior_text, "rank_setup = ensure_upgrade_rank("),
        (behavior_text, "explode_rank_setup = ensure_upgrade_rank("),
        (behavior_text, "embers_rank_setup = ensure_upgrade_rank("),
        (behavior_text, '"explode": explode_rank_setup'),
        (behavior_text, '"embers": embers_rank_setup'),
        (
            behavior_text,
            'owner_labels = (("host_owned", "host"), ("client_owned", "client"))',
        ),
        (behavior_text, "verify_explode(pair, owner=owner)"),
        (behavior_text, "verify_embers(pair, owner=owner)"),
        (behavior_text, "owner=owner,"),
        (explode_text, "delivery_deadline = time.monotonic() + 8.0"),
        (explode_text, "if receiver_cast_queued and receiver_cast_prepped:"),
        (explode_text, "time.sleep(0.05)"),
    )
    missing = [token for text, token in required_pairs if token not in text]
    if missing:
        raise StaticReTestFailure(
            "Steam spell behavior verification is missing token(s): "
            + ", ".join(missing)
        )
    for stale_default in ("steam-host-gameplay10", "wsl-steam-gameplay10"):
        if stale_default in behavior_text:
            raise StaticReTestFailure(
                "Steam spell behavior verification must not silently read a "
                f"stale default instance log: {stale_default}"
            )

    explode_start = behavior_text.find("def verify_explode(")
    embers_start = behavior_text.find("def verify_embers(", explode_start)
    chaining_start = behavior_text.find("def positive_chaining_evidence(", embers_start)
    explode_body = behavior_text[explode_start:embers_start]
    embers_body = behavior_text[embers_start:chaining_start]
    if (
        explode_start == -1
        or embers_start == -1
        or chaining_start == -1
        or "desired_rank=1" not in explode_body
        or explode_body.find("ensure_upgrade_rank(")
        > explode_body.find("find_upgraded_explode_offset(")
    ):
        raise StaticReTestFailure(
            "Steam Explode verification must acquire rank one authoritatively "
            "before searching upgraded impact geometry"
        )
    first_embers_upgrade = embers_body.find("explode_rank_setup = ensure_upgrade_rank(")
    second_embers_upgrade = embers_body.find("embers_rank_setup = ensure_upgrade_rank(")
    fragment_phase = embers_body.find("run_fragment_phase_with_impact_retry(")
    if not 0 <= first_embers_upgrade < second_embers_upgrade < fragment_phase:
        raise StaticReTestFailure(
            "Steam Embers verification must acquire Explode then Embers through "
            "validated level-up offers before casting"
        )

    source_cast = explode_text.find("post_source_cast =")
    delivery_wait = explode_text.find("delivery_deadline =", source_cast)
    damage_observation = explode_text.find("damage = observe_pair_damage(", delivery_wait)
    if not 0 <= source_cast < delivery_wait < damage_observation:
        raise StaticReTestFailure(
            "Steam Explode verification must wait for receiver cast preparation "
            "between the source cast and damage observation"
        )

    return "Steam spell behavior tests use authoritative prerequisite upgrades and bounded receiver-delivery polling"


def test_steam_combat_stat_profiles_isolate_concentration() -> str:
    verifier_text = read_text(
        ROOT / "tools/verify_steam_friend_active_pair_combat_stats.py"
    )
    context_text = read_text(
        ROOT / "tools/steam_friend_behavior_context.py"
    )
    required_tokens = (
        "PROFILE_SUITES = {",
        '"meditation": ("meditation",)',
        '"faster-caster": ("faster_caster",)',
        '"faster-caster-air": ("faster_caster_air",)',
        "def assert_concentrated_row(",
        "def require_fresh_combat_profile(",
        'output["initial_profile_state"] = require_fresh_combat_profile(pair)',
        "launch a fresh run for each",
        '"owner_process"',
        '"observer_slot"',
        "requires a pristine profile with row",
        'choices=tuple(PROFILE_SUITES)',
        "suites = PROFILE_SUITES[args.profile]",
    )
    missing = [token for token in required_tokens if token not in verifier_text]
    if missing:
        raise StaticReTestFailure(
            "Steam combat-stat profile isolation is missing token(s): "
            + ", ".join(missing)
        )
    context_tokens = (
        "config_root = steam_skill_config_root()",
        "upgrades.load_skill_configs(config_root)",
        "config_root=config_root",
    )
    missing_context = [
        token for token in context_tokens if token not in context_text
    ]
    if missing_context:
        raise StaticReTestFailure(
            "Steam combat-stat behavior reads non-Steam config state: "
            + ", ".join(missing_context)
        )
    if '"--start-at"' in verifier_text:
        raise StaticReTestFailure(
            "Steam combat-stat verification must not resume on a contaminated "
            "monotonic-progression pair"
        )

    general_start = verifier_text.find('"general": (')
    general_end = verifier_text.find('),', general_start)
    general_profile = verifier_text[general_start:general_end]
    ordered_suites = (
        '"transient_status"',
        '"mindstar"',
        '"battle_siege"',
        '"telekinesis"',
        '"focus"',
    )
    positions = [general_profile.find(suite) for suite in ordered_suites]
    if any(position == -1 for position in positions) or positions != sorted(positions):
        raise StaticReTestFailure(
            "the general Steam combat-stat profile must run strict Mindstar before "
            "remote Fireball trials and omit concentration-sensitive suites"
        )
    if (
        '"meditation"' in general_profile
        or '"faster_caster"' in general_profile
        or '"faster_caster_air"' in general_profile
    ):
        raise StaticReTestFailure(
            "Meditation and both Faster Caster modalities require their own "
            "pristine Steam pairs"
        )

    mindstar_text = read_text(
        ROOT / "tools/verify_multiplayer_mindstar_behavior_sync.py"
    )
    mindstar_direction_start = mindstar_text.find("def run_direction(")
    mindstar_direction_end = mindstar_text.find(
        "\ndef main()", mindstar_direction_start
    )
    mindstar_direction = mindstar_text[
        mindstar_direction_start:mindstar_direction_end
    ]
    pre_prime_cleanup = mindstar_direction.find(
        "pre_prime_cleanup = cleanup_live_enemies()"
    )
    spawner_prime = mindstar_direction.find(
        "manual_spawner_prime = enable_manual_stock_spawner_combat()"
    )
    baseline_cast = mindstar_direction.find(
        "baseline_cast = run_fireball_trial("
    )
    if not 0 <= pre_prime_cleanup < spawner_prime < baseline_cast:
        raise StaticReTestFailure(
            "Mindstar must remove the previous owner's targets, establish the "
            "exact stock arena spawner, then begin its manual-target Fireball trial"
        )
    mindstar_damage_tokens = (
        "before_source_cast=lambda: reset_local_cast_observation(",
        "cast_observation = read_local_cast_observation(",
        "def measure_primary_damage_trial(",
        '"method": "single_fire_projectile_authoritative_damage"',
        '"method": "client_air_damage_claim_quantum"',
        'observation["damage_claim_samples"]',
        "authoritative_damage=authoritative_damage",
        "if primary_entry == FIRE_PRIMARY_ENTRY:",
        'damage["primary_damaged"] and not damage["secondary_damaged"]',
        "elif primary_entry == AIR_PRIMARY_ENTRY:",
        'expected_geometry = "selected-target Air damage"',
        "receiver_log_offset = log_position(cast_direction.receiver_log)",
        'float(active_measurement["quantum"])',
        '/ float(baseline_measurement["quantum"])',
    )
    missing_mindstar_damage = [
        token for token in mindstar_damage_tokens if token not in mindstar_text
    ]
    if missing_mindstar_damage:
        raise StaticReTestFailure(
            "Mindstar mixed Fire/Air behavior verification is missing semantic "
            "per-hit measurement token(s): " + ", ".join(missing_mindstar_damage)
        )

    log_probe_text = read_text(ROOT / "tools/multiplayer_log_probe.py")
    spell_cast_text = read_text(ROOT / "tools/verify_spell_cast_sync.py")
    log_probe_tokens = (
        'with path.open("rb") as stream:',
        "stream.seek(offset)",
        "return path.stat().st_size",
        "exc.errno != errno.ENODATA",
        "from multiplayer_log_probe import log_after, log_position, read_log",
    )
    combined_log_text = log_probe_text + "\n" + spell_cast_text
    missing_log_probe = [
        token for token in log_probe_tokens if token not in combined_log_text
    ]
    if missing_log_probe or "len(read_log(direction." in spell_cast_text:
        raise StaticReTestFailure(
            "multiplayer cast evidence must use byte-positioned cross-variant "
            "log reads: " + ", ".join(missing_log_probe)
        )
    for behavior_path in (
        ROOT / "tools/verify_multiplayer_focus_behavior_sync.py",
        ROOT / "tools/verify_multiplayer_meditation_behavior_sync.py",
        ROOT / "tools/verify_multiplayer_faster_caster_behavior_sync.py",
    ):
        behavior_log_text = read_text(behavior_path)
        if "len(read_log(direction." in behavior_log_text:
            raise StaticReTestFailure(
                f"{behavior_path.name} retained character-positioned log offsets"
            )
        if "log_position(direction." not in behavior_log_text:
            raise StaticReTestFailure(
                f"{behavior_path.name} does not use byte-positioned log offsets"
            )
    faster_caster_text = read_text(
        ROOT / "tools/verify_multiplayer_faster_caster_behavior_sync.py"
    )
    faster_claim_tokens = (
        "CONTINUOUS_PRIMARY_ENTRIES = frozenset((AIR_PRIMARY_ENTRY,))",
        "if direction.source_pipe == CLIENT_PIPE:",
        'observation["damage_associated_skill_id"] != primary_entry',
        'f"{direction.name} continuous Air damage claims were not "',
    )
    missing_faster_claims = [
        token for token in faster_claim_tokens if token not in faster_caster_text
    ]
    if missing_faster_claims:
        raise StaticReTestFailure(
            "continuous Faster Caster must stay scoped to its exact Air claim path: "
            + ", ".join(missing_faster_claims)
        )

    all_stats_text = read_text(ROOT / "tools/verify_multiplayer_all_stat_sync.py")
    steam_progression_text = read_text(
        ROOT / "tools/verify_steam_friend_active_pair_progression.py"
    )
    mana_probe_tokens = (
        "def query_mana_observation(",
        "def set_runtime_test_godmode_enabled(",
        "previous_godmode = set_runtime_test_godmode_enabled(target_pipe, False)",
        "return _sample_mana_recovery_while_godmode_suspended(target_id, duration)",
        "finally:\n        set_runtime_test_godmode_enabled(target_pipe, previous_godmode)",
        "local runtime_before = tonumber(before and before.mana_current) or -1",
        "local native = progression ~= 0 and sd.debug.read_float(",
        "local runtime_after = tonumber(after and after.mana_current) or -1",
        "def distance_from_runtime_bracket(",
        "def distance_from_runtime_replication_window(",
        '"owner_runtime_bracket_error": distance_from_runtime_bracket(owner)',
        '"observer_runtime_bracket_error": distance_from_runtime_bracket(',
        '"owner_runtime_window_error": owner_runtime_window_error',
        '"observer_runtime_window_error": observer_runtime_window_error',
        "previous_owner_observation: dict[str, float] | None = owner",
        "previous_observer_observation: dict[str, float] | None = observer",
        'precondition_mp = float(before["native"]["mp"])',
        "settle_ceiling = max(5.0, min(100.0, precondition_mp * 0.5))",
        'float(sample["observer_runtime_window_error"])',
        "owner_gain / sampled_duration",
        "replication_tolerance = max(1.0, observed_rate * 1.1)",
        "stable_set_result = set_local_mana(target_pipe, stable_target)",
        "stable_deadline = time.monotonic() + 2.0",
        '"observer_native_mp": stable_observer["native"]',
        '"observer_runtime_before_mp": stable_observer["runtime_before"]',
        '"observer_runtime_after_mp": stable_observer["runtime_after"]',
    )
    missing_mana_probe = [
        token for token in mana_probe_tokens if token not in all_stats_text
    ]
    if missing_mana_probe:
        raise StaticReTestFailure(
            "live mana recovery must use adjacent runtime/native/runtime samples: "
            + ", ".join(missing_mana_probe)
        )
    stat_finalize_tokens = (
        "def run_stats_finalize_phase(",
        'choices=("catalog", "upgrades", "stats", "stats-finalize")',
        '"--resume-output"',
        'completed_step_count != len(steps)',
        'for direction in ("host_owned", "client_owned")',
        'output["final"] = stats.verify_final_maxima(',
        'output["final_ranked_property_matrix"]',
        'output["final_mana_recovery"]',
        'final_gain <= baseline_gain + 0.5',
    )
    missing_stat_finalize = [
        token for token in stat_finalize_tokens if token not in steam_progression_text
    ]
    if missing_stat_finalize:
        raise StaticReTestFailure(
            "Steam stat finalization must validate a complete matrix before "
            "measuring max-rank behavior: " + ", ".join(missing_stat_finalize)
        )

    mindstar_semantic_tokens = (
        "def compact_native_output_buffer(",
        '"semantic_exact_match": True',
        '"native_output_buffer_diagnostic": {',
        'stable_shape_fields = (\n        "progression_level",',
        '"count": spell["raw_output_count"]',
        '"outputs": spell["raw_outputs"]',
        '"mana_spend_cost_available": spell["mana_spend_cost_available"]',
        '"builder_seh_code": spell["builder_seh_code"]',
        "def ensure_mindstar_inactive(",
        "finally:\n        deactivated = ensure_mindstar_inactive(",
        "finally:\n        final_deactivated = ensure_mindstar_inactive(",
    )
    missing_mindstar_semantics = [
        token for token in mindstar_semantic_tokens if token not in mindstar_text
    ]
    if missing_mindstar_semantics:
        raise StaticReTestFailure(
            "Mindstar must compare semantic spell state and retain the stock "
            "high-water output buffer only as diagnostics: "
            + ", ".join(missing_mindstar_semantics)
        )

    transient_status_text = read_text(
        ROOT / "tools/verify_multiplayer_transient_status_sync.py"
    )
    transient_timing_tokens = (
        "POISON_REPLICATION_MAX_TICK_DRIFT * POISON_DAMAGE_PER_TICK",
        "last_owner_before_observer = query_poison_status(direction.owner_pipe)",
        '>= last_owner["hp"] - POISON_HP_QUANTIZATION_TOLERANCE',
        '<= last_owner_before_observer["hp"] + maximum_hp_drift',
        "maximum_tick_drift=POISON_REPLICATION_MAX_TICK_DRIFT",
        "def wait_for_observer_duration_advance(",
        'last["modifier_ticks"] < active_modifier_ticks',
        "duration_drift <= POISON_REPLICATION_MAX_TICK_DRIFT",
        "2 * POISON_REPLICATION_MAX_TICK_DRIFT",
        "owner_ticks > injected_ticks",
        "injected_ticks - owner_ticks > POISON_OWNER_CORRECTION_MAX_TICK_DRIFT",
    )
    missing_transient_timing = [
        token for token in transient_timing_tokens if token not in transient_status_text
    ]
    if missing_transient_timing:
        raise StaticReTestFailure(
            "transient poison HP parity must use bracketed samples and the same "
            "native-tick drift bound as duration replication: "
            + ", ".join(missing_transient_timing)
        )
    invalid_post_observer_hp_comparison = (
        'abs(last_observer["hp"] - last_owner["hp"]) <= maximum_hp_drift'
    )
    if invalid_post_observer_hp_comparison in transient_status_text:
        raise StaticReTestFailure(
            "transient poison HP parity must not compare an observer sample "
            "to a later owner sample without accounting for owner damage "
            "during the probe interval"
        )
    compact_start = mindstar_text.find("def compact_spell(")
    compact_end = mindstar_text.find(
        "\ndef compact_native_output_buffer(", compact_start
    )
    compact_spell = mindstar_text[compact_start:compact_end]
    forbidden_compact_fields = (
        'spell["raw_output_count"]',
        'spell["raw_outputs"]',
    )
    present_compact_fields = [
        field for field in forbidden_compact_fields if field in compact_spell
    ]
    if present_compact_fields:
        raise StaticReTestFailure(
            "Mindstar semantic parity must not treat the stock grow-only output "
            "buffer as replicated progression state: "
            + ", ".join(present_compact_fields)
        )

    battle_siege_text = read_text(
        ROOT / "tools/verify_multiplayer_battle_siege_behavior_sync.py"
    )
    battle_siege_tokens = (
        "def reset_local_cast_observation(",
        "sd.debug.reset_local_cast_observation(",
        "def read_local_cast_observation(",
        "sd.debug.get_local_cast_observation(",
        "def estimate_fundamental_damage_quantum(",
        "    wait_for_cast_runtime_ready,",
        '"mana_spent_total"',
        '"client_air_damage_claim_quantum"',
        "authoritative_damage=damage",
        '"single_fire_projectile_authoritative_damage"',
        '"host_primary_entry"] == FIRE_PRIMARY_ENTRY',
        '"client_primary_entry"] == AIR_PRIMARY_ENTRY',
        'expected_battle_ratio = (',
        'actual_battle_ratio = battle_trial["mana_spend"] / base["mana_spend"]',
        'expected_siege_ratio = (',
        'siege_trial["native_damage_quantum"]',
        '/ base["native_damage_quantum"]',
        'for field in ("battle_actual_mana_ratio", "siege_actual_damage_ratio")',
    )
    missing_battle_siege = [
        token for token in battle_siege_tokens if token not in battle_siege_text
    ]
    if missing_battle_siege:
        raise StaticReTestFailure(
            "mixed-element Battle/Siege behavior verification is missing token(s): "
            + ", ".join(missing_battle_siege)
        )
    forbidden_battle_siege_tokens = (
        "sd.debug.watch_write(",
        "sd.debug.get_write_hits(",
        "sd.events.on('runtime.tick'",
        "arm_mana_write_watch",
        "arm_damage_write_watch",
        "native_damage_per_write",
    )
    present_forbidden = [
        token
        for token in forbidden_battle_siege_tokens
        if token in battle_siege_text
    ]
    if present_forbidden:
        raise StaticReTestFailure(
            "Battle/Siege must use bounded semantic cast observations, not hot-page "
            "write watches or net resource sampling: "
            + ", ".join(present_forbidden)
        )
    cast_trial_start = battle_siege_text.find("def run_cast_trial(")
    cast_trial_end = battle_siege_text.find(
        "\ndef verify_behavior_contracts(", cast_trial_start
    )
    cast_trial = battle_siege_text[cast_trial_start:cast_trial_end]
    if cast_trial.count("cast_fireball_pair(") != 1:
        raise StaticReTestFailure(
            "Battle/Siege must measure mana, damage, and replication from one "
            "non-intrusively observed native cast"
        )
    semantic_observation_sources = (
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/player_mana_hooks.inl",
        ROOT
        / "SolomonDarkModLoader/src/multiplayer_local_transport/client_enemy_damage_sync.inl",
        ROOT
        / "SolomonDarkModLoader/src/lua_engine_bindings_debug/functions_combat_observations.inl",
    )
    semantic_observation_text = "\n".join(
        read_text(path) for path in semantic_observation_sources
    )
    semantic_observation_tokens = (
        "g_local_mana_delta_observation_mutex",
        "observation.spent_total -= applied_delta",
        "RecordLocalEnemyDamageClaimObservationInternal(",
        "if (!force_resend)",
        "const bool armed = ResetLocalPlayerManaDeltaObservation();",
        "TakeLocalPlayerManaDeltaObservation(&mana)",
        "multiplayer::ResetLocalEnemyDamageClaimObservation(network_actor_id);",
        "multiplayer::TakeLocalEnemyDamageClaimObservation(",
        "damage.claimed_damage_samples[index]",
    )
    missing_semantic_observation = [
        token
        for token in semantic_observation_tokens
        if token not in semantic_observation_text
    ]
    if missing_semantic_observation:
        raise StaticReTestFailure(
            "bounded semantic Battle/Siege observation is missing token(s): "
            + ", ".join(missing_semantic_observation)
        )

    fireball_cast_text = read_text(
        ROOT / "tools/verify_multiplayer_fireball_explode_effect_sync.py"
    )
    if fireball_cast_text.count(
        'hp=float(pair.get("target_hp", TARGET_HP))'
    ) < 2:
        raise StaticReTestFailure(
            "shared primary-cast fixtures must preserve the requested target HP "
            "through their final stock spatial-index refresh"
        )

    return (
        "Steam combat-stat behavior runs in concentration-safe pristine-pair "
        "profiles, primes the exact stock arena spawner, and measures mixed-element "
        "Battle/Siege behavior through bounded semantic observations and normalized ratios"
    )


def test_semantic_air_damage_quantum_uses_authoritative_total() -> str:
    from verify_multiplayer_battle_siege_behavior_sync import (
        estimate_fundamental_damage_quantum,
    )

    cases = (
        ([0.08] * 20, 1.72, 0.04, 43.0),
        ([0.05] * 20, 1.025, 0.025, 41.0),
    )
    for samples, authoritative_damage, expected_quantum, expected_multiple in cases:
        result = estimate_fundamental_damage_quantum(
            samples,
            authoritative_damage=authoritative_damage,
        )
        if not math.isclose(
            float(result["quantum"]), expected_quantum, abs_tol=1e-9
        ) or not math.isclose(
            float(result["authoritative_multiple"]),
            expected_multiple,
            abs_tol=1e-9,
        ):
            raise StaticReTestFailure(
                "semantic Air damage quantum did not use authoritative HP loss "
                f"to reject bundled half-hit candidates: {result}"
            )
    return "semantic Air damage estimation resolves bundled claims against authoritative HP loss"


def test_mindstar_semantic_spell_projection_ignores_raw_storage_tail() -> str:
    from verify_multiplayer_mindstar_behavior_sync import (
        compact_native_output_buffer,
        compact_spell,
    )

    semantic_spell = {
        "resolved": True,
        "build_skill_id": 0x3F3,
        "current_spell_id": 0x3F3,
        "progression_level": 4,
        "logical_output_count": 2,
        "outputs": [4140.0, 370.0],
        "damage": 4140.0,
        "secondary_damage": 0.0,
        "secondary_damage_available": False,
        "mana_cost": 370.0,
        "mana_cost_available": True,
        "mana_spend_cost": 37.0,
        "mana_spend_cost_available": True,
        "mana_output_scale": 10.0,
        "mana_output_scaled": True,
        "builder_seh_code": 0,
        "error": "",
    }
    owner = {
        "spell": {
            **semantic_spell,
            "raw_output_count": 2,
            "raw_outputs": [4140.0, 370.0],
        }
    }
    observer = {
        "spell": {
            **semantic_spell,
            "raw_output_count": 9,
            "raw_outputs": [4140.0, 370.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        }
    }
    if compact_spell(owner) != compact_spell(observer):
        raise StaticReTestFailure(
            "Mindstar semantic parity still treats a grow-only raw tail as spell state"
        )
    if compact_native_output_buffer(owner) == compact_native_output_buffer(observer):
        raise StaticReTestFailure(
            "Mindstar raw-buffer diagnostics did not preserve the 2-versus-9 repro"
        )

    owner_projection = compact_spell(owner)
    for field, value in owner_projection.items():
        changed = {**semantic_spell}
        if isinstance(value, bool):
            changed[field] = not value
        elif isinstance(value, int):
            changed[field] = value + 1
        elif isinstance(value, float):
            changed[field] = value + 0.5
        else:
            changed[field] = value + "changed"
        changed_view = {
            "spell": {
                **changed,
                "raw_output_count": 9,
                "raw_outputs": observer["spell"]["raw_outputs"],
            }
        }
        if compact_spell(owner) == compact_spell(changed_view):
            raise StaticReTestFailure(
                f"Mindstar semantic projection omitted identity field {field}"
            )
    return (
        "Mindstar ignores grow-only raw output tails while preserving every "
        "resolved spell identity field"
    )


def test_regenerate_behavior_traces_stock_native_heal_updates() -> str:
    verifier_text = read_text(
        ROOT / "tools/verify_multiplayer_regenerate_behavior_sync.py"
    )
    required_tokens = (
        'NATIVE_REGENERATE_HEAL_INSTRUCTION = read_runtime_layout_offset(',
        '"regenerate_heal_instruction"',
        'RUNTIME_FRAME_RATE_GLOBAL = read_runtime_layout_offset(',
        '"game_timing_scale"',
        'PROGRESSION_HEALTH_REGEN_OFFSET = read_runtime_layout_offset(',
        '"progression_health_regeneration"',
        'NATIVE_HEAL_NUMERATOR = 1.5',
        'NATIVE_BASE_HEAL_DIVISOR = 10.0',
        "sd.events.on('runtime.tick', function(event)",
        "sd.debug.trace_function(",
        "sd.debug.get_trace_hits(monitor.trace_name)",
        "tonumber(hit.esi) == progression",
        "base_heal / (frame_rate * monitor.base_heal_divisor)",
        "def ensure_vital_monitor_registered(",
        "def start_vital_monitor(",
        "def collect_vital_monitor(",
        "concurrent.futures.ThreadPoolExecutor(max_workers=2)",
        '"observer": executor.submit(',
        '"owner": executor.submit(',
        '"owner_native_heal_updates"',
        '"owner_heal_per_native_update"',
        '"expected_heal_per_native_update"',
        "OWNER_OBSERVER_HP_ENVELOPE = 1.05",
        "post_active_convergence = wait_for_vitals(",
        '"post_active_convergence": post_active_convergence',
    )
    missing = [token for token in required_tokens if token not in verifier_text]
    if missing:
        raise StaticReTestFailure(
            "Regenerate native-update verification is missing token(s): "
            + ", ".join(missing)
        )
    forbidden_tokens = (
        "EXPECTED_NATIVE_HEAL_PER_SECOND",
        "EXPECTED_NATIVE_HEAL_PER_TICK",
        "fallback_ms",
    )
    present_forbidden = [
        token for token in forbidden_tokens if token in verifier_text
    ]
    if present_forbidden:
        raise StaticReTestFailure(
            "Regenerate verification retained guessed cadence/fallback token(s): "
            + ", ".join(present_forbidden)
        )

    sample_start = verifier_text.find("def sample_vitals_for(")
    sample_end = verifier_text.find(
        "\ndef assert_regenerate_inactive(", sample_start
    )
    sample_body = verifier_text[sample_start:sample_end]
    if (
        sample_start == -1
        or sample_end == -1
        or "query_persistent_status(" in sample_body
    ):
        raise StaticReTestFailure(
            "Regenerate sampling must stay in-process instead of depressing the "
            "game tick rate with repeated cross-process Lua queries"
        )

    return (
        "Regenerate behavior traces the stock heal instruction and validates "
        "each native update against the live frame-rate divisor"
    )


def test_steam_rush_reuses_strict_prepared_matrix() -> str:
    behavior_text = read_text(
        ROOT / "tools/verify_multiplayer_rush_behavior_sync.py"
    )
    steam_text = read_text(
        ROOT / "tools/verify_steam_friend_active_pair_rush.py"
    )
    required_behavior_tokens = (
        "def run_prepared_rush_matrix(",
        'output["real_keyboard_baseline"]',
        'output["real_keyboard_upgraded"]',
        "COMBINED_MAX_SPEED_MULTIPLIER",
        "minimum_ranked_rush_step_ratio",
    )
    required_steam_tokens = (
        "require_shared_test_run(output[\"pair\"])",
        "configure_behavior_context(pair)",
        "rush.load_native_rush_evidence(",
        "real_input_control.windows_process_id(HOST_INSTANCE)",
        "hold_proton_key",
        "resolve_keyboard_drivers()",
        "rush.run_prepared_rush_matrix(",
    )
    missing = [
        token
        for token in required_behavior_tokens
        if token not in behavior_text
    ] + [token for token in required_steam_tokens if token not in steam_text]
    if missing:
        raise StaticReTestFailure(
            "Steam Rush behavior verification is missing token(s): "
            + ", ".join(missing)
        )
    if "launch_pair(" in steam_text or "stop_games(" in steam_text:
        raise StaticReTestFailure(
            "Steam Rush verification must consume the genuine active friend pair "
            "without a local-transport launch or fallback"
        )

    main_start = behavior_text.find("def main() -> int:")
    main_body = behavior_text[main_start:]
    if main_body.count("run_prepared_rush_matrix(") != 1:
        raise StaticReTestFailure(
            "the standalone Rush entry point must call the shared strict matrix "
            "exactly once instead of duplicating its behavior assertions"
        )

    return "Windows/Proton Steam Rush verification reuses the strict native-evidence and real-input matrix"


def test_semantic_ui_actions_dispatch_only_on_app_update_thread() -> str:
    layout_text = read_text(ROOT / "config/binary-layout.ini")
    layout_header_text = read_text(
        ROOT / "SolomonDarkModLoader/include/binary_layout.h"
    )
    layout_parser_text = read_text(
        ROOT / "SolomonDarkModLoader/src/binary_layout_parser.cpp"
    )
    layout_validation_text = read_text(
        ROOT / "SolomonDarkModLoader/src/binary_layout_validation.cpp"
    )
    action_helpers_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/debug_ui_overlay/state_and_actions_helpers.inl"
    )
    request_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/debug_ui_overlay/state_and_actions_requests_and_reset.inl"
    )
    owner_resolution_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/debug_ui_overlay/state_and_actions_surface_owner_resolution.inl"
    )
    tracked_surfaces_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/debug_ui_overlay/tracked_surfaces_and_main_menu.inl"
    )
    overlay_source_text = read_source_unit(
        ROOT / "SolomonDarkModLoader/src/debug_ui_overlay.cpp"
    )
    overlay_frame_text = read_text(DEBUG_UI_OVERLAY_FRAME_RENDER)
    public_actions_text = read_text(
        ROOT / "SolomonDarkModLoader/src/debug_ui_overlay/public_api_actions.inl"
    )
    background_tick_text = read_text(
        ROOT / "SolomonDarkModLoader/src/background_focus_bypass.cpp"
    )
    onboarding_text = read_text(ROOT / "tools/drive_steam_friend_active_pair.py")

    stale_timing_owners = [
        name
        for name, text in (
            ("binary layout", layout_text),
            ("binary layout declarations", layout_header_text),
            ("binary layout parser", layout_parser_text),
            ("binary layout validation", layout_validation_text),
            ("semantic action helpers", action_helpers_text),
            ("semantic action request path", request_text),
        )
        if "dispatch_timing" in text or "ResolveUiActionDispatchTiming" in text
    ]
    if stale_timing_owners:
        raise StaticReTestFailure(
            "semantic UI dispatch still exposes selectable thread ownership in: "
            + ", ".join(stale_timing_owners)
        )

    required_pairs = (
        (request_text, "void DispatchPendingSemanticUiActionRequest()"),
        (
            public_actions_text,
            "DispatchPendingSemanticUiActionRequest();",
        ),
        (background_tick_text, "DispatchPendingDebugUiActionOnAppTick();"),
        (
            request_text,
            "Debug UI overlay dispatched semantic UI action on the app update thread.",
        ),
        (overlay_source_text, "kPendingSemanticUiActionRequestMaximumAgeMs = 3000"),
        (request_text, "request.snapshot_generation = snapshot_generation;"),
        (request_text, "snapshot.generation != request.snapshot_generation"),
        (request_text, "TryCopyUsableDebugUiSurfaceSnapshot(&snapshot)"),
        (public_actions_text, "snapshot->snapshot_generation = pending.snapshot_generation;"),
        (owner_resolution_text, "TryResolveValidatedUiOwnerPointer("),
        (owner_resolution_text, "snapshot_owner_address != validated_owner_address"),
        (owner_resolution_text, "TryGetCurrentSpellPicker(&candidate_owner_address)"),
        (tracked_surfaces_text, "*browser_address = tracked_browser.tracked_object_ptr;"),
        (onboarding_text, "run_entry_dispatched = False"),
        (onboarding_text, "if exercise_last_game_redirect:"),
        (
            onboarding_text,
            'elif "main_menu.new_game" in available:',
        ),
        (onboarding_text, 'host_view.get("scene") == "testrun"'),
        (onboarding_text, 'host_view.get("local.in_run") == "true"'),
        (
            onboarding_text,
            'local_sync.wait_for_scene(CLIENT_ENDPOINT, "testrun", timeout=45.0)',
        ),
        (onboarding_text, '"rejoined_active_run": True'),
    )
    missing = [token for text, token in required_pairs if token not in text]
    if missing:
        raise StaticReTestFailure(
            "app-thread semantic UI dispatch regression is missing token(s): "
            + ", ".join(missing)
        )

    forbidden_render_or_caller_thread_dispatch = (
        "DispatchPendingSemanticUiActionRequest(",
        "TryDispatchSemanticUiActionRequestImmediately",
        '"overlay_frame"',
        '"render thread"',
    )
    stale_render_tokens = [
        token
        for token in forbidden_render_or_caller_thread_dispatch
        if token in overlay_frame_text
        or token == "TryDispatchSemanticUiActionRequestImmediately"
        and token in request_text
    ]
    if stale_render_tokens:
        raise StaticReTestFailure(
            "semantic UI mutation still has a render/caller-thread path: "
            + ", ".join(stale_render_tokens)
        )

    pump = background_tick_text.find("DispatchPendingDebugUiActionOnAppTick();")
    stock_tick = background_tick_text.find("original(app, edx);", pump)
    if pump == -1 or stock_tick == -1 or pump > stock_tick:
        raise StaticReTestFailure(
            "pending update-owned UI actions must run before the stock MyApp update loop"
        )

    new_game_choice = onboarding_text.find(
        'elif "main_menu.new_game" in available:'
    )
    redirect_opt_in = onboarding_text.find("if exercise_last_game_redirect:")
    resume_choice = onboarding_text.find(
        'action = ("main_menu.resume_last_game", "main_menu")', redirect_opt_in
    )
    if not 0 <= redirect_opt_in < resume_choice < new_game_choice:
        raise StaticReTestFailure(
            "connected onboarding must select native New Game by default and isolate Last Game to its regression flag"
        )

    claim = request_text.find(
        "g_debug_ui_overlay_state.pending_semantic_ui_action = "
        "PendingSemanticUiActionRequest{};",
    )
    dispatch_entry = request_text.find("void DispatchPendingSemanticUiActionRequest()")
    if dispatch_entry == -1 or claim == -1 or dispatch_entry > claim:
        raise StaticReTestFailure(
            "the app-thread dispatcher must claim pending semantic UI actions"
        )

    expiry_check = request_text.find(
        "now - request.queued_at > kPendingSemanticUiActionRequestMaximumAgeMs",
        claim,
    )
    generation_check = request_text.find(
        "snapshot.generation != request.snapshot_generation",
        claim,
    )
    if not 0 <= claim < expiry_check < generation_check:
        raise StaticReTestFailure(
            "the app-thread dispatcher must claim, expire, and generation-check every queued UI request"
        )

    forbidden_stale_owner_paths = (
        "*owner_address = snapshot_owner_address",
        "pending_skips_snapshot_match",
    )
    stale_owner_tokens = [
        token
        for token in forbidden_stale_owner_paths
        if token in request_text or token in owner_resolution_text
    ]
    if stale_owner_tokens:
        raise StaticReTestFailure(
            "semantic UI dispatch still contains a stale-observation escape hatch: "
            + ", ".join(stale_owner_tokens)
        )

    return (
        "all semantic UI mutation is queued, generation-bound, expiry-bounded, "
        "and live-owner-validated on the app thread"
    )


def test_main_thread_work_pump_is_not_render_owned() -> str:
    background_tick_text = read_text(
        ROOT / "SolomonDarkModLoader/src/background_focus_bypass.cpp"
    )
    internal_header_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_internal.h"
    )
    public_api_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api.inl"
    )
    public_pump_path = (
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_main_thread_pump.inl"
    )
    if not public_pump_path.exists():
        raise StaticReTestFailure(
            "main-thread gameplay/Lua work needs a public app-tick pump seam"
        )
    public_pump_text = read_text(public_pump_path)
    keyboard_injection_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_keyboard_injection.inl"
    )
    pump_loop_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_pump_loop.inl"
    )
    runtime_request_state_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/core/runtime_request_state.inl"
    )
    player_tick_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/actor_tick/player_actor_tick_hook.inl"
    )
    gameplay_dispatch_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_gameplay_thread_dispatch.inl"
    )
    actor_lifecycle_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_actor_lifecycle_hooks.inl"
    )
    d3d_header_text = read_text(
        ROOT / "SolomonDarkModLoader/include/d3d9_end_scene_hook.h"
    )
    d3d_source_text = read_text(
        ROOT / "SolomonDarkModLoader/src/d3d9_end_scene_hook.cpp"
    )

    required_pairs = (
        (internal_header_text, "void PumpGameplayMainThreadWork();"),
        (
            public_api_text,
            '#include "public_api_main_thread_pump.inl"',
        ),
        (public_pump_text, "void PumpGameplayMainThreadWork()"),
        (public_pump_text, "if (!g_gameplay_keyboard_injection.initialized)"),
        (public_pump_text, "PumpQueuedGameplayActions();"),
        (background_tick_text, "PumpGameplayMainThreadWork();"),
        (pump_loop_text, "AppMainTick and HookPlayerActorTick"),
        (pump_loop_text, "TryResolvePlayerActorForSlot("),
        (pump_loop_text, "&local_player_actor_address"),
        (pump_loop_text, "generation_before == generation_after"),
        (pump_loop_text, "generation_after != previously_observed_generation"),
        (pump_loop_text, "tick_scene_address == active_gameplay_address"),
        (pump_loop_text, "tick_actor_address == local_player_actor_address"),
        (
            pump_loop_text,
            "creation publishes a game object and a slot-zero preview actor",
        ),
        (
            runtime_request_state_text,
            "void PublishLocalPlayerTickOwnership(",
        ),
        (
            runtime_request_state_text,
            "void ClearLocalPlayerTickOwnership()",
        ),
        (
            runtime_request_state_text,
            "void ResetLocalPlayerTickOwnershipState()",
        ),
        (player_tick_text, "PublishLocalPlayerTickOwnership("),
        (gameplay_dispatch_text, "ClearLocalPlayerTickOwnership();"),
        (actor_lifecycle_text, "ClearLocalPlayerTickOwnership();"),
    )
    missing = [token for text, token in required_pairs if token not in text]
    if missing:
        raise StaticReTestFailure(
            "app-tick main-thread work ownership is missing token(s): "
            + ", ".join(missing)
        )

    main_pump = background_tick_text.find("PumpGameplayMainThreadWork();")
    ui_dispatch = background_tick_text.find(
        "DispatchPendingDebugUiActionOnAppTick();",
        main_pump,
    )
    stock_tick = background_tick_text.find("original(app, edx);", ui_dispatch)
    if (
        main_pump == -1
        or ui_dispatch == -1
        or stock_tick == -1
        or not main_pump < ui_dispatch < stock_tick
    ):
        raise StaticReTestFailure(
            "MyApp tick must pump queued main-thread work, dispatch resulting UI "
            "actions, then enter the stock update loop"
        )

    render_owned_tokens = (
        "D3d9FrameActionPump",
        "SetD3d9FrameActionPump",
        "g_action_pump",
    )
    render_owned_text = (
        d3d_header_text
        + d3d_source_text
        + keyboard_injection_text
    )
    stale = [token for token in render_owned_tokens if token in render_owned_text]
    if stale:
        raise StaticReTestFailure(
            "D3D EndScene must remain presentation-only; stale work-pump token(s): "
            + ", ".join(stale)
        )

    forbidden_ownership_heuristics = (
        "kLocalPlayerTickOwnershipFreshnessMs",
        "last_local_player_tick_ms",
        "now_ms - last_local_player_tick_ms",
    )
    present_heuristics = [
        token
        for token in forbidden_ownership_heuristics
        if token in pump_loop_text or token in runtime_request_state_text
    ]
    if present_heuristics:
        raise StaticReTestFailure(
            "main-thread Lua ownership still uses wall-clock freshness "
            "heuristics: " + ", ".join(present_heuristics)
        )

    return "main-thread Lua/menu work is app-tick owned and D3D EndScene remains presentation-only"


def test_multiplayer_native_transport_is_app_thread_owned() -> str:
    service_loop_text = read_text(MULTIPLAYER_SERVICE_LOOP)
    service_loop_header_text = read_text(
        ROOT / "SolomonDarkModLoader/include/multiplayer_service_loop.h"
    )
    public_pump_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_main_thread_pump.inl"
    )
    run_exit_reentry_verifier_text = read_text(
        ROOT / "tools/verify_steam_friend_run_exit_reentry.py"
    )

    service_thread_start = service_loop_text.find("void ServiceThreadMain()")
    service_thread_end = service_loop_text.find(
        "\n}  // namespace",
        service_thread_start,
    )
    if service_thread_start == -1 or service_thread_end == -1:
        raise StaticReTestFailure("multiplayer service-thread body is unavailable")
    service_thread_body = service_loop_text[
        service_thread_start:service_thread_end
    ]
    forbidden_service_thread_calls = (
        "SteamBootstrapTick(",
        "TickSteamSession(",
        "TickLocalTransport(",
    )
    stale_calls = [
        token
        for token in forbidden_service_thread_calls
        if token in service_thread_body
    ]
    if stale_calls:
        raise StaticReTestFailure(
            "native multiplayer work still runs on the background service thread: "
            + ", ".join(stale_calls)
        )

    required_pairs = (
        (
            service_loop_header_text,
            "void TickSessionAndTransportOnAppThread(std::uint64_t now_ms);",
        ),
        (service_loop_text, "g_session_transport_lifecycle_mutex"),
        (service_loop_text, "g_session_transport_owner_thread_id"),
        (service_loop_text, "g_last_session_transport_tick_ms"),
        (service_loop_text, "g_has_session_transport_tick"),
        (service_loop_text, "GetCurrentThreadId()"),
        (service_loop_text, "void TickSessionAndTransportOnAppThread"),
        (public_pump_text, "multiplayer::TickSessionAndTransportOnAppThread("),
        (run_exit_reentry_verifier_text, 'PAIR_BACKEND == "wsl"'),
        (
            run_exit_reentry_verifier_text,
            'PAIR_BACKEND == "remote-windows-host"',
        ),
        (run_exit_reentry_verifier_text, "remote_windows_process_id()"),
        (run_exit_reentry_verifier_text, "pause_menu.leave_game"),
        (run_exit_reentry_verifier_text, "drive_pair_to_hub"),
        (run_exit_reentry_verifier_text, "after_processes != initial_processes"),
        (run_exit_reentry_verifier_text, "new_crash_artifacts(started_at, instances)"),
    )
    missing = [token for text, token in required_pairs if token not in text]
    if missing:
        raise StaticReTestFailure(
            "app-thread multiplayer ownership is missing token(s): "
            + ", ".join(missing)
        )

    app_tick_call = public_pump_text.find(
        "multiplayer::TickSessionAndTransportOnAppThread("
    )
    gameplay_injection_guard = public_pump_text.find(
        "if (!g_gameplay_keyboard_injection.initialized)"
    )
    if (
        app_tick_call == -1
        or gameplay_injection_guard == -1
        or app_tick_call > gameplay_injection_guard
    ):
        raise StaticReTestFailure(
            "Steam session and gameplay transport must tick from AppMainTick even "
            "when gameplay injection is unavailable"
        )

    app_tick_definition = service_loop_text.find(
        "void TickSessionAndTransportOnAppThread"
    )
    owner_gate = service_loop_text.find(
        "if (owner_thread_id != current_thread_id)",
        app_tick_definition,
    )
    cadence_calculation = service_loop_text.find(
        "const auto tick_gap_ms = now_ms - g_last_session_transport_tick_ms;",
        app_tick_definition,
    )
    cadence_gate = service_loop_text.find(
        "tick_gap_ms < kServiceTickIntervalMs",
        app_tick_definition,
    )
    cadence_commit = service_loop_text.find(
        "g_last_session_transport_tick_ms = now_ms;",
        app_tick_definition,
    )
    steam_bootstrap_tick = service_loop_text.find(
        "SteamBootstrapTick();",
        app_tick_definition,
    )
    steam_snapshot_apply = service_loop_text.find(
        "ApplySteamSnapshotToRuntime(now_ms, GetSteamBootstrapSnapshot());",
        app_tick_definition,
    )
    steam_tick = service_loop_text.find(
        "TickSteamSession(now_ms);",
        app_tick_definition,
    )
    transport_tick = service_loop_text.find(
        "TickLocalTransport(now_ms);",
        app_tick_definition,
    )
    if (
        app_tick_definition == -1
        or owner_gate == -1
        or cadence_calculation == -1
        or cadence_gate == -1
        or cadence_commit == -1
        or steam_bootstrap_tick == -1
        or steam_snapshot_apply == -1
        or steam_tick == -1
        or transport_tick == -1
        or not (
            app_tick_definition
            < owner_gate
            < cadence_calculation
            < cadence_gate
            < cadence_commit
            < steam_bootstrap_tick
            < steam_snapshot_apply
            < steam_tick
            < transport_tick
        )
    ):
        raise StaticReTestFailure(
            "the elected AppMainTick owner must enforce the service cadence, pump "
            "Steam callbacks, and refresh the bootstrap snapshot before session "
            "messages and gameplay transport"
        )

    return (
        "Steam callbacks, session messages, packets, snapshots, progression, and "
        "native gameplay work share one elected AppMainTick owner"
    )


def test_participant_native_state_is_owned_by_current_scene() -> str:
    snapshot_types_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/core/participant_snapshot_types.inl"
    )
    scene_context_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/scene_and_animation_scene_context.inl"
    )
    snapshot_builder_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_registry_and_movement_participant_snapshot.inl"
    )
    state_getter_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_state_getters.inl"
    )
    progression_sync_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/multiplayer_local_transport/native_progression_sync.inl"
    )

    required_pairs = (
        (snapshot_types_text, "uintptr_t materialized_scene_address = 0;"),
        (snapshot_types_text, "uintptr_t materialized_world_address = 0;"),
        (scene_context_text, "bool IsParticipantMaterializationOwnedByCurrentScene("),
        (scene_context_text, "current_gameplay_address != materialized_scene_address"),
        (scene_context_text, "current_context.world_address == materialized_world_address"),
        (scene_context_text, "ShouldParticipantSceneIntentMaterializeInScene(scene_intent, current_context)"),
        (snapshot_builder_text, "snapshot.materialized_scene_address = binding.materialized_scene_address;"),
        (snapshot_builder_text, "snapshot.materialized_world_address = binding.materialized_world_address;"),
        (state_getter_text, "snapshot = *it;"),
        (state_getter_text, "snapshot.materialized_scene_address"),
        (state_getter_text, "snapshot.materialized_world_address"),
        (progression_sync_text, "DoesLocalSceneMatchParticipantIntent(participant.runtime.scene_intent)"),
        (progression_sync_text, "!gameplay_state.entity_materialized"),
        (progression_sync_text, "native_progression_reconcile_by_participant.erase("),
    )
    missing = [token for text, token in required_pairs if token not in text]
    if missing:
        raise StaticReTestFailure(
            "participant native scene ownership is missing token(s): "
            + ", ".join(missing)
        )

    ownership_start = scene_context_text.find(
        "bool IsParticipantMaterializationOwnedByCurrentScene("
    )
    ownership_end = scene_context_text.find(
        "\nbool ShouldBotBeMaterializedInScene(",
        ownership_start,
    )
    ownership_body = scene_context_text[ownership_start:ownership_end]
    forbidden_ownership_heuristics = (
        "GetTickCount64",
        "freshness",
        "retry",
        "grace",
    )
    stale_heuristics = [
        token for token in forbidden_ownership_heuristics if token in ownership_body
    ]
    if stale_heuristics:
        raise StaticReTestFailure(
            "participant native ownership must be exact, not time-based: "
            + ", ".join(stale_heuristics)
        )

    builder_owner_check = snapshot_builder_text.find(
        "!IsParticipantMaterializationOwnedByCurrentScene("
    )
    builder_native_probe = snapshot_builder_text.find(
        "IsParticipantActorMemoryFreshReadable(",
        builder_owner_check,
    )
    if (
        builder_owner_check == -1
        or builder_native_probe == -1
        or builder_owner_check > builder_native_probe
    ):
        raise StaticReTestFailure(
            "participant snapshots must prove current scene ownership before "
            "probing actor memory"
        )

    getter_owner_check = state_getter_text.find(
        "!IsParticipantMaterializationOwnedByCurrentScene("
    )
    getter_native_publish = state_getter_text.find(
        "state->actor_address = snapshot.actor_address;",
        getter_owner_check,
    )
    getter_native_read = state_getter_text.find(
        "TryReadWizardActorPersistentStatusFlags(",
        getter_owner_check,
    )
    if not (
        0 <= getter_owner_check < getter_native_publish < getter_native_read
    ):
        raise StaticReTestFailure(
            "participant state getters must reject stale scene bindings before "
            "publishing or reading native pointers"
        )

    progression_start = progression_sync_text.find(
        "void ReconcileRemoteParticipantNativeProgression("
    )
    semantic_scene_check = progression_sync_text.find(
        "DoesLocalSceneMatchParticipantIntent(participant.runtime.scene_intent)",
        progression_start,
    )
    gameplay_state_lookup = progression_sync_text.find(
        "TryGetParticipantGameplayState(",
        progression_start,
    )
    progression_write = progression_sync_text.find(
        "ReconcileRemoteParticipantDamageX4State(",
        gameplay_state_lookup,
    )
    if not (
        0 <= progression_start < semantic_scene_check < gameplay_state_lookup < progression_write
    ):
        raise StaticReTestFailure(
            "remote progression reconciliation must prove semantic scene intent "
            "and current native materialization before any write"
        )

    run_exit_reentry_verifier_text = read_text(
        ROOT / "tools/verify_steam_friend_run_exit_reentry.py"
    )
    live_release_tokens = (
        "verify_run_exit_releases_native_participants(",
        "participant.progression_runtime_state_address",
        "participant.equip_runtime_state_address",
        "outgoing-scene native participant pointers",
        'record["transition_native_release"]',
    )
    missing_live_release = [
        token
        for token in live_release_tokens
        if token not in run_exit_reentry_verifier_text
    ]
    if missing_live_release:
        raise StaticReTestFailure(
            "real-Steam run re-entry lacks native transition release checks: "
            + ", ".join(missing_live_release)
        )

    return (
        "participant native pointers are exact scene/world-owned and remote "
        "progression writes stop immediately during semantic transitions"
    )


TESTS: list[tuple[str, Callable[[], str]]] = [
    (
        "App-thread transport verifier tracks the named cadence gap",
        test_app_thread_transport_verifier_tracks_named_cadence_gap,
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
        test_poison_correction_ack_waits_for_native_application,
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
        "packaged desktop UI accepts its single-file launcher",
        test_packaged_ui_accepts_single_file_launcher,
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
        "progression matrices prearm quiet spawning before run entry",
        test_progression_matrices_prearm_quiet_spawning_before_run_entry,
    ),
    (
        "active Steam behavior harnesses preserve fixture state",
        test_active_steam_behavior_harnesses_preserve_fixture_state,
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
        "native remote Fireball retains cast heading until projectile birth",
        test_native_remote_fireball_retains_cast_heading_until_projectile_birth,
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
    ("remote held input casts defer lifecycle to sender input", test_remote_held_input_casts_defer_lifecycle_to_sender_input),
    ("run-lifecycle spell hooks only forward local player casts", test_run_lifecycle_spell_hooks_only_forward_local_player_casts),
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
        "Main-thread work pump is not render-owned",
        test_main_thread_work_pump_is_not_render_owned,
    ),
    (
        "Multiplayer native transport is app-thread owned",
        test_multiplayer_native_transport_is_app_thread_owned,
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
        "Steam friend hub lifecycle soak is wired",
        test_steam_friend_hub_lifecycle_soak_is_wired,
    ),
    ("player state exports native heading for bot spawn", test_player_state_exports_native_heading_for_bot_spawn),
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


def run_tests() -> list[TestResult]:
    results: list[TestResult] = []
    for name, test in TESTS:
        try:
            detail = test()
            results.append(TestResult(name=name, passed=True, detail=detail))
        except Exception as exc:  # noqa: BLE001 - test runner reports all failures uniformly.
            results.append(TestResult(name=name, passed=False, detail=str(exc)))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit structured JSON instead of text.")
    args = parser.parse_args()

    results = run_tests()
    failed = [result for result in results if not result.passed]
    if args.json:
        print(json.dumps([result.__dict__ for result in results], indent=2))
    else:
        for result in results:
            marker = "PASS" if result.passed else "FAIL"
            print(f"{marker}: {result.name}: {result.detail}")
        print(f"{len(results) - len(failed)}/{len(results)} tests passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
