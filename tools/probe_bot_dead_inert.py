#!/usr/bin/env python3
"""Verify that a dead Lua bot remains a materialized inert corpse."""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import cast_state_probe as csp


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = ROOT / "runtime" / "probe_bot_dead_inert.json"
DEFAULT_ELEMENT = "ether"
DEFAULT_DISCIPLINE = "mind"
PROMOTE_OFFSET_X = 80.0
OBSERVE_SECONDS = 3.0
POST_TESTRUN_SETTLE_SECONDS = 4.0
POST_PROMOTION_SETTLE_SECONDS = 2.0
POSITION_EPSILON = 0.05


class DeadInertProbeFailure(RuntimeError):
    pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Launch a no-wave test run, kill the bot, and verify dead-inert behavior."
    )
    parser.add_argument("--element", choices=sorted(csp.CREATE_ELEMENT_CENTERS), default=DEFAULT_ELEMENT)
    parser.add_argument("--discipline", choices=sorted(csp.CREATE_DISCIPLINE_CENTERS), default=DEFAULT_DISCIPLINE)
    parser.add_argument("--observe-seconds", type=float, default=OBSERVE_SECONDS)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--keep-running", action="store_true")
    return parser


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


def enable_combat_prelude() -> dict[str, str]:
    values = csp.parse_key_values(
        csp.run_lua("print('ok='..tostring(sd.gameplay.enable_combat_prelude()))")
    )
    if values.get("ok") != "true":
        raise DeadInertProbeFailure(f"sd.gameplay.enable_combat_prelude failed: {values}")
    return values


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
    x = {player_x + PROMOTE_OFFSET_X},
    y = {player_y},
    heading = 25.0,
  }},
}})
print('ok=' .. tostring(ok))
print('id=' .. tostring(bot.id))
""".strip()
        )
    )


def set_lua_bot_tick_enabled(enabled: bool) -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
lua_bots_disable_tick = {"false" if enabled else "true"}
print('ok=true')
print('lua_bots_disable_tick=' .. tostring(lua_bots_disable_tick))
""".strip()
        )
    )


def query_bot_detail(bot_id: str | int | None = None) -> dict[str, str]:
    bot_selector = (
        "sd.bots.get_state()"
        if bot_id is None
        else f"{{ sd.bots.get_state({bot_id}) }}"
    )
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local bots = sd.bots and sd.bots.get_state and {bot_selector}
local bot = type(bots) == 'table' and bots[1] or nil
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
for _, key in ipairs({{
  'id','actor_address','progression_runtime_state_address','progression_handle_address',
  'gameplay_slot','actor_slot','hp','max_hp','mp','max_mp','x','y','heading',
  'state','moving','has_target','target_x','target_y','queued_cast_count','last_queued_cast_ms',
  'slot_anim_state_index','resolved_animation_state_id'
}}) do
  emit(key, bot[key])
end
local actor = tonumber(bot.actor_address) or 0
if actor ~= 0 and sd.debug then
  emit('raw_x', sd.debug.read_float(actor + 0x18))
  emit('raw_y', sd.debug.read_float(actor + 0x1C))
  emit('raw_walk_x', sd.debug.read_float(actor + 0x158))
  emit('raw_walk_y', sd.debug.read_float(actor + 0x15C))
  emit('raw_drive', sd.debug.read_u8(actor + 0x160))
  emit('raw_no_interrupt', sd.debug.read_u8(actor + 0x1EC))
  emit('raw_skill', sd.debug.read_u32(actor + 0x270))
  emit('raw_cast_group', sd.debug.read_u8(actor + 0x27C))
  emit('raw_cast_slot', sd.debug.read_u16(actor + 0x27E))
  emit('raw_e4', sd.debug.read_u32(actor + 0xE4))
  emit('raw_e8', sd.debug.read_u32(actor + 0xE8))
end
""".strip()
        )
    )


def queue_move(bot_id: str, x: float, y: float) -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
print('ok=' .. tostring(sd.bots.move_to({bot_id}, {x}, {y})))
print('bot_id=' .. tostring({bot_id}))
print('x=' .. tostring({x}))
print('y=' .. tostring({y}))
""".strip()
        )
    )


