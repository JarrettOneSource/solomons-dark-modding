#!/usr/bin/env python3
"""Live RE probe for native bot mana writers.

This is the evidence gate for bot mana-spend ownership. It traces the stock
mana-delta function during a bot cast and requires both a bot-owned negative
native delta call and a real live MP decrease on that bot's progression state.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
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
    assert_gameplay_player_mana_not_decreased,
    capture_gameplay_player_actor,
    clear_native_mana_delta_trace,
    find_latest_mana_prepared_cost,
    query_bot_runtime,
    query_native_mana_delta_trace_hits,
    read_loader_log_lines,
    summarize_native_mana_delta_trace_hits,
    stop_bot,
    wait_for_bot_native_mana_delta,
)
from run_live_bot_native_mana_spend_probe import EARTH_PRIMARY_SKILL_ID, FORCED_MANA  # noqa: E402
from run_live_native_spell_stats_probe import (  # noqa: E402
    drive_to_materialized_bots,
    force_bot_mana,
    queue_skill,
    set_lua_bot_tick_enabled,
    tail_loader_log,
)


OUTPUT_PATH = ROOT / "runtime" / "live_bot_mana_writer_probe.json"
TRACE_NAME = "bot_native_mana_delta"


class LiveBotManaWriterFailure(RuntimeError):
    pass


def queue_earth_primary_and_observe(
    bot_id: int,
    actor_address: int,
    before_mp: float,
    target_x: float,
    target_y: float,
    *,
    target_actor_address: int = 0,
    observe_seconds: float,
    player_actor_address: int = 0,
    gameplay_player_before: dict[str, str] | None = None,
) -> dict[str, Any]:
    log_start_index = len(read_loader_log_lines())
    trace = arm_native_mana_delta_trace(TRACE_NAME)
    if trace.get("trace_ok") != "true":
        raise LiveBotManaWriterFailure(f"failed to arm native mana delta trace: {trace}")

    try:
        cast_result = queue_skill(
            bot_id,
            EARTH_PRIMARY_SKILL_ID,
            target_x,
            target_y,
            target_actor_address=target_actor_address,
        )
        if cast_result.get("ok") != "true":
            raise LiveBotManaWriterFailure(f"sd.bots.cast rejected Earth primary: {cast_result}")
        time.sleep(observe_seconds)
        bot_after = query_bot_runtime(bot_id)
        hits = query_native_mana_delta_trace_hits(TRACE_NAME)
    finally:
        clear_native_mana_delta_trace(TRACE_NAME)
        stop_after_cast = stop_bot(bot_id)

    after_mp = csp.float_value(bot_after, "mp")
    summary = summarize_native_mana_delta_trace_hits(hits, actor_address, player_actor_address)
    mp_delta = before_mp - after_mp if after_mp == after_mp else float("nan")
    gameplay_player_after = (
        capture_gameplay_player_actor()
        if gameplay_player_before is not None
        else None
    )
    if summary["negative_player_actor_hits"]:
        raise LiveBotManaWriterFailure(
            "coordinate-only Earth startup hit the gameplay player actor with native mana delta: "
            f"{summary['negative_player_actor_hits']}"
        )
    if gameplay_player_before is not None and gameplay_player_after is not None:
        assert_gameplay_player_actor_unchanged(
            gameplay_player_before,
            gameplay_player_after,
            "coordinate-only Earth startup",
        )
        assert_gameplay_player_mana_not_decreased(
            gameplay_player_before,
            gameplay_player_after,
            "coordinate-only Earth startup",
        )
    result: dict[str, Any] = {
        "trace": trace,
        "cast_result": cast_result,
        "bot_after": bot_after,
        "trace_hits": hits,
        "trace_hit_summary": summary,
        "mp_delta": mp_delta,
        "gameplay_player_after": gameplay_player_after,
        "stop_after_cast": stop_after_cast,
    }

    if mp_delta >= 0.001 or summary["negative_bot_actor_hits"]:
        prepared_rate = find_latest_mana_prepared_cost(
            read_loader_log_lines(),
            log_start_index,
            bot_id,
            EARTH_PRIMARY_SKILL_ID,
        )
        result["prepared_native_mana_rate"] = prepared_rate
        assert_native_mana_delta_matches_prepared_rate(
            {
                "trace_hit_summary": summary,
                "mp_delta": mp_delta,
            },
            prepared_rate,
            "coordinate-only Earth startup",
        )
        result["spend_mode"] = "plausible_native_spend"
    else:
        result["spend_mode"] = "no_stale_native_spend"

    return result


def run_probe(element: str, discipline: str, timeout_s: float) -> dict[str, Any]:
    result = drive_to_materialized_bots(
        element,
        discipline,
        active_bot_keys="earth",
        min_count=1,
        start_waves=False,
        post_testrun_settle_seconds=1.0,
    )
    bot = dict(result["bot_initial"])
    bot_id = csp.int_value(bot, "id")
    bot_x = csp.float_value(bot, "x")
    bot_y = csp.float_value(bot, "y")
    if bot_id == 0 or bot_x != bot_x or bot_y != bot_y:
        raise LiveBotManaWriterFailure(f"materialized bot has invalid state: {bot}")

    result["tick_gate"] = set_lua_bot_tick_enabled(False)
    stop_result = stop_bot(bot_id)
    mana_write = force_bot_mana(bot_id, FORCED_MANA, FORCED_MANA)
    if mana_write.get("ok") != "true":
        raise LiveBotManaWriterFailure(f"failed to force bot mana: {mana_write}")

    bot_before = query_bot_runtime(bot_id)
    progression_address = csp.int_value(bot_before, "progression_runtime_state_address")
    actor_address = csp.int_value(bot_before, "actor_address")
    before_mp = csp.float_value(bot_before, "mp")
    if actor_address == 0 or progression_address == 0 or before_mp != before_mp:
        raise LiveBotManaWriterFailure(f"bot has invalid runtime state: {bot_before}")

    gameplay_actor_before = capture_gameplay_player_actor()
    gameplay_player_actor_address = csp.int_value(gameplay_actor_before, "gameplay_player_actor")
    no_target_probe = queue_earth_primary_and_observe(
        bot_id,
        actor_address,
        before_mp,
        bot_x + 160.0,
        bot_y,
        observe_seconds=3.0,
        player_actor_address=gameplay_player_actor_address,
        gameplay_player_before=gameplay_actor_before,
    )

    mana_write_targeted = force_bot_mana(bot_id, FORCED_MANA, FORCED_MANA)
    if mana_write_targeted.get("ok") != "true":
        raise LiveBotManaWriterFailure(f"failed to restore bot mana: {mana_write_targeted}")
    bot_before_targeted = query_bot_runtime(bot_id)
    before_mp_targeted = csp.float_value(bot_before_targeted, "mp")
    if before_mp_targeted != before_mp_targeted:
        raise LiveBotManaWriterFailure(f"bot has invalid targeted MP state: {bot_before_targeted}")

    csp.start_run_and_waves()
    csp.boost_player_survival()
    enemy = csp.wait_for_nearest_enemy(timeout_s=30.0, max_gap=5000.0)
    target_actor_address = csp.int_value(enemy, "actor_address")
    target_x = csp.float_value(enemy, "x")
    target_y = csp.float_value(enemy, "y")
    if target_actor_address == 0 or target_x != target_x or target_y != target_y:
        raise LiveBotManaWriterFailure(f"invalid native wave target: {enemy}")

    log_start_index = len(read_loader_log_lines())
    trace = arm_native_mana_delta_trace(TRACE_NAME)
    if trace.get("trace_ok") != "true":
        raise LiveBotManaWriterFailure(f"failed to arm native mana delta trace: {trace}")

    try:
        cast_result = queue_skill(
            bot_id,
            EARTH_PRIMARY_SKILL_ID,
            target_x,
            target_y,
            target_actor_address=target_actor_address,
        )
        if cast_result.get("ok") != "true":
            raise LiveBotManaWriterFailure(f"sd.bots.cast rejected Earth primary: {cast_result}")

        mana_delta = wait_for_bot_native_mana_delta(
            bot_id,
            actor_address,
            before_mp_targeted,
            TRACE_NAME,
            timeout_s,
            player_actor_address=gameplay_player_actor_address,
            gameplay_player_before=gameplay_actor_before,
        )
    finally:
        clear_native_mana_delta_trace(TRACE_NAME)
        stop_after_cast = stop_bot(bot_id)

    gameplay_actor_after = capture_gameplay_player_actor()
    assert_gameplay_player_actor_unchanged(
        gameplay_actor_before,
        gameplay_actor_after,
        "bot mana writer probe",
    )
    assert_gameplay_player_mana_not_decreased(
        gameplay_actor_before,
        gameplay_actor_after,
        "bot mana writer probe",
    )
    prepared_rate = find_latest_mana_prepared_cost(
        read_loader_log_lines(),
        log_start_index,
        bot_id,
        EARTH_PRIMARY_SKILL_ID,
    )
    assert_native_mana_delta_matches_prepared_rate(
        mana_delta,
        prepared_rate,
        "targeted Earth startup",
    )

    result.update(
        {
            "stop_result": stop_result,
            "force_bot_mana": mana_write,
            "bot_before": bot_before,
            "gameplay_player_actor_before": gameplay_actor_before,
            "coordinate_only_stale_config_guard": no_target_probe,
            "force_bot_mana_targeted": mana_write_targeted,
            "bot_before_targeted": bot_before_targeted,
            "target_enemy": enemy,
            "trace": trace,
            "cast_result": cast_result,
            "prepared_native_mana_rate": prepared_rate,
            "stock_native_mana_delta": mana_delta,
            "stop_after_cast": stop_after_cast,
            "gameplay_player_actor_after": gameplay_actor_after,
            "player_mp_delta": mana_delta.get("player_mp_delta"),
            "loader_log_tail": tail_loader_log(220),
        }
    )
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--element", default="fire", choices=sorted(csp.CREATE_ELEMENT_CENTERS))
    parser.add_argument("--discipline", default="mind", choices=sorted(csp.CREATE_DISCIPLINE_CENTERS))
    parser.add_argument("--timeout", type=float, default=12.0)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--keep-running", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    exit_code = 0
    result: dict[str, Any] = {}
    try:
        result = run_probe(args.element, args.discipline, args.timeout)
        result["passed"] = True
    except Exception as exc:  # noqa: BLE001 - preserve diagnostics in JSON.
        result["passed"] = False
        result["error"] = str(exc)
        result["loader_log_tail"] = tail_loader_log(220)
        exit_code = 1
    finally:
        if not args.keep_running:
            csp.stop_game()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    elif result.get("passed"):
        mana_delta = result.get("stock_native_mana_delta", {})
        summary = mana_delta.get("trace_hit_summary", {})
        print(
            "PASS: live bot mana writer probe captured stock native mana delta; "
            f"mp_delta={mana_delta.get('mp_delta'):.3f} "
            f"player_mp_delta={mana_delta.get('player_mp_delta'):.3f} "
            f"bot_actor_hits={len(summary.get('bot_actor_hits', []))} "
            f"player_actor_hits={len(summary.get('player_actor_hits', []))}"
        )
        print(f"Wrote {args.output}")
    else:
        print(f"FAIL: live bot mana writer probe: {result.get('error')}")
        print(f"Wrote {args.output}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
