#!/usr/bin/env python3
"""Live baseline for pure-primary startup/latch and PerCast mana behavior.

This probe intentionally records the current Fire/Ether gap instead of
asserting the desired final behavior. It fails only when it cannot materialize
a bot, queue the casts, or observe a terminal cast event.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import cast_state_probe as csp  # noqa: E402
from run_live_native_spell_stats_probe import (  # noqa: E402
    drive_to_materialized_bots,
    find_bot_for_element,
    list_bot_states,
    force_bot_mana,
    queue_skill,
    read_runtime_layout_offset,
    tail_loader_log,
)
from run_live_bot_native_mana_spend_probe import read_loader_log_lines, stop_bot  # noqa: E402


OUTPUT_PATH = ROOT / "runtime" / "live_pure_primary_startup_probe.json"
FORCED_MANA = 250.0
PURE_PRIMARY_CASTS = (
    {"name": "fire", "element_id": 0, "skill_id": 0x3F3},
    {"name": "ether", "element_id": 4, "skill_id": 0x3F2},
)

CAST_COMPLETE_RE = re.compile(
    r"cast complete \((?P<label>[^)]+)\)\. bot_id=(?P<bot_id>\d+) "
    r"skill_id=(?P<skill_id>-?\d+) ticks=(?P<ticks>\d+).*"
)
MANA_SPENT_RE = re.compile(
    r"mana spent\. bot_id=(?P<bot_id>\d+) skill_id=(?P<skill_id>-?\d+) "
    r"mode=(?P<mode>[a-z_]+) progression_level=(?P<level>\d+) "
    r".*?cost=(?P<cost>[0-9.+\-eE]+) "
    r"before=(?P<before>[0-9.+\-eE]+) after=(?P<after>[0-9.+\-eE]+) "
    r"native=(?P<native>\d+) native_result=(?P<native_result>\d+) "
    r"seh=(?P<seh>0x[0-9A-Fa-f]+) total=(?P<total>[0-9.+\-eE]+)"
)
SPELL_DIAG_RE = re.compile(r"spell_obj diag\. bot_id=(?P<bot_id>\d+).*")
NATIVE_LATCH_EVENT_TOKENS = (
    "wizard cast prepped",
    "pure_primary_start enter",
    "pure_primary_start exit",
    "spell_dispatch enter",
    "spell_dispatch exit",
    "gameplay-slot post-stock dispatch",
)


class LivePurePrimaryStartupProbeFailure(RuntimeError):
    pass


def float_or_none(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def capture_actor_cast_snapshot(bot_id: int) -> dict[str, str]:
    progression_mp_offset = read_runtime_layout_offset("progression_mp")
    actor_primary_skill_id_offset = read_runtime_layout_offset("actor_primary_skill_id")
    actor_active_cast_group_offset = read_runtime_layout_offset("actor_active_cast_group_byte")
    actor_active_cast_slot_offset = read_runtime_layout_offset("actor_active_cast_slot_short")
    actor_primary_latch_e4_offset = read_runtime_layout_offset("actor_primary_action_latch_e4")
    actor_primary_latch_e8_offset = read_runtime_layout_offset("actor_primary_action_latch_e8")
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
local bot = sd.bots.get_state({bot_id})
if type(bot) ~= 'table' then
  emit('available', false)
  return
end
local actor = tonumber(bot.actor_address) or 0
local progression = tonumber(bot.progression_runtime_state_address) or 0
emit('available', true)
emit('actor', actor)
emit('progression', progression)
emit('bot_mp', bot.mp)
emit('actor_e4', actor ~= 0 and sd.debug.read_u32(actor + {actor_primary_latch_e4_offset}) or nil)
emit('actor_e8', actor ~= 0 and sd.debug.read_u32(actor + {actor_primary_latch_e8_offset}) or nil)
emit('primary_skill_id', actor ~= 0 and sd.debug.read_u32(actor + {actor_primary_skill_id_offset}) or nil)
emit('active_group', actor ~= 0 and sd.debug.read_u8(actor + {actor_active_cast_group_offset}) or nil)
emit('active_slot', actor ~= 0 and sd.debug.read_u16(actor + {actor_active_cast_slot_offset}) or nil)
emit('progression_mp', progression ~= 0 and sd.debug.read_float(progression + {progression_mp_offset}) or nil)
""".strip()
        )
    )


