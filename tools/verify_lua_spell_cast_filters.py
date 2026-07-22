#!/usr/bin/env python3
"""Live verification for owner-side spell-cast filtering and retirement."""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any, Callable

from verify_local_multiplayer_sync import VerifyFailure, lua, parse_key_values


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "runtime" / "lua_spell_cast_filter_verification.json"
DEFAULT_PIPE = "SolomonDarkModLoader_LuaExec"
FIRE_PRIMARY_SKILL_ID = 1011
TEST_MANA = 100.0

REGISTER = r'''
if __lua_spell_filter_acceptance_registered == true then
  error("spell filter acceptance is already registered; restart the disposable process")
end

local scene = sd.world.get_scene and sd.world.get_scene() or nil
if type(scene) ~= "table" or tostring(scene.name or scene.kind or "") ~= "testrun" then
  error("spell filter acceptance requires a settled testrun")
end
if not sd.runtime.has_capability("events.filters.spell_cast") then
  error("events.filters.spell_cast is unavailable")
end
if (tonumber(sd.bots.get_count and sd.bots.get_count() or 0) or 0) ~= 0 then
  error("spell filter acceptance requires a disposable run with no bots")
end

local fireballs = 0
for _, actor in ipairs(sd.world.list_actors and sd.world.list_actors() or {}) do
  if tonumber(actor.object_type_id) == 0x7D4 then
    fireballs = fireballs + 1
  end
end
if fireballs ~= 0 then
  error("spell filter acceptance requires no existing Fireball objects")
end

__lua_spell_filter_acceptance_registered = true
__lua_spell_filter_phase = "idle"
__lua_spell_filter_bot_id = 0
__lua_spell_filter_target_x = 0
__lua_spell_filter_target_y = 0
__lua_spell_filter_first_count = 0
__lua_spell_filter_second_count = 0
__lua_spell_filter_phase_counts = {
  local_cancel = {first = 0, second = 0},
  local_allow = {first = 0, second = 0},
  cancel = {first = 0, second = 0},
  allow = {first = 0, second = 0},
}
__lua_spell_filter_payloads = {}
__lua_spell_filter_order = {}
__lua_spell_filter_seen_fireballs = {}
__lua_spell_filter_max_fireballs = 0

local function phase_row()
  local phase = tostring(__lua_spell_filter_phase or "")
  return phase, __lua_spell_filter_phase_counts[phase]
end

sd.events.filter("spell.casting", function(event)
  local phase, counts = phase_row()
  __lua_spell_filter_first_count = __lua_spell_filter_first_count + 1
  if counts ~= nil then
    counts.first = counts.first + 1
  end
  __lua_spell_filter_order[#__lua_spell_filter_order + 1] = phase .. ":first"
  __lua_spell_filter_payloads[phase] = {
    event = event.event,
    caster_participant_id = event.caster_participant_id,
    caster_actor_address = event.caster_actor_address,
    kind = event.kind,
    skill_id = event.skill_id,
    secondary_slot = event.secondary_slot,
    x = event.x,
    y = event.y,
    direction_x = event.direction_x,
    direction_y = event.direction_y,
    target_actor_address = event.target_actor_address,
    aim_target_x = event.aim_target_x,
    aim_target_y = event.aim_target_y,
  }
  return true
end)

sd.events.filter("spell.casting", function(event)
  local phase, counts = phase_row()
  __lua_spell_filter_second_count = __lua_spell_filter_second_count + 1
  if counts ~= nil then
    counts.second = counts.second + 1
  end
  __lua_spell_filter_order[#__lua_spell_filter_order + 1] = phase .. ":second"
  if phase == "cancel" or phase == "local_cancel" then
    return false
  end
  return nil
end)

print("registered=true")
print("capability=true")
print("scene=" .. tostring(scene.name or scene.kind or ""))
'''

