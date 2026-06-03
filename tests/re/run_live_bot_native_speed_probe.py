#!/usr/bin/env python3
"""Live regression for bot movement speed against the native player envelope."""

from __future__ import annotations

import argparse
import json
import math
import struct
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import cast_state_probe as csp  # noqa: E402
import probe_bot_skill_choice_stress as stress  # noqa: E402
from run_live_native_spell_stats_probe import (  # noqa: E402
    find_bot_for_element,
    list_bot_states,
)


OUTPUT_PATH = ROOT / "runtime" / "live_bot_native_speed_probe.json"
FIRE_ELEMENT_ID = 0
RUSH_OPTION_ID = 67
DEFAULT_MAX_RUSH_STEPS = 16

ACTOR_POSITION_X_OFFSET = csp.read_runtime_layout_offset("actor_position_x")
ACTOR_POSITION_Y_OFFSET = csp.read_runtime_layout_offset("actor_position_y")
ACTOR_MOVEMENT_VECTOR_X_OFFSET = csp.read_runtime_layout_offset("actor_animation_config_block")
ACTOR_MOVEMENT_VECTOR_Y_OFFSET = csp.read_runtime_layout_offset("actor_animation_drive_parameter")
ACTOR_MOVE_SPEED_SCALE_OFFSET = csp.read_runtime_layout_offset("actor_move_speed_scale")
ACTOR_MOVEMENT_SPEED_MULTIPLIER_OFFSET = csp.read_runtime_layout_offset("actor_movement_speed_multiplier")
ACTOR_MOVE_STEP_SCALE_OFFSET = csp.read_runtime_layout_offset("actor_move_step_scale")
PROGRESSION_MOVE_SPEED_OFFSET = csp.read_runtime_layout_offset("progression_move_speed")
MOVEMENT_INPUT_ACCELERATION_DIVISOR_GLOBAL = csp.read_runtime_layout_offset(
    "movement_input_acceleration_divisor"
)
MOVEMENT_SPEED_SCALAR_GLOBAL = csp.read_runtime_layout_offset("movement_speed_scalar")
MOVEMENT_VELOCITY_DAMPING_GLOBAL = csp.read_runtime_layout_offset("movement_velocity_damping")


class LiveBotNativeSpeedProbeFailure(RuntimeError):
    pass


def parse_int(value: object, default: int = 0) -> int:
    try:
        return int(str(value), 0)
    except (TypeError, ValueError):
        try:
            return int(float(str(value)))
        except (TypeError, ValueError):
            return default


def parse_float(value: object, default: float = math.nan) -> float:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return default


def lua_values(code: str, *, timeout_s: float = 20.0) -> dict[str, str]:
    return csp.parse_key_values(csp.run_lua(code.strip(), timeout_s=timeout_s))


def lua_bool(value: object) -> bool:
    return str(value).strip().lower() in {"true", "1"}


def read_game_double(address: int) -> float:
    values = lua_values(
        f"""
local function emit(k, v) print(k .. '=' .. tostring(v)) end
local resolved = sd.debug.resolve_game_address({address}) or {address}
emit('requested', {address})
emit('resolved', resolved)
emit('lo', sd.debug.read_u32(resolved))
emit('hi', sd.debug.read_u32(resolved + 4))
""",
        timeout_s=10.0,
    )
    lo = parse_int(values.get("lo"))
    hi = parse_int(values.get("hi"))
    return struct.unpack("<d", struct.pack("<II", lo & 0xFFFFFFFF, hi & 0xFFFFFFFF))[0]


def native_globals() -> dict[str, float]:
    values = {
        "input_acceleration_divisor": read_game_double(MOVEMENT_INPUT_ACCELERATION_DIVISOR_GLOBAL),
        "speed_scalar": read_game_double(MOVEMENT_SPEED_SCALAR_GLOBAL),
        "velocity_damping": read_game_double(MOVEMENT_VELOCITY_DAMPING_GLOBAL),
    }
    for name, value in values.items():
        if not math.isfinite(value) or value <= 0.0:
            raise LiveBotNativeSpeedProbeFailure(f"invalid native movement global {name}={value}")
    return values


