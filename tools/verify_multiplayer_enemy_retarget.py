#!/usr/bin/env python3
"""Verify nearest-valid enemy retargeting after death and onto summons."""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import time
import traceback
import uuid
from pathlib import Path
from typing import Any

import verify_multiplayer_focus_behavior_sync as focus
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
    path_for_powershell,
    place_player,
    select_available_windows_udp_ports,
    stop_exact_game_processes,
    wait_for_remote,
    wait_for_scene,
)
from verify_multiplayer_organic_player_death import (
    ACCEPTANCE_MOD_ID,
    ATTACKER_STABILIZED_HP,
    SURVIVOR_HP,
    VICTIM_ARMING_HP,
    VICTIM_MAX_HP,
    WAVE_FIXTURES,
    _arm_enemy_arena,
    _disable_companion_bots,
    _materialize_native_wave_schedule,
    _query_live_enemies,
    _set_enemy_attack,
    _stabilize_enemy,
    _start_testrun_when_ready,
    _start_waves,
    _wait_for_new_wave_enemy,
    _wait_for_victim_damage,
)
from verify_multiplayer_death_spectator_respawn import (
    query_spectator_state,
)
from verify_player_health_death_sync import set_local_player_vitals


OUTPUT = ROOT / "runtime" / "multiplayer_enemy_retarget.json"
ARTIFACT_ROOT = ROOT / "runtime" / "multiplayer_enemy_retarget"
ETHER_MINION_NATIVE_TYPE_ID = 0x07F2
CALL_LEVIATHAN_SKILL_ROW = 11
TARGET_SAMPLE_INTERVAL_SECONDS = 0.05
TARGET_SAMPLE_WINDOW_SECONDS = 2.5
MAX_HOST_REACQUIRE_LATENCY_MS = 1_500.0
MAX_CLIENT_REACQUIRE_LATENCY_MS = 2_000.0
MINIMUM_STABLE_MATCH_SAMPLES = 5


class EnemyRetargetFailure(VerifyFailure):
    """Live verifier failure that preserves the evidence gathered so far."""

    def __init__(self, message: str, evidence: dict[str, Any]) -> None:
        super().__init__(message)
        self.evidence = evidence


