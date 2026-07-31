"""Retail Solomon-Dig routing for disposable wave-training episodes."""

from __future__ import annotations

import math
import time
from typing import Callable


ValuesRunner = Callable[[str, float], dict[str, str]]

ROUTE_CONTROLLER_GLOBAL = "__sdmod_ml_wave_route"
ROUTE_ARRIVAL_RADIUS = 34.0


class WaveEpisodeError(RuntimeError):
    """Raised when the stock Solomon-to-wave transition does not converge."""


def _number(
    values: dict[str, str],
    key: str,
    default: float = math.nan,
) -> float:
    try:
        value = float(values.get(key, str(default)))
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def _integer(
    values: dict[str, str],
    key: str,
    default: int = 0,
) -> int:
    try:
        return int(values.get(key, str(default)), 0)
    except (TypeError, ValueError):
        value = _number(values, key, float(default))
        return int(value) if math.isfinite(value) else default


def _boolean(values: dict[str, str], key: str) -> bool:
    return values.get(key, "").casefold() == "true"


def _remaining(deadline: float, label: str) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0.0:
        raise WaveEpisodeError(f"timed out during {label}")
    return remaining


def _wait(
    operation: Callable[[], dict[str, str]],
    predicate: Callable[[dict[str, str]], bool],
    *,
    deadline: float,
    label: str,
    interval: float = 0.1,
) -> dict[str, str]:
    last: dict[str, str] = {}
    last_error = ""
    while time.monotonic() < deadline:
        try:
            last = operation()
            last_error = ""
            if predicate(last):
                return last
        except (OSError, ValueError, WaveEpisodeError) as error:
            last_error = str(error)
        time.sleep(interval)
    raise WaveEpisodeError(
        f"timed out waiting for {label}; last={last}; "
        f"last_error={last_error!r}"
    )


ROUTE_CONTROLLER_SOURCE = f"""
local prior = rawget(_G, '{ROUTE_CONTROLLER_GLOBAL}')
if type(prior) == 'table' then prior.armed = false end
local controller = {{
  armed = true,
  destination = nil,
  arrival = nil,
  destination_distance = -1,
  movement_frames = 0,
  arrival_radius = {ROUTE_ARRIVAL_RADIUS:.1f},
}}
rawset(_G, '{ROUTE_CONTROLLER_GLOBAL}', controller)

local function normalize(x, y)
  local length = math.sqrt(x * x + y * y)
  if length <= 0.0001 then return 0.0, 0.0, 0.0 end
  return x / length, y / length, length
end

local function drive_route()
  local active = rawget(_G, '{ROUTE_CONTROLLER_GLOBAL}')
  if active ~= controller or active.armed ~= true then return end
  local scene = sd.world.get_scene() or {{}}
  if tostring(scene.name or scene.kind or '') ~= 'testrun' then return end
  local player = sd.player.get_state() or {{}}
  local x, y = tonumber(player.x), tonumber(player.y)
  if x == nil or y == nil or
      (tonumber(player.actor_address) or 0) == 0 then
    return
  end
  pcall(sd.input.set_native_control_allowance_frames, 120)
  if type(active.destination) ~= 'table' then return end
  local dx = (tonumber(active.destination.x) or x) - x
  local dy = (tonumber(active.destination.y) or y) - y
  local nx, ny, remaining = normalize(dx, dy)
  active.destination_distance = remaining
  if remaining <= active.arrival_radius then
    active.arrival = {{x = x, y = y}}
    active.destination = nil
    pcall(sd.input.hold_movement_frames, 0.0, 0.0, 1)
    return
  end
  local ok, accepted = pcall(
    sd.input.hold_movement_frames, nx, ny, 1)
  if ok and accepted == true then
    active.movement_frames = active.movement_frames + 1
  end
end

sd.events.on('runtime.tick', drive_route)
print('armed=' .. tostring(controller.armed))
"""


