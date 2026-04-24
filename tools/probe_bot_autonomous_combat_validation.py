#!/usr/bin/env python3
"""Autonomously validate Lua bot closest-target switching and damage delivery."""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

import cast_state_probe as csp
import probe_bot_close_range_combat as crc


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = ROOT / "runtime" / "probe_bot_autonomous_combat_validation.json"

DEFAULT_OBSERVE_SECONDS = 3.5
DEFAULT_NEAR_STANDOFF = 120.0
DEFAULT_FAR_STANDOFF = 300.0
DEFAULT_HP_VALUE = 100.0
DEFAULT_PROBE_HP_VALUE = 500.0
DEFAULT_ELEMENT = "ether"
DEFAULT_DISCIPLINE = "mind"

PROGRESSION_POINTER_OFFSET = 0x200
PROGRESSION_HANDLE_OFFSET = 0x300
SPELL_DISPATCH_BODY_ADDRESS = 0x00548A03
SPELL_3EF_BODY_ADDRESS = 0x0052BB87

ATTACK_RE = re.compile(
    r"attack id=.*? enemy=0x([0-9A-Fa-f]+).*?"
    r"bot=\(([0-9.+-]+),\s*([0-9.+-]+)\).*?"
    r"target=\(([0-9.+-]+),\s*([0-9.+-]+)\).*?"
    r"gap=([0-9.]+)"
)
LAST_RESULT: dict[str, object] = {}


class AutonomousCombatProbeFailure(RuntimeError):
    pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prove autonomous closest-enemy switching and damage/write-watch behavior."
    )
    parser.add_argument("--element", choices=sorted(csp.CREATE_ELEMENT_CENTERS), default=DEFAULT_ELEMENT)
    parser.add_argument("--discipline", choices=sorted(csp.CREATE_DISCIPLINE_CENTERS), default=DEFAULT_DISCIPLINE)
    parser.add_argument("--observe-seconds", type=float, default=DEFAULT_OBSERVE_SECONDS)
    parser.add_argument("--near-standoff", type=float, default=DEFAULT_NEAR_STANDOFF)
    parser.add_argument("--far-standoff", type=float, default=DEFAULT_FAR_STANDOFF)
    parser.add_argument("--hp", type=float, default=DEFAULT_HP_VALUE)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--keep-running", action="store_true")
    return parser


def launch_and_wait_for_lua() -> int:
    csp.launch_game()
    process_id = 0
    try:
        process_id = csp.wait_for_game_process(timeout_s=12.0)
    except csp.ProbeFailure:
        # The Lua pipe is the stronger readiness signal for these probes. Some
        # launcher/process-name races still leave a healthy injected runtime.
        process_id = 0
    csp.wait_for_lua_pipe(timeout_s=60.0)
    return process_id


def start_clean_testrun(process_id: int, element: str, discipline: str) -> dict[str, object]:
    hub_flow = csp.drive_hub_flow(
        process_id,
        element=element,
        discipline=discipline,
        prefer_resume=False,
    )
    crc.set_lua_tick_enabled(False)
    crc.clear_bots()
    testrun = crc.start_testrun_without_waves()
    return {"hub_flow": hub_flow, "testrun": testrun}


def sustain_probe_health(hp_value: float = DEFAULT_PROBE_HP_VALUE) -> dict[str, str]:
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


def list_enemy_actors() -> list[dict[str, str]]:
    values = csp.parse_key_values(
        csp.run_lua(
            """
local actors = sd.world and sd.world.list_actors and sd.world.list_actors() or {}
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
local n = 0
for _, actor in ipairs(actors) do
  local object_type_id = tonumber(actor.object_type_id) or 0
  if object_type_id == 5009 or object_type_id == 5010 or actor.tracked_enemy == true then
    n = n + 1
    local prefix = "enemy." .. tostring(n) .. "."
    for _, key in ipairs({
      "actor_address","object_type_id","tracked_enemy","dead","hp","max_hp","x","y"
    }) do
      emit(prefix .. key, actor[key])
    end
  end
end
emit("count", n)
""".strip()
        )
    )
    enemies: list[dict[str, str]] = []
    for index in range(1, csp.int_value(values, "count") + 1):
        prefix = f"enemy.{index}."
        enemy = {
            key[len(prefix):]: value
            for key, value in values.items()
            if key.startswith(prefix)
        }
        if enemy:
            enemies.append(enemy)
    return enemies


