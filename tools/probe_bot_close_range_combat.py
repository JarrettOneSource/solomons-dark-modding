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
DEFAULT_TARGET_HP = 100.0
SPAWN_OFFSET_X = 80.0
ACTOR_POSITION_X_OFFSET = 0x18
ACTOR_POSITION_Y_OFFSET = 0x1C
ACTOR_HEADING_OFFSET = 0x6C
OBJECT_TYPE_ID_OFFSET = 0x08
ARENA_ENEMY_OBJECT_TYPE_ID = 1001
ARENA_ENEMY_MAX_HP_OFFSET = 0x170
ARENA_ENEMY_CURRENT_HP_OFFSET = 0x174
PROGRESSION_POINTER_OFFSET = 0x200
PROGRESSION_HANDLE_OFFSET = 0x300


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
local bot_actor = tonumber(bot.actor_address) or 0
if bot_actor ~= 0 and sd.debug and sd.debug.read_float then
  bx = tonumber(sd.debug.read_float(bot_actor + 0x18)) or bx
  by = tonumber(sd.debug.read_float(bot_actor + 0x1C)) or by
end
emit('bot.live_x', bx)
emit('bot.live_y', by)
local best = nil
local best_gap = math.huge
if type(actors) == 'table' then
  for _, actor in ipairs(actors) do
    local obj = tonumber(actor.object_type_id) or 0
    local tracked = actor.tracked_enemy == true
    local dead = actor.dead == true
    local hp = tonumber(actor.hp) or 0.0
    local max_hp = tonumber(actor.max_hp) or 0.0
    if (tracked or obj == 1001) and not dead and (max_hp <= 0.0 or hp > 0.0) then
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
  emit('hostile.tracked_enemy', best.tracked_enemy)
  emit('hostile.enemy_type', best.enemy_type)
  emit('hostile.dead', best.dead)
  emit('hostile.hp', best.hp)
  emit('hostile.max_hp', best.max_hp)
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


def clear_bots() -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            """
if sd.bots and sd.bots.clear then
  sd.bots.clear()
end
local count = sd.bots and sd.bots.get_count and sd.bots.get_count() or 0
print('ok=true')
print('count=' .. tostring(count))
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


def force_actor_position(
    actor_address: str | int,
    x: float,
    y: float,
    *,
    heading: float | None = None,
) -> dict[str, str]:
    heading_line = ""
    if heading is not None:
        heading_line = (
            f"emit('heading_ok', sd.debug.write_float(actor + {ACTOR_HEADING_OFFSET}, {heading}))"
        )
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
local actor = {actor_address}
emit('actor_address', actor)
emit('x_ok', sd.debug.write_float(actor + {ACTOR_POSITION_X_OFFSET}, {x}))
emit('y_ok', sd.debug.write_float(actor + {ACTOR_POSITION_Y_OFFSET}, {y}))
{heading_line}
emit('x', sd.debug.read_float(actor + {ACTOR_POSITION_X_OFFSET}))
emit('y', sd.debug.read_float(actor + {ACTOR_POSITION_Y_OFFSET}))
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


def query_progression_for_actor(actor_address: str | int) -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
local actor = {actor_address}
local object_type_id = tonumber(sd.debug.read_u32(actor + {OBJECT_TYPE_ID_OFFSET})) or 0
emit("object_type_id", object_type_id)
if object_type_id == {ARENA_ENEMY_OBJECT_TYPE_ID} then
  emit("actor", actor)
  emit("progression", 0)
  emit("handle", 0)
  emit("health_kind", "arena_enemy")
  emit("hp", sd.debug.read_float(actor + {ARENA_ENEMY_CURRENT_HP_OFFSET}))
  emit("max_hp", sd.debug.read_float(actor + {ARENA_ENEMY_MAX_HP_OFFSET}))
  return
end
local progression = tonumber(sd.debug.read_ptr(actor + {PROGRESSION_POINTER_OFFSET})) or 0
local handle = tonumber(sd.debug.read_ptr(actor + {PROGRESSION_HANDLE_OFFSET})) or 0
if progression == 0 and handle ~= 0 then
  progression = tonumber(sd.debug.read_ptr(handle)) or 0
end
emit("actor", actor)
emit("progression", progression)
emit("handle", handle)
if progression ~= 0 then
  emit("hp", sd.debug.read_float(progression + {csp.PROGRESSION_HP_OFFSET}))
  emit("max_hp", sd.debug.read_float(progression + {csp.PROGRESSION_MAX_HP_OFFSET}))
end
""".strip()
        )
    )


