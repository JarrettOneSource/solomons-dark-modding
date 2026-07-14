#!/usr/bin/env python3
"""Verify native Meditation idle recovery and live replication for both owners."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from multiplayer_progression_probe import query_progression_snapshot
from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_PIPE,
    HOST_ID,
    HOST_PIPE,
    VerifyFailure,
    distance,
    lua,
    parse_int_text,
    parse_key_values,
    place_player,
    stop_games,
    wait_for_local_transform_settled,
    wait_for_remote_convergence,
)
from verify_multiplayer_all_stat_sync import (
    compact_snapshot,
    load_stat_contract_values,
    wait_for_derived_parity,
)
from verify_multiplayer_all_upgrade_sync import (
    build_and_verify_catalog,
    enable_quiet_progression_test_mode,
    load_skill_configs,
    new_crash_artifacts,
    wait_for_catalog_views,
    wait_for_post_run_progression_ready,
)
from verify_multiplayer_battle_siege_behavior_sync import max_stat_for_target
from verify_multiplayer_fireball_explode_effect_sync import (
    build_manual_pair,
    launch_pair_ready,
)
from verify_multiplayer_primary_kill_stress import (
    cleanup_live_enemies,
    prepare_and_queue_caster,
    wait_for_cast_runtime_ready,
)
from verify_real_input_spell_cast_sync import (
    CLIENT_LOG,
    HOST_LOG,
    read_log,
)


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "runtime/multiplayer_meditation_behavior_sync.json"
MEDITATION_ROW = 58
TRIAL_DURATION_MS = 2300
SAMPLE_INTERVAL_MS = 50
PARK_X = 1050.0
PARK_Y = 780.0


@dataclass(frozen=True)
class Direction:
    name: str
    participant_id: int
    owner_pipe: str
    observer_pipe: str
    other_pipe: str
    source_log: Path
    start_x: float
    start_y: float

    @property
    def source_id(self) -> int:
        return self.participant_id

    @property
    def source_pipe(self) -> str:
        return self.owner_pipe

    @property
    def receiver_pipe(self) -> str:
        return self.observer_pipe


DIRECTIONS = (
    Direction(
        "host_owned",
        HOST_ID,
        HOST_PIPE,
        CLIENT_PIPE,
        CLIENT_PIPE,
        HOST_LOG,
        430.0,
        330.0,
    ),
    Direction(
        "client_owned",
        CLIENT_ID,
        CLIENT_PIPE,
        HOST_PIPE,
        HOST_PIPE,
        CLIENT_LOG,
        430.0,
        520.0,
    ),
)


REGISTER_MONITOR_LUA = r"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
if not _G.__sdmod_meditation_monitor_registered then
  sd.events.on('runtime.tick', function(event)
    local monitor = _G.__sdmod_meditation_monitor
    if type(monitor) ~= 'table' or not monitor.active then return end
    local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
    local progression = player and tonumber(player.progression_address) or 0
    if progression == 0 then
      monitor.error = 'local progression unavailable'
      monitor.active = false
      monitor.done = true
      return
    end

    local now = type(event) == 'table' and
      tonumber(event.monotonic_milliseconds) or 0
    if now <= 0 then
      monitor.fallback_ms = (monitor.fallback_ms or 0) + 16
      now = monitor.fallback_ms
    end
    if monitor.started_ms < 0 then
      monitor.started_ms = now
      monitor.last_sample_ms = now - monitor.sample_interval_ms
    end

    if monitor.moving then
      local ok, result = pcall(sd.input.hold_movement_frames, 1.0, 0.0, 1)
      if not ok or result ~= true then
        monitor.error = 'native movement input failed: ' .. tostring(result)
        monitor.active = false
        monitor.done = true
        return
      end
      monitor.movement_ticks = monitor.movement_ticks + 1
    end

    if now - monitor.last_sample_ms >= monitor.sample_interval_ms then
      monitor.last_sample_ms = now
      table.insert(monitor.samples, {
        elapsed_ms = now - monitor.started_ms,
        mp = tonumber(sd.debug.read_float(progression + monitor.mp_offset)) or -1,
        idle_elapsed = tonumber(sd.debug.read_i32(
          progression + monitor.idle_elapsed_offset)) or -1,
        recovery_ramp = tonumber(sd.debug.read_i32(
          progression + monitor.recovery_ramp_offset)) or -1,
        x = tonumber(player.x) or 0,
        y = tonumber(player.y) or 0,
      })
    end

    if now - monitor.started_ms >= monitor.duration_ms then
      monitor.active = false
      monitor.done = true
      monitor.finished_ms = now
    end
  end)
  _G.__sdmod_meditation_monitor_registered = true
end
emit('registered', _G.__sdmod_meditation_monitor_registered)
"""


