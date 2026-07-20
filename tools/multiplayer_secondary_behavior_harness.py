#!/usr/bin/env python3
"""Native behavior witnesses for participant-owned secondary spells."""

from __future__ import annotations

import concurrent.futures
import math
import re
import time
from dataclasses import dataclass
from typing import Any

import multiplayer_defense_behavior_harness as defense
import multiplayer_progression_probe as progression
import verify_multiplayer_focus_behavior_sync as focus
import verify_multiplayer_primary_kill_stress as primary
import verify_multiplayer_rush_behavior_sync as rush
from steam_friend_active_pair import CLIENT_ENDPOINT, HOST_ENDPOINT, SteamFriendActivePair
from verify_local_multiplayer_sync import VerifyFailure, parse_int_text, parse_key_values
from verify_player_health_death_sync import set_local_player_vitals
from verify_real_input_spell_cast_sync import read_log


TARGET_OFFSET_X = 176.0
TARGET_OFFSET_Y = 0.0
TARGET_HP = 10000.0
PLAYER_RESOURCE_MAX = 5000.0
EFFECT_MONITOR_SECONDS = 3.0
TARGET_NATIVE_CELL_STABILITY_SECONDS = 0.6
TARGET_NATIVE_CELL_MINIMUM_SAMPLES = 3
MINIMUM_TRANSIENT_STATUS_OBSERVATION_SECONDS = 2.5
MINIMUM_TRANSIENT_STATUS_COMPARISON_SAMPLES = 2
TRANSIENT_STATUS_CLEAR_PROPAGATION_BUDGET_SECONDS = 2.0
SECONDARY_SKILL_BELT_SLOTS = (0, 1, 2, 5, 6, 7)
NATIVE_TRANSIENT_STATUS_FLAGS = {
    12: 1 << 2,  # Planewalker
    46: 1 << 3,  # Stoneskin
}
NATIVE_TARGET_MODIFIER_TYPES = {
    30: 0x1B76,  # Prismatic Shock
    35: 0x1B6F,  # Ring of Ice
}
MAGIC_SHIELD_ROW = 54
MAGIC_SHIELD_RANK_ONE_ABSORB = 25.0
MAGIC_SHIELD_FIRST_HIT_DAMAGE = 20.0
MAGIC_SHIELD_BREAK_HIT_DAMAGE = 10.0
MAGIC_SHIELD_TOLERANCE = 0.2
TURN_UNDEAD_ROW = 77
TURN_UNDEAD_ELIGIBLE_ACTOR_TYPES = frozenset((1001, 1002, 1003, 1006))
TURN_UNDEAD_DURATION_TOLERANCE_TICKS = 12
TURN_UNDEAD_HEADING_TOLERANCE_DEGREES = 2.0
TURN_UNDEAD_MINIMUM_DISPLACEMENT = 24.0
TURN_UNDEAD_MINIMUM_RADIAL_GAIN = 18.0
TURN_UNDEAD_MAXIMUM_VISUAL_POSITION_ERROR = 32.0


@dataclass(frozen=True)
class SecondarySkillSpec:
    row: int
    name: str
    behavior: str
    target_required: bool = False
    expect_new_actor: bool = False
    synchronized_effect_type: int | None = None


SKILLS = (
    SecondarySkillSpec(11, "Call Leviathan", "summon", True, True),
    SecondarySkillSpec(12, "Planewalker", "self_status"),
    SecondarySkillSpec(15, "Phasing", "phasing"),
    SecondarySkillSpec(21, "Ring of Fire", "area_damage", True),
    SecondarySkillSpec(23, "Firewalker", "persistent"),
    SecondarySkillSpec(27, "Magic Storm", "field", True, True, 0x07F0),
    SecondarySkillSpec(30, "Prismatic Shock", "target_status", True),
    SecondarySkillSpec(35, "Ring of Ice", "target_status", True),
    SecondarySkillSpec(41, "Earthquake", "target_status", True, True),
    SecondarySkillSpec(45, "Raise Golem", "summon", True, True),
    SecondarySkillSpec(46, "Stoneskin", "self_status"),
    SecondarySkillSpec(48, "Teleport", "teleport"),
    SecondarySkillSpec(49, "Magic Circle", "field", False, True),
    SecondarySkillSpec(50, "Magic Trap", "field", True, True),
    SecondarySkillSpec(51, "Dampen", "dampen"),
    SecondarySkillSpec(54, "Magic Shield", "magic_shield"),
    SecondarySkillSpec(72, "Acid Rain", "field", True, True),
    SecondarySkillSpec(73, "Fire Wall", "field", True, True),
    SecondarySkillSpec(74, "Ether Drain", "field", True, True),
    SecondarySkillSpec(76, "Call Comet", "target_damage", True, True),
    SecondarySkillSpec(77, "Turn Undead", "turn_undead", True),
    SecondarySkillSpec(78, "Mindstar", "persistent"),
    SecondarySkillSpec(79, "Regenerate", "persistent"),
)
SKILL_BY_ROW = {skill.row: skill for skill in SKILLS}


ARM_EFFECT_MONITOR_LUA = r"""
local duration_ms = tonumber("__DURATION_MS__") or 3000
local function emit(k,v) print(k .. '=' .. tostring(v)) end
if not _G.__sdmod_secondary_effect_monitor_registered then
  sd.events.on('runtime.tick', function(event)
    local monitor = _G.__sdmod_secondary_effect_monitor
    if type(monitor) ~= 'table' or not monitor.active then return end
    local now = type(event) == 'table' and
      tonumber(event.monotonic_milliseconds) or 0
    if now <= 0 then
      monitor.error = 'runtime.tick monotonic timestamp unavailable'
      monitor.active = false
      monitor.done = true
      return
    end
    if monitor.started_ms == 0 then monitor.started_ms = now end
    local current = {}
    for _, actor in ipairs(sd.world.list_actors and sd.world.list_actors() or {}) do
      local address = tonumber(actor.actor_address) or 0
      if address ~= 0 then
        current[address] = true
        if not monitor.baseline[address] then
          local type_id = tonumber(actor.object_type_id) or 0
          local row = monitor.new_actors[address]
          if row == nil then
            row = {
              type_id = type_id,
              first_x = tonumber(actor.x) or 0,
              first_y = tonumber(actor.y) or 0,
              last_x = tonumber(actor.x) or 0,
              last_y = tonumber(actor.y) or 0,
              observations = 0,
            }
            monitor.new_actors[address] = row
          end
          row.last_x = tonumber(actor.x) or row.last_x
          row.last_y = tonumber(actor.y) or row.last_y
          row.observations = row.observations + 1
          local live = (monitor.live_type_counts[type_id] or 0) + 1
          monitor.live_type_counts[type_id] = live
          monitor.peak_type_counts[type_id] = math.max(
            monitor.peak_type_counts[type_id] or 0,
            live)
        end
      end
    end
    monitor.live_type_counts = {}
    monitor.tick_count = monitor.tick_count + 1
    if now - monitor.started_ms >= monitor.duration_ms then
      monitor.active = false
      monitor.done = true
      monitor.finished_ms = now
    end
  end)
  _G.__sdmod_secondary_effect_monitor_registered = true
end
local baseline = {}
local baseline_count = 0
for _, actor in ipairs(sd.world.list_actors and sd.world.list_actors() or {}) do
  local address = tonumber(actor.actor_address) or 0
  if address ~= 0 then
    baseline[address] = true
    baseline_count = baseline_count + 1
  end
end
_G.__sdmod_secondary_effect_monitor = {
  active = true,
  done = false,
  error = '',
  duration_ms = duration_ms,
  started_ms = 0,
  finished_ms = 0,
  tick_count = 0,
  baseline = baseline,
  new_actors = {},
  live_type_counts = {},
  peak_type_counts = {},
}
emit('armed', true)
emit('baseline_count', baseline_count)
"""


COLLECT_EFFECT_MONITOR_LUA = r"""
local function emit(k,v)
  print(k .. '=' .. tostring(v == nil and '' or v))
end
local monitor = _G.__sdmod_secondary_effect_monitor or {}
emit('active', monitor.active)
emit('done', monitor.done)
emit('error', monitor.error)
emit('tick_count', monitor.tick_count)
local rows = {}
for address, actor in pairs(monitor.new_actors or {}) do
  table.insert(rows, {address=address, actor=actor})
end
table.sort(rows, function(a,b)
  if a.actor.type_id ~= b.actor.type_id then
    return a.actor.type_id < b.actor.type_id
  end
  return a.address < b.address
end)
emit('new_actor_count', #rows)
for index, row in ipairs(rows) do
  local prefix = 'actor.' .. index .. '.'
  emit(prefix .. 'type_id', row.actor.type_id)
  emit(prefix .. 'first_x', row.actor.first_x)
  emit(prefix .. 'first_y', row.actor.first_y)
  emit(prefix .. 'last_x', row.actor.last_x)
  emit(prefix .. 'last_y', row.actor.last_y)
  emit(prefix .. 'observations', row.actor.observations)
end
local types = {}
for type_id, count in pairs(monitor.peak_type_counts or {}) do
  table.insert(types, {type_id=type_id, count=count})
end
table.sort(types, function(a,b) return a.type_id < b.type_id end)
emit('type_count', #types)
for index, row in ipairs(types) do
  emit('type.' .. index .. '.id', row.type_id)
  emit('type.' .. index .. '.peak', row.count)
end
"""


QUERY_EFFECT_TYPE_COUNT_LUA = r"""
local native_type_id = tonumber("__NATIVE_TYPE_ID__") or 0
local function emit(k,v) print(k .. '=' .. tostring(v)) end
local count = 0
for _, actor in ipairs(sd.world.list_actors and sd.world.list_actors() or {}) do
  if (tonumber(actor.object_type_id) or 0) == native_type_id then
    count = count + 1
  end
end
emit('native_type_id', native_type_id)
emit('count', count)
"""


PREPARE_LOCAL_TARGET_LUA = r"""
local target_actor = tonumber("__TARGET_ACTOR__") or 0
local target_x = tonumber("__TARGET_X__") or 0
local target_y = tonumber("__TARGET_Y__") or 0
local function emit(k,v) print(k .. '=' .. tostring(v)) end
local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
local actor = tonumber(player and player.actor_address) or 0
if actor == 0 or target_actor == 0 then
  emit('ok', false)
  return
end
local function off(name) return sd.debug.layout_offset(name) end
local wrote = true
wrote = sd.debug.write_float(actor + off('actor_heading'), 90.0) and wrote
wrote = sd.debug.write_float(actor + off('actor_aim_target_x'), target_x) and wrote
wrote = sd.debug.write_float(actor + off('actor_aim_target_y'), target_y) and wrote
wrote = sd.debug.write_ptr(actor + off('actor_current_target_actor'), target_actor) and wrote
local aux0 = off('actor_aim_target_aux0')
local aux1 = off('actor_aim_target_aux1')
if aux0 ~= nil then wrote = sd.debug.write_u32(actor + aux0, 0) and wrote end
if aux1 ~= nil then wrote = sd.debug.write_u32(actor + aux1, 0) and wrote end
emit('ok', wrote)
emit('player_x', player.x)
emit('player_y', player.y)
emit('target_x', target_x)
emit('target_y', target_y)
"""


