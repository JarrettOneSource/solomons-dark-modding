#!/usr/bin/env python3
"""Prove that the learned bot moves, attacks, and damages live enemies."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys
import time

from ml_bot.bridge import (
    DEFAULT_GAME_DIRECTORY,
    DEFAULT_LAUNCHER,
    BridgeError,
    SoloSession,
)
from ml_bot.model import load_model
import verify_local_multiplayer_sync as local_sync


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = ROOT / "models" / "bot-brain" / "policy-v1.json"
MINIMUM_LIVE_DISPLACEMENT = 1.0
MINIMUM_ACCEPTANCE_TICKS = 25

GAMEPLAY_STATUS = r"""
local debug = rawget(_G, 'bot_brain_debug') or {}
local handles = sd.bots.list()
local bot = handles[1]
local bot_x, bot_y = 0, 0
if bot ~= nil then
  local ok, x, y = pcall(function()
    return bot:position()
  end)
  if ok then
    bot_x = tonumber(x) or 0
    bot_y = tonumber(y) or 0
  end
end
local minimum_enemy_hp_ratio = 1.0
local damaged_enemy_count = 0
for _, actor in ipairs(sd.world.list_actors() or {}) do
  local hp = tonumber(actor.hp) or 0
  local max_hp = tonumber(actor.max_hp) or 0
  if actor.tracked_enemy == true and max_hp > 0 and hp > 0 then
    local ratio = math.max(0, math.min(1, hp / max_hp))
    minimum_enemy_hp_ratio =
      math.min(minimum_enemy_hp_ratio, ratio)
    if ratio < 0.999 then
      damaged_enemy_count = damaged_enemy_count + 1
    end
  end
end
local wave = sd.waves.get_state() or {}
print('bot_x=' .. string.format('%.17g', bot_x))
print('bot_y=' .. string.format('%.17g', bot_y))
print('wave=' .. tostring(wave.wave or 0))
print('wave_alive=' .. tostring(wave.alive or 0))
print('wave_killed=' .. tostring(wave.killed or 0))
print('damaged_enemy_count=' .. tostring(damaged_enemy_count))
print('minimum_enemy_hp_ratio=' ..
  string.format('%.17g', minimum_enemy_hp_ratio))
print('policy_movement_name=' ..
  tostring(debug.policy_movement_name or ''))
print('policy_cast_name=' ..
  tostring(debug.policy_cast_name or ''))
