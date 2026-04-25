#!/usr/bin/env python3
"""Validate bot projectile damage while normal follow movement is active."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import cast_state_probe as csp
import probe_bot_autonomous_combat_validation as auto
import probe_bot_close_range_combat as crc


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = ROOT / "runtime" / "probe_bot_moving_attack_damage.json"

DEFAULT_OBSERVE_SECONDS = 10.0
DEFAULT_FOLLOW_OFFSET = 240.0
DEFAULT_NEAR_STANDOFF = 150.0
DEFAULT_FAR_STANDOFF = 260.0
DEFAULT_HP_VALUE = 100.0
DEFAULT_ELEMENT = "ether"
DEFAULT_DISCIPLINE = "mind"


class MovingAttackDamageProbeFailure(RuntimeError):
    pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prove bot attacks can damage enemies while the bot is moving/following."
    )
    parser.add_argument("--element", choices=sorted(csp.CREATE_ELEMENT_CENTERS), default=DEFAULT_ELEMENT)
    parser.add_argument("--discipline", choices=sorted(csp.CREATE_DISCIPLINE_CENTERS), default=DEFAULT_DISCIPLINE)
    parser.add_argument("--observe-seconds", type=float, default=DEFAULT_OBSERVE_SECONDS)
    parser.add_argument("--follow-offset", type=float, default=DEFAULT_FOLLOW_OFFSET)
    parser.add_argument("--near-standoff", type=float, default=DEFAULT_NEAR_STANDOFF)
    parser.add_argument("--far-standoff", type=float, default=DEFAULT_FAR_STANDOFF)
    parser.add_argument("--hp", type=float, default=DEFAULT_HP_VALUE)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--keep-running", action="store_true")
    return parser


def update_bot_position(bot_id: str, x: float, y: float, heading: float = 90.0) -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local ok = sd.bots.update({{
  id = {bot_id},
  scene = {{ kind = 'run' }},
  position = {{ x = {x}, y = {y}, heading = {heading} }},
}})
print('ok=' .. tostring(ok))
print('bot_id=' .. tostring({bot_id}))
print('x=' .. tostring({x}))
print('y=' .. tostring({y}))
print('heading=' .. tostring({heading}))
""".strip()
        )
    )


def query_motion_sample() -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            """
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end

local bots = sd.bots and sd.bots.get_state and sd.bots.get_state()
local bot = type(bots) == 'table' and bots[1] or nil
if type(bot) ~= 'table' then
  emit('bot.available', false)
  return
end

emit('bot.available', true)
for _, key in ipairs({
  'id','actor_address','x','y','state','moving','has_target',
  'target_x','target_y','queued_cast_count','last_queued_cast_ms'
}) do
  emit('bot.' .. key, bot[key])
end

local actor = tonumber(bot.actor_address) or 0
if actor ~= 0 and sd.debug then
  emit('bot.raw_x', sd.debug.read_float(actor + 0x18))
  emit('bot.raw_y', sd.debug.read_float(actor + 0x1C))
  emit('bot.heading', sd.debug.read_float(actor + 0x6C))
end

local player = sd.player and sd.player.get_state and sd.player.get_state()
if type(player) == 'table' then
  emit('player.available', true)
  emit('player.x', player.x)
  emit('player.y', player.y)
else
  emit('player.available', false)
end
""".strip()
        )
    )


def observe_moving_attack_window(seconds: float) -> dict[str, object]:
    baseline_attack_count = len(auto.read_attack_lines())
    baseline_death_count = len(auto.read_enemy_death_lines())
    closest_samples: list[dict[str, object]] = []
    motion_samples: list[dict[str, str]] = []

    crc.set_lua_tick_enabled(True)
    try:
        deadline = time.time() + seconds
        sampled_attack_count = 0
        sustain_deadline = 0.0
        while time.time() < deadline:
            now = time.time()
            if now >= sustain_deadline:
                auto.sustain_probe_health()
                sustain_deadline = now + 1.0

            motion = query_motion_sample()
            motion["sample_monotonic_ms"] = str(int(now * 1000.0))
            motion_samples.append(motion)

            current_attack_lines = auto.read_attack_lines()[baseline_attack_count:]
            if len(current_attack_lines) > sampled_attack_count:
                new_attacks = auto.parse_attacks(current_attack_lines[sampled_attack_count:])
                for attack in new_attacks:
                    closest_samples.append(auto.classify_attack_against_live_enemies(attack))
                sampled_attack_count = len(current_attack_lines)
            time.sleep(0.25)
    finally:
        crc.set_lua_tick_enabled(False)

    attack_lines = auto.read_attack_lines()[baseline_attack_count:]
    death_lines = auto.read_enemy_death_lines()[baseline_death_count:]
    attacks = auto.parse_attacks(attack_lines)
    deaths = auto.parse_enemy_deaths(death_lines)
    window = {
        "lines": attack_lines[-30:],
        "attacks": attacks,
        "closest_samples": closest_samples,
        "enemy_deaths": deaths,
        "enemy_death_lines": death_lines[-30:],
        "motion_samples": motion_samples,
    }
    window["targeted_death_matches"] = auto.match_targeted_deaths(window)
    return window


