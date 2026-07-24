#!/usr/bin/env python3
"""Verify organic multi-enemy convergence and client Air cast edge timing."""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
import os
import re
import select
import statistics
import subprocess
import time
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_NAME,
    HOST_ID,
    HOST_NAME,
    ROOT,
    VerifyFailure,
    game_process_ids,
    launch_pair,
    lua,
    parse_key_values,
    path_for_powershell,
    select_available_windows_udp_ports,
    start_testrun,
    stop_game_processes,
    wait_for_remote,
    wait_for_scene,
)
from verify_player_health_death_sync import set_local_player_vitals
from verify_real_input_spell_cast_sync import Direction, queue_gameplay_mouse_left


OUTPUT = ROOT / "runtime" / "multiplayer_organic_enemy_cast_timing.json"
ACCEPTANCE_MOD_ID = "sample.lua.ui_sandbox_lab"
AIR_SKILL_ID = 24
AIR_HOLD_FRAMES = 12
MINIMUM_LIVE_ENEMIES = 6
MINIMUM_MOVING_ENEMIES = 4
MINIMUM_POSITION_COMPARISONS = 100
MAXIMUM_CLIENT_ARRIVAL_GAP_MS = 300.0
P95_CLIENT_ARRIVAL_GAP_MS = 180.0
MAXIMUM_HOST_CLIENT_POSITION_ERROR = 64.0
P95_HOST_CLIENT_POSITION_ERROR = 24.0
MAXIMUM_CLIENT_CLONE_POSITION_ERROR = 64.0
P95_CLIENT_CLONE_POSITION_ERROR = 24.0
MAXIMUM_HP_ERROR = 0.1
MAXIMUM_STATE_MISMATCH_RATIO = 0.05
MAXIMUM_TRACK_INTERPOLATION_GAP_MS = 200.0
MAXIMUM_NATIVE_ALIGNMENT_GAP_MS = 100.0
NATIVE_LAG_SEARCH_MAX_MS = 600
NATIVE_LAG_SEARCH_STEP_MS = 16
MINIMUM_NATIVE_LAG_COMPARISONS = 20
MINIMUM_NATIVE_LAG_DISPLACEMENT = 16.0
FIDELITY_GHOST_WARMUP_MS = 1000.0
MAXIMUM_NATIVE_POSITION_ERROR = 44.0
P95_NATIVE_POSITION_ERROR = 32.0
P95_NATIVE_LAG_MS = 304.0
P95_PRESENTATION_SOURCE_AGE_MS = 200.0
CLIENT_TELEPORT_MINIMUM_DISTANCE = 48.0
CLIENT_TELEPORT_HOST_DISTANCE_FACTOR = 2.5
CLIENT_TELEPORT_HOST_DISTANCE_ALLOWANCE = 8.0
CLIENT_RUBBER_BAND_MINIMUM_STEP = 6.0
CLIENT_FREEZE_MAXIMUM_STEP = 0.5
HOST_FREEZE_MINIMUM_STEP = 8.0
MINIMUM_GLITCH_EPISODE_SAMPLES = 3
DEFAULT_NETWORK_LATENCY_MS = 40.0
DEFAULT_NETWORK_JITTER_MS = 12.0
DEFAULT_NETWORK_PROXY_SEED = 8242
MAXIMUM_CAST_START_LATENCY_MS = 150.0
MAXIMUM_CAST_STOP_LATENCY_MS = 150.0
MAXIMUM_CAST_DURATION_ERROR_MS = 100.0
MAXIMUM_CAST_COMPLETION_AFTER_RELEASE_MS = 250.0
TEST_PLAYER_HP = 5000.0


ARM_WORLD_PROBE_LUA = r"""
local sample_limit = tonumber("__SAMPLE_LIMIT__") or 400
local function emit(key, value) print(key .. "=" .. tostring(value)) end
_G.__sdmod_organic_enemy_sync_probe = {
  active = true,
  samples = {},
  sample_limit = sample_limit,
}
if not _G.__sdmod_organic_enemy_sync_probe_registered then
  sd.events.on("runtime.tick", function(event)
    local probe = _G.__sdmod_organic_enemy_sync_probe
    if type(probe) ~= "table" or not probe.active then return end
    local replicated = sd.world.get_replicated_actors and
      sd.world.get_replicated_actors() or nil
    local received_ms = tonumber(replicated and replicated.received_ms) or 0
    if replicated == nil or received_ms <= 0 then return end

    local local_by_address = {}
    local local_by_identity = {}
    local tracked_local_count = 0
    for _, actor in ipairs(sd.world.list_actors and sd.world.list_actors() or {}) do
      local address = tonumber(actor.actor_address) or 0
      if address ~= 0 then local_by_address[address] = actor end
      if actor.tracked_enemy then
        tracked_local_count = tracked_local_count + 1
        local key = table.concat({
          tostring(tonumber(actor.object_type_id) or 0),
          tostring(tonumber(actor.actor_slot) or -1),
          tostring(tonumber(actor.world_slot) or -1),
        }, ":")
        local_by_identity[key] = actor
      end
    end
    local local_by_id = {}
    for _, binding in ipairs(replicated.bindings or {}) do
      local network_id = tonumber(binding.network_actor_id) or 0
      local address = tonumber(binding.local_actor_address) or 0
      if network_id ~= 0 and address ~= 0 and binding.matched and
          not binding.parked and not binding.removed then
        local_by_id[network_id] = local_by_address[address]
      end
    end

    local actors = {}
    local resolved_local_addresses = {}
    for _, actor in ipairs(replicated.actors or {}) do
      local network_id = tonumber(actor.network_actor_id) or 0
      if network_id ~= 0 and actor.tracked_enemy then
        local local_actor = local_by_id[network_id]
        if local_actor == nil then
          local key = table.concat({
            tostring(tonumber(actor.object_type_id) or 0),
            tostring(tonumber(actor.actor_slot) or -1),
            tostring(tonumber(actor.world_slot) or -1),
          }, ":")
          local_actor = local_by_identity[key]
        end
        if local_actor ~= nil then
          local address = tonumber(local_actor.actor_address) or 0
          if address ~= 0 then resolved_local_addresses[address] = true end
        end
        actors[#actors + 1] = {
          id = network_id,
          x = tonumber(actor.x) or 0,
          y = tonumber(actor.y) or 0,
          hp = tonumber(actor.hp) or 0,
          dead = actor.dead and 1 or 0,
          anim = tonumber(actor.anim_drive_state) or 0,
          target = tonumber(actor.target_participant_id) or 0,
          local_x = local_actor and tonumber(local_actor.x) or nil,
          local_y = local_actor and tonumber(local_actor.y) or nil,
          local_hp = local_actor and tonumber(local_actor.hp) or nil,
          local_dead = local_actor and (local_actor.dead and 1 or 0) or nil,
          local_anim = local_actor and tonumber(local_actor.anim_drive_state) or nil,
        }
      end
    end
    table.sort(actors, function(left, right) return left.id < right.id end)
    local bound_local_count = 0
    for _ in pairs(resolved_local_addresses) do
      bound_local_count = bound_local_count + 1
    end
    probe.samples[#probe.samples + 1] = {
      monotonic_ms = tonumber(event and event.monotonic_milliseconds) or 0,
      received_ms = received_ms,
      sequence = tonumber(replicated.sequence) or 0,
      presentation_received_ms =
        tonumber(replicated.apply_presentation_received_ms) or 0,
      apply_sequence = tonumber(replicated.apply_sequence) or 0,
      source_age_ms =
        tonumber(replicated.apply_source_snapshot_age_ms) or 0,
      local_count = tracked_local_count,
      bound_local_count = bound_local_count,
      unbound_local_count =
        math.max(0, tracked_local_count - bound_local_count),
      actors = actors,
    }
    if #probe.samples >= probe.sample_limit then probe.active = false end
  end)
  _G.__sdmod_organic_enemy_sync_probe_registered = true
end
emit("registered", _G.__sdmod_organic_enemy_sync_probe_registered)
emit("active", _G.__sdmod_organic_enemy_sync_probe.active)
"""


