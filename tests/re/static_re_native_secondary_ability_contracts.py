"""Static contracts for the complete stock right-click ability system."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from static_re_contract_support import ROOT, StaticReTestFailure, read_text


CATALOG = ROOT / "docs/reverse-engineering/native-secondary-ability-catalog.json"
SKILL_CATALOG = ROOT / "docs/reverse-engineering/native-skill-catalog.json"
AUDIO_CATALOG = ROOT / "docs/reverse-engineering/native-audio-catalog.json"
SKILLS_DOC = ROOT / "docs/reverse-engineering/native-skills-and-spells.md"
EFFECTS_DOC = ROOT / "docs/reverse-engineering/native-projectiles-and-effects.md"
AUDIO_DOC = ROOT / "docs/reverse-engineering/native-audio-events.md"
GENERATOR = ROOT / "tools/generate_native_secondary_ability_catalog.py"

EXPECTED = {
    11: "Call Leviathan",
    12: "Planewalker",
    15: "Phasing",
    21: "Ring of Fire",
    23: "Firewalker",
    27: "Magic Storm",
    30: "Prismatic Shock",
    35: "Ring of Ice",
    41: "Earthquake",
    45: "Raise Golem",
    46: "Stoneskin",
    48: "Teleport",
    49: "Magic Circle",
    50: "Magic Trap",
    51: "Dampen",
    54: "Magic Shield",
    72: "Acid Rain",
    73: "Fire Wall",
    74: "Ether Drain",
    76: "Call Comet",
    77: "Turn Undead",
    78: "Mindstar",
    79: "Regenerate",
}


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise StaticReTestFailure(f"duplicate JSON key {key!r} in secondary catalog")
        value[key] = item
    return value


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(read_text(path), object_pairs_hook=_reject_duplicate_keys)
    if not isinstance(value, dict):
        raise StaticReTestFailure(f"{path.name} is not a JSON object")
    return value


def _rows(document: dict[str, Any], key: str, identity: str) -> dict[int, dict[str, Any]]:
    rows = document.get(key)
    if not isinstance(rows, list):
        raise StaticReTestFailure(f"{key} is not a list")
    result: dict[int, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or type(row.get(identity)) is not int:
            raise StaticReTestFailure(f"{key} contains a row without integer {identity}")
        row_id = row[identity]
        if row_id in result:
            raise StaticReTestFailure(f"duplicate {identity} {row_id}")
        result[row_id] = row
    return result


def test_native_secondary_ability_membership_rank_and_identity_are_closed() -> str:
    document = _load(CATALOG)
    skills_document = _load(SKILL_CATALOG)
    abilities = _rows(document, "abilities", "skill_id")
    skills = _rows(skills_document, "skills", "id")

    if document.get("schema") != "solomon-dark-native-secondary-ability-catalog-v1":
        raise StaticReTestFailure("secondary catalog schema drifted")
    source = document.get("source", {})
    if source.get("size") != 4_723_200 or source.get("sha256") != (
        "03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3"
    ):
        raise StaticReTestFailure("secondary catalog no longer pins the retail image")
    if source.get("dispatcher") != "0x0054CC50":
        raise StaticReTestFailure("secondary dispatcher identity drifted")
    if list(abilities) != list(EXPECTED) or document.get("summary", {}).get("skill_ids") != list(EXPECTED):
        raise StaticReTestFailure("right-click membership/order is no longer the exact 23-row set")

    for skill_id, name in EXPECTED.items():
        ability = abilities[skill_id]
        skill = skills.get(skill_id)
        if skill is None:
            raise StaticReTestFailure(f"skill {skill_id} vanished from the authored catalog")
        expected_fields = (
            "targeting", "trigger", "actors", "gameplay", "timing", "art",
            "audio", "authority", "cleanup", "evidence", "action",
        )
        if ability.get("name") != name or ability.get("category") != 2:
            raise StaticReTestFailure(f"skill {skill_id} identity/category drifted")
        if ability.get("disposition") != "closed_native_contract":
            raise StaticReTestFailure(f"skill {skill_id} is no longer closed")
        if any(not ability.get(field) and field not in {"actors"} for field in expected_fields):
            raise StaticReTestFailure(f"skill {skill_id} lost a lifecycle/presentation field")
        if ability.get("rank_config") != skill.get("config"):
            raise StaticReTestFailure(f"skill {skill_id} rank table diverged from native-skill-catalog")
        if ability.get("config_sha256") != skill.get("config_sha256"):
            raise StaticReTestFailure(f"skill {skill_id} config provenance diverged")
        evidence = ability.get("evidence")
        if not isinstance(evidence, list) or "0x0054CC50" not in evidence:
            raise StaticReTestFailure(f"skill {skill_id} lost its dispatcher evidence")

    lowered = read_text(CATALOG).lower()
    for forbidden in ("unknown", "tbd", "todo", "placeholder", "approximate"):
        if forbidden in lowered:
            raise StaticReTestFailure(f"secondary catalog contains unresolved marker {forbidden!r}")
    return "all 23 category-2 abilities retain exact authored rank and binary identity"


def test_native_secondary_ability_art_audio_and_lifecycle_are_pinned() -> str:
    abilities = _rows(_load(CATALOG), "abilities", "skill_id")
    audio_document = _load(AUDIO_CATALOG)
    native_audio = {
        row["file"]["path"].replace("\\", "/"): row
        for row in audio_document["compiled_registry"]
        if isinstance(row, dict) and isinstance(row.get("file"), dict)
    }

    for skill_id, ability in abilities.items():
        art_rows = ability.get("art")
        if not isinstance(art_rows, list) or not art_rows:
            raise StaticReTestFailure(f"skill {skill_id} has no complete presentation owner")
        for art_row in art_rows:
            if not all(art_row.get(key) for key in ("atlas", "records", "owner", "mode")):
                raise StaticReTestFailure(f"skill {skill_id} has an incomplete art row")
        sound_rows = ability.get("audio")
        if not isinstance(sound_rows, list) or not sound_rows:
            raise StaticReTestFailure(f"skill {skill_id} has no audio lifecycle")
        for sound_row in sound_rows:
            source = native_audio.get(sound_row.get("path"))
            if source is None:
                raise StaticReTestFailure(f"skill {skill_id} references unregistered audio")
            expected = (
                source["registry_index"],
                source["registry_member_offset"],
                source["native_class"],
                source["file"]["sha256"],
            )
            actual = tuple(
                sound_row.get(key)
                for key in ("registry_index", "registry_member_offset", "native_class", "sha256")
            )
            if actual != expected:
                raise StaticReTestFailure(f"skill {skill_id} audio metadata diverged from native registry")

    if abilities[21]["timing"] != {
        "segment_count": 30,
        "angle_step_degrees": 12,
        "shockwave_query_period_ticks": 10,
    }:
        raise StaticReTestFailure("Ring of Fire geometry/cadence drifted")
    if abilities[45]["timing"] != {
        "assembly_milestones": [0, 50, 100, 200],
        "contact_enable_age": 400,
        "natural_expiry": False,
    }:
        raise StaticReTestFailure("Golem assembly/contact lifecycle drifted")
    if abilities[50]["timing"] != {"full_charge_ticks": 800, "trigger_poll_period_ticks": 25}:
        raise StaticReTestFailure("Magic Trap charge/trigger cadence drifted")
    if abilities[54]["timing"] != {
        "hit_pulse_ticks": 40,
        "hit_pulse_start": 2.0,
        "hit_pulse_decay_per_tick": 0.05,
    }:
        raise StaticReTestFailure("Magic Shield pulse lifecycle drifted")
    if abilities[72]["timing"].get("targets_per_pulse") != "min(n, floor(n/3)+1)":
        raise StaticReTestFailure("Acid Rain exact shuffled target count drifted")
    if abilities[74]["timing"] != {
        "scale_in_ticks": 40,
        "active_ticks": 1000,
        "scale_out_ticks": 20,
        "phases": ["scale_in", "active", "scale_out"],
    }:
        raise StaticReTestFailure("Ether Drain fixed-tick lifecycle drifted")
    if abilities[51]["action"] != {
        "mode": 21,
        "name": "Action_PlayerWizard_CastSpin",
        "ticks": 73,
    }:
        raise StaticReTestFailure("Dampen cast-spin presentation drifted")
    if [row["path"] for row in abilities[78]["audio"]] != ["sounds/mindstar__stream.wav"]:
        raise StaticReTestFailure("Mindstar shared toggle stream drifted")
    if abilities[79]["audio"] != abilities[78]["audio"]:
        raise StaticReTestFailure("Regenerate no longer shares Mindstar's exact toggle stream")
    return "per-member VFX, audio, cadence, authority, and teardown are pinned"


def test_native_secondary_ability_documents_and_generator_are_wired() -> str:
    skills = read_text(SKILLS_DOC)
    effects = read_text(EFFECTS_DOC)
    audio = read_text(AUDIO_DOC)
    generator = read_text(GENERATOR)
    witnesses = {
        "skills": (
            "### Complete right-click presentation and lifecycle contract",
            "native-secondary-ability-catalog.json",
            "BadGuys[343..372,11,39]",
            "0x0054FF05",
            "0x0054FFD4",
        ),
        "effects": (
            "min(n, floor(n / 3) + 1)",
            "two `Anim_AcidRaindrop`",
            "five while",
            "100 * 10 = 1,000",
        ),
        "audio": (
            "### Secondary and advanced right-click events",
            "Call Leviathan `11`",
            "Mindstar `78` / Regenerate `79`",
            "Stoneskin `46`",
        ),
        "generator": (
            "SECONDARY_IDS = (",
            "CONTRACTS:",
            '"closed_native_contract"',
            "unresolved audio path",
        ),
    }
    documents = {"skills": skills, "effects": effects, "audio": audio, "generator": generator}
    for name, tokens in witnesses.items():
        missing = [token for token in tokens if token not in documents[name]]
        if missing:
            raise StaticReTestFailure(f"secondary {name} contract lost witnesses {missing}")
    return "right-click RE prose, exact Acid Rain branch, audio census, and generator are wired"
