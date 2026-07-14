#!/usr/bin/env python3
"""Verify and capture native remote-player body presentation in a shared run."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from multiplayer_frame_capture import capture_game_backbuffer
from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_NAME,
    CLIENT_PIPE,
    HOST_ID,
    HOST_NAME,
    HOST_PIPE,
    ROOT,
    VerifyFailure,
    activate_native_ui_action,
    disable_bots,
    hold_player_heading,
    launch_pair,
    lua,
    place_player,
    query,
    start_host_testrun_and_wait_for_clients,
    stop_games,
    wait_for_remote,
    wait_for_remote_convergence,
)
from verify_multiplayer_primary_kill_stress import set_manual_spawner_test_mode
from verify_real_input_spell_cast_sync import detect_instance_pids


OUTPUT = ROOT / "runtime" / "multiplayer_player_visibility.json"
HOST_SCREENSHOT = ROOT / "runtime" / "multiplayer_player_visibility_host.png"
CLIENT_SCREENSHOT = ROOT / "runtime" / "multiplayer_player_visibility_client.png"
HOST_RUN_SCREENSHOT = ROOT / "runtime" / "multiplayer_player_visibility_run_host.png"
CLIENT_RUN_SCREENSHOT = ROOT / "runtime" / "multiplayer_player_visibility_run_client.png"
FLAT_BONEYARD = ROOT / "tests" / "fixtures" / "boneyards" / "flat_multiplayer_test.boneyard"

VISIBILITY_PAIR_HALF_SEPARATION = 100.0
RUN_ENTRY_FORMATION_RELEASE_SECONDS = 5.25
POST_RUN_EXIT_STABLE_SECONDS = 2.0


def place_pair_for_visibility() -> dict[str, Any]:
    before = query(HOST_PIPE)
    base_x = float(before["player.x"])
    base_y = float(before["player.y"])
    # Do not snap these independently to the coarse nav sample grid. Nearby
    # targets can resolve to the same sample, which stacks both wizards and
    # makes their staff/orb layers look like a missing body in screenshots.
    host_x = base_x - VISIBILITY_PAIR_HALF_SEPARATION
    host_y = base_y
    client_x = base_x + VISIBILITY_PAIR_HALF_SEPARATION
    client_y = base_y

    hold_player_heading(HOST_PIPE, 90.0)
    hold_player_heading(CLIENT_PIPE, 270.0)
    host_place = place_player(HOST_PIPE, host_x, host_y, 90.0)
    client_place = place_player(CLIENT_PIPE, client_x, client_y, 270.0)
    client_view = wait_for_remote_convergence(
        CLIENT_PIPE,
        HOST_ID,
        host_x,
        host_y,
        90.0,
        timeout=12.0,
    )
    host_view = wait_for_remote_convergence(
        HOST_PIPE,
        CLIENT_ID,
        client_x,
        client_y,
        270.0,
        timeout=12.0,
    )
    placement = {
        "host_place": host_place,
        "client_place": client_place,
        "host_position": [host_x, host_y],
        "client_position": [client_x, client_y],
        "host_view_client_selector": host_view[f"peer.{CLIENT_ID}.render_selector"],
        "client_view_host_selector": client_view[f"peer.{HOST_ID}.render_selector"],
        "host_view_client_visual_types": [
            int(host_view[f"peer.{CLIENT_ID}.primary_visual_type"]),
            int(host_view[f"peer.{CLIENT_ID}.secondary_visual_type"]),
        ],
        "client_view_host_visual_types": [
            int(client_view[f"peer.{HOST_ID}.primary_visual_type"]),
            int(client_view[f"peer.{HOST_ID}.secondary_visual_type"]),
        ],
    }
    expected_visual_types = {7005, 7006}
    for key in (
        "host_view_client_visual_types",
        "client_view_host_visual_types",
    ):
        if set(placement[key]) != expected_visual_types:
            raise VerifyFailure(
                f"remote wizard body helper lanes are incomplete for {key}: "
                f"{placement[key]}"
            )
    if abs(client_x - host_x) < 150.0:
        raise VerifyFailure(
            "visibility capture participants are not separated enough to inspect"
        )
    return placement


def assert_complete_local_wizard_visuals(
    states: dict[str, dict[str, str]],
    scene_label: str,
) -> dict[str, list[int]]:
    expected_visual_types = {7005, 7006}
    observed: dict[str, list[int]] = {}
    for endpoint, state in states.items():
        visual_types = [
            int(state["player.primary_visual_type"]),
            int(state["player.secondary_visual_type"]),
        ]
        if set(visual_types) != expected_visual_types:
            raise VerifyFailure(
                f"{endpoint} local wizard body lanes are incomplete in "
                f"{scene_label}: {visual_types}"
            )
        observed[endpoint] = visual_types
    return observed


def wait_for_pause_leave_action(timeout: float = 10.0) -> dict[str, str]:
    pressed = lua(
        HOST_PIPE,
        "return tostring(sd.input.press_key('menu'))",
        timeout=5.0,
    ).strip()
    if pressed != "true":
        raise VerifyFailure(f"host pause-menu input was rejected: {pressed!r}")

    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        values = lua(
            HOST_PIPE,
            """
