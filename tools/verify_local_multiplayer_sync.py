#!/usr/bin/env python3
"""Live smoke test for local UDP multiplayer participant visibility and movement."""

from __future__ import annotations

import atexit
import base64
import importlib.util
import json
import os
import queue
import re
import select
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Iterable
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
HOST_ID = 0x2000000000001001
CLIENT_ID = 0x2000000000001002
THIRD_ID = 0x2000000000001003
HOST_NAME = "Host Player"
CLIENT_NAME = "Client Player"
THIRD_NAME = "Observer Player"
HOST_PIPE = "SolomonDarkModLoader_LuaExec_local-mp-host"
CLIENT_PIPE = "SolomonDarkModLoader_LuaExec_local-mp-client"
THIRD_PIPE = "SolomonDarkModLoader_LuaExec_local-mp-third"
NATIVE_UI_LUA_TIMEOUT_SECONDS = 35.0
REMOTE_PRIMARY_VISUAL_TYPE_ID = 0x1B5E
REMOTE_SECONDARY_VISUAL_TYPE_ID = 0x1B5D
REMOTE_ATTACHMENT_VISUAL_TYPE_ID = 0x1B5C
REMOTE_RENDER_SELECTION_BY_ELEMENT = {
    0: 1,  # Fire
    1: 3,  # Water
    2: 4,  # Earth
    3: 2,  # Air
    4: 0,  # Ether
}


class VerifyFailure(RuntimeError):
    pass


def run_command(args: list[str], *, env: dict[str, str] | None = None, timeout: float = 30.0) -> str:
    completed = subprocess.run(
        args,
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        raise VerifyFailure(
            f"command failed ({completed.returncode}): {' '.join(args)}\n{completed.stdout}"
        )
    return completed.stdout


def path_for_powershell(path: Path) -> str:
    resolved = path.resolve()
    if os.name == "nt":
        return str(resolved)
    completed = subprocess.run(
        ["wslpath", "-w", str(resolved)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=5.0,
        check=False,
    )
    converted = completed.stdout.strip()
    if completed.returncode != 0 or not converted:
        raise VerifyFailure(f"could not convert path for PowerShell: {resolved}: {completed.stdout}")
    return converted


def stop_games() -> None:
    subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            "Get-Process SolomonDark* -ErrorAction SilentlyContinue | Stop-Process -Force",
        ],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def game_process_ids(result: dict[str, object]) -> list[int]:
    """Return the exact game process IDs reported by a launcher result."""
    process_ids: set[int] = set()
    for key in (
        "hostProcessId",
        "clientProcessId",
        "thirdProcessId",
        "processId",
    ):
        value = result.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            process_id = value
        elif isinstance(value, str) and value.isdigit():
            process_id = int(value)
        else:
            continue
        if process_id > 0:
            process_ids.add(process_id)
    return sorted(process_ids)


def stop_game_processes(process_ids: Iterable[int]) -> None:
    """Stop only the reported Solomon Dark processes, never every game process."""
    exact_process_ids = sorted(
        {
            process_id
            for process_id in process_ids
            if isinstance(process_id, int)
            and not isinstance(process_id, bool)
            and process_id > 0
        }
    )
    if not exact_process_ids:
        return

    joined_process_ids = ",".join(str(process_id) for process_id in exact_process_ids)
    subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            (
                f"$ids = @({joined_process_ids}); "
                "Get-Process -Id $ids -ErrorAction SilentlyContinue | "
                "Where-Object { $_.ProcessName -like 'SolomonDark*' } | "
                "Stop-Process -Force"
            ),
        ],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def _read_process_id_ledger(path: Path | None) -> dict[str, object]:
    if path is None or not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _new_process_id_ledger() -> Path:
    runtime_root = ROOT / "runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    return runtime_root / f".local-mp-processes-{uuid.uuid4().hex}.json"


def extract_json(buffer: str) -> dict[str, object] | None:
    start = buffer.find("{")
    if start < 0:
        return None
    candidate = buffer[start:]
    decoder = json.JSONDecoder()
    try:
        value, _ = decoder.raw_decode(candidate)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict):
        raise VerifyFailure(f"launcher returned non-object JSON: {value!r}")
    return value


def _serialize_exact_mod_ids(
    *,
    exact_mod_id: str | None,
    exact_mod_ids: Iterable[str] | None,
) -> str | None:
    if exact_mod_id is not None and exact_mod_ids is not None:
        raise ValueError(
            "exact_mod_id and exact_mod_ids are mutually exclusive"
        )
    if exact_mod_ids is None:
        if exact_mod_id is None:
            return None
        values = [exact_mod_id]
    else:
        if isinstance(exact_mod_ids, str):
            raise TypeError("exact_mod_ids must be an iterable of mod IDs")
        values = list(exact_mod_ids)
        if not values:
            raise ValueError("exact_mod_ids must not be empty")

    seen: set[str] = set()
    for value in values:
        if (
            not isinstance(value, str)
            or re.fullmatch(r"[a-z0-9][a-z0-9._-]*", value) is None
        ):
            raise ValueError(f"invalid exact mod id: {value!r}")
        if value in seen:
            raise ValueError(f"duplicate exact mod id: {value}")
        seen.add(value)
    return ",".join(values)


