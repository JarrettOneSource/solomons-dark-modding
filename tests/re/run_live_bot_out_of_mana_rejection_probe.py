#!/usr/bin/env python3
"""Live RE probe for pre-execution bot out-of-mana rejection."""

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
    find_bot_for_element,
    list_bot_states,
    queue_default_primary,
    read_runtime_layout_offset,
    tail_loader_log,
    temporary_active_bots_config,
    wait_for_materialized_bots,
)


OUTPUT_PATH = ROOT / "runtime" / "live_bot_out_of_mana_rejection_probe.json"

MANA_REJECTED_RE = re.compile(
    r"(?:cast rejected for mana|mana rejected)\. bot_id=(?P<bot_id>\d+) "
    r"skill_id=(?P<skill_id>-?\d+) .*?mode=(?P<mode>[a-z_]+) .*"
)
QUEUED_CAST_RE = re.compile(r"queued cast for bot id=(?P<bot_id>\d+)\b")
MANA_SPENT_RE = re.compile(r"mana spent\. bot_id=(?P<bot_id>\d+) ")
LIFECYCLE_PATTERNS = (
    re.compile(r"(?:gameplay-slot|wizard) cast prepped\. bot_id=(?P<bot_id>\d+) "),
    re.compile(r"spell_dispatch enter actor=0x[0-9A-Fa-f]+ bot_id=(?P<bot_id>\d+)"),
    re.compile(r"pure_primary_start enter actor=0x[0-9A-Fa-f]+ bot_id=(?P<bot_id>\d+)"),
    re.compile(r"pure_primary_post_builder actor=0x[0-9A-Fa-f]+ bot_id=(?P<bot_id>\d+)"),
    re.compile(r"cast complete \([^)]+\)\. bot_id=(?P<bot_id>\d+) "),
    re.compile(r"native boulder release requested\. bot_id=(?P<bot_id>\d+) "),
)


class LiveBotOutOfManaProbeFailure(RuntimeError):
    pass


def read_loader_log_lines() -> list[str]:
    if not csp.LOADER_LOG.exists():
        return []
    with csp.LOADER_LOG.open("r", encoding="utf-8", errors="replace") as handle:
        return [line.rstrip("\n") for line in handle]


def stop_bot(bot_id: int) -> dict[str, str]:
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
emit('ok', sd.bots.stop({bot_id}))
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


def force_bot_mana(bot_id: int, current_mp: float, max_mp: float) -> dict[str, str]:
    mp_offset = read_runtime_layout_offset("progression_mp")
    max_mp_offset = read_runtime_layout_offset("progression_max_mp")
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
  emit('error', 'bot_not_found')
  return
end
local progression = tonumber(bot.progression_runtime_state_address) or 0
if progression == 0 then
  emit('ok', false)
  emit('error', 'missing_progression_runtime')
  return
end
local mp_address = progression + {mp_offset}
local max_mp_address = progression + {max_mp_offset}
emit('before_mp', bot.mp)
emit('before_max_mp', bot.max_mp)
emit('mp_ok', sd.debug.write_float(mp_address, {current_mp}))
emit('max_mp_ok', sd.debug.write_float(max_mp_address, {max_mp}))
emit('raw_after_mp', sd.debug.read_float(mp_address))
emit('raw_after_max_mp', sd.debug.read_float(max_mp_address))
local refreshed = sd.bots.get_state({bot_id}) or {{}}
emit('immediate_snapshot_after_mp', refreshed.mp)
emit('immediate_snapshot_after_max_mp', refreshed.max_mp)
emit('progression_runtime', progression)
emit('mp_offset', {mp_offset})
emit('max_mp_offset', {max_mp_offset})
emit('ok', refreshed.mp ~= nil and refreshed.max_mp ~= nil)
""".strip()
        )
    )


def query_bot_cast_state(bot_id: int) -> dict[str, str]:
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
  emit('available', false)
  return
end
emit('available', true)
for _, key in ipairs({{
  'id','actor_address','progression_runtime_state_address',
  'mp','max_mp','cast_pending','cast_active','cast_ready',
  'cast_startup_in_progress','cast_saw_activity','cast_skill_id',
  'cast_ticks_waiting','cast_target_actor_address'
}}) do
  emit(key, bot[key])
end
""".strip()
        )
    )


