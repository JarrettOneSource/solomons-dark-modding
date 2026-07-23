#!/usr/bin/env python3
"""Verify registered Lua enemy AI across a local multiplayer pair."""

from __future__ import annotations

import argparse
import json
import math
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from multiplayer_lua_probe import DEFAULT_CLIENTS, parse_client, run_lua_client
from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_NAME,
    CLIENT_PIPE,
    HOST_ID,
    HOST_NAME,
    HOST_PIPE,
    disable_bots,
    game_process_ids,
    launch_pair,
    start_host_testrun_and_wait_for_clients,
    stop_game_processes,
    wait_for_remote,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "runtime" / "lua_ai_multiplayer_verification.json"
ACCEPTANCE_MOD_ID = "sample.lua.ai_boss_lab"
EXPECTED_CONTENT_ID = 6758053804871806748
EXPECTED_HP = 500.0
EXPECTED_SPEED = 2.8
EXPECTED_SCALE = 1.35
EXPECTED_SPAWN_FLAGS = 11
MINIMUM_MOVEMENT_DISTANCE = 3.0


SET_MANUAL_MODE = """
local ok, active = sd.gameplay.set_manual_enemy_spawner_test_mode(true)
print("ok=" .. tostring(ok))
print("active=" .. tostring(active))
"""

ENABLE_PRELUDE = """
print("ok=" .. tostring(sd.gameplay.enable_combat_prelude()))
"""

COMBAT_STATE = """
local state = sd.gameplay.get_combat_state()
print("available=" .. tostring(state ~= nil))
print("active=" .. tostring(state ~= nil and state.active))
print("wave_index=" .. tostring(state and state.wave_index or -1))
print("wave_counter=" .. tostring(state and state.wave_counter or -1))
"""

START_WAVES = """
print("ok=" .. tostring(sd.gameplay.start_waves()))
"""

SPAWNER_STATE = """
local state = sd.gameplay.get_manual_enemy_spawner_state()
print("manual_mode=" .. tostring(state ~= nil and state.manual_mode))
print("has_spawner=" .. tostring(state ~= nil and state.has_spawner))
"""

CLEAN_SCENE = f"""
local live = 0
local content_rows = 0
for _, actor in ipairs(sd.world.list_actors() or {{}}) do
  if actor.tracked_enemy and not actor.dead and
      (tonumber(actor.hp) or 0) > 0.05 then
    live = live + 1
  end
end
local snapshot = sd.world.get_replicated_actors()
for _, actor in ipairs(snapshot and snapshot.actors or {{}}) do
  if tonumber(actor.content_id) == {EXPECTED_CONTENT_ID} then
    content_rows = content_rows + 1
  end
end
print("live_enemy_count=" .. tostring(live))
print("content_row_count=" .. tostring(content_rows))
print("ai_instance_count=" .. tostring(#sd.ai.list()))
"""

REGISTRY_STATUS = f"""
local mod = assert(sd.runtime.get_mod())
local enemy = assert(
  sd.enemies.get({EXPECTED_CONTENT_ID}),
  "Lua AI boss registration is unavailable")
print("mod_id=" .. tostring(mod.id))
print("authority=" .. tostring(sd.state.is_authority()))
print("content_id=" .. tostring(enemy.id))
print("base=" .. tostring(enemy.base))
print("hp=" .. tostring(enemy.hp))
print("speed=" .. tostring(enemy.speed))
print("scale=" .. tostring(enemy.scale))
print("ai_instance_count=" .. tostring(#sd.ai.list()))
"""

NAV_CANDIDATE = """
local grid = sd.nav.get_grid(1)
local player = sd.player.get_state()
if grid == nil or grid.refresh_pending or player == nil then
  print("ready=false")
  return
end
local best = nil
local best_distance = 0
for _, cell in ipairs(grid.cells or {}) do
  for _, sample in ipairs(cell.samples or {}) do
    if sample.traversable then
      local dx = sample.world_x - player.x
      local dy = sample.world_y - player.y
      local distance = math.sqrt(dx * dx + dy * dy)
      if distance >= 400 and distance <= 1200 and
          distance > best_distance and
          sd.nav.test_segment(
            player.x, player.y, sample.world_x, sample.world_y) then
        best = sample
        best_distance = distance
      end
    end
  end
end
print("ready=" .. tostring(best ~= nil))
print("x=" .. tostring(best and best.world_x or 0))
print("y=" .. tostring(best and best.world_y or 0))
print("distance=" .. tostring(best_distance))
"""


