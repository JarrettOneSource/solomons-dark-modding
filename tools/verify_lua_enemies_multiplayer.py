#!/usr/bin/env python3
"""Verify registered Lua enemy lifecycle across a local multiplayer pair."""

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
OUTPUT = ROOT / "runtime" / "lua_enemies_multiplayer_verification.json"
ACCEPTANCE_MOD_ID = "sample.lua.enemies_registry_lab"
EXPECTED_CONTENT_ID = 8726222830294414077
EXPECTED_NATIVE_TYPE_ID = 1001
EXPECTED_SPAWN_FLAGS = 11
EXPECTED_HP = 321.0
EXPECTED_SPEED = 2.75
EXPECTED_SCALE = 1.25


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
local registered = 0
for _, actor in ipairs(sd.world.list_actors() or {{}}) do
  if actor.tracked_enemy and not actor.dead and
      (tonumber(actor.hp) or 0) > 0.05 then
    live = live + 1
  end
end
local snapshot = sd.world.get_replicated_actors()
for _, actor in ipairs(snapshot and snapshot.actors or {{}}) do
  if tonumber(actor.content_id) == {EXPECTED_CONTENT_ID} then
    registered = registered + 1
  end
end
print("live_enemy_count=" .. tostring(live))
print("registered_snapshot_count=" .. tostring(registered))
"""

REGISTER_EVENTS = f"""
if _G.__lua_enemies_mp_registered then
  error("Lua enemy multiplayer probe is already registered")
end
local enemy = assert(
  sd.enemies.get({EXPECTED_CONTENT_ID}),
  "Lua enemy acceptance registration is unavailable")
assert(enemy.base == "skeleton")
assert(enemy.native_type_id == {EXPECTED_NATIVE_TYPE_ID})
assert(enemy.hp == 250 and enemy.speed == 2.5 and enemy.scale == 1.2)
assert(enemy.loot == "gold")
_G.__lua_enemies_mp_registered = true
_G.__lua_enemies_mp = {{
  spawn_count = 0,
  death_count = 0,
}}
sd.events.on("enemy.spawned", function(event)
  if tonumber(event.content_id) ~= {EXPECTED_CONTENT_ID} then return end
  local record = _G.__lua_enemies_mp
  record.spawn_count = record.spawn_count + 1
  record.spawn_content_id = event.content_id
  record.spawn_type = event.enemy_type
  record.spawn_x = event.x
  record.spawn_y = event.y
end)
sd.events.on("enemy.death", function(event)
  if tonumber(event.content_id) ~= {EXPECTED_CONTENT_ID} then return end
  local record = _G.__lua_enemies_mp
  record.death_count = record.death_count + 1
  record.death_content_id = event.content_id
  record.death_type = event.enemy_type
  record.death_x = event.x
  record.death_y = event.y
end)
print("registered=true")
print("authority=" .. tostring(sd.state.is_authority()))
print("content_id=" .. tostring(enemy.id))
print("native_type_id=" .. tostring(enemy.native_type_id))
"""

EVENT_STATUS = """
local record = _G.__lua_enemies_mp or {}
print("spawn_count=" .. tostring(record.spawn_count or -1))
print("spawn_content_id=" .. tostring(record.spawn_content_id or 0))
print("spawn_type=" .. tostring(record.spawn_type or 0))
print("spawn_x=" .. tostring(record.spawn_x or 0))
print("spawn_y=" .. tostring(record.spawn_y or 0))
print("death_count=" .. tostring(record.death_count or -1))
print("death_content_id=" .. tostring(record.death_content_id or 0))
print("death_type=" .. tostring(record.death_type or 0))
print("death_x=" .. tostring(record.death_x or 0))
print("death_y=" .. tostring(record.death_y or 0))
"""

CLIENT_REJECTION = f"""
local ok, error_message = pcall(sd.enemies.spawn, {EXPECTED_CONTENT_ID}, {{
  x = 100,
  y = 100,
}})
print("rejected=" .. tostring(not ok))
print("authority_error=" .. tostring(
  type(error_message) == "string" and
  string.find(error_message, "authority", 1, true) ~= nil))