def lines_matching_bot(
    lines: list[str],
    bot_id: int,
    patterns: tuple[re.Pattern[str], ...] | list[re.Pattern[str]],
) -> list[str]:
    matches: list[str] = []
    for line in lines:
        for pattern in patterns:
            match = pattern.search(line)
            if match and int(match.group("bot_id")) == bot_id:
                matches.append(line)
                break
    return matches


def rejection_matches(lines: list[str], bot_id: int) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for line in lines:
        match = MANA_REJECTED_RE.search(line)
        if not match or int(match.group("bot_id")) != bot_id:
            continue
        matches.append(
            {
                "line": line,
                "bot_id": int(match.group("bot_id")),
                "skill_id": int(match.group("skill_id")),
                "mode": match.group("mode"),
            }
        )
    return matches


def bool_field(values: dict[str, str], key: str) -> bool:
    return str(values.get(key, "")).lower() == "true"


def float_field(values: dict[str, str], key: str) -> float:
    return csp.float_value(values, key)


def start_testrun_without_waves() -> dict[str, str]:
    scene = csp.query_scene_state()
    if csp.is_settled_scene(scene, "testrun"):
        return {"ok": "true", "already_in_testrun": "true"}
    values = csp.parse_key_values(csp.run_lua("print('ok='..tostring(sd.hub.start_testrun()))"))
    if values.get("ok") != "true":
        raise LiveBotOutOfManaProbeFailure(f"sd.hub.start_testrun failed: {values}")
    csp.wait_for_scene("testrun", timeout_s=45.0)
    return values


def wait_for_idle_cast_state(bot_id: int, timeout_s: float = 8.0) -> dict[str, str]:
    deadline = time.time() + timeout_s
    last: dict[str, str] = {}
    while time.time() < deadline:
        stop_bot(bot_id)
        last = query_bot_cast_state(bot_id)
        if (
            last.get("available") == "true"
            and not bool_field(last, "cast_pending")
            and not bool_field(last, "cast_active")
            and not bool_field(last, "cast_startup_in_progress")
            and not bool_field(last, "cast_saw_activity")
        ):
            return last
        time.sleep(0.2)
    raise LiveBotOutOfManaProbeFailure(f"bot did not settle to idle cast state: {last}")


def drive_to_idle_bot_for_rejection(
    element: str,
    discipline: str,
    bot_key: str,
    bot_element_id: int,
) -> dict[str, Any]:
    result: dict[str, Any] = {"navigation": []}
    result["launcher_freshness"] = csp.ensure_launcher_bundle_fresh()

    csp.stop_game()
    csp.clear_loader_log()
    with temporary_active_bots_config(bot_key):
        csp.launch_game()
        process_id = csp.wait_for_game_process()
        result["process_id"] = process_id
        csp.wait_for_lua_pipe()
        result["navigation"].append({"step": "launch", "process_id": process_id})

        csp.drive_new_game_flow(process_id, element=element, discipline=discipline)
        result["navigation"].append({"step": "hub_ready", "flow": {"mode": "new_game"}})
        result["testrun_start"] = start_testrun_without_waves()
        result["navigation"].append({"step": "testrun_started_without_waves"})
        time.sleep(3.0)

        bots = wait_for_materialized_bots(1, timeout_s=90.0)
        probe_bot = find_bot_for_element(bots, bot_element_id)
        result["bots_initial"] = [dict(bot) for bot in bots]
        result["bot_initial"] = dict(probe_bot)
        result["tick_gate"] = set_lua_bot_tick_enabled(False)
        result["idle_before_probe"] = wait_for_idle_cast_state(csp.int_value(probe_bot, "id"))
        result["bots_after_tick_gate"] = [dict(bot) for bot in list_bot_states()]
    return result


