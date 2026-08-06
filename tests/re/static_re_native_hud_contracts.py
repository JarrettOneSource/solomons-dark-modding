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


EXPECTED_ELEMENTS: dict[str, tuple[list[float], str]] = {
    "cast.primary.card": ([730.5, 825.0, 793.5, 892.0], "UI.47"),
    "cast.secondary.card": ([810.5, 825.0, 873.5, 892.0], "UI.48"),
    "belt.slot.0": ([473.5, 840.5, 515.5, 877.5], "Skills.72"),
    "belt.slot.1": ([528.0, 832.5, 581.0, 885.5], "none"),
    "belt.slot.2": ([588.0, 832.5, 641.0, 885.5], "none"),
    "belt.slot.3": ([648.0, 834.0, 706.0, 889.0], "Inventory.46"),
    "belt.slot.4": ([899.5, 834.5, 954.5, 888.5], "Inventory.47"),
    "belt.slot.5": ([958.0, 832.5, 1011.0, 885.5], "none"),
    "belt.slot.6": ([1018.0, 832.5, 1071.0, 885.5], "none"),
    "belt.slot.7": ([1078.0, 832.5, 1131.0, 885.5], "none"),
    "belt.slot.0.input_hint": ([483.5, 877.0, 505.5, 908.0], "UI.100"),
    "belt.slot.3.count": ([671.0, 888.0, 679.0, 897.0], "Fonts.535-626@0x2A4C"),
    "belt.slot.4.count": ([920.0, 888.0, 930.0, 897.0], "Fonts.535-626@0x2B20"),
    "progression.xp.fill": ([798.0, 833.0, 802.0, 881.0], "UI.81"),
    "progression.xp.track": ([794.5, 829.0, 806.5, 885.0], "UI.82"),
    "mana.track": ([850.0, 14.5, 960.0, 34.5], "UI.70"),
    "mana.fill": ([855.0, 19.5, 955.0, 29.5], "UI.40"),
    "health.track": ([640.0, 14.5, 750.0, 34.5], "UI.70"),
    "health.fill": ([645.0, 19.5, 745.0, 29.5], "UI.26"),
    "mana.reserve.overlay": ([906.5, 19.5, 954.5, 29.5], "UI.41"),
    "health.magic_shield.overlay": ([645.0, 19.5, 745.0, 29.5], "UI.26"),
    "ally.row.0.identity": ([612.0, 39.0, 740.0, 46.0], "UI.0"),
    "ally.row.0.health": ([560.0, 39.5, 610.0, 44.5], "native.untextured-quad"),
    "concentration.binding.12.emblem": ([783.875, 9.75, 816.125, 41.25], "Skills.67"),
    "aim.cursor": ([9.5, 8.5, 40.5, 41.5], "UI.42"),
    "notification.gold": ([741.0, 49.0, 860.0, 71.0], "Fonts.376-442"),
}

EXPECTED_SOURCE_KINDS = {
    "cast.primary.card": "assetpack-manifest-id",
    "cast.secondary.card": "assetpack-manifest-id",
    "belt.slot.0": "native-bundle-record",
    "belt.slot.1": "native-renderer-or-no-draw",
    "belt.slot.2": "native-renderer-or-no-draw",
    "belt.slot.3": "native-bundle-record",
    "belt.slot.4": "native-bundle-record",
    "belt.slot.5": "native-renderer-or-no-draw",
    "belt.slot.6": "native-renderer-or-no-draw",
    "belt.slot.7": "native-renderer-or-no-draw",
    "belt.slot.0.input_hint": "assetpack-manifest-id",
    "belt.slot.3.count": "native-bundle-record-group",
    "belt.slot.4.count": "native-bundle-record-group",
    "progression.xp.fill": "native-bundle-record",
    "progression.xp.track": "assetpack-manifest-id",
    "mana.track": "native-bundle-record",
    "mana.fill": "native-bundle-record",
    "health.track": "native-bundle-record",
    "health.fill": "native-bundle-record",
    "mana.reserve.overlay": "native-bundle-record",
    "health.magic_shield.overlay": "native-bundle-record",
    "ally.row.0.identity": "assetpack-manifest-id",
    "ally.row.0.health": "native-renderer-or-no-draw",
    "concentration.binding.12.emblem": "native-bundle-record",
    "aim.cursor": "assetpack-manifest-id",
    "notification.gold": "native-bundle-record-group",
}

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


