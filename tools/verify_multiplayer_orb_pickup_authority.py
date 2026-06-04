#!/usr/bin/env python3
"""Verify host-authoritative multiplayer health/mana orb pickup request/result flow."""

from __future__ import annotations

import argparse
import json
import math
import time
from typing import Any

from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_PIPE,
    HOST_PIPE,
    ROOT,
    VerifyFailure,
    disable_bots,
    launch_pair,
    lua,
    parse_int_text,
    parse_key_values,
    place_player,
    snap_to_nav,
    start_host_testrun_and_wait_for_clients,
    stop_games,
)


RUNTIME_OUTPUT = ROOT / "runtime" / "multiplayer_orb_pickup_authority.json"
ORB_REWARD_TYPE_ID = 0x07DB
ORB_RAW_VALUE = 1
HEALTH_RESOURCE_KIND = 0
MANA_RESOURCE_KIND = 1
HEALTH_DELTA = 25.0
MANA_DELTA = 40.0
VITAL_TOLERANCE = 0.75
POSITION_TOLERANCE = 260.0
PICKUP_POSITION_TOLERANCE = 240.0
LOCAL_RUNTIME_PARTICIPANT_ID = 1
RUN_SAFE_SPAWN_X = 2350.0
RUN_SAFE_SPAWN_Y = 2850.0


