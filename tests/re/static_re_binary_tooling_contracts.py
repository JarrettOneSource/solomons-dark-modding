"""Binary identity, diagnostics, tooling, and pathfinding contracts."""

from __future__ import annotations

import ast
import hashlib
import json
import math
import re
import struct
import subprocess
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


def test_native_d3d_device_lifetime_outlives_stock_teardown() -> str:
    layout = read_text(BINARY_LAYOUT)
    guard = read_text(
        ROOT / "SolomonDarkModLoader/src/native_d3d9_lifetime_guard.cpp"
    )
    loader = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader.cpp"
    ) + read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader/initialize.inl"
    )
    project = read_text(MOD_LOADER_PROJECT)
    filters = read_text(MOD_LOADER_PROJECT_FILTERS)

    required = (
        (layout, "[native_d3d_lifetime]"),
        (layout, "device_pointer_global=0x00B401E8"),
        (layout, "device_pointer_clear=0x0040D0CF"),
        (guard, "device->AddRef()"),
        (guard, "ValidateDeviceClearInstruction("),
        (guard, "kMovAbsoluteFromEbxOpcode0 = 0x89"),
        (guard, "kMovAbsoluteFromEbxOpcode1 = 0x1D"),
        (guard, "memory.TryWrite(\n                device_clear,"),
        (guard, "g_process_lifetime_device = device"),
        (loader, "InitializeNativeD3d9LifetimeGuard("),
        (project, r"src\native_d3d9_lifetime_guard.cpp"),
        (filters, r"src\native_d3d9_lifetime_guard.cpp"),
    )
    missing = [token for text, token in required if token not in text]
    if missing:
        raise StaticReTestFailure(
            "native D3D lifetime ownership is incomplete: "
            + ", ".join(missing)
        )

    guard_install = loader.find("InitializeNativeD3d9LifetimeGuard(")
    audio_install = loader.find("InitializeLaunchAudioDisable(")
    if not 0 <= guard_install < audio_install:
        raise StaticReTestFailure(
            "D3D process-lifetime ownership is not installed immediately "
            "after binary-layout discovery"
        )
    if "ShutdownNativeD3d9LifetimeGuard" in loader:
        raise StaticReTestFailure(
            "normal subsystem teardown can release the process-owned D3D guard"
        )

    binary = ABANDONWARE_BINARY.read_bytes()
    pe_offset = struct.unpack_from("<I", binary, 0x3C)[0]
    section_count = struct.unpack_from("<H", binary, pe_offset + 6)[0]
    optional_size = struct.unpack_from("<H", binary, pe_offset + 20)[0]
    optional = pe_offset + 24
    image_base = struct.unpack_from("<I", binary, optional + 28)[0]
    target_rva = 0x0040D0CF - image_base
    section_table = optional + optional_size
    target_bytes = None
    for index in range(section_count):
        section = section_table + index * 40
        virtual_size, virtual_address, raw_size, raw_offset = struct.unpack_from(
            "<IIII", binary, section + 8
        )
        mapped_size = max(virtual_size, raw_size)
        if virtual_address <= target_rva < virtual_address + mapped_size:
            file_offset = raw_offset + target_rva - virtual_address
            target_bytes = binary[file_offset : file_offset + 6]
            break
    if target_bytes != bytes.fromhex("89 1d e8 01 b4 00"):
        raise StaticReTestFailure(
            "configured D3D device-clear seam no longer matches "
            f"retail bytes: {target_bytes!r}"
        )

    return (
        "the loader retains the retail D3D9 device for process lifetime and "
        "suppresses the single stock global-clear instruction that raced the "
        "asset worker and CRT SpriteBundle destruction"
    )


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


