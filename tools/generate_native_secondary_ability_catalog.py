#!/usr/bin/env python3
"""Build the closed stock right-click ability catalog from checked-in RE data."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RE = ROOT / "docs" / "reverse-engineering"
OUTPUT = RE / "native-secondary-ability-catalog.json"
SKILLS = RE / "native-skill-catalog.json"
AUDIO = RE / "native-audio-catalog.json"

SECONDARY_IDS = (
    11, 12, 15, 21, 23, 27, 30, 35, 41, 45, 46, 48,
    49, 50, 51, 54, 72, 73, 74, 76, 77, 78, 79,
)

COOLDOWN_ROWS: dict[int, dict[str, Any]] = {
    11: {"constructor_capacity_ticks": 833, "capacity_source": "0x007A0CBC", "arm": "dispatcher_true"},
    12: {"constructor_capacity_ticks": 2500, "capacity_source": "0x00786C18", "arm": "both_toggle_edges"},
    15: {
        "constructor_capacity_ticks": 833,
        "capacity_source": "0x00661530 mCooldown[effectiveRank]*100",
        "rank_capacity_ticks": [0, 100],
        "arm": "dispatcher_true; rank-one row clears below common 150",
    },
    21: {"constructor_capacity_ticks": 2500, "capacity_source": "0x00786C18", "arm": "dispatcher_true"},
    23: {"constructor_capacity_ticks": 50, "capacity_source": "0x00784CF8", "arm": "toggle-on only; row clears below common 150"},
    27: {"constructor_capacity_ticks": 1250, "capacity_source": "0x007A0CC8", "arm": "dispatcher_true"},
    30: {"constructor_capacity_ticks": 1250, "capacity_source": "0x007A0CC8", "arm": "dispatcher_true"},
    35: {"constructor_capacity_ticks": 2500, "capacity_source": "0x00786C18", "arm": "dispatcher_true"},
    41: {"constructor_capacity_ticks": 2500, "capacity_source": "0x00786C18", "arm": "dispatcher_true"},
    45: {"constructor_capacity_ticks": 2500, "capacity_source": "0x00786C18", "arm": "dispatcher_true"},
    46: {"constructor_capacity_ticks": 10000, "capacity_source": "0x00786C08", "arm": "dispatcher_true"},
    48: {
        "constructor_capacity_ticks": 2500,
        "capacity_source": "0x00661530 mCooldown[effectiveRank]*100",
        "rank_capacity_ticks": [0, 6000, 3000, 1500, 1000, 500, 400, 300, 100],
        "arm": "dispatcher_true; rank-eight row clears below common 150",
    },
    49: {"constructor_capacity_ticks": 2500, "capacity_source": "0x00786C18", "arm": "dispatcher_true"},
    50: {"constructor_capacity_ticks": 625, "capacity_source": "0x0078CC68", "arm": "dispatcher_true"},
    51: {"constructor_capacity_ticks": 2000, "capacity_source": "0x00785CF0", "arm": "dispatcher_true plus CastSpin"},
    54: {"constructor_capacity_ticks": 2500, "capacity_source": "0x00786C18", "arm": "dispatcher_true"},
    72: {"constructor_capacity_ticks": 2500, "capacity_source": "0x00786C18", "arm": "dispatcher_true"},
    73: {"constructor_capacity_ticks": 277, "capacity_source": "0x007A0CC4", "arm": "dispatcher_true"},
    74: {"constructor_capacity_ticks": 3750, "capacity_source": "0x007A0CC0", "arm": "dispatcher_true"},
    76: {"constructor_capacity_ticks": 1250, "capacity_source": "0x007A0CC8", "arm": "dispatcher_true"},
    77: {"constructor_capacity_ticks": 1875, "capacity_source": "0x007A0CCC", "arm": "dispatcher_true"},
    78: {"constructor_capacity_ticks": 50, "capacity_source": "0x00784CF8", "arm": "dispatcher_false; no cooldown or action"},
    79: {"constructor_capacity_ticks": 50, "capacity_source": "0x00784CF8", "arm": "dispatcher_false; no cooldown or action"},
}

COOLDOWN_SYSTEM = {
    "constructor": "0x00674EE0",
    "dynamic_rank_refresh": "0x00661530",
    "belt_gate": "0x005D5600",
    "dispatcher": "0x0054CC50",
    "arming": ["0x00661F40", "0x0065EDE0"],
    "recurrence": "0x00656E70",
    "presenter": "0x005D3E10",
    "fixed_tick_hz": 100,
    "common_capacity_ticks": 150,
    "common_capacity_source": "0x0078489C",
    "rows": COOLDOWN_ROWS,
    "reset": "Full rejuvenation clears common and category-2 currents; owner teardown removes private state.",
}

COMPOSITE_MANA_COSTS = [
    {
        "skill_id": 27,
        "components": [27, 28],
        "resolve_once_as_skill_id": 27,
        "evidence": ["0x0054CC50", "0x006741B0", "0x006600F0"],
    },
    {
        "skill_id": 45,
        "components": [45, 75],
        "resolve_once_as_skill_id": 45,
        "rank_one_raw_total": 60,
        "iron_golem_rank_zero_cost": 50,
        "evidence": ["0x0054E4E0", "0x0054E4F7", "0x006741B0", "0x005290F0", "0x0065D540", "0x006600F0"],
    },
    {
        "skill_id": 54,
        "components": [54, 55],
        "resolve_once_as_skill_id": 54,
        "evidence": ["0x0054CC50", "0x006741B0", "0x006600F0"],
    },
]

BELT_PRESENTATION = {
    "presenter": "BeltButton::Present",
    "presenter_address": "0x005D3E10",
    "ownership": {
        "game_array_offset": "Game+0x5EC",
        "slot_count": 8,
        "slot_stride": "0xEC",
        "slot_index_offset": "+0xE8",
        "logical_size": [53, 53],
        "horizontal_pitch": 60,
    },
    "skill_entry": {
        "kind": "0x1B67",
        "icon_atlas": "Skills",
        "ready_base_rgba": [1.0, 1.0, 1.0, 0.75],
        "cooldown_icon_base_rgba": [1.0, 1.0, 1.0, 0.25],
        "toggle_state_modulation": "none",
    },
    "scene_modulation": {
        "test": "gameplay+0x1AC2 == 0",
        "hub_rgb_multiplier": [0.25, 0.25, 0.25],
        "alpha_multiplier": 1.0,
    },
    "cooldown": {
        "remaining_offset": "skill_entry+0x64",
        "capacity_offset": "skill_entry+0x68",
        "fixed_tick_hz": 100,
        "base_rgba": [0.5, 0.1, 0.1, 0.75],
        "start_degrees": "360 * (1 - remaining / capacity)",
        "covered_interval": "[start_degrees, 360]",
        "geometry": "53x53 square radial fan split at every crossed 45-degree boundary",
        "draw_order": ["cooldown_square_sector", "skill_icon"],
    },
    "input_hint": {
        "bindings": ["0x201", "0x02", "0x03", "0x04", "0x05", "0x06", "0x07", "0x08"],
        "base_rgba": [1.0, 1.0, 1.0, 0.6],
        "mouse_records": {"left": 98, "middle": 99, "right": 100},
        "mouse_center": [26.5, 60.0],
        "keyboard": {
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
        },
    },
}


def actor(type_id: str, name: str) -> dict[str, str]:
    return {"type_id": type_id, "name": name}


def art(atlas: str, records: str, owner: str, mode: str) -> dict[str, str]:
    return {"atlas": atlas, "records": records, "owner": owner, "mode": mode}


def sound(
    path: str,
    trigger: str,
    mode: str = "one_shot",
    *,
    pitch: float | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {"path": path, "trigger": trigger, "mode": mode}
    if pitch is not None:
        row["pitch"] = pitch
    return row


def region_flash(
    trigger: str,
    colors: list[list[float]],
    selection: str,
    attenuation: str,
    decay_per_tick: float,
    *evidence: str,
) -> dict[str, Any]:
    return {
        "trigger": trigger,
        "colors": colors,
        "selection": selection,
        "attenuation": attenuation,
        "decay_per_tick": decay_per_tick,
        "evidence": list(evidence),
    }


TRAP_SELECTOR_COLORS = [
    [1.0, 0.1, 1.0, 1.0],
    [1.0, 0.35, 0.1, 1.0],
    [0.1, 1.0, 1.0, 1.0],
    [0.1, 0.5, 1.0, 1.0],
    [0.1, 1.0, 0.1, 1.0],
    [1.0, 0.5, 0.1, 1.0],
    [0.1, 0.5, 0.5, 1.0],
    [0.75, 0.75, 0.75, 1.0],
    [1.0, 1.0, 1.0, 1.0],
]


REGION_SCREEN_FEEDBACK: dict[int, list[dict[str, Any]]] = {
    11: [region_flash("first scale-in update", [[1.0, 0.5, 1.0, 1.0]], "fixed", "region_point_gain", 0.05, "0x006145D0")],
    12: [
        region_flash("enable only", [[1.0, 0.0, 1.0, 1.0]], "fixed", "none", 0.1, "0x00548700"),
        region_flash("each Plane Orb birth", [[1.0, 0.0, 1.0, 0.1]], "retained Planewalker magenta", "none", 0.1, "0x0052DA24"),
    ],
    15: [region_flash("accepted traversal", [[0.0, 1.0, 1.0, 1.0]], "fixed", "region_point_gain", 0.025, "0x0052A220", "0x00645B50")],
    21: [region_flash("ring creation", [[1.0, 0.5, 0.0, 1.0]], "fixed", "region_point_gain", 0.01, "0x0063F920")],
    23: [region_flash("every on/off toggle", [[1.0, 0.5, 0.0, 1.0]], "fixed", "region_point_gain", 0.1, "0x0054CDAB")],
    27: [],
    30: [region_flash(
        "wave creation",
        [[1.0, 0.0, 0.0, 1.0], [1.0, 0.5, 0.0, 1.0], [1.0, 1.0, 0.0, 1.0], [0.0, 1.0, 0.0, 1.0], [0.0, 1.0, 1.0, 1.0]],
        "RandomInt(5)",
        "region_point_gain",
        0.05,
        "0x00452C50",
        "0x00645540",
    )],
    35: [region_flash("wave creation", [[0.9, 1.0, 1.0, 1.0]], "fixed", "region_point_gain", 0.01, "0x00644460")],
    41: [region_flash("accepted cast", [[0.8, 1.0, 0.8, 1.0]], "fixed", "none", 0.025, "0x0054DF34", "0x0054DF84")],
    45: [],
    46: [region_flash("accepted cast", [[1.0, 1.0, 1.0, 1.0]], "fixed", "none", 0.1, "0x0054D87B", "0x0054D8B5")],
    48: [
        region_flash("source burst, overwritten next", [[1.0, 1.0, 1.0, 1.0]], "fixed", "none", 0.025, "0x0054D6AC", "0x00644A00"),
        region_flash("destination burst", [[1.0, 1.0, 1.0, 1.0]], "fixed", "region_point_gain", 0.025, "0x0054D700", "0x00644A00"),
    ],
    49: [region_flash("lifetime counter reaches 1498", [[0.75, 1.0, 1.0, 1.0]], "fixed", "region_point_gain", 0.1, "0x006006E0")],
    50: [
        region_flash("trap initialization", TRAP_SELECTOR_COLORS, "trap selector 0..8", "none", 0.1, "0x005E95D0", "0x00782C70"),
        region_flash("one-shot trigger", TRAP_SELECTOR_COLORS, "trap selector 0..8", "region_point_gain", 0.05, "0x005F5C80", "0x00782C70"),
    ],
    51: [],
    54: [
        region_flash("shield apply or refresh", [[0.5, 1.0, 1.0, 1.0]], "fixed", "region_point_gain", 0.1, "0x00529EE0"),
        region_flash("Explosive Shield break", [[0.5, 1.0, 1.0, 1.0]], "fixed", "region_point_gain", 0.05, "0x00648790"),
    ],
    72: [],
    73: [region_flash("wall creation", [[1.0, 0.5, 0.0, 1.0]], "fixed", "region_point_gain", 0.1, "0x0054F6E0")],
    74: [region_flash("first scale-in update", [[1.0, 0.5, 1.0, 1.0]], "fixed", "region_point_gain", 0.05, "0x0061CF20")],
    76: [region_flash("impact", [[1.0, 1.0, 1.0, 1.0]], "fixed", "none", 0.005, "0x0061E9C0")],
    77: [],
    78: [region_flash("every on/off toggle", [[0.0, 0.5, 1.0, 1.0]], "fixed", "region_point_gain", 0.1, "0x0054FF5E")],
    79: [region_flash("every on/off toggle", [[1.0, 0.5, 0.0, 1.0]], "fixed", "region_point_gain", 0.1, "0x0055002D")],
}


CONTRACTS: dict[int, dict[str, Any]] = {
    11: {
        "targeting": "aimed_world_point",
        "trigger": "press_edge",
        "actors": [actor("0x7F2", "Leviathan"), actor("0x7F3", "EtherBolt")],
        "gameplay": "Ordinary casts choose an inclusive [1,mQuantity] appendage count; the complete Bug-Master outfit forces mQuantity and doubles Call Leviathan damage. Authored appendages deploy, acquire the nearest visible target in a 50-degree/300-unit lane, track by identity, and fire straight radius-10 EtherBolts.",
        "timing": {
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
        },
        "art": [
            art("BadGuys", "343..372", "Leviathan appendage/body compositor", "world_depth_sorted"),
            art("BadGuys", "39", "central portal normal plus half-alpha additive redraw", "mixed"),
            art("BadGuys", "11", "enhanced additive-perspective mote", "additive"),
            art("BadGuys", "22", "EtherBolt", "additive"),
            art("procedural", "Ether FadeMM", "shot and contact compositor; contact also owns ZAnimLit", "zanim"),
        ],
        "audio": [
            sound("sounds/LeviathanRoar__Stream.wav", "Leviathan activation", "stream"),
            sound("sounds/PlaneCross__Loop.wav", "renewed while the ether actor is active", "ambient_loop_request"),
        ],
        "authority": "Caster authority selects targets, creates EtherBolts, and applies their contacts; presentation actors are replicated snapshots.",
        "cleanup": "Leviathan owns its appendage list and retires on age 1664 after overlapping active/fade edges; EtherBolts remain contact-active through 101 fade updates and retire on contact or update 200; registered FadeMM/motes finish independently; region teardown stops loop renewal.",
        "evidence": ["0x0054CC50", "0x006145D0", "0x006151D0", "0x006034F0"],
    },
    12: {
        "targeting": "self",
        "trigger": "toggle_or_expiry",
        "actors": [
            actor("0x1B75", "Mod_Planewalker"),
            actor("0x7EF", "PlaneOrb"),
            actor("animation", "Anim_FadeMoveAdditive_Perspective"),
        ],
        "gameplay": "Enable matterless plane state for mDuration, save the prior primary, force runtime skill 80 Plane Orb, merge by maximum remaining duration, and restore the saved primary on toggle-off or expiry. Plane Orb stores per-tick damage 2*sum(effective ranks 8,10,9,13,14,15,12)/100; Call Leviathan 11 is deliberately excluded. Each aimed orb advances without terrain collision on every update, runs 999 active-branch updates before fade starts at age 1000, grows to 1+Float(1.5), damages every hostile in its scale-sized query every sixth active authority update, owns the exact textured disc/core/birth burst, and emits an exact enhanced mote on every active-branch update.",
        "timing": {
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
        },
        "art": [
            art("BadGuys", "75", "PlaneOrb additive core", "additive_world"),
            art("images", "etherplane.png", "PlaneOrb center fan plus annulus special pass", "normal_repeating_world_uv_mesh"),
            art("BadGuys", "11,45", "27 Anim_FadeMoveAdditive_Perspective birth particles", "additive_world"),
            art("BadGuys", "11", "one enhanced perspective mote per active-branch update", "additive_world"),
        ],
        "audio": [
            sound("sounds/planewalker__Stream.wav", "enable", "stream"),
            sound("sounds/PlanewalkerOff__Stream.wav", "disable or modifier expiry", "stream"),
            sound("sounds/PlaneCross__Loop.wav", "renewed while plane state is active", "ambient_loop_request"),
            sound("sounds/distortreality.wav", "each Plane Orb birth at Region point gain"),
            sound("sounds/lightningstart.wav", "each Plane Orb birth at Region point gain", pitch=2.0),
        ],
        "authority": "The authoritative player owns modifier duration, collision flag 0x10, saved-primary restoration, and Plane Orb contacts.",
        "cleanup": "Modifier removal at 0x00623810 calls 0x0052F470, clears plane state, restores selection, and stops renewing plane ambience. Plane Orbs shrink by 0.02 after their active countdown; registered perspective children finish independently.",
        "evidence": ["0x0054CC50", "0x00548700", "0x00623800", "0x00623810", "0x0052F470", "0x00626A60", "0x0052D8C0", "0x0052D360", "0x005E2180", "0x005E2230", "0x005FB460", "0x005E8720", "0x00601910", "0x005BBD90"],
    },
    15: {
        "targeting": "aim_heading_forward_probe",
        "trigger": "press_edge_with_skill_cooldown",
        "actors": [],
        "gameplay": "Probe at most 20 forward positions along cast heading, relocate to the first collision-clear point, and update world membership atomically.",
        "timing": {"probe_limit": 20, "cooldown": "mCooldown * 100 fixed ticks"},
        "art": [art("BadGuys", "53", "Anim_FadeAdditive traversal markers", "additive_world")],
        "audio": [sound("sounds/phase.wav", "accepted relocation")],
        "authority": "Only the authoritative simulation resolves collision and commits the destination; observers consume the resulting position and traversal event.",
        "cleanup": "Traversal children are world-owned and self-expire; rejected probes spend no extra cooldown beyond the native cast gate.",
        "evidence": ["0x0054CC50", "0x0052A0B0", "0x0063FEE0"],
    },
    21: {
        "targeting": "caster_center",
        "trigger": "press_edge",
        "actors": [actor("0x7E6", "MovingFire"), actor("0x7E7", "Shockwave")],
        "gameplay": "Create exactly 30 visual MovingFire segments at 12-degree steps and one expanding Shockwave; the wave writes half damage to each of two lanes (summed to full mDamage), adds Burn/Dazzle once per target, and pushes tracked targets by unnormalized delta times the fixed radius growth.",
        "timing": {"segment_count": 30, "angle_step_degrees": 12, "segment_rng_words": 7, "shockwave_query_period_ticks": 10},
        "art": [
            art("DeadHawg", "46..77", "MovingFire frame strip", "additive_world"),
            art("DeadHawg", "18", "Shockwave Region-light submission", "region_light"),
            art("BadGuys", "333..342", "target-owned Mod_Burn flame cycle", "additive_world"),
        ],
        "audio": [
            sound("sounds/bigfire.wav", "ring creation"),
            sound("sounds/nuke.wav", "shockwave creation"),
        ],
        "authority": "Caster authority consumes the seven-word construction program per segment, creates the wave, owns unique-target contact/Burn, and applies radial displacement.",
        "cleanup": "Each fire segment follows Fire lifetime/fade; Shockwave removes itself after expansion and releases its unique-target list.",
        "evidence": ["0x0054CC50", "0x0063F920", "0x005FF8C0", "0x00610F90"],
    },
    23: {
        "targeting": "self_trail",
        "trigger": "toggle",
        "actors": [actor("0x7EE", "Fire_Goodguy")],
        "gameplay": "Toggle progression +0x8DC; toggle-on immediately emits one damage-enabled Fire_Goodguy, then the player tick emits another patch on every global tick divisible by ten while mode is not 2. The periodic path cycles its contact-geometry byte true,false,false globally and reserves exactly 50 MP as an absolute hoard.",
        "timing": {
            "activation_patch": "immediate; contact geometry forced on; does not advance the periodic global cycle",
            "patch_lifetime": "mDuration * (1.1 - RandomFloat(0.25)), decremented by float32 0.01",
            "contact_period_ticks": 3,
            "construction_rng_words": 7,
            "periodic_patch_global_ticks": 10,
            "periodic_contact_geometry_cycle": [True, False, False],
            "mana_reserve": 50,
        },
        "art": [
            art("DeadHawg", "46..77", "Fire_Goodguy animation", "additive_world"),
            art("BadGuys", "333..342", "target-owned Mod_Burn flame cycle", "additive_world"),
        ],
        "audio": [
            sound("sounds/ignite.wav", "toggle-on activation with native pitch triplet; toggle-off is silent"),
            sound("sounds/lowfire__loop.wav", "renewed by live fire patches", "ambient_loop_request"),
        ],
        "authority": "The authoritative player owns toggle, reserve, trail cadence, and Fire contacts; patches carry owner identity.",
        "cleanup": "Toggle-off stops new patches and removes the reserve; existing patches complete their independently randomized rank-duration fade/contact lifetime.",
        "evidence": ["0x0054CC50", "0x00548B00", "0x005FF050", "0x005FF1D0", "0x00610F90"],
    },
    27: {
        "targeting": "aimed_world_point",
        "trigger": "press_edge",
        "actors": [actor("0x7F0", "StormCloud"), actor("animation", "Anim_Raindrop")],
        "gameplay": "Consume the exact 31-draw cloud presentation prefix, spawn a storm for 1000 active ticks, emit native raindrops before movement/strike work, query hostile targets at radius 500, roll mDamage1..mDamage2 after constructing the three authoritative lightning points, and fade for 101 updates; Magic Tornado adds its 32nd heading draw, fixed movement, frequency, and duration.",
        "timing": {
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
        },
        "art": [
            art("BadGuys", "0,11,78,84", "raindrop ground mark, lightning, moving cloud core and 30 QuickSpline arcs", "mixed_world"),
            art("procedural", "width-2 blue-white gradient", "Anim_Raindrop falling streak", "gradient_world"),
            art("render_target", "three BadGuys-78 passes plus moving and white-mask branches", "StormCloud auxiliary painter 0x00602C30", "screen_and_world_composite"),
        ],
        "audio": [
            sound("sounds/magicstorm.wav", "accepted cast"),
            sound("sounds/lightningstart.wav", "each strike"),
            sound("sounds/thunder__Stream.wav", "strike presentation and one-in-1000 ambient flash", "stream"),
            sound("sounds/rainfall__loop.wav", "renewed while cloud is active", "ambient_loop_request"),
            sound("sounds/steadywind__loop.wav", "renewed while cloud is active", "ambient_loop_request"),
        ],
        "authority": "Caster authority chooses targets, consumes drop/strike/ambient-flash RNG, and applies damage; all strike points and cloud-owned flash state are snapshot-visible.",
        "cleanup": "After 1000 active ticks the cloud fades, ceases target queries, then retires and stops ambient renewal.",
        "evidence": ["0x0054CC50", "0x005E22E0", "0x006021A0", "0x005E8970", "0x00602C30"],
    },
    30: {
        "targeting": "caster_center_radius_350",
        "trigger": "press_edge",
        "actors": [actor("0x1B76", "Mod_Prismatic")],
        "gameplay": "Immediately query the mask-2 hostile radius-350 circle and attach/merge a duration modifier that doubles lightning susceptibility while a separate caster-attached spray owns presentation.",
        "timing": {
            "duration": "mDuration * 100 fixed ticks",
            "spray_emission_ticks": 100,
            "children_per_emission_tick": 3,
            "rng_words_per_emission_tick": 19,
        },
        "art": [
            art("BadGuys", "58", "caster-following prismatic spray core", "additive_world"),
            art("BadGuys", "111", "two independently tinted radial FadeAdditive children per tick", "additive_world"),
            art("BadGuys", "10,11", "one outward FadeMoveAdditive perspective child per tick", "additive_world"),
        ],
        "audio": [
            sound("sounds/prismaticspray__stream.wav", "accepted cast", "stream"),
            sound("sounds/lightningstart.wav", "wave spark at exact pitch 0.8"),
        ],
        "authority": "Caster authority owns radius-350 membership, immediate modifier attachment, and exact 19-word per-tick visual RNG consumption; modifier duration/status is replicated with the target.",
        "cleanup": "World-owned wave children self-expire; the target-owned modifier expires or merges by native modifier rules.",
        "evidence": ["0x0054CC50", "0x00645540", "0x00627230"],
    },
    35: {
        "targeting": "caster_center",
        "trigger": "press_edge",
        "actors": [actor("0x7E8", "FreezeWave"), actor("animation", "Anim_Fade ring layers"), actor("animation", "Anim_WhirlSnow")],
        "gameplay": "Create an expanding list-backed wave which applies ColdSlow or Frozen once per target, optional FrostBurn, and configured freeze payload, while independently registering the exact ring and snow presentation program.",
        "timing": {
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
        },
        "art": [
            art("DeadHawg", "114,121", "three independent additive bursts and one normal ring fade", "mixed_world"),
            art("BadGuys", "72", "100 or 200 independent Anim_WhirlSnow children", "world_depth_sorted"),
        ],
        "audio": [sound("sounds/ringofice.wav", "wave creation")],
        "authority": "Caster authority owns the unique-target list, status selection, contact, and optional item-effect branch.",
        "cleanup": "FreezeWave retires on update 93 and releases target references; independently registered ring/snow children continue through their own fades for up to 175 ticks.",
        "evidence": ["0x0054CC50", "0x00644460", "0x005FFDC0"],
    },
    41: {
        "targeting": "caster_center",
        "trigger": "press_edge",
        "actors": [actor("0x7F1", "Earthquake")],
        "gameplay": "Shake the world for mDuration. On each post-decrement remaining % 30 pulse, query strict center distance <512, full-bound shuffle, and visit floor(N/2) hostiles; each local visit cancels action state, rolls an optional 50..99 tick pause, and perturbs heading. It deals no direct damage.",
        "timing": {
            "duration": "mDuration * 100 fixed ticks",
            "disrupt_period_ticks": 30,
            "disrupt_clock": "post-decrement remaining % 30 == 0",
            "floor_phase_start": -5,
            "floor_phase_per_tick": 0.05,
            "floor_thresholds": [0.6, 3.0],
            "quake_child_lifetime_ticks": 180,
            "enhanced_dust_lifetime_ticks": 360,
        },
        "rng": {
            "cast": "Float(360) floor rotation, then N Integer(N) scenery-shuffle draws",
            "pulse": "N Integer(N) hostile-shuffle draws; per local visit Integer(2), optional Integer(50), Sign(15); optional Anim_Quake Float(360), Integer(4)",
            "per_tick": "one scenery Sign(1), Float(1.5); enhanced Integer(30) dust gate and exact dust children; Integer(15) boulder gate and exact Anim_Bouncer/Anim_BoulderBit constructor sequence",
        },
        "art": [
            art("DeadHawg", "200..202", "one, two, then three floor cracks with fading green redraw", "world_depth_sorted"),
            art("BadGuys", "62", "registered 180-tick Anim_Quake sine/scale child", "world_depth_sorted"),
            art("BadGuys", "10", "enhanced-only 360-tick brown Anim_FadeSin_Move scenery dust", "world_depth_sorted"),
            art("BadGuys", "2008..2010", "ZAnimLitObject-wrapped bouncer debris with enhanced dark underlay", "world_depth_sorted"),
        ],
        "audio": [
            sound("sounds/earthquake__loop.wav", "renewed while intensity is nonzero", "ambient_loop_request"),
            sound("sounds/rockhit.wav", "first live tick, before the large crack"),
            sound("sounds/QuakeCracks__Stream.wav", "first live tick large crack", "stream"),
            sound("sounds/QuakeCrackSmall__Stream.wav", "floor phase 3.0 crossing only", "stream"),
        ],
        "authority": "Caster authority owns the strict-radius target query, fixed-bound shuffle, cancellation/pause/heading mutation, group-4 scenery ledger and cursor, and every child birth/RNG word; clients render replicated wobble and child state.",
        "cleanup": "Counter zero retires the actor, clears world-shake contribution, releases its pointer list, and stops quake-loop renewal.",
        "evidence": ["0x0054CC50", "0x005E8EA0", "0x005F45A0", "0x00523140", "0x005E41F0", "0x00613200", "0x00613E10", "0x00454200", "0x00459350", "0x00457E00", "0x00457E40"],
    },
    45: {
        "targeting": "caster_heading_plus_or_minus_45_at_100_then_collision_adjusted",
        "trigger": "press_edge",
        "actors": [actor("0x7F4", "Golem"), actor("0x7E9", "Knockback")],
        "gameplay": "Enforce one summon or two with Iron Golem; ignore cursor aim, choose caster heading +/-45 at distance 100, collision-adjust against mask 0x205 without actor bodies, commit caster facing, and spawn facing +180. Assemble at ages 0/50/100/200, activate contact at age 400, acquire/chase/attack hostiles, and reflect incoming primary damage when upgraded.",
        "timing": {
            "placement_distance": 100,
            "placement_radius": 25,
            "placement_mask": "0x205 without actor flag 0x400",
            "placement_ring_count": "round-even(pi * (searchRadius + 25) / searchRadius)",
            "placement_ring_geometry": "x radius searchRadius; y radius searchRadius * 0.8",
            "placement_ring_expansion": "searchRadius += multiplier*25; multiplier *= 1+Float(1)",
            "assembly_milestones": [0, 50, 100, 200],
            "contact_enable_age": 400,
            "natural_expiry": False,
        },
        "rng": {
            "cast_prefix": "Sign(45), then blocked placement rings each consume Float(360) and failed rings Float(1)",
            "constructor": "Integer(2) alternating-limb selector after placement",
        },
        "art": [
            art("Golem", "1..208", "articulated body-part compositor", "world_depth_sorted"),
            art("BadGuys", "15,36,62,86,238..245,2008..2010", "assembly, attack, and child effects", "mixed_world"),
            art("DeadHawg", "78..87", "death fragments", "world_depth_sorted"),
            art("UI", "23", "summon status marker", "screen_overlay"),
        ],
        "audio": [
            sound("sounds/QuakeCrackSmall__Stream.wav", "assembly milestones", "stream"),
            sound("sounds/GolemProvoke__Stream.wav", "provoke", "stream"),
            sound("sounds/KnockbackGolem.wav", "attack impact"),
            sound("sounds/stonestep.wav", "movement step"),
            sound("sounds/stonebreak.wav", "death sequence first: fragment release"),
            sound("sounds/flamelashstart.wav", "death sequence second: flame lash"),
            sound("sounds/GolemDie__Stream.wav", "death sequence third", "stream"),
            sound("sounds/rockhit.wav", "death sequence fourth; also assembly impact"),
        ],
        "authority": "Caster authority owns signed heading selection, committed facing, collision-safe placement and its RNG, cap replacement, AI, target identity, contact, reflection, death, and child Knockback creation.",
        "cleanup": "No natural expiry; replacement, death, disconnect, or region teardown retires body/AI and releases child collections while registered fragments finish independently.",
        "evidence": ["0x0054CC50", "0x0054E678", "0x0054E7C0", "0x00645910", "0x005F57E0", "0x005F5B40", "0x00615CD0", "0x00617820", "0x00607F60", "0x00619730"],
    },
    46: {
        "targeting": "self",
        "trigger": "press_edge_refreshable",
        "actors": [actor("0x1B71", "Mod_StoneSkin")],
        "gameplay": "Attach a duration modifier which sets actor flag 0x1 and makes the wizard impervious; reapplication retains the greater remaining duration.",
        "timing": {"duration": "mDuration * 100 fixed ticks"},
        "art": [art("player", "actor flag 0x1 material treatment", "target-owned modifier presentation", "actor_overlay")],
        "audio": [
            sound("sounds/StoneSkin__Stream.wav", "accepted cast", "stream"),
            sound("sounds/stoneskin.wav", "modifier apply, refresh, and removal callbacks"),
        ],
        "authority": "The authoritative player owns modifier duration and rejects physical/magical damage while active.",
        "cleanup": "Expiry or teardown clears invulnerability/tint and emits the removal presentation exactly once.",
        "evidence": ["0x0054CC50", "0x006237A0", "0x00624490", "0x006244C0", "0x00626840"],
    },
    48: {
        "targeting": "arena_shuffled_safety_lattice_or_region_origin",
        "trigger": "press_edge_with_skill_cooldown",
        "actors": [],
        "gameplay": "Arena ignores aim, shuffles every 100-unit lattice cell inset by 100, selects the first maximum capped actor-distance score, and collision-adjusts it with the shared radius-40 dynamic-count elliptical ring resolver; base indoor Regions return (0,0). The world callback always writes a destination.",
        "timing": {
            "cooldown": "mCooldown * 100 fixed ticks",
            "burst_lifetime_ticks": 20,
            "burst_alpha": "2 - 0.1 per fixed tick",
            "source_scale": "1 * 1.1 per fixed tick",
            "destination_scale": "8 * 0.96 per fixed tick",
        },
        "art": [
            art("BadGuys", "90", "source growing Anim_FadeScale", "additive_world"),
            art("BadGuys", "90", "destination shrinking Anim_FadeScale", "additive_world"),
        ],
        "audio": [
            sound("sounds/teleport.wav", "source burst"),
            sound("sounds/teleport.wav", "destination burst"),
        ],
        "authority": "The host consumes the source rotation, Arena selection and collision-adjustment RNG, then destination rotation in native order before atomically committing the returned point.",
        "cleanup": "Both registered FadeScale children retire after their exact 20-tick alpha recurrence.",
        "evidence": [
            "0x0054CC50", "0x0054D625", "0x0054D728", "0x00465440", "0x00508900",
            "0x00645910", "0x00644A00", "0x00452ED0", "0x00455DF0",
        ],
    },
    49: {
        "targeting": "aimed_world_point",
        "trigger": "press_edge",
        "actors": [actor("0x7EA", "MagicCircle"), actor("0x1B70", "Mod_CircleSlow")],
        "gameplay": "Maintain a 1500-tick circle, every 10 ticks slow eligible enemies and restore local MP at twice normal recovery; retain the shipped inert HP branch.",
        "timing": {
            "lifetime_ticks": 1500,
            "effect_period_ticks": 10,
            "first_effect_update": 0,
            "ring_children_even_tick": 1,
            "ring_children_odd_tick": 2,
            "ring_child_loss_per_tick": 0.05,
        },
        "art": [
            art("BadGuys", "48", "one/two centered Anim_SpinAwayAdditive ring particles per global-tick parity", "additive_world"),
            art("BadGuys", "7", "player-attached Anim_FadeScale on successful recovery pulse only", "additive_world"),
        ],
        "audio": [sound("sounds/magiccircle.wav", "actor lifetime reaches 1498")],
        "authority": "Caster authority owns slow attachment, local MP recovery, the flickering shadow-casting radius-2 Region light, and exact ring-emitter RNG consumption; circle/color/lifetime state is replicated.",
        "cleanup": "At zero lifetime the circle unregisters; world-owned spin-away children finish independently.",
        "evidence": ["0x0054CC50", "0x0063FDE0", "0x006006E0", "0x005F3CA0", "0x005FB020"],
    },
    50: {
        "targeting": "aimed_world_point",
        "trigger": "press_edge",
        "actors": [actor("0x7F5", "MagicTrap"), actor("0x1B73", "Mod_Burn"), actor("0x1B6B", "Mod_ElectricBurn"), actor("0x1B69", "Mod_ColdSlow")],
        "gameplay": "Bind the selected primary component into a trap. Welded builds consume Integer(2) before damage lookup. Selector 0/1/2/3/4 resolves effective-rank skill 8/16/24/32/40: Ether then consumes one inclusive FloatRange(mDamage1,mDamage2), while every other component reads its single mDamage without a damage RNG draw. Store f32(baseDamage*trap mDamage), add the float32 charge increment through the update-800 clamp, test the 130-wide arming footprint every 25 ages, then detonate once across the separate 300-wide payload footprint for charge-scaled damage and the element-specific status.",
        "timing": {
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
        },
        "selector_dispatch": {
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
        },
        "art": [
            art("BadGuys", "111,112,15,85", "exact rotating charged body, selector core, normal body, and shadow", "mixed_world"),
            art("BadGuys", "16", "updates 1..32 independently fading selector-tinted perspective shimmer", "normal_world"),
            art("BadGuys", "158..167,15,17,74", "element-colored trigger arrays, center fade, and one hundred two-pass FuzzySpears", "mixed_world"),
            art("BadGuys", "333..342", "fire-selector target-owned Mod_Burn flame cycle", "additive_world"),
        ],
        "audio": [
            sound("sounds/settrap__Stream.wav", "trap initialization", "stream"),
            sound("sounds/magicmissile.wav", "ether-selector initialization"),
            sound("sounds/throwfire.wav", "fire-selector initialization"),
            sound("sounds/lightningstart.wav", "air-selector initialization"),
            sound("sounds/icestart.wav", "water-selector initialization"),
            sound("sounds/startboulder.wav", "earth-selector initialization"),
            sound("sounds/trap__stream.wav", "one-shot trigger", "stream"),
            sound("sounds/electric__loop.wav", "while an air-selector target's ElectricBurn is live", "loop"),
        ],
        "authority": "Caster authority selects a weld component, resolves that selected elemental skill's effective-rank damage, consumes the Ether-only range draw, stores the float32 primary payload, advances charge and shimmer RNG, owns both query footprints, applies contacts/statuses, and removes the trap. Air payloads attach one target-owned ElectricBurn whose 100 authoritative damage/RNG updates follow that target.",
        "cleanup": "Trigger is terminal and removes the trap after emitting world-owned children; already registered shimmer and burst children finish independently. ElectricBurn merges by maximum remaining duration with replacement payload, then its target light and loop cease with modifier retirement; ordinary trap teardown does not replay trigger effects.",
        "evidence": ["0x0054CC50", "0x0054EB5C", "0x0054ED29", "0x0054EE05", "0x00448480", "0x0055012C", "0x005E95D0", "0x00603710", "0x005F5C80", "0x00619CD0", "0x005E9700", "0x006231D0", "0x00628F10", "0x00625A70", "0x00452E20", "0x00454000", "0x00456340", "0x00535A30"],
    },
    51: {
        "targeting": "caster_center_rectangle",
        "trigger": "press_edge",
        "actors": [actor("action:21", "Action_PlayerWizard_CastSpin")],
        "gameplay": "Remove hostile guided/fire/dark missiles in range, disrupt hostile casters, roll RandomInt(100) < 0x33 (51 accepted values despite the authored 50 percent display text) to dispel shields, and queue the 73-tick cast-spin action.",
        "timing": {"cast_spin_ticks": 73, "shield_dispel_numerator": 51, "shield_dispel_denominator": 100, "move_fade_children": 360, "additive_children": 30, "visual_rng_words": 2970},
        "art": [
            art("BadGuys", "10,11", "360 source-over radial Anim_MoveFade children with independent drag and fade", "world_mixed_registration"),
            art("BadGuys", "48", "30 centered Anim_FadeAdditive_Perspective children", "additive_world"),
        ],
        "audio": [
            sound("sounds/flash.wav", "accepted cast"),
            sound("sounds/dampen__stream.wav", "accepted cast", "stream"),
        ],
        "authority": "Caster authority owns projectile removal, action disruption, and shield-dispel RNG; action pose is replicated presentation.",
        "cleanup": "World children self-expire; cast spin is atomic except death and completes after its strict phase boundary.",
        "evidence": ["0x0054CC50", "0x00648DF0", "0x00448860"],
    },
    54: {
        "targeting": "self",
        "trigger": "press_edge_refreshable",
        "actors": [
            actor("animation", "Anim_FadeAdditive break children"),
            actor("animation", "Explosive Shield composite children"),
            actor("0x7E7", "Shockwave"),
        ],
        "gameplay": "Install or refresh mAbsorb on the wizard; incoming damage drains the pool and drives a 40-tick hit pulse. If Explosive Shield is learned, break payload is absorb times mDamage/100, applied once in radius 110 as equal half-payload primary and magic lanes whose target sum is the full payload; the zero-damage Shockwave retains its Dazzle/push lifecycle.",
        "timing": {
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
        },
        "art": [
            art("BadGuys", "49", "player-attached additive shield shell and 40-tick hit pulse", "player_overlay"),
            art("BadGuys", "68", "20 Anim_FadeAdditive particles on shield break", "additive_world"),
            art("BadGuys", "15", "normal scale-12 Explosive Shield core fade", "ordinary_dynamic"),
            art("DeadHawg", "2", "normal scale/fade core at y-35", "ordinary_dynamic"),
            art("BadGuys", "158..167", "two additive ten-frame sprite arrays at rates 0.15 and 0.225", "additive_world"),
            art("BadGuys", "17,74", "100 two-pass additive Anim_FuzzySpear children", "additive_world"),
            art("DeadHawg", "18", "Shockwave Region-light submission; no main-pass sprite", "region_light"),
        ],
        "audio": [
            sound("sounds/magicshieldup.wav", "install or refresh"),
            sound("sounds/hitshield.wav", "absorbed hit"),
            sound("sounds/popshield.wav", "shield break"),
            sound("sounds/magicshieldexplode.wav", "Explosive Shield radial contact"),
        ],
        "authority": "Authoritative damage contact drains absorb, consumes the 60-word break and 502-word explosion construction streams, dispatches the radius-110 contact, and creates the light/push Shockwave; player shell and all children are snapshot-derived presentation.",
        "cleanup": "Break clears absorb and explosive factor after one particle/contact event; death, disconnect, and region teardown clear the residual pulse.",
        "evidence": ["0x0054CC50", "0x00529EE0", "0x00546650", "0x00648790", "0x0054BA80"],
    },
    72: {
        "targeting": "aimed_world_point",
        "trigger": "press_edge",
        "actors": [actor("0x7FE", "AcidRain"), actor("animation", "Anim_AcidRaindrop"), actor("animation", "Acid splash")],
        "gameplay": "Rain for 1500 active ticks, emit two drops per tick or five with Enhanced Effects plus the one-in-four splash branch, and after the 50-tick startup delay shuffle hostile candidates and damage exactly min(n, floor(n/3)+1) every 25 ticks for float32 mDamage/6 per target; damage is direct, not poison.",
        "timing": {
            "active_ticks": 1500,
            "initial_pulse_delay_ticks": 50,
            "damage_period_ticks": 25,
            "contact_damage_formula": "f32(mDamage[effective rank] / 6)",
            "field_pass_one": "additive BadGuys[10] tint (0.41,0.55,0.32), alpha 0.75*g, rotation a*0.03125*p degrees, scale (5*s,4*s)",
            "field_pass_two": "source-over BadGuys[10] tint (0.25,0.45,0.15), alpha g, rotation -0.5*a degrees, y -50*s, scale (7.5*s*p,6*s)",
            "residue_pass": "source-over BadGuys[10] tint (0.05,0.1,0.05), rain alpha, uniform scale 4.5",
            "drops_per_tick": 2,
            "enhanced_drops_per_tick": 5,
            "splash_gate": "Integer(4)==3 after raindrop allocation",
            "maximum_lifetime_ticks": 3600,
            "targets_per_pulse": "min(n, floor(n/3)+1)",
        },
        "art": [
            art("BadGuys", "0,10", "tinted raindrop head/ground mark, splash, two-pass parent field, and residue renderer", "mixed_world"),
            art("procedural", "width-3 green-blue gradient", "Anim_AcidRaindrop falling streak", "gradient_world"),
        ],
        "audio": [
            sound("sounds/magicstorm.wav", "accepted cast"),
            sound("sounds/acidsizzle.wav", "damage/residue pulses with native pitch"),
            sound("sounds/rainfall__loop.wav", "renewed through active rain and residue", "ambient_loop_request"),
        ],
        "authority": "Caster authority stores ranked mDamage, shuffles candidates, and applies float32 mDamage/6 direct periodic damage; drops/residue are presentation state.",
        "cleanup": "The actor retires only after active lifetime and residue fade both end; loop renewal stops with residue ownership.",
        "evidence": ["0x0054CC50", "0x0054F331", "0x005E3540", "0x00604E90", "0x007852E0", "0x005E3600", "0x005EB290", "0x005EB1D0"],
    },
    73: {
        "targeting": "line_perpendicular_to_aim",
        "trigger": "press_edge",
        "actors": [actor("0x7EE", "Fire_Goodguy")],
        "gameplay": "Create eleven Fire_Goodguy patches at 30-unit intervals across the 300-unit line perpendicular to aim and force each patch's +0x160 contact-geometry byte to one; every global third tick each accepted contact sums two half lanes to mDamage*0.03 and applies the shared Burn modifier.",
        "timing": {
            "patch_count": 11,
            "line_length": 300,
            "patch_spacing": 30,
            "patch_lifetime_scalar": 7,
            "patch_lifetime_ticks": 700,
            "contact_period_ticks": 3,
        },
        "art": [
            art("DeadHawg", "46..77", "Fire_Goodguy strip for every wall patch", "additive_world"),
            art("BadGuys", "333..342", "target-owned Mod_Burn flame cycle", "additive_world"),
        ],
        "audio": [
            sound("sounds/ignite.wav", "wall creation"),
            sound("sounds/fireballhit.wav", "wall creation accent"),
            sound("sounds/lowfire__loop.wav", "renewed while patches are live", "ambient_loop_request"),
        ],
        "authority": "Caster authority resolves wall geometry, creates patches, and owns their repeated contacts.",
        "cleanup": "Patches fade and retire independently after the overwritten life scalar 7 reaches zero at 0.01 per tick (700 ticks); teardown stops their low-fire renewal.",
        "evidence": ["0x0054CC50", "0x0054F759", "0x0054F883", "0x005FF050", "0x005FF1D0", "0x00610F90"],
    },
    74: {
        "targeting": "aimed_world_point",
        "trigger": "press_edge",
        "actors": [
            actor("0x807", "EtherDrain"),
            actor("animation", "Anim_SuckCloud"),
            actor("animation", "Anim_SuckDebris"),
            actor("animation", "Anim_Sucked captured-object handoff"),
            actor("animation", "Anim_FadeAdditive capture flare"),
        ],
        "gameplay": "Scale in until the float32 +0.025 recurrence crosses one on update 41, refresh retained hostile identities through the strict 1024-by-819.2 ellipse, pull radius-512 actors and eligible loot inward, apply tiered mDamage/100 contact inside strict radius 20 for ages 41..990, consume eligible loot at center, then scale out for 20 ticks.",
        "timing": {
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
        },
        "art": [
            art("BadGuys", "75", "four-layer parent galaxy", "additive_world"),
            art("BadGuys", "38", "source-over random shimmer and capture pulse", "world_depth_sorted"),
            art("BadGuys", "10..11", "sine-faded Anim_SuckCloud children", "additive_world"),
            art("DeadHawg", "177..179", "free-floating inward Anim_SuckDebris", "world_depth_sorted"),
            art("BadGuys", "36", "direct or captured-object callback flare; not free-debris completion", "additive_world"),
            art("region_light", "radius 2", "random-intensity EtherDrain point light", "region_light"),
        ],
        "audio": [
            sound("sounds/distortreality.wav", "state transition"),
            sound("sounds/lightningstart.wav", "state transition with native pitch"),
            sound("sounds/PlaneCross__Loop.wav", "renewed while field is active", "ambient_loop_request"),
            sound("sounds/steadywind__loop.wav", "renewed while field is active", "ambient_loop_request"),
        ],
        "authority": "Caster authority owns candidate identities, pressure/contact, loot consumption, and both child RNG streams; presentation cadence owns only parent shimmer and light jitter.",
        "cleanup": "Scale-out precedes retirement; destructor releases both PuppetRef arrays and cell lists while registered children self-expire.",
        "evidence": ["0x0054CC50", "0x005F8360", "0x006060C0", "0x0061CF20", "0x00606580", "0x005F8620", "0x005EE120", "0x005EE780", "0x004551D0", "0x00455310", "0x0045A9C0", "0x00455530", "0x004555D0", "0x0045AB60", "0x005EE840"],
    },
    76: {
        "targeting": "aimed_world_point",
        "trigger": "press_edge",
        "actors": [actor("0x80C", "Comet"), actor("0x7E8", "FreezeWave"), actor("animation", "Anim_Bouncer impact debris"), actor("animation", "Comet impact fades")],
        "gameplay": "Count down 400 falling updates while emitting one exact BadGuys-51 trail per tick, impact for +0x140 mDamage, create the shared FreezeWave with +0x13C mFreeze, query radius 400, register the exact world-owned impact/debris actors, install the Region white screen flash, and retire.",
        "timing": {
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
        },
        "art": [
            art("DeadHawg", "5", "falling comet body", "world_depth_sorted"),
            art("BadGuys", "51,15", "fall trails and scale-10 gray additive impact fade", "additive_world"),
            art("DeadHawg", "203..207,6", "independent radial Bouncer debris and scale-2 normal impact fade", "mixed_world"),
            art("region_overlay", "white full-screen rectangle", "Region 0x00448600 / main render 0x0046EC80", "screen_overlay"),
        ],
        "audio": [
            sound("sounds/comet__loop.wav", "renewed while falling", "ambient_loop_request"),
            sound("sounds/cometwhistle.wav", "late fall countdown"),
            sound("sounds/explodesteam.wav", "impact layers"),
            sound("sounds/magicshieldexplode.wav", "impact layer"),
            sound("sounds/bigfire.wav", "impact layer"),
            sound("sounds/ringofice.wav", "FreezeWave creation"),
        ],
        "authority": "Caster authority owns countdown, impact query, damage/freeze contacts, the spawned FreezeWave, initial debris RNG, and every later Bouncer bounce draw.",
        "cleanup": "Impact is terminal, stops loop renewal, lets the Region screen flash decay independently, and leaves registered wave, debris, and fade actors to finish for up to 1000 ticks.",
        "evidence": ["0x0054CC50", "0x0063FD00", "0x005F0C50", "0x006220D0", "0x0061E9C0", "0x005E3CD0", "0x005F0DB0", "0x00448600", "0x0063EFC0", "0x0046EC80"],
    },
    77: {
        "targeting": "aimed_area",
        "trigger": "press_edge",
        "actors": [],
        "gameplay": "Affect only Skeleton, SkeletonArcher, SkeletonMage, and Zombie: turn them away, stamp flee timing, and scale attack strength by mWeaken once.",
        "timing": {"flee_duration": "mFlee * 100 fixed ticks"},
        "art": [art("BadGuys", "48", "turn-undead additive burst", "additive_world")],
        "audio": [
            sound("sounds/levelup.wav", "accepted cast at pitch 2.0"),
            sound("sounds/levelup.wav", "accepted cast at pitch 3.0"),
        ],
        "authority": "Caster authority owns area membership, eligible-type filtering, one-time weaken stamp, heading, and flee deadline.",
        "cleanup": "The cast burst self-expires; each target returns to its ordinary behavior when its flee deadline elapses or it dies.",
        "evidence": ["0x0054CC50", "0x00647EF0"],
    },
    78: {
        "targeting": "self",
        "trigger": "toggle",
        "actors": [],
        "gameplay": "Toggle progression +0x8DD, temporarily add one effective rank to every learned skill ID 8..77 except Mindstar itself, clamp to each compiled maximum, and reserve the configured percentage of MP.",
        "timing": {"refresh": "immediate on toggle and every normal progression refresh"},
        "art": [art("Region", "cyan point-gain feedback", "dispatcher screen-feedback lane; no actor allocation", "screen_feedback")],
        "audio": [sound("sounds/mindstar__stream.wav", "toggle on or off", "stream")],
        "authority": "The authoritative progression component owns the toggle, temporary ranks, mana reserve, and overload shutdown.",
        "cleanup": "Toggle-off, mana overload, death/session reset, or actor teardown removes temporary ranks and reserve in one progression refresh.",
        "evidence": ["0x0054CC50", "0x00661E40", "0x006639D0", "0x006623F0"],
    },
    79: {
        "targeting": "self",
        "trigger": "toggle",
        "actors": [],
        "gameplay": "Toggle progression +0x8DE, reserve the configured percentage of MP, and while active add 1.5/tickRate HP per fixed update in addition to ordinary regeneration, capped at max HP.",
        "timing": {"healing_per_update": "1.5 / tickRate", "refresh": "fixed update while active"},
        "art": [art("Region", "orange point-gain feedback", "dispatcher screen-feedback lane; no actor allocation", "screen_feedback")],
        "audio": [sound("sounds/mindstar__stream.wav", "toggle on or off", "stream")],
        "authority": "The authoritative progression component owns toggle, reserve, healing, cap, and overload shutdown.",
        "cleanup": "Toggle-off, mana overload, death/session reset, or actor teardown stops healing and removes reserve immediately.",
        "evidence": ["0x0054CC50", "0x006614D0", "0x006639D0", "0x006623F0"],
    },
}


def main() -> int:
    skills_document = json.loads(SKILLS.read_text(encoding="utf-8"))
    skills = {row["id"]: row for row in skills_document["skills"]}
    audio_document = json.loads(AUDIO.read_text(encoding="utf-8"))
    audio = {
        row["file"]["path"].replace("\\", "/"): {
            "registry_index": row["registry_index"],
            "registry_member_offset": row["registry_member_offset"],
            "native_class": row["native_class"],
            "sha256": row["file"]["sha256"],
        }
        for row in audio_document["compiled_registry"]
        if row.get("file")
    }

    if (
        tuple(CONTRACTS) != SECONDARY_IDS
        or tuple(REGION_SCREEN_FEEDBACK) != SECONDARY_IDS
        or tuple(COOLDOWN_ROWS) != SECONDARY_IDS
    ):
        raise SystemExit("secondary contract membership/order drifted")

    abilities = []
    for skill_id in SECONDARY_IDS:
        skill = skills[skill_id]
        contract = CONTRACTS[skill_id]
        audio_rows = []
        for event in contract["audio"]:
            resolved = audio.get(event["path"])
            if resolved is None:
                raise SystemExit(f"unresolved audio path for skill {skill_id}: {event['path']}")
            audio_rows.append({**event, **resolved})
        abilities.append(
            {
                "skill_id": skill_id,
                "name": skill["name"],
                "family": skill["family"],
                "category": 2,
                "skills_atlas_icon_record": skill["skills_atlas_icon_record"],
                "config_path": skill["config_path"],
                "config_sha256": skill["config_sha256"],
                "rank_config": skill["config"],
                "dispatcher": "0x0054CC50",
                "action": (
                    {"mode": 21, "name": "Action_PlayerWizard_CastSpin", "ticks": 73}
                    if skill_id == 51
                    else {"mode": None, "name": "immediate_secondary_dispatch"}
                ),
                "region_screen_feedback": REGION_SCREEN_FEEDBACK[skill_id],
                **{key: value for key, value in contract.items() if key != "audio"},
                "audio": audio_rows,
                "disposition": "closed_native_contract",
            }
        )

    document = {
        "schema": "solomon-dark-native-secondary-ability-catalog-v3",
        "source": {
            "executable": "SolomonDarkAbandonware/SolomonDark.exe",
            "size": 4723200,
            "sha256": "03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3",
            "image_base": "0x00400000",
            "dispatcher": "0x0054CC50",
            "skill_catalog": SKILLS.relative_to(ROOT).as_posix(),
            "audio_catalog": AUDIO.relative_to(ROOT).as_posix(),
        },
        "summary": {
            "ability_count": len(abilities),
            "skill_ids": list(SECONDARY_IDS),
            "fixed_tick_hz": 100,
            "input_slots": 8,
            "default_right_click_slot": 0,
            "default_secondary_binding": "0x201",
            "keyboard_slot_bindings": ["0x02", "0x03", "0x04", "0x05", "0x06", "0x07", "0x08"],
            "region_screen_feedback_ability_count": sum(bool(rows) for rows in REGION_SCREEN_FEEDBACK.values()),
            "region_screen_feedback_write_count": sum(len(rows) for rows in REGION_SCREEN_FEEDBACK.values()),
        },
        "belt_presentation": BELT_PRESENTATION,
        "cooldown_system": COOLDOWN_SYSTEM,
        "composite_mana_costs": COMPOSITE_MANA_COSTS,
        "abilities": abilities,
    }
    OUTPUT.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
