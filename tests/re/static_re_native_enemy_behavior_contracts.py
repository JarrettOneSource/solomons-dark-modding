"""Contracts for the native enemy behavior interpreter and live goldens."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

from static_re_contract_support import (
    ROOT,
    StaticReTestFailure,
    assert_recorded_hash_matches_file,
    read_text,
)


BEHAVIOR_DOC = ROOT / "docs/reverse-engineering/native-enemy-behavior.md"
BEHAVIOR_FIXTURE = (
    ROOT / "tests/fixtures/webgame/enemy-behavior-goldens.json"
)

FIELD_OFFSETS = (
    "+0x4C", "+0x14", "+0x50", "+0x58", "+0x5C", "+0x6C", "+0x74",
    "+0x78", "+0x7C", "+0xBC", "+0x80", "+0x81", "+0x82", "+0x83",
    "+0x30", "+0xC1", "+0xC4", "+0x84", "+0x88", "+0x8C", "+0xB8",
    "+0xB9", "+0xCC", "+0xCD", "+0xCE", "+0xD0", "+0xCF", "+0xD1",
    "+0x54", "+0x70", "+0xD4", "+0x60", "+0x94", "+0x95", "+0x96",
    "+0x97", "+0x64", "+0x68", "+0x90", "+0x98", "+0xA8", "+0xC0",
)
FIELD_VERDICTS = {"runtime", "definition-only", "reward-only", "not-yet-reversed"}
DECLARED_UNKNOWN_FIELDS = {13, 40, 41}

SKELETON_TRANSITIONS = {
    ("skeleton", "spawn", "actor registered and alive", "search"),
    ("skeleton", "search", "valid target acquired", "approach"),
    ("skeleton", "approach", "target lost or bucket invalid", "search"),
    ("skeleton", "approach", "target in weapon reach and scheduler ready", "attack_windup"),
    ("skeleton", "attack_windup", "first native action marker fires", "attack_active"),
    ("skeleton", "attack_active", "marker callback returns and action remains queued", "attack_recovery"),
    ("skeleton", "attack_recovery", "later native action marker fires before completion", "attack_active"),
    ("skeleton", "attack_recovery", "action progress exceeds end frame", "approach"),
    ("skeleton_archer", "spawn", "actor registered and alive", "search"),
    ("skeleton_archer", "search", "valid target acquired", "range_control"),
    ("skeleton_archer", "range_control", "target lost or bucket invalid", "search"),
    ("skeleton_archer", "range_control", "range/cooldown predicate accepts", "attack_windup"),
    ("skeleton_archer", "attack_windup", "progress crosses frame 13", "attack_active"),
    ("skeleton_archer", "attack_active", "Arrow objects registered", "attack_recovery"),
    ("skeleton_archer", "attack_recovery", "progress exceeds frame 16", "range_control"),
    ("skeleton_mage", "spawn", "actor registered and alive", "search"),
    ("skeleton_mage", "search", "valid target acquired", "range_control"),
    ("skeleton_mage", "range_control", "target lost or bucket invalid", "search"),
    ("skeleton_mage", "range_control", "cast predicate accepts", "attack_windup"),
    ("skeleton_mage", "attack_windup", "progress crosses selected frame 25 or 31", "attack_active"),
    ("skeleton_mage", "attack_active", "element callback/shield effect dispatched", "attack_recovery"),
    ("skeleton_mage", "attack_recovery", "a later configured action marker fires", "attack_active"),
    ("skeleton_mage", "attack_recovery", "progress exceeds paired frame 41 or 47", "range_control"),
    ("skeleton_mage", "range_control", "shield interval expires and a configured recipient is valid", "shield_special"),
    ("skeleton_mage", "shield_special", "shield action completes", "range_control"),
    ("skeleton_family", "any_alive", "HP/death predicate fires", "death"),
}


def _unique_section(text: str, begin: str, end: str, claim: str) -> str:
    begin_count = text.count(begin)
    end_count = text.count(end)
    if begin_count != 1 or end_count != 1:
        raise StaticReTestFailure(
            f"{claim} is ambiguous: expected one begin/end marker, got "
            f"{begin_count}/{end_count}"
        )
    start = text.index(begin) + len(begin)
    stop = text.index(end)
    if start >= stop:
        raise StaticReTestFailure(f"{claim} markers do not enclose content")
    return text[start:stop]


def _table_cells(line: str) -> list[str]:
    return [cell.strip().strip("`") for cell in line.strip().strip("|").split("|")]


def test_monster_recipe_field_semantics_are_complete() -> str:
    text = read_text(BEHAVIOR_DOC)
    section = _unique_section(
        text,
        "<!-- MONSTER_RECIPE_FIELD_SEMANTICS_BEGIN -->",
        "<!-- MONSTER_RECIPE_FIELD_SEMANTICS_END -->",
        "the 42-field MonsterRecipe semantic table",
    )
    rows = []
    for line in section.splitlines():
        cells = _table_cells(line)
        if cells and re.fullmatch(r"\d+", cells[0]):
            rows.append(cells)
    if len(rows) != 42:
        raise StaticReTestFailure(
            "the MonsterRecipe interpreter no longer assigns semantics to "
            f"all 42 serialized fields: found {len(rows)} rows"
        )
    orders = [int(row[0]) for row in rows]
    if orders != list(range(1, 43)):
        raise StaticReTestFailure(
            "the MonsterRecipe semantic table no longer follows the exact "
            f"serializer order 1..42: {orders}"
        )
    offsets = tuple(row[1] for row in rows)
    if offsets != FIELD_OFFSETS:
        raise StaticReTestFailure(
            "the MonsterRecipe semantic table no longer matches the recovered "
            "42-field offset ABI"
        )
    short_rows = [int(row[0]) for row in rows if len(row) != 6]
    if short_rows:
        raise StaticReTestFailure(
            "MonsterRecipe rows no longer carry field, verdict, runtime meaning, "
            f"and native evidence: {short_rows}"
        )
    bad_verdicts = {
        int(row[0]): row[3] for row in rows if row[3] not in FIELD_VERDICTS
    }
    if bad_verdicts:
        raise StaticReTestFailure(
            "MonsterRecipe fields contain silent or non-contractual verdicts: "
            f"{bad_verdicts}"
        )
    empty_claims = [
        int(row[0]) for row in rows if not row[2] or not row[4] or not row[5]
    ]
    if empty_claims:
        raise StaticReTestFailure(
            "MonsterRecipe fields lost a name, runtime consequence, or native "
            f"evidence: {empty_claims}"
        )
    unknowns = {int(row[0]) for row in rows if row[3] == "not-yet-reversed"}
    if unknowns != DECLARED_UNKNOWN_FIELDS:
        raise StaticReTestFailure(
            "the declared MonsterRecipe unknown set changed without an explicit "
            f"semantic verdict: expected {sorted(DECLARED_UNKNOWN_FIELDS)}, "
            f"got {sorted(unknowns)}"
        )
    witnesses = {int(row[0]): row[4] for row in rows}
    for order, token in (
        (4, "actor `+0x170/+0x174`"),
        (22, "refresh cadence"),
        (30, "live `+0x17C`"),
        (32, "secondary hit"),
        (42, "range-control decisions"),
    ):
        if token not in witnesses[order]:
            raise StaticReTestFailure(
                f"MonsterRecipe field {order} no longer names its gameplay "
                f"consequence ({token})"
            )
    return "all 42 MonsterRecipe fields carry exact offsets and explicit runtime verdicts"


def test_skeleton_behavior_transition_set_is_pinned() -> str:
    text = read_text(BEHAVIOR_DOC)
    section = _unique_section(
        text,
        "<!-- SKELETON_STATE_TRANSITIONS_BEGIN -->",
        "<!-- SKELETON_STATE_TRANSITIONS_END -->",
        "the skeleton-family transition relation",
    )
    rows = []
    for line in section.splitlines():
        cells = _table_cells(line)
        if len(cells) == 5 and cells[0] in {
            "skeleton", "skeleton_archer", "skeleton_mage", "skeleton_family"
        }:
            rows.append(cells)
    if len(rows) != len(SKELETON_TRANSITIONS):
        raise StaticReTestFailure(
            "the skeleton-family state machine no longer exposes every expected "
            f"transition: found {len(rows)} of {len(SKELETON_TRANSITIONS)}"
        )
    transitions = {(row[0], row[1], row[2], row[3]) for row in rows}
    if transitions != SKELETON_TRANSITIONS:
        missing = sorted(SKELETON_TRANSITIONS - transitions)
        extra = sorted(transitions - SKELETON_TRANSITIONS)
        raise StaticReTestFailure(
            "the skeleton-family transition relation changed: "
            f"missing={missing}, extra={extra}"
        )
    empty_owners = [row[:4] for row in rows if not row[4]]
    if empty_owners:
        raise StaticReTestFailure(
            "skeleton-family transitions lost their native owner: "
            f"{empty_owners}"
        )
    required_addresses = {
        "0x00484B90", "0x00477580", "0x00485200", "0x00477B90",
        "0x00490860", "0x0047FDE0", "0x004819D0",
    }
    missing_addresses = sorted(address for address in required_addresses if address not in section)
    if missing_addresses:
        raise StaticReTestFailure(
            "the skeleton-family transition relation lost native executable "
            f"owners: {missing_addresses}"
        )
    return "skeleton, Archer, and Mage transition edges and native owners are pinned"


EXPECTED_TIMING_ROWS = {
    ("Skeleton claw", "0x0E", "0.125", "4", "7", "32", "57", "25"),
    ("Skeleton weapon", "0x0F", "0.25", "9", "24", "36", "97", "61"),
    ("Skeleton pike", "0x10", "0.125", "2", "12", "16", "97", "81"),
    (
        "Skeleton Archer", "0x11", "0.0843750015", "13", "16",
        "155", "190", "35",
    ),
    (
        "Skeleton Mage", "0x12", "0.253125012 * (1 + roll)",
        "25 or 31", "41 or 47", "variable", "variable", "variable",
    ),
}

EXPECTED_FIXTURE_TIMING = {
    "fixed_tick_ms": 10,
    "skeleton_claw": {
        "action_id": 14,
        "rate": 0.125,
        "active_frame": 4.0,
        "end_frame": 7.0,
    },
    "skeleton_weapon": {
        "action_id": 15,
        "rate": 0.25,
        "active_frame": 9.0,
        "end_frame": 24.0,
    },
    "skeleton_pike": {
        "action_id": 16,
        "rate": 0.125,
        "active_frame": 2.0,
        "end_frame": 12.0,
    },
    "skeleton_archer": {
        "action_id": 17,
        "rate": 0.0843750015,
        "active_frame": 13.0,
        "end_frame": 16.0,
    },
    "skeleton_mage": {
        "action_id": 18,
        "rate_base": 0.253125012,
        "active_frames": [25.0, 31.0],
        "end_frames": [41.0, 47.0],
    },
}

EXPECTED_TRACES = {
    "skeleton__stationary_player": (0x3E9, "stationary_player", 1000),
    "skeleton__moving_player": (0x3E9, "moving_player", 1000),
    "skeleton_archer__stationary_player": (0x3EA, "stationary_player", 1400),
    "skeleton_archer__moving_player": (0x3EA, "moving_player", 1400),
    "skeleton_mage__stationary_player": (0x3EB, "stationary_player", 1600),
    "skeleton_mage__moving_player": (0x3EB, "moving_player", 1600),
    "dire_faculty__stationary_player": (0x3F2, "stationary_player", 4000),
    "dire_faculty__moving_player": (0x3F2, "moving_player", 4000),
}


def _read_behavior_fixture() -> dict[str, object]:
    try:
        document = json.loads(read_text(BEHAVIOR_FIXTURE))
    except json.JSONDecodeError as error:
        raise StaticReTestFailure(
            f"the enemy behavior golden is not valid JSON: {error}"
        ) from error
    if not isinstance(document, dict):
        raise StaticReTestFailure("the enemy behavior golden root is not an object")
    return document


def test_enemy_behavior_goldens_pin_live_provenance_and_attack_timing() -> str:
    doc = read_text(BEHAVIOR_DOC)
    hash_matches = re.findall(
        r"Fixture SHA-256:\s*\n`([0-9a-f]{64})`\.",
        doc,
    )
    if len(hash_matches) != 1:
        raise StaticReTestFailure(
            "the committed enemy behavior fixture hash is absent or ambiguous: "
            f"found {len(hash_matches)} declarations"
        )
    assert_recorded_hash_matches_file(
        hash_matches[0],
        BEHAVIOR_FIXTURE,
        "the documented enemy behavior golden",
    )

    timing_section = _unique_section(
        doc,
        "<!-- ENEMY_ATTACK_TIMING_BEGIN -->",
        "<!-- ENEMY_ATTACK_TIMING_END -->",
        "the enemy attack timing table",
    )
    timing_row_list: list[tuple[str, ...]] = []
    timing_names = {row[0] for row in EXPECTED_TIMING_ROWS}
    for line in timing_section.splitlines():
        cells = _table_cells(line)
        if len(cells) == 8 and cells[0] in timing_names:
            timing_row_list.append(tuple(cell.replace("`", "") for cell in cells))
    timing_rows = set(timing_row_list)
    if len(timing_row_list) != len(timing_rows):
        raise StaticReTestFailure(
            "the enemy attack timing table contains ambiguous duplicate rows"
        )
    if timing_rows != EXPECTED_TIMING_ROWS:
        raise StaticReTestFailure(
            "the enemy attack timing constants changed: "
            f"missing={sorted(EXPECTED_TIMING_ROWS - timing_rows)}, "
            f"extra={sorted(timing_rows - EXPECTED_TIMING_ROWS)}"
        )

    fixture = _read_behavior_fixture()
    header = fixture.get("header")
    if not isinstance(header, dict):
        raise StaticReTestFailure(
            "the enemy behavior golden lost its live provenance header"
        )
    expected_provenance = {
        "format": "solomon-dark-native-golden-v1",
        "capture": "enemy_behavior_per_tick",
        "fixture_is_machine_recorded": True,
        "game_binary_sha256": (
            "03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3"
        ),
        "fixed_tick_ms": 10,
        "run_seed": 0x013579BD,
        "audio_disabled": True,
        "headless": False,
    }
    wrong_provenance = {
        key: header.get(key)
        for key, value in expected_provenance.items()
        if header.get(key) != value
    }
    if wrong_provenance:
        raise StaticReTestFailure(
            "the enemy behavior golden no longer identifies the accepted live "
            f"retail capture: {wrong_provenance}"
        )
    seed_source = header.get("run_seed_source")
    if not isinstance(seed_source, str) or "App+0x28 * 0xEF3" not in seed_source:
        raise StaticReTestFailure(
            "enemy behavior provenance again treats the requested shared seed "
            "as the complete construction seed"
        )
    cleanup = header.get("cleanup")
    if not isinstance(cleanup, list) or not cleanup:
        raise StaticReTestFailure(
            "the live enemy behavior capture has no owned-process cleanup witness"
        )
    if any(
        not isinstance(row, dict)
        or row.get("role") != "mon-behavior"
        or row.get("pathMatched") is not True
        or row.get("stopped") is not True
        for row in cleanup
    ):
        raise StaticReTestFailure(
            "the live enemy behavior capture did not stop its exact owned game process"
        )

    if fixture.get("attack_timing_constants") != EXPECTED_FIXTURE_TIMING:
        raise StaticReTestFailure(
            "the machine-readable enemy attack timing constants changed"
        )
    traces = fixture.get("traces")
    if not isinstance(traces, list) or len(traces) != len(EXPECTED_TRACES):
        raise StaticReTestFailure(
            "the enemy behavior golden no longer contains the eight required "
            "stationary/moving traces"
        )
    trace_ids = [
        trace.get("id") if isinstance(trace, dict) else None
        for trace in traces
    ]
    if len(set(trace_ids)) != len(trace_ids):
        raise StaticReTestFailure(
            "the enemy behavior golden contains ambiguous duplicate trace IDs"
        )
    if set(trace_ids) != set(EXPECTED_TRACES):
        raise StaticReTestFailure(
            "the enemy behavior golden lost a required skeleton/projectile/special "
            f"witness: {trace_ids}"
        )

    trace_by_id = {trace["id"]: trace for trace in traces}
    required_sample_fields = {
        "tick", "native_tick", "position", "facing", "state", "action_count",
        "action_id", "action_progress", "target_position",
        "target_participant_id", "target_actor_address", "native_actor_slot_u8",
        "native_archer_ready_u8", "native_attack_range", "hp",
    }
    required_event_fields = {
        "tick", "native_tick", "kind", "action_id", "amount",
        "target_participant_id", "projectile_type", "position", "hp_before",
        "hp_after", "source_actor_address", "source_native_type_id", "source",
    }
    event_sources = {
        "action_start": "native_action_queue",
        "action_end": "native_action_queue",
        "attack_active": "derived_action_progress_marker",
        "projectile_spawn": "native_world_registration",
        "damage": "native_player_damage_observation",
    }
    for trace_id, (type_id, target_mode, tick_count) in EXPECTED_TRACES.items():
        trace = trace_by_id[trace_id]
        if (
            trace.get("native_type_id") != type_id
            or trace.get("target_mode") != target_mode
            or trace.get("tick_count") != tick_count
        ):
            raise StaticReTestFailure(
                f"enemy behavior trace {trace_id} lost its type/mode/tick identity"
            )
        samples = trace.get("samples")
        if not isinstance(samples, list) or len(samples) != tick_count:
            raise StaticReTestFailure(
                f"enemy behavior trace {trace_id} no longer records every native tick"
            )
        if any(not isinstance(sample, dict) for sample in samples):
            raise StaticReTestFailure(
                f"enemy behavior trace {trace_id} contains a non-object tick sample"
            )
        if [sample.get("tick") for sample in samples] != list(range(tick_count)):
            raise StaticReTestFailure(
                f"enemy behavior trace {trace_id} has missing or reordered tick stamps"
            )
        first_native_tick = samples[0].get("native_tick")
        if not isinstance(first_native_tick, int) or [
            sample.get("native_tick") for sample in samples
        ] != list(range(first_native_tick, first_native_tick + tick_count)):
            raise StaticReTestFailure(
                f"enemy behavior trace {trace_id} is not contiguous in native time"
            )
        missing_sample_fields = [
            sample.get("tick")
            for sample in samples
            if not required_sample_fields.issubset(sample)
        ]
        if missing_sample_fields:
            raise StaticReTestFailure(
                f"enemy behavior trace {trace_id} lost per-tick position/state/facing "
                f"fields at ticks {missing_sample_fields[:8]}"
            )
        events = trace.get("events")
        if not isinstance(events, list) or not events:
            raise StaticReTestFailure(
                f"enemy behavior trace {trace_id} contains no attack observations"
            )
        if any(not isinstance(event, dict) for event in events):
            raise StaticReTestFailure(
                f"enemy behavior trace {trace_id} contains a non-object attack event"
            )
        malformed_events = [
            event.get("tick")
            for event in events
            if not required_event_fields.issubset(event)
        ]
        if malformed_events:
            raise StaticReTestFailure(
                f"enemy behavior trace {trace_id} lost attack/damage event fields at "
                f"ticks {malformed_events[:8]}"
            )
        wrong_sources = [
            (event.get("kind"), event.get("source"))
            for event in events
            if event_sources.get(event.get("kind")) != event.get("source")
        ]
        if wrong_sources:
            raise StaticReTestFailure(
                f"enemy behavior trace {trace_id} no longer distinguishes native "
                f"events from derived timing markers: {wrong_sources[:8]}"
            )
        damage = [event for event in events if event.get("kind") == "damage"]
        if not damage or any(event.get("amount", 0) <= 0 for event in damage):
            raise StaticReTestFailure(
                f"enemy behavior trace {trace_id} has no positive native damage witness"
            )
        displacement = trace.get("target_displacement")
        if not isinstance(displacement, (int, float)):
            raise StaticReTestFailure(
                f"enemy behavior trace {trace_id} lost target displacement"
            )
        if target_mode == "stationary_player" and displacement > 0.01:
            raise StaticReTestFailure(
                f"stationary enemy behavior target moved in {trace_id}: {displacement}"
            )
        if target_mode == "moving_player" and displacement < 20.0:
            raise StaticReTestFailure(
                f"moving enemy behavior target did not move in {trace_id}: {displacement}"
            )
        spawn = trace.get("spawn")
        if not isinstance(spawn, dict):
            raise StaticReTestFailure(
                f"enemy behavior trace {trace_id} lost its stock-spawner result"
            )
        actor_seed = spawn.get("actor_rng_seed")
        if not isinstance(actor_seed, int) or actor_seed == 0:
            raise StaticReTestFailure(
                f"enemy behavior trace {trace_id} lost its construction-derived actor seed"
            )
        if "App+0x28 * 0xEF3" not in str(spawn.get("actor_rng_seed_source", "")):
            raise StaticReTestFailure(
                f"enemy behavior trace {trace_id} lost the actor-seed lifecycle source"
            )

    expected_damage_types = {
        "skeleton__stationary_player": ({0x3E9}, {3.0}),
        "skeleton__moving_player": ({0x3E9}, {3.0}),
        "skeleton_archer__stationary_player": ({0x7DA}, {4.0}),
        "skeleton_archer__moving_player": ({0x7DA}, {4.0}),
        "skeleton_mage__stationary_player": ({0x7EB}, {24.0}),
        "skeleton_mage__moving_player": ({0x7EB}, {24.0}),
    }
    for trace_id, (source_types, amounts) in expected_damage_types.items():
        damage = [
            event for event in trace_by_id[trace_id]["events"]
            if event["kind"] == "damage"
        ]
        if {event["source_native_type_id"] for event in damage} != source_types:
            raise StaticReTestFailure(
                f"enemy behavior trace {trace_id} changed its damage source type"
            )
        if {event["amount"] for event in damage} != amounts:
            raise StaticReTestFailure(
                f"enemy behavior trace {trace_id} changed its damage amount"
            )

    skeleton_events = trace_by_id["skeleton__stationary_player"]["events"]
    first_end = next(
        (index for index, event in enumerate(skeleton_events) if event["kind"] == "action_end"),
        None,
    )
    if first_end is None:
        raise StaticReTestFailure(
            "the stationary skeleton trace contains no complete claw action witness"
        )
    first_action = skeleton_events[: first_end + 1]
    start_tick = first_action[0]["tick"]
    relative_witness = [
        (event["kind"], event["tick"] - start_tick, event["amount"])
        for event in first_action
    ]
    expected_witness = [
        ("action_start", 0, 0.0),
        ("attack_active", 32, 0.0),
        ("damage", 32, 3.0),
        ("damage", 33, 3.0),
        ("damage", 60, 3.0),
        ("action_end", 61, 0.0),
    ]
    if relative_witness != expected_witness:
        raise StaticReTestFailure(
            "the live skeleton claw windup/active/recovery timing witness changed: "
            f"{relative_witness}"
        )

    for trace_id in (
        "dire_faculty__stationary_player",
        "dire_faculty__moving_player",
    ):
        trace = trace_by_id[trace_id]
        if trace.get("special_setup") != {"write": "true", "observed": "-1"}:
            raise StaticReTestFailure(
                f"Faculty trace {trace_id} no longer declares its bounded special setup"
            )
        damage = [
            event for event in trace["events"] if event["kind"] == "damage"
        ]
        source_types = {event["source_native_type_id"] for event in damage}
        if not {0x800, 0x801}.issubset(source_types):
            raise StaticReTestFailure(
                f"Faculty trace {trace_id} lost SkullMissile or RainOfBones damage"
            )
        rain = [event for event in damage if event["source_native_type_id"] == 0x801]
        if len(rain) != 1 or not math.isclose(
            rain[0]["hp_after"] / rain[0]["hp_before"],
            0.01,
            rel_tol=0.0,
            abs_tol=1e-7,
        ):
            raise StaticReTestFailure(
                f"Faculty trace {trace_id} no longer proves Acid Pain leaves one-percent HP"
            )

    return (
        "eight live enemy traces pin provenance, construction seeds, movement, "
        "attack constants, damage sources, and Faculty special output"
    )