REBIND_TARGET_NATIVE_SPATIAL_LUA = r"""
local network_actor_id = tonumber("__NETWORK_ACTOR_ID__") or 0
local function emit(k,v) print(k .. '=' .. tostring(v)) end
local target = sd.world and sd.world.get_run_enemy_by_network_id and
  sd.world.get_run_enemy_by_network_id(network_actor_id) or nil
local actor = tonumber(target and target.actor_address) or 0
local cell_offset = sd.debug.layout_offset('actor_grid_cell_ptr')
local x_offset = sd.debug.layout_offset('actor_position_x')
local y_offset = sd.debug.layout_offset('actor_position_y')
local rebind_ok = false
local rebind_error = ''
if actor ~= 0 and cell_offset ~= nil and sd.world.rebind_actor ~= nil then
  rebind_ok, rebind_error = sd.world.rebind_actor(actor)
end
emit('ok', rebind_ok == true)
emit('error', rebind_error or '')
emit('actor', string.format('0x%08X', actor))
emit('cell', string.format(
  '0x%08X',
  actor ~= 0 and cell_offset ~= nil and
    (tonumber(sd.debug.read_ptr(actor + cell_offset)) or 0) or 0))
emit('x', actor ~= 0 and x_offset ~= nil and
  (tonumber(sd.debug.read_float(actor + x_offset)) or 0) or 0)
emit('y', actor ~= 0 and y_offset ~= nil and
  (tonumber(sd.debug.read_float(actor + y_offset)) or 0) or 0)
"""


QUERY_TARGET_NATIVE_SPATIAL_LUA = r"""
local network_actor_id = tonumber("__NETWORK_ACTOR_ID__") or 0
local function emit(k,v) print(k .. '=' .. tostring(v)) end
local target = sd.world and sd.world.get_run_enemy_by_network_id and
  sd.world.get_run_enemy_by_network_id(network_actor_id) or nil
local actor = tonumber(target and target.actor_address) or 0
local cell_offset = sd.debug.layout_offset('actor_grid_cell_ptr')
local x_offset = sd.debug.layout_offset('actor_position_x')
local y_offset = sd.debug.layout_offset('actor_position_y')
emit('found', target ~= nil and actor ~= 0)
emit('actor', string.format('0x%08X', actor))
emit('cell', string.format(
  '0x%08X',
  actor ~= 0 and cell_offset ~= nil and
    (tonumber(sd.debug.read_ptr(actor + cell_offset)) or 0) or 0))
emit('x', actor ~= 0 and x_offset ~= nil and
  (tonumber(sd.debug.read_float(actor + x_offset)) or 0) or 0)
emit('y', actor ~= 0 and y_offset ~= nil and
  (tonumber(sd.debug.read_float(actor + y_offset)) or 0) or 0)
"""


PLAYER_VITALS_LUA = r"""
local participant_id = tonumber("__PARTICIPANT_ID__") or 0
local function emit(k,v) print(k .. '=' .. tostring(v)) end
local state = nil
local replicated_persistent = 0
local native_persistent = 0
local replicated_transient = 0
local native_transient = 0
local replicated_shield_remaining = 0
local replicated_shield_capacity = 0
local replicated_shield_explosion_fraction = 0
local replicated_shield_hit_flash = 0
local native_shield_remaining = 0
local native_shield_capacity = 0
local native_shield_explosion_fraction = 0
local native_shield_hit_flash = 0
if participant_id == 0 then
  state = sd.player and sd.player.get_state and sd.player.get_state() or nil
  replicated_persistent = state and state.persistent_status_flags or 0
  native_persistent = replicated_persistent
  replicated_transient = state and state.transient_status_flags or 0
  native_transient = replicated_transient
  replicated_shield_remaining = state and state.magic_shield_absorb_remaining or 0
  replicated_shield_capacity = state and state.magic_shield_absorb_capacity or 0
  replicated_shield_explosion_fraction = state and state.magic_shield_explosion_fraction or 0
  replicated_shield_hit_flash = state and state.magic_shield_hit_flash or 0
  native_shield_remaining = replicated_shield_remaining
  native_shield_capacity = replicated_shield_capacity
  native_shield_explosion_fraction = replicated_shield_explosion_fraction
  native_shield_hit_flash = replicated_shield_hit_flash
else
  state = sd.bots and sd.bots.get_participant_state and
    sd.bots.get_participant_state(participant_id) or nil
  replicated_persistent = state and
    state.replicated_persistent_status_flags or 0
  native_persistent = state and state.native_persistent_status_flags or 0
  replicated_transient = state and
    state.replicated_transient_status_flags or 0
  native_transient = state and state.native_transient_status_flags or 0
  replicated_shield_remaining = state and
    state.replicated_magic_shield_absorb_remaining or 0
  replicated_shield_capacity = state and
    state.replicated_magic_shield_absorb_capacity or 0
  replicated_shield_explosion_fraction = state and
    state.replicated_magic_shield_explosion_fraction or 0
  replicated_shield_hit_flash = state and
    state.replicated_magic_shield_hit_flash or 0
  native_shield_remaining = state and state.magic_shield_absorb_remaining or 0
  native_shield_capacity = state and state.magic_shield_absorb_capacity or 0
  native_shield_explosion_fraction = state and
    state.magic_shield_explosion_fraction or 0
  native_shield_hit_flash = state and state.magic_shield_hit_flash or 0
end
emit('available', state ~= nil)
emit('x', state and state.x or 0)
emit('y', state and state.y or 0)
emit('heading', state and state.heading or 0)
emit('hp', state and state.hp or 0)
emit('max_hp', state and state.max_hp or 0)
emit('mp', state and state.mp or 0)
emit('max_mp', state and state.max_mp or 0)
emit('persistent_status_flags', replicated_persistent)
emit('native_persistent_status_flags', native_persistent)
emit('transient_status_flags', replicated_transient)
emit('native_transient_status_flags', native_transient)
emit('magic_shield_absorb_remaining', replicated_shield_remaining)
emit('magic_shield_absorb_capacity', replicated_shield_capacity)
emit('magic_shield_explosion_fraction', replicated_shield_explosion_fraction)
emit('magic_shield_hit_flash', replicated_shield_hit_flash)
emit('native_magic_shield_absorb_remaining', native_shield_remaining)
emit('native_magic_shield_absorb_capacity', native_shield_capacity)
emit('native_magic_shield_explosion_fraction', native_shield_explosion_fraction)
emit('native_magic_shield_hit_flash', native_shield_hit_flash)
emit('render_drive_flags', state and state.render_drive_flags or 0)
"""


ARM_LOCAL_MANA_OBSERVATION_LUA = r"""
local armed = sd.debug.reset_local_cast_observation(1)
print('armed=' .. tostring(armed))
"""


TAKE_LOCAL_MANA_OBSERVATION_LUA = r"""
local function emit(k,v) print(k .. '=' .. tostring(v)) end
local observation = sd.debug.get_local_cast_observation(1)
emit('valid', observation and observation.mana_valid or false)
emit('call_count', observation and observation.mana_call_count or 0)
emit('spend_call_count', observation and
  observation.mana_spend_call_count or 0)
emit('recovery_call_count', observation and
  observation.mana_recovery_call_count or 0)
emit('spent_total', observation and observation.mana_spent_total or 0)
emit('recovered_total', observation and
  observation.mana_recovered_total or 0)
emit('last_delta', observation and observation.mana_last_delta or 0)
"""


QUERY_ACTOR_MODIFIERS_LUA = r"""
local actor = tonumber("__ACTOR__") or 0
local function emit(k,v) print(k .. '=' .. tostring(v)) end
local modifiers = sd.debug.get_actor_modifiers(actor)
emit('available', type(modifiers) == 'table')
if type(modifiers) ~= 'table' then return end
emit('count', #modifiers)
for index, modifier in ipairs(modifiers) do
  emit('modifier.' .. index .. '.type_id', modifier.type_id or 0)
  emit('modifier.' .. index .. '.duration_ticks',
    modifier.duration_ticks or 0)
end
"""


QUERY_TURN_UNDEAD_STATE_LUA = r"""
local network_actor_id = tonumber("__NETWORK_ID__") or 0
local function emit(k,v) print(k .. '=' .. tostring(v)) end
local actor = sd.world.get_run_enemy_by_network_id and
  sd.world.get_run_enemy_by_network_id(network_actor_id) or nil
emit('available', actor ~= nil)
if actor == nil then return end
local address = tonumber(actor.actor_address) or 0
local heading_offset = sd.debug.layout_offset('actor_heading')
local flee_heading_offset =
  sd.debug.layout_offset('actor_turn_undead_flee_heading')
local activation_scalar_offset =
  sd.debug.layout_offset('actor_turn_undead_activation_scalar')
local duration_offset =
  sd.debug.layout_offset('actor_turn_undead_duration_ticks')
local layout_available = address ~= 0 and heading_offset ~= nil and
  flee_heading_offset ~= nil and activation_scalar_offset ~= nil and
  duration_offset ~= nil
emit('layout_available', layout_available)
if not layout_available then return end
local function read_float(offset)
  local ok, value = pcall(sd.debug.read_float, address + offset)
  if not ok then return nil end
  return tonumber(value)
end
local function read_i32(offset)
  local ok, value = pcall(sd.debug.read_i32, address + offset)
  if not ok then return nil end
  return tonumber(value)
end
local heading = read_float(heading_offset)
local flee_heading = read_float(flee_heading_offset)
local activation_scalar = read_float(activation_scalar_offset)
local duration_ticks = read_i32(duration_offset)
local readable = heading ~= nil and flee_heading ~= nil and
  activation_scalar ~= nil and duration_ticks ~= nil
emit('readable', readable)
if not readable then return end
emit('object_type_id', actor.object_type_id or 0)
emit('x', string.format('%.3f', tonumber(actor.x) or 0))
emit('y', string.format('%.3f', tonumber(actor.y) or 0))
emit('heading', string.format('%.3f', heading))
emit('flee_heading', string.format('%.3f', flee_heading))
emit('activation_scalar', string.format('%.6f', activation_scalar))
emit('duration_ticks', duration_ticks)
emit('dead', actor.dead or false)
emit('tracked', actor.tracked_enemy or false)
"""


CLEAR_MANUAL_TARGET_FREEZE_LUA = r"""
local actor = tonumber("__ACTOR__") or 0
local function emit(k,v) print(k .. '=' .. tostring(v)) end
emit('ok', sd.gameplay.clear_manual_run_enemy_freeze(actor))
"""


def observer_endpoint(direction: focus.Direction) -> str:
    return CLIENT_ENDPOINT if direction.source_pipe == HOST_ENDPOINT else HOST_ENDPOINT


def _float(values: dict[str, str], key: str) -> float:
    try:
        return float(values.get(key, "nan"))
    except ValueError:
        return math.nan


def query_vitals(
    pair: SteamFriendActivePair,
    endpoint: str,
    participant_id: int = 0,
) -> dict[str, Any]:
    values = parse_key_values(
        pair.lua(
            endpoint,
            PLAYER_VITALS_LUA.replace(
                "__PARTICIPANT_ID__",
                str(participant_id),
            ),
            timeout=8.0,
        )
    )
    if values.get("available") != "true":
        raise VerifyFailure(
            f"secondary behavior vitals unavailable on {endpoint}"
        )
    return {
        "x": _float(values, "x"),
        "y": _float(values, "y"),
        "heading": _float(values, "heading"),
        "hp": _float(values, "hp"),
        "max_hp": _float(values, "max_hp"),
        "mp": _float(values, "mp"),
        "max_mp": _float(values, "max_mp"),
        "persistent_status_flags": parse_int_text(
            values.get("persistent_status_flags"), 0
        ),
        "native_persistent_status_flags": parse_int_text(
            values.get("native_persistent_status_flags"), 0
        ),
        "transient_status_flags": parse_int_text(
            values.get("transient_status_flags"), 0
        ),
        "native_transient_status_flags": parse_int_text(
            values.get("native_transient_status_flags"), 0
        ),
        "magic_shield_absorb_remaining": _float(
            values, "magic_shield_absorb_remaining"
        ),
        "magic_shield_absorb_capacity": _float(
            values, "magic_shield_absorb_capacity"
        ),
        "magic_shield_explosion_fraction": _float(
            values, "magic_shield_explosion_fraction"
        ),
        "magic_shield_hit_flash": _float(
            values, "magic_shield_hit_flash"
        ),
        "native_magic_shield_absorb_remaining": _float(
            values, "native_magic_shield_absorb_remaining"
        ),
        "native_magic_shield_absorb_capacity": _float(
            values, "native_magic_shield_absorb_capacity"
        ),
        "native_magic_shield_explosion_fraction": _float(
            values, "native_magic_shield_explosion_fraction"
        ),
        "native_magic_shield_hit_flash": _float(
            values, "native_magic_shield_hit_flash"
        ),
        "render_drive_flags": parse_int_text(
            values.get("render_drive_flags"), 0
        ),
    }