CAPTURE_TARGETS_LUA = r"""
local local_participant_id = __LOCAL_PARTICIPANT_ID__
local function read_u32(address)
  if address == nil or address == 0 then return 0 end
  return tonumber(sd.debug.read_u32(address)) or 0
end
local function read_i32(address)
  local value = read_u32(address)
  if value >= 0x80000000 then return value - 0x100000000 end
  return value
end
local function read_i16(address)
  local value = tonumber(sd.debug.read_u16(address)) or 0
  if value >= 0x8000 then return value - 0x10000 end
  return value
end
local function read_i8(address)
  local value = tonumber(sd.debug.read_u8(address)) or 0
  if value >= 0x80 then return value - 0x100 end
  return value
end
local target_offset = sd.debug.layout_offset("actor_current_target_actor")
local bucket_offset =
  sd.debug.layout_offset("actor_current_target_bucket_delta")
local type_offset = sd.debug.layout_offset("game_object_type_id")
local actor_slot_offset = sd.debug.layout_offset("actor_slot")
local world_slot_offset = sd.debug.layout_offset("actor_world_slot")
local ineligible_offset =
  sd.debug.layout_offset("actor_hostile_target_ineligible_state")

local participant_by_actor = {}
local participant_by_group = {}
local player = sd.player and sd.player.get_state and
  sd.player.get_state() or nil
if player and tonumber(player.actor_address) and
    local_participant_id ~= 0 then
  local address = tonumber(player.actor_address)
  participant_by_actor[address] = local_participant_id
  local group = actor_slot_offset and
    read_i8(address + actor_slot_offset) or -1
  if group >= 0 then
    participant_by_group[group] = local_participant_id
  end
end
for _, peer in ipairs(
    sd.bots and sd.bots.get_participants and
      sd.bots.get_participants() or {}) do
  local address = tonumber(peer.actor_address) or 0
  local participant_id = tonumber(peer.id) or 0
  if address ~= 0 and participant_id ~= 0 then
    participant_by_actor[address] = participant_id
    local group = actor_slot_offset and
      read_i8(address + actor_slot_offset) or -1
    if group >= 0 then
      participant_by_group[group] = participant_id
    end
  end
end

local replicated = sd.world and sd.world.get_replicated_actors and
  sd.world.get_replicated_actors() or nil
local network_by_local = {}
local network_by_key = {}
local authority_target_by_network = {}
local function key(type_id, actor_slot, world_slot)
  return table.concat({
    tostring(type_id or 0),
    tostring(actor_slot or -1),
    tostring(world_slot or -1),
  }, ":")
end
if replicated and replicated.bindings then
  for _, binding in ipairs(replicated.bindings) do
    local address = tonumber(binding.local_actor_address) or 0
    local network_id = tonumber(binding.network_actor_id) or 0
    if address ~= 0 and network_id ~= 0 and
        binding.matched and not binding.parked then
      network_by_local[address] = network_id
    end
  end
end
if replicated and replicated.actors then
  for _, actor in ipairs(replicated.actors) do
    local network_id = tonumber(actor.network_actor_id) or 0
    if network_id ~= 0 then
      network_by_key[key(
        tonumber(actor.object_type_id) or 0,
        tonumber(actor.actor_slot) or -1,
        tonumber(actor.world_slot) or -1)] = network_id
      authority_target_by_network[network_id] = {
        participant_id =
          tonumber(actor.target_participant_id) or 0,
        native_type_id =
          tonumber(actor.target_native_type_id) or 0,
        authoritative = actor.target_authoritative and 1 or 0,
      }
    end
  end
end

for _, actor in ipairs(
    sd.world and sd.world.list_actors and
      sd.world.list_actors() or {}) do
  local address = tonumber(actor.actor_address) or 0
  local type_id = tonumber(actor.object_type_id) or 0
  local actor_slot =
    actor_slot_offset and read_i8(address + actor_slot_offset) or -1
  local world_slot =
    world_slot_offset and read_i16(address + world_slot_offset) or -1
  local network_id = network_by_local[address] or
    network_by_key[key(type_id, actor_slot, world_slot)] or 0
  if address ~= 0 and network_id ~= 0 and actor.tracked_enemy and
      not actor.dead and (tonumber(actor.hp) or 0) > 0 then
    local target_actor =
      target_offset and read_u32(address + target_offset) or 0
    local target_type_id =
      target_actor ~= 0 and type_offset and
        read_u32(target_actor + type_offset) or 0
    local target_actor_slot =
      target_actor ~= 0 and actor_slot_offset and
        read_i8(target_actor + actor_slot_offset) or -1
    local target_world_slot =
      target_actor ~= 0 and world_slot_offset and
        read_i16(target_actor + world_slot_offset) or -1
    local target_ineligible =
      target_actor ~= 0 and ineligible_offset and
        (tonumber(sd.debug.read_u8(
          target_actor + ineligible_offset)) or 0) or 0
    local target_participant_id =
      participant_by_actor[target_actor] or 0
    if target_participant_id == 0 and
        (target_type_id == 0x03ED or
         target_type_id == 0x07F2 or
         target_type_id == 0x07F4) then
      target_participant_id =
        participant_by_group[target_actor_slot] or 0
    end
    local authority_target =
      authority_target_by_network[network_id] or {}
    print(table.concat({
      "E",
      tostring(network_id),
      tostring(address),
      tostring(type_id),
      tostring(target_actor),
      tostring(target_participant_id),
      tostring(target_type_id),
      tostring(actor_slot),
      tostring(world_slot),
      tostring(target_actor_slot),
      tostring(target_world_slot),
      tostring(bucket_offset and
        read_i32(address + bucket_offset) or 0),
      tostring(target_ineligible),
      tostring(authority_target.participant_id or 0),
      tostring(authority_target.native_type_id or 0),
      tostring(authority_target.authoritative or 0),
    }, "|"))
  end
end
"""


QUERY_NATIVE_ACTORS_LUA = r"""
local wanted = __NATIVE_TYPE_ID__
local actor_slot_offset = sd.debug.layout_offset("actor_slot")
local world_slot_offset = sd.debug.layout_offset("actor_world_slot")
local function read_i16(address)
  local value = tonumber(sd.debug.read_u16(address)) or 0
  if value >= 0x8000 then return value - 0x10000 end
  return value
end
local function read_i8(address)
  local value = tonumber(sd.debug.read_u8(address)) or 0
  if value >= 0x80 then return value - 0x100 end
  return value
end
for _, actor in ipairs(
    sd.world and sd.world.list_actors and
      sd.world.list_actors() or {}) do
  local type_id = tonumber(actor.object_type_id) or 0
  local address = tonumber(actor.actor_address) or 0
  if address ~= 0 and type_id == wanted and not actor.dead then
    print(table.concat({
      "A",
      tostring(address),
      tostring(type_id),
      tostring(read_i8(address + actor_slot_offset)),
      tostring(read_i16(address + world_slot_offset)),
      string.format("%.6f", tonumber(actor.x) or 0),
      string.format("%.6f", tonumber(actor.y) or 0),
    }, "|"))
  end
end
"""