def parse_float_text(value: str | None, default: float = math.nan) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def ensure_monitor_registered(pipe_name: str) -> dict[str, str]:
    result = parse_key_values(lua(pipe_name, REGISTER_MONITOR_LUA, timeout=8.0))
    if result.get("registered") != "true":
        raise VerifyFailure(f"Meditation monitor registration failed on {pipe_name}: {result}")
    return result


def start_monitor(pipe_name: str, *, moving: bool) -> dict[str, str]:
    moving_text = "true" if moving else "false"
    code = f"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
local progression = player and tonumber(player.progression_address) or 0
local mp_offset = sd.debug.layout_offset('progression_mp')
local idle_elapsed_offset = sd.debug.layout_offset(
  'progression_meditation_idle_elapsed_ticks')
local recovery_ramp_offset = sd.debug.layout_offset(
  'progression_meditation_recovery_ramp_ticks')
emit('progression', progression)
emit('mp_offset', mp_offset)
emit('idle_elapsed_offset', idle_elapsed_offset)
emit('recovery_ramp_offset', recovery_ramp_offset)
if progression == 0 or mp_offset == nil or idle_elapsed_offset == nil or
   recovery_ramp_offset == nil then
  emit('started', false)
  return
end
local write_ok = sd.debug.write_float(progression + mp_offset, 0.0)
local write_idle_ok = sd.debug.write_i32(
  progression + idle_elapsed_offset, 0)
_G.__sdmod_meditation_monitor = {{
  active = write_ok == true and write_idle_ok == true,
  done = false,
  error = '',
  moving = {moving_text},
  duration_ms = {TRIAL_DURATION_MS},
  sample_interval_ms = {SAMPLE_INTERVAL_MS},
  started_ms = -1,
  finished_ms = -1,
  fallback_ms = 0,
  last_sample_ms = 0,
  movement_ticks = 0,
  mp_offset = mp_offset,
  idle_elapsed_offset = idle_elapsed_offset,
  recovery_ramp_offset = recovery_ramp_offset,
  samples = {{}},
}}
emit('write_mp', write_ok)
emit('write_idle_elapsed', write_idle_ok)
emit('started', _G.__sdmod_meditation_monitor.active)
emit('moving', {moving_text})
"""
    result = parse_key_values(lua(pipe_name, code, timeout=8.0))
    if (
        result.get("started") != "true"
        or result.get("write_mp") != "true"
        or result.get("write_idle_elapsed") != "true"
    ):
        raise VerifyFailure(f"Meditation monitor start failed on {pipe_name}: {result}")
    return result


def query_monitor_status(pipe_name: str) -> dict[str, str]:
    return parse_key_values(
        lua(
            pipe_name,
            """
local function emit(key, value)
  print(key .. '=' .. tostring(value == nil and '' or value))
