#!/usr/bin/env python3
"""Verify exact lobby session-state transitions in the real Steam status file."""

from __future__ import annotations

import argparse
import json
import ntpath
import os
import re
import select
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from verify_game_over_session_semantics import (
    ACCEPTANCE_MOD_ID,
    _query_process_executable,
    _start_testrun_when_ready,
    _windows_path_equal,
    stop_owned_processes,
)
from verify_local_multiplayer_sync import (
    VerifyFailure,
    extract_json,
    path_for_powershell,
)


ROOT = Path(__file__).resolve().parents[1]
INSTANCE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,47}$")
EXPECTED_STATES = ("not-in-game", "in-hub", "in-boneyard")


def _export_to_windows_environment(
    environment: dict[str, str],
    variable_names: tuple[str, ...],
) -> None:
    entries = [
        entry
        for entry in environment.get("WSLENV", "").split(":")
        if entry
    ]
    exported_names = {
        entry.split("/", 1)[0]
        for entry in entries
    }
    for variable_name in variable_names:
        if variable_name not in exported_names:
            entries.append(variable_name)
            exported_names.add(variable_name)
    environment["WSLENV"] = ":".join(entries)


def _write_result(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _prepare_acceptance_mod_state(
    runtime_root: Path,
    instance: str,
) -> Path:
    state_path = (
        runtime_root
        / "instances"
        / instance.lower()
        / "mod-manager-state.json"
    )
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "Mods": {
                    ACCEPTANCE_MOD_ID: {
                        "Enabled": True,
                    },
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return state_path


def _read_status(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _append_transition(
    transitions: list[dict[str, Any]],
    status: dict[str, Any],
) -> None:
    state = status.get("sessionState")
    if state not in EXPECTED_STATES:
        raise VerifyFailure(
            f"session status published an invalid sessionState: {state!r}"
        )
    if transitions and transitions[-1]["sessionState"] == state:
        return
    transitions.append(
        {
            "observedAtUnixMs": int(time.time() * 1000),
            "sessionState": state,
            "status": status,
        }
    )


def _wait_for_status(
    path: Path,
    transitions: list[dict[str, Any]],
    predicate: Callable[[dict[str, Any]], bool],
    *,
    timeout: float,
    description: str,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        status = _read_status(path)
        if status is not None:
            last = status
            _append_transition(transitions, status)
            if predicate(status):
                return status
        time.sleep(0.05)
    raise VerifyFailure(
        f"timed out waiting for {description}; last={last}"
    )


def _wait_for_launcher_json(
    process: subprocess.Popen[str],
    status_path: Path,
    transitions: list[dict[str, Any]],
    *,
    timeout: float,
) -> dict[str, Any]:
    assert process.stdout is not None
    deadline = time.monotonic() + timeout
    output = ""
    while time.monotonic() < deadline:
        status = _read_status(status_path)
        if status is not None:
            _append_transition(transitions, status)

        ready, _, _ = select.select([process.stdout], [], [], 0.05)
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
    raise VerifyFailure(
        "launcher did not return structured launch ownership within "
        f"{timeout:.0f}s:\n{output}"
    )


def _query_exact_process_ids(expected_executable: str) -> list[int]:
    escaped = expected_executable.replace("'", "''")
    command = (
        f"$expected='{escaped}'; "
        "$ids=Get-CimInstance Win32_Process | "
        "Where-Object { $_.ExecutablePath -and "
        "[string]::Equals($_.ExecutablePath,$expected,"
        "[System.StringComparison]::OrdinalIgnoreCase) } | "
        "ForEach-Object { [int]$_.ProcessId }; "
        "[Console]::Write(($ids | ConvertTo-Json -Compress))"
    )
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            command,
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
            "could not resolve exact staged process ownership: "
            f"{completed.stderr.strip() or completed.stdout.strip()}"
        )
    raw = completed.stdout.strip().lstrip("\ufeff")
    if not raw or raw == "null":
        return []
    value = json.loads(raw)
    if isinstance(value, int):
        return [value]
    if isinstance(value, list) and all(
        isinstance(process_id, int) for process_id in value
    ):
        return value
    raise VerifyFailure(
        f"invalid exact staged process query response: {value!r}"
    )


def _validate_transition_sequence(
    transitions: list[dict[str, Any]],
) -> None:
    observed = [
        transition["sessionState"]
        for transition in transitions
    ]
    cursor = 0
    for state in observed:
        if cursor < len(EXPECTED_STATES) and state == EXPECTED_STATES[cursor]:
            cursor += 1
    if cursor != len(EXPECTED_STATES):
        raise VerifyFailure(
            "session status did not publish the required ordered "
            f"transition {EXPECTED_STATES}: observed={observed}"
        )
    for transition in transitions:
        members = transition["status"].get("members")
        if not isinstance(members, list) or not members:
            raise VerifyFailure(
                "session status transition omitted lobby members[]: "
                f"{transition}"
            )


def run_verification(
    *,
    launcher_path: Path,
    game_directory: Path,
    runtime_root: Path,
    instance: str,
) -> dict[str, Any]:
    if not INSTANCE_PATTERN.fullmatch(instance):
        raise VerifyFailure(f"invalid isolated instance name: {instance!r}")

    runtime_root.mkdir(parents=True, exist_ok=True)
    acceptance_mod_state_path = _prepare_acceptance_mod_state(
        runtime_root,
        instance,
    )
    status_path = (
        runtime_root
        / "instances"
        / instance.lower()
        / "stage"
        / ".sdmod"
        / "multiplayer-session-status.json"
    )
    runtime_root_windows = path_for_powershell(runtime_root)
    expected_executable = ntpath.join(
        runtime_root_windows,
        "instances",
        instance.lower(),
        "stage",
        "SolomonDark.exe",
    )
    pipe_name = f"SolomonDarkModLoader_LuaExec_{instance}"
    environment = os.environ.copy()
    environment.update(
        {
            "SDMOD_UI_SANDBOX_PRESET": "map_create_fire_mind_hub",
            "SDMOD_LUA_EXEC_PIPE_NAME": pipe_name,
            "SDMOD_MULTIPLAYER_QUICK_START": "1",
            "SDMOD_MULTIPLAYER_QUICK_START_ELEMENT": "fire",
            "SDMOD_MULTIPLAYER_QUICK_START_DISCIPLINE": "mind",
        }
    )
    _export_to_windows_environment(
        environment,
        (
            "SDMOD_UI_SANDBOX_PRESET",
            "SDMOD_LUA_EXEC_PIPE_NAME",
            "SDMOD_MULTIPLAYER_QUICK_START",
            "SDMOD_MULTIPLAYER_QUICK_START_ELEMENT",
            "SDMOD_MULTIPLAYER_QUICK_START_DISCIPLINE",
        ),
    )
    arguments = [
        str(launcher_path.resolve()),
        "--json",
        "launch",
        "--instance",
        instance,
        "--runtime-root",
        runtime_root_windows,
        "--game-dir",
        path_for_powershell(game_directory),
        "--fresh-install",
        "--disable-audio",
        "--multiplayer",
        "host",
        "--lobby-privacy",
        "friends",
        "--no-invite-dialog",
    ]
    process = subprocess.Popen(
        arguments,
        cwd=launcher_path.resolve().parent,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
    )
    transitions: list[dict[str, Any]] = []
    owned: dict[int, str] = {}
    result: dict[str, Any] = {
        "ok": False,
        "instance": instance,
        "runtimeRoot": str(runtime_root),
        "statusPath": str(status_path),
        "acceptanceModId": ACCEPTANCE_MOD_ID,
        "acceptanceModStatePath": str(acceptance_mod_state_path),
        "expectedExecutable": expected_executable,
        "transitions": transitions,
    }
    try:
        launch_response = _wait_for_launcher_json(
            process,
            status_path,
            transitions,
            timeout=60.0,
        )
        launch = launch_response.get("launch")
        stage = launch_response.get("stage")
        if not isinstance(launch, dict) or not isinstance(stage, dict):
            raise VerifyFailure(
                "launcher response omitted stage or launch ownership: "
                f"{launch_response}"
            )
        process_id = int(launch.get("processId", 0))
        executable = str(stage.get("stageExecutablePath", ""))
        if (
            process_id <= 0
            or not executable
            or not _windows_path_equal(
                executable,
                expected_executable,
            )
        ):
            raise VerifyFailure(
                f"launcher reported unexpected process ownership: {launch}"
            )
        actual = _query_process_executable(process_id)
        if (
            actual is None
            or not _windows_path_equal(
                actual,
                expected_executable,
            )
        ):
            raise VerifyFailure(
                f"exact staged process was not alive: pid={process_id} "
                f"actual={actual!r}"
            )
        owned[process_id] = expected_executable
        result["stage"] = stage
        result["launch"] = launch

        hub = _wait_for_status(
            status_path,
            transitions,
            lambda status: (
                status.get("sessionState") == "in-hub"
                and status.get("isHost") is True
                and int(status.get("lobbyId", 0)) > 0
            ),
            timeout=45.0,
            description="Steam host in-hub status",
        )
        result["hub"] = hub
        _start_testrun_when_ready(pipe_name)
        result["startTestrun"] = {
            "ok": True,
            "boundedNativeReadinessRetry": True,
        }
        boneyard = _wait_for_status(
            status_path,
            transitions,
            lambda status: (
                status.get("sessionState") == "in-boneyard"
                and status.get("gamePhase") in ("loading", "session")
            ),
            timeout=45.0,
            description="Steam host in-boneyard status",
        )
        result["boneyard"] = boneyard
        _validate_transition_sequence(transitions)
        final_executable = _query_process_executable(process_id)
        result["processIdentityStable"] = (
            final_executable is not None
            and _windows_path_equal(
                final_executable,
                expected_executable,
            )
        )
        if not result["processIdentityStable"]:
            raise VerifyFailure(
                "Steam host process identity changed during transition gate"
            )
        result["ok"] = True
        return result
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3.0)
        for process_id in _query_exact_process_ids(
            expected_executable
        ):
            owned[process_id] = expected_executable
        stop_owned_processes(owned)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--launcher-path", type=Path, required=True)
    parser.add_argument("--game-dir", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--instance", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    result: dict[str, Any]
    try:
        result = run_verification(
            launcher_path=args.launcher_path,
            game_directory=args.game_dir,
            runtime_root=args.runtime_root,
            instance=args.instance,
        )
        exit_code = 0
    except Exception as exc:  # noqa: BLE001 - persist exact live failure.
        result = {
            "ok": False,
            "instance": args.instance,
            "error": str(exc),
        }
        exit_code = 1
    _write_result(args.output, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