def parse_completion(match: re.Match[str], line: str) -> dict[str, Any]:
    return {
        "line": line,
        "label": match.group("label"),
        "bot_id": int(match.group("bot_id")),
        "skill_id": int(match.group("skill_id")),
        "ticks": int(match.group("ticks")),
    }


def parse_mana(match: re.Match[str], line: str) -> dict[str, Any]:
    return {
        "line": line,
        "bot_id": int(match.group("bot_id")),
        "skill_id": int(match.group("skill_id")),
        "mode": match.group("mode"),
        "cost": float(match.group("cost")),
        "before": float(match.group("before")),
        "after": float(match.group("after")),
        "native": int(match.group("native")),
        "native_result": int(match.group("native_result")),
        "seh": match.group("seh"),
        "total": float(match.group("total")),
    }


def wait_for_terminal_cast(
    bot_id: int,
    skill_id: int,
    start_line_count: int,
    timeout_s: float,
) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    observed_mana: list[dict[str, Any]] = []
    observed_diags: list[str] = []
    observed_native_events: list[str] = []
    last_tail: list[str] = []
    while time.time() < deadline:
        lines = read_loader_log_lines()
        last_tail = lines[-200:]
        for line in lines[start_line_count:]:
            if f"bot_id={bot_id}" in line and any(token in line for token in NATIVE_LATCH_EVENT_TOKENS):
                if line not in observed_native_events:
                    observed_native_events.append(line)
            mana_match = MANA_SPENT_RE.search(line)
            if mana_match and int(mana_match.group("bot_id")) == bot_id and int(mana_match.group("skill_id")) == skill_id:
                parsed = parse_mana(mana_match, line)
                if parsed not in observed_mana:
                    observed_mana.append(parsed)
            diag_match = SPELL_DIAG_RE.search(line)
            if diag_match and int(diag_match.group("bot_id")) == bot_id and line not in observed_diags:
                observed_diags.append(line)
            complete_match = CAST_COMPLETE_RE.search(line)
            if (
                complete_match
                and int(complete_match.group("bot_id")) == bot_id
                and int(complete_match.group("skill_id")) == skill_id
            ):
                completion = parse_completion(complete_match, line)
                return {
                    "completion": completion,
                    "mana_spent": observed_mana,
                    "spell_diags": observed_diags,
                    "native_latch_events": observed_native_events,
                }
        time.sleep(0.25)

    raise LivePurePrimaryStartupProbeFailure(
        "timed out waiting for pure-primary terminal cast; "
        f"skill_id={skill_id} tail={json.dumps(last_tail[-30:], indent=2)}"
    )


def run_single_cast(
    bot_id: int,
    skill_id: int,
    target_x: float,
    target_y: float,
    timeout_s: float,
) -> dict[str, Any]:
    stop_result = stop_bot(bot_id)
    mana_write = force_bot_mana(bot_id, FORCED_MANA, FORCED_MANA)
    if mana_write.get("ok") != "true":
        raise LivePurePrimaryStartupProbeFailure(f"failed to force bot mana for {skill_id}: {mana_write}")

    before_snapshot = capture_actor_cast_snapshot(bot_id)
    start_line_count = len(read_loader_log_lines())
    cast_result = queue_skill(bot_id, skill_id, target_x, target_y)
    if cast_result.get("ok") != "true":
        raise LivePurePrimaryStartupProbeFailure(f"sd.bots.cast rejected skill {skill_id}: {cast_result}")

    terminal = wait_for_terminal_cast(bot_id, skill_id, start_line_count, timeout_s)
    after_snapshot = capture_actor_cast_snapshot(bot_id)
    before_mp = float_or_none(before_snapshot.get("progression_mp"))
    after_mp = float_or_none(after_snapshot.get("progression_mp"))
    return {
        "stop_result": stop_result,
        "mana_write": mana_write,
        "cast_result": cast_result,
        "snapshot_before": before_snapshot,
        "snapshot_after": after_snapshot,
        "mp_delta": None if before_mp is None or after_mp is None else before_mp - after_mp,
        **terminal,
    }