"""

QUEUE_SPAWN = f"""
assert(sd.state.is_authority(), "enemy spawn probe is not the authority")
local player = assert(sd.player.get_state(), "player state unavailable")
assert(
  tonumber(player.actor_address) and tonumber(player.actor_address) > 0,
  "enter an active combat arena before verification"
)
local x = player.x + 200
local y = player.y
local queued = sd.enemies.spawn({EXPECTED_CONTENT_ID}, {{
  x = x,
  y = y,
  hp = {EXPECTED_HP},
  speed = {EXPECTED_SPEED},
  scale = {EXPECTED_SCALE},
  loot = "none",
}})
print("queued=" .. tostring(queued.queued))
print("request_id=" .. tostring(queued.request_id))
print("content_id=" .. tostring(queued.content_id))
print("native_type_id=" .. tostring(queued.native_type_id))
print("requested_x=" .. tostring(x))
print("requested_y=" .. tostring(y))
"""

LOOT_STATUS = """
local snapshot = sd.world.get_replicated_loot()
local active = 0
for _, drop in ipairs(snapshot and snapshot.drops or {}) do
  if drop.active then active = active + 1 end
end
print("available=" .. tostring(snapshot ~= nil))
print("drop_count=" .. tostring(snapshot and snapshot.drop_count or -1))
print("drop_total_count=" .. tostring(snapshot and snapshot.drop_total_count or -1))
print("active_drop_count=" .. tostring(active))
"""


def _spawn_result_probe(request_id: int) -> str:
    return f"""
local result = sd.gameplay.get_last_manual_run_enemy_spawn({request_id})
print("complete=" .. tostring(result ~= nil))
if result == nil then return end
local network_id = tonumber(result.network_actor_id) or 0
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
print("network_actor_id=" .. tostring(network_id))
print("requested_x=" .. tostring(result.requested_x))
print("requested_y=" .. tostring(result.requested_y))
print("x=" .. tostring(result.x))
print("y=" .. tostring(result.y))
print("wrote_x=" .. tostring(result.wrote_x))
print("wrote_y=" .. tostring(result.wrote_y))
print("rebind_ok=" .. tostring(result.rebind_ok))
print("error=" .. tostring(result.error))
print("actor_found=" .. tostring(actor ~= nil))
print("actor_tracked=" .. tostring(actor ~= nil and actor.tracked_enemy))
print("actor_dead=" .. tostring(actor ~= nil and actor.dead))
print("actor_object_type_id=" .. tostring(actor and actor.object_type_id or 0))
print("actor_hp=" .. tostring(actor and actor.hp or 0))
print("actor_max_hp=" .. tostring(actor and actor.max_hp or 0))
"""


def _materialized_probe(network_actor_id: int) -> str:
    return f"""
local expected_network_id = {network_actor_id}
local snapshot = sd.world.get_replicated_actors()
local row = nil
local content_count = 0
for _, candidate in ipairs(snapshot and snapshot.actors or {{}}) do
  if tonumber(candidate.content_id) == {EXPECTED_CONTENT_ID} then
    content_count = content_count + 1
  end
  if tonumber(candidate.network_actor_id) == expected_network_id then
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
print("snapshot_available=" .. tostring(snapshot ~= nil))
print("snapshot_authority_id=" .. tostring(
  snapshot and snapshot.authority_participant_id or 0))
print("content_count=" .. tostring(content_count))
print("row_found=" .. tostring(row ~= nil))
print("network_actor_id=" .. tostring(row and row.network_actor_id or 0))
print("content_id=" .. tostring(row and row.content_id or 0))
print("object_type_id=" .. tostring(row and row.object_type_id or 0))
print("enemy_type=" .. tostring(row and row.enemy_type or -1))
print("spawn_flags=" .. tostring(row and row.content_spawn_flags or 0))
print("spawn_hp=" .. tostring(row and row.content_spawn_hp or 0))
print("spawn_speed=" .. tostring(row and row.content_spawn_speed or 0))
print("spawn_attack_speed=" .. tostring(
  row and row.content_spawn_attack_speed or 0))
