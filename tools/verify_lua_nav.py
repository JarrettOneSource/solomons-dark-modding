#!/usr/bin/env python3
"""Verify the blessed Lua navigation surface in a live arena."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from verify_local_multiplayer_sync import VerifyFailure, lua, parse_key_values


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "runtime" / "lua_nav_verification.json"
DEFAULT_PIPE = "SolomonDarkModLoader_LuaExec"


PROBE = r'''
assert(sd.runtime.has_capability("nav.read"))
local grid = sd.nav.get_grid(2)
if not grid or grid.refresh_pending then
  print("ready=false")
  return
end
local player = assert(sd.player.get_state(), "live player required")
local segment_ok, segment_value = pcall(
  sd.nav.test_segment,
  player.x, player.y,
  player.x, player.y)
local sample_count = 0
for _, cell in ipairs(grid.cells) do sample_count = sample_count + #cell.samples end
local high_ok = pcall(sd.nav.get_grid, 5)
local fraction_ok = pcall(sd.nav.get_grid, 1.5)
print("ready=true")
print("width=" .. tostring(grid.width))
print("height=" .. tostring(grid.height))
print("subdivisions=" .. tostring(grid.subdivisions))
print("cell_count=" .. tostring(#grid.cells))
print("sample_count=" .. tostring(sample_count))
print("raw_addresses_absent=" .. tostring(
  grid.world_address == nil and
  grid.controller_address == nil and
  grid.cells_address == nil and
  grid.probe_actor_address == nil))
print("segment_ok=" .. tostring(segment_ok))
print("segment_type=" .. type(segment_value))
print("high_rejected=" .. tostring(not high_ok))
print("fraction_rejected=" .. tostring(not fraction_ok))
'''


def _positive_int(values: dict[str, str], name: str) -> int:
    try:
        value = int(values.get(name, "0"))
    except ValueError as error:
        raise VerifyFailure(f"navigation field {name} was not an integer: {values}") from error
    if value <= 0:
        raise VerifyFailure(f"navigation field {name} was not positive: {values}")
    return value


def run(pipe_name: str, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    values: dict[str, str] = {}
    while time.monotonic() < deadline:
        values = parse_key_values(lua(pipe_name, PROBE, timeout=12.0))
        if values.get("ready") == "true":
            break
        time.sleep(0.25)
    else:
        raise VerifyFailure(f"navigation snapshot did not reach subdivision 2: {values}")

    width = _positive_int(values, "width")
    height = _positive_int(values, "height")
    cell_count = _positive_int(values, "cell_count")
    sample_count = _positive_int(values, "sample_count")
    if values.get("subdivisions") != "2":
        raise VerifyFailure(f"navigation subdivision mismatch: {values}")
    if cell_count != width * height or sample_count != cell_count * 4:
        raise VerifyFailure(f"navigation grid/sample shape mismatch: {values}")
    for field in (
        "raw_addresses_absent",
        "segment_ok",
        "high_rejected",
        "fraction_rejected",
    ):
        if values.get(field) != "true":
            raise VerifyFailure(f"navigation contract failed {field}: {values}")
    if values.get("segment_type") != "boolean":
        raise VerifyFailure(f"navigation segment result was not boolean: {values}")
    return {"ok": True, "pipe": pipe_name, "values": values}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pipe", default=DEFAULT_PIPE)
    parser.add_argument("--timeout", type=float, default=12.0)
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
