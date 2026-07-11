#!/usr/bin/env python3
"""Verify host-authored loot drops materialize as client presentation actors."""

from __future__ import annotations

import argparse
import json
import math
import time
from typing import Any

from verify_local_multiplayer_sync import (
    CLIENT_PIPE,
    HOST_PIPE,
    ROOT,
    VerifyFailure,
    disable_bots,
    launch_pair,
    lua,
    parse_key_values,
    place_player,
    start_host_testrun_and_wait_for_clients,
    stop_games,
)


RUNTIME_OUTPUT = ROOT / "runtime" / "multiplayer_loot_drop_materialization.json"
HOST_LOG = ROOT / "runtime/instances/local-mp-host/stage/.sdmod/logs/solomondarkmodloader.log"
CLIENT_LOG = ROOT / "runtime/instances/local-mp-client/stage/.sdmod/logs/solomondarkmodloader.log"
GOLD_TYPE_ID = 0x07DC
ORB_TYPE_ID = 0x07DB
ITEM_DROP_TYPE_ID = 0x07DD
POTION_ITEM_TYPE_ID = 0x1B59
MATCH_RADIUS = 260.0
PLAYER_PARK_DISTANCE = 1400.0
DROP_FORWARD_DISTANCE = 2600.0
DROP_SPACING = 240.0
FIELD_POSITION_TOLERANCE = 0.05
FLOAT_FIELD_TOLERANCE = 0.01
RADIUS_FIELD_TOLERANCE = 0.25
ORB_EXPECTED_RADIUS = 15.0
ORB_MAX_REASONABLE_RADIUS = 32.0
PROBE_GOLD_AMOUNT = 11
PROBE_HEALTH_RAW_VALUE = 3
PROBE_MANA_RAW_VALUE = 4
PROBE_POTION_SLOT = 1
PROBE_POTION_STACK = 1


CAPTURE_LUA = r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local function hx(v) return string.format("0x%08X", tonumber(v) or 0) end
local function finite(v)
  return type(v) == "number" and v == v and v ~= math.huge and v ~= -math.huge
end
local function u8(address) return tonumber(sd.debug.read_u8(address)) or 0 end
local function u32(address) return tonumber(sd.debug.read_u32(address)) or 0 end
local function f32(address) return tonumber(sd.debug.read_float(address)) or 0 end
local pos_x_offset = sd.debug.layout_offset("actor_position_x")
local pos_y_offset = sd.debug.layout_offset("actor_position_y")
local radius_offset = sd.debug.layout_offset("actor_collision_radius")
local type_id_offset = sd.debug.layout_offset("game_object_type_id")
local item_slot_offset = sd.debug.layout_offset("item_slot")
local potion_stack_count_offset = sd.debug.layout_offset("potion_stack_count")
local item_drop_held_item_offset = sd.debug.layout_offset("item_drop_held_item")
local function actor_x(address, fallback)
  if address ~= 0 and pos_x_offset ~= nil then return f32(address + pos_x_offset) end
  return tonumber(fallback) or 0
end
local function actor_y(address, fallback)
  if address ~= 0 and pos_y_offset ~= nil then return f32(address + pos_y_offset) end
  return tonumber(fallback) or 0
end
local function actor_radius(address, fallback)
  if address ~= 0 and radius_offset ~= nil then return f32(address + radius_offset) end
  return tonumber(fallback) or 0
end

local scene = sd.world.get_scene()
local player = sd.player.get_state()
emit("scene", scene and (scene.name or scene.kind) or "")
emit("player.x", player and player.x or 0)
emit("player.y", player and player.y or 0)

