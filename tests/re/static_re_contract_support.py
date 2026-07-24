"""Shared paths, readers, and result types for native static RE contracts."""

from __future__ import annotations

import hashlib
import json
import os
import struct
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from static_multiplayer_contract_support import read_source_unit

ROOT = Path(__file__).resolve().parents[2]


def _host_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if os.name == "nt" or path.is_absolute():
        return path

    windows_path = PureWindowsPath(raw_path)
    if windows_path.drive and windows_path.root:
        return (
            Path("/mnt")
            / windows_path.drive.rstrip(":").lower()
            / Path(*windows_path.parts[1:])
        )
    return path


def resolve_primary_checkout_root(repo_root: Path) -> Path:
    git_marker = repo_root / ".git"
    if not git_marker.is_file():
        return repo_root
    try:
        marker_text = git_marker.read_text(encoding="utf-8").strip()
    except OSError:
        return repo_root
    prefix = "gitdir:"
    if not marker_text.lower().startswith(prefix):
        return repo_root

    git_directory = _host_path(marker_text[len(prefix):].strip())
    if not git_directory.is_absolute():
        git_directory = (repo_root / git_directory).resolve()
    for candidate in (git_directory, *git_directory.parents):
        if candidate.name == ".git":
            return candidate.parent
    return repo_root


def resolve_workspace_root(repo_root: Path) -> Path:
    return resolve_primary_checkout_root(repo_root).parent


WORKSPACE_ROOT = resolve_workspace_root(ROOT)
PRIMARY_CHECKOUT_ROOT = resolve_primary_checkout_root(ROOT)
RE_RUNTIME_ROOT = PRIMARY_CHECKOUT_ROOT / "runtime"
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
LAUNCHER_COMMAND_EXECUTOR = (
    ROOT / "SolomonDarkModLauncher/src/App/LauncherCommandExecutor.cs"
)
STEAM_LAUNCH_PREFLIGHT = (
    ROOT / "SolomonDarkModLauncher/src/Steam/SteamLaunchPreflight.cs"
)
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
STAGED_BINARY_LAYOUT = (
    RE_RUNTIME_ROOT / "stage/.sdmod/config/binary-layout.ini"
)
STAGED_BINARY = RE_RUNTIME_ROOT / "stage/SolomonDark.exe"


def resolve_abandonware_binary(
    *,
    root: Path = ROOT,
    workspace_root: Path = WORKSPACE_ROOT,
    environment: Mapping[str, str] | None = None,
) -> Path:
    environment = os.environ if environment is None else environment
    override = environment.get("SD_RE_GAME_DIR", "").strip()
    if override:
        override_path = _host_path(override)
        return (
            override_path
            if override_path.name.lower() == "solomondark.exe"
            else override_path / "SolomonDark.exe"
        )

    candidates: list[Path] = []
    stage_report_path = root / "runtime/stage/.sdmod/stage-report.json"
    if stage_report_path.is_file():
        try:
            stage_report = json.loads(
                stage_report_path.read_text(encoding="utf-8")
            )
            retail_game_path = str(
                stage_report.get("retailGamePath", "")
            ).strip()
            if retail_game_path:
                candidates.append(
                    _host_path(retail_game_path) / "SolomonDark.exe"
                )
        except (OSError, ValueError, TypeError):
            pass

    primary_checkout = resolve_primary_checkout_root(root)
    candidates.append(
        primary_checkout.parent
        / "SolomonDarkAbandonware/SolomonDark.exe"
    )
    candidates.extend(
        (
            root.parent / "SolomonDarkAbandonware/SolomonDark.exe",
            workspace_root / "SolomonDarkAbandonware/SolomonDark.exe",
        )
    )
    return next(
        (candidate for candidate in candidates if candidate.is_file()),
        candidates[0],
    )


