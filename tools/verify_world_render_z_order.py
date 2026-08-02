#!/usr/bin/env python3
"""Prove native world-sprite ordering, lighting, and two-peer presentation."""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops

import verify_local_multiplayer_sync as sync
from multiplayer_frame_capture import capture_game_backbuffer
from verify_player_health_death_sync import (
    set_local_player_vitals,
    wait_for_remote_matches_owner_health,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE = Path("/mnt/d/codex-evidence/zorder-20260802/acceptance")
INSTANCE_NAME = "zrd"
PORTS = (51755, 51756)
MOD_ID = "canary.lua.invincibility_potion"
ATLAS_ID = f"{MOD_ID}:invincibility_potion"
POTION_TYPE_ID = 0x1B59
INVENTORY_USE_ITEM = 0x0056D1B0
INVENTORY_FIND_ITEM_BY_UID = 0x005521C0
ITEM_UID_OFFSET = 0x34
NATIVE_HEALTH_BAR_HEIGHT = 7.0
MPP_POLL_INTERVAL_SECONDS = 300.0
MPP_WAIT_TIMEOUT_SECONDS = 6.0 * 60.0 * 60.0


def _powershell_json(script: str) -> Any:
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30.0,
        check=False,
    )
    if completed.returncode != 0:
        raise sync.VerifyFailure(
            "PowerShell inventory failed: "
            f"stdout={completed.stdout!r} stderr={completed.stderr!r}"
        )
    text = completed.stdout.strip()
    return json.loads(text) if text else []


def _powershell_text(script: str) -> str:
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30.0,
        check=False,
    )
    if completed.returncode != 0:
        raise sync.VerifyFailure(
            "PowerShell command failed: "
            f"stdout={completed.stdout!r} stderr={completed.stderr!r}"
        )
    return completed.stdout


def foreign_mpp_games() -> list[dict[str, Any]]:
    value = _powershell_json(
        "$rows=@(Get-CimInstance Win32_Process | Where-Object { "
        "$_.Name -ieq 'SolomonDark.exe' -and "
        "(($_.ExecutablePath -like '*mpp*') -or "
        "($_.CommandLine -like '*mpp*')) } | "
        "Select-Object ProcessId,ParentProcessId,Name,ExecutablePath,CommandLine); "
        "ConvertTo-Json -Compress -InputObject $rows"
    )
    if value is None:
        return []
    if not isinstance(value, list):
        value = [value]
    return [row for row in value if isinstance(row, dict)]


def wait_for_mpp_games_to_exit(
    *,
    timeout: float = MPP_WAIT_TIMEOUT_SECONDS,
    poll_interval: float = MPP_POLL_INTERVAL_SECONDS,
) -> dict[str, Any]:
    started = time.monotonic()
    polls: list[dict[str, Any]] = []
    while True:
        active = foreign_mpp_games()
        polls.append(
            {
                "elapsed_seconds": time.monotonic() - started,
                "active": active,
            }
        )
        if not active:
            return {
                "waited_seconds": time.monotonic() - started,
                "poll_count": len(polls),
                "polls": polls,
            }
        elapsed = time.monotonic() - started
        if elapsed >= timeout:
            raise sync.VerifyFailure(
                "mpp-prefixed Solomon Dark processes remained active for "
                f"{elapsed:.1f}s: {active}"
            )
        time.sleep(min(poll_interval, timeout - elapsed))


def bound_campaign_ports(ports: tuple[int, int]) -> list[dict[str, Any]]:
    joined = ",".join(str(port) for port in ports)
    value = _powershell_json(
        "$ports=@(" + joined + "); "
        "$rows=@(Get-NetUDPEndpoint -ErrorAction SilentlyContinue | "
        "Where-Object { $ports -contains $_.LocalPort } | "
        "Select-Object LocalAddress,LocalPort,OwningProcess); "
        "ConvertTo-Json -Compress -InputObject $rows"
    )
    if value is None:
        return []
    if not isinstance(value, list):
        value = [value]
    return [row for row in value if isinstance(row, dict)]


def udp_exclusion_inventory(ports: tuple[int, int]) -> dict[str, Any]:
    command = "netsh interface ipv4 show excludedportrange protocol=udp"
    raw = _powershell_text(command)
    ranges: list[dict[str, int]] = []
    for line in raw.splitlines():
        match = re.fullmatch(
            r"\s*([0-9]+)\s+([0-9]+)(?:\s+\*)?\s*",
            line,
        )
        if match is None:
            continue
        ranges.append(
            {"start": int(match.group(1)), "end": int(match.group(2))}
        )
    excluded = sorted(
        port
        for port in ports
        if any(row["start"] <= port <= row["end"] for row in ranges)
    )
    if excluded:
        raise sync.VerifyFailure(
            f"campaign UDP ports are Windows-excluded: {excluded}"
        )
    return {
        "command": command,
        "raw": raw,
        "ranges": ranges,
        "requested_ports": list(ports),
        "requested_ports_excluded": [],
    }


def parse_values(pipe: str, code: str, timeout: float = 10.0) -> dict[str, str]:
    return sync.parse_key_values(sync.lua(pipe, code, timeout=timeout))


def item_definition(pipe: str) -> dict[str, int]:
    values = parse_values(
        pipe,
        """
local item = sd.items.get("invincibility_potion")
print("content_id=" .. tostring(item and item.id or 0))
print("native_subtype=" .. tostring(item and item.native_subtype or -1))
""",
    )
    content_id = int(values.get("content_id", "0"))
    native_subtype = int(values.get("native_subtype", "-1"))
    if content_id <= 0 or native_subtype < 6:
        raise sync.VerifyFailure(
            f"Invincibility Potion did not register: {values}"
        )
    return {"content_id": content_id, "native_subtype": native_subtype}


