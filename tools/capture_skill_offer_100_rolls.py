#!/usr/bin/env python3
"""Capture 100 seed-controlled retail skill-offer rolls for one stock loadout."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import record_native_sim_goldens as native_goldens  # noqa: E402
import record_progression_goldens as progression_goldens  # noqa: E402
from record_native_sim_goldens import CaptureFailure, OwnedSoloSession, require  # noqa: E402


INSTANCE = "offer-diff-100"
PORTS = (52681, 52682)
PARTICIPANT_ID = "0x2000000000006A64"
MOD_ID = "sample.lua.bots"
RUNTIME_ROOT = Path("/mnt/c/sd-skill-offer-100-roll-diff-20260824-root")
DEFAULT_OUTPUT = ROOT / "runtime" / "skill-offer-100-roll-native.json"
MASTER_SEED = 0x02468ACE
GAMEPLAY_MASTER_SEED = 0x13579BDF
ROLL_COUNT = 100
TARGET_LEVEL = 2
TARGET_EXPERIENCE = 100
STANDARD_ELEMENT_ID = 4
STANDARD_DISCIPLINE_ID = 2
STANDARD_PRIMARY_ID = 8
STANDARD_SECONDARY_ID = 11


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_revision() -> dict[str, Any]:
    def git(*arguments: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(ROOT), *arguments],
            capture_output=True,
            check=False,
            encoding="utf-8",
            errors="replace",
            text=True,
            timeout=30.0,
        )
        require(
            completed.returncode == 0,
            f"git {' '.join(arguments)} failed: {completed.stderr.strip()}",
        )
        return completed.stdout.strip()

    return {
        "commit_sha": git("rev-parse", "HEAD"),
        "tree_sha": git("rev-parse", "HEAD^{tree}"),
        "worktree_dirty": bool(git("status", "--porcelain")),
    }


def as_int(value: str | None, default: int = 0) -> int:
    if value is None or value in {"", "nil"}:
        return default
    try:
        return int(value, 0)
    except ValueError:
        return int(float(value))


def as_float(value: str | None, default: float = 0.0) -> float:
    if value is None or value in {"", "nil"}:
        return default
    return float(value)


def parse_csv_ints(value: str | None) -> list[int]:
    if not value:
        return []
    return [int(item) for item in value.split(",") if item]


def create_standard_bot(session: OwnedSoloSession) -> int:
    values = session.values(
        f"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
local player = sd.player.get_state()
if type(player) ~= 'table' then
  emit('ok', false)
  emit('error', 'missing_player')
  return
end
local id, err = sd.bots.create({{
  name = 'Offer Differential Ether Arcane',
  profile = {{
    element_id = {STANDARD_ELEMENT_ID},
    discipline_id = {STANDARD_DISCIPLINE_ID},
    level = 1,
    experience = 0,
    loadout = {{
      primary_entry_index = {STANDARD_PRIMARY_ID},
      primary_combo_entry_index = {STANDARD_PRIMARY_ID},
      secondary_entry_indices = {{ {STANDARD_SECONDARY_ID} }},
    }},
  }},
  scene = {{ kind = 'shared_hub' }},
  ready = true,
  heading = 90.0,
  position = {{
    x = (tonumber(player.x) or 0.0) + 110.0,
    y = tonumber(player.y) or 0.0,
  }},
}})
emit('ok', id ~= nil)
emit('bot_id', id or 0)
emit('error', err or '')
"""
    )
    require(values.get("ok") == "true", f"standard bot creation failed: {values}")
    bot_id = as_int(values.get("bot_id"))
    require(bot_id > 0, f"standard bot returned an invalid id: {values}")
    progression_goldens._wait_until(
        session,
        f"bot {bot_id} materialization",
        lambda: session.values(
            f"""
local bot = sd.bots.get_state({bot_id})
print('available=' .. tostring(type(bot) == 'table'))
print('actor=' .. tostring(type(bot) == 'table' and bot.actor_address or 0))
print('progression=' .. tostring(
  type(bot) == 'table' and bot.progression_runtime_state_address or 0))
"""
        ),
        lambda current: (
            current.get("available") == "true"
            and as_int(current.get("actor")) > 0
            and as_int(current.get("progression")) > 0
        ),
        timeout=45.0,
        interval=0.1,
    )
    return bot_id