def _queue_spawn_probe(x: float, y: float) -> str:
    return f"""
assert(sd.state.is_authority(), "AI boss spawn probe is not the authority")
local queued = sd.enemies.spawn({EXPECTED_CONTENT_ID}, {{
  x = {x},
  y = {y},
  hp = {EXPECTED_HP},
  speed = {EXPECTED_SPEED},
  scale = {EXPECTED_SCALE},
  loot = "none",
}})
print("queued=" .. tostring(queued.queued))
print("request_id=" .. tostring(queued.request_id))
print("content_id=" .. tostring(queued.content_id))
print("native_type_id=" .. tostring(queued.native_type_id))
print("requested_x=" .. tostring({x}))
print("requested_y=" .. tostring({y}))
"""


def _spawn_result_probe(request_id: int) -> str:
    return f"""
local result = sd.gameplay.get_last_manual_run_enemy_spawn({request_id})
print("complete=" .. tostring(result ~= nil))
if result == nil then return end
local actor = nil
for _, row in ipairs(sd.world.list_actors() or {{}}) do
  if tonumber(row.actor_address) == tonumber(result.actor_address) then
    actor = row
    break
  end
end
print("ok=" .. tostring(result.ok))
print("request_id=" .. tostring(result.request_id))
print("content_id=" .. tostring(result.content_id))
print("enemy_type=" .. tostring(result.type_id))
print("actor_address=" .. tostring(result.actor_address))
print("network_actor_id=" .. tostring(result.network_actor_id))
print("requested_x=" .. tostring(result.requested_x))
print("requested_y=" .. tostring(result.requested_y))
print("x=" .. tostring(result.x))
print("y=" .. tostring(result.y))
print("rebind_ok=" .. tostring(result.rebind_ok))
print("error=" .. tostring(result.error))
print("actor_found=" .. tostring(actor ~= nil))
print("object_type_id=" .. tostring(actor and actor.object_type_id or 0))
print("actor_hp=" .. tostring(actor and actor.hp or 0))
print("actor_max_hp=" .. tostring(actor and actor.max_hp or 0))
"""


def _host_ai_probe(network_actor_id: int) -> str:
    return f"""
local expected_network_id = {network_actor_id}
local state = sd.ai.get_state(expected_network_id)
local actor = sd.world.get_run_enemy_by_network_id(expected_network_id)
local target_id = 0
if state ~= nil and state.target_mode == "local" then
  target_id = {HOST_ID}
elseif state ~= nil and state.target_mode == "participant" then
  target_id = tonumber(state.target_participant_id) or 0
end
local target = nil
if state ~= nil and state.target_mode == "local" then
  target = sd.player.get_state()
elseif target_id > 0 then
  target = sd.bots.get_participant_state(target_id)
end
local goal_dx = state and state.move_goal and target and
  (state.move_goal.x - target.x) or 0
local goal_dy = state and state.move_goal and target and
  (state.move_goal.y - target.y) or 0
local goal_axis_aligned =
  (math.abs(math.abs(goal_dx) - 120) <= 12 and math.abs(goal_dy) <= 12) or
  (math.abs(math.abs(goal_dy) - 120) <= 12 and math.abs(goal_dx) <= 12)
local raw_internals_absent = state ~= nil and
  state.actor_address == nil and state.vtable == nil and
  state.callback_reference == nil and state.on_think == nil and
  state.registry_index == nil and state.native_function == nil
print("authority=" .. tostring(sd.state.is_authority()))
print("instance_count=" .. tostring(#sd.ai.list()))
print("found=" .. tostring(state ~= nil))
print("network_actor_id=" .. tostring(
  state and state.network_actor_id or 0))
print("content_id=" .. tostring(state and state.content_id or 0))
print("key=" .. tostring(state and state.key or ""))
print("base=" .. tostring(state and state.base or ""))
print("active=" .. tostring(state ~= nil and state.active))
print("think_count=" .. tostring(state and state.think_count or 0))
print("blackboard_step=" .. tostring(
  state and type(state.blackboard) == "table" and
  state.blackboard.step or -1))
print("target_mode=" .. tostring(state and state.target_mode or ""))
print("target_participant_id=" .. tostring(target_id))
print("target_found=" .. tostring(target ~= nil))
print("goal_offset_distance=" .. tostring(
  math.sqrt(goal_dx * goal_dx + goal_dy * goal_dy)))
print("goal_axis_aligned=" .. tostring(goal_axis_aligned))
print("move_goal_active=" .. tostring(
  state ~= nil and state.move_goal ~= nil))
print("move_goal_x=" .. tostring(
  state and state.move_goal and state.move_goal.x or 0))
print("move_goal_y=" .. tostring(
  state and state.move_goal and state.move_goal.y or 0))
print("move_goal_stop_distance=" .. tostring(
  state and state.move_goal and state.move_goal.stop_distance or 0))
print("raw_internals_absent=" .. tostring(raw_internals_absent))
print("actor_found=" .. tostring(actor ~= nil))
print("actor_x=" .. tostring(actor and actor.x or 0))
print("actor_y=" .. tostring(actor and actor.y or 0))
print("actor_object_type_id=" .. tostring(
  actor and actor.object_type_id or 0))
print("actor_enemy_type=" .. tostring(actor and actor.enemy_type or -1))
print("actor_hp=" .. tostring(actor and actor.hp or 0))
print("actor_max_hp=" .. tostring(actor and actor.max_hp or 0))
print("actor_dead=" .. tostring(actor ~= nil and actor.dead))
print("actor_tracked=" .. tostring(actor ~= nil and actor.tracked_enemy))
"""


