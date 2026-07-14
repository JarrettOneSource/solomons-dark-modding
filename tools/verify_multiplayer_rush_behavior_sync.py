#!/usr/bin/env python3
"""Verify native Rush movement behavior and position replication both ways."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from multiplayer_progression_probe import (
    query_progression_snapshot,
    query_ranked_numeric_stat,
)
from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_NAME,
    CLIENT_PIPE,
    HOST_ID,
    HOST_NAME,
    HOST_PIPE,
    VerifyFailure,
    disable_bots,
    distance,
    launch_pair,
    lua,
    parse_int_text,
    parse_key_values,
    place_player,
    start_host_testrun_and_wait_for_clients,
    stop_games,
    wait_for_local_transform_settled,
    wait_for_remote,
    wait_for_remote_convergence,
)
from verify_multiplayer_all_upgrade_sync import (
    FLAT_BONEYARD,
    choose_offer,
    enable_quiet_progression_test_mode,
    new_crash_artifacts,
    publish_deterministic_offer,
    wait_for_offer,
    wait_for_pause,
    wait_for_post_run_progression_ready,
    wait_for_result,
    wait_for_target_parity,
)


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "runtime/multiplayer_rush_behavior_sync.json"
NATIVE_RUSH_EVIDENCE = ROOT / "runtime/live_bot_native_speed_probe.json"
RELEASE_LOADER = ROOT / "bin/Release/Win32/SolomonDarkModLoader.dll"
SEND_WINDOW_KEYS = ROOT / "scripts/send_window_keys.py"
RUSH_ROW = 67
RUSH_MAX_RANK = 8
RUSH_MAX_SPEED_PERCENT = 50.0
RUSH_MAX_SPEED_MULTIPLIER = 1.0 + RUSH_MAX_SPEED_PERCENT / 100.0
CONCENTRATE_SPEED_PERCENT = 25.0
CONCENTRATE_SPEED_MULTIPLIER = 1.0 + CONCENTRATE_SPEED_PERCENT / 100.0
COMBINED_MAX_SPEED_MULTIPLIER = (
    RUSH_MAX_SPEED_MULTIPLIER * CONCENTRATE_SPEED_MULTIPLIER
)
RUSH_BATCH_SIZE = 2
DRIVE_TICKS = 40
KEYBOARD_HOLD_MS = 2200
START_X = 621.5
START_Y = 3512.1
PARK_X = 1500.0
PARK_Y = 3300.0


@dataclass(frozen=True)
class Direction:
    name: str
    participant_id: int
    owner_pipe: str
    observer_pipe: str
    other_pipe: str


DIRECTIONS = (
    Direction("host_owned", HOST_ID, HOST_PIPE, CLIENT_PIPE, CLIENT_PIPE),
    Direction("client_owned", CLIENT_ID, CLIENT_PIPE, HOST_PIPE, HOST_PIPE),
)


def parse_float_text(value: str | None, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def windows_path(path: Path) -> str:
    completed = subprocess.run(
        ["wslpath", "-w", str(path)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=5.0,
        check=False,
    )
    if completed.returncode != 0:
        raise VerifyFailure(f"wslpath failed for {path}: {completed.stdout}")
    return completed.stdout.strip()


def hold_real_key(pid: int, key: str, hold_ms: int, timeout: float) -> str:
    script = windows_path(SEND_WINDOW_KEYS)
    command = (
        f"py -3 {json.dumps(script)} --pid {pid} --activate "
        f"--activation-delay-ms 300 --hold-ms {hold_ms} --post-delay-ms 100 {key}"
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        raise VerifyFailure(
            f"real keyboard helper failed for pid {pid} ({completed.returncode}): "
            f"{completed.stdout}"
        )
    return completed.stdout.strip()


def load_native_rush_evidence(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise VerifyFailure(f"native Rush evidence is missing: {path}")
    if not RELEASE_LOADER.is_file():
        raise VerifyFailure(f"Release loader is missing: {RELEASE_LOADER}")

    evidence = json.loads(path.read_text(encoding="utf-8"))
    behavior = evidence.get("rush_behavior") or {}
    application = evidence.get("rush_application") or {}
    fresh_bundle = evidence.get("fresh_bundle") or {}
    native_globals = evidence.get("native_globals") or {}
    native_global_values = {
        "input_acceleration_divisor": float(
            native_globals.get("input_acceleration_divisor", math.nan)
        ),
        "speed_scalar": float(native_globals.get("speed_scalar", math.nan)),
        "velocity_damping": float(
            native_globals.get("velocity_damping", math.nan)
        ),
    }
    checks = {
        "probe_passed": evidence.get("passed") is True,
        "fresh_bundle_matched": fresh_bundle.get("matches") is True,
        "release_loader_hash_matched": (
            fresh_bundle.get("release_hash") == sha256_file(RELEASE_LOADER)
        ),
        "selected_native_rush": application.get("matched_rush") is True,
        "baseline_rank_zero": behavior.get("baseline_rank") == 0,
        "post_rush_rank_one": behavior.get("post_rush_rank") == 1,
        "native_percent_ten": math.isclose(
            float(behavior.get("native_speed_percent", math.nan)),
            10.0,
            rel_tol=0.0,
            abs_tol=0.001,
        ),
        "native_multiplier_1_1": math.isclose(
            float(behavior.get("native_speed_multiplier", math.nan)),
            1.1,
            rel_tol=0.0,
            abs_tol=0.001,
        ),
        "native_cap_ratio_1_1": math.isclose(
            float(behavior.get("cap_ratio", math.nan)),
            1.1,
            rel_tol=0.0,
            abs_tol=0.003,
        ),
        "native_peak_velocity_ratio_1_1": math.isclose(
            float(behavior.get("peak_velocity_ratio", math.nan)),
            1.1,
            rel_tol=0.0,
            abs_tol=0.003,
        ),
        "native_acceleration_divisor_valid": (
            math.isfinite(native_global_values["input_acceleration_divisor"])
            and native_global_values["input_acceleration_divisor"] > 0.0
        ),
        "native_speed_scalar_valid": (
            math.isfinite(native_global_values["speed_scalar"])
            and native_global_values["speed_scalar"] > 0.0
        ),
        "native_velocity_damping_valid": (
            math.isfinite(native_global_values["velocity_damping"])
            and 0.0 < native_global_values["velocity_damping"] < 1.0
        ),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise VerifyFailure(
            f"native Rush evidence failed checks {failed}: {path}"
        )
    try:
        evidence_path = str(path.resolve().relative_to(ROOT))
    except ValueError:
        evidence_path = str(path.resolve())
    return {
        "path": evidence_path,
        "checks": checks,
        "rush_behavior": behavior,
        "native_globals": native_global_values,
        "release_loader_hash": fresh_bundle["release_hash"],
    }


def expected_native_post_tick_peak_velocity(
    runtime: dict[str, str],
    rush_multiplier: float,
    native_globals: dict[str, float],
) -> float:
    actor_multiplier = parse_float_text(
        runtime.get("actor_movement_speed_multiplier"), math.nan
    )
    actor_scale = parse_float_text(runtime.get("actor_move_speed_scale"), math.nan)
    progression_speed = parse_float_text(
        runtime.get("progression_move_speed"), math.nan
    )
    acceleration_divisor = native_globals["input_acceleration_divisor"]
    speed_scalar = native_globals["speed_scalar"]
    damping = native_globals["velocity_damping"]
    speed_cap = (
        actor_multiplier
        * actor_scale
        * progression_speed
        * rush_multiplier
        * speed_scalar
    )
    unconstrained_pre_damping_peak = (1.0 / acceleration_divisor) / (1.0 - damping)
    peak = min(speed_cap, unconstrained_pre_damping_peak) * damping
    if not math.isfinite(peak) or peak <= 0.0:
        raise VerifyFailure(
            "invalid expected native keyboard velocity envelope: "
            f"runtime={runtime} rush_multiplier={rush_multiplier} "
            f"native_globals={native_globals}"
        )
    return peak


def apply_rush_batch(
    target_id: int,
    expected_active: int,
    timeout: float,
) -> dict[str, Any]:
    target_pipe = HOST_PIPE if target_id == HOST_ID else CLIENT_PIPE
    before = query_progression_snapshot(target_pipe)
    before_active = int(before["native"]["entries"][RUSH_ROW]["active"])
    if before_active + RUSH_BATCH_SIZE != expected_active:
        raise VerifyFailure(
            f"unexpected Rush batch start target={target_id}: "
            f"active={before_active} expected_next={expected_active}"
        )
    target_level = int(before["native"]["level"]) + 1
    target_experience = int(math.ceil(before["native"]["next_xp_threshold"]))

    publish = publish_deterministic_offer(
        target_id,
        target_level,
        target_experience,
        RUSH_ROW,
        RUSH_BATCH_SIZE,
    )
    offer = wait_for_offer(
        target_pipe,
        target_id,
        target_level,
        RUSH_ROW,
        timeout,
        RUSH_BATCH_SIZE,
    )
    pause_active = wait_for_pause(target_id, True, timeout)
    choice = choose_offer(target_pipe, offer["offer_id"], RUSH_ROW)
    result = wait_for_result(
        offer["offer_id"],
        target_id,
        target_level,
        RUSH_ROW,
        expected_active,
        timeout,
        RUSH_BATCH_SIZE,
    )
    parity = wait_for_target_parity(
        target_id,
        RUSH_ROW,
        expected_active,
        target_level,
        timeout,
    )
    pause_cleared = wait_for_pause(target_id, False, timeout)
    return {
        "target_participant_id": target_id,
        "before_active": before_active,
        "resulting_active": expected_active,
        "target_level": target_level,
        "publish": publish,
        "offer": offer,
        "pause_active": pause_active,
        "choice": choice,
        "result": result,
        "parity": parity,
        "pause_cleared": pause_cleared,
    }


def apply_rush_to_max(target_id: int, timeout: float) -> list[dict[str, Any]]:
    return [
        apply_rush_batch(target_id, expected_active, timeout)
        for expected_active in range(RUSH_BATCH_SIZE, RUSH_MAX_RANK + 1, RUSH_BATCH_SIZE)
    ]


def configure_native_movement_drive(pipe_name: str, ticks: int) -> dict[str, str]:
    code = f"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
if not _G.__sdmod_mp_rush_drive_registered then
  sd.events.on('runtime.tick', function()
    local drive = _G.__sdmod_mp_rush_drive
    if type(drive) ~= 'table' then return end
    local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
    local actor = player and tonumber(player.actor_address) or 0
    if actor == 0 or sd.input == nil or sd.input.hold_movement_frames == nil then
      drive.error = 'native movement input unavailable'
      drive.remaining = 0
      drive.cleared = true
      return
    end
    if drive.remaining > 0 then
      local vx = tonumber(sd.debug.read_float(
        actor + sd.debug.layout_offset('actor_animation_config_block'))) or 0
      local vy = tonumber(sd.debug.read_float(
        actor + sd.debug.layout_offset('actor_animation_drive_parameter'))) or 0
      local speed = math.sqrt(vx * vx + vy * vy)
      drive.peak_velocity = math.max(drive.peak_velocity, speed)
      local ok, result = pcall(sd.input.hold_movement_frames, drive.x, drive.y, 1)
      drive.write_ok = ok and result == true
      if not drive.write_ok then
        drive.error = tostring(result)
        drive.remaining = 0
        drive.cleared = true
        return
      end
      drive.remaining = drive.remaining - 1
      drive.applied = drive.applied + 1
      if drive.first_x == nil then
        drive.first_x = tonumber(player.x)
        drive.first_y = tonumber(player.y)
      end
      drive.last_x = tonumber(player.x)
      drive.last_y = tonumber(player.y)
      return
    end
    if not drive.cleared then
      drive.clear_ok = true
      drive.cleared = true
    end
  end)
  _G.__sdmod_mp_rush_drive_registered = true
end
_G.__sdmod_mp_rush_drive = {{
  remaining = {ticks},
  applied = 0,
  x = 1.0,
  y = 0.0,
  write_ok = true,
  clear_ok = false,
  cleared = false,
  peak_velocity = 0.0,
  error = '',
}}
emit('registered', _G.__sdmod_mp_rush_drive_registered)
emit('requested', {ticks})
"""
    values = parse_key_values(lua(pipe_name, code, timeout=8.0))
    if values.get("registered") != "true":
        raise VerifyFailure(f"failed to register native movement drive: {values}")
    return values