def query_bot_motion(bot_id: int) -> dict[str, Any]:
    values = lua_values(
        f"""
local function emit(k, v) print(k .. '=' .. tostring(v)) end
local bot = sd.bots.get_state({bot_id})
if type(bot) ~= 'table' then
  emit('available', false)
  return
end
local actor = tonumber(bot.actor_address) or 0
local progression = tonumber(bot.progression_runtime_state_address) or 0
emit('available', true)
emit('bot_id', bot.id)
emit('actor_address', actor)
emit('progression', progression)
emit('state', bot.state)
if actor ~= 0 then
  emit('x', sd.debug.read_float(actor + {ACTOR_POSITION_X_OFFSET}))
  emit('y', sd.debug.read_float(actor + {ACTOR_POSITION_Y_OFFSET}))
  emit('velocity_x', sd.debug.read_float(actor + {ACTOR_MOVEMENT_VECTOR_X_OFFSET}))
  emit('velocity_y', sd.debug.read_float(actor + {ACTOR_MOVEMENT_VECTOR_Y_OFFSET}))
  emit('actor_move_speed_scale', sd.debug.read_float(actor + {ACTOR_MOVE_SPEED_SCALE_OFFSET}))
  emit('actor_movement_speed_multiplier', sd.debug.read_float(actor + {ACTOR_MOVEMENT_SPEED_MULTIPLIER_OFFSET}))
  emit('actor_move_step_scale', sd.debug.read_float(actor + {ACTOR_MOVE_STEP_SCALE_OFFSET}))
end
if progression ~= 0 then
  emit('progression_move_speed', sd.debug.read_float(progression + {PROGRESSION_MOVE_SPEED_OFFSET}))
end
""",
        timeout_s=10.0,
    )
    motion: dict[str, Any] = dict(values)
    vx = parse_float(values.get("velocity_x"))
    vy = parse_float(values.get("velocity_y"))
    motion["velocity_magnitude"] = (
        math.sqrt(vx * vx + vy * vy)
        if math.isfinite(vx) and math.isfinite(vy)
        else math.nan
    )
    return motion


def compute_native_speed_cap(motion: dict[str, Any], globals_state: dict[str, float]) -> float:
    actor_multiplier = parse_float(motion.get("actor_movement_speed_multiplier"))
    actor_scale = parse_float(motion.get("actor_move_speed_scale"))
    progression_speed = parse_float(motion.get("progression_move_speed"))
    cap = actor_multiplier * actor_scale * progression_speed * globals_state["speed_scalar"]
    if not math.isfinite(cap) or cap < 0.0:
        raise LiveBotNativeSpeedProbeFailure(
            f"invalid native speed cap from live fields: motion={motion} globals={globals_state}"
        )
    return cap


def stop_bot(bot_id: int) -> dict[str, str]:
    return lua_values(f"print('ok=' .. tostring(sd.bots.stop({bot_id})))", timeout_s=10.0)


def issue_move(bot_id: int, target_x: float, target_y: float) -> dict[str, str]:
    result = lua_values(
        f"print('ok=' .. tostring(sd.bots.move_to({bot_id}, {target_x}, {target_y})))",
        timeout_s=10.0,
    )
    if result.get("ok") != "true":
        raise LiveBotNativeSpeedProbeFailure(f"sd.bots.move_to failed: {result}")
    return result


