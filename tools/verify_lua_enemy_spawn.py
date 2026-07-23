#!/usr/bin/env python3
"""Opt-in live verification of one authority-owned registered enemy spawn."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from verify_local_multiplayer_sync import VerifyFailure, lua, parse_key_values


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "runtime" / "lua_enemy_spawn_verification.json"
DEFAULT_PIPE = "SolomonDarkModLoader_LuaExec"
EXPECTED_CONTENT_ID = 8726222830294414077


QUEUE_SPAWN = r'''
assert(sd.runtime.has_capability("enemies.spawn.authority"))
assert(sd.state.is_authority(), "enemy spawning requires the offline or host authority")
local enemy = assert(
  sd.enemies.get(8726222830294414077),
  "enable the Lua Enemies Registry Lab mod before verification"
)
local player = assert(sd.player.get_state(), "player state unavailable")
assert(player.valid, "enter an active combat arena before verification")
local x = player.x + 200
local y = player.y
local queued = sd.enemies.spawn(enemy.id, {
  x = x,
  y = y,
  hp = 321,
  speed = 2.75,
  scale = 1.25,
  loot = "none",
})
assert(queued.queued and queued.request_id > 0, "spawn was not queued")
assert(queued.content_id == enemy.id, "queued content id differs")
print("content_id=" .. tostring(queued.content_id))
print("request_id=" .. tostring(queued.request_id))
print("requested_x=" .. tostring(x))
print("requested_y=" .. tostring(y))
'''


def result_probe(request_id: int) -> str:
    return f'''
local result = sd.gameplay.get_last_manual_run_enemy_spawn({request_id})
if result == nil then
  print("complete=false")
else
  print("complete=true")
  print("ok=" .. tostring(result.ok))
  print("content_id=" .. tostring(result.content_id))
  print("actor_address=" .. tostring(result.actor_address))
  print("x=" .. tostring(result.x))
  print("y=" .. tostring(result.y))
  print("error=" .. tostring(result.error))
  local max_hp = -1
  for _, actor in ipairs(sd.world.list_actors()) do
    if actor.actor_address == result.actor_address then max_hp = actor.max_hp end
  end
  print("max_hp=" .. tostring(max_hp))
end
'''


def integer(values: dict[str, str], field: str) -> int:
    try:
        return int(values[field], 0)
    except (KeyError, ValueError) as error:
        raise VerifyFailure(f"enemy spawn probe lacks integer {field}: {values}") from error


def number(values: dict[str, str], field: str) -> float:
    try:
        return float(values[field])
    except (KeyError, ValueError) as error:
        raise VerifyFailure(f"enemy spawn probe lacks number {field}: {values}") from error


def run(pipe_name: str, timeout_seconds: float) -> dict[str, Any]:
    queued = parse_key_values(lua(pipe_name, QUEUE_SPAWN, timeout=12.0))
    request_id = integer(queued, "request_id")
    if integer(queued, "content_id") != EXPECTED_CONTENT_ID or request_id <= 0:
        raise VerifyFailure(f"enemy spawn queue contract differs: {queued}")

    deadline = time.monotonic() + timeout_seconds
    observed: dict[str, str] = {}
    while True:
        observed = parse_key_values(
            lua(pipe_name, result_probe(request_id), timeout=5.0)
        )
        if observed.get("complete") == "true":
            break
        if time.monotonic() >= deadline:
            raise VerifyFailure(f"enemy spawn request {request_id} did not complete")
        time.sleep(0.2)

    if observed.get("ok") != "true":
        raise VerifyFailure(f"enemy spawn failed: {observed}")
    if integer(observed, "content_id") != EXPECTED_CONTENT_ID:
        raise VerifyFailure(f"completed content identity differs: {observed}")
    if integer(observed, "actor_address") <= 0:
        raise VerifyFailure(f"spawned actor address is missing: {observed}")
    if abs(number(observed, "max_hp") - 321.0) > 0.05:
        raise VerifyFailure(f"spawn HP override differs: {observed}")
    if abs(number(observed, "x") - number(queued, "requested_x")) > 0.05 or abs(
        number(observed, "y") - number(queued, "requested_y")
    ) > 0.05:
        raise VerifyFailure(f"spawn position differs: queued={queued} result={observed}")

    return {
        "ok": True,
        "pipe": pipe_name,
        "request_id": request_id,
        "queued": queued,
        "result": observed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pipe", default=DEFAULT_PIPE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    parser.add_argument(
        "--confirm-mutation",
        action="store_true",
        help="confirm that the verifier may spawn one live hostile enemy",
    )
    args = parser.parse_args()

    result: dict[str, Any] = {"ok": False, "pipe": args.pipe}
    if not args.confirm_mutation:
        result["error"] = "refusing enemy spawn without --confirm-mutation"
        return_code = 2
    elif args.timeout_seconds <= 0 or args.timeout_seconds > 60:
        result["error"] = "--timeout-seconds must be greater than 0 and at most 60"
        return_code = 2
    else:
        try:
            result = run(args.pipe, args.timeout_seconds)
            return_code = 0
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
