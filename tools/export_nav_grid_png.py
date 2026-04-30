#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
LUA_EXEC = ROOT / "tools" / "lua-exec.py"

ACTOR_TYPE_LABELS = {
    0x1: "Wizard",
    0x3E9: "Wave Enemy",
    0x7D7: "College Obstacle",
    0x7D8: "College Statue",
    0x1389: "Perk Witch",
    0x138A: "Student",
    0x138B: "Annalist",
    0x138C: "Potion Guy",
    0x138D: "Items Guy",
    0x138F: "Tyrannia",
    0x1390: "Teacher",
    0x1397: "GameNpc",
    0x1391: "Arena Enemy",
    0x1392: "Arena Enemy",
}

ACTOR_DUMP_LUA = r"""
local actors = sd.world and sd.world.list_actors and sd.world.list_actors() or nil
if type(actors) == 'table' then
  for _, actor in ipairs(actors) do
    local x = tonumber(actor.x) or 0.0
    local y = tonumber(actor.y) or 0.0
    print(string.format(
      'actor=%s,%d,%.3f,%.3f,%d,%d,%d,%d,%.3f,%.3f',
      tostring(actor.actor_address or 0),
      math.floor(tonumber(actor.object_type_id) or 0),
      x,
      y,
      math.floor(tonumber(actor.actor_slot) or -1),
      math.floor(tonumber(actor.world_slot) or -1),
      actor.dead and 1 or 0,
      actor.tracked_enemy and 1 or 0,
      tonumber(actor.hp) or 0.0,
      tonumber(actor.max_hp) or 0.0))
  end
end
""".strip()

HUB_PRIVATE_ROOM_ANCHORS = [
    {
        "key": "memorator",
        "label": "Memoratorium",
        "x": 87.480285644531,
        "y": 443.60046386719,
    },
    {
        "key": "librarian",
        "label": "Library",
        "x": 124.76531219482,
        "y": 496.97552490234,
    },
    {
        "key": "dowser",
        "label": "Storage",
        "x": 627.5,
        "y": 137.6875,
    },
    {
        "key": "polisher_arch",
        "label": "Office",
        "x": 952.5,
        "y": 106.6875,
    },
]

BOUNDARY_OPENING_COLOR = (82, 215, 255)
BOUNDARY_OPENING_TEXT_COLOR = (205, 246, 255)


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


def parse_int(value: str) -> int:
    try:
        return int(value, 0)
    except ValueError:
        return int(float(value))


def is_transient_grid_error(error: RuntimeError) -> bool:
    message = str(error)
    return (
        "nav grid unavailable" in message or
        "Lua engine is busy" in message or
        "engine is busy" in message
    )


def grid_matches_current_scene(data: dict) -> bool:
    scene_world_id = int(data.get("scene_world_id", 0) or 0)
    grid_world_address = int(data.get("grid_world_address", 0) or 0)
    return scene_world_id == 0 or grid_world_address == 0 or scene_world_id == grid_world_address