ROUTE_STATE = f"""
local player = sd.player.get_state() or {{}}
local controller =
  rawget(_G, '{ROUTE_CONTROLLER_GLOBAL}') or {{}}
local solomon_ok, solomon = pcall(sd.hub.get_solomon_dig_state)
solomon = solomon_ok and solomon or {{}}
print('player_present=' .. tostring(
  (tonumber(player.actor_address) or 0) ~= 0))
print('player_x=' .. tostring(player.x or 0))
print('player_y=' .. tostring(player.y or 0))
print('destination_active=' ..
  tostring(type(controller.destination) == 'table'))
print('arrival_valid=' ..
  tostring(type(controller.arrival) == 'table'))
print('arrival_x=' .. tostring(
  type(controller.arrival) == 'table' and controller.arrival.x or 0))
print('arrival_y=' .. tostring(
  type(controller.arrival) == 'table' and controller.arrival.y or 0))
print('movement_frames=' ..
  tostring(controller.movement_frames or 0))
print('solomon_present=' .. tostring(solomon_ok and solomon.valid == true))
print('solomon_x=' .. tostring(solomon.x or 0))
print('solomon_y=' .. tostring(solomon.y or 0))
print('solomon_state=' .. tostring(solomon.interaction_state or -1))
print('solomon_acquired=' ..
  tostring(solomon.participant_acquired == true))
print('solomon_target_slot=' ..
  tostring(solomon.target_gameplay_slot or -1))
"""


def _normalize(x: float, y: float) -> tuple[float, float]:
    length = math.hypot(x, y)
    if length <= 0.0001:
        raise WaveEpisodeError("cannot normalize a zero-length route")
    return x / length, y / length


def _openable_segments(
    run: ValuesRunner,
    participant_id: int,
    *,
    deadline: float,
) -> list[dict[str, float | int]]:
    source = f"""
local geometry, error_message =
  sd.nav.get_collision_geometry({participant_id})
print('valid=' .. tostring(
  type(geometry) == 'table' and geometry.valid == true))
print('refresh_pending=' .. tostring(
  type(geometry) == 'table' and geometry.refresh_pending == true))
print('error=' .. tostring(error_message or ''))
local count = 0
for _, row in ipairs(
    type(geometry) == 'table' and geometry.segments or {{}}) do
  if row.openable == true then
    count = count + 1
    local prefix = 'segment.' .. tostring(count) .. '.'
    print(prefix .. 'geometry_id=' .. tostring(row.geometry_id or 0))
    print(prefix .. 'start_x=' .. tostring(row.start_x or 0))
    print(prefix .. 'start_y=' .. tostring(row.start_y or 0))
    print(prefix .. 'end_x=' .. tostring(row.end_x or 0))
    print(prefix .. 'end_y=' .. tostring(row.end_y or 0))
  end
end
print('count=' .. tostring(count))
"""
    observed = _wait(
        lambda: run(source, min(10.0, _remaining(deadline, "geometry"))),
        lambda row: (
            _boolean(row, "valid")
            and not _boolean(row, "refresh_pending")
            and _integer(row, "count") > 0
        ),
        deadline=deadline,
        label="a coherent openable collision segment",
    )
    result: list[dict[str, float | int]] = []
    for index in range(1, _integer(observed, "count") + 1):
        prefix = f"segment.{index}."
        result.append(
            {
                "geometry_id": _integer(
                    observed, prefix + "geometry_id"
                ),
                "start_x": _number(observed, prefix + "start_x"),
                "start_y": _number(observed, prefix + "start_y"),
                "end_x": _number(observed, prefix + "end_x"),
                "end_y": _number(observed, prefix + "end_y"),
            }
        )
    return result


def _select_gate(
    start: tuple[float, float],
    solomon: tuple[float, float],
    segments: list[dict[str, float | int]],
) -> dict[str, object]:
    route = _normalize(solomon[0] - start[0], solomon[1] - start[1])
    route_length = math.dist(start, solomon)
    candidates: list[tuple[float, float, dict[str, float | int]]] = []
    for segment in segments:
        midpoint = (
            (float(segment["start_x"]) + float(segment["end_x"])) * 0.5,
            (float(segment["start_y"]) + float(segment["end_y"])) * 0.5,
        )
        relative = (midpoint[0] - start[0], midpoint[1] - start[1])
        projection = relative[0] * route[0] + relative[1] * route[1]
        perpendicular = abs(
            relative[0] * -route[1] + relative[1] * route[0]
        )
        if 40.0 < projection < route_length - 80.0:
            candidates.append((perpendicular, projection, segment))
    if not candidates:
        raise WaveEpisodeError(
            "no exact openable segment lies between slot 0 and Solomon"
        )
    candidates.sort(key=lambda row: (row[0], row[1]))
    anchor_row = candidates[0][2]
    anchor = (
        (float(anchor_row["start_x"]) + float(anchor_row["end_x"]))
        * 0.5,
        (float(anchor_row["start_y"]) + float(anchor_row["end_y"]))
        * 0.5,
    )
    cluster = []
    for _, _, segment in candidates:
        midpoint = (
            (float(segment["start_x"]) + float(segment["end_x"])) * 0.5,
            (float(segment["start_y"]) + float(segment["end_y"])) * 0.5,
        )
        if math.dist(midpoint, anchor) <= 140.0:
            cluster.append(segment)
    endpoints = [
        point
        for segment in cluster
        for point in (
            (float(segment["start_x"]), float(segment["start_y"])),
            (float(segment["end_x"]), float(segment["end_y"])),
        )
    ]
    midpoint = (
        sum(point[0] for point in endpoints) / len(endpoints),
        sum(point[1] for point in endpoints) / len(endpoints),
    )
    longest = max(
        cluster,
        key=lambda row: math.hypot(
            float(row["end_x"]) - float(row["start_x"]),
            float(row["end_y"]) - float(row["start_y"]),
        ),
    )
    tangent = _normalize(
        float(longest["end_x"]) - float(longest["start_x"]),
        float(longest["end_y"]) - float(longest["start_y"]),
    )
    transit = (-tangent[1], tangent[0])
    if (
        (solomon[0] - midpoint[0]) * transit[0]
        + (solomon[1] - midpoint[1]) * transit[1]
        < 0.0
    ):
        transit = (-transit[0], -transit[1])
    return {
        "midpoint": midpoint,
        "route_unit": transit,
        "geometry_ids": [int(row["geometry_id"]) for row in cluster],
    }


