"""Static contracts for selected-skill HUD buttons and Skills_Quickbar selectors."""

from __future__ import annotations

import json

from static_re_contract_support import ROOT, StaticReTestFailure


HUD_DOC = ROOT / "docs/reverse-engineering/native-hud.md"
SKILL_DOC = ROOT / "docs/reverse-engineering/native-skill-screen-and-quickbar.md"
SETTINGS_DOC = ROOT / "docs/reverse-engineering/native-settings-system.md"
CLASS_CATALOG = ROOT / "docs/reverse-engineering/native-class-catalog.json"
AUDIO_CATALOG = ROOT / "docs/reverse-engineering/native-audio-catalog.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise StaticReTestFailure(message)


def class_row(catalog: dict[str, object], name: str) -> dict[str, object]:
    rows = [row for row in catalog["classes"] if row["name"] == name]
    require(len(rows) == 1, f"class catalog lost unique {name} ownership")
    return rows[0]


def slot_function(row: dict[str, object], offset: str) -> tuple[str, str]:
    slots = [slot for slot in row["slots"] if slot["offset"] == offset]
    require(len(slots) == 1, f"{row['name']} lost unique vtable slot {offset}")
    return slots[0]["function"], slots[0]["name"]


def test_native_hud_skill_selector_ownership_geometry_and_audio_are_pinned() -> str:
    hud = HUD_DOC.read_text(encoding="utf-8")
    skill = SKILL_DOC.read_text(encoding="utf-8")
    settings = SETTINGS_DOC.read_text(encoding="utf-8")
    classes = json.loads(CLASS_CATALOG.read_text(encoding="utf-8"))
    audio = json.loads(AUDIO_CATALOG.read_text(encoding="utf-8"))

    for marker in (
        "Selected-skill hit targets and compact selectors",
        "`+0x3AC/+0x46C/+0x52C`",
        "exactly `40 x 65`",
        "`y=[-7,58)`",
        "`[760,800,840]`",
    ):
        require(marker in hud, f"native HUD report lost selector marker {marker}")

    for marker in (
        "Selected-skill HUD controls and selector modal",
        "`0x00657A70`",
        "`0x0066F0B0`",
        "`0x0066F330`",
        "`0x00659AD0`",
        "one horizontal `52 x 52` cell",
        "top is `74`",
        "height `79`",
        r"`sounds\\concentrate`",
        "`57..63,65..71`",
        "Category `3` remains non-draggable but its card selects the first concentration",
    ):
        require(marker in skill, f"native skill-selector report lost marker {marker}")

    game = class_row(classes, "Game")
    panel = class_row(classes, "MyCPanel")
    require(
        slot_function(game, "0x10") == ("0x005D8120", "Game_HandleControlAction"),
        "Game vslot +0x10 no longer owns the HUD control callback",
    )
    require(
        slot_function(panel, "0x10")[0] == "0x00434C60",
        "MyCPanel vslot +0x10 was conflated with the Game HUD callback",
    )
    require(
        "The skill selectors are therefore\nHUD members, not Settings rows" in settings,
        "Settings report lost the corrected HUD ownership boundary",
    )

    entries = {entry["registry_index"]: entry for entry in audio["compiled_registry"]}
    require(entries[0]["path_without_extension"] == "sounds\\click", "registry 0 is not click")
    require(
        entries[17]["path_without_extension"] == "sounds\\concentrate"
        and entries[17]["registry_member_offset"] == "0x00000304",
        "registry 17 concentrate identity drifted",
    )
    return "selected-skill HUD buttons, compact selector, slot routing, and audio are pinned"


if __name__ == "__main__":
    print(test_native_hud_skill_selector_ownership_geometry_and_audio_are_pinned())
