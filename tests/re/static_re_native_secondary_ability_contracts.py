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
LIGHTING_DOC = ROOT / "docs/reverse-engineering/native-lighting-and-shadow-system.md"
COOLDOWN_DOC = ROOT / "docs/reverse-engineering/native-secondary-cooldown-and-golem-mana-2026-08-23.md"
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

    if document.get("schema") != "solomon-dark-native-secondary-ability-catalog-v3":
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
            "region_screen_feedback",
        )
        if ability.get("name") != name or ability.get("category") != 2:
            raise StaticReTestFailure(f"skill {skill_id} identity/category drifted")
        if ability.get("disposition") != "closed_native_contract":
            raise StaticReTestFailure(f"skill {skill_id} is no longer closed")
        if any(
            not ability.get(field)
            and field not in {"actors", "region_screen_feedback"}
            for field in expected_fields
        ):
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


def test_native_secondary_cooldown_rows_and_composite_mana_are_closed() -> str:
    document = _load(CATALOG)
    cooldown = document.get("cooldown_system")
    if not isinstance(cooldown, dict):
        raise StaticReTestFailure("secondary catalog lost its cooldown system")
    if cooldown.get("fixed_tick_hz") != 100 or cooldown.get("common_capacity_ticks") != 150:
        raise StaticReTestFailure("secondary fixed/common clock drifted")
    if cooldown.get("constructor") != "0x00674EE0" or cooldown.get("presenter") != "0x005D3E10":
        raise StaticReTestFailure("secondary cooldown constructor/presenter ownership drifted")

    rows = cooldown.get("rows")
    if not isinstance(rows, dict):
        raise StaticReTestFailure("secondary cooldown row table vanished")
    normalized = {int(skill_id): row for skill_id, row in rows.items()}
    if list(normalized) != list(EXPECTED):
        raise StaticReTestFailure("secondary cooldown membership/order drifted")
    fixed = {
        11: 833, 12: 2500, 15: 833, 21: 2500, 23: 50, 27: 1250,
        30: 1250, 35: 2500, 41: 2500, 45: 2500, 46: 10000, 48: 2500,
        49: 2500, 50: 625, 51: 2000, 54: 2500, 72: 2500, 73: 277,
        74: 3750, 76: 1250, 77: 1875, 78: 50, 79: 50,
    }
    if {
        skill_id: row.get("constructor_capacity_ticks")
        for skill_id, row in normalized.items()
    } != fixed:
        raise StaticReTestFailure("secondary constructor capacity table drifted")
    if normalized[15].get("rank_capacity_ticks") != [0, 100]:
        raise StaticReTestFailure("Phasing ranked capacity drifted")
    if normalized[48].get("rank_capacity_ticks") != [
        0, 6000, 3000, 1500, 1000, 500, 400, 300, 100,
    ]:
        raise StaticReTestFailure("Teleport ranked capacities drifted")
    if normalized[23].get("arm") != "toggle-on only; row clears below common 150":
        raise StaticReTestFailure("Firewalker asymmetric arming drifted")
    if any(
        "dispatcher_false" not in normalized[skill_id].get("arm", "")
        for skill_id in (78, 79)
    ):
        raise StaticReTestFailure("actionless toggle cooldown disposition drifted")

    composite = _rows(document, "composite_mana_costs", "skill_id")
    if {
        skill_id: row.get("components") for skill_id, row in composite.items()
    } != {27: [27, 28], 45: [45, 75], 54: [54, 55]}:
        raise StaticReTestFailure("secondary composite mana membership drifted")
    golem = composite[45]
    if golem.get("rank_one_raw_total") != 60 or golem.get("iron_golem_rank_zero_cost") != 50:
        raise StaticReTestFailure("Raise/Iron Golem raw mana composition drifted")
    if any(
        row.get("resolve_once_as_skill_id") != skill_id
        for skill_id, row in composite.items()
    ):
        raise StaticReTestFailure("composite mana no longer resolves once as the base skill")

    correction = read_text(COOLDOWN_DOC)
    for witness in (
        "`0x00674EE0`",
        "| 45 | Raise Golem |",
        "`10+50=60`",
        "Magic Storm 27 + Magic Tornado 28",
        "100-Hz",
    ):
        if witness not in correction:
            raise StaticReTestFailure(f"secondary correction report lost {witness}")
    return "all cooldown rows, clock owners, reset branches, and aggregate mana operands are pinned"


