#!/usr/bin/env python3
"""Live verification for ordered wave-spawn rewrites and cancellation."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from verify_local_multiplayer_sync import VerifyFailure, lua, parse_key_values


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "runtime" / "lua_wave_spawn_filter_verification.json"
DEFAULT_PIPE = "SolomonDarkModLoader_LuaExec"

REGISTER = r'''
if __lua_wave_filter_acceptance_registered == true then
  error("wave filter acceptance is already registered; restart the disposable process")
end

local scene = sd.world.get_scene and sd.world.get_scene() or nil
if type(scene) ~= "table" or tostring(scene.name or scene.kind or "") ~= "testrun" then
  error("wave filter acceptance requires a settled testrun")
end

local live_enemies = 0
for _, actor in ipairs(sd.world.list_actors and sd.world.list_actors() or {}) do
  if actor.tracked_enemy and not actor.dead and (tonumber(actor.max_hp) or 0) > 0 then
    live_enemies = live_enemies + 1
  end
end
if live_enemies ~= 0 then
  error("wave filter acceptance requires a clean pre-wave run")
end

__lua_wave_filter_acceptance_registered = true
__lua_wave_filter_first_handler_count = 0
__lua_wave_filter_second_handler_count = 0
__lua_wave_filter_spawned_count = 0
__lua_wave_filter_original_count = -1
__lua_wave_filter_expected_count = -1
__lua_wave_filter_original_spawn_delay = -1
__lua_wave_filter_original_wave_delay = -1
__lua_wave_filter_second_input_count = -1
__lua_wave_filter_second_input_spawn_delay = -1
__lua_wave_filter_second_input_wave_delay = -1
__lua_wave_filter_second_input_randomize = true
__lua_wave_filter_second_action_count = -1
__lua_wave_filter_first_spawner = 0
__lua_wave_filter_first_record = 0

sd.events.filter("wave.spawning", function(event)
  __lua_wave_filter_first_handler_count =
    __lua_wave_filter_first_handler_count + 1
  if __lua_wave_filter_first_handler_count == 1 then
    __lua_wave_filter_original_count = tonumber(event.count) or -1
    __lua_wave_filter_expected_count = __lua_wave_filter_original_count + 2
    __lua_wave_filter_original_spawn_delay =
      tonumber(event.spawn_delay) or -1
    __lua_wave_filter_original_wave_delay = tonumber(event.wave_delay) or -1
    __lua_wave_filter_first_spawner = tonumber(event.spawner_address) or 0
    __lua_wave_filter_first_record =
      tonumber(event.action_record_address) or 0
    return {
      count = __lua_wave_filter_expected_count,
      spawn_delay = 1,
      wave_delay = 1,
      randomize_spawn_delay = false,
    }
  end
  return nil
end)

sd.events.filter("wave.spawning", function(event)
  __lua_wave_filter_second_handler_count =
    __lua_wave_filter_second_handler_count + 1
  if __lua_wave_filter_second_handler_count == 1 then
    __lua_wave_filter_second_input_count = tonumber(event.count) or -1
    __lua_wave_filter_second_input_spawn_delay =
      tonumber(event.spawn_delay) or -1
    __lua_wave_filter_second_input_wave_delay =
      tonumber(event.wave_delay) or -1
    __lua_wave_filter_second_input_randomize =
      event.randomize_spawn_delay == true
    return nil
  end
  if __lua_wave_filter_second_handler_count == 2 then
    __lua_wave_filter_second_action_count = tonumber(event.count) or -1
  end
  return false
end)

sd.events.on("enemy.spawned", function()
  __lua_wave_filter_spawned_count = __lua_wave_filter_spawned_count + 1
end)

print("registered=true")
print("capability=" .. tostring(
  sd.runtime.has_capability("events.filters.wave_spawn")))
'''

STATUS = r'''
local live_enemy_count = 0
local live_enemy_addresses = {}
for _, actor in ipairs(sd.world.list_actors and sd.world.list_actors() or {}) do
  local address = tonumber(actor.actor_address) or 0
  if actor.tracked_enemy and not actor.dead and (tonumber(actor.max_hp) or 0) > 0 and
      (tonumber(actor.hp) or 0) > 0 then
    live_enemy_count = live_enemy_count + 1
    live_enemy_addresses[#live_enemy_addresses + 1] = tostring(address)
  end
end
table.sort(live_enemy_addresses)

print("first_handler_count=" .. tostring(
  __lua_wave_filter_first_handler_count or 0))
print("second_handler_count=" .. tostring(
  __lua_wave_filter_second_handler_count or 0))
print("spawned_count=" .. tostring(__lua_wave_filter_spawned_count or 0))
print("original_count=" .. tostring(__lua_wave_filter_original_count or -1))
print("expected_count=" .. tostring(__lua_wave_filter_expected_count or -1))
print("original_spawn_delay=" .. tostring(
  __lua_wave_filter_original_spawn_delay or -1))
print("original_wave_delay=" .. tostring(
  __lua_wave_filter_original_wave_delay or -1))
print("second_input_count=" .. tostring(
  __lua_wave_filter_second_input_count or -1))
print("second_input_spawn_delay=" .. tostring(
  __lua_wave_filter_second_input_spawn_delay or -1))
print("second_input_wave_delay=" .. tostring(
  __lua_wave_filter_second_input_wave_delay or -1))
print("second_input_randomize=" .. tostring(
  __lua_wave_filter_second_input_randomize == true))
print("second_action_count=" .. tostring(
  __lua_wave_filter_second_action_count or -1))
print("first_spawner=" .. tostring(__lua_wave_filter_first_spawner or 0))
print("first_record=" .. tostring(__lua_wave_filter_first_record or 0))
print("live_enemy_count=" .. tostring(live_enemy_count))
print("live_enemy_addresses=" .. table.concat(live_enemy_addresses, ","))
'''

QUEUE_KILL = r'''
local target = nil
for _, actor in ipairs(sd.world.list_actors and sd.world.list_actors() or {}) do
  if actor.tracked_enemy and not actor.dead and (tonumber(actor.max_hp) or 0) > 0 and
      (tonumber(actor.hp) or 0) > 0 then
    if target == nil or (tonumber(actor.actor_address) or 0) <
        (tonumber(target.actor_address) or 0) then
      target = actor
    end
  end
end
if target == nil then
  print("queued=false")
  print("error=no_live_enemy")
  return
end
local address = tonumber(target.actor_address) or 0
local max_hp = math.max(tonumber(target.max_hp) or 1, 1)
local original_config = tonumber(sd.debug.read_ptr(address + 0x1D0)) or 0
local config = original_config
if config == 0 then
  local operator_new = assert(
    sd.debug.resolve_game_address(0x74784D),
    "retail operator new could not be resolved")
  config = assert(
    sd.debug.call_cdecl_u32_ret_u32(operator_new, 0x200),
    "wave config fixture allocation failed")
  for offset = 0, 0x1FC, 4 do
    assert(sd.debug.write_u32(config + offset, 0))
  end
  assert(sd.debug.write_i32(
    config + 0x54,
    tonumber(target.object_type_id) or 0))
  assert(sd.debug.write_ptr(address + 0x1D0, config))
end
local wrote = sd.gameplay.set_run_enemy_health(address, 0, max_hp)
local queued, err, serial = sd.debug.queue_native_enemy_death_probe(
  address, config, original_config)
print("queued=" .. tostring(queued))
print("error=" .. tostring(err or ""))
print("serial=" .. tostring(serial or 0))
print("write_health=" .. tostring(wrote))
print("actor_address=" .. tostring(address))
print("config_address=" .. tostring(config))
print("original_config_address=" .. tostring(original_config))
'''

DEATH_RESULT = r'''
local completed, success, seh, restored, err =
  sd.debug.get_native_enemy_death_probe_result(%d)
print("completed=" .. tostring(completed))
print("success=" .. tostring(success))
print("seh=" .. tostring(seh or 0))
print("config_restored=" .. tostring(restored))
print("error=" .. tostring(err or ""))
'''


def _status(pipe_name: str) -> dict[str, str]:
    return parse_key_values(lua(pipe_name, STATUS, timeout=8.0))


def _as_int(values: dict[str, str], key: str) -> int:
    try:
        return int(values.get(key, ""))
    except ValueError as exc:
        raise VerifyFailure(f"invalid integer {key}: {values}") from exc


def _wait_for(
    pipe_name: str,
    predicate: Any,
    timeout: float,
    description: str,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = _status(pipe_name)
        if predicate(last):
            return last
        time.sleep(0.1)
    raise VerifyFailure(f"timed out waiting for {description}: {last}")


def _kill_one(pipe_name: str) -> dict[str, str]:
    queued = parse_key_values(lua(pipe_name, QUEUE_KILL, timeout=8.0))
    serial = _as_int(queued, "serial")
    if (
        queued.get("queued") != "true"
        or queued.get("write_health") != "true"
        or serial == 0
    ):
        raise VerifyFailure(f"native enemy death failed to queue: {queued}")

    deadline = time.monotonic() + 8.0
    result: dict[str, str] = {}
    while time.monotonic() < deadline:
        result = parse_key_values(
            lua(pipe_name, DEATH_RESULT % serial, timeout=8.0)
        )
        if result.get("completed") == "true":
            break
        time.sleep(0.02)
    if (
        result.get("completed") != "true"
        or result.get("success") != "true"
        or result.get("seh") != "0"
        or result.get("config_restored") != "true"
    ):
        raise VerifyFailure(
            f"deferred native enemy death failed: queue={queued} result={result}"
        )
    return {**queued, **result}


def run(pipe_name: str, timeout: float) -> dict[str, Any]:
    registration = parse_key_values(lua(pipe_name, REGISTER, timeout=12.0))
    if registration.get("registered") != "true" or registration.get(
        "capability"
    ) != "true":
        raise VerifyFailure(f"wave filters failed to register: {registration}")

    start = parse_key_values(
        lua(
            pipe_name,
            'print("started=" .. tostring(sd.gameplay.start_waves()))',
            timeout=8.0,
        )
    )
    if start.get("started") != "true":
        raise VerifyFailure(f"stock waves failed to start: {start}")

    first = _wait_for(
        pipe_name,
        lambda row: (
            _as_int(row, "first_handler_count") >= 1
            and _as_int(row, "second_handler_count") >= 1
            and _as_int(row, "expected_count") > 0
            and _as_int(row, "spawned_count")
            == _as_int(row, "expected_count")
            and _as_int(row, "live_enemy_count")
            == _as_int(row, "expected_count")
        ),
        timeout,
        "the rewritten first stock spawn action",
    )
    if _as_int(first, "original_count") <= 0:
        raise VerifyFailure(
            "the stock wave action exposed no spawn budget: " f"{first}"
        )
    if _as_int(first, "expected_count") != _as_int(first, "original_count") + 2:
        raise VerifyFailure(f"unexpected rewritten spawn count: {first}")
    if (
        _as_int(first, "second_input_count")
        != _as_int(first, "expected_count")
        or _as_int(first, "second_input_spawn_delay") != 1
        or _as_int(first, "second_input_wave_delay") != 1
        or first.get("second_input_randomize") != "false"
    ):
        raise VerifyFailure(
            "the second handler did not observe the first handler rewrite: "
            f"{first}"
        )
    if _as_int(first, "first_spawner") == 0 or _as_int(first, "first_record") == 0:
        raise VerifyFailure(f"native spawner identity was absent: {first}")

    deaths: list[dict[str, str]] = []
    for _ in range(_as_int(first, "expected_count")):
        deaths.append(_kill_one(pipe_name))
        _wait_for(
            pipe_name,
            lambda row, remaining=(
                _as_int(first, "expected_count") - len(deaths)
            ): _as_int(row, "live_enemy_count") <= remaining,
            timeout,
            "the deferred enemy death",
        )

    canceled = _wait_for(
        pipe_name,
        lambda row: (
            _as_int(row, "second_handler_count") >= 2
            and _as_int(row, "second_action_count") > 0
            and _as_int(row, "live_enemy_count") == 0
        ),
        timeout,
        "the canceled second stock spawn action",
    )
    spawned_before_settle = _as_int(canceled, "spawned_count")
    time.sleep(1.0)
    settled = _status(pipe_name)
    if (
        spawned_before_settle != _as_int(first, "expected_count")
        or _as_int(settled, "spawned_count") != _as_int(first, "expected_count")
        or _as_int(settled, "live_enemy_count") != 0
    ):
        raise VerifyFailure(
            "canceled wave action produced an enemy: "
            f"before={canceled} after={settled}"
        )

    return {
        "ok": True,
        "pipe": pipe_name,
        "registration": registration,
        "start": start,
        "first_action": first,
        "deaths": deaths,
        "canceled_action": canceled,
        "settled": settled,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pipe", default=DEFAULT_PIPE)
    parser.add_argument("--timeout", type=float, default=25.0)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    result: dict[str, Any]
    try:
        result = run(args.pipe, args.timeout)
    except Exception as exc:
        result = {"ok": False, "pipe": args.pipe, "error": str(exc)}

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
