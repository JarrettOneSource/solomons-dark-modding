#!/usr/bin/env python3
"""Live RE probe for PlayerActor stock-tick position restore.

Standalone clone bots still run through stock PlayerActorTick, but their final
position is loader-owned until a native per-bot ownership handoff is recovered.
This probe arms low-impact live watches on the actor position fields, drives a
standalone bot, and then observes the actor at rest. It deliberately avoids the
page-guard write-watch path because actor position shares a hot object page with
the fields read by PlayerActorTick. If stock tick drift is logged, the
stationary samples must stay clustered around the restored position; if no
drift is logged, the same clustering check records the current non-drifting
baseline.
"""

from __future__ import annotations

import argparse
import json
import math
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


OUTPUT_PATH = ROOT / "runtime" / "live_stock_tick_restore_probe.json"
RUNTIME_BINARY_LAYOUT_PATH = ROOT / "runtime/stage/.sdmod/config/binary-layout.ini"
WATCH_X = "stock_tick_restore_actor_x"
WATCH_Y = "stock_tick_restore_actor_y"
BOT_NAME = "Stock Tick Restore Probe"

DRIFT_RE = re.compile(
    r"standalone stock tick rewrote actor position\. actor=(0x[0-9a-fA-F]+) "
    r"before=\(([-+0-9.eE]+), ([-+0-9.eE]+)\) "
    r"stock_after=\(([-+0-9.eE]+), ([-+0-9.eE]+)\) moving=([01])"
)

BAD_LOG_TOKENS = (
    "PlayerActor_MoveStep threw",
    "native tick movement step failed",
    "standalone stock-tick restore probe failed",
    "registered_gamenpc movement failed",
    "registered_gamenpc movement list anomaly",
)


class LiveStockTickRestoreFailure(RuntimeError):
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
    raise LiveStockTickRestoreFailure(f"Unable to find {name!r} in {RUNTIME_BINARY_LAYOUT_PATH}")


def create_shared_hub_bot() -> int:
    output = csp.run_lua(
        f"""
local function emit(key, value)
  if value == nil then
    print(key .. '=')
  else
    print(key .. '=' .. tostring(value))
  end
end
if type(sd.bots.clear) == 'function' then
  sd.bots.clear()
end
local player = sd.player.get_state()
if type(player) ~= 'table' then
  emit('ok', false)
  emit('error', 'missing_player')
  return
end
local id = sd.bots.create({{
  name = {json.dumps(BOT_NAME)},
  profile = {{
    element_id = 1,
    discipline_id = 1,
    level = 1,
    experience = 0,
  }},
  scene = {{ kind = 'shared_hub' }},
  ready = true,
  heading = 270.0,
  position = {{
    x = (tonumber(player.x) or 0.0) + 112.0,
    y = tonumber(player.y) or 0.0,
  }},
}})
emit('ok', id ~= nil)
emit('bot_id', id)
""".strip()
    )
    values = csp.parse_key_values(output)
    if values.get("ok") != "true":
        raise LiveStockTickRestoreFailure(f"sd.bots.create failed: {values}")
    bot_id = csp.int_value(values, "bot_id")
    if bot_id == 0:
        raise LiveStockTickRestoreFailure(f"sd.bots.create returned invalid id: {values}")
    return bot_id


def query_bot_by_id(bot_id: int) -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local function emit(key, value)
  if value == nil then
    print(key .. '=')
  else
    print(key .. '=' .. tostring(value))
  end
end

local bot = sd.bots.get_state({bot_id})
if type(bot) ~= 'table' then
  local bots = sd.bots.get_state()
  if type(bots) == 'table' then
    for _, candidate in ipairs(bots) do
      if type(candidate) == 'table' and tonumber(candidate.id) == {bot_id} then
        bot = candidate
        break
      end
    end
  end
end

if type(bot) ~= 'table' then
  emit('available', false)
  return
end

emit('available', true)
for _, key in ipairs({{
  'id', 'name', 'actor_address', 'world_address', 'entity_materialized',
  'participant_kind', 'controller_kind', 'gameplay_slot', 'actor_slot',
  'progression_runtime_state_address', 'progression_handle_address',
  'equip_runtime_state_address', 'equip_handle_address',
  'x', 'y', 'state'
}}) do
  emit(key, bot[key])
