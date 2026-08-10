#!/usr/bin/env python3
"""Mutation-audit every claim introduced by the P1 webgame hub contracts."""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable
from unittest.mock import patch

import static_re_webgame_hub_contracts as contracts


@dataclass(frozen=True)
class TextMutation:
    claim: str
    contract: str
    target: Path
    old: str
    new: str
    expected: str
    occurrences: int = 1


@dataclass(frozen=True)
class SpecialMutation:
    claim: str
    contract: str
    activate: Callable[[], AbstractContextManager[None]]
    expected: str


@dataclass(frozen=True)
class MutationResult:
    claim: str
    contract: str
    expected_message: str
    observed_message: str
    baseline_before: str
    baseline_after: str
    baseline_log: str
    trip_log: str
    restored_log: str


Mutation = TextMutation | SpecialMutation


def clear_contract_bytecode() -> None:
    cache = Path(__file__).resolve().parent / "__pycache__"
    if not cache.is_dir():
        return
    children = list(cache.iterdir())
    if not children:
        raise RuntimeError("contract bytecode directory existed but exposed no entries to clear")
    for child in children:
        if not child.is_file() or child.suffix != ".pyc":
            raise RuntimeError(f"refusing to clear unexpected contract cache entry {child}")
        child.unlink()
    cache.rmdir()


@contextmanager
def text_mutation(mutation: TextMutation) -> Iterator[None]:
    original_read = contracts._read_text  # noqa: SLF001 - intentional mutation seam.
    target = mutation.target.resolve()
    applied = False

    def mutated_read(path: Path, consequence: str) -> str:
        nonlocal applied
        text = original_read(path, consequence)
        if path.resolve() != target:
            return text
        found = text.count(mutation.old)
        if found != mutation.occurrences:
            raise RuntimeError(
                f"mutation {mutation.claim} expected {mutation.occurrences} unambiguous source occurrence(s) "
                f"in {mutation.target}, found {found}"
            )
        applied = True
        return text.replace(mutation.old, mutation.new, mutation.occurrences)

    with patch.object(contracts, "_read_text", mutated_read):
        yield
    if not applied:
        raise RuntimeError(f"mutation {mutation.claim} never reached {mutation.target}")


@contextmanager
def copied_scene_golden_present() -> Iterator[None]:
    original_json_paths = contracts._tracked_webgame_json  # noqa: SLF001 - intentional mutation seam.
    injected = contracts.WEBGAME / "scene-composition-goldens.json"
    reached = False

    def mutated_json_paths() -> list[str]:
        nonlocal reached
        reached = True
        return [*original_json_paths(), injected.relative_to(contracts.WEBGAME).as_posix()]

    with patch.object(contracts, "_tracked_webgame_json", mutated_json_paths):
        yield
    if not reached:
        raise RuntimeError("copied-fixture mutation never reached the P1 webgame JSON sweep")


ARCHITECTURE = "test_webgame_hub_architecture_is_client_owned_provisional_and_sim_independent"
SCENE = "test_webgame_hub_scene_economy_animation_and_manifest_replays_are_strict"
SESSION = "test_webgame_hub_session_graph_phase_order_and_fixture_timings_are_pinned"
TRAVERSAL = "test_webgame_hub_controller_traversal_covers_every_talk_purchase_and_run_boundary"
CAPTURE = "test_webgame_hub_capture_assets_performance_provenance_and_ci_are_wired"