def live_enemy_actors() -> list[dict[str, str]]:
    live: list[dict[str, str]] = []
    seen: set[int] = set()
    for enemy in list_enemy_actors():
        actor_address = csp.int_value(enemy, "actor_address")
        if actor_address == 0 or actor_address in seen:
            continue
        seen.add(actor_address)
        if enemy.get("tracked_enemy") != "true":
            continue
        if enemy.get("dead") == "true":
            continue
        if csp.float_value(enemy, "hp") <= 0.0 or csp.float_value(enemy, "max_hp") <= 0.0:
            continue
        live.append(enemy)
    return live


def wait_for_live_enemies(count: int, timeout_s: float = 12.0) -> list[dict[str, str]]:
    deadline = time.time() + timeout_s
    last: list[dict[str, str]] = []
    while time.time() < deadline:
        last = live_enemy_actors()
        if len(last) >= count:
            return last[:count]
        time.sleep(0.25)
    raise AutonomousCombatProbeFailure(f"Timed out waiting for {count} live enemies. Last={last}")


def wait_for_specific_live_enemies(addresses: list[int], timeout_s: float = 12.0) -> list[dict[str, str]]:
    wanted = {address for address in addresses if address != 0}
    deadline = time.time() + timeout_s
    last: list[dict[str, str]] = []
    while time.time() < deadline:
        last = live_enemy_actors()
        found: dict[int, dict[str, str]] = {}
        for enemy in last:
            actor_address = csp.int_value(enemy, "actor_address")
            if actor_address in wanted:
                found[actor_address] = enemy
        if wanted and wanted.issubset(found):
            return [found[address] for address in addresses if address in found]
        time.sleep(0.25)
    raise AutonomousCombatProbeFailure(
        f"Timed out waiting for specific live enemies {sorted(wanted)}. Last={last}"
    )


def start_waves() -> dict[str, str]:
    values = csp.parse_key_values(csp.run_lua("print('ok='..tostring(sd.gameplay.start_waves()))"))
    if values.get("ok") != "true":
        raise AutonomousCombatProbeFailure(f"sd.gameplay.start_waves failed: {values}")
    return values


def wait_for_wave_combat_active(timeout_s: float = 12.0) -> dict[str, str]:
    deadline = time.time() + timeout_s
    last: dict[str, str] = {}
    while time.time() < deadline:
        last = crc.query_combat_state()
        if last.get("available") == "true":
            wave_index = csp.int_value(last, "wave_index")
            if last.get("active") == "true" or wave_index > 0:
                return last
        time.sleep(0.1)
    raise AutonomousCombatProbeFailure(f"Timed out waiting for wave combat state. Last={last}")


def query_progression_for_actor(actor_address: int) -> dict[str, str]:
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
local actor = {actor_address}
local progression = tonumber(sd.debug.read_ptr(actor + {PROGRESSION_POINTER_OFFSET})) or 0
local handle = tonumber(sd.debug.read_ptr(actor + {PROGRESSION_HANDLE_OFFSET})) or 0
if progression == 0 and handle ~= 0 then
  progression = tonumber(sd.debug.read_ptr(handle)) or 0
end
emit("actor", actor)
emit("progression", progression)
emit("handle", handle)
if progression ~= 0 then
  emit("hp", sd.debug.read_float(progression + {csp.PROGRESSION_HP_OFFSET}))
  emit("max_hp", sd.debug.read_float(progression + {csp.PROGRESSION_MAX_HP_OFFSET}))
