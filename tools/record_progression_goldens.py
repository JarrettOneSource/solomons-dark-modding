#!/usr/bin/env python3
"""Record native XP, level-up offers, and per-actor skill-effect goldens.

The recorder owns one ``prog-*`` solo instance. It derives every provenance
field itself, records three native bot offer/apply cycles, mutates only the
owned effect bot's skill rows through ``sd.debug``, and uses the stock wave
spawner plus native death callback for kill XP. No CLI option can override
the source revision or binary hashes.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any, Callable


ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import record_enemy_behavior_goldens as enemy_goldens  # noqa: E402
import record_native_sim_goldens as native_goldens  # noqa: E402
from record_native_sim_goldens import (  # noqa: E402
    CaptureFailure,
    OwnedSoloSession,
    require,
)


INSTANCE = "prog-golden"
PORTS = (52381, 52382)
PARTICIPANT_ID = "0x2000000000006A06"
MOD_ID = "sample.lua.bots"
RUNTIME_ROOT = ROOT / "runtime" / "progre-live"
GAME_DIRECTORY = Path(
    "/mnt/c/Users/User/Documents/GitHub/SB Modding/"
    "Solomon Dark/SolomonDarkAbandonware"
)
GAME_BINARY = GAME_DIRECTORY / "SolomonDark.exe"
LOADER = ROOT / "bin" / "Release" / "Win32" / "SolomonDarkModLoader.dll"
STAGED_LOADER = ROOT / "dist" / "launcher" / "SolomonDarkModLoader.dll"
DEFAULT_OUTPUT = (
    ROOT / "tests" / "fixtures" / "webgame" / "progression-goldens.json"
)
SKILL_CATALOG = (
    ROOT / "docs" / "reverse-engineering" / "native-skill-catalog.json"
)

OFFER_SEED = 0x13579
OFFER_LEVELS = (
    (2, 100),
    (3, 170),
    (4, 280),
)
EFFECT_SKILLS = (23, 56, 57, 64, 79)
KILL_SCENARIOS = (
    (0x3E9, "Skeleton"),
    (0x3EC, "Imp"),
    (0x3EF, "Wraith"),
)
KILL_BASE_REWARDS = {
    "Skeleton": 10.0,
    "Imp": 2.0,
    "Wraith": 4.0,
}


def _powershell() -> str:
    resolved = shutil.which("powershell.exe")
    require(resolved is not None, "powershell.exe is not on PATH")
    completed = subprocess.run(
        [
            resolved,
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "$PSVersionTable.PSVersion.Major",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10.0,
        check=False,
    )
    require(
        completed.returncode == 0 and completed.stdout.strip().isdigit(),
        "powershell.exe resolved but is not runnable",
    )
    return resolved


def _windows_path(path: Path) -> str:
    completed = subprocess.run(
        ["wslpath", "-w", str(path.resolve())],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=5.0,
        check=False,
    )
    require(completed.returncode == 0, f"cannot convert path for Windows: {path}")
    return completed.stdout.strip()


def windows_sha256(path: Path) -> str:
    """Derive a file hash with the required Windows-native checksum path."""
    windows_path = _windows_path(path).replace("'", "''")
    completed = subprocess.run(
        [
            _powershell(),
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            f"(Get-FileHash -LiteralPath '{windows_path}' -Algorithm SHA256).Hash.ToLowerInvariant()",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30.0,
        check=False,
    )
    digest = completed.stdout.strip()
    require(
        completed.returncode == 0
        and len(digest) == 64
        and all(character in "0123456789abcdef" for character in digest),
        f"Windows Get-FileHash failed for {path}: {completed.stderr.strip()}",
    )
    return digest


def _windows_git(*arguments: str) -> str:
    quoted_root = _windows_path(ROOT).replace("'", "''")
    quoted_arguments = " ".join(
        "'" + argument.replace("'", "''") + "'" for argument in arguments
    )
    completed = subprocess.run(
        [
            _powershell(),
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            f"& git.exe -C '{quoted_root}' {quoted_arguments}",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30.0,
        check=False,
    )
    require(
        completed.returncode == 0,
        f"Windows git {' '.join(arguments)} failed: {completed.stderr.strip()}",
    )
    return completed.stdout.strip()


def source_revision() -> dict[str, Any]:
    return {
        "commit_sha": _windows_git("rev-parse", "HEAD"),
        "tree_sha": _windows_git("rev-parse", "HEAD^{tree}"),
        "worktree_dirty": bool(_windows_git("status", "--porcelain")),
    }


def _as_int(value: str | None, default: int = 0) -> int:
    if value is None or value in ("", "nil"):
        return default
    try:
        return int(value, 0)
    except ValueError:
        return int(float(value))


def _as_float(value: str | None, default: float = math.nan) -> float:
    if value is None or value in ("", "nil"):
        return default
    return float(value)


def _as_bool(value: str | None) -> bool:
    return value in ("true", "1")


def _wait_until(
    session: OwnedSoloSession,
    description: str,
    query: Callable[[], Any],
    predicate: Callable[[Any], bool],
    *,
    timeout: float,
    interval: float = 0.05,
) -> Any:
    deadline = time.monotonic() + timeout
    last: Any = None
    last_error = ""
    while time.monotonic() < deadline:
        session.assert_wait_target_runnable(description)
        try:
            last = query()
            if predicate(last):
                return last
        except subprocess.TimeoutExpired as error:
            last_error = str(error)
        time.sleep(interval)
    suffix = f"; last_error={last_error}" if last_error else ""
    raise CaptureFailure(
        f"{description} remained busy through timeout: {last}{suffix}"
    )


def _skill_names() -> dict[int, str]:
    document = json.loads(SKILL_CATALOG.read_text(encoding="utf-8"))
    skills = document.get("skills")
    require(isinstance(skills, list) and len(skills) == 82, "skill catalog is incomplete")
    result: dict[int, str] = {}
    for skill in skills:
        require(isinstance(skill, dict), "skill catalog row is not an object")
        skill_id = int(skill["id"])
        require(
            skill_id not in result,
            f"skill catalog contains duplicate id {skill_id}",
        )
        result[skill_id] = str(skill["name"])
    require(
        set(result) == set(range(82)),
        "skill catalog does not contain each public id 0..81 exactly once",
    )
    return result


def create_bot(
    session: OwnedSoloSession,
    *,
    name: str,
    x_offset: float,
) -> int:
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
  name = {json.dumps(name)},
  profile = {{
    element_id = 4,
    discipline_id = 2,
    level = 1,
    experience = 0,
    loadout = {{
      primary_entry_index = 8,
      primary_combo_entry_index = 8,
      secondary_entry_indices = {{ 15, 48 }},
    }},
  }},
  scene = {{ kind = 'shared_hub' }},
  ready = true,
  heading = 90.0,
  position = {{
    x = (tonumber(player.x) or 0.0) + {x_offset:.1f},
    y = tonumber(player.y) or 0.0,
  }},
}})
emit('ok', id ~= nil)
emit('bot_id', id or 0)
emit('error', err or '')
"""
    )
    require(values.get("ok") == "true", f"bot creation failed: {values}")
    bot_id = _as_int(values.get("bot_id"))
    require(bot_id > 0, f"bot creation returned an invalid ID: {values}")
    _wait_until(
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
            and _as_int(current.get("actor")) > 0
            and _as_int(current.get("progression")) > 0
        ),
        timeout=45.0,
        interval=0.2,
    )
    return bot_id


