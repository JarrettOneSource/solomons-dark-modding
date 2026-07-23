#!/usr/bin/env python3
"""Verify the address-free authored sd.ui contract on a running loader."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from verify_local_multiplayer_sync import VerifyFailure, lua, parse_key_values


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "runtime" / "lua_ui_authoring_verification.json"
DEFAULT_PIPE = "SolomonDarkModLoader_LuaExec"


SETUP_PROBE = r'''
assert(type(sd.ui) == "table", "missing sd.ui")
for _, name in ipairs({
  "create_surface", "create_panel", "create_label", "create_button",
  "show", "hide", "destroy", "set_text", "set_enabled", "focus",
  "get_authored_state",
}) do
  assert(type(sd.ui[name]) == "function", "missing sd.ui." .. name)
end
assert(sd.runtime.has_capability("ui.authoring.native"))
assert(sd.runtime.has_capability("ui.action.presentation"))
assert(sd.runtime.has_capability("ui.action.simulation.route"))

ui_verify_count = 0
ui_verify_surface = sd.ui.create_surface({
  id = "verify_surface", title = "Verifier",
  x = 0.2, y = 0.2, width = 0.6, height = 0.6,
})
local panel = sd.ui.create_panel(ui_verify_surface, {
  id = "panel", x = 0.05, y = 0.1, width = 0.9, height = 0.8,
})
ui_verify_label = sd.ui.create_label(panel, {
  id = "label", text = "before", x = 0.05, y = 0.1,
  width = 0.9, height = 0.15,
})
ui_verify_button = sd.ui.create_button(panel, {
  id = "activate", label = "Activate", x = 0.1, y = 0.5,
  width = 0.8, height = 0.2, execution = "presentation",
  on_activate = function(action)
    assert(action.surface_id == "verify_surface")
    assert(action.action_id == "activate")
    assert(action.execution == "presentation")
    assert(type(action.request_id) == "number" and action.request_id > 0)
    ui_verify_count = ui_verify_count + 1
  end,
})
assert(sd.ui.show(ui_verify_surface))
assert(sd.ui.set_text(ui_verify_label, "after"))
assert(sd.ui.set_enabled(ui_verify_button, false))
assert(sd.ui.set_enabled(ui_verify_button, true))
assert(sd.ui.focus(ui_verify_button))

local state = assert(sd.ui.get_authored_state(ui_verify_surface))
assert(state.id == "verify_surface" and state.visible == true)
assert(state.focused_handle == ui_verify_button)
assert(#state.elements == 3)
local ok, request = sd.ui.perform({
  surface_id = "verify_surface", action_id = "activate",
})
assert(ok == true and type(request) == "number" and request > 0)

local unknown_ok = pcall(sd.ui.create_surface, {
  id = "bad_unknown", title = "bad", mystery = true,
})
local bad_rect_ok = pcall(sd.ui.create_surface, {
  id = "bad_rect", title = "bad", x = 0.8, width = 0.4,
})
local bad_id_ok = pcall(sd.ui.create_surface, {id = "BAD ID"})
local bad_execution_ok = pcall(sd.ui.create_button, panel, {
  id = "bad_execution", label = "bad", execution = "remote",
  on_activate = function() end,
})
local foreign_handle_ok = pcall(sd.ui.set_text, 999999999, "bad")

print("surface_state_valid=true")
print("unknown_field_rejected=" .. tostring(not unknown_ok))
print("bad_rect_rejected=" .. tostring(not bad_rect_ok))
print("bad_id_rejected=" .. tostring(not bad_id_ok))
print("bad_execution_rejected=" .. tostring(not bad_execution_ok))
print("foreign_handle_rejected=" .. tostring(not foreign_handle_ok))
'''


RESULT_PROBE = r'''
local count = ui_verify_count
local hidden = sd.ui.hide(ui_verify_surface)
local state = assert(sd.ui.get_authored_state(ui_verify_surface))
local hidden_state_valid = hidden and state.visible == false
local destroyed = sd.ui.destroy(ui_verify_surface)
local destroyed_state_absent = sd.ui.get_authored_state(ui_verify_surface) == nil
ui_verify_surface = nil
ui_verify_label = nil
ui_verify_button = nil
ui_verify_count = nil
print("callback_dispatched=" .. tostring(count == 1))
print("hidden_state_valid=" .. tostring(hidden_state_valid))
print("destroyed_state_absent=" .. tostring(destroyed and destroyed_state_absent))
'''


def _require_true(values: dict[str, str], *names: str) -> None:
    for name in names:
        if values.get(name) != "true":
            raise VerifyFailure(f"Lua UI authoring contract failed {name}: {values}")


def run(pipe_name: str) -> dict[str, Any]:
    setup = parse_key_values(lua(pipe_name, SETUP_PROBE, timeout=12.0))
    _require_true(
        setup,
        "surface_state_valid",
        "unknown_field_rejected",
        "bad_rect_rejected",
        "bad_id_rejected",
        "bad_execution_rejected",
        "foreign_handle_rejected",
    )
    result = parse_key_values(lua(pipe_name, RESULT_PROBE, timeout=12.0))
    _require_true(
        result,
        "callback_dispatched",
        "hidden_state_valid",
        "destroyed_state_absent",
    )
    return {"ok": True, "pipe": pipe_name, "setup": setup, "result": result}


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
