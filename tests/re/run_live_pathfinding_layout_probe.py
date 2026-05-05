#!/usr/bin/env python3
"""Live RE probe for layout-backed pathfinding and movement metadata.

This probe launches the staged runtime, proves the launcher copied the current
binary-layout.ini into the stage, materializes a bot in a live testrun, and
queries the Lua debug movement surfaces that are backed by the recovered
native movement-controller and GameNpc fields.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import cast_state_probe as csp  # noqa: E402


OUTPUT_PATH = ROOT / "runtime" / "live_pathfinding_layout_probe.json"
RUNTIME_BINARY_LAYOUT_PATH = ROOT / "runtime/stage/.sdmod/config/binary-layout.ini"

REQUIRED_LAYOUT_KEYS = (
    "movement_controller_cells",
    "movement_controller_grid_height",
    "movement_controller_grid_width",
    "movement_controller_cell_width",
    "movement_controller_cell_height",
    "movement_controller_circle_count",
    "movement_controller_circle_list",
    "actor_current_target_actor",
    "actor_target_repath_cadence",
    "movement_circle_object_type",
    "movement_circle_mask",
    "movement_circle_x",
    "movement_circle_y",
    "movement_circle_radius",
    "gamenpc_move_flag",
    "gamenpc_goal_x",
    "gamenpc_goal_y",
    "gamenpc_tracked_slot",
    "gamenpc_tracked_slot_callback",
    "cell_placement_sample_resolution",
    "cell_line_sample_resolution",
    "static_circle_obstacle_mask",
    "pushable_circle_obstacle_mask",
    "push_through_gate_circle_object_type",
    "push_through_gate_circle_radius",
    "push_through_gate_radius_epsilon_milliunits",
    "max_static_circle_obstacles",
)

BAD_LOG_TOKENS = (
    "Binary layout is missing [gameplay.offsets].movement_controller",
    "Binary layout is missing [gameplay.offsets].gamenpc_",
    "Movement controller grid snapshot was incomplete",
    "Movement controller cell dimensions are invalid",
    "No traversable start cell",
    "No traversable goal cell",
    "Native placement query failed",
    "registered_gamenpc movement list anomaly",
)


class LivePathfindingLayoutProbeFailure(RuntimeError):
    pass


def read_runtime_layout() -> dict[str, int]:
    if not RUNTIME_BINARY_LAYOUT_PATH.exists():
        raise LivePathfindingLayoutProbeFailure(
            f"staged binary layout is missing: {RUNTIME_BINARY_LAYOUT_PATH}"
        )

    values: dict[str, int] = {}
    for raw_line in RUNTIME_BINARY_LAYOUT_PATH.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", ";")) or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key in REQUIRED_LAYOUT_KEYS:
            values[key] = int(value.strip(), 0)

    missing = [key for key in REQUIRED_LAYOUT_KEYS if key not in values]
    if missing:
        raise LivePathfindingLayoutProbeFailure(
            "staged binary layout is missing movement/GameNpc key(s): " + ", ".join(missing)
        )
    return values


def emit_table_lua(table_name: str, prefix: str) -> str:
    return f"""
local {table_name} = {table_name} or {{}}
for key, value in pairs({table_name}) do
  local value_type = type(value)
  if value_type == 'number' or value_type == 'boolean' or value_type == 'string' then
    print('{prefix}.' .. tostring(key) .. '=' .. tostring(value))
  end
end
""".strip()


def query_nav_grid(subdivisions: int = 2, timeout_s: float = 20.0) -> dict[str, str]:
    deadline = time.time() + timeout_s
    last: dict[str, str] = {}
    lua = f"""
local grid = sd.debug.get_nav_grid({max(1, int(subdivisions))})
local scene = sd.world.get_scene()
local function emit(key, value)
  if value == nil then
    print(key .. '=')
  else
    print(key .. '=' .. tostring(value))
  end
end
if type(grid) ~= 'table' then
  emit('available', false)
  emit('scene', scene and scene.name or nil)
  return
end
emit('available', true)
emit('scene', scene and scene.name or nil)
emit('scene_world_id', scene and scene.world_id or 0)
emit('width', grid.width)
emit('height', grid.height)
emit('cell_width', grid.cell_width)
emit('cell_height', grid.cell_height)
emit('world_address', grid.world_address)
emit('controller_address', grid.controller_address)
emit('cells_address', grid.cells_address)
emit('probe_actor_address', grid.probe_actor_address)
emit('subdivisions', grid.subdivisions)
local traversable = 0
local path_traversable = 0
local total = 0
for _, cell in ipairs(grid.cells or {{}}) do
  total = total + 1
  if cell.traversable then
    traversable = traversable + 1
  end
  if cell.path_traversable then
    path_traversable = path_traversable + 1
  end
