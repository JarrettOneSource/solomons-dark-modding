#!/usr/bin/env python3
"""Verify deterministic Lua spell registration without casting a spell."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from verify_local_multiplayer_sync import VerifyFailure, lua, parse_key_values


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "runtime" / "lua_spells_verification.json"
DEFAULT_PIPE = "SolomonDarkModLoader_LuaExec"
EXPECTED_CONTENT_ID = 8348995147374483494


PROBE = r'''
assert(sd.runtime.has_capability("spells.register"))
assert(sd.runtime.has_capability("spells.read"))
assert(sd.runtime.has_capability("spells.cast.owner"))
assert(type(sd.spells.cast) == "function")
local expected_id = 8348995147374483494
local found = nil
for _, spell in ipairs(sd.spells.list()) do
  if spell.mod_id == "sample.lua.spells_registry_lab" and
      spell.key == "gravity_well" then
    assert(found == nil, "sample spell is registered more than once")
    found = spell
  end
end
assert(found, "enable the Lua Spells Registry Lab mod before verification")
assert(found.id == expected_id, "stable spell id differs")
assert(found.slot == "secondary", "spell slot differs")
assert(found.cfg.name == "Gravity Well", "spell name differs")
assert(found.cfg.mana_cost == 30 and found.cfg.radius == 180, "spell cfg differs")
assert(found.has_on_cast and found.has_on_tick and found.has_on_hit, "callback flags differ")

found.cfg.name = "mutated descriptor"
local by_id = assert(sd.spells.get(expected_id), "content-id lookup failed")
assert(by_id.cfg.name == "Gravity Well", "descriptor mutation changed registration")
assert(by_id.id == found.id and by_id.key == found.key, "lookup differs")
assert(sd.spells.get(4611686018427387904) == nil, "unknown content id resolved")

local forbidden = {
  "address", "actor_address", "config_address", "native_skill_id",
  "on_cast", "on_tick", "on_hit", "callback_reference",
}
local raw_internals_absent = true
for _, key in ipairs(forbidden) do
  if found[key] ~= nil then raw_internals_absent = false end
end
local zero_ok = pcall(sd.spells.get, 0)
local fraction_ok = pcall(sd.spells.get, 1.5)
local late_register_ok = pcall(sd.spells.register, {
  key = "late_spell",
  slot = "primary",
  cfg = {name = "Late Spell"},
  on_cast = function() end,
})

print("stable_id=" .. tostring(found.id))
print("descriptor_copy_isolated=" .. tostring(by_id.cfg.name == "Gravity Well"))
print("raw_internals_absent=" .. tostring(raw_internals_absent))
print("zero_rejected=" .. tostring(not zero_ok))
print("fraction_rejected=" .. tostring(not fraction_ok))
print("late_registration_rejected=" .. tostring(not late_register_ok))
'''


def run(pipe_name: str) -> dict[str, Any]:
    values = parse_key_values(lua(pipe_name, PROBE, timeout=12.0))
    for field in (
        "descriptor_copy_isolated",
        "raw_internals_absent",
        "zero_rejected",
        "fraction_rejected",
        "late_registration_rejected",
    ):
        if values.get(field) != "true":
            raise VerifyFailure(f"spell registry contract failed {field}: {values}")
    if values.get("stable_id") != str(EXPECTED_CONTENT_ID):
        raise VerifyFailure(f"spell registry stable id differs: {values}")
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