end
""".strip()
        )
    )


def force_actor_vitals(actor_address: int, hp_value: float) -> dict[str, str]:
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
local actor = {actor_address}
local progression = tonumber(sd.debug.read_ptr(actor + {PROGRESSION_POINTER_OFFSET})) or 0
local handle = tonumber(sd.debug.read_ptr(actor + {PROGRESSION_HANDLE_OFFSET})) or 0
if progression == 0 and handle ~= 0 then
  progression = tonumber(sd.debug.read_ptr(handle)) or 0
end
emit("actor", actor)
emit("progression", progression)
emit("handle", handle)
if progression ~= 0 then
  emit("max_hp_ok", sd.debug.write_float(progression + {csp.PROGRESSION_MAX_HP_OFFSET}, {hp_value}))
  emit("hp_ok", sd.debug.write_float(progression + {csp.PROGRESSION_HP_OFFSET}, {hp_value}))
  emit("hp", sd.debug.read_float(progression + {csp.PROGRESSION_HP_OFFSET}))
  emit("max_hp", sd.debug.read_float(progression + {csp.PROGRESSION_MAX_HP_OFFSET}))
end
""".strip()
        )
    )


def force_enemy(actor_address: int, x: float, y: float, hp_value: float) -> dict[str, object]:
    vitals = force_actor_vitals(actor_address, hp_value)
    position = crc.force_actor_position(actor_address, x, y)
    if position.get("x_ok") != "true" or position.get("y_ok") != "true":
        raise AutonomousCombatProbeFailure(f"Failed to force enemy position: {position}")
    return {"vitals": vitals, "position": position}


def arm_hp_watch(name: str, actor_address: int) -> dict[str, str]:
    progression = query_progression_for_actor(actor_address)
    progression_address = csp.int_value(progression, "progression")
    if progression_address == 0:
        return {
            "actor": str(actor_address),
            "progression": "0",
            "watch_ok": "false",
            "watchable": "false",
            "reason": "no_progression",
        }
    hp_address = progression_address + csp.PROGRESSION_HP_OFFSET
    values = csp.parse_key_values(
        csp.run_lua(
            f"""
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
sd.debug.unwatch({json.dumps(name)})
sd.debug.clear_write_hits({json.dumps(name)})
emit("actor", {actor_address})
emit("progression", {progression_address})
emit("hp_address", {hp_address})
emit("watch_ok", sd.debug.watch_write({json.dumps(name)}, {hp_address}, 4))
emit("watchable", true)
""".strip()
        )
    )
    return values


def place_combat_enemies(
    enemies: list[dict[str, str]],
    near_enemy_address: int,
    far_enemy_address: int,
    bot_x: float,
    bot_y: float,
    near_standoff: float,
    far_standoff: float,
    hp_value: float,
) -> list[dict[str, object]]:
    placements: list[dict[str, object]] = []
    extra_index = 0
    for enemy in enemies:
        actor_address = csp.int_value(enemy, "actor_address")
        if actor_address == 0:
            continue
        if actor_address == near_enemy_address:
            target_x = bot_x + near_standoff
            target_y = bot_y
            label = "near"
        elif actor_address == far_enemy_address:
            target_x = bot_x + far_standoff
            target_y = bot_y
            label = "far"
        else:
            extra_index += 1
            target_x = bot_x + far_standoff + 450.0 + (extra_index * 75.0)
            target_y = bot_y + 350.0 + (extra_index * 50.0)
            label = "extra_far"

        vitals = force_actor_vitals(actor_address, hp_value)
        position = crc.force_actor_position(actor_address, target_x, target_y)
        placements.append({
            "actor_address": actor_address,
            "label": label,
            "target_x": target_x,
            "target_y": target_y,
            "vitals": vitals,
            "position": position,
        })
        if position.get("x_ok") != "true" or position.get("y_ok") != "true":
            raise AutonomousCombatProbeFailure(
                f"Failed to force {label} enemy position for 0x{actor_address:X}: {position}"
            )
    return placements


