#!/usr/bin/env python3
"""Verify Lua spell registration and its authored picker without casting."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from verify_local_multiplayer_sync import VerifyFailure, lua, parse_key_values


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "runtime" / "lua_spells_verification.json"
DEFAULT_PIPE = "SolomonDarkModLoader_LuaExec"
EXPECTED_CONTENT_ID = 8348995147374483494
PICKER_MOD_ID = "sample.lua.spells_registry_lab"


PROBE = r'''
assert(sd.runtime.has_capability("spells.register"))
assert(sd.runtime.has_capability("spells.read"))
assert(sd.runtime.has_capability("spells.cast.owner"))
assert(sd.runtime.has_capability("spells.effects.read"))
assert(sd.runtime.has_capability("spells.select.local"))
assert(type(sd.spells.cast) == "function")
assert(type(sd.spells.get_effects) == "function")
assert(type(sd.spells.select) == "function")
assert(type(sd.spells.clear_selection) == "function")
assert(type(sd.spells.get_selection) == "function")
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

local selected = sd.spells.select(expected_id, 8)
assert(selected.id == expected_id and selected.selected == true,
    "selected descriptor differs")
assert(selected.belt_slot == 8, "selected belt slot differs")
local selection = sd.spells.get_selection()
assert(selection.primary == nil, "unexpected registered primary selection")
assert(selection.secondary[8] and
    selection.secondary[8].id == expected_id and
    selection.secondary[8].belt_slot == 8,
    "secondary selection snapshot differs")
assert(sd.spells.clear_selection("secondary", 8) == true,
    "selected secondary was not cleared")
assert(sd.spells.get_selection().secondary[8] == nil,
    "cleared secondary selection remained visible")
local missing_belt_ok = pcall(sd.spells.select, expected_id)
local invalid_belt_ok = pcall(sd.spells.select, expected_id, 9)

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
local effect_snapshot_schema_valid = true
for _, effect in ipairs(sd.spells.get_effects()) do
  effect_snapshot_schema_valid = effect_snapshot_schema_valid and
      type(effect.effect_id) == "number" and
      type(effect.request_id) == "number" and
      type(effect.content_id) == "number" and
      type(effect.owner_participant_id) == "number" and
      type(effect.key) == "string" and
      type(effect.x) == "number" and type(effect.y) == "number" and
      type(effect.velocity_x) == "number" and
      type(effect.velocity_y) == "number" and
      type(effect.radius) == "number" and
      type(effect.age_ms) == "number" and
      type(effect.remaining_ms) == "number" and
      type(effect.local_owner) == "boolean"
end

print("stable_id=" .. tostring(found.id))
print("effect_snapshot_schema_valid=" .. tostring(effect_snapshot_schema_valid))
print("descriptor_copy_isolated=" .. tostring(by_id.cfg.name == "Gravity Well"))
print("raw_internals_absent=" .. tostring(raw_internals_absent))
print("zero_rejected=" .. tostring(not zero_ok))
print("fraction_rejected=" .. tostring(not fraction_ok))
print("late_registration_rejected=" .. tostring(not late_register_ok))
print("selection_round_trip=" .. tostring(
    not missing_belt_ok and not invalid_belt_ok and
    sd.spells.get_selection().secondary[8] == nil))
'''


PICKER_EQUIP_PROBE = r'''
local mod = assert(sd.runtime.get_mod())
assert(mod.id == "sample.lua.spells_registry_lab",
    "picker verification requires sample.lua.spells_registry_lab as the first loaded Lua mod")
local selection = sd.spells.get_selection()
if selection.secondary[1] ~= nil then
  assert(sd.spells.clear_selection("secondary", 1))
end
local ok, request = sd.ui.perform({
  surface_id = "spell_picker",
  action_id = "equip_gravity_well",
})
assert(ok == true and type(request) == "number" and request > 0,
    "visible spell picker equip action was not queued")
print("exec_target=" .. mod.id)
print("picker_visible=true")
print("equip_queued=true")
print("equip_request_id=" .. tostring(request))
'''


PICKER_CLEAR_PROBE = r'''
local selection = sd.spells.get_selection()
assert(selection.secondary[1] and
    selection.secondary[1].id == 8348995147374483494,
    "Gravity Well was not equipped before clear")
local ok, request = sd.ui.perform({
  surface_id = "spell_picker",
  action_id = "clear_gravity_well",
})
assert(ok == true and type(request) == "number" and request > 0,
    "visible spell picker clear action was not queued")
print("clear_queued=true")
print("clear_request_id=" .. tostring(request))
'''


PICKER_STATUS_PROBE = r'''
local selected = sd.spells.get_selection().secondary[1]
print("slot1_selected=" .. tostring(selected ~= nil))
print("slot1_content_id=" .. tostring(selected and selected.id or 0))
'''


PICKER_CLEANUP_PROBE = r'''
local mod = sd.runtime.get_mod()
if mod and mod.id == "sample.lua.spells_registry_lab" then
  local selected = sd.spells.get_selection().secondary[1]
  if selected ~= nil then
    sd.spells.clear_selection("secondary", 1)
  end
end
return true
'''


def _wait_for_picker_state(
    pipe_name: str,
    *,
    selected: bool,
    timeout: float,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = parse_key_values(lua(pipe_name, PICKER_STATUS_PROBE, timeout=12.0))
        is_selected = last.get("slot1_selected") == "true"
        content_matches = (
            last.get("slot1_content_id") == str(EXPECTED_CONTENT_ID)
            if selected
            else last.get("slot1_content_id") == "0"
        )
        if is_selected == selected and content_matches:
            return last
        time.sleep(0.05)
    expected = "equipped" if selected else "cleared"
    raise VerifyFailure(f"spell picker did not become {expected}: {last}")


def run(pipe_name: str, timeout: float = 12.0) -> dict[str, Any]:
    values = parse_key_values(lua(pipe_name, PROBE, timeout=12.0))
    for field in (
        "descriptor_copy_isolated",
        "effect_snapshot_schema_valid",
        "raw_internals_absent",
        "zero_rejected",
        "fraction_rejected",
        "late_registration_rejected",
        "selection_round_trip",
    ):
        if values.get(field) != "true":
            raise VerifyFailure(f"spell registry contract failed {field}: {values}")
    if values.get("stable_id") != str(EXPECTED_CONTENT_ID):
        raise VerifyFailure(f"spell registry stable id differs: {values}")

    try:
        equip = parse_key_values(lua(pipe_name, PICKER_EQUIP_PROBE, timeout=12.0))
        if (
            equip.get("exec_target") != PICKER_MOD_ID
            or equip.get("picker_visible") != "true"
            or equip.get("equip_queued") != "true"
        ):
            raise VerifyFailure(f"spell picker equip action failed: {equip}")
        equipped = _wait_for_picker_state(
            pipe_name,
            selected=True,
            timeout=timeout,
        )

        clear = parse_key_values(lua(pipe_name, PICKER_CLEAR_PROBE, timeout=12.0))
        if clear.get("clear_queued") != "true":
            raise VerifyFailure(f"spell picker clear action failed: {clear}")
        cleared = _wait_for_picker_state(
            pipe_name,
            selected=False,
            timeout=timeout,
        )
        return {
            "ok": True,
            "pipe": pipe_name,
            "values": values,
            "picker": {
                "equip": equip,
                "equipped": equipped,
                "clear": clear,
                "cleared": cleared,
            },
        }
    finally:
        try:
            lua(pipe_name, PICKER_CLEANUP_PROBE, timeout=12.0)
        except Exception:  # noqa: BLE001 - preserve the primary failure.
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pipe", default=DEFAULT_PIPE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--timeout", type=float, default=12.0)
    args = parser.parse_args()

    result: dict[str, Any] = {"ok": False, "pipe": args.pipe}
    try:
        result = run(args.pipe, timeout=max(1.0, args.timeout))
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
