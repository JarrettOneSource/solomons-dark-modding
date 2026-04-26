#!/usr/bin/env python3
"""Validate bot primary-cast damage one element at a time."""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import cast_state_probe as csp
from cast_trace_profiles import build_trace_specs, trace_profile_is_stable, trace_profile_names
import probe_bot_close_range_combat as crc
import probe_bot_primary_wave_cast as wave


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = ROOT / "runtime" / "probe_bot_element_damage.json"

ELEMENTS = {
    "water": {"element_id": 1, "primary_entry_index": 0x20},
    "earth": {"element_id": 2, "primary_entry_index": 0x28},
    "air": {"element_id": 3, "primary_entry_index": 0x18},
    "ether": {"element_id": 4, "primary_entry_index": 0x08},
}

DEFAULT_PLAYER_ELEMENT = "ether"
DEFAULT_DISCIPLINE = "mind"
DEFAULT_BOT_DISCIPLINE_ID = 1
DEFAULT_STANDOFF = 96.0
DEFAULT_HP = 160.0
DEFAULT_CASTS = 1
DEFAULT_CAST_INTERVAL_SECONDS = 0.85
DEFAULT_SETTLE_SECONDS = 1.25
DEFAULT_MAX_HOSTILE_GAP = 220.0
POST_WAVES_SETTLE_SECONDS = 2.0
ARENA_ENEMY_OBJECT_TYPE_ID = 1001
ARENA_ENEMY_MAX_HP_OFFSET = 0x170
ARENA_ENEMY_CURRENT_HP_OFFSET = 0x174
AIR_LIGHTNING_HANDLER_ADDRESS = 0x00451DC0
DEFAULT_TRACE_PROFILE = "safe_entry"


class ElementDamageProbeFailure(RuntimeError):
    pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Cleanly prove bot damage delivery for each non-fire primary element."
    )
    parser.add_argument(
        "--element",
        action="append",
        choices=sorted(ELEMENTS),
        help="Element to test. Repeat to test multiple. Defaults to all non-fire elements.",
    )
    parser.add_argument("--player-element", choices=sorted(csp.CREATE_ELEMENT_CENTERS), default=DEFAULT_PLAYER_ELEMENT)
    parser.add_argument("--discipline", choices=sorted(csp.CREATE_DISCIPLINE_CENTERS), default=DEFAULT_DISCIPLINE)
    parser.add_argument("--standoff", type=float, default=DEFAULT_STANDOFF)
    parser.add_argument("--max-hostile-gap", type=float, default=DEFAULT_MAX_HOSTILE_GAP)
    parser.add_argument("--hp", type=float, default=DEFAULT_HP)
    parser.add_argument("--casts", type=int, default=DEFAULT_CASTS)
    parser.add_argument("--cast-interval-seconds", type=float, default=DEFAULT_CAST_INTERVAL_SECONDS)
    parser.add_argument("--settle-seconds", type=float, default=DEFAULT_SETTLE_SECONDS)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--keep-running", action="store_true")
    parser.add_argument(
        "--trace-air-handler",
        action="store_true",
        help="Trace the recovered Air lightning action handler during Air probes.",
    )
    parser.add_argument(
        "--trace-builder-window",
        action="store_true",
        help="Trace the native builder/sink path during each element probe.",
    )
    parser.add_argument(
        "--trace-profile",
        default=DEFAULT_TRACE_PROFILE,
        choices=trace_profile_names(),
        help="Trace subset to arm when --trace-builder-window is set.",
    )
    parser.add_argument(
        "--allow-unstable-inline-traces",
        action="store_true",
        help="Permit unstable in-function trace points for deeper diagnostics.",
    )
    parser.add_argument(
        "--watch-target-hp",
        action="store_true",
        help="Arm a direct write watch on the selected hostile actor's HP field.",
    )
    return parser


def query_bot_by_id(bot_id: int) -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local wanted = {bot_id}
local bots = sd.bots and sd.bots.get_state and sd.bots.get_state() or {{}}
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
for _, bot in ipairs(bots) do
  if tonumber(bot.id) == wanted then
    emit('available', true)
    for _, key in ipairs({{
      'id','actor_address','progression_runtime_state_address','progression_handle_address',
      'equip_handle_address','equip_runtime_state_address','gameplay_slot','actor_slot',
      'hp','max_hp','mp','max_mp','x','y','state'
    }}) do
      emit(key, bot[key])
    end
    return
  end