local actors = sd.world.list_actors() or {}
local actor_count = 0
for _, actor in ipairs(actors) do
  local type_id = tonumber(actor.object_type_id) or 0
  if type_id == 0x07DC or type_id == 0x07DB or type_id == 0x07DD then
    local address = tonumber(actor.actor_address) or 0
    if address ~= 0 and finite(tonumber(actor.x)) and finite(tonumber(actor.y)) then
      actor_count = actor_count + 1
      local prefix = "actor." .. tostring(actor_count) .. "."
      emit(prefix .. "address", hx(address))
      emit(prefix .. "type", type_id)
      emit(prefix .. "x", string.format("%.3f", actor_x(address, actor.x)))
      emit(prefix .. "y", string.format("%.3f", actor_y(address, actor.y)))
      emit(prefix .. "listed_x", string.format("%.3f", tonumber(actor.x) or 0))
      emit(prefix .. "listed_y", string.format("%.3f", tonumber(actor.y) or 0))
      emit(prefix .. "radius", string.format("%.3f", actor_radius(address, actor.radius)))
      if type_id == 0x07DC then
        emit(prefix .. "amount_tier", u8(address + 0x13C))
        emit(prefix .. "amount", u32(address + 0x140))
        emit(prefix .. "lifetime", u32(address + 0x144))
        emit(prefix .. "state_u8", u8(address + 0x148))
      else
        if type_id == 0x07DB then
          emit(prefix .. "amount_tier", u8(address + 0x13C))
          emit(prefix .. "value", string.format("%.3f", f32(address + 0x140)))
          emit(prefix .. "lifetime", u32(address + 0x144))
          emit(prefix .. "motion", string.format("%.3f", f32(address + 0x148)))
          emit(prefix .. "progress", string.format("%.3f", f32(address + 0x14C)))
        else
          local held_item = 0
          if item_drop_held_item_offset ~= nil then
            held_item = tonumber(sd.debug.read_ptr(address + item_drop_held_item_offset)) or 0
          end
          emit(prefix .. "held_item", hx(held_item))
          if held_item ~= 0 then
            if type_id_offset ~= nil then emit(prefix .. "item_type_id", u32(held_item + type_id_offset)) end
            if item_slot_offset ~= nil then emit(prefix .. "item_slot", sd.debug.read_i32(held_item + item_slot_offset) or -1) end
            if potion_stack_count_offset ~= nil then emit(prefix .. "stack_count", sd.debug.read_i32(held_item + potion_stack_count_offset) or 0) end
          end
        end
      end
    end
  end
end
emit("actor.count", actor_count)

local loot = sd.world.get_replicated_loot and sd.world.get_replicated_loot() or nil
emit("loot.valid", loot ~= nil)
emit("loot.scene_kind", loot and loot.scene_kind or "")
emit("loot.drop_count", loot and loot.drop_count or 0)
emit("loot.drop_total_count", loot and loot.drop_total_count or 0)
local drop_count = 0
if loot and loot.drops then
  for _, drop in ipairs(loot.drops) do
    local type_id = tonumber(drop.object_type_id or drop.native_type_id) or 0
    if type_id == 0x07DC or type_id == 0x07DB or type_id == 0x07DD then
      drop_count = drop_count + 1
      local prefix = "drop." .. tostring(drop_count) .. "."
      emit(prefix .. "network_id", drop.network_drop_id or 0)
      emit(prefix .. "type", type_id)
      emit(prefix .. "kind", drop.kind or "")
      emit(prefix .. "amount", drop.amount or 0)
      emit(prefix .. "amount_tier", drop.amount_tier or 0)
      emit(prefix .. "value", string.format("%.3f", tonumber(drop.value) or 0))
      emit(prefix .. "motion", string.format("%.3f", tonumber(drop.motion) or 0))
      emit(prefix .. "progress", string.format("%.3f", tonumber(drop.progress) or 0))
      emit(prefix .. "active", drop.active and 1 or 0)
      emit(prefix .. "presentation_state", drop.presentation_state or 0)
      emit(prefix .. "materialized", drop.materialized and 1 or 0)
      emit(prefix .. "local_actor_address", hx(drop.local_actor_address or 0))
      emit(prefix .. "lifetime", drop.lifetime or 0)
      emit(prefix .. "item_type_id", drop.item_type_id or 0)
      emit(prefix .. "item_slot", drop.item_slot or -1)
      emit(prefix .. "stack_count", drop.stack_count or 0)
      emit(prefix .. "x", string.format("%.3f", tonumber(drop.x) or 0))
      emit(prefix .. "y", string.format("%.3f", tonumber(drop.y) or 0))
    end
  end
