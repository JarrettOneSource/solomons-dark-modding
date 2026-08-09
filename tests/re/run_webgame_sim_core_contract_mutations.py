#!/usr/bin/env python3
"""Mutation-audit every claim in the P2 webgame sim-core contracts."""

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

import static_re_webgame_sim_core_contracts as contracts


@dataclass(frozen=True)
class TextMutation:
    claim: str
    contract: str
    target: Path
    old: str
    new: str
    expected: str


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
    green_before: str
    restored_green: str
    transcripts: tuple[str, str, str]


Mutation = TextMutation | SpecialMutation


def clear_contract_bytecode() -> None:
    cache = Path(__file__).resolve().parent / "__pycache__"
    if not cache.is_dir():
        return
    children = list(cache.iterdir())
    unexpected = [child for child in children if not child.is_file() or child.suffix != ".pyc"]
    if unexpected:
        raise RuntimeError(
            "refusing to clear unexpected contract cache content: "
            + ", ".join(str(path) for path in unexpected)
        )
    for child in children:
        child.unlink()
    cache.rmdir()


@contextmanager
def text_mutation(mutation: TextMutation) -> Iterator[None]:
    original_read = contracts._read_text  # noqa: SLF001 - intentional mutation seam.
    target = mutation.target.resolve()
    reached = False

    def mutated_read(path: Path, consequence: str) -> str:
        nonlocal reached
        text = original_read(path, consequence)
        if path.resolve() != target:
            return text
        occurrences = text.count(mutation.old)
        if occurrences != 1:
            raise RuntimeError(
                f"mutation {mutation.claim} requires one unambiguous source token; found {occurrences}"
            )
        reached = True
        return text.replace(mutation.old, mutation.new, 1)

    with patch.object(contracts, "_read_text", mutated_read):
        yield
    if not reached:
        raise RuntimeError(f"mutation {mutation.claim} never reached {mutation.target}")


@contextmanager
def production_source_witness_missing() -> Iterator[None]:
    original_rglob = Path.rglob
    target_directory = contracts.SIM.resolve()
    witness = contracts.TYPES.resolve()
    reached = False

    def mutated_rglob(path: Path, pattern: str):  # type: ignore[no-untyped-def]
        nonlocal reached
        values = original_rglob(path, pattern)
        if path.resolve() == target_directory and pattern == "*.ts":
            reached = True
            return (candidate for candidate in values if candidate.resolve() != witness)
        return values

    with patch.object(Path, "rglob", mutated_rglob):
        yield
    if not reached:
        raise RuntimeError("source-witness mutation never reached the sim source sweep")


def hash_constant_mutation(name: str) -> Callable[[], AbstractContextManager[None]]:
    @contextmanager
    def activate() -> Iterator[None]:
        with patch.object(contracts, name, "0" * 64):
            yield

    return activate


ARCHITECTURE = "test_webgame_sim_core_is_pure_single_path_and_actor_model_pinned"
TICK_GRAPH = "test_webgame_sim_tick_graph_and_cadences_match_g1_tables"
MOVEMENT = "test_webgame_sim_movement_and_collision_replay_the_landed_t2_contract"
RNG = "test_webgame_sim_rng_is_bit_exact_for_integer_and_sealed_float_corpora"
FIRE = "test_webgame_sim_fire_projectile_replays_the_landed_g2_contract"
REPLAY = "test_webgame_sim_replay_determinism_and_ci_gates_are_wired"


