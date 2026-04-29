#!/usr/bin/env python3
"""Validate bot primary-cast damage one element at a time."""

from __future__ import annotations

import argparse
import json
import math
import re
import time
from pathlib import Path

import cast_state_probe as csp
from cast_trace_profiles import build_trace_specs, trace_profile_is_stable, trace_profile_names
import probe_bot_close_range_combat as crc
import probe_bot_primary_wave_cast as wave


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = ROOT / "runtime" / "probe_bot_element_damage.json"
RUNTIME_BINARY_LAYOUT_PATH = ROOT / "runtime" / "stage" / ".sdmod" / "config" / "binary-layout.ini"

ELEMENTS = {
    "fire": {"element_id": 0, "primary_entry_index": 0x10},
    "water": {"element_id": 1, "primary_entry_index": 0x20},
    "earth": {"element_id": 2, "primary_entry_index": 0x28},
    "air": {"element_id": 3, "primary_entry_index": 0x18},
    "ether": {"element_id": 4, "primary_entry_index": 0x08},
}
PRIMARY_STATBOOKS = {
    "fire": {
        "file": "fireball.cfg",
        "build_skill_id": 0x3F3,
        "dispatcher_skill_id": 0,
        "selection_state": 0x10,
        "lane": "pure_primary",
        "damage_keys": ("mDamage",),
        "mana_key": "mManaCost",
        "unit": "per_cast",
    },
    "water": {
        "file": "frost_jet.cfg",
        "build_skill_id": 0x3F4,
        "dispatcher_skill_id": 0x20,
        "selection_state": 0x20,
        "lane": "dispatcher",
        "damage_keys": ("mDamage",),
        "mana_key": "mManaCost",
        "unit": "per_second",
    },
    "earth": {
        "file": "boulder.cfg",
        "build_skill_id": 0x3F6,
        "dispatcher_skill_id": 0x28,
        "selection_state": 0x28,
        "lane": "dispatcher",
        "damage_keys": ("mDamage",),
        "mana_key": "mManaCost",
        "unit": "damage_x_boulder_size_and_mana_per_second",
        "requires_max_size_release": True,
    },
    "air": {
        "file": "lightning.cfg",
        "build_skill_id": 0x3F5,
        "dispatcher_skill_id": 0x18,
        "selection_state": 0x18,
        "lane": "dispatcher",
        "damage_keys": ("mDamage",),
        "mana_key": "mManaCost",
        "unit": "per_second",
    },
    "ether": {
        "file": "magic_missile.cfg",
        "build_skill_id": 0x3F2,
        "dispatcher_skill_id": 0,
        "selection_state": 0x08,
        "lane": "pure_primary",
        "damage_keys": ("mDamage1", "mDamage2"),
        "mana_key": "mManaCost",
        "unit": "per_cast",
    },
}

DEFAULT_PLAYER_ELEMENT = "ether"
DEFAULT_DISCIPLINE = "mind"
DEFAULT_BOT_DISCIPLINE_ID = 1
DEFAULT_STANDOFF = 96.0
ELEMENT_STANDOFFS = {
    "fire": 160.0,
    "water": 160.0,
    "earth": 46.0,
    "air": 360.0,
    "ether": 160.0,
}
ELEMENT_FORCE_TARGET_OFFSETS = {
    # Native Boulder grows at a fixed contact point in front of the caster
    # before cleanup applies its collision side effects.
    "earth": (45.5, 5.0),
}
DEFAULT_HP = 160.0
DEFAULT_CASTS = 1
DEFAULT_CAST_INTERVAL_SECONDS = 0.85
ELEMENT_CAST_INTERVAL_SECONDS = {
    "fire": 1.25,
    "water": 1.25,
    "earth": 22.0,
    "air": 2.0,
    "ether": 0.85,
}
DEFAULT_SETTLE_SECONDS = 1.25
DEFAULT_MAX_HOSTILE_GAP = 420.0
DEFAULT_ENEMY_WATCH_COUNT = 24
SETUP_MODES = ("waves", "manual_prelude")
POSITIONING_MODES = ("auto", "bot_only", "force_both")
ELEMENT_POSITIONING = {
    "fire": "bot_only",
    "water": "bot_only",
    "earth": "force_both",
    "air": "bot_only",
    "ether": "bot_only",
}
ELEMENT_SKIP_HOSTILE_HP_WATCHES = {
    "earth": True,
    "air": True,
    "ether": True,
}
POST_COMBAT_PRELUDE_SETTLE_SECONDS = 1.0
MANUAL_SPAWN_ENEMY_TYPE_ID = 5010
ARENA_ENEMY_OBJECT_TYPE_ID = 1001
ARENA_ENEMY_MAX_HP_OFFSET = 0x170
ARENA_ENEMY_CURRENT_HP_OFFSET = 0x174
AIR_LIGHTNING_HANDLER_ADDRESS = 0x00451DC0
COMMON_NATIVE_HIT_PATH_TRACES = {
    "native_apply_damage": 0x0063E7D0,
}
ELEMENT_NATIVE_HIT_PATH_TRACES = {
    "fire": {
        "spell_cast_pure_primary": 0x0052DA80,
        "fire_query_cone": 0x00641B10,
        "fire_query_radius": 0x00642090,
    },
    "ether": {
        "spell_cast_pure_primary": 0x0052DA80,
        "ether_query_cone": 0x00641B10,
        "ether_query_radius": 0x00642090,
    },
    "air": {
        "air_primary_handler": 0x0053F9C0,
        "air_query_cone": 0x00641B10,
        "air_query_radius": 0x00642090,
    },
    "water": {
        "water_handler": 0x00543860,
        "water_query_cone": 0x00641B10,
        "water_query_radius": 0x00642090,
        "water_line_check": 0x00524D70,
    },
    "earth": {
        "earth_cast_cleanup": 0x0052F3B0,
        "earth_active_handle_resolve": 0x0045ADE0,
        "earth_primary_handler": 0x00544C60,
        "earth_boulder_ctor": 0x005FA270,
        "earth_release_finalize": 0x005E5450,
        "earth_release_line_check": 0x00524D70,
        "earth_release_secondary": 0x0060B700,
        "earth_update": 0x0060AC40,
        "earth_child_spawn": 0x005FA6D0,
        "earth_collision_damage": 0x005F1F00,
        "earth_direct_damage": 0x005F2360,
        "earth_splash_damage": 0x005F25B0,
        "earth_radius_scan": 0x005F2980,
        "earth_child_radius_damage": 0x005F3830,
    },
}
NATIVE_DAMAGE_CONTEXT_WATCHES = {
    "source": (0x0081C6E0, 4),
    "flags": (0x0081C6E4, 4),
    "primary": (0x0081C6E8, 4),
    "secondary": (0x0081C6EC, 4),
}
PROJECTILE_SPAWN_SPECS = {
    # Earth's stock primary publishes a live world spell object.
    "earth": {"kind": "active_world_spell_object", "object_type": 0x7D5},
    # Fire and Ether are pure-primary projectile/action effects. They do not
    # publish actor+0x27C/+0x27E active handles, so their native evidence is the
    # pure-primary start plus the post-builder action object.
    "fire": {"kind": "pure_primary_action_effect"},
    "ether": {"kind": "pure_primary_action_effect"},
}
DEFAULT_TRACE_PROFILE = "safe_entry"
CONTROLLED_BOT_X = 914.0
CONTROLLED_BOT_Y = 150.0


class ElementDamageProbeFailure(RuntimeError):
    pass


def parse_number_expression(expression: str) -> float:
    cleaned = expression.strip()
    if not re.fullmatch(r"[0-9.+\-*/() \t]+", cleaned):
        raise ElementDamageProbeFailure(f"Unsupported stat-book expression: {expression!r}")
    return float(eval(cleaned, {"__builtins__": {}}, {}))


def parse_statbook_array(text: str, key: str) -> list[float]:
    match = re.search(rf"\b{re.escape(key)}\s*=\s*\{{([^}}]+)\}}\s*;", text, re.MULTILINE)
    if not match:
        raise ElementDamageProbeFailure(f"Missing stat-book array {key}")
    values: list[float] = []
    for part in match.group(1).split(","):
        part = part.strip()
        if not part:
            continue
        values.append(parse_number_expression(part))
    return values


def format_stat_value(value: float) -> int | float:
    if math.isfinite(value) and abs(value - round(value)) < 0.000001:
        return int(round(value))
    return value


def load_primary_statbook(element: str, level: int = 1) -> dict[str, object]:
    spec = PRIMARY_STATBOOKS[element]
    path = ROOT / "runtime" / "stage" / "data" / "wizardskills" / str(spec["file"])
    if not path.exists():
        raise ElementDamageProbeFailure(f"Missing staged stat-book file for {element}: {path}")
    text = path.read_text(encoding="utf-8", errors="replace")
    damage_arrays = {
        key: parse_statbook_array(text, key)
        for key in spec["damage_keys"]
    }
    mana_values = parse_statbook_array(text, str(spec["mana_key"]))
    max_index = min([len(values) for values in damage_arrays.values()] + [len(mana_values)]) - 1
    if level < 0 or level > max_index:
        raise ElementDamageProbeFailure(
            f"Stat-book level {level} out of range for {element}; max_index={max_index}"
        )
    if len(damage_arrays) == 2:
        damage_keys = list(spec["damage_keys"])
        level_damage: object = {
            damage_keys[0]: format_stat_value(damage_arrays[damage_keys[0]][level]),
            damage_keys[1]: format_stat_value(damage_arrays[damage_keys[1]][level]),
            "range": (
                f"{format_stat_value(damage_arrays[damage_keys[0]][level])}-"
                f"{format_stat_value(damage_arrays[damage_keys[1]][level])}"
            ),
        }
    else:
        key = next(iter(damage_arrays))
        level_damage = format_stat_value(damage_arrays[key][level])
    return {
        "path": str(path.relative_to(ROOT)),
        "file": spec["file"],
        "level": level,
        "level_damage": level_damage,
        "level_mana": format_stat_value(mana_values[level]),
        "unit": spec["unit"],
        "max_index": max_index,
    }


def parse_int_text(value: object, default: int = 0) -> int:
    try:
        text = str(value).strip()
        if text.lower().startswith("0x"):
            return int(text, 16)
        if re.fullmatch(r"[+-]?\d+", text):
            return int(text, 10)
        return int(float(text))
    except (TypeError, ValueError):
        return default


def parse_cast_startup_value(line: str, field: str) -> int:
    match = re.search(rf"\b{re.escape(field)}=(0x[0-9A-Fa-f]+|-?\d+)", line)
    if not match:
        return 0
    return parse_int_text(match.group(1))


def parse_log_float(line: str, field: str, default: float = 0.0) -> float:
    match = re.search(rf"\b{re.escape(field)}=([0-9.+\-eE]+)", line)
    if not match:
        return default
    try:
        return float(match.group(1))
    except ValueError:
        return default


def parse_log_word(line: str, field: str, default: str = "") -> str:
    match = re.search(rf"\b{re.escape(field)}=([^\s]+)", line)
    if not match:
        return default
    return match.group(1)


def read_loader_log_lines() -> list[str]:
    if not csp.LOADER_LOG.exists():
        return []
    with csp.LOADER_LOG.open("r", encoding="utf-8", errors="replace") as handle:
        return [line.rstrip("\n") for line in handle]


LOADOUT_RE = re.compile(
    r"skills_wizard_loadout begin progression=(0x[0-9A-Fa-f]+) "
    r"primary_entry=(\d+) combo_entry=(\d+) spell_id=(\d+)"
)
CAST_PREPPED_RE = re.compile(
    r"(?:gameplay-slot|wizard) cast prepped\. bot_id=(\d+) "
    r"(?:(?:kind=([a-z_]+) gameplay_slot=(-?\d+) ))?"
    r"skill_id=(-?\d+) "
    r"dispatcher_skill_id=(-?\d+) lane=([a-z_]+) selection_state=(-?\d+) "
    r"progression_runtime=(0x[0-9A-Fa-f]+) progression_spell_id=(-?\d+)"
)
CAST_COMPLETE_RE = re.compile(
    r"cast complete \(([^)]+)\)\. bot_id=(\d+) skill_id=(-?\d+) ticks=(\d+).*"
)
MANA_SPENT_RE = re.compile(
    r"mana spent\. bot_id=(\d+) skill_id=(-?\d+) mode=([a-z_]+) "
    r"statbook_level=(\d+) .*?(?:rate=([0-9.+\\-eE]+) )?cost=([0-9.+\\-eE]+) "
    r"before=([0-9.+\\-eE]+) after=([0-9.+\\-eE]+) total=([0-9.+\\-eE]+)"
)
MANA_REJECTED_RE = re.compile(
    r"(?:cast rejected for mana|mana rejected)\. bot_id=(\d+) skill_id=(-?\d+) .*?mode=([a-z_]+) .*"
)
SPELL_DISPATCH_ENTER_RE = re.compile(
    r"spell_dispatch enter actor=(0x[0-9A-Fa-f]+) bot_id=(\d+).*"
)
PURE_PRIMARY_START_RE = re.compile(
    r"pure_primary_start enter actor=(0x[0-9A-Fa-f]+) bot_id=(\d+).*"
)
PURE_PRIMARY_POST_BUILDER_RE = re.compile(
    r"pure_primary_post_builder actor=(0x[0-9A-Fa-f]+) bot_id=(\d+) "
    r"builder_result=(0x[0-9A-Fa-f]+).*"
)
EARTH_RELEASE_RE = re.compile(
    r"native (max-size|damage-threshold) reached; releasing held cast input for native launch\. "
    r"bot_id=(\d+) skill_id=(-?\d+).*"
)