end
emit("drop.count", drop_count)
"""


def values(pipe_name: str, code: str, timeout: float = 10.0) -> dict[str, str]:
    return parse_key_values(lua(pipe_name, code, timeout=timeout))


def parse_int(value: str | None, default: int = 0) -> int:
    if value is None:
        return default
    try:
        if value.startswith(("0x", "0X")):
            return int(value, 16)
        return int(float(value))
    except (TypeError, ValueError):
        return default


def parse_float(value: str | None, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def distance(ax: float, ay: float, bx: float, by: float) -> float:
    return math.hypot(ax - bx, ay - by)


def capture(pipe_name: str) -> dict[str, str]:
    return values(pipe_name, CAPTURE_LUA)


def actor_rows(capture_values: dict[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index in range(1, parse_int(capture_values.get("actor.count")) + 1):
        prefix = f"actor.{index}."
        rows.append({
            "address": parse_int(capture_values.get(prefix + "address")),
            "type": parse_int(capture_values.get(prefix + "type")),
            "x": parse_float(capture_values.get(prefix + "x")),
            "y": parse_float(capture_values.get(prefix + "y")),
            "listed_x": parse_float(capture_values.get(prefix + "listed_x")),
            "listed_y": parse_float(capture_values.get(prefix + "listed_y")),
            "radius": parse_float(capture_values.get(prefix + "radius")),
            "amount": parse_int(capture_values.get(prefix + "amount")),
            "amount_tier": parse_int(capture_values.get(prefix + "amount_tier")),
            "value": parse_float(capture_values.get(prefix + "value")),
            "lifetime": parse_int(capture_values.get(prefix + "lifetime")),
            "state_u8": parse_int(capture_values.get(prefix + "state_u8")),
            "motion": parse_float(capture_values.get(prefix + "motion")),
            "progress": parse_float(capture_values.get(prefix + "progress")),
            "held_item": parse_int(capture_values.get(prefix + "held_item")),
            "item_type_id": parse_int(capture_values.get(prefix + "item_type_id")),
            "item_slot": parse_int(capture_values.get(prefix + "item_slot"), -1),
            "stack_count": parse_int(capture_values.get(prefix + "stack_count")),
        })
    return rows


def drop_rows(capture_values: dict[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index in range(1, parse_int(capture_values.get("drop.count")) + 1):
        prefix = f"drop.{index}."
        rows.append({
            "network_id": parse_int(capture_values.get(prefix + "network_id")),
            "type": parse_int(capture_values.get(prefix + "type")),
            "kind": capture_values.get(prefix + "kind", ""),
            "amount": parse_int(capture_values.get(prefix + "amount")),
            "amount_tier": parse_int(capture_values.get(prefix + "amount_tier")),
            "value": parse_float(capture_values.get(prefix + "value")),
            "motion": parse_float(capture_values.get(prefix + "motion")),
            "progress": parse_float(capture_values.get(prefix + "progress")),
            "active": parse_int(capture_values.get(prefix + "active")),
            "presentation_state": parse_int(capture_values.get(prefix + "presentation_state")),
            "materialized": parse_int(capture_values.get(prefix + "materialized")),
            "local_actor_address": parse_int(capture_values.get(prefix + "local_actor_address")),
            "lifetime": parse_int(capture_values.get(prefix + "lifetime")),
            "item_type_id": parse_int(capture_values.get(prefix + "item_type_id")),
            "item_slot": parse_int(capture_values.get(prefix + "item_slot"), -1),
            "stack_count": parse_int(capture_values.get(prefix + "stack_count")),
            "x": parse_float(capture_values.get(prefix + "x")),
            "y": parse_float(capture_values.get(prefix + "y")),
        })
    return rows


def spawn_reward(pipe_name: str, *, kind: str, amount: int, x: float, y: float) -> dict[str, str]:
    code = f"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local ok, err = sd.world.spawn_reward({{kind="{kind}", amount={amount}, x={x:.3f}, y={y:.3f}}})
emit("ok", ok)
emit("err", err or "")
"""
    return values(pipe_name, code, timeout=8.0)


def require_host_spawn(kind: str, amount: int, x: float, y: float) -> dict[str, str]:
    result = spawn_reward(HOST_PIPE, kind=kind, amount=amount, x=x, y=y)
    if result.get("ok") != "true":
        raise VerifyFailure(f"host spawn_reward({kind}) failed: {result}")
    return result


def reject_client_spawn(x: float, y: float) -> dict[str, str]:
    result = spawn_reward(CLIENT_PIPE, kind="gold", amount=1, x=x, y=y)
    if result.get("ok") == "true":
        raise VerifyFailure(f"client spawn_reward unexpectedly succeeded: {result}")
    if "host-authoritative" not in result.get("err", ""):
        raise VerifyFailure(f"client spawn_reward rejected with unexpected error: {result}")
    return result