QUERY_WORLD_PROBE_LUA = r"""
local probe = _G.__sdmod_organic_enemy_sync_probe
if type(probe) ~= "table" then error("organic enemy sync probe is unavailable") end
probe.active = false
local first = tonumber("__FIRST_SAMPLE__") or 1
local count = tonumber("__SAMPLE_COUNT__") or 16
local last = math.min(#(probe.samples or {}), first + count - 1)
for index = first, last do
  local sample = probe.samples[index]
  local actors = {}
  for _, actor in ipairs(sample.actors or {}) do
    actors[#actors + 1] = table.concat({
      string.format("%.0f", actor.id or 0),
      string.format("%.6f", actor.x or 0),
      string.format("%.6f", actor.y or 0),
      string.format("%.6f", actor.hp or 0),
      tostring(actor.dead or 0),
      tostring(actor.anim or 0),
      string.format("%.0f", actor.target or 0),
      actor.local_x == nil and "" or string.format("%.6f", actor.local_x),
      actor.local_y == nil and "" or string.format("%.6f", actor.local_y),
      actor.local_hp == nil and "" or string.format("%.6f", actor.local_hp),
      actor.local_dead == nil and "" or tostring(actor.local_dead),
      actor.local_anim == nil and "" or tostring(actor.local_anim),
    }, ",")
  end
  print(table.concat({
    "S",
    tostring(sample.monotonic_ms or 0),
    tostring(sample.received_ms or 0),
    tostring(sample.sequence or 0),
    tostring(sample.presentation_received_ms or 0),
    tostring(sample.apply_sequence or 0),
    tostring(sample.source_age_ms or 0),
    tostring(sample.local_count or 0),
    tostring(sample.bound_local_count or 0),
    tostring(sample.unbound_local_count or 0),
    table.concat(actors, ";"),
  }, "|"))
end
"""


STOP_WORLD_PROBE_LUA = r"""
local probe = _G.__sdmod_organic_enemy_sync_probe
if type(probe) ~= "table" then error("organic enemy sync probe is unavailable") end
probe.active = false
print("count=" .. tostring(#(probe.samples or {})))
"""


LIVE_ENEMY_COUNT_LUA = r"""
local live = 0
for _, actor in ipairs(sd.world.list_actors and sd.world.list_actors() or {}) do
  if actor.tracked_enemy and not actor.dead and
      (tonumber(actor.hp) or 0) > 0 then
    live = live + 1
  end
end
print("live=" .. tostring(live))
"""


PLAYER_HP_LUA = r"""
local player = sd.player.get_state()
print("hp=" .. tostring(player and player.hp or 0))
"""


def _default_instance_prefix() -> str:
    return f"n82-{os.getpid():x}-{uuid.uuid4().hex[:4]}"


def _log_path(instance_prefix: str, role: str) -> Path:
    return (
        ROOT
        / "runtime"
        / "instances"
        / f"{instance_prefix}-{role}"
        / "stage"
        / ".sdmod"
        / "logs"
        / "solomondarkmodloader.log"
    )


def _read_log_after(path: Path, offset: int) -> str:
    if not path.is_file():
        return ""
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        handle.seek(offset)
        return handle.read()


def _log_offset(path: Path) -> int:
    return path.stat().st_size if path.is_file() else 0


def _wait_for_live_enemies(pipe_name: str, timeout: float) -> int:
    deadline = time.monotonic() + timeout
    last = 0
    while time.monotonic() < deadline:
        values = parse_key_values(lua(pipe_name, LIVE_ENEMY_COUNT_LUA))
        last = int(float(values.get("live", "0")))
        if last >= MINIMUM_LIVE_ENEMIES:
            return last
        time.sleep(0.1)
    raise VerifyFailure(
        f"organic combat did not produce {MINIMUM_LIVE_ENEMIES} live enemies; "
        f"last={last}"
    )


def _disable_companion_bots(pipe_names: list[str]) -> None:
    code = (
        "lua_bots_disable_tick = true; sd.bots.clear(); "
        "return tostring(sd.bots.get_count())"
    )
    for pipe_name in pipe_names:
        if lua(pipe_name, code).strip() != "0":
            raise VerifyFailure(
                f"failed to disable companion bots on {pipe_name}"
            )


def _start_waves(host_pipe: str) -> dict[str, str]:
    values = parse_key_values(
        lua(
            host_pipe,
            "print('ok=' .. tostring(sd.gameplay.start_waves()))",
        )
    )
    if values.get("ok") != "true":
        raise VerifyFailure(f"host could not start organic combat: {values}")
    return values