def configure_generic_world_sprite(
    pipe: str,
    *,
    enabled: bool,
    x: float,
    y: float,
) -> dict[str, str]:
    code = f"""
if _G.__zrd_world_sprite_registered ~= true then
  sd.events.on("runtime.tick", function()
    local state = rawget(_G, "__zrd_world_sprite")
    if state ~= nil and state.enabled == true then
      sd.world.sprite({json.dumps(ATLAS_ID)}, 0, state.x, state.y)
    end
  end)
  _G.__zrd_world_sprite_registered = true
end
_G.__zrd_world_sprite = {{
  enabled = {str(enabled).lower()},
  x = {x:.6f},
  y = {y:.6f},
}}
print("registered=" .. tostring(_G.__zrd_world_sprite_registered))
print("enabled=" .. tostring(_G.__zrd_world_sprite.enabled))
print("capability=" .. tostring(sd.runtime.has_capability("world.render.native")))
"""
    values = parse_values(pipe, code)
    expected_enabled = str(enabled).lower()
    if (
        values.get("registered") != "true"
        or values.get("enabled") != expected_enabled
        or values.get("capability") != "true"
    ):
        raise sync.VerifyFailure(
            f"generic native world sprite setup failed on {pipe}: {values}"
        )
    return values


def spawn_control_and_custom_drops(
    pipe: str,
    *,
    stock_x: float,
    custom_x: float,
    y: float,
    native_subtype: int,
) -> dict[str, str]:
    return parse_values(
        pipe,
        f"""
local stock_ok, stock_error = sd.world.spawn_reward({{
  kind = "health_potion", amount = 0,
  x = {stock_x:.6f}, y = {y:.6f}
}})
local custom_ok, custom_error = sd.world.spawn_reward({{
  kind = "lua_consumable", amount = {native_subtype},
  x = {custom_x:.6f}, y = {y:.6f}
}})
print("stock_ok=" .. tostring(stock_ok))
print("stock_error=" .. tostring(stock_error or ""))
print("custom_ok=" .. tostring(custom_ok))
print("custom_error=" .. tostring(custom_error or ""))
""",
    )


def loot_rows(pipe: str) -> list[dict[str, Any]]:
    text = sync.lua(
        pipe,
        """
local snapshot = sd.world.get_replicated_loot()
for _, row in ipairs(snapshot and snapshot.drops or {}) do
  if row.kind == "Potion" and row.active then
    print(table.concat({
      tostring(row.network_drop_id), tostring(row.item_slot),
      tostring(row.x), tostring(row.y), tostring(row.radius),
      tostring(row.materialized), tostring(row.local_actor_address)
    }, "|"))
  end
end
""",
    )
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        fields = line.strip().split("|")
        if len(fields) != 7:
            continue
        rows.append(
            {
                "network_drop_id": int(fields[0]),
                "item_slot": int(fields[1]),
                "x": float(fields[2]),
                "y": float(fields[3]),
                "radius": float(fields[4]),
                "materialized": fields[5] == "true",
                "local_actor_address": int(fields[6]),
            }
        )
    return rows


def wait_for_drop_pair(
    pipe: str,
    *,
    native_subtype: int,
    timeout: float,
) -> dict[str, dict[str, Any]]:
    deadline = time.monotonic() + timeout
    last: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        last = loot_rows(pipe)
        matching: dict[str, dict[str, Any]] = {}
        for row in last:
            if not row["materialized"] or row["local_actor_address"] == 0:
                continue
            if row["item_slot"] == 0:
                matching["stock"] = row
            elif row["item_slot"] == native_subtype:
                matching["custom"] = row
        if matching.keys() >= {"stock", "custom"}:
            return matching
        time.sleep(0.25)
    raise sync.VerifyFailure(
        f"stock/custom potion pair did not materialize on {pipe}: {last}"
    )


def set_local_pickup_range(
    pipe: str,
    *,
    pickup_range: float,
) -> dict[str, str]:
    values = parse_values(
        pipe,
        f"""
local player = sd.player.get_state()
local progression = tonumber(player and player.progression_address) or 0
local address = progression ~= 0 and progression + 0xCC or 0
local previous = address ~= 0 and sd.debug.read_float(address) or nil
local wrote = address ~= 0 and sd.debug.write_float(address, {pickup_range:.9g}) or false
local current = wrote and sd.debug.read_float(address) or nil
print("address=" .. tostring(address))
print("previous=" .. tostring(previous or -1))
print("wrote=" .. tostring(wrote))
print("current=" .. tostring(current or -1))
""",
    )
    if (
        values.get("wrote") != "true"
        or int(values.get("address", "0")) == 0
        or float(values.get("previous", "-1")) <= 0.0
        or not math.isclose(
            float(values.get("current", "-1")),
            pickup_range,
            rel_tol=0.0,
            abs_tol=1e-5,
        )
    ):
        raise sync.VerifyFailure(
            f"could not set local pickup range on {pipe}: {values}"
        )
    return values


def place_pair(
    host_pipe: str,
    client_pipe: str,
    *,
    host_target: tuple[float, float, float],
    client_target: tuple[float, float, float],
    timeout: float,
) -> dict[str, Any]:
    host_x, host_y, host_heading = host_target
    client_x, client_y, client_heading = client_target
    writes = {
        "host": sync.place_player(host_pipe, host_x, host_y, host_heading),
        "client": sync.place_player(
            client_pipe,
            client_x,
            client_y,
            client_heading,
        ),
    }
    settled = {
        "host": list(sync.wait_for_local_transform_settled(host_pipe, timeout=timeout)),
        "client": list(sync.wait_for_local_transform_settled(client_pipe, timeout=timeout)),
    }
    time.sleep(1.0)
    return {
        "targets": {
            "host": list(host_target),
            "client": list(client_target),
        },
        "writes": writes,
        "settled": settled,
        "views": {
            "host": sync.query(host_pipe),
            "client": sync.query(client_pipe),
        },
    }