def observe_velocity_after_move(
    bot_id: int,
    *,
    label: str,
    native_cap: float,
    tolerance: float,
    duration_s: float = 2.5,
) -> dict[str, Any]:
    start = query_bot_motion(bot_id)
    start_x = parse_float(start.get("x"))
    start_y = parse_float(start.get("y"))
    if not math.isfinite(start_x) or not math.isfinite(start_y):
        raise LiveBotNativeSpeedProbeFailure(f"{label}: bot has invalid position: {start}")

    candidate_targets = (
        (start_x + 160.0, start_y),
        (start_x - 160.0, start_y),
        (start_x, start_y + 160.0),
        (start_x, start_y - 160.0),
        (start_x + 115.0, start_y + 115.0),
        (start_x - 115.0, start_y - 115.0),
    )
    attempts: list[dict[str, Any]] = []
    for target_x, target_y in candidate_targets:
        stop_bot(bot_id)
        time.sleep(0.15)
        move_result = issue_move(bot_id, target_x, target_y)
        samples: list[dict[str, Any]] = []
        deadline = time.time() + duration_s
        while time.time() < deadline:
            time.sleep(0.10)
            sample = query_bot_motion(bot_id)
            sample["native_cap"] = native_cap
            samples.append(sample)
            velocity = parse_float(sample.get("velocity_magnitude"))
            if math.isfinite(velocity) and velocity > native_cap + tolerance:
                raise LiveBotNativeSpeedProbeFailure(
                    f"{label}: velocity exceeded native cap. "
                    f"velocity={velocity:.6f} cap={native_cap:.6f} tolerance={tolerance:.6f} "
                    f"sample={sample}"
                )

        positive_samples = [
            sample for sample in samples
            if parse_float(sample.get("velocity_magnitude")) > 0.01
        ]
        final = samples[-1] if samples else start
        dx = parse_float(final.get("x")) - start_x
        dy = parse_float(final.get("y")) - start_y
        displacement = math.sqrt(dx * dx + dy * dy) if math.isfinite(dx) and math.isfinite(dy) else math.nan
        attempt = {
            "label": label,
            "target": {"x": target_x, "y": target_y},
            "move_result": move_result,
            "sample_count": len(samples),
            "positive_sample_count": len(positive_samples),
            "max_velocity": max(
                (parse_float(sample.get("velocity_magnitude")) for sample in samples),
                default=math.nan,
            ),
            "native_cap": native_cap,
            "tolerance": tolerance,
            "displacement": displacement,
            "first_positive_sample": positive_samples[0] if positive_samples else None,
            "last_sample": final,
        }
        attempts.append(attempt)
        if positive_samples and math.isfinite(displacement) and displacement > 1.0:
            stop_bot(bot_id)
            return attempt

    stop_bot(bot_id)
    raise LiveBotNativeSpeedProbeFailure(
        f"{label}: bot never produced a moving native velocity sample. attempts={attempts}"
    )


def write_progression_move_speed(bot_id: int, value: float) -> dict[str, str]:
    result = lua_values(
        f"""
local function emit(k, v) print(k .. '=' .. tostring(v)) end
local bot = sd.bots.get_state({bot_id})
local progression = type(bot) == 'table' and tonumber(bot.progression_runtime_state_address) or 0
emit('progression', progression)
if progression == 0 then
  emit('ok', false)
  emit('error', 'missing_progression')
  return
end
emit('before', sd.debug.read_float(progression + {PROGRESSION_MOVE_SPEED_OFFSET}))
emit('write_ok', sd.debug.write_float(progression + {PROGRESSION_MOVE_SPEED_OFFSET}, {value}))
emit('after', sd.debug.read_float(progression + {PROGRESSION_MOVE_SPEED_OFFSET}))
emit('ok', true)
""",
        timeout_s=10.0,
    )
    if result.get("ok") != "true" or result.get("write_ok") != "true":
        raise LiveBotNativeSpeedProbeFailure(f"failed to write progression move speed: {result}")
    return result


def option_is_rush(option: dict[str, Any]) -> bool:
    return (
        parse_int(option.get("id"), -1) == RUSH_OPTION_ID
        or str(option.get("skill_file") or "").lower() == "rush.cfg"
        or "walking speed" in str(option.get("quick_description") or "").lower()
        or "walking speed" in str(option.get("description") or "").lower()
    )


