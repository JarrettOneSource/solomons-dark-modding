#!/usr/bin/env python3
"""Drive a stable bot primary-cast scenario and capture diagnostics."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cast_state_probe as csp
from cast_trace_profiles import build_trace_specs, trace_profile_names
import probe_bot_close_range_combat as crc


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = ROOT / "runtime" / "probe_bot_primary_wave_cast.json"
DEFAULT_OBSERVE_SECONDS = 6.0
DEFAULT_PROMOTE_OFFSET_X = 80.0
DEFAULT_ENEMY_STANDOFF = 120.0
DEFAULT_MAX_HOSTILE_GAP = 220.0
DEFAULT_ELEMENT = "ether"
DEFAULT_DISCIPLINE = "mind"
CAST_SIGNAL_WAIT_SECONDS = 3.0
MOVE_INTO_RANGE_TIMEOUT_SECONDS = 15.0
MOVE_INTO_RANGE_POLL_SECONDS = 0.25
PROBE_HP_VALUE = 500.0
POST_TESTRUN_SETTLE_SECONDS = 4.0
POST_PROMOTION_SETTLE_SECONDS = 3.0
POST_WAVES_SETTLE_SECONDS = 2.0
DEFAULT_TRACE_PROFILE = "full"
SETUP_MODES = ("combat_prelude", "waves")


class WaveCastProbeFailure(RuntimeError):
    pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Launch a controlled run, promote the bot, and queue a direct primary cast."
    )
    parser.add_argument("--element", choices=sorted(csp.CREATE_ELEMENT_CENTERS), default=DEFAULT_ELEMENT)
    parser.add_argument("--discipline", choices=sorted(csp.CREATE_DISCIPLINE_CENTERS), default=DEFAULT_DISCIPLINE)
    parser.add_argument(
        "--setup-mode",
        choices=SETUP_MODES,
        default="combat_prelude",
        help="combat_prelude enables casting without waves; waves preserves the old wave-start scenario.",
    )
    parser.add_argument("--observe-seconds", type=float, default=DEFAULT_OBSERVE_SECONDS)
    parser.add_argument("--promote-offset-x", type=float, default=DEFAULT_PROMOTE_OFFSET_X)
    parser.add_argument("--enemy-standoff", type=float, default=DEFAULT_ENEMY_STANDOFF)
    parser.add_argument("--max-hostile-gap", type=float, default=DEFAULT_MAX_HOSTILE_GAP)
    parser.add_argument("--trace-builder-window", dest="trace_builder_window", action="store_true")
    parser.add_argument("--trace-post-builder", dest="trace_builder_window", action="store_true")
    parser.add_argument(
        "--trace-profile",
        default=DEFAULT_TRACE_PROFILE,
        choices=trace_profile_names(),
        help="Trace subset to arm when --trace-builder-window is set.",
    )
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--keep-running", action="store_true")
    return parser


def promote_bot_into_run_scene(player_x: float, player_y: float, offset_x: float) -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local bots = sd.bots.get_state()
local bot = type(bots) == 'table' and bots[1] or nil
if type(bot) ~= 'table' then
  print('ok=false')
  print('error=no_bot')
  return
end
local ok = sd.bots.update({{
  id = bot.id,
  scene = {{ kind = 'run' }},
  position = {{
    x = {player_x + offset_x},
    y = {player_y},
    heading = 25.0,
  }},
}})
print('ok=' .. tostring(ok))
print('id=' .. tostring(bot.id))
""".strip()
        )
    )


def arm_trace(name: str, address: int, patch_size: int) -> dict[str, str]:
    trace_call = (
        f"sd.debug.trace_function({address}, {json.dumps(name)})"
        if patch_size <= 0
        else f"sd.debug.trace_function({address}, {json.dumps(name)}, {patch_size})"
    )
    return csp.parse_key_values(
        csp.run_lua(
            f"""
pcall(sd.debug.untrace_function, {address})
sd.debug.clear_trace_hits({json.dumps(name)})
print('ok=' .. tostring({trace_call}))
print('error=' .. tostring(sd.debug.get_last_error and sd.debug.get_last_error() or ''))
""".strip()
        )
    )


def clear_trace(name: str, address: int) -> None:
    csp.run_lua(
        f"""
pcall(sd.debug.untrace_function, {address})
sd.debug.clear_trace_hits({json.dumps(name)})
""".strip()
    )


