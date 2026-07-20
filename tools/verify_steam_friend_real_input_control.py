#!/usr/bin/env python3
"""Verify stock keyboard ownership on an active Windows/Proton Steam pair."""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import verify_local_multiplayer_sync as local_sync
import verify_multiplayer_rush_behavior_sync as rush
from steam_friend_active_pair import (
    CLIENT_ENDPOINT,
    HOST_ENDPOINT,
    ROOT,
    SteamFriendActivePair,
)
from steam_friend_hub_automation import (
    hold_proton_key,
    proton_input_process_id,
)
from verify_local_multiplayer_sync import VerifyFailure, path_for_powershell
from verify_steam_friend_active_pair_state import configure_modules


DEFAULT_OUTPUT = ROOT / "runtime/steam_friend_real_input_control.json"
KEY_HOLD_MS = 1800
MINIMUM_DISPLACEMENT = 20.0
MAXIMUM_BYSTANDER_DRIFT = 2.0
MAXIMUM_HEADING_VARIATION = 1.0
HEADING_SAMPLE_SECONDS = 2.0
MOVE_START = (975.0, 375.0, 0.0)
BYSTANDER_START = (1275.0, 375.0, 180.0)


@dataclass(frozen=True)
class Direction:
    label: str
    participant_id: int
    owner_endpoint: str
    observer_endpoint: str
    input_window_pid: int
    input_window_kind: str