def launch_pair(
    preset: str = "map_create_fire_mind_hub",
    *,
    host_preset: str | None = None,
    client_preset: str | None = None,
    temporary_host_profile: bool = True,
    god_mode: bool = False,
    tile_windows: bool = True,
    test_survival_boneyard_override: Path | None = None,
    test_blank_boneyard: bool = False,
    test_wave_override: Path | None = None,
    third_player: bool = False,
    third_preset: str | None = None,
    allow_focus_steal: bool = False,
    kill_existing: bool = True,
    exact_mod_id: str | None = None,
    exact_mod_ids: Iterable[str] | None = None,
) -> dict[str, object]:
    serialized_exact_mod_ids = _serialize_exact_mod_ids(
        exact_mod_id=exact_mod_id,
        exact_mod_ids=exact_mod_ids,
    )
    args = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        "scripts/Launch-LocalMultiplayerPair.ps1",
        "-HostName",
        HOST_NAME,
        "-ClientName",
        CLIENT_NAME,
    ]
    if host_preset is not None or client_preset is not None:
        if host_preset is not None:
            args.extend(["-HostPreset", host_preset])
        if client_preset is not None:
            args.extend(["-ClientPreset", client_preset])
    else:
        args.extend(["-Preset", preset])
    if temporary_host_profile:
        args.append("-TemporaryHostProfile")
    if third_player:
        args.extend(
            [
                "-EnableThird",
                "-ThirdParticipantId",
                f"0x{THIRD_ID:X}",
                "-ThirdName",
                THIRD_NAME,
            ]
        )
        if third_preset is not None:
            args.extend(["-ThirdPreset", third_preset])
    if god_mode:
        args.append("-GodMode")
    if test_survival_boneyard_override is not None:
        args.extend([
            "-TestSurvivalBoneyardOverride",
            path_for_powershell(test_survival_boneyard_override),
        ])
    if test_blank_boneyard:
        args.append("-TestBlankBoneyard")
    if test_wave_override is not None:
        args.extend([
            "-TestWaveOverride",
            path_for_powershell(test_wave_override),
        ])
    if not tile_windows:
        args.append("-NoTileWindows")
    if allow_focus_steal:
        args.append("-AllowFocusSteal")
    if serialized_exact_mod_ids is not None:
        args.extend(["-ExactModIds", serialized_exact_mod_ids])
    process_id_ledger: Path | None = None
    if not kill_existing:
        args.append("-NoKill")
        process_id_ledger = _new_process_id_ledger()
        args.extend(
            [
                "-ProcessIdOutputPath",
                path_for_powershell(process_id_ledger),
            ]
        )
    process = subprocess.Popen(
        args,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
    )
    assert process.stdout is not None

    def terminate_launcher() -> None:
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            process.kill()

    def query_scene_for_launch(pipe_name: str) -> str:
        env = os.environ.copy()
        env["SDMOD_LUA_EXEC_PIPE_NAME"] = pipe_name
        env["SDMOD_LUA_EXEC_BRIDGE_TIMEOUT_SECONDS"] = "0.750"
        try:
            completed = subprocess.run(
                [
                    "python3",
                    "tools/lua-exec.py",
                    "local s=sd.world.get_scene(); return tostring(s and (s.name or s.kind) or '')",
                ],
                cwd=ROOT,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=2.75,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return ""
        if completed.returncode != 0:
            return ""
        return completed.stdout.strip()

    launch_started = time.monotonic()
    deadline = launch_started + (180.0 if third_player else 120.0)
    # The PowerShell launcher owns the Lua pipes while it is driving the two
    # native create screens. Probing those same single-consumer pipes from this
    # wrapper can race its element/discipline actions and leave the stock game
    # transitioning with half-consumed UI state. The launcher now has explicit
    # create-screen readiness checks, so reserve this scene-only fallback for a
    # genuinely wedged launcher instead of competing during normal startup.
    fallback_probe_after = launch_started + (120.0 if third_player else 75.0)
    buffer = ""
    last_hub_probe = 0.0
    hub_ready_since: float | None = None
    launch_completed = False
    try:
        while time.monotonic() < deadline:
            ready, _, _ = select.select([process.stdout], [], [], 0.1)
            if ready:
                line = process.stdout.readline()
                if line:
                    buffer += line
                    parsed = extract_json(buffer)
                    if parsed is not None:
                        launch_completed = True
                        return parsed
                elif process.poll() is not None:
                    break

            if process.poll() is not None:
                remainder = process.stdout.read()
                if remainder:
                    buffer += remainder
                    parsed = extract_json(buffer)
                    if parsed is not None:
                        launch_completed = True
                        return parsed
                if process.returncode != 0:
                    raise VerifyFailure(
                        f"pair launcher failed ({process.returncode}):\n{buffer}"
                    )
                break

            now = time.monotonic()
            if now >= fallback_probe_after and now - last_hub_probe >= 1.0:
                last_hub_probe = now
                if (
                    query_scene_for_launch(HOST_PIPE) == "hub"
                    and query_scene_for_launch(CLIENT_PIPE) == "hub"
                    and (
                        not third_player
                        or query_scene_for_launch(THIRD_PIPE) == "hub"
                    )
                ):
                    if hub_ready_since is None:
                        hub_ready_since = now
                    elif now - hub_ready_since >= 1.0:
                        fallback_result = {
                            "fallbackReady": True,
                            "hostLuaPipe": HOST_PIPE,
                            "clientLuaPipe": CLIENT_PIPE,
                            "thirdLuaPipe": THIRD_PIPE if third_player else None,
                            "hostName": HOST_NAME,
                            "clientName": CLIENT_NAME,
                            "thirdName": THIRD_NAME if third_player else None,
                        }
                        fallback_result.update(
                            _read_process_id_ledger(process_id_ledger)
                        )
                        launch_completed = True
                        return fallback_result
                else:
                    hub_ready_since = None

        raise VerifyFailure(f"timed out waiting for pair launcher JSON:\n{buffer}")
    finally:
        terminate_launcher()
        if not launch_completed:
            stop_game_processes(
                game_process_ids(_read_process_id_ledger(process_id_ledger))
            )
        if process_id_ledger is not None:
            process_id_ledger.unlink(missing_ok=True)


def launch_trio(
    preset: str = "map_create_fire_mind_hub",
    *,
    host_preset: str | None = None,
    client_preset: str | None = None,
    third_preset: str | None = None,
    temporary_host_profile: bool = True,
    god_mode: bool = False,
    tile_windows: bool = True,
    test_survival_boneyard_override: Path | None = None,
    test_blank_boneyard: bool = False,
    test_wave_override: Path | None = None,
) -> dict[str, object]:
    """Launch the host plus two independent clients through the host relay."""
    return launch_pair(
        preset,
        host_preset=host_preset,
        client_preset=client_preset,
        temporary_host_profile=temporary_host_profile,
        god_mode=god_mode,
        tile_windows=tile_windows,
        test_survival_boneyard_override=test_survival_boneyard_override,
        test_blank_boneyard=test_blank_boneyard,
        test_wave_override=test_wave_override,
        third_player=True,
        third_preset=third_preset,
    )


def launch_additional_client(
    *,
    instance: str = "local-mp-third",
    preset: str = "create_manual",
    local_port: int = 47772,
    participant_id: int = THIRD_ID,
    player_name: str = THIRD_NAME,
    god_mode: bool = False,
    test_survival_boneyard_override: Path | None = None,
    test_blank_boneyard: bool = False,
    test_wave_override: Path | None = None,
    exact_mod_id: str | None = None,
    exact_mod_ids: Iterable[str] | None = None,
) -> dict[str, object]:
    """Launch one client without stopping or relaunching an existing session."""
    args = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        "scripts/Launch-LocalMultiplayerAdditionalClient.ps1",
        "-Instance",
        instance,
        "-Preset",
        preset,
        "-LocalPort",
        str(local_port),
        "-ParticipantId",
        f"0x{participant_id:X}",
        "-PlayerName",
        player_name,
        "-HostName",
        HOST_NAME,
    ]
    if god_mode:
        args.append("-GodMode")
    serialized_exact_mod_ids = _serialize_exact_mod_ids(
        exact_mod_id=exact_mod_id,
        exact_mod_ids=exact_mod_ids,
    )
    if serialized_exact_mod_ids is not None:
        args.extend(["-ExactModIds", serialized_exact_mod_ids])
    if test_survival_boneyard_override is not None:
        args.extend(
            [
                "-TestSurvivalBoneyardOverride",
                path_for_powershell(test_survival_boneyard_override),
            ]
        )
    if test_blank_boneyard:
        args.append("-TestBlankBoneyard")
    if test_wave_override is not None:
        args.extend(
            [
                "-TestWaveOverride",
                path_for_powershell(test_wave_override),
            ]
        )
    process_id_ledger = _new_process_id_ledger()
    args.extend(
        [
            "-ProcessIdOutputPath",
            path_for_powershell(process_id_ledger),
        ]
    )
    process = subprocess.Popen(
        args,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
    )
    assert process.stdout is not None
    buffer = ""
    deadline = time.monotonic() + 75.0
    launch_completed = False
    try:
        while time.monotonic() < deadline:
            ready, _, _ = select.select([process.stdout], [], [], 0.1)
            if ready:
                line = process.stdout.readline()
                if line:
                    buffer += line
                    parsed = extract_json(buffer)
                    if parsed is not None:
                        if not parsed.get("success"):
                            raise VerifyFailure(
                                f"additional-client launcher reported failure: {parsed}"
                            )
                        launch_completed = True
                        return parsed
                elif process.poll() is not None:
                    break
            if process.poll() is not None:
                remainder = process.stdout.read()
                if remainder:
                    buffer += remainder
                parsed = extract_json(buffer)
                if parsed is not None and parsed.get("success"):
                    launch_completed = True
                    return parsed
                break
        raise VerifyFailure(
            f"timed out waiting for additional-client launcher JSON: {buffer}"
        )
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                process.kill()
        if not launch_completed:
            stop_game_processes(
                game_process_ids(_read_process_id_ledger(process_id_ledger))
            )
        process_id_ledger.unlink(missing_ok=True)


CREATE_ELEMENT_IDS = {
    "ether": 0,
    "fire": 1,
    "air": 2,
    "water": 3,
    "earth": 4,
}
CREATE_DISCIPLINE_IDS = {
    "mind": 0,
    "body": 1,
    "arcane": 2,
}


def query_native_create_state(pipe_name: str, action_id: str = "") -> dict[str, str]:
    code = f"""
local function emit(key, value) print(key .. '=' .. tostring(value == nil and '' or value)) end
local scene = sd.world.get_scene()
local snap = sd.ui.get_snapshot()
local owner = 0
if type(snap) == 'table' then
  for _, element in ipairs(snap.elements or {{}}) do
    if element.surface_id == 'create' or element.surface_root_id == 'create' then
      owner = tonumber(element.surface_object_ptr) or 0
      break
    end
  end
end
local function read_u32(offset)
  if owner == 0 then return nil end
  local ok, value = pcall(sd.debug.read_u32, owner + offset)
  if ok then return tonumber(value) end
  return nil
end
local function read_u8(offset)
  local value = read_u32(offset)
  if value == nil then return nil end
  return value % 256
end
local action_id = {json.dumps(action_id)}
local action = nil
if action_id ~= '' and sd.ui.find_action ~= nil then
  action = sd.ui.find_action(action_id, 'create')
end
emit('scene', scene and (scene.name or scene.kind) or '')
emit('ui', snap and snap.surface_id or '')
emit('owner', owner)
emit('element_enabled', read_u8(0x18C))
emit('element_selected', read_u32(0x1A4))
emit('discipline_enabled', read_u8(0x228))
emit('discipline_selected', read_u32(0x22C))
emit('action_found', action ~= nil)
emit('action_enabled', action and action.enabled or false)
emit('action_interactive', action and action.interactive or false)
"""
    return parse_key_values(
        lua(pipe_name, code, timeout=NATIVE_UI_LUA_TIMEOUT_SECONDS)
    )


def activate_native_ui_action(
    pipe_name: str,
    action_id: str,
    surface_id: str,
) -> dict[str, str]:
    requested = parse_key_values(
        lua(
            pipe_name,
            f"""
local ok, request = sd.ui.activate_action({json.dumps(action_id)}, {json.dumps(surface_id)})
print('ok=' .. tostring(ok))
print('request=' .. tostring(request))
""",
            timeout=NATIVE_UI_LUA_TIMEOUT_SECONDS,
        )
    )
    if requested.get("ok") != "true":
        raise VerifyFailure(
            f"native UI action was rejected on {pipe_name}: {action_id} -> {requested}"
        )
    request_id = parse_int_text(requested.get("request"), 0)
    deadline = time.monotonic() + 10.0
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = parse_key_values(
            lua(
                pipe_name,
                f"""
local d = sd.ui.get_action_dispatch({request_id})
print('status=' .. tostring(d and d.status or ''))
print('error=' .. tostring(d and d.error_message or ''))
""",
                timeout=NATIVE_UI_LUA_TIMEOUT_SECONDS,
            )
        )
        status = last.get("status", "")
        if status == "failed":
            raise VerifyFailure(
                f"native UI action failed on {pipe_name}: {action_id} -> {last}"
            )
        if status not in ("", "queued", "dispatching"):
            return {**requested, **last}
        time.sleep(0.1)
    raise VerifyFailure(
        f"native UI action dispatch timed out on {pipe_name}: {action_id} -> {last}"
    )


def complete_native_create(
    pipe_name: str,
    *,
    element: str,
    discipline: str,
    timeout: float = 45.0,
) -> dict[str, object]:
    if element not in CREATE_ELEMENT_IDS:
        raise VerifyFailure(f"unknown create element {element!r}")
    if discipline not in CREATE_DISCIPLINE_IDS:
        raise VerifyFailure(f"unknown create discipline {discipline!r}")

    actions: list[dict[str, str]] = []
    phase_specs = (
        (
            "element",
            f"create.select_element_{element}",
            "element_enabled",
            "element_selected",
            CREATE_ELEMENT_IDS[element],
        ),
        (
            "discipline",
            f"create.select_discipline_{discipline}",
            "discipline_enabled",
            "discipline_selected",
            CREATE_DISCIPLINE_IDS[discipline],
        ),
    )
    for phase, action_id, enabled_key, selected_key, expected_id in phase_specs:
        deadline = time.monotonic() + timeout
        last: dict[str, str] = {}
        while time.monotonic() < deadline:
            last = query_native_create_state(pipe_name, action_id)
            selected = parse_int_text(last.get(selected_key), -1)
            if last.get("scene") in ("hub", "testrun"):
                break
            if (
                last.get("ui") == "create"
                and parse_int_text(last.get("owner"), 0) != 0
                and parse_int_text(last.get(enabled_key), 0) != 0
                and selected in (-1, 0xFFFFFFFF)
                and last.get("action_found") == "true"
            ):
                actions.append(
                    activate_native_ui_action(pipe_name, action_id, "create")
                )
                break
            time.sleep(0.1)
        else:
            raise VerifyFailure(
                f"native create {phase} never became ready on {pipe_name}: {last}"
            )

        latch_deadline = time.monotonic() + 12.0
        while time.monotonic() < latch_deadline:
            last = query_native_create_state(pipe_name)
            if last.get("scene") in ("hub", "testrun"):
                break
            if parse_int_text(last.get(selected_key), -1) == expected_id:
                break
            time.sleep(0.1)
        else:
            raise VerifyFailure(
                f"native create {phase} did not latch id={expected_id} on {pipe_name}: {last}"
            )

    deadline = time.monotonic() + timeout
    last_scene = ""
    while time.monotonic() < deadline:
        last_scene = lua(
            pipe_name,
            "local s=sd.world.get_scene(); return tostring(s and (s.name or s.kind) or '')",
            timeout=NATIVE_UI_LUA_TIMEOUT_SECONDS,
        ).strip()
        if last_scene in ("hub", "testrun"):
            return {"scene": last_scene, "actions": actions}
        time.sleep(0.1)
    raise VerifyFailure(
        f"native create selection did not reach hub/run on {pipe_name}; last={last_scene!r}"
    )