MUTATIONS: tuple[Mutation, ...] = (
    TextMutation(
        "architecture.sim-boundary",
        ARCHITECTURE,
        contracts.HUB_CONTROLLER,
        'import type { InputSurface } from "../input/gamepad-producer.js";',
        'import type { InputSurface } from "../input/gamepad-producer.js";\nimport type {} from "../sim/state.js";',
        "P1 hub client imported the concurrent P2 simulation boundary in client/hub-controller.ts",
    ),
    TextMutation(
        "architecture.provisional-g1-speed",
        ARCHITECTURE,
        contracts.HUB_CONTROLLER,
        "export const PROVISIONAL_HUB_WALK_SPEED = 100;",
        "export const PROVISIONAL_HUB_WALK_SPEED = 101;",
        "P1 shell locomotion no longer uses G1's documented 100 world-unit/s base walk speed",
    ),
    TextMutation(
        "architecture.intent-routing",
        ARCHITECTURE,
        contracts.APP,
        "      hub.handle(intent);",
        "      void intent;",
        "P1 input routing no longer sends G14 intents into hub shell state only while the hub owns the surface",
    ),
    TextMutation(
        "architecture.map-picker-routing",
        ARCHITECTURE,
        contracts.APP,
        "    sink(intent);\n  };",
        "    sink(intent);\n    hub.beginRunEntry();\n  };",
        "owner-descoped MapPicker can still enter the run flow from the browser shell",
    ),
    SpecialMutation(
        "architecture.no-copied-fixture",
        ARCHITECTURE,
        copied_scene_golden_present,
        "P1 hub contains a second mutable copy of a landed fixture: scene-composition-goldens.json",
    ),
    TextMutation(
        "scene.canonical-imports",
        SCENE,
        contracts.HUB_CONTRACTS,
        'import economyGoldenJson from "../../tests/fixtures/webgame/hub-economy-goldens.json" with { type: "json" };\nimport sceneGoldenJson',
        'import economyGoldenJson from "../../tests/fixtures/webgame/hub-economy-goldens.json" with { type: "json" };\nvoid 0;\nimport sceneGoldenJson',
        "P1 client no longer imports the three landed hub goldens directly and adjacently",
    ),
    TextMutation(
        "scene.canonical-capture",
        SCENE,
        contracts.SCENE_GOLDEN,
        '"label": "hub_camera_1000_375_final"',
        '"label": "hub_camera_mutant"',
        "P1 G12 replay cannot resolve exactly one canonical Courtyard capture",
    ),
    TextMutation(
        "scene.transform-replay",
        SCENE,
        contracts.HUB_REPLAY,
        "assert.deepEqual(actual.worldTransform, expected.world_transform",
        "assert.deepEqual(actual.worldTransform, expected.mutant_transform",
        "P1 T2 replay no longer compares every G12 native transform",
    ),
    TextMutation(
        "economy.fresh-capture",
        SCENE,
        contracts.ECONOMY_GOLDEN,
        '"id": "fresh"',
        '"id": "mutant"',
        "P1 G8 replay refuses a missing or ambiguous fresh trader capture",
    ),
    TextMutation(
        "economy.regeneration-boundary",
        SCENE,
        contracts.HUB_REPLAY,
        "regeneration=OUT_OF_SCOPE",
        "regeneration=IMPLEMENTED",
        "P1 T2 replay now implies unsupported tick-seed stock regeneration",
    ),
    TextMutation(
        "assets.missing-special-hard-failure",
        SCENE,
        contracts.MANIFEST_ASSETS,
        "assetpack manifest is missing required special draw id",
        "assetpack manifest skipped optional special draw id",
        "P1 asset lookup can silently skip a missing typed G12 draw",
    ),
    TextMutation(
        "animation.combat-boundary",
        SCENE,
        contracts.ANIMATION_REPLAY,
        "combat_states=OUT_OF_SCOPE",
        "combat_states=IMPLEMENTED",
        "P1 G4 replay escaped its idle/walk-only presentation boundary",
    ),
    TextMutation(
        "session.two-edge-arena-path",
        SESSION,
        contracts.SESSION_GOLDEN,
        '"destination": "loading.boneyard",\n        "edge": "start_run",\n        "state": "gameplay.courtyard"',
        '"destination": "gameplay.arena",\n        "edge": "start_run",\n        "state": "gameplay.courtyard"',
        "P1 G13 graph lost an unambiguous two-edge Courtyard-to-Arena path",
    ),
    TextMutation(
        "session.phase-order",
        SESSION,
        contracts.SESSION_FLOW,
        '  "slot detach",',
        '  "slot release",',
        "P1 G13 implementation no longer preserves the exact nested fourteen-phase order",
    ),
    TextMutation(
        "session.portal-fade-timing",
        SESSION,
        contracts.SESSION_FLOW,
        "export const G13_PORTAL_FADE_OUT_TICKS = 101;",
        "export const G13_PORTAL_FADE_OUT_TICKS = 100;",
        "P1 G13 outgoing stock fade no longer lasts 101 ticks",
    ),
    TextMutation(
        "session.implementation-fixture-comparison",
        SESSION,
        contracts.TRANSITION_REPLAY,
        "implemented Library portal no longer presents the exact recorded stock fade-out duration",
        "implemented Library portal timing accepted without comparison",
        "P1 transition replay no longer compares the implemented portal fade to the fixture",
    ),
    TextMutation(
        "traversal.real-gamepad-producer",
        TRAVERSAL,
        contracts.HUB_TRAVERSAL,
        "const producer = new GamepadProducer(route, () => {",
        "const producer = new FakeProducer(route, () => {",
        "P1 hub traversal no longer enters through the real G14 gamepad producer",
    ),
    TextMutation(
        "traversal.synthetic-analog-walk",
        TRAVERSAL,
        contracts.HUB_TRAVERSAL,
        "producer.sample(gamepad([x, y, 0, 0]));",
        "producer.sample(pointer([x, y]));",
        "P1 hub traversal no longer walks through synthetic analog gamepad snapshots",
    ),
    TextMutation(
        "traversal.exact-talk-set",
        TRAVERSAL,
        contracts.HUB_TRAVERSAL,
        "hub.snapshot().completedTalkFlows,\n    HUB_NPCS.map((npc) => npc.id).sort()",
        "hub.snapshot().completedTalkFlows,\n    selectedNpcs.map((npc) => npc.id).sort()",
        "P1 hub traversal no longer proves exact all-NPC talk-flow set equality",
    ),
    TextMutation(
        "traversal.purchase-ledger",
        TRAVERSAL,
        contracts.HUB_TRAVERSAL,
        "goldBefore: 698,\n          goldAfter: 548,\n          quantityBefore: 2,\n          quantityAfter: 1",
        "goldBefore: 698,\n          goldAfter: 549,\n          quantityBefore: 2,\n          quantityAfter: 1",
        "P1 hub traversal no longer proves the exact Useful Thyngs gold and stock ledger",
    ),
    TextMutation(
        "traversal.map-picker-entry",
        TRAVERSAL,
        contracts.HUB_TRAVERSAL,
        '{ kind: "layout", layoutId: "map-picker" }',
        '{ kind: "layout", layoutId: "portal-picker" }',
        "P1 traversal no longer reaches the rendered owner-descoped Courtyard MapPicker",
    ),
    TextMutation(
        "traversal.inert-snapshot",
        TRAVERSAL,
        contracts.HUB_TRAVERSAL,
        "const beforeMapConfirm = structuredClone(shell.snapshot());",
        "const beforeMapConfirm = shell.snapshot();",
        "P1 traversal no longer snapshots MapPicker state before activation",
    ),
    TextMutation(
        "traversal.inert-shell-state",
        TRAVERSAL,
        contracts.HUB_TRAVERSAL,
        'assert.deepEqual(shell.snapshot(), beforeMapConfirm, "owner-descoped MapPicker confirmation mutated shell state")',
        'assert.notDeepEqual(shell.snapshot(), beforeMapConfirm, "owner-descoped MapPicker confirmation mutated shell state")',
        "P1 traversal no longer proves owner-descoped MapPicker activation is non-navigating",
    ),
    TextMutation(
        "traversal.inert-session-state",
        TRAVERSAL,
        contracts.HUB_TRAVERSAL,
        'assert.equal(hub.snapshot().transition, null, "owner-descoped MapPicker confirmation started a session edge")',
        'assert.notEqual(hub.snapshot().transition, null, "owner-descoped MapPicker confirmation started a session edge")',
        "P1 traversal no longer proves owner-descoped MapPicker activation starts no session edge",
    ),
    TextMutation(
        "traversal.human-log",
        TRAVERSAL,
        contracts.HUB_TRAVERSAL,
        "WEBGAME_HUB_TRAVERSAL_LOG",
        "MUTANT_HUB_TRAVERSAL_LOG",
        "P1 controller-only traversal no longer emits a human-readable evidence log",
    ),
    TextMutation(
        "capture.settle-rule",
        CAPTURE,
        contracts.CAPTURE,
        "two independent captures; 41 samples each; 40 consecutive byte-identical structural payloads spanning at least 2 seconds",
        "two independent captures; 40 samples each; 39 consecutive byte-identical structural payloads spanning at least 1 second",
        "P1 capture no longer records the mandatory two-run 41/40/2-second settle rule",
    ),
    TextMutation(
        "capture.surface-census",
        CAPTURE,
        contracts.CAPTURE,
        "hub capture census must reach one hub, twenty NPCs, seven services, and one run shell",
        "hub capture census may omit one NPC",
        "P1 visual evidence no longer names its exact 29-surface census",
    ),
    TextMutation(
        "capture.asset-boundary",
        CAPTURE,
        contracts.CAPTURE,
        "hub loaded asset outside the assetpack manifest",
        "hub accepted asset outside the assetpack manifest",
        "P1 live asset audit can accept a request outside the manifest",
    ),
    TextMutation(
        "capture.sustained-performance",
        CAPTURE,
        contracts.CAPTURE,
        "measureFrameTimes(600)",
        "measureFrameTimes(60)",
        "P1 capture no longer measures a sustained 600-frame live hub sample",
    ),
    TextMutation(
        "capture.self-provenance",
        CAPTURE,
        contracts.CAPTURE,
        '["rev-parse", "HEAD"]',
        '["rev-list", "HEAD"]',
        "P1 capture no longer derives its own source SHA from Git",
    ),
    TextMutation(
        "ci.package-commands",
        CAPTURE,
        contracts.PACKAGE,
        '"hub-conformance": "tsx conformance/run-hub-conformance.ts"',
        '"hub-conformance": "tsx conformance/run-mutant.ts"',
        "P1 package no longer exposes all four exact hub gate commands",
    ),
    TextMutation(
        "ci.quality-floor",
        CAPTURE,
        contracts.QUALITY_FLOORS,
        '"unitTests": 99',
        '"unitTests": 98',
        "P1 webgame quality floors no longer match the measured final workspace",
    ),
    TextMutation(
        "ci.transition-step",
        CAPTURE,
        contracts.CI,
        "      - name: Replay P1 session transitions",
        "      - name: Skip P1 session transitions",
        "CI no longer replays P1 G13 transition conformance",
    ),
)


