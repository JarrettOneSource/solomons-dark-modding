#!/usr/bin/env python3
"""Verify that host-owned enemy simulation continues after the host dies."""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import statistics
import time
import traceback
from pathlib import Path
from typing import Any

from multiplayer_frame_capture import capture_game_backbuffer
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
    place_player,
    stop_exact_game_processes,
    wait_for_remote,
    wait_for_scene,
)
from verify_multiplayer_enemy_retarget import DISARM_ENEMY_ARENA_LUA
from verify_multiplayer_death_spectator_respawn import (
    _arm_death_traces,
    _disarm_death_traces,
)
from verify_multiplayer_organic_player_death import (
    ACCEPTANCE_MOD_ID,
    ATTACKER_STABILIZED_HP,
    VICTIM_MAX_HP,
    WAVE_FIXTURES,
    _arm_enemy_arena,
    _assert_lifecycle,
    _disable_companion_bots,
    _launch_log_path,
    _place_and_wait_for_death_target_layout,
    _query_live_enemies,
    _sample_lifecycle,
    _set_enemy_attack,
    _stabilize_enemy,
    _start_testrun_when_ready,
    _start_waves,
    _wait_for_victim_damage,
    _wait_for_new_wave_enemy,
)
from verify_player_health_death_sync import set_local_player_vitals


OUTPUT = ROOT / "runtime" / "multiplayer_host_death_continuity.json"
ARTIFACT_ROOT = ROOT / "runtime" / "multiplayer_host_death_continuity"
DEFAULT_OBSERVATION_SECONDS = 180.0
PRE_DEATH_BASELINE_SECONDS = 15.0
PROBE_INTERVAL_MS = 100
SURVIVOR_HP = 50000.0
VICTIM_ARMING_HP = 2.0


class HostDeathContinuityFailure(VerifyFailure):
    """Live verifier failure that retains all evidence captured so far."""

    def __init__(self, message: str, evidence: dict[str, Any]) -> None:
        super().__init__(message)
        self.evidence = evidence


ARM_PROBE_LUA = r"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
_G.__sdmod_host_death_continuity_probe = {
  active = true,
  next_ms = 0,
  interval_ms = __INTERVAL_MS__,
  limit = __SAMPLE_LIMIT__,
  samples = {},
  enemy_actor_address = 0,
  enemy_network_id = 0,
}
if not _G.__sdmod_host_death_continuity_probe_registered then
  sd.events.on("runtime.tick", function(event)
    local probe = _G.__sdmod_host_death_continuity_probe
    if type(probe) ~= "table" or not probe.active then return end
    local now_ms = tonumber(event and event.monotonic_milliseconds) or 0
    if now_ms < (tonumber(probe.next_ms) or 0) then return end
    probe.next_ms = now_ms + probe.interval_ms

    local player = sd.player and sd.player.get_state and
      sd.player.get_state() or nil
    local replicated = sd.world.get_replicated_actors and
      sd.world.get_replicated_actors() or nil
    local wanted_local_address =
      tonumber(probe.enemy_actor_address) or 0
    local wanted_network_id = tonumber(probe.enemy_network_id) or 0
    if wanted_network_id ~= 0 then
      for _, binding in ipairs(replicated and replicated.bindings or {}) do
        if tonumber(binding.network_actor_id) == wanted_network_id and
            (tonumber(binding.local_actor_address) or 0) ~= 0 then
          wanted_local_address = tonumber(binding.local_actor_address)
          probe.enemy_actor_address = wanted_local_address
          break
        end
      end
    end
    local local_enemy = nil
    for _, actor in ipairs(
        sd.world.list_actors and sd.world.list_actors() or {}) do
      if wanted_local_address ~= 0 and
          tonumber(actor.actor_address) == wanted_local_address then
        local_enemy = actor
        break
      end
    end
    local authority_enemy = nil
    for _, actor in ipairs(replicated and replicated.actors or {}) do
      if wanted_network_id ~= 0 and
          tonumber(actor.network_actor_id) == wanted_network_id then
        authority_enemy = actor
        break
      end
    end

    probe.samples[#probe.samples + 1] = {
      monotonic_ms = now_ms,
      received_ms = tonumber(replicated and replicated.received_ms) or 0,
      sequence = tonumber(replicated and replicated.sequence) or 0,
      player_hp = tonumber(player and player.hp) or 0,
      authority_id =
        tonumber(authority_enemy and authority_enemy.network_actor_id) or 0,
      authority_x = tonumber(authority_enemy and authority_enemy.x) or 0,
      authority_y = tonumber(authority_enemy and authority_enemy.y) or 0,
      authority_hp = tonumber(authority_enemy and authority_enemy.hp) or 0,
      authority_max_hp =
        tonumber(authority_enemy and authority_enemy.max_hp) or 0,
      target =
        tonumber(authority_enemy and authority_enemy.target_participant_id) or 0,
      local_address =
        tonumber(local_enemy and local_enemy.actor_address) or 0,
      local_type =
        tonumber(local_enemy and local_enemy.object_type_id) or 0,
      local_x = tonumber(local_enemy and local_enemy.x) or 0,
      local_y = tonumber(local_enemy and local_enemy.y) or 0,
      local_hp = tonumber(local_enemy and local_enemy.hp) or 0,
      local_max_hp = tonumber(local_enemy and local_enemy.max_hp) or 0,
    }
    if #probe.samples >= probe.limit then probe.active = false end
  end)
  _G.__sdmod_host_death_continuity_probe_registered = true
