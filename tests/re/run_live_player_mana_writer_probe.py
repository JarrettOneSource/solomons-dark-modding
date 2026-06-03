#!/usr/bin/env python3
"""Live RE probe for native player mana writes.

The manual bot mana drain is only safe to replace after the native player cast
path is understood. This probe launches the staged game, enters a testrun,
forces the local player's MP before arming any watch, then performs a native
player click-cast while watching the progression MP field. The captured EIP/ret
values are the evidence used for the next Ghidra pass.
"""

from __future__ import annotations

import argparse
import collections
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
import watch_player_cast_dispatch as player_watch  # noqa: E402


OUTPUT_PATH = ROOT / "runtime" / "live_player_mana_writer_probe.json"
RUNTIME_BINARY_LAYOUT_PATH = ROOT / "runtime/stage/.sdmod/config/binary-layout.ini"
WATCH_NAME = "player_native_progression_mp"


class LivePlayerManaWriterFailure(RuntimeError):
    pass


def read_runtime_layout_offset(name: str) -> int:
    text = RUNTIME_BINARY_LAYOUT_PATH.read_text(encoding="utf-8", errors="replace")
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", ";")) or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == name:
            return int(value.strip(), 0)
    raise LivePlayerManaWriterFailure(f"Unable to find {name!r} in {RUNTIME_BINARY_LAYOUT_PATH}")


def query_player_runtime() -> dict[str, str]:
    player = player_watch.query_player_runtime()
    if player.get("available") != "true":
        raise LivePlayerManaWriterFailure(f"player runtime unavailable: {player}")
    return player


def force_player_mana(progression_address: int, current: float, maximum: float) -> dict[str, str]:
    mp_offset = read_runtime_layout_offset("progression_mp")
    max_mp_offset = read_runtime_layout_offset("progression_max_mp")
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
local progression = {progression_address}
emit('before_mp', sd.debug.read_float(progression + {mp_offset}))
emit('before_max_mp', sd.debug.read_float(progression + {max_mp_offset}))
emit('mp_ok', sd.debug.write_float(progression + {mp_offset}, {current}))
emit('max_mp_ok', sd.debug.write_float(progression + {max_mp_offset}, {maximum}))
emit('after_mp', sd.debug.read_float(progression + {mp_offset}))
emit('after_max_mp', sd.debug.read_float(progression + {max_mp_offset}))
emit('ok', true)
""".strip()
        )
    )


def query_progression_mana(progression_address: int) -> dict[str, str]:
    mp_offset = read_runtime_layout_offset("progression_mp")
    max_mp_offset = read_runtime_layout_offset("progression_max_mp")
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local progression = {progression_address}
print('mp=' .. tostring(sd.debug.read_float(progression + {mp_offset})))
print('max_mp=' .. tostring(sd.debug.read_float(progression + {max_mp_offset})))
""".strip()
        )
    )


def arm_player_mana_watch(progression_address: int) -> dict[str, str]:
    mp_offset = read_runtime_layout_offset("progression_mp")
    watch_address = progression_address + mp_offset
    return csp.parse_key_values(
        csp.run_lua(
            f"""
pcall(sd.debug.unwatch, {json.dumps(WATCH_NAME)})
sd.debug.clear_write_hits({json.dumps(WATCH_NAME)})
print('watch_ok=' .. tostring(sd.debug.watch_write({json.dumps(WATCH_NAME)}, {watch_address}, 4)))
print('watch_address={watch_address}')
print('progression_address={progression_address}')
print('mp_offset={mp_offset}')
""".strip()
        )
    )


