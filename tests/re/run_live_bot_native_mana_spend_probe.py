#!/usr/bin/env python3
"""Live RE probe for bot mana spending through the native player delta seam."""

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
    drive_to_materialized_bot,
    force_bot_mana,
    queue_skill,
    read_runtime_layout_offset,
    tail_loader_log,
)


OUTPUT_PATH = ROOT / "runtime" / "live_bot_native_mana_spend_probe.json"
EARTH_PRIMARY_SKILL_ID = 0x3F6
FORCED_MANA = 250.0
RESTORE_FIELD_NAMES = (
    "gameplay_player_actor",
    "gameplay_player_progression_handle",
    "bot_actor_slot",
    "bot_actor_progression_handle",
)

MANA_SPENT_NATIVE_RE = re.compile(
    r"mana spent\. bot_id=(?P<bot_id>\d+) skill_id=(?P<skill_id>-?\d+) "
    r"mode=(?P<mode>[a-z_]+) progression_level=(?P<level>\d+) "
    r"(?:rate=(?P<rate>[0-9.+\-eE]+) )?"
    r".*?cost=(?P<cost>[0-9.+\-eE]+) "
    r"before=(?P<before>[0-9.+\-eE]+) after=(?P<after>[0-9.+\-eE]+) "
    r"native=1 native_result=(?P<native_result>\d+) "
    r"seh=(?P<seh>0x[0-9A-Fa-f]+) total=(?P<total>[0-9.+\-eE]+)"
)

MANA_FAILURE_RE = re.compile(
    r"(?:mana rejected|mana depleted)\. bot_id=(?P<bot_id>\d+) "
    r"skill_id=(?P<skill_id>-?\d+) .*"
)


class LiveNativeManaSpendProbeFailure(RuntimeError):
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


def capture_shim_fields(bot_id: int) -> dict[str, str]:
    gameplay_player_actor_offset = read_runtime_layout_offset("gameplay_player_actor")
    gameplay_player_progression_handle_offset = read_runtime_layout_offset(
        "gameplay_player_progression_handle"
    )
    actor_slot_offset = read_runtime_layout_offset("actor_slot")
    actor_progression_handle_offset = read_runtime_layout_offset("actor_progression_handle")
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
local function parse_address(value)
  if type(value) == 'number' then
    return value
  end
  if type(value) ~= 'string' then
    return 0
  end
  local hex = value:match('^0x(.+)$')
  if hex then
    return tonumber(hex, 16) or 0
  end
  return tonumber(value) or 0
end
local scene = sd.world and sd.world.get_scene and sd.world.get_scene()
local gameplay = type(scene) == 'table' and parse_address(scene.scene_id or scene.id) or 0
local bot = sd.bots.get_state({bot_id})
if gameplay == 0 or type(bot) ~= 'table' then
  emit('available', false)
  return
