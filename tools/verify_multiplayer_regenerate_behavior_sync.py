#!/usr/bin/env python3
"""Verify Regenerate's timed healing and mana hoard for either owner."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import subprocess
import time
from pathlib import Path
from typing import Any

from cast_state_probe import read_runtime_layout_offset
from multiplayer_persistent_status_harness import (
    PERSISTENT_REGENERATE,
    query_persistent_status,
)
from multiplayer_progression_probe import query_ranked_numeric_stat
from verify_local_multiplayer_sync import (
    CLIENT_PIPE,
    HOST_PIPE,
    VerifyFailure,
    lua,
    parse_key_values,
    stop_games,
)
from verify_multiplayer_all_upgrade_sync import (
    new_crash_artifacts,
    wait_for_post_run_progression_ready,
)
from verify_multiplayer_fireball_explode_effect_sync import launch_pair_ready
from verify_multiplayer_focus_behavior_sync import (
    DIRECTIONS,
    Direction,
    acquire_secondary_to_rank,
    enable_unsuppressed_combat_prelude,
)
from verify_multiplayer_persistent_status_sync import toggle_once
from verify_player_health_death_sync import set_local_player_vitals


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "runtime/multiplayer_regenerate_behavior_sync.json"
REGENERATE_ROW = 0x4F
START_HP = 25.0
MAX_HP = 50.0
START_MP = 100.0
MAX_MP = 100.0
BASELINE_SECONDS = 1.8
ACTIVE_SECONDS = 3.8
RESTORED_SECONDS = 1.8
NATIVE_REGENERATE_HEAL_INSTRUCTION = read_runtime_layout_offset(
    "regenerate_heal_instruction"
)
RUNTIME_FRAME_RATE_GLOBAL = read_runtime_layout_offset(
    "game_timing_scale"
)
PROGRESSION_HEALTH_REGEN_OFFSET = read_runtime_layout_offset(
    "progression_health_regeneration"
)
NATIVE_HEAL_NUMERATOR = 1.5
NATIVE_BASE_HEAL_DIVISOR = 10.0
NATIVE_HEAL_TRACE_NAME = "regenerate_native_heal"
NATIVE_TRACE_CAPACITY = 256
NATIVE_HEAL_DELTA_TOLERANCE = 0.06
NATIVE_HEAL_PER_UPDATE_TOLERANCE = 0.001
OWNER_OBSERVER_HP_ENVELOPE = 1.05
SAMPLE_INTERVAL_MS = 100


REGISTER_VITAL_MONITOR_LUA = r"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
if not _G.__sdmod_regenerate_monitor_registered then
  sd.events.on('runtime.tick', function(event)
    local monitor = _G.__sdmod_regenerate_monitor
    if type(monitor) ~= 'table' or not monitor.active then return end

    local state = nil
    if monitor.participant_id == 0 then
      state = sd.player and sd.player.get_state and sd.player.get_state() or nil
    else
      state = sd.bots and sd.bots.get_participant_state and
        sd.bots.get_participant_state(monitor.participant_id) or nil
    end
    if type(state) ~= 'table' then
      monitor.error = 'participant vitals unavailable'
      monitor.active = false
      monitor.done = true
      return
    end

    local now = type(event) == 'table' and
      tonumber(event.monotonic_milliseconds) or 0
    if now <= 0 then
      monitor.error = 'runtime.tick monotonic timestamp unavailable'
      monitor.active = false
      monitor.done = true
      return
    end
    if monitor.started_ms < 0 then
      monitor.started_ms = now
      monitor.last_sample_ms = now - monitor.sample_interval_ms
    end
    monitor.tick_count = monitor.tick_count + 1

    local elapsed_ms = now - monitor.started_ms
    if now - monitor.last_sample_ms >= monitor.sample_interval_ms or
       elapsed_ms >= monitor.duration_ms then
      monitor.last_sample_ms = now

      if monitor.track_native_heals then
        local progression = tonumber(state.progression_address) or 0
        if progression == 0 then
          monitor.error = 'local progression address unavailable'
          monitor.active = false
          monitor.done = true
          return
        end
        local hits = sd.debug.get_trace_hits(monitor.trace_name) or {}
        if #hits >= monitor.trace_capacity then
          monitor.error = 'native Regenerate trace buffer overflowed'
          monitor.trace_overflow = true
          monitor.active = false
          monitor.done = true
          return
        end
        local matching_hits = 0
        for _, hit in ipairs(hits) do
          if tonumber(hit.esi) == progression then
            matching_hits = matching_hits + 1
          end
        end
        sd.debug.clear_trace_hits(monitor.trace_name)

        local frame_rate = tonumber(
          sd.debug.read_float(monitor.frame_rate_address)) or 0
        if frame_rate <= 0 then
          monitor.error = 'native runtime frame rate unavailable'
          monitor.active = false
          monitor.done = true
          return
        end
        local base_heal = tonumber(sd.debug.read_float(
          progression + monitor.base_heal_offset)) or -1
        if base_heal < 0 then
          monitor.error = 'native base health regeneration unavailable'
          monitor.active = false
          monitor.done = true
          return
        end
        monitor.native_heal_count =
          monitor.native_heal_count + matching_hits
        monitor.expected_native_heal = monitor.expected_native_heal +
          matching_hits * (
            monitor.heal_numerator / frame_rate +
            base_heal / (frame_rate * monitor.base_heal_divisor))
        monitor.min_frame_rate = math.min(monitor.min_frame_rate, frame_rate)
        monitor.max_frame_rate = math.max(monitor.max_frame_rate, frame_rate)
        monitor.min_base_heal = math.min(monitor.min_base_heal, base_heal)
        monitor.max_base_heal = math.max(monitor.max_base_heal, base_heal)
      end

      table.insert(monitor.samples, {
        elapsed_ms = elapsed_ms,
        tick_count = monitor.tick_count,
        native_heal_count = monitor.native_heal_count,
        expected_native_heal = monitor.expected_native_heal,
        hp = tonumber(state.hp) or -1,
        mp = tonumber(state.mp) or -1,
      })
    end
    if elapsed_ms >= monitor.duration_ms then
      monitor.active = false
      monitor.done = true
      monitor.finished_ms = now
    end
  end)
  _G.__sdmod_regenerate_monitor_registered = true
end
emit('registered', _G.__sdmod_regenerate_monitor_registered)
"""