def test_process_termination_has_no_joinable_static_worker_destructors() -> str:
    worker_sources = {
        "Lua exec pipe": read_text(
            ROOT / "SolomonDarkModLoader/src/lua_exec_pipe.cpp"
        ),
        "multiplayer service": read_text(
            ROOT / "SolomonDarkModLoader/src/multiplayer_service_loop.cpp"
        ),
        "runtime tick": read_text(
            ROOT / "SolomonDarkModLoader/src/runtime_tick_service.cpp"
        ),
        "asynchronous logger": read_text(
            ROOT / "SolomonDarkModLoader/src/logger.cpp"
        ) + read_text(
            ROOT / "SolomonDarkModLoader/src/logger_writer.cpp"
        ),
        "network telemetry": read_text(
            ROOT / "SolomonDarkModLoader/src/network_telemetry.cpp"
        ),
        "local UDP ingress": read_text(
            ROOT / "SolomonDarkModLoader/src/multiplayer_local_transport.cpp"
        ) + read_text(
            ROOT
            / "SolomonDarkModLoader/src/multiplayer_local_transport/"
            "receive_packets.inl"
        ),
    }

    joinable_statics = [
        name
        for name, source in worker_sources.items()
        if re.search(
            r"(?:^|\n)\s*std::thread\s+(?:g_\w+_thread|writer_thread)\s*;",
            source,
        )
    ]
    if joinable_statics:
        raise StaticReTestFailure(
            "process-lifetime workers still register joinable std::thread "
            "destructors: " + ", ".join(joinable_statics)
        )

    missing_native_lifecycle = [
        name
        for name, source in worker_sources.items()
        if not all(
            token in source
            for token in (
                "#include <process.h>",
                "HANDLE ",
                "_beginthreadex(",
                "WaitForSingleObject(",
                "CloseHandle(",
            )
        )
    ]
    if missing_native_lifecycle:
        raise StaticReTestFailure(
            "process-lifetime workers do not use explicit native handles: "
            + ", ".join(missing_native_lifecycle)
        )

    return (
        "process-lifetime workers use explicit handles with no joinable "
        "static destructors"
    )


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
    lua_visual_branch = re.search(
        r"else if \(multiplayer::IsLuaControlledParticipant\(\*participant\)\)"
        r"\s*\{(?P<body>[\s\S]*?)\n\s*\} else \{",
        slot_creation_text,
    )
    if (
        lua_visual_branch is None or
        not re.search(
            r"CreateWizardCloneSourceActor\(\s*"
            r"world_address,\s*"
            r"native_visual_actor_address,\s*"
            r"character_profile,\s*"
            r"x,\s*y,\s*heading,\s*"
            r"&source_actor_address",
            lua_visual_branch.group("body"),
        ) or
        not re.search(
            r"CaptureActorRenderBuildSnapshot\(\s*"
            r"source_actor_address\s*\)"
            r"[\s\S]*DestroyWizardCloneSourceActor\(\s*"
            r"source_actor_address",
            lua_visual_branch.group("body"),
        )
    ):
        raise StaticReTestFailure(
            "Lua gameplay-slot visuals do not run the bot profile through "
            "the native source builder before helper publication")
    if re.search(
        r"CaptureActorRenderBuildSnapshot\(\s*"
        r"native_visual_actor_address\s*\)",
        lua_visual_branch.group("body"),
    ):
        raise StaticReTestFailure(
            "Lua gameplay-slot visuals still reinterpret finalized actor "
            "animation bytes as a reusable appearance descriptor")
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


CI_WORKFLOW = ROOT / ".github/workflows/lua-authoring-contracts.yml"
STATIC_RE_RUNNER = ROOT / "tests/re/run_static_re_tests.py"
# 360 registered contracts today, 13 of which read an artifact CI cannot have.
CI_ELIGIBLE_FLOOR = 375


def _referenced_paths(function: object) -> list[Path]:
    """Every module-level Path a test function names in its own body."""
    import inspect

    module = sys.modules[function.__module__]
    tree = ast.parse(inspect.getsource(function))
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    found: list[Path] = []
    for name in sorted(names):
        value = getattr(module, name, None)
        if isinstance(value, Path):
            found.append(value)
    return found


