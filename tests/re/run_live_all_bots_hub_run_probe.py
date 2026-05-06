#!/usr/bin/env python3
"""Live all-bot materialization probe for hub and run scenes.

This launches the staged game with every Lua bot profile active, drives a fresh
hub entry, verifies all five element bots materialize near the live player with
real actor/progression handles, then enters a testrun and repeats the same
checks. It is a regression guard for the "spawned but not visible" class of
failures.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import math
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))
TESTS_DIR = ROOT / "tests" / "re"
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

import cast_state_probe as csp  # noqa: E402
from run_live_native_spell_stats_probe import (  # noqa: E402
    PRIMARY_SKILLS,
    list_bot_states,
    temporary_active_bots_config,
)


OUTPUT_PATH = ROOT / "runtime" / "live_all_bots_hub_run_probe.json"
REPLAY_SCRIPT = ROOT / "scripts" / "Replay-UiSandbox.ps1"
UI_SANDBOX_PRESET_PATH = ROOT / "mods" / "lua_ui_sandbox_lab" / "config" / "active_preset.txt"
EXPECTED_ELEMENT_IDS = sorted(int(spec["element_id"]) for spec in PRIMARY_SKILLS)


class LiveAllBotsHubRunProbeFailure(RuntimeError):
    pass


@contextmanager
def temporary_ui_sandbox_preset(preset: str):
    existed = UI_SANDBOX_PRESET_PATH.exists()
    original_text = UI_SANDBOX_PRESET_PATH.read_text(encoding="utf-8") if existed else None
    UI_SANDBOX_PRESET_PATH.parent.mkdir(parents=True, exist_ok=True)
    UI_SANDBOX_PRESET_PATH.write_text(f"{preset}\n", encoding="utf-8")
    try:
        yield
    finally:
        if existed and original_text is not None:
            UI_SANDBOX_PRESET_PATH.write_text(original_text, encoding="utf-8")
        else:
            UI_SANDBOX_PRESET_PATH.unlink(missing_ok=True)


def finite_float(values: dict[str, str], key: str) -> float:
    value = csp.float_value(values, key)
    if not math.isfinite(value):
        return math.nan
    return value


def bot_distance_from_player(bot: dict[str, str], player: dict[str, str]) -> float:
    px = finite_float(player, "x")
    py = finite_float(player, "y")
    bx = finite_float(bot, "x")
    by = finite_float(bot, "y")
    if any(math.isnan(value) for value in (px, py, bx, by)):
        return math.inf
    dx = bx - px
    dy = by - py
    return math.sqrt(dx * dx + dy * dy)


def summarize_bot(bot: dict[str, str], player: dict[str, str]) -> dict[str, Any]:
    summary = dict(bot)
    summary["distance_from_player"] = bot_distance_from_player(bot, player)
    return summary


def validate_snapshot(snapshot: dict[str, Any], *, scene_name: str, max_distance: float) -> list[str]:
    issues: list[str] = []
    scene = snapshot["scene"]
    player = snapshot["player"]
    bots = snapshot["bots"]

    if scene.get("available") != "true" or scene.get("name") != scene_name:
        issues.append(f"scene is not settled {scene_name}: {scene}")
    if player.get("available") != "true" or csp.int_value(player, "actor_address") == 0:
        issues.append(f"player actor is unavailable: {player}")

    materialized = [
        bot for bot in bots
        if csp.int_value(bot, "actor_address") != 0
    ]
    if len(materialized) < len(EXPECTED_ELEMENT_IDS):
        issues.append(f"expected {len(EXPECTED_ELEMENT_IDS)} materialized bots, saw {len(materialized)}")

    element_ids = sorted(csp.int_value(bot, "profile_element_id") for bot in materialized)
    if element_ids != EXPECTED_ELEMENT_IDS:
        issues.append(f"expected element ids {EXPECTED_ELEMENT_IDS}, saw {element_ids}")

    for bot in materialized:
        bot_id = csp.int_value(bot, "id")
        if bot_id == 0:
            issues.append(f"bot is missing id: {bot}")
        for key in (
            "actor_address",
            "progression_runtime_state_address",
            "progression_handle_address",
            "equip_runtime_state_address",
        ):
            if csp.int_value(bot, key) == 0:
                issues.append(f"bot {bot_id} has missing {key}: {bot}")
        max_hp = finite_float(bot, "max_hp")
        max_mp = finite_float(bot, "max_mp")
        hp = finite_float(bot, "hp")
        mp = finite_float(bot, "mp")
        if not (max_hp > 0.0 and max_mp > 0.0 and hp >= 0.0 and mp >= 0.0):
            issues.append(f"bot {bot_id} has invalid live resources: {bot}")
        distance = float(bot.get("distance_from_player", math.inf))
        if not math.isfinite(distance) or distance > max_distance:
            issues.append(
                f"bot {bot_id} is too far from player: distance={distance:.3f} max={max_distance:.3f}"
            )

    return issues


def capture_snapshot(label: str) -> dict[str, Any]:
    scene = csp.query_scene_state()
    player = csp.query_player_state()
    bots = [summarize_bot(bot, player) for bot in list_bot_states()]
    return {
        "label": label,
        "scene": scene,
        "player": player,
        "bots": bots,
    }


def parse_replay_output(output: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in output.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def launch_hub_with_replay(element: str, discipline: str, timeout_s: float) -> dict[str, Any]:
    preset = f"map_create_{element}_{discipline}_hub"
    args = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        csp.to_windows_path(REPLAY_SCRIPT),
        "-Preset",
        preset,
        "-BotSet",
        "all",
        "-KeepRunning",
        "-CompletionTimeoutSeconds",
        str(int(timeout_s)),
    ]
    timed_out = False
    replay_output_timeout_s = max(timeout_s + 45.0, 60.0)
    try:
        result = csp.run_command(args, timeout=replay_output_timeout_s)
        returncode: int | None = result.returncode
        stdout = result.stdout or ""
        stderr = result.stderr or ""
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        returncode = None
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
    output = stdout + stderr
    values = parse_replay_output(output)
    if (
        returncode not in (0, None) or
        values.get("OUTCOME") != "complete" or
        values.get("PROCESS_ALIVE") != "True"
    ):
        raise LiveAllBotsHubRunProbeFailure(
            "Replay harness failed to leave a live all-bot hub session. "
            f"returncode={returncode} timed_out={timed_out} values={values} output={output}"
        )
    return {
        "preset": preset,
        "returncode": returncode,
        "timed_out_after_success": timed_out,
        "values": values,
        "stdout": stdout,
        "stderr": stderr,
    }


def wait_for_valid_snapshot(
    label: str,
    *,
    scene_name: str,
    max_distance: float,
    timeout_s: float,
) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    last_snapshot: dict[str, Any] = {}
    last_issues: list[str] = []
    while time.time() < deadline:
        last_snapshot = capture_snapshot(label)
        last_issues = validate_snapshot(last_snapshot, scene_name=scene_name, max_distance=max_distance)
        if not last_issues:
            last_snapshot["issues"] = []
            return last_snapshot
        time.sleep(0.25)

    last_snapshot["issues"] = last_issues
    raise LiveAllBotsHubRunProbeFailure(
        f"Timed out waiting for valid {label} all-bot snapshot: {last_issues}"
    )


def start_testrun_without_waves() -> dict[str, Any]:
    scene = csp.query_scene_state()
    if csp.is_settled_scene(scene, "testrun"):
        return {"ok": "true", "already_testrun": "true", "scene": scene}

    values = csp.parse_key_values(
        csp.run_lua("print('ok='..tostring(sd.hub.start_testrun()))")
    )
    if values.get("ok") != "true":
        raise LiveAllBotsHubRunProbeFailure(f"sd.hub.start_testrun failed: {values}")
    scene = csp.wait_for_scene("testrun", timeout_s=45.0)
    return {"ok": "true", "scene": scene}


def run_probe(element: str, discipline: str, max_distance: float, timeout_s: float) -> dict[str, Any]:
    result: dict[str, Any] = {
        "launcher_freshness": csp.ensure_launcher_bundle_fresh(),
        "navigation": [],
        "expected_element_ids": EXPECTED_ELEMENT_IDS,
        "max_distance": max_distance,
    }

    csp.stop_game()
    csp.clear_loader_log()
    with temporary_active_bots_config("all"), temporary_ui_sandbox_preset("idle"):
        replay = launch_hub_with_replay(element, discipline, timeout_s)
        result["replay"] = replay
        process_id = int(replay["values"].get("PROCESS_ID", "0"))
        result["process_id"] = process_id
        csp.wait_for_lua_pipe()
        result["navigation"].append({"step": "hub_ready", "replay": replay["values"]})
        result["hub"] = wait_for_valid_snapshot(
            "hub",
            scene_name="hub",
            max_distance=max_distance,
            timeout_s=timeout_s,
        )

        testrun = start_testrun_without_waves()
        result["navigation"].append({"step": "testrun_started_without_waves", "result": testrun})
        result["run"] = wait_for_valid_snapshot(
            "run",
            scene_name="testrun",
            max_distance=max_distance,
            timeout_s=timeout_s,
        )

    result["loader_log_tail"] = csp.tail_loader_log(180)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--element", default="fire", choices=sorted(csp.CREATE_ELEMENT_CENTERS))
    parser.add_argument("--discipline", default="mind", choices=sorted(csp.CREATE_DISCIPLINE_CENTERS))
    parser.add_argument("--max-distance", type=float, default=240.0)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--json", action="store_true", help="Only print structured JSON.")
    parser.add_argument("--keep-running", action="store_true", help="Leave the game process running after the probe.")
    args = parser.parse_args()

    result: dict[str, Any]
    exit_code = 0
    try:
        result = run_probe(args.element, args.discipline, args.max_distance, args.timeout)
        result["passed"] = True
    except Exception as exc:  # noqa: BLE001 - probe preserves diagnostics in JSON.
        result = {
            "passed": False,
            "error": str(exc),
            "loader_log_tail": csp.tail_loader_log(180),
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
        hub_max = max(bot["distance_from_player"] for bot in result["hub"]["bots"])
        run_max = max(bot["distance_from_player"] for bot in result["run"]["bots"])
        print(
            "PASS: all five element bots materialized near the player "
            f"in hub and run (hub_max={hub_max:.3f}, run_max={run_max:.3f})"
        )
        print(f"Wrote {args.output}")
    else:
        print(f"FAIL: live all-bots hub/run probe: {result.get('error')}")
        print(f"Wrote {args.output}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
