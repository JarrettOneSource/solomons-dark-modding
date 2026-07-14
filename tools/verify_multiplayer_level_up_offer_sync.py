#!/usr/bin/env python3
"""Verify host-authored multiplayer level-up offer/choice sync."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_NAME,
    CLIENT_PIPE,
    HOST_ID,
    HOST_NAME,
    HOST_PIPE,
    VerifyFailure,
    disable_bots,
    launch_pair,
    lua,
    parse_int_text,
    parse_key_values,
    start_host_testrun_and_wait_for_clients,
    stop_games,
    wait_for_remote,
)
from verify_real_input_spell_cast_sync import (
    CLIENT_LOG,
    HOST_LOG,
    Direction,
    enable_progression_neutral_combat,
    log_after,
    parse_local_pressed_sequences,
    read_log,
    sustain_pair_vitals,
)


ROOT = Path(__file__).resolve().parent.parent
RUNTIME_OUTPUT = ROOT / "runtime" / "multiplayer_level_up_offer_sync.json"
SKILL_CONFIG_DIR = ROOT / "runtime" / "stage" / "data" / "wizardskills"
FIREBALL_BUILD_SKILL_ID = 0x3F3
FIREBALL_PROJECTILE_TYPE = 0x7D4
FIREBALL_CAST_FRAMES = 2
MAX_FIREBALL_LEVEL_STEPS = 25
TARGET_SPELL_UPGRADE_SKILL_FILES = (
    "explode.cfg",
    "embers.cfg",
    "battle_mage.cfg",
)

MANA_PREPARED_RE = re.compile(
    r"\[bots\] mana prepared\. bot_id=(?P<bot_id>\d+) "
    r"skill_id=(?P<skill_id>-?\d+) kind=(?P<kind>[a-z_]+) "
    r"progression_level=(?P<level>\d+) cost=(?P<cost>[0-9.+\-eE]+) "
    r"native_stat_cost=(?P<native_stat_cost>[0-9.+\-eE]+) "
    r"native_output_scale=(?P<native_output_scale>[0-9.+\-eE]+).*?"
    r"progression_runtime=(?P<progression>0x[0-9A-Fa-f]+|\d+)"
)


CAPTURE_LUA = r"""
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end

local scene = sd.world and sd.world.get_scene and sd.world.get_scene() or nil
local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
local mode_offset = sd.debug and sd.debug.layout_offset and sd.debug.layout_offset("progression_nonlocal_mode_flag") or nil
local picker_screen_offset = sd.debug and sd.debug.layout_offset and sd.debug.layout_offset("progression_local_skill_picker_screen") or nil
emit("scene", scene and (scene.name or scene.kind) or "")
emit("player.level", player and player.level or 0)
emit("player.xp", player and player.xp or 0)
emit("player.progression", player and player.progression_address or 0)
emit("player.progression_mode", (player and player.progression_address and player.progression_address ~= 0 and mode_offset and sd.debug.read_u8(player.progression_address + mode_offset)) or -1)

local picker_screen = 0
if player and player.progression_address and player.progression_address ~= 0 and picker_screen_offset then
  picker_screen = sd.debug.read_ptr(player.progression_address + picker_screen_offset) or 0
end
emit("player.skill_picker_screen", picker_screen)
if picker_screen ~= 0 then
  local desired_count = sd.debug.read_i32(picker_screen + 0x88) or -1
  local option_values = sd.debug.read_ptr(picker_screen + 0x90) or 0
  local option_count = sd.debug.read_i32(picker_screen + 0x94) or -1
  local selected_index = sd.debug.read_i32(picker_screen + 0x5F8) or -1
  emit("picker.desired_count", desired_count)
  emit("picker.option_values", option_values)
  emit("picker.option_count", option_count)
  emit("picker.selected_index", selected_index)
  if option_values ~= 0 and option_count > 0 then
    local limit = option_count
    if limit > 8 then limit = 8 end
    for index = 1, limit do
      emit("picker.option." .. tostring(index) .. ".id", sd.debug.read_i32(option_values + ((index - 1) * 4)) or -1)
    end
  end
else
  emit("picker.desired_count", -1)
  emit("picker.option_values", 0)
  emit("picker.option_count", -1)
  emit("picker.selected_index", -1)
end

local mp = sd.runtime and sd.runtime.get_multiplayer_state and sd.runtime.get_multiplayer_state() or nil
emit("mp.valid", mp ~= nil)
emit("mp.participant_count", mp and mp.participant_count or 0)
if mp and mp.participants then
  for index, participant in ipairs(mp.participants) do
    local prefix = "participant." .. tostring(index) .. "."
    emit(prefix .. "id", participant.participant_id or 0)
    emit(prefix .. "name", participant.name or "")
    emit(prefix .. "kind", participant.kind or "")
    emit(prefix .. "controller", participant.controller_kind or "")
    emit(prefix .. "connected", participant.transport_connected or false)
    emit(prefix .. "in_run", participant.in_run or false)
    emit(prefix .. "level", participant.level or 0)
    emit(prefix .. "experience", participant.experience_current or 0)
    local owned = participant.owned_progression or {}
    emit(prefix .. "spellbook_revision", owned.spellbook_revision or 0)
    emit(prefix .. "statbook_revision", owned.statbook_revision or 0)
  end
end