def _command_destination(
    run: ValuesRunner,
    destination: tuple[float, float],
    *,
    deadline: float,
) -> None:
    observed = run(
        f"""
local controller = assert(
  rawget(_G, '{ROUTE_CONTROLLER_GLOBAL}'),
  'wave route controller unavailable')
controller.destination = {{
  x = {destination[0]:.9f},
  y = {destination[1]:.9f},
}}
controller.arrival = nil
print('accepted=true')
""",
        min(10.0, _remaining(deadline, "route command")),
    )
    if not _boolean(observed, "accepted"):
        raise WaveEpisodeError(f"route destination was rejected: {observed}")


def _wait_destination(
    run: ValuesRunner,
    destination: tuple[float, float],
    *,
    deadline: float,
    label: str,
    allow_solomon_acquisition: bool = False,
) -> dict[str, object]:
    final = _wait(
        lambda: run(
            ROUTE_STATE,
            min(10.0, _remaining(deadline, label)),
        ),
        lambda row: (
            (
                allow_solomon_acquisition
                and _boolean(row, "solomon_acquired")
                and _integer(row, "solomon_state", -1) >= 1
            )
            or (
                _boolean(row, "arrival_valid")
                and math.hypot(
                    _number(row, "arrival_x") - destination[0],
                    _number(row, "arrival_y") - destination[1],
                )
                <= ROUTE_ARRIVAL_RADIUS + 1.0
            )
        ),
        deadline=deadline,
        label=label,
    )
    return {
        "destination": [destination[0], destination[1]],
        "position": [
            _number(final, "player_x"),
            _number(final, "player_y"),
        ],
        "movement_frames": _integer(final, "movement_frames"),
        "solomon_acquired": _boolean(final, "solomon_acquired"),
    }


