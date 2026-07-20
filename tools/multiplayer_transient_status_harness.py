#!/usr/bin/env python3
"""Exact-native helpers for multiplayer transient-status verification."""

from __future__ import annotations

import math
import time
from typing import Any

from verify_local_multiplayer_sync import VerifyFailure, lua, parse_int_text, parse_key_values


MOD_POISONED_TYPE_ID = 0x1B72

ACTOR_MOD_LIST_COUNT_OFFSET = 0x10C
ACTOR_MOD_LIST_STORAGE_OFFSET = 0x118
MOD_TYPE_ID_OFFSET = 0x08
MOD_DURATION_OFFSET = 0x14
MOD_POISON_DAMAGE_OFFSET = 0x1C
MOD_POISON_SOURCE_SLOT_OFFSET = 0x20

TRANSIENT_POISONED = 1 << 0
TRANSIENT_SNAPSHOT_VALID = 1 << 7


def _values(pipe_name: str, code: str, timeout: float = 10.0) -> dict[str, str]:
    return parse_key_values(lua(pipe_name, code, timeout=timeout))


def _as_float(values: dict[str, str], key: str) -> float:
    try:
        return float(values.get(key, "nan"))
    except ValueError:
        return math.nan


def inject_native_poison_status(
    pipe_name: str,
    *,
    duration_ticks: int,
    damage_per_tick: float,
    source_slot: int = 0,
    label: str,
    participant_id: int | None = None,
) -> dict[str, Any]:
    """Install one stock Mod_Poisoned on a local or materialized wizard."""

    if duration_ticks < 1 or duration_ticks > 100_000:
        raise ValueError(f"duration_ticks must be in [1,100000], got {duration_ticks}")
    if source_slot < -1 or source_slot > 127:
        raise ValueError(f"source_slot must be in [-1,127], got {source_slot}")
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
local actor = requested == nil and tonumber(player and player.actor_address) or
  tonumber(bot and bot.actor_address)
actor = actor or 0
local count = actor ~= 0 and
  (tonumber(sd.debug.read_i32(actor + 0x{ACTOR_MOD_LIST_COUNT_OFFSET:X})) or 0) or 0
local storage = actor ~= 0 and
  (tonumber(sd.debug.read_ptr(actor + 0x{ACTOR_MOD_LIST_STORAGE_OFFSET:X})) or 0) or 0
local existing = 0
if count > 0 and count < 512 and storage ~= 0 then
  for index = 0, count - 1 do
    local control = tonumber(sd.debug.read_ptr(storage + index * 4)) or 0
    local object = control ~= 0 and (tonumber(sd.debug.read_ptr(control)) or 0) or 0
    local type_id = object ~= 0 and
      (tonumber(sd.debug.read_u32(object + 0x{MOD_TYPE_ID_OFFSET:X})) or 0) or 0
    if type_id == 0x{MOD_POISONED_TYPE_ID:X} then existing = existing + 1 end
  end
end
emit('actor', actor)
emit('existing', existing)
if actor == 0 or existing ~= 0 then
  emit('ok', false)
  emit('error', 'poison injection prerequisites unavailable')
  return
end
local queued, err = sd.debug.queue_native_poison_behavior_probe(
  requested or 0, {duration_ticks}, {damage_per_tick:.9f}, {source_slot})