local offer = mp and mp.active_level_up_offer or nil
emit("offer.valid", offer and offer.valid or false)
emit("offer.submitted", offer and offer.selection_submitted or false)
emit("offer.authority", offer and offer.authority_participant_id or 0)
emit("offer.target", offer and offer.target_participant_id or 0)
emit("offer.id", offer and offer.offer_id or 0)
emit("offer.run_nonce", offer and offer.run_nonce or 0)
emit("offer.level", offer and offer.level or 0)
emit("offer.experience", offer and offer.experience or 0)
emit("offer.option_count", offer and offer.option_count or 0)
emit("offer.native_picker_presented", offer and offer.native_picker_presented or false)
emit("offer.native_picker_options_pinned", offer and offer.native_picker_options_pinned or false)
emit("offer.native_picker_local_apply_observed", offer and offer.native_picker_local_apply_observed or false)
if offer and offer.options then
  for index, option in ipairs(offer.options) do
    emit("offer.option." .. tostring(index) .. ".id", option.option_id or option.id or -1)
    emit("offer.option." .. tostring(index) .. ".apply_count", option.apply_count or 1)
  end
end

local result = mp and mp.last_level_up_choice_result or nil
emit("result.valid", result and result.valid or false)
emit("result.authority", result and result.authority_participant_id or 0)
emit("result.target", result and result.target_participant_id or 0)
emit("result.offer_id", result and result.offer_id or 0)
emit("result.level", result and result.level or 0)
emit("result.experience", result and result.experience or 0)
emit("result.option_index", result and result.option_index or -1)
emit("result.option_id", result and result.option_id or -1)
emit("result.apply_count", result and result.apply_count or 0)
emit("result.resulting_active", result and result.resulting_active or 0)
emit("result.code", result and result.result_code or 0)
emit("result.auto_picked", result and result.auto_picked or false)

local wait = mp and mp.level_up_wait_status or nil
emit("wait.valid", wait and wait.valid or false)
emit("wait.pause_active", wait and wait.pause_active or false)
emit("wait.timed_out", wait and wait.timed_out or false)
emit("wait.authority", wait and wait.authority_participant_id or 0)
emit("wait.barrier_id", wait and wait.barrier_id or 0)
emit("wait.revision", wait and wait.revision or 0)
emit("wait.deadline_remaining_ms", wait and wait.deadline_remaining_ms or 0)
emit("wait.waiting_count", wait and wait.waiting_count or 0)
emit("wait.display_text", wait and wait.display_text or "")
if wait and wait.waiting_participant_ids then
  for index, participant_id in ipairs(wait.waiting_participant_ids) do
    emit("wait.participant." .. tostring(index), participant_id or 0)
  end
end
"""


def capture(pipe_name: str) -> dict[str, str]:
    return parse_key_values(lua(pipe_name, CAPTURE_LUA, timeout=5.0))


def participant_row(values: dict[str, str], participant_id: int) -> dict[str, Any] | None:
    count = parse_int_text(values.get("mp.participant_count"), 0)
    for index in range(1, count + 1):
        prefix = f"participant.{index}."
        if parse_int_text(values.get(prefix + "id"), 0) != participant_id:
            continue
        return {
            "index": index,
            "id": participant_id,
            "name": values.get(prefix + "name", ""),
            "connected": values.get(prefix + "connected", ""),
            "in_run": values.get(prefix + "in_run", ""),
            "level": parse_int_text(values.get(prefix + "level"), 0),
            "experience": parse_int_text(values.get(prefix + "experience"), 0),
            "spellbook_revision": parse_int_text(values.get(prefix + "spellbook_revision"), 0),
            "statbook_revision": parse_int_text(values.get(prefix + "statbook_revision"), 0),
        }
    return None


def offer_option_ids(raw: dict[str, str], option_count: int) -> list[int]:
    return [
        parse_int_text(raw.get(f"offer.option.{index}.id"), -1)
        for index in range(1, option_count + 1)
    ]


def parse_hex_or_int(value: str) -> int:
    return int(value, 0)


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


def query_progression_entry(
    pipe_name: str,
    *,
    option_id: int,
    participant_id: int | None = None,
) -> dict[str, Any]:
    if participant_id is None:
        progression_source_lua = """
local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
local progression = player and tonumber(player.progression_address) or 0
"""
    else:
        progression_source_lua = f"""
local participant = sd.bots and sd.bots.get_participant_state and sd.bots.get_participant_state({participant_id}) or nil
local progression = participant and tonumber(participant.progression_runtime_state_address) or 0
"""

    code = f"""
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
  if address == 0 then return '' end
  local ok, value = pcall(sd.debug.read_string, address, max_len or 96)
  if not ok then return '' end
  return clean_string(value)
end
local function read_native_string_object(address)
  address = tonumber(address) or 0
  if address == 0 then return '' end
  local data_offset = sd.debug.layout_offset('native_string_data')
  local length_offset = sd.debug.layout_offset('native_string_length')
  local data = tonumber(sd.debug.read_u32(address + data_offset)) or 0
  local length = tonumber(sd.debug.read_i32(address + length_offset)) or 0
  if data == 0 or length <= 0 or length > 256 then return '' end
  return read_c_string(data, length + 1)
