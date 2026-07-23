#!/usr/bin/env python3
"""Verify deterministic Lua enemy registration without spawning an actor."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from verify_local_multiplayer_sync import VerifyFailure, lua, parse_key_values


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "runtime" / "lua_enemies_verification.json"
DEFAULT_PIPE = "SolomonDarkModLoader_LuaExec"
EXPECTED_CONTENT_ID = 8726222830294414077


PROBE = r'''
assert(sd.runtime.has_capability("enemies.register"))
assert(sd.runtime.has_capability("enemies.read"))
local expected_id = 8726222830294414077
local found = nil
for _, enemy in ipairs(sd.enemies.list()) do
  if enemy.mod_id == "sample.lua.enemies_registry_lab" and
      enemy.key == "grave_tyrant" then
    assert(found == nil, "sample enemy is registered more than once")
    found = enemy
  end
end
assert(found, "enable the Lua Enemies Registry Lab mod before verification")
assert(found.id == expected_id, "stable enemy id differs")
assert(found.base == "skeleton" and found.native_type_id == 1001, "base differs")
assert(found.hp == 250 and found.speed == 2.5 and found.scale == 1.2, "defaults differ")
assert(found.loot == "gold", "loot policy differs")

local by_id = assert(sd.enemies.get(expected_id), "content-id lookup failed")
assert(by_id.id == found.id and by_id.key == found.key, "lookup differs")
assert(sd.enemies.get(4611686018427387904) == nil, "unknown content id resolved")

local forbidden = {
  "address", "actor_address", "config_address", "arena_address",
  "spawner_address", "config_pointer", "actor_pointer",
}
local raw_addresses_absent = true
for _, key in ipairs(forbidden) do
  if found[key] ~= nil then raw_addresses_absent = false end
end
local zero_ok = pcall(sd.enemies.get, 0)
local fraction_ok = pcall(sd.enemies.get, 1.5)
local late_register_ok = pcall(sd.enemies.register, {
  key="late_enemy", base="skeleton",
})

print("stable_id=" .. tostring(found.id))
print("raw_addresses_absent=" .. tostring(raw_addresses_absent))
print("zero_rejected=" .. tostring(not zero_ok))
print("fraction_rejected=" .. tostring(not fraction_ok))
print("late_registration_rejected=" .. tostring(not late_register_ok))
'''


def run(pipe_name: str) -> dict[str, Any]:
    values = parse_key_values(lua(pipe_name, PROBE, timeout=12.0))
    for field in (
        "raw_addresses_absent",
        "zero_rejected",
        "fraction_rejected",
        "late_registration_rejected",
    ):
        if values.get(field) != "true":
            raise VerifyFailure(f"enemy registry contract failed {field}: {values}")
    if values.get("stable_id") != str(EXPECTED_CONTENT_ID):
        raise VerifyFailure(f"enemy registry stable id differs: {values}")
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