def test_ci_runs_every_contract_that_needs_no_local_artifact() -> str:
    """CI must run the whole corpus minus a declared, justified exclusion list.

    The previous selector kept CI to modules named `static_lua_*` -- 41 of 360
    contracts. The other 319 passed only when somebody happened to run the suite
    by hand, so the RE corpus had no enforcement at all. Selecting by module
    name also meant a new contract's CI coverage depended on where its file
    happened to live.

    Two ways this could rot, both closed here: a contract could be parked in the
    exclusion list to dodge CI, so every excluded name must actually reach an
    artifact that is outside the repository or gitignored; and the workflow step
    could be narrowed again, so the invocation is pinned.
    """
    import subprocess

    from static_re_test_registry import LOCAL_ARTIFACT_TESTS, TESTS

    registered = {name: function for name, function in TESTS}
    stale = sorted(set(LOCAL_ARTIFACT_TESTS) - set(registered))
    if stale:
        raise StaticReTestFailure(
            "LOCAL_ARTIFACT_TESTS names unregistered contract(s): " + ", ".join(stale)
        )

    # Each exclusion must be real: the test has to name a Path that CI genuinely
    # cannot produce -- outside the checkout, or ignored by git.
    unjustified: list[str] = []
    for name in sorted(LOCAL_ARTIFACT_TESTS):
        candidates = _referenced_paths(registered[name])
        outside = [path for path in candidates if ROOT not in path.parents]
        inside = [path for path in candidates if ROOT in path.parents]
        ignored: list[Path] = []
        if inside:
            probe = subprocess.run(
                ["git", "check-ignore", *[str(path) for path in inside]],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            ignored = [Path(line) for line in probe.stdout.splitlines() if line]
        if not outside and not ignored:
            unjustified.append(name)
    if unjustified:
        raise StaticReTestFailure(
            "excluded from CI without reading an unavailable artifact: "
            + ", ".join(unjustified)
        )

    eligible = [name for name in registered if name not in LOCAL_ARTIFACT_TESTS]
    if len(eligible) < CI_ELIGIBLE_FLOOR:
        raise StaticReTestFailure(
            f"only {len(eligible)} contracts are CI-eligible; floor is "
            f"{CI_ELIGIBLE_FLOOR}. Contracts were removed or quietly excluded."
        )

    runner = read_text(STATIC_RE_RUNNER)
    if "--lua-only" in runner:
        raise StaticReTestFailure(
            "the module-name selector is back in the runner; it silently "
            "excluded 319 of 360 contracts from CI"
        )
    if '"--ci"' not in runner:
        raise StaticReTestFailure("the runner no longer defines --ci")

    workflow = read_text(CI_WORKFLOW)
    # Exact line: a substring check accepts trailing arguments, and the wrong
    # trailing argument is how a step comes to run nothing at all.
    if not re.search(
        r"^\s*run: python tests/re/run_static_re_tests\.py --ci[ \t]*$",
        workflow,
        re.M,
    ):
        raise StaticReTestFailure(
            "the workflow does not run the static RE suite as a bare --ci "
            "invocation"
        )
    if "--lua-only" in workflow:
        raise StaticReTestFailure("the workflow still uses the narrow selector")

    return (
        f"CI runs {len(eligible)} of {len(TESTS)} contracts; the "
        f"{len(LOCAL_ARTIFACT_TESTS)} exclusions each reach a real "
        "outside-the-repo or gitignored artifact"
    )


# Contracts that are defined but deliberately NOT registered, each mapped to the
# exact token its subsystem has since renamed or restructured away.
#
# This is empty, and the census below is what keeps it honest in both
# directions: an unregistered contract that is not named here fails, and a name
# here whose contract has been repaired also fails. Twelve orphans were found
# when the census was written; seven of them named drifted tokens and were
# declared here while the behaviour behind each was re-verified and the contract
# re-expressed against what the code does now. Adding an entry is a last resort:
# rewriting a stale contract's tokens to match today's source WITHOUT re-reading
# the subsystem converts a real gate into a tautology, which is the precise
# failure this file exists to prevent.
STALE_UNREGISTERED_CONTRACTS: dict[tuple[str, str], str] = {}


def test_every_defined_contract_reaches_the_registry() -> str:
    """Every `test_*` a contract module defines must actually be registered.

    `test_ci_runs_every_contract_that_needs_no_local_artifact` proves CI runs
    everything the registry holds, but nothing proved the registry holds
    everything the modules define. It doesn't: the registry enumerates test
    functions by hand, so writing a contract and forgetting the entry produced a
    file that looks like an enforced gate and runs never. Twelve had accumulated
    that way, and seven of them no longer passed -- their subsystems had been
    renamed underneath contracts nobody was running.

    This is the same class as selecting contracts by module name (8595158) and
    naming CI test modules one step at a time (5c5d4e7), one level further down:
    coverage riding on a hand-maintained list instead of on discovery.
    """
    import importlib

    from static_re_test_registry import TESTS

    suite_root = ROOT / "tests/re"
    registered = {(function.__module__, function.__name__) for _, function in TESTS}

    defined: set[tuple[str, str]] = set()
    for path in sorted(suite_root.glob("*.py")):
        if path.name in {"static_re_test_registry.py", "run_static_re_tests.py"}:
            continue
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name.startswith("test_")
            ):
                defined.add((path.stem, node.name))

    unregistered = defined - registered
    undeclared = sorted(unregistered - set(STALE_UNREGISTERED_CONTRACTS))
    if undeclared:
        raise StaticReTestFailure(
            "contract(s) defined but never registered, so they never run: "
            + ", ".join(f"{module}.{name}" for module, name in undeclared)
        )
    vanished = sorted(set(STALE_UNREGISTERED_CONTRACTS) - unregistered)
    if vanished:
        raise StaticReTestFailure(
            "STALE_UNREGISTERED_CONTRACTS names contract(s) that are no longer "
            "unregistered or no longer exist: "
            + ", ".join(f"{module}.{name}" for module, name in vanished)
        )

    # Each declared entry must still be broken, and must still be broken on the
    # token it claims. Otherwise the list becomes a parking space.
    for (module_name, name), token in sorted(STALE_UNREGISTERED_CONTRACTS.items()):
        module = importlib.import_module(module_name)
        source = (suite_root / f"{module_name}.py").read_text(encoding="utf-8")
        if token not in source:
            raise StaticReTestFailure(
                f"{module_name}.{name} is declared stale on {token!r}, but that "
                f"token is not in the contract at all"
            )
        try:
            getattr(module, name)()
        except Exception:
            continue
        raise StaticReTestFailure(
            f"{module_name}.{name} passes now; repair is done, so register it "
            f"instead of leaving it declared stale"
        )

    if not STALE_UNREGISTERED_CONTRACTS:
        return (
            f"all {len(defined)} defined contracts reach the registry, with "
            "none parked as stale"
        )
    return (
        f"all {len(defined)} defined contracts are registered or declared; the "
        f"{len(STALE_UNREGISTERED_CONTRACTS)} declared exclusions each still "
        "fail on the exact drifted token they name"
    )