end
emit('available', false)
""".strip()
        )
    )


def query_live_bot_binding_by_id(bot_id: int) -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local wanted = {bot_id}
local bots = sd.bots and sd.bots.get_state and sd.bots.get_state() or {{}}
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
for _, bot in ipairs(bots) do
  if tonumber(bot.id) == wanted then
    local actor = tonumber(bot.actor_address) or 0
    if actor ~= 0 then
      emit('available', true)
      emit('id', bot.id)
      emit('actor_address', actor)
      emit('progression_runtime_state_address', bot.progression_runtime_state_address)
      emit('progression_handle_address', bot.progression_handle_address)
      emit('equip_handle_address', bot.equip_handle_address)
      emit('equip_runtime_state_address', bot.equip_runtime_state_address)
      emit('gameplay_slot', bot.gameplay_slot)
      emit('actor_slot', bot.actor_slot)
      emit('hp', bot.hp)
      emit('max_hp', bot.max_hp)
      emit('mp', bot.mp)
      emit('max_mp', bot.max_mp)
      emit('x', sd.debug.read_float(actor + 0x18))
      emit('y', sd.debug.read_float(actor + 0x1C))
      emit('state', bot.state)
      return
    end
  end
end
emit('available', false)
""".strip()
        )
    )


def wait_for_bot_by_id(bot_id: int, timeout_s: float = 30.0) -> dict[str, str]:
    deadline = time.time() + timeout_s
    last: dict[str, str] = {}
    while time.time() < deadline:
        last = query_live_bot_binding_by_id(bot_id)
        if last.get("available") != "true":
            last = query_bot_by_id(bot_id)
        if last.get("available") == "true" and csp.int_value(last, "actor_address") != 0:
            return last
        time.sleep(0.25)
    raise ElementDamageProbeFailure(f"Timed out waiting for bot {bot_id} materialization. Last={last}")


def create_single_run_bot(element: str, player: dict[str, str]) -> int:
    config = ELEMENTS[element]
    bot_name = f"Damage Probe {element.title()}"
    x = csp.float_value(player, "x") - 80.0
    y = csp.float_value(player, "y")
    result = csp.parse_key_values(
        csp.run_lua(
            f"""
local id = sd.bots.create({{
  name = {json.dumps(bot_name)},
  profile = {{
    element_id = {config["element_id"]},
    discipline_id = {DEFAULT_BOT_DISCIPLINE_ID},
    level = 1,
    experience = 0,
    loadout = {{
      primary_entry_index = {config["primary_entry_index"]},
      primary_combo_entry_index = {config["primary_entry_index"]},
      secondary_entry_indices = {{ -1, -1, -1 }},
    }},
  }},
  scene = {{ kind = 'run' }},
  ready = true,
  position = {{ x = {x}, y = {y}, heading = 90.0 }},
}})
print('ok=' .. tostring(id ~= nil))
print('bot_id=' .. tostring(id))
""".strip()
        )
    )
    if result.get("ok") != "true":
        raise ElementDamageProbeFailure(f"sd.bots.create failed for {element}: {result}")
    bot_id = csp.int_value(result, "bot_id")
    if bot_id == 0:
        raise ElementDamageProbeFailure(f"sd.bots.create returned no id for {element}: {result}")
    return bot_id


def query_scene_actor_by_address(actor_address: int) -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local wanted = {actor_address}
local actors = sd.world and sd.world.list_actors and sd.world.list_actors() or {{}}
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
for _, actor in ipairs(actors) do
  if tonumber(actor.actor_address) == wanted then
    emit('available', true)
    for _, key in ipairs({{
      'actor_address','object_type_id','tracked_enemy','enemy_type','dead',
      'hp','max_hp','x','y','actor_slot','world_slot'
    }}) do
      emit(key, actor[key])
    end
    return
  end
end
emit('available', false)
emit('actor_address', wanted)
""".strip()
        )
    )


def force_scene_actor_vitals(actor_address: int, hp_value: float) -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local actor = {actor_address}
local type_id = tonumber(sd.debug.read_u32(actor + 0x08)) or 0
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
emit('actor_address', actor)
emit('object_type_id', type_id)
if type_id == {ARENA_ENEMY_OBJECT_TYPE_ID} then
  emit('max_hp_ok', sd.debug.write_float(actor + {ARENA_ENEMY_MAX_HP_OFFSET}, {hp_value}))
  emit('hp_ok', sd.debug.write_float(actor + {ARENA_ENEMY_CURRENT_HP_OFFSET}, {hp_value}))
  emit('max_hp', sd.debug.read_float(actor + {ARENA_ENEMY_MAX_HP_OFFSET}))
  emit('hp', sd.debug.read_float(actor + {ARENA_ENEMY_CURRENT_HP_OFFSET}))
else
  emit('max_hp_ok', false)
  emit('hp_ok', false)
end
""".strip()
        )
    )