end
emit('cell_count', total)
emit('traversable_count', traversable)
emit('path_traversable_count', path_traversable)
""".strip()

    while time.time() < deadline:
        last = csp.parse_key_values(csp.run_lua(lua))
        if last.get("available") == "true":
            if csp.int_value(last, "subdivisions") >= max(1, int(subdivisions)):
                return last
        time.sleep(0.35)
    raise LivePathfindingLayoutProbeFailure(f"Timed out waiting for nav-grid snapshot. Last={last}")


def query_world_movement_geometry(world_address: int) -> dict[str, str]:
    if world_address == 0:
        raise LivePathfindingLayoutProbeFailure("nav grid did not report a world address")

    return csp.parse_key_values(
        csp.run_lua(
            f"""
local geometry = sd.debug.get_world_movement_geometry({world_address}, 8, 8)
local function emit(key, value)
  if value == nil then
    print(key .. '=')
  else
    print(key .. '=' .. tostring(value))
  end
end
if type(geometry) ~= 'table' then
  emit('available', false)
  return
end
emit('available', true)
emit('world_address', geometry.world_address)
emit('controller_address', geometry.controller_address)
local function emit_list(name, value)
  if type(value) ~= 'table' then
    emit(name .. '.available', false)
    return
  end
  emit(name .. '.available', true)
  emit(name .. '.count', value.count)
  emit(name .. '.list_address', value.list_address)
  emit(name .. '.sample_count', #(value.entries or {{}}))
end
emit_list('primary', geometry.primary)
emit_list('secondary', geometry.secondary)
emit_list('shapes', geometry.shapes)
emit_list('circles', geometry.circles)
""".strip()
        )
    )


def query_movement_circle_policy_sample(
    layout: dict[str, int],
    geometry: dict[str, str],
) -> dict[str, str]:
    circle_count = csp.int_value(geometry, "circles.count")
    circle_list_address = csp.int_value(geometry, "circles.list_address")
    if circle_count <= 0 or circle_list_address == 0:
        raise LivePathfindingLayoutProbeFailure(f"circle geometry is incomplete: {geometry}")

    sample_limit = min(circle_count, max(1, layout["max_static_circle_obstacles"]))
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local circle_count = {circle_count}
local circle_list = {circle_list_address}
local sample_limit = {sample_limit}
local object_type_offset = {layout["movement_circle_object_type"]}
local mask_offset = {layout["movement_circle_mask"]}
local x_offset = {layout["movement_circle_x"]}
local y_offset = {layout["movement_circle_y"]}
local radius_offset = {layout["movement_circle_radius"]}
local static_mask = {layout["static_circle_obstacle_mask"]}
local pushable_mask = {layout["pushable_circle_obstacle_mask"]}
local gate_type = {layout["push_through_gate_circle_object_type"]}
local gate_radius = {layout["push_through_gate_circle_radius"]}
local gate_epsilon = {layout["push_through_gate_radius_epsilon_milliunits"]} / 1000.0
local function emit(key, value)
  if value == nil then
    print(key .. '=')
  else
    print(key .. '=' .. tostring(value))
  end
end
local function has_bit(value, bit)
  if bit == 0 then
    return false
  end
  return math.floor(value / bit) % 2 == 1
end
local scanned = 0
local readable = 0
local static_bit_count = 0
local static_exact_count = 0
local pushable_bit_count = 0
local pushable_static_exact_count = 0
local gate_type_count = 0
local gate_radius_match_count = 0
local first_static_mask = 0
local first_gate_radius = -1
for index = 0, sample_limit - 1 do
  scanned = scanned + 1
  local circle = sd.debug.read_ptr(circle_list + index * 4) or 0
  if circle ~= 0 then
    local object_type = sd.debug.read_u32(circle + object_type_offset) or 0
    local mask = sd.debug.read_u32(circle + mask_offset) or 0
    local x = sd.debug.read_float(circle + x_offset) or 0.0
    local y = sd.debug.read_float(circle + y_offset) or 0.0
    local radius = sd.debug.read_float(circle + radius_offset) or -1.0
    if radius >= 0 and x == x and y == y then
      readable = readable + 1
      if has_bit(mask, static_mask) then
        static_bit_count = static_bit_count + 1
        if first_static_mask == 0 then
          first_static_mask = mask
        end
      end
      if mask == static_mask then
        static_exact_count = static_exact_count + 1
      end
      if has_bit(mask, pushable_mask) then
        pushable_bit_count = pushable_bit_count + 1
      end
      if mask == (static_mask + pushable_mask) then
        pushable_static_exact_count = pushable_static_exact_count + 1
      end
      if object_type == gate_type then
        gate_type_count = gate_type_count + 1
        if first_gate_radius < 0 then
          first_gate_radius = radius
        end
        if math.abs(radius - gate_radius) <= gate_epsilon then
          gate_radius_match_count = gate_radius_match_count + 1
        end
      end
    end
  end
end
emit('circle_count', circle_count)
emit('sample_limit', sample_limit)
emit('scanned', scanned)
emit('readable', readable)
emit('static_bit_count', static_bit_count)
emit('static_exact_count', static_exact_count)
emit('pushable_bit_count', pushable_bit_count)
emit('pushable_static_exact_count', pushable_static_exact_count)
emit('gate_type_count', gate_type_count)
emit('gate_radius_match_count', gate_radius_match_count)
emit('first_static_mask', first_static_mask)
emit('first_gate_radius', first_gate_radius)
""".strip()
        )
    )