"""


def _integer(values: dict[str, str], key: str) -> int:
    try:
        return int(values.get(key, "0"))
    except ValueError as error:
        raise BridgeError(f"invalid integer {key}: {values.get(key)!r}") from error


def _finite(values: dict[str, str], key: str) -> float:
    try:
        value = float(values.get(key, "nan"))
    except ValueError as error:
        raise BridgeError(f"invalid number {key}: {values.get(key)!r}") from error
    if not math.isfinite(value):
        raise BridgeError(f"non-finite number {key}: {value}")
    return value


def verify(args: argparse.Namespace) -> dict[str, object]:
    policy = load_model(Path(args.model))
    instance = args.instance or f"ml-live-{os.getpid()}"
    session = SoloSession(
        instance=instance,
        game_directory=Path(args.game_directory),
        launcher_path=Path(args.launcher_path),
        runtime_root=Path(args.runtime_root),
        local_port=args.local_port,
        unused_remote_port=args.unused_remote_port,
        headless=not args.visible,
        element=args.element,
        discipline=args.discipline,
    )
    launch: dict[str, object] | None = None
    started_at = time.monotonic()
    first_tick = 0
    first_tick_wall = 0.0
    first_position: tuple[float, float] | None = None
    maximum_distance = 0.0
    maximum_killed = 0
    minimum_enemy_hp_ratio = 1.0
    last_status: dict[str, str] = {}
    last_gameplay: dict[str, str] = {}
    try:
        launch = session.launch()
        session.wait_for_pipe(timeout=args.startup_timeout)
        session.drive_new_game_to_hub(timeout=args.startup_timeout)
        session.write_empty_roster()
        session.wait_for_empty_roster(timeout=args.startup_timeout)
        generation = session.load_policy(policy)
        session.enable_god_mode()
        session.start_test_run(timeout=args.startup_timeout)
        session.prepare_training_combat(
            timeout=args.startup_timeout
        )
        session.write_learned_roster()
        session.wait_for_learned_bot(timeout=args.startup_timeout)
        session.wait_for_run_ready(timeout=args.startup_timeout)
        session.wait_for_bot_materialized(
            timeout=args.startup_timeout
        )
        session.prime_training_progression(
            timeout=args.startup_timeout
        )
        session.start_training_arena(
            timeout=args.startup_timeout
        )
        session.wait_for_training_enemy(
            timeout=args.startup_timeout
        )

        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            last_status = session.status()
            last_gameplay = local_sync.parse_key_values(
                session.lua(GAMEPLAY_STATUS, timeout=10.0)
            )
            tick = _integer(last_status, "simulation_tick")
            if first_tick == 0 and tick > 0:
                first_tick = tick
                first_tick_wall = time.monotonic()
            position = (
                _finite(last_gameplay, "bot_x"),
                _finite(last_gameplay, "bot_y"),
            )
            if first_position is None and position != (0.0, 0.0):
                first_position = position
            if first_position is not None:
                maximum_distance = max(
                    maximum_distance,
                    math.hypot(
                        position[0] - first_position[0],
                        position[1] - first_position[1],
                    ),
                )
            maximum_killed = max(
                maximum_killed,
                _integer(last_gameplay, "wave_killed"),
            )
            minimum_enemy_hp_ratio = min(
                minimum_enemy_hp_ratio,
                _finite(last_gameplay, "minimum_enemy_hp_ratio"),
            )
            damage_observed = (
                maximum_killed > 0
                or _integer(last_gameplay, "damaged_enemy_count") > 0
                or minimum_enemy_hp_ratio < 0.999
            )
            if (
                last_status.get("clock_source") == "simulation"
                and _integer(last_status, "policy_decision_count") >= 10
                and _integer(last_status, "move_accepted") > 0
                and _integer(last_status, "cast_accepted") > 0
                and maximum_distance >= MINIMUM_LIVE_DISPLACEMENT
                and tick - first_tick >= MINIMUM_ACCEPTANCE_TICKS
                and damage_observed
            ):
                break
            time.sleep(0.05)
        else:
            raise BridgeError(
                "learned bot live acceptance timed out: "
                f"status={last_status}, gameplay={last_gameplay}"
            )

        elapsed = time.monotonic() - started_at
        simulation_elapsed_wall = max(
            time.monotonic() - first_tick_wall,
            0.0,
        )
        final_tick = _integer(last_status, "simulation_tick")
        simulated_seconds = max(final_tick - first_tick, 0) * 0.01
        result: dict[str, object] = {
            "status": "ok",
            "instance": instance,
            "headless": not args.visible,
            "process_id": launch.get("processId") if launch else None,
            "policy_generation": generation,
            "clock_source": last_status.get("clock_source"),
            "simulation_tick_start": first_tick,
            "simulation_tick_end": final_tick,
            "policy_decision_count": _integer(
                last_status,
                "policy_decision_count",
            ),
            "move_accepted": _integer(last_status, "move_accepted"),
            "cast_accepted": _integer(last_status, "cast_accepted"),
            "maximum_bot_displacement": maximum_distance,
            "wave": _integer(last_gameplay, "wave"),
            "wave_killed": maximum_killed,
            "minimum_enemy_hp_ratio": minimum_enemy_hp_ratio,
            "last_movement": last_gameplay.get("policy_movement_name"),
            "last_cast": last_gameplay.get("policy_cast_name"),
            "elapsed_wall_seconds": elapsed,
            "simulation_elapsed_wall_seconds": simulation_elapsed_wall,
            "simulated_seconds": simulated_seconds,
            "simulation_to_wall_ratio": (
                simulated_seconds / simulation_elapsed_wall
                if simulation_elapsed_wall > 0
                else 0.0
            ),
        }
        return result
    finally:
        session.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=str(DEFAULT_MODEL))
    parser.add_argument("--instance")
    parser.add_argument(
        "--game-directory",
        default=str(DEFAULT_GAME_DIRECTORY),
    )
    parser.add_argument("--launcher-path", default=str(DEFAULT_LAUNCHER))
    parser.add_argument(
        "--runtime-root",
        default=str(ROOT / "runtime"),
    )
    parser.add_argument("--local-port", type=int, default=49790)
    parser.add_argument("--unused-remote-port", type=int, default=49791)
    parser.add_argument("--startup-timeout", type=float, default=45.0)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument(
        "--element",
        choices=("fire", "water", "earth", "air", "ether"),
        default="fire",
    )
    parser.add_argument(
        "--discipline",
        choices=("mind", "body", "arcane"),
        default="arcane",
    )
    parser.add_argument("--visible", action="store_true")
    parser.add_argument("--output")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = verify(args)
        output = json.dumps(result, indent=2, sort_keys=True)
        print(output)
        if args.output:
            path = Path(args.output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(output + "\n", encoding="utf-8")
        return 0
    except (
        BridgeError,
        local_sync.VerifyFailure,
        OSError,
        RuntimeError,
        ValueError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
