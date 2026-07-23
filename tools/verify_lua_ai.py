#!/usr/bin/env python3
"""Verify the Lua enemy-AI registration contract without launching the game."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from verify_local_multiplayer_sync import VerifyFailure, lua, parse_key_values


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "runtime" / "lua_ai_verification.json"
DEFAULT_PIPE = "SolomonDarkModLoader_LuaExec"
EXPECTED_CONTENT_ID = 6758053804871806748


PROBE = r'''
assert(sd.runtime.has_capability("ai.register"))
assert(sd.runtime.has_capability("ai.read"))
assert(type(sd.ai) == "table")
for _, name in ipairs({
  "register", "get_state", "list", "set_target",
  "set_move_goal", "stop", "clear",
}) do
  assert(type(sd.ai[name]) == "function", "missing sd.ai." .. name)
end

local found = nil
for _, enemy in ipairs(sd.enemies.list()) do
  if enemy.mod_id == "sample.lua.ai_boss_lab" and enemy.key == "grave_oracle" then
    assert(found == nil, "sample AI boss is registered more than once")
    found = enemy
  end
end
assert(found, "enable the Lua AI Boss Lab mod before verification")
assert(found.id == 6758053804871806748, "stable AI boss id differs")
assert(found.base == "skeleton_mage", "AI boss base differs")

local instances = sd.ai.list()
local schema_valid = true
local raw_internals_absent = true
for _, instance in ipairs(instances) do
  schema_valid = schema_valid and
      type(instance.network_actor_id) == "number" and
      type(instance.content_id) == "number" and
      type(instance.think_count) == "number" and
      type(instance.target_mode) == "string"
  for _, key in ipairs({
    "actor_address", "vtable", "callback_reference", "on_think",
    "registry_index", "native_function",
  }) do
    if instance[key] ~= nil then raw_internals_absent = false end
  end
end

local late_register_ok = pcall(sd.ai.register, {
  enemy = found.id,
  on_think = function() end,
})
local zero_state_ok = pcall(sd.ai.get_state, 0)
local fractional_state_ok = pcall(sd.ai.get_state, 1.5)

print("stable_id=" .. tostring(found.id))
print("schema_valid=" .. tostring(schema_valid))
print("raw_internals_absent=" .. tostring(raw_internals_absent))
print("late_registration_rejected=" .. tostring(not late_register_ok))
print("zero_id_rejected=" .. tostring(not zero_state_ok))
print("fractional_id_rejected=" .. tostring(not fractional_state_ok))
print("instance_count=" .. tostring(#instances))
'''


def run(pipe_name: str) -> dict[str, Any]:
    values = parse_key_values(lua(pipe_name, PROBE, timeout=12.0))
    for field in (
        "schema_valid",
        "raw_internals_absent",
        "late_registration_rejected",
        "zero_id_rejected",
        "fractional_id_rejected",
    ):
        if values.get(field) != "true":
            raise VerifyFailure(f"Lua AI contract failed {field}: {values}")
    if values.get("stable_id") != str(EXPECTED_CONTENT_ID):
        raise VerifyFailure(f"Lua AI stable id differs: {values}")
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