def _start_testrun_when_ready(host_pipe: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        try:
            start_testrun(host_pipe)
            return
        except VerifyFailure as exc:
            last_error = str(exc)
            time.sleep(0.25)
    raise VerifyFailure(
        f"host testrun request never reached spawn readiness: {last_error}"
    )


def _player_hp(pipe_name: str) -> float:
    values = parse_key_values(lua(pipe_name, PLAYER_HP_LUA))
    return float(values.get("hp", "0"))


def _parse_optional_float(value: str) -> float | None:
    return None if value == "" else float(value)


def parse_world_probe(text: str) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for raw_line in text.splitlines():
        if not raw_line.startswith("S|"):
            continue
        parts = raw_line.split("|", 10)
        if len(parts) not in (5, 11):
            raise VerifyFailure(f"malformed world probe sample: {raw_line!r}")
        if len(parts) == 5:
            actor_text = parts[4]
            presentation_received_ms = 0
            apply_sequence = 0
            source_age_ms = 0
            local_count = 0
            bound_local_count = 0
            unbound_local_count = 0
        else:
            actor_text = parts[10]
            presentation_received_ms = int(parts[4])
            apply_sequence = int(parts[5])
            source_age_ms = int(parts[6])
            local_count = int(parts[7])
            bound_local_count = int(parts[8])
            unbound_local_count = int(parts[9])
        actors: dict[int, dict[str, Any]] = {}
        for encoded_actor in filter(None, actor_text.split(";")):
            fields = encoded_actor.split(",")
            if len(fields) != 12:
                raise VerifyFailure(
                    f"malformed world probe actor: {encoded_actor!r}"
                )
            network_id = int(fields[0])
            actors[network_id] = {
                "x": float(fields[1]),
                "y": float(fields[2]),
                "hp": float(fields[3]),
                "dead": int(fields[4]),
                "anim": int(fields[5]),
                "target": int(fields[6]),
                "local_x": _parse_optional_float(fields[7]),
                "local_y": _parse_optional_float(fields[8]),
                "local_hp": _parse_optional_float(fields[9]),
                "local_dead": None if fields[10] == "" else int(fields[10]),
                "local_anim": None if fields[11] == "" else int(fields[11]),
            }
        samples.append(
            {
                "monotonic_ms": int(parts[1]),
                "received_ms": int(parts[2]),
                "sequence": int(parts[3]),
                "presentation_received_ms": presentation_received_ms,
                "apply_sequence": apply_sequence,
                "source_age_ms": source_age_ms,
                "local_count": local_count,
                "bound_local_count": bound_local_count,
                "unbound_local_count": unbound_local_count,
                "actors": actors,
            }
        )
    return samples


def _read_world_probe(pipe_name: str) -> list[dict[str, Any]]:
    status = parse_key_values(
        lua(pipe_name, STOP_WORLD_PROBE_LUA, timeout=15.0)
    )
    sample_count = int(status.get("count", "0"))
    samples: list[dict[str, Any]] = []
    chunk_size = 16
    for first_sample in range(1, sample_count + 1, chunk_size):
        query = QUERY_WORLD_PROBE_LUA.replace(
            "__FIRST_SAMPLE__",
            str(first_sample),
        ).replace(
            "__SAMPLE_COUNT__",
            str(chunk_size),
        )
        samples.extend(
            parse_world_probe(lua(pipe_name, query, timeout=15.0))
        )
    return samples


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return math.inf
    ordered = sorted(values)
    index = max(
        0,
        min(
            len(ordered) - 1,
            math.ceil(percentile * len(ordered)) - 1,
        ),
    )
    return ordered[index]


def _native_actor_tracks(
    samples: list[dict[str, Any]],
) -> dict[int, dict[str, list[Any]]]:
    tracks: dict[int, dict[str, list[Any]]] = {}
    for sample in samples:
        sampled_ms = float(sample["monotonic_ms"])
        for network_id, actor in sample["actors"].items():
            if (
                actor["local_x"] is None
                or actor["local_y"] is None
                or actor["local_dead"] not in (None, 0)
                or (
                    actor["local_hp"] is not None
                    and actor["local_hp"] <= 0.0
                )
            ):
                continue
            track = tracks.setdefault(
                network_id,
                {"times": [], "positions": []},
            )
            if track["times"] and track["times"][-1] == sampled_ms:
                track["positions"][-1] = (
                    float(actor["local_x"]),
                    float(actor["local_y"]),
                )
                continue
            track["times"].append(sampled_ms)
            track["positions"].append(
                (float(actor["local_x"]), float(actor["local_y"]))
            )
    return tracks


def _interpolate_track(
    track: dict[str, list[Any]],
    sampled_ms: float,
) -> tuple[float, float] | None:
    times = track["times"]
    positions = track["positions"]
    if not times:
        return None
    index = bisect.bisect_left(times, sampled_ms)
    if index < len(times) and times[index] == sampled_ms:
        return positions[index]
    if index == 0 or index >= len(times):
        return None
    before_ms = times[index - 1]
    after_ms = times[index]
    interval_ms = after_ms - before_ms
    if (
        interval_ms <= 0.0
        or interval_ms > MAXIMUM_TRACK_INTERPOLATION_GAP_MS
    ):
        return None
    alpha = (sampled_ms - before_ms) / interval_ms
    before_x, before_y = positions[index - 1]
    after_x, after_y = positions[index]
    return (
        before_x + (after_x - before_x) * alpha,
        before_y + (after_y - before_y) * alpha,
    )


def _track_displacement(track: dict[str, list[Any]]) -> float:
    positions = track["positions"]
    if not positions:
        return 0.0
    first_x, first_y = positions[0]
    return max(
        math.hypot(x - first_x, y - first_y)
        for x, y in positions
    )


def _event_episode_count(
    event_times: list[float],
    *,
    minimum_samples: int = 1,
) -> int:
    if not event_times:
        return 0
    episodes = 0
    run_length = 1
    for before_ms, after_ms in zip(event_times, event_times[1:]):
        if after_ms - before_ms <= MAXIMUM_NATIVE_ALIGNMENT_GAP_MS * 1.5:
            run_length += 1
            continue
        episodes += int(run_length >= minimum_samples)
        run_length = 1
    episodes += int(run_length >= minimum_samples)
    return episodes


def _nearest_sample(
    samples: list[dict[str, Any]],
    times: list[float],
    sampled_ms: float,
) -> dict[str, Any] | None:
    if not times:
        return None
    index = bisect.bisect_left(times, sampled_ms)
    candidates = []
    if index < len(samples):
        candidates.append(samples[index])
    if index > 0:
        candidates.append(samples[index - 1])
    if not candidates:
        return None
    nearest = min(
        candidates,
        key=lambda sample: abs(float(sample["monotonic_ms"]) - sampled_ms),
    )
    if (
        abs(float(nearest["monotonic_ms"]) - sampled_ms)
        > MAXIMUM_NATIVE_ALIGNMENT_GAP_MS
    ):
        return None
    return nearest


def _direction_cosine(
    first: tuple[float, float],
    second: tuple[float, float],
) -> float:
    first_length = math.hypot(*first)
    second_length = math.hypot(*second)
    if first_length == 0.0 or second_length == 0.0:
        return 1.0
    return (
        first[0] * second[0] + first[1] * second[1]
    ) / (first_length * second_length)


def analyze_native_fidelity(
    host_samples: list[dict[str, Any]],
    client_samples: list[dict[str, Any]],
) -> dict[str, Any]:
    host_tracks = _native_actor_tracks(host_samples)
    client_tracks = _native_actor_tracks(client_samples)
    common_ids = sorted(set(host_tracks) & set(client_tracks))

    aligned_errors: list[float] = []
    client_step_distances: list[float] = []
    teleport_times: list[float] = []
    rubber_band_times: list[float] = []
    freeze_times: list[float] = []
    actor_lag_estimates: list[dict[str, Any]] = []
    for network_id in common_ids:
        host_track = host_tracks[network_id]
        client_track = client_tracks[network_id]
        for sampled_ms, (client_x, client_y) in zip(
            client_track["times"],
            client_track["positions"],
        ):
            host_position = _interpolate_track(host_track, sampled_ms)
            if host_position is None:
                continue
            aligned_errors.append(
                math.hypot(
                    client_x - host_position[0],
                    client_y - host_position[1],
                )
            )

        times = client_track["times"]
        positions = client_track["positions"]
        for index in range(1, len(times)):
            before_ms = times[index - 1]
            after_ms = times[index]
            if (
                after_ms <= before_ms
                or after_ms - before_ms > MAXIMUM_NATIVE_ALIGNMENT_GAP_MS
            ):
                continue
            before_x, before_y = positions[index - 1]
            after_x, after_y = positions[index]
            client_step = math.hypot(
                after_x - before_x,
                after_y - before_y,
            )
            client_step_distances.append(client_step)
            host_before = _interpolate_track(host_track, before_ms)
            host_after = _interpolate_track(host_track, after_ms)
            if host_before is None or host_after is None:
                continue
            host_step = math.hypot(
                host_after[0] - host_before[0],
                host_after[1] - host_before[1],
            )
            if (
                client_step >= CLIENT_TELEPORT_MINIMUM_DISTANCE
                and client_step
                > (
                    host_step * CLIENT_TELEPORT_HOST_DISTANCE_FACTOR
                    + CLIENT_TELEPORT_HOST_DISTANCE_ALLOWANCE
                )
            ):
                teleport_times.append(after_ms)
            if (
                client_step <= CLIENT_FREEZE_MAXIMUM_STEP
                and host_step >= HOST_FREEZE_MINIMUM_STEP
            ):
                freeze_times.append(after_ms)

        for index in range(2, len(times)):
            first_ms = times[index - 2]
            middle_ms = times[index - 1]
            last_ms = times[index]
            if (
                middle_ms - first_ms > MAXIMUM_NATIVE_ALIGNMENT_GAP_MS
                or last_ms - middle_ms > MAXIMUM_NATIVE_ALIGNMENT_GAP_MS
            ):
                continue
            first = positions[index - 2]
            middle = positions[index - 1]
            last = positions[index]
            client_before = (
                middle[0] - first[0],
                middle[1] - first[1],
            )
            client_after = (
                last[0] - middle[0],
                last[1] - middle[1],
            )
            if (
                math.hypot(*client_before)
                < CLIENT_RUBBER_BAND_MINIMUM_STEP
                or math.hypot(*client_after)
                < CLIENT_RUBBER_BAND_MINIMUM_STEP
                or _direction_cosine(client_before, client_after) > -0.5
            ):
                continue
            host_first = _interpolate_track(host_track, first_ms)
            host_middle = _interpolate_track(host_track, middle_ms)
            host_last = _interpolate_track(host_track, last_ms)
            if (
                host_first is None
                or host_middle is None
                or host_last is None
            ):
                continue
            host_before = (
                host_middle[0] - host_first[0],
                host_middle[1] - host_first[1],
            )
            host_after = (
                host_last[0] - host_middle[0],
                host_last[1] - host_middle[1],
            )
            if (
                math.hypot(*host_before) >= 1.0
                and math.hypot(*host_after) >= 1.0
                and _direction_cosine(host_before, host_after) >= 0.0
            ):
                rubber_band_times.append(last_ms)

        if (
            _track_displacement(host_track)
            < MINIMUM_NATIVE_LAG_DISPLACEMENT
        ):
            continue
        best: tuple[float, float, int, int] | None = None
        for lag_ms in range(
            0,
            NATIVE_LAG_SEARCH_MAX_MS + 1,
            NATIVE_LAG_SEARCH_STEP_MS,
        ):
            errors = []
            for sampled_ms, (client_x, client_y) in zip(
                client_track["times"],
                client_track["positions"],
            ):
                host_position = _interpolate_track(
                    host_track,
                    sampled_ms - lag_ms,
                )
                if host_position is None:
                    continue
                errors.append(
                    math.hypot(
                        client_x - host_position[0],
                        client_y - host_position[1],
                    )
                )
            if len(errors) < MINIMUM_NATIVE_LAG_COMPARISONS:
                continue
            candidate = (
                _percentile(errors, 0.75),
                statistics.fmean(errors),
                lag_ms,
                len(errors),
            )
            if best is None or candidate[:3] < best[:3]:
                best = candidate
        if best is not None:
            actor_lag_estimates.append(
                {
                    "network_actor_id": network_id,
                    "lag_ms": best[2],
                    "p75_residual_error": best[0],
                    "mean_residual_error": best[1],
                    "comparison_count": best[3],
                }
            )

    host_times = [float(sample["monotonic_ms"]) for sample in host_samples]
    ghost_measurement_start_ms = (
        max(
            float(host_samples[0]["monotonic_ms"]),
            float(client_samples[0]["monotonic_ms"]),
        )
        + FIDELITY_GHOST_WARMUP_MS
        if host_samples and client_samples
        else math.inf
    )
    missing_times_by_id: dict[int, list[float]] = {}
    extra_times_by_id: dict[int, list[float]] = {}
    unbound_extra_times: list[float] = []
    ghost_sample_count = 0
    for client_sample in client_samples:
        sampled_ms = float(client_sample["monotonic_ms"])
        if sampled_ms < ghost_measurement_start_ms:
            continue
        host_sample = _nearest_sample(host_samples, host_times, sampled_ms)
        if host_sample is None:
            continue
        host_alive = {
            network_id
            for network_id, actor in host_sample["actors"].items()
            if actor["local_x"] is not None
            and actor["local_y"] is not None
            and actor["local_dead"] in (None, 0)
            and (
                actor["local_hp"] is None
                or actor["local_hp"] > 0.0
            )
        }
        client_alive = {
            network_id
            for network_id, actor in client_sample["actors"].items()
            if actor["local_x"] is not None
            and actor["local_y"] is not None
            and actor["local_dead"] in (None, 0)
            and (
                actor["local_hp"] is None
                or actor["local_hp"] > 0.0
            )
        }
        for network_id in host_alive - client_alive:
            missing_times_by_id.setdefault(network_id, []).append(sampled_ms)
            ghost_sample_count += 1
        for network_id in client_alive - host_alive:
            extra_times_by_id.setdefault(network_id, []).append(sampled_ms)
            ghost_sample_count += 1
        unbound_count = int(client_sample.get("unbound_local_count", 0))
        if unbound_count > 0:
            unbound_extra_times.append(sampled_ms)
            ghost_sample_count += unbound_count

    lag_values = [
        float(estimate["lag_ms"])
        for estimate in actor_lag_estimates
    ]
    source_ages = [
        float(sample.get("source_age_ms", 0))
        for sample in client_samples
        if sample.get("source_age_ms", 0) > 0
    ]
    host_first_received_by_sequence: dict[int, int] = {}
    for sample in host_samples:
        host_first_received_by_sequence.setdefault(
            int(sample["sequence"]),
            int(sample["received_ms"]),
        )
    client_first_received_by_sequence: dict[int, int] = {}
    for sample in client_samples:
        client_first_received_by_sequence.setdefault(
            int(sample["sequence"]),
            int(sample["received_ms"]),
        )
    transport_latencies = [
        float(client_received - host_first_received_by_sequence[sequence])
        for sequence, client_received
        in client_first_received_by_sequence.items()
        if sequence in host_first_received_by_sequence
        and client_received >= host_first_received_by_sequence[sequence]
    ]

    ghost_episode_count = sum(
        _event_episode_count(
            times,
            minimum_samples=MINIMUM_GLITCH_EPISODE_SAMPLES,
        )
        for times in (
            list(missing_times_by_id.values())
            + list(extra_times_by_id.values())
        )
    )
    ghost_episode_count += _event_episode_count(
        unbound_extra_times,
        minimum_samples=MINIMUM_GLITCH_EPISODE_SAMPLES,
    )
    return {
        "common_native_enemy_count": len(common_ids),
        "native_position_comparison_count": len(aligned_errors),
        "p50_native_position_error": _percentile(aligned_errors, 0.50),
        "p95_native_position_error": _percentile(aligned_errors, 0.95),
        "maximum_native_position_error": max(
            aligned_errors,
            default=math.inf,
        ),
        "native_lag_actor_count": len(actor_lag_estimates),
        "p50_native_lag_ms": _percentile(lag_values, 0.50),
        "p95_native_lag_ms": _percentile(lag_values, 0.95),
        "maximum_native_lag_ms": max(lag_values, default=math.inf),
        "native_lag_by_actor": actor_lag_estimates,
        "p95_client_native_step_distance": _percentile(
            client_step_distances,
            0.95,
        ),
        "maximum_client_native_step_distance": max(
            client_step_distances,
            default=math.inf,
        ),
        "teleport_event_count": len(teleport_times),
        "teleport_episode_count": _event_episode_count(teleport_times),
        "rubber_band_event_count": len(rubber_band_times),
        "rubber_band_episode_count": _event_episode_count(
            rubber_band_times,
        ),
        "freeze_event_count": len(freeze_times),
        "freeze_episode_count": _event_episode_count(
            freeze_times,
            minimum_samples=MINIMUM_GLITCH_EPISODE_SAMPLES,
        ),
        "ghost_sample_count": ghost_sample_count,
        "ghost_episode_count": ghost_episode_count,
        "ghost_measurement_start_ms": ghost_measurement_start_ms,
        "missing_client_enemy_ids": sorted(missing_times_by_id),
        "extra_client_enemy_ids": sorted(extra_times_by_id),
        "unbound_client_sample_count": len(unbound_extra_times),
        "p50_presentation_source_age_ms": _percentile(source_ages, 0.50),
        "p95_presentation_source_age_ms": _percentile(source_ages, 0.95),
        "maximum_presentation_source_age_ms": max(
            source_ages,
            default=math.inf,
        ),
        "transport_latency_comparison_count": len(transport_latencies),
        "p50_transport_latency_ms": _percentile(
            transport_latencies,
            0.50,
        ),
        "p95_transport_latency_ms": _percentile(
            transport_latencies,
            0.95,
        ),
        "maximum_transport_latency_ms": max(
            transport_latencies,
            default=math.inf,
        ),
    }


def analyze_enemy_sync(
    host_samples: list[dict[str, Any]],
    client_samples: list[dict[str, Any]],
    *,
    enforce_bounds: bool = True,
) -> dict[str, Any]:
    host_by_sequence = {
        sample["sequence"]: sample
        for sample in host_samples
        if len(sample["actors"]) >= MINIMUM_LIVE_ENEMIES
    }
    eligible_clients = [
        sample
        for sample in client_samples
        if len(sample["actors"]) >= MINIMUM_LIVE_ENEMIES
        and sample["sequence"] in host_by_sequence
    ]
    arrival_gaps = [
        float(right["received_ms"] - left["received_ms"])
        for left, right in zip(eligible_clients, eligible_clients[1:])
        if right["received_ms"] > left["received_ms"]
    ]
    host_client_errors: list[float] = []
    clone_errors: list[float] = []
    hp_errors: list[float] = []
    state_comparisons = 0
    state_mismatches = 0
    clone_state_comparisons = 0
    clone_state_mismatches = 0
    compared_actor_counts: list[int] = []
    for client_sample in eligible_clients:
        host_sample = host_by_sequence[client_sample["sequence"]]
        common_ids = set(host_sample["actors"]) & set(client_sample["actors"])
        compared_actor_counts.append(len(common_ids))
        for network_id in common_ids:
            host_actor = host_sample["actors"][network_id]
            client_actor = client_sample["actors"][network_id]
            host_client_errors.append(
                math.hypot(
                    client_actor["x"] - host_actor["x"],
                    client_actor["y"] - host_actor["y"],
                )
            )
            hp_errors.append(abs(client_actor["hp"] - host_actor["hp"]))
            state_comparisons += 3
            state_mismatches += int(
                client_actor["dead"] != host_actor["dead"]
            )
            state_mismatches += int(
                client_actor["anim"] != host_actor["anim"]
            )
            state_mismatches += int(
                client_actor["target"] != host_actor["target"]
            )
            if (
                client_actor["local_x"] is not None
                and client_actor["local_y"] is not None
            ):
                clone_errors.append(
                    math.hypot(
                        client_actor["local_x"] - client_actor["x"],
                        client_actor["local_y"] - client_actor["y"],
                    )
                )
            if client_actor["local_hp"] is not None:
                hp_errors.append(
                    abs(client_actor["local_hp"] - client_actor["hp"])
                )
            if (
                client_actor["local_dead"] is not None
                and client_actor["local_anim"] is not None
            ):
                clone_state_comparisons += 2
                clone_state_mismatches += int(
                    client_actor["local_dead"] != client_actor["dead"]
                )
                clone_state_mismatches += int(
                    client_actor["local_anim"] != client_actor["anim"]
                )

    displacement_by_actor: dict[int, float] = {}
    first_position: dict[int, tuple[float, float]] = {}
    for sample in host_samples:
        if len(sample["actors"]) < MINIMUM_LIVE_ENEMIES:
            continue
        for network_id, actor in sample["actors"].items():
            first_position.setdefault(network_id, (actor["x"], actor["y"]))
            first_x, first_y = first_position[network_id]
            displacement_by_actor[network_id] = max(
                displacement_by_actor.get(network_id, 0.0),
                math.hypot(actor["x"] - first_x, actor["y"] - first_y),
            )
    moving_enemies = sum(
        displacement >= 16.0
        for displacement in displacement_by_actor.values()
    )
    analysis = {
        "host_sample_count": len(host_samples),
        "client_sample_count": len(client_samples),
        "eligible_client_sample_count": len(eligible_clients),
        "minimum_compared_enemy_count": min(
            compared_actor_counts,
            default=0,
        ),
        "moving_enemy_count": moving_enemies,
        "maximum_enemy_displacement": max(
            displacement_by_actor.values(),
            default=0.0,
        ),
        "position_comparison_count": len(host_client_errors),
        "maximum_host_client_position_error": max(
            host_client_errors,
            default=math.inf,
        ),
        "p95_host_client_position_error": _percentile(
            host_client_errors,
            0.95,
        ),
        "client_clone_comparison_count": len(clone_errors),
        "maximum_client_clone_position_error": max(
            clone_errors,
            default=math.inf,
        ),
        "p95_client_clone_position_error": _percentile(
            clone_errors,
            0.95,
        ),
        "maximum_hp_error": max(hp_errors, default=math.inf),
        "state_comparison_count": state_comparisons,
        "state_mismatch_ratio": (
            state_mismatches / state_comparisons
            if state_comparisons
            else math.inf
        ),
        "clone_state_comparison_count": clone_state_comparisons,
        "clone_state_mismatch_ratio": (
            clone_state_mismatches / clone_state_comparisons
            if clone_state_comparisons
            else math.inf
        ),
        "maximum_client_arrival_gap_ms": max(
            arrival_gaps,
            default=math.inf,
        ),
        "p95_client_arrival_gap_ms": _percentile(
            arrival_gaps,
            0.95,
        ),
        "mean_client_arrival_gap_ms": (
            statistics.fmean(arrival_gaps)
            if arrival_gaps
            else math.inf
        ),
        "native_fidelity": analyze_native_fidelity(
            host_samples,
            client_samples,
        ),
    }
    native_fidelity = analysis["native_fidelity"]
    failures = []
    checks = (
        (
            analysis["minimum_compared_enemy_count"] >=
            MINIMUM_LIVE_ENEMIES,
            "too few simultaneous live enemies",
        ),
        (
            analysis["moving_enemy_count"] >= MINIMUM_MOVING_ENEMIES,
            "too few enemies moved during organic combat",
        ),
        (
            analysis["position_comparison_count"] >=
            MINIMUM_POSITION_COMPARISONS,
            "too few host/client enemy position comparisons",
        ),
        (
            analysis["maximum_client_arrival_gap_ms"] <=
            MAXIMUM_CLIENT_ARRIVAL_GAP_MS,
            "client motion stream stalled",
        ),
        (
            analysis["p95_client_arrival_gap_ms"] <=
            P95_CLIENT_ARRIVAL_GAP_MS,
            "client motion stream p95 interval exceeded its bound",
        ),
        (
            analysis["maximum_host_client_position_error"] <=
            MAXIMUM_HOST_CLIENT_POSITION_ERROR,
            "host/client authoritative enemy positions diverged",
        ),
        (
            analysis["p95_host_client_position_error"] <=
            P95_HOST_CLIENT_POSITION_ERROR,
            "host/client authoritative enemy p95 error exceeded its bound",
        ),
        (
            analysis["maximum_client_clone_position_error"] <=
            MAXIMUM_CLIENT_CLONE_POSITION_ERROR,
            "client native enemy clone diverged",
        ),
        (
            analysis["p95_client_clone_position_error"] <=
            P95_CLIENT_CLONE_POSITION_ERROR,
            "client native enemy clone p95 error exceeded its bound",
        ),
        (
            analysis["maximum_hp_error"] <= MAXIMUM_HP_ERROR,
            "enemy HP state diverged",
        ),
        (
            analysis["state_mismatch_ratio"] <=
            MAXIMUM_STATE_MISMATCH_RATIO,
            "host/client enemy state mismatch ratio exceeded its bound",
        ),
        (
            analysis["clone_state_mismatch_ratio"] <=
            MAXIMUM_STATE_MISMATCH_RATIO,
            "client native enemy state mismatch ratio exceeded its bound",
        ),
        (
            native_fidelity["common_native_enemy_count"] >=
            MINIMUM_LIVE_ENEMIES,
            "too few host/client native enemy tracks",
        ),
        (
            native_fidelity["native_position_comparison_count"] >=
            MINIMUM_POSITION_COMPARISONS,
            "too few time-aligned native enemy comparisons",
        ),
        (
            native_fidelity["maximum_native_position_error"] <=
            MAXIMUM_NATIVE_POSITION_ERROR,
            "client-observed enemy authority divergence exceeded its maximum",
        ),
        (
            native_fidelity["p95_native_position_error"] <=
            P95_NATIVE_POSITION_ERROR,
            "client-observed enemy authority divergence exceeded its p95 bound",
        ),
        (
            native_fidelity["native_lag_actor_count"] >=
            MINIMUM_MOVING_ENEMIES,
            "too few moving native enemy tracks for latency measurement",
        ),
        (
            native_fidelity["p95_native_lag_ms"] <= P95_NATIVE_LAG_MS,
            "client-observed enemy update latency exceeded its p95 bound",
        ),
        (
            native_fidelity["p95_presentation_source_age_ms"] <=
            P95_PRESENTATION_SOURCE_AGE_MS,
            "client enemy presentation source age exceeded its p95 bound",
        ),
        (
            native_fidelity["teleport_event_count"] == 0,
            "client enemies teleported relative to host authority",
        ),
        (
            native_fidelity["rubber_band_event_count"] == 0,
            "client enemies rubber-banded relative to host authority",
        ),
        (
            native_fidelity["freeze_episode_count"] == 0,
            "client enemies froze while host authority kept moving",
        ),
        (
            native_fidelity["ghost_episode_count"] == 0,
            "client enemy ghosts persisted after materialization warmup",
        ),
    )
    for passed, message in checks:
        if not passed:
            failures.append(message)
    analysis["failures"] = failures
    if failures and enforce_bounds:
        raise VerifyFailure(
            "; ".join(failures) + f": {analysis}"
        )
    return analysis


def _timestamp_ms(line: str) -> float:
    match = re.match(
        r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})\]",
        line,
    )
    if match is None:
        raise VerifyFailure(f"log line has no timestamp: {line!r}")
    return datetime.strptime(
        match.group(1),
        "%Y-%m-%d %H:%M:%S.%f",
    ).timestamp() * 1000.0


