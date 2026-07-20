#!/usr/bin/env python3
"""Stress Leave Game -> New Game on a genuine Steam friend pair."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import drive_steam_friend_active_pair as drive
import verify_local_multiplayer_sync as local_sync
from steam_friend_active_pair import (
    CLIENT_ENDPOINT,
    HOST_ENDPOINT,
    PAIR_BACKEND,
    ROOT,
    SteamFriendActivePair,
)
from verify_local_multiplayer_sync import VerifyFailure, parse_key_values
from verify_steam_friend_active_run_reconnect import (
    new_crash_artifacts,
    require_one_game_process,
)
from verify_steam_friend_real_input_control import windows_process_id
from steam_friend_hub_automation import remote_windows_process_id


DEFAULT_OUTPUT = ROOT / "runtime/steam_friend_run_exit_reentry.json"
POST_EXIT_STABLE_SECONDS = 2.0


def require_instance_environment() -> tuple[str, str]:
    host_instance = os.environ.get("SDMOD_STEAM_HOST_INSTANCE", "").strip()
    client_instance = os.environ.get("SDMOD_STEAM_CLIENT_INSTANCE", "").strip()
    if not host_instance or not client_instance:
        raise VerifyFailure(
            "SDMOD_STEAM_HOST_INSTANCE and SDMOD_STEAM_CLIENT_INSTANCE are required"
        )
    return host_instance, client_instance


def configure_pair(pair: SteamFriendActivePair) -> dict[str, Any]:
    discovered = pair.discover()
    local_sync.lua = pair.lua
    local_sync.HOST_ID = pair.host_participant_id
    local_sync.CLIENT_ID = pair.client_participant_id
    local_sync.HOST_PIPE = HOST_ENDPOINT
    local_sync.CLIENT_PIPE = CLIENT_ENDPOINT
    return discovered


def process_ids(host_instance: str, client_instance: str) -> dict[str, int]:
    if PAIR_BACKEND == "wsl":
        return {
            "windows": windows_process_id(host_instance),
            "proton": require_one_game_process(client_instance),
        }
    if PAIR_BACKEND == "remote-windows-host":
        return {
            "remote_windows": remote_windows_process_id(),
            "local_windows": windows_process_id(client_instance),
        }
    raise VerifyFailure(f"unsupported Steam pair backend: {PAIR_BACKEND!r}")


def wait_for_pause_leave_action(
    pair: SteamFriendActivePair,
    timeout: float,
) -> dict[str, str]:
    pressed = pair.lua(
        HOST_ENDPOINT,
        "return tostring(sd.input.press_key('menu'))",
        timeout=5.0,
    ).strip()
    if pressed != "true":
        raise VerifyFailure(f"host pause-menu input was rejected: {pressed!r}")

    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = parse_key_values(
            pair.lua(
                HOST_ENDPOINT,
                r"""
local snapshot = sd.ui.get_snapshot()
local action = sd.ui.find_action('pause_menu.leave_game', 'simple_menu')
print('surface=' .. tostring(snapshot and snapshot.surface_id or ''))
print('action=' .. tostring(action ~= nil))
""",
                timeout=5.0,
            )
        )
        if last.get("surface") == "simple_menu" and last.get("action") == "true":
            return {"pressed": pressed, **last}
        time.sleep(0.1)
    raise VerifyFailure(f"host pause-menu Leave Game action did not appear: {last}")


def wait_for_pair_to_leave_run(
    pair: SteamFriendActivePair,
    timeout: float,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    stable_since: float | None = None
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        try:
            last = {
                "host": pair.lua(
                    HOST_ENDPOINT,
                    "local s=sd.world.get_scene(); return tostring(s and (s.kind or s.name) or '')",
                    timeout=5.0,
                ).strip(),
                "client": pair.lua(
                    CLIENT_ENDPOINT,
                    "local s=sd.world.get_scene(); return tostring(s and (s.kind or s.name) or '')",
                    timeout=5.0,
                ).strip(),
            }
        except Exception:
            stable_since = None
            time.sleep(0.1)
            continue

        now = time.monotonic()
        if all(
            scene not in {"arena", "testrun", "transition"}
            for scene in last.values()
        ):
            if stable_since is None:
                stable_since = now
            elif now - stable_since >= POST_EXIT_STABLE_SECONDS:
                return last
        else:
            stable_since = None
        time.sleep(0.1)
    raise VerifyFailure(f"host-authoritative run exit did not converge: {last}")


def verify_run_exit_releases_native_participants(
    pair: SteamFriendActivePair,
    timeout: float,
) -> dict[str, dict[str, str]]:
    pending = {HOST_ENDPOINT, CLIENT_ENDPOINT}
    released: dict[str, dict[str, str]] = {}
    deadline = time.monotonic() + timeout
    while pending and time.monotonic() < deadline:
        for endpoint in tuple(pending):
            state = parse_key_values(
                pair.lua(
                    endpoint,
                    r"""