ARRANGE_MINION_NEAREST_LUA = r"""
local enemy = __ENEMY_ACTOR_ADDRESS__
local minion = __MINION_ACTOR_ADDRESS__
local enemy_x = 1850.0
local enemy_y = 1750.0
local minion_x = 1890.0
local minion_y = 1750.0
local ox = sd.debug.layout_offset("actor_position_x")
local oy = sd.debug.layout_offset("actor_position_y")
local target_offset =
  sd.debug.layout_offset("actor_current_target_actor")
local bucket_offset =
  sd.debug.layout_offset("actor_current_target_bucket_delta")
local ok = enemy ~= 0 and minion ~= 0
if ok then
  ok = sd.debug.write_float(enemy + ox, enemy_x) and ok
  ok = sd.debug.write_float(enemy + oy, enemy_y) and ok
  ok = sd.debug.write_float(minion + ox, minion_x) and ok
  ok = sd.debug.write_float(minion + oy, minion_y) and ok
  ok = sd.debug.write_ptr(enemy + target_offset, 0) and ok
  ok = sd.debug.write_i32(enemy + bucket_offset, 0) and ok
  if sd.world and sd.world.rebind_actor then
    ok = sd.world.rebind_actor(enemy) and ok
    ok = sd.world.rebind_actor(minion) and ok
  end
end
print("ok=" .. tostring(ok))
print("enemy=" .. tostring(enemy))
print("minion=" .. tostring(minion))
print("distance=" .. string.format(
  "%.3f", math.sqrt(
    (enemy_x - minion_x) * (enemy_x - minion_x) +
    (enemy_y - minion_y) * (enemy_y - minion_y))))
"""


DISARM_ENEMY_ARENA_LUA = r"""
local present = type(_G.__sdmod_defense_enemies) == "table"
_G.__sdmod_defense_enemies = nil
print("ok=true")
print("present=" .. tostring(present))
"""


def _default_instance_prefix() -> str:
    return f"ert-{os.getpid():x}-{uuid.uuid4().hex[:6]}"


def _path_from_powershell(path: str) -> Path:
    if os.name == "nt":
        return Path(path)
    completed = subprocess.run(
        ["wslpath", "-u", path],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=5.0,
        check=False,
    )
    converted = completed.stdout.strip()
    if completed.returncode != 0 or not converted:
        raise VerifyFailure(
            f"could not convert PowerShell path {path!r}: "
            f"{completed.stderr or completed.stdout}"
        )
    return Path(converted)


def _parse_target_records(text: str) -> dict[int, dict[str, int]]:
    records: dict[int, dict[str, int]] = {}
    for line in text.splitlines():
        if not line.startswith("E|"):
            continue
        parts = line.split("|")
        if len(parts) != 16:
            raise VerifyFailure(f"malformed enemy target record: {line!r}")
        values = [int(part) for part in parts[1:]]
        record = {
            "network_id": values[0],
            "actor_address": values[1],
            "native_type_id": values[2],
            "target_actor_address": values[3],
            "target_participant_id": values[4],
            "target_native_type_id": values[5],
            "actor_slot": values[6],
            "world_slot": values[7],
            "target_actor_slot": values[8],
            "target_world_slot": values[9],
            "target_bucket_delta": values[10],
            "target_ineligible_state": values[11],
            "authority_target_participant_id": values[12],
            "authority_target_native_type_id": values[13],
            "authority_target_authoritative": values[14],
        }
        records[record["network_id"]] = record
    return records


def _capture_targets(
    pipe_name: str,
    local_participant_id: int,
) -> dict[int, dict[str, int]]:
    code = CAPTURE_TARGETS_LUA.replace(
        "__LOCAL_PARTICIPANT_ID__",
        str(local_participant_id),
    )
    return _parse_target_records(lua(pipe_name, code, timeout=5.0))


def _target_matches(
    record: dict[str, int] | None,
    *,
    expected_participant_id: int,
    expected_native_type_id: int,
) -> bool:
    if not isinstance(record, dict):
        return False
    if expected_participant_id == 0 and expected_native_type_id == 0:
        return False
    if (
        expected_participant_id != 0
        and record.get("target_participant_id") != expected_participant_id
    ):
        return False
    if (
        expected_native_type_id != 0
        and record.get("target_native_type_id") != expected_native_type_id
    ):
        return False
    if expected_native_type_id != 0 and (
        record.get("authority_target_participant_id") !=
            expected_participant_id
        or record.get("authority_target_native_type_id") !=
            expected_native_type_id
        or record.get("authority_target_authoritative") != 1
    ):
        return False
    return (
        record.get("target_actor_address", 0) != 0
        and record.get("target_ineligible_state", 1) == 0
    )


