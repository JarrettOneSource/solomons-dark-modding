#!/usr/bin/env python3
"""Verify replicated cast-event parity for Earth audio and Lightning damage."""

from __future__ import annotations

import argparse
import json
import os
import select
import socket
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_NAME,
    HOST_ID,
    HOST_NAME,
    VerifyFailure,
    extract_json,
    game_process_ids,
    launch_pair,
    lua,
    parse_key_values,
    path_for_powershell,
    stop_game_processes,
    wait_for_scene,
)


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "runtime" / "multiplayer_replicated_audio_events.json"
ACCEPTANCE_MOD_ID = "sample.lua.ui_sandbox_lab"
EARTH_PRESET = "map_create_earth_mind_hub"
EARTH_HOLD_FRAMES = 170
AIR_PRESET = "map_create_air_mind_hub"
LIGHTNING_HOLD_FRAMES = 170
LIGHTNING_TARGET_HP = 40.0
SOLO_PARTICIPANT_ID = 0x2000000000001A17
LIGHTNING_DAMAGE_TICK = 0.025
LIGHTNING_DAMAGE_EVENT_COUNT_TOLERANCE = 2
LIGHTNING_DAMAGE_RELATIVE_TOLERANCE = 0.02

SOUND_PLAY_EX = 0x00407CD0
SOUND_LOOP_START = 0x00408320
SOUND_LOOP_STOP = 0x00408350
BASS_CHANNEL_PLAY = 0x006B01B0
EARTH_BOULDER_CTOR = 0x005FA270

TRACE_POINTS = (
    (SOUND_PLAY_EX, "sound_play_ex", 0),
    (SOUND_LOOP_START, "sound_loop_start", 0),
    (SOUND_LOOP_STOP, "sound_loop_stop", 0),
    (BASS_CHANNEL_PLAY, "bass_channel_play", 6),
    (EARTH_BOULDER_CTOR, "earth_boulder_ctor", 0),
)

TRIGGER_COUNT_KEYS = (
    "boulder_ctor",
    "startboulder_one_shot",
    "gather_loop_start",
    "gather_loop_stop",
    "gather_bass_channel_play",
    "rolling_loop_start",
    "rockhit_one_shot",
)

CAST_LIFECYCLE_TRIGGER_KEYS = (
    "boulder_ctor",
    "startboulder_one_shot",
    "gather_loop_start",
    "gather_loop_stop",
    "gather_bass_channel_play",
)

SELECT_LIGHTNING_TARGET_LUA = r"""
local excluded_id = tonumber("__EXCLUDED_ID__") or 0
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local replicated = sd.world.get_replicated_actors and
  sd.world.get_replicated_actors() or nil
local best = nil
if replicated and replicated.actors then
  for _, snapshot in ipairs(replicated.actors) do
    local id = tonumber(snapshot.network_actor_id) or 0
    local hp = tonumber(snapshot.hp) or 0
    local actor = id ~= 0 and sd.world.get_run_enemy_by_network_id and
      sd.world.get_run_enemy_by_network_id(id) or nil
    if id ~= excluded_id and actor ~= nil and
       snapshot.tracked_enemy and not snapshot.dead and hp > 0 then
      if best == nil or hp > (tonumber(best.hp) or 0) then best = snapshot end
    end
  end
end
emit("ok", best ~= nil)
emit("network_actor_id", best and string.format("%.0f", best.network_actor_id) or "0")
emit("x", best and string.format("%.9f", tonumber(best.x) or 0) or "0")
emit("y", best and string.format("%.9f", tonumber(best.y) or 0) or "0")
emit("hp", best and string.format("%.9f", tonumber(best.hp) or 0) or "0")
emit("max_hp", best and string.format("%.9f", tonumber(best.max_hp) or 0) or "0")
"""

ARM_LIGHTNING_DAMAGE_MONITOR_LUA = r"""
local target_id = tonumber("__TARGET_ID__") or 0
local target_x = tonumber("__TARGET_X__") or 0
local target_y = tonumber("__TARGET_Y__") or 0
local target_hp = tonumber("__TARGET_HP__") or 40
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local hp_offset = sd.debug.layout_offset("enemy_current_hp")
local x_offset = sd.debug.layout_offset("actor_position_x")
local y_offset = sd.debug.layout_offset("actor_position_y")
local target = sd.world.get_run_enemy_by_network_id and
  sd.world.get_run_enemy_by_network_id(target_id) or nil
local address = tonumber(target and target.actor_address) or 0
if address == 0 or hp_offset == nil or x_offset == nil or y_offset == nil then
  emit("armed", false)
  emit("reason", "target_or_layout_missing")
  return
end
local health_set = sd.gameplay.set_run_enemy_health(address, target_hp, target_hp)
local write_x = sd.debug.write_float(address + x_offset, target_x)
local write_y = sd.debug.write_float(address + y_offset, target_y)
if not _G.__sdmod_lightning_damage_monitor_registered then
  sd.events.on("runtime.tick", function(event)
    local monitor = _G.__sdmod_lightning_damage_monitor
    if type(monitor) ~= "table" or not monitor.active then return end
    local live = sd.world.get_run_enemy_by_network_id and
      sd.world.get_run_enemy_by_network_id(monitor.target_id) or nil
    local live_address = tonumber(live and live.actor_address) or 0
    if live_address == 0 then
      monitor.missing_samples = monitor.missing_samples + 1
      return
    end
    sd.debug.write_float(live_address + monitor.x_offset, monitor.x)
    sd.debug.write_float(live_address + monitor.y_offset, monitor.y)
    local replicated = sd.world.get_replicated_actors and
      sd.world.get_replicated_actors() or nil
    for index, snapshot in ipairs(
        replicated and replicated.actors or {}) do
      local network_id = tonumber(snapshot.network_actor_id) or 0
      if snapshot.tracked_enemy and network_id ~= monitor.target_id then
        local other = sd.world.get_run_enemy_by_network_id and
          sd.world.get_run_enemy_by_network_id(network_id) or nil
        local other_address = tonumber(other and other.actor_address) or 0
        if other_address ~= 0 then
          sd.debug.write_float(
            other_address + monitor.x_offset,
            monitor.x + 2000.0 + index * 16.0)
          sd.debug.write_float(
            other_address + monitor.y_offset,
            monitor.y + 2000.0)
        end
      end
    end
    local raw_hp = tonumber(sd.debug.read_float(
      live_address + monitor.hp_offset))
    if raw_hp == nil then
      monitor.read_errors = monitor.read_errors + 1
      return
    end
    local now = tonumber(event and event.monotonic_milliseconds) or 0
    if math.abs(monitor.previous_hp - raw_hp) > 0.0000001 then
      monitor.events[#monitor.events + 1] = {
        monotonic_ms = now,
        tick = tonumber(event and event.tick_count) or 0,
        actor_address = live_address,
        before_hp = monitor.previous_hp,
        after_hp = raw_hp,
        delta = monitor.previous_hp - raw_hp,
      }
    end
    monitor.previous_hp = raw_hp
    monitor.last_hp = raw_hp
  end)
  _G.__sdmod_lightning_damage_monitor_registered = true
end
local raw_hp = tonumber(sd.debug.read_float(address + hp_offset)) or 0
_G.__sdmod_lightning_damage_monitor = {
  active = true,
  target_id = target_id,
  x = target_x,
  y = target_y,
  hp_offset = hp_offset,
  x_offset = x_offset,
  y_offset = y_offset,
  initial_hp = raw_hp,
  previous_hp = raw_hp,
  last_hp = raw_hp,
  events = {},
  missing_samples = 0,
  read_errors = 0,
}
emit("armed", health_set and write_x and write_y)
emit("actor_address", string.format("0x%08X", address))
emit("initial_hp", string.format("%.9f", raw_hp))
"""

