"""Native actor identity, visual, and source-model contracts."""

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
    ALLY_HP_PROGRESS_GHIDRA,
    ALLY_HP_RECOMPUTE_GHIDRA,
    ALLY_HP_RE_DOC,
    BINARY_LAYOUT,
    BOT_NATIVE_SPEED_LIVE_PROBE,
    BOT_REGISTRY_AND_MOVEMENT_SPAWN,
    ENEMY_SPAWN_API_REMOVED_LIVE_PROBE,
    ENEMY_SPAWN_CALL_SHAPES_GHIDRA,
    ENEMY_WAVE_GHIDRA,
    MOD_LOADER_PROJECT,
    MOD_LOADER_PROJECT_FILTERS,
    NATIVE_SEAM_PLAN,
    NATIVE_WIZARD_DEFAULT_HP_GLOBAL_KEY,
    NATIVE_WIZARD_DEFAULT_MP_GLOBAL_KEY,
    PATHFINDING_LAYOUT_LIVE_PROBE,
    PATHFINDING_MOVEMENT_GHIDRA,
    PATHFINDING_POLICY_FLOAT_GLOBALS_GHIDRA,
    PATHFINDING_POLICY_SCALARS_GHIDRA,
    PATHFINDING_POLICY_SCALAR_DECOMPILE_GHIDRA,
    PATHFINDING_RE_DOC,
    PLAYER_GAMENPC_MOVEMENT_SEED_GHIDRA,
    PLAYER_GAMENPC_MOVEMENT_SEED_OFFSET_GHIDRA,
    REGISTERED_GAMENPC_BLOCKER_LIVE_PROBE,
    REGISTERED_GAMENPC_PUBLICATION_EXPANDED_GHIDRA,
    REGISTERED_GAMENPC_PUBLICATION_GHIDRA,
    REGISTERED_GAMENPC_PUBLICATION_XREFS_GHIDRA,
    ROOT,
    SOURCE_PROFILE_ACTOR174_EXPANDED_GHIDRA,
    SOURCE_PROFILE_FIELD_CANDIDATE_GHIDRA,
    SOURCE_PROFILE_NEGATIVE_GHIDRA,
    SOURCE_PROFILE_NEGATIVE_LIVE_PROBE,
    SOURCE_PROFILE_RE_DOC,
    SOURCE_PROFILE_WRITER_LIVE_PROBE,
    SOURCE_PROFILE_WRITE_SITES_EXPANDED_GHIDRA,
    SPAWN_STANDALONE_WIZARD,
    STAGED_BINARY,
    STOCK_TICK_INPUT_OFFSET_ACCESS_GHIDRA,
    STOCK_TICK_OWNERSHIP_XREFS_GHIDRA,
    STOCK_TICK_RESTORE_GHIDRA,
    STOCK_TICK_RESTORE_LIVE_PROBE,
    SYNTHETIC_SOURCE_PROFILE_GHIDRA,
    StaticReTestFailure,
    WAVE_SCALING_RE_DOC,
    read_layout_numeric,
    read_pe_float_by_va,
    read_text,
)

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