def observer_pipe(direction: Direction) -> str:
    return HOST_PIPE if direction.source_pipe == CLIENT_PIPE else CLIENT_PIPE


def wait_for_vitals(
    direction: Direction,
    expected_hp: float | None,
    expected_mp: float,
    timeout: float,
    *,
    hp_tolerance: float = 0.20,
    mp_tolerance: float = 0.75,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    attempts = 0
    owner: dict[str, Any] = {}
    observer: dict[str, Any] = {}
    while time.monotonic() < deadline:
        attempts += 1
        owner = query_persistent_status(direction.source_pipe)
        observer = query_persistent_status(
            observer_pipe(direction),
            participant_id=direction.source_id,
        )
        hp_matches = (
            abs(owner["hp"] - observer["hp"]) <= hp_tolerance
            if expected_hp is None
            else math.isclose(owner["hp"], expected_hp, abs_tol=hp_tolerance)
            and math.isclose(observer["hp"], expected_hp, abs_tol=hp_tolerance)
        )
        if (
            hp_matches
            and math.isclose(owner["mp"], expected_mp, abs_tol=mp_tolerance)
            and math.isclose(observer["mp"], expected_mp, abs_tol=mp_tolerance)
            and math.isclose(owner["max_hp"], MAX_HP, abs_tol=0.20)
            and math.isclose(observer["max_hp"], MAX_HP, abs_tol=0.20)
            and math.isclose(owner["max_mp"], MAX_MP, abs_tol=0.20)
            and math.isclose(observer["max_mp"], MAX_MP, abs_tol=0.20)
        ):
            return {
                "attempt_count": attempts,
                "owner": owner,
                "observer": observer,
            }
        time.sleep(0.05)
    raise VerifyFailure(
        f"{direction.name} vitals did not converge to hp={expected_hp} "
        f"mp={expected_mp}: owner={owner} observer={observer}"
    )


def ensure_vital_monitor_registered(pipe_name: str) -> dict[str, str]:
    result = parse_key_values(
        lua(pipe_name, REGISTER_VITAL_MONITOR_LUA, timeout=8.0)
    )
    if result.get("registered") != "true":
        raise VerifyFailure(
            f"Regenerate monitor registration failed on {pipe_name}: {result}"
        )
    return result


def arm_native_heal_trace(pipe_name: str) -> dict[str, str]:
    result = parse_key_values(
        lua(
            pipe_name,
            f"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
pcall(sd.debug.untrace_function, {NATIVE_REGENERATE_HEAL_INSTRUCTION})
sd.debug.clear_trace_hits('{NATIVE_HEAL_TRACE_NAME}')
local armed = sd.debug.trace_function(
  {NATIVE_REGENERATE_HEAL_INSTRUCTION},
  '{NATIVE_HEAL_TRACE_NAME}')
emit('armed', armed)
emit('error', sd.debug.get_last_error and sd.debug.get_last_error() or '')
""",
            timeout=8.0,
        )
    )
    if result.get("armed") != "true":
        raise VerifyFailure(
            f"native Regenerate trace failed on {pipe_name}: {result}"
        )
    return result


def disarm_native_heal_trace(pipe_name: str) -> dict[str, str]:
    return parse_key_values(
        lua(
            pipe_name,
            f"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
sd.debug.untrace_function({NATIVE_REGENERATE_HEAL_INSTRUCTION})
sd.debug.clear_trace_hits('{NATIVE_HEAL_TRACE_NAME}')
emit('disarmed', true)
""",
            timeout=8.0,
        )
    )


def start_vital_monitor(
    pipe_name: str,
    participant_id: int,
    duration: float,
    *,
    track_native_heals: bool = False,
) -> dict[str, str]:
    duration_ms = max(1, round(duration * 1000.0))
    result = parse_key_values(
        lua(
            pipe_name,
            f"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
_G.__sdmod_regenerate_monitor = {{
  active = true,
  done = false,
  error = '',
  participant_id = {participant_id},
  duration_ms = {duration_ms},
  sample_interval_ms = {SAMPLE_INTERVAL_MS},
  track_native_heals = {str(track_native_heals).lower()},
  trace_name = '{NATIVE_HEAL_TRACE_NAME}',
  trace_capacity = {NATIVE_TRACE_CAPACITY},
  frame_rate_address = sd.debug.resolve_game_address(
    {RUNTIME_FRAME_RATE_GLOBAL}),
  base_heal_offset = {PROGRESSION_HEALTH_REGEN_OFFSET},
  base_heal_divisor = {NATIVE_BASE_HEAL_DIVISOR},
  heal_numerator = {NATIVE_HEAL_NUMERATOR},
  started_ms = -1,
  finished_ms = -1,
  last_sample_ms = 0,
  tick_count = 0,
  native_heal_count = 0,
  expected_native_heal = 0,
  min_frame_rate = math.huge,
  max_frame_rate = 0,
  min_base_heal = math.huge,
  max_base_heal = 0,
  trace_overflow = false,
  samples = {{}},
}}
emit('started', true)
emit('participant_local', {str(participant_id == 0).lower()})
emit('track_native_heals', {str(track_native_heals).lower()})
""",
            timeout=8.0,
        )
    )
    if result.get("started") != "true":
        raise VerifyFailure(
            f"Regenerate monitor start failed on {pipe_name}: {result}"
        )
    return result


def vital_monitor_status(pipe_name: str) -> dict[str, str]:
    return parse_key_values(
        lua(
            pipe_name,
            """
local function emit(key, value)
  print(key .. '=' .. tostring(value == nil and '' or value))
end
local monitor = _G.__sdmod_regenerate_monitor or {}
emit('active', monitor.active)
emit('done', monitor.done)
emit('error', monitor.error)
emit('tick_count', monitor.tick_count)
emit('native_heal_count', monitor.native_heal_count)
emit('trace_overflow', monitor.trace_overflow)
emit('sample_count', type(monitor.samples) == 'table' and #monitor.samples or 0)
""",
            timeout=8.0,
        )
    )


def collect_vital_monitor(pipe_name: str) -> dict[str, Any]:
    raw = parse_key_values(
        lua(
            pipe_name,
            """
local function emit(key, value)
  print(key .. '=' .. tostring(value == nil and '' or value))
end
local monitor = _G.__sdmod_regenerate_monitor or {}
emit('active', monitor.active)
emit('done', monitor.done)
emit('error', monitor.error)
emit('tick_count', monitor.tick_count)
emit('native_heal_count', monitor.native_heal_count)
emit('expected_native_heal', monitor.expected_native_heal)
emit('min_frame_rate', monitor.min_frame_rate)
emit('max_frame_rate', monitor.max_frame_rate)
emit('min_base_heal', monitor.min_base_heal)
emit('max_base_heal', monitor.max_base_heal)
emit('trace_overflow', monitor.trace_overflow)
emit('sample_count', type(monitor.samples) == 'table' and #monitor.samples or 0)
for index, sample in ipairs(monitor.samples or {}) do
  emit('sample.' .. index .. '.elapsed_ms', sample.elapsed_ms)
  emit('sample.' .. index .. '.tick_count', sample.tick_count)
  emit('sample.' .. index .. '.native_heal_count', sample.native_heal_count)
  emit('sample.' .. index .. '.expected_native_heal', sample.expected_native_heal)
  emit('sample.' .. index .. '.hp', sample.hp)
  emit('sample.' .. index .. '.mp', sample.mp)
end
""",
            timeout=8.0,
        )
    )
    count = int(raw.get("sample_count", "0"))
    samples = [
        {
            "elapsed": float(raw[f"sample.{index}.elapsed_ms"]) / 1000.0,
            "tick_count": int(raw[f"sample.{index}.tick_count"]),
            "native_heal_count": int(
                raw[f"sample.{index}.native_heal_count"]
            ),
            "expected_native_heal": float(
                raw[f"sample.{index}.expected_native_heal"]
            ),
            "hp": float(raw[f"sample.{index}.hp"]),
            "mp": float(raw[f"sample.{index}.mp"]),
        }
        for index in range(1, count + 1)
    ]
    if raw.get("done") != "true" or raw.get("error") or len(samples) < 2:
        raise VerifyFailure(
            f"Regenerate monitor did not complete cleanly on {pipe_name}: {raw}"
        )
    return {
        "tick_count": int(raw.get("tick_count", "0")),
        "native_heal_count": int(raw.get("native_heal_count", "0")),
        "expected_native_heal": float(
            raw.get("expected_native_heal", "0")
        ),
        "min_frame_rate": float(raw.get("min_frame_rate", "inf")),
        "max_frame_rate": float(raw.get("max_frame_rate", "0")),
        "min_base_heal": float(raw.get("min_base_heal", "inf")),
        "max_base_heal": float(raw.get("max_base_heal", "0")),
        "trace_overflow": raw.get("trace_overflow") == "true",
        "samples": samples,
    }


def sample_vitals_for(
    direction: Direction,
    duration: float,
    *,
    track_native_heals: bool = False,
) -> dict[str, Any]:
    observer = observer_pipe(direction)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        registration_futures = {
            "owner": executor.submit(
                ensure_vital_monitor_registered,
                direction.source_pipe,
            ),
            "observer": executor.submit(
                ensure_vital_monitor_registered,
                observer,
            ),
        }
        registrations = {
            label: future.result()
            for label, future in registration_futures.items()
        }
    trace_arm: dict[str, str] | None = None
    trace_disarm: dict[str, str] | None = None
    if track_native_heals:
        trace_arm = arm_native_heal_trace(direction.source_pipe)
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            start_futures = {
                "observer": executor.submit(
                    start_vital_monitor,
                    observer,
                    direction.source_id,
                    duration,
                ),
                "owner": executor.submit(
                    start_vital_monitor,
                    direction.source_pipe,
                    0,
                    duration,
                    track_native_heals=track_native_heals,
                ),
            }
            starts = {
                label: future.result()
                for label, future in start_futures.items()
            }

        deadline = time.monotonic() + duration + 10.0
        statuses: dict[str, dict[str, str]] = {}
        time.sleep(duration + 0.25)
        while time.monotonic() < deadline:
            statuses = {
                "owner": vital_monitor_status(direction.source_pipe),
                "observer": vital_monitor_status(observer),
            }
            if all(
                status.get("done") == "true"
                for status in statuses.values()
            ):
                break
            if any(status.get("error") for status in statuses.values()):
                raise VerifyFailure(
                    f"{direction.name} Regenerate monitor failed: {statuses}"
                )
            time.sleep(0.20)
        else:
            raise VerifyFailure(
                f"{direction.name} Regenerate monitor timed out: {statuses}"
            )

        owner_monitor = collect_vital_monitor(direction.source_pipe)
        observer_monitor = collect_vital_monitor(observer)
    finally:
        if track_native_heals:
            trace_disarm = disarm_native_heal_trace(direction.source_pipe)
    owner_samples = owner_monitor["samples"]
    observer_samples = observer_monitor["samples"]
    samples: list[dict[str, Any]] = []
    for owner_sample in owner_samples:
        observer_sample = min(
            observer_samples,
            key=lambda sample: abs(sample["elapsed"] - owner_sample["elapsed"]),
        )
        samples.append(
            {
                "elapsed": owner_sample["elapsed"],
                "owner_tick_count": owner_sample["tick_count"],
                "observer_tick_count": observer_sample["tick_count"],
                "owner_native_heal_count": owner_sample[
                    "native_heal_count"
                ],
                "owner_expected_native_heal": owner_sample[
                    "expected_native_heal"
                ],
                "owner_hp": owner_sample["hp"],
                "observer_hp": observer_sample["hp"],
                "owner_mp": owner_sample["mp"],
                "observer_mp": observer_sample["mp"],
            }
        )
    return {
        "duration": samples[-1]["elapsed"] - samples[0]["elapsed"],
        "sample_count": len(samples),
        "first": samples[0],
        "last": samples[-1],
        "owner_runtime_tick_count": owner_monitor["tick_count"],
        "observer_runtime_tick_count": observer_monitor["tick_count"],
        "owner_native_heal_count": owner_monitor["native_heal_count"],
        "owner_expected_native_heal": owner_monitor[
            "expected_native_heal"
        ],
        "owner_min_frame_rate": owner_monitor["min_frame_rate"],
        "owner_max_frame_rate": owner_monitor["max_frame_rate"],
        "owner_min_base_heal": owner_monitor["min_base_heal"],
        "owner_max_base_heal": owner_monitor["max_base_heal"],
        "native_trace_overflow": owner_monitor["trace_overflow"],
        "native_trace_arm": trace_arm,
        "native_trace_disarm": trace_disarm,
        "registrations": registrations,
        "starts": starts,
        "max_owner_observer_hp_error": max(
            abs(sample["owner_hp"] - sample["observer_hp"])
            for sample in samples
        ),
        "max_owner_observer_mp_error": max(
            abs(sample["owner_mp"] - sample["observer_mp"])
            for sample in samples
        ),
        "samples": samples,
    }


def assert_regenerate_inactive(
    direction: Direction,
    label: str,
    trial: dict[str, Any],
) -> dict[str, Any]:
    native_heal_count = (
        int(trial["last"]["owner_native_heal_count"])
        - int(trial["first"]["owner_native_heal_count"])
    )
    owner_delta = trial["last"]["owner_hp"] - trial["first"]["owner_hp"]
    observer_delta = (
        trial["last"]["observer_hp"] - trial["first"]["observer_hp"]
    )
    if native_heal_count != 0:
        raise VerifyFailure(
            f"{direction.name} {label} executed Regenerate's native heal "
            f"while inactive: count={native_heal_count} trial={trial}"
        )
    if owner_delta < -0.05 or observer_delta < -0.05:
        raise VerifyFailure(
            f"{direction.name} {label} lost HP in the quiet fixture: "
            f"owner_delta={owner_delta} observer_delta={observer_delta}"
        )
    if not math.isclose(owner_delta, observer_delta, abs_tol=0.20):
        raise VerifyFailure(
            f"{direction.name} {label} passive healing diverged: "
            f"owner_delta={owner_delta} observer_delta={observer_delta}"
        )
    return {
        "owner_passive_healed": owner_delta,
        "observer_passive_healed": observer_delta,
        "native_regenerate_heal_updates": native_heal_count,
        "ok": True,
    }


def assert_regeneration(
    direction: Direction,
    trial: dict[str, Any],
) -> dict[str, Any]:
    elapsed = trial["last"]["elapsed"] - trial["first"]["elapsed"]
    native_heal_count = (
        int(trial["last"]["owner_native_heal_count"])
        - int(trial["first"]["owner_native_heal_count"])
    )
    expected_native_heal = (
        float(trial["last"]["owner_expected_native_heal"])
        - float(trial["first"]["owner_expected_native_heal"])
    )
    owner_delta = trial["last"]["owner_hp"] - trial["first"]["owner_hp"]
    observer_delta = (
        trial["last"]["observer_hp"] - trial["first"]["observer_hp"]
    )
    if elapsed <= 0.0 or native_heal_count <= 0:
        raise VerifyFailure(
            f"{direction.name} native Regenerate update did not advance: {trial}"
        )
    if trial["native_trace_overflow"]:
        raise VerifyFailure(
            f"{direction.name} native Regenerate trace overflowed: {trial}"
        )
    owner_rate = owner_delta / elapsed
    observer_rate = observer_delta / elapsed
    owner_heal_per_update = owner_delta / native_heal_count
    expected_heal_per_update = expected_native_heal / native_heal_count
    if not math.isclose(
        owner_delta,
        expected_native_heal,
        abs_tol=NATIVE_HEAL_DELTA_TOLERANCE,
    ):
        raise VerifyFailure(
            f"{direction.name} Regenerate diverged from its stock native "
            f"updates: owner_delta={owner_delta} "
            f"expected_native_heal={expected_native_heal} trial={trial}"
        )
    if not math.isclose(
        owner_heal_per_update,
        expected_heal_per_update,
        abs_tol=NATIVE_HEAL_PER_UPDATE_TOLERANCE,
    ):
        raise VerifyFailure(
            f"{direction.name} Regenerate per-update heal diverged: "
            f"observed={owner_heal_per_update} "
            f"expected={expected_heal_per_update} trial={trial}"
        )
    if observer_delta <= 0.0:
        raise VerifyFailure(
            f"{direction.name} observer did not replicate Regenerate healing: "
            f"owner_delta={owner_delta} observer_delta={observer_delta}"
        )
    if trial["max_owner_observer_hp_error"] > OWNER_OBSERVER_HP_ENVELOPE:
        raise VerifyFailure(
            f"{direction.name} Regenerate observer lag exceeded the "
            f"replication envelope: "
            f"{trial['max_owner_observer_hp_error']}"
        )
    return {
        "owner_healed": owner_delta,
        "observer_healed": observer_delta,
        "owner_heal_per_second": owner_rate,
        "observer_heal_per_second": observer_rate,
        "owner_native_heal_updates": native_heal_count,
        "owner_native_heal_updates_per_second": native_heal_count / elapsed,
        "owner_heal_per_native_update": owner_heal_per_update,
        "expected_heal_per_native_update": expected_heal_per_update,
        "expected_native_heal": expected_native_heal,
        "native_heal_instruction": NATIVE_REGENERATE_HEAL_INSTRUCTION,
        "runtime_frame_rate_global": RUNTIME_FRAME_RATE_GLOBAL,
        "progression_health_regeneration_offset": (
            PROGRESSION_HEALTH_REGEN_OFFSET
        ),
        "native_heal_numerator": NATIVE_HEAL_NUMERATOR,
        "native_base_heal_divisor": NATIVE_BASE_HEAL_DIVISOR,
        "min_runtime_frame_rate": trial["owner_min_frame_rate"],
        "max_runtime_frame_rate": trial["owner_max_frame_rate"],
        "min_base_health_regeneration": trial["owner_min_base_heal"],
        "max_base_health_regeneration": trial["owner_max_base_heal"],
        "max_owner_observer_hp_error": trial["max_owner_observer_hp_error"],
        "ok": True,
    }


def run_direction(
    direction: Direction,
    acquisition: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    resource_reset = set_local_player_vitals(
        direction.source_pipe,
        START_HP,
        MAX_HP,
        mp=START_MP,
        max_mp=MAX_MP,
    )
    baseline_convergence = wait_for_vitals(
        direction,
        START_HP,
        START_MP,
        timeout,
    )
    baseline = sample_vitals_for(
        direction,
        BASELINE_SECONDS,
        track_native_heals=True,
    )
    baseline_behavior = assert_regenerate_inactive(
        direction,
        "baseline",
        baseline,
    )

    activated = toggle_once(
        direction,
        belt_slot=int(acquisition["belt_slot"]),
        expected_values=PERSISTENT_REGENERATE,
        timeout=timeout,
    )
    hoard_property = query_ranked_numeric_stat(
        direction.source_pipe,
        REGENERATE_ROW,
        "mHoard",
    )
    if not hoard_property["property_found"]:
        raise VerifyFailure(
            f"{direction.name} Regenerate mHoard is unavailable: {hoard_property}"
        )
    expected_mp = MAX_MP * (
        1.0 - float(hoard_property["value"]) / 100.0
    )
    activation_convergence = wait_for_vitals(
        direction,
        None,
        expected_mp,
        timeout,
        hp_tolerance=1.05,
    )
    active_resource_reset = set_local_player_vitals(
        direction.source_pipe,
        START_HP,
        MAX_HP,
        mp=START_MP,
        max_mp=MAX_MP,
    )
    active_convergence = wait_for_vitals(
        direction,
        START_HP,
        expected_mp,
        timeout,
        hp_tolerance=1.05,
    )
    active = sample_vitals_for(
        direction,
        ACTIVE_SECONDS,
        track_native_heals=True,
    )
    behavior = assert_regeneration(direction, active)
    post_active_convergence = wait_for_vitals(
        direction,
        None,
        expected_mp,
        timeout,
        hp_tolerance=0.20,
    )

    deactivated = toggle_once(
        direction,
        belt_slot=int(acquisition["belt_slot"]),
        expected_values=0,
        timeout=timeout,
    )
    restored = sample_vitals_for(
        direction,
        RESTORED_SECONDS,
        track_native_heals=True,
    )
    restored_behavior = assert_regenerate_inactive(
        direction,
        "restored",
        restored,
    )
    return {
        "resource_reset": resource_reset,
        "baseline_convergence": baseline_convergence,
        "baseline": baseline,
        "baseline_behavior": baseline_behavior,
        "activated": activated,
        "hoard_property": hoard_property,
        "expected_active_mp": expected_mp,
        "activation_convergence": activation_convergence,
        "active_resource_reset": active_resource_reset,
        "active_convergence": active_convergence,
        "active": active,
        "behavior": behavior,
        "post_active_convergence": post_active_convergence,
        "deactivated": deactivated,
        "restored": restored,
        "restored_behavior": restored_behavior,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=25.0)
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
            manual_combat=False,
            prearm_manual_spawner=True,
        )
        output["launch"] = startup["launch"]
        output["combat_prelude"] = enable_unsuppressed_combat_prelude(
            args.timeout
        )
        output["post_run_progression_ready"] = (
            wait_for_post_run_progression_ready(args.timeout)
        )
        acquisitions = {
            direction.name: acquire_secondary_to_rank(
                direction,
                REGENERATE_ROW,
                1,
                args.timeout,
            )
            for direction in DIRECTIONS
        }
        output["acquisitions"] = acquisitions
        output["directions"] = {}
        for direction in DIRECTIONS:
            output["directions"][direction.name] = run_direction(
                direction,
                acquisitions[direction.name],
                args.timeout,
            )

        crashes = new_crash_artifacts(started_at)
        output["new_crash_artifacts"] = crashes
        if crashes:
            raise VerifyFailure(
                f"new crash artifacts during Regenerate test: {crashes}"
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
