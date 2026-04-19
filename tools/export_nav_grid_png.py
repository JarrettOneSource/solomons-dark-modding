#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
LUA_EXEC = ROOT / "tools" / "lua-exec.py"


def run_lua(code: str) -> str:
    result = subprocess.run(
        [sys.executable, str(LUA_EXEC), code],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20.0,
        check=False,
    )
    output = (result.stdout or "") + (result.stderr or "")
    if result.returncode != 0:
        raise RuntimeError(output.strip() or "lua-exec failed")
    return output


def parse_grid_dump(output: str) -> dict:
    data: dict[str, object] = {
        "cells": [],
        "player": None,
        "bot": None,
        "subdivisions": 1,
    }
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key == "width":
            data["width"] = int(value)
        elif key == "height":
            data["height"] = int(value)
        elif key == "cell_width":
            data["cell_width"] = float(value)
        elif key == "cell_height":
            data["cell_height"] = float(value)
        elif key == "probe_x":
            data["probe_x"] = float(value)
        elif key == "probe_y":
            data["probe_y"] = float(value)
        elif key == "subdivisions":
            data["subdivisions"] = int(value)
        elif key == "scene":
            data["scene"] = value
        elif key == "cell":
            gx, gy, cx, cy, traversable = value.split(",")
            data["cells"].append(
                {
                    "grid_x": int(gx),
                    "grid_y": int(gy),
                    "center_x": float(cx),
                    "center_y": float(cy),
                    "traversable": traversable == "1",
                    "samples": [],
                }
            )
        elif key == "sample":
            gx, gy, sx, sy, wx, wy, traversable = value.split(",")
            for cell in reversed(data["cells"]):
                if cell["grid_x"] == int(gx) and cell["grid_y"] == int(gy):
                    cell["samples"].append({
                        "sample_x": int(sx),
                        "sample_y": int(sy),
                        "world_x": float(wx),
                        "world_y": float(wy),
                        "traversable": traversable == "1",
                    })
                    break
        elif key == "player":
            x, y = value.split(",")
            data["player"] = {"x": float(x), "y": float(y)}
        elif key == "bot":
            x, y = value.split(",")
            data["bot"] = {"x": float(x), "y": float(y)}
    return data


def load_grid_data(subdivisions: int) -> dict:
    lua = r"""
local grid = sd.debug.get_nav_grid(8)
if type(grid) ~= 'table' then
  error('nav grid unavailable')
end
local scene = sd.world.get_scene()
print('scene=' .. tostring(scene and scene.name or 'nil'))
print('width=' .. tostring(grid.width))
print('height=' .. tostring(grid.height))
print('cell_width=' .. tostring(grid.cell_width))
print('cell_height=' .. tostring(grid.cell_height))
print('probe_x=' .. tostring(grid.probe_x))
print('probe_y=' .. tostring(grid.probe_y))
print('subdivisions=' .. tostring(grid.subdivisions))
for _, cell in ipairs(grid.cells or {}) do
  print(string.format(
    'cell=%d,%d,%.3f,%.3f,%d',
    tonumber(cell.grid_x) or -1,
    tonumber(cell.grid_y) or -1,
    tonumber(cell.center_x) or 0.0,
    tonumber(cell.center_y) or 0.0,
    cell.traversable and 1 or 0))
  for _, sample in ipairs(cell.samples or {}) do
    print(string.format(
      'sample=%d,%d,%d,%d,%.3f,%.3f,%d',
      tonumber(cell.grid_x) or -1,
      tonumber(cell.grid_y) or -1,
      tonumber(sample.sample_x) or -1,
      tonumber(sample.sample_y) or -1,
      tonumber(sample.world_x) or 0.0,
      tonumber(sample.world_y) or 0.0,
      sample.traversable and 1 or 0))
  end
end
local player = sd.player.get_state()
if type(player) == 'table' then
  print(string.format('player=%.3f,%.3f', tonumber(player.x) or 0.0, tonumber(player.y) or 0.0))
end
local bots = sd.bots.get_state()
if type(bots) == 'table' then
  for _, bot in ipairs(bots) do
    if type(bot) == 'table' and tostring(bot.name) == 'Lua Patrol Bot' then
      print(string.format('bot=%.3f,%.3f', tonumber(bot.x) or 0.0, tonumber(bot.y) or 0.0))
      break
    end
  end
end
""".strip()
    lua = lua.replace('sd.debug.get_nav_grid(8)', f'sd.debug.get_nav_grid({subdivisions})')
    return parse_grid_dump(run_lua(lua))


def grid_to_pixel(world_x: float, world_y: float, cell_width: float, cell_height: float, margin: int, cell_px: int) -> tuple[float, float]:
    px = margin + (world_x / cell_width) * cell_px
    py = margin + (world_y / cell_height) * cell_px
    return px, py