def wait_for_bot_progression(session: OwnedSoloSession, bot_id: int) -> dict[str, str]:
    roster = session.values(
        f"""
local bot = sd.bots.get_state({bot_id})
print('present=' .. tostring(bot ~= nil))
"""
    )
    require(
        roster.get("present") == "true",
        f"bot {bot_id} disappeared from the roster during arena transition: {roster}",
    )

    def probe() -> dict[str, str]:
        return session.values(
            f"""
local function off(name) return tonumber(sd.debug.layout_offset(name)) or 0 end
local bot = sd.bots.get_state({bot_id})
local actor = tonumber(bot and bot.actor_address) or 0
local progression = tonumber(bot and bot.progression_runtime_state_address) or 0
local table_address = progression ~= 0 and tonumber(sd.debug.read_u32(
  progression + off('standalone_wizard_progression_table_base'))) or 0
local count = progression ~= 0 and tonumber(sd.debug.read_i32(
  progression + off('standalone_wizard_progression_table_count'))) or 0
print('present=' .. tostring(bot ~= nil))
print('actor=' .. tostring(actor))
print('progression=' .. tostring(progression))
print('table=' .. tostring(table_address))
print('count=' .. tostring(count))
"""
        )

    return _wait_until(
        session,
        f"bot {bot_id} arena progression materialization",
        probe,
        lambda current: (
            current.get("present") == "true"
            and _as_int(current.get("actor")) > 0
            and _as_int(current.get("progression")) > 0
            and _as_int(current.get("table")) > 0
            and _as_int(current.get("count")) >= 82
        ),
        timeout=20.0,
        interval=0.1,
    )