ARM_LIGHTNING_TARGET_REFRESH_LUA = r"""
local target_id = tonumber("__TARGET_ID__") or 0
local target_x = tonumber("__TARGET_X__") or 0
local target_y = tonumber("__TARGET_Y__") or 0
local function emit(key, value) print(key .. "=" .. tostring(value)) end
if not _G.__sdmod_lightning_target_refresh_registered then
  sd.events.on("runtime.tick", function()
    local refresh = _G.__sdmod_lightning_target_refresh
    if type(refresh) ~= "table" or not refresh.active then return end
    local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
    local actor = tonumber(player and player.actor_address) or 0
    local target = sd.world.get_run_enemy_by_network_id and
      sd.world.get_run_enemy_by_network_id(refresh.target_id) or nil
    local target_actor = tonumber(target and target.actor_address) or 0
    if actor == 0 or target_actor == 0 then
      refresh.missing_samples = refresh.missing_samples + 1
      return
    end
    sd.debug.write_float(actor + refresh.position_x_offset, refresh.x)
    sd.debug.write_float(actor + refresh.position_y_offset, refresh.y + 96.0)
    sd.debug.write_float(actor + refresh.heading_offset, 0.0)
    sd.debug.write_ptr(actor + refresh.current_target_offset, target_actor)
    local target_group = sd.debug.read_u8(
      target_actor + refresh.actor_slot_offset)
    local target_slot = sd.debug.read_u16(
      target_actor + refresh.world_slot_offset)
    sd.debug.write_u8(
      actor + refresh.spell_target_group_offset, target_group)
    sd.debug.write_u16(
      actor + refresh.spell_target_slot_offset, target_slot)
    sd.debug.write_float(actor + refresh.aim_x_offset, refresh.x)
    sd.debug.write_float(actor + refresh.aim_y_offset, refresh.y)
    refresh.applied_samples = refresh.applied_samples + 1
  end)
  _G.__sdmod_lightning_target_refresh_registered = true
end
local offsets = {
  position_x_offset = sd.debug.layout_offset("actor_position_x"),
  position_y_offset = sd.debug.layout_offset("actor_position_y"),
  heading_offset = sd.debug.layout_offset("actor_heading"),
  current_target_offset = sd.debug.layout_offset("actor_current_target_actor"),
  actor_slot_offset = sd.debug.layout_offset("actor_slot"),
  world_slot_offset = sd.debug.layout_offset("actor_world_slot"),
  spell_target_group_offset =
    sd.debug.layout_offset("actor_spell_target_group_byte"),
  spell_target_slot_offset =
    sd.debug.layout_offset("actor_spell_target_slot_short"),
  aim_x_offset = sd.debug.layout_offset("actor_aim_target_x"),
  aim_y_offset = sd.debug.layout_offset("actor_aim_target_y"),
}
local complete = true
for _, value in pairs(offsets) do
  if value == nil then complete = false end
end
offsets.active = complete
offsets.target_id = target_id
offsets.x = target_x
offsets.y = target_y
offsets.applied_samples = 0
offsets.missing_samples = 0
_G.__sdmod_lightning_target_refresh = offsets
emit("armed", complete)
"""

COLLECT_LIGHTNING_DAMAGE_MONITOR_LUA = r"""
local monitor = _G.__sdmod_lightning_damage_monitor
if type(monitor) ~= "table" then error("Lightning damage monitor unavailable") end
monitor.active = false
print(table.concat({
  "META",
  tostring(monitor.target_id or 0),
  string.format("%.9f", monitor.initial_hp or 0),
  string.format("%.9f", monitor.last_hp or 0),
  tostring(#(monitor.events or {})),
  tostring(monitor.missing_samples or 0),
  tostring(monitor.read_errors or 0),
}, "|"))
for index, event in ipairs(monitor.events or {}) do
  print(table.concat({
    "D",
    tostring(index),
    tostring(event.monotonic_ms or 0),
    tostring(event.tick or 0),
    string.format("0x%08X", event.actor_address or 0),
    string.format("%.9f", event.before_hp or 0),
    string.format("%.9f", event.after_hp or 0),
    string.format("%.9f", event.delta or 0),
  }, "|"))
end
"""

STOP_LIGHTNING_TARGET_REFRESH_LUA = r"""
local refresh = _G.__sdmod_lightning_target_refresh
if type(refresh) == "table" then refresh.active = false end
print("applied_samples=" .. tostring(
  type(refresh) == "table" and refresh.applied_samples or 0))
print("missing_samples=" .. tostring(
  type(refresh) == "table" and refresh.missing_samples or 0))
"""


def assert_lightning_damage_event_parity(
    *,
    label: str,
    local_events: list[float],
    remote_events: list[float],
) -> dict[str, Any]:
    local_positive = [value for value in local_events if value > 0.0]
    remote_positive = [value for value in remote_events if value > 0.0]
    local_damage = sum(local_positive)
    remote_damage = sum(remote_positive)
    if local_damage <= 0.0 or remote_damage <= 0.0:
        raise VerifyFailure(
            f"{label}: Lightning did not damage the authority in both origins: "
            f"local={local_damage:.9f} remote={remote_damage:.9f}"
        )

    local_damage_tick_count = round(local_damage / LIGHTNING_DAMAGE_TICK)
    remote_damage_tick_count = round(remote_damage / LIGHTNING_DAMAGE_TICK)
    count_delta = abs(local_damage_tick_count - remote_damage_tick_count)
    damage_delta = abs(local_damage - remote_damage)
    damage_tolerance = max(
        LIGHTNING_DAMAGE_TICK * LIGHTNING_DAMAGE_EVENT_COUNT_TOLERANCE,
        max(local_damage, remote_damage) * LIGHTNING_DAMAGE_RELATIVE_TOLERANCE,
    )
    if (
        count_delta > LIGHTNING_DAMAGE_EVENT_COUNT_TOLERANCE
        or damage_delta > damage_tolerance
    ):
        raise VerifyFailure(
            f"{label}: replicated Lightning damage events diverged: "
            f"local_transitions={len(local_positive)} "
            f"remote_transitions={len(remote_positive)} "
            f"local_damage_ticks={local_damage_tick_count} "
            f"remote_damage_ticks={remote_damage_tick_count} "
            f"local_damage={local_damage:.9f} "
            f"remote_damage={remote_damage:.9f} "
            f"count_delta={count_delta} damage_delta={damage_delta:.9f} "
            f"damage_tolerance={damage_tolerance:.9f}"
        )
    return {
        "local_raw_transition_count": len(local_positive),
        "remote_raw_transition_count": len(remote_positive),
        "local_damage_tick_count": local_damage_tick_count,
        "remote_damage_tick_count": remote_damage_tick_count,
        "damage_tick_count_delta": count_delta,
        "local_damage": local_damage,
        "remote_damage": remote_damage,
        "damage_delta": damage_delta,
        "damage_tolerance": damage_tolerance,
    }


def values(pipe_name: str, code: str, timeout: float = 8.0) -> dict[str, str]:
    return parse_key_values(lua(pipe_name, code, timeout=timeout))


def disable_bots_on_pipe(pipe_name: str) -> dict[str, str]:
    deadline = time.monotonic() + 15.0
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = values(
            pipe_name,
            """
lua_bots_disable_tick = true
sd.bots.clear()
print("count=" .. tostring(sd.bots.get_count()))
""",
        )
        if last.get("count") == "0":
            return last
        time.sleep(0.25)
    raise VerifyFailure(f"failed to disable bots on {pipe_name}: {last}")


def reserve_udp_ports(count: int) -> list[int]:
    sockets: list[socket.socket] = []
    ports: list[int] = []
    try:
        for _ in range(count):
            handle = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            handle.bind(("127.0.0.1", 0))
            sockets.append(handle)
            ports.append(int(handle.getsockname()[1]))
    finally:
        for handle in sockets:
            handle.close()
    if len(set(ports)) != count:
        raise VerifyFailure(f"failed to reserve {count} distinct UDP ports: {ports}")
    return ports


def expected_executable(runtime_root: Path, instance: str) -> Path:
    return (
        runtime_root
        / "instances"
        / instance.lower()
        / "stage"
        / "SolomonDark.exe"
    ).resolve()


def normalize_windows_path(value: str) -> str:
    return value.replace("/", "\\").rstrip("\\").casefold()


def query_processes(process_ids: Iterable[int]) -> dict[int, str]:
    exact_ids = sorted({int(value) for value in process_ids if int(value) > 0})
    if not exact_ids:
        return {}
    joined = ",".join(str(value) for value in exact_ids)
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            (
                f"$ids=@({joined}); "
                "$rows=@(Get-CimInstance Win32_Process | "
                "Where-Object { $_.ProcessId -in $ids } | "
                "Select-Object ProcessId,ExecutablePath); "
                "$rows | ConvertTo-Json -Depth 3 -Compress"
            ),
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=15.0,
        check=False,
    )
    if completed.returncode != 0:
        raise VerifyFailure(
            "failed to query owned processes: "
            f"{completed.stderr.strip() or completed.stdout.strip()}"
        )
    raw = completed.stdout.strip()
    if not raw:
        return {}
    document = json.loads(raw)
    rows = document if isinstance(document, list) else [document]
    return {
        int(row["ProcessId"]): str(row["ExecutablePath"])
        for row in rows
        if isinstance(row, dict)
        and row.get("ProcessId") is not None
        and row.get("ExecutablePath")
    }