def _grid_route(
    run: ValuesRunner,
    current: tuple[float, float],
    solomon: tuple[float, float],
    *,
    deadline: float,
) -> list[tuple[float, float]]:
    source = f"""
local grid = sd.nav.get_grid(4) or {{}}
print('valid=' .. tostring(type(grid.cells) == 'table'))
print('refresh_pending=' .. tostring(grid.refresh_pending == true))
if type(grid.cells) ~= 'table' or grid.refresh_pending == true then
  print('path_found=false')
  print('count=0')
  return
end

local points = {{}}
local ordered = {{}}
local subdivisions = tonumber(grid.subdivisions) or 4
local function key(x, y)
  return tostring(x) .. ':' .. tostring(y)
end
for _, cell in ipairs(grid.cells) do
  for _, sample in ipairs(cell.samples or {{}}) do
    local cell_x, cell_y =
      tonumber(cell.grid_x), tonumber(cell.grid_y)
    local sample_x, sample_y =
      tonumber(sample.sample_x), tonumber(sample.sample_y)
    local x, y = tonumber(sample.world_x), tonumber(sample.world_y)
    if sample.traversable == true and cell_x ~= nil and cell_y ~= nil and
        sample_x ~= nil and sample_y ~= nil and x ~= nil and y ~= nil then
      local sx = cell_x * subdivisions + sample_x
      local sy = cell_y * subdivisions + sample_y
      local point = {{sx=sx, sy=sy, x=x, y=y}}
      points[key(sx, sy)] = point
      ordered[#ordered + 1] = point
    end
  end
end

local function nearest(x, y)
  local best, best_distance = nil, math.huge
  for _, point in ipairs(ordered) do
    local dx, dy = point.x - x, point.y - y
    local distance = dx * dx + dy * dy
    if distance < best_distance then
      best, best_distance = point, distance
    end
  end
  return best
end

local function nearest_reachable(x, y)
  local ranked = {{}}
  for _, point in ipairs(ordered) do
    local dx, dy = point.x - x, point.y - y
    ranked[#ranked + 1] = {{
      point=point,
      distance=dx * dx + dy * dy,
    }}
  end
  table.sort(ranked, function(left, right)
    return left.distance < right.distance
  end)
  for index = 1, math.min(#ranked, 128) do
    local point = ranked[index].point
    local ok, clear = pcall(
      sd.nav.test_segment, x, y, point.x, point.y)
    if ok and clear == true then return point end
  end
  return nil
end

local start = nearest_reachable(
  {current[0]:.9f}, {current[1]:.9f})
local goal = nearest({solomon[0]:.9f}, {solomon[1]:.9f})
if start == nil or goal == nil then
  print('path_found=false')
  print('count=0')
  return
end

local start_key, goal_key = key(start.sx, start.sy), key(goal.sx, goal.sy)
local queue, head = {{start_key}}, 1
local visited, parent = {{[start_key]=true}}, {{}}
local directions = {{{{1,0}},{{-1,0}},{{0,1}},{{0,-1}}}}
while head <= #queue and visited[goal_key] ~= true do
  local current_key = queue[head]
  head = head + 1
  local point = points[current_key]
  for _, direction in ipairs(directions) do
    local next_key = key(
      point.sx + direction[1],
      point.sy + direction[2])
    if points[next_key] ~= nil and visited[next_key] ~= true then
      visited[next_key] = true
      parent[next_key] = current_key
      queue[#queue + 1] = next_key
    end
  end
end
if visited[goal_key] ~= true then
  print('path_found=false')
  print('count=0')
  return
end

local reversed, cursor = {{}}, goal_key
while cursor ~= nil do
  reversed[#reversed + 1] = points[cursor]
  if cursor == start_key then break end
  cursor = parent[cursor]
end
local path = {{{{x={current[0]:.9f}, y={current[1]:.9f}}}}}
for index = #reversed, 1, -1 do
  path[#path + 1] = reversed[index]
end

local smooth, anchor = {{}}, 1
while anchor < #path do
  local selected = anchor + 1
  for candidate = #path, anchor + 1, -1 do
    local ok, clear = pcall(
      sd.nav.test_segment,
      path[anchor].x, path[anchor].y,
      path[candidate].x, path[candidate].y)
    if ok and clear == true then
      selected = candidate
      break
    end
  end
  smooth[#smooth + 1] = path[selected]
  anchor = selected
end
print('path_found=true')
print('count=' .. tostring(#smooth))
print('grid_point_count=' .. tostring(#ordered))
for index, point in ipairs(smooth) do
  print('waypoint.' .. tostring(index) .. '.x=' .. tostring(point.x))
  print('waypoint.' .. tostring(index) .. '.y=' .. tostring(point.y))
end
"""
    observed = _wait(
        lambda: run(
            source,
            min(30.0, _remaining(deadline, "hub grid route")),
        ),
        lambda row: (
            _boolean(row, "valid")
            and not _boolean(row, "refresh_pending")
            and _boolean(row, "path_found")
            and _integer(row, "count") > 0
        ),
        deadline=deadline,
        label="a traversable stock-grid route to Solomon",
        interval=0.25,
    )
    return [
        (
            _number(observed, f"waypoint.{index}.x"),
            _number(observed, f"waypoint.{index}.y"),
        )
        for index in range(1, _integer(observed, "count") + 1)
    ]


