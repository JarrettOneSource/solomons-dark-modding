#!/usr/bin/env python3
"""Live RE probe for standalone clone collision/materialization behavior.

This launches the staged game, materializes standalone clone-rail bots, records
the native registration/grid fields recovered from Ghidra, then forces a
standalone/standalone overlap and verifies the loader's explicit standalone push
keeps the actors separated.
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


OUTPUT_PATH = ROOT / "runtime" / "live_standalone_collision_probe.json"

ACTOR_OFFSET_POSITION_X = csp.read_runtime_layout_offset("actor_position_x")
ACTOR_OFFSET_POSITION_Y = csp.read_runtime_layout_offset("actor_position_y")
ACTOR_OFFSET_MOVE_BLOCKED_FLAG = csp.read_runtime_layout_offset("actor_move_blocked_flag")
ACTOR_OFFSET_GRID_MEMBER_FLAG = csp.read_runtime_layout_offset("actor_grid_member_flag")
ACTOR_OFFSET_COLLISION_RESPONSE_FLAG = csp.read_runtime_layout_offset("actor_collision_response_flag")
ACTOR_OFFSET_PRIMARY_FLAG_MASK = csp.read_runtime_layout_offset("actor_primary_flag_mask")
ACTOR_OFFSET_SECONDARY_FLAG_MASK = csp.read_runtime_layout_offset("actor_secondary_flag_mask")
ACTOR_OFFSET_GRID_CELL = csp.read_runtime_layout_offset("actor_grid_cell_ptr")
ACTOR_OFFSET_OWNER_WORLD = csp.read_runtime_layout_offset("actor_owner")
ACTOR_OFFSET_SLOT_GROUP = csp.read_runtime_layout_offset("actor_slot")
ACTOR_OFFSET_SLOT_INDEX = csp.read_runtime_layout_offset("actor_world_slot")
ACTOR_OFFSET_REGISTER_TRANSIENT = csp.read_runtime_layout_offset("actor_register_transient")
ACTOR_OFFSET_COLLISION_RADIUS = csp.read_runtime_layout_offset("actor_collision_radius")

BAD_LOG_TOKENS = (
    "Unhandled exception",
    "0xC0000005",
    "standalone stock tick rewrote actor position",
    "tracked actor invalidated out-of-band",
    "WorldCellGrid_RebindActor failed",
)


class LiveStandaloneCollisionProbeFailure(RuntimeError):
    pass


def emit_actor_materialization_lua(actor_address: int) -> str:
    return f"""
local actor = {actor_address}
local function emit(key, value)
  if value == nil then
    print(key .. '=')
  else
    print(key .. '=' .. tostring(value))
  end
end
if actor == 0 then
  emit('available', false)
  return
end
emit('available', true)
emit('actor', actor)
emit('x', sd.debug.read_float(actor + {ACTOR_OFFSET_POSITION_X}))
emit('y', sd.debug.read_float(actor + {ACTOR_OFFSET_POSITION_Y}))
emit('radius', sd.debug.read_float(actor + {ACTOR_OFFSET_COLLISION_RADIUS}))
emit('move_blocked_flag_34', sd.debug.read_u8(actor + {ACTOR_OFFSET_MOVE_BLOCKED_FLAG}))
emit('grid_member_flag_36', sd.debug.read_u8(actor + {ACTOR_OFFSET_GRID_MEMBER_FLAG}))
emit('collision_response_flag_37', sd.debug.read_u8(actor + {ACTOR_OFFSET_COLLISION_RESPONSE_FLAG}))
emit('primary_flag_mask_38', sd.debug.read_u32(actor + {ACTOR_OFFSET_PRIMARY_FLAG_MASK}))
emit('secondary_flag_mask_3c', sd.debug.read_u32(actor + {ACTOR_OFFSET_SECONDARY_FLAG_MASK}))
emit('grid_cell_ptr_54', sd.debug.read_ptr(actor + {ACTOR_OFFSET_GRID_CELL}))
emit('owner_world_ptr_58', sd.debug.read_ptr(actor + {ACTOR_OFFSET_OWNER_WORLD}))
emit('slot_group_5c', sd.debug.read_u8(actor + {ACTOR_OFFSET_SLOT_GROUP}))
emit('slot_index_5e', sd.debug.read_u16(actor + {ACTOR_OFFSET_SLOT_INDEX}))
emit('register_transient_68', sd.debug.read_u8(actor + {ACTOR_OFFSET_REGISTER_TRANSIENT}))
""".strip()


def query_actor_materialization(actor_address: int) -> dict[str, str]:
    if actor_address == 0:
        return {"available": "false"}
    return csp.parse_key_values(csp.run_lua(emit_actor_materialization_lua(actor_address)))


def force_bot_overlap(bot_id: int, bot_actor: int, x: float, y: float) -> dict[str, str]:
    if bot_actor == 0:
        raise LiveStandaloneCollisionProbeFailure("bot actor is not materialized")
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local ok_stop = true
if sd.bots and sd.bots.stop then
  ok_stop = sd.bots.stop({bot_id})
end
local actor = {bot_actor}
local ok_x = sd.debug.write_float(actor + {ACTOR_OFFSET_POSITION_X}, {x})
local ok_y = sd.debug.write_float(actor + {ACTOR_OFFSET_POSITION_Y}, {y})
print('ok_stop=' .. tostring(ok_stop))
print('ok_x=' .. tostring(ok_x))
print('ok_y=' .. tostring(ok_y))
""".strip()
        )
    )