def build_native_projectile_spawn_validation(
    element: str,
    spec: dict[str, object],
    *,
    matching_complete: dict[str, object] | None,
    pure_primary_start_matches: list[dict[str, object]],
    pure_primary_builder_matches: list[dict[str, object]],
    earth_spawn_matches: list[dict[str, object]],
) -> dict[str, object]:
    spawn_spec = PROJECTILE_SPAWN_SPECS.get(element)
    if spawn_spec is None:
        return {
            "ok": True,
            "kind": "not_required_for_this_element",
            "checks": {"spawn_evidence_not_required": True},
        }

    if spawn_spec["kind"] == "pure_primary_action_effect":
        expected_build_skill_id = int(spec["build_skill_id"])
        expected_selection_state = int(spec["selection_state"])
        matching_start = next(
            (
                item
                for item in reversed(pure_primary_start_matches)
                if int(item["startup_p750"]) == expected_build_skill_id
                and int(item["startup_sel_id"]) == expected_selection_state
                and int(item["local_sel_shim"]) == 1
            ),
            None,
        )
        matching_builder = next(
            (
                item
                for item in reversed(pure_primary_builder_matches)
                if int(item["startup_p750"]) == expected_build_skill_id
                and int(item["startup_sel_id"]) == expected_selection_state
                and int(item["builder_result"]) != 0
            ),
            None,
        )
        checks = {
            "pure_primary_start_logged": matching_start is not None,
            "pure_primary_selection_state_matches": matching_start is not None
            and int(matching_start["startup_sel_id"]) == expected_selection_state,
            "pure_primary_build_skill_matches": matching_start is not None
            and int(matching_start["startup_p750"]) == expected_build_skill_id,
            "pure_primary_local_selection_shim_active": matching_start is not None
            and int(matching_start["local_sel_shim"]) == 1,
            "pure_primary_slot_item_shim_active": matching_start is not None
            and int(matching_start["slot_item_shim"]) == 1,
            "pure_primary_attachment_item_present": matching_start is not None
            and int(matching_start["attachment_item"]) != 0,
            "pure_primary_builder_logged": matching_builder is not None,
            "pure_primary_builder_result_nonzero": matching_builder is not None
            and int(matching_builder["builder_result"]) != 0,
            "pure_primary_native_action_latch_set": matching_builder is not None
            and (int(matching_builder["startup_e4"]) != 0 or int(matching_builder["startup_e8"]) != 0),
            "pure_primary_no_active_handle_expected": matching_builder is not None
            and int(matching_builder["active_cast_group"]) == 0xFF
            and int(matching_builder["active_cast_slot"]) == 0xFFFF,
            "pure_primary_builder_scale_present": matching_builder is not None
            and finite_float(float(matching_builder["result_f34"])),
        }
        return {
            "ok": all(checks.values()),
            "kind": str(spawn_spec["kind"]),
            "checks": checks,
            "matching_start": matching_start,
            "matching_builder": matching_builder,
            "start_log_count": len(pure_primary_start_matches),
            "builder_log_count": len(pure_primary_builder_matches),
        }

    expected_object_type = int(spawn_spec["object_type"])
    matching_release = next(
        (
            item
            for item in reversed(earth_spawn_matches)
            if int(item["skill_id"]) == int(spec["build_skill_id"])
            and int(item["obj_ptr"]) != 0
        ),
        None,
    )
    object_source = matching_release or matching_complete
    release_reason = str(matching_release.get("release_reason", "")) if matching_release else ""
    max_size_fields_ok = (
        matching_release is not None
        and finite_float(float(matching_release.get("obj_74", 0.0)))
        and finite_float(float(matching_release.get("obj_1fc", 0.0)))
        and finite_float(float(matching_release.get("max_charge", 0.0)))
        and float(matching_release.get("obj_1fc", 0.0)) > 0.0
        and float(matching_release.get("max_charge", 0.0)) > 0.0
        and float(matching_release.get("obj_74", 0.0)) >= float(matching_release.get("obj_1fc", 0.0)) - 0.001
        and float(matching_release.get("obj_74", 0.0)) >= float(matching_release.get("max_charge", 0.0)) - 0.001
    )
    threshold_fields_ok = (
        matching_release is not None
        and int(matching_release.get("target_actor", 0)) != 0
        and int(matching_release.get("target_health", 0)) != 0
        and finite_float(float(matching_release.get("projected_damage", 0.0)))
        and finite_float(float(matching_release.get("target_hp", 0.0)))
        and finite_float(float(matching_release.get("base_damage", 0.0)))
        and finite_float(float(matching_release.get("obj_74", 0.0)))
        and float(matching_release.get("base_damage", 0.0)) > 0.0
        and float(matching_release.get("target_hp", 0.0)) > 0.0
        and abs(
            float(matching_release.get("projected_damage", 0.0)) -
            (
                float(matching_release.get("base_damage", 0.0)) *
                float(matching_release.get("obj_74", 0.0)) *
                float(matching_release.get("obj_74", 0.0))
            )
        ) <= 0.002
        and float(matching_release.get("projected_damage", 0.0)) >=
            float(matching_release.get("target_hp", 0.0))
        and int(matching_release.get("threshold_charge_write", 0)) == 1
        and int(matching_release.get("threshold_max_write", 0)) == 1
        and int(matching_release.get("release_charge_write", 0)) == 1
    )
    stock_cleanup_window_ok = (
        matching_complete is not None
        and int(matching_complete.get("cleanup_requested", 0)) == 1
        and int(matching_complete.get("post_release_ticks", 0)) >= 60
    )
    checks = {
        "native_spell_object_spawn_logged": object_source is not None
        and int(object_source.get("obj_ptr", 0)) != 0,
        "native_spell_object_type_matches": object_source is not None
        and int(object_source.get("obj_type", 0)) == expected_object_type,
        "native_spell_object_handle_present": object_source is not None
        and int(object_source.get("group", object_source.get("group_before", 0xFF))) != 0xFF
        and int(object_source.get("slot", object_source.get("slot_before", 0xFFFF))) != 0xFFFF,
        "native_release_requested_before_cleanup": matching_release is not None,
        "native_release_uses_stock_cleanup_window": stock_cleanup_window_ok,
        "native_max_size_fields_match_when_used": release_reason != "max_size" or max_size_fields_ok,
        "native_damage_threshold_fields_match_when_used": (
            release_reason != "damage_threshold" or threshold_fields_ok
        ),
        "native_cast_completed_after_release": matching_complete is not None
        and matching_complete.get("exit_label") in {
            "max_size_reached",
            "max_size_released",
            "damage_threshold_released",
        },
    }
    return {
        "ok": all(checks.values()),
        "kind": str(spawn_spec["kind"]),
        "expected_object_type": expected_object_type,
        "checks": checks,
        "matching_spawn": matching_release,
        "matching_release": matching_release,
        "release_reason": release_reason,
        "max_size_fields_ok": max_size_fields_ok,
        "threshold_fields_ok": threshold_fields_ok,
        "stock_cleanup_window_ok": stock_cleanup_window_ok,
        "matching_complete": matching_complete,
        "spawn_log_count": len(earth_spawn_matches),
    }