def clear_hp_watch(name: str) -> None:
    csp.run_lua(
        f"""
pcall(sd.debug.unwatch, {json.dumps(name)})
sd.debug.clear_write_hits({json.dumps(name)})
""".strip()
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
for i = 1, math.min(#hits, 8) do
  local hit = hits[i]
  for _, key in ipairs({{
    "requested_address","resolved_address","access_address","thread_id",
    "eip","esp","ebp","eax","ecx","edx","ret","arg0","arg1","arg2"
  }}) do
    emit("hit." .. i .. "." .. key, hit[key])
  end
end
""".strip()
        )
    )


def arm_spell_traces() -> dict[str, str]:
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
pcall(sd.debug.untrace_function, {SPELL_DISPATCH_BODY_ADDRESS})
pcall(sd.debug.untrace_function, {SPELL_3EF_BODY_ADDRESS})
sd.debug.clear_trace_hits("autonomous_spell_dispatch_body")
sd.debug.clear_trace_hits("autonomous_spell_3ef_body")
emit("dispatch_body", sd.debug.trace_function({SPELL_DISPATCH_BODY_ADDRESS}, "autonomous_spell_dispatch_body", 6))
emit("spell_3ef_body", sd.debug.trace_function({SPELL_3EF_BODY_ADDRESS}, "autonomous_spell_3ef_body", 5))
""".strip()
        )
    )


def clear_spell_traces() -> None:
    csp.run_lua(
        f"""
pcall(sd.debug.untrace_function, {SPELL_DISPATCH_BODY_ADDRESS})
pcall(sd.debug.untrace_function, {SPELL_3EF_BODY_ADDRESS})
sd.debug.clear_trace_hits("autonomous_spell_dispatch_body")
sd.debug.clear_trace_hits("autonomous_spell_3ef_body")
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
emit("count", #hits)
for i = 1, math.min(#hits, 8) do
  local hit = hits[i]
  for _, key in ipairs({{
    "requested_address","resolved_address","thread_id","eax","ecx","edx",
    "ebx","esi","edi","ebp","esp_before_pushad","ret","arg0","arg1","arg2"
  }}) do
    emit("hit." .. i .. "." .. key, hit[key])
  end
end
""".strip()
        )
    )


def read_loader_lines() -> list[str]:
    if not csp.LOADER_LOG.exists():
        return []
    text = csp.LOADER_LOG.read_text(encoding="utf-8", errors="replace")
    return text.splitlines()


def read_attack_lines() -> list[str]:
    return [
        line for line in read_loader_lines()
        if "[lua.bots] attack id=" in line
    ]


def read_enemy_death_lines() -> list[str]:
    return [
        line for line in read_loader_lines()
        if "enemy.death hook invoked." in line
    ]


def parse_attacks(lines: list[str]) -> list[dict[str, object]]:
    attacks: list[dict[str, object]] = []
    for line in lines:
        match = ATTACK_RE.search(line)
        if match is None:
            continue
        attacks.append({
            "line": line,
            "enemy_hex": match.group(1).upper(),
            "enemy_address": int(match.group(1), 16),
            "bot_x": float(match.group(2)),
            "bot_y": float(match.group(3)),
            "target_x": float(match.group(4)),
            "target_y": float(match.group(5)),
            "gap": float(match.group(6)),
        })
    return attacks


def classify_attack_against_live_enemies(attack: dict[str, object]) -> dict[str, object]:
    enemies = live_enemy_actors()
    bot_x = float(attack.get("bot_x") or 0.0)
    bot_y = float(attack.get("bot_y") or 0.0)
    target_address = int(attack.get("enemy_address") or 0)
    closest_address = 0
    closest_gap = float("inf")
    target_seen = False
    target_gap = float(attack.get("gap") or 0.0)
    for enemy in enemies:
        actor_address = csp.int_value(enemy, "actor_address")
        enemy_x = csp.float_value(enemy, "x")
        enemy_y = csp.float_value(enemy, "y")
        gap = ((enemy_x - bot_x) ** 2 + (enemy_y - bot_y) ** 2) ** 0.5
        if actor_address == target_address:
            target_seen = True
            target_gap = gap
        if gap < closest_gap:
            closest_gap = gap
            closest_address = actor_address
    return {
        "attack": attack,
        "target_seen_in_live_snapshot": target_seen,
        "closest_address": closest_address,
        "closest_gap": closest_gap,
        "target_gap": target_gap,
        "target_is_closest": target_seen and target_address == closest_address,
        "live_enemy_count": len(enemies),
    }