# A live multiplayer run issues tens of thousands of lua() calls. Spawning a
# fresh python+powershell pair per call (the old path) cost ~0.4s each — pure
# process-startup tax that dominated per-kill wall time. Instead we keep one
# long-lived powershell "-Daemon" per pipe and shuttle requests over its
# stdin/stdout, so that tax is paid once per pipe per run. The daemon speaks a
# base64-line protocol (see Invoke-LuaExecDaemon); the raw game response is
# decoded and formatted here through the SAME _format_response the one-shot
# bridge uses, so behaviour and error semantics are identical — just faster.
_lua_exec_spec = importlib.util.spec_from_file_location(
    "sdmod_lua_exec_bridge", ROOT / "tools" / "lua-exec.py"
)
_lua_exec_module = importlib.util.module_from_spec(_lua_exec_spec)
_lua_exec_spec.loader.exec_module(_lua_exec_module)
_format_lua_response = _lua_exec_module._format_response

_LUA_DAEMONS: dict[str, subprocess.Popen] = {}
_LUA_DAEMON_LOCKS: dict[str, threading.Lock] = {}
_LUA_DAEMON_READ_QUEUES: dict[
    str,
    queue.Queue[tuple[str, Exception | None]],
] = {}
_LUA_DAEMON_REGISTRY_LOCK = threading.Lock()


def _lua_daemon_lock(pipe_name: str) -> threading.Lock:
    with _LUA_DAEMON_REGISTRY_LOCK:
        lock = _LUA_DAEMON_LOCKS.get(pipe_name)
        if lock is None:
            lock = threading.Lock()
            _LUA_DAEMON_LOCKS[pipe_name] = lock
        return lock


def _spawn_lua_daemon(pipe_name: str) -> subprocess.Popen:
    env = os.environ.copy()
    env["SDMOD_LUA_EXEC_PIPE_NAME"] = pipe_name
    proc = subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-File",
            "scripts/Invoke-LuaExec.ps1",
            "-Daemon",
            "-PipeName",
            pipe_name,
        ],
        cwd=ROOT,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="ascii",
        bufsize=1,
    )
    if os.name == "nt":
        _start_lua_daemon_reader(pipe_name, proc)
    return proc


def _start_lua_daemon_reader(
    pipe_name: str,
    proc: subprocess.Popen,
) -> None:
    output: queue.Queue[tuple[str, Exception | None]] = queue.Queue()
    _LUA_DAEMON_READ_QUEUES[pipe_name] = output

    def read_lines() -> None:
        if proc.stdout is None:
            output.put(("", None))
            return
        while True:
            try:
                line = proc.stdout.readline()
            except Exception as error:  # noqa: BLE001 - return reader failure to caller.
                output.put(("", error))
                return
            output.put((line, None))
            if not line:
                return

    threading.Thread(target=read_lines, daemon=True).start()


def _get_lua_daemon(pipe_name: str) -> subprocess.Popen:
    proc = _LUA_DAEMONS.get(pipe_name)
    if proc is None or proc.poll() is not None:
        proc = _spawn_lua_daemon(pipe_name)
        _LUA_DAEMONS[pipe_name] = proc
    return proc


def _kill_lua_daemon(pipe_name: str) -> None:
    proc = _LUA_DAEMONS.pop(pipe_name, None)
    _LUA_DAEMON_READ_QUEUES.pop(pipe_name, None)
    if proc is None:
        return
    for closer in (
        lambda: proc.stdin and proc.stdin.close(),
        proc.kill,
    ):
        try:
            closer()
        except (OSError, ValueError):
            pass
    try:
        proc.wait(timeout=0.5)
    except (subprocess.TimeoutExpired, OSError, ValueError):
        pass


def _lua_daemon_exit_detail(proc: subprocess.Popen) -> str:
    try:
        if proc.poll() is None or proc.stderr is None:
            return ""
        detail = proc.stderr.read().strip()
        return detail
    except (OSError, ValueError):
        return ""


def _read_lua_daemon_line(
    pipe_name: str,
    proc: subprocess.Popen,
    timeout: float,
) -> tuple[bool, str]:
    if proc.stdout is None:
        return True, ""
    if os.name != "nt":
        ready, _, _ = select.select([proc.stdout], [], [], timeout)
        return (True, proc.stdout.readline()) if ready else (False, "")

    output = _LUA_DAEMON_READ_QUEUES.get(pipe_name)
    if output is None:
        raise ValueError(f"missing Windows Lua daemon reader for {pipe_name}")
    try:
        line, error = output.get(timeout=timeout)
    except queue.Empty:
        return False, ""
    if error is not None:
        raise error
    return True, line


@atexit.register
def _shutdown_lua_daemons() -> None:
    for pipe_name in list(_LUA_DAEMONS):
        _kill_lua_daemon(pipe_name)


def lua(pipe_name: str, code: str, timeout: float = 10.0) -> str:
    deadline = max(0.05, float(timeout))
    request = base64.b64encode(code.encode("utf-8")).decode("ascii")
    lock = _lua_daemon_lock(pipe_name)
    with lock:
        proc = _get_lua_daemon(pipe_name)
        try:
            proc.stdin.write(request + "\n")
            proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            _kill_lua_daemon(pipe_name)
            raise VerifyFailure(
                f"lua bridge daemon write failed for {pipe_name}: {exc}"
            ) from exc

        try:
            ready, line = _read_lua_daemon_line(pipe_name, proc, deadline)
        except (OSError, ValueError) as exc:
            _kill_lua_daemon(pipe_name)
            raise VerifyFailure(
                f"lua bridge daemon read failed for {pipe_name}: {exc}"
            ) from exc
        if not ready:
            exit_detail = _lua_daemon_exit_detail(proc)
            _kill_lua_daemon(pipe_name)
            if exit_detail:
                raise VerifyFailure(
                    f"lua bridge daemon exited for {pipe_name}: {exit_detail}"
                )
            raise VerifyFailure(
                f"lua bridge daemon timed out after {deadline:.1f}s for {pipe_name}: {code[:120]}"
            )

    if not line:
        exit_detail = _lua_daemon_exit_detail(proc)
        _kill_lua_daemon(pipe_name)
        if exit_detail:
            raise VerifyFailure(
                f"lua bridge daemon closed for {pipe_name}: {exit_detail}"
            )
        raise VerifyFailure(
            f"lua bridge daemon closed unexpectedly for {pipe_name}: {code[:120]}"
        )
    try:
        raw = base64.b64decode(line.strip()).decode("utf-8", "replace")
    except ValueError as exc:
        _kill_lua_daemon(pipe_name)
        raise VerifyFailure(
            f"lua bridge daemon returned a malformed frame for {pipe_name}: {line!r}"
        ) from exc

    stdout_text, stderr_text, exit_code = _format_lua_response(raw)
    if exit_code != 0:
        detail = stderr_text.strip() or stdout_text.strip() or "lua execution failed"
        raise VerifyFailure(f"lua failed on {pipe_name}: {detail}")
    return stdout_text.strip()