end
local monitor = _G.__sdmod_meditation_monitor or {}
for _, key in ipairs({
  'active','done','error','started_ms','finished_ms','movement_ticks'
}) do emit(key, monitor[key]) end
emit('sample_count', type(monitor.samples) == 'table' and #monitor.samples or 0)
""",
            timeout=8.0,
        )
    )


def query_meditation_runtime(pipe_name: str) -> dict[str, str]:
    return parse_key_values(
        lua(
            pipe_name,
            """
local function emit(key, value)
  print(key .. '=' .. tostring(value == nil and '' or value))
end
local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
local progression = player and tonumber(player.progression_address) or 0
local idle_offset = sd.debug.layout_offset(
  'progression_meditation_idle_elapsed_ticks')
local ramp_offset = sd.debug.layout_offset(
  'progression_meditation_recovery_ramp_ticks')
emit('progression', progression)
emit('idle_elapsed', progression ~= 0 and idle_offset ~= nil and
  sd.debug.read_i32(progression + idle_offset) or -1)
emit('recovery_ramp', progression ~= 0 and ramp_offset ~= nil and
  sd.debug.read_i32(progression + ramp_offset) or -1)
""",
            timeout=8.0,
        )
    )


def interrupt_meditation_with_primary_cast(
    direction: Direction,
    timeout: float,
) -> dict[str, Any]:
    cleanup_live_enemies()
    target = build_manual_pair(
        direction,
        0.0,
        0.0,
        target_hp=100000.0,
        include_secondary=False,
    )
    cast_runtime = wait_for_cast_runtime_ready(direction, timeout=min(timeout, 8.0))
    before = query_meditation_runtime(direction.owner_pipe)
    resource_fill = parse_key_values(
        lua(
            direction.owner_pipe,
            """
local function emit(key, value) print(key .. '=' .. tostring(value)) end
local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
local progression = player and tonumber(player.progression_address) or 0
local mp_offset = sd.debug.layout_offset('progression_mp')
local max_mp_offset = sd.debug.layout_offset('progression_max_mp')
local maximum = progression ~= 0 and max_mp_offset ~= nil and
  tonumber(sd.debug.read_float(progression + max_mp_offset)) or 0
emit('maximum', maximum)
emit('write', progression ~= 0 and mp_offset ~= nil and maximum > 0 and
  sd.debug.write_float(progression + mp_offset, maximum) or false)
emit('current', progression ~= 0 and mp_offset ~= nil and
  sd.debug.read_float(progression + mp_offset) or -1)
""",
            timeout=8.0,
        )
    )
    if resource_fill.get("write") != "true":
        raise VerifyFailure(
            f"{direction.name} could not fill mana for interrupt cast: {resource_fill}"
        )
    log_offset = len(read_log(direction.source_log))
    queued = prepare_and_queue_caster(
        direction,
        int(target["primary_actor_address"]),
        float(target["primary_x"]),
        float(target["primary_y"]),
        64,
    )

    marker = (
        "Multiplayer local native cast sent. "
        f"native_queue_id="
    )
    participant_marker = f"participant_id={direction.participant_id}"
    deadline = time.monotonic() + timeout
    samples: list[dict[str, str]] = []
    cast_observed = False
    reset_observed = False
    while time.monotonic() < deadline:
        current = query_meditation_runtime(direction.owner_pipe)
        samples.append(current)
        segment = read_log(direction.source_log)[log_offset:]
        cast_observed = marker in segment and participant_marker in segment
        idle_elapsed = parse_int_text(current.get("idle_elapsed"), -1)
        reset_observed = 0 <= idle_elapsed <= 25
        if cast_observed and reset_observed:
            break
        time.sleep(0.02)
    cleared = parse_key_values(
        lua(
            direction.owner_pipe,
            "local function emit(k,v) print(k .. '=' .. tostring(v)) end; "
            "emit('cleared', sd.input.clear_mouse_left())",
            timeout=8.0,
        )
    )
    if not cast_observed or not reset_observed:
        raise VerifyFailure(
            f"{direction.name} genuine primary did not reset Meditation idle time: "
            f"cast_observed={cast_observed} reset_observed={reset_observed} "
            f"before={before} recent_samples={samples[-12:]}"
        )
    return {
        "before": before,
        "target": target,
        "cast_runtime": cast_runtime,
        "resource_fill": resource_fill,
        "queued": queued,
        "samples": samples,
        "cast_observed": cast_observed,
        "reset_observed": reset_observed,
        "clear": cleared,
        "minimum_idle_elapsed": min(
            parse_int_text(sample.get("idle_elapsed"), 1_000_000_000)
            for sample in samples
        ),
    }


def read_monitor_result(pipe_name: str) -> dict[str, Any]:
    raw = parse_key_values(
        lua(
            pipe_name,
            """
local function emit(key, value)
  print(key .. '=' .. tostring(value == nil and '' or value))
end
local monitor = _G.__sdmod_meditation_monitor or {}
for _, key in ipairs({
  'active','done','error','started_ms','finished_ms','movement_ticks'
}) do emit(key, monitor[key]) end
local samples = type(monitor.samples) == 'table' and monitor.samples or {}
emit('sample_count', #samples)
for index, sample in ipairs(samples) do
  local prefix = 'sample.' .. tostring(index) .. '.'
  for _, key in ipairs({'elapsed_ms','mp','idle_elapsed','recovery_ramp','x','y'}) do
    emit(prefix .. key, sample[key])
  end
end
""",
            timeout=10.0,
        )
    )
    count = parse_int_text(raw.get("sample_count"), 0)
    samples: list[dict[str, float | int]] = []
    for index in range(1, count + 1):
        prefix = f"sample.{index}."
        samples.append(
            {
                "elapsed_seconds": parse_float_text(raw.get(prefix + "elapsed_ms")) / 1000.0,
                "mp": parse_float_text(raw.get(prefix + "mp")),
                "idle_elapsed": parse_int_text(raw.get(prefix + "idle_elapsed"), -1),
                "recovery_ramp": parse_int_text(raw.get(prefix + "recovery_ramp"), -1),
                "x": parse_float_text(raw.get(prefix + "x")),
                "y": parse_float_text(raw.get(prefix + "y")),
            }
        )
    if raw.get("done") != "true" or raw.get("error"):
        raise VerifyFailure(f"Meditation monitor did not complete cleanly: {raw}")
    if len(samples) < 20 or any(
        not math.isfinite(float(sample["mp"])) for sample in samples
    ):
        raise VerifyFailure(f"Meditation monitor captured invalid samples: {samples}")
    return {
        "movement_ticks": parse_int_text(raw.get("movement_ticks"), 0),
        "sample_count": len(samples),
        "samples": samples,
    }


def window_rate(samples: list[dict[str, float | int]], start: float, end: float) -> float:
    selected = [
        sample for sample in samples
        if start <= float(sample["elapsed_seconds"]) <= end
    ]
    if len(selected) < 2:
        raise VerifyFailure(
            f"Meditation sample window {start:.2f}-{end:.2f}s is empty: {samples}"
        )
    elapsed = float(selected[-1]["elapsed_seconds"]) - float(selected[0]["elapsed_seconds"])
    if elapsed <= 0.0:
        raise VerifyFailure(f"Meditation sample timestamps did not advance: {selected}")
    return (float(selected[-1]["mp"]) - float(selected[0]["mp"])) / elapsed


def query_mana_view(
    pipe_name: str,
    participant_id: int | None,
) -> dict[str, float]:
    participant_selector = "nil" if participant_id is None else str(participant_id)
    values = parse_key_values(
        lua(
            pipe_name,
            f"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
local requested = {participant_selector}
local player = sd.player.get_state()
local bot = requested ~= nil and sd.bots.get_participant_state(requested) or nil
local progression = requested == nil and tonumber(player and player.progression_address) or
  tonumber(bot and bot.progression_runtime_state_address)
local multiplayer = sd.runtime.get_multiplayer_state()
local participant = nil
for _, candidate in ipairs(multiplayer and multiplayer.participants or {{}}) do
  if (requested == nil and candidate.is_owner) or
     (requested ~= nil and tonumber(candidate.participant_id) == requested) then
    participant = candidate
    break
  end
end
emit('available', progression ~= nil and progression ~= 0 and participant ~= nil)
emit('runtime_mp', participant and participant.mana_current or 0)
emit('native_mp', progression and sd.debug.read_float(
  progression + sd.debug.layout_offset('progression_mp')) or 0)
""",
            timeout=5.0,
        )
    )
    if values.get("available") != "true":
        raise VerifyFailure(
            f"live mana view unavailable pipe={pipe_name} "
            f"participant_id={participant_id}: {values}"
        )
    return {
        "native_mp": parse_float_text(values.get("native_mp")),
        "runtime_mp": parse_float_text(values.get("runtime_mp")),
    }