def choose_until_rush(
    *,
    bot_ids: list[int],
    fire_bot_id: int,
    source_progression: int,
    max_steps: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    steps: list[dict[str, Any]] = []
    for step_index in range(1, max_steps + 1):
        fire_stats = stress.query_progression_stats(fire_bot_id)
        target_level = int(fire_stats["level"]) + 1
        target_xp = int(float(fire_stats["next_xp_threshold"]) + 10.0)
        stress.debug_sync_level_up(target_level, target_xp, source_progression)

        step: dict[str, Any] = {
            "step": step_index,
            "target_level": target_level,
            "target_xp": target_xp,
            "applications": [],
        }
        for bot_id in bot_ids:
            choices = stress.query_choices(bot_id)
            if not choices["pending"] or int(choices["count"]) <= 0:
                raise LiveBotNativeSpeedProbeFailure(
                    f"bot {bot_id} did not receive skill choices at level {target_level}: {choices}"
                )
            enriched = stress.enrich_choice_options(bot_id, choices)
            option_index = 1
            matched_rush = False
            if bot_id == fire_bot_id:
                for index, option in enumerate(enriched, start=1):
                    if option_is_rush(option):
                        option_index = index
                        matched_rush = True
                        break

            selected = enriched[option_index - 1]
            option_id = parse_int(selected.get("id"), -1)
            entry_before = stress.query_entry_state(bot_id, option_id)
            stats_before = stress.query_progression_stats(bot_id)
            loadout_before = stress.query_bot_loadout(bot_id)
            apply_result = stress.choose_skill(bot_id, option_index, int(choices["generation"]))
            entry_after = stress.query_entry_state(bot_id, option_id)
            stats_after = stress.query_progression_stats(bot_id)
            stress.assert_bot_owned_progression_mode(bot_id, stats_after, f"after_rush_step_{step_index}")
            loadout_after = stress.query_bot_loadout(bot_id)
            application = {
                "bot_id": bot_id,
                "generation": choices["generation"],
                "selected_index": option_index,
                "selected_option": selected,
                "apply_result": apply_result,
                "matched_rush": matched_rush,
                "entry_before": entry_before,
                "entry_after": entry_after,
                "entry_byte_diff": stress.diff_hex_bytes(
                    str(entry_before.get("bytes", "")),
                    str(entry_after.get("bytes", "")),
                ),
                "stats_before": stats_before,
                "stats_after": stats_after,
                "stats_diff": stress.diff_dict(stats_before, stats_after),
                "loadout_before": loadout_before,
                "loadout_after": loadout_after,
                "loadout_diff": stress.diff_dict(loadout_before, loadout_after),
            }
            step["applications"].append(application)
            if matched_rush:
                steps.append(step)
                return application, steps
        steps.append(step)

    raise LiveBotNativeSpeedProbeFailure(
        f"Rush was not offered to Fire bot within {max_steps} native level-up rolls"
    )


def launch_all_bots_run() -> dict[str, Any]:
    result: dict[str, Any] = {"fresh_bundle": csp.ensure_launcher_bundle_fresh()}
    csp.stop_game()
    csp.clear_loader_log()
    with stress.temporary_active_bots_config("all"):
        csp.launch_game()
        pid = csp.wait_for_game_process()
        result["pid"] = pid
        csp.wait_for_lua_pipe(timeout_s=60.0)
        result["hub_flow"] = csp.drive_new_game_flow(pid, element="ether", discipline="mind")
        start_run = stress.lua_values("print('ok='..tostring(sd.hub.start_testrun()))")
        if not lua_bool(start_run.get("ok")):
            raise LiveBotNativeSpeedProbeFailure(f"sd.hub.start_testrun failed: {start_run}")
        csp.wait_for_scene("testrun", timeout_s=45.0)
        time.sleep(2.0)
        result["bot_summary"] = stress.wait_for_materialized_bots(timeout_s=90.0)
    return result


def run_probe(max_rush_steps: int) -> dict[str, Any]:
    result = launch_all_bots_run()
    result["tick_gate"] = stress.set_lua_bot_tick_enabled(False)

    bot_summary = result["bot_summary"]
    source_progression = stress.int_value(bot_summary, "player.progression")
    bot_count = stress.int_value(bot_summary, "bot.count")
    bot_ids = [
        stress.int_value(bot_summary, f"bot.{index}.id")
        for index in range(1, bot_count + 1)
    ]
    if not bot_ids:
        raise LiveBotNativeSpeedProbeFailure(f"no bot ids in summary: {bot_summary}")

    fire_bot = find_bot_for_element(list_bot_states(), FIRE_ELEMENT_ID)
    fire_bot_id = parse_int(fire_bot.get("id"))
    result["fire_bot"] = fire_bot
    result["native_globals"] = native_globals()

    baseline_motion = query_bot_motion(fire_bot_id)
    baseline_cap = compute_native_speed_cap(baseline_motion, result["native_globals"])
    result["baseline_motion"] = baseline_motion
    result["baseline_native_speed_cap"] = baseline_cap
    original_progression_speed = parse_float(baseline_motion.get("progression_move_speed"))
    if not math.isfinite(original_progression_speed) or original_progression_speed <= 0.0:
        raise LiveBotNativeSpeedProbeFailure(f"invalid baseline progression speed: {baseline_motion}")

    try:
        result["baseline_observation"] = observe_velocity_after_move(
            fire_bot_id,
            label="baseline",
            native_cap=baseline_cap,
            tolerance=0.06,
        )

        low_progression_speed = max(0.10, min(original_progression_speed * 0.30, 0.30))
        result["low_speed_write"] = write_progression_move_speed(fire_bot_id, low_progression_speed)
        low_motion = query_bot_motion(fire_bot_id)
        low_cap = compute_native_speed_cap(low_motion, result["native_globals"])
        result["low_speed_motion"] = low_motion
        result["low_speed_native_speed_cap"] = low_cap
        result["low_speed_observation"] = observe_velocity_after_move(
            fire_bot_id,
            label="low_progression_speed",
            native_cap=low_cap,
            tolerance=0.04,
        )
    finally:
        result["restore_progression_speed"] = write_progression_move_speed(
            fire_bot_id,
            original_progression_speed,
        )
        stop_bot(fire_bot_id)
        time.sleep(0.25)

    rush_application, rush_steps = choose_until_rush(
        bot_ids=bot_ids,
        fire_bot_id=fire_bot_id,
        source_progression=source_progression,
        max_steps=max_rush_steps,
    )
    result["rush_application"] = rush_application
    result["rush_steps"] = rush_steps
    post_rush_motion = query_bot_motion(fire_bot_id)
    post_rush_cap = compute_native_speed_cap(post_rush_motion, result["native_globals"])
    result["post_rush_motion"] = post_rush_motion
    result["post_rush_native_speed_cap"] = post_rush_cap
    result["post_rush_observation"] = observe_velocity_after_move(
        fire_bot_id,
        label="post_rush",
        native_cap=post_rush_cap,
        tolerance=0.06,
    )

    result["loader_log_tail"] = csp.tail_loader_log(220)
    result["passed"] = True
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-rush-steps", type=int, default=DEFAULT_MAX_RUSH_STEPS)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--keep-running", action="store_true")
    args = parser.parse_args()

    exit_code = 0
    try:
        result = run_probe(args.max_rush_steps)
    except Exception as exc:  # noqa: BLE001 - preserve structured failure output.
        result = {
            "passed": False,
            "error": str(exc),
            "loader_log_tail": csp.tail_loader_log(220),
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
        baseline = result["baseline_observation"]
        low = result["low_speed_observation"]
        rush = result["post_rush_observation"]
        print(
            "PASS: Fire bot movement stayed within the native live speed envelope "
            f"(baseline max={baseline['max_velocity']:.4f}/cap={baseline['native_cap']:.4f}, "
            f"low max={low['max_velocity']:.4f}/cap={low['native_cap']:.4f}, "
            f"post-rush max={rush['max_velocity']:.4f}/cap={rush['native_cap']:.4f})"
        )
        print(f"Wrote {args.output}")
    else:
        print(f"FAIL: live bot native speed probe: {result.get('error')}")
        print(f"Wrote {args.output}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
