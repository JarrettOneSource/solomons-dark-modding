#!/usr/bin/env python3
"""Verify deterministic Lua item registration without changing inventory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from verify_local_multiplayer_sync import VerifyFailure, lua, parse_key_values


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "runtime" / "lua_items_verification.json"
DEFAULT_PIPE = "SolomonDarkModLoader_LuaExec"


PROBE = r'''
assert(sd.runtime.has_capability("items.register"))
assert(sd.runtime.has_capability("items.read"))
local expected_id = 5785942626980372610
local found = nil
for _, item in ipairs(sd.items.list()) do
  if item.mod_id == "sample.lua.items_registry_lab" and
      item.key == "pentaclostic_ring" then
    assert(found == nil, "sample item is registered more than once")
    found = item
  end
end
assert(found, "enable the Lua Items Registry Lab mod before verification")
assert(found.id == expected_id, "stable item id differs")
assert(found.name == "Pentaclostic Ring", "recipe name differs")
assert(found.type == "ring" and found.native_type_id == 7002, "recipe type differs")
assert(found.available and found.recipe_uid > 0, found.unavailable_reason or "recipe unavailable")

local by_id = assert(sd.items.get(expected_id), "content-id lookup failed")
assert(by_id.id == found.id and by_id.recipe_uid == found.recipe_uid, "lookup differs")
assert(sd.items.get(4611686018427387904) == nil, "unknown content id resolved")

local forbidden = {
  "address", "item_address", "recipe_address", "catalog_address",
  "recipe_pointer", "catalog_pointer",
}
local raw_addresses_absent = true
for _, key in ipairs(forbidden) do
  if found[key] ~= nil then raw_addresses_absent = false end
end
local zero_ok = pcall(sd.items.get, 0)
local fraction_ok = pcall(sd.items.get, 1.5)
local late_register_ok = pcall(sd.items.register, {
  key="late_item", name="Pentaclostic Ring", type="ring",
})

print("stable_id=" .. tostring(found.id))
print("recipe_uid=" .. tostring(found.recipe_uid))
print("available=" .. tostring(found.available))
print("raw_addresses_absent=" .. tostring(raw_addresses_absent))
print("zero_rejected=" .. tostring(not zero_ok))
print("fraction_rejected=" .. tostring(not fraction_ok))
print("late_registration_rejected=" .. tostring(not late_register_ok))
'''


def run(pipe_name: str) -> dict[str, Any]:
    values = parse_key_values(lua(pipe_name, PROBE, timeout=12.0))
    for field in (
        "available",
        "raw_addresses_absent",
        "zero_rejected",
        "fraction_rejected",
        "late_registration_rejected",
    ):
        if values.get(field) != "true":
            raise VerifyFailure(f"item registry contract failed {field}: {values}")
    if values.get("stable_id") != "5785942626980372610":
        raise VerifyFailure(f"item registry stable id differs: {values}")
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