# Every 40-hex object id a golden records as its own provenance, mapped to the
# git object type it must be and how many times it appears. Pinned so that
# re-recording evidence nobody can re-derive cannot quietly restate where it
# came from.
RECORDED_CAPTURE_SHAS: dict[str, tuple[str, int]] = {
    # G3 enemy-behavior goldens and the tree that commit points at.
    "0ab44c0b482cf3b05ddac637836a9761be9a9042": ("commit", 1),
    "191cc252d3d2dda68bc831127ff759bd71271367": ("tree", 1),
    # G2 projectile goldens.
    "1b9d454da60afefa2cb5f01a0f6e8ce829efebe6": ("commit", 1),
    # G12 scene-composition goldens: one clean base repeated in four captures.
    "50332fc8d53c37bdf83d7ed6a56caf095caf04a1": ("commit", 4),
    # G8 hub/economy goldens: top-level source plus census, trader, and Dig headers;
    # G7 embeds one complete G8 Dig sequence with its original source header.
    "acc4ef5d7a2a03ae4f4b7b3350cb06f13960836d": ("commit", 14),
    # G7 loot goldens: top-level and recorder-derived header source revision.
    "fbfc7502090e8c84ad310f8fa4db5bebc4583bf3": ("commit", 2),
    # G14 input goldens: one campaign SHA repeated across nine captures.
    "2bc3ab13f3d05e26238954e5264c3a86967bd1d4": ("commit", 9),
    # G13 session-flow golden: one clean recorder SHA in both section headers.
    "3c49c4eef6d4b91fe40b58cad99678e119007d84": ("commit", 2),
    # G4 animation goldens: one clean capture commit/tree pair repeated in the
    # top-level header and each of the nine recording headers.
    "d4c22e0560e0e12aba14c40787909c96cead4030": ("commit", 10),
    "17b06f96dc49cdd67648f674c90b0ee6815fe863": ("tree", 10),
    # G9 retail HUD golden: one clean recorder commit/tree pair.
    "2686eaf9fb55b8c8d5aa3e5d95cba88c3045a91d": ("commit", 1),
    "6b58f4db1ba8ce5c5018d6278940efb6f9a6dff3": ("tree", 1),
    # loadre class/loadout golden: one clean base in the fixture header.
    "c36f0a81721fa5d3dc2edda65f3347354974b2f0": ("commit", 1),
    # G10 save-format and G6 progression goldens share one clean base commit.
    "8deaa9400cc1df33748976aa0464e8016c11a46b": ("commit", 2),
    # G5 audio dispatch golden: one clean capture commit/tree pair.
    "508c5be780692c8e30a8c68d395b31d27f0866e8": ("commit", 1),
    "0a0a49fedbf242c5be02760a71f4ff9468b4623f": ("tree", 1),
    # G6 progression golden additionally records that base commit's tree.
    "a3bc978196605af4ec9b5f6a3be9c0660cd1ae40": ("tree", 1),
    # G1 movement and RNG goldens, and the tree that commit points at.
    "51d81ed3705468b2c96cdd5a072eb2e9b0f8db0b": ("commit", 2),
    "55ea6c0c646df739f3243a01d0cd35c4d6f9b786": ("tree", 2),
    # G1 float RNG goldens: the capture commit/tree pair is preserved in the
    # externally sealed source bundle declared below, once in each of 9 headers.
    "04c02dc98086bc0687f1906ba644a19a059e9a45": ("archived-commit", 9),
    "495cec38cfb16fa0dfe5d4a80d0a58145a074bac": ("archived-tree", 9),
    # G11 settled menu goldens: every recorder-derived commit/tree object is
    # preserved in the evidence bundle declared below.
    "18a23950d98f22a2eee61302f29c4e7a7c03069a": ("archived-commit", 6),
    "1c009e2eb79c9dfdc6d22a71bfb2c14b8969ac34": ("archived-tree", 15),
    "3a12f89bb61f788f2b1c9dca140cd556a2448a7d": ("archived-tree", 45),
    "405bb0f697fcdf484f304f0d5f38224d39a6ae70": ("archived-commit", 50),
    "433162e0f78ce421211d65dc693fedfe2630e357": ("archived-tree", 6),
    "4ae5370977019c1c20813fa17d5141f32cd50968": ("archived-commit", 15),
    "6363b637a5d2840d23f31430eaf0ed9bf32ae63b": ("archived-commit", 45),
    "68a3735ae342561623fa135b2c0e1243c673e111": ("archived-commit", 76),
    "70ba8c80324b23144313be6968bad9917c2b4019": ("archived-tree", 1),
    "7210d566ffe62a526eb6018f5e5fa86aaa458dbd": ("archived-tree", 76),
    "b3eafc6c4ebccd574f534796203c7c7bea702280": ("archived-commit", 1),
    "b6aaa8f1f9752963b570384a29a6082228c2cbfa": ("archived-tree", 50),
    "d709ce1b23b819cd2fda920cfc1613a773c54f5c": ("archived-commit", 1),
    "dbf36ac822163bd3ef8308994ee666a1963792bc": ("archived-commit", 10),
    "fe13cd29846a7c4b3e450b1a4b312fccda65944b": ("archived-tree", 10),
}

# The G10 Region1 payload happens to be exactly twenty bytes, so its ordinary
# hexadecimal serialization has the same lexical shape as a Git object id.
# Name every location rather than exempting the value by count: moving it into
# a provenance field must not make the capture-object census silently ignore it.
NON_PROVENANCE_HEX40_LOCATIONS: dict[str, tuple[str, ...]] = {
    "03000000f9070000931300009413000000000000": (
        "tests/fixtures/webgame/save-format-goldens.json.captures[0].files[1].tree.root.children[4].payload_hex",
        "tests/fixtures/webgame/save-format-goldens.json.captures[1].files[1].tree.root.children[4].payload_hex",
        "tests/fixtures/webgame/save-format-goldens.json.captures[2].files[1].tree.root.children[4].payload_hex",
    ),
}

# The legacy G11 capture commits were unverifiable and required this explicit
# declaration. Settlement v2.22 replaced every active G11 fixture and archived
# every new recorder-derived commit/tree object, so no active capture remains in
# this exception class.
UNRECOVERABLE_CAPTURE_COMMITS: dict[str, str] = {}

