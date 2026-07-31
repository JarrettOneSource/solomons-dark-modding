#!/usr/bin/env python3
"""Fresh staged acceptance probe for ML Bot Policy v3 native seams.

The probe owns only launcher-returned processes under this worktree's runtime
root. It validates exact collision geometry against native placement truth,
replicated enemy statuses and hazards, semantic inventory reads, and
participant-scoped exactly-once consumable use.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
RE_DIR = ROOT / "tests" / "re"
if str(RE_DIR) not in sys.path:
    sys.path.insert(0, str(RE_DIR))

import run_live_native_spell_stats_probe as phase2_probe  # noqa: E402


OUTPUT_PATH = ROOT / "runtime" / "live_ml_bot_v3_native_seams_probe.json"
PROCEDURAL_SELECTOR_RVA = 0x00B3BEDC
GEOMETRY_SEEDS = (0x2A0FC5AA, 0x11111111, 0x22222222)
PROBE_RUN_TAG = (
    f"{os.getpid() & 0xFFFF:04X}"
    f"{time.time_ns() & 0xFFFFFFFF:08X}"
)


class V3NativeSeamsProbeFailure(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise V3NativeSeamsProbeFailure(message)


def as_int(values: dict[str, str], key: str, default: int = 0) -> int:
    raw = values.get(key)
    if raw is None or raw == "":
        return default
    try:
        return int(raw, 0)
    except ValueError:
        return int(float(raw))


def as_float(
    values: dict[str, str],
    key: str,
    default: float = math.nan,
) -> float:
    raw = values.get(key)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def wait_for_scene(
    session: phase2_probe.OwnedSoloSession,
    expected: str,
    *,
    timeout: float = 80.0,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = session.values(
            """
local scene = sd.world.get_scene() or {}
print('scene=' .. tostring(scene.name or scene.kind or ''))
print('transitioning=' .. tostring(scene.transitioning or false))
"""
        )
        if (
            last.get("scene") == expected
            and last.get("transitioning") == "false"
        ):
            return last
        time.sleep(0.25)
    raise V3NativeSeamsProbeFailure(
        f"scene did not settle as {expected!r}: {last}"
    )


def enter_procedural_run(
    session: phase2_probe.OwnedSoloSession,
    seed: int,
) -> dict[str, str]:
    configured = session.values(
        f"""
local selector =
  sd.debug.resolve_game_address({PROCEDURAL_SELECTOR_RVA})
local selector_ok =
  selector ~= nil and selector ~= 0 and
  sd.debug.write_i32(selector, 1)
local seed_ok = sd.debug.set_run_generation_seed({seed})
print('selector_ok=' .. tostring(selector_ok == true))
print('seed_ok=' .. tostring(seed_ok == true))
"""
    )
    require(
        configured.get("selector_ok") == "true",
        f"could not select the stock procedural survival layout: {configured}",
    )
    require(
        configured.get("seed_ok") == "true",
        f"could not set run generation seed {seed:#x}: {configured}",
    )

    deadline = time.monotonic() + 20.0
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = session.values(
            """
local ok, result = pcall(sd.hub.start_testrun)
print('accepted=' .. tostring(ok and result == true))
print('error=' .. tostring((not ok) and result or ''))
"""
        )
        if last.get("accepted") == "true":
            break
        time.sleep(0.5)
    require(
        last.get("accepted") == "true",
        f"procedural testrun was not accepted: {last}",
    )
    wait_for_scene(session, "testrun")
    return configured


def wait_for_geometry(
    session: phase2_probe.OwnedSoloSession,
    bot_id: int,
    *,
    timeout: float = 40.0,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = session.values(
            f"""
local grid = sd.nav.get_grid(4)
local geometry = sd.nav.get_collision_geometry({bot_id})
print('grid_ready=' .. tostring(
  grid ~= nil and
  grid.refresh_pending == false and
  grid.subdivisions == 4))