def start_stock_wave_episode(
    run: ValuesRunner,
    observer_participant_id: int,
    *,
    timeout: float = 180.0,
) -> dict[str, object]:
    """Physically trigger Solomon Dig and wait for a live retail wave."""

    if observer_participant_id <= 0:
        raise ValueError("observer_participant_id must be positive")
    if not math.isfinite(timeout) or timeout <= 0.0:
        raise ValueError("timeout must be finite and positive")
    deadline = time.monotonic() + timeout
    initial = _wait(
        lambda: run(
            ROUTE_STATE,
            min(10.0, _remaining(deadline, "Solomon materialization")),
        ),
        lambda row: (
            _boolean(row, "player_present")
            and _boolean(row, "solomon_present")
        ),
        deadline=deadline,
        label="the stock Solomon Dig setpiece",
    )
    armed = run(
        ROUTE_CONTROLLER_SOURCE,
        min(10.0, _remaining(deadline, "route controller")),
    )
    if not _boolean(armed, "armed"):
        raise WaveEpisodeError(
            f"could not arm the slot-0 wave route: {armed}"
        )

    start = (
        _number(initial, "player_x"),
        _number(initial, "player_y"),
    )
    solomon = (
        _number(initial, "solomon_x"),
        _number(initial, "solomon_y"),
    )
    gate = _select_gate(
        start,
        solomon,
        _openable_segments(
            run,
            observer_participant_id,
            deadline=deadline,
        ),
    )
    midpoint = gate["midpoint"]
    transit = gate["route_unit"]
    assert isinstance(midpoint, tuple)
    assert isinstance(transit, tuple)
    destinations = {
        "gate_approach": (
            midpoint[0] - transit[0] * 105.0,
            midpoint[1] - transit[1] * 105.0,
        ),
        "gate_exit": (
            midpoint[0] + transit[0] * 175.0,
            midpoint[1] + transit[1] * 175.0,
        ),
    }
    legs: dict[str, object] = {}
    for label, destination in destinations.items():
        _command_destination(run, destination, deadline=deadline)
        legs[label] = _wait_destination(
            run,
            destination,
            deadline=deadline,
            label=label.replace("_", " "),
        )

    current_state = run(
        ROUTE_STATE,
        min(10.0, _remaining(deadline, "post-gate state")),
    )
    current = (
        _number(current_state, "player_x"),
        _number(current_state, "player_y"),
    )
    hub_path = _grid_route(
        run,
        current,
        solomon,
        deadline=deadline,
    )
    hub_legs = []
    for index, waypoint in enumerate(hub_path, start=1):
        _command_destination(run, waypoint, deadline=deadline)
        leg = _wait_destination(
            run,
            waypoint,
            deadline=deadline,
            label=f"hub path waypoint {index}",
            allow_solomon_acquisition=True,
        )
        hub_legs.append(leg)
        if leg["solomon_acquired"] is True:
            break
    legs["hub_path"] = hub_legs

    trigger = _wait(
        lambda: run(
            """
local ok, state = sd.hub.trigger_solomon_dig()
print('triggered=' .. tostring(ok))
print('state=' .. tostring(
  state and state.interaction_state or -1))
print('acquired=' .. tostring(
  state and state.participant_acquired or false))
print('target_slot=' .. tostring(
  state and state.target_gameplay_slot or -1))
""",
            min(10.0, _remaining(deadline, "Solomon trigger")),
        ),
        lambda row: (
            _boolean(row, "triggered")
            and _boolean(row, "acquired")
            and _integer(row, "state", -1) >= 1
            and _integer(row, "target_slot", -1) >= 0
        ),
        deadline=deadline,
        label="the native Solomon conversation trigger",
    )
    released = run(
        f"""
local controller = rawget(_G, '{ROUTE_CONTROLLER_GLOBAL}') or {{}}
controller.armed = false
controller.destination = nil
pcall(sd.input.hold_movement_frames, 0.0, 0.0, 1)
print('released=' .. tostring(controller.armed == false))
""",
        min(10.0, _remaining(deadline, "route release")),
    )
    if not _boolean(released, "released"):
        raise WaveEpisodeError("could not release the slot-0 route controller")

    active = _wait(
        lambda: run(
            """
local wave = sd.waves.get_state() or {}
print('wave=' .. tostring(wave.wave or 0))
print('phase=' .. tostring(wave.phase or ''))
print('alive=' .. tostring(wave.alive or 0))
print('spawned=' .. tostring(wave.spawned or 0))
print('remaining=' .. tostring(wave.remaining_to_spawn or 0))
""",
            min(10.0, _remaining(deadline, "retail wave")),
        ),
        lambda row: _integer(row, "wave") > 0
        and _integer(row, "alive") > 0,
        deadline=deadline,
        label="a live enemy from the retail wave spawner",
    )
    return {
        "transition": "stock_solomon_dig",
        "start": [start[0], start[1]],
        "solomon": [solomon[0], solomon[1]],
        "gate_geometry_ids": gate["geometry_ids"],
        "legs": legs,
        "trigger_state": _integer(trigger, "state", -1),
        "trigger_slot": _integer(trigger, "target_slot", -1),
        "wave": _integer(active, "wave"),
        "wave_phase": active.get("phase", ""),
        "alive": _integer(active, "alive"),
        "spawned": _integer(active, "spawned"),
        "remaining_to_spawn": _integer(active, "remaining"),
    }
