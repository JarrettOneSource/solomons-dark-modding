#!/usr/bin/env python3
"""Verify persistent-skill behavior on a genuine Steam friend pair."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
import traceback
from pathlib import Path
from typing import Any

import multiplayer_persistent_status_harness as persistent_harness
import verify_multiplayer_firewalker_effect_sync as firewalker
import verify_multiplayer_focus_behavior_sync as focus
import verify_multiplayer_persistent_status_sync as persistent
import verify_multiplayer_regenerate_behavior_sync as regenerate
import verify_multiplayer_rush_behavior_sync as rush
import verify_player_health_death_sync as health
from steam_friend_active_pair import (
    CLIENT_ENDPOINT,
    HOST_ENDPOINT,
    ROOT,
    SteamFriendActivePair,
)
from steam_friend_behavior_context import disable_runtime_test_godmode
from verify_local_multiplayer_sync import VerifyFailure
from verify_steam_friend_active_pair_progression import (
    configure_verifiers,
    find_new_crash_artifacts,
)


DEFAULT_OUTPUT = ROOT / "runtime/steam_friend_active_pair_persistent_behavior.json"
HOST_INSTANCE = os.environ.get("SDMOD_STEAM_HOST_INSTANCE", "").strip()
CLIENT_INSTANCE = os.environ.get("SDMOD_STEAM_CLIENT_INSTANCE", "").strip()


def instance_log(instance: str, override_environment_variable: str) -> Path:
    override = os.environ.get(override_environment_variable, "").strip()
    if override:
        return Path(override)
    if not instance:
        raise VerifyFailure("both Steam instance environment variables are required")
    return (
        ROOT
        / "runtime/instances"
        / instance
        / "stage/.sdmod/logs/solomondarkmodloader.log"
    )


def configure(pair: SteamFriendActivePair) -> tuple[focus.Direction, focus.Direction]:
    configure_verifiers(pair)
    host_log = instance_log(HOST_INSTANCE, "SDMOD_STEAM_HOST_LOG_PATH")
    client_log = instance_log(CLIENT_INSTANCE, "SDMOD_STEAM_CLIENT_LOG_PATH")
    directions = (
        focus.Direction(
            "host_owned",
            "host",
            pair.host_participant_id,
            HOST_ENDPOINT,
            host_log,
            client_log,
        ),
        focus.Direction(
            "client_owned",
            "client",
            pair.client_participant_id,
            CLIENT_ENDPOINT,
            client_log,
            host_log,
        ),
    )
    replacements = {
        "HOST_ID": pair.host_participant_id,
        "CLIENT_ID": pair.client_participant_id,
        "HOST_PIPE": HOST_ENDPOINT,
        "CLIENT_PIPE": CLIENT_ENDPOINT,
        "HOST_LOG": host_log,
        "CLIENT_LOG": client_log,
        "DIRECTIONS": directions,
        "lua": pair.lua,
    }
    for module in (
        focus,
        persistent,
        persistent_harness,
        firewalker,
        regenerate,
        rush,
        health,
    ):
        for name, value in replacements.items():
            if hasattr(module, name):
                setattr(module, name, value)
    return directions


def acquire_persistent_skills(
    directions: tuple[focus.Direction, focus.Direction],
    timeout: float,
) -> dict[str, dict[str, dict[str, Any]]]:
    result: dict[str, dict[str, dict[str, Any]]] = {}
    for direction in directions:
        result[direction.name] = {
            label: focus.acquire_secondary_to_rank(
                direction,
                entry_row,
                1,
                timeout,
            )
            for label, entry_row, _ in persistent.SKILLS
        }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=25.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    started_at = time.time()
    pair = SteamFriendActivePair()
    output: dict[str, Any] = {"ok": False}
    return_code = 1
    try:
        output["pair"] = pair.discover()
        if any(
            side.get("scene") != "testrun"
            for side in output["pair"].values()
            if isinstance(side, dict) and "scene" in side
        ):
            raise VerifyFailure("Steam friend pair is not in a shared test run")

        directions = configure(pair)
        output["test_godmode"] = disable_runtime_test_godmode(pair)
        output["active_step"] = "combat_prelude"
        output["combat_prelude"] = focus.enable_unsuppressed_combat_prelude(
            args.timeout
        )
        output["post_run_progression_ready"] = (
            firewalker.wait_for_post_run_progression_ready(args.timeout)
        )
        output["resources"] = {
            direction.name: health.set_local_player_vitals(
                direction.source_pipe,
                500.0,
                500.0,
            )
            for direction in directions
        }

        output["active_step"] = "acquire_persistent_skills"
        acquisitions = acquire_persistent_skills(directions, args.timeout)
        output["acquisitions"] = acquisitions

        output["persistent_lifecycle"] = {}
        for direction in directions:
            output["active_step"] = f"persistent_lifecycle.{direction.name}"
            output["persistent_lifecycle"][direction.name] = (
                persistent.run_lifecycle(
                    direction,
                    acquisitions[direction.name],
                    args.timeout,
                )
            )

        output["firewalker"] = {}
        for direction in directions:
            output["active_step"] = f"firewalker.{direction.name}"
            output["firewalker"][direction.name] = firewalker.run_direction(
                direction,
                acquisitions[direction.name]["firewalker"],
                args.timeout,
            )

        output["regenerate"] = {}
        for direction in directions:
            output["active_step"] = f"regenerate.{direction.name}"
            output["regenerate"][direction.name] = regenerate.run_direction(
                direction,
                acquisitions[direction.name]["regenerate"],
                args.timeout,
            )

        output["new_crash_artifacts"] = find_new_crash_artifacts(started_at)
        if output["new_crash_artifacts"]:
            raise VerifyFailure("new crash artifacts appeared during persistent tests")
        output.pop("active_step", None)
        output["ok"] = True
        return_code = 0
    except (VerifyFailure, subprocess.TimeoutExpired, ValueError, OSError) as exc:
        output["error"] = str(exc)
        output["error_type"] = type(exc).__name__
        output["traceback"] = traceback.format_exc()
        output["new_crash_artifacts"] = find_new_crash_artifacts(started_at)
    finally:
        pair.close()
        output = pair.redact(output)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(output, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    print(
        json.dumps(
            {
                "ok": output.get("ok", False),
                "active_step": output.get("active_step"),
                "error": output.get("error"),
                "persistent_directions": sorted(
                    output.get("persistent_lifecycle", {}).keys()
                ),
                "firewalker_directions": sorted(
                    output.get("firewalker", {}).keys()
                ),
                "regenerate_directions": sorted(
                    output.get("regenerate", {}).keys()
                ),
                "output": str(args.output),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