end
emit('scene_kind', type(bot.scene) == 'table' and bot.scene.kind or nil)
""".strip()
        )
    )


def wait_for_bot(bot_id: int, *, timeout_s: float = 60.0) -> dict[str, str]:
    deadline = time.time() + timeout_s
    last: dict[str, str] = {}
    stable_actor = 0
    stable_count = 0
    while time.time() < deadline:
        last = query_bot_by_id(bot_id)
        actor_address = csp.int_value(last, "actor_address")
        has_runtime_state = (
            csp.int_value(last, "progression_runtime_state_address") != 0 or
            csp.int_value(last, "progression_handle_address") != 0 or
            csp.int_value(last, "equip_runtime_state_address") != 0 or
            csp.int_value(last, "equip_handle_address") != 0
        )
        if (
            last.get("available") == "true" and
            last.get("entity_materialized") == "true" and
            actor_address != 0 and
            csp.int_value(last, "gameplay_slot") == -1 and
            has_runtime_state
        ):
            if actor_address == stable_actor:
                stable_count += 1
            else:
                stable_actor = actor_address
                stable_count = 1
            if stable_count >= 4:
                return last
        else:
            stable_actor = 0
            stable_count = 0
        time.sleep(0.25)
    raise LiveStockTickRestoreFailure(f"timed out waiting for bot materialization. Last={last}")


def arm_position_watches(actor_address: int) -> dict[str, str]:
    x_offset = read_runtime_layout_offset("actor_position_x")
    y_offset = read_runtime_layout_offset("actor_position_y")
    tick_address = read_runtime_layout_offset("player_actor_tick")
    move_address = read_runtime_layout_offset("player_actor_move_step")
    x_address = actor_address + x_offset
    y_address = actor_address + y_offset
    return csp.parse_key_values(
        csp.run_lua(
            f"""
pcall(sd.debug.unwatch, {json.dumps(WATCH_X)})
pcall(sd.debug.unwatch, {json.dumps(WATCH_Y)})
sd.debug.clear_write_hits({json.dumps(WATCH_X)})
sd.debug.clear_write_hits({json.dumps(WATCH_Y)})
local tick = sd.debug.query_memory({tick_address})
local move = sd.debug.query_memory({move_address})
local function emit(key, value)
  if value == nil then
    print(key .. '=')
  else
    print(key .. '=' .. tostring(value))
  end
end
emit('actor_address', {actor_address})
emit('x_address', {x_address})
emit('y_address', {y_address})
emit('x_offset', {x_offset})
emit('y_offset', {y_offset})
emit('player_actor_tick_layout', {tick_address})
emit('player_actor_move_step_layout', {move_address})
emit('player_actor_tick_resolved', tick and tick.resolved_address or 0)
emit('player_actor_tick_region_base', tick and tick.base or 0)
emit('player_actor_move_step_resolved', move and move.resolved_address or 0)
emit('player_actor_move_step_region_base', move and move.base or 0)
sd.debug.watch({json.dumps(WATCH_X)}, {x_address}, 4)
sd.debug.watch({json.dumps(WATCH_Y)}, {y_address}, 4)
emit('watch_x_ok', true)
emit('watch_y_ok', true)
""".strip()
        )
    )


def clear_position_watches() -> None:
    csp.run_lua(
        f"""
