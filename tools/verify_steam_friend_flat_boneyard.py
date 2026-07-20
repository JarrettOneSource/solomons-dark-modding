#!/usr/bin/env python3
"""Verify the explicit flat Boneyard on an active Windows/Proton Steam pair."""

from __future__ import annotations

import argparse
import json
import os
import traceback
from pathlib import Path
from typing import Any

import multiplayer_frame_capture as frame_capture
import verify_flat_multiplayer_boneyard as flat
import verify_local_multiplayer_sync as local_sync
import verify_multiplayer_primary_kill_stress as primary
from steam_friend_active_pair import (
    CLIENT_ENDPOINT,
    HOST_ENDPOINT,
    ROOT,
    SteamFriendActivePair,
)
from verify_local_multiplayer_sync import VerifyFailure


DEFAULT_OUTPUT = ROOT / "runtime/steam_friend_flat_boneyard.json"
HOST_SCREENSHOT = ROOT / "runtime/steam_friend_flat_boneyard_windows.png"
CLIENT_SCREENSHOT = ROOT / "runtime/steam_friend_flat_boneyard_proton.png"


def configure(pair: SteamFriendActivePair) -> None:
    for module in (local_sync, flat, primary, frame_capture):
        if hasattr(module, "lua"):
            module.lua = pair.lua
    for module in (flat, primary):
        module.HOST_PIPE = HOST_ENDPOINT
        module.CLIENT_PIPE = CLIENT_ENDPOINT


def verify_staged_fixture(instance: str) -> dict[str, Any]:
    staged = (
        ROOT
        / "runtime"
        / "instances"
        / instance
        / "stage"
        / "data"
        / "levels"
        / "survival.boneyard"
    )
    if not staged.is_file():
        raise VerifyFailure(f"staged flat Boneyard is missing for {instance}")
    staged_hash = flat.sha256(staged)
    if staged_hash != flat.EXPECTED_SHA256:
        raise VerifyFailure(f"staged flat Boneyard differs for {instance}")
    return {
        "path": str(staged),
        "bytes": staged.stat().st_size,
        "sha256": staged_hash,
    }


def run(
    pair: SteamFriendActivePair,
    host_instance: str,
    client_instance: str,
    timeout: float,
) -> dict[str, Any]:
    if not flat.FIXTURE.is_file() or flat.sha256(flat.FIXTURE) != flat.EXPECTED_SHA256:
        raise VerifyFailure("the committed flat Boneyard fixture is missing or changed")

    discovered = pair.discover()
    if (
        discovered["host"]["scene"] != "testrun"
        or discovered["client"]["scene"] != "testrun"
    ):
        raise VerifyFailure("Steam friend pair is not in a shared test run")
    configure(pair)

    result: dict[str, Any] = {
        "pair": discovered,
        "fixture": {
            "path": str(flat.FIXTURE),
            "bytes": flat.FIXTURE.stat().st_size,
            "sha256": flat.EXPECTED_SHA256,
        },
        "staged_overrides": {
            "windows": verify_staged_fixture(host_instance),
            "proton": verify_staged_fixture(client_instance),
        },
    }
    result["manual_mode"] = {
        "windows": primary.set_manual_spawner_test_mode(HOST_ENDPOINT, True),
        "proton": primary.set_manual_spawner_test_mode(CLIENT_ENDPOINT, True),
    }
    for label, state in result["manual_mode"].items():
        if state.get("ok") != "true" or state.get("active") != "true":
            raise VerifyFailure(f"manual enemy mode is not active on {label}")
    result["manual_combat"] = primary.enable_manual_stock_spawner_combat()
    result["spawner_ready"] = {
        "windows": primary.wait_for_manual_spawner_ready(HOST_ENDPOINT, timeout),
        "proton": primary.wait_for_manual_spawner_ready(CLIENT_ENDPOINT, timeout),
    }
    result["cleanup"] = primary.cleanup_live_enemies()
    result["blank_arena"] = {
        "windows": flat.wait_for_blank_arena_census(HOST_ENDPOINT, timeout),
        "proton": flat.wait_for_blank_arena_census(CLIENT_ENDPOINT, timeout),
    }
    result["nav"] = {
        "windows": flat.nav_summary(
            HOST_ENDPOINT,
            timeout,
            expected_actor_count=0,
        ),
        "proton": flat.nav_summary(
            CLIENT_ENDPOINT,
            timeout,
            expected_actor_count=0,
        ),
    }
    for label, summary in result["nav"].items():
        actor_set = {
            "active_count": summary["replicated_actor_count"],
            "total_count": summary["replicated_actor_total_count"],
        }
        if actor_set != {"active_count": 0, "total_count": 0}:
            raise VerifyFailure(
                f"{label} flat Boneyard was not empty before manual spawning"
            )

    result["screenshots"] = {
        "windows": frame_capture.capture_game_backbuffer(
            HOST_ENDPOINT,
            HOST_SCREENSHOT,
            maximum_dominant_fraction=0.85,
        ),
        "proton": frame_capture.capture_game_backbuffer(
            CLIENT_ENDPOINT,
            CLIENT_SCREENSHOT,
            game_path_kind="proton",
            maximum_dominant_fraction=0.85,
        ),
    }

    host_state = local_sync.query(HOST_ENDPOINT)
    anchor = (float(host_state["player.x"]), float(host_state["player.y"]))
    result["clear_lane"] = primary.select_clear_kill_lane(
        anchor,
        pipe_name=HOST_ENDPOINT,
    )
    lane_x = float(result["clear_lane"]["x"])
    lane_y = float(result["clear_lane"]["y"])
    result["spawn"] = primary.spawn_one_enemy(
        lane_x,
        lane_y,
        setup_hp=40.0,
        freeze_on_spawn=True,
    )
    network_id = int(result["spawn"]["result"]["network_actor_id"])
    result["enemy_views"] = flat.wait_for_enemy_convergence(
        network_id,
        lane_x,
        lane_y,
        expected_hp=40.0,
        timeout=timeout,
    )
    result["summary"] = {
        "staged_fixture_matches": 2,
        "blank_arena_observers": 2,
        "scenery_objects": 0,
        "roads": 0,
        "fences": 0,
        "static_collision_circles": 0,
        "authoritative_enemies_verified": 1,
    }
    result["ok"] = True
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--host-instance",
        default=os.environ.get("SDMOD_STEAM_HOST_INSTANCE", "steam-host-gameplay12"),
    )
    parser.add_argument(
        "--client-instance",
        default=os.environ.get("SDMOD_STEAM_CLIENT_INSTANCE", "wsl-steam-client"),
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    pair = SteamFriendActivePair()
    result: dict[str, Any] = {"ok": False}
    return_code = 1
    try:
        result = run(pair, args.host_instance, args.client_instance, args.timeout)
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
