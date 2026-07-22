#!/usr/bin/env python3
"""Verify ordered drop-roll rewrites, native forcing, restore, and cancellation."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from verify_local_multiplayer_sync import VerifyFailure, lua, parse_key_values


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "runtime" / "lua_drop_filter_verification.json"
DEFAULT_PIPE = "SolomonDarkModLoader_LuaExec"

REGISTER = r"""
if __lua_drop_filter_acceptance_registered == true then
  error("drop filter acceptance is already registered; restart the disposable process")
end

local scene = sd.world.get_scene and sd.world.get_scene() or nil
if type(scene) ~= "table" or tostring(scene.name or scene.kind or "") ~= "testrun" then
  error("drop filter acceptance requires a settled testrun before registration")
end

local live_enemies = 0
local reward_actors = 0
for _, actor in ipairs(sd.world.list_actors and sd.world.list_actors() or {}) do
  if actor.tracked_enemy and not actor.dead and (tonumber(actor.max_hp) or 0) > 0 then
    live_enemies = live_enemies + 1
  end
  local object_type = tonumber(actor.object_type_id) or 0
  if object_type == 2011 or object_type == 2012 or object_type == 2013 or object_type == 2038 then
    reward_actors = reward_actors + 1
  end
end
if live_enemies ~= 0 or reward_actors ~= 0 then
  error("drop filter acceptance requires a clean pre-wave run")
end

local function selector_signature(event)
  local values = {}
  for index = 1, 6 do
    values[index] = tostring(event.selectors[index])
  end
  return table.concat(values, ",")
end

__lua_drop_filter_acceptance_registered = true
__lua_drop_filter_first_count = 0
__lua_drop_filter_second_count = 0
__lua_drop_filter_post_count = 0
__lua_drop_filter_first_input = ""
__lua_drop_filter_second_input_gold = -1
__lua_drop_filter_second_kind = ""
__lua_drop_filter_first_config = 0
__lua_drop_filter_first_arena = 0
__lua_drop_filter_first_mask = 0

sd.events.filter("drop.rolling", function(event)
  __lua_drop_filter_first_count = __lua_drop_filter_first_count + 1
  if __lua_drop_filter_first_count == 1 then
    __lua_drop_filter_first_input = selector_signature(event)
    __lua_drop_filter_first_config = tonumber(event.config_address) or 0
    __lua_drop_filter_first_arena = tonumber(event.arena_address) or 0
    __lua_drop_filter_first_mask = tonumber(event.arena_disable_mask) or 0
    return {gold_selector = 3}
  end
  return nil
end)

sd.events.filter("drop.rolling", function(event)
  __lua_drop_filter_second_count = __lua_drop_filter_second_count + 1
  if __lua_drop_filter_second_count == 1 then
    __lua_drop_filter_second_input_gold = tonumber(event.gold_selector) or -1
    __lua_drop_filter_second_kind = tostring(event.kind)
    return {kind = "gold"}
  end
  return false
end)

sd.events.on("drop.spawned", function(event)
  __lua_drop_filter_post_count = __lua_drop_filter_post_count + 1
end)