end
local function emit_name_candidates(prefix, statbook)
  statbook = tonumber(statbook) or 0
  emit(prefix .. '.name', '')
  if statbook == 0 then return end
  local string_object = statbook + sd.debug.layout_offset('statbook_name_string')
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
{progression_source_lua}
local table_base_offset = sd.debug.layout_offset('standalone_wizard_progression_table_base')
local table_count_offset = sd.debug.layout_offset('standalone_wizard_progression_table_count')
local entry_stride = sd.debug.layout_offset('standalone_wizard_progression_entry_stride')
local internal_id_offset = sd.debug.layout_offset('standalone_wizard_progression_entry_internal_id')
local active_offset = sd.debug.layout_offset('standalone_wizard_progression_active_flag')
local visible_offset = sd.debug.layout_offset('standalone_wizard_progression_visible_flag')
local category_offset = sd.debug.layout_offset('standalone_wizard_progression_entry_category')
local statbook_offset = sd.debug.layout_offset('standalone_wizard_progression_entry_statbook')
local max_level_offset = sd.debug.layout_offset('statbook_max_level')
local table_addr = progression ~= 0 and sd.debug.read_u32(progression + table_base_offset) or 0
local table_count = progression ~= 0 and sd.debug.read_i32(progression + table_count_offset) or 0
local option_id = {option_id}
emit('available', progression ~= 0 and table_addr ~= 0 and table_count > option_id)
emit('progression', progression)
emit('table', table_addr)
emit('table_count', table_count)
emit('option_id', option_id)
if progression ~= 0 and table_addr ~= 0 and table_count > option_id then
  local entry = table_addr + (option_id * entry_stride)
  local statbook = sd.debug.read_u32(entry + statbook_offset) or 0
  emit('entry', entry)
  emit('internal_id', sd.debug.read_i32(entry + internal_id_offset))
  emit('active', sd.debug.read_u16(entry + active_offset))
  emit('visible', sd.debug.read_u16(entry + visible_offset))
  emit('category', sd.debug.read_u16(entry + category_offset))
  emit('statbook', statbook)
  if statbook ~= 0 then
    emit('statbook.max_level', sd.debug.read_i32(statbook + max_level_offset))
  end
  emit_name_candidates('statbook', statbook)
end
"""
    values = parse_key_values(lua(pipe_name, code, timeout=5.0))
    metadata = resolve_skill_metadata(values.get("statbook.name", ""), option_id)
    return {
        "available": values.get("available") == "true",
        "progression": parse_int_text(values.get("progression"), 0),
        "table": parse_int_text(values.get("table"), 0),
        "table_count": parse_int_text(values.get("table_count"), 0),
        "option_id": parse_int_text(values.get("option_id"), option_id),
        "entry": parse_int_text(values.get("entry"), 0),
        "internal_id": parse_int_text(values.get("internal_id"), -1),
        "active": parse_int_text(values.get("active"), 0),
        "visible": parse_int_text(values.get("visible"), 0),
        "category": parse_int_text(values.get("category"), 0),
        "statbook": parse_int_text(values.get("statbook"), 0),
        "statbook_max_level": parse_int_text(values.get("statbook.max_level"), -1),
        "native_text": values.get("statbook.name", ""),
        "name": metadata["skill_name"],
        "skill_file": metadata["skill_file"],
        "quick_description": metadata["quick_description"],
        "description": metadata["description"],
        "name_candidates": {
            "object": values.get("statbook.name_object", ""),
            "ptr_object": values.get("statbook.name_ptr_object", ""),
            "ptr_direct": values.get("statbook.name_ptr_direct", ""),
            "direct": values.get("statbook.name_direct", ""),
        },
    }


def query_progression_stats(
    pipe_name: str,
    *,
    participant_id: int | None = None,
) -> dict[str, Any]:
    if participant_id is None:
        progression_source_lua = """
local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
local progression = player and tonumber(player.progression_address) or 0
"""
    else:
        progression_source_lua = f"""
local participant = sd.bots and sd.bots.get_participant_state and sd.bots.get_participant_state({participant_id}) or nil
local progression = participant and tonumber(participant.progression_runtime_state_address) or 0
"""

    code = f"""
local function emit(k, v) print(k .. '=' .. tostring(v)) end
{progression_source_lua}
emit('available', progression ~= 0)
emit('progression', progression)
if progression ~= 0 then
  emit('level', sd.debug.read_i32(progression + sd.debug.layout_offset('progression_level')))
  emit('xp', sd.debug.read_float(progression + sd.debug.layout_offset('progression_xp')))
  emit('previous_xp_threshold', sd.debug.read_float(progression + sd.debug.layout_offset('progression_previous_xp_threshold')))
  emit('next_xp_threshold', sd.debug.read_float(progression + sd.debug.layout_offset('progression_next_xp_threshold')))
  emit('nonlocal_mode', sd.debug.read_u8(progression + sd.debug.layout_offset('progression_nonlocal_mode_flag')))