def actor_snapshot(
    session: OwnedSoloSession,
    *,
    bot_id: int | None,
    skill_ids: tuple[int, ...] = EFFECT_SKILLS,
) -> dict[str, Any]:
    ids = ", ".join(str(value) for value in skill_ids)
    selector = "nil" if bot_id is None else str(bot_id)
    values = session.values(
        f"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
local function off(name) return tonumber(sd.debug.layout_offset(name)) or 0 end
local function rf(address) return tonumber(sd.debug.read_float(address)) or 0 end
local function ri(address) return tonumber(sd.debug.read_i32(address)) or 0 end
local function ru(address) return tonumber(sd.debug.read_u32(address)) or 0 end
local requested = {selector}
local public = requested == nil and sd.player.get_state() or sd.bots.get_state(requested)
local actor = tonumber(public and public.actor_address) or 0
local progression = requested == nil and
  (tonumber(public and public.progression_address) or 0) or
  (tonumber(public and public.progression_runtime_state_address) or 0)
local player = sd.player.get_state() or {{}}
local timing_address = sd.debug.resolve_game_address(0x00820230)
emit('actor_address', actor)
emit('progression_address', progression)
emit('actor_plus_0x200', actor ~= 0 and ru(actor + 0x200) or 0)
emit('actor_plus_0x300', actor ~= 0 and ru(actor + 0x300) or 0)
emit('tick', tonumber(player.local_player_tick_count) or 0)
emit('game_timing_scale', timing_address and rf(timing_address) or 0)
if progression == 0 then return end
emit('level', ri(progression + off('progression_level')))
emit('xp', rf(progression + off('progression_xp')))
emit('previous_threshold', rf(progression + off('progression_previous_xp_threshold')))
emit('next_threshold', rf(progression + off('progression_next_xp_threshold')))
emit('base_hp', rf(progression + 0x6C))
emit('hp', rf(progression + off('progression_hp')))
emit('max_hp', rf(progression + off('progression_max_hp')))
emit('base_mp', rf(progression + 0x78))
emit('mp', rf(progression + off('progression_mp')))
emit('max_mp', rf(progression + off('progression_max_mp')))
emit('mana_recovery', rf(progression + off('progression_mana_recovery_multiplier')))
emit('health_regeneration', rf(progression + off('progression_health_regeneration')))
emit('hoarded_mp', rf(progression + off('progression_hoarded_mp')))
emit('offer_seed', ri(progression + 0x834))
emit('firewalker_active', sd.debug.read_u8(progression + 0x8DC) or 0)
emit('mindstar_active', sd.debug.read_u8(progression + 0x8DD) or 0)
emit('regenerate_active', sd.debug.read_u8(progression + 0x8DE) or 0)
local table_address = ru(progression + off('standalone_wizard_progression_table_base'))
local count = ri(progression + off('standalone_wizard_progression_table_count'))
local stride = off('standalone_wizard_progression_entry_stride')
local permanent = off('standalone_wizard_progression_active_flag')
local effective = off('standalone_wizard_progression_entry_effective_rank')
emit('skill_table_address', table_address)
emit('skill_table_count', count)
for _, id in ipairs({{ {ids} }}) do
  if table_address ~= 0 and id < count then
    local row = table_address + id * stride
    emit('skill.' .. id .. '.permanent', sd.debug.read_u16(row + permanent) or 0)
    emit('skill.' .. id .. '.effective', sd.debug.read_u16(row + effective) or 0)
  end
end
"""
    )
    require(_as_int(values.get("progression_address")) > 0, f"missing progression: {values}")
    result: dict[str, Any] = {
        "tick": _as_int(values.get("tick")),
        "game_timing_scale": _as_float(values.get("game_timing_scale")),
        "actor_address": _as_int(values.get("actor_address")),
        "progression_address": _as_int(values.get("progression_address")),
        "actor_plus_0x200": _as_int(values.get("actor_plus_0x200")),
        "actor_plus_0x300": _as_int(values.get("actor_plus_0x300")),
        "level": _as_int(values.get("level")),
        "xp": _as_float(values.get("xp")),
        "previous_threshold": _as_float(values.get("previous_threshold")),
        "next_threshold": _as_float(values.get("next_threshold")),
        "base_hp": _as_float(values.get("base_hp")),
        "hp": _as_float(values.get("hp")),
        "max_hp": _as_float(values.get("max_hp")),
        "base_mp": _as_float(values.get("base_mp")),
        "mp": _as_float(values.get("mp")),
        "max_mp": _as_float(values.get("max_mp")),
        "mana_recovery": _as_float(values.get("mana_recovery")),
        "health_regeneration": _as_float(values.get("health_regeneration")),
        "hoarded_mp": _as_float(values.get("hoarded_mp")),
        "offer_seed": _as_int(values.get("offer_seed")),
        "toggles": {
            "firewalker": _as_bool(values.get("firewalker_active")),
            "mindstar": _as_bool(values.get("mindstar_active")),
            "regenerate": _as_bool(values.get("regenerate_active")),
        },
        "skill_table_address": _as_int(values.get("skill_table_address")),
        "skill_table_count": _as_int(values.get("skill_table_count")),
        "skills": {},
    }
    for skill_id in skill_ids:
        result["skills"][str(skill_id)] = {
            "permanent_rank": _as_int(values.get(f"skill.{skill_id}.permanent")),
            "effective_rank": _as_int(values.get(f"skill.{skill_id}.effective")),
        }
    return result


def skill_row_rules(session: OwnedSoloSession, bot_id: int) -> list[dict[str, Any]]:
    values = session.values(
        f"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
local function off(name) return tonumber(sd.debug.layout_offset(name)) or 0 end
local bot = sd.bots.get_state({bot_id})
local progression = tonumber(bot and bot.progression_runtime_state_address) or 0
local table_address = progression ~= 0 and
  (tonumber(sd.debug.read_u32(
    progression + off('standalone_wizard_progression_table_base'))) or 0) or 0
local count = progression ~= 0 and
  (tonumber(sd.debug.read_i32(
    progression + off('standalone_wizard_progression_table_count'))) or 0) or 0
local stride = off('standalone_wizard_progression_entry_stride')
local function pairs_at(row, pointer_offset, count_offset)
  local pointer = tonumber(sd.debug.read_u32(row + pointer_offset)) or 0
  local length = tonumber(sd.debug.read_i32(row + count_offset)) or 0
  local parts = {{}}
  if pointer ~= 0 and length > 0 and length <= 32 then
    for index = 0, length - 1 do
      parts[#parts + 1] = tostring(sd.debug.read_i32(pointer + index * 8) or 0) .. ':' ..
        tostring(sd.debug.read_i32(pointer + index * 8 + 4) or 0)
    end
  end
  return table.concat(parts, ',')
end
local function ids_at(row, pointer_offset, count_offset)
  local pointer = tonumber(sd.debug.read_u32(row + pointer_offset)) or 0
  local length = tonumber(sd.debug.read_i32(row + count_offset)) or 0
  local parts = {{}}
  if pointer ~= 0 and length > 0 and length <= 32 then
    for index = 0, length - 1 do
      parts[#parts + 1] = tostring(sd.debug.read_i32(pointer + index * 4) or 0)
    end
  end
  return table.concat(parts, ',')
end
emit('count', count)
for id = 0, count - 1 do
  local row = table_address + id * stride
  emit('row.' .. id .. '.root', sd.debug.read_i16(row + 0x1C) or -1)
  emit('row.' .. id .. '.category', sd.debug.read_u8(row + 0x26) or 0)
  emit('row.' .. id .. '.minimum_level', sd.debug.read_i32(row + 0x2C) or 0)
  emit('row.' .. id .. '.all', pairs_at(row, 0x38, 0x3C))
  emit('row.' .. id .. '.forbidden', pairs_at(row, 0x48, 0x4C))
  emit('row.' .. id .. '.any', ids_at(row, 0x58, 0x5C))
end
""",
        timeout=30.0,
    )
    count = _as_int(values.get("count"))
    require(count >= 82, f"skill-row rule sweep reached no real catalog: {values}")

    def parse_pairs(text: str | None) -> list[dict[str, int]]:
        if not text:
            return []
        result = []
        for item in text.split(","):
            skill_id, rank = item.split(":", 1)
            result.append({"skill_id": int(skill_id), "minimum_rank": int(rank)})
        return result

    rows = []
    for skill_id in range(82):
        rows.append({
            "id": skill_id,
            "root_id": _as_int(values.get(f"row.{skill_id}.root"), -1),
            "category": _as_int(values.get(f"row.{skill_id}.category")),
            "minimum_player_level": _as_int(
                values.get(f"row.{skill_id}.minimum_level")
            ),
            "requires_all": parse_pairs(values.get(f"row.{skill_id}.all")),
            "forbidden_if_at_least": parse_pairs(
                values.get(f"row.{skill_id}.forbidden")
            ),
            "requires_any": [
                int(item)
                for item in values.get(f"row.{skill_id}.any", "").split(",")
                if item
            ],
        })
    return rows


