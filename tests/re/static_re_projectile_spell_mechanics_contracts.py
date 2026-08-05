"""Static contracts for the G2 native projectile/spell mechanics record."""

from __future__ import annotations

import json
import math
import struct
from typing import Any

from static_re_contract_support import ROOT, StaticReTestFailure


DOC_PATH = ROOT / "docs/reverse-engineering/native-projectile-and-spell-mechanics.md"
FIXTURE_PATH = ROOT / "tests/fixtures/webgame/projectile-goldens.json"
CAPTURE_SHA = "1b9d454da60afefa2cb5f01a0f6e8ce829efebe6"


def _fail(message: str) -> None:
    raise StaticReTestFailure(message)


def _require(condition: bool, message: str) -> None:
    if not condition:
        _fail(message)


def _document() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


def _fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _samples(table: dict[str, Any]) -> list[dict[str, Any]]:
    columns = table["columns"]
    rows = table["rows"]
    _require(len(columns) == len(set(columns)), "sample columns must be unique")
    _require(table["count"] == len(rows), "sample count does not match rows")
    _require(
        all(len(row) == len(columns) for row in rows),
        "sample row width does not match columns",
    )
    return [dict(zip(columns, row, strict=True)) for row in rows]


def _f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def _assert_consecutive_native_ticks(samples: list[dict[str, Any]], name: str) -> None:
    _require(samples, f"{name} has no samples")
    for index, sample in enumerate(samples):
        _require(sample["tickIndex"] == index, f"{name} tickIndex gap at {index}")
        if index:
            _require(
                sample["nativeTick"] == samples[index - 1]["nativeTick"] + 1,
                f"{name} nativeTick gap at {index}",
            )


def _require_tokens(text: str, tokens: tuple[str, ...], subject: str) -> None:
    missing = [token for token in tokens if token not in text]
    if missing:
        _fail(f"{subject} is missing: {', '.join(missing)}")


def test_projectile_spell_native_dispatch_contract_is_complete() -> str:
    doc = _document()
    _require_tokens(
        doc,
        (
            "`0x0044B370`",
            "`0x0044B580`",
            "`0x0044B770`",
            "`0x00550180`",
            "`0x0054CAF0`",
            "`0x005B7080`",
            "`0x0063F6D0`",
            "`0x0053B830`",
            "`((animation_frame + 7) / 15) % 24`",
            "| Ether / Magic Missile | `8` | `0x0053CFE0`",
            "| Fire / Fireball | `16` | `0x0053DC60`",
            "| Air / Lightning | `24` | `0x0053F9C0`",
            "| Water / Frost Jet | `32` | `0x00543860`",
            "| Earth / Boulder | `40` | `0x00544C60`",
            "factory type `0x7D3`",
            "factory type `0x7D4`",
            "factory type `0x7D5`",
        ),
        "projectile/spell dispatch document",
    )
    return "All five primary handlers, factories, and the shared emitter are pinned"


def test_projectile_goldens_pin_live_capture_provenance_and_rank_coverage() -> str:
    fixture = _fixture()
    _require(fixture["fixtureVersion"] == 1, "unexpected fixture version")
    _require(fixture["campaign"] == "spellre-20260804", "wrong campaign")
    _require(fixture["roadmapGap"] == "G2", "wrong roadmap gap")

    capture = fixture["capture"]
    _require(capture["sourceSha"] == CAPTURE_SHA, "capture SHA drifted")
    _require(capture["runtimeSourceSeamAdded"] is False, "fixture claims a new seam")
    _require(capture["audioDisabled"] is True, "live audio was not disabled")
    _require(
        capture["udpPorts"] == {"local": 52281, "unusedRemote": 52282},
        "capture escaped the allocated UDP ports",
    )
    _require(
        set(capture["instances"])
        == {
            "spr-fire-r1-world",
            "spr-ether-r1",
            "spr-earth-r1",
            "spr-air-r1",
            "spr-water-r1",
            "spr-fire-contact",
            "spr-ether-contact",
            "spr-earth-contact",
            "spr-air-contact",
            "spr-water-contact2",
        },
        "capture instance inventory drifted",
    )
    methods = " ".join(capture["captureMethod"])
    _require("Lua exec" in methods, "Lua exec capture method is absent")
    _require("foreground Windows OS right-button input" in methods, "real Frost input is absent")
    _require("effective_rank from 1 to 2" in capture["rank2Method"], "rank-2 method is absent")

    trajectories = fixture["trajectories"]
    expected_counts = {
        ("ether", "rank1"): 604,
        ("ether", "rank2"): 604,
        ("fire", "rank1"): 399,
        ("fire", "rank2"): 399,
        ("air", "rank1"): 229,
        ("air", "rank2"): 259,
        ("water", "rank1"): 600,
        ("water", "rank2"): 600,
    }
    for (element, rank), count in expected_counts.items():
        entry = trajectories[element][rank]
        _require(entry["rank"] == int(rank[-1]), f"{element}/{rank} rank drifted")
        _require(entry["samples"]["count"] == count, f"{element}/{rank} count drifted")

    earth = trajectories["earth"]
    _require(
        [entry["holdFrames"] for entry in earth["rank1ChargeCaptures"]]
        == [2, 170, 700],
        "Earth rank-1 charge levels drifted",
    )
    _require(earth["rank2"]["rank"] == 2, "Earth rank-2 capture is absent")
    _require(earth["rank2"]["holdFrames"] == 170, "Earth rank-2 hold drifted")
    return "Live SHA, instances, methods, ports, and rank coverage are pinned"


