#!/usr/bin/env python3
"""Verify shared run-menu pause, resume, and timeout on a Steam friend pair."""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import verify_local_multiplayer_sync as local_sync
import verify_multiplayer_primary_kill_stress as primary
from steam_friend_active_pair import (
    CLIENT_ENDPOINT,
    HOST_ENDPOINT,
    ROOT,
    SteamFriendActivePair,
)
from steam_friend_behavior_context import (
    configure_behavior_context,
    require_shared_test_run,
    reset_quiet_arena,
)
from verify_local_multiplayer_sync import VerifyFailure, parse_key_values


DEFAULT_OUTPUT = ROOT / "runtime/steam_friend_shared_menu_pause.json"
SHARED_TIMEOUT_SECONDS = 60.0
WORLD_FREEZE_SAMPLE_SECONDS = 1.5
MAXIMUM_FROZEN_DRIFT = 0.25
MINIMUM_RESUMED_MOTION = 3.0
ENEMY_POSITION = (2600.0, 1500.0)


@dataclass(frozen=True)
class Direction:
    name: str
    owner_endpoint: str


DIRECTIONS = (
    Direction("host_owned", HOST_ENDPOINT),
    Direction("client_owned", CLIENT_ENDPOINT),
)


def floating(values: dict[str, str], key: str) -> float:
    try:
        return float(values.get(key, "nan"))
    except (TypeError, ValueError):
        return math.nan