print("spawn_scale=" .. tostring(row and row.content_spawn_scale or 0))
print("row_hp=" .. tostring(row and row.hp or 0))
print("row_max_hp=" .. tostring(row and row.max_hp or 0))
print("row_dead=" .. tostring(row ~= nil and row.dead))
print("row_tracked=" .. tostring(row ~= nil and row.tracked_enemy))
print("row_lifecycle_owned=" .. tostring(row ~= nil and row.lifecycle_owned))
print("raw_addresses_absent=" .. tostring(
  row ~= nil and row.actor_address == nil and row.config_address == nil))
print("binding_count=" .. tostring(binding_count))
print("binding_address=" .. tostring(binding and binding.local_actor_address or 0))
print("binding_matched=" .. tostring(binding ~= nil and binding.matched))
print("binding_parked=" .. tostring(binding ~= nil and binding.parked))
print("binding_removed=" .. tostring(binding ~= nil and binding.removed))
print("local_found=" .. tostring(actor ~= nil))
print("local_address=" .. tostring(actor and actor.actor_address or 0))
print("local_object_type_id=" .. tostring(actor and actor.object_type_id or 0))
print("local_enemy_type=" .. tostring(actor and actor.enemy_type or -1))
print("local_hp=" .. tostring(actor and actor.hp or 0))
print("local_max_hp=" .. tostring(actor and actor.max_hp or 0))
print("local_dead=" .. tostring(actor ~= nil and actor.dead))
print("local_tracked=" .. tostring(actor ~= nil and actor.tracked_enemy))
print("position_error=" .. tostring(math.sqrt(dx * dx + dy * dy)))
"""


def _kill_probe(actor_address: int) -> str:
    return f"""
assert(sd.state.is_authority(), "enemy death probe is not the authority")
local wrote = sd.gameplay.set_run_enemy_health(
  {actor_address}, 0, {EXPECTED_HP})
local triggered, exception_code = sd.world.trigger_enemy_death({actor_address})
print("health_zeroed=" .. tostring(wrote))
print("death_triggered=" .. tostring(triggered))
print("exception_code=" .. tostring(exception_code or 0))
"""


def _death_snapshot_probe(network_actor_id: int) -> str:
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
local record = _G.__lua_enemies_mp or {{}}
print("snapshot_available=" .. tostring(snapshot ~= nil))
print("snapshot_authority_id=" .. tostring(
  snapshot and snapshot.authority_participant_id or 0))
print("matching_rows=" .. tostring(matching))
print("network_actor_id=" .. tostring(row and row.network_actor_id or 0))
print("dead=" .. tostring(row ~= nil and row.dead))
print("content_id=" .. tostring(row and row.content_id or 0))
print("object_type_id=" .. tostring(row and row.object_type_id or 0))
print("enemy_type=" .. tostring(row and row.enemy_type or -1))
print("spawn_flags=" .. tostring(row and row.content_spawn_flags or 0))
print("spawn_hp=" .. tostring(row and row.content_spawn_hp or 0))
print("spawn_speed=" .. tostring(row and row.content_spawn_speed or 0))
print("spawn_attack_speed=" .. tostring(
  row and row.content_spawn_attack_speed or 0))
print("spawn_scale=" .. tostring(row and row.content_spawn_scale or 0))
print("spawn_count=" .. tostring(record.spawn_count or -1))
print("spawn_content_id=" .. tostring(record.spawn_content_id or 0))
print("death_count=" .. tostring(record.death_count or -1))
print("death_content_id=" .. tostring(record.death_content_id or 0))
print("death_type=" .. tostring(record.death_type or 0))
"""


def _failed_exec(result: dict[str, Any]) -> str | None:
    if result.get("returncode") == 0:
        return None
    return str(
        result.get("stderr") or result.get("stdout") or "Lua exec failed"
    ).strip()


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
            and values.get("wrote_x") == "true"
            and values.get("wrote_y") == "true"
            and values.get("rebind_ok") == "true"
            and values.get("error") in ("", "nil")
            and values.get("actor_found") == "true"
            and values.get("actor_tracked") == "true"
            and values.get("actor_dead") == "false"
            and _int_value(values, "actor_object_type_id")
            == EXPECTED_NATIVE_TYPE_ID
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


