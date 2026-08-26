"""Static contracts for the G9 native retail HUD reconstruction."""

from __future__ import annotations

import ast
import json
import math
import re
from pathlib import Path
from typing import Any

from static_re_contract_support import ROOT, StaticReTestFailure


DOC_PATH = ROOT / "docs/reverse-engineering/native-hud.md"
GOLDEN_PATH = ROOT / "tests/fixtures/webgame/hud-goldens.json"
RECORDER_PATH = ROOT / "tools/record_native_hud_goldens.py"
SHARED_SOLO_RECORDER_PATH = ROOT / "tools/record_native_sim_goldens.py"
HUD_HOOK_PATH = (
    ROOT
    / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/gameplay_hud_hooks.inl"
)
SCENE_CAPTURE_PATH = ROOT / "SolomonDarkModLoader/src/native_scene_capture.cpp"
SCENE_CAPTURE_HOOKS_PATH = (
    ROOT / "SolomonDarkModLoader/src/native_scene_capture/hooks.inl"
)
SCENE_CAPTURE_OBSERVATION_PATH = (
    ROOT / "SolomonDarkModLoader/src/native_scene_capture/observation.inl"
)
SCENE_CAPTURE_PUBLIC_API_PATH = (
    ROOT / "SolomonDarkModLoader/src/native_scene_capture/public_api.inl"
)
BINARY_LAYOUT_PATH = ROOT / "config/binary-layout.ini"


EXPECTED_ELEMENT_ROWS = (
    '| 1 | `cast.primary.card` | `[730.5,825,793.5,892]` | center-bottom; base is `[730.5,825,788.5,887]`, black shadow is `+5,+5` | `UI.47` (Manifest) | none | `0..1` shadow then base | `0x005D2520`, `0x005D3E10` |',
    '| 2 | `cast.secondary.card` | `[810.5,825,873.5,892]` | center-bottom; base is `[810.5,825,868.5,887]`, black shadow is `+5,+5` | `UI.48` (Manifest) | none | `2..3` shadow then base | `0x005D2520`, `0x005D3E10` |',
    '| 3 | `belt.slot.0` | visual `[473.5,840.5,515.5,877.5]`; logical `[468,832.5,521,885.5]` | center-bottom; first position of 60 px pitch; 53 x 53 logical box | `Skills.72` (Native `images/Skills.bundle`, record 72) | none | `4` | `0x005D3E10` |',
    '| 4 | `belt.slot.1` | logical `[528,832.5,581,885.5]` | center-bottom; 60 px pitch | no draw | none | none | `0x005D3E10` |',
    '| 5 | `belt.slot.2` | logical `[588,832.5,641,885.5]` | center-bottom; 60 px pitch | no draw | none | none | `0x005D3E10` |',
    '| 6 | `belt.slot.3` | visual `[648,834,706,889]`; logical `[648,832.5,701,885.5]` | center-bottom; shadow is `+5,+5` | `Inventory.46` (Native `images/Inventory.bundle`, record 46) | none | `6..7` shadow then base | `0x005D3E10` |',
    '| 7 | `belt.slot.4` | visual `[899.5,834.5,954.5,888.5]`; logical `[898,832.5,951,885.5]` | center-bottom; right bank resumes after XP/cast center gap; shadow is `+5,+5` | `Inventory.47` (Native `images/Inventory.bundle`, record 47) | none | `12..13` shadow then base | `0x005D3E10` |',
    '| 8 | `belt.slot.5` | logical `[958,832.5,1011,885.5]` | center-bottom; 60 px pitch | no draw | none | none | `0x005D3E10` |',
    '| 9 | `belt.slot.6` | logical `[1018,832.5,1071,885.5]` | center-bottom; 60 px pitch | no draw | none | none | `0x005D3E10` |',
    '| 10 | `belt.slot.7` | logical `[1078,832.5,1131,885.5]` | center-bottom; 60 px pitch | no draw | none | none | `0x005D3E10` |',
    '| 11 | `belt.slot.0.input_hint` | authored `[483.5,877,505.5,908]`; clipped `[483.5,877,505.5,900]` | centered below slot 0; the bottom 8 px intentionally leave the viewport | `UI.100` (Manifest) | none | `5` | `0x005D3E10` |',
    '| 12 | `belt.slot.3.input_hint` | glyph `[671,888,679,897]`; backing glyph strip spans `[667.5,885,680.5,900]` | centered below slot 3 | `UI.22` backing (Native) plus `Fonts.535-626@0x2A4C` | `Fonts` group 8, header `[10,3,28]`, measured line height 9 px; default Health-Potion binding `3` is 8 px wide | `8..11` | `0x005D3E10`, `0x004A57C0`, `0x00415230`, `0x004299F0` |',
    '| 13 | `belt.slot.4.input_hint` | glyph `[920,888,930,897]`; backing glyph strip spans `[917.5,885,930.5,900]` | centered below slot 4 | `UI.22` backing (Native) plus `Fonts.535-626@0x2B20` | same group/header/9 px line; default Mana-Potion binding `4` is 10 px wide | `14..17` | `0x005D3E10`, `0x004A57C0`, `0x00415230`, `0x004299F0` |',
    '| 14 | `progression.xp.fill` | maximum `[798,833,802,881]`; live 45/90 clip `[798,857,802,881]` | center-bottom; 4 x 48 maximum, bottom-fixed at `y=881`, grows upward | `UI.81` (Native `images/UI.bundle`, record 81; UI object `+0x3E3C`) | none | `18` | `0x005D2B0C`, `0x00414D00` |',
    '| 15 | `progression.xp.track` | `[794.5,829,806.5,885]` | center-bottom; 12 x 56 frame centered at `x=800`, bottom inset 15 | `UI.82` (Manifest) | none | `19` | `0x005D2B0C`, `0x004142E0` |',
    '| 16 | `mana.track` | baseline `[850,14.5,960,34.5]`; dynamic width | center-top; left edge fixed at `center+50`, grows right | `UI.70` (Native `images/UI.bundle`, record 70) | none | `20..22` | `0x005D2520`, `0x00415230`, `0x00420EC0` |',
    '| 17 | `mana.fill` | baseline maximum `[855,19.5,955,29.5]`; dynamic width | center-top; left edge fixed at `center+55`, left-clipped | `UI.40` (Native `images/UI.bundle`, record 40) | none | `23..25` | `0x005D2520`, `0x00415230`, `0x00420EC0` |',
    '| 18 | `health.track` | baseline `[640,14.5,750,34.5]`; dynamic width | center-top; right edge fixed at `center-50`, grows left | `UI.70` (Native record 70) | none | `26..28` | `0x005D2520`, `0x00415230`, `0x00420EC0` |',
    '| 19 | `health.fill` | baseline maximum `[645,19.5,745,29.5]`; dynamic width | center-top; right edge fixed at `center-55`; content remains left-clipped | `UI.26` (Native `images/UI.bundle`, record 26) | none | `29..31` | `0x005D2520`, `0x00415230`, `0x00420EC0` |',
    '| 20 | `mana.reserve.overlay` | observed 50/100 `[906.5,19.5,954.5,29.5]` | center-top; right-side reserved-capacity segment, right edge approximately `x=955` | `UI.41` (Native `images/UI.bundle`, record 41) | none | conditional `26..32`, before health; later baseline orders shift by 7 | `0x005D2BDD`, `0x00415230` |',
    '| 21 | `health.magic_shield.overlay` | maximum `[645,19.5,745,29.5]` | center-top; independently left-clipped, then width-sorted against life | `UI.26` (Native record 26), cyan tint `(0.5,1,1,1)` | none | conditional three-call strip; shorter of life/shield first, longer last | `0x005D2BDD`, `0x00415230`, `0x00420EC0` |',
    '| 22 | `ally.row.0.identity` | reserved `[612,39,740,46]` | center-top; reservation begins `center-188`; name origin `x=612`, baseline `y=46` in multiplayer | stock `UI.0` (Manifest) or `Fonts.376-442` exact-name replacement | stock `ALLY` art is 26 x 7; multiplayer uses Fonts group 6 at quarter scale with 67 glyph metrics and 1,043 kerning pairs | `32` baseline | `0x005D3408`, `0x005CF480`, `0x004142E0`, loader `0x0043BCD0` |',
    '| 23 | `ally.row.0.health` | maximum `[560,39.5,610,44.5]` | center-top; 50 x 5, left `center-240`; subsequent rows use 10 px pitch | Primitive untextured quad | none | `33` baseline | `0x005D3408`, `0x005CF480`, `0x004142E0` |',
    '| 24 | `skill.binding.12.primary` | baseline Earth `[783.875,9.75,816.125,41.25]`; cluster-dependent center | selected-primary emblem at 0.75 scale/alpha; conditional A/B are child variants of this selected-skill cluster | selected row\'s authored Skills record; Earth is `Skills.67` | none | `34` baseline | `0x005D367A`, `0x0046B140`, `0x00414EA0` |',
    '| 25 | `aim.cursor` | observed `[9.5,8.5,40.5,41.5]` | pointer; 31 x 33 centered on the native mouse point and viewport-clipped | `UI.42` (Manifest) | none | `35`, always in the tail | `0x005D3D48`, `0x004F6070` |',
    '| 26 | `notification.gold` | base `[741,49,860,69]`, shadow `[741,51,860,71]`, union `[741,49,860,71]` | center-top transient stack; shadow offset `(0,+2)` | `Fonts.376-442` (Native bitmap-font group 6) | header `[24,5,28]`; exact string `_s(1)25 GOLD`; measured 119 x 20 per line | transient notification pass, after the main HUD body and before cursor tail | `0x005CA7C0`, `0x005CF000`, `0x004F5620` |',
)

