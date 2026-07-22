#!/usr/bin/env python3
"""Verify ordered enemy-spawn rewrites and cancellation on stock waves."""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any

from verify_local_multiplayer_sync import VerifyFailure, lua, parse_key_values


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "runtime" / "lua_enemy_spawn_filter_verification.json"
DEFAULT_PIPE = "SolomonDarkModLoader_LuaExec"
FIRST_REWRITE_HP = 2000.0
FINAL_REWRITE_HP = 4321.0

REGISTER = rf"""
if __lua_enemy_spawn_filter_acceptance_registered == true then
  error("enemy spawn filter acceptance is already registered; restart the disposable process")
end

local scene = sd.world.get_scene and sd.world.get_scene() or nil
if type(scene) ~= "table" or tostring(scene.name or scene.kind or "") ~= "testrun" then
  error("enemy spawn filter acceptance requires a settled testrun before registration")
end

local existing = 0
for _, actor in ipairs(sd.world.list_actors and sd.world.list_actors() or {{}}) do
  if actor.tracked_enemy and not actor.dead and (tonumber(actor.max_hp) or 0) > 0 then
    existing = existing + 1
  end
end
if existing ~= 0 then
  error("enemy spawn filter acceptance requires a pre-wave run with no live enemies")
end

__lua_enemy_spawn_filter_acceptance_registered = true
__lua_enemy_spawn_filter_first_count = 0
__lua_enemy_spawn_filter_second_count = 0
__lua_enemy_spawn_filter_post_count = 0
__lua_enemy_spawn_filter_first_input_hp = 0
__lua_enemy_spawn_filter_second_input_hp = 0
__lua_enemy_spawn_filter_post_type = 0

sd.events.filter("enemy.spawning", function(event)
  __lua_enemy_spawn_filter_first_count = __lua_enemy_spawn_filter_first_count + 1
  if __lua_enemy_spawn_filter_first_count == 1 then
    __lua_enemy_spawn_filter_first_input_hp = event.hp
    return {{hp = {FIRST_REWRITE_HP}}}
  end
  return nil
end)

sd.events.filter("enemy.spawning", function(event)
  __lua_enemy_spawn_filter_second_count = __lua_enemy_spawn_filter_second_count + 1
  if __lua_enemy_spawn_filter_second_count == 1 then
    __lua_enemy_spawn_filter_second_input_hp = event.hp
    return {{hp = {FINAL_REWRITE_HP}}}
  end
  return false
end)

sd.events.on("enemy.spawned", function(event)
  __lua_enemy_spawn_filter_post_count = __lua_enemy_spawn_filter_post_count + 1
  __lua_enemy_spawn_filter_post_type = event.enemy_type or 0
end)

print("registered=true")
print("capability=" .. tostring(sd.runtime.has_capability("events.filters.enemy_spawn")))
"""

STATUS = r"""
local actor_count = 0
local actor_max_hp = 0
local actor_type = 0
for _, actor in ipairs(sd.world.list_actors and sd.world.list_actors() or {}) do
  if actor.tracked_enemy and not actor.dead and (tonumber(actor.max_hp) or 0) > 0 then
    actor_count = actor_count + 1
    actor_max_hp = tonumber(actor.max_hp) or actor_max_hp
    actor_type = tonumber(actor.enemy_type) or actor_type
  end
end
print("first_count=" .. tostring(__lua_enemy_spawn_filter_first_count or 0))
print("second_count=" .. tostring(__lua_enemy_spawn_filter_second_count or 0))
print("post_count=" .. tostring(__lua_enemy_spawn_filter_post_count or 0))
print("first_input_hp=" .. tostring(__lua_enemy_spawn_filter_first_input_hp or 0))
print("second_input_hp=" .. tostring(__lua_enemy_spawn_filter_second_input_hp or 0))
print("post_type=" .. tostring(__lua_enemy_spawn_filter_post_type or 0))
print("actor_count=" .. tostring(actor_count))
print("actor_max_hp=" .. tostring(actor_max_hp))
print("actor_type=" .. tostring(actor_type))
"""


def _number(values: dict[str, str], key: str) -> float:
    try:
        value = float(values.get(key, "nan"))
    except ValueError as exc:
        raise VerifyFailure(
            f"enemy spawn filter returned non-numeric {key}: {values.get(key)!r}"
        ) from exc
    if not math.isfinite(value):
        raise VerifyFailure(
            f"enemy spawn filter returned non-finite {key}: {values.get(key)!r}"
        )
    return value


def run(pipe_name: str, timeout: float) -> dict[str, Any]:
    registration = parse_key_values(lua(pipe_name, REGISTER, timeout=12.0))
    if registration.get("registered") != "true" or registration.get(
        "capability"
    ) != "true":
        raise VerifyFailure(f"enemy spawn filters failed to register: {registration}")

    start = parse_key_values(
        lua(
            pipe_name,
            'print("started=" .. tostring(sd.gameplay.start_waves()))',
            timeout=8.0,
        )
    )
    if start.get("started") != "true":
        raise VerifyFailure(f"stock waves failed to start: {start}")

    deadline = time.monotonic() + timeout
    status: dict[str, str] = {}
    while time.monotonic() < deadline:
        status = parse_key_values(lua(pipe_name, STATUS, timeout=8.0))
        if (
            int(status.get("first_count", "0")) >= 2
            and int(status.get("second_count", "0")) >= 2
            and int(status.get("post_count", "0")) == 1
            and int(status.get("actor_count", "0")) == 1
        ):
            break
        time.sleep(0.15)
    else:
        raise VerifyFailure(
            "timed out waiting for one rewritten spawn and a canceled follow-up: "
            f"{status}"
        )

    first_input_hp = _number(status, "first_input_hp")
    second_input_hp = _number(status, "second_input_hp")
    actor_max_hp = _number(status, "actor_max_hp")
    if first_input_hp <= 0:
        raise VerifyFailure(f"invalid native input HP: {first_input_hp}")
    if abs(second_input_hp - FIRST_REWRITE_HP) > 0.001:
        raise VerifyFailure(
            "second handler did not observe the first ordered rewrite: "
            f"expected={FIRST_REWRITE_HP} actual={second_input_hp}"
        )
    if abs(actor_max_hp - FINAL_REWRITE_HP) > 0.01:
        raise VerifyFailure(
            "native actor did not consume the final rewritten max HP: "
            f"expected={FINAL_REWRITE_HP} actual={actor_max_hp}"
        )
    if status.get("post_type") != status.get("actor_type"):
        raise VerifyFailure(
            "rewritten actor identity disagrees with the post-spawn event: "
            f"{status}"
        )

    return {
        "ok": True,
        "pipe": pipe_name,
        "registration": registration,
        "start": start,
        "status": status,
        "first_input_hp": first_input_hp,
        "first_rewrite_hp": FIRST_REWRITE_HP,
        "second_input_hp": second_input_hp,
        "final_rewrite_hp": FINAL_REWRITE_HP,
        "actor_max_hp": actor_max_hp,
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