def motion_distance(samples: list[dict[str, str]]) -> float:
    positions: list[tuple[float, float]] = []
    for sample in samples:
        x_text = sample.get("bot.raw_x") or sample.get("bot.x")
        y_text = sample.get("bot.raw_y") or sample.get("bot.y")
        if x_text is None or y_text is None:
            continue
        try:
            positions.append((float(x_text), float(y_text)))
        except ValueError:
            continue
    if len(positions) < 2:
        return 0.0
    start = positions[0]
    return max(((x - start[0]) ** 2 + (y - start[1]) ** 2) ** 0.5 for x, y in positions)


def run_probe(args: argparse.Namespace) -> dict[str, object]:
    result: dict[str, object] = {
        "launcher_freshness": csp.ensure_launcher_bundle_fresh(),
        "steps": [],
    }

    process_id = auto.launch_and_wait_for_lua()
    result["process_id"] = process_id
    result["steps"].append({"step": "launch", "process_id": process_id})

    result["navigation"] = auto.start_clean_testrun(process_id, args.element, args.discipline)
    result["steps"].append({"step": "testrun_ready"})

    crc.set_lua_tick_enabled(True)
    spawned_bot = csp.wait_for_materialized_bot()
    crc.set_lua_tick_enabled(False)

    player = csp.query_player_state()
    player_x = csp.float_value(player, "x")
    player_y = csp.float_value(player, "y")
    promotion = crc.promote_bot_into_run_scene(player_x, player_y)
    if promotion.get("ok") != "true":
        raise MovingAttackDamageProbeFailure(f"Bot run-scene promotion failed: {promotion}")
    time.sleep(1.0)

    bot = csp.query_bot_state()
    bot_id = bot.get("id", "")
    if csp.int_value(bot, "actor_address") == 0 or not bot_id:
        raise MovingAttackDamageProbeFailure(f"Bot did not materialize after promotion: {bot}")

    start_x = player_x - args.follow_offset
    if start_x < 80.0:
        start_x = player_x + args.follow_offset
    start_y = player_y
    result["bot_setup"] = {
        "spawned": spawned_bot,
        "promoted": bot,
        "promotion": promotion,
        "reposition": update_bot_position(bot_id, start_x, start_y, 90.0),
        "start": {"x": start_x, "y": start_y},
        "player": player,
    }
    time.sleep(0.5)

    result["probe_health_before_waves"] = auto.sustain_probe_health()
    result["start_waves"] = auto.start_waves()
    result["wave_combat_state"] = auto.wait_for_wave_combat_active()
    enemies = auto.wait_for_live_enemies(2)
    result["live_enemies_after_wave_start"] = enemies

    first_enemy_address = csp.int_value(enemies[0], "actor_address")
    second_enemy_address = csp.int_value(enemies[1], "actor_address")
    current_bot = query_motion_sample()
    bot_x = float(current_bot.get("bot.raw_x") or current_bot.get("bot.x") or start_x)
    bot_y = float(current_bot.get("bot.raw_y") or current_bot.get("bot.y") or start_y)
    result["enemy_placements"] = auto.place_combat_enemies(
        auto.live_enemy_actors(),
        first_enemy_address,
        second_enemy_address,
        bot_x,
        bot_y,
        args.near_standoff,
        args.far_standoff,
        args.hp,
    )
    result["probe_health_after_placement"] = auto.sustain_probe_health()

    window = observe_moving_attack_window(args.observe_seconds)
    movement = motion_distance(window.get("motion_samples") or [])
    targeted_death_matches = window.get("targeted_death_matches") or []

    result["observation"] = window
    result["validation"] = {
        "attack_seen": bool(window.get("attacks")),
        "targeted_death_seen": bool(targeted_death_matches),
        "targeted_death_count": len(targeted_death_matches),
        "targeted_closest_seen": auto.any_attack_targeted_closest(window),
        "movement_distance": movement,
        "movement_seen": movement >= 25.0,
    }
    result["ok"] = bool(
        result["validation"]["attack_seen"]
        and result["validation"]["targeted_death_seen"]
        and result["validation"]["targeted_closest_seen"]
        and result["validation"]["movement_seen"]
    )
    result["loader_log_filtered"] = crc.filter_loader_log(csp.tail_loader_log(240))
    return result


def main() -> int:
    args = build_parser().parse_args()
    result: dict[str, object] = {}
    try:
        csp.stop_game()
        csp.clear_loader_log()
        result = run_probe(args)
    except Exception as exc:
        result.setdefault("ok", False)
        result["error"] = str(exc)
        result["loader_log_tail"] = csp.tail_loader_log(160)
    finally:
        try:
            crc.set_lua_tick_enabled(False)
        except Exception:
            pass
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        if not args.keep_running:
            csp.stop_game()

    summary = {
        "ok": result.get("ok"),
        "validation": result.get("validation"),
        "error": result.get("error"),
        "output": str(args.output),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