CREATE_BOT = r'''
local phase = %s
local player = assert(sd.player.get_state(), "local player is unavailable")
local primary = assert(
  sd.bots.resolve_primary_entry(0),
  "native Fire primary entry is unavailable")
local x = (tonumber(player.x) or 0) + 96
local y = tonumber(player.y) or 0
local target_x = x + 320
local target_y = y
local id = sd.bots.create({
  name = "Spell Filter " .. phase,
  profile = {
    element_id = 0,
    discipline_id = 1,
    level = 1,
    experience = 0,
    loadout = {
      primary_entry_index = primary,
      primary_combo_entry_index = primary,
      secondary_entry_indices = {-1, -1, -1},
    },
  },
  scene = {kind = "run"},
  ready = true,
  heading = 90,
  position = {x = x, y = y},
})
assert(id ~= nil, "sd.bots.create failed")
__lua_spell_filter_phase = phase
__lua_spell_filter_bot_id = id
__lua_spell_filter_target_x = target_x
__lua_spell_filter_target_y = target_y
print("created=true")
print("phase=" .. phase)
print("bot_id=" .. tostring(id))
print("target_x=" .. tostring(target_x))
print("target_y=" .. tostring(target_y))
'''

PREPARE_BOT = rf'''
local id = assert(__lua_spell_filter_bot_id, "bot id is unavailable")
local bot = assert(sd.bots.get_state(id), "bot state is unavailable")
local actor = tonumber(bot.actor_address) or 0
local progression = tonumber(bot.progression_runtime_state_address) or 0
assert(actor ~= 0, "bot actor is not materialized")
assert(progression ~= 0, "bot progression is not materialized")
local mp_offset = assert(sd.debug.layout_offset("progression_mp"))
local max_mp_offset = assert(sd.debug.layout_offset("progression_max_mp"))
local max_ok = sd.debug.write_float(progression + max_mp_offset, {TEST_MANA})
local mp_ok = sd.debug.write_float(progression + mp_offset, {TEST_MANA})
print("prepared=" .. tostring(max_ok and mp_ok))
print("actor_address=" .. tostring(actor))
print("progression_address=" .. tostring(progression))
print("mp=" .. tostring(sd.debug.read_float(progression + mp_offset)))
print("max_mp=" .. tostring(sd.debug.read_float(progression + max_mp_offset)))
'''

QUEUE_CAST = rf'''
local id = assert(__lua_spell_filter_bot_id, "bot id is unavailable")
local ok = sd.bots.cast({{
  id = id,
  kind = "primary",
  skill_id = {FIRE_PRIMARY_SKILL_ID},
  target = {{
    x = __lua_spell_filter_target_x,
    y = __lua_spell_filter_target_y,
  }},
}})
print("queued=" .. tostring(ok))
print("bot_id=" .. tostring(id))
'''