def query_shared_pause(
    pair: SteamFriendActivePair,
    endpoint: str,
) -> dict[str, str]:
    return parse_key_values(
        pair.lua(
            endpoint,
            r"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
local state = sd.runtime.get_multiplayer_state()
local pause = state and state.shared_gameplay_pause_status or nil
local ui = sd.ui.get_snapshot()
emit('valid', pause and pause.valid or false)
emit('active', pause and pause.pause_active or false)
emit('timed_out', pause and pause.timed_out or false)
emit('local_request_active', pause and pause.local_request_active or false)
emit('local_request_epoch', pause and pause.local_request_epoch or 0)
emit('run_nonce', pause and pause.run_nonce or 0)
emit('deadline_remaining_ms', pause and pause.deadline_remaining_ms or 0)
emit('authority_participant_id', pause and pause.authority_participant_id or 0)
emit('origin_participant_id', pause and pause.origin_participant_id or 0)
emit('surface', ui and ui.surface_id or '')
""",
            timeout=8.0,
        )
    )


def open_local_pause_surface(
    pair: SteamFriendActivePair,
    endpoint: str,
    timeout: float,
) -> dict[str, str]:
    pressed = pair.lua(
        endpoint,
        "return tostring(sd.input.press_key('menu'))",
        timeout=8.0,
    ).strip()
    if pressed != "true":
        raise VerifyFailure(f"menu input was rejected on {endpoint}: {pressed!r}")

    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = query_shared_pause(pair, endpoint)
        if (
            last.get("surface") in {
                "pause_menu",
                "simple_menu",
                "quick_panel",
                "settings",
            }
            and last.get("local_request_active") == "true"
        ):
            return last
        time.sleep(0.1)
    raise VerifyFailure(f"pause surface did not publish a request: {last}")


def close_local_pause_surface(
    endpoint: str,
) -> dict[str, str]:
    return local_sync.activate_native_ui_action(
        endpoint,
        "pause_menu.resume_game",
        "simple_menu",
    )


def wait_for_shared_pause(
    pair: SteamFriendActivePair,
    origin_participant_id: int,
    timeout: float,
) -> dict[str, dict[str, str]]:
    deadline = time.monotonic() + timeout
    last: dict[str, dict[str, str]] = {}
    while time.monotonic() < deadline:
        last = {
            "host": query_shared_pause(pair, HOST_ENDPOINT),
            "client": query_shared_pause(pair, CLIENT_ENDPOINT),
        }
        if all(
            state.get("valid") == "true"
            and state.get("active") == "true"
            and int(state.get("origin_participant_id", "0"))
            == origin_participant_id
            for state in last.values()
        ):
            return last
        time.sleep(0.1)
    raise VerifyFailure(f"shared pause did not converge: {last}")


def wait_for_shared_resume(
    pair: SteamFriendActivePair,
    timeout: float,
    *,
    require_timeout: bool = False,
) -> dict[str, dict[str, str]]:
    deadline = time.monotonic() + timeout
    last: dict[str, dict[str, str]] = {}
    while time.monotonic() < deadline:
        last = {
            "host": query_shared_pause(pair, HOST_ENDPOINT),
            "client": query_shared_pause(pair, CLIENT_ENDPOINT),
        }
        inactive = all(state.get("active") == "false" for state in last.values())
        timeout_visible = all(
            state.get("timed_out") == "true" for state in last.values()
        )
        if inactive and (not require_timeout or timeout_visible):
            return last
        time.sleep(0.1)
    raise VerifyFailure(f"shared pause did not resume: {last}")


def wait_for_timeout_release(
    pair: SteamFriendActivePair,
) -> dict[str, dict[str, str]]:
    return wait_for_shared_resume(
        pair,
        SHARED_TIMEOUT_SECONDS + 12.0,
        require_timeout=True,
    )


def enemy_position(network_actor_id: int) -> tuple[float, float]:
    state = primary.query_run_enemy_by_network_id(
        HOST_ENDPOINT,
        network_actor_id,
    )
    if state.get("found") != "true":
        raise VerifyFailure(
            f"host lost pause-test enemy {network_actor_id}: {state}"
        )
    position = (floating(state, "x"), floating(state, "y"))
    if not all(math.isfinite(value) for value in position):
        raise VerifyFailure(f"pause-test enemy position is invalid: {state}")
    return position


def position_distance(
    left: tuple[float, float],
    right: tuple[float, float],
) -> float:
    return math.hypot(right[0] - left[0], right[1] - left[1])


def assert_world_frozen(network_actor_id: int) -> dict[str, Any]:
    samples = [enemy_position(network_actor_id)]
    deadline = time.monotonic() + WORLD_FREEZE_SAMPLE_SECONDS
    while time.monotonic() < deadline:
        time.sleep(0.1)
        samples.append(enemy_position(network_actor_id))
    maximum_drift = max(
        position_distance(samples[0], sample) for sample in samples[1:]
    )
    if maximum_drift > MAXIMUM_FROZEN_DRIFT:
        raise VerifyFailure(
            f"host world moved during shared pause: drift={maximum_drift:.3f}"
        )
    return {"samples": samples, "maximum_drift": maximum_drift}


def assert_world_resumed(
    network_actor_id: int,
    timeout: float,
) -> dict[str, Any]:
    start = enemy_position(network_actor_id)
    deadline = time.monotonic() + timeout
    samples = [start]
    while time.monotonic() < deadline:
        time.sleep(0.1)
        current = enemy_position(network_actor_id)
        samples.append(current)
        motion = position_distance(start, current)
        if motion >= MINIMUM_RESUMED_MOTION:
            return {"samples": samples, "motion": motion}
    raise VerifyFailure(f"host world did not resume enemy motion: {samples[-4:]}")


def prepare_moving_enemy(
    timeout: float,
) -> dict[str, Any]:
    reset = reset_quiet_arena()
    spawn = primary.spawn_one_enemy(
        *ENEMY_POSITION,
        setup_hp=50_000.0,
        freeze_on_spawn=False,
    )
    network_actor_id = int(spawn["network_actor_id"])
    primary.find_target(
        HOST_ENDPOINT,
        *ENEMY_POSITION,
        network_actor_id,
        timeout,
        require_local_binding=False,
    )
    primary.find_target(
        CLIENT_ENDPOINT,
        *ENEMY_POSITION,
        network_actor_id,
        timeout,
    )
    motion = assert_world_resumed(network_actor_id, timeout)
    return {
        "reset": reset,
        "spawn": spawn,
        "network_actor_id": network_actor_id,
        "baseline_motion": motion,
    }


def run_direction(
    pair: SteamFriendActivePair,
    direction: Direction,
    timeout: float,
) -> dict[str, Any]:
    prepared = prepare_moving_enemy(timeout)
    origin_id = (
        pair.host_participant_id
        if direction.owner_endpoint == HOST_ENDPOINT
        else pair.client_participant_id
    )
    opened = open_local_pause_surface(pair, direction.owner_endpoint, timeout)
    shared = wait_for_shared_pause(pair, origin_id, timeout)
    frozen = assert_world_frozen(prepared["network_actor_id"])
    closed = close_local_pause_surface(direction.owner_endpoint)
    resumed_state = wait_for_shared_resume(pair, timeout)
    resumed_world = assert_world_resumed(prepared["network_actor_id"], timeout)
    return {
        "prepared": prepared,
        "opened": opened,
        "shared": shared,
        "frozen": frozen,
        "closed": closed,
        "resumed_state": resumed_state,
        "resumed_world": resumed_world,
    }


def run_timeout_case(
    pair: SteamFriendActivePair,
    timeout: float,
) -> dict[str, Any]:
    prepared = prepare_moving_enemy(timeout)
    opened = open_local_pause_surface(pair, CLIENT_ENDPOINT, timeout)
    shared = wait_for_shared_pause(
        pair,
        pair.client_participant_id,
        timeout,
    )
    frozen = assert_world_frozen(prepared["network_actor_id"])
    timed_out = wait_for_timeout_release(pair)
    resumed_world = assert_world_resumed(prepared["network_actor_id"], timeout)
    closed = close_local_pause_surface(CLIENT_ENDPOINT)
    released = wait_for_shared_resume(pair, timeout)
    return {
        "prepared": prepared,
        "opened": opened,
        "shared": shared,
        "frozen": frozen,
        "timed_out": timed_out,
        "resumed_world": resumed_world,
        "closed": closed,
        "released": released,
    }


def run(
    pair: SteamFriendActivePair,
    timeout: float,
    *,
    test_timeout: bool,
) -> dict[str, Any]:
    discovered = pair.discover()
    require_shared_test_run(discovered)
    configure_behavior_context(pair)
    result: dict[str, Any] = {
        "ok": False,
        "pair": discovered,
        "directions": {},
    }
    result["manual_prelude"] = primary.enable_manual_stock_spawner_combat()
    for direction in DIRECTIONS:
        result["directions"][direction.name] = run_direction(
            pair,
            direction,
            timeout,
        )
    if test_timeout:
        result["timeout"] = run_timeout_case(pair, timeout)
    result["ok"] = True
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--test-timeout", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    pair = SteamFriendActivePair()
    result: dict[str, Any] = {"ok": False}
    return_code = 1
    try:
        result = run(pair, args.timeout, test_timeout=args.test_timeout)
        return_code = 0
    except Exception as exc:
        result["error"] = str(exc)
        result["error_type"] = type(exc).__name__
        result["traceback"] = traceback.format_exc()
    finally:
        pair.close()
        result = pair.redact(result)
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
                    "output": str(args.output),
                },
                indent=2,
                sort_keys=True,
            )
        )
    return return_code


if __name__ == "__main__":
    sys.exit(main())