def parse_key_values(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in text.splitlines():
        if "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def parse_int_text(value: str | None, default: int = 0) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value, 0)
    except ValueError:
        return int(float(value))


def visual_blocks_by_type(values: dict[str, str], prefix: str) -> dict[int, str]:
    blocks: dict[int, str] = {}
    for lane in ("primary", "secondary"):
        type_id = parse_int_text(values.get(f"{prefix}.{lane}_visual_type"), 0)
        block = values.get(f"{prefix}.{lane}_visual_block", "")
        if type_id != 0 and block:
            blocks[type_id] = block
    return blocks


QUERY_LUA = r"""
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
local scene = sd.world.get_scene()
local player = sd.player.get_state()
emit("scene", scene and (scene.name or scene.kind) or "")
emit("player.actor", player and player.actor_address or 0)
emit("player.x", player and player.x or 0)
emit("player.y", player and player.y or 0)
emit("player.heading", player and player.heading or 0)
local radius_offset = sd.debug.layout_offset("actor_collision_radius")
local animation_drive_offset = sd.debug.layout_offset("actor_animation_drive_state_byte")
local heading_offset = sd.debug.layout_offset("actor_heading")
local function actor_radius(actor_address)
  if actor_address == nil or actor_address == 0 or radius_offset == nil then
    return 0
  end
  return sd.debug.read_float(actor_address + radius_offset) or 0
end
local function actor_animation_drive(actor_address)
  if actor_address == nil or actor_address == 0 or animation_drive_offset == nil then
    return 0
  end
  return sd.debug.read_u8(actor_address + animation_drive_offset) or 0
end
local function actor_heading(actor_address)
  if actor_address == nil or actor_address == 0 or heading_offset == nil then
    return 0
  end
  return sd.debug.read_float(actor_address + heading_offset) or 0
end
local function staff_visual_state(lane)
  if lane == nil or lane.current_object_address == nil or lane.current_object_address == 0 then
    return 0
  end
  return sd.debug.read_u32(lane.current_object_address + 0x84) or 0
end
local function visual_link_block(lane)
  if lane == nil or lane.current_object_address == nil or lane.current_object_address == 0 then
    return ""
  end
  local out = {}
  for i = 0, 31 do
    out[#out + 1] = string.format("%02X", tonumber(sd.debug.read_u8(lane.current_object_address + 0x88 + i)) or 0)
  end
  return table.concat(out, " ")
end
local function visual_link_type(lane)
  if lane == nil then
    return 0
  end
  return lane.current_object_type_id or 0
end
local function visual_link_address(lane)
  if lane == nil then
    return 0
  end
  return lane.current_object_address or 0
end
local function render_selector(state)
  if state == nil then
    return ""
  end
  return table.concat({
    tostring(state.render_variant_primary or 0),
    tostring(state.render_variant_secondary or 0),
    tostring(state.render_weapon_type or 0),
    tostring(state.render_selection_byte or 0),
    tostring(state.render_variant_tertiary or 0),
  }, ",")
end
emit("player.radius", player and actor_radius(player.actor_address) or 0)
emit("player.actor_heading", player and actor_heading(player.actor_address) or 0)
emit("player.animation_drive", player and actor_animation_drive(player.actor_address) or 0)
emit("player.staff_visual_state", player and staff_visual_state(player.attachment_visual_lane) or 0)
emit("player.render_selector", render_selector(player))
emit("player.primary_visual_type", player and visual_link_type(player.primary_visual_lane) or 0)
emit("player.primary_visual_block", player and visual_link_block(player.primary_visual_lane) or "")
emit("player.secondary_visual_type", player and visual_link_type(player.secondary_visual_lane) or 0)
emit("player.secondary_visual_block", player and visual_link_block(player.secondary_visual_lane) or "")
emit("player.attachment_visual_type", player and visual_link_type(player.attachment_visual_lane) or 0)
emit("player.attachment_visual_address", player and visual_link_address(player.attachment_visual_lane) or 0)
local peers = sd.bots.get_participants()
emit("peer.count", #peers)
for i, peer in ipairs(peers) do
  local prefix = "peer." .. tostring(peer.id) .. "."
  emit(prefix .. "name", peer.name)
  emit(prefix .. "kind", peer.participant_kind)
  emit(prefix .. "controller", peer.controller_kind)
  emit(prefix .. "element_id", peer.profile and peer.profile.element_id or -1)
  emit(prefix .. "materialized", peer.entity_materialized)
  emit(prefix .. "transform", peer.transform_valid)
  emit(prefix .. "actor", peer.actor_address)
  emit(prefix .. "x", peer.x)
  emit(prefix .. "y", peer.y)
  emit(prefix .. "heading", peer.heading)
  emit(prefix .. "actor_heading", actor_heading(peer.actor_address))
  emit(prefix .. "radius", actor_radius(peer.actor_address))
  emit(prefix .. "animation_drive", actor_animation_drive(peer.actor_address))
  emit(prefix .. "staff_visual_state", staff_visual_state(peer.attachment_visual_lane))
  emit(prefix .. "render_selector", render_selector(peer))
  emit(prefix .. "primary_visual_type", visual_link_type(peer.primary_visual_lane))
  emit(prefix .. "primary_visual_block", visual_link_block(peer.primary_visual_lane))
  emit(prefix .. "secondary_visual_type", visual_link_type(peer.secondary_visual_lane))
  emit(prefix .. "secondary_visual_block", visual_link_block(peer.secondary_visual_lane))
  emit(prefix .. "attachment_visual_type", visual_link_type(peer.attachment_visual_lane))
  emit(prefix .. "attachment_visual_address", visual_link_address(peer.attachment_visual_lane))
  local nameplate = nil
  if peer.actor_address ~= nil and peer.actor_address ~= 0 then
    nameplate = sd.bots.get_nameplate(peer.actor_address)
  end
  emit(prefix .. "nameplate", nameplate and nameplate.name or "")
end
local replicated = nil
if sd.world.get_replicated_actors ~= nil then
  replicated = sd.world.get_replicated_actors()
end
emit("replicated.valid", replicated ~= nil)
emit("replicated.scene_kind", replicated and replicated.scene_kind or "")
emit("replicated.actor_count", replicated and replicated.actor_count or 0)
emit("replicated.actor_total_count", replicated and replicated.actor_total_count or 0)
emit("replicated.authority_participant_id", replicated and replicated.authority_participant_id or 0)
emit("replicated.apply_valid", replicated and replicated.apply_valid or false)
-- Natural level-ups (crossing an XP threshold from real kills) open a
-- host-coordinated skill picker that holds BOTH instances paused
-- (level_up_wait_status.pause_active) until the target participant chooses an
-- option. While paused, the gameplay-tick-driven transform publish freezes, so
-- the peer's mirror stops updating and a pair can never converge. Carry the
-- pause/offer signal on this existing snapshot so convergence can resolve the
-- offer inline instead of timing out. The active offer is only "valid" on the
-- instance that must choose (the target), so callers act on the pipe that
-- reports levelup.offer_valid=true.
local mp = sd.runtime and sd.runtime.get_multiplayer_state and sd.runtime.get_multiplayer_state() or nil
local local_participant = nil
for _, participant in ipairs(mp and mp.participants or {}) do
  if participant.is_owner then
    local_participant = participant
    break
  end
end
emit("local.runtime_valid", local_participant and local_participant.runtime_valid or false)
emit("local.in_run", local_participant and local_participant.in_run or false)
emit("local.run_nonce", local_participant and local_participant.run_nonce or 0)
emit("local.scene_kind", local_participant and local_participant.scene_kind or "")
local offer = mp and mp.active_level_up_offer or nil
emit("levelup.offer_valid", offer and offer.valid or false)
emit("levelup.offer_id", offer and offer.offer_id or 0)
emit("levelup.offer_submitted", offer and offer.selection_submitted or false)
emit("levelup.offer_option_count", offer and offer.option_count or 0)
local wait = mp and mp.level_up_wait_status or nil
emit("levelup.pause_active", wait and wait.pause_active or false)
emit("levelup.waiting_count", wait and wait.waiting_count or 0)
"""


def query(pipe_name: str) -> dict[str, str]:
    return parse_key_values(lua(pipe_name, QUERY_LUA))


def pending_level_up_offer(values: dict[str, str]) -> dict[str, int] | None:
    """Return the unresolved level-up offer this instance must choose, or None.

    ``values`` is a :func:`query` result. A level-up offer is only ``valid`` on
    the instance that is the offer target (the one whose skill picker is open),
    so a non-None result means *this* pipe should submit the choice.
    """
    if values.get("levelup.offer_valid") != "true":
        return None
    if values.get("levelup.offer_submitted") == "true":
        return None
    return {
        "offer_id": parse_int_text(values.get("levelup.offer_id"), 0),
        "option_count": parse_int_text(values.get("levelup.offer_option_count"), 0),
    }


def submit_level_up_choice(
    pipe_name: str,
    offer_id: int,
    option_index: int = 1,
) -> dict[str, str]:
    """Submit a level-up skill choice on ``pipe_name`` (the offer target's pipe)."""
    code = f"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local ok, result = pcall(sd.runtime.choose_level_up_option, {{ offer_id = {offer_id}, option_index = {option_index} }})
emit("pcall_ok", ok)
emit("result", result)
"""
    values = parse_key_values(lua(pipe_name, code, timeout=5.0))
    if values.get("pcall_ok") != "true" or values.get("result") != "true":
        raise VerifyFailure(
            f"failed to submit level-up choice on {pipe_name}: "
            f"offer_id={offer_id} option_index={option_index} -> {values}"
        )
    return values


def resolve_level_ups_from_snapshots(
    host_values: dict[str, str],
    client_values: dict[str, str],
    *,
    option_index: int = 1,
) -> list[dict[str, Any]]:
    """Resolve any pending level-up offers visible in the given host/client snapshots.

    Chooses the first option on whichever pipe is the offer target, unblocking the
    host-coordinated level-up pause. Returns one record per offer resolved (empty
    if neither instance had a pending offer to act on). Picking the first option is
    deterministic and always legal: the native picker only ever offers currently
    valid choices, regenerating them each level.
    """
    resolved: list[dict[str, Any]] = []
    for pipe_name, values in ((HOST_PIPE, host_values), (CLIENT_PIPE, client_values)):
        pending = pending_level_up_offer(values)
        if pending is None:
            continue
        offer_id = pending["offer_id"]
        submit_level_up_choice(pipe_name, offer_id, option_index)
        resolved.append(
            {
                "pipe": pipe_name,
                "offer_id": offer_id,
                "option_index": option_index,
                "option_count": pending["option_count"],
            }
        )
    return resolved


def wait_for_remote(
    pipe_name: str,
    participant_id: int,
    expected_name: str,
    expected_scene: str,
    timeout: float = 30.0,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    last_error = ""
    prefix = f"peer.{participant_id}."
    while time.monotonic() < deadline:
        try:
            last = query(pipe_name)
            last_error = ""
        except (VerifyFailure, subprocess.TimeoutExpired) as exc:
            last_error = str(exc)
            time.sleep(0.25)
            continue
        if (
            last.get("scene") == expected_scene
            and last.get(prefix + "name") == expected_name
            and last.get(prefix + "nameplate") == expected_name
            and last.get(prefix + "materialized") == "true"
            and last.get(prefix + "transform") == "true"
            and int(float(last.get(prefix + "actor", "0") or "0")) != 0
        ):
            return last
        time.sleep(0.25)
    suffix = f"; last_error={last_error}" if last_error else ""
    raise VerifyFailure(
        f"remote participant {participant_id} not visible on {pipe_name}; last={last}{suffix}"
    )


def nudge_player(pipe_name: str, dx: float, dy: float, heading: float) -> dict[str, str]:
    code = f"""
local player = sd.player.get_state()
local ox = sd.debug.layout_offset("actor_position_x")
local oy = sd.debug.layout_offset("actor_position_y")
local oh = sd.debug.layout_offset("actor_heading")
local os = sd.debug.layout_offset("actor_animation_selection_state")
local oha = sd.debug.layout_offset("actor_control_brain_heading_accumulator")
local odf = sd.debug.layout_offset("actor_control_brain_desired_facing")
local odfs = sd.debug.layout_offset("actor_control_brain_desired_facing_smoothed")
local ost = sd.debug.layout_offset("actor_control_brain_state_id")
local ots = sd.debug.layout_offset("actor_control_brain_target_slot")
local oth = sd.debug.layout_offset("actor_control_brain_target_handle")
local ort = sd.debug.layout_offset("actor_control_brain_retarget_ticks")
local otc = sd.debug.layout_offset("actor_control_brain_target_cooldown_ticks")
local oac = sd.debug.layout_offset("actor_control_brain_action_cooldown_ticks")
local oab = sd.debug.layout_offset("actor_control_brain_action_burst_ticks")
local ohl = sd.debug.layout_offset("actor_control_brain_heading_lock_ticks")
local ofl = sd.debug.layout_offset("actor_control_brain_follow_leader")
local omx = sd.debug.layout_offset("actor_control_brain_move_input_x")
local omy = sd.debug.layout_offset("actor_control_brain_move_input_y")
local owv = sd.debug.layout_offset("actor_animation_config_block")
local owd = sd.debug.layout_offset("actor_animation_drive_parameter")
local owc1 = sd.debug.layout_offset("actor_walk_cycle_primary")
local owc2 = sd.debug.layout_offset("actor_walk_cycle_secondary")
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local function write_u32_if(actor, offset, value)
  if offset ~= nil then return sd.debug.write_u32(actor + offset, value) end
  return true
end
local function write_u16_if(actor, offset, value)
  if offset ~= nil then return sd.debug.write_u16(actor + offset, value) end
  return true
end
local function write_u8_if(actor, offset, value)
  if offset ~= nil then return sd.debug.write_u8(actor + offset, value) end
  return true
end
local function write_float_if(actor, offset, value)
  if offset ~= nil then return sd.debug.write_float(actor + offset, value) end
  return true
end
local function clear_control(actor)
  local wrote = true
  -- Zero the actor's own momentum integrator inputs FIRST (unconditionally, even
  -- if there is no control brain) so a residual post-cast walk vector cannot keep
  -- marching the participant after placement. The PlayerActorTick integrator
  -- re-feeds these from input each tick, so this only sticks during a no-input
  -- park phase (which is exactly when we place).
  wrote = write_float_if(actor, owv, 0.0) and wrote
  wrote = write_float_if(actor, owd, 0.0) and wrote
  wrote = write_float_if(actor, owc1, 0.0) and wrote
  wrote = write_float_if(actor, owc2, 0.0) and wrote
  if os == nil then return wrote end
  local control = sd.debug.read_u32(actor + os) or 0
  if control == 0 then return wrote end
  wrote = write_u32_if(control, ost, 0) and wrote
  wrote = write_u8_if(control, ots, 0xFF) and wrote
  wrote = write_u16_if(control, oth, 0xFFFF) and wrote
  wrote = write_u32_if(control, ort, 0) and wrote
  wrote = write_u32_if(control, otc, 0) and wrote
  wrote = write_u32_if(control, oac, 0) and wrote
  wrote = write_u32_if(control, oab, 0) and wrote
  wrote = write_u32_if(control, ohl, 0) and wrote
  wrote = write_u32_if(control, ofl, 0) and wrote
  wrote = write_float_if(control, omx, 0.0) and wrote
  wrote = write_float_if(control, omy, 0.0) and wrote
  return wrote