def arm_local_mana_observation(
    pair: SteamFriendActivePair,
    endpoint: str,
) -> dict[str, str]:
    values = parse_key_values(
        pair.lua(endpoint, ARM_LOCAL_MANA_OBSERVATION_LUA, timeout=8.0)
    )
    if values.get("armed") != "true":
        raise VerifyFailure(
            f"local native mana observation failed to arm on {endpoint}"
        )
    return values


def take_local_mana_observation(
    pair: SteamFriendActivePair,
    endpoint: str,
) -> dict[str, Any]:
    values = parse_key_values(
        pair.lua(endpoint, TAKE_LOCAL_MANA_OBSERVATION_LUA, timeout=8.0)
    )
    return {
        "valid": values.get("valid") == "true",
        "call_count": parse_int_text(values.get("call_count"), 0),
        "spend_call_count": parse_int_text(
            values.get("spend_call_count"), 0
        ),
        "recovery_call_count": parse_int_text(
            values.get("recovery_call_count"), 0
        ),
        "spent_total": _float(values, "spent_total"),
        "recovered_total": _float(values, "recovered_total"),
        "last_delta": _float(values, "last_delta"),
    }


def arm_effect_monitor(
    pair: SteamFriendActivePair,
    endpoint: str,
) -> dict[str, str]:
    values = parse_key_values(
        pair.lua(
            endpoint,
            ARM_EFFECT_MONITOR_LUA.replace(
                "__DURATION_MS__",
                str(round(EFFECT_MONITOR_SECONDS * 1000.0)),
            ),
            timeout=8.0,
        )
    )
    if values.get("armed") != "true":
        raise VerifyFailure(f"secondary effect monitor failed to arm: {values}")
    return values


def collect_effect_monitor(
    pair: SteamFriendActivePair,
    endpoint: str,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    values: dict[str, str] = {}
    while time.monotonic() < deadline:
        values = parse_key_values(
            pair.lua(endpoint, COLLECT_EFFECT_MONITOR_LUA, timeout=8.0)
        )
        if values.get("error"):
            raise VerifyFailure(
                f"secondary effect monitor failed on {endpoint}: {values}"
            )
        if values.get("done") == "true":
            break
        time.sleep(0.08)
    else:
        raise VerifyFailure(
            f"secondary effect monitor timed out on {endpoint}: {values}"
        )

    actor_count = parse_int_text(values.get("new_actor_count"), 0)
    type_count = parse_int_text(values.get("type_count"), 0)
    actors = [
        {
            "type_id": parse_int_text(values.get(f"actor.{index}.type_id"), 0),
            "first_x": _float(values, f"actor.{index}.first_x"),
            "first_y": _float(values, f"actor.{index}.first_y"),
            "last_x": _float(values, f"actor.{index}.last_x"),
            "last_y": _float(values, f"actor.{index}.last_y"),
            "observations": parse_int_text(
                values.get(f"actor.{index}.observations"), 0
            ),
        }
        for index in range(1, actor_count + 1)
    ]
    type_peaks = {
        parse_int_text(values.get(f"type.{index}.id"), 0): parse_int_text(
            values.get(f"type.{index}.peak"), 0
        )
        for index in range(1, type_count + 1)
    }
    return {
        "tick_count": parse_int_text(values.get("tick_count"), 0),
        "new_actor_count": actor_count,
        "actors": actors,
        "type_peaks": type_peaks,
    }


def arm_effect_monitors(
    pair: SteamFriendActivePair,
    direction: focus.Direction,
) -> dict[str, dict[str, str]]:
    endpoints = {
        "owner": direction.source_pipe,
        "observer": observer_endpoint(direction),
    }
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            label: executor.submit(arm_effect_monitor, pair, endpoint)
            for label, endpoint in endpoints.items()
        }
        return {label: future.result() for label, future in futures.items()}


def collect_effect_monitors(
    pair: SteamFriendActivePair,
    direction: focus.Direction,
    timeout: float,
) -> dict[str, dict[str, Any]]:
    endpoints = {
        "owner": direction.source_pipe,
        "observer": observer_endpoint(direction),
    }
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            label: executor.submit(
                collect_effect_monitor,
                pair,
                endpoint,
                timeout,
            )
            for label, endpoint in endpoints.items()
        }
        return {label: future.result() for label, future in futures.items()}


