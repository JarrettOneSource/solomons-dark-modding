#!/usr/bin/env python3
"""Live regression for Earth Boulder target swaps during held charge."""

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
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import cast_state_probe as csp  # noqa: E402
import probe_bot_close_range_combat as crc  # noqa: E402
import probe_bot_element_damage as element_probe  # noqa: E402
import probe_bot_primary_wave_cast as wave  # noqa: E402


OUTPUT_PATH = ROOT / "runtime" / "live_boulder_retarget_probe.json"
# The wave spawner can reuse an actor address after native "enemy.death hook invoked" evidence.
ENEMY_DEATH_RE = re.compile(r"enemy\.death hook invoked\.\s+enemy=(0x[0-9A-Fa-f]+)\b")


class LiveBoulderRetargetProbeFailure(RuntimeError):
    pass


def as_float(value: Any, default: float = math.nan) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def close_enough(actual: float, expected: float, tolerance: float = 3.0) -> bool:
    return math.isfinite(actual) and abs(actual - expected) <= tolerance


def heading_towards(from_x: float, from_y: float, to_x: float, to_y: float) -> float:
    return (math.degrees(math.atan2(to_y - from_y, to_x - from_x)) + 90.0) % 360.0


def wait_for_two_hostiles(
    bot_actor_address: int,
    *,
    limit: int,
    timeout_s: float,
) -> list[dict[str, object]]:
    deadline = time.time() + timeout_s
    last: list[dict[str, object]] = []
    while time.time() < deadline:
        last = element_probe.query_watchable_hostiles(limit, bot_actor_address)
        if len(last) >= 2:
            return last
        time.sleep(0.20)
    raise LiveBoulderRetargetProbeFailure(
        f"Timed out waiting for two live hostiles. last_count={len(last)}"
    )


def choose_live_retarget_hostile(
    bot_actor_address: int,
    initial_actor_address: int,
    *,
    limit: int,
    timeout_s: float,
) -> dict[str, object]:
    deadline = time.time() + timeout_s
    last: list[dict[str, object]] = []
    while time.time() < deadline:
        last = element_probe.query_watchable_hostiles(limit, bot_actor_address)
        for hostile in last:
            actor_address = int(hostile.get("actor_address", 0))
            if actor_address != 0 and actor_address != initial_actor_address:
                return hostile
        time.sleep(0.10)
    raise LiveBoulderRetargetProbeFailure(
        "Timed out waiting for a live retarget hostile. "
        f"initial=0x{initial_actor_address:X} last={last}"
    )


def set_dual_target_state(
    *,
    bot_id: int,
    bot_actor_address: int,
    initial_actor_address: int,
    retarget_actor_address: int,
    bot_x: float,
    bot_y: float,
    initial_x: float,
    initial_y: float,
    retarget_x: float,
    retarget_y: float,
    initial_far_x: float,
    initial_far_y: float,
    initial_hp: float,
    retarget_hp: float,
    bot_mp: float,
    face_retarget: bool,
) -> dict[str, str]:
    mp_offset = element_probe.read_runtime_layout_offset("progression_mp")
    max_mp_offset = element_probe.read_runtime_layout_offset("progression_max_mp")
    heading = heading_towards(bot_x, bot_y, retarget_x, retarget_y)
    initial_target_x = initial_far_x if face_retarget else initial_x
    initial_target_y = initial_far_y if face_retarget else initial_y
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
local bot_id = {bot_id}
local bot = {bot_actor_address}
local initial = {initial_actor_address}
local retarget = {retarget_actor_address}
local bot_x = {bot_x}
local bot_y = {bot_y}
local initial_x = {initial_target_x}
local initial_y = {initial_target_y}
local retarget_x = {retarget_x}
local retarget_y = {retarget_y}
local heading = {heading}
local prog = tonumber(sd.debug.read_ptr(bot + {element_probe.ACTOR_PROGRESSION_RUNTIME_STATE_OFFSET})) or 0
local handle = tonumber(sd.debug.read_ptr(bot + {element_probe.ACTOR_PROGRESSION_HANDLE_OFFSET})) or 0
if prog == 0 and handle ~= 0 then
  prog = tonumber(sd.debug.read_ptr(handle)) or 0