def run_probe(
    element: str,
    discipline: str,
    settle_seconds: float,
    bot_key: str,
    bot_element_id: int,
    current_mp: float,
    max_mp: float,
    allow_queued_rejection: bool,
) -> dict[str, Any]:
    result = drive_to_idle_bot_for_rejection(element, discipline, bot_key, bot_element_id)
    bot = dict(result["bot_initial"])
    bot_id = csp.int_value(bot, "id")
    bot_x = csp.float_value(bot, "x")
    bot_y = csp.float_value(bot, "y")
    if bot_id == 0 or bot_x != bot_x or bot_y != bot_y:
        raise LiveBotOutOfManaProbeFailure(f"materialized bot has invalid state: {bot}")

    result["stop_result"] = stop_bot(bot_id)
    result["idle_after_stop"] = wait_for_idle_cast_state(bot_id)
    result["mana_write"] = force_bot_mana(bot_id, current_mp, max_mp)
    if result["mana_write"].get("ok") != "true":
        raise LiveBotOutOfManaProbeFailure(f"failed to force bot mana: {result['mana_write']}")

    before = query_bot_cast_state(bot_id)
    if before.get("available") != "true":
        raise LiveBotOutOfManaProbeFailure(f"bot state unavailable before cast: {before}")

    start_line_count = len(read_loader_log_lines())
    result["queue_result"] = queue_default_primary(bot_id, bot_x + 160.0, bot_y)
    time.sleep(max(settle_seconds, 0.05))
    after = query_bot_cast_state(bot_id)
    log_lines = read_loader_log_lines()[start_line_count:]

    result["bot_id"] = bot_id
    result["bot_before"] = before
    result["bot_after"] = after
    result["mana_rejections"] = rejection_matches(log_lines, bot_id)
    result["queued_cast_lines"] = lines_matching_bot(log_lines, bot_id, [QUEUED_CAST_RE])
    result["mana_spent_lines"] = lines_matching_bot(log_lines, bot_id, [MANA_SPENT_RE])
    result["cast_lifecycle_lines"] = lines_matching_bot(log_lines, bot_id, LIFECYCLE_PATTERNS)
    result["new_loader_log_tail"] = log_lines[-80:]
    result["loader_log_tail"] = tail_loader_log()

    queue_rejected = result["queue_result"].get("ok") == "false"
    mana_rejected = bool(result["mana_rejections"])
    rejected_without_effects = queue_rejected or mana_rejected
    no_pending = not bool_field(after, "cast_pending")
    no_active = not bool_field(after, "cast_active")
    no_startup = not bool_field(after, "cast_startup_in_progress")
    no_activity = not bool_field(after, "cast_saw_activity")
    mp_not_spent = float_field(after, "mp") + 0.01 >= float_field(before, "mp")
    no_queue_insert = not result["queued_cast_lines"]
    no_mana_spend = not result["mana_spent_lines"]
    no_lifecycle = not result["cast_lifecycle_lines"]

    checks = {
        "cast_rejected_without_effects": rejected_without_effects,
        "sd_bots_cast_returned_false": queue_rejected or allow_queued_rejection,
        "mana_rejection_logged": mana_rejected,
        "no_pending_cast_after_rejection": no_pending,
        "no_active_cast_after_rejection": no_active,
        "no_startup_after_rejection": no_startup,
        "no_cast_activity_after_rejection": no_activity,
        "mp_not_spent": mp_not_spent,
        "no_pending_cast_insert_log": no_queue_insert or allow_queued_rejection,
        "no_native_mana_spend": no_mana_spend,
        "no_cast_lifecycle_or_effect_logs": no_lifecycle,
    }
    result["checks"] = checks
    result["passed"] = all(checks.values())
    if not result["passed"]:
        result["error"] = (
            "out-of-mana rejection validation failed: " +
            ", ".join(name for name, passed in checks.items() if not passed)
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--element", default="fire", choices=sorted(csp.CREATE_ELEMENT_CENTERS))
    parser.add_argument("--discipline", default="mind", choices=sorted(csp.CREATE_DISCIPLINE_CENTERS))
    parser.add_argument("--bot-key", default="fire")
    parser.add_argument("--bot-element-id", type=int, default=0)
    parser.add_argument("--current-mp", type=float, default=0.0)
    parser.add_argument("--max-mp", type=float, default=0.0)
    parser.add_argument(
        "--allow-queued-rejection",
        action="store_true",
        help="Allow QueueBotCast to accept the request when preparation must reject it before effects.",
    )
    parser.add_argument("--settle-seconds", type=float, default=0.6)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--json", action="store_true", help="Only print structured JSON.")
    parser.add_argument("--keep-running", action="store_true", help="Leave the game process running after the probe.")
    args = parser.parse_args()

    exit_code = 0
    try:
        result = run_probe(
            args.element,
            args.discipline,
            args.settle_seconds,
            args.bot_key,
            args.bot_element_id,
            args.current_mp,
            args.max_mp,
            args.allow_queued_rejection,
        )
        if not result.get("passed"):
            exit_code = 1
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
        print("PASS: live bot out-of-mana rejection")
        print(f"Wrote {args.output}")
    else:
        print(f"FAIL: live bot out-of-mana rejection: {result.get('error')}")
        print(f"Wrote {args.output}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