def find_matching_actor(
    rows: list[dict[str, Any]],
    *,
    actor_address: int,
    type_id: int,
    x: float,
    y: float,
) -> dict[str, Any] | None:
    for row in rows:
        if row["address"] != actor_address or row["type"] != type_id:
            continue
        row = dict(row)
        row["distance"] = round(distance(row["x"], row["y"], x, y), 3)
        if row["distance"] <= MATCH_RADIUS:
            return row
    return None


def select_actor(
    rows: list[dict[str, Any]],
    *,
    type_id: int,
    amount: int | None,
    resource_kind: int | None,
    raw_value: int | None,
    item_type_id: int | None = None,
    item_slot: int | None = None,
    stack_count: int | None = None,
    x: float,
    y: float,
) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for row in rows:
        if row["type"] != type_id:
            continue
        if amount is not None and row["amount"] != amount:
            continue
        if resource_kind is not None and row["amount_tier"] != resource_kind:
            continue
        if raw_value is not None and abs(row["value"] - raw_value) > FLOAT_FIELD_TOLERANCE:
            continue
        if item_type_id is not None and row["item_type_id"] != item_type_id:
            continue
        if item_slot is not None and row["item_slot"] != item_slot:
            continue
        if stack_count is not None and row["stack_count"] != stack_count:
            continue
        row_distance = distance(row["x"], row["y"], x, y)
        if row_distance > MATCH_RADIUS:
            continue
        candidate = dict(row)
        candidate["distance"] = round(row_distance, 3)
        candidates.append(candidate)
    if not candidates:
        return None
    candidates.sort(key=lambda row: row["distance"])
    return candidates[0]


def select_materialized_drop(
    capture_values: dict[str, str],
    *,
    type_id: int,
    amount: int | None,
    resource_kind: int | None,
    raw_value: int | None,
    item_type_id: int | None = None,
    item_slot: int | None = None,
    stack_count: int | None = None,
    x: float,
    y: float,
) -> dict[str, Any] | None:
    actors = actor_rows(capture_values)
    candidates: list[dict[str, Any]] = []
    for drop in drop_rows(capture_values):
        if drop["type"] != type_id or drop["network_id"] == 0:
            continue
        if amount is not None and drop["amount"] != amount:
            continue
        if resource_kind is not None and drop["amount_tier"] != resource_kind:
            continue
        if raw_value is not None and abs(drop["value"] - raw_value) > 0.01:
            continue
        if item_type_id is not None and drop["item_type_id"] != item_type_id:
            continue
        if item_slot is not None and drop["item_slot"] != item_slot:
            continue
        if stack_count is not None and drop["stack_count"] != stack_count:
            continue
        if not drop["active"] or not drop["materialized"] or drop["local_actor_address"] == 0:
            continue
        drop_distance = distance(drop["x"], drop["y"], x, y)
        if drop_distance > MATCH_RADIUS:
            continue
        actor = find_matching_actor(
            actors,
            actor_address=drop["local_actor_address"],
            type_id=type_id,
            x=x,
            y=y,
        )
        if actor is None:
            continue
        candidate = dict(drop)
        candidate["distance"] = round(drop_distance, 3)
        candidate["actor"] = actor
        candidates.append(candidate)
    if not candidates:
        return None
    candidates.sort(key=lambda row: row["distance"])
    return candidates[0]