HUD_DOCUMENT_CLAIM = "native HUD document element-table claim"
HUD_ELEMENT_ROW_PATTERN = re.compile(
    r"^\| (?P<number>\d+) \| `(?P<id>[a-z0-9._]+)` \| "
    r"(?P<geometry>[^|\r\n]+?) \| (?P<alignment>[^|\r\n]+?) \| "
    r"(?P<art>[^|\r\n]+?) \| (?P<font>[^|\r\n]+?) \| "
    r"(?P<order>[^|\r\n]+?) \| (?P<owners>[^|\r\n]+?) \|$"
)

EXPECTED_SCENARIOS = (
    "full_health",
    "gold_pickup",
    "damaged_health",
    "near_death_health",
    "magic_shield_health",
    "magic_shield_below_health_fill",
    "mana_drain_and_refill",
    "mana_reserve_overlay",
    "earth_charge_hold",
    "active_cooldown",
    "two_participant_ally_bar",
    "wave_and_score",
    "damage_x4_buff",
    "partial_xp_progress",
    "level_up",
)

EXPECTED_VISIBILITY_STATES = (
    "hub_alive",
    "run_alive",
    "run_alive_featured_enemy",
    "local_death",
    "death_presentation_first_5_seconds",
    "spectating_living_peer",
    "respawned_alive",
    "level_up_picker",
)


def _read(path: Path) -> str:
    if not path.is_file():
        raise StaticReTestFailure(
            f"native HUD claim source is absent: {path.relative_to(ROOT)}"
        )
    return path.read_text(encoding="utf-8")


def _load_fixture() -> tuple[str, dict[str, Any]]:
    doc = _read(DOC_PATH)
    try:
        golden = json.loads(_read(GOLDEN_PATH))
    except json.JSONDecodeError as exc:
        raise StaticReTestFailure(
            f"native HUD golden is not reviewable JSON: {exc}"
        ) from exc
    if golden.get("header", {}).get("schema") != "solomon-dark-native-hud-goldens-v1":
        raise StaticReTestFailure(
            "HUD consumers would parse an unrecognized golden schema"
        )
    return doc, golden


def _require_regex(text: str, pattern: str, message: str) -> None:
    if re.search(pattern, text, flags=re.MULTILINE) is None:
        raise StaticReTestFailure(message)


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _parse_element_row(row: str, consequence: str) -> dict[str, str]:
    match = HUD_ELEMENT_ROW_PATTERN.fullmatch(row)
    if match is None:
        raise StaticReTestFailure(consequence)
    return match.groupdict()


def _expected_element_rows() -> dict[str, dict[str, str]]:
    rows = [
        _parse_element_row(
            row,
            f"{HUD_DOCUMENT_CLAIM}: a reviewed expected row lost its eight-column structure",
        )
        for row in EXPECTED_ELEMENT_ROWS
    ]
    ids = [row["id"] for row in rows]
    if len(rows) != 26 or [int(row["number"]) for row in rows] != list(range(1, 27)):
        raise StaticReTestFailure(
            f"{HUD_DOCUMENT_CLAIM}: expected constants no longer enumerate concrete rows 1 through 26"
        )
    if not {
        "cast.primary.card",
        "belt.slot.3.input_hint",
        "progression.xp.fill",
        "notification.gold",
    }.issubset(ids):
        raise StaticReTestFailure(
            f"{HUD_DOCUMENT_CLAIM}: expected geometry sweep lost a card, glyph, clipped fill, or font witness"
        )
    duplicates = sorted({element_id for element_id in ids if ids.count(element_id) > 1})
    if duplicates:
        raise StaticReTestFailure(
            f"{HUD_DOCUMENT_CLAIM}: expected constants contain ambiguous duplicate ids {duplicates}"
        )
    return {row["id"]: row for row in rows}


def _rects(cell: str, element_id: str) -> list[list[float]]:
    matches = re.findall(
        r"\[(-?(?:\d+(?:\.\d+)?)),(-?(?:\d+(?:\.\d+)?)),"
        r"(-?(?:\d+(?:\.\d+)?)),(-?(?:\d+(?:\.\d+)?))\]",
        cell,
    )
    if not matches:
        raise StaticReTestFailure(
            f"{HUD_DOCUMENT_CLAIM}: {element_id} geometry cell contains no explicit four-coordinate rect"
        )
    return [[float(value) for value in match] for match in matches]


def _rect_matches(actual: object, expected: list[float]) -> bool:
    return (
        isinstance(actual, list)
        and len(actual) == 4
        and all(
            isinstance(value, (int, float))
            and math.isclose(float(value), target, abs_tol=0.001)
            for value, target in zip(actual, expected, strict=True)
        )
    )