def force_specific_target_range(
    bot_actor_address: int,
    hostile_actor_address: int,
    standoff: float,
    *,
    heading: float = 90.0,
    bot_hp: float = 500.0,
) -> dict[str, str]:
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
local bot = {bot_actor_address}
local hostile = {hostile_actor_address}
local standoff = {standoff}
local bx = tonumber(sd.debug.read_float(bot + 0x18)) or 0.0
local by = tonumber(sd.debug.read_float(bot + 0x1C)) or 0.0
local prog = tonumber(sd.debug.read_ptr(bot + 0x200)) or 0
local handle = tonumber(sd.debug.read_ptr(bot + 0x300)) or 0
if prog == 0 and handle ~= 0 then
  prog = tonumber(sd.debug.read_ptr(handle)) or 0
end
local hx = bx + standoff
local hy = by
emit('bot_actor_address', bot)
emit('hostile_actor_address', hostile)
emit('bot_x', bx)
emit('bot_y', by)
emit('bot_progression', prog)
if prog ~= 0 then
  emit('bot_hp_ok', sd.debug.write_float(prog + {csp.PROGRESSION_HP_OFFSET}, {bot_hp}))
  emit('bot_max_hp_ok', sd.debug.write_float(prog + {csp.PROGRESSION_MAX_HP_OFFSET}, {bot_hp}))
end
emit('target_x', hx)
emit('target_y', hy)
emit('bot_heading_ok', sd.debug.write_float(bot + 0x6C, {heading}))
emit('hostile_x_ok', sd.debug.write_float(hostile + 0x18, hx))
emit('hostile_y_ok', sd.debug.write_float(hostile + 0x1C, hy))
local dx = (tonumber(sd.debug.read_float(hostile + 0x18)) or hx) - bx
local dy = (tonumber(sd.debug.read_float(hostile + 0x1C)) or hy) - by
emit('gap', math.sqrt(dx * dx + dy * dy))
""".strip()
        )
    )


def pin_target_during_window(
    bot_actor_address: int,
    hostile_actor_address: int,
    standoff: float,
    duration_s: float,
    step_s: float = 0.10,
) -> list[dict[str, str]]:
    samples: list[dict[str, str]] = []
    deadline = time.time() + max(duration_s, 0.0)
    while time.time() < deadline:
        samples.append(force_specific_target_range(bot_actor_address, hostile_actor_address, standoff))
        time.sleep(max(step_s, 0.02))
    return samples


def arm_trace(name: str, address: int, patch_size: int = 0) -> dict[str, str]:
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
for i = 1, math.min(#hits, 16) do
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


def arm_builder_traces(element: str, profile: str) -> tuple[dict[str, dict[str, str]], list[tuple[str, int]]]:
    results: dict[str, dict[str, str]] = {}
    armed: list[tuple[str, int]] = []
    for spec in build_trace_specs(f"bot_{element}_primary", profile):
        result = arm_trace(spec.name, spec.address, spec.patch_size)
        results[spec.name] = result
        if result.get("ok") == "true":
            armed.append((spec.name, spec.address))
    return results, armed


def arm_target_hp_watch(name: str, actor_address: int) -> dict[str, str]:
    hp_address = actor_address + ARENA_ENEMY_CURRENT_HP_OFFSET
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
pcall(sd.debug.unwatch, {json.dumps(name)})
sd.debug.clear_write_hits({json.dumps(name)})
emit("actor", {actor_address})
emit("hp_address", {hp_address})
emit("watch_ok", sd.debug.watch_write({json.dumps(name)}, {hp_address}, 4))
""".strip()
        )
    )