def projections(pipe: str, points: dict[str, tuple[float, float]]) -> dict[str, Any]:
    lines = [
        "local camera = sd.camera.get_state()",
        "local viewport = sd.draw.get_viewport()",
        "assert(camera and camera.scene_available, 'native camera unavailable')",
        "assert(viewport, 'capture viewport unavailable')",
        "local function emit(name, x, y)",
    ]
    lines.extend(
        [
            "  local screen_x = (x - camera.origin_x) * camera.scale",
            "  local screen_y = (y - camera.origin_y) * camera.scale",
            "  local scene_width = camera.width * camera.scale",
            "  local scene_height = camera.height * camera.scale",
            "  local visible = screen_x >= 0 and screen_x <= scene_width and",
            "    screen_y >= 0 and screen_y <= scene_height",
            "  print(name .. '.x=' .. tostring(screen_x))",
            "  print(name .. '.y=' .. tostring(screen_y))",
            "  print(name .. '.visible=' .. tostring(visible))",
            "  print(name .. '.width=' .. tostring(viewport.width))",
            "  print(name .. '.height=' .. tostring(viewport.height))",
            "end",
        ]
    )
    for name, (x, y) in points.items():
        lines.append(f"emit({json.dumps(name)}, {x:.6f}, {y:.6f})")
    values = parse_values(pipe, "\n".join(lines))
    result: dict[str, Any] = {}
    for name in points:
        result[name] = {
            "x": float(values[f"{name}.x"]),
            "y": float(values[f"{name}.y"]),
            "visible": values[f"{name}.visible"] == "true",
            "width": int(values[f"{name}.width"]),
            "height": int(values[f"{name}.height"]),
        }
        if not result[name]["visible"]:
            raise sync.VerifyFailure(
                f"capture point {name} is offscreen on {pipe}: {result[name]}"
            )
    return result


def capture_phase(
    evidence: Path,
    label: str,
    pipes: dict[str, str],
    points: dict[str, tuple[float, float]] | None = None,
    points_by_role: dict[str, dict[str, tuple[float, float]]] | None = None,
) -> dict[str, Any]:
    if (points is None) == (points_by_role is None):
        raise ValueError("provide exactly one of points or points_by_role")
    phase: dict[str, Any] = {}
    for role, pipe in pipes.items():
        role_points = points if points is not None else points_by_role[role]
        projection = projections(pipe, role_points)
        output = evidence / f"{label}-{role}.png"
        capture = capture_game_backbuffer(pipe, output)
        phase[role] = {"projection": projection, "capture": capture}
    return phase


def _crop_box(
    image: Image.Image,
    point: dict[str, Any],
    *,
    half_width: int = 29,
    half_height: int = 31,
) -> tuple[int, int, int, int]:
    x = int(round(float(point["x"])))
    y = int(round(float(point["y"])))
    return (
        max(0, x - half_width),
        max(0, y - half_height),
        min(image.width, x + half_width + 1),
        min(image.height, y + half_height + 1),
    )


def color_stats(
    image_path: Path,
    point: dict[str, Any],
    *,
    color: str,
) -> dict[str, Any]:
    with Image.open(image_path) as opened:
        image = opened.convert("RGB")
        box = _crop_box(image, point)
        pixels = list(image.crop(box).get_flattened_data())
    selected = [pixel for pixel in pixels if _matches_potion_color(pixel, color)]
    brightness = sorted(max(pixel) for pixel in selected)
    percentile_90 = (
        brightness[min(len(brightness) - 1, math.floor(len(brightness) * 0.9))]
        if brightness
        else 0
    )
    return {
        "box": list(box),
        "matching_pixels": len(selected),
        "maximum_channel": max(brightness, default=0),
        "percentile_90_channel": percentile_90,
    }


def _matches_potion_color(pixel: tuple[int, int, int], color: str) -> bool:
    red, green, blue = pixel
    if color == "red":
        return red >= 55 and red >= green * 1.35 and red >= blue * 1.2
    if color == "green":
        return green >= 55 and green >= red * 1.35 and green >= blue * 1.2
    raise ValueError(color)


def potion_template_stats(
    reference_path: Path,
    reference_point: dict[str, Any],
    candidate_path: Path,
    candidate_point: dict[str, Any],
    *,
    color: str,
    alignment_radius: int = 2,
) -> dict[str, Any]:
    """Measure how much of a potion's tint-invariant color mask remains."""
    with Image.open(reference_path) as opened:
        reference_image = opened.convert("RGB")
        reference_box = _crop_box(reference_image, reference_point)
        reference = reference_image.crop(reference_box)
    with Image.open(candidate_path) as opened:
        candidate_image = opened.convert("RGB")
        candidate_box = _crop_box(candidate_image, candidate_point)
        candidate = candidate_image.crop(candidate_box)

    if reference.size != candidate.size:
        raise sync.VerifyFailure(
            "potion comparison crops have different dimensions: "
            f"reference={reference_box} candidate={candidate_box}"
        )

    reference_pixels = reference.load()
    candidate_pixels = candidate.load()
    width, height = reference.size
    mask = [
        (x, y)
        for y in range(height)
        for x in range(width)
        if _matches_potion_color(reference_pixels[x, y], color)
    ]

    best_matches = -1
    best_offset = (0, 0)
    for y_offset in range(-alignment_radius, alignment_radius + 1):
        for x_offset in range(-alignment_radius, alignment_radius + 1):
            matches = sum(
                _matches_potion_color(
                    candidate_pixels[x + x_offset, y + y_offset],
                    color,
                )
                for x, y in mask
                if 0 <= x + x_offset < width
                and 0 <= y + y_offset < height
            )
            candidate_key = (matches, -abs(x_offset) - abs(y_offset))
            best_key = (
                best_matches,
                -abs(best_offset[0]) - abs(best_offset[1]),
            )
            if candidate_key > best_key:
                best_matches = matches
                best_offset = (x_offset, y_offset)

    template_pixels = len(mask)
    return {
        "reference_box": list(reference_box),
        "candidate_box": list(candidate_box),
        "template_pixels": template_pixels,
        "matching_pixels": max(0, best_matches),
        "remaining_ratio": (
            max(0, best_matches) / template_pixels if template_pixels else 0.0
        ),
        "alignment_offset": list(best_offset),
    }


def _latest_log_line(
    path: Path,
    *,
    minimum_line_count: int,
    required_tokens: tuple[str, ...],
) -> str | None:
    if not path.is_file():
        return None
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in reversed(lines[minimum_line_count:]):
        if all(token in line for token in required_tokens):
            return line
    return None