def field_comparison(
    label: str,
    host_actor: dict[str, Any],
    client_drop: dict[str, Any],
) -> dict[str, Any]:
    client_actor = client_drop["actor"]
    x_delta = abs(host_actor["x"] - client_actor["x"])
    y_delta = abs(host_actor["y"] - client_actor["y"])
    comparison: dict[str, Any] = {
        "label": label,
        "ok": True,
        "host_actor": host_actor,
        "client_drop": client_drop,
        "position_delta": {
            "x": round(x_delta, 4),
            "y": round(y_delta, 4),
            "distance": round(distance(host_actor["x"], host_actor["y"], client_actor["x"], client_actor["y"]), 4),
        },
        "lifetime_delta": abs(host_actor["lifetime"] - client_actor["lifetime"]),
        "radius_delta": round(abs(host_actor["radius"] - client_actor["radius"]), 4),
        "failures": [],
    }

    def fail(reason: str) -> None:
        comparison["ok"] = False
        comparison["failures"].append(reason)

    if x_delta > FIELD_POSITION_TOLERANCE or y_delta > FIELD_POSITION_TOLERANCE:
        fail("client presentation actor position differs from host actor")
    if host_actor["amount_tier"] != client_actor["amount_tier"]:
        fail("amount/resource tier differs")
    if host_actor["type"] != client_actor["type"]:
        fail("native type differs")
    if abs(host_actor["radius"] - client_actor["radius"]) > RADIUS_FIELD_TOLERANCE:
        fail("client presentation actor radius differs from host actor")
    if host_actor["type"] == GOLD_TYPE_ID:
        if host_actor["amount"] != client_actor["amount"] or host_actor["amount"] != client_drop["amount"]:
            fail("gold amount differs")
        if host_actor["state_u8"] != client_actor["state_u8"]:
            fail("gold presentation state byte differs")
        if (
            host_actor["state_u8"] != client_drop["presentation_state"]
            and not (
                comparison["lifetime_delta"] <= 3
                and client_actor["state_u8"] == host_actor["state_u8"]
                and client_drop["active"] == 1
            )
        ):
            fail("gold snapshot presentation state differs from host actor")
    elif host_actor["type"] == ORB_TYPE_ID:
        motion_delta = abs(host_actor["motion"] - client_actor["motion"])
        allowed_motion_delta = comparison["lifetime_delta"] * 3.0 + 3.0
        snapshot_motion_delta = abs(client_drop["motion"] - client_actor["motion"])
        snapshot_lifetime_delta = abs(client_drop["lifetime"] - client_actor["lifetime"])
        allowed_snapshot_motion_delta = snapshot_lifetime_delta * 3.0 + 3.0
        progress_delta = abs(host_actor["progress"] - client_actor["progress"])
        allowed_progress_delta = comparison["lifetime_delta"] * 0.05 + 0.05
        snapshot_progress_delta = abs(client_drop["progress"] - client_actor["progress"])
        allowed_snapshot_progress_delta = snapshot_lifetime_delta * 0.05 + 0.05
        if client_actor["radius"] > ORB_MAX_REASONABLE_RADIUS:
            fail("client orb presentation radius is unreasonably large")
        if abs(client_actor["radius"] - ORB_EXPECTED_RADIUS) > RADIUS_FIELD_TOLERANCE:
            fail("client orb presentation radius differs from native expected radius")
        if abs(host_actor["value"] - client_actor["value"]) > FLOAT_FIELD_TOLERANCE:
            fail("orb raw value differs")
        if snapshot_motion_delta > allowed_snapshot_motion_delta:
            fail("orb snapshot motion drift is too large")
        if motion_delta > allowed_motion_delta:
            fail("orb motion differs")
        if snapshot_progress_delta > allowed_snapshot_progress_delta:
            fail("orb snapshot progress drift is too large")
        if progress_delta > allowed_progress_delta:
            fail("orb progress differs")
    elif host_actor["type"] == ITEM_DROP_TYPE_ID:
        if host_actor["held_item"] == 0 or client_actor["held_item"] == 0:
            fail("item drop held item pointer is missing")
        if host_actor["item_type_id"] != POTION_ITEM_TYPE_ID:
            fail("host item drop is not a potion")
        if client_actor["item_type_id"] != POTION_ITEM_TYPE_ID:
            fail("client item drop is not a potion")
        if host_actor["item_slot"] != client_actor["item_slot"] or host_actor["item_slot"] != client_drop["item_slot"]:
            fail("potion slot differs")
        if host_actor["stack_count"] != client_actor["stack_count"] or host_actor["stack_count"] != client_drop["stack_count"]:
            fail("potion stack count differs")
    if host_actor["lifetime"] != 0 and client_actor["lifetime"] == 0:
        fail("client presentation actor lifetime expired while host actor is live")
    return comparison


def log_tail(path, max_lines: int = 160) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return lines[-max_lines:]