end
"""
    values = parse_key_values(lua(pipe_name, code, timeout=5.0))
    return {
        "available": values.get("available") == "true",
        "progression": parse_int_text(values.get("progression"), 0),
        "level": parse_int_text(values.get("level"), 0),
        "xp": float(values.get("xp", "0") or 0.0),
        "previous_xp_threshold": float(values.get("previous_xp_threshold", "0") or 0.0),
        "next_xp_threshold": float(values.get("next_xp_threshold", "0") or 0.0),
        "nonlocal_mode": parse_int_text(values.get("nonlocal_mode"), -1),
    }


def enrich_offer_options(option_ids: list[int]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for option_id in option_ids:
        entry = query_progression_entry(
            HOST_PIPE,
            option_id=option_id,
            participant_id=CLIENT_ID,
        )
        enriched.append(
            {
                "id": option_id,
                "name": entry["name"],
                "skill_file": entry["skill_file"],
                "native_text": entry["native_text"],
                "quick_description": entry["quick_description"],
                "description": entry["description"],
                "entry": entry,
            }
        )
    return enriched


def is_target_spell_upgrade_option(option: dict[str, Any]) -> bool:
    return str(option.get("skill_file") or "").lower() in TARGET_SPELL_UPGRADE_SKILL_FILES


def summarize_level_steps(level_steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for step in level_steps:
        offer = step.get("offer", {})
        summary.append(
            {
                "step": step.get("step"),
                "target_level": step.get("target_level"),
                "target_experience": step.get("target_experience"),
                "offer_id": offer.get("offer_id"),
                "options": [
                    {
                        "id": option.get("id"),
                        "name": option.get("name"),
                        "skill_file": option.get("skill_file"),
                    }
                    for option in offer.get("enriched_options", [])
                ],
                "selected": {
                    "index": offer.get("selected_option_index"),
                    "id": offer.get("selected_option_id"),
                },
            }
        )
    return summary


def selected_skill_file(step: dict[str, Any]) -> str:
    offer = step.get("offer", {})
    selected_index = int(offer.get("selected_option_index") or 0)
    options = offer.get("enriched_options", [])
    if selected_index <= 0 or selected_index > len(options):
        return ""
    return str(options[selected_index - 1].get("skill_file") or "").lower()


def parse_remote_mana_prepared(
    log_text: str,
    *,
    bot_id: int,
    skill_id: int,
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for line in log_text.splitlines():
        match = MANA_PREPARED_RE.search(line)
        if match is None:
            continue
        if int(match.group("bot_id")) != bot_id or int(match.group("skill_id")) != skill_id:
            continue
        matches.append(
            {
                "line": line,
                "bot_id": bot_id,
                "skill_id": skill_id,
                "kind": match.group("kind"),
                "progression_level": int(match.group("level")),
                "cost": float(match.group("cost")),
                "native_stat_cost": float(match.group("native_stat_cost")),
                "native_output_scale": float(match.group("native_output_scale")),
                "progression_runtime": parse_hex_or_int(match.group("progression")),
            }
        )
    return matches


def parse_remote_projectile_sequences(
    log_text: str,
    *,
    bot_id: int,
    skill_id: int,
    expected_projectile_type: int,
) -> list[int]:
    sequences: list[int] = []
    expected_type_text = f"0x{expected_projectile_type:X}"
    for line in log_text.splitlines():
        if (
            "[bots] cast complete (" not in line
            or f"bot_id={bot_id}" not in line
            or f"skill_id={skill_id}" not in line
            or "remote_input_controlled=1" not in line
            or "remote_projectile_observed=1" not in line
            or f"remote_projectile_expected_type={expected_type_text}" not in line
        ):
            continue
        match = re.search(r"remote_cast_sequence=(\d+)", line)
        if match:
            sequences.append(int(match.group(1)))
    return sequences


def verify_client_fireball_cast_on_host(
    label: str,
    *,
    expected_min_level: int | None = None,
    baseline_cost: float | None = None,
) -> dict[str, Any]:
    from verify_multiplayer_fireball_explode_effect_sync import (
        build_manual_pair,
        cast_fireball_pair,
    )
    from verify_multiplayer_primary_kill_stress import cleanup_live_enemies

    direction = Direction(
        label,
        CLIENT_ID,
        "Client Player",
        CLIENT_PIPE,
        CLIENT_LOG,
        0,
        HOST_PIPE,
        HOST_LOG,
    )
    cleanup = cleanup_live_enemies()
    pair = build_manual_pair(
        direction,
        320.0,
        0.0,
        target_hp=5000.0,
        include_secondary=False,
    )
    source_offset = len(read_log(CLIENT_LOG))
    receiver_offset = len(read_log(HOST_LOG))
    cast = cast_fireball_pair(
        direction,
        pair,
        f"level_up_offer.{label}",
        resource_value=5000.0,
    )
    source_log = log_after(CLIENT_LOG, source_offset)
    phase_counts = cast["phase_counts"]
    native_hook_count = cast["native_hook_count"]
    native_sequences = parse_local_pressed_sequences(source_log, CLIENT_ID)
    if native_hook_count != 1 or len(native_sequences) != 1:
        raise VerifyFailure(
            f"{label}: expected one native Fireball cast sequence, "
            f"hooks={native_hook_count} sequences={native_sequences} phases={phase_counts}"
        )

    deadline = time.monotonic() + 4.0
    prepared_matches: list[dict[str, Any]] = []
    projectile_sequences: list[int] = []
    receiver_log = ""
    while time.monotonic() < deadline:
        receiver_log = log_after(HOST_LOG, receiver_offset)
        prepared_matches = parse_remote_mana_prepared(
            receiver_log,
            bot_id=CLIENT_ID,
            skill_id=FIREBALL_BUILD_SKILL_ID,
        )
        projectile_sequences = parse_remote_projectile_sequences(
            receiver_log,
            bot_id=CLIENT_ID,
            skill_id=FIREBALL_BUILD_SKILL_ID,
            expected_projectile_type=FIREBALL_PROJECTILE_TYPE,
        )
        if prepared_matches:
            break
        time.sleep(0.05)

    if not prepared_matches:
        raise VerifyFailure(
            f"{label}: host never prepared the client's remote Fireball cast; "
            f"native_sequences={native_sequences} receiver_tail={receiver_log[-4000:]}"
        )
    replicated_delivery = cast["replicated_cast_delivery"]
    if not replicated_delivery["ok"]:
        raise VerifyFailure(
            f"{label}: host did not queue and prepare the client's remote Fireball; "
            f"delivery={replicated_delivery} receiver_tail={receiver_log[-4000:]}"
        )

    prepared = prepared_matches[-1]
    if expected_min_level is not None and prepared["progression_level"] < expected_min_level:
        raise VerifyFailure(
            f"{label}: host used stale client Fireball progression level; "
            f"expected_min={expected_min_level} prepared={prepared}"
        )

    return {
        "cleanup": cleanup,
        "pair": pair,
        "cast": cast,
        "phase_counts": phase_counts,
        "native_hook_count": native_hook_count,
        "native_sequences": native_sequences,
        "mana_prepared": {
            key: value
            for key, value in prepared.items()
            if key != "line"
        },
        "baseline_cost": baseline_cost,
        "cost_delta_from_baseline": (
            prepared["cost"] - baseline_cost
            if baseline_cost is not None
            else None
        ),
        "projectile_sequences": projectile_sequences,
        "replicated_cast_delivery": replicated_delivery,
    }


def wait_for_pair_ready(timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, dict[str, str]] = {}
    while time.monotonic() < deadline:
        last = {
            "host": capture(HOST_PIPE),
            "client": capture(CLIENT_PIPE),
        }
        host_client = participant_row(last["host"], CLIENT_ID)
        client_host = participant_row(last["client"], HOST_ID)
        if (
            last["host"].get("scene") == "testrun"
            and last["client"].get("scene") == "testrun"
            and host_client is not None
            and client_host is not None
            and host_client["connected"] == "true"
            and client_host["connected"] == "true"
            and host_client["in_run"] == "true"
            and client_host["in_run"] == "true"
        ):
            return {
                "host_observes_client": host_client,
                "client_observes_host": client_host,
            }
        time.sleep(0.2)
    raise VerifyFailure(f"multiplayer run pair did not expose both participants: {last}")


def publish_offer(level: int, experience: int) -> dict[str, str]:
    code = f"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local ok, result = pcall(sd.runtime.debug_publish_level_up_offer, {{ level = {level}, experience = {experience}, target_participant_id = {CLIENT_ID} }})
emit("pcall_ok", ok)
emit("result", result)
"""
    values = parse_key_values(lua(HOST_PIPE, code, timeout=5.0))
    if values.get("pcall_ok") != "true" or values.get("result") != "true":
        raise VerifyFailure(f"host failed to publish level-up offer: {values}")
    return values