def _client_snapshot_probe(network_actor_id: int) -> str:
    return f"""
local expected_network_id = {network_actor_id}
local snapshot = sd.world.get_replicated_actors()
local row = nil
local matching = 0
for _, candidate in ipairs(snapshot and snapshot.actors or {{}}) do
  if tonumber(candidate.network_actor_id) == expected_network_id then
    matching = matching + 1
    row = candidate
  end
end
local binding = nil
local binding_count = 0
for _, candidate in ipairs(snapshot and snapshot.bindings or {{}}) do
  if tonumber(candidate.network_actor_id) == expected_network_id then
    binding_count = binding_count + 1
    binding = candidate
  end
end
local actor = sd.world.get_run_enemy_by_network_id(expected_network_id)
local dx = row and actor and
  ((tonumber(row.x) or 0) - (tonumber(actor.x) or 0)) or 999999
local dy = row and actor and
  ((tonumber(row.y) or 0) - (tonumber(actor.y) or 0)) or 999999
print("authority=" .. tostring(sd.state.is_authority()))
print("ai_instance_count=" .. tostring(#sd.ai.list()))
print("ai_state_nil=" .. tostring(sd.ai.get_state(expected_network_id) == nil))
print("snapshot_available=" .. tostring(snapshot ~= nil))
print("snapshot_authority_id=" .. tostring(
  snapshot and snapshot.authority_participant_id or 0))
print("matching_rows=" .. tostring(matching))
print("network_actor_id=" .. tostring(row and row.network_actor_id or 0))
print("content_id=" .. tostring(row and row.content_id or 0))
print("object_type_id=" .. tostring(row and row.object_type_id or 0))
print("enemy_type=" .. tostring(row and row.enemy_type or -1))
print("spawn_flags=" .. tostring(row and row.content_spawn_flags or 0))
print("spawn_hp=" .. tostring(row and row.content_spawn_hp or 0))
print("spawn_speed=" .. tostring(row and row.content_spawn_speed or 0))
print("spawn_scale=" .. tostring(row and row.content_spawn_scale or 0))
print("target_participant_id=" .. tostring(
  row and row.target_participant_id or 0))
print("target_authoritative=" .. tostring(
  row ~= nil and row.target_authoritative))
print("row_x=" .. tostring(row and row.x or 0))
print("row_y=" .. tostring(row and row.y or 0))
print("row_dead=" .. tostring(row ~= nil and row.dead))
print("row_tracked=" .. tostring(row ~= nil and row.tracked_enemy))
print("row_lifecycle_owned=" .. tostring(
  row ~= nil and row.lifecycle_owned))
print("raw_addresses_absent=" .. tostring(
  row ~= nil and row.actor_address == nil and row.config_address == nil))
print("binding_count=" .. tostring(binding_count))
print("binding_address=" .. tostring(
  binding and binding.local_actor_address or 0))
print("binding_matched=" .. tostring(binding ~= nil and binding.matched))
print("binding_parked=" .. tostring(binding ~= nil and binding.parked))
print("binding_removed=" .. tostring(binding ~= nil and binding.removed))
print("local_found=" .. tostring(actor ~= nil))
print("local_address=" .. tostring(actor and actor.actor_address or 0))
print("local_object_type_id=" .. tostring(
  actor and actor.object_type_id or 0))
print("local_enemy_type=" .. tostring(actor and actor.enemy_type or -1))
print("local_dead=" .. tostring(actor ~= nil and actor.dead))
print("local_tracked=" .. tostring(actor ~= nil and actor.tracked_enemy))
print("position_error=" .. tostring(math.sqrt(dx * dx + dy * dy)))
"""