def query_write_hits(name: str) -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local hits = sd.debug.get_write_hits({json.dumps(name)}) or {{}}
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
emit("count", #hits)
for i = 1, math.min(#hits, 16) do
  local hit = hits[i]
  for _, key in ipairs({{
    "requested_address","resolved_address","base_address","access_address",
    "thread_id","eip","esp","ebp","eax","ecx","edx","ret","arg0","arg1","arg2"
  }}) do
    emit("hit." .. i .. "." .. key, hit[key])
  end
end
""".strip()
        )
    )


def clear_target_hp_watch(name: str) -> None:
    csp.run_lua(
        f"""
pcall(sd.debug.unwatch, {json.dumps(name)})
sd.debug.clear_write_hits({json.dumps(name)})
""".strip()
    )


def prepare_clean_run(player_element: str, discipline: str) -> dict[str, object]:
    last_error: Exception | None = None
    for attempt in range(2):
        csp.stop_game()
        csp.clear_loader_log()
        csp.launch_game()
        process_id = csp.wait_for_game_process(timeout_s=45.0)
        csp.wait_for_lua_pipe(timeout_s=60.0)
        early_tick_gate = crc.set_lua_tick_enabled(False)
        try:
            hub_flow = csp.drive_hub_flow(
                process_id,
                element=player_element,
                discipline=discipline,
                prefer_resume=False,
            )
            break
        except csp.ProbeFailure as exc:
            last_error = exc
            if "Last scene=" not in str(exc) or "transition" not in str(exc) or attempt != 0:
                raise
    else:
        raise ElementDamageProbeFailure(f"Unable to reach clean hub scene: {last_error}") from last_error

    tick_gate = crc.set_lua_tick_enabled(False)
    clear_result = crc.clear_bots()
    testrun = crc.start_testrun_without_waves()
    post_run_clear = crc.clear_bots()
    return {
        "process_id": process_id,
        "hub_flow": hub_flow,
        "early_lua_tick_gate": early_tick_gate,
        "lua_tick_gate": tick_gate,
        "clear_bots": clear_result,
        "post_run_clear_bots": post_run_clear,
        "testrun": testrun,
    }


def finite_float(value: float) -> bool:
    return not math.isnan(value) and math.isfinite(value)


def target_hp_write_count(result: dict[str, object]) -> int:
    hits = result.get("target_hp_write_hits")
    if not isinstance(hits, dict):
        return 0
    return csp.int_value(hits, "count")


def run_element_probe(element: str, args: argparse.Namespace) -> dict[str, object]:
    result: dict[str, object] = {
        "element": element,
        "element_config": ELEMENTS[element],
        "ok": False,
        "navigation": {},
        "casts": [],
    }
    armed_traces: list[tuple[str, int]] = []
    target_hp_watch_name = f"bot_{element}_target_hp"
    target_hp_watch_armed = False
    try:
        if (
            args.trace_builder_window
            and not args.allow_unstable_inline_traces
            and not trace_profile_is_stable(args.trace_profile)
        ):
            raise ElementDamageProbeFailure(
                f"trace profile {args.trace_profile!r} contains unstable inline trace points; "
                "use --trace-profile safe_entry or pass --allow-unstable-inline-traces explicitly"
            )
        result["navigation"] = prepare_clean_run(args.player_element, args.discipline)
        player = csp.query_player_state()
        bot_id = create_single_run_bot(element, player)
        bot = wait_for_bot_by_id(bot_id)
        crc.force_actor_position(
            csp.int_value(bot, "actor_address"),
            csp.float_value(bot, "x"),
            csp.float_value(bot, "y"),
            heading=90.0,
        )
        crc.stop_bot(str(bot_id))
        wave.sustain_probe_health()

        waves = csp.parse_key_values(csp.run_lua("print('ok='..tostring(sd.gameplay.start_waves()))"))
        if waves.get("ok") != "true":
            raise ElementDamageProbeFailure(f"sd.gameplay.start_waves failed for {element}: {waves}")
        result["navigation"]["waves"] = waves
        time.sleep(POST_WAVES_SETTLE_SECONDS)
        wave.sustain_probe_health()

        hostile = csp.wait_for_nearest_enemy(timeout_s=30.0, max_gap=5000.0)
        hostile_actor = csp.int_value(hostile, "actor_address")
        bot_actor = csp.int_value(bot, "actor_address")
        range_setup = force_specific_target_range(bot_actor, hostile_actor, args.standoff)
        if (
            range_setup.get("hostile_x_ok") != "true"
            or range_setup.get("hostile_y_ok") != "true"
            or csp.float_value(range_setup, "gap") > args.max_hostile_gap
        ):
            raise ElementDamageProbeFailure(f"Unable to establish bot/hostile range for {element}: {range_setup}")
        forced_vitals = force_scene_actor_vitals(hostile_actor, args.hp)
        before = query_scene_actor_by_address(hostile_actor)
        if args.watch_target_hp:
            result["target_hp_watch"] = arm_target_hp_watch(target_hp_watch_name, hostile_actor)
            target_hp_watch_armed = result["target_hp_watch"].get("watch_ok") == "true"
        if args.trace_builder_window:
            trace_results, builder_traces = arm_builder_traces(element, args.trace_profile)
            result["builder_trace_arm"] = trace_results
            armed_traces.extend(builder_traces)
        if args.trace_air_handler and element == "air":
            trace_name = "air_lightning_handler"
            result["air_handler_trace_arm"] = arm_trace(trace_name, AIR_LIGHTNING_HANDLER_ADDRESS)
            if result["air_handler_trace_arm"].get("ok") == "true":
                armed_traces.append((trace_name, AIR_LIGHTNING_HANDLER_ADDRESS))

        for cast_index in range(max(args.casts, 1)):
            pinned = force_specific_target_range(bot_actor, hostile_actor, args.standoff)
            hostile_now = query_scene_actor_by_address(hostile_actor)
            cast = crc.queue_direct_primary_cast(
                str(bot_id),
                str(hostile_actor),
                csp.float_value(pinned, "target_x"),
                csp.float_value(pinned, "target_y"),
            )
            cast["index"] = str(cast_index + 1)
            cast["hp_before_cast"] = hostile_now.get("hp", "")
            cast["pin"] = pinned
            result["casts"].append(cast)
            cast_window = max(args.cast_interval_seconds, 0.1)
            cast["pin_samples"] = pin_target_during_window(
                bot_actor,
                hostile_actor,
                args.standoff,
                cast_window,
            )

        result["post_cast_pin_samples"] = pin_target_during_window(
            bot_actor,
            hostile_actor,
            args.standoff,
            max(args.settle_seconds, 0.0),
        )
        if args.trace_air_handler and element == "air":
            result["air_handler_trace_hits"] = query_trace_hits("air_lightning_handler")
        if args.trace_builder_window:
            result["builder_trace_hits"] = {
                spec.name: query_trace_hits(spec.name)
                for spec in build_trace_specs(f"bot_{element}_primary", args.trace_profile)
            }
        if target_hp_watch_armed:
            result["target_hp_write_hits"] = query_write_hits(target_hp_watch_name)
        after = query_scene_actor_by_address(hostile_actor)
        hp_before = csp.float_value(before, "hp")
        hp_after = csp.float_value(after, "hp")
        hp_write_count = target_hp_write_count(result)
        target_removed_after_damage = (
            before.get("available") == "true"
            and after.get("available") != "true"
            and hp_write_count > 0
        )
        hp_decreased = (
            finite_float(hp_before)
            and (
                (finite_float(hp_after) and hp_after < hp_before)
                or target_removed_after_damage
            )
        )
        any_cast_queued = any(cast.get("ok") == "true" for cast in result["casts"])
        result.update(
            {
                "player": player,
                "bot": bot,
                "hostile": hostile,
                "range_setup": range_setup,
                "forced_vitals": forced_vitals,
                "before": before,
                "after": after,
                "validation": {
                    "hp_before": hp_before,
                    "hp_after": hp_after,
                    "hp_decreased": hp_decreased,
                    "hp_write_count": hp_write_count,
                    "target_removed_after_damage": target_removed_after_damage,
                    "any_cast_queued": any_cast_queued,
                },
            }
        )
        result["ok"] = bool(hp_decreased and any_cast_queued)
    except (csp.ProbeFailure, crc.CloseRangeProbeFailure, ElementDamageProbeFailure) as exc:
        result["error"] = str(exc)
    finally:
        for trace_name, trace_address in armed_traces:
            try:
                clear_trace(trace_name, trace_address)
            except Exception:
                pass
        if target_hp_watch_armed:
            try:
                clear_target_hp_watch(target_hp_watch_name)
            except Exception:
                pass
        result["loader_log_tail"] = csp.tail_loader_log()
        result["loader_log_filtered"] = crc.filter_loader_log(result["loader_log_tail"])
        if not args.keep_running:
            csp.stop_game()
    return result


def main() -> int:
    args = build_parser().parse_args()
    elements = args.element or list(ELEMENTS.keys())
    result: dict[str, object] = {
        "launcher_freshness": csp.ensure_launcher_bundle_fresh(),
        "elements": elements,
        "results": [],
    }
    for element in elements:
        result["results"].append(run_element_probe(element, args))
    result["ok"] = all(item.get("ok") is True for item in result["results"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
