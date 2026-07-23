#!/usr/bin/env python3
"""Verify sd.time against an already-running loader in an active run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from verify_local_multiplayer_sync import VerifyFailure, lua, parse_key_values


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "runtime" / "lua_time_verification.json"
DEFAULT_PIPE = "SolomonDarkModLoader_LuaExec"


PROBE = r'''
assert(type(sd.time) == "table", "missing sd.time")
for _, name in ipairs({"get_scale", "get_state", "set_scale", "step"}) do
  assert(type(sd.time[name]) == "function", "missing sd.time." .. name)
end
assert(sd.runtime.has_capability("time.shared.scale"))
assert(sd.runtime.has_capability("time.shared.frame_step"))

local ok, result = xpcall(function()
  local initial = sd.time.get_state()
  assert(type(initial.scale) == "number")
  assert(initial.maximum_step_frames == 120)
  assert(initial.scale_resolution == 0.000001)

  local slow = sd.time.set_scale(0.5)
  assert(slow <= 0.5)
  local slowed = sd.time.get_state()
  assert(slowed.scale <= 0.5 and slowed.requested_scale == 0.5)

  sd.time.set_scale(0)
  local paused = sd.time.get_state()
  assert(paused.paused and paused.requested_scale == 0)
  local sequence = sd.time.step(1)
  assert(type(sequence) == "number" and sequence > 0)

  local invalid_scale = pcall(sd.time.set_scale, 1.01)
  local invalid_step = pcall(sd.time.step, 121)
  return {
    namespace_valid = true,
    slow_motion_valid = true,
    pause_valid = true,
    step_valid = true,
    invalid_scale_rejected = not invalid_scale,
    invalid_step_rejected = not invalid_step,
  }
end, function(message) return tostring(message) end)

pcall(sd.time.set_scale, 1)
if not ok then error(result) end
for key, value in pairs(result) do
  print(key .. "=" .. tostring(value))
end
'''


def run(pipe_name: str) -> dict[str, Any]:
    values = parse_key_values(lua(pipe_name, PROBE, timeout=12.0))
    checks = (
        "namespace_valid",
        "slow_motion_valid",
        "pause_valid",
        "step_valid",
        "invalid_scale_rejected",
        "invalid_step_rejected",
    )
    failures = [name for name in checks if values.get(name) != "true"]
    if failures:
        raise VerifyFailure(f"Lua time contract failed {failures}: {values}")
    return {"ok": True, "pipe": pipe_name, "values": values}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pipe", default=DEFAULT_PIPE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    try:
        result: dict[str, Any] = run(args.pipe)
        return_code = 0
    except Exception as error:  # noqa: BLE001 - preserve exact live evidence.
        result = {"ok": False, "pipe": args.pipe, "error": str(error)}
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