ABANDONWARE_BINARY = resolve_abandonware_binary()
ALLY_HP_PROGRESS_GHIDRA = RE_RUNTIME_ROOT / "ghidra_ally_hp_progression_paths.txt"
ALLY_HP_RECOMPUTE_GHIDRA = RE_RUNTIME_ROOT / "ghidra_ally_hp_recompute_candidate.txt"
PRIMARY_SPELL_BUILDER_GHIDRA = RE_RUNTIME_ROOT / "ghidra_primary_spell_builder_resource_paths.txt"
SYNTHETIC_SOURCE_PROFILE_GHIDRA = RE_RUNTIME_ROOT / "ghidra_synthetic_source_profile_paths.txt"
SOURCE_PROFILE_NEGATIVE_GHIDRA = RE_RUNTIME_ROOT / "ghidra_source_profile_negative_producer_scan.txt"
SOURCE_PROFILE_ACTOR174_EXPANDED_GHIDRA = RE_RUNTIME_ROOT / "ghidra_source_profile_actor174_expanded_scan.txt"
SOURCE_PROFILE_FIELD_CANDIDATE_GHIDRA = RE_RUNTIME_ROOT / "ghidra_source_profile_field_candidate_decompiles.txt"
SOURCE_PROFILE_WRITE_SITES_EXPANDED_GHIDRA = RE_RUNTIME_ROOT / "ghidra_source_profile_write_sites_expanded.txt"
SOURCE_PROFILE_NEGATIVE_LIVE_PROBE = ROOT / "tests/re/run_live_source_profile_negative_probe.py"
SOURCE_PROFILE_WRITER_LIVE_PROBE = ROOT / "tests/re/run_live_source_profile_writer_probe.py"
PURE_PRIMARY_STARTUP_LIVE_PROBE = ROOT / "tests/re/run_live_pure_primary_startup_probe.py"
PURE_PRIMARY_EQUIP_SINK_GHIDRA = RE_RUNTIME_ROOT / "ghidra_pure_primary_equip_sink_paths.txt"
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
ENEMY_WAVE_GHIDRA = RE_RUNTIME_ROOT / "ghidra_enemy_wave_spawn_paths.txt"
ENEMY_SPAWN_CALL_SHAPES_GHIDRA = RE_RUNTIME_ROOT / "ghidra_enemy_spawn_call_shapes.txt"
ENEMY_SPAWN_API_REMOVED_LIVE_PROBE = ROOT / "tests/re/run_live_enemy_spawn_api_removed_probe.py"
PATHFINDING_MOVEMENT_GHIDRA = RE_RUNTIME_ROOT / "ghidra_pathfinding_movement_paths.txt"
PATHFINDING_POLICY_SCALARS_GHIDRA = RE_RUNTIME_ROOT / "ghidra_pathfinding_policy_scalar_scan.txt"
PATHFINDING_POLICY_SCALAR_DECOMPILE_GHIDRA = RE_RUNTIME_ROOT / "ghidra_pathfinding_policy_scalar_decompile.txt"
PATHFINDING_POLICY_FLOAT_GLOBALS_GHIDRA = RE_RUNTIME_ROOT / "ghidra_pathfinding_policy_float_globals.txt"
PATHFINDING_LAYOUT_LIVE_PROBE = ROOT / "tests/re/run_live_pathfinding_layout_probe.py"
PLAYER_GAMENPC_MOVEMENT_SEED_GHIDRA = RE_RUNTIME_ROOT / "ghidra_player_gamenpc_movement_seed_paths.txt"
PLAYER_GAMENPC_MOVEMENT_SEED_OFFSET_GHIDRA = (
    RE_RUNTIME_ROOT / "ghidra_player_gamenpc_movement_seed_offsets.txt"
)
STOCK_TICK_RESTORE_GHIDRA = RE_RUNTIME_ROOT / "ghidra_stock_tick_restore_paths.txt"
STOCK_TICK_OWNERSHIP_XREFS_GHIDRA = RE_RUNTIME_ROOT / "ghidra_stock_tick_ownership_xrefs.txt"
STOCK_TICK_INPUT_OFFSET_ACCESS_GHIDRA = RE_RUNTIME_ROOT / "ghidra_stock_tick_input_offset_accesses.txt"
STOCK_TICK_RESTORE_LIVE_PROBE = ROOT / "tests/re/run_live_stock_tick_restore_probe.py"
BOT_NATIVE_SPEED_LIVE_PROBE = ROOT / "tests/re/run_live_bot_native_speed_probe.py"
REGISTERED_GAMENPC_PUBLICATION_GHIDRA = (
    RE_RUNTIME_ROOT / "ghidra_registered_gamenpc_publication_blockers.txt"
)
REGISTERED_GAMENPC_PUBLICATION_XREFS_GHIDRA = (
    RE_RUNTIME_ROOT / "ghidra_registered_gamenpc_publication_xrefs.txt"
)
REGISTERED_GAMENPC_PUBLICATION_EXPANDED_GHIDRA = (
    RE_RUNTIME_ROOT / "ghidra_registered_gamenpc_publication_expanded.txt"
)
REGISTERED_GAMENPC_BLOCKER_LIVE_PROBE = (
    ROOT / "tests/re/run_live_registered_gamenpc_blocker_probe.py"
)
STANDALONE_COLLISION_REGISTRATION_GHIDRA = (
    RE_RUNTIME_ROOT / "ghidra_standalone_collision_registration_paths.txt"
)
STANDALONE_COLLISION_OVERLAP_GHIDRA = (
    RE_RUNTIME_ROOT / "ghidra_standalone_collision_overlap_builder_paths.txt"
)
STANDALONE_COLLISION_OWNERSHIP_XREFS_GHIDRA = (
    RE_RUNTIME_ROOT / "ghidra_standalone_collision_ownership_xrefs.txt"
)
STANDALONE_COLLISION_FIELD_WRITES_GHIDRA = (
    RE_RUNTIME_ROOT / "ghidra_standalone_collision_field_writes.txt"
)
STANDALONE_CLONE_INSTRUCTION_GHIDRA = (
    RE_RUNTIME_ROOT / "ghidra_wizard_clone_from_source_instructions.txt"
)
CAST_STATE_GHIDRA = RE_RUNTIME_ROOT / "ghidra_stock_tick_slot_shim_cast_paths.txt"
CAST_STATE_OFFSETS_GHIDRA = RE_RUNTIME_ROOT / "ghidra_cast_state_offsets.txt"
CAST_SPELL_OBJECT_GHIDRA = RE_RUNTIME_ROOT / "ghidra_cast_spell_object_handlers.txt"
CAST_SLOT0_DISPATCH_XREFS_GHIDRA = RE_RUNTIME_ROOT / "ghidra_cast_slot0_dispatch_xrefs.txt"
CAST_SLOT0_GATE_OFFSET_ACCESS_GHIDRA = RE_RUNTIME_ROOT / "ghidra_cast_slot0_gate_offset_accesses.txt"
CAST_SELECTION_LIFECYCLE_XREFS_GHIDRA = RE_RUNTIME_ROOT / "ghidra_selection_lifecycle_xrefs.txt"
CAST_SELECTION_CLEANUP_TARGETS_GHIDRA = RE_RUNTIME_ROOT / "ghidra_selection_and_cleanup_targets.txt"
CAST_SELECTION_BRAIN_OFFSET_ACCESS_GHIDRA = (
    RE_RUNTIME_ROOT / "ghidra_selection_brain_offset_accesses.txt"
)
CAST_ACTIVE_SPELL_LIFECYCLE_XREFS_GHIDRA = (
    RE_RUNTIME_ROOT / "ghidra_active_spell_lifecycle_xrefs.txt"
)
CAST_LATCH_OFFSET_ACCESS_GHIDRA = RE_RUNTIME_ROOT / "ghidra_cast_latch_offset_accesses.txt"
CAST_BOULDER_VTABLE_GHIDRA = RE_RUNTIME_ROOT / "ghidra_boulder_spell_object_vtable_slots.txt"
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
