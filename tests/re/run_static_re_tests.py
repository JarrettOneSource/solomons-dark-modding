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
MULTIPLAYER_SERVICE_LOOP = ROOT / "SolomonDarkModLoader/src/multiplayer_service_loop.cpp"
WORLD_SNAPSHOT_RECONCILIATION = (
    ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/world_snapshot_reconciliation.inl"
)
LUA_EXEC_PIPE = ROOT / "SolomonDarkModLoader/src/lua_exec_pipe.cpp"
STAGED_GAME_LAUNCHER = ROOT / "SolomonDarkModLauncher/src/Launch/StagedGameLauncher.cs"
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
RUN_ENEMY_SEED_VERIFIER = ROOT / "tools/verify_run_enemy_seed_viability.py"
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
PLAYER_ACTOR_TICK_HOOK = (
    ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/actor_tick/player_actor_tick_hook.inl"
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
    helper_cpp_text = read_text(NATIVE_SPELL_STATS_CPP)
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
        "magic missile hit damage gate branch layout": "magic_missile_hit_damage_projectile_group_gate_branch=0x005F1F39",
        "gate patch name": "player_actor_apply_mana_delta_local_actor_gate",
        "ether gate patch name": "spell_cast_008_ether_slot_gate",
        "ether projectile gate patch name": "spell_cast_008_ether_projectile_slot_gate",
        "fire gate patch name": "spell_cast_010_fire_slot_gate",
        "magic missile hit damage gate patch name": "magic_missile_hit_damage_projectile_group_gate",
        "gate patch binding": "kPlayerActorApplyManaDeltaLocalActorGateBranch",
        "ether gate patch binding": "kSpellCast008SlotGateBranch",
        "ether projectile gate patch binding": "kSpellCast008ProjectileSlotGateBranch",
        "fire gate patch binding": "kSpellCast010SlotGateBranch",
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
    native_stats_text = read_text(NATIVE_SPELL_STATS_CPP)
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
    native_spell_stats_text = read_text(NATIVE_SPELL_STATS_CPP)
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


def test_primary_selection_mapping_is_native_backed_not_static_table() -> str:
    native_spell_stats_text = read_text(NATIVE_SPELL_STATS_CPP)
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
    skill_choices_text = read_text(ROOT / "SolomonDarkModLoader/src/bot_runtime/helpers/skill_choices.inl")
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
    helper_cpp_text = read_text(NATIVE_SPELL_STATS_CPP)
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
    player_cast_hook_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/player_cast_hooks.inl"
    )
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

    player_cast_text = read_text(PLAYER_CAST_HOOKS)
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
        (STANDALONE_SLOT_BOT_CREATION, "[bots] visual stage=slot_actor_staff_attached"),
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
    runtime_state_text = read_text(MULTIPLAYER_RUNTIME_STATE)
    transport_header_text = read_text(MULTIPLAYER_LOCAL_TRANSPORT_HEADER)
    transport_text = read_text(MULTIPLAYER_LOCAL_TRANSPORT)
    world_snapshot_reconciliation_text = read_text(WORLD_SNAPSHOT_RECONCILIATION)
    service_loop_text = read_text(MULTIPLAYER_SERVICE_LOOP)
    lua_exec_pipe_text = read_text(LUA_EXEC_PIPE)
    staged_game_launcher_text = read_text(STAGED_GAME_LAUNCHER)
    project_text = read_text(MOD_LOADER_PROJECT)
    project_filters_text = read_text(MOD_LOADER_PROJECT_FILTERS)
    bot_runtime_header_text = read_text(BOT_RUNTIME_HEADER)
    bot_snapshots_text = read_text(BOT_RUNTIME_SNAPSHOTS_API)
    entity_sync_text = read_text(PARTICIPANT_ENTITY_SYNC)
    scene_binding_text = read_text(PARTICIPANT_SCENE_BINDING_TICKS)
    native_remote_playback_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_movement/native_remote_playback.inl"
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
    run_seed_verifier_text = read_text(RUN_ENEMY_SEED_VERIFIER)

    required_pairs = (
        (protocol_text, "constexpr std::uint16_t kProtocolVersion = 10;"),
        (protocol_text, "kParticipantDisplayNameBytes"),
        (protocol_text, "kWorldSnapshotMaxActors"),
        (protocol_text, "WorldSnapshotFlagTruncated"),
        (protocol_text, "WorldActorSnapshotFlagLifecycleOwned"),
        (protocol_text, "std::uint64_t participant_id;"),
        (protocol_text, "display_name"),
        (protocol_text, "static_assert(sizeof(StatePacket) == 148"),
        (protocol_text, "static_assert(sizeof(WorldSnapshotPacket) == 3360"),
        (runtime_state_text, "LocalUdp"),
        (runtime_state_text, "WorldSnapshotRuntimeInfo"),
        (runtime_state_text, "WorldSnapshotApplyRuntimeInfo"),
        (runtime_state_text, "WorldSnapshotActorBindingRuntimeInfo"),
        (runtime_state_text, "ParticipantTransformSample"),
        (runtime_state_text, "transform_history"),
        (runtime_state_text, "world_snapshot_history"),
        (runtime_state_text, "kParticipantTransformHistoryCapacity"),
        (runtime_state_text, "kWorldSnapshotHistoryCapacity"),
        (runtime_state_text, "TrySampleParticipantTransform"),
        (runtime_state_text, "TrySampleWorldSnapshot"),
        (runtime_state_text, "InterpolateHeadingDegrees"),
        (runtime_state_text, "actor_total_count"),
        (runtime_state_text, "truncated"),
        (runtime_state_text, "created_actor_count"),
        (runtime_state_text, "created_actor_total_count"),
        (runtime_state_text, "health_write_count"),
        (runtime_state_text, "dead_actor_count"),
        (runtime_state_text, "actor_bindings"),
        (transport_header_text, "TickLocalTransport"),
        (transport_text, "SDMOD_MULTIPLAYER_TRANSPORT"),
        (transport_text, "SDMOD_MULTIPLAYER_LOCAL_PORT"),
        (transport_text, "SDMOD_MULTIPLAYER_REMOTE_PORT"),
        (transport_text, "SDMOD_MULTIPLAYER_PLAYER_NAME"),
        (transport_text, "RelayStatePacketToPeers"),
        (transport_text, "BuildLocalWorldSnapshotPacket"),
        (transport_text, "TryGetRunLifecycleEnemySpawnSerial"),
        (transport_text, "BuildRunWorldActorNetworkId"),
        (transport_text, "ParticipantSceneIntentKind::SharedHub"),
        (transport_text, "ParticipantSceneIntentKind::Run"),
        (transport_text, "actor.tracked_enemy"),
        (transport_text, "WorldSnapshotFlagTruncated"),
        (transport_text, "ApplyWorldSnapshotPacket"),
        (world_snapshot_reconciliation_text, "ApplyReplicatedWorldSnapshotIfActive"),
        (world_snapshot_reconciliation_text, "BuildLocalReplicatedWorldActorBindings"),
        (world_snapshot_reconciliation_text, "TryCreateReplicatedSharedHubActor"),
        (world_snapshot_reconciliation_text, "IsReplicatedSharedHubFactoryActorType"),
        (world_snapshot_reconciliation_text, "CallGameObjectFactorySafe"),
        (world_snapshot_reconciliation_text, "CallActorWorldRegisterSafe"),
        (world_snapshot_reconciliation_text, "created_actor_total_count += counts.created_actor_count"),
        (world_snapshot_reconciliation_text, "TryRebindActorToOwnerWorld"),
        (world_snapshot_reconciliation_text, "kWorldSnapshotApplyStaleMs"),
        (world_snapshot_reconciliation_text, "kWorldSnapshotInterpolationDelayMs"),
        (world_snapshot_reconciliation_text, "TrySampleWorldSnapshot"),
        (world_snapshot_reconciliation_text, "ParticipantSceneIntentKind::SharedHub"),
        (world_snapshot_reconciliation_text, "ParticipantSceneIntentKind::Run"),
        (world_snapshot_reconciliation_text, "QueueGameplayStartWaves"),
        (world_snapshot_reconciliation_text, "IsLocalRunCombatAlreadyActive"),
        (world_snapshot_reconciliation_text, "remote_state_wave"),
        (world_snapshot_reconciliation_text, "MaybeCatchUpRunEnemyPoolForAuthoritativeSnapshot"),
        (world_snapshot_reconciliation_text, "TryAccelerateRunLifecycleEnemyPoolForSnapshot"),
        (world_snapshot_reconciliation_text, "TryBindAuthoritativeRunActorToLocalPool"),
        (world_snapshot_reconciliation_text, "BindReplicatedRunActor"),
        (world_snapshot_reconciliation_text, "RecordWorldSnapshotBinding"),
        (world_snapshot_reconciliation_text, "ApplyReplicatedRunEnemyHealth"),
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
        (transport_text, "TryGetPlayerState"),
        (transport_text, "TryGetWorldState"),
        (transport_text, "packet.wave = local->runtime.wave"),
        (service_loop_text, "InitializeLocalTransport()"),
        (service_loop_text, "TickLocalTransport(now_ms)"),
        (service_loop_text, "ShutdownLocalTransport()"),
        (lua_exec_pipe_text, "SDMOD_LUA_EXEC_PIPE_NAME"),
        (staged_game_launcher_text, "SDMOD_MULTIPLAYER_TRANSPORT"),
        (staged_game_launcher_text, "SDMOD_MULTIPLAYER_PARTICIPANT_ID"),
        (staged_game_launcher_text, "SDMOD_MULTIPLAYER_PLAYER_NAME"),
        (staged_game_launcher_text, "SDMOD_LUA_EXEC_PIPE_NAME"),
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
        (native_remote_playback_text, "ApplyNativeRemoteParticipantPlayback"),
        (native_remote_playback_text, "replicated_transform_playback_ms"),
        (native_remote_playback_text, "kRemoteTransformInterpolationDelayMs"),
        (native_remote_playback_text, "TrySampleParticipantTransform"),
        (native_remote_playback_text, "kRemoteSnapDistance"),
        (participant_collision_text, "left.local_player && right.native_remote"),
        (participant_collision_text, "right.local_player && left.native_remote"),
        (networking_doc_text, "client-predicted / authority-verified"),
        (networking_doc_text, "SDMOD_MULTIPLAYER_TRANSPORT=local_udp"),
        (networking_doc_text, "SDMOD_MULTIPLAYER_PLAYER_NAME"),
        (networking_doc_text, "verify_local_multiplayer_sync.py"),
        (networking_doc_text, "SDMOD_LUA_EXEC_PIPE_NAME"),
        (networking_doc_text, "player/player"),
        (networking_doc_text, "WorldSnapshot"),
        (networking_doc_text, "run-world"),
        (networking_doc_text, "tracked enemies"),
        (networking_doc_text, "bootstrap client wave activation"),
        (networking_doc_text, "accelerates its native wave-spawner timers"),
        (networking_doc_text, "host lifecycle spawn serial"),
        (networking_doc_text, "live HP/max-HP"),
        (world_sync_plan_text, "tools/verify_run_enemy_seed_viability.py"),
        (world_sync_plan_text, "stock run-enemy lockstep was rejected"),
        (world_sync_plan_text, "client's native wave spawner as a local"),
        (world_sync_plan_text, "host lifecycle spawn serial"),
        (world_sync_plan_text, "extra_unparked_client_tracked_enemies"),
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
        (script_text, "local-mp-host"),
        (script_text, "local-mp-client"),
        (script_text, "SDMOD_MULTIPLAYER_PLAYER_NAME"),
        (script_text, "SDMOD_LUA_EXEC_PIPE_NAME"),
        (script_text, "multiplayer.steam_bootstrap=false"),
        (verifier_text, "wait_for_remote"),
        (verifier_text, "nudge_player"),
        (verifier_text, "wait_for_remote_convergence"),
        (verifier_text, "wait_for_local_transform_settled"),
        (verifier_text, "heading_tolerance: float = 0.25"),
        (verifier_text, "observed-motion heading"),
        (verifier_text, "wait_for_collision_push"),
        (verifier_text, "sd.bots.get_nameplate"),
        (verifier_text, "sd.hub.start_testrun"),
    )
    missing = [token for text, token in required_pairs if token not in text]
    if missing:
        raise StaticReTestFailure(
            "local multiplayer transport wiring missing token(s): " + ", ".join(missing))
    if "latest runtime snapshot" in networking_doc_text:
        raise StaticReTestFailure("networking docs still describe latest-packet playback instead of interpolation history")

    return "local UDP dev transport is wired through protocol, service loop, interpolated participant/world sync, docs, and launch script"


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
    skill_choices_text = read_text(ROOT / "SolomonDarkModLoader/src/bot_runtime/helpers/skill_choices.inl")
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
    player_cast_hooks_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/player_cast_hooks.inl"
    )
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


