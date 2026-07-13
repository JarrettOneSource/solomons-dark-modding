#!/usr/bin/env python3
"""Exact owner/runtime/observer probes for persistent multiplayer skills."""

from __future__ import annotations

import json
import math
import time
from typing import Any

from cast_state_probe import read_runtime_layout_offset
from verify_local_multiplayer_sync import VerifyFailure, lua, parse_int_text, parse_key_values


PERSISTENT_FIREWALKER = 1 << 0
PERSISTENT_MINDSTAR = 1 << 1
PERSISTENT_REGENERATE = 1 << 2
PERSISTENT_VALUE_MASK = (
    PERSISTENT_FIREWALKER | PERSISTENT_MINDSTAR | PERSISTENT_REGENERATE
)
PERSISTENT_SNAPSHOT_VALID = 1 << 7
NATIVE_OBJECT_FACTORY = read_runtime_layout_offset("fire_ember_fragment_factory")
FIREWALKER_TRAIL_NATIVE_TYPE = 0x07EE


def _as_float(values: dict[str, str], key: str) -> float:
    try:
        return float(values.get(key, "nan"))
    except ValueError:
        return math.nan


def query_persistent_status(
    pipe_name: str,
    *,
    participant_id: int | None = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """Read one local owner or materialized remote participant at every layer."""

    participant_selector = "nil" if participant_id is None else str(participant_id)
    code = f"""
local function emit(key, value)
  if value == nil then value = '<nil>' end
  print(key .. '=' .. tostring(value))
end
local requested = {participant_selector}
local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
local bot = requested ~= nil and sd.bots and sd.bots.get_participant_state and
  sd.bots.get_participant_state(requested) or nil
local mp = sd.runtime and sd.runtime.get_multiplayer_state and
  sd.runtime.get_multiplayer_state() or nil
local runtime = nil
if mp and mp.participants then
  for _, participant in ipairs(mp.participants) do
    if (requested == nil and participant.is_owner) or
       (requested ~= nil and tonumber(participant.participant_id) == requested) then
      runtime = participant
      break
    end
  end
end
local actor = requested == nil and tonumber(player and player.actor_address) or
  tonumber(bot and bot.actor_address)
actor = actor or 0
local local_flags = tonumber(player and player.persistent_status_flags) or 0
emit('actor', actor)
emit('runtime_available', runtime ~= nil)
emit('runtime_flags', runtime and runtime.persistent_status_flags or 0)
emit('local_flags', requested == nil and local_flags or 0)
emit('replicated_flags', bot and bot.replicated_persistent_status_flags or local_flags)
emit('native_flags', bot and bot.native_persistent_status_flags or local_flags)
emit('hp', requested == nil and (player and player.hp or 0) or (bot and bot.hp or 0))
emit('max_hp', requested == nil and (player and player.max_hp or 0) or (bot and bot.max_hp or 0))
emit('mp', requested == nil and (player and player.mp or 0) or (bot and bot.mp or 0))
emit('max_mp', requested == nil and (player and player.max_mp or 0) or (bot and bot.max_mp or 0))
emit('x', requested == nil and (player and player.x or 0) or (bot and bot.x or 0))
emit('y', requested == nil and (player and player.y or 0) or (bot and bot.y or 0))
emit('progression', requested == nil and
  (player and player.progression_address or 0) or
  (bot and bot.progression_runtime_state_address or 0))
emit('ok', actor ~= 0 and runtime ~= nil)
"""
    values = parse_key_values(lua(pipe_name, code, timeout=timeout))
    if values.get("ok") != "true":
        raise VerifyFailure(
            f"persistent status unavailable pipe={pipe_name} "
            f"participant={participant_id}: {values}"
        )
    return {
        "participant_id": participant_id,
        "actor_address": parse_int_text(values.get("actor"), 0),
        "progression_address": parse_int_text(values.get("progression"), 0),
        "local_flags": parse_int_text(values.get("local_flags"), 0),
        "runtime_flags": parse_int_text(values.get("runtime_flags"), 0),
        "replicated_flags": parse_int_text(values.get("replicated_flags"), 0),
        "native_flags": parse_int_text(values.get("native_flags"), 0),
        "hp": _as_float(values, "hp"),
        "max_hp": _as_float(values, "max_hp"),
        "mp": _as_float(values, "mp"),
        "max_mp": _as_float(values, "max_mp"),
        "x": _as_float(values, "x"),
        "y": _as_float(values, "y"),
        "raw": values,
    }


def wait_for_persistent_status(
    owner_pipe: str,
    observer_pipe: str,
    participant_id: int,
    expected_values: int,
    *,
    timeout: float,
) -> dict[str, Any]:
    """Wait until the owner's native state and every observer layer agree."""

    if expected_values & ~PERSISTENT_VALUE_MASK:
        raise ValueError(f"invalid persistent status values: {expected_values:#x}")
    expected_flags = PERSISTENT_SNAPSHOT_VALID | expected_values
    deadline = time.monotonic() + timeout
    owner: dict[str, Any] = {}
    observer: dict[str, Any] = {}
    attempts = 0
    while time.monotonic() < deadline:
        attempts += 1
        owner = query_persistent_status(owner_pipe)
        observer = query_persistent_status(
            observer_pipe,
            participant_id=participant_id,
        )
        compared = (
            owner["local_flags"],
            owner["runtime_flags"],
            observer["runtime_flags"],
            observer["replicated_flags"],
            observer["native_flags"],
        )
        if all(flags == expected_flags for flags in compared):
            return {
                "expected_flags": expected_flags,
                "attempt_count": attempts,
                "owner": owner,
                "observer": observer,
            }
        time.sleep(0.05)
    raise VerifyFailure(
        f"participant {participant_id} persistent status did not converge to "
        f"{expected_flags:#x}: owner={owner} observer={observer}"
    )


def arm_native_factory_trace(pipe_name: str, trace_name: str) -> dict[str, str]:
    escaped_name = json.dumps(trace_name)
    values = parse_key_values(
        lua(
            pipe_name,
            f"""
pcall(sd.debug.untrace_function, {NATIVE_OBJECT_FACTORY})
sd.debug.clear_trace_hits({escaped_name})
local ok = sd.debug.trace_function({NATIVE_OBJECT_FACTORY}, {escaped_name})
print('ok=' .. tostring(ok))
print('error=' .. tostring(sd.debug.get_last_error and sd.debug.get_last_error() or ''))
""",
        )
    )
    if values.get("ok") != "true":
        raise VerifyFailure(
            f"could not arm native object factory trace on {pipe_name}: {values}"
        )
    return values


def sample_native_factory_trace(pipe_name: str, trace_name: str) -> dict[str, Any]:
    escaped_name = json.dumps(trace_name)
    values = parse_key_values(
        lua(
            pipe_name,
            f"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
local hits = sd.debug.get_trace_hits and sd.debug.get_trace_hits({escaped_name}) or {{}}
local counts = {{}}
local firewalker_returns = {{}}
for _, hit in ipairs(hits) do
  local type_id = tonumber(hit.arg0) or -1
  counts[type_id] = (counts[type_id] or 0) + 1
  if type_id == {FIREWALKER_TRAIL_NATIVE_TYPE} then
    local return_address = tonumber(hit.ret) or 0
    firewalker_returns[return_address] =
      (firewalker_returns[return_address] or 0) + 1
  end
end
local types = {{}}
for type_id, _ in pairs(counts) do table.insert(types, type_id) end
table.sort(types)
local returns = {{}}
for return_address, _ in pairs(firewalker_returns) do
  table.insert(returns, return_address)
end
table.sort(returns)
emit('factory_call_count', #hits)
emit('type_total_count', #types)
for index, type_id in ipairs(types) do
  emit('type.' .. tostring(index) .. '.id', type_id)
  emit('type.' .. tostring(index) .. '.count', counts[type_id])
end
emit('firewalker_return_total_count', #returns)
for index, return_address in ipairs(returns) do
  emit('firewalker_return.' .. tostring(index) .. '.address', return_address)
  emit(
    'firewalker_return.' .. tostring(index) .. '.count',
    firewalker_returns[return_address])
end
""",
        )
    )
    type_counts: dict[int, int] = {}
    for index in range(1, parse_int_text(values.get("type_total_count"), 0) + 1):
        type_id = parse_int_text(values.get(f"type.{index}.id"), -1)
        count = parse_int_text(values.get(f"type.{index}.count"), 0)
        type_counts[type_id] = count
    firewalker_return_counts: dict[int, int] = {}
    for index in range(
        1,
        parse_int_text(values.get("firewalker_return_total_count"), 0) + 1,
    ):
        return_address = parse_int_text(
            values.get(f"firewalker_return.{index}.address"),
            0,
        )
        firewalker_return_counts[return_address] = parse_int_text(
            values.get(f"firewalker_return.{index}.count"),
            0,
        )
    return {
        "factory_call_count": parse_int_text(values.get("factory_call_count"), 0),
        "type_counts": type_counts,
        "firewalker_return_counts": firewalker_return_counts,
        "raw": values,
    }


def clear_native_factory_trace(pipe_name: str, trace_name: str) -> dict[str, str]:
    escaped_name = json.dumps(trace_name)
    return parse_key_values(
        lua(
            pipe_name,
            f"""
pcall(sd.debug.untrace_function, {NATIVE_OBJECT_FACTORY})
sd.debug.clear_trace_hits({escaped_name})
print('ok=true')
""",
        )
    )


def query_firewalker_native_actors(pipe_name: str) -> dict[str, Any]:
    """Read every live stock Firewalker trail actor in one process."""

    values = parse_key_values(
        lua(
            pipe_name,
            f"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
local trail_type = {FIREWALKER_TRAIL_NATIVE_TYPE}
local function off(name) return tonumber(sd.debug.layout_offset(name)) or 0 end
local actors = sd.world and sd.world.list_actors and sd.world.list_actors() or {{}}
local count = 0
local positive_lifetime_count = 0
local finite_position_count = 0
local max_damage = 0
for _, actor in ipairs(actors or {{}}) do
  if tonumber(actor.object_type_id) == trail_type then
    count = count + 1
    local address = tonumber(actor.actor_address) or 0
    local lifetime = address ~= 0 and
      tonumber(sd.debug.read_float(address + off('firewalker_lifetime'))) or 0
    local damage = address ~= 0 and
      tonumber(sd.debug.read_float(address + off('firewalker_damage'))) or 0
    local source = address ~= 0 and
      tonumber(sd.debug.read_u8(address + off('firewalker_source_slot'))) or 255
    if source > 127 then source = source - 256 end
    if lifetime > 0 then positive_lifetime_count = positive_lifetime_count + 1 end
    if tonumber(actor.x) ~= nil and tonumber(actor.y) ~= nil then
      finite_position_count = finite_position_count + 1
    end
    if damage > max_damage then max_damage = damage end
    if count <= 16 then
      local prefix = 'actor.' .. tostring(count) .. '.'
      emit(prefix .. 'address', address)
      emit(prefix .. 'slot', actor.actor_slot or -999)
      emit(prefix .. 'source_slot', source)
      emit(prefix .. 'x', actor.x or 0)
      emit(prefix .. 'y', actor.y or 0)
      emit(prefix .. 'lifetime', lifetime)
      emit(prefix .. 'damage', damage)
      emit(prefix .. 'visual_scale', address ~= 0 and
        sd.debug.read_float(address + off('firewalker_visual_scale')) or 0)
      emit(prefix .. 'variant', address ~= 0 and
        sd.debug.read_u8(address + off('firewalker_variant')) or 0)
    end
  end
end
emit('count', count)
emit('positive_lifetime_count', positive_lifetime_count)
emit('finite_position_count', finite_position_count)
emit('max_damage', max_damage)
""",
        )
    )
    return {
        "count": parse_int_text(values.get("count"), 0),
        "positive_lifetime_count": parse_int_text(
            values.get("positive_lifetime_count"),
            0,
        ),
        "finite_position_count": parse_int_text(
            values.get("finite_position_count"),
            0,
        ),
        "max_damage": _as_float(values, "max_damage"),
        "raw": values,
    }


def query_replicated_firewalker_sync(
    pipe_name: str,
    owner_participant_id: int,
) -> dict[str, str]:
    """Compare owner-authored Firewalker snapshots with observer-native actors."""

    values = parse_key_values(
        lua(
            pipe_name,
            f"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
local owner_id = {owner_participant_id}
local trail_type = {FIREWALKER_TRAIL_NATIVE_TYPE}
local function off(name) return tonumber(sd.debug.layout_offset(name)) or 0 end
local function read_f(address, name)
  return tonumber(sd.debug.read_float(address + off(name))) or 0
end
local function read_u8(address, name)
  return tonumber(sd.debug.read_u8(address + off(name))) or 0
end
local function read_i32(address, name)
  return tonumber(sd.debug.read_i32(address + off(name))) or 0
end
local function read_u32(address, name)
  return tonumber(sd.debug.read_u32(address + off(name))) or 0
end
local root = sd.world and sd.world.get_replicated_spell_effects and
  sd.world.get_replicated_spell_effects() or nil
emit('available', root ~= nil)
if root == nil then return end

local effects = {{}}
local snapshot_count = 0
local snapshot_active_count = 0
local snapshot_terminal_count = 0
local snapshot_runtime_count = 0
for _, snapshot in ipairs(root.snapshots or {{}}) do
  if tonumber(snapshot.owner_participant_id) == owner_id then
    emit('snapshot.sequence', snapshot.sequence or 0)
    emit('snapshot.truncated', snapshot.truncated or false)
    for _, effect in ipairs(snapshot.effects or {{}}) do
      if tonumber(effect.native_type_id) == trail_type then
        snapshot_count = snapshot_count + 1
        effects[tonumber(effect.effect_serial) or 0] = effect
        if effect.active then snapshot_active_count = snapshot_active_count + 1 end
        if effect.terminal then snapshot_terminal_count = snapshot_terminal_count + 1 end
        if effect.firewalker_runtime_valid then
          snapshot_runtime_count = snapshot_runtime_count + 1
        end
      end
    end
  end
end
emit('snapshot.count', snapshot_count)
emit('snapshot.active_count', snapshot_active_count)
emit('snapshot.terminal_count', snapshot_terminal_count)
emit('snapshot.runtime_count', snapshot_runtime_count)

local apply = root.apply or {{}}
for _, key in ipairs({{
  'matched_firewalker_effect_count','created_firewalker_effect_count',
  'max_matched_firewalker_effect_count','firewalker_runtime_write_count',
  'terminal_write_count','cumulative_firewalker_create_count',
  'cumulative_firewalker_runtime_write_count','cumulative_terminal_write_count'
}}) do emit('apply.' .. key, apply[key] or 0) end

local binding_count = 0
local matched_count = 0
local source_mismatch_count = 0
local runtime_mismatch_count = 0
local max_position_error = 0
local max_phase_error = 0
local max_lifetime_error = 0
for _, binding in ipairs(apply.bindings or {{}}) do
  if tonumber(binding.owner_participant_id) == owner_id and
     tonumber(binding.native_type_id) == trail_type then
    binding_count = binding_count + 1
    if binding.matched then matched_count = matched_count + 1 end
    local error_value = tonumber(binding.position_error) or 0
    if error_value > max_position_error then max_position_error = error_value end
    local address = tonumber(binding.local_actor_address) or 0
    local effect = effects[tonumber(binding.effect_serial) or 0]
    if address ~= 0 and effect ~= nil then
      local source = read_u8(address, 'firewalker_source_slot')
      if source > 127 then source = source - 256 end
      if source ~= tonumber(binding.owner_gameplay_slot) then
        source_mismatch_count = source_mismatch_count + 1
      end
      local phase_error = math.abs(
        read_f(address, 'firewalker_phase') -
        (tonumber(effect.firewalker_phase) or 0))
      local lifetime_error = math.abs(
        read_f(address, 'firewalker_lifetime') -
        (tonumber(effect.firewalker_lifetime) or 0))
      if phase_error > max_phase_error then max_phase_error = phase_error end
      if lifetime_error > max_lifetime_error then
        max_lifetime_error = lifetime_error
      end
      local exact =
        math.abs(read_f(address, 'firewalker_collision_scale') -
          (tonumber(effect.firewalker_collision_scale) or 0)) <= 0.001 and
        math.abs(read_f(address, 'firewalker_phase_step') -
          (tonumber(effect.firewalker_phase_step) or 0)) <= 0.001 and
        math.abs(read_f(address, 'firewalker_fade') -
          (tonumber(effect.firewalker_fade) or 0)) <= 0.001 and
        math.abs(read_f(address, 'firewalker_direction') -
          (tonumber(effect.firewalker_direction) or 0)) <= 0.001 and
        math.abs(read_f(address, 'firewalker_visual_scale') -
          (tonumber(effect.firewalker_visual_scale) or 0)) <= 0.001 and
        math.abs(read_f(address, 'firewalker_damage') -
          (tonumber(effect.firewalker_damage) or 0)) <= 0.001 and
        read_u8(address, 'firewalker_active') ==
          (tonumber(effect.firewalker_active) or 0) and
        read_i32(address, 'firewalker_aux') ==
          (tonumber(effect.firewalker_aux) or 0) and
        read_u8(address, 'firewalker_variant') ==
          (tonumber(effect.firewalker_variant) or 0) and
        read_u32(address, 'firewalker_damage_mask') ==
          (tonumber(effect.firewalker_damage_mask) or 0)
      if not exact then runtime_mismatch_count = runtime_mismatch_count + 1 end
      if binding_count <= 16 then
        local prefix = 'binding.' .. tostring(binding_count) .. '.'
        emit(prefix .. 'serial', binding.effect_serial or 0)
        emit(prefix .. 'actor', address)
        emit(prefix .. 'owner_gameplay_slot', binding.owner_gameplay_slot or -999)
        emit(prefix .. 'local_actor_slot', binding.local_actor_slot or -999)
        emit(prefix .. 'source_slot', source)
        emit(prefix .. 'position_error', error_value)
        emit(prefix .. 'phase_error', phase_error)
        emit(prefix .. 'lifetime_error', lifetime_error)
      end
    end
  end
end
emit('binding.count', binding_count)
emit('binding.matched_count', matched_count)
emit('binding.source_mismatch_count', source_mismatch_count)
emit('binding.runtime_mismatch_count', runtime_mismatch_count)
emit('binding.max_position_error', max_position_error)
emit('binding.max_phase_error', max_phase_error)
emit('binding.max_lifetime_error', max_lifetime_error)

local native_count = 0
for _, actor in ipairs(sd.world.list_actors() or {{}}) do
  if tonumber(actor.object_type_id) == trail_type then native_count = native_count + 1 end
end
emit('native.count', native_count)
""",
        )
    )
    return values