STATUS = r'''
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end

local phase = tostring(__lua_spell_filter_phase or "idle")
local counts = (__lua_spell_filter_phase_counts or {})[phase] or {}
local payload = (__lua_spell_filter_payloads or {})[phase] or {}
local id = tonumber(__lua_spell_filter_bot_id) or 0
local bot = id ~= 0 and sd.bots.get_state(id) or nil

emit("phase", phase)
emit("bot_id", id)
emit("first_count", __lua_spell_filter_first_count or 0)
emit("second_count", __lua_spell_filter_second_count or 0)
emit("phase_first_count", counts.first or 0)
emit("phase_second_count", counts.second or 0)
emit("order", table.concat(__lua_spell_filter_order or {}, ","))
emit("available", bot ~= nil)
emit("entity_materialized", bot and bot.entity_materialized or false)
emit("runtime_valid", bot and bot.runtime_valid or false)
emit("cast_ready", bot and bot.cast_ready or false)
emit("cast_pending", bot and bot.cast_pending or false)
emit("cast_active", bot and bot.cast_active or false)
emit("cast_skill_id", bot and bot.cast_skill_id or 0)
emit("active_spell_object_type", bot and bot.active_spell_object_type or 0)
emit("active_spell_object_address", bot and bot.active_spell_object_address or 0)

local actor = bot and (tonumber(bot.actor_address) or 0) or 0
local progression = bot and
  (tonumber(bot.progression_runtime_state_address) or 0) or 0
emit("actor_address", actor)
emit("progression_address", progression)
emit("mp", bot and bot.mp or 0)
emit("max_mp", bot and bot.max_mp or 0)

if actor ~= 0 then
  local function offset(name)
    return assert(sd.debug.layout_offset(name), "missing layout: " .. name)
  end
  emit("primary_skill_id", sd.debug.read_u32(
    actor + offset("actor_primary_skill_id")) or -1)
  emit("previous_skill_id", sd.debug.read_u32(
    actor + offset("actor_previous_skill_id")) or -1)
  emit("primary_latch_e4", sd.debug.read_u32(
    actor + offset("actor_primary_action_latch_e4")) or -1)
  emit("primary_latch_e8", sd.debug.read_u32(
    actor + offset("actor_primary_action_latch_e8")) or -1)
  emit("post_gate", sd.debug.read_u8(
    actor + offset("actor_post_gate_active_byte")) or -1)
  emit("active_group", sd.debug.read_u8(
    actor + offset("actor_active_cast_group_byte")) or -1)
  emit("active_slot", sd.debug.read_u16(
    actor + offset("actor_active_cast_slot_short")) or -1)
  emit("target_group", sd.debug.read_u8(
    actor + offset("actor_spell_target_group_byte")) or -1)
  emit("target_slot", sd.debug.read_u16(
    actor + offset("actor_spell_target_slot_short")) or -1)
end
if progression ~= 0 then
  emit("raw_mp", sd.debug.read_float(
    progression + assert(sd.debug.layout_offset("progression_mp"))) or -1)
end

local fireball_count = 0
for _, world_actor in ipairs(
    sd.world.list_actors and sd.world.list_actors() or {}) do
  if tonumber(world_actor.object_type_id) == 0x7D4 then
    fireball_count = fireball_count + 1
    local address = tonumber(world_actor.actor_address) or 0
    if address ~= 0 then
      __lua_spell_filter_seen_fireballs[address] = true
    end
  end
end
__lua_spell_filter_max_fireballs = math.max(
  tonumber(__lua_spell_filter_max_fireballs) or 0,
  fireball_count)
local seen_fireballs = {}
for address in pairs(__lua_spell_filter_seen_fireballs or {}) do
  seen_fireballs[#seen_fireballs + 1] = address
end
table.sort(seen_fireballs)
for index, address in ipairs(seen_fireballs) do
  seen_fireballs[index] = tostring(address)
end
emit("fireball_count", fireball_count)
emit("max_fireball_count", __lua_spell_filter_max_fireballs or 0)
emit("seen_fireball_addresses", table.concat(seen_fireballs, ","))

emit("payload_event", payload.event or "")
emit("payload_participant_id", payload.caster_participant_id or 0)
emit("payload_actor_address", payload.caster_actor_address or 0)
emit("payload_kind", payload.kind or "")
emit("payload_skill_id", payload.skill_id or 0)
emit("payload_secondary_slot", payload.secondary_slot or -1)
emit("payload_x", payload.x or "")
emit("payload_y", payload.y or "")
emit("payload_direction_x", payload.direction_x or "")
emit("payload_direction_y", payload.direction_y or "")
emit("payload_target_actor_address", payload.target_actor_address or 0)
emit("payload_aim_target_x", payload.aim_target_x or "")
emit("payload_aim_target_y", payload.aim_target_y or "")
emit("expected_target_x", __lua_spell_filter_target_x or 0)
emit("expected_target_y", __lua_spell_filter_target_y or 0)
'''

DESTROY_BOT = r'''
local id = tonumber(__lua_spell_filter_bot_id) or 0
local destroyed = id ~= 0 and sd.bots.destroy(id) or false
print("destroyed=" .. tostring(destroyed))
print("bot_id=" .. tostring(id))
__lua_spell_filter_bot_id = 0
'''

PREPARE_LOCAL = rf'''
local phase = %s
local player = assert(sd.player.get_state(), "local player is unavailable")
local progression = tonumber(player.progression_address) or 0
assert(progression ~= 0, "local player progression is unavailable")
local mp_offset = assert(sd.debug.layout_offset("progression_mp"))
local max_mp_offset = assert(sd.debug.layout_offset("progression_max_mp"))
assert(sd.debug.write_float(progression + max_mp_offset, {TEST_MANA}))
assert(sd.debug.write_float(progression + mp_offset, {TEST_MANA}))
__lua_spell_filter_phase = phase
__lua_spell_filter_local_min_mp = {TEST_MANA}
__lua_spell_filter_local_max_fireballs = 0
print("prepared=true")
print("phase=" .. phase)
print("actor_address=" .. tostring(player.actor_address or 0))
print("progression_address=" .. tostring(progression))
print("mp=" .. tostring(sd.debug.read_float(progression + mp_offset)))
'''