# The float capture ran after float-only code and contemporaneous menu-recorder
# work had been committed together in the isolated campaign clone. Rebasing
# that commit onto main would change the SHA recorded by the immutable golden;
# merging it would land the superseded menu-recorder history. Instead, this
# thin Git bundle preserves the exact commit and tree outside the repository,
# with acc4ef5 as its prerequisite. CI cannot see evidence-bundle artifacts, so
# its file hash is a provenance constant. REPORT-floatland.md records an
# end-to-end import that first proves the commit absent from an acc4ef5-only
# repository, then imports the bundle and resolves this exact commit/tree pair.
FLOAT_CAPTURE_SOURCE_ARCHIVE = {
    "evidence_path": "float-capture-source.bundle",
    "sha256": "eb3e6b83ef617d09be583be6b10017df745c8d2c358321cad9b48e6404089737",
    "bytes": 24013,
    "prerequisite_commit": "acc4ef5d7a2a03ae4f4b7b3350cb06f13960836d",
    "capture_commit": "04c02dc98086bc0687f1906ba644a19a059e9a45",
    "capture_tree": "495cec38cfb16fa0dfe5d4a80d0a58145a074bac",
    "bundle_ref": "refs/codex-evidence/goldfix-float-source",
}
MENU_CAPTURE_SOURCE_ARCHIVE = {
    "evidence_path": "raw-v9/profile-select-new-game-edge/v222-promotion/menufix-capture-source.bundle",
    "sha256": "c9d521db6917d1ff997604aaf7038537a510673548a5bd091ad315e7ac78fb50",
    "bytes": 634629,
    "prerequisite_commit": "c24fc3cce419939cafe8b27565ed04308df60467",
    "heads": {
        "refs/codex-evidence/menufix-v222/source-18a23950d98f": "18a23950d98f22a2eee61302f29c4e7a7c03069a",
        "refs/codex-evidence/menufix-v222/source-405bb0f697fc": "405bb0f697fcdf484f304f0d5f38224d39a6ae70",
        "refs/codex-evidence/menufix-v222/source-4ae537097701": "4ae5370977019c1c20813fa17d5141f32cd50968",
        "refs/codex-evidence/menufix-v222/source-6363b637a5d2": "6363b637a5d2840d23f31430eaf0ed9bf32ae63b",
        "refs/codex-evidence/menufix-v222/source-68a3735ae342": "68a3735ae342561623fa135b2c0e1243c673e111",
        "refs/codex-evidence/menufix-v222/source-b3eafc6c4ebc": "b3eafc6c4ebccd574f534796203c7c7bea702280",
        "refs/codex-evidence/menufix-v222/source-d709ce1b23b8": "d709ce1b23b819cd2fda920cfc1613a773c54f5c",
        "refs/codex-evidence/menufix-v222/source-dbf36ac82216": "dbf36ac822163bd3ef8308994ee666a1963792bc",
    },
    "recorded_object_types": {
        "18a23950d98f22a2eee61302f29c4e7a7c03069a": "commit",
        "1c009e2eb79c9dfdc6d22a71bfb2c14b8969ac34": "tree",
        "3a12f89bb61f788f2b1c9dca140cd556a2448a7d": "tree",
        "405bb0f697fcdf484f304f0d5f38224d39a6ae70": "commit",
        "433162e0f78ce421211d65dc693fedfe2630e357": "tree",
        "4ae5370977019c1c20813fa17d5141f32cd50968": "commit",
        "6363b637a5d2840d23f31430eaf0ed9bf32ae63b": "commit",
        "68a3735ae342561623fa135b2c0e1243c673e111": "commit",
        "70ba8c80324b23144313be6968bad9917c2b4019": "tree",
        "7210d566ffe62a526eb6018f5e5fa86aaa458dbd": "tree",
        "b3eafc6c4ebccd574f534796203c7c7bea702280": "commit",
        "b6aaa8f1f9752963b570384a29a6082228c2cbfa": "tree",
        "d709ce1b23b819cd2fda920cfc1613a773c54f5c": "commit",
        "dbf36ac822163bd3ef8308994ee666a1963792bc": "commit",
        "fe13cd29846a7c4b3e450b1a4b312fccda65944b": "tree",
    },
}
ARCHIVED_CAPTURE_OBJECTS = {
    FLOAT_CAPTURE_SOURCE_ARCHIVE["capture_commit"]: "commit",
    FLOAT_CAPTURE_SOURCE_ARCHIVE["capture_tree"]: "tree",
    **MENU_CAPTURE_SOURCE_ARCHIVE["recorded_object_types"],
}

FIXTURE_ROOT = ROOT / "tests/fixtures"

# The fixtures whose headers record BOTH a source commit and its tree, so the
# pair can be checked against itself. Named rather than counted: a count floor
# says "some fixtures still do this" and needs editing whenever one is added,
# while naming them says which ones, and fails with the name of whichever
# stopped. New paired fixtures are welcome and need no entry here -- this set is
# a floor on the sweep, not a whitelist of what it may examine.
COMMIT_TREE_PAIRED_FIXTURES = frozenset(
    {
        "webgame/movement-goldens.json",
        "webgame/enemy-behavior-goldens.json",
        "webgame/rng-goldens.json",
        "webgame/audio-event-goldens.json",
        "webgame/progression-goldens.json",
    }
)

_HEX40 = re.compile(r"^[0-9a-f]{40}$")