def _primary_rect(element_id: str, rects: list[list[float]]) -> list[float]:
    return rects[-1] if element_id == "notification.gold" else rects[0]


def _expected_atlas_and_source(row: dict[str, str]) -> tuple[str, str, list[str]]:
    art = row["art"]
    if art == "no draw":
        return "none", "native-renderer-or-no-draw", []
    if art == "Primitive untextured quad":
        return "native.untextured-quad", "native-renderer-or-no-draw", []
    atlas_ids = re.findall(r"`((?:UI|Skills|Inventory|Fonts)\.[^`]+)`", art)
    if not atlas_ids:
        raise StaticReTestFailure(
            f"{HUD_DOCUMENT_CLAIM}: {row['id']} art cell lost its explicit atlas reference"
        )
    atlas_id = atlas_ids[-1] if " plus " in art else atlas_ids[0]
    if "Manifest" in art:
        source_kind = "assetpack-manifest-id"
    elif "bitmap-font group" in art or " plus " in art:
        source_kind = "native-bundle-record-group"
    else:
        source_kind = "native-bundle-record"
    return atlas_id, source_kind, atlas_ids


def _assert_element_row_matches_fixture(
    row: dict[str, str], element: dict[str, Any]
) -> None:
    element_id = row["id"]
    rects = _rects(row["geometry"], element_id)
    expected_native_rect = _primary_rect(element_id, rects)
    if not _rect_matches(element.get("native_rect"), expected_native_rect):
        raise StaticReTestFailure(
            f"native HUD fixture row {element_id} would move from document geometry {expected_native_rect}"
        )

    logical_rects = re.findall(
        r"logical `\[(-?(?:\d+(?:\.\d+)?),-?(?:\d+(?:\.\d+)?),"
        r"-?(?:\d+(?:\.\d+)?),-?(?:\d+(?:\.\d+)?))\]`",
        row["geometry"],
    )
    expected_logical = (
        [float(value) for value in logical_rects[-1].split(",")]
        if logical_rects
        else None
    )
    if expected_logical is None and row["geometry"].startswith("logical `"):
        expected_logical = rects[0]
    if expected_logical is not None and not _rect_matches(
        element.get("logical_rect"), expected_logical
    ):
        raise StaticReTestFailure(
            f"native HUD fixture row {element_id} would move its logical box from {expected_logical}"
        )

    expected_clipped = expected_native_rect
    if element_id in {"belt.slot.0.input_hint", "progression.xp.fill"}:
        expected_clipped = rects[-1]
    if not _rect_matches(element.get("clipped_native_rect"), expected_clipped):
        raise StaticReTestFailure(
            f"native HUD fixture row {element_id} would move its settled clip from {expected_clipped}"
        )

    expected_atlas, expected_source, component_ids = _expected_atlas_and_source(row)
    if element.get("atlas_id") != expected_atlas:
        raise StaticReTestFailure(
            f"native HUD fixture row {element_id} would select an atlas other than {expected_atlas}"
        )
    asset_source = element.get("asset_source")
    if not isinstance(asset_source, dict) or asset_source.get("kind") != expected_source:
        raise StaticReTestFailure(
            f"native HUD fixture row {element_id} would lose its {expected_source} source classification"
        )
    if len(component_ids) > 1 and element.get("component_atlas_ids") != component_ids:
        raise StaticReTestFailure(
            f"native HUD fixture row {element_id} would disagree with component atlases {component_ids}"
        )
    bundle = re.search(r"Native `([^`]+\.bundle)`", row["art"])
    if bundle is not None and asset_source.get("bundle") != bundle.group(1):
        raise StaticReTestFailure(
            f"native HUD fixture row {element_id} would read a different native bundle than {bundle.group(1)}"
        )
    record = re.search(r"\brecord (\d+)\b", row["art"])
    if record is not None and asset_source.get("record_index") != int(record.group(1)):
        raise StaticReTestFailure(
            f"native HUD fixture row {element_id} would read a different bundle record than {record.group(1)}"
        )

    expected_addresses = re.findall(r"0x[0-9A-F]{8}", row["owners"])
    if element.get("native_addresses") != expected_addresses:
        raise StaticReTestFailure(
            f"native HUD fixture row {element_id} would move from native owners {expected_addresses}"
        )

    font = element.get("font")
    if row["font"] == "none":
        if font is not None:
            raise StaticReTestFailure(
                f"native HUD fixture row {element_id} would invent font metrics for a non-text element"
            )
    elif not isinstance(font, dict):
        raise StaticReTestFailure(
            f"native HUD fixture row {element_id} would lose its documented glyph metrics"
        )
    else:
        font_contract = row["font"]
        if element_id == "belt.slot.4.input_hint":
            font_contract = _expected_element_rows()["belt.slot.3.input_hint"]["font"]
        header = re.search(r"header `\[(\d+),(\d+),(\d+)\]`", font_contract)
        if header is not None and font.get("header") != [
            int(header.group(1)),
            int(header.group(2)),
            int(header.group(3)),
        ]:
            raise StaticReTestFailure(
                f"native HUD fixture row {element_id} would change its bitmap-font header"
            )
        line_height = re.search(r"(?:line height|header/)(\d+) px", row["font"])
        if line_height is not None and font.get("measured_line_height_px") != int(
            line_height.group(1)
        ):
            raise StaticReTestFailure(
                f"native HUD fixture row {element_id} would change its measured glyph line height"
            )
        records = re.search(r"Fonts\.(\d+)-(\d+)", expected_atlas)
        if records is not None and (
            font.get("bundle") != "images/Fonts.bundle"
            or font.get("records") != f"{records.group(1)}..{records.group(2)}"
        ):
            raise StaticReTestFailure(
                f"native HUD fixture row {element_id} would change its bitmap-font record group"
            )
        if element_id.startswith("belt.slot.") and element_id.endswith(".count"):
            if font.get("renderer") != "0x004A57C0":
                raise StaticReTestFailure(
                    f"native HUD fixture row {element_id} would change its glyph renderer owner"
                )
        if element_id == "ally.row.0.identity":
            expected_metrics = {
                "loader_glyph_advance_px": 4,
                "loader_space_advance_px": 2,
                "loader_padding_px": 2,
                "loader_baseline_offset_px": 7,
            }
            if any(font.get(key) != value for key, value in expected_metrics.items()):
                raise StaticReTestFailure(
                    "native HUD fixture row ally.row.0.identity would change its exact-name glyph advances, padding, or baseline"
                )

    observed_width = re.search(r"observed `\d+` is (\d+) px wide", row["font"])
    if observed_width is not None and not math.isclose(
        expected_native_rect[2] - expected_native_rect[0],
        float(observed_width.group(1)),
    ):
        raise StaticReTestFailure(
            f"{HUD_DOCUMENT_CLAIM}: {element_id} glyph width disagrees with its documented rect"
        )
    if element_id == "notification.gold":
        measured = re.search(r"measured (\d+) x (\d+) per line", row["font"])
        base = rects[0]
        if measured is None or (
            base[2] - base[0],
            base[3] - base[1],
        ) != (float(measured.group(1)), float(measured.group(2))):
            raise StaticReTestFailure(
                f"{HUD_DOCUMENT_CLAIM}: notification.gold measured glyph box disagrees with its base rect"
            )