local scene = sd.world.get_scene()
local participants = sd.bots.get_participants()
local native_bound = 0
for _, participant in ipairs(participants) do
    if participant.entity_materialized or
       (participant.actor_address or 0) ~= 0 or
       (participant.world_address or 0) ~= 0 or
       (participant.progression_handle_address or 0) ~= 0 or
       (participant.progression_runtime_state_address or 0) ~= 0 or
       (participant.equip_handle_address or 0) ~= 0 or
       (participant.equip_runtime_state_address or 0) ~= 0 then
        native_bound = native_bound + 1
    end
end
print('scene=' .. tostring(scene and (scene.kind or scene.name) or ''))
print('participants=' .. tostring(#participants))
print('native_bound=' .. tostring(native_bound))
""",
                    timeout=5.0,
                )
            )
            if state.get("scene") in {"arena", "testrun"}:
                continue
            if int(state.get("participants", "0")) < 1:
                raise VerifyFailure(
                    f"{endpoint} lost its authenticated participant during run exit"
                )
            if int(state.get("native_bound", "-1")) != 0:
                raise VerifyFailure(
                    f"{endpoint} exposed outgoing-scene native participant pointers "
                    f"after leaving the run: {state}"
                )
            released[endpoint] = state
            pending.remove(endpoint)
        if pending:
            time.sleep(0.05)

    if pending:
        raise VerifyFailure(
            "run exit did not leave the arena on endpoint(s): "
            + ", ".join(sorted(pending))
        )
    return released


def drive_pair_to_hub(
    pair: SteamFriendActivePair,
    timeout: float,
    *,
    host_element: str = "fire",
    client_element: str = "air",
    discipline: str = "arcane",
) -> dict[str, Any]:
    host = drive.drive_one_to_hub(
        pair,
        HOST_ENDPOINT,
        element=host_element,
        discipline=discipline,
        timeout=timeout,
    )
    client = drive.drive_one_to_hub(
        pair,
        CLIENT_ENDPOINT,
        element=client_element,
        discipline=discipline,
        timeout=timeout,
    )
    if host["scene"] != "hub" or client["scene"] != "hub":
        raise VerifyFailure(
            f"pair did not settle in the hub after New Game: host={host} client={client}"
        )
    return {"host": host, "client": client}


def start_shared_run(
    pair: SteamFriendActivePair,
    *,
    test_godmode: bool = False,
    test_manual_enemy_mode: bool = False,
    run_generation_seed: int | None = None,
) -> dict[str, Any]:
    host_view = local_sync.query(HOST_ENDPOINT)
    client_view = local_sync.query(CLIENT_ENDPOINT)
    local_sync.CLIENT_NAME = host_view.get(
        f"peer.{pair.client_participant_id}.name",
        "",
    )
    local_sync.HOST_NAME = client_view.get(
        f"peer.{pair.host_participant_id}.name",
        "",
    )
    protections: dict[str, Any] = {}
    if test_godmode:
        protections["godmode"] = {
            "host": drive.arm_test_godmode(pair, HOST_ENDPOINT),
            "client": drive.arm_test_godmode(pair, CLIENT_ENDPOINT),
        }
    if test_manual_enemy_mode:
        protections["manual_enemy_mode"] = {
            "host": drive.arm_test_manual_enemy_mode(pair, HOST_ENDPOINT),
            "client": drive.arm_test_manual_enemy_mode(pair, CLIENT_ENDPOINT),
        }
    seed_result = (
        drive.set_run_generation_seed(pair, run_generation_seed)
        if run_generation_seed is not None
        else None
    )
    client_start_blocked = local_sync.assert_client_start_testrun_blocked()
    run_entry = local_sync.start_host_testrun_and_wait_for_clients(timeout=60.0)
    bootstrap = local_sync.verify_run_entry_bootstrap(timeout=20.0)
    return {
        "test_protections": protections,
        "run_generation_seed": seed_result,
        "client_start_blocked": client_start_blocked,
        "run_entry": run_entry,
        "bootstrap": bootstrap,
    }


def instance_log(instance: str, override_environment_variable: str) -> Path:
    override = os.environ.get(override_environment_variable, "").strip()
    if override:
        return Path(override)
    return (
        ROOT
        / "runtime"
        / "instances"
        / instance
        / "stage/.sdmod/logs/solomondarkmodloader.log"
    )


def assert_no_wrong_thread_rejections(log_paths: tuple[Path, Path]) -> None:
    token = "Multiplayer session/transport tick rejected outside its owning AppMainTick thread."
    for log_path in log_paths:
        if log_path.is_file() and token in log_path.read_text(
            encoding="utf-8",
            errors="replace",
        ):
            raise VerifyFailure(
                f"wrong-thread transport tick was rejected in {log_path}"
            )


def run(
    pair: SteamFriendActivePair,
    cycles: int,
    timeout: float,
    *,
    test_godmode: bool = False,
    test_manual_enemy_mode: bool = False,
    host_element: str = "fire",
    client_element: str = "air",
    discipline: str = "arcane",
    run_generation_seeds: tuple[int, ...] = (),
) -> dict[str, Any]:
    host_instance, client_instance = require_instance_environment()
    instances = (host_instance, client_instance)
    log_paths = (
        instance_log(host_instance, "SDMOD_STEAM_HOST_LOG_PATH"),
        instance_log(client_instance, "SDMOD_STEAM_CLIENT_LOG_PATH"),
    )
    started_at = time.time()
    discovered = configure_pair(pair)
    scene_views = [
        side
        for side in discovered.values()
        if isinstance(side, dict) and "scene" in side
    ]
    if len(scene_views) != 2 or any(
        side["scene"] != "testrun" for side in scene_views
    ):
        raise VerifyFailure(f"Steam pair must begin in a shared run: {discovered}")

    initial_processes = process_ids(host_instance, client_instance)
    records: list[dict[str, Any]] = []
    for cycle in range(1, cycles + 1):
        before_processes = process_ids(host_instance, client_instance)
        record: dict[str, Any] = {
            "cycle": cycle,
            "processes_before": before_processes,
            "pause_menu": wait_for_pause_leave_action(pair, min(timeout, 15.0)),
        }
        record["leave_action"] = local_sync.activate_native_ui_action(
            HOST_ENDPOINT,
            "pause_menu.leave_game",
            "simple_menu",
        )
        record["transition_native_release"] = (
            verify_run_exit_releases_native_participants(
                pair,
                min(timeout, 15.0),
            )
        )
        record["post_exit_scenes"] = wait_for_pair_to_leave_run(pair, timeout)
        record["new_game"] = drive_pair_to_hub(
            pair,
            timeout,
            host_element=host_element,
            client_element=client_element,
            discipline=discipline,
        )
        record["reentered_run"] = start_shared_run(
            pair,
            test_godmode=test_godmode,
            test_manual_enemy_mode=test_manual_enemy_mode,
            run_generation_seed=(
                run_generation_seeds[cycle - 1]
                if run_generation_seeds
                else None
            ),
        )
        after_processes = process_ids(host_instance, client_instance)
        record["processes_after"] = after_processes
        if after_processes != initial_processes:
            raise VerifyFailure(
                "a game process changed during Leave Game -> New Game: "
                f"initial={initial_processes} current={after_processes}"
            )
        records.append(record)

    assert_no_wrong_thread_rejections(log_paths)
    crashes = new_crash_artifacts(started_at, instances)
    if crashes:
        raise VerifyFailure(f"new crash artifacts appeared: {crashes}")
    return {
        "ok": True,
        "pair": discovered,
        "cycles": records,
        "processes": initial_processes,
        "new_crash_artifacts": crashes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--test-godmode", action="store_true")
    parser.add_argument("--test-manual-enemy-mode", action="store_true")
    parser.add_argument("--host-element", default="fire")
    parser.add_argument("--client-element", default="air")
    parser.add_argument("--discipline", default="arcane")
    parser.add_argument(
        "--run-generation-seed",
        action="append",
        type=drive.parse_run_generation_seed,
        default=[],
        help="Set one exact host run seed per re-entry cycle.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.cycles <= 0:
        parser.error("--cycles must be positive")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if args.run_generation_seed and len(args.run_generation_seed) != args.cycles:
        parser.error("provide exactly one --run-generation-seed per cycle")

    pair = SteamFriendActivePair()
    result: dict[str, Any] = {"ok": False}
    return_code = 1
    try:
        result = run(
            pair,
            args.cycles,
            args.timeout,
            test_godmode=args.test_godmode,
            test_manual_enemy_mode=args.test_manual_enemy_mode,
            host_element=args.host_element,
            client_element=args.client_element,
            discipline=args.discipline,
            run_generation_seeds=tuple(args.run_generation_seed),
        )
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
                    "completed_cycles": len(result.get("cycles", [])),
                    "output": str(args.output),
                },
                indent=2,
                sort_keys=True,
            )
        )
    return return_code


if __name__ == "__main__":
    sys.exit(main())