def validate_owned_processes(expected: dict[int, Path]) -> dict[str, str]:
    actual = query_processes(expected)
    if set(actual) != set(expected):
        raise VerifyFailure(
            f"owned process set mismatch: expected={sorted(expected)} "
            f"actual={sorted(actual)}"
        )
    for process_id, expected_path in expected.items():
        expected_windows_path = path_for_powershell(expected_path)
        if normalize_windows_path(actual[process_id]) != normalize_windows_path(
            expected_windows_path
        ):
            raise VerifyFailure(
                f"PID {process_id} path mismatch: expected={expected_windows_path} "
                f"actual={actual[process_id]}"
            )
    return {str(process_id): str(path) for process_id, path in sorted(actual.items())}


def activate_owned_game_window(
    process_id: int,
    expected_processes: dict[int, Path],
) -> dict[str, Any]:
    if process_id not in expected_processes:
        raise VerifyFailure(
            f"refusing to activate unowned PID {process_id}: "
            f"owned={sorted(expected_processes)}"
        )
    before = validate_owned_processes(expected_processes)
    completed = subprocess.run(
        [
            "py.exe",
            "-3",
            path_for_powershell(ROOT / "scripts" / "activate_window.py"),
            "--pid",
            str(process_id),
            "--delay-ms",
            "500",
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10.0,
        check=False,
    )
    if completed.returncode != 0:
        raise VerifyFailure(
            f"failed to activate owned PID {process_id}: "
            f"{completed.stderr.strip() or completed.stdout.strip()}"
        )
    after = validate_owned_processes(expected_processes)
    return {
        "process_id": process_id,
        "before": before[str(process_id)],
        "after": after[str(process_id)],
        "activation": completed.stdout.strip(),
    }


def stop_owned_processes(expected: dict[int, Path]) -> dict[str, str]:
    actual = query_processes(expected)
    for process_id, actual_path in actual.items():
        expected_path = expected.get(process_id)
        if expected_path is None:
            raise VerifyFailure(
                f"refusing to stop unowned PID {process_id}: {actual_path}"
            )
        expected_windows_path = path_for_powershell(expected_path)
        if normalize_windows_path(actual_path) != normalize_windows_path(
            expected_windows_path
        ):
            raise VerifyFailure(
                f"refusing to stop PID {process_id} after path changed: "
                f"expected={expected_windows_path} actual={actual_path}"
            )
    if actual:
        stop_game_processes(tuple(sorted(actual)))
    remaining = query_processes(actual)
    if remaining:
        raise VerifyFailure(f"owned processes remained after cleanup: {remaining}")
    return {
        str(process_id): path
        for process_id, path in sorted(actual.items())
    }


def audio_session_samples(
    expected_processes: dict[int, Path],
    *,
    sample_count: int = 6,
    interval_ms: int = 250,
) -> dict[str, Any]:
    validate_owned_processes(expected_processes)
    joined = ",".join(str(value) for value in sorted(expected_processes))
    command = (
        f"& .\\scripts\\Get-ProcessAudioSession.ps1 "
        f"-ProcessId @({joined}) -SampleCount {sample_count} "
        f"-IntervalMilliseconds {interval_ms}"
    )
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30.0,
        check=False,
    )
    if completed.returncode != 0:
        raise VerifyFailure(
            "audio-session probe failed: "
            f"{completed.stderr.strip() or completed.stdout.strip()}"
        )
    document = json.loads(completed.stdout)
    active_by_pid = {process_id: 0 for process_id in expected_processes}
    for sample in document.get("samples", []):
        for process in sample.get("processes", []):
            process_id = int(process.get("processId", 0))
            expected_path = expected_processes.get(process_id)
            if expected_path is None:
                continue
            process_path = process.get("processPath")
            if not process.get("processExists") or not process_path:
                raise VerifyFailure(
                    f"audio probe lost owned PID {process_id}: {process}"
                )
            if normalize_windows_path(str(process_path)) != normalize_windows_path(
                path_for_powershell(expected_path)
            ):
                raise VerifyFailure(
                    f"audio probe path mismatch for PID {process_id}: {process_path}"
                )
            sessions = process.get("sessions", [])
            active_by_pid[process_id] += sum(
                1 for session in sessions if session.get("State") == "Active"
            )
    inactive = [
        process_id for process_id, active_count in active_by_pid.items()
        if active_count == 0
    ]
    if inactive:
        raise VerifyFailure(
            f"audio-enabled processes never exposed an active audio session: {inactive}"
        )
    return {
        "active_samples_by_pid": {
            str(process_id): count
            for process_id, count in sorted(active_by_pid.items())
        },
        "probe": document,
    }