def test_native_hud_document_element_table_is_exact() -> str:
    doc = _read(DOC_PATH)
    section_matches = list(
        re.finditer(
            r"^## Complete element census[ \t]*\r?\n(?P<body>.*?)(?=^### |^## )",
            doc,
            flags=re.MULTILINE | re.DOTALL,
        )
    )
    if len(section_matches) != 1:
        raise StaticReTestFailure(
            f"{HUD_DOCUMENT_CLAIM}: the implementer census section must be unique, found {len(section_matches)}"
        )
    table_matches = list(
        re.finditer(
            r"^\| # \| Stable element id \| Native rect \| Anchor and alignment \| "
            r"Art and source \| Font/text metrics \| Baseline order \| Native owner\(s\) \|[ \t]*\r?\n"
            r"^\| ---: \| --- \| --- \| --- \| --- \| --- \| --- \| --- \|[ \t]*\r?\n"
            r"(?P<rows>(?:^\|[^\r\n]*\|[ \t]*(?:\r?\n|$))+)",
            section_matches[0].group("body"),
            flags=re.MULTILINE,
        )
    )
    if len(table_matches) != 1:
        raise StaticReTestFailure(
            f"{HUD_DOCUMENT_CLAIM}: the eight-column geometry/source table must be unique and contiguous, found {len(table_matches)}"
        )
    table_rows = table_matches[0].group("rows")
    parsed_rows = [
        _parse_element_row(
            line,
            f"{HUD_DOCUMENT_CLAIM}: an implementer row lost its explicit eight-column structure",
        )
        for line in table_rows.splitlines()
        if line
    ]
    ids = [row["id"] for row in parsed_rows]
    duplicates = sorted({element_id for element_id in ids if ids.count(element_id) > 1})
    if duplicates:
        raise StaticReTestFailure(
            f"{HUD_DOCUMENT_CLAIM}: duplicate document row ids {duplicates} make geometry/source lookup ambiguous"
        )
    expected = _expected_element_rows()
    if len(parsed_rows) != len(expected) or set(ids) != set(expected):
        raise StaticReTestFailure(
            f"{HUD_DOCUMENT_CLAIM}: document must expose exactly the 26 reviewed element rows; missing={sorted(set(expected) - set(ids))}, extra={sorted(set(ids) - set(expected))}"
        )
    for element_id, expected_row in zip(expected, EXPECTED_ELEMENT_ROWS, strict=True):
        matches = list(
            re.finditer(rf"^{re.escape(expected_row)}$", table_rows, flags=re.MULTILINE)
        )
        if len(matches) != 1:
            raise StaticReTestFailure(
                f"{HUD_DOCUMENT_CLAIM}: {element_id} doc row no longer pins its exact rects, atlas/source, glyph metrics, draw order, and native owners"
            )
    return "all 26 HUD document rows structurally pin complete geometry, sources, glyph metrics, order, and owners"


def test_native_hud_element_census_and_rects_are_pinned() -> str:
    doc, golden = _load_fixture()
    expected_rows = _expected_element_rows()
    census = golden.get("element_census")
    if not isinstance(census, dict):
        raise StaticReTestFailure(
            "HUD implementation would lose the machine-readable element census"
        )
    elements = census.get("elements")
    if not isinstance(elements, list) or not elements:
        raise StaticReTestFailure(
            "HUD element validation examined no live census content"
        )
    if census.get("count") != len(expected_rows) or len(elements) != len(expected_rows):
        raise StaticReTestFailure(
            "HUD semantic census would no longer contain exactly the 26 reviewed elements"
        )
    ids = [element.get("id") for element in elements]
    if len(set(ids)) != len(ids):
        raise StaticReTestFailure(
            "HUD element lookup would be ambiguous because stable ids are duplicated"
        )
    if set(ids) != set(expected_rows):
        raise StaticReTestFailure(
            "HUD semantic census would add, remove, or rename a reviewed element identity"
        )
    by_id = {element["id"]: element for element in elements}
    if "progression.xp.track" not in by_id or "aim.cursor" not in by_id:
        raise StaticReTestFailure(
            "HUD census sweep did not reach the named XP and pointer witnesses"
        )

    for element_id, expected_row in expected_rows.items():
        element = by_id[element_id]
        _assert_element_row_matches_fixture(expected_row, element)
        if not element.get("anchor") or not element.get("alignment"):
            raise StaticReTestFailure(
                f"{element_id} would no longer have enough anchor information for viewport reconstruction"
            )
        addresses = element.get("native_addresses")
        if not isinstance(addresses, list) or not addresses:
            raise StaticReTestFailure(
                f"{element_id} would lose every native ownership address"
            )
        if f"`{element_id}`" not in doc:
            raise StaticReTestFailure(
                f"the binary-free HUD specification would omit census row {element_id}"
            )

    xp = by_id["progression.xp.fill"]
    if xp.get("clipped_native_rect") != [798.0, 857.0, 802.0, 881.0]:
        raise StaticReTestFailure(
            "XP census would conflate the observed 45/90 clip with its 48-pixel maximum geometry"
        )
    hint = by_id["belt.slot.0.input_hint"]
    if hint.get("clipped_native_rect") != [483.5, 877.0, 505.5, 899.999939]:
        raise StaticReTestFailure(
            "belt input hint would lose the retail bottom-edge clipping witness"
        )
    identity = by_id["ally.row.0.identity"]
    variants = identity.get("mode_variants")
    if not isinstance(variants, list) or [row.get("mode") for row in variants] != [
        "stock_single_player_or_bot_seam",
        "multiplayer_transport",
    ]:
        raise StaticReTestFailure(
            "ally identity would conflate the stock ALLY glyph with the multiplayer exact-name replacement"
        )

    crops = golden.get("reference_crops")
    if not isinstance(crops, list) or len(crops) < 38:
        raise StaticReTestFailure(
            "HUD visual diffing would lose a per-element crop or required scripted-state crop"
        )
    crop_ids = [crop.get("id") for crop in crops]
    if len(set(crop_ids)) != len(crop_ids):
        raise StaticReTestFailure(
            "HUD reference-crop lookup would be ambiguous because crop ids are duplicated"
        )
    if not set(expected_rows).issubset(crop_ids):
        raise StaticReTestFailure(
            "HUD visual diffing would no longer include every named census element"
        )
    if "state.health.magic_shield_below_life" not in crop_ids:
        raise StaticReTestFailure(
            "HUD visual diffing would lose the shield/life draw-order crossover witness"
        )
    for crop in crops:
        if not _is_sha256(crop.get("source_sha256")) or not _is_sha256(crop.get("sha256")):
            raise StaticReTestFailure(
                f"evidence-only HUD crop {crop.get('id')!r} would lose source/crop provenance"
            )
        if not str(crop.get("path", "")).startswith(
            "/mnt/d/codex-evidence/uire-20260806/hud-crops/"
        ):
            raise StaticReTestFailure(
                f"evidence-only HUD crop {crop.get('id')!r} would escape the campaign evidence root"
            )
    return "native HUD census pins all 26 rects, atlas sources, anchors, and visual crops"


