#!/usr/bin/env python3
"""Verify the address-free authored sd.ui contract on a running loader."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops

from multiplayer_frame_capture import capture_game_backbuffer
from verify_local_multiplayer_sync import VerifyFailure, lua, parse_key_values


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "runtime" / "lua_ui_authoring_verification.json"
BASELINE_SCREENSHOT = ROOT / "runtime" / "lua_ui_authoring_baseline.png"
SCREENSHOT = ROOT / "runtime" / "lua_ui_authoring_verification.png"
DEFAULT_PIPE = "SolomonDarkModLoader_LuaExec"
SURFACE_BOUNDS = (0.2, 0.2, 0.8, 0.8)


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
local state = assert(sd.ui.get_authored_state(ui_verify_surface))
assert(state.id == "verify_surface" and state.visible == false)

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

print("surface_created_hidden=true")
print("unknown_field_rejected=" .. tostring(not unknown_ok))
print("bad_rect_rejected=" .. tostring(not bad_rect_ok))
print("bad_id_rejected=" .. tostring(not bad_id_ok))
print("bad_execution_rejected=" .. tostring(not bad_execution_ok))
print("foreign_handle_rejected=" .. tostring(not foreign_handle_ok))
'''


SHOW_PROBE = r'''
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

print("surface_state_valid=true")
'''


STATUS_PROBE = r'''
local state = assert(sd.ui.get_authored_state(ui_verify_surface))
print("callback_dispatched=" .. tostring(ui_verify_count == 1))
print("surface_visible=" .. tostring(state.visible == true))
print("element_count=" .. tostring(#state.elements))
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


CLEANUP_PROBE = r'''
if type(ui_verify_surface) == "number" then
  pcall(sd.ui.destroy, ui_verify_surface)
end
ui_verify_surface = nil
ui_verify_label = nil
ui_verify_button = nil
ui_verify_count = nil
return true
'''


def _require_true(values: dict[str, str], *names: str) -> None:
    for name in names:
        if values.get(name) != "true":
            raise VerifyFailure(f"Lua UI authoring contract failed {name}: {values}")


def _changed(pixel: tuple[int, int, int], threshold: int) -> bool:
    return max(pixel) >= threshold


def _image_pixels(image: Image.Image) -> Any:
    flattened = getattr(image, "get_flattened_data", None)
    return flattened() if flattened is not None else image.getdata()


def _count_changed(image: Image.Image, threshold: int) -> int:
    return sum(1 for pixel in _image_pixels(image) if _changed(pixel, threshold))


def inspect_native_ui_pixels(
    baseline_path: Path,
    visible_path: Path,
    *,
    surface_bounds: tuple[float, float, float, float] = SURFACE_BOUNDS,
    threshold: int = 18,
) -> dict[str, Any]:
    with Image.open(baseline_path) as baseline_source:
        baseline = baseline_source.convert("RGB")
    with Image.open(visible_path) as visible_source:
        visible = visible_source.convert("RGB")
    if baseline.size != visible.size:
        raise VerifyFailure(
            f"Lua UI captures differ in size: baseline={baseline.size} "
            f"visible={visible.size}"
        )

    width, height = visible.size
    x0 = max(0, min(width, round(surface_bounds[0] * width)))
    y0 = max(0, min(height, round(surface_bounds[1] * height)))
    x1 = max(x0, min(width, round(surface_bounds[2] * width)))
    y1 = max(y0, min(height, round(surface_bounds[3] * height)))
    roi_pixels = (x1 - x0) * (y1 - y0)
    total_pixels = width * height
    outside_pixels = total_pixels - roi_pixels
    if roi_pixels <= 0 or outside_pixels <= 0:
        raise VerifyFailure(
            f"Lua UI verifier has invalid surface bounds: {surface_bounds}"
        )

    difference = ImageChops.difference(baseline, visible)
    changed_inside = _count_changed(
        difference.crop((x0, y0, x1, y1)),
        threshold,
    )
    changed_outside = _count_changed(difference, threshold) - changed_inside

    inside_fraction = changed_inside / float(roi_pixels)
    outside_fraction = changed_outside / float(outside_pixels)
    minimum_changed = max(256, round(roi_pixels * 0.005))
    if (
        changed_inside < minimum_changed
        or inside_fraction - outside_fraction < 0.003
    ):
        raise VerifyFailure(
            "Lua UI native pixels were not localized to the authored surface: "
            f"inside={changed_inside}/{roi_pixels} ({inside_fraction:.5f}) "
            f"outside={changed_outside}/{outside_pixels} ({outside_fraction:.5f})"
        )
    return {
        "width": width,
        "height": height,
        "surface_pixel_bounds": [x0, y0, x1, y1],
        "changed_inside": changed_inside,
        "changed_outside": changed_outside,
        "inside_fraction": inside_fraction,
        "outside_fraction": outside_fraction,
        "threshold": threshold,
    }


def _wait_for_callback(pipe_name: str, timeout: float) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = parse_key_values(lua(pipe_name, STATUS_PROBE, timeout=12.0))
        if (
            last.get("callback_dispatched") == "true"
            and last.get("surface_visible") == "true"
            and last.get("element_count") == "3"
        ):
            return last
        time.sleep(0.05)
    raise VerifyFailure(f"Lua UI callback did not settle: {last}")


def run(
    pipe_name: str,
    baseline_screenshot: Path,
    screenshot: Path,
    *,
    game_path_kind: str,
    timeout: float,
) -> dict[str, Any]:
    needs_cleanup = True
    try:
        setup = parse_key_values(lua(pipe_name, SETUP_PROBE, timeout=12.0))
        _require_true(
            setup,
            "surface_created_hidden",
            "unknown_field_rejected",
            "bad_rect_rejected",
            "bad_id_rejected",
            "bad_execution_rejected",
            "foreign_handle_rejected",
        )
        baseline_capture = capture_game_backbuffer(
            pipe_name,
            baseline_screenshot,
            game_path_kind=game_path_kind,
        )
        shown = parse_key_values(lua(pipe_name, SHOW_PROBE, timeout=12.0))
        _require_true(shown, "surface_state_valid")
        status = _wait_for_callback(pipe_name, timeout)
        visible_capture = capture_game_backbuffer(
            pipe_name,
            screenshot,
            game_path_kind=game_path_kind,
        )
        pixels = inspect_native_ui_pixels(baseline_screenshot, screenshot)

        result = parse_key_values(lua(pipe_name, RESULT_PROBE, timeout=12.0))
        _require_true(
            result,
            "callback_dispatched",
            "hidden_state_valid",
            "destroyed_state_absent",
        )
        needs_cleanup = False
        return {
            "ok": True,
            "pipe": pipe_name,
            "setup": setup,
            "shown": shown,
            "status": status,
            "result": result,
            "baseline_capture": baseline_capture,
            "visible_capture": visible_capture,
            "pixels": pixels,
        }
    finally:
        if needs_cleanup:
            try:
                lua(pipe_name, CLEANUP_PROBE, timeout=12.0)
            except Exception:  # noqa: BLE001 - preserve the primary failure.
                pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pipe", default=DEFAULT_PIPE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument(
        "--baseline-screenshot",
        type=Path,
        default=BASELINE_SCREENSHOT,
    )
    parser.add_argument("--screenshot", type=Path, default=SCREENSHOT)
    parser.add_argument(
        "--game-path-kind",
        choices=("windows", "proton"),
        default="windows",
    )
    parser.add_argument("--timeout", type=float, default=12.0)
    args = parser.parse_args()

    try:
        result: dict[str, Any] = run(
            args.pipe,
            args.baseline_screenshot,
            args.screenshot,
            game_path_kind=args.game_path_kind,
            timeout=max(1.0, args.timeout),
        )
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
