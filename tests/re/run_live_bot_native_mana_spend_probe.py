#!/usr/bin/env python3
"""Live RE probe for bot mana spending through stock native spell handlers."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import cast_state_probe as csp  # noqa: E402
from bot_mana_trace_helpers import (  # noqa: E402
    assert_native_mana_delta_matches_prepared_rate,
    arm_native_mana_delta_trace,
    assert_gameplay_player_actor_unchanged,
    capture_gameplay_player_actor,
    clear_native_mana_delta_trace,
    find_latest_mana_prepared_cost,
    query_bot_runtime,
    read_loader_log_lines,
    stop_bot,
    wait_for_bot_native_mana_delta,
)
from run_live_native_spell_stats_probe import (  # noqa: E402
    drive_to_materialized_bots,
    force_bot_mana,
    queue_skill,
    set_lua_bot_tick_enabled,
    tail_loader_log,
)


OUTPUT_PATH = ROOT / "runtime" / "live_bot_native_mana_spend_probe.json"
TRACE_NAME = "bot_native_mana_spend"
EARTH_PRIMARY_SKILL_ID = 0x3F6
FORCED_MANA = 250.0


class LiveNativeManaSpendProbeFailure(RuntimeError):
    pass


def force_queue_and_wait_for_spend(
    bot_id: int,
    skill_id: int,
    target_x: float,
    target_y: float,
    timeout_s: float,
    *,
    target_actor_address: int = 0,
) -> dict[str, Any]:
    stop_result = stop_bot(bot_id)
    mana_write = force_bot_mana(bot_id, FORCED_MANA, FORCED_MANA)
    if mana_write.get("ok") != "true":
        raise LiveNativeManaSpendProbeFailure(f"failed to force bot mana for {skill_id}: {mana_write}")

    bot_before = query_bot_runtime(bot_id)
    actor_address = csp.int_value(bot_before, "actor_address")
    progression_address = csp.int_value(bot_before, "progression_runtime_state_address")
    before_mp = csp.float_value(bot_before, "mp")
    if actor_address == 0 or progression_address == 0 or before_mp != before_mp:
        raise LiveNativeManaSpendProbeFailure(f"bot has invalid runtime state: {bot_before}")

    gameplay_actor_before = capture_gameplay_player_actor()
    log_start_index = len(read_loader_log_lines())
    trace = arm_native_mana_delta_trace(TRACE_NAME)
    if trace.get("trace_ok") != "true":
        raise LiveNativeManaSpendProbeFailure(f"failed to arm native mana delta trace: {trace}")

    try:
        cast_result = queue_skill(
            bot_id,
            skill_id,
            target_x,
            target_y,
            target_actor_address=target_actor_address,
        )
        if cast_result.get("ok") != "true":
            raise LiveNativeManaSpendProbeFailure(f"sd.bots.cast rejected skill {skill_id}: {cast_result}")
        mana_delta = wait_for_bot_native_mana_delta(
            bot_id,
            actor_address,
            before_mp,
            TRACE_NAME,
            timeout_s,
        )
    finally:
        clear_native_mana_delta_trace(TRACE_NAME)
        stop_after_cast = stop_bot(bot_id)

    gameplay_actor_after = capture_gameplay_player_actor()
    assert_gameplay_player_actor_unchanged(
        gameplay_actor_before,
        gameplay_actor_after,
        str(skill_id),
    )
    if mana_delta["mp_delta"] <= 0.0:
        raise LiveNativeManaSpendProbeFailure(f"native mana delta did not reduce MP: {mana_delta}")
    prepared_rate = find_latest_mana_prepared_cost(
        read_loader_log_lines(),
        log_start_index,
        bot_id,
        skill_id,
    )
    assert_native_mana_delta_matches_prepared_rate(
        mana_delta,
        prepared_rate,
        f"skill {skill_id}",
    )

    return {
        "stop_result": stop_result,
        "mana_write": mana_write,
        "bot_before": bot_before,
        "gameplay_player_actor_before": gameplay_actor_before,
        "trace": trace,
        "cast_result": cast_result,
        "prepared_native_mana_rate": prepared_rate,
        "stock_native_mana_delta": mana_delta,
        "stop_after_cast": stop_after_cast,
        "gameplay_player_actor_after": gameplay_actor_after,
    }


def run_probe(element: str, discipline: str, timeout_s: float) -> dict[str, Any]:
    result = drive_to_materialized_bots(
        element,
        discipline,
        active_bot_keys="earth",
        min_count=1,
    )
    bot = dict(result["bot_initial"])
    bot_id = csp.int_value(bot, "id")
    bot_x = csp.float_value(bot, "x")
    bot_y = csp.float_value(bot, "y")
    if bot_id == 0 or bot_x != bot_x or bot_y != bot_y:
        raise LiveNativeManaSpendProbeFailure(f"materialized bot has invalid state: {bot}")

    result["tick_gate"] = set_lua_bot_tick_enabled(False)
    enemy = csp.wait_for_nearest_enemy(timeout_s=30.0, max_gap=5000.0)
    target_actor_address = csp.int_value(enemy, "actor_address")
    target_x = csp.float_value(enemy, "x")
    target_y = csp.float_value(enemy, "y")
    if target_actor_address == 0 or target_x != target_x or target_y != target_y:
        raise LiveNativeManaSpendProbeFailure(f"invalid native wave target: {enemy}")
    result["target_enemy"] = enemy
    result["per_second"] = force_queue_and_wait_for_spend(
        bot_id,
        EARTH_PRIMARY_SKILL_ID,
        target_x,
        target_y,
        timeout_s,
        target_actor_address=target_actor_address,
    )
    result["bot_final"] = csp.query_bot_state()
    result["loader_log_tail"] = tail_loader_log()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--element", default="fire", choices=sorted(csp.CREATE_ELEMENT_CENTERS))
    parser.add_argument("--discipline", default="mind", choices=sorted(csp.CREATE_DISCIPLINE_CENTERS))
    parser.add_argument("--timeout", type=float, default=12.0)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--json", action="store_true", help="Only print structured JSON.")
    parser.add_argument("--keep-running", action="store_true", help="Leave the game process running after the probe.")
    args = parser.parse_args()

    exit_code = 0
    try:
        result = run_probe(args.element, args.discipline, args.timeout)
        result["passed"] = True
    except Exception as exc:  # noqa: BLE001 - preserve live diagnostics in JSON.
        result = {
            "passed": False,
            "error": str(exc),
            "loader_log_tail": tail_loader_log(),
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
        mana_delta = result["per_second"]["stock_native_mana_delta"]
        print(
            "PASS: live bot native mana spend "
            f"mp_delta={mana_delta['mp_delta']:.3f} "
            f"bot_actor_hits={len(mana_delta['trace_hit_summary']['bot_actor_hits'])}"
        )
        print(f"Wrote {args.output}")
    else:
        print(f"FAIL: live bot native mana spend probe: {result.get('error')}")
        print(f"Wrote {args.output}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