def analyze_air_cast_timing(
    source_log: str,
    observer_log: str,
    source_id: int,
) -> dict[str, Any]:
    source_pattern = re.compile(
        rf"participant_id={source_id} cast_sequence=(\d+).*"
        rf"phase=(pressed|released).*skill_id={AIR_SKILL_ID}\b"
    )
    source_edges: dict[int, dict[str, float]] = {}
    for line in source_log.splitlines():
        if "Multiplayer local cast sent." not in line:
            continue
        match = source_pattern.search(line)
        if match is not None:
            source_edges.setdefault(int(match.group(1)), {})[
                match.group(2)
            ] = _timestamp_ms(line)
    complete_sequences = [
        sequence
        for sequence, edges in source_edges.items()
        if "pressed" in edges and "released" in edges
    ]
    if not complete_sequences:
        raise VerifyFailure(
            "client Air cast did not produce pressed and released edges"
        )
    cast_sequence = min(complete_sequences)
    edges = source_edges[cast_sequence]

    observer_start = None
    observer_stop = None
    observer_complete = None
    for line in observer_log.splitlines():
        if (
            "Multiplayer remote cast queued." in line
            and f"participant_id={source_id}" in line
            and f"cast_sequence={cast_sequence}" in line
            and f"skill_id={AIR_SKILL_ID}" in line
        ):
            observer_start = _timestamp_ms(line)
        elif (
            "Multiplayer remote cast input release." in line
            and f"participant_id={source_id}" in line
            and f"cast_sequence={cast_sequence}" in line
            and f"skill_id={AIR_SKILL_ID}" in line
        ):
            observer_stop = _timestamp_ms(line)
        elif (
            "[bots] cast complete (remote_input_released)." in line
            and f"bot_id={source_id}" in line
            and f"remote_cast_sequence={cast_sequence}" in line
        ):
            observer_complete = _timestamp_ms(line)
    if (
        observer_start is None
        or observer_stop is None
        or observer_complete is None
    ):
        raise VerifyFailure(
            "host did not observe the complete Air cast lifecycle "
            f"for cast_sequence={cast_sequence}"
        )

    source_duration = edges["released"] - edges["pressed"]
    observer_duration = observer_stop - observer_start
    analysis = {
        "skill_id": AIR_SKILL_ID,
        "cast_sequence": cast_sequence,
        "source_duration_ms": source_duration,
        "host_observed_duration_ms": observer_duration,
        "duration_error_ms": abs(observer_duration - source_duration),
        "start_latency_ms": observer_start - edges["pressed"],
        "stop_latency_ms": observer_stop - edges["released"],
        "completion_after_source_release_ms": (
            observer_complete - edges["released"]
        ),
    }
    checks = (
        (
            0.0 <= analysis["start_latency_ms"] <=
            MAXIMUM_CAST_START_LATENCY_MS,
            "Air cast start latency exceeded its bound",
        ),
        (
            0.0 <= analysis["stop_latency_ms"] <=
            MAXIMUM_CAST_STOP_LATENCY_MS,
            "Air cast stop latency exceeded its bound",
        ),
        (
            analysis["duration_error_ms"] <=
            MAXIMUM_CAST_DURATION_ERROR_MS,
            "host-observed Air cast duration diverged from the client",
        ),
        (
            0.0 <= analysis["completion_after_source_release_ms"] <=
            MAXIMUM_CAST_COMPLETION_AFTER_RELEASE_MS,
            "host Air cast did not complete promptly after client release",
        ),
    )
    failures = [message for passed, message in checks if not passed]
    if failures:
        raise VerifyFailure(
            "; ".join(failures) + f": {analysis}"
        )
    return analysis