end
local function write_facing(actor, heading)
  local wrote = sd.debug.write_float(actor + oh, heading)
  if os ~= nil and oha ~= nil and odf ~= nil and odfs ~= nil then
    local control = sd.debug.read_u32(actor + os) or 0
    if control ~= 0 then
      wrote = sd.debug.write_float(control + oha, heading) and wrote
      wrote = sd.debug.write_float(control + odf, heading) and wrote
      wrote = sd.debug.write_float(control + odfs, heading) and wrote
    end
  end
  return wrote
end
if player == nil or player.actor_address == nil or player.actor_address == 0 then
  error("player actor unavailable")
end
local nx = tonumber(player.x) + ({dx})
local ny = tonumber(player.y) + ({dy})
emit("before.x", player.x)
emit("before.y", player.y)
emit("write.x", sd.debug.write_float(player.actor_address + ox, nx))
emit("write.y", sd.debug.write_float(player.actor_address + oy, ny))
emit("write.heading", write_facing(player.actor_address, {heading}))
local after = sd.player.get_state()
emit("after.x", after and after.x or 0)
emit("after.y", after and after.y or 0)
emit("after.heading", after and after.heading or 0)
"""
    values = parse_key_values(lua(pipe_name, code))
    if values.get("write.x") != "true" or values.get("write.y") != "true":
        raise VerifyFailure(f"failed to nudge player on {pipe_name}: {values}")
    return values


def hold_player_heading(pipe_name: str, heading: float | None) -> dict[str, str]:
    desired = "nil" if heading is None else f"{heading:.6f}"
    code = f"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
local function apply_held_heading()
  local desired = tonumber(_G.__sdmod_mp_test_held_heading)
  if desired == nil then return true end
  local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
  local actor = player and tonumber(player.actor_address) or 0
  if actor == 0 then return false end
  local heading_offset = sd.debug.layout_offset('actor_heading')
  local selection_offset = sd.debug.layout_offset('actor_animation_selection_state')
  local accumulator_offset = sd.debug.layout_offset('actor_control_brain_heading_accumulator')
  local desired_offset = sd.debug.layout_offset('actor_control_brain_desired_facing')
  local smoothed_offset = sd.debug.layout_offset('actor_control_brain_desired_facing_smoothed')
  local wrote = sd.debug.write_float(actor + heading_offset, desired)
  local control = selection_offset ~= nil and tonumber(sd.debug.read_u32(actor + selection_offset)) or 0
  if control ~= 0 then
    if accumulator_offset ~= nil then wrote = sd.debug.write_float(control + accumulator_offset, desired) and wrote end
    if desired_offset ~= nil then wrote = sd.debug.write_float(control + desired_offset, desired) and wrote end
    if smoothed_offset ~= nil then wrote = sd.debug.write_float(control + smoothed_offset, desired) and wrote end
  end
  return wrote
end
if not _G.__sdmod_mp_test_heading_hold_registered then
  sd.events.on('runtime.tick', apply_held_heading)
  _G.__sdmod_mp_test_heading_hold_registered = true
end
_G.__sdmod_mp_test_held_heading = {desired}
emit('registered', _G.__sdmod_mp_test_heading_hold_registered)
emit('enabled', _G.__sdmod_mp_test_held_heading ~= nil)
emit('apply', apply_held_heading())
"""
    values = parse_key_values(lua(pipe_name, code, timeout=5.0))
    if values.get("registered") != "true" or values.get("apply") != "true":
        raise VerifyFailure(f"failed to configure player heading hold on {pipe_name}: {values}")
    return values


def place_player(pipe_name: str, x: float, y: float, heading: float) -> dict[str, str]:
    code = f"""
local player = sd.player.get_state()
local ox = sd.debug.layout_offset("actor_position_x")
local oy = sd.debug.layout_offset("actor_position_y")
local oh = sd.debug.layout_offset("actor_heading")
local os = sd.debug.layout_offset("actor_animation_selection_state")
local oha = sd.debug.layout_offset("actor_control_brain_heading_accumulator")
local odf = sd.debug.layout_offset("actor_control_brain_desired_facing")
local odfs = sd.debug.layout_offset("actor_control_brain_desired_facing_smoothed")
local ost = sd.debug.layout_offset("actor_control_brain_state_id")
local ots = sd.debug.layout_offset("actor_control_brain_target_slot")
local oth = sd.debug.layout_offset("actor_control_brain_target_handle")
local ort = sd.debug.layout_offset("actor_control_brain_retarget_ticks")
local otc = sd.debug.layout_offset("actor_control_brain_target_cooldown_ticks")
local oac = sd.debug.layout_offset("actor_control_brain_action_cooldown_ticks")
local oab = sd.debug.layout_offset("actor_control_brain_action_burst_ticks")
local ohl = sd.debug.layout_offset("actor_control_brain_heading_lock_ticks")
local ofl = sd.debug.layout_offset("actor_control_brain_follow_leader")
local omx = sd.debug.layout_offset("actor_control_brain_move_input_x")
local omy = sd.debug.layout_offset("actor_control_brain_move_input_y")
local owv = sd.debug.layout_offset("actor_animation_config_block")
local owd = sd.debug.layout_offset("actor_animation_drive_parameter")
local owc1 = sd.debug.layout_offset("actor_walk_cycle_primary")
local owc2 = sd.debug.layout_offset("actor_walk_cycle_secondary")
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local function write_u32_if(actor, offset, value)
  if offset ~= nil then return sd.debug.write_u32(actor + offset, value) end
  return true
end
local function write_u16_if(actor, offset, value)
  if offset ~= nil then return sd.debug.write_u16(actor + offset, value) end
  return true
end
local function write_u8_if(actor, offset, value)
  if offset ~= nil then return sd.debug.write_u8(actor + offset, value) end
  return true
end
local function write_float_if(actor, offset, value)
  if offset ~= nil then return sd.debug.write_float(actor + offset, value) end
  return true
end
local function clear_control(actor)
  local wrote = true
  -- Zero the actor's own momentum integrator inputs FIRST (unconditionally, even
  -- if there is no control brain) so a residual post-cast walk vector cannot keep
  -- marching the participant after placement. The PlayerActorTick integrator
  -- re-feeds these from input each tick, so this only sticks during a no-input
  -- park phase (which is exactly when we place).
  wrote = write_float_if(actor, owv, 0.0) and wrote
  wrote = write_float_if(actor, owd, 0.0) and wrote
  wrote = write_float_if(actor, owc1, 0.0) and wrote
  wrote = write_float_if(actor, owc2, 0.0) and wrote
  if os == nil then return wrote end
  local control = sd.debug.read_u32(actor + os) or 0
  if control == 0 then return wrote end
  wrote = write_u32_if(control, ost, 0) and wrote
  wrote = write_u8_if(control, ots, 0xFF) and wrote
  wrote = write_u16_if(control, oth, 0xFFFF) and wrote
  wrote = write_u32_if(control, ort, 0) and wrote
  wrote = write_u32_if(control, otc, 0) and wrote
  wrote = write_u32_if(control, oac, 0) and wrote
  wrote = write_u32_if(control, oab, 0) and wrote
  wrote = write_u32_if(control, ohl, 0) and wrote
  wrote = write_u32_if(control, ofl, 0) and wrote
  wrote = write_float_if(control, omx, 0.0) and wrote
  wrote = write_float_if(control, omy, 0.0) and wrote
  return wrote
end
local function write_facing(actor, heading)
  local wrote = sd.debug.write_float(actor + oh, heading)
  if os ~= nil and oha ~= nil and odf ~= nil and odfs ~= nil then
    local control = sd.debug.read_u32(actor + os) or 0
    if control ~= 0 then
      wrote = sd.debug.write_float(control + oha, heading) and wrote
      wrote = sd.debug.write_float(control + odf, heading) and wrote
      wrote = sd.debug.write_float(control + odfs, heading) and wrote
    end
  end
  return wrote
end
if player == nil or player.actor_address == nil or player.actor_address == 0 then
  error("player actor unavailable")
end
emit("before.x", player.x)
emit("before.y", player.y)
emit("clear_control", clear_control(player.actor_address))
emit("write.x", sd.debug.write_float(player.actor_address + ox, {x}))
emit("write.y", sd.debug.write_float(player.actor_address + oy, {y}))
emit("write.heading", write_facing(player.actor_address, {heading}))
local rebind_ok, rebind_error = true, ""
if sd.world ~= nil and sd.world.rebind_actor ~= nil then
  rebind_ok, rebind_error = sd.world.rebind_actor(player.actor_address)
end
emit("rebind", rebind_ok)
emit("rebind_error", rebind_error or "")
local after = sd.player.get_state()
emit("after.x", after and after.x or 0)
emit("after.y", after and after.y or 0)
emit("after.heading", after and after.heading or 0)
"""
    values = parse_key_values(lua(pipe_name, code))
    if values.get("write.x") != "true" or values.get("write.y") != "true":
        raise VerifyFailure(f"failed to place player on {pipe_name}: {values}")
    return values