QUEUE_LOCAL_PRIMARY = r'''
local queued = sd.input.hold_mouse_left_frames(12)
print("queued=" .. tostring(queued))
'''

LOCAL_STATUS = r'''
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end

local function offset(name)
  return assert(sd.debug.layout_offset(name), "missing layout: " .. name)
end

local phase = tostring(__lua_spell_filter_phase or "idle")
local counts = (__lua_spell_filter_phase_counts or {})[phase] or {}
local payload = (__lua_spell_filter_payloads or {})[phase] or {}
local player = assert(sd.player.get_state(), "local player is unavailable")
local actor = tonumber(player.actor_address) or 0
local progression = tonumber(player.progression_address) or 0
local mp = tonumber(player.mp) or 0

local fireball_count = 0
for _, world_actor in ipairs(
    sd.world.list_actors and sd.world.list_actors() or {}) do
  if tonumber(world_actor.object_type_id) == 0x7D4 then
    fireball_count = fireball_count + 1
  end
end
__lua_spell_filter_local_min_mp = math.min(
  tonumber(__lua_spell_filter_local_min_mp) or mp,
  mp)
__lua_spell_filter_local_max_fireballs = math.max(
  tonumber(__lua_spell_filter_local_max_fireballs) or 0,
  fireball_count)

emit("phase", phase)
emit("phase_first_count", counts.first or 0)
emit("phase_second_count", counts.second or 0)
emit("order", table.concat(__lua_spell_filter_order or {}, ","))
emit("actor_address", actor)
emit("progression_address", progression)
emit("mp", mp)
emit("min_mp", __lua_spell_filter_local_min_mp)
emit("fireball_count", fireball_count)
emit("max_fireball_count", __lua_spell_filter_local_max_fireballs)

if actor ~= 0 then
  emit("primary_skill_id", sd.debug.read_u32(
    actor + offset("actor_primary_skill_id")) or -1)
  emit("previous_skill_id", sd.debug.read_u32(
    actor + offset("actor_previous_skill_id")) or -1)
  emit("primary_latch_e4", sd.debug.read_u32(
    actor + offset("actor_primary_action_latch_e4")) or -1)
  emit("primary_latch_e8", sd.debug.read_u32(
    actor + offset("actor_primary_action_latch_e8")) or -1)
  emit("post_gate", sd.debug.read_u8(
    actor + offset("actor_post_gate_active_byte")) or -1)
  emit("active_group", sd.debug.read_u8(
    actor + offset("actor_active_cast_group_byte")) or -1)
  emit("active_slot", sd.debug.read_u16(
    actor + offset("actor_active_cast_slot_short")) or -1)
  emit("target_group", sd.debug.read_u8(
    actor + offset("actor_spell_target_group_byte")) or -1)
  emit("target_slot", sd.debug.read_u16(
    actor + offset("actor_spell_target_slot_short")) or -1)
end
if progression ~= 0 then
  emit("raw_mp", sd.debug.read_float(
    progression + offset("progression_mp")) or -1)
end

emit("payload_event", payload.event or "")
emit("payload_participant_id", payload.caster_participant_id or 0)
emit("payload_actor_address", payload.caster_actor_address or 0)
emit("payload_kind", payload.kind or "")
emit("payload_skill_id", payload.skill_id or 0)
emit("payload_secondary_slot", payload.secondary_slot or -1)
emit("payload_x", payload.x or "")
emit("payload_y", payload.y or "")
emit("payload_direction_x", payload.direction_x or "")
emit("payload_direction_y", payload.direction_y or "")
emit("payload_target_actor_address", payload.target_actor_address or 0)
emit("payload_aim_target_x", payload.aim_target_x or "")
emit("payload_aim_target_y", payload.aim_target_y or "")
'''

