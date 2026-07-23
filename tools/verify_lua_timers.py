#!/usr/bin/env python3
"""Exercise one-shot, repeating, sequence, cancellation, and error timers live."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from verify_local_multiplayer_sync import VerifyFailure, lua, parse_key_values


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "runtime" / "lua_timer_verification.json"
DEFAULT_PIPE = "SolomonDarkModLoader_LuaExec"


SETUP = r'''
assert(sd.runtime.has_capability("timer.local.scheduler"))
sd.timer.clear()
__sd_timer_acceptance = {
  after_count = 0,
  repeating_count = 0,
  sequence_order = "",
  cancelled_count = 0,
  error_count = 0,
}

sd.timer.after(90, function()
  __sd_timer_acceptance.after_count = __sd_timer_acceptance.after_count + 1
end)

local repeating
repeating = sd.timer.every(50, function()
  __sd_timer_acceptance.repeating_count = __sd_timer_acceptance.repeating_count + 1
  if __sd_timer_acceptance.repeating_count == 3 then
    assert(sd.timer.cancel(repeating))
  end
end)

sd.timer.sequence({
  { delay_ms = 30, callback = function()
      __sd_timer_acceptance.sequence_order = __sd_timer_acceptance.sequence_order .. "A"
    end },
  { delay_ms = 30, callback = function()
      __sd_timer_acceptance.sequence_order = __sd_timer_acceptance.sequence_order .. "B"
    end },
  { delay_ms = 30, callback = function()
      __sd_timer_acceptance.sequence_order = __sd_timer_acceptance.sequence_order .. "C"
    end },
})

local cancelled = sd.timer.after(90, function()
  __sd_timer_acceptance.cancelled_count = __sd_timer_acceptance.cancelled_count + 1
end)
assert(sd.timer.cancel(cancelled))
assert(not sd.timer.cancel(cancelled))

sd.timer.every(20, function()
  __sd_timer_acceptance.error_count = __sd_timer_acceptance.error_count + 1
  error("expected timer verifier failure")
end)

assert(not pcall(sd.timer.every, 0, function() end))
assert(not pcall(sd.timer.sequence, {}))
print("scheduled=true")
'''

QUERY = r'''
local state = __sd_timer_acceptance or {}
print("after_count=" .. tostring(state.after_count or -1))
print("repeating_count=" .. tostring(state.repeating_count or -1))
print("sequence_order=" .. tostring(state.sequence_order or ""))
print("cancelled_count=" .. tostring(state.cancelled_count or -1))
print("error_count=" .. tostring(state.error_count or -1))
'''


def run(pipe_name: str, timeout: float) -> dict[str, Any]:
    setup_values = parse_key_values(lua(pipe_name, SETUP, timeout=12.0))
    if setup_values.get("scheduled") != "true":
        raise VerifyFailure(f"timer setup failed: {setup_values}")

    deadline = time.monotonic() + timeout
    values: dict[str, str] = {}
    while time.monotonic() < deadline:
        values = parse_key_values(lua(pipe_name, QUERY, timeout=12.0))
        if (
            values.get("after_count") == "1"
            and values.get("repeating_count") == "3"
            and values.get("sequence_order") == "ABC"
            and values.get("cancelled_count") == "0"
            and values.get("error_count") == "1"
        ):
            break
        time.sleep(0.05)

    if values.get("after_count") != "1":
        raise VerifyFailure(f"one-shot callback count mismatch: {values}")
    if values.get("repeating_count") != "3":
        raise VerifyFailure(f"repeating callback count mismatch: {values}")
    if values.get("sequence_order") != "ABC":
        raise VerifyFailure(f"sequence order mismatch: {values}")
    if values.get("cancelled_count") != "0":
        raise VerifyFailure(f"cancelled callback ran: {values}")
    if values.get("error_count") != "1":
        raise VerifyFailure(f"failing repeating timer was not canceled: {values}")

    remaining = parse_key_values(
        lua(pipe_name, 'print("remaining=" .. tostring(sd.timer.clear()))', timeout=12.0)
    )
    if remaining.get("remaining") != "0":
        raise VerifyFailure(f"completed timers remain scheduled: {remaining}")
    return {
        "ok": True,
        "pipe": pipe_name,
        "values": values,
        "remaining": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pipe", default=DEFAULT_PIPE)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    result: dict[str, Any] = {"ok": False, "pipe": args.pipe}
    try:
        result = run(args.pipe, args.timeout)
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
