#!/usr/bin/env python3
"""Verify organic multi-enemy convergence and client Air cast edge timing."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import statistics
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
  last_received_ms = -1,
}
if not _G.__sdmod_organic_enemy_sync_probe_registered then
  sd.events.on("runtime.tick", function(event)
    local probe = _G.__sdmod_organic_enemy_sync_probe
    if type(probe) ~= "table" or not probe.active then return end
    local replicated = sd.world.get_replicated_actors and
      sd.world.get_replicated_actors() or nil
    local received_ms = tonumber(replicated and replicated.received_ms) or 0
    if replicated == nil or received_ms <= 0 or
        received_ms == probe.last_received_ms then
      return
    end
    probe.last_received_ms = received_ms

    local local_by_address = {}
    for _, actor in ipairs(sd.world.list_actors and sd.world.list_actors() or {}) do
      local address = tonumber(actor.actor_address) or 0
      if address ~= 0 then local_by_address[address] = actor end
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
    for _, actor in ipairs(replicated.actors or {}) do
      local network_id = tonumber(actor.network_actor_id) or 0
      if network_id ~= 0 and actor.tracked_enemy then
        local local_actor = local_by_id[network_id]
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
    probe.samples[#probe.samples + 1] = {
      monotonic_ms = tonumber(event and event.monotonic_milliseconds) or 0,
      received_ms = received_ms,
      sequence = tonumber(replicated.sequence) or 0,
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
for _, sample in ipairs(probe.samples or {}) do
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
    table.concat(actors, ";"),
  }, "|"))
end
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


def _wait_for_live_enemies(host_pipe: str, timeout: float) -> int:
    deadline = time.monotonic() + timeout
    last = 0
    while time.monotonic() < deadline:
        values = parse_key_values(lua(host_pipe, LIVE_ENEMY_COUNT_LUA))
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
        parts = raw_line.split("|", 4)
        if len(parts) != 5:
            raise VerifyFailure(f"malformed world probe sample: {raw_line!r}")
        actors: dict[int, dict[str, Any]] = {}
        for encoded_actor in filter(None, parts[4].split(";")):
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
                "actors": actors,
            }
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


def analyze_enemy_sync(
    host_samples: list[dict[str, Any]],
    client_samples: list[dict[str, Any]],
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
    }
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
    )
    for passed, message in checks:
        if not passed:
            failures.append(message)
    if failures:
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


def run_live_verification(
    *,
    instance_prefix: str,
    ports: list[int],
    game_directory: Path | None,
    sample_seconds: float,
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
        game_directory=game_directory,
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
        result["initial_live_enemies"] = _wait_for_live_enemies(
            host_pipe,
            20.0,
        )
        initial_hp = {
            "host": _player_hp(host_pipe),
            "client": _player_hp(client_pipe),
        }
        arm_code = ARM_WORLD_PROBE_LUA.replace(
            "__SAMPLE_LIMIT__",
            "400",
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
        sample_started = time.monotonic()
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
        remaining = sample_seconds - (time.monotonic() - sample_started)
        if remaining > 0:
            time.sleep(remaining)

        host_samples = parse_world_probe(
            lua(host_pipe, QUERY_WORLD_PROBE_LUA, timeout=15.0)
        )
        client_samples = parse_world_probe(
            lua(client_pipe, QUERY_WORLD_PROBE_LUA, timeout=15.0)
        )
        result["enemy_sync"] = analyze_enemy_sync(
            host_samples,
            client_samples,
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
    parser.add_argument("--host-port", type=int, default=None)
    parser.add_argument("--client-port", type=int, default=None)
    parser.add_argument("--sample-seconds", type=float, default=10.0)
    args = parser.parse_args()

    instance_prefix = args.instance_prefix or _default_instance_prefix()
    result: dict[str, Any] = {"ok": False}
    return_code = 1
    try:
        if args.sample_seconds < 5.0:
            raise VerifyFailure("--sample-seconds must be at least 5")
        if (args.host_port is None) != (args.client_port is None):
            raise VerifyFailure(
                "--host-port and --client-port must be supplied together"
            )
        ports = (
            [args.host_port, args.client_port]
            if args.host_port is not None
            else select_available_windows_udp_ports(2)
        )
        result = run_live_verification(
            instance_prefix=instance_prefix,
            ports=[int(port) for port in ports],
            game_directory=args.game_dir,
            sample_seconds=args.sample_seconds,
        )
        return_code = 0
    except Exception as exc:
        result["error"] = str(exc)
        result["error_type"] = type(exc).__name__
        result["traceback"] = traceback.format_exc()
        result["instance_prefix"] = instance_prefix
    finally:
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