def queue_cast_at_player(bot_id: str) -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local player = sd.player.get_state()
local target_x = tonumber(player and player.x) or 0.0
local target_y = tonumber(player and player.y) or 0.0
local target_actor = tonumber(player and player.actor_address) or 0
local ok = sd.bots.cast({{
  id = {bot_id},
  kind = 'primary',
  target_actor_address = target_actor,
  target = {{ x = target_x, y = target_y }},
}})
print('ok=' .. tostring(ok))
print('bot_id=' .. tostring({bot_id}))
print('target_actor_address=' .. tostring(target_actor))
print('target_x=' .. tostring(target_x))
print('target_y=' .. tostring(target_y))
""".strip()
        )
    )


def force_bot_dead(bot_id: str) -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local bot = sd.bots.get_state({bot_id})
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
if type(bot) ~= 'table' then
  emit('ok', false)
  emit('error', 'no_bot')
  return
end
local progression = tonumber(bot.progression_runtime_state_address) or 0
if progression == 0 then
  emit('ok', false)
  emit('error', 'no_progression')
  return
end
emit('bot_id', bot.id)
emit('progression', progression)
emit('max_hp_before', sd.debug.read_float(progression + {csp.PROGRESSION_MAX_HP_OFFSET}))
emit('hp_before', sd.debug.read_float(progression + {csp.PROGRESSION_HP_OFFSET}))
emit('max_hp_ok', sd.debug.write_float(progression + {csp.PROGRESSION_MAX_HP_OFFSET}, 500.0))
emit('hp_ok', sd.debug.write_float(progression + {csp.PROGRESSION_HP_OFFSET}, 0.0))
emit('hp_after', sd.debug.read_float(progression + {csp.PROGRESSION_HP_OFFSET}))
emit('max_hp_after', sd.debug.read_float(progression + {csp.PROGRESSION_MAX_HP_OFFSET}))
emit('ok', true)
""".strip()
        )
    )


def queue_after_death_commands(bot_id: str, x: float, y: float) -> dict[str, dict[str, str]]:
    return {
        "move": queue_move(bot_id, x + 200.0, y),
        "face": csp.parse_key_values(
            csp.run_lua(f"print('ok=' .. tostring(sd.bots.face({bot_id}, 180.0)))")
        ),
        "cast": queue_cast_at_player(bot_id),
        "stop": csp.parse_key_values(
            csp.run_lua(f"print('ok=' .. tostring(sd.bots.stop({bot_id})))")
        ),
    }


def observe_bot(bot_id: str, seconds: float) -> list[dict[str, str]]:
    samples: list[dict[str, str]] = []
    deadline = time.time() + max(0.0, seconds)
    while time.time() < deadline:
        sample = query_bot_detail(bot_id)
        sample["sample_monotonic_ms"] = str(int(time.time() * 1000.0))
        samples.append(sample)
        time.sleep(0.25)
    sample = query_bot_detail(bot_id)
    sample["sample_monotonic_ms"] = str(int(time.time() * 1000.0))
    samples.append(sample)
    return samples


def float_value(values: dict[str, str], key: str) -> float:
    try:
        return float(values.get(key, ""))
    except (TypeError, ValueError):
        return math.nan


def is_dead_sample(sample: dict[str, str]) -> bool:
    hp = float_value(sample, "hp")
    max_hp = float_value(sample, "max_hp")
    return math.isfinite(hp) and math.isfinite(max_hp) and max_hp > 0.0 and hp <= 0.0


def max_position_drift(samples: list[dict[str, str]], baseline: dict[str, str]) -> float:
    base_x = float_value(baseline, "raw_x")
    base_y = float_value(baseline, "raw_y")
    if not math.isfinite(base_x) or not math.isfinite(base_y):
        base_x = float_value(baseline, "x")
        base_y = float_value(baseline, "y")
    drift = 0.0
    for sample in samples:
        x = float_value(sample, "raw_x")
        y = float_value(sample, "raw_y")
        if not math.isfinite(x) or not math.isfinite(y):
            x = float_value(sample, "x")
            y = float_value(sample, "y")
        if not math.isfinite(x) or not math.isfinite(y):
            continue
        drift = max(drift, math.hypot(x - base_x, y - base_y))
    return drift


