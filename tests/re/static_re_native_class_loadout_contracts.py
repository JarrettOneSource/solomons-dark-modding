"""Static contracts for the native class/loadout semantic payload."""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import re
import struct
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from static_re_contract_support import (
    ROOT,
    StaticReTestFailure,
    assert_recorded_hash_matches_file,
)


DOC_PATH = ROOT / "docs/reverse-engineering/native-class-loadouts.md"
FIXTURE_PATH = ROOT / "tests/fixtures/webgame/class-loadout-goldens.json"
RECORDER_PATH = ROOT / "tools/record_native_class_loadout_goldens.py"
CLASS_CATALOG_PATH = ROOT / "docs/reverse-engineering/native-class-catalog.json"

CLAIM_CENSUS = "class census and identity claim"
CLAIM_KIT = "starting kit and initialized stats claim"
CLAIM_KIT_DOC = "starting kit document table claim"
CLAIM_MAPPING = "definition-to-actor field mapping claim"
CLAIM_UNLOCK = "class unlock condition table claim"
CLAIM_LIVE = "live provenance and mixed participant independence claim"


ELEMENTS: tuple[dict[str, Any], ...] = (
    {
        "key": "ether",
        "name": "Ether",
        "raw_id": 0,
        "profile_id": 4,
        "root": 0,
        "primary": 8,
        "primary_name": "Magic Missile",
        "secondary": 11,
        "secondary_name": "Call Leviathan",
        "portrait": "Create.9",
        "portrait_record": 9,
    },
    {
        "key": "fire",
        "name": "Fire",
        "raw_id": 1,
        "profile_id": 0,
        "root": 1,
        "primary": 16,
        "primary_name": "Fireball",
        "secondary": 21,
        "secondary_name": "Ring of Fire",
        "portrait": "Create.10",
        "portrait_record": 10,
    },
    {
        "key": "air",
        "name": "Air",
        "raw_id": 2,
        "profile_id": 3,
        "root": 2,
        "primary": 24,
        "primary_name": "Lightning",
        "secondary": 27,
        "secondary_name": "Magic Storm",
        "portrait": "Create.11",
        "portrait_record": 11,
    },
    {
        "key": "water",
        "name": "Water",
        "raw_id": 3,
        "profile_id": 1,
        "root": 3,
        "primary": 32,
        "primary_name": "Frost Jet",
        "secondary": 35,
        "secondary_name": "Ring of Ice",
        "portrait": "Create.12",
        "portrait_record": 12,
    },
    {
        "key": "earth",
        "name": "Earth",
        "raw_id": 4,
        "profile_id": 2,
        "root": 4,
        "primary": 40,
        "primary_name": "Boulder",
        "secondary": 45,
        "secondary_name": "Raise Golem",
        "portrait": "Create.13",
        "portrait_record": 13,
    },
)

DISCIPLINES: tuple[dict[str, Any], ...] = (
    {
        "key": "arcane",
        "name": "Arcane",
        "raw_id": 0,
        "profile_id": 2,
        "root": 7,
        "art": "Create.0",
        "art_record": 0,
    },
    {
        "key": "body",
        "name": "Body",
        "raw_id": 1,
        "profile_id": 1,
        "root": 5,
        "art": "Create.1",
        "art_record": 1,
    },
    {
        "key": "mind",
        "name": "Mind",
        "raw_id": 2,
        "profile_id": 0,
        "root": 6,
        "art": "Create.5",
        "art_record": 5,
    },
)

EXPECTED_CLASS_KEYS = tuple(
    f"{element['key']}-{discipline['key']}"
    for element in ELEMENTS
    for discipline in DISCIPLINES
)

EXPECTED_EXTERNAL_EVIDENCE_HASHES = {
    "ether-arcane": "e21ef6070978e1127bd3698be0cd08cb27a4238eed41b5d70eec70294b726113",
    "ether-body": "66e58cb6ad82bdfdb445467927f4c18617bbf390734b2614440beb8cee1ef913",
    "ether-mind": "fdbbd00cc7d2b0c647714cdc3400c532b7db6192f7d312d07cde9e200fecfed0",
    "fire-arcane": "e7e5ccb19b542b11db0ec48684d99bcc141c4a7b3ed122d959651205859b4336",
    "fire-body": "ac1d4e2d24b10aab523cb5f9276b07a22cbcdaa6eb5e563a5318b82ca0f7e631",
    "fire-mind": "96551d38e1db2e52726bcd5015b2b0c3e3a42aa0cdbad7970cc7afc661c96bde",
    "air-arcane": "14bb37f93b200aed1550247137d701e6166ceda48237cf05de5fd098ed31b362",
    "air-body": "515a81281e5a7a3645a7ff6d8f935529cae88ae5ea43f9287b0ce45a10a19858",
    "air-mind": "f83467b4cd9c33b35e1056ba987085de5d9663839d42fbb42346a90ddc91edf2",
    "water-arcane": "c1dc91a7c0f64c025beedc0c4bb27365be69e3b03d0efa592397bf3db00baa45",
    "water-body": "10b8a37e4bd01453d0d273340f3d5d6e5165d81f6f53342733a9c0a2316a9fc2",
    "water-mind": "a937a1fd0d6c6f8e5cf6ebe975db41f5e66bd20ca95e85ecf49d71854369c9ce",
    "earth-arcane": "fa958968e37652409ee50abbf11adf045f7249f2d05b18bd16863c68b8d4847b",
    "earth-body": "0db46a2029f162e12a253d217bbef13e36d4634db3fce5b4929cf1e0ffcbf46f",
    "earth-mind": "fdcc0d0ef5c486f4d83c154721b3fda58335ba82d69c58bf38d72bff7d86b707",
}

EXPECTED_COMMITTED_HASH_PATHS = {
    "config/binary-layout.ini",
    "docs/reverse-engineering/native-asset-object-map.json",
    "docs/reverse-engineering/native-class-catalog.json",
    "docs/reverse-engineering/native-skill-catalog.json",
    "tools/record_native_class_loadout_goldens.py",
}

# name -> (offset, storage, typed value, raw word). A None raw word means the
# typed byte, not its four-byte neighboring window, is the contract.
EXPECTED_FIXED_STATS: dict[str, tuple[str, str, int | float, str | None]] = {
    "base_hp": ("0x6C", "f32", 50.0, "0x42480000"),
    "base_mp": ("0x78", "f32", 100.0, "0x42C80000"),
    "cast_speed_multiplier": ("0x94", "f32", 1.0, "0x3F800000"),
    "cheat_death_charges": ("0x820", "i32", 0, "0x00000000"),
    "cheat_death_enabled": ("0x81C", "u8", 0, None),
    "current_spell_id": ("0x750", "i32", 0, "0x00000000"),
    "damage_x4_remaining_ticks": ("0x824", "i32", 0, "0x00000000"),
    "deflect_chance": ("0xB8", "f32", 0.0, "0x00000000"),
    "experience": ("0x34", "f32", 0.0, "0x00000000"),
    "health_regeneration": ("0x9C", "f32", 1.0, "0x3F800000"),
    "hoarded_mp": ("0x740", "f32", 0.0, "0x00000000"),
    "hp": ("0x70", "f32", 50.0, "0x42480000"),
    "level": ("0x30", "i32", 1, "0x00000001"),
    "local_skill_picker_flag": ("0x839", "u8", 0, None),
    "mana_recovery_multiplier": ("0x98", "f32", 10.0, "0x41200000"),
    "max_hp": ("0x74", "f32", 50.0, "0x42480000"),
    "max_mp": ("0x80", "f32", 100.0, "0x42C80000"),
    "meditation_idle_elapsed_ticks": ("0x888", "i32", 0, "0x00000000"),
    "meditation_idle_ticks": ("0x884", "i32", -1, "0xFFFFFFFF"),
    "meditation_recovery_bonus": ("0x890", "f32", -1.0, "0xBF800000"),
    "melee_damage_multiplier": ("0x6F4", "f32", 1.0, "0x3F800000"),
    "move_speed": ("0x90", "f32", 0.949999988079071, "0x3F733333"),
    "mp": ("0x7C", "f32", 100.0, "0x42C80000"),
    "next_experience_threshold": ("0x3C", "f32", 90.0, "0x42B40000"),
    "nonlocal_mode_flag": ("0x40", "u8", 0, None),
    "offensive_damage_multiplier": ("0xF8", "f32", 1.0, "0x3F800000"),
    "offensive_mana_multiplier": ("0x3D4", "f32", 1.0, "0x3F800000"),
    "pickup_range": ("0xCC", "f32", 1.25, "0x3FA00000"),
    "previous_experience_threshold": ("0x38", "f32", 0.0, "0x00000000"),
    "push_strength": ("0x818", "f32", 12.0, "0x41400000"),
    "resist_magic_fraction": ("0xA4", "f32", 0.0, "0x00000000"),
    "resist_poison_fraction": ("0xA8", "f32", 0.0, "0x00000000"),
    "secondary_recharge_multiplier": ("0xD0", "f32", 1.0, "0x3F800000"),
    "spell_damage_base_additive": ("0x84", "f32", 0.0, "0x00000000"),
    "spell_damage_global_flat": ("0xFC", "f32", 0.0, "0x00000000"),
    "spell_damage_global_multiplier": ("0xF4", "f32", 1.0, "0x3F800000"),
    "staff_melee_damage_a": ("0xC4", "f32", 0.5, "0x3F000000"),
    "staff_melee_damage_b": ("0xC8", "f32", 1.0, "0x3F800000"),
    "unknown_0x68": ("0x68", "f32", 150.0, "0x43160000"),
    "unknown_0x88": ("0x88", "f32", 0.0, "0x00000000"),
    "unknown_0x8c": ("0x8C", "f32", 0.0, "0x00000000"),
    "unknown_0xa0": ("0xA0", "f32", 0.0, "0x00000000"),
    "unknown_0xac": ("0xAC", "f32", 0.0, "0x00000000"),
    "unknown_0xb0": ("0xB0", "f32", 0.0, "0x00000000"),
    "unknown_0xb4": ("0xB4", "f32", 1.0, "0x3F800000"),
    "unknown_0xbc": ("0xBC", "f32", 1.0, "0x3F800000"),
    "unknown_0xc0": ("0xC0", "f32", 1.0, "0x3F800000"),
}