def query_gamenpc_motion(actor_address: int) -> dict[str, str]:
    if actor_address == 0:
        raise LivePathfindingLayoutProbeFailure("bot has no actor address")
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local motion = sd.debug.get_gamenpc_motion({actor_address})
local function emit(key, value)
  if value == nil then
    print(key .. '=')
  else
    print(key .. '=' .. tostring(value))
  end
end
if type(motion) ~= 'table' then
  emit('available', false)
  return
end
emit('available', true)
emit('actor_address', motion.actor_address)
emit('x', motion.x)
emit('y', motion.y)
emit('heading', motion.heading)
emit('desired_yaw', motion.desired_yaw)
emit('move_flag', motion.move_flag)
emit('goal_x', motion.goal_x)
emit('goal_y', motion.goal_y)
emit('goal_distance_sq', motion.goal_distance_sq)
emit('mode', motion.mode)
emit('repath_timer', motion.repath_timer)
emit('speed_scalar', motion.speed_scalar)
emit('startup_cadence', motion.startup_cadence)
emit('tracked_slot', motion.tracked_slot)
emit('callback', motion.callback)
emit('late_timer', motion.late_timer)
""".strip()
        )
    )


def set_lua_bot_tick_enabled(enabled: bool) -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
rawset(_G, 'lua_bots_disable_tick', {str(not enabled).lower()})
print('ok=true')
print('lua_bots_disable_tick=' .. tostring(rawget(_G, 'lua_bots_disable_tick') == true))
""".strip()
        )
    )


def query_bot_by_id(bot_id: int) -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local bot = sd.bots and sd.bots.get_state and sd.bots.get_state({bot_id}) or nil
if type(bot) ~= 'table' then
  local bots = sd.bots and sd.bots.get_state and sd.bots.get_state() or nil
  if type(bots) == 'table' then
    for _, candidate in ipairs(bots) do
      if type(candidate) == 'table' and tonumber(candidate.id) == {bot_id} then
        bot = candidate
        break
      end
    end
  end
end
local function emit(key, value)
  if value == nil then
    print(key .. '=')
  else
    print(key .. '=' .. tostring(value))
  end
end
if type(bot) ~= 'table' then
  emit('available', false)
  return
end
emit('available', true)
for _, key in ipairs({{
  'id','actor_address','progression_runtime_state_address','progression_handle_address',
  'equip_handle_address','equip_runtime_state_address','gameplay_slot','actor_slot',
  'hp','max_hp','mp','max_mp','x','y','state'
}}) do
  emit(key, bot[key])