def _client_mutation_rejection_probe(network_actor_id: int) -> str:
    return f"""
local target_ok, target_error = pcall(
  sd.ai.set_target, {network_actor_id}, "local")
local goal_ok, goal_error = pcall(
  sd.ai.set_move_goal, {network_actor_id}, 10, 20, 36)
print("target_rejected=" .. tostring(not target_ok))
print("goal_rejected=" .. tostring(not goal_ok))
print("target_authority_error=" .. tostring(
  type(target_error) == "string" and
  string.find(target_error, "authority", 1, true) ~= nil))
print("goal_authority_error=" .. tostring(
  type(goal_error) == "string" and
  string.find(goal_error, "authority", 1, true) ~= nil))
print("ai_instance_count=" .. tostring(#sd.ai.list()))
"""


def _movement_segment_probe(
    start_x: float,
    start_y: float,
    network_actor_id: int,
) -> str:
    return f"""
local actor = assert(sd.world.get_run_enemy_by_network_id({network_actor_id}))
local ok, clear = pcall(
  sd.nav.test_segment, {start_x}, {start_y}, actor.x, actor.y)
print("query_ok=" .. tostring(ok))
print("segment_clear=" .. tostring(ok and clear))
print("actor_x=" .. tostring(actor.x))
print("actor_y=" .. tostring(actor.y))
"""


def _kill_probe(actor_address: int) -> str:
    return f"""
local wrote = sd.gameplay.set_run_enemy_health(
  {actor_address}, 0, {EXPECTED_HP})
local triggered, exception_code = sd.world.trigger_enemy_death({actor_address})
print("health_zeroed=" .. tostring(wrote))
print("death_triggered=" .. tostring(triggered))
print("exception_code=" .. tostring(exception_code or 0))
"""


def _retired_probe(network_actor_id: int) -> str:
    return f"""
print("instance_count=" .. tostring(#sd.ai.list()))
print("state_nil=" .. tostring(sd.ai.get_state({network_actor_id}) == nil))
"""


def _cleanup_probe(request_id: int, actor_address: int) -> str:
    return f"""
local actor_address = {actor_address}
if actor_address <= 0 and {request_id} > 0 then
  local result = sd.gameplay.get_last_manual_run_enemy_spawn({request_id})
  actor_address = tonumber(result and result.actor_address) or 0
end
if actor_address > 0 then
  pcall(sd.gameplay.set_run_enemy_health, actor_address, 0, {EXPECTED_HP})
  pcall(sd.world.trigger_enemy_death, actor_address)
end
return true
"""


def _failed_exec(result: dict[str, Any]) -> str | None:
    if result.get("returncode") == 0:
        return None
    return str(
        result.get("stderr") or result.get("stdout") or "Lua exec failed"
    ).strip()


def _values(result: dict[str, Any]) -> dict[str, str]:
    values = result.get("values", {})
    if not isinstance(values, dict):
        raise RuntimeError(f"Lua probe returned invalid values: {result}")
    return values


def _int_value(values: dict[str, str], name: str) -> int:
    try:
        return int(values.get(name, ""))
    except ValueError as error:
        raise RuntimeError(f"invalid {name}: {values}") from error


def _positive_int(values: dict[str, str], name: str) -> int:
    value = _int_value(values, name)
    if value <= 0:
        raise RuntimeError(f"invalid {name}: {values}")
    return value


def _number_value(values: dict[str, str], name: str) -> float:
    try:
        value = float(values.get(name, ""))
    except ValueError as error:
        raise RuntimeError(f"invalid {name}: {values}") from error
    if not math.isfinite(value):
        raise RuntimeError(f"non-finite {name}: {values}")
    return value


def _near(values: dict[str, str], name: str, expected: float, tolerance: float) -> bool:
    try:
        return abs(_number_value(values, name) - expected) <= tolerance
    except RuntimeError:
        return False