def observe_attack_window(seconds: float) -> dict[str, object]:
    baseline_attack_count = len(read_attack_lines())
    baseline_death_count = len(read_enemy_death_lines())
    crc.set_lua_tick_enabled(True)
    samples: list[dict[str, object]] = []
    try:
        deadline = time.time() + seconds
        sampled_attack_count = 0
        while time.time() < deadline:
            current_attack_lines = read_attack_lines()[baseline_attack_count:]
            if len(current_attack_lines) > sampled_attack_count:
                new_attacks = parse_attacks(current_attack_lines[sampled_attack_count:])
                for attack in new_attacks:
                    samples.append(classify_attack_against_live_enemies(attack))
                sampled_attack_count = len(current_attack_lines)
            time.sleep(0.2)
    finally:
        crc.set_lua_tick_enabled(False)

    lines = read_attack_lines()[baseline_attack_count:]
    death_lines = read_enemy_death_lines()[baseline_death_count:]
    return {
        "lines": lines[-20:],
        "attacks": parse_attacks(lines),
        "closest_samples": samples,
        "enemy_death_lines": death_lines[-20:],
    }


def any_attack_targeted_closest(window: dict[str, object]) -> bool:
    samples = window.get("closest_samples")
    if not isinstance(samples, list):
        return False
    return any(bool(sample.get("target_is_closest")) for sample in samples if isinstance(sample, dict))