end
emit("registered", _G.__sdmod_host_death_continuity_probe_registered)
emit("active", _G.__sdmod_host_death_continuity_probe.active)
"""


STOP_PROBE_LUA = r"""
local probe = _G.__sdmod_host_death_continuity_probe
if type(probe) ~= "table" then error("continuity probe unavailable") end
probe.active = false
print("count=" .. tostring(#(probe.samples or {})))
"""


QUERY_PROBE_LUA = r"""
local probe = _G.__sdmod_host_death_continuity_probe
if type(probe) ~= "table" then error("continuity probe unavailable") end
local first = __FIRST_SAMPLE__
local count = __SAMPLE_COUNT__
local last = math.min(#(probe.samples or {}), first + count - 1)
for index = first, last do
  local sample = probe.samples[index]
  print(table.concat({
    "S",
    tostring(sample.monotonic_ms or 0),
    tostring(sample.received_ms or 0),
    tostring(sample.sequence or 0),
    string.format("%.6f", sample.player_hp or 0),
    tostring(sample.authority_id or 0),
    string.format("%.6f", sample.authority_x or 0),
    string.format("%.6f", sample.authority_y or 0),
    string.format("%.6f", sample.authority_hp or 0),
    string.format("%.6f", sample.authority_max_hp or 0),
    tostring(sample.target or 0),
    tostring(sample.local_address or 0),
    tostring(sample.local_type or 0),
    string.format("%.6f", sample.local_x or 0),
    string.format("%.6f", sample.local_y or 0),
    string.format("%.6f", sample.local_hp or 0),
    string.format("%.6f", sample.local_max_hp or 0),
  }, "|"))
end
"""


CONFIGURE_PROBE_ENEMY_LUA = r"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local probe = _G.__sdmod_host_death_continuity_probe
if type(probe) ~= "table" then error("continuity probe unavailable") end
local wanted_address = __ENEMY_ACTOR_ADDRESS__
local wanted_network_id = __ENEMY_NETWORK_ID__
if wanted_network_id == 0 and wanted_address ~= 0 then
  local selected = nil
  for _, actor in ipairs(
      sd.world.list_actors and sd.world.list_actors() or {}) do
    if tonumber(actor.actor_address) == wanted_address then
      selected = actor
      break
    end
  end
  local replicated = sd.world.get_replicated_actors and
    sd.world.get_replicated_actors() or nil
  local best_distance = math.huge
  for _, actor in ipairs(replicated and replicated.actors or {}) do
    if selected and actor.tracked_enemy and not actor.dead and
        tonumber(actor.object_type_id) ==
          tonumber(selected.object_type_id) then
      local dx = (tonumber(actor.x) or 0) - (tonumber(selected.x) or 0)
      local dy = (tonumber(actor.y) or 0) - (tonumber(selected.y) or 0)
      local distance = math.sqrt(dx * dx + dy * dy)
      if distance < best_distance then
        best_distance = distance
        wanted_network_id = tonumber(actor.network_actor_id) or 0
      end
    end
  end
  emit("distance", best_distance)
end
if wanted_network_id ~= 0 then
  local replicated = sd.world.get_replicated_actors and
    sd.world.get_replicated_actors() or nil
  for _, binding in ipairs(replicated and replicated.bindings or {}) do
    if tonumber(binding.network_actor_id) == wanted_network_id and
        (tonumber(binding.local_actor_address) or 0) ~= 0 then
      wanted_address = tonumber(binding.local_actor_address)
      break
    end
  end
end
probe.enemy_actor_address = wanted_address
probe.enemy_network_id = wanted_network_id
emit("actor_address", probe.enemy_actor_address)
emit("network_id", probe.enemy_network_id)
"""


KILL_OTHER_ENEMIES_LUA = r"""
local keep = __ENEMY_ACTOR_ADDRESS__
local attempted = 0
local accepted = 0
for _, actor in ipairs(sd.world.list_actors and sd.world.list_actors() or {}) do
  local address = tonumber(actor.actor_address) or 0
  if address ~= keep and actor.tracked_enemy and not actor.dead and
      (tonumber(actor.hp) or 0) > 0 then
    attempted = attempted + 1
    local max_hp = math.max(tonumber(actor.max_hp) or 1, 1)
    sd.gameplay.set_run_enemy_health(address, 0, max_hp)
    if sd.world.trigger_enemy_death(address) then
      accepted = accepted + 1
    end
  end
end
print("attempted=" .. tostring(attempted))
print("accepted=" .. tostring(accepted))
"""


ENEMY_CENSUS_LUA = r"""
local rows = {}
for _, actor in ipairs(sd.world.list_actors and sd.world.list_actors() or {}) do
  if actor.tracked_enemy and not actor.dead and
      (tonumber(actor.hp) or 0) > 0 then
    rows[#rows + 1] = actor
  end
end
table.sort(rows, function(left, right)
  return (tonumber(left.actor_address) or 0) <
    (tonumber(right.actor_address) or 0)
end)
print("count=" .. tostring(#rows))
for _, actor in ipairs(rows) do
  print(table.concat({
    "E",
    tostring(tonumber(actor.actor_address) or 0),
    tostring(tonumber(actor.object_type_id) or 0),
    string.format("%.6f", tonumber(actor.hp) or 0),
    string.format("%.6f", tonumber(actor.max_hp) or 0),
    string.format("%.6f", tonumber(actor.x) or 0),
    string.format("%.6f", tonumber(actor.y) or 0),
  }, "|"))
end
"""


def _parse_census(text: str) -> list[dict[str, int | float]]:
    rows: list[dict[str, int | float]] = []
    for line in text.splitlines():
        if not line.startswith("E|"):
            continue
        parts = line.split("|")
        if len(parts) != 7:
            raise VerifyFailure(f"malformed enemy census row: {line!r}")
        rows.append(
            {
                "actor_address": int(parts[1]),
                "object_type_id": int(parts[2]),
                "hp": float(parts[3]),
                "max_hp": float(parts[4]),
                "x": float(parts[5]),
                "y": float(parts[6]),
            }
        )
    return rows


def _arm_probe(pipe_name: str, observation_seconds: float) -> dict[str, str]:
    limit = math.ceil((observation_seconds + 45.0) * 1000.0 /
                      PROBE_INTERVAL_MS)
    code = (
        ARM_PROBE_LUA
        .replace("__INTERVAL_MS__", str(PROBE_INTERVAL_MS))
        .replace("__SAMPLE_LIMIT__", str(limit))
    )
    values = parse_key_values(lua(pipe_name, code, timeout=10.0))
    if values.get("registered") != "true" or values.get("active") != "true":
        raise VerifyFailure(f"continuity probe failed to arm: {values}")
    return values


def _isolate_enemy(
    host_pipe: str,
    enemy_actor_address: int,
    *,
    timeout: float = 12.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    attempts: list[dict[str, str]] = []
    stable_samples = 0
    live: list[dict[str, int | float]] = []
    code = KILL_OTHER_ENEMIES_LUA.replace(
        "__ENEMY_ACTOR_ADDRESS__",
        str(enemy_actor_address),
    )
    while time.monotonic() < deadline:
        attempts.append(parse_key_values(lua(host_pipe, code)))
        live = _query_live_enemies(host_pipe)
        if (
            len(live) == 1
            and int(live[0]["actor_address"]) == enemy_actor_address
        ):
            stable_samples += 1
            if stable_samples >= 5:
                return {
                    "attempts": attempts,
                    "stable_samples": stable_samples,
                    "live": live,
                }
        else:
            stable_samples = 0
        time.sleep(0.1)
    raise VerifyFailure(
        "could not isolate the selected stock enemy: "
        f"selected={enemy_actor_address} live={live} attempts={attempts}"
    )


def _configure_probe_enemy(
    *,
    host_pipe: str,
    client_pipe: str,
    enemy_actor_address: int,
    timeout: float = 8.0,
) -> dict[str, dict[str, str]]:
    deadline = time.monotonic() + timeout
    host: dict[str, str] = {}
    client: dict[str, str] = {}
    host_code = (
        CONFIGURE_PROBE_ENEMY_LUA
        .replace("__ENEMY_ACTOR_ADDRESS__", str(enemy_actor_address))
        .replace("__ENEMY_NETWORK_ID__", "0")
    )
    while time.monotonic() < deadline:
        host = parse_key_values(lua(host_pipe, host_code))
        network_id = int(host.get("network_id", "0"))
        distance = float(host.get("distance", "inf"))
        if network_id == 0 or distance > 32.0:
            time.sleep(0.1)
            continue
        client_code = (
            CONFIGURE_PROBE_ENEMY_LUA
            .replace("__ENEMY_ACTOR_ADDRESS__", "0")
            .replace("__ENEMY_NETWORK_ID__", str(network_id))
        )
        client = parse_key_values(lua(client_pipe, client_code))
        if int(client.get("actor_address", "0")) != 0:
            return {"host": host, "client": client}
        time.sleep(0.1)
    raise VerifyFailure(
        "selected stock enemy did not resolve to both continuity probes: "
        f"host={host} client={client}"
    )


def _parse_samples(text: str) -> list[dict[str, int | float]]:
    samples: list[dict[str, int | float]] = []
    for line in text.splitlines():
        if not line.startswith("S|"):
            continue
        parts = line.split("|")
        if len(parts) != 17:
            raise VerifyFailure(f"malformed continuity sample: {line!r}")
        samples.append(
            {
                "monotonic_ms": int(parts[1]),
                "received_ms": int(parts[2]),
                "sequence": int(parts[3]),
                "player_hp": float(parts[4]),
                "authority_id": int(parts[5]),
                "authority_x": float(parts[6]),
                "authority_y": float(parts[7]),
                "authority_hp": float(parts[8]),
                "authority_max_hp": float(parts[9]),
                "target": int(parts[10]),
                "local_address": int(parts[11]),
                "local_type": int(parts[12]),
                "local_x": float(parts[13]),
                "local_y": float(parts[14]),
                "local_hp": float(parts[15]),
                "local_max_hp": float(parts[16]),
            }
        )
    return samples


def _read_probe(pipe_name: str) -> list[dict[str, int | float]]:
    status = parse_key_values(lua(pipe_name, STOP_PROBE_LUA, timeout=10.0))
    count = int(status.get("count", "0"))
    samples: list[dict[str, int | float]] = []
    for first in range(1, count + 1, 64):
        code = (
            QUERY_PROBE_LUA
            .replace("__FIRST_SAMPLE__", str(first))
            .replace("__SAMPLE_COUNT__", "64")
        )
        samples.extend(_parse_samples(lua(pipe_name, code, timeout=15.0)))
    return samples


def _negative_hp_edges(
    samples: list[dict[str, int | float]],
    *,
    start_ms: int,
    end_ms: int | None = None,
) -> list[dict[str, float]]:
    edges: list[dict[str, float]] = []
    previous: dict[str, int | float] | None = None
    for sample in samples:
        if int(sample["monotonic_ms"]) < start_ms:
            continue
        if end_ms is not None and int(sample["monotonic_ms"]) > end_ms:
            continue
        if previous is not None:
            delta = float(previous["player_hp"]) - float(sample["player_hp"])
            if delta > 0.01:
                edges.append(
                    {
                        "monotonic_ms": float(sample["monotonic_ms"]),
                        "damage": delta,
                    }
                )
        previous = sample
    return edges


def _edge_cadence(edges: list[dict[str, float]]) -> dict[str, float | int]:
    intervals = [
        right["monotonic_ms"] - left["monotonic_ms"]
        for left, right in zip(edges, edges[1:])
    ]
    return {
        "edge_count": len(edges),
        "interval_count": len(intervals),
        "mean_interval_ms": (
            statistics.fmean(intervals) if intervals else math.inf
        ),
        "maximum_interval_ms": max(intervals, default=math.inf),
        "mean_damage": (
            statistics.fmean(edge["damage"] for edge in edges)
            if edges else 0.0
        ),
    }


def _movement_summary(
    samples: list[dict[str, int | float]],
    *,
    start_ms: int,
    end_ms: int | None = None,
    x_key: str,
    y_key: str,
) -> dict[str, float | int]:
    points = [
        (
            int(sample["monotonic_ms"]),
            float(sample[x_key]),
            float(sample[y_key]),
        )
        for sample in samples
        if int(sample["monotonic_ms"]) >= start_ms
        and (end_ms is None or int(sample["monotonic_ms"]) <= end_ms)
        and int(sample["local_address"]) != 0
    ]
    steps = [
        math.hypot(right[1] - left[1], right[2] - left[2])
        for left, right in zip(points, points[1:])
    ]
    moving_steps = [step for step in steps if step > 0.25]
    duration_ms = points[-1][0] - points[0][0] if len(points) > 1 else 0
    path_distance = sum(steps)
    return {
        "sample_count": len(points),
        "step_count": len(steps),
        "moving_step_count": len(moving_steps),
        "moving_step_ratio": (
            len(moving_steps) / len(steps) if steps else 0.0
        ),
        "duration_ms": duration_ms,
        "path_distance": path_distance,
        "path_per_second": (
            path_distance / (duration_ms / 1000.0)
            if duration_ms > 0 else 0.0
        ),
        "maximum_step": max(steps, default=0.0),
        "mean_moving_step": (
            statistics.fmean(moving_steps) if moving_steps else 0.0
        ),
    }


def _snapshot_cadence(
    samples: list[dict[str, int | float]],
    *,
    start_ms: int,
) -> dict[str, float | int]:
    arrivals: list[int] = []
    last = 0
    for sample in samples:
        if int(sample["monotonic_ms"]) < start_ms:
            continue
        received_ms = int(sample["received_ms"])
        if received_ms > 0 and received_ms != last:
            arrivals.append(received_ms)
            last = received_ms
    gaps = [
        float(right - left)
        for left, right in zip(arrivals, arrivals[1:])
        if right > left
    ]
    return {
        "arrival_count": len(arrivals),
        "gap_count": len(gaps),
        "maximum_gap_ms": max(gaps, default=math.inf),
        "mean_gap_ms": statistics.fmean(gaps) if gaps else math.inf,
    }


def _log_metrics(log_path: Path, death_timestamp: str) -> dict[str, Any]:
    text = log_path.read_text(encoding="utf-8", errors="replace")
    after = text
    if death_timestamp:
        marker = f"[{death_timestamp}]"
        position = text.find(marker)
        if position >= 0:
            after = text[position:]
    gaps = [
        int(value)
        for value in re.findall(
            r"Multiplayer app-thread gameplay tick gap\. gap_ms=(\d+)",
            after,
        )
    ]
    return {
        "tick_gap_count": len(gaps),
        "tick_gap_max_ms": max(gaps, default=0),
        "tick_gap_total_ms": sum(gaps),
        "catch_up_count": after.count("run.lifecycle enemy pool catch-up."),
        "manual_spawn_request_count": after.count(
            "manual run enemy spawn: queued stock-spawner request."
        ),
        "actor_world_hold_count": after.count(
            "ActorWorld_Tick held for shared simulation control."
        ),
        "snapshot_stall_count": after.count(
            "holding last authoritative actor state during transient snapshot stall"
        ),
    }


def _remote_death_timestamp(client_log: Path) -> str:
    text = client_log.read_text(encoding="utf-8", errors="replace")
    matches = re.findall(
        r"\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3})\] "
        r"\[bots\] native remote death epoch started\. "
        rf"participant_id={HOST_ID}\b",
        text,
    )
    return matches[-1] if matches else ""


def _local_death_timestamp(host_log: Path) -> str:
    text = host_log.read_text(encoding="utf-8", errors="replace")
    matches = re.findall(
        r"\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3})\] "
        rf"Multiplayer death presentation started\. participant_id={HOST_ID}\b",
        text,
    )
    return matches[-1] if matches else ""


def _preserve_logs(
    artifact_root: Path,
    host_log: Path,
    client_log: Path,
) -> dict[str, str]:
    preserved: dict[str, str] = {}
    for role, source in (("host", host_log), ("client", client_log)):
        if not source.is_file():
            continue
        destination = artifact_root / f"{role}-solomondarkmodloader.log"
        shutil.copy2(source, destination)
        preserved[role] = str(destination)
    return preserved


def _analyze(
    host_samples: list[dict[str, int | float]],
    client_samples: list[dict[str, int | float]],
) -> dict[str, Any]:
    death_samples = [
        sample
        for sample in host_samples
        if float(sample["player_hp"]) <= 0.0
    ]
    if not death_samples:
        raise VerifyFailure("host continuity probe never observed terminal HP")
    death_ms = int(death_samples[0]["monotonic_ms"])
    stable_post_ms = death_ms + 7000
    tracked_start_ms = max(
        (
            min(
                int(sample["monotonic_ms"])
                for sample in samples
                if int(sample["authority_id"]) != 0
            )
            for samples in (host_samples, client_samples)
            if any(int(sample["authority_id"]) != 0 for sample in samples)
        ),
        default=death_ms,
    )
    pre_death_end_ms = death_ms - 500
    final_ms = max(
        (
            int(sample["monotonic_ms"])
            for sample in host_samples + client_samples
        ),
        default=stable_post_ms,
    )
    terminal_start_ms = max(stable_post_ms, final_ms - 60_000)
    post_targets = [
        int(sample["target"])
        for sample in client_samples
        if int(sample["monotonic_ms"]) >= stable_post_ms
        and int(sample["authority_id"]) != 0
        and int(sample["target"]) != 0
    ]
    survivor_target_count = sum(target == CLIENT_ID for target in post_targets)
    wrong_target_count = sum(target != CLIENT_ID for target in post_targets)
    analysis = {
        "death_monotonic_ms": death_ms,
        "tracked_enemy_start_ms": tracked_start_ms,
        "pre_death_end_ms": pre_death_end_ms,
        "stable_post_death_start_ms": stable_post_ms,
        "terminal_window_start_ms": terminal_start_ms,
        "final_sample_ms": final_ms,
        "host_sample_count": len(host_samples),
        "client_sample_count": len(client_samples),
        "pre_death_host_authority_movement": _movement_summary(
            host_samples,
            start_ms=tracked_start_ms,
            end_ms=pre_death_end_ms,
            x_key="local_x",
            y_key="local_y",
        ),
        "pre_death_client_clone_movement": _movement_summary(
            client_samples,
            start_ms=tracked_start_ms,
            end_ms=pre_death_end_ms,
            x_key="local_x",
            y_key="local_y",
        ),
        "pre_death_client_snapshot_cadence": _snapshot_cadence(
            [
                sample
                for sample in client_samples
                if int(sample["monotonic_ms"]) <= pre_death_end_ms
            ],
            start_ms=tracked_start_ms,
        ),
        "host_authority_movement": _movement_summary(
            host_samples,
            start_ms=stable_post_ms,
            x_key="local_x",
            y_key="local_y",
        ),
        "client_clone_movement": _movement_summary(
            client_samples,
            start_ms=stable_post_ms,
            x_key="local_x",
            y_key="local_y",
        ),
        "host_terminal_authority_movement": _movement_summary(
            host_samples,
            start_ms=terminal_start_ms,
            x_key="local_x",
            y_key="local_y",
        ),
        "client_terminal_clone_movement": _movement_summary(
            client_samples,
            start_ms=terminal_start_ms,
            x_key="local_x",
            y_key="local_y",
        ),
        "client_snapshot_cadence": _snapshot_cadence(
            client_samples,
            start_ms=stable_post_ms,
        ),
        "pre_death_host_damage_edges": _negative_hp_edges(
            host_samples,
            start_ms=tracked_start_ms,
            end_ms=pre_death_end_ms,
        ),
        "post_death_damage_edges": _negative_hp_edges(
            client_samples,
            start_ms=stable_post_ms,
        ),
        "terminal_damage_edges": _negative_hp_edges(
            client_samples,
            start_ms=terminal_start_ms,
        ),
        "post_death_target_sample_count": len(post_targets),
        "survivor_target_count": survivor_target_count,
        "wrong_target_count": wrong_target_count,
        "retarget_success_ratio": (
            survivor_target_count / len(post_targets)
            if post_targets else 0.0
        ),
    }
    analysis["pre_death_attack_cadence"] = _edge_cadence(
        analysis["pre_death_host_damage_edges"]
    )
    analysis["post_death_attack_cadence"] = _edge_cadence(
        analysis["post_death_damage_edges"]
    )
    analysis["terminal_attack_cadence"] = _edge_cadence(
        analysis["terminal_damage_edges"]
    )
    return analysis


def run_live_verification(
    *,
    instance_prefix: str,
    ports: list[int],
    game_directory: Path,
    launcher_path: Path | None,
    artifact_root: Path,
    observation_seconds: float,
    measure_only: bool,
) -> dict[str, Any]:
    artifact_root.mkdir(parents=True, exist_ok=True)
    effective_wave = artifact_root / "effective-melee-wave.txt"
    shutil.copy2(WAVE_FIXTURES["melee"], effective_wave)
    wave_schedule = {
        "fixture_path": str(WAVE_FIXTURES["melee"].resolve()),
        "effective_path": str(effective_wave.resolve()),
        "record_count": 1,
        "enemy_token": "SKELETON",
    }
    launch = launch_pair(
        host_preset="map_create_fire_mind_hub",
        client_preset="map_create_air_mind_hub",
        temporary_host_profile=True,
        tile_windows=False,
        test_blank_boneyard=True,
        test_wave_override=effective_wave,
        use_sandbox_preset_flow=True,
        kill_existing=False,
        instance_prefix=instance_prefix,
        host_port=ports[0],
        client_port=ports[1],
        game_directory=game_directory,
        launcher_path=launcher_path,
        exact_mod_id=ACCEPTANCE_MOD_ID,
        enable_audio=False,
    )
    result: dict[str, Any] = {
        "ok": False,
        "measure_only": measure_only,
        "instance_prefix": instance_prefix,
        "ports": ports,
        "observation_seconds": observation_seconds,
        "wave_schedule": wave_schedule,
        "launch": launch,
        "process_ids": game_process_ids(launch),
    }
    if launch.get("audioDisabled") is not True:
        result["cleanup"] = stop_exact_game_processes(launch)
        raise VerifyFailure(f"pair audio was not disabled: {launch}")
    if len(result["process_ids"]) != 2:
        result["cleanup"] = stop_exact_game_processes(launch)
        raise VerifyFailure(f"pair launch omitted exact process IDs: {launch}")
    host_pipe = str(launch["hostLuaPipe"])
    client_pipe = str(launch["clientLuaPipe"])
    host_log = _launch_log_path(launch, "hostLog")
    client_log = _launch_log_path(launch, "clientLog")
    pipes = [host_pipe, client_pipe]
    death_traces_armed = False
    try:
        _disable_companion_bots([host_pipe, client_pipe])
        _start_testrun_when_ready(host_pipe)
        wait_for_scene(host_pipe, "testrun", 45.0)
        wait_for_scene(client_pipe, "testrun", 45.0)
        result["relationships"] = {
            "host_observes_client": wait_for_remote(
                host_pipe, CLIENT_ID, CLIENT_NAME, "testrun", 45.0
            ),
            "client_observes_host": wait_for_remote(
                client_pipe, HOST_ID, HOST_NAME, "testrun", 45.0
            ),
        }
        set_local_player_vitals(host_pipe, SURVIVOR_HP, SURVIVOR_HP)
        set_local_player_vitals(client_pipe, SURVIVOR_HP, SURVIVOR_HP)
        target_layout = _place_and_wait_for_death_target_layout(
            host_pipe=host_pipe,
            client_pipe=client_pipe,
            victim_role="host",
        )
        result["target_layout"] = target_layout
        result["probe_arm"] = {
            "host": _arm_probe(host_pipe, observation_seconds),
            "client": _arm_probe(client_pipe, observation_seconds),
        }
        result["death_traces_armed"] = _arm_death_traces(pipes)
        death_traces_armed = True
        pre_wave_enemies = _query_live_enemies(host_pipe)
        pre_wave_addresses = {
            int(actor["actor_address"]) for actor in pre_wave_enemies
        }
        result["wave_start"] = _start_waves(host_pipe)
        if pre_wave_enemies:
            enemy = pre_wave_enemies[0]
            result["stock_enemy_selection"] = "existing_native_wave"
        else:
            enemy = _wait_for_new_wave_enemy(
                host_pipe,
                pre_wave_actor_addresses=pre_wave_addresses,
            )
            result["stock_enemy_selection"] = "new_native_wave"
        result["stock_enemy_before_stabilization"] = enemy
        result["stock_census_before_stabilization"] = _parse_census(
            lua(host_pipe, ENEMY_CENSUS_LUA)
        )
        result["enemy_stabilized"] = _stabilize_enemy(
            host_pipe,
            enemy_actor_address=int(enemy["actor_address"]),
        )
        result["enemy_isolation"] = _isolate_enemy(
            host_pipe,
            int(enemy["actor_address"]),
        )
        result["isolated_census"] = _parse_census(
            lua(host_pipe, ENEMY_CENSUS_LUA)
        )
        authority = target_layout["host_authority"]
        host_xy = (
            float(authority["host_x"]),
            float(authority["host_y"]),
        )
        client_xy = (
            float(authority["client_x"]),
            float(authority["client_y"]),
        )
        attack_distance = -64.0 if client_xy[0] >= host_xy[0] else 64.0
        result["enemy_arena"] = _arm_enemy_arena(
            host_pipe, host_xy[0], host_xy[1]
        )
        result["enemy_attack"] = _set_enemy_attack(
            host_pipe,
            target_x=host_xy[0],
            target_y=host_xy[1],
            target_participant_id=0,
            enemy_actor_address=int(enemy["actor_address"]),
            attack_distance=attack_distance,
        )
        result["probe_enemy"] = _configure_probe_enemy(
            host_pipe=host_pipe,
            client_pipe=client_pipe,
            enemy_actor_address=int(enemy["actor_address"]),
        )
        result["enemy_damage_observed"] = _wait_for_victim_damage(
            host_pipe,
            baseline_hp=SURVIVOR_HP,
            timeout=18.0,
        )
        time.sleep(PRE_DEATH_BASELINE_SECONDS)
        result["host_armed"] = set_local_player_vitals(
            host_pipe,
            VICTIM_ARMING_HP,
            VICTIM_MAX_HP,
        )
        result["enemy_death_attack"] = _set_enemy_attack(
            host_pipe,
            target_x=host_xy[0],
            target_y=host_xy[1],
            target_participant_id=0,
            enemy_actor_address=int(enemy["actor_address"]),
            attack_distance=attack_distance,
        )
        lifecycle, milestones = _sample_lifecycle(
            victim_pipe=host_pipe,
            observer_pipe=client_pipe,
            victim_id=HOST_ID,
            timeout=18.0,
        )
        result["lifecycle_samples"] = lifecycle
        result["milestones"] = milestones
        result["grace_seconds"] = _assert_lifecycle(lifecycle, milestones)
        result["arena_disarmed"] = parse_key_values(
            lua(host_pipe, DISARM_ENEMY_ARENA_LUA)
        )
        result["early_screenshots"] = {
            "host": capture_game_backbuffer(
                host_pipe, artifact_root / "host-post-death-early.png"
            ),
            "client": capture_game_backbuffer(
                client_pipe, artifact_root / "client-post-death-early.png"
            ),
        }

        positions = (
            (2350.0, 1750.0, 180.0),
            (2200.0, 1750.0, 0.0),
            (2350.0, 1900.0, 180.0),
            (2200.0, 1900.0, 0.0),
        )
        movements: list[dict[str, Any]] = []
        started = time.monotonic()
        next_move = started
        index = 0
        while time.monotonic() - started < observation_seconds:
            now = time.monotonic()
            if now >= next_move:
                x, y, heading = positions[index % len(positions)]
                movements.append(
                    {
                        "elapsed_seconds": now - started,
                        "placement": place_player(
                            client_pipe, x, y, heading
                        ),
                    }
                )
                index += 1
                next_move += 15.0
            time.sleep(min(0.25, max(0.01, next_move - time.monotonic())))
        result["survivor_movements"] = movements
        result["terminal_screenshots"] = {
            "client": capture_game_backbuffer(
                client_pipe, artifact_root / "client-post-death-terminal.png"
            ),
            "host": capture_game_backbuffer(
                host_pipe, artifact_root / "host-post-death-terminal.png"
            ),
        }
        host_samples = _read_probe(host_pipe)
        client_samples = _read_probe(client_pipe)
        result["probe_samples"] = {
            "host": host_samples,
            "client": client_samples,
        }
        result["analysis"] = _analyze(host_samples, client_samples)
        remote_death_timestamp = _remote_death_timestamp(client_log)
        local_death_timestamp = _local_death_timestamp(host_log)
        result["death_timestamps"] = {
            "host_local": local_death_timestamp,
            "client_remote": remote_death_timestamp,
        }
        result["log_metrics"] = {
            "host": _log_metrics(host_log, local_death_timestamp),
            "client": _log_metrics(client_log, remote_death_timestamp),
        }
        analysis = result["analysis"]
        failures: list[str] = []
        if analysis["retarget_success_ratio"] != 1.0:
            failures.append("enemy did not target only the surviving client")
        if analysis["host_authority_movement"]["path_distance"] <= 16.0:
            failures.append("host-owned enemy simulation stopped moving")
        if analysis["client_clone_movement"]["path_distance"] <= 16.0:
            failures.append("client enemy clone stopped moving")
        if (
            analysis["host_terminal_authority_movement"]["path_distance"]
            <= 16.0
        ):
            failures.append(
                "host-owned enemy simulation stopped in the terminal minute"
            )
        if (
            analysis["client_terminal_clone_movement"]["path_distance"]
            <= 16.0
        ):
            failures.append(
                "client enemy clone stopped in the terminal minute"
            )
        if not analysis["post_death_damage_edges"]:
            failures.append("enemy produced no post-host-death attacks")
        if not analysis["terminal_damage_edges"]:
            failures.append(
                "enemy produced no attacks in the terminal minute"
            )
        if analysis["client_snapshot_cadence"]["maximum_gap_ms"] > 300.0:
            failures.append("client authoritative snapshot cadence stalled")
        if result["log_metrics"]["client"]["catch_up_count"] != 0:
            failures.append("client enemy pool catch-up did not converge")
        result["failures"] = failures
        result["ok"] = measure_only or not failures
        return result
    except Exception as exc:
        result["error"] = str(exc)
        result["error_type"] = type(exc).__name__
        result["traceback"] = traceback.format_exc()
        raise HostDeathContinuityFailure(str(exc), result) from exc
    finally:
        if death_traces_armed:
            try:
                result["death_traces_disarmed"] = _disarm_death_traces(
                    pipes
                )
            except Exception as exc:  # noqa: BLE001 - cleanup evidence.
                result["death_trace_cleanup_error"] = str(exc)
        try:
            result["preserved_logs"] = _preserve_logs(
                artifact_root,
                host_log,
                client_log,
            )
        except Exception as exc:  # noqa: BLE001 - evidence preservation.
            result["log_preservation_error"] = str(exc)
        result["cleanup"] = stop_exact_game_processes(launch)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance-prefix", required=True)
    parser.add_argument("--host-port", type=int, required=True)
    parser.add_argument("--client-port", type=int, required=True)
    parser.add_argument("--game-dir", type=Path, required=True)
    parser.add_argument("--launcher-path", type=Path)
    parser.add_argument("--artifact-root", type=Path, default=ARTIFACT_ROOT)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument(
        "--observation-seconds",
        type=float,
        default=DEFAULT_OBSERVATION_SECONDS,
    )
    parser.add_argument("--measure-only", action="store_true")
    args = parser.parse_args()
    result: dict[str, Any] = {
        "ok": False,
        "instance_prefix": args.instance_prefix,
    }
    exit_code = 1
    try:
        result = run_live_verification(
            instance_prefix=args.instance_prefix,
            ports=[args.host_port, args.client_port],
            game_directory=args.game_dir,
            launcher_path=args.launcher_path,
            artifact_root=args.artifact_root,
            observation_seconds=args.observation_seconds,
            measure_only=args.measure_only,
        )
        exit_code = 0 if result["ok"] else 1
    except Exception as exc:  # noqa: BLE001 - retain exact live evidence.
        evidence = getattr(exc, "evidence", None)
        if isinstance(evidence, dict):
            result = evidence
        result.setdefault("error", str(exc))
        result.setdefault("error_type", type(exc).__name__)
        result.setdefault("traceback", traceback.format_exc())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "ok": result.get("ok", False),
                "failures": result.get("failures"),
                "error": result.get("error"),
                "output": str(args.output),
                "artifact_root": str(args.artifact_root),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