RESET_BOT_ACCEPTANCE = r'''
__lua_spell_filter_phase = "idle"
__lua_spell_filter_first_count = 0
__lua_spell_filter_second_count = 0
__lua_spell_filter_phase_counts.cancel = {first = 0, second = 0}
__lua_spell_filter_phase_counts.allow = {first = 0, second = 0}
__lua_spell_filter_payloads.cancel = nil
__lua_spell_filter_payloads.allow = nil
__lua_spell_filter_order = {}
__lua_spell_filter_seen_fireballs = {}
__lua_spell_filter_max_fireballs = 0
print("reset=true")
'''


def _integer(values: dict[str, str], key: str) -> int:
    try:
        return int(values.get(key, ""), 0)
    except ValueError as exc:
        raise VerifyFailure(f"invalid integer {key}: {values}") from exc


def _number(values: dict[str, str], key: str) -> float:
    try:
        value = float(values.get(key, "nan"))
    except ValueError as exc:
        raise VerifyFailure(f"invalid number {key}: {values}") from exc
    if not math.isfinite(value):
        raise VerifyFailure(f"non-finite number {key}: {values}")
    return value


def _status(pipe_name: str) -> dict[str, str]:
    return parse_key_values(lua(pipe_name, STATUS, timeout=8.0))


def _local_status(pipe_name: str) -> dict[str, str]:
    return parse_key_values(lua(pipe_name, LOCAL_STATUS, timeout=8.0))


