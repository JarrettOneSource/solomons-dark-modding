#!/usr/bin/env python3
"""Launch testrun, spawn a hostile near a bot before waves, and observe bot combat."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cast_state_probe as csp


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = ROOT / "runtime" / "probe_bot_close_range_combat.json"
DEFAULT_STANDOFF = 120.0
DEFAULT_OBSERVE_SECONDS = 8.0
SPAWN_OFFSET_X = 80.0


class CloseRangeProbeFailure(RuntimeError):
    pass
def query_combat_sample() -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            """
local bots = sd.bots and sd.bots.get_state and sd.bots.get_state()
local bot = type(bots) == 'table' and bots[1] or nil
local actors = sd.world and sd.world.list_actors and sd.world.list_actors()
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
if type(bot) ~= 'table' then
  emit('available', false)
  return
end
emit('available', true)
for _, key in ipairs({
  'id','actor_address','gameplay_slot','actor_slot','hp','max_hp',
  'mp','max_mp','x','y','state','queued_cast_count','last_queued_cast_ms'
}) do
  emit('bot.' .. key, bot[key])
end
local bx = tonumber(bot.x) or 0.0
local by = tonumber(bot.y) or 0.0
local best = nil
local best_gap = math.huge
if type(actors) == 'table' then
  for _, actor in ipairs(actors) do
    local obj = tonumber(actor.object_type_id) or 0
    if obj == 2012 or obj == 5009 or obj == 5010 then
      local ax = tonumber(actor.x) or 0.0
      local ay = tonumber(actor.y) or 0.0
      local dx = ax - bx
      local dy = ay - by
      local gap = math.sqrt(dx * dx + dy * dy)
      if gap < best_gap then
        best_gap = gap
        best = actor
      end
    end
  end
end
if type(best) == 'table' then
  emit('hostile.available', true)
  emit('hostile.object_type_id', best.object_type_id)
  emit('hostile.actor_address', best.actor_address)
  emit('hostile.x', best.x)
  emit('hostile.y', best.y)
  emit('hostile.gap', best_gap)
else
  emit('hostile.available', false)
end
""".strip()
        )
    )


def set_lua_tick_enabled(enabled: bool) -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
lua_bots_disable_tick = {"false" if enabled else "true"}
print('ok=true')
print('lua_bots_disable_tick=' .. tostring(lua_bots_disable_tick))
""".strip()
        )
    )


def stop_bot(bot_id: str) -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
print('ok=' .. tostring(sd.bots.stop({bot_id})))
""".strip()
        )
    )


def queue_direct_primary_cast(bot_id: str, hostile_actor_address: str, hostile_x: float, hostile_y: float) -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local ok = sd.bots.cast({{
  id = {bot_id},
  kind = 'primary',
  target_actor_address = {hostile_actor_address},
  target = {{ x = {hostile_x}, y = {hostile_y} }},
}})
print('ok=' .. tostring(ok))
print('bot_id=' .. tostring({bot_id}))
print('target_actor_address=' .. tostring({hostile_actor_address}))
""".strip()
        )
    )


def filter_loader_log(lines: list[str]) -> list[str]:
    needles = (
        "attack ",
        "attack_skip",
        "queued cast",
        "spell_3ef hook",
        "cast prepped",
        "synthetic cast intent",
        "cast complete",
        "cast dispatch failed",
        "spell_obj diag",
        "No traversable start cell",
        "gameplay-slot stock tick rewrote actor position",
    )
    filtered = [line for line in lines if any(needle in line for needle in needles)]
    return filtered[-120:]


def start_testrun_without_waves() -> None:
    values = csp.parse_key_values(csp.run_lua("print('ok='..tostring(sd.hub.start_testrun()))"))
    if values.get("ok") != "true":
        raise CloseRangeProbeFailure(f"sd.hub.start_testrun failed: {values}")
    csp.wait_for_scene("testrun", timeout_s=45.0)


def promote_bot_into_run_scene(player_x: float, player_y: float) -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local bots = sd.bots.get_state()
local bot = type(bots) == 'table' and bots[1] or nil
if type(bot) ~= 'table' then
  print('ok=false')
  print('error=no_bot')
  return
