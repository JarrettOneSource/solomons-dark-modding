"""Static contracts for the G2 native projectile/spell mechanics record."""

from __future__ import annotations

import json
import math
import struct
from typing import Any

from static_re_contract_support import ROOT, StaticReTestFailure


DOC_PATH = ROOT / "docs/reverse-engineering/native-projectile-and-spell-mechanics.md"
SKILLS_DOC_PATH = ROOT / "docs/reverse-engineering/native-skills-and-spells.md"
EARTH_VFX_CATALOG_PATH = ROOT / "docs/reverse-engineering/earth-boulder-vfx-catalog.json"
AUDIO_DOC_PATH = ROOT / "docs/reverse-engineering/native-audio-events.md"
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


def _earth_vfx_catalog() -> dict[str, Any]:
    return json.loads(EARTH_VFX_CATALOG_PATH.read_text(encoding="utf-8"))


def test_earth_boulder_second_pass_visual_ownership_is_pinned() -> str:
    catalog = _earth_vfx_catalog()
    constants = catalog["constants"]
    assets = {entry.get("record"): entry for entry in catalog["assets"] if "record" in entry}
    functions = {entry["address"] for entry in catalog["functions"]}

    _require(
        catalog["binary"]["sha256"]
        == "03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3",
        "Earth VFX binary identity drifted",
    )
    _require(
        {"0x00544C60", "0x00609D30", "0x005FE430", "0x0060AC40", "0x005E5450"}
        <= functions,
        "Earth owner/tick/builder/draw/release join is incomplete",
    )
    _require(constants["persistent_aura_record"] == 15, "persistent aura record drifted")
    _require(
        constants["persistent_aura_alpha_range"] == [0.35, 0.6]
        and constants["persistent_aura_scale_factor"] == 4.099999904632568,
        "persistent aura alpha/scale drifted",
    )
    _require(constants["opening_flash_record"] == 86, "opening flash record drifted")
    _require(
        constants["opening_flash_scale_factor"] == 2.5
        and constants["opening_flash_rotation_degrees_per_render_tick"] == 6.0
        and constants["opening_flash_blend"] == "additive",
        "opening flash compositor drifted",
    )
    _require(
        constants["visual_jitter_radius_range"] == [0.0, 3.0]
        and constants["visual_local_y_base"] == -20.0
        and constants["visual_local_y_charge_factor"] == -32.5,
        "Earth visual-root transform drifted",
    )
    _require(
        assets[15]["width"] == 38
        and assets[15]["height"] == 37
        and assets[15]["sha256"]
        == "5abc42fa09f09a5fefe3df9281d2102e6b93a48249edb4e21f36f73e1a0011eb",
        "record-15 extraction drifted",
    )
    _require("additive opening flash" in assets[86]["role"], "record 86 role drifted")
    _require("floor(30*old_charge)" in _document(), "assembly rebuild edge is absent")
    _require("must therefore not remove Earth" in _document(), "native range ownership drifted")
    _require(
        "each surviving flight tick advances position then postmultiplies"
        in catalog["render_contract"]["orientation"],
        "released-shell orientation ownership drifted",
    )
    return "Earth aura/flash, assembly, root transform, released orientation, and range are pinned"


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