def windows_process_id(instance: str) -> int:
    executable = (
        ROOT
        / "runtime/instances"
        / instance
        / "stage/SolomonDark.exe"
    ).resolve()
    if not executable.is_file():
        raise VerifyFailure(
            f"Windows game executable is missing for {instance}: {executable}"
        )
    windows_executable = path_for_powershell(executable)
    quoted_executable = "'" + windows_executable.replace("'", "''") + "'"
    command = (
        f"$path={quoted_executable}; "
        "$matches=@(Get-CimInstance Win32_Process | Where-Object { "
        "$_.Name -eq 'SolomonDark.exe' -and "
        "[string]::Equals([string]$_.ExecutablePath,$path," 
        "[System.StringComparison]::OrdinalIgnoreCase) }); "
        "if ($matches.Count -ne 1) { exit 1 }; $matches[0].ProcessId"
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        cwd=ROOT,
        env=os.environ.copy(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=10.0,
        check=False,
    )
    if completed.returncode != 0 or not completed.stdout.strip().isdigit():
        raise VerifyFailure(
            f"could not resolve the Windows game process for {instance}"
        )
    return int(completed.stdout.strip())


def local_transform(endpoint: str) -> tuple[float, float, float]:
    values = local_sync.query(endpoint)
    return (
        float(values["player.x"]),
        float(values["player.y"]),
        float(values["player.heading"]),
    )


def heading_distance(left: float, right: float) -> float:
    return abs((left - right + 180.0) % 360.0 - 180.0)


def hold_direction_key(
    direction: Direction,
    key: str,
    hold_ms: int,
    timeout: float,
) -> str:
    if direction.input_window_kind == "windows":
        return rush.hold_real_key(
            direction.input_window_pid,
            key,
            hold_ms,
            timeout,
        )
    if direction.input_window_kind == "proton":
        return hold_proton_key(
            direction.input_window_pid,
            key,
            hold_ms,
            timeout,
        )
    raise VerifyFailure(
        f"unknown input-window kind: {direction.input_window_kind}"
    )


def sample_heading_stability(
    direction: Direction, timeout: float = HEADING_SAMPLE_SECONDS
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    local_headings: list[float] = []
    local_actor_headings: list[float] = []
    remote_headings: list[float] = []
    remote_actor_headings: list[float] = []
    prefix = f"peer.{direction.participant_id}."
    while time.monotonic() < deadline:
        owner = local_sync.query(direction.owner_endpoint)
        observer = local_sync.query(direction.observer_endpoint)
        local_headings.append(float(owner["player.heading"]))
        local_actor_headings.append(float(owner["player.actor_heading"]))
        remote_headings.append(float(observer[prefix + "heading"]))
        remote_actor_headings.append(float(observer[prefix + "actor_heading"]))
        time.sleep(0.1)

    def variation(values: list[float]) -> float:
        return max(heading_distance(value, values[0]) for value in values)

    local_variation = variation(local_headings)
    local_actor_variation = variation(local_actor_headings)
    remote_variation = variation(remote_headings)
    remote_actor_variation = variation(remote_actor_headings)
    mirror_error = max(
        heading_distance(local_heading, remote_heading)
        for local_heading, remote_heading in zip(local_headings, remote_headings)
    )
    actor_mirror_error = max(
        heading_distance(local_heading, remote_heading)
        for local_heading, remote_heading in zip(
            local_actor_headings, remote_actor_headings
        )
    )
    maximum = max(
        local_variation,
        local_actor_variation,
        remote_variation,
        remote_actor_variation,
        mirror_error,
        actor_mirror_error,
    )
    if maximum > MAXIMUM_HEADING_VARIATION:
        raise VerifyFailure(
            f"{direction.label} heading wandered after input release: max={maximum}"
        )
    return {
        "samples": len(local_headings),
        "local_variation": local_variation,
        "local_actor_variation": local_actor_variation,
        "remote_variation": remote_variation,
        "remote_actor_variation": remote_actor_variation,
        "mirror_error": mirror_error,
        "actor_mirror_error": actor_mirror_error,
    }


def run_direction(direction: Direction, timeout: float) -> dict[str, Any]:
    local_sync.place_player(
        direction.observer_endpoint,
        *BYSTANDER_START,
    )
    local_sync.place_player(
        direction.owner_endpoint,
        *MOVE_START,
    )
    start_x, start_y, start_heading = local_sync.wait_for_local_transform_settled(
        direction.owner_endpoint,
        timeout=min(timeout, 10.0),
        stable_seconds=0.5,
    )
    other_before = local_transform(direction.observer_endpoint)
    local_sync.wait_for_remote_convergence(
        direction.observer_endpoint,
        direction.participant_id,
        start_x,
        start_y,
        start_heading,
        timeout=timeout,
    )

    armed = False
    try:
        monitor_start = rush.arm_keyboard_movement_monitor(
            direction.owner_endpoint
        )
        armed = True
        key_output = hold_direction_key(
            direction,
            "d",
            KEY_HOLD_MS,
            timeout,
        )
        monitor = rush.finish_keyboard_movement_monitor(
            direction.owner_endpoint
        )
        armed = False
    finally:
        if armed:
            try:
                rush.finish_keyboard_movement_monitor(direction.owner_endpoint)
            except Exception:
                pass

    final_x, final_y, final_heading = local_sync.wait_for_local_transform_settled(
        direction.owner_endpoint,
        timeout=min(timeout, 10.0),
        stable_seconds=0.7,
    )
    observer = local_sync.wait_for_remote_convergence(
        direction.observer_endpoint,
        direction.participant_id,
        final_x,
        final_y,
        final_heading,
        timeout=timeout,
    )
    other_after = local_transform(direction.observer_endpoint)
    displacement = math.hypot(final_x - start_x, final_y - start_y)
    bystander_drift = math.hypot(
        other_after[0] - other_before[0], other_after[1] - other_before[1]
    )
    if displacement < MINIMUM_DISPLACEMENT:
        raise VerifyFailure(
            f"{direction.label} stock keyboard displacement was too small: "
            f"{displacement}"
        )
    if bystander_drift > MAXIMUM_BYSTANDER_DRIFT:
        raise VerifyFailure(
            f"{direction.label} input moved the non-owning participant: "
            f"drift={bystander_drift}"
        )
    peak_input = float(monitor["peak_input"])
    peak_step = float(monitor["peak_position_step"])
    if int(monitor["input_frames"]) <= 0 or peak_input <= 0.01 or peak_step <= 0.01:
        raise VerifyFailure(
            f"{direction.label} did not traverse the stock movement path: {monitor}"
        )

    prefix = f"peer.{direction.participant_id}."
    observer_error = math.hypot(
        float(observer[prefix + "x"]) - final_x,
        float(observer[prefix + "y"]) - final_y,
    )
    return {
        "input_window_kind": direction.input_window_kind,
        "input_window_pid": direction.input_window_pid,
        "input_method": "Windows SendInput scancode through the focused game window",
        "key": "d",
        "hold_ms": KEY_HOLD_MS,
        "helper": key_output,
        "monitor_start": monitor_start,
        "monitor": {
            "samples": int(monitor["samples"]),
            "input_frames": int(monitor["input_frames"]),
            "peak_input": peak_input,
            "peak_control": float(monitor["peak_control"]),
            "peak_accumulator_speed": float(monitor["peak_accumulator_speed"]),
            "peak_position_step": peak_step,
        },
        "start": [start_x, start_y, start_heading],
        "final": [final_x, final_y, final_heading],
        "displacement": displacement,
        "bystander_drift": bystander_drift,
        "observer_position_error": observer_error,
        "heading_stability": sample_heading_stability(direction),
    }


def run(scene: str, timeout: float) -> dict[str, Any]:
    host_instance = os.environ.get(
        "SDMOD_STEAM_HOST_INSTANCE", "steam-host-gameplay12"
    )
    pair = SteamFriendActivePair()
    try:
        pair_state = pair.discover()
        names = configure_modules(pair)
        rush.lua = pair.lua
        host_scene = local_sync.query(HOST_ENDPOINT).get("scene")
        client_scene = local_sync.query(CLIENT_ENDPOINT).get("scene")
        if host_scene != scene or client_scene != scene:
            raise VerifyFailure(
                f"Steam friend pair is not in {scene}: "
                f"windows={host_scene} proton={client_scene}"
            )

        directions = (
            Direction(
                "windows_owner",
                pair.host_participant_id,
                HOST_ENDPOINT,
                CLIENT_ENDPOINT,
                windows_process_id(host_instance),
                "windows",
            ),
            Direction(
                "proton_owner",
                pair.client_participant_id,
                CLIENT_ENDPOINT,
                HOST_ENDPOINT,
                proton_input_process_id(),
                "proton",
            ),
        )
        trials = {
            direction.label: run_direction(direction, timeout)
            for direction in directions
        }
        result: dict[str, Any] = {
            "ok": True,
            "pair": pair_state,
            "scene": scene,
            "names_available": {key: bool(value) for key, value in names.items()},
            "trials": trials,
            "summary": {
                "stock_keyboard_owners_tested": 2,
                "windows_owner_moved": True,
                "proton_owner_moved": True,
                "cross_control_events": 0,
                "post_release_heading_wander": False,
                "observer_convergence": True,
            },
        }
        return pair.redact(result)
    finally:
        pair.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", choices=("hub", "testrun"), required=True)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    result: dict[str, Any] = {"ok": False}
    try:
        result = run(args.scene, args.timeout)
        return_code = 0
    except Exception as exc:
        result["error"] = str(exc)
        return_code = 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "ok": result.get("ok", False),
                "error": result.get("error"),
                "scene": result.get("scene"),
                "summary": result.get("summary"),
                "output": str(args.output),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
