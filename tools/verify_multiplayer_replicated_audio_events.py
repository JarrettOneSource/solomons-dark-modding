#!/usr/bin/env python3
"""Verify event-faithful Earth audio for local and replicated casts."""

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
SOLO_PARTICIPANT_ID = 0x2000000000001A17

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


def values(pipe_name: str, code: str, timeout: float = 8.0) -> dict[str, str]:
    return parse_key_values(lua(pipe_name, code, timeout=timeout))


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
        ["powershell.exe", "-NoProfile", "-Command", command],
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
    parser.add_argument("--hold-frames", type=int, default=EARTH_HOLD_FRAMES)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.game_directory.is_dir():
        raise SystemExit(f"game directory does not exist: {args.game_directory}")
    if args.hold_frames < 30:
        raise SystemExit("--hold-frames must be at least 30")
    if len(args.instance_prefix) > 40:
        raise SystemExit("--instance-prefix must be at most 40 characters")

    runtime_root = args.runtime_root.resolve()
    output = args.output.resolve()
    ports = reserve_udp_ports(4)
    pair_pids: list[int] = []
    expected_pair: dict[int, Path] = {}
    result: dict[str, Any] = {
        "ok": False,
        "instance_prefix": args.instance_prefix,
        "runtime_root": str(runtime_root),
        "game_directory": str(args.game_directory.resolve()),
        "audio_enabled": True,
        "hold_frames": args.hold_frames,
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
            launcher_path=(ROOT / "dist" / "launcher" / "SolomonDarkModLauncher.exe"),
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
        if pair_pids and expected_pair:
            stop_owned_processes(expected_pair)


if __name__ == "__main__":
    raise SystemExit(main())