emit('queued', queued)
emit('error', err or '')
emit('ok', queued == true)
"""
    raw = _values(pipe_name, code, timeout=15.0)
    if raw.get("ok") != "true":
        raise VerifyFailure(f"native poison injection failed {label}: {raw}")

    deadline = time.monotonic() + 10.0
    active: dict[str, Any] = {}
    while time.monotonic() < deadline:
        active = query_poison_status(pipe_name, participant_id=participant_id)
        if active["poison_count"] == 1 and active["modifier_ticks"] > 0:
            break
        time.sleep(0.02)
    else:
        raise VerifyFailure(
            f"queued native poison injection did not materialize {label}: "
            f"queue={raw} active={active}"
        )
    return {
        "label": label,
        "participant_id": participant_id,
        "actor_address": active["actor_address"],
        "modifier_address": active["modifier_address"],
        "control_block_address": active["control_block_address"],
        "duration_after_apply": active["modifier_ticks"],
        "refs_before_add": active["control_refs"],
        "refs_after_add": active["control_refs"],
        "active": active,
        "raw": raw,
    }


def query_poison_status(
    pipe_name: str,
    *,
    participant_id: int | None = None,
) -> dict[str, Any]:
    """Read protocol, bot snapshot, and exact native poison state."""

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
local actor = requested == nil and tonumber(player and player.actor_address) or
  tonumber(bot and bot.actor_address)
actor = actor or 0
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

local count = actor ~= 0 and
  (tonumber(sd.debug.read_i32(actor + 0x{ACTOR_MOD_LIST_COUNT_OFFSET:X})) or 0) or 0
local storage = actor ~= 0 and
  (tonumber(sd.debug.read_ptr(actor + 0x{ACTOR_MOD_LIST_STORAGE_OFFSET:X})) or 0) or 0
local poison_count = 0
local poison = 0
local control = 0
if count > 0 and count < 512 and storage ~= 0 then
  for index = 0, count - 1 do
    local candidate_control = tonumber(sd.debug.read_ptr(storage + index * 4)) or 0
    local candidate = candidate_control ~= 0 and
      (tonumber(sd.debug.read_ptr(candidate_control)) or 0) or 0
    local type_id = candidate ~= 0 and
      (tonumber(sd.debug.read_u32(candidate + 0x{MOD_TYPE_ID_OFFSET:X})) or 0) or 0
    if type_id == 0x{MOD_POISONED_TYPE_ID:X} then
      poison_count = poison_count + 1
      if poison == 0 then
        poison = candidate
        control = candidate_control
      end
    end
  end
end

local local_flags = player and tonumber(player.transient_status_flags) or 0
local local_ticks = player and tonumber(player.poison_remaining_ticks) or 0
emit('actor', actor)
emit('hp', requested == nil and (player and player.hp or 0) or (bot and bot.hp or 0))
emit('local_flags', requested == nil and local_flags or 0)
emit('local_ticks', requested == nil and local_ticks or 0)
emit('runtime_flags', runtime and runtime.transient_status_flags or 0)
emit('runtime_ticks', runtime and runtime.poison_remaining_ticks or 0)
emit('replicated_flags', bot and bot.replicated_transient_status_flags or local_flags)
emit('replicated_ticks', bot and bot.replicated_poison_remaining_ticks or local_ticks)
emit('native_flags', bot and bot.native_transient_status_flags or local_flags)
emit('native_ticks', bot and bot.native_poison_remaining_ticks or local_ticks)
emit('modifier_list_count', count)
emit('poison_count', poison_count)
emit('poison', poison)
emit('control', control)
emit('control_refs', control ~= 0 and sd.debug.read_i32(control + 4) or -1)
emit('modifier_ticks', poison ~= 0 and
  sd.debug.read_i32(poison + 0x{MOD_DURATION_OFFSET:X}) or 0)
emit('damage_per_tick', poison ~= 0 and
  sd.debug.read_float(poison + 0x{MOD_POISON_DAMAGE_OFFSET:X}) or 0)
emit('source_slot', poison ~= 0 and
  sd.debug.read_i8(poison + 0x{MOD_POISON_SOURCE_SLOT_OFFSET:X}) or -999)
emit('ok', actor ~= 0 and runtime ~= nil)
"""
    raw = _values(pipe_name, code)
    if raw.get("ok") != "true":
        raise VerifyFailure(
            f"poison status unavailable pipe={pipe_name} participant={participant_id}: {raw}"
        )
    return {
        "participant_id": participant_id,
        "actor_address": parse_int_text(raw.get("actor"), 0),
        "hp": _as_float(raw, "hp"),
        "local_flags": parse_int_text(raw.get("local_flags"), 0),
        "local_ticks": parse_int_text(raw.get("local_ticks"), 0),
        "runtime_flags": parse_int_text(raw.get("runtime_flags"), 0),
        "runtime_ticks": parse_int_text(raw.get("runtime_ticks"), 0),
        "replicated_flags": parse_int_text(raw.get("replicated_flags"), 0),
        "replicated_ticks": parse_int_text(raw.get("replicated_ticks"), 0),
        "native_flags": parse_int_text(raw.get("native_flags"), 0),
        "native_ticks": parse_int_text(raw.get("native_ticks"), 0),
        "modifier_list_count": parse_int_text(raw.get("modifier_list_count"), 0),
        "poison_count": parse_int_text(raw.get("poison_count"), 0),
        "modifier_address": parse_int_text(raw.get("poison"), 0),
        "control_block_address": parse_int_text(raw.get("control"), 0),
        "control_refs": parse_int_text(raw.get("control_refs"), -1),
        "modifier_ticks": parse_int_text(raw.get("modifier_ticks"), 0),
        "damage_per_tick": _as_float(raw, "damage_per_tick"),
        "source_slot": parse_int_text(raw.get("source_slot"), -999),
        "raw": raw,
    }


