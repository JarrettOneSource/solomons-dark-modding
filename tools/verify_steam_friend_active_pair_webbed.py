#!/usr/bin/env python3
"""Verify genuine Spider Webbed behavior on an active Steam friend pair."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import traceback
from pathlib import Path
from typing import Any

import verify_multiplayer_primary_kill_stress as primary
import verify_multiplayer_webbed_status_sync as webbed
from multiplayer_webbed_status_harness import stop_stock_web_escape
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
from verify_local_multiplayer_sync import VerifyFailure
from verify_steam_friend_active_pair_progression import find_new_crash_artifacts


DEFAULT_OUTPUT = ROOT / "runtime/steam_friend_active_pair_webbed.json"


def stop_escape_inputs() -> dict[str, Any]:
    return {
        "host": stop_stock_web_escape(HOST_ENDPOINT),
        "client": stop_stock_web_escape(CLIENT_ENDPOINT),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    started_at = time.time()
    pair = SteamFriendActivePair()
    output: dict[str, Any] = {"ok": False}
    return_code = 1
    configured = False
    try:
        output["active_step"] = "discover_pair"
        output["pair"] = pair.discover()
        require_shared_test_run(output["pair"])
        context = configure_behavior_context(pair)
        configured = True

        output["active_step"] = "reset_quiet_arena"
        output["arena_reset"] = reset_quiet_arena()
        output["directions"] = {}
        for direction in context.webbed_directions:
            output["active_step"] = f"webbed.{direction.name}"
            direction_result: dict[str, Any] = {}
            output["directions"][direction.name] = direction_result
            webbed.run_direction(direction, args.timeout, direction_result)

        output["spiders_after"] = {
            name: {
                "host": webbed.query_run_enemy_by_network_id(
                    HOST_ENDPOINT,
                    result["spider"]["network_actor_id"],
                ),
                "client": webbed.query_run_enemy_by_network_id(
                    CLIENT_ENDPOINT,
                    result["spider"]["network_actor_id"],
                ),
            }
            for name, result in output["directions"].items()
        }
        output["active_step"] = "cleanup"
        output["escape_cleanup"] = stop_escape_inputs()
        output["enemy_cleanup"] = primary.cleanup_live_enemies()
        output["new_crash_artifacts"] = find_new_crash_artifacts(started_at)
        if output["new_crash_artifacts"]:
            raise VerifyFailure(
                "new crash artifacts appeared during the Steam Webbed test"
            )
        output.pop("active_step", None)
        output["ok"] = True
        return_code = 0
    except (VerifyFailure, subprocess.TimeoutExpired, ValueError, OSError) as exc:
        output["error"] = str(exc)
        output["error_type"] = type(exc).__name__
        output["traceback"] = traceback.format_exc()
        output["new_crash_artifacts"] = find_new_crash_artifacts(started_at)
    finally:
        if configured:
            if "escape_cleanup" not in output:
                try:
                    output["escape_cleanup"] = stop_escape_inputs()
                except (VerifyFailure, OSError) as cleanup_error:
                    output["escape_cleanup_error"] = str(cleanup_error)
            try:
                webbed.set_enemy_mode("park", timeout=5.0)
            except (VerifyFailure, OSError) as cleanup_error:
                output["enemy_park_error"] = str(cleanup_error)
            if "enemy_cleanup" not in output:
                try:
                    output["teardown_enemy_cleanup"] = (
                        primary.cleanup_live_enemies()
                    )
                except (VerifyFailure, OSError) as cleanup_error:
                    output["enemy_cleanup_error"] = str(cleanup_error)
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
                "directions": {
                    name: {
                        "owner_ticks": result.get("owner_active", {}).get(
                            "modifier_ticks"
                        ),
                        "owner_strength": result.get("owner_active", {}).get(
                            "modifier_strength"
                        ),
                        "observer_native_count": result.get(
                            "observer_active", {}
                        ).get("webbed_count"),
                        "observer_render_flags": result.get(
                            "observer_active", {}
                        ).get("actor_render_drive_flags"),
                    }
                    for name, result in output.get("directions", {}).items()
                },
                "new_crash_artifacts": output.get("new_crash_artifacts", []),
                "output": str(args.output),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