def test_materialized_projectile_trajectories_pin_native_motion() -> str:
    trajectories = _fixture()["trajectories"]
    epsilon = 0.0001

    for rank_name in ("rank1", "rank2"):
        ether = _samples(trajectories["ether"][rank_name]["samples"])
        _assert_consecutive_native_ticks(ether, f"ether/{rank_name}")
        _require(all(row["radius"] == 15.0 for row in ether), "Ether radius drifted")
        _require(all(row["baseSpeed"] == 3.0 for row in ether), "Ether speed drifted")
        _require(all(row["movementScalar"] == 1.0 for row in ether), "Ether scalar drifted")
        for index, (before, after) in enumerate(zip(ether, ether[1:]), start=1):
            distance = math.hypot(after["x"] - before["x"], after["y"] - before["y"])
            if after["ageTicks"] == before["ageTicks"]:
                _require(index == len(ether) - 1, "Ether froze before its terminal sample")
                _require(distance <= epsilon, "Ether terminal sample moved without an actor tick")
            else:
                _require(after["ageTicks"] == before["ageTicks"] + 1, "Ether age gap")
                _require(abs(distance - 3.0) <= epsilon, f"Ether step drifted: {distance}")

        fire = _samples(trajectories["fire"][rank_name]["samples"])
        _assert_consecutive_native_ticks(fire, f"fire/{rank_name}")
        _require(all(row["radius"] == 22.5 for row in fire), "Fire radius drifted")
        for row in fire:
            unit_length = math.hypot(row["velocityX"], row["velocityY"])
            _require(abs(unit_length - 1.0) <= epsilon, "Fire velocity is not unit length")
        for index, (before, after) in enumerate(zip(fire, fire[1:]), start=1):
            distance = math.hypot(after["x"] - before["x"], after["y"] - before["y"])
            if after["ageTicks"] == before["ageTicks"]:
                _require(index == len(fire) - 1, "Fire froze before its terminal sample")
                _require(distance <= epsilon, "Fire terminal sample moved without an actor tick")
            else:
                _require(after["ageTicks"] == before["ageTicks"] + 1, "Fire age gap")
                _require(abs(distance - 4.5) <= epsilon, f"Fire step drifted: {distance}")

    return "Ether and Fire native-tick radii, headings, and 3.0/4.5 motion are pinned"