end
""".strip()
        )
    )


def prepare_manual_movement_control(bot_id: int) -> dict[str, Any]:
    tick_control = set_lua_bot_tick_enabled(False)
    stop_result = csp.parse_key_values(
        csp.run_lua(f"print('ok=' .. tostring(sd.bots.stop({bot_id})))")
    )

    samples: list[dict[str, str]] = []
    deadline = time.time() + 8.0
    while time.time() < deadline:
        sample = query_bot_by_id(bot_id)
        samples.append(sample)
        if sample.get("available") == "true" and len(samples) >= 3:
            recent = samples[-3:]
            coords = [
                (csp.float_value(item, "x"), csp.float_value(item, "y"))
                for item in recent
            ]
            if all(not math.isnan(x) and not math.isnan(y) for x, y in coords):
                max_delta = 0.0
                origin_x, origin_y = coords[0]
                for x, y in coords[1:]:
                    max_delta = max(max_delta, math.hypot(x - origin_x, y - origin_y))
                if max_delta <= 2.0:
                    return {
                        "tick_control": tick_control,
                        "stop_result": stop_result,
                        "settled_bot": sample,
                        "settle_samples": samples,
                    }
        time.sleep(0.25)

    last = samples[-1] if samples else {}
    if last.get("available") != "true":
        raise LivePathfindingLayoutProbeFailure(
            f"manual movement setup lost bot {bot_id}: tick_control={tick_control} "
            f"stop_result={stop_result} last={last}"
        )
    return {
        "tick_control": tick_control,
        "stop_result": stop_result,
        "settled_bot": last,
        "settle_samples": samples,
    }


def distance_between(left: dict[str, str], right_x: float, right_y: float) -> float:
    x = csp.float_value(left, "x")
    y = csp.float_value(left, "y")
    if math.isnan(x) or math.isnan(y):
        return math.nan
    dx = x - right_x
    dy = y - right_y
    return math.sqrt(dx * dx + dy * dy)


def issue_move_and_observe(bot_id: int, bot: dict[str, str]) -> dict[str, Any]:
    control = prepare_manual_movement_control(bot_id)
    bot = dict(control["settled_bot"])
    bot_x = csp.float_value(bot, "x")
    bot_y = csp.float_value(bot, "y")
    if math.isnan(bot_x) or math.isnan(bot_y):
        raise LivePathfindingLayoutProbeFailure(f"bot has invalid position: {bot}")

    target_x = bot_x + 180.0
    target_y = bot_y
    initial_gap = math.sqrt((target_x - bot_x) * (target_x - bot_x) + (target_y - bot_y) * (target_y - bot_y))
    move_result = csp.parse_key_values(
        csp.run_lua(f"print('ok=' .. tostring(sd.bots.move_to({bot_id}, {target_x}, {target_y})))")
    )
    if move_result.get("ok") != "true":
        raise LivePathfindingLayoutProbeFailure(f"sd.bots.move_to failed: {move_result}")

    samples: list[dict[str, str]] = []
    improved = False
    for _ in range(24):
        time.sleep(0.25)
        sample = query_bot_by_id(bot_id)
        samples.append(sample)
        gap = distance_between(sample, target_x, target_y)
        if not math.isnan(gap) and gap < initial_gap - 8.0:
            improved = True
            break

    if not improved:
        final_gap = distance_between(samples[-1], target_x, target_y) if samples else math.nan
        raise LivePathfindingLayoutProbeFailure(
            f"bot did not advance toward layout-backed move target: initial_gap={initial_gap:.3f} "
            f"final_gap={final_gap:.3f} samples={samples[-3:]}"
        )

    csp.run_lua(f"print('ok=' .. tostring(sd.bots.stop({bot_id})))")
    return {
        "manual_control": control,
        "target": {"x": target_x, "y": target_y},
        "initial_gap": initial_gap,
        "samples": samples,
    }


def reject_bad_log_tokens(log_tail: list[str]) -> None:
    joined = "\n".join(log_tail)
    for token in BAD_LOG_TOKENS:
        if token in joined:
            raise LivePathfindingLayoutProbeFailure(f"loader log contains pathfinding failure token: {token}")


def drive_to_materialized_bot(element: str, discipline: str) -> dict[str, Any]:
    result: dict[str, Any] = {"navigation": []}
    result["launcher_freshness"] = csp.ensure_launcher_bundle_fresh()

    csp.stop_game()
    csp.clear_loader_log()
    csp.launch_game()
    process_id = csp.wait_for_game_process()
    result["process_id"] = process_id
    csp.wait_for_lua_pipe()
    result["navigation"].append({"step": "launch", "process_id": process_id})

    result["staged_layout"] = read_runtime_layout()

    hub_flow = csp.drive_hub_flow(process_id, element=element, discipline=discipline, prefer_resume=False)
    result["navigation"].append({"step": "hub_ready", "flow": hub_flow})
    csp.start_run_and_waves()
    csp.boost_player_survival()
    result["navigation"].append({"step": "testrun_started"})

    bot = csp.wait_for_materialized_bot()
    bot_id = csp.int_value(bot, "id")
    actor_address = csp.int_value(bot, "actor_address")
    if bot_id == 0 or actor_address == 0:
        raise LivePathfindingLayoutProbeFailure(f"materialized bot has invalid identity: {bot}")
    result["bot_initial"] = bot
    return result


def run_probe(element: str, discipline: str) -> dict[str, Any]:
    result = drive_to_materialized_bot(element, discipline)
    bot = dict(result["bot_initial"])
    bot_id = csp.int_value(bot, "id")
    actor_address = csp.int_value(bot, "actor_address")

    nav_grid = query_nav_grid(subdivisions=2)
    if csp.int_value(nav_grid, "width") <= 0 or csp.int_value(nav_grid, "height") <= 0:
        raise LivePathfindingLayoutProbeFailure(f"nav grid dimensions are invalid: {nav_grid}")
    if csp.int_value(nav_grid, "cells_address") == 0 or csp.int_value(nav_grid, "controller_address") == 0:
        raise LivePathfindingLayoutProbeFailure(f"nav grid missing controller/cells address: {nav_grid}")
    if csp.int_value(nav_grid, "path_traversable_count") <= 0:
        raise LivePathfindingLayoutProbeFailure(f"nav grid has no path-traversable cells: {nav_grid}")
    result["nav_grid"] = nav_grid

    geometry = query_world_movement_geometry(csp.int_value(nav_grid, "world_address"))
    if geometry.get("available") != "true":
        raise LivePathfindingLayoutProbeFailure(f"movement geometry unavailable: {geometry}")
    if csp.int_value(geometry, "controller_address") == 0:
        raise LivePathfindingLayoutProbeFailure(f"movement geometry missing controller address: {geometry}")
    if csp.int_value(geometry, "circles.count") <= 0:
        raise LivePathfindingLayoutProbeFailure(f"movement geometry has no circle entries: {geometry}")
    result["movement_geometry"] = geometry

    circle_policy = query_movement_circle_policy_sample(result["staged_layout"], geometry)
    if csp.int_value(circle_policy, "readable") <= 0:
        raise LivePathfindingLayoutProbeFailure(f"movement circle policy sample read no circles: {circle_policy}")
    if csp.int_value(circle_policy, "static_bit_count") <= 0:
        raise LivePathfindingLayoutProbeFailure(f"movement circle policy sample found no static mask: {circle_policy}")
    if csp.int_value(circle_policy, "gate_radius_match_count") <= 0:
        raise LivePathfindingLayoutProbeFailure(
            "movement circle policy sample found no push-through gate matching "
            f"configured type/radius: {circle_policy}"
        )
    result["movement_circle_policy"] = circle_policy

    initial_motion = query_gamenpc_motion(actor_address)
    if initial_motion.get("available") != "true":
        raise LivePathfindingLayoutProbeFailure(f"GameNpc motion snapshot unavailable: {initial_motion}")
    result["gamenpc_motion_initial"] = initial_motion

    result["movement_observation"] = issue_move_and_observe(bot_id, bot)
    result["bot_final"] = query_bot_by_id(bot_id)
    result["gamenpc_motion_final"] = query_gamenpc_motion(actor_address)

    log_tail = csp.tail_loader_log(260)
    reject_bad_log_tokens(log_tail)
    result["loader_log_tail"] = log_tail
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--element", default="fire", choices=sorted(csp.CREATE_ELEMENT_CENTERS))
    parser.add_argument("--discipline", default="mind", choices=sorted(csp.CREATE_DISCIPLINE_CENTERS))
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--json", action="store_true", help="Only print structured JSON.")
    parser.add_argument("--keep-running", action="store_true", help="Leave the game process running after the probe.")
    args = parser.parse_args()

    exit_code = 0
    try:
        result: dict[str, Any] = run_probe(args.element, args.discipline)
        result["passed"] = True
    except Exception as exc:  # noqa: BLE001 - probe preserves diagnostics in JSON.
        result = {
            "passed": False,
            "error": str(exc),
            "loader_log_tail": csp.tail_loader_log(260),
        }
        exit_code = 1
    finally:
        if not args.keep_running:
            csp.stop_game()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    elif result.get("passed"):
        print("PASS: live pathfinding layout probe validated staged movement/GameNpc seams")
        print(f"Wrote {args.output}")
    else:
        print(f"FAIL: live pathfinding layout probe: {result.get('error')}")
        print(f"Wrote {args.output}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