def _native_indicator_geometry(
    line: str,
    *,
    expected_health_percent: int,
) -> dict[str, float]:
    fields: dict[str, float] = {}
    for name in (
        "health_ratio",
        "health_percent",
        "center_x",
        "name_y",
        "bar_top",
        "bar_width",
    ):
        match = re.search(
            rf"(?:^| ){name}=(-?[0-9]+(?:\.[0-9]+)?)",
            line,
        )
        if match is None:
            raise sync.VerifyFailure(
                f"native indicator log has no numeric {name}: {line}"
            )
        fields[name] = float(match.group(1))

    if round(fields["health_percent"]) != expected_health_percent:
        raise sync.VerifyFailure(
            "native indicator health percentage is stale: "
            f"expected={expected_health_percent} line={line}"
        )
    if (
        fields["bar_width"] < 64.0
        or not math.isfinite(fields["center_x"])
        or not math.isfinite(fields["bar_top"])
    ):
        raise sync.VerifyFailure(
            f"native indicator geometry is invalid: {line}"
        )
    fields["left"] = fields["center_x"] - fields["bar_width"] * 0.5
    fields["right"] = fields["center_x"] + fields["bar_width"] * 0.5
    fields["bottom"] = fields["bar_top"] + NATIVE_HEALTH_BAR_HEIGHT
    return fields