def wait_for_effect_type_absent(
    pair: SteamFriendActivePair,
    native_type_id: int,
    timeout: float,
    stable_seconds: float = 0.5,
) -> dict[str, Any]:
    endpoints = {
        "host": HOST_ENDPOINT,
        "client": CLIENT_ENDPOINT,
    }
    code = QUERY_EFFECT_TYPE_COUNT_LUA.replace(
        "__NATIVE_TYPE_ID__", str(native_type_id)
    )
    started = time.monotonic()
    deadline = started + timeout
    stable_since: float | None = None
    sample_count = 0
    last: dict[str, dict[str, Any]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        while time.monotonic() < deadline:
            futures = {
                label: executor.submit(pair.lua, endpoint, code, timeout=8.0)
                for label, endpoint in endpoints.items()
            }
            last = {
                label: {
                    **parse_key_values(future.result()),
                }
                for label, future in futures.items()
            }
            sample_count += 1
            absent = all(
                parse_int_text(sample.get("count"), -1) == 0
                for sample in last.values()
            )
            now = time.monotonic()
            if absent:
                if stable_since is None:
                    stable_since = now
                elif now - stable_since >= stable_seconds:
                    return {
                        "native_type_id": native_type_id,
                        "stable_seconds": now - stable_since,
                        "elapsed_seconds": now - started,
                        "sample_count": sample_count,
                        "last": last,
                    }
            else:
                stable_since = None
            time.sleep(0.08)
    raise VerifyFailure(
        f"effect type 0x{native_type_id:X} did not retire on both peers "
        f"before the next behavior case: last={last}"
    )


def verify_synchronized_effect_positions(
    direction: focus.Direction,
    skill: SecondarySkillSpec,
    effects: dict[str, dict[str, Any]],
    tolerance: float = 2.0,
) -> dict[str, Any] | None:
    effect_type = skill.synchronized_effect_type
    if effect_type is None:
        return None

    owner_actors = [
        actor
        for actor in effects["owner"]["actors"]
        if actor["type_id"] == effect_type
    ]
    observer_actors = [
        actor
        for actor in effects["observer"]["actors"]
        if actor["type_id"] == effect_type
    ]
    if not owner_actors or not observer_actors:
        raise VerifyFailure(
            f"{direction.name} {skill.name} did not materialize synchronized "
            f"effect type 0x{effect_type:X} on both peers: effects={effects}"
        )

    unmatched_observers = list(observer_actors)
    matches: list[dict[str, Any]] = []
    for owner in owner_actors:
        best = min(
            unmatched_observers,
            key=lambda observer: math.hypot(
                owner["last_x"] - observer["last_x"],
                owner["last_y"] - observer["last_y"],
            ),
            default=None,
        )
        if best is None:
            raise VerifyFailure(
                f"{direction.name} {skill.name} observer is missing an owner "
                f"effect type 0x{effect_type:X}: effects={effects}"
            )
        unmatched_observers.remove(best)
        position_error = math.hypot(
            owner["last_x"] - best["last_x"],
            owner["last_y"] - best["last_y"],
        )
        matches.append(
            {
                "owner": owner,
                "observer": best,
                "position_error": position_error,
            }
        )

    maximum_position_error = max(
        match["position_error"] for match in matches
    )
    if maximum_position_error > tolerance:
        raise VerifyFailure(
            f"{direction.name} {skill.name} effect position diverged by "
            f"{maximum_position_error:.3f}: matches={matches}"
        )
    return {
        "native_type_id": effect_type,
        "tolerance": tolerance,
        "maximum_position_error": maximum_position_error,
        "matches": matches,
    }


def wait_for_secondary_delivery(
    direction: focus.Direction,
    row: int,
    belt_slot: int,
    source_offset: int,
    observer_offset: int,
    timeout: float,
) -> dict[str, int]:
    local_token = (
        "Multiplayer local secondary cast queued from native dispatcher."
    )
    replay_token = "[bots] remote native secondary cast replayed."
    deadline = time.monotonic() + timeout
    local_count = 0
    replay_count = 0
    mouse_right_injection_count = 0
    keyboard_edge_count = 0
    while time.monotonic() < deadline:
        local_log = read_log(direction.source_log)[source_offset:]
        observer_log = read_log(direction.observer_log)[observer_offset:]
        local_count = sum(
            local_token in line and f"skill_entry={row}" in line
            for line in local_log.splitlines()
        )
        replay_count = sum(
            replay_token in line
            and f"skill_entry={row}" in line
            and "success=1" in line
            for line in observer_log.splitlines()
        )
        mouse_right_injection_count = local_log.count(
            "Injected gameplay mouse-right click."
        )
        keyboard_edge_count = local_log.count(
            "Consumed queued gameplay keyboard edge."
        )
        input_witnessed = (
            mouse_right_injection_count >= 1
            if belt_slot == 0
            else keyboard_edge_count >= 1
        )
        if local_count >= 1 and replay_count >= 1 and input_witnessed:
            return {
                "local_accept_count": local_count,
                "remote_replay_success_count": replay_count,
                "native_mouse_right_injection_count": (
                    mouse_right_injection_count
                ),
                "native_keyboard_edge_count": keyboard_edge_count,
            }
        time.sleep(0.05)
    raise VerifyFailure(
        f"{direction.name} secondary row {row} did not complete native replay: "
        f"local={local_count} remote={replay_count} "
        f"mouse_right={mouse_right_injection_count} "
        f"keyboard={keyboard_edge_count} belt_slot={belt_slot}"
    )


DAMPEN_APPLICATION_PATTERN = re.compile(
    r"Multiplayer Dampen behavior applied\. .*?"
    r"cast_sequence=(?P<cast_sequence>\d+) "
    r"position=\((?P<x>[-+0-9.eE]+),(?P<y>[-+0-9.eE]+)\) .*?"
    r"authority_instance=(?P<authority_instance>[01]) .*?"
    r"scene_actor_count=(?P<scene_actor_count>\d+) .*?"
    r"actors_in_radius=(?P<actors_in_radius>\d+) .*?"
    r"projectiles_repelled=(?P<projectiles_repelled>\d+) .*?"
    r"mages_disrupted=(?P<mages_disrupted>\d+) .*?"
    r"shields_dispelled=(?P<shields_dispelled>\d+)"
)
DAMPEN_DISPATCH_TOKEN = (
    "Multiplayer stock Dampen effect block suppressed; native dispatcher "
    "completed. success=1"
)
DAMPEN_PRESENTATION_PATTERN = re.compile(
    r"Multiplayer Dampen DX9 presentation drawn\. .*?success=1"
)
DAMPEN_SHARED_VIEW_OFFSET_X = 160.0


def prepare_dampen_shared_view_geometry(
    direction: focus.Direction,
    timeout: float,
) -> dict[str, Any]:
    """Place both real players close enough to witness the world-space pulse."""
    owner_direction_index = (
        0 if direction.source_pipe == HOST_ENDPOINT else 1
    )
    owner_rush = rush.DIRECTIONS[owner_direction_index]
    observer_rush = rush.DIRECTIONS[1 - owner_direction_index]

    observer_placement = rush.place_player(
        owner_rush.other_pipe,
        rush.START_X + DAMPEN_SHARED_VIEW_OFFSET_X,
        rush.START_Y,
        180.0,
    )
    owner_placement = rush.place_player(
        owner_rush.owner_pipe,
        rush.START_X,
        rush.START_Y,
        0.0,
    )
    owner_transform = rush.wait_for_local_transform_settled(
        owner_rush.owner_pipe,
        timeout=min(timeout, 10.0),
        stable_seconds=0.35,
    )
    observer_transform = rush.wait_for_local_transform_settled(
        owner_rush.other_pipe,
        timeout=min(timeout, 10.0),
        stable_seconds=0.35,
    )
    owner_on_observer = rush.wait_for_remote_convergence(
        owner_rush.observer_pipe,
        owner_rush.participant_id,
        *owner_transform,
        timeout=timeout,
    )
    observer_on_owner = rush.wait_for_remote_convergence(
        observer_rush.observer_pipe,
        observer_rush.participant_id,
        *observer_transform,
        timeout=timeout,
    )

    separation = math.hypot(
        owner_transform[0] - observer_transform[0],
        owner_transform[1] - observer_transform[1],
    )
    if separation > DAMPEN_SHARED_VIEW_OFFSET_X + 2.0:
        raise VerifyFailure(
            f"{direction.name} Dampen shared-view geometry diverged: "
            f"owner={owner_transform} observer={observer_transform}"
        )
    return {
        "owner_placement": owner_placement,
        "observer_placement": observer_placement,
        "owner_transform": owner_transform,
        "observer_transform": observer_transform,
        "owner_on_observer": owner_on_observer,
        "observer_on_owner": observer_on_owner,
        "separation": separation,
    }


def _latest_dampen_application(log_text: str) -> dict[str, Any] | None:
    matches = list(DAMPEN_APPLICATION_PATTERN.finditer(log_text))
    if not matches:
        return None
    fields = matches[-1].groupdict()
    return {
        "cast_sequence": int(fields["cast_sequence"]),
        "x": float(fields["x"]),
        "y": float(fields["y"]),
        "authority_instance": int(fields["authority_instance"]),
        "scene_actor_count": int(fields["scene_actor_count"]),
        "actors_in_radius": int(fields["actors_in_radius"]),
        "projectiles_repelled": int(fields["projectiles_repelled"]),
        "mages_disrupted": int(fields["mages_disrupted"]),
        "shields_dispelled": int(fields["shields_dispelled"]),
    }


def wait_for_dampen_application(
    direction: focus.Direction,
    source_offset: int,
    observer_offset: int,
    expected_x: float,
    expected_y: float,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        source_log = read_log(direction.source_log)[source_offset:]
        observer_log = read_log(direction.observer_log)[observer_offset:]
        source = _latest_dampen_application(source_log)
        observer = _latest_dampen_application(observer_log)
        source_dispatch_count = source_log.count(DAMPEN_DISPATCH_TOKEN)
        observer_dispatch_count = observer_log.count(DAMPEN_DISPATCH_TOKEN)
        source_presentation_count = len(
            DAMPEN_PRESENTATION_PATTERN.findall(source_log)
        )
        observer_presentation_count = len(
            DAMPEN_PRESENTATION_PATTERN.findall(observer_log)
        )
        last = {
            "owner": source,
            "observer": observer,
            "owner_native_dispatch_count": source_dispatch_count,
            "observer_native_dispatch_count": observer_dispatch_count,
            "owner_presentation_count": source_presentation_count,
            "observer_presentation_count": observer_presentation_count,
        }
        if (
            source is not None
            and observer is not None
            and source_dispatch_count >= 1
            and observer_dispatch_count >= 1
            and source_presentation_count >= 1
            and observer_presentation_count >= 1
        ):
            if source["cast_sequence"] != observer["cast_sequence"]:
                raise VerifyFailure(
                    f"{direction.name} Dampen behavior used different cast "
                    f"sequences: {last}"
                )
            if {
                source["authority_instance"],
                observer["authority_instance"],
            } != {0, 1}:
                raise VerifyFailure(
                    f"{direction.name} Dampen did not execute once per Steam "
                    f"authority role: {last}"
                )
            position_error = max(
                math.hypot(source["x"] - expected_x, source["y"] - expected_y),
                math.hypot(
                    observer["x"] - expected_x,
                    observer["y"] - expected_y,
                ),
                math.hypot(
                    source["x"] - observer["x"],
                    source["y"] - observer["y"],
                ),
            )
            outcomes = (
                "projectiles_repelled",
                "mages_disrupted",
                "shields_dispelled",
            )
            mismatches = {
                key: {
                    "owner": source[key],
                    "observer": observer[key],
                }
                for key in outcomes
                if source[key] != observer[key]
            }
            if position_error > 2.0 or mismatches:
                raise VerifyFailure(
                    f"{direction.name} Dampen behavior diverged: "
                    f"position_error={position_error} "
                    f"outcome_mismatches={mismatches}"
                )
            last["position_error"] = position_error
            last["outcome_mismatches"] = mismatches
            return last
        time.sleep(0.05)
    raise VerifyFailure(
        f"{direction.name} Dampen did not produce matching native dispatch, "
        f"DX9 presentation, and deterministic behavior on both peers: {last}"
    )


def acquire_skill(
    direction: focus.Direction,
    row: int,
    timeout: float,
) -> dict[str, Any]:
    return focus.acquire_secondary_to_rank(direction, row, 1, timeout)


def ensure_batch_capacity(
    directions: tuple[focus.Direction, focus.Direction],
    rows: list[int],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for direction in directions:
        snapshot = progression.query_progression_snapshot(direction.source_pipe)
        belt = snapshot["loadout"]["secondary_entry_indices"]
        missing = [row for row in rows if row not in belt]
        free_slots = [
            slot
            for slot in SECONDARY_SKILL_BELT_SLOTS
            if belt[slot] == -1
        ]
        free = len(free_slots)
        if len(missing) > free:
            raise VerifyFailure(
                f"{direction.name} secondary batch needs {len(missing)} belt "
                f"slots but only {free} are free: belt={belt} rows={rows}"
            )
        result[direction.name] = {
            "belt_before": belt,
            "missing_rows": missing,
            "free_slots": free,
            "free_skill_belt_slots": free_slots,
        }
    return result


def query_target_state(endpoint: str, network_id: int) -> dict[str, Any]:
    values = primary.query_run_enemy_by_network_id(endpoint, network_id)
    return {
        "found": values.get("found") == "true",
        "dead": values.get("dead") == "true",
        "tracked": values.get("tracked") == "true",
        "hp": _float(values, "hp"),
        "max_hp": _float(values, "max_hp"),
        "x": _float(values, "x"),
        "y": _float(values, "y"),
    }


def _heading_error_degrees(left: float, right: float) -> float:
    return abs((left - right + 180.0) % 360.0 - 180.0)


def query_turn_undead_state(
    pair: SteamFriendActivePair,
    endpoint: str,
    network_id: int,
) -> dict[str, Any]:
    values = parse_key_values(
        pair.lua(
            endpoint,
            QUERY_TURN_UNDEAD_STATE_LUA.replace(
                "__NETWORK_ID__",
                str(network_id),
            ),
            timeout=8.0,
        )
    )
    return {
        "available": values.get("available") == "true",
        "layout_available": values.get("layout_available") == "true",
        "readable": values.get("readable") == "true",
        "object_type_id": parse_int_text(values.get("object_type_id"), 0),
        "x": _float(values, "x"),
        "y": _float(values, "y"),
        "heading": _float(values, "heading"),
        "flee_heading": _float(values, "flee_heading"),
        "activation_scalar": _float(values, "activation_scalar"),
        "duration_ticks": parse_int_text(values.get("duration_ticks"), 0),
        "dead": values.get("dead") == "true",
        "tracked": values.get("tracked") == "true",
    }


def query_turn_undead_pair(
    pair: SteamFriendActivePair,
    network_id: int,
) -> dict[str, dict[str, Any]]:
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        host_future = executor.submit(
            query_turn_undead_state,
            pair,
            HOST_ENDPOINT,
            network_id,
        )
        client_future = executor.submit(
            query_turn_undead_state,
            pair,
            CLIENT_ENDPOINT,
            network_id,
        )
        return {
            "host": host_future.result(),
            "client": client_future.result(),
        }


def require_turn_undead_baseline(
    pair: SteamFriendActivePair,
    network_id: int,
) -> dict[str, Any]:
    states = query_turn_undead_pair(pair, network_id)
    host = states["host"]
    client = states["client"]
    for label, state in states.items():
        if (
            not state["available"]
            or not state["layout_available"]
            or not state["readable"]
            or not state["tracked"]
            or state["dead"]
        ):
            raise VerifyFailure(
                f"Turn Undead baseline unavailable on {label}: {state}"
            )
        if state["object_type_id"] not in TURN_UNDEAD_ELIGIBLE_ACTOR_TYPES:
            raise VerifyFailure(
                f"Turn Undead target type is not in the stock eligible "
                f"family on {label}: {state}"
            )
        if state["duration_ticks"] > 0:
            raise VerifyFailure(
                f"Turn Undead target began active on {label}: {state}"
            )
        if not all(
            math.isfinite(float(state[key]))
            for key in ("x", "y", "heading", "flee_heading", "activation_scalar")
        ):
            raise VerifyFailure(
                f"Turn Undead baseline contained non-finite state on "
                f"{label}: {state}"
            )
    if host["object_type_id"] != client["object_type_id"]:
        raise VerifyFailure(
            f"Turn Undead target native type diverged: {states}"
        )
    position_error = math.hypot(
        host["x"] - client["x"],
        host["y"] - client["y"],
    )
    if position_error > TURN_UNDEAD_MAXIMUM_VISUAL_POSITION_ERROR:
        raise VerifyFailure(
            f"Turn Undead target baseline position diverged by "
            f"{position_error}: {states}"
        )
    return {"states": states, "position_error": position_error}


def wait_for_turn_undead_activation(
    pair: SteamFriendActivePair,
    network_id: int,
    timeout: float,
) -> dict[str, Any]:
    started = time.monotonic()
    deadline = started + timeout
    samples = 0
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        states = query_turn_undead_pair(pair, network_id)
        samples += 1
        host = states["host"]
        client = states["client"]
        duration_error = abs(
            int(host["duration_ticks"]) - int(client["duration_ticks"])
        )
        flee_heading_error = _heading_error_degrees(
            float(host["flee_heading"]),
            float(client["flee_heading"]),
        )
        scalar_error = abs(
            float(host["activation_scalar"])
            - float(client["activation_scalar"])
        )
        scalar_tolerance = max(
            0.02,
            0.02
            * max(
                abs(float(host["activation_scalar"])),
                abs(float(client["activation_scalar"])),
            ),
        )
        position_error = math.hypot(
            float(host["x"]) - float(client["x"]),
            float(host["y"]) - float(client["y"]),
        )
        last = {
            "states": states,
            "duration_error_ticks": duration_error,
            "flee_heading_error_degrees": flee_heading_error,
            "activation_scalar_error": scalar_error,
            "activation_scalar_tolerance": scalar_tolerance,
            "position_error": position_error,
            "samples": samples,
            "elapsed_seconds": time.monotonic() - started,
        }
        if (
            all(
                state["available"]
                and state["layout_available"]
                and state["readable"]
                and state["tracked"]
                and not state["dead"]
                and state["object_type_id"]
                in TURN_UNDEAD_ELIGIBLE_ACTOR_TYPES
                and state["duration_ticks"] > 0
                for state in states.values()
            )
            and duration_error <= TURN_UNDEAD_DURATION_TOLERANCE_TICKS
            and flee_heading_error
            <= TURN_UNDEAD_HEADING_TOLERANCE_DEGREES
            and scalar_error <= scalar_tolerance
        ):
            return last
        time.sleep(0.03)
    raise VerifyFailure(
        "Turn Undead did not establish matching native flee state on both "
        f"peers: {last}"
    )


def clear_turn_undead_target_freeze(
    pair: SteamFriendActivePair,
    host_actor_address: int,
) -> dict[str, str]:
    values = parse_key_values(
        pair.lua(
            HOST_ENDPOINT,
            CLEAR_MANUAL_TARGET_FREEZE_LUA.replace(
                "__ACTOR__",
                str(host_actor_address),
            ),
            timeout=8.0,
        )
    )
    if values.get("ok") != "true":
        raise VerifyFailure(
            f"Turn Undead target freeze did not clear: {values}"
        )
    return values


def wait_for_turn_undead_flee(
    pair: SteamFriendActivePair,
    target: dict[str, Any],
    activation: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    network_id = int(target["network_id"])
    caster_x = float(target["owner_transform"][0])
    caster_y = float(target["owner_transform"][1])
    initial_host_x = float(activation["states"]["host"]["x"])
    initial_host_y = float(activation["states"]["host"]["y"])
    initial_client_x = float(activation["states"]["client"]["x"])
    initial_client_y = float(activation["states"]["client"]["y"])
    initial_host_radius = math.hypot(
        initial_host_x - caster_x,
        initial_host_y - caster_y,
    )
    initial_client_radius = math.hypot(
        initial_client_x - caster_x,
        initial_client_y - caster_y,
    )
    started = time.monotonic()
    deadline = started + timeout
    samples = 0
    last: dict[str, Any] = {}
    best_active: dict[str, Any] = {}
    best_active_radial_gain = -math.inf
    while time.monotonic() < deadline:
        states = query_turn_undead_pair(pair, network_id)
        samples += 1
        host = states["host"]
        client = states["client"]
        host_displacement = math.hypot(
            float(host["x"]) - initial_host_x,
            float(host["y"]) - initial_host_y,
        )
        client_displacement = math.hypot(
            float(client["x"]) - initial_client_x,
            float(client["y"]) - initial_client_y,
        )
        host_radial_gain = (
            math.hypot(
                float(host["x"]) - caster_x,
                float(host["y"]) - caster_y,
            )
            - initial_host_radius
        )
        client_radial_gain = (
            math.hypot(
                float(client["x"]) - caster_x,
                float(client["y"]) - caster_y,
            )
            - initial_client_radius
        )
        position_error = math.hypot(
            float(host["x"]) - float(client["x"]),
            float(host["y"]) - float(client["y"]),
        )
        last = {
            "states": states,
            "host_displacement": host_displacement,
            "client_displacement": client_displacement,
            "host_radial_gain": host_radial_gain,
            "client_radial_gain": client_radial_gain,
            "position_error": position_error,
            "samples": samples,
            "elapsed_seconds": time.monotonic() - started,
        }
        both_active = all(
            int(state["duration_ticks"]) > 0 for state in states.values()
        )
        minimum_radial_gain = min(host_radial_gain, client_radial_gain)
        if both_active and minimum_radial_gain > best_active_radial_gain:
            best_active_radial_gain = minimum_radial_gain
            best_active = last
        if (
            all(
                state["available"]
                and state["readable"]
                and state["tracked"]
                and not state["dead"]
                and state["duration_ticks"] > 0
                for state in states.values()
            )
            and host_displacement >= TURN_UNDEAD_MINIMUM_DISPLACEMENT
            and client_displacement >= TURN_UNDEAD_MINIMUM_DISPLACEMENT
            and host_radial_gain >= TURN_UNDEAD_MINIMUM_RADIAL_GAIN
            and client_radial_gain >= TURN_UNDEAD_MINIMUM_RADIAL_GAIN
            and position_error <= TURN_UNDEAD_MAXIMUM_VISUAL_POSITION_ERROR
        ):
            return last
        if samples > 1 and all(
            int(state["duration_ticks"]) <= 0 for state in states.values()
        ):
            break
        time.sleep(0.05)
    raise VerifyFailure(
        "Turn Undead did not produce converged movement away from its caster: "
        f"last={last} best_active={best_active}"
    )


def query_target_modifiers(
    pair: SteamFriendActivePair,
    endpoint: str,
    network_id: int,
) -> dict[str, Any]:
    target = primary.query_run_enemy_by_network_id(endpoint, network_id)
    if target.get("found") != "true":
        raise VerifyFailure(
            f"target modifier query could not resolve network actor "
            f"{network_id} on {endpoint}"
        )
    try:
        actor_address = int(target.get("actor_address", "0"), 0)
    except ValueError as exc:
        raise VerifyFailure(
            f"target modifier query returned an invalid local actor on "
            f"{endpoint}"
        ) from exc
    if actor_address == 0:
        raise VerifyFailure(
            f"target modifier query returned no local actor on {endpoint}"
        )

    values = parse_key_values(
        pair.lua(
            endpoint,
            QUERY_ACTOR_MODIFIERS_LUA.replace(
                "__ACTOR__", str(actor_address)
            ),
            timeout=8.0,
        )
    )
    if values.get("available") != "true":
        raise VerifyFailure(
            f"native target modifier list was unreadable on {endpoint}"
        )
    count = parse_int_text(values.get("count"), 0)
    modifiers = [
        {
            "type_id": parse_int_text(
                values.get(f"modifier.{index}.type_id"), 0
            ),
            "duration_ticks": parse_int_text(
                values.get(f"modifier.{index}.duration_ticks"), 0
            ),
        }
        for index in range(1, count + 1)
    ]
    return {
        "available": True,
        "modifiers": modifiers,
        "type_ids": sorted({row["type_id"] for row in modifiers}),
    }


def query_target_modifier_pair(
    pair: SteamFriendActivePair,
    network_id: int,
) -> dict[str, dict[str, Any]]:
    endpoints = {"host": HOST_ENDPOINT, "client": CLIENT_ENDPOINT}
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            label: executor.submit(
                query_target_modifiers,
                pair,
                endpoint,
                network_id,
            )
            for label, endpoint in endpoints.items()
        }
        return {label: future.result() for label, future in futures.items()}


def require_target_modifier_absent(
    pair: SteamFriendActivePair,
    network_id: int,
    modifier_type: int,
) -> dict[str, dict[str, Any]]:
    states = query_target_modifier_pair(pair, network_id)
    present = [
        label
        for label, state in states.items()
        if modifier_type in state["type_ids"]
    ]
    if present:
        raise VerifyFailure(
            f"target modifier 0x{modifier_type:X} was already active on "
            f"{present}"
        )
    return states


def wait_for_target_modifier_sync(
    pair: SteamFriendActivePair,
    network_id: int,
    modifier_type: int,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        states = query_target_modifier_pair(pair, network_id)
        durations = {
            label: max(
                (
                    row["duration_ticks"]
                    for row in state["modifiers"]
                    if row["type_id"] == modifier_type
                ),
                default=0,
            )
            for label, state in states.items()
        }
        duration_error = abs(durations["host"] - durations["client"])
        duration_tolerance = max(
            30.0,
            max(durations.values()) * 0.15,
        )
        last = {
            "expected_type_id": modifier_type,
            "host_duration_ticks": durations["host"],
            "client_duration_ticks": durations["client"],
            "duration_error": duration_error,
            "duration_tolerance": duration_tolerance,
            "host_type_ids": states["host"]["type_ids"],
            "client_type_ids": states["client"]["type_ids"],
        }
        if (
            durations["host"] > 0
            and durations["client"] > 0
            and duration_error <= duration_tolerance
        ):
            return last
        time.sleep(0.05)
    raise VerifyFailure(
        f"target modifier 0x{modifier_type:X} did not become a matching "
        f"positive native status on both peers: {last}"
    )


def wait_for_target_convergence(
    network_id: int,
    timeout: float,
    *,
    expected_hp: float | None = None,
    maximum_hp: float | None = None,
    expected_x: float | None = None,
    expected_y: float | None = None,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        while time.monotonic() < deadline:
            host_future = executor.submit(
                query_target_state,
                HOST_ENDPOINT,
                network_id,
            )
            client_future = executor.submit(
                query_target_state,
                CLIENT_ENDPOINT,
                network_id,
            )
            host = host_future.result()
            client = client_future.result()
            hp_error = abs(host["hp"] - client["hp"])
            position_error = math.hypot(
                host["x"] - client["x"],
                host["y"] - client["y"],
            )
            expected_hp_error = (
                max(
                    abs(host["hp"] - expected_hp),
                    abs(client["hp"] - expected_hp),
                )
                if expected_hp is not None
                else 0.0
            )
            expected_position_error = (
                max(
                    math.hypot(host["x"] - expected_x, host["y"] - expected_y),
                    math.hypot(
                        client["x"] - expected_x,
                        client["y"] - expected_y,
                    ),
                )
                if expected_x is not None and expected_y is not None
                else 0.0
            )
            maximum_hp_satisfied = (
                max(host["hp"], client["hp"]) <= maximum_hp
                if maximum_hp is not None
                else True
            )
            last = {
                "host": host,
                "client": client,
                "hp_error": hp_error,
                "position_error": position_error,
                "expected_hp_error": expected_hp_error,
                "expected_position_error": expected_position_error,
                "maximum_hp": maximum_hp,
                "maximum_hp_satisfied": maximum_hp_satisfied,
            }
            if (
                host["found"]
                and client["found"]
                and host["tracked"]
                and client["tracked"]
                and host["dead"] == client["dead"]
                and hp_error <= 0.25
                and position_error <= 3.0
                and expected_hp_error <= 0.25
                and expected_position_error <= 3.0
                and maximum_hp_satisfied
            ):
                return last
            time.sleep(0.08)
    raise VerifyFailure(
        "secondary target did not converge by network identity: "
        f"network_id={network_id} last={last}"
    )


def query_target_native_spatial(
    pair: SteamFriendActivePair,
    endpoint: str,
    network_id: int,
) -> dict[str, str]:
    return parse_key_values(
        pair.lua(
            endpoint,
            QUERY_TARGET_NATIVE_SPATIAL_LUA.replace(
                "__NETWORK_ACTOR_ID__",
                str(network_id),
            ),
            timeout=8.0,
        )
    )


def require_target_native_cell_stability(
    pair: SteamFriendActivePair,
    network_id: int,
    expected_x: float,
    expected_y: float,
) -> dict[str, Any]:
    endpoints = {"host": HOST_ENDPOINT, "client": CLIENT_ENDPOINT}
    rebind_snippet = REBIND_TARGET_NATIVE_SPATIAL_LUA.replace(
        "__NETWORK_ACTOR_ID__",
        str(network_id),
    )
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            label: executor.submit(
                pair.lua,
                endpoint,
                rebind_snippet,
                timeout=8.0,
            )
            for label, endpoint in endpoints.items()
        }
        rebound = {
            label: parse_key_values(future.result())
            for label, future in futures.items()
        }

    expected_cells: dict[str, int] = {}
    for label, state in rebound.items():
        cell = parse_int_text(state.get("cell"), 0)
        if state.get("ok") != "true" or cell == 0:
            raise VerifyFailure(
                f"{label} native target spatial rebind failed: {state}"
            )
        expected_cells[label] = cell

    started = time.monotonic()
    samples: list[dict[str, dict[str, str]]] = []
    while (
        time.monotonic() - started < TARGET_NATIVE_CELL_STABILITY_SECONDS
        or len(samples) < TARGET_NATIVE_CELL_MINIMUM_SAMPLES
    ):
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = {
                label: executor.submit(
                    query_target_native_spatial,
                    pair,
                    endpoint,
                    network_id,
                )
                for label, endpoint in endpoints.items()
            }
            sample = {
                label: future.result()
                for label, future in futures.items()
            }
        for label, state in sample.items():
            cell = parse_int_text(state.get("cell"), 0)
            x = float(state.get("x", "nan"))
            y = float(state.get("y", "nan"))
            position_error = math.hypot(x - expected_x, y - expected_y)
            if (
                state.get("found") != "true"
                or cell != expected_cells[label]
                or not math.isfinite(position_error)
                or position_error > 3.0
            ):
                raise VerifyFailure(
                    f"{label} frozen target left its rebound native spatial cell: "
                    f"expected_cell=0x{expected_cells[label]:08X} "
                    f"expected_position=({expected_x:.3f},{expected_y:.3f}) "
                    f"position_error={position_error:.3f} state={state}"
                )
        samples.append(sample)
        time.sleep(0.08)

    return {
        "duration_seconds": time.monotonic() - started,
        "sample_count": len(samples),
        "rebind": rebound,
        "expected_cells": {
            label: f"0x{cell:08X}"
            for label, cell in expected_cells.items()
        },
        "last": samples[-1],
    }


def prepare_target(
    pair: SteamFriendActivePair,
    direction: focus.Direction,
) -> dict[str, Any]:
    owner_rush = rush.DIRECTIONS[0 if direction.source_pipe == HOST_ENDPOINT else 1]
    rush.place_player(owner_rush.other_pipe, rush.PARK_X, rush.PARK_Y, 180.0)
    placement = rush.place_player(
        owner_rush.owner_pipe,
        rush.START_X,
        rush.START_Y,
        90.0,
    )
    owner_transform = rush.wait_for_local_transform_settled(
        owner_rush.owner_pipe,
        timeout=10.0,
        stable_seconds=0.35,
    )
    rush.wait_for_remote_convergence(
        owner_rush.observer_pipe,
        owner_rush.participant_id,
        *owner_transform,
        timeout=20.0,
    )

    target_x = float(owner_transform[0]) + TARGET_OFFSET_X
    target_y = float(owner_transform[1]) + TARGET_OFFSET_Y

    spawned = primary.spawn_one_enemy(target_x, target_y, setup_hp=TARGET_HP)
    network_id = int(spawned["network_actor_id"])
    host_target = primary.find_target(
        HOST_ENDPOINT,
        target_x,
        target_y,
        network_id,
        timeout=8.0,
        require_local_binding=False,
    )
    client_target = primary.find_target(
        CLIENT_ENDPOINT,
        target_x,
        target_y,
        network_id,
        timeout=8.0,
    )
    source_target = host_target if direction.source_pipe == HOST_ENDPOINT else client_target
    source_actor = (
        int(spawned["actor_address"])
        if direction.source_pipe == HOST_ENDPOINT
        else parse_int_text(source_target.get("local.actor_address"), 0)
    )
    if source_actor == 0:
        raise VerifyFailure(
            f"{direction.name} secondary target has no source-local actor"
        )
    prepared = parse_key_values(
        pair.lua(
            direction.source_pipe,
            PREPARE_LOCAL_TARGET_LUA
            .replace("__TARGET_ACTOR__", str(source_actor))
            .replace("__TARGET_X__", f"{target_x:.3f}")
            .replace("__TARGET_Y__", f"{target_y:.3f}"),
            timeout=8.0,
        )
    )
    if prepared.get("ok") != "true":
        raise VerifyFailure(
            f"{direction.name} secondary target preparation failed: {prepared}"
        )
    baseline = wait_for_target_convergence(
        network_id,
        timeout=12.0,
        expected_hp=TARGET_HP,
        expected_x=target_x,
        expected_y=target_y,
    )
    native_spatial_stability = require_target_native_cell_stability(
        pair,
        network_id,
        target_x,
        target_y,
    )
    return {
        "placement": placement,
        "owner_transform": owner_transform,
        "spawn": spawned,
        "x": target_x,
        "y": target_y,
        "network_id": network_id,
        "source_actor": source_actor,
        "host_before": host_target,
        "client_before": client_target,
        "baseline": baseline,
        "prepared": prepared,
        "native_spatial_stability": native_spatial_stability,
    }


def _position_error(owner: dict[str, Any], observer: dict[str, Any]) -> float:
    return math.hypot(owner["x"] - observer["x"], owner["y"] - observer["y"])


def wait_for_vitals_convergence(
    pair: SteamFriendActivePair,
    direction: focus.Direction,
    timeout: float,
    mana_tolerance: float = 0.75,
) -> dict[str, Any]:
    started = time.monotonic()
    deadline = started + timeout
    samples = 0
    last: dict[str, Any] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        while time.monotonic() < deadline:
            owner_future = executor.submit(
                query_vitals,
                pair,
                direction.source_pipe,
            )
            observer_future = executor.submit(
                query_vitals,
                pair,
                observer_endpoint(direction),
                direction.source_id,
            )
            owner = owner_future.result()
            observer = observer_future.result()
            samples += 1
            mana_error = abs(owner["mp"] - observer["mp"])
            position_error = _position_error(owner, observer)
            last = {
                "owner": owner,
                "observer": observer,
                "mana_error": mana_error,
                "position_error": position_error,
                "samples": samples,
                "elapsed_seconds": time.monotonic() - started,
            }
            if mana_error <= mana_tolerance and position_error <= 2.0:
                return last
            time.sleep(0.08)
    raise VerifyFailure(
        f"{direction.name} secondary vitals did not converge: {last}"
    )


def run_native_transient_status(
    pair: SteamFriendActivePair,
    direction: focus.Direction,
    skill: SecondarySkillSpec,
    acquisition: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    status_flag = NATIVE_TRANSIENT_STATUS_FLAGS[skill.row]
    resources = set_local_player_vitals(
        direction.source_pipe,
        PLAYER_RESOURCE_MAX,
        PLAYER_RESOURCE_MAX,
        mp=PLAYER_RESOURCE_MAX,
        max_mp=PLAYER_RESOURCE_MAX,
    )

    before_owner = query_vitals(pair, direction.source_pipe)
    before_observer = query_vitals(
        pair,
        observer_endpoint(direction),
        direction.source_id,
    )
    if (
        before_owner["native_transient_status_flags"] & status_flag
        or before_observer["transient_status_flags"] & status_flag
        or before_observer["native_transient_status_flags"] & status_flag
    ):
        raise VerifyFailure(
            f"{direction.name} {skill.name} began with stale native status: "
            f"owner={before_owner} observer={before_observer}"
        )

    source_offset = len(read_log(direction.source_log))
    observer_offset = len(read_log(direction.observer_log))
    mana_observation_arm = arm_local_mana_observation(
        pair,
        direction.source_pipe,
    )
    input_cast = focus.cast_secondary_belt_slot(
        direction,
        int(acquisition["belt_slot"]),
        timeout,
    )
    delivery = wait_for_secondary_delivery(
        direction,
        skill.row,
        int(acquisition["belt_slot"]),
        source_offset,
        observer_offset,
        timeout,
    )
    mana_observation = take_local_mana_observation(
        pair,
        direction.source_pipe,
    )
    if (
        not mana_observation["valid"]
        or int(mana_observation["spend_call_count"]) < 1
        or float(mana_observation["spent_total"]) <= 0.01
    ):
        raise VerifyFailure(
            f"{direction.name} {skill.name} did not spend mana through the "
            f"native delta path: {mana_observation}"
        )

    started = time.monotonic()
    deadline = started + max(timeout, 16.0)
    owner_active_since: float | None = None
    owner_cleared_at: float | None = None
    observer_cleared_at: float | None = None
    lifecycle_samples: list[dict[str, Any]] = []
    compared_active_samples = 0
    replicated_active_samples = 0
    native_active_samples = 0
    maximum_sample_duration_seconds = 0.0
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        while time.monotonic() < deadline:
            sample_started = time.monotonic()
            owner_future = executor.submit(
                query_vitals,
                pair,
                direction.source_pipe,
            )
            observer_future = executor.submit(
                query_vitals,
                pair,
                observer_endpoint(direction),
                direction.source_id,
            )
            owner = owner_future.result()
            observer = observer_future.result()
            elapsed = time.monotonic() - started
            sample_duration = time.monotonic() - sample_started
            maximum_sample_duration_seconds = max(
                maximum_sample_duration_seconds,
                sample_duration,
            )
            owner_active = bool(
                owner["native_transient_status_flags"] & status_flag
            )
            observer_replicated_active = bool(
                observer["transient_status_flags"] & status_flag
            )
            observer_native_active = bool(
                observer["native_transient_status_flags"] & status_flag
            )
            lifecycle_samples.append(
                {
                    "elapsed_seconds": elapsed,
                    "sample_duration_seconds": sample_duration,
                    "owner_active": owner_active,
                    "observer_replicated_active": observer_replicated_active,
                    "observer_native_active": observer_native_active,
                    "owner_flags": owner["native_transient_status_flags"],
                    "observer_replicated_flags": observer[
                        "transient_status_flags"
                    ],
                    "observer_native_flags": observer[
                        "native_transient_status_flags"
                    ],
                }
            )

            if owner_active and owner_active_since is None:
                owner_active_since = elapsed
            if (
                owner_active
                and owner_active_since is not None
                and elapsed - owner_active_since >= 0.75
            ):
                compared_active_samples += 1
                replicated_active_samples += int(observer_replicated_active)
                native_active_samples += int(observer_native_active)
            if (
                owner_active_since is not None
                and not owner_active
                and owner_cleared_at is None
            ):
                owner_cleared_at = elapsed
            if (
                owner_cleared_at is not None
                and not observer_replicated_active
                and not observer_native_active
            ):
                observer_cleared_at = elapsed
                break
            time.sleep(0.08)

    if owner_active_since is None:
        raise VerifyFailure(
            f"{direction.name} {skill.name} never established its native "
            "owner status"
        )
    if owner_cleared_at is None:
        raise VerifyFailure(
            f"{direction.name} {skill.name} owner status did not expire"
        )
    active_observation_seconds = owner_cleared_at - owner_active_since
    if (
        active_observation_seconds < MINIMUM_TRANSIENT_STATUS_OBSERVATION_SECONDS
        or compared_active_samples < MINIMUM_TRANSIENT_STATUS_COMPARISON_SAMPLES
    ):
        raise VerifyFailure(
            f"{direction.name} {skill.name} active lifecycle was too short: "
            f"seconds={active_observation_seconds:.3f} "
            f"samples={compared_active_samples}"
        )
    minimum_matching_samples = math.ceil(compared_active_samples * 0.9)
    if (
        replicated_active_samples < minimum_matching_samples
        or native_active_samples < minimum_matching_samples
    ):
        raise VerifyFailure(
            f"{direction.name} {skill.name} observer did not retain the "
            f"owner-authored status: compared={compared_active_samples} "
            f"replicated={replicated_active_samples} native={native_active_samples}"
        )
    if observer_cleared_at is None:
        raise VerifyFailure(
            f"{direction.name} {skill.name} observer status did not clear"
        )
    clear_delay = observer_cleared_at - owner_cleared_at
    # A paired sample starts both endpoint reads together. With an SSH-backed
    # physical peer, the faster result can therefore be up to one measured
    # round trip older than the slower result. Keep the gameplay propagation
    # budget strict while accounting for that known observation uncertainty.
    clear_delay_budget = (
        TRANSIENT_STATUS_CLEAR_PROPAGATION_BUDGET_SECONDS
        + maximum_sample_duration_seconds
    )
    if clear_delay > clear_delay_budget:
        raise VerifyFailure(
            f"{direction.name} {skill.name} observer status cleared "
            f"{clear_delay:.3f}s after the owner; "
            f"budget={clear_delay_budget:.3f}s"
        )

    vitals_convergence = wait_for_vitals_convergence(
        pair,
        direction,
        timeout=min(timeout, 12.0),
    )
    return {
        "behavior": "native_transient_status",
        "status_flag": status_flag,
        "resources": resources,
        "before_owner": before_owner,
        "before_observer": before_observer,
        "mana_observation_arm": mana_observation_arm,
        "mana_observation": mana_observation,
        "input_cast": input_cast,
        "delivery": delivery,
        "owner_active_since_seconds": owner_active_since,
        "owner_cleared_at_seconds": owner_cleared_at,
        "observer_cleared_at_seconds": observer_cleared_at,
        "observer_clear_delay_seconds": clear_delay,
        "observer_clear_delay_budget_seconds": clear_delay_budget,
        "maximum_sample_duration_seconds": maximum_sample_duration_seconds,
        "active_observation_seconds": active_observation_seconds,
        "compared_active_samples": compared_active_samples,
        "replicated_active_samples": replicated_active_samples,
        "native_active_samples": native_active_samples,
        "lifecycle_samples": lifecycle_samples,
        "vitals_convergence": vitals_convergence,
    }


def _magic_shield_values(state: dict[str, Any], *, native: bool) -> dict[str, float]:
    prefix = "native_" if native else ""
    return {
        "absorb_remaining": float(
            state[f"{prefix}magic_shield_absorb_remaining"]
        ),
        "absorb_capacity": float(
            state[f"{prefix}magic_shield_absorb_capacity"]
        ),
        "explosion_fraction": float(
            state[f"{prefix}magic_shield_explosion_fraction"]
        ),
        "hit_flash": float(state[f"{prefix}magic_shield_hit_flash"]),
    }


def _magic_shield_matches(
    values: dict[str, float],
    *,
    expected_remaining: float,
    expected_capacity: float,
    expected_explosion_fraction: float,
) -> bool:
    return (
        abs(values["absorb_remaining"] - expected_remaining)
        <= MAGIC_SHIELD_TOLERANCE
        and abs(values["absorb_capacity"] - expected_capacity)
        <= MAGIC_SHIELD_TOLERANCE
        and abs(
            values["explosion_fraction"] - expected_explosion_fraction
        )
        <= 0.001
    )


def wait_for_magic_shield_convergence(
    pair: SteamFriendActivePair,
    direction: focus.Direction,
    *,
    expected_remaining: float,
    expected_capacity: float,
    expected_explosion_fraction: float,
    timeout: float,
    minimum_sample_seconds: float = 0.0,
) -> dict[str, Any]:
    started = time.monotonic()
    deadline = started + timeout
    samples = 0
    converged_at: float | None = None
    maximum_hit_flash = {
        "owner_native": 0.0,
        "observer_replicated": 0.0,
        "observer_native": 0.0,
    }
    last: dict[str, Any] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        while time.monotonic() < deadline:
            owner_future = executor.submit(
                query_vitals,
                pair,
                direction.source_pipe,
            )
            observer_future = executor.submit(
                query_vitals,
                pair,
                observer_endpoint(direction),
                direction.source_id,
            )
            owner = owner_future.result()
            observer = observer_future.result()
            samples += 1
            owner_native = _magic_shield_values(owner, native=True)
            observer_replicated = _magic_shield_values(
                observer,
                native=False,
            )
            observer_native = _magic_shield_values(observer, native=True)
            maximum_hit_flash["owner_native"] = max(
                maximum_hit_flash["owner_native"],
                owner_native["hit_flash"],
            )
            maximum_hit_flash["observer_replicated"] = max(
                maximum_hit_flash["observer_replicated"],
                observer_replicated["hit_flash"],
            )
            maximum_hit_flash["observer_native"] = max(
                maximum_hit_flash["observer_native"],
                observer_native["hit_flash"],
            )
            elapsed = time.monotonic() - started
            matches = all(
                _magic_shield_matches(
                    values,
                    expected_remaining=expected_remaining,
                    expected_capacity=expected_capacity,
                    expected_explosion_fraction=expected_explosion_fraction,
                )
                for values in (
                    owner_native,
                    observer_replicated,
                    observer_native,
                )
            )
            if matches and abs(owner["hp"] - observer["hp"]) <= 0.2:
                if converged_at is None:
                    converged_at = elapsed
                if elapsed >= minimum_sample_seconds:
                    return {
                        "owner": owner,
                        "observer": observer,
                        "owner_native": owner_native,
                        "observer_replicated": observer_replicated,
                        "observer_native": observer_native,
                        "maximum_hit_flash": maximum_hit_flash,
                        "samples": samples,
                        "converged_at_seconds": converged_at,
                        "elapsed_seconds": elapsed,
                    }
            last = {
                "owner": owner,
                "observer": observer,
                "owner_native": owner_native,
                "observer_replicated": observer_replicated,
                "observer_native": observer_native,
                "maximum_hit_flash": maximum_hit_flash,
                "samples": samples,
                "elapsed_seconds": elapsed,
            }
            time.sleep(0.02)
    raise VerifyFailure(
        f"{direction.name} Magic Shield did not converge to "
        f"remaining={expected_remaining} capacity={expected_capacity} "
        f"explosion={expected_explosion_fraction}: {last}"
    )


def run_magic_shield(
    pair: SteamFriendActivePair,
    direction: focus.Direction,
    acquisition: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    resources = set_local_player_vitals(
        direction.source_pipe,
        PLAYER_RESOURCE_MAX,
        PLAYER_RESOURCE_MAX,
        mp=PLAYER_RESOURCE_MAX,
        max_mp=PLAYER_RESOURCE_MAX,
    )
    before_owner = query_vitals(pair, direction.source_pipe)
    before_observer = query_vitals(
        pair,
        observer_endpoint(direction),
        direction.source_id,
    )
    for label, values in (
        ("owner", _magic_shield_values(before_owner, native=True)),
        (
            "observer_replicated",
            _magic_shield_values(before_observer, native=False),
        ),
        ("observer_native", _magic_shield_values(before_observer, native=True)),
    ):
        if values["absorb_remaining"] > MAGIC_SHIELD_TOLERANCE:
            raise VerifyFailure(
                f"{direction.name} Magic Shield began active on {label}: "
                f"{values}"
            )

    source_offset = len(read_log(direction.source_log))
    observer_offset = len(read_log(direction.observer_log))
    mana_observation_arm = arm_local_mana_observation(
        pair,
        direction.source_pipe,
    )
    input_cast = focus.cast_secondary_belt_slot(
        direction,
        int(acquisition["belt_slot"]),
        timeout,
    )
    delivery = wait_for_secondary_delivery(
        direction,
        MAGIC_SHIELD_ROW,
        int(acquisition["belt_slot"]),
        source_offset,
        observer_offset,
        timeout,
    )
    mana_observation = take_local_mana_observation(
        pair,
        direction.source_pipe,
    )
    if (
        not mana_observation["valid"]
        or int(mana_observation["spend_call_count"]) < 1
        or float(mana_observation["spent_total"]) <= 0.01
    ):
        raise VerifyFailure(
            f"{direction.name} Magic Shield did not spend mana through the "
            f"native delta path: {mana_observation}"
        )

    active = wait_for_magic_shield_convergence(
        pair,
        direction,
        expected_remaining=MAGIC_SHIELD_RANK_ONE_ABSORB,
        expected_capacity=MAGIC_SHIELD_RANK_ONE_ABSORB,
        expected_explosion_fraction=0.0,
        timeout=timeout,
    )
    first_hit = defense.invoke_native_magic_hit_trial(
        direction.source_pipe,
        projectile_damage=0.0,
        magic_damage=MAGIC_SHIELD_FIRST_HIT_DAMAGE,
        attempts=1,
        label=f"{direction.name}_magic_shield_absorb",
        timeout=timeout,
        require_life_loss=False,
    )
    if abs(float(first_hit["hp_delta"])) > 0.01:
        raise VerifyFailure(
            f"{direction.name} Magic Shield failed to absorb its first hit: "
            f"{first_hit}"
        )
    after_first_hit = wait_for_magic_shield_convergence(
        pair,
        direction,
        expected_remaining=(
            MAGIC_SHIELD_RANK_ONE_ABSORB - MAGIC_SHIELD_FIRST_HIT_DAMAGE
        ),
        expected_capacity=MAGIC_SHIELD_RANK_ONE_ABSORB,
        expected_explosion_fraction=0.0,
        timeout=timeout,
        minimum_sample_seconds=0.5,
    )
    flashes = after_first_hit["maximum_hit_flash"]
    if (
        flashes["owner_native"] <= 0.001
        or flashes["observer_replicated"] <= 0.001
        or flashes["observer_native"] <= 0.001
    ):
        raise VerifyFailure(
            f"{direction.name} Magic Shield hit flash did not replicate "
            f"through native state: {flashes}"
        )

    break_hit = defense.invoke_native_magic_hit_trial(
        direction.source_pipe,
        projectile_damage=0.0,
        magic_damage=MAGIC_SHIELD_BREAK_HIT_DAMAGE,
        attempts=1,
        label=f"{direction.name}_magic_shield_break",
        timeout=timeout,
        require_life_loss=False,
    )
    if abs(float(break_hit["hp_delta"])) > 0.01:
        raise VerifyFailure(
            f"{direction.name} Magic Shield break leaked damage to life: "
            f"{break_hit}"
        )
    cleared = wait_for_magic_shield_convergence(
        pair,
        direction,
        expected_remaining=0.0,
        expected_capacity=0.0,
        expected_explosion_fraction=0.0,
        timeout=timeout,
    )
    return {
        "behavior": "magic_shield",
        "resources": resources,
        "before_owner": before_owner,
        "before_observer": before_observer,
        "mana_observation_arm": mana_observation_arm,
        "mana_observation": mana_observation,
        "input_cast": input_cast,
        "delivery": delivery,
        "active": active,
        "first_hit": first_hit,
        "after_first_hit": after_first_hit,
        "break_hit": break_hit,
        "cleared": cleared,
    }


def run_phasing(
    pair: SteamFriendActivePair,
    direction: focus.Direction,
    acquisition: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    rush.enable_quiet_stock_input_mode(timeout)
    rush_direction = rush.DIRECTIONS[0 if direction.source_pipe == HOST_ENDPOINT else 1]
    baseline = rush.run_movement_trial(
        rush_direction,
        "secondary_phasing_baseline",
        timeout,
    )

    rush.place_player(rush_direction.other_pipe, rush.PARK_X, rush.PARK_Y, 180.0)
    placement = rush.place_player(
        rush_direction.owner_pipe,
        rush.START_X,
        rush.START_Y,
        0.0,
    )
    start_x, start_y, start_heading = rush.wait_for_local_transform_settled(
        rush_direction.owner_pipe,
        timeout=10.0,
        stable_seconds=0.35,
    )
    rush.wait_for_remote_convergence(
        rush_direction.observer_pipe,
        rush_direction.participant_id,
        start_x,
        start_y,
        start_heading,
        timeout=timeout,
    )

    source_offset = len(read_log(direction.source_log))
    observer_offset = len(read_log(direction.observer_log))
    monitor_arms = arm_effect_monitors(pair, direction)
    mana_observation_arm = arm_local_mana_observation(
        pair,
        direction.source_pipe,
    )
    drive_start = rush.configure_native_movement_drive(
        rush_direction.owner_pipe,
        rush.DRIVE_TICKS,
    )
    input_cast = focus.cast_secondary_belt_slot(
        direction,
        int(acquisition["belt_slot"]),
        timeout,
    )
    delivery = wait_for_secondary_delivery(
        direction,
        15,
        int(acquisition["belt_slot"]),
        source_offset,
        observer_offset,
        timeout,
    )
    mana_observation = take_local_mana_observation(
        pair,
        direction.source_pipe,
    )
    if (
        not mana_observation["valid"]
        or int(mana_observation["spend_call_count"]) < 1
        or float(mana_observation["spent_total"]) <= 0.01
    ):
        raise VerifyFailure(
            f"{direction.name} Phasing did not spend mana through the native "
            f"delta path: {mana_observation}"
        )
    drive = rush.wait_for_native_movement_drive(
        rush_direction.owner_pipe,
        rush.DRIVE_TICKS,
        timeout,
    )
    final_x, final_y, final_heading = rush.wait_for_local_transform_settled(
        rush_direction.owner_pipe,
        timeout=10.0,
        stable_seconds=0.60,
    )
    observer_state = rush.wait_for_remote_convergence(
        rush_direction.observer_pipe,
        rush_direction.participant_id,
        final_x,
        final_y,
        final_heading,
        timeout=timeout,
    )
    effects = collect_effect_monitors(pair, direction, timeout)

    displacement = math.hypot(final_x - start_x, final_y - start_y)
    extra_displacement = displacement - float(baseline["displacement"])
    prefix = f"peer.{rush_direction.participant_id}."
    observer_x = float(observer_state[prefix + "x"])
    observer_y = float(observer_state[prefix + "y"])
    position_error = math.hypot(final_x - observer_x, final_y - observer_y)
    if extra_displacement < 60.0:
        raise VerifyFailure(
            f"{direction.name} Phasing did not add its native displacement: "
            f"baseline={baseline['displacement']} phased={displacement}"
        )
    if position_error > 2.0:
        raise VerifyFailure(
            f"{direction.name} Phasing observer position diverged by "
            f"{position_error}"
        )
    return {
        "behavior": "phasing",
        "baseline": baseline,
        "placement": placement,
        "monitor_arms": monitor_arms,
        "mana_observation_arm": mana_observation_arm,
        "mana_observation": mana_observation,
        "drive_start": drive_start,
        "input_cast": input_cast,
        "delivery": delivery,
        "drive": drive,
        "start": {"x": start_x, "y": start_y, "heading": start_heading},
        "final": {"x": final_x, "y": final_y, "heading": final_heading},
        "displacement": displacement,
        "extra_displacement": extra_displacement,
        "observer_position_error": position_error,
        "effects": effects,
    }


def run_generic(
    pair: SteamFriendActivePair,
    direction: focus.Direction,
    skill: SecondarySkillSpec,
    acquisition: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    resources = set_local_player_vitals(
        direction.source_pipe,
        PLAYER_RESOURCE_MAX,
        PLAYER_RESOURCE_MAX,
        mp=PLAYER_RESOURCE_MAX,
        max_mp=PLAYER_RESOURCE_MAX,
    )
    target = prepare_target(pair, direction) if skill.target_required else None
    dampen_shared_view_geometry = (
        prepare_dampen_shared_view_geometry(direction, timeout)
        if skill.behavior == "dampen"
        else None
    )
    turn_undead_baseline = (
        require_turn_undead_baseline(pair, int(target["network_id"]))
        if target is not None and skill.row == TURN_UNDEAD_ROW
        else None
    )
    expected_target_modifier = NATIVE_TARGET_MODIFIER_TYPES.get(skill.row)
    target_modifier_baseline = (
        require_target_modifier_absent(
            pair,
            int(target["network_id"]),
            expected_target_modifier,
        )
        if target is not None and expected_target_modifier is not None
        else None
    )
    before_owner = query_vitals(pair, direction.source_pipe)
    before_observer = query_vitals(
        pair,
        observer_endpoint(direction),
        direction.source_id,
    )
    source_offset = len(read_log(direction.source_log))
    observer_offset = len(read_log(direction.observer_log))
    monitor_arms = arm_effect_monitors(pair, direction)
    mana_observation_arm = arm_local_mana_observation(
        pair,
        direction.source_pipe,
    )
    turn_undead_freeze_clear = (
        clear_turn_undead_target_freeze(
            pair,
            int(target["spawn"]["actor_address"]),
        )
        if target is not None and skill.row == TURN_UNDEAD_ROW
        else None
    )
    input_cast = focus.cast_secondary_belt_slot(
        direction,
        int(acquisition["belt_slot"]),
        timeout,
    )
    delivery = wait_for_secondary_delivery(
        direction,
        skill.row,
        int(acquisition["belt_slot"]),
        source_offset,
        observer_offset,
        timeout,
    )
    turn_undead_activation = (
        wait_for_turn_undead_activation(
            pair,
            int(target["network_id"]),
            timeout=min(timeout, 8.0),
        )
        if target is not None and skill.row == TURN_UNDEAD_ROW
        else None
    )
    turn_undead_flee = (
        wait_for_turn_undead_flee(
            pair,
            target,
            turn_undead_activation,
            timeout=min(timeout, 10.0),
        )
        if turn_undead_activation is not None
        else None
    )
    dampen_witness = (
        wait_for_dampen_application(
            direction,
            source_offset,
            observer_offset,
            float(before_owner["x"]),
            float(before_owner["y"]),
            timeout,
        )
        if skill.behavior == "dampen"
        else None
    )
    target_modifier_witness = (
        wait_for_target_modifier_sync(
            pair,
            int(target["network_id"]),
            expected_target_modifier,
            timeout=min(timeout, 8.0),
        )
        if target is not None and expected_target_modifier is not None
        else None
    )
    after_delivery_owner = query_vitals(pair, direction.source_pipe)
    mana_observation = take_local_mana_observation(
        pair,
        direction.source_pipe,
    )
    effects = collect_effect_monitors(pair, direction, timeout)
    vitals_convergence = wait_for_vitals_convergence(
        pair,
        direction,
        timeout=min(timeout, 12.0),
    )
    after_owner = vitals_convergence["owner"]
    after_observer = vitals_convergence["observer"]

    final_mana_delta = before_owner["mp"] - after_owner["mp"]
    native_mana_spent = float(mana_observation["spent_total"])
    observer_mana_error = abs(after_owner["mp"] - after_observer["mp"])
    position_error = _position_error(after_owner, after_observer)
    if (
        skill.behavior != "persistent"
        and (
            not mana_observation["valid"]
            or int(mana_observation["spend_call_count"]) < 1
            or native_mana_spent <= 0.01
        )
    ):
        raise VerifyFailure(
            f"{direction.name} {skill.name} did not spend mana through the "
            f"native delta path: {mana_observation}"
        )
    if observer_mana_error > 2.0:
        raise VerifyFailure(
            f"{direction.name} {skill.name} observer mana diverged by "
            f"{observer_mana_error}"
        )
    if position_error > 2.0:
        raise VerifyFailure(
            f"{direction.name} {skill.name} observer position diverged by "
            f"{position_error}"
        )

    target_after: dict[str, Any] | None = None
    behavior_witness: dict[str, Any] | None = (
        {
            "baseline": turn_undead_baseline,
            "activation": turn_undead_activation,
            "freeze_clear": turn_undead_freeze_clear,
            "flee": turn_undead_flee,
        }
        if turn_undead_flee is not None
        else (
            dampen_witness
            if dampen_witness is not None
            else target_modifier_witness
        )
    )
    if target is not None:
        damage_baseline_hp = min(
            float(target["baseline"]["host"]["hp"]),
            float(target["baseline"]["client"]["hp"]),
        )
        target_after = wait_for_target_convergence(
            int(target["network_id"]),
            timeout=min(timeout, 12.0),
            maximum_hp=(
                damage_baseline_hp - 0.01
                if skill.behavior in ("area_damage", "target_damage")
                else None
            ),
        )
        if skill.behavior in ("area_damage", "target_damage"):
            host_damage = (
                float(target["baseline"]["host"]["hp"])
                - float(target_after["host"]["hp"])
            )
            client_damage = (
                float(target["baseline"]["client"]["hp"])
                - float(target_after["client"]["hp"])
            )
            if host_damage <= 0.01 or client_damage <= 0.01:
                raise VerifyFailure(
                    f"{direction.name} {skill.name} caused no authoritative "
                    f"target damage: host={host_damage} client={client_damage}"
                )
            if abs(host_damage - client_damage) > 0.25:
                raise VerifyFailure(
                    f"{direction.name} {skill.name} target damage diverged: "
                    f"host={host_damage} client={client_damage}"
                )
            behavior_witness = {
                "host_damage": host_damage,
                "client_damage": client_damage,
            }

    shared_effect_types = sorted(
        set(effects["owner"]["type_peaks"])
        & set(effects["observer"]["type_peaks"])
    )
    if skill.expect_new_actor and not shared_effect_types:
        raise VerifyFailure(
            f"{direction.name} {skill.name} created no matching native effect "
            f"type: effects={effects}"
        )
    effect_position_sync = verify_synchronized_effect_positions(
        direction,
        skill,
        effects,
    )

    return {
        "behavior": skill.behavior,
        "resources": resources,
        "target": target,
        "dampen_shared_view_geometry": dampen_shared_view_geometry,
        "turn_undead_baseline": turn_undead_baseline,
        "turn_undead_activation": turn_undead_activation,
        "turn_undead_freeze_clear": turn_undead_freeze_clear,
        "turn_undead_flee": turn_undead_flee,
        "target_modifier_baseline": target_modifier_baseline,
        "target_modifier_witness": target_modifier_witness,
        "before_owner": before_owner,
        "before_observer": before_observer,
        "monitor_arms": monitor_arms,
        "mana_observation_arm": mana_observation_arm,
        "mana_observation": mana_observation,
        "input_cast": input_cast,
        "delivery": delivery,
        "after_delivery_owner": after_delivery_owner,
        "effects": effects,
        "shared_effect_types": shared_effect_types,
        "effect_position_sync": effect_position_sync,
        "after_owner": after_owner,
        "after_observer": after_observer,
        "vitals_convergence": vitals_convergence,
        "native_mana_spent": native_mana_spent,
        "final_mana_delta": final_mana_delta,
        "observer_mana_error": observer_mana_error,
        "observer_position_error": position_error,
        "target_after": target_after,
        "behavior_witness": behavior_witness,
    }


def run_skill(
    pair: SteamFriendActivePair,
    direction: focus.Direction,
    skill: SecondarySkillSpec,
    acquisition: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    if skill.behavior == "persistent":
        raise VerifyFailure(
            f"{skill.name} belongs in the dedicated persistent lifecycle suite"
        )
    if skill.behavior == "phasing":
        return run_phasing(pair, direction, acquisition, timeout)
    if skill.behavior == "magic_shield":
        return run_magic_shield(pair, direction, acquisition, timeout)
    if skill.row in NATIVE_TRANSIENT_STATUS_FLAGS:
        return run_native_transient_status(
            pair,
            direction,
            skill,
            acquisition,
            timeout,
        )
    return run_generic(pair, direction, skill, acquisition, timeout)