def _git_capture(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True
    )


def _collect_recorded_shas() -> dict[str, list[str]]:
    """Every 40-hex string in every committed fixture, with where it appears."""
    found: dict[str, list[str]] = {}

    def walk(node: object, path: str, origin: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, f"{path}.{key}", origin)
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]", origin)
        elif isinstance(node, str) and _HEX40.match(node):
            found.setdefault(node, []).append(f"{origin}{path}")

    for path in sorted(FIXTURE_ROOT.rglob("*.json")):
        walk(
            json.loads(path.read_text(encoding="utf-8")),
            "",
            path.relative_to(ROOT).as_posix(),
        )
    return found


def test_recorded_capture_provenance_resolves_or_is_declared() -> str:
    """A recorded capture commit must name a commit that actually exists.

    The G11 contract checked that `capture_commit` was forty hex characters and
    nothing else, which is the same shape as recording a sha256 and only
    asserting its length (05ea10a): the field reads like provenance a reviewer
    could follow, and following it was never possible. Checking it for real
    found that all sixty-six G11 capture commits name objects that exist neither
    here nor on the remote, while G1, G2 and G14 all recorded ancestors of main.

    Commits are required to be ancestors of HEAD rather than merely present:
    presence depends on which refs a clone happens to have fetched, and a
    contract must not pass or fail on that. The one archived float-capture
    commit/tree pair is deliberately not merged because its isolated history
    also contains the superseded menu recorder; an evidence-bundle declaration
    and end-to-end import receipt preserve those exact objects instead.
    """
    shallow = _git_capture("rev-parse", "--is-shallow-repository")
    if shallow.returncode != 0:
        raise StaticReTestFailure(
            "capture-provenance census needs a git repository: "
            + shallow.stderr.strip()
        )
    if shallow.stdout.strip() != "false":
        raise StaticReTestFailure(
            "capture-provenance census cannot run against a shallow clone: "
            "check out with fetch-depth 0"
        )

    found = _collect_recorded_shas()
    for value, expected_locations in NON_PROVENANCE_HEX40_LOCATIONS.items():
        actual_locations = tuple(sorted(found.pop(value, ())))
        if actual_locations != expected_locations:
            raise StaticReTestFailure(
                "the declared non-provenance native-save payload moved or changed: "
                f"value={value} expected={list(expected_locations)} "
                f"actual={list(actual_locations)}"
            )
    observed = {sha: len(paths) for sha, paths in found.items()}
    expected = {sha: count for sha, (_, count) in RECORDED_CAPTURE_SHAS.items()}
    if observed != expected:
        added = sorted(set(observed) - set(expected))
        dropped = sorted(set(expected) - set(observed))
        moved = sorted(
            f"{sha} {expected[sha]}->{observed[sha]}"
            for sha in set(observed) & set(expected)
            if observed[sha] != expected[sha]
        )
        raise StaticReTestFailure(
            "the recorded capture-provenance census drifted: "
            f"new={added} gone={dropped} recount={moved}"
        )

    expected_archive = {
        "evidence_path": "float-capture-source.bundle",
        "sha256": "eb3e6b83ef617d09be583be6b10017df745c8d2c358321cad9b48e6404089737",
        "bytes": 24013,
        "prerequisite_commit": "acc4ef5d7a2a03ae4f4b7b3350cb06f13960836d",
        "capture_commit": "04c02dc98086bc0687f1906ba644a19a059e9a45",
        "capture_tree": "495cec38cfb16fa0dfe5d4a80d0a58145a074bac",
        "bundle_ref": "refs/codex-evidence/goldfix-float-source",
    }
    if FLOAT_CAPTURE_SOURCE_ARCHIVE != expected_archive:
        raise StaticReTestFailure(
            "float capture source archive no longer pins the exact bundle hash, prerequisite, commit, tree, and ref"
        )
    expected_menu_archive = {
        "evidence_path": "raw-v9/profile-select-new-game-edge/v222-promotion/menufix-capture-source.bundle",
        "sha256": "c9d521db6917d1ff997604aaf7038537a510673548a5bd091ad315e7ac78fb50",
        "bytes": 634629,
        "prerequisite_commit": "c24fc3cce419939cafe8b27565ed04308df60467",
        "heads": {
            "refs/codex-evidence/menufix-v222/source-18a23950d98f": "18a23950d98f22a2eee61302f29c4e7a7c03069a",
            "refs/codex-evidence/menufix-v222/source-405bb0f697fc": "405bb0f697fcdf484f304f0d5f38224d39a6ae70",
            "refs/codex-evidence/menufix-v222/source-4ae537097701": "4ae5370977019c1c20813fa17d5141f32cd50968",
            "refs/codex-evidence/menufix-v222/source-6363b637a5d2": "6363b637a5d2840d23f31430eaf0ed9bf32ae63b",
            "refs/codex-evidence/menufix-v222/source-68a3735ae342": "68a3735ae342561623fa135b2c0e1243c673e111",
            "refs/codex-evidence/menufix-v222/source-b3eafc6c4ebc": "b3eafc6c4ebccd574f534796203c7c7bea702280",
            "refs/codex-evidence/menufix-v222/source-d709ce1b23b8": "d709ce1b23b819cd2fda920cfc1613a773c54f5c",
            "refs/codex-evidence/menufix-v222/source-dbf36ac82216": "dbf36ac822163bd3ef8308994ee666a1963792bc",
        },
        "recorded_object_types": {
            sha: recorded_kind.removeprefix("archived-")
            for sha, (recorded_kind, _) in RECORDED_CAPTURE_SHAS.items()
            if recorded_kind in {"archived-commit", "archived-tree"}
            and sha
            not in {
                expected_archive["capture_commit"],
                expected_archive["capture_tree"],
            }
        },
    }
    if MENU_CAPTURE_SOURCE_ARCHIVE != expected_menu_archive:
        raise StaticReTestFailure(
            "menufix capture source archive no longer pins the exact bundle hash, prerequisite, heads, and recorded object types"
        )
    expected_archived_objects = {
        expected_archive["capture_commit"]: "commit",
        expected_archive["capture_tree"]: "tree",
        **expected_menu_archive["recorded_object_types"],
    }
    if ARCHIVED_CAPTURE_OBJECTS != expected_archived_objects:
        raise StaticReTestFailure(
            "float capture source archive lookup is incomplete or ambiguous for its commit/tree pair"
        )

    for sha, (kind, _) in sorted(RECORDED_CAPTURE_SHAS.items()):
        archived_kind = ARCHIVED_CAPTURE_OBJECTS.get(sha)
        if archived_kind is not None:
            if kind != f"archived-{archived_kind}":
                raise StaticReTestFailure(
                    f"archived capture object {sha} is not classified as its archived {archived_kind}"
                )
            continue
        declared = sha in UNRECOVERABLE_CAPTURE_COMMITS
        if (kind == "absent") != declared:
            raise StaticReTestFailure(
                f"{sha} is recorded as {kind!r} but "
                f"{'is' if declared else 'is not'} declared unrecoverable"
            )
        probe = _git_capture("cat-file", "-t", sha)
        actual = probe.stdout.strip() if probe.returncode == 0 else "absent"
        if declared:
            if actual != "absent":
                raise StaticReTestFailure(
                    f"{sha} is declared unrecoverable but resolves to a {actual}; "
                    f"the evidence was re-captured, so drop the declaration"
                )
            continue
        if actual != kind:
            raise StaticReTestFailure(
                f"{sha} is recorded as a {kind} but git calls it {actual!r}"
            )
        if kind == "commit":
            reachable = _git_capture("merge-base", "--is-ancestor", sha, "HEAD")
            if reachable.returncode != 0:
                raise StaticReTestFailure(
                    f"{sha} is recorded as capture provenance but is not an "
                    f"ancestor of HEAD, so the capture cannot be re-derived"
                )

    # Wherever a header records both, the tree must be the one that commit points
    # at -- otherwise the pair is two unrelated facts wearing a matching prefix.
    #
    # The two `continue`s below are what make this loop worth guarding. They are
    # there so a fixture that records neither sha is not treated as a failure,
    # but they would equally skip a fixture that dropped both, or the whole
    # sweep if the fixture tree moved -- and the pair count was only ever
    # reported in the return line, never asserted, so zero agreements read
    # exactly like agreement. A header that records one sha without the other is
    # worse still: it was silently skipped while looking like provenance.
    checked: set[str] = set()
    half_recorded: list[str] = []
    for path in sorted(FIXTURE_ROOT.rglob("*.json")):
        header = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(header, dict):
            continue
        header = header.get("header")
        if not isinstance(header, dict):
            continue
        relative = path.relative_to(FIXTURE_ROOT).as_posix()
        commit = header.get("source_commit_sha")
        tree = header.get("source_tree_sha")
        if not isinstance(commit, str) or not isinstance(tree, str):
            if isinstance(commit, str) or isinstance(tree, str):
                half_recorded.append(relative)
            continue
        checked.add(relative)
        resolved = _git_capture("rev-parse", f"{commit}^{{tree}}")
        if resolved.returncode != 0 or resolved.stdout.strip() != tree:
            raise StaticReTestFailure(
                f"{path.name} records tree {tree[:12]} for commit "
                f"{commit[:12]}, which points at "
                f"{resolved.stdout.strip()[:12] or 'nothing'}"
            )
    if half_recorded:
        raise StaticReTestFailure(
            "fixture header(s) record a source commit without its tree, or a "
            "tree without its commit, so the pair cannot be checked against "
            f"itself: {', '.join(sorted(half_recorded))}"
        )
    unswept = COMMIT_TREE_PAIRED_FIXTURES - checked
    if unswept:
        raise StaticReTestFailure(
            "the commit/tree agreement sweep no longer reaches "
            f"{', '.join(sorted(unswept))}; the fixture moved or dropped its "
            "recorded provenance, so the check above is passing on silence"
        )

    findings = (
        ROOT / "docs/reverse-engineering/native-menus-and-boot.md"
    ).read_text(encoding="utf-8")
    flattened = " ".join(findings.split())
    for token in (
        "menufix-capture-source.bundle",
        "c9d521db6917d1ff997604aaf7038537a510673548a5bd091ad315e7ac78fb50",
        "all 15 recorded commit/tree objects",
    ):
        if token not in flattened:
            raise StaticReTestFailure(
                f"G11 must document its archived capture provenance; "
                f"missing {token!r}"
            )

    live = (
        len(RECORDED_CAPTURE_SHAS)
        - len(UNRECOVERABLE_CAPTURE_COMMITS)
        - len(ARCHIVED_CAPTURE_OBJECTS)
    )
    return (
        f"{live} of {len(RECORDED_CAPTURE_SHAS)} recorded capture object ids "
        f"resolve and are ancestors of HEAD, {len(ARCHIVED_CAPTURE_OBJECTS)} "
        f"capture objects are externally archived, {len(checked)} commit/tree pairs "
        f"agree (including all {len(COMMIT_TREE_PAIRED_FIXTURES)} named), "
        f"and the {len(UNRECOVERABLE_CAPTURE_COMMITS)} active capture commits "
        "in the unrecoverable exception class remain absent"
    )