def materialized_enemy_matches(
    values: dict[str, str],
    network_actor_id: int,
    enemy_type: int,
) -> bool:
    try:
        return (
            values.get("authority") == "false"
            and values.get("snapshot_available") == "true"
            and _int_value(values, "snapshot_authority_id") == HOST_ID
            and _int_value(values, "content_count") == 1
            and values.get("row_found") == "true"
            and _int_value(values, "network_actor_id") == network_actor_id
            and _int_value(values, "content_id") == EXPECTED_CONTENT_ID
            and _int_value(values, "object_type_id")
            == EXPECTED_NATIVE_TYPE_ID
            and _int_value(values, "enemy_type") == enemy_type
            and _int_value(values, "spawn_flags") == EXPECTED_SPAWN_FLAGS
            and _near(values, "spawn_hp", EXPECTED_HP, 0.001)
            and _near(values, "spawn_speed", EXPECTED_SPEED, 0.001)
            and _near(values, "spawn_attack_speed", 0.0, 0.001)
            and _near(values, "spawn_scale", EXPECTED_SCALE, 0.001)
            and _near(values, "row_max_hp", EXPECTED_HP, 0.05)
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
            and _int_value(values, "local_object_type_id")
            == EXPECTED_NATIVE_TYPE_ID
            and _int_value(values, "local_enemy_type") == enemy_type
            and _near(values, "local_max_hp", EXPECTED_HP, 0.05)
            and values.get("local_dead") == "false"
            and values.get("local_tracked") == "true"
            and _number_value(values, "position_error") <= 12.0
        )
    except RuntimeError:
        return False


def event_status_matches(
    values: dict[str, str],
    *,
    spawn_count: int,
    death_count: int,
    enemy_type: int | None,
) -> bool:
    try:
        return (
            _int_value(values, "spawn_count") == spawn_count
            and _int_value(values, "death_count") == death_count
            and (
                spawn_count == 0
                or (
                    enemy_type is not None
                    and _int_value(values, "spawn_content_id")
                    == EXPECTED_CONTENT_ID
                    and _int_value(values, "spawn_type") == enemy_type
                    and math.isfinite(_number_value(values, "spawn_x"))
                    and math.isfinite(_number_value(values, "spawn_y"))
                )
            )
            and (
                death_count == 0
                or (
                    enemy_type is not None
                    and _int_value(values, "death_content_id")
                    == EXPECTED_CONTENT_ID
                    and _int_value(values, "death_type") == enemy_type
                    and math.isfinite(_number_value(values, "death_x"))
                    and math.isfinite(_number_value(values, "death_y"))
                )
            )
        )
    except RuntimeError:
        return False


def death_snapshot_matches(
    values: dict[str, str],
    network_actor_id: int,
    enemy_type: int,
) -> bool:
    try:
        return (
            values.get("snapshot_available") == "true"
            and _int_value(values, "snapshot_authority_id") == HOST_ID
            and _int_value(values, "matching_rows") == 1
            and _int_value(values, "network_actor_id") == network_actor_id
            and values.get("dead") == "true"
            and _int_value(values, "content_id") == EXPECTED_CONTENT_ID
            and _int_value(values, "object_type_id")
            == EXPECTED_NATIVE_TYPE_ID
            and _int_value(values, "enemy_type") == enemy_type
            and _int_value(values, "spawn_flags") == EXPECTED_SPAWN_FLAGS
            and _near(values, "spawn_hp", EXPECTED_HP, 0.001)
            and _near(values, "spawn_speed", EXPECTED_SPEED, 0.001)
            and _near(values, "spawn_attack_speed", 0.0, 0.001)
            and _near(values, "spawn_scale", EXPECTED_SCALE, 0.001)
            and _int_value(values, "spawn_count") == 1
            and _int_value(values, "spawn_content_id") == EXPECTED_CONTENT_ID
            and _int_value(values, "death_count") == 1
            and _int_value(values, "death_content_id") == EXPECTED_CONTENT_ID
            and _int_value(values, "death_type") == enemy_type
        )
    except RuntimeError:
        return False