print("registered=true")
print("capability=" .. tostring(sd.runtime.has_capability("events.filters.drop_roll")))
"""

STATUS = r"""
local live_enemy_count = 0
local live_enemy_address = 0
local reward_addresses = {}
local gold_count = 0
for _, actor in ipairs(sd.world.list_actors and sd.world.list_actors() or {}) do
  local address = tonumber(actor.actor_address) or 0
  if actor.tracked_enemy and not actor.dead and (tonumber(actor.max_hp) or 0) > 0 then
    live_enemy_count = live_enemy_count + 1
    if live_enemy_address == 0 or address < live_enemy_address then
      live_enemy_address = address
    end
  end
  local object_type = tonumber(actor.object_type_id) or 0
  if object_type == 2011 or object_type == 2012 or object_type == 2013 or object_type == 2038 then
    reward_addresses[#reward_addresses + 1] = tostring(address)
    if object_type == 2012 then
      gold_count = gold_count + 1
    end
  end
end
table.sort(reward_addresses)

local restored_selectors = {}
local config = tonumber(__lua_drop_filter_first_config) or 0
if config ~= 0 then
  for index = 0, 5 do
    restored_selectors[#restored_selectors + 1] = tostring(sd.debug.read_u8(config + 0xCC + index))
  end
end
local restored_mask = -1
local arena = tonumber(__lua_drop_filter_first_arena) or 0
if arena ~= 0 then
  restored_mask = tonumber(sd.debug.read_u32(arena + 0x8F04)) or -1
end

print("first_count=" .. tostring(__lua_drop_filter_first_count or 0))
print("second_count=" .. tostring(__lua_drop_filter_second_count or 0))
print("post_count=" .. tostring(__lua_drop_filter_post_count or 0))
print("first_input=" .. tostring(__lua_drop_filter_first_input or ""))
print("second_input_gold=" .. tostring(__lua_drop_filter_second_input_gold or -1))
print("second_kind=" .. tostring(__lua_drop_filter_second_kind or ""))
print("restored_selectors=" .. table.concat(restored_selectors, ","))
print("original_mask=" .. tostring(__lua_drop_filter_first_mask or -1))
print("restored_mask=" .. tostring(restored_mask))
print("live_enemy_count=" .. tostring(live_enemy_count))
print("live_enemy_address=" .. tostring(live_enemy_address))
print("reward_addresses=" .. table.concat(reward_addresses, ","))
print("gold_count=" .. tostring(gold_count))
"""

KILL_ONE = r"""
local target = nil
for _, actor in ipairs(sd.world.list_actors and sd.world.list_actors() or {}) do
  if actor.tracked_enemy and not actor.dead and (tonumber(actor.max_hp) or 0) > 0 then
    if target == nil or (tonumber(actor.actor_address) or 0) < (tonumber(target.actor_address) or 0) then
      target = actor
    end
  end
end
if target == nil then
  print("killed=false")
  print("reason=no_live_enemy")
  return
end
local address = tonumber(target.actor_address) or 0
local max_hp = math.max(tonumber(target.max_hp) or 1, 1)
local original_config = tonumber(sd.debug.read_ptr(address + 0x1D0)) or 0
local config = original_config
local fixture = false
if config == 0 then
  local operator_new = assert(
    sd.debug.resolve_game_address(0x74784D),
    "retail operator new could not be resolved")
  config = assert(
    sd.debug.call_cdecl_u32_ret_u32(operator_new, 0x200),
    "drop config fixture allocation failed")
  for offset = 0, 0x1FC, 4 do
    assert(sd.debug.write_u32(config + offset, 0))
  end
  assert(sd.debug.write_i32(
    config + 0x54,
    tonumber(target.object_type_id) or 0))
  assert(sd.debug.write_ptr(address + 0x1D0, config))
  fixture = true
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
print("fixture=" .. tostring(fixture))
"""

DEATH_RESULT = r"""
local completed, success, seh, restored, err =
  sd.debug.get_native_enemy_death_probe_result(%d)
print("completed=" .. tostring(completed))
print("success=" .. tostring(success))
print("seh=" .. tostring(seh or 0))
print("config_restored=" .. tostring(restored))
print("error=" .. tostring(err or ""))
"""


def _status(pipe_name: str) -> dict[str, str]:
    return parse_key_values(lua(pipe_name, STATUS, timeout=8.0))


def _reward_addresses(status: dict[str, str]) -> set[int]:
    raw = status.get("reward_addresses", "")
    if not raw:
        return set()
    try:
        return {int(value) for value in raw.split(",") if value}
    except ValueError as exc:
        raise VerifyFailure(f"invalid reward address list: {raw!r}") from exc


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
        time.sleep(0.15)
    raise VerifyFailure(f"timed out waiting for {description}: {last}")


def _kill_one(pipe_name: str) -> dict[str, str]:
    queued = parse_key_values(lua(pipe_name, KILL_ONE, timeout=8.0))
    try:
        request_serial = int(queued.get("serial", "0"))
    except ValueError as exc:
        raise VerifyFailure(f"invalid native enemy-death serial: {queued}") from exc
    if (
        queued.get("queued") != "true"
        or queued.get("write_health") != "true"
        or request_serial == 0
    ):
        raise VerifyFailure(f"native enemy death failed to queue: {queued}")

    deadline = time.monotonic() + 8.0
    result: dict[str, str] = {}
    while time.monotonic() < deadline:
        result = parse_key_values(
            lua(pipe_name, DEATH_RESULT % request_serial, timeout=8.0)
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
        raise VerifyFailure(f"drop filters failed to register: {registration}")

    start = parse_key_values(
        lua(
            pipe_name,
            'print("started=" .. tostring(sd.gameplay.start_waves()))',
            timeout=8.0,
        )
    )
    if start.get("started") != "true":
        raise VerifyFailure(f"stock waves failed to start: {start}")

    _wait_for(
        pipe_name,
        lambda row: int(row.get("live_enemy_count", "0")) >= 1,
        timeout,
        "the first stock enemy",
    )
    first_kill = _kill_one(pipe_name)

    first_status = _wait_for(
        pipe_name,
        lambda row: (
            int(row.get("first_count", "0")) >= 1
            and int(row.get("second_count", "0")) >= 1
            and int(row.get("post_count", "0")) >= 1
            and int(row.get("gold_count", "0")) >= 1
        ),
        timeout,
        "the forced native gold reward",
    )
    if first_status.get("second_input_gold") != "3":
        raise VerifyFailure(
            "second handler did not observe the first selector rewrite: "
            f"{first_status}"
        )
    if first_status.get("second_kind") != "stock":
        raise VerifyFailure(
            f"unexpected pre-force handler kind: {first_status}"
        )
    if first_status.get("restored_selectors") != first_status.get("first_input"):
        raise VerifyFailure(
            "native config selector bytes were not restored after forcing gold: "
            f"{first_status}"
        )
    if first_status.get("restored_mask") != first_status.get("original_mask"):
        raise VerifyFailure(
            "arena drop mask was not restored after forcing gold: "
            f"{first_status}"
        )

    rewards_before_cancel = _reward_addresses(first_status)
    post_count_before_cancel = int(first_status.get("post_count", "0"))
    _wait_for(
        pipe_name,
        lambda row: int(row.get("live_enemy_count", "0")) >= 1,
        timeout,
        "the second stock enemy",
    )
    second_kill = _kill_one(pipe_name)
    canceled_status = _wait_for(
        pipe_name,
        lambda row: (
            int(row.get("first_count", "0")) >= 2
            and int(row.get("second_count", "0")) >= 2
        ),
        timeout,
        "the canceled second roll",
    )
    time.sleep(0.75)
    settled_status = _status(pipe_name)
    new_rewards = _reward_addresses(settled_status) - rewards_before_cancel
    if new_rewards:
        raise VerifyFailure(
            f"canceled roll materialized reward actors: {sorted(new_rewards)}"
        )
    if int(settled_status.get("post_count", "0")) != post_count_before_cancel:
        raise VerifyFailure(
            "canceled roll emitted a post-spawn notification: "
            f"before={post_count_before_cancel} status={settled_status}"
        )

    return {
        "ok": True,
        "pipe": pipe_name,
        "registration": registration,
        "start": start,
        "first_kill": first_kill,
        "first_status": first_status,
        "rewards_before_cancel": sorted(rewards_before_cancel),
        "second_kill": second_kill,
        "canceled_status": canceled_status,
        "settled_status": settled_status,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pipe", default=DEFAULT_PIPE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()

    result: dict[str, Any] = {"ok": False, "pipe": args.pipe}
    try:
        result = run(args.pipe, args.timeout)
        return_code = 0
    except Exception as exc:  # noqa: BLE001 - persist exact live evidence.
        result["error"] = str(exc)
        return_code = 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "ok": result.get("ok", False),
                "error": result.get("error"),
                "output": str(args.output),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
