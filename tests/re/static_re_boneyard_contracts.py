"""Static contracts for the native Boneyard container and committed fixture."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from static_re_contract_support import ROOT, StaticReTestFailure


sys.path.insert(0, str(ROOT / "tools"))
import inspect_boneyard  # noqa: E402


FIXTURE = ROOT / "tests/fixtures/boneyards/flat_multiplayer_test.boneyard"
EXPECTED_SHA256 = "7c7d23f2fbfcdf73b5bb7f4af0f836cc9d199997fe9c7dd38183c7659b6d949d"


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
        "native_rng_construct=0x00401110",
        "native_rng_initialize=0x00401120",
        "native_rng_integer=0x00401170",
        "native_rng_float=0x00401310",
        "native_global_rng_state=0x00818B08",
        "native_global_rng_state_object=0x00818B10",
        "actor_world_compact_decoration_list=0x8ADC",
        "boneyard_compact_flags=0x18",
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
        "seed transport, and all seven uninitialized compact-flag sites are mapped"
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
        "boneyard_scrub_variant=0x140",
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
        'emit("boneyard_tree_count"',
        'emit("boneyard_tree_digest"',
        'off("actor_world_compact_decoration_list")',
        'emit("boneyard_compact_count"',
        'emit("boneyard_compact_digest"',
        '"boneyard_compact_type_7_8_noncanonical_flags"',
        "def decor_tables(",
        "def capture_matched_camera_pair(",
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
    if "stop_games()" in verifier:
        raise StaticReTestFailure(
            "Boneyard live verifier still performs machine-wide game cleanup"
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
