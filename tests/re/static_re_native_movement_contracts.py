"""Native movement, collision, seam, and code-quality contracts."""

from __future__ import annotations

import ast
import hashlib
import json
import math
import re
import struct
import sys
from pathlib import Path

from static_re_contract_support import (
    ACCEPTED_NATIVE_SHIMS_DOC,
    BINARY_LAYOUT,
    BOT_ELEMENT_DAMAGE_PROBE,
    CAST_ACTIVE_SPELL_LIFECYCLE_XREFS_GHIDRA,
    CAST_BOULDER_VTABLE_GHIDRA,
    CAST_LATCH_OFFSET_ACCESS_GHIDRA,
    CAST_SELECTION_BRAIN_OFFSET_ACCESS_GHIDRA,
    CAST_SELECTION_CLEANUP_TARGETS_GHIDRA,
    CAST_SELECTION_LIFECYCLE_XREFS_GHIDRA,
    CAST_SLOT0_DISPATCH_XREFS_GHIDRA,
    CAST_SLOT0_GATE_OFFSET_ACCESS_GHIDRA,
    CAST_SPELL_OBJECT_GHIDRA,
    CAST_STATE_GHIDRA,
    CAST_STATE_OFFSETS_GHIDRA,
    CORRECTED_SMELL_GUARDS,
    DISPATCH_PUMP_LOOP,
    DISPATCH_REQUEST_QUEUES,
    GAMEPLAY_CONSTANTS,
    LUA_BOT_COMBAT,
    LUA_BOT_CONFIG,
    LUA_BOT_CONSTANTS_RE_DOC,
    LUA_BOT_ENEMY_SEMANTIC_LIVE_PROBE,
    LUA_BOT_FOLLOW,
    LUA_BOT_STATE,
    LUA_BOT_TRAVEL,
    MOD_LOADER_PROJECT,
    MOD_LOADER_PROJECT_FILTERS,
    NATIVE_SEAM_PLAN,
    PATHFINDING_RE_DOC,
    PENDING_CAST_PROCESSING,
    PLAYER_ACTOR_TICK_HOOK,
    PROVE_LUA_FOLLOW,
    PURE_PRIMARY_EQUIP_SINK_GHIDRA,
    PURE_PRIMARY_STARTUP_LIVE_PROBE,
    ROOT,
    SKILL_SELECTION_RULES,
    STANDALONE_CLONE_INSTRUCTION_GHIDRA,
    STANDALONE_CLONE_SOURCE,
    STANDALONE_COLLISION_FIELD_WRITES_GHIDRA,
    STANDALONE_COLLISION_OVERLAP_GHIDRA,
    STANDALONE_COLLISION_OWNERSHIP_XREFS_GHIDRA,
    STANDALONE_COLLISION_REGISTRATION_GHIDRA,
    STANDALONE_DEBUG_SUMMARIES,
    STANDALONE_EQUIP_VISUAL_LANES,
    STANDALONE_SELECTION_PRIMING,
    STANDALONE_SLOT_BOT_CREATION,
    StaticReTestFailure,
    read_player_cast_hooks_source,
    read_text,
)

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
        "WaveData_Parse and FUN_0062D920 identify the stock arena enemy classes",
        "kFirstArenaCombatActorType = 1001",
        "kLastArenaCombatActorType = 1013",
        "kGreenImpArenaCombatActorType = 0x7FC",
        "kMaggotArenaCombatActorType = 0x7FD",
        "kSpiderArenaCombatActorType = 0x809",
        "kImpPortalArenaCombatActorType = 0x139D",
        "object_type_id >= kFirstArenaCombatActorType",
        "object_type_id <= kLastArenaCombatActorType",
        "object_type_id == kGreenImpArenaCombatActorType",
        "object_type_id == kMaggotArenaCombatActorType",
        "object_type_id == kSpiderArenaCombatActorType",
        "object_type_id == kImpPortalArenaCombatActorType",
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