def compact_network_sample(
    direction: Direction,
) -> dict[str, float]:
    owner = query_mana_view(direction.owner_pipe, None)
    observer = query_mana_view(direction.observer_pipe, direction.participant_id)
    return {
        "owner_mp": owner["native_mp"],
        "observer_native_mp": observer["native_mp"],
        "observer_runtime_mp": observer["runtime_mp"],
    }


def run_trial(
    direction: Direction,
    label: str,
    *,
    moving: bool,
    interrupt_with_cast: bool,
    timeout: float,
) -> dict[str, Any]:
    place_player(direction.other_pipe, PARK_X, PARK_Y, 180.0)
    placement = place_player(
        direction.owner_pipe,
        direction.start_x,
        direction.start_y,
        0.0,
    )
    initial_x, initial_y, initial_heading = wait_for_local_transform_settled(
        direction.owner_pipe,
        timeout=min(timeout, 10.0),
        stable_seconds=0.35,
    )
    wait_for_remote_convergence(
        direction.observer_pipe,
        direction.participant_id,
        initial_x,
        initial_y,
        initial_heading,
        timeout=timeout,
    )
    idle_interrupt = (
        interrupt_meditation_with_primary_cast(direction, timeout)
        if interrupt_with_cast
        else None
    )
    post_interrupt_placement = None
    if idle_interrupt is not None:
        cleanup_live_enemies()
        place_player(direction.other_pipe, PARK_X, PARK_Y, 180.0)
        post_interrupt_placement = place_player(
            direction.owner_pipe,
            direction.start_x,
            direction.start_y,
            0.0,
        )
        initial_x, initial_y, initial_heading = wait_for_local_transform_settled(
            direction.owner_pipe,
            timeout=min(timeout, 10.0),
            stable_seconds=0.35,
        )
        wait_for_remote_convergence(
            direction.observer_pipe,
            direction.participant_id,
            initial_x,
            initial_y,
            initial_heading,
            timeout=timeout,
        )
    registration = ensure_monitor_registered(direction.owner_pipe)
    monitor_start = start_monitor(direction.owner_pipe, moving=moving)

    deadline = time.monotonic() + timeout
    last_status: dict[str, str] = {}
    network_samples: list[dict[str, float]] = []
    next_network_sample = 0.0
    while time.monotonic() < deadline:
        last_status = query_monitor_status(direction.owner_pipe)
        now = time.monotonic()
        if now >= next_network_sample:
            network_samples.append(compact_network_sample(direction))
            next_network_sample = now + 0.20
        if last_status.get("error"):
            raise VerifyFailure(f"{direction.name} {label} monitor failed: {last_status}")
        if last_status.get("done") == "true":
            break
        time.sleep(0.04)
    else:
        raise VerifyFailure(f"{direction.name} {label} monitor timed out: {last_status}")

    monitor = read_monitor_result(direction.owner_pipe)
    samples = monitor["samples"]
    settled_x, settled_y, settled_heading = wait_for_local_transform_settled(
        direction.owner_pipe,
        timeout=min(timeout, 10.0),
        stable_seconds=0.35,
    )
    observer_transform = wait_for_remote_convergence(
        direction.observer_pipe,
        direction.participant_id,
        settled_x,
        settled_y,
        settled_heading,
        timeout=timeout,
    )
    prefix = f"peer.{direction.participant_id}."
    observer_x = parse_float_text(observer_transform.get(prefix + "x"))
    observer_y = parse_float_text(observer_transform.get(prefix + "y"))

    full_rate = window_rate(samples, 0.30, 1.80)
    early_rate = window_rate(samples, 0.20, 0.75)
    late_rate = window_rate(samples, 1.25, 2.05)
    peak_rate = max(full_rate, early_rate, late_rate, 0.0)
    replication_tolerance = max(3.0, peak_rate * 0.35)
    owner_observer_errors = [
        abs(sample["owner_mp"] - sample["observer_native_mp"])
        for sample in network_samples
    ]
    observer_internal_errors = [
        abs(sample["observer_native_mp"] - sample["observer_runtime_mp"])
        for sample in network_samples
    ]
    # The trial starts with an intentional owner-only debug write from full to
    # zero mana. That precondition is not a network event, so the first sampled
    # observer can legitimately retain the old value until the next 20 Hz
    # owned-progression packet. Require prompt convergence, then enforce the
    # live recovery contract for every remaining sample.
    replication_converged_index = next(
        (
            index
            for index, (owner_error, internal_error) in enumerate(
                zip(owner_observer_errors, observer_internal_errors)
            )
            if owner_error <= replication_tolerance
            and internal_error <= replication_tolerance
        ),
        -1,
    )
    if replication_converged_index < 0 or replication_converged_index > 2:
        raise VerifyFailure(
            f"{direction.name} {label} forced mana precondition did not converge promptly: "
            f"owner_errors={owner_observer_errors} "
            f"internal_errors={observer_internal_errors} "
            f"tolerance={replication_tolerance:.3f}"
        )
    validated_owner_observer_errors = owner_observer_errors[
        replication_converged_index:
    ]
    validated_observer_internal_errors = observer_internal_errors[
        replication_converged_index:
    ]
    if max(validated_owner_observer_errors, default=0.0) > replication_tolerance:
        raise VerifyFailure(
            f"{direction.name} {label} owner/observer mana diverged: "
            f"errors={validated_owner_observer_errors} "
            f"tolerance={replication_tolerance:.3f}"
        )
    if max(validated_observer_internal_errors, default=0.0) > replication_tolerance:
        raise VerifyFailure(
            f"{direction.name} {label} observer native/runtime mana diverged: "
            f"errors={validated_observer_internal_errors} "
            f"tolerance={replication_tolerance:.3f}"
        )
    if moving and monitor["movement_ticks"] < 60:
        raise VerifyFailure(
            f"{direction.name} {label} did not sustain native movement: {monitor}"
        )

    return {
        "direction": direction.name,
        "label": label,
        "moving": moving,
        "placement": placement,
        "settled_initial_position": {
            "x": initial_x,
            "y": initial_y,
            "heading": initial_heading,
        },
        "idle_interrupt": idle_interrupt,
        "post_interrupt_placement": post_interrupt_placement,
        "monitor_registration": registration,
        "monitor_start": monitor_start,
        "monitor": monitor,
        "rates": {
            "full": full_rate,
            "early": early_rate,
            "late": late_rate,
        },
        "mana_gain": float(samples[-1]["mp"]) - float(samples[0]["mp"]),
        "max_idle_elapsed": max(int(sample["idle_elapsed"]) for sample in samples),
        "max_recovery_ramp": max(int(sample["recovery_ramp"]) for sample in samples),
        "network_samples": network_samples,
        "replication_tolerance": replication_tolerance,
        "replication_converged_sample_index": replication_converged_index,
        "max_owner_observer_mp_error_after_convergence": max(
            validated_owner_observer_errors,
            default=0.0,
        ),
        "max_observer_native_runtime_mp_error_after_convergence": max(
            validated_observer_internal_errors,
            default=0.0,
        ),
        "final_position": {"x": settled_x, "y": settled_y, "heading": settled_heading},
        "observer_position": {
            "x": observer_x,
            "y": observer_y,
            "error": distance(settled_x, settled_y, observer_x, observer_y),
        },
    }


