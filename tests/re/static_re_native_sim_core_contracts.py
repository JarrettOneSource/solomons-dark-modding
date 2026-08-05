"""Static contracts for the native movement, tick, and RNG conformance corpus."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from static_re_contract_support import ROOT, StaticReTestFailure, read_text


DOC = ROOT / "docs/reverse-engineering/native-movement-and-tick.md"
ROADMAP = ROOT / "docs/browser-rebuild-roadmap.md"
MOVEMENT_FIXTURE = ROOT / "tests/fixtures/webgame/movement-goldens.json"
RNG_FIXTURE = ROOT / "tests/fixtures/webgame/rng-goldens.json"
RECORDER = ROOT / "tools/record_native_sim_goldens.py"
RNG_SEAM = (
    ROOT
    / "SolomonDarkModLoader/src/lua_engine_bindings_debug/functions_native_rng.inl"
)
DEBUG_BINDINGS = ROOT / "SolomonDarkModLoader/src/lua_engine_bindings_debug.cpp"
DEBUG_INCLUDES = (
    ROOT / "SolomonDarkModLoader/src/lua_engine_bindings_debug/functions.inl"
)
LUA_API = ROOT / "api/lua/sd.lua"
PROJECT = ROOT / "SolomonDarkModLoader/SolomonDarkModLoader.vcxproj"
PROJECT_FILTERS = ROOT / "SolomonDarkModLoader/SolomonDarkModLoader.vcxproj.filters"
TRANSPORT = ROOT / "SolomonDarkModLoader/src/multiplayer_local_transport.cpp"
SERVICE_LOOP = ROOT / "SolomonDarkModLoader/src/multiplayer_service_loop.cpp"
RUNTIME_TICK = ROOT / "SolomonDarkModLoader/src/runtime_tick_service.cpp"
GAMEPLAY_CONSTANTS = (
    ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/gameplay_constants.inl"
)
LUA_AI = ROOT / "SolomonDarkModLoader/src/lua_engine_bindings_ai.cpp"
BOT_BRAIN = ROOT / "mods/bot-brain/scripts/main.lua"

GAME_SHA256 = "03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3"
RNG_MASK = 0x3FFFFFFF
RNG_WORD_COUNT = 55


def _require_tokens(label: str, text: str, tokens: tuple[str, ...]) -> None:
    missing = [token for token in tokens if token not in text]
    if missing:
        raise StaticReTestFailure(
            f"{label} is missing required token(s): {', '.join(missing)}"
        )


def _load_json(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(read_text(path))
    except json.JSONDecodeError as error:
        raise StaticReTestFailure(
            f"{path.relative_to(ROOT)} is not valid JSON: {error}"
        ) from error
    if not isinstance(document, dict):
        raise StaticReTestFailure(
            f"{path.relative_to(ROOT)} must contain a JSON object"
        )
    return document


def _close(actual: float, expected: float, tolerance: float, label: str) -> None:
    if not math.isclose(actual, expected, rel_tol=0.0, abs_tol=tolerance):
        raise StaticReTestFailure(
            f"{label} is {actual!r}; expected {expected!r} +/- {tolerance}"
        )


def _scenario_map(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    scenarios = document.get("scenarios")
    if not isinstance(scenarios, list):
        raise StaticReTestFailure("movement fixture scenarios must be a list")
    result: dict[str, dict[str, Any]] = {}
    for scenario in scenarios:
        if not isinstance(scenario, dict) or not isinstance(scenario.get("id"), str):
            raise StaticReTestFailure("movement fixture has an invalid scenario")
        scenario_id = scenario["id"]
        if scenario_id in result:
            raise StaticReTestFailure(f"duplicate movement scenario: {scenario_id}")
        result[scenario_id] = scenario
    return result


def _displacement(scenario: dict[str, Any]) -> tuple[float, float, float]:
    samples = scenario["samples"]
    first = samples[0]
    last = samples[-1]
    dx = float(last["x"]) - float(first["x"])
    dy = float(last["y"]) - float(first["y"])
    return dx, dy, math.hypot(dx, dy)


def _model_native_rng(
    seed: int,
    bound: int,
    count: int,
) -> tuple[list[int], int, int, list[int]]:
    words = [seed & RNG_MASK, 1]
    while len(words) < RNG_WORD_COUNT:
        words.append((words[-1] + words[-2]) & RNG_MASK)
    index_a = 0
    index_b = 31
    power_of_two = 2
    while power_of_two < bound:
        power_of_two <<= 1
    outputs: list[int] = []
    for _ in range(count):
        value = (words[index_b] + words[index_a]) & RNG_MASK
        words[index_a] = value
        index_a = (index_a + 1) % RNG_WORD_COUNT
        index_b = (index_b + 1) % RNG_WORD_COUNT
        outputs.append(((value >> 6) & (power_of_two - 1)) % bound)
    return outputs, index_a, index_b, words


def _validate_fixture_header(
    document: dict[str, Any],
    *,
    instance: str,
    ports: list[int],
) -> str:
    header = document.get("header")
    if not isinstance(header, dict):
        raise StaticReTestFailure(f"{instance} fixture has no header object")
    expected = {
        "instance": instance,
        "ports": ports,
        "audio_disabled": True,
        "fixture_is_machine_recorded": True,
        "worktree_dirty_at_capture_start": False,
        "game_binary_sha256": GAME_SHA256,
    }
    mismatches = [
        f"{key}={header.get(key)!r}"
        for key, value in expected.items()
        if header.get(key) != value
    ]
    if mismatches:
        raise StaticReTestFailure(
            f"{instance} fixture provenance mismatch: {', '.join(mismatches)}"
        )
    source_sha = header.get("source_commit_sha")
    tree_sha = header.get("source_tree_sha")
    if not isinstance(source_sha, str) or re.fullmatch(r"[0-9a-f]{40}", source_sha) is None:
        raise StaticReTestFailure(f"{instance} source commit is not a full SHA")
    if not isinstance(tree_sha, str) or re.fullmatch(r"[0-9a-f]{40}", tree_sha) is None:
        raise StaticReTestFailure(f"{instance} source tree is not a full SHA")
    if header.get("loader_sha256") != header.get("build_loader_sha256"):
        raise StaticReTestFailure(
            f"{instance} launcher loader did not match its Release build"
        )
    epsilon = header.get("epsilon")
    if not isinstance(epsilon, dict):
        raise StaticReTestFailure(f"{instance} fixture has no epsilon contract")
    _close(float(epsilon.get("position_absolute", -1)), 1e-4, 0.0, "position epsilon")
    _close(float(epsilon.get("scalar_absolute", -1)), 1e-6, 0.0, "scalar epsilon")
    if "32-bit floats" not in str(epsilon.get("justification", "")):
        raise StaticReTestFailure(f"{instance} epsilon has no float32 justification")
    cleanup = header.get("cleanup")
    if not isinstance(cleanup, list) or len(cleanup) != 1:
        raise StaticReTestFailure(f"{instance} fixture has no exact cleanup record")
    cleanup_entry = cleanup[0]
    if (
        not isinstance(cleanup_entry, dict)
        or cleanup_entry.get("instance") != instance
        or cleanup_entry.get("pathMatched") is not True
        or cleanup_entry.get("stopped") is not True
    ):
        raise StaticReTestFailure(f"{instance} cleanup did not stop a path-matched PID")
    return source_sha


def test_native_movement_integrators_and_collision_are_address_pinned() -> str:
    doc = read_text(DOC)
    _require_tokens(
        "native sim-core document",
        doc,
        (
            "PlayerControlBrain_Update` at `0x0052C910`",
            "`PlayerActor_Tick` at `0x00548B00`",
            "`actor+0x158/+0x15C`",
            "delta = actor[+0x218] * v_pre",
            "`0.1` velocity unit per tick",
            "`1.1875`",
            "`0.9f` at `0x00784970`",
            "damping is `0.95f`",
            "`0x00784E20`",
            "does not have a per-discipline base-speed table",
            "`Badguy_Tick` at `0x004835F0`",
            "`0.25 * base_speed * modifiers`",
            "`MoveStep` at `0x00525800`",
            "`movement_collision_test_circle_placement` is `0x00523C90`",
            "primary resolver at `0x00522CE0`",
            "iteration bound of 8 at `0x00807888`",
            "factory type `0x07E9`",
            "ticks at `0x00600220`",
            "`0.6 * actor+0x30`",
        ),
    )
    for constructor in (
        "0x00473E30",
        "0x004740C0",
        "0x00474470",
        "0x00474660",
        "0x00474E50",
        "0x004759A0",
        "0x004771B0",
        "0x00479150",
        "0x00479940",
        "0x0047E0F0",
        "0x0048A6B0",
        "0x0048ABB0",
        "0x0048B970",
    ):
        if constructor not in doc:
            raise StaticReTestFailure(
                f"enemy base-speed constructor is not pinned: {constructor}"
            )
    return "player/enemy integrators, collision, radii, and Knockback addresses are pinned"


def test_native_tick_graph_reconciles_simulation_and_service_cadences() -> str:
    doc = read_text(DOC)
    _require_tokens(
        "native tick graph",
        doc,
        (
            "App_Run 0x0040C690",
            "fixed-step scheduler 0x0040D3C0",
            "fixed tick 0x0040D1B0",
            "render pass 0x0040D230",
            "WinMM `timeGetTime`",
            "100 fixed ticks/s and 10 ms/tick",
            "at most 16.667 ms / 60 Hz",
            "ActorWorld_Tick",
            "in **insertion order**",
            "minimum 67 ms",
            "Bot mana reserve recovery | 250 ms",
            "`0x00820230`",
            "not a writable time-scale control",
        ),
    )
    source_contracts = (
        (
            "transport cadence source",
            read_text(TRANSPORT),
            (
                "kLocalTransportParticipantFrameIntervalMs = 50",
                "kLocalTransportWorldSnapshotIntervalMs = 200",
                "kLocalTransportRunWorldMotionIntervalMs = 67",
                "kLocalTransportLootSnapshotIntervalMs = 250",
                "kLocalTransportAnimatedLootSnapshotIntervalMs = 50",
                "kLocalTransportSpellEffectSnapshotIntervalMs = 16",
                "kLocalTransportWaveSummaryCheckpointIntervalMs = 400",
                "kParticipantProgressionReliableCheckpointIntervalMs = 5000",
            ),
        ),
        (
            "service loop cadence source",
            read_text(SERVICE_LOOP),
            ("kServiceTickIntervalMs = 16",),
        ),
        (
            "runtime tick cadence source",
            read_text(RUNTIME_TICK),
            ("kRuntimeTickIntervalMs = 50",),
        ),
        (
            "gameplay cadence source",
            read_text(GAMEPLAY_CONSTANTS),
            (
                "kWizardBotSceneBindingTickIntervalMs = 50",
                "kBotManaReserveRecoveryIntervalMs = 250",
            ),
        ),
        (
            "Lua AI cadence source",
            read_text(LUA_AI),
            (
                "kLuaEnemyAiMinimumThinkIntervalMs = 16",
                "kLuaEnemyAiMaximumThinkIntervalMs = 5000",
                "std::uint32_t interval_ms = 100",
            ),
        ),
        (
            "Bot Brain cadence source",
            read_text(BOT_BRAIN),
            (
                "think_interval_ms = 250",
                "approach_move_interval_ms = 1000",
                "kite_move_interval_ms = 250",
                "orbit_move_interval_ms = 500",
                "flee_move_interval_ms = 250",
                "policy_interval_ms = 100",
                "manager_interval_ms = 100",
            ),
        ),
    )
    for label, text, tokens in source_contracts:
        _require_tokens(label, text, tokens)
    return "100 Hz simulation order is separated from render, AI, mana, and transport clocks"


def test_movement_golden_provenance_and_schema_are_live_recorded() -> str:
    movement = _load_json(MOVEMENT_FIXTURE)
    if movement.get("schema_version") != 1:
        raise StaticReTestFailure("movement fixture schema version changed")
    source_sha = _validate_fixture_header(
        movement,
        instance="phr-move",
        ports=[52271, 52272],
    )
    header = movement["header"]
    if header.get("tick_interval_ms") != 10:
        raise StaticReTestFailure("movement fixture is not sampled at the 10 ms tick")
    if header.get("sample_phase") != "loader runtime.tick, pre-stock PlayerActor_Tick":
        raise StaticReTestFailure("movement fixture phase is not the pre-stock player boundary")
    if "Stock MoveStep/collision" not in str(header.get("capture_method", "")):
        raise StaticReTestFailure("movement capture method does not preserve stock collision")
    if movement.get("native_layout") != {
        "collision_radius": "actor+0x30",
        "movement_scalar": "actor+0x218",
        "position": ["actor+0x18", "actor+0x1C"],
        "velocity_accumulator": ["actor+0x158", "actor+0x15C"],
    }:
        raise StaticReTestFailure("movement fixture native layout changed")
    baseline = movement.get("native_baseline")
    if not isinstance(baseline, dict):
        raise StaticReTestFailure("movement fixture has no live baseline")
    expected_scalars = {
        "actor_move_speed_scale": 1.0,
        "actor_movement_speed_multiplier": 1.0,
        "progression_move_speed": 0.95,
        "global_movement_speed_scalar": 1.25,
        "computed_velocity_cap": 1.1875,
        "actor_move_step_scale": 1.0,
        "actor_collision_radius": 25.0,
        "input_acceleration_divisor": 10.0,
        "controlled_velocity_damping": 0.95,
        "uncontrolled_velocity_damping": 0.9,
    }
    for field, expected in expected_scalars.items():
        _close(float(baseline.get(field, -1000)), expected, 2e-6, field)
    return f"movement fixture is a clean live capture from {source_sha[:12]}"


def test_movement_golden_traces_pin_normalization_slide_stop_and_knockback() -> str:
    movement = _load_json(MOVEMENT_FIXTURE)
    scenarios = _scenario_map(movement)
    expected_counts = {
        "cardinal_east": (40, 120),
        "cardinal_west": (40, 120),
        "cardinal_south": (40, 120),
        "cardinal_north": (40, 120),
        "diagonal_southeast": (40, 120),
        "wall_0_degrees": (100, 180),
        "wall_30_degrees": (100, 180),
        "wall_60_degrees": (100, 180),
        "knockback_contact": (0, 123),
    }
    if set(scenarios) != set(expected_counts):
        raise StaticReTestFailure(
            f"movement scenarios changed: {sorted(scenarios)}"
        )
    for scenario_id, (active_ticks, total_ticks) in expected_counts.items():
        scenario = scenarios[scenario_id]
        samples = scenario.get("samples")
        if (
            scenario.get("active_ticks") != active_ticks
            or scenario.get("total_ticks") != total_ticks
            or not isinstance(samples, list)
            or len(samples) != total_ticks
        ):
            raise StaticReTestFailure(f"{scenario_id} tick envelope changed")
        if [sample.get("index") for sample in samples] != list(range(total_ticks)):
            raise StaticReTestFailure(f"{scenario_id} sample indices are not contiguous")
        native_ticks = [int(sample["native_tick"]) for sample in samples]
        if any(current != previous + 1 for previous, current in zip(native_ticks, native_ticks[1:])):
            raise StaticReTestFailure(f"{scenario_id} skipped a native tick")
        for previous, current in zip(samples, samples[1:]):
            dx = float(current["x"]) - float(previous["x"])
            dy = float(current["y"]) - float(previous["y"])
            _close(float(current["position_step_x"]), dx, 1e-9, f"{scenario_id} step x")
            _close(float(current["position_step_y"]), dy, 1e-9, f"{scenario_id} step y")
            _close(
                float(current["position_step"]),
                math.hypot(dx, dy),
                1e-9,
                f"{scenario_id} step length",
            )

    cardinal_contracts = {
        "cardinal_east": (0, 1),
        "cardinal_west": (0, -1),
        "cardinal_south": (1, 1),
        "cardinal_north": (1, -1),
    }
    cardinal_distances: list[float] = []
    for scenario_id, (axis, sign) in cardinal_contracts.items():
        dx, dy, distance = _displacement(scenarios[scenario_id])
        components = (dx, dy)
        if components[axis] * sign <= 39.0 or abs(components[1 - axis]) > 1e-4:
            raise StaticReTestFailure(f"{scenario_id} cardinal displacement changed")
        cardinal_distances.append(distance)
        moving = [
            sample
            for sample in scenarios[scenario_id]["samples"]
            if float(sample["position_step"]) > 1e-5
        ]
        if int(moving[-1]["index"]) not in (60, 61, 62):
            raise StaticReTestFailure(f"{scenario_id} no longer has the 0.9 coast tail")
    if max(cardinal_distances) - min(cardinal_distances) > 0.002:
        raise StaticReTestFailure("cardinal movement is no longer symmetric")
    _, _, diagonal_distance = _displacement(scenarios["diagonal_southeast"])
    _close(diagonal_distance, cardinal_distances[0], 0.002, "diagonal-normalized distance")

    lane = movement["capture_lane"]
    normal = (float(lane["boundary_normal_x"]), float(lane["boundary_normal_y"]))
    tangent = (float(lane["boundary_tangent_x"]), float(lane["boundary_tangent_y"]))
    normal_displacements: list[float] = []
    tangent_displacements: list[float] = []
    for angle in (0, 30, 60):
        dx, dy, _ = _displacement(scenarios[f"wall_{angle}_degrees"])
        normal_displacements.append(dx * normal[0] + dy * normal[1])
        tangent_displacements.append(dx * tangent[0] + dy * tangent[1])
    if max(normal_displacements) - min(normal_displacements) > 1e-4:
        raise StaticReTestFailure("wall angles no longer resolve to one contact plane")
    _close(tangent_displacements[0], 0.0, 1e-4, "normal wall tangent motion")
    if not (tangent_displacements[1] > 40.0 and tangent_displacements[2] > 80.0):
        raise StaticReTestFailure("angled wall approaches no longer retain slide motion")

    knockback = scenarios["knockback_contact"]
    nonzero_steps = [
        sample
        for sample in knockback["samples"]
        if float(sample["position_step"]) > 1e-5
    ]
    if len(nonzero_steps) != 2:
        raise StaticReTestFailure("Knockback golden must have exactly two movement steps")
    for sample in nonzero_steps:
        _close(float(sample["position_step_x"]), 10.0, 1e-6, "Knockback X step")
        _close(float(sample["position_step_y"]), 0.0, 1e-6, "Knockback Y step")
    return "cardinals, diagonal, release tail, wall contacts/slides, and 10-unit Knockback replay"


def test_native_rng_golden_replays_exact_retail_recurrence() -> str:
    rng = _load_json(RNG_FIXTURE)
    if rng.get("schema_version") != 1:
        raise StaticReTestFailure("RNG fixture schema version changed")
    source_sha = _validate_fixture_header(
        rng,
        instance="phr-rng",
        ports=[52273, 52274],
    )
    algorithm = rng.get("algorithm")
    if algorithm != {
        "family": "additive_lagged_fibonacci",
        "initial_indices": [0, 31],
        "integer_output": "((new_word >> 6) & (ceil_pow2(range)-1)) % range",
        "lags": [55, 24],
        "modulus": 1 << 30,
        "state_word_bits": 30,
        "state_word_count": 55,
    }:
        raise StaticReTestFailure(f"RNG algorithm contract changed: {algorithm!r}")
    sequences = rng.get("sequences")
    if not isinstance(sequences, list):
        raise StaticReTestFailure("RNG sequences must be a list")
    expected_cases = {
        (1, 16, 64),
        (0x01234567, 100, 96),
        (0x01234567, 1001, 96),
        (RNG_MASK, 999999, 96),
    }
    actual_cases = {
        (int(item["seed"]), int(item["range"]), int(item["count"]))
        for item in sequences
    }
    if actual_cases != expected_cases:
        raise StaticReTestFailure(f"RNG seed/bound census changed: {actual_cases!r}")
    for sequence in sequences:
        seed = int(sequence["seed"])
        bound = int(sequence["range"])
        count = int(sequence["count"])
        outputs, index_a, index_b, words = _model_native_rng(seed, bound, count)
        if sequence.get("outputs") != outputs:
            raise StaticReTestFailure(f"native RNG outputs diverged for seed {seed}")
        if sequence.get("final_index_a") != index_a or sequence.get("final_index_b") != index_b:
            raise StaticReTestFailure(f"native RNG indices diverged for seed {seed}")
        if sequence.get("final_state_words") != words:
            raise StaticReTestFailure(f"native RNG state diverged for seed {seed}")
        if sequence.get("stream") != "native-private-stack-state":
            raise StaticReTestFailure(f"RNG sequence {seed} did not use isolated retail state")
    observed = rng.get("observed_run_seed")
    if not isinstance(observed, dict):
        raise StaticReTestFailure("RNG fixture has no observed run seed")
    if observed.get("selected_in_hub") != 0x01234567 or observed.get("get_seed_in_hub") != 0x01234567:
        raise StaticReTestFailure("published run seed was not observed in the hub")
    active = observed.get("active_state_after_world_generation")
    if (
        not isinstance(active, dict)
        or active.get("published_seed") != 0x01234567
        or active.get("divisor") != 100000
        or not isinstance(active.get("state_words"), list)
        or len(active["state_words"]) != RNG_WORD_COUNT
        or not 0 <= int(active.get("index_a", -1)) < RNG_WORD_COUNT
        or not 0 <= int(active.get("index_b", -1)) < RNG_WORD_COUNT
    ):
        raise StaticReTestFailure("post-generation active RNG observation is incomplete")
    return f"four retail RNG sequences and post-generation state replay from {source_sha[:12]}"


def test_native_rng_stream_ownership_and_callsite_census_are_pinned() -> str:
    doc = read_text(DOC)
    _require_tokens(
        "native RNG document",
        doc,
        (
            "55-word additive",
            "lags 55 and 24",
            "`0xE8`-byte object",
            "`0x00401110`",
            "`0x00401120`",
            "`0x00401170`",
            "`0x00401310`",
            "`0x00818B08`",
            "`0x00818B10`",
            "Retail startup at `0x0040CEB2`",
            "Boneyard generation at `0x006388B0`",
            "`0x006388FE`",
            "`0x0063895B`",
            "Level-up offers | `0x0067CB70`",
            "Enemy/item drops | `0x0047C070`",
            "Demon Skull SpitFire action | `0x00449880`",
            "Magic Missile handler `0x0053CFE0`",
            "Storm Cloud `0x006021A0`",
            "942 calls/references",
            "1,511 float-primitive references",
            "2,601 active-pointer references",
            "No universal damage-variance roll",
        ),
    )
    return "RNG recurrence, seeds, shared/private streams, and gameplay call-site families are pinned"


def test_native_sim_recorder_seam_is_bounded_isolated_and_registered() -> str:
    recorder = read_text(RECORDER)
    seam = read_text(RNG_SEAM)
    bindings = read_text(DEBUG_BINDINGS)
    includes = read_text(DEBUG_INCLUDES)
    api = read_text(LUA_API)
    project = read_text(PROJECT)
    filters = read_text(PROJECT_FILTERS)
    roadmap = read_text(ROADMAP)
    _require_tokens(
        "native RNG recorder seam",
        seam,
        (
            "kDebugNativeRngStateSize = 0xE8",
            "kDebugNativeRngMaximumSamples = 256",
            "seed must be at most 0x3fffffff",
            "range must be positive",
            "std::array<std::uint8_t, kDebugNativeRngStateSize>",
            "ResolveGameAddressOrZero(kNativeRngInitialize)",
            "ResolveGameAddressOrZero(kNativeRngInteger)",
            '"native-private-stack-state"',
            '"final_index_a"',
            '"final_index_b"',
            '"final_state_words"',
        ),
    )
    if seam.count("0x00818B08") != 1 or "read_u32(0x00818B08" in seam:
        raise StaticReTestFailure("isolated RNG seam reached beyond its documentary active-pointer mention")
    _require_tokens(
        "native sim recorder",
        recorder,
        (
            'MOVEMENT_INSTANCE = "phr-move"',
            'RNG_INSTANCE = "phr-rng"',
            "MOVEMENT_PORTS = (52271, 52272)",
            "RNG_PORTS = (52273, 52274)",
            'environment["SDMOD_DISABLE_AUDIO"] = "1"',
            '"refusing final live goldens from a dirty worktree"',
            '"staged launcher loader does not match the Release build"',
            "stop_owned_process_ids",
            "model_native_rng(seed, bound, count)",
            '"fixture_is_machine_recorded": True',
        ),
    )
    registration_contracts = (
        (bindings, 'RegisterFunction(state, &LuaDebugSampleNativeRng, "sample_native_rng")'),
        (includes, '#include "functions_native_rng.inl"'),
        (api, "function sd_debug.sample_native_rng(seed, range, count) end"),
        (project, 'Include="src\\lua_engine_bindings_debug\\functions_native_rng.inl"'),
        (filters, 'Include="src\\lua_engine_bindings_debug\\functions_native_rng.inl"'),
    )
    for text, token in registration_contracts:
        if token not in text:
            raise StaticReTestFailure(f"native RNG recorder registration is missing: {token}")
    _require_tokens(
        "browser rebuild roadmap G1 closure",
        roadmap,
        (
            "docs/reverse-engineering/native-movement-and-tick.md",
            "tests/fixtures/webgame/movement-goldens.json",
            "tests/fixtures/webgame/rng-goldens.json",
            "tests/re/static_re_native_sim_core_contracts.py",
            "CLOSED 2026-08-04",
        ),
    )
    return "recorder is clean-SHA gated, isolated, bounded, registered, and roadmap-closing"