def snap_to_nav(pipe_name: str, x: float, y: float) -> tuple[float, float]:
    code = f"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local grid = sd.debug.get_nav_grid(1)
if type(grid) ~= "table" or grid.valid == false or type(grid.cells) ~= "table" then
  emit("available", false)
  return
end
local target_x = {x}
local target_y = {y}
local best = nil
local best_gap = nil
for _, cell in ipairs(grid.cells) do
  if type(cell) == "table" and type(cell.samples) == "table" then
    for _, sample in ipairs(cell.samples) do
      if type(sample) == "table" and sample.traversable and
          tonumber(sample.world_x) ~= nil and tonumber(sample.world_y) ~= nil then
        local dx = tonumber(sample.world_x) - target_x
        local dy = tonumber(sample.world_y) - target_y
        local gap = math.sqrt(dx * dx + dy * dy)
        if best_gap == nil or gap < best_gap then
          best_gap = gap
          best = sample
        end
      end
    end
  end
end
if best == nil then
  emit("available", false)
  return
end
emit("available", true)
emit("x", best.world_x)
emit("y", best.world_y)
emit("gap", string.format("%.3f", best_gap or 0))
"""
    deadline = time.monotonic() + 5.0
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = parse_key_values(lua(pipe_name, code))
        if last.get("available") == "true":
            return float(last["x"]), float(last["y"])
        time.sleep(0.25)
    raise VerifyFailure(f"nav grid did not produce a traversable sample on {pipe_name}: {last}")


def distance(ax: float, ay: float, bx: float, by: float) -> float:
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5


def heading_distance(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def query_local_transform(pipe_name: str) -> tuple[float, float, float]:
    values = query(pipe_name)
    return (
        float(values["player.x"]),
        float(values["player.y"]),
        float(values["player.heading"]),
    )


def wait_for_local_transform_settled(
    pipe_name: str,
    timeout: float = 6.0,
    stable_seconds: float = 0.5,
    distance_tolerance: float = 0.75,
    heading_tolerance: float = 0.5,
) -> tuple[float, float, float]:
    deadline = time.monotonic() + timeout
    stable_since: float | None = None
    last = query_local_transform(pipe_name)
    while time.monotonic() < deadline:
        time.sleep(0.1)
        current = query_local_transform(pipe_name)
        position_delta = distance(last[0], last[1], current[0], current[1])
        heading_delta = heading_distance(current[2], last[2])
        if position_delta <= distance_tolerance and heading_delta <= heading_tolerance:
            if stable_since is None:
                stable_since = time.monotonic()
            if time.monotonic() - stable_since >= stable_seconds:
                return current
        else:
            stable_since = None
        last = current
    return last


def wait_for_remote_motion(
    observer_pipe: str,
    participant_id: int,
    previous_x: float,
    previous_y: float,
    expected_heading: float,
    heading_tolerance: float = 0.25,
    timeout: float = 10.0,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    prefix = f"peer.{participant_id}."
    while time.monotonic() < deadline:
        last = query(observer_pipe)
        x = float(last.get(prefix + "x", "nan"))
        y = float(last.get(prefix + "y", "nan"))
        heading = float(last.get(prefix + "heading", "nan"))
        actor_heading = float(last.get(prefix + "actor_heading", "nan"))
        moved_distance = ((x - previous_x) ** 2 + (y - previous_y) ** 2) ** 0.5
        if (
            moved_distance >= 2.0
            and heading_distance(heading, expected_heading) <= heading_tolerance
            and heading_distance(actor_heading, expected_heading) <= heading_tolerance
        ):
            return last
        time.sleep(0.2)
    raise VerifyFailure(
        f"remote participant {participant_id} did not move from {previous_x:.3f},{previous_y:.3f} "
        f"with observed-motion heading {expected_heading:.3f} "
        f"on {observer_pipe}; last={last}"
    )


def wait_for_remote_convergence(
    observer_pipe: str,
    participant_id: int,
    expected_x: float,
    expected_y: float,
    expected_heading: float,
    timeout: float = 10.0,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    prefix = f"peer.{participant_id}."
    while time.monotonic() < deadline:
        last = query(observer_pipe)
        x = float(last.get(prefix + "x", "nan"))
        y = float(last.get(prefix + "y", "nan"))
        heading = float(last.get(prefix + "heading", "nan"))
        actor_heading = float(last.get(prefix + "actor_heading", "nan"))
        if (
            distance(x, y, expected_x, expected_y) <= 3.0
            and heading_distance(heading, expected_heading) <= 1.0
            and heading_distance(actor_heading, expected_heading) <= 1.0
        ):
            return last
        time.sleep(0.15)
    raise VerifyFailure(
        f"remote participant {participant_id} did not settle near "
        f"{expected_x:.3f},{expected_y:.3f} heading {expected_heading:.3f} "
        f"on {observer_pipe}; last={last}"
    )


def wait_for_native_remote_overlap_stability(
    *,
    scene_name: str,
    anchor_pipe: str,
    anchor_id: int,
    anchor_x: float,
    anchor_y: float,
    anchor_heading: float,
    mover_pipe: str,
    mover_peer_id: int,
    mover_x: float,
    mover_y: float,
    mover_heading: float,
    timeout: float = 8.0,
) -> dict[str, object]:
    hold_player_heading(anchor_pipe, anchor_heading)
    hold_player_heading(mover_pipe, mover_heading)
    place_player(anchor_pipe, anchor_x, anchor_y, anchor_heading)
    # Arena collision/nav correction can move the owner immediately after a
    # raw placement. Converge the mirror against the settled owner, then keep
    # the requested mover offset relative to that settled position.
    settled_anchor_x, settled_anchor_y, settled_anchor_heading = (
        wait_for_local_transform_settled(
            anchor_pipe,
            stable_seconds=0.5,
        )
    )
    wait_for_remote_convergence(
        mover_pipe,
        anchor_id,
        settled_anchor_x,
        settled_anchor_y,
        settled_anchor_heading,
        timeout=8.0,
    )
    mover_start = place_player(
        mover_pipe,
        settled_anchor_x + (mover_x - anchor_x),
        settled_anchor_y + (mover_y - anchor_y),
        mover_heading,
    )
    mover_start_xy = (float(mover_start["after.x"]), float(mover_start["after.y"]))
    anchor_on_mover_prefix = f"peer.{mover_peer_id}."
    # The caller passes anchor_id as the anchor's identity and mover_peer_id as
    # the same identity from the mover's point of view. Resolve the mover's id
    # from the two known local test pipes for the reverse observation.
    mover_id = HOST_ID if mover_pipe == HOST_PIPE else CLIENT_ID
    mover_on_anchor_prefix = f"peer.{mover_id}."
    deadline = time.monotonic() + timeout
    stable_since: float | None = None
    last: dict[str, object] = {}
    while time.monotonic() < deadline:
        mover_view = query(mover_pipe)
        anchor_view = query(anchor_pipe)
        if mover_view.get("scene") != scene_name or anchor_view.get("scene") != scene_name:
            stable_since = None
            time.sleep(0.15)
            continue

        mover_player = (float(mover_view["player.x"]), float(mover_view["player.y"]))
        anchor_mirror = (
            float(mover_view.get(anchor_on_mover_prefix + "x", "nan")),
            float(mover_view.get(anchor_on_mover_prefix + "y", "nan")),
        )
        mover_mirror = (
            float(anchor_view.get(mover_on_anchor_prefix + "x", "nan")),
            float(anchor_view.get(mover_on_anchor_prefix + "y", "nan")),
        )
        mover_radius = float(mover_view.get("player.radius", "0") or "0")
        peer_radius = float(mover_view.get(anchor_on_mover_prefix + "radius", "0") or "0")
        overlap_threshold = max(8.0, mover_radius + peer_radius - 1.0)
        mover_drift = distance(*mover_player, *mover_start_xy)
        replicated_delta = distance(*mover_player, *mover_mirror)
        overlap_distance = distance(*mover_player, *anchor_mirror)
        last = {
            "mover_pipe": mover_pipe,
            "settled_anchor": [settled_anchor_x, settled_anchor_y],
            "mover_start": list(mover_start_xy),
            "mover_player": list(mover_player),
            "mover_mirror": list(mover_mirror),
            "anchor_mirror": list(anchor_mirror),
            "mover_drift": mover_drift,
            "replicated_delta": replicated_delta,
            "overlap_distance": overlap_distance,
            "overlap_threshold": overlap_threshold,
        }

        if (
            mover_drift <= 0.75
            and replicated_delta <= 3.0
            and overlap_distance < overlap_threshold
        ):
            if stable_since is None:
                stable_since = time.monotonic()
            elif time.monotonic() - stable_since >= 1.0:
                last["stable_seconds"] = time.monotonic() - stable_since
                return last
        else:
            stable_since = None
        time.sleep(0.15)

    raise VerifyFailure(
        f"local/native-remote overlap did not remain stable and converged on {mover_pipe} "
        f"in {scene_name}; last={last}"
    )


def verify_native_remote_overlap_policy(scene_name: str) -> dict[str, object]:
    host_before = query(HOST_PIPE)
    base_x = float(host_before["player.x"])
    base_y = float(host_before["player.y"])
    client_overlap = wait_for_native_remote_overlap_stability(
        scene_name=scene_name,
        anchor_pipe=HOST_PIPE,
        anchor_id=HOST_ID,
        anchor_x=base_x,
        anchor_y=base_y,
        anchor_heading=90.0,
        mover_pipe=CLIENT_PIPE,
        mover_peer_id=HOST_ID,
        mover_x=base_x + 2.0,
        mover_y=base_y,
        mover_heading=270.0,
    )
    host_overlap = wait_for_native_remote_overlap_stability(
        scene_name=scene_name,
        anchor_pipe=CLIENT_PIPE,
        anchor_id=CLIENT_ID,
        anchor_x=base_x + 160.0,
        anchor_y=base_y,
        anchor_heading=270.0,
        mover_pipe=HOST_PIPE,
        mover_peer_id=CLIENT_ID,
        mover_x=base_x + 162.0,
        mover_y=base_y,
        mover_heading=90.0,
    )
    return {
        "policy": "skip_local_native_remote_push_to_avoid_replication_feedback",
        "client_overlap": client_overlap,
        "host_overlap": host_overlap,
    }


def disable_bots() -> None:
    code = "lua_bots_disable_tick = true; sd.bots.clear(); return tostring(sd.bots.get_count())"

    def disable_one(pipe_name: str) -> str:
        deadline = time.monotonic() + 15.0
        last_error = ""
        last_count = ""
        while time.monotonic() < deadline:
            try:
                last_count = lua(pipe_name, code, timeout=5.0).strip()
                if last_count == "0":
                    return last_count
            except (VerifyFailure, subprocess.TimeoutExpired) as exc:
                last_error = str(exc)
            time.sleep(0.25)
        detail = last_error or last_count
        raise VerifyFailure(f"failed to disable bots on {pipe_name}: {detail!r}")

    host_count = disable_one(HOST_PIPE)
    client_count = disable_one(CLIENT_PIPE)
    if host_count.strip() != "0" or client_count.strip() != "0":
        raise VerifyFailure(f"failed to disable bots: host={host_count!r} client={client_count!r}")


def start_testrun(pipe_name: str) -> None:
    values = parse_key_values(lua(pipe_name, "print('ok=' .. tostring(sd.hub.start_testrun()))"))
    if values.get("ok") != "true":
        raise VerifyFailure(f"failed to start testrun on {pipe_name}: {values}")


def assert_client_start_testrun_blocked() -> dict[str, object]:
    expected = "host-only while connected to a multiplayer session"
    try:
        output = lua(CLIENT_PIPE, "print('ok=' .. tostring(sd.hub.start_testrun()))")
    except VerifyFailure as exc:
        if expected not in str(exc):
            raise VerifyFailure(f"client start_testrun failed for an unexpected reason: {exc}") from exc
        scene = lua(
            CLIENT_PIPE,
            "local s=sd.world.get_scene(); return tostring(s and (s.name or s.kind) or '')",
        ).strip()
        if scene != "hub":
            raise VerifyFailure(f"client start_testrun block left client in unexpected scene {scene!r}")
        return {
            "blocked": True,
            "expected_error": expected,
            "scene": scene,
        }
    raise VerifyFailure(f"client unexpectedly started testrun directly: {output!r}")


def wait_for_scene(pipe_name: str, scene_name: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    last = ""
    last_error = ""
    while time.monotonic() < deadline:
        try:
            last = lua(
                pipe_name,
                "local s=sd.world.get_scene(); return tostring(s and (s.name or s.kind) or '')",
                timeout=5.0,
            ).strip()
            last_error = ""
        except (VerifyFailure, subprocess.TimeoutExpired) as exc:
            last_error = str(exc)
            time.sleep(0.25)
            continue
        if last == scene_name:
            return
        time.sleep(0.25)
    suffix = f"; last_error={last_error}" if last_error else ""
    raise VerifyFailure(f"{pipe_name} did not reach scene {scene_name}; last={last}{suffix}")


def wait_for_both_hub_settled(settle_seconds: float = 3.0, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    settled_since: float | None = None
    last_host = ""
    last_client = ""
    while time.monotonic() < deadline:
        try:
            last_host = lua(
                HOST_PIPE,
                "local s=sd.world.get_scene(); return tostring(s and (s.name or s.kind) or '')",
                timeout=5.0,
            ).strip()
            last_client = lua(
                CLIENT_PIPE,
                "local s=sd.world.get_scene(); return tostring(s and (s.name or s.kind) or '')",
                timeout=5.0,
            ).strip()
        except (VerifyFailure, subprocess.TimeoutExpired):
            settled_since = None
            time.sleep(0.25)
            continue
        now = time.monotonic()
        if last_host == "" or last_client == "":
            time.sleep(0.25)
            continue
        if last_host == "hub" and last_client == "hub":
            if settled_since is None:
                settled_since = now
            elif now - settled_since >= settle_seconds:
                return
        else:
            settled_since = None
        time.sleep(0.25)
    raise VerifyFailure(
        f"instances did not remain hub-settled before run entry; host={last_host!r} client={last_client!r}"
    )


def start_host_testrun_and_wait_for_clients(timeout: float = 30.0) -> dict[str, object]:
    wait_for_both_hub_settled(timeout=max(15.0, timeout))
    # Spawn readiness keeps its own scene-identity stability window. The first
    # request after a fresh create->hub transition intentionally initializes
    # that window and returns a transient error, even if the semantic scene has
    # already read as hub for several seconds. Retry rejected requests; a
    # successful request is queued exactly once and exits this loop.
    start_deadline = time.monotonic() + timeout
    last_start_error = ""
    while time.monotonic() < start_deadline:
        try:
            start_testrun(HOST_PIPE)
            break
        except (VerifyFailure, subprocess.TimeoutExpired) as exc:
            last_start_error = str(exc)
            time.sleep(0.25)
    else:
        raise VerifyFailure(
            "host testrun request never reached spawn readiness: "
            f"{last_start_error}"
        )
    wait_for_scene(HOST_PIPE, "testrun", timeout=timeout)
    wait_for_scene(CLIENT_PIPE, "testrun", timeout=timeout)
    return {
        "host_started": True,
        "client_followed_host": True,
        "scene": "testrun",
    }


def verify_run_entry_bootstrap(timeout: float = 15.0) -> dict[str, object]:
    wait_for_remote(HOST_PIPE, CLIENT_ID, CLIENT_NAME, "testrun")
    wait_for_remote(CLIENT_PIPE, HOST_ID, HOST_NAME, "testrun")

    deadline = time.monotonic() + timeout
    last: dict[str, object] = {}
    while time.monotonic() < deadline:
        host = query(HOST_PIPE)
        client = query(CLIENT_PIPE)
        host_x = float(host["player.x"])
        host_y = float(host["player.y"])
        client_x = float(client["player.x"])
        client_y = float(client["player.y"])
        host_client_spawn_distance = distance(host_x, host_y, client_x, client_y)
        host_observed_client_distance = distance(
            float(host[f"peer.{CLIENT_ID}.x"]),
            float(host[f"peer.{CLIENT_ID}.y"]),
            client_x,
            client_y,
        )
        client_observed_host_distance = distance(
            float(client[f"peer.{HOST_ID}.x"]),
            float(client[f"peer.{HOST_ID}.y"]),
            host_x,
            host_y,
        )
        client_replicated_scene_kind = client.get("replicated.scene_kind", "")
        last = {
            "host_player": [host_x, host_y],
            "client_player": [client_x, client_y],
            "host_client_spawn_distance": host_client_spawn_distance,
            "host_observed_client_distance": host_observed_client_distance,
            "client_observed_host_distance": client_observed_host_distance,
            "client_replicated_scene_kind": client_replicated_scene_kind,
            "client_replicated_actor_count": parse_int_text(client.get("replicated.actor_count")),
            "client_replicated_actor_total_count": parse_int_text(client.get("replicated.actor_total_count")),
            "client_replicated_authority_participant_id": parse_int_text(client.get("replicated.authority_participant_id")),
        }
        if (
            host.get("scene") == "testrun"
            and client.get("scene") == "testrun"
            and client_replicated_scene_kind == "Run"
            and host_client_spawn_distance <= 112.0
            and host_observed_client_distance <= 32.0
            and client_observed_host_distance <= 32.0
        ):
            return last
        time.sleep(0.25)

    raise VerifyFailure(f"run entry bootstrap did not converge; last={last}")


def verify_scene(scene_name: str) -> dict[str, object]:
    host_seen = wait_for_remote(HOST_PIPE, CLIENT_ID, CLIENT_NAME, scene_name)
    client_seen = wait_for_remote(CLIENT_PIPE, HOST_ID, HOST_NAME, scene_name)
    host_source_staff_visual_state = int(
        float(host_seen.get("player.staff_visual_state", "0") or "0"))
    client_source_staff_visual_state = int(
        float(client_seen.get("player.staff_visual_state", "0") or "0"))
    host_remote_staff_visual_state = int(
        float(host_seen.get(f"peer.{CLIENT_ID}.staff_visual_state", "0") or "0"))
    client_remote_staff_visual_state = int(
        float(client_seen.get(f"peer.{HOST_ID}.staff_visual_state", "0") or "0"))
    # Staff attachment +0x84 is native-owned and can contain process-local data
    # in run scenes. Keep it in the report for diagnosis, but do not require
    # cross-client equality.
    host_source_selector = host_seen.get("player.render_selector", "")
    client_source_selector = client_seen.get("player.render_selector", "")
    host_remote_selector = host_seen.get(f"peer.{CLIENT_ID}.render_selector", "")
    client_remote_selector = client_seen.get(f"peer.{HOST_ID}.render_selector", "")
    remote_selector_checks = (
        ("host remote", host_seen, CLIENT_ID, host_remote_selector),
        ("client remote", client_seen, HOST_ID, client_remote_selector),
    )
    for label, values, participant_id, selector_text in remote_selector_checks:
        element_id = parse_int_text(
            values.get(f"peer.{participant_id}.element_id"), -1)
        expected_selection = REMOTE_RENDER_SELECTION_BY_ELEMENT.get(element_id)
        try:
            selector_parts = [int(part, 0) for part in selector_text.split(",")]
        except ValueError:
            selector_parts = []
        if (
            expected_selection is None or
            len(selector_parts) != 5 or
            selector_parts[3] != expected_selection
        ):
            raise VerifyFailure(
                f"{label} did not preserve its profile-built render selection: "
                f"element={element_id} expected={expected_selection} "
                f"selector={selector_text!r}")
    client_source_visual_blocks = visual_blocks_by_type(client_seen, "player")
    host_source_visual_blocks = visual_blocks_by_type(host_seen, "player")
    host_remote_visual_blocks = visual_blocks_by_type(host_seen, f"peer.{CLIENT_ID}")
    client_remote_visual_blocks = visual_blocks_by_type(client_seen, f"peer.{HOST_ID}")
    remote_visual_lane_checks = (
        ("host remote", host_seen, CLIENT_ID),
        ("client remote", client_seen, HOST_ID),
    )
    for label, values, participant_id in remote_visual_lane_checks:
        primary_type = parse_int_text(
            values.get(f"peer.{participant_id}.primary_visual_type"), 0)
        secondary_type = parse_int_text(
            values.get(f"peer.{participant_id}.secondary_visual_type"), 0)
        if (
            primary_type != REMOTE_PRIMARY_VISUAL_TYPE_ID or
            secondary_type != REMOTE_SECONDARY_VISUAL_TYPE_ID
        ):
            raise VerifyFailure(
                f"{label} actor-owned helper lane mismatch: "
                f"primary=0x{primary_type:04X} secondary=0x{secondary_type:04X}")
    for type_id, source_block in client_source_visual_blocks.items():
        remote_block = host_remote_visual_blocks.get(type_id, "")
        if remote_block != source_block:
            raise VerifyFailure(
                "host remote visual-link block does not mirror client source: "
                f"type=0x{type_id:04X} remote={remote_block!r} source={source_block!r}")
    for type_id, source_block in host_source_visual_blocks.items():
        remote_block = client_remote_visual_blocks.get(type_id, "")
        if remote_block != source_block:
            raise VerifyFailure(
                "client remote visual-link block does not mirror host source: "
                f"type=0x{type_id:04X} remote={remote_block!r} source={source_block!r}")

    host_player_before = query(HOST_PIPE)
    base_x = float(host_player_before["player.x"])
    base_y = float(host_player_before["player.y"])
    host_place_x, host_place_y = snap_to_nav(HOST_PIPE, base_x - 120.0, base_y)
    client_place_x, client_place_y = snap_to_nav(HOST_PIPE, base_x + 120.0, base_y)
    hold_player_heading(HOST_PIPE, 90.0)
    hold_player_heading(CLIENT_PIPE, 270.0)
    host_place = place_player(HOST_PIPE, host_place_x, host_place_y, 90.0)
    client_place = place_player(CLIENT_PIPE, client_place_x, client_place_y, 270.0)
    host_idle_x, host_idle_y, host_idle_heading = wait_for_local_transform_settled(HOST_PIPE)
    client_idle_x, client_idle_y, client_idle_heading = wait_for_local_transform_settled(CLIENT_PIPE)
    # Settling the second process can overlap a late run-entry placement or
    # native collision correction in the first.  Refresh the owner's actual
    # transform immediately before asking its observer to converge; otherwise
    # the verifier can compare a correct mirror against a stale pre-correction
    # coordinate captured several seconds earlier.
    host_idle_x, host_idle_y, host_idle_heading = wait_for_local_transform_settled(
        HOST_PIPE,
        stable_seconds=0.75,
    )
    client_seen = wait_for_remote_convergence(
        CLIENT_PIPE,
        HOST_ID,
        host_idle_x,
        host_idle_y,
        host_idle_heading,
        timeout=12.0,
    )
    client_idle_x, client_idle_y, client_idle_heading = wait_for_local_transform_settled(
        CLIENT_PIPE,
        stable_seconds=0.75,
    )
    host_seen = wait_for_remote_convergence(
        HOST_PIPE,
        CLIENT_ID,
        client_idle_x,
        client_idle_y,
        client_idle_heading,
        timeout=12.0,
    )

    host_observed_client_before = (
        float(host_seen[f"peer.{CLIENT_ID}.x"]),
        float(host_seen[f"peer.{CLIENT_ID}.y"]),
    )
    client_observed_host_before = (
        float(client_seen[f"peer.{HOST_ID}.x"]),
        float(client_seen[f"peer.{HOST_ID}.y"]),
    )

    hold_player_heading(HOST_PIPE, 135.0)
    host_move = nudge_player(HOST_PIPE, 90.0, 0.0, 135.0)
    time.sleep(0.2)
    host_x, host_y, host_heading = wait_for_local_transform_settled(HOST_PIPE, stable_seconds=0.25)
    client_after_host_move = wait_for_remote_motion(
        CLIENT_PIPE,
        HOST_ID,
        client_observed_host_before[0],
        client_observed_host_before[1],
        host_heading,
    )
    client_after_host_settled = wait_for_remote_convergence(
        CLIENT_PIPE,
        HOST_ID,
        host_x,
        host_y,
        host_heading,
    )

    hold_player_heading(CLIENT_PIPE, 225.0)
    client_move = nudge_player(CLIENT_PIPE, -70.0, 30.0, 225.0)
    time.sleep(0.2)
    client_x, client_y, client_heading = wait_for_local_transform_settled(CLIENT_PIPE, stable_seconds=0.25)
    host_after_client_move = wait_for_remote_motion(
        HOST_PIPE,
        CLIENT_ID,
        host_observed_client_before[0],
        host_observed_client_before[1],
        client_heading,
    )
    host_after_client_settled = wait_for_remote_convergence(
        HOST_PIPE,
        CLIENT_ID,
        client_x,
        client_y,
        client_heading,
    )
    participant_overlap = verify_native_remote_overlap_policy(scene_name)
    heading_hold_release = {
        "host": hold_player_heading(HOST_PIPE, None),
        "client": hold_player_heading(CLIENT_PIPE, None),
    }

    return {
        "scene": scene_name,
        "host_remote_name": host_seen[f"peer.{CLIENT_ID}.name"],
        "host_remote_nameplate": host_seen[f"peer.{CLIENT_ID}.nameplate"],
        "host_remote_staff_visual_state": f"0x{host_remote_staff_visual_state:08X}",
        "client_source_staff_visual_state": f"0x{client_source_staff_visual_state:08X}",
        "host_remote_render_selector": host_remote_selector,
        "client_source_render_selector": client_source_selector,
        "host_remote_visual_link_types": sorted(host_remote_visual_blocks),
        "host_remote_visual_lane_types": {
            "primary": parse_int_text(
                host_seen.get(f"peer.{CLIENT_ID}.primary_visual_type"), 0),
            "secondary": parse_int_text(
                host_seen.get(f"peer.{CLIENT_ID}.secondary_visual_type"), 0),
        },
        "client_remote_name": client_seen[f"peer.{HOST_ID}.name"],
        "client_remote_nameplate": client_seen[f"peer.{HOST_ID}.nameplate"],
        "client_remote_staff_visual_state": f"0x{client_remote_staff_visual_state:08X}",
        "host_source_staff_visual_state": f"0x{host_source_staff_visual_state:08X}",
        "client_remote_render_selector": client_remote_selector,
        "host_source_render_selector": host_source_selector,
        "client_remote_visual_link_types": sorted(client_remote_visual_blocks),
        "client_remote_visual_lane_types": {
            "primary": parse_int_text(
                client_seen.get(f"peer.{HOST_ID}.primary_visual_type"), 0),
            "secondary": parse_int_text(
                client_seen.get(f"peer.{HOST_ID}.secondary_visual_type"), 0),
        },
        "host_moved_to": [host_x, host_y],
        "client_observed_host_before": list(client_observed_host_before),
        "client_observed_host_at": [
            float(client_after_host_move[f"peer.{HOST_ID}.x"]),
            float(client_after_host_move[f"peer.{HOST_ID}.y"]),
        ],
        "client_observed_host_settled": [
            float(client_after_host_settled[f"peer.{HOST_ID}.x"]),
            float(client_after_host_settled[f"peer.{HOST_ID}.y"]),
        ],
        "client_observed_host_heading": float(client_after_host_move[f"peer.{HOST_ID}.heading"]),
        "client_moved_to": [client_x, client_y],
        "host_observed_client_before": list(host_observed_client_before),
        "host_observed_client_at": [
            float(host_after_client_move[f"peer.{CLIENT_ID}.x"]),
            float(host_after_client_move[f"peer.{CLIENT_ID}.y"]),
        ],
        "host_observed_client_settled": [
            float(host_after_client_settled[f"peer.{CLIENT_ID}.x"]),
            float(host_after_client_settled[f"peer.{CLIENT_ID}.y"]),
        ],
        "host_observed_client_heading": float(host_after_client_move[f"peer.{CLIENT_ID}.heading"]),
        "participant_overlap": participant_overlap,
        "heading_hold_release": heading_hold_release,
    }


def main() -> int:
    result: dict[str, object] = {"ok": False, "checks": []}
    try:
        stop_games()
        result["launch"] = launch_pair()
        disable_bots()
        result["checks"].append(verify_scene("hub"))

        result["client_start_blocked"] = assert_client_start_testrun_blocked()
        result["host_run_entry"] = start_host_testrun_and_wait_for_clients()
        result["run_entry_bootstrap"] = verify_run_entry_bootstrap()
        result["checks"].append(verify_scene("testrun"))

        result["ok"] = True
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        result["error"] = str(exc)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 1
    finally:
        stop_games()


if __name__ == "__main__":
    sys.exit(main())