def analyze_retarget_samples(
    samples: list[dict[str, Any]],
    *,
    expected_participant_id: int,
    expected_native_type_id: int,
    dead_participant_id: int,
) -> dict[str, Any]:
    host_match_indices = [
        index
        for index, sample in enumerate(samples)
        if _target_matches(
            sample.get("host"),
            expected_participant_id=expected_participant_id,
            expected_native_type_id=expected_native_type_id,
        )
    ]
    client_match_indices = [
        index
        for index, sample in enumerate(samples)
        if _target_matches(
            sample.get("client"),
            expected_participant_id=expected_participant_id,
            expected_native_type_id=expected_native_type_id,
        )
    ]
    both_match_indices = sorted(
        set(host_match_indices).intersection(client_match_indices)
    )
    first_host_index = (
        host_match_indices[0] if host_match_indices else None
    )
    first_client_index = (
        client_match_indices[0] if client_match_indices else None
    )
    first_both_index = (
        both_match_indices[0] if both_match_indices else None
    )
    host_latency_ms = (
        float(samples[first_host_index]["elapsed_seconds"]) * 1000.0
        if first_host_index is not None else None
    )
    client_latency_ms = (
        float(samples[first_client_index]["elapsed_seconds"]) * 1000.0
        if first_client_index is not None else None
    )
    stable_match_samples = 0
    if first_both_index is not None:
        for sample in samples[first_both_index:]:
            if (
                _target_matches(
                    sample.get("host"),
                    expected_participant_id=expected_participant_id,
                    expected_native_type_id=expected_native_type_id,
                )
                and _target_matches(
                    sample.get("client"),
                    expected_participant_id=expected_participant_id,
                    expected_native_type_id=expected_native_type_id,
                )
            ):
                stable_match_samples += 1
            else:
                break
    dead_target_sample_count = sum(
        1
        for sample in samples
        for role in ("host", "client")
        if isinstance(sample.get(role), dict)
        and dead_participant_id != 0
        and sample[role].get("target_participant_id") ==
            dead_participant_id
    )
    passed = (
        host_latency_ms is not None
        and host_latency_ms <= MAX_HOST_REACQUIRE_LATENCY_MS
        and client_latency_ms is not None
        and client_latency_ms <= MAX_CLIENT_REACQUIRE_LATENCY_MS
        and stable_match_samples >= MINIMUM_STABLE_MATCH_SAMPLES
    )
    return {
        "passed": passed,
        "expected_participant_id": expected_participant_id,
        "expected_native_type_id": expected_native_type_id,
        "dead_participant_id": dead_participant_id,
        "host_reacquire_latency_ms": host_latency_ms,
        "client_reacquire_latency_ms": client_latency_ms,
        "max_host_reacquire_latency_ms":
            MAX_HOST_REACQUIRE_LATENCY_MS,
        "max_client_reacquire_latency_ms":
            MAX_CLIENT_REACQUIRE_LATENCY_MS,
        "first_both_match_sample_index": first_both_index,
        "stable_match_sample_count": stable_match_samples,
        "minimum_stable_match_samples":
            MINIMUM_STABLE_MATCH_SAMPLES,
        "dead_target_sample_count": dead_target_sample_count,
        "sample_count": len(samples),
        "final_host": samples[-1].get("host") if samples else None,
        "final_client":
            samples[-1].get("client") if samples else None,
    }


def _parse_native_actors(text: str) -> list[dict[str, int | float]]:
    actors: list[dict[str, int | float]] = []
    for line in text.splitlines():
        if not line.startswith("A|"):
            continue
        parts = line.split("|")
        if len(parts) != 7:
            raise VerifyFailure(f"malformed native actor record: {line!r}")
        actors.append(
            {
                "actor_address": int(parts[1]),
                "native_type_id": int(parts[2]),
                "actor_slot": int(parts[3]),
                "world_slot": int(parts[4]),
                "x": float(parts[5]),
                "y": float(parts[6]),
            }
        )
    return actors


def _query_native_actors(
    pipe_name: str,
    native_type_id: int,
) -> list[dict[str, int | float]]:
    code = QUERY_NATIVE_ACTORS_LUA.replace(
        "__NATIVE_TYPE_ID__",
        str(native_type_id),
    )
    return _parse_native_actors(lua(pipe_name, code, timeout=5.0))


def _wait_for_native_actor(
    pipe_name: str,
    native_type_id: int,
    *,
    timeout: float,
) -> dict[str, int | float]:
    deadline = time.monotonic() + timeout
    last: list[dict[str, int | float]] = []
    while time.monotonic() < deadline:
        last = _query_native_actors(pipe_name, native_type_id)
        if last:
            return last[0]
        time.sleep(0.05)
    raise VerifyFailure(
        f"native actor 0x{native_type_id:X} did not materialize on "
        f"{pipe_name}: {last}"
    )


def _wait_for_enemy_network_id(
    host_pipe: str,
    enemy_actor_address: int,
    *,
    timeout: float = 10.0,
) -> tuple[int, dict[str, int]]:
    deadline = time.monotonic() + timeout
    last: dict[int, dict[str, int]] = {}
    while time.monotonic() < deadline:
        last = _capture_targets(host_pipe, HOST_ID)
        for network_id, record in last.items():
            if record["actor_address"] == enemy_actor_address:
                return network_id, record
        time.sleep(0.05)
    raise VerifyFailure(
        "selected wave enemy never received a replicated network identity: "
        f"actor=0x{enemy_actor_address:X} records={last}"
    )