def test_low_mana_primary_branch_and_all_consumers_are_pinned() -> str:
    mechanics = _document()
    skills = SKILLS_DOC_PATH.read_text(encoding="utf-8")
    audio = AUDIO_DOC_PATH.read_text(encoding="utf-8")

    _require_tokens(
        skills,
        (
            "## 2026-08-15 pure-primary low-mana branch closure",
            "shared mana helper `0x0052B150`",
            "`rejectIfInsufficient=0`",
            "MP exactly equal to cost spends the full cost and selects underpowered",
            "zero MP spends zero but still selects underpowered",
            "Ether `0x0053CFE0`",
            "Fire `0x0053DC60`",
            "Air `0x0053F9C0`",
            "Water `0x00543860`",
            "Earth `0x00544C60`",
            "effective turn input `2 -> 1.2`",
            "actor mask `0x2` rather than `0x1082`",
            "zeros the growth field",
            "float32 `baseCharge=base*charge`",
        ),
        "low-mana primary gameplay contract",
    )
    _require_tokens(
        mechanics,
        (
            "## 2026-08-15 low-mana presentation and damage consumers",
            "Phase advances from speed `2.4`, hence `7.2` degrees per tick instead of `9`",
            "The impact actor does not carry/read `+0x160`",
            "separately registered Fire particles remain",
            "width `.5625`, RGBA `(0,1,1,.25)`",
            "`.5,.3,.1`. Its ZAnimLit source starts at radius",
            "MiscLights retain their sampled radii but multiply",
            "`max(1,trunc(normalCount/4))`",
            "Initial additive alpha is therefore `.1875`",
            "`max(.25,min((base*charge)*charge,base*1.25))`",
            "Earth has no persistent weak render flag",
        ),
        "low-mana primary visual and contact contract",
    )
    _require_tokens(
        audio,
        (
            "## 2026-08-15 low-mana primary audio",
            "`sounds\\\\fizzle.wav`",
            "`sounds\\\\magicmissile` at pitch `1`, gain `.75`",
            "`sounds\\\\throwfire` at pitch `1`, gain `.75`",
            "registry 162 `sounds\\\\lightningloop__loop`",
            "`sounds\\\\iceloop__loop`",
            "every global tick divisible by 50 plays `fizzle` at pitch `.5`",
            "without inventing an extra press edge",
        ),
        "low-mana primary audio contract",
    )
    return "The shared low-mana branch and all five primary consumer graphs are pinned"


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
            "all four corona circles use `BadGuys[110]`",
            "`BadGuys[110]`",
            "`BadGuys[267..270]`",
            "`(age_ticks / 3) % 12`",
            "3 ticks/frame, 36 ticks/cycle",
            "`0x0079C5BC`",
            "`0x005E01E0`",
            "`0x00624B40`",
            "`regionLightPoint: null`",
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


def test_primary_targeting_homing_and_staff_cadence_are_pinned() -> str:
    doc = _document()
    heading = "## 2026-08-14 targeting, range, homing, and one-shot cadence correction"
    _require(heading in doc, "primary targeting/homing/cadence correction is absent")
    closure = doc.split(heading, maxsplit=1)[1]
    _require_tokens(
        closure,
        (
            "`0x00529AD0`",
            "30-degree aperture",
            "lower `+0xFC` priority first",
            "Gravestone constructor\n`0x005E5C30`",
            "priority `1000`",
            "dot product at least `0.71`",
            "vslot `+0x34` attachment offset",
            "exactly `(grave.x, grave.y-20)`",
            "no native fixed 205-unit reach",
            "QuickSpline middle control point half that distance",
            "nearest unused\neligible actor within radius `200`",
            "float32\n`0.600000024`",
            "`spawn + aimDirection*100`",
            "`0x00641160`",
            "float32\n`999999`",
            "turn accumulator `0.01`",
            "heading += 2 * turnAccumulator * movementScalar * signedAngularDelta",
            "Losing a target clears\nthe handle for rank 1",
            "Terrain lookahead runs every fifth age tick",
            "There is no native\nfixed flight lifetime",
            "float32 rate\n`0.075`",
            "Fire uses `0.05625`",
            "still-held Ether or Fire primary immediately queues the next\naction",
            "Protocol v13",
        ),
        "primary targeting, homing, range, and Staff cadence document",
    )
    return "Lightning fallback/arc, Ether homing, ranges, and held Staff cadence are pinned"