end
local function freeze_enemy(actor, x, y, hp)
  local ok_x = sd.debug.write_float(actor + {element_probe.ACTOR_POSITION_X_OFFSET}, x)
  local ok_y = sd.debug.write_float(actor + {element_probe.ACTOR_POSITION_Y_OFFSET}, y)
  local ok_max_hp = sd.debug.write_float(actor + {element_probe.ARENA_ENEMY_MAX_HP_OFFSET}, hp)
  local ok_hp = sd.debug.write_float(actor + {element_probe.ARENA_ENEMY_CURRENT_HP_OFFSET}, hp)
  local ok_rebind = true
  if sd.world and sd.world.rebind_actor then
    ok_rebind = sd.world.rebind_actor(actor)
  end
  return ok_x and ok_y and ok_max_hp and ok_hp and ok_rebind
end
emit('bot_actor_address', bot)
emit('initial_actor_address', initial)
emit('retarget_actor_address', retarget)
emit('bot_progression', prog)
emit('bot_x_ok', sd.debug.write_float(bot + {element_probe.ACTOR_POSITION_X_OFFSET}, bot_x))
emit('bot_y_ok', sd.debug.write_float(bot + {element_probe.ACTOR_POSITION_Y_OFFSET}, bot_y))
emit('bot_heading_ok', sd.debug.write_float(bot + {element_probe.ACTOR_HEADING_OFFSET}, heading))
if prog ~= 0 then
  emit('bot_hp_ok', sd.debug.write_float(prog + {csp.PROGRESSION_HP_OFFSET}, 50000.0))
  emit('bot_max_hp_ok', sd.debug.write_float(prog + {csp.PROGRESSION_MAX_HP_OFFSET}, 50000.0))
emit('bot_mp_ok', sd.debug.write_float(prog + {mp_offset}, {bot_mp}))
  emit('bot_max_mp_ok', sd.debug.write_float(prog + {max_mp_offset}, {bot_mp}))
end
emit('initial_object_type_before_freeze', sd.debug.read_u32(initial + {element_probe.OBJECT_TYPE_ID_OFFSET}))
emit('initial_hp_before_freeze', sd.debug.read_float(initial + {element_probe.ARENA_ENEMY_CURRENT_HP_OFFSET}))
emit('retarget_object_type_before_freeze', sd.debug.read_u32(retarget + {element_probe.OBJECT_TYPE_ID_OFFSET}))
emit('retarget_hp_before_freeze', sd.debug.read_float(retarget + {element_probe.ARENA_ENEMY_CURRENT_HP_OFFSET}))
emit('initial_ok', freeze_enemy(initial, initial_x, initial_y, {initial_hp}))
emit('retarget_ok', freeze_enemy(retarget, retarget_x, retarget_y, {retarget_hp}))
emit('initial_object_type_after_freeze', sd.debug.read_u32(initial + {element_probe.OBJECT_TYPE_ID_OFFSET}))
emit('initial_hp_after_freeze', sd.debug.read_float(initial + {element_probe.ARENA_ENEMY_CURRENT_HP_OFFSET}))
emit('retarget_object_type_after_freeze', sd.debug.read_u32(retarget + {element_probe.OBJECT_TYPE_ID_OFFSET}))
emit('retarget_hp_after_freeze', sd.debug.read_float(retarget + {element_probe.ARENA_ENEMY_CURRENT_HP_OFFSET}))
if sd.world and sd.world.rebind_actor then
  emit('bot_rebind_ok', sd.world.rebind_actor(bot))
  emit('initial_rebind_ok', sd.world.rebind_actor(initial))
  emit('retarget_rebind_ok', sd.world.rebind_actor(retarget))
end
if {str(face_retarget).lower()} then
  emit('face_target_ok', sd.bots.face_target(bot_id, retarget, heading))