MUTATIONS: tuple[Mutation, ...] = (
    SpecialMutation(
        "architecture.source-witness",
        ARCHITECTURE,
        production_source_witness_missing,
        "P2 purity sweep did not reach every deterministic sim source witness",
    ),
    TextMutation(
        "architecture.purity",
        ARCHITECTURE,
        contracts.CONSTANTS,
        "export const TICK_RATE_HZ = 100;",
        "Math.random();\nexport const TICK_RATE_HZ = 100;",
        "P2 sim purity was broken by DOM, wall-clock, random, process, or direct I/O access",
    ),
    TextMutation(
        "architecture.roadmap",
        ARCHITECTURE,
        contracts.ROADMAP,
        "There is exactly one sim and exactly one server implementation.",
        "There may be more than one sim implementation.",
        "P2 roadmap no longer pins one pure sim and the native actor/participant model",
    ),
    TextMutation(
        "architecture.g14-schema",
        ARCHITECTURE,
        contracts.INTENT_SCHEMA,
        '"title": "Solomon Dark Intent"',
        '"title": "Unpinned Intent"',
        "P2 intent input lost the landed G14 schema",
    ),
    TextMutation(
        "architecture.actor-state",
        ARCHITECTURE,
        contracts.TYPES,
        "readonly object_type_id: number;",
        "readonly untyped_actor_code: number;",
        "P2 state no longer consumes G14 Intent with explicit ticks and the native actor/participant/slot identities",
    ),
    TextMutation(
        "architecture.one-step-path",
        ARCHITECTURE,
        contracts.SIMULATION,
        "export function stepSimulation(",
        "function stepServerSimulation(): void {}\n\nexport function stepSimulation(",
        "P2 sim forked solo, server, or offline stepping away from one implementation",
    ),
    TextMutation(
        "architecture.fire-only-path",
        ARCHITECTURE,
        contracts.SIMULATION,
        "secondary casting belongs to P3; P2 accepts FIRE primary only",
        "secondary casting is accepted by P2",
        "P2 no longer has one FIRE-only step path with later combat rejected explicitly",
    ),
    TextMutation(
        "architecture.p3-exclusion",
        ARCHITECTURE,
        contracts.CONSTANTS,
        "export const FIRE = {",
        "// Earth implementation\nexport const FIRE = {",
        "P2 sim implemented an Earth, Frost, or Air combat path reserved for P3",
    ),
    TextMutation(
        "tick.clock-authority",
        TICK_GRAPH,
        contracts.MOVEMENT_DOC,
        "100 fixed ticks/s and 10 ms/tick.",
        "99 fixed ticks/s and 10 ms/tick.",
        "G1 clock authority no longer distinguishes the 100 Hz sim from render, transport, and wall clocks",
    ),
    TextMutation(
        "tick.doc-cadence-row",
        TICK_GRAPH,
        contracts.MOVEMENT_DOC,
        "| Normal Badguy movement | 2 fixed ticks / 20 ms eligibility |",
        "| Normal Badguy movement | 3 fixed ticks / 30 ms eligibility |",
        "G1 fixed-tick order or implementer-facing cadence rows drifted from the registered P2 contract",
    ),
    TextMutation(
        "tick.runtime-order",
        TICK_GRAPH,
        contracts.CONSTANTS,
        '"scene_dispatch",',
        '"scene_dispatch_changed",',
        "P2 runtime/test order no longer pins every G1 fixed-tick phase in sequence",
    ),
    TextMutation(
        "tick.runtime-cadence",
        TICK_GRAPH,
        contracts.CONSTANTS,
        "normal_badguy_movement: 2,",
        "normal_badguy_movement: 3,",
        "P2 runtime cadence table no longer matches the G1/G2 fixed-tick values",
    ),
    TextMutation(
        "tick.executable-order",
        TICK_GRAPH,
        contracts.SIMULATION,
        "const trackedActorCenters = snapshotTrackedCenters(intentState.actors);",
        "const trackedActorCenters = [];",
        "P2 executable actor-world order no longer snapshots, initializes, insertion-ticks, removes, then advances the fixed clock",
    ),
    SpecialMutation(
        "movement.fixture-hash",
        MOVEMENT,
        hash_constant_mutation("MOVEMENT_FIXTURE_SHA256"),
        "P2 movement fixture sha256 does not match its file: recorded 0000000000000000, movement-goldens.json hashes to 1a28704c2ddb00ee",
    ),
    TextMutation(
        "movement.doc-table",
        MOVEMENT,
        contracts.MOVEMENT_DOC,
        "| progression `+0x90` | `0.95` |",
        "| progression `+0x90` | `0.96` |",
        "G1 movement baseline or enemy constructor table drifted away from the constants implemented by P2",
    ),
    TextMutation(
        "movement.runtime-constants",
        MOVEMENT,
        contracts.CONSTANTS,
        "progression_multiplier: 0.95,",
        "progression_multiplier: 0.96,",
        "P2 player movement constants no longer equal the G1 baseline table",
    ),
    TextMutation(
        "movement.integrator-order",
        MOVEMENT,
        contracts.MOVEMENT,
        "input.x / PLAYER_MOVEMENT.input_divisor",
        "f32(input.x) / PLAYER_MOVEMENT.input_divisor",
        "P2 movement no longer preserves normalization, divide-before-narrowing, placement-before-damping, or cadence compensation",
    ),
    TextMutation(
        "movement.collision-order",
        MOVEMENT,
        contracts.COLLISION,
        "collision rectangle lookup is ambiguous for id",
        "collision rectangle duplicate id",
        "P2 collision no longer follows ordered circle placement, bounded resolution, ambiguity refusal, and native knockback semantics",
    ),
    TextMutation(
        "movement.t2-coverage",
        MOVEMENT,
        contracts.MOVEMENT_TEST,
        "expect(scenarios).toHaveLength(9);",
        "expect(scenarios).toHaveLength(8);",
        "P2 movement T2 gate no longer replays all landed open, wall, and knockback rows under fixture-declared epsilon",
    ),
    SpecialMutation(
        "rng.integer-fixture-hash",
        RNG,
        hash_constant_mutation("INTEGER_RNG_FIXTURE_SHA256"),
        "P2 integer RNG fixture sha256 does not match its file: recorded 0000000000000000, rng-goldens.json hashes to 9488a374e3a93b2b",
    ),
    SpecialMutation(
        "rng.sealed-float-fixture-hash",
        RNG,
        hash_constant_mutation("FLOAT_RNG_FIXTURE_SHA256"),
        "P2 SEALED float RNG fixture sha256 does not match its file: recorded 0000000000000000, float-rng-goldens.json hashes to 04b13d45611ee2c6",
    ),
    TextMutation(
        "rng.doc-lifecycle",
        RNG,
        contracts.MOVEMENT_DOC,
        "App **)0x00b401a8 + 0x28) * 0xEF3",
        "App **)0x00b401a8 + 0x28) * 0xEF4",
        "G1 RNG state, rounding table, sign cost, or explicit elapsed-tick seed lifecycle drifted from P2 constants",
    ),
    TextMutation(
        "rng.integer-recurrence",
        RNG,
        contracts.RNG,
        "(previous + beforePrevious) & NATIVE_RNG.mask",
        "(previous - beforePrevious) & NATIVE_RNG.mask",
        "P2 integer RNG no longer implements the 55/24 recurrence, biased bound map, or two-word signed mode",
    ),
    TextMutation(
        "rng.float-rounding",
        RNG,
        contracts.RNG,
        "const scaled = f32(unit.value * f32(requestedMagnitude));",
        "const scaled = unit.value * requestedMagnitude;",
        "P2 float RNG no longer preserves both unit rounding points, all three scaled rounding points, and native sign draws",
    ),
    TextMutation(
        "rng.corpus-coverage",
        RNG,
        contracts.RNG_TEST,
        '"unit-signed",',
        '"unit-sign-omitted",',
        "P2 RNG gate no longer consumes every integer sequence and every SEALED float pre-state, bit result, and post-state",
    ),
    SpecialMutation(
        "fire.fixture-hash",
        FIRE,
        hash_constant_mutation("PROJECTILE_FIXTURE_SHA256"),
        "P2 projectile fixture sha256 does not match its file: recorded 0000000000000000, projectile-goldens.json hashes to fc50f26b72f3d67a",
    ),
    TextMutation(
        "fire.doc-table",
        FIRE,
        contracts.PROJECTILE_DOC,
        "velocity is aim unit vector times `4.5`",
        "velocity is aim unit vector times `4.6`",
        "G2 FIRE table, emitter table, accepted damage sources, or runtime constants drifted from one another",
    ),
    TextMutation(
        "fire.emitter-lookup",
        FIRE,
        contracts.FIRE,
        "if (matches.length !== 1)",
        "if (matches.length < 1)",
        "P2 FIRE emitter no longer resolves the native facing, bank, unique point-1 candidate, and staff no-scale branch",
    ),
    TextMutation(
        "fire.flight-cadence",
        FIRE,
        contracts.FIRE,
        "moved.age_ticks % GAMEPLAY_CADENCE_TICKS.fire_terrain_contact === 0",
        "moved.age_ticks % 4 === 0",
        "P2 FIRE flight/contact no longer preserves spawn, velocity, cell/radius queries, event order, and terrain cadence",
    ),
    TextMutation(
        "fire.no-invented-lifetime",
        FIRE,
        contracts.FIRE,
        "export function tickFireProjectile(",
        "const ttl = 100;\nexport function tickFireProjectile(",
        "P2 FIRE invented a fixed projectile lifetime that G2 explicitly did not recover",
    ),
    TextMutation(
        "fire.t2-coverage",
        FIRE,
        contracts.FIRE_TEST,
        "toHaveLength(399);",
        "toHaveLength(398);",
        "P2 FIRE T2 gate no longer covers both trajectories, tombstone semantics, contact order/damage, and 499-tick residual control",
    ),
    TextMutation(
        "replay.divergence-budgets",
        REPLAY,
        contracts.TRACE,
        "rng: 0,",
        "rng: 1,",
        "P2 replay runner no longer declares zero divergence budgets for every recorded subsystem",
    ),
    TextMutation(
        "replay.g14-and-diff",
        REPLAY,
        contracts.TRACE,
        "intent: parseIntent(intentEnvelope.intent)",
        "intent: intentEnvelope.intent as never",
        "P2 replay runner no longer validates the G14 intent/state timeline and diffs every declared subsystem loudly",
    ),
    TextMutation(
        "replay.self-trace-control",
        REPLAY,
        contracts.SCRIPTED_RUN,
        "export const SCRIPTED_RUN_TICKS = 6_000;",
        "export const SCRIPTED_RUN_TICKS = 5_999;",
        "P2 self-trace no longer records/replays 60 seconds exactly and proves a one-bit corruption fails in RNG",
    ),
    TextMutation(
        "replay.cross-process-proof",
        REPLAY,
        contracts.DETERMINISM,
        "await Promise.all([firstPromise, secondPromise])",
        "await Promise.all([firstPromise, firstPromise])",
        "P2 determinism proof no longer uses two independent OS processes for 1000 ticks with byte/hash equality and a one-bit control",
    ),
    TextMutation(
        "battery.package-scripts",
        REPLAY,
        contracts.PACKAGE,
        '"conformance:self-trace": "tsx conformance/run-self-trace.ts --ticks 6000"',
        '"conformance:self-trace": "tsx conformance/run-self-trace.ts --ticks 5999"',
        "P2 package battery no longer exposes exact T2, 60-second replay, and 1000-tick determinism gates",
    ),
    TextMutation(
        "battery.quality-floors",
        REPLAY,
        contracts.QUALITY_FLOORS,
        '"unitTests": 81',
        '"unitTests": 80',
        "P2 webgame quality floors no longer ratchet to the complete sim/conformance battery",
    ),
    TextMutation(
        "battery.ci-wiring",
        REPLAY,
        contracts.CI,
        "Replay the 60-second deterministic sim self-trace",
        "Replay an abbreviated deterministic sim self-trace",
        "P2 exact T2, self-trace, and determinism scripts are no longer additive CI gates",
    ),
)