def test_native_hud_fill_cooldown_charge_and_notification_behavior_are_pinned() -> str:
    doc, golden = _load_fixture()
    behavior = golden.get("behavior_contract")
    if not isinstance(behavior, dict) or "health_fill" not in behavior:
        raise StaticReTestFailure(
            "HUD behavior validation did not reach its named health-fill witness"
        )

    health = behavior["health_fill"]
    if health.get("function") != (
        "visible_width_px = dynamic_core_width * clamp(current / maximum, 0, 1)^2"
    ):
        raise StaticReTestFailure(
            "health fill would cease to use the retail squared current/max clip"
        )
    if health.get("baseline_core_width_px") != 100.0 or health.get("anchor") != "left":
        raise StaticReTestFailure(
            "health fill would lose its 100-pixel left-anchored envelope"
        )
    if health.get("native_fields") != {
        "base": "progression+0x6C",
        "current": "progression+0x70",
        "maximum": "progression+0x74",
    }:
        raise StaticReTestFailure(
            "health fill would read a display surrogate instead of the native current/maximum pair"
        )
    samples = health.get("observed_samples")
    if not isinstance(samples, list) or [sample.get("scenario") for sample in samples] != [
        "full_health",
        "damaged_health",
        "near_death_health",
    ]:
        raise StaticReTestFailure(
            "health behavior would lose the full, damaged, and near-death live witnesses"
        )
    for sample in samples:
        current = float(sample["current"])
        maximum = float(sample["maximum"])
        expected_width = float(health["baseline_core_width_px"]) * max(
            0.0, min(current / maximum, 1.0)
        ) ** 2
        if not math.isclose(
            float(sample["visible_width_px"]), expected_width, abs_tol=0.001
        ):
            raise StaticReTestFailure(
                f"{sample['scenario']} health pixels would disagree with the squared native ratio"
            )

    shield = health.get("magic_shield")
    if not isinstance(shield, dict) or shield.get("function") != (
        "second left-anchored width = dynamic_core_width * "
        "clamp(shield_current / shield_maximum, 0, 1)"
    ):
        raise StaticReTestFailure(
            "magic shield would lose its independent linear UI.26 clip"
        )
    compositions = shield.get("observed_compositions")
    if not isinstance(compositions, list) or {
        row.get("scenario") for row in compositions
    } != {"magic_shield_health", "magic_shield_below_health_fill"}:
        raise StaticReTestFailure(
            "magic shield would lose one side of the life/shield width crossover"
        )
    if len(compositions) != 2:
        raise StaticReTestFailure(
            "magic shield crossover lookup would be ambiguous because scenarios are duplicated"
        )
    by_scenario = {row["scenario"]: row for row in compositions}
    above = by_scenario["magic_shield_health"]
    below = by_scenario["magic_shield_below_health_fill"]
    if above.get("shield_tint_rgba") != [0.5, 1.0, 1.0, 1.0] or below.get(
        "shield_tint_rgba"
    ) != [0.5, 1.0, 1.0, 1.0]:
        raise StaticReTestFailure(
            "magic shield would stop using the observed cyan tint"
        )
    if not (
        float(above["life_visible_width_px"]) < float(above["shield_visible_width_px"])
        and int(above["life_first_draw_order"]) < int(above["shield_first_draw_order"])
        and float(below["shield_visible_width_px"]) < float(below["life_visible_width_px"])
        and int(below["shield_first_draw_order"]) < int(below["life_first_draw_order"])
    ):
        raise StaticReTestFailure(
            "health layers would no longer draw shorter-first and longer-last across the crossover"
        )

    mana = behavior.get("mana_fill", {})
    if mana.get("function") != (
        "visible_width_px = dynamic_core_width * clamp(current / maximum, 0, 1)"
    ):
        raise StaticReTestFailure(
            "mana fill would cease to use the retail linear current/max clip"
        )
    if mana.get("native_fixed_tick_hz") != 100 or "250 ms" not in mana.get(
        "g1_250ms_distinction", ""
    ):
        raise StaticReTestFailure(
            "mana presentation would conflate the 100 Hz native pool with the 250 ms loader reserve service"
        )
    if mana.get("native_fields") != {
        "base": "progression+0x78",
        "current": "progression+0x7C",
        "maximum": "progression+0x80",
        "reserve": "progression+0x740",
    }:
        raise StaticReTestFailure(
            "mana and reserve presentation would read the wrong progression fields"
        )
    if float(mana["first_sample"]["mana"]["current"]) >= float(
        mana["last_sample"]["mana"]["current"]
    ):
        raise StaticReTestFailure(
            "mana refill golden would no longer demonstrate an increasing native pool"
        )

    cooldown = behavior.get("cooldown", {})
    expected_cooldown = {
        "remaining_field_offset": "skill_entry+0x64",
        "capacity_field_offset": "skill_entry+0x68",
        "observed_capacity_ticks": 2500.0,
        "sector_start_degrees": 360.0,
        "sector_end_degrees": "360 * (1 - remaining / capacity)",
        "covered_interval": "[end_degrees, 360]",
        "segment_size_degrees": 45.0,
        "ready_icon_observed_alpha": 0.375,
        "active_icon_alpha": 0.25,
    }
    for key, expected in expected_cooldown.items():
        if cooldown.get(key) != expected:
            raise StaticReTestFailure(
                f"cooldown presentation would change the reviewed {key} constant"
            )
    if float(cooldown["observed_first_remaining"]) <= float(
        cooldown["observed_last_remaining"]
    ):
        raise StaticReTestFailure(
            "cooldown trace would no longer demonstrate fixed-tick remaining-time decay"
        )

    earth = behavior.get("earth_charge", {})
    if (
        earth.get("hud_meter")
        != "none; charge presentation is the G2 world-space Boulder scale curve"
        or earth.get("field") != "Boulder+0x74"
        or earth.get("initial_charge") != 0.18
        or earth.get("increment_per_fixed_tick") != 0.00125
        or earth.get("ticks_to_full_from_initial") != 656
        or earth.get("seconds_to_full_at_100hz") != 6.56
    ):
        raise StaticReTestFailure(
            "Earth hold would gain a fabricated HUD meter or drift from the G2 float32 charge curve"
        )

    xp = behavior.get("xp_and_level", {})
    if (
        xp.get("maximum_fill_height_px") != 48.0
        or xp.get("observed_partial_fill_height_px") != 24.0
        or xp.get("observed_partial_state")
        != {"xp": 45, "previous_threshold": 0, "next_threshold": 90}
        or xp.get("numeric_level_in_run") != "absent"
    ):
        raise StaticReTestFailure(
            "XP/level presentation would lose its 48-pixel gauge, 45/90 witness, or numeric-level absence"
        )

    gold = behavior.get("gold_notification", {})
    if (
        gold.get("format") != "_s(%.2f)%s with payload 25 GOLD"
        or gold.get("initial_lifetime_seconds") != 1.5
        or gold.get("alpha") != "clamp(timer, 0, 1)"
    ):
        raise StaticReTestFailure(
            "gold pickup presentation would drift from its text, lifetime, or fade contract"
        )
    absences = behavior.get("buff_debuff_and_floaters", {})
    if absences.get("screen_icon_row") != "absent in the exhaustive retail HUD capture" or not str(
        absences.get("numeric_damage_heal_floaters", "")
    ).startswith("absent"):
        raise StaticReTestFailure(
            "browser HUD would be allowed to invent retail buff icons or numeric floaters"
        )

    _require_regex(
        doc,
        r"^health_core_width =\n"
        r"^    2 \* \(base_health \+ 0\.25 \* "
        r"\(maximum_health - base_health\)\)\n"
        r"^health_track_width = health_core_width \+ 10\n"
        r"^health_ratio = clamp\(current_health / maximum_health, 0, 1\)\n"
        r"^health_visible_width = health_core_width \* health_ratio \* health_ratio$",
        "binary-free HUD prose would no longer specify dynamic squared-life geometry",
    )
    _require_regex(
        doc,
        r"^end_degrees = 360 \* \(1 - remaining / capacity\)\n"
        r"^covered sector = \[end_degrees, 360\]$",
        "binary-free HUD prose would no longer specify the adjacent cooldown sector bounds",
    )
    return "native HUD fills, shield ordering, cooldown, charge, XP, and pickup behavior are pinned"