def test_fireball_contact_range_and_recast_closure_is_pinned() -> str:
    doc = _document()
    heading = "## 2026-08-14 Fireball contact, range, and recast closure"
    _require(heading in doc, "Fireball contact/range/recast closure is absent")
    closure = doc.split(heading, maxsplit=1)[1]
    _require_tokens(
        closure,
        (
            "`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`",
            "`0x0044B170` /\n  `0x0044B370`",
            "`0x00656580`",
            "`0.05625`/tick",
            "release is not\n  required for native Fire auto-repeat",
            "not target- or distance-bounded",
            "`0x0053DC60`",
            "`0x00529380`",
            "`4.5` Fireball speed global",
            "segment/polygon query `0x00524D70`",
            "collision mask\n  `0x700`",
            "`Fireball::Tick` `0x005FDD90`",
            "returns before\n   common movement and before cosmetic-particle allocation",
            "falls through and allocates one final\n   `Anim_FireParticle`",
            "No hard flight timer exists",
            "`0x005E5160`",
            "removal vslot **before**",
            "audio and presentation allocation",
            "`9bfad709cfb932b7e836c58f781a42ee78907a0211bac5d14a2583d721192738`",
            "visible semantic ages are exactly `0..15`",
            "frames\n  `0..3` each last four ticks",
            "record `110` source-over at `5*scale`",
            "`(1,1,0.75)`",
            "`ZAnimLit` vtable `0x0079C4DC`",
            "radius `1.5`, intensity\n  `1 - 0.04*age`",
            "shipped/default Enhanced\nEffects on halves fade to `[0.025,0.05)`",
            "no native\ncollision body/category/contact flags or health authority",
        ),
        "Fireball contact/range/recast closure",
    )
    _require_tokens(
        AUDIO_DOC_PATH.read_text(encoding="utf-8"),
        (
            "| `projectile.fire.impact` | Fireball contact | `0x005E5288` inside `0x005E5160` | 30 `sounds\\fireballhit` |",
            "signed float-RNG pitch `1 + U[-0.1,0.1)`",
            "The Fireball removal vslot runs first; null terrain contact owns the same request.",
        ),
        "Fireball impact audio catalog row",
    )
    return "Fire targeting absence, contact order, exact burst, light, audio, and bounded actor lane are pinned"


def test_ether_flight_compositor_and_contact_ownership_are_pinned() -> str:
    doc = _document()
    heading = "## 2026-08-14 Ether primary presentation audit"
    _require(heading in doc, "Ether presentation audit is absent")
    audit = doc.split(heading, maxsplit=1)[1]
    _require_tokens(
        audit,
        (
            "`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`",
            "`0x0053CFE0`",
            "`0x005E4990` / `0x005E4F80`",
            "`0x005FD270` / `0x005E0460`",
            "`0x005E4A80` / `0x005F1F00` / `0x005E4B80`",
            "`0x00535A30`",
            "`0x0079C544`",
            "`+0x154` | `RandomFloat(360)`",
            "`+0x15C` | `1.0`",
            "`+0x160` | `0`",
            "`+0x161` | `0`",
            "phase_next = phase + movementScalar * speed * 3",
            "advances presentation by 9",
            "root = (actor.x, actor.y - 10)",
            "**two complete outer passes**",
            "`Integer(10) + 2`",
            "`alpha = 0.35 * abs(sin_deg(5 * phase))`",
            "`alpha = 0.55 * abs(sin_deg(8 * phase))`",
            "| `110` | purple core | 27 x 26",
            "| `111` | white spark/cloud | 40 x 40",
            "| `112` | white ray | 40 x 40",
            "`a7b13b464e035e2099081ce942db4aa231fc7c20de1ecacbd9d0a590132c88d3`",
            "ordinary flight",
            "`BadGuys[53]`, heading-aligned",
            "`Anim_FadeMM`",
            "`ZAnimLit`",
            "Flight itself requests no sound",
            "does not construct a separate source glow or launch trail",
            "Do not infer impact from containment expiry or disappearance",
            "drawable frames are `F[1]..F[19]`",
            "exact sentinel `-9999.0f`",
            "radius `0.75`, intensity `1.0`, delta `-0.05`",
            "Registry 58 `magicmissilehit` pitch is `f32(1+U[0,0.1))`",
        ),
        "Ether flight/contact ownership audit",
    )
    return "Ether records 110..112 own flight; record 53 and FadeMM remain contact-owned"


def test_class_specific_rails_wall_shadow_painters_are_pinned() -> str:
    doc = _document()
    _require_tokens(
        doc,
        (
            "Rails builder `0x005F0EC0`",
            "`N=trunc(distance(P,P1)/length(s))+1`",
            "`Q=P+N*s`",
            "exactly two width-10 black line quads",
            "divisors `5` and `1.5`",
            "Wall builder `0x005EEBB0`",
            "Renderer `0x0061E780` calls segment",
            "helper `0x006561A0`",
            "indices `[0,1,2,2,1,3]`",
            "Neither Rails nor Wall owns a retained shadow",
        ),
        "Rails and Wall class-specific shadow painters",
    )
    return "Rails and Wall use their exact custom current-frame shadow painters"