def run_contract(name: str) -> str:
    function = getattr(contracts, name, None)
    if not callable(function):
        raise RuntimeError(f"mutation names unknown contract {name}")
    result = function()
    if not isinstance(result, str) or not result:
        raise RuntimeError(f"contract {name} returned no green detail")
    return result


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def write_transcript(path: Path, *, claim: str, stage: str, status: str, message: str) -> None:
    path.write_text(
        f"claim: {claim}\nstage: {stage}\nstatus: {status}\nmessage: {message}\n",
        encoding="utf-8",
    )


def run_mutations(evidence_dir: Path) -> list[MutationResult]:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    results: list[MutationResult] = []
    for index, mutation in enumerate(MUTATIONS, start=1):
        prefix = f"{index:03d}-{slug(mutation.claim)}"
        before_name = f"{prefix}-green-before.log"
        trip_name = f"{prefix}-trip.log"
        after_name = f"{prefix}-restored-green.log"

        clear_contract_bytecode()
        green_before = run_contract(mutation.contract)
        write_transcript(
            evidence_dir / before_name,
            claim=mutation.claim,
            stage="green-before",
            status="PASS",
            message=green_before,
        )

        clear_contract_bytecode()
        observed = ""
        activation = text_mutation(mutation) if isinstance(mutation, TextMutation) else mutation.activate()
        with activation:
            try:
                run_contract(mutation.contract)
            except contracts.StaticReTestFailure as exc:
                observed = str(exc)
        if observed != mutation.expected:
            raise RuntimeError(
                f"mutation {mutation.claim} expected {mutation.expected!r}, observed {observed!r}"
            )
        write_transcript(
            evidence_dir / trip_name,
            claim=mutation.claim,
            stage="trip",
            status="EXPECTED_FAIL",
            message=observed,
        )

        clear_contract_bytecode()
        restored_green = run_contract(mutation.contract)
        if restored_green != green_before:
            raise RuntimeError(f"mutation {mutation.claim} did not restore the same green baseline")
        write_transcript(
            evidence_dir / after_name,
            claim=mutation.claim,
            stage="restored-green",
            status="PASS",
            message=restored_green,
        )
        results.append(
            MutationResult(
                claim=mutation.claim,
                contract=mutation.contract,
                expected_message=mutation.expected,
                observed_message=observed,
                green_before=green_before,
                restored_green=restored_green,
                transcripts=(before_name, trip_name, after_name),
            )
        )
    clear_contract_bytecode()
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()
    results = run_mutations(args.evidence_dir.resolve())
    summary = {
        "schema": "webgame-sim-core-mutation-audit-v1",
        "mutations": len(results),
        "all_tripped_with_exact_message": True,
        "all_restored_green": True,
        "results": [asdict(result) for result in results],
    }
    (args.evidence_dir / "mutation-results.json").write_text(
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