def test_native_secondary_belt_presentation_is_closed() -> str:
    belt = _load(CATALOG).get("belt_presentation")
    if not isinstance(belt, dict):
        raise StaticReTestFailure("secondary catalog lost its belt presentation contract")
    if belt.get("presenter_address") != "0x005D3E10" or belt.get("ownership") != {
        "game_array_offset": "Game+0x5EC",
        "slot_count": 8,
        "slot_stride": "0xEC",
        "slot_index_offset": "+0xE8",
        "logical_size": [53, 53],
        "horizontal_pitch": 60,
    }:
        raise StaticReTestFailure("BeltButton ownership or eight-slot geometry drifted")
    skill_entry = belt.get("skill_entry", {})
    if skill_entry.get("ready_base_rgba") != [1.0, 1.0, 1.0, 0.75]:
        raise StaticReTestFailure("ready skill icon color drifted")
    if skill_entry.get("cooldown_icon_base_rgba") != [1.0, 1.0, 1.0, 0.25]:
        raise StaticReTestFailure("cooldown skill icon color drifted")
    if skill_entry.get("toggle_state_modulation") != "none":
        raise StaticReTestFailure("secondary toggles acquired a non-native belt highlight")
    cooldown = belt.get("cooldown", {})
    if cooldown.get("base_rgba") != [0.5, 0.1, 0.1, 0.75]:
        raise StaticReTestFailure("cooldown sector color drifted")
    if cooldown.get("geometry") != (
        "53x53 square radial fan split at every crossed 45-degree boundary"
    ) or cooldown.get("draw_order") != ["cooldown_square_sector", "skill_icon"]:
        raise StaticReTestFailure("cooldown square-fan geometry or painter order drifted")
    hint = belt.get("input_hint", {})
    if hint.get("bindings") != [
        "0x201", "0x02", "0x03", "0x04", "0x05", "0x06", "0x07", "0x08",
    ] or hint.get("base_rgba") != [1.0, 1.0, 1.0, 0.6]:
        raise StaticReTestFailure("secondary input bindings or hint color drifted")
    keyboard = hint.get("keyboard", {})
    if keyboard != {
        "backing_atlas": "UI",
        "backing_record": 22,
        "backing_natural_size": [15, 15],
        "backing_width": "measured_text_width + 6",
        "backing_left": "(53 - backing_width) / 2",
        "backing_top": 53,
        "font_atlas": "Fonts",
        "font_group": 8,
        "font_records": "535..626",
        "font_header": [10.0, 3.0, 28.0],
        "text_rgba": [0.0, 0.0, 0.0, 1.0],
        "text_center_x": 26.5,
        "text_baseline_y": 64.0,
    }:
        raise StaticReTestFailure("native keyboard plaque/font contract drifted")
    return "BeltButton ownership, cooldown fan, icon state, and all input hints are pinned"