pcall(sd.debug.unwatch, {json.dumps(WATCH_X)})
pcall(sd.debug.unwatch, {json.dumps(WATCH_Y)})
sd.debug.clear_write_hits({json.dumps(WATCH_X)})
sd.debug.clear_write_hits({json.dumps(WATCH_Y)})
""".strip()
    )


def issue_move_and_observe(bot_id: int, bot: dict[str, str]) -> dict[str, Any]:
    bot_x = csp.float_value(bot, "x")
    bot_y = csp.float_value(bot, "y")
    if math.isnan(bot_x) or math.isnan(bot_y):
        raise LiveStockTickRestoreFailure(f"bot has invalid position: {bot}")

    target_x = bot_x - 180.0
    target_y = bot_y
    initial_gap = math.sqrt((target_x - bot_x) * (target_x - bot_x) + (target_y - bot_y) * (target_y - bot_y))
    move_result = csp.parse_key_values(
        csp.run_lua(f"print('ok=' .. tostring(sd.bots.move_to({bot_id}, {target_x}, {target_y})))")
    )
    if move_result.get("ok") != "true":
        raise LiveStockTickRestoreFailure(f"sd.bots.move_to failed: {move_result}")

    samples: list[dict[str, str]] = []
    improved = False
    for _ in range(40):
        time.sleep(0.25)
        sample = query_bot_by_id(bot_id)
        samples.append(sample)
        gap = distance_to(sample, target_x, target_y)
        if not math.isnan(gap) and gap < initial_gap - 8.0:
            improved = True
            break

    if not improved:
        final_gap = distance_to(samples[-1], target_x, target_y) if samples else math.nan
        raise LiveStockTickRestoreFailure(
            f"standalone bot did not advance after stock restore: "
            f"initial_gap={initial_gap:.3f} final_gap={final_gap:.3f} samples={samples[-3:]}"
        )
    csp.run_lua(f"print('ok=' .. tostring(sd.bots.stop({bot_id})))")
    return {
        "target": {"x": target_x, "y": target_y},
        "initial_gap": initial_gap,
        "samples": samples,
    }


def distance_to(sample: dict[str, str], target_x: float, target_y: float) -> float:
    x = csp.float_value(sample, "x")
    y = csp.float_value(sample, "y")
    if math.isnan(x) or math.isnan(y):
        return math.nan
    dx = target_x - x
    dy = target_y - y
    return math.sqrt(dx * dx + dy * dy)


def parse_stock_drift_events(log_tail: list[str], actor_address: int) -> list[dict[str, Any]]:
    actor_hex = f"0x{actor_address:X}".lower()
    events: list[dict[str, Any]] = []
    for line in log_tail:
        match = DRIFT_RE.search(line)
        if not match:
            continue
        if match.group(1).lower() != actor_hex:
            continue
        before_x = float(match.group(2))
        before_y = float(match.group(3))
        stock_after_x = float(match.group(4))
        stock_after_y = float(match.group(5))
        stock_dx = stock_after_x - before_x
        stock_dy = stock_after_y - before_y
        events.append(
            {
                "line": line,
                "before_x": before_x,
                "before_y": before_y,
                "stock_after_x": stock_after_x,
                "stock_after_y": stock_after_y,
                "stock_displacement": math.sqrt(stock_dx * stock_dx + stock_dy * stock_dy),
                "moving": match.group(6) == "1",
            }
        )
    return events


def summarize_stock_drift_events(drift_events: list[dict[str, Any]]) -> dict[str, Any]:
    significant = [event for event in drift_events if event["stock_displacement"] > 0.01]
    return {
        "count": len(drift_events),
        "significant_count": len(significant),
        "first_significant": significant[0] if significant else None,
    }


def validate_live_watch_log(log_tail: list[str]) -> dict[str, int]:
    x_initial = sum(1 for line in log_tail if f"WATCH: {WATCH_X} initial" in line)
    y_initial = sum(1 for line in log_tail if f"WATCH: {WATCH_Y} initial" in line)
    x_changed = sum(1 for line in log_tail if f"WATCH: {WATCH_X} changed" in line)
    y_changed = sum(1 for line in log_tail if f"WATCH: {WATCH_Y} changed" in line)
    if x_initial <= 0 or y_initial <= 0:
        raise LiveStockTickRestoreFailure(
            f"live position watches did not initialize: x_initial={x_initial} y_initial={y_initial}"
        )
    if x_changed <= 0 or y_changed <= 0:
        raise LiveStockTickRestoreFailure(
            f"live position watches did not observe movement: x_changed={x_changed} y_changed={y_changed}"
        )
    return {
        "x_initial": x_initial,
        "y_initial": y_initial,
        "x_changed": x_changed,
        "y_changed": y_changed,
    }


def sample_actor_position(actor_address: int) -> dict[str, str]:
    x_offset = read_runtime_layout_offset("actor_position_x")
    y_offset = read_runtime_layout_offset("actor_position_y")
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local actor = {actor_address}
print('x=' .. tostring(sd.debug.read_float(actor + {x_offset})))
print('y=' .. tostring(sd.debug.read_float(actor + {y_offset})))
""".strip()
        )
    )


def observe_stationary_actor(actor_address: int, *, duration_s: float = 2.0) -> dict[str, Any]:
    samples: list[dict[str, str]] = []
    deadline = time.time() + duration_s
    while time.time() < deadline:
        samples.append(sample_actor_position(actor_address))
        time.sleep(0.25)
    if len(samples) < 3:
        raise LiveStockTickRestoreFailure(f"not enough stationary samples: {samples}")

    origin_x = csp.float_value(samples[0], "x")
    origin_y = csp.float_value(samples[0], "y")
    max_distance = 0.0
    for sample in samples:
        x = csp.float_value(sample, "x")
        y = csp.float_value(sample, "y")
        if math.isnan(x) or math.isnan(y) or math.isnan(origin_x) or math.isnan(origin_y):
            raise LiveStockTickRestoreFailure(f"stationary sample has invalid actor position: {sample}")
        dx = x - origin_x
        dy = y - origin_y
        max_distance = max(max_distance, math.sqrt(dx * dx + dy * dy))

    if max_distance > 0.25:
        raise LiveStockTickRestoreFailure(
            f"actor drifted while stopped after stock-tick restore window: max_distance={max_distance:.3f} "
            f"samples={samples}"
        )
    return {
        "samples": samples,
        "max_distance": max_distance,
    }