local snapshot = sd.ui.get_snapshot()
local action = sd.ui.find_action('pause_menu.leave_game', 'simple_menu')
print('surface=' .. tostring(snapshot and snapshot.surface_id or ''))
print('action=' .. tostring(action ~= nil))
""",
            timeout=5.0,
        )
        last = {}
        for line in values.splitlines():
            key, separator, value = line.partition("=")
            if separator:
                last[key.strip()] = value.strip()
        if last.get("surface") == "simple_menu" and last.get("action") == "true":
            return {"pressed": pressed, **last}
        time.sleep(0.1)
    raise VerifyFailure(f"host pause-menu Leave Game action did not appear: {last}")


def wait_for_pair_to_leave_run(timeout: float = 30.0) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    stable_since: float | None = None
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        try:
            last = {
                "host": lua(
                    HOST_PIPE,
                    "local s=sd.world.get_scene(); return tostring(s and (s.name or s.kind) or '')",
                    timeout=5.0,
                ).strip(),
                "client": lua(
                    CLIENT_PIPE,
                    "local s=sd.world.get_scene(); return tostring(s and (s.name or s.kind) or '')",
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
            elif now - stable_since >= POST_RUN_EXIT_STABLE_SECONDS:
                return last
        else:
            stable_since = None
        time.sleep(0.1)
    raise VerifyFailure(f"host-authoritative run exit did not converge: {last}")


def run(result: dict[str, Any]) -> None:
    result["launch"] = launch_pair(
        tile_windows=True,
        god_mode=True,
        test_survival_boneyard_override=FLAT_BONEYARD,
        test_blank_boneyard=True,
    )
    disable_bots()
    result["hub_ready"] = {
        "host": wait_for_remote(HOST_PIPE, CLIENT_ID, CLIENT_NAME, "hub"),
        "client": wait_for_remote(CLIENT_PIPE, HOST_ID, HOST_NAME, "hub"),
    }
    result["hub_state"] = {
        "host": query(HOST_PIPE),
        "client": query(CLIENT_PIPE),
    }
    result["hub_local_visual_types"] = assert_complete_local_wizard_visuals(
        result["hub_state"],
        "hub",
    )
    result["hub_capture_placement"] = place_pair_for_visibility()
    pids = detect_instance_pids()
    result["hub_screenshots"] = {
        "host": capture_game_backbuffer(HOST_PIPE, pids["host"], HOST_SCREENSHOT),
        "client": capture_game_backbuffer(CLIENT_PIPE, pids["client"], CLIENT_SCREENSHOT),
    }
    result["manual_spawner_prearm"] = {
        "host": set_manual_spawner_test_mode(HOST_PIPE, True),
        "client": set_manual_spawner_test_mode(CLIENT_PIPE, True),
    }
    for label, state in result["manual_spawner_prearm"].items():
        if state.get("ok") != "true" or state.get("active") != "true":
            raise VerifyFailure(
                f"failed to prearm {label} manual spawner mode: {state}"
            )
    result["run_entry"] = start_host_testrun_and_wait_for_clients(timeout=60.0)
    result["run_ready"] = {
        "host": wait_for_remote(HOST_PIPE, CLIENT_ID, CLIENT_NAME, "testrun"),
        "client": wait_for_remote(CLIENT_PIPE, HOST_ID, HOST_NAME, "testrun"),
    }
    # Client placement is intentionally host-authored for the first five
    # seconds of a run. Wait until that bootstrap lease expires before testing
    # ordinary participant movement and presentation.
    time.sleep(RUN_ENTRY_FORMATION_RELEASE_SECONDS)
    disable_bots()
    result["run_state"] = {
        "host": query(HOST_PIPE),
        "client": query(CLIENT_PIPE),
    }
    result["run_local_visual_types"] = assert_complete_local_wizard_visuals(
        result["run_state"],
        "run",
    )
    result["run_capture_placement"] = place_pair_for_visibility()
    result["run_screenshots"] = {
        "host": capture_game_backbuffer(
            HOST_PIPE,
            pids["host"],
            HOST_RUN_SCREENSHOT,
        ),
        "client": capture_game_backbuffer(
            CLIENT_PIPE,
            pids["client"],
            CLIENT_RUN_SCREENSHOT,
        ),
    }
    result["host_leave_menu"] = wait_for_pause_leave_action()
    result["host_leave_action"] = activate_native_ui_action(
        HOST_PIPE,
        "pause_menu.leave_game",
        "simple_menu",
    )
    result["post_run_exit_scenes"] = wait_for_pair_to_leave_run()
    result["ok"] = True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()

    result: dict[str, Any] = {"ok": False}
    try:
        stop_games()
        run(result)
        return_code = 0
    except Exception as exc:
        result["error"] = str(exc)
        return_code = 1
    finally:
        stop_games()

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "ok": result.get("ok", False),
        "error": result.get("error"),
        "hub_capture_placement": result.get("hub_capture_placement"),
        "run_capture_placement": result.get("run_capture_placement"),
        "hub_screenshots": result.get("hub_screenshots"),
        "run_screenshots": result.get("run_screenshots"),
        "hub_local_visual_types": result.get("hub_local_visual_types"),
        "run_local_visual_types": result.get("run_local_visual_types"),
        "host_leave_action": result.get("host_leave_action"),
        "post_run_exit_scenes": result.get("post_run_exit_scenes"),
        "output": str(OUTPUT),
    }, indent=2, sort_keys=True))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