def run_probe(element: str, discipline: str, timeout_s: float) -> dict[str, Any]:
    result = drive_to_materialized_bots(
        element,
        discipline,
        active_bot_keys="fire,ether",
        min_count=len(PURE_PRIMARY_CASTS),
    )
    bots = [dict(bot) for bot in result["bots_initial"]]
    cast_results: list[dict[str, Any]] = []
    for spec in PURE_PRIMARY_CASTS:
        bot = find_bot_for_element(bots, int(spec["element_id"]))
        bot_id = csp.int_value(bot, "id")
        bot_x = csp.float_value(bot, "x")
        bot_y = csp.float_value(bot, "y")
        if bot_id == 0 or bot_x != bot_x or bot_y != bot_y:
            raise LivePurePrimaryStartupProbeFailure(f"materialized bot has invalid state: {bot}")
        target_x = bot_x + 160.0
        target_y = bot_y
        cast_results.append(
            {
                "name": spec["name"],
                "bot_id": bot_id,
                "skill_id": spec["skill_id"],
                **run_single_cast(bot_id, int(spec["skill_id"]), target_x, target_y, timeout_s),
            }
        )
        time.sleep(0.5)

    result["pure_primary_casts"] = cast_results
    result["bots_final"] = list_bot_states()
    result["bot_final"] = csp.query_bot_state()
    result["loader_log_tail"] = tail_loader_log()
    return result


def assert_native_percast_behavior(result: dict[str, Any]) -> None:
    failures: list[str] = []
    for entry in result.get("pure_primary_casts", []):
        name = entry.get("name", "<unknown>")
        completion = entry.get("completion", {})
        label = completion.get("label")
        mana_events = entry.get("mana_spent", [])
        per_cast_events = [
            event for event in mana_events
            if (
                event.get("mode") == "per_cast"
                and event.get("native") == 1
                and str(event.get("seh", "")).lower() == "0x0"
                and event.get("cost", 0.0) > 0.0
                and event.get("before", 0.0) > event.get("after", 0.0)
                and event.get("before", 0.0) - event.get("after", 0.0) + 0.01 >= event.get("cost", 0.0)
            )
        ]
        if label == "startup_timeout":
            failures.append(f"{name}: still exits via startup_timeout")
        if not per_cast_events:
            failures.append(f"{name}: no native PerCast mana spend event with native=1/seh=0 and a real MP delta")
    if failures:
        raise LivePurePrimaryStartupProbeFailure("; ".join(failures))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--element", default="fire", choices=sorted(csp.CREATE_ELEMENT_CENTERS))
    parser.add_argument("--discipline", default="mind", choices=sorted(csp.CREATE_DISCIPLINE_CENTERS))
    parser.add_argument("--timeout", type=float, default=16.0)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--json", action="store_true", help="Only print structured JSON.")
    parser.add_argument("--keep-running", action="store_true", help="Leave the game process running after the probe.")
    parser.add_argument(
        "--allow-startup-timeout-baseline",
        action="store_true",
        help="Record the old gap without failing; default enforces the fixed native PerCast behavior.",
    )
    args = parser.parse_args()

    exit_code = 0
    try:
        result = run_probe(args.element, args.discipline, args.timeout)
        result["native_percast_required"] = not args.allow_startup_timeout_baseline
        if not args.allow_startup_timeout_baseline:
            assert_native_percast_behavior(result)
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
        summaries = []
        for entry in result["pure_primary_casts"]:
            completion = entry["completion"]
            summaries.append(
                f"{entry['name']}={completion['label']}/ticks{completion['ticks']}/mana_events{len(entry['mana_spent'])}"
            )
        print("PASS: live pure-primary startup baseline " + " ".join(summaries))
        print(f"Wrote {args.output}")
    else:
        print(f"FAIL: live pure-primary startup probe: {result.get('error')}")
        print(f"Wrote {args.output}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