CAPTURE_LUA = r"""
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
local function hx(v) return string.format("0x%08X", tonumber(v) or 0) end
local function finite(v)
  return type(v) == "number" and v == v and v ~= math.huge and v ~= -math.huge
end
local function u8(address) return tonumber(sd.debug.read_u8(address)) or 0 end
local function u32(address) return tonumber(sd.debug.read_u32(address)) or 0 end
local function f32(address) return tonumber(sd.debug.read_float(address)) or 0 end

local scene = sd.world and sd.world.get_scene and sd.world.get_scene() or nil
local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
emit("scene", scene and (scene.name or scene.kind) or "")
emit("player.hp", player and player.hp or 0)
emit("player.max_hp", player and player.max_hp or 0)
emit("player.mp", player and player.mp or 0)
emit("player.max_mp", player and player.max_mp or 0)
emit("player.x", player and player.x or 0)
emit("player.y", player and player.y or 0)

local world_address = player and tonumber(player.world_address) or 0
local transient_offset = sd.debug.layout_offset("actor_world_transient_actor_list")
local pointer_count_offset = sd.debug.layout_offset("pointer_list_count")
local pointer_items_offset = sd.debug.layout_offset("pointer_list_items")
local transient_list = world_address + transient_offset
local transient_count = world_address ~= 0 and u32(transient_list + pointer_count_offset) or 0
local transient_items = world_address ~= 0 and tonumber(sd.debug.read_ptr(transient_list + pointer_items_offset)) or 0
emit("transient.world", hx(world_address))
emit("transient.list", hx(transient_list))
emit("transient.count", transient_count)
emit("transient.items", hx(transient_items))
if transient_items ~= 0 then
  local limit = math.min(transient_count, 12)
  for index = 1, limit do
    local address = tonumber(sd.debug.read_ptr(transient_items + ((index - 1) * 4))) or 0
    local prefix = "transient." .. tostring(index) .. "."
    emit(prefix .. "address", hx(address))
    if address ~= 0 then
      emit(prefix .. "type", u32(address + sd.debug.layout_offset("game_object_type_id")))
      emit(prefix .. "owner", hx(tonumber(sd.debug.read_ptr(address + sd.debug.layout_offset("actor_owner"))) or 0))
      emit(prefix .. "x", string.format("%.3f", f32(address + sd.debug.layout_offset("actor_position_x"))))
      emit(prefix .. "y", string.format("%.3f", f32(address + sd.debug.layout_offset("actor_position_y"))))
      emit(prefix .. "radius", string.format("%.3f", f32(address + sd.debug.layout_offset("actor_collision_radius"))))
      emit(prefix .. "orb_kind", u8(address + 0x13C))
      emit(prefix .. "orb_value", string.format("%.3f", f32(address + 0x140)))
      emit(prefix .. "orb_lifetime", u32(address + 0x144))
    end
  end
end

local actors = sd.world and sd.world.list_actors and sd.world.list_actors() or {}
local orb_count = 0
for _, actor in ipairs(actors) do
  local type_id = tonumber(actor.object_type_id) or 0
  if type_id == 0x07DB then
    local address = tonumber(actor.actor_address) or 0
    if address ~= 0 and finite(tonumber(actor.x)) and finite(tonumber(actor.y)) then
      orb_count = orb_count + 1
      local prefix = "orb." .. tostring(orb_count) .. "."
      emit(prefix .. "address", hx(address))
      emit(prefix .. "type", type_id)
      emit(prefix .. "x", string.format("%.3f", tonumber(actor.x) or 0))
      emit(prefix .. "y", string.format("%.3f", tonumber(actor.y) or 0))
      emit(prefix .. "resource_kind", u8(address + 0x13C))
      emit(prefix .. "value", string.format("%.3f", f32(address + 0x140)))
      emit(prefix .. "lifetime", u32(address + 0x144))
      emit(prefix .. "motion", string.format("%.3f", f32(address + 0x148)))
    end
  end
end
emit("orb.count", orb_count)

local loot = sd.world and sd.world.get_replicated_loot and sd.world.get_replicated_loot() or nil
emit("loot.valid", loot ~= nil)
emit("loot.drop_count", loot and loot.drop_count or 0)
emit("loot.drop_total_count", loot and loot.drop_total_count or 0)
local loot_orb_count = 0
if loot and loot.drops then
  for _, drop in ipairs(loot.drops) do
    local type_id = tonumber(drop.object_type_id or drop.native_type_id) or 0
    if type_id == 0x07DB or drop.kind == "Orb" then
      loot_orb_count = loot_orb_count + 1
      local prefix = "loot_orb." .. tostring(loot_orb_count) .. "."
      emit(prefix .. "network_id", drop.network_drop_id or 0)
      emit(prefix .. "type", type_id)
      emit(prefix .. "kind", drop.kind or "")
      emit(prefix .. "kind_id", drop.kind_id or 0)
      emit(prefix .. "amount", drop.amount or 0)
      emit(prefix .. "amount_tier", drop.amount_tier or 0)
      emit(prefix .. "resource_kind", drop.resource_kind or drop.amount_tier or 0)
      emit(prefix .. "value", string.format("%.3f", tonumber(drop.value) or 0))
      emit(prefix .. "active", drop.active and 1 or 0)
      emit(prefix .. "lifetime", drop.lifetime or 0)
      emit(prefix .. "x", string.format("%.3f", tonumber(drop.x) or 0))
      emit(prefix .. "y", string.format("%.3f", tonumber(drop.y) or 0))
    end
  end
end
emit("loot_orb.count", loot_orb_count)

if loot and loot.last_pickup_result then
  local result = loot.last_pickup_result
  emit("pickup.valid", true)
  emit("pickup.participant_id", result.participant_id or 0)
  emit("pickup.request_sequence", result.request_sequence or 0)
  emit("pickup.network_drop_id", result.network_drop_id or 0)
  emit("pickup.result", result.result or "")
  emit("pickup.result_id", result.result_id or 0)
  emit("pickup.kind", result.kind or "")
  emit("pickup.amount", result.amount or 0)
  emit("pickup.resource_kind", result.resource_kind or -1)
  emit("pickup.resource_delta", string.format("%.3f", tonumber(result.resource_delta) or 0))
  emit("pickup.resulting_life_current", string.format("%.3f", tonumber(result.resulting_life_current) or 0))
  emit("pickup.resulting_life_max", string.format("%.3f", tonumber(result.resulting_life_max) or 0))
  emit("pickup.resulting_mana_current", string.format("%.3f", tonumber(result.resulting_mana_current) or 0))
  emit("pickup.resulting_mana_max", string.format("%.3f", tonumber(result.resulting_mana_max) or 0))
else
  emit("pickup.valid", false)
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
    emit(prefix .. "runtime_valid", participant.runtime_valid or false)
    emit(prefix .. "in_run", participant.in_run or false)
    emit(prefix .. "life_current", string.format("%.3f", tonumber(participant.life_current) or 0))
    emit(prefix .. "life_max", string.format("%.3f", tonumber(participant.life_max) or 0))
    emit(prefix .. "mana_current", string.format("%.3f", tonumber(participant.mana_current) or 0))
    emit(prefix .. "mana_max", string.format("%.3f", tonumber(participant.mana_max) or 0))
    emit(prefix .. "x", string.format("%.3f", tonumber(participant.x) or 0))
    emit(prefix .. "y", string.format("%.3f", tonumber(participant.y) or 0))
  end
end
"""