def query_native_movement_drive(pipe_name: str) -> dict[str, str]:
    code = """
local function emit(key, value)
  print(key .. '=' .. tostring(value == nil and '' or value))
end
local drive = _G.__sdmod_mp_rush_drive or {}
for _, key in ipairs({
  'remaining','applied','write_ok','clear_ok','cleared','error',
  'first_x','first_y','last_x','last_y','peak_velocity'
}) do emit(key, drive[key]) end
"""
    return parse_key_values(lua(pipe_name, code, timeout=8.0))


def wait_for_native_movement_drive(
    pipe_name: str,
    ticks: int,
    timeout: float,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = query_native_movement_drive(pipe_name)
        if last.get("error"):
            raise VerifyFailure(f"native movement drive failed: {last}")
        if (
            parse_int_text(last.get("remaining"), -1) == 0
            and parse_int_text(last.get("applied"), -1) == ticks
            and last.get("write_ok") == "true"
            and last.get("clear_ok") == "true"
            and last.get("cleared") == "true"
        ):
            return last
        time.sleep(0.05)
    raise VerifyFailure(f"native movement drive timed out on {pipe_name}: {last}")


def query_native_movement_runtime(pipe_name: str) -> dict[str, str]:
    code = """
local function emit(key, value)
  print(key .. '=' .. tostring(value == nil and '' or value))
end
local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
local actor = player and tonumber(player.actor_address) or 0
local world = player and tonumber(player.world_address) or 0
local scene = sd.world and sd.world.get_scene and sd.world.get_scene() or nil
local gameplay = scene and tonumber(scene.id) or 0
local progression = player and tonumber(
  player.progression_address or player.progression_runtime_state_address) or 0
local function off(name) return sd.debug.layout_offset(name) end
emit('actor', actor)
emit('world', world)
emit('gameplay', gameplay)
emit('progression', progression)
emit('x', player and player.x)
emit('y', player and player.y)
emit('heading', player and player.heading)
if actor ~= 0 then
  emit('actor_move_speed_scale', sd.debug.read_float(actor + off('actor_move_speed_scale')))
  emit('actor_movement_speed_multiplier', sd.debug.read_float(actor + off('actor_movement_speed_multiplier')))
  emit('actor_vector_x', sd.debug.read_float(actor + off('actor_animation_config_block')))
  emit('actor_vector_y', sd.debug.read_float(actor + off('actor_animation_drive_parameter')))
end
if gameplay ~= 0 then
  emit('input_x', sd.debug.read_float(gameplay + off('gameplay_local_movement_input_x')))
  emit('input_y', sd.debug.read_float(gameplay + off('gameplay_local_movement_input_y')))
end
if progression ~= 0 then
  local vtable = tonumber(sd.debug.read_u32(progression)) or 0
  emit('vtable', vtable)
  emit('movement_tick_method', vtable ~= 0 and sd.debug.read_u32(vtable + 0x6c) or 0)
  emit('progression_move_speed', sd.debug.read_float(progression + off('progression_move_speed')))
end
"""
    return parse_key_values(lua(pipe_name, code, timeout=8.0))


def run_movement_trial(direction: Direction, label: str, timeout: float) -> dict[str, Any]:
    place_player(direction.other_pipe, PARK_X, PARK_Y, 180.0)
    placement = place_player(direction.owner_pipe, START_X, START_Y, 0.0)
    start_x, start_y, start_heading = wait_for_local_transform_settled(
        direction.owner_pipe,
        timeout=min(timeout, 10.0),
        stable_seconds=0.35,
    )
    wait_for_remote_convergence(
        direction.observer_pipe,
        direction.participant_id,
        start_x,
        start_y,
        start_heading,
        timeout=timeout,
    )
    before_runtime = query_native_movement_runtime(direction.owner_pipe)
    drive_start = configure_native_movement_drive(
        direction.owner_pipe,
        DRIVE_TICKS,
    )
    drive_result = wait_for_native_movement_drive(
        direction.owner_pipe,
        DRIVE_TICKS,
        timeout,
    )
    settled_x, settled_y, settled_heading = wait_for_local_transform_settled(
        direction.owner_pipe,
        timeout=min(timeout, 10.0),
        stable_seconds=0.6,
    )
    observer = wait_for_remote_convergence(
        direction.observer_pipe,
        direction.participant_id,
        settled_x,
        settled_y,
        settled_heading,
        timeout=timeout,
    )
    prefix = f"peer.{direction.participant_id}."
    observer_x = parse_float_text(observer.get(prefix + "x"), math.nan)
    observer_y = parse_float_text(observer.get(prefix + "y"), math.nan)
    displacement = distance(start_x, start_y, settled_x, settled_y)
    forward_displacement = settled_x - start_x
    cross_axis_displacement = abs(settled_y - start_y)
    if not math.isfinite(displacement) or displacement <= 5.0:
        raise VerifyFailure(
            f"{direction.name} {label} native movement was too small: "
            f"start=({start_x},{start_y}) final=({settled_x},{settled_y})"
        )
    if forward_displacement <= 5.0 or cross_axis_displacement > 5.0:
        raise VerifyFailure(
            f"{direction.name} {label} movement left the flat measurement lane: "
            f"forward={forward_displacement} cross_axis={cross_axis_displacement}"
        )
    return {
        "direction": direction.name,
        "label": label,
        "placement": placement,
        "drive_start": drive_start,
        "drive_result": drive_result,
        "before_runtime": before_runtime,
        "after_runtime": query_native_movement_runtime(direction.owner_pipe),
        "requested_start": {"x": START_X, "y": START_Y},
        "start": {"x": start_x, "y": start_y, "heading": start_heading},
        "final": {
            "x": settled_x,
            "y": settled_y,
            "heading": settled_heading,
        },
        "displacement": displacement,
        "forward_displacement": forward_displacement,
        "cross_axis_displacement": cross_axis_displacement,
        "peak_velocity": parse_float_text(
            drive_result.get("peak_velocity"),
            math.nan,
        ),
        "observer": {
            "x": observer_x,
            "y": observer_y,
            "position_error": distance(settled_x, settled_y, observer_x, observer_y),
        },
    }


def arm_keyboard_movement_monitor(pipe_name: str) -> dict[str, str]:
    code = """
local function emit(key, value) print(key .. '=' .. tostring(value)) end
if not _G.__sdmod_mp_rush_keyboard_monitor_registered then
  sd.events.on('runtime.tick', function()
    local trial = _G.__sdmod_mp_rush_keyboard_trial
    if type(trial) ~= 'table' or not trial.active then return end
    local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
    local actor = player and tonumber(player.actor_address) or 0
    local scene = sd.world and sd.world.get_scene and sd.world.get_scene() or nil
    local gameplay = scene and tonumber(scene.id) or 0
    if actor == 0 or gameplay == 0 then return end
    local function off(name) return sd.debug.layout_offset(name) end
    local vx = tonumber(sd.debug.read_float(
      actor + off('actor_animation_config_block'))) or 0
    local vy = tonumber(sd.debug.read_float(
      actor + off('actor_animation_drive_parameter'))) or 0
    local input_x = tonumber(sd.debug.read_float(
      gameplay + off('gameplay_local_movement_input_x'))) or 0
    local input_y = tonumber(sd.debug.read_float(
      gameplay + off('gameplay_local_movement_input_y'))) or 0
    local selection = tonumber(sd.debug.read_u32(
      actor + off('actor_animation_selection_state'))) or 0
    local control_x = selection ~= 0 and tonumber(sd.debug.read_float(
      selection + off('actor_control_brain_move_input_x'))) or 0
    local control_y = selection ~= 0 and tonumber(sd.debug.read_float(
      selection + off('actor_control_brain_move_input_y'))) or 0
    local speed = math.sqrt(vx * vx + vy * vy)
    local input_magnitude = math.sqrt(input_x * input_x + input_y * input_y)
    local control_magnitude = math.sqrt(control_x * control_x + control_y * control_y)
    trial.samples = trial.samples + 1
    trial.peak_velocity = math.max(trial.peak_velocity, speed)
    trial.peak_input = math.max(trial.peak_input, input_magnitude)
    trial.peak_control = math.max(trial.peak_control, control_magnitude)
    trial.min_x = math.min(trial.min_x, tonumber(player.x) or trial.min_x)
    trial.max_x = math.max(trial.max_x, tonumber(player.x) or trial.max_x)
    trial.min_y = math.min(trial.min_y, tonumber(player.y) or trial.min_y)
    trial.max_y = math.max(trial.max_y, tonumber(player.y) or trial.max_y)
    if input_magnitude > 0.01 then
      trial.input_frames = trial.input_frames + 1
    end
  end)
  _G.__sdmod_mp_rush_keyboard_monitor_registered = true
end
_G.__sdmod_mp_rush_keyboard_trial = {
  active = true,
  samples = 0,
  input_frames = 0,
  peak_input = 0.0,
  peak_control = 0.0,
  peak_velocity = 0.0,
  min_x = math.huge,
  max_x = -math.huge,
  min_y = math.huge,
  max_y = -math.huge,
}
local allowance_ok, allowance_result = pcall(
  sd.input.set_native_control_allowance_frames, 3600)
emit('registered', _G.__sdmod_mp_rush_keyboard_monitor_registered)
emit('active', _G.__sdmod_mp_rush_keyboard_trial.active)
emit('allowance_ok', allowance_ok and allowance_result == true)
"""
    result = parse_key_values(lua(pipe_name, code, timeout=8.0))
    if (
        result.get("registered") != "true"
        or result.get("active") != "true"
        or result.get("allowance_ok") != "true"
    ):
        raise VerifyFailure(f"failed to arm real keyboard movement monitor: {result}")
    return result


def finish_keyboard_movement_monitor(pipe_name: str) -> dict[str, str]:
    code = """
local function emit(key, value)
  print(key .. '=' .. tostring(value == nil and '' or value))
end
local trial = _G.__sdmod_mp_rush_keyboard_trial or {}
trial.active = false
local allowance_ok, allowance_result = pcall(
  sd.input.set_native_control_allowance_frames, 0)
for _, key in ipairs({
  'samples','input_frames','peak_input','peak_control','peak_velocity',
  'min_x','max_x','min_y','max_y'
}) do
  emit(key, trial[key])
end
emit('active', trial.active)
emit('allowance_cleared', allowance_ok and allowance_result == true)
"""
    result = parse_key_values(lua(pipe_name, code, timeout=8.0))
    if result.get("active") != "false":
        raise VerifyFailure(f"failed to stop real keyboard movement monitor: {result}")
    if result.get("allowance_cleared") != "true":
        raise VerifyFailure(f"failed to clear native control allowance: {result}")
    if parse_int_text(result.get("samples"), 0) <= 0:
        raise VerifyFailure(f"real keyboard movement monitor captured no samples: {result}")
    if parse_int_text(result.get("input_frames"), 0) <= 0:
        raise VerifyFailure(f"stock gameplay never observed held keyboard input: {result}")
    return result


def run_real_keyboard_movement_trial(
    direction: Direction,
    pid: int,
    label: str,
    timeout: float,
) -> dict[str, Any]:
    place_player(direction.other_pipe, PARK_X, PARK_Y, 180.0)
    placement = place_player(direction.owner_pipe, START_X, START_Y, 0.0)
    start_x, start_y, start_heading = wait_for_local_transform_settled(
        direction.owner_pipe,
        timeout=min(timeout, 10.0),
        stable_seconds=0.45,
    )
    wait_for_remote_convergence(
        direction.observer_pipe,
        direction.participant_id,
        start_x,
        start_y,
        start_heading,
        timeout=timeout,
    )
    before_runtime = query_native_movement_runtime(direction.owner_pipe)
    monitor_start = arm_keyboard_movement_monitor(direction.owner_pipe)
    key_output = hold_real_key(pid, "d", KEYBOARD_HOLD_MS, timeout)
    settled_x, settled_y, settled_heading = wait_for_local_transform_settled(
        direction.owner_pipe,
        timeout=min(timeout, 10.0),
        stable_seconds=0.7,
    )
    monitor = finish_keyboard_movement_monitor(direction.owner_pipe)
    observer = wait_for_remote_convergence(
        direction.observer_pipe,
        direction.participant_id,
        settled_x,
        settled_y,
        settled_heading,
        timeout=timeout,
    )
    prefix = f"peer.{direction.participant_id}."
    observer_x = parse_float_text(observer.get(prefix + "x"), math.nan)
    observer_y = parse_float_text(observer.get(prefix + "y"), math.nan)
    displacement = distance(start_x, start_y, settled_x, settled_y)
    forward_displacement = settled_x - start_x
    cross_axis_displacement = abs(settled_y - start_y)
    peak_velocity = parse_float_text(monitor.get("peak_velocity"), math.nan)
    if not math.isfinite(displacement) or displacement <= 20.0:
        raise VerifyFailure(
            f"{direction.name} {label} real keyboard movement was too small: "
            f"start=({start_x},{start_y}) final=({settled_x},{settled_y}) "
            f"monitor={monitor}"
        )
    if not math.isfinite(peak_velocity) or peak_velocity <= 0.01:
        raise VerifyFailure(
            f"{direction.name} {label} real keyboard velocity was not observed: {monitor}"
        )
    return {
        "direction": direction.name,
        "label": label,
        "process_id": pid,
        "placement": placement,
        "before_runtime": before_runtime,
        "after_runtime": query_native_movement_runtime(direction.owner_pipe),
        "monitor_start": monitor_start,
        "monitor": monitor,
        "key_helper_output": key_output,
        "hold_ms": KEYBOARD_HOLD_MS,
        "requested_start": {"x": START_X, "y": START_Y},
        "start": {"x": start_x, "y": start_y, "heading": start_heading},
        "final": {"x": settled_x, "y": settled_y, "heading": settled_heading},
        "displacement": displacement,
        "forward_displacement": forward_displacement,
        "cross_axis_displacement": cross_axis_displacement,
        "peak_velocity": peak_velocity,
        "observer": {
            "x": observer_x,
            "y": observer_y,
            "position_error": distance(settled_x, settled_y, observer_x, observer_y),
        },
    }


def compact_rush_view(
    snapshot: dict[str, Any],
    ranked_stat: dict[str, Any],
) -> dict[str, Any]:
    return {
        "level": snapshot["native"]["level"],
        "rush_active": snapshot["native"]["entries"][RUSH_ROW]["active"],
        "rush_rank": ranked_stat["rank"],
        "rush_resolved_rank": ranked_stat["resolved_rank"],
        "rush_value_found": ranked_stat["property_found"],
        "rush_speed_percent": ranked_stat["value"],
        "move_speed": snapshot["native"]["move_speed"],
        "gameplay_slot": snapshot["native"]["gameplay_slot"],
        "process_a": snapshot["native"]["process_concentration_entry_a"],
        "slot_a": snapshot["native"]["slot_concentration_entry_a"],
        "ledger_a": snapshot["ledger"]["concentration_entry_a"],
    }


def assert_rush_contexts(
    expected_rank: int,
    expected_speed_percent: float,
    *,
    expect_concentration: bool,
) -> dict[str, Any]:
    locations = {
        "host_owner": (HOST_PIPE, None),
        "client_observes_host": (CLIENT_PIPE, HOST_ID),
        "client_owner": (CLIENT_PIPE, None),
        "host_observes_client": (HOST_PIPE, CLIENT_ID),
    }
    views = {
        label: query_progression_snapshot(pipe_name, participant_id=participant_id)
        for label, (pipe_name, participant_id) in locations.items()
    }
    ranked_stats = {
        label: query_ranked_numeric_stat(
            pipe_name,
            RUSH_ROW,
            "mValue",
            participant_id=participant_id,
        )
        for label, (pipe_name, participant_id) in locations.items()
    }
    compact = {
        label: compact_rush_view(views[label], ranked_stats[label])
        for label in locations
    }
    mismatches: list[dict[str, Any]] = []
    for label, view in compact.items():
        for field in ("rush_active", "rush_rank", "rush_resolved_rank"):
            expected = expected_rank
            if int(view[field]) != expected:
                mismatches.append(
                    {"view": label, "field": field, "actual": view[field], "expected": expected}
                )
        if not view["rush_value_found"]:
            mismatches.append(
                {
                    "view": label,
                    "field": "rush_value_found",
                    "actual": view["rush_value_found"],
                    "expected": True,
                }
            )
        if not math.isclose(
            float(view["rush_speed_percent"]),
            expected_speed_percent,
            rel_tol=0.0,
            abs_tol=0.001,
        ):
            mismatches.append(
                {
                    "view": label,
                    "field": "rush_speed_percent",
                    "actual": view["rush_speed_percent"],
                    "expected": expected_speed_percent,
                }
            )
        if expect_concentration:
            for field in ("slot_a", "ledger_a"):
                if int(view[field]) != RUSH_ROW:
                    mismatches.append(
                        {
                            "view": label,
                            "field": field,
                            "actual": view[field],
                            "expected": RUSH_ROW,
                        }
                    )
    if expect_concentration:
        for owner_label in ("host_owner", "client_owner"):
            if int(compact[owner_label]["process_a"]) != RUSH_ROW:
                mismatches.append(
                    {
                        "view": owner_label,
                        "field": "process_a",
                        "actual": compact[owner_label]["process_a"],
                        "expected": RUSH_ROW,
                    }
                )
    if mismatches:
        raise VerifyFailure(f"Rush native contexts diverged: {mismatches}")
    return {
        "expected_rank": expected_rank,
        "expected_speed_percent": expected_speed_percent,
        "views": compact,
        "mismatches": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument(
        "--minimum-concentrate-motion-ratio",
        "--minimum-speed-ratio",
        dest="minimum_concentrate_motion_ratio",
        type=float,
        default=1.15,
        help=(
            "minimum downstream motion ratio after Rush is also selected as "
            "the 25%% Concentrate skill"
        ),
    )
    parser.add_argument(
        "--minimum-ranked-rush-velocity-ratio",
        type=float,
        default=1.30,
        help=(
            "minimum real-keyboard peak-velocity gain attributable to ranked "
            "Rush after removing the independently measured Concentrate gain; "
            "the measured peaks must also match the live native envelope"
        ),
    )
    parser.add_argument("--keep-open", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument(
        "--native-rush-evidence",
        type=Path,
        default=NATIVE_RUSH_EVIDENCE,
        help="fresh passing stock-native Rush probe for the current Release DLL",
    )
    args = parser.parse_args()

    started_at = time.time()
    output: dict[str, Any] = {"ok": False}
    return_code = 1
    try:
        output["native_rush_evidence"] = load_native_rush_evidence(
            args.native_rush_evidence
        )
        stop_games()
        output["launch"] = launch_pair(
            preset="map_create_fire_mind_hub",
            god_mode=True,
            test_survival_boneyard_override=FLAT_BONEYARD,
            test_blank_boneyard=True,
            allow_focus_steal=True,
        )
        process_ids = {
            "host_owned": int(output["launch"]["hostProcessId"]),
            "client_owned": int(output["launch"]["clientProcessId"]),
        }
        disable_bots()
        output["hub_ready"] = {
            "host": wait_for_remote(HOST_PIPE, CLIENT_ID, CLIENT_NAME, "hub", args.timeout),
            "client": wait_for_remote(CLIENT_PIPE, HOST_ID, HOST_NAME, "hub", args.timeout),
        }
        output["quiet_progression_test_mode"] = enable_quiet_progression_test_mode()
        output["run_entry"] = start_host_testrun_and_wait_for_clients(args.timeout)
        output["post_run_progression_ready"] = wait_for_post_run_progression_ready(args.timeout)
        from verify_multiplayer_primary_kill_stress import (
            enable_manual_stock_spawner_combat,
        )

        output["combat_prelude"] = enable_manual_stock_spawner_combat()
        output["baseline_rush_contexts"] = assert_rush_contexts(
            0,
            0.0,
            expect_concentration=False,
        )

        output["baseline"] = {
            direction.name: run_movement_trial(direction, "baseline", args.timeout)
            for direction in DIRECTIONS
        }
        output["real_keyboard_baseline"] = {
            direction.name: run_real_keyboard_movement_trial(
                direction,
                process_ids[direction.name],
                "baseline",
                args.timeout,
            )
            for direction in DIRECTIONS
        }
        output["rush_applications"] = {
            direction.name: apply_rush_to_max(direction.participant_id, args.timeout)
            for direction in DIRECTIONS
        }
        output["rush_contexts"] = assert_rush_contexts(
            RUSH_MAX_RANK,
            RUSH_MAX_SPEED_PERCENT,
            expect_concentration=True,
        )
        output["upgraded"] = {
            direction.name: run_movement_trial(direction, "max_rush", args.timeout)
            for direction in DIRECTIONS
        }
        output["real_keyboard_upgraded"] = {
            direction.name: run_real_keyboard_movement_trial(
                direction,
                process_ids[direction.name],
                "max_rush",
                args.timeout,
            )
            for direction in DIRECTIONS
        }

        standing_speed_ratios: dict[str, float] = {}
        baseline_views = output["baseline_rush_contexts"]["views"]
        upgraded_views = output["rush_contexts"]["views"]
        for label in baseline_views:
            baseline_speed = float(baseline_views[label]["move_speed"])
            upgraded_speed = float(upgraded_views[label]["move_speed"])
            ratio = upgraded_speed / baseline_speed
            standing_speed_ratios[label] = ratio
            if not math.isclose(
                ratio,
                CONCENTRATE_SPEED_MULTIPLIER,
                rel_tol=0.0,
                abs_tol=0.002,
            ):
                raise VerifyFailure(
                    f"{label} Concentrate standing speed ratio diverged: "
                    f"baseline={baseline_speed:.6f} upgraded={upgraded_speed:.6f} "
                    f"ratio={ratio:.6f} expected={CONCENTRATE_SPEED_MULTIPLIER:.6f}"
                )
        output["speed_contract"] = {
            "ranked_rush_max_percent": RUSH_MAX_SPEED_PERCENT,
            "ranked_rush_max_multiplier": RUSH_MAX_SPEED_MULTIPLIER,
            "concentrate_speed_percent": CONCENTRATE_SPEED_PERCENT,
            "concentrate_speed_multiplier": CONCENTRATE_SPEED_MULTIPLIER,
            "combined_max_multiplier": COMBINED_MAX_SPEED_MULTIPLIER,
            "standing_speed_ratios": standing_speed_ratios,
            "motion_measurement_scope": (
                "scripted local input is downstream of the ranked Rush evaluator; "
                "that trial measures Concentrate movement plus position replication. "
                "The real-keyboard trial enters through stock input and separately "
                "proves ranked Rush."
            ),
            "ranked_behavior_evidence": output["native_rush_evidence"],
        }

        motion_ratios: dict[str, float] = {}
        for direction in DIRECTIONS:
            baseline = float(output["baseline"][direction.name]["displacement"])
            upgraded = float(output["upgraded"][direction.name]["displacement"])
            ratio = upgraded / baseline
            motion_ratios[direction.name] = ratio
            if ratio < args.minimum_concentrate_motion_ratio:
                raise VerifyFailure(
                    f"{direction.name} Concentrate did not materially accelerate downstream motion: "
                    f"baseline={baseline:.4f} upgraded={upgraded:.4f} ratio={ratio:.4f} "
                    f"minimum={args.minimum_concentrate_motion_ratio:.4f}"
                )
        if abs(motion_ratios["host_owned"] - motion_ratios["client_owned"]) > 0.05:
            raise VerifyFailure(
                f"host/client Concentrate motion ratios diverged: {motion_ratios}"
            )
        output["concentrate_motion_ratios"] = motion_ratios

        keyboard_contract: dict[str, dict[str, float]] = {}
        ranked_velocity_ratios: dict[str, float] = {}
        native_globals = output["native_rush_evidence"]["native_globals"]
        for direction in DIRECTIONS:
            baseline_trial = output["real_keyboard_baseline"][direction.name]
            upgraded_trial = output["real_keyboard_upgraded"][direction.name]
            displacement_ratio = (
                float(upgraded_trial["displacement"])
                / float(baseline_trial["displacement"])
            )
            peak_velocity_ratio = (
                float(upgraded_trial["peak_velocity"])
                / float(baseline_trial["peak_velocity"])
            )
            ranked_velocity_ratio = (
                peak_velocity_ratio / CONCENTRATE_SPEED_MULTIPLIER
            )
            expected_baseline_peak = expected_native_post_tick_peak_velocity(
                baseline_trial["before_runtime"],
                1.0,
                native_globals,
            )
            expected_upgraded_peak = expected_native_post_tick_peak_velocity(
                upgraded_trial["before_runtime"],
                RUSH_MAX_SPEED_MULTIPLIER,
                native_globals,
            )
            expected_peak_velocity_ratio = (
                expected_upgraded_peak / expected_baseline_peak
            )
            expected_ranked_velocity_ratio = (
                expected_peak_velocity_ratio / CONCENTRATE_SPEED_MULTIPLIER
            )
            keyboard_contract[direction.name] = {
                "displacement_ratio": displacement_ratio,
                "peak_velocity_ratio": peak_velocity_ratio,
                "concentrate_multiplier": CONCENTRATE_SPEED_MULTIPLIER,
                "ranked_rush_velocity_ratio": ranked_velocity_ratio,
                "expected_ranked_rush_multiplier": RUSH_MAX_SPEED_MULTIPLIER,
                "expected_baseline_peak_velocity": expected_baseline_peak,
                "expected_upgraded_peak_velocity": expected_upgraded_peak,
                "expected_peak_velocity_ratio": expected_peak_velocity_ratio,
                "expected_ranked_rush_velocity_ratio": expected_ranked_velocity_ratio,
            }
            ranked_velocity_ratios[direction.name] = ranked_velocity_ratio
            if not math.isclose(
                float(baseline_trial["peak_velocity"]),
                expected_baseline_peak,
                rel_tol=0.0,
                abs_tol=0.015,
            ):
                raise VerifyFailure(
                    f"{direction.name} baseline keyboard velocity diverged from the native envelope: "
                    f"measured={baseline_trial['peak_velocity']:.6f} "
                    f"expected={expected_baseline_peak:.6f}"
                )
            if not math.isclose(
                float(upgraded_trial["peak_velocity"]),
                expected_upgraded_peak,
                rel_tol=0.0,
                abs_tol=0.015,
            ):
                raise VerifyFailure(
                    f"{direction.name} upgraded keyboard velocity diverged from the native envelope: "
                    f"measured={upgraded_trial['peak_velocity']:.6f} "
                    f"expected={expected_upgraded_peak:.6f}"
                )
            if not math.isclose(
                ranked_velocity_ratio,
                expected_ranked_velocity_ratio,
                rel_tol=0.0,
                abs_tol=0.02,
            ):
                raise VerifyFailure(
                    f"{direction.name} ranked Rush velocity ratio diverged from the native envelope: "
                    f"measured={ranked_velocity_ratio:.6f} "
                    f"expected={expected_ranked_velocity_ratio:.6f}"
                )
            if ranked_velocity_ratio < args.minimum_ranked_rush_velocity_ratio:
                raise VerifyFailure(
                    f"{direction.name} stock keyboard movement did not apply ranked Rush: "
                    f"baseline_peak={baseline_trial['peak_velocity']:.6f} "
                    f"upgraded_peak={upgraded_trial['peak_velocity']:.6f} "
                    f"combined_ratio={peak_velocity_ratio:.6f} "
                    f"ranked_ratio={ranked_velocity_ratio:.6f} "
                    f"minimum={args.minimum_ranked_rush_velocity_ratio:.6f}"
                )
        if abs(
            ranked_velocity_ratios["host_owned"]
            - ranked_velocity_ratios["client_owned"]
        ) > 0.08:
            raise VerifyFailure(
                "host/client real-keyboard ranked Rush velocity ratios diverged: "
                f"{ranked_velocity_ratios}"
            )
        output["real_keyboard_contract"] = keyboard_contract

        crashes = new_crash_artifacts(started_at)
        output["new_crash_artifacts"] = crashes
        if crashes:
            raise VerifyFailure(f"new crash artifacts appeared during Rush behavior test: {crashes}")
        output["ok"] = True
        return_code = 0
    except (VerifyFailure, subprocess.TimeoutExpired, ValueError, OSError) as exc:
        output["error"] = str(exc)
        output["new_crash_artifacts"] = new_crash_artifacts(started_at)
    finally:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(output, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if not args.keep_open:
            stop_games()

    print(
        json.dumps(
            {
                "ok": output.get("ok", False),
                "error": output.get("error"),
                "concentrate_motion_ratios": output.get("concentrate_motion_ratios"),
                "real_keyboard_contract": output.get("real_keyboard_contract"),
                "speed_contract": output.get("speed_contract"),
                "new_crash_artifacts": output.get("new_crash_artifacts", []),
                "output": str(args.output),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