def query_write_hits() -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local hits = sd.debug.get_write_hits({json.dumps(WATCH_NAME)}) or {{}}
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
emit('count', #hits)
for i = 1, math.min(#hits, 256) do
  local hit = hits[i]
  for _, key in ipairs({{
    'requested_address','resolved_address','base_address','value_address',
    'access_address','thread_id','eip','esp','ebp','eax','ecx','edx',
    'ret','arg0','arg1','arg2','before_bytes_hex','after_bytes_hex'
  }}) do
    emit('hit.' .. i .. '.' .. key, hit[key])
  end
end
""".strip()
        )
    )


def parse_hex_float(value: str | None) -> float:
    if not value:
        return math.nan
    try:
        raw = bytes(int(part, 16) for part in value.split())
        if len(raw) != 4:
            return math.nan
        return struct.unpack("<f", raw)[0]
    except (TypeError, ValueError, struct.error):
        return math.nan


def summarize_write_hits(hits: dict[str, str]) -> dict[str, Any]:
    count = csp.int_value(hits, "count")
    by_eip: dict[int, dict[str, Any]] = collections.OrderedDict()
    decreasing_hits: list[dict[str, Any]] = []
    for index in range(1, count + 1):
        eip = csp.int_value(hits, f"hit.{index}.eip")
        if eip == 0:
            continue
        before = parse_hex_float(hits.get(f"hit.{index}.before_bytes_hex"))
        after = parse_hex_float(hits.get(f"hit.{index}.after_bytes_hex"))
        delta = after - before if math.isfinite(before) and math.isfinite(after) else math.nan
        row = by_eip.setdefault(
            eip,
            {
                "eip": f"0x{eip:X}",
                "count": 0,
                "decrease_count": 0,
                "increase_count": 0,
                "same_count": 0,
                "first_hit_index": index,
                "first_before": before,
                "first_after": after,
                "ret": f"0x{csp.int_value(hits, f'hit.{index}.ret'):X}",
                "arg0": f"0x{csp.int_value(hits, f'hit.{index}.arg0'):X}",
            },
        )
        row["count"] += 1
        if math.isfinite(delta):
            if delta < -0.001:
                row["decrease_count"] += 1
                if len(decreasing_hits) < 16:
                    decreasing_hits.append(
                        {
                            "index": index,
                            "eip": f"0x{eip:X}",
                            "ret": f"0x{csp.int_value(hits, f'hit.{index}.ret'):X}",
                            "arg0": f"0x{csp.int_value(hits, f'hit.{index}.arg0'):X}",
                            "before": before,
                            "after": after,
                            "delta": delta,
                        }
                    )
            elif delta > 0.001:
                row["increase_count"] += 1
            else:
                row["same_count"] += 1
    return {
        "stored_hit_count": count,
        "unique_writers": list(by_eip.values()),
        "decreasing_hits": decreasing_hits,
    }


def clear_player_mana_watch() -> None:
    csp.run_lua(
        f"""
pcall(sd.debug.unwatch, {json.dumps(WATCH_NAME)})
sd.debug.clear_write_hits({json.dumps(WATCH_NAME)})
""".strip()
    )


def click_player_cast(
    *,
    delay_seconds: float,
    wait_seconds: float,
    click_x: float,
    click_y: float,
    click_count: int,
    click_interval: float,
) -> list[dict[str, str]]:
    if delay_seconds > 0:
        time.sleep(delay_seconds)
    clicks: list[dict[str, str]] = []
    for index in range(max(1, click_count)):
        click_result = player_watch.click_normalized(click_x, click_y)
        click_result["index"] = str(index + 1)
        clicks.append(click_result)
        if index + 1 < click_count and click_interval > 0:
            time.sleep(click_interval)
    if wait_seconds > 0:
        time.sleep(wait_seconds)
    return clicks


def drive_to_native_player_run(element: str, discipline: str) -> dict[str, Any]:
    result: dict[str, Any] = {"navigation": []}
    result["launcher_freshness"] = csp.ensure_launcher_bundle_fresh()

    csp.stop_game()
    csp.clear_loader_log()
    csp.launch_game()
    process_id = csp.wait_for_game_process()
    csp.wait_for_lua_pipe()
    result["process_id"] = process_id
    result["navigation"].append({"step": "launch", "process_id": process_id})

    result["lua_tick"] = player_watch.set_lua_tick_enabled(False)
    result["clear_bots"] = player_watch.clear_bots()
    hub_flow = csp.drive_hub_flow(
        process_id,
        element=element,
        discipline=discipline,
        prefer_resume=False,
    )
    result["navigation"].append({"step": "hub_ready", "flow": hub_flow})

    scene_before_testrun = csp.query_scene_state()
    if csp.is_settled_scene(scene_before_testrun, "testrun"):
        scene = scene_before_testrun
    else:
        testrun = csp.parse_key_values(csp.run_lua("print('ok='..tostring(sd.hub.start_testrun()))"))
        if testrun.get("ok") != "true":
            raise LivePlayerManaWriterFailure(f"sd.hub.start_testrun failed: {testrun}")
        scene = csp.wait_for_scene("testrun", timeout_s=45.0)
    result["navigation"].append({"step": "testrun", "scene": scene})

    combat = csp.parse_key_values(csp.run_lua("print('ok='..tostring(sd.gameplay.enable_combat_prelude()))"))
    if combat.get("ok") != "true":
        raise LivePlayerManaWriterFailure(f"sd.gameplay.enable_combat_prelude failed: {combat}")
    result["navigation"].append({"step": "combat_prelude_enabled"})
    csp.boost_player_survival()
    return result


def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    result = drive_to_native_player_run(args.element, args.discipline)
    player_before = query_player_runtime()
    progression_address = csp.int_value(player_before, "progression_address")
    progression_handle_address = csp.int_value(player_before, "progression_handle_address")
    actor_address = csp.int_value(player_before, "actor_address")
    if actor_address == 0 or progression_address == 0:
        raise LivePlayerManaWriterFailure(f"player has invalid runtime pointers: {player_before}")

    force_result = force_player_mana(progression_address, args.starting_mp, args.starting_max_mp)
    if force_result.get("mp_ok") != "true" or force_result.get("max_mp_ok") != "true":
        raise LivePlayerManaWriterFailure(f"failed to force player mana: {force_result}")

    player_after_force = query_player_runtime()
    mana_before_cast = query_progression_mana(progression_address)
    watch = arm_player_mana_watch(progression_address)
    if watch.get("watch_ok") != "true":
        raise LivePlayerManaWriterFailure(f"failed to arm player mana watch: {watch}")

    try:
        spell_window_before = player_watch.query_spell_window(actor_address, progression_address)
        clicks = click_player_cast(
            delay_seconds=args.auto_click_delay,
            wait_seconds=args.wait_seconds,
            click_x=args.click_normalized_x,
            click_y=args.click_normalized_y,
            click_count=args.auto_click_count,
            click_interval=args.auto_click_interval,
        )
        spell_window_after = player_watch.query_spell_window(actor_address, progression_address)
        mana_after_cast = query_progression_mana(progression_address)
        hits = query_write_hits()
        hit_summary = summarize_write_hits(hits)
    finally:
        clear_player_mana_watch()

    before_mp = csp.float_value(mana_before_cast, "mp")
    after_mp = csp.float_value(mana_after_cast, "mp")
    hit_count = csp.int_value(hits, "count")
    if hit_count <= 0:
        raise LivePlayerManaWriterFailure(
            f"native player cast produced no progression MP write hits; before={mana_before_cast} after={mana_after_cast}"
        )
    if not hit_summary["decreasing_hits"]:
        raise LivePlayerManaWriterFailure(
            f"native player cast produced MP write hits but none decreased MP; before={mana_before_cast} after={mana_after_cast}"
        )
    if math.isfinite(before_mp) and math.isfinite(after_mp) and after_mp >= before_mp - 0.001:
        raise LivePlayerManaWriterFailure(
            f"progression MP did not decrease during native player cast; before={before_mp} after={after_mp}"
        )

    result.update(
        {
            "player_before": player_before,
            "progression_handle_address": progression_handle_address,
            "force_player_mana": force_result,
            "player_after_force": player_after_force,
            "mana_before_cast": mana_before_cast,
            "watch": watch,
            "auto_click_results": clicks,
            "spell_window_before": spell_window_before,
            "spell_window_after": spell_window_after,
            "mana_after_cast": mana_after_cast,
            "write_hits": hits,
            "write_hit_summary": hit_summary,
            "loader_log_tail": csp.tail_loader_log(220),
        }
    )
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--element", default="fire", choices=sorted(csp.CREATE_ELEMENT_CENTERS))
    parser.add_argument("--discipline", default="mind", choices=sorted(csp.CREATE_DISCIPLINE_CENTERS))
    parser.add_argument("--starting-mp", type=float, default=250.0)
    parser.add_argument("--starting-max-mp", type=float, default=250.0)
    parser.add_argument("--auto-click-delay", type=float, default=1.0)
    parser.add_argument("--auto-click-interval", type=float, default=0.35)
    parser.add_argument("--auto-click-count", type=int, default=1)
    parser.add_argument("--click-normalized-x", type=float, default=0.5)
    parser.add_argument("--click-normalized-y", type=float, default=0.5)
    parser.add_argument("--wait-seconds", type=float, default=3.0)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--keep-running", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    exit_code = 0
    result: dict[str, Any] = {}
    try:
        result = run_probe(args)
        result["passed"] = True
    except Exception as exc:  # noqa: BLE001 - probe preserves diagnostics in JSON.
        result["passed"] = False
        result["error"] = str(exc)
        result["loader_log_tail"] = csp.tail_loader_log(220)
        exit_code = 1
    finally:
        if not args.keep_running:
            csp.stop_game()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    elif result.get("passed"):
        hits = result.get("write_hits", {})
        print(f"PASS: live player mana writer probe captured {hits.get('count')} native MP write hit(s)")
        print(f"Wrote {args.output}")
    else:
        print(f"FAIL: live player mana writer probe: {result.get('error')}")
        print(f"Wrote {args.output}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