print('width=' .. tostring(grid and grid.width or 0))
print('height=' .. tostring(grid and grid.height or 0))
print('circle_count=' ..
  tostring(geometry and #geometry.circles or 0))
print('segment_count=' ..
  tostring(geometry and #geometry.segments or 0))
print('polygon_count=' ..
  tostring(geometry and #geometry.polygons or 0))
"""
        )
        if (
            last.get("grid_ready") == "true"
            and as_int(last, "circle_count") > 100
        ):
            return last
        time.sleep(0.5)
    raise V3NativeSeamsProbeFailure(
        f"procedural collision geometry did not populate: {last}"
    )


EXACT_GEOMETRY_FIDELITY_LUA = r"""
local bot_id = __BOT_ID__
local grid = assert(sd.nav.get_grid(4), "nav grid unavailable")
assert(grid.refresh_pending == false, "nav grid refresh is pending")
assert(grid.subdivisions == 4, "unexpected subdivision count")
local geometry = assert(
  sd.nav.get_collision_geometry(bot_id),
  "collision geometry unavailable")
assert(geometry.refresh_pending == false, "geometry refresh is pending")
assert(
  geometry.observer_radius_resolved == true,
  "observer radius unresolved")

local player = assert(sd.player.get_state(), "player state unavailable")
local observer = assert(sd.bots.get_state(bot_id), "bot state unavailable")
local radius = geometry.observer_radius
local endpoint_only_distance = radius * 2.0 + 0.51
local grid_width = grid.height * grid.cell_width
local grid_height = grid.width * grid.cell_height

local runtime = sd.runtime.get_multiplayer_state() or {}
local participant_positions = {}
local radii = {}
for _, row in ipairs(geometry.participant_radii or {}) do
  radii[tostring(row.participant_id)] =
    row.radius_resolved == true and (tonumber(row.radius) or 0.0) or 0.0
end
for _, row in ipairs(runtime.participants or {}) do
  local row_radius = radii[tostring(row.participant_id)] or radius
  participant_positions[#participant_positions + 1] = {
    id = row.participant_id,
    x = tonumber(row.x) or 0.0,
    y = tonumber(row.y) or 0.0,
    radius = row_radius,
  }
end

local function point_segment_distance_sq(x, y, ax, ay, bx, by)
  local dx = bx - ax
  local dy = by - ay
  local length_sq = dx * dx + dy * dy
  if length_sq <= 0.0000001 then
    local px = x - ax
    local py = y - ay
    return px * px + py * py
  end
  local t = ((x - ax) * dx + (y - ay) * dy) / length_sq
  t = math.max(0.0, math.min(1.0, t))
  local px = x - (ax + dx * t)
  local py = y - (ay + dy * t)
  return px * px + py * py
end

local function point_in_polygon(x, y, points)
  local inside = false
  local previous = points[#points]
  for _, current in ipairs(points) do
    local crosses =
      ((current.y > y) ~= (previous.y > y)) and
      (x <
        (previous.x - current.x) *
          (y - current.y) /
          (previous.y - current.y) +
        current.x)
    if crosses then
      inside = not inside
    end
    previous = current
  end
  return inside
end

local function polygon_overlaps_circle(x, y, points)
  if #points < 3 then
    return false
  end
  if point_in_polygon(x, y, points) then
    return true
  end
  local radius_sq = radius * radius
  local previous = points[#points]
  for _, current in ipairs(points) do
    if point_segment_distance_sq(
        x, y,
        previous.x, previous.y,
        current.x, current.y) <= radius_sq then
      return true
    end
    previous = current
  end
  return false
end

local function exact_walkable(x, y)
  if x < 0.0 or y < 0.0 or x >= grid_width or y >= grid_height then
    return false
  end
  for _, circle in ipairs(geometry.circles or {}) do
    if circle.path_blocks == true then
      local dx = x - circle.x
      local dy = y - circle.y
      local combined = radius + circle.radius
      if dx * dx + dy * dy <= combined * combined then
        return false
      end
    end
  end
  for _, segment in ipairs(geometry.segments or {}) do
    if segment.path_blocks == true and
        point_segment_distance_sq(
          x, y,
          segment.start_x, segment.start_y,
          segment.end_x, segment.end_y) <= radius * radius then
      return false
    end
  end
  for _, polygon in ipairs(geometry.polygons or {}) do
    if polygon.path_blocks == true and
        polygon_overlaps_circle(x, y, polygon.points or {}) then
      return false
    end
  end
  return true
end

local function native_truth(x, y)
  return sd.nav.test_segment(
    x - endpoint_only_distance,
    y,
    x,
    y)
end

-- The public geometry is resolved for the synthetic bot while the only
-- address-free placement oracle is resolved for the local player. Their
-- radii/masks are identical, but each excludes a different self body. Remove
-- samples near either participant body so the comparison isolates static
-- geometry rather than that deliberate observer swap.
local function near_participant_body(x, y)
  for _, row in ipairs(participant_positions) do
    local dx = x - row.x
    local dy = y - row.y
    local combined = radius + row.radius + 1.0
    if dx * dx + dy * dy <= combined * combined then
      return true
    end
  end
  return false
end

local function new_stats()
  return {
    samples = 0,
    mismatches = 0,
    false_open = 0,
    false_block = 0,
    polygon_bounds_hits = 0,
    segment_near_hits = 0,
    circle_near_hits = 0,
    mismatch_examples = {},
  }
end

local function attribute_false_open(stats, x, y)
  for _, polygon in ipairs(geometry.polygons or {}) do
    if x >= polygon.bounds_x - radius and
        x <= polygon.bounds_x + polygon.bounds_w + radius and
        y >= polygon.bounds_y - radius and
        y <= polygon.bounds_y + polygon.bounds_h + radius then
      stats.polygon_bounds_hits = stats.polygon_bounds_hits + 1
      break
    end
  end
  local nearest_segment = math.huge
  for _, segment in ipairs(geometry.segments or {}) do
    nearest_segment = math.min(
      nearest_segment,
      math.sqrt(point_segment_distance_sq(
        x, y,
        segment.start_x, segment.start_y,
        segment.end_x, segment.end_y)))
  end
  if nearest_segment <= radius + 1.0 then
    stats.segment_near_hits = stats.segment_near_hits + 1
  end
  local nearest_circle_gap = math.huge
  local nearest_any_circle_gap = math.huge
  local nearest_any_circle_type = 0
  local nearest_any_circle_mask = 0
  local nearest_any_circle_blocks = false
  for _, circle in ipairs(geometry.circles or {}) do
    local dx = x - circle.x
    local dy = y - circle.y
    local gap =
      math.sqrt(dx * dx + dy * dy) -
      (radius + circle.radius)
    if gap < nearest_any_circle_gap then
      nearest_any_circle_gap = gap
      nearest_any_circle_type = circle.native_type_id
      nearest_any_circle_mask = circle.mask
      nearest_any_circle_blocks = circle.path_blocks == true
    end
    if circle.path_blocks == true then
      nearest_circle_gap = math.min(
        nearest_circle_gap,
        gap)
    end
  end
  if nearest_circle_gap <= 1.0 then
    stats.circle_near_hits = stats.circle_near_hits + 1
  end
  if #stats.mismatch_examples < 20 then
    stats.mismatch_examples[#stats.mismatch_examples + 1] = {
      x = x,
      y = y,
      nearest_segment = nearest_segment,
      nearest_circle_gap = nearest_circle_gap,
      nearest_any_circle_gap = nearest_any_circle_gap,
      nearest_any_circle_type = nearest_any_circle_type,
      nearest_any_circle_mask = nearest_any_circle_mask,
      nearest_any_circle_blocks = nearest_any_circle_blocks,
    }
  end
end

local function compare(stats, x, y)
  if x < 0.0 or y < 0.0 or x >= grid_width or y >= grid_height or
      near_participant_body(x, y) then
    return nil, nil
  end
  local predicted = exact_walkable(x, y)
  local truth = native_truth(x, y)
  stats.samples = stats.samples + 1
  if predicted ~= truth then
    stats.mismatches = stats.mismatches + 1
    if predicted then
      stats.false_open = stats.false_open + 1
      attribute_false_open(stats, x, y)
    else
      stats.false_block = stats.false_block + 1
    end
  end
  return predicted, truth
end

local dense = new_stats()
local dense_step = 25.0
for y = dense_step * 0.2, grid_height - 0.001, dense_step do
  for x = dense_step * 0.2, grid_width - 0.001, dense_step do
    compare(dense, x, y)
    compare(dense, x + dense_step * 0.6, y)
    compare(dense, x, y + dense_step * 0.6)
    compare(dense, x + dense_step * 0.6, y + dense_step * 0.6)
  end
end

local subdivisions = grid.subdivisions
local sample_width = grid.cell_width / subdivisions
local sample_height = grid.cell_height / subdivisions
local candidates = {}
for row = 0, grid.width * subdivisions - 1 do
  for column = 0, grid.height * subdivisions - 1 do
    local x = (column + 0.5) * sample_width
    local y = (row + 0.5) * sample_height
    if x >= 480.0 and x <= grid_width - 480.0 and
        y >= 480.0 and y <= grid_height - 480.0 and
        not near_participant_body(x, y) and
        exact_walkable(x, y) and native_truth(x, y) then
      candidates[#candidates + 1] = {x = x, y = y}
    end
  end
end

local observers = {}
local observer_count = math.min(192, #candidates)
for index = 1, observer_count do
  local source_index = math.floor(
    (index - 0.5) * #candidates / observer_count) + 1
  observers[#observers + 1] = candidates[source_index]
end

local directions = {
  {x = 0.0, y = -1.0},
  {x = 0.7071067811865476, y = -0.7071067811865476},
  {x = 1.0, y = 0.0},
  {x = 0.7071067811865476, y = 0.7071067811865476},
  {x = 0.0, y = 1.0},
  {x = -0.7071067811865476, y = 0.7071067811865476},
  {x = -1.0, y = 0.0},
  {x = -0.7071067811865476, y = -0.7071067811865476},
}
local patch = new_stats()
local rays = new_stats()
local clearance_count = 0
local clearance_nonzero = 0
local clearance_abs_sum = 0.0
local clearance_max = 0.0
for _, origin in ipairs(observers) do
  for row_offset = -3, 3 do
    for column_offset = -3, 3 do
      if row_offset ~= 0 or column_offset ~= 0 then
        compare(
          patch,
          origin.x + column_offset * 60.0,
          origin.y + row_offset * 60.0)
      end
    end
  end
  for _, direction in ipairs(directions) do
    local predicted_clearance = 480.0
    local truth_clearance = 480.0
    local complete = true
    for distance = 60, 480, 60 do
      local predicted, truth = compare(
        rays,
        origin.x + direction.x * distance,
        origin.y + direction.y * distance)
      if predicted == nil then
        complete = false
      else
        if predicted_clearance == 480.0 and not predicted then
          predicted_clearance = distance
        end
        if truth_clearance == 480.0 and not truth then
          truth_clearance = distance
        end
      end
    end
    if complete then
      local error = math.abs(predicted_clearance - truth_clearance)
      clearance_count = clearance_count + 1
      clearance_abs_sum = clearance_abs_sum + error
      clearance_max = math.max(clearance_max, error)
      if error ~= 0.0 then
        clearance_nonzero = clearance_nonzero + 1
      end
    end
  end
end

local function emit_stats(name, stats)
  print(name .. '_samples=' .. stats.samples)
  print(name .. '_mismatches=' .. stats.mismatches)
  print(name .. '_false_open=' .. stats.false_open)
  print(name .. '_false_block=' .. stats.false_block)
  print(name .. '_polygon_bounds_hits=' .. stats.polygon_bounds_hits)
  print(name .. '_segment_near_hits=' .. stats.segment_near_hits)
  print(name .. '_circle_near_hits=' .. stats.circle_near_hits)
  for index, example in ipairs(stats.mismatch_examples) do
    print(name .. '_mismatch_' .. index .. '=' ..
      example.x .. ',' .. example.y .. ',' ..
      example.nearest_segment .. ',' ..
      example.nearest_circle_gap .. ',' ..
      example.nearest_any_circle_gap .. ',' ..
      example.nearest_any_circle_type .. ',' ..
      example.nearest_any_circle_mask .. ',' ..
      tostring(example.nearest_any_circle_blocks))
  end
  print(name .. '_error_rate=' ..
    (stats.samples > 0 and stats.mismatches / stats.samples or 0.0))
end

local circle_blocks = 0
local pushable_circles = 0
for _, circle in ipairs(geometry.circles or {}) do
  if circle.path_blocks then circle_blocks = circle_blocks + 1 end
  if circle.pushable then pushable_circles = pushable_circles + 1 end
end
local segment_blocks = 0
local openable_segments = 0
for _, segment in ipairs(geometry.segments or {}) do
  if segment.path_blocks then segment_blocks = segment_blocks + 1 end
  if segment.openable then openable_segments = openable_segments + 1 end
end

print('grid_width=' .. grid.width)
print('grid_height=' .. grid.height)
print('observer_radius=' .. radius)
print('circle_count=' .. #geometry.circles)
print('circle_blocks=' .. circle_blocks)
print('pushable_circles=' .. pushable_circles)
for index, circle in ipairs(geometry.circles or {}) do
  if circle.path_blocks ~= true then
    print('nonblocking_circle_' .. index .. '=' ..
      circle.native_type_id .. ',' .. circle.mask .. ',' ..
      circle.x .. ',' .. circle.y .. ',' .. circle.radius .. ',' ..
      tostring(circle.pushable))
  end
end
print('segment_count=' .. #geometry.segments)
print('segment_blocks=' .. segment_blocks)
print('openable_segments=' .. openable_segments)
print('polygon_count=' .. #geometry.polygons)
for index, polygon in ipairs(geometry.polygons or {}) do
  local min_x = math.huge
  local min_y = math.huge
  local max_x = -math.huge
  local max_y = -math.huge
  for _, point in ipairs(polygon.points or {}) do
    min_x = math.min(min_x, point.x)
    min_y = math.min(min_y, point.y)
    max_x = math.max(max_x, point.x)
    max_y = math.max(max_y, point.y)
  end
  print('polygon_' .. index .. '_shape=' ..
    polygon.bounds_x .. ',' .. polygon.bounds_y .. ',' ..
    polygon.bounds_w .. ',' .. polygon.bounds_h .. ',' ..
    min_x .. ',' .. min_y .. ',' .. max_x .. ',' .. max_y)
end
print('participant_radius_count=' .. #geometry.participant_radii)
print('observer_candidates=' .. #candidates)
print('observers=' .. #observers)
emit_stats('dense', dense)
emit_stats('patch', patch)
emit_stats('rays', rays)
print('clearance_count=' .. clearance_count)
print('clearance_nonzero=' .. clearance_nonzero)
print('clearance_mae=' ..
  (clearance_count > 0 and clearance_abs_sum / clearance_count or 0.0))
print('clearance_max=' .. clearance_max)
"""


def run_geometry_seed(seed: int, ordinal: int) -> dict[str, Any]:
    instance = (
        f"MLV3Geometry{ordinal:02d}"
        f"{seed:08X}{PROBE_RUN_TAG}"
    )
    session = phase2_probe.OwnedSoloSession(instance)
    result: dict[str, Any] = {"seed": seed, "instance": instance}
    try:
        result["launch"] = session.launch()
        session.wait_for_pipe()
        result["hub"] = session.wait_for_hub()
        bot_id = phase2_probe.create_probe_bot(session)
        result["bot_id"] = bot_id
        time.sleep(2.0)
        result["run_setup"] = enter_procedural_run(session, seed)
        phase2_probe.wait_for_materialized_bot(session, bot_id)
        result["geometry_ready"] = wait_for_geometry(session, bot_id)

        values = session.values(
            EXACT_GEOMETRY_FIDELITY_LUA.replace(
                "__BOT_ID__",
                str(bot_id),
            ),
            timeout=240.0,
        )
        result["metrics"] = values
        require(as_int(values, "circle_count") > 100, f"no circles: {values}")
        require(as_int(values, "polygon_count") > 0, f"no polygons: {values}")
        require(as_int(values, "patch_samples") > 0, f"no patch samples: {values}")
        require(as_int(values, "rays_samples") > 0, f"no ray samples: {values}")
        require(
            as_int(values, "patch_mismatches") == 0,
            f"exact patch geometry disagreed with native truth: {values}",
        )
        require(
            as_int(values, "rays_mismatches") == 0,
            f"exact ray geometry disagreed with native truth: {values}",
        )
        require(
            as_int(values, "clearance_nonzero") == 0,
            f"exact ray clearance disagreed with native truth: {values}",
        )
        return result
    finally:
        result["cleanup"] = session.close()


def create_status_probe_bot(
    session: phase2_probe.OwnedSoloSession,
) -> int:
    values = session.values(
        """
sd.bots.clear()
local player = assert(sd.player.get_state(), "missing player")
local id, err = sd.bots.create({
  name = "ML V3 Status Probe",
  profile = {
    element_id = 1,
    discipline_id = 2,
    level = 1,
    experience = 0,
    loadout = {
      primary_entry_index = 32,
      primary_combo_entry_index = 32,
      secondary_entry_indices = {},
    },
  },
  scene = {kind = "shared_hub"},
  ready = true,
  heading = 90.0,
  position = {
    x = (tonumber(player.x) or 0.0) + 112.0,
    y = tonumber(player.y) or 0.0,
  },
})
print("ok=" .. tostring(id ~= nil))
print("bot_id=" .. tostring(id or 0))
print("error=" .. tostring(err or ""))
"""
    )
    require(values.get("ok") == "true", f"status bot create failed: {values}")
    bot_id = as_int(values, "bot_id")
    require(bot_id > 0, f"status bot ID was invalid: {values}")
    return bot_id


def enable_manual_enemy_spawner(
    session: phase2_probe.OwnedSoloSession,
) -> dict[str, str]:
    values = session.values(
        """
local ok, active =
  sd.gameplay.set_manual_enemy_spawner_test_mode(true)
print("ok=" .. tostring(ok == true))
print("active=" .. tostring(active == true))
"""
    )
    require(
        values.get("ok") == "true" and values.get("active") == "true",
        f"manual enemy spawner could not be enabled: {values}",
    )
    return values


def spawn_probe_enemy(
    session: phase2_probe.OwnedSoloSession,
    bot_id: int,
    native_type_id: int,
    offset_x: float,
    *,
    freeze_on_spawn: bool,
    hp: float = 5000.0,
) -> dict[str, int | float]:
    requested = session.values(
        f"""
local bot = assert(sd.bots.get_state({bot_id}), "bot missing")
local x = (tonumber(bot.x) or 0.0) + {offset_x:.17g}
local y = tonumber(bot.y) or 0.0
local ok, err, request_id =
  sd.gameplay.spawn_manual_run_enemy({{
    type_id = {native_type_id},
    x = x,
    y = y,
    freeze_on_spawn = {str(freeze_on_spawn).lower()},
    allow_direct_arena_spawn = true,
  }})
print("ok=" .. tostring(ok == true))
print("error=" .. tostring(err or ""))
print("request_id=" .. tostring(request_id or 0))
print("x=" .. tostring(x))
print("y=" .. tostring(y))
"""
    )
    request_id = as_int(requested, "request_id")
    require(
        requested.get("ok") == "true" and request_id > 0,
        f"manual enemy {native_type_id} was rejected: {requested}",
    )

    deadline = time.monotonic() + 25.0
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = session.values(
            f"""
local result =
  sd.gameplay.get_last_manual_run_enemy_spawn({request_id}) or {{}}
if result.ok == true and
    (tonumber(result.actor_address) or 0) ~= 0 then
  sd.gameplay.set_run_enemy_health(
    result.actor_address,
    {hp:.17g},
    {hp:.17g})
end
print("available=" .. tostring(next(result) ~= nil))
print("ok=" .. tostring(result.ok == true))
print("actor=" .. tostring(result.actor_address or 0))
print("network_actor_id=" ..
  tostring(result.network_actor_id or 0))
print("error=" .. tostring(result.error or ""))
"""
        )
        if (
            last.get("available") == "true"
            and last.get("ok") == "true"
            and as_int(last, "actor") > 0
            and as_int(last, "network_actor_id") > 0
        ):
            return {
                "actor": as_int(last, "actor"),
                "network_actor_id": as_int(last, "network_actor_id"),
                "x": as_float(requested, "x"),
                "y": as_float(requested, "y"),
                "native_type_id": native_type_id,
            }
        time.sleep(0.1)
    raise V3NativeSeamsProbeFailure(
        f"manual enemy {native_type_id} did not materialize: {last}"
    )


def read_enemy_status(
    session: phase2_probe.OwnedSoloSession,
    network_actor_id: int,
) -> dict[str, str]:
    return session.values(
        f"""
local found = nil
for _, row in ipairs(
    (sd.world.get_replicated_actors() or {{}}).actors or {{}}) do
  if tonumber(row.network_actor_id) == {network_actor_id} then
    found = row
    break
  end
end
print("found=" .. tostring(found ~= nil))
print("resolved=" .. tostring(
  found and found.combat_status_resolved == true))
for _, name in ipairs({{"slowed", "frozen", "poisoned", "webbed"}}) do
  print(name .. "=" .. tostring(
    found and found[name] == true))
end
print("slow_ticks=" ..
  tostring(found and found.slow_remaining_ticks or 0))
print("frozen_ticks=" ..
  tostring(found and found.frozen_remaining_ticks or 0))
print("poison_ticks=" ..
  tostring(found and found.poison_remaining_ticks or 0))
print("webbed_ticks=" ..
  tostring(found and found.webbed_remaining_ticks or 0))
print("slow_seconds=" ..
  tostring(found and found.slow_remaining_seconds or 0))
print("frozen_seconds=" ..
  tostring(found and found.frozen_remaining_seconds or 0))
print("poison_seconds=" ..
  tostring(found and found.poison_remaining_seconds or 0))
print("webbed_seconds=" ..
  tostring(found and found.webbed_remaining_seconds or 0))
"""
    )


def wait_for_enemy_status(
    session: phase2_probe.OwnedSoloSession,
    network_actor_id: int,
    status: str,
    tick_key: str,
    *,
    timeout: float = 15.0,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = read_enemy_status(session, network_actor_id)
        if (
            last.get("found") == "true"
            and last.get("resolved") == "true"
            and last.get(status) == "true"
            and as_int(last, tick_key) > 0
        ):
            return last
        time.sleep(0.1)
    raise V3NativeSeamsProbeFailure(
        f"replicated enemy status {status} did not flip: {last}"
    )


def install_status_modifier_probe_handle(
    session: phase2_probe.OwnedSoloSession,
    enemy_actor: int,
) -> dict[str, str]:
    # This private acceptance helper reproduces the stock modifier route:
    # factory -> vtable OnApply -> actor smart-pointer list. Addresses remain
    # in temporary Lua globals and are never emitted by the public seam.
    values = session.values(
        f"""
_G.__ml_v3_status_modifier = nil
_G.__ml_v3_status_original_type = nil
_G.__ml_v3_status_original_duration = nil
local actor = {enemy_actor}
local factory =
  tonumber(sd.debug.resolve_game_address(0x005B7080)) or 0
local factory_context =
  tonumber(sd.debug.resolve_game_address(0x0081F630)) or 0
local operator_new =
  tonumber(sd.debug.resolve_game_address(0x0074784D)) or 0
local damage_target =
  tonumber(sd.debug.resolve_game_address(0x0081C6D8)) or 0
local modifier =
  factory ~= 0 and factory_context ~= 0 and
  sd.debug.call_thiscall_u32_ret_u32(
    factory, factory_context, 0x1B72) or nil
local seeded =
  type(modifier) == "number" and modifier ~= 0 and
  sd.debug.write_i32(modifier + 0x14, 6000) and
  sd.debug.write_float(modifier + 0x20, 0.0) and
  sd.debug.write_i8(modifier + 0x24, 1)
local vtable =
  seeded and (tonumber(sd.debug.read_u32(modifier)) or 0) or 0
local apply =
  vtable ~= 0 and
  (tonumber(sd.debug.read_u32(vtable + 0x24)) or 0) or 0
local saved_target =
  damage_target ~= 0 and
  (tonumber(sd.debug.read_u32(damage_target)) or 0) or 0
local context_ok =
  damage_target ~= 0 and
  sd.debug.write_u32(damage_target, actor)
local applied =
  context_ok and apply ~= 0 and
  sd.debug.call_thiscall_u32_ret_u32(
    apply, modifier, actor) ~= nil
if context_ok then
  sd.debug.write_u32(damage_target, saved_target)
end
local control =
  applied and operator_new ~= 0 and
  sd.debug.call_cdecl_u32_ret_u32(operator_new, 8) or nil
local control_ok =
  type(control) == "number" and control ~= 0 and
  sd.debug.write_u32(control, modifier) and
  sd.debug.write_i32(control + 4, 1)
local list = actor + 0x104
local list_vtable =
  control_ok and
  (tonumber(sd.debug.read_u32(list)) or 0) or 0
local add =
  list_vtable ~= 0 and
  (tonumber(sd.debug.read_u32(list_vtable + 0x10)) or 0) or 0
local attached =
  add ~= 0 and
  sd.debug.call_thiscall_u32(add, list, control)
if attached then
  _G.__ml_v3_status_modifier = modifier
  _G.__ml_v3_status_original_type = 0x1B72
  _G.__ml_v3_status_original_duration = 6000
end
print("factory_ok=" ..
  tostring(type(modifier) == "number" and modifier ~= 0))
print("seeded=" .. tostring(seeded == true))
print("applied=" .. tostring(applied == true))
print("attached=" .. tostring(attached == true))
print("found=" ..
  tostring(_G.__ml_v3_status_modifier ~= nil))
print("original_known=" ..
  tostring(_G.__ml_v3_status_original_type == 0x1B72))
"""
    )
    require(
        values.get("found") == "true"
        and values.get("original_known") == "true",
        f"native enemy modifier installation failed: {values}",
    )
    return values


def rewrite_status_modifier_type(
    session: phase2_probe.OwnedSoloSession,
    native_type_id: int,
) -> dict[str, str]:
    values = session.values(
        f"""
local modifier = _G.__ml_v3_status_modifier
local ok =
  type(modifier) == "number" and
  modifier ~= 0 and
  sd.debug.write_i32(modifier + 0x08, {native_type_id})
print("ok=" .. tostring(ok == true))
"""
    )
    require(
        values.get("ok") == "true",
        f"status modifier classifier probe write failed: {values}",
    )
    return values


def restore_status_modifier_probe(
    session: phase2_probe.OwnedSoloSession,
) -> dict[str, str]:
    return session.values(
        """
local modifier = _G.__ml_v3_status_modifier
local original_type = _G.__ml_v3_status_original_type
local original_duration = _G.__ml_v3_status_original_duration
local type_ok =
  type(modifier) == "number" and
  type(original_type) == "number" and
  sd.debug.write_i32(modifier + 0x08, original_type)
local duration_ok =
  type(modifier) == "number" and
  type(original_duration) == "number" and
  sd.debug.write_i32(modifier + 0x14, original_duration)
_G.__ml_v3_status_modifier = nil
_G.__ml_v3_status_original_type = nil
_G.__ml_v3_status_original_duration = nil
print("type_ok=" .. tostring(type_ok == true))
print("duration_ok=" .. tostring(duration_ok == true))
"""
    )


def prove_enemy_statuses(
    session: phase2_probe.OwnedSoloSession,
    bot_id: int,
) -> dict[str, Any]:
    enemy = spawn_probe_enemy(
        session,
        bot_id,
        0x3E9,
        30.0,
        freeze_on_spawn=True,
    )
    network_actor_id = int(enemy["network_actor_id"])
    baseline_deadline = time.monotonic() + 10.0
    baseline: dict[str, str] = {}
    while time.monotonic() < baseline_deadline:
        baseline = read_enemy_status(session, network_actor_id)
        if (
            baseline.get("found") == "true"
            and baseline.get("resolved") == "true"
        ):
            break
        time.sleep(0.1)
    require(
        baseline.get("found") == "true"
        and baseline.get("resolved") == "true",
        f"enemy status baseline was unavailable: {baseline}",
    )
    for status in ("slowed", "frozen", "poisoned", "webbed"):
        require(
            baseline.get(status) == "false",
            f"enemy status baseline was unexpectedly active: {baseline}",
        )

    handle = install_status_modifier_probe_handle(
        session,
        int(enemy["actor"]),
    )
    native = wait_for_enemy_status(
        session,
        network_actor_id,
        "poisoned",
        "poison_ticks",
    )
    mappings = (
        ("slowed", "slow_ticks", 0x1B69),
        ("frozen", "frozen_ticks", 0x1B6F),
        ("poisoned", "poison_ticks", 0x1B72),
        ("webbed", "webbed_ticks", 0x1B79),
    )
    transitions: dict[str, dict[str, str]] = {}
    try:
        for status, tick_key, type_id in mappings:
            rewrite_status_modifier_type(session, type_id)
            transitions[status] = wait_for_enemy_status(
                session,
                network_actor_id,
                status,
                tick_key,
            )
            seconds_key = {
                "slowed": "slow_seconds",
                "frozen": "frozen_seconds",
                "poisoned": "poison_seconds",
                "webbed": "webbed_seconds",
            }[status]
            ticks = as_int(transitions[status], tick_key)
            seconds = as_float(transitions[status], seconds_key)
            require(
                abs(seconds - ticks / 100.0) <= 0.011,
                f"{status} timer unit mismatch: {transitions[status]}",
            )
    finally:
        restored = restore_status_modifier_probe(session)
    require(
        restored.get("type_ok") == "true"
        and restored.get("duration_ok") == "true",
        f"status modifier probe did not restore native state: {restored}",
    )
    return {
        "baseline": baseline,
        "native_factory_status": native,
        "classifier_handle": handle,
        "transitions": transitions,
        "restored": restored,
    }


def read_hazard_census(
    session: phase2_probe.OwnedSoloSession,
) -> dict[str, str]:
    return session.values(
        """
local snapshot = sd.world.get_replicated_hazards() or {}
local known = {}
local unknown = 0
local forbidden = 0
local function inspect(value, seen)
  if type(value) ~= "table" or seen[value] then return end
  seen[value] = true
  for key, child in pairs(value) do
    if type(key) == "string" then
      local lowered = string.lower(key)
      if string.find(lowered, "address", 1, true) or
          string.find(lowered, "pointer", 1, true) or
          string.find(lowered, "exception", 1, true) or
          string.find(lowered, "seh", 1, true) then
        forbidden = forbidden + 1
      end
    end
    inspect(child, seen)
  end
end
inspect(snapshot, {})
for _, row in ipairs(snapshot.hazards or {}) do
  if row.type_known == true then
    known[tostring(row.kind)] =
      (known[tostring(row.kind)] or 0) + 1
  else
    unknown = unknown + 1
  end
end
print("valid=" .. tostring(snapshot.valid == true))
print("hazard_count=" .. tostring(snapshot.hazard_count or 0))
print("hazard_total_count=" ..
  tostring(snapshot.hazard_total_count or 0))
print("projectile=" .. tostring(known.projectile or 0))
print("area=" .. tostring(known.area or 0))
print("beam=" .. tostring(known.beam or 0))
print("unknown=" .. tostring(unknown))
print("forbidden_keys=" .. tostring(forbidden))
local synthetic = false
for _, row in ipairs(snapshot.hazards or {}) do
  if tonumber(row.native_type_id) == 0x0803 and
      row.hostile == true and row.active == true and
      row.type_known == false then
    synthetic = true
  end
end
print("synthetic_unknown=" .. tostring(synthetic))
"""
    )


def prove_hazards(
    session: phase2_probe.OwnedSoloSession,
    bot_id: int,
) -> dict[str, Any]:
    deadline = time.monotonic() + 15.0
    unknown: dict[str, str] = {}
    while time.monotonic() < deadline:
        unknown = read_hazard_census(session)
        if unknown.get("synthetic_unknown") == "true":
            break
        time.sleep(0.1)
    require(
        unknown.get("valid") == "true"
        and unknown.get("synthetic_unknown") == "true"
        and as_int(unknown, "unknown") >= 1
        and as_int(unknown, "forbidden_keys") == 0,
        f"unknown hostile hazard did not remain visible: {unknown}",
    )

    spawned = {
        "archer": spawn_probe_enemy(
            session,
            bot_id,
            0x3EA,
            180.0,
            freeze_on_spawn=False,
            hp=50000.0,
        ),
        "demon_skull": spawn_probe_enemy(
            session,
            bot_id,
            0x3F0,
            240.0,
            freeze_on_spawn=False,
            hp=50000.0,
        ),
        "dire_faculty": spawn_probe_enemy(
            session,
            bot_id,
            0x3F2,
            300.0,
            freeze_on_spawn=False,
            hp=50000.0,
        ),
    }
    # Trigger the recovered stock animation-event producers on real hostile
    # actors: Archer 0x11 -> Arrow, DemonSkull 0x1A -> EyeLaser, and
    # DireFaculty 0x20 with selector 0 -> RainOfBones. The resulting objects
    # enter the retail ActorWorld and are captured by the normal hazard scan.
    triggered = session.values(
        f"""
local operator_new =
  tonumber(sd.debug.resolve_game_address(0x0074784D)) or 0
local event =
  operator_new ~= 0 and
  sd.debug.call_cdecl_u32_ret_u32(operator_new, 0x20) or nil
local event_ok =
  type(event) == "number" and event ~= 0
local function dispatch(function_va, actor, event_id)
  local fn =
    tonumber(sd.debug.resolve_game_address(function_va)) or 0
  return
    event_ok and fn ~= 0 and
    sd.debug.write_i32(event + 0x14, event_id) and
    sd.debug.call_thiscall_u32(fn, actor, event)
end
local archer =
  {int(spawned["archer"]["actor"])}
local demon =
  {int(spawned["demon_skull"]["actor"])}
local dire =
  {int(spawned["dire_faculty"]["actor"])}
local bot =
  assert(sd.bots.get_state({bot_id}), "bot missing")
local archer_slot =
  sd.debug.read_i8(archer + 0x5C)
local target_slot =
  tonumber(bot.actor_slot) or -1
local archer_target_ok =
  type(archer_slot) == "number" and
  target_slot > 0 and
  sd.debug.write_i8(
    archer + 0x5C,
    target_slot)
local archer_ok =
  archer_target_ok and dispatch(
    0x00477B90,
    archer,
    0x11)
local archer_restore_ok =
  sd.debug.write_i8(
    archer + 0x5C,
    archer_slot)
local beam_ok =
  dispatch(
    0x00498180,
    demon,
    0x1A)
local selector_ok =
  sd.debug.write_i32(dire + 0x250, 0)
local area_ok =
  selector_ok and
  dispatch(0x004804D0, dire, 0x20)
local scene_counts = {{
  [0x07DA] = 0,
  [0x07FF] = 0,
  [0x0801] = 0,
}}
local scene_nonzero_slots = {{
  [0x07DA] = 0,
  [0x07FF] = 0,
  [0x0801] = 0,
}}
for _, row in ipairs(sd.world.list_actors() or {{}}) do
  local native_type_id = tonumber(row.object_type_id) or 0
  if scene_counts[native_type_id] ~= nil then
    scene_counts[native_type_id] =
      scene_counts[native_type_id] + 1
    if (tonumber(row.actor_slot) or 0) ~= 0 then
      scene_nonzero_slots[native_type_id] =
        scene_nonzero_slots[native_type_id] + 1
    end
  end
end
print("event_ok=" .. tostring(event_ok))
print("archer_target_ok=" ..
  tostring(archer_target_ok == true))
print("archer_restore_ok=" ..
  tostring(archer_restore_ok == true))
print("archer_ok=" .. tostring(archer_ok == true))
print("beam_ok=" .. tostring(beam_ok == true))
print("selector_ok=" .. tostring(selector_ok == true))
print("area_ok=" .. tostring(area_ok == true))
print("arrow_count=" .. tostring(scene_counts[0x07DA]))
print("arrow_hostile_slots=" ..
  tostring(scene_nonzero_slots[0x07DA]))
print("beam_count=" .. tostring(scene_counts[0x07FF]))
print("beam_hostile_slots=" ..
  tostring(scene_nonzero_slots[0x07FF]))
print("area_count=" .. tostring(scene_counts[0x0801]))
print("area_hostile_slots=" ..
  tostring(scene_nonzero_slots[0x0801]))
"""
    )
    require(
        all(
            triggered.get(key) == "true"
            for key in (
                "event_ok",
                "archer_target_ok",
                "archer_restore_ok",
                "archer_ok",
                "beam_ok",
                "selector_ok",
                "area_ok",
            )
        ),
        f"stock hazard event dispatch failed: {triggered}",
    )

    best: dict[str, str] = unknown
    seen_max = {"projectile": 0, "area": 0, "beam": 0}
    arrow_retriggers = 0
    arrow_retrigger_source = f"""
local operator_new =
  tonumber(sd.debug.resolve_game_address(0x0074784D)) or 0
local event =
  operator_new ~= 0 and
  sd.debug.call_cdecl_u32_ret_u32(operator_new, 0x20) or nil
local fn =
  tonumber(sd.debug.resolve_game_address(0x00477B90)) or 0
local archer = {int(spawned["archer"]["actor"])}
local bot =
  assert(sd.bots.get_state({bot_id}), "bot missing")
local target_slot =
  tonumber(bot.actor_slot) or -1
local original_slot =
  sd.debug.read_i8(archer + 0x5C)
local ready =
  type(event) == "number" and event ~= 0 and
  fn ~= 0 and
  target_slot > 0 and
  type(original_slot) == "number"
local dispatched =
  ready and
  sd.debug.write_i8(archer + 0x5C, target_slot) and
  sd.debug.write_i32(event + 0x14, 0x11) and
  sd.debug.call_thiscall_u32(fn, archer, event)
local restored =
  type(original_slot) == "number" and
  sd.debug.write_i8(archer + 0x5C, original_slot)
print("dispatched=" .. tostring(dispatched == true))
print("restored=" .. tostring(restored == true))
"""
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline:
        if seen_max["projectile"] == 0:
            retriggered = session.values(
                arrow_retrigger_source
            )
            require(
                retriggered.get("dispatched") == "true"
                and retriggered.get("restored") == "true",
                "stock Arrow retrigger failed: "
                f"{retriggered}",
            )
            arrow_retriggers += 1
        current = read_hazard_census(session)
        for kind in seen_max:
            seen_max[kind] = max(
                seen_max[kind],
                as_int(current, kind),
            )
        if (
            current.get("synthetic_unknown") == "true"
            and all(count > 0 for count in seen_max.values())
        ):
            best = current
            break
        if sum(seen_max.values()) > sum(
            as_int(best, kind) for kind in seen_max
        ):
            best = current
        time.sleep(0.05)
    require(
        seen_max["projectile"] > 0,
        "no known hostile projectile was captured: "
        f"triggered={triggered} snapshot={best}",
    )
    require(
        seen_max["area"] > 0,
        f"no known hostile area was captured: {best}",
    )
    require(
        seen_max["beam"] > 0,
        f"no known hostile beam was captured: {best}",
    )
    return {
        "unknown": unknown,
        "spawned_types": {
            name: int(row["native_type_id"])
            for name, row in spawned.items()
        },
        "native_event_dispatch": triggered,
        "arrow_retriggers": arrow_retriggers,
        "maximum_concurrent_by_kind": seen_max,
        "last": best,
    }


def run_status_hazard_probe() -> dict[str, Any]:
    instance = f"MLV3StatusHazard{PROBE_RUN_TAG}"
    session = phase2_probe.OwnedSoloSession(instance)
    result: dict[str, Any] = {"instance": instance}
    previous_unknown = os.environ.get(
        "SDMOD_TEST_UNKNOWN_HOSTILE_HAZARD"
    )
    previous_wslenv = os.environ.get("WSLENV")
    os.environ["SDMOD_TEST_UNKNOWN_HOSTILE_HAZARD"] = "1"
    if os.name != "nt":
        entries = [
            entry
            for entry in (previous_wslenv or "").split(":")
            if entry
        ]
        if "SDMOD_TEST_UNKNOWN_HOSTILE_HAZARD" not in entries:
            entries.append("SDMOD_TEST_UNKNOWN_HOSTILE_HAZARD")
        os.environ["WSLENV"] = ":".join(entries)
    try:
        result["launch"] = session.launch()
    finally:
        if previous_unknown is None:
            os.environ.pop(
                "SDMOD_TEST_UNKNOWN_HOSTILE_HAZARD",
                None,
            )
        else:
            os.environ[
                "SDMOD_TEST_UNKNOWN_HOSTILE_HAZARD"
            ] = previous_unknown
        if previous_wslenv is None:
            os.environ.pop("WSLENV", None)
        else:
            os.environ["WSLENV"] = previous_wslenv
    try:
        session.wait_for_pipe()
        result["hub"] = session.wait_for_hub()
        bot_id = create_status_probe_bot(session)
        result["bot_id"] = bot_id
        result["run_setup"] = enter_procedural_run(
            session,
            0x33333333,
        )
        phase2_probe.wait_for_materialized_bot(session, bot_id)
        enable_manual_enemy_spawner(session)
        result["vital_guard"] = session.values(
            """
local player = assert(sd.player.get_state(), "player missing")
local progression =
  tonumber(player.progression_address) or 0
local hp_offset =
  tonumber(sd.debug.layout_offset("progression_hp")) or 0
local max_hp_offset =
  tonumber(sd.debug.layout_offset("progression_max_hp")) or 0
local ok =
  progression ~= 0 and
  sd.debug.write_float(progression + max_hp_offset, 1000000.0) and
  sd.debug.write_float(progression + hp_offset, 1000000.0)
print("ok=" .. tostring(ok == true))
"""
        )
        require(
            result["vital_guard"].get("ok") == "true",
            f"could not protect disposable hazard probe: {result['vital_guard']}",
        )
        result["statuses"] = prove_enemy_statuses(session, bot_id)
        result["hazards"] = prove_hazards(session, bot_id)
        return result
    finally:
        result["cleanup"] = session.close()


def active_drop_ids(
    session: phase2_probe.OwnedSoloSession,
) -> set[int]:
    values = session.values(
        """
for index, row in ipairs(
    (sd.world.get_replicated_loot() or {}).drops or {}) do
  if row.active == true then
    print("drop." .. tostring(index) .. "=" ..
      tostring(row.network_drop_id or 0))
  end
end
"""
    )
    return {
        int(value)
        for key, value in values.items()
        if key.startswith("drop.") and int(value) > 0
    }


def potion_count(
    session: phase2_probe.OwnedSoloSession,
    bot_id: int,
    subtype: int,
) -> tuple[int, int]:
    values = session.values(
        f"""
local details =
  sd.bots.get_inventory_details({bot_id}) or {{}}
local count = 0
for _, row in ipairs(details.potions or {{}}) do
  if tonumber(row.stock_subtype) == {subtype} and
      tonumber(row.content_id) == 0 then
    count = count + (tonumber(row.count) or 0)
  end
end
print("count=" .. tostring(count))
print("revision=" ..
  tostring(details.inventory_revision or 0))
"""
    )
    return as_int(values, "count"), as_int(values, "revision")


def separate_bot_from_local_player(
    session: phase2_probe.OwnedSoloSession,
    bot_id: int,
) -> dict[str, str]:
    values = session.values(
        f"""
local player = assert(sd.player.get_state(), "player missing")
local bot = assert(sd.bots.get_state({bot_id}), "bot missing")
local px = tonumber(player.x) or 0.0
local py = tonumber(player.y) or 0.0
local bx = tonumber(bot.x) or 0.0
local by = tonumber(bot.y) or 0.0
local function distance(x, y)
  local dx = x - px
  local dy = y - py
  return math.sqrt(dx * dx + dy * dy)
end
local candidates = {{
  {{ bx + 112.0, by }},
  {{ bx - 112.0, by }},
  {{ bx, by + 112.0 }},
  {{ bx, by - 112.0 }},
}}
local accepted = distance(bx, by) >= 80.0
local target_x = bx
local target_y = by
if not accepted then
  for _, candidate in ipairs(candidates) do
    if distance(candidate[1], candidate[2]) >= 80.0 and
        sd.nav.test_segment(
          bx,
          by,
          candidate[1],
          candidate[2]) then
      target_x = candidate[1]
      target_y = candidate[2]
      accepted = sd.bots.update({{
        id = {bot_id},
        position = {{ x = target_x, y = target_y }},
      }}) == true
      if accepted then break end
    end
  end
end
local updated = assert(sd.bots.get_state({bot_id}), "bot missing")
local ux = tonumber(updated.x) or target_x
local uy = tonumber(updated.y) or target_y
print("ok=" .. tostring(accepted == true))
print("distance=" .. tostring(distance(ux, uy)))
print("x=" .. tostring(ux))
print("y=" .. tostring(uy))
"""
    )
    require(
        values.get("ok") == "true"
        and as_float(values, "distance") >= 80.0,
        "could not separate the synthetic participant from the local "
        f"player before stock pickup proof: {values}",
    )
    return values


def spawn_and_pick_up_potion(
    session: phase2_probe.OwnedSoloSession,
    bot_id: int,
    subtype: int,
) -> dict[str, Any]:
    # Host deactivation completes at the post-stock app-tick boundary. Give
    # the retired Sack actor one more boundary before reusing the arena's
    # stock potion-drop path for the next subtype.
    time.sleep(0.75)
    before_ids = active_drop_ids(session)
    before_count, before_revision = potion_count(
        session,
        bot_id,
        subtype,
    )
    spawned = session.values(
        f"""
local bot = assert(sd.bots.get_state({bot_id}), "bot missing")
local ok, err = sd.world.spawn_reward({{
  kind = "potion{subtype}",
  amount = 1,
  x = tonumber(bot.x) or 0.0,
  y = tonumber(bot.y) or 0.0,
}})
print("ok=" .. tostring(ok == true))
print("error=" .. tostring(err or ""))
"""
    )
    require(
        spawned.get("ok") == "true",
        f"stock potion{subtype} spawn failed: {spawned}",
    )

    drop_id = 0
    deadline = time.monotonic() + 15.0
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = session.values(
            f"""
for index, row in ipairs(
    (sd.world.get_replicated_loot() or {{}}).drops or {{}}) do
  if row.active == true and
      tonumber(row.item_type_id) == 7001 and
      tonumber(row.item_slot) == {subtype} then
    print("drop." .. tostring(index) .. "=" ..
      tostring(row.network_drop_id or 0))
  end
end
"""
        )
        candidates = {
            int(value)
            for value in last.values()
            if int(value) > 0 and int(value) not in before_ids
        }
        if candidates:
            drop_id = min(candidates)
            break
        time.sleep(0.05)
    require(
        drop_id > 0,
        f"stock potion{subtype} did not enter replicated loot: {last}",
    )

    pickup = session.values(
        f"""
local ok, sequence_or_error =
  sd.world.request_loot_pickup({drop_id}, {bot_id})
print("ok=" .. tostring(ok == true))
print("sequence=" ..
  tostring(type(sequence_or_error) == "number" and
    sequence_or_error or 0))
print("error=" ..
  tostring(type(sequence_or_error) == "string" and
    sequence_or_error or ""))
"""
    )
    require(
        pickup.get("ok") == "true",
        f"stock potion{subtype} pickup was rejected: {pickup}",
    )

    deadline = time.monotonic() + 15.0
    after_count = before_count
    after_revision = before_revision
    while time.monotonic() < deadline:
        after_count, after_revision = potion_count(
            session,
            bot_id,
            subtype,
        )
        if (
            after_count == before_count + 1
            and after_revision > before_revision
        ):
            break
        time.sleep(0.05)
    require(
        after_count == before_count + 1
        and after_revision > before_revision,
        "stock potion pickup did not round-trip into the synthetic "
        f"inventory: subtype={subtype} count={before_count}->{after_count} "
        f"revision={before_revision}->{after_revision}",
    )
    return {
        "subtype": subtype,
        "drop_id": drop_id,
        "pickup_sequence": as_int(pickup, "sequence"),
        "count_before": before_count,
        "count_after": after_count,
        "revision_before": before_revision,
        "revision_after": after_revision,
    }


def prove_inventory_schema_and_timers(
    session: phase2_probe.OwnedSoloSession,
    bot_id: int,
) -> dict[str, str]:
    values = session.values(
        f"""
local bot = assert(sd.bots.get_state({bot_id}), "bot missing")
local progression =
  tonumber(bot.progression_runtime_state_address) or 0
local offsets = {{
  damage = tonumber(sd.debug.layout_offset(
    "progression_damage_x4_remaining_ticks")) or 0,
  poison = tonumber(sd.debug.layout_offset(
    "progression_poison_immunity_remaining_ticks")) or 0,
  concentration = tonumber(sd.debug.layout_offset(
    "progression_all_concentration_remaining_ticks")) or 0,
}}
local original = {{
  damage = sd.debug.read_i32(progression + offsets.damage),
  poison = sd.debug.read_i32(progression + offsets.poison),
  concentration =
    sd.debug.read_i32(progression + offsets.concentration),
}}
local writes_ok =
  progression ~= 0 and
  sd.debug.write_i32(progression + offsets.damage, 6000) and
  sd.debug.write_i32(progression + offsets.poison, 1000) and
  sd.debug.write_i32(progression + offsets.concentration, 3000)
local details =
  sd.bots.get_inventory_details({bot_id}) or {{}}
local forbidden = 0
local address_strings = 0
local function inspect(value, seen)
  if type(value) ~= "table" or seen[value] then return end
  seen[value] = true
  for key, child in pairs(value) do
    if type(key) == "string" then
      local lowered = string.lower(key)
      if string.find(lowered, "address", 1, true) or
          string.find(lowered, "pointer", 1, true) or
          string.find(lowered, "exception", 1, true) or
          string.find(lowered, "seh", 1, true) then
        forbidden = forbidden + 1
      end
    end
    if type(child) == "string" and
        string.match(child, "0x%x%x%x%x%x%x") then
      address_strings = address_strings + 1
    end
    inspect(child, seen)
  end
end
inspect(details, {{}})
local runtime = sd.runtime.get_multiplayer_state() or {{}}
local content_rows = 0
local stock_content_zero = true
for _, participant in ipairs(runtime.participants or {{}}) do
  if tonumber(participant.participant_id) == {bot_id} then
    for _, item in ipairs(
        (participant.owned_progression or {{}})
          .inventory_items or {{}}) do
      if tonumber(item.type_id) == 7001 then
        content_rows = content_rows + 1
        if item.content_id == nil or
            tonumber(item.content_id) ~= 0 then
          stock_content_zero = false
        end
      end
    end
  end
end
local stock_rows = 0
local identity_rows = 0
local supported = {{}}
for _, row in ipairs(details.potions or {{}}) do
  if tonumber(row.content_id) == 0 and
      tonumber(row.stock_subtype) >= 0 and
      tonumber(row.stock_subtype) <= 5 then
    stock_rows = stock_rows + 1
    if type(row.identity_key) == "string" and
        row.identity_key ~= "" and row.effect_resolved == true then
      identity_rows = identity_rows + 1
    end
    supported[tostring(row.stock_subtype)] =
      row.synthetic_use_supported == true
  end
end
local present_equipment = 0
local catalog_equipment = 0
for _, row in ipairs(details.equipped or {{}}) do
  if row.present == true then present_equipment = present_equipment + 1 end
  if row.catalog_resolved == true then
    catalog_equipment = catalog_equipment + 1
  end
end
local restore_ok =
  sd.debug.write_i32(
    progression + offsets.damage, original.damage or 0) and
  sd.debug.write_i32(
    progression + offsets.poison, original.poison or 0) and
  sd.debug.write_i32(
    progression + offsets.concentration,
    original.concentration or 0)
print("writes_ok=" .. tostring(writes_ok == true))
print("timers_resolved=" ..
  tostring(details.timers_resolved == true))
print("damage_seconds=" ..
  tostring(details.damage_x4_remaining_seconds or -1))
print("poison_seconds=" ..
  tostring(details.poison_immunity_remaining_seconds or -1))
print("concentration_seconds=" ..
  tostring(details.all_concentration_remaining_seconds or -1))
print("stock_rows=" .. tostring(stock_rows))
print("identity_rows=" .. tostring(identity_rows))
print("content_rows=" .. tostring(content_rows))
print("stock_content_zero=" .. tostring(stock_content_zero))
print("equipped_rows=" .. tostring(#(details.equipped or {{}})))
print("present_equipment=" .. tostring(present_equipment))
print("catalog_equipment=" .. tostring(catalog_equipment))
print("supported_0=" .. tostring(supported["0"] == true))
print("supported_1=" .. tostring(supported["1"] == true))
print("supported_2=" .. tostring(supported["2"] == true))
print("supported_3=" .. tostring(supported["3"] == true))
print("supported_4=" .. tostring(supported["4"] == true))
print("supported_5=" .. tostring(supported["5"] == true))
print("forbidden_keys=" .. tostring(forbidden))
print("address_strings=" .. tostring(address_strings))
print("restore_ok=" .. tostring(restore_ok == true))
"""
    )
    require(
        values.get("writes_ok") == "true"
        and values.get("timers_resolved") == "true"
        and values.get("restore_ok") == "true",
        f"live inventory timers were not resolved/restored: {values}",
    )
    require(
        59.0 <= as_float(values, "damage_seconds") <= 60.0
        and 9.0 <= as_float(values, "poison_seconds") <= 10.0
        and 29.0 <= as_float(values, "concentration_seconds") <= 30.0,
        f"inventory timer units were not 100 Hz: {values}",
    )
    require(
        as_int(values, "stock_rows") == 6
        and as_int(values, "identity_rows") == 6
        and as_int(values, "content_rows") >= 6
        and values.get("stock_content_zero") == "true",
        f"stock identity/content IDs did not round-trip: {values}",
    )
    require(
        as_int(values, "equipped_rows") == 7,
        f"equipment slot census was not seven: {values}",
    )
    expected_support = {
        0: "true",
        1: "true",
        2: "false",
        3: "false",
        4: "false",
        5: "true",
    }
    for subtype, expected in expected_support.items():
        require(
            values.get(f"supported_{subtype}") == expected,
            f"synthetic support mismatch for subtype {subtype}: {values}",
        )
    require(
        as_int(values, "forbidden_keys") == 0
        and as_int(values, "address_strings") == 0,
        f"inventory details exposed native diagnostics: {values}",
    )
    return values


def use_stock_potion(
    session: phase2_probe.OwnedSoloSession,
    bot_id: int,
    subtype: int,
    *,
    supported: bool,
) -> dict[str, str]:
    values = session.values(
        f"""
local bot_before = assert(sd.bots.get_state({bot_id}), "bot missing")
local progression =
  tonumber(bot_before.progression_runtime_state_address) or 0
local hp_offset =
  tonumber(sd.debug.layout_offset("progression_hp")) or 0
local max_hp_offset =
  tonumber(sd.debug.layout_offset("progression_max_hp")) or 0
local mp_offset =
  tonumber(sd.debug.layout_offset("progression_mp")) or 0
local max_mp_offset =
  tonumber(sd.debug.layout_offset("progression_max_mp")) or 0
local max_hp =
  tonumber(sd.debug.read_float(progression + max_hp_offset)) or 0
local max_mp =
  tonumber(sd.debug.read_float(progression + max_mp_offset)) or 0
local need_hp = {str(subtype in (0, 5)).lower()}
local need_mp = {str(subtype in (1, 5)).lower()}
local vitals_prepared =
  progression ~= 0 and max_hp > 0 and max_mp > 0
if vitals_prepared and need_hp then
  vitals_prepared =
    sd.debug.write_float(progression + hp_offset, max_hp * 0.25)
end
if vitals_prepared and need_mp then
  vitals_prepared =
    sd.debug.write_float(progression + mp_offset, max_mp * 0.25)
end
local before = assert(
  sd.bots.get_inventory_details({bot_id}),
  "inventory missing")
local slot = 0
local count_before = 0
for index, row in ipairs(before.potions or {{}}) do
  if tonumber(row.stock_subtype) == {subtype} and
      tonumber(row.content_id) == 0 then
    slot = index
    count_before = tonumber(row.count) or 0
    break
  end
end
local revision_before = tonumber(before.inventory_revision) or 0
local ok, result_or_error = sd.bots.use_consumable(
  {bot_id},
  {{
    potion_slot = slot,
    inventory_revision = revision_before,
  }})
local duplicate_ok, duplicate_result = sd.bots.use_consumable(
  {bot_id},
  {{
    potion_slot = slot,
    inventory_revision = revision_before,
  }})
local after = assert(
  sd.bots.get_inventory_details({bot_id}),
  "inventory missing after use")
local count_after = 0
for _, row in ipairs(after.potions or {{}}) do
  if tonumber(row.stock_subtype) == {subtype} and
      tonumber(row.content_id) == 0 then
    count_after = count_after + (tonumber(row.count) or 0)
  end
end
local bot_after = assert(sd.bots.get_state({bot_id}), "bot missing after")
local runtime = sd.runtime.get_multiplayer_state() or {{}}
local runtime_hp = -1
local runtime_mp = -1
for _, participant in ipairs(runtime.participants or {{}}) do
  if tonumber(participant.participant_id) == {bot_id} then
    runtime_hp = tonumber(participant.life_current) or -1
    runtime_mp = tonumber(participant.mana_current) or -1
  end
end
print("vitals_prepared=" .. tostring(vitals_prepared == true))
print("slot=" .. tostring(slot))
print("count_before=" .. tostring(count_before))
print("revision_before=" .. tostring(revision_before))
print("ok=" .. tostring(ok == true))
print("error=" ..
  tostring(type(result_or_error) == "string" and
    result_or_error or ""))
print("use_id=" ..
  tostring(type(result_or_error) == "table" and
    result_or_error.use_id or 0))
print("result_revision=" ..
  tostring(type(result_or_error) == "table" and
    result_or_error.inventory_revision or 0))
print("result_subtype=" ..
  tostring(type(result_or_error) == "table" and
    result_or_error.stock_subtype or -1))
print("result_content_id=" ..
  tostring(type(result_or_error) == "table" and
    result_or_error.content_id or -1))
print("duplicate_ok=" .. tostring(duplicate_ok == true))
print("duplicate_error=" ..
  tostring(type(duplicate_result) == "string" and
    duplicate_result or ""))
print("count_after=" .. tostring(count_after))
print("revision_after=" ..
  tostring(after.inventory_revision or 0))
print("hp_after=" .. tostring(bot_after.hp or -1))
print("max_hp=" .. tostring(bot_after.max_hp or -1))
print("mp_after=" .. tostring(bot_after.mp or -1))
print("max_mp=" .. tostring(bot_after.max_mp or -1))
print("runtime_hp=" .. tostring(runtime_hp))
print("runtime_mp=" .. tostring(runtime_mp))
"""
    )
    require(
        as_int(values, "slot") > 0
        and as_int(values, "count_before") > 0,
        f"stock subtype {subtype} was not selectable: {values}",
    )
    if supported:
        require(
            values.get("vitals_prepared") == "true"
            and values.get("ok") == "true"
            and as_int(values, "use_id") > 0
            and as_int(values, "result_subtype", -1) == subtype
            and as_int(values, "result_content_id", -1) == 0,
            f"stock subtype {subtype} use failed: {values}",
        )
        require(
            values.get("duplicate_ok") == "false"
            and "stale inventory_revision" in values.get(
                "duplicate_error",
                "",
            )
            and as_int(values, "count_after")
            == as_int(values, "count_before") - 1
            and as_int(values, "revision_after")
            == as_int(values, "revision_before") + 1
            and as_int(values, "result_revision")
            == as_int(values, "revision_after"),
            f"stock subtype {subtype} was not exactly once: {values}",
        )
        if subtype in (0, 5):
            require(
                abs(
                    as_float(values, "hp_after")
                    - as_float(values, "max_hp")
                )
                <= 0.02,
                f"stock subtype {subtype} did not restore HP: {values}",
            )
        if subtype in (1, 5):
            require(
                abs(
                    as_float(values, "mp_after")
                    - as_float(values, "max_mp")
                )
                <= 0.02,
                f"stock subtype {subtype} did not restore mana: {values}",
            )
        require(
            abs(
                as_float(values, "runtime_hp")
                - as_float(values, "hp_after")
            )
            <= 0.02
            and abs(
                as_float(values, "runtime_mp")
                - as_float(values, "mp_after")
            )
            <= 0.02,
            f"stock subtype {subtype} vitals were not replication-coherent: "
            f"{values}",
        )
    else:
        require(
            values.get("ok") == "false"
            and "no proven synthetic-safe effect path"
            in values.get("error", "")
            and values.get("duplicate_ok") == "false"
            and as_int(values, "count_after")
            == as_int(values, "count_before")
            and as_int(values, "revision_after")
            == as_int(values, "revision_before"),
            f"unsupported stock subtype {subtype} mutated state: {values}",
        )
    for key in ("error", "duplicate_error"):
        lowered = values.get(key, "").lower()
        require(
            "seh" not in lowered and "exception" not in lowered
            and "0x" not in lowered,
            f"consumable error exposed native diagnostics: {values}",
        )
    return values


def run_inventory_consumable_probe() -> dict[str, Any]:
    instance = f"MLV3Inventory{PROBE_RUN_TAG}"
    session = phase2_probe.OwnedSoloSession(instance)
    result: dict[str, Any] = {"instance": instance}
    try:
        result["launch"] = session.launch()
        session.wait_for_pipe()
        result["hub"] = session.wait_for_hub()
        bot_id = phase2_probe.create_probe_bot(session)
        result["bot_id"] = bot_id
        result["run_setup"] = enter_procedural_run(
            session,
            0x44444444,
        )
        phase2_probe.wait_for_materialized_bot(session, bot_id)
        result["pickup_position"] = (
            separate_bot_from_local_player(
                session,
                bot_id,
            )
        )
        result["pickup_ranges"] = session.values(
            f"""
local player = assert(sd.player.get_state(), "player missing")
local bot = assert(sd.bots.get_state({bot_id}), "bot missing")
local offset =
  tonumber(sd.debug.layout_offset("progression_pickup_range")) or 0
local player_progression =
  tonumber(player.progression_address) or 0
local bot_progression =
  tonumber(bot.progression_runtime_state_address) or 0
print("player=" .. tostring(
  sd.debug.read_float(player_progression + offset) or 0))
print("bot=" .. tostring(
  sd.debug.read_float(bot_progression + offset) or 0))
"""
        )
        local_before = session.values(
            """
local player = assert(sd.player.get_state(), "player missing")
print("hp=" .. tostring(player.hp or 0))
print("mp=" .. tostring(player.mp or 0))
"""
        )
        result["local_before"] = local_before
        result["pickups"] = [
            spawn_and_pick_up_potion(
                session,
                bot_id,
                subtype,
            )
            for subtype in range(6)
        ]
        result["details"] = prove_inventory_schema_and_timers(
            session,
            bot_id,
        )
        supported = {0, 1, 5}
        result["uses"] = {
            str(subtype): use_stock_potion(
                session,
                bot_id,
                subtype,
                supported=subtype in supported,
            )
            for subtype in range(6)
        }
        local_after = session.values(
            """
local player = assert(sd.player.get_state(), "player missing")
print("hp=" .. tostring(player.hp or 0))
print("mp=" .. tostring(player.mp or 0))
"""
        )
        result["local_after"] = local_after
        require(
            abs(
                as_float(local_after, "hp")
                - as_float(local_before, "hp")
            )
            <= 0.02
            and abs(
                as_float(local_after, "mp")
                - as_float(local_before, "mp")
            )
            <= 0.02,
            "synthetic consumable use mutated the local player: "
            f"before={local_before} after={local_after}",
        )
        return result
    finally:
        result["cleanup"] = session.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--geometry-only",
        action="store_true",
        help="run only the three-seed exact-geometry acceptance",
    )
    parser.add_argument(
        "--status-hazard-only",
        action="store_true",
        help="run only replicated enemy-status and hazard acceptance",
    )
    parser.add_argument(
        "--inventory-only",
        action="store_true",
        help="run only inventory and synthetic consumable acceptance",
    )
    parser.add_argument(
        "--seed",
        type=lambda value: int(value, 0),
        action="append",
        help="override the geometry seed set; repeat for multiple seeds",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_PATH,
        help="JSON evidence path",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    selected_modes = sum(
        (
            args.geometry_only,
            args.status_hazard_only,
            args.inventory_only,
        )
    )
    if selected_modes > 1:
        raise SystemExit(
            "select at most one of --geometry-only, "
            "--status-hazard-only, or --inventory-only"
        )
    seeds = tuple(args.seed or GEOMETRY_SEEDS)
    document: dict[str, Any] = {
        "schema": "ml-bot-v3-native-seams-live-probe-v1",
        "started_unix": time.time(),
        "geometry": [],
    }
    try:
        if not args.status_hazard_only and not args.inventory_only:
            for ordinal, seed in enumerate(seeds, start=1):
                document["geometry"].append(
                    run_geometry_seed(seed, ordinal)
                )
        if not args.geometry_only and not args.inventory_only:
            document["status_hazards"] = (
                run_status_hazard_probe()
            )
        if not args.geometry_only and not args.status_hazard_only:
            document["inventory_consumables"] = (
                run_inventory_consumable_probe()
            )
        document["passed"] = True
        return_code = 0
    except BaseException as exc:
        document["passed"] = False
        document["error"] = f"{type(exc).__name__}: {exc}"
        return_code = 1
    finally:
        document["finished_unix"] = time.time()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(document, indent=2, sort_keys=True))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