def test_earth_charge_curve_and_release_geometry_are_exact() -> str:
    earth = _fixture()["trajectories"]["earth"]
    curve = earth["chargeCurve"]
    _require(curve["initial"] == 0.18, "Earth initial charge drifted")
    _require(curve["incrementPerNativeTick"] == 0.00125, "Earth increment drifted")
    _require(curve["maximum"] == 1.0, "Earth maximum drifted")
    _require(curve["fullAfterIncrements"] == 656, "Earth full tick drifted")
    _require(curve["firstRecordedFullTickIndexZeroBased"] == 655, "Earth full row drifted")
    _require(curve["firstRecordedFullElapsedMs"] == 6547, "Earth full time drifted")
    _require(
        curve["formula"]
        == "C[0] = float32(0.18); C[n+1] = min(1, float32(C[n] + float32(0.5 * 0.0025)))",
        "Earth float32 recurrence drifted",
    )

    charge = _f32(0.18)
    increment = _f32(_f32(0.5) * _f32(0.0025))
    values: dict[int, float] = {}
    for update in range(1, 657):
        charge = min(1.0, _f32(charge + increment))
        if update in (97, 170, 656):
            values[update] = charge
    expected = {
        97: 0.3012498915195465,
        170: 0.39249980449676514,
        656: 1.0,
    }
    _require(values == expected, f"computed Earth recurrence drifted: {values}")

    captures = earth["rank1ChargeCaptures"]
    _require(
        [entry["finalCharge"] for entry in captures] == [0.301249892, 0.392499804, 1.0],
        "Earth rank-1 final charges drifted",
    )
    _require(
        [entry["samples"]["count"] for entry in captures] == [435, 508, 1038],
        "Earth rank-1 sample counts drifted",
    )
    _require(captures[0]["firstFlight"]["tickIndex"] == 97, "minimum action drifted")
    _require(captures[1]["firstFlight"]["tickIndex"] == 170, "170-frame release drifted")
    _require(captures[2]["firstFull"]["tickIndex"] == 655, "full-charge row drifted")
    _require(captures[2]["firstFlight"]["collisionRadius"] == 75.0, "flight radius drifted")
    _require(captures[2]["firstFlight"]["bodyRadiusX"] == 500.0, "body scale drifted")
    _require(earth["rank2"]["finalCharge"] == 0.392499804, "rank-2 curve drifted")
    _require(earth["rank2"]["firstFlight"]["damagePool"] == 4.62168264, "rank-2 pool drifted")
    return "Earth float32 recurrence, three charge levels, and release geometry are pinned"


def test_air_and_frost_channels_remain_tick_queries_with_exact_stop_edges() -> str:
    trajectories = _fixture()["trajectories"]

    for rank_name in ("rank1", "rank2"):
        air = _samples(trajectories["air"][rank_name]["samples"])
        _assert_consecutive_native_ticks(air, f"air/{rank_name}")
        _require("actorAddress" not in air[0], "Air was modeled as a projectile actor")
        _require(any(row["primarySkillId"] == 24 for row in air), "Air sustain is absent")
        _require(air[-1]["primarySkillId"] == 0, "Air stop edge is absent")

        water_entry = trajectories["water"][rank_name]
        water = _samples(water_entry["samples"])
        _assert_consecutive_native_ticks(water, f"water/{rank_name}")
        _require("actorAddress" not in water[0], "Frost was modeled as a projectile actor")
        transitions = water_entry["transitions"]
        _require([row["primarySkillId"] for row in transitions] == [0, 32, 0], "Frost edges drifted")
        _require(transitions[1]["audioActive"] is True, "Frost loop did not start")
        _require(transitions[1]["audioReferenceCount"] == 1, "Frost start refcount drifted")
        _require(transitions[2]["audioActive"] is False, "Frost loop did not stop")
        _require(transitions[2]["audioReferenceCount"] == 0, "Frost stop refcount drifted")
        _require(
            transitions[1]["audioStartCount"] == transitions[0]["audioStartCount"] + 1,
            "Frost start-count edge drifted",
        )
        _require(
            transitions[1]["audioStopCount"] == transitions[0]["audioStopCount"] + 1,
            "Frost harmless pre-start stop drifted",
        )
        _require(
            transitions[2]["audioStopCount"] == transitions[1]["audioStopCount"] + 1,
            "Frost release stop drifted",
        )

    rank1 = trajectories["water"]["rank1"]["transitions"]
    _require(rank1[2]["elapsedMs"] - rank1[1]["elapsedMs"] == 1500, "Frost 150-tick time drifted")

    real_mouse = trajectories["water"]["realMouseRank1"]
    _require("foreground Windows OS right button" in real_mouse["input"], "real input is absent")
    transitions = real_mouse["transitions"]
    _require([row["primarySkillId"] for row in transitions] == [0, 32, 0], "real Frost edges drifted")
    _require(transitions[1]["audioStartCount"] == 1, "real Frost start count drifted")
    _require(transitions[2]["audioStopCount"] == 1, "real Frost stop count drifted")
    _require(transitions[2]["elapsedMs"] - transitions[1]["elapsedMs"] == 110, "real Frost duration drifted")
    return "Air/Frost tick queries and deterministic plus real-input stop edges are pinned"