def _run_probe(client: tuple[str, str], code: str) -> dict[str, Any]:
    result = run_lua_client(client[0], client[1], code, timeout=12.0)
    failure = _failed_exec(result)
    if failure:
        raise RuntimeError(failure)
    return result


def _values(result: dict[str, Any]) -> dict[str, str]:
    values = result.get("values", {})
    if not isinstance(values, dict):
        raise RuntimeError(f"Lua probe returned invalid values: {result}")
    return values


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
                and values.get("registered_snapshot_count") == "0"
            ),
            timeout=timeout,
            description="empty manual-spawner scene",
        )
        for peer in clients
    ]
    return result


def _register_event_probes(
    clients: list[tuple[str, str]],
) -> list[dict[str, Any]]:
    registrations = [_run_probe(peer, REGISTER_EVENTS) for peer in clients]
    expected_roles = ("true", "false")
    for registration, authority in zip(
        registrations,
        expected_roles,
        strict=True,
    ):
        values = _values(registration)
        if not (
            values.get("registered") == "true"
            and values.get("authority") == authority
            and _int_value(values, "content_id") == EXPECTED_CONTENT_ID
            and _int_value(values, "native_type_id")
            == EXPECTED_NATIVE_TYPE_ID
        ):
            raise RuntimeError(
                f"Lua enemy event registration differs: {registration}"
            )
    return registrations


def _poll_events(
    client: tuple[str, str],
    *,
    spawn_count: int,
    death_count: int,
    enemy_type: int | None,
    timeout: float,
) -> dict[str, Any]:
    return _poll_probe(
        client,
        EVENT_STATUS,
        lambda values: event_status_matches(
            values,
            spawn_count=spawn_count,
            death_count=death_count,
            enemy_type=enemy_type,
        ),
        timeout=timeout,
        description=(
            f"Lua enemy events spawn_count={spawn_count} death_count={death_count}"
        ),
    )