else
  emit('face_target_ok', sd.bots.face_target(bot_id, initial, heading))
end
emit('bot_x', bot_x)
emit('bot_y', bot_y)
emit('initial_x', initial_x)
emit('initial_y', initial_y)
emit('retarget_x', retarget_x)
emit('retarget_y', retarget_y)
emit('heading', heading)
""".strip()
        )
    )


def boulder_release_logged(
    *,
    bot_id: int,
    log_start_index: int,
) -> bool:
    needle = f"bot_id={bot_id}"
    for line in element_probe.read_loader_log_lines()[max(log_start_index, 0):]:
        if "[bots] native boulder release requested." in line and needle in line:
            return True
    return False


def boulder_completion_logged(
    *,
    bot_id: int,
    log_start_index: int,
) -> bool:
    needle = f"bot_id={bot_id}"
    for line in element_probe.read_loader_log_lines()[max(log_start_index, 0):]:
        if "[bots] cast complete (" in line and needle in line:
            return True
    return False


def find_enemy_death_lines(
    loader_log_lines: list[str],
    *,
    actor_address: int,
    log_start_index: int,
) -> list[str]:
    matches: list[str] = []
    for line in loader_log_lines[max(log_start_index, 0):]:
        match = ENEMY_DEATH_RE.search(line)
        if match is None:
            continue
        if int(match.group(1), 16) == actor_address:
            matches.append(line)
    return matches


def query_active_boulder_object(bot_id: int) -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local bot_id = {bot_id}
local bot = sd.bots and sd.bots.get_state and sd.bots.get_state(bot_id) or {{}}
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
emit('cast_active', bot.cast_active)
emit('active_spell_object_readable', bot.active_spell_object_readable)
emit('active_spell_object_address', bot.active_spell_object_address)
emit('active_spell_object_type', bot.active_spell_object_type)
emit('active_spell_object_x', bot.active_spell_object_x)
emit('active_spell_object_y', bot.active_spell_object_y)
emit('active_spell_object_radius', bot.active_spell_object_radius)
emit('active_spell_object_charge', bot.active_spell_object_charge)
""".strip()
        )
    )


def wait_for_active_boulder_object(
    *,
    bot_id: int,
    timeout_s: float,
) -> dict[str, str]:
    deadline = time.time() + max(timeout_s, 0.1)
    last: dict[str, str] = {}
    while time.time() < deadline:
        last = query_active_boulder_object(bot_id)
        object_address = as_int(last.get("active_spell_object_address"))
        object_x = as_float(last.get("active_spell_object_x"))
        object_y = as_float(last.get("active_spell_object_y"))
        if (
            last.get("cast_active") == "true"
            and last.get("active_spell_object_readable") == "true"
            and object_address != 0
            and math.isfinite(object_x)
            and math.isfinite(object_y)
        ):
            return last
        time.sleep(0.05)
    raise LiveBoulderRetargetProbeFailure(
        f"Timed out waiting for active charged Boulder object. last={last}"
    )


def pin_retarget_window(
    *,
    bot_id: int,
    bot_actor_address: int,
    initial_actor_address: int,
    retarget_actor_address: int,
    bot_x: float,
    bot_y: float,
    initial_x: float,
    initial_y: float,
    retarget_x: float,
    retarget_y: float,
    initial_far_x: float,
    initial_far_y: float,
    initial_hp: float,
    retarget_hp: float,
    bot_mp: float,
    duration_s: float,
    step_s: float,
    release_log_start_index: int,
) -> list[dict[str, str]]:
    samples: list[dict[str, str]] = []
    deadline = time.time() + max(duration_s, 0.0)
    while time.time() < deadline:
        if boulder_completion_logged(bot_id=bot_id, log_start_index=release_log_start_index):
            break
        samples.append(
            set_dual_target_state(
                bot_id=bot_id,
                bot_actor_address=bot_actor_address,
                initial_actor_address=initial_actor_address,
                retarget_actor_address=retarget_actor_address,
                bot_x=bot_x,
                bot_y=bot_y,
                initial_x=initial_x,
                initial_y=initial_y,
                retarget_x=retarget_x,
                retarget_y=retarget_y,
                initial_far_x=initial_far_x,
                initial_far_y=initial_far_y,
                initial_hp=initial_hp,
                retarget_hp=retarget_hp,
                bot_mp=bot_mp,
                face_retarget=True,
            )
        )
        if boulder_completion_logged(bot_id=bot_id, log_start_index=release_log_start_index):
            break
        time.sleep(max(step_s, 0.03))
    return samples


