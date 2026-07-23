#!/usr/bin/env python3
"""Verify sd.camera against an already-running loader in a gameplay Region."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from verify_local_multiplayer_sync import VerifyFailure, lua, parse_key_values


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "runtime" / "lua_camera_verification.json"
DEFAULT_PIPE = "SolomonDarkModLoader_LuaExec"


PROBE = r'''
assert(type(sd.camera) == "table", "missing sd.camera")
for _, name in ipairs({"get_state", "set_focus", "clear_focus", "shake"}) do
  assert(type(sd.camera[name]) == "function", "missing sd.camera." .. name)
end
assert(sd.runtime.has_capability("camera.local.read"))
assert(sd.runtime.has_capability("camera.local.focus"))
assert(sd.runtime.has_capability("camera.local.shake"))

local initial = sd.camera.get_state()
assert(initial.available == true)
assert(initial.scene_available == true, "a gameplay Region is required")
for _, field in ipairs({
  "origin_x", "origin_y", "width", "height", "center_x", "center_y",
  "scale", "shake_magnitude", "shake_accumulator",
}) do
  assert(type(initial[field]) == "number", "invalid camera field " .. field)
end
assert(initial.width > 0 and initial.height > 0 and initial.scale > 0)

local extra_get_ok = pcall(sd.camera.get_state, true)
local nan_focus_ok = pcall(sd.camera.set_focus, 0 / 0, initial.center_y)
local huge_focus_ok = pcall(sd.camera.set_focus, 1000001, initial.center_y)
local zero_shake_ok = pcall(sd.camera.shake, 0)
local high_shake_ok = pcall(sd.camera.shake, 1.01)
local extra_clear_ok = pcall(sd.camera.clear_focus, true)

assert(sd.camera.set_focus(initial.center_x, initial.center_y) == true)
local focused = sd.camera.get_state()
assert(focused.focus_active == true and focused.owns_focus == true)
assert(focused.focus_x == initial.center_x and focused.focus_y == initial.center_y)
assert(sd.camera.shake(0.1) == true)
local shaken = sd.camera.get_state()
assert(shaken.shake_magnitude >= 0 and shaken.shake_accumulator >= 0)
assert(sd.camera.clear_focus() == true)
assert(sd.camera.clear_focus() == false)

print("namespace_valid=true")
print("state_schema_valid=true")
print("focus_lifecycle_valid=true")
print("native_shake_valid=true")
print("extra_get_rejected=" .. tostring(not extra_get_ok))
print("nan_focus_rejected=" .. tostring(not nan_focus_ok))
print("huge_focus_rejected=" .. tostring(not huge_focus_ok))
print("zero_shake_rejected=" .. tostring(not zero_shake_ok))
print("high_shake_rejected=" .. tostring(not high_shake_ok))
print("extra_clear_rejected=" .. tostring(not extra_clear_ok))
'''


def run(pipe_name: str) -> dict[str, Any]:
    values = parse_key_values(lua(pipe_name, PROBE, timeout=12.0))
    checks = (
        "namespace_valid",
        "state_schema_valid",
        "focus_lifecycle_valid",
        "native_shake_valid",
        "extra_get_rejected",
        "nan_focus_rejected",
        "huge_focus_rejected",
        "zero_shake_rejected",
        "high_shake_rejected",
        "extra_clear_rejected",
    )
    failures = [name for name in checks if values.get(name) != "true"]
    if failures:
        raise VerifyFailure(f"Lua camera contract failed {failures}: {values}")
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
        try:
            lua(args.pipe, "return sd.camera.clear_focus()", timeout=5.0)
        except Exception:  # noqa: BLE001 - original failure remains primary.
            pass

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