def assert_behavior(
    direction: Direction,
    baseline: dict[str, Any],
    stationary: dict[str, Any],
    moving: dict[str, Any],
) -> dict[str, float]:
    baseline_rate = float(baseline["rates"]["full"])
    early_rate = float(stationary["rates"]["early"])
    late_rate = float(stationary["rates"]["late"])
    moving_rate = float(moving["rates"]["full"])
    moving_late_rate = float(moving["rates"]["late"])
    if baseline_rate <= 1.0 or moving_rate <= 1.0:
        raise VerifyFailure(
            f"{direction.name} base mana recovery was not active: "
            f"baseline={baseline_rate:.3f} moving={moving_rate:.3f}"
        )
    if late_rate < baseline_rate * 3.5:
        raise VerifyFailure(
            f"{direction.name} Meditation did not produce its post-cast recovery step: "
            f"baseline={baseline_rate:.3f} early={early_rate:.3f} "
            f"late={late_rate:.3f} moving={moving_rate:.3f}"
        )
    # Compare equivalent post-threshold windows. The full moving window also
    # includes the ordinary recovery period before the idle threshold.
    if not (late_rate * 0.40 <= moving_late_rate <= late_rate * 0.60):
        raise VerifyFailure(
            f"{direction.name} moving Meditation did not preserve stock half recovery: "
            f"stationary={late_rate:.3f} moving={moving_late_rate:.3f}"
        )
    if early_rate > baseline_rate * 1.75 or early_rate < -0.05:
        raise VerifyFailure(
            f"{direction.name} Meditation activated before the native idle threshold: "
            f"baseline={baseline_rate:.3f} early={early_rate:.3f}"
        )
    stationary_samples = stationary["monitor"]["samples"]
    moving_samples = moving["monitor"]["samples"]
    if int(stationary_samples[0]["idle_elapsed"]) > 35 or int(
        moving_samples[0]["idle_elapsed"]
    ) > 35:
        raise VerifyFailure(
            f"{direction.name} trials did not begin from a cast-reset idle counter: "
            f"stationary={stationary_samples[0]} moving={moving_samples[0]}"
        )
    if int(stationary["max_idle_elapsed"]) < 100 or int(
        moving["max_idle_elapsed"]
    ) < 100:
        raise VerifyFailure(
            f"{direction.name} Meditation idle counter never crossed rank threshold"
        )
    return {
        "baseline_rate": baseline_rate,
        "stationary_early_rate": early_rate,
        "stationary_late_rate": late_rate,
        "moving_full_rate": moving_rate,
        "moving_late_rate": moving_late_rate,
        "idle_multiplier_vs_baseline": late_rate / baseline_rate,
        "stationary_to_moving_ratio": late_rate / moving_late_rate,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--keep-open", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    started_at = time.time()
    output: dict[str, Any] = {"ok": False}
    return_code = 1
    try:
        startup = launch_pair_ready(
            args.timeout,
            god_mode=False,
            manual_combat=True,
        )
        output["startup"] = startup
        output["quiet_progression_test_mode"] = enable_quiet_progression_test_mode()
        output["post_run_progression_ready"] = wait_for_post_run_progression_ready(
            args.timeout
        )
        catalog_result = build_and_verify_catalog(
            wait_for_catalog_views(args.timeout),
            load_skill_configs(),
        )
        catalog = catalog_result["catalog"]
        contract_values = load_stat_contract_values(catalog)
        initial = {
            HOST_ID: query_progression_snapshot(HOST_PIPE),
            CLIENT_ID: query_progression_snapshot(CLIENT_PIPE),
        }

        output["baseline"] = {
            direction.name: run_trial(
                direction,
                "baseline_stationary",
                moving=False,
                interrupt_with_cast=False,
                timeout=args.timeout,
            )
            for direction in DIRECTIONS
        }
        output["upgrades"] = {
            direction.name: max_stat_for_target(
                catalog,
                MEDITATION_ROW,
                direction.participant_id,
                initial,
                contract_values,
                args.timeout,
            )
            for direction in DIRECTIONS
        }
        output["upgraded_views"] = {}
        for direction in DIRECTIONS:
            owner, observer = wait_for_derived_parity(
                direction.participant_id,
                args.timeout,
            )
            active = int(owner["native"]["entries"][MEDITATION_ROW]["active"])
            maximum = int(catalog[MEDITATION_ROW]["native_max_level"])
            derived = owner["native"]["derived"]
            if active != maximum:
                raise VerifyFailure(
                    f"{direction.name} Meditation rank is {active}, expected {maximum}"
                )
            if int(derived["meditation_idle_ticks"]) != 100 or not math.isclose(
                float(derived["meditation_recovery_bonus"]),
                5.0,
                abs_tol=0.002,
            ):
                raise VerifyFailure(
                    f"{direction.name} max Meditation native fields are wrong: {derived}"
                )
            output["upgraded_views"][direction.name] = {
                "owner": compact_snapshot(owner, MEDITATION_ROW),
                "observer": compact_snapshot(observer, MEDITATION_ROW),
            }

        output["upgraded_stationary"] = {
            direction.name: run_trial(
                direction,
                "max_stationary",
                moving=False,
                interrupt_with_cast=True,
                timeout=args.timeout,
            )
            for direction in DIRECTIONS
        }
        output["upgraded_moving"] = {
            direction.name: run_trial(
                direction,
                "max_moving",
                moving=True,
                interrupt_with_cast=True,
                timeout=args.timeout,
            )
            for direction in DIRECTIONS
        }
        output["behavior"] = {
            direction.name: assert_behavior(
                direction,
                output["baseline"][direction.name],
                output["upgraded_stationary"][direction.name],
                output["upgraded_moving"][direction.name],
            )
            for direction in DIRECTIONS
        }
        idle_multipliers = [
            float(output["behavior"][direction.name]["idle_multiplier_vs_baseline"])
            for direction in DIRECTIONS
        ]
        if max(idle_multipliers) / min(idle_multipliers) > 1.30:
            raise VerifyFailure(
                f"Meditation behavior differs materially by owner: {idle_multipliers}"
            )

        crashes = new_crash_artifacts(started_at)
        output["new_crash_artifacts"] = crashes
        if crashes:
            raise VerifyFailure(
                f"new crash artifacts during Meditation behavior test: {crashes}"
            )
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
                "behavior": output.get("behavior"),
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