def build_statbook_validation(
    element: str,
    bot: dict[str, str],
    bot_id: int,
    log_lines: list[str],
) -> dict[str, object]:
    config = ELEMENTS[element]
    spec = PRIMARY_STATBOOKS[element]
    profile = {
        "element_id": csp.int_value(bot, "profile.element_id"),
        "discipline_id": csp.int_value(bot, "profile.discipline_id"),
        "level": csp.int_value(bot, "profile.level"),
        "experience": csp.int_value(bot, "profile.experience"),
        "primary_entry_index": csp.int_value(bot, "profile.loadout.primary_entry_index"),
        "primary_combo_entry_index": csp.int_value(bot, "profile.loadout.primary_combo_entry_index"),
    }
    statbook = load_primary_statbook(element, max(profile["level"], 1))
    progression_runtime = csp.int_value(bot, "progression_runtime_state_address")

    loadout_matches: list[dict[str, object]] = []
    prepped_matches: list[dict[str, object]] = []
    complete_matches: list[dict[str, object]] = []
    dispatch_matches: list[dict[str, object]] = []
    pure_primary_start_matches: list[dict[str, object]] = []
    pure_primary_builder_matches: list[dict[str, object]] = []
    earth_spawn_matches: list[dict[str, object]] = []
    mana_spent_matches: list[dict[str, object]] = []
    mana_rejected_matches: list[dict[str, object]] = []
    for line in log_lines:
        loadout_match = LOADOUT_RE.search(line)
        if loadout_match:
            loadout_matches.append(
                {
                    "line": line,
                    "progression": parse_int_text(loadout_match.group(1)),
                    "primary_entry": parse_int_text(loadout_match.group(2)),
                    "combo_entry": parse_int_text(loadout_match.group(3)),
                    "spell_id": parse_int_text(loadout_match.group(4)),
                }
            )
        prepped_match = CAST_PREPPED_RE.search(line)
        if prepped_match and parse_int_text(prepped_match.group(1)) == bot_id:
            prepped_matches.append(
                {
                    "line": line,
                    "bot_id": parse_int_text(prepped_match.group(1)),
                    "kind": prepped_match.group(2) or "legacy_gameplay_slot",
                    "gameplay_slot": parse_int_text(prepped_match.group(3) or "-999"),
                    "skill_id": parse_int_text(prepped_match.group(4)),
                    "dispatcher_skill_id": parse_int_text(prepped_match.group(5)),
                    "lane": prepped_match.group(6),
                    "selection_state": parse_int_text(prepped_match.group(7)),
                    "progression_runtime": parse_int_text(prepped_match.group(8)),
                    "progression_spell_id": parse_int_text(prepped_match.group(9)),
                    "startup_p750": parse_cast_startup_value(line, "p750"),
                }
            )
        dispatch_match = SPELL_DISPATCH_ENTER_RE.search(line)
        if dispatch_match and parse_int_text(dispatch_match.group(2)) == bot_id:
            dispatch_matches.append(
                {
                    "line": line,
                    "actor": parse_int_text(dispatch_match.group(1)),
                    "bot_id": parse_int_text(dispatch_match.group(2)),
                    "chosen_runtime": parse_cast_startup_value(line, "chosen_runtime"),
                    "skill": parse_cast_startup_value(line, "skill"),
                    "previous_skill": parse_cast_startup_value(line, "prev"),
                    "progression_runtime": parse_cast_startup_value(line, "prog"),
                    "selection_state": parse_cast_startup_value(line, "sel_id"),
                    "native_range": parse_cast_startup_value(line, "f278"),
                }
            )
        pure_primary_start_match = PURE_PRIMARY_START_RE.search(line)
        if pure_primary_start_match and parse_int_text(pure_primary_start_match.group(2)) == bot_id:
            pure_primary_start_matches.append(
                {
                    "line": line,
                    "actor": parse_int_text(pure_primary_start_match.group(1)),
                    "bot_id": parse_int_text(pure_primary_start_match.group(2)),
                    "startup": parse_cast_startup_value(line, "startup"),
                    "local_sel_shim": parse_cast_startup_value(line, "local_sel_shim"),
                    "local_window_shim": parse_cast_startup_value(line, "local_window_shim"),
                    "slot_item_shim": parse_cast_startup_value(line, "slot_item_shim"),
                    "attachment_item": parse_cast_startup_value(line, "attachment_item"),
                    "fallback_slot_plus4": parse_cast_startup_value(line, "fallback_slot_plus4"),
                    "fallback_slot_plus4_type": parse_cast_startup_value(line, "fallback_slot_plus4_type"),
                    "startup_p750": parse_cast_startup_value(line, "p750"),
                    "startup_sel_id": parse_cast_startup_value(line, "sel_id"),
                    "startup_e4": parse_cast_startup_value(line, "e4"),
                    "startup_e8": parse_cast_startup_value(line, "e8"),
                }
            )
        pure_primary_builder_match = PURE_PRIMARY_POST_BUILDER_RE.search(line)
        if pure_primary_builder_match and parse_int_text(pure_primary_builder_match.group(2)) == bot_id:
            pure_primary_builder_matches.append(
                {
                    "line": line,
                    "actor": parse_int_text(pure_primary_builder_match.group(1)),
                    "bot_id": parse_int_text(pure_primary_builder_match.group(2)),
                    "builder_result": parse_int_text(pure_primary_builder_match.group(3)),
                    "result_type": parse_cast_startup_value(line, "result_type"),
                    "result_f34": parse_log_float(line, "result_f34"),
                    "result_f38": parse_log_float(line, "result_f38"),
                    "active_cast_group": parse_cast_startup_value(line, "active_cast_group"),
                    "active_cast_slot": parse_cast_startup_value(line, "active_cast_slot"),
                    "startup_p750": parse_cast_startup_value(line, "p750"),
                    "startup_sel_id": parse_cast_startup_value(line, "sel_id"),
                    "startup_e4": parse_cast_startup_value(line, "e4"),
                    "startup_e8": parse_cast_startup_value(line, "e8"),
                }
            )
        earth_spawn_match = EARTH_RELEASE_RE.search(line)
        if earth_spawn_match and parse_int_text(earth_spawn_match.group(2)) == bot_id:
            earth_spawn_matches.append(
                {
                    "line": line,
                    "release_reason": (
                        "damage_threshold"
                        if earth_spawn_match.group(1) == "damage-threshold"
                        else "max_size"
                    ),
                    "bot_id": parse_int_text(earth_spawn_match.group(2)),
                    "skill_id": parse_int_text(earth_spawn_match.group(3)),
                    "group": parse_cast_startup_value(line, "group"),
                    "slot": parse_cast_startup_value(line, "slot"),
                    "handle_source": parse_log_word(line, "handle_source"),
                    "selection_state": parse_cast_startup_value(line, "selection_state"),
                    "obj_ptr": parse_cast_startup_value(line, "obj_ptr"),
                    "obj_type": parse_cast_startup_value(line, "obj_type"),
                    "obj_74": parse_log_float(line, "obj_74"),
                    "obj_1f0": parse_log_float(line, "obj_1f0"),
                    "obj_1fc": parse_log_float(line, "obj_1fc"),
                    "obj_22c": parse_cast_startup_value(line, "obj_22c"),
                    "obj_230": parse_cast_startup_value(line, "obj_230"),
                    "max_charge": parse_log_float(line, "max_charge"),
                    "statbook_level": parse_cast_startup_value(line, "statbook_level"),
                    "stat_source": parse_cast_startup_value(line, "stat_source"),
                    "stat_vt": parse_cast_startup_value(line, "stat_vt"),
                    "damage_getter": parse_cast_startup_value(line, "damage_getter"),
                    "damage_getter_attempt": parse_cast_startup_value(line, "damage_getter_attempt"),
                    "damage_getter_seh": parse_cast_startup_value(line, "damage_getter_seh"),
                    "damage_native": parse_cast_startup_value(line, "damage_native"),
                    "base_damage": parse_log_float(line, "base_damage"),
                    "statbook_damage": parse_log_float(line, "statbook_damage"),
                    "projected_damage": parse_log_float(line, "projected_damage"),
                    "target_actor": parse_cast_startup_value(line, "target_actor"),
                    "target_health": parse_cast_startup_value(line, "target_health"),
                    "target_health_kind": parse_log_word(line, "target_health_kind"),
                    "target_hp": parse_log_float(line, "target_hp"),
                    "target_max_hp": parse_log_float(line, "target_max_hp"),
                    "target_x": parse_log_float(line, "target_x"),
                    "target_y": parse_log_float(line, "target_y"),
                    "target_radius": parse_log_float(line, "target_radius"),
                    "target_distance": parse_log_float(line, "target_distance"),
                    "target_impact_radius": parse_log_float(line, "target_impact_radius"),
                    "target_damage_scale": parse_log_float(line, "target_damage_scale"),
                    "target_in_impact": parse_cast_startup_value(line, "target_in_impact"),
                    "native_cleanup_release": parse_cast_startup_value(line, "native_cleanup_release"),
                    "threshold_charge_write": parse_cast_startup_value(line, "threshold_charge_write"),
                    "threshold_max_write": parse_cast_startup_value(line, "threshold_max_write"),
                    "release_charge_write": parse_cast_startup_value(line, "release_charge_write"),
                }
            )
        complete_match = CAST_COMPLETE_RE.search(line)
        if complete_match and parse_int_text(complete_match.group(2)) == bot_id:
            complete_matches.append(
                {
                    "line": line,
                    "exit_label": complete_match.group(1),
                    "bot_id": parse_int_text(complete_match.group(2)),
                    "skill_id": parse_int_text(complete_match.group(3)),
                    "ticks": parse_int_text(complete_match.group(4)),
                    "post_release_ticks": parse_cast_startup_value(line, "post_release_ticks"),
                    "group_before": parse_cast_startup_value(line, "group_before"),
                    "slot_before": parse_cast_startup_value(line, "slot_before"),
                    "group_after": parse_cast_startup_value(line, "group_after"),
                    "cleanup_requested": parse_cast_startup_value(line, "cleanup_requested"),
                    "cleanup_actor_handle_live": parse_cast_startup_value(line, "cleanup_actor_handle_live"),
                    "handle_source": parse_log_word(line, "handle_source"),
                    "selection_state": parse_cast_startup_value(line, "selection_state"),
                    "obj_ptr": parse_cast_startup_value(line, "obj_ptr"),
                    "obj_type": parse_cast_startup_value(line, "obj_type"),
                    "obj_74": re.search(r"\bobj_74=([0-9.+\-eE]+)", line).group(1)
                    if re.search(r"\bobj_74=([0-9.+\-eE]+)", line)
                    else "",
                    "obj_1f0": re.search(r"\bobj_1f0=([0-9.+\-eE]+)", line).group(1)
                    if re.search(r"\bobj_1f0=([0-9.+\-eE]+)", line)
                    else "",
                    "obj_1fc": re.search(r"\bobj_1fc=([0-9.+\-eE]+)", line).group(1)
                    if re.search(r"\bobj_1fc=([0-9.+\-eE]+)", line)
                    else "",
                    "obj_22c": parse_cast_startup_value(line, "obj_22c"),
                    "obj_230": parse_cast_startup_value(line, "obj_230"),
                    "boulder_max_size": parse_cast_startup_value(line, "boulder_max_size"),
                }
            )
        mana_spent_match = MANA_SPENT_RE.search(line)
        if mana_spent_match and parse_int_text(mana_spent_match.group(1)) == bot_id:
            mana_spent_matches.append(
                {
                    "line": line,
                    "bot_id": parse_int_text(mana_spent_match.group(1)),
                    "skill_id": parse_int_text(mana_spent_match.group(2)),
                    "mode": mana_spent_match.group(3),
                    "statbook_level": parse_int_text(mana_spent_match.group(4)),
                    "rate": float(mana_spent_match.group(5))
                    if mana_spent_match.group(5) is not None
                    else None,
                    "cost": float(mana_spent_match.group(6)),
                    "before": float(mana_spent_match.group(7)),
                    "after": float(mana_spent_match.group(8)),
                    "total": float(mana_spent_match.group(9)),
                }
            )
        mana_rejected_match = MANA_REJECTED_RE.search(line)
        if mana_rejected_match and parse_int_text(mana_rejected_match.group(1)) == bot_id:
            mana_rejected_matches.append(
                {
                    "line": line,
                    "bot_id": parse_int_text(mana_rejected_match.group(1)),
                    "skill_id": parse_int_text(mana_rejected_match.group(2)),
                    "mode": mana_rejected_match.group(3),
                }
            )

    matching_loadout = next(
        (
            item
            for item in reversed(loadout_matches)
            if int(item["progression"]) == progression_runtime
            and int(item["primary_entry"]) == config["primary_entry_index"]
            and int(item["combo_entry"]) == config["primary_entry_index"]
            and int(item["spell_id"]) == spec["build_skill_id"]
        ),
        None,
    )
    matching_prepped = next(
        (
            item
            for item in reversed(prepped_matches)
            if int(item["skill_id"]) == spec["build_skill_id"]
            and int(item["dispatcher_skill_id"]) == spec["dispatcher_skill_id"]
            and item["lane"] == spec["lane"]
            and int(item["selection_state"]) == spec["selection_state"]
            and int(item["progression_runtime"]) == progression_runtime
            and int(item["startup_p750"]) == spec["build_skill_id"]
        ),
        None,
    )
    matching_complete = next(
        (
            item
            for item in reversed(complete_matches)
            if int(item["skill_id"]) == spec["build_skill_id"]
        ),
        None,
    )
    matching_dispatch = next(
        (
            item
            for item in reversed(dispatch_matches)
            if int(item["skill"]) == config["primary_entry_index"]
            and int(item["selection_state"]) == spec["selection_state"]
            and int(item["progression_runtime"]) == progression_runtime
        ),
        None,
    )
    continuous_dispatch_logged = bool(
        spec.get("unit") == "per_second" and matching_dispatch is not None
    )
    earth_release_policy_ok = True
    earth_release_base_damage_matches_statbook = True
    if spec.get("requires_max_size_release"):
        earth_release_labels = {"max_size_reached", "max_size_released", "damage_threshold_released"}
        matching_release = next(
            (
                item
                for item in reversed(earth_spawn_matches)
                if int(item["skill_id"]) == spec["build_skill_id"]
            ),
            None,
        )
        release_reason = str(matching_release.get("release_reason", "")) if matching_release else ""
        release_by_max_size = (
            matching_complete
            and matching_complete.get("exit_label") in {"max_size_reached", "max_size_released"}
            and int(matching_complete.get("boulder_max_size", 0)) == 1
            and matching_release is not None
            and int(matching_complete.get("cleanup_requested", 0)) == 1
            and int(matching_complete.get("post_release_ticks", 0)) >= 60
        )
        release_by_damage_threshold = (
            matching_complete
            and matching_complete.get("exit_label") == "damage_threshold_released"
            and matching_release is not None
            and release_reason == "damage_threshold"
            and int(matching_release.get("target_actor", 0)) != 0
            and int(matching_release.get("target_health", 0)) != 0
            and int(matching_complete.get("cleanup_requested", 0)) == 1
            and int(matching_complete.get("post_release_ticks", 0)) >= 60
            and float(matching_release.get("projected_damage", 0.0)) >=
                float(matching_release.get("target_hp", 0.0))
        )
        earth_release_policy_ok = bool(
            matching_complete
            and matching_complete.get("exit_label") in earth_release_labels
            and (release_by_max_size or release_by_damage_threshold)
        )
        expected_base_damage = float(statbook.get("level_damage", 0.0))
        release_statbook_damage = (
            float(matching_release.get("statbook_damage", 0.0))
            if matching_release is not None and finite_float(float(matching_release.get("statbook_damage", 0.0)))
            else float(matching_release.get("base_damage", 0.0))
            if matching_release is not None
            else 0.0
        )
        earth_release_base_damage_matches_statbook = bool(
            matching_release is not None
            and int(matching_release.get("statbook_level", -1)) == int(statbook.get("level", -2))
            and finite_float(release_statbook_damage)
            and abs(release_statbook_damage - expected_base_damage) <= 0.001
        )
    native_projectile_spawn_validation = build_native_projectile_spawn_validation(
        element,
        spec,
        matching_complete=matching_complete,
        pure_primary_start_matches=pure_primary_start_matches,
        pure_primary_builder_matches=pure_primary_builder_matches,
        earth_spawn_matches=earth_spawn_matches,
    )
    native_spawn_logged = native_projectile_spawn_validation.get("ok") is True
    pure_primary_spawn_logged = bool(spec.get("lane") == "pure_primary" and native_spawn_logged)
    cast_lifecycle_logged = bool(
        matching_complete is not None
        or continuous_dispatch_logged
        or pure_primary_spawn_logged
    )
    expected_mana_mode = "per_cast" if spec.get("unit") == "per_cast" else "per_second"
    matching_mana_spend = next(
        (
            item
            for item in reversed(mana_spent_matches)
            if int(item["skill_id"]) == spec["build_skill_id"]
            and item["mode"] == expected_mana_mode
            and int(item["statbook_level"]) == int(statbook.get("level", -1))
            and (
                (
                    expected_mana_mode == "per_cast"
                    and abs(float(item["cost"]) - float(statbook.get("level_mana", 0.0))) <= 0.001
                )
                or (
                    expected_mana_mode == "per_second"
                    and item.get("rate") is not None
                    and abs(float(item["rate"]) - float(statbook.get("level_mana", 0.0))) <= 0.001
                    and float(item["cost"]) > 0.0
                )
            )
            and float(item["after"]) < float(item["before"])
        ),
        None,
    )

    checks = {
        "profile_element_matches": profile["element_id"] == config["element_id"],
        "profile_discipline_matches": profile["discipline_id"] == DEFAULT_BOT_DISCIPLINE_ID,
        "profile_level_is_level_1": profile["level"] == 1,
        "profile_loadout_primary_matches": profile["primary_entry_index"] == config["primary_entry_index"],
        "profile_loadout_combo_matches": profile["primary_combo_entry_index"] == config["primary_entry_index"],
        "progression_runtime_nonzero": progression_runtime != 0,
        "statbook_loaded": bool(statbook.get("path")),
        "skills_wizard_loadout_logged": matching_loadout is not None,
        "cast_prepped_logged": matching_prepped is not None or continuous_dispatch_logged,
        "cast_lifecycle_logged": cast_lifecycle_logged,
        "mana_spent_from_statbook": matching_mana_spend is not None,
        "earth_release_policy_satisfied": earth_release_policy_ok,
        "earth_release_base_damage_matches_statbook": earth_release_base_damage_matches_statbook,
        "native_projectile_or_effect_spawn_logged": native_spawn_logged,
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "expected": {
            "element_id": config["element_id"],
            "primary_entry_index": config["primary_entry_index"],
            "primary_combo_entry_index": config["primary_entry_index"],
            "build_skill_id": spec["build_skill_id"],
            "dispatcher_skill_id": spec["dispatcher_skill_id"],
            "selection_state": spec["selection_state"],
            "lane": spec["lane"],
        },
        "profile": profile,
        "progression_runtime": progression_runtime,
        "statbook": statbook,
        "matching_loadout": matching_loadout,
        "matching_prepped": matching_prepped,
        "matching_complete": matching_complete,
        "matching_dispatch": matching_dispatch,
        "matching_mana_spend": matching_mana_spend,
        "native_projectile_spawn_validation": native_projectile_spawn_validation,
        "loadout_log_count": len(loadout_matches),
        "prepped_log_count": len(prepped_matches),
        "complete_log_count": len(complete_matches),
        "dispatch_log_count": len(dispatch_matches),
        "pure_primary_start_log_count": len(pure_primary_start_matches),
        "pure_primary_builder_log_count": len(pure_primary_builder_matches),
        "earth_spawn_log_count": len(earth_spawn_matches),
        "mana_spent_log_count": len(mana_spent_matches),
        "mana_rejected_log_count": len(mana_rejected_matches),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Cleanly prove bot primary projectile/effect spawn and damage delivery."
    )
    parser.add_argument(
        "--element",
        action="append",
        choices=sorted(ELEMENTS),
        help="Element to test. Repeat to test multiple. Defaults to all configured elements.",
    )
    parser.add_argument("--player-element", choices=sorted(csp.CREATE_ELEMENT_CENTERS), default=DEFAULT_PLAYER_ELEMENT)
    parser.add_argument("--discipline", choices=sorted(csp.CREATE_DISCIPLINE_CENTERS), default=DEFAULT_DISCIPLINE)
    parser.add_argument(
        "--standoff",
        type=float,
        default=None,
        help="Override bot/hostile spacing. Defaults to each element's effective damage range.",
    )
    parser.add_argument(
        "--bot-x",
        type=float,
        default=CONTROLLED_BOT_X,
        help="World X coordinate used for the controlled bot/hostile damage probe.",
    )
    parser.add_argument(
        "--bot-y",
        type=float,
        default=CONTROLLED_BOT_Y,
        help="World Y coordinate used for the controlled bot/hostile damage probe.",
    )
    parser.add_argument("--target-x", type=float, default=None, help="Override controlled hostile X.")
    parser.add_argument("--target-y", type=float, default=None, help="Override controlled hostile Y.")
    parser.add_argument("--max-hostile-gap", type=float, default=DEFAULT_MAX_HOSTILE_GAP)
    parser.add_argument("--hp", type=float, default=DEFAULT_HP)
    parser.add_argument("--casts", type=int, default=DEFAULT_CASTS)
    parser.add_argument(
        "--cast-interval-seconds",
        type=float,
        default=None,
        help="Override the per-element observation window between casts.",
    )
    parser.add_argument("--settle-seconds", type=float, default=DEFAULT_SETTLE_SECONDS)
    parser.add_argument("--enemy-watch-count", type=int, default=DEFAULT_ENEMY_WATCH_COUNT)
    parser.add_argument(
        "--setup-mode",
        choices=SETUP_MODES,
        default="waves",
        help="waves uses stock-spawned enemies; manual_prelude is diagnostic only and may wedge native spawn.",
    )
    parser.add_argument(
        "--positioning",
        choices=POSITIONING_MODES,
        default="auto",
        help=(
            "auto chooses the stable per-element validation mode; bot_only preserves native enemy "
            "movement and moves only the synthetic bot; force_both is the controlled-position "
            "diagnostic used for collision-sensitive casts."
        ),
    )
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--keep-running", action="store_true")
    parser.add_argument(
        "--trace-air-handler",
        action="store_true",
        help="Trace the recovered Air lightning action handler during Air probes.",
    )
    parser.add_argument(
        "--trace-builder-window",
        action="store_true",
        help="Trace the native builder/sink path during each element probe.",
    )
    parser.add_argument(
        "--trace-profile",
        default=DEFAULT_TRACE_PROFILE,
        choices=trace_profile_names(),
        help="Trace subset to arm when --trace-builder-window is set.",
    )
    parser.add_argument(
        "--allow-unstable-inline-traces",
        action="store_true",
        help="Permit unstable in-function trace points for deeper diagnostics.",
    )
    parser.add_argument(
        "--watch-target-hp",
        action="store_true",
        help="Deprecated alias. HP validation now tracks every nearby hostile by default.",
    )
    parser.add_argument(
        "--skip-hostile-hp-watches",
        action="store_true",
        help="Skip write watches and validate only by before/after hostile HP snapshots.",
    )
    parser.add_argument(
        "--watch-damage-context",
        action="store_true",
        help="Arm write watches on the native global damage context while casting.",
    )
    parser.add_argument(
        "--trace-native-hit-path",
        action="store_true",
        help="Diagnostic: trace the recovered native target query/collision/damage path.",
    )
    parser.add_argument(
        "--bot-starting-mp",
        type=float,
        default=None,
        help="Diagnostic: force the bot progression MP before casting.",
    )
    parser.add_argument(
        "--expect-mana-rejected",
        action="store_true",
        help="Validate that the queued cast is rejected for insufficient mana.",
    )
    return parser


