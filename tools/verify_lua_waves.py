#!/usr/bin/env python3
"""Verify Lua wave intelligence without changing the live run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from verify_local_multiplayer_sync import VerifyFailure, lua, parse_key_values


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "runtime" / "lua_waves_verification.json"
DEFAULT_PIPE = "SolomonDarkModLoader_LuaExec"


PROBE = r'''
assert(sd.runtime.has_capability("waves.read"))
assert(sd.runtime.has_capability("waves.schedule.read"))
local state = assert(sd.waves.get_state(), "wave state unavailable")
local valid_phases = { idle=true, spawning=true, clearing=true, completed=true }
assert(valid_phases[state.phase], "unknown wave phase")
local spawned, alive, killed, planned = 0, 0, 0, 0
local previous_type = -1
for _, row in ipairs(state.composition) do
  assert(row.enemy_type > previous_type, "composition is not sorted")
  assert(row.spawned == row.alive + row.killed, "row totals differ")
  previous_type = row.enemy_type
  spawned = spawned + row.spawned
  alive = alive + row.alive
  killed = killed + row.killed
  planned = planned + row.planned
end
assert(spawned == state.spawned, "spawned aggregate differs")
assert(alive == state.alive, "alive aggregate differs")
assert(killed == state.killed, "killed aggregate differs")
assert(planned == state.planned, "planned aggregate differs")

local schedule = sd.waves.get_schedule(3)
local schedule_valid = true
local schedule_previous_wave = state.wave
for _, entry in ipairs(schedule) do
  local entry_planned = 0
  if entry.wave <= schedule_previous_wave or not entry.random_group_projection then
    schedule_valid = false
  end
  for _, row in ipairs(entry.composition) do
    entry_planned = entry_planned + row.planned
  end
  if entry_planned ~= entry.spawn_budget then schedule_valid = false end
  schedule_previous_wave = entry.wave
end

local raw_keys = {
  "spawner_address", "action_record_address", "arena_address", "world_address",
}
local raw_addresses_absent = true
for _, key in ipairs(raw_keys) do
  if state[key] ~= nil then raw_addresses_absent = false end
end
local zero_ok = pcall(sd.waves.get_schedule, 0)
local fraction_ok = pcall(sd.waves.get_schedule, 1.5)
local too_large_ok = pcall(sd.waves.get_schedule, 65)

print("wave=" .. tostring(state.wave))
print("phase=" .. tostring(state.phase))
print("planned=" .. tostring(state.planned))
print("spawned=" .. tostring(state.spawned))
print("alive=" .. tostring(state.alive))
print("killed=" .. tostring(state.killed))
print("remaining_to_spawn=" .. tostring(state.remaining_to_spawn))
print("composition_rows=" .. tostring(#state.composition))
print("schedule_rows=" .. tostring(#schedule))
print("schedule_valid=" .. tostring(schedule_valid))
print("raw_addresses_absent=" .. tostring(raw_addresses_absent))
print("zero_rejected=" .. tostring(not zero_ok))
print("fraction_rejected=" .. tostring(not fraction_ok))
print("too_large_rejected=" .. tostring(not too_large_ok))
'''


def run(pipe_name: str) -> dict[str, Any]:
    values = parse_key_values(lua(pipe_name, PROBE, timeout=12.0))
    for field in (
        "schedule_valid",
        "raw_addresses_absent",
        "zero_rejected",
        "fraction_rejected",
        "too_large_rejected",
    ):
        if values.get(field) != "true":
            raise VerifyFailure(f"wave contract failed {field}: {values}")
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