def wait_for_materialized_drop(
    *,
    type_id: int,
    amount: int | None = None,
    resource_kind: int | None = None,
    raw_value: int | None = None,
    item_type_id: int | None = None,
    item_slot: int | None = None,
    stack_count: int | None = None,
    x: float,
    y: float,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = capture(CLIENT_PIPE)
        selected = select_materialized_drop(
            last,
            type_id=type_id,
            amount=amount,
            resource_kind=resource_kind,
            raw_value=raw_value,
            item_type_id=item_type_id,
            item_slot=item_slot,
            stack_count=stack_count,
            x=x,
            y=y,
        )
        if selected is not None:
            return {
                "capture": last,
                "drop": selected,
            }
        time.sleep(0.1)
    raise VerifyFailure(
        "client did not materialize host-authored loot drop; "
        f"type=0x{type_id:04X} amount={amount} resource_kind={resource_kind} "
        f"raw_value={raw_value} item_type=0x{item_type_id or 0:04X} "
        f"item_slot={item_slot} stack_count={stack_count} x={x:.3f} y={y:.3f} last={last}"
    )


def setup_pair(max_attempts: int) -> dict[str, Any]:
    last_error = ""
    for attempt in range(1, max_attempts + 1):
        try:
            stop_games()
            launch = launch_pair()
            disable_bots()
            run_entry = start_host_testrun_and_wait_for_clients()
            return {
                "attempt": attempt,
                "launch": launch,
                "run_entry": run_entry,
            }
        except Exception as exc:
            last_error = str(exc)
            stop_games()
            time.sleep(1.0)
    raise VerifyFailure(f"failed to prepare multiplayer run pair: {last_error}")


def run_verifier(args: argparse.Namespace) -> dict[str, Any]:
    result: dict[str, Any] = {"ok": False}
    if not args.no_launch:
        result["setup"] = setup_pair(args.attempts)

    host_before = capture(HOST_PIPE)
    host_x = parse_float(host_before.get("player.x"))
    host_y = parse_float(host_before.get("player.y"))
    result["player_parking"] = {
        "host": place_player(HOST_PIPE, host_x - PLAYER_PARK_DISTANCE, host_y, 180.0),
        "client": place_player(CLIENT_PIPE, host_x - PLAYER_PARK_DISTANCE, host_y - DROP_SPACING, 180.0),
    }
    time.sleep(0.25)

    gold_x, gold_y = host_x + DROP_FORWARD_DISTANCE, host_y
    health_x, health_y = host_x + DROP_FORWARD_DISTANCE + DROP_SPACING, host_y + DROP_SPACING
    mana_x, mana_y = host_x + DROP_FORWARD_DISTANCE + (DROP_SPACING * 2.0), host_y - DROP_SPACING
    potion_x, potion_y = host_x + DROP_FORWARD_DISTANCE + (DROP_SPACING * 3.0), host_y

    result["client_spawn_rejection"] = reject_client_spawn(gold_x, gold_y)
    result["host_spawns"] = {
        "gold": require_host_spawn("gold", PROBE_GOLD_AMOUNT, gold_x, gold_y),
        "health_orb": require_host_spawn("health_orb", PROBE_HEALTH_RAW_VALUE, health_x, health_y),
        "mana_orb": require_host_spawn("mana_orb", PROBE_MANA_RAW_VALUE, mana_x, mana_y),
        "mana_potion": require_host_spawn("mana_potion", PROBE_POTION_SLOT, potion_x, potion_y),
    }

    result["initial_materialized"] = {
        "gold": wait_for_materialized_drop(
            type_id=GOLD_TYPE_ID,
            amount=PROBE_GOLD_AMOUNT,
            x=gold_x,
            y=gold_y,
            timeout=args.timeout,
        )["drop"],
        "health_orb": wait_for_materialized_drop(
            type_id=ORB_TYPE_ID,
            resource_kind=0,
            raw_value=PROBE_HEALTH_RAW_VALUE,
            x=health_x,
            y=health_y,
            timeout=args.timeout,
        )["drop"],
        "mana_orb": wait_for_materialized_drop(
            type_id=ORB_TYPE_ID,
            resource_kind=1,
            raw_value=PROBE_MANA_RAW_VALUE,
            x=mana_x,
            y=mana_y,
            timeout=args.timeout,
        )["drop"],
        "mana_potion": wait_for_materialized_drop(
            type_id=ITEM_DROP_TYPE_ID,
            item_type_id=POTION_ITEM_TYPE_ID,
            item_slot=PROBE_POTION_SLOT,
            stack_count=PROBE_POTION_STACK,
            x=potion_x,
            y=potion_y,
            timeout=args.timeout,
        )["drop"],
    }
    result["final_host_capture"] = capture(HOST_PIPE)
    result["final_client_capture"] = capture(CLIENT_PIPE)
    result["materialized"] = {
        "gold": select_materialized_drop(
            result["final_client_capture"],
            type_id=GOLD_TYPE_ID,
            amount=PROBE_GOLD_AMOUNT,
            resource_kind=None,
            raw_value=None,
            x=gold_x,
            y=gold_y,
        ),
        "health_orb": select_materialized_drop(
            result["final_client_capture"],
            type_id=ORB_TYPE_ID,
            amount=None,
            resource_kind=0,
            raw_value=PROBE_HEALTH_RAW_VALUE,
            x=health_x,
            y=health_y,
        ),
        "mana_orb": select_materialized_drop(
            result["final_client_capture"],
            type_id=ORB_TYPE_ID,
            amount=None,
            resource_kind=1,
            raw_value=PROBE_MANA_RAW_VALUE,
            x=mana_x,
            y=mana_y,
        ),
        "mana_potion": select_materialized_drop(
            result["final_client_capture"],
            type_id=ITEM_DROP_TYPE_ID,
            amount=None,
            resource_kind=None,
            raw_value=None,
            item_type_id=POTION_ITEM_TYPE_ID,
            item_slot=PROBE_POTION_SLOT,
            stack_count=PROBE_POTION_STACK,
            x=potion_x,
            y=potion_y,
        ),
    }
    missing_client = [
        label
        for label, drop in result["materialized"].items()
        if drop is None
    ]
    if missing_client and any(result["initial_materialized"].get(label) is None for label in missing_client):
        raise VerifyFailure(f"client materialized drop actor(s) missing in final capture: {missing_client}")
    host_actors = actor_rows(result["final_host_capture"])
    result["host_actors"] = {
        "gold": select_actor(
            host_actors,
            type_id=GOLD_TYPE_ID,
            amount=PROBE_GOLD_AMOUNT,
            resource_kind=None,
            raw_value=None,
            x=gold_x,
            y=gold_y,
        ),
        "health_orb": select_actor(
            host_actors,
            type_id=ORB_TYPE_ID,
            amount=None,
            resource_kind=0,
            raw_value=PROBE_HEALTH_RAW_VALUE,
            x=health_x,
            y=health_y,
        ),
        "mana_orb": select_actor(
            host_actors,
            type_id=ORB_TYPE_ID,
            amount=None,
            resource_kind=1,
            raw_value=PROBE_MANA_RAW_VALUE,
            x=mana_x,
            y=mana_y,
        ),
        "mana_potion": select_actor(
            host_actors,
            type_id=ITEM_DROP_TYPE_ID,
            amount=None,
            resource_kind=None,
            raw_value=None,
            item_type_id=POTION_ITEM_TYPE_ID,
            item_slot=PROBE_POTION_SLOT,
            stack_count=PROBE_POTION_STACK,
            x=potion_x,
            y=potion_y,
        ),
    }
    missing_host = [
        label
        for label, actor in result["host_actors"].items()
        if actor is None
    ]
    if missing_host:
        raise VerifyFailure(f"host drop actor(s) missing after spawn: {missing_host}")
    result["field_comparisons"] = {
        label: field_comparison(label, result["host_actors"][label], drop or result["initial_materialized"][label])
        for label, drop in result["materialized"].items()
    }
    result["log_tails"] = {
        "host": log_tail(HOST_LOG),
        "client": log_tail(CLIENT_LOG),
    }
    result["ok"] = all(
        row is not None and row["materialized"] == 1 and row["local_actor_address"] != 0
        for row in result["initial_materialized"].values()
    ) and all(
        comparison["ok"]
        for comparison in result["field_comparisons"].values()
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-launch", action="store_true")
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()

    result: dict[str, Any] = {"ok": False}
    try:
        result = run_verifier(args)
        RUNTIME_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        RUNTIME_OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps({
            "ok": result["ok"],
            "materialized": result.get("materialized"),
            "field_comparisons": result.get("field_comparisons"),
            "client_spawn_rejection": result.get("client_spawn_rejection"),
            "output": str(RUNTIME_OUTPUT),
        }, indent=2, sort_keys=True))
        return 0 if result["ok"] else 1
    except Exception as exc:
        result["error"] = str(exc)
        RUNTIME_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        RUNTIME_OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 1
    finally:
        if not args.no_launch:
            stop_games()


if __name__ == "__main__":
    raise SystemExit(main())