def query_bot_by_id(bot_id: int) -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local wanted = {bot_id}
local bots = sd.bots and sd.bots.get_state and sd.bots.get_state() or {{}}
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
	for _, bot in ipairs(bots) do
	  if tonumber(bot.id) == wanted then
	    emit('available', true)
	    for _, key in ipairs({{
	      'id','actor_address','progression_runtime_state_address','progression_handle_address',
	      'equip_handle_address','equip_runtime_state_address','gameplay_slot','actor_slot',
	      'hp','max_hp','mp','max_mp','x','y','state'
	    }}) do
	      emit(key, bot[key])
	    end
	    local profile = bot.profile or {{}}
	    local loadout = profile.loadout or {{}}
	    emit('profile.element_id', profile.element_id)
	    emit('profile.discipline_id', profile.discipline_id)
	    emit('profile.level', profile.level)
	    emit('profile.experience', profile.experience)
	    emit('profile.loadout.primary_entry_index', loadout.primary_entry_index)
	    emit('profile.loadout.primary_combo_entry_index', loadout.primary_combo_entry_index)
	    return
	  end
	end
emit('available', false)
""".strip()
        )
    )


def query_live_bot_binding_by_id(bot_id: int) -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local wanted = {bot_id}
local bots = sd.bots and sd.bots.get_state and sd.bots.get_state() or {{}}
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
for _, bot in ipairs(bots) do
  if tonumber(bot.id) == wanted then
    local actor = tonumber(bot.actor_address) or 0
    if actor ~= 0 then
      emit('available', true)
      emit('id', bot.id)
      emit('actor_address', actor)
      emit('progression_runtime_state_address', bot.progression_runtime_state_address)
      emit('progression_handle_address', bot.progression_handle_address)
      emit('equip_handle_address', bot.equip_handle_address)
      emit('equip_runtime_state_address', bot.equip_runtime_state_address)
      emit('gameplay_slot', bot.gameplay_slot)
      emit('actor_slot', bot.actor_slot)
      emit('hp', bot.hp)
      emit('max_hp', bot.max_hp)
	      emit('mp', bot.mp)
	      emit('max_mp', bot.max_mp)
	      emit('x', sd.debug.read_float(actor + 0x18))
	      emit('y', sd.debug.read_float(actor + 0x1C))
	      emit('state', bot.state)
	      local profile = bot.profile or {{}}
	      local loadout = profile.loadout or {{}}
	      emit('profile.element_id', profile.element_id)
	      emit('profile.discipline_id', profile.discipline_id)
	      emit('profile.level', profile.level)
	      emit('profile.experience', profile.experience)
	      emit('profile.loadout.primary_entry_index', loadout.primary_entry_index)
	      emit('profile.loadout.primary_combo_entry_index', loadout.primary_combo_entry_index)
	      return
	    end
	  end
end
emit('available', false)
""".strip()
        )
    )


def wait_for_bot_by_id(bot_id: int, timeout_s: float = 30.0) -> dict[str, str]:
    deadline = time.time() + timeout_s
    last: dict[str, str] = {}
    while time.time() < deadline:
        last = query_live_bot_binding_by_id(bot_id)
        if last.get("available") != "true":
            last = query_bot_by_id(bot_id)
        if last.get("available") == "true" and csp.int_value(last, "actor_address") != 0:
            return last
        time.sleep(0.25)
    raise ElementDamageProbeFailure(f"Timed out waiting for bot {bot_id} materialization. Last={last}")


def create_single_run_bot(element: str, player: dict[str, str], x: float, y: float) -> int:
    config = ELEMENTS[element]
    bot_name = f"Damage Probe {element.title()}"
    result = csp.parse_key_values(
        csp.run_lua(
            f"""
local id = sd.bots.create({{
  name = {json.dumps(bot_name)},
  profile = {{
    element_id = {config["element_id"]},
    discipline_id = {DEFAULT_BOT_DISCIPLINE_ID},
    level = 1,
    experience = 0,
    loadout = {{
      primary_entry_index = {config["primary_entry_index"]},
      primary_combo_entry_index = {config["primary_entry_index"]},
      secondary_entry_indices = {{ -1, -1, -1 }},
    }},
  }},
  scene = {{ kind = 'run' }},
  ready = true,
  position = {{ x = {x}, y = {y}, heading = 90.0 }},
}})
print('ok=' .. tostring(id ~= nil))
print('bot_id=' .. tostring(id))
""".strip()
        )
    )
    if result.get("ok") != "true":
        raise ElementDamageProbeFailure(f"sd.bots.create failed for {element}: {result}")
    bot_id = csp.int_value(result, "bot_id")
    if bot_id == 0:
        raise ElementDamageProbeFailure(f"sd.bots.create returned no id for {element}: {result}")
    return bot_id


def read_runtime_layout_offset(name: str) -> int:
    text = RUNTIME_BINARY_LAYOUT_PATH.read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", ";")) or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        if key.strip() == name:
            return int(value.strip(), 0)
    raise ElementDamageProbeFailure(
        f"Unable to find {name!r} in {RUNTIME_BINARY_LAYOUT_PATH}"
    )


def force_bot_progression_mp(bot_id: int, mp: float) -> dict[str, str]:
    mp_offset = read_runtime_layout_offset("progression_mp")
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local bot_id = {bot_id}
local requested_mp = {mp}
local mp_offset = {mp_offset}
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
local bot = sd.bots.get_state(bot_id)
if type(bot) ~= 'table' then
  emit('ok', false)
  emit('error', 'bot_not_found')
  return
end
local progression = tonumber(bot.progression_runtime_state_address) or 0
if progression == 0 then
  emit('ok', false)
  emit('error', 'missing_progression_runtime')
  return
end
emit('before', bot.mp)
local mp_address = progression + mp_offset
emit('write_ok', sd.debug.write_float(mp_address, requested_mp))
emit('raw_after', sd.debug.read_float(mp_address))
local refreshed = sd.bots.get_state(bot_id) or {{}}
emit('snapshot_after', refreshed.mp)
emit('max_mp', refreshed.max_mp)
emit('progression_runtime', progression)
emit('mp_offset', mp_offset)
emit('mp_address', mp_address)
emit('ok', refreshed.mp ~= nil)
""".strip()
        )
    )


def query_scene_actor_by_address(actor_address: int) -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local wanted = {actor_address}
local actors = sd.world and sd.world.list_actors and sd.world.list_actors() or {{}}
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
for _, actor in ipairs(actors) do
  if tonumber(actor.actor_address) == wanted then
    emit('available', true)
    for _, key in ipairs({{
      'actor_address','object_type_id','tracked_enemy','enemy_type','dead',
      'hp','max_hp','x','y','actor_slot','world_slot'
    }}) do
      emit(key, actor[key])
    end
    return
  end
end
emit('available', false)
emit('actor_address', wanted)
""".strip()
        )
    )


def wait_for_spawn_result(request_id: int, timeout_s: float = 10.0) -> dict[str, str]:
    deadline = time.time() + timeout_s
    last: dict[str, str] = {}
    while time.time() < deadline:
        last = csp.parse_key_values(
            csp.run_lua(
                f"""
local wanted = {request_id}
local result = sd.world.get_last_spawned_enemy and sd.world.get_last_spawned_enemy(wanted) or nil
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
if type(result) ~= 'table' then
  emit('available', false)
  emit('request_id', wanted)
  return
end
emit('available', true)
for _, key in ipairs({{
  'valid','ok','request_id','type_id','actor_address','requested_x','requested_y',
  'x','y','wrote_x','wrote_y','rebind_ok','rebind_exception_code',
  'completed_tick_ms','error_message'
}}) do
  emit(key, result[key])
end
""".strip()
            )
        )
        if last.get("available") == "true":
            return last
        time.sleep(0.1)
    raise ElementDamageProbeFailure(
        f"Timed out waiting for manual enemy spawn result request_id={request_id}. Last={last}"
    )