def test_native_hud_visibility_scaling_and_multiplayer_are_pinned() -> str:
    doc, golden = _load_fixture()
    visibility = golden.get("visibility_contract")
    if not isinstance(visibility, dict):
        raise StaticReTestFailure(
            "HUD implementation would lose its game-state visibility matrix"
        )
    matrix = visibility.get("matrix")
    if not isinstance(matrix, list) or not matrix:
        raise StaticReTestFailure(
            "HUD visibility validation examined no real state rows"
        )
    states = tuple(row.get("state") for row in matrix)
    if states != EXPECTED_VISIBILITY_STATES:
        raise StaticReTestFailure(
            "HUD visibility matrix would add, remove, reorder, or rename a reviewed game state"
        )
    if len({row["state"] for row in matrix}) != len(matrix):
        raise StaticReTestFailure(
            "HUD visibility lookup would be ambiguous because state rows are duplicated"
        )
    by_state = {row["state"]: row for row in matrix}
    if "0x005D3D48" not in by_state["local_death"]["stock_hud"]:
        raise StaticReTestFailure(
            "death visibility would restore stock HUD elements that retail skips"
        )
    if "no product spectator panel yet" not in by_state[
        "death_presentation_first_5_seconds"
    ]["stock_hud"]:
        raise StaticReTestFailure(
            "spectator UI would appear during the five-second death-presentation grace interval"
        )
    if "product spectator overlay" not in by_state["spectating_living_peer"][
        "stock_hud"
    ]:
        raise StaticReTestFailure(
            "dead local owners would lose the landed spectator product affordance"
        )
    if visibility.get("participant_count_rule") != {
        "solo": 0,
        "two_participants": 1,
        "n_participants": "n - 1 unique nonlocal durable rows, sorted by participant id",
    }:
        raise StaticReTestFailure(
            "ally rows would regress to self, duplicate, phantom, or nondeterministic participants"
        )
    membership = visibility.get("live_draw_membership", {})
    if (
        membership.get("hub_structurally_settled") is not False
        or membership.get("hub_diagnostic_draw_count") != 40
        or membership.get("hub_run_draw_count") != 36
        or membership.get("hub_non_rect_varying_draws") != ["College.18", "College.17"]
    ):
        raise StaticReTestFailure(
            "hub HUD would be promoted from a known non-settling 40-draw diagnostic to a false golden"
        )

    absence_findings = golden.get("element_census", {}).get("absence_findings")
    if not isinstance(absence_findings, list) or not absence_findings:
        raise StaticReTestFailure(
            "HUD absence validation examined no named findings"
        )
    absence_ids = [row.get("id") for row in absence_findings]
    if absence_ids != [
        "progression.numeric_level",
        "gold.persistent_counter",
        "wave.numeric_or_score_indicator",
        "buff_or_debuff.icon_row",
        "damage_or_heal.floater",
    ]:
        raise StaticReTestFailure(
            "HUD absence contract would permit a fabricated level, gold, wave/score, buff, or floater element"
        )
    not_yet = golden.get("element_census", {}).get("not_yet_reversed")
    if not isinstance(not_yet, list) or len(not_yet) != 1 or not_yet[0].get(
        "id"
    ) != "featured_enemy.panel":
        raise StaticReTestFailure(
            "featured-enemy HUD layout would be guessed instead of remaining explicitly unreversed"
        )

    scaling = golden.get("scaling_contract")
    if not isinstance(scaling, dict):
        raise StaticReTestFailure(
            "HUD implementation would lose its 1280x800 anchor transform"
        )
    if (
        scaling.get("observed_native_resolution") != [1600, 900]
        or scaling.get("target_resolution") != [1280, 800]
        or scaling.get("target_transform")
        != {
            "center_x_delta_px": -160,
            "bottom_y_delta_px": -100,
            "top_y_delta_px": 0,
            "scale_factor": 1.0,
        }
        or "do not uniformly scale" not in scaling.get("implementation", "")
    ):
        raise StaticReTestFailure(
            "1280x800 HUD would use naive uniform scaling instead of native center/top/bottom anchors"
        )
    if scaling.get("designed_not_observed") != {
        "safe_inset_px": 24,
        "minimum_skill_slot_px": [48, 48],
        "native_skill_slot_px": [53, 53],
        "minimum_vital_track_px": [110, 20],
        "minimum_ally_bar_px": [50, 8],
        "minimum_name_font_px": 12,
        "minimum_name_line_box_px": 16,
        "minimum_counter_font_px": 12,
        "minimum_notification_font_px": 16,
        "minimum_general_line_box_px": 16,
        "pointer_safe_rule": "clamp the complete 31x33 cursor inside the drawable viewport",
    }:
        raise StaticReTestFailure(
            "Steam Deck HUD would lose a labeled readability minimum or 24-pixel safe area"
        )

    _require_regex(
        doc,
        r"^center-top:\s+x' = x \+ \(viewport_width - 1600\) / 2; y' = y\n"
        r"^center-bottom: x' = x \+ \(viewport_width - 1600\) / 2; y' = y \+ \(viewport_height - 900\)\n"
        r"^pointer:\s+center on the current pointer/aim point, then viewport-clip$",
        "binary-free HUD prose would no longer keep the three native anchor rules adjacent",
    )
    if "## Designed-not-observed readability policy" not in doc:
        raise StaticReTestFailure(
            "browser readability choices would be misrepresented as observed retail behavior"
        )
    if "G11 owns every pre-gameplay or overlay **screen**" not in doc or (
        "G12 owns frame composition" not in doc
    ):
        raise StaticReTestFailure(
            "HUD specification would cross the landed G11 screen or G12 composition boundary"
        )
    if "[`ui-binary-map.md`](../ui-binary-map.md)" not in doc or (
        "[`ui-engine-system-map.md`](../ui-engine-system-map.md)" not in doc
    ):
        raise StaticReTestFailure(
            "HUD census would stop tracing its element and renderer ownership to both prior UI maps"
        )

    layout = _read(BINARY_LAYOUT_PATH)
    for line, consequence in (
        (
            "gameplay_ally_healthbar_append=0x005CF480",
            "ally append would call a different native ABI",
        ),
        (
            "gameplay_ally_healthbar_count=0x1C20",
            "ally rows would read a different native vector count",
        ),
        (
            "gameplay_ui_bundle=0x008199E4",
            "ally identity would read a different UI bundle singleton",
        ),
    ):
        if line not in layout:
            raise StaticReTestFailure(consequence)

    hud_hooks = _read(HUD_HOOK_PATH)
    _require_regex(
        hud_hooks,
        r"^    const auto rows = BuildGameplayAllyHudRows\(\);\n"
        r"^    const auto label_glyph =\n"
        r"^        bundle_address \+ kGameplayUiAllyLabelGlyphOffset;\n"
        r"^    for \(const auto& row : rows\) \{\n"
        r"^        if \(!CallGameplayAllyHealthbarAppendSafe\(\n"
        r"^                append_address,\n"
        r"^                gameplay_address,\n"
        r"^                label_glyph,\n"
        r"^                row\.hp_ratio,",
        "ally roster would no longer call the typed glyph-then-ratio append ABI",
    )
    if (
        "return left.participant_id < right.participant_id;" not in hud_hooks
        or "return left.participant_id == right.participant_id;" not in hud_hooks
        or "kGameplayAllyHudReservedLabelWidth = 128.0f" not in hud_hooks
    ):
        raise StaticReTestFailure(
            "ally rows would lose deterministic identity deduplication or the 128-pixel name reservation"
        )
    return "native HUD visibility, 16:10 scaling, and multiplayer epoch constraints are pinned"