def _poll_empty_loot_stable(
    client: tuple[str, str],
    *,
    timeout: float,
    stable_seconds: float = 0.75,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    stable_since: float | None = None
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = run_lua_client(client[0], client[1], LOOT_STATUS, timeout=12.0)
        values = last.get("values", {})
        empty = (
            _failed_exec(last) is None
            and isinstance(values, dict)
            and values.get("available") == "true"
            and values.get("drop_count") == "0"
            and values.get("drop_total_count") == "0"
            and values.get("active_drop_count") == "0"
        )
        now = time.monotonic()
        if empty:
            if stable_since is None:
                stable_since = now
            elif now - stable_since >= stable_seconds:
                return last
        else:
            stable_since = None
        time.sleep(0.1)
    raise RuntimeError(
        f"replicated loot did not remain empty for {client[0]}: {last}"
    )


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
    try:
        if launch:
            result["pair"] = launch_pair(
                god_mode=True,
                tile_windows=False,
                kill_existing=False,
                exact_mod_id=ACCEPTANCE_MOD_ID,
            )
            launched_process_ids.extend(game_process_ids(result["pair"]))
            if len(set(launched_process_ids)) != 2:
                raise RuntimeError(
                    "local pair did not report two exact process IDs: "
                    f"{launched_process_ids}"
                )
            disable_bots()
            wait_for_remote(HOST_PIPE, CLIENT_ID, CLIENT_NAME, "hub")
            wait_for_remote(CLIENT_PIPE, HOST_ID, HOST_NAME, "hub")
            result["run"] = start_host_testrun_and_wait_for_clients(
                timeout=timeout,
            )
            wait_for_remote(HOST_PIPE, CLIENT_ID, CLIENT_NAME, "testrun")
            wait_for_remote(CLIENT_PIPE, HOST_ID, HOST_NAME, "testrun")

        result["combat_bootstrap"] = _bootstrap_manual_spawners(peers, timeout)
        result["registrations"] = _register_event_probes(peers)
        result["initial_events"] = [
            _poll_events(
                peer,
                spawn_count=0,
                death_count=0,
                enemy_type=None,
                timeout=timeout,
            )
            for peer in peers
        ]
        result["initial_loot"] = _poll_empty_loot_stable(
            client,
            timeout=timeout,
        )

        rejection = _run_probe(client, CLIENT_REJECTION)
        result["client_rejection"] = rejection
        rejection_values = _values(rejection)
        if not (
            rejection_values.get("rejected") == "true"
            and rejection_values.get("authority_error") == "true"
        ):
            raise RuntimeError(
                f"Lua enemy client spawn was not authority-rejected: {rejection}"
            )
        result["events_after_rejection"] = [
            _poll_events(
                peer,
                spawn_count=0,
                death_count=0,
                enemy_type=None,
                timeout=timeout,
            )
            for peer in peers
        ]

        queued = _run_probe(host, QUEUE_SPAWN)
        result["queued"] = queued
        queued_values = _values(queued)
        if not (
            queued_values.get("queued") == "true"
            and _int_value(queued_values, "content_id") == EXPECTED_CONTENT_ID
            and _int_value(queued_values, "native_type_id")
            == EXPECTED_NATIVE_TYPE_ID
        ):
            raise RuntimeError(f"Lua enemy spawn queue contract differs: {queued}")
        request_id = _positive_int(queued_values, "request_id")

        spawn_result = _poll_probe(
            host,
            _spawn_result_probe(request_id),
            lambda values: spawn_result_matches(values, request_id),
            timeout=timeout,
            description="authority registered enemy spawn",
        )
        result["spawn_result"] = spawn_result
        spawn_values = _values(spawn_result)
        network_actor_id = _positive_int(spawn_values, "network_actor_id")
        actor_address = _positive_int(spawn_values, "actor_address")
        enemy_type = _int_value(spawn_values, "enemy_type")

        result["host_spawn_event"] = _poll_events(
            host,
            spawn_count=1,
            death_count=0,
            enemy_type=enemy_type,
            timeout=timeout,
        )
        result["client_materialization"] = _poll_probe(
            client,
            _materialized_probe(network_actor_id),
            lambda values: materialized_enemy_matches(
                values,
                network_actor_id,
                enemy_type,
            ),
            timeout=timeout,
            description="client registered enemy materialization",
        )
        result["client_spawn_event"] = _poll_events(
            client,
            spawn_count=1,
            death_count=0,
            enemy_type=enemy_type,
            timeout=timeout,
        )

        killed = _run_probe(host, _kill_probe(actor_address))
        result["kill"] = killed
        killed_values = _values(killed)
        if not (
            killed_values.get("health_zeroed") == "true"
            and killed_values.get("death_triggered") == "true"
            and killed_values.get("exception_code") == "0"
        ):
            raise RuntimeError(f"Lua enemy native death trigger failed: {killed}")

        result["host_death_event"] = _poll_events(
            host,
            spawn_count=1,
            death_count=1,
            enemy_type=enemy_type,
            timeout=timeout,
        )
        result["client_death_tombstone"] = _poll_probe(
            client,
            _death_snapshot_probe(network_actor_id),
            lambda values: death_snapshot_matches(
                values,
                network_actor_id,
                enemy_type,
            ),
            timeout=timeout,
            description="client registered enemy death tombstone",
        )
        result["client_death_event"] = _poll_events(
            client,
            spawn_count=1,
            death_count=1,
            enemy_type=enemy_type,
            timeout=timeout,
        )
        result["loot_none"] = _poll_empty_loot_stable(
            client,
            timeout=timeout,
        )

        result["request_id"] = request_id
        result["network_actor_id"] = network_actor_id
        result["ok"] = True
        return result
    finally:
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
        help="confirm that the verifier may spawn and kill one hostile enemy",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    result: dict[str, Any] = {"ok": False}
    if not args.confirm_mutation:
        result["error"] = (
            "refusing enemy lifecycle mutations without --confirm-mutation"
        )
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