def validate_loader_log(log_tail: list[str], actor_address: int) -> None:
    joined = "\n".join(log_tail)
    present = [token for token in BAD_LOG_TOKENS if token in joined]
    if present:
        raise LiveStockTickRestoreFailure("loader log contains failure token(s): " + ", ".join(present))
    actor_hex = f"0x{actor_address:X}"
    if f"tracked actor invalidated out-of-band. actor={actor_hex}" in joined:
        raise LiveStockTickRestoreFailure(f"watched bot actor was invalidated out of band: {actor_hex}")


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


def clear_lua_bots() -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            """
if sd.bots and sd.bots.clear then
  sd.bots.clear()
end
local count = sd.bots and sd.bots.get_count and sd.bots.get_count() or 0
print('ok=true')
print('count=' .. tostring(count))
""".strip()
        )
    )


def run_probe() -> dict[str, Any]:
    result: dict[str, Any] = {
        "launcher_freshness": csp.ensure_launcher_bundle_fresh(),
        "navigation": [],
    }
    csp.stop_game()
    csp.clear_loader_log()
    csp.launch_game()
    process_id = csp.wait_for_game_process()
    csp.wait_for_lua_pipe()
    result["process_id"] = process_id
    result["navigation"].append({"step": "launch", "process_id": process_id})
    result["lua_tick_disabled_initial"] = set_lua_bot_tick_enabled(False)
    result["clear_bots_initial"] = clear_lua_bots()

    hub_flow = csp.drive_hub_flow(process_id, element="fire", discipline="mind", prefer_resume=False)
    result["navigation"].append({"step": "hub_ready", "flow": hub_flow})
    result["lua_tick_disabled_hub"] = set_lua_bot_tick_enabled(False)
    result["clear_bots_hub"] = clear_lua_bots()

    bot_id = create_shared_hub_bot()
    time.sleep(1.0)
    bot_initial = wait_for_bot(bot_id)
    actor_address = csp.int_value(bot_initial, "actor_address")
    if actor_address == 0:
        raise LiveStockTickRestoreFailure(f"bot has invalid actor: {bot_initial}")
    if csp.int_value(bot_initial, "gameplay_slot") != -1:
        raise LiveStockTickRestoreFailure(f"expected standalone shared-hub bot with gameplay_slot=-1: {bot_initial}")
    result["bot_id"] = bot_id
    result["bot_initial"] = bot_initial

    watch = arm_position_watches(actor_address)
    if watch.get("watch_x_ok") != "true" or watch.get("watch_y_ok") != "true":
        raise LiveStockTickRestoreFailure(f"failed to arm position write watches: {watch}")

    try:
        result["watch"] = watch
        result["movement_observation"] = issue_move_and_observe(bot_id, bot_initial)
        result["stationary_observation"] = observe_stationary_actor(actor_address)
        result["bot_final"] = query_bot_by_id(bot_id)
    finally:
        clear_position_watches()

    log_tail = csp.tail_loader_log(500)
    validate_loader_log(log_tail, actor_address)
    drift_events = parse_stock_drift_events(log_tail, actor_address)
    stock_drift_evidence = summarize_stock_drift_events(drift_events)
    watch_evidence = validate_live_watch_log(log_tail)

    result["stock_drift_events"] = drift_events
    result["stock_drift_evidence"] = stock_drift_evidence
    result["watch_evidence"] = watch_evidence
    result["loader_log_tail"] = log_tail
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--json", action="store_true", help="Only print structured JSON.")
    parser.add_argument("--keep-running", action="store_true")
    args = parser.parse_args()

    exit_code = 0
    try:
        result = run_probe()
        result["passed"] = True
    except Exception as exc:  # noqa: BLE001 - probe preserves diagnostics in JSON.
        result = {
            "passed": False,
            "error": str(exc),
            "loader_log_tail": csp.tail_loader_log(320),
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
        print("PASS: live stock-tick restore probe validated standalone restore barrier")
        print(f"Wrote {args.output}")
    else:
        print(f"FAIL: live stock-tick restore probe: {result.get('error')}")
        print(f"Wrote {args.output}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
