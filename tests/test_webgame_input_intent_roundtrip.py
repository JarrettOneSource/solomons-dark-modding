from __future__ import annotations

import hashlib
import json
import math
import re
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "webgame-contracts" / "intent-schema.json"
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "webgame" / "input-goldens.json"

SCENARIOS = {
    "click_open_ground_native_absence",
    "click_wall_native_absence",
    "tap_cast",
    "earth_charge_120ms",
    "earth_charge_600ms",
    "earth_charge_1500ms",
    "frost_channel_start_stop",
    "hud_click_swallowed",
}


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _load() -> tuple[dict[str, Any], dict[str, Any]]:
    return (
        json.loads(SCHEMA_PATH.read_text(encoding="utf-8")),
        json.loads(FIXTURE_PATH.read_text(encoding="utf-8")),
    )


def _require_world_point(value: Any) -> None:
    assert isinstance(value, dict)
    assert set(value) == {"x", "y"}
    assert all(
        isinstance(value[axis], (int, float)) and math.isfinite(value[axis])
        for axis in ("x", "y")
    )


def _validate_intent(intent: dict[str, Any]) -> None:
    kind = intent.get("kind")
    if kind == "move":
        assert set(intent) == {"kind", "phase", "move"}
        assert intent["phase"] in {"start", "update", "stop"}
        move = intent["move"]
        if move.get("type") == "world_target":
            assert set(move) == {"type", "point"}
            _require_world_point(move["point"])
        else:
            assert move.get("type") == "unit_vector"
            assert set(move) == {"type", "vector"}
            _require_world_point(move["vector"])
            magnitude = math.hypot(move["vector"]["x"], move["vector"]["y"])
            assert math.isclose(magnitude, 1.0, rel_tol=0.0, abs_tol=1e-6)
    elif kind == "aim":
        assert set(intent) == {"kind", "point"}
        _require_world_point(intent["point"])
    elif kind == "cast":
        assert set(intent) == {"kind", "slot", "phase"}
        assert intent["slot"] in {"primary", "secondary"}
        assert intent["phase"] in {"press", "hold", "release"}
    elif kind == "interact":
        assert set(intent) == {"kind", "target", "phase"}
        assert isinstance(intent["target"], str) and intent["target"]
        assert intent["phase"] in {"press", "release"}
    else:
        assert kind == "menu_nav"
        assert set(intent) == {"kind", "command", "phase"}
        assert intent["command"] in {
            "up",
            "down",
            "left",
            "right",
            "confirm",
            "back",
            "next",
            "previous",
        }
        assert intent["phase"] in {"press", "release"}


def _flatten_intents(capture: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        intent
        for record in capture["intent_timeline"]
        for intent in record["intents"]
    ]


def _assert_every_live_native_trace_round_trips_losslessly() -> None:
    _, fixture = _load()
    assert fixture["format"] == "sd-webgame-input-goldens-v1"
    assert fixture["generated_by"] == "tools/capture_native_input_goldens.py"
    assert {capture["header"]["scenario"] for capture in fixture["captures"]} == SCENARIOS

    for capture in fixture["captures"]:
        header = capture["header"]
        raw = capture["raw_timeline"]
        encoding = capture["intent_timeline"]
        reconstructed = [record["native_source"]["raw"] for record in encoding]

        assert len(raw) == len(encoding) > 0
        assert reconstructed == raw
        assert _sha256(raw) == header["round_trip"]["raw_sha256"]
        assert _sha256(reconstructed) == header["round_trip"]["reconstructed_sha256"]
        assert header["round_trip"]["exact_equal"] is True
        assert re.fullmatch(r"[0-9a-f]{40}", header["source_sha"])
        assert re.fullmatch(r"[0-9a-f]{64}", header["executable_sha256"])
        assert header["instance"] in {"inp-earth", "inp-water"}
        assert "exact-PID/path" in header["capture_method"]
        assert "SendMessageTimeoutW" in header["capture_method"]

        for index, (source, record) in enumerate(zip(raw, encoding, strict=True)):
            assert record["schema_version"] == "1.0.0"
            assert record["sequence"] == index
            assert record["tick"] == source["simulation_tick"]
            assert record["native_source"]["kind"] == source["kind"]
            for intent in record["intents"]:
                _validate_intent(intent)