def wait_for_remote_actor(
    observer_pipe: str,
    participant_id: int,
    *,
    timeout: float = 20.0,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = values(
            observer_pipe,
            f"""
local function emit(k, v) print(k .. "=" .. tostring(v)) end
local state = sd.bots and sd.bots.get_participant_state and
  sd.bots.get_participant_state({participant_id}) or nil
emit("available", state ~= nil)
emit("actor", state and state.actor_address or 0)
emit("scene_kind", state and state.scene and state.scene.kind or "")
emit("cast_active", state and state.cast_active or false)
""",
        )
        if (
            last.get("available") == "true"
            and int(last.get("actor", "0"), 0) != 0
            and last.get("scene_kind") == "Run"
        ):
            return last
        time.sleep(0.2)
    raise VerifyFailure(
        f"remote participant {participant_id} did not materialize: {last}"
    )


def start_testrun_when_ready(
    pipe_name: str,
    *,
    timeout: float = 30.0,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        try:
            result = values(
                pipe_name,
                "print('ok=' .. tostring(sd.hub.start_testrun()))",
            )
            if result.get("ok") == "true":
                return result
            last_error = str(result)
        except VerifyFailure as exc:
            last_error = str(exc)
        time.sleep(0.25)
    raise VerifyFailure(
        f"testrun request never reached stable scene identity: {last_error}"
    )


def enter_pair_run(host_pipe: str, client_pipe: str) -> dict[str, Any]:
    start = start_testrun_when_ready(host_pipe)
    wait_for_scene(host_pipe, "testrun", timeout=30.0)
    wait_for_scene(client_pipe, "testrun", timeout=30.0)
    wait_for_remote_actor(host_pipe, CLIENT_ID)
    wait_for_remote_actor(client_pipe, HOST_ID)
    combat = values(
        host_pipe,
        "print('ok=' .. tostring(sd.gameplay.start_waves()))",
    )
    if combat.get("ok") != "true":
        raise VerifyFailure(f"host failed to start waves: {combat}")
    return {"start": start, "combat": combat}


def enter_solo_run(pipe_name: str) -> dict[str, str]:
    start = start_testrun_when_ready(pipe_name)
    wait_for_scene(pipe_name, "testrun", timeout=30.0)
    combat = values(
        pipe_name,
        "print('ok=' .. tostring(sd.gameplay.start_waves()))",
    )
    if combat.get("ok") != "true":
        raise VerifyFailure(f"solo failed to start waves: {combat}")
    return {"start": start.get("ok", ""), "combat": combat.get("ok", "")}


def set_player_mana(pipe_name: str, value: float = 5000.0) -> dict[str, str]:
    result = values(
        pipe_name,
        f"""
local function emit(k, v) print(k .. "=" .. tostring(v)) end
local player = sd.player.get_state()
local actor = player and tonumber(player.actor_address) or 0
local progression = player and tonumber(player.progression_address) or 0
if progression == 0 and actor ~= 0 then
  progression = tonumber(sd.debug.read_ptr(
    actor + sd.debug.layout_offset("actor_progression_runtime_state"))) or 0
end
emit("actor", actor)
emit("progression", progression)
emit("max_mp", progression ~= 0 and sd.debug.write_float(
  progression + sd.debug.layout_offset("progression_max_mp"), {value}) or false)
emit("mp", progression ~= 0 and sd.debug.write_float(
  progression + sd.debug.layout_offset("progression_mp"), {value}) or false)
""",
    )
    if (
        int(result.get("actor", "0"), 0) == 0
        or int(result.get("progression", "0"), 0) == 0
        or result.get("max_mp") != "true"
        or result.get("mp") != "true"
    ):
        raise VerifyFailure(f"failed to set player mana on {pipe_name}: {result}")
    return result


def enable_lightning_target_pin_mode(pipe_name: str) -> dict[str, str]:
    result = values(
        pipe_name,
        """
local ok, active = sd.gameplay.set_manual_enemy_spawner_test_mode(true)
print("ok=" .. tostring(ok))
print("active=" .. tostring(active))
""",
    )
    if result.get("ok") != "true" or result.get("active") != "true":
        raise VerifyFailure(
            f"failed to enable controlled Lightning target pin mode: {result}"
        )
    return result


def wait_for_lightning_target(
    host_pipe: str,
    *,
    excluded_network_actor_id: int = 0,
    timeout: float = 20.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = values(
            host_pipe,
            SELECT_LIGHTNING_TARGET_LUA.replace(
                "__EXCLUDED_ID__",
                str(excluded_network_actor_id),
            ),
        )
        if (
            last.get("ok") == "true"
            and int(last.get("network_actor_id", "0"), 0) != 0
        ):
            return {
                "network_actor_id": int(last["network_actor_id"], 0),
                "x": float(last["x"]),
                "y": float(last["y"]),
                "hp": float(last["hp"]),
                "max_hp": float(last["max_hp"]),
            }
        time.sleep(0.1)
    raise VerifyFailure(f"stock wave exposed no Lightning target: {last}")


def wait_for_bound_lightning_target(
    pipe_name: str,
    network_actor_id: int,
    *,
    timeout: float = 15.0,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = values(
            pipe_name,
            f"""
local target = sd.world.get_run_enemy_by_network_id and
  sd.world.get_run_enemy_by_network_id({network_actor_id}) or nil
print("found=" .. tostring(target ~= nil))
print("actor_address=" .. string.format(
  "0x%08X", tonumber(target and target.actor_address) or 0))
""",
        )
        if (
            last.get("found") == "true"
            and int(last.get("actor_address", "0"), 0) != 0
        ):
            return last
        time.sleep(0.1)
    raise VerifyFailure(
        f"Lightning target {network_actor_id} did not bind on {pipe_name}: {last}"
    )


def wait_for_shared_lightning_target(
    host_pipe: str,
    client_pipe: str,
    *,
    excluded_network_actor_id: int = 0,
    timeout: float = 20.0,
) -> tuple[dict[str, Any], dict[str, dict[str, str]]]:
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        try:
            target = wait_for_lightning_target(
                host_pipe,
                excluded_network_actor_id=excluded_network_actor_id,
                timeout=1.0,
            )
            network_actor_id = int(target["network_actor_id"])
            bindings = {
                "host": wait_for_bound_lightning_target(
                    host_pipe,
                    network_actor_id,
                    timeout=0.5,
                ),
                "client": wait_for_bound_lightning_target(
                    client_pipe,
                    network_actor_id,
                    timeout=0.5,
                ),
            }
            time.sleep(0.2)
            for pipe_name in (host_pipe, client_pipe):
                wait_for_bound_lightning_target(
                    pipe_name,
                    network_actor_id,
                    timeout=0.5,
                )
            return target, bindings
        except VerifyFailure as exc:
            last_error = str(exc)
            time.sleep(0.1)
    raise VerifyFailure(
        "stock wave exposed no stable shared Lightning target: "
        f"{last_error}"
    )


def arm_lightning_damage_monitor(
    host_pipe: str,
    target: dict[str, Any],
) -> dict[str, str]:
    result = values(
        host_pipe,
        ARM_LIGHTNING_DAMAGE_MONITOR_LUA
        .replace("__TARGET_ID__", str(target["network_actor_id"]))
        .replace("__TARGET_X__", f"{target['x']:.9f}")
        .replace("__TARGET_Y__", f"{target['y']:.9f}")
        .replace("__TARGET_HP__", f"{LIGHTNING_TARGET_HP:.9f}"),
    )
    if (
        result.get("armed") != "true"
        or abs(float(result.get("initial_hp", "nan")) - LIGHTNING_TARGET_HP)
        > 1e-5
    ):
        raise VerifyFailure(f"failed to arm Lightning HP monitor: {result}")
    return result


def arm_lightning_target_refresh(
    source_pipe: str,
    target: dict[str, Any],
) -> dict[str, str]:
    result = values(
        source_pipe,
        ARM_LIGHTNING_TARGET_REFRESH_LUA
        .replace("__TARGET_ID__", str(target["network_actor_id"]))
        .replace("__TARGET_X__", f"{target['x']:.9f}")
        .replace("__TARGET_Y__", f"{target['y']:.9f}"),
    )
    if result.get("armed") != "true":
        raise VerifyFailure(f"failed to arm Lightning target refresh: {result}")
    return result


def wait_for_local_cast_release(
    pipe_name: str,
    *,
    timeout: float = 12.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    saw_down = False
    first_down_monotonic: float | None = None
    samples = 0
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        samples += 1
        last = values(
            pipe_name,
            """
local input = sd.input.get_mouse_left_state()
print("down=" .. tostring(input and input.down or false))
print("edge_serial=" .. tostring(input and input.edge_serial or 0))
print("edge_tick_ms=" .. tostring(input and input.edge_tick_ms or 0))
""",
        )
        down = last.get("down") == "true"
        if down and not saw_down:
            saw_down = True
            first_down_monotonic = time.monotonic()
        if saw_down and not down:
            return {
                "samples": samples,
                "first_down_monotonic": first_down_monotonic,
                "release_monotonic": time.monotonic(),
                "last": last,
            }
        time.sleep(0.02)
    raise VerifyFailure(
        f"fixed-window Lightning input did not release: "
        f"saw_down={saw_down} last={last}"
    )


def read_lightning_target_raw_hp(
    pipe_name: str,
    network_actor_id: int,
) -> float:
    result = values(
        pipe_name,
        f"""
local target = sd.world.get_run_enemy_by_network_id and
  sd.world.get_run_enemy_by_network_id({network_actor_id}) or nil
local address = tonumber(target and target.actor_address) or 0
local hp_offset = sd.debug.layout_offset("enemy_current_hp")
print("found=" .. tostring(address ~= 0 and hp_offset ~= nil))
print("raw_hp=" .. tostring(
  address ~= 0 and hp_offset ~= nil and
  sd.debug.read_float(address + hp_offset) or "nan"))
""",
    )
    raw_hp = float(result.get("raw_hp", "nan"))
    if result.get("found") != "true" or not raw_hp == raw_hp:
        raise VerifyFailure(
            f"Lightning raw target HP unavailable on {pipe_name}: {result}"
        )
    return raw_hp


def wait_for_lightning_health_convergence(
    pipe_names: Iterable[str],
    network_actor_id: int,
    *,
    expected_hp: float | None,
    stable_samples_required: int = 5,
    timeout: float = 8.0,
) -> dict[str, Any]:
    unique_pipes = tuple(dict.fromkeys(pipe_names))
    deadline = time.monotonic() + timeout
    stable_samples = 0
    previous: dict[str, float] | None = None
    last: dict[str, float] = {}
    while time.monotonic() < deadline:
        try:
            last = {
                pipe_name: read_lightning_target_raw_hp(
                    pipe_name,
                    network_actor_id,
                )
                for pipe_name in unique_pipes
            }
        except VerifyFailure:
            stable_samples = 0
            previous = None
            time.sleep(0.1)
            continue
        values_now = tuple(last.values())
        peer_converged = max(values_now) - min(values_now) <= 0.001
        expected_converged = (
            expected_hp is None
            or all(abs(value - expected_hp) <= 0.001 for value in values_now)
        )
        unchanged = (
            previous is not None
            and all(
                abs(last[pipe_name] - previous[pipe_name]) <= 0.000001
                for pipe_name in unique_pipes
            )
        )
        if peer_converged and expected_converged and unchanged:
            stable_samples += 1
            if stable_samples >= stable_samples_required:
                return {
                    "network_actor_id": network_actor_id,
                    "expected_hp": expected_hp,
                    "stable_samples": stable_samples,
                    "raw_hp_by_pipe": last,
                }
        else:
            stable_samples = 0
        previous = last
        time.sleep(0.1)
    raise VerifyFailure(
        "Lightning target HP did not converge: "
        f"target={network_actor_id} expected={expected_hp} last={last}"
    )


def wait_for_remote_cast_idle(
    observer_pipe: str,
    participant_id: int,
    *,
    timeout: float = 8.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    stable_samples = 0
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = values(
            observer_pipe,
            f"""
local state = sd.bots.get_participant_state({participant_id})
print("found=" .. tostring(state ~= nil))
print("cast_active=" .. tostring(state and state.cast_active or false))
print("cast_pending=" .. tostring(state and state.cast_pending or false))
""",
        )
        if (
            last.get("found") == "true"
            and last.get("cast_active") == "false"
            and last.get("cast_pending") == "false"
        ):
            stable_samples += 1
            if stable_samples >= 5:
                return {
                    "stable_samples": stable_samples,
                    "last": last,
                }
        else:
            stable_samples = 0
        time.sleep(0.1)
    raise VerifyFailure(
        f"remote Lightning cast did not settle for {participant_id}: {last}"
    )


def collect_lightning_damage_events(host_pipe: str) -> dict[str, Any]:
    text = lua(host_pipe, COLLECT_LIGHTNING_DAMAGE_MONITOR_LUA, timeout=8.0)
    metadata: dict[str, Any] | None = None
    events: list[dict[str, Any]] = []
    for line in text.splitlines():
        fields = line.strip().split("|")
        if fields[0] == "META" and len(fields) == 7:
            metadata = {
                "network_actor_id": int(fields[1], 0),
                "initial_hp": float(fields[2]),
                "last_hp": float(fields[3]),
                "event_count": int(fields[4], 0),
                "missing_samples": int(fields[5], 0),
                "read_errors": int(fields[6], 0),
            }
        elif fields[0] == "D" and len(fields) == 8:
            events.append(
                {
                    "index": int(fields[1], 0),
                    "monotonic_ms": int(fields[2], 0),
                    "tick": int(fields[3], 0),
                    "actor_address": fields[4],
                    "before_hp": float(fields[5]),
                    "after_hp": float(fields[6]),
                    "delta": float(fields[7]),
                }
            )
    if metadata is None or metadata["event_count"] != len(events):
        raise VerifyFailure(
            f"invalid Lightning damage monitor payload: metadata={metadata} "
            f"events={len(events)} raw={text[-1000:]}"
        )
    if metadata["missing_samples"] != 0 or metadata["read_errors"] != 0:
        raise VerifyFailure(f"Lightning raw HP monitor lost integrity: {metadata}")
    metadata["events"] = events
    return metadata


def run_lightning_damage_direction(
    *,
    label: str,
    source_pipe: str,
    host_pipe: str,
    other_pipe: str,
    target: dict[str, Any],
    hold_frames: int,
    source_participant_id: int,
    source_process_id: int,
    expected_processes: dict[int, Path],
) -> dict[str, Any]:
    clear_cast_state(source_pipe)
    clear_cast_state(other_pipe)
    arm = arm_lightning_damage_monitor(host_pipe, target)
    baseline_convergence = wait_for_lightning_health_convergence(
        (host_pipe, source_pipe, other_pipe),
        int(target["network_actor_id"]),
        expected_hp=LIGHTNING_TARGET_HP,
    )
    refresh = arm_lightning_target_refresh(source_pipe, target)
    try:
        source_window = activate_owned_game_window(
            source_process_id,
            expected_processes,
        )
        queued = values(
            source_pipe,
            f"""
local target = sd.world.get_run_enemy_by_network_id and
  sd.world.get_run_enemy_by_network_id({int(target["network_actor_id"])}) or nil
local target_actor = tonumber(target and target.actor_address) or 0
local held = sd.input.hold_mouse_left_frames({hold_frames})
local pin_ok, pin_result = pcall(
  sd.input.pin_manual_primary_target, target_actor)
print("held=" .. tostring(held))
print("target_actor=" .. string.format("0x%08X", target_actor))
print("pinned=" .. tostring(pin_ok and pin_result == true))
""",
        )
        if (
            queued.get("held") != "true"
            or queued.get("pinned") != "true"
            or int(queued.get("target_actor", "0"), 0) == 0
        ):
            raise VerifyFailure(f"{label}: failed to queue Lightning: {queued}")
        input_window = wait_for_local_cast_release(source_pipe)
        observer_idle = wait_for_remote_cast_idle(
            other_pipe,
            source_participant_id,
        )
        final_convergence = wait_for_lightning_health_convergence(
            (host_pipe, source_pipe, other_pipe),
            int(target["network_actor_id"]),
            expected_hp=None,
            stable_samples_required=15,
        )
        damage = collect_lightning_damage_events(host_pipe)
    finally:
        refresh_stopped = values(
            source_pipe,
            STOP_LIGHTNING_TARGET_REFRESH_LUA,
        )
        clear_cast_state(source_pipe)
    positive_events = [
        event
        for event in damage["events"]
        if event["delta"] > 0.0
    ]
    return {
        "label": label,
        "hold_frames": hold_frames,
        "monitor_arm": arm,
        "baseline_convergence": baseline_convergence,
        "target_refresh_arm": refresh,
        "target_refresh_stop": refresh_stopped,
        "source_window": source_window,
        "queued": queued,
        "input_window": input_window,
        "observer_idle": observer_idle,
        "final_convergence": final_convergence,
        "authority_hp": damage,
        "positive_damage_events": positive_events,
        "positive_damage": sum(
            event["delta"] for event in positive_events
        ),
    }


def run_lightning_damage_parity(
    *,
    host_pipe: str,
    client_pipe: str,
    host_process_id: int,
    client_process_id: int,
    expected_processes: dict[int, Path],
    hold_frames: int = LIGHTNING_HOLD_FRAMES,
) -> dict[str, Any]:
    local_target, local_bindings = wait_for_shared_lightning_target(
        host_pipe,
        client_pipe,
    )
    remote_target, remote_bindings = wait_for_shared_lightning_target(
        host_pipe,
        client_pipe,
        excluded_network_actor_id=int(local_target["network_actor_id"]),
    )
    target_pin_mode = {
        "host": enable_lightning_target_pin_mode(host_pipe),
        "client": enable_lightning_target_pin_mode(client_pipe),
    }
    local = run_lightning_damage_direction(
        label="host_local",
        source_pipe=host_pipe,
        host_pipe=host_pipe,
        other_pipe=client_pipe,
        target=local_target,
        hold_frames=hold_frames,
        source_participant_id=HOST_ID,
        source_process_id=host_process_id,
        expected_processes=expected_processes,
    )
    remote = run_lightning_damage_direction(
        label="client_remote_authority",
        source_pipe=client_pipe,
        host_pipe=host_pipe,
        other_pipe=host_pipe,
        target=remote_target,
        hold_frames=hold_frames,
        source_participant_id=CLIENT_ID,
        source_process_id=client_process_id,
        expected_processes=expected_processes,
    )
    parity = assert_lightning_damage_event_parity(
        label="client_to_host",
        local_events=[
            event["delta"]
            for event in local["positive_damage_events"]
        ],
        remote_events=[
            event["delta"]
            for event in remote["positive_damage_events"]
        ],
    )
    return {
        "target_pin_mode": target_pin_mode,
        "targets": {
            "local": local_target,
            "remote": remote_target,
        },
        "bindings": {
            "local": local_bindings,
            "remote": remote_bindings,
        },
        "local": local,
        "remote": remote,
        "parity": parity,
    }


def clear_cast_state(pipe_name: str) -> dict[str, str]:
    result = values(
        pipe_name,
        "print('cleared=' .. tostring(sd.input.clear_local_cast_state()))",
    )
    if result.get("cleared") != "true":
        raise VerifyFailure(f"failed to clear local cast state on {pipe_name}: {result}")
    return result


def queue_earth_cast(pipe_name: str, hold_frames: int) -> dict[str, str]:
    result = values(
        pipe_name,
        f"""
local function emit(k, v) print(k .. "=" .. tostring(v)) end
local player = sd.player.get_state()
local actor = player and tonumber(player.actor_address) or 0
if actor == 0 then error("player actor unavailable") end
local x = sd.debug.read_float(
  actor + sd.debug.layout_offset("actor_position_x"))
local y = sd.debug.read_float(
  actor + sd.debug.layout_offset("actor_position_y"))
emit("heading", sd.debug.write_float(
  actor + sd.debug.layout_offset("actor_heading"), 90.0))
emit("aim_x", sd.debug.write_float(
  actor + sd.debug.layout_offset("actor_aim_target_x"), x + 320.0))
emit("aim_y", sd.debug.write_float(
  actor + sd.debug.layout_offset("actor_aim_target_y"), y))
emit("aux0", sd.debug.write_u32(
  actor + sd.debug.layout_offset("actor_aim_target_aux0"), 0))
emit("aux1", sd.debug.write_u32(
  actor + sd.debug.layout_offset("actor_aim_target_aux1"), 0))
emit("held", sd.input.hold_mouse_left_frames({hold_frames}))
""",
    )
    if any(
        result.get(key) != "true"
        for key in ("heading", "aim_x", "aim_y", "aux0", "aux1", "held")
    ):
        raise VerifyFailure(f"failed to queue Earth cast on {pipe_name}: {result}")
    return result


def trace_name(case_name: str, point_name: str) -> str:
    return f"replicated_audio.{case_name}.{point_name}"


def arm_traces(pipe_name: str, case_name: str) -> dict[str, str]:
    last_result: dict[str, str] = {}
    last_failed: list[str] = []
    for attempt in range(1, 4):
        lines: list[str] = []
        for address, point_name, patch_size in TRACE_POINTS:
            name = trace_name(case_name, point_name)
            lines.extend(
                (
                    f"pcall(sd.debug.untrace_function, {address})",
                    f"pcall(sd.debug.clear_trace_hits, {json.dumps(name)})",
                )
            )
            call = (
                f"sd.debug.trace_function({address}, {json.dumps(name)}, {patch_size})"
                if patch_size
                else f"sd.debug.trace_function({address}, {json.dumps(name)})"
            )
            lines.append(
                f"print({json.dumps('arm.' + point_name + '=')} .. tostring({call}))"
            )
        last_result = values(pipe_name, "\n".join(lines))
        last_failed = [
            point_name for _, point_name, _ in TRACE_POINTS
            if last_result.get(f"arm.{point_name}") != "true"
        ]
        if not last_failed:
            last_result["arm.attempt"] = str(attempt)
            return last_result
        disarm_traces(pipe_name)
        time.sleep(0.15)
    raise VerifyFailure(
        f"failed to arm audio traces on {pipe_name}: {last_failed}; {last_result}"
    )


def disarm_traces(pipe_name: str) -> None:
    code = "\n".join(
        f"pcall(sd.debug.untrace_function, {address})"
        for address, _, _ in TRACE_POINTS
    )
    try:
        lua(pipe_name, code, timeout=8.0)
    except Exception:
        pass


def sample_traces(pipe_name: str, case_name: str) -> dict[str, int]:
    names = {
        point_name: trace_name(case_name, point_name)
        for _, point_name, _ in TRACE_POINTS
    }
    raw = values(
        pipe_name,
        f"""
local function emit(k, v) print(k .. "=" .. tostring(v)) end
local registry_slot = sd.debug.resolve_game_address(0x008199D8)
local registry = registry_slot and tonumber(sd.debug.read_ptr(registry_slot)) or 0
local gather = registry + 0x176C
local rolling = registry + 0x1ACC
local startboulder = registry + 0x0F0C
local rockhit = registry + 0x0D54
local gather_start_return = sd.debug.resolve_game_address(0x00549F5C)
local gather_transition_stop_return = sd.debug.resolve_game_address(0x0054975D)
local gather_charge_stop_return = sd.debug.resolve_game_address(0x0054AD17)
local bass_loop_start_return = sd.debug.resolve_game_address(0x00408343)
local startboulder_return = sd.debug.resolve_game_address(0x00544FAD)
local rockhit_return = sd.debug.resolve_game_address(0x00621420)
local play = sd.debug.get_trace_hits({json.dumps(names["sound_play_ex"])}) or {{}}
local starts = sd.debug.get_trace_hits({json.dumps(names["sound_loop_start"])}) or {{}}
local stops = sd.debug.get_trace_hits({json.dumps(names["sound_loop_stop"])}) or {{}}
local bass = sd.debug.get_trace_hits({json.dumps(names["bass_channel_play"])}) or {{}}
local boulders = sd.debug.get_trace_hits({json.dumps(names["earth_boulder_ctor"])}) or {{}}
local startboulder_count = 0
local rockhit_count = 0
for _, hit in ipairs(play) do
  if hit.ecx == startboulder and hit.ret == startboulder_return then
    startboulder_count = startboulder_count + 1
  end
  if hit.ecx == rockhit and hit.ret == rockhit_return then
    rockhit_count = rockhit_count + 1
  end
end
local gather_start_count = 0
local rolling_start_count = 0
for _, hit in ipairs(starts) do
  if hit.ecx == gather and hit.ret == gather_start_return then
    gather_start_count = gather_start_count + 1
  end
  if hit.ecx == rolling then
    rolling_start_count = rolling_start_count + 1
  end
end
local gather_stop_count = 0
for _, hit in ipairs(stops) do
  if hit.ecx == gather and
      (hit.ret == gather_transition_stop_return or
       hit.ret == gather_charge_stop_return) then
    gather_stop_count = gather_stop_count + 1
  end
end
local gather_bass_count = 0
for _, hit in ipairs(bass) do
  if hit.ecx == gather and hit.ret == bass_loop_start_return then
    gather_bass_count = gather_bass_count + 1
  end
end
emit("registry", registry)
emit("boulder_ctor", #boulders)
emit("startboulder_one_shot", startboulder_count)
emit("gather_loop_start", gather_start_count)
emit("gather_loop_stop", gather_stop_count)
emit("gather_bass_channel_play", gather_bass_count)
emit("rolling_loop_start", rolling_start_count)
emit("rockhit_one_shot", rockhit_count)
sd.debug.clear_trace_hits({json.dumps(names["sound_play_ex"])})
sd.debug.clear_trace_hits({json.dumps(names["sound_loop_start"])})
sd.debug.clear_trace_hits({json.dumps(names["sound_loop_stop"])})
sd.debug.clear_trace_hits({json.dumps(names["bass_channel_play"])})
sd.debug.clear_trace_hits({json.dumps(names["earth_boulder_ctor"])})
""",
    )
    if int(raw.get("registry", "0"), 0) == 0:
        raise VerifyFailure(f"audio registry unavailable on {pipe_name}: {raw}")
    return {
        key: int(raw.get(key, "0"), 0)
        for key in TRIGGER_COUNT_KEYS
    }


def add_trigger_counts(
    total: dict[str, int],
    sample: dict[str, int],
) -> None:
    for key in TRIGGER_COUNT_KEYS:
        total[key] = total.get(key, 0) + sample.get(key, 0)


def gather_loop_state(pipe_name: str) -> dict[str, int]:
    raw = values(
        pipe_name,
        """
local function emit(k, v) print(k .. "=" .. tostring(v)) end
local registry_slot = sd.debug.resolve_game_address(0x008199D8)
local registry = registry_slot and tonumber(sd.debug.read_ptr(registry_slot)) or 0
local gather = registry + 0x176C
emit("registry", registry)
emit("refcount", registry ~= 0 and sd.debug.read_u32(gather + 0x4C) or 0)
""",
    )
    return {
        "registry": int(raw.get("registry", "0"), 0),
        "refcount": int(raw.get("refcount", "0"), 0),
    }


def collect_cast_traces_until_idle(
    source_pipe: str,
    *,
    source_case_name: str,
    observer_pipe: str | None = None,
    observer_case_name: str | None = None,
    participant_id: int | None = None,
    timeout: float = 12.0,
) -> tuple[dict[str, int], dict[str, int] | None, dict[str, str]]:
    deadline = time.monotonic() + timeout
    source_counts = {key: 0 for key in TRIGGER_COUNT_KEYS}
    observer_counts = (
        {key: 0 for key in TRIGGER_COUNT_KEYS}
        if observer_pipe is not None
        else None
    )
    idle_since: float | None = None
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        add_trigger_counts(
            source_counts,
            sample_traces(source_pipe, source_case_name),
        )
        if observer_pipe is not None:
            if observer_case_name is None or observer_counts is None:
                raise VerifyFailure("observer trace name is required")
            add_trigger_counts(
                observer_counts,
                sample_traces(observer_pipe, observer_case_name),
            )
        source = values(
            source_pipe,
            """
local function emit(k, v) print(k .. "=" .. tostring(v)) end
local input = sd.input.get_mouse_left_state()
emit("input_down", input and input.down or false)
""",
        )
        remote_active = "false"
        if observer_pipe is not None and participant_id is not None:
            observer = values(
                observer_pipe,
                f"""
local state = sd.bots.get_participant_state({participant_id})
print("cast_active=" .. tostring(state and state.cast_active or false))
""",
            )
            remote_active = observer.get("cast_active", "false")
        last = {
            "input_down": source.get("input_down", ""),
            "remote_active": remote_active,
        }
        if last["input_down"] == "false" and remote_active == "false":
            if idle_since is None:
                idle_since = time.monotonic()
            elif time.monotonic() - idle_since >= 0.5:
                add_trigger_counts(
                    source_counts,
                    sample_traces(source_pipe, source_case_name),
                )
                if observer_pipe is not None:
                    assert observer_case_name is not None
                    assert observer_counts is not None
                    add_trigger_counts(
                        observer_counts,
                        sample_traces(observer_pipe, observer_case_name),
                    )
                return source_counts, observer_counts, last
        else:
            idle_since = None
        time.sleep(0.08)
    raise VerifyFailure(f"Earth cast did not settle: {last}")


def assert_trigger_contract(
    *,
    label: str,
    local_counts: dict[str, int],
    remote_counts: dict[str, int] | None = None,
) -> None:
    required_counts = {
        "boulder_ctor": 1,
        "startboulder_one_shot": 1,
        "gather_loop_start": 1,
        # Stock first calls Stop while selecting Earth at refcount zero, then
        # calls it once more for the real release transition.
        "gather_loop_stop": 2,
        "gather_bass_channel_play": 1,
    }
    bad_local = {
        key: {
            "expected": expected_count,
            "actual": local_counts.get(key),
        }
        for key, expected_count in required_counts.items()
        if local_counts.get(key) != expected_count
    }
    if bad_local:
        raise VerifyFailure(
            f"{label}: local Earth lifecycle was not one-shot/event-faithful: "
            f"{bad_local}; all={local_counts}"
        )
    if remote_counts is None:
        return
    mismatched = {
        key: {
            "local": local_counts.get(key),
            "remote": remote_counts.get(key),
        }
        for key in TRIGGER_COUNT_KEYS
        if local_counts.get(key) != remote_counts.get(key)
    }
    if mismatched:
        raise VerifyFailure(
            f"{label}: replicated Earth audio diverged from the local cast: "
            f"{mismatched}"
        )


def run_pair_direction(
    *,
    case_name: str,
    source_pipe: str,
    observer_pipe: str,
    source_participant_id: int,
    expected_processes: dict[int, Path],
    hold_frames: int,
) -> dict[str, Any]:
    for pipe_name in (source_pipe, observer_pipe):
        clear_cast_state(pipe_name)
    time.sleep(0.35)
    source_arm = arm_traces(source_pipe, f"{case_name}.source")
    observer_arm = arm_traces(observer_pipe, f"{case_name}.observer")
    try:
        audio = audio_session_samples(expected_processes)
        queued = queue_earth_cast(source_pipe, hold_frames)
        source_counts, observer_counts, settled = collect_cast_traces_until_idle(
            source_pipe,
            source_case_name=f"{case_name}.source",
            observer_pipe=observer_pipe,
            observer_case_name=f"{case_name}.observer",
            participant_id=source_participant_id,
        )
    finally:
        disarm_traces(source_pipe)
        disarm_traces(observer_pipe)
    assert observer_counts is not None
    source_loop = gather_loop_state(source_pipe)
    observer_loop = gather_loop_state(observer_pipe)
    if source_loop["refcount"] != 0 or observer_loop["refcount"] != 0:
        raise VerifyFailure(
            f"{case_name}: gather loop remained active after Earth release: "
            f"source={source_loop} observer={observer_loop}; "
            f"source_counts={source_counts} observer_counts={observer_counts}"
        )
    assert_trigger_contract(
        label=case_name,
        local_counts=source_counts,
        remote_counts=observer_counts,
    )
    return {
        "source_arm": source_arm,
        "observer_arm": observer_arm,
        "queued": queued,
        "settled": settled,
        "source_counts": source_counts,
        "observer_counts": observer_counts,
        "source_gather_loop": source_loop,
        "observer_gather_loop": observer_loop,
        "audio_sessions": audio,
    }


def launch_solo(
    *,
    instance: str,
    local_port: int,
    unused_remote_port: int,
    game_directory: Path,
    runtime_root: Path,
) -> dict[str, Any]:
    ledger = runtime_root / f".replicated-audio-solo-{uuid.uuid4().hex}.json"
    runtime_root.mkdir(parents=True, exist_ok=True)
    args = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        "scripts/Launch-LocalSoloSession.ps1",
        "-Instance",
        instance,
        "-Preset",
        EARTH_PRESET,
        "-RuntimeRoot",
        path_for_powershell(runtime_root),
        "-LocalPort",
        str(local_port),
        "-UnusedRemotePort",
        str(unused_remote_port),
        "-ParticipantId",
        f"0x{SOLO_PARTICIPANT_ID:X}",
        "-PlayerName",
        "Audio Solo",
        "-GameDirectory",
        path_for_powershell(game_directory),
        "-ExactModIds",
        ACCEPTANCE_MOD_ID,
        "-EnableAudio",
        "-ProcessIdOutputPath",
        path_for_powershell(ledger),
    ]
    process = subprocess.Popen(
        args,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
    )
    assert process.stdout is not None
    output = ""
    parsed: dict[str, Any] | None = None
    try:
        deadline = time.monotonic() + 100.0
        while time.monotonic() < deadline:
            ready, _, _ = select.select([process.stdout], [], [], 0.1)
            if ready:
                line = process.stdout.readline()
                if line:
                    output += line
                    parsed = extract_json(output)
                    if parsed is not None:
                        return parsed
                elif process.poll() is not None:
                    break
            if process.poll() is not None:
                output += process.stdout.read()
                parsed = extract_json(output)
                if parsed is not None:
                    return parsed
                break
        raise VerifyFailure(f"solo launcher did not return JSON:\n{output}")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                process.kill()
        if parsed is None and ledger.is_file():
            process_ids = game_process_ids(json.loads(ledger.read_text()))
            stop_owned_processes(
                {
                    process_id: expected_executable(runtime_root, instance)
                    for process_id in process_ids
                }
            )
        ledger.unlink(missing_ok=True)


def run_solo_case(
    *,
    instance_prefix: str,
    game_directory: Path,
    runtime_root: Path,
    ports: tuple[int, int],
    hold_frames: int,
    pair_local_reference: dict[str, int],
) -> dict[str, Any]:
    instance = f"{instance_prefix}-solo"
    launch = launch_solo(
        instance=instance,
        local_port=ports[0],
        unused_remote_port=ports[1],
        game_directory=game_directory,
        runtime_root=runtime_root,
    )
    process_ids = game_process_ids(launch)
    if len(process_ids) != 1:
        raise VerifyFailure(f"solo launcher did not report one exact PID: {launch}")
    expected_processes = {
        process_ids[0]: expected_executable(runtime_root, instance)
    }
    result: dict[str, Any] = {
        "launch": launch,
        "owned_processes": validate_owned_processes(expected_processes),
    }
    pipe_name = str(launch.get("luaPipe", ""))
    if not pipe_name or launch.get("audioDisabled") is not False:
        stop_owned_processes(expected_processes)
        raise VerifyFailure(f"solo launch was not explicitly audio-enabled: {launch}")
    try:
        result["run"] = enter_solo_run(pipe_name)
        result["mana"] = set_player_mana(pipe_name)
        clear_cast_state(pipe_name)
        time.sleep(0.35)
        result["arm"] = arm_traces(pipe_name, "solo")
        try:
            result["audio_sessions"] = audio_session_samples(expected_processes)
            result["queued"] = queue_earth_cast(pipe_name, hold_frames)
            counts, _, result["settled"] = collect_cast_traces_until_idle(
                pipe_name,
                source_case_name="solo",
            )
        finally:
            disarm_traces(pipe_name)
        result["counts"] = counts
        result["gather_loop"] = gather_loop_state(pipe_name)
        if result["gather_loop"]["refcount"] != 0:
            raise VerifyFailure(
                "solo gather loop remained active after Earth release: "
                f"{result['gather_loop']}; counts={counts}"
            )
        assert_trigger_contract(label="solo", local_counts=counts)
        mismatch = {
            key: {
                "pair_local": pair_local_reference.get(key),
                "solo": counts.get(key),
            }
            for key in CAST_LIFECYCLE_TRIGGER_KEYS
            if pair_local_reference.get(key) != counts.get(key)
        }
        if mismatch:
            raise VerifyFailure(
                "solo Earth cast-lifecycle audio diverged from multiplayer "
                f"local control: {mismatch}"
            )
        result["matches_pair_local_cast_lifecycle"] = True
        return result
    finally:
        result["cleanup"] = stop_owned_processes(expected_processes)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-directory", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--instance-prefix",
        default=f"audioevt-{os.getpid()}-{uuid.uuid4().hex[:6]}",
    )
    parser.add_argument(
        "--launcher-path",
        type=Path,
        default=ROOT / "dist" / "launcher" / "SolomonDarkModLauncher.exe",
    )
    parser.add_argument("--hold-frames", type=int, default=EARTH_HOLD_FRAMES)
    parser.add_argument(
        "--lightning-hold-frames",
        type=int,
        default=LIGHTNING_HOLD_FRAMES,
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.game_directory.is_dir():
        raise SystemExit(f"game directory does not exist: {args.game_directory}")
    if args.hold_frames < 30:
        raise SystemExit("--hold-frames must be at least 30")
    if args.lightning_hold_frames < 30:
        raise SystemExit("--lightning-hold-frames must be at least 30")
    if not args.launcher_path.is_file():
        raise SystemExit(f"launcher does not exist: {args.launcher_path}")
    if len(args.instance_prefix) > 40:
        raise SystemExit("--instance-prefix must be at most 40 characters")

    runtime_root = args.runtime_root.resolve()
    output = args.output.resolve()
    ports = reserve_udp_ports(6)
    pair_pids: list[int] = []
    expected_pair: dict[int, Path] = {}
    air_pair_pids: list[int] = []
    expected_air_pair: dict[int, Path] = {}
    result: dict[str, Any] = {
        "ok": False,
        "instance_prefix": args.instance_prefix,
        "runtime_root": str(runtime_root),
        "game_directory": str(args.game_directory.resolve()),
        "audio_enabled": True,
        "hold_frames": args.hold_frames,
        "lightning_hold_frames": args.lightning_hold_frames,
        "launcher_path": str(args.launcher_path.resolve()),
    }
    try:
        pair = launch_pair(
            preset=EARTH_PRESET,
            god_mode=True,
            tile_windows=True,
            kill_existing=False,
            instance_prefix=args.instance_prefix,
            host_port=ports[0],
            client_port=ports[1],
            game_directory=args.game_directory.resolve(),
            launcher_path=args.launcher_path.resolve(),
            runtime_root=runtime_root,
            exact_mod_id=ACCEPTANCE_MOD_ID,
            enable_audio=True,
        )
        result["pair_launch"] = pair
        pair_pids = game_process_ids(pair)
        if len(pair_pids) != 2 or pair.get("audioDisabled") is not False:
            raise VerifyFailure(f"pair was not exactly owned and audio-enabled: {pair}")
        host_pipe = str(pair.get("hostLuaPipe", ""))
        client_pipe = str(pair.get("clientLuaPipe", ""))
        if not host_pipe or not client_pipe:
            raise VerifyFailure(f"pair launcher omitted Lua pipes: {pair}")
        expected_pair = {
            int(pair["hostProcessId"]): expected_executable(
                runtime_root, f"{args.instance_prefix}-host"
            ),
            int(pair["clientProcessId"]): expected_executable(
                runtime_root, f"{args.instance_prefix}-client"
            ),
        }
        result["pair_owned_processes"] = validate_owned_processes(expected_pair)
        result["pair_run"] = enter_pair_run(host_pipe, client_pipe)
        result["pair_mana"] = {
            "host": set_player_mana(host_pipe),
            "client": set_player_mana(client_pipe),
        }
        result["host_to_client"] = run_pair_direction(
            case_name="host_to_client",
            source_pipe=host_pipe,
            observer_pipe=client_pipe,
            source_participant_id=HOST_ID,
            expected_processes=expected_pair,
            hold_frames=args.hold_frames,
        )
        result["client_to_host"] = run_pair_direction(
            case_name="client_to_host",
            source_pipe=client_pipe,
            observer_pipe=host_pipe,
            source_participant_id=CLIENT_ID,
            expected_processes=expected_pair,
            hold_frames=args.hold_frames,
        )
        host_reference = result["host_to_client"]["source_counts"]
        client_reference = result["client_to_host"]["source_counts"]
        if host_reference != client_reference:
            raise VerifyFailure(
                "host/client local Earth controls diverged: "
                f"host={host_reference} client={client_reference}"
            )
        result["pair_cleanup"] = stop_owned_processes(expected_pair)
        pair_pids = []

        air_instance_prefix = f"{args.instance_prefix}-air"
        air_pair = launch_pair(
            host_preset=AIR_PRESET,
            client_preset=AIR_PRESET,
            god_mode=True,
            tile_windows=False,
            kill_existing=False,
            instance_prefix=air_instance_prefix,
            host_port=ports[4],
            client_port=ports[5],
            game_directory=args.game_directory.resolve(),
            launcher_path=args.launcher_path.resolve(),
            runtime_root=runtime_root,
            exact_mod_id=ACCEPTANCE_MOD_ID,
            enable_audio=True,
        )
        if air_pair.get("fallbackReady") is True:
            air_pair.setdefault("instancePrefix", air_instance_prefix)
            air_pair.setdefault("runtimeRoot", str(runtime_root))
            air_pair.setdefault("audioDisabled", False)
        result["lightning_pair_launch"] = air_pair
        air_pair_pids = game_process_ids(air_pair)
        if len(air_pair_pids) != 2:
            raise VerifyFailure(
                f"Lightning pair did not return two exact PIDs: {air_pair}"
            )
        expected_air_pair = {
            int(air_pair["hostProcessId"]): expected_executable(
                runtime_root, f"{air_instance_prefix}-host"
            ),
            int(air_pair["clientProcessId"]): expected_executable(
                runtime_root, f"{air_instance_prefix}-client"
            ),
        }
        if air_pair.get("audioDisabled") is not False:
            raise VerifyFailure(
                f"Lightning pair was not audio-enabled: {air_pair}"
            )
        air_host_pipe = str(air_pair.get("hostLuaPipe", ""))
        air_client_pipe = str(air_pair.get("clientLuaPipe", ""))
        if not air_host_pipe or not air_client_pipe:
            raise VerifyFailure(f"Lightning pair omitted Lua pipes: {air_pair}")
        result["lightning_pair_owned_processes"] = validate_owned_processes(
            expected_air_pair
        )
        result["lightning_pair_bots_disabled"] = {
            "host": disable_bots_on_pipe(air_host_pipe),
            "client": disable_bots_on_pipe(air_client_pipe),
        }
        result["lightning_pair_run"] = enter_pair_run(
            air_host_pipe,
            air_client_pipe,
        )
        result["lightning_pair_mana"] = {
            "host": set_player_mana(air_host_pipe),
            "client": set_player_mana(air_client_pipe),
        }
        result["lightning_damage_parity"] = run_lightning_damage_parity(
            host_pipe=air_host_pipe,
            client_pipe=air_client_pipe,
            host_process_id=int(air_pair["hostProcessId"]),
            client_process_id=int(air_pair["clientProcessId"]),
            expected_processes=expected_air_pair,
            hold_frames=args.lightning_hold_frames,
        )
        result["lightning_pair_cleanup"] = stop_owned_processes(
            expected_air_pair
        )
        air_pair_pids = []

        result["solo"] = run_solo_case(
            instance_prefix=args.instance_prefix,
            game_directory=args.game_directory.resolve(),
            runtime_root=runtime_root,
            ports=(ports[2], ports[3]),
            hold_frames=args.hold_frames,
            pair_local_reference=host_reference,
        )
        result["ok"] = True
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        result["error"] = str(exc)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 1
    finally:
        if air_pair_pids and expected_air_pair:
            stop_owned_processes(expected_air_pair)
        if pair_pids and expected_pair:
            stop_owned_processes(expected_pair)


if __name__ == "__main__":
    raise SystemExit(main())