def draw_marker(draw: ImageDraw.ImageDraw, xy: tuple[float, float], color: tuple[int, int, int], label: str, font: ImageFont.ImageFont) -> None:
    x, y = xy
    r = 7
    draw.ellipse((x - r, y - r, x + r, y + r), fill=color, outline=(0, 0, 0), width=2)
    draw.text((x + 10, y - 8), label, fill=color, font=font)


def render_grid(data: dict, output_path: Path) -> None:
    width = int(data["width"])
    height = int(data["height"])
    cell_width = float(data["cell_width"])
    cell_height = float(data["cell_height"])
    cells = list(data["cells"])
    rows = max((int(cell["grid_x"]) for cell in cells), default=-1) + 1
    cols = max((int(cell["grid_y"]) for cell in cells), default=-1) + 1
    margin = 48
    cell_px = 80
    legend_height = 90
    image_width = margin * 2 + cols * cell_px
    image_height = margin * 2 + rows * cell_px + legend_height

    image = Image.new("RGB", (image_width, image_height), (24, 24, 28))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()

    subdivisions = int(data.get("subdivisions", 1) or 1)
    for cell in cells:
        row = int(cell["grid_x"])
        col = int(cell["grid_y"])
        left = margin + col * cell_px
        top = margin + row * cell_px
        right = left + cell_px
        bottom = top + cell_px
        coarse_fill = (76, 140, 84, 60) if cell["traversable"] else (125, 62, 62, 60)
        draw.rectangle((left, top, right, bottom), fill=coarse_fill, outline=(210, 210, 210), width=1)
        sub_px_x = cell_px / subdivisions
        sub_px_y = cell_px / subdivisions
        for sample in cell.get("samples", []):
            sx = int(sample["sample_x"])
            sy = int(sample["sample_y"])
            sub_left = left + sy * sub_px_x
            sub_top = top + sx * sub_px_y
            sub_right = sub_left + sub_px_x
            sub_bottom = sub_top + sub_px_y
            fill = (76, 180, 84) if sample["traversable"] else (140, 72, 72)
            draw.rectangle((sub_left, sub_top, sub_right, sub_bottom), fill=fill, outline=None)
        center_x = left + cell_px / 2
        center_y = top + cell_px / 2
        draw.text((left + 3, top + 3), f"{row},{col}", fill=(240, 240, 240), font=font)
        draw.ellipse((center_x - 2, center_y - 2, center_x + 2, center_y + 2), fill=(255, 255, 255))

    player = data.get("player")
    if isinstance(player, dict):
        draw_marker(
            draw,
            grid_to_pixel(player["x"], player["y"], cell_width, cell_height, margin, cell_px),
            (80, 180, 255),
            f"Player {player['x']:.1f},{player['y']:.1f}",
            font,
        )

    bot = data.get("bot")
    if isinstance(bot, dict):
        draw_marker(
            draw,
            grid_to_pixel(bot["x"], bot["y"], cell_width, cell_height, margin, cell_px),
            (255, 210, 80),
            f"Bot {bot['x']:.1f},{bot['y']:.1f}",
            font,
        )

    legend_top = margin + rows * cell_px + 12
    draw.text((margin, legend_top), f"Scene: {data.get('scene', 'unknown')}", fill=(240, 240, 240), font=font)
    draw.text((margin, legend_top + 16), f"Grid snapshot fields width={width}, height={height}; rendered rows={rows}, cols={cols}; cell size {cell_width:.1f} x {cell_height:.1f}, subdivisions {data.get('subdivisions', 1)}", fill=(220, 220, 220), font=font)
    draw.rectangle((margin, legend_top + 36, margin + 18, legend_top + 54), fill=(76, 180, 84), outline=(210, 210, 210))
    draw.text((margin + 26, legend_top + 36), "Walkable subcell sample", fill=(240, 240, 240), font=font)
    draw.rectangle((margin + 220, legend_top + 36, margin + 238, legend_top + 54), fill=(140, 72, 72), outline=(210, 210, 210))
    draw.text((margin + 246, legend_top + 36), "Blocked subcell sample", fill=(240, 240, 240), font=font)
    image.save(output_path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Export the current gameplay nav grid to a PNG.")
    parser.add_argument("--output", default="runtime/hub_nav_grid.png", help="Output PNG path relative to repo root.")
    parser.add_argument("--subdivisions", type=int, default=8, help="Samples per coarse cell edge.")
    args = parser.parse_args()

    output_path = (ROOT / args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data = load_grid_data(args.subdivisions)
    render_grid(data, output_path)
    print(f"wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