def file_slug(claim: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", claim.lower()).strip("-")


def write_transcript(path: Path, stage: str, mutation: Mutation, body: str) -> None:
    path.write_text(
        f"stage={stage}\nclaim={mutation.claim}\ncontract={mutation.contract}\n{body}\n",
        encoding="utf-8",
    )


def run_mutation(mutation: Mutation, index: int, transcript_root: Path) -> MutationResult:
    contract = getattr(contracts, mutation.contract)
    slug = f"{index:02d}-{file_slug(mutation.claim)}"
    baseline_path = transcript_root / f"{slug}-green-baseline.log"
    trip_path = transcript_root / f"{slug}-trip.log"
    restored_path = transcript_root / f"{slug}-restored-green.log"

    clear_contract_bytecode()
    before = contract()
    write_transcript(baseline_path, "green-baseline", mutation, f"PASS\n{before}")

    observed = ""
    active = text_mutation(mutation) if isinstance(mutation, TextMutation) else mutation.activate()
    clear_contract_bytecode()
    with active:
        try:
            contract()
        except contracts.StaticReTestFailure as exc:
            observed = str(exc)
        else:
            raise RuntimeError(f"mutation {mutation.claim} failed to trip {mutation.contract}")
    write_transcript(trip_path, "trip", mutation, f"EXPECTED\n{mutation.expected}\nOBSERVED\n{observed}")
    if observed != mutation.expected:
        raise RuntimeError(
            f"mutation {mutation.claim} tripped the wrong claim:\n"
            f"expected: {mutation.expected}\nobserved: {observed}"
        )

    clear_contract_bytecode()
    after = contract()
    write_transcript(restored_path, "restored-green", mutation, f"PASS\n{after}")
    return MutationResult(
        claim=mutation.claim,
        contract=mutation.contract,
        expected_message=mutation.expected,
        observed_message=observed,
        baseline_before=before,
        baseline_after=after,
        baseline_log=baseline_path.name,
        trip_log=trip_path.name,
        restored_log=restored_path.name,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, required=True, help="Write the complete mutation table as JSON")
    parser.add_argument(
        "--transcript-dir",
        type=Path,
        required=True,
        help="Write green-baseline, trip, and restored-green logs for every mutation",
    )
    args = parser.parse_args()
    args.transcript_dir.mkdir(parents=True, exist_ok=True)
    results: list[MutationResult] = []
    for index, mutation in enumerate(MUTATIONS, start=1):
        result = run_mutation(mutation, index, args.transcript_dir)
        results.append(result)
        print(
            f"PASS {index:02d}/{len(MUTATIONS)} {result.claim}: "
            f"{result.observed_message} [green before/after]"
        )
    args.json.write_text(
        json.dumps([asdict(result) for result in results], indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"{len(results)}/{len(MUTATIONS)} P1 hub contract mutations tripped the named claim")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
