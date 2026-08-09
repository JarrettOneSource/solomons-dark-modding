"""Static contracts for the P2 deterministic browser simulation core."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from static_re_contract_support import (
    ROOT,
    StaticReTestFailure,
    assert_recorded_hash_matches_file,
)


WEBGAME = ROOT / "webgame"
SIM = WEBGAME / "sim"
CONFORMANCE = WEBGAME / "conformance"
ROADMAP = ROOT / "docs/browser-rebuild-roadmap.md"
MOVEMENT_DOC = ROOT / "docs/reverse-engineering/native-movement-and-tick.md"
TIMING_DOC = ROOT / "docs/reverse-engineering/game-timing-scale.md"
PROJECTILE_DOC = ROOT / "docs/reverse-engineering/native-projectile-and-spell-mechanics.md"
PARTICIPANT_DOC = ROOT / "docs/multiplayer-participant-model.md"
ELEMENT_DAMAGE_DOC = ROOT / "docs/reverse-engineering/multiplayer-element-damage-2026-07-26.md"
FIRE_CONTACT_DOC = ROOT / "docs/reverse-engineering/multiplayer-fireball-contact-2026-07-26.md"
INTENT_SCHEMA = ROOT / "webgame-contracts/intent-schema.json"
MOVEMENT_FIXTURE = ROOT / "tests/fixtures/webgame/movement-goldens.json"
PROJECTILE_FIXTURE = ROOT / "tests/fixtures/webgame/projectile-goldens.json"
INTEGER_RNG_FIXTURE = ROOT / "tests/fixtures/webgame/rng-goldens.json"
FLOAT_RNG_FIXTURE = ROOT / "tests/fixtures/webgame/float-rng-goldens.json"
PACKAGE = WEBGAME / "package.json"
QUALITY_FLOORS = WEBGAME / "quality-floors.json"
CI = ROOT / ".github/workflows/lua-authoring-contracts.yml"

CONSTANTS = SIM / "constants.ts"
TYPES = SIM / "types.ts"
RNG = SIM / "rng.ts"
COLLISION = SIM / "collision.ts"
MOVEMENT = SIM / "movement.ts"
FIRE = SIM / "fire.ts"
SIMULATION = SIM / "simulation.ts"
SERIALIZE = SIM / "serialize.ts"
SIM_TEST = SIM / "simulation.test.ts"
MOVEMENT_TEST = CONFORMANCE / "t2-movement.test.ts"
FIRE_TEST = CONFORMANCE / "t2-fire-projectile.test.ts"
RNG_TEST = CONFORMANCE / "native-rng.test.ts"
TRACE = CONFORMANCE / "trace-replay.ts"
TRACE_TEST = CONFORMANCE / "trace-replay.test.ts"
SELF_TRACE = CONFORMANCE / "run-self-trace.ts"
SCRIPTED_RUN = CONFORMANCE / "scripted-run.ts"
DETERMINISM = CONFORMANCE / "determinism.ts"
DETERMINISM_TEST = CONFORMANCE / "determinism.test.ts"
DETERMINISM_WORKER = CONFORMANCE / "determinism-worker.ts"

MOVEMENT_FIXTURE_SHA256 = "1a28704c2ddb00ee92c6222563525cbb2c0de63179563d8ac0e8c9e2764c354a"
PROJECTILE_FIXTURE_SHA256 = "fc50f26b72f3d67a3797ffc883507c4fef0cd36e42b8f0bf2e1a878603299274"
INTEGER_RNG_FIXTURE_SHA256 = "9488a374e3a93b2be18b7f56e3b638e5df775f495fb2790ca3d0e746d281c3f6"
FLOAT_RNG_FIXTURE_SHA256 = "04b13d45611ee2c67dac2a73ff8572e7f948516eb6c05411686b609b970d9665"


def _read_text(path: Path, consequence: str) -> str:
    if not path.is_file():
        raise StaticReTestFailure(consequence)
    return path.read_text(encoding="utf-8")


def _read_json(path: Path, consequence: str) -> dict[str, Any]:
    try:
        value = json.loads(_read_text(path, consequence))
    except json.JSONDecodeError as exc:
        raise StaticReTestFailure(consequence) from exc
    if not isinstance(value, dict):
        raise StaticReTestFailure(consequence)
    return value


def _require_tokens(text: str, tokens: tuple[str, ...], consequence: str) -> None:
    if any(token not in text for token in tokens):
        raise StaticReTestFailure(consequence)


def _require_regex(text: str, pattern: str, consequence: str) -> None:
    if re.search(pattern, text, flags=re.MULTILINE | re.DOTALL) is None:
        raise StaticReTestFailure(consequence)


def _production_sim_sources() -> dict[str, str]:
    paths = sorted(path for path in SIM.rglob("*.ts") if not path.name.endswith(".test.ts"))
    relative_paths = {path.relative_to(WEBGAME).as_posix() for path in paths}
    witnesses = {
        "sim/collision.ts",
        "sim/constants.ts",
        "sim/fire.ts",
        "sim/float32.ts",
        "sim/index.ts",
        "sim/movement.ts",
        "sim/rng.ts",
        "sim/serialize.ts",
        "sim/simulation.ts",
        "sim/types.ts",
    }
    missing = sorted(witnesses - relative_paths)
    if missing:
        raise StaticReTestFailure(
            "P2 purity sweep did not reach every deterministic sim source witness"
        )
    return {
        path.relative_to(WEBGAME).as_posix(): _read_text(
            path,
            "P2 purity sweep could not read a deterministic sim source",
        )
        for path in paths
    }


def test_webgame_sim_core_is_pure_single_path_and_actor_model_pinned() -> str:
    sources = _production_sim_sources()
    combined = "\n".join(sources[name] for name in sorted(sources))
    forbidden = re.compile(
        r"\b(?:document|window|navigator|HTMLElement|WebSocket|XMLHttpRequest)\b"
        r"|\b(?:Date|performance)\.now\s*\("
        r"|\bMath\.random\s*\("
        r"|\b(?:fetch|setTimeout|setInterval)\s*\("
        r"|from\s+[\"']node:(?:fs|fs/promises|path|child_process|crypto)[\"']"
        r"|\bprocess\.",
    )
    offenders = sorted(name for name, source in sources.items() if forbidden.search(source))
    if offenders:
        raise StaticReTestFailure(
            "P2 sim purity was broken by DOM, wall-clock, random, process, or direct I/O access"
        )

    roadmap = _read_text(ROADMAP, "P2 architecture lost its roadmap authority")
    _require_tokens(
        roadmap,
        (
            "There is exactly one sim and exactly one server implementation.",
            "Solo, co-op, and dedicated run identical code paths.",
            "The sim must be pure.",
            "No DOM, no wall clock, no `Math.random`, no direct I/O",
            "`webgame/sim/`",
            "object_type_id families, tracked_enemy",
            "participant/slot model from `docs/multiplayer-participant-model.md`",
        ),
        "P2 roadmap no longer pins one pure sim and the native actor/participant model",
    )

    types = sources["sim/types.ts"]
    simulation = sources["sim/simulation.ts"]
    schema = _read_json(INTENT_SCHEMA, "P2 intent input lost the landed G14 schema")
    if schema.get("title") != "Solomon Dark Intent":
        raise StaticReTestFailure("P2 intent input lost the landed G14 schema")
    _require_tokens(
        types + simulation,
        (
            'import type { Intent } from "../input/intent.js";',
            "readonly intent: Intent;",
            "readonly object_type_id: number;",
            "readonly tracked_enemy: boolean;",
            'export type ParticipantKind = "LocalHuman" | "RemoteParticipant";',
            'export type ParticipantControllerKind = "Native" | "LuaBrain";',
            "readonly participants: readonly ParticipantState[];",
            "readonly slots: readonly (string | null)[];",
            "readonly elapsed_app_ticks: number;",
            'export const LOCAL_PARTICIPANT_ID = "1";',
            'export const FIRST_LUA_CONTROLLED_PARTICIPANT_ID = "1152921504606851072";',
            "slots: [participant.id, null, null, null]",
            "matches.length !== 1",
        ),
        "P2 state no longer consumes G14 Intent with explicit ticks and the native actor/participant/slot identities",
    )

    if re.search(r"\bstep(?:Solo|Server|Offline)Simulation\b", combined) is not None:
        raise StaticReTestFailure("P2 sim forked solo, server, or offline stepping away from one implementation")
    _require_tokens(
        simulation,
        (
            "export function stepSimulation(",
            'if (intent.slot === "secondary")',
            'throw new Error("secondary casting belongs to P3; P2 accepts FIRE primary only")',
            'if (intent.phase !== "press")',
            "const projectile = createFireProjectile(",
            "config.cast_glyph_points",
            "state.next_actor_serial",
        ),
        "P2 no longer has one FIRE-only step path with later combat rejected explicitly",
    )
    if re.search(r"\b(?:earth|frost|lightning|boulder)\b", combined, flags=re.IGNORECASE):
        raise StaticReTestFailure("P2 sim implemented an Earth, Frost, or Air combat path reserved for P3")
    return "pure explicit-state G14 sim, native actors/participants/slots, and one FIRE-only step path are pinned"


def test_webgame_sim_tick_graph_and_cadences_match_g1_tables() -> str:
    doc = _read_text(MOVEMENT_DOC, "P2 tick graph lost the landed G1 document")
    timing = _read_text(TIMING_DOC, "P2 tick graph lost the timing-scale correction")
    constants = _read_text(CONSTANTS, "P2 tick graph constants disappeared")
    simulation = _read_text(SIMULATION, "P2 fixed-tick implementation disappeared")
    sim_test = _read_text(SIM_TEST, "P2 tick-graph executable contract disappeared")

    _require_tokens(
        doc + timing,
        (
            "100 fixed ticks/s and 10 ms/tick.",
            "not advance actors and must not be used as the browser simulation clock.",
            "This address is a native tick-frequency conversion constant, not a general simulation speed",
            "Transport timestamps and Lua",
            "wall-clock timers must not enter the deterministic browser core",
        ),
        "G1 clock authority no longer distinguishes the 100 Hz sim from render, transport, and wall clocks",
    )
    _require_tokens(
        doc,
        (
            "ticks the application-level ActorWorld",
            "dispatches the current scene",
            "runs the pre-world pass",
            "snapshots tracked actor centers",
            "calls the game-state pass",
            "first initializes pending actors",
            "insertion order",
            "removes actors marked for destruction",
            "post-actor state",
            "increments scene/global tick",
            "| Native fixed simulation | 10 ms / 100 Hz |",
            "| Normal Badguy movement | 2 fixed ticks / 20 ms eligibility |",
            "| Badguy alternate states | 5, 10, or 15 fixed ticks |",
        ),
        "G1 fixed-tick order or implementer-facing cadence rows drifted from the registered P2 contract",
    )
    order_rows_pattern = (
        r'"application_actor_world",\s*"scene_dispatch",\s*"game_pre_world",\s*'
        r'"tracked_actor_snapshot",\s*"game_state",\s*"initialize_pending_actors",\s*'
        r'"tick_actors_in_insertion_order",\s*"remove_destroyed_actors",\s*'
        r'"game_post_world",\s*"scene_tick_counter_and_timers",'
    )
    runtime_order_pattern = (
        r'TICK_SYSTEM_ORDER\s*=\s*\[\s*'
        + order_rows_pattern
        + r"\s*\]"
    )
    _require_regex(
        constants,
        runtime_order_pattern,
        "P2 runtime/test order no longer pins every G1 fixed-tick phase in sequence",
    )
    _require_regex(
        sim_test,
        r"expect\(TICK_SYSTEM_ORDER\)\.toEqual\(\[\s*"
        + order_rows_pattern
        + r"\s*\]\);",
        "P2 runtime/test order no longer pins every G1 fixed-tick phase in sequence",
    )
    _require_regex(
        constants,
        r"export const TICK_RATE_HZ = 100;\s*export const TICK_INTERVAL_MS = 10;[\s\S]*?"
        r"native_fixed_simulation: 1,\s*normal_badguy_movement: 2,\s*"
        r"badguy_alternate_5: 5,\s*badguy_alternate_10: 10,\s*"
        r"badguy_alternate_15: 15,\s*fire_target_contact: 1,\s*fire_terrain_contact: 5,",
        "P2 runtime cadence table no longer matches the G1/G2 fixed-tick values",
    )
    _require_regex(
        simulation,
        r"const trackedActorCenters = snapshotTrackedCenters\(intentState\.actors\);\s*"
        r"const initializedActors = initializePendingActors\([\s\S]*?\);\s*"
        r"const ticked = tickActors\(initializedActors, state\.scene_tick, config\);\s*"
        r"return \{\s*\.\.\.state,\s*elapsed_app_ticks: state\.elapsed_app_ticks \+ 1,\s*"
        r"scene_tick: state\.scene_tick \+ 1,\s*"
        r"actors: ticked\.actors\.filter\(\(actor\) => !actor\.destroyed\),",
        "P2 executable actor-world order no longer snapshots, initializes, insertion-ticks, removes, then advances the fixed clock",
    )
    return "100 Hz clock, all ten G1 phases, actor insertion order, removal, and exact gameplay cadences are pinned"


def test_webgame_sim_movement_and_collision_replay_the_landed_t2_contract() -> str:
    assert_recorded_hash_matches_file(
        MOVEMENT_FIXTURE_SHA256,
        MOVEMENT_FIXTURE,
        "P2 movement fixture sha256",
    )
    doc = _read_text(MOVEMENT_DOC, "P2 movement implementation lost the G1 document")
    constants = _read_text(CONSTANTS, "P2 movement constants disappeared")
    movement = _read_text(MOVEMENT, "P2 movement integrator disappeared")
    collision = _read_text(COLLISION, "P2 collision implementation disappeared")
    test = _read_text(MOVEMENT_TEST, "P2 movement T2 replay disappeared")

    _require_tokens(
        doc,
        (
            "| actor `+0x120` | `1.0` | Common actor construction; transient native movement/status multiplier. |",
            "| actor `+0x74` | `1.0` | Common actor construction; native move-speed scale. |",
            "| progression `+0x90` | `0.95` |",
            "| global | `1.25` | `0x00784740`; cap scale. |",
            "| resulting cap | `1.1875` |",
            "| actor `+0x218` | `1.0` |",
            "| Imp (and Green Imp inheritance) | `0x00473E30` (`0x00474D20`) | `4.5`",
            "| Zombie | `0x004740C0` | `1.0 * 0.85`",
            "| Wraith | `0x00474470` | `1.0` |",
            "| Demon Skull | `0x00474660` | `4.0`",
            "| Dire Faculty | `0x00474E50` | `2.75`",
            "| Spider | `0x004759A0` | `3 + RandomFloat(2)` = `[3,5]`",
            "| Skeleton | `0x004771B0` | `(1.25 + RandomFloat(1)) * 1.25^2`",
            "| Demon | `0x00479150` | `1.0 * 0.75` |",
            "| Coffin | `0x00479940` | `1.0 * 0.75` |",
            "| Maggot | `0x0047E0F0` | `1 + RandomFloat(1)` = `[1,2]`",
            "| Skeleton Archer | `0x0048A6B0` | Skeleton result `* 0.75` |",
            "| Skeleton Mage | `0x0048ABB0` | Archer result `* 0.65` |",
            "| Heartmonger | `0x0048B970` | Skeleton result `* 0.65 * 0.75` |",
        ),
        "G1 movement baseline or enemy constructor table drifted away from the constants implemented by P2",
    )
    _require_regex(
        constants,
        r"export const PLAYER_MOVEMENT = \{\s*input_divisor: 10,\s*transient_multiplier: 1,\s*"
        r"move_speed_scale: 1,\s*progression_multiplier: 0\.95,\s*global_cap_scale: 1\.25,\s*"
        r"resulting_cap: 1\.1875,\s*move_step_scale: 1,\s*move_threshold_squared: 0\.01,\s*"
        r"ordinary_damping: Math\.fround\(0\.9\),\s*controlled_damping: Math\.fround\(0\.95\),\s*\}",
        "P2 player movement constants no longer equal the G1 baseline table",
    )
    _require_tokens(
        movement,
        (
            "const input = normalizeAtMostOne(actor.movement.intent);",
            "input.x / PLAYER_MOVEMENT.input_divisor",
            "const velocityBeforeDamping = capVelocity(accumulated, cap);",
            "if (lengthSquared > PLAYER_MOVEMENT.move_threshold_squared)",
            '"alternate",',
            "const damping = actor.movement.controlled_damping",
            "x: f32(dampingSource.x * damping)",
            "actor.insertion_order % cadence !== globalTick % cadence",
            "* cadence;",
        ),
        "P2 movement no longer preserves normalization, divide-before-narrowing, placement-before-damping, or cadence compensation",
    )
    _require_tokens(
        doc + constants + collision + movement,
        (
            "`movement_collision_test_circle_placement` is `0x00523C90`",
            "Multiple contacts are resolved sequentially in collision-list order.",
            "iteration bound of 8 at `0x00807888`",
            "step = min(remaining_distance_at_+0x13C, 10)",
            "temporarily set target_radius = original_radius * 0.6",
            "iteration_limit: 8",
            "knockback_radius_scale: 0.6",
            "collision rectangle lookup is ambiguous for id",
            "for (const rectangle of rectangles)",
            "Math.min(knockback.remaining_distance, 10)",
        ),
        "P2 collision no longer follows ordered circle placement, bounded resolution, ambiguity refusal, and native knockback semantics",
    )
    _require_tokens(
        test,
        (
            'readRepositoryJson("tests/fixtures/webgame/movement-goldens.json")',
            "const positionEpsilon = fixtureNumber(epsilon.position_absolute",
            "const scalarEpsilon = fixtureNumber(epsilon.scalar_absolute",
            "expect(scenarios).toHaveLength(9);",
            "toBeGreaterThan(100)",
            "tickPlayerMovement",
            "tickPlayerKnockback",
            'id.startsWith("wall_")',
            'id === "knockback_contact"',
        ),
        "P2 movement T2 gate no longer replays all landed open, wall, and knockback rows under fixture-declared epsilon",
    )
    return "hashed movement corpus, all G1 tables, exact integrator/collision semantics, and nine-scenario T2 replay are pinned"


def test_webgame_sim_rng_is_bit_exact_for_integer_and_sealed_float_corpora() -> str:
    assert_recorded_hash_matches_file(
        INTEGER_RNG_FIXTURE_SHA256,
        INTEGER_RNG_FIXTURE,
        "P2 integer RNG fixture sha256",
    )
    assert_recorded_hash_matches_file(
        FLOAT_RNG_FIXTURE_SHA256,
        FLOAT_RNG_FIXTURE,
        "P2 SEALED float RNG fixture sha256",
    )
    doc = _read_text(MOVEMENT_DOC, "P2 RNG implementation lost the G1 document")
    constants = _read_text(CONSTANTS, "P2 RNG constants disappeared")
    rng = _read_text(RNG, "P2 native RNG implementation disappeared")
    test = _read_text(RNG_TEST, "P2 RNG conformance replay disappeared")

    _require_tokens(
        doc + constants,
        (
            "| `+0x00` | 32 bits | first ring index, initially 0 |",
            "| `+0x04` | 32 bits | second ring index, initially 31 |",
            "| `+0x08..+0xE0` | 55 x 32 bits | state words; only low 30 bits are used |",
            "| `+0xE4` | 32 bits | float divisor, `100000` |",
            "mask = 0x3fffffff",
            "result = ((u >> 6) & (P - 1)) % n",
            "| `1.0` | 0 / 100001 | 0.00% |",
            "| `3.0` | 27,836 / 100001 | 27.84% |",
            "| `4.5` | 25,225 / 100001 | 25.22% |",
            "A signed float request costs **two** stream words, not one",
            "rounds to float32 twice rather than three times",
            "seed = *(int *)(*(App **)0x00b401a8 + 0x28) * 0xEF3",
            "App+0x28` is an **elapsed-tick counter**",
            "carry the tick count as explicit state",
            "mask: 0x3fffffff",
            "state_word_count: 55",
            "initial_index_b: 31",
            "stock_divisor: 100_000",
            "seed_tick_multiplier: 0x0ef3",
        ),
        "G1 RNG state, rounding table, sign cost, or explicit elapsed-tick seed lifecycle drifted from P2 constants",
    )
    _require_tokens(
        rng,
        (
            "return Math.imul(elapsedAppTicks, NATIVE_RNG.seed_tick_multiplier);",
            "stateWords[0] = seed & NATIVE_RNG.mask;",
            "stateWords[1] = 1;",
            "(previous + beforePrevious) & NATIVE_RNG.mask",
            "const word = (left + right) & NATIVE_RNG.mask;",
            "value: ((draw.value >>> 6) & (powerOfTwo - 1)) % bound",
            "const sign = positiveInteger(magnitude.state, 2);",
        ),
        "P2 integer RNG no longer implements the 55/24 recurrence, biased bound map, or two-word signed mode",
    )
    _require_tokens(
        rng,
        (
            "const narrowedInteger = f32(integer.value);",
            "value: f32(narrowedInteger / state.divisor)",
            "const scaled = f32(unit.value * f32(requestedMagnitude));",
            "return signed ? applyNativeSign(magnitude.state, magnitude.value) : magnitude;",
            "return signed ? applyNativeSign(unit.state, scaled) : { value: scaled, state: unit.state };",
        ),
        "P2 float RNG no longer preserves both unit rounding points, all three scaled rounding points, and native sign draws",
    )
    _require_tokens(
        test,
        (
            'readRepositoryJson("tests/fixtures/webgame/rng-goldens.json")',
            "toHaveLength(4)",
            "expect(state.state_words).toEqual(integerArray(sequence.final_state_words",
            'readRepositoryJson("tests/fixtures/webgame/float-rng-goldens.json")',
            "scaled_float32_rounding_points",
            "unit_float32_rounding_points",
            '"scaled-magnitude-1-unsigned"',
            '"scaled-magnitude-3-unsigned"',
            '"scaled-magnitude-4_5-signed"',
            '"unit-unsigned"',
            '"unit-signed"',
            "expectRngState(state, fixtureRecord(expected.pre_call",
            "float32Bits(draw.value)",
            "expectRngState(state, fixtureRecord(expected.post_call",
        ),
        "P2 RNG gate no longer consumes every integer sequence and every SEALED float pre-state, bit result, and post-state",
    )
    return "hashed integer and SEALED float corpora, exact recurrence, lifecycle, rounding points, sign modes, and full replay are pinned"


def test_webgame_sim_fire_projectile_replays_the_landed_g2_contract() -> str:
    assert_recorded_hash_matches_file(
        PROJECTILE_FIXTURE_SHA256,
        PROJECTILE_FIXTURE,
        "P2 projectile fixture sha256",
    )
    doc = _read_text(PROJECTILE_DOC, "P2 FIRE implementation lost the G2 document")
    element_damage = _read_text(ELEMENT_DAMAGE_DOC, "P2 FIRE damage lost its accepted element-damage source")
    fire_contact = _read_text(FIRE_CONTACT_DOC, "P2 FIRE damage lost its accepted contact source")
    constants = _read_text(CONSTANTS, "P2 FIRE constants disappeared")
    fire = _read_text(FIRE, "P2 FIRE projectile implementation disappeared")
    test = _read_text(FIRE_TEST, "P2 FIRE T2 replay disappeared")

    _require_tokens(
        doc + element_damage + fire_contact + constants,
        (
            "| Fire / Fireball | `16` | `0x0053DC60` | factory type `0x7D4`, constructor `0x005E0970` |",
            "| Fire | cast glyph emitter plus local `(0,+10)`, then `20` units along aim; velocity is aim unit vector times `4.5` | actor radius `22.5`; candidate query radius `20` every tick in the current spatial cell; terrain every fifth tick with five-tick lookahead | no fixed timer found; first impact removes the Fireball; status/area work is dispatched before removal |",
            "| Fire one-shot | exactly `4.0` in `multiplayer-fireball-contact-2026-07-26.md` | `4.0`, error `0`, epsilon `0.000001` |",
            "| `->+8 == 0x1B5C` | virtual call `vt+0x24` | `K = (int)actor->+0x238`, **unclamped** |",
            "| otherwise | `[g+0x5D0]` / `[g+0x5D4]` | `K = (int)clamp(actor->+0x238 - 14.0, 0.0, 2.0)` |",
            "point index 1",
            "| `#3244..#3483` | 240 |",
            "| Ether, Fire | `(0, +10)` |",
            "Fire additionally pushes `20` units along aim.",
            "client casts reached one native impact and exactly `4.0` damage",
            '"docs/reverse-engineering/multiplayer-element-damage-2026-07-26.md"',
            '"docs/reverse-engineering/multiplayer-fireball-contact-2026-07-26.md"',
            "object_type_id: 0x07d4",
            "skill_id: 16",
            "local_offset_y: 10",
            "forward_spawn_offset: 20",
            "speed_per_tick: 4.5",
            "collision_radius: 22.5",
            "target_query_radius: 20",
            "terrain_lookahead_ticks: 5",
            "contact_damage: 4",
        ),
        "G2 FIRE table, emitter table, accepted damage sources, or runtime constants drifted from one another",
    )
    _require_tokens(
        fire,
        (
            "const truncatedHeading = Math.trunc(headingDegrees);",
            "Math.trunc((truncatedHeading + 7) / 15)",
            "if (facing >= 24)",
            "facing -= 24;",
            'spriteSet.kind === "staff"',
            "Math.trunc(Math.max(0, Math.min(2, spriteSet.pose - 14)))",
            "entry.point_index === 1",
            "if (matches.length !== 1)",
            'wizard.sprite_set.kind === "staff"',
            "? 1",
            ": wizard.movement.move_speed_scale",
        ),
        "P2 FIRE emitter no longer resolves the native facing, bank, unique point-1 candidate, and staff no-scale branch",
    )
    _require_tokens(
        fire,
        (
            "emitter.x + FIRE.local_offset_x + aimUnit.x * FIRE.forward_spawn_offset",
            "emitter.y + FIRE.local_offset_y + aimUnit.y * FIRE.forward_spawn_offset",
            "projectile.aim_unit.x * FIRE.speed_per_tick",
            "sameSpatialCell(projectile.position, actor.position, cellSize)",
            "distance <= FIRE.target_query_radius + actor.radius",
            "distance <= projectile.radius + actor.radius",
            'kind: "fire_status"',
            'kind: "damage"',
            'kind: "fire_removed"',
            "moved.age_ticks % GAMEPLAY_CADENCE_TICKS.fire_terrain_contact === 0",
            "FIRE.speed_per_tick * FIRE.terrain_lookahead_ticks",
        ),
        "P2 FIRE flight/contact no longer preserves spawn, velocity, cell/radius queries, event order, and terrain cadence",
    )
    if re.search(r"(?:lifetime|ttl|max_age|maxAge)\s*[:=]", fire, flags=re.IGNORECASE):
        raise StaticReTestFailure("P2 FIRE invented a fixed projectile lifetime that G2 explicitly did not recover")
    _require_tokens(
        test,
        (
            'readRepositoryJson("tests/fixtures/webgame/projectile-goldens.json")',
            'for (const rankName of ["rank1", "rank2"] as const)',
            "toHaveLength(399)",
            "Row 398 is the recorder's explicit frozen tombstone after removal.",
            "toBeLessThanOrEqual(epsilon)",
            "expect(noInventedLifetime.age_ticks).toBe(399);",
            "Fire contact lookup must refuse missing or duplicate candidates",
            '"fire_status",\n      "damage",\n      "fire_removed",',
            "fixtureNumber(contact.observedDamage",
            "fixtureNumber(contact.residualObservationTicks",
            "fixtureNumber(contact.subsequentHpDamage",
        ),
        "P2 FIRE T2 gate no longer covers both trajectories, tombstone semantics, contact order/damage, and 499-tick residual control",
    )
    return "hashed G2 FIRE corpus, exact emitter/flight/contact semantics, cited 4 damage, no lifetime, and both T2 ranks are pinned"


def test_webgame_sim_replay_determinism_and_ci_gates_are_wired() -> str:
    trace = _read_text(TRACE, "P2 trace replay runner disappeared")
    trace_test = _read_text(TRACE_TEST, "P2 trace replay controls disappeared")
    self_trace = _read_text(SELF_TRACE, "P2 60-second replay executable disappeared")
    scripted = _read_text(SCRIPTED_RUN, "P2 scripted 60-second intent stream disappeared")
    determinism = _read_text(DETERMINISM, "P2 cross-process determinism proof disappeared")
    determinism_test = _read_text(DETERMINISM_TEST, "P2 determinism control test disappeared")
    worker = _read_text(DETERMINISM_WORKER, "P2 independent determinism worker disappeared")
    package = _read_json(PACKAGE, "P2 webgame package scripts are absent or malformed")
    floors = _read_json(QUALITY_FLOORS, "P2 webgame quality floors are absent or malformed")
    ci = _read_text(CI, "P2 webgame CI workflow disappeared")

    _require_regex(
        trace + trace_test,
        r"REPLAY_DIVERGENCE_BUDGETS\s*=\s*\{\s*clock: 0,\s*participants: 0,\s*rng: 0,\s*"
        r"movement: 0,\s*fire: 0,\s*actor_model: 0,\s*\}",
        "P2 replay runner no longer declares zero divergence budgets for every recorded subsystem",
    )
    _require_tokens(
        trace,
        (
            'readonly schema: "solomon-dark-sim-trace-v1";',
            "readonly tick_rate_hz: 100;",
            "readonly intents: readonly IntentEnvelope[];",
            "readonly expected_state: SimulationState;",
            "intent: parseIntent(intentEnvelope.intent)",
            'if (candidate.schema !== "solomon-dark-sim-trace-v1")',
            "if (candidate.tick_rate_hz !== 100)",
            "if (timelineValues.length === 0)",
            "subsystemProjection(state, subsystem)",
            "REPLAY_DIVERGENCE_BUDGETS[subsystem]",
            "`${subsystem} divergence at tick ${tick}",
        ),
        "P2 replay runner no longer validates the G14 intent/state timeline and diffs every declared subsystem loudly",
    )
    _require_tokens(
        scripted + self_trace + trace_test,
        (
            "export const SCRIPTED_RUN_TICKS = 6_000;",
            "const trace = createSelfTrace(initial, ticks);",
            "const replay = replayTrace(reparsed);",
            "replayTrace(corruptTraceSingleBit(reparsed));",
            'if (!corruptionMessage.includes("rng divergence"))',
            "seconds_recorded: trace.timeline.length / trace.tick_rate_hz",
            "corrupted_trace_failed: true",
            'toThrow(\n      "rng divergence at tick 10 $.state_words[0]"',
        ),
        "P2 self-trace no longer records/replays 60 seconds exactly and proves a one-bit corruption fails in RNG",
    )
    _require_tokens(
        determinism + determinism_test + worker,
        (
            'import { spawn } from "node:child_process";',
            "const firstPromise = launchWorker(ticks, \"determinism worker A\");",
            "const secondPromise = launchWorker(ticks, \"determinism worker B\");",
            "await Promise.all([firstPromise, secondPromise])",
            "if (!firstBytes.equals(secondBytes) || first.sha256 !== second.sha256)",
            "ticks < 1_000",
            "state_words: [firstWord ^ 1",
            "if (corruptedHash === first.sha256)",
            "process_ids: [first.pid, second.pid]",
            "const receipt = await proveCrossProcessDeterminism(1_000);",
            "expect(receipt.process_ids[0]).not.toBe(receipt.process_ids[1]);",
            "expect(receipt.sha256).not.toBe(receipt.single_bit_control_sha256);",
            "pid: process.pid",
        ),
        "P2 determinism proof no longer uses two independent OS processes for 1000 ticks with byte/hash equality and a one-bit control",
    )

    scripts = package.get("scripts")
    if not isinstance(scripts, dict) or {
        "conformance:t2": scripts.get("conformance:t2"),
        "conformance:self-trace": scripts.get("conformance:self-trace"),
        "determinism": scripts.get("determinism"),
    } != {
        "conformance:t2": "vitest run conformance/t2-movement.test.ts conformance/t2-fire-projectile.test.ts conformance/native-rng.test.ts --reporter=verbose",
        "conformance:self-trace": "tsx conformance/run-self-trace.ts --ticks 6000",
        "determinism": "tsx conformance/run-determinism.ts 1000",
    }:
        raise StaticReTestFailure("P2 package battery no longer exposes exact T2, 60-second replay, and 1000-tick determinism gates")
    expected_floors = {
        "lintFiles": 73,
        "typecheckedFiles": 70,
        "unitTestFiles": 22,
        "unitTests": 81,
    }
    if any(
        not isinstance(floors.get(key), int) or floors[key] < value
        for key, value in expected_floors.items()
    ):
        raise StaticReTestFailure("P2 webgame quality floors no longer ratchet to the complete sim/conformance battery")
    _require_tokens(
        ci,
        (
            "Replay T2 movement, FIRE, and native RNG goldens",
            "npm --prefix webgame run conformance:t2",
            "Replay the 60-second deterministic sim self-trace",
            "npm --prefix webgame run conformance:self-trace",
            "Prove cross-process simulation determinism",
            "npm --prefix webgame run determinism",
        ),
        "P2 exact T2, self-trace, and determinism scripts are no longer additive CI gates",
    )
    return "zero-budget trace replay, loud corruption, two-process hash proof, ratcheted battery, and additive CI gates are pinned"