def test_native_secondary_region_screen_feedback_lane_is_closed() -> str:
    document = _load(CATALOG)
    abilities = _rows(document, "abilities", "skill_id")
    expected_writers = {
        11, 12, 15, 21, 23, 30, 35, 41, 46, 48, 49, 50, 54, 73, 74, 76, 78, 79,
    }
    actual_writers = {
        skill_id
        for skill_id, ability in abilities.items()
        if ability.get("region_screen_feedback")
    }
    if actual_writers != expected_writers:
        raise StaticReTestFailure("Region screen-feedback writer membership drifted")
    summary = document.get("summary", {})
    if summary.get("region_screen_feedback_ability_count") != 18:
        raise StaticReTestFailure("Region screen-feedback ability count drifted")
    if summary.get("region_screen_feedback_write_count") != 22:
        raise StaticReTestFailure("Region screen-feedback write count drifted")

    for skill_id, ability in abilities.items():
        rows = ability.get("region_screen_feedback")
        if not isinstance(rows, list):
            raise StaticReTestFailure(f"skill {skill_id} lost its Region screen-feedback ledger")
        for row in rows:
            if row.get("attenuation") not in {"none", "region_point_gain"}:
                raise StaticReTestFailure(f"skill {skill_id} has an invalid Region attenuation owner")
            if not isinstance(row.get("decay_per_tick"), (int, float)) or row["decay_per_tick"] <= 0:
                raise StaticReTestFailure(f"skill {skill_id} has an invalid Region alpha loss")
            colors = row.get("colors")
            if not isinstance(colors, list) or not colors:
                raise StaticReTestFailure(f"skill {skill_id} has no Region flash color")
            if any(
                not isinstance(color, list)
                or len(color) != 4
                or any(not isinstance(channel, (int, float)) or channel < 0 or channel > 1 for channel in color)
                for color in colors
            ):
                raise StaticReTestFailure(f"skill {skill_id} has an invalid Region RGBA row")
            if not row.get("trigger") or not row.get("selection") or not row.get("evidence"):
                raise StaticReTestFailure(f"skill {skill_id} lost Region trigger/selection evidence")

    if abilities[41]["region_screen_feedback"][0] != {
        "trigger": "accepted cast",
        "colors": [[0.8, 1.0, 0.8, 1.0]],
        "selection": "fixed",
        "attenuation": "none",
        "decay_per_tick": 0.025,
        "evidence": ["0x0054DF34", "0x0054DF84"],
    }:
        raise StaticReTestFailure("Earthquake fixed pale-green Region flash drifted")
    if abilities[12]["region_screen_feedback"][1] != {
        "trigger": "each Plane Orb birth",
        "colors": [[1.0, 0.0, 1.0, 0.1]],
        "selection": "retained Planewalker magenta",
        "attenuation": "none",
        "decay_per_tick": 0.1,
        "evidence": ["0x0052DA24"],
    }:
        raise StaticReTestFailure("Plane Orb low-alpha magenta Region flash drifted")
    if [row["attenuation"] for row in abilities[48]["region_screen_feedback"]] != [
        "none", "region_point_gain",
    ]:
        raise StaticReTestFailure("Teleport source/destination overwrite order drifted")
    if len(abilities[50]["region_screen_feedback"][0]["colors"]) != 9:
        raise StaticReTestFailure("Magic Trap selector-color table is incomplete")
    if abilities[50].get("selector_dispatch") != {
        "sentinel": 7,
        "weld_build_ids": [1000, 1009],
        "pure_build_selectors": {
            "1010": 0,
            "1011": 1,
            "1012": 3,
            "1013": 2,
            "1014": 4,
        },
        "planewalker_overrides_selected_build": False,
    }:
        raise StaticReTestFailure("Magic Trap synthetic-build selector dispatch drifted")
    if len(abilities[30]["region_screen_feedback"][0]["colors"]) != 5:
        raise StaticReTestFailure("Prismatic Region palette is incomplete")
    if abilities[76]["region_screen_feedback"][0]["decay_per_tick"] != 0.005:
        raise StaticReTestFailure("Call Comet Region float32 loss drifted")

    effects = read_text(EFFECTS_DOC)
    for evidence in (
        "Region +0x8E14/+0x8E18/+0x8E1C",
        "0x0063EFC0",
        "0x0046EC80",
        "0x00782C70..0x00782DBA",
        "0x0055012C",
    ):
        if evidence not in effects:
            raise StaticReTestFailure(f"Region screen-feedback RE lost {evidence}")
    return "all 23 abilities classify the single Region-owned flash lane and its exact overwrite lifecycle"


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

    if abilities[11]["timing"] != {
        "phases": ["scale_in", "active", "scale_out"],
        "scale_in_updates": 41,
        "active_age_ticks": "41..1640 inclusive (1600 updates)",
        "scale_out_age_ticks": "1640..1664 inclusive (25 updates)",
        "total_live_updates": 1664,
        "first_deployed_active_update": 59,
        "shot_reset_ticks": "75+Integer(26)",
        "bolt_countdown_ticks": 100,
        "bolt_fade_updates": 101,
        "bolt_total_live_updates_without_contact": 200,
    }:
        raise StaticReTestFailure("Call Leviathan overlapping phase and EtherBolt clocks drifted")
    if [row["records"] for row in abilities[11]["art"]] != [
        "343..372", "39", "11", "22", "Ether FadeMM",
    ]:
        raise StaticReTestFailure("Call Leviathan complete portal/appendage/bolt/FadeMM art drifted")
    if abilities[21]["timing"] != {
        "segment_count": 30,
        "angle_step_degrees": 12,
        "segment_rng_words": 7,
        "shockwave_query_period_ticks": 10,
    }:
        raise StaticReTestFailure("Ring of Fire geometry/cadence drifted")
    if abilities[12]["timing"] != {
        "duration": "mDuration * 100 fixed ticks",
        "orb_countdown_ticks": 1000,
        "orb_active_branch_updates": 999,
        "orb_fade_start_age": 1000,
        "orb_fade_scale_per_tick": 0.02,
        "orb_initial_speed": 1.75,
        "orb_initial_scale": 0.5,
        "orb_scale_growth_per_tick": 0.01,
        "orb_acceleration_multiplier": 0.980000019,
        "orb_damage_period_ticks": 6,
        "orb_damage_multiplier": 5,
        "orb_damage_rank_ids": [8, 10, 9, 13, 14, 15, 12],
        "orb_damage_per_tick": "2*sum(effective ranks)/100; excludes Call Leviathan 11",
        "core_rotation_degrees_per_tick": 1.5,
        "mesh_segments": {"normal": 7, "enhanced": 15},
        "mesh_vertices": "1 + 2*N",
        "mesh_triangles": "3*N",
        "mesh_uv": "world_xy / 192 with repeat wrap",
        "birth_particles": 27,
        "birth_particle_rng_words": 180,
        "enhanced_motes_per_active_tick": 1,
        "enhanced_mote_rng_words": 5,
    }:
        raise StaticReTestFailure("Planewalker Plane Orb lifecycle drifted")
    if [row["records"] for row in abilities[12]["art"]] != [
        "75", "etherplane.png", "11,45", "11",
    ]:
        raise StaticReTestFailure("Planewalker Plane Orb art ownership drifted")
    if abilities[12]["audio"][-1].get("pitch") != 2.0:
        raise StaticReTestFailure("Plane Orb lightning-start pitch drifted")
    if abilities[27]["timing"] != {
        "active_ticks": 1000,
        "first_strike_ticks": 50,
        "query_radius": 500,
        "strike_reset_ticks": "uniform integer 30..120, divided by tornado frequency factor",
        "fade_per_tick": 0.01,
        "fade_ticks": 101,
        "tornado_movement_per_tick": 0.349999994,
        "constructor_rng_draws": 31,
        "tornado_constructor_rng_draws": 32,
        "drops_per_tick": 2,
        "enhanced_drops_per_tick": 5,
        "tornado_drops_per_tick": 1,
        "enhanced_tornado_drops_per_tick": 2,
        "flash_decay_per_tick": 0.100000001,
        "ambient_flash_roll": "RandomInt(1000) == 3 every tick; winning roll then consumes Float(0.35)",
        "falling_drop_quad": "local x -1, y height, width 2, positive streak length; transparent top RGBA (0.4,0.95,1,0), half-alpha bottom RGBA (0.8,0.95,1,0.5)",
        "landed_drop_ring": "BadGuys[63] at the ground root, tint (0.8,1,1), alpha 1-scale^2",
    }:
        raise StaticReTestFailure("Magic Storm geometry/lifecycle drifted")
    if [row["records"] for row in abilities[27]["art"]] != [
        "11,63,78,84",
        "width-2 transparent-top/half-alpha-bottom blue-white quad",
        "three BadGuys-78 passes plus moving and white-mask branches",
    ]:
        raise StaticReTestFailure("Magic Storm cloud/drop art ownership drifted")
    if abilities[30]["targeting"] != "caster_center_radius_350":
        raise StaticReTestFailure("Prismatic immediate radius-350 targeting drifted")
    if abilities[30]["timing"] != {
        "duration": "mDuration * 100 fixed ticks",
        "spray_emission_ticks": 100,
        "children_per_emission_tick": 3,
        "rng_words_per_emission_tick": 19,
    }:
        raise StaticReTestFailure("Prismatic spray emission lifecycle drifted")
    if [row["records"] for row in abilities[30]["art"]] != ["58", "111", "10,11"]:
        raise StaticReTestFailure("Prismatic exact parent/child atlas ownership drifted")
    if abilities[35]["timing"] != {
        "initial_life": 0.924,
        "life_per_tick": 0.01,
        "initial_radius": 75,
        "radius_per_tick": 6,
        "query_period_ticks": 10,
        "lifetime_ticks": 93,
        "ice_blast_count": 3,
        "normal_whirl_snow_count": 100,
        "enhanced_whirl_snow_count": 200,
        "presentation_rng_draws": "3 + 8*N (803 normal, 1603 enhanced)",
        "maximum_child_lifetime_ticks": 175,
    }:
        raise StaticReTestFailure("Ring of Ice expansion/lifecycle drifted")
    if abilities[35]["art"][0]["records"] != "114,121":
        raise StaticReTestFailure("Ring of Ice exact DeadHawg records drifted")
    skills_doc = read_text(SKILLS_DOC)
    if "`DeadHawg[114,121]` plus `BadGuys[72]` for Ring of Ice" not in skills_doc:
        raise StaticReTestFailure("Ring of Ice complete presentation census vanished")
    if "`DeadHawg[16,17]` for Ring of Ice" in skills_doc:
        raise StaticReTestFailure("Ring of Ice regressed to refuted DeadHawg records 16/17")
    if abilities[41]["timing"] != {
        "duration": "mDuration * 100 fixed ticks",
        "disrupt_period_ticks": 30,
        "disrupt_clock": "post-decrement remaining % 30 == 0",
        "floor_phase_start": -5,
        "floor_phase_per_tick": 0.05,
        "floor_thresholds": [0.6, 3.0],
        "quake_child_lifetime_ticks": 180,
        "enhanced_dust_lifetime_ticks": 360,
    }:
        raise StaticReTestFailure("Earthquake authoritative and child clocks drifted")
    if [row["records"] for row in abilities[41]["art"]] != [
        "200..202", "62", "10", "2008..2010",
    ]:
        raise StaticReTestFailure("Earthquake complete floor/quake/dust/boulder art drifted")
    if [row["path"] for row in abilities[41]["audio"]] != [
        "sounds/earthquake__loop.wav",
        "sounds/rockhit.wav",
        "sounds/QuakeCracks__Stream.wav",
        "sounds/QuakeCrackSmall__Stream.wav",
    ]:
        raise StaticReTestFailure("Earthquake birth, loop, and threshold audio drifted")
    if abilities[41]["rng"] != {
        "cast": "Float(360) floor rotation, then N Integer(N) scenery-shuffle draws",
        "pulse": "N Integer(N) hostile-shuffle draws; per local visit Integer(2), optional Integer(50), Sign(15); optional Anim_Quake Float(360), Integer(4)",
        "per_tick": "one scenery Sign(1), Float(1.5); enhanced Integer(30) dust gate and exact dust children; Integer(15) boulder gate and exact Anim_Bouncer/Anim_BoulderBit constructor sequence",
    }:
        raise StaticReTestFailure("Earthquake native RNG ownership drifted")
    if abilities[45]["targeting"] != "caster_heading_plus_or_minus_45_at_100_then_collision_adjusted":
        raise StaticReTestFailure("Golem cursor-independent signed placement target drifted")
    if abilities[45]["timing"] != {
        "placement_distance": 100,
        "placement_radius": 25,
        "placement_mask": "0x205 without actor flag 0x400",
        "placement_ring_count": "round-even(pi * (searchRadius + 25) / searchRadius)",
        "placement_ring_geometry": "x radius searchRadius; y radius searchRadius * 0.8",
        "placement_ring_expansion": "searchRadius += multiplier*25; multiplier *= 1+Float(1)",
        "assembly_milestones": [0, 50, 100, 200],
        "contact_enable_age": 400,
        "natural_expiry": False,
    }:
        raise StaticReTestFailure("Golem assembly/contact lifecycle drifted")
    if abilities[45]["rng"] != {
        "cast_prefix": "Sign(45), then blocked placement rings each consume Float(360) and failed rings Float(1)",
        "constructor": "Integer(2) alternating-limb selector after placement",
    }:
        raise StaticReTestFailure("Golem placement and constructor RNG ordering drifted")
    if [row["trigger"] for row in abilities[23]["audio"]] != [
        "toggle-on activation with native pitch triplet; toggle-off is silent",
        "renewed by live fire patches",
    ]:
        raise StaticReTestFailure("Firewalker toggle-off audio silence drifted")
    if [row["trigger"] for row in abilities[46]["audio"]] != [
        "accepted cast",
        "modifier apply, refresh, and removal callbacks",
    ]:
        raise StaticReTestFailure("Stoneskin callback audio lifecycle drifted")
    if [row["path"] for row in abilities[45]["audio"]] != [
        "sounds/QuakeCrackSmall__Stream.wav",
        "sounds/GolemProvoke__Stream.wav",
        "sounds/KnockbackGolem.wav",
        "sounds/stonestep.wav",
        "sounds/stonebreak.wav",
        "sounds/flamelashstart.wav",
        "sounds/GolemDie__Stream.wav",
        "sounds/rockhit.wav",
    ]:
        raise StaticReTestFailure("Golem complete assembly/AI/death audio census drifted")
    if abilities[49]["timing"] != {
        "lifetime_ticks": 1500,
        "effect_period_ticks": 10,
        "first_effect_update": 0,
        "ring_children_even_tick": 1,
        "ring_children_odd_tick": 2,
        "ring_child_loss_per_tick": 0.05,
    }:
        raise StaticReTestFailure("Magic Circle pulse/emitter lifecycle drifted")
    if [row["records"] for row in abilities[49]["art"]] != ["48", "7"]:
        raise StaticReTestFailure("Magic Circle ring/player-pulse atlas ownership drifted")
    if abilities[50]["timing"] != {
        "damage_selector_skill_ids": [8, 16, 24, 32, 40],
        "ether_damage_range_properties": ["mDamage1", "mDamage2"],
        "ether_damage_rng_words": 1,
        "non_ether_damage_rng_words": 0,
        "full_payload_formula": "f32(baseDamage * trap mDamage[effective rank])",
        "terminal_payload_formula": "f32(fullPayload * charge); no minimum clamp",
        "water_slow_factor": "f32(0.5 / permafrostSlowScale)",
        "water_slow_duration_ticks": "max(50,trunc(400*charge))",
        "full_charge_ticks": 800,
        "trigger_poll_period_ticks": 25,
        "arming_footprint_width": 130,
        "payload_footprint_width": 300,
        "armed_shimmer_emission_ticks": 32,
        "armed_shimmer_rng_words_per_tick": 2,
        "trigger_presentation_rng_words": 502,
        "electric_burn_duration_ticks": 100,
        "electric_burn_damage_divisor": 100,
        "electric_burn_light_base_radius": 0.5,
        "electric_burn_light_intensity": 1,
        "electric_burn_signed_jitter_bound": 0.25,
        "electric_burn_integer_bound": 3,
        "electric_burn_conditional_float_bound": 0.5,
        "electric_burn_chain_count": 0,
        "camera_pulse_initial": 1.25,
        "camera_pulse_multiplier_per_tick": 0.94,
        "camera_pulse_cutoff": 0.001,
    }:
        raise StaticReTestFailure("Magic Trap charge/trigger cadence drifted")
    if [row["records"] for row in abilities[50]["art"]] != [
        "111,112,15,85", "16", "158..167,15,17,74", "333..342",
    ]:
        raise StaticReTestFailure("Magic Trap complete armed/shimmer/terminal art drifted")
    effects_doc = read_text(EFFECTS_DOC)
    if "BadGuys 111,112,15,85,16,158..167,17,74; fire modifier 333..342" not in effects_doc:
        raise StaticReTestFailure("Magic Trap class census lost its complete shipped art")
    if "BadGuys 16, 110..112, 393..400" in effects_doc:
        raise StaticReTestFailure("Magic Trap class census regressed to loaded-but-undrawn records")
    if [row["path"] for row in abilities[50]["audio"]] != [
        "sounds/settrap__Stream.wav",
        "sounds/magicmissile.wav",
        "sounds/throwfire.wav",
        "sounds/lightningstart.wav",
        "sounds/icestart.wav",
        "sounds/startboulder.wav",
        "sounds/trap__stream.wav",
        "sounds/electric__loop.wav",
    ]:
        raise StaticReTestFailure("Magic Trap set/bound-primary/trigger/modifier audio order drifted")
    if abilities[54]["timing"] != {
        "hit_pulse_ticks": 40,
        "hit_pulse_start": 2.0,
        "hit_pulse_decay_per_tick": 0.05,
        "break_children": 20,
        "break_rng_words": 60,
        "explosion_visual_rng_words": 502,
        "explosion_contact_radius": 110,
        "sprite_array_frame_rates": [0.15, 0.225],
        "fuzzy_spear_children": 100,
        "shockwave_initial_radius": 75,
        "shockwave_radius_per_tick": 6,
        "shockwave_initial_life": 0.35,
        "shockwave_fade_threshold": 0.0375,
        "camera_pulse_initial": 1.25,
        "camera_pulse_decay_per_tick": 0.94,
    }:
        raise StaticReTestFailure("Magic Shield pulse lifecycle drifted")
    if [row["records"] for row in abilities[54]["art"]] != [
        "49", "68", "15", "2", "158..167", "17,74", "18",
    ]:
        raise StaticReTestFailure("Magic Shield complete art membership drifted")
    if abilities[72]["timing"] != {
        "active_ticks": 1500,
        "initial_pulse_delay_ticks": 50,
        "damage_period_ticks": 25,
        "contact_damage_formula": "f32(mDamage[effective rank] / 6)",
        "target_query": "supplied width 400; strict root-center distance squared < 200*200; hostile mask 2; Coffin type 0xBB9 excluded; no body-radius expansion",
        "cloud_rotation_owner": "actor +0x148 fixed-tick age with constructor phase +0x14C; never renderer frame cadence",
        "cloud_pass_source_over": "world-sorted BadGuys[78] at y -175, tint (0.41,0.55,0.32), alpha 0.75*c, rotation a*0.03125*p degrees, scale (5*s,4*s)",
        "cloud_pass_additive": "world-sorted additive BadGuys[78] with the identical first-pass transform",
        "cloud_circle_additive": "world-sorted additive BadGuys[10] at y -175-50*s, tint (0.25,0.45,0.15), alpha c, rotation -0.5*a degrees, scale (7.5*s*p,6*s)",
        "residue_pass": "pre-world source-over DeadHawg[4] at the ground root, tint (0.05,0.1,0.05), residue alpha, uniform scale 4.5",
        "falling_drop_quad": "local x -1, y height, width 3, positive streak length; transparent top RGBA (0.4,0.95,0.5,0), half-alpha bottom RGBA (0.7,0.95,0.75,0.5)",
        "falling_drop_marker": "quarter-alpha BadGuys[0] remains at the ground root while the streak falls",
        "landed_drop_ring": "BadGuys[63] at the ground root, tint (0.8,1,0.8), alpha 1-scale^2",
        "drops_per_tick": 2,
        "enhanced_drops_per_tick": 5,
        "splash_gate": "Integer(4)==3 after raindrop allocation",
        "maximum_lifetime_ticks": 3600,
        "targets_per_pulse": "min(n, floor(n/3)+1)",
    }:
        raise StaticReTestFailure("Acid Rain exact damage and shuffled target count drifted")
    if [row["records"] for row in abilities[72]["art"]] != [
        "0,10,63,78",
        "4",
        "width-3 transparent-top/half-alpha-bottom green quad",
    ]:
        raise StaticReTestFailure("Acid Rain complete cloud/drop/residue art membership drifted")
    if abilities[74]["timing"] != {
        "nominal_scale_in_ticks": 40,
        "scale_in_ticks": 41,
        "active_ticks": 1000,
        "scale_out_ticks": 20,
        "phases": ["scale_in", "active", "scale_out"],
        "total_live_updates": 1061,
        "gameplay_age_ticks": "41..990 inclusive (950 ticks)",
        "child_spawn_age_ticks": "42..990 inclusive (949 ticks)",
        "candidate_refresh_age_ticks": "1,18,35,105,205,...,1005",
        "suck_cloud_success_rng_words": 8,
        "suck_debris_success_rng_words": 5,
        "suck_debris_rng_words_per_tick": 3,
        "contact_damage_tiers": "d2<400: 1x; d2<225: 2x; d2<100: 4x; target flag 0x1 doubles again",
        "contact_rng_words": "one Float(0.5) per hostile dispatch",
    }:
        raise StaticReTestFailure("Ether Drain fixed-tick lifecycle drifted")
    if [row["records"] for row in abilities[74]["art"]] != [
        "75", "38", "10..11", "177..179", "36", "radius 2",
    ]:
        raise StaticReTestFailure("Ether Drain complete parent/child art membership drifted")
    if abilities[76]["timing"] != {
        "fall_ticks": 400,
        "warning_post_update_ticks_remaining": 174,
        "query_radius": 400,
        "trail_life": "0.5*(0.5+Float(0.5)), decay 0.025",
        "impact": "when actor +0x14C countdown reaches zero",
        "impact_additive_fade_ticks": 500,
        "impact_ring_fade_ticks": 1000,
        "debris_life_decay": "0.015 on each non-skipped airborne update and every settled update",
        "debris_bounce_damping": 0.65,
        "debris_gravity": 0.4,
        "screen_flash": "RGBA (1,1,1,1), repeated float32 alpha decay 0.005; nominal 200 ticks and clamps on update 201",
    }:
        raise StaticReTestFailure("Call Comet fall/trail lifecycle drifted")
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
    lighting = read_text(LIGHTING_DOC)
    generator = read_text(GENERATOR)
    witnesses = {
        "skills": (
            "### Complete right-click presentation and lifecycle contract",
            "native-secondary-ability-catalog.json",
            "### Native secondary belt presenter",
            "cooldown square fan",
            "BadGuys[11,22,39,343..372]",
            "0x0054FF05",
            "0x0054FFD4",
        ),
        "effects": (
            "min(n, floor(n / 3) + 1)",
            "compiled double `6.0`",
            "scale `(7.5*s*p,6*s)`",
            "uniform scale `4.5`",
            "BadGuys[78]",
            "BadGuys[63]",
            "DeadHawg[4]",
            "two `Anim_AcidRaindrop`",
            "five while",
            "100 * 10 = 1,000",
            "**post-decrement** `remaining % 30 == 0`",
            "`Anim_BoulderBit`",
        ),
        "audio": (
            "### Secondary and advanced right-click events",
            "Call Leviathan `11`",
            "Mindstar `78` / Regenerate `79`",
            "Stoneskin `46`",
        ),
        "lighting": (
            "### Website-modeled right-click actor dispositions",
            "MovingFire, Fire_Goodguy",
            "EtherFade variant one",
            "radius `0.5+S(0.25)`, intensity 1",
            "intensity `min(remainingTicks/50,1)`",
            "target's embedded Action manager at `actor+0x104`",
            "creator registration and a tick-local",
            "append ordinal for each synchronous batch",
        ),
        "generator": (
            "SECONDARY_IDS = (",
            "BELT_PRESENTATION = {",
            "COOLDOWN_ROWS:",
            "COMPOSITE_MANA_COSTS = [",
            "CONTRACTS:",
            '"closed_native_contract"',
            "unresolved audio path",
        ),
    }
    documents = {
        "skills": skills,
        "effects": effects,
        "audio": audio,
        "lighting": lighting,
        "generator": generator,
    }
    for name, tokens in witnesses.items():
        missing = [token for token in tokens if token not in documents[name]]
        if missing:
            raise StaticReTestFailure(f"secondary {name} contract lost witnesses {missing}")
    return "right-click RE prose, lighting ownership/order, audio census, and generator are wired"