def test_projectile_contact_events_cross_check_existing_damage_goldens() -> str:
    fixture = _fixture()
    _require(
        fixture["existingDamageGoldens"]
        == {
            "sources": [
                "docs/reverse-engineering/multiplayer-element-damage-2026-07-26.md",
                "docs/reverse-engineering/multiplayer-fireball-contact-2026-07-26.md",
                "docs/reverse-engineering/earth-boulder-damage-formula-2026-07-27.md",
            ],
            "ether": {"host": 1.2001953125, "client": 1.1000976562},
            "fire": {"contact": 4.0},
            "air": {"host": 4.2333984375, "client": 4.18359375},
            "waterFrost": {"host": 4.2333984375, "client": 4.2084960938},
            "earth": {"hold2": 0.90625, "hold170": 1.5390625, "full": 10.0},
        },
        "cited damage goldens drifted",
    )

    contacts = {entry["element"]: entry for entry in fixture["contacts"]}
    _require(set(contacts) == {"fire", "ether", "air", "waterFrost", "earth"}, "contact set drifted")
    expected = {
        "fire": (4.0, 4.0, 0.000001, 1),
        "ether": (1.1999969000000021, 1.2001953125, 0.00025, 1),
        "air": (4.2502594000000045, 4.2333984375, 0.026, 170),
        "waterFrost": (4.2502594000000045, 4.2333984375, 0.026, 170),
        "earth": (10.0, 10.0, 0.000001, 1),
    }
    for element, (observed, golden, epsilon, event_count) in expected.items():
        entry = contacts[element]
        _require(entry["observedDamage"] == observed, f"{element} observed damage drifted")
        _require(entry["existingHostGolden"] == golden, f"{element} host golden drifted")
        _require(entry["epsilon"] == epsilon, f"{element} epsilon drifted")
        _require(len(entry["damageEvents"]) == event_count, f"{element} event count drifted")
        error = abs(entry["observedDamage"] - entry["existingHostGolden"])
        _require(abs(entry["absoluteError"] - error) < 1e-12, f"{element} error drifted")
        _require(error <= entry["epsilon"], f"{element} exceeds its epsilon")
        _require(entry["crossCheckPassed"] is True, f"{element} cross-check is false")

    _require(contacts["fire"]["damageEvents"][0]["projectileTargetDistance"] == 30.5124151, "Fire distance drifted")
    _require(contacts["ether"]["damageEvents"][0]["projectileTargetDistance"] == 19.5819551, "Ether distance drifted")
    _require(contacts["earth"]["damageEvents"][0]["projectileTargetDistance"] == 51.8984223, "Earth distance drifted")
    _require(contacts["earth"]["damageEvents"][0]["projectileRadius"] == 45.0, "Earth contact radius drifted")
    _require(contacts["fire"]["residualObservationTicks"] == 499, "Fire residual window drifted")
    _require(contacts["fire"]["subsequentHpDamage"] == 0.0, "Fire residual HP drifted")
    return "Live contacts remain inside the cited golden-specific epsilon bounds"


def test_projectile_presentation_and_fire_goodguy_semantics_are_pinned() -> str:
    doc = _document()
    _require_tokens(
        doc,
        (
            "`BadGuys[53]`",
            "`BadGuys[255..266]`",
            "`BadGuys[110..112]`",
            "`(age_ticks / 3) % 12`",
            "3 ticks/frame, 36 ticks/cycle",
            "`BadGuys[30]` and `[28]`",
            "`BadGuys[86]`",
            "`DeadHawg[46..77]`",
            "`Fire_Goodguy` (`0x7EE`)",
            "`0x005E76C0`",
            "`0x005FF050`",
            "`0x005FF1D0`",
            "`0x00610F90`",
            "lifetime `+0x144` starts at `2.0` and falls by `0.01` per tick",
            "every tick divisible by three",
            "`32 * scale` radius",
            "world-sprite-render-pipeline.md",
        ),
        "projectile presentation/Fire_Goodguy document",
    )
    return "Atlas hooks, frame cadence, world queue, and damaging 0x7EE trails are pinned"
