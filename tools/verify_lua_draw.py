#!/usr/bin/env python3
"""Verify Lua immediate drawing through the live D3D9 backbuffer."""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any

from PIL import Image

from multiplayer_frame_capture import capture_game_backbuffer
from verify_local_multiplayer_sync import VerifyFailure, lua, parse_key_values


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "runtime" / "lua_draw_verification.json"
SCREENSHOT = ROOT / "runtime" / "lua_draw_verification.png"
DEFAULT_PIPE = "SolomonDarkModLoader_LuaExec"

ACTIVATE = r"""
if lua_draw_acceptance_registered ~= true then
  lua_draw_acceptance_registered = true
  lua_draw_acceptance_active = false
  lua_draw_acceptance_ticks = 0
  lua_draw_acceptance_error = ""
  lua_draw_acceptance_projection = nil
  lua_draw_acceptance_origin_y = 0

  sd.events.on("runtime.tick", function()
    if lua_draw_acceptance_active ~= true then
      return
    end
    local ok, err = pcall(function()
      lua_draw_acceptance_ticks = lua_draw_acceptance_ticks + 1
      local viewport = assert(sd.draw.get_viewport())
      local origin_y = math.max(0, viewport.height - 234)
      lua_draw_acceptance_origin_y = origin_y
      sd.draw.rect(24, origin_y, 576, 210, {
        color = {r = 7, g = 13, b = 29, a = 255},
      })
      sd.draw.text("LUA DRAW LIVE", 42, origin_y + 14, {
        scale = 1.25,
        color = {r = 255, g = 255, b = 255, a = 255},
      })
      sd.draw.rect(42, origin_y + 51, 120, 64, {
        color = {r = 17, g = 203, b = 71, a = 255},
      })
      sd.draw.rect(180, origin_y + 51, 120, 64, {
        filled = false,
        thickness = 5,
        color = {r = 255, g = 255, b = 255, a = 255},
      })
      sd.draw.line(42, origin_y + 151, 300, origin_y + 181, {
        thickness = 7,
        color = {r = 29, g = 211, b = 241, a = 255},
      })
      sd.draw.rect(350, origin_y + 46, 220, 104, {
        color = {r = 231, g = 19, b = 173, a = 255},
      })
      sd.draw.sprite("Title", 9, 460, origin_y + 98, {
        width = 200,
        height = 96,
        centered = true,
      })

      local player = sd.player.get_state()
      if type(player) == "table" then
        lua_draw_acceptance_projection = sd.draw.world_to_screen(player.x, player.y)
      end
    end)
    if not ok then
      lua_draw_acceptance_error = tostring(err)
      lua_draw_acceptance_active = false
    end
  end)
end

lua_draw_acceptance_ticks = 0
lua_draw_acceptance_error = ""
lua_draw_acceptance_projection = nil
lua_draw_acceptance_active = true

local limits = sd.draw.get_limits()
local sprite, sprite_error = sd.draw.get_sprite_info("title", 9)
print("alias=" .. tostring(sd.hud == sd.draw))
print("commands_per_mod_frame=" .. tostring(limits.commands_per_mod_frame))
print("text_bytes_per_mod_frame=" .. tostring(limits.text_bytes_per_mod_frame))
print("text_bytes_per_command=" .. tostring(limits.text_bytes_per_command))
print("stock_atlas_count=" .. tostring(limits.stock_atlas_count))
print("sprite_atlas=" .. tostring(sprite and sprite.atlas or ""))
print("sprite_record=" .. tostring(sprite and sprite.record or ""))
print("sprite_error=" .. tostring(sprite_error or ""))
"""

STATUS = r"""
local viewport, viewport_error = sd.draw.get_viewport()
local projection = lua_draw_acceptance_projection
print("ticks=" .. tostring(lua_draw_acceptance_ticks or 0))
print("error=" .. tostring(lua_draw_acceptance_error or ""))
print("viewport_width=" .. tostring(viewport and viewport.width or 0))
print("viewport_height=" .. tostring(viewport and viewport.height or 0))
print("viewport_error=" .. tostring(viewport_error or ""))
print("projected=" .. tostring(type(projection) == "table"))
print("projection_x=" .. tostring(projection and projection.x or 0))
print("projection_y=" .. tostring(projection and projection.y or 0))
print("projection_visible=" .. tostring(projection and projection.visible or false))
print("projection_generation=" .. tostring(projection and projection.generation or 0))
print("origin_y=" .. tostring(lua_draw_acceptance_origin_y or 0))
"""