def _wait_for_cast_timing(
    source_log_path: Path,
    observer_log_path: Path,
    source_offset: int,
    observer_offset: int,
    source_id: int,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        try:
            return analyze_air_cast_timing(
                _read_log_after(source_log_path, source_offset),
                _read_log_after(observer_log_path, observer_offset),
                source_id,
            )
        except VerifyFailure as exc:
            last_error = str(exc)
            time.sleep(0.05)
    raise VerifyFailure(
        f"Air cast timing evidence did not settle: {last_error}"
    )


def _start_latency_proxy(
    *,
    instance_prefix: str,
    host_game_port: int,
    client_game_port: int,
    host_proxy_port: int,
    client_proxy_port: int,
    latency_ms: float,
    jitter_ms: float,
    seed: int,
) -> dict[str, Any]:
    windows_python = Path("/mnt/c/Python313/python.exe")
    if not windows_python.is_file():
        raise VerifyFailure(
            f"Windows Python was not found at {windows_python}"
        )
    proxy_root = ROOT / "runtime" / "latency-proxies" / instance_prefix
    proxy_root.mkdir(parents=True, exist_ok=True)
    stop_file = proxy_root / "stop"
    metrics_path = proxy_root / "metrics.json"
    stop_file.unlink(missing_ok=True)
    metrics_path.unlink(missing_ok=True)
    command = [
        str(windows_python),
        path_for_powershell(ROOT / "tools" / "udp_latency_proxy.py"),
        "--host-proxy",
        f"127.0.0.1:{host_proxy_port}",
        "--host-game",
        f"127.0.0.1:{host_game_port}",
        "--client-proxy",
        f"127.0.0.1:{client_proxy_port}",
        "--client-game",
        f"127.0.0.1:{client_game_port}",
        "--latency-ms",
        str(latency_ms),
        "--jitter-ms",
        str(jitter_ms),
        "--seed",
        str(seed),
        "--metrics",
        path_for_powershell(metrics_path),
        "--stop-file",
        path_for_powershell(stop_file),
    ]
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
    )
    assert process.stdout is not None
    output_lines: list[str] = []
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if process.poll() is not None:
            output_lines.extend(process.stdout.readlines())
            break
        readable, _, _ = select.select([process.stdout], [], [], 0.1)
        if not readable:
            continue
        line = process.stdout.readline()
        if not line:
            continue
        output_lines.append(line)
        if line.startswith("proxy_ready "):
            return {
                "process": process,
                "pid": process.pid,
                "executable": str(windows_python),
                "stop_file": stop_file,
                "metrics_path": metrics_path,
                "output_lines": output_lines,
                "host_proxy_port": host_proxy_port,
                "client_proxy_port": client_proxy_port,
            }
    if process.poll() is None:
        process.terminate()
        process.wait(timeout=5.0)
    raise VerifyFailure(
        "latency proxy did not become ready: "
        + "".join(output_lines).strip()
    )