def registry_matches(values: dict[str, str], *, authority: bool) -> bool:
    try:
        return (
            values.get("mod_id") == ACCEPTANCE_MOD_ID
            and values.get("authority") == ("true" if authority else "false")
            and _int_value(values, "content_id") == EXPECTED_CONTENT_ID
            and values.get("base") == "skeleton_mage"
            and _near(values, "hp", EXPECTED_HP, 0.001)
            and _near(values, "speed", EXPECTED_SPEED, 0.001)
            and _near(values, "scale", EXPECTED_SCALE, 0.001)
            and _int_value(values, "ai_instance_count") == 0
        )
    except RuntimeError:
        return False


def spawn_result_matches(values: dict[str, str], request_id: int) -> bool:
    try:
        return (
            values.get("complete") == "true"
            and values.get("ok") == "true"
            and _int_value(values, "request_id") == request_id
            and _int_value(values, "content_id") == EXPECTED_CONTENT_ID
            and _int_value(values, "enemy_type") >= 0
            and _positive_int(values, "actor_address") > 0
            and _positive_int(values, "network_actor_id") > 0
            and values.get("rebind_ok") == "true"
            and values.get("error") in ("", "nil")
            and values.get("actor_found") == "true"
            and _positive_int(values, "object_type_id") > 0
            and _near(values, "actor_hp", EXPECTED_HP, 0.05)
            and _near(values, "actor_max_hp", EXPECTED_HP, 0.05)
            and abs(
                _number_value(values, "x")
                - _number_value(values, "requested_x")
            )
            <= 0.05
            and abs(
                _number_value(values, "y")
                - _number_value(values, "requested_y")
            )
            <= 0.05
        )
    except RuntimeError:
        return False


def host_ai_matches(
    values: dict[str, str],
    *,
    network_actor_id: int,
    object_type_id: int,
    enemy_type: int,
    minimum_think_count: int,
    start_x: float | None = None,
    start_y: float | None = None,
) -> bool:
    try:
        think_count = _int_value(values, "think_count")
        actor_x = _number_value(values, "actor_x")
        actor_y = _number_value(values, "actor_y")
        movement_matches = True
        if start_x is not None and start_y is not None:
            movement_matches = math.hypot(
                actor_x - start_x,
                actor_y - start_y,
            ) >= MINIMUM_MOVEMENT_DISTANCE
        return (
            values.get("authority") == "true"
            and _int_value(values, "instance_count") == 1
            and values.get("found") == "true"
            and _int_value(values, "network_actor_id") == network_actor_id
            and _int_value(values, "content_id") == EXPECTED_CONTENT_ID
            and values.get("key") == "grave_oracle"
            and values.get("base") == "skeleton_mage"
            and values.get("active") == "true"
            and think_count >= minimum_think_count
            and _int_value(values, "blackboard_step") == think_count
            and values.get("target_mode") in ("local", "participant")
            and _positive_int(values, "target_participant_id") > 0
            and values.get("target_found") == "true"
            and _near(values, "goal_offset_distance", 120.0, 12.0)
            and values.get("goal_axis_aligned") == "true"
            and values.get("move_goal_active") == "true"
            and abs(_number_value(values, "move_goal_x")) <= 20000.0
            and abs(_number_value(values, "move_goal_y")) <= 20000.0
            and _near(values, "move_goal_stop_distance", 36.0, 0.001)
            and values.get("raw_internals_absent") == "true"
            and values.get("actor_found") == "true"
            and _int_value(values, "actor_object_type_id") == object_type_id
            and _int_value(values, "actor_enemy_type") == enemy_type
            and _near(values, "actor_max_hp", EXPECTED_HP, 0.05)
            and values.get("actor_dead") == "false"
            and values.get("actor_tracked") == "true"
            and movement_matches
        )
    except RuntimeError:
        return False