CLEANUP = "lua_draw_acceptance_active = false; return true"


def _near(pixel: tuple[int, int, int], target: tuple[int, int, int], tolerance: int) -> bool:
    return all(abs(actual - expected) <= tolerance for actual, expected in zip(pixel, target))


def _count_near(
    image: Image.Image,
    bounds: tuple[int, int, int, int],
    target: tuple[int, int, int],
    tolerance: int = 12,
) -> int:
    return sum(
        1
        for pixel in _image_pixels(image.crop(bounds))
        if _near(pixel, target, tolerance)
    )


def _image_pixels(image: Image.Image) -> Any:
    flattened = getattr(image, "get_flattened_data", None)
    return flattened() if flattened is not None else image.getdata()


def inspect_acceptance_pixels(path: Path, origin_y: int) -> dict[str, int]:
    with Image.open(path) as source:
        image = source.convert("RGB")
        if image.width < 600 or image.height < 234:
            raise VerifyFailure(
                f"Lua draw verifier needs at least a 600x234 viewport; got "
                f"{image.width}x{image.height}"
            )

        if origin_y < 0 or origin_y + 210 > image.height:
            raise VerifyFailure(
                f"Lua draw reported invalid acceptance origin: y={origin_y} "
                f"height={image.height}"
            )
        green_pixels = _count_near(
            image,
            (46, origin_y + 55, 158, origin_y + 111),
            (17, 203, 71),
        )
        cyan_pixels = _count_near(
            image,
            (36, origin_y + 143, 306, origin_y + 189),
            (29, 211, 241),
        )
        white_text_pixels = _count_near(
            image,
            (38, origin_y + 10, 260, origin_y + 43),
            (255, 255, 255),
            20,
        )
        white_outline_pixels = _count_near(
            image,
            (176, origin_y + 47, 304, origin_y + 119),
            (255, 255, 255),
            20,
        )

        sprite_region = image.crop(
            (354, origin_y + 50, 566, origin_y + 146)
        )
        magenta = (231, 19, 173)
        sprite_pixels = sum(
            1
            for pixel in _image_pixels(sprite_region)
            if not _near(pixel, magenta, 16)
        )

    counts = {
        "green_fill_pixels": green_pixels,
        "cyan_line_pixels": cyan_pixels,
        "white_text_pixels": white_text_pixels,
        "white_outline_pixels": white_outline_pixels,
        "sprite_non_backdrop_pixels": sprite_pixels,
    }
    minimums = {
        "green_fill_pixels": 5000,
        "cyan_line_pixels": 700,
        "white_text_pixels": 60,
        "white_outline_pixels": 1000,
        "sprite_non_backdrop_pixels": 250,
    }
    failures = [
        f"{name}={counts[name]} minimum={minimum}"
        for name, minimum in minimums.items()
        if counts[name] < minimum
    ]
    if failures:
        raise VerifyFailure("Lua draw pixels did not satisfy: " + "; ".join(failures))
    return counts


def _as_int(values: dict[str, str], name: str) -> int:
    try:
        return int(values.get(name, "0"))
    except ValueError as exc:
        raise VerifyFailure(f"Lua draw returned non-integer {name}: {values.get(name)!r}") from exc


def _as_float(values: dict[str, str], name: str) -> float:
    try:
        value = float(values.get(name, "nan"))
    except ValueError as exc:
        raise VerifyFailure(f"Lua draw returned non-numeric {name}: {values.get(name)!r}") from exc
    if not math.isfinite(value):
        raise VerifyFailure(f"Lua draw returned non-finite {name}: {values.get(name)!r}")
    return value


def wait_for_draw(pipe_name: str, timeout: float) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = parse_key_values(lua(pipe_name, STATUS, timeout=10.0))
        if last.get("error"):
            raise VerifyFailure(f"Lua draw handler failed: {last['error']}")
        if _as_int(last, "ticks") >= 2:
            return last
        time.sleep(0.1)
    raise VerifyFailure(f"Lua draw handler did not complete two ticks: {last}")