def parse_grid_dump(output: str) -> dict:
    data: dict[str, object] = {
        "actors": [],
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
        elif key == "scene_world_id":
            data["scene_world_id"] = parse_int(value)
        elif key == "grid_world_address":
            data["grid_world_address"] = parse_int(value)
        elif key == "grid_controller_address":
            data["grid_controller_address"] = parse_int(value)
        elif key == "grid_probe_actor_address":
            data["grid_probe_actor_address"] = parse_int(value)
        elif key == "cell":
            parts = value.split(",")
            gx, gy, cx, cy, traversable = parts[:5]
            path_traversable = parts[5] if len(parts) >= 6 else traversable
            data["cells"].append(
                {
                    "grid_x": int(gx),
                    "grid_y": int(gy),
                    "center_x": float(cx),
                    "center_y": float(cy),
                    "traversable": traversable == "1",
                    "path_traversable": path_traversable == "1",
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
        elif key == "actor":
            address, type_id, x, y, actor_slot, world_slot, dead, tracked_enemy, hp, max_hp = value.split(",")
            data["actors"].append(
                {
                    "actor_address": parse_int(address),
                    "object_type_id": parse_int(type_id),
                    "x": float(x),
                    "y": float(y),
                    "actor_slot": parse_int(actor_slot),
                    "world_slot": parse_int(world_slot),
                    "dead": dead == "1",
                    "tracked_enemy": tracked_enemy == "1",
                    "hp": float(hp),
                    "max_hp": float(max_hp),
                }
            )
    return data


def build_grid_dump_lua(subdivisions: int) -> str:
    return f"""
local requested_subdivisions = {max(1, int(subdivisions))}
local grid = sd.debug.get_nav_grid(requested_subdivisions)
if type(grid) ~= 'table' then
  error('nav grid unavailable')
end
local scene = sd.world.get_scene()
print('scene=' .. tostring(scene and scene.name or 'nil'))
print('scene_world_id=' .. tostring(scene and scene.world_id or 0))
print('width=' .. tostring(grid.width))
print('height=' .. tostring(grid.height))
print('cell_width=' .. tostring(grid.cell_width))
print('cell_height=' .. tostring(grid.cell_height))
print('grid_world_address=' .. tostring(grid.world_address or 0))
print('grid_controller_address=' .. tostring(grid.controller_address or 0))
print('grid_probe_actor_address=' .. tostring(grid.probe_actor_address or 0))
print('probe_x=' .. tostring(grid.probe_x))
print('probe_y=' .. tostring(grid.probe_y))
print('subdivisions=' .. tostring(grid.subdivisions))
for _, cell in ipairs(grid.cells or {{}}) do
  print(string.format(
    'cell=%d,%d,%.3f,%.3f,%d,%d',
    tonumber(cell.grid_x) or -1,
    tonumber(cell.grid_y) or -1,
    tonumber(cell.center_x) or 0.0,
    tonumber(cell.center_y) or 0.0,
    cell.traversable and 1 or 0,
    cell.path_traversable and 1 or 0))
  for _, sample in ipairs(cell.samples or {{}}) do
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
    if type(bot) == 'table' and tostring(bot.name or ''):match('^Lua Bot ') ~= nil then
      print(string.format('bot=%.3f,%.3f', tonumber(bot.x) or 0.0, tonumber(bot.y) or 0.0))
      break
    end
  end
end
{ACTOR_DUMP_LUA}
""".strip()


def build_grid_metadata_lua(subdivisions: int) -> str:
    return f"""
local requested_subdivisions = {max(1, int(subdivisions))}
local grid = sd.debug.get_nav_grid(requested_subdivisions)
if type(grid) ~= 'table' then
  error('nav grid unavailable')
end
local scene = sd.world.get_scene()
print('scene=' .. tostring(scene and scene.name or 'nil'))
print('scene_world_id=' .. tostring(scene and scene.world_id or 0))
print('width=' .. tostring(grid.width))
print('height=' .. tostring(grid.height))
print('cell_width=' .. tostring(grid.cell_width))
print('cell_height=' .. tostring(grid.cell_height))
print('grid_world_address=' .. tostring(grid.world_address or 0))
print('grid_controller_address=' .. tostring(grid.controller_address or 0))
print('grid_probe_actor_address=' .. tostring(grid.probe_actor_address or 0))
print('probe_x=' .. tostring(grid.probe_x))
print('probe_y=' .. tostring(grid.probe_y))
print('subdivisions=' .. tostring(grid.subdivisions))
for _, cell in ipairs(grid.cells or {{}}) do
  print(string.format(
    'cell=%d,%d,%.3f,%.3f,%d,%d',
    tonumber(cell.grid_x) or -1,
    tonumber(cell.grid_y) or -1,
    tonumber(cell.center_x) or 0.0,
    tonumber(cell.center_y) or 0.0,
    cell.traversable and 1 or 0,
    cell.path_traversable and 1 or 0))
end
local player = sd.player.get_state()
if type(player) == 'table' then
  print(string.format('player=%.3f,%.3f', tonumber(player.x) or 0.0, tonumber(player.y) or 0.0))
end
local bots = sd.bots.get_state()
if type(bots) == 'table' then
  for _, bot in ipairs(bots) do
    if type(bot) == 'table' and tostring(bot.name or ''):match('^Lua Bot ') ~= nil then
      print(string.format('bot=%.3f,%.3f', tonumber(bot.x) or 0.0, tonumber(bot.y) or 0.0))
      break
    end
  end
end
{ACTOR_DUMP_LUA}
""".strip()


def build_grid_samples_lua(subdivisions: int, first_cell: int, last_cell: int) -> str:
    return f"""
local requested_subdivisions = {max(1, int(subdivisions))}
local first_cell = {max(1, int(first_cell))}
local last_cell = {max(1, int(last_cell))}
local grid = sd.debug.get_nav_grid(requested_subdivisions)
if type(grid) ~= 'table' then
  error('nav grid unavailable')
end
for cell_index = first_cell, math.min(last_cell, #(grid.cells or {{}})) do
  local cell = grid.cells[cell_index]
  if type(cell) == 'table' then
    for _, sample in ipairs(cell.samples or {{}}) do
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
end
""".strip()


def append_sample_dump(data: dict, output: str) -> None:
    cells_by_key = {
        (int(cell["grid_x"]), int(cell["grid_y"])): cell
        for cell in data.get("cells", [])
        if isinstance(cell, dict)
    }
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line.startswith("sample="):
            continue
        value = line.split("=", 1)[1]
        gx, gy, sx, sy, wx, wy, traversable = value.split(",")
        cell = cells_by_key.get((int(gx), int(gy)))
        if cell is None:
            continue
        cell["samples"].append({
            "sample_x": int(sx),
            "sample_y": int(sy),
            "world_x": float(wx),
            "world_y": float(wy),
            "traversable": traversable == "1",
        })


def load_grid_data(subdivisions: int) -> dict:
    requested_subdivisions = max(1, subdivisions)
    if requested_subdivisions >= 8:
        return load_grid_data_chunked(requested_subdivisions)

    lua = build_grid_dump_lua(requested_subdivisions)
    last_data: dict | None = None
    # sd.debug.get_nav_grid() returns the last gameplay-thread snapshot and
    # queues the requested rebuild. Retry briefly so exports are the requested
    # sampling density rather than a stale lower-resolution snapshot.
    for attempt in range(8):
        try:
            data = parse_grid_dump(run_lua(lua))
        except RuntimeError as exc:
            if is_transient_grid_error(exc) and attempt < 7:
                time.sleep(0.25 if attempt == 0 else 0.6)
                continue
            raise
        last_data = data
        if int(data.get("subdivisions", 0) or 0) >= requested_subdivisions and grid_matches_current_scene(data):
            return data
        time.sleep(0.25 if attempt == 0 else 0.6)
    if last_data is not None and not grid_matches_current_scene(last_data):
        raise RuntimeError(
            "nav grid snapshot is stale: "
            f"scene_world_id=0x{int(last_data.get('scene_world_id', 0) or 0):X} "
            f"grid_world_address=0x{int(last_data.get('grid_world_address', 0) or 0):X}"
        )
    return last_data or parse_grid_dump(run_lua(lua))


def load_grid_data_chunked(subdivisions: int) -> dict:
    requested_subdivisions = max(1, subdivisions)
    metadata_lua = build_grid_metadata_lua(requested_subdivisions)
    data: dict | None = None
    for attempt in range(8):
        try:
            data = parse_grid_dump(run_lua(metadata_lua))
        except RuntimeError as exc:
            if is_transient_grid_error(exc) and attempt < 7:
                time.sleep(0.25 if attempt == 0 else 0.6)
                continue
            raise
        if int(data.get("subdivisions", 0) or 0) >= requested_subdivisions and grid_matches_current_scene(data):
            break
        time.sleep(0.25 if attempt == 0 else 0.6)
    if data is None:
        raise RuntimeError("nav grid metadata unavailable")
    if not grid_matches_current_scene(data):
        raise RuntimeError(
            "nav grid snapshot is stale: "
            f"scene_world_id=0x{int(data.get('scene_world_id', 0) or 0):X} "
            f"grid_world_address=0x{int(data.get('grid_world_address', 0) or 0):X}"
        )

    cell_count = len(data.get("cells", []))
    chunk_size = 8
    for first in range(1, cell_count + 1, chunk_size):
        last = min(cell_count, first + chunk_size - 1)
        sample_lua = build_grid_samples_lua(requested_subdivisions, first, last)
        for attempt in range(4):
            try:
                append_sample_dump(data, run_lua(sample_lua))
                break
            except RuntimeError as exc:
                if is_transient_grid_error(exc) and attempt < 3:
                    time.sleep(0.25 if attempt == 0 else 0.6)
                    continue
                raise
    return data


def grid_to_pixel(world_x: float, world_y: float, cell_width: float, cell_height: float, margin: int, cell_px: int) -> tuple[float, float]:
    px = margin + (world_x / cell_width) * cell_px
    py = margin + (world_y / cell_height) * cell_px
    return px, py


def load_font(size: int) -> ImageFont.ImageFont:
    for name in ("DejaVuSans.ttf", "Arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_marker(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    color: tuple[int, int, int],
    label: str,
    font: ImageFont.ImageFont,
    radius: int,
) -> None:
    x, y = xy
    r = radius
    draw.ellipse((x - r, y - r, x + r, y + r), fill=color, outline=(0, 0, 0), width=2)
    draw.text((x + r + 4, y - 8), label, fill=color, font=font)


def clamp_label_position(
    draw: ImageDraw.ImageDraw,
    label: str,
    font: ImageFont.ImageFont,
    x: float,
    y: float,
    image_width: int,
    image_height: int,
    *,
    pad_x: int = 6,
    pad_y: int = 4,
) -> tuple[float, float, float, float, int, int]:
    text_bbox = draw.textbbox((0, 0), label, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    label_x = x
    label_y = y
    if label_x + text_width + pad_x * 2 > image_width - 8:
        label_x = image_width - text_width - pad_x * 2 - 8
    if label_x < 8:
        label_x = 8
    if label_y + text_height + pad_y * 2 > image_height - 8:
        label_y = image_height - text_height - pad_y * 2 - 8
    if label_y < 8:
        label_y = 8
    return (
        label_x,
        label_y,
        label_x + text_width + pad_x * 2,
        label_y + text_height + pad_y * 2,
        text_width,
        text_height,
    )


def actor_type_label(type_id: int) -> str:
    return ACTOR_TYPE_LABELS.get(type_id, f"Actor 0x{type_id:X}")


def actor_color(type_id: int) -> tuple[int, int, int]:
    if type_id == 0x1:
        return (80, 180, 255)
    if type_id == 0x138A:
        return (90, 220, 210)
    if type_id in {0x1389, 0x138B, 0x138C, 0x138D, 0x138F, 0x1390}:
        return (255, 178, 88)
    if type_id in {0x7D7, 0x7D8}:
        return (190, 190, 200)
    if type_id in {0x3E9, 0x1391, 0x1392}:
        return (255, 96, 96)
    return (236, 236, 236)


def prepare_actor_overlays(data: dict, include_player_family: bool) -> list[dict]:
    actors = [
        actor for actor in data.get("actors", [])
        if isinstance(actor, dict)
    ]
    filtered = []
    for actor in actors:
        type_id = int(actor.get("object_type_id", 0) or 0)
        if not include_player_family and type_id == 0x1:
            continue
        filtered.append(actor)

    filtered.sort(
        key=lambda actor: (
            int(actor.get("object_type_id", 0) or 0),
            float(actor.get("y", 0.0) or 0.0),
            float(actor.get("x", 0.0) or 0.0),
            int(actor.get("actor_address", 0) or 0),
        )
    )

    total_by_label: dict[str, int] = {}
    for actor in filtered:
        label = actor_type_label(int(actor.get("object_type_id", 0) or 0))
        total_by_label[label] = total_by_label.get(label, 0) + 1

    seen_by_label: dict[str, int] = {}
    overlays = []
    for actor in filtered:
        type_id = int(actor.get("object_type_id", 0) or 0)
        base_label = actor_type_label(type_id)
        seen_by_label[base_label] = seen_by_label.get(base_label, 0) + 1
        label = (
            f"{base_label} {seen_by_label[base_label]}"
            if total_by_label.get(base_label, 0) > 1
            else base_label
        )
        overlays.append({**actor, "label": label, "color": actor_color(type_id)})
    return overlays


def draw_actor_label(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    label: str,
    color: tuple[int, int, int],
    font: ImageFont.ImageFont,
    image_width: int,
    image_height: int,
    marker_radius: int,
    label_index: int,
) -> None:
    x, y = xy
    draw.ellipse(
        (x - marker_radius, y - marker_radius, x + marker_radius, y + marker_radius),
        fill=color,
        outline=(0, 0, 0),
        width=2,
    )

    stagger = label_index % 6
    label_x = x + marker_radius + 4
    label_y = y - 10 + (stagger - 2) * 8
    box_left, box_top, box_right, box_bottom, _, _ = clamp_label_position(
        draw,
        label,
        font,
        label_x,
        label_y,
        image_width,
        image_height,
    )
    draw.rectangle((box_left, box_top, box_right, box_bottom), fill=(16, 16, 18), outline=color)
    draw.text((box_left + 6, box_top + 3), label, fill=color, font=font)
    draw.line((x, y, box_left, (box_top + box_bottom) / 2), fill=color, width=1)


def draw_entrance_label(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    label: str,
    font: ImageFont.ImageFont,
    image_width: int,
    image_height: int,
) -> None:
    x, y = xy
    radius = 10
    line_color = (245, 218, 98)
    text_color = (255, 246, 190)
    panel_fill = (18, 18, 20)
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), outline=line_color, width=3)
    draw.line((x - radius, y, x + radius, y), fill=line_color, width=2)
    draw.line((x, y - radius, x, y + radius), fill=line_color, width=2)

    text_bbox = draw.textbbox((0, 0), label, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    pad_x = 6
    pad_y = 4
    label_x = x + 14
    label_y = y - text_height - 10
    if label_x + text_width + pad_x * 2 > image_width - 8:
        label_x = x - text_width - pad_x * 2 - 14
    if label_y < 8:
        label_y = y + 12
    if label_y + text_height + pad_y * 2 > image_height - 8:
        label_y = image_height - text_height - pad_y * 2 - 8
    box = (
        label_x,
        label_y,
        label_x + text_width + pad_x * 2,
        label_y + text_height + pad_y * 2,
    )
    draw.rectangle(box, fill=panel_fill, outline=line_color)
    draw.text((label_x + pad_x, label_y + pad_y - 1), label, fill=text_color, font=font)
    draw.line((x, y - radius, label_x, label_y + (text_height + pad_y * 2) / 2), fill=line_color, width=1)


def should_draw_hub_overlay(data: dict, mode: str) -> bool:
    if mode == "never":
        return False
    if mode == "always":
        return True
    return str(data.get("scene", "")).lower() == "hub"


def detect_boundary_openings(data: dict) -> list[dict]:
    cells = [
        cell for cell in data.get("cells", [])
        if isinstance(cell, dict)
    ]
    if not cells:
        return []

    rows = max((int(cell["grid_x"]) for cell in cells), default=-1) + 1
    cols = max((int(cell["grid_y"]) for cell in cells), default=-1) + 1
    subdivisions = int(data.get("subdivisions", 1) or 1)
    if rows <= 0 or cols <= 0 or subdivisions <= 0:
        return []

    cell_width = float(data["cell_width"])
    cell_height = float(data["cell_height"])
    total_width = cols * cell_width
    total_height = rows * cell_height

    edge_slots: dict[str, set[int]] = {"top": set(), "bottom": set(), "left": set(), "right": set()}
    for cell in cells:
        row = int(cell["grid_x"])
        col = int(cell["grid_y"])
        for sample in cell.get("samples", []):
            if not bool(sample.get("traversable", False)):
                continue
            sample_x = int(sample["sample_x"])
            sample_y = int(sample["sample_y"])
            if row == 0 and sample_x == 0:
                edge_slots["top"].add(col * subdivisions + sample_y)
            if row == rows - 1 and sample_x == subdivisions - 1:
                edge_slots["bottom"].add(col * subdivisions + sample_y)
            if col == 0 and sample_y == 0:
                edge_slots["left"].add(row * subdivisions + sample_x)
            if col == cols - 1 and sample_y == subdivisions - 1:
                edge_slots["right"].add(row * subdivisions + sample_x)

    openings: list[dict] = []
    next_index = {edge: 1 for edge in edge_slots}
    for edge in ("top", "right", "bottom", "left"):
        slots = sorted(edge_slots[edge])
        run_start: int | None = None
        previous: int | None = None
        for slot in slots + [None]:
            if slot is not None and (previous is None or slot == previous + 1):
                if run_start is None:
                    run_start = slot
                previous = slot
                continue

            if run_start is not None and previous is not None:
                if edge in {"top", "bottom"}:
                    start_world = run_start * (cell_width / subdivisions)
                    end_world = (previous + 1) * (cell_width / subdivisions)
                    y = 0.0 if edge == "top" else total_height
                    opening = {
                        "edge": edge,
                        "index": next_index[edge],
                        "x": (start_world + end_world) * 0.5,
                        "y": y,
                        "start_x": start_world,
                        "start_y": y,
                        "end_x": end_world,
                        "end_y": y,
                        "span_units": end_world - start_world,
                    }
                else:
                    start_world = run_start * (cell_height / subdivisions)
                    end_world = (previous + 1) * (cell_height / subdivisions)
                    x = 0.0 if edge == "left" else total_width
                    opening = {
                        "edge": edge,
                        "index": next_index[edge],
                        "x": x,
                        "y": (start_world + end_world) * 0.5,
                        "start_x": x,
                        "start_y": start_world,
                        "end_x": x,
                        "end_y": end_world,
                        "span_units": end_world - start_world,
                    }
                openings.append(opening)
                next_index[edge] += 1

            run_start = slot
            previous = slot

    return openings


def boundary_opening_label(opening: dict) -> str:
    return f"{str(opening['edge']).title()} opening {int(opening['index'])}"


def draw_boundary_opening(
    draw: ImageDraw.ImageDraw,
    opening: dict,
    cell_width: float,
    cell_height: float,
    margin: int,
    cell_px: int,
    font: ImageFont.ImageFont,
    image_width: int,
    image_height: int,
) -> None:
    start = grid_to_pixel(
        float(opening["start_x"]),
        float(opening["start_y"]),
        cell_width,
        cell_height,
        margin,
        cell_px,
    )
    end = grid_to_pixel(
        float(opening["end_x"]),
        float(opening["end_y"]),
        cell_width,
        cell_height,
        margin,
        cell_px,
    )
    center = grid_to_pixel(
        float(opening["x"]),
        float(opening["y"]),
        cell_width,
        cell_height,
        margin,
        cell_px,
    )

    draw.line((start[0], start[1], end[0], end[1]), fill=BOUNDARY_OPENING_COLOR, width=5)
    draw.ellipse(
        (center[0] - 6, center[1] - 6, center[0] + 6, center[1] + 6),
        fill=BOUNDARY_OPENING_COLOR,
        outline=(0, 0, 0),
        width=2,
    )

    edge = str(opening["edge"])
    label = boundary_opening_label(opening)
    if edge == "right":
        label_x = center[0] - 150
        label_y = center[1] - 12
    elif edge == "left":
        label_x = center[0] + 12
        label_y = center[1] - 12
    elif edge == "top":
        label_x = center[0] - 48
        label_y = center[1] + 12
    else:
        label_x = center[0] - 48
        label_y = center[1] - 32

    box_left, box_top, box_right, box_bottom, _, _ = clamp_label_position(
        draw,
        label,
        font,
        label_x,
        label_y,
        image_width,
        image_height,
    )
    draw.rectangle((box_left, box_top, box_right, box_bottom), fill=(12, 24, 30), outline=BOUNDARY_OPENING_COLOR)
    draw.text((box_left + 6, box_top + 3), label, fill=BOUNDARY_OPENING_TEXT_COLOR, font=font)
    draw.line((center[0], center[1], box_left, (box_top + box_bottom) / 2), fill=BOUNDARY_OPENING_COLOR, width=1)


def render_grid(
    data: dict,
    output_path: Path,
    cell_px: int,
    real_cells_only: bool,
    include_dynamic_markers: bool,
    dynamic_marker_radius: int,
    include_scene_actors: bool,
    include_player_family_actors: bool,
    actor_marker_radius: int,
    hub_entrances_mode: str,
    hub_boundary_openings_mode: str,
) -> None:
    width = int(data["width"])
    height = int(data["height"])
    cell_width = float(data["cell_width"])
    cell_height = float(data["cell_height"])
    cells = list(data["cells"])
    rows = max((int(cell["grid_x"]) for cell in cells), default=-1) + 1
    cols = max((int(cell["grid_y"]) for cell in cells), default=-1) + 1
    margin = 48
    draw_private_room_anchors = should_draw_hub_overlay(data, hub_entrances_mode)
    draw_boundary_openings = should_draw_hub_overlay(data, hub_boundary_openings_mode)
    boundary_openings = detect_boundary_openings(data) if draw_boundary_openings else []
    actor_overlays = prepare_actor_overlays(data, include_player_family_actors) if include_scene_actors else []
    legend_height = 90
    if draw_private_room_anchors:
        legend_height += 24
    if boundary_openings:
        legend_height += 24
    if actor_overlays:
        legend_height += 24
    image_width = margin * 2 + cols * cell_px
    image_height = margin * 2 + rows * cell_px + legend_height

    image = Image.new("RGB", (image_width, image_height), (24, 24, 28))
    draw = ImageDraw.Draw(image)
    font = load_font(max(11, min(24, cell_px // 10)))

    subdivisions = int(data.get("subdivisions", 1) or 1)
    for cell in cells:
        row = int(cell["grid_x"])
        col = int(cell["grid_y"])
        left = margin + col * cell_px
        top = margin + row * cell_px
        right = left + cell_px
        bottom = top + cell_px
        cell_open = bool(cell.get("path_traversable", cell.get("traversable", False)))
        coarse_fill = (76, 180, 84) if cell_open else (140, 72, 72)
        draw.rectangle((left, top, right, bottom), fill=coarse_fill, outline=(210, 210, 210), width=1)
        sub_px_x = cell_px / subdivisions
        sub_px_y = cell_px / subdivisions
        if not real_cells_only:
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

    if draw_private_room_anchors:
        for entrance in HUB_PRIVATE_ROOM_ANCHORS:
            draw_entrance_label(
                draw,
                grid_to_pixel(float(entrance["x"]), float(entrance["y"]), cell_width, cell_height, margin, cell_px),
                str(entrance["label"]),
                font,
                image_width,
                image_height,
            )

    for opening in boundary_openings:
        draw_boundary_opening(
            draw,
            opening,
            cell_width,
            cell_height,
            margin,
            cell_px,
            font,
            image_width,
            image_height,
        )

    for actor_index, actor in enumerate(actor_overlays):
        draw_actor_label(
            draw,
            grid_to_pixel(float(actor["x"]), float(actor["y"]), cell_width, cell_height, margin, cell_px),
            str(actor["label"]),
            actor["color"],
            font,
            image_width,
            image_height,
            actor_marker_radius,
            actor_index,
        )

    if include_dynamic_markers:
        player = data.get("player")
        if isinstance(player, dict):
            draw_marker(
                draw,
                grid_to_pixel(player["x"], player["y"], cell_width, cell_height, margin, cell_px),
                (80, 180, 255),
                f"Player {player['x']:.1f},{player['y']:.1f}",
                font,
                dynamic_marker_radius,
            )

        bot = data.get("bot")
        if isinstance(bot, dict):
            draw_marker(
                draw,
                grid_to_pixel(bot["x"], bot["y"], cell_width, cell_height, margin, cell_px),
                (255, 210, 80),
                f"Bot {bot['x']:.1f},{bot['y']:.1f}",
                font,
                dynamic_marker_radius,
            )

    legend_top = margin + rows * cell_px + 12
    draw.text((margin, legend_top), f"Scene: {data.get('scene', 'unknown')}", fill=(240, 240, 240), font=font)
    mode = "real path cells" if real_cells_only else "sample occupancy"
    draw.text((margin, legend_top + 16), f"Grid snapshot fields width={width}, height={height}; rendered rows={rows}, cols={cols}; cell size {cell_width:.1f} x {cell_height:.1f}, subdivisions {data.get('subdivisions', 1)}; mode={mode}", fill=(220, 220, 220), font=font)
    draw.rectangle((margin, legend_top + 36, margin + 18, legend_top + 54), fill=(76, 180, 84), outline=(210, 210, 210))
    draw.text((margin + 26, legend_top + 36), "Walkable path cell" if real_cells_only else "Walkable subcell sample", fill=(240, 240, 240), font=font)
    draw.rectangle((margin + 220, legend_top + 36, margin + 238, legend_top + 54), fill=(140, 72, 72), outline=(210, 210, 210))
    draw.text((margin + 246, legend_top + 36), "Blocked path cell" if real_cells_only else "Blocked subcell sample", fill=(240, 240, 240), font=font)
    legend_line_y = legend_top + 62
    if draw_private_room_anchors:
        draw.ellipse((margin, legend_top + 62, margin + 18, legend_top + 80), outline=(245, 218, 98), width=3)
        draw.text((margin + 26, legend_top + 62), "Known private-room anchors", fill=(240, 240, 240), font=font)
        legend_line_y += 24
    if boundary_openings:
        draw.line((margin, legend_line_y + 9, margin + 18, legend_line_y + 9), fill=BOUNDARY_OPENING_COLOR, width=5)
        draw.text((margin + 26, legend_line_y), f"Walkable boundary openings ({len(boundary_openings)})", fill=(240, 240, 240), font=font)
        legend_line_y += 24
    if actor_overlays:
        draw.ellipse((margin, legend_line_y, margin + 18, legend_line_y + 18), fill=(255, 178, 88), outline=(0, 0, 0), width=2)
        draw.text((margin + 26, legend_line_y), f"Live scene actor overlay ({len(actor_overlays)} actors)", fill=(240, 240, 240), font=font)
    image.save(output_path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Export the current gameplay nav grid to a PNG.")
    parser.add_argument("--output", default="runtime/hub_nav_grid.png", help="Output PNG path relative to repo root.")
    parser.add_argument("--subdivisions", type=int, default=8, help="Samples per coarse cell edge.")
    parser.add_argument("--cell-px", type=int, default=80, help="Rendered pixels per coarse cell edge.")
    parser.add_argument("--real-cells-only", action="store_true", help="Render the actual pathfinding cells instead of subcell samples.")
    parser.add_argument("--include-dynamic-markers", action="store_true", help="Overlay current player/bot positions. Disabled by default for static maps.")
    parser.add_argument("--dynamic-marker-radius", type=int, default=14, help="Radius in pixels for optional player/bot markers.")
    parser.add_argument("--include-scene-actors", action="store_true", help="Overlay live NPC/trader/world actor dots and labels.")
    parser.add_argument("--include-player-family-actors", action="store_true", help="Include object type 0x1 actors in the scene actor overlay.")
    parser.add_argument("--actor-marker-radius", type=int, default=8, help="Radius in pixels for optional scene actor markers.")
    parser.add_argument(
        "--hub-entrances",
        choices=("auto", "always", "never"),
        default="auto",
        help="Overlay known hub private-room anchors. Auto draws them only when the current scene is hub.",
    )
    parser.add_argument(
        "--hub-boundary-openings",
        choices=("auto", "always", "never"),
        default="auto",
        help="Overlay walkable edge openings found from the sampled hub grid. Auto draws them only when the current scene is hub.",
    )
    args = parser.parse_args()

    output_path = (ROOT / args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data = load_grid_data(args.subdivisions)
    render_grid(
        data,
        output_path,
        max(16, args.cell_px),
        args.real_cells_only,
        args.include_dynamic_markers,
        max(4, args.dynamic_marker_radius),
        args.include_scene_actors,
        args.include_player_family_actors,
        max(3, args.actor_marker_radius),
        args.hub_entrances,
        args.hub_boundary_openings,
    )
    print(f"wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