def validate_release(
    *,
    native_validation: dict[str, object],
    initial_actor_address: int,
    retarget_actor_address: int,
    initial_x: float,
    initial_y: float,
    retarget_x: float,
    retarget_y: float,
    before_initial: dict[str, str],
    before_retarget: dict[str, str],
    after_initial: dict[str, str],
    after_retarget: dict[str, str],
    retarget_hp_expected: float,
    expected_boulder_object: int,
    loader_log_lines: list[str],
    release_log_start_index: int,
) -> dict[str, object]:
    failures: list[str] = []
    spawn = native_validation.get("native_projectile_spawn_validation")
    if not isinstance(spawn, dict):
        raise LiveBoulderRetargetProbeFailure("missing native projectile spawn validation")
    release = spawn.get("matching_release")
    complete = spawn.get("matching_complete")
    if not isinstance(release, dict):
        failures.append("missing native boulder release log")
        release = {}
    if not isinstance(complete, dict):
        failures.append("missing native boulder completion log")
        complete = {}

    release_target = as_int(release.get("target_actor"))
    completion_target = as_int(complete.get("release_target_actor"))
    requested_target = as_int(release.get("requested_target_actor"))
    release_reason = str(release.get("release_reason", ""))
    release_obj_ptr = as_int(release.get("obj_ptr"))
    completion_obj_ptr = as_int(complete.get("obj_ptr"))
    release_target_x = as_float(release.get("target_x"))
    release_target_y = as_float(release.get("target_y"))
    complete_x = as_float(complete.get("obj_x"))
    complete_y = as_float(complete.get("obj_y"))
    release_target_hp = as_float(release.get("target_hp"))
    requested_target_hp = as_float(release.get("requested_target_hp"))
    projected_hp_damage = as_float(release.get("projected_hp_damage"))
    target_distance = as_float(release.get("target_distance"))
    target_impact_radius = as_float(release.get("target_impact_radius"))
    target_in_impact = as_int(release.get("target_in_impact"))
    projection_target_in_impact = as_int(release.get("projection_target_in_impact"))
    completion_charge = as_float(complete.get("obj_charge"))
    completion_max_charge = as_float(complete.get("obj_max_charge"))
    completion_boulder_max_size = as_int(complete.get("boulder_max_size"), -1)
    initial_to_retarget_distance = math.hypot(retarget_x - initial_x, retarget_y - initial_y)
    boulder_object_to_retarget_distance = (
        math.hypot(complete_x - retarget_x, complete_y - retarget_y)
        if math.isfinite(complete_x) and math.isfinite(complete_y)
        else math.nan
    )

    if release_target != retarget_actor_address:
        failures.append(
            f"release target did not retarget: release_target=0x{release_target:X} "
            f"expected=0x{retarget_actor_address:X}"
        )
    if requested_target != retarget_actor_address:
        failures.append(
            f"live requested target was not re-evaluated after retarget: "
            f"requested_target=0x{requested_target:X} expected=0x{retarget_actor_address:X}"
        )
    if completion_target != retarget_actor_address:
        failures.append(
            f"completion target did not freeze retarget actor: release_target_actor=0x{completion_target:X} "
            f"expected=0x{retarget_actor_address:X}"
        )
    if release_obj_ptr == 0:
        failures.append("release log did not report a live Boulder object pointer")
    if completion_obj_ptr == 0:
        failures.append("completion log did not report a live Boulder object pointer")
    if release_obj_ptr != 0 and completion_obj_ptr != 0 and release_obj_ptr != completion_obj_ptr:
        failures.append(
            "release/completion did not use the same charged Boulder object: "
            f"release_obj=0x{release_obj_ptr:X} completion_obj=0x{completion_obj_ptr:X}"
        )
    if expected_boulder_object != 0 and release_obj_ptr != expected_boulder_object:
        failures.append(
            "release did not use the same charged Boulder object captured before retarget: "
            f"release_obj=0x{release_obj_ptr:X} expected=0x{expected_boulder_object:X}"
        )
    if release_reason != "target_lethal":
        failures.append(f"retarget release did not use target-lethal policy: {release_reason}")
    if (
        not math.isfinite(projected_hp_damage)
        or not math.isfinite(release_target_hp)
        or release_target_hp <= 0.0
        or projected_hp_damage + 0.001 < release_target_hp
    ):
        failures.append(
            "retarget target-lethal decision did not prove current Boulder damage covers current target HP: "
            f"projected_hp_damage={projected_hp_damage:.6f} target_hp={release_target_hp:.6f}"
        )
    if (
        not math.isfinite(requested_target_hp)
        or abs(requested_target_hp - retarget_hp_expected) > 0.01
    ):
        failures.append(
            "requested target HP was not the retarget's controlled current HP: "
            f"requested_target_hp={requested_target_hp:.6f} expected={retarget_hp_expected:.6f}"
        )
    if (
        not math.isfinite(release_target_hp)
        or abs(release_target_hp - retarget_hp_expected) > 0.01
    ):
        failures.append(
            "release target HP was not the retarget's controlled current HP: "
            f"target_hp={release_target_hp:.6f} expected={retarget_hp_expected:.6f}"
        )
    if completion_boulder_max_size != 0:
        failures.append(
            "target-lethal retarget release still completed as a max-size Boulder: "
            f"boulder_max_size={completion_boulder_max_size}"
        )
    if (
        math.isfinite(completion_charge)
        and math.isfinite(completion_max_charge)
        and completion_charge >= completion_max_charge - 0.001
    ):
        failures.append(
            "target-lethal retarget release kept charging to native max size: "
            f"charge={completion_charge:.6f} max={completion_max_charge:.6f}"
        )
    coordinate_tolerance = (
        max(3.0, min(target_impact_radius, 24.0))
        if math.isfinite(target_impact_radius)
        else 3.0
    )
    if (
        not close_enough(release_target_x, retarget_x, coordinate_tolerance) or
        not close_enough(release_target_y, retarget_y, coordinate_tolerance)
    ):
        failures.append(
            "release target coordinates did not follow retarget actor: "
            f"release=({release_target_x:.2f}, {release_target_y:.2f}) "
            f"expected=({retarget_x:.2f}, {retarget_y:.2f}) "
            f"tolerance={coordinate_tolerance:.2f}"
        )
    if not math.isfinite(target_distance):
        failures.append("release did not report a finite retarget distance")
    initial_hp_before = as_float(before_initial.get("hp"))
    initial_hp_after = as_float(after_initial.get("hp"))
    retarget_available_after = after_retarget.get("available") == "true"
    retarget_hp_before = as_float(before_retarget.get("hp"))
    retarget_hp_after = as_float(after_retarget.get("hp"))
    retarget_dead_after = after_retarget.get("dead") == "true"
    retarget_removed = before_retarget.get("available") == "true" and not retarget_available_after
    retarget_hp_decreased = (
        math.isfinite(retarget_hp_before)
        and math.isfinite(retarget_hp_after)
        and retarget_hp_after < retarget_hp_before
    )
    initial_death_lines = find_enemy_death_lines(
        loader_log_lines,
        actor_address=initial_actor_address,
        log_start_index=release_log_start_index,
    )
    retarget_death_lines = find_enemy_death_lines(
        loader_log_lines,
        actor_address=retarget_actor_address,
        log_start_index=release_log_start_index,
    )
    retarget_death_logged = bool(retarget_death_lines)
    retarget_impact_observed = (
        retarget_removed or
        retarget_dead_after or
        retarget_hp_decreased or
        retarget_death_logged
    )
    if initial_death_lines:
        failures.append(
            "initial target died after the bot swapped targets: " +
            " | ".join(initial_death_lines[-3:])
        )
    if (
        after_initial.get("available") == "true" and
        math.isfinite(initial_hp_before) and
        math.isfinite(initial_hp_after) and
        initial_hp_after < initial_hp_before - 0.01
    ):
        failures.append(
            "initial target was damaged after the bot swapped targets: "
            f"before={initial_hp_before} after={initial_hp_after}"
        )

    if failures:
        raise LiveBoulderRetargetProbeFailure("; ".join(failures))

    return {
        "release": release,
        "completion": complete,
        "boulder_object": release_obj_ptr,
        "completion_boulder_object": completion_obj_ptr,
        "expected_boulder_object": expected_boulder_object,
        "release_target_actor": release_target,
        "requested_target_actor": requested_target,
        "completion_release_target_actor": completion_target,
        "release_reason": release_reason,
        "projected_hp_damage": projected_hp_damage,
        "release_target_hp": release_target_hp,
        "requested_target_hp": requested_target_hp,
        "retarget_hp_expected": retarget_hp_expected,
        "initial_to_retarget_distance": initial_to_retarget_distance,
        "release_target_distance": target_distance,
        "release_target_in_impact": target_in_impact,
        "projection_target_in_impact": projection_target_in_impact,
        "target_impact_radius": target_impact_radius,
        "coordinate_tolerance": coordinate_tolerance,
        "completion_charge": completion_charge,
        "completion_max_charge": completion_max_charge,
        "completion_boulder_max_size": completion_boulder_max_size,
        "boulder_object_to_retarget_distance": boulder_object_to_retarget_distance,
        "initial_target_after": after_initial,
        "retarget_after": after_retarget,
        "retarget_removed": retarget_removed,
        "retarget_dead_after": retarget_dead_after,
        "retarget_hp_decreased": retarget_hp_decreased,
        "retarget_death_logged": retarget_death_logged,
        "retarget_impact_observed": retarget_impact_observed,
        "retarget_death_lines": retarget_death_lines[-3:],
        "initial_death_lines": initial_death_lines[-3:],
    }