EXPECTED_SELECTED_STATS = {
    "element_skill_row": ("0x82C", "i32", "element_root"),
    "discipline_skill_row": ("0x830", "i32", "discipline_root"),
    "primary_skill_row": ("0x86C", "i32", "primary_spell"),
    "secondary_skill_row": ("0x870", "i32", "secondary_spell"),
}

EXPECTED_VARIABLE_STATS = {
    "serialized_class_slot_0x834": ("0x834", "i32"),
    "special_choice_argument": ("0x844", "i32"),
    "meditation_recovery_ramp_ticks": ("0x88C", "i32"),
}

# These initialized fields were recovered after the committed class-loadout
# capture envelope was frozen. Keep their document contract explicit without
# pretending the older raw fixture sampled bytes outside its owned ranges.
EXPECTED_DOCUMENT_ONLY_FIXED_STATS = {
    "pending_skill_choices": ("0x44", "i32", 0, "0x00000000"),
    "deferred_skill_choices": ("0x48", "i32", 0, "0x00000000"),
    "unforge_attempt_count": ("0x874", "i32", 0, "0x00000000"),
}

EXPECTED_EQUIPMENT = {
    "amulet": 0,
    "attachment": 7004,
    "hat": 7005,
    "primary": 7005,
    "ring_1": 0,
    "ring_2": 0,
    "robe": 7006,
    "secondary": 7006,
    "weapon": 7004,
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise StaticReTestFailure(message)


def _read_json(path: Path, claim: str) -> dict[str, Any]:
    _require(path.is_file(), f"{claim}: required committed file is absent: {path.name}")
    value = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(value, dict), f"{claim}: {path.name} is not a JSON object")
    return value


def _read_text(path: Path, claim: str) -> str:
    _require(path.is_file(), f"{claim}: required committed file is absent: {path.name}")
    value = path.read_text(encoding="utf-8")
    _require(bool(value.strip()), f"{claim}: {path.name} is empty, so no claim was checked")
    return value


def _documented_number(value: int | float) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _assert_documented_fixed_stat(
    stat_name: str,
    storage: str,
    value: int | float,
    raw: str | None,
    initial: str,
) -> None:
    number_pattern = r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?"
    if stat_name == "nonlocal_mode_flag":
        pattern = rf"local `(?P<value>{number_pattern})`; remote bot `1`"
    elif stat_name == "current_spell_id":
        pattern = rf"local `(?P<value>{number_pattern})`; mixed remote bot `1014`"
    else:
        pattern = (
            rf"`(?P<value>{number_pattern})`"
            r"(?:, bits `(?P<bits>0x[0-9A-F]{8})`)?"
        )
    match = re.fullmatch(pattern, initial)
    _require(
        match is not None,
        f"{CLAIM_KIT_DOC}: {stat_name} initial-value cell lost its explicit typed-value structure; implementers could no longer distinguish the contracted value from commentary",
    )
    expected_value = _documented_number(value)
    documented_value = match.group("value")
    _require(
        documented_value == expected_value,
        f"{CLAIM_KIT_DOC}: {stat_name} documented value is {documented_value}, expected {expected_value}; every class could be initialized from a decimal that disagrees with the fixture and contract",
    )
    documented_bits = match.groupdict().get("bits")
    expected_bits = raw if storage == "f32" and value != 0.0 else None
    _require(
        documented_bits == expected_bits,
        f"{CLAIM_KIT_DOC}: {stat_name} documented raw bit pattern is {documented_bits}, expected {expected_bits}; every class could be initialized from bytes that disagree with the fixture and contract",
    )


def _unique_documented_stat_initial(
    table_rows: str,
    stat_name: str,
    offset: str,
    storage: str,
) -> str:
    row_pattern = (
        rf"^\| (?P<field>[^|\r\n]+?) \| `\+{re.escape(offset)} "
        rf"{re.escape(storage)}` \| (?P<initial>[^|\r\n]+?) \| "
        r"(?P<source>[^|\r\n]+?) \|$"
    )
    matches = list(re.finditer(row_pattern, table_rows, flags=re.MULTILINE))
    _require(
        len(matches) == 1,
        f"{CLAIM_KIT_DOC}: {stat_name} must resolve to one structural {offset} {storage} table row, found {len(matches)}; duplicate or missing candidates could make implementers choose the wrong class initialization value",
    )
    return matches[0].group("initial")


def _unique_index(
    rows: Any,
    key_name: str,
    expected_keys: Sequence[str],
    claim: str,
    label: str,
) -> dict[str, Mapping[str, Any]]:
    _require(isinstance(rows, list), f"{claim}: {label} is not a concrete list")
    keys = [row.get(key_name) if isinstance(row, dict) else None for row in rows]
    _require(
        keys == list(expected_keys),
        f"{claim}: {label} must enumerate exactly {list(expected_keys)}, observed {keys}",
    )
    duplicates = sorted({key for key in keys if keys.count(key) > 1})
    _require(
        not duplicates,
        f"{claim}: {label} lookup is ambiguous for duplicate keys {duplicates}",
    )
    result = {str(row[key_name]): row for row in rows}
    _require(
        set(result) == set(expected_keys),
        f"{claim}: {label} indexing lost a required class before its claims were checked",
    )
    return result


def _element_for_key(class_key: str) -> Mapping[str, Any]:
    matches = [row for row in ELEMENTS if class_key.startswith(f"{row['key']}-")]
    _require(
        len(matches) == 1,
        f"{CLAIM_CENSUS}: {class_key} resolves to {len(matches)} element definitions",
    )
    return matches[0]


def _discipline_for_key(class_key: str) -> Mapping[str, Any]:
    matches = [row for row in DISCIPLINES if class_key.endswith(f"-{row['key']}")]
    _require(
        len(matches) == 1,
        f"{CLAIM_CENSUS}: {class_key} resolves to {len(matches)} Discipline definitions",
    )
    return matches[0]