REQUEST_PICKUP_LUA = r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local ok, value = sd.world.request_loot_pickup(%d)
emit("ok", ok)
emit(ok and "request_sequence" or "error", value or "")
"""


SET_CLIENT_VITALS_LUA = r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local player = sd.player.get_state()
if player == nil or player.actor_address == nil or player.actor_address == 0 then
  error("player actor unavailable")
end
local progression = tonumber(player.progression_address) or 0
if progression == 0 then
  progression = tonumber(sd.debug.read_ptr(player.actor_address + sd.debug.layout_offset("actor_progression_runtime_state"))) or 0
end
if progression == 0 then
  error("player progression unavailable")
end
local ohp = sd.debug.layout_offset("progression_hp")
local omaxhp = sd.debug.layout_offset("progression_max_hp")
local omp = sd.debug.layout_offset("progression_mp")
local omaxmp = sd.debug.layout_offset("progression_max_mp")
emit("write.max_hp", sd.debug.write_float(progression + omaxhp, %.3f))
emit("write.hp", sd.debug.write_float(progression + ohp, %.3f))
emit("write.max_mp", sd.debug.write_float(progression + omaxmp, %.3f))
emit("write.mp", sd.debug.write_float(progression + omp, %.3f))
local after = sd.player.get_state()
emit("after.hp", after and after.hp or -1)
emit("after.max_hp", after and after.max_hp or -1)
emit("after.mp", after and after.mp or -1)
emit("after.max_mp", after and after.max_mp or -1)
"""