def test_native_hud_element_census_and_rects_are_pinned() -> str:
    doc, golden = _load_fixture()
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
    if census.get("count") != len(EXPECTED_ELEMENTS) or len(elements) != len(EXPECTED_ELEMENTS):
        raise StaticReTestFailure(
            "HUD semantic census would no longer contain exactly the 26 reviewed elements"
        )
    ids = [element.get("id") for element in elements]
    if len(set(ids)) != len(ids):
        raise StaticReTestFailure(
            "HUD element lookup would be ambiguous because stable ids are duplicated"
        )
    if set(ids) != set(EXPECTED_ELEMENTS):
        raise StaticReTestFailure(
            "HUD semantic census would add, remove, or rename a reviewed element identity"
        )
    by_id = {element["id"]: element for element in elements}
    if "progression.xp.track" not in by_id or "aim.cursor" not in by_id:
        raise StaticReTestFailure(
            "HUD census sweep did not reach the named XP and pointer witnesses"
        )

    for element_id, (expected_rect, expected_atlas) in EXPECTED_ELEMENTS.items():
        element = by_id[element_id]
        if element.get("native_rect") != expected_rect:
            raise StaticReTestFailure(
                f"{element_id} would move from its native rect {expected_rect}"
            )
        if element.get("atlas_id") != expected_atlas:
            raise StaticReTestFailure(
                f"{element_id} would select a different retail atlas record than {expected_atlas}"
            )
        if element.get("asset_source", {}).get("kind") != EXPECTED_SOURCE_KINDS[element_id]:
            raise StaticReTestFailure(
                f"{element_id} would lose whether its art comes from the landed manifest, native bundle, or primitive renderer"
            )
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
    if not set(EXPECTED_ELEMENTS).issubset(crop_ids):
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
    if health.get("function") != "visible_width_px = 100 * clamp(current / maximum, 0, 1)^2":
        raise StaticReTestFailure(
            "health fill would cease to use the retail squared current/max clip"
        )
    if health.get("maximum_width_px") != 100.0 or health.get("anchor") != "left":
        raise StaticReTestFailure(
            "health fill would lose its 100-pixel left-anchored envelope"
        )
    if health.get("native_fields") != {
        "maximum": "progression+0x6C",
        "current": "progression+0x70",
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
        expected_width = 100.0 * max(0.0, min(current / maximum, 1.0)) ** 2
        if not math.isclose(
            float(sample["visible_width_px"]), expected_width, abs_tol=0.001
        ):
            raise StaticReTestFailure(
                f"{sample['scenario']} health pixels would disagree with the squared native ratio"
            )

    shield = health.get("magic_shield")
    if not isinstance(shield, dict) or shield.get("function") != (
        "second left-anchored width = 100 * clamp(shield_current / shield_maximum, 0, 1)"
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
    if mana.get("function") != "visible_width_px = 100 * clamp(current / maximum, 0, 1)":
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
        "maximum": "progression+0x78",
        "current": "progression+0x7C",
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
        r"^life_width_px = 100 \* r \* r\n"
        r"^life_rect = \[645, 19\.5, 645 \+ life_width_px, 29\.5\]$",
        "binary-free HUD prose would no longer specify the adjacent squared-life formula and rect",
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
        animated_sets: list[list[dict[str, Any]]] = []
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
            animated_sets.append(settle.get("animated_draws", []))
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
    if "def require_one(rows: list[Any], claim: str)" not in recorder or (
        "lookup is ambiguous" not in recorder
    ):
        raise StaticReTestFailure(
            "HUD recorder could silently choose between duplicate native candidates"
        )

    coordinator = _read(SCENE_CAPTURE_PATH)
    hooks = _read(SCENE_CAPTURE_HOOKS_PATH)
    observation = _read(SCENE_CAPTURE_OBSERVATION_PATH)
    public_api = _read(SCENE_CAPTURE_PUBLIC_API_PATH)
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
    return "native HUD recorder is live, self-provenanced, settle-gated, bounded, and visual-diffable"