def _stop_latency_proxy(proxy: dict[str, Any]) -> dict[str, Any]:
    process = proxy["process"]
    assert isinstance(process, subprocess.Popen)
    stop_file = proxy["stop_file"]
    assert isinstance(stop_file, Path)
    stop_file.touch()
    forced = False
    try:
        process.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        forced = True
        process.terminate()
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2.0)
    stdout = process.stdout
    output_lines = list(proxy["output_lines"])
    if stdout is not None:
        output_lines.extend(stdout.readlines())
        stdout.close()
    metrics_path = proxy["metrics_path"]
    metrics = None
    if isinstance(metrics_path, Path) and metrics_path.is_file():
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    return {
        "pid": proxy["pid"],
        "executable": proxy["executable"],
        "host_proxy_port": proxy["host_proxy_port"],
        "client_proxy_port": proxy["client_proxy_port"],
        "exit_code": process.returncode,
        "forced_stop": forced,
        "metrics_path": str(metrics_path),
        "metrics": metrics,
        "output": "".join(output_lines),
    }


def _build_evidence(
    launcher_path: Path | None,
    build_label: str,
) -> dict[str, Any]:
    effective_launcher = (
        launcher_path
        if launcher_path is not None
        else ROOT / "dist" / "launcher" / "SolomonDarkModLauncher.exe"
    ).resolve()
    loader_path = effective_launcher.parent / "SolomonDarkModLoader.dll"
    evidence: dict[str, Any] = {
        "label": build_label,
        "launcher_path": str(effective_launcher),
        "loader_path": str(loader_path),
        "loader_exists": loader_path.is_file(),
    }
    if loader_path.is_file():
        evidence["loader_size"] = loader_path.stat().st_size
        evidence["loader_sha256"] = hashlib.sha256(
            loader_path.read_bytes()
        ).hexdigest()
    return evidence