SPAWN_ORB_LUA = r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local ok, err = sd.world.spawn_reward({kind="%s", amount=%d, x=%.3f, y=%.3f})
emit("ok", ok)
emit("error", err or "")
"""


def values(pipe_name: str, code: str, timeout: float = 8.0) -> dict[str, str]:
    return parse_key_values(lua(pipe_name, code, timeout=timeout))


def capture(pipe_name: str) -> dict[str, str]:
    return values(pipe_name, CAPTURE_LUA)


def capture_pair() -> dict[str, dict[str, str]]:
    return {
        "host": capture(HOST_PIPE),
        "client": capture(CLIENT_PIPE),
    }


def parse_float_text(value: str | None, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def approximately(actual: float, expected: float, tolerance: float = VITAL_TOLERANCE) -> bool:
    return math.isfinite(actual) and abs(actual - expected) <= tolerance


def distance(ax: float, ay: float, bx: float, by: float) -> float:
    return math.hypot(ax - bx, ay - by)


def row_count(values: dict[str, str], prefix: str) -> int:
    return parse_int_text(values.get(prefix + "count"), 0)


def orb_rows(capture_values: dict[str, str], prefix: str = "orb.") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index in range(1, row_count(capture_values, prefix) + 1):
        row_prefix = f"{prefix}{index}."
        rows.append({
            "address": parse_int_text(capture_values.get(row_prefix + "address"), 0),
            "type": parse_int_text(capture_values.get(row_prefix + "type"), 0),
            "x": parse_float_text(capture_values.get(row_prefix + "x")),
            "y": parse_float_text(capture_values.get(row_prefix + "y")),
            "resource_kind": parse_int_text(capture_values.get(row_prefix + "resource_kind"), -1),
            "value": parse_float_text(capture_values.get(row_prefix + "value")),
            "lifetime": parse_int_text(capture_values.get(row_prefix + "lifetime"), 0),
            "motion": parse_float_text(capture_values.get(row_prefix + "motion")),
        })
    return rows


def loot_orb_rows(capture_values: dict[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index in range(1, row_count(capture_values, "loot_orb.") + 1):
        row_prefix = f"loot_orb.{index}."
        rows.append({
            "network_id": parse_int_text(capture_values.get(row_prefix + "network_id"), 0),
            "type": parse_int_text(capture_values.get(row_prefix + "type"), 0),
            "kind": capture_values.get(row_prefix + "kind", ""),
            "amount": parse_int_text(capture_values.get(row_prefix + "amount"), 0),
            "resource_kind": parse_int_text(capture_values.get(row_prefix + "resource_kind"), -1),
            "value": parse_float_text(capture_values.get(row_prefix + "value")),
            "active": parse_int_text(capture_values.get(row_prefix + "active"), 0),
            "lifetime": parse_int_text(capture_values.get(row_prefix + "lifetime"), 0),
            "x": parse_float_text(capture_values.get(row_prefix + "x")),
            "y": parse_float_text(capture_values.get(row_prefix + "y")),
        })
    return rows


def participant_rows(capture_values: dict[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index in range(1, parse_int_text(capture_values.get("mp.participant_count"), 0) + 1):
        row_prefix = f"participant.{index}."
        rows.append({
            "id": parse_int_text(capture_values.get(row_prefix + "id"), 0),
            "life_current": parse_float_text(capture_values.get(row_prefix + "life_current")),
            "life_max": parse_float_text(capture_values.get(row_prefix + "life_max")),
            "mana_current": parse_float_text(capture_values.get(row_prefix + "mana_current")),
            "mana_max": parse_float_text(capture_values.get(row_prefix + "mana_max")),
            "x": parse_float_text(capture_values.get(row_prefix + "x")),
            "y": parse_float_text(capture_values.get(row_prefix + "y")),
        })
    return rows


def find_participant(capture_values: dict[str, str], participant_id: int) -> dict[str, Any] | None:
    for row in participant_rows(capture_values):
        if row["id"] == participant_id:
            return row
    return None


def set_client_vitals(hp: float, max_hp: float, mp: float, max_mp: float) -> dict[str, str]:
    result = values(CLIENT_PIPE, SET_CLIENT_VITALS_LUA % (max_hp, hp, max_mp, mp))
    for key in ("write.max_hp", "write.hp", "write.max_mp", "write.mp"):
        if result.get(key) != "true":
            raise VerifyFailure(f"failed to set client vitals: {result}")
    return result


def wait_for_host_client_vitals(
    *,
    expected_hp: float,
    expected_max_hp: float,
    expected_mp: float,
    expected_max_mp: float,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    last_row: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        last = capture(HOST_PIPE)
        last_row = find_participant(last, CLIENT_ID)
        if (
            last_row is not None
            and approximately(last_row["life_current"], expected_hp)
            and approximately(last_row["life_max"], expected_max_hp)
            and approximately(last_row["mana_current"], expected_mp)
            and approximately(last_row["mana_max"], expected_max_mp)
        ):
            return {"capture": last, "participant": last_row}
        time.sleep(0.1)
    raise VerifyFailure(f"host did not observe client vitals: row={last_row} capture={last}")


def wait_for_host_client_vitals_sample(timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    last_row: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        last = capture(HOST_PIPE)
        last_row = find_participant(last, CLIENT_ID)
        if (
            last_row is not None
            and math.isfinite(last_row["life_current"])
            and math.isfinite(last_row["life_max"])
            and math.isfinite(last_row["mana_current"])
            and math.isfinite(last_row["mana_max"])
            and last_row["life_max"] > 0.0
            and last_row["mana_max"] > 0.0
        ):
            return {"capture": last, "participant": last_row}
        time.sleep(0.1)
    raise VerifyFailure(f"host did not expose a usable client vitals sample: row={last_row} capture={last}")


def wait_for_client_local_vitals(
    *,
    expected_hp: float,
    expected_max_hp: float,
    expected_mp: float,
    expected_max_mp: float,
    timeout: float,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = capture(CLIENT_PIPE)
        if (
            approximately(parse_float_text(last.get("player.hp")), expected_hp)
            and approximately(parse_float_text(last.get("player.max_hp")), expected_max_hp)
            and approximately(parse_float_text(last.get("player.mp")), expected_mp)
            and approximately(parse_float_text(last.get("player.max_mp")), expected_max_mp)
        ):
            return last
        time.sleep(0.1)
    raise VerifyFailure(f"client local vitals did not converge: {last}")


def wait_for_client_local_resource(
    *,
    resource_kind: int,
    expected_current: float,
    expected_max: float,
    timeout: float,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = capture(CLIENT_PIPE)
        if resource_kind == HEALTH_RESOURCE_KIND:
            current = parse_float_text(last.get("player.hp"))
            maximum = parse_float_text(last.get("player.max_hp"))
        else:
            current = parse_float_text(last.get("player.mp"))
            maximum = parse_float_text(last.get("player.max_mp"))
        if current + VITAL_TOLERANCE >= expected_current and approximately(maximum, expected_max):
            return last
        time.sleep(0.1)
    raise VerifyFailure(
        "client local orb resource did not reach authority result: "
        f"resource={resource_kind} expected={expected_current}/{expected_max} last={last}"
    )


def wait_for_host_client_resource(
    *,
    resource_kind: int,
    expected_current: float,
    expected_max: float,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    last_row: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        last = capture(HOST_PIPE)
        last_row = find_participant(last, CLIENT_ID)
        if last_row is not None:
            if resource_kind == HEALTH_RESOURCE_KIND:
                current = last_row["life_current"]
                maximum = last_row["life_max"]
            else:
                current = last_row["mana_current"]
                maximum = last_row["mana_max"]
            if current + VITAL_TOLERANCE >= expected_current and approximately(maximum, expected_max):
                return {"capture": last, "participant": last_row}
        time.sleep(0.1)
    raise VerifyFailure(
        "host participant orb resource did not reach authority result: "
        f"resource={resource_kind} expected={expected_current}/{expected_max} row={last_row} capture={last}"
    )


def request_pickup(network_drop_id: int) -> dict[str, str]:
    result = values(CLIENT_PIPE, REQUEST_PICKUP_LUA % network_drop_id)
    if result.get("ok") != "true":
        raise VerifyFailure(f"client request_loot_pickup failed: {result}")
    return result


def request_pickup_when_ready(
    *,
    network_drop_id: int,
    drop_x: float,
    drop_y: float,
    timeout: float,
) -> dict[str, str]:
    code = f"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local network_drop_id = {network_drop_id}
local drop_x = {drop_x:.3f}
local drop_y = {drop_y:.3f}
local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
if player == nil then
  emit("ok", false)
  emit("error", "player_missing")
  return
end
local loot = sd.world and sd.world.get_replicated_loot and sd.world.get_replicated_loot() or nil
local found = false
if loot and loot.drops then
  for _, drop in ipairs(loot.drops) do
    if tonumber(drop.network_drop_id) == network_drop_id then
      found = true
      drop_x = tonumber(drop.x) or drop_x
      drop_y = tonumber(drop.y) or drop_y
      break
    end
  end
end
local dx = (tonumber(player.x) or 0) - drop_x
local dy = (tonumber(player.y) or 0) - drop_y
local dist = math.sqrt((dx * dx) + (dy * dy))
emit("drop_present", found)
emit("player.x", player.x or 0)
emit("player.y", player.y or 0)
emit("drop.x", drop_x)
emit("drop.y", drop_y)
emit("distance", dist)
if not found then
  emit("ok", false)
  emit("error", "drop_missing")
  return
end
if dist > 320.0 then
  emit("ok", false)
  emit("error", "player_out_of_range")
  return
end
local ok, value = sd.world.request_loot_pickup(network_drop_id)
emit("ok", ok)
emit(ok and "request_sequence" or "error", value or "")
"""
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = values(CLIENT_PIPE, code)
        if last.get("ok") == "true":
            return last
        if last.get("error") == "player_out_of_range":
            place_player(CLIENT_PIPE, drop_x, drop_y, 90.0)
        time.sleep(0.1)
    raise VerifyFailure(
        "client could not queue orb pickup from an in-range replicated snapshot: "
        f"drop={network_drop_id} last={last}"
    )