def wait_for_native_indicator_geometry(
    path: Path,
    *,
    minimum_line_count: int,
    participant_id: int,
    expected_health_percent: int,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    required = (
        "source=native_world_indicator",
        f"participant={participant_id}",
        "ok=1",
        "health_bar=native",
        f"health_percent={expected_health_percent}",
    )
    while time.monotonic() < deadline:
        line = _latest_log_line(
            path,
            minimum_line_count=minimum_line_count,
            required_tokens=required,
        )
        if line is not None:
            return {
                "line": line,
                "geometry": _native_indicator_geometry(
                    line,
                    expected_health_percent=expected_health_percent,
                ),
            }
        time.sleep(0.1)
    raise sync.VerifyFailure(
        f"native indicator log did not converge for participant "
        f"{participant_id} at {expected_health_percent}%: {path}"
    )


def verify_native_health_bar_pixels(
    image_path: Path,
    geometry: dict[str, float],
) -> dict[str, Any]:
    with Image.open(image_path) as opened:
        image = opened.convert("RGB")

    left = max(0, math.ceil(geometry["left"] + 1.0))
    top = max(0, math.ceil(geometry["bar_top"] + 1.0))
    right = min(image.width, math.floor(geometry["right"] - 1.0))
    bottom = min(image.height, math.floor(geometry["bottom"] - 1.0))
    if right - left < 8 or bottom - top < 2:
        raise sync.VerifyFailure(
            f"native health bar is outside its capture: "
            f"image={image_path} geometry={geometry}"
        )

    fill_ratio = max(0.0, min(1.0, geometry["health_ratio"]))
    fill_right = max(
        left + 1,
        min(right, left + round((right - left) * fill_ratio)),
    )

    def is_health_pixel(pixel: tuple[int, int, int]) -> bool:
        red, green, blue = pixel
        return red >= 130 and red - green >= 55 and red - blue >= 45

    def count(region_left: int, region_right: int) -> tuple[int, int]:
        pixels = [
            image.getpixel((x, y))
            for y in range(top, bottom)
            for x in range(region_left, region_right)
        ]
        return sum(is_health_pixel(pixel) for pixel in pixels), len(pixels)

    filled_health, filled_total = count(left, fill_right)
    empty_health, empty_total = count(fill_right, right)
    if filled_total == 0 or filled_health / filled_total < 0.35:
        raise sync.VerifyFailure(
            "native health bar fill is not visible above the scene: "
            f"image={image_path} geometry={geometry} "
            f"health_pixels={filled_health}/{filled_total}"
        )
    if empty_total > 0 and empty_health / empty_total > 0.35:
        raise sync.VerifyFailure(
            "native health bar empty segment does not match its replicated "
            f"ratio: image={image_path} geometry={geometry} "
            f"health_pixels={empty_health}/{empty_total}"
        )
    return {
        "bounds": [left, top, right, bottom],
        "filled_health_pixels": filled_health,
        "filled_pixels": filled_total,
        "empty_health_pixels": empty_health,
        "empty_pixels": empty_total,
    }


def analyze_potion_captures(
    evidence: Path,
    lighting_control: dict[str, Any],
    behind: dict[str, Any],
    front: dict[str, Any],
    behind_swapped: dict[str, Any],
    front_swapped: dict[str, Any],
) -> dict[str, Any]:
    analysis: dict[str, Any] = {}
    for role in ("host", "client"):
        role_result: dict[str, Any] = {}
        phases = (
            ("potion_lighting", lighting_control),
            ("actor_behind", behind),
            ("actor_front", front),
            ("actor_behind_swapped", behind_swapped),
            ("actor_front_swapped", front_swapped),
        )
        for label, phase in phases:
            image_path = evidence / f"{label}-{role}.png"
            projection = phase[role]["projection"]
            role_result[label] = {
                "stock": color_stats(image_path, projection["stock"], color="red"),
                "custom": color_stats(image_path, projection["custom"], color="green"),
            }
        stock_phases = (
            ("actor_behind", "actor_front")
            if role == "host"
            else ("actor_behind_swapped", "actor_front_swapped")
        )
        custom_phases = (
            ("actor_behind_swapped", "actor_front_swapped")
            if role == "host"
            else ("actor_behind", "actor_front")
        )
        phase_values = dict(phases)

        def template_analysis(
            item: str,
            color: str,
            local_phases: tuple[str, str],
        ) -> dict[str, Any]:
            behind_label, front_label = local_phases
            control_label = (
                "actor_behind_swapped"
                if behind_label == "actor_behind"
                else "actor_behind"
            )
            reference_path = evidence / f"{behind_label}-{role}.png"
            reference_point = phase_values[behind_label][role]["projection"][item]
            control = potion_template_stats(
                reference_path,
                reference_point,
                evidence / f"{control_label}-{role}.png",
                phase_values[control_label][role]["projection"][item],
                color=color,
            )
            actor_front = potion_template_stats(
                reference_path,
                reference_point,
                evidence / f"{front_label}-{role}.png",
                phase_values[front_label][role]["projection"][item],
                color=color,
            )
            return {
                "reference_phase": behind_label,
                "behind_control_phase": control_label,
                "actor_front_phase": front_label,
                "behind_control": control,
                "actor_front": actor_front,
            }

        stock_template = template_analysis("stock", "red", stock_phases)
        custom_template = template_analysis("custom", "green", custom_phases)
        role_result["template_occlusion"] = {
            "stock": stock_template,
            "custom": custom_template,
        }
        behind_stock = stock_template["behind_control"]["template_pixels"]
        front_stock = stock_template["actor_front"]["matching_pixels"]
        behind_custom = custom_template["behind_control"]["template_pixels"]
        front_custom = custom_template["actor_front"]["matching_pixels"]
        role_result["occlusion"] = {
            "stock_pixels_hidden": behind_stock - front_stock,
            "custom_pixels_hidden": behind_custom - front_custom,
        }
        lighting_stock = role_result["potion_lighting"]["stock"]
        lighting_custom = role_result["potion_lighting"]["custom"]
        stock_light = lighting_stock["percentile_90_channel"]
        custom_light = lighting_custom["percentile_90_channel"]
        role_result["lighting"] = {
            "stock_percentile_90": stock_light,
            "custom_percentile_90": custom_light,
            "highlight_delta": abs(stock_light - custom_light),
        }
        if min(
            lighting_stock["matching_pixels"],
            lighting_custom["matching_pixels"],
        ) < 12:
            raise sync.VerifyFailure(
                f"potion lighting control was not visible for {role}: {role_result}"
            )
        for item, template in (
            ("stock", stock_template),
            ("custom", custom_template),
        ):
            control = template["behind_control"]
            actor_front = template["actor_front"]
            if control["template_pixels"] < 12:
                raise sync.VerifyFailure(
                    f"{item} potion template was not visible for {role}: {role_result}"
                )
            if control["remaining_ratio"] < 0.9:
                raise sync.VerifyFailure(
                    f"{item} potion did not draw over the behind actor for {role}: "
                    f"{role_result}"
                )
            if actor_front["remaining_ratio"] > 0.65:
                raise sync.VerifyFailure(
                    f"front actor did not cover enough of the {item} potion for "
                    f"{role}: {role_result}"
                )
        if abs(stock_light - custom_light) > 56:
            raise sync.VerifyFailure(
                f"side-by-side stock/custom lighting highlights diverged for {role}: {role_result}"
            )
        analysis[role] = role_result
    return analysis


def capture_native_indicator_phase(
    evidence: Path,
    *,
    label: str,
    pipes: dict[str, str],
    log_paths: dict[str, Path],
    host_target: tuple[float, float, float],
    client_target: tuple[float, float, float],
    host_health_percent: int,
    client_health_percent: int,
    timeout: float,
) -> dict[str, Any]:
    baseline_lines = {
        role: (
            len(path.read_text(encoding="utf-8", errors="replace").splitlines())
            if path.is_file()
            else 0
        )
        for role, path in log_paths.items()
    }
    placement = place_pair(
        pipes["host"],
        pipes["client"],
        host_target=host_target,
        client_target=client_target,
        timeout=timeout,
    )
    sync.wait_for_remote_convergence(
        pipes["host"],
        sync.CLIENT_ID,
        *client_target,
        timeout=timeout,
    )
    sync.wait_for_remote_convergence(
        pipes["client"],
        sync.HOST_ID,
        *host_target,
        timeout=timeout,
    )

    writes = {
        "host": set_local_player_vitals(
            pipes["host"],
            float(host_health_percent),
            100.0,
        ),
        "client": set_local_player_vitals(
            pipes["client"],
            float(client_health_percent),
            100.0,
        ),
    }
    convergence = {
        "host_observes_client": wait_for_remote_matches_owner_health(
            pipes["client"],
            pipes["host"],
            sync.CLIENT_ID,
            100.0,
            expect_dead=False,
            timeout=timeout,
        ),
        "client_observes_host": wait_for_remote_matches_owner_health(
            pipes["host"],
            pipes["client"],
            sync.HOST_ID,
            100.0,
            expect_dead=False,
            timeout=timeout,
        ),
    }
    indicator = {
        "host": wait_for_native_indicator_geometry(
            log_paths["host"],
            minimum_line_count=baseline_lines["host"],
            participant_id=sync.CLIENT_ID,
            expected_health_percent=client_health_percent,
            timeout=timeout,
        ),
        "client": wait_for_native_indicator_geometry(
            log_paths["client"],
            minimum_line_count=baseline_lines["client"],
            participant_id=sync.HOST_ID,
            expected_health_percent=host_health_percent,
            timeout=timeout,
        ),
    }

    captures: dict[str, Any] = {}
    for role, pipe in pipes.items():
        output = evidence / f"{label}-{role}.png"
        captures[role] = capture_game_backbuffer(pipe, output)
        indicator[role]["pixels"] = verify_native_health_bar_pixels(
            output,
            indicator[role]["geometry"],
        )

    return {
        "placement": placement,
        "vitals_writes": writes,
        "vitals_convergence": convergence,
        "indicator": indicator,
        "captures": captures,
        "stock_indicator_semantics": "native_post_scene_always_above_scene",
    }


def wait_for_custom_inventory_item(
    pipe: str,
    *,
    native_subtype: int,
    timeout: float,
) -> dict[str, int]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = parse_values(
            pipe,
            f"""
local inventory = sd.player.get_inventory_state()
print("root=" .. tostring(inventory and inventory.item_list_root_address or 0))
for _, item in ipairs(inventory and inventory.items or {{}}) do
  if item.type_id == {POTION_TYPE_ID} and item.slot == {native_subtype} then
    print("item_address=" .. tostring(item.item_address))
    print("uid=" .. tostring(sd.debug.read_u32(item.item_address + {ITEM_UID_OFFSET}) or 0))
    print("stack=" .. tostring(item.stack_count))
    break
  end
end
""",
        )
        if int(last.get("root", "0")) > 0 and int(last.get("item_address", "0")) > 0 and int(last.get("uid", "0")) > 0:
            return {
                "root": int(last["root"]),
                "item_address": int(last["item_address"]),
                "uid": int(last["uid"]),
                "stack": int(last.get("stack", "0")),
            }
        time.sleep(0.25)
    raise sync.VerifyFailure(
        f"custom potion was not added to inventory on {pipe}: {last}"
    )


def consume_custom_inventory_item(pipe: str, item: dict[str, int]) -> dict[str, str]:
    values = parse_values(
        pipe,
        f"""
local find = sd.debug.resolve_game_address({INVENTORY_FIND_ITEM_BY_UID})
local use = sd.debug.resolve_game_address({INVENTORY_USE_ITEM})
local found = sd.debug.call_thiscall_u32_ret_u32(find, {item['root']}, {item['uid']})
print("found=" .. tostring(found or 0))
print("expected=" .. tostring({item['item_address']}))
print("used=" .. tostring(sd.debug.call_thiscall_u32(use, {item['root']}, {item['uid']})))
""",
    )
    if values.get("found") != values.get("expected") or values.get("used") != "true":
        raise sync.VerifyFailure(f"native custom-potion use failed: {values}")
    return values


def wait_for_log_tokens(
    paths: dict[str, Path],
    required: dict[str, tuple[str, ...]],
    *,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        complete = True
        last = {}
        for role, path in paths.items():
            text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
            tokens = required[role]
            matches = {token: token in text for token in tokens}
            last[role] = {"path": str(path), "matches": matches}
            complete = complete and all(matches.values())
        if complete:
            return last
        time.sleep(0.25)
    raise sync.VerifyFailure(f"loader log receipts did not converge: {last}")


def analyze_vfx_delta(
    evidence: Path,
    baseline: dict[str, Any],
    active: dict[str, Any],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for role in ("host", "client"):
        baseline_path = evidence / f"vfx-baseline-{role}.png"
        active_path = evidence / f"vfx-active-{role}.png"
        point = active[role]["projection"]["effect"]
        with Image.open(baseline_path) as before_open, Image.open(active_path) as after_open:
            before = before_open.convert("RGB")
            after = after_open.convert("RGB")
            box = _crop_box(after, point, half_width=75, half_height=85)
            difference = ImageChops.difference(before.crop(box), after.crop(box))
            changed = sum(
                1
                for pixel in difference.get_flattened_data()
                if max(pixel) >= 18
            )
        green_before = color_stats(baseline_path, baseline[role]["projection"]["effect"], color="green")
        green_after = color_stats(active_path, point, color="green")
        if changed < 40 or green_after["matching_pixels"] <= green_before["matching_pixels"]:
            raise sync.VerifyFailure(
                f"replicated native SpellGlow was not visible on {role}: "
                f"changed={changed} before={green_before} after={green_after}"
            )
        result[role] = {
            "box": list(box),
            "changed_pixels": changed,
            "green_before": green_before,
            "green_after": green_after,
        }
    return result


def run(
    *,
    evidence: Path,
    game_directory: Path,
    runtime_root: Path,
    launcher_path: Path,
    instance_prefix: str,
    ports: tuple[int, int],
    timeout: float,
) -> dict[str, Any]:
    mpp_wait = wait_for_mpp_games_to_exit()
    bound = bound_campaign_ports(ports)
    if bound:
        raise sync.VerifyFailure(
            f"campaign UDP ports are already bound: {bound}"
        )
    udp_exclusions = udp_exclusion_inventory(ports)

    evidence.mkdir(parents=True, exist_ok=True)
    host_pipe = f"SolomonDarkModLoader_LuaExec_{instance_prefix}-host"
    client_pipe = f"SolomonDarkModLoader_LuaExec_{instance_prefix}-client"
    pipes = {"host": host_pipe, "client": client_pipe}
    log_paths = {
        role: runtime_root
        / "instances"
        / f"{instance_prefix}-{role}"
        / "stage/.sdmod/logs/solomondarkmodloader.log"
        for role in pipes
    }
    for path in log_paths.values():
        path.unlink(missing_ok=True)

    launch = sync.launch_pair(
        host_preset="map_create_fire_mind_hub",
        client_preset="map_create_water_body_hub",
        temporary_host_profile=True,
        god_mode=False,
        tile_windows=False,
        allow_focus_steal=False,
        kill_existing=False,
        instance_prefix=instance_prefix,
        host_port=ports[0],
        client_port=ports[1],
        third_port=ports[1] + 1,
        game_directory=game_directory,
        launcher_path=launcher_path,
        runtime_root=runtime_root,
        exact_mod_id=MOD_ID,
        quick_start=True,
        enable_audio=False,
    )
    process_ids = sync.game_process_ids(launch)
    if len(process_ids) != 2:
        sync.stop_game_processes(process_ids)
        raise sync.VerifyFailure(
            f"z-order pair did not report two exact game PIDs: {launch}"
        )

    result: dict[str, Any] = {
        "ok": False,
        "launch": launch,
        "process_ids": process_ids,
        "instance_prefix": instance_prefix,
        "ports": list(ports),
        "audio_disabled": True,
        "mpp_wait": mpp_wait,
        "udp_exclusions": udp_exclusions,
    }
    try:
        sync.wait_for_remote(
            host_pipe,
            sync.CLIENT_ID,
            sync.CLIENT_NAME,
            "hub",
            timeout,
        )
        sync.wait_for_remote(
            client_pipe,
            sync.HOST_ID,
            sync.HOST_NAME,
            "hub",
            timeout,
        )
        for pipe in pipes.values():
            count = sync.lua(
                pipe,
                "lua_bots_disable_tick=true; sd.bots.clear(); return tostring(sd.bots.get_count())",
            ).strip()
            if count != "0":
                raise sync.VerifyFailure(f"bots remained active on {pipe}: {count}")

        sync.start_testrun(host_pipe)
        sync.wait_for_scene(host_pipe, "testrun", timeout)
        sync.wait_for_scene(client_pipe, "testrun", timeout)
        sync.wait_for_remote(
            host_pipe,
            sync.CLIENT_ID,
            sync.CLIENT_NAME,
            "testrun",
            timeout,
        )
        sync.wait_for_remote(
            client_pipe,
            sync.HOST_ID,
            sync.HOST_NAME,
            "testrun",
            timeout,
        )

        definition = item_definition(host_pipe)
        result["item_definition"] = definition
        host_state = sync.query(host_pipe)
        center_x = float(host_state["player.x"]) + 300.0
        center_y = float(host_state["player.y"]) + 300.0
        stock_x = center_x - 80.0
        custom_x = center_x + 80.0
        generic_x = center_x + 190.0
        generic_y = center_y + 60.0

        result["generic_world_sprite"] = {
            role: configure_generic_world_sprite(
                pipe,
                enabled=True,
                x=generic_x,
                y=generic_y,
            )
            for role, pipe in pipes.items()
        }
        place_pair(
            host_pipe,
            client_pipe,
            host_target=(stock_x, center_y + 60.0, 0.0),
            client_target=(custom_x, center_y + 60.0, 0.0),
            timeout=timeout,
        )
        result["generic_capture"] = capture_phase(
            evidence,
            "generic-native-seam",
            pipes,
            {"generic": (generic_x, generic_y)},
        )
        for pipe in pipes.values():
            configure_generic_world_sprite(
                pipe,
                enabled=False,
                x=generic_x,
                y=generic_y,
            )

        # Keep the local peers from consuming drops while their silhouettes
        # cross. This derived range drives both stock pickup and the
        # multiplayer-native request boundary; restore it before the real
        # custom-potion pickup below.
        pickup_range_hold = {
            role: set_local_pickup_range(pipe, pickup_range=0.01)
            for role, pipe in pipes.items()
        }
        result["pickup_range_hold"] = pickup_range_hold

        spawn = spawn_control_and_custom_drops(
            host_pipe,
            stock_x=stock_x,
            custom_x=custom_x,
            y=center_y,
            native_subtype=definition["native_subtype"],
        )
        if spawn.get("stock_ok") != "true" or spawn.get("custom_ok") != "true":
            raise sync.VerifyFailure(f"potion spawn requests failed: {spawn}")
        result["spawn"] = spawn
        # Authoritative native drops are deliberately absent from the host's
        # replicated-loot mirror; the client mirror proves both materialized
        # carriers and supplies their shared world positions.
        client_drops = wait_for_drop_pair(
            client_pipe,
            native_subtype=definition["native_subtype"],
            timeout=timeout,
        )
        result["drops"] = {
            "client_materialized": client_drops,
            "authoritative_world_positions": {
                name: {"x": row["x"], "y": row["y"]}
                for name, row in client_drops.items()
            },
        }
        result["potion_lighting_placement"] = place_pair(
            host_pipe,
            client_pipe,
            host_target=(stock_x, center_y - 48.0, 0.0),
            client_target=(custom_x, center_y - 48.0, 0.0),
            timeout=timeout,
        )
        lighting_control = capture_phase(
            evidence,
            "potion_lighting",
            pipes,
            {"stock": (stock_x, center_y), "custom": (custom_x, center_y)},
        )
        result["potion_lighting"] = lighting_control

        # Sack's stock -25 sort bias makes its effective key Y-25, while a
        # live PlayerWizard retains the base zero bias. Keep silhouettes
        # crossed on each side of that exact boundary.
        behind_y = center_y - 32.0
        front_y = center_y + 4.0
        result["actor_behind_placement"] = place_pair(
            host_pipe,
            client_pipe,
            host_target=(stock_x, behind_y, 0.0),
            client_target=(custom_x, behind_y, 0.0),
            timeout=timeout,
        )
        behind = capture_phase(
            evidence,
            "actor_behind",
            pipes,
            {"stock": (stock_x, center_y), "custom": (custom_x, center_y)},
        )
        result["actor_behind"] = behind
        wait_for_drop_pair(
            client_pipe,
            native_subtype=definition["native_subtype"],
            timeout=5.0,
        )

        result["actor_front_placement"] = place_pair(
            host_pipe,
            client_pipe,
            host_target=(stock_x, front_y, 0.0),
            client_target=(custom_x, front_y, 0.0),
            timeout=timeout,
        )
        front = capture_phase(
            evidence,
            "actor_front",
            pipes,
            {"stock": (stock_x, center_y), "custom": (custom_x, center_y)},
        )
        result["actor_front"] = front

        result["actor_behind_swapped_placement"] = place_pair(
            host_pipe,
            client_pipe,
            host_target=(custom_x, behind_y, 0.0),
            client_target=(stock_x, behind_y, 0.0),
            timeout=timeout,
        )
        behind_swapped = capture_phase(
            evidence,
            "actor_behind_swapped",
            pipes,
            {"stock": (stock_x, center_y), "custom": (custom_x, center_y)},
        )
        result["actor_behind_swapped"] = behind_swapped
        result["actor_front_swapped_placement"] = place_pair(
            host_pipe,
            client_pipe,
            host_target=(custom_x, front_y, 0.0),
            client_target=(stock_x, front_y, 0.0),
            timeout=timeout,
        )
        front_swapped = capture_phase(
            evidence,
            "actor_front_swapped",
            pipes,
            {"stock": (stock_x, center_y), "custom": (custom_x, center_y)},
        )
        result["actor_front_swapped"] = front_swapped
        result["potion_pixel_analysis"] = analyze_potion_captures(
            evidence,
            lighting_control,
            behind,
            front,
            behind_swapped,
            front_swapped,
        )

        indicator_x = center_x
        indicator_y = center_y + 170.0
        result["indicator_host_actor_front"] = capture_native_indicator_phase(
            evidence,
            label="indicator-host-actor-front",
            pipes=pipes,
            log_paths=log_paths,
            host_target=(indicator_x, indicator_y + 32.0, 0.0),
            client_target=(indicator_x, indicator_y - 32.0, 180.0),
            host_health_percent=52,
            client_health_percent=63,
            timeout=timeout,
        )
        result["indicator_client_actor_front"] = capture_native_indicator_phase(
            evidence,
            label="indicator-client-actor-front",
            pipes=pipes,
            log_paths=log_paths,
            host_target=(indicator_x, indicator_y - 32.0, 0.0),
            client_target=(indicator_x, indicator_y + 32.0, 180.0),
            host_health_percent=41,
            client_health_percent=74,
            timeout=timeout,
        )

        result["pickup_range_restore"] = {
            role: set_local_pickup_range(
                pipe,
                pickup_range=float(pickup_range_hold[role]["previous"]),
            )
            for role, pipe in pipes.items()
        }
        time.sleep(0.5)
        pickup = result["drops"]["client_materialized"]["custom"]
        sync.place_player(
            host_pipe,
            float(pickup["x"]),
            float(pickup["y"]),
            0.0,
        )
        sync.wait_for_local_transform_settled(host_pipe, timeout=timeout)
        custom_item = wait_for_custom_inventory_item(
            host_pipe,
            native_subtype=definition["native_subtype"],
            timeout=timeout,
        )
        result["custom_inventory_item"] = custom_item
        effect_x = center_x + 150.0
        effect_y = center_y + 120.0
        sync.place_player(host_pipe, effect_x, effect_y, 0.0)
        sync.place_player(client_pipe, effect_x + 120.0, effect_y, 180.0)
        sync.wait_for_local_transform_settled(host_pipe, timeout=timeout)
        sync.wait_for_local_transform_settled(client_pipe, timeout=timeout)
        time.sleep(1.0)
        host_vfx_view = sync.query(host_pipe)
        client_vfx_view = sync.query(client_pipe)
        client_host_prefix = f"peer.{sync.HOST_ID}."
        effect_points = {
            "host": {
                "effect": (
                    float(host_vfx_view["player.x"]),
                    float(host_vfx_view["player.y"]),
                )
            },
            "client": {
                "effect": (
                    float(client_vfx_view[client_host_prefix + "x"]),
                    float(client_vfx_view[client_host_prefix + "y"]),
                )
            },
        }
        baseline = capture_phase(
            evidence,
            "vfx-baseline",
            pipes,
            points_by_role=effect_points,
        )
        result["vfx_baseline"] = baseline
        result["native_inventory_use"] = consume_custom_inventory_item(
            host_pipe,
            custom_item,
        )
        time.sleep(0.35)
        active = capture_phase(
            evidence,
            "vfx-active",
            pipes,
            points_by_role=effect_points,
        )
        result["vfx_active"] = active
        result["vfx_pixel_analysis"] = analyze_vfx_delta(
            evidence,
            baseline,
            active,
        )

        required_tokens = {
            "host": (
                "Lua native world renderer initialized",
                "native carrier glyph reached stock draw batch",
                "custom glyph reached stock carrier draw batch",
                "invincibility potion activated participant_id=",
                "source=native_world_indicator",
                "health_bar=native",
            ),
            "client": (
                "Lua native world renderer initialized",
                "native carrier glyph reached stock draw batch",
                "custom glyph reached stock carrier draw batch",
                "invincibility potion activated participant_id=",
                "source=native_world_indicator",
                "health_bar=native",
            ),
        }
        result["log_receipts"] = wait_for_log_tokens(
            log_paths,
            required_tokens,
            timeout=timeout,
        )
        for role, path in log_paths.items():
            copied = evidence / f"{role}-solomondarkmodloader.log"
            copied.write_bytes(path.read_bytes())
            result["log_receipts"][role]["evidence_copy"] = str(copied)
            log_text = copied.read_text(encoding="utf-8", errors="replace")
            if "Lua custom potion world sprite draw failed" in log_text or "lua_world_render: world sprite skipped" in log_text:
                raise sync.VerifyFailure(
                    f"native world rendering logged a failure on {role}"
                )

        result["summary"] = {
            "side_by_side": True,
            "both_peers": True,
            "stock_and_custom_same_scene": True,
            "actor_front_occludes_both": True,
            "actor_behind_is_occluded_by_both": True,
            "native_lighting_lane_both_peers": True,
            "generic_world_sprite_both_peers": True,
            "native_spell_glow_both_peers": True,
            "floating_bar_stock_indicator_semantics_both_peers": True,
        }
        result["ok"] = True
        return result
    finally:
        result["cleanup"] = sync.stop_game_processes(process_ids)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument(
        "--game-dir",
        type=Path,
        default=Path("/mnt/c/SolomonDarkAbandonware"),
    )
    parser.add_argument("--runtime-root", type=Path, default=ROOT / "runtime")
    parser.add_argument(
        "--launcher-path",
        type=Path,
        default=ROOT / "dist/launcher/SolomonDarkModLauncher.exe",
    )
    parser.add_argument("--instance-prefix", default=INSTANCE_NAME)
    parser.add_argument("--host-port", type=int, default=PORTS[0])
    parser.add_argument("--client-port", type=int, default=PORTS[1])
    parser.add_argument("--timeout", type=float, default=75.0)
    args = parser.parse_args()

    result: dict[str, Any] = {
        "ok": False,
        "instance_prefix": args.instance_prefix,
        "ports": [args.host_port, args.client_port],
    }
    exit_code = 0
    try:
        result = run(
            evidence=args.evidence,
            game_directory=args.game_dir,
            runtime_root=args.runtime_root,
            launcher_path=args.launcher_path,
            instance_prefix=args.instance_prefix,
            ports=(args.host_port, args.client_port),
            timeout=args.timeout,
        )
    except Exception as exc:  # noqa: BLE001 - persist exact acceptance failure.
        result["error"] = str(exc)
        result["error_type"] = type(exc).__name__
        exit_code = 1

    args.evidence.mkdir(parents=True, exist_ok=True)
    output = args.evidence / "result.json"
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "ok": result.get("ok", False),
                "error": result.get("error"),
                "summary": result.get("summary"),
                "output": str(output),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