def query_trace_hits(name: str) -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local hits = sd.debug.get_trace_hits({json.dumps(name)}) or {{}}
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
emit('count', #hits)
for i = 1, math.min(#hits, 8) do
  local hit = hits[i]
  for _, key in ipairs({{
    'requested_address','resolved_address','thread_id','eax','ecx','edx','ebx',
    'esi','edi','ebp','esp_before_pushad','ret','arg0','arg1','arg2','arg3','arg4','arg5','arg6','arg7','arg8'
  }}) do
    emit('hit.' .. i .. '.' .. key, hit[key])
  end
end
""".strip()
        )
    )


def arm_trace_profile(profile: str) -> dict[str, dict[str, str]]:
    return {
        spec.name: arm_trace(spec.name, spec.address, spec.patch_size)
        for spec in build_trace_specs("bot_primary", profile)
    }


def clear_trace_profile(profile: str) -> None:
    for spec in build_trace_specs("bot_primary", profile):
        clear_trace(spec.name, spec.address)


def query_trace_profile_hits(profile: str) -> dict[str, dict[str, str]]:
    return {
        spec.name: query_trace_hits(spec.name)
        for spec in build_trace_specs("bot_primary", profile)
    }


def queue_move(bot_id: str, x: float, y: float) -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
print('ok=' .. tostring(sd.bots.move_to({bot_id}, {x}, {y})))
print('bot_id=' .. tostring({bot_id}))
print('x=' .. tostring({x}))
print('y=' .. tostring({y}))
""".strip()
        )
    )


def queue_transform_update(bot_id: str, x: float, y: float) -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
print('ok=' .. tostring(sd.bots.update({{
  id = {bot_id},
  scene = {{ kind = 'run' }},
  position = {{ x = {x}, y = {y} }},
  heading = 25.0,
}})))
print('bot_id=' .. tostring({bot_id}))
print('x=' .. tostring({x}))
print('y=' .. tostring({y}))
""".strip()
        )
    )


def enable_combat_prelude() -> dict[str, str]:
    values = csp.parse_key_values(csp.run_lua("print('ok='..tostring(sd.gameplay.enable_combat_prelude()))"))
    if values.get("ok") != "true":
        raise WaveCastProbeFailure(f"sd.gameplay.enable_combat_prelude failed: {values}")
    return values


def query_combat_state() -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            """
local state = sd.gameplay and sd.gameplay.get_combat_state and sd.gameplay.get_combat_state()
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
if type(state) ~= 'table' then
  emit('available', false)
  return
end
emit('available', true)
for _, key in ipairs({
  'arena_id','section_index','wave_index','wait_ticks','advance_mode',
  'advance_threshold','wave_counter','started_music','transition_requested','active'
}) do
  emit(key, state[key])
end
""".strip()
        )
    )


def wait_for_combat_prelude_ready(timeout_s: float = 8.0) -> dict[str, str]:
    deadline = time.time() + timeout_s
    last: dict[str, str] = {}
    while time.time() < deadline:
        last = query_combat_state()
        if last.get("available") == "true":
            wave_index = int(last.get("wave_index") or "0", 10)
            if wave_index > 0:
                raise WaveCastProbeFailure(f"Combat prelude advanced into waves: {last}")
            if last.get("active") == "true" and last.get("transition_requested") == "true":
                return last
        time.sleep(0.1)
    raise WaveCastProbeFailure(f"Timed out waiting for combat prelude state. Last={last}")


def sustain_probe_health(hp_value: float = PROBE_HP_VALUE) -> dict[str, str]:
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

local player = sd.player and sd.player.get_state and sd.player.get_state()
if type(player) == 'table' then
  local progression = tonumber(player.progression_address) or 0
  if progression ~= 0 then
    emit('player_progression', progression)
    emit('player_hp_ok', sd.debug.write_float(progression + {csp.PROGRESSION_HP_OFFSET}, {hp_value}))
    emit('player_max_hp_ok', sd.debug.write_float(progression + {csp.PROGRESSION_MAX_HP_OFFSET}, {hp_value}))
  end
end

local bots = sd.bots and sd.bots.get_state and sd.bots.get_state()
local bot = type(bots) == 'table' and bots[1] or nil
if type(bot) == 'table' then
  local progression = tonumber(bot.progression_runtime_state_address) or 0
  emit('bot_id', bot.id)
  emit('bot_progression', progression)
  if progression ~= 0 then
    emit('bot_hp_ok', sd.debug.write_float(progression + {csp.PROGRESSION_HP_OFFSET}, {hp_value}))
    emit('bot_max_hp_ok', sd.debug.write_float(progression + {csp.PROGRESSION_MAX_HP_OFFSET}, {hp_value}))
  end
end
""".strip()
        )
    )


