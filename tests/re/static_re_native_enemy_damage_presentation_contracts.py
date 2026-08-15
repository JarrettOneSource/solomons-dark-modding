"""Static contract for the complete native enemy-damage presenter census."""

from __future__ import annotations

import json

from static_re_contract_support import ROOT, StaticReTestFailure, read_text


REPORT = ROOT / "docs/reverse-engineering/native-enemy-hit-and-death-effects.md"
ENEMY_CATALOG = ROOT / "docs/reverse-engineering/native-enemy-catalog.json"
AUDIO_CATALOG = ROOT / "docs/reverse-engineering/native-audio-catalog.json"


def _require_tokens(text: str, tokens: tuple[str, ...]) -> None:
    missing = [token for token in tokens if token not in text]
    if missing:
        raise StaticReTestFailure(
            "native enemy-damage report is missing contract token(s): "
            + ", ".join(missing)
        )


def test_native_enemy_damage_presenter_contract_is_pinned() -> str:
    report = read_text(REPORT)
    _require_tokens(
        report,
        (
            "actual polymorphic seam is enemy `vtable +0x4C`",
            "`0x0048A290`",
            "`0x0048A600`",
            "`0x0048B1E0`",
            "`0x0048B1C0`",
            "`0x0048BC80`",
            "`0x0048BCE0`",
            "`0x0048C370`",
            "receiver `0x00607F60`",
            "entry 12, `+0x228`",
            "entry 107, `+0x127C`",
            "first eligible lethal hit still plays its hurt cue",
            "the breaking hit does **not** overflow into health",
            "entry 42 (`+0x750`)",
            "cooldown `10` plus pulse `2.0`",
            "entry 74 (`+0xCD0`)",
            "exactly twenty",
            "BadGuys record 69",
            "initial alpha = 0.5 + U[0,0.75)",
            "uniform scale = 1.5 + U[0,0.25)",
            "BadGuys record 49",
            "scale = 1.5 + 0.1 * sin(worldTick * 20 degrees) * wobble",
            "The finite Website recipient set is therefore Mage self plus Skeleton, Archer,\n"
            "and Zombie allies",
            "Skeleton `0x3E9`",
            "SkeletonArcher `0x3EA`",
            "Zombie `0x3EE`",
            "only then does `0x0047FE8B` call the\napplication helper",
            "rank-one target-contact sound request",
            "target-local hit\n  sprite or sound request",
            "`rockhit` request at `0x0062141B` is not attached",
        ),
    )
    return (
        "enemy damage is partitioned into common body hit, family hurt cue, "
        "shield absorb/break, and negative projectile-contact dispositions"
    )


def test_enemy_damage_receiver_slot_membership_matches_finite_catalog() -> str:
    catalog = json.loads(ENEMY_CATALOG.read_text(encoding="utf-8"))
    slots = {
        row["name"]: row.get("selected_vtable_slots", {}).get("0x4C")
        for row in catalog["enemies"]
        if "0x4C" in row.get("selected_vtable_slots", {})
    }
    expected = {
        "Badguy": "0x0048A290",
        "Skeleton": "0x0048A600",
        "SkeletonArcher": "0x0048A600",
        "SkeletonMage": "0x0048A600",
        "Imp": "0x0048B1C0",
        "GoodImp": "0x0048B1C0",
        "Zombie": "0x0048B1E0",
        "Wraith": "0x0048B290",
        "DemonSkull": "0x0048A290",
        "Demon": "0x0048A290",
        "DireFaculty": "0x0048A600",
        "Heartmonger": "0x0048A600",
        "Coffin": "0x0048A290",
        "GreenImp": "0x0048B1C0",
        "Maggot": "0x0048A290",
        "Spider": "0x0048BC80",
        "Cocoon": "0x0048BCE0",
        "Portal": "0x0048C370",
    }
    if slots != expected:
        raise StaticReTestFailure(
            f"enemy +0x4C damage-receiver census drifted: {slots}"
        )
    return "all 18 Badguy-derived receiver slots match the finite native class catalog"


def test_enemy_damage_audio_identity_is_exact() -> str:
    catalog = json.loads(AUDIO_CATALOG.read_text(encoding="utf-8"))
    wanted = {
        "sounds\\bonecrack": (12, "0x00000228", "9b42d96a3d505cc1d631d43b6fde4b7fb9670ed2fa758a7692207f2c514047c4"),
        "sounds\\hitshield": (42, "0x00000750", "ad5a4870955e5393c17a03c847af274f7a054b62a4c712582206623d1d92ad3f"),
        "sounds\\popshield": (74, "0x00000CD0", "b4d6bf4d9a68f11bab92def6e823a53f6b8534c49b96e80bbf25d99972af2503"),
        "sounds\\zombieouch": (107, "0x0000127C", "db5400fa0d40ec3507d56d6d29c77ca23dfff4686abe97193b13945da0772d32"),
    }
    actual = {}
    for row in catalog["compiled_registry"]:
        path = row["path_without_extension"]
        if path in wanted:
            actual[path] = (
                row["registry_index"],
                row["registry_member_offset"],
                row["file"]["sha256"],
            )
    if actual != wanted:
        raise StaticReTestFailure(
            f"enemy damage audio registry identity drifted: {actual}"
        )
    return "all four enemy hurt/shield WAVs retain exact registry identity and hashes"
