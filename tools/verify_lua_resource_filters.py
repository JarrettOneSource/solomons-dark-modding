#!/usr/bin/env python3
"""Verify XP and gold filters through retail progression and pickup paths."""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any, Callable

from verify_local_multiplayer_sync import VerifyFailure, lua, parse_key_values


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "runtime" / "lua_resource_filter_verification.json"
DEFAULT_PIPE = "SolomonDarkModLoader_LuaExec"
# The retail gold spawner decomposes larger totals into denomination pickups.
# Keep these amounts small so each test reaches Gold_ChangeGlobal as one delta.
ORDERED_GOLD_AMOUNT = 1
CANCELED_GOLD_AMOUNT = 3

REGISTER_XP = r"""
if __lua_resource_xp_registered == true then
  error("XP resource filters are already registered; restart the disposable process")
end
local scene = sd.world.get_scene and sd.world.get_scene() or nil
if type(scene) ~= "table" or tostring(scene.name or scene.kind or "") ~= "testrun" then
  error("resource filter acceptance requires a settled testrun")
end

__lua_resource_xp_registered = true
__lua_resource_xp_phase = "rewrite"
__lua_resource_xp_first_count = 0
__lua_resource_xp_second_count = 0
__lua_resource_xp_first_input = 0
__lua_resource_xp_second_input = 0
__lua_resource_xp_current = 0
__lua_resource_xp_source = ""
__lua_resource_xp_native_scaling = false

sd.events.filter("xp.gaining", function(event)
  __lua_resource_xp_first_count = __lua_resource_xp_first_count + 1
  __lua_resource_xp_first_input = tonumber(event.amount) or 0
  __lua_resource_xp_current = tonumber(event.current_xp) or 0
  __lua_resource_xp_source = tostring(event.source or "")
  __lua_resource_xp_native_scaling = event.native_scaling == true
  return {amount = event.amount * 2}
end)

sd.events.filter("xp.gaining", function(event)
  __lua_resource_xp_second_count = __lua_resource_xp_second_count + 1
  __lua_resource_xp_second_input = tonumber(event.amount) or 0
  if __lua_resource_xp_phase == "cancel" then
    return false
  end
  return {amount = 7}
end)

print("registered=true")
print("capability=" .. tostring(sd.runtime.has_capability("events.filters.resources")))
"""

REGISTER_GOLD = rf"""
if __lua_resource_gold_registered == true then
  error("gold resource filters are already registered; restart the disposable process")
end
__lua_resource_gold_registered = true
__lua_resource_gold_phase = "rewrite"
__lua_resource_gold_first_count = 0
__lua_resource_gold_second_count = 0
__lua_resource_gold_post_count = 0
__lua_resource_gold_post_delta = 0
__lua_resource_gold_first_input = 0
__lua_resource_gold_second_input = 0
__lua_resource_gold_current = 0
__lua_resource_gold_source = ""

sd.events.filter("gold.changing", function(event)
  if event.delta ~= {ORDERED_GOLD_AMOUNT} and event.delta ~= {CANCELED_GOLD_AMOUNT} then
    return nil
  end
  __lua_resource_gold_first_count = __lua_resource_gold_first_count + 1
  __lua_resource_gold_first_input = tonumber(event.delta) or 0
  __lua_resource_gold_current = tonumber(event.current_gold) or 0
  __lua_resource_gold_source = tostring(event.source or "")
  return {{delta = event.delta * 2}}
end)

sd.events.filter("gold.changing", function(event)
  if event.delta ~= {ORDERED_GOLD_AMOUNT * 2} and event.delta ~= {CANCELED_GOLD_AMOUNT * 2} then
    return nil
  end
  __lua_resource_gold_second_count = __lua_resource_gold_second_count + 1
  __lua_resource_gold_second_input = tonumber(event.delta) or 0
  if __lua_resource_gold_phase == "cancel" then
    return false
  end
  return {{delta = event.delta + 3}}
end)

sd.events.on("gold.changed", function(event)
  if event.delta == {ORDERED_GOLD_AMOUNT * 2 + 3} then
    __lua_resource_gold_post_count = __lua_resource_gold_post_count + 1
    __lua_resource_gold_post_delta = tonumber(event.delta) or 0
  end
end)

print("registered=true")
"""

