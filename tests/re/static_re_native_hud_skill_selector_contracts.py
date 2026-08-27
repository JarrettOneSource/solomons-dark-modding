"""Static contracts for selected-skill HUD buttons and Skills_Quickbar selectors."""

from __future__ import annotations

import json

from static_re_contract_support import ROOT, StaticReTestFailure


HUD_DOC = ROOT / "docs/reverse-engineering/native-hud.md"
SKILL_DOC = ROOT / "docs/reverse-engineering/native-skill-screen-and-quickbar.md"
SETTINGS_DOC = ROOT / "docs/reverse-engineering/native-settings-system.md"
CLASS_CATALOG = ROOT / "docs/reverse-engineering/native-class-catalog.json"
AUDIO_CATALOG = ROOT / "docs/reverse-engineering/native-audio-catalog.json"
GATE_DOC = ROOT / "docs/reverse-engineering/native-gate-art-and-lifecycle.md"
TUTORIAL_DOC = ROOT / "docs/re/tutorial-mechanics.md"


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


def test_native_skill_screen_ambient_seal_motion_is_pinned() -> str:
    skill = SKILL_DOC.read_text(encoding="utf-8")
    for marker in (
        "2026-08-25 ambient-seal motion correction",
        "`x = 800 + 40*sin(2*theta*pi/180)`",
        "`theta - screenTick/60`",
        "`+0x20 -> 0x00427800`",
        "`_CIsin 0x007470D0`",
        "no RNG call, seed, cursor, or time value participates",
        "resets on every\nSkillScreen construction",
        "frame `211 x 94`, trim\norigin `(405,108)`",
    ):
        require(marker in skill, f"native SkillScreen seal report lost marker {marker}")
    return "SkillScreen ambient seals retain deterministic sine placement and local phase"


def test_native_skilldragger_threshold_hit_presentation_and_audio_are_pinned() -> str:
    skill = SKILL_DOC.read_text(encoding="utf-8")
    classes = json.loads(CLASS_CATALOG.read_text(encoding="utf-8"))
    audio = json.loads(AUDIO_CATALOG.read_text(encoding="utf-8"))
    for marker in (
        "2026-08-26 corrective SkillDragger closure",
        "`0x0078473C = 9`",
        "`0x007849B0 = 40`",
        "`0x00784D58 = 1.25`",
        "Skills record\n  `164`",
        "strictly greatest\n  positive overlap area",
        "A rejected drop mutates nothing and is\n  silent",
        "same live HUD rectangles moved by modal writer\n  `0x005C7200`",
    ):
        require(marker in skill, f"native SkillDragger report lost marker {marker}")
    dragger = class_row(classes, "SkillDragger")
    require(
        slot_function(dragger, "0x0C")[0] == "0x0065E4D0",
        "SkillDragger lost its pointer render owner",
    )
    require(
        slot_function(dragger, "0x6C")[0] == "0x006564A0",
        "SkillDragger lost its release owner",
    )
    entries = {entry["registry_index"]: entry for entry in audio["compiled_registry"]}
    require(
        entries[1]["path_without_extension"] == "sounds\\pickskill",
        "SkillDragger accepted-drop audio is not registry entry 1 pickskill",
    )
    return "SkillDragger threshold, moving art, overlap hit, audio, and teardown are pinned"


def test_native_beltbutton_pull_off_release_and_burst_are_pinned() -> str:
    skill = SKILL_DOC.read_text(encoding="utf-8")
    classes = json.loads(CLASS_CATALOG.read_text(encoding="utf-8"))
    audio = json.loads(AUDIO_CATALOG.read_text(encoding="utf-8"))
    for marker in (
        "2026-08-26 corrective BeltButton pull-off closure",
        "strict threshold `length > 50.0`",
        "release-callback byte\n  `+0x7B = 1`",
        "press-callback byte `+0x7C = 0`",
        "exactly 24 UI-record-65 bouncers",
        "four or three moving/fading\n  UI-record-69 members",
        "There is no stock\nbelt-to-belt move operation",
    ):
        require(marker in skill, f"native BeltButton pull-off report lost marker {marker}")
    belt = class_row(classes, "BeltButton")
    require(
        slot_function(belt, "0x68")[0] == "0x005C7DF0",
        "BeltButton lost its pressed-movement pull-off owner",
    )
    entries = {entry["registry_index"]: entry for entry in audio["compiled_registry"]}
    require(
        entries[73]["path_without_extension"] == "sounds\\poof",
        "BeltButton pull-off audio is not registry entry 73 poof",
    )
    return "BeltButton release-only activation, strict pull-off, poof, and complete burst are pinned"


def test_tutorial_camera_enemy_and_gate_contact_memberships_are_pinned() -> str:
    gate = GATE_DOC.read_text(encoding="utf-8")
    tutorial = TUTORIAL_DOC.read_text(encoding="utf-8")
    for marker in (
        "2026-08-26 Gate contact membership correction",
        "`PlayerWizard` constructor `0x0052B4C0` writes flags `0x801`",
        "Common Badguy constructor\n  `0x00473390` writes flags `0x2`",
        "`0x80 & 0x100 == 0`",
        "active for enemies even though they cannot push the leaf",
    ):
        require(marker in gate, f"native Gate report lost hostile-contact marker {marker}")
    for marker in (
        "2026-08-26 live-enemy transition correction",
        "no branch changes player or enemy movement bounds",
        "no branch relocates, retires, damages, or retargets a live Badguy",
        "keep the full\nTutorial camera active whenever any registered enemy circle or ground Sack",
        "it neither teleports nor deletes an actor",
    ):
        require(marker in tutorial, f"Tutorial report lost live-enemy camera marker {marker}")
    return "Tutorial camera cleanup and asymmetric player/enemy Gate contact are pinned"


def test_tutorial_sirmin_wardrobe_override_is_pinned() -> str:
    tutorial = TUTORIAL_DOC.read_text(encoding="utf-8")
    for marker in (
        "## 2026-08-27 Sirmin wardrobe override",
        "`Game+0x1428` at `0x005D5DA1..0x005D5DA9`",
        "`Game+0x142C` at `0x005D5E0E..0x005D5E16`",
        "`(1,0.5,0,1)`",
        "`0.6000000238418579`",
        "primary wearable color at item `+0x88..+0x94`",
        "There is no RNG draw in this override",
        "secondary colors remain exact white",
        "tan/orange Sirmin wardrobe with the independent purple Ether effect",
        "disposable Tutorial player generation",
    ):
        require(marker in tutorial, f"Tutorial Sirmin wardrobe report lost marker {marker}")
    return "Tutorial Hat/Robe tan override and independent Ether Staff effect are pinned"


if __name__ == "__main__":
    print(test_native_hud_skill_selector_ownership_geometry_and_audio_are_pinned())