def read_loader_log_text() -> str:
    if not csp.LOADER_LOG.exists():
        return ""
    return csp.LOADER_LOG.read_text(encoding="utf-8", errors="replace")


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

        hub_flow = csp.drive_hub_flow(process_id, element=args.element, discipline=args.discipline, prefer_resume=True)
        result["navigation"].append(
            {"step": "hub_ready", "flow": hub_flow, "element": args.element, "discipline": args.discipline}
        )

        scene_before_testrun = csp.query_scene_state()
        if csp.is_settled_scene(scene_before_testrun, "testrun"):
            values = {"ok": "true", "already_testrun": "true"}
        else:
            values = csp.parse_key_values(csp.run_lua("print('ok='..tostring(sd.hub.start_testrun()))"))
            if values.get("ok") != "true":
                raise DeadInertProbeFailure(f"sd.hub.start_testrun failed: {values}")
            csp.wait_for_scene("testrun", timeout_s=45.0)
        time.sleep(POST_TESTRUN_SETTLE_SECONDS)
        result["navigation"].append({"step": "testrun_started", "result": values})

        result["combat_enable"] = enable_combat_prelude()
        time.sleep(0.5)
        result["combat_state_after_enable"] = query_combat_state()

        player = csp.query_player_state()
        promotion = promote_bot_into_run_scene(csp.float_value(player, "x"), csp.float_value(player, "y"))
        if promotion.get("ok") != "true":
            raise DeadInertProbeFailure(f"Bot run-scene promotion failed: {promotion}")
        time.sleep(POST_PROMOTION_SETTLE_SECONDS)

        bot = query_bot_detail()
        bot_id = bot.get("id", "")
        if bot.get("available") != "true" or not bot_id:
            raise DeadInertProbeFailure(f"Bot unavailable after promotion: {bot}")
        if csp.int_value(bot, "actor_address") == 0:
            raise DeadInertProbeFailure(f"Bot actor not materialized: {bot}")
        result["before_death"] = bot
        result["disable_lua_bot_tick"] = set_lua_bot_tick_enabled(False)

        bot_x = float_value(bot, "raw_x")
        bot_y = float_value(bot, "raw_y")
        if not math.isfinite(bot_x) or not math.isfinite(bot_y):
            bot_x = float_value(bot, "x")
            bot_y = float_value(bot, "y")

        result["move_before_death"] = queue_move(bot_id, bot_x + 120.0, bot_y)
        time.sleep(0.75)
        result["moving_sample_before_death"] = query_bot_detail(bot_id)

        result["force_dead"] = force_bot_dead(bot_id)
        if result["force_dead"].get("ok") != "true":
            raise DeadInertProbeFailure(f"Force-dead write failed: {result['force_dead']}")
        time.sleep(0.75)
        result["dead_baseline"] = query_bot_detail(bot_id)

        result["commands_after_death"] = queue_after_death_commands(bot_id, bot_x, bot_y)
        samples = observe_bot(bot_id, args.observe_seconds)
        result["dead_observation_samples"] = samples
        result["after"] = {
            "bot": samples[-1] if samples else query_bot_detail(bot_id),
            "world": csp.query_world_state(),
            "combat_state": query_combat_state(),
            "loader_log_tail": csp.tail_loader_log(160),
        }

        baseline = result["dead_baseline"]
        final_bot = result["after"]["bot"]
        drift = max_position_drift(samples, baseline)
        commands_after_death = result["commands_after_death"]
        world = result["after"]["world"]
        combat_state = result["after"]["combat_state"]
        result["validation"] = {
            "bot_dead": is_dead_sample(final_bot),
            "bot_materialized": csp.int_value(final_bot, "actor_address") != 0,
            "state_idle": final_bot.get("state") in {"", "idle", "Idle"},
            "movement_rejected": commands_after_death["move"].get("ok") == "false",
            "face_rejected": commands_after_death["face"].get("ok") == "false",
            "cast_rejected": commands_after_death["cast"].get("ok") == "false",
            "stop_accepted": commands_after_death["stop"].get("ok") == "true",
            "death_animation_drive_state": final_bot.get("raw_drive") == "1",
            "position_drift": drift,
            "position_stable": drift <= POSITION_EPSILON,
            "wave_zero": world.get("wave") in {"0", "0.0"} and combat_state.get("wave_index") in {"0", "0.0"},
            "enemy_count_zero": world.get("enemy_count") in {"0", "0.0"},
        }
        result["ok"] = all(
            bool(result["validation"][key])
            for key in (
                "bot_dead",
                "bot_materialized",
                "state_idle",
                "movement_rejected",
                "face_rejected",
                "cast_rejected",
                "stop_accepted",
                "death_animation_drive_state",
                "position_stable",
                "wave_zero",
                "enemy_count_zero",
            )
        )

        if not result["ok"]:
            return 1
        return 0
    except Exception as exc:
        result["ok"] = False
        result["error"] = str(exc)
        return 1
    finally:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        if not args.keep_running:
            csp.stop_game()


if __name__ == "__main__":
    sys.exit(main())