def test_remaining_native_addresses_and_probe_offsets_are_layout_backed() -> str:
    layout_text = read_text(BINARY_LAYOUT)
    seams_header_text = read_text(ROOT / "SolomonDarkModLoader/src/gameplay_seams.h")
    address_storage_text = read_text(ROOT / "SolomonDarkModLoader/src/gameplay_seams/address_storage.inl")
    address_bindings_text = read_text(ROOT / "SolomonDarkModLoader/src/gameplay_seams/state_and_address_bindings.inl")
    size_bindings_text = read_text(ROOT / "SolomonDarkModLoader/src/gameplay_seams/size_bindings.inl")
    exception_handlers_text = read_text(ROOT / "SolomonDarkModLoader/src/logger_exception_handlers.cpp")
    skill_choices_text = read_text(ROOT / "SolomonDarkModLoader/src/bot_runtime/helpers/skill_choices.inl")
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
    actor_render_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/standalone_materialization_actor_render_state.inl"
    )
    priming_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/scene_and_animation_bot_priming_and_selection.inl"
    )
    standalone_spawn_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/execute_requests/spawn_standalone_wizard.inl"
    )
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
        "SeedWizardBotNativeCollisionStateFromSourceActor",
        "kNativeDerivedSourceProfileSize",
        "native-derived source profile",
    )
    combined_text = "\n".join((
        clone_source_text,
        slot_creation_text,
        actor_render_text,
        priming_text,
        standalone_spawn_text,
        native_types_text,
        safe_decls_text,
        player_calls_text,
        seam_header_text,
        seam_storage_text,
        seam_bindings_text,
        layout_text,
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
        r"SeedWizardBotNativeCollisionStateFromSourceActor[\s\S]*SeedGameplaySlotBotRenderStateFromSourceActor",
        priming_text,
    ):
        raise StaticReTestFailure(
            "gameplay-slot bot priming does not seed native collision before render materialization")
    if "AttachBuiltDescriptorToEquipVisualLane" not in slot_creation_text:
        raise StaticReTestFailure(
            "gameplay-slot bot materialization does not publish the source descriptor through helper lanes")
    if not re.search(
        r"CaptureActorRenderBuildSnapshot[\s\S]*ApplySourceActorRenderSelectorsToTargetActor[\s\S]*AttachBuiltDescriptorToEquipVisualLane",
        slot_creation_text,
    ):
        raise StaticReTestFailure(
            "gameplay-slot bot materialization does not publish safe source selector bytes before helper lanes")

    return "wizard visuals are built from native Skills_Wizard colors and published through safe selectors plus stock clone/helper lanes"


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
        read_text(ROOT / "SolomonDarkModLoader/src/bot_runtime/public_api/skill_choices_api.inl"),
    ))
    native_stats_text = read_text(NATIVE_SPELL_STATS_CPP)
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


TESTS: list[tuple[str, Callable[[], str]]] = [
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
    ("primary build skill mapping has single runtime owner", test_primary_build_skill_mapping_has_single_runtime_owner),
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
