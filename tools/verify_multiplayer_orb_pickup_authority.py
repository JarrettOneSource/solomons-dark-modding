#!/usr/bin/env python3
"""Verify host-authoritative multiplayer health/mana orb pickup request/result flow."""

from __future__ import annotations

import argparse
import json
import math
import time
from typing import Any

from multiplayer_pickup_geometry import (
    PickupGeometryRuntime,
    select_reachable_spawn_point,
)
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
STOCK_ORB_WORLD_UNITS_PER_PICKUP_RANGE = 60.0
PICKUP_RANGE_TEST_MARGIN = 0.95
PICKUP_SUPPRESSION_RADIUS = 335.0
PICKUP_PARKING_MIN_DISTANCE = 520.0
LOCAL_RUNTIME_PARTICIPANT_ID = 1


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
    local owned = participant.owned_progression or {}
    local derived = owned.derived_stats or {}
    emit(prefix .. "pickup_range", string.format("%.3f", tonumber(derived.pickup_range) or 0))
  end
end
"""


REQUEST_PICKUP_LUA = r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local ok, value = sd.world.request_loot_pickup(%d)
emit("ok", ok)
emit(ok and "request_sequence" or "error", value or "")
"""


SET_CLIENT_RESOURCES_LUA = r"""
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
local target_hp = %s
local target_mp = %s
emit("write.hp", target_hp == nil or sd.debug.write_float(progression + ohp, target_hp))
emit("write.mp", target_mp == nil or sd.debug.write_float(progression + omp, target_mp))
local after = sd.player.get_state()
emit("after.hp", after and after.hp or -1)
emit("after.max_hp", after and after.max_hp or -1)
emit("after.mp", after and after.mp or -1)
emit("after.max_mp", after and after.max_mp or -1)
emit("native.max_hp", sd.debug.read_float(progression + omaxhp))
emit("native.max_mp", sd.debug.read_float(progression + omaxmp))
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
            "pickup_range": parse_float_text(
                capture_values.get(row_prefix + "pickup_range")
            ),
        })
    return rows


def find_participant(capture_values: dict[str, str], participant_id: int) -> dict[str, Any] | None:
    for row in participant_rows(capture_values):
        if row["id"] == participant_id:
            return row
    return None


def lua_optional_float(value: float | None) -> str:
    if value is None:
        return "nil"
    if not math.isfinite(value):
        raise VerifyFailure(f"resource fixture value is not finite: {value}")
    return f"{value:.3f}"


def set_client_resources(
    *,
    hp: float | None = None,
    mp: float | None = None,
) -> dict[str, str]:
    result = values(
        CLIENT_PIPE,
        SET_CLIENT_RESOURCES_LUA % (
            lua_optional_float(hp),
            lua_optional_float(mp),
        ),
    )
    for key in ("write.hp", "write.mp"):
        if result.get(key) != "true":
            raise VerifyFailure(f"failed to set client resources: {result}")
    return result


def capture_client_vitals() -> dict[str, float]:
    snapshot = capture(CLIENT_PIPE)
    vitals = {
        "hp": parse_float_text(snapshot.get("player.hp")),
        "max_hp": parse_float_text(snapshot.get("player.max_hp")),
        "mp": parse_float_text(snapshot.get("player.mp")),
        "max_mp": parse_float_text(snapshot.get("player.max_mp")),
    }
    if (
        not all(math.isfinite(value) for value in vitals.values())
        or vitals["max_hp"] <= 0.0
        or vitals["max_mp"] <= 0.0
    ):
        raise VerifyFailure(f"client vitals are unavailable before orb test: {vitals}")
    return vitals


def wait_for_host_client_native_maxima(
    *,
    expected_max_hp: float,
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
            and math.isfinite(last_row["life_current"])
            and -VITAL_TOLERANCE <= last_row["life_current"] <= expected_max_hp + VITAL_TOLERANCE
            and approximately(last_row["life_max"], expected_max_hp)
            and math.isfinite(last_row["mana_current"])
            and -VITAL_TOLERANCE <= last_row["mana_current"] <= expected_max_mp + VITAL_TOLERANCE
            and approximately(last_row["mana_max"], expected_max_mp)
        ):
            return {"capture": last, "participant": last_row}
        time.sleep(0.1)
    raise VerifyFailure(
        f"host did not preserve client native maxima: row={last_row} capture={last}"
    )


def wait_for_host_client_resource_window(
    *,
    resource_kind: int,
    minimum_current: float,
    maximum_current: float,
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
            if (
                math.isfinite(current)
                and current + VITAL_TOLERANCE >= minimum_current
                and current <= maximum_current + VITAL_TOLERANCE
                and approximately(maximum, expected_max)
            ):
                return {"capture": last, "participant": last_row}
        time.sleep(0.1)
    raise VerifyFailure(
        "host did not observe the bounded client orb fixture: "
        f"resource={resource_kind} expected_current={minimum_current}..{maximum_current} "
        f"expected_max={expected_max} row={last_row} capture={last}"
    )


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
        if (
            current + VITAL_TOLERANCE >= expected_current
            and current <= expected_max + VITAL_TOLERANCE
            and approximately(maximum, expected_max)
        ):
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
            if (
                current + VITAL_TOLERANCE >= expected_current
                and current <= expected_max + VITAL_TOLERANCE
                and approximately(maximum, expected_max)
            ):
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


def try_wait_for_client_pickup_result(
    *,
    network_drop_id: int,
    request_sequence: int | None,
    expected_result: str,
    timeout: float,
) -> dict[str, str] | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        capture_values = capture(CLIENT_PIPE)
        sequence_matches = (
            request_sequence is None or
            parse_int_text(capture_values.get("pickup.request_sequence"), 0) == request_sequence
        )
        if (
            capture_values.get("pickup.valid") == "true"
            and parse_int_text(capture_values.get("pickup.network_drop_id"), 0) == network_drop_id
            and sequence_matches
            and capture_values.get("pickup.result") == expected_result
        ):
            return capture_values
        time.sleep(0.1)
    return None


def move_client_into_pickup_range(
    *,
    network_drop_id: int,
    drop_x: float,
    drop_y: float,
    timeout: float,
) -> dict[str, Any]:
    place = place_player(CLIENT_PIPE, drop_x, drop_y, 90.0)
    deadline = time.monotonic() + timeout
    next_reposition_at = time.monotonic() + 0.5
    last_client: dict[str, str] = {}
    last_host: dict[str, str] = {}
    local_row: dict[str, Any] | None = None
    host_row: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        last_client = capture(CLIENT_PIPE)
        last_host = capture(HOST_PIPE)
        player_x = parse_float_text(last_client.get("player.x"))
        player_y = parse_float_text(last_client.get("player.y"))
        local_row = find_participant(last_client, LOCAL_RUNTIME_PARTICIPANT_ID)
        host_row = find_participant(last_host, CLIENT_ID)
        local_range_limit = (
            local_row["pickup_range"]
            * STOCK_ORB_WORLD_UNITS_PER_PICKUP_RANGE
            * PICKUP_RANGE_TEST_MARGIN
            if local_row is not None
            and math.isfinite(local_row["pickup_range"])
            and local_row["pickup_range"] > 0.0
            else 0.0
        )
        host_range_limit = (
            host_row["pickup_range"]
            * STOCK_ORB_WORLD_UNITS_PER_PICKUP_RANGE
            * PICKUP_RANGE_TEST_MARGIN
            if host_row is not None
            and math.isfinite(host_row["pickup_range"])
            and host_row["pickup_range"] > 0.0
            else 0.0
        )
        player_distance = distance(player_x, player_y, drop_x, drop_y)
        runtime_distance = (
            distance(local_row["x"], local_row["y"], drop_x, drop_y)
            if local_row is not None else math.inf
        )
        authority_distance = (
            distance(host_row["x"], host_row["y"], drop_x, drop_y)
            if host_row is not None else math.inf
        )
        player_in_range = local_range_limit > 0.0 and player_distance <= local_range_limit
        runtime_in_range = (
            local_range_limit > 0.0 and runtime_distance <= local_range_limit
        )
        authority_in_range = (
            host_range_limit > 0.0 and authority_distance <= host_range_limit
        )
        accepted_during_positioning = (
            last_client.get("pickup.valid") == "true"
            and parse_int_text(
                last_client.get("pickup.network_drop_id"), 0
            ) == network_drop_id
            and last_client.get("pickup.result") == "Accepted"
        )
        if (
            accepted_during_positioning
            or (player_in_range and runtime_in_range and authority_in_range)
        ):
            return {
                "place": place,
                "client_capture": last_client,
                "host_capture": last_host,
                "local_participant": local_row,
                "host_participant": host_row,
                "drop_x": drop_x,
                "drop_y": drop_y,
                "client_range_limit": local_range_limit,
                "host_range_limit": host_range_limit,
                "player_distance": player_distance,
                "runtime_distance": runtime_distance,
                "authority_distance": authority_distance,
                "accepted_during_positioning": accepted_during_positioning,
            }
        if (
            not (player_in_range and runtime_in_range and authority_in_range)
            and time.monotonic() >= next_reposition_at
        ):
            place = place_player(CLIENT_PIPE, drop_x, drop_y, 90.0)
            next_reposition_at = time.monotonic() + 0.5
        time.sleep(0.1)
    raise VerifyFailure(
        "client did not settle in orb pickup range before request: "
        f"drop=({drop_x:.3f},{drop_y:.3f}) local_row={local_row} host_row={host_row} "
        f"client={last_client} host={last_host}"
    )


def move_client_out_of_pickup_range(
    *,
    drop_x: float,
    drop_y: float,
    timeout: float,
) -> dict[str, Any]:
    candidate_targets = [
        (drop_x + 900.0, drop_y + 900.0),
        (drop_x - 900.0, drop_y + 900.0),
        (drop_x + 900.0, drop_y - 900.0),
        (drop_x - 900.0, drop_y - 900.0),
        (drop_x + 1200.0, drop_y),
        (drop_x - 1200.0, drop_y),
    ]
    parking_x = candidate_targets[0][0]
    parking_y = candidate_targets[0][1]
    best_distance = -1.0
    for candidate_x, candidate_y in candidate_targets:
        try:
            snap_x, snap_y = snap_to_nav(CLIENT_PIPE, candidate_x, candidate_y)
        except Exception:
            snap_x, snap_y = candidate_x, candidate_y
        candidate_distance = distance(snap_x, snap_y, drop_x, drop_y)
        if candidate_distance > best_distance:
            best_distance = candidate_distance
            parking_x = snap_x
            parking_y = snap_y
    if best_distance < PICKUP_PARKING_MIN_DISTANCE:
        parking_x = drop_x + PICKUP_PARKING_MIN_DISTANCE + 128.0
        parking_y = drop_y + PICKUP_PARKING_MIN_DISTANCE + 128.0

    place = place_player(CLIENT_PIPE, parking_x, parking_y, 90.0)
    deadline = time.monotonic() + timeout
    last_client: dict[str, str] = {}
    last_host: dict[str, str] = {}
    host_row: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        last_client = capture(CLIENT_PIPE)
        last_host = capture(HOST_PIPE)
        client_distance = distance(
            parse_float_text(last_client.get("player.x")),
            parse_float_text(last_client.get("player.y")),
            drop_x,
            drop_y,
        )
        host_row = find_participant(last_host, CLIENT_ID)
        host_distance = (
            distance(host_row["x"], host_row["y"], drop_x, drop_y)
            if host_row is not None else 0.0
        )
        if (
            client_distance > PICKUP_SUPPRESSION_RADIUS and
            host_row is not None and
            host_distance > PICKUP_SUPPRESSION_RADIUS
        ):
            return {
                "place": place,
                "client_capture": last_client,
                "host_capture": last_host,
                "host_participant": host_row,
                "drop_x": drop_x,
                "drop_y": drop_y,
                "parking_x": parking_x,
                "parking_y": parking_y,
                "client_distance": client_distance,
                "host_distance": host_distance,
            }
        time.sleep(0.1)
    raise VerifyFailure(
        "client did not settle out of orb pickup range before spawn: "
        f"drop=({drop_x:.3f},{drop_y:.3f}) host_row={host_row} "
        f"client={last_client} host={last_host}"
    )


def wait_for_client_pickup_result(
    *,
    network_drop_id: int,
    request_sequence: int,
    expected_result: str,
    timeout: float,
) -> dict[str, str]:
    accepted = try_wait_for_client_pickup_result(
        network_drop_id=network_drop_id,
        request_sequence=request_sequence,
        expected_result=expected_result,
        timeout=timeout,
    )
    if accepted is not None:
        return accepted
    last = capture(CLIENT_PIPE)
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


def select_spawn_anchor(timeout: float) -> dict[str, Any]:
    return select_reachable_spawn_point(
        PickupGeometryRuntime(
            client_pipe=CLIENT_PIPE,
            client_participant_id=CLIENT_ID,
            capture_pair=capture_pair,
            find_participant=find_participant,
            place_player=place_player,
            snap_to_nav=snap_to_nav,
        ),
        pickup_suppression_radius=PICKUP_SUPPRESSION_RADIUS,
        timeout=timeout,
    )


def verify_one_orb_pickup(
    *,
    label: str,
    kind: str,
    resource_kind: int,
    expected_delta: float,
    native_max_hp: float,
    native_max_mp: float,
    anchor_x: float,
    anchor_y: float,
    timeout: float,
) -> dict[str, Any]:
    resource_max = (
        native_max_hp
        if resource_kind == HEALTH_RESOURCE_KIND
        else native_max_mp
    )
    headroom = max(2.0, min(10.0, resource_max * 0.1))
    base_current = resource_max - expected_delta - headroom
    if base_current <= VITAL_TOLERANCE:
        raise VerifyFailure(
            f"native {label} maximum is too small for a full orb delta: "
            f"maximum={resource_max} delta={expected_delta}"
        )
    fixture_ceiling = resource_max - expected_delta - VITAL_TOLERANCE

    result: dict[str, Any] = {
        "label": label,
        "native_max_hp": native_max_hp,
        "native_max_mp": native_max_mp,
        "fixture_base_current": base_current,
        "fixture_ceiling": fixture_ceiling,
    }
    result["set_client_resources"] = set_client_resources(
        hp=base_current if resource_kind == HEALTH_RESOURCE_KIND else None,
        mp=base_current if resource_kind == MANA_RESOURCE_KIND else None,
    )
    result["host_client_vitals_before"] = wait_for_host_client_resource_window(
        resource_kind=resource_kind,
        minimum_current=base_current,
        maximum_current=fixture_ceiling,
        expected_max=resource_max,
        timeout=timeout,
    )
    before_addresses = {row["address"] for row in orb_rows(capture(HOST_PIPE))}
    spawn_x = anchor_x
    spawn_y = anchor_y
    result["client_pre_spawn_parking"] = move_client_out_of_pickup_range(
        drop_x=spawn_x,
        drop_y=spawn_y,
        timeout=timeout,
    )
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
    network_drop_id = int(replicated_drop["network_id"])
    result["client_pickup_position"] = move_client_into_pickup_range(
        network_drop_id=network_drop_id,
        drop_x=float(replicated_drop["x"]),
        drop_y=float(replicated_drop["y"]),
        timeout=timeout,
    )
    result["pre_request_pair"] = capture_pair()
    accepted = try_wait_for_client_pickup_result(
        network_drop_id=network_drop_id,
        request_sequence=None,
        expected_result="Accepted",
        timeout=min(5.0, timeout),
    )
    if accepted is None:
        raise VerifyFailure(
            "client orb proximity hook did not accept the in-range pickup"
        )
    request_sequence = parse_int_text(accepted.get("pickup.request_sequence"), 0)
    result["request"] = {
        "ok": "true",
        "path": "client_proximity_hook",
        "request_sequence": str(request_sequence),
    }
    result["accepted_result"] = accepted
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
        "accepted_native_max_preserved": approximately(
            expected_max_hp if resource_kind == HEALTH_RESOURCE_KIND else expected_max_mp,
            resource_max,
        ),
        "accepted_result_includes_full_delta": (
            (expected_hp if resource_kind == HEALTH_RESOURCE_KIND else expected_mp) +
            VITAL_TOLERANCE >= base_current + expected_delta
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

    baseline = capture_client_vitals()
    result["baseline_client_vitals"] = baseline
    anchor = select_spawn_anchor(timeout=args.timeout)
    result["anchor"] = anchor
    anchor_x = float(anchor["snapped_x"])
    anchor_y = float(anchor["snapped_y"])
    result["health_orb"] = verify_one_orb_pickup(
        label="health",
        kind="health_orb",
        resource_kind=HEALTH_RESOURCE_KIND,
        expected_delta=HEALTH_DELTA,
        native_max_hp=baseline["max_hp"],
        native_max_mp=baseline["max_mp"],
        anchor_x=anchor_x,
        anchor_y=anchor_y,
        timeout=args.timeout,
    )
    result["mana_orb"] = verify_one_orb_pickup(
        label="mana",
        kind="mana_orb",
        resource_kind=MANA_RESOURCE_KIND,
        expected_delta=MANA_DELTA,
        native_max_hp=baseline["max_hp"],
        native_max_mp=baseline["max_mp"],
        anchor_x=anchor_x,
        anchor_y=anchor_y,
        timeout=args.timeout,
    )
    result["final_client_vitals"] = capture_client_vitals()
    result["final_host_client_vitals"] = wait_for_host_client_native_maxima(
        expected_max_hp=baseline["max_hp"],
        expected_max_mp=baseline["max_mp"],
        timeout=args.timeout,
    )
    final_client = result["final_client_vitals"]
    result["native_maxima_preserved"] = (
        approximately(final_client["max_hp"], baseline["max_hp"]) and
        approximately(final_client["max_mp"], baseline["max_mp"])
    )
    result["ok"] = (
        all(result["health_orb"]["conclusion"].values()) and
        all(result["mana_orb"]["conclusion"].values()) and
        result["native_maxima_preserved"]
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