STATUS = r"""
local player = sd.player.get_state()
print("xp=" .. tostring(player and player.xp or -1))
print("gold=" .. tostring(player and player.gold or -1))
print("xp_first_count=" .. tostring(__lua_resource_xp_first_count or 0))
print("xp_second_count=" .. tostring(__lua_resource_xp_second_count or 0))
print("xp_first_input=" .. tostring(__lua_resource_xp_first_input or 0))
print("xp_second_input=" .. tostring(__lua_resource_xp_second_input or 0))
print("xp_current=" .. tostring(__lua_resource_xp_current or 0))
print("xp_source=" .. tostring(__lua_resource_xp_source or ""))
print("xp_native_scaling=" .. tostring(__lua_resource_xp_native_scaling or false))
print("gold_first_count=" .. tostring(__lua_resource_gold_first_count or 0))
print("gold_second_count=" .. tostring(__lua_resource_gold_second_count or 0))
print("gold_post_count=" .. tostring(__lua_resource_gold_post_count or 0))
print("gold_post_delta=" .. tostring(__lua_resource_gold_post_delta or 0))
print("gold_first_input=" .. tostring(__lua_resource_gold_first_input or 0))
print("gold_second_input=" .. tostring(__lua_resource_gold_second_input or 0))
print("gold_current=" .. tostring(__lua_resource_gold_current or 0))
print("gold_source=" .. tostring(__lua_resource_gold_source or ""))
"""

QUEUE_XP = r"""
local queued, err, serial = sd.debug.queue_native_experience_gain_probe(%s, %s)
print("queued=" .. tostring(queued))
print("error=" .. tostring(err or ""))
print("serial=" .. tostring(serial or 0))
"""

XP_RESULT = r"""
local completed, success, before_xp, after_xp, seh, err =
  sd.debug.get_native_experience_gain_probe_result(%d)
print("completed=" .. tostring(completed))
print("success=" .. tostring(success))
print("before_xp=" .. tostring(before_xp or 0))
print("after_xp=" .. tostring(after_xp or 0))
print("seh=" .. tostring(seh or 0))
print("error=" .. tostring(err or ""))
"""

SPAWN_GOLD = r"""
local player = assert(sd.player.get_state(), "player state unavailable")
local ok, err = sd.world.spawn_reward({
  kind = "gold",
  amount = %d,
  x = assert(tonumber(player.x)),
  y = assert(tonumber(player.y)),
})
print("spawned=" .. tostring(ok))
print("error=" .. tostring(err or ""))
"""


def _number(values: dict[str, str], name: str) -> float:
    try:
        value = float(values.get(name, "nan"))
    except ValueError as exc:
        raise VerifyFailure(f"non-numeric {name}: {values.get(name)!r}") from exc
    if not math.isfinite(value):
        raise VerifyFailure(f"non-finite {name}: {values.get(name)!r}")
    return value


def _status(pipe_name: str) -> dict[str, str]:
    return parse_key_values(lua(pipe_name, STATUS, timeout=8.0))


