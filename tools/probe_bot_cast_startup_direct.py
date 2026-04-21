#!/usr/bin/env python3
"""Drive a deterministic direct-cast startup probe and persist every step."""

from __future__ import annotations

import json
import time
from pathlib import Path

import cast_state_probe as csp
import probe_bot_close_range_combat as close_probe


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = ROOT / "runtime" / "probe_bot_cast_startup_direct.json"
DEFAULT_STANDOFF = 120.0


def write_progress(payload: dict[str, object]) -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def snapshot_bot_and_hostile() -> dict[str, object]:
    result: dict[str, object] = {}
    try:
        result["bot"] = csp.query_bot_state()
    except Exception as exc:  # noqa: BLE001
        result["bot_error"] = str(exc)
    try:
        result["scene"] = csp.query_scene_state()
    except Exception as exc:  # noqa: BLE001
        result["scene_error"] = str(exc)
    try:
        result["selection"] = csp.query_selection_debug_state()
    except Exception as exc:  # noqa: BLE001
        result["selection_error"] = str(exc)
    try:
        result["hostile"] = csp.wait_for_nearest_enemy(timeout_s=1.0, max_gap=5000.0)
    except Exception as exc:  # noqa: BLE001
        result["hostile_error"] = str(exc)
    return result


def main() -> int:
    result: dict[str, object] = {
        "launcher_freshness": csp.ensure_launcher_bundle_fresh(),
        "steps": [],
    }
    write_progress(result)

    def step(name: str, fn):
        try:
            value = fn()
            result["steps"].append({"name": name, "ok": True, "value": value})
            write_progress(result)
            return value
        except Exception as exc:  # noqa: BLE001
            result["steps"].append({"name": name, "ok": False, "error": str(exc)})
            result["error"] = f"{name}: {exc}"
            result["loader_log_tail"] = csp.tail_loader_log()
            write_progress(result)
            raise

    try:
        step("stop_game", csp.stop_game)
        step("clear_loader_log", csp.clear_loader_log)
        step("launch_game", csp.launch_game)
        process_id = step("wait_for_game_process", csp.wait_for_game_process)
        step("wait_for_lua_pipe", csp.wait_for_lua_pipe)
        step(
            "drive_new_game_flow",
            lambda: csp.drive_new_game_flow(
                process_id,
                element=csp.DEFAULT_ELEMENT,
                discipline=csp.DEFAULT_DISCIPLINE,
            ),
        )
        step("start_testrun_without_waves", close_probe.start_testrun_without_waves)
        step("set_lua_tick_enabled_false", lambda: close_probe.set_lua_tick_enabled(False))

        bot = step("wait_for_materialized_bot", csp.wait_for_materialized_bot)
        player = step("query_player_state", csp.query_player_state)
        step("snapshot_after_materialization", snapshot_bot_and_hostile)

        promotion = step(
            "promote_bot_into_run_scene",
            lambda: close_probe.promote_bot_into_run_scene(
                csp.float_value(player, "x"),
                csp.float_value(player, "y"),
            ),
        )
        result["promotion"] = promotion
        write_progress(result)
        time.sleep(1.0)
        bot = step("query_bot_after_promotion", csp.query_bot_state)
        step("stop_bot_after_promotion", lambda: close_probe.stop_bot(bot["id"]))

        spawn = step(
            "spawn_hostile_near_bot",
            lambda: close_probe.spawn_hostile_near_bot(
                csp.float_value(bot, "x"),
                csp.float_value(bot, "y"),
                DEFAULT_STANDOFF,
            ),
        )
        result["spawn"] = spawn
        write_progress(result)
        time.sleep(1.0)

        pre_cast_snapshot = step("pre_cast_snapshot", snapshot_bot_and_hostile)
        hostile = pre_cast_snapshot.get("hostile")
        if not isinstance(hostile, dict):
            raise RuntimeError(f"expected hostile snapshot, got {hostile!r}")

        direct_cast = step(
            "queue_direct_primary_cast",
            lambda: close_probe.queue_direct_primary_cast(
                bot["id"],
                hostile["actor_address"],
                csp.float_value(hostile, "x"),
                csp.float_value(hostile, "y"),
            ),
        )
        result["direct_cast"] = direct_cast
        write_progress(result)

        samples = []
        for index in range(6):
            time.sleep(0.5)
            sample = snapshot_bot_and_hostile()
            sample["index"] = index
            sample["monotonic_ms"] = int(time.time() * 1000.0)
            samples.append(sample)
            result["samples"] = samples
            write_progress(result)

        result["loader_log_tail"] = csp.tail_loader_log()
        write_progress(result)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    finally:
        try:
            close_probe.set_lua_tick_enabled(True)
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    raise SystemExit(main())