def test_air_lightning_cadence_and_contact_light_source_are_pinned() -> str:
    doc = _document()
    _require_tokens(
        doc,
        (
            "`0x5F3759DF`",
            "`0x3E959773`",
            "new shipped profile selects Enhanced Effects On / spacing `15`",
            "seven vertex pairs/fourteen vertices",
            "thirty-six indices",
            "field `+0x140` is radius",
            "`+0x144` is intensity starting at `1`",
            "`multipleShadows=false`",
            "painter sort field `+0xA0`",
            "inner `75` and outer",
        ),
        "Air Lightning cadence/light-source document",
    )

    squared_distance = _f32(102.5 * 102.5)
    half_squared_distance = _f32(squared_distance * 0.5)
    squared_bits = struct.unpack("<I", struct.pack("<f", squared_distance))[0]
    estimate_bits = 0x5F3759DF - (squared_bits >> 1)
    estimate = struct.unpack("<f", struct.pack("<I", estimate_bits))[0]
    inverse_distance = _f32(
        estimate * (1.5 - half_squared_distance * estimate * estimate)
    )
    distance = _f32(1.0 / inverse_distance)
    ratio = _f32(distance / 15.0)
    step = min(0.5, _f32(2.0 / ratio))
    _require(
        struct.unpack("<I", struct.pack("<f", step))[0] == 0x3E959773,
        f"Air parameter step bits drifted: {step}",
    )

    samples: list[float] = []
    parameter = _f32(0.0)
    while parameter < 2.0 - step:
        samples.append(parameter)
        parameter = _f32(parameter + step)
    samples.append(2.0)
    _require(
        samples
        == [
            0.0,
            0.29217109084129333,
            0.5843421816825867,
            0.8765132427215576,
            1.1686843633651733,
            1.460855484008789,
            2.0,
        ],
        f"Air parameter samples drifted: {samples}",
    )
    return "Air shipped-default cadence, topology, and ZAnimLit mapping are pinned"


def test_frost_jet_operand_widths_and_rank_one_update_ownership_are_pinned() -> str:
    doc = _document()
    _require_tokens(
        doc,
        (
            "`0x004537E6` is `DC 05 08 4D 78 00`",
            "`00 00 00 40 E1 7A 84 3F` = `0.009999999776482582`",
            "`00 00 00 40 33 33 B3 3F` = `0.07500000298023224`",
            "`CD CC CC 3D` = `0.10000000149011612`",
            "Normal vtable\n`0x00784E84 + 0x08`",
            "Over vtable `0x00784EB4 + 0x08`",
            "both contain\n`0x00453670`",
            "`0x00793D7C`",
            "`Anim_FrostJetEffect_Chaining`",
            "It is not the Over updater",
            "Every persistent field is rounded by its `fstp DWORD` store",
            "`0x00415130` writes the submitted scale directly",
            "must not pre-quantize the cyan-to-white",
        ),
        "Frost Jet scalar-width/update-ownership document",
    )
    return "Frost Jet QWORD scalars and rank-1 shared updater are pinned"


# Emitter points the goldens resolve to, from records #3263 (K=0) and #3431 (K=7)
# of the images/Clothes.bundle common stream, point index 1.
_EMITTER_BANK_0 = (-45.5, -15.5)
_EMITTER_BANK_7 = (-41.5, -34.5)
_EMITTER_EPSILON = 1e-4  # the fixture's own trajectoryWorldUnits epsilon


def _facing_index(heading_degrees: float) -> int:
    """Native 0x0053B830: truncate, +7, signed /15, one conditional -24."""
    facing = int(heading_degrees) + 7
    facing //= 15
    if facing >= 24:
        facing -= 24
    return facing


def _emitter_of_projectile(
    sample: dict[str, Any], local_y: float, along_aim: float, speed: float | None
) -> tuple[float, float]:
    """Undo one elapsed tick, the element local, and any along-aim push."""
    if "velocityX" in sample:
        # Fire stores the aim UNIT vector; the per-tick step is that times 4.5.
        aim_x, aim_y = sample["velocityX"], sample["velocityY"]
        norm = math.hypot(aim_x, aim_y)
        _require(abs(norm - 1.0) < 1e-6, "Fire velocity columns are not a unit vector")
        aim_x, aim_y = aim_x / norm, aim_y / norm
        step = speed
    else:
        theta = math.radians(sample["headingDegrees"])
        aim_x, aim_y = math.sin(theta), -math.cos(theta)
        step = sample["baseSpeed"] * sample["movementScalar"]
    spawn_x = sample["x"] - aim_x * step
    spawn_y = sample["y"] - aim_y * step
    return (
        spawn_x - sample["wizardX"] - along_aim * aim_x,
        spawn_y - sample["wizardY"] - along_aim * aim_y - local_y,
    )