def actor_distance(left: dict[str, str], right: dict[str, str]) -> float:
    lx = csp.float_value(left, "x")
    ly = csp.float_value(left, "y")
    rx = csp.float_value(right, "x")
    ry = csp.float_value(right, "y")
    return math.sqrt(((lx - rx) * (lx - rx)) + ((ly - ry) * (ly - ry)))


def query_bot_by_id(bot_id: int) -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local bot = sd.bots and sd.bots.get_state and sd.bots.get_state({bot_id})
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
  'id','actor_address','gameplay_slot','actor_slot','x','y','state','entity_materialized'
}}) do
  emit(key, bot[key])
end
""".strip()
        )
    )


def query_all_bots() -> list[dict[str, str]]:
    values = csp.parse_key_values(
        csp.run_lua(
            """
local bots = sd.bots and sd.bots.get_state and sd.bots.get_state() or {}
local function emit(key, value)
  if value == nil then
    print(key .. '=')
  else
    print(key .. '=' .. tostring(value))
  end
end
emit('count', #bots)
for index, bot in ipairs(bots) do
  emit('bot.' .. index .. '.id', bot.id)
  emit('bot.' .. index .. '.actor_address', bot.actor_address)
  emit('bot.' .. index .. '.gameplay_slot', bot.gameplay_slot)
  emit('bot.' .. index .. '.actor_slot', bot.actor_slot)
  emit('bot.' .. index .. '.x', bot.x)
  emit('bot.' .. index .. '.y', bot.y)
  emit('bot.' .. index .. '.state', bot.state)
  emit('bot.' .. index .. '.entity_materialized', bot.entity_materialized)
end
""".strip()
        )
    )
    rows: list[dict[str, str]] = []
    count = int(values.get("count") or "0")
    for index in range(1, count + 1):
        row = {"available": "true"}
        for key in (
            "id",
            "actor_address",
            "gameplay_slot",
            "actor_slot",
            "x",
            "y",
            "state",
            "entity_materialized",
        ):
            row[key] = values.get(f"bot.{index}.{key}", "")
        rows.append(row)
    return rows


def create_probe_bot(name: str, element_id: int, scene_kind: str, x: float, y: float) -> int:
    values = csp.parse_key_values(
        csp.run_lua(
            f"""
local function emit(key, value)
  if value == nil then
    print(key .. '=')
  else
    print(key .. '=' .. tostring(value))
  end
end
local id = sd.bots.create({{
  name = {json.dumps(name)},
  profile = {{
    element_id = {element_id},
    discipline_id = 1,
    level = 1,
    experience = 0,
  }},
  scene = {{ kind = {json.dumps(scene_kind)} }},
  ready = true,
  position = {{ x = {x}, y = {y}, heading = 90.0 }},
}})
emit('ok', id ~= nil)
emit('bot_id', id)
""".strip()
        )
    )
    if values.get("ok") != "true":
        raise LiveStandaloneCollisionProbeFailure(f"shared hub bot create failed: {values}")
    bot_id = csp.int_value(values, "bot_id")
    if bot_id == 0:
        raise LiveStandaloneCollisionProbeFailure(f"second bot create returned invalid id: {values}")
    return bot_id


def wait_for_bot_by_id(bot_id: int, timeout_s: float = 30.0) -> dict[str, str]:
    deadline = time.time() + timeout_s
    last: dict[str, str] = {}
    while time.time() < deadline:
        last = query_bot_by_id(bot_id)
        if last.get("available") == "true" and csp.int_value(last, "actor_address") != 0:
            return last
        time.sleep(0.25)
    raise LiveStandaloneCollisionProbeFailure(f"timed out waiting for bot {bot_id}: {last}")


def wait_for_collision_push(
    pusher_actor: int,
    pushed_actor: int,
    min_sep: float,
    *,
    timeout_s: float = 4.0,
) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    samples: list[dict[str, Any]] = []
    last_player: dict[str, str] = {}
    last_bot: dict[str, str] = {}

    while time.time() < deadline:
        time.sleep(0.20)
        last_player = query_actor_materialization(pusher_actor)
        last_bot = query_actor_materialization(pushed_actor)
        distance = actor_distance(last_player, last_bot)
        sample = {
            "distance": distance,
            "player": last_player,
            "bot": last_bot,
        }
        samples.append(sample)
        if distance >= min_sep - 0.25:
            return {
                "pushed": True,
                "distance": distance,
                "min_sep": min_sep,
                "samples": samples,
            }

    return {
        "pushed": False,
        "distance": actor_distance(last_player, last_bot),
        "min_sep": min_sep,
        "samples": samples,
    }


def wait_for_standalone_bots(min_count: int = 2, timeout_s: float = 45.0) -> list[dict[str, str]]:
    deadline = time.time() + timeout_s
    last: list[dict[str, str]] = []
    while time.time() < deadline:
        bots = query_all_bots()
        standalone = [
            bot for bot in bots
            if csp.int_value(bot, "actor_address") != 0 and csp.int_value(bot, "gameplay_slot") == -1
        ]
        if len(standalone) >= min_count:
            return standalone
        last = bots
        time.sleep(0.25)
    raise LiveStandaloneCollisionProbeFailure(
        f"timed out waiting for {min_count} standalone clone bots: {last}"
    )


def drive_to_gameplay_scene(element: str, discipline: str) -> dict[str, Any]:
    result: dict[str, Any] = {"navigation": []}
    result["launcher_freshness"] = csp.ensure_launcher_bundle_fresh()

    csp.stop_game()
    csp.clear_loader_log()
    csp.launch_game()
    process_id = csp.wait_for_game_process()
    result["process_id"] = process_id
    csp.wait_for_lua_pipe()
    result["navigation"].append({"step": "launch", "process_id": process_id})

    hub_flow = csp.drive_hub_flow(process_id, element=element, discipline=discipline, prefer_resume=False)
    scene = hub_flow.get("scene", {})
    if not isinstance(scene, dict) or scene.get("name") not in {"hub", "testrun"}:
        raise LiveStandaloneCollisionProbeFailure(f"expected hub or testrun scene, got: {hub_flow}")
    result["scene_name"] = scene.get("name")
    result["navigation"].append({"step": "scene_ready", "flow": hub_flow})
    return result


def reject_bad_log_tokens(log_tail: str) -> None:
    present = [token for token in BAD_LOG_TOKENS if token in log_tail]
    if present:
        raise LiveStandaloneCollisionProbeFailure(
            "loader log contains bad standalone collision token(s): " + ", ".join(present)
        )


def run_probe(element: str, discipline: str) -> dict[str, Any]:
    result = drive_to_gameplay_scene(element, discipline)
    player = csp.query_player_state()
    player_x = csp.float_value(player, "x")
    player_y = csp.float_value(player, "y")
    if not math.isfinite(player_x) or not math.isfinite(player_y):
        raise LiveStandaloneCollisionProbeFailure(f"hub player position is invalid: {player}")

    csp.run_lua("if sd.bots and sd.bots.clear then sd.bots.clear() end\nprint('ok=true')")
    scene_kind = "shared_hub" if result.get("scene_name") == "hub" else "run"
    created_bot_ids: list[int] = []
    for index, element_id in enumerate((0, 1, 2, 3, 4, 1), start=1):
        created_bot_ids.append(
            create_probe_bot(
                f"collision_probe_{index}",
                element_id,
                scene_kind,
                player_x + 80.0 + (index * 48.0),
                player_y,
            )
        )
    result["created_bot_ids"] = created_bot_ids
    standalone_bots = wait_for_standalone_bots(2)
    bot = standalone_bots[0]
    second_bot = standalone_bots[1]
    first_bot_id = csp.int_value(bot, "id")
    second_bot_id = csp.int_value(second_bot, "id")
    first_actor = csp.int_value(bot, "actor_address")
    if first_bot_id == 0 or first_actor == 0:
        raise LiveStandaloneCollisionProbeFailure(f"missing first bot actor: {bot}")

    first_native = query_actor_materialization(first_actor)
    first_radius = csp.float_value(first_native, "radius")
    first_x = csp.float_value(first_native, "x")
    first_y = csp.float_value(first_native, "y")
    second_actor = csp.int_value(second_bot, "actor_address")
    second_native = query_actor_materialization(second_actor)

    result["first_bot_initial"] = bot
    result["second_bot_initial"] = second_bot
    result["first_native_initial"] = first_native
    result["second_native_initial"] = second_native

    first_world = csp.int_value(first_native, "owner_world_ptr_58")
    second_world = csp.int_value(second_native, "owner_world_ptr_58")
    first_cell = csp.int_value(first_native, "grid_cell_ptr_54")
    second_cell = csp.int_value(second_native, "grid_cell_ptr_54")
    second_radius = csp.float_value(second_native, "radius")
    if first_world == 0 or second_world == 0 or first_world != second_world:
        raise LiveStandaloneCollisionProbeFailure(
            f"standalone bots are not in the same native world: first={first_native} second={second_native}"
        )
    if first_cell == 0 or second_cell == 0:
        raise LiveStandaloneCollisionProbeFailure(
            f"standalone bot is not bound to a native grid cell: first={first_native} second={second_native}"
        )
    if not math.isfinite(first_radius) or not math.isfinite(second_radius) or first_radius <= 0.0 or second_radius <= 0.0:
        raise LiveStandaloneCollisionProbeFailure(
            f"invalid collision radii: first={first_radius} second={second_radius}"
        )

    csp.run_lua(f"print('ok1=' .. tostring(sd.bots.stop({first_bot_id})))\nprint('ok2=' .. tostring(sd.bots.stop({second_bot_id})))")
    result["overlap_write"] = force_bot_overlap(second_bot_id, second_actor, first_x, first_y)
    if result["overlap_write"].get("ok_x") != "true" or result["overlap_write"].get("ok_y") != "true":
        raise LiveStandaloneCollisionProbeFailure(f"failed to force bot overlap: {result['overlap_write']}")

    overlapped_player = query_actor_materialization(first_actor)
    overlapped_bot = query_actor_materialization(second_actor)
    result["forced_overlap"] = {
        "distance": actor_distance(overlapped_player, overlapped_bot),
        "first": overlapped_player,
        "second": overlapped_bot,
    }

    push_result = wait_for_collision_push(first_actor, second_actor, first_radius + second_radius)
    result["collision_push"] = push_result
    if not push_result["pushed"]:
        raise LiveStandaloneCollisionProbeFailure(f"standalone collision push did not separate actors: {push_result}")

    result["first_native_final"] = query_actor_materialization(first_actor)
    result["second_native_final"] = query_actor_materialization(second_actor)
    result["loader_log_tail"] = csp.tail_loader_log(260)
    reject_bad_log_tokens(result["loader_log_tail"])
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
        result = {"passed": False, "error": str(exc)}
        exit_code = 1
    finally:
        if not args.keep_running:
            csp.stop_game()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"wrote {args.output}")
        print("PASS" if result.get("passed") else "FAIL")
        if not result.get("passed"):
            print(result.get("error", "unknown error"))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
