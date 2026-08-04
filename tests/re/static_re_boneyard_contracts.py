"""Static contracts for the native Boneyard container and committed fixture."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from static_re_contract_support import ROOT, StaticReTestFailure


sys.path.insert(0, str(ROOT / "tools"))
import decode_boneyard_scripts  # noqa: E402
import inspect_boneyard  # noqa: E402


FIXTURE = ROOT / "tests/fixtures/boneyards/flat_multiplayer_test.boneyard"
EXPECTED_SHA256 = "7c7d23f2fbfcdf73b5bb7f4af0f836cc9d199997fe9c7dd38183c7659b6d949d"
LOADING_BACKGROUND_SHA256 = (
    "251365e025129972707b436d441d52ae2c5f8199bc3f80a1c4e03b2a28a1180c"
)


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_flat_boneyard_fixture_matches_native_syncbuffer_envelope() -> str:
    data = FIXTURE.read_bytes()
    actual_sha256 = hashlib.sha256(data).hexdigest()
    if actual_sha256 != EXPECTED_SHA256:
        raise StaticReTestFailure(
            f"flat Boneyard fixture changed: expected={EXPECTED_SHA256} actual={actual_sha256}"
        )

    parsed = inspect_boneyard.parse_boneyard(data, str(FIXTURE))
    summary = inspect_boneyard.summarize(parsed)
    if summary["syncBuffer"] != {
        "chunks": 7721,
        "maxDepth": 9,
        "namedBuffers": 0,
    }:
        raise StaticReTestFailure(
            f"flat Boneyard SyncBuffer shape changed: {summary['syncBuffer']}"
        )
    if summary["arenaSections"] != 13 or len(summary["regionLayoutSections"]) != 14:
        raise StaticReTestFailure("flat Boneyard native Arena/RegionLayout envelope changed")

    sections = summary["regionLayoutSections"]
    if any(
        sections[index]["objectManager"]["count"] != 0
        for index in inspect_boneyard.OBJECT_MANAGER_SECTIONS - {13}
    ):
        raise StaticReTestFailure("flat editor fixture unexpectedly contains placed objects")
    if sections[11].get("recordCount") != 0:
        raise StaticReTestFailure("flat editor fixture unexpectedly contains sprite placements")
    if sections[13]["objectManager"] != {
        "count": 1,
        "types": [{"id": 6006, "name": "TimeLine", "count": 1}],
    }:
        raise StaticReTestFailure("flat editor fixture lost its stock default TimeLine")
    return "stock-created flat Boneyard has the exact native SyncBuffer and RegionLayout envelope"


def test_boneyard_parser_rejects_empty_truncated_and_trailing_files() -> str:
    valid = FIXTURE.read_bytes()
    invalid_cases = {
        "empty": b"",
        "truncated": valid[:-1],
        "trailing": valid + b"\0",
        "wrong root child count": valid[:4] + b"\x02\0\0\0" + valid[8:],
    }
    accepted: list[str] = []
    for name, payload in invalid_cases.items():
        try:
            inspect_boneyard.parse_boneyard(payload, name)
        except inspect_boneyard.BoneyardFormatError:
            continue
        accepted.append(name)
    if accepted:
        raise StaticReTestFailure(
            "Boneyard parser accepted invalid cases: " + ", ".join(accepted)
        )
    return "Boneyard parser rejects empty, truncated, trailing, and malformed envelopes"


def test_boneyard_scripting_model_and_runtime_anchors_are_registered() -> str:
    findings = _read("docs/reverse-engineering/boneyard-scripting.md")
    system_doc = _read("docs/reverse-engineering/boneyard-system.md")
    layout = _read("config/binary-layout.ini")
    decoder = _read("tools/decode_boneyard_scripts.py")

    required_findings = (
        "0x00684360",
        "0x00686400",
        "0x00683C10",
        "0x00684610",
        "0x0068B060",
        "0x00689750",
        "0x00646F80",
        "0x00652040",
        "0x0046E390",
        "0x0046C9A0",
        "0x0046D000",
        "0x004B4EC0",
        "0x004B5EF0",
        "0x004B6750",
        "94 menu registrations",
        "92 unique action IDs",
        "`1014` is runtime-only",
        "Alpha Arena.boneyard",
        "d596b4915140f5faa23fd1286e3d622c6189ecb00b9667f5e7b3444a84b8322b",
        "57310",
        "Rotten Tom",
    )
    missing_findings = [token for token in required_findings if token not in findings]
    if missing_findings:
        raise StaticReTestFailure(
            "Boneyard scripting RE map is incomplete: " + ", ".join(missing_findings)
        )

    if "boneyard-scripting.md" not in system_doc:
        raise StaticReTestFailure("Boneyard system doc does not link the scripting RE map")

    required_layout = (
        "[gameplay.boneyard_scripting_re]",
        "bonedit_action_build=0x004B6750",
        "timeline_sync=0x00646F80",
        "timeline_tick=0x0046E390",
        "timeline_event_activate=0x0046C9A0",
        "spawner_tick=0x0046D000",
        "codeline_sync=0x00683C10",
        "trigger_sync=0x00684360",
        "trigger_control_sync=0x00686400",
        "script_thread_tick=0x0068B060",
        "script_dispatch=0x00689750",
        "monster_recipe_sync=0x0063E890",
        "npc_recipe_sync=0x0063EBD0",
        "boneyard_uid_relink=0x0064BC40",
    )
    missing_layout = [token for token in required_layout if token not in layout]
    if missing_layout:
        raise StaticReTestFailure(
            "Boneyard scripting binary-layout anchors are incomplete: "
            + ", ".join(missing_layout)
        )

    required_decoder = (
        "TRIGGER_TYPES =",
        "PREDICATES =",
        "ACTIONS =",
        "TIMELINE_EVENT_TYPES =",
        "SPAWN_RECORD_TYPES =",
        "def decode_boneyard(",
        "def _decode_code_body(",
        "def _decode_trigger_control(",
        "def _decode_timeline(",
        "def _decode_monster_recipe(",
        "def _decode_npc_recipe(",
    )
    missing_decoder = [token for token in required_decoder if token not in decoder]
    if missing_decoder:
        raise StaticReTestFailure(
            "Boneyard scripting decoder surface is incomplete: "
            + ", ".join(missing_decoder)
        )
    if len(decode_boneyard_scripts.ACTIONS) != 92:
        raise StaticReTestFailure("Bonedit action map no longer contains 92 unique IDs")
    missing_action_rows = [
        f"{action_id}:{name}"
        for action_id, name in decode_boneyard_scripts.ACTIONS.items()
        if f"| {action_id} | {name} |" not in findings
    ]
    if missing_action_rows:
        raise StaticReTestFailure(
            "Boneyard scripting doc omits Bonedit action rows: "
            + ", ".join(missing_action_rows)
        )
    if set(range(1001, 1097)) - set(decode_boneyard_scripts.ACTIONS) != {
        1014,
        1021,
        1022,
        1050,
    }:
        raise StaticReTestFailure("Bonedit action/runtime gap map changed")
    return (
        "Trigger, ScriptThread, CodeLine, TimeLine, TimeLineEvent, Spawner, "
        "recipe, Bonedit, and Alpha decode anchors are registered"
    )


def test_default_boneyard_load_seed_and_compact_decor_findings_are_registered() -> str:
    findings = _read(
        "docs/reverse-engineering/native-default-boneyard-load-seed-and-decor.md"
    )
    layout = _read("config/binary-layout.ini")

    required_findings = (
        "0x0058E8C0",
        "0x005BB970",
        "0x005CFA80",
        "0x0046EA90",
        "0x0046DC60",
        "0x0046D7B0",
        "0x006388B0",
        "0x0062CB00",
        "0x006531B0",
        "0x00818B08",
        "0x00818B10",
        "ReinitializeAppliedRunGenerationSeedForArenaCreate",
        "Generated `play.boneyard` bytes",
        "Tree/Scrub, Gravestone, Building, Goodie, Road, Fence, terrain, and compact decor",
        "80 4E 18 01",
        "C6 46 18 01",
        "Tree `+0x148/+0x14C/+0x150` sway state is not serialized",
        "Scrub `+0x134` animation phase",
        "Goodie `+0x144` is serialized and conditionally consumed",
        "0x004717E9",
        "0x00471805",
        "0x004723A6",
        "0x004723C2",
        "0x004712BB",
        "0x004726E3",
        "0x006287D0",
        "0x00622DC0",
        "0x00608912",
        "0x0045A556",
        "Heartmonger death path `0x0049FB60`",
        "0x00649D10",
        "| 21–24 | Large irregular ground rocks and boulders",
        "native-order render-input tables plus exact matched-camera decor pixels",
        "protocol version must remain unchanged",
    )
    missing_findings = [token for token in required_findings if token not in findings]
    if missing_findings:
        raise StaticReTestFailure(
            "default Boneyard RE map is incomplete: " + ", ".join(missing_findings)
        )

    required_layout = (
        "default_boneyard_selection_dispatch=0x0058E8C0",
        "default_boneyard_gameplay_loader=0x005BB970",
        "gameplay_start_finalize=0x005CFA80",
        "boneyard_loader=0x0046DC60",
        "boneyard_procedural_create_save=0x0046D7B0",
        "boneyard_generator=0x006388B0",
        "boneyard_tree_generator=0x0062CB00",
        "boneyard_materialize=0x006531B0",
        "region_layout_sync=0x00653660",
        "arena_compact_decor_update=0x00470A90",
        "arena_world_render=0x00470EE0",
        "arena_marker_primary_tint_rng=0x004712BB",
        "arena_marker_tint_scale=0x00785D34",
        "arena_marker_tint_bias=0x00784E20",
        "arena_compact_render_loop=0x004716B1",
        "arena_compact_ambient_kind_guard=0x004717E9",
        "arena_compact_ambient_rng_gate=0x00471805",
        "arena_compact_ambient_rng_x=0x0047182A",
        "arena_compact_ambient_rng_y=0x0047184A",
        "arena_compact_ambient_rng_lifetime=0x004718D5",
        "arena_compact_ambient_spawn=0x0047191C",
        "arena_secondary_ambient_kind_guard=0x004723A6",
        "arena_secondary_ambient_rng_gate=0x004723C2",
        "arena_secondary_ambient_rng_x=0x004723F1",
        "arena_secondary_ambient_rng_y=0x0047240D",
        "arena_secondary_ambient_rng_lifetime=0x00472479",
        "arena_secondary_ambient_rng_scale=0x00472493",
        "arena_secondary_ambient_spawn=0x004724E4",
        "arena_marker_secondary_tint_rng=0x004726E3",
        "arena_ambient_effect_spawn=0x00649D10",
        "scenery_base_ctor=0x006287D0",
        "scenery_base_serialize=0x00622DC0",
        "scenery_base_tick=0x00624AC0",
        "tree_tick=0x005F1C50",
        "tree_render_main=0x00608480",
        "tree_render_overlay_common_scalar_read=0x00608912",
        "scrub_ctor_rng_call=0x005E40A4",
        "scrub_tick=0x005E40D0",
        "scrub_tick_rng_call=0x005E40E2",
        "scrub_serialize=0x005E40F0",
        "scrub_render=0x00620120",
        "goodie_ctor=0x005E3D60",
        "goodie_serialize=0x005E3DD0",
        "goodie_render=0x0061F070",
        "road_serialize=0x0063EAA0",
        "fence_spec_serialize=0x0063EB70",
        "terrain_serialize=0x00651720",
        "native_rng_construct=0x00401110",
        "native_rng_initialize=0x00401120",
        "native_rng_integer=0x00401170",
        "native_rng_float=0x00401310",
        "native_global_rng_state=0x00818B08",
        "native_global_rng_state_object=0x00818B10",
        "flicker_light_ctor=0x004550B0",
        "flicker_light_render=0x0045A510",
        "flicker_light_render_rng_call=0x0045A556",
        "heartmonger_death_flicker_light_creator=0x0049FB60",
        "actor_world_compact_decoration_list=0x8ADC",
        "boneyard_arena_ambient_kind=0x8F20",
        "boneyard_compact_flags=0x18",
        "boneyard_compact_bounds_left=0x1C",
        "boneyard_compact_bounds_top=0x20",
        "boneyard_compact_bounds_right=0x24",
        "boneyard_compact_bounds_bottom=0x28",
        "boneyard_compact_runtime_size=0x2C",
        "boneyard_compact_serialized_size=0x19",
    )
    missing_layout = [token for token in required_layout if token not in layout]
    if missing_layout:
        raise StaticReTestFailure(
            "default Boneyard binary-layout map is incomplete: "
            + ", ".join(missing_layout)
        )

    for index, address in enumerate(
        (
            "0x0063BC10",
            "0x0063BD1F",
            "0x0063BDFB",
            "0x0063BF30",
            "0x0063C03B",
            "0x0063C117",
            "0x0063C45F",
        )
    ):
        token = f"boneyard_compact_flags_initialize_{index}={address}"
        if token not in layout:
            raise StaticReTestFailure(
                f"default Boneyard compact-decoration patch site is missing: {token}"
            )

    return (
        "default Boneyard selection, retail RNG, local materialization, authority "
        "seed transport, full persistent decor families, peer-local Tree/Scrub/"
        "Goodie state, render-time ambient RNG, and all seven compact-flag sites "
        "are mapped"
    )


def test_loading_screen_uses_native_stage_progress_and_shared_d3d9_lifetime() -> str:
    loading = _read("SolomonDarkModLoader/src/loading_screen.cpp")
    renderer = _read("SolomonDarkModLoader/src/loading_screen_renderer.cpp")
    native_present = _read(
        "SolomonDarkModLoader/src/loading_screen_native_present.cpp"
    )
    renderer_internal = _read(
        "SolomonDarkModLoader/src/loading_screen_internal.h"
    )
    join_flow = _read("SolomonDarkModLoader/src/multiplayer_join_flow.cpp")
    join_progress = _read(
        "SolomonDarkModLoader/src/multiplayer_join_flow/loading_screen_progress.inl"
    )
    join_tick = join_progress + _read(
        "SolomonDarkModLoader/src/multiplayer_join_flow/tick_state_machine.inl"
    )
    barrier = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "run_loading_barrier_sync.inl"
    )
    launcher = _read(
        "SolomonDarkModLauncher/src/Staging/"
        "LoadingScreenAssetMaterializer.cs"
    )
    launcher_ui = _read(
        "SolomonDarkModLauncher.UI/src/Views/MainWindow.xaml"
    )
    launcher_ui_progress_path = ROOT / (
        "SolomonDarkModLauncher.UI/src/ViewModels/"
        "MatchLoadingProgress.cs"
    )
    launcher_ui_view_model = _read(
        "SolomonDarkModLauncher.UI/src/ViewModels/"
        "MainWindowViewModel.cs"
    )
    launcher_ui_theme = _read(
        "SolomonDarkModLauncher.UI/src/Themes/"
        "LauncherTheme.xaml"
    )
    launcher_executor = _read(
        "SolomonDarkModLauncher/src/App/"
        "LauncherCommandExecutor.cs"
    )
    package = _read("scripts/New-BetaReleasePackage.ps1")
    verifier = _read("tools/verify_loading_screen.py")

    required_native_stages = (
        '"arena_start_run_dispatch"',
        '"boneyard_loader"',
        '"boneyard_procedural_create_save"',
        '"boneyard_generator"',
        '"boneyard_materialize"',
        "HookArenaStart",
        "HookBoneyardLoader",
        "HookProceduralCreateSave",
        "HookBoneyardGenerator",
        "HookBoneyardMaterialize",
        "LoadingScreenStage::PreparingBoneyard",
        "LoadingScreenStage::GeneratingBoneyard",
        "LoadingScreenStage::SerializingBoneyard",
        "LoadingScreenStage::ReadingBoneyard",
        "LoadingScreenStage::MaterializingWorld",
        "definition.progress > current.progress",
        "std::uintptr_t path_word_6",
    )
    missing_native = [
        token for token in required_native_stages if token not in loading
    ]
    if missing_native:
        raise StaticReTestFailure(
            "loading screen native stage map is incomplete: "
            + ", ".join(missing_native)
        )
    if "progress +=" in loading or "progress +=" in renderer:
        raise StaticReTestFailure(
            "loading screen progress must not advance from a timer or easing loop"
        )
    if loading.count("std::uintptr_t path_word_6") != 4:
        raise StaticReTestFailure(
            "native Boneyard path-object hooks do not preserve the recovered "
            "seven-DWORD callee-cleaned ABI"
        )

    required_renderer = (
        "kBottomBandHeightFraction = 0.18f",
        "kProgressBarWidthFraction = 0.60f",
        "viewport_aspect > image_aspect",
        "visible_height =",
        "visible_width =",
        "D3DPOOL_MANAGED",
        "InstallD3d9FrameHook",
        "RemoveD3d9FrameCallback",
    )
    combined_renderer = renderer + _read(
        "SolomonDarkModLoader/src/lua_draw_texture_loader.cpp"
    )
    missing_renderer = [
        token for token in required_renderer if token not in combined_renderer
    ]
    if missing_renderer:
        raise StaticReTestFailure(
            "loading screen renderer contract is incomplete: "
            + ", ".join(missing_renderer)
        )
    if "native_d3d9_lifetime_guard" in renderer:
        raise StaticReTestFailure(
            "loading screen renderer bypasses the shared D3D9 frame seam"
        )
    for token, source in (
        ("kLoadingScreenPresentationDelayMs = 150", renderer_internal),
        ("GetLastSeenD3d9Device()", native_present),
        ("device->BeginScene()", native_present),
        ("device->EndScene()", native_present),
        ("device->Present(", native_present),
        ("SDMOD_LOADING_SCREEN_CAPTURE_DIRECTORY", native_present),
        ("PresentLoadingScreenFrame();", loading),
    ):
        if token not in source:
            raise StaticReTestFailure(
                f"native loading-stage presentation seam is missing: {token}"
            )

    required_multiplayer = (
        "LoadingScreenStage::ConnectingTransport",
        "LoadingScreenStage::JoiningLobby",
        "LoadingScreenStage::AuthenticatingSession",
        "LoadingScreenStage::EstablishingRoute",
        "LoadingScreenStage::SynchronizingHostSettings",
        "LoadingScreenStage::ReceivingHostCheckpoint",
        "LoadingScreenStage::ReceivingRunPlan",
        "LoadingScreenStage::ReceivingWorldCheckpoint",
        "LoadingScreenStage::ReceivingWaveCheckpoint",
    )
    if (
        "phase_state.inl" not in join_flow
        or any(token not in join_progress for token in required_multiplayer)
    ):
        raise StaticReTestFailure(
            "multiplayer join phase changes do not start real loading stages"
        )
    for token in (
        "runtime.transport_route_ready",
        "runtime.host_settings_checkpoint_received",
        "runtime.world_snapshot.valid",
        "runtime.host_wave_checkpoint_run_nonce",
    ):
        if token not in join_tick:
            raise StaticReTestFailure(
                f"multiplayer join progress source is missing: {token}"
            )
    for token in (
        "BeginRunLoadingBarrier(",
        'if (reason != "new_run")',
        "runtime_state.world_snapshot.valid",
        "runtime_state.host_wave_checkpoint_run_nonce",
        "!visible_participant_ids.empty()",
        "LoadingScreenStage::WaitingForParticipants",
        "LoadingScreenStage::ConfirmingParticipants",
        "ReleaseRunLoadingBarrier(",
        "CompleteLoadingScreen();",
    ):
        if token not in barrier:
            raise StaticReTestFailure(
                f"run-loading barrier progress source is missing: {token}"
            )

    background = ROOT / "assets/loading/Wizards_dire_BG.png"
    actual_sha256 = hashlib.sha256(background.read_bytes()).hexdigest()
    if actual_sha256 != LOADING_BACKGROUND_SHA256:
        raise StaticReTestFailure(
            "loading screen background is not the owner-approved canonical asset: "
            f"{actual_sha256}"
        )
    if (
        "FileTreeMirror.Synchronize" not in launcher
        or '".sdmod"' not in launcher
        or '"assets"' not in launcher
        or 'Copy-Item (Join-Path $root "assets")' not in package
    ):
        raise StaticReTestFailure(
            "loading screen asset is not staged and packaged with the loader"
        )
    if launcher_ui_progress_path.exists():
        raise StaticReTestFailure(
            "the desktop launcher must not carry a match loading "
            "progress model; the loading screen belongs to the staged "
            "game only (owner direction, 2026-07-27)"
        )
    for token, source, where in (
        ("Wizards_dire_BG", launcher_ui, "MainWindow.xaml"),
        ("MatchLoadingProgressBarStyle", launcher_ui, "MainWindow.xaml"),
        (
            "MatchLoadingProgressBarStyle",
            launcher_ui_theme,
            "LauncherTheme.xaml",
        ),
        ("MatchLoading", launcher_ui_view_model, "MainWindowViewModel.cs"),
        (
            "UpdateProgressScope",
            launcher_executor,
            "LauncherCommandExecutor.cs",
        ),
    ):
        if token in source:
            raise StaticReTestFailure(
                "the desktop launcher window must not present the match "
                f"loading screen: {token} found in {where}"
            )
    for token in (
        'INSTANCE_PREFIX = "ffix"',
        "HOST_PORT = 49711",
        "CLIENT_PORT = 49712",
        "enable_audio=False",
        "disable_multiplayer_transport=(",
        "stop_exact_game_processes(launch)",
        "waiting_for_participants",
    ):
        if token not in verifier:
            raise StaticReTestFailure(
                f"loading-screen live verifier safety contract is missing: {token}"
            )

    return (
        "loading progress is monotonic and sourced from Steam "
        "route/authentication, host/world/wave checkpoints, native Boneyard "
        "work, and run-barrier milestones; the desktop launcher window "
        "presents no loading screen; rendering uses the shared D3D9 "
        "lifetime seam and canonical packaged art"
    )


def test_multiplayer_boneyard_scenery_shares_the_host_generation_boundary() -> str:
    seed_sources = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/core/run_generation_seed_helpers.inl"
    ) + _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_gameplay_action_queues.inl"
    )
    run_hooks = _read(
        "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks/run_transition_hooks.inl"
    )
    presentation_patch = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/core/boneyard_generator_patch.inl"
    )
    verifier = _read("tools/verify_run_static_layout_sync.py")
    layout = _read("config/binary-layout.ini")
    networking = _read("docs/networking/README.md")

    required_seed_contract = (
        "ReinitializeAppliedRunGenerationSeedForArenaCreate",
        "multiplayer::IsLocalTransportEnabled()",
        "applied_run_generation_seed.load",
        "InitializeNativeGlobalRngForRunGeneration(seed, source)",
    )
    missing_seed = [token for token in required_seed_contract if token not in seed_sources]
    if missing_seed:
        raise StaticReTestFailure(
            "Boneyard arena-boundary seed contract is incomplete: " + ", ".join(missing_seed)
        )

    hook_start = run_hooks.find("void __fastcall HookCreateArena(")
    hook_end = run_hooks.find("void __fastcall HookStartGame(", hook_start)
    if hook_start < 0 or hook_end < 0:
        raise StaticReTestFailure("HookCreateArena body was not found")
    hook_body = run_hooks[hook_start:hook_end]
    cleanup_index = hook_body.find("ClearRememberedEnemyTracking();")
    reseed_index = hook_body.find(
        'ReinitializeAppliedRunGenerationSeedForArenaCreate("arena_create_pre_stock")'
    )
    stock_index = hook_body.find("original(self, unused_edx);")
    if not (0 <= cleanup_index < reseed_index < stock_index):
        raise StaticReTestFailure(
            "HookCreateArena must reseed after loader cleanup and before stock Boneyard generation"
        )

    required_layout_offsets = (
        "boneyard_scenery_materialization_key=0x10",
        "boneyard_tree_variant=0x140",
        "boneyard_tree_overlay_variant=0x142",
        "boneyard_tree_overlay_enabled=0x144",
        "boneyard_scenery_common_scalar=0xCC",
        "boneyard_tree_sway_countdown=0x148",
        "boneyard_tree_sway_target=0x14C",
        "boneyard_tree_sway_current=0x150",
        "boneyard_scrub_variant=0x140",
        "boneyard_scrub_phase=0x134",
        "boneyard_goodie_active=0x143",
        "boneyard_goodie_timer=0x144",
        "actor_world_compact_decoration_list=0x8ADC",
        "boneyard_compact_type=0x00",
        "boneyard_compact_position_x=0x04",
        "boneyard_compact_position_y=0x08",
        "boneyard_compact_rotation=0x0C",
        "boneyard_compact_scale=0x10",
        "boneyard_compact_alpha=0x14",
        "boneyard_compact_flags=0x18",
    )
    missing_layout = [token for token in required_layout_offsets if token not in layout]
    if missing_layout:
        raise StaticReTestFailure(
            "Boneyard scenery verifier offsets are incomplete: " + ", ".join(missing_layout)
        )

    required_verifier_contract = (
        'off("actor_world_scenery_object_list")',
        'off("pointer_list_count")',
        'off("pointer_list_items")',
        "TREE_TYPE_ID = 2001",
        "SCRUB_TYPE_ID = 2062",
        'emit("boneyard_scenery_count"',
        'emit("boneyard_scenery_digest"',
        'emit("boneyard_scenery_diagnostic_digest"',
        'emit("boneyard_tree_count"',
        'emit("boneyard_tree_digest"',
        'emit("boneyard_tree_diagnostic_digest"',
        '"common_scalar_bits"',
        'off("actor_world_road_list")',
        'emit("boneyard_road_digest"',
        'off("actor_world_fence_list")',
        'emit("boneyard_fence_digest"',
        'off("actor_world_terrain_list")',
        'emit("boneyard_terrain_digest"',
        'off("actor_world_compact_decoration_list")',
        'emit("boneyard_compact_count"',
        'emit("boneyard_compact_digest"',
        'emit("boneyard_presentation_digest"',
        '"boneyard_presentation_arena_ambient_kind"',
        '"boneyard_presentation_marker_scale_bits"',
        '"boneyard_compact_type_7_8_noncanonical_flags"',
        '"boneyard_compact_type_21_24_count"',
        'off("boneyard_compact_bounds_left")',
        'off("boneyard_compact_bounds_bottom")',
        "def decor_tables(",
        "def render_decor_tables(",
        '"presentation_inputs": presentation_inputs',
        "def full_render_input_digest(",
        '"verified_render_profile"',
        'if row["type_id"] != 2001:',
        '"render_decor_tables_exact": True',
        '"diagnostic_decor_tables_exact"',
        "def matched_camera_targets(",
        "def exact_decor_pixel_comparison(",
        "def exact_stable_decor_pixel_comparison(",
        "def exact_temporal_envelope_decor_pixel_comparison(",
        "def temporal_minimum_edge_comparison(",
        "ImageChops.darker(",
        "minimum_symmetric_match_fraction = 0.985",
        "per-channel temporal minimum for persistent geometry",
        "ACTOR_LIGHT_PARKING_OFFSET_X = -320.0",
        "MINIMUM_PLAYER_LIGHT_DISTANCE = 310.0",
        "TARGET_PLAYER_LIGHT_DISTANCE = 320.0",
        "MAXIMUM_PLAYER_LIGHT_DISTANCE = 330.0",
        "NATIVE_COLLISION_RADIAL_TOLERANCE = 25.0",
        "MINIMUM_MATCHED_AREA_SEPARATION = 250.0",
        "STABLE_CROSS_PEER_CHANNEL_DELTA = 2",
        "class ParkingSelectionFailure(VerifyFailure):",
        "def actor_light_parking_goal(",
        "def actor_light_parking_geometry(",
        "def settled_actor_parking_geometry(",
        "def nav_traversable_positions(",
        "def nav_actor_parking_positions(",
        "sd.debug.get_nav_grid(1)",
        "grid_world ~= scene_world",
        "sample.traversable",
        "target_gap >= {MINIMUM_PLAYER_LIGHT_DISTANCE!r}",
        "math.abs(target_gap - {TARGET_PLAYER_LIGHT_DISTANCE!r})",
        "return a.radial_error < b.radial_error",
        "actor_parking_samples",
        '"preselected_actor_parking_sample"',
        '"client": list(shared_position)',
        "def settle_shared_actor_parking(",
        "def settle_matched_camera_target(",
        "except ParkingSelectionFailure as error:",
        '"target_attempts": []',
        "def capture_matched_camera_areas(",
        "complex_visual_content_insufficient = (",
        "def temporal_envelope_has_only_insufficient_content(",
        'not envelope["sufficient_visual_content"]',
        "CAPTURE_ATTEMPTS_PER_FRAME = 8",
        "def capture_information_frame(",
        "def enable_quiet_layout_test_mode(",
        "sd.gameplay.set_manual_enemy_spawner_test_mode(true)",
        'run_result["quiet_layout_test_mode"]',
        '"blank or low-information"',
        '"low_information_retries"',
        "god_mode=True",
        'launch.get("godModeEnabled") is not True',
        "actor_clearance(row) >= 1000.0",
        "camera_safe_margin = 650.0",
        "local_sync.wait_for_local_transform_settled(",
        "local_sync.wait_for_remote_convergence(",
        "settled_actor_geometry",
        "minimum_decor_roi_clearance = 120.0",
        "No damage or spell probe",
        '"differing_pixel_count": differing_pixel_count',
        '"pixel_hashes_match": host_hash == client_hash',
        "differing_pixel_count == 0",
        '"differing_stable_pixel_count": differing_stable_pixel_count',
        '"stable_pixel_hashes_match": stable_hashes_match',
        "minimum_stable_visible_pixel_count = 1024",
        "minimum_stable_unique_colors = 128",
        "envelope_gap = max(",
        "maximum_stable_envelope_gap = max(",
        '"maximum_allowed_stable_cross_peer_envelope_gap"',
        '"stable_pixel_fraction_is_diagnostic_only": True',
        "stable_visible_pixel_count >= minimum_stable_visible_pixel_count",
        'if not stable_pixels["bounded_match"]',
        '"frames_per_peer": len(host_paths)',
        '"differing_envelope_pixel_count"',
        '"maximum_envelope_channel_gap"',
        '"allowed_unexplained_channel_gap": 0',
        '"excluded_pixel_count": sum(excluded_mask)',
        "minimum_visible_pixel_count = 512",
        '"world_roi_excluded": True',
        "range(1, CAPTURE_FRAMES_PER_PEER + 1)",
        '"family": family',
        '"trees"',
        '"large-rocks"',
        '"ground-clutter"',
        '"scenery-props"',
        "def configure_visual_gate_render_profile(",
        "complex_lighting = { address = 0x00B3BCA8, value = __COMPLEX_LIGHTING__ }",
        "complex_shadows = { address = 0x00B3BCA9, value = __COMPLEX_SHADOWS__ }",
        "multiple_shadows = { address = 0x00B3BCAA, value = __MULTIPLE_SHADOWS__ }",
        "zoom_effects = { address = 0x00B3BCAC, value = __ZOOM_EFFECTS__ }",
        "enhanced_effects = { address = 0x00B3BCAD, value = 0 }",
        "sd.debug.resolve_game_address(slot.address)",
        "def capture_owned_process_identities(",
        "def stop_owned_processes(",
        '"boneyard_scenery_count"',
        '"boneyard_scenery_digest"',
        '"boneyard_tree_count"',
        '"boneyard_tree_digest"',
        'integer(host, "boneyard_scenery_count") > 0',
        'integer(host, "boneyard_tree_count") > 0',
        'integer(host, "boneyard_compact_count") > 0',
        'integer(host, "boneyard_compact_type_7_8_count") > 0',
    )
    missing_verifier = [token for token in required_verifier_contract if token not in verifier]
    if missing_verifier:
        raise StaticReTestFailure(
            "Live Boneyard scenery equality gate is incomplete: " + ", ".join(missing_verifier)
        )
    if (
        verifier.count(
            "temporal_envelope_has_only_insufficient_content("
        )
        < 2
    ):
        raise StaticReTestFailure(
            "complex-lighting content classification is not wired into "
            "matched-target retry"
        )
    hub_ready_index = verifier.find(
        'run_result["hub_remote_materialized"]'
    )
    quiet_mode_index = verifier.find(
        'run_result["quiet_layout_test_mode"]'
    )
    run_entry_index = verifier.find('run_result["host_run_entry"]')
    if not (
        0 <= hub_ready_index < quiet_mode_index < run_entry_index
    ):
        raise StaticReTestFailure(
            "static-layout quiet mode must activate after hub convergence "
            "and before run entry"
        )
    if "stop_games()" in verifier:
        raise StaticReTestFailure(
            "Boneyard live verifier still performs machine-wide game cleanup"
        )
    if "queue_native_magic_hit_behavior_probe" in verifier:
        raise StaticReTestFailure(
            "Boneyard visual gate still injects actor damage presentation"
        )
    required_presentation_repair = (
        "HookBoneyardTreeCtor",
        "kBoneyardSceneryCommonScalarOffset",
        "HookBoneyardTreeTick",
        "kBoneyardCanonicalTreeSwayCountdown",
        "HookBoneyardTreeRenderOverlay",
        "HookBoneyardSceneryRenderLighting",
        "CanonicalizeBoneyardTreeLightingScalar",
        "StableBoneyardTreeLightingScalar",
        "StableBoneyardTreeSwayScale",
        "StableBoneyardSceneryHash",
        "kBoneyardTreeTypeId",
        "StableBoneyardScrubPhase",
        "HookBoneyardScrubCtor",
        "HookBoneyardScrubTick",
        "HookBoneyardGoodieCtor",
        "kBoneyardGoodieTimerOffset",
        "BoneyardAmbientRngGate",
        "BoneyardMarkerPrimaryTintRng",
        "BoneyardMarkerSecondaryTintRng",
        "StableBoneyardMarkerTint",
        "ambient_rng_suppression=2",
        "marker_tint_rng_stabilization=2",
    )
    missing_repair = [
        token
        for token in required_presentation_repair
        if token not in presentation_patch
    ]
    if missing_repair:
        raise StaticReTestFailure(
            "Boneyard presentation repair is incomplete: "
            + ", ".join(missing_repair)
        )

    for token in ("Solomon_Dig", "Lantern", "Tree 2001", "Scrub 2062"):
        if token not in networking:
            raise StaticReTestFailure(
                f"networking documentation does not distinguish run-static actors from {token}"
            )

    return (
        "multiplayer Boneyard scenery is generated from the host seed at the stock "
        "Arena_Create boundary, with exact Tree/Scrub and compact-decor tables, "
        "matched cameras, and exact PID/path cleanup verified at runtime"
    )