def client_snapshot_matches(
    values: dict[str, str],
    *,
    network_actor_id: int,
    object_type_id: int,
    enemy_type: int,
    target_participant_id: int,
    start_x: float | None = None,
    start_y: float | None = None,
) -> bool:
    try:
        row_x = _number_value(values, "row_x")
        row_y = _number_value(values, "row_y")
        movement_matches = True
        if start_x is not None and start_y is not None:
            movement_matches = math.hypot(
                row_x - start_x,
                row_y - start_y,
            ) >= MINIMUM_MOVEMENT_DISTANCE
        return (
            values.get("authority") == "false"
            and _int_value(values, "ai_instance_count") == 0
            and values.get("ai_state_nil") == "true"
            and values.get("snapshot_available") == "true"
            and _int_value(values, "snapshot_authority_id") == HOST_ID
            and _int_value(values, "matching_rows") == 1
            and _int_value(values, "network_actor_id") == network_actor_id
            and _int_value(values, "content_id") == EXPECTED_CONTENT_ID
            and _int_value(values, "object_type_id") == object_type_id
            and _int_value(values, "enemy_type") == enemy_type
            and _int_value(values, "spawn_flags") == EXPECTED_SPAWN_FLAGS
            and _near(values, "spawn_hp", EXPECTED_HP, 0.001)
            and _near(values, "spawn_speed", EXPECTED_SPEED, 0.001)
            and _near(values, "spawn_scale", EXPECTED_SCALE, 0.001)
            and _int_value(values, "target_participant_id")
            == target_participant_id
            and values.get("target_authoritative") == "true"
            and values.get("row_dead") == "false"
            and values.get("row_tracked") == "true"
            and values.get("row_lifecycle_owned") == "true"
            and values.get("raw_addresses_absent") == "true"
            and _int_value(values, "binding_count") == 1
            and _positive_int(values, "binding_address") > 0
            and values.get("binding_matched") == "true"
            and values.get("binding_parked") == "false"
            and values.get("binding_removed") == "false"
            and values.get("local_found") == "true"
            and _positive_int(values, "local_address")
            == _positive_int(values, "binding_address")
            and _int_value(values, "local_object_type_id") == object_type_id
            and _int_value(values, "local_enemy_type") == enemy_type
            and values.get("local_dead") == "false"
            and values.get("local_tracked") == "true"
            and _number_value(values, "position_error") <= 12.0
            and movement_matches
        )
    except RuntimeError:
        return False


def _run_probe(client: tuple[str, str], code: str) -> dict[str, Any]:
    result = run_lua_client(client[0], client[1], code, timeout=12.0)
    failure = _failed_exec(result)
    if failure:
        raise RuntimeError(failure)
    return result