def move_client_into_pickup_range(
    *,
    drop_x: float,
    drop_y: float,
    timeout: float,
) -> dict[str, Any]:
    place = place_player(CLIENT_PIPE, drop_x, drop_y, 90.0)
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    last_row: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        last = capture(CLIENT_PIPE)
        player_x = parse_float_text(last.get("player.x"))
        player_y = parse_float_text(last.get("player.y"))
        last_row = find_participant(last, LOCAL_RUNTIME_PARTICIPANT_ID)
        player_in_range = distance(player_x, player_y, drop_x, drop_y) <= PICKUP_POSITION_TOLERANCE
        runtime_in_range = (
            last_row is not None
            and distance(last_row["x"], last_row["y"], drop_x, drop_y) <= PICKUP_POSITION_TOLERANCE
        )
        if player_in_range and runtime_in_range:
            return {
                "place": place,
                "capture": last,
                "local_participant": last_row,
                "drop_x": drop_x,
                "drop_y": drop_y,
            }
        time.sleep(0.1)
    raise VerifyFailure(
        "client did not settle in orb pickup range before request: "
        f"drop=({drop_x:.3f},{drop_y:.3f}) row={last_row} capture={last}"
    )


def wait_for_client_pickup_result(
    *,
    network_drop_id: int,
    request_sequence: int,
    expected_result: str,
    timeout: float,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = capture(CLIENT_PIPE)
        if (
            last.get("pickup.valid") == "true"
            and parse_int_text(last.get("pickup.network_drop_id"), 0) == network_drop_id
            and parse_int_text(last.get("pickup.request_sequence"), 0) == request_sequence
            and last.get("pickup.result") == expected_result
        ):
            return last
        time.sleep(0.1)
    raise VerifyFailure(
        "client did not receive expected orb pickup result: "
        f"drop={network_drop_id} request={request_sequence} expected={expected_result} last={last}"
    )


def spawn_orb(kind: str, amount: int, x: float, y: float) -> dict[str, str]:
    result = values(HOST_PIPE, SPAWN_ORB_LUA % (kind, amount, x, y), timeout=8.0)
    if result.get("ok") != "true":
        raise VerifyFailure(f"spawn_reward({kind}) failed: {result}")
    return result


def wait_for_spawned_host_orb(
    *,
    before_addresses: set[int],
    resource_kind: int,
    raw_value: float,
    x: float,
    y: float,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = capture(HOST_PIPE)
        for row in orb_rows(last):
            if row["address"] in before_addresses:
                continue
            if (
                row["resource_kind"] == resource_kind
                and approximately(row["value"], raw_value)
                and row["lifetime"] > 0
                and distance(row["x"], row["y"], x, y) <= POSITION_TOLERANCE
            ):
                return {"capture": last, "orb": row}
        time.sleep(0.1)
    raise VerifyFailure(f"host did not expose spawned orb: resource={resource_kind} last={last}")


def wait_for_client_replicated_orb(
    *,
    resource_kind: int,
    raw_value: float,
    x: float,
    y: float,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = capture(CLIENT_PIPE)
        for row in loot_orb_rows(last):
            if (
                row["network_id"] != 0
                and row["active"] == 1
                and row["resource_kind"] == resource_kind
                and approximately(row["value"], raw_value)
                and distance(row["x"], row["y"], x, y) <= POSITION_TOLERANCE
            ):
                return {"capture": last, "drop": row}
        time.sleep(0.1)
    raise VerifyFailure(f"client did not receive replicated orb: resource={resource_kind} last={last}")


def wait_for_host_orb_consumed(address: int, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = capture(HOST_PIPE)
        matching = [row for row in orb_rows(last) if row["address"] == address]
        if not matching:
            return {"capture": last, "orb_removed": True}
        row = matching[0]
        if row["value"] <= VITAL_TOLERANCE and row["lifetime"] == 0:
            return {"capture": last, "orb": row, "orb_removed": False}
        time.sleep(0.1)
    raise VerifyFailure(f"host orb did not get consumed: address=0x{address:X} last={last}")


def wait_for_client_replicated_orb_absent(network_drop_id: int, timeout: float) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = capture(CLIENT_PIPE)
        if all(row["network_id"] != network_drop_id for row in loot_orb_rows(last)):
            return last
        time.sleep(0.1)
    raise VerifyFailure(f"client replicated orb did not disappear: id={network_drop_id} last={last}")


def setup_live_run_pair_without_waves(max_attempts: int) -> dict[str, Any]:
    last_error = ""
    for attempt in range(1, max_attempts + 1):
        try:
            stop_games()
            launch = launch_pair()
            disable_bots()
            run_entry = start_host_testrun_and_wait_for_clients()
            time.sleep(1.0)
            return {
                "attempt": attempt,
                "launch": launch,
                "run_entry": run_entry,
            }
        except Exception as exc:
            last_error = str(exc)
            stop_games()
            time.sleep(1.0)
    raise VerifyFailure(f"failed to prepare live run pair after {max_attempts} attempts: {last_error}")


def select_host_spawn_anchor(timeout: float) -> dict[str, Any]:
    before = capture_pair()
    _ = timeout
    target_x, target_y = snap_to_nav(HOST_PIPE, RUN_SAFE_SPAWN_X, RUN_SAFE_SPAWN_Y)
    if not math.isfinite(target_x) or not math.isfinite(target_y):
        raise VerifyFailure(f"host spawn anchor unavailable: before={before}")
    return {
        "before": before,
        "target_x": target_x,
        "target_y": target_y,
    }


def verify_one_orb_pickup(
    *,
    label: str,
    kind: str,
    resource_kind: int,
    expected_delta: float,
    anchor_x: float,
    anchor_y: float,
    timeout: float,
) -> dict[str, Any]:
    base_hp = 50.0
    base_max_hp = 100.0
    base_mp = 20.0
    base_max_mp = 200.0 if resource_kind == MANA_RESOURCE_KIND else 100.0

    result: dict[str, Any] = {"label": label}
    result["set_client_vitals"] = set_client_vitals(base_hp, base_max_hp, base_mp, base_max_mp)
    result["host_client_vitals_before"] = wait_for_host_client_vitals_sample(timeout=timeout)
    before_addresses = {row["address"] for row in orb_rows(capture(HOST_PIPE))}
    spawn_x = anchor_x
    spawn_y = anchor_y
    result["spawn"] = spawn_orb(kind, ORB_RAW_VALUE, spawn_x, spawn_y)
    result["host_spawned_orb"] = wait_for_spawned_host_orb(
        before_addresses=before_addresses,
        resource_kind=resource_kind,
        raw_value=float(ORB_RAW_VALUE),
        x=spawn_x,
        y=spawn_y,
        timeout=timeout,
    )
    result["client_replicated_orb"] = wait_for_client_replicated_orb(
        resource_kind=resource_kind,
        raw_value=float(ORB_RAW_VALUE),
        x=spawn_x,
        y=spawn_y,
        timeout=timeout,
    )
    replicated_drop = result["client_replicated_orb"]["drop"]
    result["client_pickup_position"] = move_client_into_pickup_range(
        drop_x=float(replicated_drop["x"]),
        drop_y=float(replicated_drop["y"]),
        timeout=timeout,
    )
    result["pre_request_pair"] = capture_pair()
    network_drop_id = int(replicated_drop["network_id"])
    try:
        request = request_pickup_when_ready(
            network_drop_id=network_drop_id,
            drop_x=float(replicated_drop["x"]),
            drop_y=float(replicated_drop["y"]),
            timeout=timeout,
        )
    except VerifyFailure as exc:
        result["request_failure"] = {
            "error": str(exc),
            "pair": capture_pair(),
        }
        RUNTIME_OUTPUT.write_text(json.dumps({"ok": False, "partial": result}, indent=2))
        raise
    request_sequence = parse_int_text(request.get("request_sequence"), 0)
    result["request"] = request
    result["accepted_result"] = wait_for_client_pickup_result(
        network_drop_id=network_drop_id,
        request_sequence=request_sequence,
        expected_result="Accepted",
        timeout=timeout,
    )
    accepted = result["accepted_result"]
    expected_hp = parse_float_text(accepted.get("pickup.resulting_life_current"))
    expected_max_hp = parse_float_text(accepted.get("pickup.resulting_life_max"))
    expected_mp = parse_float_text(accepted.get("pickup.resulting_mana_current"))
    expected_max_mp = parse_float_text(accepted.get("pickup.resulting_mana_max"))
    result["client_local_vitals_after_accept"] = wait_for_client_local_resource(
        resource_kind=resource_kind,
        expected_current=expected_hp if resource_kind == HEALTH_RESOURCE_KIND else expected_mp,
        expected_max=expected_max_hp if resource_kind == HEALTH_RESOURCE_KIND else expected_max_mp,
        timeout=timeout,
    )
    result["host_client_vitals_after_accept"] = wait_for_host_client_resource(
        resource_kind=resource_kind,
        expected_current=expected_hp if resource_kind == HEALTH_RESOURCE_KIND else expected_mp,
        expected_max=expected_max_hp if resource_kind == HEALTH_RESOURCE_KIND else expected_max_mp,
        timeout=timeout,
    )
    result["host_orb_after_accept"] = wait_for_host_orb_consumed(
        int(result["host_spawned_orb"]["orb"]["address"]),
        timeout=timeout,
    )
    result["client_drop_after_accept"] = wait_for_client_replicated_orb_absent(
        network_drop_id,
        timeout=timeout,
    )

    duplicate_request = request_pickup(network_drop_id)
    duplicate_sequence = parse_int_text(duplicate_request.get("request_sequence"), 0)
    result["duplicate_request"] = duplicate_request
    result["duplicate_result"] = wait_for_client_pickup_result(
        network_drop_id=network_drop_id,
        request_sequence=duplicate_sequence,
        expected_result="AlreadyGone",
        timeout=timeout,
    )
    result["after_duplicate_pair"] = capture_pair()

    client_after = result["client_local_vitals_after_accept"]
    host_after = result["host_client_vitals_after_accept"]["participant"]
    result["conclusion"] = {
        "accepted_kind_is_orb": accepted.get("pickup.kind") == "Orb",
        "accepted_resource_kind_matches": parse_int_text(accepted.get("pickup.resource_kind"), -1) == resource_kind,
        "accepted_delta_matches": approximately(
            parse_float_text(accepted.get("pickup.resource_delta")),
            expected_delta,
        ),
        "accepted_amount_matches": approximately(
            parse_float_text(accepted.get("pickup.amount")),
            expected_delta,
        ),
        "client_resource_reached_authority": (
            parse_float_text(client_after.get("player.hp" if resource_kind == HEALTH_RESOURCE_KIND else "player.mp")) +
            VITAL_TOLERANCE >= (expected_hp if resource_kind == HEALTH_RESOURCE_KIND else expected_mp)
        ),
        "host_participant_resource_reached_authority": (
            (host_after["life_current"] if resource_kind == HEALTH_RESOURCE_KIND else host_after["mana_current"]) +
            VITAL_TOLERANCE >= (expected_hp if resource_kind == HEALTH_RESOURCE_KIND else expected_mp)
        ),
        "client_metadata_deactivated": True,
        "duplicate_rejected_without_second_credit": result["duplicate_result"].get("pickup.result") == "AlreadyGone",
    }
    if not all(result["conclusion"].values()):
        raise VerifyFailure(f"{label} orb pickup conclusion failed: {result['conclusion']}")
    return result


def verify_orb_pickup_authority(args: argparse.Namespace) -> dict[str, Any]:
    result: dict[str, Any] = {"ok": False}
    if not args.no_launch:
        result["setup"] = setup_live_run_pair_without_waves(max_attempts=args.attempts)

    anchor = select_host_spawn_anchor(timeout=args.timeout)
    result["anchor"] = anchor
    anchor_x = float(anchor["target_x"])
    anchor_y = float(anchor["target_y"])
    result["health_orb"] = verify_one_orb_pickup(
        label="health",
        kind="health_orb",
        resource_kind=HEALTH_RESOURCE_KIND,
        expected_delta=HEALTH_DELTA,
        anchor_x=anchor_x,
        anchor_y=anchor_y,
        timeout=args.timeout,
    )
    result["mana_orb"] = verify_one_orb_pickup(
        label="mana",
        kind="mana_orb",
        resource_kind=MANA_RESOURCE_KIND,
        expected_delta=MANA_DELTA,
        anchor_x=anchor_x,
        anchor_y=anchor_y + 64.0,
        timeout=args.timeout,
    )
    result["ok"] = (
        all(result["health_orb"]["conclusion"].values()) and
        all(result["mana_orb"]["conclusion"].values())
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-launch", action="store_true")
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=12.0)
    args = parser.parse_args()

    result: dict[str, Any] = {"ok": False}
    try:
        result = verify_orb_pickup_authority(args)
        RUNTIME_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        RUNTIME_OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps({
            "ok": result["ok"],
            "health": result["health_orb"].get("conclusion", {}),
            "mana": result["mana_orb"].get("conclusion", {}),
            "output": str(RUNTIME_OUTPUT),
        }, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        result["error"] = str(exc)
        RUNTIME_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        RUNTIME_OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps({
            "ok": False,
            "error": str(exc),
            "output": str(RUNTIME_OUTPUT),
        }, indent=2, sort_keys=True))
        return 1
    finally:
        if not args.no_launch:
            stop_games()


if __name__ == "__main__":
    raise SystemExit(main())