def run_probe(args: argparse.Namespace) -> dict[str, object]:
    result: dict[str, object] = {
        "passed": False,
        "scenario": "earth_boulder_held_charge_retarget",
    }
    hostile_hp_watch_names: list[str] = []
    native_trace_names: list[tuple[str, int]] = []
    try:
        result["launcher_freshness"] = csp.ensure_launcher_bundle_fresh()
        result["navigation"] = element_probe.prepare_clean_run(args.player_element, args.discipline)
        if args.trace_native_hit_path:
            trace_arms, native_trace_names = element_probe.arm_native_hit_path_traces("earth")
            result["native_hit_path_trace_arms"] = trace_arms
        player = csp.query_player_state()
        bot_id = element_probe.create_single_run_bot("earth", player, args.bot_x, args.bot_y)
        bot = element_probe.wait_for_bot_by_id(bot_id)
        crc.stop_bot(str(bot_id))
        bot_actor = csp.int_value(bot, "actor_address")
        result["bot"] = bot
        wave.sustain_probe_health()
        waves = csp.parse_key_values(csp.run_lua("print('ok='..tostring(sd.gameplay.start_waves()))"))
        if waves.get("ok") != "true":
            raise LiveBoulderRetargetProbeFailure(f"sd.gameplay.start_waves failed: {waves}")
        result["navigation"]["waves"] = waves
        time.sleep(element_probe.POST_COMBAT_PRELUDE_SETTLE_SECONDS)
        wave.sustain_probe_health()
        hostiles = wait_for_two_hostiles(bot_actor, limit=args.enemy_watch_count, timeout_s=30.0)
        initial_actor = int(hostiles[0]["actor_address"])
        retarget_actor = int(hostiles[1]["actor_address"])
        initial_x = args.bot_x + 45.5
        initial_y = args.bot_y + 5.0
        retarget_x = args.bot_x + 20.0
        retarget_y = args.bot_y + 38.0
        initial_far_x = args.bot_x + 320.0
        initial_far_y = args.bot_y + 320.0

        result["targets"] = {
            "initial_actor": initial_actor,
            "retarget_actor": retarget_actor,
            "initial_contact": {"x": initial_x, "y": initial_y},
            "retarget_contact": {"x": retarget_x, "y": retarget_y},
            "initial_far": {"x": initial_far_x, "y": initial_far_y},
        }
        result["initial_setup"] = set_dual_target_state(
            bot_id=bot_id,
            bot_actor_address=bot_actor,
            initial_actor_address=initial_actor,
            retarget_actor_address=retarget_actor,
            bot_x=args.bot_x,
            bot_y=args.bot_y,
            initial_x=initial_x,
            initial_y=initial_y,
            retarget_x=retarget_x,
            retarget_y=retarget_y,
            initial_far_x=initial_far_x,
            initial_far_y=initial_far_y,
            initial_hp=args.initial_hp,
            retarget_hp=args.retarget_hp,
            bot_mp=args.bot_mp,
            face_retarget=False,
        )
        before_initial = element_probe.query_scene_actor_by_address(initial_actor)
        if before_initial.get("available") != "true":
            raise LiveBoulderRetargetProbeFailure(
                f"initial target was not available before cast: initial={before_initial}"
            )

        cast = crc.queue_direct_primary_cast(
            str(bot_id),
            str(initial_actor),
            initial_x,
            initial_y,
        )
        result["cast"] = cast
        if cast.get("ok") != "true":
            raise LiveBoulderRetargetProbeFailure(f"sd.bots.cast failed: {cast}")
        release_log_start_index = len(element_probe.read_loader_log_lines())
        active_boulder = wait_for_active_boulder_object(bot_id=bot_id, timeout_s=5.0)
        result["active_boulder_before_retarget"] = active_boulder
        retarget_x = as_float(active_boulder.get("active_spell_object_x"))
        retarget_y = as_float(active_boulder.get("active_spell_object_y"))
        if not math.isfinite(retarget_x) or not math.isfinite(retarget_y):
            raise LiveBoulderRetargetProbeFailure(
                f"active Boulder object did not report a finite impact center: {active_boulder}"
            )
        result["targets"]["retarget_contact"] = {"x": retarget_x, "y": retarget_y}
        result["targets"]["retarget_contact_source"] = "active_boulder_object"
        time.sleep(max(args.retarget_delay, 0.0))
        live_retarget = choose_live_retarget_hostile(
            bot_actor,
            initial_actor,
            limit=args.enemy_watch_count,
            timeout_s=5.0,
        )
        retarget_actor = int(live_retarget["actor_address"])
        result["targets"]["retarget_actor"] = retarget_actor
        result["targets"]["retarget_source"] = "live_at_retarget"
        before_retarget = element_probe.query_scene_actor_by_address(retarget_actor)
        if before_retarget.get("available") != "true":
            raise LiveBoulderRetargetProbeFailure(
                f"retarget was not available at target swap: retarget={before_retarget}"
            )
        if args.force_hostile_hp_watches:
            watched_hostiles = [dict(hostiles[0]), dict(live_retarget)]
            result["hostile_hp_watches"] = element_probe.arm_hostile_hp_watches("earth_retarget", watched_hostiles)
            hostile_hp_watch_names = list(result["hostile_hp_watches"].keys())
        result["retarget_samples"] = pin_retarget_window(
            bot_id=bot_id,
            bot_actor_address=bot_actor,
            initial_actor_address=initial_actor,
            retarget_actor_address=retarget_actor,
            bot_x=args.bot_x,
            bot_y=args.bot_y,
            initial_x=initial_x,
            initial_y=initial_y,
            retarget_x=retarget_x,
            retarget_y=retarget_y,
            initial_far_x=initial_far_x,
            initial_far_y=initial_far_y,
            initial_hp=args.initial_hp,
            retarget_hp=args.retarget_hp,
            bot_mp=args.bot_mp,
            duration_s=args.pin_seconds,
            step_s=args.pin_step,
            release_log_start_index=release_log_start_index,
        )
        time.sleep(max(args.settle_seconds, 0.0))
        full_loader_log = element_probe.read_loader_log_lines()
        native_validation = element_probe.build_native_spell_stat_validation(
            "earth",
            bot,
            bot_id,
            full_loader_log,
        )
        after_initial = element_probe.query_scene_actor_by_address(initial_actor)
        after_retarget = element_probe.query_scene_actor_by_address(retarget_actor)
        result["native_spell_stat_validation"] = native_validation
        if native_trace_names:
            result["native_hit_path_trace_hits"] = {
                name: element_probe.query_trace_hits(name)
                for name, _address in native_trace_names
            }
        result["after_initial"] = after_initial
        result["after_retarget"] = after_retarget
        result["evidence"] = validate_release(
            native_validation=native_validation,
            initial_actor_address=initial_actor,
            retarget_actor_address=retarget_actor,
            initial_x=initial_x,
            initial_y=initial_y,
            retarget_x=retarget_x,
            retarget_y=retarget_y,
            before_initial=before_initial,
            before_retarget=before_retarget,
            after_initial=after_initial,
            after_retarget=after_retarget,
            retarget_hp_expected=args.retarget_hp,
            expected_boulder_object=as_int(active_boulder.get("active_spell_object_address")),
            loader_log_lines=full_loader_log,
            release_log_start_index=release_log_start_index,
        )
        result["passed"] = True
        return result
    except Exception as exc:  # noqa: BLE001 - retain partial live evidence.
        result["error"] = str(exc)
        return result
    finally:
        if hostile_hp_watch_names:
            element_probe.clear_hostile_hp_watches(hostile_hp_watch_names)
        for name, address in native_trace_names:
            element_probe.clear_trace(name, address)
        if not args.keep_running:
            csp.stop_game()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--keep-running", action="store_true")
    parser.add_argument("--player-element", choices=sorted(csp.CREATE_ELEMENT_CENTERS), default="ether")
    parser.add_argument("--discipline", choices=sorted(csp.CREATE_DISCIPLINE_CENTERS), default="mind")
    parser.add_argument("--bot-x", type=float, default=914.0)
    parser.add_argument("--bot-y", type=float, default=150.0)
    parser.add_argument("--bot-mp", type=float, default=500.0)
    parser.add_argument("--initial-hp", type=float, default=25000.0)
    parser.add_argument("--retarget-hp", type=float, default=2.5)
    parser.add_argument("--enemy-watch-count", type=int, default=24)
    parser.add_argument("--retarget-delay", type=float, default=0.10)
    parser.add_argument("--pin-seconds", type=float, default=18.0)
    parser.add_argument("--pin-step", type=float, default=0.20)
    parser.add_argument("--settle-seconds", type=float, default=3.0)
    parser.add_argument("--force-hostile-hp-watches", action="store_true")
    parser.add_argument("--trace-native-hit-path", action="store_true")
    args = parser.parse_args()

    exit_code = 0
    try:
        result = run_probe(args)
    except Exception as exc:  # noqa: BLE001 - preserve live diagnostics in JSON.
        exit_code = 1
        result = {
            "passed": False,
            "scenario": "earth_boulder_held_charge_retarget",
            "error": str(exc),
        }
    if not result.get("passed"):
        exit_code = 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    elif result.get("passed"):
        evidence = result["evidence"]
        print(
            "PASS: Earth Boulder retarget "
            f"release_target=0x{as_int(evidence.get('release_target_actor')):X} "
            f"reason={evidence.get('release_reason')}"
        )
        print(f"Wrote {args.output}")
    else:
        print(f"FAIL: Earth Boulder retarget probe: {result.get('error')}")
        print(f"Wrote {args.output}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