def capture_acceptance_frame(
    pipe_name: str,
    screenshot: Path,
    *,
    game_path_kind: str,
    origin_y: int,
    timeout: float,
) -> tuple[dict[str, Any], dict[str, int]]:
    """Wait until the committed display list reaches the D3D9 render callback."""

    deadline = time.monotonic() + timeout
    while True:
        capture = capture_game_backbuffer(
            pipe_name,
            screenshot,
            game_path_kind=game_path_kind,
        )
        try:
            pixels = inspect_acceptance_pixels(screenshot, origin_y)
        except VerifyFailure:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.05)
            continue
        return capture, pixels


def run(
    pipe_name: str,
    screenshot: Path,
    *,
    game_path_kind: str,
    timeout: float,
    require_world_projection: bool,
) -> dict[str, Any]:
    activation = parse_key_values(lua(pipe_name, ACTIVATE, timeout=12.0))
    expected = {
        "alias": "true",
        "commands_per_mod_frame": "512",
        "text_bytes_per_mod_frame": "16384",
        "text_bytes_per_command": "1024",
        "stock_atlas_count": "28",
        "sprite_atlas": "Title",
        "sprite_record": "9",
        "sprite_error": "",
    }
    mismatches = {
        key: {"expected": expected_value, "actual": activation.get(key)}
        for key, expected_value in expected.items()
        if activation.get(key) != expected_value
    }
    if mismatches:
        raise VerifyFailure(f"Lua draw API contract mismatch: {mismatches}")

    status = wait_for_draw(pipe_name, timeout)
    viewport_width = _as_int(status, "viewport_width")
    viewport_height = _as_int(status, "viewport_height")
    origin_y = _as_int(status, "origin_y")
    if viewport_width < 600 or viewport_height < 234:
        raise VerifyFailure(
            f"Lua draw viewport is too small: {viewport_width}x{viewport_height}"
        )

    projection: dict[str, Any] = {
        "available": status.get("projected") == "true",
        "visible": status.get("projection_visible") == "true",
        "generation": _as_int(status, "projection_generation"),
    }
    if projection["available"]:
        projection["x"] = _as_float(status, "projection_x")
        projection["y"] = _as_float(status, "projection_y")
        projection["inside_viewport"] = (
            0.0 <= projection["x"] <= viewport_width
            and 0.0 <= projection["y"] <= viewport_height
        )
    if require_world_projection and not (
        projection["available"]
        and projection["visible"]
        and projection.get("inside_viewport")
        and projection["generation"] > 0
    ):
        raise VerifyFailure(f"live gameplay world projection is unavailable: {projection}")

    capture, pixels = capture_acceptance_frame(
        pipe_name,
        screenshot,
        game_path_kind=game_path_kind,
        origin_y=origin_y,
        timeout=timeout,
    )
    return {
        "ok": True,
        "pipe": pipe_name,
        "activation": activation,
        "status": status,
        "projection": projection,
        "capture": capture,
        "pixels": pixels,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pipe", default=DEFAULT_PIPE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--screenshot", type=Path, default=SCREENSHOT)
    parser.add_argument(
        "--game-path-kind",
        choices=("windows", "proton"),
        default="windows",
    )
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument(
        "--allow-missing-world-projection",
        action="store_true",
        help="Permit menu-only validation without a rendered PlayerWizard scene.",
    )
    args = parser.parse_args()

    result: dict[str, Any] = {"ok": False}
    try:
        result = run(
            args.pipe,
            args.screenshot,
            game_path_kind=args.game_path_kind,
            timeout=args.timeout,
            require_world_projection=not args.allow_missing_world_projection,
        )
        return_code = 0
    except Exception as exc:  # noqa: BLE001 - persist exact live evidence.
        result["error"] = str(exc)
        return_code = 1
    finally:
        try:
            lua(args.pipe, CLEANUP, timeout=8.0)
        except Exception as cleanup_exc:  # noqa: BLE001 - retain primary failure.
            result["cleanup_error"] = str(cleanup_exc)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "ok": result.get("ok", False),
                "error": result.get("error"),
                "output": str(args.output),
                "screenshot": str(args.screenshot),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