def run_live_verification(
    *,
    instance_prefix: str,
    ports: list[int],
    proxy_ports: list[int] | None,
    game_directory: Path | None,
    launcher_path: Path | None,
    sample_seconds: float,
    enforce_enemy_bounds: bool,
    include_cast: bool,
    build_label: str,
) -> dict[str, Any]:
    launch = launch_pair(
        host_preset="map_create_fire_mind_hub",
        client_preset="map_create_air_mind_hub",
        temporary_host_profile=True,
        tile_windows=False,
        kill_existing=False,
        instance_prefix=instance_prefix,
        host_port=ports[0],
        client_port=ports[1],
        host_remote_port=(
            proxy_ports[0]
            if proxy_ports is not None
            else None
        ),
        client_remote_port=(
            proxy_ports[1]
            if proxy_ports is not None
            else None
        ),
        game_directory=game_directory,
        launcher_path=launcher_path,
        exact_mod_id=ACCEPTANCE_MOD_ID,
    )
    process_ids = game_process_ids(launch)
    if len(process_ids) != 2:
        stop_game_processes(process_ids)
        raise VerifyFailure(
            f"isolated pair did not report two process IDs: {launch}"
        )

    host_pipe = str(launch["hostLuaPipe"])
    client_pipe = str(launch["clientLuaPipe"])
    host_log = _log_path(instance_prefix, "host")
    client_log = _log_path(instance_prefix, "client")
    result: dict[str, Any] = {
        "launch": launch,
        "process_ids": process_ids,
        "instance_prefix": instance_prefix,
        "ports": ports,
        "proxy_ports": proxy_ports,
        "build": _build_evidence(launcher_path, build_label),
    }
    try:
        _disable_companion_bots([host_pipe, client_pipe])
        _start_testrun_when_ready(host_pipe)
        wait_for_scene(host_pipe, "testrun", 45.0)
        wait_for_scene(client_pipe, "testrun", 45.0)
        result["relationships"] = {
            "host_observes_client": wait_for_remote(
                host_pipe,
                CLIENT_ID,
                CLIENT_NAME,
                "testrun",
                45.0,
            ),
            "client_observes_host": wait_for_remote(
                client_pipe,
                HOST_ID,
                HOST_NAME,
                "testrun",
                45.0,
            ),
        }
        result["vitals"] = {
            "host": set_local_player_vitals(
                host_pipe,
                TEST_PLAYER_HP,
                TEST_PLAYER_HP,
            ),
            "client": set_local_player_vitals(
                client_pipe,
                TEST_PLAYER_HP,
                TEST_PLAYER_HP,
            ),
        }
        result["wave_start"] = _start_waves(host_pipe)
        result["initial_live_enemies"] = {
            "host": _wait_for_live_enemies(host_pipe, 20.0),
            "client": _wait_for_live_enemies(client_pipe, 20.0),
        }
        initial_hp = {
            "host": _player_hp(host_pipe),
            "client": _player_hp(client_pipe),
        }
        arm_code = ARM_WORLD_PROBE_LUA.replace(
            "__SAMPLE_LIMIT__",
            str(max(400, math.ceil(sample_seconds * 80.0))),
        )
        for pipe_name in (host_pipe, client_pipe):
            armed = parse_key_values(lua(pipe_name, arm_code))
            if (
                armed.get("registered") != "true"
                or armed.get("active") != "true"
            ):
                raise VerifyFailure(
                    f"failed to arm organic enemy probe on {pipe_name}: "
                    f"{armed}"
                )

        sample_started = time.monotonic()
        if include_cast:
            source_offset = _log_offset(client_log)
            observer_offset = _log_offset(host_log)
            direction = Direction(
                name="client_to_host_air",
                source_id=CLIENT_ID,
                source_name=CLIENT_NAME,
                source_pipe=client_pipe,
                source_log=client_log,
                source_pid=int(launch["clientProcessId"]),
                receiver_pipe=host_pipe,
                receiver_log=host_log,
            )
            result["air_input"] = queue_gameplay_mouse_left(
                direction,
                AIR_HOLD_FRAMES,
            )
            result["air_cast_timing"] = _wait_for_cast_timing(
                client_log,
                host_log,
                source_offset,
                observer_offset,
                CLIENT_ID,
                8.0,
            )
        else:
            result["air_input"] = None
            result["air_cast_timing"] = None
        remaining = sample_seconds - (time.monotonic() - sample_started)
        if remaining > 0:
            time.sleep(remaining)

        host_samples = _read_world_probe(host_pipe)
        client_samples = _read_world_probe(client_pipe)
        result["enemy_sync"] = analyze_enemy_sync(
            host_samples,
            client_samples,
            enforce_bounds=enforce_enemy_bounds,
        )
        final_hp = {
            "host": _player_hp(host_pipe),
            "client": _player_hp(client_pipe),
        }
        damage = {
            role: initial_hp[role] - final_hp[role]
            for role in initial_hp
        }
        result["organic_combat_damage"] = {
            "initial_hp": initial_hp,
            "final_hp": final_hp,
            "damage": damage,
        }
        if max(damage.values()) <= 0.05:
            raise VerifyFailure(
                "organic enemies did not damage either live player: "
                f"{result['organic_combat_damage']}"
            )
        result["ok"] = True
        return result
    finally:
        stop_game_processes(process_ids)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--instance-prefix",
        default="",
        help="Unique launcher instance prefix (generated by default).",
    )
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument(
        "--game-dir",
        type=Path,
        default=None,
        help="Retail game directory override for isolated worktrees.",
    )
    parser.add_argument(
        "--launcher-path",
        type=Path,
        default=None,
        help=(
            "Launcher build to stage. Its adjacent loader DLL is hashed into "
            "the evidence artifact."
        ),
    )
    parser.add_argument(
        "--build-label",
        default="",
        help="Human-readable build label stored in the evidence artifact.",
    )
    parser.add_argument(
        "--measure-only",
        action="store_true",
        help="Capture fidelity metrics without enforcing acceptance bounds.",
    )
    parser.add_argument(
        "--skip-cast",
        action="store_true",
        help="Measure enemy replication without exercising the Air cast gate.",
    )
    parser.add_argument("--host-port", type=int, default=None)
    parser.add_argument("--client-port", type=int, default=None)
    parser.add_argument(
        "--latency-ms",
        type=float,
        default=DEFAULT_NETWORK_LATENCY_MS,
        help=(
            "Deterministic one-way UDP proxy latency "
            f"(default: {DEFAULT_NETWORK_LATENCY_MS:g})."
        ),
    )
    parser.add_argument(
        "--jitter-ms",
        type=float,
        default=DEFAULT_NETWORK_JITTER_MS,
        help=(
            "Uniform per-datagram jitter around --latency-ms "
            f"(default: {DEFAULT_NETWORK_JITTER_MS:g})."
        ),
    )
    parser.add_argument(
        "--proxy-seed",
        type=int,
        default=DEFAULT_NETWORK_PROXY_SEED,
    )
    parser.add_argument("--sample-seconds", type=float, default=10.0)
    args = parser.parse_args()

    instance_prefix = args.instance_prefix or _default_instance_prefix()
    result: dict[str, Any] = {"ok": False}
    return_code = 1
    proxy: dict[str, Any] | None = None
    try:
        if args.sample_seconds < 5.0:
            raise VerifyFailure("--sample-seconds must be at least 5")
        if args.latency_ms < 0.0 or args.jitter_ms < 0.0:
            raise VerifyFailure(
                "--latency-ms and --jitter-ms must not be negative"
            )
        if (args.host_port is None) != (args.client_port is None):
            raise VerifyFailure(
                "--host-port and --client-port must be supplied together"
            )
        if args.host_port is not None:
            ports = [args.host_port, args.client_port]
            proxy_ports = (
                select_available_windows_udp_ports(
                    2,
                    excluded_ports=ports,
                )
                if args.latency_ms > 0.0 or args.jitter_ms > 0.0
                else None
            )
        elif args.latency_ms > 0.0 or args.jitter_ms > 0.0:
            selected_ports = select_available_windows_udp_ports(4)
            ports = selected_ports[:2]
            proxy_ports = selected_ports[2:]
        else:
            ports = select_available_windows_udp_ports(2)
            proxy_ports = None
        if proxy_ports is not None:
            proxy = _start_latency_proxy(
                instance_prefix=instance_prefix,
                host_game_port=int(ports[0]),
                client_game_port=int(ports[1]),
                host_proxy_port=int(proxy_ports[0]),
                client_proxy_port=int(proxy_ports[1]),
                latency_ms=args.latency_ms,
                jitter_ms=args.jitter_ms,
                seed=args.proxy_seed,
            )
        result = run_live_verification(
            instance_prefix=instance_prefix,
            ports=[int(port) for port in ports],
            proxy_ports=(
                [int(port) for port in proxy_ports]
                if proxy_ports is not None
                else None
            ),
            game_directory=args.game_dir,
            launcher_path=args.launcher_path,
            sample_seconds=args.sample_seconds,
            enforce_enemy_bounds=not args.measure_only,
            include_cast=not args.skip_cast,
            build_label=args.build_label,
        )
        return_code = 0
    except Exception as exc:
        result["error"] = str(exc)
        result["error_type"] = type(exc).__name__
        result["traceback"] = traceback.format_exc()
        result["instance_prefix"] = instance_prefix
    finally:
        if proxy is not None:
            result["network_proxy"] = _stop_latency_proxy(proxy)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "ok": result.get("ok", False),
                    "error": result.get("error"),
                    "enemy_sync": result.get("enemy_sync"),
                    "air_cast_timing": result.get("air_cast_timing"),
                    "organic_combat_damage": result.get(
                        "organic_combat_damage"
                    ),
                    "instance_prefix": instance_prefix,
                    "output": str(args.output),
                },
                indent=2,
                sort_keys=True,
            )
        )
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