def _wait_for(
    pipe_name: str,
    predicate: Callable[[dict[str, str]], bool],
    timeout: float,
    description: str,
    *,
    interval: float = 0.05,
    status_reader: Callable[[str], dict[str, str]] = _status,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = status_reader(pipe_name)
        if predicate(last):
            return last
        time.sleep(interval)
    raise VerifyFailure(f"timed out waiting for {description}: {last}")


def _create_bot(pipe_name: str, phase: str, timeout: float) -> dict[str, str]:
    created = parse_key_values(
        lua(pipe_name, CREATE_BOT % json.dumps(phase), timeout=10.0)
    )
    if created.get("created") != "true" or _integer(created, "bot_id") == 0:
        raise VerifyFailure(f"{phase} bot creation failed: {created}")
    ready = _wait_for(
        pipe_name,
        lambda row: (
            row.get("phase") == phase
            and row.get("available") == "true"
            and row.get("entity_materialized") == "true"
            and _integer(row, "actor_address") != 0
            and _integer(row, "progression_address") != 0
        ),
        timeout,
        f"the {phase} bot to materialize",
    )
    prepared = parse_key_values(lua(pipe_name, PREPARE_BOT, timeout=8.0))
    if prepared.get("prepared") != "true":
        raise VerifyFailure(f"{phase} bot mana preparation failed: {prepared}")
    if abs(_number(prepared, "mp") - TEST_MANA) > 0.01:
        raise VerifyFailure(f"{phase} bot mana did not settle: {prepared}")
    return {"created": created, "ready": ready, "prepared": prepared}


def _queue_cast(pipe_name: str, phase: str) -> dict[str, str]:
    queued = parse_key_values(lua(pipe_name, QUEUE_CAST, timeout=8.0))
    if queued.get("queued") != "true":
        raise VerifyFailure(f"{phase} bot cast failed to queue: {queued}")
    return queued


def _assert_payload(status: dict[str, str], phase: str) -> None:
    bot_id = _integer(status, "bot_id")
    actor_address = _integer(status, "actor_address")
    expected = {
        "payload_event": "spell.casting",
        "payload_kind": "primary",
        "payload_skill_id": str(FIRE_PRIMARY_SKILL_ID),
        "payload_participant_id": str(bot_id),
        "payload_actor_address": str(actor_address),
        "payload_secondary_slot": "-1",
        "payload_target_actor_address": "0",
    }
    mismatches = {
        key: {"expected": value, "actual": status.get(key)}
        for key, value in expected.items()
        if status.get(key) != value
    }
    if mismatches:
        raise VerifyFailure(f"{phase} payload identity mismatch: {mismatches}")
    for key in (
        "payload_x",
        "payload_y",
        "payload_direction_x",
        "payload_direction_y",
        "payload_aim_target_x",
        "payload_aim_target_y",
    ):
        _number(status, key)
    if abs(
        _number(status, "payload_aim_target_x")
        - _number(status, "expected_target_x")
    ) > 0.01 or abs(
        _number(status, "payload_aim_target_y")
        - _number(status, "expected_target_y")
    ) > 0.01:
        raise VerifyFailure(f"{phase} payload lost the requested aim target: {status}")


def _destroy_bot(pipe_name: str, phase: str) -> dict[str, str]:
    destroyed = parse_key_values(lua(pipe_name, DESTROY_BOT, timeout=8.0))
    if destroyed.get("destroyed") != "true":
        raise VerifyFailure(f"{phase} bot cleanup failed: {destroyed}")
    time.sleep(0.2)
    return destroyed


def _prepare_local(pipe_name: str, phase: str) -> dict[str, str]:
    prepared = parse_key_values(
        lua(pipe_name, PREPARE_LOCAL % json.dumps(phase), timeout=8.0)
    )
    if prepared.get("prepared") != "true":
        raise VerifyFailure(f"{phase} local preparation failed: {prepared}")
    if abs(_number(prepared, "mp") - TEST_MANA) > 0.01:
        raise VerifyFailure(f"{phase} local mana did not settle: {prepared}")
    if _integer(prepared, "actor_address") == 0:
        raise VerifyFailure(f"{phase} local actor is unavailable: {prepared}")
    return prepared


def _queue_local_primary(pipe_name: str, phase: str) -> dict[str, str]:
    queued = parse_key_values(lua(pipe_name, QUEUE_LOCAL_PRIMARY, timeout=8.0))
    if queued.get("queued") != "true":
        raise VerifyFailure(f"{phase} local primary failed to queue: {queued}")
    return queued


def _assert_local_payload(status: dict[str, str], phase: str) -> None:
    expected = {
        "payload_event": "spell.casting",
        "payload_participant_id": "0",
        "payload_actor_address": status.get("actor_address"),
        "payload_kind": "primary",
        "payload_skill_id": str(FIRE_PRIMARY_SKILL_ID),
        "payload_secondary_slot": "-1",
        "payload_target_actor_address": "0",
    }
    mismatches = {
        key: {"expected": value, "actual": status.get(key)}
        for key, value in expected.items()
        if status.get(key) != value
    }
    if mismatches:
        raise VerifyFailure(f"{phase} local payload identity mismatch: {mismatches}")
    for key in (
        "payload_x",
        "payload_y",
        "payload_direction_x",
        "payload_direction_y",
    ):
        _number(status, key)
    aim_x = status.get("payload_aim_target_x", "")
    aim_y = status.get("payload_aim_target_y", "")
    if bool(aim_x) != bool(aim_y):
        raise VerifyFailure(f"{phase} local payload has a partial aim target: {status}")
    if aim_x:
        position_x = _number(status, "payload_x")
        position_y = _number(status, "payload_y")
        aim_target_x = _number(status, "payload_aim_target_x")
        aim_target_y = _number(status, "payload_aim_target_y")
        distance = math.hypot(
            aim_target_x - position_x,
            aim_target_y - position_y,
        )
        if (
            (abs(aim_target_x) < 0.001 and abs(aim_target_y) < 0.001)
            or distance < 1.0
            or distance > 4096.0
            or abs(aim_target_x) > 20000.0
            or abs(aim_target_y) > 20000.0
        ):
            raise VerifyFailure(
                f"{phase} local payload exposed an implausible aim target: {status}"
            )


def _run_local_acceptance(
    pipe_name: str,
    timeout: float,
    cancel_settle: float,
) -> dict[str, Any]:
    cancel_setup = _prepare_local(pipe_name, "local_cancel")
    cancel_queue = _queue_local_primary(pipe_name, "local_cancel")
    canceled = _wait_for(
        pipe_name,
        lambda row: (
            _integer(row, "phase_first_count") == 1
            and _integer(row, "phase_second_count") == 1
        ),
        timeout,
        "the canceled local primary to reach both handlers",
        interval=0.025,
        status_reader=_local_status,
    )
    settle_deadline = time.monotonic() + cancel_settle
    while time.monotonic() < settle_deadline:
        canceled = _local_status(pipe_name)
        time.sleep(0.05)
    if (
        _integer(canceled, "phase_first_count") != 1
        or _integer(canceled, "phase_second_count") != 1
        or canceled.get("order") != "local_cancel:first,local_cancel:second"
    ):
        raise VerifyFailure(
            f"canceled local primary did not filter exactly once: {canceled}"
        )
    _assert_local_payload(canceled, "local_cancel")
    if abs(_number(canceled, "raw_mp") - TEST_MANA) > 0.01:
        raise VerifyFailure(f"canceled local primary consumed mana: {canceled}")
    expected_retired = {
        "primary_skill_id": "0",
        "previous_skill_id": "0",
        "primary_latch_e4": "0",
        "primary_latch_e8": "0",
        "post_gate": "0",
        "active_group": "255",
        "active_slot": "65535",
        "target_group": "255",
        "target_slot": "65535",
        "max_fireball_count": "0",
    }
    leaked = {
        key: {"expected": expected, "actual": canceled.get(key)}
        for key, expected in expected_retired.items()
        if canceled.get(key) != expected
    }
    if leaked:
        raise VerifyFailure(f"canceled local primary leaked native state: {leaked}")

    allow_setup = _prepare_local(pipe_name, "local_allow")
    allow_queue = _queue_local_primary(pipe_name, "local_allow")
    allowed = _wait_for(
        pipe_name,
        lambda row: (
            _integer(row, "phase_first_count") == 1
            and _integer(row, "phase_second_count") == 1
            and (
                _number(row, "min_mp") < TEST_MANA - 0.01
                or _integer(row, "max_fireball_count") > 0
            )
        ),
        timeout,
        "the allowed local primary to reach native mana or projectile behavior",
        interval=0.025,
        status_reader=_local_status,
    )
    if (
        _integer(allowed, "phase_first_count") != 1
        or _integer(allowed, "phase_second_count") != 1
        or allowed.get("order")
        != (
            "local_cancel:first,local_cancel:second,"
            "local_allow:first,local_allow:second"
        )
    ):
        raise VerifyFailure(
            f"allowed local primary did not filter exactly once: {allowed}"
        )
    _assert_local_payload(allowed, "local_allow")
    native_mana_decreased = _number(allowed, "min_mp") < TEST_MANA - 0.01
    native_fireball_observed = _integer(allowed, "max_fireball_count") > 0
    if not native_mana_decreased and not native_fireball_observed:
        raise VerifyFailure(f"allowed local primary produced no native evidence: {allowed}")

    cleared = _wait_for(
        pipe_name,
        lambda row: _integer(row, "fireball_count") == 0,
        timeout,
        "the allowed local Fireball to retire before bot acceptance",
        status_reader=_local_status,
    )
    return {
        "cancel": {
            "setup": cancel_setup,
            "queue": cancel_queue,
            "settled": canceled,
            "settle_seconds": cancel_settle,
        },
        "allow": {
            "setup": allow_setup,
            "queue": allow_queue,
            "settled": allowed,
            "cleared": cleared,
            "native_mana_decreased": native_mana_decreased,
            "native_fireball_observed": native_fireball_observed,
        },
    }


def run(pipe_name: str, timeout: float, cancel_settle: float) -> dict[str, Any]:
    registration = parse_key_values(lua(pipe_name, REGISTER, timeout=12.0))
    if (
        registration.get("registered") != "true"
        or registration.get("capability") != "true"
        or registration.get("scene") != "testrun"
    ):
        raise VerifyFailure(f"spell filters failed to register: {registration}")

    local_acceptance = _run_local_acceptance(
        pipe_name,
        timeout,
        cancel_settle,
    )
    reset = parse_key_values(lua(pipe_name, RESET_BOT_ACCEPTANCE, timeout=8.0))
    if reset.get("reset") != "true":
        raise VerifyFailure(f"bot spell-filter acceptance reset failed: {reset}")

    cancel_setup = _create_bot(pipe_name, "cancel", timeout)
    cancel_queue = _queue_cast(pipe_name, "cancel")
    canceled = _wait_for(
        pipe_name,
        lambda row: (
            _integer(row, "first_count") == 1
            and _integer(row, "second_count") == 1
            and row.get("cast_pending") == "false"
            and row.get("cast_active") == "false"
        ),
        timeout,
        "the canceled cast request to retire",
    )

    settle_deadline = time.monotonic() + cancel_settle
    while time.monotonic() < settle_deadline:
        canceled = _status(pipe_name)
        time.sleep(0.05)

    if (
        _integer(canceled, "first_count") != 1
        or _integer(canceled, "second_count") != 1
        or _integer(canceled, "phase_first_count") != 1
        or _integer(canceled, "phase_second_count") != 1
        or canceled.get("order") != "cancel:first,cancel:second"
    ):
        raise VerifyFailure(f"canceled attempt did not filter exactly once: {canceled}")
    _assert_payload(canceled, "cancel")
    if abs(_number(canceled, "raw_mp") - TEST_MANA) > 0.01:
        raise VerifyFailure(f"canceled cast consumed native mana: {canceled}")
    expected_retired = {
        "cast_pending": "false",
        "cast_active": "false",
        "primary_skill_id": "0",
        "previous_skill_id": "0",
        "primary_latch_e4": "0",
        "primary_latch_e8": "0",
        "post_gate": "0",
        "active_group": "255",
        "active_slot": "65535",
        "target_group": "255",
        "target_slot": "65535",
        "fireball_count": "0",
        "max_fireball_count": "0",
        "seen_fireball_addresses": "",
    }
    leaked = {
        key: {"expected": expected, "actual": canceled.get(key)}
        for key, expected in expected_retired.items()
        if canceled.get(key) != expected
    }
    if leaked:
        raise VerifyFailure(f"canceled cast leaked native state: {leaked}")
    cancel_cleanup = _destroy_bot(pipe_name, "cancel")

    allow_setup = _create_bot(pipe_name, "allow", timeout)
    allow_queue = _queue_cast(pipe_name, "allow")
    allowed = _wait_for(
        pipe_name,
        lambda row: (
            _integer(row, "first_count") == 2
            and _integer(row, "second_count") == 2
            and (
                _number(row, "raw_mp") < TEST_MANA - 0.01
                or _integer(row, "max_fireball_count") > 0
            )
        ),
        timeout,
        "the allowed cast to reach native mana or projectile behavior",
        interval=0.025,
    )

    allow_settle_deadline = time.monotonic() + 0.5
    while time.monotonic() < allow_settle_deadline:
        allowed = _status(pipe_name)
        time.sleep(0.025)
    if (
        _integer(allowed, "first_count") != 2
        or _integer(allowed, "second_count") != 2
        or _integer(allowed, "phase_first_count") != 1
        or _integer(allowed, "phase_second_count") != 1
        or allowed.get("order")
        != "cancel:first,cancel:second,allow:first,allow:second"
    ):
        raise VerifyFailure(f"allowed attempt did not filter exactly once: {allowed}")
    _assert_payload(allowed, "allow")
    native_mana_decreased = _number(allowed, "raw_mp") < TEST_MANA - 0.01
    native_fireball_observed = _integer(allowed, "max_fireball_count") > 0
    if not native_mana_decreased and not native_fireball_observed:
        raise VerifyFailure(f"allowed cast produced no native evidence: {allowed}")
    allow_cleanup = _destroy_bot(pipe_name, "allow")

    return {
        "ok": True,
        "pipe": pipe_name,
        "registration": registration,
        "local": local_acceptance,
        "bot": {
            "reset": reset,
            "cancel": {
                "setup": cancel_setup,
                "queue": cancel_queue,
                "settled": canceled,
                "cleanup": cancel_cleanup,
                "settle_seconds": cancel_settle,
            },
            "allow": {
                "setup": allow_setup,
                "queue": allow_queue,
                "settled": allowed,
                "cleanup": allow_cleanup,
                "native_mana_decreased": native_mana_decreased,
                "native_fireball_observed": native_fireball_observed,
            },
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pipe", default=DEFAULT_PIPE)
    parser.add_argument("--timeout", type=float, default=25.0)
    parser.add_argument("--cancel-settle", type=float, default=1.75)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    result: dict[str, Any] = {"ok": False, "pipe": args.pipe}
    try:
        result = run(args.pipe, args.timeout, args.cancel_settle)
        return_code = 0
    except Exception as exc:  # noqa: BLE001 - preserve exact live evidence.
        result["error"] = str(exc)
        return_code = 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