def force_actor_vitals(actor_address: str | int, hp_value: float) -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
local actor = {actor_address}
local object_type_id = tonumber(sd.debug.read_u32(actor + {OBJECT_TYPE_ID_OFFSET})) or 0
emit("object_type_id", object_type_id)
if object_type_id == {ARENA_ENEMY_OBJECT_TYPE_ID} then
  emit("actor", actor)
  emit("progression", 0)
  emit("handle", 0)
  emit("health_kind", "arena_enemy")
  emit("max_hp_ok", sd.debug.write_float(actor + {ARENA_ENEMY_MAX_HP_OFFSET}, {hp_value}))
  emit("hp_ok", sd.debug.write_float(actor + {ARENA_ENEMY_CURRENT_HP_OFFSET}, {hp_value}))
  emit("hp", sd.debug.read_float(actor + {ARENA_ENEMY_CURRENT_HP_OFFSET}))
  emit("max_hp", sd.debug.read_float(actor + {ARENA_ENEMY_MAX_HP_OFFSET}))
  return
end
local progression = tonumber(sd.debug.read_ptr(actor + {PROGRESSION_POINTER_OFFSET})) or 0
local handle = tonumber(sd.debug.read_ptr(actor + {PROGRESSION_HANDLE_OFFSET})) or 0
if progression == 0 and handle ~= 0 then
  progression = tonumber(sd.debug.read_ptr(handle)) or 0
end
emit("actor", actor)
emit("progression", progression)
emit("handle", handle)
if progression ~= 0 then
  emit("max_hp_ok", sd.debug.write_float(progression + {csp.PROGRESSION_MAX_HP_OFFSET}, {hp_value}))
  emit("hp_ok", sd.debug.write_float(progression + {csp.PROGRESSION_HP_OFFSET}, {hp_value}))
  emit("hp", sd.debug.read_float(progression + {csp.PROGRESSION_HP_OFFSET}))
  emit("max_hp", sd.debug.read_float(progression + {csp.PROGRESSION_MAX_HP_OFFSET}))
end
""".strip()
        )
    )


def arm_hp_watch(name: str, actor_address: str | int) -> dict[str, str]:
    progression = query_progression_for_actor(actor_address)
    progression_address = csp.int_value(progression, "progression")
    if progression_address == 0:
        return {
            "actor": str(actor_address),
            "progression": "0",
            "watch_ok": "false",
            "watchable": "false",
            "reason": "no_progression",
        }
    hp_address = progression_address + csp.PROGRESSION_HP_OFFSET
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
sd.debug.unwatch({json.dumps(name)})
sd.debug.clear_write_hits({json.dumps(name)})
emit("actor", {actor_address})
emit("progression", {progression_address})
emit("hp_address", {hp_address})
emit("watch_ok", sd.debug.watch_write({json.dumps(name)}, {hp_address}, 4))
emit("watchable", true)
""".strip()
        )
    )