def spawn_hostile_near_position(x: float, y: float, standoff: float) -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local ok, err, request_id = sd.world.spawn_enemy({{
  type_id = {MANUAL_SPAWN_ENEMY_TYPE_ID},
  x = {x + standoff},
  y = {y},
}})
print('ok=' .. tostring(ok))
print('err=' .. tostring(err))
print('request_id=' .. tostring(request_id))
""".strip()
        )
    )


def query_watchable_hostiles(limit: int, origin_actor_address: int) -> list[dict[str, object]]:
    output = csp.run_lua(
        f"""
local limit = {max(limit, 1)}
local origin = {origin_actor_address}
local ox = 0.0
local oy = 0.0
if origin ~= 0 then
  ox = tonumber(sd.debug.read_float(origin + 0x18)) or 0.0
  oy = tonumber(sd.debug.read_float(origin + 0x1C)) or 0.0
end
local actors = sd.world and sd.world.list_actors and sd.world.list_actors() or {{}}
local rows = {{}}
for _, actor in ipairs(actors) do
  local actor_address = tonumber(actor.actor_address) or 0
  local tracked = actor.tracked_enemy == true
  local dead = actor.dead == true
  local hp = tonumber(actor.hp) or 0.0
  local max_hp = tonumber(actor.max_hp) or 0.0
  if actor_address ~= 0 and tracked and not dead and hp > 0.0 and max_hp > 0.0 then
    local ax = tonumber(actor.x) or 0.0
    local ay = tonumber(actor.y) or 0.0
    local dx = ax - ox
    local dy = ay - oy
    rows[#rows + 1] = {{
      actor_address = actor_address,
      object_type_id = actor.object_type_id,
      enemy_type = actor.enemy_type,
      hp = hp,
      max_hp = max_hp,
      x = ax,
      y = ay,
      gap = math.sqrt(dx * dx + dy * dy),
    }}
  end
end
table.sort(rows, function(a, b) return a.gap < b.gap end)
for i = 1, math.min(#rows, limit) do
  local row = rows[i]
  print('enemy.' .. i .. '.actor_address=' .. tostring(row.actor_address))
  print('enemy.' .. i .. '.object_type_id=' .. tostring(row.object_type_id))
  print('enemy.' .. i .. '.enemy_type=' .. tostring(row.enemy_type))
  print('enemy.' .. i .. '.hp=' .. tostring(row.hp))
  print('enemy.' .. i .. '.max_hp=' .. tostring(row.max_hp))
  print('enemy.' .. i .. '.x=' .. tostring(row.x))
  print('enemy.' .. i .. '.y=' .. tostring(row.y))
  print('enemy.' .. i .. '.gap=' .. tostring(row.gap))
end
print('count=' .. tostring(math.min(#rows, limit)))
print('total=' .. tostring(#rows))
""".strip()
    )
    values = csp.parse_key_values(output)
    rows: list[dict[str, object]] = []
    for index in range(1, csp.int_value(values, "count") + 1):
        actor_address = csp.int_value(values, f"enemy.{index}.actor_address")
        if actor_address == 0:
            continue
        rows.append(
            {
                "name": f"hostile_hp_{index}",
                "actor_address": actor_address,
                "hp_address": actor_address + ARENA_ENEMY_CURRENT_HP_OFFSET,
                "object_type_id": csp.int_value(values, f"enemy.{index}.object_type_id"),
                "enemy_type": values.get(f"enemy.{index}.enemy_type", ""),
                "hp": values.get(f"enemy.{index}.hp", ""),
                "max_hp": values.get(f"enemy.{index}.max_hp", ""),
                "x": values.get(f"enemy.{index}.x", ""),
                "y": values.get(f"enemy.{index}.y", ""),
                "gap": values.get(f"enemy.{index}.gap", ""),
            }
        )
    return rows


def ensure_hostile_is_watched(hostiles: list[dict[str, object]], actor_address: int) -> list[dict[str, object]]:
    if any(int(row.get("actor_address", 0)) == actor_address for row in hostiles):
        return hostiles
    actor = query_scene_actor_by_address(actor_address)
    if actor.get("available") != "true":
        return hostiles
    return [
        {
            "name": f"hostile_hp_{len(hostiles) + 1}",
            "actor_address": actor_address,
            "hp_address": actor_address + ARENA_ENEMY_CURRENT_HP_OFFSET,
            "object_type_id": csp.int_value(actor, "object_type_id"),
            "enemy_type": actor.get("enemy_type", ""),
            "hp": actor.get("hp", ""),
            "max_hp": actor.get("max_hp", ""),
            "x": actor.get("x", ""),
            "y": actor.get("y", ""),
            "gap": "",
        }
    ] + hostiles


def select_live_watched_hostile(
    bot_actor_address: int,
    watched_hostiles: list[dict[str, object]],
    limit: int,
    preferred_actor_address: int = 0,
) -> tuple[int, dict[str, str]]:
    watched_addresses = {int(row.get("actor_address", 0)) for row in watched_hostiles}
    if preferred_actor_address and preferred_actor_address in watched_addresses:
        state = query_scene_actor_by_address(preferred_actor_address)
        if state.get("available") == "true":
            return preferred_actor_address, state

    current_hostiles = query_watchable_hostiles(limit, bot_actor_address)
    for hostile in current_hostiles:
        actor_address = int(hostile.get("actor_address", 0))
        if actor_address not in watched_addresses:
            continue
        state = query_scene_actor_by_address(actor_address)
        if state.get("available") == "true":
            return actor_address, state
    raise ElementDamageProbeFailure("No watched hostile remained live immediately before cast.")


def acquire_live_watched_hostile(
    *,
    element: str,
    bot_actor_address: int,
    limit: int,
    skip_watches: bool,
    old_watch_names: list[str],
    result: dict[str, object],
    reason: str,
    preferred_actor_address: int = 0,
    baseline_hp: float | None = None,
    timeout_s: float = 8.0,
) -> tuple[list[dict[str, object]], list[str], int, dict[str, str]]:
    if old_watch_names:
        clear_hostile_hp_watches(old_watch_names)
        old_watch_names = []

    deadline = time.time() + timeout_s
    last_hostiles: list[dict[str, object]] = []
    last_error = ""
    while time.time() < deadline:
        hostiles = query_watchable_hostiles(limit, bot_actor_address)
        if preferred_actor_address:
            hostiles = ensure_hostile_is_watched(hostiles, preferred_actor_address)
        last_hostiles = hostiles
        if not hostiles:
            time.sleep(0.15)
            continue

        try:
            actor_address, state = select_live_watched_hostile(
                bot_actor_address,
                hostiles,
                limit,
                preferred_actor_address,
            )
        except ElementDamageProbeFailure as exc:
            last_error = str(exc)
            time.sleep(0.15)
            continue

        if baseline_hp is not None:
            force_target_vitals_for_baseline(
                result,
                actor_address,
                baseline_hp,
                f"{reason}:selected_hostile",
            )
            state = query_scene_actor_by_address(actor_address)
            if state.get("available") != "true":
                last_error = f"selected hostile disappeared after vitals reset: {state}"
                time.sleep(0.15)
                continue

        watch_names: list[str] = []
        watches: dict[str, dict[str, object]] = {}
        if not skip_watches:
            watches = arm_hostile_hp_watches(element, hostiles)
            watch_names = list(watches.keys())

        result["watched_hostiles"] = hostiles
        result["hostile_hp_watches"] = watches
        refreshes = result.setdefault("hostile_watch_refreshes", [])
        if isinstance(refreshes, list):
            refreshes.append(
                {
                    "reason": reason,
                    "count": len(hostiles),
                    "target_actor_address": actor_address,
                    "watched": bool(watch_names),
                }
            )
        return hostiles, watch_names, actor_address, state

    raise ElementDamageProbeFailure(
        f"Timed out acquiring live watched hostile for {element} during {reason}. "
        f"last_count={len(last_hostiles)} last_error={last_error}"
    )


def arm_hostile_hp_watches(element: str, hostiles: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    if not hostiles:
        return {}

    lua_lines = [
        "local function emit(key, value)",
        "  if value == nil then",
        "    print(key .. '=')",
        "  else",
        "    print(key .. '=' .. tostring(value))",
        "  end",
        "end",
    ]
    for index, hostile in enumerate(hostiles, start=1):
        actor_address = int(hostile["actor_address"])
        name = f"bot_{element}_enemy_hp_{index}_{actor_address:x}"
        hostile["name"] = name
        lua_lines.append(f"pcall(sd.debug.unwatch, {json.dumps(name)})")
        lua_lines.append(f"sd.debug.clear_write_hits({json.dumps(name)})")
    for hostile in hostiles:
        name = str(hostile["name"])
        hp_address = int(hostile["hp_address"])
        lua_lines.append(f"emit({json.dumps(name)}, sd.debug.watch_write({json.dumps(name)}, {hp_address}, 4))")
        lua_lines.append(f"emit({json.dumps(name)} .. '_hp_address', {hp_address})")
    values = csp.parse_key_values(csp.run_lua("\n".join(lua_lines)))

    armed: dict[str, dict[str, object]] = {}
    for hostile in hostiles:
        name = str(hostile["name"])
        armed[name] = {
            **hostile,
            "watch_ok": values.get(name, "false"),
            "armed_hp_address": csp.int_value(values, f"{name}_hp_address"),
        }
    return armed


def clear_hostile_hp_watches(names: list[str]) -> None:
    if not names:
        return
    lua_lines = []
    for name in names:
        lua_lines.append(f"pcall(sd.debug.unwatch, {json.dumps(name)})")
        lua_lines.append(f"sd.debug.clear_write_hits({json.dumps(name)})")
    csp.run_lua("\n".join(lua_lines))


def clear_write_hits(names: list[str]) -> None:
    if not names:
        return
    lua_lines = [f"sd.debug.clear_write_hits({json.dumps(name)})" for name in names]
    csp.run_lua("\n".join(lua_lines))


def arm_damage_context_watches(element: str) -> dict[str, dict[str, object]]:
    lua_lines = [
        "local function emit(key, value)",
        "  if value == nil then",
        "    print(key .. '=')",
        "  else",
        "    print(key .. '=' .. tostring(value))",
        "  end",
        "end",
    ]
    names: dict[str, tuple[str, int, int]] = {}
    for key, (address, size) in NATIVE_DAMAGE_CONTEXT_WATCHES.items():
        name = f"bot_{element}_damage_context_{key}"
        names[key] = (name, address, size)
        lua_lines.append(f"pcall(sd.debug.unwatch, {json.dumps(name)})")
        lua_lines.append(f"sd.debug.clear_write_hits({json.dumps(name)})")
    for key, (name, address, size) in names.items():
        lua_lines.append(
            f"local {key}_addr = "
            f"(sd.debug.resolve_game_address and sd.debug.resolve_game_address({address})) or {address}"
        )
        lua_lines.append(f"emit({json.dumps(name)}, sd.debug.watch_write({json.dumps(name)}, {key}_addr, {size}))")
        lua_lines.append(f"emit({json.dumps(name)} .. '_address', {address})")
        lua_lines.append(f"emit({json.dumps(name)} .. '_resolved_address', {key}_addr)")
    values = csp.parse_key_values(csp.run_lua("\n".join(lua_lines)))
    return {
        name: {
            "key": key,
            "game_address": address,
            "size": size,
            "watch_ok": values.get(name, "false"),
            "armed_address": csp.int_value(values, f"{name}_address"),
            "resolved_address": csp.int_value(values, f"{name}_resolved_address"),
        }
        for key, (name, address, size) in names.items()
    }


def clear_damage_context_watches(names: list[str]) -> None:
    if not names:
        return
    lua_lines = []
    for name in names:
        lua_lines.append(f"pcall(sd.debug.unwatch, {json.dumps(name)})")
        lua_lines.append(f"sd.debug.clear_write_hits({json.dumps(name)})")
    csp.run_lua("\n".join(lua_lines))


def force_scene_actor_vitals(actor_address: int, hp_value: float) -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local actor = {actor_address}
local type_id = tonumber(sd.debug.read_u32(actor + 0x08)) or 0
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
emit('actor_address', actor)
emit('object_type_id', type_id)
if type_id == {ARENA_ENEMY_OBJECT_TYPE_ID} then
  emit('max_hp_ok', sd.debug.write_float(actor + {ARENA_ENEMY_MAX_HP_OFFSET}, {hp_value}))
  emit('hp_ok', sd.debug.write_float(actor + {ARENA_ENEMY_CURRENT_HP_OFFSET}, {hp_value}))
  emit('max_hp', sd.debug.read_float(actor + {ARENA_ENEMY_MAX_HP_OFFSET}))
  emit('hp', sd.debug.read_float(actor + {ARENA_ENEMY_CURRENT_HP_OFFSET}))
else
  emit('max_hp_ok', false)
  emit('hp_ok', false)
end
""".strip()
        )
    )


def force_target_vitals_for_baseline(
    result: dict[str, object],
    actor_address: int,
    hp_value: float,
    reason: str,
) -> dict[str, str]:
    forced = force_scene_actor_vitals(actor_address, hp_value)
    forced["reason"] = reason
    events = result.setdefault("forced_vitals_events", [])
    if isinstance(events, list):
        events.append(dict(forced))
    return forced


def force_specific_target_range(
    bot_actor_address: int,
    hostile_actor_address: int,
    standoff: float,
    *,
    heading: float = 90.0,
    bot_hp: float = 500.0,
    bot_x: float = CONTROLLED_BOT_X,
    bot_y: float = CONTROLLED_BOT_Y,
    target_x: float | None = None,
    target_y: float | None = None,
) -> dict[str, str]:
    safe_bot_x = bot_x
    safe_bot_y = bot_y
    safe_target_x = safe_bot_x + standoff if target_x is None else target_x
    safe_target_y = safe_bot_y if target_y is None else target_y
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
local bot = {bot_actor_address}
local hostile = {hostile_actor_address}
	local standoff = {standoff}
	local hx = {safe_target_x}
	local hy = {safe_target_y}
	local bx = {safe_bot_x}
	local by = {safe_bot_y}
local prog = tonumber(sd.debug.read_ptr(bot + 0x200)) or 0
local handle = tonumber(sd.debug.read_ptr(bot + 0x300)) or 0
if prog == 0 and handle ~= 0 then
  prog = tonumber(sd.debug.read_ptr(handle)) or 0
end
emit('bot_actor_address', bot)
emit('hostile_actor_address', hostile)
emit('bot_x', bx)
emit('bot_y', by)
emit('hostile_x', hx)
emit('hostile_y', hy)
emit('bot_progression', prog)
if prog ~= 0 then
  emit('bot_hp_ok', sd.debug.write_float(prog + {csp.PROGRESSION_HP_OFFSET}, {bot_hp}))
  emit('bot_max_hp_ok', sd.debug.write_float(prog + {csp.PROGRESSION_MAX_HP_OFFSET}, {bot_hp}))
end
emit('target_x', hx)
emit('target_y', hy)
emit('hostile_x_ok', sd.debug.write_float(hostile + 0x18, hx))
emit('hostile_y_ok', sd.debug.write_float(hostile + 0x1C, hy))
emit('hostile_move_speed_ok', sd.debug.write_float(hostile + 0x74, 0.0))
emit('hostile_speed_mult_ok', sd.debug.write_float(hostile + 0x120, 0.0))
emit('hostile_move_input_x_ok', sd.debug.write_float(hostile + 0x158, 0.0))
emit('hostile_move_input_y_ok', sd.debug.write_float(hostile + 0x15C, 0.0))
emit('hostile_move_step_ok', sd.debug.write_float(hostile + 0x218, 0.0))
emit('bot_x_ok', sd.debug.write_float(bot + 0x18, bx))
emit('bot_y_ok', sd.debug.write_float(bot + 0x1C, by))
emit('bot_heading_ok', sd.debug.write_float(bot + 0x6C, {heading}))
if sd.world and sd.world.rebind_actor then
  emit('hostile_rebind_ok', sd.world.rebind_actor(hostile))
  emit('bot_rebind_ok', sd.world.rebind_actor(bot))
end
local dx = (tonumber(sd.debug.read_float(hostile + 0x18)) or hx) - (tonumber(sd.debug.read_float(bot + 0x18)) or bx)
local dy = (tonumber(sd.debug.read_float(hostile + 0x1C)) or hy) - (tonumber(sd.debug.read_float(bot + 0x1C)) or by)
emit('gap', math.sqrt(dx * dx + dy * dy))
""".strip()
        )
    )


def position_bot_near_live_target(
    bot_actor_address: int,
    hostile_actor_address: int,
    standoff: float,
    *,
    heading: float = 90.0,
    bot_hp: float = 500.0,
) -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
local bot = {bot_actor_address}
local hostile = {hostile_actor_address}
local standoff = {standoff}
local type_id = tonumber(sd.debug.read_u32(hostile + 0x08)) or 0
local hp = tonumber(sd.debug.read_float(hostile + {ARENA_ENEMY_CURRENT_HP_OFFSET})) or 0.0
local hx = tonumber(sd.debug.read_float(hostile + 0x18)) or 0.0
local hy = tonumber(sd.debug.read_float(hostile + 0x1C)) or 0.0
local bx = hx - standoff
local by = hy
local prog = tonumber(sd.debug.read_ptr(bot + 0x200)) or 0
local handle = tonumber(sd.debug.read_ptr(bot + 0x300)) or 0
if prog == 0 and handle ~= 0 then
  prog = tonumber(sd.debug.read_ptr(handle)) or 0
end
emit('positioning', 'bot_only')
emit('bot_actor_address', bot)
emit('hostile_actor_address', hostile)
emit('hostile_available', type_id == {ARENA_ENEMY_OBJECT_TYPE_ID} and hp > 0.0)
emit('hostile_type_id', type_id)
emit('hostile_hp', hp)
emit('bot_x', bx)
emit('bot_y', by)
emit('hostile_x', hx)
emit('hostile_y', hy)
emit('target_x', hx)
emit('target_y', hy)
emit('bot_progression', prog)
if prog ~= 0 then
  emit('bot_hp_ok', sd.debug.write_float(prog + {csp.PROGRESSION_HP_OFFSET}, {bot_hp}))
  emit('bot_max_hp_ok', sd.debug.write_float(prog + {csp.PROGRESSION_MAX_HP_OFFSET}, {bot_hp}))
end
emit('bot_x_ok', sd.debug.write_float(bot + 0x18, bx))
emit('bot_y_ok', sd.debug.write_float(bot + 0x1C, by))
emit('bot_heading_ok', sd.debug.write_float(bot + 0x6C, {heading}))
if sd.world and sd.world.rebind_actor then
  emit('bot_rebind_ok', sd.world.rebind_actor(bot))
end
local actual_bx = tonumber(sd.debug.read_float(bot + 0x18)) or bx
local actual_by = tonumber(sd.debug.read_float(bot + 0x1C)) or by
local dx = hx - actual_bx
local dy = hy - actual_by
emit('gap', math.sqrt(dx * dx + dy * dy))
""".strip()
        )
    )


def sample_specific_target_range(
    bot_actor_address: int,
    hostile_actor_address: int,
) -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
local bot = {bot_actor_address}
local hostile = {hostile_actor_address}
local bx = tonumber(sd.debug.read_float(bot + 0x18)) or 0.0
local by = tonumber(sd.debug.read_float(bot + 0x1C)) or 0.0
local hx = tonumber(sd.debug.read_float(hostile + 0x18)) or 0.0
local hy = tonumber(sd.debug.read_float(hostile + 0x1C)) or 0.0
local dx = hx - bx
local dy = hy - by
emit('bot_actor_address', bot)
emit('hostile_actor_address', hostile)
emit('bot_x', bx)
emit('bot_y', by)
emit('hostile_x', hx)
emit('hostile_y', hy)
emit('target_x', hx)
emit('target_y', hy)
emit('gap', math.sqrt(dx * dx + dy * dy))
""".strip()
        )
    )


def establish_probe_range(
    bot_actor_address: int,
    hostile_actor_address: int,
    standoff: float,
    positioning: str,
    *,
    bot_x: float = CONTROLLED_BOT_X,
    bot_y: float = CONTROLLED_BOT_Y,
    target_x: float | None = None,
    target_y: float | None = None,
) -> dict[str, str]:
    if positioning == "force_both":
        return force_specific_target_range(
            bot_actor_address,
            hostile_actor_address,
            standoff,
            bot_x=bot_x,
            bot_y=bot_y,
            target_x=target_x,
            target_y=target_y,
        )
    return position_bot_near_live_target(
        bot_actor_address,
        hostile_actor_address,
        standoff,
    )


def probe_range_setup_succeeded(range_setup: dict[str, str], max_gap: float) -> bool:
    if range_setup.get("hostile_available") == "false":
        return False
    if range_setup.get("bot_x_ok") != "true" or range_setup.get("bot_y_ok") != "true":
        return False
    if range_setup.get("hostile_x_ok") == "false" or range_setup.get("hostile_y_ok") == "false":
        return False
    if range_setup.get("bot_rebind_ok") == "false" or range_setup.get("hostile_rebind_ok") == "false":
        return False
    return csp.float_value(range_setup, "gap") <= max_gap


def pin_target_during_window(
    bot_actor_address: int,
    hostile_actor_address: int,
    standoff: float,
    duration_s: float,
    step_s: float = 0.10,
    bot_x: float = CONTROLLED_BOT_X,
    bot_y: float = CONTROLLED_BOT_Y,
    target_x: float | None = None,
    target_y: float | None = None,
) -> list[dict[str, str]]:
    samples: list[dict[str, str]] = []
    deadline = time.time() + max(duration_s, 0.0)
    while time.time() < deadline:
        samples.append(
            force_specific_target_range(
                bot_actor_address,
                hostile_actor_address,
                standoff,
                bot_x=bot_x,
                bot_y=bot_y,
                target_x=target_x,
                target_y=target_y,
            )
        )
        time.sleep(max(step_s, 0.02))
    return samples


def pin_bot_near_live_target_during_window(
    bot_actor_address: int,
    hostile_actor_address: int,
    standoff: float,
    duration_s: float,
    step_s: float = 0.10,
) -> list[dict[str, str]]:
    samples: list[dict[str, str]] = []
    deadline = time.time() + max(duration_s, 0.0)
    while time.time() < deadline:
        samples.append(
            position_bot_near_live_target(
                bot_actor_address,
                hostile_actor_address,
                standoff,
            )
        )
        time.sleep(max(step_s, 0.02))
    return samples


def pin_probe_range_during_window(
    bot_actor_address: int,
    hostile_actor_address: int,
    standoff: float,
    duration_s: float,
    positioning: str,
    *,
    bot_x: float = CONTROLLED_BOT_X,
    bot_y: float = CONTROLLED_BOT_Y,
    target_x: float | None = None,
    target_y: float | None = None,
) -> list[dict[str, str]]:
    if positioning == "force_both":
        return pin_target_during_window(
            bot_actor_address,
            hostile_actor_address,
            standoff,
            duration_s,
            bot_x=bot_x,
            bot_y=bot_y,
            target_x=target_x,
            target_y=target_y,
        )
    return pin_bot_near_live_target_during_window(
        bot_actor_address,
        hostile_actor_address,
        standoff,
        duration_s,
    )


def arm_trace(name: str, address: int, patch_size: int = 0) -> dict[str, str]:
    trace_call = (
        f"sd.debug.trace_function({address}, {json.dumps(name)})"
        if patch_size <= 0
        else f"sd.debug.trace_function({address}, {json.dumps(name)}, {patch_size})"
    )
    return csp.parse_key_values(
        csp.run_lua(
            f"""
pcall(sd.debug.untrace_function, {address})
sd.debug.clear_trace_hits({json.dumps(name)})
print('ok=' .. tostring({trace_call}))
print('error=' .. tostring(sd.debug.get_last_error and sd.debug.get_last_error() or ''))
""".strip()
        )
    )


def clear_trace(name: str, address: int) -> None:
    csp.run_lua(
        f"""
pcall(sd.debug.untrace_function, {address})
sd.debug.clear_trace_hits({json.dumps(name)})
""".strip()
    )


def query_trace_hits(name: str) -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local hits = sd.debug.get_trace_hits({json.dumps(name)}) or {{}}
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
emit('count', #hits)
for i = 1, math.min(#hits, 16) do
  local hit = hits[i]
  for _, key in ipairs({{
    'requested_address','resolved_address','thread_id','eax','ecx','edx','ebx',
    'esi','edi','ebp','esp_before_pushad','ret','arg0','arg1','arg2','arg3','arg4','arg5','arg6','arg7','arg8'
  }}) do
    emit('hit.' .. i .. '.' .. key, hit[key])
  end
end
""".strip()
        )
    )


