#!/usr/bin/env python3
"""Verify the semantic Lua scene contract without changing the live scene."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from verify_local_multiplayer_sync import VerifyFailure, lua, parse_key_values


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "runtime" / "lua_scene_verification.json"
DEFAULT_PIPE = "SolomonDarkModLoader_LuaExec"


PROBE = r'''
assert(sd.runtime.has_capability("scene.read"))
assert(sd.runtime.has_capability("scene.switch.authority"))
local scene = assert(sd.scene.get_state(), "scene state unavailable")
local raw_keys = {
  "id", "scene_id", "world_id", "arena_id", "region_state_id",
  "gameplay_scene_address", "world_address", "arena_address", "region_state_address",
}
local raw_addresses_absent = true
for _, key in ipairs(raw_keys) do
  if scene[key] ~= nil then raw_addresses_absent = false end
end
local fraction_ok = pcall(sd.scene.switch_region, 1.5)
local negative_ok = pcall(sd.scene.switch_region, -1)
local too_large_ok = pcall(sd.scene.switch_region, 6)
print("kind=" .. tostring(scene.kind))
print("name=" .. tostring(scene.name))
print("region_index=" .. tostring(scene.region_index))
print("region_type_id=" .. tostring(scene.region_type_id))
print("transitioning=" .. tostring(scene.transitioning))
print("is_authority=" .. tostring(scene.is_authority))
print("raw_addresses_absent=" .. tostring(raw_addresses_absent))
print("fraction_rejected=" .. tostring(not fraction_ok))
print("negative_rejected=" .. tostring(not negative_ok))
print("too_large_rejected=" .. tostring(not too_large_ok))
'''


def run(pipe_name: str) -> dict[str, Any]:
    values = parse_key_values(lua(pipe_name, PROBE, timeout=12.0))
    for field in (
        "raw_addresses_absent",
        "fraction_rejected",
        "negative_rejected",
        "too_large_rejected",
    ):
        if values.get(field) != "true":
            raise VerifyFailure(f"scene contract failed {field}: {values}")
    if not values.get("kind") or not values.get("name"):
        raise VerifyFailure(f"scene labels were unavailable: {values}")
    return {"ok": True, "pipe": pipe_name, "values": values}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pipe", default=DEFAULT_PIPE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    result: dict[str, Any] = {"ok": False, "pipe": args.pipe}
    try:
        result = run(args.pipe)
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