def _matches(point: tuple[float, float], expected: tuple[float, float]) -> bool:
    return (
        abs(point[0] - expected[0]) < _EMITTER_EPSILON
        and abs(point[1] - expected[1]) < _EMITTER_EPSILON
    )


def test_cast_glyph_emitter_index_and_offsets_are_pinned() -> str:
    doc = _document()
    _require_tokens(
        doc,
        (
            "0053b838  fld   dword ptr [edi + 0x6c]",
            "facing = ((int)actor.heading_degrees + 7) / 15",
            "if (facing >= 24) facing -= 24",
            "one conditional subtract, NOT a modulo",
            "`0x00747360` is the **CRT float-to-int truncation helper**",
            "index = facing + 24 * K",
            "`K = (int)actor->+0x238`, **unclamped**",
            "`K = (int)clamp(actor->+0x238 - 14.0, 0.0, 2.0)`",
            "`14.0` at `0x0078C560` and `2.0` at `0x007DE838`",
            "**no `+0x74` scale",
            "stride `0xC4`",
            "point-list pointer at `+0xA8`",
            "**point index 1**",
            "`#3244..#3483`",
            "`#796..#867`",
            "`#3263` (`K=0`)",
            "`#3431` (`K=7`)",
            "`0x007DE840` = `0.0`, `0x00784D80` = `15.0`",
            "images/Clothes.bundle",
        ),
        "cast glyph emitter document",
    )
    _require(
        _facing_index(287.59668) == 19,
        "documented facing formula does not yield 19 for the fixture heading",
    )
    _require(
        _facing_index(0.0) == 0 and _facing_index(359.9) == 0,
        "facing formula must wrap 359.9 back onto 0 with one subtraction",
    )
    return "Emitter index arithmetic, record layout, and element offsets are pinned"


def test_cast_glyph_emitter_resolves_every_recorded_projectile_spawn() -> str:
    fixture = _fixture()
    trajectories = fixture["trajectories"]
    resolved: list[str] = []

    for rank in ("rank1", "rank2"):
        sample = _samples(trajectories["ether"][rank]["samples"])[0]
        _require(sample["ageTicks"] == 1, f"ether {rank} first sample is not age 1")
        _require(
            _facing_index(sample["wizardHeadingDegrees"]) == 19,
            f"ether {rank} facing drifted",
        )
        point = _emitter_of_projectile(sample, local_y=10.0, along_aim=0.0, speed=None)
        _require(_matches(point, _EMITTER_BANK_7), f"ether {rank} emitter drifted: {point}")
        resolved.append(f"ether.{rank}")

    for rank in ("rank1", "rank2"):
        sample = _samples(trajectories["fire"][rank]["samples"])[0]
        _require(sample["ageTicks"] == 1, f"fire {rank} first sample is not age 1")
        point = _emitter_of_projectile(sample, local_y=10.0, along_aim=20.0, speed=4.5)
        _require(_matches(point, _EMITTER_BANK_7), f"fire {rank} emitter drifted: {point}")
        resolved.append(f"fire.{rank}")

    held_total = 0
    captures = [("earth.rank2", trajectories["earth"]["rank2"]["samples"])]
    captures += [
        (f"earth.rank1[{index}]", capture["samples"])
        for index, capture in enumerate(trajectories["earth"]["rank1ChargeCaptures"])
    ]
    for name, table in captures:
        held = [row for row in _samples(table) if row["held"]]
        _require(held, f"{name} records no held boulder samples")
        for index, row in enumerate(held):
            point = (
                row["x"] - row["wizardX"],
                row["y"] - row["wizardY"] - 15.0,
            )
            expected = _EMITTER_BANK_0 if index == 0 else _EMITTER_BANK_7
            _require(
                _matches(point, expected),
                f"{name} held sample {index} emitter drifted: {point}",
            )
        held_total += len(held)

    _require(held_total == 1137, f"held Earth sample coverage drifted: {held_total}")
    _require(len(resolved) == 4, "projectile spawn coverage drifted")
    return (
        "All 4 projectile spawns and 1137 held Earth samples resolve to the "
        "extracted emitter points at facing 19"
    )