def _wait_for(
    pipe_name: str,
    predicate: Callable[[dict[str, str]], bool],
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


def _queue_xp(
    pipe_name: str,
    amount: float,
    apply_native_scaling: bool,
    timeout: float,
) -> dict[str, str]:
    code = QUEUE_XP % (repr(amount), "true" if apply_native_scaling else "false")
    queued = parse_key_values(lua(pipe_name, code, timeout=8.0))
    try:
        serial = int(queued.get("serial", "0"))
    except ValueError as exc:
        raise VerifyFailure(f"invalid XP probe serial: {queued}") from exc
    if queued.get("queued") != "true" or serial == 0:
        raise VerifyFailure(f"native XP gain failed to queue: {queued}")

    deadline = time.monotonic() + timeout
    result: dict[str, str] = {}
    while time.monotonic() < deadline:
        result = parse_key_values(lua(pipe_name, XP_RESULT % serial, timeout=8.0))
        if result.get("completed") == "true":
            break
        time.sleep(0.02)
    if (
        result.get("completed") != "true"
        or result.get("success") != "true"
        or result.get("seh") != "0"
    ):
        raise VerifyFailure(f"native XP gain failed: queue={queued} result={result}")
    return {**queued, **result}


def _set_phase(pipe_name: str, family: str, phase: str) -> None:
    lua(
        pipe_name,
        f'__lua_resource_{family}_phase = "{phase}"; print("phase={phase}")',
        timeout=8.0,
    )


def _spawn_gold(pipe_name: str, amount: int) -> dict[str, str]:
    result = parse_key_values(lua(pipe_name, SPAWN_GOLD % amount, timeout=8.0))
    if result.get("spawned") != "true":
        raise VerifyFailure(f"native gold reward failed to spawn: {result}")
    return result


def run(pipe_name: str, timeout: float) -> dict[str, Any]:
    registration = parse_key_values(lua(pipe_name, REGISTER_XP, timeout=12.0))
    if registration.get("registered") != "true" or registration.get("capability") != "true":
        raise VerifyFailure(f"XP filters failed to register: {registration}")

    before_xp = _number(_status(pipe_name), "xp")
    first_xp_probe = _queue_xp(pipe_name, 3.0, False, timeout)
    xp_ordered_rewrite = _status(pipe_name)
    if xp_ordered_rewrite.get("xp_first_count") != "1" or xp_ordered_rewrite.get(
        "xp_second_count"
    ) != "1":
        raise VerifyFailure(f"XP rewrite did not execute exactly once: {xp_ordered_rewrite}")
    first_input = _number(xp_ordered_rewrite, "xp_first_input")
    second_input = _number(xp_ordered_rewrite, "xp_second_input")
    if abs(second_input - first_input * 2.0) > 0.001:
        raise VerifyFailure(f"second XP handler missed the first rewrite: {xp_ordered_rewrite}")
    if xp_ordered_rewrite.get("xp_source") != "script" or xp_ordered_rewrite.get(
        "xp_native_scaling"
    ) != "false":
        raise VerifyFailure(f"XP probe identity was not unscaled script input: {xp_ordered_rewrite}")
    after_rewrite_xp = _number(xp_ordered_rewrite, "xp")
    if (
        abs(_number(first_xp_probe, "before_xp") - before_xp) > 0.001
        or abs(_number(first_xp_probe, "after_xp") - after_rewrite_xp) > 0.001
        or abs((after_rewrite_xp - before_xp) - 7.0) > 0.001
    ):
        raise VerifyFailure(
            "ordered XP rewrite did not commit through native progression: "
            f"before={before_xp} after={after_rewrite_xp} status={xp_ordered_rewrite}"
        )

    _set_phase(pipe_name, "xp", "cancel")
    before_cancel_xp = _number(_status(pipe_name), "xp")
    canceled_xp_probe = _queue_xp(pipe_name, 5.0, False, timeout)
    xp_cancellation = _status(pipe_name)
    if xp_cancellation.get("xp_first_count") != "2" or xp_cancellation.get(
        "xp_second_count"
    ) != "2":
        raise VerifyFailure(f"XP cancellation did not execute exactly once: {xp_cancellation}")
    if (
        abs(_number(canceled_xp_probe, "before_xp") - before_cancel_xp) > 0.001
        or abs(_number(canceled_xp_probe, "after_xp") - before_cancel_xp) > 0.001
        or abs(_number(xp_cancellation, "xp") - before_cancel_xp) > 0.001
    ):
        raise VerifyFailure(
            f"canceled XP gain changed native progression: {xp_cancellation}"
        )

    gold_registration = parse_key_values(lua(pipe_name, REGISTER_GOLD, timeout=12.0))
    if gold_registration.get("registered") != "true":
        raise VerifyFailure(f"gold filters failed to register: {gold_registration}")

    before_gold = _number(_status(pipe_name), "gold")
    first_gold_spawn = _spawn_gold(pipe_name, ORDERED_GOLD_AMOUNT)
    gold_ordered_rewrite = _wait_for(
        pipe_name,
        lambda row: (
            int(row.get("gold_second_count", "0")) >= 1
            and int(row.get("gold_post_count", "0")) >= 1
        ),
        timeout,
        "ordered native gold rewrite",
    )
    if gold_ordered_rewrite.get("gold_first_count") != "1" or gold_ordered_rewrite.get(
        "gold_second_count"
    ) != "1":
        raise VerifyFailure(f"gold rewrite did not execute exactly once: {gold_ordered_rewrite}")
    if _number(gold_ordered_rewrite, "gold_first_input") != ORDERED_GOLD_AMOUNT:
        raise VerifyFailure(f"gold first input mismatch: {gold_ordered_rewrite}")
    if _number(gold_ordered_rewrite, "gold_second_input") != ORDERED_GOLD_AMOUNT * 2:
        raise VerifyFailure(f"second gold handler missed the first rewrite: {gold_ordered_rewrite}")
    if gold_ordered_rewrite.get("gold_source") != "pickup":
        raise VerifyFailure(f"gold pickup source mismatch: {gold_ordered_rewrite}")
    expected_gold_delta = ORDERED_GOLD_AMOUNT * 2 + 3
    if _number(gold_ordered_rewrite, "gold") - before_gold != expected_gold_delta:
        raise VerifyFailure(
            "ordered gold rewrite did not commit through Gold_ChangeGlobal: "
            f"before={before_gold} status={gold_ordered_rewrite}"
        )
    if _number(gold_ordered_rewrite, "gold_post_delta") != expected_gold_delta:
        raise VerifyFailure(f"gold.changed did not report applied delta: {gold_ordered_rewrite}")

    _set_phase(pipe_name, "gold", "cancel")
    before_cancel_gold = _number(_status(pipe_name), "gold")
    post_count_before_cancel = int(_status(pipe_name).get("gold_post_count", "0"))
    second_gold_spawn = _spawn_gold(pipe_name, CANCELED_GOLD_AMOUNT)
    gold_cancellation = _wait_for(
        pipe_name,
        lambda row: int(row.get("gold_second_count", "0")) >= 2,
        timeout,
        "native gold cancellation",
    )
    time.sleep(0.75)
    gold_cancellation = _status(pipe_name)
    if gold_cancellation.get("gold_first_count") != "2" or gold_cancellation.get(
        "gold_second_count"
    ) != "2":
        raise VerifyFailure(
            f"gold cancellation did not execute exactly once: {gold_cancellation}"
        )
    if _number(gold_cancellation, "gold") != before_cancel_gold:
        raise VerifyFailure(f"canceled gold change mutated the total: {gold_cancellation}")
    if int(gold_cancellation.get("gold_post_count", "0")) != post_count_before_cancel:
        raise VerifyFailure(f"canceled gold change emitted post telemetry: {gold_cancellation}")

    native_experience_gain = {
        "before": before_xp,
        "after": after_rewrite_xp,
        "first_probe": first_xp_probe,
        "canceled_probe": canceled_xp_probe,
    }
    native_gold_change = {
        "before": before_gold,
        "after": _number(gold_ordered_rewrite, "gold"),
        "first_spawn": first_gold_spawn,
    }
    return {
        "ok": True,
        "pipe": pipe_name,
        "registration": registration,
        "xp_ordered_rewrite": xp_ordered_rewrite,
        "xp_cancellation": xp_cancellation,
        "gold_registration": gold_registration,
        "gold_ordered_rewrite": gold_ordered_rewrite,
        "gold_cancellation": gold_cancellation,
        "native_experience_gain": native_experience_gain,
        "native_gold_change": native_gold_change,
        "second_gold_spawn": second_gold_spawn,
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
    except Exception as error:  # noqa: BLE001 - persist exact live evidence.
        result["error"] = str(error)
        return_code = 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