end
local actor = tonumber(bot.actor_address) or 0
emit('available', true)
emit('gameplay', gameplay)
emit('bot_actor', actor)
emit('gameplay_player_actor', sd.debug.read_ptr(gameplay + {gameplay_player_actor_offset}))
emit('gameplay_player_progression_handle', sd.debug.read_ptr(gameplay + {gameplay_player_progression_handle_offset}))
emit('bot_actor_slot', actor ~= 0 and sd.debug.read_u8(actor + {actor_slot_offset}) or nil)
emit('bot_actor_progression_handle', actor ~= 0 and sd.debug.read_ptr(actor + {actor_progression_handle_offset}) or nil)
""".strip()
        )
    )


def assert_shim_fields_restored(before: dict[str, str], after: dict[str, str], label: str) -> None:
    if before.get("available") != "true" or after.get("available") != "true":
        raise LiveNativeManaSpendProbeFailure(
            f"unable to capture shim restore fields for {label}: before={before} after={after}"
        )
    mismatches = [
        f"{name}: before={before.get(name)} after={after.get(name)}"
        for name in RESTORE_FIELD_NAMES
        if before.get(name) != after.get(name)
    ]
    if mismatches:
        raise LiveNativeManaSpendProbeFailure(
            f"native mana shim did not restore fields for {label}: " + "; ".join(mismatches)
        )


def parse_native_mana_spend(match: re.Match[str], line: str) -> dict[str, Any]:
    return {
        "line": line,
        "bot_id": int(match.group("bot_id")),
        "skill_id": int(match.group("skill_id")),
        "mode": match.group("mode"),
        "rate": float(match.group("rate")) if match.group("rate") else None,
        "cost": float(match.group("cost")),
        "before": float(match.group("before")),
        "after": float(match.group("after")),
        "native_result": int(match.group("native_result")),
        "seh": match.group("seh"),
        "total": float(match.group("total")),
    }


def wait_for_native_mana_spend(
    bot_id: int,
    skill_id: int,
    expected_mode: str,
    start_line_count: int,
    timeout_s: float,
) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    last_tail: list[str] = []
    while time.time() < deadline:
        lines = read_loader_log_lines()
        last_tail = lines[-160:]
        for line in lines[start_line_count:]:
            failure = MANA_FAILURE_RE.search(line)
            if failure and int(failure.group("bot_id")) == bot_id and int(failure.group("skill_id")) == skill_id:
                raise LiveNativeManaSpendProbeFailure(f"native mana spend failed: {line}")

            spent = MANA_SPENT_NATIVE_RE.search(line)
            if not spent:
                continue
            if int(spent.group("bot_id")) != bot_id or int(spent.group("skill_id")) != skill_id:
                continue

            result = parse_native_mana_spend(spent, line)
            if result["mode"] != expected_mode:
                raise LiveNativeManaSpendProbeFailure(
                    f"native mana spend used unexpected mode for skill {skill_id}: {line}"
                )
            if result["seh"].lower() != "0x0":
                raise LiveNativeManaSpendProbeFailure(f"native mana spend raised SEH: {line}")
            if result["cost"] <= 0.0:
                raise LiveNativeManaSpendProbeFailure(f"native mana spend cost was not positive: {line}")
            if result["before"] <= result["after"]:
                raise LiveNativeManaSpendProbeFailure(f"native mana spend did not reduce MP: {line}")
            if result["before"] - result["after"] + 0.01 < result["cost"]:
                raise LiveNativeManaSpendProbeFailure(f"native mana spend delta is smaller than cost: {line}")
            if expected_mode == "per_second":
                rate = result.get("rate")
                if rate is None:
                    raise LiveNativeManaSpendProbeFailure(f"per-second spend did not log a rate: {line}")
                if not (11.5 <= rate <= 12.5):
                    raise LiveNativeManaSpendProbeFailure(
                        f"Earth per-second spend is not using the unscaled native mManaCost rate: {line}"
                    )
            return result
        time.sleep(0.25)

    raise LiveNativeManaSpendProbeFailure(
        "timed out waiting for native mana spend; "
        f"tail={json.dumps(last_tail[-20:], indent=2)}"
    )


def force_queue_and_wait_for_spend(
    bot_id: int,
    skill_id: int,
    expected_mode: str,
    target_x: float,
    target_y: float,
    timeout_s: float,
) -> dict[str, Any]:
    stop_result = stop_bot(bot_id)
    mana_write = force_bot_mana(bot_id, FORCED_MANA, FORCED_MANA)
    if mana_write.get("ok") != "true":
        raise LiveNativeManaSpendProbeFailure(f"failed to force bot mana for {skill_id}: {mana_write}")

    before_fields = capture_shim_fields(bot_id)
    start_line_count = len(read_loader_log_lines())
    cast_result = queue_skill(bot_id, skill_id, target_x, target_y)
    if cast_result.get("ok") != "true":
        raise LiveNativeManaSpendProbeFailure(f"sd.bots.cast rejected skill {skill_id}: {cast_result}")

    spend = wait_for_native_mana_spend(
        bot_id,
        skill_id,
        expected_mode,
        start_line_count,
        timeout_s,
    )
    after_fields = capture_shim_fields(bot_id)
    assert_shim_fields_restored(before_fields, after_fields, str(skill_id))
    return {
        "stop_result": stop_result,
        "mana_write": mana_write,
        "cast_result": cast_result,
        "shim_fields_before": before_fields,
        "shim_fields_after": after_fields,
        "native_mana_spend": spend,
    }


def run_probe(element: str, discipline: str, timeout_s: float) -> dict[str, Any]:
    result = drive_to_materialized_bot(element, discipline)
    bot = dict(result["bot_initial"])
    bot_id = csp.int_value(bot, "id")
    bot_x = csp.float_value(bot, "x")
    bot_y = csp.float_value(bot, "y")
    if bot_id == 0 or bot_x != bot_x or bot_y != bot_y:
        raise LiveNativeManaSpendProbeFailure(f"materialized bot has invalid state: {bot}")

    target_x = bot_x + 160.0
    target_y = bot_y
    result["per_second"] = force_queue_and_wait_for_spend(
        bot_id,
        EARTH_PRIMARY_SKILL_ID,
        "per_second",
        target_x,
        target_y,
        timeout_s,
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
        per_second = result["per_second"]["native_mana_spend"]
        print(
            "PASS: live bot native mana spend "
            f"per_second={per_second['before']:.3f}->{per_second['after']:.3f}"
        )
        print(f"Wrote {args.output}")
    else:
        print(f"FAIL: live bot native mana spend probe: {result.get('error')}")
        print(f"Wrote {args.output}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