def force_close_range_sample(
    standoff: float,
    max_gap: float,
) -> dict[str, object]:
    before = crc.query_combat_sample()
    if before.get("available") != "true" or before.get("hostile.available") != "true":
        return {"ok": False, "before": before, "error": "sample_unavailable"}

    before_gap = float(before["hostile.gap"])
    if before_gap <= max_gap:
        return {"ok": True, "forced": False, "before": before, "sample": before, "final_gap": before_gap}

    bot_actor = before.get("bot.actor_address", "0")
    hostile_actor = before.get("hostile.actor_address", "0")
    bot_x = float(before.get("bot.live_x") or before.get("bot.x") or 0.0)
    bot_y = float(before.get("bot.live_y") or before.get("bot.y") or 0.0)
    hostile_x = bot_x + standoff
    hostile_y = bot_y
    force_bot = crc.force_actor_position(bot_actor, bot_x, bot_y, heading=90.0)
    force_hostile = crc.force_actor_position(hostile_actor, hostile_x, hostile_y)
    time.sleep(MOVE_INTO_RANGE_POLL_SECONDS)
    sustain_probe_health()
    after = crc.query_combat_sample()
    after_gap = float(after["hostile.gap"]) if after.get("hostile.gap") else None
    return {
        "ok": after_gap is not None and after_gap <= max_gap,
        "forced": True,
        "before": before,
        "force_bot": force_bot,
        "force_hostile": force_hostile,
        "sample": after,
        "final_gap": after_gap,
    }


def force_player_target_sample(
    standoff: float,
    max_gap: float,
) -> dict[str, object]:
    bot = csp.query_bot_state()
    player = csp.query_player_state()
    bot_actor = bot.get("actor_address", "0")
    player_actor = player.get("actor_address", "0")
    player_x = csp.float_value(player, "x")
    player_y = csp.float_value(player, "y")
    bot_x = player_x - standoff
    bot_y = player_y
    force_bot = crc.force_actor_position(bot_actor, bot_x, bot_y, heading=90.0)
    time.sleep(MOVE_INTO_RANGE_POLL_SECONDS)
    sustain_probe_health()
    bot_after = csp.query_bot_state()
    player_after = csp.query_player_state()
    bx = float(force_bot.get("x") or csp.float_value(bot_after, "x"))
    by = float(force_bot.get("y") or csp.float_value(bot_after, "y"))
    px = csp.float_value(player_after, "x")
    py = csp.float_value(player_after, "y")
    gap = ((px - bx) ** 2 + (py - by) ** 2) ** 0.5
    sample = {
        "available": "true",
        "bot.id": bot_after.get("id", bot.get("id", "")),
        "bot.actor_address": bot_after.get("actor_address", bot_actor),
        "bot.live_x": str(bx),
        "bot.live_y": str(by),
        "hostile.available": "true",
        "hostile.object_type_id": "player",
        "hostile.actor_address": player_after.get("actor_address", player_actor),
        "hostile.x": str(px),
        "hostile.y": str(py),
        "hostile.gap": str(gap),
    }
    return {
        "ok": gap <= max_gap,
        "target_source": "player",
        "forced": True,
        "force_bot": force_bot,
        "sample": sample,
        "final_gap": gap,
    }


def query_actor_vitals(actor_address: str | int) -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local actor = tonumber({json.dumps(str(actor_address))}) or 0
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
emit('actor_address', actor)
if actor == 0 or not sd.debug or not sd.debug.read_ptr then
  emit('available', false)
  return
end
local progression = tonumber(sd.debug.read_ptr(actor + 0x200)) or 0
local handle = tonumber(sd.debug.read_ptr(actor + 0x300)) or 0
if progression == 0 and handle ~= 0 then
  progression = tonumber(sd.debug.read_ptr(handle)) or 0
end
emit('progression_runtime', progression)
emit('progression_handle', handle)
if progression == 0 or not sd.debug.read_float then
  emit('available', false)
  return