def publish_barrier_offer(level: int, experience: int) -> dict[str, str]:
    code = f"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local ok, result = pcall(sd.runtime.debug_publish_level_up_offer, {{ level = {level}, experience = {experience} }})
emit("pcall_ok", ok)
emit("result", result)
"""
    values = parse_key_values(lua(HOST_PIPE, code, timeout=5.0))
    if values.get("pcall_ok") != "true" or values.get("result") != "true":
        raise VerifyFailure(f"host failed to publish all-player level-up offer: {values}")
    return values


def wait_for_local_offer(
    pipe_name: str,
    participant_id: int,
    level: int,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = capture(pipe_name)
        if (
            last.get("offer.valid") == "true"
            and parse_int_text(last.get("offer.authority"), 0) == HOST_ID
            and parse_int_text(last.get("offer.target"), 0) == participant_id
            and parse_int_text(last.get("offer.level"), 0) == level
            and parse_int_text(last.get("offer.option_count"), 0) > 0
            and parse_int_text(last.get("player.skill_picker_screen"), 0) != 0
            and last.get("offer.native_picker_presented") == "true"
            and last.get("offer.native_picker_options_pinned") == "true"
        ):
            option_count = parse_int_text(last.get("offer.option_count"), 0)
            picker_count = parse_int_text(last.get("picker.option_count"), 0)
            if picker_count < option_count:
                time.sleep(0.1)
                continue

            mismatched_options: list[tuple[int, int, int]] = []
            for option_index in range(1, option_count + 1):
                offered_id = parse_int_text(last.get(f"offer.option.{option_index}.id"), -1)
                picker_id = parse_int_text(last.get(f"picker.option.{option_index}.id"), -1)
                if offered_id != picker_id:
                    mismatched_options.append((option_index, offered_id, picker_id))
            if mismatched_options:
                time.sleep(0.1)
                continue

            return {
                "raw": last,
                "offer_id": parse_int_text(last.get("offer.id"), 0),
                "option_count": option_count,
                "option_ids": offer_option_ids(last, option_count),
                "first_option_id": parse_int_text(last.get("offer.option.1.id"), -1),
                "progression_mode": parse_int_text(last.get("player.progression_mode"), -1),
                "player_level": parse_int_text(last.get("player.level"), 0),
                "picker_screen": parse_int_text(last.get("player.skill_picker_screen"), 0),
                "picker_option_count": picker_count,
                "picker_selected_index": parse_int_text(last.get("picker.selected_index"), -1),
            }
        time.sleep(0.1)
    raise VerifyFailure(
        "local participant did not receive level-up offer: "
        f"participant_id={participant_id} last={last}"
    )


def wait_for_client_offer(level: int, timeout: float) -> dict[str, Any]:
    return wait_for_local_offer(CLIENT_PIPE, CLIENT_ID, level, timeout)


def wait_for_host_offer(level: int, timeout: float) -> dict[str, Any]:
    return wait_for_local_offer(HOST_PIPE, HOST_ID, level, timeout)


def wait_for_wait_status(
    *,
    participant_id: int,
    pause_active: bool,
    timeout: float,
) -> dict[str, dict[str, str]]:
    deadline = time.monotonic() + timeout
    last_host: dict[str, str] = {}
    last_client: dict[str, str] = {}
    expected_pause = "true" if pause_active else "false"
    while time.monotonic() < deadline:
        last_host = capture(HOST_PIPE)
        last_client = capture(CLIENT_PIPE)
        host_waiting_count = parse_int_text(last_host.get("wait.waiting_count"), 0)
        client_waiting_count = parse_int_text(last_client.get("wait.waiting_count"), 0)
        host_waiting_ids = {
            parse_int_text(last_host.get(f"wait.participant.{index}"), 0)
            for index in range(1, host_waiting_count + 1)
        }
        client_waiting_ids = {
            parse_int_text(last_client.get(f"wait.participant.{index}"), 0)
            for index in range(1, client_waiting_count + 1)
        }

        if pause_active:
            if (
                last_host.get("wait.valid") == "true"
                and last_client.get("wait.valid") == "true"
                and last_host.get("wait.pause_active") == expected_pause
                and last_client.get("wait.pause_active") == expected_pause
                and participant_id in host_waiting_ids
                and participant_id in client_waiting_ids
            ):
                return {"host": last_host, "client": last_client}
        else:
            if (
                last_host.get("wait.valid") == "true"
                and last_client.get("wait.valid") == "true"
                and last_host.get("wait.pause_active") == expected_pause
                and last_client.get("wait.pause_active") == expected_pause
                and host_waiting_count == 0
                and client_waiting_count == 0
            ):
                return {"host": last_host, "client": last_client}
        time.sleep(0.1)
    raise VerifyFailure(
        "level-up wait status did not reach expected state: "
        f"participant_id={participant_id} pause_active={pause_active} "
        f"last_host={last_host} last_client={last_client}"
    )


def wait_for_waiting_ids(
    expected_participant_ids: set[int],
    timeout: float,
    *,
    host_display_text: str | None = None,
    require_timed_out: bool | None = None,
) -> dict[str, dict[str, str]]:
    deadline = time.monotonic() + timeout
    last_host: dict[str, str] = {}
    last_client: dict[str, str] = {}
    while time.monotonic() < deadline:
        last_host = capture(HOST_PIPE)
        last_client = capture(CLIENT_PIPE)
        snapshots = (last_host, last_client)
        observed_sets: list[set[int]] = []
        for snapshot in snapshots:
            waiting_count = parse_int_text(snapshot.get("wait.waiting_count"), 0)
            observed_sets.append(
                {
                    parse_int_text(
                        snapshot.get(f"wait.participant.{index}"),
                        0,
                    )
                    for index in range(1, waiting_count + 1)
                }
                - {0}
            )
        same_barrier = (
            parse_int_text(last_host.get("wait.barrier_id"), 0) != 0
            and last_host.get("wait.barrier_id")
            == last_client.get("wait.barrier_id")
        )
        expected_pause = bool(expected_participant_ids)
        pause_matches = all(
            (snapshot.get("wait.pause_active") == "true")
            == expected_pause
            for snapshot in snapshots
        )
        timeout_matches = (
            require_timed_out is None
            or all(
                (snapshot.get("wait.timed_out") == "true")
                == require_timed_out
                for snapshot in snapshots
            )
        )
        display_matches = (
            host_display_text is None
            or last_host.get("wait.display_text") == host_display_text
        )
        if (
            same_barrier
            and pause_matches
            and timeout_matches
            and display_matches
            and all(
                observed == expected_participant_ids
                for observed in observed_sets
            )
        ):
            return {"host": last_host, "client": last_client}
        time.sleep(0.1)
    raise VerifyFailure(
        "level-up barrier waiting set did not converge: "
        f"expected={sorted(expected_participant_ids)} "
        f"host_display_text={host_display_text!r} "
        f"require_timed_out={require_timed_out} "
        f"last_host={last_host} last_client={last_client}"
    )


def choose_local_option(
    pipe_name: str,
    offer_id: int,
    option_index: int,
) -> dict[str, str]:
    code = f"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local ok, result = pcall(sd.runtime.choose_level_up_option, {{ offer_id = {offer_id}, option_index = {option_index} }})
emit("pcall_ok", ok)
emit("result", result)
"""
    values = parse_key_values(lua(pipe_name, code, timeout=5.0))
    if values.get("pcall_ok") != "true" or values.get("result") != "true":
        raise VerifyFailure(
            f"local participant failed to submit level-up choice: {values}"
        )
    return values