def query_write_hits(name: str) -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local hits = sd.debug.get_write_hits({json.dumps(name)}) or {{}}
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
emit("count", #hits)
for i = 1, math.min(#hits, 8) do
  local hit = hits[i]
  for _, key in ipairs({{
    "requested_address","resolved_address","access_address","thread_id",
    "eip","esp","ebp","eax","ecx","edx","ret","arg0","arg1","arg2"
  }}) do
    emit("hit." .. i .. "." .. key, hit[key])
  end
end
""".strip()
        )
    )


def clear_hp_watch(name: str) -> None:
    csp.run_lua(
        f"""
pcall(sd.debug.unwatch, {json.dumps(name)})
sd.debug.clear_write_hits({json.dumps(name)})
""".strip()
    )


def filter_loader_log(lines: list[str]) -> list[str]:
    needles = (
        "attack ",
        "attack_skip",
        "queued cast",
        "skills_wizard_loadout",
        "pure_primary_start enter",
        "pure_primary_start exit",
        "spell_dispatch enter",
        "spell_dispatch exit",
        "spell_3ef hook",
        "cast prepped",
        "cast prepare failed",
        "cast post-tick detail",
        "synthetic cast intent",
        "cast complete",
        "cast dispatch failed",
        "spell_obj diag",
        "pure_primary_damage",
        "No traversable start cell",
        "run.ended",
        "destroyed lua bot",
        "gameplay-slot stock tick rewrote actor position",
    )
    filtered = [line for line in lines if any(needle in line for needle in needles)]
    return filtered[-120:]


def start_testrun_without_waves() -> dict[str, str]:
    scene = csp.query_scene_state()
    if csp.is_settled_scene(scene, "testrun"):
        return {"ok": "true", "already_testrun": "true"}
    values = csp.parse_key_values(csp.run_lua("print('ok='..tostring(sd.hub.start_testrun()))"))
    if values.get("ok") != "true":
        raise CloseRangeProbeFailure(f"sd.hub.start_testrun failed: {values}")
    csp.wait_for_scene("testrun", timeout_s=45.0)
    return values


def enable_combat_prelude() -> dict[str, str]:
    values = csp.parse_key_values(csp.run_lua("print('ok='..tostring(sd.gameplay.enable_combat_prelude()))"))
    if values.get("ok") != "true":
        raise CloseRangeProbeFailure(f"sd.gameplay.enable_combat_prelude failed: {values}")
    return values


def query_combat_state() -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            """
local state = sd.gameplay and sd.gameplay.get_combat_state and sd.gameplay.get_combat_state()
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
if type(state) ~= 'table' then
  emit('available', false)
  return
end
emit('available', true)
for _, key in ipairs({
  'arena_id','section_index','wave_index','wait_ticks','advance_mode',
  'advance_threshold','wave_counter','started_music','transition_requested','active'
}) do
  emit(key, state[key])
end
""".strip()
        )
    )


def wait_for_combat_prelude_ready(timeout_s: float = 8.0) -> dict[str, str]:
    deadline = time.time() + timeout_s
    last: dict[str, str] = {}
    while time.time() < deadline:
        last = query_combat_state()
        if last.get("available") == "true":
            wave_index = int(last.get("wave_index") or "0", 10)
            if wave_index > 0:
                raise CloseRangeProbeFailure(f"Combat prelude advanced into waves: {last}")
            if last.get("active") == "true" and last.get("transition_requested") == "true":
                return last
        time.sleep(0.1)
    raise CloseRangeProbeFailure(f"Timed out waiting for combat prelude state. Last={last}")


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
local ok, err, request_id = sd.world.spawn_enemy({{
  type_id = 5010,
  x = {bot_x + standoff},
  y = {bot_y},
}})
print('ok=' .. tostring(ok))
print('err=' .. tostring(err))
print('request_id=' .. tostring(request_id))
""".strip()
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Spawn a hostile near a bot before waves and observe Lua-brain-driven combat."
    )
    parser.add_argument("--standoff", type=float, default=DEFAULT_STANDOFF)
    parser.add_argument("--observe-seconds", type=float, default=DEFAULT_OBSERVE_SECONDS)
    parser.add_argument("--hp", type=float, default=DEFAULT_TARGET_HP)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--keep-running", action="store_true")
    parser.add_argument("--skip-hp-watch", action="store_true")
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

        hub_flow = csp.drive_hub_flow(
            process_id,
            element=csp.DEFAULT_ELEMENT,
            discipline=csp.DEFAULT_DISCIPLINE,
            prefer_resume=False,
        )
        result["navigation"].append(
            {
                "step": "hub_ready",
                "flow": hub_flow,
                "element": csp.DEFAULT_ELEMENT,
                "discipline": csp.DEFAULT_DISCIPLINE,
                "hub_lua_tick_gate": set_lua_tick_enabled(False),
                "hub_bot_clear": clear_bots(),
            }
        )

        testrun = start_testrun_without_waves()
        result["navigation"].append({"step": "testrun_started", "result": testrun})
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
        # Enemy_Create's manual-spawn binding intentionally refuses to run once
        # arena combat is populated, so seed controlled hostiles first and only
        # then enable the no-wave combat prelude.
        spawn = spawn_hostile_near_bot(
            csp.float_value(bot, "x"),
            csp.float_value(bot, "y"),
            args.standoff,
        )
        if spawn.get("ok") != "true":
            raise CloseRangeProbeFailure(f"Spawn enemy failed: {spawn}")
        combat = enable_combat_prelude()
        combat_state = wait_for_combat_prelude_ready()
        result["navigation"].append({"step": "combat_prelude_enabled", "result": combat, "state": combat_state})
        time.sleep(1.0)
        hostile = csp.wait_for_nearest_enemy(max_gap=2000.0)
        hostile_address = hostile["actor_address"]
        forced_vitals = force_actor_vitals(hostile_address, args.hp)
        hp_watch = (
            {
                "actor": str(hostile_address),
                "progression": "0",
                "watch_ok": "false",
                "watchable": "false",
                "reason": "disabled_by_probe",
            }
            if args.skip_hp_watch
            else arm_hp_watch("close_range_hostile_hp", hostile_address)
        )
        hostile_before = query_progression_for_actor(hostile_address)
        direct_cast = queue_direct_primary_cast(
            bot["id"],
            hostile_address,
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
            "forced_vitals": forced_vitals,
            "hp_watch": hp_watch,
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
            "hostile_progression": query_progression_for_actor(hostile_address),
            "hostile_hp_write_hits": (
                {"count": "0", "watchable": "false", "reason": "disabled_by_probe"}
                if args.skip_hp_watch
                else query_write_hits("close_range_hostile_hp")
            ),
        }
        hostile_after = result["after"]["hostile_progression"]
        hp_before = csp.float_value(hostile_before, "hp")
        hp_after = csp.float_value(hostile_after, "hp")
        hp_write_hits = csp.int_value(result["after"]["hostile_hp_write_hits"], "count")
        result["validation"] = {
            "direct_cast_ok": direct_cast.get("ok") == "true",
            "hp_before": hp_before,
            "hp_after": hp_after,
            "hp_decreased": hp_after < hp_before,
            "hp_write_hits": hp_write_hits,
            "hp_write_seen": hp_write_hits > 0,
            "damage_proved": hp_after < hp_before or hp_write_hits > 0,
        }
        result["ok"] = bool(result["validation"]["direct_cast_ok"] and result["validation"]["damage_proved"])
        result["loader_log_tail"] = csp.tail_loader_log()
        result["loader_log_filtered"] = filter_loader_log(result["loader_log_tail"])

        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(result, indent=2, sort_keys=True))
        set_lua_tick_enabled(True)
        return 0 if result["ok"] else 1
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
        try:
            clear_hp_watch("close_range_hostile_hp")
        except csp.ProbeFailure:
            pass
        print(json.dumps(result, indent=2, sort_keys=True))
        return 1
    finally:
        try:
            clear_hp_watch("close_range_hostile_hp")
        except csp.ProbeFailure:
            pass
        if not args.keep_running:
            csp.stop_game()


if __name__ == "__main__":
    raise SystemExit(main())