def arm_builder_traces(element: str, profile: str) -> tuple[dict[str, dict[str, str]], list[tuple[str, int]]]:
    results: dict[str, dict[str, str]] = {}
    armed: list[tuple[str, int]] = []
    for spec in build_trace_specs(f"bot_{element}_primary", profile):
        result = arm_trace(spec.name, spec.address, spec.patch_size)
        results[spec.name] = result
        if result.get("ok") == "true":
            armed.append((spec.name, spec.address))
    return results, armed


def native_hit_path_traces_for_element(element: str) -> dict[str, int]:
    traces = dict(COMMON_NATIVE_HIT_PATH_TRACES)
    traces.update(ELEMENT_NATIVE_HIT_PATH_TRACES.get(element, {}))
    return traces


def arm_native_hit_path_traces(element: str) -> tuple[dict[str, dict[str, str]], list[tuple[str, int]]]:
    results: dict[str, dict[str, str]] = {}
    armed: list[tuple[str, int]] = []
    for key, address in native_hit_path_traces_for_element(element).items():
        name = f"bot_{element}_{key}"
        result = arm_trace(name, address)
        results[name] = result
        if result.get("ok") == "true":
            armed.append((name, address))
    return results, armed


def query_write_hits(name: str) -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local hits = sd.debug.get_write_hits({json.dumps(name)}) or {{}}
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
emit("count", #hits)
for i = 1, math.min(#hits, 16) do
  local hit = hits[i]
  for _, key in ipairs({{
    "requested_address","resolved_address","base_address","access_address",
    "thread_id","eip","esp","ebp","eax","ecx","edx","ret","arg0","arg1","arg2"
  }}) do
    emit("hit." .. i .. "." .. key, hit[key])
  end
end
""".strip()
        )
    )


def prepare_clean_run(player_element: str, discipline: str) -> dict[str, object]:
    last_error: Exception | None = None
    for attempt in range(3):
        csp.stop_game()
        csp.clear_loader_log()
        csp.launch_game()
        process_id = csp.wait_for_game_process(timeout_s=45.0)
        csp.wait_for_lua_pipe(timeout_s=60.0)
        early_tick_gate = crc.set_lua_tick_enabled(False)
        try:
            hub_flow = csp.drive_hub_flow(
                process_id,
                element=player_element,
                discipline=discipline,
                prefer_resume=False,
            )
            break
        except csp.ProbeFailure as exc:
            last_error = exc
            csp.stop_game()
            if attempt >= 2:
                raise
    else:
        raise ElementDamageProbeFailure(f"Unable to reach clean hub scene: {last_error}") from last_error

    tick_gate = crc.set_lua_tick_enabled(False)
    clear_result = crc.clear_bots()
    testrun = crc.start_testrun_without_waves()
    post_run_clear = crc.clear_bots()
    return {
        "process_id": process_id,
        "hub_flow": hub_flow,
        "early_lua_tick_gate": early_tick_gate,
        "lua_tick_gate": tick_gate,
        "clear_bots": clear_result,
        "post_run_clear_bots": post_run_clear,
        "testrun": testrun,
    }


def finite_float(value: float) -> bool:
    return not math.isnan(value) and math.isfinite(value)


def hostile_hp_write_count(result: dict[str, object], watch_name: str) -> int:
    hits = result.get("hostile_hp_write_hits")
    if not isinstance(hits, dict):
        return 0
    watch_hits = hits.get(watch_name)
    if not isinstance(watch_hits, dict):
        return 0
    return csp.int_value(watch_hits, "count")


def summarize_hostile_damage(
    result: dict[str, object],
    watched_hostiles: list[dict[str, object]],
    target_actor: int,
) -> tuple[list[dict[str, object]], dict[int, dict[str, str]]]:
    victims: list[dict[str, object]] = []
    after_by_actor: dict[int, dict[str, str]] = {}
    for hostile in watched_hostiles:
        actor_address = int(hostile["actor_address"])
        watch_name = str(hostile["name"])
        after = query_scene_actor_by_address(actor_address)
        after_by_actor[actor_address] = after
        hp_before = csp.float_value({"hp": str(hostile.get("hp", ""))}, "hp")
        hp_after = csp.float_value(after, "hp")
        write_count = hostile_hp_write_count(result, watch_name)
        removed_after_write = after.get("available") != "true" and write_count > 0
        hp_decreased = (
            finite_float(hp_before)
            and (
                (finite_float(hp_after) and hp_after < hp_before)
                or removed_after_write
            )
        )
        if hp_decreased:
            victims.append(
                {
                    "actor_address": actor_address,
                    "watch_name": watch_name,
                    "target": actor_address == target_actor,
                    "hp_before": hp_before,
                    "hp_after": hp_after if finite_float(hp_after) else None,
                    "hp_write_count": write_count,
                    "removed_after_write": removed_after_write,
                    "enemy_type": hostile.get("enemy_type", ""),
                    "object_type_id": hostile.get("object_type_id", 0),
                }
            )
    return victims, after_by_actor


def refresh_watched_hostile_baselines(
    watched_hostiles: list[dict[str, object]],
) -> list[dict[str, object]]:
    baselines: list[dict[str, object]] = []
    for hostile in watched_hostiles:
        actor_address = int(hostile["actor_address"])
        current = query_scene_actor_by_address(actor_address)
        if current.get("available") != "true":
            continue
        hp = csp.float_value(current, "hp")
        max_hp = csp.float_value(current, "max_hp")
        if not finite_float(hp) or hp <= 0.0 or not finite_float(max_hp) or max_hp <= 0.0:
            continue
        refreshed = dict(hostile)
        for key in (
            "actor_address",
            "object_type_id",
            "tracked_enemy",
            "enemy_type",
            "dead",
            "hp",
            "max_hp",
            "x",
            "y",
            "actor_slot",
            "world_slot",
        ):
            if key in current:
                refreshed[key] = current[key]
        baselines.append(refreshed)
    return baselines


def effective_standoff(element: str, args: argparse.Namespace) -> float:
    if args.standoff is not None:
        return float(args.standoff)
    return ELEMENT_STANDOFFS.get(element, DEFAULT_STANDOFF)


def effective_cast_interval_seconds(element: str, args: argparse.Namespace) -> float:
    if args.cast_interval_seconds is not None:
        return float(args.cast_interval_seconds)
    return ELEMENT_CAST_INTERVAL_SECONDS.get(element, DEFAULT_CAST_INTERVAL_SECONDS)


def effective_positioning(element: str, args: argparse.Namespace) -> str:
    if args.positioning != "auto":
        return str(args.positioning)
    return ELEMENT_POSITIONING.get(element, "bot_only")


def effective_skip_hostile_hp_watches(element: str, args: argparse.Namespace) -> bool:
    return bool(args.skip_hostile_hp_watches or ELEMENT_SKIP_HOSTILE_HP_WATCHES.get(element, False))


def effective_controlled_target_position(
    element: str,
    positioning: str,
    args: argparse.Namespace,
    bot_x: float,
    bot_y: float,
) -> tuple[float | None, float | None]:
    target_x = args.target_x
    target_y = args.target_y
    if positioning == "force_both" and target_x is None and target_y is None:
        offset = ELEMENT_FORCE_TARGET_OFFSETS.get(element)
        if offset is not None:
            target_x = bot_x + offset[0]
            target_y = bot_y + offset[1]
    return target_x, target_y


def run_element_probe(element: str, args: argparse.Namespace) -> dict[str, object]:
    result: dict[str, object] = {
        "element": element,
        "element_config": ELEMENTS[element],
        "ok": False,
        "navigation": {},
        "casts": [],
    }
    armed_traces: list[tuple[str, int]] = []
    hostile_hp_watch_names: list[str] = []
    damage_context_watch_names: list[str] = []
    watched_hostiles: list[dict[str, object]] = []
    damage_baseline_hostiles: list[dict[str, object]] = []
    standoff = effective_standoff(element, args)
    cast_interval_seconds = effective_cast_interval_seconds(element, args)
    positioning = effective_positioning(element, args)
    skip_hostile_hp_watches = effective_skip_hostile_hp_watches(element, args)
    result["standoff"] = standoff
    result["cast_interval_seconds"] = cast_interval_seconds
    result["validation_profile"] = {
        "positioning": positioning,
        "skip_hostile_hp_watches": skip_hostile_hp_watches,
        "enemy_watch_count": args.enemy_watch_count,
    }
    try:
        if (
            args.trace_builder_window
            and not args.allow_unstable_inline_traces
            and not trace_profile_is_stable(args.trace_profile)
        ):
            raise ElementDamageProbeFailure(
                f"trace profile {args.trace_profile!r} contains unstable inline trace points; "
                "use --trace-profile safe_entry or pass --allow-unstable-inline-traces explicitly"
        )
        result["navigation"] = prepare_clean_run(args.player_element, args.discipline)
        player = csp.query_player_state()
        planned_bot_x = float(args.bot_x)
        planned_bot_y = float(args.bot_y)
        planned_target_x, planned_target_y = effective_controlled_target_position(
            element,
            positioning,
            args,
            planned_bot_x,
            planned_bot_y,
        )
        result["controlled_bot_position"] = {"x": planned_bot_x, "y": planned_bot_y}
        result["controlled_target_position"] = {"x": planned_target_x, "y": planned_target_y}
        bot_id = create_single_run_bot(element, player, planned_bot_x, planned_bot_y)
        bot = wait_for_bot_by_id(bot_id)
        crc.stop_bot(str(bot_id))
        bot_actor = csp.int_value(bot, "actor_address")
        wave.sustain_probe_health()
        if args.setup_mode == "manual_prelude":
            spawn = spawn_hostile_near_position(planned_bot_x, planned_bot_y, standoff)
            if spawn.get("ok") != "true":
                raise ElementDamageProbeFailure(f"sd.world.spawn_enemy failed for {element}: {spawn}")
            combat = crc.enable_combat_prelude()
            combat_state = crc.wait_for_combat_prelude_ready()
            spawn_result = wait_for_spawn_result(csp.int_value(spawn, "request_id"))
            hostile_actor = csp.int_value(spawn_result, "actor_address")
            if hostile_actor == 0:
                raise ElementDamageProbeFailure(f"sd.world.spawn_enemy returned no actor for {element}: {spawn_result}")
            result["navigation"]["spawn"] = spawn
            result["navigation"]["spawn_result"] = spawn_result
            result["navigation"]["combat_prelude"] = combat
            result["navigation"]["combat_state"] = combat_state
        else:
            waves = csp.parse_key_values(csp.run_lua("print('ok='..tostring(sd.gameplay.start_waves()))"))
            if waves.get("ok") != "true":
                raise ElementDamageProbeFailure(f"sd.gameplay.start_waves failed for {element}: {waves}")
            result["navigation"]["waves"] = waves
        time.sleep(POST_COMBAT_PRELUDE_SETTLE_SECONDS)
        wave.sustain_probe_health()
        if args.setup_mode == "manual_prelude":
            hostile = query_scene_actor_by_address(hostile_actor)
            if hostile.get("available") != "true":
                hostile = csp.wait_for_nearest_enemy(timeout_s=15.0, max_gap=5000.0)
                hostile_actor = csp.int_value(hostile, "actor_address")
        else:
            hostile = csp.wait_for_nearest_enemy(timeout_s=30.0, max_gap=5000.0)
            hostile_actor = csp.int_value(hostile, "actor_address")
        range_setup = establish_probe_range(
            bot_actor,
            hostile_actor,
            standoff,
            positioning,
            bot_x=planned_bot_x,
            bot_y=planned_bot_y,
            target_x=planned_target_x,
            target_y=planned_target_y,
        )
        if not probe_range_setup_succeeded(range_setup, args.max_hostile_gap):
            raise ElementDamageProbeFailure(f"Unable to establish bot/hostile range for {element}: {range_setup}")
        forced_vitals = force_target_vitals_for_baseline(
            result, hostile_actor, args.hp, "initial_range_setup"
        )
        range_setup = establish_probe_range(
            bot_actor,
            hostile_actor,
            standoff,
            positioning,
            bot_x=planned_bot_x,
            bot_y=planned_bot_y,
            target_x=planned_target_x,
            target_y=planned_target_y,
        )
        forced_vitals = force_target_vitals_for_baseline(
            result, hostile_actor, args.hp, "confirmed_range_setup"
        )
        before = query_scene_actor_by_address(hostile_actor)
        if before.get("available") != "true":
            raise ElementDamageProbeFailure(
                f"Controlled hostile disappeared before {element} cast was queued: {before}"
            )
        watched_hostiles, hostile_hp_watch_names, hostile_actor, before = acquire_live_watched_hostile(
            element=element,
            bot_actor_address=bot_actor,
            limit=args.enemy_watch_count,
            skip_watches=skip_hostile_hp_watches,
            old_watch_names=hostile_hp_watch_names,
            result=result,
            reason="pre_cast",
            preferred_actor_address=hostile_actor,
            baseline_hp=args.hp,
        )
        hostile = before
        range_setup = establish_probe_range(
            bot_actor,
            hostile_actor,
            standoff,
            positioning,
            bot_x=planned_bot_x,
            bot_y=planned_bot_y,
            target_x=planned_target_x,
            target_y=planned_target_y,
        )
        before = query_scene_actor_by_address(hostile_actor)
        if before.get("available") != "true":
            watched_hostiles, hostile_hp_watch_names, hostile_actor, before = acquire_live_watched_hostile(
                element=element,
                bot_actor_address=bot_actor,
                limit=args.enemy_watch_count,
                skip_watches=skip_hostile_hp_watches,
                old_watch_names=hostile_hp_watch_names,
                result=result,
                reason="post_range_setup",
                baseline_hp=args.hp,
            )
            range_setup = establish_probe_range(
                bot_actor,
                hostile_actor,
                standoff,
                positioning,
                bot_x=planned_bot_x,
                bot_y=planned_bot_y,
                target_x=planned_target_x,
                target_y=planned_target_y,
            )
            before = query_scene_actor_by_address(hostile_actor)
            if before.get("available") != "true":
                raise ElementDamageProbeFailure(
                    f"No watched hostile stayed live after final {element} range setup: {before}"
                )
        if args.watch_target_hp:
            result["target_hp_watch"] = {
                "deprecated": True,
                "message": "All watched hostile HP fields are already covered by hostile_hp_watches.",
            }
        if args.watch_damage_context:
            result["damage_context_watches"] = arm_damage_context_watches(element)
            damage_context_watch_names = list(result["damage_context_watches"].keys())
        if args.trace_builder_window:
            trace_results, builder_traces = arm_builder_traces(element, args.trace_profile)
            result["builder_trace_arm"] = trace_results
            armed_traces.extend(builder_traces)
        if args.trace_air_handler and element == "air":
            trace_name = "air_lightning_handler"
            result["air_handler_trace_arm"] = arm_trace(trace_name, AIR_LIGHTNING_HANDLER_ADDRESS)
            if result["air_handler_trace_arm"].get("ok") == "true":
                armed_traces.append((trace_name, AIR_LIGHTNING_HANDLER_ADDRESS))
        if args.trace_native_hit_path:
            trace_results, native_hit_traces = arm_native_hit_path_traces(element)
            result["native_hit_path_trace_arm"] = trace_results
            armed_traces.extend(native_hit_traces)

        before_for_validation: dict[str, object] = dict(before)
        for cast_index in range(max(args.casts, 1)):
            if cast_index > 0:
                watched_hostiles, hostile_hp_watch_names, hostile_actor, hostile_now = acquire_live_watched_hostile(
                    element=element,
                    bot_actor_address=bot_actor,
                    limit=args.enemy_watch_count,
                    skip_watches=skip_hostile_hp_watches,
                    old_watch_names=hostile_hp_watch_names,
                    result=result,
                    reason=f"cast_{cast_index + 1}_baseline_reset",
                    preferred_actor_address=hostile_actor,
                    baseline_hp=args.hp,
                )
                before = hostile_now
            hostile_now = query_scene_actor_by_address(hostile_actor)
            if hostile_now.get("available") != "true":
                watched_hostiles, hostile_hp_watch_names, hostile_actor, hostile_now = acquire_live_watched_hostile(
                    element=element,
                    bot_actor_address=bot_actor,
                    limit=args.enemy_watch_count,
                    skip_watches=skip_hostile_hp_watches,
                    old_watch_names=hostile_hp_watch_names,
                    result=result,
                    reason=f"cast_{cast_index + 1}_pre_pin",
                    baseline_hp=args.hp,
                )
                if cast_index == 0:
                    before = hostile_now
            pinned = establish_probe_range(
                bot_actor,
                hostile_actor,
                standoff,
                positioning,
                bot_x=planned_bot_x,
                bot_y=planned_bot_y,
                target_x=planned_target_x,
                target_y=planned_target_y,
            )
            hostile_now = query_scene_actor_by_address(hostile_actor)
            if hostile_now.get("available") != "true":
                watched_hostiles, hostile_hp_watch_names, hostile_actor, hostile_now = acquire_live_watched_hostile(
                    element=element,
                    bot_actor_address=bot_actor,
                    limit=args.enemy_watch_count,
                    skip_watches=skip_hostile_hp_watches,
                    old_watch_names=hostile_hp_watch_names,
                    result=result,
                    reason=f"cast_{cast_index + 1}_post_pin",
                    baseline_hp=args.hp,
                )
                pinned = establish_probe_range(
                    bot_actor,
                    hostile_actor,
                    standoff,
                    positioning,
                    bot_x=planned_bot_x,
                    bot_y=planned_bot_y,
                    target_x=planned_target_x,
                    target_y=planned_target_y,
                )
                hostile_now = query_scene_actor_by_address(hostile_actor)
                if hostile_now.get("available") != "true":
                    raise ElementDamageProbeFailure(
                        f"Controlled hostile disappeared before {element} cast {cast_index + 1}: {hostile_now}"
                    )
                if cast_index == 0:
                    before = hostile_now

            hostile_now = query_scene_actor_by_address(hostile_actor)
            if hostile_now.get("available") != "true":
                raise ElementDamageProbeFailure(
                    f"Controlled hostile disappeared after {element} vitals reset {cast_index + 1}: {hostile_now}"
                )
            current_baselines = refresh_watched_hostile_baselines(watched_hostiles)
            target_baseline = next(
                (
                    hostile
                    for hostile in current_baselines
                    if int(hostile.get("actor_address", 0)) == hostile_actor
                ),
                None,
            )
            if target_baseline is None:
                watched_hostiles, hostile_hp_watch_names, hostile_actor, hostile_now = acquire_live_watched_hostile(
                    element=element,
                    bot_actor_address=bot_actor,
                    limit=args.enemy_watch_count,
                    skip_watches=skip_hostile_hp_watches,
                    old_watch_names=hostile_hp_watch_names,
                    result=result,
                    reason=f"cast_{cast_index + 1}_baseline_refresh",
                    baseline_hp=args.hp,
                )
                pinned = establish_probe_range(
                    bot_actor,
                    hostile_actor,
                    standoff,
                    positioning,
                    bot_x=planned_bot_x,
                    bot_y=planned_bot_y,
                    target_x=planned_target_x,
                    target_y=planned_target_y,
                )
                hostile_now = query_scene_actor_by_address(hostile_actor)
                if hostile_now.get("available") != "true":
                    raise ElementDamageProbeFailure(
                        f"Controlled hostile disappeared before clean {element} cast baseline {cast_index + 1}: {hostile_now}"
                    )
                current_baselines = refresh_watched_hostile_baselines(watched_hostiles)
                target_baseline = next(
                    (
                        hostile
                        for hostile in current_baselines
                        if int(hostile.get("actor_address", 0)) == hostile_actor
                    ),
                    None,
                )
            if target_baseline is None:
                raise ElementDamageProbeFailure(
                    f"Unable to capture clean {element} pre-cast baseline for target {hostile_actor:x}"
                )

            if cast_index == 0 and args.bot_starting_mp is not None:
                forced_bot_mana = force_bot_progression_mp(bot_id, args.bot_starting_mp)
                result["forced_bot_mana"] = forced_bot_mana
                if forced_bot_mana.get("ok") != "true" or forced_bot_mana.get("write_ok") != "true":
                    raise ElementDamageProbeFailure(
                        f"Unable to force bot MP before {element} cast: {forced_bot_mana}"
                    )
                bot = query_bot_by_id(bot_id)

            current_by_actor = {
                int(hostile.get("actor_address", 0)): hostile
                for hostile in current_baselines
            }
            damage_baseline_hostiles = [
                dict(current_by_actor.get(int(hostile.get("actor_address", 0))) or hostile)
                for hostile in watched_hostiles
            ]
            before_for_validation = dict(target_baseline)
            baselines = result.setdefault("pre_cast_hostile_baselines", [])
            if isinstance(baselines, list):
                baselines.append(
                    {
                        "cast_index": cast_index + 1,
                        "target_actor_address": hostile_actor,
                        "hostiles": damage_baseline_hostiles,
                    }
                )
            clear_write_hits(hostile_hp_watch_names)
            clear_write_hits(damage_context_watch_names)

            cast = crc.queue_direct_primary_cast(
                str(bot_id),
                str(hostile_actor),
                csp.float_value(pinned, "target_x"),
                csp.float_value(pinned, "target_y"),
            )
            cast["index"] = str(cast_index + 1)
            cast["hp_before_cast"] = str(target_baseline.get("hp", ""))
            cast["pin"] = pinned
            result["casts"].append(cast)
            cast_window = max(cast_interval_seconds, 0.1)
            cast["pin_samples"] = pin_probe_range_during_window(
                bot_actor,
                hostile_actor,
                standoff,
                cast_window,
                positioning,
                bot_x=planned_bot_x,
                bot_y=planned_bot_y,
                target_x=planned_target_x,
                target_y=planned_target_y,
            )

        result["post_cast_pin_samples"] = pin_probe_range_during_window(
            bot_actor,
            hostile_actor,
            standoff,
            max(args.settle_seconds, 0.0),
            positioning,
            bot_x=planned_bot_x,
            bot_y=planned_bot_y,
            target_x=planned_target_x,
            target_y=planned_target_y,
        )
        if args.trace_air_handler and element == "air":
            result["air_handler_trace_hits"] = query_trace_hits("air_lightning_handler")
        if args.trace_builder_window:
            result["builder_trace_hits"] = {
                spec.name: query_trace_hits(spec.name)
                for spec in build_trace_specs(f"bot_{element}_primary", args.trace_profile)
            }
        if args.trace_native_hit_path:
            native_hit_trace_specs = native_hit_path_traces_for_element(element)
            result["native_hit_path_trace_hits"] = {
                f"bot_{element}_{key}": query_trace_hits(f"bot_{element}_{key}")
                for key in native_hit_trace_specs
            }
        result["hostile_hp_write_hits"] = {
            name: query_write_hits(name)
            for name in hostile_hp_watch_names
        }
        result["damage_context_write_hits"] = {
            name: query_write_hits(name)
            for name in damage_context_watch_names
        }
        after = query_scene_actor_by_address(hostile_actor)
        hp_before = csp.float_value({key: str(value) for key, value in before_for_validation.items()}, "hp")
        hp_after = csp.float_value(after, "hp")
        victims, after_by_actor = summarize_hostile_damage(result, damage_baseline_hostiles, hostile_actor)
        target_watch_name = next(
            (
                str(hostile.get("name"))
                for hostile in damage_baseline_hostiles
                if int(hostile.get("actor_address", 0)) == hostile_actor
            ),
            "",
        )
        hp_write_count = hostile_hp_write_count(result, target_watch_name) if target_watch_name else 0
        target_removed_after_damage = (
            before_for_validation.get("available") == "true"
            and after.get("available") != "true"
            and hp_write_count > 0
        )
        hp_decreased = (
            finite_float(hp_before)
            and (
                (finite_float(hp_after) and hp_after < hp_before)
                or target_removed_after_damage
            )
        )
        any_cast_queued = any(cast.get("ok") == "true" for cast in result["casts"])
        full_loader_log_tail = read_loader_log_lines()
        statbook_validation = build_statbook_validation(
            element,
            bot,
            bot_id,
            full_loader_log_tail,
        )
        native_spawn_validation = statbook_validation.get("native_projectile_spawn_validation")
        native_release = (
            native_spawn_validation.get("matching_release")
            if isinstance(native_spawn_validation, dict)
            else None
        )
        before_was_available = before_for_validation.get("available", "true") == "true"
        native_release_removed_target = (
            isinstance(native_release, dict)
            and before_was_available
            and after.get("available") != "true"
            and int(native_release.get("target_actor", 0)) == hostile_actor
            and str(native_release.get("release_reason", "")) in {"max_size", "damage_threshold"}
        )
        if native_release_removed_target and not any(victim.get("target") is True for victim in victims):
            victims.append(
                {
                    "actor_address": hostile_actor,
                    "watch_name": target_watch_name,
                    "target": True,
                    "hp_before": hp_before,
                    "hp_after": None,
                    "hp_write_count": hp_write_count,
                    "removed_after_write": False,
                    "removed_after_native_release": True,
                    "enemy_type": before_for_validation.get("enemy_type", ""),
                    "object_type_id": before_for_validation.get("object_type_id", 0),
                }
            )
        target_removed_after_damage = target_removed_after_damage or native_release_removed_target
        hp_decreased = hp_decreased or native_release_removed_target
        mana_rejected_logged = int(statbook_validation.get("mana_rejected_log_count", 0)) > 0
        mana_rejection_validation = {
            "expected": bool(args.expect_mana_rejected),
            "mana_rejected_logged": mana_rejected_logged,
            "any_cast_queued": any_cast_queued,
            "any_hostile_damaged": bool(victims),
            "hp_decreased": hp_decreased,
            "ok": bool(
                args.expect_mana_rejected
                and mana_rejected_logged
                and not any_cast_queued
                and not victims
                and not hp_decreased
            ),
        }
        result.update(
            {
                "player": player,
                "bot": bot,
                "hostile": hostile,
                "range_setup": range_setup,
                "forced_vitals": forced_vitals,
                "before": before_for_validation,
                "after": after,
                "validation": {
                    "hp_before": hp_before,
                    "hp_after": hp_after,
                    "hp_decreased": hp_decreased,
                    "hp_write_count": hp_write_count,
                    "target_removed_after_damage": target_removed_after_damage,
                    "any_cast_queued": any_cast_queued,
                    "target_watch_name": target_watch_name,
                    "actual_victims": victims,
                    "any_hostile_damaged": bool(victims),
                    "target_damaged": any(victim.get("target") is True for victim in victims),
                    "after_by_actor": after_by_actor,
                },
                "statbook_validation": statbook_validation,
                "mana_rejection_validation": mana_rejection_validation,
            }
        )
        if args.expect_mana_rejected:
            result["ok"] = mana_rejection_validation["ok"]
        else:
            result["ok"] = bool(victims and any_cast_queued and statbook_validation.get("ok") is True)
    except (csp.ProbeFailure, crc.CloseRangeProbeFailure, ElementDamageProbeFailure) as exc:
        result["error"] = str(exc)
    finally:
        for trace_name, trace_address in armed_traces:
            try:
                clear_trace(trace_name, trace_address)
            except Exception:
                pass
        if hostile_hp_watch_names:
            try:
                clear_hostile_hp_watches(hostile_hp_watch_names)
            except Exception:
                pass
        if damage_context_watch_names:
            try:
                clear_damage_context_watches(damage_context_watch_names)
            except Exception:
                pass
        result["loader_log_tail"] = csp.tail_loader_log(400)
        result["loader_log_filtered"] = crc.filter_loader_log(result["loader_log_tail"])
        if not args.keep_running:
            csp.stop_game()
    return result


def main() -> int:
    args = build_parser().parse_args()
    elements = args.element or list(ELEMENTS.keys())
    result: dict[str, object] = {
        "launcher_freshness": csp.ensure_launcher_bundle_fresh(),
        "elements": elements,
        "results": [],
    }
    for element in elements:
        result["results"].append(run_element_probe(element, args))
    result["ok"] = all(item.get("ok") is True for item in result["results"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