def test_native_hud_recorder_is_self_provenanced_settled_and_visual_diffable() -> str:
    _, golden = _load_fixture()
    header = golden.get("header")
    if not isinstance(header, dict):
        raise StaticReTestFailure(
            "HUD golden would lose its recorder-derived provenance header"
        )
    if (
        header.get("recorded_live") is not True
        or header.get("instance") != "ui-g9a"
        or header.get("ports") != [52361, 52362]
        or header.get("participant_id") != "0x2000000000004909"
        or header.get("audio_disabled") is not True
        or header.get("native_resolution") != [1600, 900]
    ):
        raise StaticReTestFailure(
            "HUD golden would lose its exact live instance, ports, participant, audio, or viewport provenance"
        )
    if not re.fullmatch(r"[0-9a-f]{40}", str(header.get("source_commit_sha", ""))) or not re.fullmatch(
        r"[0-9a-f]{40}", str(header.get("source_tree_sha", ""))
    ):
        raise StaticReTestFailure(
            "HUD golden would lose a full recorder-derived source commit or tree identity"
        )
    if header.get("worktree_dirty_at_capture_start") is not False:
        raise StaticReTestFailure(
            "published HUD golden would come from an uncommitted source tree"
        )
    for field in ("game_binary_sha256", "loader_sha256", "staged_loader_sha256"):
        if not _is_sha256(header.get(field)):
            raise StaticReTestFailure(
                f"HUD golden would lose the exact live {field} provenance"
            )
    if header["loader_sha256"] != header["staged_loader_sha256"]:
        raise StaticReTestFailure(
            "HUD capture would not prove the staged loader matches the Release build"
        )
    if header.get("settle_contract") != {
        "minimum_consecutive_samples": 40,
        "minimum_span_seconds": 2.0,
        "maximum_animated_fraction": 0.3,
    }:
        raise StaticReTestFailure(
            "HUD golden would weaken its 40-sample, two-second, 30-percent settle policy"
        )
    cleanup = header.get("cleanup")
    if not isinstance(cleanup, list) or len(cleanup) != 1:
        raise StaticReTestFailure(
            "HUD process-cleanup receipt would be missing or ambiguous"
        )
    receipt = cleanup[0]
    if not (
        receipt.get("pathMatched") is True
        and receipt.get("stopped") is True
        and int(receipt.get("processId", 0)) > 0
        and receipt.get("expectedPath") == receipt.get("actualPath")
    ):
        raise StaticReTestFailure(
            "HUD recorder would not prove exact-path ownership before stopping its process"
        )

    if tuple(golden.get("scenario_order", ())) != EXPECTED_SCENARIOS:
        raise StaticReTestFailure(
            "HUD scripted session would lose or reorder a required retail state"
        )
    scenarios = golden.get("scenarios")
    if not isinstance(scenarios, dict) or set(scenarios) != set(EXPECTED_SCENARIOS):
        raise StaticReTestFailure(
            "HUD scenario lookup would be missing or ambiguous against the scripted order"
        )
    if "full_health" not in scenarios or "two_participant_ally_bar" not in scenarios:
        raise StaticReTestFailure(
            "HUD settle sweep did not reach the named full-health and ally witnesses"
        )
    captured_scenarios = EXPECTED_SCENARIOS[:-1]
    for scenario_name in captured_scenarios:
        scenario = scenarios[scenario_name]
        captures = scenario.get("independent_captures")
        if not isinstance(captures, list) or len(captures) != 2:
            raise StaticReTestFailure(
                f"{scenario_name} would lose one of its two independent settle-gated captures"
            )
        signatures: list[str] = []
        animated_sets: list[list[int]] = []
        for capture in captures:
            settle = capture.get("settle_gate", {})
            if (
                settle.get("required_minimum_consecutive_samples") != 40
                or settle.get("required_minimum_span_ms") != 2000
                or int(settle.get("stable_sample_count", 0)) < 40
                or int(settle.get("stable_span_ms", 0)) < 2000
                or float(settle.get("animated_fraction", 1.0)) > 0.3
            ):
                raise StaticReTestFailure(
                    f"{scenario_name} would no longer prove structural settlement before capture"
                )
            signature = settle.get("structural_signature_sha256")
            if not _is_sha256(signature):
                raise StaticReTestFailure(
                    f"{scenario_name} would lose its settled structural signature"
                )
            signatures.append(signature)
            animated_draws = settle.get("animated_draws")
            if not isinstance(animated_draws, list):
                raise StaticReTestFailure(
                    f"{scenario_name} would lose its measured animated-element set"
                )
            for animated_draw in animated_draws:
                if (
                    not isinstance(animated_draw, dict)
                    or not isinstance(animated_draw.get("draw_order"), int)
                    or not isinstance(animated_draw.get("anchor_rect"), list)
                    or len(animated_draw["anchor_rect"]) != 4
                    or not isinstance(animated_draw.get("envelope"), list)
                    or len(animated_draw["envelope"]) != 4
                ):
                    raise StaticReTestFailure(
                        f"{scenario_name} would lose an animated element's identity, anchor rect, or motion envelope"
                    )
            animated_sets.append(
                [int(animated_draw["draw_order"]) for animated_draw in animated_draws]
            )
            representative = capture.get("representative")
            if not isinstance(representative, dict) or not representative.get("draws"):
                raise StaticReTestFailure(
                    f"{scenario_name} settle gate would contain no real HUD draw witness"
                )
        if signatures[0] != signatures[1] or animated_sets[0] != animated_sets[1]:
            raise StaticReTestFailure(
                f"{scenario_name} would not reproduce its structure and animated set independently"
            )
        trace = scenario.get("behavior_trace")
        if not isinstance(trace, list) or not trace:
            raise StaticReTestFailure(
                f"{scenario_name} would lose every native-tick behavior sample"
            )
        if any(not isinstance(sample.get("tick"), int) for sample in trace):
            raise StaticReTestFailure(
                f"{scenario_name} behavior samples would lose native simulation tick stamps"
            )
        screenshot = scenario.get("screenshot")
        if not isinstance(screenshot, dict) or not _is_sha256(screenshot.get("sha256")):
            raise StaticReTestFailure(
                f"{scenario_name} would lose its backbuffer reference provenance"
            )

    level_transition = scenarios["level_up"].get("transition", {})
    if (
        level_transition.get("before", {}).get("level") != "1"
        or level_transition.get("observed", {}).get("level") != "2"
        or level_transition.get("result", {}).get("success") != "true"
    ):
        raise StaticReTestFailure(
            "level-up golden would no longer prove a successful fixed-tick 1-to-2 transition"
        )

    recorder = _read(RECORDER_PATH)
    parsed = ast.parse(recorder, filename=str(RECORDER_PATH))
    parser_flags = {
        node.args[0].value
        for node in ast.walk(parsed)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "add_argument"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    }
    if parser_flags != {"--smoke"}:
        raise StaticReTestFailure(
            "HUD recorder would accept a caller-supplied provenance or uncontrolled capture parameter"
        )
    if "SETTLE_SAMPLE_FLOOR = 40" not in recorder:
        raise StaticReTestFailure(
            "HUD recorder could accept fewer than 40 consecutive structural samples"
        )
    if (
        "SETTLE_SECONDS_FLOOR = 2.0" not in recorder
        or "MAXIMUM_ANIMATED_FRACTION = 0.30" not in recorder
        or "SETTLE_CAPTURE_FRAMES = 480" not in recorder
    ):
        raise StaticReTestFailure(
            "HUD recorder would weaken the settle duration, animated fraction, or sampling window"
        )
    _require_regex(
        recorder,
        r"^    source = source_revision\(\)\n"
        r"^    require\(GAME_BINARY\.is_file\(\),[\s\S]*?"
        r"^                \"header\": provenance_header\(source, launch\),",
        "HUD recorder would no longer derive source and binary provenance inside its own main path",
    )
    if (
        "is broken, not busy" not in recorder
        or "remained busy" not in recorder
        or "session.assert_wait_target_runnable" not in recorder
    ):
        raise StaticReTestFailure(
            "HUD recorder would collapse broken, busy, and unrunnable capture states into one wait"
        )
    if (
        '"tint": draw.get("tint")' not in recorder
        or '"resolved_screen_rect": draw.get("resolved_screen_rect")' not in recorder
        or "structural_payload(frame)" not in recorder
        or "geometry_payload(frame)" not in recorder
    ):
        raise StaticReTestFailure(
            "HUD settle gate would stop separating structural fields from rect-only animation"
        )
    _require_regex(
        recorder,
        r"^def require_one\(rows: list\[Any\], claim: str\) -> Any:\n"
        r"^    require\(len\(rows\) == 1, f\"\{claim\} lookup is ambiguous: found \{len\(rows\)\} candidates\"\)\n"
        r"^    return rows\[0\]$",
        "HUD recorder could silently choose between duplicate native candidates",
    )

    coordinator = _read(SCENE_CAPTURE_PATH)
    hooks = _read(SCENE_CAPTURE_HOOKS_PATH)
    observation = _read(SCENE_CAPTURE_OBSERVATION_PATH)
    public_api = _read(SCENE_CAPTURE_PUBLIC_API_PATH)
    shared_solo_recorder = _read(SHARED_SOLO_RECORDER_PATH)
    if (
        '"SDMOD_NATIVE_SCENE_CAPTURE_DIRECTORY"' not in coordinator
        or '"SDMOD_NATIVE_SCENE_CAPTURE_SURFACE"' not in coordinator
        or 'surface == "hud"' not in public_api
    ):
        raise StaticReTestFailure(
            "native HUD observation seam would stop being explicitly environment-gated"
        )
    if (
        "native HUD capture exceeded its 64 rendered-slot bound" not in hooks
        or "native HUD capture exceeded its 32 rendered-strip bound" not in hooks
        or "native HUD capture observed an invalid ally-bar vector instead of guessing its rows"
        not in observation
    ):
        raise StaticReTestFailure(
            "native HUD observation seam would become unbounded or guess invalid ally rows"
        )
    if (
        "native HUD capture reached the HUD renderer before a runnable scene camera boundary"
        not in observation
        or "native HUD capture could not register its EndScene boundary" not in public_api
    ):
        raise StaticReTestFailure(
            "native HUD observation seam would treat hook existence as end-to-end runnability"
        )
    if (
        "kD3d9DevicePointerGlobalAddress = 0x00B401E8" not in public_api
        or ".ResolveGameAddressOrZero(kD3d9DevicePointerGlobalAddress)"
        not in public_api
    ):
        raise StaticReTestFailure(
            "native HUD EndScene boundary would resolve the wrong retail D3D9 device global"
        )
    if (
        "terminal_output = (stderr.strip() or stdout.strip())[-4000:]"
        not in shared_solo_recorder
        or "terminal_output or 'no terminal output'" not in shared_solo_recorder
    ):
        raise StaticReTestFailure(
            "HUD launch failures would hide the terminal setup error needed to distinguish broken from busy"
        )
    return "native HUD recorder is live, self-provenanced, settle-gated, bounded, and visual-diffable"


