#!/usr/bin/env python3
"""Verify runtime Lua sprite registration and live D3D9 rendering."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from PIL import Image

from multiplayer_frame_capture import capture_game_backbuffer
from verify_local_multiplayer_sync import VerifyFailure, lua, parse_key_values


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "runtime" / "lua_sprites_verification.json"
SCREENSHOT = ROOT / "runtime" / "lua_sprites_verification.png"
DEFAULT_PIPE = "SolomonDarkModLoader_LuaExec"
DEFAULT_IMAGE = "sprites/lab.png"
DEFAULT_BUNDLE = "sprites/lab.bundle"


def _lua_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def build_activation(image_path: str, bundle_path: str) -> str:
    image = _lua_string(image_path)
    bundle = _lua_string(bundle_path)
    return f'''
assert(type(sd.sprites) == "table", "missing sd.sprites")
for _, name in ipairs({{
  "register", "unregister", "get", "list", "get_limits",
}}) do
  assert(type(sd.sprites[name]) == "function", "missing sd.sprites." .. name)
end
assert(sd.runtime.has_capability("sprites.local.register"))
assert(sd.runtime.has_capability("sprites.local.read"))

if lua_sprites_acceptance_registered ~= true then
  lua_sprites_acceptance_registered = true
  lua_sprites_acceptance_active = false
  lua_sprites_acceptance_ticks = 0
  lua_sprites_acceptance_error = ""
  lua_sprites_acceptance_origin_x = 0
  lua_sprites_acceptance_origin_y = 0

  sd.events.on("runtime.tick", function()
    if lua_sprites_acceptance_active ~= true then return end
    local ok, err = pcall(function()
      lua_sprites_acceptance_ticks = lua_sprites_acceptance_ticks + 1
      local viewport = assert(sd.draw.get_viewport())
      local origin_x = math.max(0, viewport.width - 200)
      local origin_y = math.max(0, viewport.height - 200)
      lua_sprites_acceptance_origin_x = origin_x
      lua_sprites_acceptance_origin_y = origin_y
      sd.draw.rect(origin_x + 8, origin_y + 8, 184, 184, {{
        color = {{r = 231, g = 19, b = 173, a = 255}},
      }})
      sd.draw.sprite(
        lua_sprites_acceptance_atlas.id,
        0,
        origin_x + 100,
        origin_y + 100,
        {{centered = true, width = 128, height = 128}})
    end)
    if not ok then
      lua_sprites_acceptance_error = tostring(err)
      lua_sprites_acceptance_active = false
    end
  end)
end

lua_sprites_acceptance_active = false
pcall(sd.sprites.unregister, "acceptance")

local image = {image}
local bundle = {bundle}
local traversal_ok = pcall(
  sd.sprites.register, "bad_traversal", "../escape.png", bundle)
local absolute_ok = pcall(
  sd.sprites.register, "bad_absolute", "/escape.png", bundle)
local image_extension_ok = pcall(
  sd.sprites.register, "bad_image_extension", "sprites/nope.txt", bundle)
local bundle_extension_ok = pcall(
  sd.sprites.register, "bad_bundle_extension", image, "sprites/nope.txt")
local bad_key_ok = pcall(sd.sprites.register, "BadKey", image, bundle)
local extra_register_ok = pcall(
  sd.sprites.register, "extra", image, bundle, true)
local extra_list_ok = pcall(sd.sprites.list, true)
local extra_limits_ok = pcall(sd.sprites.get_limits, true)

local first = sd.sprites.register("acceptance", image, bundle)
assert(type(first) == "table" and first.frame_count > 0)
local second = sd.sprites.register("acceptance", image, bundle)
assert(second.id == first.id and second.revision > first.revision)
assert(second.key == "acceptance" and second.image == image)
assert(second.bundle == bundle and second.local_only == true)
assert(type(second.image_width) == "number" and second.image_width > 0)
assert(type(second.image_height) == "number" and second.image_height > 0)
assert(second.canonical_path == nil and second.native_pointer == nil)

local found = assert(sd.sprites.get("acceptance"))
assert(found.id == second.id and found.revision == second.revision)
assert(sd.sprites.get("missing") == nil)
local listed = false
for _, atlas in ipairs(sd.sprites.list()) do
  if atlas.id == second.id and atlas.revision == second.revision then
    listed = true
  end
end
assert(listed)

local limits = sd.sprites.get_limits()
assert(limits.atlases_per_mod == 32)
assert(limits.global_atlases == 128)
assert(limits.frames_per_atlas == 4096)
assert(limits.global_frames == 32768)
assert(limits.relative_path_bytes == 512)
assert(limits.atlas_id_bytes == 257)
assert(limits.image_bytes == 67108864)
assert(limits.bundle_bytes == 16777216)
assert(limits.image_dimension == 4096)
assert(limits.frame_geometry == 16384)

local frame = assert(sd.draw.get_sprite_info(second.id, 0))
assert(frame.atlas == second.id and frame.record == 0)
assert(frame.rotated == false)
assert(frame.packed_width > 0 and frame.packed_height > 0)

lua_sprites_acceptance_atlas = second
lua_sprites_acceptance_ticks = 0
lua_sprites_acceptance_error = ""
lua_sprites_acceptance_active = true

local mod = sd.runtime.get_mod()
print("owner_mod_id=" .. tostring(mod.id))
print("atlas_id=" .. second.id)
print("frame_count=" .. tostring(second.frame_count))
print("initial_revision=" .. tostring(first.revision))
print("replacement_revision=" .. tostring(second.revision))
print("traversal_rejected=" .. tostring(not traversal_ok))
print("absolute_rejected=" .. tostring(not absolute_ok))
print("image_extension_rejected=" .. tostring(not image_extension_ok))
print("bundle_extension_rejected=" .. tostring(not bundle_extension_ok))
print("bad_key_rejected=" .. tostring(not bad_key_ok))
print("extra_register_rejected=" .. tostring(not extra_register_ok))
print("extra_list_rejected=" .. tostring(not extra_list_ok))
print("extra_limits_rejected=" .. tostring(not extra_limits_ok))
print("schema_valid=true")
print("draw_lookup_valid=true")
'''


STATUS = r'''
local viewport, viewport_error = sd.draw.get_viewport()
print("ticks=" .. tostring(lua_sprites_acceptance_ticks or 0))
print("error=" .. tostring(lua_sprites_acceptance_error or ""))
print("viewport_width=" .. tostring(viewport and viewport.width or 0))
print("viewport_height=" .. tostring(viewport and viewport.height or 0))
print("viewport_error=" .. tostring(viewport_error or ""))
print("origin_x=" .. tostring(lua_sprites_acceptance_origin_x or 0))
print("origin_y=" .. tostring(lua_sprites_acceptance_origin_y or 0))
'''

CLEANUP = r'''
lua_sprites_acceptance_active = false
lua_sprites_acceptance_atlas = nil
return sd.sprites.unregister("acceptance")
'''


def _as_int(values: dict[str, str], name: str) -> int:
    try:
        return int(values.get(name, "0"))
    except ValueError as error:
        raise VerifyFailure(
            f"Lua sprites returned non-integer {name}: {values.get(name)!r}"
        ) from error


def _near(
    pixel: tuple[int, int, int],
    target: tuple[int, int, int],
    tolerance: int,
) -> bool:
    return all(
        abs(actual - expected) <= tolerance
        for actual, expected in zip(pixel, target)
    )


def _pixels(image: Image.Image) -> Any:
    flattened = getattr(image, "get_flattened_data", None)
    return flattened() if flattened is not None else image.getdata()


def inspect_sprite_pixels(path: Path, origin_x: int, origin_y: int) -> dict[str, int]:
    magenta = (231, 19, 173)
    with Image.open(path) as source:
        image = source.convert("RGB")
        if image.width < 200 or image.height < 200:
            raise VerifyFailure(
                f"Lua sprites verifier needs at least a 200x200 viewport; got "
                f"{image.width}x{image.height}"
            )
        if (
            origin_x < 0
            or origin_y < 0
            or origin_x + 200 > image.width
            or origin_y + 200 > image.height
        ):
            raise VerifyFailure(
                f"Lua sprites reported invalid origin ({origin_x}, {origin_y}) for "
                f"{image.width}x{image.height}"
            )

        panel = image.crop(
            (origin_x + 8, origin_y + 8, origin_x + 192, origin_y + 192)
        )
        sprite = image.crop(
            (origin_x + 36, origin_y + 36, origin_x + 164, origin_y + 164)
        )
        magenta_pixels = sum(
            1 for pixel in _pixels(panel) if _near(pixel, magenta, 16)
        )
        sprite_non_backdrop_pixels = sum(
            1 for pixel in _pixels(sprite) if not _near(pixel, magenta, 16)
        )

    counts = {
        "magenta_backdrop_pixels": magenta_pixels,
        "sprite_non_backdrop_pixels": sprite_non_backdrop_pixels,
    }
    if magenta_pixels < 2000 or sprite_non_backdrop_pixels < 64:
        raise VerifyFailure(f"Lua sprite pixels did not satisfy acceptance: {counts}")
    return counts


def wait_for_sprite(pipe_name: str, timeout: float) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = parse_key_values(lua(pipe_name, STATUS, timeout=10.0))
        if last.get("error"):
            raise VerifyFailure(f"Lua sprites draw handler failed: {last['error']}")
        if _as_int(last, "ticks") >= 2:
            return last
        time.sleep(0.1)
    raise VerifyFailure(f"Lua sprites handler did not complete two ticks: {last}")


def run(
    pipe_name: str,
    image_path: str,
    bundle_path: str,
    screenshot: Path,
    *,
    game_path_kind: str,
    timeout: float,
    expected_mod_id: str | None,
) -> dict[str, Any]:
    activation = parse_key_values(
        lua(pipe_name, build_activation(image_path, bundle_path), timeout=12.0)
    )
    required_true = (
        "traversal_rejected",
        "absolute_rejected",
        "image_extension_rejected",
        "bundle_extension_rejected",
        "bad_key_rejected",
        "extra_register_rejected",
        "extra_list_rejected",
        "extra_limits_rejected",
        "schema_valid",
        "draw_lookup_valid",
    )
    failures = [name for name in required_true if activation.get(name) != "true"]
    if failures:
        raise VerifyFailure(f"Lua sprites contract failed {failures}: {activation}")
    if expected_mod_id is not None and activation.get("owner_mod_id") != expected_mod_id:
        raise VerifyFailure(
            f"Lua exec owns {activation.get('owner_mod_id')!r}, expected "
            f"{expected_mod_id!r}"
        )
    if _as_int(activation, "frame_count") < 1:
        raise VerifyFailure(f"Lua sprites returned no frames: {activation}")
    if _as_int(activation, "replacement_revision") <= _as_int(
        activation, "initial_revision"
    ):
        raise VerifyFailure(f"Lua sprites replacement did not advance: {activation}")

    status = wait_for_sprite(pipe_name, timeout)
    viewport_width = _as_int(status, "viewport_width")
    viewport_height = _as_int(status, "viewport_height")
    if viewport_width < 200 or viewport_height < 200:
        raise VerifyFailure(
            f"Lua sprites viewport is too small: {viewport_width}x{viewport_height}"
        )

    capture = capture_game_backbuffer(
        pipe_name,
        screenshot,
        game_path_kind=game_path_kind,
    )
    pixels = inspect_sprite_pixels(
        screenshot,
        _as_int(status, "origin_x"),
        _as_int(status, "origin_y"),
    )
    return {
        "ok": True,
        "pipe": pipe_name,
        "image": image_path,
        "bundle": bundle_path,
        "activation": activation,
        "status": status,
        "capture": capture,
        "pixels": pixels,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pipe", default=DEFAULT_PIPE)
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    parser.add_argument("--bundle", default=DEFAULT_BUNDLE)
    parser.add_argument("--expected-mod-id")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--screenshot", type=Path, default=SCREENSHOT)
    parser.add_argument(
        "--game-path-kind",
        choices=("windows", "proton"),
        default="windows",
    )
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args()

    result: dict[str, Any] = {"ok": False, "pipe": args.pipe}
    try:
        result = run(
            args.pipe,
            args.image,
            args.bundle,
            args.screenshot,
            game_path_kind=args.game_path_kind,
            timeout=args.timeout,
            expected_mod_id=args.expected_mod_id,
        )
        return_code = 0
    except Exception as error:  # noqa: BLE001 - persist exact live evidence.
        result["error"] = str(error)
        return_code = 1
    finally:
        try:
            lua(args.pipe, CLEANUP, timeout=8.0)
        except Exception as cleanup_error:  # noqa: BLE001 - retain primary failure.
            result["cleanup_error"] = str(cleanup_error)

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
