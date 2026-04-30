#!/usr/bin/env python3
"""Stress bot-native skill rolls and applies against live progression state."""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from pathlib import Path

import cast_state_probe as csp


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = ROOT / "runtime" / "probe_bot_skill_choice_stress.json"
SKILL_CONFIG_DIR = ROOT / "runtime" / "stage" / "data" / "wizardskills"
PROGRESSION_TABLE_BASE_OFFSET = 0x20
PROGRESSION_TABLE_COUNT_OFFSET = 0x24
PROGRESSION_ENTRY_STRIDE = 0x70
PROGRESSION_LEVEL_OFFSET = 0x30
PROGRESSION_XP_OFFSET = 0x34
PROGRESSION_PREVIOUS_XP_THRESHOLD_OFFSET = 0x38
PROGRESSION_NEXT_XP_THRESHOLD_OFFSET = 0x3C
PROGRESSION_HP_OFFSET = 0x70
PROGRESSION_MAX_HP_OFFSET = 0x74
PROGRESSION_MP_OFFSET = 0x7C
PROGRESSION_MAX_MP_OFFSET = 0x80
PROGRESSION_MOVE_SPEED_OFFSET = 0x90
PROGRESSION_ENTRY_INTERNAL_ID_OFFSET = 0x1C
PROGRESSION_ENTRY_ACTIVE_OFFSET = 0x20
PROGRESSION_ENTRY_VISIBLE_OFFSET = 0x22
PROGRESSION_ENTRY_CATEGORY_OFFSET = 0x26
PROGRESSION_ENTRY_STATBOOK_OFFSET = 0x6C
STATBOOK_NAME_STRING_OFFSET = 0x1C
STATBOOK_MAX_LEVEL_OFFSET = 0x5C
BONUS_CHOICE_COUNT_SKILL_ID = 0x3F


class SkillChoiceStressFailure(RuntimeError):
    pass


def display_name_from_stem(stem: str) -> str:
    special = {
        "health_up": "HEALTH UP",
        "mana_up": "MANA UP",
    }
    if stem in special:
        return special[stem]
    return " ".join(part.capitalize() for part in stem.split("_"))


def read_lua_style_string(text: str, key: str) -> str:
    match = re.search(rf"{re.escape(key)}\s*=\s*\"([^\"]*)\"", text)
    return match.group(1) if match else ""