def test_tutorial_pointer_quad_pivot_and_complete_call_membership_are_pinned() -> str:
    doc = _read(DOC_PATH)
    for marker in (
        "Tutorial pointer centred-quad and responsive-composition audit",
        "15 direct call sites",
        "`0x005C9BB0` binds UI record 28 at `UI+0x15A8`",
        "The direction pair is never consumed as a draw position.",
        "`0x00414F90` creates a rotation matrix",
        "`0x004142E0` adds the record's `width/2,height/2`",
        "nontransparent bounds\n  `(2,2)..(55,59)`",
        "pointer's origin offset and centred UI-28 quad must receive the same uniform\nscale",
    ):
        if marker not in doc:
            raise StaticReTestFailure(
                f"native Tutorial pointer report lost centred-quad marker {marker}"
            )

    expected_calls = {
        "0x005D0EFA",
        "0x005D10B6",
        "0x005D11F8",
        "0x005D133E",
        "0x005D143C",
        "0x005D1529",
        "0x005D16E1",
        "0x005D1A00",
        "0x005D1AF5",
        "0x005D1B9B",
        "0x005D1CD9",
        "0x005D1DE9",
        "0x005D206A",
        "0x005D21BE",
        "0x005D2274",
    }
    audit = doc.split(
        "## 2026-08-25 Tutorial pointer centred-quad and responsive-composition audit",
        1,
    )[1]
    recovered_calls = set(re.findall(r"`(0x005D[0-9A-F]{4})`", audit))
    if not expected_calls.issubset(recovered_calls):
        raise StaticReTestFailure(
            "native Tutorial pointer audit lost one or more of the complete 15 direct calls"
        )
    return "Tutorial UI-28 centred pivot, direction-only pair, and 15-call membership are pinned"
