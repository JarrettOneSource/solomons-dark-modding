#!/usr/bin/env python3
"""Verify and capture native remote-player body presentation in a shared run."""

from __future__ import annotations

import json
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
    disable_bots,
    hold_player_heading,
    launch_pair,
    place_player,
    query,
    snap_to_nav,
    start_host_testrun_and_wait_for_clients,
    stop_games,
    verify_scene,
    wait_for_remote,
    wait_for_remote_convergence,
)
from verify_real_input_spell_cast_sync import detect_instance_pids


OUTPUT = ROOT / "runtime" / "multiplayer_player_visibility.json"
HOST_SCREENSHOT = ROOT / "runtime" / "multiplayer_player_visibility_host.png"
CLIENT_SCREENSHOT = ROOT / "runtime" / "multiplayer_player_visibility_client.png"


def place_pair_for_visibility() -> dict[str, Any]:
    before = query(HOST_PIPE)
    base_x = float(before["player.x"])
    base_y = float(before["player.y"])
    host_x, host_y = snap_to_nav(HOST_PIPE, base_x - 45.0, base_y)
    client_x, client_y = snap_to_nav(HOST_PIPE, base_x + 45.0, base_y)

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
    return {
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


def run(result: dict[str, Any]) -> None:
    result["launch"] = launch_pair(tile_windows=True)
    disable_bots()
    result["hub_ready"] = {
        "host": wait_for_remote(HOST_PIPE, CLIENT_ID, CLIENT_NAME, "hub"),
        "client": wait_for_remote(CLIENT_PIPE, HOST_ID, HOST_NAME, "hub"),
    }
    result["hub_verification"] = verify_scene("hub")
    result["capture_scene"] = "hub"
    result["capture_placement"] = place_pair_for_visibility()
    pids = detect_instance_pids()
    result["screenshots"] = {
        "host": capture_game_backbuffer(HOST_PIPE, pids["host"], HOST_SCREENSHOT),
        "client": capture_game_backbuffer(CLIENT_PIPE, pids["client"], CLIENT_SCREENSHOT),
    }
    result["run_entry"] = start_host_testrun_and_wait_for_clients(timeout=60.0)
    result["run_ready"] = {
        "host": wait_for_remote(HOST_PIPE, CLIENT_ID, CLIENT_NAME, "testrun"),
        "client": wait_for_remote(CLIENT_PIPE, HOST_ID, HOST_NAME, "testrun"),
    }
    result["run_verification"] = verify_scene("testrun")
    result["ok"] = True


def main() -> int:
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
        "capture_placement": result.get("capture_placement"),
        "screenshots": result.get("screenshots"),
        "output": str(OUTPUT),
    }, indent=2, sort_keys=True))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