def load_skill_metadata_catalog() -> dict[str, dict[str, str]]:
    catalog: dict[str, dict[str, str]] = {}
    if not SKILL_CONFIG_DIR.exists():
        return catalog
    for path in sorted(SKILL_CONFIG_DIR.glob("*.cfg")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        metadata = {
            "skill_name": display_name_from_stem(path.stem),
            "skill_file": path.name,
            "quick_description": read_lua_style_string(text, "mQDescription"),
            "description": read_lua_style_string(text, "mDescription"),
        }
        for key in ("quick_description", "description"):
            value = metadata[key].strip().lower()
            if value:
                catalog[value] = metadata
    return catalog


SKILL_METADATA_CATALOG = load_skill_metadata_catalog()


def resolve_skill_metadata(native_text: object, option_id: int) -> dict[str, str]:
    text = str(native_text or "").strip()
    metadata = SKILL_METADATA_CATALOG.get(text.lower())
    if metadata is not None:
        return dict(metadata)
    return {
        "skill_name": text or f"skill_{option_id}",
        "skill_file": "",
        "quick_description": text,
        "description": "",
    }


def lua_values(code: str, *, timeout_s: float = 20.0) -> dict[str, str]:
    return csp.parse_key_values(csp.run_lua(code.strip(), timeout_s=timeout_s))


def lua_bool(value: str | None) -> bool:
    return value == "true" or value == "1"


def int_value(values: dict[str, str], key: str, default: int = 0) -> int:
    text = values.get(key)
    if text is None or text == "" or text == "nil":
        return default
    try:
        return int(text, 0)
    except ValueError:
        return int(float(text))


def float_value(values: dict[str, str], key: str, default: float = 0.0) -> float:
    text = values.get(key)
    if text is None or text == "" or text == "nil":
        return default
    return float(text)


def parse_hex_bytes(text: str | None) -> list[int]:
    if not text:
        return []
    bytes_out: list[int] = []
    for token in text.split():
        try:
            bytes_out.append(int(token, 16))
        except ValueError:
            continue
    return bytes_out


def diff_hex_bytes(before: str | None, after: str | None) -> list[dict[str, int]]:
    before_bytes = parse_hex_bytes(before)
    after_bytes = parse_hex_bytes(after)
    length = max(len(before_bytes), len(after_bytes))
    diffs: list[dict[str, int]] = []
    for offset in range(length):
        before_value = before_bytes[offset] if offset < len(before_bytes) else -1
        after_value = after_bytes[offset] if offset < len(after_bytes) else -1
        if before_value != after_value:
            diffs.append({
                "offset": offset,
                "before": before_value,
                "after": after_value,
            })
    return diffs


def diff_dict(before: dict[str, object], after: dict[str, object]) -> dict[str, dict[str, object]]:
    ignored_keys = {"available"}
    diffs: dict[str, dict[str, object]] = {}
    for key in sorted((set(before) | set(after)) - ignored_keys):
        before_value = before.get(key)
        after_value = after.get(key)
        if before_value != after_value:
            diffs[key] = {
                "before": before_value,
                "after": after_value,
            }
    return diffs


def set_lua_bot_tick_enabled(enabled: bool) -> dict[str, str]:
    return lua_values(
        f"""
lua_bots_disable_tick = {"false" if enabled else "true"}
print('ok=true')
print('lua_bots_disable_tick=' .. tostring(lua_bots_disable_tick))
""")


def query_bot_summary() -> dict[str, str]:
    return lua_values(
        """
local function emit(k, v) print(k .. '=' .. tostring(v)) end
local player = sd.player.get_state()
local bots = sd.bots.get_state()
emit('player.progression', player and player.progression_address or 0)
emit('player.level', player and player.level or 0)
emit('player.xp', player and player.xp or 0)
emit('bot.count', type(bots) == 'table' and #bots or 0)
if type(bots) == 'table' then
  for i, bot in ipairs(bots) do
    local profile = bot.profile or {}
    local loadout = profile.loadout or {}
    emit('bot.' .. i .. '.id', bot.id)
    emit('bot.' .. i .. '.name', bot.name)
    emit('bot.' .. i .. '.element_id', profile.element_id)
    emit('bot.' .. i .. '.discipline_id', profile.discipline_id)
    emit('bot.' .. i .. '.primary_entry_index', loadout.primary_entry_index)
    emit('bot.' .. i .. '.level', profile.level)
    emit('bot.' .. i .. '.xp', profile.experience)
    emit('bot.' .. i .. '.progression', bot.progression_runtime_state_address)
  end
end
""")


def query_bot_profile(bot_id: int) -> dict[str, int | bool]:
    values = lua_values(
        f"""
local function emit(k, v) print(k .. '=' .. tostring(v)) end
local bot = sd.bots.get_state({bot_id})
if type(bot) ~= 'table' then
  emit('available', false)
  return
end
local profile = bot.profile or {{}}
local loadout = profile.loadout or {{}}
emit('available', true)
emit('id', bot.id)
emit('level', profile.level)
emit('xp', profile.experience)
emit('progression', bot.progression_runtime_state_address)
emit('primary_entry_index', loadout.primary_entry_index)
emit('primary_combo_entry_index', loadout.primary_combo_entry_index)
local secondaries = loadout.secondary_entry_indices or {{}}
emit('secondary_entry_index_1', secondaries[1] or -1)
emit('secondary_entry_index_2', secondaries[2] or -1)
emit('secondary_entry_index_3', secondaries[3] or -1)
"""
    )
    return {
        "available": lua_bool(values.get("available")),
        "id": int_value(values, "id", bot_id),
        "level": int_value(values, "level"),
        "xp": int_value(values, "xp"),
        "progression": int_value(values, "progression"),
        "primary_entry_index": int_value(values, "primary_entry_index", -1),
        "primary_combo_entry_index": int_value(values, "primary_combo_entry_index", -1),
        "secondary_entry_indices": [
            int_value(values, "secondary_entry_index_1", -1),
            int_value(values, "secondary_entry_index_2", -1),
            int_value(values, "secondary_entry_index_3", -1),
        ],
    }


def query_bot_loadout(bot_id: int) -> dict[str, object]:
    profile = query_bot_profile(bot_id)
    return {
        "available": profile["available"],
        "primary_entry_index": profile["primary_entry_index"],
        "primary_combo_entry_index": profile["primary_combo_entry_index"],
        "secondary_entry_indices": profile["secondary_entry_indices"],
    }


def query_progression_stats(bot_id: int) -> dict[str, object]:
    values = lua_values(
        f"""
local function emit(k, v) print(k .. '=' .. tostring(v)) end
local bot = sd.bots.get_state({bot_id})
if type(bot) ~= 'table' then
  emit('available', false)
  return
end
local progression = tonumber(bot.progression_runtime_state_address) or 0
emit('available', progression ~= 0)
emit('progression', progression)
if progression ~= 0 then
  emit('level', sd.debug.read_i32(progression + {PROGRESSION_LEVEL_OFFSET}))
  emit('xp', sd.debug.read_float(progression + {PROGRESSION_XP_OFFSET}))
  emit('previous_xp_threshold', sd.debug.read_float(progression + {PROGRESSION_PREVIOUS_XP_THRESHOLD_OFFSET}))
  emit('next_xp_threshold', sd.debug.read_float(progression + {PROGRESSION_NEXT_XP_THRESHOLD_OFFSET}))
  emit('hp', sd.debug.read_float(progression + {PROGRESSION_HP_OFFSET}))
  emit('max_hp', sd.debug.read_float(progression + {PROGRESSION_MAX_HP_OFFSET}))
  emit('mp', sd.debug.read_float(progression + {PROGRESSION_MP_OFFSET}))
  emit('max_mp', sd.debug.read_float(progression + {PROGRESSION_MAX_MP_OFFSET}))
  emit('move_speed', sd.debug.read_float(progression + {PROGRESSION_MOVE_SPEED_OFFSET}))
end
"""
    )
    return {
        "available": lua_bool(values.get("available")),
        "progression": int_value(values, "progression"),
        "level": int_value(values, "level"),
        "xp": float_value(values, "xp"),
        "previous_xp_threshold": float_value(values, "previous_xp_threshold"),
        "next_xp_threshold": float_value(values, "next_xp_threshold"),
        "hp": float_value(values, "hp"),
        "max_hp": float_value(values, "max_hp"),
        "mp": float_value(values, "mp"),
        "max_mp": float_value(values, "max_mp"),
        "move_speed": float_value(values, "move_speed"),
    }


def wait_for_materialized_bots(timeout_s: float = 30.0) -> dict[str, str]:
    deadline = time.time() + timeout_s
    last: dict[str, str] = {}
    while time.time() < deadline:
        last = query_bot_summary()
        count = int_value(last, "bot.count")
        materialized = 0
        for index in range(1, count + 1):
            if int_value(last, f"bot.{index}.progression") != 0:
                materialized += 1
        if count > 0 and materialized == count:
            return last
        time.sleep(0.5)
    raise SkillChoiceStressFailure(f"timed out waiting for materialized bots: {last}")


def debug_sync_level_up(level: int, experience: int, source_progression: int) -> dict[str, str]:
    values = lua_values(
        f"""
local ok = sd.bots.debug_sync_level_up({{
  level = {level},
  experience = {experience},
  source_progression_address = {source_progression},
}})
print('ok=' .. tostring(ok))
""")
    if not lua_bool(values.get("ok")):
        raise SkillChoiceStressFailure(f"debug_sync_level_up failed: {values}")
    return values


def query_choices(bot_id: int) -> dict[str, object]:
    values = lua_values(
        f"""
local function emit(k, v) print(k .. '=' .. tostring(v)) end
local choices = sd.bots.get_skill_choices({bot_id})
if type(choices) ~= 'table' then
  emit('available', false)
  return
end
emit('available', true)
emit('pending', choices.pending)
emit('generation', choices.generation)
emit('level', choices.level)
emit('experience', choices.experience)
emit('count', type(choices.options) == 'table' and #choices.options or 0)
if type(choices.options) == 'table' then
  for i, option in ipairs(choices.options) do
    emit('option.' .. i .. '.id', option.id)
    emit('option.' .. i .. '.apply_count', option.apply_count)
  end
end
""")
    count = int_value(values, "count")
    options: list[dict[str, int]] = []
    for index in range(1, count + 1):
        options.append({
            "id": int_value(values, f"option.{index}.id", -1),
            "apply_count": int_value(values, f"option.{index}.apply_count", 1),
        })
    return {
        "available": lua_bool(values.get("available")),
        "pending": lua_bool(values.get("pending")),
        "generation": int_value(values, "generation"),
        "level": int_value(values, "level"),
        "experience": int_value(values, "experience"),
        "count": count,
        "options": options,
    }


def query_entry_state(bot_id: int, option_id: int) -> dict[str, object]:
    values = lua_values(
        f"""
local function emit(k, v) print(k .. '=' .. tostring(v)) end
local function clean_string(value)
  if type(value) ~= 'string' or value == '' then
    return ''
  end
  local nul = string.find(value, '\\0', 1, true)
  if nul ~= nil then
    value = string.sub(value, 1, nul - 1)
  end
  if value == '' or string.find(value, '[%z\\1-\\8\\11\\12\\14-\\31\\127]') ~= nil then
    return ''
  end
  return value
end
local function read_c_string(address, max_len)
  address = tonumber(address) or 0
  if address == 0 then
    return ''
  end
  local ok, value = pcall(sd.debug.read_string, address, max_len or 96)
  if not ok then
    return ''
  end
  return clean_string(value)
end
local function read_native_string_object(address)
  address = tonumber(address) or 0
  if address == 0 then
    return ''
  end
  local data = tonumber(sd.debug.read_u32(address + 4)) or 0
  local length = tonumber(sd.debug.read_i32(address + 0x10)) or 0
  if data == 0 or length <= 0 or length > 256 then
    return ''
  end
  return read_c_string(data, length + 1)
end
local function emit_name_candidates(prefix, statbook)
  statbook = tonumber(statbook) or 0
  emit(prefix .. '.name', '')
  if statbook == 0 then
    return
  end
  local string_object = statbook + {STATBOOK_NAME_STRING_OFFSET}
  local direct = read_c_string(string_object, 96)
  local object_string = read_native_string_object(string_object)
  local ptr = tonumber(sd.debug.read_u32(string_object)) or 0
  local pointed_object_string = read_native_string_object(ptr)
  local pointed_direct = read_c_string(ptr, 96)
  emit(prefix .. '.name_direct', direct)
  emit(prefix .. '.name_object', object_string)
  emit(prefix .. '.name_ptr_object', pointed_object_string)
  emit(prefix .. '.name_ptr_direct', pointed_direct)
  local name = object_string
  if name == '' then name = pointed_object_string end
  if name == '' then name = pointed_direct end
  if name == '' then name = direct end
  emit(prefix .. '.name', name)
end
local bot = sd.bots.get_state({bot_id})
if type(bot) ~= 'table' then
  emit('available', false)
  return
end
local progression = tonumber(bot.progression_runtime_state_address) or 0
local table_addr = progression ~= 0 and sd.debug.read_u32(progression + {PROGRESSION_TABLE_BASE_OFFSET}) or 0
local table_count = progression ~= 0 and sd.debug.read_i32(progression + {PROGRESSION_TABLE_COUNT_OFFSET}) or 0
local option_id = {option_id}
emit('available', progression ~= 0 and table_addr ~= 0 and table_count > option_id)
emit('progression', progression)
emit('table', table_addr)
emit('table_count', table_count)
emit('option_id', option_id)
if progression ~= 0 and table_addr ~= 0 and table_count > option_id then
  local entry = table_addr + (option_id * {PROGRESSION_ENTRY_STRIDE})
  local statbook = sd.debug.read_u32(entry + {PROGRESSION_ENTRY_STATBOOK_OFFSET}) or 0
  emit('entry', entry)
  emit('internal_id', sd.debug.read_i32(entry + {PROGRESSION_ENTRY_INTERNAL_ID_OFFSET}))
  emit('active', sd.debug.read_u16(entry + {PROGRESSION_ENTRY_ACTIVE_OFFSET}))
  emit('visible', sd.debug.read_u16(entry + {PROGRESSION_ENTRY_VISIBLE_OFFSET}))
  emit('category', sd.debug.read_u16(entry + {PROGRESSION_ENTRY_CATEGORY_OFFSET}))
  emit('statbook', statbook)
  if statbook ~= 0 then
    emit('statbook.max_level', sd.debug.read_i32(statbook + {STATBOOK_MAX_LEVEL_OFFSET}))
  end
  emit_name_candidates('statbook', statbook)
  emit('bytes', sd.debug.read_bytes(entry, {PROGRESSION_ENTRY_STRIDE}))
end
""")
    return {
        "available": lua_bool(values.get("available")),
        "progression": int_value(values, "progression"),
        "table": int_value(values, "table"),
        "table_count": int_value(values, "table_count"),
        "option_id": int_value(values, "option_id", option_id),
        "entry": int_value(values, "entry"),
        "internal_id": int_value(values, "internal_id", -1),
        "active": int_value(values, "active"),
        "visible": int_value(values, "visible"),
        "category": int_value(values, "category"),
        "statbook": int_value(values, "statbook"),
        "statbook_max_level": int_value(values, "statbook.max_level", -1),
        "name": values.get("statbook.name", ""),
        "name_candidates": {
            "object": values.get("statbook.name_object", ""),
            "ptr_object": values.get("statbook.name_ptr_object", ""),
            "ptr_direct": values.get("statbook.name_ptr_direct", ""),
            "direct": values.get("statbook.name_direct", ""),
        },
        "bytes": values.get("bytes", ""),
    }


def enrich_choice_options(bot_id: int, choices: dict[str, object]) -> list[dict[str, object]]:
    enriched: list[dict[str, object]] = []
    for option in choices.get("options", []):
        if not isinstance(option, dict):
            continue
        option_id = int(option.get("id", -1))
        entry = query_entry_state(bot_id, option_id)
        metadata = resolve_skill_metadata(entry.get("name"), option_id)
        enriched.append({
            "id": option_id,
            "name": metadata["skill_name"],
            "native_text": entry.get("name") or "",
            "skill_file": metadata["skill_file"],
            "quick_description": metadata["quick_description"],
            "description": metadata["description"],
            "apply_count": option.get("apply_count", 1),
            "entry": {
                "available": entry.get("available"),
                "entry": entry.get("entry"),
                "internal_id": entry.get("internal_id"),
                "active": entry.get("active"),
                "visible": entry.get("visible"),
                "category": entry.get("category"),
                "statbook": entry.get("statbook"),
                "statbook_max_level": entry.get("statbook_max_level"),
                "name_candidates": entry.get("name_candidates"),
            },
        })
    return enriched


def write_entry_flags(bot_id: int, option_id: int, active: int | None, visible: int | None) -> dict[str, str]:
    active_line = "emit('active_write', true)"
    visible_line = "emit('visible_write', true)"
    if active is not None:
        active_line = f"emit('active_write', sd.debug.write_u16(entry + {PROGRESSION_ENTRY_ACTIVE_OFFSET}, {active}))"
    if visible is not None:
        visible_line = f"emit('visible_write', sd.debug.write_u16(entry + {PROGRESSION_ENTRY_VISIBLE_OFFSET}, {visible}))"
    return lua_values(
        f"""
local function emit(k, v) print(k .. '=' .. tostring(v)) end
local bot = sd.bots.get_state({bot_id})
local progression = type(bot) == 'table' and tonumber(bot.progression_runtime_state_address) or 0
local table_addr = progression ~= 0 and sd.debug.read_u32(progression + {PROGRESSION_TABLE_BASE_OFFSET}) or 0
local option_id = {option_id}
local entry = table_addr + (option_id * {PROGRESSION_ENTRY_STRIDE})
emit('available', progression ~= 0 and table_addr ~= 0)
if progression ~= 0 and table_addr ~= 0 then
  {active_line}
  {visible_line}
end
""")


def choose_skill(bot_id: int, option_index: int, generation: int) -> dict[str, str]:
    values = lua_values(
        f"""
local function emit(k, v) print(k .. '=' .. tostring(v)) end
local ok, result = pcall(sd.bots.choose_skill, {bot_id}, {option_index}, {generation})
emit('pcall_ok', ok)
emit('result', result)
emit('ok', ok and result == true)
""")
    if not lua_bool(values.get("ok")):
        raise SkillChoiceStressFailure(
            f"choose_skill failed bot={bot_id} index={option_index} generation={generation}: {values}"
        )
    return values


def run_bonus_choice_count_probe(bot_id: int, level: int, experience: int, source_progression: int) -> dict[str, object]:
    before = query_entry_state(bot_id, BONUS_CHOICE_COUNT_SKILL_ID)
    if not before["available"]:
        raise SkillChoiceStressFailure(f"bonus choice-count entry is unavailable: {before}")

    write_entry_flags(
        bot_id,
        BONUS_CHOICE_COUNT_SKILL_ID,
        1,
        1,
    )
    debug_sync_level_up(level, experience, source_progression)
    choices = query_choices(bot_id)
    write_entry_flags(
        bot_id,
        BONUS_CHOICE_COUNT_SKILL_ID,
        int(before["active"]),
        int(before["visible"]),
    )

    if choices["count"] < 4:
        raise SkillChoiceStressFailure(
            f"bonus choice-count probe expected at least 4 choices after entry 0x3F became visible: {choices}"
        )
    choices["options_enriched"] = enrich_choice_options(bot_id, choices)
    return {
        "before": before,
        "choices": choices,
        "restored": query_entry_state(bot_id, BONUS_CHOICE_COUNT_SKILL_ID),
    }


def run_stress(iterations: int, seed: int) -> dict[str, object]:
    rng = random.Random(seed)
    result: dict[str, object] = {
        "iterations_requested": iterations,
        "seed": seed,
        "bot_summary_before": None,
        "bonus_choice_count_probe": None,
        "iterations": [],
        "pool_signatures": {},
        "unique_pool_counts": {},
    }

    csp.stop_game()
    csp.clear_loader_log()
    result["fresh_bundle"] = csp.ensure_launcher_bundle_fresh()
    csp.launch_game()
    pid = csp.wait_for_game_process()
    result["pid"] = pid
    csp.wait_for_lua_pipe(timeout_s=60.0)
    csp.drive_new_game_flow(pid, element="ether", discipline="mind")
    values = lua_values("print('ok='..tostring(sd.hub.start_testrun()))")
    if not lua_bool(values.get("ok")):
        raise SkillChoiceStressFailure(f"sd.hub.start_testrun failed: {values}")
    csp.wait_for_scene("testrun", timeout_s=45.0)
    time.sleep(2.0)

    summary = wait_for_materialized_bots()
    result["bot_summary_before"] = summary
    set_lua_bot_tick_enabled(False)

    source_progression = int_value(summary, "player.progression")
    bot_count = int_value(summary, "bot.count")
    bot_ids = [int_value(summary, f"bot.{index}.id") for index in range(1, bot_count + 1)]
    if not bot_ids:
        raise SkillChoiceStressFailure("no materialized bots found for stress test")

    result["bonus_choice_count_probe"] = run_bonus_choice_count_probe(
        bot_ids[0],
        1000,
        100000,
        source_progression,
    )

    pool_signatures: dict[int, list[tuple[int, ...]]] = {bot_id: [] for bot_id in bot_ids}
    iteration_records: list[dict[str, object]] = []

    for iteration in range(1, iterations + 1):
        level = iteration + 1
        experience = 100 + (iteration * 10)
        debug_sync_level_up(level, experience, source_progression)
        record: dict[str, object] = {
            "iteration": iteration,
            "level": level,
            "experience": experience,
            "bots": [],
        }
        for bot_id in bot_ids:
            choices = query_choices(bot_id)
            if not choices["pending"] or choices["count"] <= 0:
                raise SkillChoiceStressFailure(
                    f"bot {bot_id} did not receive pending choices on iteration {iteration}: {choices}"
                )
            option_ids = tuple(option["id"] for option in choices["options"])
            pool_signatures[bot_id].append(option_ids)
            enriched_options = enrich_choice_options(bot_id, choices)
            option_index = rng.randint(1, int(choices["count"]))
            selected = choices["options"][option_index - 1]
            option_id = int(selected["id"])
            selected_enriched = enriched_options[option_index - 1]
            before = query_entry_state(bot_id, option_id)
            stats_before = query_progression_stats(bot_id)
            loadout_before = query_bot_loadout(bot_id)
            choose_skill(bot_id, option_index, int(choices["generation"]))
            after = query_entry_state(bot_id, option_id)
            stats_after = query_progression_stats(bot_id)
            loadout_after = query_bot_loadout(bot_id)
            profile_after = query_bot_profile(bot_id)
            entry_changed = before.get("bytes") != after.get("bytes")
            entry_enabled = int(after.get("active", 0)) > 0 or int(after.get("visible", 0)) > 0
            if not entry_changed and not entry_enabled:
                raise SkillChoiceStressFailure(
                    "selected skill did not appear to change or enable its progression entry: "
                    f"iteration={iteration} bot={bot_id} option_id={option_id} before={before} after={after}"
                )
            if not profile_after["available"] or profile_after["level"] != level or profile_after["xp"] != experience:
                raise SkillChoiceStressFailure(
                    "bot runtime profile did not stay synchronized after skill apply: "
                    f"iteration={iteration} bot={bot_id} expected_level={level} expected_xp={experience} "
                    f"profile_after={profile_after}"
                )

            record["bots"].append({
                "bot_id": bot_id,
                "generation": choices["generation"],
                "options": option_ids,
                "options_enriched": enriched_options,
                "option_count": choices["count"],
                "selected_index": option_index,
                "selected_option_id": option_id,
                "selected_option_name": selected_enriched.get("name"),
                "entry_changed": entry_changed,
                "entry_active_before": before.get("active"),
                "entry_visible_before": before.get("visible"),
                "entry_active_after": after.get("active"),
                "entry_visible_after": after.get("visible"),
                "progression_entry_before": before,
                "progression_entry_after": after,
                "progression_entry_field_diff": diff_dict(
                    {k: v for k, v in before.items() if k not in {"bytes", "name_candidates"}},
                    {k: v for k, v in after.items() if k not in {"bytes", "name_candidates"}},
                ),
                "progression_entry_byte_diff": diff_hex_bytes(
                    str(before.get("bytes", "")),
                    str(after.get("bytes", "")),
                ),
                "progression_stat_before": stats_before,
                "progression_stat_after": stats_after,
                "progression_stat_diff": diff_dict(stats_before, stats_after),
                "loadout_before": loadout_before,
                "loadout_after": loadout_after,
                "loadout_diff": diff_dict(loadout_before, loadout_after),
                "profile_level_after": profile_after["level"],
                "profile_xp_after": profile_after["xp"],
                "profile_primary_entry_after": profile_after["primary_entry_index"],
            })
        iteration_records.append(record)

    result["iterations"] = iteration_records
    result["pool_signatures"] = {
        str(bot_id): [list(signature) for signature in signatures]
        for bot_id, signatures in pool_signatures.items()
    }
    result["unique_pool_counts"] = {
        str(bot_id): len(set(signatures))
        for bot_id, signatures in pool_signatures.items()
    }
    if iterations > 1:
        for bot_id, unique_count in result["unique_pool_counts"].items():
            if int(unique_count) < 2:
                raise SkillChoiceStressFailure(
                    f"bot {bot_id} did not show evolving skill pools over {iterations} iterations"
                )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--seed", type=int, default=1337)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--keep-running", action="store_true")
    args = parser.parse_args()

    if args.iterations <= 0:
        raise SkillChoiceStressFailure("--iterations must be positive")

    result: dict[str, object] | None = None
    try:
        result = run_stress(args.iterations, args.seed)
        result["ok"] = True
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps({
            "ok": True,
            "output": str(args.output),
            "iterations": args.iterations,
            "unique_pool_counts": result["unique_pool_counts"],
            "bonus_option_count": result["bonus_choice_count_probe"]["choices"]["count"],
        }, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        failure = {
            "ok": False,
            "error": str(exc),
            "partial_result": result,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(failure, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(failure, indent=2, sort_keys=True))
        return 1
    finally:
        if not args.keep_running:
            csp.stop_game()


if __name__ == "__main__":
    raise SystemExit(main())
