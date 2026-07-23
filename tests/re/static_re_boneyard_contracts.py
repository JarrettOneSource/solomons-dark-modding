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
        '"boneyard_scenery_count"',
        '"boneyard_scenery_digest"',
        '"boneyard_tree_count"',
        '"boneyard_tree_digest"',
        'integer(host, "boneyard_scenery_count") > 0',
        'integer(host, "boneyard_tree_count") > 0',
    )
    missing_verifier = [token for token in required_verifier_contract if token not in verifier]
    if missing_verifier:
        raise StaticReTestFailure(
            "Live Boneyard scenery equality gate is incomplete: " + ", ".join(missing_verifier)
        )

    for token in ("Solomon_Dig", "Lantern", "Tree 2001", "Scrub 2062"):
        if token not in networking:
            raise StaticReTestFailure(
                f"networking documentation does not distinguish run-static actors from {token}"
            )

    return (
        "multiplayer Boneyard scenery is generated from the host seed at the stock "
        "Arena_Create boundary, with Tree/Scrub presentation compared exactly at runtime"
    )