end
emit('available', true)
emit('hp', sd.debug.read_float(progression + {csp.PROGRESSION_HP_OFFSET}))
emit('max_hp', sd.debug.read_float(progression + {csp.PROGRESSION_MAX_HP_OFFSET}))
""".strip()
        )
    )


def move_bot_into_range(
    bot_id: str,
    hostile_x: float,
    hostile_y: float,
    standoff: float,
    max_gap: float,
) -> dict[str, object]:
    target_x = hostile_x - standoff
    target_y = hostile_y
    update = queue_transform_update(bot_id, target_x, target_y)
    time.sleep(MOVE_INTO_RANGE_POLL_SECONDS)
    sustain_probe_health()
    sample = crc.query_combat_sample()
    sample["sample_monotonic_ms"] = str(int(time.time() * 1000.0))
    samples: list[dict[str, str]] = [sample]
    if sample.get("available") == "true" and sample.get("hostile.available") == "true":
        gap = float(sample["hostile.gap"])
        if gap <= max_gap:
            return {
                "ok": True,
                "update": update,
                "move": None,
                "target_x": target_x,
                "target_y": target_y,
                "final_gap": gap,
                "sample": sample,
                "samples": samples,
            }

    move = queue_move(bot_id, target_x, target_y)
    deadline = time.time() + MOVE_INTO_RANGE_TIMEOUT_SECONDS
    while time.time() < deadline:
        sustain_probe_health()
        sample = crc.query_combat_sample()
        sample["sample_monotonic_ms"] = str(int(time.time() * 1000.0))
        samples.append(sample)
        if sample.get("available") == "true" and sample.get("hostile.available") == "true":
            gap = float(sample["hostile.gap"])
            if gap <= max_gap:
                return {
                    "ok": True,
                    "move": move,
                    "target_x": target_x,
                    "target_y": target_y,
                    "final_gap": gap,
                    "sample": sample,
                    "samples": samples,
                }
        time.sleep(MOVE_INTO_RANGE_POLL_SECONDS)

    last_sample = samples[-1] if samples else {}
    final_gap = float(last_sample["hostile.gap"]) if last_sample.get("hostile.gap") else None
    return {
        "ok": False,
        "update": update,
        "move": move,
        "target_x": target_x,
        "target_y": target_y,
        "final_gap": final_gap,
        "sample": last_sample,
        "samples": samples,
    }


def read_loader_log_text() -> str:
    if not csp.LOADER_LOG.exists():
        return ""
    return csp.LOADER_LOG.read_text(encoding="utf-8", errors="replace")


def derive_loader_signals(log_text: str) -> dict[str, bool]:
    return {
        "queued_cast_logged": "[bots] queued cast for bot id=" in log_text,
        "cast_prepped_logged": "[bots] gameplay-slot cast prepped." in log_text,
        "cast_complete_logged": "cast complete" in log_text,
        "run_ended_logged": "[lua.bots] run.ended" in log_text,
        "pure_primary_start_entered": "[bots] pure_primary_start enter" in log_text,
        "pure_primary_start_exited": "[bots] pure_primary_start exit" in log_text,
        "spell_dispatch_entered": "[bots] spell_dispatch enter" in log_text,
        "spell_dispatch_exited": "[bots] spell_dispatch exit" in log_text,
        "cast_prepare_failed": "[bots] gameplay-slot cast prepare failed." in log_text,
        "cast_post_tick_detail": "[bots] gameplay-slot cast post-tick detail." in log_text,
    }


def wait_for_cast_signals(timeout_s: float = CAST_SIGNAL_WAIT_SECONDS) -> dict[str, object]:
    deadline = time.time() + timeout_s
    state: dict[str, object] = derive_loader_signals("")
    while time.time() < deadline:
        log_text = read_loader_log_text()
        state.update(derive_loader_signals(log_text))
        if state["cast_prepped_logged"] or state["run_ended_logged"]:
            break
        time.sleep(0.1)
    state["loader_log_tail"] = csp.tail_loader_log()
    state["loader_log_filtered"] = crc.filter_loader_log(state["loader_log_tail"])
    return state


def main() -> int:
    args = build_parser().parse_args()
    result: dict[str, object] = {
        "launcher_freshness": csp.ensure_launcher_bundle_fresh(),
        "navigation": [],
        "trace_profile": args.trace_profile,
        "setup_mode": args.setup_mode,
    }

    try:
        csp.stop_game()
        csp.clear_loader_log()

        csp.launch_game()
        process_id = csp.wait_for_game_process()
        csp.wait_for_lua_pipe()
        result["process_id"] = process_id
        result["navigation"].append({"step": "launch", "process_id": process_id})

        hub_flow = csp.drive_hub_flow(
            process_id,
            element=args.element,
            discipline=args.discipline,
            prefer_resume=True,
        )
        result["navigation"].append(
            {
                "step": "hub_ready",
                "flow": hub_flow,
                "element": args.element,
                "discipline": args.discipline,
                "hub_lua_tick_gate": crc.set_lua_tick_enabled(False),
                "hub_bot_clear": crc.clear_bots(),
            }
        )

        scene_before_testrun = csp.query_scene_state()
        if csp.is_settled_scene(scene_before_testrun, "testrun"):
            values = {"ok": "true", "already_testrun": "true"}
        else:
            values = csp.parse_key_values(csp.run_lua("print('ok='..tostring(sd.hub.start_testrun()))"))
            if values.get("ok") != "true":
                raise WaveCastProbeFailure(f"sd.hub.start_testrun failed: {values}")
            csp.wait_for_scene("testrun", timeout_s=45.0)
        time.sleep(POST_TESTRUN_SETTLE_SECONDS)
        result["navigation"].append({"step": "testrun_started", "result": values})
        testrun_tick_gate = crc.set_lua_tick_enabled(True)
        spawned_bot = csp.wait_for_materialized_bot()
        result["navigation"].append({
            "step": "bot_spawned_in_testrun",
            "lua_tick_gate": testrun_tick_gate,
            "bot": spawned_bot,
        })

        player = csp.query_player_state()
        result["before"] = {
            "player": player,
            "scene": csp.query_scene_state(),
            "world": csp.query_world_state(),
            "selection": csp.query_selection_debug_state(),
        }

        promotion = promote_bot_into_run_scene(
            csp.float_value(player, "x"),
            csp.float_value(player, "y"),
            args.promote_offset_x,
        )
        if promotion.get("ok") != "true":
            raise WaveCastProbeFailure(f"Bot run-scene promotion failed: {promotion}")
        time.sleep(POST_PROMOTION_SETTLE_SECONDS)

        bot = csp.query_bot_state()
        if csp.int_value(bot, "actor_address") == 0:
            raise WaveCastProbeFailure(f"Bot did not materialize after promotion: {bot}")

        tick_gate = crc.set_lua_tick_enabled(False)
        stop_after_promotion = crc.stop_bot(bot["id"])
        result["post_promotion_control"] = {
            "lua_tick_gate": tick_gate,
            "stop": stop_after_promotion,
        }

        spawn: dict[str, str] = {}
        setup_result: dict[str, str]
        combat_state_after_setup: dict[str, str] = {}
        if args.setup_mode == "waves":
            setup_result = csp.parse_key_values(csp.run_lua("print('ok='..tostring(sd.gameplay.start_waves()))"))
            if setup_result.get("ok") != "true":
                raise WaveCastProbeFailure(f"sd.gameplay.start_waves failed: {setup_result}")
            result["navigation"].append({"step": "waves_started", "result": setup_result})
        else:
            setup_result = enable_combat_prelude()
            result["navigation"].append({"step": "combat_prelude_enabled", "result": setup_result})
            combat_state_after_setup = wait_for_combat_prelude_ready()
        time.sleep(POST_WAVES_SETTLE_SECONDS)

        csp.clear_loader_log()
        if args.trace_builder_window:
            result["trace_arm_results"] = arm_trace_profile(args.trace_profile)

        bot = csp.query_bot_state()
        if args.setup_mode == "waves":
            # Wave mode uses stock-spawned enemies. The manual spawn helper is
            # intentionally disabled once arena combat is active because that
            # call shape can wedge Enemy_Create's placement sweep.
            spawn = {"ok": "skipped", "reason": "using_stock_wave_enemies"}
        result["post_setup_spawn"] = spawn
        time.sleep(1.0)
        result["health_seed_before_move"] = sustain_probe_health()
        if args.setup_mode == "combat_prelude":
            range_setup = force_player_target_sample(args.enemy_standoff, args.max_hostile_gap)
            if not range_setup.get("ok"):
                raise WaveCastProbeFailure(f"Unable to establish close-range bot/player sample: {range_setup}")
            current_sample = range_setup["sample"]
            live_bot_id = current_sample["bot.id"]
        else:
            current_sample = crc.query_combat_sample()
            if current_sample.get("available") != "true" or current_sample.get("hostile.available") != "true":
                raise WaveCastProbeFailure(f"Bot/hostile sample unavailable after reposition: {current_sample}")
            live_bot_id = current_sample["bot.id"]
            range_setup = force_close_range_sample(args.enemy_standoff, args.max_hostile_gap)
            if range_setup.get("ok"):
                current_sample = range_setup["sample"]
            else:
                move_into_range = move_bot_into_range(
                    live_bot_id,
                    float(current_sample["hostile.x"]),
                    float(current_sample["hostile.y"]),
                    args.enemy_standoff,
                    args.max_hostile_gap,
                )
                range_setup["move_into_range"] = move_into_range
                if move_into_range.get("ok"):
                    current_sample = move_into_range["sample"]
        if not range_setup.get("ok"):
            raise WaveCastProbeFailure(f"Unable to establish close-range bot/hostile sample: {range_setup}")
        current_gap = float(current_sample["hostile.gap"])
        result["health_seed_before_cast"] = sustain_probe_health()
        target_vitals_before = query_actor_vitals(current_sample["hostile.actor_address"])
        live_bot_id = current_sample["bot.id"]
        stop_before_cast = crc.stop_bot(live_bot_id)
        direct_cast = crc.queue_direct_primary_cast(
            live_bot_id,
            current_sample["hostile.actor_address"],
            float(current_sample["hostile.x"]),
            float(current_sample["hostile.y"]),
        )
        cast_signals = wait_for_cast_signals()

        result["wave_setup"] = {
            "promotion": promotion,
            "setup_mode": args.setup_mode,
            "setup_result": setup_result,
            "combat_state": combat_state_after_setup or query_combat_state(),
            "combat_state_after_cast": query_combat_state(),
            "spawn": spawn,
            "range_setup": range_setup,
            "lua_tick_gate": tick_gate,
            "stop_after_promotion": stop_after_promotion,
            "stop_before_cast": stop_before_cast,
            "sample_before_cast": current_sample,
            "target_vitals_before_cast": target_vitals_before,
            "direct_cast": direct_cast,
            "direct_cast_gap_exceeds_range": current_gap > args.max_hostile_gap,
            "direct_cast_gap": current_gap,
            "cast_signals": cast_signals,
        }
        result["target"] = {
            "cast_hostile": {
                "actor_address": current_sample["hostile.actor_address"],
                "x": current_sample["hostile.x"],
                "y": current_sample["hostile.y"],
                "gap": current_sample["hostile.gap"],
                "object_type_id": current_sample["hostile.object_type_id"],
            },
        }

        samples: list[dict[str, str]] = []
        deadline = time.time() + args.observe_seconds
        while time.time() < deadline:
            sample = (
                force_player_target_sample(args.enemy_standoff, args.max_hostile_gap)["sample"]
                if args.setup_mode == "combat_prelude"
                else crc.query_combat_sample()
            )
            sample["sample_monotonic_ms"] = str(int(time.time() * 1000.0))
            samples.append(sample)
            time.sleep(1.0)

        result["samples"] = samples
        result["after"] = {
            "bot": csp.query_bot_state(),
            "player": csp.query_player_state(),
            "scene": csp.query_scene_state(),
            "world": csp.query_world_state(),
            "selection": csp.query_selection_debug_state(),
            "target_vitals": query_actor_vitals(current_sample["hostile.actor_address"]),
            "bot_actor_raw": csp.query_actor_raw_fields(
                "bot", csp.int_value(csp.query_bot_state(), "actor_address")
            ),
        }
        if args.trace_builder_window:
            result["trace_hits"] = query_trace_profile_hits(args.trace_profile)
        result["loader_log_tail"] = csp.tail_loader_log()
        result["loader_log_filtered"] = crc.filter_loader_log(result["loader_log_tail"])
        result["signals"] = derive_loader_signals("\n".join(result["loader_log_tail"]))

        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(result, indent=2, sort_keys=True))
        crc.set_lua_tick_enabled(True)
        return 0
    except (csp.ProbeFailure, WaveCastProbeFailure) as exc:
        result["error"] = str(exc)
        result["loader_log_tail"] = csp.tail_loader_log()
        result["loader_log_filtered"] = crc.filter_loader_log(result["loader_log_tail"])
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        if args.trace_builder_window:
            try:
                result["trace_hits"] = query_trace_profile_hits(args.trace_profile)
            except csp.ProbeFailure:
                pass
        result["signals"] = derive_loader_signals("\n".join(result.get("loader_log_tail", [])))
        try:
            crc.set_lua_tick_enabled(True)
        except csp.ProbeFailure:
            pass
        print(json.dumps(result, indent=2, sort_keys=True))
        return 1
    finally:
        if args.trace_builder_window:
            try:
                clear_trace_profile(args.trace_profile)
            except csp.ProbeFailure:
                pass
        if not args.keep_running:
            csp.stop_game()


if __name__ == "__main__":
    raise SystemExit(main())