def _write_offer_seed(session: OwnedSoloSession, bot_id: int) -> None:
    values = session.values(
        f"""
local bot = sd.bots.get_state({bot_id})
local progression = tonumber(bot and bot.progression_runtime_state_address) or 0
local ok = progression ~= 0 and sd.debug.write_i32(progression + 0x834, {OFFER_SEED})
print('ok=' .. tostring(ok))
print('observed=' .. tostring(
  progression ~= 0 and sd.debug.read_i32(progression + 0x834) or 0))
"""
    )
    require(
        values.get("ok") == "true" and _as_int(values.get("observed")) == OFFER_SEED,
        f"actor-private offer seed write failed: {values}",
    )


def _query_offer(session: OwnedSoloSession, bot_id: int) -> dict[str, Any]:
    values = session.values(
        f"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
local choices = sd.bots.get_skill_choices({bot_id})
emit('available', type(choices) == 'table')
if type(choices) ~= 'table' then return end
emit('pending', choices.pending)
emit('generation', choices.generation)
emit('level', choices.level)
emit('experience', choices.experience)
emit('count', type(choices.options) == 'table' and #choices.options or 0)
for index, option in ipairs(choices.options or {{}}) do
  emit('option.' .. index .. '.id', option.id)
  emit('option.' .. index .. '.apply_count', option.apply_count)
end
"""
    )
    count = _as_int(values.get("count"))
    return {
        "available": _as_bool(values.get("available")),
        "pending": _as_bool(values.get("pending")),
        "generation": _as_int(values.get("generation")),
        "level": _as_int(values.get("level")),
        "experience": _as_int(values.get("experience")),
        "options": [
            {
                "id": _as_int(values.get(f"option.{index}.id"), -1),
                "apply_count": _as_int(
                    values.get(f"option.{index}.apply_count"), 1
                ),
            }
            for index in range(1, count + 1)
        ],
    }


def capture_offers(
    session: OwnedSoloSession,
    bot_id: int,
    names: dict[int, str],
) -> list[dict[str, Any]]:
    captures = []
    for target_level, experience in OFFER_LEVELS:
        _write_offer_seed(session, bot_id)
        before = actor_snapshot(session, bot_id=bot_id)
        require(
            before["offer_seed"] == OFFER_SEED,
            f"level {target_level} offer seed was not armed on this actor",
        )
        synced = session.values(
            f"""
local ok = sd.bots.debug_sync_level_up({{
  level = {target_level}, experience = {experience}
}})
print('ok=' .. tostring(ok))
"""
        )
        require(synced.get("ok") == "true", f"bot level sync failed: {synced}")
        offer = _wait_until(
            session,
            f"level {target_level} offer",
            lambda: _query_offer(session, bot_id),
            lambda current: (
                current["available"]
                and current["pending"]
                and current["level"] == target_level
                and len(current["options"]) >= 3
            ),
            timeout=15.0,
            interval=0.1,
        )
        for option in offer["options"]:
            option["name"] = names.get(option["id"], f"special_{option['id']}")
        selected_index = 1
        selected = offer["options"][selected_index - 1]
        chosen = session.values(
            f"""
local ok, result = pcall(
  sd.bots.choose_skill, {bot_id}, {selected_index}, {offer['generation']})
print('pcall_ok=' .. tostring(ok))
print('ok=' .. tostring(ok and result == true))
print('error=' .. tostring(ok and '' or result))
"""
        )
        require(chosen.get("ok") == "true", f"bot choice apply failed: {chosen}")
        after = actor_snapshot(session, bot_id=bot_id)
        require(after["level"] == target_level, f"level {target_level} did not persist")
        captures.append({
            "before": before,
            "requested_level": target_level,
            "requested_experience": experience,
            "offer_rng": {
                "stream": "actor-private level-up offer RNG",
                "seed_source": "progression+0x834",
                "seed": OFFER_SEED,
                "builder_reseeds_each_call": True,
                "builder_mutates_seed_field": False,
            },
            "offer": offer,
            "selection": {
                "option_index_one_based": selected_index,
                "option_id": selected["id"],
                "name": selected["name"],
                "apply_count": selected["apply_count"],
            },
            "after": after,
        })
    return captures


def _set_rank_and_refresh(
    session: OwnedSoloSession,
    bot_id: int | None,
    *,
    skill_id: int,
    rank: int,
    firewalker: int | None = None,
    regenerate: int | None = None,
) -> None:
    selector = "nil" if bot_id is None else str(bot_id)
    firewalker_line = "true"
    regenerate_line = "true"
    if firewalker is not None:
        firewalker_line = f"sd.debug.write_u8(progression + 0x8DC, {firewalker})"
    if regenerate is not None:
        regenerate_line = f"sd.debug.write_u8(progression + 0x8DE, {regenerate})"
    values = session.values(
        f"""
local function off(name) return tonumber(sd.debug.layout_offset(name)) or 0 end
local requested = {selector}
local public = requested == nil and sd.player.get_state() or sd.bots.get_state(requested)
local progression = requested == nil and
  (tonumber(public and public.progression_address) or 0) or
  (tonumber(public and public.progression_runtime_state_address) or 0)
local table_address = progression ~= 0 and tonumber(sd.debug.read_u32(
  progression + off('standalone_wizard_progression_table_base'))) or 0
local stride = off('standalone_wizard_progression_entry_stride')
local permanent = off('standalone_wizard_progression_active_flag')
local effective = off('standalone_wizard_progression_entry_effective_rank')
local row = table_address ~= 0 and table_address + {skill_id} * stride or 0
local writes = row ~= 0 and
  sd.debug.write_u16(row + permanent, {rank}) and
  sd.debug.write_u16(row + effective, {rank}) and
  {firewalker_line} and
  {regenerate_line}
local refresh = sd.debug.resolve_game_address(0x0065F9A0)
local refreshed = writes and
  sd.debug.call_thiscall_ret_u32(refresh, progression) ~= nil
print('writes=' .. tostring(writes))
print('refreshed=' .. tostring(refreshed))
"""
    )
    require(
        values.get("writes") == "true" and values.get("refreshed") == "true",
        f"skill {skill_id} rank/refresh failed: {values}",
    )


def capture_skill_effects(
    session: OwnedSoloSession,
    bot_id: int,
    names: dict[int, str],
) -> list[dict[str, Any]]:
    effects: list[dict[str, Any]] = []

    before = actor_snapshot(session, bot_id=bot_id)
    _set_rank_and_refresh(session, bot_id, skill_id=56, rank=1)
    after = actor_snapshot(session, bot_id=bot_id)
    require(abs(after["max_mp"] - (after["base_mp"] + 100.0)) < 0.01, "Mana Up formula failed")
    effects.append({
        "skill_id": 56,
        "name": names[56],
        "rank": 1,
        "target": "synthetic_bot_actor",
        "trigger": "native progression refresh",
        "formula": "max_mp = base_mp + mValue[1] = base_mp + 100",
        "before": before,
        "after": after,
    })

    before = after
    _set_rank_and_refresh(session, bot_id, skill_id=57, rank=1)
    after = actor_snapshot(session, bot_id=bot_id)
    require(
        before["mana_recovery"] > 0
        and abs(after["mana_recovery"] / before["mana_recovery"] - 1.25) < 0.001,
        "Channel Mana formula failed",
    )
    effects.append({
        "skill_id": 57,
        "name": names[57],
        "rank": 1,
        "target": "synthetic_bot_actor",
        "trigger": "native progression refresh",
        "formula": "mana_recovery = base_recovery * (1 + mValue[1] / 100) = base_recovery * 1.25",
        "before": before,
        "after": after,
    })

    before = after
    _set_rank_and_refresh(session, bot_id, skill_id=64, rank=1)
    after = actor_snapshot(session, bot_id=bot_id)
    require(abs(after["max_hp"] - (after["base_hp"] + 50.0)) < 0.01, "Health Up formula failed")
    effects.append({
        "skill_id": 64,
        "name": names[64],
        "rank": 1,
        "target": "synthetic_bot_actor",
        "trigger": "native progression refresh",
        "formula": "max_hp = base_hp + mValue[1] = base_hp + 50",
        "before": before,
        "after": after,
    })

    _clear_derived_hoard(session, None)
    before = actor_snapshot(session, bot_id=None)
    require(before["hoarded_mp"] == 0.0, "Regenerate isolation did not start at zero hoard")
    _set_rank_and_refresh(
        session,
        None,
        skill_id=79,
        rank=1,
        firewalker=0,
        regenerate=1,
    )
    armed = actor_snapshot(session, bot_id=None)
    require(
        abs(armed["hoarded_mp"] - armed["max_mp"] * 0.25) < 0.01,
        "Regenerate mana-hoard formula failed",
    )
    lowered = session.values(
        f"""
local function off(name) return tonumber(sd.debug.layout_offset(name)) or 0 end
local player = sd.player.get_state()
local progression = tonumber(player and player.progression_address) or 0
local max_hp = tonumber(sd.debug.read_float(
  progression + off('progression_max_hp'))) or 0
print('ok=' .. tostring(sd.debug.write_float(
  progression + off('progression_hp'), max_hp - 10.0)))
"""
    )
    require(lowered.get("ok") == "true", f"Regenerate HP staging failed: {lowered}")
    tick_before = actor_snapshot(session, bot_id=None)
    tick_after = _wait_until(
        session,
        "Regenerate per-tick effect",
        lambda: actor_snapshot(session, bot_id=None),
        lambda current: current["tick"] >= tick_before["tick"] + 60,
        timeout=10.0,
        interval=0.02,
    )
    tick_delta = tick_after["tick"] - tick_before["tick"]
    hp_delta = tick_after["hp"] - tick_before["hp"]
    require(tick_delta >= 60 and hp_delta > 0, "Regenerate produced no per-tick HP recovery")
    expected_hp_per_tick = (
        1.5 + tick_before["health_regeneration"] / 10.0
    ) / tick_before["game_timing_scale"]
    require(
        abs(hp_delta / tick_delta - expected_hp_per_tick) < 0.001,
        "Regenerate per-update heal formula diverged from native timing state",
    )
    effects.append({
        "skill_id": 79,
        "name": names[79],
        "rank": 1,
        "target": "local_player_actor",
        "trigger": "specialized progression tick while toggle +0x8DE is active",
        "formula": (
            "hp_delta = native_updates * ((1.5 + health_regeneration / 10) / "
            "game_timing_scale), capped at max_hp"
        ),
        "isolated_derived_state_before_refresh": before,
        "armed": armed,
        "before": tick_before,
        "after": tick_after,
        "observed_tick_delta": tick_delta,
        "observed_hp_delta": hp_delta,
        "observed_hp_per_tick": hp_delta / tick_delta,
        "expected_hp_per_tick": expected_hp_per_tick,
    })

    _set_rank_and_refresh(
        session,
        None,
        skill_id=79,
        rank=0,
        regenerate=0,
    )
    _clear_derived_hoard(session, None)
    before = actor_snapshot(session, bot_id=bot_id)
    require(before["hoarded_mp"] == 0.0, "Firewalker isolation did not start at zero hoard")
    _set_rank_and_refresh(
        session,
        bot_id,
        skill_id=23,
        rank=1,
        firewalker=1,
    )
    after = actor_snapshot(session, bot_id=bot_id)
    require(
        abs(after["hoarded_mp"] - 50.0) < 0.01,
        "Firewalker actor+0x740 hoard formula failed",
    )
    effects.append({
        "skill_id": 23,
        "name": names[23],
        "rank": 1,
        "target": "synthetic_bot_actor",
        "trigger": "toggle + native progression refresh",
        "formula": (
            "actor_hoarded_mp(+0x740) += scalar mHoard = 50 MP; "
            "unlike rank-table hoards, Mana Up does not scale Firewalker's reserve"
        ),
        "before": before,
        "after": after,
    })
    return effects


def _clear_derived_hoard(session: OwnedSoloSession, bot_id: int | None) -> None:
    selector = "nil" if bot_id is None else str(bot_id)
    values = session.values(
        f"""
local function off(name) return tonumber(sd.debug.layout_offset(name)) or 0 end
local requested = {selector}
local public = requested == nil and sd.player.get_state() or sd.bots.get_state(requested)
local progression = requested == nil and
  (tonumber(public and public.progression_address) or 0) or
  (tonumber(public and public.progression_runtime_state_address) or 0)
local ok = progression ~= 0 and sd.debug.write_float(
  progression + off('progression_hoarded_mp'), 0.0)
print('ok=' .. tostring(ok))
"""
    )
    require(values.get("ok") == "true", f"derived hoard isolation failed: {values}")


def reset_effect_skills(session: OwnedSoloSession, bot_id: int) -> None:
    for skill_id in EFFECT_SKILLS:
        _set_rank_and_refresh(
            session,
            bot_id,
            skill_id=skill_id,
            rank=0,
            firewalker=0 if skill_id == 23 else None,
            regenerate=0 if skill_id == 79 else None,
        )


def _player_xy(session: OwnedSoloSession) -> tuple[float, float]:
    values = session.values(
        """
local player = sd.player.get_state() or {}
print('x=' .. tostring(player.x or 0))
print('y=' .. tostring(player.y or 0))
"""
    )
    return _as_float(values.get("x"), 0.0), _as_float(values.get("y"), 0.0)


def _kill_enemy(session: OwnedSoloSession, actor: int) -> dict[str, Any]:
    queued = session.values(
        f"""
local address = {actor}
local original_config = tonumber(sd.debug.read_ptr(address + 0x1D0)) or 0
local config = original_config
if config == 0 then
  local operator_new = assert(sd.debug.resolve_game_address(0x74784D))
  config = assert(sd.debug.call_cdecl_u32_ret_u32(operator_new, 0x200))
  for offset = 0, 0x1FC, 4 do assert(sd.debug.write_u32(config + offset, 0)) end
  assert(sd.debug.write_ptr(address + 0x1D0, config))
end
local max_offset = sd.debug.layout_offset('enemy_max_hp')
local max_hp = tonumber(sd.debug.read_float(address + max_offset)) or 1
local health_ok = sd.gameplay.set_run_enemy_health(address, 0, math.max(max_hp, 1))
local ok, err, serial = sd.debug.queue_native_enemy_death_probe(
  address, config, original_config)
print('queued=' .. tostring(ok))
print('error=' .. tostring(err or ''))
print('serial=' .. tostring(serial or 0))
print('health_ok=' .. tostring(health_ok))
print('config=' .. tostring(config))
print('original_config=' .. tostring(original_config))
"""
    )
    serial = _as_int(queued.get("serial"))
    require(
        queued.get("queued") == "true"
        and queued.get("health_ok") == "true"
        and serial > 0,
        f"native death did not queue: {queued}",
    )
    result = _wait_until(
        session,
        f"native death serial {serial}",
        lambda: session.values(
            f"""
local completed, success, seh, restored, err =
  sd.debug.get_native_enemy_death_probe_result({serial})
print('completed=' .. tostring(completed))
print('success=' .. tostring(success))
print('seh=' .. tostring(seh or 0))
print('restored=' .. tostring(restored))
print('error=' .. tostring(err or ''))
"""
        ),
        lambda current: current.get("completed") == "true",
        timeout=10.0,
        interval=0.02,
    )
    require(
        result.get("success") == "true"
        and result.get("seh") == "0"
        and result.get("restored") == "true",
        f"native death callback failed: {result}",
    )
    return {
        "request_serial": serial,
        "config_address": _as_int(queued.get("config")),
        "original_config_address": _as_int(queued.get("original_config")),
        "result": result,
    }


def _grant_native_kill_xp(session: OwnedSoloSession, amount: float) -> dict[str, Any]:
    queued = session.values(
        f"""
local ok, err, serial = sd.debug.queue_native_experience_gain_probe(
  {amount:.9f}, true)
print('queued=' .. tostring(ok))
print('error=' .. tostring(err or ''))
print('serial=' .. tostring(serial or 0))
"""
    )
    serial = _as_int(queued.get("serial"))
    require(
        queued.get("queued") == "true" and serial > 0,
        f"native kill-XP award did not queue: {queued}",
    )
    result = _wait_until(
        session,
        f"native kill-XP serial {serial}",
        lambda: session.values(
            f"""
local completed, success, before, after, seh, err =
  sd.debug.get_native_experience_gain_probe_result({serial})
print('completed=' .. tostring(completed))
print('success=' .. tostring(success))
print('before=' .. tostring(before or 0))
print('after=' .. tostring(after or 0))
print('seh=' .. tostring(seh or 0))
print('error=' .. tostring(err or ''))
"""
        ),
        lambda current: current.get("completed") == "true",
        timeout=10.0,
        interval=0.02,
    )
    require(
        result.get("success") == "true" and result.get("seh") == "0",
        f"native kill-XP award failed: {result}",
    )
    return {
        "request_serial": serial,
        "apply_native_scaling": True,
        "requested_amount": amount,
        "result": result,
    }


def capture_kill_xp(session: OwnedSoloSession) -> list[dict[str, Any]]:
    x, y = _player_xy(session)
    captures = []
    for index, (type_id, family) in enumerate(KILL_SCENARIOS):
        spawn, spawner = enemy_goldens.spawn_enemy(
            session,
            type_id=type_id,
            x=x + 260.0 + index * 40.0,
            y=y,
        )
        actor = int(spawn["actor_address"])
        raw = session.values(
            f"""
print('reward=' .. tostring(sd.debug.read_float({actor} + 0x178) or 0))
print('type_id=' .. tostring(sd.debug.read_i32({actor} + 0x54) or 0))
"""
        )
        before = actor_snapshot(session, bot_id=None, skill_ids=())
        death = _kill_enemy(session, actor)
        after_death_presenter = actor_snapshot(session, bot_id=None, skill_ids=())
        require(
            after_death_presenter["xp"] == before["xp"],
            f"{family} death presenter unexpectedly awarded XP itself",
        )
        raw_reward = _as_float(raw.get("reward"))
        base_reward = KILL_BASE_REWARDS[family]
        observed_arena_xp_scalar = raw_reward / base_reward
        require(
            abs(observed_arena_xp_scalar - 0.425) < 0.0001,
            f"{family} evaluated reward did not carry arena+0x9024 scaling",
        )
        xp_award = _grant_native_kill_xp(session, raw_reward)
        after = _wait_until(
            session,
            f"{family} XP credit",
            lambda: actor_snapshot(session, bot_id=None, skill_ids=()),
            lambda current: current["xp"] > before["xp"],
            timeout=10.0,
            interval=0.02,
        )
        observed = after["xp"] - before["xp"]
        require(abs(observed - raw_reward) < 0.01, f"{family} XP did not equal raw reward")
        captures.append({
            "family": family,
            "type_id": type_id,
            "actor_address": actor,
            "native_actor_reward_at_0x178": raw_reward,
            "unscaled_family_reward": base_reward,
            "observed_arena_xp_scalar": observed_arena_xp_scalar,
            "before": before,
            "after_death_presenter_before_xp_award": after_death_presenter,
            "after": after,
            "observed_xp_gain": observed,
            "death_callback": death,
            "native_xp_award": xp_award,
            "spawn": spawn,
            "spawner_priming": spawner,
        })
    return captures


def build_document(
    *,
    source: dict[str, Any],
    launch: dict[str, Any],
    cleanup: list[dict[str, Any]],
    offer_bot_id: int,
    effect_bot_id: int,
    row_rules: list[dict[str, Any]],
    offers: list[dict[str, Any]],
    effects: list[dict[str, Any]],
    stock_match: dict[str, Any],
    kills: list[dict[str, Any]],
    isolation: dict[str, Any],
) -> dict[str, Any]:
    return {
        "header": {
            "format": "solomon-dark-native-golden-v1",
            "capture": "progression_xp_offers_and_skill_effects",
            "fixture_is_machine_recorded": True,
            "captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "source_commit_sha": source["commit_sha"],
            "source_tree_sha": source["tree_sha"],
            "worktree_dirty_at_capture_start": source["worktree_dirty"],
            "game_binary_path": str(GAME_BINARY),
            "game_binary_sha256": windows_sha256(GAME_BINARY),
            "loader_sha256": windows_sha256(STAGED_LOADER),
            "build_loader_sha256": windows_sha256(LOADER),
            "instance": INSTANCE,
            "ports": list(PORTS),
            "audio_disabled": True,
            "headless": True,
            "launch_process_id": int(launch["processId"]),
            "launch_executable_path": launch["executablePath"],
            "capture_method": (
                "Owned retail solo instance; stock wave spawner and native death presenter followed "
                "by the retail progression XP grant seam with native scaling for each actor reward; "
                "native bot level sync/offer/apply seam; actor-private offer seed at progression+0x834; "
                "per-actor skill-row writes followed by retail ActorProgressionRefresh; tick-stamped "
                "native progression reads."
            ),
            "provenance_derivation": {
                "source": "recorder-owned Windows git.exe queries",
                "hashes": "recorder-owned Windows Get-FileHash queries",
                "cli_overrides_permitted": False,
            },
            "gameplay_rng_setup": {
                "stream": "active stock gameplay RNG stream",
                "seed_source": "recorder constant passed to sd.rng.set_seed for arena setup",
                "seed": enemy_goldens.RUN_SEED,
                "used_for_offer_selection": False,
            },
            "offer_rng_seed_write": {
                "actor_private_field": "progression+0x834",
                "value": OFFER_SEED,
            },
            "cleanup": cleanup,
        },
        "actor_layout": {
            "actor_direct_progression": "actor+0x200",
            "actor_progression_handle": "actor+0x300",
            "skill_table_pointer": "progression+0x20",
            "skill_table_count": "progression+0x24",
            "skill_row_stride": "0x70",
            "permanent_rank": "row+0x20",
            "effective_rank": "row+0x22",
            "level": "progression+0x30",
            "xp": "progression+0x34",
            "previous_threshold": "progression+0x38",
            "next_threshold": "progression+0x3C",
            "hp_current_max": "progression+0x70/+0x74",
            "mp_current_max": "progression+0x7C/+0x80",
            "hoarded_mp": "progression+0x740",
            "offer_seed": "progression+0x834",
            "toggles": "progression+0x8DC/+0x8DD/+0x8DE",
        },
        "participants": {
            "offer_bot_id": offer_bot_id,
            "effect_bot_id": effect_bot_id,
        },
        "offer_rule_rows": row_rules,
        "level_ups": offers,
        "skill_effects": effects,
        "stock_match": stock_match,
        "xp_kills": kills,
        "per_actor_isolation": isolation,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--raw-evidence", type=Path, default=None)
    args = parser.parse_args()

    _powershell()
    native_goldens.RUNTIME_ROOT = RUNTIME_ROOT
    native_goldens.GAME_DIRECTORY = GAME_DIRECTORY
    native_goldens.GAME_BINARY = GAME_BINARY
    native_goldens.sha256_file = windows_sha256
    enemy_goldens.native_goldens.RUNTIME_ROOT = RUNTIME_ROOT
    enemy_goldens.native_goldens.GAME_DIRECTORY = GAME_DIRECTORY
    enemy_goldens.native_goldens.GAME_BINARY = GAME_BINARY
    enemy_goldens.sha256_file = windows_sha256

    source = source_revision()
    names = _skill_names()
    os.environ["SDMOD_LUA_BOTS_ACTIVE"] = "none"
    forwarded = set(filter(None, os.environ.get("WSLENV", "").split(":")))
    forwarded.update({
        "SDMOD_LUA_BOTS_ACTIVE",
        "SDMOD_DISABLE_AUDIO",
        "SDMOD_ENABLE_AUDIO",
    })
    os.environ["WSLENV"] = ":".join(sorted(forwarded))
    session = OwnedSoloSession(
        instance=INSTANCE,
        ports=PORTS,
        mod_id=MOD_ID,
        participant_id=PARTICIPANT_ID,
        test_blank_boneyard=False,
        headless=True,
    )
    launch: dict[str, Any] | None = None
    cleanup: list[dict[str, Any]] = []
    document: dict[str, Any] | None = None
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
        offer_bot_id = create_bot(session, name="Progression Offer Bot", x_offset=110.0)
        row_rules = skill_row_rules(session, offer_bot_id)
        offers = capture_offers(session, offer_bot_id, names)
        stock_match = enemy_goldens.start_stock_match(session)
        wait_for_bot_progression(session, offer_bot_id)
        reset_effect_skills(session, offer_bot_id)
        effect_bot_id = offer_bot_id
        local_before_effects = actor_snapshot(session, bot_id=None, skill_ids=())
        progression_bot_before_effects = actor_snapshot(session, bot_id=effect_bot_id)
        effects = capture_skill_effects(session, effect_bot_id, names)
        local_after_effects = actor_snapshot(session, bot_id=None, skill_ids=())
        progression_bot_after_effects = actor_snapshot(session, bot_id=effect_bot_id)
        kills = capture_kill_xp(session)
        isolation = {
            "local_player_before_progression_bot_mutation": local_before_effects,
            "local_player_after_progression_bot_mutation": local_after_effects,
            "progression_bot_before_effect_mutation": progression_bot_before_effects,
            "progression_bot_after_effect_mutation": progression_bot_after_effects,
            "effect_bot_final": actor_snapshot(session, bot_id=effect_bot_id),
        }
        cleanup = session.close()
        require(len(cleanup) == 1, f"cleanup did not stop exactly one owned process: {cleanup}")
        require(launch is not None, "launch provenance was not captured")
        document = build_document(
            source=source,
            launch=launch,
            cleanup=cleanup,
            offer_bot_id=offer_bot_id,
            effect_bot_id=effect_bot_id,
            row_rules=row_rules,
            offers=offers,
            effects=effects,
            stock_match=stock_match,
            kills=kills,
            isolation=isolation,
        )
    finally:
        if session.process_ids:
            session.close()

    require(document is not None, "capture produced no document")
    serialized = json.dumps(document, indent=2, sort_keys=True) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(serialized, encoding="utf-8")
    if args.raw_evidence is not None:
        args.raw_evidence.parent.mkdir(parents=True, exist_ok=True)
        args.raw_evidence.write_text(serialized, encoding="utf-8")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CaptureFailure as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