PYTHON_SUITE_RUNNER = ROOT / "tests/run_python_suite.py"

# CI ran 30 of the 84 test modules before the runner discovered them.
PYTHON_MODULE_FLOOR = 77

# Image.get_flattened_data() landed in Pillow 12. Two verifiers call it
# unguarded, so a pin below 12 is a broken CI, not a conservative one.
PILLOW_MAJOR_FLOOR = 12


def _load_python_suite_runner():
    """Import tests/run_python_suite.py without putting tests/ on sys.path."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_run_python_suite_probe", PYTHON_SUITE_RUNNER
    )
    if spec is None or spec.loader is None:
        raise StaticReTestFailure(f"cannot import {PYTHON_SUITE_RUNNER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ci_runs_every_test_module_it_can() -> str:
    """CI must discover test modules, not name them one workflow step at a time.

    Naming them made coverage depend on whether somebody remembered to write
    the step: 54 of 84 modules never ran, which is how two verifiers came to be
    hard-broken on the exact Pillow version CI pinned.
    """
    runner = _load_python_suite_runner()
    excluded = runner.MACHINE_DEPENDENT_TESTS

    discovered = sorted(path.stem for path in (ROOT / "tests").glob("test_*.py"))
    stale = sorted(set(excluded) - set(discovered))
    if stale:
        raise StaticReTestFailure(
            "MACHINE_DEPENDENT_TESTS names modules that do not exist: "
            + ", ".join(stale)
        )
    if len(excluded) > runner.MAX_MACHINE_DEPENDENT:
        raise StaticReTestFailure(
            f"{len(excluded)} modules are excluded from CI; the ceiling is "
            f"{runner.MAX_MACHINE_DEPENDENT}"
        )
    missing_reason = sorted(name for name, why in excluded.items() if not why.strip())
    if missing_reason:
        raise StaticReTestFailure(
            "excluded without a stated reason: " + ", ".join(missing_reason)
        )

    selected = [name for name in discovered if name not in excluded]
    if len(selected) < PYTHON_MODULE_FLOOR:
        raise StaticReTestFailure(
            f"only {len(selected)} test modules are CI-eligible; floor is "
            f"{PYTHON_MODULE_FLOOR}. Modules were removed or quietly excluded."
        )

    workflow = read_text(CI_WORKFLOW)
    # Exact line, not a substring: `... run_python_suite.py --list` prints the
    # module names and runs nothing, and a substring check calls that covered.
    if not re.search(
        r"^\s*run: python tests/run_python_suite\.py[ \t]*$", workflow, re.M
    ):
        raise StaticReTestFailure(
            "the workflow does not run the discovered Python suite as a bare "
            "invocation; any trailing argument can make the step vacuous"
        )
    if "python -m unittest tests." in workflow:
        raise StaticReTestFailure(
            "the workflow names test modules by hand again; that is how 54 of "
            "84 modules came to never run"
        )

    # The pin and the pixel API have to move together. They drifted once: CI
    # pinned Pillow 11 while the verifiers called a Pillow 12 method.
    pins = re.findall(r"Pillow==(\d+)\.(\d+)\.(\d+)", workflow)
    if not pins:
        raise StaticReTestFailure("the workflow does not pin Pillow")
    for major, minor, patch in pins:
        if int(major) < PILLOW_MAJOR_FLOOR:
            raise StaticReTestFailure(
                f"CI pins Pillow {major}.{minor}.{patch}, which has no "
                "Image.get_flattened_data(); the image verifiers call it "
                "unguarded"
            )

    # One API on one version: no straddle, no deprecated spelling.
    straddled: list[str] = []
    deprecated: list[str] = []
    this_file = Path(__file__).resolve()
    for path in sorted((ROOT / "tools").rglob("*.py")) + sorted(
        (ROOT / "tests").rglob("*.py")
    ):
        if path.resolve() == this_file:
            continue  # this contract names both spellings in order to ban them
        text = read_text(path)
        if '"get_flattened_data"' in text or "'get_flattened_data'" in text:
            straddled.append(path.relative_to(ROOT).as_posix())
        if ".getdata()" in text:
            deprecated.append(path.relative_to(ROOT).as_posix())
    if straddled:
        raise StaticReTestFailure(
            "the Pillow version straddle is back in: " + ", ".join(straddled)
        )
    if deprecated:
        raise StaticReTestFailure(
            "deprecated Image.getdata() is back in: " + ", ".join(deprecated)
        )

    return (
        f"CI discovers and runs {len(selected)} of {len(discovered)} test "
        f"modules; the {len(excluded)} exclusions each state why they need a "
        f"real machine, and the Pillow pin provides get_flattened_data()"
    )