def capture_progression(session: OwnedSoloSession, bot_id: int | None) -> dict[str, Any]:
    selector = "nil" if bot_id is None else str(bot_id)
    values = session.values(
        f"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
local function off(name) return tonumber(sd.debug.layout_offset(name)) or 0 end
local function ri(address) return tonumber(sd.debug.read_i32(address)) or 0 end
local function ru(address) return tonumber(sd.debug.read_u32(address)) or 0 end
local function r16(address) return tonumber(sd.debug.read_u16(address)) or 0 end
local function r8(address) return tonumber(sd.debug.read_u8(address)) or 0 end
local function rf(address) return tonumber(sd.debug.read_float(address)) or 0 end
local requested = {selector}
local public = requested == nil and sd.player.get_state() or sd.bots.get_state(requested)
local progression = requested == nil and
  (tonumber(public and public.progression_address) or 0) or
  (tonumber(public and public.progression_runtime_state_address) or 0)
emit('progression', progression)
if progression == 0 then return end
local table_address = ru(progression + off('standalone_wizard_progression_table_base'))
local table_count = ri(progression + off('standalone_wizard_progression_table_count'))
local stride = off('standalone_wizard_progression_entry_stride')
local permanent_offset = off('standalone_wizard_progression_active_flag')
local effective_offset = off('standalone_wizard_progression_entry_effective_rank')
emit('table_address', table_address)
emit('table_count', table_count)
emit('level', ri(progression + off('progression_level')))
emit('experience', rf(progression + off('progression_xp')))
emit('previous_threshold', rf(progression + off('progression_previous_xp_threshold')))
emit('next_threshold', rf(progression + off('progression_next_xp_threshold')))
emit('nonlocal_mode', r8(progression + off('progression_nonlocal_mode_flag')))
emit('max_mana', rf(progression + off('progression_max_mp')))
emit('element_root', ri(progression + 0x82C))
emit('discipline_root', ri(progression + 0x830))
emit('offer_seed', ri(progression + 0x834))
emit('picker_screen', ru(progression + 0x83C))
emit('weld_offer_marker', ru(progression + 0x840))
emit('pending_weld_build', ri(progression + 0x844))
emit('offer_cycle', ru(progression + 0x848))
emit('discipline_offer_bias', r8(progression + 0x7DA))
emit('feature_flags', ru(progression + 0x878))
emit('primary_skill', ri(progression + 0x86C))
emit('secondary_skill', ri(progression + 0x870))
local forced_pointer = ru(progression + 0x860)
local forced_count = ri(progression + 0x864)
local forced = {{}}
if forced_pointer ~= 0 and forced_count > 0 and forced_count <= 32 then
  for index = 0, forced_count - 1 do
    forced[#forced + 1] = tostring(ri(forced_pointer + index * 4))
  end
end
emit('forced_ids', table.concat(forced, ','))
local permanent = {{}}
local effective = {{}}
for id = 0, table_count - 1 do
  local row = table_address + id * stride
  permanent[#permanent + 1] = tostring(r16(row + permanent_offset))
  effective[#effective + 1] = tostring(r16(row + effective_offset))
  emit('row.' .. id .. '.root', sd.debug.read_i16(row + 0x1C) or -1)
  emit('row.' .. id .. '.category', r8(row + 0x26))
  emit('row.' .. id .. '.minimum_level', ri(row + 0x2C))
  local statbook = ru(row + 0x6C)
  emit('row.' .. id .. '.cap', statbook ~= 0 and ri(statbook + 0x58) or 0)
  emit('row.' .. id .. '.max', statbook ~= 0 and ri(statbook + 0x5C) or 0)
end
emit('permanent_ranks', table.concat(permanent, ','))
emit('effective_ranks', table.concat(effective, ','))
for index = 0, 7 do
  emit('advanced_unlock.' .. index, sd.debug.read_u8(0x00B3BDD8 + index) or 0)
end
local game_slot = sd.debug.resolve_game_address(0x0081C264)
local game = game_slot and ru(game_slot) or 0
emit('game', game)
for id = 0, math.min(table_count - 1, 82) do
  emit('global_disable_a.' .. id, game ~= 0 and r8(game + 0x1668 + id) or 0)
  emit('global_disable_b.' .. id, game ~= 0 and r8(game + 0x1868 + id) or 0)
end
""",
        timeout=30.0,
    )
    table_count = as_int(values.get("table_count"))
    require(as_int(values.get("progression")) > 0, f"missing progression: {values}")
    require(table_count >= 83, f"native progression table is incomplete: {table_count}")
    return {
        "progression_address": as_int(values.get("progression")),
        "table_address": as_int(values.get("table_address")),
        "table_count": table_count,
        "level": as_int(values.get("level")),
        "experience": as_float(values.get("experience")),
        "previous_threshold": as_float(values.get("previous_threshold")),
        "next_threshold": as_float(values.get("next_threshold")),
        "nonlocal_mode": as_int(values.get("nonlocal_mode")),
        "maximum_mana": as_float(values.get("max_mana")),
        "element_root": as_int(values.get("element_root"), -1),
        "discipline_root": as_int(values.get("discipline_root"), -1),
        "offer_seed": as_int(values.get("offer_seed")),
        "picker_screen": as_int(values.get("picker_screen")),
        "weld_offer_marker": as_int(values.get("weld_offer_marker")),
        "pending_weld_build": as_int(values.get("pending_weld_build"), -1),
        "offer_cycle": as_int(values.get("offer_cycle")),
        "discipline_offer_bias": as_int(values.get("discipline_offer_bias")),
        "feature_flags": as_int(values.get("feature_flags")),
        "primary_skill": as_int(values.get("primary_skill"), -1),
        "secondary_skill": as_int(values.get("secondary_skill"), -1),
        "forced_offer_skill_ids": parse_csv_ints(values.get("forced_ids")),
        "permanent_ranks": parse_csv_ints(values.get("permanent_ranks")),
        "effective_ranks": parse_csv_ints(values.get("effective_ranks")),
        "advanced_unlocks": [
            as_int(values.get(f"advanced_unlock.{index}")) != 0
            for index in range(8)
        ],
        "global_disable_a": [
            as_int(values.get(f"global_disable_a.{skill_id}"))
            for skill_id in range(table_count)
        ],
        "global_disable_b": [
            as_int(values.get(f"global_disable_b.{skill_id}"))
            for skill_id in range(table_count)
        ],
        "rows": [
            {
                "id": skill_id,
                "root": as_int(values.get(f"row.{skill_id}.root"), -1),
                "category": as_int(values.get(f"row.{skill_id}.category")),
                "minimum_level": as_int(values.get(f"row.{skill_id}.minimum_level")),
                "cap_level": as_int(values.get(f"row.{skill_id}.cap")),
                "maximum_level": as_int(values.get(f"row.{skill_id}.max")),
            }
            for skill_id in range(table_count)
        ],
    }


def normalize_bot_to_local(
    session: OwnedSoloSession,
    bot_id: int,
    local_state: dict[str, Any],
) -> None:
    permanent = ", ".join(str(value) for value in local_state["permanent_ranks"])
    effective = ", ".join(str(value) for value in local_state["effective_ranks"])
    values = session.values(
        f"""
local function off(name) return tonumber(sd.debug.layout_offset(name)) or 0 end
local bot = sd.bots.get_state({bot_id})
local progression = tonumber(bot and bot.progression_runtime_state_address) or 0
local table_address = progression ~= 0 and tonumber(sd.debug.read_u32(
  progression + off('standalone_wizard_progression_table_base'))) or 0
local table_count = progression ~= 0 and tonumber(sd.debug.read_i32(
  progression + off('standalone_wizard_progression_table_count'))) or 0
local stride = off('standalone_wizard_progression_entry_stride')
local permanent_offset = off('standalone_wizard_progression_active_flag')
local effective_offset = off('standalone_wizard_progression_entry_effective_rank')
local permanent = {{ {permanent} }}
local effective = {{ {effective} }}
local writes = progression ~= 0 and table_address ~= 0 and
  table_count == #permanent and table_count == #effective
if writes then
  for id = 0, table_count - 1 do
    local row = table_address + id * stride
    writes = sd.debug.write_u16(row + permanent_offset, permanent[id + 1]) and writes
    writes = sd.debug.write_u16(row + effective_offset, effective[id + 1]) and writes
  end
end
writes = writes and sd.debug.write_i32(progression + 0x82C, {local_state['element_root']})
writes = writes and sd.debug.write_i32(progression + 0x830, {local_state['discipline_root']})
writes = writes and sd.debug.write_u32(progression + 0x840, {local_state['weld_offer_marker']})
writes = writes and sd.debug.write_i32(progression + 0x844, {local_state['pending_weld_build']})
writes = writes and sd.debug.write_u32(progression + 0x848, {local_state['offer_cycle']})
writes = writes and sd.debug.write_u8(progression + 0x7DA, {local_state['discipline_offer_bias']})
writes = writes and sd.debug.write_u32(progression + 0x878, {local_state['feature_flags']})
writes = writes and sd.debug.write_i32(progression + 0x86C, {local_state['primary_skill']})
writes = writes and sd.debug.write_i32(progression + 0x870, {local_state['secondary_skill']})
writes = writes and sd.debug.write_i32(progression + 0x864, 0)
local refresh = sd.debug.resolve_game_address(0x0065F9A0)
local refreshed = writes and sd.debug.call_thiscall_ret_u32(refresh, progression) ~= nil
print('writes=' .. tostring(writes))
print('refreshed=' .. tostring(refreshed))
""",
        timeout=30.0,
    )
    require(
        values.get("writes") == "true" and values.get("refreshed") == "true",
        f"bot-to-local book normalization failed: {values}",
    )


def sample_seeds(session: OwnedSoloSession, master_seed: int) -> list[int]:
    values = session.values(
        f"""
local sample = assert(sd.debug.sample_native_rng({master_seed}, 1000000, {ROLL_COUNT}))
print('count=' .. tostring(sample.count or 0))
print('stream=' .. tostring(sample.stream or ''))
print('outputs=' .. table.concat(sample.outputs or {{}}, ','))
"""
    )
    seeds = parse_csv_ints(values.get("outputs"))
    require(values.get("stream") == "native-private-stack-state", f"wrong RNG stream: {values}")
    require(as_int(values.get("count")) == ROLL_COUNT, f"wrong seed count: {values}")
    require(len(seeds) == ROLL_COUNT, f"missing sampled seeds: {len(seeds)}")
    require(all(0 <= seed < 1_000_000 for seed in seeds), "sampled seed left native range")
    return seeds


def write_offer_seed(session: OwnedSoloSession, bot_id: int, seed: int) -> None:
    values = session.values(
        f"""
local bot = sd.bots.get_state({bot_id})
local progression = tonumber(bot and bot.progression_runtime_state_address) or 0
local ok = progression ~= 0 and sd.debug.write_i32(progression + 0x834, {seed})
print('ok=' .. tostring(ok))
print('observed=' .. tostring(
  progression ~= 0 and sd.debug.read_i32(progression + 0x834) or -1))
"""
    )
    require(
        values.get("ok") == "true" and as_int(values.get("observed"), -1) == seed,
        f"offer seed write failed: {values}",
    )


def roll_offer(
    session: OwnedSoloSession,
    bot_id: int,
    seed: int,
    gameplay_seed: int,
) -> dict[str, Any]:
    write_offer_seed(session, bot_id, seed)
    values = session.values(
        f"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
local function off(name) return tonumber(sd.debug.layout_offset(name)) or 0 end
local bot = sd.bots.get_state({bot_id})
local progression = tonumber(bot and bot.progression_runtime_state_address) or 0
local global_slot = sd.debug.resolve_game_address(0x00818B08)
local global_rng = global_slot and (sd.debug.read_u32(global_slot) or 0) or 0
local reseed_ok = false
if global_rng ~= 0 then
  local reseed = sd.debug.resolve_game_address(0x00401120)
  reseed_ok = pcall(function()
    sd.debug.call_thiscall_u32(reseed, global_rng, {gameplay_seed})
  end)
end
emit('gameplay_reseed_ok', reseed_ok)
emit('gameplay_seed', {gameplay_seed})
local ok = sd.bots.debug_sync_level_up({{
  level = {TARGET_LEVEL},
  experience = {TARGET_EXPERIENCE},
}})
local choices = sd.bots.get_skill_choices({bot_id}) or {{}}
emit('ok', ok)
emit('pending', choices.pending)
emit('generation', choices.generation)
emit('level', choices.level)
emit('experience', choices.experience)
emit('count', type(choices.options) == 'table' and #choices.options or 0)
for index, option in ipairs(choices.options or {{}}) do
  emit('option.' .. index .. '.id', option.id)
  emit('option.' .. index .. '.apply_count', option.apply_count)
end
emit('seed_after', progression ~= 0 and sd.debug.read_i32(progression + 0x834) or -1)
local table_address = progression ~= 0 and tonumber(sd.debug.read_u32(
  progression + off('standalone_wizard_progression_table_base'))) or 0
local table_count = progression ~= 0 and tonumber(sd.debug.read_i32(
  progression + off('standalone_wizard_progression_table_count'))) or 0
local stride = off('standalone_wizard_progression_entry_stride')
local permanent_offset = off('standalone_wizard_progression_active_flag')
local ranks = {{}}
for id = 0, table_count - 1 do
  ranks[#ranks + 1] = tostring(sd.debug.read_u16(
    table_address + id * stride + permanent_offset) or 0)
end
emit('permanent_ranks', table.concat(ranks, ','))
emit('element_root', progression ~= 0 and sd.debug.read_i32(progression + 0x82C) or -1)
emit('discipline_root', progression ~= 0 and sd.debug.read_i32(progression + 0x830) or -1)
emit('max_mana', progression ~= 0 and sd.debug.read_float(
  progression + off('progression_max_mp')) or 0)
emit('feature_flags', progression ~= 0 and sd.debug.read_u32(progression + 0x878) or 0)
emit('offer_cycle', progression ~= 0 and sd.debug.read_u32(progression + 0x848) or 0)
emit('gameplay_index_a', global_rng ~= 0 and sd.debug.read_i32(global_rng) or -1)
emit('gameplay_index_b', global_rng ~= 0 and sd.debug.read_i32(global_rng + 4) or -1)
local gameplay_words = {{}}
if global_rng ~= 0 then
  for index = 0, 54 do
    gameplay_words[#gameplay_words + 1] = tostring(sd.debug.read_i32(
      global_rng + 8 + index * 4) or -1)
  end
end
emit('gameplay_words', table.concat(gameplay_words, ','))
""",
        timeout=30.0,
    )
    count = as_int(values.get("count"))
    require(values.get("gameplay_reseed_ok") == "true", f"gameplay RNG reseed failed: {values}")
    return {
        "seed": seed,
        "gameplay_seed": gameplay_seed,
        "gameplay_rng_after": {
            "index_a": as_int(values.get("gameplay_index_a"), -1),
            "index_b": as_int(values.get("gameplay_index_b"), -1),
            "words": parse_csv_ints(values.get("gameplay_words")),
        },
        "seed_after": as_int(values.get("seed_after"), -1),
        "pending": values.get("pending") == "true",
        "generation": as_int(values.get("generation")),
        "level": as_int(values.get("level")),
        "experience": as_int(values.get("experience")),
        "options": [
            {
                "id": as_int(values.get(f"option.{index}.id"), -1),
                "apply_count": as_int(values.get(f"option.{index}.apply_count"), 1),
            }
            for index in range(1, count + 1)
        ],
        "permanent_ranks": parse_csv_ints(values.get("permanent_ranks")),
        "element_root": as_int(values.get("element_root"), -1),
        "discipline_root": as_int(values.get("discipline_root"), -1),
        "maximum_mana": as_float(values.get("max_mana")),
        "feature_flags": as_int(values.get("feature_flags")),
        "offer_cycle": as_int(values.get("offer_cycle")),
    }


def state_projection(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "level": state["level"],
        "experience": state["experience"],
        "previous_threshold": state["previous_threshold"],
        "next_threshold": state["next_threshold"],
        "maximum_mana": state["maximum_mana"],
        "element_root": state["element_root"],
        "discipline_root": state["discipline_root"],
        "weld_offer_marker": state["weld_offer_marker"],
        "pending_weld_build": state["pending_weld_build"],
        "offer_cycle": state["offer_cycle"],
        "discipline_offer_bias": state["discipline_offer_bias"],
        "feature_flags": state["feature_flags"],
        "primary_skill": state["primary_skill"],
        "secondary_skill": state["secondary_skill"],
        "forced_offer_skill_ids": state["forced_offer_skill_ids"],
        "permanent_ranks": state["permanent_ranks"],
        "effective_ranks": state["effective_ranks"],
        "advanced_unlocks": state["advanced_unlocks"],
        "global_disable_a": state["global_disable_a"],
        "global_disable_b": state["global_disable_b"],
    }


def summarize_rolls(rolls: list[dict[str, Any]], names: dict[int, str]) -> dict[str, Any]:
    appearances: Counter[int] = Counter()
    position_counts: list[Counter[int]] = [Counter(), Counter(), Counter(), Counter()]
    duplicate_rolls = 0
    signatures: list[tuple[int, ...]] = []
    for roll in rolls:
        option_ids = tuple(int(option["id"]) for option in roll["options"])
        signatures.append(option_ids)
        appearances.update(option_ids)
        if len(set(option_ids)) < len(option_ids):
            duplicate_rolls += 1
        for index, skill_id in enumerate(option_ids):
            position_counts[index][skill_id] += 1
    return {
        "unique_ordered_pools": len(set(signatures)),
        "duplicate_id_rolls": duplicate_rolls,
        "unique_skill_ids": sorted(appearances),
        "appearance_counts": [
            {"id": skill_id, "name": names.get(skill_id, f"skill_{skill_id}"), "count": count}
            for skill_id, count in sorted(appearances.items())
        ],
        "position_counts": [
            [
                {"id": skill_id, "name": names.get(skill_id, f"skill_{skill_id}"), "count": count}
                for skill_id, count in sorted(counter.items())
            ]
            for counter in position_counts
            if counter
        ],
    }


def run_capture() -> dict[str, Any]:
    progression_goldens._powershell()
    native_goldens.RUNTIME_ROOT = RUNTIME_ROOT
    native_goldens.GAME_DIRECTORY = progression_goldens.GAME_DIRECTORY
    native_goldens.GAME_BINARY = progression_goldens.GAME_BINARY
    native_goldens.sha256_file = progression_goldens.windows_sha256
    names = progression_goldens._skill_names()

    os.environ["SDMOD_LUA_BOTS_ACTIVE"] = "none"
    forwarded = set(filter(None, os.environ.get("WSLENV", "").split(":")))
    forwarded.update({"SDMOD_LUA_BOTS_ACTIVE", "SDMOD_DISABLE_AUDIO", "SDMOD_ENABLE_AUDIO"})
    os.environ["WSLENV"] = ":".join(sorted(forwarded))

    session = OwnedSoloSession(
        instance=INSTANCE,
        ports=PORTS,
        mod_id=MOD_ID,
        participant_id=PARTICIPANT_ID,
        test_blank_boneyard=False,
        headless=True,
        quick_start_element="ether",
        quick_start_discipline="arcane",
    )
    launch: dict[str, Any] | None = None
    cleanup: list[dict[str, Any]] = []
    try:
        launch = session.launch()
        session.wait_for_pipe()
        session.wait_for_scene("hub")
        cleared = session.values(
            """
sd.bots.clear()
print('count=' .. tostring(#(sd.bots.list() or {})))
"""
        )
        require(cleared.get("count") == "0", f"startup bots did not clear: {cleared}")
        local_level_one = capture_progression(session, None)
        bot_id = create_standard_bot(session)
        raw_bot_level_one = capture_progression(session, bot_id)
        raw_rank_mismatches = [
            skill_id
            for skill_id, (local_rank, bot_rank) in enumerate(zip(
                local_level_one["permanent_ranks"],
                raw_bot_level_one["permanent_ranks"],
                strict=True,
            ))
            if local_rank != bot_rank
        ]
        normalize_bot_to_local(session, bot_id, local_level_one)
        bot_level_one = capture_progression(session, bot_id)

        loadout_comparison = {
            "raw_bot_rank_mismatch_ids": raw_rank_mismatches,
            "local_nonlocal_mode": local_level_one["nonlocal_mode"],
            "bot_nonlocal_mode": bot_level_one["nonlocal_mode"],
            "rank_match": local_level_one["permanent_ranks"] == bot_level_one["permanent_ranks"],
            "effective_rank_match": local_level_one["effective_ranks"] == bot_level_one["effective_ranks"],
            "element_root_match": local_level_one["element_root"] == bot_level_one["element_root"],
            "discipline_root_match": local_level_one["discipline_root"] == bot_level_one["discipline_root"],
            "primary_match": local_level_one["primary_skill"] == bot_level_one["primary_skill"],
            "secondary_match": local_level_one["secondary_skill"] == bot_level_one["secondary_skill"],
        }
        require(loadout_comparison["rank_match"], "native bot loadout ranks differ from stock local loadout")
        require(loadout_comparison["effective_rank_match"], "native bot effective ranks differ from local")
        require(loadout_comparison["element_root_match"], "native bot element root differs from local")
        require(loadout_comparison["discipline_root_match"], "native bot discipline root differs from local")
        require(loadout_comparison["primary_match"], "native bot primary differs from local")
        require(loadout_comparison["secondary_match"], "native bot secondary differs from local")

        seeds = sample_seeds(session, MASTER_SEED)
        gameplay_seeds = sample_seeds(session, GAMEPLAY_MASTER_SEED)
        write_offer_seed(session, bot_id, MASTER_SEED % 1_000_000)
        pre_sync = session.values(
            f"""
print('ok=' .. tostring(sd.bots.debug_sync_level_up({{
  level = {TARGET_LEVEL}, experience = {TARGET_EXPERIENCE}
}})))
"""
        )
        require(pre_sync.get("ok") == "true", f"native level-two setup failed: {pre_sync}")
        frozen_state = capture_progression(session, bot_id)
        require(frozen_state["level"] == TARGET_LEVEL, f"bot did not reach level two: {frozen_state}")
        frozen_projection = state_projection(frozen_state)

        rolls: list[dict[str, Any]] = []
        mutations: list[dict[str, Any]] = []
        for index, (seed, gameplay_seed) in enumerate(
            zip(seeds, gameplay_seeds, strict=True),
            start=1,
        ):
            roll = roll_offer(session, bot_id, seed, gameplay_seed)
            require(roll["pending"], f"roll {index} did not produce a pending offer: {roll}")
            require(len(roll["options"]) == 3, f"roll {index} did not produce three choices: {roll}")
            require(roll["seed_after"] == seed, f"roll {index} mutated its actor-private seed")
            if roll["permanent_ranks"] != frozen_state["permanent_ranks"]:
                mutations.append({"roll": index, "field": "permanent_ranks"})
            for option in roll["options"]:
                option["name"] = names.get(int(option["id"]), f"skill_{option['id']}")
            rolls.append(roll)

        final_state = capture_progression(session, bot_id)
        final_projection = state_projection(final_state)
        if final_projection != frozen_projection:
            mutations.append({
                "roll": "final",
                "field": "progression_projection",
                "before": frozen_projection,
                "after": final_projection,
            })
        local_final = capture_progression(session, None)
        require(not mutations, f"native 100-roll capture mutated frozen state: {mutations}")
        require(
            state_projection(local_final) == state_projection(local_level_one),
            "native diagnostic mutated the local player",
        )
        row_rules = progression_goldens.skill_row_rules(session, bot_id)
        cleanup = session.close()
        require(len(cleanup) == 1, f"cleanup did not stop exactly one owned process: {cleanup}")
        require(launch is not None, "launch provenance was not captured")

        return {
            "schema": "solomon-dark-skill-offer-differential-v2",
            "captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "retail": {
                "binary_path": str(progression_goldens.GAME_BINARY),
                "binary_size": progression_goldens.GAME_BINARY.stat().st_size,
                "binary_sha256": progression_goldens.windows_sha256(progression_goldens.GAME_BINARY),
                "preferred_image_base": "0x00400000",
                "offer_builder": "Skills_Wizard vtable +0x74 -> 0x0067CB70",
                "rng_initializer": "0x00401110",
                "rng_integer": "0x00401170",
            },
            "diagnostic": {
                "source_revision": source_revision(),
                "script_sha256": sha256_file(Path(__file__)),
                "loader_sha256": progression_goldens.windows_sha256(progression_goldens.STAGED_LOADER),
                "launch": launch,
                "cleanup": cleanup,
                "injected_loader": True,
                "offer_implementation_replaced_or_hooked": False,
            },
            "experiment": {
                "loadout": {
                    "element": "ether",
                    "discipline": "arcane",
                    "native_roots": [0, 7],
                    "starting_skills": [8, 11],
                },
                "target_level": TARGET_LEVEL,
                "target_experience": TARGET_EXPERIENCE,
                "roll_count": ROLL_COUNT,
                "seed_source": {
                    "master_seed": MASTER_SEED,
                    "sampler": "retail isolated native RNG",
                    "range": 1_000_000,
                    "seeds": seeds,
                },
                "gameplay_seed_source": {
                    "master_seed": GAMEPLAY_MASTER_SEED,
                    "sampler": "retail isolated native RNG",
                    "range": 1_000_000,
                    "seeds": gameplay_seeds,
                },
                "active_gameplay_rng_reseeded_before_each_roll": True,
                "choice_applied": False,
                "book_and_progression_frozen_between_rolls": True,
            },
            "local_level_one": local_level_one,
            "bot_level_one_before_normalization": raw_bot_level_one,
            "bot_level_one": bot_level_one,
            "loadout_comparison": loadout_comparison,
            "frozen_level_two": frozen_state,
            "row_rules": row_rules,
            "rolls": rolls,
            "summary": summarize_rolls(rolls, names),
            "mutations": mutations,
        }
    finally:
        if session.process_ids:
            session.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    document = run_capture()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "ok": True,
        "output": str(args.output),
        "roll_count": len(document["rolls"]),
        "summary": document["summary"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CaptureFailure as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