def run_validation(args: argparse.Namespace) -> dict[str, object]:
    result: dict[str, object] = {
        "launcher_freshness": csp.ensure_launcher_bundle_fresh(),
        "steps": [],
    }
    global LAST_RESULT
    LAST_RESULT = result
    process_id = launch_and_wait_for_lua()
    result["process_id"] = process_id
    result["steps"].append({"step": "launch", "process_id": process_id})

    result["navigation"] = start_clean_testrun(process_id, args.element, args.discipline)
    result["steps"].append({"step": "testrun_ready"})

    crc.set_lua_tick_enabled(True)
    spawned_bot = csp.wait_for_materialized_bot()
    crc.set_lua_tick_enabled(False)
    player = csp.query_player_state()
    promotion = crc.promote_bot_into_run_scene(csp.float_value(player, "x"), csp.float_value(player, "y"))
    if promotion.get("ok") != "true":
        raise AutonomousCombatProbeFailure(f"Bot run-scene promotion failed: {promotion}")
    time.sleep(1.0)
    bot = csp.query_bot_state()
    if csp.int_value(bot, "actor_address") == 0:
        raise AutonomousCombatProbeFailure(f"Bot did not materialize after promotion: {bot}")
    crc.stop_bot(bot["id"])
    bot_x = csp.float_value(bot, "x")
    bot_y = csp.float_value(bot, "y")
    result["bot_setup"] = {
        "spawned": spawned_bot,
        "promoted": bot,
        "promotion": promotion,
        "stop": crc.stop_bot(bot["id"]),
    }

    known_addresses = {
        csp.int_value(enemy, "actor_address")
        for enemy in list_enemy_actors()
        if csp.int_value(enemy, "actor_address") != 0
    }
    result["pre_wave_known_enemy_addresses"] = sorted(known_addresses)
    result["probe_health_before_waves"] = sustain_probe_health()
    result["start_waves"] = start_waves()
    result["wave_combat_state"] = wait_for_wave_combat_active()
    enemies = wait_for_live_enemies(2)
    result["live_enemies_after_wave_start"] = enemies

    first_enemy_address = csp.int_value(enemies[0], "actor_address")
    second_enemy_address = csp.int_value(enemies[1], "actor_address")
    result["selected_enemy_addresses"] = {
        "initial_near": first_enemy_address,
        "initial_far": second_enemy_address,
    }
    result["initial_enemy_placements"] = place_combat_enemies(
        live_enemy_actors(),
        first_enemy_address,
        second_enemy_address,
        bot_x,
        bot_y,
        args.near_standoff,
        args.far_standoff,
        args.hp,
    )
    result["probe_health_after_initial_placement"] = sustain_probe_health()
    result["enemies_before_first_window"] = live_enemy_actors()

    result["spell_trace_arm"] = arm_spell_traces()
    result["hp_watch_initial_near"] = arm_hp_watch("autonomous_initial_near_hp", first_enemy_address)
    result["hp_watch_initial_far"] = arm_hp_watch("autonomous_initial_far_hp", second_enemy_address)
    first_before = {
        "near": query_progression_for_actor(first_enemy_address),
        "far": query_progression_for_actor(second_enemy_address),
    }
    first_window = observe_attack_window(args.observe_seconds)
    result["probe_health_after_first_window"] = sustain_probe_health()
    first_after = {
        "near": query_progression_for_actor(first_enemy_address),
        "far": query_progression_for_actor(second_enemy_address),
    }
    result["first_window"] = {
        "before": first_before,
        "observation": first_window,
        "after": first_after,
        "write_hits": {
            "near": query_write_hits("autonomous_initial_near_hp"),
            "far": query_write_hits("autonomous_initial_far_hp"),
        },
    }
    clear_hp_watch("autonomous_initial_near_hp")
    clear_hp_watch("autonomous_initial_far_hp")

    result["swapped_enemy_placements"] = place_combat_enemies(
        live_enemy_actors(),
        second_enemy_address,
        first_enemy_address,
        bot_x,
        bot_y,
        args.near_standoff,
        args.far_standoff,
        args.hp,
    )
    result["probe_health_after_swap"] = sustain_probe_health()
    time.sleep(2.3)
    result["enemies_before_second_window"] = live_enemy_actors()
    result["hp_watch_swapped_near"] = arm_hp_watch("autonomous_swapped_near_hp", second_enemy_address)
    result["hp_watch_swapped_far"] = arm_hp_watch("autonomous_swapped_far_hp", first_enemy_address)
    second_before = {
        "near": query_progression_for_actor(second_enemy_address),
        "far": query_progression_for_actor(first_enemy_address),
    }
    second_window = observe_attack_window(args.observe_seconds)
    result["probe_health_after_second_window"] = sustain_probe_health()
    second_after = {
        "near": query_progression_for_actor(second_enemy_address),
        "far": query_progression_for_actor(first_enemy_address),
    }
    result["second_window"] = {
        "before": second_before,
        "observation": second_window,
        "after": second_after,
        "write_hits": {
            "near": query_write_hits("autonomous_swapped_near_hp"),
            "far": query_write_hits("autonomous_swapped_far_hp"),
        },
    }
    clear_hp_watch("autonomous_swapped_near_hp")
    clear_hp_watch("autonomous_swapped_far_hp")

    result["spell_trace_hits"] = {
        "dispatch_body": query_trace_hits("autonomous_spell_dispatch_body"),
        "spell_3ef_body": query_trace_hits("autonomous_spell_3ef_body"),
    }
    result["loader_log_filtered"] = crc.filter_loader_log(csp.tail_loader_log(240))

    first_attacks = first_window["attacks"]
    second_attacks = second_window["attacks"]
    first_target = first_attacks[0]["enemy_address"] if first_attacks else 0
    second_target = second_attacks[0]["enemy_address"] if second_attacks else 0

    first_near_hp_before = csp.float_value(first_before["near"], "hp")
    first_near_hp_after = csp.float_value(first_after["near"], "hp")
    second_near_hp_before = csp.float_value(second_before["near"], "hp")
    second_near_hp_after = csp.float_value(second_after["near"], "hp")
    first_near_write_count = csp.int_value(result["first_window"]["write_hits"]["near"], "count")
    second_near_write_count = csp.int_value(result["second_window"]["write_hits"]["near"], "count")
    dispatch_hits = csp.int_value(result["spell_trace_hits"]["dispatch_body"], "count")
    spell_3ef_hits = csp.int_value(result["spell_trace_hits"]["spell_3ef_body"], "count")

    first_targeted_closest = any_attack_targeted_closest(first_window)
    second_targeted_closest = any_attack_targeted_closest(second_window)
    first_enemy_death_count = len(first_window.get("enemy_death_lines") or [])
    second_enemy_death_count = len(second_window.get("enemy_death_lines") or [])

    result["validation"] = {
        "first_attack_seen": bool(first_attacks),
        "second_attack_seen": bool(second_attacks),
        "first_target_was_initial_near": first_target == first_enemy_address,
        "second_target_switched_to_previous_far": second_target == second_enemy_address,
        "no_lock_to_first_target": bool(first_target and second_target and first_target != second_target),
        "first_targeted_closest_at_observation": first_targeted_closest,
        "second_targeted_closest_at_observation": second_targeted_closest,
        "first_target": first_target,
        "second_target": second_target,
        "initial_near": first_enemy_address,
        "initial_far": second_enemy_address,
        "first_near_hp_before": first_near_hp_before,
        "first_near_hp_after": first_near_hp_after,
        "second_near_hp_before": second_near_hp_before,
        "second_near_hp_after": second_near_hp_after,
        "first_near_hp_write_hits": first_near_write_count,
        "second_near_hp_write_hits": second_near_write_count,
        "first_enemy_death_count": first_enemy_death_count,
        "second_enemy_death_count": second_enemy_death_count,
        "spell_dispatch_hits": dispatch_hits,
        "spell_3ef_hits": spell_3ef_hits,
        "damage_or_hp_write_seen": (
            first_near_write_count > 0
            or second_near_write_count > 0
            or first_near_hp_after < first_near_hp_before
            or second_near_hp_after < second_near_hp_before
            or first_enemy_death_count > 0
            or second_enemy_death_count > 0
        ),
    }
    result["closest_target_ok"] = all(
        bool(result["validation"][key])
        for key in (
            "first_attack_seen",
            "second_attack_seen",
            "first_targeted_closest_at_observation",
            "second_targeted_closest_at_observation",
        )
    )
    result["damage_ok"] = bool(result["validation"]["damage_or_hp_write_seen"])
    result["ok"] = bool(result["closest_target_ok"] and result["damage_ok"])
    return result


def main() -> int:
    args = build_parser().parse_args()
    result: dict[str, object] = {}
    try:
        csp.stop_game()
        csp.clear_loader_log()
        result = run_validation(args)
    except Exception as exc:
        if not result and LAST_RESULT:
            result = LAST_RESULT
        result.setdefault("ok", False)
        result["error"] = str(exc)
        result["loader_log_tail"] = csp.tail_loader_log(160)
    finally:
        try:
            crc.set_lua_tick_enabled(False)
        except Exception:
            pass
        try:
            clear_hp_watch("autonomous_initial_near_hp")
            clear_hp_watch("autonomous_initial_far_hp")
            clear_hp_watch("autonomous_swapped_near_hp")
            clear_hp_watch("autonomous_swapped_far_hp")
            clear_spell_traces()
        except Exception:
            pass
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        if not args.keep_running:
            csp.stop_game()

    summary = {
        "ok": result.get("ok"),
        "closest_target_ok": result.get("closest_target_ok"),
        "damage_ok": result.get("damage_ok"),
        "validation": result.get("validation"),
        "error": result.get("error"),
        "output": str(args.output),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
