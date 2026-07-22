"""Binary identity, diagnostics, tooling, and pathfinding contracts."""

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
    ABANDONWARE_BINARY,
    BINARY_LAYOUT,
    BOT_PATHFINDING_PATH_BUILDING,
    BOT_PATHFINDING_TRAVERSABILITY,
    CAST_RELEASE_HELPERS,
    INVESTIGATION_REGISTER_COVERAGE,
    LAUNCHER_COMMAND_EXECUTOR,
    LUA_BOT_FOLLOW,
    MOD_LOADER_PROJECT,
    MOD_LOADER_PROJECT_FILTERS,
    NATIVE_SEAM_PLAN,
    RESOURCE_STATE,
    ROOT,
    SCENE_ANIMATION_DRIVE_PROFILES,
    SMELL_SOURCES,
    SPAWN_STANDALONE_WIZARD,
    STAGED_BINARY,
    STAGED_BINARY_LAYOUT,
    STANDALONE_CLONE_SOURCE,
    STEAM_LAUNCH_PREFLIGHT,
    STOCK_TICK_RESTORE_LIVE_PROBE,
    StaticReTestFailure,
    read_bot_skill_choice_source,
    read_gameplay_seams_header_source,
    read_native_spell_stats_source,
    read_player_cast_hooks_source,
    read_source_unit,
    read_text,
    sha256,
)

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
    registry_path = ROOT / "tests/re/static_re_test_registry.py"
    registry_tree = ast.parse(read_text(registry_path))
    registry_assignment = next(
        (
            node
            for node in registry_tree.body
            if isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "TESTS"
        ),
        None,
    )
    if registry_assignment is None or not isinstance(registry_assignment.value, ast.List):
        raise StaticReTestFailure("static RE registry does not define a literal TESTS list")
    test_names = {
        entry.elts[0].value
        for entry in registry_assignment.value.elts
        if isinstance(entry, ast.Tuple)
        and len(entry.elts) == 2
        and isinstance(entry.elts[0], ast.Constant)
        and isinstance(entry.elts[0].value, str)
    }
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
        "FileSystemAccessRule",
        "AccessControlType.Deny",
        "RemoveAccessRuleSpecific",
        "FileSystemRights.FullControl",
        "SetAccessControl",
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
    for external_tool in ("takeown.exe", "icacls.exe", "RunWindowsTool"):
        if external_tool in mirror_text:
            raise StaticReTestFailure(
                "stage ACL recovery still depends on an external Windows "
                f"utility: {external_tool}"
            )
    if "entry.LinkTarget is not null" not in mirror_text:
        raise StaticReTestFailure(
            "stage mirror identifies junctions only through the reparse "
            "attribute"
        )
    return (
        "stage mirror repairs ownership and explicit deny ACLs through managed "
        "Windows security APIs before retrying destination writes"
    )


def test_stage_mirror_publishes_and_verifies_file_contents() -> str:
    mirror_text = read_text(
        ROOT / "SolomonDarkModLauncher/src/Staging/FileTreeMirror.cs"
    )
    compact = re.sub(r"\s+", "", mirror_text)
    required_tokens = (
        "FilesHaveEqualContents(sourceFile, destinationFile)",
        "CreateTemporaryStagePath(destinationDirectoryPath, sourceFile.Name)",
        "File.Move(tempPath, destinationPath, overwrite: true)",
        "DeleteTemporaryStageFile(tempPath)",
    )
    missing = [
        token
        for token in required_tokens
        if re.sub(r"\s+", "", token) not in compact
    ]
    if missing:
        raise StaticReTestFailure(
            "stage mirror does not verify and atomically publish file contents: "
            + ", ".join(missing)
        )
    if (
        "File.Copy(sourceFile.FullName,destinationPath,overwrite:true)"
        in compact
    ):
        raise StaticReTestFailure(
            "stage mirror still overwrites live destination files in place"
        )
    return "stage mirror verifies bytes and atomically publishes complete files"


def test_multiplayer_launch_preflights_steam_before_starting_game() -> str:
    executor_text = read_text(LAUNCHER_COMMAND_EXECUTOR)
    preflight_text = read_text(STEAM_LAUNCH_PREFLIGHT)

    preflight_call = (
        "SteamLaunchPreflight.EnsureAvailable(stageResult.SteamBootstrap);"
    )
    launch_call = "var launchedGame = StagedGameLauncher.Launch("
    if preflight_call not in executor_text:
        raise StaticReTestFailure(
            "multiplayer launch does not verify the active Steam session before starting the game"
        )
    if executor_text.index(preflight_call) > executor_text.index(launch_call):
        raise StaticReTestFailure(
            "Steam readiness is checked only after SolomonDark.exe starts"
        )

    required_preflight_tokens = (
        "internal static class SteamLaunchPreflight",
        "SteamStageBootstrapResult bootstrap",
        "using var session = new SteamManualDispatchSession(steamApiPath, bootstrap.AppId);",
        "Open Steam, sign in, and wait until Steam is online.",
        "Run Steam and this launcher with the same administrator setting.",
    )
    missing = [
        token for token in required_preflight_tokens if token not in preflight_text
    ]
    if missing:
        raise StaticReTestFailure(
            "Steam launch preflight is incomplete: " + ", ".join(missing)
        )
    return "multiplayer launch validates Steam before SolomonDark.exe starts"


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
    run_lifecycle_hooks_text = read_source_unit(
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
        read_source_unit(ROOT / "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks.inl"),
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