def clear_local_native_poison_status(pipe_name: str) -> dict[str, Any]:
    """Expire every stock poison modifier on the local player."""

    code = f"""
local function emit(key, value)
  if value == nil then value = '<nil>' end
  print(key .. '=' .. tostring(value))
end
local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
local actor = player and tonumber(player.actor_address) or 0
local count = actor ~= 0 and
  (tonumber(sd.debug.read_i32(actor + 0x{ACTOR_MOD_LIST_COUNT_OFFSET:X})) or 0) or 0
local storage = actor ~= 0 and
  (tonumber(sd.debug.read_ptr(actor + 0x{ACTOR_MOD_LIST_STORAGE_OFFSET:X})) or 0) or 0
local found = 0
local cleared = 0
if count > 0 and count < 512 and storage ~= 0 then
  for index = 0, count - 1 do
    local control = tonumber(sd.debug.read_ptr(storage + index * 4)) or 0
    local object = control ~= 0 and (tonumber(sd.debug.read_ptr(control)) or 0) or 0
    local type_id = object ~= 0 and
      (tonumber(sd.debug.read_u32(object + 0x{MOD_TYPE_ID_OFFSET:X})) or 0) or 0
    if type_id == 0x{MOD_POISONED_TYPE_ID:X} then
      found = found + 1
      if sd.debug.write_i32(object + 0x{MOD_DURATION_OFFSET:X}, 0) == true then
        cleared = cleared + 1
      end
    end
  end
end
emit('actor', actor)
emit('found', found)
emit('cleared', cleared)
emit('ok', actor ~= 0 and found > 0 and cleared == found)
"""
    raw = _values(pipe_name, code)
    if raw.get("ok") != "true":
        raise VerifyFailure(f"failed to clear local poison status: {raw}")
    return {
        "found": parse_int_text(raw.get("found"), 0),
        "cleared": parse_int_text(raw.get("cleared"), 0),
        "raw": raw,
    }


def wait_for_poison_state(
    pipe_name: str,
    *,
    participant_id: int | None,
    poisoned: bool,
    timeout: float,
    maximum_tick_drift: int | None = None,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = query_poison_status(pipe_name, participant_id=participant_id)
        protocol_poisoned = bool(last["runtime_flags"] & TRANSIENT_POISONED)
        protocol_valid = bool(last["runtime_flags"] & TRANSIENT_SNAPSHOT_VALID)
        native_poisoned = bool(last["native_flags"] & TRANSIENT_POISONED)
        if poisoned:
            active = (
                protocol_valid
                and protocol_poisoned
                and native_poisoned
                and last["poison_count"] == 1
                and last["runtime_ticks"] > 0
                and last["native_ticks"] > 0
                and last["modifier_ticks"] > 0
            )
            duration_settled = (
                maximum_tick_drift is None
                or abs(last["native_ticks"] - last["runtime_ticks"])
                <= maximum_tick_drift
            )
            if active and duration_settled:
                return last
        elif (
            protocol_valid
            and not protocol_poisoned
            and not native_poisoned
            and last["poison_count"] == 0
            and last["runtime_ticks"] == 0
            and last["native_ticks"] == 0
        ):
            return last
        time.sleep(0.05)
    raise VerifyFailure(
        f"poison state did not converge pipe={pipe_name} participant={participant_id} "
        f"poisoned={poisoned} maximum_tick_drift={maximum_tick_drift}: {last}"
    )