end
local ok = sd.bots.update({{
  id = bot.id,
  scene = {{ kind = 'run' }},
  position = {{
    x = {player_x + SPAWN_OFFSET_X},
    y = {player_y},
    heading = 25.0,
  }},
}})
print('ok=' .. tostring(ok))
""".strip()
        )
    )


def spawn_hostile_near_bot(bot_x: float, bot_y: float, standoff: float) -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local ok, err = sd.world.spawn_enemy({{
  type_id = 5010,
  x = {bot_x + standoff},
  y = {bot_y},
}})
print('ok=' .. tostring(ok))
print('err=' .. tostring(err))
""".strip()
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Spawn a hostile near a bot before waves and observe Lua-brain-driven combat."
    )
    parser.add_argument("--standoff", type=float, default=DEFAULT_STANDOFF)
    parser.add_argument("--observe-seconds", type=float, default=DEFAULT_OBSERVE_SECONDS)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--keep-running", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result: dict[str, object] = {
        "launcher_freshness": csp.ensure_launcher_bundle_fresh(),
        "navigation": [],
    }

    try:
        csp.stop_game()
        csp.clear_loader_log()

        csp.launch_game()
        process_id = csp.wait_for_game_process()
        csp.wait_for_lua_pipe()
        result["process_id"] = process_id
        result["navigation"].append({"step": "launch", "process_id": process_id})

        csp.drive_new_game_flow(
            process_id,
            element=csp.DEFAULT_ELEMENT,
            discipline=csp.DEFAULT_DISCIPLINE,
        )
        result["navigation"].append(
            {
                "step": "new_game",
                "element": csp.DEFAULT_ELEMENT,
                "discipline": csp.DEFAULT_DISCIPLINE,
            }
        )

        start_testrun_without_waves()
        result["navigation"].append({"step": "testrun_started"})
        set_lua_tick_enabled(True)

        bot = csp.wait_for_materialized_bot()
        tick_gate = set_lua_tick_enabled(False)
        player = csp.query_player_state()
        scene = csp.query_scene_state()
        world = csp.query_world_state()
        selection = csp.query_selection_debug_state()
        promotion = promote_bot_into_run_scene(
            csp.float_value(player, "x"),
            csp.float_value(player, "y"),
        )
        if promotion.get("ok") != "true":
            raise CloseRangeProbeFailure(f"Bot run-scene promotion failed: {promotion}")
        time.sleep(1.0)
        bot = csp.wait_for_materialized_bot()
        stop_after_promotion = stop_bot(bot["id"])
        spawn = spawn_hostile_near_bot(
            csp.float_value(bot, "x"),
            csp.float_value(bot, "y"),
            args.standoff,
        )
        if spawn.get("ok") != "true":
            raise CloseRangeProbeFailure(f"Spawn enemy failed: {spawn}")
        time.sleep(1.0)
        hostile = csp.wait_for_nearest_enemy(max_gap=2000.0)
        direct_cast = queue_direct_primary_cast(
            bot["id"],
            hostile["actor_address"],
            csp.float_value(hostile, "x"),
            csp.float_value(hostile, "y"),
        )
        result["before"] = {
            "bot": bot,
            "player": player,
            "hostile": hostile,
            "scene": scene,
            "world": world,
            "selection": selection,
        }
        result["spawn_setup"] = {
            "lua_tick_gate": tick_gate,
            "promotion": promotion,
            "stop_after_promotion": stop_after_promotion,
            "standoff": args.standoff,
            "spawn": spawn,
            "direct_cast": direct_cast,
        }

        samples: list[dict[str, str]] = []
        deadline = time.time() + args.observe_seconds
        while time.time() < deadline:
            sample = query_combat_sample()
            sample["sample_monotonic_ms"] = str(int(time.time() * 1000.0))
            samples.append(sample)
            time.sleep(1.0)

        result["samples"] = samples
        result["after"] = {
            "bot": csp.query_bot_state(),
            "scene": csp.query_scene_state(),
            "world": csp.query_world_state(),
            "selection": csp.query_selection_debug_state(),
            "bot_actor_raw": csp.query_actor_raw_fields(
                "bot", csp.int_value(csp.query_bot_state(), "actor_address")
            ),
        }
        result["loader_log_tail"] = csp.tail_loader_log()
        result["loader_log_filtered"] = filter_loader_log(result["loader_log_tail"])

        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(result, indent=2, sort_keys=True))
        set_lua_tick_enabled(True)
        return 0
    except (csp.ProbeFailure, CloseRangeProbeFailure) as exc:
        result["error"] = str(exc)
        result["loader_log_tail"] = csp.tail_loader_log()
        result["loader_log_filtered"] = filter_loader_log(result["loader_log_tail"])
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        try:
            set_lua_tick_enabled(True)
        except csp.ProbeFailure:
            pass
        print(json.dumps(result, indent=2, sort_keys=True))
        return 1
    finally:
        if not args.keep_running:
            csp.stop_game()


if __name__ == "__main__":
    raise SystemExit(main())