def choose_client_option(offer_id: int, option_index: int) -> dict[str, str]:
    return choose_local_option(CLIENT_PIPE, offer_id, option_index)


def choose_host_option(offer_id: int, option_index: int) -> dict[str, str]:
    return choose_local_option(HOST_PIPE, offer_id, option_index)


def wait_for_choice_result(
    offer_id: int,
    level: int,
    timeout: float,
    *,
    target_participant_id: int = CLIENT_ID,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_host: dict[str, str] = {}
    last_client: dict[str, str] = {}
    while time.monotonic() < deadline:
        last_host = capture(HOST_PIPE)
        last_client = capture(CLIENT_PIPE)
        local_values = (
            last_host
            if target_participant_id == HOST_ID
            else last_client
        )
        host_code = parse_int_text(last_host.get("result.code"), 0)
        client_code = parse_int_text(last_client.get("result.code"), 0)
        if (
            parse_int_text(last_host.get("result.offer_id"), 0) == offer_id
            and parse_int_text(last_client.get("result.offer_id"), 0) == offer_id
            and parse_int_text(last_host.get("result.target"), 0)
            == target_participant_id
            and parse_int_text(last_client.get("result.target"), 0)
            == target_participant_id
            and host_code == 1
            and client_code == 1
            and parse_int_text(local_values.get("result.level"), 0) == level
            and local_values.get("offer.valid") == "false"
            and parse_int_text(
                local_values.get("player.skill_picker_screen"),
                0,
            ) == 0
        ):
            return {
                "host": last_host,
                "client": last_client,
                "host_remote_client": participant_row(last_host, CLIENT_ID),
                "client_observes_host": participant_row(last_client, HOST_ID),
                "client_progression_mode": parse_int_text(
                    last_client.get("player.progression_mode"),
                    -1,
                ),
                "client_player_level": parse_int_text(
                    last_client.get("player.level"),
                    0,
                ),
                "client_picker_screen": parse_int_text(
                    last_client.get("player.skill_picker_screen"),
                    0,
                ),
                "local_progression_mode": parse_int_text(
                    local_values.get("player.progression_mode"),
                    -1,
                ),
                "local_player_level": parse_int_text(
                    local_values.get("player.level"),
                    0,
                ),
                "local_picker_screen": parse_int_text(
                    local_values.get("player.skill_picker_screen"),
                    0,
                ),
                "result_option_id": parse_int_text(
                    local_values.get("result.option_id"),
                    -1,
                ),
                "auto_picked":
                    local_values.get("result.auto_picked") == "true",
            }
        time.sleep(0.1)
    raise VerifyFailure(
        "accepted level-up choice result did not arrive: "
        f"target_participant_id={target_participant_id} "
        f"last_host={last_host} last_client={last_client}"
    )


def verify_level_up_offer_sync(timeout: float) -> dict[str, Any]:
    ready = wait_for_pair_ready(timeout)
    run_materialized = {
        "host_observes_client": wait_for_remote(HOST_PIPE, CLIENT_ID, CLIENT_NAME, "testrun"),
        "client_observes_host": wait_for_remote(CLIENT_PIPE, HOST_ID, HOST_NAME, "testrun"),
    }
    vitals_before_combat = sustain_pair_vitals()
    combat = enable_progression_neutral_combat()
    vitals_after_combat = sustain_pair_vitals()
    baseline_fireball_cast = verify_client_fireball_cast_on_host(
        "client_to_host_baseline_fireball"
    )
    level_steps: list[dict[str, Any]] = []
    spell_upgrade_step: dict[str, Any] | None = None

    for step in range(1, MAX_FIREBALL_LEVEL_STEPS + 1):
        host_client_stats = query_progression_stats(
            HOST_PIPE,
            participant_id=CLIENT_ID,
        )
        client_stats = query_progression_stats(CLIENT_PIPE)
        if not host_client_stats["available"] or not client_stats["available"]:
            raise VerifyFailure(
                f"participant progression stats unavailable before level-up step {step}: "
                f"host_client={host_client_stats} client={client_stats}"
            )
        target_level = max(
            host_client_stats["level"],
            client_stats["level"],
        ) + 1
        target_experience = int(
            max(
                host_client_stats["next_xp_threshold"],
                client_stats["next_xp_threshold"],
                125.0,
            ) + 10.0
        )

        publish = publish_barrier_offer(target_level, target_experience)
        host_offer = wait_for_host_offer(target_level, timeout)
        offer = wait_for_client_offer(target_level, timeout)
        wait_active = wait_for_waiting_ids(
            {HOST_ID, CLIENT_ID},
            timeout,
            require_timed_out=False,
        )
        if offer["progression_mode"] != 0:
            raise VerifyFailure(f"client progression mode was not restored after offer sync: {offer}")
        if offer["player_level"] < target_level:
            raise VerifyFailure(f"client local progression did not sync to target level: {offer}")

        enriched_options = enrich_offer_options(offer["option_ids"])
        selected_option_index = 1
        matched_spell_upgrade = False
        for option_index, option in enumerate(enriched_options, start=1):
            if is_target_spell_upgrade_option(option):
                selected_option_index = option_index
                matched_spell_upgrade = True
                break
        selected_option_id = offer["option_ids"][selected_option_index - 1]

        before_host_selected = query_progression_entry(
            HOST_PIPE,
            option_id=selected_option_id,
            participant_id=CLIENT_ID,
        )
        before_client_selected = query_progression_entry(
            CLIENT_PIPE,
            option_id=selected_option_id,
        )
        host_choice = choose_host_option(host_offer["offer_id"], 1)
        host_result = wait_for_choice_result(
            host_offer["offer_id"],
            target_level,
            timeout,
            target_participant_id=HOST_ID,
        )
        wait_for_client = wait_for_waiting_ids(
            {CLIENT_ID},
            timeout,
            host_display_text="Waiting on 1 player",
            require_timed_out=False,
        )
        choice = choose_client_option(offer["offer_id"], selected_option_index)
        result = wait_for_choice_result(offer["offer_id"], target_level, timeout)
        wait_cleared = wait_for_waiting_ids(
            set(),
            timeout,
            require_timed_out=False,
        )
        if result["client_progression_mode"] != 0:
            raise VerifyFailure(f"client progression mode was not restored after choice result: {result}")
        if result["client_player_level"] < target_level:
            raise VerifyFailure(f"client local progression did not keep target level: {result}")
        if result["host_remote_client"] is None or result["host_remote_client"]["level"] < target_level:
            raise VerifyFailure(f"host did not retain client participant target level: {result}")

        after_host_selected = query_progression_entry(
            HOST_PIPE,
            option_id=selected_option_id,
            participant_id=CLIENT_ID,
        )
        after_client_selected = query_progression_entry(
            CLIENT_PIPE,
            option_id=selected_option_id,
        )
        step_record = {
            "step": step,
            "target_level": target_level,
            "target_experience": target_experience,
            "stats_before": {
                "host_client": host_client_stats,
                "client": client_stats,
            },
            "publish": publish,
            "host_offer": {
                "offer_id": host_offer["offer_id"],
                "option_count": host_offer["option_count"],
                "option_ids": host_offer["option_ids"],
            },
            "offer": {
                "offer_id": offer["offer_id"],
                "option_count": offer["option_count"],
                "option_ids": offer["option_ids"],
                "enriched_options": enriched_options,
                "selected_option_index": selected_option_index,
                "selected_option_id": selected_option_id,
                "picker_screen": offer["picker_screen"],
                "picker_option_count": offer["picker_option_count"],
            },
            "wait_active": {
                "host_waiting_count": parse_int_text(wait_active["host"].get("wait.waiting_count"), 0),
                "client_waiting_count": parse_int_text(wait_active["client"].get("wait.waiting_count"), 0),
            },
            "host_choice": host_choice,
            "host_result": {
                "result_option_id": host_result["result_option_id"],
                "local_player_level": host_result["local_player_level"],
                "local_picker_screen": host_result["local_picker_screen"],
            },
            "wait_for_client": {
                "host_waiting_count": parse_int_text(
                    wait_for_client["host"].get("wait.waiting_count"),
                    0,
                ),
                "host_display_text": wait_for_client["host"].get(
                    "wait.display_text",
                    "",
                ),
                "client_waiting_count": parse_int_text(
                    wait_for_client["client"].get("wait.waiting_count"),
                    0,
                ),
            },
            "choice": choice,
            "result": {
                "result_option_id": result["result_option_id"],
                "client_progression_mode": result["client_progression_mode"],
                "client_player_level": result["client_player_level"],
                "client_picker_screen": result["client_picker_screen"],
                "host_remote_client": result["host_remote_client"],
            },
            "wait_cleared": {
                "host_waiting_count": parse_int_text(wait_cleared["host"].get("wait.waiting_count"), 0),
                "client_waiting_count": parse_int_text(wait_cleared["client"].get("wait.waiting_count"), 0),
            },
            "selected_entry": {
                "before_host": before_host_selected,
                "after_host": after_host_selected,
                "before_client": before_client_selected,
                "after_client": after_client_selected,
            },
            "matched_spell_upgrade": matched_spell_upgrade,
        }
        level_steps.append(step_record)

        if matched_spell_upgrade:
            if not before_host_selected["available"] or not after_host_selected["available"]:
                raise VerifyFailure(f"host did not expose client spell-upgrade entry before/after apply: {step_record}")
            if not before_client_selected["available"] or not after_client_selected["available"]:
                raise VerifyFailure(f"client did not expose local spell-upgrade entry before/after apply: {step_record}")
            if after_host_selected["active"] <= before_host_selected["active"]:
                raise VerifyFailure(f"host remote spell-upgrade active count did not increase: {step_record}")
            if after_client_selected["active"] <= before_client_selected["active"]:
                raise VerifyFailure(f"client local spell-upgrade active count did not increase: {step_record}")
            spell_upgrade_step = step_record
            break

    if spell_upgrade_step is None:
        raise VerifyFailure(
            "No target spell-affecting upgrade was offered within "
            f"{MAX_FIREBALL_LEVEL_STEPS} multiplayer level-up steps: "
            f"{summarize_level_steps(level_steps)}"
        )

    post_upgrade_fireball_cast = verify_client_fireball_cast_on_host(
        "client_to_host_upgraded_fireball",
        expected_min_level=spell_upgrade_step["target_level"],
        baseline_cost=baseline_fireball_cast["mana_prepared"]["cost"],
    )
    if (
        selected_skill_file(spell_upgrade_step) == "battle_mage.cfg"
        and (
            post_upgrade_fireball_cast["cost_delta_from_baseline"] is None
            or post_upgrade_fireball_cast["cost_delta_from_baseline"] >= -0.001
        )
    ):
        raise VerifyFailure(
            "Battle Mage applied but host remote Fireball cost did not decrease: "
            f"baseline={baseline_fireball_cast} post={post_upgrade_fireball_cast} "
            f"step={spell_upgrade_step}"
        )

    return {
        "ready": ready,
        "run_materialized": run_materialized,
        "vitals_before_combat": vitals_before_combat,
        "combat": combat,
        "vitals_after_combat": vitals_after_combat,
        "baseline_fireball_cast": baseline_fireball_cast,
        "spell_upgrade_step": spell_upgrade_step,
        "level_steps": level_steps,
        "post_upgrade_fireball_cast": post_upgrade_fireball_cast,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--keep-open", action="store_true")
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()

    output: dict[str, Any] = {"ok": False}
    try:
        stop_games()
        output["launch"] = launch_pair()
        disable_bots()
        output["hub_ready"] = {
            "host_observes_client": wait_for_remote(HOST_PIPE, CLIENT_ID, CLIENT_NAME, "hub"),
            "client_observes_host": wait_for_remote(CLIENT_PIPE, HOST_ID, HOST_NAME, "hub"),
        }
        from verify_multiplayer_primary_kill_stress import (
            set_manual_spawner_test_mode,
        )

        output["manual_spawner_prearm"] = {
            "host": set_manual_spawner_test_mode(HOST_PIPE, True),
            "client": set_manual_spawner_test_mode(CLIENT_PIPE, True),
        }
        output["run_entry"] = start_host_testrun_and_wait_for_clients(timeout=args.timeout)
        output["level_up_offer_sync"] = verify_level_up_offer_sync(timeout=args.timeout)
        output["ok"] = True
    except (VerifyFailure, subprocess.TimeoutExpired) as exc:
        output["error"] = str(exc)
        RUNTIME_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        RUNTIME_OUTPUT.write_text(
            json.dumps(output, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if args.json:
            print(json.dumps(output, indent=2, sort_keys=True))
        else:
            print(f"level-up offer sync verifier failed: {exc}")
        return 1
    finally:
        if not args.keep_open:
            stop_games()

    RUNTIME_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_OUTPUT.write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if args.json:
        print(json.dumps(output, indent=2, sort_keys=True))
    else:
        details = output["level_up_offer_sync"]
        spell_upgrade_step = details["spell_upgrade_step"]
        print(
            "level-up offer sync ok: "
            f"spell_upgrade_offer={spell_upgrade_step['offer']['offer_id']} "
            f"step={spell_upgrade_step['step']} "
            f"picked={spell_upgrade_step['result']['result_option_id']} "
            f"cost={details['baseline_fireball_cast']['mana_prepared']['cost']:.3f}->"
            f"{details['post_upgrade_fireball_cast']['mana_prepared']['cost']:.3f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