def _poll_probe(
    client: tuple[str, str],
    code: str,
    predicate: Callable[[dict[str, str]], bool],
    *,
    timeout: float,
    description: str,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = run_lua_client(client[0], client[1], code, timeout=12.0)
        values = last.get("values", {})
        if (
            _failed_exec(last) is None
            and isinstance(values, dict)
            and predicate(values)
        ):
            return last
        time.sleep(0.1)
    raise RuntimeError(f"{description} did not converge for {client[0]}: {last}")


def _bootstrap_manual_spawners(
    clients: list[tuple[str, str]],
    timeout: float,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    result["manual_mode"] = [_run_probe(peer, SET_MANUAL_MODE) for peer in clients]
    for probe in result["manual_mode"]:
        values = _values(probe)
        if values.get("ok") != "true" or values.get("active") != "true":
            raise RuntimeError(f"manual spawner mode failed: {probe}")
    result["prelude"] = [_run_probe(peer, ENABLE_PRELUDE) for peer in clients]
    if any(_values(probe).get("ok") != "true" for probe in result["prelude"]):
        raise RuntimeError(f"combat prelude failed: {result['prelude']}")
    result["combat"] = [
        _poll_probe(
            peer,
            COMBAT_STATE,
            lambda values: (
                values.get("available") == "true"
                and values.get("active") == "true"
                and values.get("wave_index") == "0"
                and values.get("wave_counter") == "999999999"
            ),
            timeout=timeout,
            description="manual combat state",
        )
        for peer in clients
    ]
    result["start_waves"] = [_run_probe(peer, START_WAVES) for peer in clients]
    if any(
        _values(probe).get("ok") != "true" for probe in result["start_waves"]
    ):
        raise RuntimeError(f"native spawner priming failed: {result['start_waves']}")
    result["spawners"] = [
        _poll_probe(
            peer,
            SPAWNER_STATE,
            lambda values: (
                values.get("manual_mode") == "true"
                and values.get("has_spawner") == "true"
            ),
            timeout=timeout,
            description="native manual spawner",
        )
        for peer in clients
    ]
    result["clean_scenes"] = [
        _poll_probe(
            peer,
            CLEAN_SCENE,
            lambda values: (
                values.get("live_enemy_count") == "0"
                and values.get("content_row_count") == "0"
                and values.get("ai_instance_count") == "0"
            ),
            timeout=timeout,
            description="empty Lua AI scene",
        )
        for peer in clients
    ]
    return result


def _best_effort_cleanup(
    host: tuple[str, str],
    *,
    request_id: int,
    actor_address: int,
) -> None:
    try:
        run_lua_client(
            host[0],
            host[1],
            _cleanup_probe(request_id, actor_address),
            timeout=5.0,
        )
    except Exception:
        pass


def run(
    clients: list[tuple[str, str]],
    *,
    launch: bool,
    timeout: float,
) -> dict[str, Any]:
    if len(clients) < 2:
        raise RuntimeError("at least a host and client Lua endpoint are required")
    host = clients[0]
    client = clients[1]
    peers = [host, client]
    result: dict[str, Any] = {
        "ok": False,
        "launched_pair": launch,
        "host": host[0],
        "client": client[0],
    }
    launched_process_ids: list[int] = []
    request_id = 0
    actor_address = 0
    mutation_touched = False
    killed = False
    try:
        if launch:
            result["pair"] = launch_pair(
                god_mode=True,
                tile_windows=False,
                kill_existing=False,
                exact_mod_id=ACCEPTANCE_MOD_ID,
            )
            launched_process_ids.extend(game_process_ids(result["pair"]))
            disable_bots()
            wait_for_remote(HOST_PIPE, CLIENT_ID, CLIENT_NAME, "hub")
            wait_for_remote(CLIENT_PIPE, HOST_ID, HOST_NAME, "hub")
            result["run"] = start_host_testrun_and_wait_for_clients(
                timeout=timeout,
            )
            wait_for_remote(HOST_PIPE, CLIENT_ID, CLIENT_NAME, "testrun")
            wait_for_remote(CLIENT_PIPE, HOST_ID, HOST_NAME, "testrun")

        result["combat_bootstrap"] = _bootstrap_manual_spawners(peers, timeout)
        result["registries"] = [
            _poll_probe(
                peer,
                REGISTRY_STATUS,
                lambda values, authority=index == 0: registry_matches(
                    values,
                    authority=authority,
                ),
                timeout=timeout,
                description="Lua AI registry",
            )
            for index, peer in enumerate(peers)
        ]
        nav = _poll_probe(
            host,
            NAV_CANDIDATE,
            lambda values: (
                values.get("ready") == "true"
                and 400.0 <= _number_value(values, "distance") <= 1200.0
            ),
            timeout=timeout,
            description="clear Lua AI spawn lane",
        )
        result["nav_candidate"] = nav
        nav_values = _values(nav)
        spawn_x = _number_value(nav_values, "x")
        spawn_y = _number_value(nav_values, "y")

        queued = _run_probe(host, _queue_spawn_probe(spawn_x, spawn_y))
        mutation_touched = True
        result["queued"] = queued
        queued_values = _values(queued)
        request_id = _positive_int(queued_values, "request_id")
        if not (
            queued_values.get("queued") == "true"
            and _int_value(queued_values, "content_id") == EXPECTED_CONTENT_ID
            and _positive_int(queued_values, "native_type_id") > 0
        ):
            raise RuntimeError(f"Lua AI boss spawn queue differs: {queued}")

        spawn = _poll_probe(
            host,
            _spawn_result_probe(request_id),
            lambda values: spawn_result_matches(values, request_id),
            timeout=timeout,
            description="registered Lua AI boss spawn",
        )
        result["spawn"] = spawn
        spawn_values = _values(spawn)
        actor_address = _positive_int(spawn_values, "actor_address")
        network_actor_id = _positive_int(spawn_values, "network_actor_id")
        object_type_id = _positive_int(spawn_values, "object_type_id")
        enemy_type = _int_value(spawn_values, "enemy_type")

        first_host = _poll_probe(
            host,
            _host_ai_probe(network_actor_id),
            lambda values: host_ai_matches(
                values,
                network_actor_id=network_actor_id,
                object_type_id=object_type_id,
                enemy_type=enemy_type,
                minimum_think_count=3,
            ),
            timeout=timeout,
            description="authority Lua AI controller",
        )
        result["first_host_ai"] = first_host
        first_host_values = _values(first_host)
        first_think_count = _int_value(first_host_values, "think_count")
        first_host_x = _number_value(first_host_values, "actor_x")
        first_host_y = _number_value(first_host_values, "actor_y")
        first_target_id = _positive_int(
            first_host_values,
            "target_participant_id",
        )

        first_client = _poll_probe(
            client,
            _client_snapshot_probe(network_actor_id),
            lambda values: client_snapshot_matches(
                values,
                network_actor_id=network_actor_id,
                object_type_id=object_type_id,
                enemy_type=enemy_type,
                target_participant_id=first_target_id,
            ),
            timeout=timeout,
            description="client Lua AI world snapshot",
        )
        result["first_client_snapshot"] = first_client
        first_client_values = _values(first_client)
        first_client_x = _number_value(first_client_values, "row_x")
        first_client_y = _number_value(first_client_values, "row_y")

        rejection = _run_probe(
            client,
            _client_mutation_rejection_probe(network_actor_id),
        )
        result["client_mutation_rejection"] = rejection
        rejection_values = _values(rejection)
        for name in (
            "target_rejected",
            "goal_rejected",
            "target_authority_error",
            "goal_authority_error",
        ):
            if rejection_values.get(name) != "true":
                raise RuntimeError(
                    f"Lua AI client mutation was not authority-rejected: {rejection}"
                )
        if _int_value(rejection_values, "ai_instance_count") != 0:
            raise RuntimeError(f"Lua AI client created a controller: {rejection}")

        second_host = _poll_probe(
            host,
            _host_ai_probe(network_actor_id),
            lambda values: host_ai_matches(
                values,
                network_actor_id=network_actor_id,
                object_type_id=object_type_id,
                enemy_type=enemy_type,
                minimum_think_count=first_think_count + 5,
                start_x=first_host_x,
                start_y=first_host_y,
            ),
            timeout=timeout,
            description="authority Lua AI movement",
        )
        result["second_host_ai"] = second_host
        second_host_values = _values(second_host)
        second_host_x = _number_value(second_host_values, "actor_x")
        second_host_y = _number_value(second_host_values, "actor_y")
        second_target_id = _positive_int(
            second_host_values,
            "target_participant_id",
        )

        segment = _run_probe(
            host,
            _movement_segment_probe(
                first_host_x,
                first_host_y,
                network_actor_id,
            ),
        )
        result["movement_segment"] = segment
        segment_values = _values(segment)
        if not (
            segment_values.get("query_ok") == "true"
            and segment_values.get("segment_clear") == "true"
        ):
            raise RuntimeError(
                f"Lua AI movement left the native clear lane: {segment}"
            )

        result["second_client_snapshot"] = _poll_probe(
            client,
            _client_snapshot_probe(network_actor_id),
            lambda values: client_snapshot_matches(
                values,
                network_actor_id=network_actor_id,
                object_type_id=object_type_id,
                enemy_type=enemy_type,
                target_participant_id=second_target_id,
                start_x=first_client_x,
                start_y=first_client_y,
            ),
            timeout=timeout,
            description="client Lua AI movement convergence",
        )

        kill = _run_probe(host, _kill_probe(actor_address))
        result["kill"] = kill
        kill_values = _values(kill)
        if not (
            kill_values.get("health_zeroed") == "true"
            and kill_values.get("death_triggered") == "true"
            and kill_values.get("exception_code") == "0"
        ):
            raise RuntimeError(f"Lua AI boss death trigger failed: {kill}")
        killed = True

        result["retired"] = [
            _poll_probe(
                peer,
                _retired_probe(network_actor_id),
                lambda values: (
                    values.get("instance_count") == "0"
                    and values.get("state_nil") == "true"
                ),
                timeout=timeout,
                description="Lua AI controller retirement",
            )
            for peer in peers
        ]
        result["request_id"] = request_id
        result["network_actor_id"] = network_actor_id
        result["ok"] = True
        return result
    finally:
        if mutation_touched and not killed:
            _best_effort_cleanup(
                host,
                request_id=request_id,
                actor_address=actor_address,
            )
        stop_game_processes(launched_process_ids)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--client",
        action="append",
        type=parse_client,
        help="Lua endpoint as NAME=PIPE; order must be host then client.",
    )
    parser.add_argument(
        "--launch-pair",
        action="store_true",
        help="Stage and launch an isolated local pair before verification.",
    )
    parser.add_argument(
        "--confirm-mutation",
        action="store_true",
        help="confirm that the verifier may spawn, steer, and kill one hostile",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    result: dict[str, Any] = {"ok": False}
    if not args.confirm_mutation:
        result["error"] = "refusing Lua AI mutations without --confirm-mutation"
        return_code = 2
    else:
        try:
            result = run(
                args.client or list(DEFAULT_CLIENTS),
                launch=args.launch_pair,
                timeout=max(1.0, args.timeout),
            )
            return_code = 0 if result.get("ok") else 1
        except Exception as error:  # noqa: BLE001 - preserve exact live evidence.
            result["error"] = str(error)
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