def _assert_intent_schema_pins_the_device_independent_action_union() -> None:
    schema, _ = _load()
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$ref"] == "#/$defs/intent"
    definitions = schema["$defs"]
    assert len(definitions["intent"]["oneOf"]) == 5

    move_variants = definitions["moveIntent"]["properties"]["move"]["oneOf"]
    assert {
        variant["properties"]["type"]["const"] for variant in move_variants
    } == {"world_target", "unit_vector"}
    assert definitions["aimIntent"]["properties"]["point"]["$ref"] == (
        "#/$defs/worldPoint"
    )
    assert definitions["castIntent"]["properties"]["phase"]["enum"] == [
        "press",
        "hold",
        "release",
    ]
    assert definitions["nativeEncodingRecord"]["properties"]["intents"][
        "items"
    ]["$ref"] == "#/$defs/intent"

    _validate_intent(
        {
            "kind": "move",
            "phase": "update",
            "move": {"type": "world_target", "point": {"x": 1.0, "y": 2.0}},
        }
    )
    _validate_intent(
        {
            "kind": "move",
            "phase": "update",
            "move": {"type": "unit_vector", "vector": {"x": 0.0, "y": 1.0}},
        }
    )


def _assert_live_goldens_pin_native_mouse_semantics() -> None:
    _, fixture = _load()
    captures = {
        capture["header"]["scenario"]: capture for capture in fixture["captures"]
    }
    for capture in captures.values():
        assert {event["kind"] for event in capture["raw_timeline"]} == {
            "win32",
            "input_sample",
            "actor_tick",
        }

    for scenario in (
        "click_open_ground_native_absence",
        "click_wall_native_absence",
    ):
        capture = captures[scenario]
        assert capture["observations"]["world_move_intent_count"] == 0
        assert capture["observations"]["native_actor_position_delta"] == 0.0
        assert capture["observations"]["surface_route"] == "world_cast"
        assert not any(intent["kind"] == "move" for intent in _flatten_intents(capture))

    assert captures["click_open_ground_native_absence"]["target"][
        "nav_segment_open"
    ] is True
    assert captures["click_wall_native_absence"]["target"][
        "nav_segment_open"
    ] is False

    for scenario, capture in captures.items():
        assert capture["real_input_result"]["button"] == "left"
        if scenario == "hud_click_swallowed":
            continue

        target = capture["target"]
        observations = capture["observations"]
        initial_aim = observations["initial_aim_world_point"]
        target_error = math.hypot(
            target["world_x"] - initial_aim["x"],
            target["world_y"] - initial_aim["y"],
        )
        assert math.isclose(
            target_error,
            observations["screen_to_world_target_error"],
            rel_tol=0.0,
            abs_tol=1e-9,
        )
        assert target_error <= 1.0
        assert target["nav_segment_open"] is observations["nav_segment_open"]

        aims = [
            intent
            for intent in _flatten_intents(capture)
            if intent["kind"] == "aim"
        ]
        assert aims[0]["point"] == initial_aim
        assert len(aims) == observations["active_actor_tick_count"] + 1

    earth_maxima = []
    for scenario in (
        "earth_charge_120ms",
        "earth_charge_600ms",
        "earth_charge_1500ms",
    ):
        capture = captures[scenario]
        assert capture["observations"]["primary_skill_ids"] == [40]
        assert capture["observations"]["release_observed"] is True
        phases = {
            intent["phase"]
            for intent in _flatten_intents(capture)
            if intent["kind"] == "cast"
        }
        assert phases == {"press", "hold", "release"}
        earth_maxima.append(
            max(
                sample["charge"]
                for sample in capture["observations"]["active_spell_samples"]
            )
        )
    assert earth_maxima[0] < earth_maxima[1] < earth_maxima[2]

    frost = captures["frost_channel_start_stop"]
    assert frost["observations"]["primary_skill_ids"] == [32]
    assert frost["observations"]["release_observed"] is True
    frost_phases = [
        intent["phase"]
        for intent in _flatten_intents(frost)
        if intent["kind"] == "cast"
    ]
    assert frost_phases[0] == "press"
    assert "hold" in frost_phases
    assert frost_phases[-1] == "release"

    hud = captures["hud_click_swallowed"]
    assert hud["observations"]["surface_route"] == "hud_interaction"
    assert {intent["kind"] for intent in _flatten_intents(hud)} == {"interact"}
    assert any(
        event["kind"] == "input_sample" and event["mouse"]["left"]
        for event in hud["raw_timeline"]
    )
    actor_events = [event for event in hud["raw_timeline"] if event["kind"] == "actor_tick"]
    assert actor_events
    assert all(not event["cast_active"] for event in actor_events)
    assert all(not event["gates"]["cast_blocked"] for event in actor_events)
    assert all(not event["gates"]["gameplay_input_blocked"] for event in actor_events)


class WebgameInputIntentRoundTripTests(unittest.TestCase):
    def test_every_live_native_trace_round_trips_through_intent_encoding_losslessly(
        self,
    ) -> None:
        _assert_every_live_native_trace_round_trips_losslessly()

    def test_intent_schema_pins_the_device_independent_action_union(self) -> None:
        _assert_intent_schema_pins_the_device_independent_action_union()

    def test_live_goldens_pin_native_mouse_cast_charge_channel_and_hud_routing(
        self,
    ) -> None:
        _assert_live_goldens_pin_native_mouse_semantics()