def _word_value(raw: str, storage: str) -> int | float:
    _require(
        re.fullmatch(r"0x[0-9A-F]{8}", raw or "") is not None,
        f"{CLAIM_KIT}: typed stat raw word is not an exact uppercase 32-bit value: {raw!r}",
    )
    word = int(raw, 16)
    if storage == "i32":
        return struct.unpack("<i", struct.pack("<I", word))[0]
    if storage == "f32":
        return struct.unpack("<f", struct.pack("<I", word))[0]
    if storage == "u8":
        return word & 0xFF
    raise StaticReTestFailure(
        f"{CLAIM_KIT}: stat storage {storage!r} has no byte-exact decoder"
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _expected_definition(class_key: str) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    return _element_for_key(class_key), _discipline_for_key(class_key)


def _structural_payload(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(snapshot)
    value["observed"].pop("tick", None)
    value["observed"].pop("app_tick", None)
    value["stats"].pop("meditation_recovery_ramp_ticks", None)
    return value


def _structural_digest(snapshot: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        _structural_payload(snapshot),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def _class_state_digest(snapshot: Mapping[str, Any]) -> str:
    normalized = _structural_payload(snapshot)
    payload = {
        "entity": normalized["entity"],
        "stats": normalized["stats"],
        "progression_book": normalized["progression_book"],
        "raw_regions": normalized["raw_regions"],
        "native_inventory": normalized["native_inventory"],
        "equipment": normalized["participant"]["equipment"],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return _sha256_bytes(encoded)


def _validate_settle_gate(
    settled: Mapping[str, Any],
    claim_label: str,
) -> None:
    snapshot = settled.get("first_complete_controllable_snapshot")
    gate = settled.get("settle_gate")
    _require(
        isinstance(snapshot, dict) and isinstance(gate, dict),
        f"{CLAIM_LIVE}: {claim_label} lacks a concrete snapshot and settle gate",
    )
    _require(
        gate.get("required_minimum_consecutive_samples") == 40,
        f"{CLAIM_LIVE}: {claim_label} no longer requires 40 consecutive structural samples",
    )
    _require(
        gate.get("required_minimum_span_seconds") == 2.0,
        f"{CLAIM_LIVE}: {claim_label} no longer requires a two-second structural span",
    )
    sample_count = gate.get("consecutive_sample_count")
    samples = gate.get("samples")
    _require(
        isinstance(sample_count, int) and sample_count >= 40,
        f"{CLAIM_LIVE}: {claim_label} did not reach the required structural sample floor",
    )
    _require(
        isinstance(samples, list) and len(samples) == sample_count,
        f"{CLAIM_LIVE}: {claim_label} settle sample list does not match its measured count",
    )
    _require(
        float(gate.get("measured_span_seconds", 0.0)) >= 2.0,
        f"{CLAIM_LIVE}: {claim_label} settled for less than two measured seconds",
    )
    digest = _structural_digest(snapshot)
    _require(
        gate.get("structural_sha256") == digest,
        f"{CLAIM_LIVE}: {claim_label} structural digest no longer authenticates its first snapshot",
    )
    expected_indices = list(range(1, sample_count + 1))
    observed_indices = [sample.get("sample_index") for sample in samples]
    _require(
        observed_indices == expected_indices,
        f"{CLAIM_LIVE}: {claim_label} settle sweep did not inspect every numbered sample",
    )
    _require(
        all(sample.get("structural_sha256") == digest for sample in samples),
        f"{CLAIM_LIVE}: {claim_label} accepted a structurally different settle sample",
    )
    ticks = [sample.get("tick") for sample in samples]
    app_ticks = [sample.get("app_tick") for sample in samples]
    _require(
        all(isinstance(value, int) for value in ticks + app_ticks),
        f"{CLAIM_LIVE}: {claim_label} settle sweep lost concrete tick stamps",
    )
    _require(
        ticks == sorted(ticks) and app_ticks == sorted(app_ticks),
        f"{CLAIM_LIVE}: {claim_label} settle tick stamps move backward",
    )
    _require(
        gate.get("first_tick") == ticks[0]
        and gate.get("last_tick") == ticks[-1]
        and gate.get("first_app_tick") == app_ticks[0]
        and gate.get("last_app_tick") == app_ticks[-1],
        f"{CLAIM_LIVE}: {claim_label} settle endpoints do not name the sampled tick endpoints",
    )
    _require(
        snapshot["observed"].get("tick") == ticks[0]
        and snapshot["observed"].get("app_tick") == app_ticks[0],
        f"{CLAIM_LIVE}: {claim_label} first controllable snapshot is not the first settle sample",
    )
    observed = snapshot["observed"]
    _require(
        observed.get("scene") == "hub"
        and observed.get("scene_kind") == "hub"
        and observed.get("session_state") == "in-hub"
        and observed.get("region_index") == 0
        and observed.get("input_sealed") is False
        and isinstance(observed.get("participant_count"), int)
        and observed["participant_count"] >= 1,
        f"{CLAIM_LIVE}: {claim_label} was not captured at a controllable Courtyard tick",
    )
    dynamic = gate.get("dynamic_runtime_fields")
    _require(
        isinstance(dynamic, dict)
        and set(dynamic) == {"meditation_recovery_ramp_ticks"},
        f"{CLAIM_LIVE}: {claim_label} must classify exactly progression+0x88C as dynamic",
    )
    classified = dynamic["meditation_recovery_ramp_ticks"]
    _require(
        classified.get("classification")
        == "runtime counter; retained at first tick but excluded from structural digest",
        f"{CLAIM_LIVE}: {claim_label} no longer states why progression+0x88C is excluded",
    )
    _require(
        all(
            set(sample.get("dynamic_runtime_stats") or {})
            == {"meditation_recovery_ramp_ticks"}
            for sample in samples
        ),
        f"{CLAIM_LIVE}: {claim_label} settle samples classify an extra changing field",
    )


def test_native_class_loadout_census_and_identity_are_pinned() -> str:
    fixture = _read_json(FIXTURE_PATH, CLAIM_CENSUS)
    definitions = _unique_index(
        fixture.get("class_definitions"),
        "class_key",
        EXPECTED_CLASS_KEYS,
        CLAIM_CENSUS,
        "class definition census",
    )
    header = fixture.get("header") or {}
    _require(
        (header.get("capture") or {}).get("class_count") == len(EXPECTED_CLASS_KEYS),
        f"{CLAIM_CENSUS}: header must name all 15 concrete selectable choices",
    )

    for class_key in EXPECTED_CLASS_KEYS:
        definition = definitions[class_key]
        element, discipline = _expected_definition(class_key)
        expected_identity = {
            "combined_scalar_id": None,
            "create_discipline_raw_id": discipline["raw_id"],
            "create_element_raw_id": element["raw_id"],
            "profile_discipline_id": discipline["profile_id"],
            "profile_element_id": element["profile_id"],
        }
        _require(
            definition.get("native_identity") == expected_identity,
            f"{CLAIM_CENSUS}: {class_key} native selector/profile identity drifted",
        )
        _require(
            definition.get("display_name")
            == f"{element['name']} / {discipline['name']}",
            f"{CLAIM_CENSUS}: {class_key} display identity no longer names both factors",
        )
        expected_art = {
            "discipline_art_atlas_record": discipline["art_record"],
            "discipline_art_id": discipline["art"],
            "element_portrait_atlas_record": element["portrait_record"],
            "element_portrait_id": element["portrait"],
        }
        _require(
            definition.get("native_art") == expected_art,
            f"{CLAIM_CENSUS}: {class_key} native portrait/Discipline art identity drifted",
        )

    catalog = _read_json(CLASS_CATALOG_PATH, CLAIM_CENSUS)
    _require(
        (catalog.get("summary") or {}).get("class_count") == 598,
        f"{CLAIM_CENSUS}: native class catalog enumeration anchor is no longer 598",
    )
    classes = catalog.get("classes")
    _require(
        isinstance(classes, list) and len(classes) == 598,
        f"{CLAIM_CENSUS}: native class catalog sweep did not reach all 598 concrete rows",
    )
    expected_types = {
        "CreateWizardMenu": ("0x00797B7C", "0x0058A820", "0x0058BCE0"),
        "PlayerWizard": ("0x00793F74", None, None),
        "Skills_Wizard": ("0x007A0CD4", None, None),
    }
    for name, (vtable, tick, click) in expected_types.items():
        matches = [row for row in classes if row.get("name") == name]
        _require(
            len(matches) == 1,
            f"{CLAIM_CENSUS}: {name} catalog lookup must refuse {len(matches)} candidates",
        )
        native_type = matches[0]
        _require(
            native_type.get("vtable") == vtable,
            f"{CLAIM_CENSUS}: {name} vtable no longer anchors the shared runtime type",
        )
        if tick is not None and click is not None:
            slots = native_type.get("slots")
            _require(
                isinstance(slots, list) and bool(slots),
                f"{CLAIM_CENSUS}: CreateWizardMenu slot sweep reached no vtable content",
            )
            tick_matches = [row for row in slots if row.get("offset") == "0x08"]
            click_matches = [row for row in slots if row.get("offset") == "0x64"]
            _require(
                len(tick_matches) == 1 and tick_matches[0].get("function") == tick,
                f"{CLAIM_CENSUS}: Create commit tick must remain uniquely wired to {tick}",
            )
            _require(
                len(click_matches) == 1 and click_matches[0].get("function") == click,
                f"{CLAIM_CENSUS}: Create choice click must remain uniquely wired to {click}",
            )

    doc = _read_text(DOC_PATH, CLAIM_CENSUS)
    required_doc_tokens = (
        "A retail class is not an object type or one numeric `class_id`.",
        "`class_key`, such as `fire-mind`, is a portable fixture/browser key.",
        "The element definition is a compiled switch in the new-character finalizer at\n`0x005D0290`.",
        "The Discipline definition is another compiled switch in `0x005D0290`",
        "G11 owns the Create screen's layout, art placement, focus, and input.",
    )
    for token in required_doc_tokens:
        _require(
            token in doc,
            f"{CLAIM_CENSUS}: implementation document lost the identity/source boundary expressed by {token!r}",
        )
    for class_key in EXPECTED_CLASS_KEYS:
        element, discipline = _expected_definition(class_key)
        expected_row = (
            f"| `{class_key}` | `{element['raw_id']}/{discipline['raw_id']}` | "
            f"`{element['profile_id']}/{discipline['profile_id']}` | "
            f"`{element['portrait']}` / `{discipline['art']}` | "
            f"`{element['root']}`; `{element['primary']}` {element['primary_name']}; "
            f"`{element['secondary']}` {element['secondary_name']} | "
            f"`{discipline['root']}` {discipline['name']} |"
        )
        _require(
            re.search(rf"^{re.escape(expected_row)}$", doc, flags=re.MULTILINE)
            is not None,
            f"{CLAIM_CENSUS}: document census row for {class_key} no longer pins every id, art reference, and spell",
        )
    return "15 product classes, three ID namespaces, art ids, and native type anchors are exact"


def test_native_class_loadout_documented_starting_kit_stats_are_exact() -> str:
    doc = _read_text(DOC_PATH, CLAIM_KIT_DOC)
    section_matches = list(
        re.finditer(
            r"^## Common initialized scalar state[ \t]*\r?\n"
            r"(?P<body>.*?)(?=^## )",
            doc,
            flags=re.MULTILINE | re.DOTALL,
        )
    )
    _require(
        len(section_matches) == 1,
        f"{CLAIM_KIT_DOC}: the common initialized scalar section must be unique, found {len(section_matches)}; otherwise the document does not identify which starting-kit table implementers must follow",
    )
    section = section_matches[0].group("body")
    applicability_pattern = (
        r"^The table is the complete scalar surface captured at the first controllable\r?\n"
        r"Courtyard tick for every class\. Offsets are from that participant's\r?\n"
        r"`Skills_Wizard`/progression object\. `f32` raw bits are shown where a decimal\r?\n"
        rf"would otherwise lose byte identity\. All {len(EXPECTED_CLASS_KEYS)} captures agree on every fixed value\.$"
    )
    applicability_matches = list(
        re.finditer(applicability_pattern, section, flags=re.MULTILINE)
    )
    _require(
        len(applicability_matches) == 1,
        f"{CLAIM_KIT_DOC}: the scalar table must structurally state that its values apply to all {len(EXPECTED_CLASS_KEYS)} classes; otherwise a class could silently fall outside the documented contract",
    )

    table_pattern = (
        r"^\| Field \| Offset / storage \| Initial value \| Native source or status \|[ \t]*\r?\n"
        r"^\| --- \| --- \| --- \| --- \|[ \t]*\r?\n"
        r"(?P<rows>(?:^\|[^\r\n]*\|[ \t]*(?:\r?\n|$))+)"
    )
    table_matches = list(
        re.finditer(table_pattern, section, flags=re.MULTILINE)
    )
    _require(
        len(table_matches) == 1,
        f"{CLAIM_KIT_DOC}: the four-column initialized-stat table must be unique and contiguous, found {len(table_matches)}; reflowed prose cannot stand in for row structure",
    )
    table_rows = table_matches[0].group("rows")
    structured_rows = list(
        re.finditer(
            r"^\| (?P<field>[^|\r\n]+?) \| `\+(?P<offset>0x[0-9A-F]+) "
            r"(?P<storage>f32|i32|u8)` \| (?P<initial>[^|\r\n]+?) \| "
            r"(?P<source>[^|\r\n]+?) \|$",
            table_rows,
            flags=re.MULTILINE,
        )
    )
    expected_names = (
        set(EXPECTED_FIXED_STATS)
        | set(EXPECTED_DOCUMENT_ONLY_FIXED_STATS)
        | set(EXPECTED_SELECTED_STATS)
        | set(EXPECTED_VARIABLE_STATS)
    )
    _require(
        {
            "base_hp",
            "move_speed",
            "secondary_skill_row",
            "meditation_recovery_ramp_ticks",
        }
        <= expected_names,
        f"{CLAIM_KIT_DOC}: expected constants lost a fixed, selected, or runtime witness, so the document sweep could pass without checking real kit content",
    )
    observed_locations = [
        (match.group("offset"), match.group("storage"))
        for match in structured_rows
    ]
    duplicate_locations = sorted(
        location
        for location in set(observed_locations)
        if observed_locations.count(location) > 1
    )
    _require(
        not duplicate_locations,
        f"{CLAIM_KIT_DOC}: duplicate offset/storage rows {duplicate_locations} make the starting-kit lookup ambiguous for implementers",
    )
    _require(
        len(structured_rows) == len(expected_names),
        f"{CLAIM_KIT_DOC}: the initialized-stat table exposes {len(structured_rows)} structural rows for {len(expected_names)} expected stats; an omitted or extra row would leave class initialization ambiguous",
    )
    expected_locations = {
        (offset, storage)
        for offset, storage, *_ in EXPECTED_FIXED_STATS.values()
    } | {
        (offset, storage)
        for offset, storage, *_ in EXPECTED_DOCUMENT_ONLY_FIXED_STATS.values()
    } | {
        (offset, storage)
        for offset, storage, *_ in EXPECTED_SELECTED_STATS.values()
    } | set(EXPECTED_VARIABLE_STATS.values())
    _require(
        set(observed_locations) == expected_locations,
        f"{CLAIM_KIT_DOC}: documented stat locations drifted from the contract; missing={sorted(expected_locations - set(observed_locations))}, extra={sorted(set(observed_locations) - expected_locations)}",
    )

    for stat_name, (offset, storage, value, raw) in EXPECTED_FIXED_STATS.items():
        initial = _unique_documented_stat_initial(
            table_rows, stat_name, offset, storage
        )
        _assert_documented_fixed_stat(
            stat_name, storage, value, raw, initial
        )
    for stat_name, (
        offset,
        storage,
        value,
        raw,
    ) in EXPECTED_DOCUMENT_ONLY_FIXED_STATS.items():
        initial = _unique_documented_stat_initial(
            table_rows, stat_name, offset, storage
        )
        _assert_documented_fixed_stat(
            stat_name, storage, value, raw, initial
        )

    for stat_name, (offset, storage, source_name) in EXPECTED_SELECTED_STATS.items():
        initial = _unique_documented_stat_initial(
            table_rows, stat_name, offset, storage
        )
        expected_initial = (
            "Discipline table value"
            if source_name == "discipline_root"
            else "element table value"
        )
        _require(
            initial == expected_initial,
            f"{CLAIM_KIT_DOC}: {stat_name} must document {expected_initial!r}, observed {initial!r}; a selected class could start from a row unrelated to its element or Discipline definition",
        )

    documented_variable_values = {
        "serialized_class_slot_0x834": "sample-dependent",
        "special_choice_argument": "sample-dependent/opaque",
        "meditation_recovery_ramp_ticks": "live runtime counter",
    }
    _require(
        set(documented_variable_values) == set(EXPECTED_VARIABLE_STATS),
        f"{CLAIM_KIT_DOC}: document-only runtime statuses no longer cover exactly the contract's variable stat constants",
    )
    for stat_name, (offset, storage) in EXPECTED_VARIABLE_STATS.items():
        initial = _unique_documented_stat_initial(
            table_rows, stat_name, offset, storage
        )
        expected_initial = documented_variable_values[stat_name]
        _require(
            initial == expected_initial,
            f"{CLAIM_KIT_DOC}: {stat_name} must remain documented as {expected_initial!r}, observed {initial!r}; a sample-dependent runtime value could be mistaken for a class constant",
        )

    return (
        f"all {len(expected_names)} documented stat rows structurally pin the values and raw bits shared by all "
        f"{len(EXPECTED_CLASS_KEYS)} starting kits"
    )


def test_native_class_loadout_starting_kits_are_stat_exact() -> str:
    fixture = _read_json(FIXTURE_PATH, CLAIM_KIT)
    definitions = _unique_index(
        fixture.get("class_definitions"),
        "class_key",
        EXPECTED_CLASS_KEYS,
        CLAIM_KIT,
        "starting-kit definition census",
    )
    captures = _unique_index(
        fixture.get("captures"),
        "class_key",
        EXPECTED_CLASS_KEYS,
        CLAIM_KIT,
        "live starting-kit capture census",
    )
    expected_stat_keys = (
        set(EXPECTED_FIXED_STATS)
        | set(EXPECTED_SELECTED_STATS)
        | set(EXPECTED_VARIABLE_STATS)
    )

    for class_key in EXPECTED_CLASS_KEYS:
        element, discipline = _expected_definition(class_key)
        definition = definitions[class_key]
        expected_kit = {
            "all_root_rows_granted": list(range(8)),
            "equipment_type_ids": {"hat": 7005, "robe": 7006, "weapon": 7004},
            "inventory_slots": [0, 1],
            "inventory_type_ids": [7001, 7001],
            "primary_spell": {
                "name": element["primary_name"],
                "rank": 1,
                "row": element["primary"],
            },
            "root_rank": 1,
            "secondary_spell": {
                "name": element["secondary_name"],
                "rank": 1,
                "row": element["secondary"],
            },
            "selected_discipline_root": {
                "name": f"{discipline['name']} Discipline",
                "rank": 1,
                "row": discipline["root"],
            },
            "selected_element_root": {
                "name": f"Element of {element['name']}",
                "rank": 1,
                "row": element["root"],
            },
        }
        _require(
            definition.get("starting_kit") == expected_kit,
            f"{CLAIM_KIT}: {class_key} definition no longer carries its exact roots, spells, ranks, and items",
        )

        snapshot = captures[class_key].get("first_complete_controllable_snapshot")
        _require(
            isinstance(snapshot, dict),
            f"{CLAIM_KIT}: {class_key} has no first controllable actor snapshot",
        )
        stats = snapshot.get("stats")
        _require(
            isinstance(stats, dict) and set(stats) == expected_stat_keys,
            f"{CLAIM_KIT}: {class_key} stat census must cover every documented fixed, selected, and opaque field",
        )
        for stat_name, (offset, storage, value, raw) in EXPECTED_FIXED_STATS.items():
            observed = stats[stat_name]
            _require(
                observed.get("offset") == offset
                and observed.get("storage") == storage
                and observed.get("value") == value,
                f"{CLAIM_KIT}: {class_key} {stat_name} no longer initializes as {offset} {storage} {value}",
            )
            _require(
                _word_value(observed.get("raw_u32", ""), storage) == value,
                f"{CLAIM_KIT}: {class_key} {stat_name} typed value disagrees with its native bytes",
            )
            if raw is not None:
                _require(
                    observed.get("raw_u32") == raw,
                    f"{CLAIM_KIT}: {class_key} {stat_name} raw word no longer pins {raw}",
                )
        selected_values = {
            "element_root": element["root"],
            "discipline_root": discipline["root"],
            "primary_spell": element["primary"],
            "secondary_spell": element["secondary"],
        }
        for stat_name, (offset, storage, source_name) in EXPECTED_SELECTED_STATS.items():
            observed = stats[stat_name]
            expected_value = selected_values[source_name]
            _require(
                observed.get("offset") == offset
                and observed.get("storage") == storage
                and observed.get("value") == expected_value
                and _word_value(observed.get("raw_u32", ""), storage) == expected_value,
                f"{CLAIM_KIT}: {class_key} {stat_name} no longer starts from its selected definition row",
            )
        for stat_name, (offset, storage) in EXPECTED_VARIABLE_STATS.items():
            observed = stats[stat_name]
            _require(
                observed.get("offset") == offset
                and observed.get("storage") == storage
                and _word_value(observed.get("raw_u32", ""), storage)
                == observed.get("value"),
                f"{CLAIM_KIT}: {class_key} opaque/runtime field {stat_name} lost its typed byte provenance",
            )
        random_slot = stats["serialized_class_slot_0x834"]["value"]
        _require(
            isinstance(random_slot, int) and 0 <= random_slot < 1_000_000,
            f"{CLAIM_KIT}: {class_key} constructor-random +0x834 value left its native range",
        )

        book = snapshot.get("progression_book")
        _require(
            isinstance(book, dict)
            and book.get("entry_count") == 83
            and book.get("entry_stride") == "0x70",
            f"{CLAIM_KIT}: {class_key} no longer exposes one complete 83-row 0x70-stride book",
        )
        entries = book.get("entries")
        _require(
            isinstance(entries, list)
            and [row.get("entry_index") for row in entries] == list(range(83)),
            f"{CLAIM_KIT}: {class_key} book sweep must reach each concrete row 0 through 82 exactly once",
        )
        active_rows = set(range(8)) | {element["primary"], element["secondary"]}
        for row in entries:
            row_index = row["entry_index"]
            expected_rank = 1 if row_index in active_rows else 0
            _require(
                row.get("base_rank_u16") == expected_rank
                and row.get("effective_rank_u16") == expected_rank,
                f"{CLAIM_KIT}: {class_key} book row {row_index} must start at rank {expected_rank}",
            )

        inventory = snapshot.get("native_inventory")
        expected_items = [
            {"recipe_uid": 0, "slot": 0, "stack_count": 1, "type_id": 7001},
            {"recipe_uid": 0, "slot": 1, "stack_count": 1, "type_id": 7001},
        ]
        _require(
            isinstance(inventory, dict)
            and inventory.get("valid") is True
            and inventory.get("truncated") is False
            and inventory.get("item_count") == 2
            and inventory.get("raw_item_count") == 2
            and inventory.get("enumerated_item_count") == 2
            and inventory.get("items") == expected_items,
            f"{CLAIM_KIT}: {class_key} must start with exactly two slot-ordered 7001 potions",
        )
        equipment = ((snapshot.get("participant") or {}).get("equipment") or {})
        slots = equipment.get("slots")
        _require(
            equipment.get("valid") is True
            and isinstance(slots, dict)
            and set(slots) == set(EXPECTED_EQUIPMENT),
            f"{CLAIM_KIT}: {class_key} equipment sweep must reach every named and visual slot",
        )
        for slot_name, type_id in EXPECTED_EQUIPMENT.items():
            _require(
                slots[slot_name] == {"recipe_uid": 0, "type_id": type_id},
                f"{CLAIM_KIT}: {class_key} equipment slot {slot_name} no longer starts as native type {type_id}",
            )

        raw_regions = snapshot.get("raw_regions")
        _require(
            isinstance(raw_regions, dict)
            and set(raw_regions)
            == {"constructor_scalar", "class_selection", "progression_book"},
            f"{CLAIM_KIT}: {class_key} raw-byte sweep lost a documented per-entity region",
        )
        expected_raw_shapes = {
            "constructor_scalar": (164, "0x30"),
            "class_selection": (72, "0x82C"),
        }
        for region_name, (byte_count, progression_offset) in expected_raw_shapes.items():
            region = raw_regions[region_name]
            raw_bytes = bytes.fromhex(region.get("hex", ""))
            _require(
                region.get("byte_count") == byte_count
                and len(raw_bytes) == byte_count
                and region.get("progression_offset") == progression_offset,
                f"{CLAIM_KIT}: {class_key} {region_name} raw region no longer pins its exact address span",
            )
            _require(
                region.get("sha256") == _sha256_bytes(raw_bytes),
                f"{CLAIM_KIT}: {class_key} {region_name} recorded hash does not authenticate its bytes",
            )
        raw_book = raw_regions["progression_book"]
        raw_book_bytes = bytes.fromhex(raw_book.get("hex", ""))
        normalized_book_bytes = bytes.fromhex(raw_book.get("normalized_hex", ""))
        _require(
            raw_book.get("address_source") == "progression+0x20"
            and raw_book.get("byte_count") == 9296
            and len(raw_book_bytes) == 9296
            and len(normalized_book_bytes) == 9296,
            f"{CLAIM_KIT}: {class_key} raw book must cover all 83 rows at 0x70 bytes each",
        )
        _require(
            raw_book.get("sha256") == _sha256_bytes(raw_book_bytes)
            and raw_book.get("normalized_sha256")
            == _sha256_bytes(normalized_book_bytes),
            f"{CLAIM_KIT}: {class_key} raw and normalized book hashes must authenticate both recordings",
        )
        _require(
            raw_book.get("pointer_normalization")
            == "zero each row's +0x6C..+0x6F StatBook pointer",
            f"{CLAIM_KIT}: {class_key} book portability rule no longer names the exact pointer bytes",
        )
        for row in entries:
            row_index = row["entry_index"]
            start = row_index * 0x70
            _require(
                normalized_book_bytes[start + 0x6C : start + 0x70] == b"\0\0\0\0",
                f"{CLAIM_KIT}: {class_key} normalized book row {row_index} retained a process pointer",
            )
            decoded = {
                "family_root_u16": struct.unpack_from("<H", raw_book_bytes, start + 0x1C)[0],
                "unknown_0x1e_u16": struct.unpack_from("<H", raw_book_bytes, start + 0x1E)[0],
                "base_rank_u16": struct.unpack_from("<H", raw_book_bytes, start + 0x20)[0],
                "effective_rank_u16": struct.unpack_from("<H", raw_book_bytes, start + 0x22)[0],
                "unknown_0x24_u8": raw_book_bytes[start + 0x24],
                "unknown_0x25_u8": raw_book_bytes[start + 0x25],
                "category_u8": raw_book_bytes[start + 0x26],
                "flags_0x27_u8": raw_book_bytes[start + 0x27],
                "cooldown_current_raw_u32": (
                    f"0x{struct.unpack_from('<I', raw_book_bytes, start + 0x64)[0]:08X}"
                ),
                "cooldown_cap_raw_u32": (
                    f"0x{struct.unpack_from('<I', raw_book_bytes, start + 0x68)[0]:08X}"
                ),
            }
            _require(
                all(row.get(field) == value for field, value in decoded.items()),
                f"{CLAIM_KIT}: {class_key} decoded book row {row_index} disagrees with its native bytes",
            )

    doc = _read_text(DOC_PATH, CLAIM_KIT)
    _require(
        "There are no class-specific numeric HP, MP, movement, damage, resistance,\nrecovery, or equipment modifiers at initialization."
        in doc,
        f"{CLAIM_KIT}: document no longer distinguishes shared init values from class rules",
    )
    _require(
        "all `83 * 0x70 = 9296` raw bytes" in doc,
        f"{CLAIM_KIT}: document no longer commits to the full per-entity raw book region",
    )
    return "all 15 starting kits, every typed stat, item slot, rank, and raw book byte are exact"


def test_native_class_loadout_definition_to_actor_mapping_is_pinned() -> str:
    fixture = _read_json(FIXTURE_PATH, CLAIM_MAPPING)
    definitions = _unique_index(
        fixture.get("class_definitions"),
        "class_key",
        EXPECTED_CLASS_KEYS,
        CLAIM_MAPPING,
        "definition mapping census",
    )
    captures = _unique_index(
        fixture.get("captures"),
        "class_key",
        EXPECTED_CLASS_KEYS,
        CLAIM_MAPPING,
        "actor mapping capture census",
    )
    mapping_shape = {
        "element_root": ("0x82C", "element_skill_row"),
        "discipline_root": ("0x830", "discipline_skill_row"),
        "primary_spell": ("0x86C", "primary_skill_row"),
        "secondary_spell": ("0x870", "secondary_skill_row"),
    }

    for class_key in EXPECTED_CLASS_KEYS:
        element, discipline = _expected_definition(class_key)
        expected_values = {
            "element_root": element["root"],
            "discipline_root": discipline["root"],
            "primary_spell": element["primary"],
            "secondary_spell": element["secondary"],
        }
        definition_mapping = definitions[class_key].get("definition_to_actor_fields")
        _require(
            isinstance(definition_mapping, dict)
            and set(definition_mapping) == set(mapping_shape),
            f"{CLAIM_MAPPING}: {class_key} must map all four definition selectors to actor fields",
        )
        snapshot = captures[class_key]["first_complete_controllable_snapshot"]
        stats = snapshot["stats"]
        raw_region = snapshot["raw_regions"]["class_selection"]
        raw_bytes = bytes.fromhex(raw_region["hex"])
        _require(
            len(raw_bytes) == 0x48 and raw_region.get("progression_offset") == "0x82C",
            f"{CLAIM_MAPPING}: {class_key} class-selection bytes no longer begin at progression+0x82C",
        )
        for field_name, (offset, stat_name) in mapping_shape.items():
            expected_value = expected_values[field_name]
            _require(
                definition_mapping[field_name]
                == {"progression_offset": offset, "value": expected_value},
                f"{CLAIM_MAPPING}: {class_key} {field_name} must map to {offset} with value {expected_value}",
            )
            _require(
                stats[stat_name]["offset"] == offset
                and stats[stat_name]["value"] == expected_value,
                f"{CLAIM_MAPPING}: {class_key} actor {stat_name} does not consume {field_name}",
            )
            relative = int(offset, 16) - 0x82C
            _require(
                struct.unpack_from("<i", raw_bytes, relative)[0] == expected_value,
                f"{CLAIM_MAPPING}: {class_key} raw actor bytes do not contain {field_name} at {offset}",
            )

        entity = snapshot.get("entity")
        _require(
            isinstance(entity, dict)
            and entity.get("actor_address", 0) > 0
            and entity.get("progression_address", 0) > 0
            and entity.get("progression_book_address", 0) > 0,
            f"{CLAIM_MAPPING}: {class_key} actor/progression/book ownership has no concrete live witness",
        )
        _require(
            entity.get("actor_plus_0x300_handle")
            == entity.get("api_progression_handle_address")
            and entity.get("actor_plus_0x300_handle_inner")
            == entity.get("progression_address"),
            f"{CLAIM_MAPPING}: {class_key} actor+0x300 handle no longer resolves its own progression object",
        )
        _require(
            entity.get("progression_book_entry_count") == 83,
            f"{CLAIM_MAPPING}: {class_key} actor-owned book mapping no longer reaches 83 rows",
        )
        owned = ((snapshot.get("participant") or {}).get("owned_progression") or {})
        _require(
            owned.get("initialized") is True
            and owned.get("book_entry_count") == 83
            and owned.get("book_entry_total_count") == 83
            and owned.get("book_truncated") is False,
            f"{CLAIM_MAPPING}: {class_key} participant-owned ledger no longer agrees with the native book",
        )

    doc = _read_text(DOC_PATH, CLAIM_MAPPING)
    required_mapping_tokens = (
        "The Create tick `0x0058A820` publishes those raw values to\n`DAT_0080807C` (element) and `DAT_00808080` (Discipline)",
        "| element root row | progression `+0x82C i32` |",
        "| Discipline root row | progression `+0x830 i32` |",
        "| primary spell row | progression `+0x86C i32` |",
        "| secondary spell row | progression `+0x870 i32` |",
        "PlayerWizard + 0x300 -> progression smart-pointer handle",
        "`0x0065F9A0` refreshes derived state after the selected grants",
    )
    for token in required_mapping_tokens:
        _require(
            token in doc,
            f"{CLAIM_MAPPING}: implementation document lost the wired consequence expressed by {token!r}",
        )
    _require(
        re.search(
            r"`0x0058BCE0` searches exactly five element hit points and\n"
            r"three Discipline hit points\. A click writes only the owning Create object:",
            doc,
        )
        is not None,
        f"{CLAIM_MAPPING}: document no longer pins the selector counts to the click handler",
    )
    return "all definition fields map byte-exactly into each participant-owned actor progression"


def test_native_class_loadout_unlock_conditions_are_pinned() -> str:
    fixture = _read_json(FIXTURE_PATH, CLAIM_UNLOCK)
    definitions = _unique_index(
        fixture.get("class_definitions"),
        "class_key",
        EXPECTED_CLASS_KEYS,
        CLAIM_UNLOCK,
        "definition unlock census",
    )
    unlocks = _unique_index(
        fixture.get("unlock_conditions"),
        "class_key",
        EXPECTED_CLASS_KEYS,
        CLAIM_UNLOCK,
        "standalone unlock census",
    )
    expected_unlock = {
        "condition": "always",
        "initially_unlocked": True,
        "persistent_unlock_key": None,
    }
    for class_key in EXPECTED_CLASS_KEYS:
        _require(
            definitions[class_key].get("unlock") == expected_unlock,
            f"{CLAIM_UNLOCK}: {class_key} definition must remain available on a fresh run",
        )
        _require(
            {key: value for key, value in unlocks[class_key].items() if key != "class_key"}
            == expected_unlock,
            f"{CLAIM_UNLOCK}: {class_key} standalone unlock row must remain always/true/no-key",
        )

    doc = _read_text(DOC_PATH, CLAIM_UNLOCK)
    for class_key in EXPECTED_CLASS_KEYS:
        pattern = (
            rf"^\| `{re.escape(class_key)}` \| yes \| always \| none \|$"
        )
        _require(
            re.search(pattern, doc, flags=re.MULTILINE) is not None,
            f"{CLAIM_UNLOCK}: document table no longer gives {class_key} the exact first-run condition",
        )
    required_unlock_tokens = (
        "contains no save/unlock\npredicate",
        "it does not gate\nmanual picker choices and is not evidence of class locks",
        "G10 owns the save representation.",
        "That persistence boundary does not create class unlock state.",
    )
    for token in required_unlock_tokens:
        _require(
            token in doc,
            f"{CLAIM_UNLOCK}: document lost the unlock/persistence boundary expressed by {token!r}",
        )
    return "all 15 classes remain first-run available with no persistent unlock key"


def _find_function(tree: ast.Module, name: str, claim: str) -> ast.FunctionDef:
    matches = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    _require(
        len(matches) == 1,
        f"{claim}: recorder function {name} must resolve uniquely, found {len(matches)}",
    )
    return matches[0]


def _find_assignment(function: ast.FunctionDef, name: str, claim: str) -> ast.AST:
    matches: list[ast.AST] = []
    for node in ast.walk(function):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id == name:
            matches.append(node.value)
    _require(
        len(matches) == 1,
        f"{claim}: recorder assignment {name} must resolve uniquely, found {len(matches)}",
    )
    return matches[0]


def _dict_value(node: ast.AST, key: str, claim: str) -> ast.AST:
    _require(
        isinstance(node, ast.Dict),
        f"{claim}: expected a concrete dictionary while resolving {key}",
    )
    matches: list[ast.AST] = []
    for key_node, value_node in zip(node.keys, node.values):
        if isinstance(key_node, ast.Constant) and key_node.value == key:
            matches.append(value_node)
    _require(
        len(matches) == 1,
        f"{claim}: dictionary key {key} must resolve uniquely, found {len(matches)}",
    )
    return matches[0]


def test_native_class_loadout_goldens_are_live_settled_and_participant_owned() -> str:
    fixture = _read_json(FIXTURE_PATH, CLAIM_LIVE)
    header = fixture.get("header")
    _require(isinstance(header, dict), f"{CLAIM_LIVE}: fixture has no provenance header")
    _require(
        header.get("schema") == "solomon-dark-class-loadout-goldens-v1",
        f"{CLAIM_LIVE}: fixture schema no longer identifies class-loadout recordings",
    )
    source = header.get("source") or {}
    _require(
        source.get("base_commit") == "c36f0a81721fa5d3dc2edda65f3347354974b2f0"
        and source.get("branch") == "main"
        and source.get("dirty") is False,
        f"{CLAIM_LIVE}: recorder provenance must name its exact clean source revision",
    )
    committed_hashes = source.get("committed_file_hashes")
    _require(
        isinstance(committed_hashes, dict)
        and set(committed_hashes) == EXPECTED_COMMITTED_HASH_PATHS,
        f"{CLAIM_LIVE}: committed-hash sweep must reach every recorder input exactly once",
    )
    for relative_path in sorted(EXPECTED_COMMITTED_HASH_PATHS):
        record = committed_hashes[relative_path]
        _require(
            isinstance(record, dict) and set(record) == {"sha256"},
            f"{CLAIM_LIVE}: {relative_path} committed hash record has an ambiguous shape",
        )
        assert_recorded_hash_matches_file(
            record["sha256"],
            ROOT / relative_path,
            f"class-loadout committed source {relative_path}",
        )

    capture_header = header.get("capture") or {}
    _require(
        capture_header.get("class_count") == 15
        and capture_header.get("instance_namespace") == "load-*"
        and capture_header.get("udp_ports") == [52411, 52412]
        and capture_header.get("audio_disabled") is True,
        f"{CLAIM_LIVE}: capture header no longer pins the complete isolated instance envelope",
    )
    _require(
        capture_header.get("settle_gate")
        == {
            "minimum_consecutive_samples": 40,
            "minimum_span_seconds": 2.0,
            "structural_payload": (
                "actor mapping, every stat, all 83 rows, raw regions, inventory, "
                "equipment, and participant-owned ledgers; ticks and the named "
                "progression+0x88C runtime counter excluded"
            ),
        },
        f"{CLAIM_LIVE}: provenance header no longer states the complete settle payload and exclusions",
    )
    _require(
        (header.get("native_binary") or {}).get("sha256")
        == "03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3",
        f"{CLAIM_LIVE}: retail binary provenance no longer pins the analyzed executable",
    )
    loader = header.get("loader") or {}
    expected_loader_hash = "db14aaf55da2b6939ca5702227698e3eecf9eee5b0d43cdd430dcdd3a6ca5852"
    _require(
        loader.get("release_sha256") == expected_loader_hash
        and loader.get("launcher_staged_sha256") == expected_loader_hash
        and loader.get("loaded_module_sha256") == expected_loader_hash,
        f"{CLAIM_LIVE}: release, staged, and actually loaded DLL provenance must agree",
    )

    captures = _unique_index(
        fixture.get("captures"),
        "class_key",
        EXPECTED_CLASS_KEYS,
        CLAIM_LIVE,
        "settled live capture census",
    )
    _require(
        set(EXPECTED_EXTERNAL_EVIDENCE_HASHES) == set(EXPECTED_CLASS_KEYS),
        f"{CLAIM_LIVE}: external evidence constants do not witness every selectable class",
    )
    for index, class_key in enumerate(EXPECTED_CLASS_KEYS, start=1):
        capture = captures[class_key]
        _validate_settle_gate(capture, class_key)
        provenance = capture.get("run_provenance")
        _require(
            isinstance(provenance, dict)
            and provenance.get("instance") == f"load-gold-{index:02d}-{class_key}"
            and provenance.get("udp_ports") == [52411, 52412]
            and provenance.get("audio_disabled") is True
            and provenance.get("cleanup_proved") is True,
            f"{CLAIM_LIVE}: {class_key} run receipt no longer proves its isolated launch and cleanup",
        )
        _require(
            provenance.get("evidence_sha256")
            == EXPECTED_EXTERNAL_EVIDENCE_HASHES[class_key],
            f"{CLAIM_LIVE}: {class_key} external evidence hash drifted from its provenance constant",
        )
        loaded = provenance.get("loaded_loader") or {}
        _require(
            loaded.get("sha256") == expected_loader_hash
            and loaded.get("path")
            == "D:\\sd-loadre-20260805\\dist\\launcher\\SolomonDarkModLoader.dll"
            and "SolomonDarkModLoader attached." in loaded.get("attachment_receipt", "")
            and "Build flavor: Release." in loaded.get("release_receipt", "")
            and "[lua-exec-pipe] server started." in loaded.get("lua_exec_receipt", ""),
            f"{CLAIM_LIVE}: {class_key} lacks an end-to-end receipt for the actually running loader",
        )

    mixed = fixture.get("mixed_participant_case")
    _require(isinstance(mixed, dict), f"{CLAIM_LIVE}: mixed-class case is absent")
    _require(
        mixed.get("case_key") == "fire-mind-local__earth-body-bot"
        and mixed.get("local_class_key") == "fire-mind"
        and mixed.get("bot_class_key") == "earth-body",
        f"{CLAIM_LIVE}: mixed case no longer witnesses Fire/Mind beside Earth/Body",
    )
    local = mixed.get("local_after_bot")
    bot = mixed.get("bot")
    _require(
        isinstance(local, dict) and isinstance(bot, dict),
        f"{CLAIM_LIVE}: mixed case lacks both concrete participant snapshots",
    )
    _validate_settle_gate(local, "mixed local Fire/Mind")
    _validate_settle_gate(bot, "mixed Earth/Body bot")
    local_snapshot = local["first_complete_controllable_snapshot"]
    bot_snapshot = bot["first_complete_controllable_snapshot"]
    local_stats = local_snapshot["stats"]
    _require(
        {
            "element_skill_row": local_stats["element_skill_row"]["value"],
            "discipline_skill_row": local_stats["discipline_skill_row"]["value"],
            "primary_skill_row": local_stats["primary_skill_row"]["value"],
            "secondary_skill_row": local_stats["secondary_skill_row"]["value"],
        }
        == {
            "element_skill_row": 1,
            "discipline_skill_row": 6,
            "primary_skill_row": 16,
            "secondary_skill_row": 21,
        },
        f"{CLAIM_LIVE}: mixed local actor no longer retains the Fire/Mind selector quartet",
    )
    bot_profile = bot_snapshot.get("bot_profile") or {}
    _require(
        bot_profile
        == {
            "appearance_choice_ids": [-1, -1, -1, -1],
            "discipline_id": 1,
            "element_id": 2,
            "experience": 0,
            "level": 1,
            "loadout": {
                "primary_combo_entry_index": -1,
                "primary_entry_index": -1,
                "secondary_entry_indices": [-1] * 8,
            },
        },
        f"{CLAIM_LIVE}: bot profile no longer records the semantic-only Earth/Body assignment path",
    )
    bot_stats = bot_snapshot["stats"]
    _require(
        {
            "element_skill_row": bot_stats["element_skill_row"]["value"],
            "discipline_skill_row": bot_stats["discipline_skill_row"]["value"],
            "primary_skill_row": bot_stats["primary_skill_row"]["value"],
            "secondary_skill_row": bot_stats["secondary_skill_row"]["value"],
            "current_spell_id": bot_stats["current_spell_id"]["value"],
            "nonlocal_mode_flag": bot_stats["nonlocal_mode_flag"]["value"],
        }
        == {
            "element_skill_row": -1,
            "discipline_skill_row": 5,
            "primary_skill_row": -1,
            "secondary_skill_row": -1,
            "current_spell_id": 1014,
            "nonlocal_mode_flag": 1,
        },
        f"{CLAIM_LIVE}: bot actor no longer follows the observed semantic-only native priming result",
    )
    bot_entries = bot_snapshot["progression_book"]["entries"]
    _require(
        isinstance(bot_entries, list)
        and [row.get("entry_index") for row in bot_entries] == list(range(83)),
        f"{CLAIM_LIVE}: mixed bot book sweep did not reach all 83 native rows",
    )
    bot_active = {
        row["entry_index"]
        for row in bot_entries
        if row.get("base_rank_u16") == 1 and row.get("effective_rank_u16") == 1
    }
    _require(
        bot_active == set(range(8)) | {40},
        f"{CLAIM_LIVE}: semantic-only Earth/Body bot must activate roots 0..7 and Earth primary 40 only",
    )
    local_entity = local_snapshot["entity"]
    bot_entity = bot_snapshot["entity"]
    independence = mixed.get("independence")
    _require(
        independence
        == {
            "distinct_actor_addresses": True,
            "distinct_progression_addresses": True,
            "distinct_progression_book_addresses": True,
            "local_book_unchanged_by_bot_creation": True,
        },
        f"{CLAIM_LIVE}: mixed case no longer declares every per-participant ownership consequence",
    )
    _require(
        local_entity["actor_address"] != bot_entity["actor_address"]
        and local_entity["progression_address"] != bot_entity["progression_address"]
        and local_entity["progression_book_address"]
        != bot_entity["progression_book_address"],
        f"{CLAIM_LIVE}: mixed participants share an actor, progression object, or native book address",
    )
    _require(
        local_snapshot["observed"]["participant_count"] == 2
        and bot_snapshot["observed"]["participant_count"] == 2,
        f"{CLAIM_LIVE}: mixed case snapshots do not both witness two materialized participants",
    )
    local_digest = _class_state_digest(local_snapshot)
    _require(
        mixed.get("local_before_bot_class_state_sha256")
        == mixed.get("local_after_bot_class_state_sha256")
        == local_digest
        == "30a78c75598dc813c3a8087a75b8f478f17d808713a67e0a9b4b0fbdeb24ff22",
        f"{CLAIM_LIVE}: bot creation changed the local participant's class-state digest",
    )
    _require(
        bot_snapshot["native_inventory"].get("item_count") == 0
        and bot_snapshot["native_inventory"].get("items") == []
        and bot_snapshot["participant"]["owned_progression"].get("book_entry_count")
        == 0
        and bot_snapshot["participant"]["owned_progression"].get("initialized")
        is True,
        f"{CLAIM_LIVE}: semantic-only bot no longer preserves the observed empty mirrored inventory/book ledger",
    )
    bot_slots = bot_snapshot["participant"]["equipment"]["slots"]
    _require(
        bot_slots["primary"]["type_id"] == 7006
        and bot_slots["secondary"]["type_id"] == 7005
        and bot_slots["attachment"]["type_id"] == 7004
        and bot_slots["hat"]["type_id"] == 0
        and bot_slots["robe"]["type_id"] == 0
        and bot_slots["weapon"]["type_id"] == 0,
        f"{CLAIM_LIVE}: mixed bot visual lanes no longer pin robe/hat/staff without named local equip slots",
    )
    doc = _read_text(DOC_PATH, CLAIM_LIVE)
    mixed_doc_tokens = (
        "The fixture case `fire-mind-local__earth-body-bot` creates a local Fire/Mind\nactor and then a semantic Earth/Body bot in the same Courtyard",
        "bot progression `+0x82C=-1`, `+0x830=5`, `+0x86C=-1`, `+0x870=-1`",
        "Do not force the local Create finalizer's four-field result onto this bot path.",
        "local class-state digest is\n`321b985680a62e89e16e619b53d11f044d5c1147b7dbbfd0cd58f9e1e0a3acdb`\nboth before and after bot creation.",
    )
    for token in mixed_doc_tokens:
        _require(
            token in doc,
            f"{CLAIM_LIVE}: implementation document lost the mixed-participant consequence expressed by {token!r}",
        )

    recorder_source = _read_text(RECORDER_PATH, CLAIM_LIVE)
    tree = ast.parse(recorder_source, filename=str(RECORDER_PATH))
    main = _find_function(tree, "main", CLAIM_LIVE)
    add_argument_calls = [
        node
        for node in ast.walk(main)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "parser"
        and node.func.attr == "add_argument"
    ]
    _require(
        len(add_argument_calls) == 4,
        f"{CLAIM_LIVE}: recorder CLI must expose exactly four operational arguments, found {len(add_argument_calls)}",
    )
    options = [
        call.args[0].value
        for call in add_argument_calls
        if call.args and isinstance(call.args[0], ast.Constant)
    ]
    _require(
        options == ["--output", "--evidence-directory", "--game-directory", "--overwrite"],
        f"{CLAIM_LIVE}: recorder CLI added, removed, or reordered an option and may now accept provenance overrides",
    )
    revision_assignment = _find_assignment(main, "revision", CLAIM_LIVE)
    _require(
        ast.unparse(revision_assignment) == "source_revision()",
        f"{CLAIM_LIVE}: recorder no longer derives its revision from the checkout",
    )
    header_assignment = _find_assignment(main, "header", CLAIM_LIVE)
    source_dict = _dict_value(header_assignment, "source", CLAIM_LIVE)
    native_binary_dict = _dict_value(header_assignment, "native_binary", CLAIM_LIVE)
    loader_dict = _dict_value(header_assignment, "loader", CLAIM_LIVE)
    _require(
        ast.unparse(_dict_value(source_dict, "base_commit", CLAIM_LIVE))
        == "revision['sha']"
        and ast.unparse(_dict_value(source_dict, "dirty", CLAIM_LIVE))
        == "revision['dirty']"
        and ast.unparse(
            _dict_value(source_dict, "committed_file_hashes", CLAIM_LIVE)
        )
        == "committed_source_hashes()",
        f"{CLAIM_LIVE}: source provenance is not derived directly by the recorder",
    )
    _require(
        ast.unparse(_dict_value(native_binary_dict, "sha256", CLAIM_LIVE))
        == "sha256_file(executable)",
        f"{CLAIM_LIVE}: retail executable provenance is no longer hashed by the recorder",
    )
    _require(
        ast.unparse(_dict_value(loader_dict, "release_sha256", CLAIM_LIVE))
        == "sha256_file(RELEASE_LOADER)"
        and ast.unparse(
            _dict_value(loader_dict, "launcher_staged_sha256", CLAIM_LIVE)
        )
        == "sha256_file(STAGED_LOADER)"
        and ast.unparse(
            _dict_value(loader_dict, "loaded_module_sha256", CLAIM_LIVE)
        )
        == "next(iter(loaded_loader_hashes))",
        f"{CLAIM_LIVE}: loader provenance no longer derives release, staged, and live hashes independently",
    )
    runnable_probe = _find_function(tree, "wait_for_lua_runnable", CLAIM_LIVE)
    runnable_text = ast.unparse(runnable_probe)
    runnable_lua_calls = [
        node
        for node in ast.walk(runnable_probe)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "lua"
    ]
    runnable_process_checks = [
        node
        for node in ast.walk(runnable_probe)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "require_live_owned_process"
    ]
    _require(
        len(runnable_lua_calls) == 1 and len(runnable_process_checks) == 1,
        f"{CLAIM_LIVE}: Lua readiness must run one real query and recheck the exact owned process on retry",
    )
    _require(
        "BROKEN: Lua exec probe ran but failed:" in runnable_text
        and "BUSY: Lua exec pipe never became ready:" in runnable_text,
        f"{CLAIM_LIVE}: Lua readiness no longer distinguishes terminal breakage from retryable busy state",
    )
    settle_probe = _find_function(tree, "capture_settled_snapshot", CLAIM_LIVE)
    settle_text = ast.unparse(settle_probe)
    settle_process_checks = [
        node
        for node in ast.walk(settle_probe)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "require_live_owned_process"
    ]
    retry_classifiers = [
        node
        for node in ast.walk(settle_probe)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_is_retryable_pipe_failure"
    ]
    _require(
        len(settle_process_checks) == 2 and len(retry_classifiers) == 1,
        f"{CLAIM_LIVE}: snapshot readiness must check liveness on both retry paths and classify pipe failures once",
    )
    _require(
        "BROKEN: class snapshot probe failed:" in settle_text
        and "BUSY: class initialization never became complete:" in settle_text,
        f"{CLAIM_LIVE}: snapshot readiness no longer reports broken and busy as distinct outcomes",
    )
    return "all goldens are self-provenanced, structurally settled, cleaned, and participant-independent"