def _wait_for_logical_death(
    victim_pipe: str,
    *,
    timeout: float,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = query_spectator_state(victim_pipe)
        hp = float(last.get("hp", "0"))
        if hp <= 0.0:
            return last
        time.sleep(0.025)
    raise VerifyFailure(
        f"victim never reached authoritative life zero: {last}"
    )


def _sample_target_pair(
    *,
    host_pipe: str,
    client_pipe: str,
    network_id: int,
    sample_seconds: float = TARGET_SAMPLE_WINDOW_SECONDS,
) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    started = time.monotonic()
    deadline = started + sample_seconds
    while time.monotonic() < deadline:
        elapsed = time.monotonic() - started
        host = _capture_targets(host_pipe, HOST_ID)
        client = _capture_targets(client_pipe, CLIENT_ID)
        samples.append(
            {
                "elapsed_seconds": elapsed,
                "host": host.get(network_id),
                "client": client.get(network_id),
            }
        )
        time.sleep(TARGET_SAMPLE_INTERVAL_SECONDS)
    return samples


def _capture_frame(
    pipe_name: str,
    output_path: Path,
    *,
    attempts: int = 5,
) -> dict[str, Any]:
    errors: list[str] = []
    for attempt in range(1, attempts + 1):
        try:
            result = capture_game_backbuffer(pipe_name, output_path)
            result["attempt"] = attempt
            result["prior_errors"] = errors
            return result
        except VerifyFailure as exc:
            errors.append(str(exc))
            if attempt < attempts:
                time.sleep(0.1)
    raise VerifyFailure(
        f"could not capture rendered frame from {pipe_name}: {errors}"
    )


def _prepare_wave_schedule(
    game_directory: Path,
    artifact_directory: Path,
) -> dict[str, Any]:
    return _materialize_native_wave_schedule(
        retail_wave_path=game_directory.resolve() / "data" / "wave.txt",
        fixture_path=WAVE_FIXTURES["melee"],
        output_path=artifact_directory / "effective-melee-wave.txt",
    )


def _launch_ready_pair(
    *,
    instance_prefix: str,
    ports: list[int],
    game_directory: Path,
    launcher_path: Path | None,
    artifact_directory: Path,
    client_preset: str,
    enable_audio: bool,
) -> tuple[dict[str, object], Path, str, str]:
    wave_schedule = _prepare_wave_schedule(
        game_directory,
        artifact_directory,
    )
    launch = launch_pair(
        host_preset="map_create_fire_mind_hub",
        client_preset=client_preset,
        temporary_host_profile=True,
        tile_windows=False,
        test_blank_boneyard=True,
        test_wave_override=Path(wave_schedule["effective_path"]),
        use_sandbox_preset_flow=True,
        kill_existing=False,
        instance_prefix=instance_prefix,
        host_port=ports[0],
        client_port=ports[1],
        game_directory=game_directory,
        launcher_path=launcher_path,
        exact_mod_id=ACCEPTANCE_MOD_ID,
        enable_audio=enable_audio,
    )
    runtime_root_value = launch.get("runtimeRoot")
    if not isinstance(runtime_root_value, str) or not runtime_root_value:
        raise VerifyFailure(
            f"pair launch omitted its disposable runtime root: {launch}"
        )
    runtime_root = _path_from_powershell(runtime_root_value)
    process_ids = game_process_ids(launch)
    if len(process_ids) != 2:
        stop_exact_game_processes(launch)
        raise VerifyFailure(
            f"isolated enemy-retarget pair did not report two PIDs: "
            f"{launch}"
        )
    host_pipe = str(launch["hostLuaPipe"])
    client_pipe = str(launch["clientLuaPipe"])
    _disable_companion_bots([host_pipe, client_pipe])
    _start_testrun_when_ready(host_pipe)
    wait_for_scene(host_pipe, "testrun", 45.0)
    wait_for_scene(client_pipe, "testrun", 45.0)
    wait_for_remote(
        host_pipe,
        CLIENT_ID,
        CLIENT_NAME,
        "testrun",
        45.0,
    )
    wait_for_remote(
        client_pipe,
        HOST_ID,
        HOST_NAME,
        "testrun",
        45.0,
    )
    set_local_player_vitals(host_pipe, SURVIVOR_HP, SURVIVOR_HP)
    set_local_player_vitals(client_pipe, SURVIVOR_HP, SURVIVOR_HP)
    return launch, runtime_root, host_pipe, client_pipe


def _start_single_enemy_wave(
    host_pipe: str,
) -> tuple[dict[str, int | float], dict[str, Any]]:
    pre_wave_actor_addresses = {
        int(actor["actor_address"])
        for actor in _query_live_enemies(host_pipe)
    }
    wave_start = _start_waves(host_pipe)
    enemy = _wait_for_new_wave_enemy(
        host_pipe,
        pre_wave_actor_addresses=pre_wave_actor_addresses,
    )
    _stabilize_enemy(
        host_pipe,
        enemy_actor_address=int(enemy["actor_address"]),
    )
    return enemy, {
        "pre_wave_actor_addresses":
            sorted(pre_wave_actor_addresses),
        "wave_start": wave_start,
        "stabilized_hp": ATTACKER_STABILIZED_HP,
    }


def _run_death_case(
    *,
    victim_role: str,
    base_instance_prefix: str,
    ports: list[int],
    game_directory: Path,
    launcher_path: Path | None,
    artifact_root: Path,
    enable_audio: bool,
    measure_only: bool,
) -> dict[str, Any]:
    if victim_role not in {"host", "client"}:
        raise ValueError(f"invalid victim role: {victim_role}")
    instance_prefix = f"{base_instance_prefix}-{victim_role[:1]}d"
    artifact_directory = artifact_root / f"{victim_role}-death"
    artifact_directory.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {
        "scenario": f"{victim_role}_dies",
        "instance_prefix": instance_prefix,
        "ports": ports,
    }
    launch: dict[str, object] = {}
    runtime_root = artifact_directory / "runtime"
    cleanup: list[dict[str, Any]] = []
    try:
        launch, runtime_root, host_pipe, client_pipe = _launch_ready_pair(
            instance_prefix=instance_prefix,
            ports=ports,
            game_directory=game_directory,
            launcher_path=launcher_path,
            artifact_directory=artifact_directory,
            client_preset="map_create_ether_mind_hub",
            enable_audio=enable_audio,
        )
        result["launch"] = launch
        result["process_ids"] = game_process_ids(launch)
        victim_pipe = host_pipe if victim_role == "host" else client_pipe
        survivor_pipe = (
            client_pipe if victim_role == "host" else host_pipe
        )
        victim_id = HOST_ID if victim_role == "host" else CLIENT_ID
        survivor_id = CLIENT_ID if victim_role == "host" else HOST_ID
        victim_x, victim_y = 1850.0, 1750.0
        survivor_x, survivor_y = 2050.0, 1750.0
        result["placement"] = {
            "victim": place_player(
                victim_pipe,
                victim_x,
                victim_y,
                0.0,
            ),
            "survivor": place_player(
                survivor_pipe,
                survivor_x,
                survivor_y,
                180.0,
            ),
            "separation": math.hypot(
                survivor_x - victim_x,
                survivor_y - victim_y,
            ),
        }
        enemy, wave_evidence = _start_single_enemy_wave(host_pipe)
        result["wave"] = wave_evidence
        result["enemy"] = enemy
        enemy_address = int(enemy["actor_address"])
        network_id, initial_target = _wait_for_enemy_network_id(
            host_pipe,
            enemy_address,
        )
        result["enemy_network_id"] = network_id
        result["initial_target_record"] = initial_target
        result["arena"] = _arm_enemy_arena(
            host_pipe,
            victim_x,
            victim_y,
        )
        victim_before = query_spectator_state(victim_pipe)
        result["attack"] = _set_enemy_attack(
            host_pipe,
            target_x=victim_x,
            target_y=victim_y,
            target_participant_id=(
                0 if victim_role == "host" else victim_id
            ),
            enemy_actor_address=enemy_address,
            attack_distance=64.0,
        )
        result["damage_observed"] = _wait_for_victim_damage(
            victim_pipe,
            baseline_hp=float(victim_before["hp"]),
            timeout=18.0,
        )
        result["victim_armed"] = set_local_player_vitals(
            victim_pipe,
            VICTIM_ARMING_HP,
            VICTIM_MAX_HP,
        )
        result["logical_death"] = _wait_for_logical_death(
            victim_pipe,
            timeout=18.0,
        )
        result["arena_disarmed"] = parse_key_values(
            lua(host_pipe, DISARM_ENEMY_ARENA_LUA)
        )
        samples = _sample_target_pair(
            host_pipe=host_pipe,
            client_pipe=client_pipe,
            network_id=network_id,
        )
        result["target_samples"] = samples
        result["summary"] = analyze_retarget_samples(
            samples,
            expected_participant_id=survivor_id,
            expected_native_type_id=0,
            dead_participant_id=victim_id,
        )
        result["screenshots"] = {
            "host": _capture_frame(
                host_pipe,
                artifact_directory / "host-after-reacquire.png",
            ),
            "client": _capture_frame(
                client_pipe,
                artifact_directory / "client-after-reacquire.png",
            ),
        }
        result["passed"] = bool(result["summary"]["passed"])
        if not result["passed"] and not measure_only:
            raise VerifyFailure(
                f"{victim_role}-death nearest-target reacquisition "
                f"failed: {result['summary']}"
            )
        return result
    except Exception as exc:
        result["error"] = str(exc)
        result["error_type"] = type(exc).__name__
        raise EnemyRetargetFailure(str(exc), result) from exc
    finally:
        if launch:
            cleanup = stop_exact_game_processes(launch)
        result["cleanup"] = cleanup


def _run_minion_case(
    *,
    base_instance_prefix: str,
    ports: list[int],
    game_directory: Path,
    launcher_path: Path | None,
    artifact_root: Path,
    enable_audio: bool,
    measure_only: bool,
) -> dict[str, Any]:
    instance_prefix = f"{base_instance_prefix}-mn"
    artifact_directory = artifact_root / "ether-minion"
    artifact_directory.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {
        "scenario": "ether_minion_nearest",
        "instance_prefix": instance_prefix,
        "ports": ports,
    }
    launch: dict[str, object] = {}
    runtime_root = artifact_directory / "runtime"
    cleanup: list[dict[str, Any]] = []
    try:
        launch, runtime_root, host_pipe, client_pipe = _launch_ready_pair(
            instance_prefix=instance_prefix,
            ports=ports,
            game_directory=game_directory,
            launcher_path=launcher_path,
            artifact_directory=artifact_directory,
            client_preset="map_create_ether_mind_hub",
            enable_audio=enable_audio,
        )
        result["launch"] = launch
        result["process_ids"] = game_process_ids(launch)
        place_player(host_pipe, 2300.0, 1750.0, 180.0)
        place_player(client_pipe, 2500.0, 1750.0, 180.0)
        enemy, wave_evidence = _start_single_enemy_wave(host_pipe)
        result["wave"] = wave_evidence
        result["enemy"] = enemy
        enemy_address = int(enemy["actor_address"])
        network_id, initial_target = _wait_for_enemy_network_id(
            host_pipe,
            enemy_address,
        )
        result["enemy_network_id"] = network_id
        result["initial_target_record"] = initial_target
        client_log = (
            runtime_root / "instances" /
            f"{instance_prefix}-client" / "stage" /
            ".sdmod" / "logs" / "solomondarkmodloader.log"
        )
        host_log = (
            runtime_root / "instances" /
            f"{instance_prefix}-host" / "stage" /
            ".sdmod" / "logs" / "solomondarkmodloader.log"
        )
        direction = focus.Direction(
            name="client_ether_minion",
            process_role="client",
            source_id=CLIENT_ID,
            source_pipe=client_pipe,
            source_log=client_log,
            observer_log=host_log,
        )
        result["call_leviathan_input"] = (
            focus.cast_secondary_belt_slot(
                direction,
                0,
                8.0,
                cursor_world=(1890.0, 1750.0),
            )
        )
        host_minion = _wait_for_native_actor(
            host_pipe,
            ETHER_MINION_NATIVE_TYPE_ID,
            timeout=10.0,
        )
        client_minion = _wait_for_native_actor(
            client_pipe,
            ETHER_MINION_NATIVE_TYPE_ID,
            timeout=10.0,
        )
        result["minion"] = {
            "native_type_id": ETHER_MINION_NATIVE_TYPE_ID,
            "skill_row": CALL_LEVIATHAN_SKILL_ROW,
            "host": host_minion,
            "client": client_minion,
        }
        arrange_code = (
            ARRANGE_MINION_NEAREST_LUA
            .replace("__ENEMY_ACTOR_ADDRESS__", str(enemy_address))
            .replace(
                "__MINION_ACTOR_ADDRESS__",
                str(int(host_minion["actor_address"])),
            )
        )
        result["arrangement"] = parse_key_values(
            lua(host_pipe, arrange_code, timeout=10.0)
        )
        if result["arrangement"].get("ok") != "true":
            raise VerifyFailure(
                f"could not arrange nearest Ether minion: "
                f"{result['arrangement']}"
            )
        samples = _sample_target_pair(
            host_pipe=host_pipe,
            client_pipe=client_pipe,
            network_id=network_id,
        )
        result["target_samples"] = samples
        result["summary"] = analyze_retarget_samples(
            samples,
            expected_participant_id=CLIENT_ID,
            expected_native_type_id=ETHER_MINION_NATIVE_TYPE_ID,
            dead_participant_id=0,
        )
        result["screenshots"] = {
            "host": _capture_frame(
                host_pipe,
                artifact_directory / "host-targeting-ether-minion.png",
            ),
            "client": _capture_frame(
                client_pipe,
                artifact_directory / "client-targeting-ether-minion.png",
            ),
        }
        result["passed"] = bool(result["summary"]["passed"])
        if not result["passed"] and not measure_only:
            raise VerifyFailure(
                "nearest Ether-minion acquisition failed: "
                f"{result['summary']}"
            )
        return result
    except Exception as exc:
        result["error"] = str(exc)
        result["error_type"] = type(exc).__name__
        raise EnemyRetargetFailure(str(exc), result) from exc
    finally:
        if launch:
            cleanup = stop_exact_game_processes(launch)
        result["cleanup"] = cleanup


def run_live_verification(
    *,
    scenarios: list[str],
    instance_prefix: str,
    ports: list[int],
    game_directory: Path,
    launcher_path: Path | None,
    artifact_root: Path,
    enable_audio: bool,
    measure_only: bool,
) -> dict[str, Any]:
    if len(ports) != 2:
        raise ValueError(f"expected two UDP ports, got {ports}")
    result: dict[str, Any] = {
        "ok": False,
        "measure_only": measure_only,
        "instance_prefix": instance_prefix,
        "ports": ports,
        "scenarios_requested": scenarios,
        "scenarios": {},
    }
    for scenario in scenarios:
        try:
            if scenario == "host-death":
                evidence = _run_death_case(
                    victim_role="host",
                    base_instance_prefix=instance_prefix,
                    ports=ports,
                    game_directory=game_directory,
                    launcher_path=launcher_path,
                    artifact_root=artifact_root,
                    enable_audio=enable_audio,
                    measure_only=measure_only,
                )
            elif scenario == "client-death":
                evidence = _run_death_case(
                    victim_role="client",
                    base_instance_prefix=instance_prefix,
                    ports=ports,
                    game_directory=game_directory,
                    launcher_path=launcher_path,
                    artifact_root=artifact_root,
                    enable_audio=enable_audio,
                    measure_only=measure_only,
                )
            elif scenario == "ether-minion":
                evidence = _run_minion_case(
                    base_instance_prefix=instance_prefix,
                    ports=ports,
                    game_directory=game_directory,
                    launcher_path=launcher_path,
                    artifact_root=artifact_root,
                    enable_audio=enable_audio,
                    measure_only=measure_only,
                )
            else:
                raise ValueError(f"unknown scenario: {scenario}")
        except EnemyRetargetFailure as exc:
            result["scenarios"][scenario] = exc.evidence
            result["error"] = str(exc)
            result["error_scenario"] = scenario
            raise EnemyRetargetFailure(str(exc), result) from exc
        result["scenarios"][scenario] = evidence
    failed = [
        scenario
        for scenario, evidence in result["scenarios"].items()
        if not evidence.get("passed", False)
    ]
    result["failed_scenarios"] = failed
    result["ok"] = measure_only or not failed
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance-prefix", default="")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--artifact-root", type=Path, default=None)
    parser.add_argument("--game-dir", type=Path, required=True)
    parser.add_argument("--launcher-path", type=Path, default=None)
    parser.add_argument(
        "--scenario",
        action="append",
        choices=("host-death", "client-death", "ether-minion"),
        dest="scenarios",
    )
    parser.add_argument("--measure-only", action="store_true")
    parser.add_argument("--enable-audio", action="store_true")
    parser.add_argument("--host-port", type=int, default=None)
    parser.add_argument("--client-port", type=int, default=None)
    args = parser.parse_args()

    if (args.host_port is None) != (args.client_port is None):
        parser.error(
            "--host-port and --client-port must be supplied together"
        )
    ports = (
        [args.host_port, args.client_port]
        if args.host_port is not None
        else select_available_windows_udp_ports(2)
    )
    instance_prefix = (
        args.instance_prefix or _default_instance_prefix()
    )
    if len(instance_prefix) > 42:
        parser.error(
            "--instance-prefix must leave room for the scenario suffix"
        )
    scenarios = args.scenarios or [
        "host-death",
        "client-death",
        "ether-minion",
    ]
    artifact_root = (
        args.artifact_root
        if args.artifact_root is not None
        else ARTIFACT_ROOT / instance_prefix
    )
    result: dict[str, Any] = {
        "ok": False,
        "instance_prefix": instance_prefix,
    }
    exit_code = 1
    try:
        result = run_live_verification(
            scenarios=scenarios,
            instance_prefix=instance_prefix,
            ports=[int(port) for port in ports],
            game_directory=args.game_dir,
            launcher_path=args.launcher_path,
            artifact_root=artifact_root,
            enable_audio=args.enable_audio,
            measure_only=args.measure_only,
        )
        exit_code = 0 if result["ok"] else 1
    except Exception as exc:  # noqa: BLE001 - persist exact live evidence.
        if isinstance(exc, EnemyRetargetFailure):
            result = exc.evidence
        result["ok"] = False
        result["error"] = str(exc)
        result["error_type"] = type(exc).__name__
        result["traceback"] = traceback.format_exc()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summaries = {
        name: evidence.get("summary")
        for name, evidence in result.get("scenarios", {}).items()
        if isinstance(evidence, dict)
    }
    print(
        json.dumps(
            {
                "ok": result.get("ok", False),
                "measure_only": args.measure_only,
                "instance_prefix": instance_prefix,
                "summaries": summaries,
                "error": result.get("error"),
                "output": str(args.output),
                "artifact_root": str(artifact_root),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
